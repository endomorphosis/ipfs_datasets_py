"""Per-authority Federal Register full-text attempt exhaustion gate (LCR-075).

Fail-closed admission gate for Federal Register full-text acquisition. A
document may only leave the acquisition frontier when every official
full-text alternative has been attempted under a sealed, real-time cutoff
and the resulting disposition is either:

* admitted full text (fetched, hash-verified, successfully parsed); or
* a non-body disposition (``METADATA_ONLY``, ``ABSTRACT_ONLY``,
  ``MISSING_BODY_OFFICIAL``, exclusion, or quarantine) backed by an allowed
  reason **and** complete attempt evidence proving every official alternative
  has no usable body.

Design invariants
-----------------
* FederalRegister.gov and GovInfo are the required official full-text
  authorities; both must appear in the per-document attempt ledger.
* Each attempt records URL, ``observed_at``, status, response/content hash,
  retry count, terminal reason, and parser result.
* Any available/retrieved official body that is not fetched, hash-verified,
  successfully parsed, and admitted as full text remains unresolved /
  ``failed_final`` and blocks publication. Exclusion or quarantine cannot
  erase that failure.
* ``failed_final`` / ``pending`` dispositions always block.
* Missing hashes, missing/malformed/non-UTC ``cutoff_sealed_at``,
  per-attempt ``observed_at``, or ``receipt_created_at``, mutable/future
  cutoffs, ``cutoff_sealed_at`` after the first acquisition observation,
  ``receipt_created_at`` before the last recorded attempt, or any timestamp
  later than the verifier clock also block acquisition and publication.
* Live network I/O is out of scope; unit tests use sealed fixtures only.
* Completeness is cutoff-relative (inherits LCR-049 source policy).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Optional, Sequence, Union

from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (
    CURRENTNESS_DISCLAIMER,
    DEFAULT_OBSERVATION_CUTOFF,
    FEDERAL_REGISTER_SITE,
    GOVINFO_SITE,
    OFFICIAL_FULL_TEXT_SOURCES,
    PREVIOUS_PUBLIC_PIN,
    SCHEMA_VERSION as POLICY_SCHEMA_VERSION,
    BodyTextDisposition,
    FederalRegisterSourcePolicyError,
    FixtureSchemaError as PolicyFixtureSchemaError,
    MutableCutoffError,
    OfficialAuthority,
    OfficialAuthorityError,
    TimestampError,
    build_legal_id,
    content_sha256,
    cutoff_release_point,
    format_utc_timestamp,
    is_mutable_cutoff,
    normalize_sha256,
    parse_utc_timestamp,
    repository_root,
    require_full_text_authority,
    require_immutable_observation_cutoff,
    validate_calendar_date,
    validate_document_number,
    validate_official_url,
)

# ---------------------------------------------------------------------------
# Schema / task identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "federal-register-fulltext-gate-v1"
FIXTURE_SCHEMA_VERSION: Final = "federal-register-fulltext-attempt-receipts-v1"
TASK_ID: Final = "LCR-075"
GOAL_ID: Final = "LCR-G110"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "federal_register_fulltext_gate.py"

# Fixed non-authorizing verifier clock for fixture-only evaluation.
# Live acquisition must supply a trusted clock; the gate never invents time.
FIXTURE_VERIFIER_CLOCK_UTC: Final = "2026-08-10T12:00:00Z"

# Bounded skew: timestamps may not be more than this ahead of verifier time.
DEFAULT_MAX_FUTURE_SKEW: Final = timedelta(minutes=5)

DEFAULT_FIXTURE_RELATIVE_PATH: Final = Path(
    "tests/fixtures/legal_ir/federal_register_fulltext_attempt_receipts.json"
)

# Official full-text authorities that must be exhausted for non-body states.
REQUIRED_FULL_TEXT_AUTHORITIES: Final = (
    OfficialAuthority.FEDERAL_REGISTER,
    OfficialAuthority.GOVINFO,
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]
ClockFn = Callable[[], datetime]

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FederalRegisterFulltextGateError(FederalRegisterSourcePolicyError):
    """Base error for Federal Register full-text attempt gate failures."""


class AttemptEvidenceError(FederalRegisterFulltextGateError):
    """Raised when attempt ledger evidence is incomplete or inconsistent."""


class ExhaustionError(FederalRegisterFulltextGateError):
    """Raised when official full-text alternatives were not exhausted."""


class UnresolvedBodyError(FederalRegisterFulltextGateError):
    """Raised when a usable official body was not admitted as full text."""


class SealTimestampError(FederalRegisterFulltextGateError):
    """Raised when cutoff seal / receipt / observation timestamps fail rules."""


class DispositionAdmissionError(FederalRegisterFulltextGateError):
    """Raised when a non-body disposition lacks an allowed reason."""


class FailedFinalAdmissionError(FederalRegisterFulltextGateError):
    """Raised when failed-final or pending items block admission."""


class MissingHashError(FederalRegisterFulltextGateError):
    """Raised when a required response/content hash is absent."""


class FixtureSchemaError(FederalRegisterFulltextGateError, PolicyFixtureSchemaError):
    """Raised when the sealed attempt-receipts fixture is malformed."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AttemptStatus(str, Enum):
    """Lifecycle status of one per-authority/format full-text attempt."""

    PENDING = "pending"
    FETCHED = "fetched"
    HASH_VERIFIED = "hash_verified"
    PARSED = "parsed"
    ADMITTED = "admitted"
    NO_BODY = "no_body"
    FAILED = "failed"
    SKIPPED = "skipped"

    @classmethod
    def coerce(cls, value: Any) -> "AttemptStatus":
        if isinstance(value, AttemptStatus):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "ok": cls.ADMITTED,
            "success": cls.ADMITTED,
            "complete": cls.ADMITTED,
            "done": cls.ADMITTED,
            "verified": cls.HASH_VERIFIED,
            "hash": cls.HASH_VERIFIED,
            "parse_ok": cls.PARSED,
            "empty": cls.NO_BODY,
            "unavailable": cls.NO_BODY,
            "missing_body": cls.NO_BODY,
            "error": cls.FAILED,
            "timeout": cls.FAILED,
            "open": cls.PENDING,
            "in_progress": cls.PENDING,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise AttemptEvidenceError(f"unknown attempt status: {value!r}")

    @property
    def is_terminal(self) -> bool:
        return self in {
            AttemptStatus.ADMITTED,
            AttemptStatus.NO_BODY,
            AttemptStatus.FAILED,
            AttemptStatus.SKIPPED,
            AttemptStatus.PARSED,
            AttemptStatus.HASH_VERIFIED,
            AttemptStatus.FETCHED,
        }

    @property
    def is_pending(self) -> bool:
        return self is AttemptStatus.PENDING

    @property
    def proves_no_usable_body(self) -> bool:
        """True when this terminal status proves no usable body at the URL."""

        return self is AttemptStatus.NO_BODY

    @property
    def indicates_body_present(self) -> bool:
        """True when the attempt progressed far enough that a body existed."""

        return self in {
            AttemptStatus.FETCHED,
            AttemptStatus.HASH_VERIFIED,
            AttemptStatus.PARSED,
            AttemptStatus.ADMITTED,
        }


class ParserResult(str, Enum):
    """Typed parser outcome for one full-text attempt payload."""

    SUCCESS = "success"
    NO_BODY = "no_body"
    EMPTY = "empty"
    ERROR_PAGE = "error_page"
    NAVIGATION = "navigation"
    ANTI_BOT = "anti_bot"
    PARSE_ERROR = "parse_error"
    UNSUPPORTED_FORMAT = "unsupported_format"
    NOT_RUN = "not_run"

    @classmethod
    def coerce(cls, value: Any) -> "ParserResult":
        if isinstance(value, ParserResult):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "ok": cls.SUCCESS,
            "parsed": cls.SUCCESS,
            "full_text": cls.SUCCESS,
            "body": cls.SUCCESS,
            "missing": cls.NO_BODY,
            "unavailable": cls.NO_BODY,
            "none": cls.EMPTY,
            "blank": cls.EMPTY,
            "error": cls.PARSE_ERROR,
            "failed": cls.PARSE_ERROR,
            "captcha": cls.ANTI_BOT,
            "blocked": cls.ANTI_BOT,
            "nav": cls.NAVIGATION,
            "skipped": cls.NOT_RUN,
            "pending": cls.NOT_RUN,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise AttemptEvidenceError(f"unknown parser result: {value!r}")

    @property
    def proves_no_usable_body(self) -> bool:
        return self in {
            ParserResult.NO_BODY,
            ParserResult.EMPTY,
            ParserResult.ERROR_PAGE,
            ParserResult.NAVIGATION,
            ParserResult.ANTI_BOT,
            ParserResult.UNSUPPORTED_FORMAT,
        }

    @property
    def indicates_usable_body(self) -> bool:
        return self is ParserResult.SUCCESS


class ContentFormat(str, Enum):
    """Official full-text content format attempted for a document."""

    HTML = "html"
    XML = "xml"
    PDF = "pdf"
    JSON = "json"
    TEXT = "text"
    UNKNOWN = "unknown"

    @classmethod
    def coerce(cls, value: Any) -> "ContentFormat":
        if isinstance(value, ContentFormat):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "htm": cls.HTML,
            "xhtml": cls.HTML,
            "application_xml": cls.XML,
            "text_xml": cls.XML,
            "application_pdf": cls.PDF,
            "application_json": cls.JSON,
            "txt": cls.TEXT,
            "plain": cls.TEXT,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise AttemptEvidenceError(f"unknown content format: {value!r}")


class FulltextDisposition(str, Enum):
    """Typed admission disposition after per-authority attempt exhaustion.

    Non-body dispositions require an allowed reason and complete exhaustion
    evidence. ``failed_final`` and ``pending`` always block publication.
    """

    FULL_TEXT = "full_text"
    HTML_BODY = "html_body"
    XML_BODY = "xml_body"
    PDF_BODY = "pdf_body"
    GOVINFO_BODY = "govinfo_body"
    ABSTRACT_ONLY = "abstract_only"
    METADATA_ONLY = "metadata_only"
    MISSING_BODY_OFFICIAL = "missing_body_official"
    EXCLUDED = "excluded"
    QUARANTINED = "quarantined"
    FAILED_FINAL = "failed_final"
    PENDING = "pending"

    @classmethod
    def coerce(cls, value: Any) -> "FulltextDisposition":
        if isinstance(value, FulltextDisposition):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "full": cls.FULL_TEXT,
            "body": cls.FULL_TEXT,
            "fulltext": cls.FULL_TEXT,
            "html": cls.HTML_BODY,
            "xml": cls.XML_BODY,
            "pdf": cls.PDF_BODY,
            "govinfo": cls.GOVINFO_BODY,
            "abstract": cls.ABSTRACT_ONLY,
            "meta": cls.METADATA_ONLY,
            "metadata": cls.METADATA_ONLY,
            "missing": cls.MISSING_BODY_OFFICIAL,
            "unavailable": cls.MISSING_BODY_OFFICIAL,
            "missing_body": cls.MISSING_BODY_OFFICIAL,
            "exclusion": cls.EXCLUDED,
            "exclude": cls.EXCLUDED,
            "quarantine": cls.QUARANTINED,
            "failed": cls.FAILED_FINAL,
            "open": cls.PENDING,
            "in_progress": cls.PENDING,
            "unresolved": cls.PENDING,
        }
        if text in aliases:
            return aliases[text]
        # Map LCR-049 body dispositions where they overlap.
        try:
            body = BodyTextDisposition.coerce(text)
            mapping = {
                BodyTextDisposition.FULL_TEXT: cls.FULL_TEXT,
                BodyTextDisposition.HTML_BODY: cls.HTML_BODY,
                BodyTextDisposition.XML_BODY: cls.XML_BODY,
                BodyTextDisposition.PDF_BODY: cls.PDF_BODY,
                BodyTextDisposition.GOVINFO_BODY: cls.GOVINFO_BODY,
                BodyTextDisposition.ABSTRACT_ONLY: cls.ABSTRACT_ONLY,
                BodyTextDisposition.METADATA_ONLY: cls.METADATA_ONLY,
                BodyTextDisposition.UNAVAILABLE: cls.MISSING_BODY_OFFICIAL,
                BodyTextDisposition.FAILED_FINAL: cls.FAILED_FINAL,
            }
            if body in mapping:
                return mapping[body]
        except Exception:
            pass
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise DispositionAdmissionError(f"unknown full-text disposition: {value!r}")

    @property
    def has_usable_body(self) -> bool:
        return self in BODY_BEARING_FULLTEXT_DISPOSITIONS

    @property
    def is_non_body(self) -> bool:
        return self in NON_BODY_FULLTEXT_DISPOSITIONS

    @property
    def requires_exhaustion(self) -> bool:
        return self in EXHAUSTION_REQUIRED_DISPOSITIONS

    @property
    def blocks_publication(self) -> bool:
        return self in {FulltextDisposition.FAILED_FINAL, FulltextDisposition.PENDING}


BODY_BEARING_FULLTEXT_DISPOSITIONS: Final = frozenset(
    {
        FulltextDisposition.FULL_TEXT,
        FulltextDisposition.HTML_BODY,
        FulltextDisposition.XML_BODY,
        FulltextDisposition.PDF_BODY,
        FulltextDisposition.GOVINFO_BODY,
    }
)

NON_BODY_FULLTEXT_DISPOSITIONS: Final = frozenset(
    {
        FulltextDisposition.ABSTRACT_ONLY,
        FulltextDisposition.METADATA_ONLY,
        FulltextDisposition.MISSING_BODY_OFFICIAL,
        FulltextDisposition.EXCLUDED,
        FulltextDisposition.QUARANTINED,
        FulltextDisposition.FAILED_FINAL,
        FulltextDisposition.PENDING,
    }
)

EXHAUSTION_REQUIRED_DISPOSITIONS: Final = frozenset(
    {
        FulltextDisposition.ABSTRACT_ONLY,
        FulltextDisposition.METADATA_ONLY,
        FulltextDisposition.MISSING_BODY_OFFICIAL,
        FulltextDisposition.EXCLUDED,
        FulltextDisposition.QUARANTINED,
    }
)


class AllowedNonBodyReason(str, Enum):
    """Closed allow-list of reasons that may justify a non-body disposition."""

    OFFICIAL_BODY_UNAVAILABLE = "official_body_unavailable"
    OFFICIAL_METADATA_ONLY = "official_metadata_only"
    OFFICIAL_ABSTRACT_ONLY = "official_abstract_only"
    WITHDRAWN_WITHOUT_BODY = "withdrawn_without_body"
    CORRECTION_WITHOUT_BODY = "correction_without_body"
    RIGHTS_OR_SCOPE_EXCLUSION = "rights_or_scope_exclusion"
    CONTENT_QUARANTINE = "content_quarantine"
    DUPLICATE_OF_ADMITTED = "duplicate_of_admitted"
    OUTSIDE_CUTOFF_SCOPE = "outside_cutoff_scope"

    @classmethod
    def coerce(cls, value: Any) -> "AllowedNonBodyReason":
        if isinstance(value, AllowedNonBodyReason):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "unavailable": cls.OFFICIAL_BODY_UNAVAILABLE,
            "no_body": cls.OFFICIAL_BODY_UNAVAILABLE,
            "missing_body": cls.OFFICIAL_BODY_UNAVAILABLE,
            "metadata": cls.OFFICIAL_METADATA_ONLY,
            "metadata_only": cls.OFFICIAL_METADATA_ONLY,
            "abstract": cls.OFFICIAL_ABSTRACT_ONLY,
            "abstract_only": cls.OFFICIAL_ABSTRACT_ONLY,
            "withdrawn": cls.WITHDRAWN_WITHOUT_BODY,
            "correction": cls.CORRECTION_WITHOUT_BODY,
            "exclusion": cls.RIGHTS_OR_SCOPE_EXCLUSION,
            "excluded": cls.RIGHTS_OR_SCOPE_EXCLUSION,
            "rights": cls.RIGHTS_OR_SCOPE_EXCLUSION,
            "quarantine": cls.CONTENT_QUARANTINE,
            "quarantined": cls.CONTENT_QUARANTINE,
            "duplicate": cls.DUPLICATE_OF_ADMITTED,
            "out_of_scope": cls.OUTSIDE_CUTOFF_SCOPE,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise DispositionAdmissionError(
            f"non-body disposition requires an allowed reason; got {value!r}"
        )


# Disposition → preferred allowed reasons (soft guidance; any allow-list value
# is accepted when exhaustion evidence is complete).
_PREFERRED_REASONS: Final = MappingProxyType(
    {
        FulltextDisposition.METADATA_ONLY: frozenset(
            {AllowedNonBodyReason.OFFICIAL_METADATA_ONLY}
        ),
        FulltextDisposition.ABSTRACT_ONLY: frozenset(
            {AllowedNonBodyReason.OFFICIAL_ABSTRACT_ONLY}
        ),
        FulltextDisposition.MISSING_BODY_OFFICIAL: frozenset(
            {
                AllowedNonBodyReason.OFFICIAL_BODY_UNAVAILABLE,
                AllowedNonBodyReason.WITHDRAWN_WITHOUT_BODY,
                AllowedNonBodyReason.CORRECTION_WITHOUT_BODY,
            }
        ),
        FulltextDisposition.EXCLUDED: frozenset(
            {
                AllowedNonBodyReason.RIGHTS_OR_SCOPE_EXCLUSION,
                AllowedNonBodyReason.DUPLICATE_OF_ADMITTED,
                AllowedNonBodyReason.OUTSIDE_CUTOFF_SCOPE,
            }
        ),
        FulltextDisposition.QUARANTINED: frozenset(
            {AllowedNonBodyReason.CONTENT_QUARANTINE}
        ),
    }
)


class GateVerdict(str, Enum):
    """Gate verdict for one attempt receipt or fixture case."""

    PASS = "pass"
    FAIL = "fail"

    @classmethod
    def coerce(cls, value: Any) -> "GateVerdict":
        if isinstance(value, GateVerdict):
            return value
        text = str(value or "").strip().lower()
        if text in {"pass", "ok", "success", "closed", "true", "1"}:
            return cls.PASS
        if text in {"fail", "failed", "error", "reject", "false", "0"}:
            return cls.FAIL
        raise FederalRegisterFulltextGateError(f"unknown verdict: {value!r}")


class FailureKind(str, Enum):
    """Typed failure kinds rejected by the full-text attempt gate."""

    FAILED_FINAL = "failed_final"
    PENDING = "pending"
    MISSING_HASH = "missing_hash"
    MISSING_TIMESTAMP = "missing_timestamp"
    MALFORMED_TIMESTAMP = "malformed_timestamp"
    NON_UTC_TIMESTAMP = "non_utc_timestamp"
    MUTABLE_CUTOFF = "mutable_cutoff"
    FUTURE_CUTOFF = "future_cutoff"
    CUTOFF_SEAL_AFTER_OBSERVATION = "cutoff_seal_after_observation"
    RECEIPT_BEFORE_LAST_ATTEMPT = "receipt_before_last_attempt"
    TIMESTAMP_AFTER_VERIFIER = "timestamp_after_verifier"
    MISSING_ALLOWED_REASON = "missing_allowed_reason"
    INCOMPLETE_EXHAUSTION = "incomplete_exhaustion"
    BODY_NOT_ADMITTED = "body_not_admitted"
    EXCLUSION_ERASES_FAILURE = "exclusion_erases_failure"
    MISSING_ATTEMPT_EVIDENCE = "missing_attempt_evidence"
    OFFICIAL_AUTHORITY = "official_authority"
    DOCUMENT_IDENTITY = "document_identity"
    SCHEMA = "schema"
    OTHER = "other"

    @classmethod
    def coerce(cls, value: Any) -> "FailureKind":
        if isinstance(value, FailureKind):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "failed": cls.FAILED_FINAL,
            "failed_final_item": cls.FAILED_FINAL,
            "open": cls.PENDING,
            "unresolved": cls.PENDING,
            "hash": cls.MISSING_HASH,
            "missing_response_hash": cls.MISSING_HASH,
            "missing_content_hash": cls.MISSING_HASH,
            "timestamp": cls.MISSING_TIMESTAMP,
            "missing_observed_at": cls.MISSING_TIMESTAMP,
            "missing_cutoff_sealed_at": cls.MISSING_TIMESTAMP,
            "missing_receipt_created_at": cls.MISSING_TIMESTAMP,
            "malformed": cls.MALFORMED_TIMESTAMP,
            "non_utc": cls.NON_UTC_TIMESTAMP,
            "mutable": cls.MUTABLE_CUTOFF,
            "future": cls.FUTURE_CUTOFF,
            "cutoff_sealed_at_after_observation": cls.CUTOFF_SEAL_AFTER_OBSERVATION,
            "seal_after_observation": cls.CUTOFF_SEAL_AFTER_OBSERVATION,
            "receipt_created_before_attempt": cls.RECEIPT_BEFORE_LAST_ATTEMPT,
            "receipt_before_attempt": cls.RECEIPT_BEFORE_LAST_ATTEMPT,
            "after_verifier": cls.TIMESTAMP_AFTER_VERIFIER,
            "verifier_clock": cls.TIMESTAMP_AFTER_VERIFIER,
            "allowed_reason": cls.MISSING_ALLOWED_REASON,
            "reason": cls.MISSING_ALLOWED_REASON,
            "exhaustion": cls.INCOMPLETE_EXHAUSTION,
            "incomplete_attempt": cls.INCOMPLETE_EXHAUSTION,
            "body_available": cls.BODY_NOT_ADMITTED,
            "unresolved_body": cls.BODY_NOT_ADMITTED,
            "exclusion": cls.EXCLUSION_ERASES_FAILURE,
            "quarantine_erases": cls.EXCLUSION_ERASES_FAILURE,
            "attempt": cls.MISSING_ATTEMPT_EVIDENCE,
            "authority": cls.OFFICIAL_AUTHORITY,
            "identity": cls.DOCUMENT_IDENTITY,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        return cls.OTHER


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FederalRegisterFulltextGateError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise FederalRegisterFulltextGateError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise FederalRegisterFulltextGateError(
            f"{name} exceeds maximum length {maximum}"
        )
    return text


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FederalRegisterFulltextGateError(f"{name} must be an integer")
    if value < 0:
        raise FederalRegisterFulltextGateError(f"{name} must be >= 0")
    return value


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise FederalRegisterFulltextGateError(f"{name} must be a boolean")
    return value


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FederalRegisterFulltextGateError(f"{name} must be a mapping")
    return value


def _as_sequence(value: Any, name: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise FederalRegisterFulltextGateError(f"{name} must be a list")
    return value


def default_fulltext_fixture_path() -> Path:
    """Return the default on-disk path of the sealed attempt-receipts fixture."""

    return repository_root() / DEFAULT_FIXTURE_RELATIVE_PATH


def fixture_verifier_now() -> datetime:
    """Return the fixed fixture verifier clock as an aware UTC datetime."""

    return parse_utc_timestamp(FIXTURE_VERIFIER_CLOCK_UTC, name="verifier_clock")


def require_strict_utc_z_timestamp(value: Any, *, name: str = "timestamp") -> str:
    """Require an explicit ``...Z`` UTC timestamp string (no offset form).

    Fail-closed: missing, empty, naive, offset-only, or non-``Z`` values are
    rejected. Returns the normalized ``YYYY-MM-DDTHH:MM:SSZ`` form.
    """

    if value is None or (isinstance(value, str) and not value.strip()):
        raise SealTimestampError(f"{name} is required and must be a UTC ...Z timestamp")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise SealTimestampError(f"{name} must be timezone-aware UTC, got naive")
        return format_utc_timestamp(value.astimezone(timezone.utc))
    if not isinstance(value, str):
        raise SealTimestampError(f"{name} must be an ISO-8601 UTC ...Z string")
    text = value.strip()
    # Reject offset form without trailing Z — acceptance requires UTC Z.
    if text.endswith("+00:00") or text.endswith("-00:00"):
        raise SealTimestampError(
            f"{name} must use trailing Z UTC form, not offset {value!r}"
        )
    if not text.endswith("Z"):
        # Distinguish non-UTC vs malformed.
        try:
            dt = parse_utc_timestamp(text, name=name)
        except TimestampError as exc:
            # Naive or malformed.
            msg = str(exc).lower()
            if "naive" in msg or "timezone-aware" in msg:
                raise SealTimestampError(
                    f"{name} must be timezone-aware UTC ending in Z; got {value!r}"
                ) from exc
            raise SealTimestampError(
                f"{name} is malformed ISO-8601 UTC timestamp: {value!r}"
            ) from exc
        # Parsed with offset but no Z — non-UTC form for this gate.
        raise SealTimestampError(
            f"{name} must use trailing Z UTC form; got {value!r}"
        )
    try:
        dt = parse_utc_timestamp(text, name=name)
    except TimestampError as exc:
        raise SealTimestampError(
            f"{name} is malformed ISO-8601 UTC timestamp: {value!r}"
        ) from exc
    return format_utc_timestamp(dt)


def _authority_family(authority: OfficialAuthority) -> OfficialAuthority:
    """Normalize inventory API authority into the FR full-text family."""

    if authority is OfficialAuthority.FEDERAL_REGISTER_API:
        return OfficialAuthority.FEDERAL_REGISTER
    return authority


# ---------------------------------------------------------------------------
# Attempt and document records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FormatAttempt:
    """One per-authority/format full-text acquisition attempt."""

    attempt_id: str
    authority: OfficialAuthority
    content_format: ContentFormat
    url: str
    observed_at: str
    status: AttemptStatus
    response_hash: Optional[str] = None
    content_hash: Optional[str] = None
    retry_count: int = 0
    terminal_reason: str = ""
    parser_result: ParserResult = ParserResult.NOT_RUN
    body_available: bool = False
    body_usable: bool = False
    http_status: Optional[int] = None
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "attempt_id",
            _require_non_empty_str(self.attempt_id, "attempt_id", maximum=128),
        )
        authority = require_full_text_authority(self.authority)
        object.__setattr__(self, "authority", authority)
        object.__setattr__(
            self, "content_format", ContentFormat.coerce(self.content_format)
        )
        object.__setattr__(
            self, "url", validate_official_url(self.url, name="url")
        )
        object.__setattr__(
            self,
            "observed_at",
            require_strict_utc_z_timestamp(self.observed_at, name="observed_at"),
        )
        object.__setattr__(self, "status", AttemptStatus.coerce(self.status))
        if self.response_hash is not None and str(self.response_hash).strip():
            object.__setattr__(
                self,
                "response_hash",
                normalize_sha256(self.response_hash, name="response_hash"),
            )
        else:
            object.__setattr__(self, "response_hash", None)
        if self.content_hash is not None and str(self.content_hash).strip():
            object.__setattr__(
                self,
                "content_hash",
                normalize_sha256(self.content_hash, name="content_hash"),
            )
        else:
            object.__setattr__(self, "content_hash", None)
        object.__setattr__(
            self, "retry_count", _require_non_negative_int(self.retry_count, "retry_count")
        )
        object.__setattr__(self, "terminal_reason", str(self.terminal_reason or ""))
        object.__setattr__(
            self, "parser_result", ParserResult.coerce(self.parser_result)
        )
        object.__setattr__(
            self, "body_available", _require_bool(self.body_available, "body_available")
        )
        object.__setattr__(
            self, "body_usable", _require_bool(self.body_usable, "body_usable")
        )
        if self.http_status is not None:
            status_code = _require_non_negative_int(self.http_status, "http_status")
            if status_code > 599:
                raise AttemptEvidenceError(
                    f"http_status out of range: {self.http_status!r}"
                )
            object.__setattr__(self, "http_status", status_code)
        object.__setattr__(self, "notes", str(self.notes or ""))

        # Consistency: usable implies available; admitted implies usable body path.
        if self.body_usable and not self.body_available:
            raise AttemptEvidenceError(
                f"attempt {self.attempt_id!r}: body_usable requires body_available"
            )
        if self.status is AttemptStatus.ADMITTED and not self.body_usable:
            raise AttemptEvidenceError(
                f"attempt {self.attempt_id!r}: admitted status requires body_usable"
            )
        if self.parser_result.indicates_usable_body and not self.body_usable:
            # Parser success without body_usable is inconsistent.
            raise AttemptEvidenceError(
                f"attempt {self.attempt_id!r}: parser_result=success requires body_usable"
            )

    @property
    def authority_family(self) -> OfficialAuthority:
        return _authority_family(self.authority)

    @property
    def has_hash_evidence(self) -> bool:
        return bool(self.response_hash or self.content_hash)

    @property
    def proves_no_usable_body(self) -> bool:
        if self.body_usable or self.body_available:
            return False
        if self.status.proves_no_usable_body:
            return True
        if self.parser_result.proves_no_usable_body and self.status.is_terminal:
            return True
        return False

    @property
    def has_unresolved_usable_body(self) -> bool:
        """Body was available/usable but not fully admitted."""

        if self.status is AttemptStatus.ADMITTED:
            return False
        if self.body_usable:
            return True
        if self.body_available and self.parser_result.indicates_usable_body:
            return True
        if (
            self.body_available
            and self.status.indicates_body_present
            and self.status is not AttemptStatus.ADMITTED
        ):
            # Fetched/parsed body that never reached admission.
            if self.parser_result is ParserResult.SUCCESS:
                return True
            if self.status in {
                AttemptStatus.FETCHED,
                AttemptStatus.HASH_VERIFIED,
                AttemptStatus.PARSED,
            }:
                return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "authority": self.authority.value,
            "content_format": self.content_format.value,
            "url": self.url,
            "observed_at": self.observed_at,
            "status": self.status.value,
            "response_hash": self.response_hash,
            "content_hash": self.content_hash,
            "retry_count": self.retry_count,
            "terminal_reason": self.terminal_reason,
            "parser_result": self.parser_result.value,
            "body_available": self.body_available,
            "body_usable": self.body_usable,
            "http_status": self.http_status,
            "notes": self.notes,
        }

    @classmethod
    def from_mapping(
        cls, value: JsonMapping, *, context: str = "attempt"
    ) -> "FormatAttempt":
        raw = _as_mapping(value, context)
        return cls(
            attempt_id=raw.get("attempt_id", raw.get("id", "")),
            authority=raw.get("authority", OfficialAuthority.FEDERAL_REGISTER),
            content_format=raw.get(
                "content_format", raw.get("format", ContentFormat.HTML)
            ),
            url=raw.get("url", raw.get("official_source_url", "")),
            observed_at=raw.get("observed_at", ""),
            status=raw.get("status", AttemptStatus.PENDING),
            response_hash=raw.get("response_hash"),
            content_hash=raw.get("content_hash"),
            retry_count=raw.get("retry_count", 0),
            terminal_reason=raw.get("terminal_reason", ""),
            parser_result=raw.get("parser_result", ParserResult.NOT_RUN),
            body_available=raw.get("body_available", False),
            body_usable=raw.get("body_usable", False),
            http_status=raw.get("http_status"),
            notes=raw.get("notes", ""),
        )


@dataclass(frozen=True)
class DocumentAttemptLedger:
    """Per-document attempt ledger and typed full-text disposition."""

    document_number: str
    publication_date: str
    disposition: FulltextDisposition
    attempts: tuple[FormatAttempt, ...] = ()
    allowed_reason: Optional[str] = None
    admitted_content_hash: Optional[str] = None
    legal_id: Optional[str] = None
    notes: str = ""

    def __post_init__(self) -> None:
        doc = validate_document_number(self.document_number)
        pub = validate_calendar_date(self.publication_date, name="publication_date")
        object.__setattr__(self, "document_number", doc)
        object.__setattr__(self, "publication_date", pub)
        object.__setattr__(
            self, "disposition", FulltextDisposition.coerce(self.disposition)
        )
        attempts = tuple(
            item if isinstance(item, FormatAttempt) else FormatAttempt.from_mapping(item)
            for item in (self.attempts or ())
        )
        object.__setattr__(self, "attempts", attempts)
        if self.allowed_reason is not None and str(self.allowed_reason).strip():
            # Validate against allow-list when provided.
            reason = AllowedNonBodyReason.coerce(self.allowed_reason)
            object.__setattr__(self, "allowed_reason", reason.value)
        else:
            object.__setattr__(self, "allowed_reason", None)
        if self.admitted_content_hash is not None and str(
            self.admitted_content_hash
        ).strip():
            object.__setattr__(
                self,
                "admitted_content_hash",
                normalize_sha256(
                    self.admitted_content_hash, name="admitted_content_hash"
                ),
            )
        else:
            object.__setattr__(self, "admitted_content_hash", None)
        if self.legal_id is not None and str(self.legal_id).strip():
            object.__setattr__(
                self,
                "legal_id",
                _require_non_empty_str(self.legal_id, "legal_id", maximum=256),
            )
        else:
            object.__setattr__(self, "legal_id", build_legal_id(doc, pub))
        object.__setattr__(self, "notes", str(self.notes or ""))

    @property
    def observed_ats(self) -> tuple[datetime, ...]:
        return tuple(
            parse_utc_timestamp(a.observed_at, name="observed_at") for a in self.attempts
        )

    @property
    def first_observed_at(self) -> Optional[datetime]:
        times = self.observed_ats
        return min(times) if times else None

    @property
    def last_observed_at(self) -> Optional[datetime]:
        times = self.observed_ats
        return max(times) if times else None

    @property
    def exhausted_authorities(self) -> frozenset[OfficialAuthority]:
        """Authorities with at least one terminal no-usable-body attempt."""

        found: set[OfficialAuthority] = set()
        for attempt in self.attempts:
            if attempt.proves_no_usable_body:
                found.add(attempt.authority_family)
        return frozenset(found)

    @property
    def attempted_authorities(self) -> frozenset[OfficialAuthority]:
        return frozenset(a.authority_family for a in self.attempts)

    @property
    def admitted_attempts(self) -> tuple[FormatAttempt, ...]:
        return tuple(a for a in self.attempts if a.status is AttemptStatus.ADMITTED)

    @property
    def has_unresolved_usable_body(self) -> bool:
        return any(a.has_unresolved_usable_body for a in self.attempts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_number": self.document_number,
            "publication_date": self.publication_date,
            "disposition": self.disposition.value,
            "attempts": [a.to_dict() for a in self.attempts],
            "allowed_reason": self.allowed_reason,
            "admitted_content_hash": self.admitted_content_hash,
            "legal_id": self.legal_id,
            "notes": self.notes,
        }

    @classmethod
    def from_mapping(
        cls, value: JsonMapping, *, context: str = "document"
    ) -> "DocumentAttemptLedger":
        raw = _as_mapping(value, context)
        attempts = raw.get("attempts") or ()
        return cls(
            document_number=raw.get("document_number", ""),
            publication_date=raw.get("publication_date", ""),
            disposition=raw.get(
                "disposition",
                raw.get("text_availability", FulltextDisposition.PENDING),
            ),
            attempts=tuple(attempts),
            allowed_reason=raw.get("allowed_reason", raw.get("admission_reason")),
            admitted_content_hash=raw.get(
                "admitted_content_hash", raw.get("content_hash")
            ),
            legal_id=raw.get("legal_id"),
            notes=raw.get("notes", ""),
        )


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FulltextAttemptReceipt:
    """Sealed per-document full-text attempt receipt for one acquisition cohort."""

    receipt_id: str
    observation_cutoff: str
    cutoff_sealed_at: str
    receipt_created_at: str
    documents: tuple[DocumentAttemptLedger, ...]
    release_point: Optional[str] = None
    previous_public_pin: str = PREVIOUS_PUBLIC_PIN
    schema_version: str = SCHEMA_VERSION
    task_id: str = TASK_ID
    goal_id: str = GOAL_ID
    notes: str = ""
    currentness_disclaimer: str = CURRENTNESS_DISCLAIMER

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "receipt_id",
            _require_non_empty_str(self.receipt_id, "receipt_id", maximum=128),
        )
        try:
            cutoff = require_immutable_observation_cutoff(self.observation_cutoff)
        except MutableCutoffError:
            raise
        object.__setattr__(self, "observation_cutoff", cutoff)
        object.__setattr__(
            self,
            "cutoff_sealed_at",
            require_strict_utc_z_timestamp(
                self.cutoff_sealed_at, name="cutoff_sealed_at"
            ),
        )
        object.__setattr__(
            self,
            "receipt_created_at",
            require_strict_utc_z_timestamp(
                self.receipt_created_at, name="receipt_created_at"
            ),
        )
        documents = tuple(
            item
            if isinstance(item, DocumentAttemptLedger)
            else DocumentAttemptLedger.from_mapping(item)
            for item in (self.documents or ())
        )
        if not documents:
            raise AttemptEvidenceError("documents must be non-empty")
        object.__setattr__(self, "documents", documents)
        if self.release_point is not None and str(self.release_point).strip():
            object.__setattr__(
                self,
                "release_point",
                _require_non_empty_str(self.release_point, "release_point", maximum=256),
            )
            if is_mutable_cutoff(self.release_point):
                raise MutableCutoffError(
                    f"release_point must be immutable, got {self.release_point!r}"
                )
        else:
            object.__setattr__(self, "release_point", cutoff_release_point(cutoff))
        object.__setattr__(
            self,
            "previous_public_pin",
            _require_non_empty_str(
                self.previous_public_pin, "previous_public_pin", maximum=128
            ),
        )
        if is_mutable_cutoff(self.previous_public_pin):
            raise MutableCutoffError(
                f"previous_public_pin must be immutable, got {self.previous_public_pin!r}"
            )
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version", maximum=128),
        )
        object.__setattr__(
            self, "task_id", _require_non_empty_str(self.task_id, "task_id", maximum=32)
        )
        object.__setattr__(
            self, "goal_id", _require_non_empty_str(self.goal_id, "goal_id", maximum=32)
        )
        object.__setattr__(self, "notes", str(self.notes or ""))
        object.__setattr__(
            self,
            "currentness_disclaimer",
            _require_non_empty_str(
                self.currentness_disclaimer, "currentness_disclaimer", maximum=2048
            ),
        )

    @property
    def all_attempts(self) -> tuple[FormatAttempt, ...]:
        attempts: list[FormatAttempt] = []
        for doc in self.documents:
            attempts.extend(doc.attempts)
        return tuple(attempts)

    @property
    def first_observed_at(self) -> Optional[datetime]:
        times = [
            parse_utc_timestamp(a.observed_at, name="observed_at")
            for a in self.all_attempts
        ]
        return min(times) if times else None

    @property
    def last_observed_at(self) -> Optional[datetime]:
        times = [
            parse_utc_timestamp(a.observed_at, name="observed_at")
            for a in self.all_attempts
        ]
        return max(times) if times else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "observation_cutoff": self.observation_cutoff,
            "cutoff_sealed_at": self.cutoff_sealed_at,
            "receipt_created_at": self.receipt_created_at,
            "documents": [d.to_dict() for d in self.documents],
            "release_point": self.release_point,
            "previous_public_pin": self.previous_public_pin,
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "goal_id": self.goal_id,
            "notes": self.notes,
            "currentness_disclaimer": self.currentness_disclaimer,
        }

    @classmethod
    def from_mapping(cls, value: JsonMapping) -> "FulltextAttemptReceipt":
        raw = _as_mapping(value, "fulltext_attempt_receipt")
        return cls(
            receipt_id=raw.get("receipt_id", ""),
            observation_cutoff=raw.get(
                "observation_cutoff", DEFAULT_OBSERVATION_CUTOFF
            ),
            cutoff_sealed_at=raw.get("cutoff_sealed_at", ""),
            receipt_created_at=raw.get("receipt_created_at", ""),
            documents=tuple(raw.get("documents") or ()),
            release_point=raw.get("release_point"),
            previous_public_pin=raw.get(
                "previous_public_pin", PREVIOUS_PUBLIC_PIN
            ),
            schema_version=raw.get("schema_version", SCHEMA_VERSION),
            task_id=raw.get("task_id", TASK_ID),
            goal_id=raw.get("goal_id", GOAL_ID),
            notes=raw.get("notes", ""),
            currentness_disclaimer=raw.get(
                "currentness_disclaimer", CURRENTNESS_DISCLAIMER
            ),
        )


# ---------------------------------------------------------------------------
# Gate result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateFinding:
    """One typed finding from the full-text attempt gate."""

    kind: FailureKind
    message: str
    path: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", FailureKind.coerce(self.kind))
        object.__setattr__(
            self,
            "message",
            _require_non_empty_str(self.message, "message", maximum=2048),
        )
        object.__setattr__(self, "path", str(self.path or ""))
        if not isinstance(self.details, Mapping):
            raise FederalRegisterFulltextGateError("details must be a mapping")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "message": self.message,
            "path": self.path,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class GateResult:
    """Gate evaluation outcome for one full-text attempt receipt."""

    verdict: GateVerdict
    receipt_id: str
    findings: tuple[GateFinding, ...]
    observation_cutoff: str
    document_count: int
    failed_final_count: int
    pending_count: int
    admitted_full_text_count: int
    non_body_count: int

    @property
    def passed(self) -> bool:
        return self.verdict is GateVerdict.PASS

    @property
    def failure_kinds(self) -> tuple[str, ...]:
        return tuple(sorted({finding.kind.value for finding in self.findings}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "receipt_id": self.receipt_id,
            "findings": [f.to_dict() for f in self.findings],
            "failure_kinds": list(self.failure_kinds),
            "observation_cutoff": self.observation_cutoff,
            "document_count": self.document_count,
            "failed_final_count": self.failed_final_count,
            "pending_count": self.pending_count,
            "admitted_full_text_count": self.admitted_full_text_count,
            "non_body_count": self.non_body_count,
        }


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _finding(
    kind: FailureKind,
    message: str,
    *,
    path: str = "",
    **details: Any,
) -> GateFinding:
    return GateFinding(kind=kind, message=message, path=path, details=details)


def _classify_seal_timestamp_error(exc: BaseException) -> FailureKind:
    """Map a seal/timestamp exception message to a typed failure kind."""

    msg = str(exc).lower()
    if "trailing z" in msg or "timezone-aware" in msg or "ending in z" in msg:
        return FailureKind.NON_UTC_TIMESTAMP
    if "malformed" in msg or "iso-8601" in msg:
        return FailureKind.MALFORMED_TIMESTAMP
    if "required" in msg or "non-empty" in msg:
        return FailureKind.MISSING_TIMESTAMP
    return FailureKind.MISSING_TIMESTAMP


def _validate_timestamps_against_clock(
    receipt: FulltextAttemptReceipt,
    *,
    now: datetime,
    max_future_skew: timedelta,
) -> list[GateFinding]:
    findings: list[GateFinding] = []
    horizon = now + max_future_skew

    def _check(name: str, value: str, path: str) -> Optional[datetime]:
        try:
            dt = parse_utc_timestamp(value, name=name)
        except TimestampError as exc:
            findings.append(
                _finding(
                    FailureKind.MALFORMED_TIMESTAMP,
                    str(exc),
                    path=path,
                )
            )
            return None
        if dt > horizon:
            findings.append(
                _finding(
                    FailureKind.TIMESTAMP_AFTER_VERIFIER,
                    f"{name}={value!r} is later than verifier clock "
                    f"{format_utc_timestamp(now)}",
                    path=path,
                    timestamp=value,
                    verifier_clock=format_utc_timestamp(now),
                )
            )
        return dt

    cutoff_dt = _check(
        "cutoff_sealed_at", receipt.cutoff_sealed_at, "cutoff_sealed_at"
    )
    receipt_dt = _check(
        "receipt_created_at", receipt.receipt_created_at, "receipt_created_at"
    )

    # Observation cutoff must not be a future pin relative to verifier.
    try:
        obs_cutoff_dt = parse_utc_timestamp(
            receipt.observation_cutoff, name="observation_cutoff"
        )
        if obs_cutoff_dt > horizon:
            findings.append(
                _finding(
                    FailureKind.FUTURE_CUTOFF,
                    f"observation_cutoff={receipt.observation_cutoff!r} is in the "
                    f"future relative to verifier clock "
                    f"{format_utc_timestamp(now)}",
                    path="observation_cutoff",
                )
            )
    except TimestampError as exc:
        findings.append(
            _finding(FailureKind.MALFORMED_TIMESTAMP, str(exc), path="observation_cutoff")
        )

    first_obs = receipt.first_observed_at
    last_obs = receipt.last_observed_at

    for idx, attempt in enumerate(receipt.all_attempts):
        path = f"attempts[{idx}].observed_at"
        # Attempts already validated as Z at parse; still check clock.
        try:
            obs = parse_utc_timestamp(attempt.observed_at, name="observed_at")
        except TimestampError as exc:
            findings.append(
                _finding(FailureKind.MALFORMED_TIMESTAMP, str(exc), path=path)
            )
            continue
        if obs > horizon:
            findings.append(
                _finding(
                    FailureKind.TIMESTAMP_AFTER_VERIFIER,
                    f"observed_at={attempt.observed_at!r} is later than verifier "
                    f"clock {format_utc_timestamp(now)}",
                    path=path,
                    attempt_id=attempt.attempt_id,
                )
            )

    if cutoff_dt is not None and first_obs is not None and cutoff_dt > first_obs:
        findings.append(
            _finding(
                FailureKind.CUTOFF_SEAL_AFTER_OBSERVATION,
                f"cutoff_sealed_at={receipt.cutoff_sealed_at!r} is after the first "
                f"acquisition observation {format_utc_timestamp(first_obs)}",
                path="cutoff_sealed_at",
                first_observed_at=format_utc_timestamp(first_obs),
            )
        )

    if receipt_dt is not None and last_obs is not None and receipt_dt < last_obs:
        findings.append(
            _finding(
                FailureKind.RECEIPT_BEFORE_LAST_ATTEMPT,
                f"receipt_created_at={receipt.receipt_created_at!r} is before the "
                f"last recorded attempt {format_utc_timestamp(last_obs)}",
                path="receipt_created_at",
                last_observed_at=format_utc_timestamp(last_obs),
            )
        )

    return findings


def _validate_attempt_hashes(
    document: DocumentAttemptLedger,
    *,
    doc_path: str,
) -> list[GateFinding]:
    findings: list[GateFinding] = []
    for idx, attempt in enumerate(document.attempts):
        path = f"{doc_path}.attempts[{idx}]"
        # Any terminal fetched/verified/parsed/admitted attempt needs a hash.
        needs_hash = attempt.status in {
            AttemptStatus.FETCHED,
            AttemptStatus.HASH_VERIFIED,
            AttemptStatus.PARSED,
            AttemptStatus.ADMITTED,
            AttemptStatus.NO_BODY,
        }
        if needs_hash and not attempt.has_hash_evidence:
            findings.append(
                _finding(
                    FailureKind.MISSING_HASH,
                    f"attempt {attempt.attempt_id!r} status={attempt.status.value} "
                    "requires response_hash or content_hash",
                    path=path,
                    attempt_id=attempt.attempt_id,
                    status=attempt.status.value,
                )
            )
        # Admitted attempt must be fully pipeline-complete.
        if attempt.status is AttemptStatus.ADMITTED:
            if not attempt.content_hash and not attempt.response_hash:
                findings.append(
                    _finding(
                        FailureKind.MISSING_HASH,
                        f"admitted attempt {attempt.attempt_id!r} requires hash evidence",
                        path=path,
                        attempt_id=attempt.attempt_id,
                    )
                )
            if attempt.parser_result is not ParserResult.SUCCESS:
                findings.append(
                    _finding(
                        FailureKind.BODY_NOT_ADMITTED,
                        f"admitted attempt {attempt.attempt_id!r} requires "
                        f"parser_result=success, got {attempt.parser_result.value}",
                        path=path,
                        attempt_id=attempt.attempt_id,
                    )
                )
    if document.disposition.has_usable_body:
        if not document.admitted_content_hash:
            findings.append(
                _finding(
                    FailureKind.MISSING_HASH,
                    f"document {document.document_number!r} disposition="
                    f"{document.disposition.value} requires admitted_content_hash",
                    path=f"{doc_path}.admitted_content_hash",
                )
            )
        if not document.admitted_attempts:
            findings.append(
                _finding(
                    FailureKind.BODY_NOT_ADMITTED,
                    f"document {document.document_number!r} claims body-bearing "
                    f"disposition {document.disposition.value} without an admitted attempt",
                    path=doc_path,
                )
            )
        else:
            # At least one admitted attempt must be hash-verified + parsed.
            ok = False
            for attempt in document.admitted_attempts:
                if (
                    attempt.has_hash_evidence
                    and attempt.parser_result is ParserResult.SUCCESS
                    and attempt.body_usable
                ):
                    ok = True
                    break
            if not ok:
                findings.append(
                    _finding(
                        FailureKind.BODY_NOT_ADMITTED,
                        f"document {document.document_number!r}: admitted full text "
                        "must be fetched, hash-verified, successfully parsed, and "
                        "body_usable",
                        path=doc_path,
                    )
                )
    return findings


def _validate_document_disposition(
    document: DocumentAttemptLedger,
    *,
    doc_path: str,
) -> list[GateFinding]:
    findings: list[GateFinding] = []
    disp = document.disposition

    if disp is FulltextDisposition.FAILED_FINAL:
        findings.append(
            _finding(
                FailureKind.FAILED_FINAL,
                f"document {document.document_number!r} disposition=failed_final "
                "blocks acquisition and publication",
                path=doc_path,
            )
        )
        return findings

    if disp is FulltextDisposition.PENDING:
        findings.append(
            _finding(
                FailureKind.PENDING,
                f"document {document.document_number!r} disposition=pending "
                "blocks acquisition and publication",
                path=doc_path,
            )
        )
        return findings

    if not document.attempts:
        findings.append(
            _finding(
                FailureKind.MISSING_ATTEMPT_EVIDENCE,
                f"document {document.document_number!r} has empty attempt ledger",
                path=f"{doc_path}.attempts",
            )
        )

    # Pending attempts always block.
    for idx, attempt in enumerate(document.attempts):
        if attempt.status.is_pending:
            findings.append(
                _finding(
                    FailureKind.PENDING,
                    f"attempt {attempt.attempt_id!r} is still pending",
                    path=f"{doc_path}.attempts[{idx}]",
                    attempt_id=attempt.attempt_id,
                )
            )

    # Unresolved usable body: never erasable by exclusion/quarantine.
    if document.has_unresolved_usable_body:
        if disp in {
            FulltextDisposition.EXCLUDED,
            FulltextDisposition.QUARANTINED,
        }:
            findings.append(
                _finding(
                    FailureKind.EXCLUSION_ERASES_FAILURE,
                    f"document {document.document_number!r}: disposition="
                    f"{disp.value} cannot erase an available/retrieved official "
                    "body that was not admitted as full text",
                    path=doc_path,
                )
            )
        else:
            findings.append(
                _finding(
                    FailureKind.BODY_NOT_ADMITTED,
                    f"document {document.document_number!r}: available or retrieved "
                    "official body was not fetched, hash-verified, successfully "
                    "parsed, and admitted as full text",
                    path=doc_path,
                )
            )

    if disp.requires_exhaustion:
        if not document.allowed_reason:
            findings.append(
                _finding(
                    FailureKind.MISSING_ALLOWED_REASON,
                    f"document {document.document_number!r} disposition="
                    f"{disp.value} requires an allowed reason and complete "
                    "attempt exhaustion evidence",
                    path=f"{doc_path}.allowed_reason",
                )
            )
        # Require both official full-text authorities exhausted with no usable body.
        required = {
            OfficialAuthority.FEDERAL_REGISTER,
            OfficialAuthority.GOVINFO,
        }
        exhausted = set(document.exhausted_authorities)
        missing = sorted(a.value for a in required - exhausted)
        if missing:
            findings.append(
                _finding(
                    FailureKind.INCOMPLETE_EXHAUSTION,
                    f"document {document.document_number!r} disposition="
                    f"{disp.value} lacks no-usable-body evidence for authorities: "
                    f"{missing}; FederalRegister.gov and GovInfo must both be exhausted",
                    path=f"{doc_path}.attempts",
                    missing_authorities=missing,
                    exhausted_authorities=sorted(a.value for a in exhausted),
                )
            )
        # Every attempt that is not no-body must not claim usable body (already
        # covered) and terminal reasons should be present on no-body attempts.
        for idx, attempt in enumerate(document.attempts):
            if attempt.proves_no_usable_body and not str(attempt.terminal_reason).strip():
                findings.append(
                    _finding(
                        FailureKind.MISSING_ATTEMPT_EVIDENCE,
                        f"attempt {attempt.attempt_id!r} proves no usable body but "
                        "lacks terminal_reason",
                        path=f"{doc_path}.attempts[{idx}].terminal_reason",
                        attempt_id=attempt.attempt_id,
                    )
                )

    findings.extend(_validate_attempt_hashes(document, doc_path=doc_path))
    return findings


def evaluate_fulltext_attempt_receipt(
    receipt: FulltextAttemptReceipt | JsonMapping,
    *,
    now: Optional[datetime | str | ClockFn] = None,
    max_future_skew: timedelta = DEFAULT_MAX_FUTURE_SKEW,
    raise_on_failure: bool = False,
) -> GateResult:
    """Evaluate one full-text attempt receipt against fail-closed gate rules."""

    findings: list[GateFinding] = []

    def _failed_parse_result(
        *,
        kind: FailureKind,
        message: str,
        path: str,
        raw: Any,
    ) -> GateResult:
        mapping = raw if isinstance(raw, Mapping) else {}
        result = GateResult(
            verdict=GateVerdict.FAIL,
            receipt_id=str(mapping.get("receipt_id") or ""),
            findings=(_finding(kind, message, path=path),),
            observation_cutoff=str(mapping.get("observation_cutoff") or ""),
            document_count=0,
            failed_final_count=0,
            pending_count=0,
            admitted_full_text_count=0,
            non_body_count=0,
        )
        if raise_on_failure:
            raise_for_findings(result)
        return result

    if not isinstance(receipt, FulltextAttemptReceipt):
        raw_receipt = receipt
        try:
            receipt = FulltextAttemptReceipt.from_mapping(receipt)
        except MutableCutoffError as exc:
            return _failed_parse_result(
                kind=FailureKind.MUTABLE_CUTOFF,
                message=str(exc),
                path="observation_cutoff",
                raw=raw_receipt,
            )
        except SealTimestampError as exc:
            return _failed_parse_result(
                kind=_classify_seal_timestamp_error(exc),
                message=str(exc),
                path="timestamps",
                raw=raw_receipt,
            )
        except (
            AttemptEvidenceError,
            DispositionAdmissionError,
            OfficialAuthorityError,
            FederalRegisterFulltextGateError,
        ) as exc:
            return _failed_parse_result(
                kind=FailureKind.OTHER,
                message=str(exc),
                path="receipt",
                raw=raw_receipt,
            )

    # Resolve verifier clock.
    if now is None:
        clock = fixture_verifier_now()
    elif callable(now):
        clock = now()
        if clock.tzinfo is None:
            raise SealTimestampError("verifier clock must be timezone-aware UTC")
        clock = clock.astimezone(timezone.utc)
    elif isinstance(now, datetime):
        if now.tzinfo is None:
            raise SealTimestampError("verifier clock must be timezone-aware UTC")
        clock = now.astimezone(timezone.utc)
    else:
        clock = parse_utc_timestamp(now, name="verifier_clock")

    findings.extend(
        _validate_timestamps_against_clock(
            receipt, now=clock, max_future_skew=max_future_skew
        )
    )

    failed_final = 0
    pending = 0
    admitted = 0
    non_body = 0

    for doc_idx, document in enumerate(receipt.documents):
        doc_path = f"documents[{doc_idx}]"
        if document.disposition is FulltextDisposition.FAILED_FINAL:
            failed_final += 1
        elif document.disposition is FulltextDisposition.PENDING:
            pending += 1
        elif document.disposition.has_usable_body:
            admitted += 1
        else:
            non_body += 1
        findings.extend(
            _validate_document_disposition(document, doc_path=doc_path)
        )

    # De-duplicate findings by (kind, path, message) while preserving order.
    seen: set[tuple[str, str, str]] = set()
    unique: list[GateFinding] = []
    for finding in findings:
        key = (finding.kind.value, finding.path, finding.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)

    verdict = GateVerdict.PASS if not unique else GateVerdict.FAIL
    result = GateResult(
        verdict=verdict,
        receipt_id=receipt.receipt_id,
        findings=tuple(unique),
        observation_cutoff=receipt.observation_cutoff,
        document_count=len(receipt.documents),
        failed_final_count=failed_final,
        pending_count=pending,
        admitted_full_text_count=admitted,
        non_body_count=non_body,
    )
    if raise_on_failure and not result.passed:
        raise_for_findings(result)
    return result


def raise_for_findings(result: GateResult) -> None:
    """Raise a typed error for the first finding in a failed gate result."""

    if result.passed or not result.findings:
        return
    finding = result.findings[0]
    kind = finding.kind
    message = finding.message
    mapping = {
        FailureKind.FAILED_FINAL: FailedFinalAdmissionError,
        FailureKind.PENDING: FailedFinalAdmissionError,
        FailureKind.MISSING_HASH: MissingHashError,
        FailureKind.MISSING_TIMESTAMP: SealTimestampError,
        FailureKind.MALFORMED_TIMESTAMP: SealTimestampError,
        FailureKind.NON_UTC_TIMESTAMP: SealTimestampError,
        FailureKind.MUTABLE_CUTOFF: MutableCutoffError,
        FailureKind.FUTURE_CUTOFF: SealTimestampError,
        FailureKind.CUTOFF_SEAL_AFTER_OBSERVATION: SealTimestampError,
        FailureKind.RECEIPT_BEFORE_LAST_ATTEMPT: SealTimestampError,
        FailureKind.TIMESTAMP_AFTER_VERIFIER: SealTimestampError,
        FailureKind.MISSING_ALLOWED_REASON: DispositionAdmissionError,
        FailureKind.INCOMPLETE_EXHAUSTION: ExhaustionError,
        FailureKind.BODY_NOT_ADMITTED: UnresolvedBodyError,
        FailureKind.EXCLUSION_ERASES_FAILURE: UnresolvedBodyError,
        FailureKind.MISSING_ATTEMPT_EVIDENCE: AttemptEvidenceError,
        FailureKind.OFFICIAL_AUTHORITY: OfficialAuthorityError,
    }
    exc_cls = mapping.get(kind, FederalRegisterFulltextGateError)
    raise exc_cls(message)


def assert_fulltext_admission(
    receipt: FulltextAttemptReceipt | JsonMapping,
    *,
    now: Optional[datetime | str | ClockFn] = None,
    max_future_skew: timedelta = DEFAULT_MAX_FUTURE_SKEW,
) -> GateResult:
    """Evaluate *receipt* and raise if the gate fails."""

    return evaluate_fulltext_attempt_receipt(
        receipt,
        now=now,
        max_future_skew=max_future_skew,
        raise_on_failure=True,
    )


# ---------------------------------------------------------------------------
# Fixture load / expand / evaluate
# ---------------------------------------------------------------------------


def load_fulltext_fixture_payload(
    path: Optional[PathLike] = None,
) -> dict[str, Any]:
    """Load the sealed full-text attempt-receipts fixture as a raw mapping."""

    fixture_path = Path(path) if path is not None else default_fulltext_fixture_path()
    if not fixture_path.is_file():
        raise FixtureSchemaError(f"fulltext attempt fixture not found: {fixture_path}")
    try:
        raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FixtureSchemaError(
            f"fulltext attempt fixture JSON is invalid: {exc}"
        ) from exc
    if not isinstance(raw, Mapping):
        raise FixtureSchemaError("fulltext attempt fixture root must be a JSON object")
    schema = raw.get("schema_version")
    if schema != FIXTURE_SCHEMA_VERSION:
        raise FixtureSchemaError(
            f"schema_version must be {FIXTURE_SCHEMA_VERSION!r}, got {schema!r}"
        )
    task_id = raw.get("task_id")
    if task_id != TASK_ID:
        raise FixtureSchemaError(f"task_id must be {TASK_ID!r}, got {task_id!r}")
    return dict(raw)


def expand_fulltext_fixture_cases(
    payload: Optional[JsonMapping] = None,
    *,
    path: Optional[PathLike] = None,
) -> list[dict[str, Any]]:
    """Return fixture cases (pass + adversarial fail recipes)."""

    if payload is None:
        payload = load_fulltext_fixture_payload(path)
    cases = payload.get("cases")
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)):
        raise FixtureSchemaError("cases must be a list")
    if not cases:
        raise FixtureSchemaError("cases must be non-empty")
    expanded: list[dict[str, Any]] = []
    for idx, case in enumerate(cases):
        if not isinstance(case, Mapping):
            raise FixtureSchemaError(f"cases[{idx}] must be a mapping")
        case_id = case.get("case_id")
        if not case_id:
            raise FixtureSchemaError(f"cases[{idx}].case_id is required")
        expected = GateVerdict.coerce(case.get("expected_status", "fail"))
        expected_kinds = tuple(
            FailureKind.coerce(item).value
            for item in (case.get("expected_kinds") or ())
        )
        receipt_raw = case.get("receipt")
        if not isinstance(receipt_raw, Mapping):
            raise FixtureSchemaError(f"cases[{idx}].receipt must be a mapping")
        receipt = dict(receipt_raw)
        receipt.setdefault(
            "observation_cutoff",
            payload.get("observation_cutoff", DEFAULT_OBSERVATION_CUTOFF),
        )
        receipt.setdefault(
            "cutoff_sealed_at",
            payload.get("cutoff_sealed_at", "2026-08-10T00:00:00Z"),
        )
        receipt.setdefault(
            "receipt_created_at",
            payload.get("receipt_created_at", "2026-08-10T11:00:00Z"),
        )
        receipt.setdefault(
            "previous_public_pin",
            payload.get("previous_public_pin", PREVIOUS_PUBLIC_PIN),
        )
        receipt.setdefault("task_id", TASK_ID)
        receipt.setdefault("goal_id", GOAL_ID)
        receipt.setdefault("schema_version", SCHEMA_VERSION)
        receipt.setdefault("currentness_disclaimer", CURRENTNESS_DISCLAIMER)
        if "receipt_id" not in receipt:
            receipt["receipt_id"] = str(case_id)
        expanded.append(
            {
                "case_id": str(case_id),
                "expected_status": expected.value,
                "expected_kinds": list(expected_kinds),
                "receipt": receipt,
                "notes": str(case.get("notes") or ""),
            }
        )
    return expanded


def evaluate_fixture_case(
    case: JsonMapping,
    *,
    now: Optional[datetime | str | ClockFn] = None,
) -> GateResult:
    """Evaluate one expanded fixture case and return the gate result."""

    raw = _as_mapping(case, "case")
    receipt_raw = raw.get("receipt")
    if not isinstance(receipt_raw, Mapping):
        raise FixtureSchemaError("case.receipt must be a mapping")
    clock = now if now is not None else fixture_verifier_now()
    try:
        return evaluate_fulltext_attempt_receipt(
            receipt_raw, now=clock, raise_on_failure=False
        )
    except MutableCutoffError as exc:
        return GateResult(
            verdict=GateVerdict.FAIL,
            receipt_id=str(receipt_raw.get("receipt_id") or raw.get("case_id") or ""),
            findings=(
                _finding(
                    FailureKind.MUTABLE_CUTOFF,
                    str(exc),
                    path="observation_cutoff",
                ),
            ),
            observation_cutoff=str(receipt_raw.get("observation_cutoff") or ""),
            document_count=0,
            failed_final_count=0,
            pending_count=0,
            admitted_full_text_count=0,
            non_body_count=0,
        )
    except SealTimestampError as exc:
        kind = _classify_seal_timestamp_error(exc)
        return GateResult(
            verdict=GateVerdict.FAIL,
            receipt_id=str(receipt_raw.get("receipt_id") or raw.get("case_id") or ""),
            findings=(_finding(kind, str(exc), path="timestamps"),),
            observation_cutoff=str(receipt_raw.get("observation_cutoff") or ""),
            document_count=0,
            failed_final_count=0,
            pending_count=0,
            admitted_full_text_count=0,
            non_body_count=0,
        )


def evaluate_fulltext_fixture(
    path: Optional[PathLike] = None,
    *,
    payload: Optional[JsonMapping] = None,
    now: Optional[datetime | str | ClockFn] = None,
) -> list[dict[str, Any]]:
    """Evaluate every fixture case; return per-case gate summaries."""

    cases = expand_fulltext_fixture_cases(payload, path=path)
    results: list[dict[str, Any]] = []
    for case in cases:
        result = evaluate_fixture_case(case, now=now)
        expected = GateVerdict.coerce(case["expected_status"])
        expected_kinds = set(case.get("expected_kinds") or [])
        actual_kinds = set(result.failure_kinds)
        status_match = result.verdict is expected
        kinds_match = (
            True
            if expected is GateVerdict.PASS
            else expected_kinds.issubset(actual_kinds)
        )
        results.append(
            {
                "case_id": case["case_id"],
                "expected_status": expected.value,
                "actual_status": result.verdict.value,
                "expected_kinds": sorted(expected_kinds),
                "actual_kinds": list(result.failure_kinds),
                "status_match": status_match,
                "kinds_match": kinds_match,
                "passed": status_match and kinds_match,
                "result": result.to_dict(),
            }
        )
    return results


def assert_fixture_expectations(
    path: Optional[PathLike] = None,
    *,
    payload: Optional[JsonMapping] = None,
    now: Optional[datetime | str | ClockFn] = None,
) -> list[dict[str, Any]]:
    """Evaluate the fixture and raise if any case mismatches expectations."""

    results = evaluate_fulltext_fixture(path=path, payload=payload, now=now)
    failures = [row for row in results if not row["passed"]]
    if failures:
        summary = "; ".join(
            f"{row['case_id']}: expected={row['expected_status']}/"
            f"{row['expected_kinds']} actual={row['actual_status']}/"
            f"{row['actual_kinds']}"
            for row in failures
        )
        raise FederalRegisterFulltextGateError(
            f"fulltext attempt fixture expectation mismatches: {summary}"
        )
    return results


# ---------------------------------------------------------------------------
# Example / builder helpers for tests and sealed fixtures
# ---------------------------------------------------------------------------


def _hash(label: str) -> str:
    return content_sha256(f"fr-fulltext:{label}")


def _attempt(
    *,
    attempt_id: str,
    authority: str,
    content_format: str,
    url: str,
    observed_at: str,
    status: str,
    parser_result: str,
    body_available: bool,
    body_usable: bool,
    terminal_reason: str = "",
    retry_count: int = 0,
    with_hash: bool = True,
    http_status: int = 200,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "attempt_id": attempt_id,
        "authority": authority,
        "content_format": content_format,
        "url": url,
        "observed_at": observed_at,
        "status": status,
        "retry_count": retry_count,
        "terminal_reason": terminal_reason,
        "parser_result": parser_result,
        "body_available": body_available,
        "body_usable": body_usable,
        "http_status": http_status,
    }
    if with_hash:
        payload["response_hash"] = _hash(f"response:{attempt_id}")
        if body_usable:
            payload["content_hash"] = _hash(f"content:{attempt_id}")
    return payload


def _fr_html_url(document_number: str) -> str:
    return f"{FEDERAL_REGISTER_SITE}/documents/{document_number}"


def _govinfo_url(document_number: str) -> str:
    return f"{GOVINFO_SITE}/app/details/FR-{document_number}"


def example_full_text_document(
    *,
    document_number: str = "2026-04567",
    publication_date: str = "2026-03-15",
    fr_observed_at: str = "2026-08-10T01:00:00Z",
) -> dict[str, Any]:
    """Return a document ledger admitted as full text from FederalRegister.gov."""

    attempt = _attempt(
        attempt_id=f"{document_number}-fr-html",
        authority=OfficialAuthority.FEDERAL_REGISTER.value,
        content_format=ContentFormat.HTML.value,
        url=_fr_html_url(document_number),
        observed_at=fr_observed_at,
        status=AttemptStatus.ADMITTED.value,
        parser_result=ParserResult.SUCCESS.value,
        body_available=True,
        body_usable=True,
        terminal_reason="admitted_full_text",
        retry_count=0,
    )
    return {
        "document_number": document_number,
        "publication_date": publication_date,
        "disposition": FulltextDisposition.FULL_TEXT.value,
        "attempts": [attempt],
        "admitted_content_hash": attempt["content_hash"],
        "legal_id": build_legal_id(document_number, publication_date),
        "notes": "Official HTML body admitted after hash verification and parse.",
    }


def example_exhausted_non_body_document(
    *,
    document_number: str = "2026-04568",
    publication_date: str = "2026-03-16",
    disposition: str = FulltextDisposition.METADATA_ONLY.value,
    allowed_reason: str = AllowedNonBodyReason.OFFICIAL_METADATA_ONLY.value,
    fr_observed_at: str = "2026-08-10T02:00:00Z",
    govinfo_observed_at: str = "2026-08-10T02:05:00Z",
) -> dict[str, Any]:
    """Return a non-body document with complete FR + GovInfo exhaustion evidence."""

    fr_attempt = _attempt(
        attempt_id=f"{document_number}-fr-html",
        authority=OfficialAuthority.FEDERAL_REGISTER.value,
        content_format=ContentFormat.HTML.value,
        url=_fr_html_url(document_number),
        observed_at=fr_observed_at,
        status=AttemptStatus.NO_BODY.value,
        parser_result=ParserResult.NO_BODY.value,
        body_available=False,
        body_usable=False,
        terminal_reason="official_html_has_metadata_only",
        retry_count=1,
    )
    govinfo_attempt = _attempt(
        attempt_id=f"{document_number}-govinfo-pdf",
        authority=OfficialAuthority.GOVINFO.value,
        content_format=ContentFormat.PDF.value,
        url=_govinfo_url(document_number),
        observed_at=govinfo_observed_at,
        status=AttemptStatus.NO_BODY.value,
        parser_result=ParserResult.EMPTY.value,
        body_available=False,
        body_usable=False,
        terminal_reason="govinfo_package_has_no_body",
        retry_count=1,
        http_status=404,
    )
    return {
        "document_number": document_number,
        "publication_date": publication_date,
        "disposition": disposition,
        "allowed_reason": allowed_reason,
        "attempts": [fr_attempt, govinfo_attempt],
        "notes": "Both official alternatives exhausted with no usable body.",
    }


def example_closed_fulltext_receipt(
    *,
    receipt_id: str = "fr-fulltext-closed-ok",
    observation_cutoff: str = DEFAULT_OBSERVATION_CUTOFF,
    cutoff_sealed_at: str = "2026-08-10T00:00:00Z",
    receipt_created_at: str = "2026-08-10T11:00:00Z",
) -> dict[str, Any]:
    """Return a minimal closed full-text attempt receipt that passes the gate."""

    full = example_full_text_document()
    meta = example_exhausted_non_body_document()
    return {
        "receipt_id": receipt_id,
        "observation_cutoff": observation_cutoff,
        "cutoff_sealed_at": cutoff_sealed_at,
        "receipt_created_at": receipt_created_at,
        "documents": [full, meta],
        "release_point": cutoff_release_point(observation_cutoff),
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "notes": "Sealed full-text attempt cohort for LCR-075 unit tests.",
    }


def build_default_fulltext_fixture_payload() -> dict[str, Any]:
    """Build the compact default full-text attempt-receipts fixture recipe."""

    closed = example_closed_fulltext_receipt()

    abstract_ok = example_closed_fulltext_receipt(receipt_id="fr-fulltext-abstract-ok")
    abstract_ok["documents"] = [
        example_exhausted_non_body_document(
            document_number="2026-04570",
            disposition=FulltextDisposition.ABSTRACT_ONLY.value,
            allowed_reason=AllowedNonBodyReason.OFFICIAL_ABSTRACT_ONLY.value,
        )
    ]

    missing_ok = example_closed_fulltext_receipt(receipt_id="fr-fulltext-missing-ok")
    missing_ok["documents"] = [
        example_exhausted_non_body_document(
            document_number="2026-04571",
            disposition=FulltextDisposition.MISSING_BODY_OFFICIAL.value,
            allowed_reason=AllowedNonBodyReason.OFFICIAL_BODY_UNAVAILABLE.value,
        )
    ]

    excluded_ok = example_closed_fulltext_receipt(receipt_id="fr-fulltext-excluded-ok")
    excluded_ok["documents"] = [
        example_exhausted_non_body_document(
            document_number="2026-04572",
            disposition=FulltextDisposition.EXCLUDED.value,
            allowed_reason=AllowedNonBodyReason.RIGHTS_OR_SCOPE_EXCLUSION.value,
        )
    ]

    quarantine_ok = example_closed_fulltext_receipt(
        receipt_id="fr-fulltext-quarantine-ok"
    )
    quarantine_ok["documents"] = [
        example_exhausted_non_body_document(
            document_number="2026-04573",
            disposition=FulltextDisposition.QUARANTINED.value,
            allowed_reason=AllowedNonBodyReason.CONTENT_QUARANTINE.value,
        )
    ]

    # --- Fail cases ---
    no_exhaustion = example_closed_fulltext_receipt(
        receipt_id="fr-fail-incomplete-exhaustion"
    )
    no_exhaustion["documents"] = [
        {
            "document_number": "2026-04600",
            "publication_date": "2026-03-20",
            "disposition": FulltextDisposition.METADATA_ONLY.value,
            "allowed_reason": AllowedNonBodyReason.OFFICIAL_METADATA_ONLY.value,
            # Only FR attempted; GovInfo missing.
            "attempts": [
                _attempt(
                    attempt_id="2026-04600-fr-html",
                    authority=OfficialAuthority.FEDERAL_REGISTER.value,
                    content_format=ContentFormat.HTML.value,
                    url=_fr_html_url("2026-04600"),
                    observed_at="2026-08-10T02:00:00Z",
                    status=AttemptStatus.NO_BODY.value,
                    parser_result=ParserResult.NO_BODY.value,
                    body_available=False,
                    body_usable=False,
                    terminal_reason="metadata_only",
                )
            ],
        }
    ]

    no_reason = example_closed_fulltext_receipt(receipt_id="fr-fail-missing-reason")
    no_reason_doc = example_exhausted_non_body_document(document_number="2026-04601")
    no_reason_doc.pop("allowed_reason", None)
    no_reason["documents"] = [no_reason_doc]

    body_not_admitted = example_closed_fulltext_receipt(
        receipt_id="fr-fail-body-not-admitted"
    )
    body_not_admitted["documents"] = [
        {
            "document_number": "2026-04602",
            "publication_date": "2026-03-21",
            "disposition": FulltextDisposition.METADATA_ONLY.value,
            "allowed_reason": AllowedNonBodyReason.OFFICIAL_METADATA_ONLY.value,
            "attempts": [
                _attempt(
                    attempt_id="2026-04602-fr-html",
                    authority=OfficialAuthority.FEDERAL_REGISTER.value,
                    content_format=ContentFormat.HTML.value,
                    url=_fr_html_url("2026-04602"),
                    observed_at="2026-08-10T02:00:00Z",
                    status=AttemptStatus.PARSED.value,
                    parser_result=ParserResult.SUCCESS.value,
                    body_available=True,
                    body_usable=True,
                    terminal_reason="parsed_but_not_admitted",
                ),
                _attempt(
                    attempt_id="2026-04602-govinfo-pdf",
                    authority=OfficialAuthority.GOVINFO.value,
                    content_format=ContentFormat.PDF.value,
                    url=_govinfo_url("2026-04602"),
                    observed_at="2026-08-10T02:05:00Z",
                    status=AttemptStatus.NO_BODY.value,
                    parser_result=ParserResult.EMPTY.value,
                    body_available=False,
                    body_usable=False,
                    terminal_reason="no_body",
                    http_status=404,
                ),
            ],
        }
    ]

    exclusion_erases = example_closed_fulltext_receipt(
        receipt_id="fr-fail-exclusion-erases"
    )
    exclusion_erases["documents"] = [
        {
            "document_number": "2026-04603",
            "publication_date": "2026-03-22",
            "disposition": FulltextDisposition.EXCLUDED.value,
            "allowed_reason": AllowedNonBodyReason.RIGHTS_OR_SCOPE_EXCLUSION.value,
            "attempts": [
                _attempt(
                    attempt_id="2026-04603-fr-html",
                    authority=OfficialAuthority.FEDERAL_REGISTER.value,
                    content_format=ContentFormat.HTML.value,
                    url=_fr_html_url("2026-04603"),
                    observed_at="2026-08-10T02:00:00Z",
                    status=AttemptStatus.FETCHED.value,
                    parser_result=ParserResult.SUCCESS.value,
                    body_available=True,
                    body_usable=True,
                    terminal_reason="body_fetched_then_excluded",
                ),
                _attempt(
                    attempt_id="2026-04603-govinfo-pdf",
                    authority=OfficialAuthority.GOVINFO.value,
                    content_format=ContentFormat.PDF.value,
                    url=_govinfo_url("2026-04603"),
                    observed_at="2026-08-10T02:05:00Z",
                    status=AttemptStatus.NO_BODY.value,
                    parser_result=ParserResult.EMPTY.value,
                    body_available=False,
                    body_usable=False,
                    terminal_reason="no_body",
                    http_status=404,
                ),
            ],
        }
    ]

    failed_final = example_closed_fulltext_receipt(receipt_id="fr-fail-failed-final")
    failed_final["documents"] = [
        {
            "document_number": "2026-04604",
            "publication_date": "2026-03-23",
            "disposition": FulltextDisposition.FAILED_FINAL.value,
            "attempts": [
                _attempt(
                    attempt_id="2026-04604-fr-html",
                    authority=OfficialAuthority.FEDERAL_REGISTER.value,
                    content_format=ContentFormat.HTML.value,
                    url=_fr_html_url("2026-04604"),
                    observed_at="2026-08-10T02:00:00Z",
                    status=AttemptStatus.FAILED.value,
                    parser_result=ParserResult.PARSE_ERROR.value,
                    body_available=False,
                    body_usable=False,
                    terminal_reason="permanent_fetch_failure",
                    retry_count=3,
                    http_status=500,
                )
            ],
        }
    ]

    pending = example_closed_fulltext_receipt(receipt_id="fr-fail-pending")
    pending["documents"] = [
        {
            "document_number": "2026-04605",
            "publication_date": "2026-03-24",
            "disposition": FulltextDisposition.PENDING.value,
            "attempts": [
                _attempt(
                    attempt_id="2026-04605-fr-html",
                    authority=OfficialAuthority.FEDERAL_REGISTER.value,
                    content_format=ContentFormat.HTML.value,
                    url=_fr_html_url("2026-04605"),
                    observed_at="2026-08-10T02:00:00Z",
                    status=AttemptStatus.PENDING.value,
                    parser_result=ParserResult.NOT_RUN.value,
                    body_available=False,
                    body_usable=False,
                    with_hash=False,
                    http_status=0,
                )
            ],
        }
    ]

    missing_hash = example_closed_fulltext_receipt(receipt_id="fr-fail-missing-hash")
    missing_hash_doc = example_full_text_document(document_number="2026-04606")
    missing_hash_doc["attempts"][0].pop("response_hash", None)
    missing_hash_doc["attempts"][0].pop("content_hash", None)
    missing_hash_doc["admitted_content_hash"] = None
    missing_hash["documents"] = [missing_hash_doc]

    missing_seal = example_closed_fulltext_receipt(receipt_id="fr-fail-missing-seal")
    missing_seal["cutoff_sealed_at"] = ""

    malformed_ts = example_closed_fulltext_receipt(receipt_id="fr-fail-malformed-ts")
    malformed_ts["receipt_created_at"] = "not-a-timestamp"

    non_utc = example_closed_fulltext_receipt(receipt_id="fr-fail-non-utc")
    non_utc["receipt_created_at"] = "2026-08-10T11:00:00+00:00"

    mutable = example_closed_fulltext_receipt(receipt_id="fr-fail-mutable-cutoff")
    mutable["observation_cutoff"] = "latest"

    future_cutoff = example_closed_fulltext_receipt(receipt_id="fr-fail-future-cutoff")
    future_cutoff["observation_cutoff"] = "2026-12-31T00:00:00Z"
    future_cutoff["cutoff_sealed_at"] = "2026-08-10T00:00:00Z"

    seal_after = example_closed_fulltext_receipt(receipt_id="fr-fail-seal-after-obs")
    # First observation is 01:00; seal at 03:00 is after first observation.
    seal_after["cutoff_sealed_at"] = "2026-08-10T03:00:00Z"
    seal_after["documents"] = [
        example_full_text_document(fr_observed_at="2026-08-10T01:00:00Z")
    ]
    seal_after["receipt_created_at"] = "2026-08-10T11:00:00Z"

    receipt_before = example_closed_fulltext_receipt(
        receipt_id="fr-fail-receipt-before-attempt"
    )
    receipt_before["receipt_created_at"] = "2026-08-10T01:30:00Z"
    receipt_before["documents"] = [
        example_full_text_document(fr_observed_at="2026-08-10T02:00:00Z")
    ]

    after_verifier = example_closed_fulltext_receipt(
        receipt_id="fr-fail-after-verifier"
    )
    after_verifier["receipt_created_at"] = "2026-08-10T18:00:00Z"
    after_verifier["documents"] = [
        example_full_text_document(fr_observed_at="2026-08-10T01:00:00Z")
    ]

    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "policy_schema_version": POLICY_SCHEMA_VERSION,
        "gate_schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "cutoff_sealed_at": "2026-08-10T00:00:00Z",
        "receipt_created_at": "2026-08-10T11:00:00Z",
        "verifier_clock": FIXTURE_VERIFIER_CLOCK_UTC,
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
        "official_full_text_sources": list(OFFICIAL_FULL_TEXT_SOURCES),
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "notes": (
            "Compact adversarial full-text attempt-receipt recipes for LCR-075. "
            "Cases encode non-body exhaustion, unresolved usable bodies, "
            "failed-final/pending items, missing hashes, and real-time seal "
            "timestamp failures. Expand via expand_fulltext_fixture_cases()."
        ),
        "cases": [
            {
                "case_id": "full_text_and_metadata_ok",
                "expected_status": "pass",
                "expected_kinds": [],
                "receipt": closed,
                "notes": "Admitted full text plus exhausted metadata-only.",
            },
            {
                "case_id": "abstract_only_exhausted_ok",
                "expected_status": "pass",
                "expected_kinds": [],
                "receipt": abstract_ok,
                "notes": "ABSTRACT_ONLY with allowed reason and FR+GovInfo exhaustion.",
            },
            {
                "case_id": "missing_body_exhausted_ok",
                "expected_status": "pass",
                "expected_kinds": [],
                "receipt": missing_ok,
                "notes": "MISSING_BODY_OFFICIAL with complete exhaustion evidence.",
            },
            {
                "case_id": "excluded_exhausted_ok",
                "expected_status": "pass",
                "expected_kinds": [],
                "receipt": excluded_ok,
                "notes": "Exclusion with allowed reason and no usable body anywhere.",
            },
            {
                "case_id": "quarantined_exhausted_ok",
                "expected_status": "pass",
                "expected_kinds": [],
                "receipt": quarantine_ok,
                "notes": "Quarantine with allowed reason and complete exhaustion.",
            },
            {
                "case_id": "incomplete_exhaustion",
                "expected_status": "fail",
                "expected_kinds": ["incomplete_exhaustion"],
                "receipt": no_exhaustion,
                "notes": "METADATA_ONLY without GovInfo exhaustion.",
            },
            {
                "case_id": "missing_allowed_reason",
                "expected_status": "fail",
                "expected_kinds": ["missing_allowed_reason"],
                "receipt": no_reason,
                "notes": "Non-body disposition without allowed reason.",
            },
            {
                "case_id": "body_not_admitted",
                "expected_status": "fail",
                "expected_kinds": ["body_not_admitted"],
                "receipt": body_not_admitted,
                "notes": "Usable body parsed but not admitted as full text.",
            },
            {
                "case_id": "exclusion_erases_failure",
                "expected_status": "fail",
                "expected_kinds": ["exclusion_erases_failure"],
                "receipt": exclusion_erases,
                "notes": "Exclusion cannot erase an available official body.",
            },
            {
                "case_id": "failed_final",
                "expected_status": "fail",
                "expected_kinds": ["failed_final"],
                "receipt": failed_final,
                "notes": "failed_final disposition blocks publication.",
            },
            {
                "case_id": "pending",
                "expected_status": "fail",
                "expected_kinds": ["pending"],
                "receipt": pending,
                "notes": "Pending disposition/attempt blocks publication.",
            },
            {
                "case_id": "missing_hash",
                "expected_status": "fail",
                "expected_kinds": ["missing_hash"],
                "receipt": missing_hash,
                "notes": "Admitted full text missing content/response hash.",
            },
            {
                "case_id": "missing_cutoff_sealed_at",
                "expected_status": "fail",
                "expected_kinds": ["missing_timestamp"],
                "receipt": missing_seal,
                "notes": "cutoff_sealed_at is required.",
            },
            {
                "case_id": "malformed_timestamp",
                "expected_status": "fail",
                "expected_kinds": ["malformed_timestamp"],
                "receipt": malformed_ts,
                "notes": "receipt_created_at is not valid ISO-8601.",
            },
            {
                "case_id": "non_utc_timestamp",
                "expected_status": "fail",
                "expected_kinds": ["non_utc_timestamp"],
                "receipt": non_utc,
                "notes": "Offset form without trailing Z is rejected.",
            },
            {
                "case_id": "mutable_cutoff",
                "expected_status": "fail",
                "expected_kinds": ["mutable_cutoff"],
                "receipt": mutable,
                "notes": "observation_cutoff uses mutable token 'latest'.",
            },
            {
                "case_id": "future_cutoff",
                "expected_status": "fail",
                "expected_kinds": ["future_cutoff"],
                "receipt": future_cutoff,
                "notes": "observation_cutoff is after the verifier clock.",
            },
            {
                "case_id": "cutoff_seal_after_observation",
                "expected_status": "fail",
                "expected_kinds": ["cutoff_seal_after_observation"],
                "receipt": seal_after,
                "notes": "cutoff_sealed_at is after the first acquisition observation.",
            },
            {
                "case_id": "receipt_before_last_attempt",
                "expected_status": "fail",
                "expected_kinds": ["receipt_before_last_attempt"],
                "receipt": receipt_before,
                "notes": "receipt_created_at precedes the last recorded attempt.",
            },
            {
                "case_id": "timestamp_after_verifier",
                "expected_status": "fail",
                "expected_kinds": ["timestamp_after_verifier"],
                "receipt": after_verifier,
                "notes": "receipt_created_at is later than the verifier clock.",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "ALLOWED_NON_BODY_REASONS",
    "BODY_BEARING_FULLTEXT_DISPOSITIONS",
    "DEFAULT_MAX_FUTURE_SKEW",
    "EXHAUSTION_REQUIRED_DISPOSITIONS",
    "FIXTURE_SCHEMA_VERSION",
    "FIXTURE_VERIFIER_CLOCK_UTC",
    "GOAL_ID",
    "NON_BODY_FULLTEXT_DISPOSITIONS",
    "REQUIRED_FULL_TEXT_AUTHORITIES",
    "SCHEMA_VERSION",
    "TASK_ID",
    "AllowedNonBodyReason",
    "AttemptEvidenceError",
    "AttemptStatus",
    "ContentFormat",
    "DispositionAdmissionError",
    "DocumentAttemptLedger",
    "ExhaustionError",
    "FailedFinalAdmissionError",
    "FailureKind",
    "FederalRegisterFulltextGateError",
    "FixtureSchemaError",
    "FormatAttempt",
    "FulltextAttemptReceipt",
    "FulltextDisposition",
    "GateFinding",
    "GateResult",
    "GateVerdict",
    "MissingHashError",
    "ParserResult",
    "SealTimestampError",
    "UnresolvedBodyError",
    "assert_fixture_expectations",
    "assert_fulltext_admission",
    "build_default_fulltext_fixture_payload",
    "default_fulltext_fixture_path",
    "evaluate_fixture_case",
    "evaluate_fulltext_attempt_receipt",
    "evaluate_fulltext_fixture",
    "example_closed_fulltext_receipt",
    "example_exhausted_non_body_document",
    "example_full_text_document",
    "expand_fulltext_fixture_cases",
    "fixture_verifier_now",
    "load_fulltext_fixture_payload",
    "raise_for_findings",
    "require_strict_utc_z_timestamp",
]

# Convenience frozenset of allowed reason values for importers/tests.
ALLOWED_NON_BODY_REASONS: Final = frozenset(item.value for item in AllowedNonBodyReason)
