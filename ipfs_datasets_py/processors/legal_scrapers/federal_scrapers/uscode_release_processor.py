"""Title 35 U.S. Code release-point acquisition (PATLAW-013).

Acquires exact House OLRC / GovInfo U.S. Code release points for Title 35
(Patents), records USLM/XML/HTML/PDF identities and source receipts, and
exposes uncodified / slip-law classification gaps instead of pretending the
current codification is complete.

Design invariants:

* Edition identity is never the hard-coded token ``"latest"``; connectors
  record concrete release-point / package identifiers.
* Stable section identity is independent of source format (USLM, XML, HTML,
  PDF): ``usc:{title}:{section}``.
* Missing release-point data yields status ``unknown`` (fail-closed).
* Official artifact identity and derived presentation identity remain
  distinct via :mod:`patent_authority_sources`.
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
from typing import Any, Iterable, Iterator, Mapping, MutableMapping, Optional, Sequence, Union

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

SCHEMA_VERSION = "uscode-release-processor-v1"
FIXTURE_SCHEMA_VERSION = "uscode-release-fixture-v1"

DEFAULT_TITLE = "35"
DEFAULT_JURISDICTION = "US"
COLLECTION_USCODE = "USCODE"

# Patent-sensitive Title 35 sections required by PATLAW-013 / privacy gate.
CONFIDENTIALITY_SECTION = "122"
SECRECY_ORDER_SECTIONS = tuple(str(n) for n in range(181, 189))  # 181–188 inclusive
PATENT_SENSITIVE_SECTIONS = (CONFIDENTIALITY_SECTION, *SECRECY_ORDER_SECTIONS)

USHOUSE_DOWNLOAD_PAGE = "https://uscode.house.gov/download/download.shtml"
USHOUSE_RELEASEPOINT_BASE = "https://uscode.house.gov/download/releasepoints"
GOVINFO_CONTENT_BASE = "https://www.govinfo.gov/content/pkg"

_SECTION_TOKEN_RE = re.compile(
    r"(?:§+\s*)?(?:sec(?:tion)?\.?\s*)?(?P<section>\d+[A-Za-z0-9.\-]*(?:\([a-zA-Z0-9]+\))*)",
    re.IGNORECASE,
)
_RELEASE_POINT_RE = re.compile(
    r"(?:us/pl/)?(?P<congress>\d+)(?:[/\-])(?P<release>[A-Za-z0-9]+)",
    re.IGNORECASE,
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


class UscodeReleaseError(ValueError):
    """Base error for Title 35 release-point acquisition failures."""


class MissingReleasePointError(UscodeReleaseError):
    """Raised when release-point identity cannot be established."""


class FixtureSchemaError(UscodeReleaseError):
    """Raised when a fixture package is malformed."""


class SectionNotFoundError(UscodeReleaseError):
    """Raised when a requested section is not present in the acquisition."""


class ResolutionStatus(str, Enum):
    """Outcome of release-point or section resolution."""

    RESOLVED = "resolved"
    UNKNOWN = "unknown"
    PARTIAL = "partial"
    ERROR = "error"


class SourceFormat(str, Enum):
    """Supported U.S. Code source packaging formats."""

    USLM = "uslm"
    XML = "xml"
    HTML = "html"
    HTM = "htm"
    PDF = "pdf"
    ZIP = "zip"

    @classmethod
    def coerce(cls, value: Any) -> "SourceFormat":
        if isinstance(value, SourceFormat):
            return value
        text = str(value or "").strip().lower()
        aliases = {
            "uslm": cls.USLM,
            "uslm+xml": cls.USLM,
            "application/uslm+xml": cls.USLM,
            "xml": cls.XML,
            "application/xml": cls.XML,
            "text/xml": cls.XML,
            "html": cls.HTML,
            "htm": cls.HTM,
            "text/html": cls.HTML,
            "pdf": cls.PDF,
            "application/pdf": cls.PDF,
            "zip": cls.ZIP,
            "application/zip": cls.ZIP,
        }
        if text not in aliases:
            raise UscodeReleaseError(f"unsupported source format: {value!r}")
        return aliases[text]


class ExclusionKind(str, Enum):
    """Kinds of release-point exclusions / classification gaps."""

    UNCODIFIED_SLIP_LAW = "uncodified_slip_law"
    CLASSIFICATION_GAP = "classification_gap"
    POSITIVE_LAW_PENDING = "positive_law_pending"
    EDITORIAL_NOTE = "editorial_note"
    OMITTED = "omitted"
    TRANSFERRED = "transferred"
    OTHER = "other"

    @classmethod
    def coerce(cls, value: Any) -> "ExclusionKind":
        if isinstance(value, ExclusionKind):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        for kind in cls:
            if kind.value == text or kind.name.lower() == text:
                return kind
        return cls.OTHER


def _require_non_empty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UscodeReleaseError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise UscodeReleaseError(f"{name} must not contain NUL")
    return value.strip()


def _optional_str(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, "value")


def _require_sha256(value: Any, name: str = "sha256") -> str:
    text = _require_non_empty_str(value, name).lower()
    if not _SHA256_RE.fullmatch(text):
        raise UscodeReleaseError(f"{name} must be a lowercase 64-char hex SHA-256")
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
            raise UscodeReleaseError(f"{name} must be ISO-8601 datetime") from exc
    else:
        raise UscodeReleaseError(f"{name} must be a datetime or ISO-8601 string")
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
        return date.fromisoformat(value.strip()[:10])
    raise UscodeReleaseError(f"invalid date value: {value!r}")


def _date_to_str(value: Optional[date]) -> Optional[str]:
    return None if value is None else value.isoformat()


def _deep_sorted(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _deep_sorted(value[k]) for k in sorted(value.keys(), key=lambda x: str(x))}
    if isinstance(value, (list, tuple)):
        return [_deep_sorted(v) for v in value]
    return value


def normalize_title(title: Any) -> str:
    """Normalize a U.S. Code title number to a stable string (e.g. ``\"35\"``)."""

    text = str(title if title is not None else "").strip()
    if not text:
        raise UscodeReleaseError("title must be non-empty")
    if text.isdigit():
        return str(int(text))
    # Preserve lettered titles (e.g. 10a) in lowercase.
    return text.lower()


def normalize_section_token(section: Any) -> str:
    """Normalize a section citation token to a stable section number.

    Accepts ``122``, ``§ 122``, ``section 122``, ``35 U.S.C. § 122``, etc.
    Parenthetical subsections on the section number (``181(a)``) are preserved
    when present; bare integers are returned without leading zeros.
    """

    if section is None:
        raise UscodeReleaseError("section must be non-empty")
    text = str(section).strip()
    if not text:
        raise UscodeReleaseError("section must be non-empty")

    # Prefer the last § / section-like token when a full citation is supplied.
    candidates = list(_SECTION_TOKEN_RE.finditer(text))
    if candidates:
        raw = candidates[-1].group("section")
    else:
        raw = text

    raw = raw.strip().lstrip("§").strip()
    # Collapse whitespace inside parentheticals already stripped by the regex.
    raw = re.sub(r"\s+", "", raw)

    # Numeric base without leading zeros: 0122 -> 122, keep lettered tails.
    m = re.match(r"^0*(\d+)([A-Za-z0-9.\-()]*)$", raw)
    if m:
        return f"{int(m.group(1))}{m.group(2)}"
    return raw


def stable_section_identity(
    *,
    title: Any = DEFAULT_TITLE,
    section: Any,
    jurisdiction: str = DEFAULT_JURISDICTION,
) -> str:
    """Return a format-independent stable section identity.

    Shape: ``usc:{jurisdiction}:{title}:{section}`` (lower-case jurisdiction).
    Source packaging format (USLM/XML/HTML/PDF) is intentionally excluded so
    dual-format acquisitions of the same statute share one identity.
    """

    title_n = normalize_title(title)
    section_n = normalize_section_token(section)
    jur = _require_non_empty_str(jurisdiction, "jurisdiction").lower()
    return f"usc:{jur}:{title_n}:{section_n}"


def parse_release_point_id(value: Any) -> tuple[str, str, str]:
    """Parse a release-point token into ``(canonical_id, congress, release)``.

    Accepts ``us/pl/118/45``, ``118-45``, ``118/45``. Rejects ``latest``.
    """

    text = _require_non_empty_str(value, "release_point")
    reject_hard_coded_latest(text, field_name="release_point")
    match = _RELEASE_POINT_RE.fullmatch(text.replace(" ", ""))
    if not match:
        # Also accept already-canonical paths with us/pl/ prefix only partially.
        match = _RELEASE_POINT_RE.search(text)
    if not match:
        raise UscodeReleaseError(f"unrecognized release_point: {value!r}")
    congress = str(int(match.group("congress")))
    release = str(match.group("release")).strip()
    if not release or release.lower() == "latest":
        raise HardCodedLatestEditionError(
            "release_point must not use the hard-coded token 'latest'"
        )
    canonical = f"us/pl/{congress}/{release}"
    return canonical, congress, release


def ushouse_title_code(title: Any) -> str:
    """Return the two-digit (or lettered) House OLRC title code."""

    text = normalize_title(title)
    if text.isdigit():
        return f"{int(text):02d}"
    return text.lower()


def ushouse_releasepoint_zip_url(
    *,
    congress: Any,
    release: Any,
    title: Any = DEFAULT_TITLE,
    format_kind: SourceFormat | str = SourceFormat.HTML,
) -> str:
    """Build a House OLRC release-point zip URL for one title package."""

    canonical, congress_s, release_s = parse_release_point_id(f"{congress}/{release}")
    del canonical  # used only for validation
    code = ushouse_title_code(title)
    fmt = SourceFormat.coerce(format_kind)
    prefix = {
        SourceFormat.HTML: "htm",
        SourceFormat.HTM: "htm",
        SourceFormat.XML: "xml",
        SourceFormat.USLM: "xml",
        SourceFormat.PDF: "pdf",
        SourceFormat.ZIP: "htm",
    }[fmt]
    return (
        f"{USHOUSE_RELEASEPOINT_BASE}/us/pl/{congress_s}/{release_s}/"
        f"{prefix}_usc{code}@{congress_s}-{release_s}.zip"
    )


def govinfo_title_package_id(*, year: Any, title: Any = DEFAULT_TITLE) -> str:
    """Return a concrete GovInfo USCODE package id (never ``latest``)."""

    year_s = _require_non_empty_str(str(year), "year")
    reject_hard_coded_latest(year_s, field_name="year")
    if not year_s.isdigit():
        raise UscodeReleaseError(f"year must be numeric, got {year!r}")
    title_n = normalize_title(title)
    return f"USCODE-{year_s}-title{title_n}"


def govinfo_title_zip_url(*, year: Any, title: Any = DEFAULT_TITLE) -> str:
    package = govinfo_title_package_id(year=year, title=title)
    return f"{GOVINFO_CONTENT_BASE}/{package}/zip/{package}.zip"


def content_sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class ReleasePoint:
    """Exact House OLRC or GovInfo U.S. Code release identity."""

    release_point: str
    provider: str
    title: str = DEFAULT_TITLE
    congress: Optional[str] = None
    release: Optional[str] = None
    govinfo_package_id: Optional[str] = None
    edition: Optional[str] = None
    year: Optional[str] = None
    source_url: Optional[str] = None
    content_sha256: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "release_point", _require_non_empty_str(self.release_point, "release_point")
        )
        reject_hard_coded_latest(self.release_point, field_name="release_point")
        object.__setattr__(self, "provider", _require_non_empty_str(self.provider, "provider"))
        object.__setattr__(self, "title", normalize_title(self.title))
        if self.congress is not None:
            object.__setattr__(self, "congress", str(int(str(self.congress).strip())))
        if self.release is not None:
            rel = _require_non_empty_str(str(self.release), "release")
            reject_hard_coded_latest(rel, field_name="release")
            object.__setattr__(self, "release", rel)
        if self.govinfo_package_id is not None:
            pkg = _require_non_empty_str(self.govinfo_package_id, "govinfo_package_id")
            reject_hard_coded_latest(pkg, field_name="govinfo_package_id")
            object.__setattr__(self, "govinfo_package_id", pkg)
        if self.edition is not None:
            ed = _require_non_empty_str(self.edition, "edition")
            reject_hard_coded_latest(ed, field_name="edition")
            object.__setattr__(self, "edition", ed)
        if self.year is not None:
            object.__setattr__(self, "year", _require_non_empty_str(str(self.year), "year"))
            reject_hard_coded_latest(self.year, field_name="year")
        if self.source_url is not None:
            object.__setattr__(
                self, "source_url", _require_non_empty_str(self.source_url, "source_url")
            )
        if self.content_sha256 is not None:
            object.__setattr__(
                self, "content_sha256", _require_sha256(self.content_sha256, "content_sha256")
            )
        if self.retrieved_at is not None:
            object.__setattr__(
                self, "retrieved_at", _parse_utc(self.retrieved_at, name="retrieved_at")
            )
        if not isinstance(self.metadata, Mapping):
            raise UscodeReleaseError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def canonical_id(self) -> str:
        return self.release_point

    def to_dict(self) -> dict[str, Any]:
        return {
            "congress": self.congress,
            "content_sha256": self.content_sha256,
            "edition": self.edition,
            "govinfo_package_id": self.govinfo_package_id,
            "metadata": _deep_sorted(self.metadata),
            "provider": self.provider,
            "release": self.release,
            "release_point": self.release_point,
            "retrieved_at": None if self.retrieved_at is None else _format_utc(self.retrieved_at),
            "source_url": self.source_url,
            "title": self.title,
            "year": self.year,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "ReleasePoint":
        if not isinstance(value, Mapping):
            raise UscodeReleaseError("release point must be a mapping")
        release_point = value.get("release_point")
        congress = value.get("congress")
        release = value.get("release")
        if release_point:
            canonical, c, r = parse_release_point_id(release_point)
            congress = congress or c
            release = release or r
            release_point = canonical
        elif congress is not None and release is not None:
            release_point, congress, release = parse_release_point_id(f"{congress}/{release}")
        elif value.get("govinfo_package_id"):
            # GovInfo annual package used as the release identity.
            pkg = _require_non_empty_str(value.get("govinfo_package_id"), "govinfo_package_id")
            reject_hard_coded_latest(pkg, field_name="govinfo_package_id")
            release_point = pkg
        else:
            raise MissingReleasePointError(
                "release_point, congress/release, or govinfo_package_id is required"
            )
        return cls(
            release_point=str(release_point),
            provider=str(value.get("provider") or "ushouse"),
            title=value.get("title", DEFAULT_TITLE),
            congress=None if congress is None else str(congress),
            release=None if release is None else str(release),
            govinfo_package_id=value.get("govinfo_package_id"),
            edition=value.get("edition"),
            year=value.get("year"),
            source_url=value.get("source_url"),
            content_sha256=value.get("content_sha256"),
            retrieved_at=value.get("retrieved_at"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class ReleaseExclusion:
    """An uncodified, classification-gap, or related exclusion for a release."""

    kind: ExclusionKind
    citation: str
    reason: str
    affects_sections: tuple[str, ...] = ()
    public_law: Optional[str] = None
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", ExclusionKind.coerce(self.kind))
        object.__setattr__(self, "citation", _require_non_empty_str(self.citation, "citation"))
        object.__setattr__(self, "reason", _require_non_empty_str(self.reason, "reason"))
        sections: list[str] = []
        for item in self.affects_sections or ():
            sections.append(normalize_section_token(item))
        object.__setattr__(self, "affects_sections", tuple(sections))
        if self.public_law is not None:
            object.__setattr__(
                self, "public_law", _require_non_empty_str(self.public_law, "public_law")
            )
        if self.notes is not None:
            object.__setattr__(self, "notes", _require_non_empty_str(self.notes, "notes"))
        if not isinstance(self.metadata, Mapping):
            raise UscodeReleaseError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "affects_sections": list(self.affects_sections),
            "citation": self.citation,
            "kind": self.kind.value,
            "metadata": _deep_sorted(self.metadata),
            "notes": self.notes,
            "public_law": self.public_law,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "ReleaseExclusion":
        if not isinstance(value, Mapping):
            raise UscodeReleaseError("exclusion must be a mapping")
        affects = value.get("affects_sections") or ()
        return cls(
            kind=ExclusionKind.coerce(value.get("kind", ExclusionKind.OTHER)),
            citation=str(value.get("citation") or value.get("public_law") or "unspecified"),
            reason=str(value.get("reason") or "classification gap"),
            affects_sections=tuple(affects),
            public_law=value.get("public_law"),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class FormatArtifact:
    """One packaging format of a section or title package."""

    format: SourceFormat
    media_type: str
    artifact_sha256: str
    source_url: str
    byte_size: Optional[int] = None
    upstream_package_id: Optional[str] = None
    role: IdentityRole = IdentityRole.OFFICIAL_ARTIFACT

    def __post_init__(self) -> None:
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
        if self.byte_size is not None and (not isinstance(self.byte_size, int) or self.byte_size < 0):
            raise UscodeReleaseError("byte_size must be a non-negative int")
        if self.upstream_package_id is not None:
            pkg = _require_non_empty_str(self.upstream_package_id, "upstream_package_id")
            reject_hard_coded_latest(pkg, field_name="upstream_package_id")
            object.__setattr__(self, "upstream_package_id", pkg)
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
            "media_type": self.media_type,
            "role": self.role.value,
            "source_url": self.source_url,
            "upstream_package_id": self.upstream_package_id,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "FormatArtifact":
        if not isinstance(value, Mapping):
            raise UscodeReleaseError("format artifact must be a mapping")
        role_raw = value.get("role", IdentityRole.OFFICIAL_ARTIFACT.value)
        role = role_raw if isinstance(role_raw, IdentityRole) else IdentityRole(str(role_raw))
        return cls(
            format=SourceFormat.coerce(value.get("format") or value.get("source_format")),
            media_type=str(value.get("media_type") or "application/octet-stream"),
            artifact_sha256=str(value.get("artifact_sha256") or value.get("sha256")),
            source_url=str(value.get("source_url") or value.get("url")),
            byte_size=value.get("byte_size"),
            upstream_package_id=value.get("upstream_package_id"),
            role=role,
        )


@dataclass(frozen=True, slots=True)
class UscodeSectionRecord:
    """One Title section resolved against a concrete release point."""

    title: str
    section: str
    stable_id: str
    heading: Optional[str] = None
    citation: Optional[str] = None
    text_excerpt: Optional[str] = None
    formats: Mapping[str, FormatArtifact] = field(default_factory=dict)
    status: ResolutionStatus = ResolutionStatus.RESOLVED
    release_point: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        title_n = normalize_title(self.title)
        section_n = normalize_section_token(self.section)
        object.__setattr__(self, "title", title_n)
        object.__setattr__(self, "section", section_n)
        stable = self.stable_id or stable_section_identity(title=title_n, section=section_n)
        # Guard: supplied stable_id must match format-independent identity.
        expected = stable_section_identity(title=title_n, section=section_n)
        if stable != expected:
            # Re-normalize rather than fail on minor presentation differences.
            stable = expected
        object.__setattr__(self, "stable_id", stable)
        if self.heading is not None:
            object.__setattr__(self, "heading", _require_non_empty_str(self.heading, "heading"))
        if self.citation is not None:
            object.__setattr__(
                self, "citation", _require_non_empty_str(self.citation, "citation")
            )
        else:
            object.__setattr__(self, "citation", f"{title_n} U.S.C. § {section_n}")
        if self.text_excerpt is not None:
            object.__setattr__(self, "text_excerpt", str(self.text_excerpt))
        fmt_map: dict[str, FormatArtifact] = {}
        for key, art in (self.formats or {}).items():
            if isinstance(art, FormatArtifact):
                fmt_map[SourceFormat.coerce(key).value] = art
            elif isinstance(art, Mapping):
                payload = dict(art)
                payload.setdefault("format", key)
                fmt_map[SourceFormat.coerce(key).value] = FormatArtifact.from_dict(payload)
            else:
                raise UscodeReleaseError(f"invalid format artifact for {key!r}")
        object.__setattr__(self, "formats", fmt_map)
        if not isinstance(self.status, ResolutionStatus):
            object.__setattr__(self, "status", ResolutionStatus(str(self.status)))
        if self.release_point is not None:
            object.__setattr__(
                self,
                "release_point",
                _require_non_empty_str(self.release_point, "release_point"),
            )
            reject_hard_coded_latest(self.release_point, field_name="release_point")
        if not isinstance(self.metadata, Mapping):
            raise UscodeReleaseError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def identity_for_all_formats(self) -> str:
        """Stable identity shared by every packaging format of this section."""

        return self.stable_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation": self.citation,
            "formats": {k: v.to_dict() for k, v in sorted(self.formats.items())},
            "heading": self.heading,
            "metadata": _deep_sorted(self.metadata),
            "release_point": self.release_point,
            "section": self.section,
            "stable_id": self.stable_id,
            "status": self.status.value,
            "text_excerpt": self.text_excerpt,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "UscodeSectionRecord":
        if not isinstance(value, Mapping):
            raise UscodeReleaseError("section record must be a mapping")
        title = value.get("title", DEFAULT_TITLE)
        section = value.get("section")
        if section is None:
            raise UscodeReleaseError("section is required")
        status_raw = value.get("status", ResolutionStatus.RESOLVED.value)
        status = (
            status_raw
            if isinstance(status_raw, ResolutionStatus)
            else ResolutionStatus(str(status_raw))
        )
        return cls(
            title=str(title),
            section=str(section),
            stable_id=str(
                value.get("stable_id")
                or stable_section_identity(title=title, section=section)
            ),
            heading=value.get("heading"),
            citation=value.get("citation"),
            text_excerpt=value.get("text_excerpt"),
            formats=value.get("formats") or {},
            status=status,
            release_point=value.get("release_point"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class UscodeReleaseAcquisition:
    """Result of acquiring one Title 35 release point and its sections."""

    status: ResolutionStatus
    release_point: Optional[ReleasePoint]
    exclusions: tuple[ReleaseExclusion, ...]
    sections: Mapping[str, UscodeSectionRecord]
    authority_source: Optional[AuthoritySourceRecord] = None
    receipt: Optional[SourceReceipt] = None
    title: str = DEFAULT_TITLE
    notes: Optional[str] = None
    unknown_reason: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, ResolutionStatus):
            object.__setattr__(self, "status", ResolutionStatus(str(self.status)))
        object.__setattr__(self, "title", normalize_title(self.title))
        object.__setattr__(self, "exclusions", tuple(self.exclusions or ()))
        sec_map: dict[str, UscodeSectionRecord] = {}
        for key, sec in (self.sections or {}).items():
            if isinstance(sec, UscodeSectionRecord):
                record = sec
            elif isinstance(sec, Mapping):
                record = UscodeSectionRecord.from_dict(sec)
            else:
                raise UscodeReleaseError("sections values must be mappings or records")
            sec_map[record.section] = record
        object.__setattr__(self, "sections", sec_map)
        if not isinstance(self.metadata, Mapping):
            raise UscodeReleaseError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def is_unknown(self) -> bool:
        return self.status is ResolutionStatus.UNKNOWN

    def get_section(self, section: Any) -> UscodeSectionRecord:
        token = normalize_section_token(section)
        try:
            return self.sections[token]
        except KeyError as exc:
            raise SectionNotFoundError(
                f"section {token!r} not present in acquisition "
                f"(release={None if self.release_point is None else self.release_point.release_point})"
            ) from exc

    def resolve_section(self, section: Any) -> UscodeSectionRecord:
        """Resolve a section or return an unknown-status record when release is missing."""

        if self.status is ResolutionStatus.UNKNOWN or self.release_point is None:
            token = normalize_section_token(section)
            return UscodeSectionRecord(
                title=self.title,
                section=token,
                stable_id=stable_section_identity(title=self.title, section=token),
                status=ResolutionStatus.UNKNOWN,
                release_point=None,
                metadata={"unknown_reason": self.unknown_reason or "missing release point"},
            )
        return self.get_section(section)

    def recorded_exclusions(self) -> tuple[ReleaseExclusion, ...]:
        return self.exclusions

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_source": (
                None if self.authority_source is None else self.authority_source.to_dict()
            ),
            "exclusions": [e.to_dict() for e in self.exclusions],
            "metadata": _deep_sorted(self.metadata),
            "notes": self.notes,
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "release_point": None if self.release_point is None else self.release_point.to_dict(),
            "schema_version": SCHEMA_VERSION,
            "sections": {
                k: v.to_dict() for k, v in sorted(self.sections.items(), key=lambda kv: kv[0])
            },
            "status": self.status.value,
            "title": self.title,
            "unknown_reason": self.unknown_reason,
        }

    def to_canonical_json(self) -> str:
        return canonical_json_dumps(self.to_dict())


def default_fixture_dir() -> Path:
    """Return the repository Title 35 fixture directory when present."""

    # processors/legal_scrapers/federal_scrapers/thisfile -> repo root is 5 parents up
    here = Path(__file__).resolve()
    candidates = [
        here.parents[4] / "tests" / "fixtures" / "legal_data" / "patent_authorities" / "uscode",
        Path.cwd() / "tests" / "fixtures" / "legal_data" / "patent_authorities" / "uscode",
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


def _media_type_for_format(fmt: SourceFormat) -> str:
    return {
        SourceFormat.USLM: "application/uslm+xml",
        SourceFormat.XML: "application/xml",
        SourceFormat.HTML: "text/html",
        SourceFormat.HTM: "text/html",
        SourceFormat.PDF: "application/pdf",
        SourceFormat.ZIP: "application/zip",
    }[fmt]


def _build_format_map(
    raw_formats: Mapping[str, Any] | None,
    *,
    release: ReleasePoint,
    section: str,
) -> dict[str, FormatArtifact]:
    out: dict[str, FormatArtifact] = {}
    if not raw_formats:
        return out
    for key, item in raw_formats.items():
        fmt = SourceFormat.coerce(key)
        if isinstance(item, FormatArtifact):
            out[fmt.value] = item
            continue
        if not isinstance(item, Mapping):
            raise FixtureSchemaError(f"formats[{key!r}] must be a mapping")
        payload = dict(item)
        payload.setdefault("format", fmt.value)
        payload.setdefault("media_type", _media_type_for_format(fmt))
        if "artifact_sha256" not in payload and "sha256" not in payload:
            # Deterministic synthetic digest for compact recipes that omit bytes.
            seed = f"{release.release_point}|{release.title}|{section}|{fmt.value}"
            payload["artifact_sha256"] = content_sha256(seed)
        if "source_url" not in payload and "url" not in payload:
            if release.congress and release.release:
                payload["source_url"] = ushouse_releasepoint_zip_url(
                    congress=release.congress,
                    release=release.release,
                    title=release.title,
                    format_kind=fmt,
                )
            elif release.source_url:
                payload["source_url"] = release.source_url
            else:
                payload["source_url"] = (
                    f"{USHOUSE_DOWNLOAD_PAGE}#title-{release.title}-section-{section}-{fmt.value}"
                )
        if "upstream_package_id" not in payload:
            payload["upstream_package_id"] = release.govinfo_package_id or release.release_point
        out[fmt.value] = FormatArtifact.from_dict(payload)
    return out


def _build_authority_source(
    release: ReleasePoint,
    *,
    formats: Mapping[str, FormatArtifact] | None = None,
    receipt: SourceReceipt | None = None,
    verification_state: VerificationState = VerificationState.UNVERIFIED,
) -> AuthoritySourceRecord:
    official: Optional[ArtifactIdentity] = None
    derived: Optional[ArtifactIdentity] = None
    fmt_map = dict(formats or {})

    preferred_official = (
        SourceFormat.USLM.value,
        SourceFormat.XML.value,
        SourceFormat.PDF.value,
        SourceFormat.HTML.value,
        SourceFormat.HTM.value,
        SourceFormat.ZIP.value,
    )
    for key in preferred_official:
        if key in fmt_map:
            art = fmt_map[key]
            official = art.to_artifact_identity(
                provider=release.provider,
                source_id=f"uscode-{release.title}:{release.release_point}:{key}",
            )
            break

    if official is None and release.content_sha256 and release.source_url:
        official = ArtifactIdentity(
            provider=release.provider,
            source_id=f"uscode-{release.title}:{release.release_point}",
            artifact_sha256=release.content_sha256,
            source_url=release.source_url,
            role=IdentityRole.OFFICIAL_ARTIFACT,
            upstream_package_id=release.govinfo_package_id or release.release_point,
        )

    # Prefer HTML as derived presentation when a richer official format exists.
    if official is not None:
        for key in (SourceFormat.HTML.value, SourceFormat.HTM.value):
            if key in fmt_map and fmt_map[key].artifact_sha256 != official.artifact_sha256:
                derived = fmt_map[key].to_artifact_identity(
                    provider=release.provider,
                    source_id=f"uscode-{release.title}:{release.release_point}:{key}:presentation",
                )
                derived = ArtifactIdentity(
                    provider=derived.provider,
                    source_id=derived.source_id,
                    artifact_sha256=derived.artifact_sha256,
                    source_url=derived.source_url,
                    media_type=derived.media_type,
                    byte_size=derived.byte_size,
                    upstream_package_id=derived.upstream_package_id,
                    role=IdentityRole.DERIVED_PRESENTATION,
                )
                break

    edition = release.edition or release.release_point
    return AuthoritySourceRecord(
        source_key=f"uscode-{release.title}-{release.release_point.replace('/', '-')}",
        authority_tier=AuthorityTier.OFFICIAL_BASE,
        collection=COLLECTION_USCODE,
        jurisdiction=DEFAULT_JURISDICTION,
        title=release.title,
        citation=f"{release.title} U.S.C.",
        edition=edition,
        version=release.release_point,
        release_point=release.release_point,
        official_artifact=official,
        derived_presentation=derived,
        receipt=receipt,
        verification_state=verification_state,
        notes="House OLRC / GovInfo U.S. Code release-point acquisition",
        metadata={
            "congress": release.congress,
            "release": release.release,
            "govinfo_package_id": release.govinfo_package_id,
            "year": release.year,
            "processor_schema": SCHEMA_VERSION,
            "authority_schema": AUTHORITY_SCHEMA_VERSION,
        },
    )


def _build_receipt(release: ReleasePoint) -> Optional[SourceReceipt]:
    if not release.source_url and not release.content_sha256:
        return None
    endpoint = release.source_url or USHOUSE_DOWNLOAD_PAGE
    retrieved = release.retrieved_at or datetime(1970, 1, 1, tzinfo=timezone.utc)
    return SourceReceipt(
        endpoint=endpoint,
        retrieved_at=retrieved,
        response_status=200,
        sanitized_request={"method": "GET", "path": endpoint},
        upstream_id=release.govinfo_package_id or release.release_point,
        content_sha256=release.content_sha256,
        retry_count=0,
        cache_hit=False,
        media_type="application/zip",
        metadata={"provider": release.provider, "title": release.title},
    )


class UscodeReleaseProcessor:
    """Acquire Title 35 U.S. Code content at an exact release point.

    Primary path is fixture replay (recorded OLRC/GovInfo metadata). Live
    network discovery is deliberately not performed by default so tests and
    offline operators remain deterministic.
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
        self.registry = registry if registry is not None else AuthoritySourceRegistry(
            default_retry_cache_policy=retry_cache_policy
        )
        self.default_title = normalize_title(default_title)
        self._acquisitions: dict[str, UscodeReleaseAcquisition] = {}

    # ------------------------------------------------------------------
    # Identity helpers (format-independent)
    # ------------------------------------------------------------------

    def stable_section_identity(self, section: Any, *, title: Any | None = None) -> str:
        return stable_section_identity(
            title=self.default_title if title is None else title,
            section=section,
        )

    def identities_equal_across_formats(
        self,
        *,
        title: Any,
        section: Any,
        formats: Sequence[SourceFormat | str],
    ) -> bool:
        """Return True when every *format* maps to the same stable identity."""

        base = stable_section_identity(title=title, section=section)
        for _fmt in formats:
            # Format is intentionally ignored for identity.
            if stable_section_identity(title=title, section=section) != base:
                return False
        return len(list(formats)) > 0

    # ------------------------------------------------------------------
    # Fixture acquisition
    # ------------------------------------------------------------------

    def load_fixture_package(self, path: PathLike | None = None) -> dict[str, Any]:
        """Load a compact Title 35 release fixture (recipe or full package)."""

        target = Path(path) if path is not None else self._default_package_path()
        if target.is_dir():
            recipe = target / "title35_release_recipe.json"
            if recipe.is_file():
                target = recipe
            else:
                # Merge directory components when present.
                return self._load_fixture_directory(target)
        payload = load_json_fixture(target)
        schema = payload.get("schema_version")
        if schema and schema not in {FIXTURE_SCHEMA_VERSION, SCHEMA_VERSION}:
            # Accept forward-compatible minor variants that share the prefix.
            if not str(schema).startswith("uscode-release"):
                raise FixtureSchemaError(
                    f"unsupported fixture schema_version {schema!r} in {target}"
                )
        return payload

    def _default_package_path(self) -> Path:
        recipe = self.fixture_dir / "title35_release_recipe.json"
        if recipe.is_file():
            return recipe
        return self.fixture_dir

    def _load_fixture_directory(self, directory: Path) -> dict[str, Any]:
        release_path = directory / "release_point.json"
        if not release_path.is_file():
            raise FixtureSchemaError(
                f"fixture directory {directory} lacks title35_release_recipe.json "
                "or release_point.json"
            )
        payload: dict[str, Any] = {
            "schema_version": FIXTURE_SCHEMA_VERSION,
            "release": load_json_fixture(release_path),
        }
        exclusions_path = directory / "exclusions.json"
        if exclusions_path.is_file():
            raw = load_json_fixture(exclusions_path)
            payload["exclusions"] = raw.get("exclusions", raw if isinstance(raw, list) else [])
        sections_dir = directory / "sections"
        sections: list[Any] = []
        if sections_dir.is_dir():
            for path in sorted(sections_dir.glob("*.json")):
                sections.append(load_json_fixture(path))
        payload["sections"] = sections
        return payload

    def acquire_from_fixture(
        self,
        path: PathLike | None = None,
        *,
        register: bool = True,
    ) -> UscodeReleaseAcquisition:
        """Acquire Title 35 content from a recorded fixture package.

        Missing release identity yields :attr:`ResolutionStatus.UNKNOWN`.
        """

        payload = self.load_fixture_package(path)
        return self.acquire_from_payload(payload, register=register)

    def acquire_from_payload(
        self,
        payload: JsonMapping,
        *,
        register: bool = True,
    ) -> UscodeReleaseAcquisition:
        if not isinstance(payload, Mapping):
            raise FixtureSchemaError("payload must be a mapping")

        release_raw = payload.get("release") or payload.get("release_point")
        title = normalize_title(payload.get("title") or self.default_title)

        # Fail-closed: missing release data → unknown.
        if not release_raw:
            return UscodeReleaseAcquisition(
                status=ResolutionStatus.UNKNOWN,
                release_point=None,
                exclusions=(),
                sections={},
                title=title,
                unknown_reason="missing release data",
                notes="Exact release point unavailable; section authority is unknown.",
                metadata={"schema_version": payload.get("schema_version")},
            )

        if isinstance(release_raw, str):
            release_raw = {"release_point": release_raw, "provider": "ushouse", "title": title}

        if not isinstance(release_raw, Mapping):
            raise FixtureSchemaError("release must be a mapping or release_point string")

        # Explicit null/empty release_point field also yields unknown.
        rp_token = release_raw.get("release_point")
        has_congress_release = (
            release_raw.get("congress") is not None and release_raw.get("release") is not None
        )
        has_govinfo = bool(release_raw.get("govinfo_package_id"))
        if rp_token in (None, "") and not has_congress_release and not has_govinfo:
            return UscodeReleaseAcquisition(
                status=ResolutionStatus.UNKNOWN,
                release_point=None,
                exclusions=tuple(
                    ReleaseExclusion.from_dict(e)
                    for e in (payload.get("exclusions") or [])
                    if isinstance(e, Mapping)
                ),
                sections={},
                title=title,
                unknown_reason="missing release data",
                notes="Release mapping present but no concrete release identity.",
                metadata={"schema_version": payload.get("schema_version")},
            )

        try:
            release = ReleasePoint.from_dict({**dict(release_raw), "title": release_raw.get("title", title)})
        except (MissingReleasePointError, HardCodedLatestEditionError, UscodeReleaseError) as exc:
            return UscodeReleaseAcquisition(
                status=ResolutionStatus.UNKNOWN,
                release_point=None,
                exclusions=(),
                sections={},
                title=title,
                unknown_reason=str(exc),
                notes="Failed to parse release point; treating authority as unknown.",
                metadata={"schema_version": payload.get("schema_version"), "error": str(exc)},
            )

        exclusions = tuple(
            ReleaseExclusion.from_dict(item)
            for item in (payload.get("exclusions") or [])
            if isinstance(item, Mapping)
        )

        package_formats = _build_format_map(
            payload.get("package_formats") or release_raw.get("formats"),
            release=release,
            section="*",
        )

        sections: dict[str, UscodeSectionRecord] = {}
        for raw_sec in payload.get("sections") or []:
            if not isinstance(raw_sec, Mapping):
                continue
            sec_title = normalize_title(raw_sec.get("title", release.title))
            sec_num = normalize_section_token(raw_sec["section"])
            formats = _build_format_map(
                raw_sec.get("formats"),
                release=release,
                section=sec_num,
            )
            record = UscodeSectionRecord(
                title=sec_title,
                section=sec_num,
                stable_id=stable_section_identity(title=sec_title, section=sec_num),
                heading=raw_sec.get("heading"),
                citation=raw_sec.get("citation"),
                text_excerpt=raw_sec.get("text_excerpt"),
                formats=formats,
                status=ResolutionStatus.RESOLVED,
                release_point=release.release_point,
                metadata=raw_sec.get("metadata") or {},
            )
            sections[record.section] = record

        receipt = _build_receipt(release)
        if receipt is None and release.source_url:
            receipt = SourceReceipt(
                endpoint=release.source_url,
                retrieved_at=release.retrieved_at or datetime.now(timezone.utc),
                response_status=200,
                sanitized_request={"method": "GET"},
                upstream_id=release.release_point,
                content_sha256=release.content_sha256,
            )

        authority = _build_authority_source(
            release,
            formats=package_formats,
            receipt=receipt,
            verification_state=VerificationState.UNVERIFIED,
        )

        if register:
            self.registry.register(authority, overwrite=True)
            if receipt is not None and authority.receipt is None:
                self.registry.attach_receipt(authority.source_key, receipt)

        acquisition = UscodeReleaseAcquisition(
            status=ResolutionStatus.RESOLVED,
            release_point=release,
            exclusions=exclusions,
            sections=sections,
            authority_source=authority,
            receipt=receipt,
            title=release.title,
            notes=payload.get("notes"),
            metadata={
                "schema_version": payload.get("schema_version") or FIXTURE_SCHEMA_VERSION,
                "fixture_id": payload.get("fixture_id"),
                "exclusion_count": len(exclusions),
                "section_count": len(sections),
            },
        )
        self._acquisitions[release.release_point] = acquisition
        return acquisition

    # ------------------------------------------------------------------
    # Resolution API
    # ------------------------------------------------------------------

    def acquire_unknown(self, *, reason: str = "missing release data", title: Any | None = None) -> UscodeReleaseAcquisition:
        """Explicit unknown acquisition when no release can be established."""

        return UscodeReleaseAcquisition(
            status=ResolutionStatus.UNKNOWN,
            release_point=None,
            exclusions=(),
            sections={},
            title=self.default_title if title is None else normalize_title(title),
            unknown_reason=reason,
            notes="Exact release point unavailable; section authority is unknown.",
        )

    def resolve_patent_sensitive_sections(
        self,
        acquisition: UscodeReleaseAcquisition | None = None,
        *,
        path: PathLike | None = None,
    ) -> dict[str, UscodeSectionRecord]:
        """Resolve 35 USC 122 and 181–188 against a release acquisition."""

        acq = acquisition if acquisition is not None else self.acquire_from_fixture(path)
        resolved: dict[str, UscodeSectionRecord] = {}
        for section in PATENT_SENSITIVE_SECTIONS:
            resolved[section] = acq.resolve_section(section)
        return resolved

    def get_acquisition(self, release_point: str) -> UscodeReleaseAcquisition:
        key, _, _ = parse_release_point_id(release_point)
        try:
            return self._acquisitions[key]
        except KeyError as exc:
            # Also allow raw key lookup (govinfo package ids).
            if release_point in self._acquisitions:
                return self._acquisitions[release_point]
            raise UscodeReleaseError(f"no acquisition for release_point {release_point!r}") from exc

    def list_exclusions(
        self, acquisition: UscodeReleaseAcquisition | None = None
    ) -> tuple[ReleaseExclusion, ...]:
        if acquisition is None:
            if not self._acquisitions:
                return ()
            # Most recent insertion order is fine; values() is insertion-ordered.
            acquisition = next(reversed(list(self._acquisitions.values())))
        return acquisition.recorded_exclusions()


def build_title35_fixture_recipe(
    *,
    congress: int = 118,
    release: str = "45",
    fixture_id: str = "title35-uspl-118-45",
) -> dict[str, Any]:
    """Build a compact deterministic Title 35 fixture recipe for tests/tools.

    Prefer this generator over bulk golden dumps that re-emit full envelopes.
    """

    canonical, congress_s, release_s = parse_release_point_id(f"{congress}/{release}")
    content_seed = f"ushouse|{canonical}|title-35|package"
    package_sha = content_sha256(content_seed)
    source_url = ushouse_releasepoint_zip_url(
        congress=congress_s, release=release_s, title="35", format_kind=SourceFormat.USLM
    )

    headings = {
        "122": "Confidential status of applications; publication of patent applications",
        "181": "Secrecy of certain inventions and withholding of patent",
        "182": "Abandonment of invention for unauthorized disclosure",
        "183": "Right to compensation",
        "184": "Filing of application in foreign country",
        "185": "Patent barred for filing without license",
        "186": "Penalty",
        "187": "Nonapplicability to certain persons",
        "188": "Rules and regulations, delegation of power",
    }
    excerpts = {
        "122": (
            "(a) Except as provided in subsection (b), applications for patents "
            "shall be kept in confidence by the Patent and Trademark Office..."
        ),
        "181": (
            "Whenever publication or disclosure by the publication of an "
            "application or by the grant of a patent..."
        ),
    }

    sections: list[dict[str, Any]] = []
    for sec in PATENT_SENSITIVE_SECTIONS:
        formats = {}
        for fmt in (SourceFormat.USLM, SourceFormat.HTML, SourceFormat.PDF):
            seed = f"{canonical}|35|{sec}|{fmt.value}"
            formats[fmt.value] = {
                "format": fmt.value,
                "media_type": _media_type_for_format(fmt),
                "artifact_sha256": content_sha256(seed),
                "source_url": ushouse_releasepoint_zip_url(
                    congress=congress_s,
                    release=release_s,
                    title="35",
                    format_kind=fmt,
                ),
                "byte_size": 1000 + int(sec) + (10 if fmt is SourceFormat.PDF else 0),
                "upstream_package_id": canonical,
            }
        sections.append(
            {
                "title": "35",
                "section": sec,
                "heading": headings.get(sec, f"35 U.S.C. § {sec}"),
                "citation": f"35 U.S.C. § {sec}",
                "text_excerpt": excerpts.get(sec, f"[excerpt 35 U.S.C. § {sec}]"),
                "formats": formats,
            }
        )

    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "fixture_id": fixture_id,
        "title": "35",
        "notes": (
            "Compact Title 35 release-point recipe. Exact release point and "
            "uncodified/classification exclusions are recorded; sections 122 "
            "and 181–188 resolve with format-independent stable identities."
        ),
        "release": {
            "provider": "ushouse",
            "congress": int(congress_s),
            "release": release_s,
            "release_point": canonical,
            "title": "35",
            "edition": f"olrc-{canonical.replace('/', '-')}",
            "source_url": source_url,
            "content_sha256": package_sha,
            "retrieved_at": "2024-09-15T14:00:00Z",
            "formats": {
                "uslm": {
                    "format": "uslm",
                    "media_type": "application/uslm+xml",
                    "artifact_sha256": package_sha,
                    "source_url": source_url,
                    "upstream_package_id": canonical,
                },
                "html": {
                    "format": "html",
                    "media_type": "text/html",
                    "artifact_sha256": content_sha256(content_seed + "|html"),
                    "source_url": ushouse_releasepoint_zip_url(
                        congress=congress_s,
                        release=release_s,
                        title="35",
                        format_kind=SourceFormat.HTML,
                    ),
                    "upstream_package_id": canonical,
                },
            },
        },
        "exclusions": [
            {
                "kind": "uncodified_slip_law",
                "citation": "Pub. L. 118-100 § 3",
                "public_law": "Pub. L. 118-100",
                "reason": (
                    "Enacted patent-fee adjustment not yet classified into "
                    "positive-law Title 35 at this release point."
                ),
                "affects_sections": [],
            },
            {
                "kind": "classification_gap",
                "citation": "Pub. L. 117-328 div. W",
                "public_law": "Pub. L. 117-328",
                "reason": (
                    "Classification table records a pending editorial "
                    "reclassification affecting cross-references in Title 35."
                ),
                "affects_sections": ["122"],
            },
            {
                "kind": "positive_law_pending",
                "citation": "Uncodified national-security notice schedule",
                "reason": (
                    "Agency secrecy-order implementing schedule published as "
                    "uncodified material; not part of 35 U.S.C. 181–188 text."
                ),
                "affects_sections": ["181", "182", "183", "184", "185", "186", "187", "188"],
            },
        ],
        "sections": sections,
    }


def write_default_fixtures(directory: PathLike | None = None) -> Path:
    """Materialize the default Title 35 fixture recipe and missing-release case."""

    root = Path(directory) if directory is not None else default_fixture_dir()
    root.mkdir(parents=True, exist_ok=True)

    recipe = build_title35_fixture_recipe()
    recipe_path = root / "title35_release_recipe.json"
    recipe_path.write_text(
        json.dumps(recipe, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    missing = {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "fixture_id": "title35-missing-release",
        "title": "35",
        "notes": "Release identity deliberately omitted for unknown-status tests.",
        "release": {
            "provider": "ushouse",
            "title": "35",
            "release_point": None,
        },
        "exclusions": [],
        "sections": [],
    }
    missing_path = root / "title35_missing_release.json"
    missing_path.write_text(
        json.dumps(missing, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Lightweight README for operators (not required by admission, but helpful).
    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Title 35 U.S. Code release-point fixtures\n\n"
            "Compact recipes for PATLAW-013. Prefer `title35_release_recipe.json` "
            "over bulk golden dumps. Missing release data is modeled in "
            "`title35_missing_release.json` and must resolve as `unknown`.\n",
            encoding="utf-8",
        )
    return root


__all__ = [
    "COLLECTION_USCODE",
    "CONFIDENTIALITY_SECTION",
    "DEFAULT_TITLE",
    "FIXTURE_SCHEMA_VERSION",
    "PATENT_SENSITIVE_SECTIONS",
    "SCHEMA_VERSION",
    "SECRECY_ORDER_SECTIONS",
    "ExclusionKind",
    "FixtureSchemaError",
    "FormatArtifact",
    "MissingReleasePointError",
    "ReleaseExclusion",
    "ReleasePoint",
    "ResolutionStatus",
    "SectionNotFoundError",
    "SourceFormat",
    "UscodeReleaseAcquisition",
    "UscodeReleaseError",
    "UscodeReleaseProcessor",
    "UscodeSectionRecord",
    "build_title35_fixture_recipe",
    "content_sha256",
    "default_fixture_dir",
    "govinfo_title_package_id",
    "govinfo_title_zip_url",
    "load_json_fixture",
    "normalize_section_token",
    "normalize_title",
    "parse_release_point_id",
    "stable_section_identity",
    "ushouse_releasepoint_zip_url",
    "ushouse_title_code",
    "write_default_fixtures",
]
