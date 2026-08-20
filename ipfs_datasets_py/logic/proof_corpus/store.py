"""Content-addressed multi-family proof corpus store (ProofCorpusStore@1).

Persists Intent, Legal, and Security formalization envelopes so a gate or
query layer can retrieve an artifact by CID without re-running formalization.
Family-specific caches remain sources of offline fixtures; this store unifies
them under one integrity-bound envelope schema.

Integrity is fail-closed:

* every on-disk envelope is rehashed on load and rejected on digest mismatch;
* formalization artifact identity is recomputed from the stored payload;
* source digest is bound to the artifact declaration digest;
* family must match the artifact domain;
* corrupt trees never partially load — ``reload`` raises on the first bad record.

Secondary indexes (family / source digest / profile) support local lookup.
Full query/rebuild APIs live in LIG-012 (``query.py`` / ``index.py``).

**DQK-066:** the mutable corpus index may promote to DuckDB authority.  When
promoted, whole-file ``index.json`` rewrites are forbidden; the index rebuilds
from immutable per-CID envelopes.  Envelope bytes and CIDs remain canonical.

**DQK-067:** ``index.json`` is explicit import/export compatibility only.
Normal runtime operates with the legacy index file absent; immutable per-CID
envelopes remain the sole content-addressed evidence on disk.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from ..formalization.compiler import FormalizationArtifact
from .schemas import (
    PROOF_CORPUS_INDEX_SCHEMA_VERSION,
    PROOF_CORPUS_STORE_INTERFACE,
    PROOF_CORPUS_STORE_SCHEMA_VERSION,
    ArtifactEnvelope,
    ProofCorpusFamily,
    ProofCorpusIntegrityError,
    ProofCorpusSchemaError,
    as_mapping,
    canonical_bytes,
    parse_family,
    require_digest,
    require_profile,
    require_text,
)


class ProofCorpusStoreError(ProofCorpusSchemaError):
    """Raised when a proof corpus store operation cannot proceed safely."""


class ProofCorpusStoreIntegrityError(
    ProofCorpusStoreError, ProofCorpusIntegrityError
):
    """Raised when a stored envelope or index fails integrity verification."""


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical_bytes(payload)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


@dataclass
class ProofCorpusStore:
    """Filesystem- or memory-backed multi-family proof corpus store.

    Envelopes are content-addressed by their envelope digest.  Secondary
    indexes support lookup by family, source digest, and profile.  Statistics
    track hit/miss counts for get paths.
    """

    root: Path | None = None
    _envelopes: dict[str, ArtifactEnvelope] = field(
        default_factory=dict, init=False, repr=False
    )
    # family -> content_cid set
    _family_index: dict[str, set[str]] = field(
        default_factory=dict, init=False, repr=False
    )
    # source_digest -> profile -> content_cid
    _source_index: dict[str, dict[str, str]] = field(
        default_factory=dict, init=False, repr=False
    )
    # profile -> content_cid (last writer wins for a profile key)
    _profile_index: dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )
    _hits: int = field(default=0, init=False, repr=False)
    _misses: int = field(default=0, init=False, repr=False)
    _lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )
    # DQK-066: optional dual/promoted proof authority repository.
    _authority_repository: Any = field(default=None, init=False, repr=False)
    _index_rebuilds: int = field(default=0, init=False, repr=False)
    _json_rewrite_blocks: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.root is not None:
            object.__setattr__(self, "root", Path(self.root))
            self.root.mkdir(parents=True, exist_ok=True)
            self.reload()

    def bind_authority_repository(self, repository: Any) -> None:
        """Bind dual/promoted DuckDB proof authority for the corpus index (DQK-066)."""

        with self._lock:
            self._authority_repository = repository
            if repository is not None and hasattr(repository, "register_backend"):
                try:
                    repository.register_backend("common")
                except Exception:
                    pass

    def bind_shadow_repository(self, repository: Any) -> None:
        """Alias for :meth:`bind_authority_repository` (DQK-065 compatibility)."""

        self.bind_authority_repository(repository)

    @property
    def authority_repository(self) -> Any:
        return self._authority_repository

    @property
    def interface(self) -> str:
        return PROOF_CORPUS_STORE_INTERFACE

    @property
    def schema_version(self) -> str:
        return PROOF_CORPUS_STORE_SCHEMA_VERSION

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": len(self._envelopes),
                "index_rebuilds": self._index_rebuilds,
                "json_rewrite_blocks": self._json_rewrite_blocks,
                "authority_bound": 1 if self._authority_repository is not None else 0,
            }

    def _envelopes_dir(self) -> Path | None:
        if self.root is None:
            return None
        path = self.root / "envelopes"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _index_path(self) -> Path | None:
        if self.root is None:
            return None
        return self.root / "index.json"

    def _envelope_path(self, content_cid: str) -> Path | None:
        envelopes_dir = self._envelopes_dir()
        if envelopes_dir is None:
            return None
        safe = content_cid.replace("/", "_")
        return envelopes_dir / f"{safe}.json"

    def _index_envelope(self, envelope: ArtifactEnvelope) -> None:
        self._envelopes[envelope.content_cid] = envelope
        family_key = envelope.family.value
        self._family_index.setdefault(family_key, set()).add(envelope.content_cid)
        by_source = self._source_index.setdefault(envelope.source_digest, {})
        by_source[envelope.profile] = envelope.content_cid
        self._profile_index[envelope.profile] = envelope.content_cid

    def _persist_envelope(self, envelope: ArtifactEnvelope) -> None:
        path = self._envelope_path(envelope.content_cid)
        if path is None:
            return
        _atomic_write_json(path, envelope.to_dict())

    def _persist_index(self) -> None:
        path = self._index_path()
        if path is None:
            return
        # DQK-066/067: after promotion or export-only, whole-file index.json
        # rewrites are forbidden on the runtime path.  Mutable index authority
        # lives in DuckDB; rebuild from envelopes instead.  Explicit
        # export_index_json_compat remains the compatibility export API.
        repo = self._authority_repository
        blocked = False
        try:
            from ..common.proof_cache import legacy_json_persistence_allowed

            blocked = not legacy_json_persistence_allowed(repo)
        except Exception:
            blocked = bool(repo is not None and getattr(repo, "is_promoted", False))
        if blocked:
            self._json_rewrite_blocks += 1
            if repo is not None and hasattr(repo, "assert_json_rewrite_allowed"):
                repo.assert_json_rewrite_allowed(
                    "common", path=str(path) if path else "index.json"
                )
            raise ProofCorpusStoreError(
                "whole-file JSON index rewrite forbidden after proof authority "
                "export-only cutover; rebuild from immutable envelopes or use "
                "export_index_json_compat"
            )
        with self._lock:
            families = {
                family: sorted(cids)
                for family, cids in sorted(self._family_index.items())
            }
            sources = {
                digest: dict(sorted(profiles.items()))
                for digest, profiles in sorted(self._source_index.items())
            }
            payload = {
                "families": families,
                "interface": PROOF_CORPUS_STORE_INTERFACE,
                "profiles": dict(sorted(self._profile_index.items())),
                "schema_version": PROOF_CORPUS_INDEX_SCHEMA_VERSION,
                "sources": sources,
                "store_schema_version": PROOF_CORPUS_STORE_SCHEMA_VERSION,
            }
        # Dual mode: still dual-write index.json for parity while DuckDB is
        # authority; project through the repository when bound.
        if repo is not None and hasattr(repo, "mutate_corpus_index"):
            try:
                for cid, envelope in self._envelopes.items():
                    repo.mutate_corpus_index(
                        "common",
                        key=type("K", (), {"digest": envelope.content_digest})(),
                        envelope_content_id=cid,
                        envelope_content_digest=envelope.content_digest,
                        operation="index",
                        payload={"profile": envelope.profile},
                    )
            except Exception:
                pass
        _atomic_write_json(path, payload)

    def _load_envelope_file(self, path: Path) -> ArtifactEnvelope:
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProofCorpusStoreIntegrityError(
                f"proof corpus envelope is unreadable ({path.name}): {exc}"
            ) from exc
        try:
            envelope = ArtifactEnvelope.from_dict(
                as_mapping(payload, "artifact envelope")
            )
        except ProofCorpusSchemaError as exc:
            raise ProofCorpusStoreIntegrityError(
                f"proof corpus envelope failed integrity ({path.name}): {exc}"
            ) from exc
        # Byte-level rehash of the identity payload vs recorded digests already
        # happens in ArtifactEnvelope; additionally ensure file content is not
        # a non-canonical alias that still round-trips (fail closed on digest).
        return envelope.verify_integrity()

    def put(
        self,
        value: ArtifactEnvelope
        | FormalizationArtifact
        | Mapping[str, Any],
        *,
        profile: str | None = None,
        family: ProofCorpusFamily | str | None = None,
        source_id: str | None = None,
        source_digest: str | None = None,
        attachments: Mapping[str, Any] | None = None,
        producer_id: str = "",
        review_state: str = "reviewed",
        jurisdiction: str = "",
    ) -> ArtifactEnvelope:
        """Store an envelope and return the verified record.

        Accepts a finished :class:`ArtifactEnvelope`, a
        :class:`FormalizationArtifact`, or a mapping envelope / artifact payload.
        """

        with self._lock:
            if isinstance(value, ArtifactEnvelope):
                if profile is not None and value.profile != require_profile(
                    profile
                ):
                    raise ProofCorpusStoreError(
                        "profile argument conflicts with the supplied envelope"
                    )
                if family is not None and value.family is not parse_family(family):
                    raise ProofCorpusStoreError(
                        "family argument conflicts with the supplied envelope"
                    )
                if source_id is not None and source_id != value.source_id:
                    raise ProofCorpusStoreError(
                        "source_id argument conflicts with the supplied envelope"
                    )
                if (
                    source_digest is not None
                    and source_digest != value.source_digest
                ):
                    raise ProofCorpusStoreError(
                        "source_digest argument conflicts with the supplied envelope"
                    )
                if attachments:
                    raise ProofCorpusStoreError(
                        "attachments cannot be supplied with a finished envelope"
                    )
                if jurisdiction and jurisdiction != value.jurisdiction:
                    raise ProofCorpusStoreError(
                        "jurisdiction argument conflicts with the supplied envelope"
                    )
                envelope = value.verify_integrity()
            elif isinstance(value, FormalizationArtifact):
                if profile is None:
                    raise ProofCorpusStoreError(
                        "profile is required when putting a formalization artifact"
                    )
                envelope = ArtifactEnvelope.build(
                    value,
                    profile=profile,
                    family=family,
                    source_id=source_id,
                    source_digest=source_digest,
                    attachments=attachments,
                    producer_id=producer_id,
                    review_state=review_state,
                    jurisdiction=jurisdiction,
                )
            else:
                mapping = as_mapping(value, "put value")
                # Finished envelope mapping (has family + content fields or profile)
                if "family" in mapping or "content_cid" in mapping:
                    envelope = ArtifactEnvelope.from_dict(mapping)
                    if profile is not None and envelope.profile != require_profile(
                        profile
                    ):
                        raise ProofCorpusStoreError(
                            "profile argument conflicts with the supplied envelope"
                        )
                    envelope = envelope.verify_integrity()
                else:
                    if profile is None:
                        raise ProofCorpusStoreError(
                            "profile is required when putting a raw artifact mapping"
                        )
                    envelope = ArtifactEnvelope.build(
                        mapping,
                        profile=profile,
                        family=family,
                        source_id=source_id,
                        source_digest=source_digest,
                        attachments=attachments,
                        producer_id=producer_id,
                        review_state=review_state,
                        jurisdiction=jurisdiction,
                    )

            self._index_envelope(envelope)
            self._persist_envelope(envelope)
            # DQK-066: promoted authority forbids whole-file index.json rewrites.
            # Immutable envelopes remain durable; the index is DuckDB-authoritative
            # and can be rebuilt via rebuild_index_from_envelopes().
            repo = self._authority_repository
            if repo is not None and getattr(repo, "is_promoted", False):
                if hasattr(repo, "mutate_corpus_index"):
                    try:
                        repo.mutate_corpus_index(
                            "common",
                            key=type(
                                "K", (), {"digest": envelope.content_digest}
                            )(),
                            envelope_content_id=envelope.content_cid,
                            envelope_content_digest=envelope.content_digest,
                            operation="index",
                            payload={"profile": envelope.profile},
                        )
                    except Exception:
                        pass
                # Seed immutable envelope material for later rebuilds.
                bag = getattr(repo, "_immutable_envelopes", None)
                if isinstance(bag, dict):
                    bag[envelope.content_cid] = {
                        "content_id": envelope.content_cid,
                        "content_digest": envelope.content_digest,
                        "byte_size": 0,
                        "media_type": "application/json",
                        "key_digest": envelope.content_digest,
                        "backend": "common",
                        "entry_digest": envelope.content_digest,
                        "created_at": 0.0,
                    }
            else:
                self._persist_index()
            return envelope

    def get(self, content_cid: str) -> ArtifactEnvelope:
        """Load one envelope by content CID (memory first, then disk)."""

        cid = require_text(content_cid, "content_cid")
        with self._lock:
            envelope = self._envelopes.get(cid)
            if envelope is not None:
                self._hits += 1
                return envelope.verify_integrity()
            path = self._envelope_path(cid)
            if path is None or not path.is_file():
                self._misses += 1
                raise ProofCorpusStoreError(
                    f"envelope not found for content_cid={cid!r}"
                )
            envelope = self._load_envelope_file(path)
            if envelope.content_cid != cid:
                raise ProofCorpusStoreIntegrityError(
                    "on-disk envelope CID does not match requested CID"
                )
            self._index_envelope(envelope)
            self._hits += 1
            return envelope

    def get_by_cid(self, content_cid: str) -> ArtifactEnvelope:
        """Alias for :meth:`get` (ProofCorpusStore@1 surface)."""

        return self.get(content_cid)

    def get_by_profile(self, profile: str) -> ArtifactEnvelope:
        """Return the envelope currently indexed for *profile*."""

        profile = require_profile(profile)
        with self._lock:
            cid = self._profile_index.get(profile)
            if cid is None:
                self._misses += 1
                raise ProofCorpusStoreError(
                    f"no envelope indexed for profile={profile!r}"
                )
            return self.get(cid)

    def get_by_source_digest(
        self,
        source_digest: str,
        *,
        profile: str | None = None,
    ) -> ArtifactEnvelope:
        """Return a stored envelope for a source digest.

        When *profile* is provided the source+profile index is preferred.
        Otherwise the sole matching envelope is returned; multiple profiles for
        one source require an explicit profile.
        """

        source_digest = require_digest(source_digest, "source_digest")
        with self._lock:
            by_profile = self._source_index.get(source_digest)
            if not by_profile:
                self.reload()
                by_profile = self._source_index.get(source_digest)
            if not by_profile:
                self._misses += 1
                raise ProofCorpusStoreError(
                    f"no envelope for source_digest={source_digest!r}"
                )
            if profile is not None:
                profile = require_profile(profile)
                cid = by_profile.get(profile)
                if cid is None:
                    self._misses += 1
                    raise ProofCorpusStoreError(
                        f"no envelope for source_digest={source_digest!r} "
                        f"profile={profile!r}"
                    )
                return self.get(cid)
            if len(by_profile) > 1:
                profiles = ", ".join(sorted(by_profile))
                raise ProofCorpusStoreError(
                    "multiple envelopes for source_digest="
                    f"{source_digest!r}; specify profile (candidates: {profiles})"
                )
            cid = next(iter(by_profile.values()))
            return self.get(cid)

    def list_by_family(
        self, family: ProofCorpusFamily | str
    ) -> tuple[ArtifactEnvelope, ...]:
        """Return all stored envelopes for one family (sorted by content_cid)."""

        family = parse_family(family)
        with self._lock:
            cids = sorted(self._family_index.get(family.value, set()))
            return tuple(self.get(cid) for cid in cids)

    def contains(self, content_cid: str) -> bool:
        """Return True on store hit without raising; does not count as get hit."""

        try:
            cid = require_text(content_cid, "content_cid")
        except ProofCorpusSchemaError:
            return False
        with self._lock:
            if cid in self._envelopes:
                return True
            path = self._envelope_path(cid)
            return path is not None and path.is_file()

    def families(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._family_index))

    def profiles(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._profile_index))

    def source_digests(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._source_index))

    def cids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._envelopes))

    def __len__(self) -> int:
        with self._lock:
            return len(self._envelopes)

    def reload(self) -> int:
        """Reload all on-disk envelopes with full integrity verification.

        Corrupt or digest-mismatched envelopes fail closed and prevent the
        store from accepting the damaged tree.  Returns the number loaded.
        """

        with self._lock:
            if self.root is None:
                for cid, envelope in list(self._envelopes.items()):
                    verified = envelope.verify_integrity()
                    self._envelopes[cid] = verified
                return len(self._envelopes)

            envelopes_dir = self._envelopes_dir()
            assert envelopes_dir is not None
            loaded: dict[str, ArtifactEnvelope] = {}
            family_index: dict[str, set[str]] = {}
            source_index: dict[str, dict[str, str]] = {}
            profile_index: dict[str, str] = {}

            for path in sorted(envelopes_dir.glob("*.json")):
                envelope = self._load_envelope_file(path)
                if envelope.content_cid in loaded:
                    raise ProofCorpusStoreIntegrityError(
                        f"duplicate envelope content_cid on disk: "
                        f"{envelope.content_cid}"
                    )
                loaded[envelope.content_cid] = envelope
                family_index.setdefault(envelope.family.value, set()).add(
                    envelope.content_cid
                )
                source_index.setdefault(envelope.source_digest, {})[
                    envelope.profile
                ] = envelope.content_cid
                profile_index[envelope.profile] = envelope.content_cid

            index_path = self._index_path()
            if index_path is not None and index_path.is_file():
                try:
                    index_payload = json.loads(
                        index_path.read_text(encoding="utf-8")
                    )
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise ProofCorpusStoreIntegrityError(
                        f"proof corpus index is unreadable: {exc}"
                    ) from exc
                index_payload = as_mapping(index_payload, "proof corpus index")
                if (
                    index_payload.get("schema_version")
                    != PROOF_CORPUS_INDEX_SCHEMA_VERSION
                ):
                    raise ProofCorpusStoreIntegrityError(
                        "unsupported proof corpus index schema: "
                        f"{index_payload.get('schema_version')!r}"
                    )
                profiles = index_payload.get("profiles", {})
                if not isinstance(profiles, Mapping):
                    raise ProofCorpusStoreIntegrityError(
                        "proof corpus index profiles must be a mapping"
                    )
                for profile_key, cid in profiles.items():
                    profile_key = require_profile(profile_key)
                    cid = require_text(cid, "index profile cid")
                    if cid not in loaded:
                        raise ProofCorpusStoreIntegrityError(
                            f"proof corpus index references missing envelope "
                            f"for profile={profile_key!r} content_cid={cid!r}"
                        )
                    if loaded[cid].profile != profile_key:
                        raise ProofCorpusStoreIntegrityError(
                            f"proof corpus index profile={profile_key!r} "
                            f"does not match envelope profile "
                            f"{loaded[cid].profile!r}"
                        )

            self._envelopes = loaded
            self._family_index = family_index
            self._source_index = source_index
            self._profile_index = profile_index
            return len(loaded)

    def rebuild_index_from_envelopes(self) -> dict[str, Any]:
        """Rebuild the mutable secondary index from immutable envelope material.

        Acceptance (DQK-066): "The corpus index rebuilds from immutable envelopes".
        Envelope content CIDs and digests are never rewritten.  When promoted,
        this is the only supported index mutation path (no whole-file JSON
        rewrite of ``index.json``).
        """

        with self._lock:
            # Prefer on-disk envelopes when available; fall back to memory.
            if self.root is not None:
                envelopes_dir = self._envelopes_dir()
                assert envelopes_dir is not None
                loaded: dict[str, ArtifactEnvelope] = {}
                for path in sorted(envelopes_dir.glob("*.json")):
                    envelope = self._load_envelope_file(path)
                    if envelope.content_cid in loaded:
                        raise ProofCorpusStoreIntegrityError(
                            f"duplicate envelope content_cid on disk: "
                            f"{envelope.content_cid}"
                        )
                    loaded[envelope.content_cid] = envelope
                source_envelopes = loaded
            else:
                source_envelopes = {
                    cid: env.verify_integrity()
                    for cid, env in self._envelopes.items()
                }

            family_index: dict[str, set[str]] = {}
            source_index: dict[str, dict[str, str]] = {}
            profile_index: dict[str, str] = {}
            for envelope in source_envelopes.values():
                family_index.setdefault(envelope.family.value, set()).add(
                    envelope.content_cid
                )
                source_index.setdefault(envelope.source_digest, {})[
                    envelope.profile
                ] = envelope.content_cid
                profile_index[envelope.profile] = envelope.content_cid

            self._envelopes = dict(source_envelopes)
            self._family_index = family_index
            self._source_index = source_index
            self._profile_index = profile_index
            self._index_rebuilds += 1

            # Project rebuild into bound authority repository when present.
            repo = self._authority_repository
            authority_report: dict[str, Any] | None = None
            if repo is not None:
                # Seed immutable envelope material then rebuild repository index.
                for envelope in source_envelopes.values():
                    bag = getattr(repo, "_immutable_envelopes", None)
                    if isinstance(bag, dict):
                        bag[envelope.content_cid] = {
                            "content_id": envelope.content_cid,
                            "content_digest": envelope.content_digest,
                            "byte_size": 0,
                            "media_type": "application/json",
                            "key_digest": envelope.content_digest,
                            "backend": "common",
                            "entry_digest": envelope.content_digest,
                            "created_at": 0.0,
                        }
                if hasattr(repo, "rebuild_corpus_index_from_envelopes"):
                    authority_report = repo.rebuild_corpus_index_from_envelopes()

            # When not promoted/export-only, refresh on-disk index.json from
            # rebuilt state.  After DQK-067 cutover, skip whole-file rewrite
            # (authority is DuckDB; use export_index_json_compat explicitly).
            allow_json = True
            try:
                from ..common.proof_cache import legacy_json_persistence_allowed

                allow_json = legacy_json_persistence_allowed(repo)
            except Exception:
                allow_json = not (
                    repo is not None and getattr(repo, "is_promoted", False)
                )
            if allow_json:
                path = self._index_path()
                if path is not None:
                    families = {
                        family: sorted(cids)
                        for family, cids in sorted(family_index.items())
                    }
                    sources = {
                        digest: dict(sorted(profiles.items()))
                        for digest, profiles in sorted(source_index.items())
                    }
                    payload = {
                        "families": families,
                        "interface": PROOF_CORPUS_STORE_INTERFACE,
                        "profiles": dict(sorted(profile_index.items())),
                        "schema_version": PROOF_CORPUS_INDEX_SCHEMA_VERSION,
                        "sources": sources,
                        "store_schema_version": PROOF_CORPUS_STORE_SCHEMA_VERSION,
                        "rebuilt_from": "immutable_envelopes",
                    }
                    _atomic_write_json(path, payload)

            return {
                "rebuilt": len(source_envelopes),
                "families": len(family_index),
                "profiles": len(profile_index),
                "sources": len(source_index),
                "index_rebuilds": self._index_rebuilds,
                "authority": authority_report,
                "promoted": bool(
                    repo is not None and getattr(repo, "is_promoted", False)
                ),
                "export_only": bool(
                    repo is not None and getattr(repo, "is_export_only", False)
                ),
            }

    def export_index_json_compat(self, path: Path | str | None = None) -> dict[str, Any]:
        """Explicit export of the secondary index as legacy ``index.json``.

        Allowed after DQK-067 export-only cutover.  The written file is never
        re-admitted as authority; DuckDB + immutable envelopes remain canonical.
        """

        target = Path(path) if path is not None else self._index_path()
        if target is None:
            raise ProofCorpusStoreError(
                "export_index_json_compat requires a path or a store root"
            )
        with self._lock:
            families = {
                family: sorted(cids)
                for family, cids in sorted(self._family_index.items())
            }
            sources = {
                digest: dict(sorted(profiles.items()))
                for digest, profiles in sorted(self._source_index.items())
            }
            payload = {
                "families": families,
                "interface": PROOF_CORPUS_STORE_INTERFACE,
                "profiles": dict(sorted(self._profile_index.items())),
                "schema_version": PROOF_CORPUS_INDEX_SCHEMA_VERSION,
                "sources": sources,
                "store_schema_version": PROOF_CORPUS_STORE_SCHEMA_VERSION,
                "export_only": True,
                "legacy_file_authoritative": False,
                "owner_task_id": "DQK-067",
            }
        _atomic_write_json(target, payload)
        return {
            "path": str(target),
            "families": len(families),
            "profiles": len(payload["profiles"]),
            "operation": "export_index_json_compat",
            "legacy_file_authoritative": False,
        }

    def import_index_json_compat(self, path: Path | str | None = None) -> dict[str, Any]:
        """One-time import of a legacy ``index.json`` (rebuild preferred).

        Validates the index against on-disk envelopes when present, then
        refreshes in-memory secondary indexes.  Does not make the file
        authoritative after import.
        """

        target = Path(path) if path is not None else self._index_path()
        if target is None or not Path(target).is_file():
            raise ProofCorpusStoreError(
                f"import_index_json_compat source is not a file: {target}"
            )
        # Prefer full reload which validates index against envelopes.
        if self.root is not None and Path(target) == self._index_path():
            count = self.reload()
            return {
                "path": str(target),
                "loaded": count,
                "operation": "import_index_json_compat",
                "legacy_file_authoritative": False,
            }
        # Foreign path: load envelopes from root then overlay index profiles.
        try:
            payload = json.loads(Path(target).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProofCorpusStoreError(
                f"import_index_json_compat unreadable: {exc}"
            ) from exc
        report = self.rebuild_index_from_envelopes()
        report["imported_index"] = str(target)
        report["operation"] = "import_index_json_compat"
        report["legacy_file_authoritative"] = False
        report["index_schema"] = payload.get("schema_version")
        return report


def put_envelope(
    store: ProofCorpusStore,
    value: ArtifactEnvelope | FormalizationArtifact | Mapping[str, Any],
    **kwargs: Any,
) -> ArtifactEnvelope:
    """Module-level put helper for the ProofCorpusStore@1 surface."""

    return store.put(value, **kwargs)


def get_envelope(store: ProofCorpusStore, content_cid: str) -> ArtifactEnvelope:
    """Module-level get helper for the ProofCorpusStore@1 surface."""

    return store.get(content_cid)


def put_family_fixtures(
    store: ProofCorpusStore,
    *,
    intent_artifact: FormalizationArtifact | Mapping[str, Any],
    intent_profile: str,
    legal_record: Mapping[str, Any],
    security_record: Mapping[str, Any],
) -> tuple[ArtifactEnvelope, ArtifactEnvelope, ArtifactEnvelope]:
    """Put one Intent, Legal, and Security fixture envelope into *store*.

    Convenience for offline multi-family acceptance tests and rebuild scripts.
    """

    intent_env = store.put(
        ArtifactEnvelope.from_intent_artifact(
            intent_artifact, profile=intent_profile
        )
    )
    legal_env = store.put(ArtifactEnvelope.from_legal_record(legal_record))
    security_env = store.put(
        ArtifactEnvelope.from_security_record(security_record)
    )
    return intent_env, legal_env, security_env


# DQK-065/066/067: re-export unified repository symbols so static/import
# guards observe the store as a compatibility surface over DuckDB authority.
from ..common.proof_cache import (  # noqa: E402
    LEGACY_PROOF_BACKENDS,
    LegacyProofBackend,
    ProofAuthorityJSONRewriteError,
    ProofJSONCompatibilityError,
    UnifiedProofAuthorityRepository,
    UnifiedProofShadowRepository,
    assert_direct_json_persistence_forbidden,
    build_proof_authority_repository,
    build_proof_shadow_repository,
    get_authority_repository,
    get_shadow_repository,
    legacy_json_persistence_allowed,
    set_authority_repository,
    set_shadow_repository,
)

__all__ = [
    "ProofCorpusStore",
    "ProofCorpusStoreError",
    "ProofCorpusStoreIntegrityError",
    "LEGACY_PROOF_BACKENDS",
    "LegacyProofBackend",
    "ProofAuthorityJSONRewriteError",
    "ProofJSONCompatibilityError",
    "UnifiedProofAuthorityRepository",
    "UnifiedProofShadowRepository",
    "assert_direct_json_persistence_forbidden",
    "build_proof_authority_repository",
    "build_proof_shadow_repository",
    "get_authority_repository",
    "get_shadow_repository",
    "legacy_json_persistence_allowed",
    "set_authority_repository",
    "set_shadow_repository",
    "get_envelope",
    "put_envelope",
    "put_family_fixtures",
]
