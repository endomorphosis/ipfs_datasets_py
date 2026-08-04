"""eCFR Title 37 cross-check acquisition (PATLAW-012).

Acquires current and historical Title 37 CFR structure, full XML metadata,
and version history from the electronic Code of Federal Regulations (eCFR)
API as an **unofficial presentation** for temporal cross-check only.

Design invariants:

* Every admitted record carries ``authority_tier=unofficial-current`` and
  artifact role :attr:`IdentityRole.DERIVED_PRESENTATION`. eCFR text must
  never impersonate an official annual CFR / GovInfo artifact.
* Edition identity is never the hard-coded token ``"latest"``; connectors
  record concrete ``up_to_date_as_of`` / version-date identifiers.
* Official annual CFR identity remains on
  :mod:`cfr_annual_processor` (separate module, separate identity fields).
* Pagination, retry exhaustion, HTTP 429 rate-limit, and schema failures are
  **typed** exceptions (not bare ``Exception`` / string codes).
* Live network I/O is opt-in; unit tests use recorded fixtures only.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Optional, Sequence, Union

from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    SCHEMA_VERSION as AUTHORITY_SCHEMA_VERSION,
    AuthoritySourceRecord,
    AuthoritySourceRegistry,
    AuthorityTier,
    ArtifactIdentity,
    HardCodedLatestEditionError,
    IdentityRole,
    RetryCachePolicy,
    SourceReceipt,
    VerificationState,
    canonical_json_dumps,
    reject_hard_coded_latest,
)

SCHEMA_VERSION = "ecfr-crosscheck-processor-v1"
FIXTURE_SCHEMA_VERSION = "ecfr-crosscheck-fixture-v1"

DEFAULT_TITLE = "37"
DEFAULT_JURISDICTION = "US"
COLLECTION_ECFR = "eCFR"
PROVIDER_ECFR = "ecfr"

ECFR_API_BASE = "https://www.ecfr.gov/api/versioner/v1"
ECFR_CURRENT_BASE = "https://www.ecfr.gov/current"

# Patent-relevant Title 37 anchors commonly exercised by the authority stack.
PATENT_PARTS = ("1", "3", "11", "41", "42")
DUTY_OF_DISCLOSURE_SECTION = "1.56"
DEFAULT_CROSSCHECK_SECTIONS = (
    "1.56",
    "1.97",
    "1.98",
    "41.50",
    "42.100",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SECTION_TOKEN_RE = re.compile(
    r"(?:§+\s*)?(?:sec(?:tion)?\.?\s*)?(?P<section>\d+(?:\.\d+)*(?:[A-Za-z0-9.\-]*)?)",
    re.IGNORECASE,
)
_PART_TOKEN_RE = re.compile(r"(?:part\s*)?(?P<part>\d+[A-Za-z0-9.\-]*)", re.IGNORECASE)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors (typed failure surface)
# ---------------------------------------------------------------------------


class EcfrCrosscheckError(ValueError):
    """Base error for eCFR cross-check acquisition failures."""


class EcfrPaginationError(EcfrCrosscheckError):
    """Raised when eCFR pagination is incomplete, cyclic, or out of bounds."""


class EcfrRetryExhaustedError(EcfrCrosscheckError):
    """Raised when bounded retry/backoff is exhausted without success."""


class EcfrRateLimitError(EcfrCrosscheckError):
    """Raised on HTTP 429 / rate-limit responses after policy handling."""

    def __init__(
        self,
        message: str = "eCFR rate limit (HTTP 429)",
        *,
        retry_after: Optional[float] = None,
        response_status: int = 429,
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.response_status = response_status


class EcfrSchemaError(EcfrCrosscheckError):
    """Raised when an eCFR API response or fixture fails schema validation."""


class FixtureSchemaError(EcfrCrosscheckError):
    """Raised when a fixture package is malformed."""


class SectionNotFoundError(EcfrCrosscheckError):
    """Raised when a requested CFR section is not present in the acquisition."""


class MissingVersionDateError(EcfrCrosscheckError):
    """Raised when version / up_to_date_as_of identity cannot be established."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ResolutionStatus(str, Enum):
    """Outcome of eCFR acquisition or section resolution."""

    RESOLVED = "resolved"
    UNKNOWN = "unknown"
    PARTIAL = "partial"
    ERROR = "error"


class EcfrContentKind(str, Enum):
    """Kinds of eCFR content packages a connector may acquire."""

    STRUCTURE = "structure"
    FULL_XML = "full_xml"
    VERSION_HISTORY = "version_history"
    SECTION = "section"
    TITLE = "title"
    OTHER = "other"

    @classmethod
    def coerce(cls, value: Any) -> "EcfrContentKind":
        if isinstance(value, EcfrContentKind):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "structure": cls.STRUCTURE,
            "title_structure": cls.STRUCTURE,
            "full_xml": cls.FULL_XML,
            "full-xml": cls.FULL_XML,
            "xml": cls.FULL_XML,
            "version_history": cls.VERSION_HISTORY,
            "versions": cls.VERSION_HISTORY,
            "history": cls.VERSION_HISTORY,
            "section": cls.SECTION,
            "title": cls.TITLE,
            "other": cls.OTHER,
        }
        if text in aliases:
            return aliases[text]
        for kind in cls:
            if kind.value == text or kind.name.lower() == text:
                return kind
        return cls.OTHER


class FailureKind(str, Enum):
    """Closed set of typed transport/schema failure kinds for fixtures."""

    PAGINATION = "pagination"
    RETRY_EXHAUSTED = "retry_exhausted"
    RATE_LIMIT_429 = "rate_limit_429"
    SCHEMA = "schema"
    OTHER = "other"

    @classmethod
    def coerce(cls, value: Any) -> "FailureKind":
        if isinstance(value, FailureKind):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "pagination": cls.PAGINATION,
            "page": cls.PAGINATION,
            "retry": cls.RETRY_EXHAUSTED,
            "retry_exhausted": cls.RETRY_EXHAUSTED,
            "retries_exhausted": cls.RETRY_EXHAUSTED,
            "429": cls.RATE_LIMIT_429,
            "rate_limit": cls.RATE_LIMIT_429,
            "rate_limit_429": cls.RATE_LIMIT_429,
            "http_429": cls.RATE_LIMIT_429,
            "schema": cls.SCHEMA,
            "fixture_schema": cls.SCHEMA,
            "other": cls.OTHER,
        }
        if text in aliases:
            return aliases[text]
        for kind in cls:
            if kind.value == text or kind.name.lower() == text:
                return kind
        return cls.OTHER


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EcfrCrosscheckError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise EcfrCrosscheckError(f"{name} must not contain NUL")
    return value.strip()


def _optional_str(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, "value")


def _require_sha256(value: Any, name: str = "sha256") -> str:
    text = _require_non_empty_str(value, name).lower()
    if not _SHA256_RE.fullmatch(text):
        raise EcfrCrosscheckError(f"{name} must be a lowercase 64-char hex SHA-256")
    return text


def _parse_utc(value: Any, *, name: str = "retrieved_at") -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise EcfrCrosscheckError(f"{name} must be ISO-8601 datetime") from exc
    else:
        raise EcfrCrosscheckError(f"{name} must be a datetime or ISO-8601 string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def _format_utc(dt: datetime) -> str:
    normalized = dt.astimezone(timezone.utc).replace(microsecond=(dt.microsecond // 1000) * 1000)
    return normalized.isoformat().replace("+00:00", "Z")


def _parse_optional_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        text = value.strip()
        reject_hard_coded_latest(text, field_name="date")
        return date.fromisoformat(text[:10])
    raise EcfrCrosscheckError(f"invalid date value: {value!r}")


def _date_to_str(value: Optional[date]) -> Optional[str]:
    return None if value is None else value.isoformat()


def _deep_sorted(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _deep_sorted(value[k]) for k in sorted(value.keys(), key=lambda x: str(x))}
    if isinstance(value, (list, tuple)):
        return [_deep_sorted(v) for v in value]
    return value


def normalize_title(title: Any) -> str:
    """Normalize a CFR title number to a stable string (e.g. ``\"37\"``)."""

    text = str(title if title is not None else "").strip()
    if not text:
        raise EcfrCrosscheckError("title must be non-empty")
    if text.isdigit():
        return str(int(text))
    return text.lower()


def normalize_part_token(part: Any) -> str:
    """Normalize a CFR part token (e.g. ``1``, ``part 41``)."""

    if part is None:
        raise EcfrCrosscheckError("part must be non-empty")
    text = str(part).strip()
    if not text:
        raise EcfrCrosscheckError("part must be non-empty")
    match = _PART_TOKEN_RE.search(text)
    if match:
        token = match.group("part")
    else:
        token = text
    # Strip leading zeros for pure numeric parts.
    if token.isdigit():
        return str(int(token))
    return token


def normalize_section_token(section: Any) -> str:
    """Normalize a CFR section citation to a stable section number.

    Accepts ``1.56``, ``§ 1.56``, ``37 CFR 1.56``, ``section 1.56``, etc.
    """

    if section is None:
        raise EcfrCrosscheckError("section must be non-empty")
    text = str(section).strip()
    if not text:
        raise EcfrCrosscheckError("section must be non-empty")
    # Prefer the last number-looking token after stripping common prefixes.
    cleaned = re.sub(r"(?i)\b\d+\s*(?:C\.?\s*F\.?\s*R\.?|CFR)\b", " ", text)
    cleaned = cleaned.replace("§", " ").strip()
    match = _SECTION_TOKEN_RE.search(cleaned)
    if match:
        token = match.group("section")
    else:
        token = text.lstrip("§").strip()
    return token


def stable_section_identity(
    *,
    title: Any = DEFAULT_TITLE,
    section: Any,
    jurisdiction: str = DEFAULT_JURISDICTION,
) -> str:
    """Return format-independent stable identity ``cfr:{jurisdiction}:{title}:{section}``."""

    t = normalize_title(title)
    s = normalize_section_token(section)
    j = _require_non_empty_str(jurisdiction, "jurisdiction").lower()
    return f"cfr:{j}:{t}:{s}"


def content_sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def ecfr_title_structure_url(*, title: Any = DEFAULT_TITLE, date_as_of: date | str) -> str:
    """Build eCFR structure endpoint for a title as of a concrete date."""

    as_of = _parse_optional_date(date_as_of)
    if as_of is None:
        raise MissingVersionDateError("date_as_of is required for eCFR structure URL")
    reject_hard_coded_latest(str(date_as_of), field_name="date_as_of")
    t = normalize_title(title)
    return f"{ECFR_API_BASE}/structure/{as_of.isoformat()}/title-{t}.json"


def ecfr_full_xml_url(*, title: Any = DEFAULT_TITLE, date_as_of: date | str) -> str:
    """Build eCFR full-title XML endpoint for a concrete version date."""

    as_of = _parse_optional_date(date_as_of)
    if as_of is None:
        raise MissingVersionDateError("date_as_of is required for eCFR full XML URL")
    reject_hard_coded_latest(str(date_as_of), field_name="date_as_of")
    t = normalize_title(title)
    return f"{ECFR_API_BASE}/full/{as_of.isoformat()}/title-{t}.xml"


def ecfr_versions_url(*, title: Any = DEFAULT_TITLE) -> str:
    """Build eCFR versions listing endpoint for a title."""

    t = normalize_title(title)
    return f"{ECFR_API_BASE}/versions/title-{t}.json"


def ecfr_section_presentation_url(
    *,
    title: Any = DEFAULT_TITLE,
    section: Any,
) -> str:
    """Build human presentation URL for an eCFR section (unofficial)."""

    t = normalize_title(title)
    s = normalize_section_token(section)
    return f"{ECFR_CURRENT_BASE}/title-{t}/section-{s}"


def version_identity(*, title: Any, up_to_date_as_of: date) -> str:
    """Concrete version identity string (never ``latest``)."""

    t = normalize_title(title)
    return f"ecfr-title-{t}-as-of-{up_to_date_as_of.isoformat()}"


# ---------------------------------------------------------------------------
# Domain records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AmendmentMeta:
    """Amendment / effective metadata retained for a CFR section snapshot."""

    amendatory_action: Optional[str] = None
    authority_citation: Optional[str] = None
    source_citation: Optional[str] = None
    effective_date: Optional[date] = None
    publication_date: Optional[date] = None
    fr_citation: Optional[str] = None
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "effective_date", _parse_optional_date(self.effective_date))
        object.__setattr__(self, "publication_date", _parse_optional_date(self.publication_date))
        for name in (
            "amendatory_action",
            "authority_citation",
            "source_citation",
            "fr_citation",
            "notes",
        ):
            raw = getattr(self, name)
            if raw is not None:
                object.__setattr__(self, name, _require_non_empty_str(raw, name))

    def to_dict(self) -> dict[str, Any]:
        return {
            "amendatory_action": self.amendatory_action,
            "authority_citation": self.authority_citation,
            "effective_date": _date_to_str(self.effective_date),
            "fr_citation": self.fr_citation,
            "notes": self.notes,
            "publication_date": _date_to_str(self.publication_date),
            "source_citation": self.source_citation,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping | None) -> Optional["AmendmentMeta"]:
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise EcfrSchemaError("amendment metadata must be a mapping")
        if not value:
            return None
        return cls(
            amendatory_action=value.get("amendatory_action"),
            authority_citation=value.get("authority_citation"),
            source_citation=value.get("source_citation"),
            effective_date=value.get("effective_date"),
            publication_date=value.get("publication_date"),
            fr_citation=value.get("fr_citation"),
            notes=value.get("notes"),
        )


@dataclass(frozen=True, slots=True)
class EcfrVersionPoint:
    """Concrete eCFR version identity for Title 37 (never ``latest``)."""

    up_to_date_as_of: date
    title: str = DEFAULT_TITLE
    provider: str = PROVIDER_ECFR
    version_id: Optional[str] = None
    content_sha256: Optional[str] = None
    source_url: Optional[str] = None
    structure_url: Optional[str] = None
    full_xml_url: Optional[str] = None
    versions_url: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    is_current_snapshot: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", normalize_title(self.title))
        as_of = _parse_optional_date(self.up_to_date_as_of)
        if as_of is None:
            raise MissingVersionDateError("up_to_date_as_of is required")
        object.__setattr__(self, "up_to_date_as_of", as_of)
        object.__setattr__(
            self, "provider", _require_non_empty_str(self.provider, "provider")
        )
        vid = self.version_id or version_identity(
            title=self.title, up_to_date_as_of=as_of
        )
        reject_hard_coded_latest(vid, field_name="version_id")
        object.__setattr__(self, "version_id", vid)
        if self.content_sha256 is not None:
            object.__setattr__(
                self, "content_sha256", _require_sha256(self.content_sha256, "content_sha256")
            )
        for name in ("source_url", "structure_url", "full_xml_url", "versions_url"):
            raw = getattr(self, name)
            if raw is not None:
                object.__setattr__(self, name, _require_non_empty_str(raw, name))
        if self.retrieved_at is not None:
            object.__setattr__(self, "retrieved_at", _parse_utc(self.retrieved_at))
        if not isinstance(self.metadata, Mapping):
            raise EcfrCrosscheckError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def canonical_id(self) -> str:
        return self.version_id or version_identity(
            title=self.title, up_to_date_as_of=self.up_to_date_as_of
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_sha256": self.content_sha256,
            "full_xml_url": self.full_xml_url,
            "is_current_snapshot": bool(self.is_current_snapshot),
            "metadata": _deep_sorted(dict(self.metadata)),
            "provider": self.provider,
            "retrieved_at": (
                None if self.retrieved_at is None else _format_utc(self.retrieved_at)
            ),
            "source_url": self.source_url,
            "structure_url": self.structure_url,
            "title": self.title,
            "up_to_date_as_of": self.up_to_date_as_of.isoformat(),
            "version_id": self.version_id,
            "versions_url": self.versions_url,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "EcfrVersionPoint":
        if not isinstance(value, Mapping):
            raise EcfrSchemaError("version point must be a mapping")
        as_of = value.get("up_to_date_as_of") or value.get("date") or value.get("version_date")
        if as_of in (None, ""):
            raise MissingVersionDateError("up_to_date_as_of is required on version point")
        return cls(
            up_to_date_as_of=as_of,  # type: ignore[arg-type]
            title=value.get("title", DEFAULT_TITLE),  # type: ignore[arg-type]
            provider=value.get("provider", PROVIDER_ECFR),  # type: ignore[arg-type]
            version_id=value.get("version_id"),
            content_sha256=value.get("content_sha256"),
            source_url=value.get("source_url"),
            structure_url=value.get("structure_url"),
            full_xml_url=value.get("full_xml_url"),
            versions_url=value.get("versions_url"),
            retrieved_at=value.get("retrieved_at"),
            is_current_snapshot=bool(value.get("is_current_snapshot", False)),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class EcfrSectionRecord:
    """One Title 37 section snapshot from eCFR (unofficial presentation)."""

    title: str
    section: str
    stable_id: str
    part: Optional[str] = None
    heading: Optional[str] = None
    citation: Optional[str] = None
    text_excerpt: Optional[str] = None
    content_sha256: Optional[str] = None
    source_url: Optional[str] = None
    media_type: str = "application/xml"
    up_to_date_as_of: Optional[date] = None
    version_id: Optional[str] = None
    amendment: Optional[AmendmentMeta] = None
    status: ResolutionStatus = ResolutionStatus.RESOLVED
    content_kind: EcfrContentKind = EcfrContentKind.SECTION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", normalize_title(self.title))
        object.__setattr__(self, "section", normalize_section_token(self.section))
        expected = stable_section_identity(title=self.title, section=self.section)
        object.__setattr__(self, "stable_id", expected)
        if self.part is not None:
            object.__setattr__(self, "part", normalize_part_token(self.part))
        for name in ("heading", "citation", "text_excerpt", "source_url"):
            raw = getattr(self, name)
            if raw is not None:
                object.__setattr__(self, name, _optional_str(raw))
        if self.version_id is not None:
            cleaned = _require_non_empty_str(self.version_id, "version_id")
            reject_hard_coded_latest(cleaned, field_name="version_id")
            object.__setattr__(self, "version_id", cleaned)
        if self.content_sha256 is not None:
            object.__setattr__(
                self, "content_sha256", _require_sha256(self.content_sha256, "content_sha256")
            )
        object.__setattr__(self, "up_to_date_as_of", _parse_optional_date(self.up_to_date_as_of))
        if not isinstance(self.status, ResolutionStatus):
            object.__setattr__(self, "status", ResolutionStatus(str(self.status)))
        if not isinstance(self.content_kind, EcfrContentKind):
            object.__setattr__(self, "content_kind", EcfrContentKind.coerce(self.content_kind))
        if self.amendment is not None and not isinstance(self.amendment, AmendmentMeta):
            raise EcfrSchemaError("amendment must be AmendmentMeta")
        if not isinstance(self.metadata, Mapping):
            raise EcfrCrosscheckError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))
        if self.citation is None:
            object.__setattr__(self, "citation", f"{self.title} CFR {self.section}")
        media = self.media_type or "application/xml"
        object.__setattr__(self, "media_type", _require_non_empty_str(media, "media_type"))

    def to_derived_identity(self, *, provider: str = PROVIDER_ECFR) -> Optional[ArtifactIdentity]:
        if not self.content_sha256 or not self.source_url:
            return None
        return ArtifactIdentity(
            provider=provider,
            source_id=self.stable_id,
            artifact_sha256=self.content_sha256,
            source_url=self.source_url,
            media_type=self.media_type,
            role=IdentityRole.DERIVED_PRESENTATION,
            upstream_package_id=self.version_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "amendment": None if self.amendment is None else self.amendment.to_dict(),
            "citation": self.citation,
            "content_kind": self.content_kind.value,
            "content_sha256": self.content_sha256,
            "heading": self.heading,
            "media_type": self.media_type,
            "metadata": _deep_sorted(dict(self.metadata)),
            "part": self.part,
            "section": self.section,
            "source_url": self.source_url,
            "stable_id": self.stable_id,
            "status": self.status.value,
            "text_excerpt": self.text_excerpt,
            "title": self.title,
            "up_to_date_as_of": _date_to_str(self.up_to_date_as_of),
            "version_id": self.version_id,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "EcfrSectionRecord":
        if not isinstance(value, Mapping):
            raise EcfrSchemaError("section record must be a mapping")
        title = normalize_title(value.get("title", DEFAULT_TITLE))
        section = normalize_section_token(value["section"])
        amendment = AmendmentMeta.from_dict(value.get("amendment") or value.get("amendment_meta"))
        status_raw = value.get("status", ResolutionStatus.RESOLVED.value)
        status = (
            status_raw
            if isinstance(status_raw, ResolutionStatus)
            else ResolutionStatus(str(status_raw))
        )
        return cls(
            title=title,
            section=section,
            stable_id=value.get("stable_id") or stable_section_identity(title=title, section=section),
            part=value.get("part"),
            heading=value.get("heading"),
            citation=value.get("citation"),
            text_excerpt=value.get("text_excerpt"),
            content_sha256=value.get("content_sha256"),
            source_url=value.get("source_url"),
            media_type=value.get("media_type") or "application/xml",
            up_to_date_as_of=value.get("up_to_date_as_of"),
            version_id=value.get("version_id"),
            amendment=amendment,
            status=status,
            content_kind=EcfrContentKind.coerce(value.get("content_kind", "section")),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class EcfrPackageMeta:
    """Title-level structure / full-XML package metadata from eCFR."""

    content_kind: EcfrContentKind
    content_sha256: str
    source_url: str
    media_type: str
    byte_size: Optional[int] = None
    version_id: Optional[str] = None
    up_to_date_as_of: Optional[date] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.content_kind, EcfrContentKind):
            object.__setattr__(self, "content_kind", EcfrContentKind.coerce(self.content_kind))
        object.__setattr__(
            self, "content_sha256", _require_sha256(self.content_sha256, "content_sha256")
        )
        object.__setattr__(
            self, "source_url", _require_non_empty_str(self.source_url, "source_url")
        )
        object.__setattr__(
            self, "media_type", _require_non_empty_str(self.media_type, "media_type")
        )
        if self.byte_size is not None and (
            not isinstance(self.byte_size, int) or self.byte_size < 0
        ):
            raise EcfrCrosscheckError("byte_size must be a non-negative int")
        if self.version_id is not None:
            cleaned = _require_non_empty_str(self.version_id, "version_id")
            reject_hard_coded_latest(cleaned, field_name="version_id")
            object.__setattr__(self, "version_id", cleaned)
        object.__setattr__(self, "up_to_date_as_of", _parse_optional_date(self.up_to_date_as_of))
        if not isinstance(self.metadata, Mapping):
            raise EcfrCrosscheckError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_derived_identity(self, *, provider: str, source_id: str) -> ArtifactIdentity:
        return ArtifactIdentity(
            provider=provider,
            source_id=source_id,
            artifact_sha256=self.content_sha256,
            source_url=self.source_url,
            media_type=self.media_type,
            byte_size=self.byte_size,
            role=IdentityRole.DERIVED_PRESENTATION,
            upstream_package_id=self.version_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "byte_size": self.byte_size,
            "content_kind": self.content_kind.value,
            "content_sha256": self.content_sha256,
            "media_type": self.media_type,
            "metadata": _deep_sorted(dict(self.metadata)),
            "source_url": self.source_url,
            "up_to_date_as_of": _date_to_str(self.up_to_date_as_of),
            "version_id": self.version_id,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "EcfrPackageMeta":
        if not isinstance(value, Mapping):
            raise EcfrSchemaError("package meta must be a mapping")
        return cls(
            content_kind=EcfrContentKind.coerce(value.get("content_kind") or value.get("kind")),
            content_sha256=value["content_sha256"],
            source_url=value["source_url"],
            media_type=value.get("media_type") or "application/json",
            byte_size=value.get("byte_size"),
            version_id=value.get("version_id"),
            up_to_date_as_of=value.get("up_to_date_as_of"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class TypedFailure:
    """Recorded typed failure for fixture replay / transport diagnostics."""

    kind: FailureKind
    message: str
    response_status: Optional[int] = None
    retry_after: Optional[float] = None
    page: Optional[int] = None
    attempts: Optional[int] = None
    endpoint: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, FailureKind):
            object.__setattr__(self, "kind", FailureKind.coerce(self.kind))
        object.__setattr__(self, "message", _require_non_empty_str(self.message, "message"))
        if not isinstance(self.metadata, Mapping):
            raise EcfrCrosscheckError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def raise_error(self) -> None:
        """Raise the corresponding typed exception for this failure."""

        if self.kind is FailureKind.PAGINATION:
            raise EcfrPaginationError(self.message)
        if self.kind is FailureKind.RETRY_EXHAUSTED:
            raise EcfrRetryExhaustedError(self.message)
        if self.kind is FailureKind.RATE_LIMIT_429:
            raise EcfrRateLimitError(
                self.message,
                retry_after=self.retry_after,
                response_status=self.response_status or 429,
            )
        if self.kind is FailureKind.SCHEMA:
            raise EcfrSchemaError(self.message)
        raise EcfrCrosscheckError(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempts": self.attempts,
            "endpoint": self.endpoint,
            "kind": self.kind.value,
            "message": self.message,
            "metadata": _deep_sorted(dict(self.metadata)),
            "page": self.page,
            "response_status": self.response_status,
            "retry_after": self.retry_after,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "TypedFailure":
        if not isinstance(value, Mapping):
            raise EcfrSchemaError("typed failure must be a mapping")
        return cls(
            kind=FailureKind.coerce(value.get("kind")),
            message=value.get("message") or value.get("error") or "typed failure",
            response_status=value.get("response_status"),
            retry_after=value.get("retry_after"),
            page=value.get("page"),
            attempts=value.get("attempts"),
            endpoint=value.get("endpoint"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class EcfrCrosscheckAcquisition:
    """Result of acquiring a current or historical Title 37 eCFR snapshot."""

    status: ResolutionStatus
    version: Optional[EcfrVersionPoint]
    sections: Mapping[str, EcfrSectionRecord] = field(default_factory=dict)
    packages: Mapping[str, EcfrPackageMeta] = field(default_factory=dict)
    version_history: tuple[date, ...] = ()
    authority_source: Optional[AuthoritySourceRecord] = None
    receipt: Optional[SourceReceipt] = None
    title: str = DEFAULT_TITLE
    presentation_label: str = "unofficial presentation"
    unknown_reason: Optional[str] = None
    notes: Optional[str] = None
    failures: tuple[TypedFailure, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, ResolutionStatus):
            object.__setattr__(self, "status", ResolutionStatus(str(self.status)))
        object.__setattr__(self, "title", normalize_title(self.title))
        object.__setattr__(
            self,
            "presentation_label",
            _require_non_empty_str(self.presentation_label, "presentation_label"),
        )
        # Enforce unofficial labeling language.
        label_l = self.presentation_label.lower()
        if "unofficial" not in label_l:
            object.__setattr__(
                self,
                "presentation_label",
                f"unofficial presentation ({self.presentation_label})",
            )
        secs = {
            normalize_section_token(k): (
                v if isinstance(v, EcfrSectionRecord) else EcfrSectionRecord.from_dict(v)
            )
            for k, v in dict(self.sections).items()
        }
        object.__setattr__(self, "sections", secs)
        pkgs = {
            str(k): (v if isinstance(v, EcfrPackageMeta) else EcfrPackageMeta.from_dict(v))
            for k, v in dict(self.packages).items()
        }
        object.__setattr__(self, "packages", pkgs)
        history = tuple(
            d if isinstance(d, date) else date.fromisoformat(str(d)[:10])
            for d in self.version_history
        )
        object.__setattr__(self, "version_history", history)
        fails = tuple(
            f if isinstance(f, TypedFailure) else TypedFailure.from_dict(f)
            for f in self.failures
        )
        object.__setattr__(self, "failures", fails)
        if not isinstance(self.metadata, Mapping):
            raise EcfrCrosscheckError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def is_unknown(self) -> bool:
        return self.status is ResolutionStatus.UNKNOWN

    @property
    def is_unofficial(self) -> bool:
        return True

    @property
    def up_to_date_as_of(self) -> Optional[date]:
        return None if self.version is None else self.version.up_to_date_as_of

    def get_section(self, section: Any) -> EcfrSectionRecord:
        key = normalize_section_token(section)
        try:
            return self.sections[key]
        except KeyError as exc:
            raise SectionNotFoundError(
                f"section {key!r} not present in eCFR acquisition"
            ) from exc

    def resolve_section(self, section: Any) -> EcfrSectionRecord:
        key = normalize_section_token(section)
        if key in self.sections:
            return self.sections[key]
        if self.is_unknown:
            return EcfrSectionRecord(
                title=self.title,
                section=key,
                stable_id=stable_section_identity(title=self.title, section=key),
                status=ResolutionStatus.UNKNOWN,
                up_to_date_as_of=self.up_to_date_as_of,
                version_id=None if self.version is None else self.version.version_id,
                metadata={"unknown_reason": self.unknown_reason or "missing version data"},
            )
        raise SectionNotFoundError(f"section {key!r} not present in eCFR acquisition")

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_source": (
                None if self.authority_source is None else self.authority_source.to_dict()
            ),
            "failures": [f.to_dict() for f in self.failures],
            "metadata": _deep_sorted(dict(self.metadata)),
            "notes": self.notes,
            "packages": {k: v.to_dict() for k, v in sorted(self.packages.items())},
            "presentation_label": self.presentation_label,
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "schema_version": SCHEMA_VERSION,
            "sections": {k: v.to_dict() for k, v in sorted(self.sections.items())},
            "status": self.status.value,
            "title": self.title,
            "unknown_reason": self.unknown_reason,
            "version": None if self.version is None else self.version.to_dict(),
            "version_history": [d.isoformat() for d in self.version_history],
        }

    def to_canonical_json(self) -> str:
        return canonical_json_dumps(self.to_dict())


# ---------------------------------------------------------------------------
# Fixture I/O
# ---------------------------------------------------------------------------


def default_fixture_dir() -> Path:
    """Return the repository Title 37 CFR fixture directory when present."""

    here = Path(__file__).resolve()
    candidates = [
        here.parents[4] / "tests" / "fixtures" / "legal_data" / "patent_authorities" / "cfr",
        Path.cwd() / "tests" / "fixtures" / "legal_data" / "patent_authorities" / "cfr",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[0]


def load_json_fixture(path: PathLike) -> dict[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise FixtureSchemaError(f"fixture root must be a mapping: {p}")
    return dict(payload)


def _build_receipt(version: EcfrVersionPoint) -> Optional[SourceReceipt]:
    endpoint = version.source_url or version.structure_url or version.full_xml_url
    if not endpoint:
        return None
    return SourceReceipt(
        endpoint=endpoint,
        retrieved_at=version.retrieved_at or datetime.now(timezone.utc),
        response_status=200,
        sanitized_request={"method": "GET", "provider": PROVIDER_ECFR},
        upstream_id=version.version_id,
        content_sha256=version.content_sha256,
        media_type="application/json",
        retry_count=0,
        metadata={
            "up_to_date_as_of": version.up_to_date_as_of.isoformat(),
            "presentation": "unofficial",
        },
    )


def _build_authority_source(
    version: EcfrVersionPoint,
    *,
    packages: Mapping[str, EcfrPackageMeta],
    receipt: Optional[SourceReceipt],
) -> AuthoritySourceRecord:
    """Build unofficial-current authority record with derived presentation only."""

    source_key = f"ecfr:title-{version.title}:{version.canonical_id}"
    # Prefer full_xml package for presentation identity; fall back to structure.
    derived: Optional[ArtifactIdentity] = None
    for key in ("full_xml", "structure", "title"):
        pkg = packages.get(key)
        if pkg is not None:
            derived = pkg.to_derived_identity(
                provider=version.provider, source_id=source_key
            )
            break
    if derived is None and version.content_sha256 and version.source_url:
        derived = ArtifactIdentity(
            provider=version.provider,
            source_id=source_key,
            artifact_sha256=version.content_sha256,
            source_url=version.source_url,
            media_type="application/xml",
            role=IdentityRole.DERIVED_PRESENTATION,
            upstream_package_id=version.version_id,
        )

    return AuthoritySourceRecord(
        source_key=source_key,
        authority_tier=AuthorityTier.UNOFFICIAL_CURRENT,
        collection=COLLECTION_ECFR,
        jurisdiction=DEFAULT_JURISDICTION,
        title=version.title,
        citation=f"Title {version.title} C.F.R. (eCFR)",
        edition=version.canonical_id,
        version=version.up_to_date_as_of.isoformat(),
        # No official_artifact — eCFR is presentation only.
        official_artifact=None,
        derived_presentation=derived,
        receipt=receipt,
        verification_state=VerificationState.UNVERIFIED,
        publication_date=version.up_to_date_as_of,
        notes=(
            "eCFR unofficial presentation for temporal cross-check only; "
            "verify dispositive text against official annual CFR / FR artifacts."
        ),
        metadata={
            "processor_schema": SCHEMA_VERSION,
            "authority_schema": AUTHORITY_SCHEMA_VERSION,
            "presentation_label": "unofficial presentation",
            "is_current_snapshot": bool(version.is_current_snapshot),
            "up_to_date_as_of": version.up_to_date_as_of.isoformat(),
        },
    )


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class EcfrCrosscheckProcessor:
    """Acquire current/historical Title 37 eCFR content for cross-check.

    Primary path is fixture replay. Live network discovery is not performed by
    default so tests and offline operators remain deterministic.
    """

    def __init__(
        self,
        *,
        fixture_dir: PathLike | None = None,
        registry: AuthoritySourceRegistry | None = None,
        retry_cache_policy: RetryCachePolicy | None = None,
        default_title: str = DEFAULT_TITLE,
    ) -> None:
        self.fixture_dir = Path(fixture_dir) if fixture_dir else default_fixture_dir()
        self.registry = (
            registry
            if registry is not None
            else AuthoritySourceRegistry(default_retry_cache_policy=retry_cache_policy)
        )
        self.retry_cache_policy = (
            retry_cache_policy
            if retry_cache_policy is not None
            else self.registry.default_retry_cache_policy
        )
        self.default_title = normalize_title(default_title)
        self._acquisitions: dict[str, EcfrCrosscheckAcquisition] = {}

    # ------------------------------------------------------------------
    # Fixture load
    # ------------------------------------------------------------------

    def load_fixture_package(self, path: PathLike | None = None) -> dict[str, Any]:
        target = Path(path) if path is not None else self._default_package_path()
        if target.is_dir():
            for name in (
                "ecfr_current_recipe.json",
                "ecfr_historical_recipe.json",
                "ecfr_crosscheck_recipe.json",
            ):
                candidate = target / name
                if candidate.is_file():
                    target = candidate
                    break
            else:
                raise FixtureSchemaError(
                    f"fixture directory {target} lacks an eCFR recipe JSON"
                )
        payload = load_json_fixture(target)
        schema = payload.get("schema_version")
        if schema and schema not in {FIXTURE_SCHEMA_VERSION, SCHEMA_VERSION}:
            if not str(schema).startswith("ecfr-crosscheck"):
                raise FixtureSchemaError(
                    f"unsupported fixture schema_version {schema!r} in {target}"
                )
        return payload

    def _default_package_path(self) -> Path:
        for name in ("ecfr_current_recipe.json", "ecfr_crosscheck_recipe.json"):
            recipe = self.fixture_dir / name
            if recipe.is_file():
                return recipe
        return self.fixture_dir

    def acquire_from_fixture(
        self,
        path: PathLike | None = None,
        *,
        register: bool = True,
        raise_recorded_failures: bool = False,
    ) -> EcfrCrosscheckAcquisition:
        payload = self.load_fixture_package(path)
        return self.acquire_from_payload(
            payload, register=register, raise_recorded_failures=raise_recorded_failures
        )

    def acquire_from_payload(
        self,
        payload: JsonMapping,
        *,
        register: bool = True,
        raise_recorded_failures: bool = False,
    ) -> EcfrCrosscheckAcquisition:
        if not isinstance(payload, Mapping):
            raise FixtureSchemaError("payload must be a mapping")

        # Recorded typed failures may be raised for transport-simulation tests.
        failures = tuple(
            TypedFailure.from_dict(item)
            for item in (payload.get("failures") or [])
            if isinstance(item, Mapping)
        )
        if raise_recorded_failures and failures:
            failures[0].raise_error()

        title = normalize_title(payload.get("title") or self.default_title)
        version_raw = (
            payload.get("version")
            or payload.get("version_point")
            or payload.get("snapshot")
        )

        if not version_raw:
            return EcfrCrosscheckAcquisition(
                status=ResolutionStatus.UNKNOWN,
                version=None,
                sections={},
                packages={},
                title=title,
                unknown_reason="missing version data",
                notes="eCFR up_to_date_as_of unavailable; cross-check authority is unknown.",
                failures=failures,
                metadata={"schema_version": payload.get("schema_version")},
            )

        if isinstance(version_raw, str):
            # Accept bare ISO date as version identity.
            version_raw = {
                "up_to_date_as_of": version_raw,
                "provider": PROVIDER_ECFR,
                "title": title,
            }

        if not isinstance(version_raw, Mapping):
            raise FixtureSchemaError("version must be a mapping or ISO date string")

        as_of_token = (
            version_raw.get("up_to_date_as_of")
            or version_raw.get("date")
            or version_raw.get("version_date")
        )
        if as_of_token in (None, ""):
            return EcfrCrosscheckAcquisition(
                status=ResolutionStatus.UNKNOWN,
                version=None,
                sections={},
                packages={},
                title=title,
                unknown_reason="missing version data",
                notes="Version mapping present but no concrete up_to_date_as_of.",
                failures=failures,
                metadata={"schema_version": payload.get("schema_version")},
            )

        try:
            reject_hard_coded_latest(str(as_of_token), field_name="up_to_date_as_of")
            version = EcfrVersionPoint.from_dict(
                {**dict(version_raw), "title": version_raw.get("title", title)}
            )
        except (MissingVersionDateError, HardCodedLatestEditionError, EcfrCrosscheckError) as exc:
            return EcfrCrosscheckAcquisition(
                status=ResolutionStatus.UNKNOWN,
                version=None,
                sections={},
                packages={},
                title=title,
                unknown_reason=str(exc),
                notes="Failed to parse eCFR version; treating cross-check as unknown.",
                failures=failures,
                metadata={
                    "schema_version": payload.get("schema_version"),
                    "error": str(exc),
                },
            )

        # Fill default endpoint URLs when omitted from compact recipes.
        structure_url = version.structure_url or ecfr_title_structure_url(
            title=version.title, date_as_of=version.up_to_date_as_of
        )
        full_xml_url = version.full_xml_url or ecfr_full_xml_url(
            title=version.title, date_as_of=version.up_to_date_as_of
        )
        versions_url = version.versions_url or ecfr_versions_url(title=version.title)
        source_url = version.source_url or structure_url
        version = EcfrVersionPoint(
            up_to_date_as_of=version.up_to_date_as_of,
            title=version.title,
            provider=version.provider,
            version_id=version.version_id,
            content_sha256=version.content_sha256,
            source_url=source_url,
            structure_url=structure_url,
            full_xml_url=full_xml_url,
            versions_url=versions_url,
            retrieved_at=version.retrieved_at,
            is_current_snapshot=version.is_current_snapshot,
            metadata=version.metadata,
        )

        packages: dict[str, EcfrPackageMeta] = {}
        for key, raw_pkg in (payload.get("packages") or {}).items():
            if isinstance(raw_pkg, Mapping):
                packages[str(key)] = EcfrPackageMeta.from_dict(raw_pkg)
        # Synthesize structure / full_xml packages from version when absent.
        if "structure" not in packages and version.content_sha256:
            packages["structure"] = EcfrPackageMeta(
                content_kind=EcfrContentKind.STRUCTURE,
                content_sha256=content_sha256(
                    f"structure|{version.canonical_id}|{version.content_sha256}"
                ),
                source_url=structure_url,
                media_type="application/json",
                version_id=version.version_id,
                up_to_date_as_of=version.up_to_date_as_of,
            )
        if "full_xml" not in packages:
            xml_sha = version.content_sha256 or content_sha256(f"full-xml|{version.canonical_id}")
            packages["full_xml"] = EcfrPackageMeta(
                content_kind=EcfrContentKind.FULL_XML,
                content_sha256=xml_sha
                if version.content_sha256
                else content_sha256(f"full-xml|{version.canonical_id}"),
                source_url=full_xml_url,
                media_type="application/xml",
                version_id=version.version_id,
                up_to_date_as_of=version.up_to_date_as_of,
            )

        sections: dict[str, EcfrSectionRecord] = {}
        for raw_sec in payload.get("sections") or []:
            if not isinstance(raw_sec, Mapping):
                continue
            sec = EcfrSectionRecord.from_dict(
                {
                    **dict(raw_sec),
                    "title": raw_sec.get("title", version.title),
                    "up_to_date_as_of": raw_sec.get(
                        "up_to_date_as_of", version.up_to_date_as_of.isoformat()
                    ),
                    "version_id": raw_sec.get("version_id", version.version_id),
                    "source_url": raw_sec.get("source_url")
                    or ecfr_section_presentation_url(
                        title=version.title, section=raw_sec["section"]
                    ),
                }
            )
            sections[sec.section] = sec

        history_raw = payload.get("version_history") or payload.get("versions") or []
        history: list[date] = []
        for item in history_raw:
            if isinstance(item, Mapping):
                d = item.get("date") or item.get("up_to_date_as_of") or item.get("version_date")
            else:
                d = item
            parsed = _parse_optional_date(d)
            if parsed is not None:
                history.append(parsed)
        if version.up_to_date_as_of not in history:
            history.append(version.up_to_date_as_of)
        history = sorted(set(history))

        receipt = _build_receipt(version)
        authority = _build_authority_source(version, packages=packages, receipt=receipt)

        if register:
            self.registry.register(authority, overwrite=True)
            if receipt is not None and authority.receipt is None:
                self.registry.attach_receipt(authority.source_key, receipt)

        presentation_label = (
            payload.get("presentation_label")
            or "unofficial presentation"
        )

        acquisition = EcfrCrosscheckAcquisition(
            status=ResolutionStatus.RESOLVED,
            version=version,
            sections=sections,
            packages=packages,
            version_history=tuple(history),
            authority_source=authority,
            receipt=receipt,
            title=version.title,
            presentation_label=str(presentation_label),
            notes=payload.get("notes")
            or (
                "eCFR unofficial presentation; verify dispositive text against "
                "official annual CFR / FR artifacts."
            ),
            failures=failures,
            metadata={
                "schema_version": payload.get("schema_version") or FIXTURE_SCHEMA_VERSION,
                "fixture_id": payload.get("fixture_id"),
                "section_count": len(sections),
                "package_count": len(packages),
                "is_current_snapshot": bool(version.is_current_snapshot),
            },
        )
        self._acquisitions[version.canonical_id] = acquisition
        return acquisition

    # ------------------------------------------------------------------
    # Failure simulation API (typed)
    # ------------------------------------------------------------------

    def raise_typed_failure(self, failure: TypedFailure | JsonMapping | FailureKind) -> None:
        """Raise a typed transport/schema failure (for callers and tests)."""

        if isinstance(failure, FailureKind):
            TypedFailure(kind=failure, message=f"simulated {failure.value} failure").raise_error()
        if isinstance(failure, TypedFailure):
            failure.raise_error()
        if isinstance(failure, Mapping):
            TypedFailure.from_dict(failure).raise_error()
        raise EcfrCrosscheckError(f"unsupported failure descriptor: {failure!r}")

    def classify_http_failure(
        self,
        *,
        response_status: int,
        message: str | None = None,
        retry_after: float | None = None,
        attempts: int | None = None,
        page: int | None = None,
        endpoint: str | None = None,
        max_attempts: int | None = None,
    ) -> TypedFailure:
        """Map an HTTP/transport outcome to a typed :class:`TypedFailure`."""

        limit = max_attempts if max_attempts is not None else self.retry_cache_policy.max_attempts
        if response_status == 429:
            return TypedFailure(
                kind=FailureKind.RATE_LIMIT_429,
                message=message or "eCFR rate limit (HTTP 429)",
                response_status=429,
                retry_after=retry_after,
                attempts=attempts,
                endpoint=endpoint,
            )
        if page is not None and page < 0:
            return TypedFailure(
                kind=FailureKind.PAGINATION,
                message=message or f"invalid eCFR page index {page}",
                response_status=response_status,
                page=page,
                endpoint=endpoint,
            )
        if attempts is not None and attempts >= limit:
            return TypedFailure(
                kind=FailureKind.RETRY_EXHAUSTED,
                message=message
                or f"eCFR retries exhausted after {attempts} attempts (limit {limit})",
                response_status=response_status,
                attempts=attempts,
                endpoint=endpoint,
            )
        if response_status >= 400:
            return TypedFailure(
                kind=FailureKind.OTHER,
                message=message or f"eCFR HTTP {response_status}",
                response_status=response_status,
                attempts=attempts,
                endpoint=endpoint,
            )
        return TypedFailure(
            kind=FailureKind.OTHER,
            message=message or "eCFR transport failure",
            response_status=response_status,
            attempts=attempts,
            endpoint=endpoint,
        )

    def validate_pagination(
        self,
        *,
        page: int,
        page_size: int,
        total_items: int | None = None,
        next_page_token: str | None = None,
        seen_tokens: Iterable[str] | None = None,
    ) -> None:
        """Validate pagination parameters; raise :class:`EcfrPaginationError` on failure."""

        if page < 1:
            raise EcfrPaginationError(f"page must be >= 1, got {page}")
        if page_size < 1:
            raise EcfrPaginationError(f"page_size must be >= 1, got {page_size}")
        if total_items is not None:
            if total_items < 0:
                raise EcfrPaginationError(f"total_items must be >= 0, got {total_items}")
            max_page = max(1, (total_items + page_size - 1) // page_size) if total_items else 1
            if page > max_page:
                raise EcfrPaginationError(
                    f"page {page} exceeds max page {max_page} for total_items={total_items}"
                )
        if next_page_token and seen_tokens is not None:
            seen = set(seen_tokens)
            if next_page_token in seen:
                raise EcfrPaginationError(
                    f"pagination cycle detected for token {next_page_token!r}"
                )

    def validate_api_schema(self, payload: Any, *, required_keys: Sequence[str]) -> dict[str, Any]:
        """Validate a minimal eCFR API response shape; raise :class:`EcfrSchemaError`."""

        if not isinstance(payload, Mapping):
            raise EcfrSchemaError("eCFR API response must be a mapping")
        missing = [k for k in required_keys if k not in payload]
        if missing:
            raise EcfrSchemaError(
                f"eCFR API response missing required keys: {missing}"
            )
        return dict(payload)

    # ------------------------------------------------------------------
    # Resolution API
    # ------------------------------------------------------------------

    def acquire_unknown(
        self, *, reason: str = "missing version data", title: Any | None = None
    ) -> EcfrCrosscheckAcquisition:
        return EcfrCrosscheckAcquisition(
            status=ResolutionStatus.UNKNOWN,
            version=None,
            sections={},
            packages={},
            title=self.default_title if title is None else normalize_title(title),
            unknown_reason=reason,
            notes="eCFR up_to_date_as_of unavailable; cross-check authority is unknown.",
        )

    def resolve_crosscheck_sections(
        self,
        acquisition: EcfrCrosscheckAcquisition | None = None,
        *,
        path: PathLike | None = None,
        sections: Sequence[str] | None = None,
    ) -> dict[str, EcfrSectionRecord]:
        acq = acquisition if acquisition is not None else self.acquire_from_fixture(path)
        wanted = list(sections) if sections is not None else list(DEFAULT_CROSSCHECK_SECTIONS)
        return {s: acq.resolve_section(s) for s in wanted}

    def get_acquisition(self, version_id: str) -> EcfrCrosscheckAcquisition:
        try:
            return self._acquisitions[version_id]
        except KeyError as exc:
            raise EcfrCrosscheckError(
                f"no acquisition for version_id {version_id!r}"
            ) from exc


# ---------------------------------------------------------------------------
# Fixture generators
# ---------------------------------------------------------------------------


def build_ecfr_current_fixture_recipe(
    *,
    up_to_date_as_of: str = "2024-07-01",
    fixture_id: str = "ecfr-title37-current-2024-07-01",
) -> dict[str, Any]:
    """Build a compact current Title 37 eCFR fixture recipe."""

    as_of = date.fromisoformat(up_to_date_as_of)
    reject_hard_coded_latest(up_to_date_as_of, field_name="up_to_date_as_of")
    version_id = version_identity(title="37", up_to_date_as_of=as_of)
    package_sha = content_sha256(f"ecfr|current|{version_id}|title-37")
    structure_url = ecfr_title_structure_url(title="37", date_as_of=as_of)
    full_xml_url = ecfr_full_xml_url(title="37", date_as_of=as_of)

    headings = {
        "1.56": "Duty to disclose information material to patentability",
        "1.97": "Filing of information disclosure statement",
        "1.98": "Content of information disclosure statement",
        "41.50": "Decisions and other actions by the Board",
        "42.100": "Procedure; pendency",
    }
    excerpts = {
        "1.56": (
            "(a) A patent by its very nature is affected with a public interest. "
            "The public interest is best served, and the most effective patent "
            "examination occurs when, at the time an application is being examined, "
            "the Office is aware of and evaluates the teachings of all information "
            "material to patentability..."
        ),
        "1.97": (
            "(a) In order for an applicant for a patent or for a reissue of a patent "
            "to have an information disclosure statement in a nonprovisional patent "
            "application..."
        ),
    }
    amendments = {
        "1.56": {
            "amendatory_action": "revised",
            "authority_citation": "35 U.S.C. 2(b)(2)",
            "source_citation": "57 FR 2034, Jan. 17, 1992",
            "effective_date": "1992-03-16",
            "publication_date": "1992-01-17",
            "fr_citation": "57 FR 2034",
        },
        "42.100": {
            "amendatory_action": "added",
            "authority_citation": "35 U.S.C. 316",
            "source_citation": "77 FR 48680, Aug. 14, 2012",
            "effective_date": "2012-09-16",
            "publication_date": "2012-08-14",
            "fr_citation": "77 FR 48680",
        },
    }

    sections: list[dict[str, Any]] = []
    for sec in DEFAULT_CROSSCHECK_SECTIONS:
        part = sec.split(".", 1)[0]
        seed = f"{version_id}|37|{sec}|xml"
        sections.append(
            {
                "title": "37",
                "part": part,
                "section": sec,
                "heading": headings.get(sec, f"37 CFR {sec}"),
                "citation": f"37 CFR {sec}",
                "text_excerpt": excerpts.get(sec, f"[excerpt 37 CFR {sec}]"),
                "content_sha256": content_sha256(seed),
                "source_url": ecfr_section_presentation_url(title="37", section=sec),
                "media_type": "application/xml",
                "up_to_date_as_of": as_of.isoformat(),
                "version_id": version_id,
                "content_kind": "section",
                "amendment": amendments.get(sec),
            }
        )

    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "fixture_id": fixture_id,
        "title": "37",
        "presentation_label": "unofficial presentation",
        "notes": (
            "Compact current Title 37 eCFR recipe. Labeled unofficial presentation; "
            "up_to_date_as_of and amendment/effective metadata retained. Official "
            "annual CFR identity lives in cfr_annual fixtures, not here."
        ),
        "version": {
            "provider": PROVIDER_ECFR,
            "title": "37",
            "up_to_date_as_of": as_of.isoformat(),
            "version_id": version_id,
            "content_sha256": package_sha,
            "source_url": structure_url,
            "structure_url": structure_url,
            "full_xml_url": full_xml_url,
            "versions_url": ecfr_versions_url(title="37"),
            "retrieved_at": "2024-07-15T12:00:00Z",
            "is_current_snapshot": True,
        },
        "packages": {
            "structure": {
                "content_kind": "structure",
                "content_sha256": content_sha256(f"structure|{version_id}"),
                "source_url": structure_url,
                "media_type": "application/json",
                "byte_size": 4096,
                "version_id": version_id,
                "up_to_date_as_of": as_of.isoformat(),
            },
            "full_xml": {
                "content_kind": "full_xml",
                "content_sha256": package_sha,
                "source_url": full_xml_url,
                "media_type": "application/xml",
                "byte_size": 2_500_000,
                "version_id": version_id,
                "up_to_date_as_of": as_of.isoformat(),
            },
            "version_history": {
                "content_kind": "version_history",
                "content_sha256": content_sha256(f"versions|{version_id}"),
                "source_url": ecfr_versions_url(title="37"),
                "media_type": "application/json",
                "byte_size": 8192,
                "version_id": version_id,
                "up_to_date_as_of": as_of.isoformat(),
            },
        },
        "version_history": [
            "2023-07-01",
            "2024-01-01",
            as_of.isoformat(),
        ],
        "sections": sections,
        "failures": [],
    }


def build_ecfr_historical_fixture_recipe(
    *,
    up_to_date_as_of: str = "2020-01-01",
    fixture_id: str = "ecfr-title37-historical-2020-01-01",
) -> dict[str, Any]:
    """Build a compact historical Title 37 eCFR fixture recipe (as-of date)."""

    as_of = date.fromisoformat(up_to_date_as_of)
    reject_hard_coded_latest(up_to_date_as_of, field_name="up_to_date_as_of")
    version_id = version_identity(title="37", up_to_date_as_of=as_of)
    package_sha = content_sha256(f"ecfr|historical|{version_id}|title-37")
    structure_url = ecfr_title_structure_url(title="37", date_as_of=as_of)
    full_xml_url = ecfr_full_xml_url(title="37", date_as_of=as_of)

    # Historical snapshot includes a subset of sections that existed as of date.
    sections_spec = (
        ("1.56", "Duty to disclose information material to patentability"),
        ("1.97", "Filing of information disclosure statement"),
        ("1.98", "Content of information disclosure statement"),
        ("41.50", "Decisions and other actions by the Board"),
    )
    sections: list[dict[str, Any]] = []
    for sec, heading in sections_spec:
        part = sec.split(".", 1)[0]
        seed = f"{version_id}|37|{sec}|xml"
        sections.append(
            {
                "title": "37",
                "part": part,
                "section": sec,
                "heading": heading,
                "citation": f"37 CFR {sec}",
                "text_excerpt": f"[historical excerpt 37 CFR {sec} as of {as_of.isoformat()}]",
                "content_sha256": content_sha256(seed),
                "source_url": ecfr_section_presentation_url(title="37", section=sec),
                "media_type": "application/xml",
                "up_to_date_as_of": as_of.isoformat(),
                "version_id": version_id,
                "content_kind": "section",
                "amendment": {
                    "amendatory_action": "in force",
                    "effective_date": "1992-03-16" if sec.startswith("1.") else "2004-09-13",
                    "notes": f"Historical text as of {as_of.isoformat()}",
                },
            }
        )

    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "fixture_id": fixture_id,
        "title": "37",
        "presentation_label": "unofficial presentation",
        "notes": (
            "Compact historical Title 37 eCFR as-of recipe. Current eCFR text is "
            "not used to judge a historical event without as-of reconstruction."
        ),
        "version": {
            "provider": PROVIDER_ECFR,
            "title": "37",
            "up_to_date_as_of": as_of.isoformat(),
            "version_id": version_id,
            "content_sha256": package_sha,
            "source_url": structure_url,
            "structure_url": structure_url,
            "full_xml_url": full_xml_url,
            "versions_url": ecfr_versions_url(title="37"),
            "retrieved_at": "2024-07-15T12:05:00Z",
            "is_current_snapshot": False,
        },
        "packages": {
            "structure": {
                "content_kind": "structure",
                "content_sha256": content_sha256(f"structure|{version_id}"),
                "source_url": structure_url,
                "media_type": "application/json",
                "byte_size": 3500,
                "version_id": version_id,
                "up_to_date_as_of": as_of.isoformat(),
            },
            "full_xml": {
                "content_kind": "full_xml",
                "content_sha256": package_sha,
                "source_url": full_xml_url,
                "media_type": "application/xml",
                "byte_size": 2_100_000,
                "version_id": version_id,
                "up_to_date_as_of": as_of.isoformat(),
            },
        },
        "version_history": [
            "2018-07-01",
            "2019-07-01",
            as_of.isoformat(),
        ],
        "sections": sections,
        "failures": [],
    }


def build_ecfr_failure_fixture_recipe(
    *,
    kind: FailureKind | str = FailureKind.RATE_LIMIT_429,
    fixture_id: str | None = None,
) -> dict[str, Any]:
    """Build a compact fixture that records a typed transport/schema failure."""

    failure_kind = FailureKind.coerce(kind)
    fid = fixture_id or f"ecfr-failure-{failure_kind.value}"
    messages = {
        FailureKind.PAGINATION: "eCFR pagination cycle detected for token 'page-3'",
        FailureKind.RETRY_EXHAUSTED: "eCFR retries exhausted after 5 attempts",
        FailureKind.RATE_LIMIT_429: "eCFR rate limit (HTTP 429)",
        FailureKind.SCHEMA: "eCFR API response missing required keys: ['meta']",
        FailureKind.OTHER: "eCFR transport failure",
    }
    failure: dict[str, Any] = {
        "kind": failure_kind.value,
        "message": messages.get(failure_kind, "eCFR failure"),
        "endpoint": f"{ECFR_API_BASE}/structure/2024-07-01/title-37.json",
    }
    if failure_kind is FailureKind.RATE_LIMIT_429:
        failure["response_status"] = 429
        failure["retry_after"] = 30.0
        failure["attempts"] = 3
    elif failure_kind is FailureKind.RETRY_EXHAUSTED:
        failure["response_status"] = 503
        failure["attempts"] = 5
    elif failure_kind is FailureKind.PAGINATION:
        failure["page"] = 3
        failure["response_status"] = 200
    elif failure_kind is FailureKind.SCHEMA:
        failure["response_status"] = 200

    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "fixture_id": fid,
        "title": "37",
        "presentation_label": "unofficial presentation",
        "notes": f"Typed failure fixture for {failure_kind.value}.",
        "version": {
            "provider": PROVIDER_ECFR,
            "title": "37",
            "up_to_date_as_of": "2024-07-01",
            "version_id": "ecfr-title-37-as-of-2024-07-01",
            "content_sha256": content_sha256(f"failure|{failure_kind.value}"),
            "source_url": ecfr_title_structure_url(title="37", date_as_of="2024-07-01"),
            "is_current_snapshot": True,
        },
        "sections": [],
        "packages": {},
        "version_history": ["2024-07-01"],
        "failures": [failure],
    }


def write_default_fixtures(directory: PathLike | None = None) -> Path:
    """Materialize current, historical, and typed-failure eCFR fixtures."""

    root = Path(directory) if directory is not None else default_fixture_dir()
    root.mkdir(parents=True, exist_ok=True)

    current = build_ecfr_current_fixture_recipe()
    (root / "ecfr_current_recipe.json").write_text(
        json.dumps(current, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    historical = build_ecfr_historical_fixture_recipe()
    (root / "ecfr_historical_recipe.json").write_text(
        json.dumps(historical, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    for kind in (
        FailureKind.PAGINATION,
        FailureKind.RETRY_EXHAUSTED,
        FailureKind.RATE_LIMIT_429,
        FailureKind.SCHEMA,
    ):
        failure = build_ecfr_failure_fixture_recipe(kind=kind)
        (root / f"ecfr_failure_{kind.value}.json").write_text(
            json.dumps(failure, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    missing = {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "fixture_id": "ecfr-title37-missing-version",
        "title": "37",
        "presentation_label": "unofficial presentation",
        "notes": "Version identity deliberately omitted for unknown-status tests.",
        "version": {
            "provider": PROVIDER_ECFR,
            "title": "37",
            "up_to_date_as_of": None,
        },
        "sections": [],
        "packages": {},
        "failures": [],
    }
    (root / "ecfr_missing_version.json").write_text(
        json.dumps(missing, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Title 37 CFR fixtures (eCFR + annual)\n\n"
            "Compact recipes for PATLAW-012.\n\n"
            "* `ecfr_current_recipe.json` / `ecfr_historical_recipe.json` — eCFR "
            "unofficial presentation (cross-check only).\n"
            "* `cfr_annual_recipe.json` — official GovInfo annual CFR package "
            "identity (separate from eCFR).\n"
            "* `ecfr_failure_*.json` — typed pagination / retry / 429 / schema failures.\n"
            "Prefer generators over bulk golden dumps.\n",
            encoding="utf-8",
        )
    return root


__all__ = [
    "COLLECTION_ECFR",
    "DEFAULT_CROSSCHECK_SECTIONS",
    "DEFAULT_TITLE",
    "DUTY_OF_DISCLOSURE_SECTION",
    "ECFR_API_BASE",
    "FIXTURE_SCHEMA_VERSION",
    "PATENT_PARTS",
    "PROVIDER_ECFR",
    "SCHEMA_VERSION",
    "AmendmentMeta",
    "EcfrContentKind",
    "EcfrCrosscheckAcquisition",
    "EcfrCrosscheckError",
    "EcfrCrosscheckProcessor",
    "EcfrPackageMeta",
    "EcfrPaginationError",
    "EcfrRateLimitError",
    "EcfrRetryExhaustedError",
    "EcfrSchemaError",
    "EcfrSectionRecord",
    "EcfrVersionPoint",
    "FailureKind",
    "FixtureSchemaError",
    "MissingVersionDateError",
    "ResolutionStatus",
    "SectionNotFoundError",
    "TypedFailure",
    "build_ecfr_current_fixture_recipe",
    "build_ecfr_failure_fixture_recipe",
    "build_ecfr_historical_fixture_recipe",
    "content_sha256",
    "default_fixture_dir",
    "ecfr_full_xml_url",
    "ecfr_section_presentation_url",
    "ecfr_title_structure_url",
    "ecfr_versions_url",
    "load_json_fixture",
    "normalize_part_token",
    "normalize_section_token",
    "normalize_title",
    "stable_section_identity",
    "version_identity",
    "write_default_fixtures",
]
