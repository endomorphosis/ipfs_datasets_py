"""Reconcile official filing receipts and USPTO-converted artifacts (PATLAW-155).

After a human Patent Center handoff records an approved/submitted package
digest (PATLAW-154), acknowledgement, payment, and USPTO-converted artifacts
arrive only through explicit authorized import. This module:

* cross-checks application / customer / confirmation identifiers;
* cross-checks submitted filenames, content digests, timestamps, and document
  counts;
* evaluates conversion differences (exact match vs expected conversion with
  disclosed differences);
* applies the **authoritative acknowledgement rule** for filed status; and
* appends immutable, content-free reconciliation events to the matter ledger.

Design invariants
-----------------
* A **payment receipt alone is never** filing acknowledgement and never
  authorizes filed / receipt-verified status.
* Exact matches and expected conversions with disclosed differences may
  verify; wrong matter, missing acknowledgement, mismatched files, partial
  submission, and payment-only cases remain **conflicting** or **incomplete**.
* Results and ledger events are **content-free**: digests, identifiers, and
  reason codes only — never document bodies, claim text, or payment secrets.
* No network, browser, session, payment, signature, or automated filing
  surface exists. Receipts are never fabricated.

Conflict policy (PATLAW-155): own this reconciler and its tests only; do not
edit the durable store implementation.
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
    MatterEvent,
    MatterEventKind,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.matter_ledger import (
    IngestResult,
    LedgerChannel,
    MatterLedger,
)

# ---------------------------------------------------------------------------
# Versions / interface
# ---------------------------------------------------------------------------

RECONCILER_SCHEMA_VERSION: Final = "uspto.filing-receipt-reconciler.v1"
RECONCILER_INTERFACE: Final = "FilingReceiptReconciler@1"
PARSER_VERSION: Final = "patlaw-155.filing-receipt-reconciler.v1"
RULESET_VERSION: Final = "filing-receipt-acknowledgement-policy@1"

OUTPUT_KIND_RECONCILIATION: Final = "filing_receipt_reconciliation"
OUTPUT_KIND_RECONCILIATION_EVENT: Final = "filing_receipt_reconciliation_event"

RECONCILER_DISCLAIMER: Final = (
    "Filing receipt reconciliation is decision support. It never fabricates "
    "acknowledgement or payment evidence, never treats a payment receipt alone "
    "as filing acknowledgement, never logs private document content, and never "
    "claims filing occurred without the authoritative acknowledgement rule."
)

DEFAULT_MAX_FILES: Final = 256
DEFAULT_MAX_EVIDENCE: Final = 64
DEFAULT_MAX_DIFFERENCES: Final = 256
DEFAULT_MAX_REASON_CODES: Final = 128
DEFAULT_MAX_WARNINGS: Final = 256

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_ISO_UTC_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)

# Capabilities this module must never expose successfully.
FORBIDDEN_RECONCILER_INTERFACES: Final[frozenset[str]] = frozenset(
    {
        "network",
        "network_login",
        "network_request",
        "http_client",
        "browser",
        "browser_control",
        "automate_browser",
        "selenium",
        "playwright",
        "session",
        "session_store",
        "payment",
        "pay_fee",
        "sign",
        "apply_signature",
        "file",
        "file_application",
        "submit",
        "perform_final_submission",
        "automate_patent_center",
        "fabricate_acknowledgement",
        "fabricate_payment_receipt",
        "fabricate_receipt",
        "claim_filing_occurred",
        "log_private_content",
    }
)

FORBIDDEN_IMPORT_MODULES: Final[frozenset[str]] = frozenset(
    {
        "requests",
        "httpx",
        "urllib3",
        "aiohttp",
        "selenium",
        "playwright",
        "pyppeteer",
    }
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ReconciliationDisposition(str, Enum):
    """Overall outcome of one reconciliation pass."""

    VERIFIED = "verified"
    """Exact match of identifiers, files, and required acknowledgement."""

    VERIFIED_WITH_DISCLOSED_DIFFERENCES = "verified_with_disclosed_differences"
    """Expected conversion differences disclosed and accepted."""

    CONFLICTING = "conflicting"
    """Identifier, matter, digest, or file conflicts prevent verification."""

    INCOMPLETE = "incomplete"
    """Missing required evidence (ack, partial submission, payment-only, …)."""


class FiledStatusEligibility(str, Enum):
    """Whether filed / receipt-verified status may be asserted."""

    ELIGIBLE = "eligible"
    BLOCKED = "blocked"


class EvidenceRole(str, Enum):
    """Role of an imported official artifact (non-substitutable)."""

    ACKNOWLEDGEMENT = "acknowledgement"
    PAYMENT_RECEIPT = "payment_receipt"
    USPTO_CONVERTED = "uspto_converted"
    OFFICIAL_FILING_RECEIPT = "official_filing_receipt"
    CORRECTED_FILING_RECEIPT = "corrected_filing_receipt"
    OTHER = "other"


class ConversionMatchKind(str, Enum):
    """How a converted artifact relates to the submitted package."""

    EXACT = "exact"
    EXPECTED_CONVERSION = "expected_conversion"
    MISMATCHED = "mismatched"
    MISSING = "missing"
    UNEXPECTED = "unexpected"
    NOT_APPLICABLE = "not_applicable"


class IdentifierMatchKind(str, Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    MISSING_EXPECTED = "missing_expected"
    MISSING_OBSERVED = "missing_observed"
    ABSENT_BOTH = "absent_both"


class FileMatchKind(str, Enum):
    EXACT = "exact"
    DIGEST_MISMATCH = "digest_mismatch"
    MISSING_FROM_RECEIPT = "missing_from_receipt"
    UNEXPECTED_ON_RECEIPT = "unexpected_on_receipt"
    PARTIAL = "partial"


class ReconciliationReasonCode(str, Enum):
    EXACT_MATCH = "exact_match"
    EXPECTED_CONVERSION_DISCLOSED = "expected_conversion_disclosed"
    AUTHORITATIVE_ACKNOWLEDGEMENT_PRESENT = "authoritative_acknowledgement_present"
    AUTHORITATIVE_ACKNOWLEDGEMENT_MISSING = "authoritative_acknowledgement_missing"
    PAYMENT_ONLY_INSUFFICIENT = "payment_only_insufficient"
    PAYMENT_RECEIPT_PRESENT = "payment_receipt_present"
    WRONG_MATTER = "wrong_matter"
    PACKAGE_DIGEST_MISMATCH = "package_digest_mismatch"
    SUBMITTED_DIGEST_MISMATCH = "submitted_digest_mismatch"
    APPLICATION_NUMBER_MISMATCH = "application_number_mismatch"
    CUSTOMER_NUMBER_MISMATCH = "customer_number_mismatch"
    CONFIRMATION_NUMBER_MISMATCH = "confirmation_number_mismatch"
    FILE_DIGEST_MISMATCH = "file_digest_mismatch"
    FILENAME_MISMATCH = "filename_mismatch"
    DOCUMENT_COUNT_MISMATCH = "document_count_mismatch"
    PARTIAL_SUBMISSION = "partial_submission"
    CONVERSION_MISMATCH = "conversion_mismatch"
    CONVERSION_DIFFERENCE_UNDISCLOSED = "conversion_difference_undisclosed"
    TIMESTAMP_MISMATCH = "timestamp_mismatch"
    FABRICATED_EVIDENCE_REJECTED = "fabricated_evidence_rejected"
    UNVERIFIED_ACKNOWLEDGEMENT = "unverified_acknowledgement"
    NO_EVIDENCE = "no_evidence"
    LEDGER_EVENT_APPENDED = "ledger_event_appended"
    CONTENT_FREE_RESULT = "content_free_result"
    FILED_STATUS_BLOCKED = "filed_status_blocked"
    FILED_STATUS_ELIGIBLE = "filed_status_eligible"
    REVIEW_REQUIRED = "review_required"


# ---------------------------------------------------------------------------
# Reviewed authoritative acknowledgement policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthoritativeAcknowledgementPolicy:
    """Reviewed policy: filed status requires verified acknowledgement.

    Aligns with PATLAW-154 ``has_verified_official_artifacts_for_receipt``:
    at least one non-fabricated, verified acknowledgement bound to the
    approved/submitted package digest. Payment alone never qualifies.
    """

    policy_id: str = RULESET_VERSION
    requires_verified_acknowledgement: bool = True
    payment_receipt_alone_insufficient: bool = True
    acknowledgement_must_bind_package_digest: bool = True
    acknowledgement_must_not_be_fabricated: bool = True
    accept_expected_conversion_with_disclosed_differences: bool = True
    require_submitted_digest_match: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "accept_expected_conversion_with_disclosed_differences": (
                self.accept_expected_conversion_with_disclosed_differences
            ),
            "acknowledgement_must_bind_package_digest": (
                self.acknowledgement_must_bind_package_digest
            ),
            "acknowledgement_must_not_be_fabricated": (
                self.acknowledgement_must_not_be_fabricated
            ),
            "payment_receipt_alone_insufficient": (
                self.payment_receipt_alone_insufficient
            ),
            "policy_id": self.policy_id,
            "require_submitted_digest_match": self.require_submitted_digest_match,
            "requires_verified_acknowledgement": (
                self.requires_verified_acknowledgement
            ),
        }

    @classmethod
    def reviewed_default(cls) -> "AuthoritativeAcknowledgementPolicy":
        return cls()


DEFAULT_ACKNOWLEDGEMENT_POLICY: Final = (
    AuthoritativeAcknowledgementPolicy.reviewed_default()
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FilingReceiptReconcilerError(ValueError):
    """Base error for filing receipt reconciliation failures."""

    def __init__(self, message: str, *, code: str = "reconciler_error") -> None:
        super().__init__(message)
        self.code = code

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


class ForbiddenReconcilerInterfaceError(FilingReceiptReconcilerError):
    """Raised when a forbidden capability is requested."""

    def __init__(self, interface: str, message: str | None = None) -> None:
        iface = str(interface)
        super().__init__(
            message
            or (
                f"reconciler forbids interface {iface!r}: no network, browser, "
                "session, payment, signature, fabrication, or private-content "
                "logging surface exists"
            ),
            code="forbidden_reconciler_interface",
        )
        self.interface = iface


class FabricatedEvidenceError(FilingReceiptReconcilerError):
    """Raised when fabricated acknowledgement/payment evidence is supplied."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="fabricated_evidence")


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
    return _require_str(value, field, max_len=max_len)


def _identifier(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _ID_RE.match(text):
        raise ValueError(f"{field} has invalid identifier shape")
    return text


def _optional_identifier(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, field)


def _sha256_hex_field(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    lowered = text.lower()
    if not _SHA256_RE.match(lowered):
        raise ValueError(f"{field} must be a 64-char lowercase hex sha256")
    return lowered


def _optional_sha256(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _sha256_hex_field(value, field)


def _iso_utc(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    if not _ISO_UTC_RE.match(text):
        raise ValueError(f"{field} must be ISO-8601 UTC timestamp")
    return text


def _optional_iso_utc(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _iso_utc(value, field)


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value)
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    if isinstance(value, str):
        try:
            return DisclosureClassification(value)
        except ValueError as exc:
            raise ValueError(f"invalid classification: {value!r}") from exc
    raise TypeError("classification must be DisclosureClassification or str")


def _tuple_of_str(
    value: Any, field: str, *, max_items: int = 256
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise TypeError(f"{field} must be a sequence of str, not str")
    if not isinstance(value, Sequence):
        raise TypeError(f"{field} must be a sequence of str")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: list[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise TypeError(f"{field}[{i}] must be str")
        text = item.strip()
        if not text:
            raise ValueError(f"{field}[{i}] must be non-empty")
        if len(text) > 512:
            raise ValueError(f"{field}[{i}] exceeds max length 512")
        out.append(text)
    return tuple(out)


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
    for k, v in value.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise TypeError(f"{field} keys and values must be str")
        ks, vs = k.strip(), v.strip()
        if not ks:
            raise ValueError(f"{field} key must be non-empty")
        out[ks] = vs
    return MappingProxyType(out)


def _optional_nonneg_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int or None")
    if value < 0:
        raise ValueError(f"{field} must be non-negative")
    return value


def _normalize_identifier_token(value: str | None) -> str | None:
    """Normalize identity tokens for comparison (strip, collapse whitespace)."""
    if value is None:
        return None
    text = re.sub(r"\s+", "", value.strip())
    return text or None


def _default_id_factory() -> str:
    return uuid.uuid4().hex[:12]


def normalize_interface_name(name: str) -> str:
    return _require_str(name, "interface", max_len=128).lower().replace(" ", "_")


def assert_interface_allowed(interface: str) -> None:
    key = normalize_interface_name(interface)
    if key in FORBIDDEN_RECONCILER_INTERFACES:
        raise ForbiddenReconcilerInterfaceError(key)
    for token in (
        "network",
        "browser",
        "selenium",
        "playwright",
        "session_cookie",
        "payment",
        "pay_fee",
        "fabricate_receipt",
        "log_private",
        "automate_patent_center",
    ):
        if token in key:
            raise ForbiddenReconcilerInterfaceError(key)


def is_forbidden_interface(interface: str) -> bool:
    try:
        assert_interface_allowed(interface)
    except ForbiddenReconcilerInterfaceError:
        return True
    except (TypeError, ValueError):
        return True
    return False


def prove_no_forbidden_interfaces() -> dict[str, Any]:
    """Content-free proof that forbidden interfaces are closed."""
    rejected = 0
    for iface in sorted(FORBIDDEN_RECONCILER_INTERFACES):
        try:
            assert_interface_allowed(iface)
        except ForbiddenReconcilerInterfaceError:
            rejected += 1
    return {
        "closed": {
            "browser": True,
            "network": True,
            "payment": True,
            "private_content_logging": True,
            "session": True,
        },
        "no_network_browser_session_payment": True,
        "rejected_count": rejected,
    }


# ---------------------------------------------------------------------------
# Input records (content-free metadata only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SubmittedFileBinding:
    """One submitted package file bound by content digest (no body bytes)."""

    filename: str
    content_digest: str
    role: str | None = None
    media_kind: str | None = None
    byte_size: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "filename", _require_str(self.filename, "filename", max_len=512)
        )
        object.__setattr__(
            self,
            "content_digest",
            _sha256_hex_field(self.content_digest, "content_digest"),
        )
        object.__setattr__(
            self, "role", _optional_str(self.role, "role", max_len=128)
        )
        object.__setattr__(
            self,
            "media_kind",
            _optional_str(self.media_kind, "media_kind", max_len=64),
        )
        object.__setattr__(
            self, "byte_size", _optional_nonneg_int(self.byte_size, "byte_size")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "byte_size": self.byte_size,
            "content_digest": self.content_digest,
            "filename": self.filename,
            "media_kind": self.media_kind,
            "role": self.role,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SubmittedFileBinding":
        if not isinstance(value, Mapping):
            raise TypeError("SubmittedFileBinding must be a mapping")
        return cls(
            filename=value.get("filename", ""),
            content_digest=value.get("content_digest", ""),
            role=value.get("role"),
            media_kind=value.get("media_kind"),
            byte_size=value.get("byte_size"),
        )


@dataclass(frozen=True, slots=True)
class SubmittedPackageBinding:
    """Approved/submitted package identity from human handoff (PATLAW-154)."""

    matter_id: str
    package_id: str
    package_digest: str
    submitted_digest: str
    files: tuple[SubmittedFileBinding, ...]
    application_number: str | None = None
    customer_number: str | None = None
    confirmation_number: str | None = None
    document_count: int | None = None
    submitted_at_utc: str | None = None
    handoff_id: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "matter_id", _identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self, "package_id", _identifier(self.package_id, "package_id")
        )
        object.__setattr__(
            self,
            "package_digest",
            _sha256_hex_field(self.package_digest, "package_digest"),
        )
        object.__setattr__(
            self,
            "submitted_digest",
            _sha256_hex_field(self.submitted_digest, "submitted_digest"),
        )
        files = tuple(self.files or ())
        if len(files) > DEFAULT_MAX_FILES:
            raise FilingReceiptReconcilerError(
                "files exceeds max", code="too_many_files"
            )
        coerced: list[SubmittedFileBinding] = []
        for i, f in enumerate(files):
            if isinstance(f, SubmittedFileBinding):
                coerced.append(f)
            elif isinstance(f, Mapping):
                coerced.append(SubmittedFileBinding.from_dict(f))
            else:
                raise TypeError(
                    f"files[{i}] must be SubmittedFileBinding or mapping"
                )
        object.__setattr__(self, "files", tuple(coerced))
        object.__setattr__(
            self,
            "application_number",
            _optional_str(self.application_number, "application_number", max_len=64),
        )
        object.__setattr__(
            self,
            "customer_number",
            _optional_str(self.customer_number, "customer_number", max_len=64),
        )
        object.__setattr__(
            self,
            "confirmation_number",
            _optional_str(
                self.confirmation_number, "confirmation_number", max_len=128
            ),
        )
        doc_count = self.document_count
        if doc_count is None:
            doc_count = len(coerced) if coerced else None
        object.__setattr__(
            self, "document_count", _optional_nonneg_int(doc_count, "document_count")
        )
        object.__setattr__(
            self,
            "submitted_at_utc",
            _optional_iso_utc(self.submitted_at_utc, "submitted_at_utc"),
        )
        object.__setattr__(
            self, "handoff_id", _optional_identifier(self.handoff_id, "handoff_id")
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def file_digest_map(self) -> Mapping[str, str]:
        return MappingProxyType({f.filename: f.content_digest for f in self.files})

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_number": self.application_number,
            "confirmation_number": self.confirmation_number,
            "customer_number": self.customer_number,
            "document_count": self.document_count,
            "files": [f.to_dict() for f in self.files],
            "handoff_id": self.handoff_id,
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "package_digest": self.package_digest,
            "package_id": self.package_id,
            "submitted_at_utc": self.submitted_at_utc,
            "submitted_digest": self.submitted_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SubmittedPackageBinding":
        if not isinstance(value, Mapping):
            raise TypeError("SubmittedPackageBinding must be a mapping")
        return cls(
            matter_id=value.get("matter_id", ""),
            package_id=value.get("package_id", ""),
            package_digest=value.get("package_digest", ""),
            submitted_digest=value.get("submitted_digest", ""),
            files=tuple(value.get("files") or ()),
            application_number=value.get("application_number"),
            customer_number=value.get("customer_number"),
            confirmation_number=value.get("confirmation_number"),
            document_count=value.get("document_count"),
            submitted_at_utc=value.get("submitted_at_utc"),
            handoff_id=value.get("handoff_id"),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class ImportedEvidence:
    """User-imported official artifact metadata (never fabricated, no body)."""

    artifact_id: str
    role: EvidenceRole | str
    content_digest: str
    package_digest: str
    verified: bool = False
    fabricated: bool = False
    matter_id: str | None = None
    application_number: str | None = None
    customer_number: str | None = None
    confirmation_number: str | None = None
    filename: str | None = None
    observed_at_utc: str | None = None
    document_count: int | None = None
    listed_files: tuple[SubmittedFileBinding, ...] = ()
    source_receipt_id: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self, "role", _coerce_enum(EvidenceRole, self.role, "role")
        )
        object.__setattr__(
            self,
            "content_digest",
            _sha256_hex_field(self.content_digest, "content_digest"),
        )
        object.__setattr__(
            self,
            "package_digest",
            _sha256_hex_field(self.package_digest, "package_digest"),
        )
        if not isinstance(self.verified, bool):
            raise TypeError("verified must be bool")
        if not isinstance(self.fabricated, bool):
            raise TypeError("fabricated must be bool")
        if self.fabricated:
            raise FabricatedEvidenceError(
                "official evidence must be user-imported; fabrication is forbidden"
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
            self,
            "customer_number",
            _optional_str(self.customer_number, "customer_number", max_len=64),
        )
        object.__setattr__(
            self,
            "confirmation_number",
            _optional_str(
                self.confirmation_number, "confirmation_number", max_len=128
            ),
        )
        object.__setattr__(
            self, "filename", _optional_str(self.filename, "filename", max_len=512)
        )
        object.__setattr__(
            self,
            "observed_at_utc",
            _optional_iso_utc(self.observed_at_utc, "observed_at_utc"),
        )
        object.__setattr__(
            self,
            "document_count",
            _optional_nonneg_int(self.document_count, "document_count"),
        )
        listed = tuple(self.listed_files or ())
        if len(listed) > DEFAULT_MAX_FILES:
            raise FilingReceiptReconcilerError(
                "listed_files exceeds max", code="too_many_listed_files"
            )
        coerced: list[SubmittedFileBinding] = []
        for i, f in enumerate(listed):
            if isinstance(f, SubmittedFileBinding):
                coerced.append(f)
            elif isinstance(f, Mapping):
                coerced.append(SubmittedFileBinding.from_dict(f))
            else:
                raise TypeError(
                    f"listed_files[{i}] must be SubmittedFileBinding or mapping"
                )
        object.__setattr__(self, "listed_files", tuple(coerced))
        object.__setattr__(
            self,
            "source_receipt_id",
            _optional_identifier(self.source_receipt_id, "source_receipt_id"),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def binds_package_digest(self, package_digest: str) -> bool:
        return self.package_digest == _sha256_hex_field(
            package_digest, "package_digest"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_number": self.application_number,
            "artifact_id": self.artifact_id,
            "confirmation_number": self.confirmation_number,
            "content_digest": self.content_digest,
            "customer_number": self.customer_number,
            "document_count": self.document_count,
            "fabricated": self.fabricated,
            "filename": self.filename,
            "labels": dict(self.labels),
            "listed_files": [f.to_dict() for f in self.listed_files],
            "matter_id": self.matter_id,
            "observed_at_utc": self.observed_at_utc,
            "package_digest": self.package_digest,
            "role": self.role.value
            if isinstance(self.role, EvidenceRole)
            else str(self.role),
            "source_receipt_id": self.source_receipt_id,
            "verified": self.verified,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ImportedEvidence":
        if not isinstance(value, Mapping):
            raise TypeError("ImportedEvidence must be a mapping")
        return cls(
            artifact_id=value.get("artifact_id", ""),
            role=value.get("role", EvidenceRole.OTHER.value),
            content_digest=value.get("content_digest", ""),
            package_digest=value.get("package_digest", ""),
            verified=bool(value.get("verified", False)),
            fabricated=bool(value.get("fabricated", False)),
            matter_id=value.get("matter_id"),
            application_number=value.get("application_number"),
            customer_number=value.get("customer_number"),
            confirmation_number=value.get("confirmation_number"),
            filename=value.get("filename"),
            observed_at_utc=value.get("observed_at_utc"),
            document_count=value.get("document_count"),
            listed_files=tuple(value.get("listed_files") or ()),
            source_receipt_id=value.get("source_receipt_id"),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class ConvertedArtifactBinding:
    """USPTO-converted artifact compared to a submitted original.

    When digests differ, *disclosed_differences* must list content-free codes
    describing the expected conversion (e.g. ``media_kind:docx->pdf``).
    """

    artifact_id: str
    content_digest: str
    package_digest: str
    source_filename: str | None = None
    source_digest: str | None = None
    converted_filename: str | None = None
    matter_id: str | None = None
    expected_conversion: bool = False
    disclosed_differences: tuple[str, ...] = ()
    verified: bool = False
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "content_digest",
            _sha256_hex_field(self.content_digest, "content_digest"),
        )
        object.__setattr__(
            self,
            "package_digest",
            _sha256_hex_field(self.package_digest, "package_digest"),
        )
        object.__setattr__(
            self,
            "source_filename",
            _optional_str(self.source_filename, "source_filename", max_len=512),
        )
        object.__setattr__(
            self,
            "source_digest",
            _optional_sha256(self.source_digest, "source_digest"),
        )
        object.__setattr__(
            self,
            "converted_filename",
            _optional_str(
                self.converted_filename, "converted_filename", max_len=512
            ),
        )
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        if not isinstance(self.expected_conversion, bool):
            raise TypeError("expected_conversion must be bool")
        object.__setattr__(
            self,
            "disclosed_differences",
            _tuple_of_str(
                self.disclosed_differences,
                "disclosed_differences",
                max_items=DEFAULT_MAX_DIFFERENCES,
            ),
        )
        if not isinstance(self.verified, bool):
            raise TypeError("verified must be bool")
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "content_digest": self.content_digest,
            "converted_filename": self.converted_filename,
            "disclosed_differences": list(self.disclosed_differences),
            "expected_conversion": self.expected_conversion,
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "package_digest": self.package_digest,
            "source_digest": self.source_digest,
            "source_filename": self.source_filename,
            "verified": self.verified,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConvertedArtifactBinding":
        if not isinstance(value, Mapping):
            raise TypeError("ConvertedArtifactBinding must be a mapping")
        return cls(
            artifact_id=value.get("artifact_id", ""),
            content_digest=value.get("content_digest", ""),
            package_digest=value.get("package_digest", ""),
            source_filename=value.get("source_filename"),
            source_digest=value.get("source_digest"),
            converted_filename=value.get("converted_filename"),
            matter_id=value.get("matter_id"),
            expected_conversion=bool(value.get("expected_conversion", False)),
            disclosed_differences=tuple(value.get("disclosed_differences") or ()),
            verified=bool(value.get("verified", False)),
            labels=value.get("labels") or {},
        )


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IdentifierCheck:
    field: str
    match: IdentifierMatchKind | str
    expected: str | None = None
    observed: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "field", _require_str(self.field, "field", max_len=64)
        )
        object.__setattr__(
            self, "match", _coerce_enum(IdentifierMatchKind, self.match, "match")
        )
        object.__setattr__(
            self, "expected", _optional_str(self.expected, "expected", max_len=128)
        )
        object.__setattr__(
            self, "observed", _optional_str(self.observed, "observed", max_len=128)
        )

    @property
    def is_conflict(self) -> bool:
        return self.match is IdentifierMatchKind.MISMATCH

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected": self.expected,
            "field": self.field,
            "match": self.match.value
            if isinstance(self.match, IdentifierMatchKind)
            else str(self.match),
            "observed": self.observed,
        }


@dataclass(frozen=True, slots=True)
class FileCheck:
    filename: str
    match: FileMatchKind | str
    expected_digest: str | None = None
    observed_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "filename", _require_str(self.filename, "filename", max_len=512)
        )
        object.__setattr__(
            self, "match", _coerce_enum(FileMatchKind, self.match, "match")
        )
        object.__setattr__(
            self,
            "expected_digest",
            _optional_sha256(self.expected_digest, "expected_digest"),
        )
        object.__setattr__(
            self,
            "observed_digest",
            _optional_sha256(self.observed_digest, "observed_digest"),
        )

    @property
    def is_conflict(self) -> bool:
        return self.match in (
            FileMatchKind.DIGEST_MISMATCH,
            FileMatchKind.MISSING_FROM_RECEIPT,
            FileMatchKind.UNEXPECTED_ON_RECEIPT,
            FileMatchKind.PARTIAL,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_digest": self.expected_digest,
            "filename": self.filename,
            "match": self.match.value
            if isinstance(self.match, FileMatchKind)
            else str(self.match),
            "observed_digest": self.observed_digest,
        }


@dataclass(frozen=True, slots=True)
class ConversionCheck:
    artifact_id: str
    match: ConversionMatchKind | str
    source_filename: str | None = None
    disclosed_differences: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self, "match", _coerce_enum(ConversionMatchKind, self.match, "match")
        )
        object.__setattr__(
            self,
            "source_filename",
            _optional_str(self.source_filename, "source_filename", max_len=512),
        )
        object.__setattr__(
            self,
            "disclosed_differences",
            _tuple_of_str(
                self.disclosed_differences,
                "disclosed_differences",
                max_items=DEFAULT_MAX_DIFFERENCES,
            ),
        )

    @property
    def is_conflict(self) -> bool:
        return self.match in (
            ConversionMatchKind.MISMATCHED,
            ConversionMatchKind.UNEXPECTED,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "disclosed_differences": list(self.disclosed_differences),
            "match": self.match.value
            if isinstance(self.match, ConversionMatchKind)
            else str(self.match),
            "source_filename": self.source_filename,
        }


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Immutable content-free reconciliation outcome."""

    reconciliation_id: str
    matter_id: str
    package_id: str
    package_digest: str
    disposition: ReconciliationDisposition | str
    filed_status_eligibility: FiledStatusEligibility | str
    schema_version: str = RECONCILER_SCHEMA_VERSION
    output_kind: str = OUTPUT_KIND_RECONCILIATION
    policy_id: str = RULESET_VERSION
    has_authoritative_acknowledgement: bool = False
    has_payment_receipt: bool = False
    identifier_checks: tuple[IdentifierCheck, ...] = ()
    file_checks: tuple[FileCheck, ...] = ()
    conversion_checks: tuple[ConversionCheck, ...] = ()
    disclosed_differences: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    related_artifact_ids: tuple[str, ...] = ()
    ledger_event_id: str | None = None
    review_state: ReviewState | str = ReviewState.REQUIRED
    classification: DisclosureClassification | str = (
        DisclosureClassification.CONFIDENTIAL_APPLICATION
    )
    reconciled_at_utc: str | None = None
    content_digest: str = ""
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reconciliation_id",
            _identifier(self.reconciliation_id, "reconciliation_id"),
        )
        object.__setattr__(
            self, "matter_id", _identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self, "package_id", _identifier(self.package_id, "package_id")
        )
        object.__setattr__(
            self,
            "package_digest",
            _sha256_hex_field(self.package_digest, "package_digest"),
        )
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(ReconciliationDisposition, self.disposition, "disposition"),
        )
        object.__setattr__(
            self,
            "filed_status_eligibility",
            _coerce_enum(
                FiledStatusEligibility,
                self.filed_status_eligibility,
                "filed_status_eligibility",
            ),
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != RECONCILER_SCHEMA_VERSION:
            raise FilingReceiptReconcilerError(
                f"schema_version must be {RECONCILER_SCHEMA_VERSION!r}",
                code="invalid_schema_version",
            )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        object.__setattr__(
            self, "policy_id", _require_str(self.policy_id, "policy_id", max_len=128)
        )
        if not isinstance(self.has_authoritative_acknowledgement, bool):
            raise TypeError("has_authoritative_acknowledgement must be bool")
        if not isinstance(self.has_payment_receipt, bool):
            raise TypeError("has_payment_receipt must be bool")
        object.__setattr__(
            self,
            "identifier_checks",
            tuple(self.identifier_checks or ()),
        )
        object.__setattr__(self, "file_checks", tuple(self.file_checks or ()))
        object.__setattr__(
            self, "conversion_checks", tuple(self.conversion_checks or ())
        )
        object.__setattr__(
            self,
            "disclosed_differences",
            _tuple_of_str(
                self.disclosed_differences,
                "disclosed_differences",
                max_items=DEFAULT_MAX_DIFFERENCES,
            ),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(
                self.reason_codes, "reason_codes", max_items=DEFAULT_MAX_REASON_CODES
            ),
        )
        object.__setattr__(
            self,
            "warnings",
            _tuple_of_str(self.warnings, "warnings", max_items=DEFAULT_MAX_WARNINGS),
        )
        object.__setattr__(
            self,
            "related_artifact_ids",
            _tuple_of_str(
                self.related_artifact_ids, "related_artifact_ids", max_items=256
            ),
        )
        object.__setattr__(
            self,
            "ledger_event_id",
            _optional_identifier(self.ledger_event_id, "ledger_event_id"),
        )
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        object.__setattr__(
            self,
            "classification",
            _coerce_classification(self.classification),
        )
        object.__setattr__(
            self,
            "reconciled_at_utc",
            _optional_iso_utc(self.reconciled_at_utc, "reconciled_at_utc"),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )
        material = self.material_payload()
        digest = sha256_hex(canonical_json(material))
        if self.content_digest:
            existing = _sha256_hex_field(self.content_digest, "content_digest")
            if existing != digest:
                raise FilingReceiptReconcilerError(
                    "content_digest does not match reconciliation material",
                    code="content_digest_mismatch",
                )
            object.__setattr__(self, "content_digest", existing)
        else:
            object.__setattr__(self, "content_digest", digest)

    def material_payload(self) -> dict[str, Any]:
        return {
            "classification": self.classification.value
            if isinstance(self.classification, DisclosureClassification)
            else str(self.classification),
            "conversion_checks": [c.to_dict() for c in self.conversion_checks],
            "disclosed_differences": list(self.disclosed_differences),
            "disposition": self.disposition.value
            if isinstance(self.disposition, ReconciliationDisposition)
            else str(self.disposition),
            "file_checks": [f.to_dict() for f in self.file_checks],
            "filed_status_eligibility": self.filed_status_eligibility.value
            if isinstance(self.filed_status_eligibility, FiledStatusEligibility)
            else str(self.filed_status_eligibility),
            "has_authoritative_acknowledgement": (
                self.has_authoritative_acknowledgement
            ),
            "has_payment_receipt": self.has_payment_receipt,
            "identifier_checks": [i.to_dict() for i in self.identifier_checks],
            "labels": dict(self.labels),
            "ledger_event_id": self.ledger_event_id,
            "matter_id": self.matter_id,
            "output_kind": self.output_kind,
            "package_digest": self.package_digest,
            "package_id": self.package_id,
            "policy_id": self.policy_id,
            "reason_codes": list(self.reason_codes),
            "reconciled_at_utc": self.reconciled_at_utc,
            "reconciliation_id": self.reconciliation_id,
            "related_artifact_ids": list(self.related_artifact_ids),
            "review_state": self.review_state.value
            if isinstance(self.review_state, ReviewState)
            else str(self.review_state),
            "schema_version": self.schema_version,
            "warnings": list(self.warnings),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.material_payload()
        payload["content_digest"] = self.content_digest
        return payload

    @property
    def is_verified(self) -> bool:
        return self.disposition in (
            ReconciliationDisposition.VERIFIED,
            ReconciliationDisposition.VERIFIED_WITH_DISCLOSED_DIFFERENCES,
        )

    @property
    def may_assert_filed_status(self) -> bool:
        return (
            self.filed_status_eligibility is FiledStatusEligibility.ELIGIBLE
            and self.has_authoritative_acknowledgement
            and self.is_verified
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReconciliationResult":
        if not isinstance(value, Mapping):
            raise TypeError("ReconciliationResult must be a mapping")
        id_checks = tuple(
            IdentifierCheck(
                field=i.get("field", ""),
                match=i.get("match", IdentifierMatchKind.ABSENT_BOTH.value),
                expected=i.get("expected"),
                observed=i.get("observed"),
            )
            for i in (value.get("identifier_checks") or ())
            if isinstance(i, Mapping)
        )
        file_checks = tuple(
            FileCheck(
                filename=f.get("filename", ""),
                match=f.get("match", FileMatchKind.PARTIAL.value),
                expected_digest=f.get("expected_digest"),
                observed_digest=f.get("observed_digest"),
            )
            for f in (value.get("file_checks") or ())
            if isinstance(f, Mapping)
        )
        conv_checks = tuple(
            ConversionCheck(
                artifact_id=c.get("artifact_id", ""),
                match=c.get("match", ConversionMatchKind.NOT_APPLICABLE.value),
                source_filename=c.get("source_filename"),
                disclosed_differences=tuple(c.get("disclosed_differences") or ()),
            )
            for c in (value.get("conversion_checks") or ())
            if isinstance(c, Mapping)
        )
        return cls(
            reconciliation_id=value.get("reconciliation_id", ""),
            matter_id=value.get("matter_id", ""),
            package_id=value.get("package_id", ""),
            package_digest=value.get("package_digest", ""),
            disposition=value.get(
                "disposition", ReconciliationDisposition.INCOMPLETE.value
            ),
            filed_status_eligibility=value.get(
                "filed_status_eligibility",
                FiledStatusEligibility.BLOCKED.value,
            ),
            schema_version=value.get("schema_version", RECONCILER_SCHEMA_VERSION),
            output_kind=value.get("output_kind", OUTPUT_KIND_RECONCILIATION),
            policy_id=value.get("policy_id", RULESET_VERSION),
            has_authoritative_acknowledgement=bool(
                value.get("has_authoritative_acknowledgement", False)
            ),
            has_payment_receipt=bool(value.get("has_payment_receipt", False)),
            identifier_checks=id_checks,
            file_checks=file_checks,
            conversion_checks=conv_checks,
            disclosed_differences=tuple(value.get("disclosed_differences") or ()),
            reason_codes=tuple(value.get("reason_codes") or ()),
            warnings=tuple(value.get("warnings") or ()),
            related_artifact_ids=tuple(value.get("related_artifact_ids") or ()),
            ledger_event_id=value.get("ledger_event_id"),
            review_state=value.get("review_state", ReviewState.REQUIRED.value),
            classification=value.get(
                "classification",
                DisclosureClassification.CONFIDENTIAL_APPLICATION.value,
            ),
            reconciled_at_utc=value.get("reconciled_at_utc"),
            content_digest=value.get("content_digest", ""),
            labels=value.get("labels") or {},
        )


# ---------------------------------------------------------------------------
# Authoritative acknowledgement rule
# ---------------------------------------------------------------------------


def has_authoritative_acknowledgement(
    evidence: Sequence[ImportedEvidence],
    *,
    package_digest: str,
    policy: AuthoritativeAcknowledgementPolicy | None = None,
) -> bool:
    """Return True when evidence satisfies the reviewed acknowledgement rule.

    Requires at least one non-fabricated, verified acknowledgement bound to
    *package_digest*. Payment-only is always insufficient under the default
    policy.
    """
    pol = policy or DEFAULT_ACKNOWLEDGEMENT_POLICY
    digest = _sha256_hex_field(package_digest, "package_digest")
    for art in evidence:
        if not isinstance(art, ImportedEvidence):
            continue
        if art.fabricated:
            continue
        if not art.verified:
            continue
        if art.role is not EvidenceRole.ACKNOWLEDGEMENT:
            continue
        if pol.acknowledgement_must_bind_package_digest and not art.binds_package_digest(
            digest
        ):
            continue
        return True
    return False


def payment_only_evidence(evidence: Sequence[ImportedEvidence]) -> bool:
    """True when payment receipts exist but no acknowledgement role is present."""
    roles = {
        e.role
        for e in evidence
        if isinstance(e, ImportedEvidence) and not e.fabricated
    }
    has_pay = EvidenceRole.PAYMENT_RECEIPT in roles
    has_ack = EvidenceRole.ACKNOWLEDGEMENT in roles
    return has_pay and not has_ack


# ---------------------------------------------------------------------------
# Reconciler
# ---------------------------------------------------------------------------


class FilingReceiptReconciler:
    """Cross-check official receipts/converted artifacts against a package.

    Pure evaluation plus optional immutable ledger append. Never logs private
    document content.
    """

    interface: Final = RECONCILER_INTERFACE
    schema_version: Final = RECONCILER_SCHEMA_VERSION

    def __init__(
        self,
        *,
        policy: AuthoritativeAcknowledgementPolicy | None = None,
        ledger: MatterLedger | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._policy = policy or DEFAULT_ACKNOWLEDGEMENT_POLICY
        self._ledger = ledger
        self._id_factory = id_factory or _default_id_factory

    @property
    def policy(self) -> AuthoritativeAcknowledgementPolicy:
        return self._policy

    def assert_capability_allowed(self, interface: str) -> None:
        assert_interface_allowed(interface)

    def has_network_interface(self) -> bool:
        return False

    def has_browser_interface(self) -> bool:
        return False

    def has_session_interface(self) -> bool:
        return False

    def has_payment_interface(self) -> bool:
        return False

    # Forbidden method surface — always fail closed.
    def login(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenReconcilerInterfaceError("network_login")

    def open_browser(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenReconcilerInterfaceError("browser")

    def pay(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenReconcilerInterfaceError("payment")

    def pay_fee(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenReconcilerInterfaceError("pay_fee")

    def fabricate_acknowledgement(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenReconcilerInterfaceError("fabricate_acknowledgement")

    def fabricate_payment_receipt(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenReconcilerInterfaceError("fabricate_payment_receipt")

    def fabricate_receipt(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenReconcilerInterfaceError("fabricate_receipt")

    def log_private_content(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenReconcilerInterfaceError("log_private_content")

    def reconcile(
        self,
        package: SubmittedPackageBinding | Mapping[str, Any],
        evidence: Sequence[ImportedEvidence | Mapping[str, Any]] = (),
        converted: Sequence[ConvertedArtifactBinding | Mapping[str, Any]] = (),
        *,
        reconciled_at_utc: str | None = None,
        append_to_ledger: bool = True,
        classification: DisclosureClassification | str = (
            DisclosureClassification.CONFIDENTIAL_APPLICATION
        ),
        labels: Mapping[str, str] | None = None,
    ) -> ReconciliationResult:
        """Reconcile imported receipts/conversions against *package*.

        Returns a content-free :class:`ReconciliationResult`. When a ledger is
        configured and *append_to_ledger* is True, appends an immutable filing
        event with only digests, identifiers, and reason codes in metadata.
        """
        pkg = (
            package
            if isinstance(package, SubmittedPackageBinding)
            else SubmittedPackageBinding.from_dict(package)
        )
        evs = self._coerce_evidence(evidence)
        convs = self._coerce_converted(converted)
        at = (
            _iso_utc(reconciled_at_utc, "reconciled_at_utc")
            if reconciled_at_utc
            else None
        )
        reason_codes: list[str] = [
            ReconciliationReasonCode.CONTENT_FREE_RESULT.value
        ]
        warnings: list[str] = []
        related: list[str] = []

        # --- package digest consistency ------------------------------------
        conflict = False
        incomplete = False
        if (
            self._policy.require_submitted_digest_match
            and pkg.submitted_digest != pkg.package_digest
        ):
            conflict = True
            reason_codes.append(
                ReconciliationReasonCode.SUBMITTED_DIGEST_MISMATCH.value
            )

        # --- evidence role inventory ---------------------------------------
        has_pay = any(
            e.role is EvidenceRole.PAYMENT_RECEIPT and e.verified for e in evs
        )
        if has_pay:
            reason_codes.append(
                ReconciliationReasonCode.PAYMENT_RECEIPT_PRESENT.value
            )

        if not evs and not convs:
            incomplete = True
            reason_codes.append(ReconciliationReasonCode.NO_EVIDENCE.value)

        # Fabricated should already raise at construction; double-check.
        for e in evs:
            if e.fabricated:
                conflict = True
                reason_codes.append(
                    ReconciliationReasonCode.FABRICATED_EVIDENCE_REJECTED.value
                )

        # --- wrong matter / package digest binding -------------------------
        for e in evs:
            related.append(e.artifact_id)
            if e.matter_id is not None and e.matter_id != pkg.matter_id:
                conflict = True
                reason_codes.append(ReconciliationReasonCode.WRONG_MATTER.value)
            if not e.binds_package_digest(pkg.package_digest):
                conflict = True
                reason_codes.append(
                    ReconciliationReasonCode.PACKAGE_DIGEST_MISMATCH.value
                )

        for c in convs:
            related.append(c.artifact_id)
            if c.matter_id is not None and c.matter_id != pkg.matter_id:
                conflict = True
                reason_codes.append(ReconciliationReasonCode.WRONG_MATTER.value)
            if c.package_digest != pkg.package_digest:
                conflict = True
                reason_codes.append(
                    ReconciliationReasonCode.PACKAGE_DIGEST_MISMATCH.value
                )

        # --- authoritative acknowledgement ---------------------------------
        has_auth_ack = has_authoritative_acknowledgement(
            evs, package_digest=pkg.package_digest, policy=self._policy
        )
        if has_auth_ack:
            reason_codes.append(
                ReconciliationReasonCode.AUTHORITATIVE_ACKNOWLEDGEMENT_PRESENT.value
            )
        else:
            # Distinguish payment-only, unverified ack, and missing ack.
            if payment_only_evidence(evs) and self._policy.payment_receipt_alone_insufficient:
                incomplete = True
                reason_codes.append(
                    ReconciliationReasonCode.PAYMENT_ONLY_INSUFFICIENT.value
                )
            elif any(
                e.role is EvidenceRole.ACKNOWLEDGEMENT and not e.verified for e in evs
            ):
                incomplete = True
                reason_codes.append(
                    ReconciliationReasonCode.UNVERIFIED_ACKNOWLEDGEMENT.value
                )
            else:
                incomplete = True
                reason_codes.append(
                    ReconciliationReasonCode.AUTHORITATIVE_ACKNOWLEDGEMENT_MISSING.value
                )

        # --- identifier cross-check ----------------------------------------
        id_checks = self._check_identifiers(pkg, evs, reason_codes)
        if any(c.is_conflict for c in id_checks):
            conflict = True

        # --- file / document-count cross-check -----------------------------
        file_checks, file_conflict, file_incomplete, partial = self._check_files(
            pkg, evs, reason_codes
        )
        if file_conflict:
            conflict = True
        if file_incomplete or partial:
            incomplete = True

        # --- conversion differences ----------------------------------------
        conv_checks, disclosed, conv_conflict, has_expected = self._check_conversions(
            pkg, convs, reason_codes
        )
        if conv_conflict:
            conflict = True

        # --- disposition / filed eligibility --------------------------------
        disposition, filed = self._resolve_disposition(
            conflict=conflict,
            incomplete=incomplete,
            has_auth_ack=has_auth_ack,
            has_expected_conversion=has_expected,
            disclosed=disclosed,
            reason_codes=reason_codes,
        )

        review = (
            ReviewState.COMPLETE
            if disposition
            in (
                ReconciliationDisposition.VERIFIED,
                ReconciliationDisposition.VERIFIED_WITH_DISCLOSED_DIFFERENCES,
            )
            and filed is FiledStatusEligibility.ELIGIBLE
            else ReviewState.REQUIRED
        )
        if review is ReviewState.REQUIRED:
            reason_codes.append(ReconciliationReasonCode.REVIEW_REQUIRED.value)

        # Deduplicate reason codes while preserving order.
        reason_codes = list(dict.fromkeys(reason_codes))
        related = list(dict.fromkeys(related))

        recon_id = f"recon:{self._id_factory()}"
        result = ReconciliationResult(
            reconciliation_id=recon_id,
            matter_id=pkg.matter_id,
            package_id=pkg.package_id,
            package_digest=pkg.package_digest,
            disposition=disposition,
            filed_status_eligibility=filed,
            policy_id=self._policy.policy_id,
            has_authoritative_acknowledgement=has_auth_ack,
            has_payment_receipt=has_pay,
            identifier_checks=tuple(id_checks),
            file_checks=tuple(file_checks),
            conversion_checks=tuple(conv_checks),
            disclosed_differences=tuple(disclosed),
            reason_codes=tuple(reason_codes),
            warnings=tuple(dict.fromkeys(warnings)),
            related_artifact_ids=tuple(related),
            review_state=review,
            classification=classification,
            reconciled_at_utc=at,
            labels=labels or {},
        )

        if append_to_ledger and self._ledger is not None:
            result = self._append_ledger_event(result, pkg=pkg, at=at)

        return result

    # -- internal helpers ---------------------------------------------------

    def _coerce_evidence(
        self, evidence: Sequence[ImportedEvidence | Mapping[str, Any]]
    ) -> list[ImportedEvidence]:
        out: list[ImportedEvidence] = []
        if len(evidence) > DEFAULT_MAX_EVIDENCE:
            raise FilingReceiptReconcilerError(
                "evidence exceeds max", code="too_much_evidence"
            )
        for i, item in enumerate(evidence):
            if isinstance(item, ImportedEvidence):
                out.append(item)
            elif isinstance(item, Mapping):
                out.append(ImportedEvidence.from_dict(item))
            else:
                raise TypeError(
                    f"evidence[{i}] must be ImportedEvidence or mapping"
                )
        return out

    def _coerce_converted(
        self, converted: Sequence[ConvertedArtifactBinding | Mapping[str, Any]]
    ) -> list[ConvertedArtifactBinding]:
        out: list[ConvertedArtifactBinding] = []
        if len(converted) > DEFAULT_MAX_EVIDENCE:
            raise FilingReceiptReconcilerError(
                "converted exceeds max", code="too_many_conversions"
            )
        for i, item in enumerate(converted):
            if isinstance(item, ConvertedArtifactBinding):
                out.append(item)
            elif isinstance(item, Mapping):
                out.append(ConvertedArtifactBinding.from_dict(item))
            else:
                raise TypeError(
                    f"converted[{i}] must be ConvertedArtifactBinding or mapping"
                )
        return out

    def _check_identifiers(
        self,
        pkg: SubmittedPackageBinding,
        evs: Sequence[ImportedEvidence],
        reason_codes: list[str],
    ) -> list[IdentifierCheck]:
        checks: list[IdentifierCheck] = []
        fields = (
            ("application_number", pkg.application_number, "APPLICATION_NUMBER_MISMATCH"),
            ("customer_number", pkg.customer_number, "CUSTOMER_NUMBER_MISMATCH"),
            (
                "confirmation_number",
                pkg.confirmation_number,
                "CONFIRMATION_NUMBER_MISMATCH",
            ),
        )
        # Prefer acknowledgement evidence for observed identifiers.
        ack_sources = [
            e for e in evs if e.role is EvidenceRole.ACKNOWLEDGEMENT
        ] or list(evs)

        for field, expected_raw, reason_attr in fields:
            expected = _normalize_identifier_token(expected_raw)
            observed_vals: list[str] = []
            for e in ack_sources:
                obs = _normalize_identifier_token(getattr(e, field))
                if obs is not None:
                    observed_vals.append(obs)
            observed = observed_vals[0] if observed_vals else None
            # Conflict if multiple observed disagree.
            if len(set(observed_vals)) > 1:
                match = IdentifierMatchKind.MISMATCH
                observed = observed_vals[0]
            elif expected is None and observed is None:
                match = IdentifierMatchKind.ABSENT_BOTH
            elif expected is None:
                match = IdentifierMatchKind.MISSING_EXPECTED
            elif observed is None:
                # Not a hard conflict if package didn't require ack fields
                # to surface the identifier — only mismatch is conflict.
                match = IdentifierMatchKind.MISSING_OBSERVED
            elif expected == observed:
                match = IdentifierMatchKind.MATCH
            else:
                match = IdentifierMatchKind.MISMATCH

            checks.append(
                IdentifierCheck(
                    field=field,
                    match=match,
                    expected=expected_raw,
                    observed=next(
                        (
                            getattr(e, field)
                            for e in ack_sources
                            if getattr(e, field) is not None
                        ),
                        None,
                    ),
                )
            )
            if match is IdentifierMatchKind.MISMATCH:
                code = getattr(ReconciliationReasonCode, reason_attr).value
                reason_codes.append(code)
        return checks

    def _check_files(
        self,
        pkg: SubmittedPackageBinding,
        evs: Sequence[ImportedEvidence],
        reason_codes: list[str],
    ) -> tuple[list[FileCheck], bool, bool, bool]:
        """Return (checks, conflict, incomplete, partial)."""
        checks: list[FileCheck] = []
        conflict = False
        incomplete = False
        partial = False

        # Aggregate listed files from acknowledgement (preferred) then all.
        listed: dict[str, str] = {}
        listed_sources = [
            e for e in evs if e.role is EvidenceRole.ACKNOWLEDGEMENT
        ] or list(evs)
        for e in listed_sources:
            for f in e.listed_files:
                if f.filename in listed and listed[f.filename] != f.content_digest:
                    conflict = True
                    reason_codes.append(
                        ReconciliationReasonCode.FILE_DIGEST_MISMATCH.value
                    )
                listed[f.filename] = f.content_digest

        pkg_map = {f.filename: f.content_digest for f in pkg.files}

        if listed:
            for name, digest in pkg_map.items():
                if name not in listed:
                    checks.append(
                        FileCheck(
                            filename=name,
                            match=FileMatchKind.MISSING_FROM_RECEIPT,
                            expected_digest=digest,
                            observed_digest=None,
                        )
                    )
                    partial = True
                    reason_codes.append(
                        ReconciliationReasonCode.PARTIAL_SUBMISSION.value
                    )
                elif listed[name] != digest:
                    checks.append(
                        FileCheck(
                            filename=name,
                            match=FileMatchKind.DIGEST_MISMATCH,
                            expected_digest=digest,
                            observed_digest=listed[name],
                        )
                    )
                    conflict = True
                    reason_codes.append(
                        ReconciliationReasonCode.FILE_DIGEST_MISMATCH.value
                    )
                else:
                    checks.append(
                        FileCheck(
                            filename=name,
                            match=FileMatchKind.EXACT,
                            expected_digest=digest,
                            observed_digest=listed[name],
                        )
                    )
            for name, digest in listed.items():
                if name not in pkg_map:
                    checks.append(
                        FileCheck(
                            filename=name,
                            match=FileMatchKind.UNEXPECTED_ON_RECEIPT,
                            expected_digest=None,
                            observed_digest=digest,
                        )
                    )
                    conflict = True
                    reason_codes.append(
                        ReconciliationReasonCode.FILENAME_MISMATCH.value
                    )
        elif pkg.files and any(
            e.role is EvidenceRole.ACKNOWLEDGEMENT for e in evs
        ):
            # Ack present but lists no files while package has files → partial.
            for name, digest in pkg_map.items():
                checks.append(
                    FileCheck(
                        filename=name,
                        match=FileMatchKind.MISSING_FROM_RECEIPT,
                        expected_digest=digest,
                        observed_digest=None,
                    )
                )
            partial = True
            incomplete = True
            reason_codes.append(ReconciliationReasonCode.PARTIAL_SUBMISSION.value)

        # Document count cross-check against acknowledgement.
        for e in evs:
            if e.role is not EvidenceRole.ACKNOWLEDGEMENT:
                continue
            if (
                e.document_count is not None
                and pkg.document_count is not None
                and e.document_count != pkg.document_count
            ):
                conflict = True
                reason_codes.append(
                    ReconciliationReasonCode.DOCUMENT_COUNT_MISMATCH.value
                )
                # Represent as a synthetic partial file check note via warnings
                # path is reason_codes only (content-free).

            if (
                e.observed_at_utc is not None
                and pkg.submitted_at_utc is not None
                and e.observed_at_utc < pkg.submitted_at_utc
            ):
                # Receipt timestamp before submission is a soft conflict signal.
                conflict = True
                reason_codes.append(
                    ReconciliationReasonCode.TIMESTAMP_MISMATCH.value
                )

        return checks, conflict, incomplete, partial

    def _check_conversions(
        self,
        pkg: SubmittedPackageBinding,
        convs: Sequence[ConvertedArtifactBinding],
        reason_codes: list[str],
    ) -> tuple[list[ConversionCheck], list[str], bool, bool]:
        """Return (checks, disclosed_diffs, conflict, has_expected_conversion)."""
        checks: list[ConversionCheck] = []
        disclosed: list[str] = []
        conflict = False
        has_expected = False
        pkg_digests = {f.content_digest for f in pkg.files}
        pkg_by_name = {f.filename: f for f in pkg.files}

        for c in convs:
            if c.content_digest in pkg_digests:
                checks.append(
                    ConversionCheck(
                        artifact_id=c.artifact_id,
                        match=ConversionMatchKind.EXACT,
                        source_filename=c.source_filename,
                        disclosed_differences=(),
                    )
                )
                continue

            # Digest differs from package originals.
            if c.expected_conversion and c.disclosed_differences:
                if self._policy.accept_expected_conversion_with_disclosed_differences:
                    has_expected = True
                    disclosed.extend(c.disclosed_differences)
                    checks.append(
                        ConversionCheck(
                            artifact_id=c.artifact_id,
                            match=ConversionMatchKind.EXPECTED_CONVERSION,
                            source_filename=c.source_filename,
                            disclosed_differences=c.disclosed_differences,
                        )
                    )
                    reason_codes.append(
                        ReconciliationReasonCode.EXPECTED_CONVERSION_DISCLOSED.value
                    )
                    # Optional: verify source binding if provided.
                    if c.source_filename and c.source_filename in pkg_by_name:
                        src = pkg_by_name[c.source_filename]
                        if (
                            c.source_digest is not None
                            and c.source_digest != src.content_digest
                        ):
                            conflict = True
                            reason_codes.append(
                                ReconciliationReasonCode.CONVERSION_MISMATCH.value
                            )
                            checks[-1] = ConversionCheck(
                                artifact_id=c.artifact_id,
                                match=ConversionMatchKind.MISMATCHED,
                                source_filename=c.source_filename,
                                disclosed_differences=c.disclosed_differences,
                            )
                    continue
                # Policy rejects expected conversion path — treat as mismatch.
                conflict = True
                checks.append(
                    ConversionCheck(
                        artifact_id=c.artifact_id,
                        match=ConversionMatchKind.MISMATCHED,
                        source_filename=c.source_filename,
                        disclosed_differences=c.disclosed_differences,
                    )
                )
                reason_codes.append(
                    ReconciliationReasonCode.CONVERSION_MISMATCH.value
                )
                continue

            if c.expected_conversion and not c.disclosed_differences:
                conflict = True
                checks.append(
                    ConversionCheck(
                        artifact_id=c.artifact_id,
                        match=ConversionMatchKind.MISMATCHED,
                        source_filename=c.source_filename,
                        disclosed_differences=(),
                    )
                )
                reason_codes.append(
                    ReconciliationReasonCode.CONVERSION_DIFFERENCE_UNDISCLOSED.value
                )
                continue

            # Unexpected digest difference without expected-conversion flag.
            conflict = True
            checks.append(
                ConversionCheck(
                    artifact_id=c.artifact_id,
                    match=ConversionMatchKind.MISMATCHED,
                    source_filename=c.source_filename,
                    disclosed_differences=c.disclosed_differences,
                )
            )
            reason_codes.append(
                ReconciliationReasonCode.CONVERSION_MISMATCH.value
            )

        return checks, list(dict.fromkeys(disclosed)), conflict, has_expected

    def _resolve_disposition(
        self,
        *,
        conflict: bool,
        incomplete: bool,
        has_auth_ack: bool,
        has_expected_conversion: bool,
        disclosed: Sequence[str],
        reason_codes: list[str],
    ) -> tuple[ReconciliationDisposition, FiledStatusEligibility]:
        if conflict:
            reason_codes.append(
                ReconciliationReasonCode.FILED_STATUS_BLOCKED.value
            )
            return (
                ReconciliationDisposition.CONFLICTING,
                FiledStatusEligibility.BLOCKED,
            )

        if incomplete or not has_auth_ack:
            reason_codes.append(
                ReconciliationReasonCode.FILED_STATUS_BLOCKED.value
            )
            return (
                ReconciliationDisposition.INCOMPLETE,
                FiledStatusEligibility.BLOCKED,
            )

        # Authoritative ack present and no conflicts.
        if has_expected_conversion and disclosed:
            reason_codes.append(
                ReconciliationReasonCode.FILED_STATUS_ELIGIBLE.value
            )
            return (
                ReconciliationDisposition.VERIFIED_WITH_DISCLOSED_DIFFERENCES,
                FiledStatusEligibility.ELIGIBLE,
            )

        reason_codes.append(ReconciliationReasonCode.EXACT_MATCH.value)
        reason_codes.append(
            ReconciliationReasonCode.FILED_STATUS_ELIGIBLE.value
        )
        return (
            ReconciliationDisposition.VERIFIED,
            FiledStatusEligibility.ELIGIBLE,
        )

    def _append_ledger_event(
        self,
        result: ReconciliationResult,
        *,
        pkg: SubmittedPackageBinding,
        at: str | None,
    ) -> ReconciliationResult:
        assert self._ledger is not None
        event_utc = at or "1970-01-01T00:00:00Z"
        # Content-free metadata only — digests, codes, identifiers.
        metadata: dict[str, str] = {
            "disposition": (
                result.disposition.value
                if isinstance(result.disposition, ReconciliationDisposition)
                else str(result.disposition)
            ),
            "filed_status_eligibility": (
                result.filed_status_eligibility.value
                if isinstance(
                    result.filed_status_eligibility, FiledStatusEligibility
                )
                else str(result.filed_status_eligibility)
            ),
            "has_authoritative_acknowledgement": (
                "true" if result.has_authoritative_acknowledgement else "false"
            ),
            "has_payment_receipt": (
                "true" if result.has_payment_receipt else "false"
            ),
            "output_kind": OUTPUT_KIND_RECONCILIATION_EVENT,
            "package_digest": result.package_digest,
            "package_id": result.package_id,
            "parser_version": PARSER_VERSION,
            "policy_id": result.policy_id,
            "reconciliation_id": result.reconciliation_id,
            "schema_version": RECONCILER_SCHEMA_VERSION,
        }
        if pkg.application_number:
            metadata["application_number"] = pkg.application_number
        if pkg.confirmation_number:
            metadata["confirmation_number"] = pkg.confirmation_number
        if result.disclosed_differences:
            # Join codes only — never private text.
            metadata["disclosed_differences"] = ",".join(
                result.disclosed_differences[:16]
            )
        # Cap metadata size via truncation of reason codes list.
        metadata["reason_codes"] = ",".join(result.reason_codes[:24])

        desc_digest = sha256_hex(
            canonical_json(
                {
                    "disposition": metadata["disposition"],
                    "package_digest": result.package_digest,
                    "reconciliation_id": result.reconciliation_id,
                }
            )
        )
        event_id = f"evt:recon:{result.reconciliation_id}"
        event = MatterEvent(
            schema_version=CONTRACTS_SCHEMA_VERSION,
            event_id=event_id,
            matter_id=result.matter_id,
            kind=MatterEventKind.FILING,
            event_utc=event_utc,
            source_receipt_id=result.related_artifact_ids[0]
            if result.related_artifact_ids
            else None,
            description_digest=desc_digest,
            related_artifact_ids=result.related_artifact_ids,
            classification=result.classification
            if isinstance(result.classification, DisclosureClassification)
            else DisclosureClassification(str(result.classification)),
            metadata=metadata,
        )
        ingest: IngestResult = self._ledger.ingest_event(
            matter_id=result.matter_id,
            event=event,
            channel=LedgerChannel.PRIVATE_IMPORT,
            notes=("filing_receipt_reconciliation",),
        )
        # Rebuild result with ledger event id and extra reason code.
        data = result.to_dict()
        data.pop("content_digest", None)
        data["ledger_event_id"] = event_id
        reasons = list(result.reason_codes)
        reasons.append(ReconciliationReasonCode.LEDGER_EVENT_APPENDED.value)
        if not ingest.ok and ingest.disposition.value == "quarantined":
            # Wrong-matter quarantine on ledger — surface as conflict signal
            # without mutating prior disposition if already conflicting.
            reasons.append(ReconciliationReasonCode.WRONG_MATTER.value)
        data["reason_codes"] = list(dict.fromkeys(reasons))
        return ReconciliationResult.from_dict(data)


def create_filing_receipt_reconciler(
    *,
    policy: AuthoritativeAcknowledgementPolicy | None = None,
    ledger: MatterLedger | None = None,
    id_factory: Callable[[], str] | None = None,
) -> FilingReceiptReconciler:
    """Factory for :class:`FilingReceiptReconciler`."""
    return FilingReceiptReconciler(
        policy=policy, ledger=ledger, id_factory=id_factory
    )


def reconcile_filing_receipts(
    package: SubmittedPackageBinding | Mapping[str, Any],
    evidence: Sequence[ImportedEvidence | Mapping[str, Any]] = (),
    converted: Sequence[ConvertedArtifactBinding | Mapping[str, Any]] = (),
    *,
    ledger: MatterLedger | None = None,
    policy: AuthoritativeAcknowledgementPolicy | None = None,
    reconciled_at_utc: str | None = None,
    append_to_ledger: bool = True,
) -> ReconciliationResult:
    """Module-level convenience entry point."""
    reconciler = create_filing_receipt_reconciler(
        policy=policy, ledger=ledger
    )
    return reconciler.reconcile(
        package,
        evidence,
        converted,
        reconciled_at_utc=reconciled_at_utc,
        append_to_ledger=append_to_ledger,
    )


__all__ = [
    "AuthoritativeAcknowledgementPolicy",
    "DEFAULT_ACKNOWLEDGEMENT_POLICY",
    "ConversionCheck",
    "ConversionMatchKind",
    "ConvertedArtifactBinding",
    "EvidenceRole",
    "FabricatedEvidenceError",
    "FileCheck",
    "FileMatchKind",
    "FiledStatusEligibility",
    "FilingReceiptReconciler",
    "FilingReceiptReconcilerError",
    "FORBIDDEN_IMPORT_MODULES",
    "FORBIDDEN_RECONCILER_INTERFACES",
    "IdentifierCheck",
    "IdentifierMatchKind",
    "ImportedEvidence",
    "OUTPUT_KIND_RECONCILIATION",
    "PARSER_VERSION",
    "RECONCILER_DISCLAIMER",
    "RECONCILER_INTERFACE",
    "RECONCILER_SCHEMA_VERSION",
    "RULESET_VERSION",
    "ReconciliationDisposition",
    "ReconciliationReasonCode",
    "ReconciliationResult",
    "SubmittedFileBinding",
    "SubmittedPackageBinding",
    "assert_interface_allowed",
    "create_filing_receipt_reconciler",
    "has_authoritative_acknowledgement",
    "is_forbidden_interface",
    "payment_only_evidence",
    "prove_no_forbidden_interfaces",
    "reconcile_filing_receipts",
    "sha256_hex",
]
