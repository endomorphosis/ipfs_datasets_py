"""Parse USPTO submissions, amendments, metadata, and receipts (PATLAW-033).

Deterministically extracts claims, amendment instructions, remarks,
declarations/forms, fee and signature *presence*, attachments, document
descriptions, application metadata, acknowledgement identifiers, and payment
receipt evidence.

Design constraints (fail-closed):

* Original DOCX remains authoritative when paired with a USPTO-converted PDF.
* Every extracted fact points at an exact artifact version and evidence span.
* Signature *presence* is recorded; reusable signing material is never retained.
* Missing/mismatched metadata or receipts, and DOCX/PDF differences, are
  explicit issues — never silently ignored.

This module owns submission/receipt semantics only. It does not compile
government requirements, compliance aggregation, or office-action parsing.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    AuthorityRelation,
    DisclosureClassification,
    ExtractedSpan,
    ExtractionOrigin,
    ReviewState,
    SubmissionFact,
    canonical_json,
    most_restrictive_classification,
    requires_quarantine,
)

SUBMISSION_PROCESSOR_SCHEMA_VERSION: Final = "uspto.submission-processor.v1"
SUBMISSION_PROCESSOR_INTERFACE: Final = "UsptoSubmissionProcessor@1"
PARSER_VERSION: Final = "patlaw-033.submission.v1"

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SubmissionDisposition(str, Enum):
    """Pipeline disposition after submission semantic extraction."""

    EXTRACTED = "extracted"
    REVIEW = "review"
    QUARANTINE = "quarantine"
    REJECTED = "rejected"


class ArtifactRole(str, Enum):
    """Role of an artifact inside a submission package."""

    AUTHORITATIVE_DOCX = "authoritative_docx"
    USPTO_CONVERTED_PDF = "uspto_converted_pdf"
    SUBMISSION = "submission"
    AMENDMENT = "amendment"
    REMARKS = "remarks"
    DECLARATION = "declaration"
    FORM = "form"
    ACKNOWLEDGEMENT_RECEIPT = "acknowledgement_receipt"
    PAYMENT_RECEIPT = "payment_receipt"
    ATTACHMENT = "attachment"
    CLAIM_SET = "claim_set"
    OTHER = "other"
    UNKNOWN = "unknown"


class SubmissionFactType(str, Enum):
    """Typed facts emitted by the submission processor."""

    CLAIM = "claim"
    CURRENT_CLAIM = "current_claim"
    AMENDMENT_INSTRUCTION = "amendment_instruction"
    REMARKS = "remarks"
    DECLARATION = "declaration"
    FORM = "form"
    FEE_PRESENCE = "fee_presence"
    SIGNATURE_PRESENCE = "signature_presence"
    ATTACHMENT = "attachment"
    DOCUMENT_DESCRIPTION = "document_description"
    APPLICATION_METADATA = "application_metadata"
    ACKNOWLEDGEMENT_IDENTIFIER = "acknowledgement_identifier"
    PAYMENT_RECEIPT = "payment_receipt"
    VERSION_MARKER = "version_marker"
    UNSUPPORTED = "unsupported"


class FactExtractionStatus(str, Enum):
    """Per-fact extraction outcome (maps into SubmissionFact.extraction_status)."""

    OK = "ok"
    PARTIAL = "partial"
    MISSING = "missing"
    MISMATCHED = "mismatched"
    UNKNOWN = "unknown"
    REVIEW_REQUIRED = "review_required"


class SubmissionIssueKind(str, Enum):
    """Explicit package-level problems; never silent."""

    MISSING_METADATA = "missing_metadata"
    MISMATCHED_METADATA = "mismatched_metadata"
    MISSING_RECEIPT = "missing_receipt"
    MISMATCHED_RECEIPT = "mismatched_receipt"
    DOCX_PDF_DIFFERENCE = "docx_pdf_difference"
    MATTER_ID_MISMATCH = "matter_id_mismatch"
    DOCUMENT_DESCRIPTION_MISMATCH = "document_description_mismatch"
    SIGNATURE_MATERIAL_SUPPRESSED = "signature_material_suppressed"
    MISSING_CLAIM = "missing_claim"
    VERSION_CONFLICT = "version_conflict"
    AUTHORITY_DOCX_PREFERRED = "authority_docx_preferred"
    EMPTY_PACKAGE = "empty_package"
    MISSING_SPAN = "missing_span"
    MISSING_ARTIFACT = "missing_artifact"
    UNSUPPORTED_CONTENT = "unsupported_content"


class SubmissionReasonCode(str, Enum):
    CLAIMS_EXTRACTED = "claims_extracted"
    AMENDMENTS_EXTRACTED = "amendments_extracted"
    REMARKS_EXTRACTED = "remarks_extracted"
    DECLARATIONS_EXTRACTED = "declarations_extracted"
    FORMS_EXTRACTED = "forms_extracted"
    FEES_EXTRACTED = "fees_extracted"
    SIGNATURE_PRESENCE_ONLY = "signature_presence_only"
    ATTACHMENTS_EXTRACTED = "attachments_extracted"
    METADATA_EXTRACTED = "metadata_extracted"
    ACKNOWLEDGEMENT_EXTRACTED = "acknowledgement_extracted"
    PAYMENT_RECEIPT_EXTRACTED = "payment_receipt_extracted"
    CURRENT_CLAIMS_RECONSTRUCTED = "current_claims_reconstructed"
    DOCX_AUTHORITATIVE = "docx_authoritative"
    DOCX_PDF_DIFFERENCE = "docx_pdf_difference"
    MISSING_RECEIPT = "missing_receipt"
    MISMATCHED_METADATA = "mismatched_metadata"
    REVIEW_REQUIRED = "review_required"
    QUARANTINE_CLASSIFICATION = "quarantine_classification"
    EMPTY_INPUT = "empty_input"


class SignaturePresenceStatus(str, Enum):
    """Presence-only signature signal — never carries signing material."""

    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Validation helpers (local; mirrors contracts style)
# ---------------------------------------------------------------------------


class SubmissionProcessorError(ValueError):
    """Bounded semantic extraction failure with a stable machine-readable code."""

    def __init__(self, message: str, *, code: str = "submission_processor_error") -> None:
        super().__init__(message)
        self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _text_digest(text: str) -> str:
    return sha256_hex(text)


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


def _optional_sha256(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=64)
    if text is None:
        return None
    text = text.lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field} must be sha256 hex")
    return text


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int")
    if value < 0:
        raise ValueError(f"{field} must be >= 0")
    return value


def _optional_float_01(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be float or None")
    f = float(value)
    if f < 0.0 or f > 1.0:
        raise ValueError(f"{field} must be in [0, 1]")
    return f


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
    if isinstance(value, str):
        raise TypeError(f"{field} must be a sequence of str, not str")
    if not isinstance(value, Sequence):
        raise TypeError(f"{field} must be a sequence")
    out: list[str] = []
    for i, item in enumerate(value):
        if i >= max_items:
            break
        out.append(_require_str(item, f"{field}[{i}]", max_len=512))
    return tuple(out)


def _frozen_str_map(
    value: Any,
    field: str,
    *,
    max_items: int = 64,
    max_value_len: int = 1024,
) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    items: dict[str, str] = {}
    for i, (k, v) in enumerate(value.items()):
        if i >= max_items:
            break
        key = _require_str(k, f"{field}.key", max_len=128)
        if v is None:
            continue
        items[key] = _require_str(str(v), f"{field}[{key}]", max_len=max_value_len)
    return MappingProxyType(items)


# ---------------------------------------------------------------------------
# Input / intermediate records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClaimVersion:
    """A claim set at a named document version (as_filed, amendment, current…)."""

    version: str
    claims: Mapping[str, str]  # claim number -> claim text
    artifact_id: str | None = None
    source_span_ids: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "version", _require_str(self.version, "version", max_len=64)
        )
        if not isinstance(self.claims, Mapping):
            raise TypeError("claims must be a mapping")
        claims = {
            _require_str(str(k), "claim_number", max_len=32): _require_str(
                str(v), "claim_text", max_len=200_000
            )
            for k, v in self.claims.items()
        }
        object.__setattr__(self, "claims", MappingProxyType(claims))
        object.__setattr__(
            self, "artifact_id", _optional_identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "source_span_ids",
            _frozen_str_map(self.source_span_ids, "source_span_ids", max_items=256),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "claims": dict(self.claims),
            "source_span_ids": dict(self.source_span_ids),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClaimVersion":
        if not isinstance(value, Mapping):
            raise TypeError("ClaimVersion must be a mapping")
        return cls(
            version=value.get("version", "1"),
            claims=value.get("claims") or {},
            artifact_id=value.get("artifact_id"),
            source_span_ids=value.get("source_span_ids") or {},
        )


@dataclass(frozen=True, slots=True)
class SubmissionArtifactInput:
    """One artifact in a multi-document submission package.

    Prefer providing extraction-derived text and spans. Raw bytes are never
    stored on the result; only digests and span anchors.
    """

    artifact_id: str
    role: ArtifactRole
    classification: DisclosureClassification = DisclosureClassification.UNKNOWN
    content_sha256: str | None = None
    media_family: str | None = None
    full_text: str = ""
    spans: tuple[ExtractedSpan, ...] = ()
    filing_metadata: Mapping[str, str] = field(default_factory=dict)
    document_description: str | None = None
    matter_id: str | None = None
    application_number: str | None = None
    version: str = "1"
    receipt_fields: Mapping[str, str] = field(default_factory=dict)
    related_artifact_ids: tuple[str, ...] = ()
    authority_relation: AuthorityRelation = AuthorityRelation.UNKNOWN
    # Pre-declared differences from document extraction compare (DOCX vs PDF).
    differences: tuple[Mapping[str, Any], ...] = ()
    # Layout cues: e.g. signature_presence layout items (presence only).
    layout_cues: tuple[Mapping[str, str], ...] = ()
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self, "role", _coerce_enum(ArtifactRole, self.role, "role")
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self, "content_sha256", _optional_sha256(self.content_sha256, "content_sha256")
        )
        object.__setattr__(
            self,
            "media_family",
            _optional_str(self.media_family, "media_family", max_len=32),
        )
        if not isinstance(self.full_text, str):
            raise TypeError("full_text must be str")
        if len(self.full_text) > 2_000_000:
            raise ValueError("full_text exceeds max length")
        if not isinstance(self.spans, tuple):
            object.__setattr__(self, "spans", tuple(self.spans))
        object.__setattr__(
            self,
            "filing_metadata",
            _frozen_str_map(self.filing_metadata, "filing_metadata", max_items=64),
        )
        object.__setattr__(
            self,
            "document_description",
            _optional_str(self.document_description, "document_description", max_len=512),
        )
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self,
            "application_number",
            _optional_str(self.application_number, "application_number", max_len=64),
        )
        object.__setattr__(
            self, "version", _require_str(self.version, "version", max_len=64)
        )
        object.__setattr__(
            self,
            "receipt_fields",
            _frozen_str_map(self.receipt_fields, "receipt_fields", max_items=64),
        )
        object.__setattr__(
            self,
            "related_artifact_ids",
            _tuple_of_str(self.related_artifact_ids, "related_artifact_ids", max_items=64),
        )
        object.__setattr__(
            self,
            "authority_relation",
            _coerce_enum(
                AuthorityRelation, self.authority_relation, "authority_relation"
            ),
        )
        if not isinstance(self.differences, tuple):
            object.__setattr__(self, "differences", tuple(self.differences))
        if not isinstance(self.layout_cues, tuple):
            object.__setattr__(self, "layout_cues", tuple(self.layout_cues))
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_number": self.application_number,
            "artifact_id": self.artifact_id,
            "authority_relation": self.authority_relation.value,
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "differences": [dict(d) for d in self.differences],
            "document_description": self.document_description,
            "filing_metadata": dict(self.filing_metadata),
            "full_text": self.full_text,
            "labels": dict(self.labels),
            "layout_cues": [dict(c) for c in self.layout_cues],
            "matter_id": self.matter_id,
            "media_family": self.media_family,
            "receipt_fields": dict(self.receipt_fields),
            "related_artifact_ids": list(self.related_artifact_ids),
            "role": self.role.value,
            "spans": [s.to_dict() for s in self.spans],
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SubmissionArtifactInput":
        if not isinstance(value, Mapping):
            raise TypeError("SubmissionArtifactInput must be a mapping")
        spans_raw = value.get("spans") or ()
        spans = tuple(
            s if isinstance(s, ExtractedSpan) else ExtractedSpan.from_dict(s)
            for s in spans_raw
        )
        diffs = tuple(value.get("differences") or ())
        cues = tuple(value.get("layout_cues") or ())
        return cls(
            artifact_id=value.get("artifact_id", ""),
            role=value.get("role", ArtifactRole.UNKNOWN.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            content_sha256=value.get("content_sha256"),
            media_family=value.get("media_family"),
            full_text=value.get("full_text") or "",
            spans=spans,
            filing_metadata=value.get("filing_metadata") or {},
            document_description=value.get("document_description"),
            matter_id=value.get("matter_id"),
            application_number=value.get("application_number"),
            version=value.get("version") or "1",
            receipt_fields=value.get("receipt_fields") or {},
            related_artifact_ids=tuple(value.get("related_artifact_ids") or ()),
            authority_relation=value.get(
                "authority_relation", AuthorityRelation.UNKNOWN.value
            ),
            differences=diffs,
            layout_cues=cues,
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class SubmissionPackageInput:
    """Multi-artifact package: original DOCX, converted PDF, receipts, etc."""

    package_id: str
    artifacts: tuple[SubmissionArtifactInput, ...]
    matter_id: str | None = None
    expected_application_number: str | None = None
    claim_versions: tuple[ClaimVersion, ...] = ()
    require_ack_receipt: bool = True
    require_payment_receipt: bool = False
    classification: DisclosureClassification = DisclosureClassification.UNKNOWN
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "package_id", _identifier(self.package_id, "package_id")
        )
        if not isinstance(self.artifacts, tuple):
            object.__setattr__(self, "artifacts", tuple(self.artifacts))
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self,
            "expected_application_number",
            _optional_str(
                self.expected_application_number,
                "expected_application_number",
                max_len=64,
            ),
        )
        if not isinstance(self.claim_versions, tuple):
            object.__setattr__(self, "claim_versions", tuple(self.claim_versions))
        if not isinstance(self.require_ack_receipt, bool):
            raise TypeError("require_ack_receipt must be bool")
        if not isinstance(self.require_payment_receipt, bool):
            raise TypeError("require_payment_receipt must be bool")
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifacts": [a.to_dict() for a in self.artifacts],
            "claim_versions": [c.to_dict() for c in self.claim_versions],
            "classification": self.classification.value,
            "expected_application_number": self.expected_application_number,
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "package_id": self.package_id,
            "require_ack_receipt": self.require_ack_receipt,
            "require_payment_receipt": self.require_payment_receipt,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SubmissionPackageInput":
        if not isinstance(value, Mapping):
            raise TypeError("SubmissionPackageInput must be a mapping")
        arts = tuple(
            a
            if isinstance(a, SubmissionArtifactInput)
            else SubmissionArtifactInput.from_dict(a)
            for a in (value.get("artifacts") or ())
        )
        cvs = tuple(
            c if isinstance(c, ClaimVersion) else ClaimVersion.from_dict(c)
            for c in (value.get("claim_versions") or ())
        )
        return cls(
            package_id=value.get("package_id", ""),
            artifacts=arts,
            matter_id=value.get("matter_id"),
            expected_application_number=value.get("expected_application_number"),
            claim_versions=cvs,
            require_ack_receipt=bool(value.get("require_ack_receipt", True)),
            require_payment_receipt=bool(value.get("require_payment_receipt", False)),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            labels=value.get("labels") or {},
        )


# ---------------------------------------------------------------------------
# Output records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SubmissionIssue:
    """Explicit missing/mismatched/difference signal (never silent)."""

    schema_version: str
    issue_id: str
    kind: SubmissionIssueKind
    severity: str  # info | warning | error
    message_code: str
    artifact_ids: tuple[str, ...]
    related_span_ids: tuple[str, ...]
    detail: str | None
    classification: DisclosureClassification

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != SUBMISSION_PROCESSOR_SCHEMA_VERSION:
            raise ValueError(
                "SubmissionIssue.schema_version must be "
                f"{SUBMISSION_PROCESSOR_SCHEMA_VERSION}"
            )
        object.__setattr__(self, "issue_id", _identifier(self.issue_id, "issue_id"))
        object.__setattr__(
            self, "kind", _coerce_enum(SubmissionIssueKind, self.kind, "kind")
        )
        object.__setattr__(
            self, "severity", _require_str(self.severity, "severity", max_len=32)
        )
        object.__setattr__(
            self,
            "message_code",
            _require_str(self.message_code, "message_code", max_len=128),
        )
        object.__setattr__(
            self,
            "artifact_ids",
            _tuple_of_str(self.artifact_ids, "artifact_ids", max_items=64),
        )
        object.__setattr__(
            self,
            "related_span_ids",
            _tuple_of_str(self.related_span_ids, "related_span_ids", max_items=64),
        )
        object.__setattr__(
            self, "detail", _optional_str(self.detail, "detail", max_len=1024)
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_ids": list(self.artifact_ids),
            "classification": self.classification.value,
            "detail": self.detail,
            "issue_id": self.issue_id,
            "kind": self.kind.value,
            "message_code": self.message_code,
            "related_span_ids": list(self.related_span_ids),
            "schema_version": self.schema_version,
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SubmissionIssue":
        if not isinstance(value, Mapping):
            raise TypeError("SubmissionIssue must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", SUBMISSION_PROCESSOR_SCHEMA_VERSION
            ),
            issue_id=value.get("issue_id", ""),
            kind=value.get("kind", SubmissionIssueKind.UNSUPPORTED_CONTENT.value),
            severity=value.get("severity", "warning"),
            message_code=value.get("message_code", "issue"),
            artifact_ids=tuple(value.get("artifact_ids") or ()),
            related_span_ids=tuple(value.get("related_span_ids") or ()),
            detail=value.get("detail"),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
        )


@dataclass(frozen=True, slots=True)
class EnrichedSubmissionFact:
    """SubmissionFact plus provenance context retained only for analysis.

    Public projection strips digests that might reconstitute secret content;
    the contract :class:`SubmissionFact` already stores digests-only identity.
    """

    fact: SubmissionFact
    artifact_id: str
    value_digest: str
    # Safe display value for non-sensitive fields only (never signature material).
    display_value: str | None
    field_name: str | None
    page_index: int | None
    authority_relation: AuthorityRelation
    is_authoritative: bool
    signature_presence: SignaturePresenceStatus | None

    def __post_init__(self) -> None:
        if not isinstance(self.fact, SubmissionFact):
            raise TypeError("fact must be SubmissionFact")
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self, "value_digest", _require_str(self.value_digest, "value_digest", max_len=64)
        )
        if not _SHA256_RE.match(self.value_digest.lower()):
            raise ValueError("value_digest must be sha256 hex")
        object.__setattr__(self, "value_digest", self.value_digest.lower())
        object.__setattr__(
            self,
            "display_value",
            _optional_str(self.display_value, "display_value", max_len=512),
        )
        object.__setattr__(
            self, "field_name", _optional_str(self.field_name, "field_name", max_len=128)
        )
        if self.page_index is not None:
            object.__setattr__(
                self, "page_index", _nonneg_int(self.page_index, "page_index")
            )
        object.__setattr__(
            self,
            "authority_relation",
            _coerce_enum(
                AuthorityRelation, self.authority_relation, "authority_relation"
            ),
        )
        if not isinstance(self.is_authoritative, bool):
            raise TypeError("is_authoritative must be bool")
        if self.signature_presence is not None:
            object.__setattr__(
                self,
                "signature_presence",
                _coerce_enum(
                    SignaturePresenceStatus,
                    self.signature_presence,
                    "signature_presence",
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "authority_relation": self.authority_relation.value,
            "display_value": self.display_value,
            "fact": self.fact.to_dict(),
            "field_name": self.field_name,
            "is_authoritative": self.is_authoritative,
            "page_index": self.page_index,
            "signature_presence": (
                self.signature_presence.value if self.signature_presence else None
            ),
            "value_digest": self.value_digest,
        }

    def public_projection(self) -> dict[str, Any]:
        """Identifiers, digests, and presence flags — never body text or signatures."""
        return {
            "artifact_id": self.artifact_id,
            "authority_relation": self.authority_relation.value,
            "affected_claims": list(self.fact.affected_claims),
            "evidence_span_id": self.fact.evidence_span_id,
            "extraction_status": self.fact.extraction_status,
            "fact_id": self.fact.fact_id,
            "fact_type": self.fact.fact_type,
            "field_name": self.field_name,
            "is_authoritative": self.is_authoritative,
            "page_index": self.page_index,
            "signature_presence": (
                self.signature_presence.value if self.signature_presence else None
            ),
            "value_digest": self.value_digest,
            "version": self.fact.version,
            # display_value deliberately omitted — may hold claim text digests only
            # on internal to_dict; public projection never emits raw claim text.
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EnrichedSubmissionFact":
        if not isinstance(value, Mapping):
            raise TypeError("EnrichedSubmissionFact must be a mapping")
        fact_raw = value.get("fact") or {}
        fact = (
            fact_raw
            if isinstance(fact_raw, SubmissionFact)
            else SubmissionFact.from_dict(fact_raw)
        )
        return cls(
            fact=fact,
            artifact_id=value.get("artifact_id", ""),
            value_digest=value.get("value_digest", ""),
            display_value=value.get("display_value"),
            field_name=value.get("field_name"),
            page_index=value.get("page_index"),
            authority_relation=value.get(
                "authority_relation", AuthorityRelation.UNKNOWN.value
            ),
            is_authoritative=bool(value.get("is_authoritative", False)),
            signature_presence=value.get("signature_presence"),
        )


@dataclass(frozen=True, slots=True)
class SubmissionAnalysisResult:
    """Full semantic extraction outcome for a submission package."""

    schema_version: str
    analysis_id: str
    package_id: str
    disposition: SubmissionDisposition
    review_state: ReviewState
    classification: DisclosureClassification
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    facts: tuple[EnrichedSubmissionFact, ...]
    spans: tuple[ExtractedSpan, ...]
    issues: tuple[SubmissionIssue, ...]
    current_claims: Mapping[str, str]
    current_claim_span_ids: Mapping[str, str]
    claim_versions: tuple[ClaimVersion, ...]
    authoritative_artifact_ids: tuple[str, ...]
    input_artifact_ids: tuple[str, ...]
    signature_presence: SignaturePresenceStatus
    acknowledgement_ids: tuple[str, ...]
    payment_receipt_present: bool
    parser_versions: Mapping[str, str]
    labels: Mapping[str, str]
    matter_id: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != SUBMISSION_PROCESSOR_SCHEMA_VERSION:
            raise ValueError(
                "SubmissionAnalysisResult.schema_version must be "
                f"{SUBMISSION_PROCESSOR_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "analysis_id", _identifier(self.analysis_id, "analysis_id")
        )
        object.__setattr__(
            self, "package_id", _identifier(self.package_id, "package_id")
        )
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(SubmissionDisposition, self.disposition, "disposition"),
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
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=128),
        )
        object.__setattr__(
            self, "warnings", _tuple_of_str(self.warnings, "warnings", max_items=128)
        )
        if not isinstance(self.facts, tuple):
            object.__setattr__(self, "facts", tuple(self.facts))
        if not isinstance(self.spans, tuple):
            object.__setattr__(self, "spans", tuple(self.spans))
        if not isinstance(self.issues, tuple):
            object.__setattr__(self, "issues", tuple(self.issues))
        object.__setattr__(
            self,
            "current_claims",
            _frozen_str_map(
                self.current_claims, "current_claims", max_items=256, max_value_len=200_000
            ),
        )
        object.__setattr__(
            self,
            "current_claim_span_ids",
            _frozen_str_map(
                self.current_claim_span_ids, "current_claim_span_ids", max_items=256
            ),
        )
        if not isinstance(self.claim_versions, tuple):
            object.__setattr__(self, "claim_versions", tuple(self.claim_versions))
        object.__setattr__(
            self,
            "authoritative_artifact_ids",
            _tuple_of_str(
                self.authoritative_artifact_ids,
                "authoritative_artifact_ids",
                max_items=64,
            ),
        )
        object.__setattr__(
            self,
            "input_artifact_ids",
            _tuple_of_str(self.input_artifact_ids, "input_artifact_ids", max_items=128),
        )
        object.__setattr__(
            self,
            "signature_presence",
            _coerce_enum(
                SignaturePresenceStatus, self.signature_presence, "signature_presence"
            ),
        )
        object.__setattr__(
            self,
            "acknowledgement_ids",
            _tuple_of_str(
                self.acknowledgement_ids, "acknowledgement_ids", max_items=32
            ),
        )
        if not isinstance(self.payment_receipt_present, bool):
            raise TypeError("payment_receipt_present must be bool")
        object.__setattr__(
            self,
            "parser_versions",
            _frozen_str_map(self.parser_versions, "parser_versions", max_items=32),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        if requires_quarantine(self.classification) and self.review_state not in (
            ReviewState.REQUIRED,
            ReviewState.PENDING,
        ):
            object.__setattr__(self, "review_state", ReviewState.REQUIRED)

    @property
    def requires_review(self) -> bool:
        return self.disposition in (
            SubmissionDisposition.REVIEW,
            SubmissionDisposition.QUARANTINE,
            SubmissionDisposition.REJECTED,
        ) or self.review_state in (ReviewState.REQUIRED, ReviewState.PENDING)

    @property
    def contract_facts(self) -> tuple[SubmissionFact, ...]:
        return tuple(f.fact for f in self.facts)

    def span_by_id(self, span_id: str) -> ExtractedSpan | None:
        for span in self.spans:
            if span.span_id == span_id:
                return span
        return None

    def fact_by_id(self, fact_id: str) -> EnrichedSubmissionFact | None:
        for fact in self.facts:
            if fact.fact.fact_id == fact_id:
                return fact
        return None

    def facts_of_type(self, fact_type: SubmissionFactType | str) -> tuple[EnrichedSubmissionFact, ...]:
        ft = fact_type.value if isinstance(fact_type, SubmissionFactType) else str(fact_type)
        return tuple(f for f in self.facts if f.fact.fact_type == ft)

    def to_dict(self) -> dict[str, Any]:
        return {
            "acknowledgement_ids": list(self.acknowledgement_ids),
            "analysis_id": self.analysis_id,
            "authoritative_artifact_ids": list(self.authoritative_artifact_ids),
            "claim_versions": [c.to_dict() for c in self.claim_versions],
            "classification": self.classification.value,
            "current_claim_span_ids": dict(self.current_claim_span_ids),
            "current_claims": dict(self.current_claims),
            "disposition": self.disposition.value,
            "facts": [f.to_dict() for f in self.facts],
            "input_artifact_ids": list(self.input_artifact_ids),
            "issues": [i.to_dict() for i in self.issues],
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "package_id": self.package_id,
            "parser_versions": dict(self.parser_versions),
            "payment_receipt_present": self.payment_receipt_present,
            "reason_codes": list(self.reason_codes),
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "signature_presence": self.signature_presence.value,
            "spans": [s.to_dict() for s in self.spans],
            "warnings": list(self.warnings),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def public_projection(self) -> dict[str, Any]:
        """Safe projection: no claim body text, no signature material."""
        return {
            "acknowledgement_ids": list(self.acknowledgement_ids),
            "analysis_id": self.analysis_id,
            "authoritative_artifact_ids": list(self.authoritative_artifact_ids),
            "classification": self.classification.value,
            "current_claim_numbers": sorted(self.current_claims.keys(), key=_claim_sort_key),
            "current_claim_span_ids": dict(self.current_claim_span_ids),
            "disposition": self.disposition.value,
            "facts": [f.public_projection() for f in self.facts],
            "input_artifact_ids": list(self.input_artifact_ids),
            "issue_kinds": [i.kind.value for i in self.issues],
            "issues": [
                {
                    "artifact_ids": list(i.artifact_ids),
                    "issue_id": i.issue_id,
                    "kind": i.kind.value,
                    "message_code": i.message_code,
                    "severity": i.severity,
                }
                for i in self.issues
            ],
            "matter_id": self.matter_id,
            "package_id": self.package_id,
            "parser_versions": dict(self.parser_versions),
            "payment_receipt_present": self.payment_receipt_present,
            "reason_codes": list(self.reason_codes),
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "signature_presence": self.signature_presence.value,
            "span_ids": [s.span_id for s in self.spans],
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SubmissionAnalysisResult":
        if not isinstance(value, Mapping):
            raise TypeError("SubmissionAnalysisResult must be a mapping")
        facts = tuple(
            f if isinstance(f, EnrichedSubmissionFact) else EnrichedSubmissionFact.from_dict(f)
            for f in (value.get("facts") or ())
        )
        spans = tuple(
            s if isinstance(s, ExtractedSpan) else ExtractedSpan.from_dict(s)
            for s in (value.get("spans") or ())
        )
        issues = tuple(
            i if isinstance(i, SubmissionIssue) else SubmissionIssue.from_dict(i)
            for i in (value.get("issues") or ())
        )
        claim_versions = tuple(
            c if isinstance(c, ClaimVersion) else ClaimVersion.from_dict(c)
            for c in (value.get("claim_versions") or ())
        )
        return cls(
            schema_version=value.get(
                "schema_version", SUBMISSION_PROCESSOR_SCHEMA_VERSION
            ),
            analysis_id=value.get("analysis_id", ""),
            package_id=value.get("package_id", ""),
            disposition=value.get("disposition", SubmissionDisposition.REVIEW.value),
            review_state=value.get("review_state", ReviewState.PENDING.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            reason_codes=tuple(value.get("reason_codes") or ()),
            warnings=tuple(value.get("warnings") or ()),
            facts=facts,
            spans=spans,
            issues=issues,
            current_claims=value.get("current_claims") or {},
            current_claim_span_ids=value.get("current_claim_span_ids") or {},
            claim_versions=claim_versions,
            authoritative_artifact_ids=tuple(
                value.get("authoritative_artifact_ids") or ()
            ),
            input_artifact_ids=tuple(value.get("input_artifact_ids") or ()),
            signature_presence=value.get(
                "signature_presence", SignaturePresenceStatus.UNKNOWN.value
            ),
            acknowledgement_ids=tuple(value.get("acknowledgement_ids") or ()),
            payment_receipt_present=bool(value.get("payment_receipt_present", False)),
            parser_versions=value.get("parser_versions") or {},
            labels=value.get("labels") or {},
            matter_id=value.get("matter_id"),
        )


def _claim_sort_key(n: str) -> tuple[int, str]:
    try:
        return (int(n), n)
    except ValueError:
        return (10**9, n)


# ---------------------------------------------------------------------------
# Parsing patterns (deterministic)
# ---------------------------------------------------------------------------

_CLAIM_LINE_RE = re.compile(
    r"(?m)^\s*(?:Claim\s+)?(\d+)\s*\.\s+(.+?)(?=\n\s*(?:Claim\s+)?\d+\s*\.|\n\s*(?:REMARKS|AMENDMENTS?|CONCLUSION|WHAT IS CLAIMED|I claim)|\Z)",
    re.I | re.S,
)
_CLAIM_STATUS_RE = re.compile(
    r"(?m)^\s*(?:Claim\s+)?(\d+)\s*\(\s*(currently amended|original|new|canceled|cancelled|withdrawn|previously presented)\s*\)\s*:?\s*(.*?)(?=\n\s*(?:Claim\s+)?\d+\s*\(|\n\s*(?:REMARKS|AMENDMENTS?|CONCLUSION)|\Z)",
    re.I | re.S,
)
_AMENDMENT_INSTR_RE = re.compile(
    r"(?mi)^\s*(?:Please\s+)?(?:amend|cancel|add|withdraw|rewrite)\s+claim[s]?\s+([\d,\s\-and]+)\s*(?:as follows)?\s*:?\s*(.*?)(?=\n\s*(?:Please\s+)?(?:amend|cancel|add|withdraw|rewrite)\s+claim|\n\s*REMARKS|\n\s*Claim\s+\d+|\Z)",
    re.S,
)
_REMARKS_RE = re.compile(
    r"(?is)\bREMARKS\b\s*:?\s*(.*?)(?=\n\s*(?:CONCLUSION|CLAIMS?|AMENDMENTS?|WHAT IS CLAIMED|I claim|Respectfully submitted)|\Z)"
)
_DECLARATION_RE = re.compile(
    r"(?is)\b(?:I\s+hereby\s+declare|declaration\s+under\s+37\s*C\.?\s*F\.?\s*R\.?\s*1\.63|Inventor(?:'s)?\s+Declaration)\b(.{0,800})"
)
_FORM_RE = re.compile(
    r"\b(PTO/(?:SB|AIA|SB/\d+|[A-Z]{1,4})/\d{1,4}|Form\s+SB\d{1,3}|SB\d{2})\b",
    re.I,
)
_FEE_RE = re.compile(
    r"(?mi)(?:Fee\s*(?:Code|Item)?\s*[:#]?\s*([A-Z0-9\-]{2,12}).{0,40}?\$?\s*([\d,]+\.\d{2}))|(?:\$\s*([\d,]+\.\d{2}).{0,40}?Fee\s*(?:Code)?\s*[:#]?\s*([A-Z0-9\-]{2,12}))|(Basic\s+Filing|Search\s+Fee|Examination\s+Fee)\s*[|:]\s*\$?\s*([\d,]+(?:\.\d{2})?)"
)
_SIGNATURE_PRESENCE_RE = re.compile(
    r"(?mi)(?:\bElectronically\s+signed\b|\bSignature\s*:|\bRespectfully\s+submitted\b|/\s*s\s*/|☐\s*Signature|\[\s*X\s*\]\s*Signed)"
)
# Capture groups that look like reusable signing material — we suppress them.
_SIGNATURE_MATERIAL_RE = re.compile(
    r"(?mi)(?:/\s*s\s*/\s*([A-Za-z][A-Za-z .'\-]{2,80})|Signature\s*:\s*([A-Za-z][A-Za-z .'\-]{2,80})|Digital\s+signature\s+blob\s*:\s*([A-Za-z0-9+/=]{20,}))"
)
_APP_NO_RE = re.compile(
    r"\b(?:Application\s*(?:No\.?|Number)\s*[:#]?\s*)(\d{2}\s*/\s*\d{3},?\d{3}|\d{8})\b",
    re.I,
)
_CONF_NO_RE = re.compile(
    r"\b(?:Confirmation\s*(?:No\.?|Number)\s*[:#]?\s*)(\d{4})\b",
    re.I,
)
_RECEIPT_ID_RE = re.compile(
    r"\b(?:Receipt|Acknowledgement|Acknowledgment)\s*(?:ID|No\.?|Number)?\s*[:#]?\s*([A-Z0-9\-]{6,})\b",
    re.I,
)
_RECEIPT_DATE_RE = re.compile(
    r"\b(?:Receipt\s*Date|Filing\s*Date|Received)\s*[:#]?\s*(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}Z)?|\d{1,2}/\d{1,2}/\d{4})\b",
    re.I,
)
_PAYMENT_RE = re.compile(
    r"(?mi)(?:Payment\s*(?:Amount|Total)?\s*[:#]?\s*\$?\s*([\d,]+\.\d{2})|Amount\s*(?:Paid|USD)?\s*[:#]?\s*\$?\s*([\d,]+\.\d{2})|Deposit\s*Account\s*(?:last\s*4|ending)?\s*[:#*]?\s*([*\dxX]{0,8}\d{4}))"
)
_ATTACHMENT_RE = re.compile(
    r"(?mi)^\s*(?:Attachment|Exhibit|Appendix)\s*[:#]?\s*(.+)$"
)
_DOC_DESC_RE = re.compile(
    r"(?mi)^\s*Document\s+Description\s*[:#]?\s*(.+)$"
)
_ATTORNEY_DOCKET_RE = re.compile(
    r"\b(?:Attorney\s*Docket\s*(?:No\.?|Number)?\s*[:#]?\s*)([A-Z0-9][A-Z0-9./\-]{2,})\b",
    re.I,
)


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class SubmissionProcessor:
    """Extract submission facts, amendments, metadata, and receipts with spans."""

    def __init__(
        self,
        *,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._id_factory = id_factory or (lambda: f"sub:{uuid.uuid4().hex}")

    def process(
        self,
        value: SubmissionPackageInput | Mapping[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> SubmissionAnalysisResult:
        package = self._coerce_package(value, **kwargs)
        return self._process(package)

    def process_many(
        self, values: Iterable[SubmissionPackageInput | Mapping[str, Any]]
    ) -> list[SubmissionAnalysisResult]:
        return [self.process(v) for v in values]

    def _coerce_package(
        self,
        value: SubmissionPackageInput | Mapping[str, Any] | None,
        **kwargs: Any,
    ) -> SubmissionPackageInput:
        if value is None:
            return SubmissionPackageInput(**kwargs)
        if isinstance(value, SubmissionPackageInput):
            if kwargs:
                data = value.to_dict()
                data.update(kwargs)
                return SubmissionPackageInput.from_dict(data)
            return value
        if isinstance(value, Mapping):
            data = dict(value)
            data.update(kwargs)
            return SubmissionPackageInput.from_dict(data)
        raise TypeError(
            "process() expects SubmissionPackageInput, mapping, or kwargs"
        )

    def _process(self, package: SubmissionPackageInput) -> SubmissionAnalysisResult:
        analysis_id = str(self._id_factory())
        classifications = [package.classification]
        for art in package.artifacts:
            classifications.append(art.classification)
        classification = most_restrictive_classification(classifications)

        reason_codes: list[str] = []
        warnings: list[str] = []
        facts: list[EnrichedSubmissionFact] = []
        spans: list[ExtractedSpan] = []
        issues: list[SubmissionIssue] = []
        claim_versions: list[ClaimVersion] = list(package.claim_versions)
        span_seq = 0
        fact_seq = 0
        issue_seq = 0

        def next_span_id() -> str:
            nonlocal span_seq
            span_seq += 1
            return f"span:{analysis_id}:{span_seq:04d}"

        def next_fact_id() -> str:
            nonlocal fact_seq
            fact_seq += 1
            return f"fact:{analysis_id}:{fact_seq:04d}"

        def next_issue_id() -> str:
            nonlocal issue_seq
            issue_seq += 1
            return f"issue:{analysis_id}:{issue_seq:04d}"

        def add_issue(
            kind: SubmissionIssueKind,
            *,
            severity: str,
            message_code: str,
            artifact_ids: Sequence[str] = (),
            related_span_ids: Sequence[str] = (),
            detail: str | None = None,
        ) -> None:
            issues.append(
                SubmissionIssue(
                    schema_version=SUBMISSION_PROCESSOR_SCHEMA_VERSION,
                    issue_id=next_issue_id(),
                    kind=kind,
                    severity=severity,
                    message_code=message_code,
                    artifact_ids=tuple(artifact_ids),
                    related_span_ids=tuple(related_span_ids),
                    detail=detail,
                    classification=classification,
                )
            )

        def make_span(
            *,
            artifact_id: str,
            text: str,
            char_start: int | None,
            char_end: int | None,
            page_index: int | None,
            origin: ExtractionOrigin,
            reading_order: int | None,
            confidence: float | None = 0.9,
        ) -> ExtractedSpan:
            span = ExtractedSpan(
                schema_version=CONTRACTS_SCHEMA_VERSION,
                span_id=next_span_id(),
                artifact_id=artifact_id,
                page_index=page_index,
                char_start=char_start,
                char_end=char_end,
                bbox=None,
                origin=origin,
                reading_order=reading_order,
                confidence=confidence,
                text_digest=_text_digest(text),
                image_digest=None,
                classification=classification,
            )
            spans.append(span)
            return span

        def add_fact(
            *,
            fact_type: SubmissionFactType,
            artifact: SubmissionArtifactInput,
            span: ExtractedSpan,
            value_text: str,
            affected_claims: Sequence[str] = (),
            version: str | None = None,
            extraction_status: FactExtractionStatus = FactExtractionStatus.OK,
            field_name: str | None = None,
            display_value: str | None = None,
            is_authoritative: bool = False,
            signature_presence: SignaturePresenceStatus | None = None,
            authority_relation: AuthorityRelation | None = None,
        ) -> EnrichedSubmissionFact:
            # Never allow display_value to carry signature material.
            if fact_type is SubmissionFactType.SIGNATURE_PRESENCE:
                display_value = (
                    signature_presence.value
                    if signature_presence is not None
                    else SignaturePresenceStatus.UNKNOWN.value
                )
                value_text = display_value
            fact = SubmissionFact(
                schema_version=CONTRACTS_SCHEMA_VERSION,
                fact_id=next_fact_id(),
                evidence_span_id=span.span_id,
                fact_type=fact_type.value,
                affected_claims=tuple(str(c) for c in affected_claims),
                version=version or artifact.version,
                extraction_status=extraction_status.value,
                classification=classification,
            )
            enriched = EnrichedSubmissionFact(
                fact=fact,
                artifact_id=artifact.artifact_id,
                value_digest=_text_digest(value_text),
                display_value=display_value,
                field_name=field_name,
                page_index=span.page_index,
                authority_relation=authority_relation
                or artifact.authority_relation,
                is_authoritative=is_authoritative,
                signature_presence=signature_presence,
            )
            facts.append(enriched)
            return enriched

        if not package.artifacts:
            add_issue(
                SubmissionIssueKind.EMPTY_PACKAGE,
                severity="error",
                message_code=SubmissionReasonCode.EMPTY_INPUT.value,
                detail="no_artifacts",
            )
            reason_codes.append(SubmissionReasonCode.EMPTY_INPUT.value)
            return SubmissionAnalysisResult(
                schema_version=SUBMISSION_PROCESSOR_SCHEMA_VERSION,
                analysis_id=analysis_id,
                package_id=package.package_id,
                disposition=SubmissionDisposition.REJECTED,
                review_state=ReviewState.REQUIRED,
                classification=classification,
                reason_codes=tuple(reason_codes),
                warnings=tuple(warnings),
                facts=(),
                spans=(),
                issues=tuple(issues),
                current_claims={},
                current_claim_span_ids={},
                claim_versions=tuple(claim_versions),
                authoritative_artifact_ids=(),
                input_artifact_ids=(),
                signature_presence=SignaturePresenceStatus.UNKNOWN,
                acknowledgement_ids=(),
                payment_receipt_present=False,
                parser_versions={"submission_processor": PARSER_VERSION},
                labels=dict(package.labels),
                matter_id=package.matter_id,
            )

        if requires_quarantine(classification):
            reason_codes.append(SubmissionReasonCode.QUARANTINE_CLASSIFICATION.value)

        # Determine authoritative artifacts: DOCX originals win over converted PDFs.
        authoritative_ids = self._resolve_authoritative_ids(package.artifacts)
        if any(a.role is ArtifactRole.AUTHORITATIVE_DOCX for a in package.artifacts):
            reason_codes.append(SubmissionReasonCode.DOCX_AUTHORITATIVE.value)
            if any(a.role is ArtifactRole.USPTO_CONVERTED_PDF for a in package.artifacts):
                add_issue(
                    SubmissionIssueKind.AUTHORITY_DOCX_PREFERRED,
                    severity="info",
                    message_code=SubmissionReasonCode.DOCX_AUTHORITATIVE.value,
                    artifact_ids=authoritative_ids,
                    detail="original_docx_authoritative_over_converted_pdf",
                )

        # Ingest pre-supplied spans from artifacts.
        for art in package.artifacts:
            for s in art.spans:
                spans.append(s)

        # Cross-artifact matter / application number consistency.
        app_numbers: dict[str, str] = {}
        for art in package.artifacts:
            app = art.application_number or art.filing_metadata.get("application_number")
            if not app:
                m = _APP_NO_RE.search(art.full_text or "")
                if m:
                    app = re.sub(r"\s+", "", m.group(1))
            if app:
                app_numbers[art.artifact_id] = app
            if (
                package.matter_id
                and art.matter_id
                and art.matter_id != package.matter_id
            ):
                add_issue(
                    SubmissionIssueKind.MATTER_ID_MISMATCH,
                    severity="error",
                    message_code="matter_id_mismatch",
                    artifact_ids=(art.artifact_id,),
                    detail=f"package={package.matter_id} artifact={art.matter_id}",
                )

        if package.expected_application_number:
            expected = re.sub(r"\s+", "", package.expected_application_number)
            for art_id, app in app_numbers.items():
                if re.sub(r"\s+", "", app) != expected:
                    add_issue(
                        SubmissionIssueKind.MISMATCHED_METADATA,
                        severity="error",
                        message_code=SubmissionReasonCode.MISMATCHED_METADATA.value,
                        artifact_ids=(art_id,),
                        detail=(
                            f"application_number expected={expected} found={app}"
                        ),
                    )
                    reason_codes.append(SubmissionReasonCode.MISMATCHED_METADATA.value)

        # Detect app number conflicts across artifacts.
        unique_apps = {re.sub(r"\s+", "", v) for v in app_numbers.values()}
        if len(unique_apps) > 1:
            add_issue(
                SubmissionIssueKind.MISMATCHED_METADATA,
                severity="error",
                message_code="application_number_conflict",
                artifact_ids=tuple(app_numbers.keys()),
                detail=f"values={sorted(unique_apps)}",
            )
            reason_codes.append(SubmissionReasonCode.MISMATCHED_METADATA.value)

        # DOCX/PDF differences from extraction compare payloads.
        for art in package.artifacts:
            for diff in art.differences:
                kind = str(diff.get("kind") or "content")
                add_issue(
                    SubmissionIssueKind.DOCX_PDF_DIFFERENCE,
                    severity="warning",
                    message_code=SubmissionReasonCode.DOCX_PDF_DIFFERENCE.value,
                    artifact_ids=tuple(
                        x
                        for x in (
                            diff.get("docx_artifact_id") or art.artifact_id,
                            diff.get("pdf_artifact_id"),
                        )
                        if x
                    ),
                    detail=str(diff.get("detail") or kind)[:512],
                )
                if SubmissionReasonCode.DOCX_PDF_DIFFERENCE.value not in reason_codes:
                    reason_codes.append(
                        SubmissionReasonCode.DOCX_PDF_DIFFERENCE.value
                    )

        # Also compare claim text between DOCX and PDF when both present.
        docx_arts = [a for a in package.artifacts if a.role is ArtifactRole.AUTHORITATIVE_DOCX]
        pdf_arts = [a for a in package.artifacts if a.role is ArtifactRole.USPTO_CONVERTED_PDF]
        if docx_arts and pdf_arts:
            d_claims = self._extract_claims_map(docx_arts[0].full_text)
            p_claims = self._extract_claims_map(pdf_arts[0].full_text)
            if d_claims and p_claims and d_claims != p_claims:
                add_issue(
                    SubmissionIssueKind.DOCX_PDF_DIFFERENCE,
                    severity="warning",
                    message_code="claim_text_docx_pdf_mismatch",
                    artifact_ids=(docx_arts[0].artifact_id, pdf_arts[0].artifact_id),
                    detail="claim_text_disagreement",
                )
                if SubmissionReasonCode.DOCX_PDF_DIFFERENCE.value not in reason_codes:
                    reason_codes.append(
                        SubmissionReasonCode.DOCX_PDF_DIFFERENCE.value
                    )

        # Parse each artifact (DOCX first when present).
        parse_order = sorted(
            package.artifacts,
            key=lambda a: (
                0
                if a.role is ArtifactRole.AUTHORITATIVE_DOCX
                else 1
                if a.role
                in (
                    ArtifactRole.SUBMISSION,
                    ArtifactRole.AMENDMENT,
                    ArtifactRole.CLAIM_SET,
                )
                else 2
                if a.role is ArtifactRole.USPTO_CONVERTED_PDF
                else 3
            ),
        )

        reading = 0
        signature_status = SignaturePresenceStatus.ABSENT
        acknowledgement_ids: list[str] = []
        payment_present = False
        parsed_claims_by_version: dict[str, dict[str, str]] = {}
        parsed_claim_spans: dict[str, dict[str, str]] = {}

        for art in parse_order:
            is_auth = art.artifact_id in authoritative_ids
            # Skip non-authoritative PDF claim extraction when DOCX is present —
            # but still extract metadata/receipts/signatures from PDF.
            skip_claims = (
                art.role is ArtifactRole.USPTO_CONVERTED_PDF
                and any(
                    a.role is ArtifactRole.AUTHORITATIVE_DOCX for a in package.artifacts
                )
            )
            text = art.full_text or ""

            # Application metadata fields.
            meta_sources: list[tuple[str, str, int | None]] = []
            for name, val in art.filing_metadata.items():
                meta_sources.append((name, val, None))
            for name, pattern in (
                ("application_number", _APP_NO_RE),
                ("confirmation_number", _CONF_NO_RE),
                ("attorney_docket", _ATTORNEY_DOCKET_RE),
            ):
                m = pattern.search(text)
                if m:
                    meta_sources.append((name, m.group(1).strip(), None))
            seen_meta: set[str] = set()
            for name, val, page in meta_sources:
                key = f"{name}:{val}"
                if key in seen_meta:
                    continue
                seen_meta.add(key)
                start = text.find(val) if val in text else None
                end = (start + len(val)) if start is not None else None
                span = make_span(
                    artifact_id=art.artifact_id,
                    text=val,
                    char_start=start,
                    char_end=end,
                    page_index=page if page is not None else 0,
                    origin=ExtractionOrigin.METADATA
                    if name in art.filing_metadata
                    else ExtractionOrigin.NATIVE,
                    reading_order=reading,
                )
                reading += 1
                add_fact(
                    fact_type=SubmissionFactType.APPLICATION_METADATA,
                    artifact=art,
                    span=span,
                    value_text=val,
                    field_name=name,
                    display_value=val[:256],
                    is_authoritative=is_auth,
                    version=art.version,
                )
                if SubmissionReasonCode.METADATA_EXTRACTED.value not in reason_codes:
                    reason_codes.append(SubmissionReasonCode.METADATA_EXTRACTED.value)

            if not any(
                f.fact.fact_type == SubmissionFactType.APPLICATION_METADATA.value
                and f.field_name == "application_number"
                and f.artifact_id == art.artifact_id
                for f in facts
            ):
                if art.role in (
                    ArtifactRole.SUBMISSION,
                    ArtifactRole.AMENDMENT,
                    ArtifactRole.AUTHORITATIVE_DOCX,
                    ArtifactRole.ACKNOWLEDGEMENT_RECEIPT,
                ):
                    # Expected metadata missing for primary instruments.
                    if package.expected_application_number or art.role is ArtifactRole.ACKNOWLEDGEMENT_RECEIPT:
                        add_issue(
                            SubmissionIssueKind.MISSING_METADATA,
                            severity="warning",
                            message_code="missing_application_number",
                            artifact_ids=(art.artifact_id,),
                        )

            # Document description.
            for m in _DOC_DESC_RE.finditer(text):
                desc = m.group(1).strip()
                span = make_span(
                    artifact_id=art.artifact_id,
                    text=desc,
                    char_start=m.start(1),
                    char_end=m.end(1),
                    page_index=0,
                    origin=ExtractionOrigin.NATIVE,
                    reading_order=reading,
                )
                reading += 1
                add_fact(
                    fact_type=SubmissionFactType.DOCUMENT_DESCRIPTION,
                    artifact=art,
                    span=span,
                    value_text=desc,
                    field_name="document_description",
                    display_value=desc[:256],
                    is_authoritative=is_auth,
                )
            if art.document_description:
                desc = art.document_description
                if not any(
                    f.fact.fact_type == SubmissionFactType.DOCUMENT_DESCRIPTION.value
                    and f.artifact_id == art.artifact_id
                    for f in facts
                ):
                    span = make_span(
                        artifact_id=art.artifact_id,
                        text=desc,
                        char_start=None,
                        char_end=None,
                        page_index=0,
                        origin=ExtractionOrigin.METADATA,
                        reading_order=reading,
                    )
                    reading += 1
                    add_fact(
                        fact_type=SubmissionFactType.DOCUMENT_DESCRIPTION,
                        artifact=art,
                        span=span,
                        value_text=desc,
                        field_name="document_description",
                        display_value=desc[:256],
                        is_authoritative=is_auth,
                    )

            # Attachments.
            for m in _ATTACHMENT_RE.finditer(text):
                att = m.group(1).strip()
                span = make_span(
                    artifact_id=art.artifact_id,
                    text=att,
                    char_start=m.start(1),
                    char_end=m.end(1),
                    page_index=0,
                    origin=ExtractionOrigin.NATIVE,
                    reading_order=reading,
                )
                reading += 1
                add_fact(
                    fact_type=SubmissionFactType.ATTACHMENT,
                    artifact=art,
                    span=span,
                    value_text=att,
                    field_name="attachment",
                    display_value=att[:256],
                    is_authoritative=is_auth,
                )
                if SubmissionReasonCode.ATTACHMENTS_EXTRACTED.value not in reason_codes:
                    reason_codes.append(
                        SubmissionReasonCode.ATTACHMENTS_EXTRACTED.value
                    )
            if art.role is ArtifactRole.ATTACHMENT:
                label = art.document_description or art.labels.get("name") or art.artifact_id
                span = make_span(
                    artifact_id=art.artifact_id,
                    text=label,
                    char_start=None,
                    char_end=None,
                    page_index=0,
                    origin=ExtractionOrigin.METADATA,
                    reading_order=reading,
                )
                reading += 1
                add_fact(
                    fact_type=SubmissionFactType.ATTACHMENT,
                    artifact=art,
                    span=span,
                    value_text=label,
                    field_name="attachment",
                    display_value=label[:256],
                    is_authoritative=is_auth,
                )

            # Forms.
            for m in _FORM_RE.finditer(text):
                form_id = m.group(1).strip()
                span = make_span(
                    artifact_id=art.artifact_id,
                    text=form_id,
                    char_start=m.start(1),
                    char_end=m.end(1),
                    page_index=0,
                    origin=ExtractionOrigin.NATIVE,
                    reading_order=reading,
                )
                reading += 1
                add_fact(
                    fact_type=SubmissionFactType.FORM,
                    artifact=art,
                    span=span,
                    value_text=form_id,
                    field_name="form_number",
                    display_value=form_id,
                    is_authoritative=is_auth,
                )
                if SubmissionReasonCode.FORMS_EXTRACTED.value not in reason_codes:
                    reason_codes.append(SubmissionReasonCode.FORMS_EXTRACTED.value)

            # Declarations.
            for m in _DECLARATION_RE.finditer(text):
                snippet = m.group(0)[:400]
                span = make_span(
                    artifact_id=art.artifact_id,
                    text=snippet,
                    char_start=m.start(),
                    char_end=min(m.end(), m.start() + 400),
                    page_index=0,
                    origin=ExtractionOrigin.NATIVE,
                    reading_order=reading,
                )
                reading += 1
                add_fact(
                    fact_type=SubmissionFactType.DECLARATION,
                    artifact=art,
                    span=span,
                    value_text=snippet,
                    field_name="declaration",
                    display_value="declaration_present",
                    is_authoritative=is_auth,
                )
                if SubmissionReasonCode.DECLARATIONS_EXTRACTED.value not in reason_codes:
                    reason_codes.append(
                        SubmissionReasonCode.DECLARATIONS_EXTRACTED.value
                    )
            if art.role is ArtifactRole.DECLARATION and not any(
                f.fact.fact_type == SubmissionFactType.DECLARATION.value
                and f.artifact_id == art.artifact_id
                for f in facts
            ):
                span = make_span(
                    artifact_id=art.artifact_id,
                    text="declaration_artifact",
                    char_start=None,
                    char_end=None,
                    page_index=0,
                    origin=ExtractionOrigin.METADATA,
                    reading_order=reading,
                )
                reading += 1
                add_fact(
                    fact_type=SubmissionFactType.DECLARATION,
                    artifact=art,
                    span=span,
                    value_text="declaration_artifact",
                    field_name="declaration",
                    display_value="declaration_present",
                    is_authoritative=is_auth,
                )

            # Fees.
            for m in _FEE_RE.finditer(text):
                fee_code = m.group(1) or m.group(4) or m.group(5) or "fee"
                amount = m.group(2) or m.group(3) or m.group(6) or ""
                value = f"{fee_code}:{amount}"
                span = make_span(
                    artifact_id=art.artifact_id,
                    text=value,
                    char_start=m.start(),
                    char_end=m.end(),
                    page_index=0,
                    origin=ExtractionOrigin.NATIVE,
                    reading_order=reading,
                )
                reading += 1
                add_fact(
                    fact_type=SubmissionFactType.FEE_PRESENCE,
                    artifact=art,
                    span=span,
                    value_text=value,
                    field_name="fee",
                    display_value=value[:128],
                    is_authoritative=is_auth,
                )
                if SubmissionReasonCode.FEES_EXTRACTED.value not in reason_codes:
                    reason_codes.append(SubmissionReasonCode.FEES_EXTRACTED.value)

            # Signature presence only.
            layout_sig = any(
                str(c.get("kind", "")).lower() in ("signature_presence", "signature")
                or str(c.get("signature_presence", "")).lower() == "true"
                for c in art.layout_cues
            )
            text_sig = bool(_SIGNATURE_PRESENCE_RE.search(text))
            if layout_sig or text_sig:
                # Suppress any reusable signing material.
                for sm in _SIGNATURE_MATERIAL_RE.finditer(text):
                    add_issue(
                        SubmissionIssueKind.SIGNATURE_MATERIAL_SUPPRESSED,
                        severity="info",
                        message_code=SubmissionReasonCode.SIGNATURE_PRESENCE_ONLY.value,
                        artifact_ids=(art.artifact_id,),
                        detail="signature_material_not_retained",
                    )
                sig_status = SignaturePresenceStatus.PRESENT
                signature_status = SignaturePresenceStatus.PRESENT
                # Span covers presence marker only, never the material group.
                m = _SIGNATURE_PRESENCE_RE.search(text)
                if m:
                    marker = m.group(0)[:64]
                    start, end = m.start(), min(m.end(), m.start() + 64)
                else:
                    marker = "signature_presence"
                    start = end = None
                span = make_span(
                    artifact_id=art.artifact_id,
                    text=marker,
                    char_start=start,
                    char_end=end,
                    page_index=0,
                    origin=ExtractionOrigin.NATIVE,
                    reading_order=reading,
                )
                reading += 1
                add_fact(
                    fact_type=SubmissionFactType.SIGNATURE_PRESENCE,
                    artifact=art,
                    span=span,
                    value_text=sig_status.value,
                    field_name="signature_presence",
                    display_value=sig_status.value,
                    is_authoritative=is_auth,
                    signature_presence=sig_status,
                )
                if (
                    SubmissionReasonCode.SIGNATURE_PRESENCE_ONLY.value
                    not in reason_codes
                ):
                    reason_codes.append(
                        SubmissionReasonCode.SIGNATURE_PRESENCE_ONLY.value
                    )

            # Acknowledgement receipt identifiers.
            if art.role is ArtifactRole.ACKNOWLEDGEMENT_RECEIPT or art.receipt_fields:
                fields = dict(art.receipt_fields)
                for name, pattern in (
                    ("receipt_id", _RECEIPT_ID_RE),
                    ("application_number", _APP_NO_RE),
                    ("confirmation_number", _CONF_NO_RE),
                    ("receipt_date", _RECEIPT_DATE_RE),
                ):
                    if name not in fields:
                        m = pattern.search(text)
                        if m:
                            fields[name] = m.group(1).strip()
                if not fields and art.role is ArtifactRole.ACKNOWLEDGEMENT_RECEIPT:
                    add_issue(
                        SubmissionIssueKind.MISSING_RECEIPT,
                        severity="error",
                        message_code="empty_acknowledgement_receipt",
                        artifact_ids=(art.artifact_id,),
                    )
                for name, val in fields.items():
                    start = text.find(val) if val and val in text else None
                    end = (start + len(val)) if start is not None else None
                    span = make_span(
                        artifact_id=art.artifact_id,
                        text=val,
                        char_start=start,
                        char_end=end,
                        page_index=0,
                        origin=ExtractionOrigin.METADATA,
                        reading_order=reading,
                    )
                    reading += 1
                    add_fact(
                        fact_type=SubmissionFactType.ACKNOWLEDGEMENT_IDENTIFIER,
                        artifact=art,
                        span=span,
                        value_text=val,
                        field_name=name,
                        display_value=val[:256],
                        is_authoritative=True,
                    )
                    if name in ("receipt_id", "acknowledgement_id"):
                        acknowledgement_ids.append(val)
                if fields and (
                    SubmissionReasonCode.ACKNOWLEDGEMENT_EXTRACTED.value
                    not in reason_codes
                ):
                    reason_codes.append(
                        SubmissionReasonCode.ACKNOWLEDGEMENT_EXTRACTED.value
                    )
            else:
                # Still scan body for receipt IDs in mixed documents.
                for m in _RECEIPT_ID_RE.finditer(text):
                    rid = m.group(1).strip()
                    span = make_span(
                        artifact_id=art.artifact_id,
                        text=rid,
                        char_start=m.start(1),
                        char_end=m.end(1),
                        page_index=0,
                        origin=ExtractionOrigin.NATIVE,
                        reading_order=reading,
                    )
                    reading += 1
                    add_fact(
                        fact_type=SubmissionFactType.ACKNOWLEDGEMENT_IDENTIFIER,
                        artifact=art,
                        span=span,
                        value_text=rid,
                        field_name="receipt_id",
                        display_value=rid,
                        is_authoritative=is_auth,
                    )
                    acknowledgement_ids.append(rid)
                    if (
                        SubmissionReasonCode.ACKNOWLEDGEMENT_EXTRACTED.value
                        not in reason_codes
                    ):
                        reason_codes.append(
                            SubmissionReasonCode.ACKNOWLEDGEMENT_EXTRACTED.value
                        )

            # Payment receipt evidence.
            if art.role is ArtifactRole.PAYMENT_RECEIPT or art.receipt_fields.get(
                "amount_usd"
            ):
                fields = dict(art.receipt_fields)
                if "amount_usd" not in fields:
                    m = _PAYMENT_RE.search(text)
                    if m:
                        fields["amount_usd"] = (m.group(1) or m.group(2) or "").strip()
                        if m.group(3):
                            # Masked deposit account only — already masked.
                            fields["payment_method"] = f"deposit_account_last4_masked"
                if not fields and art.role is ArtifactRole.PAYMENT_RECEIPT:
                    add_issue(
                        SubmissionIssueKind.MISSING_RECEIPT,
                        severity="error",
                        message_code="empty_payment_receipt",
                        artifact_ids=(art.artifact_id,),
                    )
                for name, val in fields.items():
                    # Never retain raw card/PAN — only masked markers allowed.
                    if re.search(r"\b\d{13,19}\b", val):
                        add_issue(
                            SubmissionIssueKind.MISMATCHED_RECEIPT,
                            severity="error",
                            message_code="payment_secret_suppressed",
                            artifact_ids=(art.artifact_id,),
                            detail="raw_payment_credential_not_retained",
                        )
                        val = "suppressed"
                    span = make_span(
                        artifact_id=art.artifact_id,
                        text=val,
                        char_start=None,
                        char_end=None,
                        page_index=0,
                        origin=ExtractionOrigin.METADATA,
                        reading_order=reading,
                    )
                    reading += 1
                    add_fact(
                        fact_type=SubmissionFactType.PAYMENT_RECEIPT,
                        artifact=art,
                        span=span,
                        value_text=val,
                        field_name=name,
                        display_value=val[:128],
                        is_authoritative=True,
                    )
                    payment_present = True
                if fields and (
                    SubmissionReasonCode.PAYMENT_RECEIPT_EXTRACTED.value
                    not in reason_codes
                ):
                    reason_codes.append(
                        SubmissionReasonCode.PAYMENT_RECEIPT_EXTRACTED.value
                    )
            else:
                for m in _PAYMENT_RE.finditer(text):
                    amount = (m.group(1) or m.group(2) or "").strip()
                    if not amount:
                        continue
                    span = make_span(
                        artifact_id=art.artifact_id,
                        text=amount,
                        char_start=m.start(),
                        char_end=m.end(),
                        page_index=0,
                        origin=ExtractionOrigin.NATIVE,
                        reading_order=reading,
                    )
                    reading += 1
                    add_fact(
                        fact_type=SubmissionFactType.PAYMENT_RECEIPT,
                        artifact=art,
                        span=span,
                        value_text=amount,
                        field_name="amount_usd",
                        display_value=amount,
                        is_authoritative=is_auth,
                    )
                    payment_present = True
                    if (
                        SubmissionReasonCode.PAYMENT_RECEIPT_EXTRACTED.value
                        not in reason_codes
                    ):
                        reason_codes.append(
                            SubmissionReasonCode.PAYMENT_RECEIPT_EXTRACTED.value
                        )

            # Remarks.
            if not skip_claims or art.role is ArtifactRole.REMARKS:
                m = _REMARKS_RE.search(text)
                if m and m.group(1).strip():
                    body = m.group(1).strip()[:4000]
                    span = make_span(
                        artifact_id=art.artifact_id,
                        text=body,
                        char_start=m.start(1),
                        char_end=m.start(1) + len(body),
                        page_index=0,
                        origin=ExtractionOrigin.NATIVE,
                        reading_order=reading,
                    )
                    reading += 1
                    add_fact(
                        fact_type=SubmissionFactType.REMARKS,
                        artifact=art,
                        span=span,
                        value_text=body,
                        field_name="remarks",
                        display_value=body[:256],
                        is_authoritative=is_auth,
                    )
                    if SubmissionReasonCode.REMARKS_EXTRACTED.value not in reason_codes:
                        reason_codes.append(
                            SubmissionReasonCode.REMARKS_EXTRACTED.value
                        )

            # Amendment instructions.
            if not skip_claims:
                for m in _AMENDMENT_INSTR_RE.finditer(text):
                    claim_ref = m.group(1).strip()
                    body = (m.group(2) or "").strip()[:2000]
                    affected = _parse_claim_list(claim_ref)
                    value = f"amend:{claim_ref}:{body}"
                    span = make_span(
                        artifact_id=art.artifact_id,
                        text=value[:2000],
                        char_start=m.start(),
                        char_end=min(m.end(), m.start() + 2000),
                        page_index=0,
                        origin=ExtractionOrigin.NATIVE,
                        reading_order=reading,
                    )
                    reading += 1
                    add_fact(
                        fact_type=SubmissionFactType.AMENDMENT_INSTRUCTION,
                        artifact=art,
                        span=span,
                        value_text=value,
                        affected_claims=affected,
                        field_name="amendment_instruction",
                        display_value=f"amend claims {claim_ref}"[:256],
                        is_authoritative=is_auth,
                        version=art.version,
                    )
                    if (
                        SubmissionReasonCode.AMENDMENTS_EXTRACTED.value
                        not in reason_codes
                    ):
                        reason_codes.append(
                            SubmissionReasonCode.AMENDMENTS_EXTRACTED.value
                        )

                # Status-labeled claims (currently amended / new / …).
                status_hits = list(_CLAIM_STATUS_RE.finditer(text))
                version_claims: dict[str, str] = {}
                version_spans: dict[str, str] = {}
                if status_hits:
                    for m in status_hits:
                        num = m.group(1)
                        status = m.group(2).lower().replace("cancelled", "canceled")
                        claim_text = (m.group(3) or "").strip()
                        if status in ("canceled", "withdrawn"):
                            claim_text = claim_text or f"({status})"
                        value = f"{num}|{status}|{claim_text}"
                        span = make_span(
                            artifact_id=art.artifact_id,
                            text=value[:4000],
                            char_start=m.start(),
                            char_end=min(m.end(), m.start() + 4000),
                            page_index=0,
                            origin=ExtractionOrigin.NATIVE,
                            reading_order=reading,
                        )
                        reading += 1
                        add_fact(
                            fact_type=SubmissionFactType.CLAIM
                            if status != "currently amended"
                            else SubmissionFactType.AMENDMENT_INSTRUCTION,
                            artifact=art,
                            span=span,
                            value_text=value,
                            affected_claims=(num,),
                            field_name=f"claim_status:{status}",
                            display_value=claim_text[:256] if claim_text else status,
                            is_authoritative=is_auth,
                            version=art.version,
                        )
                        if status not in ("canceled", "withdrawn") and claim_text:
                            version_claims[num] = claim_text
                            version_spans[num] = span.span_id
                    if version_claims:
                        parsed_claims_by_version[art.version] = {
                            **parsed_claims_by_version.get(art.version, {}),
                            **version_claims,
                        }
                        parsed_claim_spans[art.version] = {
                            **parsed_claim_spans.get(art.version, {}),
                            **version_spans,
                        }
                    if SubmissionReasonCode.CLAIMS_EXTRACTED.value not in reason_codes:
                        reason_codes.append(
                            SubmissionReasonCode.CLAIMS_EXTRACTED.value
                        )
                    if status_hits and (
                        SubmissionReasonCode.AMENDMENTS_EXTRACTED.value
                        not in reason_codes
                    ):
                        reason_codes.append(
                            SubmissionReasonCode.AMENDMENTS_EXTRACTED.value
                        )
                else:
                    # Plain numbered claims.
                    plain = list(_CLAIM_LINE_RE.finditer(text))
                    version_claims = {}
                    version_spans = {}
                    for m in plain:
                        num = m.group(1)
                        claim_text = m.group(2).strip()
                        if not claim_text:
                            continue
                        span = make_span(
                            artifact_id=art.artifact_id,
                            text=claim_text[:4000],
                            char_start=m.start(2),
                            char_end=min(m.end(2), m.start(2) + 4000),
                            page_index=0,
                            origin=ExtractionOrigin.NATIVE,
                            reading_order=reading,
                        )
                        reading += 1
                        add_fact(
                            fact_type=SubmissionFactType.CLAIM,
                            artifact=art,
                            span=span,
                            value_text=claim_text,
                            affected_claims=(num,),
                            field_name="claim",
                            display_value=claim_text[:256],
                            is_authoritative=is_auth,
                            version=art.version,
                        )
                        version_claims[num] = claim_text
                        version_spans[num] = span.span_id
                    if version_claims:
                        parsed_claims_by_version[art.version] = {
                            **parsed_claims_by_version.get(art.version, {}),
                            **version_claims,
                        }
                        parsed_claim_spans[art.version] = {
                            **parsed_claim_spans.get(art.version, {}),
                            **version_spans,
                        }
                        if (
                            SubmissionReasonCode.CLAIMS_EXTRACTED.value
                            not in reason_codes
                        ):
                            reason_codes.append(
                                SubmissionReasonCode.CLAIMS_EXTRACTED.value
                            )

            # Version marker fact.
            if art.version and art.version not in ("1", "unknown"):
                span = make_span(
                    artifact_id=art.artifact_id,
                    text=art.version,
                    char_start=None,
                    char_end=None,
                    page_index=0,
                    origin=ExtractionOrigin.METADATA,
                    reading_order=reading,
                )
                reading += 1
                add_fact(
                    fact_type=SubmissionFactType.VERSION_MARKER,
                    artifact=art,
                    span=span,
                    value_text=art.version,
                    field_name="version",
                    display_value=art.version,
                    is_authoritative=is_auth,
                    version=art.version,
                )

        # Build claim_versions from package input + parsed claims.
        for cv in package.claim_versions:
            claim_versions  # already seeded
        for ver, claims in parsed_claims_by_version.items():
            span_map = parsed_claim_spans.get(ver, {})
            # Prefer matching artifact for this version.
            art_id = None
            for a in package.artifacts:
                if a.version == ver:
                    art_id = a.artifact_id
                    break
            # Merge if already provided.
            existing = next((c for c in claim_versions if c.version == ver), None)
            if existing:
                merged = {**dict(existing.claims), **claims}
                merged_spans = {**dict(existing.source_span_ids), **span_map}
                claim_versions = [c for c in claim_versions if c.version != ver]
                claim_versions.append(
                    ClaimVersion(
                        version=ver,
                        claims=merged,
                        artifact_id=art_id or existing.artifact_id,
                        source_span_ids=merged_spans,
                    )
                )
            else:
                claim_versions.append(
                    ClaimVersion(
                        version=ver,
                        claims=claims,
                        artifact_id=art_id,
                        source_span_ids=span_map,
                    )
                )

        # Reconstruct current claims: last non-as_filed version wins, else as_filed.
        current_claims, current_span_ids = self._reconstruct_current_claims(
            claim_versions
        )
        if current_claims:
            # Prefer authoritative artifact for current-claim facts.
            auth_art = None
            for a in package.artifacts:
                if a.artifact_id in authoritative_ids:
                    auth_art = a
                    break
            if auth_art is None and package.artifacts:
                auth_art = package.artifacts[0]
            for num, claim_text in sorted(
                current_claims.items(), key=lambda kv: _claim_sort_key(kv[0])
            ):
                span_id = current_span_ids.get(num)
                if span_id:
                    span = next((s for s in spans if s.span_id == span_id), None)
                else:
                    span = None
                if span is None and auth_art is not None:
                    span = make_span(
                        artifact_id=auth_art.artifact_id,
                        text=claim_text[:4000],
                        char_start=None,
                        char_end=None,
                        page_index=0,
                        origin=ExtractionOrigin.MERGED,
                        reading_order=reading,
                    )
                    reading += 1
                    current_span_ids[num] = span.span_id
                if span is not None and auth_art is not None:
                    add_fact(
                        fact_type=SubmissionFactType.CURRENT_CLAIM,
                        artifact=auth_art,
                        span=span,
                        value_text=claim_text,
                        affected_claims=(num,),
                        field_name="current_claim",
                        display_value=claim_text[:256],
                        is_authoritative=True,
                        version="current",
                        authority_relation=AuthorityRelation.AUTHORITATIVE_ORIGINAL,
                    )
            if (
                SubmissionReasonCode.CURRENT_CLAIMS_RECONSTRUCTED.value
                not in reason_codes
            ):
                reason_codes.append(
                    SubmissionReasonCode.CURRENT_CLAIMS_RECONSTRUCTED.value
                )

        # Required receipt checks.
        has_ack_artifact = any(
            a.role is ArtifactRole.ACKNOWLEDGEMENT_RECEIPT for a in package.artifacts
        )
        has_pay_artifact = any(
            a.role is ArtifactRole.PAYMENT_RECEIPT for a in package.artifacts
        )
        if package.require_ack_receipt and not (
            has_ack_artifact or acknowledgement_ids
        ):
            add_issue(
                SubmissionIssueKind.MISSING_RECEIPT,
                severity="error",
                message_code=SubmissionReasonCode.MISSING_RECEIPT.value,
                detail="acknowledgement_receipt_required",
            )
            reason_codes.append(SubmissionReasonCode.MISSING_RECEIPT.value)
        if package.require_payment_receipt and not (has_pay_artifact or payment_present):
            add_issue(
                SubmissionIssueKind.MISSING_RECEIPT,
                severity="error",
                message_code=SubmissionReasonCode.MISSING_RECEIPT.value,
                detail="payment_receipt_required",
            )
            reason_codes.append(SubmissionReasonCode.MISSING_RECEIPT.value)

        # Document description mismatches across artifacts with descriptions.
        descs = {
            a.artifact_id: a.document_description
            for a in package.artifacts
            if a.document_description
        }
        if len(set(descs.values())) > 1 and len(descs) > 1:
            # Only flag when same-role pair or explicitly linked.
            linked_pairs = []
            for a in package.artifacts:
                for rel in a.related_artifact_ids:
                    if rel in descs and a.document_description and descs[rel] != a.document_description:
                        linked_pairs.append((a.artifact_id, rel))
            if linked_pairs:
                for a_id, b_id in linked_pairs:
                    add_issue(
                        SubmissionIssueKind.DOCUMENT_DESCRIPTION_MISMATCH,
                        severity="warning",
                        message_code="document_description_mismatch",
                        artifact_ids=(a_id, b_id),
                    )

        # Every fact must point at a known span.
        span_ids = {s.span_id for s in spans}
        for f in facts:
            if f.fact.evidence_span_id not in span_ids:
                add_issue(
                    SubmissionIssueKind.MISSING_SPAN,
                    severity="error",
                    message_code="fact_span_missing",
                    artifact_ids=(f.artifact_id,),
                    related_span_ids=(f.fact.evidence_span_id,),
                )

        # Disposition.
        error_issues = [i for i in issues if i.severity == "error"]
        warning_issues = [i for i in issues if i.severity == "warning"]
        disposition = SubmissionDisposition.EXTRACTED
        review_state = ReviewState.NOT_REQUIRED
        if requires_quarantine(classification):
            disposition = SubmissionDisposition.QUARANTINE
            review_state = ReviewState.REQUIRED
            reason_codes.append(SubmissionReasonCode.REVIEW_REQUIRED.value)
        elif error_issues or warning_issues:
            disposition = SubmissionDisposition.REVIEW
            review_state = ReviewState.REQUIRED
            if SubmissionReasonCode.REVIEW_REQUIRED.value not in reason_codes:
                reason_codes.append(SubmissionReasonCode.REVIEW_REQUIRED.value)
        elif not facts:
            disposition = SubmissionDisposition.REVIEW
            review_state = ReviewState.REQUIRED
            warnings.append("no_facts_extracted")
            reason_codes.append(SubmissionReasonCode.REVIEW_REQUIRED.value)

        # Deduplicate acknowledgement ids.
        ack_unique: list[str] = []
        for a in acknowledgement_ids:
            if a not in ack_unique:
                ack_unique.append(a)

        return SubmissionAnalysisResult(
            schema_version=SUBMISSION_PROCESSOR_SCHEMA_VERSION,
            analysis_id=analysis_id,
            package_id=package.package_id,
            disposition=disposition,
            review_state=review_state,
            classification=classification,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            warnings=tuple(warnings),
            facts=tuple(facts),
            spans=tuple(spans),
            issues=tuple(issues),
            current_claims=current_claims,
            current_claim_span_ids=current_span_ids,
            claim_versions=tuple(claim_versions),
            authoritative_artifact_ids=tuple(authoritative_ids),
            input_artifact_ids=tuple(a.artifact_id for a in package.artifacts),
            signature_presence=signature_status,
            acknowledgement_ids=tuple(ack_unique),
            payment_receipt_present=payment_present,
            parser_versions={"submission_processor": PARSER_VERSION},
            labels=dict(package.labels),
            matter_id=package.matter_id,
        )

    @staticmethod
    def _resolve_authoritative_ids(
        artifacts: Sequence[SubmissionArtifactInput],
    ) -> list[str]:
        """DOCX originals and explicit authoritative relations take precedence."""
        ids: list[str] = []
        for a in artifacts:
            if a.role is ArtifactRole.AUTHORITATIVE_DOCX:
                ids.append(a.artifact_id)
            elif a.authority_relation is AuthorityRelation.AUTHORITATIVE_ORIGINAL:
                ids.append(a.artifact_id)
        if ids:
            return list(dict.fromkeys(ids))
        # Fallback: non-derivative, non-pdf-conversion artifacts.
        for a in artifacts:
            if a.role is ArtifactRole.USPTO_CONVERTED_PDF:
                continue
            if a.authority_relation is AuthorityRelation.DERIVATIVE:
                continue
            if a.role in (
                ArtifactRole.SUBMISSION,
                ArtifactRole.AMENDMENT,
                ArtifactRole.CLAIM_SET,
                ArtifactRole.DECLARATION,
                ArtifactRole.FORM,
            ):
                ids.append(a.artifact_id)
        if not ids and artifacts:
            ids.append(artifacts[0].artifact_id)
        return list(dict.fromkeys(ids))

    @staticmethod
    def _extract_claims_map(text: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for m in _CLAIM_STATUS_RE.finditer(text or ""):
            status = m.group(2).lower()
            if status in ("canceled", "cancelled", "withdrawn"):
                continue
            body = (m.group(3) or "").strip()
            if body:
                out[m.group(1)] = body
        if out:
            return out
        for m in _CLAIM_LINE_RE.finditer(text or ""):
            body = m.group(2).strip()
            if body:
                out[m.group(1)] = body
        return out

    @staticmethod
    def _reconstruct_current_claims(
        versions: Sequence[ClaimVersion],
    ) -> tuple[dict[str, str], dict[str, str]]:
        if not versions:
            return {}, {}
        # Prefer explicit "current", else last amendment-like, else as_filed.
        by_ver = {v.version: v for v in versions}
        order = list(versions)
        chosen: ClaimVersion | None = by_ver.get("current")
        if chosen is None:
            # Walk in order; later versions overlay earlier.
            claims: dict[str, str] = {}
            spans: dict[str, str] = {}
            for v in order:
                for num, text in v.claims.items():
                    if text.lower().strip() in ("(canceled)", "(cancelled)", "(withdrawn)"):
                        claims.pop(num, None)
                        spans.pop(num, None)
                    else:
                        claims[num] = text
                        if num in v.source_span_ids:
                            spans[num] = v.source_span_ids[num]
            return claims, spans
        return dict(chosen.claims), dict(chosen.source_span_ids)


def _parse_claim_list(ref: str) -> tuple[str, ...]:
    """Parse '1-3 and 5' style claim references into discrete numbers."""
    ref = ref.replace("and", ",")
    parts = re.split(r"[,;\s]+", ref)
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if "-" in p or "–" in p:
            a, _, b = re.split(r"[-–]", p, maxsplit=1)
            try:
                start, end = int(a), int(b)
                if 0 < end - start < 50:
                    out.extend(str(i) for i in range(start, end + 1))
                else:
                    out.append(p)
            except ValueError:
                out.append(p)
        elif re.fullmatch(r"\d+", p):
            out.append(p)
    return tuple(dict.fromkeys(out))


def process_submission(
    value: SubmissionPackageInput | Mapping[str, Any] | None = None,
    /,
    **kwargs: Any,
) -> SubmissionAnalysisResult:
    """Module-level convenience wrapper around :class:`SubmissionProcessor`."""
    return SubmissionProcessor().process(value, **kwargs)


def artifact_from_extraction(
    *,
    artifact_id: str,
    role: ArtifactRole | str,
    full_text: str,
    classification: DisclosureClassification | str = DisclosureClassification.PUBLIC_USER,
    content_sha256: str | None = None,
    media_family: str | None = None,
    spans: Sequence[ExtractedSpan] | None = None,
    filing_metadata: Mapping[str, str] | None = None,
    document_description: str | None = None,
    matter_id: str | None = None,
    application_number: str | None = None,
    version: str = "1",
    receipt_fields: Mapping[str, str] | None = None,
    related_artifact_ids: Sequence[str] = (),
    authority_relation: AuthorityRelation | str = AuthorityRelation.UNKNOWN,
    differences: Sequence[Mapping[str, Any]] = (),
    layout_cues: Sequence[Mapping[str, str]] = (),
    labels: Mapping[str, str] | None = None,
) -> SubmissionArtifactInput:
    """Helper to build a :class:`SubmissionArtifactInput` from extraction outputs."""
    return SubmissionArtifactInput(
        artifact_id=artifact_id,
        role=role,  # type: ignore[arg-type]
        classification=classification,  # type: ignore[arg-type]
        content_sha256=content_sha256,
        media_family=media_family,
        full_text=full_text,
        spans=tuple(spans or ()),
        filing_metadata=filing_metadata or {},
        document_description=document_description,
        matter_id=matter_id,
        application_number=application_number,
        version=version,
        receipt_fields=receipt_fields or {},
        related_artifact_ids=tuple(related_artifact_ids),
        authority_relation=authority_relation,  # type: ignore[arg-type]
        differences=tuple(differences),
        layout_cues=tuple(layout_cues),
        labels=labels or {},
    )


__all__ = [
    "SUBMISSION_PROCESSOR_INTERFACE",
    "SUBMISSION_PROCESSOR_SCHEMA_VERSION",
    "PARSER_VERSION",
    "ArtifactRole",
    "ClaimVersion",
    "EnrichedSubmissionFact",
    "FactExtractionStatus",
    "SignaturePresenceStatus",
    "SubmissionAnalysisResult",
    "SubmissionArtifactInput",
    "SubmissionDisposition",
    "SubmissionFactType",
    "SubmissionIssue",
    "SubmissionIssueKind",
    "SubmissionPackageInput",
    "SubmissionProcessor",
    "SubmissionProcessorError",
    "SubmissionReasonCode",
    "artifact_from_extraction",
    "process_submission",
    "sha256_hex",
]
