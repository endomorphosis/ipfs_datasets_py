"""Official annual Title 37 CFR acquisition via GovInfo (PATLAW-012).

Acquires official annual Code of Federal Regulations packages for Title 37
(Patents, Trademarks, and Copyrights) from GovInfo, preserving package /
granule metadata, content hashes, and official artifact identity.

Design invariants:

* Every admitted record carries ``authority_tier=official-base`` and artifact
  role :attr:`IdentityRole.OFFICIAL_ARTIFACT`.
* Official annual identity is **never** conflated with eCFR unofficial
  presentation (see :mod:`ecfr_crosscheck_processor`). Dual identity, when
  attached, keeps official and derived presentation fields separate.
* Edition identity is never the hard-coded token ``"latest"``; connectors
  record concrete year / package identifiers (e.g. ``CFR-2024-title37``).
* Pagination, retry exhaustion, HTTP 429 rate-limit, and schema failures are
  **typed** exceptions.
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
from typing import Any, Iterable, Mapping, Optional, Sequence, Union

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

# Re-export shared CFR identity helpers so tests can import from either module.
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.ecfr_crosscheck_processor import (
    DEFAULT_CROSSCHECK_SECTIONS,
    FailureKind,
    TypedFailure,
    EcfrPaginationError,
    EcfrRateLimitError,
    EcfrRetryExhaustedError,
    EcfrSchemaError,
    normalize_part_token,
    normalize_section_token,
    normalize_title,
    stable_section_identity,
)

SCHEMA_VERSION = "cfr-annual-processor-v1"
FIXTURE_SCHEMA_VERSION = "cfr-annual-fixture-v1"

DEFAULT_TITLE = "37"
DEFAULT_JURISDICTION = "US"
COLLECTION_CFR = "CFR"
PROVIDER_GOVINFO = "govinfo"

GOVINFO_API_BASE = "https://api.govinfo.gov"
GOVINFO_CONTENT_BASE = "https://www.govinfo.gov/content/pkg"
GOVINFO_CFR_COLLECTION = "CFR"

# Title 37 annual volumes commonly published by GPO (parts coverage varies by year).
DEFAULT_VOLUMES = ("1",)  # Title 37 is typically a single volume

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_YEAR_RE = re.compile(r"^\d{4}$")
_PACKAGE_ID_RE = re.compile(
    r"^CFR-(?P<year>\d{4})-title(?P<title>\d+[A-Za-z]?)$",
    re.IGNORECASE,
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CfrAnnualError(ValueError):
    """Base error for official annual CFR acquisition failures."""


class MissingPackageError(CfrAnnualError):
    """Raised when annual package identity cannot be established."""


class FixtureSchemaError(CfrAnnualError):
    """Raised when a fixture package is malformed."""


class SectionNotFoundError(CfrAnnualError):
    """Raised when a requested section is not present in the acquisition."""


class CfrPaginationError(CfrAnnualError):
    """Raised when GovInfo pagination is incomplete, cyclic, or out of bounds."""


class CfrRetryExhaustedError(CfrAnnualError):
    """Raised when bounded retry/backoff is exhausted without success."""


class CfrRateLimitError(CfrAnnualError):
    """Raised on HTTP 429 / rate-limit responses after policy handling."""

    def __init__(
        self,
        message: str = "GovInfo CFR rate limit (HTTP 429)",
        *,
        retry_after: Optional[float] = None,
        response_status: int = 429,
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.response_status = response_status


class CfrSchemaError(CfrAnnualError):
    """Raised when a GovInfo API response or fixture fails schema validation."""


class ResolutionStatus(str, Enum):
    """Outcome of annual CFR acquisition or section resolution."""

    RESOLVED = "resolved"
    UNKNOWN = "unknown"
    PARTIAL = "partial"
    ERROR = "error"


class SourceFormat(str, Enum):
    """Supported annual CFR packaging formats."""

    XML = "xml"
    PDF = "pdf"
    HTML = "html"
    MODS = "mods"
    PREMIS = "premis"
    ZIP = "zip"
    TEXT = "text"

    @classmethod
    def coerce(cls, value: Any) -> "SourceFormat":
        if isinstance(value, SourceFormat):
            return value
        text = str(value or "").strip().lower()
        aliases = {
            "xml": cls.XML,
            "application/xml": cls.XML,
            "text/xml": cls.XML,
            "pdf": cls.PDF,
            "application/pdf": cls.PDF,
            "html": cls.HTML,
            "htm": cls.HTML,
            "text/html": cls.HTML,
            "mods": cls.MODS,
            "application/mods+xml": cls.MODS,
            "premis": cls.PREMIS,
            "zip": cls.ZIP,
            "application/zip": cls.ZIP,
            "text": cls.TEXT,
            "txt": cls.TEXT,
            "text/plain": cls.TEXT,
        }
        if text not in aliases:
            raise CfrAnnualError(f"unsupported source format: {value!r}")
        return aliases[text]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CfrAnnualError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise CfrAnnualError(f"{name} must not contain NUL")
    return value.strip()


def _optional_str(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, "value")


def _require_sha256(value: Any, name: str = "sha256") -> str:
    text = _require_non_empty_str(value, name).lower()
    if not _SHA256_RE.fullmatch(text):
        raise CfrAnnualError(f"{name} must be a lowercase 64-char hex SHA-256")
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
            raise CfrAnnualError(f"{name} must be ISO-8601 datetime") from exc
    else:
        raise CfrAnnualError(f"{name} must be a datetime or ISO-8601 string")
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
        reject_hard_coded_latest(value.strip(), field_name="date")
        return date.fromisoformat(value.strip()[:10])
    raise CfrAnnualError(f"invalid date value: {value!r}")


def _date_to_str(value: Optional[date]) -> Optional[str]:
    return None if value is None else value.isoformat()


def _deep_sorted(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _deep_sorted(value[k]) for k in sorted(value.keys(), key=lambda x: str(x))}
    if isinstance(value, (list, tuple)):
        return [_deep_sorted(v) for v in value]
    return value


def content_sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def normalize_year(year: Any) -> str:
    """Normalize an annual edition year; reject hard-coded ``latest``."""

    if year is None:
        raise MissingPackageError("year is required")
    text = str(year).strip()
    reject_hard_coded_latest(text, field_name="year")
    if not _YEAR_RE.fullmatch(text):
        raise MissingPackageError(f"year must be a 4-digit calendar year, got {year!r}")
    return text


def govinfo_cfr_package_id(*, year: Any, title: Any = DEFAULT_TITLE) -> str:
    """Return GovInfo package id for an annual CFR title (e.g. ``CFR-2024-title37``)."""

    y = normalize_year(year)
    t = normalize_title(title)
    return f"CFR-{y}-title{t}"


def parse_govinfo_cfr_package_id(value: Any) -> tuple[str, str, str]:
    """Parse ``CFR-YYYY-titleNN`` into ``(package_id, year, title)``."""

    text = _require_non_empty_str(value, "package_id")
    reject_hard_coded_latest(text, field_name="package_id")
    match = _PACKAGE_ID_RE.fullmatch(text)
    if not match:
        raise MissingPackageError(
            f"package_id must look like CFR-YYYY-titleNN, got {value!r}"
        )
    year = match.group("year")
    title = normalize_title(match.group("title"))
    return f"CFR-{year}-title{title}", year, title


def govinfo_package_content_url(
    *,
    package_id: str,
    format_kind: SourceFormat | str = SourceFormat.XML,
) -> str:
    """Build a GovInfo content URL for an annual CFR package."""

    pid = _require_non_empty_str(package_id, "package_id")
    reject_hard_coded_latest(pid, field_name="package_id")
    fmt = SourceFormat.coerce(format_kind)
    if fmt is SourceFormat.ZIP:
        return f"{GOVINFO_CONTENT_BASE}/{pid}/zip/{pid}.zip"
    if fmt is SourceFormat.PDF:
        return f"{GOVINFO_CONTENT_BASE}/{pid}/pdf/{pid}.pdf"
    if fmt is SourceFormat.HTML:
        return f"{GOVINFO_CONTENT_BASE}/{pid}/html/{pid}.htm"
    if fmt is SourceFormat.MODS:
        return f"{GOVINFO_CONTENT_BASE}/{pid}/mods.xml"
    if fmt is SourceFormat.PREMIS:
        return f"{GOVINFO_CONTENT_BASE}/{pid}/premis.xml"
    # Default XML package root
    return f"{GOVINFO_CONTENT_BASE}/{pid}/xml/{pid}.xml"


def govinfo_granule_url(
    *,
    package_id: str,
    granule_id: str,
    format_kind: SourceFormat | str = SourceFormat.XML,
) -> str:
    """Build a GovInfo granule content URL."""

    pid = _require_non_empty_str(package_id, "package_id")
    gid = _require_non_empty_str(granule_id, "granule_id")
    fmt = SourceFormat.coerce(format_kind)
    ext = {
        SourceFormat.XML: "xml",
        SourceFormat.PDF: "pdf",
        SourceFormat.HTML: "htm",
        SourceFormat.TEXT: "txt",
    }.get(fmt, "xml")
    return f"{GOVINFO_CONTENT_BASE}/{pid}/{fmt.value}/{gid}.{ext}"


def _media_type_for_format(fmt: SourceFormat) -> str:
    return {
        SourceFormat.XML: "application/xml",
        SourceFormat.PDF: "application/pdf",
        SourceFormat.HTML: "text/html",
        SourceFormat.MODS: "application/mods+xml",
        SourceFormat.PREMIS: "application/xml",
        SourceFormat.ZIP: "application/zip",
        SourceFormat.TEXT: "text/plain",
    }[fmt]


# ---------------------------------------------------------------------------
# Domain records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FormatArtifact:
    """One format-specific official annual CFR artifact."""

    format: SourceFormat
    media_type: str
    artifact_sha256: str
    source_url: str
    byte_size: Optional[int] = None
    upstream_package_id: Optional[str] = None
    granule_id: Optional[str] = None
    role: IdentityRole = IdentityRole.OFFICIAL_ARTIFACT

    def __post_init__(self) -> None:
        if not isinstance(self.format, SourceFormat):
            object.__setattr__(self, "format", SourceFormat.coerce(self.format))
        object.__setattr__(
            self, "media_type", _require_non_empty_str(self.media_type, "media_type")
        )
        object.__setattr__(
            self, "artifact_sha256", _require_sha256(self.artifact_sha256, "artifact_sha256")
        )
        object.__setattr__(
            self, "source_url", _require_non_empty_str(self.source_url, "source_url")
        )
        if self.byte_size is not None and (
            not isinstance(self.byte_size, int) or self.byte_size < 0
        ):
            raise CfrAnnualError("byte_size must be a non-negative int")
        if self.upstream_package_id is not None:
            cleaned = _require_non_empty_str(self.upstream_package_id, "upstream_package_id")
            reject_hard_coded_latest(cleaned, field_name="upstream_package_id")
            object.__setattr__(self, "upstream_package_id", cleaned)
        if self.granule_id is not None:
            object.__setattr__(
                self, "granule_id", _require_non_empty_str(self.granule_id, "granule_id")
            )
        if not isinstance(self.role, IdentityRole):
            object.__setattr__(self, "role", IdentityRole(str(self.role)))

    def to_artifact_identity(self, *, provider: str, source_id: str) -> ArtifactIdentity:
        return ArtifactIdentity(
            provider=provider,
            source_id=source_id,
            artifact_sha256=self.artifact_sha256,
            source_url=self.source_url,
            media_type=self.media_type,
            byte_size=self.byte_size,
            upstream_package_id=self.upstream_package_id,
            role=self.role,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_sha256": self.artifact_sha256,
            "byte_size": self.byte_size,
            "format": self.format.value,
            "granule_id": self.granule_id,
            "media_type": self.media_type,
            "role": self.role.value,
            "source_url": self.source_url,
            "upstream_package_id": self.upstream_package_id,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "FormatArtifact":
        if not isinstance(value, Mapping):
            raise CfrSchemaError("format artifact must be a mapping")
        role_raw = value.get("role", IdentityRole.OFFICIAL_ARTIFACT.value)
        role = role_raw if isinstance(role_raw, IdentityRole) else IdentityRole(str(role_raw))
        return cls(
            format=SourceFormat.coerce(value.get("format")),
            media_type=value.get("media_type") or _media_type_for_format(
                SourceFormat.coerce(value.get("format", "xml"))
            ),
            artifact_sha256=value["artifact_sha256"],
            source_url=value["source_url"],
            byte_size=value.get("byte_size"),
            upstream_package_id=value.get("upstream_package_id"),
            granule_id=value.get("granule_id"),
            role=role,
        )


@dataclass(frozen=True, slots=True)
class AnnualPackage:
    """Concrete official annual CFR package identity (never ``latest``)."""

    year: str
    title: str = DEFAULT_TITLE
    package_id: Optional[str] = None
    provider: str = PROVIDER_GOVINFO
    edition: Optional[str] = None
    volume: Optional[str] = None
    content_sha256: Optional[str] = None
    source_url: Optional[str] = None
    date_issued: Optional[date] = None
    retrieved_at: Optional[datetime] = None
    formats: Mapping[str, FormatArtifact] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        y = normalize_year(self.year)
        t = normalize_title(self.title)
        object.__setattr__(self, "year", y)
        object.__setattr__(self, "title", t)
        object.__setattr__(
            self, "provider", _require_non_empty_str(self.provider, "provider")
        )
        pid = self.package_id or govinfo_cfr_package_id(year=y, title=t)
        reject_hard_coded_latest(pid, field_name="package_id")
        # Normalize package id form.
        try:
            pid, _, _ = parse_govinfo_cfr_package_id(pid)
        except MissingPackageError:
            # Allow non-standard ids only if they do not contain "latest".
            pass
        object.__setattr__(self, "package_id", pid)
        edition = self.edition or f"annual-{y}"
        reject_hard_coded_latest(edition, field_name="edition")
        object.__setattr__(self, "edition", edition)
        if self.volume is not None:
            object.__setattr__(self, "volume", _require_non_empty_str(str(self.volume), "volume"))
        if self.content_sha256 is not None:
            object.__setattr__(
                self, "content_sha256", _require_sha256(self.content_sha256, "content_sha256")
            )
        if self.source_url is not None:
            object.__setattr__(
                self, "source_url", _require_non_empty_str(self.source_url, "source_url")
            )
        object.__setattr__(self, "date_issued", _parse_optional_date(self.date_issued))
        if self.retrieved_at is not None:
            object.__setattr__(self, "retrieved_at", _parse_utc(self.retrieved_at))
        fmts: dict[str, FormatArtifact] = {}
        for key, raw in dict(self.formats).items():
            art = raw if isinstance(raw, FormatArtifact) else FormatArtifact.from_dict(raw)
            fmts[str(key) if not isinstance(key, SourceFormat) else key.value] = art
        object.__setattr__(self, "formats", fmts)
        if not isinstance(self.metadata, Mapping):
            raise CfrAnnualError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def canonical_id(self) -> str:
        return self.package_id or govinfo_cfr_package_id(year=self.year, title=self.title)

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_sha256": self.content_sha256,
            "date_issued": _date_to_str(self.date_issued),
            "edition": self.edition,
            "formats": {k: v.to_dict() for k, v in sorted(self.formats.items())},
            "metadata": _deep_sorted(dict(self.metadata)),
            "package_id": self.package_id,
            "provider": self.provider,
            "retrieved_at": (
                None if self.retrieved_at is None else _format_utc(self.retrieved_at)
            ),
            "source_url": self.source_url,
            "title": self.title,
            "volume": self.volume,
            "year": self.year,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "AnnualPackage":
        if not isinstance(value, Mapping):
            raise CfrSchemaError("annual package must be a mapping")
        year = value.get("year")
        package_id = value.get("package_id") or value.get("govinfo_package_id")
        title = value.get("title", DEFAULT_TITLE)
        if year in (None, "") and package_id:
            _, year, title_from_pkg = parse_govinfo_cfr_package_id(package_id)
            title = value.get("title", title_from_pkg)
        if year in (None, "") and not package_id:
            raise MissingPackageError("year or package_id is required")
        if year in (None, ""):
            raise MissingPackageError("year is required")
        formats_raw = value.get("formats") or {}
        formats: dict[str, Any] = {}
        if isinstance(formats_raw, Mapping):
            formats = dict(formats_raw)
        return cls(
            year=str(year),
            title=title,  # type: ignore[arg-type]
            package_id=package_id,
            provider=value.get("provider", PROVIDER_GOVINFO),  # type: ignore[arg-type]
            edition=value.get("edition"),
            volume=value.get("volume"),
            content_sha256=value.get("content_sha256"),
            source_url=value.get("source_url"),
            date_issued=value.get("date_issued"),
            retrieved_at=value.get("retrieved_at"),
            formats=formats,
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class CfrSectionRecord:
    """One Title 37 section from an official annual CFR package."""

    title: str
    section: str
    stable_id: str
    part: Optional[str] = None
    heading: Optional[str] = None
    citation: Optional[str] = None
    text_excerpt: Optional[str] = None
    formats: Mapping[str, FormatArtifact] = field(default_factory=dict)
    package_id: Optional[str] = None
    year: Optional[str] = None
    status: ResolutionStatus = ResolutionStatus.RESOLVED
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", normalize_title(self.title))
        object.__setattr__(self, "section", normalize_section_token(self.section))
        expected = stable_section_identity(title=self.title, section=self.section)
        object.__setattr__(self, "stable_id", expected)
        if self.part is not None:
            object.__setattr__(self, "part", normalize_part_token(self.part))
        for name in ("heading", "citation", "text_excerpt", "package_id", "year"):
            raw = getattr(self, name)
            if raw is not None:
                object.__setattr__(self, name, _require_non_empty_str(str(raw), name))
        if self.year is not None:
            object.__setattr__(self, "year", normalize_year(self.year))
        if self.package_id is not None:
            reject_hard_coded_latest(self.package_id, field_name="package_id")
        fmts: dict[str, FormatArtifact] = {}
        for key, raw in dict(self.formats).items():
            art = raw if isinstance(raw, FormatArtifact) else FormatArtifact.from_dict(raw)
            # Force official role for annual artifacts.
            if art.role is not IdentityRole.OFFICIAL_ARTIFACT:
                art = FormatArtifact(
                    format=art.format,
                    media_type=art.media_type,
                    artifact_sha256=art.artifact_sha256,
                    source_url=art.source_url,
                    byte_size=art.byte_size,
                    upstream_package_id=art.upstream_package_id,
                    granule_id=art.granule_id,
                    role=IdentityRole.OFFICIAL_ARTIFACT,
                )
            fmts[str(key) if not isinstance(key, SourceFormat) else key.value] = art
        object.__setattr__(self, "formats", fmts)
        if not isinstance(self.status, ResolutionStatus):
            object.__setattr__(self, "status", ResolutionStatus(str(self.status)))
        if not isinstance(self.metadata, Mapping):
            raise CfrAnnualError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))
        if self.citation is None:
            object.__setattr__(self, "citation", f"{self.title} CFR {self.section}")

    def identity_for_all_formats(self) -> str:
        return self.stable_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation": self.citation,
            "formats": {k: v.to_dict() for k, v in sorted(self.formats.items())},
            "heading": self.heading,
            "metadata": _deep_sorted(dict(self.metadata)),
            "package_id": self.package_id,
            "part": self.part,
            "section": self.section,
            "stable_id": self.stable_id,
            "status": self.status.value,
            "text_excerpt": self.text_excerpt,
            "title": self.title,
            "year": self.year,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "CfrSectionRecord":
        if not isinstance(value, Mapping):
            raise CfrSchemaError("section record must be a mapping")
        title = normalize_title(value.get("title", DEFAULT_TITLE))
        section = normalize_section_token(value["section"])
        status_raw = value.get("status", ResolutionStatus.RESOLVED.value)
        status = (
            status_raw
            if isinstance(status_raw, ResolutionStatus)
            else ResolutionStatus(str(status_raw))
        )
        return cls(
            title=title,
            section=section,
            stable_id=value.get("stable_id")
            or stable_section_identity(title=title, section=section),
            part=value.get("part"),
            heading=value.get("heading"),
            citation=value.get("citation"),
            text_excerpt=value.get("text_excerpt"),
            formats=value.get("formats") or {},
            package_id=value.get("package_id"),
            year=value.get("year"),
            status=status,
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class CfrAnnualAcquisition:
    """Result of acquiring an official annual Title 37 CFR package."""

    status: ResolutionStatus
    package: Optional[AnnualPackage]
    sections: Mapping[str, CfrSectionRecord] = field(default_factory=dict)
    authority_source: Optional[AuthoritySourceRecord] = None
    receipt: Optional[SourceReceipt] = None
    title: str = DEFAULT_TITLE
    unknown_reason: Optional[str] = None
    notes: Optional[str] = None
    failures: tuple[TypedFailure, ...] = ()
    # Optional eCFR presentation identity kept separate when cross-linked.
    ecfr_presentation_sha256: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, ResolutionStatus):
            object.__setattr__(self, "status", ResolutionStatus(str(self.status)))
        object.__setattr__(self, "title", normalize_title(self.title))
        secs = {
            normalize_section_token(k): (
                v if isinstance(v, CfrSectionRecord) else CfrSectionRecord.from_dict(v)
            )
            for k, v in dict(self.sections).items()
        }
        object.__setattr__(self, "sections", secs)
        fails = tuple(
            f if isinstance(f, TypedFailure) else TypedFailure.from_dict(f)
            for f in self.failures
        )
        object.__setattr__(self, "failures", fails)
        if self.ecfr_presentation_sha256 is not None:
            object.__setattr__(
                self,
                "ecfr_presentation_sha256",
                _require_sha256(self.ecfr_presentation_sha256, "ecfr_presentation_sha256"),
            )
        if not isinstance(self.metadata, Mapping):
            raise CfrAnnualError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def is_unknown(self) -> bool:
        return self.status is ResolutionStatus.UNKNOWN

    def get_section(self, section: Any) -> CfrSectionRecord:
        key = normalize_section_token(section)
        try:
            return self.sections[key]
        except KeyError as exc:
            raise SectionNotFoundError(
                f"section {key!r} not present in annual CFR acquisition"
            ) from exc

    def resolve_section(self, section: Any) -> CfrSectionRecord:
        key = normalize_section_token(section)
        if key in self.sections:
            return self.sections[key]
        if self.is_unknown:
            return CfrSectionRecord(
                title=self.title,
                section=key,
                stable_id=stable_section_identity(title=self.title, section=key),
                status=ResolutionStatus.UNKNOWN,
                package_id=None if self.package is None else self.package.package_id,
                year=None if self.package is None else self.package.year,
                metadata={"unknown_reason": self.unknown_reason or "missing package data"},
            )
        raise SectionNotFoundError(
            f"section {key!r} not present in annual CFR acquisition"
        )

    def official_artifact_sha256(self) -> Optional[str]:
        if self.package is None:
            return None
        if self.package.content_sha256:
            return self.package.content_sha256
        if self.authority_source and self.authority_source.official_artifact:
            return self.authority_source.official_artifact.artifact_sha256
        return None

    def identities_remain_separate(self) -> bool:
        """True when official annual identity is not equal to eCFR presentation."""

        official = self.official_artifact_sha256()
        if official is None or self.ecfr_presentation_sha256 is None:
            # Separate when only one side is present, or both absent.
            return True
        return official != self.ecfr_presentation_sha256

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_source": (
                None if self.authority_source is None else self.authority_source.to_dict()
            ),
            "ecfr_presentation_sha256": self.ecfr_presentation_sha256,
            "failures": [f.to_dict() for f in self.failures],
            "metadata": _deep_sorted(dict(self.metadata)),
            "notes": self.notes,
            "package": None if self.package is None else self.package.to_dict(),
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "schema_version": SCHEMA_VERSION,
            "sections": {k: v.to_dict() for k, v in sorted(self.sections.items())},
            "status": self.status.value,
            "title": self.title,
            "unknown_reason": self.unknown_reason,
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


def _build_format_map(
    raw: Any,
    *,
    package: AnnualPackage,
    section: str,
) -> dict[str, FormatArtifact]:
    if not raw:
        return {}
    if not isinstance(raw, Mapping):
        raise FixtureSchemaError(f"formats for section {section!r} must be a mapping")
    out: dict[str, FormatArtifact] = {}
    for key, value in raw.items():
        if not isinstance(value, Mapping):
            raise FixtureSchemaError(f"formats[{key!r}] must be a mapping")
        fmt = SourceFormat.coerce(value.get("format") or key)
        art = FormatArtifact(
            format=fmt,
            media_type=value.get("media_type") or _media_type_for_format(fmt),
            artifact_sha256=value["artifact_sha256"],
            source_url=value.get("source_url")
            or govinfo_package_content_url(package_id=package.canonical_id, format_kind=fmt),
            byte_size=value.get("byte_size"),
            upstream_package_id=value.get("upstream_package_id") or package.package_id,
            granule_id=value.get("granule_id"),
            role=IdentityRole.OFFICIAL_ARTIFACT,
        )
        out[fmt.value] = art
    return out


def _build_receipt(package: AnnualPackage) -> Optional[SourceReceipt]:
    endpoint = package.source_url
    if not endpoint and package.package_id:
        endpoint = govinfo_package_content_url(
            package_id=package.package_id, format_kind=SourceFormat.XML
        )
    if not endpoint:
        return None
    return SourceReceipt(
        endpoint=endpoint,
        retrieved_at=package.retrieved_at or datetime.now(timezone.utc),
        response_status=200,
        sanitized_request={"method": "GET", "provider": PROVIDER_GOVINFO},
        upstream_id=package.package_id,
        content_sha256=package.content_sha256,
        media_type="application/xml",
        retry_count=0,
        metadata={
            "year": package.year,
            "collection": COLLECTION_CFR,
            "authority": "official-base",
        },
    )


def _build_authority_source(
    package: AnnualPackage,
    *,
    formats: Mapping[str, FormatArtifact],
    receipt: Optional[SourceReceipt],
    ecfr_presentation: Optional[ArtifactIdentity] = None,
) -> AuthoritySourceRecord:
    """Build official-base authority with separate optional eCFR presentation."""

    source_key = f"govinfo:cfr:{package.canonical_id}"
    official: Optional[ArtifactIdentity] = None
    for preferred in ("xml", "pdf", "zip"):
        art = formats.get(preferred) or package.formats.get(preferred)
        if art is not None:
            official = art.to_artifact_identity(
                provider=package.provider, source_id=source_key
            )
            break
    if official is None and package.content_sha256 and package.source_url:
        official = ArtifactIdentity(
            provider=package.provider,
            source_id=source_key,
            artifact_sha256=package.content_sha256,
            source_url=package.source_url,
            media_type="application/xml",
            role=IdentityRole.OFFICIAL_ARTIFACT,
            upstream_package_id=package.package_id,
        )
    if official is None:
        raise MissingPackageError(
            "official annual package requires an official artifact identity"
        )

    derived = None
    if ecfr_presentation is not None:
        derived = ArtifactIdentity(
            provider=ecfr_presentation.provider,
            source_id=ecfr_presentation.source_id,
            artifact_sha256=ecfr_presentation.artifact_sha256,
            source_url=ecfr_presentation.source_url,
            media_type=ecfr_presentation.media_type,
            byte_size=ecfr_presentation.byte_size,
            upstream_package_id=ecfr_presentation.upstream_package_id,
            role=IdentityRole.DERIVED_PRESENTATION,
        )
        # Guarantee separation of digests.
        if derived.artifact_sha256 == official.artifact_sha256:
            raise CfrAnnualError(
                "eCFR presentation identity must remain separate from official "
                "annual artifact identity (identical sha256)"
            )

    return AuthoritySourceRecord(
        source_key=source_key,
        authority_tier=AuthorityTier.OFFICIAL_BASE,
        collection=COLLECTION_CFR,
        jurisdiction=DEFAULT_JURISDICTION,
        title=package.title,
        citation=f"Title {package.title} C.F.R. ({package.year} annual edition)",
        edition=package.edition,
        version=package.year,
        release_point=package.package_id,
        date_issued=package.date_issued,
        publication_date=package.date_issued,
        official_artifact=official,
        derived_presentation=derived,
        receipt=receipt,
        verification_state=VerificationState.UNVERIFIED,
        notes=(
            "Official annual GovInfo CFR package. eCFR presentation identity, "
            "when present, is recorded separately and must not replace this artifact."
        ),
        metadata={
            "processor_schema": SCHEMA_VERSION,
            "authority_schema": AUTHORITY_SCHEMA_VERSION,
            "year": package.year,
            "volume": package.volume,
            "package_id": package.package_id,
        },
    )


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class CfrAnnualProcessor:
    """Acquire official annual Title 37 CFR packages from GovInfo fixtures.

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
        self._acquisitions: dict[str, CfrAnnualAcquisition] = {}

    def load_fixture_package(self, path: PathLike | None = None) -> dict[str, Any]:
        target = Path(path) if path is not None else self._default_package_path()
        if target.is_dir():
            recipe = target / "cfr_annual_recipe.json"
            if recipe.is_file():
                target = recipe
            else:
                raise FixtureSchemaError(
                    f"fixture directory {target} lacks cfr_annual_recipe.json"
                )
        payload = load_json_fixture(target)
        schema = payload.get("schema_version")
        if schema and schema not in {FIXTURE_SCHEMA_VERSION, SCHEMA_VERSION}:
            if not str(schema).startswith("cfr-annual"):
                raise FixtureSchemaError(
                    f"unsupported fixture schema_version {schema!r} in {target}"
                )
        return payload

    def _default_package_path(self) -> Path:
        recipe = self.fixture_dir / "cfr_annual_recipe.json"
        if recipe.is_file():
            return recipe
        return self.fixture_dir

    def acquire_from_fixture(
        self,
        path: PathLike | None = None,
        *,
        register: bool = True,
        raise_recorded_failures: bool = False,
    ) -> CfrAnnualAcquisition:
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
    ) -> CfrAnnualAcquisition:
        if not isinstance(payload, Mapping):
            raise FixtureSchemaError("payload must be a mapping")

        failures = tuple(
            TypedFailure.from_dict(item)
            for item in (payload.get("failures") or [])
            if isinstance(item, Mapping)
        )
        if raise_recorded_failures and failures:
            self._raise_typed_failure(failures[0])

        title = normalize_title(payload.get("title") or self.default_title)
        package_raw = (
            payload.get("package")
            or payload.get("annual_package")
            or payload.get("release")
        )

        if not package_raw:
            return CfrAnnualAcquisition(
                status=ResolutionStatus.UNKNOWN,
                package=None,
                sections={},
                title=title,
                unknown_reason="missing package data",
                notes="Official annual package identity unavailable.",
                failures=failures,
                metadata={"schema_version": payload.get("schema_version")},
            )

        if isinstance(package_raw, str):
            package_raw = {"package_id": package_raw, "provider": PROVIDER_GOVINFO}

        if not isinstance(package_raw, Mapping):
            raise FixtureSchemaError("package must be a mapping or package_id string")

        year_token = package_raw.get("year")
        package_id_token = package_raw.get("package_id") or package_raw.get(
            "govinfo_package_id"
        )
        if year_token in (None, "") and package_id_token in (None, ""):
            return CfrAnnualAcquisition(
                status=ResolutionStatus.UNKNOWN,
                package=None,
                sections={},
                title=title,
                unknown_reason="missing package data",
                notes="Package mapping present but no concrete year/package identity.",
                failures=failures,
                metadata={"schema_version": payload.get("schema_version")},
            )

        try:
            if year_token not in (None, ""):
                reject_hard_coded_latest(str(year_token), field_name="year")
            if package_id_token not in (None, ""):
                reject_hard_coded_latest(str(package_id_token), field_name="package_id")
            package = AnnualPackage.from_dict(
                {**dict(package_raw), "title": package_raw.get("title", title)}
            )
        except (MissingPackageError, HardCodedLatestEditionError, CfrAnnualError) as exc:
            return CfrAnnualAcquisition(
                status=ResolutionStatus.UNKNOWN,
                package=None,
                sections={},
                title=title,
                unknown_reason=str(exc),
                notes="Failed to parse annual package; treating authority as unknown.",
                failures=failures,
                metadata={
                    "schema_version": payload.get("schema_version"),
                    "error": str(exc),
                },
            )

        # Default source_url when omitted.
        if not package.source_url:
            package = AnnualPackage(
                year=package.year,
                title=package.title,
                package_id=package.package_id,
                provider=package.provider,
                edition=package.edition,
                volume=package.volume,
                content_sha256=package.content_sha256,
                source_url=govinfo_package_content_url(
                    package_id=package.canonical_id, format_kind=SourceFormat.XML
                ),
                date_issued=package.date_issued,
                retrieved_at=package.retrieved_at,
                formats=package.formats,
                metadata=package.metadata,
            )

        package_formats = _build_format_map(
            payload.get("package_formats") or package_raw.get("formats") or package.formats,
            package=package,
            section="*",
        )
        # Merge into package if package.formats empty.
        if not package.formats and package_formats:
            package = AnnualPackage(
                year=package.year,
                title=package.title,
                package_id=package.package_id,
                provider=package.provider,
                edition=package.edition,
                volume=package.volume,
                content_sha256=package.content_sha256
                or next(iter(package_formats.values())).artifact_sha256,
                source_url=package.source_url,
                date_issued=package.date_issued,
                retrieved_at=package.retrieved_at,
                formats=package_formats,
                metadata=package.metadata,
            )

        sections: dict[str, CfrSectionRecord] = {}
        for raw_sec in payload.get("sections") or []:
            if not isinstance(raw_sec, Mapping):
                continue
            sec_title = normalize_title(raw_sec.get("title", package.title))
            sec_num = normalize_section_token(raw_sec["section"])
            formats = _build_format_map(
                raw_sec.get("formats"),
                package=package,
                section=sec_num,
            )
            record = CfrSectionRecord(
                title=sec_title,
                section=sec_num,
                stable_id=stable_section_identity(title=sec_title, section=sec_num),
                part=raw_sec.get("part"),
                heading=raw_sec.get("heading"),
                citation=raw_sec.get("citation"),
                text_excerpt=raw_sec.get("text_excerpt"),
                formats=formats,
                package_id=package.package_id,
                year=package.year,
                status=ResolutionStatus.RESOLVED,
                metadata=raw_sec.get("metadata") or {},
            )
            sections[record.section] = record

        # Optional linked eCFR presentation identity (must remain separate).
        ecfr_sha = payload.get("ecfr_presentation_sha256")
        ecfr_identity: Optional[ArtifactIdentity] = None
        ecfr_raw = payload.get("ecfr_presentation") or payload.get("derived_presentation")
        if isinstance(ecfr_raw, Mapping):
            ecfr_identity = ArtifactIdentity.from_dict(
                {
                    **dict(ecfr_raw),
                    "role": IdentityRole.DERIVED_PRESENTATION.value,
                }
            )
            ecfr_sha = ecfr_identity.artifact_sha256
        elif ecfr_sha:
            # Minimal presentation identity for dual-identity separation tests.
            ecfr_identity = ArtifactIdentity(
                provider="ecfr",
                source_id=f"ecfr:title-{package.title}:linked",
                artifact_sha256=str(ecfr_sha).lower(),
                source_url=f"https://www.ecfr.gov/current/title-{package.title}",
                media_type="application/xml",
                role=IdentityRole.DERIVED_PRESENTATION,
            )

        receipt = _build_receipt(package)
        authority = _build_authority_source(
            package,
            formats=package_formats or package.formats,
            receipt=receipt,
            ecfr_presentation=ecfr_identity,
        )

        if register:
            self.registry.register(authority, overwrite=True)
            if receipt is not None and authority.receipt is None:
                self.registry.attach_receipt(authority.source_key, receipt)

        acquisition = CfrAnnualAcquisition(
            status=ResolutionStatus.RESOLVED,
            package=package,
            sections=sections,
            authority_source=authority,
            receipt=receipt,
            title=package.title,
            notes=payload.get("notes")
            or "Official annual GovInfo Title 37 CFR package.",
            failures=failures,
            ecfr_presentation_sha256=str(ecfr_sha).lower() if ecfr_sha else None,
            metadata={
                "schema_version": payload.get("schema_version") or FIXTURE_SCHEMA_VERSION,
                "fixture_id": payload.get("fixture_id"),
                "section_count": len(sections),
                "package_id": package.package_id,
                "year": package.year,
            },
        )
        self._acquisitions[package.canonical_id] = acquisition
        return acquisition

    def _raise_typed_failure(self, failure: TypedFailure) -> None:
        kind = failure.kind
        if kind is FailureKind.PAGINATION:
            raise CfrPaginationError(failure.message)
        if kind is FailureKind.RETRY_EXHAUSTED:
            raise CfrRetryExhaustedError(failure.message)
        if kind is FailureKind.RATE_LIMIT_429:
            raise CfrRateLimitError(
                failure.message,
                retry_after=failure.retry_after,
                response_status=failure.response_status or 429,
            )
        if kind is FailureKind.SCHEMA:
            raise CfrSchemaError(failure.message)
        raise CfrAnnualError(failure.message)

    def raise_typed_failure(self, failure: TypedFailure | JsonMapping | FailureKind) -> None:
        if isinstance(failure, FailureKind):
            self._raise_typed_failure(
                TypedFailure(kind=failure, message=f"simulated {failure.value} failure")
            )
        if isinstance(failure, TypedFailure):
            self._raise_typed_failure(failure)
        if isinstance(failure, Mapping):
            self._raise_typed_failure(TypedFailure.from_dict(failure))
        raise CfrAnnualError(f"unsupported failure descriptor: {failure!r}")

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
        limit = max_attempts if max_attempts is not None else self.retry_cache_policy.max_attempts
        if response_status == 429:
            return TypedFailure(
                kind=FailureKind.RATE_LIMIT_429,
                message=message or "GovInfo CFR rate limit (HTTP 429)",
                response_status=429,
                retry_after=retry_after,
                attempts=attempts,
                endpoint=endpoint,
            )
        if page is not None and page < 0:
            return TypedFailure(
                kind=FailureKind.PAGINATION,
                message=message or f"invalid GovInfo page index {page}",
                response_status=response_status,
                page=page,
                endpoint=endpoint,
            )
        if attempts is not None and attempts >= limit:
            return TypedFailure(
                kind=FailureKind.RETRY_EXHAUSTED,
                message=message
                or f"GovInfo CFR retries exhausted after {attempts} attempts (limit {limit})",
                response_status=response_status,
                attempts=attempts,
                endpoint=endpoint,
            )
        return TypedFailure(
            kind=FailureKind.OTHER,
            message=message or f"GovInfo CFR HTTP {response_status}",
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
        if page < 1:
            raise CfrPaginationError(f"page must be >= 1, got {page}")
        if page_size < 1:
            raise CfrPaginationError(f"page_size must be >= 1, got {page_size}")
        if total_items is not None:
            if total_items < 0:
                raise CfrPaginationError(f"total_items must be >= 0, got {total_items}")
            max_page = max(1, (total_items + page_size - 1) // page_size) if total_items else 1
            if page > max_page:
                raise CfrPaginationError(
                    f"page {page} exceeds max page {max_page} for total_items={total_items}"
                )
        if next_page_token and seen_tokens is not None:
            if next_page_token in set(seen_tokens):
                raise CfrPaginationError(
                    f"pagination cycle detected for token {next_page_token!r}"
                )

    def validate_api_schema(
        self, payload: Any, *, required_keys: Sequence[str]
    ) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise CfrSchemaError("GovInfo API response must be a mapping")
        missing = [k for k in required_keys if k not in payload]
        if missing:
            raise CfrSchemaError(
                f"GovInfo API response missing required keys: {missing}"
            )
        return dict(payload)

    def acquire_unknown(
        self, *, reason: str = "missing package data", title: Any | None = None
    ) -> CfrAnnualAcquisition:
        return CfrAnnualAcquisition(
            status=ResolutionStatus.UNKNOWN,
            package=None,
            sections={},
            title=self.default_title if title is None else normalize_title(title),
            unknown_reason=reason,
            notes="Official annual package identity unavailable.",
        )

    def resolve_patent_sections(
        self,
        acquisition: CfrAnnualAcquisition | None = None,
        *,
        path: PathLike | None = None,
        sections: Sequence[str] | None = None,
    ) -> dict[str, CfrSectionRecord]:
        acq = acquisition if acquisition is not None else self.acquire_from_fixture(path)
        wanted = list(sections) if sections is not None else list(DEFAULT_CROSSCHECK_SECTIONS)
        return {s: acq.resolve_section(s) for s in wanted}

    def get_acquisition(self, package_id: str) -> CfrAnnualAcquisition:
        try:
            return self._acquisitions[package_id]
        except KeyError as exc:
            raise CfrAnnualError(f"no acquisition for package_id {package_id!r}") from exc


# ---------------------------------------------------------------------------
# Fixture generators
# ---------------------------------------------------------------------------


def build_cfr_annual_fixture_recipe(
    *,
    year: str = "2024",
    fixture_id: str = "cfr-annual-2024-title37",
    include_ecfr_presentation: bool = True,
) -> dict[str, Any]:
    """Build a compact official annual Title 37 CFR fixture recipe."""

    y = normalize_year(year)
    package_id = govinfo_cfr_package_id(year=y, title="37")
    package_sha = content_sha256(f"govinfo|annual|{package_id}|xml")
    source_url = govinfo_package_content_url(package_id=package_id, format_kind=SourceFormat.XML)

    headings = {
        "1.56": "Duty to disclose information material to patentability",
        "1.97": "Filing of information disclosure statement",
        "1.98": "Content of information disclosure statement",
        "41.50": "Decisions and other actions by the Board",
        "42.100": "Procedure; pendency",
    }

    sections: list[dict[str, Any]] = []
    for sec in DEFAULT_CROSSCHECK_SECTIONS:
        part = sec.split(".", 1)[0]
        formats = {}
        for fmt in (SourceFormat.XML, SourceFormat.PDF):
            seed = f"{package_id}|37|{sec}|{fmt.value}"
            granule_id = f"{package_id}-part{part}-sec{sec.replace('.', '-')}"
            formats[fmt.value] = {
                "format": fmt.value,
                "media_type": _media_type_for_format(fmt),
                "artifact_sha256": content_sha256(seed),
                "source_url": govinfo_granule_url(
                    package_id=package_id, granule_id=granule_id, format_kind=fmt
                ),
                "byte_size": 2000 + len(sec) * 10 + (50 if fmt is SourceFormat.PDF else 0),
                "upstream_package_id": package_id,
                "granule_id": granule_id,
                "role": IdentityRole.OFFICIAL_ARTIFACT.value,
            }
        sections.append(
            {
                "title": "37",
                "part": part,
                "section": sec,
                "heading": headings.get(sec, f"37 CFR {sec}"),
                "citation": f"37 CFR {sec}",
                "text_excerpt": f"[official annual excerpt 37 CFR {sec}, {y} edition]",
                "formats": formats,
            }
        )

    recipe: dict[str, Any] = {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "fixture_id": fixture_id,
        "title": "37",
        "notes": (
            "Compact official annual Title 37 GovInfo CFR recipe. Official "
            "artifact identity is separate from any eCFR presentation identity."
        ),
        "package": {
            "provider": PROVIDER_GOVINFO,
            "year": y,
            "title": "37",
            "package_id": package_id,
            "edition": f"annual-{y}",
            "volume": "1",
            "content_sha256": package_sha,
            "source_url": source_url,
            "date_issued": f"{y}-07-01",
            "retrieved_at": "2024-09-01T10:00:00Z",
            "formats": {
                "xml": {
                    "format": "xml",
                    "media_type": "application/xml",
                    "artifact_sha256": package_sha,
                    "source_url": source_url,
                    "upstream_package_id": package_id,
                    "byte_size": 3_000_000,
                    "role": IdentityRole.OFFICIAL_ARTIFACT.value,
                },
                "pdf": {
                    "format": "pdf",
                    "media_type": "application/pdf",
                    "artifact_sha256": content_sha256(f"{package_id}|pdf"),
                    "source_url": govinfo_package_content_url(
                        package_id=package_id, format_kind=SourceFormat.PDF
                    ),
                    "upstream_package_id": package_id,
                    "byte_size": 4_500_000,
                    "role": IdentityRole.OFFICIAL_ARTIFACT.value,
                },
                "mods": {
                    "format": "mods",
                    "media_type": "application/mods+xml",
                    "artifact_sha256": content_sha256(f"{package_id}|mods"),
                    "source_url": govinfo_package_content_url(
                        package_id=package_id, format_kind=SourceFormat.MODS
                    ),
                    "upstream_package_id": package_id,
                    "role": IdentityRole.OFFICIAL_ARTIFACT.value,
                },
            },
        },
        "sections": sections,
        "failures": [],
    }

    if include_ecfr_presentation:
        # Deliberately different digest from package_sha so identities stay separate.
        ecfr_sha = content_sha256(f"ecfr|presentation|linked|{package_id}")
        assert ecfr_sha != package_sha
        recipe["ecfr_presentation_sha256"] = ecfr_sha
        recipe["ecfr_presentation"] = {
            "provider": "ecfr",
            "source_id": f"ecfr:title-37:as-of-{y}-07-01",
            "artifact_sha256": ecfr_sha,
            "source_url": "https://www.ecfr.gov/api/versioner/v1/full/"
            f"{y}-07-01/title-37.xml",
            "media_type": "application/xml",
            "role": IdentityRole.DERIVED_PRESENTATION.value,
            "upstream_package_id": f"ecfr-title-37-as-of-{y}-07-01",
        }

    return recipe


def build_cfr_annual_missing_package_recipe() -> dict[str, Any]:
    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "fixture_id": "cfr-annual-missing-package",
        "title": "37",
        "notes": "Package identity deliberately omitted for unknown-status tests.",
        "package": {
            "provider": PROVIDER_GOVINFO,
            "title": "37",
            "year": None,
            "package_id": None,
        },
        "sections": [],
        "failures": [],
    }


def write_default_fixtures(directory: PathLike | None = None) -> Path:
    """Materialize official annual CFR fixtures alongside eCFR recipes."""

    root = Path(directory) if directory is not None else default_fixture_dir()
    root.mkdir(parents=True, exist_ok=True)

    recipe = build_cfr_annual_fixture_recipe()
    (root / "cfr_annual_recipe.json").write_text(
        json.dumps(recipe, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    missing = build_cfr_annual_missing_package_recipe()
    (root / "cfr_annual_missing_package.json").write_text(
        json.dumps(missing, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Also ensure eCFR fixtures exist in the same directory tree.
    from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.ecfr_crosscheck_processor import (
        write_default_fixtures as write_ecfr_fixtures,
    )

    write_ecfr_fixtures(root)
    return root


__all__ = [
    "COLLECTION_CFR",
    "DEFAULT_TITLE",
    "DEFAULT_VOLUMES",
    "FIXTURE_SCHEMA_VERSION",
    "GOVINFO_CONTENT_BASE",
    "PROVIDER_GOVINFO",
    "SCHEMA_VERSION",
    "AnnualPackage",
    "CfrAnnualAcquisition",
    "CfrAnnualError",
    "CfrAnnualProcessor",
    "CfrPaginationError",
    "CfrRateLimitError",
    "CfrRetryExhaustedError",
    "CfrSchemaError",
    "CfrSectionRecord",
    "FailureKind",
    "FixtureSchemaError",
    "FormatArtifact",
    "MissingPackageError",
    "ResolutionStatus",
    "SectionNotFoundError",
    "SourceFormat",
    "TypedFailure",
    "build_cfr_annual_fixture_recipe",
    "build_cfr_annual_missing_package_recipe",
    "content_sha256",
    "default_fixture_dir",
    "govinfo_cfr_package_id",
    "govinfo_granule_url",
    "govinfo_package_content_url",
    "load_json_fixture",
    "normalize_section_token",
    "normalize_title",
    "normalize_year",
    "parse_govinfo_cfr_package_id",
    "stable_section_identity",
    "write_default_fixtures",
]
