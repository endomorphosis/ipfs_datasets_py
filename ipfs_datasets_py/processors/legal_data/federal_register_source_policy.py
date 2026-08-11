"""Official-source authority contract for the Federal Register (LCR-049).

Defines the sealed authorities, immutable UTC observation-cutoff rules,
document-number publication identity, and typed body-text dispositions used
by the cutoff-bound Federal Register completeness oracle.

Design invariants
-----------------
* FederalRegister.gov API is the official inventory/discovery authority.
* FederalRegister.gov and GovInfo are the official full-text authorities.
* Observation cutoffs are immutable UTC pins per run; tokens such as
  ``latest``, ``current``, ``live``, or branch refs are rejected.
* Completeness is cutoff-relative, not a claim of permanent currentness.
* Document-number + publication-date form durable publication identity.
* Metadata/abstract dispositions must never masquerade as full body text.
* Live network I/O is out of scope; unit tests use sealed fixtures only.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Mapping, Optional, Sequence, Union
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Schema identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "federal-register-source-policy-v1"
FIXTURE_SCHEMA_VERSION: Final = "federal-register-completion-receipts-v1"
TASK_ID: Final = "LCR-049"
GOAL_ID: Final = "LCR-G100"

DEFAULT_DATASET_REPO_ID: Final = "justicedao/ipfs_federal_register"
PREVIOUS_PUBLIC_PIN: Final = "720668ae016cc400916dda884c9005e03618edfa"

# Planning-date sealed observation cutoff (UTC). Completeness is relative
# to this pin, not wall-clock "currentness".
DEFAULT_OBSERVATION_CUTOFF: Final = "2026-08-10T00:00:00Z"
DEFAULT_OBSERVATION_CUTOFF_DATE: Final = "2026-08-10"

# Legacy baseline advertised endpoint and the inclusive delta start after it.
LEGACY_BASELINE_END_INCLUSIVE: Final = "2026-03-02"
LEGACY_DELTA_START_INCLUSIVE: Final = "2026-03-03"
LEGACY_BASELINE_START_INCLUSIVE: Final = "1994-01-01"
LEGACY_ADVERTISED_COUNT: Final = 993_703
LEGACY_MATERIALIZED_COUNT: Final = 993_708

# Official authorities.
FEDERAL_REGISTER_API_BASE: Final = "https://www.federalregister.gov/api/v1"
FEDERAL_REGISTER_DOCUMENTS_API: Final = (
    "https://www.federalregister.gov/api/v1/documents.json"
)
FEDERAL_REGISTER_SITE: Final = "https://www.federalregister.gov"
GOVINFO_SITE: Final = "https://www.govinfo.gov"
GOVINFO_API_BASE: Final = "https://api.govinfo.gov"
GOVINFO_CONTENT_BASE: Final = "https://www.govinfo.gov/content/pkg"

OFFICIAL_INVENTORY_SOURCE: Final = "FederalRegister.gov API"
OFFICIAL_FULL_TEXT_SOURCES: Final = ("FederalRegister.gov", "GovInfo")

MAX_API_PER_PAGE: Final = 1000
DEFAULT_API_PER_PAGE: Final = 100

CURRENTNESS_DISCLAIMER: Final = (
    "Federal Register completeness is cutoff-relative. Acquisition and "
    "publication timestamps record when a package was retrieved or sealed; "
    "they are not a claim that the daily register is permanently current as "
    "of wall-clock time. Retrieval output is a research aid and is not a "
    "substitute for the official source."
)

DEFAULT_FIXTURE_RELATIVE_PATH: Final = Path(
    "tests/fixtures/legal_ir/federal_register_completion_receipts.json"
)

# ---------------------------------------------------------------------------
# Regular expressions
# ---------------------------------------------------------------------------

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
# Federal Register document numbers are not uniformly ``YYYY-NNNNN``.  The
# official service retains historical two-character series (for example
# ``94-184`` and ``E9-9``) and prefixes corrected/republished modern documents
# (for example ``C1-2010-31877`` and ``R1-2017-02032``).  Historical series may
# have one- to six-digit tails; modern and revision forms retain their stricter
# four- to six-digit tails.  Keep this a closed grammar: the accepted
# two-character series are the exact known set enumerated by the
# FederalRegister.gov source tests, not a generic alphanumeric escape hatch.
_HISTORICAL_DOCUMENT_SERIES_PATTERN: Final = (
    r"(?:0[0-9]|20|9[2-9]|C[0-9]|E[13-9]|R[0-9]|X[019]|Z[4-9])"
)
_DOCUMENT_NUMBER_PATTERN: Final = (
    rf"(?:[CR][0-9]-[0-9]{{4}}-[0-9]{{4,6}}|"
    rf"[0-9]{{4}}-[0-9]{{4,6}}|"
    rf"{_HISTORICAL_DOCUMENT_SERIES_PATTERN}-[0-9]{{1,6}})"
)
_DOCUMENT_NUMBER_RE = re.compile(rf"^{_DOCUMENT_NUMBER_PATTERN}$")
_PUBLICATION_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_YEAR_MONTH_RE = re.compile(r"^[0-9]{4}-[0-9]{2}$")
_UTC_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$"
)
_MUTABLE_CUTOFF_RE = re.compile(
    r"^(?:latest|current|live|now|today|tip|trunk|main|master|HEAD|"
    r"default|prod|production|staging|dev|develop|development|nightly|"
    r"canary|origin/.*|refs/.*)$",
    re.IGNORECASE,
)
_MUTABLE_TOKEN_IN_PATH_RE = re.compile(
    r"(?:^|[/@:])(?:latest|main|master|HEAD|current|live|now)(?:$|[/@:])",
    re.IGNORECASE,
)
_OFFICIAL_HOSTS: Final = frozenset(
    {
        "federalregister.gov",
        "www.federalregister.gov",
        "api.federalregister.gov",
        "govinfo.gov",
        "www.govinfo.gov",
        "api.govinfo.gov",
    }
)
_OFFICIAL_HOST_SUFFIXES: Final = (
    ".federalregister.gov",
    ".govinfo.gov",
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FederalRegisterSourcePolicyError(ValueError):
    """Base error for Federal Register official-source policy failures."""


class MutableCutoffError(FederalRegisterSourcePolicyError):
    """Raised when an observation cutoff uses a mutable token or is unpinned."""


class OfficialAuthorityError(FederalRegisterSourcePolicyError):
    """Raised when a non-official authority is used for inventory or full text."""


class DocumentIdentityError(FederalRegisterSourcePolicyError):
    """Raised when document-number / publication identity is invalid."""


class BodyTextDispositionError(FederalRegisterSourcePolicyError):
    """Raised when body-text disposition is inconsistent with content."""


class TimestampError(FederalRegisterSourcePolicyError):
    """Raised when a required UTC timestamp is missing or malformed."""


class FixtureSchemaError(FederalRegisterSourcePolicyError):
    """Raised when the sealed completion-receipts fixture is malformed."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OfficialAuthority(str, Enum):
    """Sealed official authorities for inventory and full-text acquisition."""

    FEDERAL_REGISTER_API = "federal_register_api"
    FEDERAL_REGISTER = "federal_register"
    GOVINFO = "govinfo"

    @classmethod
    def coerce(cls, value: Any) -> "OfficialAuthority":
        if isinstance(value, OfficialAuthority):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "fr_api": cls.FEDERAL_REGISTER_API,
            "federalregister_api": cls.FEDERAL_REGISTER_API,
            "federalregister.gov_api": cls.FEDERAL_REGISTER_API,
            "api": cls.FEDERAL_REGISTER_API,
            "inventory": cls.FEDERAL_REGISTER_API,
            "discovery": cls.FEDERAL_REGISTER_API,
            "fr": cls.FEDERAL_REGISTER,
            "federalregister": cls.FEDERAL_REGISTER,
            "federalregister.gov": cls.FEDERAL_REGISTER,
            "www.federalregister.gov": cls.FEDERAL_REGISTER,
            "nara": cls.FEDERAL_REGISTER,
            "gpo": cls.GOVINFO,
            "govinfo.gov": cls.GOVINFO,
            "www.govinfo.gov": cls.GOVINFO,
            "api.govinfo.gov": cls.GOVINFO,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise OfficialAuthorityError(f"unknown official authority: {value!r}")

    @property
    def is_inventory_authority(self) -> bool:
        return self is OfficialAuthority.FEDERAL_REGISTER_API

    @property
    def is_full_text_authority(self) -> bool:
        return self in {
            OfficialAuthority.FEDERAL_REGISTER,
            OfficialAuthority.GOVINFO,
            OfficialAuthority.FEDERAL_REGISTER_API,
        }


class BodyTextDisposition(str, Enum):
    """Typed disposition of official full-text body for one document.

    Metadata-only and abstract-only states must never masquerade as body text.
    ``failed_final`` is never publication success.
    """

    FULL_TEXT = "full_text"
    HTML_BODY = "html_body"
    XML_BODY = "xml_body"
    PDF_BODY = "pdf_body"
    GOVINFO_BODY = "govinfo_body"
    ABSTRACT_ONLY = "abstract_only"
    METADATA_ONLY = "metadata_only"
    UNAVAILABLE = "unavailable"
    FAILED_FINAL = "failed_final"

    @classmethod
    def coerce(cls, value: Any) -> "BodyTextDisposition":
        if isinstance(value, BodyTextDisposition):
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
            "missing": cls.UNAVAILABLE,
            "none": cls.UNAVAILABLE,
            "missing_body_official": cls.UNAVAILABLE,
            "failed": cls.FAILED_FINAL,
            "failed_final": cls.FAILED_FINAL,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise BodyTextDispositionError(f"unknown body-text disposition: {value!r}")

    @property
    def has_usable_body(self) -> bool:
        return self in BODY_BEARING_DISPOSITIONS

    @property
    def is_non_body(self) -> bool:
        return self in NON_BODY_DISPOSITIONS

    @property
    def blocks_publication(self) -> bool:
        return self is BodyTextDisposition.FAILED_FINAL


BODY_BEARING_DISPOSITIONS: Final = frozenset(
    {
        BodyTextDisposition.FULL_TEXT,
        BodyTextDisposition.HTML_BODY,
        BodyTextDisposition.XML_BODY,
        BodyTextDisposition.PDF_BODY,
        BodyTextDisposition.GOVINFO_BODY,
    }
)

NON_BODY_DISPOSITIONS: Final = frozenset(
    {
        BodyTextDisposition.ABSTRACT_ONLY,
        BodyTextDisposition.METADATA_ONLY,
        BodyTextDisposition.UNAVAILABLE,
        BodyTextDisposition.FAILED_FINAL,
    }
)

# Long body text under a non-body disposition is treated as metadata-as-body.
METADATA_AS_BODY_CHAR_THRESHOLD: Final = 500

# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FederalRegisterSourcePolicyError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise FederalRegisterSourcePolicyError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise FederalRegisterSourcePolicyError(
            f"{name} exceeds maximum length {maximum}"
        )
    return text


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FederalRegisterSourcePolicyError(f"{name} must be an integer")
    if value < 0:
        raise FederalRegisterSourcePolicyError(f"{name} must be >= 0")
    return value


def canonical_json_dumps(payload: Mapping[str, Any]) -> str:
    """Return deterministic JSON text for fixtures and content addressing."""

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def digest_mapping(payload: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON encoding of *payload*."""

    return content_sha256(canonical_json_dumps(payload))


def normalize_sha256(value: Any, *, name: str = "sha256") -> str:
    """Normalize a SHA-256 digest to lowercase 64-char hex (no prefix)."""

    text = _require_non_empty_str(value, name).lower()
    if text.startswith("sha256:"):
        text = text[7:]
    if not _SHA256_HEX_RE.fullmatch(text):
        raise FederalRegisterSourcePolicyError(
            f"{name} must be a lowercase 64-char hex SHA-256; got {value!r}"
        )
    return text


def repository_root() -> Path:
    """Return the repository root containing ``tests/fixtures``."""

    return Path(__file__).resolve().parents[3]


def default_completion_fixture_path() -> Path:
    """Return the default on-disk path of the sealed completion receipts."""

    return repository_root() / DEFAULT_FIXTURE_RELATIVE_PATH


# ---------------------------------------------------------------------------
# UTC timestamps and observation cutoffs
# ---------------------------------------------------------------------------


def parse_utc_timestamp(value: Any, *, name: str = "timestamp") -> datetime:
    """Parse a required UTC timestamp (``...Z`` or offset-aware ISO-8601)."""

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise TimestampError(f"{name} must be a non-empty UTC timestamp")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise TimestampError(f"{name} must be ISO-8601 datetime: {value!r}") from exc
    else:
        raise TimestampError(f"{name} must be a datetime or ISO-8601 string")
    if dt.tzinfo is None:
        raise TimestampError(f"{name} must be timezone-aware UTC, got naive {value!r}")
    return dt.astimezone(timezone.utc)


def format_utc_timestamp(dt: datetime) -> str:
    """Format *dt* as an RFC-3339 UTC timestamp ending in ``Z``."""

    normalized = dt.astimezone(timezone.utc).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")


def is_mutable_cutoff(value: Any) -> bool:
    """Return True when *value* is a hard-coded mutable cutoff token."""

    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    if _MUTABLE_CUTOFF_RE.fullmatch(text):
        return True
    if _MUTABLE_TOKEN_IN_PATH_RE.search(text):
        return True
    return False


def require_immutable_observation_cutoff(
    value: Any,
    *,
    name: str = "observation_cutoff",
    allow_date_only: bool = True,
) -> str:
    """Require an immutable UTC observation cutoff pin.

    Accepts ``YYYY-MM-DDTHH:MM:SSZ`` (preferred) or a calendar date
    ``YYYY-MM-DD`` which is normalized to midnight UTC. Rejects mutable
    tokens (``latest``, ``current``, ``live``, branch refs) and naive /
    non-UTC timestamps.
    """

    text = _require_non_empty_str(value, name, maximum=64)
    if is_mutable_cutoff(text):
        raise MutableCutoffError(
            f"{name} must be an immutable UTC pin, not a mutable token: {value!r}"
        )
    if allow_date_only and _PUBLICATION_DATE_RE.fullmatch(text):
        # Date-only pins normalize to midnight UTC.
        validate_calendar_date(text, name=name)
        return f"{text}T00:00:00Z"
    if not _UTC_TIMESTAMP_RE.fullmatch(text):
        # Allow offset form via parse, then re-emit as Z.
        try:
            dt = parse_utc_timestamp(text, name=name)
        except TimestampError as exc:
            raise MutableCutoffError(
                f"{name} must be an immutable UTC timestamp (...Z), got {value!r}"
            ) from exc
        return format_utc_timestamp(dt)
    # Validate calendar components.
    dt = parse_utc_timestamp(text, name=name)
    return format_utc_timestamp(dt)


def observation_cutoff_date(cutoff: Any) -> str:
    """Return the calendar date (``YYYY-MM-DD``) of an observation cutoff."""

    pinned = require_immutable_observation_cutoff(cutoff)
    return pinned[:10]


def validate_calendar_date(value: Any, *, name: str = "date") -> str:
    """Validate an ISO calendar date ``YYYY-MM-DD``."""

    text = _require_non_empty_str(value, name, maximum=32)
    if not _PUBLICATION_DATE_RE.fullmatch(text):
        raise DocumentIdentityError(f"{name} must be YYYY-MM-DD; got {value!r}")
    year = int(text[0:4])
    month = int(text[5:7])
    day = int(text[8:10])
    if year < 1936 or year > 2100:
        raise DocumentIdentityError(f"{name} year out of plausible range: {value!r}")
    try:
        date(year, month, day)
    except ValueError as exc:
        raise DocumentIdentityError(f"{name} is not a valid calendar date: {value!r}") from exc
    return text


def parse_calendar_date(value: Any, *, name: str = "date") -> date:
    text = validate_calendar_date(value, name=name)
    return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))


def validate_year_month(value: Any, *, name: str = "year_month") -> str:
    """Validate a publication partition key ``YYYY-MM``."""

    text = _require_non_empty_str(value, name, maximum=16)
    if not _YEAR_MONTH_RE.fullmatch(text):
        raise DocumentIdentityError(f"{name} must be YYYY-MM; got {value!r}")
    month = int(text[5:7])
    if month < 1 or month > 12:
        raise DocumentIdentityError(f"{name} month out of range: {value!r}")
    return text


def days_between_inclusive(start: date, end: date) -> int:
    """Return inclusive day count for ``[start, end]``."""

    if end < start:
        raise FederalRegisterSourcePolicyError(
            f"end date {end.isoformat()} precedes start {start.isoformat()}"
        )
    return (end - start).days + 1


# ---------------------------------------------------------------------------
# Document identity
# ---------------------------------------------------------------------------


def validate_document_number(value: Any, *, name: str = "document_number") -> str:
    """Validate an official Federal Register document-number shape.

    In addition to modern ``YYYY-NNNNN`` identifiers, the official corpus
    contains historical two-character series and correction/republication
    identifiers such as ``C1-YYYY-NNNNN`` and ``R1-YYYY-NNNNN``.  Prefixes
    are preserved as identity-bearing bytes; they are never stripped or
    folded into the underlying document number.
    """

    text = _require_non_empty_str(value, name, maximum=32)
    if not _DOCUMENT_NUMBER_RE.fullmatch(text):
        raise DocumentIdentityError(
            f"{name} must be an official Federal Register document number; "
            f"got {value!r}"
        )
    parts = text.split("-")
    year_token = parts[1] if len(parts) == 3 else parts[0]
    if len(year_token) == 4 and year_token.isdigit():
        year = int(year_token)
        if year < 1936 or year > 2100:
            raise DocumentIdentityError(
                f"{name} year out of plausible range: {value!r}"
            )
    return text


def build_legal_id(
    document_number: Any,
    publication_date: Any,
    *,
    qualifier: Optional[str] = None,
) -> str:
    """Build stable publication identity ``fr:<doc>:<date>[:qualifier]``."""

    doc = validate_document_number(document_number)
    pub = validate_calendar_date(publication_date, name="publication_date")
    if qualifier is None or str(qualifier).strip() == "":
        return f"fr:{doc}:{pub}"
    q = _require_non_empty_str(qualifier, "qualifier", maximum=256).lower()
    return f"fr:{doc}:{pub}:{q}"


def parse_legal_id(value: Any, *, name: str = "legal_id") -> tuple[str, str, Optional[str]]:
    """Parse ``fr:<document_number>:<publication_date>[:qualifier...]``."""

    text = _require_non_empty_str(value, name)
    parts = text.split(":")
    if len(parts) < 3 or parts[0].lower() != "fr":
        raise DocumentIdentityError(
            f"{name} must match fr:<document_number>:<publication_date>"
            f"[:qualifier...]; got {value!r}"
        )
    doc = validate_document_number(parts[1], name=f"{name}.document_number")
    pub = validate_calendar_date(parts[2], name=f"{name}.publication_date")
    qualifier = ":".join(parts[3:]) if len(parts) > 3 else None
    if qualifier is not None:
        qualifier = qualifier.lower()
    return doc, pub, qualifier


# ---------------------------------------------------------------------------
# Official URLs and authorities
# ---------------------------------------------------------------------------


def _host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_official_host(host: str) -> bool:
    """Return True when *host* is an official FR/GovInfo host."""

    h = (host or "").lower().strip(".")
    if not h:
        return False
    if h in _OFFICIAL_HOSTS:
        return True
    return any(h.endswith(suffix) for suffix in _OFFICIAL_HOST_SUFFIXES)


def validate_official_url(value: Any, *, name: str = "official_source_url") -> str:
    """Require an absolute http(s) URL on an official FR/GovInfo host."""

    url = _require_non_empty_str(value, name, maximum=2048)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise OfficialAuthorityError(f"{name} must be an absolute http(s) URL")
    host = (parsed.hostname or "").lower()
    if not is_official_host(host):
        raise OfficialAuthorityError(
            f"{name} must target federalregister.gov or govinfo.gov; got {value!r}"
        )
    return url


def require_inventory_authority(value: Any) -> OfficialAuthority:
    """Require FederalRegister.gov API as the inventory authority."""

    authority = OfficialAuthority.coerce(value)
    if not authority.is_inventory_authority:
        raise OfficialAuthorityError(
            f"inventory authority must be FederalRegister.gov API, got {value!r}"
        )
    return authority


def require_full_text_authority(value: Any) -> OfficialAuthority:
    """Require an official full-text authority (FR or GovInfo)."""

    authority = OfficialAuthority.coerce(value)
    if not authority.is_full_text_authority:
        raise OfficialAuthorityError(
            f"full-text authority must be FederalRegister.gov or GovInfo, got {value!r}"
        )
    return authority


def official_authority_catalog() -> Mapping[str, Any]:
    """Return the sealed official-authority catalog (read-only)."""

    return MappingProxyType(
        {
            "inventory_source": OFFICIAL_INVENTORY_SOURCE,
            "inventory_authority": OfficialAuthority.FEDERAL_REGISTER_API.value,
            "inventory_url": FEDERAL_REGISTER_DOCUMENTS_API,
            "full_text_sources": list(OFFICIAL_FULL_TEXT_SOURCES),
            "full_text_authorities": [
                OfficialAuthority.FEDERAL_REGISTER.value,
                OfficialAuthority.GOVINFO.value,
            ],
            "max_api_per_page": MAX_API_PER_PAGE,
            "default_api_per_page": DEFAULT_API_PER_PAGE,
            "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
            "previous_public_pin": PREVIOUS_PUBLIC_PIN,
            "default_observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
            "legacy_baseline_end_inclusive": LEGACY_BASELINE_END_INCLUSIVE,
            "legacy_delta_start_inclusive": LEGACY_DELTA_START_INCLUSIVE,
            "legacy_baseline_start_inclusive": LEGACY_BASELINE_START_INCLUSIVE,
            "legacy_advertised_count": LEGACY_ADVERTISED_COUNT,
            "legacy_materialized_count": LEGACY_MATERIALIZED_COUNT,
            "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
            "schema_version": SCHEMA_VERSION,
            "task_id": TASK_ID,
        }
    )


# ---------------------------------------------------------------------------
# Body-text disposition validation
# ---------------------------------------------------------------------------


def validate_body_text_disposition_fields(
    *,
    disposition: Any,
    text: Any = None,
    abstract: Any = None,
    name: str = "text_availability",
) -> BodyTextDisposition:
    """Validate typed body disposition against optional text payloads.

    Fail-closed rules:

    * body-bearing dispositions require non-empty body text;
    * non-body dispositions must not carry long body text (metadata-as-body);
    * ``failed_final`` always blocks publication (caller enforces cohort rules).
    """

    disp = BodyTextDisposition.coerce(disposition)
    body = "" if text is None else str(text)
    abs_text = "" if abstract is None else str(abstract)

    if disp.has_usable_body:
        if not body.strip():
            raise BodyTextDispositionError(
                f"{name}={disp.value} requires non-empty body text"
            )
        return disp

    # Non-body dispositions must not masquerade as full text.
    if body.strip() and len(body.strip()) > METADATA_AS_BODY_CHAR_THRESHOLD:
        raise BodyTextDispositionError(
            f"{name}={disp.value} must not carry long body text "
            f"({len(body.strip())} chars > {METADATA_AS_BODY_CHAR_THRESHOLD}); "
            "metadata/abstract must not be represented as body text"
        )
    if (
        disp is BodyTextDisposition.METADATA_ONLY
        and body.strip()
        and not abs_text.strip()
        and len(body.strip()) > 64
    ):
        # Short navigation crumbs are tolerated; substantial text is not.
        raise BodyTextDispositionError(
            f"{name}=metadata_only must not carry substantial body text "
            f"({len(body.strip())} chars)"
        )
    return disp


def disposition_count_map(
    counts: Mapping[Any, Any] | None,
    *,
    name: str = "body_text_dispositions",
) -> dict[str, int]:
    """Normalize a disposition→count mapping with non-negative integers."""

    if counts is None:
        return {}
    if not isinstance(counts, Mapping):
        raise BodyTextDispositionError(f"{name} must be a mapping")
    result: dict[str, int] = {}
    for key, raw in counts.items():
        disp = BodyTextDisposition.coerce(key)
        result[disp.value] = _require_non_negative_int(raw, f"{name}[{key}]")
    return result


# ---------------------------------------------------------------------------
# Release / as-of pins
# ---------------------------------------------------------------------------


def require_exact_release_point(
    value: Any,
    *,
    name: str = "release_point",
) -> str:
    """Require a concrete release/as-of pin (never ``latest`` / branch)."""

    text = _require_non_empty_str(value, name, maximum=256)
    if is_mutable_cutoff(text):
        raise MutableCutoffError(
            f"{name} must be an exact pin, not a mutable token: {value!r}"
        )
    return text


def cutoff_release_point(cutoff: Any = DEFAULT_OBSERVATION_CUTOFF) -> str:
    """Return the canonical release-point token for a sealed cutoff."""

    pinned = require_immutable_observation_cutoff(cutoff)
    return f"fr/cutoff/{pinned[:10]}"


# ---------------------------------------------------------------------------
# Policy record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FederalRegisterSourcePolicy:
    """Sealed official-source policy for one cutoff-bound Federal Register run."""

    observation_cutoff: str = DEFAULT_OBSERVATION_CUTOFF
    inventory_authority: OfficialAuthority = OfficialAuthority.FEDERAL_REGISTER_API
    full_text_authorities: tuple[OfficialAuthority, ...] = (
        OfficialAuthority.FEDERAL_REGISTER,
        OfficialAuthority.GOVINFO,
    )
    dataset_repo_id: str = DEFAULT_DATASET_REPO_ID
    previous_public_pin: str = PREVIOUS_PUBLIC_PIN
    legacy_delta_start_inclusive: str = LEGACY_DELTA_START_INCLUSIVE
    legacy_baseline_end_inclusive: str = LEGACY_BASELINE_END_INCLUSIVE
    schema_version: str = SCHEMA_VERSION
    task_id: str = TASK_ID
    currentness_disclaimer: str = CURRENTNESS_DISCLAIMER

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "observation_cutoff",
            require_immutable_observation_cutoff(self.observation_cutoff),
        )
        object.__setattr__(
            self,
            "inventory_authority",
            require_inventory_authority(self.inventory_authority),
        )
        authorities = tuple(
            require_full_text_authority(item) for item in self.full_text_authorities
        )
        if not authorities:
            raise OfficialAuthorityError("full_text_authorities must be non-empty")
        object.__setattr__(self, "full_text_authorities", authorities)
        object.__setattr__(
            self,
            "dataset_repo_id",
            _require_non_empty_str(self.dataset_repo_id, "dataset_repo_id", maximum=256),
        )
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
            "legacy_delta_start_inclusive",
            validate_calendar_date(
                self.legacy_delta_start_inclusive, name="legacy_delta_start_inclusive"
            ),
        )
        object.__setattr__(
            self,
            "legacy_baseline_end_inclusive",
            validate_calendar_date(
                self.legacy_baseline_end_inclusive, name="legacy_baseline_end_inclusive"
            ),
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version", maximum=128),
        )
        object.__setattr__(
            self,
            "task_id",
            _require_non_empty_str(self.task_id, "task_id", maximum=32),
        )
        object.__setattr__(
            self,
            "currentness_disclaimer",
            _require_non_empty_str(
                self.currentness_disclaimer, "currentness_disclaimer", maximum=2048
            ),
        )

    @property
    def observation_cutoff_date(self) -> str:
        return self.observation_cutoff[:10]

    @property
    def release_point(self) -> str:
        return cutoff_release_point(self.observation_cutoff)

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_cutoff": self.observation_cutoff,
            "inventory_authority": self.inventory_authority.value,
            "full_text_authorities": [a.value for a in self.full_text_authorities],
            "dataset_repo_id": self.dataset_repo_id,
            "previous_public_pin": self.previous_public_pin,
            "legacy_delta_start_inclusive": self.legacy_delta_start_inclusive,
            "legacy_baseline_end_inclusive": self.legacy_baseline_end_inclusive,
            "release_point": self.release_point,
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "currentness_disclaimer": self.currentness_disclaimer,
            "official_catalog": dict(official_authority_catalog()),
        }

    @classmethod
    def from_mapping(cls, value: JsonMapping) -> "FederalRegisterSourcePolicy":
        if not isinstance(value, Mapping):
            raise FederalRegisterSourcePolicyError("policy must be a mapping")
        raw_authorities = value.get("full_text_authorities") or (
            OfficialAuthority.FEDERAL_REGISTER.value,
            OfficialAuthority.GOVINFO.value,
        )
        if not isinstance(raw_authorities, Sequence) or isinstance(
            raw_authorities, (str, bytes)
        ):
            raise FederalRegisterSourcePolicyError(
                "full_text_authorities must be a list"
            )
        return cls(
            observation_cutoff=value.get(
                "observation_cutoff", DEFAULT_OBSERVATION_CUTOFF
            ),
            inventory_authority=value.get(
                "inventory_authority", OfficialAuthority.FEDERAL_REGISTER_API
            ),
            full_text_authorities=tuple(raw_authorities),
            dataset_repo_id=value.get("dataset_repo_id", DEFAULT_DATASET_REPO_ID),
            previous_public_pin=value.get(
                "previous_public_pin", PREVIOUS_PUBLIC_PIN
            ),
            legacy_delta_start_inclusive=value.get(
                "legacy_delta_start_inclusive", LEGACY_DELTA_START_INCLUSIVE
            ),
            legacy_baseline_end_inclusive=value.get(
                "legacy_baseline_end_inclusive", LEGACY_BASELINE_END_INCLUSIVE
            ),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
            task_id=value.get("task_id", TASK_ID),
            currentness_disclaimer=value.get(
                "currentness_disclaimer", CURRENTNESS_DISCLAIMER
            ),
        )


@lru_cache(maxsize=1)
def default_source_policy() -> FederalRegisterSourcePolicy:
    """Return the process-local default sealed source policy."""

    return FederalRegisterSourcePolicy()


def clear_source_policy_cache() -> None:
    """Clear the process-local source-policy cache (for tests)."""

    default_source_policy.cache_clear()


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "BODY_BEARING_DISPOSITIONS",
    "CURRENTNESS_DISCLAIMER",
    "DEFAULT_API_PER_PAGE",
    "DEFAULT_DATASET_REPO_ID",
    "DEFAULT_OBSERVATION_CUTOFF",
    "DEFAULT_OBSERVATION_CUTOFF_DATE",
    "FEDERAL_REGISTER_DOCUMENTS_API",
    "FIXTURE_SCHEMA_VERSION",
    "GOAL_ID",
    "GOVINFO_CONTENT_BASE",
    "LEGACY_ADVERTISED_COUNT",
    "LEGACY_BASELINE_END_INCLUSIVE",
    "LEGACY_BASELINE_START_INCLUSIVE",
    "LEGACY_DELTA_START_INCLUSIVE",
    "LEGACY_MATERIALIZED_COUNT",
    "MAX_API_PER_PAGE",
    "METADATA_AS_BODY_CHAR_THRESHOLD",
    "NON_BODY_DISPOSITIONS",
    "OFFICIAL_FULL_TEXT_SOURCES",
    "OFFICIAL_INVENTORY_SOURCE",
    "PREVIOUS_PUBLIC_PIN",
    "SCHEMA_VERSION",
    "TASK_ID",
    "BodyTextDisposition",
    "BodyTextDispositionError",
    "DocumentIdentityError",
    "FederalRegisterSourcePolicy",
    "FederalRegisterSourcePolicyError",
    "FixtureSchemaError",
    "MutableCutoffError",
    "OfficialAuthority",
    "OfficialAuthorityError",
    "TimestampError",
    "build_legal_id",
    "canonical_json_dumps",
    "clear_source_policy_cache",
    "content_sha256",
    "cutoff_release_point",
    "days_between_inclusive",
    "default_completion_fixture_path",
    "default_source_policy",
    "digest_mapping",
    "disposition_count_map",
    "format_utc_timestamp",
    "is_mutable_cutoff",
    "is_official_host",
    "normalize_sha256",
    "observation_cutoff_date",
    "official_authority_catalog",
    "parse_calendar_date",
    "parse_legal_id",
    "parse_utc_timestamp",
    "repository_root",
    "require_exact_release_point",
    "require_full_text_authority",
    "require_immutable_observation_cutoff",
    "require_inventory_authority",
    "validate_body_text_disposition_fields",
    "validate_calendar_date",
    "validate_document_number",
    "validate_official_url",
    "validate_year_month",
]
