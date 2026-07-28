"""Rebuildable secondary indexes for the proof corpus (LIG-012).

Envelopes remain authoritative.  Indexes are derived projections over stored
envelopes and may be discarded and rebuilt without changing identity or
integrity of any envelope.

Wire shape reuses ``proof-corpus-index/v1`` for the store-compatible projection
(families / sources / profiles) and extends it with obligation digests so the
query layer can answer ``list_constraints_for_obligation`` without scanning.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from .schemas import (
    PROOF_CORPUS_INDEX_SCHEMA_VERSION,
    PROOF_CORPUS_STORE_INTERFACE,
    PROOF_CORPUS_STORE_SCHEMA_VERSION,
    ArtifactEnvelope,
    ProofCorpusSchemaError,
    as_mapping,
    canonical_bytes,
    parse_family,
    require_digest,
    require_profile,
    require_text,
)
from .store import ProofCorpusStore

# Bare SHA-256 hex (ProofObligation.digest); sha256: prefix is stripped on input.
_HEX64_RE: Final = re.compile(r"^[0-9a-f]{64}$")

PROOF_CORPUS_INDEX_FILENAME: Final = "index.json"
PROOF_CORPUS_SECONDARY_INDEX_FILENAME: Final = "secondary_index.json"


class ProofCorpusIndexError(ProofCorpusSchemaError):
    """Raised when a secondary index cannot be built, loaded, or verified."""


def normalize_obligation_digest(value: Any) -> str:
    """Normalize an obligation digest to lowercase bare 64-char hex.

    :class:`~ipfs_datasets_py.logic.formalization.compiler.ProofObligation`
    digests are bare hex.  Callers may also pass ``sha256:<hex>``; both forms
    are accepted and collapsed to bare hex for stable index keys.
    """

    text = require_text(value, "obligation_digest").lower()
    if text.startswith("sha256:"):
        text = text.removeprefix("sha256:")
    if not _HEX64_RE.fullmatch(text):
        raise ProofCorpusIndexError(
            "obligation_digest must be a 64-char lowercase hex digest "
            "(optionally prefixed with sha256:)"
        )
    return text


def _require_obligation_id(value: Any) -> str:
    return require_text(value, "obligation_id")


def _obligation_entries(
    envelope: ArtifactEnvelope,
) -> tuple[tuple[str, str], ...]:
    """Return ``(obligation_digest, obligation_id)`` pairs for *envelope*."""

    artifact = envelope.formalization_artifact()
    pairs: list[tuple[str, str]] = []
    for obligation in artifact.proof_obligations:
        digest = normalize_obligation_digest(obligation.digest)
        pairs.append((digest, require_text(obligation.obligation_id, "obligation_id")))
    # Deterministic order for rebuild stability independent of artifact sort.
    pairs.sort(key=lambda item: (item[0], item[1]))
    return tuple(pairs)


def _sorted_unique(values: Iterable[str]) -> list[str]:
    return sorted(set(values))


@dataclass
class ProofCorpusIndex:
    """Deterministic secondary index rebuilt solely from envelopes.

    Store-compatible fields (``families``, ``sources``, ``profiles``) match the
    on-disk projection written by :class:`ProofCorpusStore`.  Obligation maps
    are LIG-012 extensions used by :class:`~.query.ProofCorpusQuery`.
    """

    schema_version: str = PROOF_CORPUS_INDEX_SCHEMA_VERSION
    interface: str = PROOF_CORPUS_STORE_INTERFACE
    store_schema_version: str = PROOF_CORPUS_STORE_SCHEMA_VERSION
    # family -> sorted content_cid list
    families: dict[str, list[str]] = field(default_factory=dict)
    # source_digest -> profile -> content_cid
    sources: dict[str, dict[str, str]] = field(default_factory=dict)
    # profile -> content_cid (last writer wins; build uses sorted CID order)
    profiles: dict[str, str] = field(default_factory=dict)
    # obligation_digest (bare hex) -> sorted content_cid list
    obligations: dict[str, list[str]] = field(default_factory=dict)
    # obligation_id -> sorted content_cid list
    obligation_ids: dict[str, list[str]] = field(default_factory=dict)
    # content_cid -> sorted obligation digests (reverse map for rebuild checks)
    envelope_obligations: dict[str, list[str]] = field(default_factory=dict)
    _lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )

    # ------------------------------------------------------------------
    # Construction / rebuild
    # ------------------------------------------------------------------

    @classmethod
    def empty(cls) -> "ProofCorpusIndex":
        """Return an empty index with pinned schema constants."""

        return cls()

    @classmethod
    def build(
        cls,
        envelopes: Sequence[ArtifactEnvelope] | Iterable[ArtifactEnvelope],
    ) -> "ProofCorpusIndex":
        """Build a complete secondary index from verified envelopes.

        Envelope order does not affect the result: indexing sorts by
        ``content_cid`` before applying last-writer-wins profile maps so
        rebuilds are byte-stable for a fixed envelope set.
        """

        verified: list[ArtifactEnvelope] = []
        seen: set[str] = set()
        for item in envelopes:
            if not isinstance(item, ArtifactEnvelope):
                raise ProofCorpusIndexError(
                    "index build requires ArtifactEnvelope instances"
                )
            envelope = item.verify_integrity()
            if envelope.content_cid in seen:
                raise ProofCorpusIndexError(
                    f"duplicate envelope content_cid during index build: "
                    f"{envelope.content_cid}"
                )
            seen.add(envelope.content_cid)
            verified.append(envelope)

        verified.sort(key=lambda env: env.content_cid)

        families: dict[str, list[str]] = {}
        sources: dict[str, dict[str, str]] = {}
        profiles: dict[str, str] = {}
        obligations: dict[str, list[str]] = {}
        obligation_ids: dict[str, list[str]] = {}
        envelope_obligations: dict[str, list[str]] = {}

        for envelope in verified:
            cid = envelope.content_cid
            family_key = envelope.family.value
            families.setdefault(family_key, []).append(cid)

            by_source = sources.setdefault(envelope.source_digest, {})
            by_source[envelope.profile] = cid
            # Last writer in sorted-CID order wins for a bare profile key,
            # matching ProofCorpusStore._index_envelope behaviour.
            profiles[envelope.profile] = cid

            digests_for_envelope: list[str] = []
            for digest, obligation_id in _obligation_entries(envelope):
                obligations.setdefault(digest, []).append(cid)
                obligation_ids.setdefault(obligation_id, []).append(cid)
                digests_for_envelope.append(digest)
            envelope_obligations[cid] = _sorted_unique(digests_for_envelope)

        # Normalize map values to sorted unique lists / sorted keys.
        families = {
            family: _sorted_unique(cids)
            for family, cids in sorted(families.items())
        }
        sources = {
            digest: dict(sorted(profiles_map.items()))
            for digest, profiles_map in sorted(sources.items())
        }
        profiles = dict(sorted(profiles.items()))
        obligations = {
            digest: _sorted_unique(cids)
            for digest, cids in sorted(obligations.items())
        }
        obligation_ids = {
            oid: _sorted_unique(cids)
            for oid, cids in sorted(obligation_ids.items())
        }
        envelope_obligations = {
            cid: list(digests)
            for cid, digests in sorted(envelope_obligations.items())
        }

        return cls(
            families=families,
            sources=sources,
            profiles=profiles,
            obligations=obligations,
            obligation_ids=obligation_ids,
            envelope_obligations=envelope_obligations,
        )

    @classmethod
    def from_store(cls, store: ProofCorpusStore) -> "ProofCorpusIndex":
        """Rebuild an index by loading every envelope from *store*."""

        if not isinstance(store, ProofCorpusStore):
            raise ProofCorpusIndexError(
                "from_store requires a ProofCorpusStore instance"
            )
        envelopes: list[ArtifactEnvelope] = []
        for cid in store.cids():
            envelopes.append(store.get(cid))
        # Also discover any on-disk envelopes not yet in the memory map by
        # reloading when a root is configured (store.reload is fail-closed).
        if store.root is not None:
            store.reload()
            envelopes = [store.get(cid) for cid in store.cids()]
        return cls.build(envelopes)

    def rebuild_from_store(self, store: ProofCorpusStore) -> "ProofCorpusIndex":
        """Replace this index in place with a rebuild from *store*."""

        rebuilt = self.from_store(store)
        with self._lock:
            self.schema_version = rebuilt.schema_version
            self.interface = rebuilt.interface
            self.store_schema_version = rebuilt.store_schema_version
            self.families = rebuilt.families
            self.sources = rebuilt.sources
            self.profiles = rebuilt.profiles
            self.obligations = rebuilt.obligations
            self.obligation_ids = rebuilt.obligation_ids
            self.envelope_obligations = rebuilt.envelope_obligations
        return self

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_store_dict(self) -> dict[str, Any]:
        """Return the store-compatible ``index.json`` projection only."""

        with self._lock:
            return {
                "families": {
                    family: list(cids)
                    for family, cids in sorted(self.families.items())
                },
                "interface": self.interface,
                "profiles": dict(sorted(self.profiles.items())),
                "schema_version": self.schema_version,
                "sources": {
                    digest: dict(sorted(profiles.items()))
                    for digest, profiles in sorted(self.sources.items())
                },
                "store_schema_version": self.store_schema_version,
            }

    def to_dict(self) -> dict[str, Any]:
        """Return the full secondary index (store fields + obligations)."""

        with self._lock:
            payload = self.to_store_dict()
            payload["envelope_obligations"] = {
                cid: list(digests)
                for cid, digests in sorted(self.envelope_obligations.items())
            }
            payload["obligation_ids"] = {
                oid: list(cids)
                for oid, cids in sorted(self.obligation_ids.items())
            }
            payload["obligations"] = {
                digest: list(cids)
                for digest, cids in sorted(self.obligations.items())
            }
            return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProofCorpusIndex":
        """Parse a secondary index mapping (store or full shape)."""

        payload = dict(as_mapping(value, "proof corpus index"))
        schema = payload.get("schema_version", PROOF_CORPUS_INDEX_SCHEMA_VERSION)
        if schema != PROOF_CORPUS_INDEX_SCHEMA_VERSION:
            raise ProofCorpusIndexError(
                f"unsupported proof corpus index schema: {schema!r}"
            )

        families_raw = payload.get("families", {})
        if not isinstance(families_raw, Mapping):
            raise ProofCorpusIndexError("index families must be a mapping")
        families: dict[str, list[str]] = {}
        for family, cids in families_raw.items():
            family_key = parse_family(family).value
            if not isinstance(cids, Sequence) or isinstance(
                cids, (str, bytes, bytearray)
            ):
                raise ProofCorpusIndexError(
                    f"index families[{family_key!r}] must be a sequence of CIDs"
                )
            families[family_key] = _sorted_unique(
                require_text(cid, "family content_cid") for cid in cids
            )

        sources_raw = payload.get("sources", {})
        if not isinstance(sources_raw, Mapping):
            raise ProofCorpusIndexError("index sources must be a mapping")
        sources: dict[str, dict[str, str]] = {}
        for digest, profiles_map in sources_raw.items():
            digest_key = require_digest(digest, "source_digest")
            if not isinstance(profiles_map, Mapping):
                raise ProofCorpusIndexError(
                    f"index sources[{digest_key!r}] must be a mapping"
                )
            sources[digest_key] = {
                require_profile(profile): require_text(cid, "source content_cid")
                for profile, cid in sorted(profiles_map.items(), key=lambda p: str(p[0]))
            }

        profiles_raw = payload.get("profiles", {})
        if not isinstance(profiles_raw, Mapping):
            raise ProofCorpusIndexError("index profiles must be a mapping")
        profiles = {
            require_profile(profile): require_text(cid, "profile content_cid")
            for profile, cid in sorted(profiles_raw.items(), key=lambda p: str(p[0]))
        }

        obligations_raw = payload.get("obligations", {})
        if obligations_raw in (None, ""):
            obligations_raw = {}
        if not isinstance(obligations_raw, Mapping):
            raise ProofCorpusIndexError("index obligations must be a mapping")
        obligations: dict[str, list[str]] = {}
        for digest, cids in obligations_raw.items():
            digest_key = normalize_obligation_digest(digest)
            if not isinstance(cids, Sequence) or isinstance(
                cids, (str, bytes, bytearray)
            ):
                raise ProofCorpusIndexError(
                    f"index obligations[{digest_key!r}] must be a sequence of CIDs"
                )
            obligations[digest_key] = _sorted_unique(
                require_text(cid, "obligation content_cid") for cid in cids
            )

        obligation_ids_raw = payload.get("obligation_ids", {})
        if obligation_ids_raw in (None, ""):
            obligation_ids_raw = {}
        if not isinstance(obligation_ids_raw, Mapping):
            raise ProofCorpusIndexError("index obligation_ids must be a mapping")
        obligation_ids: dict[str, list[str]] = {}
        for oid, cids in obligation_ids_raw.items():
            oid_key = _require_obligation_id(oid)
            if not isinstance(cids, Sequence) or isinstance(
                cids, (str, bytes, bytearray)
            ):
                raise ProofCorpusIndexError(
                    f"index obligation_ids[{oid_key!r}] must be a sequence of CIDs"
                )
            obligation_ids[oid_key] = _sorted_unique(
                require_text(cid, "obligation_id content_cid") for cid in cids
            )

        envelope_obs_raw = payload.get("envelope_obligations", {})
        if envelope_obs_raw in (None, ""):
            envelope_obs_raw = {}
        if not isinstance(envelope_obs_raw, Mapping):
            raise ProofCorpusIndexError(
                "index envelope_obligations must be a mapping"
            )
        envelope_obligations: dict[str, list[str]] = {}
        for cid, digests in envelope_obs_raw.items():
            cid_key = require_text(cid, "envelope content_cid")
            if not isinstance(digests, Sequence) or isinstance(
                digests, (str, bytes, bytearray)
            ):
                raise ProofCorpusIndexError(
                    f"index envelope_obligations[{cid_key!r}] must be a sequence"
                )
            envelope_obligations[cid_key] = _sorted_unique(
                normalize_obligation_digest(d) for d in digests
            )

        return cls(
            schema_version=schema,
            interface=require_text(
                payload.get("interface", PROOF_CORPUS_STORE_INTERFACE),
                "interface",
            ),
            store_schema_version=require_text(
                payload.get(
                    "store_schema_version", PROOF_CORPUS_STORE_SCHEMA_VERSION
                ),
                "store_schema_version",
            ),
            families=dict(sorted(families.items())),
            sources={
                digest: dict(sorted(profiles_map.items()))
                for digest, profiles_map in sorted(sources.items())
            },
            profiles=dict(sorted(profiles.items())),
            obligations=dict(sorted(obligations.items())),
            obligation_ids=dict(sorted(obligation_ids.items())),
            envelope_obligations=dict(sorted(envelope_obligations.items())),
        )

    # ------------------------------------------------------------------
    # Lookup helpers (CID lists only — query layer loads envelopes)
    # ------------------------------------------------------------------

    def cids_for_family(self, family: str) -> tuple[str, ...]:
        family_key = parse_family(family).value
        with self._lock:
            return tuple(self.families.get(family_key, ()))

    def cids_for_profile(self, profile: str) -> tuple[str, ...]:
        profile = require_profile(profile)
        with self._lock:
            cid = self.profiles.get(profile)
            return (cid,) if cid is not None else ()

    def cids_for_source(
        self,
        source_digest: str,
        *,
        profile: str | None = None,
    ) -> tuple[str, ...]:
        source_digest = require_digest(source_digest, "source_digest")
        with self._lock:
            by_profile = self.sources.get(source_digest, {})
            if profile is not None:
                profile = require_profile(profile)
                cid = by_profile.get(profile)
                return (cid,) if cid is not None else ()
            return tuple(sorted(by_profile.values()))

    def cids_for_obligation_digest(
        self, obligation_digest: str
    ) -> tuple[str, ...]:
        digest = normalize_obligation_digest(obligation_digest)
        with self._lock:
            return tuple(self.obligations.get(digest, ()))

    def cids_for_obligation_id(self, obligation_id: str) -> tuple[str, ...]:
        oid = _require_obligation_id(obligation_id)
        with self._lock:
            return tuple(self.obligation_ids.get(oid, ()))

    def all_cids(self) -> tuple[str, ...]:
        with self._lock:
            cids: set[str] = set()
            for family_cids in self.families.values():
                cids.update(family_cids)
            return tuple(sorted(cids))

    def __len__(self) -> int:
        return len(self.all_cids())

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ProofCorpusIndex):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def persist(
        self,
        root: Path | str,
        *,
        store_projection: bool = True,
        secondary: bool = True,
    ) -> None:
        """Atomically write index files under *root*.

        * ``index.json`` — store-compatible projection (when *store_projection*)
        * ``secondary_index.json`` — full index including obligations
        """

        root_path = Path(root)
        root_path.mkdir(parents=True, exist_ok=True)
        if store_projection:
            _atomic_write_json(root_path / PROOF_CORPUS_INDEX_FILENAME, self.to_store_dict())
        if secondary:
            _atomic_write_json(
                root_path / PROOF_CORPUS_SECONDARY_INDEX_FILENAME, self.to_dict()
            )

    @classmethod
    def load(
        cls,
        root: Path | str,
        *,
        prefer_secondary: bool = True,
    ) -> "ProofCorpusIndex":
        """Load an index from *root* (secondary file preferred when present)."""

        root_path = Path(root)
        secondary_path = root_path / PROOF_CORPUS_SECONDARY_INDEX_FILENAME
        store_path = root_path / PROOF_CORPUS_INDEX_FILENAME
        if prefer_secondary and secondary_path.is_file():
            path = secondary_path
        elif store_path.is_file():
            path = store_path
        elif secondary_path.is_file():
            path = secondary_path
        else:
            raise ProofCorpusIndexError(
                f"no proof corpus index found under {root_path}"
            )
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProofCorpusIndexError(
                f"proof corpus index is unreadable ({path.name}): {exc}"
            ) from exc
        return cls.from_dict(as_mapping(payload, "proof corpus index"))


def rebuild_index(store: ProofCorpusStore) -> ProofCorpusIndex:
    """Rebuild a :class:`ProofCorpusIndex` from *store* (module-level helper)."""

    return ProofCorpusIndex.from_store(store)


def rebuild_and_persist(
    store: ProofCorpusStore,
    *,
    root: Path | str | None = None,
) -> ProofCorpusIndex:
    """Rebuild from *store* and optionally persist under *root* or ``store.root``."""

    index = rebuild_index(store)
    target = root if root is not None else store.root
    if target is not None:
        index.persist(target)
    return index


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


__all__ = [
    "PROOF_CORPUS_INDEX_FILENAME",
    "PROOF_CORPUS_SECONDARY_INDEX_FILENAME",
    "ProofCorpusIndex",
    "ProofCorpusIndexError",
    "normalize_obligation_digest",
    "rebuild_and_persist",
    "rebuild_index",
]
