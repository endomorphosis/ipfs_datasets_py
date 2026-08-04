"""Explainable requirement/evidence gap report projection (PATLAW-051).

Renders an immutable analysis bundle (and optional pre-computed analysis
records) into a human- and machine-readable gap matrix without recomputing
hidden legal logic.

Design invariants
-----------------
* Deterministic report projection only — dossier / bundle inputs are not
  mutated and legal outcomes are not re-derived.
* The report is content-bound to the source analysis bundle
  (``source_bundle_id`` + ``source_bundle_digest``). Serialization round-trips
  preserve that binding; verification confirms the same bundle.
* Every statement exposes :class:`SourceLink` provenance (artifacts, authority,
  spans, sections, records). Untraced subjects surface as prominent unknowns.
* Unknowns, gaps, and mandatory reviewer actions are first-class and prominent
  in both machine and human forms.
* Private / quarantine classifications redact surface text according to the
  output policy; identifiers, digests, statuses, and reason codes remain.
* The label ``all_clear`` is **never** emitted while mandatory review remains,
  unknowns block clearance, or mandatory gaps/unsatisfied demands are open.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    ReviewState,
    canonical_json,
    is_private_classification,
    is_public_classification,
    requires_quarantine,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.analysis_bundle import (
    ANALYSIS_BUNDLE_SCHEMA_VERSION,
    BundleSectionKind,
    BundleSectionRef,
    ProvenanceLink,
    UsptoAnalysisBundle,
)

# ---------------------------------------------------------------------------
# Versions / interface
# ---------------------------------------------------------------------------

GAP_REPORT_SCHEMA_VERSION: Final = "uspto.gap-report.v1"
GAP_REPORT_INTERFACE: Final = "RequirementEvidenceGapReport@1"
GAP_REPORT_RULESET_VERSION: Final = "gap-report-rules@1"
PARSER_VERSION: Final = "patlaw-051.gap-report.v1"

OUTPUT_KIND_REQUIREMENT_EVIDENCE_GAP_REPORT: Final = (
    "requirement_evidence_gap_report"
)

GAP_REPORT_DISCLAIMER: Final = (
    "This gap report is a deterministic projection of an immutable analysis "
    "bundle for human review. It is not a legal opinion, not a filing "
    "authorization, and does not recompute hidden legal outcomes."
)

REDACTION_TOKEN: Final = "[REDACTED]"
UNKNOWN_BANNER: Final = "UNKNOWN"

DEFAULT_MAX_STATEMENTS: Final = 8192
DEFAULT_MAX_ROWS: Final = 4096
DEFAULT_MAX_SOURCE_LINKS: Final = 8192
DEFAULT_MAX_INVENTORY: Final = 1024

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")

# Surface-text field names that must never leave a private projection.
_PRIVATE_TEXT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "text",
        "body",
        "content",
        "detail_text",
        "explanation",
        "message",
        "summary",
        "narrative",
        "human_readable",
        "display_value",
        "instruction_text",
        "raw_text",
        "prompt",
        "bytes",
        "raw_bytes",
        "embedding",
        "embeddings",
        "vector",
        "password",
        "api_key",
        "token",
        "secret",
        "private_cid",
        "cid",
    }
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class GapStatus(str, Enum):
    """Per-requirement / statement gap status (projection vocabulary)."""

    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    MISSING = "missing"
    GAP = "gap"


class GapReportLabel(str, Enum):
    """Top-level clearance label for the report.

    ``ALL_CLEAR`` is admissible only when no mandatory review remains, no
    prominent unknowns block clearance, and no mandatory gaps/unsatisfied
    demands are open.
    """

    ALL_CLEAR = "all_clear"
    REVIEW_REQUIRED = "review_required"
    UNKNOWNS_PRESENT = "unknowns_present"
    GAPS_PRESENT = "gaps_present"
    PARTIAL = "partial"
    EMPTY = "empty"
    QUARANTINE = "quarantine"


class OutputPolicyMode(str, Enum):
    """How private surface text is handled in report projections."""

    FULL = "full"
    REDACT_PRIVATE = "redact_private"
    IDENTIFIERS_ONLY = "identifiers_only"


class StatementKind(str, Enum):
    """Kinds of explainable statements in the gap report."""

    MATTER_SUMMARY = "matter_summary"
    ARTIFACT = "artifact"
    RECEIPT = "receipt"
    REQUIREMENT = "requirement"
    AUTHORITY = "authority"
    EVIDENCE = "evidence"
    COUNTER_EVIDENCE = "counter_evidence"
    STATUS = "status"
    GAP = "gap"
    UNCERTAINTY = "uncertainty"
    CANDIDATE_DATE = "candidate_date"
    REVIEWER_ACTION = "reviewer_action"
    WARNING = "warning"
    UNKNOWN = "unknown"
    BUNDLE_BINDING = "bundle_binding"
    INVENTORY = "inventory"
    OTHER = "other"


class GapReportError(ValueError):
    """Raised for invalid gap-report construction or policy violations."""

    def __init__(self, message: str, *, code: str = "gap_report_error") -> None:
        super().__init__(message)
        self.code = code

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


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


def _sha256_hex_field(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64).lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field} must be a 64-char lowercase hex SHA-256 digest")
    return text


def _optional_sha256(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=64)
    if text is None:
        return None
    text = text.lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field} must be a 64-char lowercase hex SHA-256 digest")
    return text


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Any:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip())
        except ValueError as exc:
            raise ValueError(f"unknown {field}: {value!r}") from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    if isinstance(value, str):
        try:
            return DisclosureClassification(value.strip())
        except ValueError as exc:
            raise ValueError(f"unknown disclosure classification: {value!r}") from exc
    raise TypeError("classification must be DisclosureClassification or str")


def _tuple_of_str(
    value: Any, field: str, *, max_items: int = 256
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of strings")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    return tuple(_require_str(item, f"{field}[{i}]", max_len=512) for i, item in enumerate(value))


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


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int")
    if value < 0:
        raise ValueError(f"{field} must be non-negative")
    return value


def _default_id_factory() -> str:
    return uuid.uuid4().hex


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        mapped = value.to_dict()
        if isinstance(mapped, Mapping):
            return mapped
    return None


def _status_from_raw(raw: Any) -> GapStatus:
    if raw is None:
        return GapStatus.UNKNOWN
    if isinstance(raw, GapStatus):
        return raw
    text = str(raw).strip().lower()
    mapping = {
        "satisfied": GapStatus.SATISFIED,
        "unsatisfied": GapStatus.UNSATISFIED,
        "unknown": GapStatus.UNKNOWN,
        "not_applicable": GapStatus.NOT_APPLICABLE,
        "n/a": GapStatus.NOT_APPLICABLE,
        "missing": GapStatus.MISSING,
        "gap": GapStatus.GAP,
        "pass": GapStatus.SATISFIED,
        "fail": GapStatus.UNSATISFIED,
        "failed": GapStatus.UNSATISFIED,
        "violated": GapStatus.UNSATISFIED,
    }
    return mapping.get(text, GapStatus.UNKNOWN)


def _is_blocking_unknown(status: GapStatus, *, mandatory: bool) -> bool:
    if not mandatory:
        return status is GapStatus.UNKNOWN
    return status in (GapStatus.UNKNOWN, GapStatus.MISSING)


def _is_open_gap(status: GapStatus, *, mandatory: bool) -> bool:
    if status is GapStatus.NOT_APPLICABLE:
        return False
    if status in (GapStatus.UNSATISFIED, GapStatus.GAP, GapStatus.MISSING):
        return True
    if mandatory and status is GapStatus.UNKNOWN:
        return True
    return False


# ---------------------------------------------------------------------------
# Output policy (private text redaction)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OutputRedactionPolicy:
    """Policy governing surface-text redaction in gap-report projections."""

    mode: OutputPolicyMode = OutputPolicyMode.REDACT_PRIVATE
    redaction_token: str = REDACTION_TOKEN
    quarantine_as_private: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "mode", _coerce_enum(OutputPolicyMode, self.mode, "mode")
        )
        object.__setattr__(
            self,
            "redaction_token",
            _require_str(self.redaction_token, "redaction_token", max_len=64),
        )
        if not isinstance(self.quarantine_as_private, bool):
            raise TypeError("quarantine_as_private must be bool")

    def must_redact(self, classification: DisclosureClassification | str) -> bool:
        cls = _coerce_classification(classification)
        if self.mode is OutputPolicyMode.FULL:
            # FULL still refuses credential secrets / private when misused.
            if cls is DisclosureClassification.CREDENTIAL_OR_PAYMENT:
                return True
            return False
        if self.mode is OutputPolicyMode.IDENTIFIERS_ONLY:
            return True
        # REDACT_PRIVATE
        if is_private_classification(cls):
            return True
        if self.quarantine_as_private and requires_quarantine(cls):
            return True
        return False

    def redact_text(
        self,
        text: str | None,
        classification: DisclosureClassification | str,
        *,
        allow_public: bool = True,
    ) -> tuple[str | None, bool]:
        """Return ``(possibly_redacted_text, was_redacted)``."""
        if text is None:
            return None, False
        if not isinstance(text, str):
            text = str(text)
        cls = _coerce_classification(classification)
        if self.mode is OutputPolicyMode.IDENTIFIERS_ONLY:
            return self.redaction_token, True
        if self.must_redact(cls):
            return self.redaction_token, True
        if allow_public and is_public_classification(cls):
            return text, False
        if self.must_redact(cls):
            return self.redaction_token, True
        return text, False

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "quarantine_as_private": self.quarantine_as_private,
            "redaction_token": self.redaction_token,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OutputRedactionPolicy":
        if not isinstance(value, Mapping):
            raise TypeError("OutputRedactionPolicy must be a mapping")
        return cls(
            mode=value.get("mode", OutputPolicyMode.REDACT_PRIVATE.value),
            redaction_token=value.get("redaction_token", REDACTION_TOKEN),
            quarantine_as_private=bool(value.get("quarantine_as_private", True)),
        )


DEFAULT_OUTPUT_POLICY: Final = OutputRedactionPolicy()


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceLink:
    """Provenance links exposed on every explainable statement."""

    link_id: str
    role: str
    artifact_ids: tuple[str, ...] = ()
    authority_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    section_ids: tuple[str, ...] = ()
    record_ids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "link_id", _identifier(self.link_id, "link_id"))
        object.__setattr__(
            self, "role", _require_str(self.role, "role", max_len=64)
        )
        object.__setattr__(
            self,
            "artifact_ids",
            _tuple_of_str(self.artifact_ids, "artifact_ids", max_items=128),
        )
        object.__setattr__(
            self,
            "authority_ids",
            _tuple_of_str(self.authority_ids, "authority_ids", max_items=128),
        )
        object.__setattr__(
            self, "span_ids", _tuple_of_str(self.span_ids, "span_ids", max_items=256)
        )
        object.__setattr__(
            self,
            "section_ids",
            _tuple_of_str(self.section_ids, "section_ids", max_items=128),
        )
        object.__setattr__(
            self,
            "record_ids",
            _tuple_of_str(self.record_ids, "record_ids", max_items=128),
        )
        object.__setattr__(
            self, "notes", _tuple_of_str(self.notes, "notes", max_items=16)
        )

    @property
    def is_traced(self) -> bool:
        return bool(
            self.artifact_ids
            or self.authority_ids
            or self.span_ids
            or self.section_ids
            or self.record_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_ids": list(self.artifact_ids),
            "authority_ids": list(self.authority_ids),
            "link_id": self.link_id,
            "notes": list(self.notes),
            "record_ids": list(self.record_ids),
            "role": self.role,
            "section_ids": list(self.section_ids),
            "span_ids": list(self.span_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceLink":
        if not isinstance(value, Mapping):
            raise TypeError("SourceLink must be a mapping")
        return cls(
            link_id=value.get("link_id", ""),
            role=value.get("role", "source"),
            artifact_ids=tuple(value.get("artifact_ids") or ()),
            authority_ids=tuple(value.get("authority_ids") or ()),
            span_ids=tuple(value.get("span_ids") or ()),
            section_ids=tuple(value.get("section_ids") or ()),
            record_ids=tuple(value.get("record_ids") or ()),
            notes=tuple(value.get("notes") or ()),
        )


@dataclass(frozen=True, slots=True)
class GapStatement:
    """One explainable statement with mandatory source links."""

    statement_id: str
    kind: StatementKind
    summary: str
    status: GapStatus
    source_links: tuple[SourceLink, ...]
    is_unknown: bool
    is_prominent_unknown: bool
    classification: DisclosureClassification
    redacted: bool
    detail_text: str | None = None
    reason_codes: tuple[str, ...] = ()
    related_ids: tuple[str, ...] = ()
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "statement_id", _identifier(self.statement_id, "statement_id")
        )
        object.__setattr__(
            self, "kind", _coerce_enum(StatementKind, self.kind, "kind")
        )
        object.__setattr__(
            self, "summary", _require_str(self.summary, "summary", max_len=1024)
        )
        object.__setattr__(
            self, "status", _coerce_enum(GapStatus, self.status, "status")
        )
        if not isinstance(self.source_links, tuple):
            object.__setattr__(self, "source_links", tuple(self.source_links))
        if not self.source_links:
            raise GapReportError(
                f"statement {self.statement_id!r} must expose at least one source link",
                code="missing_source_links",
            )
        for link in self.source_links:
            if not isinstance(link, SourceLink):
                raise TypeError("source_links must be SourceLink instances")
        if not isinstance(self.is_unknown, bool):
            raise TypeError("is_unknown must be bool")
        if not isinstance(self.is_prominent_unknown, bool):
            raise TypeError("is_prominent_unknown must be bool")
        if self.is_prominent_unknown and not self.is_unknown:
            object.__setattr__(self, "is_unknown", True)
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        if not isinstance(self.redacted, bool):
            raise TypeError("redacted must be bool")
        object.__setattr__(
            self,
            "detail_text",
            _optional_str(self.detail_text, "detail_text", max_len=4096),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=64),
        )
        object.__setattr__(
            self,
            "related_ids",
            _tuple_of_str(self.related_ids, "related_ids", max_items=64),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification.value,
            "detail_text": self.detail_text,
            "is_prominent_unknown": self.is_prominent_unknown,
            "is_unknown": self.is_unknown,
            "kind": self.kind.value,
            "labels": dict(self.labels),
            "reason_codes": list(self.reason_codes),
            "redacted": self.redacted,
            "related_ids": list(self.related_ids),
            "source_links": [s.to_dict() for s in self.source_links],
            "statement_id": self.statement_id,
            "status": self.status.value,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GapStatement":
        if not isinstance(value, Mapping):
            raise TypeError("GapStatement must be a mapping")
        return cls(
            statement_id=value.get("statement_id", ""),
            kind=value.get("kind", StatementKind.OTHER.value),
            summary=value.get("summary", "statement"),
            status=value.get("status", GapStatus.UNKNOWN.value),
            source_links=tuple(
                SourceLink.from_dict(s) for s in (value.get("source_links") or ())
            ),
            is_unknown=bool(value.get("is_unknown", False)),
            is_prominent_unknown=bool(value.get("is_prominent_unknown", False)),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            redacted=bool(value.get("redacted", False)),
            detail_text=value.get("detail_text"),
            reason_codes=tuple(value.get("reason_codes") or ()),
            related_ids=tuple(value.get("related_ids") or ()),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class ArtifactInventoryItem:
    """One artifact or validation-receipt inventory entry."""

    item_id: str
    kind: str
    artifact_id: str | None
    receipt_id: str | None
    content_digest: str | None
    classification: DisclosureClassification
    source_links: tuple[SourceLink, ...]
    section_id: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", _identifier(self.item_id, "item_id"))
        object.__setattr__(
            self, "kind", _require_str(self.kind, "kind", max_len=64)
        )
        object.__setattr__(
            self, "artifact_id", _optional_identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self, "receipt_id", _optional_identifier(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self,
            "content_digest",
            _optional_sha256(self.content_digest, "content_digest"),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        if not isinstance(self.source_links, tuple):
            object.__setattr__(self, "source_links", tuple(self.source_links))
        if not self.source_links:
            raise GapReportError(
                f"inventory item {self.item_id!r} must expose source links",
                code="missing_source_links",
            )
        object.__setattr__(
            self, "section_id", _optional_identifier(self.section_id, "section_id")
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "classification": self.classification.value,
            "content_digest": self.content_digest,
            "item_id": self.item_id,
            "kind": self.kind,
            "labels": dict(self.labels),
            "receipt_id": self.receipt_id,
            "section_id": self.section_id,
            "source_links": [s.to_dict() for s in self.source_links],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactInventoryItem":
        if not isinstance(value, Mapping):
            raise TypeError("ArtifactInventoryItem must be a mapping")
        return cls(
            item_id=value.get("item_id", ""),
            kind=value.get("kind", "artifact"),
            artifact_id=value.get("artifact_id"),
            receipt_id=value.get("receipt_id"),
            content_digest=value.get("content_digest"),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            source_links=tuple(
                SourceLink.from_dict(s) for s in (value.get("source_links") or ())
            ),
            section_id=value.get("section_id"),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class ReviewerActionProjection:
    """Typed reviewer action projected into the gap report."""

    action_id: str
    kind: str
    message: str
    priority: int
    source_links: tuple[SourceLink, ...]
    requirement_id: str | None = None
    reason_codes: tuple[str, ...] = ()
    redacted: bool = False
    classification: DisclosureClassification = DisclosureClassification.UNKNOWN
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "action_id", _identifier(self.action_id, "action_id")
        )
        object.__setattr__(
            self, "kind", _require_str(self.kind, "kind", max_len=64)
        )
        object.__setattr__(
            self, "message", _require_str(self.message, "message", max_len=512)
        )
        object.__setattr__(self, "priority", _nonneg_int(self.priority, "priority"))
        if not isinstance(self.source_links, tuple):
            object.__setattr__(self, "source_links", tuple(self.source_links))
        if not self.source_links:
            raise GapReportError(
                f"reviewer action {self.action_id!r} must expose source links",
                code="missing_source_links",
            )
        object.__setattr__(
            self,
            "requirement_id",
            _optional_identifier(self.requirement_id, "requirement_id"),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=32),
        )
        if not isinstance(self.redacted, bool):
            raise TypeError("redacted must be bool")
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "classification": self.classification.value,
            "kind": self.kind,
            "labels": dict(self.labels),
            "message": self.message,
            "priority": self.priority,
            "reason_codes": list(self.reason_codes),
            "redacted": self.redacted,
            "requirement_id": self.requirement_id,
            "source_links": [s.to_dict() for s in self.source_links],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReviewerActionProjection":
        if not isinstance(value, Mapping):
            raise TypeError("ReviewerActionProjection must be a mapping")
        return cls(
            action_id=value.get("action_id", ""),
            kind=value.get("kind", "review_package"),
            message=value.get("message", "review_required"),
            priority=int(value.get("priority") or 0),
            source_links=tuple(
                SourceLink.from_dict(s) for s in (value.get("source_links") or ())
            ),
            requirement_id=value.get("requirement_id"),
            reason_codes=tuple(value.get("reason_codes") or ()),
            redacted=bool(value.get("redacted", False)),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class CandidateDateProjection:
    """Candidate response-date row with uncertainty and source links."""

    candidate_id: str
    status: GapStatus
    candidate_utc: str | None
    uncertainty_summary: str
    uncertainty_kinds: tuple[str, ...]
    assumptions: Mapping[str, str]
    source_links: tuple[SourceLink, ...]
    is_unknown: bool
    is_review_only: bool
    human_review_question: str | None
    classification: DisclosureClassification
    redacted: bool = False
    rule_chain: tuple[str, ...] = ()
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "candidate_id", _identifier(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "status", _coerce_enum(GapStatus, self.status, "status")
        )
        object.__setattr__(
            self,
            "candidate_utc",
            _optional_str(self.candidate_utc, "candidate_utc", max_len=64),
        )
        object.__setattr__(
            self,
            "uncertainty_summary",
            _require_str(self.uncertainty_summary, "uncertainty_summary", max_len=512),
        )
        object.__setattr__(
            self,
            "uncertainty_kinds",
            _tuple_of_str(self.uncertainty_kinds, "uncertainty_kinds", max_items=32),
        )
        object.__setattr__(
            self,
            "assumptions",
            _frozen_str_map(self.assumptions, "assumptions", max_items=32),
        )
        if not isinstance(self.source_links, tuple):
            object.__setattr__(self, "source_links", tuple(self.source_links))
        if not self.source_links:
            raise GapReportError(
                f"candidate date {self.candidate_id!r} must expose source links",
                code="missing_source_links",
            )
        if not isinstance(self.is_unknown, bool):
            raise TypeError("is_unknown must be bool")
        if not isinstance(self.is_review_only, bool):
            raise TypeError("is_review_only must be bool")
        if not self.is_review_only:
            raise GapReportError(
                "candidate dates are review-only projections",
                code="candidate_not_review_only",
            )
        object.__setattr__(
            self,
            "human_review_question",
            _optional_str(
                self.human_review_question, "human_review_question", max_len=512
            ),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        if not isinstance(self.redacted, bool):
            raise TypeError("redacted must be bool")
        object.__setattr__(
            self, "rule_chain", _tuple_of_str(self.rule_chain, "rule_chain", max_items=32)
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumptions": dict(self.assumptions),
            "candidate_id": self.candidate_id,
            "candidate_utc": self.candidate_utc,
            "classification": self.classification.value,
            "human_review_question": self.human_review_question,
            "is_review_only": self.is_review_only,
            "is_unknown": self.is_unknown,
            "labels": dict(self.labels),
            "redacted": self.redacted,
            "rule_chain": list(self.rule_chain),
            "source_links": [s.to_dict() for s in self.source_links],
            "status": self.status.value,
            "uncertainty_kinds": list(self.uncertainty_kinds),
            "uncertainty_summary": self.uncertainty_summary,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CandidateDateProjection":
        if not isinstance(value, Mapping):
            raise TypeError("CandidateDateProjection must be a mapping")
        return cls(
            candidate_id=value.get("candidate_id", ""),
            status=value.get("status", GapStatus.UNKNOWN.value),
            candidate_utc=value.get("candidate_utc"),
            uncertainty_summary=value.get("uncertainty_summary", "unknown"),
            uncertainty_kinds=tuple(value.get("uncertainty_kinds") or ()),
            assumptions=value.get("assumptions") or {},
            source_links=tuple(
                SourceLink.from_dict(s) for s in (value.get("source_links") or ())
            ),
            is_unknown=bool(value.get("is_unknown", True)),
            is_review_only=bool(value.get("is_review_only", True)),
            human_review_question=value.get("human_review_question"),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            redacted=bool(value.get("redacted", False)),
            rule_chain=tuple(value.get("rule_chain") or ()),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class RequirementGapRow:
    """One government demand with evidence, gap, uncertainty, and actions."""

    row_id: str
    requirement_id: str
    requirement_type: str
    status: GapStatus
    gap_status: GapStatus
    mandatory: bool
    authority_ids: tuple[str, ...]
    evidence_span_ids: tuple[str, ...]
    counter_evidence_span_ids: tuple[str, ...]
    uncertainty: str
    source_links: tuple[SourceLink, ...]
    statements: tuple[GapStatement, ...]
    classification: DisclosureClassification
    assessment_id: str | None = None
    reviewer_action: ReviewerActionProjection | None = None
    affected_claims: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "row_id", _identifier(self.row_id, "row_id"))
        object.__setattr__(
            self, "requirement_id", _identifier(self.requirement_id, "requirement_id")
        )
        object.__setattr__(
            self,
            "requirement_type",
            _require_str(self.requirement_type, "requirement_type", max_len=128),
        )
        object.__setattr__(
            self, "status", _coerce_enum(GapStatus, self.status, "status")
        )
        object.__setattr__(
            self, "gap_status", _coerce_enum(GapStatus, self.gap_status, "gap_status")
        )
        if not isinstance(self.mandatory, bool):
            raise TypeError("mandatory must be bool")
        object.__setattr__(
            self,
            "authority_ids",
            _tuple_of_str(self.authority_ids, "authority_ids", max_items=128),
        )
        object.__setattr__(
            self,
            "evidence_span_ids",
            _tuple_of_str(self.evidence_span_ids, "evidence_span_ids", max_items=256),
        )
        object.__setattr__(
            self,
            "counter_evidence_span_ids",
            _tuple_of_str(
                self.counter_evidence_span_ids,
                "counter_evidence_span_ids",
                max_items=256,
            ),
        )
        object.__setattr__(
            self,
            "uncertainty",
            _require_str(self.uncertainty, "uncertainty", max_len=512),
        )
        if not isinstance(self.source_links, tuple):
            object.__setattr__(self, "source_links", tuple(self.source_links))
        if not self.source_links:
            raise GapReportError(
                f"requirement row {self.row_id!r} must expose source links",
                code="missing_source_links",
            )
        if not isinstance(self.statements, tuple):
            object.__setattr__(self, "statements", tuple(self.statements))
        for stmt in self.statements:
            if not isinstance(stmt, GapStatement):
                raise TypeError("statements must be GapStatement instances")
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self,
            "assessment_id",
            _optional_identifier(self.assessment_id, "assessment_id"),
        )
        if self.reviewer_action is not None and not isinstance(
            self.reviewer_action, ReviewerActionProjection
        ):
            raise TypeError("reviewer_action must be ReviewerActionProjection or None")
        object.__setattr__(
            self,
            "affected_claims",
            _tuple_of_str(self.affected_claims, "affected_claims", max_items=256),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=64),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    @property
    def is_unknown(self) -> bool:
        return self.status is GapStatus.UNKNOWN or self.gap_status is GapStatus.UNKNOWN

    @property
    def blocks_clearance(self) -> bool:
        if not self.mandatory:
            return False
        if self.status is GapStatus.NOT_APPLICABLE:
            return False
        return self.status is not GapStatus.SATISFIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "affected_claims": list(self.affected_claims),
            "assessment_id": self.assessment_id,
            "authority_ids": list(self.authority_ids),
            "classification": self.classification.value,
            "counter_evidence_span_ids": list(self.counter_evidence_span_ids),
            "evidence_span_ids": list(self.evidence_span_ids),
            "gap_status": self.gap_status.value,
            "labels": dict(self.labels),
            "mandatory": self.mandatory,
            "reason_codes": list(self.reason_codes),
            "requirement_id": self.requirement_id,
            "requirement_type": self.requirement_type,
            "reviewer_action": (
                self.reviewer_action.to_dict() if self.reviewer_action else None
            ),
            "row_id": self.row_id,
            "source_links": [s.to_dict() for s in self.source_links],
            "statements": [s.to_dict() for s in self.statements],
            "status": self.status.value,
            "uncertainty": self.uncertainty,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RequirementGapRow":
        if not isinstance(value, Mapping):
            raise TypeError("RequirementGapRow must be a mapping")
        action_raw = value.get("reviewer_action")
        return cls(
            row_id=value.get("row_id", ""),
            requirement_id=value.get("requirement_id", ""),
            requirement_type=value.get("requirement_type", "unknown"),
            status=value.get("status", GapStatus.UNKNOWN.value),
            gap_status=value.get("gap_status", GapStatus.UNKNOWN.value),
            mandatory=bool(value.get("mandatory", True)),
            authority_ids=tuple(value.get("authority_ids") or ()),
            evidence_span_ids=tuple(value.get("evidence_span_ids") or ()),
            counter_evidence_span_ids=tuple(
                value.get("counter_evidence_span_ids") or ()
            ),
            uncertainty=value.get("uncertainty", "unknown"),
            source_links=tuple(
                SourceLink.from_dict(s) for s in (value.get("source_links") or ())
            ),
            statements=tuple(
                GapStatement.from_dict(s) for s in (value.get("statements") or ())
            ),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            assessment_id=value.get("assessment_id"),
            reviewer_action=(
                ReviewerActionProjection.from_dict(action_raw) if action_raw else None
            ),
            affected_claims=tuple(value.get("affected_claims") or ()),
            reason_codes=tuple(value.get("reason_codes") or ()),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class MatterSummary:
    """Matter-level summary bound to the source analysis bundle."""

    matter_id: str | None
    bundle_id: str
    bundle_digest: str
    disposition: str
    review_state: ReviewState
    classification: DisclosureClassification
    section_counts: Mapping[str, str]
    warning_codes: tuple[str, ...]
    unsupported_checks: tuple[str, ...]
    validation_receipt_ids: tuple[str, ...]
    input_artifact_ids: tuple[str, ...]
    source_links: tuple[SourceLink, ...]
    analysis_id: str | None = None
    requires_review: bool = True
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self, "bundle_id", _identifier(self.bundle_id, "bundle_id")
        )
        object.__setattr__(
            self,
            "bundle_digest",
            _sha256_hex_field(self.bundle_digest, "bundle_digest"),
        )
        object.__setattr__(
            self,
            "disposition",
            _require_str(self.disposition, "disposition", max_len=64),
        )
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self,
            "section_counts",
            _frozen_str_map(self.section_counts, "section_counts", max_items=64),
        )
        object.__setattr__(
            self,
            "warning_codes",
            _tuple_of_str(self.warning_codes, "warning_codes", max_items=256),
        )
        object.__setattr__(
            self,
            "unsupported_checks",
            _tuple_of_str(
                self.unsupported_checks, "unsupported_checks", max_items=256
            ),
        )
        object.__setattr__(
            self,
            "validation_receipt_ids",
            _tuple_of_str(
                self.validation_receipt_ids,
                "validation_receipt_ids",
                max_items=256,
            ),
        )
        object.__setattr__(
            self,
            "input_artifact_ids",
            _tuple_of_str(
                self.input_artifact_ids, "input_artifact_ids", max_items=512
            ),
        )
        if not isinstance(self.source_links, tuple):
            object.__setattr__(self, "source_links", tuple(self.source_links))
        if not self.source_links:
            raise GapReportError(
                "matter summary must expose source links to the bundle",
                code="missing_source_links",
            )
        object.__setattr__(
            self, "analysis_id", _optional_identifier(self.analysis_id, "analysis_id")
        )
        if not isinstance(self.requires_review, bool):
            raise TypeError("requires_review must be bool")
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "bundle_digest": self.bundle_digest,
            "bundle_id": self.bundle_id,
            "classification": self.classification.value,
            "disposition": self.disposition,
            "input_artifact_ids": list(self.input_artifact_ids),
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "requires_review": self.requires_review,
            "review_state": self.review_state.value,
            "section_counts": dict(self.section_counts),
            "source_links": [s.to_dict() for s in self.source_links],
            "unsupported_checks": list(self.unsupported_checks),
            "validation_receipt_ids": list(self.validation_receipt_ids),
            "warning_codes": list(self.warning_codes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MatterSummary":
        if not isinstance(value, Mapping):
            raise TypeError("MatterSummary must be a mapping")
        return cls(
            matter_id=value.get("matter_id"),
            bundle_id=value.get("bundle_id", ""),
            bundle_digest=value.get("bundle_digest", ""),
            disposition=value.get("disposition", "unknown"),
            review_state=value.get("review_state", ReviewState.PENDING.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            section_counts=value.get("section_counts") or {},
            warning_codes=tuple(value.get("warning_codes") or ()),
            unsupported_checks=tuple(value.get("unsupported_checks") or ()),
            validation_receipt_ids=tuple(
                value.get("validation_receipt_ids") or ()
            ),
            input_artifact_ids=tuple(value.get("input_artifact_ids") or ()),
            source_links=tuple(
                SourceLink.from_dict(s) for s in (value.get("source_links") or ())
            ),
            analysis_id=value.get("analysis_id"),
            requires_review=bool(value.get("requires_review", True)),
            labels=value.get("labels") or {},
        )


# ---------------------------------------------------------------------------
# Top-level report
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RequirementEvidenceGapReport:
    """Explainable requirement/evidence gap report bound to one analysis bundle.

    Machine-readable via :meth:`to_dict` / :meth:`from_dict`.
    Human-readable via :meth:`to_markdown` / the ``human_readable`` field.
    """

    schema_version: str
    report_id: str
    output_kind: str
    source_bundle_id: str
    source_bundle_digest: str
    label: GapReportLabel
    mandatory_review_remaining: bool
    unknown_count: int
    gap_count: int
    classification: DisclosureClassification
    review_state: ReviewState
    matter_summary: MatterSummary
    inventory: tuple[ArtifactInventoryItem, ...]
    requirement_rows: tuple[RequirementGapRow, ...]
    candidate_dates: tuple[CandidateDateProjection, ...]
    reviewer_actions: tuple[ReviewerActionProjection, ...]
    unknowns: tuple[GapStatement, ...]
    statements: tuple[GapStatement, ...]
    warnings: tuple[str, ...]
    reason_codes: tuple[str, ...]
    ruleset_versions: Mapping[str, str]
    output_policy: OutputRedactionPolicy
    redaction_applied: bool
    content_digest: str
    human_readable: str
    disclaimer: str = GAP_REPORT_DISCLAIMER
    matter_id: str | None = None
    analysis_id: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != GAP_REPORT_SCHEMA_VERSION:
            raise GapReportError(
                f"schema_version must be {GAP_REPORT_SCHEMA_VERSION}",
                code="schema_version_mismatch",
            )
        object.__setattr__(
            self, "report_id", _identifier(self.report_id, "report_id")
        )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_REQUIREMENT_EVIDENCE_GAP_REPORT:
            raise GapReportError(
                f"output_kind must be {OUTPUT_KIND_REQUIREMENT_EVIDENCE_GAP_REPORT!r}",
                code="invalid_output_kind",
            )
        object.__setattr__(
            self,
            "source_bundle_id",
            _identifier(self.source_bundle_id, "source_bundle_id"),
        )
        object.__setattr__(
            self,
            "source_bundle_digest",
            _sha256_hex_field(self.source_bundle_digest, "source_bundle_digest"),
        )
        object.__setattr__(
            self, "label", _coerce_enum(GapReportLabel, self.label, "label")
        )
        if not isinstance(self.mandatory_review_remaining, bool):
            raise TypeError("mandatory_review_remaining must be bool")
        object.__setattr__(
            self, "unknown_count", _nonneg_int(self.unknown_count, "unknown_count")
        )
        object.__setattr__(
            self, "gap_count", _nonneg_int(self.gap_count, "gap_count")
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        if not isinstance(self.matter_summary, MatterSummary):
            raise TypeError("matter_summary must be MatterSummary")
        if self.matter_summary.bundle_id != self.source_bundle_id:
            raise GapReportError(
                "matter_summary.bundle_id must equal source_bundle_id",
                code="bundle_id_mismatch",
            )
        if self.matter_summary.bundle_digest != self.source_bundle_digest:
            raise GapReportError(
                "matter_summary.bundle_digest must equal source_bundle_digest",
                code="bundle_digest_mismatch",
            )
        for attr, max_items in (
            ("inventory", DEFAULT_MAX_INVENTORY),
            ("requirement_rows", DEFAULT_MAX_ROWS),
            ("candidate_dates", DEFAULT_MAX_ROWS),
            ("reviewer_actions", DEFAULT_MAX_ROWS),
            ("unknowns", DEFAULT_MAX_STATEMENTS),
            ("statements", DEFAULT_MAX_STATEMENTS),
        ):
            val = getattr(self, attr)
            if not isinstance(val, tuple):
                object.__setattr__(self, attr, tuple(val))
            if len(getattr(self, attr)) > max_items:
                raise GapReportError(
                    f"{attr} exceeds max {max_items}",
                    code=f"too_many_{attr}",
                )
        object.__setattr__(
            self, "warnings", _tuple_of_str(self.warnings, "warnings", max_items=256)
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=128),
        )
        object.__setattr__(
            self,
            "ruleset_versions",
            _frozen_str_map(self.ruleset_versions, "ruleset_versions", max_items=64),
        )
        if not isinstance(self.output_policy, OutputRedactionPolicy):
            raise TypeError("output_policy must be OutputRedactionPolicy")
        if not isinstance(self.redaction_applied, bool):
            raise TypeError("redaction_applied must be bool")
        object.__setattr__(
            self,
            "content_digest",
            _sha256_hex_field(self.content_digest, "content_digest"),
        )
        object.__setattr__(
            self,
            "human_readable",
            _require_str(self.human_readable, "human_readable", max_len=262144),
        )
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=2048),
        )
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self, "analysis_id", _optional_identifier(self.analysis_id, "analysis_id")
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )

        # Hard invariant: never advertise all_clear while mandatory review remains.
        if (
            self.label is GapReportLabel.ALL_CLEAR
            and self.mandatory_review_remaining
        ):
            raise GapReportError(
                "all_clear label is forbidden while mandatory review remains",
                code="all_clear_with_mandatory_review",
            )
        if self.label is GapReportLabel.ALL_CLEAR and self.unknown_count > 0:
            raise GapReportError(
                "all_clear label is forbidden while unknowns are present",
                code="all_clear_with_unknowns",
            )
        if self.label is GapReportLabel.ALL_CLEAR and self.gap_count > 0:
            raise GapReportError(
                "all_clear label is forbidden while gaps are present",
                code="all_clear_with_gaps",
            )
        if self.label is GapReportLabel.ALL_CLEAR and self.reviewer_actions:
            raise GapReportError(
                "all_clear label is forbidden while reviewer actions remain",
                code="all_clear_with_reviewer_actions",
            )
        if requires_quarantine(self.classification) and self.review_state not in (
            ReviewState.REQUIRED,
            ReviewState.PENDING,
        ):
            object.__setattr__(self, "review_state", ReviewState.REQUIRED)

    # ---- Queries ----

    @property
    def is_private(self) -> bool:
        return is_private_classification(self.classification)

    @property
    def requires_review(self) -> bool:
        return (
            self.mandatory_review_remaining
            or self.review_state in (ReviewState.REQUIRED, ReviewState.PENDING)
            or self.label
            in (
                GapReportLabel.REVIEW_REQUIRED,
                GapReportLabel.UNKNOWNS_PRESENT,
                GapReportLabel.GAPS_PRESENT,
                GapReportLabel.PARTIAL,
                GapReportLabel.QUARANTINE,
                GapReportLabel.EMPTY,
            )
        )

    def statements_missing_source_links(self) -> tuple[str, ...]:
        """Should always be empty; provided for defensive consumers/tests."""
        missing: list[str] = []
        for stmt in self.statements:
            if not stmt.source_links:
                missing.append(stmt.statement_id)
        return tuple(missing)

    def binds_bundle(self, bundle: UsptoAnalysisBundle) -> bool:
        """True when this report is bound to *bundle* by id and digest."""
        if not isinstance(bundle, UsptoAnalysisBundle):
            return False
        return (
            self.source_bundle_id == bundle.bundle_id
            and self.source_bundle_digest == bundle.bundle_digest
        )

    def material_payload(self) -> dict[str, Any]:
        """Payload that participates in the report content digest.

        Excludes generated identity (``report_id``, ``content_digest``,
        ``human_readable`` rendering which is derived from material fields).
        Human-readable is included as a digest of itself for stability checks
        when rehydrated; the content digest is computed from this payload
        without ``content_digest`` / ``report_id``.
        """
        return {
            "analysis_id": self.analysis_id,
            "candidate_dates": [c.to_dict() for c in self.candidate_dates],
            "classification": self.classification.value,
            "disclaimer": self.disclaimer,
            "gap_count": self.gap_count,
            "inventory": [i.to_dict() for i in self.inventory],
            "label": self.label.value,
            "labels": dict(self.labels),
            "mandatory_review_remaining": self.mandatory_review_remaining,
            "matter_id": self.matter_id,
            "matter_summary": self.matter_summary.to_dict(),
            "output_kind": self.output_kind,
            "output_policy": self.output_policy.to_dict(),
            "reason_codes": list(self.reason_codes),
            "redaction_applied": self.redaction_applied,
            "requirement_rows": [r.to_dict() for r in self.requirement_rows],
            "review_state": self.review_state.value,
            "reviewer_actions": [a.to_dict() for a in self.reviewer_actions],
            "ruleset_versions": dict(self.ruleset_versions),
            "schema_version": self.schema_version,
            "source_bundle_digest": self.source_bundle_digest,
            "source_bundle_id": self.source_bundle_id,
            "statements": [s.to_dict() for s in self.statements],
            "unknown_count": self.unknown_count,
            "unknowns": [u.to_dict() for u in self.unknowns],
            "warnings": list(self.warnings),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.material_payload()
        payload["content_digest"] = self.content_digest
        payload["human_readable"] = self.human_readable
        payload["report_id"] = self.report_id
        return payload

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def to_markdown(self) -> str:
        return self.human_readable

    def public_projection(self) -> dict[str, Any]:
        """Safe identifiers/counts — no private surface text."""
        return {
            "analysis_id": self.analysis_id,
            "candidate_date_count": len(self.candidate_dates),
            "classification": self.classification.value,
            "content_digest": self.content_digest,
            "gap_count": self.gap_count,
            "inventory_count": len(self.inventory),
            "is_private": self.is_private,
            "label": self.label.value,
            "mandatory_review_remaining": self.mandatory_review_remaining,
            "matter_id": self.matter_id,
            "output_kind": self.output_kind,
            "redaction_applied": self.redaction_applied,
            "report_id": self.report_id,
            "requirement_row_count": len(self.requirement_rows),
            "requires_review": self.requires_review,
            "review_state": self.review_state.value,
            "reviewer_action_count": len(self.reviewer_actions),
            "schema_version": self.schema_version,
            "source_bundle_digest": self.source_bundle_digest,
            "source_bundle_id": self.source_bundle_id,
            "statement_count": len(self.statements),
            "unknown_count": self.unknown_count,
            "warning_count": len(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RequirementEvidenceGapReport":
        if not isinstance(value, Mapping):
            raise TypeError("RequirementEvidenceGapReport must be a mapping")
        policy_raw = value.get("output_policy") or {}
        return cls(
            schema_version=value.get("schema_version", GAP_REPORT_SCHEMA_VERSION),
            report_id=value.get("report_id", ""),
            output_kind=value.get(
                "output_kind", OUTPUT_KIND_REQUIREMENT_EVIDENCE_GAP_REPORT
            ),
            source_bundle_id=value.get("source_bundle_id", ""),
            source_bundle_digest=value.get("source_bundle_digest", ""),
            label=value.get("label", GapReportLabel.REVIEW_REQUIRED.value),
            mandatory_review_remaining=bool(
                value.get("mandatory_review_remaining", True)
            ),
            unknown_count=int(value.get("unknown_count") or 0),
            gap_count=int(value.get("gap_count") or 0),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            review_state=value.get("review_state", ReviewState.PENDING.value),
            matter_summary=MatterSummary.from_dict(value.get("matter_summary") or {}),
            inventory=tuple(
                ArtifactInventoryItem.from_dict(i)
                for i in (value.get("inventory") or ())
            ),
            requirement_rows=tuple(
                RequirementGapRow.from_dict(r)
                for r in (value.get("requirement_rows") or ())
            ),
            candidate_dates=tuple(
                CandidateDateProjection.from_dict(c)
                for c in (value.get("candidate_dates") or ())
            ),
            reviewer_actions=tuple(
                ReviewerActionProjection.from_dict(a)
                for a in (value.get("reviewer_actions") or ())
            ),
            unknowns=tuple(
                GapStatement.from_dict(u) for u in (value.get("unknowns") or ())
            ),
            statements=tuple(
                GapStatement.from_dict(s) for s in (value.get("statements") or ())
            ),
            warnings=tuple(value.get("warnings") or ()),
            reason_codes=tuple(value.get("reason_codes") or ()),
            ruleset_versions=value.get("ruleset_versions") or {},
            output_policy=OutputRedactionPolicy.from_dict(policy_raw),
            redaction_applied=bool(value.get("redaction_applied", False)),
            content_digest=value.get("content_digest", ""),
            human_readable=value.get("human_readable", "gap report"),
            disclaimer=value.get("disclaimer", GAP_REPORT_DISCLAIMER),
            matter_id=value.get("matter_id"),
            analysis_id=value.get("analysis_id"),
            labels=value.get("labels") or {},
        )


# ---------------------------------------------------------------------------
# Input + renderer
# ---------------------------------------------------------------------------


@dataclass
class GapReportInput:
    """Inputs for deterministic gap-report projection.

    The analysis bundle is required. Optional analysis records (compliance
    assessments, candidate dates, reviewer actions) are **projected only** —
    never recomputed.
    """

    analysis_bundle: UsptoAnalysisBundle
    assessments: Sequence[Any] = ()
    candidate_dates: Sequence[Any] = ()
    reviewer_actions: Sequence[Any] = ()
    requirements: Sequence[Any] = ()
    output_policy: OutputRedactionPolicy = DEFAULT_OUTPUT_POLICY
    labels: Mapping[str, str] = MappingProxyType({})
    matter_id: str | None = None
    analysis_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.analysis_bundle, UsptoAnalysisBundle):
            raise TypeError("analysis_bundle must be UsptoAnalysisBundle")
        if not isinstance(self.output_policy, OutputRedactionPolicy):
            if isinstance(self.output_policy, Mapping):
                self.output_policy = OutputRedactionPolicy.from_dict(
                    self.output_policy
                )
            else:
                raise TypeError("output_policy must be OutputRedactionPolicy")
        if not isinstance(self.assessments, Sequence) or isinstance(
            self.assessments, (str, bytes)
        ):
            raise TypeError("assessments must be a sequence")
        if not isinstance(self.candidate_dates, Sequence) or isinstance(
            self.candidate_dates, (str, bytes)
        ):
            raise TypeError("candidate_dates must be a sequence")
        if not isinstance(self.reviewer_actions, Sequence) or isinstance(
            self.reviewer_actions, (str, bytes)
        ):
            raise TypeError("reviewer_actions must be a sequence")
        if not isinstance(self.requirements, Sequence) or isinstance(
            self.requirements, (str, bytes)
        ):
            raise TypeError("requirements must be a sequence")
        self.labels = _frozen_str_map(self.labels, "labels", max_items=32)
        if self.matter_id is not None:
            self.matter_id = _optional_identifier(self.matter_id, "matter_id")
        if self.analysis_id is not None:
            self.analysis_id = _optional_identifier(self.analysis_id, "analysis_id")


class GapReportRenderer:
    """Project an analysis bundle into a requirement/evidence gap report."""

    def __init__(
        self,
        *,
        id_factory: Callable[[], str] | None = None,
        output_policy: OutputRedactionPolicy | None = None,
    ) -> None:
        self._id_factory = id_factory or _default_id_factory
        self._default_policy = output_policy or DEFAULT_OUTPUT_POLICY

    def render(self, report_input: GapReportInput) -> RequirementEvidenceGapReport:
        if not isinstance(report_input, GapReportInput):
            raise TypeError("report_input must be GapReportInput")
        return self._render(report_input)

    def process(self, report_input: GapReportInput) -> RequirementEvidenceGapReport:
        return self.render(report_input)

    def render_bundle(
        self,
        bundle: UsptoAnalysisBundle,
        **kwargs: Any,
    ) -> RequirementEvidenceGapReport:
        policy = kwargs.pop("output_policy", self._default_policy)
        return self.render(
            GapReportInput(analysis_bundle=bundle, output_policy=policy, **kwargs)
        )

    # ---- internal ----

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}:{self._id_factory()}"

    def _render(self, inp: GapReportInput) -> RequirementEvidenceGapReport:
        bundle = inp.analysis_bundle
        policy = inp.output_policy
        matter_id = inp.matter_id or bundle.matter_id
        analysis_id = inp.analysis_id or bundle.analysis_id
        classification = bundle.classification

        provenance_by_subject = self._index_provenance(bundle.provenance)
        redaction_applied = False

        # --- Matter summary ---
        section_counts: dict[str, str] = {}
        for kind in BundleSectionKind:
            count = len(bundle.sections_by_kind(kind))
            if count:
                section_counts[kind.value] = str(count)

        bundle_link = SourceLink(
            link_id=self._new_id("src"),
            role="analysis_bundle",
            artifact_ids=tuple(bundle.input_artifact_ids[:64]),
            record_ids=(bundle.bundle_id,),
            notes=(f"digest:{bundle.bundle_digest[:16]}",),
        )
        matter_summary = MatterSummary(
            matter_id=matter_id,
            bundle_id=bundle.bundle_id,
            bundle_digest=bundle.bundle_digest,
            disposition=(
                bundle.disposition.value
                if hasattr(bundle.disposition, "value")
                else str(bundle.disposition)
            ),
            review_state=bundle.review_state,
            classification=classification,
            section_counts=section_counts,
            warning_codes=tuple(bundle.warning_codes),
            unsupported_checks=tuple(bundle.unsupported_checks),
            validation_receipt_ids=tuple(bundle.validation_receipt_ids),
            input_artifact_ids=tuple(bundle.input_artifact_ids),
            source_links=(bundle_link,),
            analysis_id=analysis_id,
            requires_review=bool(bundle.requires_review),
            labels=dict(bundle.labels),
        )

        statements: list[GapStatement] = []
        unknowns: list[GapStatement] = []
        inventory: list[ArtifactInventoryItem] = []
        requirement_rows: list[RequirementGapRow] = []
        candidate_dates: list[CandidateDateProjection] = []
        reviewer_actions: list[ReviewerActionProjection] = []
        warnings: list[str] = [w.message for w in bundle.warnings]
        reason_codes: list[str] = list(bundle.warning_codes)

        # Bundle binding statement
        bind_stmt = GapStatement(
            statement_id=self._new_id("stmt"),
            kind=StatementKind.BUNDLE_BINDING,
            summary=(
                f"Report bound to analysis bundle {bundle.bundle_id} "
                f"(digest {bundle.bundle_digest[:16]}…)"
            ),
            status=GapStatus.SATISFIED,
            source_links=(bundle_link,),
            is_unknown=False,
            is_prominent_unknown=False,
            classification=classification,
            redacted=False,
            reason_codes=("bundle_bound",),
            related_ids=(bundle.bundle_id,),
        )
        statements.append(bind_stmt)

        # Matter summary statement
        matter_stmt = GapStatement(
            statement_id=self._new_id("stmt"),
            kind=StatementKind.MATTER_SUMMARY,
            summary=(
                f"Matter {matter_id or 'unknown'} disposition="
                f"{matter_summary.disposition} review={bundle.review_state.value}"
            ),
            status=(
                GapStatus.UNKNOWN
                if bundle.requires_review
                else GapStatus.SATISFIED
            ),
            source_links=(bundle_link,),
            is_unknown=bool(bundle.requires_review),
            is_prominent_unknown=bool(bundle.requires_review),
            classification=classification,
            redacted=False,
            reason_codes=tuple(bundle.warning_codes[:16]),
            related_ids=tuple(
                x for x in (matter_id, analysis_id, bundle.bundle_id) if x
            ),
        )
        statements.append(matter_stmt)
        if matter_stmt.is_prominent_unknown:
            unknowns.append(matter_stmt)

        # --- Artifact / receipt inventory ---
        seen_artifacts: set[str] = set()
        for section in bundle.sections_by_kind(BundleSectionKind.ARTIFACT_MANIFEST):
            item, stmt, redacted = self._inventory_from_section(
                section, policy=policy, role="artifact"
            )
            inventory.append(item)
            statements.append(stmt)
            redaction_applied = redaction_applied or redacted
            if section.record_id:
                seen_artifacts.add(section.record_id)
        for aid in bundle.input_artifact_ids:
            if aid in seen_artifacts:
                continue
            link = SourceLink(
                link_id=self._new_id("src"),
                role="input_artifact",
                artifact_ids=(aid,),
                record_ids=(aid,),
            )
            item = ArtifactInventoryItem(
                item_id=self._new_id("inv"),
                kind="input_artifact",
                artifact_id=aid,
                receipt_id=None,
                content_digest=None,
                classification=classification,
                source_links=(link,),
            )
            inventory.append(item)
            statements.append(
                GapStatement(
                    statement_id=self._new_id("stmt"),
                    kind=StatementKind.ARTIFACT,
                    summary=f"Input artifact {aid}",
                    status=GapStatus.SATISFIED,
                    source_links=(link,),
                    is_unknown=False,
                    is_prominent_unknown=False,
                    classification=classification,
                    redacted=False,
                    related_ids=(aid,),
                )
            )
            seen_artifacts.add(aid)

        for rid in bundle.validation_receipt_ids:
            link = SourceLink(
                link_id=self._new_id("src"),
                role="validation_receipt",
                record_ids=(rid,),
            )
            inventory.append(
                ArtifactInventoryItem(
                    item_id=self._new_id("inv"),
                    kind="validation_receipt",
                    artifact_id=None,
                    receipt_id=rid,
                    content_digest=None,
                    classification=classification,
                    source_links=(link,),
                )
            )
            statements.append(
                GapStatement(
                    statement_id=self._new_id("stmt"),
                    kind=StatementKind.RECEIPT,
                    summary=f"Validation receipt {rid}",
                    status=GapStatus.SATISFIED,
                    source_links=(link,),
                    is_unknown=False,
                    is_prominent_unknown=False,
                    classification=classification,
                    redacted=False,
                    related_ids=(rid,),
                )
            )

        # Unsupported checks → prominent unknowns
        for check in bundle.unsupported_checks:
            link = SourceLink(
                link_id=self._new_id("src"),
                role="unsupported_check",
                record_ids=(check,),
                notes=("unsupported_check",),
            )
            stmt = GapStatement(
                statement_id=self._new_id("stmt"),
                kind=StatementKind.UNKNOWN,
                summary=f"{UNKNOWN_BANNER}: unsupported check {check}",
                status=GapStatus.UNKNOWN,
                source_links=(link,),
                is_unknown=True,
                is_prominent_unknown=True,
                classification=classification,
                redacted=False,
                reason_codes=("unsupported_check",),
                related_ids=(check,),
            )
            statements.append(stmt)
            unknowns.append(stmt)

        # Missing provenance → prominent unknowns
        for link in bundle.provenance:
            if link.is_traced:
                continue
            src = SourceLink(
                link_id=self._new_id("src"),
                role="missing_provenance",
                record_ids=(link.subject_id, link.link_id),
                notes=(f"subject_kind:{link.subject_kind}",),
            )
            stmt = GapStatement(
                statement_id=self._new_id("stmt"),
                kind=StatementKind.UNKNOWN,
                summary=(
                    f"{UNKNOWN_BANNER}: untraced subject {link.subject_id} "
                    f"({link.subject_kind})"
                ),
                status=GapStatus.UNKNOWN,
                source_links=(src,),
                is_unknown=True,
                is_prominent_unknown=True,
                classification=classification,
                redacted=False,
                reason_codes=("missing_provenance",),
                related_ids=(link.subject_id,),
            )
            statements.append(stmt)
            unknowns.append(stmt)

        # --- Requirement rows from assessments or requirement sections ---
        assessment_maps = [
            m for m in (_as_mapping(a) for a in inp.assessments) if m is not None
        ]
        requirement_maps = [
            m for m in (_as_mapping(r) for r in inp.requirements) if m is not None
        ]
        req_type_by_id: dict[str, str] = {}
        for req in requirement_maps:
            rid = str(req.get("requirement_id") or req.get("record_id") or "")
            if rid:
                req_type_by_id[rid] = str(
                    req.get("requirement_type") or req.get("type") or "unknown"
                )

        covered_req_ids: set[str] = set()
        if assessment_maps:
            for raw in assessment_maps:
                row, row_stmts, row_actions, redacted = self._row_from_assessment(
                    raw,
                    policy=policy,
                    provenance_by_subject=provenance_by_subject,
                    bundle=bundle,
                    req_type_by_id=req_type_by_id,
                )
                requirement_rows.append(row)
                statements.extend(row_stmts)
                for u in row_stmts:
                    if u.is_prominent_unknown:
                        unknowns.append(u)
                reviewer_actions.extend(row_actions)
                covered_req_ids.add(row.requirement_id)
                redaction_applied = redaction_applied or redacted
        else:
            # Project requirement sections as unknown/open rows (fail-closed).
            for section in bundle.sections_by_kind(BundleSectionKind.REQUIREMENT):
                row, row_stmts, redacted = self._row_from_requirement_section(
                    section,
                    policy=policy,
                    provenance_by_subject=provenance_by_subject,
                )
                requirement_rows.append(row)
                statements.extend(row_stmts)
                for u in row_stmts:
                    if u.is_prominent_unknown:
                        unknowns.append(u)
                covered_req_ids.add(row.requirement_id)
                redaction_applied = redaction_applied or redacted

            # Assessment sections without full payloads → status rows.
            for section in bundle.sections_by_kind(BundleSectionKind.ASSESSMENT):
                if section.record_id in covered_req_ids:
                    continue
                row, row_stmts, redacted = self._row_from_assessment_section(
                    section,
                    policy=policy,
                    provenance_by_subject=provenance_by_subject,
                )
                requirement_rows.append(row)
                statements.extend(row_stmts)
                for u in row_stmts:
                    if u.is_prominent_unknown:
                        unknowns.append(u)
                covered_req_ids.add(row.requirement_id)
                redaction_applied = redaction_applied or redacted

        # Explicit requirement maps not covered by assessments
        for req in requirement_maps:
            rid = str(req.get("requirement_id") or "")
            if not rid or rid in covered_req_ids:
                continue
            row, row_stmts, redacted = self._row_from_requirement_map(
                req,
                policy=policy,
                provenance_by_subject=provenance_by_subject,
                bundle=bundle,
            )
            requirement_rows.append(row)
            statements.extend(row_stmts)
            for u in row_stmts:
                if u.is_prominent_unknown:
                    unknowns.append(u)
            redaction_applied = redaction_applied or redacted

        # --- Candidate dates ---
        date_maps = [
            m
            for m in (_as_mapping(c) for c in inp.candidate_dates)
            if m is not None
        ]
        if date_maps:
            for raw in date_maps:
                cand, stmt, redacted = self._candidate_from_map(
                    raw,
                    policy=policy,
                    provenance_by_subject=provenance_by_subject,
                    bundle=bundle,
                )
                candidate_dates.append(cand)
                statements.append(stmt)
                if stmt.is_prominent_unknown:
                    unknowns.append(stmt)
                redaction_applied = redaction_applied or redacted
        else:
            for section in bundle.sections_by_kind(BundleSectionKind.CANDIDATE_DATE):
                cand, stmt, redacted = self._candidate_from_section(
                    section,
                    policy=policy,
                    provenance_by_subject=provenance_by_subject,
                )
                candidate_dates.append(cand)
                statements.append(stmt)
                if stmt.is_prominent_unknown:
                    unknowns.append(stmt)
                redaction_applied = redaction_applied or redacted

        # --- Package-level reviewer actions ---
        action_maps = [
            m
            for m in (_as_mapping(a) for a in inp.reviewer_actions)
            if m is not None
        ]
        for raw in action_maps:
            action, stmt, redacted = self._action_from_map(
                raw,
                policy=policy,
                classification=classification,
                bundle=bundle,
            )
            # De-dupe by action_id
            if any(a.action_id == action.action_id for a in reviewer_actions):
                continue
            reviewer_actions.append(action)
            statements.append(stmt)
            if stmt.is_prominent_unknown:
                unknowns.append(stmt)
            redaction_applied = redaction_applied or redacted

        # If package requires review and no actions yet, emit package review.
        package_needs_review = bool(
            bundle.requires_review
            or any(r.blocks_clearance for r in requirement_rows)
            or unknowns
            or bundle.unsupported_checks
        )
        if package_needs_review and not reviewer_actions:
            link = SourceLink(
                link_id=self._new_id("src"),
                role="package_review",
                record_ids=(bundle.bundle_id,),
                artifact_ids=tuple(bundle.input_artifact_ids[:16]),
            )
            msg, redacted = policy.redact_text(
                "Mandatory human review of package gaps/unknowns is required",
                classification,
            )
            redaction_applied = redaction_applied or redacted
            action = ReviewerActionProjection(
                action_id=self._new_id("action"),
                kind="review_package",
                message=msg or REDACTION_TOKEN,
                priority=10,
                source_links=(link,),
                requirement_id=None,
                reason_codes=("mandatory_review",),
                redacted=redacted,
                classification=classification,
            )
            reviewer_actions.append(action)
            statements.append(
                GapStatement(
                    statement_id=self._new_id("stmt"),
                    kind=StatementKind.REVIEWER_ACTION,
                    summary=f"Reviewer action: {action.kind}",
                    status=GapStatus.UNKNOWN,
                    source_links=(link,),
                    is_unknown=True,
                    is_prominent_unknown=True,
                    classification=classification,
                    redacted=redacted,
                    detail_text=action.message,
                    reason_codes=tuple(action.reason_codes),
                    related_ids=(action.action_id,),
                )
            )

        # Counts
        unknown_count = sum(
            1
            for r in requirement_rows
            if r.mandatory and r.is_unknown
        ) + len([u for u in unknowns if u.is_prominent_unknown])
        # Prefer explicit unknown statement count for prominence.
        unknown_count = len([u for u in unknowns if u.is_prominent_unknown])
        # Also count mandatory unknown requirement rows not already in unknowns.
        for r in requirement_rows:
            if r.mandatory and r.is_unknown:
                # Ensure counted via unknowns list if not already present.
                if not any(
                    r.requirement_id in s.related_ids for s in unknowns
                ):
                    unknown_count += 1

        gap_count = sum(
            1
            for r in requirement_rows
            if r.mandatory and _is_open_gap(r.gap_status, mandatory=True)
        )

        mandatory_review_remaining = bool(
            package_needs_review
            or reviewer_actions
            or unknown_count > 0
            or gap_count > 0
            or bundle.review_state
            in (ReviewState.REQUIRED, ReviewState.PENDING)
        )

        # Never all_clear when mandatory review remains.
        label = self._compute_label(
            classification=classification,
            mandatory_review_remaining=mandatory_review_remaining,
            unknown_count=unknown_count,
            gap_count=gap_count,
            requirement_rows=requirement_rows,
            reviewer_actions=reviewer_actions,
            bundle=bundle,
            inventory=inventory,
        )

        review_state = bundle.review_state
        if mandatory_review_remaining and review_state is ReviewState.NOT_REQUIRED:
            review_state = ReviewState.REQUIRED
        if requires_quarantine(classification):
            review_state = ReviewState.REQUIRED

        ruleset_versions = dict(bundle.ruleset_versions)
        ruleset_versions["gap_report"] = GAP_REPORT_RULESET_VERSION
        ruleset_versions["gap_report_parser"] = PARSER_VERSION
        ruleset_versions.setdefault("contracts", CONTRACTS_SCHEMA_VERSION)
        ruleset_versions.setdefault(
            "analysis_bundle", ANALYSIS_BUNDLE_SCHEMA_VERSION
        )

        # Sort for determinism
        requirement_rows.sort(key=lambda r: (r.requirement_id, r.row_id))
        candidate_dates.sort(key=lambda c: c.candidate_id)
        reviewer_actions.sort(key=lambda a: (a.priority, a.action_id))
        inventory.sort(key=lambda i: i.item_id)
        statements.sort(key=lambda s: s.statement_id)
        unknowns.sort(key=lambda s: s.statement_id)

        human_readable = self._render_markdown(
            label=label,
            matter_summary=matter_summary,
            inventory=inventory,
            requirement_rows=requirement_rows,
            candidate_dates=candidate_dates,
            reviewer_actions=reviewer_actions,
            unknowns=unknowns,
            warnings=warnings,
            mandatory_review_remaining=mandatory_review_remaining,
            unknown_count=unknown_count,
            gap_count=gap_count,
            classification=classification,
            redaction_applied=redaction_applied,
            policy=policy,
        )
        if policy.must_redact(classification):
            # Entire human-readable surface is identifiers-oriented when private.
            if policy.mode is OutputPolicyMode.IDENTIFIERS_ONLY or is_private_classification(
                classification
            ):
                human_readable = self._render_markdown_redacted(
                    label=label,
                    matter_summary=matter_summary,
                    inventory=inventory,
                    requirement_rows=requirement_rows,
                    candidate_dates=candidate_dates,
                    reviewer_actions=reviewer_actions,
                    unknowns=unknowns,
                    mandatory_review_remaining=mandatory_review_remaining,
                    unknown_count=unknown_count,
                    gap_count=gap_count,
                    classification=classification,
                    policy=policy,
                )
                redaction_applied = True

        report_id = self._new_id("gap")
        # Material digest excludes report_id / content_digest / human_readable body
        # but includes a stable hash of human_readable for rehydration checks.
        material = {
            "analysis_id": analysis_id,
            "candidate_dates": [c.to_dict() for c in candidate_dates],
            "classification": classification.value,
            "disclaimer": GAP_REPORT_DISCLAIMER,
            "gap_count": gap_count,
            "human_readable_digest": sha256_hex(human_readable),
            "inventory": [i.to_dict() for i in inventory],
            "label": label.value,
            "labels": dict(sorted(inp.labels.items())),
            "mandatory_review_remaining": mandatory_review_remaining,
            "matter_id": matter_id,
            "matter_summary": matter_summary.to_dict(),
            "output_kind": OUTPUT_KIND_REQUIREMENT_EVIDENCE_GAP_REPORT,
            "output_policy": policy.to_dict(),
            "reason_codes": list(dict.fromkeys(reason_codes)),
            "redaction_applied": redaction_applied,
            "requirement_rows": [r.to_dict() for r in requirement_rows],
            "review_state": review_state.value,
            "reviewer_actions": [a.to_dict() for a in reviewer_actions],
            "ruleset_versions": dict(sorted(ruleset_versions.items())),
            "schema_version": GAP_REPORT_SCHEMA_VERSION,
            "source_bundle_digest": bundle.bundle_digest,
            "source_bundle_id": bundle.bundle_id,
            "statements": [s.to_dict() for s in statements],
            "unknown_count": unknown_count,
            "unknowns": [u.to_dict() for u in unknowns],
            "warnings": list(warnings),
        }
        content_digest = sha256_hex(canonical_json(material))

        return RequirementEvidenceGapReport(
            schema_version=GAP_REPORT_SCHEMA_VERSION,
            report_id=report_id,
            output_kind=OUTPUT_KIND_REQUIREMENT_EVIDENCE_GAP_REPORT,
            source_bundle_id=bundle.bundle_id,
            source_bundle_digest=bundle.bundle_digest,
            label=label,
            mandatory_review_remaining=mandatory_review_remaining,
            unknown_count=unknown_count,
            gap_count=gap_count,
            classification=classification,
            review_state=review_state,
            matter_summary=matter_summary,
            inventory=tuple(inventory),
            requirement_rows=tuple(requirement_rows),
            candidate_dates=tuple(candidate_dates),
            reviewer_actions=tuple(reviewer_actions),
            unknowns=tuple(unknowns),
            statements=tuple(statements),
            warnings=tuple(warnings),
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            ruleset_versions=ruleset_versions,
            output_policy=policy,
            redaction_applied=redaction_applied,
            content_digest=content_digest,
            human_readable=human_readable,
            disclaimer=GAP_REPORT_DISCLAIMER,
            matter_id=matter_id,
            analysis_id=analysis_id,
            labels=dict(inp.labels),
        )

    def _compute_label(
        self,
        *,
        classification: DisclosureClassification,
        mandatory_review_remaining: bool,
        unknown_count: int,
        gap_count: int,
        requirement_rows: Sequence[RequirementGapRow],
        reviewer_actions: Sequence[ReviewerActionProjection],
        bundle: UsptoAnalysisBundle,
        inventory: Sequence[ArtifactInventoryItem],
    ) -> GapReportLabel:
        if requires_quarantine(classification):
            return GapReportLabel.QUARANTINE
        if not inventory and not requirement_rows and not bundle.sections:
            return GapReportLabel.EMPTY
        # Hard rule: never all_clear with mandatory review.
        if mandatory_review_remaining:
            if unknown_count > 0:
                return GapReportLabel.UNKNOWNS_PRESENT
            if gap_count > 0:
                return GapReportLabel.GAPS_PRESENT
            if reviewer_actions:
                return GapReportLabel.REVIEW_REQUIRED
            return GapReportLabel.REVIEW_REQUIRED
        if unknown_count > 0:
            return GapReportLabel.UNKNOWNS_PRESENT
        if gap_count > 0:
            return GapReportLabel.GAPS_PRESENT
        if bundle.disposition.value in ("partial", "review", "unknown"):
            return GapReportLabel.PARTIAL
        if reviewer_actions:
            return GapReportLabel.REVIEW_REQUIRED
        return GapReportLabel.ALL_CLEAR

    def _index_provenance(
        self, provenance: Sequence[ProvenanceLink]
    ) -> dict[str, ProvenanceLink]:
        out: dict[str, ProvenanceLink] = {}
        for link in provenance:
            out.setdefault(link.subject_id, link)
        return out

    def _source_from_section(
        self,
        section: BundleSectionRef,
        *,
        role: str,
        provenance_by_subject: Mapping[str, ProvenanceLink],
        extra_spans: Sequence[str] = (),
    ) -> SourceLink:
        prov = provenance_by_subject.get(section.record_id)
        artifact_ids = list(section.source_artifact_ids)
        authority_ids = list(section.authority_ids)
        span_ids = list(extra_spans)
        if prov is not None:
            for a in prov.artifact_ids:
                if a not in artifact_ids:
                    artifact_ids.append(a)
            for a in prov.authority_ids:
                if a not in authority_ids:
                    authority_ids.append(a)
            for s in prov.span_ids:
                if s not in span_ids:
                    span_ids.append(s)
        return SourceLink(
            link_id=self._new_id("src"),
            role=role,
            artifact_ids=tuple(artifact_ids),
            authority_ids=tuple(authority_ids),
            span_ids=tuple(span_ids),
            section_ids=(section.section_id,),
            record_ids=(section.record_id,),
        )

    def _inventory_from_section(
        self,
        section: BundleSectionRef,
        *,
        policy: OutputRedactionPolicy,
        role: str,
    ) -> tuple[ArtifactInventoryItem, GapStatement, bool]:
        del policy  # inventory uses digests/ids only
        link = SourceLink(
            link_id=self._new_id("src"),
            role=role,
            artifact_ids=tuple(section.source_artifact_ids)
            or ((section.record_id,) if section.record_id else ()),
            section_ids=(section.section_id,),
            record_ids=(section.record_id,),
        )
        item = ArtifactInventoryItem(
            item_id=self._new_id("inv"),
            kind=section.kind.value,
            artifact_id=section.record_id,
            receipt_id=None,
            content_digest=section.content_digest,
            classification=section.classification,
            source_links=(link,),
            section_id=section.section_id,
            labels=dict(section.labels),
        )
        stmt = GapStatement(
            statement_id=self._new_id("stmt"),
            kind=StatementKind.ARTIFACT,
            summary=f"Artifact inventory {section.record_id}",
            status=GapStatus.SATISFIED,
            source_links=(link,),
            is_unknown=False,
            is_prominent_unknown=False,
            classification=section.classification,
            redacted=False,
            related_ids=(section.record_id, section.section_id),
        )
        return item, stmt, False

    def _row_from_assessment(
        self,
        raw: Mapping[str, Any],
        *,
        policy: OutputRedactionPolicy,
        provenance_by_subject: Mapping[str, ProvenanceLink],
        bundle: UsptoAnalysisBundle,
        req_type_by_id: Mapping[str, str],
    ) -> tuple[
        RequirementGapRow,
        list[GapStatement],
        list[ReviewerActionProjection],
        bool,
    ]:
        requirement_id = _identifier(
            str(raw.get("requirement_id") or raw.get("assessment_id") or "req:unknown"),
            "requirement_id",
        )
        assessment_id = _optional_identifier(
            raw.get("assessment_id"), "assessment_id"
        )
        status = _status_from_raw(raw.get("status"))
        mandatory = bool(raw.get("mandatory", True))
        classification = _coerce_classification(
            raw.get("classification", bundle.classification)
        )
        req_type = str(
            raw.get("requirement_type")
            or req_type_by_id.get(requirement_id)
            or "unknown"
        )
        authority_ids: list[str] = []
        auth_raw = raw.get("authority")
        if isinstance(auth_raw, Mapping):
            for key in ("authority_ids", "selected_versions", "node_ids"):
                vals = auth_raw.get(key) or ()
                if isinstance(vals, Sequence) and not isinstance(vals, (str, bytes)):
                    for v in vals:
                        authority_ids.append(str(v))
            if auth_raw.get("authority_id"):
                authority_ids.append(str(auth_raw["authority_id"]))
            if auth_raw.get("snapshot_id"):
                authority_ids.append(str(auth_raw["snapshot_id"]))
        if raw.get("authority_snapshot_id"):
            authority_ids.append(str(raw["authority_snapshot_id"]))
        authority_ids = list(dict.fromkeys(authority_ids))

        evidence = tuple(
            str(x)
            for x in (
                raw.get("evidence_span_ids")
                or raw.get("support_span_ids")
                or ()
            )
        )
        counter = tuple(
            str(x)
            for x in (
                raw.get("counter_evidence_span_ids")
                or raw.get("counter_span_ids")
                or ()
            )
        )
        reason_codes = tuple(str(x) for x in (raw.get("reason_codes") or raw.get("reasons") or ()))
        uncertainty = str(
            raw.get("uncertainty")
            or (
                "unknown assessment — human review required"
                if status is GapStatus.UNKNOWN
                else (
                    "unsatisfied — evidence gap"
                    if status is GapStatus.UNSATISFIED
                    else "no residual uncertainty recorded"
                )
            )
        )
        gap_status = status
        if status is GapStatus.UNSATISFIED:
            gap_status = GapStatus.GAP
        elif status is GapStatus.UNKNOWN:
            gap_status = GapStatus.UNKNOWN
        elif status is GapStatus.SATISFIED:
            gap_status = GapStatus.SATISFIED
        elif status is GapStatus.NOT_APPLICABLE:
            gap_status = GapStatus.NOT_APPLICABLE

        prov = provenance_by_subject.get(requirement_id) or provenance_by_subject.get(
            assessment_id or ""
        )
        artifact_ids = list(prov.artifact_ids) if prov else []
        if not artifact_ids:
            # Fall back to bundle requirement/assessment sections.
            for section in bundle.sections:
                if section.record_id in (requirement_id, assessment_id):
                    artifact_ids.extend(section.source_artifact_ids)
                    for a in section.authority_ids:
                        if a not in authority_ids:
                            authority_ids.append(a)

        link = SourceLink(
            link_id=self._new_id("src"),
            role="requirement_assessment",
            artifact_ids=tuple(dict.fromkeys(artifact_ids)),
            authority_ids=tuple(authority_ids),
            span_ids=tuple(dict.fromkeys(list(evidence) + list(counter))),
            record_ids=tuple(
                x for x in (requirement_id, assessment_id) if x
            ),
        )
        redaction_applied = False
        stmts: list[GapStatement] = []
        actions: list[ReviewerActionProjection] = []

        # Demand statement
        summary = f"Requirement {requirement_id} type={req_type} status={status.value}"
        detail = raw.get("explanation") or raw.get("detail_text")
        detail_s, redacted = policy.redact_text(
            str(detail) if detail is not None else None, classification
        )
        redaction_applied = redaction_applied or redacted
        is_unk = _is_blocking_unknown(status, mandatory=mandatory)
        stmts.append(
            GapStatement(
                statement_id=self._new_id("stmt"),
                kind=StatementKind.REQUIREMENT,
                summary=summary,
                status=status,
                source_links=(link,),
                is_unknown=is_unk,
                is_prominent_unknown=is_unk,
                classification=classification,
                redacted=redacted,
                detail_text=detail_s,
                reason_codes=reason_codes,
                related_ids=tuple(
                    x for x in (requirement_id, assessment_id) if x
                ),
            )
        )
        # Authority
        if authority_ids:
            auth_link = SourceLink(
                link_id=self._new_id("src"),
                role="authority",
                authority_ids=tuple(authority_ids),
                artifact_ids=tuple(dict.fromkeys(artifact_ids)),
                record_ids=(requirement_id,),
            )
            stmts.append(
                GapStatement(
                    statement_id=self._new_id("stmt"),
                    kind=StatementKind.AUTHORITY,
                    summary=f"Authority for {requirement_id}: {', '.join(authority_ids[:8])}",
                    status=GapStatus.SATISFIED,
                    source_links=(auth_link,),
                    is_unknown=False,
                    is_prominent_unknown=False,
                    classification=classification,
                    redacted=False,
                    related_ids=tuple(authority_ids[:16]),
                )
            )
        else:
            auth_link = SourceLink(
                link_id=self._new_id("src"),
                role="authority_missing",
                record_ids=(requirement_id,),
            )
            stmts.append(
                GapStatement(
                    statement_id=self._new_id("stmt"),
                    kind=StatementKind.UNKNOWN,
                    summary=f"{UNKNOWN_BANNER}: missing authority for {requirement_id}",
                    status=GapStatus.UNKNOWN,
                    source_links=(auth_link,),
                    is_unknown=True,
                    is_prominent_unknown=True,
                    classification=classification,
                    redacted=False,
                    reason_codes=("missing_authority",),
                    related_ids=(requirement_id,),
                )
            )

        # Evidence / counter-evidence
        if evidence:
            e_link = SourceLink(
                link_id=self._new_id("src"),
                role="evidence",
                span_ids=evidence,
                artifact_ids=tuple(dict.fromkeys(artifact_ids)),
                record_ids=(requirement_id,),
            )
            stmts.append(
                GapStatement(
                    statement_id=self._new_id("stmt"),
                    kind=StatementKind.EVIDENCE,
                    summary=(
                        f"Evidence spans for {requirement_id}: "
                        f"{', '.join(evidence[:8])}"
                    ),
                    status=GapStatus.SATISFIED,
                    source_links=(e_link,),
                    is_unknown=False,
                    is_prominent_unknown=False,
                    classification=classification,
                    redacted=False,
                    related_ids=evidence,
                )
            )
        else:
            e_link = SourceLink(
                link_id=self._new_id("src"),
                role="evidence_missing",
                record_ids=(requirement_id,),
            )
            miss = mandatory and status is not GapStatus.NOT_APPLICABLE
            stmts.append(
                GapStatement(
                    statement_id=self._new_id("stmt"),
                    kind=StatementKind.GAP if miss else StatementKind.EVIDENCE,
                    summary=(
                        f"{UNKNOWN_BANNER if miss else 'Note'}: no evidence spans "
                        f"for {requirement_id}"
                    ),
                    status=GapStatus.MISSING if miss else GapStatus.NOT_APPLICABLE,
                    source_links=(e_link,),
                    is_unknown=miss,
                    is_prominent_unknown=miss,
                    classification=classification,
                    redacted=False,
                    reason_codes=("missing_evidence",) if miss else (),
                    related_ids=(requirement_id,),
                )
            )

        if counter:
            c_link = SourceLink(
                link_id=self._new_id("src"),
                role="counter_evidence",
                span_ids=counter,
                artifact_ids=tuple(dict.fromkeys(artifact_ids)),
                record_ids=(requirement_id,),
            )
            stmts.append(
                GapStatement(
                    statement_id=self._new_id("stmt"),
                    kind=StatementKind.COUNTER_EVIDENCE,
                    summary=(
                        f"Counter-evidence spans for {requirement_id}: "
                        f"{', '.join(counter[:8])}"
                    ),
                    status=GapStatus.UNSATISFIED,
                    source_links=(c_link,),
                    is_unknown=False,
                    is_prominent_unknown=False,
                    classification=classification,
                    redacted=False,
                    related_ids=counter,
                )
            )

        # Gap / status / uncertainty
        unc_text, unc_redacted = policy.redact_text(uncertainty, classification)
        redaction_applied = redaction_applied or unc_redacted
        stmts.append(
            GapStatement(
                statement_id=self._new_id("stmt"),
                kind=StatementKind.UNCERTAINTY,
                summary=f"Uncertainty for {requirement_id}: {unc_text}",
                status=status if status is not GapStatus.SATISFIED else GapStatus.SATISFIED,
                source_links=(link,),
                is_unknown=status is GapStatus.UNKNOWN,
                is_prominent_unknown=status is GapStatus.UNKNOWN and mandatory,
                classification=classification,
                redacted=unc_redacted,
                detail_text=unc_text,
                reason_codes=reason_codes,
                related_ids=(requirement_id,),
            )
        )
        stmts.append(
            GapStatement(
                statement_id=self._new_id("stmt"),
                kind=StatementKind.GAP,
                summary=f"Gap status for {requirement_id}: {gap_status.value}",
                status=gap_status,
                source_links=(link,),
                is_unknown=gap_status is GapStatus.UNKNOWN,
                is_prominent_unknown=(
                    gap_status is GapStatus.UNKNOWN and mandatory
                ),
                classification=classification,
                redacted=False,
                reason_codes=reason_codes,
                related_ids=(requirement_id,),
            )
        )

        # Reviewer action from assessment
        action_raw = raw.get("reviewer_action")
        required_human = raw.get("required_human_action")
        row_action: ReviewerActionProjection | None = None
        if isinstance(action_raw, Mapping) or action_raw is not None:
            mapped = _as_mapping(action_raw) or {}
            if mapped:
                action, action_stmt, a_red = self._action_from_map(
                    mapped,
                    policy=policy,
                    classification=classification,
                    bundle=bundle,
                    default_requirement_id=requirement_id,
                )
                row_action = action
                actions.append(action)
                stmts.append(action_stmt)
                redaction_applied = redaction_applied or a_red
        elif required_human or (
            mandatory and status is not GapStatus.SATISFIED
            and status is not GapStatus.NOT_APPLICABLE
        ):
            kind = str(required_human or "review_evidence")
            msg, a_red = policy.redact_text(
                f"Review required for {requirement_id}: {kind}",
                classification,
            )
            redaction_applied = redaction_applied or a_red
            action = ReviewerActionProjection(
                action_id=self._new_id("action"),
                kind=kind if len(kind) <= 64 else "review_evidence",
                message=msg or REDACTION_TOKEN,
                priority=20,
                source_links=(link,),
                requirement_id=requirement_id,
                reason_codes=reason_codes or ("review_required",),
                redacted=a_red,
                classification=classification,
            )
            row_action = action
            actions.append(action)
            stmts.append(
                GapStatement(
                    statement_id=self._new_id("stmt"),
                    kind=StatementKind.REVIEWER_ACTION,
                    summary=f"Reviewer action for {requirement_id}: {action.kind}",
                    status=GapStatus.UNKNOWN,
                    source_links=(link,),
                    is_unknown=True,
                    is_prominent_unknown=True,
                    classification=classification,
                    redacted=a_red,
                    detail_text=action.message,
                    reason_codes=tuple(action.reason_codes),
                    related_ids=(requirement_id, action.action_id),
                )
            )

        affected = tuple(str(x) for x in (raw.get("affected_claims") or ()))
        row = RequirementGapRow(
            row_id=self._new_id("row"),
            requirement_id=requirement_id,
            requirement_type=req_type,
            status=status,
            gap_status=gap_status,
            mandatory=mandatory,
            authority_ids=tuple(authority_ids),
            evidence_span_ids=evidence,
            counter_evidence_span_ids=counter,
            uncertainty=unc_text or uncertainty,
            source_links=(link,),
            statements=tuple(stmts),
            classification=classification,
            assessment_id=assessment_id,
            reviewer_action=row_action,
            affected_claims=affected,
            reason_codes=reason_codes,
            labels={
                str(k): str(v)
                for k, v in (raw.get("labels") or {}).items()
            }
            if isinstance(raw.get("labels"), Mapping)
            else {},
        )
        return row, stmts, actions, redaction_applied

    def _row_from_requirement_section(
        self,
        section: BundleSectionRef,
        *,
        policy: OutputRedactionPolicy,
        provenance_by_subject: Mapping[str, ProvenanceLink],
    ) -> tuple[RequirementGapRow, list[GapStatement], bool]:
        del policy
        link = self._source_from_section(
            section, role="requirement", provenance_by_subject=provenance_by_subject
        )
        status = GapStatus.UNKNOWN
        stmts = [
            GapStatement(
                statement_id=self._new_id("stmt"),
                kind=StatementKind.REQUIREMENT,
                summary=(
                    f"{UNKNOWN_BANNER}: requirement {section.record_id} bound "
                    "without assessment payload"
                ),
                status=status,
                source_links=(link,),
                is_unknown=True,
                is_prominent_unknown=True,
                classification=section.classification,
                redacted=False,
                reason_codes=("assessment_payload_absent",),
                related_ids=(section.record_id, section.section_id),
            ),
            GapStatement(
                statement_id=self._new_id("stmt"),
                kind=StatementKind.GAP,
                summary=f"Gap status for {section.record_id}: unknown",
                status=GapStatus.UNKNOWN,
                source_links=(link,),
                is_unknown=True,
                is_prominent_unknown=True,
                classification=section.classification,
                redacted=False,
                related_ids=(section.record_id,),
            ),
        ]
        if section.authority_ids:
            stmts.append(
                GapStatement(
                    statement_id=self._new_id("stmt"),
                    kind=StatementKind.AUTHORITY,
                    summary=(
                        f"Authority for {section.record_id}: "
                        f"{', '.join(section.authority_ids[:8])}"
                    ),
                    status=GapStatus.SATISFIED,
                    source_links=(
                        SourceLink(
                            link_id=self._new_id("src"),
                            role="authority",
                            authority_ids=tuple(section.authority_ids),
                            section_ids=(section.section_id,),
                            record_ids=(section.record_id,),
                        ),
                    ),
                    is_unknown=False,
                    is_prominent_unknown=False,
                    classification=section.classification,
                    redacted=False,
                    related_ids=tuple(section.authority_ids),
                )
            )
        req_type = (
            section.labels.get("requirement_type")
            if section.labels
            else None
        ) or "unknown"
        row = RequirementGapRow(
            row_id=self._new_id("row"),
            requirement_id=section.record_id,
            requirement_type=req_type,
            status=status,
            gap_status=GapStatus.UNKNOWN,
            mandatory=True,
            authority_ids=tuple(section.authority_ids),
            evidence_span_ids=(),
            counter_evidence_span_ids=(),
            uncertainty="assessment payload absent — fail closed to unknown",
            source_links=(link,),
            statements=tuple(stmts),
            classification=section.classification,
            assessment_id=None,
            reviewer_action=None,
            labels=dict(section.labels),
        )
        return row, stmts, False

    def _row_from_assessment_section(
        self,
        section: BundleSectionRef,
        *,
        policy: OutputRedactionPolicy,
        provenance_by_subject: Mapping[str, ProvenanceLink],
    ) -> tuple[RequirementGapRow, list[GapStatement], bool]:
        del policy
        link = self._source_from_section(
            section, role="assessment", provenance_by_subject=provenance_by_subject
        )
        status_label = (
            section.labels.get("status") if section.labels else None
        ) or "unknown"
        status = _status_from_raw(status_label)
        is_unk = status is GapStatus.UNKNOWN
        stmts = [
            GapStatement(
                statement_id=self._new_id("stmt"),
                kind=StatementKind.STATUS,
                summary=(
                    f"Assessment section {section.record_id} status={status.value}"
                ),
                status=status,
                source_links=(link,),
                is_unknown=is_unk,
                is_prominent_unknown=is_unk,
                classification=section.classification,
                redacted=False,
                related_ids=(section.record_id, section.section_id),
            )
        ]
        row = RequirementGapRow(
            row_id=self._new_id("row"),
            requirement_id=section.record_id,
            requirement_type=(
                (section.labels.get("requirement_type") if section.labels else None)
                or "unknown"
            ),
            status=status,
            gap_status=status if status is not GapStatus.UNSATISFIED else GapStatus.GAP,
            mandatory=True,
            authority_ids=tuple(section.authority_ids),
            evidence_span_ids=(),
            counter_evidence_span_ids=(),
            uncertainty=(
                "assessment section projected without full payload"
                if is_unk
                else "status from section labels"
            ),
            source_links=(link,),
            statements=tuple(stmts),
            classification=section.classification,
            assessment_id=section.record_id,
            labels=dict(section.labels),
        )
        return row, stmts, False

    def _row_from_requirement_map(
        self,
        raw: Mapping[str, Any],
        *,
        policy: OutputRedactionPolicy,
        provenance_by_subject: Mapping[str, ProvenanceLink],
        bundle: UsptoAnalysisBundle,
    ) -> tuple[RequirementGapRow, list[GapStatement], bool]:
        requirement_id = _identifier(
            str(raw.get("requirement_id") or "req:unknown"), "requirement_id"
        )
        classification = _coerce_classification(
            raw.get("classification", bundle.classification)
        )
        prov = provenance_by_subject.get(requirement_id)
        link = SourceLink(
            link_id=self._new_id("src"),
            role="requirement",
            artifact_ids=tuple(prov.artifact_ids) if prov else (),
            authority_ids=tuple(
                str(x)
                for x in (
                    raw.get("legal_citations")
                    or raw.get("authority_ids")
                    or (prov.authority_ids if prov else ())
                    or ()
                )
            ),
            span_ids=tuple(
                x
                for x in (
                    [str(raw["source_span_id"])] if raw.get("source_span_id") else []
                )
            ),
            record_ids=(requirement_id,),
        )
        detail, redacted = policy.redact_text(
            str(raw.get("explanation") or raw.get("detail_text") or "")
            or None,
            classification,
        )
        stmts = [
            GapStatement(
                statement_id=self._new_id("stmt"),
                kind=StatementKind.REQUIREMENT,
                summary=(
                    f"{UNKNOWN_BANNER}: requirement {requirement_id} lacks assessment"
                ),
                status=GapStatus.UNKNOWN,
                source_links=(link,),
                is_unknown=True,
                is_prominent_unknown=True,
                classification=classification,
                redacted=redacted,
                detail_text=detail,
                reason_codes=("missing_assessment",),
                related_ids=(requirement_id,),
            )
        ]
        row = RequirementGapRow(
            row_id=self._new_id("row"),
            requirement_id=requirement_id,
            requirement_type=str(raw.get("requirement_type") or "unknown"),
            status=GapStatus.UNKNOWN,
            gap_status=GapStatus.UNKNOWN,
            mandatory=True,
            authority_ids=tuple(link.authority_ids),
            evidence_span_ids=(),
            counter_evidence_span_ids=(),
            uncertainty="no assessment bound — fail closed to unknown",
            source_links=(link,),
            statements=tuple(stmts),
            classification=classification,
            affected_claims=tuple(str(x) for x in (raw.get("affected_claims") or ())),
        )
        return row, stmts, redacted

    def _candidate_from_map(
        self,
        raw: Mapping[str, Any],
        *,
        policy: OutputRedactionPolicy,
        provenance_by_subject: Mapping[str, ProvenanceLink],
        bundle: UsptoAnalysisBundle,
    ) -> tuple[CandidateDateProjection, GapStatement, bool]:
        candidate_id = _identifier(
            str(raw.get("candidate_id") or raw.get("deadline_id") or "cand:unknown"),
            "candidate_id",
        )
        classification = _coerce_classification(
            raw.get("classification", bundle.classification)
        )
        status = _status_from_raw(raw.get("status") or "unknown")
        uncertainty = str(
            raw.get("uncertainty_summary")
            or raw.get("uncertainty")
            or "unknown"
        )
        uncertainty_kinds = tuple(
            str(x) for x in (raw.get("uncertainty_kinds") or ())
        )
        assumptions_raw = raw.get("assumptions") or {}
        assumptions = {
            str(k): str(v)
            for k, v in (
                assumptions_raw.items()
                if isinstance(assumptions_raw, Mapping)
                else {}
            )
        }
        span_ids = tuple(
            str(x)
            for x in (
                raw.get("source_spans")
                or raw.get("span_ids")
                or ()
            )
            if not isinstance(x, Mapping)
        )
        # source_spans may be objects
        if not span_ids and isinstance(raw.get("source_spans"), Sequence):
            for item in raw.get("source_spans") or ():
                if isinstance(item, Mapping) and item.get("span_id"):
                    span_ids = span_ids + (str(item["span_id"]),)
                elif isinstance(item, str):
                    span_ids = span_ids + (item,)
        prov = provenance_by_subject.get(candidate_id)
        link = SourceLink(
            link_id=self._new_id("src"),
            role="candidate_date",
            artifact_ids=tuple(prov.artifact_ids) if prov else (),
            authority_ids=tuple(prov.authority_ids) if prov else (),
            span_ids=span_ids or (tuple(prov.span_ids) if prov else ()),
            record_ids=(candidate_id,),
        )
        unc_text, redacted = policy.redact_text(uncertainty, classification)
        q_raw = raw.get("human_review_question")
        q_text, q_red = policy.redact_text(
            str(q_raw) if q_raw is not None else None, classification
        )
        redacted = redacted or q_red
        is_unknown = status is GapStatus.UNKNOWN or bool(uncertainty_kinds)
        cand = CandidateDateProjection(
            candidate_id=candidate_id,
            status=status,
            candidate_utc=(
                str(raw["candidate_utc"])
                if raw.get("candidate_utc")
                else (
                    str(raw["candidate_date"])
                    if raw.get("candidate_date")
                    else None
                )
            ),
            uncertainty_summary=unc_text or "unknown",
            uncertainty_kinds=uncertainty_kinds,
            assumptions=assumptions,
            source_links=(link,),
            is_unknown=is_unknown,
            is_review_only=bool(raw.get("is_review_only", True)),
            human_review_question=q_text,
            classification=classification,
            redacted=redacted,
            rule_chain=tuple(str(x) for x in (raw.get("rule_chain") or ())),
            labels={
                str(k): str(v)
                for k, v in (raw.get("labels") or {}).items()
            }
            if isinstance(raw.get("labels"), Mapping)
            else {},
        )
        stmt = GapStatement(
            statement_id=self._new_id("stmt"),
            kind=StatementKind.CANDIDATE_DATE,
            summary=(
                f"{'UNKNOWN: ' if is_unknown else ''}"
                f"Candidate date {candidate_id}"
                f"{' @ ' + cand.candidate_utc if cand.candidate_utc else ''}"
                f" — {unc_text}"
            ),
            status=status,
            source_links=(link,),
            is_unknown=is_unknown,
            is_prominent_unknown=is_unknown,
            classification=classification,
            redacted=redacted,
            detail_text=q_text,
            reason_codes=uncertainty_kinds,
            related_ids=(candidate_id,),
        )
        return cand, stmt, redacted

    def _candidate_from_section(
        self,
        section: BundleSectionRef,
        *,
        policy: OutputRedactionPolicy,
        provenance_by_subject: Mapping[str, ProvenanceLink],
    ) -> tuple[CandidateDateProjection, GapStatement, bool]:
        link = self._source_from_section(
            section,
            role="candidate_date",
            provenance_by_subject=provenance_by_subject,
        )
        uncertainty = (
            section.labels.get("uncertainty_summary")
            if section.labels
            else None
        ) or "unknown — candidate date section without full payload"
        unc_text, redacted = policy.redact_text(uncertainty, section.classification)
        cand = CandidateDateProjection(
            candidate_id=section.record_id,
            status=GapStatus.UNKNOWN,
            candidate_utc=(
                section.labels.get("candidate_utc") if section.labels else None
            ),
            uncertainty_summary=unc_text or "unknown",
            uncertainty_kinds=("section_projection",),
            assumptions={},
            source_links=(link,),
            is_unknown=True,
            is_review_only=True,
            human_review_question=(
                section.labels.get("human_review_question")
                if section.labels
                else None
            ),
            classification=section.classification,
            redacted=redacted,
            labels=dict(section.labels),
        )
        stmt = GapStatement(
            statement_id=self._new_id("stmt"),
            kind=StatementKind.CANDIDATE_DATE,
            summary=(
                f"{UNKNOWN_BANNER}: candidate date {section.record_id} — {unc_text}"
            ),
            status=GapStatus.UNKNOWN,
            source_links=(link,),
            is_unknown=True,
            is_prominent_unknown=True,
            classification=section.classification,
            redacted=redacted,
            related_ids=(section.record_id, section.section_id),
        )
        return cand, stmt, redacted

    def _action_from_map(
        self,
        raw: Mapping[str, Any],
        *,
        policy: OutputRedactionPolicy,
        classification: DisclosureClassification,
        bundle: UsptoAnalysisBundle,
        default_requirement_id: str | None = None,
    ) -> tuple[ReviewerActionProjection, GapStatement, bool]:
        del bundle
        action_id = _identifier(
            str(raw.get("action_id") or self._new_id("action")), "action_id"
        )
        kind = str(raw.get("kind") or "review_package")
        cls = _coerce_classification(raw.get("classification", classification))
        msg_raw = str(raw.get("message") or "review_required")
        msg, redacted = policy.redact_text(msg_raw, cls)
        req_id = raw.get("requirement_id") or default_requirement_id
        link = SourceLink(
            link_id=self._new_id("src"),
            role="reviewer_action",
            record_ids=tuple(
                x for x in (action_id, req_id) if x
            ),
        )
        action = ReviewerActionProjection(
            action_id=action_id,
            kind=kind,
            message=msg or REDACTION_TOKEN,
            priority=int(raw.get("priority") or 0),
            source_links=(link,),
            requirement_id=(
                _optional_identifier(req_id, "requirement_id") if req_id else None
            ),
            reason_codes=tuple(str(x) for x in (raw.get("reason_codes") or ())),
            redacted=redacted,
            classification=cls,
            labels={
                str(k): str(v)
                for k, v in (raw.get("labels") or {}).items()
            }
            if isinstance(raw.get("labels"), Mapping)
            else {},
        )
        stmt = GapStatement(
            statement_id=self._new_id("stmt"),
            kind=StatementKind.REVIEWER_ACTION,
            summary=f"Reviewer action {action.kind} ({action.action_id})",
            status=GapStatus.UNKNOWN,
            source_links=(link,),
            is_unknown=True,
            is_prominent_unknown=True,
            classification=cls,
            redacted=redacted,
            detail_text=action.message,
            reason_codes=tuple(action.reason_codes),
            related_ids=tuple(
                x for x in (action.action_id, action.requirement_id) if x
            ),
        )
        return action, stmt, redacted

    def _render_markdown(
        self,
        *,
        label: GapReportLabel,
        matter_summary: MatterSummary,
        inventory: Sequence[ArtifactInventoryItem],
        requirement_rows: Sequence[RequirementGapRow],
        candidate_dates: Sequence[CandidateDateProjection],
        reviewer_actions: Sequence[ReviewerActionProjection],
        unknowns: Sequence[GapStatement],
        warnings: Sequence[str],
        mandatory_review_remaining: bool,
        unknown_count: int,
        gap_count: int,
        classification: DisclosureClassification,
        redaction_applied: bool,
        policy: OutputRedactionPolicy,
    ) -> str:
        del policy
        lines: list[str] = [
            "# Requirement / Evidence Gap Report",
            "",
            f"**Label:** `{label.value}`",
            f"**Mandatory review remaining:** `{mandatory_review_remaining}`",
            f"**Unknowns:** `{unknown_count}`  |  **Gaps:** `{gap_count}`",
            f"**Classification:** `{classification.value}`",
            f"**Redaction applied:** `{redaction_applied}`",
            "",
            f"_{GAP_REPORT_DISCLAIMER}_",
            "",
            "## Matter summary",
            "",
            f"- Matter: `{matter_summary.matter_id or 'n/a'}`",
            f"- Bundle: `{matter_summary.bundle_id}`",
            f"- Bundle digest: `{matter_summary.bundle_digest}`",
            f"- Disposition: `{matter_summary.disposition}`",
            f"- Review state: `{matter_summary.review_state.value}`",
            f"- Input artifacts: {len(matter_summary.input_artifact_ids)}",
            f"- Validation receipts: {len(matter_summary.validation_receipt_ids)}",
            f"- Unsupported checks: {len(matter_summary.unsupported_checks)}",
            "",
        ]
        if unknowns:
            lines.extend(
                [
                    f"## {UNKNOWN_BANNER} (prominent)",
                    "",
                ]
            )
            for u in unknowns:
                lines.append(
                    f"- **{UNKNOWN_BANNER}** `{u.statement_id}`: {u.summary}"
                )
                for link in u.source_links:
                    lines.append(
                        f"  - sources: artifacts={list(link.artifact_ids)} "
                        f"authority={list(link.authority_ids)} "
                        f"spans={list(link.span_ids)} "
                        f"records={list(link.record_ids)}"
                    )
            lines.append("")

        lines.extend(["## Artifact / receipt inventory", ""])
        if not inventory:
            lines.append("- _(empty inventory)_")
        for item in inventory:
            lines.append(
                f"- `{item.kind}` id=`{item.item_id}` "
                f"artifact=`{item.artifact_id or 'n/a'}` "
                f"receipt=`{item.receipt_id or 'n/a'}` "
                f"digest=`{(item.content_digest or 'n/a')[:16]}`"
            )
        lines.append("")

        lines.extend(["## Requirement / evidence matrix", ""])
        if not requirement_rows:
            lines.append(
                f"- **{UNKNOWN_BANNER}**: no requirement rows projected"
            )
        for row in requirement_rows:
            marker = f"**{UNKNOWN_BANNER}** " if row.is_unknown else ""
            lines.append(
                f"### {marker}`{row.requirement_id}` "
                f"({row.requirement_type}) — status=`{row.status.value}` "
                f"gap=`{row.gap_status.value}` mandatory=`{row.mandatory}`"
            )
            lines.append(f"- Uncertainty: {row.uncertainty}")
            lines.append(f"- Authority: {list(row.authority_ids) or '_(none)_'}")
            lines.append(
                f"- Evidence spans: {list(row.evidence_span_ids) or '_(none)_'}"
            )
            lines.append(
                f"- Counter-evidence spans: "
                f"{list(row.counter_evidence_span_ids) or '_(none)_'}"
            )
            for link in row.source_links:
                lines.append(
                    f"- Source link `{link.link_id}` role=`{link.role}` "
                    f"artifacts={list(link.artifact_ids)} "
                    f"authority={list(link.authority_ids)} "
                    f"spans={list(link.span_ids)}"
                )
            if row.reviewer_action:
                lines.append(
                    f"- Reviewer action: `{row.reviewer_action.kind}` "
                    f"— {row.reviewer_action.message}"
                )
            lines.append("")

        lines.extend(["## Candidate dates (review-only)", ""])
        if not candidate_dates:
            lines.append("- _(no candidate dates)_")
        for cand in candidate_dates:
            marker = f"**{UNKNOWN_BANNER}** " if cand.is_unknown else ""
            lines.append(
                f"- {marker}`{cand.candidate_id}` utc=`{cand.candidate_utc or 'n/a'}` "
                f"status=`{cand.status.value}` — {cand.uncertainty_summary}"
            )
            for link in cand.source_links:
                lines.append(
                    f"  - sources: artifacts={list(link.artifact_ids)} "
                    f"spans={list(link.span_ids)}"
                )
        lines.append("")

        lines.extend(["## Reviewer actions", ""])
        if not reviewer_actions:
            lines.append("- _(none)_")
        for action in reviewer_actions:
            lines.append(
                f"- `{action.kind}` priority={action.priority} "
                f"req=`{action.requirement_id or 'package'}` — {action.message}"
            )
            for link in action.source_links:
                lines.append(
                    f"  - sources: records={list(link.record_ids)}"
                )
        lines.append("")

        if warnings:
            lines.extend(["## Warnings", ""])
            for w in warnings:
                lines.append(f"- {w}")
            lines.append("")

        lines.extend(
            [
                "---",
                f"Label `{label.value}` | "
                f"mandatory_review_remaining=`{mandatory_review_remaining}`",
            ]
        )
        # Safety: never emit all_clear wording when review remains.
        if mandatory_review_remaining:
            body = "\n".join(lines)
            # Strip accidental all-clear phrasing from human form.
            body = body.replace("all clear", "review required")
            body = body.replace("All Clear", "Review Required")
            body = body.replace("ALL CLEAR", "REVIEW REQUIRED")
            return body
        return "\n".join(lines)

    def _render_markdown_redacted(
        self,
        *,
        label: GapReportLabel,
        matter_summary: MatterSummary,
        inventory: Sequence[ArtifactInventoryItem],
        requirement_rows: Sequence[RequirementGapRow],
        candidate_dates: Sequence[CandidateDateProjection],
        reviewer_actions: Sequence[ReviewerActionProjection],
        unknowns: Sequence[GapStatement],
        mandatory_review_remaining: bool,
        unknown_count: int,
        gap_count: int,
        classification: DisclosureClassification,
        policy: OutputRedactionPolicy,
    ) -> str:
        token = policy.redaction_token
        lines = [
            "# Requirement / Evidence Gap Report (redacted)",
            "",
            f"**Label:** `{label.value}`",
            f"**Mandatory review remaining:** `{mandatory_review_remaining}`",
            f"**Unknowns:** `{unknown_count}`  |  **Gaps:** `{gap_count}`",
            f"**Classification:** `{classification.value}`",
            f"**Redaction:** `{token}`",
            "",
            f"_{GAP_REPORT_DISCLAIMER}_",
            "",
            "## Matter summary",
            f"- Matter: `{matter_summary.matter_id or 'n/a'}`",
            f"- Bundle: `{matter_summary.bundle_id}`",
            f"- Bundle digest: `{matter_summary.bundle_digest}`",
            f"- Disposition: `{matter_summary.disposition}`",
            f"- Review state: `{matter_summary.review_state.value}`",
            "",
            f"## {UNKNOWN_BANNER} (prominent)",
        ]
        for u in unknowns:
            lines.append(
                f"- **{UNKNOWN_BANNER}** `{u.statement_id}` kind=`{u.kind.value}` "
                f"status=`{u.status.value}` summary=`{token if u.redacted else u.summary}`"
            )
            for link in u.source_links:
                lines.append(
                    f"  - sources: artifacts={list(link.artifact_ids)} "
                    f"authority={list(link.authority_ids)} "
                    f"spans={list(link.span_ids)} records={list(link.record_ids)}"
                )
        lines.extend(["", "## Inventory"])
        for item in inventory:
            lines.append(
                f"- `{item.kind}` `{item.item_id}` artifact=`{item.artifact_id}` "
                f"receipt=`{item.receipt_id}`"
            )
        lines.extend(["", "## Requirement matrix"])
        for row in requirement_rows:
            lines.append(
                f"- `{row.requirement_id}` status=`{row.status.value}` "
                f"gap=`{row.gap_status.value}` evidence={list(row.evidence_span_ids)} "
                f"counter={list(row.counter_evidence_span_ids)} "
                f"authority={list(row.authority_ids)}"
            )
            for link in row.source_links:
                lines.append(
                    f"  - source `{link.link_id}` role=`{link.role}` "
                    f"artifacts={list(link.artifact_ids)} spans={list(link.span_ids)}"
                )
        lines.extend(["", "## Candidate dates"])
        for cand in candidate_dates:
            lines.append(
                f"- `{cand.candidate_id}` status=`{cand.status.value}` "
                f"utc=`{cand.candidate_utc}` uncertainty=`{token if cand.redacted else cand.uncertainty_summary}`"
            )
        lines.extend(["", "## Reviewer actions"])
        for action in reviewer_actions:
            lines.append(
                f"- `{action.kind}` `{action.action_id}` "
                f"message=`{token if action.redacted else action.message}`"
            )
        if mandatory_review_remaining:
            lines.extend(
                [
                    "",
                    "---",
                    "Mandatory human review remains — not all_clear.",
                ]
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def render_gap_report(
    bundle: UsptoAnalysisBundle,
    *,
    assessments: Sequence[Any] = (),
    candidate_dates: Sequence[Any] = (),
    reviewer_actions: Sequence[Any] = (),
    requirements: Sequence[Any] = (),
    output_policy: OutputRedactionPolicy | None = None,
    labels: Mapping[str, str] | None = None,
    matter_id: str | None = None,
    analysis_id: str | None = None,
    id_factory: Callable[[], str] | None = None,
) -> RequirementEvidenceGapReport:
    """One-shot helper to render a gap report from an analysis bundle."""
    renderer = GapReportRenderer(
        id_factory=id_factory,
        output_policy=output_policy,
    )
    return renderer.render(
        GapReportInput(
            analysis_bundle=bundle,
            assessments=assessments,
            candidate_dates=candidate_dates,
            reviewer_actions=reviewer_actions,
            requirements=requirements,
            output_policy=output_policy or DEFAULT_OUTPUT_POLICY,
            labels=labels or {},
            matter_id=matter_id,
            analysis_id=analysis_id,
        )
    )


def verify_report_bundle_binding(
    report: RequirementEvidenceGapReport,
    bundle: UsptoAnalysisBundle,
) -> bool:
    """Return True when *report* round-trips to the same *bundle* binding."""
    if not isinstance(report, RequirementEvidenceGapReport):
        raise TypeError("report must be RequirementEvidenceGapReport")
    if not isinstance(bundle, UsptoAnalysisBundle):
        raise TypeError("bundle must be UsptoAnalysisBundle")
    if not report.binds_bundle(bundle):
        return False
    # Round-trip the report and confirm binding fields survive.
    revived = RequirementEvidenceGapReport.from_dict(report.to_dict())
    return (
        revived.source_bundle_id == bundle.bundle_id
        and revived.source_bundle_digest == bundle.bundle_digest
        and revived.source_bundle_id == report.source_bundle_id
        and revived.source_bundle_digest == report.source_bundle_digest
    )


def report_round_trip_equal(
    report: RequirementEvidenceGapReport,
) -> bool:
    """True when ``from_dict(to_dict(report))`` preserves the canonical payload."""
    revived = RequirementEvidenceGapReport.from_dict(report.to_dict())
    return revived.to_canonical_json() == report.to_canonical_json()


__all__ = [
    "DEFAULT_OUTPUT_POLICY",
    "GAP_REPORT_DISCLAIMER",
    "GAP_REPORT_INTERFACE",
    "GAP_REPORT_RULESET_VERSION",
    "GAP_REPORT_SCHEMA_VERSION",
    "OUTPUT_KIND_REQUIREMENT_EVIDENCE_GAP_REPORT",
    "PARSER_VERSION",
    "REDACTION_TOKEN",
    "UNKNOWN_BANNER",
    "ArtifactInventoryItem",
    "CandidateDateProjection",
    "GapReportError",
    "GapReportInput",
    "GapReportLabel",
    "GapReportRenderer",
    "GapStatement",
    "GapStatus",
    "MatterSummary",
    "OutputPolicyMode",
    "OutputRedactionPolicy",
    "RequirementEvidenceGapReport",
    "RequirementGapRow",
    "ReviewerActionProjection",
    "SourceLink",
    "StatementKind",
    "render_gap_report",
    "report_round_trip_equal",
    "sha256_hex",
    "verify_report_bundle_binding",
]
