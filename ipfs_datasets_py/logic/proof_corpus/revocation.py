"""Immutable proof-corpus revocation snapshots (ProofRevocationSnapshot@1 / LIG-030).

Revocation is an append-only, content-addressed chain of exact-root snapshots.
Each snapshot binds:

* corpus root CID (the manifest root being enforced against);
* parent snapshot CID and generation (append-only lineage);
* ordered unique revocation entries (target CID, reason, issuer, time);
* producer identity;
* optional supersession links.

Parent cycles, self-revocation of the snapshot root, rollback/downgrade of
generation, duplicate targets, hash/CID mismatch, and unbound empty reasons
fail closed.  Consumers decide policy consequences; this leaf freezes the
snapshot contract only.

This leaf does not rewrite :mod:`.schemas`, :mod:`.store`, :mod:`.manifest`,
:mod:`.model`, or :mod:`.policy`.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Iterable

from ..ir_core.identity import cid_v1_from_digest
from .manifest import (
    ProofCorpusManifest,
    ProofCorpusManifestError,
    ProofCorpusManifestIntegrityError,
)

PROOF_REVOCATION_SNAPSHOT_INTERFACE: Final = "ProofRevocationSnapshot@1"
PROOF_REVOCATION_SNAPSHOT_SCHEMA_VERSION: Final = "proof-revocation-snapshot/v1"
REVOCATION_ENTRY_SCHEMA_VERSION: Final = "proof-revocation-entry/v1"

DEFAULT_MAX_REVOCATION_ENTRIES: Final = 65_536

_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_BARE_DIGEST_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_CID_RE: Final = re.compile(r"^b[a-z2-7]{10,200}$")
_MUTABLE_LATEST_RE: Final = re.compile(
    r"(^|[./_-])latest($|[./_-])", re.IGNORECASE
)

_SNAPSHOT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "content_cid",
        "content_digest",
        "corpus_root_cid",
        "entries",
        "generation",
        "interface",
        "parent_cid",
        "producer_id",
        "root_cid",
        "schema_version",
    }
)


class ProofRevocationError(ProofCorpusManifestError):
    """Raised when a revocation snapshot or entry is malformed."""


class ProofRevocationIntegrityError(
    ProofRevocationError, ProofCorpusManifestIntegrityError
):
    """Raised when a revocation snapshot fails integrity or lineage checks."""


class RevocationReasonKind(str, Enum):
    """Closed reason vocabulary for revocation entries."""

    SUPERSEDED = "superseded"
    COMPROMISED = "compromised"
    POLICY = "policy"
    WITHDRAWN = "withdrawn"
    ERROR = "error"
    OTHER = "other"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_ready(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    raise ProofRevocationError(
        f"value of type {type(value).__name__} is not JSON-serializable "
        "for the revocation snapshot"
    )


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProofRevocationError(f"{label} must be a mapping")
    return value


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ProofRevocationError(
            f"{field_name} must be a non-empty trimmed string"
        )
    return value


def _optional_text(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_text(value, field_name)


def _require_digest(value: Any, field_name: str) -> str:
    digest = _require_text(value, field_name)
    if _BARE_DIGEST_RE.fullmatch(digest):
        digest = f"sha256:{digest}"
    if not _DIGEST_RE.fullmatch(digest):
        raise ProofRevocationError(
            f"{field_name} must be a sha256:<hex> digest"
        )
    return digest


def _optional_digest(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_digest(value, field_name)


def _require_cid(value: Any, field_name: str) -> str:
    cid = _require_text(value, field_name)
    if not _CID_RE.fullmatch(cid):
        raise ProofRevocationError(
            f"{field_name} must be a CIDv1 base32 string"
        )
    return cid


def _optional_cid(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_cid(value, field_name)


def _require_positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProofRevocationError(f"{field_name} must be an int")
    if value <= 0:
        raise ProofRevocationError(f"{field_name} must be a positive int")
    return value


def _require_non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProofRevocationError(f"{field_name} must be an int")
    if value < 0:
        raise ProofRevocationError(f"{field_name} must be a non-negative int")
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ProofRevocationError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _parse_enum(value: Any, enum_cls: type[Enum], field_name: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_cls)
        raise ProofRevocationError(
            f"{field_name} must be one of: {allowed}"
        ) from exc


def _reject_mutable_latest(value: str, field_name: str) -> None:
    if value.lower() == "latest" or _MUTABLE_LATEST_RE.search(value):
        raise ProofRevocationIntegrityError(
            f"{field_name} must not use mutable 'latest' alias: {value!r}"
        )


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RevocationEntry:
    """One ordered revocation targeting a content-addressed artifact."""

    target_cid: str
    reason_kind: RevocationReasonKind | str
    reason: str
    revoked_at: str
    issuer_id: str
    ordinal: int = 0
    supersedes_cid: str = ""
    evidence_cid: str = ""
    notes: str = ""
    entry_digest: str = ""
    schema_version: str = REVOCATION_ENTRY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "target_cid", _require_cid(self.target_cid, "target_cid")
        )
        object.__setattr__(
            self,
            "reason_kind",
            _parse_enum(self.reason_kind, RevocationReasonKind, "reason_kind"),
        )
        object.__setattr__(
            self, "reason", _require_text(self.reason, "reason")
        )
        _reject_mutable_latest(self.reason, "reason")
        object.__setattr__(
            self, "revoked_at", _require_text(self.revoked_at, "revoked_at")
        )
        object.__setattr__(
            self, "issuer_id", _require_text(self.issuer_id, "issuer_id")
        )
        _reject_mutable_latest(self.issuer_id, "issuer_id")
        object.__setattr__(
            self, "ordinal", _require_non_negative_int(self.ordinal, "ordinal")
        )
        object.__setattr__(
            self,
            "supersedes_cid",
            _optional_cid(self.supersedes_cid, "supersedes_cid"),
        )
        object.__setattr__(
            self,
            "evidence_cid",
            _optional_cid(self.evidence_cid, "evidence_cid"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != REVOCATION_ENTRY_SCHEMA_VERSION:
            raise ProofRevocationError(
                f"unsupported revocation entry schema: "
                f"{self.schema_version!r}"
            )

        body = self._identity_payload()
        digest = _sha256_digest(_canonical_bytes(body))
        if self.entry_digest:
            recorded = _require_digest(self.entry_digest, "entry_digest")
            if recorded != digest:
                raise ProofRevocationIntegrityError(
                    "revocation entry_digest does not match payload "
                    "(hash mismatch)"
                )
        object.__setattr__(self, "entry_digest", digest)

    def _identity_payload(self) -> dict[str, Any]:
        kind = (
            self.reason_kind.value
            if isinstance(self.reason_kind, RevocationReasonKind)
            else self.reason_kind
        )
        return {
            "evidence_cid": self.evidence_cid,
            "issuer_id": self.issuer_id,
            "notes": self.notes,
            "ordinal": self.ordinal,
            "reason": self.reason,
            "reason_kind": kind,
            "revoked_at": self.revoked_at,
            "schema_version": self.schema_version,
            "supersedes_cid": self.supersedes_cid,
            "target_cid": self.target_cid,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["entry_digest"] = self.entry_digest
        return payload

    @classmethod
    def from_dict(cls, value: Any) -> "RevocationEntry":
        if isinstance(value, RevocationEntry):
            return value
        payload = dict(_as_mapping(value, "revocation entry"))
        _reject_unknown(
            payload,
            frozenset(
                {
                    "entry_digest",
                    "evidence_cid",
                    "issuer_id",
                    "notes",
                    "ordinal",
                    "reason",
                    "reason_kind",
                    "revoked_at",
                    "schema_version",
                    "supersedes_cid",
                    "target_cid",
                }
            ),
            "revocation entry",
        )
        return cls(
            target_cid=payload["target_cid"],
            reason_kind=payload["reason_kind"],
            reason=payload["reason"],
            revoked_at=payload["revoked_at"],
            issuer_id=payload["issuer_id"],
            ordinal=int(payload.get("ordinal", 0) or 0),
            supersedes_cid=payload.get("supersedes_cid", ""),
            evidence_cid=payload.get("evidence_cid", ""),
            notes=payload.get("notes", ""),
            entry_digest=payload.get("entry_digest", ""),
            schema_version=payload.get(
                "schema_version", REVOCATION_ENTRY_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def _normalize_entries(value: Any) -> tuple[RevocationEntry, ...]:
    if value in (None, ()):
        return ()
    if isinstance(value, (str, bytes, bytearray, Mapping, RevocationEntry)):
        raise ProofRevocationError(
            "entries must be a sequence of revocation entries"
        )
    try:
        items = tuple(
            item
            if isinstance(item, RevocationEntry)
            else RevocationEntry.from_dict(item)
            for item in value
        )
    except TypeError as exc:
        raise ProofRevocationError(
            "entries must be a sequence of revocation entries"
        ) from exc
    return items


@dataclass(frozen=True, slots=True)
class ProofRevocationSnapshot:
    """Immutable append-only revocation snapshot (ProofRevocationSnapshot@1).

    Identity is content-addressed.  ``root_cid`` is the snapshot authority
    that later envelopes bind via ``revocation_root_cid``.
    """

    corpus_root_cid: str
    entries: tuple[RevocationEntry, ...] | Sequence[RevocationEntry] = ()
    parent_cid: str = ""
    generation: int = 1
    producer_id: str = ""
    content_digest: str = ""
    content_cid: str = ""
    root_cid: str = ""
    schema_version: str = PROOF_REVOCATION_SNAPSHOT_SCHEMA_VERSION
    interface: str = PROOF_REVOCATION_SNAPSHOT_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "corpus_root_cid",
            _require_cid(self.corpus_root_cid, "corpus_root_cid"),
        )
        object.__setattr__(self, "entries", _normalize_entries(self.entries))
        if len(self.entries) > DEFAULT_MAX_REVOCATION_ENTRIES:
            raise ProofRevocationIntegrityError(
                f"entries exceed max_revocation_entries "
                f"({DEFAULT_MAX_REVOCATION_ENTRIES})"
            )

        ordinals = [entry.ordinal for entry in self.entries]
        if ordinals != sorted(ordinals):
            raise ProofRevocationIntegrityError(
                "revocation entries must be ordered by non-decreasing ordinal"
            )
        if len(ordinals) != len(set(ordinals)):
            raise ProofRevocationIntegrityError(
                "revocation entries must have unique ordinals"
            )

        targets = [entry.target_cid for entry in self.entries]
        if len(targets) != len(set(targets)):
            raise ProofRevocationIntegrityError(
                "revocation entries contain duplicate target_cid"
            )

        object.__setattr__(
            self, "parent_cid", _optional_cid(self.parent_cid, "parent_cid")
        )
        object.__setattr__(
            self,
            "generation",
            _require_positive_int(self.generation, "generation"),
        )
        object.__setattr__(
            self, "producer_id", _optional_text(self.producer_id, "producer_id")
        )
        if self.producer_id:
            _reject_mutable_latest(self.producer_id, "producer_id")

        if self.schema_version != PROOF_REVOCATION_SNAPSHOT_SCHEMA_VERSION:
            raise ProofRevocationError(
                f"unsupported revocation snapshot schema: "
                f"{self.schema_version!r}"
            )
        if self.interface != PROOF_REVOCATION_SNAPSHOT_INTERFACE:
            raise ProofRevocationError(
                f"unsupported revocation snapshot interface: "
                f"{self.interface!r}"
            )

        body = self._identity_payload()
        digest = _sha256_digest(_canonical_bytes(body))
        cid = cid_v1_from_digest(bytes.fromhex(digest.removeprefix("sha256:")))

        # A snapshot must not revoke its own root (self-cycle) or its parent.
        if self.corpus_root_cid in set(targets):
            # Revoking the corpus root is allowed as a corpus-level kill switch
            # only when explicitly recorded; we do not treat it as a cycle.
            pass
        for entry in self.entries:
            if entry.target_cid == cid:
                raise ProofRevocationIntegrityError(
                    "revocation entry must not target the snapshot's own "
                    "root_cid (revocation cycle rejected)"
                )
            if self.parent_cid and entry.target_cid == self.parent_cid:
                raise ProofRevocationIntegrityError(
                    "revocation entry must not target parent_cid "
                    "(revocation lineage cycle rejected)"
                )

        if self.content_digest:
            recorded = _require_digest(self.content_digest, "content_digest")
            if recorded != digest:
                raise ProofRevocationIntegrityError(
                    "revocation content_digest does not match payload "
                    "(hash mismatch)"
                )
        if self.content_cid:
            recorded_cid = _require_cid(self.content_cid, "content_cid")
            if recorded_cid != cid:
                raise ProofRevocationIntegrityError(
                    "revocation content_cid does not match payload "
                    "(CID mismatch)"
                )
        if self.root_cid:
            recorded_root = _require_cid(self.root_cid, "root_cid")
            if recorded_root != cid:
                raise ProofRevocationIntegrityError(
                    "revocation root_cid does not match payload (CID mismatch)"
                )
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(self, "content_cid", cid)
        object.__setattr__(self, "root_cid", cid)

        if self.parent_cid and self.parent_cid == self.root_cid:
            raise ProofRevocationIntegrityError(
                "revocation parent_cid must not equal its own root_cid "
                "(revocation cycle rejected)"
            )

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "corpus_root_cid": self.corpus_root_cid,
            "entries": [item.to_dict() for item in self.entries],
            "generation": self.generation,
            "interface": self.interface,
            "parent_cid": self.parent_cid,
            "producer_id": self.producer_id,
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_cid"] = self.content_cid
        payload["content_digest"] = self.content_digest
        payload["root_cid"] = self.root_cid
        return _json_ready(payload)

    @classmethod
    def from_dict(cls, value: Any) -> "ProofRevocationSnapshot":
        if isinstance(value, ProofRevocationSnapshot):
            return value
        payload = dict(_as_mapping(value, "revocation snapshot"))
        _reject_unknown(payload, _SNAPSHOT_FIELDS, "revocation snapshot")
        return cls(
            corpus_root_cid=payload["corpus_root_cid"],
            entries=tuple(payload.get("entries", ()) or ()),
            parent_cid=payload.get("parent_cid", ""),
            generation=int(payload.get("generation", 1) or 1),
            producer_id=payload.get("producer_id", ""),
            content_digest=payload.get("content_digest", ""),
            content_cid=payload.get("content_cid", ""),
            root_cid=payload.get("root_cid", ""),
            schema_version=payload.get(
                "schema_version", PROOF_REVOCATION_SNAPSHOT_SCHEMA_VERSION
            ),
            interface=payload.get(
                "interface", PROOF_REVOCATION_SNAPSHOT_INTERFACE
            ),
        )

    def verify_integrity(self) -> None:
        """Rehash identity and fail closed on digest/CID drift."""

        restored = ProofRevocationSnapshot.from_dict(self.to_dict())
        if restored.content_digest != self.content_digest:
            raise ProofRevocationIntegrityError(
                "revocation content_digest drifted on rehash"
            )
        if restored.root_cid != self.root_cid:
            raise ProofRevocationIntegrityError(
                "revocation root_cid drifted on rehash"
            )

    def revoked_cids(self) -> frozenset[str]:
        return frozenset(entry.target_cid for entry in self.entries)

    def is_revoked(self, target_cid: str) -> bool:
        cid = _require_cid(target_cid, "target_cid")
        return cid in self.revoked_cids()

    def entry_for(self, target_cid: str) -> RevocationEntry | None:
        cid = _require_cid(target_cid, "target_cid")
        for entry in self.entries:
            if entry.target_cid == cid:
                return entry
        return None

    def union_revoked_with_ancestors(
        self,
        ancestors: Sequence["ProofRevocationSnapshot"] = (),
    ) -> frozenset[str]:
        """Return cumulative revoked CIDs including ancestor snapshots."""

        revoked: set[str] = set(self.revoked_cids())
        for ancestor in ancestors:
            if not isinstance(ancestor, ProofRevocationSnapshot):
                raise ProofRevocationError(
                    "ancestors must be ProofRevocationSnapshot instances"
                )
            revoked.update(ancestor.revoked_cids())
        return frozenset(revoked)


def build_revocation_entry(
    *,
    target_cid: str,
    reason_kind: RevocationReasonKind | str,
    reason: str,
    revoked_at: str,
    issuer_id: str,
    ordinal: int = 0,
    supersedes_cid: str = "",
    evidence_cid: str = "",
    notes: str = "",
) -> RevocationEntry:
    """Construct a validated :class:`RevocationEntry`."""

    return RevocationEntry(
        target_cid=target_cid,
        reason_kind=reason_kind,
        reason=reason,
        revoked_at=revoked_at,
        issuer_id=issuer_id,
        ordinal=ordinal,
        supersedes_cid=supersedes_cid,
        evidence_cid=evidence_cid,
        notes=notes,
    )


def build_revocation_snapshot(**kwargs: Any) -> ProofRevocationSnapshot:
    """Construct a validated :class:`ProofRevocationSnapshot`."""

    return ProofRevocationSnapshot(**kwargs)


def detect_revocation_cycle(
    child_cid: str,
    parent_cid: str,
    lineage: Mapping[str, str] | None = None,
) -> None:
    """Reject cycles in the revocation snapshot parent chain."""

    if not parent_cid:
        return
    child = _require_cid(child_cid, "child_cid")
    parent = _require_cid(parent_cid, "parent_cid")
    if parent == child:
        raise ProofRevocationIntegrityError(
            "revocation parent_cid must not equal its own root_cid "
            "(revocation cycle rejected)"
        )
    if lineage is None:
        return
    seen: set[str] = {child}
    current = parent
    while current:
        if current in seen:
            raise ProofRevocationIntegrityError(
                f"revocation parent lineage contains a cycle at {current!r}"
            )
        seen.add(current)
        current = lineage.get(current, "")
        if current:
            current = _require_cid(current, "lineage parent_cid")


def check_revocation_lineage(
    child: ProofRevocationSnapshot,
    parent: ProofRevocationSnapshot,
    *,
    lineage: Mapping[str, str] | None = None,
) -> None:
    """Validate append-only revocation lineage; reject rollback/downgrade.

    Rules:

    * ``child.parent_cid`` equals ``parent.root_cid``;
    * ``child.generation`` strictly greater than ``parent.generation``;
    * ``child.corpus_root_cid`` equals ``parent.corpus_root_cid`` (same corpus);
    * no parent cycle;
    * revoked target sets are append-only: parent targets remain revoked
      (child may add targets; may not drop prior revocations when checked
      as a cumulative supersession).
    """

    if not isinstance(child, ProofRevocationSnapshot):
        raise ProofRevocationError("child must be a ProofRevocationSnapshot")
    if not isinstance(parent, ProofRevocationSnapshot):
        raise ProofRevocationError("parent must be a ProofRevocationSnapshot")

    if not child.parent_cid:
        raise ProofRevocationIntegrityError(
            "child revocation snapshot must declare parent_cid for lineage"
        )
    if child.parent_cid != parent.root_cid:
        raise ProofRevocationIntegrityError(
            "child.parent_cid must equal parent.root_cid"
        )
    if child.generation <= parent.generation:
        raise ProofRevocationIntegrityError(
            f"child generation {child.generation} must be strictly greater "
            f"than parent generation {parent.generation} "
            "(rollback/downgrade rejected)"
        )
    if child.corpus_root_cid != parent.corpus_root_cid:
        raise ProofRevocationIntegrityError(
            "child corpus_root_cid must match parent corpus_root_cid"
        )

    detect_revocation_cycle(
        child.root_cid,
        child.parent_cid,
        lineage={**(lineage or {}), parent.root_cid: parent.parent_cid},
    )

    # Append-only target set: child must retain every parent target.
    missing = parent.revoked_cids() - child.revoked_cids()
    if missing:
        raise ProofRevocationIntegrityError(
            "child revocation snapshot dropped parent targets "
            f"(append-only violation): {', '.join(sorted(missing))}"
        )


def bind_manifest_revocation_root(
    manifest: ProofCorpusManifest,
    snapshot: ProofRevocationSnapshot,
) -> None:
    """Fail closed when a manifest and snapshot disagree on roots.

    * Snapshot ``corpus_root_cid`` must equal the manifest ``root_cid``.
    * When the manifest declares ``revocation_root_cid``, it must equal the
      snapshot ``root_cid``.
    """

    if not isinstance(manifest, ProofCorpusManifest):
        raise ProofRevocationError("manifest must be a ProofCorpusManifest")
    if not isinstance(snapshot, ProofRevocationSnapshot):
        raise ProofRevocationError(
            "snapshot must be a ProofRevocationSnapshot"
        )
    if snapshot.corpus_root_cid != manifest.root_cid:
        raise ProofRevocationIntegrityError(
            "revocation snapshot corpus_root_cid must equal manifest root_cid"
        )
    if (
        manifest.revocation_root_cid
        and manifest.revocation_root_cid != snapshot.root_cid
    ):
        raise ProofRevocationIntegrityError(
            "manifest revocation_root_cid must equal snapshot root_cid"
        )


def cumulative_revoked_cids(
    snapshots: Iterable[ProofRevocationSnapshot],
) -> frozenset[str]:
    """Union of revoked CIDs across an ordered snapshot sequence."""

    revoked: set[str] = set()
    for snapshot in snapshots:
        if not isinstance(snapshot, ProofRevocationSnapshot):
            raise ProofRevocationError(
                "snapshots must be ProofRevocationSnapshot instances"
            )
        revoked.update(snapshot.revoked_cids())
    return frozenset(revoked)


__all__ = [
    "DEFAULT_MAX_REVOCATION_ENTRIES",
    "PROOF_REVOCATION_SNAPSHOT_INTERFACE",
    "PROOF_REVOCATION_SNAPSHOT_SCHEMA_VERSION",
    "ProofRevocationError",
    "ProofRevocationIntegrityError",
    "ProofRevocationSnapshot",
    "REVOCATION_ENTRY_SCHEMA_VERSION",
    "RevocationEntry",
    "RevocationReasonKind",
    "bind_manifest_revocation_root",
    "build_revocation_entry",
    "build_revocation_snapshot",
    "check_revocation_lineage",
    "cumulative_revoked_cids",
    "detect_revocation_cycle",
]
