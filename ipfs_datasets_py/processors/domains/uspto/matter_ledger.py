"""Matter ledger reconciliation for USPTO originals, derivatives, receipts,
status, and versions (PATLAW-025).

The ledger reconciles:

* original submission files (e.g. DOCX);
* converted renderings (e.g. USPTO PDF);
* GUI / export metadata and document descriptions;
* acknowledgement and payment receipts;
* public file-wrapper document inventory;
* transaction / status events; and
* amendments and the current claim-set versions.

Invariants (fail-closed):

* Conflicts and missing / delayed items remain **explicit** records — never
  silently dropped or folded into a success path.
* Authoritative original versus derivative relationships are preserved; a
  derivative never overwrites or replaces its parent.
* Artifacts whose matter identifiers disagree with the ledger matter are
  **quarantined**, not admitted into the active matter set.
* Replay of the same ingest sequence yields the same content-addressed ledger
  and **never overwrites** prior history (append-only versions).

Missing or delayed public documents are recorded as retrieval freshness gaps,
not proof that USPTO did not receive an item.

This module owns reconciliation semantics only. Providers, raw artifact stores,
and parsers are immutable inputs.
"""

from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Mapping, Protocol, Sequence

from .artifact_manifest import ARTIFACT_MANIFEST_SCHEMA_VERSION, ArtifactManifest
from .contracts import (
    CONTRACTS_SCHEMA_VERSION,
    AuthorityRelation,
    DisclosureClassification,
    MatterEvent,
    MatterEventKind,
    SourceReceipt,
    canonical_json,
    requires_quarantine,
)

MATTER_LEDGER_SCHEMA_VERSION: Final = "uspto.matter-ledger.v1"
MATTER_LEDGER_INTERFACE: Final = "MatterLedger@1"

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_ISO_UTC_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)

# Label keys commonly used by private export / document sync / classifier.
_LABEL_ROLE: Final = "role"
_LABEL_LOGICAL_ID: Final = "logical_id"
_LABEL_SOURCE_DOCUMENT_ID: Final = "source_document_id"
_LABEL_DOCUMENT_CODE: Final = "document_code"
_LABEL_CLAIM_SET: Final = "claim_set"
_LABEL_AMENDMENT: Final = "amendment"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class LedgerChannel(str, Enum):
    """Provenance channel for a ledger admission."""

    PRIVATE_IMPORT = "private_import"
    PUBLIC_FILE_WRAPPER = "public_file_wrapper"
    STATUS_API = "status_api"
    MANUAL = "manual"
    DERIVED = "derived"
    UNKNOWN = "unknown"


class LedgerItemKind(str, Enum):
    """Semantic kind of a ledger item (plan §10 reconciliation surface)."""

    ORIGINAL_SUBMISSION = "original_submission"
    CONVERTED_RENDERING = "converted_rendering"
    GUI_METADATA = "gui_metadata"
    ACKNOWLEDGEMENT = "acknowledgement"
    PAYMENT_RECEIPT = "payment_receipt"
    FILE_WRAPPER_DOCUMENT = "file_wrapper_document"
    STATUS_EVENT = "status_event"
    TRANSACTION_EVENT = "transaction_event"
    AMENDMENT = "amendment"
    CLAIM_SET = "claim_set"
    INVENTORY_PLACEHOLDER = "inventory_placeholder"
    OTHER = "other"


class LedgerPresence(str, Enum):
    """Whether the item's content is present in an admitted store."""

    PRESENT = "present"
    MISSING = "missing"
    DELAYED = "delayed"
    QUARANTINED = "quarantined"


class IngestDisposition(str, Enum):
    """Outcome of one ingest attempt."""

    ADMITTED = "admitted"
    """First content-addressed admission for this logical key + digest."""

    DEDUPLICATED = "deduplicated"
    """Identical entry already present; history unchanged."""

    VERSIONED = "versioned"
    """Same logical id, new content digest → new immutable version retained."""

    QUARANTINED = "quarantined"
    """Wrong matter id / policy violation — not in the active matter set."""

    CONFLICT = "conflict"
    """Admitted or retained with an explicit conflict record."""

    GAP_RECORDED = "gap_recorded"
    """Missing / delayed inventory item recorded as a freshness gap."""


class ConflictCode(str, Enum):
    """Typed conflict codes kept explicit on the ledger."""

    AUTHORITY_CONFLICT = "authority_conflict"
    HASH_MISMATCH = "hash_mismatch"
    MATTER_ID_MISMATCH = "matter_id_mismatch"
    DUAL_AUTHORITATIVE_ORIGINAL = "dual_authoritative_original"
    PARENT_MISSING = "parent_missing"
    VERSION_CONTENT_COLLISION = "version_content_collision"
    LABEL_CONFLICT = "label_conflict"
    RELATION_INVERSION = "relation_inversion"
    CHANNEL_DISAGREEMENT = "channel_disagreement"


class GapCode(str, Enum):
    """Typed gap codes. None of these imply nonreceipt of a filing."""

    INVENTORY_WITHOUT_BYTES = "inventory_without_bytes"
    DELAYED_PUBLICATION = "delayed_publication"
    STATUS_RETRIEVAL_GAP = "status_retrieval_gap"
    EXPECTED_ITEM_ABSENT = "expected_item_absent"
    RECEIPT_WITHOUT_ORIGINAL = "receipt_without_original"
    CONVERSION_WITHOUT_ORIGINAL = "conversion_without_original"


class GapInterpretation(str, Enum):
    """How a missing / delayed item must be interpreted."""

    FRESHNESS_GAP = "freshness_gap"
    """Delayed publication / not yet downloadable — never nonreceipt."""

    RETRIEVAL_GAP = "retrieval_gap"
    """API / store retrieval failed or incomplete — never nonreceipt."""

    UNAVAILABLE_PRIVATE = "unavailable_private"
    UNAVAILABLE_NPL = "unavailable_npl"
    UNAVAILABLE_OTHER = "unavailable_other"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MatterLedgerError(ValueError):
    """Raised for invalid ledger construction or inputs."""

    def __init__(self, message: str, *, code: str = "matter_ledger_error") -> None:
        super().__init__(message)
        self.code = code

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _require_str(value: Any, field: str, *, max_len: int = 4096) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _optional_str(value: Any, field: str, *, max_len: int = 4096) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str or None")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _identifier(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _optional_identifier(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=256)
    if text is None:
        return None
    if not _ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _sha256_hex(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64).lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field} must be a 64-char lowercase hex SHA-256 digest")
    return text


def _optional_sha256(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=64)
    if text is None:
        return None
    return _sha256_hex(text, field)


def _optional_utc(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=64)
    if text is None:
        return None
    if not _ISO_UTC_RE.match(text):
        raise ValueError(f"{field} must be ISO-8601 UTC: {text!r}")
    return text


def _require_utc(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    if not _ISO_UTC_RE.match(text):
        raise ValueError(f"{field} must be ISO-8601 UTC: {text!r}")
    return text


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Any:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


def _frozen_str_map(
    value: Any, field: str, *, max_items: int = 64
) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: dict[str, str] = {}
    for key, raw in value.items():
        k = _require_str(key, f"{field}.key", max_len=128)
        v = _require_str(raw, f"{field}[{k}]", max_len=2048)
        out[k] = v
    return MappingProxyType(dict(sorted(out.items())))


def _tuple_of_str(value: Any, field: str, *, max_items: int = 256) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of strings")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    return tuple(
        _require_str(item, f"{field}[{i}]", max_len=256) for i, item in enumerate(value)
    )


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int")
    if value < 1:
        raise ValueError(f"{field} must be >= 1")
    return value


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int")
    if value < 0:
        raise ValueError(f"{field} must be >= 0")
    return value


def content_addressed_id(prefix: str, payload: Mapping[str, Any]) -> str:
    """Deterministic entry / conflict / gap id from a canonical payload."""
    digest = hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()
    safe_prefix = _require_str(prefix, "prefix", max_len=64)
    return f"{safe_prefix}:{digest[:32]}"


def normalize_matter_key(matter_id: str) -> str:
    """Normalize a matter identifier for comparison (case-sensitive strip)."""
    return _identifier(matter_id, "matter_id")


def matter_ids_compatible(expected: str, observed: str | None) -> bool:
    """Return True when *observed* is absent or equals *expected* after normalize.

    Digits-only application numbers are compared without punctuation so that
    ``16/000,001`` and ``16000001`` (when embedded in matter ids) can be matched
    by callers that pass both forms via labels — the primary matter_id field
    itself remains an opaque identifier.
    """
    if observed is None:
        return True
    exp = normalize_matter_key(expected)
    obs = normalize_matter_key(observed)
    if exp == obs:
        return True
    # Compact digit equality when both look like application numbers.
    exp_digits = re.sub(r"\D", "", exp)
    obs_digits = re.sub(r"\D", "", obs)
    if exp_digits and exp_digits == obs_digits and len(exp_digits) >= 8:
        return True
    return False


def infer_item_kind(
    *,
    authority_relation: AuthorityRelation | str | None = None,
    media_type: str | None = None,
    labels: Mapping[str, str] | None = None,
    explicit: LedgerItemKind | str | None = None,
) -> LedgerItemKind:
    """Infer :class:`LedgerItemKind` from labels / media / relation cues."""
    if explicit is not None:
        return _coerce_enum(LedgerItemKind, explicit, "item_kind")

    labels = labels or {}
    role = (labels.get(_LABEL_ROLE) or labels.get("document_kind") or "").lower()
    media = (media_type or "").lower()
    rel = None
    if authority_relation is not None:
        rel = _coerce_enum(AuthorityRelation, authority_relation, "authority_relation")

    if role in {
        "original_submission",
        "original",
        "docx_original",
        "authoritative_docx",
    }:
        return LedgerItemKind.ORIGINAL_SUBMISSION
    if role in {
        "uspto_converted_pdf",
        "converted_pdf",
        "pdf_conversion",
        "converted_rendering",
    }:
        return LedgerItemKind.CONVERTED_RENDERING
    if role in {"acknowledgement", "acknowledgment", "ack_receipt", "filing_receipt"}:
        return LedgerItemKind.ACKNOWLEDGEMENT
    if role in {"payment_receipt", "fee_receipt", "payment"}:
        return LedgerItemKind.PAYMENT_RECEIPT
    if role in {"gui_metadata", "export_metadata", "document_description"}:
        return LedgerItemKind.GUI_METADATA
    if role in {"amendment", "claim_amendment"} or labels.get(_LABEL_AMENDMENT):
        return LedgerItemKind.AMENDMENT
    if role in {"claim_set", "claims"} or labels.get(_LABEL_CLAIM_SET):
        return LedgerItemKind.CLAIM_SET
    if role in {"file_wrapper", "file_wrapper_document", "odp_document"}:
        return LedgerItemKind.FILE_WRAPPER_DOCUMENT
    if role in {"status", "status_event"}:
        return LedgerItemKind.STATUS_EVENT
    if role in {"transaction", "transaction_event"}:
        return LedgerItemKind.TRANSACTION_EVENT
    if role in {"inventory", "inventory_placeholder"}:
        return LedgerItemKind.INVENTORY_PLACEHOLDER

    if "payment" in role and "receipt" in role:
        return LedgerItemKind.PAYMENT_RECEIPT
    if "acknowledg" in role or "filing_receipt" in role:
        return LedgerItemKind.ACKNOWLEDGEMENT

    if rel is AuthorityRelation.DERIVATIVE or rel is AuthorityRelation.DERIVED_FROM:
        if "pdf" in media or role.endswith(".pdf"):
            return LedgerItemKind.CONVERTED_RENDERING
        return LedgerItemKind.CONVERTED_RENDERING

    if "wordprocessingml" in media or media.endswith("docx"):
        return LedgerItemKind.ORIGINAL_SUBMISSION
    if media == "application/pdf" and rel is AuthorityRelation.AUTHORITATIVE_ORIGINAL:
        return LedgerItemKind.FILE_WRAPPER_DOCUMENT

    return LedgerItemKind.OTHER


# ---------------------------------------------------------------------------
# Domain records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One immutable, content-addressed ledger entry (never overwritten).

    ``entry_id`` is derived from the canonical identity fields so replay of the
    same inputs yields the same id. ``version`` increments per ``logical_id``
    when content digests differ; prior versions remain in the ledger.
    """

    schema_version: str
    entry_id: str
    matter_id: str
    logical_id: str
    item_kind: LedgerItemKind
    authority_relation: AuthorityRelation
    presence: LedgerPresence
    version: int
    content_sha256: str | None
    size_bytes: int | None
    artifact_id: str | None
    parent_entry_ids: tuple[str, ...]
    parent_artifact_ids: tuple[str, ...]
    related_entry_ids: tuple[str, ...]
    source_receipt_id: str | None
    channel: LedgerChannel
    classification: DisclosureClassification
    media_type: str | None
    event_kind: MatterEventKind | None
    event_utc: str | None
    admitted_utc: str
    labels: Mapping[str, str]
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != MATTER_LEDGER_SCHEMA_VERSION:
            raise MatterLedgerError(
                f"LedgerEntry.schema_version must be {MATTER_LEDGER_SCHEMA_VERSION}",
                code="schema_version_mismatch",
            )
        object.__setattr__(self, "entry_id", _identifier(self.entry_id, "entry_id"))
        object.__setattr__(self, "matter_id", _identifier(self.matter_id, "matter_id"))
        object.__setattr__(
            self, "logical_id", _identifier(self.logical_id, "logical_id")
        )
        object.__setattr__(
            self, "item_kind", _coerce_enum(LedgerItemKind, self.item_kind, "item_kind")
        )
        object.__setattr__(
            self,
            "authority_relation",
            _coerce_enum(
                AuthorityRelation, self.authority_relation, "authority_relation"
            ),
        )
        object.__setattr__(
            self, "presence", _coerce_enum(LedgerPresence, self.presence, "presence")
        )
        object.__setattr__(self, "version", _positive_int(self.version, "version"))
        object.__setattr__(
            self, "content_sha256", _optional_sha256(self.content_sha256, "content_sha256")
        )
        if self.size_bytes is not None:
            object.__setattr__(
                self, "size_bytes", _nonneg_int(self.size_bytes, "size_bytes")
            )
        object.__setattr__(
            self, "artifact_id", _optional_identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "parent_entry_ids",
            _tuple_of_str(self.parent_entry_ids, "parent_entry_ids", max_items=64),
        )
        object.__setattr__(
            self,
            "parent_artifact_ids",
            _tuple_of_str(self.parent_artifact_ids, "parent_artifact_ids", max_items=64),
        )
        object.__setattr__(
            self,
            "related_entry_ids",
            _tuple_of_str(self.related_entry_ids, "related_entry_ids", max_items=64),
        )
        object.__setattr__(
            self,
            "source_receipt_id",
            _optional_identifier(self.source_receipt_id, "source_receipt_id"),
        )
        object.__setattr__(
            self, "channel", _coerce_enum(LedgerChannel, self.channel, "channel")
        )
        object.__setattr__(
            self,
            "classification",
            _coerce_enum(
                DisclosureClassification, self.classification, "classification"
            ),
        )
        object.__setattr__(
            self, "media_type", _optional_str(self.media_type, "media_type", max_len=256)
        )
        if self.event_kind is not None:
            object.__setattr__(
                self,
                "event_kind",
                _coerce_enum(MatterEventKind, self.event_kind, "event_kind"),
            )
        object.__setattr__(
            self, "event_utc", _optional_utc(self.event_utc, "event_utc")
        )
        object.__setattr__(
            self, "admitted_utc", _require_utc(self.admitted_utc, "admitted_utc")
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=64)
        )
        object.__setattr__(
            self, "notes", _tuple_of_str(self.notes, "notes", max_items=32)
        )

        # Authority invariant: derivatives must declare a parent when present.
        if (
            self.authority_relation
            in (AuthorityRelation.DERIVATIVE, AuthorityRelation.DERIVED_FROM)
            and self.presence is LedgerPresence.PRESENT
            and not self.parent_artifact_ids
            and not self.parent_entry_ids
            and not self.labels.get("parent_logical_id")
        ):
            # Soft note only — reconcile will emit an explicit gap/conflict.
            # Construction still allowed so inputs are never dropped.
            pass

    @property
    def is_authoritative_original(self) -> bool:
        return self.authority_relation is AuthorityRelation.AUTHORITATIVE_ORIGINAL

    @property
    def is_derivative(self) -> bool:
        return self.authority_relation in (
            AuthorityRelation.DERIVATIVE,
            AuthorityRelation.DERIVED_FROM,
        )

    def identity_payload(self) -> dict[str, Any]:
        """Fields that define content-addressed identity (exclude admitted_utc)."""
        return {
            "artifact_id": self.artifact_id,
            "authority_relation": self.authority_relation.value,
            "channel": self.channel.value,
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "event_kind": self.event_kind.value if self.event_kind else None,
            "event_utc": self.event_utc,
            "item_kind": self.item_kind.value,
            "labels": dict(self.labels),
            "logical_id": self.logical_id,
            "matter_id": self.matter_id,
            "media_type": self.media_type,
            "parent_artifact_ids": list(self.parent_artifact_ids),
            "parent_entry_ids": list(self.parent_entry_ids),
            "presence": self.presence.value,
            "schema_version": self.schema_version,
            "size_bytes": self.size_bytes,
            "source_receipt_id": self.source_receipt_id,
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_utc": self.admitted_utc,
            "artifact_id": self.artifact_id,
            "authority_relation": self.authority_relation.value,
            "channel": self.channel.value,
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "entry_id": self.entry_id,
            "event_kind": self.event_kind.value if self.event_kind else None,
            "event_utc": self.event_utc,
            "item_kind": self.item_kind.value,
            "labels": dict(self.labels),
            "logical_id": self.logical_id,
            "matter_id": self.matter_id,
            "media_type": self.media_type,
            "notes": list(self.notes),
            "parent_artifact_ids": list(self.parent_artifact_ids),
            "parent_entry_ids": list(self.parent_entry_ids),
            "presence": self.presence.value,
            "related_entry_ids": list(self.related_entry_ids),
            "schema_version": self.schema_version,
            "size_bytes": self.size_bytes,
            "source_receipt_id": self.source_receipt_id,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LedgerEntry":
        if not isinstance(value, Mapping):
            raise TypeError("LedgerEntry must be a mapping")
        event_kind = value.get("event_kind")
        return cls(
            schema_version=value.get("schema_version", MATTER_LEDGER_SCHEMA_VERSION),
            entry_id=value.get("entry_id", ""),
            matter_id=value.get("matter_id", ""),
            logical_id=value.get("logical_id", ""),
            item_kind=value.get("item_kind", LedgerItemKind.OTHER.value),
            authority_relation=value.get(
                "authority_relation", AuthorityRelation.UNKNOWN.value
            ),
            presence=value.get("presence", LedgerPresence.PRESENT.value),
            version=int(value.get("version") or 1),
            content_sha256=value.get("content_sha256"),
            size_bytes=value.get("size_bytes"),
            artifact_id=value.get("artifact_id"),
            parent_entry_ids=tuple(value.get("parent_entry_ids") or ()),
            parent_artifact_ids=tuple(value.get("parent_artifact_ids") or ()),
            related_entry_ids=tuple(value.get("related_entry_ids") or ()),
            source_receipt_id=value.get("source_receipt_id"),
            channel=value.get("channel", LedgerChannel.UNKNOWN.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            media_type=value.get("media_type"),
            event_kind=event_kind,
            event_utc=value.get("event_utc"),
            admitted_utc=value.get("admitted_utc", ""),
            labels=value.get("labels") or {},
            notes=tuple(value.get("notes") or ()),
        )


@dataclass(frozen=True, slots=True)
class LedgerConflict:
    """Explicit conflict that must never be collapsed away."""

    schema_version: str
    conflict_id: str
    matter_id: str
    code: ConflictCode
    entry_ids: tuple[str, ...]
    message: str
    recorded_utc: str
    details: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != MATTER_LEDGER_SCHEMA_VERSION:
            raise MatterLedgerError(
                f"LedgerConflict.schema_version must be {MATTER_LEDGER_SCHEMA_VERSION}",
                code="schema_version_mismatch",
            )
        object.__setattr__(
            self, "conflict_id", _identifier(self.conflict_id, "conflict_id")
        )
        object.__setattr__(self, "matter_id", _identifier(self.matter_id, "matter_id"))
        object.__setattr__(
            self, "code", _coerce_enum(ConflictCode, self.code, "code")
        )
        object.__setattr__(
            self, "entry_ids", _tuple_of_str(self.entry_ids, "entry_ids", max_items=64)
        )
        object.__setattr__(
            self, "message", _require_str(self.message, "message", max_len=2048)
        )
        object.__setattr__(
            self, "recorded_utc", _require_utc(self.recorded_utc, "recorded_utc")
        )
        object.__setattr__(
            self, "details", _frozen_str_map(self.details, "details", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "conflict_id": self.conflict_id,
            "details": dict(self.details),
            "entry_ids": list(self.entry_ids),
            "matter_id": self.matter_id,
            "message": self.message,
            "recorded_utc": self.recorded_utc,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LedgerConflict":
        if not isinstance(value, Mapping):
            raise TypeError("LedgerConflict must be a mapping")
        return cls(
            schema_version=value.get("schema_version", MATTER_LEDGER_SCHEMA_VERSION),
            conflict_id=value.get("conflict_id", ""),
            matter_id=value.get("matter_id", ""),
            code=value.get("code", ConflictCode.AUTHORITY_CONFLICT.value),
            entry_ids=tuple(value.get("entry_ids") or ()),
            message=value.get("message", ""),
            recorded_utc=value.get("recorded_utc", ""),
            details=value.get("details") or {},
        )


@dataclass(frozen=True, slots=True)
class LedgerGap:
    """Explicit missing / delayed item. Never proof of nonreceipt."""

    schema_version: str
    gap_id: str
    matter_id: str
    code: GapCode
    interpretation: GapInterpretation
    logical_id: str
    message: str
    recorded_utc: str
    related_entry_ids: tuple[str, ...]
    is_proof_of_nonreceipt: bool
    details: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != MATTER_LEDGER_SCHEMA_VERSION:
            raise MatterLedgerError(
                f"LedgerGap.schema_version must be {MATTER_LEDGER_SCHEMA_VERSION}",
                code="schema_version_mismatch",
            )
        object.__setattr__(self, "gap_id", _identifier(self.gap_id, "gap_id"))
        object.__setattr__(self, "matter_id", _identifier(self.matter_id, "matter_id"))
        object.__setattr__(self, "code", _coerce_enum(GapCode, self.code, "code"))
        object.__setattr__(
            self,
            "interpretation",
            _coerce_enum(GapInterpretation, self.interpretation, "interpretation"),
        )
        object.__setattr__(
            self, "logical_id", _identifier(self.logical_id, "logical_id")
        )
        object.__setattr__(
            self, "message", _require_str(self.message, "message", max_len=2048)
        )
        object.__setattr__(
            self, "recorded_utc", _require_utc(self.recorded_utc, "recorded_utc")
        )
        object.__setattr__(
            self,
            "related_entry_ids",
            _tuple_of_str(self.related_entry_ids, "related_entry_ids", max_items=64),
        )
        if not isinstance(self.is_proof_of_nonreceipt, bool):
            raise TypeError("is_proof_of_nonreceipt must be bool")
        # Hard fail-closed: gaps are never proof of nonreceipt.
        if self.is_proof_of_nonreceipt:
            raise MatterLedgerError(
                "ledger gaps must never be marked as proof of nonreceipt",
                code="gap_nonreceipt_forbidden",
            )
        object.__setattr__(
            self, "details", _frozen_str_map(self.details, "details", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "details": dict(self.details),
            "gap_id": self.gap_id,
            "interpretation": self.interpretation.value,
            "is_proof_of_nonreceipt": self.is_proof_of_nonreceipt,
            "logical_id": self.logical_id,
            "matter_id": self.matter_id,
            "message": self.message,
            "recorded_utc": self.recorded_utc,
            "related_entry_ids": list(self.related_entry_ids),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LedgerGap":
        if not isinstance(value, Mapping):
            raise TypeError("LedgerGap must be a mapping")
        return cls(
            schema_version=value.get("schema_version", MATTER_LEDGER_SCHEMA_VERSION),
            gap_id=value.get("gap_id", ""),
            matter_id=value.get("matter_id", ""),
            code=value.get("code", GapCode.EXPECTED_ITEM_ABSENT.value),
            interpretation=value.get(
                "interpretation", GapInterpretation.FRESHNESS_GAP.value
            ),
            logical_id=value.get("logical_id", ""),
            message=value.get("message", ""),
            recorded_utc=value.get("recorded_utc", ""),
            related_entry_ids=tuple(value.get("related_entry_ids") or ()),
            is_proof_of_nonreceipt=bool(value.get("is_proof_of_nonreceipt", False)),
            details=value.get("details") or {},
        )


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    """Artifact or event held out of the active matter set."""

    schema_version: str
    quarantine_id: str
    expected_matter_id: str
    observed_matter_id: str | None
    reason_codes: tuple[str, ...]
    message: str
    recorded_utc: str
    artifact_id: str | None
    content_sha256: str | None
    source_payload_digest: str
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != MATTER_LEDGER_SCHEMA_VERSION:
            raise MatterLedgerError(
                f"QuarantineRecord.schema_version must be {MATTER_LEDGER_SCHEMA_VERSION}",
                code="schema_version_mismatch",
            )
        object.__setattr__(
            self, "quarantine_id", _identifier(self.quarantine_id, "quarantine_id")
        )
        object.__setattr__(
            self,
            "expected_matter_id",
            _identifier(self.expected_matter_id, "expected_matter_id"),
        )
        object.__setattr__(
            self,
            "observed_matter_id",
            _optional_identifier(self.observed_matter_id, "observed_matter_id"),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=32),
        )
        if not self.reason_codes:
            raise MatterLedgerError(
                "quarantine requires at least one reason code",
                code="empty_quarantine_reasons",
            )
        object.__setattr__(
            self, "message", _require_str(self.message, "message", max_len=2048)
        )
        object.__setattr__(
            self, "recorded_utc", _require_utc(self.recorded_utc, "recorded_utc")
        )
        object.__setattr__(
            self, "artifact_id", _optional_identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "content_sha256",
            _optional_sha256(self.content_sha256, "content_sha256"),
        )
        object.__setattr__(
            self,
            "source_payload_digest",
            _sha256_hex(self.source_payload_digest, "source_payload_digest"),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "content_sha256": self.content_sha256,
            "expected_matter_id": self.expected_matter_id,
            "labels": dict(self.labels),
            "message": self.message,
            "observed_matter_id": self.observed_matter_id,
            "quarantine_id": self.quarantine_id,
            "reason_codes": list(self.reason_codes),
            "recorded_utc": self.recorded_utc,
            "schema_version": self.schema_version,
            "source_payload_digest": self.source_payload_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QuarantineRecord":
        if not isinstance(value, Mapping):
            raise TypeError("QuarantineRecord must be a mapping")
        return cls(
            schema_version=value.get("schema_version", MATTER_LEDGER_SCHEMA_VERSION),
            quarantine_id=value.get("quarantine_id", ""),
            expected_matter_id=value.get("expected_matter_id", ""),
            observed_matter_id=value.get("observed_matter_id"),
            reason_codes=tuple(value.get("reason_codes") or ()),
            message=value.get("message", ""),
            recorded_utc=value.get("recorded_utc", ""),
            artifact_id=value.get("artifact_id"),
            content_sha256=value.get("content_sha256"),
            source_payload_digest=value.get("source_payload_digest", ""),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Result of a single ingest attempt against the ledger."""

    disposition: IngestDisposition
    entry: LedgerEntry | None
    quarantine: QuarantineRecord | None
    conflicts: tuple[LedgerConflict, ...]
    gaps: tuple[LedgerGap, ...]
    message: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(IngestDisposition, self.disposition, "disposition"),
        )
        if self.entry is not None and not isinstance(self.entry, LedgerEntry):
            raise TypeError("entry must be LedgerEntry or None")
        if self.quarantine is not None and not isinstance(
            self.quarantine, QuarantineRecord
        ):
            raise TypeError("quarantine must be QuarantineRecord or None")
        object.__setattr__(self, "conflicts", tuple(self.conflicts or ()))
        object.__setattr__(self, "gaps", tuple(self.gaps or ()))
        object.__setattr__(
            self, "message", _optional_str(self.message, "message", max_len=2048)
        )

    @property
    def ok(self) -> bool:
        return self.disposition in (
            IngestDisposition.ADMITTED,
            IngestDisposition.DEDUPLICATED,
            IngestDisposition.VERSIONED,
            IngestDisposition.GAP_RECORDED,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflicts": [c.to_dict() for c in self.conflicts],
            "disposition": self.disposition.value,
            "entry": None if self.entry is None else self.entry.to_dict(),
            "gaps": [g.to_dict() for g in self.gaps],
            "message": self.message,
            "ok": self.ok,
            "quarantine": None
            if self.quarantine is None
            else self.quarantine.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ClaimSetVersion:
    """One immutable claim-set version bound to a matter."""

    schema_version: str
    claim_set_id: str
    matter_id: str
    version: int
    content_sha256: str
    entry_id: str
    as_of_utc: str | None
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != MATTER_LEDGER_SCHEMA_VERSION:
            raise MatterLedgerError(
                f"ClaimSetVersion.schema_version must be {MATTER_LEDGER_SCHEMA_VERSION}",
                code="schema_version_mismatch",
            )
        object.__setattr__(
            self, "claim_set_id", _identifier(self.claim_set_id, "claim_set_id")
        )
        object.__setattr__(self, "matter_id", _identifier(self.matter_id, "matter_id"))
        object.__setattr__(self, "version", _positive_int(self.version, "version"))
        object.__setattr__(
            self, "content_sha256", _sha256_hex(self.content_sha256, "content_sha256")
        )
        object.__setattr__(self, "entry_id", _identifier(self.entry_id, "entry_id"))
        object.__setattr__(
            self, "as_of_utc", _optional_utc(self.as_of_utc, "as_of_utc")
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_utc": self.as_of_utc,
            "claim_set_id": self.claim_set_id,
            "content_sha256": self.content_sha256,
            "entry_id": self.entry_id,
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "schema_version": self.schema_version,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClaimSetVersion":
        if not isinstance(value, Mapping):
            raise TypeError("ClaimSetVersion must be a mapping")
        return cls(
            schema_version=value.get("schema_version", MATTER_LEDGER_SCHEMA_VERSION),
            claim_set_id=value.get("claim_set_id", ""),
            matter_id=value.get("matter_id", ""),
            version=int(value.get("version") or 1),
            content_sha256=value.get("content_sha256", ""),
            entry_id=value.get("entry_id", ""),
            as_of_utc=value.get("as_of_utc"),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class MatterLedgerSnapshot:
    """Immutable reconciled view of one matter at a point in time.

    History is append-only: this snapshot is a projection. Prior entry versions
    remain listed under ``entries`` (all versions) while ``current_by_logical_id``
    points at the latest version per logical id among non-quarantined entries.
    """

    schema_version: str
    matter_id: str
    snapshot_id: str
    content_digest: str
    entries: tuple[LedgerEntry, ...]
    conflicts: tuple[LedgerConflict, ...]
    gaps: tuple[LedgerGap, ...]
    quarantines: tuple[QuarantineRecord, ...]
    claim_sets: tuple[ClaimSetVersion, ...]
    current_by_logical_id: Mapping[str, str]
    history_entry_ids: tuple[str, ...]
    reconciled_utc: str
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != MATTER_LEDGER_SCHEMA_VERSION:
            raise MatterLedgerError(
                f"MatterLedgerSnapshot.schema_version must be "
                f"{MATTER_LEDGER_SCHEMA_VERSION}",
                code="schema_version_mismatch",
            )
        object.__setattr__(self, "matter_id", _identifier(self.matter_id, "matter_id"))
        object.__setattr__(
            self, "snapshot_id", _identifier(self.snapshot_id, "snapshot_id")
        )
        object.__setattr__(
            self, "content_digest", _sha256_hex(self.content_digest, "content_digest")
        )
        object.__setattr__(self, "entries", tuple(self.entries or ()))
        object.__setattr__(self, "conflicts", tuple(self.conflicts or ()))
        object.__setattr__(self, "gaps", tuple(self.gaps or ()))
        object.__setattr__(self, "quarantines", tuple(self.quarantines or ()))
        object.__setattr__(self, "claim_sets", tuple(self.claim_sets or ()))
        object.__setattr__(
            self,
            "current_by_logical_id",
            _frozen_str_map(
                self.current_by_logical_id, "current_by_logical_id", max_items=4096
            ),
        )
        object.__setattr__(
            self,
            "history_entry_ids",
            _tuple_of_str(self.history_entry_ids, "history_entry_ids", max_items=8192),
        )
        object.__setattr__(
            self, "reconciled_utc", _require_utc(self.reconciled_utc, "reconciled_utc")
        )
        object.__setattr__(
            self, "notes", _tuple_of_str(self.notes, "notes", max_items=64)
        )

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)

    @property
    def has_gaps(self) -> bool:
        return bool(self.gaps)

    @property
    def has_quarantines(self) -> bool:
        return bool(self.quarantines)

    def originals(self) -> tuple[LedgerEntry, ...]:
        return tuple(e for e in self.entries if e.is_authoritative_original)

    def derivatives(self) -> tuple[LedgerEntry, ...]:
        return tuple(e for e in self.entries if e.is_derivative)

    def current_claim_set(self) -> ClaimSetVersion | None:
        if not self.claim_sets:
            return None
        return max(self.claim_sets, key=lambda c: c.version)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_sets": [c.to_dict() for c in self.claim_sets],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "content_digest": self.content_digest,
            "current_by_logical_id": dict(self.current_by_logical_id),
            "entries": [e.to_dict() for e in self.entries],
            "gaps": [g.to_dict() for g in self.gaps],
            "has_conflicts": self.has_conflicts,
            "has_gaps": self.has_gaps,
            "has_quarantines": self.has_quarantines,
            "history_entry_ids": list(self.history_entry_ids),
            "matter_id": self.matter_id,
            "notes": list(self.notes),
            "quarantines": [q.to_dict() for q in self.quarantines],
            "reconciled_utc": self.reconciled_utc,
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
        }

    def to_canonical_json(self) -> str:
        # Projection fields that are derived (has_*) omitted for digest stability.
        payload = {
            "claim_sets": [c.to_dict() for c in self.claim_sets],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "content_digest": self.content_digest,
            "current_by_logical_id": dict(self.current_by_logical_id),
            "entries": [e.to_dict() for e in self.entries],
            "gaps": [g.to_dict() for g in self.gaps],
            "history_entry_ids": list(self.history_entry_ids),
            "matter_id": self.matter_id,
            "notes": list(self.notes),
            "quarantines": [q.to_dict() for q in self.quarantines],
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
        }
        return canonical_json(payload)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MatterLedgerSnapshot":
        if not isinstance(value, Mapping):
            raise TypeError("MatterLedgerSnapshot must be a mapping")
        return cls(
            schema_version=value.get("schema_version", MATTER_LEDGER_SCHEMA_VERSION),
            matter_id=value.get("matter_id", ""),
            snapshot_id=value.get("snapshot_id", ""),
            content_digest=value.get("content_digest", ""),
            entries=tuple(
                LedgerEntry.from_dict(e) for e in (value.get("entries") or ())
            ),
            conflicts=tuple(
                LedgerConflict.from_dict(c) for c in (value.get("conflicts") or ())
            ),
            gaps=tuple(LedgerGap.from_dict(g) for g in (value.get("gaps") or ())),
            quarantines=tuple(
                QuarantineRecord.from_dict(q) for q in (value.get("quarantines") or ())
            ),
            claim_sets=tuple(
                ClaimSetVersion.from_dict(c) for c in (value.get("claim_sets") or ())
            ),
            current_by_logical_id=value.get("current_by_logical_id") or {},
            history_entry_ids=tuple(value.get("history_entry_ids") or ()),
            reconciled_utc=value.get("reconciled_utc", ""),
            notes=tuple(value.get("notes") or ()),
        )


# ---------------------------------------------------------------------------
# Append-only store
# ---------------------------------------------------------------------------


class LedgerStore(Protocol):
    """Append-only persistence surface for one or more matters."""

    def list_entry_ids(self, matter_id: str) -> tuple[str, ...]:
        ...

    def get_entry(self, matter_id: str, entry_id: str) -> LedgerEntry | None:
        ...

    def list_entries(self, matter_id: str) -> tuple[LedgerEntry, ...]:
        ...

    def append_entry(self, entry: LedgerEntry) -> bool:
        """Append if new. Return False when entry_id already present (no overwrite)."""
        ...

    def list_conflicts(self, matter_id: str) -> tuple[LedgerConflict, ...]:
        ...

    def append_conflict(self, conflict: LedgerConflict) -> bool:
        ...

    def list_gaps(self, matter_id: str) -> tuple[LedgerGap, ...]:
        ...

    def append_gap(self, gap: LedgerGap) -> bool:
        ...

    def list_quarantines(self, matter_id: str) -> tuple[QuarantineRecord, ...]:
        ...

    def append_quarantine(self, record: QuarantineRecord) -> bool:
        ...

    def list_claim_sets(self, matter_id: str) -> tuple[ClaimSetVersion, ...]:
        ...

    def append_claim_set(self, claim_set: ClaimSetVersion) -> bool:
        ...


class InMemoryLedgerStore:
    """Thread-safe in-memory append-only ledger store.

    Existing records are never mutated or replaced. Duplicate appends are
    no-ops that return ``False``.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[str, dict[str, LedgerEntry]] = {}
        self._entry_order: dict[str, list[str]] = {}
        self._conflicts: dict[str, dict[str, LedgerConflict]] = {}
        self._conflict_order: dict[str, list[str]] = {}
        self._gaps: dict[str, dict[str, LedgerGap]] = {}
        self._gap_order: dict[str, list[str]] = {}
        self._quarantines: dict[str, dict[str, QuarantineRecord]] = {}
        self._quarantine_order: dict[str, list[str]] = {}
        self._claim_sets: dict[str, dict[str, ClaimSetVersion]] = {}
        self._claim_set_order: dict[str, list[str]] = {}

    def list_entry_ids(self, matter_id: str) -> tuple[str, ...]:
        mid = normalize_matter_key(matter_id)
        with self._lock:
            return tuple(self._entry_order.get(mid, ()))

    def get_entry(self, matter_id: str, entry_id: str) -> LedgerEntry | None:
        mid = normalize_matter_key(matter_id)
        with self._lock:
            return self._entries.get(mid, {}).get(entry_id)

    def list_entries(self, matter_id: str) -> tuple[LedgerEntry, ...]:
        mid = normalize_matter_key(matter_id)
        with self._lock:
            order = self._entry_order.get(mid, ())
            bag = self._entries.get(mid, {})
            return tuple(bag[eid] for eid in order if eid in bag)

    def append_entry(self, entry: LedgerEntry) -> bool:
        if not isinstance(entry, LedgerEntry):
            raise TypeError("entry must be LedgerEntry")
        mid = entry.matter_id
        with self._lock:
            bag = self._entries.setdefault(mid, {})
            if entry.entry_id in bag:
                existing = bag[entry.entry_id]
                # Never overwrite. Identity must match if ids collide.
                if existing.to_dict() != entry.to_dict():
                    # Same id, different body is a hard error (content-addressed ids
                    # should make this impossible for well-formed callers).
                    raise MatterLedgerError(
                        f"entry_id collision with differing payload: {entry.entry_id}",
                        code="entry_id_collision",
                    )
                return False
            bag[entry.entry_id] = entry
            self._entry_order.setdefault(mid, []).append(entry.entry_id)
            return True

    def list_conflicts(self, matter_id: str) -> tuple[LedgerConflict, ...]:
        mid = normalize_matter_key(matter_id)
        with self._lock:
            order = self._conflict_order.get(mid, ())
            bag = self._conflicts.get(mid, {})
            return tuple(bag[cid] for cid in order if cid in bag)

    def append_conflict(self, conflict: LedgerConflict) -> bool:
        mid = conflict.matter_id
        with self._lock:
            bag = self._conflicts.setdefault(mid, {})
            if conflict.conflict_id in bag:
                return False
            bag[conflict.conflict_id] = conflict
            self._conflict_order.setdefault(mid, []).append(conflict.conflict_id)
            return True

    def list_gaps(self, matter_id: str) -> tuple[LedgerGap, ...]:
        mid = normalize_matter_key(matter_id)
        with self._lock:
            order = self._gap_order.get(mid, ())
            bag = self._gaps.get(mid, {})
            return tuple(bag[gid] for gid in order if gid in bag)

    def append_gap(self, gap: LedgerGap) -> bool:
        mid = gap.matter_id
        with self._lock:
            bag = self._gaps.setdefault(mid, {})
            if gap.gap_id in bag:
                return False
            bag[gap.gap_id] = gap
            self._gap_order.setdefault(mid, []).append(gap.gap_id)
            return True

    def list_quarantines(self, matter_id: str) -> tuple[QuarantineRecord, ...]:
        mid = normalize_matter_key(matter_id)
        with self._lock:
            order = self._quarantine_order.get(mid, ())
            bag = self._quarantines.get(mid, {})
            return tuple(bag[qid] for qid in order if qid in bag)

    def append_quarantine(self, record: QuarantineRecord) -> bool:
        mid = record.expected_matter_id
        with self._lock:
            bag = self._quarantines.setdefault(mid, {})
            if record.quarantine_id in bag:
                return False
            bag[record.quarantine_id] = record
            self._quarantine_order.setdefault(mid, []).append(record.quarantine_id)
            return True

    def list_claim_sets(self, matter_id: str) -> tuple[ClaimSetVersion, ...]:
        mid = normalize_matter_key(matter_id)
        with self._lock:
            order = self._claim_set_order.get(mid, ())
            bag = self._claim_sets.get(mid, {})
            return tuple(bag[cid] for cid in order if cid in bag)

    def append_claim_set(self, claim_set: ClaimSetVersion) -> bool:
        mid = claim_set.matter_id
        with self._lock:
            bag = self._claim_sets.setdefault(mid, {})
            if claim_set.claim_set_id in bag:
                return False
            bag[claim_set.claim_set_id] = claim_set
            self._claim_set_order.setdefault(mid, []).append(claim_set.claim_set_id)
            return True


# ---------------------------------------------------------------------------
# MatterLedger
# ---------------------------------------------------------------------------


def _logical_id_for_artifact(
    *,
    artifact_id: str | None,
    labels: Mapping[str, str],
    content_sha256: str | None,
    item_kind: LedgerItemKind,
) -> str:
    if labels.get(_LABEL_LOGICAL_ID):
        return _identifier(labels[_LABEL_LOGICAL_ID], "logical_id")
    if labels.get(_LABEL_SOURCE_DOCUMENT_ID):
        return _identifier(labels[_LABEL_SOURCE_DOCUMENT_ID], "logical_id")
    if artifact_id:
        return _identifier(artifact_id, "logical_id")
    if content_sha256:
        return f"{item_kind.value}:{content_sha256[:16]}"
    return f"{item_kind.value}:anonymous"


def _build_entry_id(
    *,
    matter_id: str,
    logical_id: str,
    version: int,
    content_sha256: str | None,
    item_kind: LedgerItemKind,
    authority_relation: AuthorityRelation,
    presence: LedgerPresence,
) -> str:
    return content_addressed_id(
        "le",
        {
            "authority_relation": authority_relation.value,
            "content_sha256": content_sha256,
            "item_kind": item_kind.value,
            "logical_id": logical_id,
            "matter_id": matter_id,
            "presence": presence.value,
            "schema_version": MATTER_LEDGER_SCHEMA_VERSION,
            "version": version,
        },
    )


class MatterLedger:
    """Reconcile originals, derivatives, receipts, status, and versions.

    The ledger is append-only. Ingesting the same content again is an
    idempotent deduplication. Changed content for the same logical id creates a
    new version entry; prior versions are retained forever.

    Wrong matter identifiers and unknown-classification quarantine signals are
    recorded under :class:`QuarantineRecord` and never enter the active matter
    entry set for that matter_id.
    """

    schema_version: str = MATTER_LEDGER_SCHEMA_VERSION
    interface: str = MATTER_LEDGER_INTERFACE

    def __init__(
        self,
        store: LedgerStore | None = None,
        *,
        wall_clock: Callable[[], str] | None = None,
    ) -> None:
        self._store: LedgerStore = store if store is not None else InMemoryLedgerStore()
        self._clock: Callable[[], str] = wall_clock or _utc_now_iso
        self._lock = threading.RLock()

    @property
    def store(self) -> LedgerStore:
        return self._store

    # -- ingest surfaces -----------------------------------------------------

    def ingest_artifact(
        self,
        *,
        matter_id: str,
        manifest: ArtifactManifest | Mapping[str, Any],
        item_kind: LedgerItemKind | str | None = None,
        channel: LedgerChannel | str = LedgerChannel.PRIVATE_IMPORT,
        logical_id: str | None = None,
        notes: Sequence[str] = (),
        force_quarantine: bool = False,
    ) -> IngestResult:
        """Admit an :class:`ArtifactManifest` into the matter ledger.

        When ``manifest.matter_id`` disagrees with *matter_id*, the artifact is
        quarantined and not added to the active entry set.
        """
        mid = normalize_matter_key(matter_id)
        man = (
            manifest
            if isinstance(manifest, ArtifactManifest)
            else ArtifactManifest.from_dict(manifest)
        )
        ch = _coerce_enum(LedgerChannel, channel, "channel")
        labels = dict(man.labels)
        kind = infer_item_kind(
            authority_relation=man.authority_relation,
            media_type=man.media_type,
            labels=labels,
            explicit=item_kind,
        )
        now = self._clock()

        # Wrong matter id → quarantine (never admit to active set).
        if force_quarantine or not matter_ids_compatible(mid, man.matter_id):
            return self._quarantine(
                expected_matter_id=mid,
                observed_matter_id=man.matter_id,
                reason_codes=("wrong_matter_id",),
                message=(
                    f"artifact {man.artifact_id} matter_id {man.matter_id!r} "
                    f"does not match ledger matter {mid!r}; quarantined"
                ),
                artifact_id=man.artifact_id,
                content_sha256=man.sha256,
                source_payload=man.to_dict(),
                labels=labels,
                recorded_utc=now,
            )

        # Unknown classification still admits as present but with a note; privacy
        # quarantine of bytes is owned by private_store / privacy modules.
        lid = (
            _identifier(logical_id, "logical_id")
            if logical_id
            else _logical_id_for_artifact(
                artifact_id=man.artifact_id,
                labels=labels,
                content_sha256=man.sha256,
                item_kind=kind,
            )
        )

        return self._admit_entry(
            matter_id=mid,
            logical_id=lid,
            item_kind=kind,
            authority_relation=man.authority_relation,
            presence=LedgerPresence.PRESENT,
            content_sha256=man.sha256,
            size_bytes=man.size_bytes,
            artifact_id=man.artifact_id,
            parent_artifact_ids=man.parent_artifact_ids,
            source_receipt_id=man.source_receipt_id,
            channel=ch,
            classification=man.classification,
            media_type=man.media_type,
            event_kind=None,
            event_utc=None,
            labels=labels,
            notes=tuple(notes)
            + (
                ("unknown classification retained; privacy gate owns dispatch",)
                if requires_quarantine(man.classification)
                else ()
            ),
            admitted_utc=now,
        )

    def ingest_event(
        self,
        *,
        matter_id: str | None = None,
        event: MatterEvent | Mapping[str, Any],
        channel: LedgerChannel | str = LedgerChannel.STATUS_API,
        notes: Sequence[str] = (),
    ) -> IngestResult:
        """Admit a :class:`MatterEvent` (status / transaction / other)."""
        ev = event if isinstance(event, MatterEvent) else MatterEvent.from_dict(event)
        mid = normalize_matter_key(matter_id or ev.matter_id)
        ch = _coerce_enum(LedgerChannel, channel, "channel")
        now = self._clock()

        if not matter_ids_compatible(mid, ev.matter_id):
            return self._quarantine(
                expected_matter_id=mid,
                observed_matter_id=ev.matter_id,
                reason_codes=("wrong_matter_id",),
                message=(
                    f"event {ev.event_id} matter_id {ev.matter_id!r} does not "
                    f"match ledger matter {mid!r}; quarantined"
                ),
                artifact_id=None,
                content_sha256=ev.description_digest,
                source_payload=ev.to_dict(),
                labels=dict(ev.metadata),
                recorded_utc=now,
            )

        if ev.kind is MatterEventKind.STATUS:
            kind = LedgerItemKind.STATUS_EVENT
        elif ev.kind is MatterEventKind.TRANSACTION:
            kind = LedgerItemKind.TRANSACTION_EVENT
        else:
            kind = LedgerItemKind.OTHER

        digest = ev.description_digest
        if digest is None:
            digest = hashlib.sha256(
                canonical_json(ev.to_dict()).encode("utf-8")
            ).hexdigest()

        return self._admit_entry(
            matter_id=mid,
            logical_id=ev.event_id,
            item_kind=kind,
            authority_relation=AuthorityRelation.AUTHORITATIVE_ORIGINAL,
            presence=LedgerPresence.PRESENT,
            content_sha256=digest,
            size_bytes=None,
            artifact_id=None,
            parent_artifact_ids=(),
            source_receipt_id=ev.source_receipt_id,
            channel=ch,
            classification=ev.classification,
            media_type=None,
            event_kind=ev.kind,
            event_utc=ev.event_utc,
            labels=dict(ev.metadata),
            notes=tuple(notes),
            admitted_utc=now,
            related_entry_ids=(),
            extra_related_artifact_ids=ev.related_artifact_ids,
        )

    def ingest_inventory_item(
        self,
        *,
        matter_id: str,
        source_document_id: str,
        available: bool,
        content_sha256: str | None = None,
        size_bytes: int | None = None,
        media_type: str | None = None,
        artifact_id: str | None = None,
        authority_relation: AuthorityRelation | str = AuthorityRelation.AUTHORITATIVE_ORIGINAL,
        classification: DisclosureClassification | str = DisclosureClassification.PUBLIC_OFFICIAL,
        channel: LedgerChannel | str = LedgerChannel.PUBLIC_FILE_WRAPPER,
        delayed: bool = False,
        gap_code: GapCode | str | None = None,
        labels: Mapping[str, str] | None = None,
        source_receipt_id: str | None = None,
        notes: Sequence[str] = (),
    ) -> IngestResult:
        """Record a file-wrapper inventory row, with or without admitted bytes.

        When *available* is false, a :class:`LedgerGap` is recorded with
        ``is_proof_of_nonreceipt=False`` (freshness / retrieval gap).
        """
        mid = normalize_matter_key(matter_id)
        logical_id = _identifier(source_document_id, "source_document_id")
        ch = _coerce_enum(LedgerChannel, channel, "channel")
        rel = _coerce_enum(AuthorityRelation, authority_relation, "authority_relation")
        cls = _coerce_enum(DisclosureClassification, classification, "classification")
        now = self._clock()
        label_map = dict(labels or {})
        label_map.setdefault(_LABEL_SOURCE_DOCUMENT_ID, logical_id)

        if available:
            if not content_sha256:
                raise MatterLedgerError(
                    "available inventory items require content_sha256",
                    code="missing_content_sha256",
                )
            return self._admit_entry(
                matter_id=mid,
                logical_id=logical_id,
                item_kind=LedgerItemKind.FILE_WRAPPER_DOCUMENT,
                authority_relation=rel,
                presence=LedgerPresence.PRESENT,
                content_sha256=content_sha256,
                size_bytes=size_bytes,
                artifact_id=artifact_id,
                parent_artifact_ids=(),
                source_receipt_id=source_receipt_id,
                channel=ch,
                classification=cls,
                media_type=media_type,
                event_kind=None,
                event_utc=None,
                labels=label_map,
                notes=tuple(notes),
                admitted_utc=now,
            )

        presence = LedgerPresence.DELAYED if delayed else LedgerPresence.MISSING
        code = _coerce_enum(
            GapCode,
            gap_code
            or (
                GapCode.DELAYED_PUBLICATION
                if delayed
                else GapCode.INVENTORY_WITHOUT_BYTES
            ),
            "gap_code",
        )
        interpretation = (
            GapInterpretation.FRESHNESS_GAP
            if delayed or code is GapCode.DELAYED_PUBLICATION
            else GapInterpretation.RETRIEVAL_GAP
        )
        message = (
            f"file-wrapper inventory lists {logical_id} but bytes are "
            f"{'delayed' if delayed else 'not yet available'}; this is a "
            f"retrieval freshness gap, not proof of nonreceipt"
        )
        entry_result = self._admit_entry(
            matter_id=mid,
            logical_id=logical_id,
            item_kind=LedgerItemKind.INVENTORY_PLACEHOLDER,
            authority_relation=rel,
            presence=presence,
            content_sha256=content_sha256,
            size_bytes=size_bytes,
            artifact_id=artifact_id,
            parent_artifact_ids=(),
            source_receipt_id=source_receipt_id,
            channel=ch,
            classification=cls,
            media_type=media_type,
            event_kind=None,
            event_utc=None,
            labels=label_map,
            notes=tuple(notes) + (message,),
            admitted_utc=now,
        )
        gap = self._record_gap(
            matter_id=mid,
            code=code,
            interpretation=interpretation,
            logical_id=logical_id,
            message=message,
            recorded_utc=now,
            related_entry_ids=(
                (entry_result.entry.entry_id,) if entry_result.entry else ()
            ),
            details={
                "available": "false",
                "delayed": "true" if delayed else "false",
                "source_document_id": logical_id,
            },
        )
        return IngestResult(
            disposition=IngestDisposition.GAP_RECORDED,
            entry=entry_result.entry,
            quarantine=None,
            conflicts=entry_result.conflicts,
            gaps=(gap,) + entry_result.gaps,
            message=message,
        )

    def ingest_source_receipt(
        self,
        *,
        matter_id: str,
        receipt: SourceReceipt | Mapping[str, Any],
        item_kind: LedgerItemKind | str = LedgerItemKind.ACKNOWLEDGEMENT,
        channel: LedgerChannel | str = LedgerChannel.PRIVATE_IMPORT,
        labels: Mapping[str, str] | None = None,
        notes: Sequence[str] = (),
    ) -> IngestResult:
        """Admit a sanitized :class:`SourceReceipt` as a ledger item."""
        mid = normalize_matter_key(matter_id)
        rec = (
            receipt
            if isinstance(receipt, SourceReceipt)
            else SourceReceipt.from_dict(receipt)
        )
        ch = _coerce_enum(LedgerChannel, channel, "channel")
        kind = _coerce_enum(LedgerItemKind, item_kind, "item_kind")
        now = self._clock()
        label_map = dict(labels or {})
        label_map.setdefault("endpoint", rec.endpoint[:256])
        digest = rec.response_digest or rec.request_digest
        return self._admit_entry(
            matter_id=mid,
            logical_id=rec.receipt_id,
            item_kind=kind,
            authority_relation=AuthorityRelation.AUTHORITATIVE_ORIGINAL,
            presence=LedgerPresence.PRESENT,
            content_sha256=digest,
            size_bytes=None,
            artifact_id=None,
            parent_artifact_ids=(),
            source_receipt_id=rec.receipt_id,
            channel=ch,
            classification=DisclosureClassification.PUBLIC_USER,
            media_type="application/json",
            event_kind=None,
            event_utc=rec.retrieval_utc
            if _ISO_UTC_RE.match(rec.retrieval_utc)
            else None,
            labels=label_map,
            notes=tuple(notes),
            admitted_utc=now,
        )

    def link_derivative(
        self,
        *,
        matter_id: str,
        original_entry_id: str,
        derivative_entry_id: str,
    ) -> IngestResult:
        """Record an explicit original→derivative link without mutating history.

        Creates a new derivative version that references the original when the
        existing derivative lacks a parent link. The prior derivative entry is
        retained (append-only).
        """
        mid = normalize_matter_key(matter_id)
        original = self._store.get_entry(mid, original_entry_id)
        derivative = self._store.get_entry(mid, derivative_entry_id)
        now = self._clock()
        if original is None or derivative is None:
            raise MatterLedgerError(
                "both original and derivative entry ids must already exist",
                code="missing_link_target",
            )
        if not original.is_authoritative_original:
            conflict = self._record_conflict(
                matter_id=mid,
                code=ConflictCode.RELATION_INVERSION,
                entry_ids=(original.entry_id, derivative.entry_id),
                message=(
                    f"link_derivative requires authoritative original; "
                    f"{original.entry_id} has relation "
                    f"{original.authority_relation.value}"
                ),
                recorded_utc=now,
                details={"original_relation": original.authority_relation.value},
            )
            return IngestResult(
                disposition=IngestDisposition.CONFLICT,
                entry=derivative,
                quarantine=None,
                conflicts=(conflict,),
                gaps=(),
                message=conflict.message,
            )

        if (
            derivative.parent_entry_ids == (original.entry_id,)
            and original.artifact_id
            and original.artifact_id in derivative.parent_artifact_ids
        ):
            return IngestResult(
                disposition=IngestDisposition.DEDUPLICATED,
                entry=derivative,
                quarantine=None,
                conflicts=(),
                gaps=(),
                message="derivative already linked to original",
            )

        # Append a new derivative version with parent linkage (history preserved).
        parent_artifacts = tuple(
            dict.fromkeys(
                (
                    *derivative.parent_artifact_ids,
                    *(
                        (original.artifact_id,)
                        if original.artifact_id
                        else ()
                    ),
                )
            )
        )
        return self._admit_entry(
            matter_id=mid,
            logical_id=derivative.logical_id,
            item_kind=LedgerItemKind.CONVERTED_RENDERING
            if derivative.item_kind
            in (LedgerItemKind.CONVERTED_RENDERING, LedgerItemKind.OTHER)
            else derivative.item_kind,
            authority_relation=AuthorityRelation.DERIVATIVE,
            presence=derivative.presence,
            content_sha256=derivative.content_sha256,
            size_bytes=derivative.size_bytes,
            artifact_id=derivative.artifact_id,
            parent_artifact_ids=parent_artifacts,
            parent_entry_ids=(original.entry_id,),
            source_receipt_id=derivative.source_receipt_id,
            channel=LedgerChannel.DERIVED,
            classification=derivative.classification,
            media_type=derivative.media_type,
            event_kind=None,
            event_utc=None,
            labels=dict(derivative.labels)
            | {
                "linked_original_entry_id": original.entry_id,
                "conversion_pair_role": "derivative",
            },
            notes=derivative.notes
            + (f"linked as derivative of {original.entry_id}",),
            admitted_utc=now,
            related_entry_ids=(original.entry_id,),
            force_new_version=True,
        )

    def record_claim_set(
        self,
        *,
        matter_id: str,
        content_sha256: str,
        artifact_id: str | None = None,
        as_of_utc: str | None = None,
        labels: Mapping[str, str] | None = None,
        notes: Sequence[str] = (),
        channel: LedgerChannel | str = LedgerChannel.PRIVATE_IMPORT,
        classification: DisclosureClassification
        | str = DisclosureClassification.CONFIDENTIAL_APPLICATION,
    ) -> IngestResult:
        """Admit a claim-set version; newer content creates a new version."""
        mid = normalize_matter_key(matter_id)
        digest = _sha256_hex(content_sha256, "content_sha256")
        ch = _coerce_enum(LedgerChannel, channel, "channel")
        cls = _coerce_enum(DisclosureClassification, classification, "classification")
        now = self._clock()
        label_map = dict(labels or {})
        label_map.setdefault(_LABEL_CLAIM_SET, "true")
        result = self._admit_entry(
            matter_id=mid,
            logical_id="claim-set:current",
            item_kind=LedgerItemKind.CLAIM_SET,
            authority_relation=AuthorityRelation.AUTHORITATIVE_ORIGINAL,
            presence=LedgerPresence.PRESENT,
            content_sha256=digest,
            size_bytes=None,
            artifact_id=artifact_id,
            parent_artifact_ids=(),
            source_receipt_id=None,
            channel=ch,
            classification=cls,
            media_type=label_map.get("media_type"),
            event_kind=None,
            event_utc=as_of_utc,
            labels=label_map,
            notes=tuple(notes),
            admitted_utc=now,
        )
        if result.entry is not None and result.disposition in (
            IngestDisposition.ADMITTED,
            IngestDisposition.VERSIONED,
            IngestDisposition.DEDUPLICATED,
        ):
            claim = ClaimSetVersion(
                schema_version=MATTER_LEDGER_SCHEMA_VERSION,
                claim_set_id=content_addressed_id(
                    "cs",
                    {
                        "content_sha256": digest,
                        "matter_id": mid,
                        "version": result.entry.version,
                    },
                ),
                matter_id=mid,
                version=result.entry.version,
                content_sha256=digest,
                entry_id=result.entry.entry_id,
                as_of_utc=as_of_utc,
                labels=label_map,
            )
            self._store.append_claim_set(claim)
        return result

    def record_amendment(
        self,
        *,
        matter_id: str,
        content_sha256: str,
        logical_id: str,
        artifact_id: str | None = None,
        parent_artifact_ids: Sequence[str] = (),
        labels: Mapping[str, str] | None = None,
        notes: Sequence[str] = (),
        channel: LedgerChannel | str = LedgerChannel.PRIVATE_IMPORT,
        classification: DisclosureClassification
        | str = DisclosureClassification.CONFIDENTIAL_APPLICATION,
        event_utc: str | None = None,
    ) -> IngestResult:
        """Admit an amendment artifact as an authoritative original version."""
        mid = normalize_matter_key(matter_id)
        digest = _sha256_hex(content_sha256, "content_sha256")
        lid = _identifier(logical_id, "logical_id")
        ch = _coerce_enum(LedgerChannel, channel, "channel")
        cls = _coerce_enum(DisclosureClassification, classification, "classification")
        now = self._clock()
        label_map = dict(labels or {})
        label_map.setdefault(_LABEL_AMENDMENT, "true")
        return self._admit_entry(
            matter_id=mid,
            logical_id=lid,
            item_kind=LedgerItemKind.AMENDMENT,
            authority_relation=AuthorityRelation.AUTHORITATIVE_ORIGINAL,
            presence=LedgerPresence.PRESENT,
            content_sha256=digest,
            size_bytes=None,
            artifact_id=artifact_id,
            parent_artifact_ids=tuple(parent_artifact_ids),
            source_receipt_id=None,
            channel=ch,
            classification=cls,
            media_type=label_map.get("media_type"),
            event_kind=MatterEventKind.RESPONSE,
            event_utc=event_utc,
            labels=label_map,
            notes=tuple(notes),
            admitted_utc=now,
        )

    def ingest_gui_metadata(
        self,
        *,
        matter_id: str,
        logical_id: str,
        metadata: Mapping[str, str],
        content_sha256: str | None = None,
        channel: LedgerChannel | str = LedgerChannel.PRIVATE_IMPORT,
        notes: Sequence[str] = (),
    ) -> IngestResult:
        """Admit GUI / export metadata as an explicit ledger item."""
        mid = normalize_matter_key(matter_id)
        lid = _identifier(logical_id, "logical_id")
        ch = _coerce_enum(LedgerChannel, channel, "channel")
        now = self._clock()
        meta = {str(k): str(v) for k, v in dict(metadata or {}).items()}
        digest = content_sha256 or hashlib.sha256(
            canonical_json(meta).encode("utf-8")
        ).hexdigest()
        labels = dict(meta)
        labels.setdefault(_LABEL_ROLE, "gui_metadata")
        return self._admit_entry(
            matter_id=mid,
            logical_id=lid,
            item_kind=LedgerItemKind.GUI_METADATA,
            authority_relation=AuthorityRelation.AUTHORITATIVE_ORIGINAL,
            presence=LedgerPresence.PRESENT,
            content_sha256=digest,
            size_bytes=None,
            artifact_id=None,
            parent_artifact_ids=(),
            source_receipt_id=None,
            channel=ch,
            classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
            media_type="application/json",
            event_kind=None,
            event_utc=None,
            labels=labels,
            notes=tuple(notes),
            admitted_utc=now,
        )

    # -- reconciliation ------------------------------------------------------

    def reconcile(self, matter_id: str) -> MatterLedgerSnapshot:
        """Build an immutable snapshot with explicit conflicts and gaps.

        Re-runs structural checks (orphan derivatives, dual originals for the
        same conversion family, missing parents) and appends any newly found
        conflict / gap records without mutating existing entries.
        """
        mid = normalize_matter_key(matter_id)
        with self._lock:
            self._structural_reconcile(mid)
            entries = self._store.list_entries(mid)
            conflicts = self._store.list_conflicts(mid)
            gaps = self._store.list_gaps(mid)
            quarantines = self._store.list_quarantines(mid)
            claim_sets = self._store.list_claim_sets(mid)

            # Sort for deterministic projection.
            entries_sorted = tuple(
                sorted(
                    entries,
                    key=lambda e: (
                        e.logical_id,
                        e.version,
                        e.entry_id,
                    ),
                )
            )
            conflicts_sorted = tuple(
                sorted(conflicts, key=lambda c: (c.code.value, c.conflict_id))
            )
            gaps_sorted = tuple(
                sorted(gaps, key=lambda g: (g.code.value, g.gap_id))
            )
            quarantines_sorted = tuple(
                sorted(quarantines, key=lambda q: q.quarantine_id)
            )
            claim_sets_sorted = tuple(
                sorted(claim_sets, key=lambda c: (c.version, c.claim_set_id))
            )

            current: dict[str, str] = {}
            for entry in entries_sorted:
                if entry.presence is LedgerPresence.QUARANTINED:
                    continue
                prev_id = current.get(entry.logical_id)
                if prev_id is None:
                    current[entry.logical_id] = entry.entry_id
                    continue
                prev = next(e for e in entries_sorted if e.entry_id == prev_id)
                if entry.version >= prev.version:
                    current[entry.logical_id] = entry.entry_id

            history_ids = tuple(e.entry_id for e in entries_sorted)
            notes: list[str] = []
            if conflicts_sorted:
                notes.append(f"{len(conflicts_sorted)} explicit conflict(s) retained")
            if gaps_sorted:
                notes.append(
                    f"{len(gaps_sorted)} missing/delayed gap(s) retained "
                    f"(not proof of nonreceipt)"
                )
            if quarantines_sorted:
                notes.append(
                    f"{len(quarantines_sorted)} quarantined item(s) held out of "
                    f"active matter set"
                )

            # Content digest is clock-independent: observational timestamps
            # (admitted_utc / recorded_utc / reconciled_utc) are excluded so
            # replay under different wall clocks yields the same digest.
            body = {
                "claim_sets": [
                    {
                        "claim_set_id": c.claim_set_id,
                        "content_sha256": c.content_sha256,
                        "entry_id": c.entry_id,
                        "labels": dict(c.labels),
                        "matter_id": c.matter_id,
                        "version": c.version,
                    }
                    for c in claim_sets_sorted
                ],
                "conflicts": [
                    {
                        "code": c.code.value,
                        "conflict_id": c.conflict_id,
                        "details": dict(c.details),
                        "entry_ids": list(c.entry_ids),
                        "matter_id": c.matter_id,
                        "message": c.message,
                    }
                    for c in conflicts_sorted
                ],
                "current_by_logical_id": dict(sorted(current.items())),
                "entries": [e.identity_payload() | {"entry_id": e.entry_id} for e in entries_sorted],
                "gaps": [
                    {
                        "code": g.code.value,
                        "details": dict(g.details),
                        "gap_id": g.gap_id,
                        "interpretation": g.interpretation.value,
                        "is_proof_of_nonreceipt": g.is_proof_of_nonreceipt,
                        "logical_id": g.logical_id,
                        "matter_id": g.matter_id,
                        "message": g.message,
                        "related_entry_ids": list(g.related_entry_ids),
                    }
                    for g in gaps_sorted
                ],
                "history_entry_ids": list(history_ids),
                "matter_id": mid,
                "notes": notes,
                "quarantines": [
                    {
                        "artifact_id": q.artifact_id,
                        "content_sha256": q.content_sha256,
                        "expected_matter_id": q.expected_matter_id,
                        "labels": dict(q.labels),
                        "message": q.message,
                        "observed_matter_id": q.observed_matter_id,
                        "quarantine_id": q.quarantine_id,
                        "reason_codes": list(q.reason_codes),
                        "source_payload_digest": q.source_payload_digest,
                    }
                    for q in quarantines_sorted
                ],
                "schema_version": MATTER_LEDGER_SCHEMA_VERSION,
            }
            content_digest = hashlib.sha256(
                canonical_json(body).encode("utf-8")
            ).hexdigest()
            snapshot_id = content_addressed_id(
                "snap",
                {"content_digest": content_digest, "matter_id": mid},
            )
            # reconciled_utc is observational; content_digest excludes it.
            return MatterLedgerSnapshot(
                schema_version=MATTER_LEDGER_SCHEMA_VERSION,
                matter_id=mid,
                snapshot_id=snapshot_id,
                content_digest=content_digest,
                entries=entries_sorted,
                conflicts=conflicts_sorted,
                gaps=gaps_sorted,
                quarantines=quarantines_sorted,
                claim_sets=claim_sets_sorted,
                current_by_logical_id=current,
                history_entry_ids=history_ids,
                reconciled_utc=self._clock(),
                notes=tuple(notes),
            )

    def replay(
        self,
        matter_id: str,
        operations: Sequence[Mapping[str, Any]],
        *,
        reset_store: bool = False,
    ) -> MatterLedgerSnapshot:
        """Replay a sequence of ingest operation dicts deterministically.

        Each operation is a mapping with ``op`` key::

            {"op": "artifact", "manifest": {...}, ...}
            {"op": "event", "event": {...}}
            {"op": "inventory", "source_document_id": "...", "available": false, ...}
            {"op": "claim_set", "content_sha256": "..."}
            {"op": "amendment", "content_sha256": "...", "logical_id": "..."}
            {"op": "gui_metadata", "logical_id": "...", "metadata": {...}}
            {"op": "link_derivative", "original_entry_id": "...", "derivative_entry_id": "..."}
            {"op": "source_receipt", "receipt": {...}}

        When *reset_store* is true, a fresh :class:`InMemoryLedgerStore` is used
        so the replay is isolated. The resulting snapshot content digest is
        independent of wall-clock (digest excludes ``reconciled_utc`` /
        observational timestamps that are not part of entry identity).
        """
        mid = normalize_matter_key(matter_id)
        if reset_store:
            self._store = InMemoryLedgerStore()
        for index, raw in enumerate(operations):
            if not isinstance(raw, Mapping):
                raise MatterLedgerError(
                    f"operations[{index}] must be a mapping",
                    code="invalid_replay_op",
                )
            op = str(raw.get("op") or "").strip()
            if op == "artifact":
                self.ingest_artifact(
                    matter_id=mid,
                    manifest=raw.get("manifest") or {},
                    item_kind=raw.get("item_kind"),
                    channel=raw.get("channel", LedgerChannel.PRIVATE_IMPORT.value),
                    logical_id=raw.get("logical_id"),
                    notes=tuple(raw.get("notes") or ()),
                    force_quarantine=bool(raw.get("force_quarantine", False)),
                )
            elif op == "event":
                self.ingest_event(
                    matter_id=mid,
                    event=raw.get("event") or {},
                    channel=raw.get("channel", LedgerChannel.STATUS_API.value),
                    notes=tuple(raw.get("notes") or ()),
                )
            elif op == "inventory":
                self.ingest_inventory_item(
                    matter_id=mid,
                    source_document_id=str(raw.get("source_document_id") or ""),
                    available=bool(raw.get("available", False)),
                    content_sha256=raw.get("content_sha256"),
                    size_bytes=raw.get("size_bytes"),
                    media_type=raw.get("media_type"),
                    artifact_id=raw.get("artifact_id"),
                    authority_relation=raw.get(
                        "authority_relation",
                        AuthorityRelation.AUTHORITATIVE_ORIGINAL.value,
                    ),
                    classification=raw.get(
                        "classification",
                        DisclosureClassification.PUBLIC_OFFICIAL.value,
                    ),
                    channel=raw.get(
                        "channel", LedgerChannel.PUBLIC_FILE_WRAPPER.value
                    ),
                    delayed=bool(raw.get("delayed", False)),
                    gap_code=raw.get("gap_code"),
                    labels=raw.get("labels") or {},
                    source_receipt_id=raw.get("source_receipt_id"),
                    notes=tuple(raw.get("notes") or ()),
                )
            elif op == "claim_set":
                self.record_claim_set(
                    matter_id=mid,
                    content_sha256=str(raw.get("content_sha256") or ""),
                    artifact_id=raw.get("artifact_id"),
                    as_of_utc=raw.get("as_of_utc"),
                    labels=raw.get("labels") or {},
                    notes=tuple(raw.get("notes") or ()),
                    channel=raw.get("channel", LedgerChannel.PRIVATE_IMPORT.value),
                    classification=raw.get(
                        "classification",
                        DisclosureClassification.CONFIDENTIAL_APPLICATION.value,
                    ),
                )
            elif op == "amendment":
                self.record_amendment(
                    matter_id=mid,
                    content_sha256=str(raw.get("content_sha256") or ""),
                    logical_id=str(raw.get("logical_id") or ""),
                    artifact_id=raw.get("artifact_id"),
                    parent_artifact_ids=tuple(raw.get("parent_artifact_ids") or ()),
                    labels=raw.get("labels") or {},
                    notes=tuple(raw.get("notes") or ()),
                    channel=raw.get("channel", LedgerChannel.PRIVATE_IMPORT.value),
                    classification=raw.get(
                        "classification",
                        DisclosureClassification.CONFIDENTIAL_APPLICATION.value,
                    ),
                    event_utc=raw.get("event_utc"),
                )
            elif op == "gui_metadata":
                self.ingest_gui_metadata(
                    matter_id=mid,
                    logical_id=str(raw.get("logical_id") or ""),
                    metadata=raw.get("metadata") or {},
                    content_sha256=raw.get("content_sha256"),
                    channel=raw.get("channel", LedgerChannel.PRIVATE_IMPORT.value),
                    notes=tuple(raw.get("notes") or ()),
                )
            elif op == "link_derivative":
                self.link_derivative(
                    matter_id=mid,
                    original_entry_id=str(raw.get("original_entry_id") or ""),
                    derivative_entry_id=str(raw.get("derivative_entry_id") or ""),
                )
            elif op == "source_receipt":
                self.ingest_source_receipt(
                    matter_id=mid,
                    receipt=raw.get("receipt") or {},
                    item_kind=raw.get(
                        "item_kind", LedgerItemKind.ACKNOWLEDGEMENT.value
                    ),
                    channel=raw.get("channel", LedgerChannel.PRIVATE_IMPORT.value),
                    labels=raw.get("labels") or {},
                    notes=tuple(raw.get("notes") or ()),
                )
            else:
                raise MatterLedgerError(
                    f"unknown replay op: {op!r}",
                    code="unknown_replay_op",
                )
        return self.reconcile(mid)

    def history(self, matter_id: str) -> tuple[LedgerEntry, ...]:
        """Return all entries (all versions) in admission order."""
        return self._store.list_entries(normalize_matter_key(matter_id))

    def get_entry(self, matter_id: str, entry_id: str) -> LedgerEntry | None:
        return self._store.get_entry(normalize_matter_key(matter_id), entry_id)

    # -- internals -----------------------------------------------------------

    def _versions_for_logical(
        self, matter_id: str, logical_id: str
    ) -> tuple[LedgerEntry, ...]:
        return tuple(
            e
            for e in self._store.list_entries(matter_id)
            if e.logical_id == logical_id
        )

    def _next_version(
        self, matter_id: str, logical_id: str, content_sha256: str | None
    ) -> tuple[int, LedgerEntry | None]:
        """Return (version, existing_same_digest_or_None)."""
        versions = self._versions_for_logical(matter_id, logical_id)
        for entry in versions:
            if entry.content_sha256 == content_sha256 and content_sha256 is not None:
                return entry.version, entry
            if content_sha256 is None and entry.content_sha256 is None:
                # Presence-only placeholders: match on presence notes via entry_id
                # rebuild — treat same logical_id + None digest as one logical row
                # unless presence differs (handled by entry_id identity).
                return entry.version, entry
        max_v = max((e.version for e in versions), default=0)
        return max_v + 1, None

    def _admit_entry(
        self,
        *,
        matter_id: str,
        logical_id: str,
        item_kind: LedgerItemKind,
        authority_relation: AuthorityRelation,
        presence: LedgerPresence,
        content_sha256: str | None,
        size_bytes: int | None,
        artifact_id: str | None,
        parent_artifact_ids: Sequence[str],
        source_receipt_id: str | None,
        channel: LedgerChannel,
        classification: DisclosureClassification,
        media_type: str | None,
        event_kind: MatterEventKind | None,
        event_utc: str | None,
        labels: Mapping[str, str],
        notes: Sequence[str],
        admitted_utc: str,
        parent_entry_ids: Sequence[str] = (),
        related_entry_ids: Sequence[str] = (),
        extra_related_artifact_ids: Sequence[str] = (),
        force_new_version: bool = False,
    ) -> IngestResult:
        mid = matter_id
        digest = _optional_sha256(content_sha256, "content_sha256")
        conflicts: list[LedgerConflict] = []
        gaps: list[LedgerGap] = []

        if force_new_version:
            versions = self._versions_for_logical(mid, logical_id)
            version = max((e.version for e in versions), default=0) + 1
            existing = None
        else:
            version, existing = self._next_version(mid, logical_id, digest)

        if existing is not None and not force_new_version:
            # Idempotent hit — ensure authority/kind agreement; else conflict.
            if existing.authority_relation != authority_relation:
                conflict = self._record_conflict(
                    matter_id=mid,
                    code=ConflictCode.AUTHORITY_CONFLICT,
                    entry_ids=(existing.entry_id,),
                    message=(
                        f"re-ingest of {logical_id} disagrees on authority_relation: "
                        f"stored={existing.authority_relation.value} "
                        f"incoming={authority_relation.value}"
                    ),
                    recorded_utc=admitted_utc,
                    details={
                        "incoming": authority_relation.value,
                        "stored": existing.authority_relation.value,
                    },
                )
                conflicts.append(conflict)
            return IngestResult(
                disposition=(
                    IngestDisposition.CONFLICT
                    if conflicts
                    else IngestDisposition.DEDUPLICATED
                ),
                entry=existing,
                quarantine=None,
                conflicts=tuple(conflicts),
                gaps=(),
                message="identical content already admitted; history not overwritten",
            )

        entry_id = _build_entry_id(
            matter_id=mid,
            logical_id=logical_id,
            version=version,
            content_sha256=digest,
            item_kind=item_kind,
            authority_relation=authority_relation,
            presence=presence,
        )
        # Collapse related artifact ids into labels for traceability when no
        # related entry ids exist yet.
        label_map = dict(labels)
        if extra_related_artifact_ids:
            label_map.setdefault(
                "related_artifact_ids",
                ",".join(extra_related_artifact_ids)[:2048],
            )

        entry = LedgerEntry(
            schema_version=MATTER_LEDGER_SCHEMA_VERSION,
            entry_id=entry_id,
            matter_id=mid,
            logical_id=logical_id,
            item_kind=item_kind,
            authority_relation=authority_relation,
            presence=presence,
            version=version,
            content_sha256=digest,
            size_bytes=size_bytes,
            artifact_id=artifact_id,
            parent_entry_ids=tuple(parent_entry_ids),
            parent_artifact_ids=tuple(parent_artifact_ids),
            related_entry_ids=tuple(related_entry_ids),
            source_receipt_id=source_receipt_id,
            channel=channel,
            classification=classification,
            media_type=media_type,
            event_kind=event_kind,
            event_utc=event_utc,
            admitted_utc=admitted_utc,
            labels=label_map,
            notes=tuple(notes),
        )

        # Detect authority conflict across versions of same logical id.
        prior = self._versions_for_logical(mid, logical_id)
        for prev in prior:
            if (
                prev.authority_relation != entry.authority_relation
                and prev.content_sha256 != entry.content_sha256
            ):
                conflict = self._record_conflict(
                    matter_id=mid,
                    code=ConflictCode.AUTHORITY_CONFLICT,
                    entry_ids=(prev.entry_id, entry.entry_id),
                    message=(
                        f"authority_relation changed across versions of "
                        f"{logical_id}: {prev.authority_relation.value} → "
                        f"{entry.authority_relation.value}"
                    ),
                    recorded_utc=admitted_utc,
                    details={
                        "from": prev.authority_relation.value,
                        "to": entry.authority_relation.value,
                    },
                )
                conflicts.append(conflict)

        # Derivative without parent → explicit gap (not silent drop).
        if entry.is_derivative and not entry.parent_artifact_ids and not entry.parent_entry_ids:
            gap = self._record_gap(
                matter_id=mid,
                code=GapCode.CONVERSION_WITHOUT_ORIGINAL,
                interpretation=GapInterpretation.RETRIEVAL_GAP,
                logical_id=logical_id,
                message=(
                    f"derivative {entry.entry_id} has no parent original linked; "
                    f"relationship gap retained"
                ),
                recorded_utc=admitted_utc,
                related_entry_ids=(entry.entry_id,),
                details={"item_kind": entry.item_kind.value},
            )
            gaps.append(gap)

        appended = self._store.append_entry(entry)
        if not appended:
            # Race / exact replay of same entry_id.
            stored = self._store.get_entry(mid, entry.entry_id)
            return IngestResult(
                disposition=IngestDisposition.DEDUPLICATED,
                entry=stored or entry,
                quarantine=None,
                conflicts=tuple(conflicts),
                gaps=tuple(gaps),
                message="entry_id already present; history not overwritten",
            )

        disposition = (
            IngestDisposition.VERSIONED if version > 1 else IngestDisposition.ADMITTED
        )
        if conflicts:
            disposition = IngestDisposition.CONFLICT
        return IngestResult(
            disposition=disposition,
            entry=entry,
            quarantine=None,
            conflicts=tuple(conflicts),
            gaps=tuple(gaps),
            message=None,
        )

    def _quarantine(
        self,
        *,
        expected_matter_id: str,
        observed_matter_id: str | None,
        reason_codes: Sequence[str],
        message: str,
        artifact_id: str | None,
        content_sha256: str | None,
        source_payload: Mapping[str, Any],
        labels: Mapping[str, str],
        recorded_utc: str,
    ) -> IngestResult:
        payload_digest = hashlib.sha256(
            canonical_json(dict(source_payload)).encode("utf-8")
        ).hexdigest()
        qid = content_addressed_id(
            "q",
            {
                "artifact_id": artifact_id,
                "content_sha256": content_sha256,
                "expected_matter_id": expected_matter_id,
                "observed_matter_id": observed_matter_id,
                "payload_digest": payload_digest,
                "reason_codes": list(reason_codes),
            },
        )
        record = QuarantineRecord(
            schema_version=MATTER_LEDGER_SCHEMA_VERSION,
            quarantine_id=qid,
            expected_matter_id=expected_matter_id,
            observed_matter_id=observed_matter_id,
            reason_codes=tuple(reason_codes),
            message=message,
            recorded_utc=recorded_utc,
            artifact_id=artifact_id,
            content_sha256=content_sha256,
            source_payload_digest=payload_digest,
            labels=labels,
        )
        self._store.append_quarantine(record)
        # Also record as conflict for visibility on the expected matter.
        conflict = self._record_conflict(
            matter_id=expected_matter_id,
            code=ConflictCode.MATTER_ID_MISMATCH,
            entry_ids=(),
            message=message,
            recorded_utc=recorded_utc,
            details={
                "observed_matter_id": observed_matter_id or "",
                "quarantine_id": qid,
            },
        )
        return IngestResult(
            disposition=IngestDisposition.QUARANTINED,
            entry=None,
            quarantine=record,
            conflicts=(conflict,),
            gaps=(),
            message=message,
        )

    def _record_conflict(
        self,
        *,
        matter_id: str,
        code: ConflictCode,
        entry_ids: Sequence[str],
        message: str,
        recorded_utc: str,
        details: Mapping[str, str] | None = None,
    ) -> LedgerConflict:
        cid = content_addressed_id(
            "cf",
            {
                "code": code.value,
                "details": dict(details or {}),
                "entry_ids": list(entry_ids),
                "matter_id": matter_id,
                "message": message,
            },
        )
        conflict = LedgerConflict(
            schema_version=MATTER_LEDGER_SCHEMA_VERSION,
            conflict_id=cid,
            matter_id=matter_id,
            code=code,
            entry_ids=tuple(entry_ids),
            message=message,
            recorded_utc=recorded_utc,
            details=details or {},
        )
        self._store.append_conflict(conflict)
        return conflict

    def _record_gap(
        self,
        *,
        matter_id: str,
        code: GapCode,
        interpretation: GapInterpretation,
        logical_id: str,
        message: str,
        recorded_utc: str,
        related_entry_ids: Sequence[str] = (),
        details: Mapping[str, str] | None = None,
    ) -> LedgerGap:
        gid = content_addressed_id(
            "gap",
            {
                "code": code.value,
                "details": dict(details or {}),
                "interpretation": interpretation.value,
                "logical_id": logical_id,
                "matter_id": matter_id,
                "message": message,
            },
        )
        gap = LedgerGap(
            schema_version=MATTER_LEDGER_SCHEMA_VERSION,
            gap_id=gid,
            matter_id=matter_id,
            code=code,
            interpretation=interpretation,
            logical_id=logical_id,
            message=message,
            recorded_utc=recorded_utc,
            related_entry_ids=tuple(related_entry_ids),
            is_proof_of_nonreceipt=False,
            details=details or {},
        )
        self._store.append_gap(gap)
        return gap

    def _structural_reconcile(self, matter_id: str) -> None:
        """Emit conflicts/gaps for structural issues not caught at ingest."""
        now = self._clock()
        entries = self._store.list_entries(matter_id)
        by_artifact: dict[str, list[LedgerEntry]] = {}
        for entry in entries:
            if entry.artifact_id:
                by_artifact.setdefault(entry.artifact_id, []).append(entry)

        # Parent artifact references that never appear as entries.
        known_artifacts = {
            e.artifact_id for e in entries if e.artifact_id is not None
        }
        for entry in entries:
            if not entry.is_derivative:
                continue
            for parent_aid in entry.parent_artifact_ids:
                if parent_aid not in known_artifacts:
                    self._record_gap(
                        matter_id=matter_id,
                        code=GapCode.CONVERSION_WITHOUT_ORIGINAL,
                        interpretation=GapInterpretation.RETRIEVAL_GAP,
                        logical_id=entry.logical_id,
                        message=(
                            f"derivative {entry.entry_id} references missing parent "
                            f"artifact {parent_aid}"
                        ),
                        recorded_utc=now,
                        related_entry_ids=(entry.entry_id,),
                        details={"parent_artifact_id": parent_aid},
                    )

        # Dual authoritative originals that share a conversion-family label.
        originals = [
            e
            for e in entries
            if e.is_authoritative_original
            and e.item_kind is LedgerItemKind.ORIGINAL_SUBMISSION
            and e.presence is LedgerPresence.PRESENT
        ]
        # Group by label family if present; otherwise no dual-original check.
        families: dict[str, list[LedgerEntry]] = {}
        for orig in originals:
            family = orig.labels.get("family") or orig.labels.get("document_code")
            if family:
                families.setdefault(family, []).append(orig)
        for family, group in families.items():
            # Distinct content digests under same family are versions, not duals.
            digests = {e.content_sha256 for e in group if e.content_sha256}
            # Dual only when same version number claimed for different digests —
            # handled by versioning. Flag when two present originals share family
            # with no version progression (same version, different digest).
            by_version: dict[int, list[LedgerEntry]] = {}
            for e in group:
                by_version.setdefault(e.version, []).append(e)
            for ver, peers in by_version.items():
                digs = {p.content_sha256 for p in peers}
                if len(digs) > 1:
                    self._record_conflict(
                        matter_id=matter_id,
                        code=ConflictCode.DUAL_AUTHORITATIVE_ORIGINAL,
                        entry_ids=tuple(p.entry_id for p in peers),
                        message=(
                            f"multiple authoritative originals at version {ver} "
                            f"for family {family!r}"
                        ),
                        recorded_utc=now,
                        details={"family": family, "version": str(ver)},
                    )

        # Receipt without any original submission present.
        has_original = any(
            e.item_kind is LedgerItemKind.ORIGINAL_SUBMISSION
            and e.presence is LedgerPresence.PRESENT
            for e in entries
        )
        receipts = [
            e
            for e in entries
            if e.item_kind
            in (LedgerItemKind.ACKNOWLEDGEMENT, LedgerItemKind.PAYMENT_RECEIPT)
            and e.presence is LedgerPresence.PRESENT
        ]
        if receipts and not has_original:
            for rec in receipts:
                self._record_gap(
                    matter_id=matter_id,
                    code=GapCode.RECEIPT_WITHOUT_ORIGINAL,
                    interpretation=GapInterpretation.RETRIEVAL_GAP,
                    logical_id=rec.logical_id,
                    message=(
                        f"receipt {rec.entry_id} present without an original "
                        f"submission in the ledger"
                    ),
                    recorded_utc=now,
                    related_entry_ids=(rec.entry_id,),
                    details={"item_kind": rec.item_kind.value},
                )


# ---------------------------------------------------------------------------
# Factory helpers for tests / integration
# ---------------------------------------------------------------------------


def build_manifest_for_ledger(
    *,
    artifact_id: str,
    sha256: str,
    size_bytes: int,
    matter_id: str,
    classification: DisclosureClassification | str,
    media_type: str,
    authority_relation: AuthorityRelation | str = AuthorityRelation.AUTHORITATIVE_ORIGINAL,
    parent_artifact_ids: Sequence[str] = (),
    source_receipt_id: str | None = None,
    labels: Mapping[str, str] | None = None,
    encryption_namespace: str | None = None,
) -> ArtifactManifest:
    """Convenience builder that fills private-store requirements when needed."""
    from .artifact_manifest import build_artifact_manifest

    cls = (
        classification
        if isinstance(classification, DisclosureClassification)
        else DisclosureClassification(str(classification))
    )
    ns = encryption_namespace
    if ns is None and (
        requires_quarantine(cls)
        or cls
        in (
            DisclosureClassification.CONFIDENTIAL_APPLICATION,
            DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
            DisclosureClassification.RESTRICTED_EXPORT_REVIEW,
        )
    ):
        ns = f"private://ledger/{matter_id}"
    return build_artifact_manifest(
        artifact_id=artifact_id,
        sha256=sha256,
        size_bytes=size_bytes,
        classification=cls,
        media_type=media_type,
        matter_id=matter_id,
        source_receipt_id=source_receipt_id,
        authority_relation=authority_relation,
        parent_artifact_ids=parent_artifact_ids,
        encryption_namespace=ns,
        labels=labels or {},
    )


__all__ = [
    "MATTER_LEDGER_INTERFACE",
    "MATTER_LEDGER_SCHEMA_VERSION",
    "ClaimSetVersion",
    "ConflictCode",
    "GapCode",
    "GapInterpretation",
    "InMemoryLedgerStore",
    "IngestDisposition",
    "IngestResult",
    "LedgerChannel",
    "LedgerConflict",
    "LedgerEntry",
    "LedgerGap",
    "LedgerItemKind",
    "LedgerPresence",
    "LedgerStore",
    "MatterLedger",
    "MatterLedgerError",
    "MatterLedgerSnapshot",
    "QuarantineRecord",
    "build_manifest_for_ledger",
    "content_addressed_id",
    "infer_item_kind",
    "matter_ids_compatible",
    "normalize_matter_key",
]
