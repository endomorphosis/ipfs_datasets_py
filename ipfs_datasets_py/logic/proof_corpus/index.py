"""Rebuildable secondary indexes for the proof corpus store (LIG-012).

Envelopes remain authoritative.  This module builds deterministic secondary
indexes (family, source digest, source id, profile, obligation digest) purely
from verified :class:`ArtifactEnvelope` values so a damaged or missing on-disk
``index.json`` can be reconstructed without re-formalizing sources.

Wire shape reuses ``proof-corpus-index/v1`` and extends it with obligation and
source-id postings used by :mod:`query`.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

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
from .store import ProofCorpusStore, ProofCorpusStoreIntegrityError


PROOF_CORPUS_INDEX_INTERFACE: Final = "ProofCorpusIndex@1"

# Obligation digests from ir_core.ProofObligation are bare hex; normalize to
# the corpus digest wire form for index keys and query filters.
_HEX64_RE_PREFIX: Final = "sha256:"


class ProofCorpusIndexError(ProofCorpusSchemaError):
    """Raised when a secondary index cannot be built, loaded, or queried."""


class ProofCorpusIndexIntegrityError(
    ProofCorpusIndexError, ProofCorpusIntegrityError
):
    """Raised when a secondary index fails integrity or drift checks."""


def normalize_obligation_digest(value: Any) -> str:
    """Normalize an obligation digest to ``sha256:<hex>`` form.

    Accepts bare 64-char hex (as returned by :attr:`ProofObligation.digest`)
    or an already-prefixed ``sha256:`` digest.
    """

    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ProofCorpusIndexError(
            "obligation_digest must be a non-empty trimmed string"
        )
    text = value
    if text.startswith(_HEX64_RE_PREFIX):
        return require_digest(text, "obligation_digest")
    if len(text) == 64 and all(c in "0123456789abcdef" for c in text):
        return require_digest(f"sha256:{text}", "obligation_digest")
    raise ProofCorpusIndexError(
        "obligation_digest must be sha256:<hex> or a 64-char lowercase hex digest"
    )


def obligation_digests_for_envelope(
    envelope: ArtifactEnvelope,
) -> tuple[str, ...]:
    """Return sorted unique obligation digests present in *envelope*."""

    digests: set[str] = set()
    try:
        artifact = envelope.formalization_artifact()
    except ProofCorpusIntegrityError:
        # Fail closed: a broken artifact is not indexable.
        raise
    for obligation in artifact.proof_obligations:
        digests.add(normalize_obligation_digest(obligation.digest))
    return tuple(sorted(digests))


def _require_cid_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ProofCorpusIndexIntegrityError(f"{label} must be a sequence of CIDs")
    cids = [require_text(item, f"{label} cid") for item in value]
    if len(cids) != len(set(cids)):
        raise ProofCorpusIndexIntegrityError(f"{label} must not contain duplicate CIDs")
    if cids != sorted(cids):
        raise ProofCorpusIndexIntegrityError(f"{label} CIDs must be sorted")
    return cids


@dataclass
class ProofCorpusIndex:
    """Deterministic secondary index over verified proof-corpus envelopes.

    Indexes are rebuildable from envelopes alone.  Serialization is canonical
    (sorted keys, sorted posting lists) so two rebuilds of the same envelope
    set always produce byte-identical payloads.
    """

    # family -> sorted content_cids
    families: dict[str, list[str]] = field(default_factory=dict)
    # source_digest -> profile -> content_cid
    sources: dict[str, dict[str, str]] = field(default_factory=dict)
    # profile -> sorted content_cids (multi-valued; store single-value is put-order)
    profiles: dict[str, list[str]] = field(default_factory=dict)
    # source_id -> sorted content_cids
    source_ids: dict[str, list[str]] = field(default_factory=dict)
    # obligation_digest (sha256:…) -> sorted content_cids
    obligations: dict[str, list[str]] = field(default_factory=dict)
    # content_cid set for membership / rebuild verification
    content_cids: list[str] = field(default_factory=list)
    schema_version: str = PROOF_CORPUS_INDEX_SCHEMA_VERSION
    interface: str = PROOF_CORPUS_INDEX_INTERFACE
    store_schema_version: str = PROOF_CORPUS_STORE_SCHEMA_VERSION

    # ------------------------------------------------------------------
    # Construction / rebuild
    # ------------------------------------------------------------------

    @classmethod
    def build(
        cls,
        envelopes: Iterable[ArtifactEnvelope],
    ) -> "ProofCorpusIndex":
        """Build a fresh index from verified envelopes (authoritative rebuild)."""

        index = cls()
        index.rebuild(envelopes)
        return index

    @classmethod
    def from_store(cls, store: ProofCorpusStore) -> "ProofCorpusIndex":
        """Rebuild an index by loading every envelope currently in *store*."""

        envelopes = tuple(store.get(cid) for cid in store.cids())
        return cls.build(envelopes)

    def rebuild(
        self,
        envelopes: Iterable[ArtifactEnvelope],
    ) -> "ProofCorpusIndex":
        """Replace all postings from *envelopes* (deterministic, fail closed)."""

        families: dict[str, set[str]] = {}
        sources: dict[str, dict[str, str]] = {}
        profiles: dict[str, set[str]] = {}
        source_ids: dict[str, set[str]] = {}
        obligations: dict[str, set[str]] = {}
        content_cids: set[str] = set()

        # Stable iteration order: sort by content_cid after materializing.
        ordered = sorted(
            (env.verify_integrity() for env in envelopes),
            key=lambda env: env.content_cid,
        )
        for envelope in ordered:
            cid = envelope.content_cid
            if cid in content_cids:
                raise ProofCorpusIndexIntegrityError(
                    f"duplicate envelope content_cid while rebuilding index: {cid}"
                )
            content_cids.add(cid)

            family_key = envelope.family.value
            families.setdefault(family_key, set()).add(cid)

            by_profile = sources.setdefault(envelope.source_digest, {})
            by_profile[envelope.profile] = cid
            profiles.setdefault(envelope.profile, set()).add(cid)

            source_ids.setdefault(envelope.source_id, set()).add(cid)

            for oblig_digest in obligation_digests_for_envelope(envelope):
                obligations.setdefault(oblig_digest, set()).add(cid)

        self.families = {
            family: sorted(cids) for family, cids in sorted(families.items())
        }
        self.sources = {
            digest: dict(sorted(profiles_map.items()))
            for digest, profiles_map in sorted(sources.items())
        }
        self.profiles = {
            profile: sorted(cids) for profile, cids in sorted(profiles.items())
        }
        self.source_ids = {
            sid: sorted(cids) for sid, cids in sorted(source_ids.items())
        }
        self.obligations = {
            digest: sorted(cids) for digest, cids in sorted(obligations.items())
        }
        self.content_cids = sorted(content_cids)
        self.schema_version = PROOF_CORPUS_INDEX_SCHEMA_VERSION
        self.interface = PROOF_CORPUS_INDEX_INTERFACE
        self.store_schema_version = PROOF_CORPUS_STORE_SCHEMA_VERSION
        return self

    def clear(self) -> None:
        """Drop all postings."""

        self.families.clear()
        self.sources.clear()
        self.profiles.clear()
        self.source_ids.clear()
        self.obligations.clear()
        self.content_cids.clear()

    # ------------------------------------------------------------------
    # Lookups (CID lists; callers resolve envelopes via the store)
    # ------------------------------------------------------------------

    def cids_for_family(self, family: ProofCorpusFamily | str) -> tuple[str, ...]:
        family_key = parse_family(family).value
        return tuple(self.families.get(family_key, ()))

    def cids_for_profile(self, profile: str) -> tuple[str, ...]:
        profile = require_profile(profile)
        return tuple(self.profiles.get(profile, ()))

    def cids_for_source_digest(
        self,
        source_digest: str,
        *,
        profile: str | None = None,
    ) -> tuple[str, ...]:
        source_digest = require_digest(source_digest, "source_digest")
        by_profile = self.sources.get(source_digest, {})
        if profile is not None:
            profile = require_profile(profile)
            cid = by_profile.get(profile)
            return (cid,) if cid is not None else ()
        return tuple(sorted(set(by_profile.values())))

    def cids_for_source_id(self, source_id: str) -> tuple[str, ...]:
        source_id = require_text(source_id, "source_id")
        return tuple(self.source_ids.get(source_id, ()))

    def cids_for_obligation(
        self,
        obligation_digest: str,
    ) -> tuple[str, ...]:
        key = normalize_obligation_digest(obligation_digest)
        return tuple(self.obligations.get(key, ()))

    def contains(self, content_cid: str) -> bool:
        try:
            cid = require_text(content_cid, "content_cid")
        except ProofCorpusSchemaError:
            return False
        return cid in self.content_cids

    def __len__(self) -> int:
        return len(self.content_cids)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Canonical index payload (sorted; suitable for atomic write)."""

        return {
            "content_cids": list(self.content_cids),
            "families": {
                family: list(cids) for family, cids in sorted(self.families.items())
            },
            "interface": self.interface,
            "obligations": {
                digest: list(cids)
                for digest, cids in sorted(self.obligations.items())
            },
            "profiles": {
                profile: list(cids)
                for profile, cids in sorted(self.profiles.items())
            },
            "schema_version": self.schema_version,
            "source_ids": {
                sid: list(cids) for sid, cids in sorted(self.source_ids.items())
            },
            "sources": {
                digest: dict(sorted(profiles.items()))
                for digest, profiles in sorted(self.sources.items())
            },
            "store_interface": PROOF_CORPUS_STORE_INTERFACE,
            "store_schema_version": self.store_schema_version,
        }

    def to_store_index_dict(self) -> dict[str, Any]:
        """Subset matching the on-disk store ``index.json`` shape.

        Used to verify that a rebuild from envelopes matches the secondary
        postings the store persists for order-independent keys (families /
        sources).  Store profile postings are single-valued last-writer-wins
        (put-order dependent); this projection uses the lexicographically last
        CID per profile so the payload is still deterministic.
        """

        return {
            "families": {
                family: list(cids) for family, cids in sorted(self.families.items())
            },
            "interface": PROOF_CORPUS_STORE_INTERFACE,
            "profiles": {
                profile: cids[-1]
                for profile, cids in sorted(self.profiles.items())
                if cids
            },
            "schema_version": PROOF_CORPUS_INDEX_SCHEMA_VERSION,
            "sources": {
                digest: dict(sorted(profiles.items()))
                for digest, profiles in sorted(self.sources.items())
            },
            "store_schema_version": PROOF_CORPUS_STORE_SCHEMA_VERSION,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProofCorpusIndex":
        payload = as_mapping(value, "proof corpus index")
        schema = payload.get("schema_version", PROOF_CORPUS_INDEX_SCHEMA_VERSION)
        if schema != PROOF_CORPUS_INDEX_SCHEMA_VERSION:
            raise ProofCorpusIndexIntegrityError(
                f"unsupported proof corpus index schema: {schema!r}"
            )

        families_raw = as_mapping(payload.get("families", {}), "index.families")
        families: dict[str, list[str]] = {}
        for family_key, cids in families_raw.items():
            family = parse_family(family_key).value
            families[family] = _require_cid_list(cids, f"index.families[{family}]")

        sources_raw = as_mapping(payload.get("sources", {}), "index.sources")
        sources: dict[str, dict[str, str]] = {}
        for digest_key, profiles_map in sources_raw.items():
            digest = require_digest(digest_key, "index.sources key")
            profiles_map = as_mapping(profiles_map, f"index.sources[{digest}]")
            sources[digest] = {
                require_profile(profile): require_text(cid, "index source cid")
                for profile, cid in sorted(profiles_map.items(), key=lambda p: p[0])
            }

        profiles_raw = as_mapping(payload.get("profiles", {}), "index.profiles")
        profiles: dict[str, list[str]] = {}
        for profile_key, value in profiles_raw.items():
            profile_key = require_profile(profile_key)
            # Accept store-shaped single CID or multi-valued sorted lists.
            if isinstance(value, str):
                profiles[profile_key] = [require_text(value, "index profile cid")]
            else:
                profiles[profile_key] = _require_cid_list(
                    value, f"index.profiles[{profile_key}]"
                )

        source_ids_raw = as_mapping(payload.get("source_ids", {}), "index.source_ids")
        source_ids: dict[str, list[str]] = {}
        for sid, cids in source_ids_raw.items():
            sid = require_text(sid, "index.source_ids key")
            source_ids[sid] = _require_cid_list(cids, f"index.source_ids[{sid}]")

        obligations_raw = as_mapping(
            payload.get("obligations", {}), "index.obligations"
        )
        obligations: dict[str, list[str]] = {}
        for digest_key, cids in obligations_raw.items():
            digest = normalize_obligation_digest(digest_key)
            obligations[digest] = _require_cid_list(
                cids, f"index.obligations[{digest}]"
            )

        if "content_cids" in payload:
            content_cids = _require_cid_list(
                payload.get("content_cids"), "index.content_cids"
            )
        else:
            # Derive from family postings when loading a store-shaped index.
            derived: set[str] = set()
            for cids in families.values():
                derived.update(cids)
            content_cids = sorted(derived)

        return cls(
            families=dict(sorted(families.items())),
            sources=dict(sorted(sources.items())),
            profiles=dict(sorted(profiles.items())),
            source_ids=dict(sorted(source_ids.items())),
            obligations=dict(sorted(obligations.items())),
            content_cids=list(content_cids),
            schema_version=PROOF_CORPUS_INDEX_SCHEMA_VERSION,
            interface=str(
                payload.get("interface", PROOF_CORPUS_INDEX_INTERFACE)
            ),
            store_schema_version=str(
                payload.get(
                    "store_schema_version", PROOF_CORPUS_STORE_SCHEMA_VERSION
                )
            ),
        )

    def save(self, path: Path | str) -> None:
        """Atomically write the canonical index payload to *path*."""

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = canonical_bytes(self.to_dict())
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

    @classmethod
    def load(cls, path: Path | str) -> "ProofCorpusIndex":
        """Load and validate an index file (fail closed on corruption)."""

        path = Path(path)
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProofCorpusIndexIntegrityError(
                f"proof corpus index is unreadable ({path.name}): {exc}"
            ) from exc
        return cls.from_dict(as_mapping(payload, "proof corpus index"))

    def matches_store_index(self, store_index: Mapping[str, Any]) -> bool:
        """Return True when *store_index* matches rebuildable postings.

        Compares order-independent keys (``families``, ``sources``,
        ``schema_version``).  Store ``profiles`` are put-order last-writer-wins
        and may diverge when multiple envelopes share a profile; callers that
        need full profile coverage should use this index's multi-valued
        postings instead.
        """

        expected = self.to_store_index_dict()
        other = as_mapping(store_index, "store index")
        for key in ("families", "sources", "schema_version"):
            if expected.get(key) != other.get(key):
                return False
        # Every store profile CID must exist in the multi-valued rebuild.
        other_profiles = other.get("profiles", {})
        if not isinstance(other_profiles, Mapping):
            return False
        for profile_key, cid in other_profiles.items():
            if profile_key not in self.profiles:
                return False
            if cid not in self.profiles[profile_key]:
                return False
        return True

    def assert_matches_envelopes(
        self,
        envelopes: Iterable[ArtifactEnvelope],
    ) -> None:
        """Fail closed if this index does not match a rebuild from *envelopes*."""

        rebuilt = ProofCorpusIndex.build(envelopes)
        if rebuilt.to_dict() != self.to_dict():
            raise ProofCorpusIndexIntegrityError(
                "proof corpus index does not match rebuild from envelopes"
            )


def rebuild_index_from_store(store: ProofCorpusStore) -> ProofCorpusIndex:
    """Module-level helper: rebuild a secondary index from a live store."""

    return ProofCorpusIndex.from_store(store)


def load_store_index(path: Path | str) -> dict[str, Any]:
    """Load a store-shaped ``index.json`` mapping (validated minimally)."""

    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProofCorpusStoreIntegrityError(
            f"proof corpus index is unreadable: {exc}"
        ) from exc
    payload = dict(as_mapping(payload, "proof corpus index"))
    if payload.get("schema_version") != PROOF_CORPUS_INDEX_SCHEMA_VERSION:
        raise ProofCorpusStoreIntegrityError(
            "unsupported proof corpus index schema: "
            f"{payload.get('schema_version')!r}"
        )
    return payload


__all__ = [
    "PROOF_CORPUS_INDEX_INTERFACE",
    "ProofCorpusIndex",
    "ProofCorpusIndexError",
    "ProofCorpusIndexIntegrityError",
    "load_store_index",
    "normalize_obligation_digest",
    "obligation_digests_for_envelope",
    "rebuild_index_from_store",
]
