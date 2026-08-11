"""Per-authority Federal Register full-text attempt exhaustion gate (LCR-085).

Fail-closed admission gate for Federal Register full-text acquisition. A
document may only leave the acquisition frontier when every applicable
official authority-and-format alternative from the LCR-049 canonical frontier
has been evidenced under a sealed, real-time cutoff and the resulting
disposition is either:

* admitted full text (fetched, response- and content-hash verified against
  captured immutable bytes, successfully parsed, and bound to a digest
  independently recomputed from the exact admitted body bytes); or
* a non-body disposition (``METADATA_ONLY``, ``ABSTRACT_ONLY``,
  ``MISSING_BODY_OFFICIAL``, exclusion, or quarantine) backed by an allowed
  reason **and** complete source-policy-authorized absence evidence for every
  remaining alternative, with immutable request and response bytes whose
  digests independently reproduce every recorded hash.

Design invariants
-----------------
* Authorizing identity is exact v2: schema
  ``federal-register-fulltext-gate-v2``, producer
  ``federal_register_fulltext_gate.py@2``, program
  ``legal-corpora-reindex-v1``, task ``LCR-085``, goal ``LCR-G147``, mode
  ``live``. No default, alias, coercion, v1 value, or fixture mode can
  authorize.
* FederalRegister.gov HTML and GovInfo PDF form the complete LCR-049-derived
  authority-by-format frontier; every document ledger must cover that frontier
  exactly (no missing, extra, or duplicate keys).
* Attempt URL host and media type must bind to the declared authority and
  format.
* Failed, skipped, pending, retryable, anti-bot, navigation, error-page,
  unsupported-format, parser-failed, and every hashless state are
  non-exhaustive and cannot prove absence.
* Negative closure requires captured immutable request and response bytes
  whose digests independently recompute every recorded request/response hash.
* Admitted bodies require both response and content hashes, recomputed from
  captured bytes, with the document admitted digest equal to the content hash.
* Authorizing APIs require an explicit verifier-owned UTC instant, apply fixed
  zero future skew, and expose no caller-controlled tolerance override.
* Live network I/O is out of scope; unit tests use sealed fixtures only.
* Completeness is cutoff-relative (inherits LCR-049 source policy).
"""

from __future__ import annotations

import base64
import inspect
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Optional, Sequence, Union
from urllib.parse import urlparse

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
# Schema / task identity (exact authorizing values; no aliases)
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "federal-register-fulltext-gate-v2"
FIXTURE_SCHEMA_VERSION: Final = "federal-register-fulltext-attempt-receipts-v2"
LEGACY_SCHEMA_VERSION: Final = "federal-register-fulltext-gate-v1"
LEGACY_FIXTURE_SCHEMA_VERSION: Final = "federal-register-fulltext-attempt-receipts-v1"
TASK_ID: Final = "LCR-085"
GOAL_ID: Final = "LCR-G147"
LEGACY_TASK_ID: Final = "LCR-075"
LEGACY_GOAL_ID: Final = "LCR-G110"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "federal_register_fulltext_gate.py@2"
LEGACY_PRODUCER: Final = "federal_register_fulltext_gate.py"
MODE_LIVE: Final = "live"
MODE_FIXTURE: Final = "fixture"

AUTHORIZING_IDENTITY: Final = MappingProxyType(
    {
        "schema_version": SCHEMA_VERSION,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "mode": MODE_LIVE,
    }
)

IDENTITY_FIELDS: Final = (
    "schema_version",
    "producer",
    "program_id",
    "task_id",
    "goal_id",
    "mode",
)

# Fixed non-authorizing verifier clock for fixture-only structural evaluation.
# Live acquisition must supply a trusted clock; the gate never invents time.
FIXTURE_VERIFIER_CLOCK_UTC: Final = "2026-08-10T12:00:00Z"

# Fixed zero future skew: timestamps may never exceed verifier time.
# No authorizing public helper accepts a tolerance override.
ZERO_FUTURE_SKEW: Final = timedelta(0)
FIXED_MAX_FUTURE_SKEW: Final = ZERO_FUTURE_SKEW
# Legacy alias retained only for import discovery; never authorizing.
DEFAULT_MAX_FUTURE_SKEW: Final = ZERO_FUTURE_SKEW

DEFAULT_FIXTURE_RELATIVE_PATH: Final = Path(
    "tests/fixtures/legal_ir/federal_register_fulltext_attempt_receipts.json"
)

# Official full-text authorities that must be exhausted for non-body states.
REQUIRED_FULL_TEXT_AUTHORITIES: Final = (
    OfficialAuthority.FEDERAL_REGISTER,
    OfficialAuthority.GOVINFO,
)

# Canonical LCR-049-derived authority × format frontier (exact, ordered).
CANONICAL_FULLTEXT_FRONTIER: Final = (
    (OfficialAuthority.FEDERAL_REGISTER, "html"),
    (OfficialAuthority.GOVINFO, "pdf"),
)

_AUTHORITY_HOST_SUFFIXES: Final = MappingProxyType(
    {
        OfficialAuthority.FEDERAL_REGISTER: (
            "federalregister.gov",
            ".federalregister.gov",
        ),
        OfficialAuthority.GOVINFO: (
            "govinfo.gov",
            ".govinfo.gov",
        ),
        OfficialAuthority.FEDERAL_REGISTER_API: (
            "federalregister.gov",
            ".federalregister.gov",
        ),
    }
)

_FORMAT_MEDIA_TYPES: Final = MappingProxyType(
    {
        "html": frozenset({"text/html", "application/xhtml+xml"}),
        "xml": frozenset({"application/xml", "text/xml"}),
        "pdf": frozenset({"application/pdf"}),
        "json": frozenset({"application/json"}),
        "text": frozenset({"text/plain"}),
    }
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


class ByteBindingError(FederalRegisterFulltextGateError):
    """Raised when declared hashes do not match captured immutable bytes."""


class IdentityError(FederalRegisterFulltextGateError):
    """Raised when authorizing identity fields are missing or wrong."""


class FrontierError(FederalRegisterFulltextGateError):
    """Raised when the authority-format ledger is incomplete or extra."""


class VerifierClockError(FederalRegisterFulltextGateError):
    """Raised when the verifier-owned clock is missing or untrusted."""


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
    def is_non_exhaustive(self) -> bool:
        """Statuses that can never prove official absence."""

        return self in {
            AttemptStatus.PENDING,
            AttemptStatus.FAILED,
            AttemptStatus.SKIPPED,
            AttemptStatus.FETCHED,
            AttemptStatus.HASH_VERIFIED,
            AttemptStatus.PARSED,
        }

    @property
    def indicates_body_present(self) -> bool:
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
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise AttemptEvidenceError(f"unknown parser result: {value!r}")

    @property
    def is_non_exhaustive_negative(self) -> bool:
        """Terminal negative outcomes that never prove source-policy absence."""

        return self in {
            ParserResult.ERROR_PAGE,
            ParserResult.NAVIGATION,
            ParserResult.ANTI_BOT,
            ParserResult.PARSE_ERROR,
            ParserResult.UNSUPPORTED_FORMAT,
            ParserResult.NOT_RUN,
        }

    @property
    def may_support_absence(self) -> bool:
        """Parser outcomes that may accompany authorized absence evidence."""

        return self in {ParserResult.NO_BODY, ParserResult.EMPTY}

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
        # Map LCR-049 body dispositions where they overlap (exact values only).
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
            if body in mapping and body.value == text:
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
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise DispositionAdmissionError(
            f"non-body disposition requires an allowed reason; got {value!r}"
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
        if text == "pass":
            return cls.PASS
        if text == "fail":
            return cls.FAIL
        raise FederalRegisterFulltextGateError(f"unknown verdict: {value!r}")


class FailureKind(str, Enum):
    """Typed failure kinds rejected by the full-text attempt gate."""

    FAILED_FINAL = "failed_final"
    PENDING = "pending"
    MISSING_HASH = "missing_hash"
    HASH_MISMATCH = "hash_mismatch"
    BYTE_BINDING = "byte_binding"
    MISSING_TIMESTAMP = "missing_timestamp"
    MALFORMED_TIMESTAMP = "malformed_timestamp"
    NON_UTC_TIMESTAMP = "non_utc_timestamp"
    MUTABLE_CUTOFF = "mutable_cutoff"
    FUTURE_CUTOFF = "future_cutoff"
    CUTOFF_SEAL_AFTER_OBSERVATION = "cutoff_seal_after_observation"
    RECEIPT_BEFORE_LAST_ATTEMPT = "receipt_before_last_attempt"
    TIMESTAMP_AFTER_VERIFIER = "timestamp_after_verifier"
    MISSING_VERIFIER_TIME = "missing_verifier_time"
    CALLER_SKEW = "caller_skew"
    MISSING_ALLOWED_REASON = "missing_allowed_reason"
    INCOMPLETE_EXHAUSTION = "incomplete_exhaustion"
    EXTRA_FRONTIER = "extra_frontier"
    DUPLICATE_LEDGER_KEY = "duplicate_ledger_key"
    AUTHORITY_HOST_MISMATCH = "authority_host_mismatch"
    FORMAT_MEDIA_MISMATCH = "format_media_mismatch"
    BODY_NOT_ADMITTED = "body_not_admitted"
    EXCLUSION_ERASES_FAILURE = "exclusion_erases_failure"
    NON_EXHAUSTIVE_NEGATIVE = "non_exhaustive_negative"
    MISSING_ATTEMPT_EVIDENCE = "missing_attempt_evidence"
    OFFICIAL_AUTHORITY = "official_authority"
    DOCUMENT_IDENTITY = "document_identity"
    IDENTITY = "identity"
    FIXTURE_MODE = "fixture_mode"
    SCHEMA = "schema"
    OTHER = "other"

    @classmethod
    def coerce(cls, value: Any) -> "FailureKind":
        if isinstance(value, FailureKind):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
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


def format_utc_timestamp_precise(dt: datetime) -> str:
    """Format *dt* as UTC ``...Z``, preserving microseconds when present."""

    utc = dt.astimezone(timezone.utc)
    if utc.microsecond:
        return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond:06d}Z"
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def default_fulltext_fixture_path() -> Path:
    """Return the default on-disk path of the sealed attempt-receipts fixture."""

    return repository_root() / DEFAULT_FIXTURE_RELATIVE_PATH


def fixture_verifier_now() -> datetime:
    """Return the fixed fixture verifier clock as an aware UTC datetime."""

    return parse_utc_timestamp(FIXTURE_VERIFIER_CLOCK_UTC, name="verifier_clock")


def require_strict_utc_z_timestamp(value: Any, *, name: str = "timestamp") -> str:
    """Require an explicit ``...Z`` UTC timestamp string (no offset form).

    Fail-closed: missing, empty, naive, offset-only, or non-``Z`` values are
    rejected. Returns the normalized ``YYYY-MM-DDTHH:MM:SS[.ffffff]Z`` form.
    """

    if value is None or (isinstance(value, str) and not value.strip()):
        raise SealTimestampError(f"{name} is required and must be a UTC ...Z timestamp")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise SealTimestampError(f"{name} must be timezone-aware UTC, got naive")
        return format_utc_timestamp_precise(value.astimezone(timezone.utc))
    if not isinstance(value, str):
        raise SealTimestampError(f"{name} must be an ISO-8601 UTC ...Z string")
    text = value.strip()
    if text.endswith("+00:00") or text.endswith("-00:00"):
        raise SealTimestampError(
            f"{name} must use trailing Z UTC form, not offset {value!r}"
        )
    if not text.endswith("Z"):
        try:
            parse_utc_timestamp(text, name=name)
        except TimestampError as exc:
            msg = str(exc).lower()
            if "naive" in msg or "timezone-aware" in msg:
                raise SealTimestampError(
                    f"{name} must be timezone-aware UTC ending in Z; got {value!r}"
                ) from exc
            raise SealTimestampError(
                f"{name} is malformed ISO-8601 UTC timestamp: {value!r}"
            ) from exc
        raise SealTimestampError(
            f"{name} must use trailing Z UTC form; got {value!r}"
        )
    try:
        dt = parse_utc_timestamp(text, name=name)
    except TimestampError as exc:
        raise SealTimestampError(
            f"{name} is malformed ISO-8601 UTC timestamp: {value!r}"
        ) from exc
    return format_utc_timestamp_precise(dt)


def _authority_family(authority: OfficialAuthority) -> OfficialAuthority:
    """Normalize inventory API authority into the FR full-text family."""

    if authority is OfficialAuthority.FEDERAL_REGISTER_API:
        return OfficialAuthority.FEDERAL_REGISTER
    return authority


def ledger_key(
    document_number: str,
    authority: OfficialAuthority | str,
    content_format: ContentFormat | str,
) -> str:
    """Return the unique document × authority × format ledger key."""

    auth = OfficialAuthority.coerce(authority)
    auth = _authority_family(auth)
    fmt = ContentFormat.coerce(content_format)
    return f"{document_number}:{auth.value}:{fmt.value}"


def canonical_frontier_keys(document_number: str) -> tuple[str, ...]:
    """Return the complete LCR-049 frontier keys for *document_number*."""

    return tuple(
        ledger_key(document_number, authority, fmt)
        for authority, fmt in CANONICAL_FULLTEXT_FRONTIER
    )


def decode_captured_bytes(value: Any, *, name: str) -> Optional[bytes]:
    """Decode captured immutable artifact bytes from a receipt field.

    Accepts ``None``/empty (absence of capture), raw ``bytes``, UTF-8 text,
    or ``b64:<payload>`` / ``hex:<payload>`` encodings.
    """

    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if not isinstance(value, str):
        raise ByteBindingError(f"{name} must be bytes, str, or null")
    text = value
    if text == "":
        return b""
    if text.startswith("b64:"):
        try:
            return base64.b64decode(text[4:], validate=True)
        except Exception as exc:
            raise ByteBindingError(f"{name} is not valid base64: {value!r}") from exc
    if text.startswith("hex:"):
        try:
            return bytes.fromhex(text[4:])
        except Exception as exc:
            raise ByteBindingError(f"{name} is not valid hex: {value!r}") from exc
    return text.encode("utf-8")


def _host_matches_authority(host: str, authority: OfficialAuthority) -> bool:
    family = _authority_family(authority)
    suffixes = _AUTHORITY_HOST_SUFFIXES.get(family)
    if not suffixes:
        return False
    h = (host or "").lower().strip(".")
    if not h:
        return False
    for suffix in suffixes:
        if suffix.startswith("."):
            if h.endswith(suffix) or h == suffix[1:]:
                return True
        elif h == suffix or h.endswith("." + suffix):
            return True
    return False


def _media_type_matches_format(media_type: Optional[str], content_format: ContentFormat) -> bool:
    if media_type is None or not str(media_type).strip():
        return False
    base = str(media_type).split(";", 1)[0].strip().lower()
    allowed = _FORMAT_MEDIA_TYPES.get(content_format.value)
    if not allowed:
        return False
    return base in allowed


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
    request_hash: Optional[str] = None
    retry_count: int = 0
    terminal_reason: str = ""
    parser_result: ParserResult = ParserResult.NOT_RUN
    body_available: bool = False
    body_usable: bool = False
    http_status: Optional[int] = None
    media_type: Optional[str] = None
    request_bytes: Optional[str] = None
    response_bytes: Optional[str] = None
    content_bytes: Optional[str] = None
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
        for field_name in ("response_hash", "content_hash", "request_hash"):
            raw = getattr(self, field_name)
            if raw is not None and str(raw).strip():
                object.__setattr__(
                    self,
                    field_name,
                    normalize_sha256(raw, name=field_name),
                )
            else:
                object.__setattr__(self, field_name, None)
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
        if self.media_type is not None and str(self.media_type).strip():
            object.__setattr__(
                self,
                "media_type",
                _require_non_empty_str(self.media_type, "media_type", maximum=256),
            )
        else:
            object.__setattr__(self, "media_type", None)
        for field_name in ("request_bytes", "response_bytes", "content_bytes"):
            raw = getattr(self, field_name)
            if raw is None:
                object.__setattr__(self, field_name, None)
            elif isinstance(raw, (bytes, bytearray)):
                object.__setattr__(self, field_name, bytes(raw).decode("latin-1"))
            else:
                object.__setattr__(self, field_name, str(raw))
        object.__setattr__(self, "notes", str(self.notes or ""))

        if self.body_usable and not self.body_available:
            raise AttemptEvidenceError(
                f"attempt {self.attempt_id!r}: body_usable requires body_available"
            )
        if self.status is AttemptStatus.ADMITTED and not self.body_usable:
            raise AttemptEvidenceError(
                f"attempt {self.attempt_id!r}: admitted status requires body_usable"
            )
        if self.parser_result.indicates_usable_body and not self.body_usable:
            raise AttemptEvidenceError(
                f"attempt {self.attempt_id!r}: parser_result=success requires body_usable"
            )

    @property
    def authority_family(self) -> OfficialAuthority:
        return _authority_family(self.authority)

    @property
    def frontier_key(self) -> str:
        return f"{self.authority_family.value}:{self.content_format.value}"

    def document_ledger_key(self, document_number: str) -> str:
        return ledger_key(document_number, self.authority_family, self.content_format)

    @property
    def has_response_hash(self) -> bool:
        return bool(self.response_hash)

    @property
    def has_content_hash(self) -> bool:
        return bool(self.content_hash)

    @property
    def has_both_body_hashes(self) -> bool:
        return bool(self.response_hash and self.content_hash)

    @property
    def decoded_request_bytes(self) -> Optional[bytes]:
        return decode_captured_bytes(self.request_bytes, name="request_bytes")

    @property
    def decoded_response_bytes(self) -> Optional[bytes]:
        return decode_captured_bytes(self.response_bytes, name="response_bytes")

    @property
    def decoded_content_bytes(self) -> Optional[bytes]:
        return decode_captured_bytes(self.content_bytes, name="content_bytes")

    @property
    def proves_authorized_absence(self) -> bool:
        """True only for source-policy-authorized absence with byte binding."""

        if self.body_usable or self.body_available:
            return False
        if self.status is not AttemptStatus.NO_BODY:
            return False
        if not self.parser_result.may_support_absence:
            return False
        if self.status.is_non_exhaustive or self.parser_result.is_non_exhaustive_negative:
            return False
        if not self.request_hash or not self.response_hash:
            return False
        req = self.decoded_request_bytes
        resp = self.decoded_response_bytes
        if req is None or resp is None:
            return False
        if content_sha256(req) != self.request_hash:
            return False
        if content_sha256(resp) != self.response_hash:
            return False
        return True

    @property
    def has_unresolved_usable_body(self) -> bool:
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
            "request_hash": self.request_hash,
            "retry_count": self.retry_count,
            "terminal_reason": self.terminal_reason,
            "parser_result": self.parser_result.value,
            "body_available": self.body_available,
            "body_usable": self.body_usable,
            "http_status": self.http_status,
            "media_type": self.media_type,
            "request_bytes": self.request_bytes,
            "response_bytes": self.response_bytes,
            "content_bytes": self.content_bytes,
            "notes": self.notes,
        }

    @classmethod
    def from_mapping(
        cls, value: JsonMapping, *, context: str = "attempt"
    ) -> "FormatAttempt":
        raw = _as_mapping(value, context)
        if "authority" not in raw:
            raise AttemptEvidenceError(f"{context} requires explicit authority")
        if "content_format" not in raw and "format" not in raw:
            raise AttemptEvidenceError(f"{context} requires explicit content_format")
        if "status" not in raw:
            raise AttemptEvidenceError(f"{context} requires explicit status")
        if "url" not in raw and "official_source_url" not in raw:
            raise AttemptEvidenceError(f"{context} requires explicit url")
        if "observed_at" not in raw:
            raise AttemptEvidenceError(f"{context} requires explicit observed_at")
        return cls(
            attempt_id=raw.get("attempt_id", raw.get("id", "")),
            authority=raw["authority"],
            content_format=raw.get("content_format", raw.get("format")),
            url=raw.get("url", raw.get("official_source_url")),
            observed_at=raw["observed_at"],
            status=raw["status"],
            response_hash=raw.get("response_hash"),
            content_hash=raw.get("content_hash"),
            request_hash=raw.get("request_hash"),
            retry_count=raw.get("retry_count", 0),
            terminal_reason=raw.get("terminal_reason", ""),
            parser_result=raw.get("parser_result", ParserResult.NOT_RUN),
            body_available=raw.get("body_available", False),
            body_usable=raw.get("body_usable", False),
            http_status=raw.get("http_status"),
            media_type=raw.get("media_type"),
            request_bytes=raw.get("request_bytes"),
            response_bytes=raw.get("response_bytes"),
            content_bytes=raw.get("content_bytes", raw.get("admitted_body_bytes")),
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
    admitted_body_bytes: Optional[str] = None
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
        if self.admitted_body_bytes is None:
            object.__setattr__(self, "admitted_body_bytes", None)
        elif isinstance(self.admitted_body_bytes, (bytes, bytearray)):
            object.__setattr__(
                self, "admitted_body_bytes", bytes(self.admitted_body_bytes).decode("latin-1")
            )
        else:
            object.__setattr__(self, "admitted_body_bytes", str(self.admitted_body_bytes))
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
        found: set[OfficialAuthority] = set()
        for attempt in self.attempts:
            if attempt.proves_authorized_absence:
                found.add(attempt.authority_family)
        return frozenset(found)

    @property
    def exhausted_frontier_keys(self) -> frozenset[str]:
        return frozenset(
            attempt.document_ledger_key(self.document_number)
            for attempt in self.attempts
            if attempt.proves_authorized_absence
            or attempt.status is AttemptStatus.ADMITTED
        )

    @property
    def attempted_authorities(self) -> frozenset[OfficialAuthority]:
        return frozenset(a.authority_family for a in self.attempts)

    @property
    def admitted_attempts(self) -> tuple[FormatAttempt, ...]:
        return tuple(a for a in self.attempts if a.status is AttemptStatus.ADMITTED)

    @property
    def has_unresolved_usable_body(self) -> bool:
        return any(a.has_unresolved_usable_body for a in self.attempts)

    @property
    def decoded_admitted_body_bytes(self) -> Optional[bytes]:
        return decode_captured_bytes(
            self.admitted_body_bytes, name="admitted_body_bytes"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_number": self.document_number,
            "publication_date": self.publication_date,
            "disposition": self.disposition.value,
            "attempts": [a.to_dict() for a in self.attempts],
            "allowed_reason": self.allowed_reason,
            "admitted_content_hash": self.admitted_content_hash,
            "admitted_body_bytes": self.admitted_body_bytes,
            "legal_id": self.legal_id,
            "notes": self.notes,
        }

    @classmethod
    def from_mapping(
        cls, value: JsonMapping, *, context: str = "document"
    ) -> "DocumentAttemptLedger":
        raw = _as_mapping(value, context)
        if "document_number" not in raw:
            raise AttemptEvidenceError(f"{context} requires explicit document_number")
        if "publication_date" not in raw:
            raise AttemptEvidenceError(f"{context} requires explicit publication_date")
        if "disposition" not in raw and "text_availability" not in raw:
            raise DispositionAdmissionError(
                f"{context} requires explicit disposition"
            )
        attempts = raw.get("attempts") or ()
        return cls(
            document_number=raw["document_number"],
            publication_date=raw["publication_date"],
            disposition=raw.get("disposition", raw.get("text_availability")),
            attempts=tuple(attempts),
            allowed_reason=raw.get("allowed_reason", raw.get("admission_reason")),
            admitted_content_hash=raw.get("admitted_content_hash"),
            admitted_body_bytes=raw.get("admitted_body_bytes"),
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
    schema_version: str = ""
    producer: str = ""
    program_id: str = ""
    task_id: str = ""
    goal_id: str = ""
    mode: str = ""
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
        # Identity fields are stored exactly as provided.  Empty strings remain
        # structurally representable so evaluation can return typed findings,
        # but non-string values must never gain authority through ``str()``.
        for name in IDENTITY_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, str):
                raise IdentityError(f"identity field {name} must be a string")
            object.__setattr__(self, name, value)
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

    @property
    def has_authorizing_identity(self) -> bool:
        return all(
            getattr(self, name) == expected
            for name, expected in AUTHORIZING_IDENTITY.items()
        )

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
            "producer": self.producer,
            "program_id": self.program_id,
            "task_id": self.task_id,
            "goal_id": self.goal_id,
            "mode": self.mode,
            "notes": self.notes,
            "currentness_disclaimer": self.currentness_disclaimer,
        }

    @classmethod
    def from_mapping(
        cls,
        value: JsonMapping,
        *,
        require_authorizing_identity: bool = False,
    ) -> "FulltextAttemptReceipt":
        raw = _as_mapping(value, "fulltext_attempt_receipt")
        if require_authorizing_identity:
            _require_explicit_authorizing_identity(raw)
        for required in (
            "receipt_id",
            "observation_cutoff",
            "cutoff_sealed_at",
            "receipt_created_at",
            "documents",
        ):
            if required not in raw:
                raise AttemptEvidenceError(
                    f"fulltext_attempt_receipt requires explicit {required}"
                )
        return cls(
            receipt_id=raw["receipt_id"],
            observation_cutoff=raw["observation_cutoff"],
            cutoff_sealed_at=raw["cutoff_sealed_at"],
            receipt_created_at=raw["receipt_created_at"],
            documents=tuple(raw.get("documents") or ()),
            release_point=raw.get("release_point"),
            previous_public_pin=raw.get(
                "previous_public_pin", PREVIOUS_PUBLIC_PIN
            ),
            schema_version=raw.get("schema_version", ""),
            producer=raw.get("producer", ""),
            program_id=raw.get("program_id", ""),
            task_id=raw.get("task_id", ""),
            goal_id=raw.get("goal_id", ""),
            mode=raw.get("mode", ""),
            notes=raw.get("notes", ""),
            currentness_disclaimer=raw.get(
                "currentness_disclaimer", CURRENTNESS_DISCLAIMER
            ),
        )


def _require_explicit_authorizing_identity(raw: Mapping[str, Any]) -> None:
    """Require every identity field explicitly present and exact live values."""

    missing = [name for name in IDENTITY_FIELDS if name not in raw]
    if missing:
        raise IdentityError(
            f"authorizing identity fields must be explicitly present; missing {missing}"
        )
    for name, expected in AUTHORIZING_IDENTITY.items():
        value = raw.get(name)
        if not isinstance(value, str):
            raise IdentityError(f"authorizing identity field {name} must be a string")
        if not value.strip():
            raise IdentityError(f"authorizing identity field {name} is empty")
        if value != expected:
            raise IdentityError(
                f"authorizing identity field {name} must be {expected!r}, got {value!r}"
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
    msg = str(exc).lower()
    if "trailing z" in msg or "timezone-aware" in msg or "ending in z" in msg:
        return FailureKind.NON_UTC_TIMESTAMP
    if "malformed" in msg or "iso-8601" in msg:
        return FailureKind.MALFORMED_TIMESTAMP
    if "required" in msg or "non-empty" in msg:
        return FailureKind.MISSING_TIMESTAMP
    return FailureKind.MISSING_TIMESTAMP


def _resolve_verifier_clock(
    now: Optional[datetime | str | ClockFn],
) -> tuple[Optional[datetime], Optional[GateFinding]]:
    if now is None:
        return None, _finding(
            FailureKind.MISSING_VERIFIER_TIME,
            "authorizing evaluation requires an explicit verifier-owned UTC instant",
            path="verifier_now",
        )
    try:
        if callable(now):
            clock = now()
        elif isinstance(now, datetime):
            clock = now
        else:
            clock = parse_utc_timestamp(now, name="verifier_clock")
        if clock.tzinfo is None:
            raise SealTimestampError("verifier clock must be timezone-aware UTC")
        return clock.astimezone(timezone.utc), None
    except (TimestampError, SealTimestampError) as exc:
        return None, _finding(
            FailureKind.MALFORMED_TIMESTAMP,
            str(exc),
            path="verifier_now",
        )


def _validate_identity(receipt: FulltextAttemptReceipt) -> list[GateFinding]:
    findings: list[GateFinding] = []
    if receipt.mode == MODE_FIXTURE:
        findings.append(
            _finding(
                FailureKind.FIXTURE_MODE,
                "fixture mode cannot authorize full-text admission",
                path="mode",
                mode=receipt.mode,
            )
        )
        return findings
    for name, expected in AUTHORIZING_IDENTITY.items():
        value = getattr(receipt, name)
        if not value:
            findings.append(
                _finding(
                    FailureKind.IDENTITY,
                    f"identity field {name} is omitted or empty",
                    path=name,
                )
            )
        elif value != expected:
            findings.append(
                _finding(
                    FailureKind.IDENTITY,
                    f"identity field {name} must be {expected!r}, got {value!r}",
                    path=name,
                    expected=expected,
                    actual=value,
                )
            )
    # Reject every v1 receipt explicitly.
    if receipt.schema_version == LEGACY_SCHEMA_VERSION:
        findings.append(
            _finding(
                FailureKind.IDENTITY,
                f"v1 schema {LEGACY_SCHEMA_VERSION!r} cannot authorize",
                path="schema_version",
            )
        )
    if receipt.task_id == LEGACY_TASK_ID or receipt.goal_id == LEGACY_GOAL_ID:
        findings.append(
            _finding(
                FailureKind.IDENTITY,
                "legacy LCR-075 / LCR-G110 identity cannot authorize",
                path="task_id",
            )
        )
    if receipt.producer in {LEGACY_PRODUCER, ""}:
        if receipt.producer == LEGACY_PRODUCER:
            findings.append(
                _finding(
                    FailureKind.IDENTITY,
                    f"legacy producer {LEGACY_PRODUCER!r} cannot authorize",
                    path="producer",
                )
            )
    return findings


def _validate_timestamps_against_clock(
    receipt: FulltextAttemptReceipt,
    *,
    now: datetime,
) -> list[GateFinding]:
    findings: list[GateFinding] = []
    horizon = now + ZERO_FUTURE_SKEW

    def _check(name: str, value: str, path: str) -> Optional[datetime]:
        try:
            dt = parse_utc_timestamp(value, name=name)
        except TimestampError as exc:
            findings.append(
                _finding(FailureKind.MALFORMED_TIMESTAMP, str(exc), path=path)
            )
            return None
        if dt > horizon:
            findings.append(
                _finding(
                    FailureKind.TIMESTAMP_AFTER_VERIFIER,
                    f"{name}={value!r} is later than verifier clock "
                    f"{format_utc_timestamp_precise(now)}",
                    path=path,
                    timestamp=value,
                    verifier_clock=format_utc_timestamp_precise(now),
                )
            )
        return dt

    cutoff_dt = _check(
        "cutoff_sealed_at", receipt.cutoff_sealed_at, "cutoff_sealed_at"
    )
    receipt_dt = _check(
        "receipt_created_at", receipt.receipt_created_at, "receipt_created_at"
    )

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
                    f"{format_utc_timestamp_precise(now)}",
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
                    f"clock {format_utc_timestamp_precise(now)}",
                    path=path,
                    attempt_id=attempt.attempt_id,
                )
            )

    if cutoff_dt is not None and first_obs is not None and cutoff_dt > first_obs:
        findings.append(
            _finding(
                FailureKind.CUTOFF_SEAL_AFTER_OBSERVATION,
                f"cutoff_sealed_at={receipt.cutoff_sealed_at!r} is after the first "
                f"acquisition observation {format_utc_timestamp_precise(first_obs)}",
                path="cutoff_sealed_at",
                first_observed_at=format_utc_timestamp_precise(first_obs),
            )
        )

    if receipt_dt is not None and last_obs is not None and receipt_dt < last_obs:
        findings.append(
            _finding(
                FailureKind.RECEIPT_BEFORE_LAST_ATTEMPT,
                f"receipt_created_at={receipt.receipt_created_at!r} is before the "
                f"last recorded attempt {format_utc_timestamp_precise(last_obs)}",
                path="receipt_created_at",
                last_observed_at=format_utc_timestamp_precise(last_obs),
            )
        )

    return findings


def _validate_attempt_binding(
    attempt: FormatAttempt,
    *,
    document_number: str,
    path: str,
) -> list[GateFinding]:
    findings: list[GateFinding] = []
    host = (urlparse(attempt.url).hostname or "").lower()
    if not _host_matches_authority(host, attempt.authority):
        findings.append(
            _finding(
                FailureKind.AUTHORITY_HOST_MISMATCH,
                f"attempt {attempt.attempt_id!r} URL host {host!r} does not bind to "
                f"authority {attempt.authority.value}",
                path=f"{path}.url",
                attempt_id=attempt.attempt_id,
                host=host,
                authority=attempt.authority.value,
            )
        )
    if attempt.media_type is not None or attempt.status is AttemptStatus.ADMITTED:
        if not _media_type_matches_format(attempt.media_type, attempt.content_format):
            findings.append(
                _finding(
                    FailureKind.FORMAT_MEDIA_MISMATCH,
                    f"attempt {attempt.attempt_id!r} media_type={attempt.media_type!r} "
                    f"does not match format {attempt.content_format.value}",
                    path=f"{path}.media_type",
                    attempt_id=attempt.attempt_id,
                    media_type=attempt.media_type,
                    content_format=attempt.content_format.value,
                )
            )
    # Canonical frontier membership.
    key = attempt.document_ledger_key(document_number)
    if key not in set(canonical_frontier_keys(document_number)):
        findings.append(
            _finding(
                FailureKind.EXTRA_FRONTIER,
                f"attempt {attempt.attempt_id!r} key {key!r} is outside the "
                "canonical LCR-049 full-text frontier",
                path=path,
                ledger_key=key,
            )
        )
    return findings


def _validate_attempt_hashes_and_bytes(
    attempt: FormatAttempt,
    *,
    path: str,
) -> list[GateFinding]:
    findings: list[GateFinding] = []

    # Non-exhaustive negative outcomes.
    if attempt.status in {AttemptStatus.FAILED, AttemptStatus.SKIPPED}:
        findings.append(
            _finding(
                FailureKind.NON_EXHAUSTIVE_NEGATIVE,
                f"attempt {attempt.attempt_id!r} status={attempt.status.value} "
                "cannot prove exhaustion or absence",
                path=path,
                attempt_id=attempt.attempt_id,
                status=attempt.status.value,
            )
        )
    if attempt.parser_result.is_non_exhaustive_negative and attempt.status is not AttemptStatus.ADMITTED:
        # Only flag when used as negative/absence evidence path.
        if attempt.status is AttemptStatus.NO_BODY or (
            not attempt.body_usable and attempt.status.is_terminal
        ):
            findings.append(
                _finding(
                    FailureKind.NON_EXHAUSTIVE_NEGATIVE,
                    f"attempt {attempt.attempt_id!r} parser_result="
                    f"{attempt.parser_result.value} is terminal negative evidence "
                    "and cannot prove authorized absence",
                    path=f"{path}.parser_result",
                    attempt_id=attempt.attempt_id,
                    parser_result=attempt.parser_result.value,
                )
            )

    if attempt.status is AttemptStatus.ADMITTED:
        if not attempt.response_hash:
            findings.append(
                _finding(
                    FailureKind.MISSING_HASH,
                    f"admitted attempt {attempt.attempt_id!r} requires response_hash",
                    path=f"{path}.response_hash",
                    attempt_id=attempt.attempt_id,
                )
            )
        if not attempt.content_hash:
            findings.append(
                _finding(
                    FailureKind.MISSING_HASH,
                    f"admitted attempt {attempt.attempt_id!r} requires content_hash",
                    path=f"{path}.content_hash",
                    attempt_id=attempt.attempt_id,
                )
            )
        if attempt.response_hash and not attempt.content_hash:
            findings.append(
                _finding(
                    FailureKind.MISSING_HASH,
                    f"admitted attempt {attempt.attempt_id!r}: response_hash without "
                    "content_hash is non-authorizing",
                    path=path,
                    attempt_id=attempt.attempt_id,
                )
            )
        if attempt.content_hash and not attempt.response_hash:
            findings.append(
                _finding(
                    FailureKind.MISSING_HASH,
                    f"admitted attempt {attempt.attempt_id!r}: content_hash without "
                    "response_hash is non-authorizing",
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
        resp = attempt.decoded_response_bytes
        body = attempt.decoded_content_bytes
        if resp is None:
            findings.append(
                _finding(
                    FailureKind.BYTE_BINDING,
                    f"admitted attempt {attempt.attempt_id!r} requires captured "
                    "response_bytes for independent response_hash verification",
                    path=f"{path}.response_bytes",
                    attempt_id=attempt.attempt_id,
                )
            )
        elif attempt.response_hash and content_sha256(resp) != attempt.response_hash:
            findings.append(
                _finding(
                    FailureKind.HASH_MISMATCH,
                    f"admitted attempt {attempt.attempt_id!r}: response_hash does "
                    "not match captured response_bytes",
                    path=f"{path}.response_hash",
                    attempt_id=attempt.attempt_id,
                )
            )
        if body is None:
            findings.append(
                _finding(
                    FailureKind.BYTE_BINDING,
                    f"admitted attempt {attempt.attempt_id!r} requires captured "
                    "content_bytes for independent content_hash verification",
                    path=f"{path}.content_bytes",
                    attempt_id=attempt.attempt_id,
                )
            )
        elif attempt.content_hash and content_sha256(body) != attempt.content_hash:
            findings.append(
                _finding(
                    FailureKind.HASH_MISMATCH,
                    f"admitted attempt {attempt.attempt_id!r}: content_hash does "
                    "not match captured content_bytes",
                    path=f"{path}.content_hash",
                    attempt_id=attempt.attempt_id,
                )
            )

    if attempt.status is AttemptStatus.NO_BODY:
        # Absence path requires both hashes and captured immutable bytes.
        if not attempt.request_hash or not attempt.response_hash:
            findings.append(
                _finding(
                    FailureKind.MISSING_HASH,
                    f"absence attempt {attempt.attempt_id!r} requires request_hash "
                    "and response_hash over captured immutable bytes",
                    path=path,
                    attempt_id=attempt.attempt_id,
                )
            )
        req = attempt.decoded_request_bytes
        resp = attempt.decoded_response_bytes
        if req is None or resp is None:
            findings.append(
                _finding(
                    FailureKind.BYTE_BINDING,
                    f"absence attempt {attempt.attempt_id!r} requires captured "
                    "immutable request_bytes and response_bytes",
                    path=path,
                    attempt_id=attempt.attempt_id,
                )
            )
        else:
            if attempt.request_hash and content_sha256(req) != attempt.request_hash:
                findings.append(
                    _finding(
                        FailureKind.HASH_MISMATCH,
                        f"absence attempt {attempt.attempt_id!r}: request_hash does "
                        "not match captured request_bytes",
                        path=f"{path}.request_hash",
                        attempt_id=attempt.attempt_id,
                    )
                )
            if attempt.response_hash and content_sha256(resp) != attempt.response_hash:
                findings.append(
                    _finding(
                        FailureKind.HASH_MISMATCH,
                        f"absence attempt {attempt.attempt_id!r}: response_hash does "
                        "not match captured response_bytes",
                        path=f"{path}.response_hash",
                        attempt_id=attempt.attempt_id,
                    )
                )
        if attempt.parser_result.is_non_exhaustive_negative:
            findings.append(
                _finding(
                    FailureKind.NON_EXHAUSTIVE_NEGATIVE,
                    f"absence attempt {attempt.attempt_id!r} parser_result="
                    f"{attempt.parser_result.value} cannot prove authorized absence",
                    path=f"{path}.parser_result",
                    attempt_id=attempt.attempt_id,
                )
            )

    # Hashless failed/anti-bot style attempts.
    if attempt.status is AttemptStatus.FAILED and not (
        attempt.response_hash or attempt.content_hash
    ):
        findings.append(
            _finding(
                FailureKind.MISSING_HASH,
                f"failed attempt {attempt.attempt_id!r} is hashless and non-exhaustive",
                path=path,
                attempt_id=attempt.attempt_id,
            )
        )

    return findings


def _validate_document_frontier(
    document: DocumentAttemptLedger,
    *,
    doc_path: str,
) -> list[GateFinding]:
    findings: list[GateFinding] = []
    required = set(canonical_frontier_keys(document.document_number))
    seen: dict[str, int] = {}
    for idx, attempt in enumerate(document.attempts):
        key = attempt.document_ledger_key(document.document_number)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            findings.append(
                _finding(
                    FailureKind.DUPLICATE_LEDGER_KEY,
                    f"document {document.document_number!r} has duplicate ledger "
                    f"key {key!r}",
                    path=f"{doc_path}.attempts[{idx}]",
                    ledger_key=key,
                )
            )
        findings.extend(
            _validate_attempt_binding(
                attempt,
                document_number=document.document_number,
                path=f"{doc_path}.attempts[{idx}]",
            )
        )
        findings.extend(
            _validate_attempt_hashes_and_bytes(
                attempt, path=f"{doc_path}.attempts[{idx}]"
            )
        )

    present = set(seen)
    missing = sorted(required - present)
    extra = sorted(present - required)
    if missing:
        findings.append(
            _finding(
                FailureKind.INCOMPLETE_EXHAUSTION,
                f"document {document.document_number!r} missing canonical frontier "
                f"entries: {missing}",
                path=f"{doc_path}.attempts",
                missing_ledger_keys=missing,
            )
        )
    if extra:
        findings.append(
            _finding(
                FailureKind.EXTRA_FRONTIER,
                f"document {document.document_number!r} has unexpected frontier "
                f"entries: {extra}",
                path=f"{doc_path}.attempts",
                extra_ledger_keys=extra,
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
        findings.extend(_validate_document_frontier(document, doc_path=doc_path))
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
        findings.extend(_validate_document_frontier(document, doc_path=doc_path))
        return findings

    if not document.attempts:
        findings.append(
            _finding(
                FailureKind.MISSING_ATTEMPT_EVIDENCE,
                f"document {document.document_number!r} has empty attempt ledger",
                path=f"{doc_path}.attempts",
            )
        )

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

    # Unresolved usable body: never erasable by exclusion/quarantine/metadata.
    if document.has_unresolved_usable_body:
        if disp in {
            FulltextDisposition.EXCLUDED,
            FulltextDisposition.QUARANTINED,
            FulltextDisposition.METADATA_ONLY,
            FulltextDisposition.ABSTRACT_ONLY,
            FulltextDisposition.MISSING_BODY_OFFICIAL,
        }:
            findings.append(
                _finding(
                    FailureKind.EXCLUSION_ERASES_FAILURE,
                    f"document {document.document_number!r}: disposition="
                    f"{disp.value} cannot hide a usable official body on another "
                    "alternative",
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

    findings.extend(_validate_document_frontier(document, doc_path=doc_path))

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
        required = set(canonical_frontier_keys(document.document_number))
        exhausted = {
            a.document_ledger_key(document.document_number)
            for a in document.attempts
            if a.proves_authorized_absence
        }
        missing = sorted(required - exhausted)
        if missing:
            findings.append(
                _finding(
                    FailureKind.INCOMPLETE_EXHAUSTION,
                    f"document {document.document_number!r} disposition="
                    f"{disp.value} lacks authorized absence evidence for "
                    f"frontier keys: {missing}",
                    path=f"{doc_path}.attempts",
                    missing_ledger_keys=missing,
                )
            )
        for idx, attempt in enumerate(document.attempts):
            if attempt.proves_authorized_absence and not str(attempt.terminal_reason).strip():
                findings.append(
                    _finding(
                        FailureKind.MISSING_ATTEMPT_EVIDENCE,
                        f"attempt {attempt.attempt_id!r} proves authorized absence "
                        "but lacks terminal_reason",
                        path=f"{doc_path}.attempts[{idx}].terminal_reason",
                        attempt_id=attempt.attempt_id,
                    )
                )
            # Usable body hidden by non-body disposition.
            if attempt.body_usable or attempt.has_unresolved_usable_body:
                findings.append(
                    _finding(
                        FailureKind.EXCLUSION_ERASES_FAILURE,
                        f"document {document.document_number!r}: usable body on "
                        f"attempt {attempt.attempt_id!r} hidden by disposition "
                        f"{disp.value}",
                        path=f"{doc_path}.attempts[{idx}]",
                        attempt_id=attempt.attempt_id,
                    )
                )

    if disp.has_usable_body:
        if not document.admitted_content_hash:
            findings.append(
                _finding(
                    FailureKind.MISSING_HASH,
                    f"document {document.document_number!r} disposition="
                    f"{document.disposition.value} requires admitted_content_hash",
                    path=f"{doc_path}.admitted_content_hash",
                )
            )
        admitted_bytes = document.decoded_admitted_body_bytes
        if admitted_bytes is None:
            findings.append(
                _finding(
                    FailureKind.BYTE_BINDING,
                    f"document {document.document_number!r} requires "
                    "admitted_body_bytes for independent digest recompute",
                    path=f"{doc_path}.admitted_body_bytes",
                )
            )
        elif document.admitted_content_hash:
            recomputed = content_sha256(admitted_bytes)
            if recomputed != document.admitted_content_hash:
                findings.append(
                    _finding(
                        FailureKind.HASH_MISMATCH,
                        f"document {document.document_number!r}: admitted_content_hash "
                        "does not match digest of admitted_body_bytes",
                        path=f"{doc_path}.admitted_content_hash",
                        expected=recomputed,
                        actual=document.admitted_content_hash,
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
            ok = False
            for attempt in document.admitted_attempts:
                if (
                    attempt.has_both_body_hashes
                    and attempt.parser_result is ParserResult.SUCCESS
                    and attempt.body_usable
                    and attempt.decoded_content_bytes is not None
                    and attempt.decoded_response_bytes is not None
                    and attempt.content_hash
                    and content_sha256(attempt.decoded_content_bytes)
                    == attempt.content_hash
                    and attempt.response_hash
                    and content_sha256(attempt.decoded_response_bytes)
                    == attempt.response_hash
                ):
                    if (
                        document.admitted_content_hash
                        and attempt.content_hash != document.admitted_content_hash
                    ):
                        findings.append(
                            _finding(
                                FailureKind.HASH_MISMATCH,
                                f"document {document.document_number!r}: "
                                "admitted_content_hash must equal admitted attempt "
                                "content_hash",
                                path=f"{doc_path}.admitted_content_hash",
                            )
                        )
                    else:
                        ok = True
                    break
            if not ok:
                findings.append(
                    _finding(
                        FailureKind.BODY_NOT_ADMITTED,
                        f"document {document.document_number!r}: admitted full text "
                        "must be fetched, response- and content-hash verified from "
                        "captured bytes, successfully parsed, and body_usable",
                        path=doc_path,
                    )
                )
        # Remaining alternatives must have authorized absence.
        required = set(canonical_frontier_keys(document.document_number))
        admitted_keys = {
            a.document_ledger_key(document.document_number)
            for a in document.admitted_attempts
        }
        remaining = required - admitted_keys
        absence_keys = {
            a.document_ledger_key(document.document_number)
            for a in document.attempts
            if a.proves_authorized_absence
        }
        missing_absence = sorted(remaining - absence_keys)
        if missing_absence:
            findings.append(
                _finding(
                    FailureKind.INCOMPLETE_EXHAUSTION,
                    f"document {document.document_number!r}: remaining frontier "
                    f"alternatives lack authorized absence: {missing_absence}",
                    path=f"{doc_path}.attempts",
                    missing_ledger_keys=missing_absence,
                )
            )

    return findings


def _reject_caller_skew_kwargs(kwargs: Mapping[str, Any]) -> Optional[GateFinding]:
    """Reject any caller attempt to widen future-skew tolerance."""

    forbidden = {
        "max_future_skew",
        "future_skew",
        "skew",
        "tolerance",
        "clock_skew",
        "allowed_skew",
    }
    for name in forbidden:
        if name in kwargs:
            value = kwargs[name]
            return _finding(
                FailureKind.CALLER_SKEW,
                f"authorizing APIs reject caller-supplied skew argument {name}="
                f"{value!r}; the verifier owns the fixed zero-skew policy",
                path=name,
            )
    return None


def evaluate_fulltext_attempt_receipt(
    receipt: FulltextAttemptReceipt | JsonMapping,
    *,
    now: Optional[datetime | str | ClockFn] = None,
    raise_on_failure: bool = False,
    **kwargs: Any,
) -> GateResult:
    """Evaluate one full-text attempt receipt against fail-closed gate rules.

    Authorizing evaluation requires an explicit verifier-owned UTC instant.
    Fixed zero future skew is mandatory; caller skew overrides are rejected.
    """

    skew_finding = _reject_caller_skew_kwargs(kwargs)
    findings: list[GateFinding] = []
    if skew_finding is not None:
        findings.append(skew_finding)

    def _failed_parse_result(
        *,
        kind: FailureKind,
        message: str,
        path: str,
        raw: Any,
        extra: Sequence[GateFinding] = (),
    ) -> GateResult:
        mapping = raw if isinstance(raw, Mapping) else {}
        all_findings = list(extra) + [_finding(kind, message, path=path)]
        result = GateResult(
            verdict=GateVerdict.FAIL,
            receipt_id=str(mapping.get("receipt_id") or ""),
            findings=tuple(all_findings),
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

    raw_receipt: Any = receipt
    if not isinstance(receipt, FulltextAttemptReceipt):
        try:
            # Structural parse first (does not authorize via defaults).
            if isinstance(receipt, Mapping):
                identity_findings = _identity_findings_from_mapping(receipt)
                findings.extend(identity_findings)
            receipt = FulltextAttemptReceipt.from_mapping(receipt)
        except MutableCutoffError as exc:
            return _failed_parse_result(
                kind=FailureKind.MUTABLE_CUTOFF,
                message=str(exc),
                path="observation_cutoff",
                raw=raw_receipt,
                extra=findings,
            )
        except SealTimestampError as exc:
            return _failed_parse_result(
                kind=_classify_seal_timestamp_error(exc),
                message=str(exc),
                path="timestamps",
                raw=raw_receipt,
                extra=findings,
            )
        except IdentityError as exc:
            return _failed_parse_result(
                kind=FailureKind.IDENTITY,
                message=str(exc),
                path="identity",
                raw=raw_receipt,
                extra=findings,
            )
        except (
            AttemptEvidenceError,
            DispositionAdmissionError,
            OfficialAuthorityError,
            ByteBindingError,
            FederalRegisterFulltextGateError,
        ) as exc:
            return _failed_parse_result(
                kind=FailureKind.OTHER,
                message=str(exc),
                path="receipt",
                raw=raw_receipt,
                extra=findings,
            )
    else:
        findings.extend(_validate_identity(receipt))

    clock, clock_finding = _resolve_verifier_clock(now)
    if clock_finding is not None:
        findings.append(clock_finding)

    if clock is not None:
        findings.extend(
            _validate_timestamps_against_clock(receipt, now=clock)
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


def _identity_findings_from_mapping(raw: Mapping[str, Any]) -> list[GateFinding]:
    findings: list[GateFinding] = []
    mode = raw.get("mode")
    if mode == MODE_FIXTURE:
        findings.append(
            _finding(
                FailureKind.FIXTURE_MODE,
                "fixture mode cannot authorize full-text admission",
                path="mode",
            )
        )
    missing = [name for name in IDENTITY_FIELDS if name not in raw]
    if missing:
        findings.append(
            _finding(
                FailureKind.IDENTITY,
                f"identity fields omitted: {missing}",
                path="identity",
                missing=missing,
            )
        )
    for name, expected in AUTHORIZING_IDENTITY.items():
        if name not in raw:
            continue
        value = raw.get(name)
        if not isinstance(value, str):
            findings.append(
                _finding(
                    FailureKind.IDENTITY,
                    f"identity field {name} must be a string",
                    path=name,
                    expected=expected,
                    actual_type=type(value).__name__,
                )
            )
        elif not value.strip():
            findings.append(
                _finding(
                    FailureKind.IDENTITY,
                    f"identity field {name} is empty",
                    path=name,
                )
            )
        elif value != expected:
            findings.append(
                _finding(
                    FailureKind.IDENTITY,
                    f"identity field {name} must be {expected!r}, got {value!r}",
                    path=name,
                    expected=expected,
                    actual=value,
                )
            )
    return findings


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
        FailureKind.HASH_MISMATCH: ByteBindingError,
        FailureKind.BYTE_BINDING: ByteBindingError,
        FailureKind.MISSING_TIMESTAMP: SealTimestampError,
        FailureKind.MALFORMED_TIMESTAMP: SealTimestampError,
        FailureKind.NON_UTC_TIMESTAMP: SealTimestampError,
        FailureKind.MUTABLE_CUTOFF: MutableCutoffError,
        FailureKind.FUTURE_CUTOFF: SealTimestampError,
        FailureKind.CUTOFF_SEAL_AFTER_OBSERVATION: SealTimestampError,
        FailureKind.RECEIPT_BEFORE_LAST_ATTEMPT: SealTimestampError,
        FailureKind.TIMESTAMP_AFTER_VERIFIER: SealTimestampError,
        FailureKind.MISSING_VERIFIER_TIME: VerifierClockError,
        FailureKind.CALLER_SKEW: VerifierClockError,
        FailureKind.MISSING_ALLOWED_REASON: DispositionAdmissionError,
        FailureKind.INCOMPLETE_EXHAUSTION: ExhaustionError,
        FailureKind.EXTRA_FRONTIER: FrontierError,
        FailureKind.DUPLICATE_LEDGER_KEY: FrontierError,
        FailureKind.AUTHORITY_HOST_MISMATCH: OfficialAuthorityError,
        FailureKind.FORMAT_MEDIA_MISMATCH: AttemptEvidenceError,
        FailureKind.BODY_NOT_ADMITTED: UnresolvedBodyError,
        FailureKind.EXCLUSION_ERASES_FAILURE: UnresolvedBodyError,
        FailureKind.NON_EXHAUSTIVE_NEGATIVE: ExhaustionError,
        FailureKind.MISSING_ATTEMPT_EVIDENCE: AttemptEvidenceError,
        FailureKind.OFFICIAL_AUTHORITY: OfficialAuthorityError,
        FailureKind.IDENTITY: IdentityError,
        FailureKind.FIXTURE_MODE: IdentityError,
        FailureKind.SCHEMA: FixtureSchemaError,
    }
    exc_cls = mapping.get(kind, FederalRegisterFulltextGateError)
    raise exc_cls(message)


def assert_fulltext_admission(
    receipt: FulltextAttemptReceipt | JsonMapping,
    *,
    now: Optional[datetime | str | ClockFn] = None,
    **kwargs: Any,
) -> GateResult:
    """Evaluate *receipt* and raise if the gate fails."""

    return evaluate_fulltext_attempt_receipt(
        receipt,
        now=now,
        raise_on_failure=True,
        **kwargs,
    )


def public_helper_rejects_skew_override() -> bool:
    """Return True when no authorizing helper accepts a tolerance override."""

    for fn in (
        evaluate_fulltext_attempt_receipt,
        assert_fulltext_admission,
        evaluate_fixture_case,
        evaluate_fulltext_fixture,
        assert_fixture_expectations,
    ):
        params = inspect.signature(fn).parameters
        for name in ("max_future_skew", "future_skew", "skew", "tolerance"):
            if name in params:
                return False
    return True


# ---------------------------------------------------------------------------
# Fixture load / expand / evaluate
# ---------------------------------------------------------------------------


def load_fulltext_fixture_payload(
    path: Optional[PathLike] = None,
) -> dict[str, Any]:
    """Load the sealed full-text attempt-receipts fixture as a raw mapping.

    Compact recipe fixtures may set ``generator`` to
    ``build_default_fulltext_fixture_payload`` so digests remain independently
    recomputed from captured immutable bytes instead of bulk golden dumps.
    """

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
    generator = raw.get("generator")
    if generator == "build_default_fulltext_fixture_payload" or "cases" not in raw:
        built = build_default_fulltext_fixture_payload()
        # Preserve declared case_ids order/set when the recipe lists them.
        declared_ids = raw.get("case_ids")
        if isinstance(declared_ids, Sequence) and not isinstance(
            declared_ids, (str, bytes)
        ):
            built_ids = [case["case_id"] for case in built["cases"]]
            if list(declared_ids) != built_ids:
                raise FixtureSchemaError(
                    "fixture case_ids must match build_default_fulltext_fixture_payload "
                    f"order; declared={list(declared_ids)!r} built={built_ids!r}"
                )
        return built
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
        # Non-identity structural defaults for compact fail recipes only.
        # Identity fields are never defaulted — authorizing evaluation requires
        # explicit exact values on pass cases.
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
    **kwargs: Any,
) -> GateResult:
    """Evaluate one expanded fixture case and return the gate result."""

    raw = _as_mapping(case, "case")
    receipt_raw = raw.get("receipt")
    if not isinstance(receipt_raw, Mapping):
        raise FixtureSchemaError("case.receipt must be a mapping")
    # Even a fixture helper is a public route to the authorizing evaluator.  It
    # must not manufacture a verifier-owned instant for a live receipt.  Tests
    # that need the sealed fixture clock pass ``fixture_verifier_now()``
    # explicitly; omitted time therefore fails closed in the common evaluator.
    clock = now
    try:
        return evaluate_fulltext_attempt_receipt(
            receipt_raw, now=clock, raise_on_failure=False, **kwargs
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
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Evaluate every fixture case; return per-case gate summaries."""

    cases = expand_fulltext_fixture_cases(payload, path=path)
    results: list[dict[str, Any]] = []
    for case in cases:
        result = evaluate_fixture_case(case, now=now, **kwargs)
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
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Evaluate the fixture and raise if any case mismatches expectations."""

    results = evaluate_fulltext_fixture(path=path, payload=payload, now=now, **kwargs)
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


def _bytes_field(label: str) -> str:
    """Return deterministic captured-byte payload text for fixtures."""

    return f"fr-fulltext-bytes:{label}"


def _authorizing_identity_fields() -> dict[str, str]:
    return dict(AUTHORIZING_IDENTITY)


def _admitted_attempt(
    *,
    attempt_id: str,
    authority: str,
    content_format: str,
    url: str,
    observed_at: str,
    media_type: str,
    terminal_reason: str = "admitted_full_text",
) -> dict[str, Any]:
    response_body = _bytes_field(f"response:{attempt_id}")
    content_body = _bytes_field(f"content:{attempt_id}")
    return {
        "attempt_id": attempt_id,
        "authority": authority,
        "content_format": content_format,
        "url": url,
        "observed_at": observed_at,
        "status": AttemptStatus.ADMITTED.value,
        "response_hash": content_sha256(response_body),
        "content_hash": content_sha256(content_body),
        "retry_count": 0,
        "terminal_reason": terminal_reason,
        "parser_result": ParserResult.SUCCESS.value,
        "body_available": True,
        "body_usable": True,
        "http_status": 200,
        "media_type": media_type,
        "response_bytes": response_body,
        "content_bytes": content_body,
    }


def _absence_attempt(
    *,
    attempt_id: str,
    authority: str,
    content_format: str,
    url: str,
    observed_at: str,
    media_type: str,
    terminal_reason: str,
    parser_result: str = ParserResult.NO_BODY.value,
    http_status: int = 404,
    retry_count: int = 1,
) -> dict[str, Any]:
    request_body = _bytes_field(f"request:{attempt_id}")
    response_body = _bytes_field(f"response-absence:{attempt_id}")
    return {
        "attempt_id": attempt_id,
        "authority": authority,
        "content_format": content_format,
        "url": url,
        "observed_at": observed_at,
        "status": AttemptStatus.NO_BODY.value,
        "request_hash": content_sha256(request_body),
        "response_hash": content_sha256(response_body),
        "retry_count": retry_count,
        "terminal_reason": terminal_reason,
        "parser_result": parser_result,
        "body_available": False,
        "body_usable": False,
        "http_status": http_status,
        "media_type": media_type,
        "request_bytes": request_body,
        "response_bytes": response_body,
    }


def _fr_html_url(document_number: str) -> str:
    return f"{FEDERAL_REGISTER_SITE}/documents/{document_number}"


def _govinfo_url(document_number: str) -> str:
    return f"{GOVINFO_SITE}/app/details/FR-{document_number}"


def example_full_text_document(
    *,
    document_number: str = "2026-04567",
    publication_date: str = "2026-03-15",
    fr_observed_at: str = "2026-08-10T01:00:00Z",
    govinfo_observed_at: str = "2026-08-10T01:05:00Z",
) -> dict[str, Any]:
    """Return a document ledger admitted as full text with complete frontier."""

    admitted = _admitted_attempt(
        attempt_id=f"{document_number}-fr-html",
        authority=OfficialAuthority.FEDERAL_REGISTER.value,
        content_format=ContentFormat.HTML.value,
        url=_fr_html_url(document_number),
        observed_at=fr_observed_at,
        media_type="text/html",
    )
    absence = _absence_attempt(
        attempt_id=f"{document_number}-govinfo-pdf",
        authority=OfficialAuthority.GOVINFO.value,
        content_format=ContentFormat.PDF.value,
        url=_govinfo_url(document_number),
        observed_at=govinfo_observed_at,
        media_type="application/pdf",
        terminal_reason="govinfo_package_has_no_body",
        parser_result=ParserResult.EMPTY.value,
        http_status=404,
    )
    return {
        "document_number": document_number,
        "publication_date": publication_date,
        "disposition": FulltextDisposition.FULL_TEXT.value,
        "attempts": [admitted, absence],
        "admitted_content_hash": admitted["content_hash"],
        "admitted_body_bytes": admitted["content_bytes"],
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
    """Return a non-body document with complete FR + GovInfo absence evidence."""

    fr_attempt = _absence_attempt(
        attempt_id=f"{document_number}-fr-html",
        authority=OfficialAuthority.FEDERAL_REGISTER.value,
        content_format=ContentFormat.HTML.value,
        url=_fr_html_url(document_number),
        observed_at=fr_observed_at,
        media_type="text/html",
        terminal_reason="official_html_has_metadata_only",
        parser_result=ParserResult.NO_BODY.value,
        http_status=200,
    )
    govinfo_attempt = _absence_attempt(
        attempt_id=f"{document_number}-govinfo-pdf",
        authority=OfficialAuthority.GOVINFO.value,
        content_format=ContentFormat.PDF.value,
        url=_govinfo_url(document_number),
        observed_at=govinfo_observed_at,
        media_type="application/pdf",
        terminal_reason="govinfo_package_has_no_body",
        parser_result=ParserResult.EMPTY.value,
        http_status=404,
    )
    return {
        "document_number": document_number,
        "publication_date": publication_date,
        "disposition": disposition,
        "allowed_reason": allowed_reason,
        "attempts": [fr_attempt, govinfo_attempt],
        "notes": "Both official alternatives exhausted with authorized absence.",
    }


def example_closed_fulltext_receipt(
    *,
    receipt_id: str = "fr-fulltext-closed-ok",
    observation_cutoff: str = DEFAULT_OBSERVATION_CUTOFF,
    cutoff_sealed_at: str = "2026-08-10T00:00:00Z",
    receipt_created_at: str = "2026-08-10T11:00:00Z",
    mode: str = MODE_LIVE,
) -> dict[str, Any]:
    """Return a minimal closed full-text attempt receipt that passes the gate."""

    full = example_full_text_document()
    meta = example_exhausted_non_body_document()
    payload = {
        "receipt_id": receipt_id,
        "observation_cutoff": observation_cutoff,
        "cutoff_sealed_at": cutoff_sealed_at,
        "receipt_created_at": receipt_created_at,
        "documents": [full, meta],
        "release_point": cutoff_release_point(observation_cutoff),
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "notes": "Sealed full-text attempt cohort for LCR-085 unit tests.",
    }
    payload.update(_authorizing_identity_fields())
    payload["mode"] = mode
    if mode == MODE_FIXTURE:
        # Fixture mode remains non-authorizing even with other v2 fields.
        payload["mode"] = MODE_FIXTURE
    return payload


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
            "attempts": [
                _absence_attempt(
                    attempt_id="2026-04600-fr-html",
                    authority=OfficialAuthority.FEDERAL_REGISTER.value,
                    content_format=ContentFormat.HTML.value,
                    url=_fr_html_url("2026-04600"),
                    observed_at="2026-08-10T02:00:00Z",
                    media_type="text/html",
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
    usable = _admitted_attempt(
        attempt_id="2026-04602-fr-html",
        authority=OfficialAuthority.FEDERAL_REGISTER.value,
        content_format=ContentFormat.HTML.value,
        url=_fr_html_url("2026-04602"),
        observed_at="2026-08-10T02:00:00Z",
        media_type="text/html",
    )
    usable["status"] = AttemptStatus.PARSED.value
    usable["terminal_reason"] = "parsed_but_not_admitted"
    body_not_admitted["documents"] = [
        {
            "document_number": "2026-04602",
            "publication_date": "2026-03-21",
            "disposition": FulltextDisposition.METADATA_ONLY.value,
            "allowed_reason": AllowedNonBodyReason.OFFICIAL_METADATA_ONLY.value,
            "attempts": [
                usable,
                _absence_attempt(
                    attempt_id="2026-04602-govinfo-pdf",
                    authority=OfficialAuthority.GOVINFO.value,
                    content_format=ContentFormat.PDF.value,
                    url=_govinfo_url("2026-04602"),
                    observed_at="2026-08-10T02:05:00Z",
                    media_type="application/pdf",
                    terminal_reason="no_body",
                    parser_result=ParserResult.EMPTY.value,
                    http_status=404,
                ),
            ],
        }
    ]

    exclusion_erases = example_closed_fulltext_receipt(
        receipt_id="fr-fail-exclusion-erases"
    )
    fetched = _admitted_attempt(
        attempt_id="2026-04603-fr-html",
        authority=OfficialAuthority.FEDERAL_REGISTER.value,
        content_format=ContentFormat.HTML.value,
        url=_fr_html_url("2026-04603"),
        observed_at="2026-08-10T02:00:00Z",
        media_type="text/html",
    )
    fetched["status"] = AttemptStatus.FETCHED.value
    fetched["terminal_reason"] = "body_fetched_then_excluded"
    exclusion_erases["documents"] = [
        {
            "document_number": "2026-04603",
            "publication_date": "2026-03-22",
            "disposition": FulltextDisposition.EXCLUDED.value,
            "allowed_reason": AllowedNonBodyReason.RIGHTS_OR_SCOPE_EXCLUSION.value,
            "attempts": [
                fetched,
                _absence_attempt(
                    attempt_id="2026-04603-govinfo-pdf",
                    authority=OfficialAuthority.GOVINFO.value,
                    content_format=ContentFormat.PDF.value,
                    url=_govinfo_url("2026-04603"),
                    observed_at="2026-08-10T02:05:00Z",
                    media_type="application/pdf",
                    terminal_reason="no_body",
                    parser_result=ParserResult.EMPTY.value,
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
                {
                    "attempt_id": "2026-04604-fr-html",
                    "authority": OfficialAuthority.FEDERAL_REGISTER.value,
                    "content_format": ContentFormat.HTML.value,
                    "url": _fr_html_url("2026-04604"),
                    "observed_at": "2026-08-10T02:00:00Z",
                    "status": AttemptStatus.FAILED.value,
                    "response_hash": _hash("failed-response"),
                    "retry_count": 3,
                    "terminal_reason": "permanent_fetch_failure",
                    "parser_result": ParserResult.PARSE_ERROR.value,
                    "body_available": False,
                    "body_usable": False,
                    "http_status": 500,
                    "media_type": "text/html",
                },
                _absence_attempt(
                    attempt_id="2026-04604-govinfo-pdf",
                    authority=OfficialAuthority.GOVINFO.value,
                    content_format=ContentFormat.PDF.value,
                    url=_govinfo_url("2026-04604"),
                    observed_at="2026-08-10T02:05:00Z",
                    media_type="application/pdf",
                    terminal_reason="no_body",
                ),
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
                {
                    "attempt_id": "2026-04605-fr-html",
                    "authority": OfficialAuthority.FEDERAL_REGISTER.value,
                    "content_format": ContentFormat.HTML.value,
                    "url": _fr_html_url("2026-04605"),
                    "observed_at": "2026-08-10T02:00:00Z",
                    "status": AttemptStatus.PENDING.value,
                    "retry_count": 0,
                    "terminal_reason": "",
                    "parser_result": ParserResult.NOT_RUN.value,
                    "body_available": False,
                    "body_usable": False,
                    "media_type": "text/html",
                },
                _absence_attempt(
                    attempt_id="2026-04605-govinfo-pdf",
                    authority=OfficialAuthority.GOVINFO.value,
                    content_format=ContentFormat.PDF.value,
                    url=_govinfo_url("2026-04605"),
                    observed_at="2026-08-10T02:05:00Z",
                    media_type="application/pdf",
                    terminal_reason="no_body",
                ),
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

    # LCR-085 mutation-matrix cases
    hashless_antibot = example_closed_fulltext_receipt(
        receipt_id="fr-fail-hashless-antibot"
    )
    hashless_antibot["documents"] = [
        {
            "document_number": "2026-04750",
            "publication_date": "2026-04-01",
            "disposition": FulltextDisposition.METADATA_ONLY.value,
            "allowed_reason": AllowedNonBodyReason.OFFICIAL_METADATA_ONLY.value,
            "attempts": [
                {
                    "attempt_id": "2026-04750-fr-html",
                    "authority": OfficialAuthority.FEDERAL_REGISTER.value,
                    "content_format": ContentFormat.HTML.value,
                    "url": _fr_html_url("2026-04750"),
                    "observed_at": "2026-08-10T02:00:00Z",
                    "status": AttemptStatus.FAILED.value,
                    "retry_count": 2,
                    "terminal_reason": "anti_bot",
                    "parser_result": ParserResult.ANTI_BOT.value,
                    "body_available": False,
                    "body_usable": False,
                    "http_status": 403,
                    "media_type": "text/html",
                },
                {
                    "attempt_id": "2026-04750-govinfo-pdf",
                    "authority": OfficialAuthority.GOVINFO.value,
                    "content_format": ContentFormat.PDF.value,
                    "url": _govinfo_url("2026-04750"),
                    "observed_at": "2026-08-10T02:05:00Z",
                    "status": AttemptStatus.FAILED.value,
                    "retry_count": 2,
                    "terminal_reason": "anti_bot",
                    "parser_result": ParserResult.ANTI_BOT.value,
                    "body_available": False,
                    "body_usable": False,
                    "http_status": 403,
                    "media_type": "application/pdf",
                },
            ],
        }
    ]

    skew_4m59 = example_closed_fulltext_receipt(receipt_id="fr-fail-skew-4m59")
    # Demonstrated four-minute-fifty-nine-second case under the old 5-minute
    # tolerance; zero-skew policy must deny.
    skew_4m59["receipt_created_at"] = "2026-08-10T12:04:59Z"

    fixture_mode = example_closed_fulltext_receipt(
        receipt_id="fr-fail-fixture-mode", mode=MODE_FIXTURE
    )

    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "policy_schema_version": POLICY_SCHEMA_VERSION,
        "gate_schema_version": SCHEMA_VERSION,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "mode": MODE_FIXTURE,
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "cutoff_sealed_at": "2026-08-10T00:00:00Z",
        "receipt_created_at": "2026-08-10T11:00:00Z",
        "verifier_clock": FIXTURE_VERIFIER_CLOCK_UTC,
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
        "official_full_text_sources": list(OFFICIAL_FULL_TEXT_SOURCES),
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "notes": (
            "Compact adversarial full-text attempt-receipt recipes for LCR-085. "
            "Cases encode complete frontier exhaustion, byte binding, v2 "
            "identity, zero-skew verifier time, and non-exhaustive negatives. "
            "Expand via expand_fulltext_fixture_cases()."
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
                "notes": "ABSTRACT_ONLY with allowed reason and complete frontier.",
            },
            {
                "case_id": "missing_body_exhausted_ok",
                "expected_status": "pass",
                "expected_kinds": [],
                "receipt": missing_ok,
                "notes": "MISSING_BODY_OFFICIAL with complete absence evidence.",
            },
            {
                "case_id": "excluded_exhausted_ok",
                "expected_status": "pass",
                "expected_kinds": [],
                "receipt": excluded_ok,
                "notes": "Exclusion with allowed reason and no usable body.",
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
                "notes": "METADATA_ONLY without GovInfo frontier entry.",
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
                "expected_kinds": ["exclusion_erases_failure"],
                "receipt": body_not_admitted,
                "notes": "Usable body hidden by metadata-only disposition.",
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
            {
                "case_id": "hashless_antibot_pair",
                "expected_status": "fail",
                "expected_kinds": ["non_exhaustive_negative"],
                "receipt": hashless_antibot,
                "notes": "Two hashless failed anti-bot attempts cannot exhaust.",
            },
            {
                "case_id": "skew_four_minute_fifty_nine",
                "expected_status": "fail",
                "expected_kinds": ["timestamp_after_verifier"],
                "receipt": skew_4m59,
                "notes": "4m59s after verifier fails under fixed zero skew.",
            },
            {
                "case_id": "fixture_mode_non_authorizing",
                "expected_status": "fail",
                "expected_kinds": ["fixture_mode"],
                "receipt": fixture_mode,
                "notes": "Fixture mode cannot authorize.",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

ALLOWED_NON_BODY_REASONS: Final = frozenset(item.value for item in AllowedNonBodyReason)

__all__ = [
    "ALLOWED_NON_BODY_REASONS",
    "AUTHORIZING_IDENTITY",
    "BODY_BEARING_FULLTEXT_DISPOSITIONS",
    "CANONICAL_FULLTEXT_FRONTIER",
    "DEFAULT_MAX_FUTURE_SKEW",
    "EXHAUSTION_REQUIRED_DISPOSITIONS",
    "FIXED_MAX_FUTURE_SKEW",
    "FIXTURE_SCHEMA_VERSION",
    "FIXTURE_VERIFIER_CLOCK_UTC",
    "GOAL_ID",
    "IDENTITY_FIELDS",
    "MODE_FIXTURE",
    "MODE_LIVE",
    "NON_BODY_FULLTEXT_DISPOSITIONS",
    "PRODUCER",
    "PROGRAM_ID",
    "REQUIRED_FULL_TEXT_AUTHORITIES",
    "SCHEMA_VERSION",
    "TASK_ID",
    "ZERO_FUTURE_SKEW",
    "AllowedNonBodyReason",
    "AttemptEvidenceError",
    "AttemptStatus",
    "ByteBindingError",
    "ContentFormat",
    "DispositionAdmissionError",
    "DocumentAttemptLedger",
    "ExhaustionError",
    "FailedFinalAdmissionError",
    "FailureKind",
    "FederalRegisterFulltextGateError",
    "FixtureSchemaError",
    "FormatAttempt",
    "FrontierError",
    "FulltextAttemptReceipt",
    "FulltextDisposition",
    "GateFinding",
    "GateResult",
    "GateVerdict",
    "IdentityError",
    "MissingHashError",
    "ParserResult",
    "SealTimestampError",
    "UnresolvedBodyError",
    "VerifierClockError",
    "assert_fixture_expectations",
    "assert_fulltext_admission",
    "build_default_fulltext_fixture_payload",
    "canonical_frontier_keys",
    "decode_captured_bytes",
    "default_fulltext_fixture_path",
    "evaluate_fixture_case",
    "evaluate_fulltext_attempt_receipt",
    "evaluate_fulltext_fixture",
    "example_closed_fulltext_receipt",
    "example_exhausted_non_body_document",
    "example_full_text_document",
    "expand_fulltext_fixture_cases",
    "fixture_verifier_now",
    "format_utc_timestamp_precise",
    "ledger_key",
    "load_fulltext_fixture_payload",
    "public_helper_rejects_skew_override",
    "raise_for_findings",
    "require_strict_utc_z_timestamp",
]
