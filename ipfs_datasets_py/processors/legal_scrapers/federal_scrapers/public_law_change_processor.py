"""Public Law change acquisition and full examination manifest (PATLAW-018).

Acquires GovInfo Public Law (PLAW / STATUTE) packages and builds an examination
manifest that retains **every** examined Public Law, including those that are
not patent-relevant. Patent relevance is a first-class flag, never a filter
that drops non-patent laws from the manifest.

Design invariants:

* Edition / package identity is never the hard-coded token ``\"latest\"``;
  concrete congress/law package ids are discovered at runtime or pinned in
  fixtures.
* House OLRC codification views and eCFR/FederalRegister.gov material may
  appear only as **cross-check** (``unofficial-current`` /
  ``derived_presentation``); they never replace the official GovInfo Public
  Law artifact.
* Official Public Law packages carry ``authority_tier=official-change`` with
  ``IdentityRole.OFFICIAL_ARTIFACT``.
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

SCHEMA_VERSION = "public-law-change-processor-v1"
FIXTURE_SCHEMA_VERSION = "public-law-change-fixture-v1"

DEFAULT_PROVIDER = "govinfo"
DEFAULT_JURISDICTION = "US"
COLLECTION_PLAW = "PLAW"
COLLECTION_STATUTE = "STATUTE"

GOVINFO_API_BASE = "https://api.govinfo.gov"
GOVINFO_CONTENT_BASE = "https://www.govinfo.gov/content/pkg"

# Cross-check providers that must never become official Public Law authority.
CROSS_CHECK_PROVIDERS = frozenset(
    {
        "ushouse",
        "uscode.house.gov",
        "house",
        "ecfr",
        "www.ecfr.gov",
        "federalregister.gov",
        "www.federalregister.gov",
        "fr.gov",
    }
)

# Keywords used for a lightweight patent-relevance classifier (not a legal opinion).
_PATENT_KEYWORDS = frozenset(
    {
        "patent",
        "patents",
        "trademark",
        "trademarks",
        "uspto",
        "invention",
        "inventions",
        "title 35",
        "35 u.s.c",
        "patent and trademark office",
        "intellectual property",
        "inter partes",
        "ptab",
        "priority date",
        "provisional application",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PL_NUMBER_RE = re.compile(
    r"(?:pub(?:lic)?\.?\s*l(?:aw)?\.?\s*)?(?P<congress>\d{2,3})[-–—/\s]+(?P<law>\d{1,4})",
    re.IGNORECASE,
)
_PACKAGE_ID_RE = re.compile(
    r"^PLAW-(?P<congress>\d{2,3})publ(?P<law>\d{1,4})$",
    re.IGNORECASE,
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PublicLawChangeError(ValueError):
    """Base error for Public Law change processing."""


class FixtureSchemaError(PublicLawChangeError):
    """Raised when a fixture package is malformed."""


class PublicLawNotFoundError(PublicLawChangeError):
    """Raised when a requested Public Law is not present."""


class CrossCheckMasqueradeError(PublicLawChangeError):
    """Raised when a cross-check source is presented as official Public Law."""


class MissingPackageError(PublicLawChangeError):
    """Raised when Public Law package identity cannot be established."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ResolutionStatus(str, Enum):
    """Outcome of Public Law acquisition or examination."""

    RESOLVED = "resolved"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    ERROR = "error"
    CONFLICT = "conflict"
    INCONCLUSIVE = "inconclusive"
    UNVERIFIED = "unverified"


class SourceFormat(str, Enum):
    """Supported Public Law packaging formats."""

    PDF = "pdf"
    XML = "xml"
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
            "pdf": cls.PDF,
            "application/pdf": cls.PDF,
            "xml": cls.XML,
            "application/xml": cls.XML,
            "text/xml": cls.XML,
            "html": cls.HTML,
            "htm": cls.HTML,
            "text/html": cls.HTML,
            "mods": cls.MODS,
            "application/mods+xml": cls.MODS,
            "premis": cls.PREMIS,
            "application/premis+xml": cls.PREMIS,
            "zip": cls.ZIP,
            "application/zip": cls.ZIP,
            "text": cls.TEXT,
            "txt": cls.TEXT,
            "text/plain": cls.TEXT,
        }
        if text not in aliases:
            raise PublicLawChangeError(f"unsupported source format: {value!r}")
        return aliases[text]


class CrossCheckRole(str, Enum):
    """How a non-GovInfo view is used relative to the official Public Law."""

    NONE = "none"
    HOUSE_CODIFICATION = "house_codification"
    ECFR_PRESENTATION = "ecfr_presentation"
    FEDERAL_REGISTER_DISCOVERY = "federal_register_discovery"
    OTHER = "other"

    @classmethod
    def coerce(cls, value: Any) -> "CrossCheckRole":
        if isinstance(value, CrossCheckRole):
            return value
        text = str(value or "none").strip().lower().replace("-", "_").replace(" ", "_")
        for role in cls:
            if role.value == text or role.name.lower() == text:
                return role
        return cls.OTHER


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PublicLawChangeError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise PublicLawChangeError(f"{name} must not contain NUL")
    return value.strip()


def _optional_str(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, "value")


def _require_sha256(value: Any, name: str = "sha256") -> str:
    text = _require_non_empty_str(value, name).lower()
    if not _SHA256_RE.fullmatch(text):
        raise PublicLawChangeError(f"{name} must be a lowercase 64-char hex SHA-256")
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
            raise PublicLawChangeError(f"{name} must be ISO-8601 datetime") from exc
    else:
        raise PublicLawChangeError(f"{name} must be a datetime or ISO-8601 string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def _format_utc(dt: datetime) -> str:
    normalized = dt.astimezone(timezone.utc).replace(
        microsecond=(dt.microsecond // 1000) * 1000
    )
    return normalized.isoformat().replace("+00:00", "Z")


def _parse_optional_date(value: Any, *, name: str) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError as exc:
            raise PublicLawChangeError(f"{name} must be an ISO date") from exc
    raise PublicLawChangeError(f"{name} must be a date or ISO date string")


def _date_to_str(value: Optional[date]) -> Optional[str]:
    return None if value is None else value.isoformat()


def _deep_sorted(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(k): _deep_sorted(value[k]) for k in sorted(value.keys(), key=lambda x: str(x))
        }
    if isinstance(value, (list, tuple)):
        return [_deep_sorted(v) for v in value]
    return value


def content_sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _media_type_for_format(fmt: SourceFormat) -> str:
    return {
        SourceFormat.PDF: "application/pdf",
        SourceFormat.XML: "application/xml",
        SourceFormat.HTML: "text/html",
        SourceFormat.MODS: "application/mods+xml",
        SourceFormat.PREMIS: "application/premis+xml",
        SourceFormat.ZIP: "application/zip",
        SourceFormat.TEXT: "text/plain",
    }[fmt]


def normalize_congress(value: Any) -> str:
    text = _require_non_empty_str(str(value), "congress")
    reject_hard_coded_latest(text, field_name="congress")
    if not text.isdigit():
        raise PublicLawChangeError(f"congress must be numeric, got {value!r}")
    return str(int(text))


def normalize_law_number(value: Any) -> str:
    text = _require_non_empty_str(str(value), "law_number")
    reject_hard_coded_latest(text, field_name="law_number")
    digits = re.sub(r"\D", "", text)
    if not digits:
        raise PublicLawChangeError(f"law_number must contain digits, got {value!r}")
    return str(int(digits))


def parse_public_law_number(value: Any) -> tuple[str, str, str]:
    """Return ``(citation, congress, law_number)`` for a Public Law identifier.

    Accepts forms such as ``Pub. L. 118-45``, ``118/45``, ``PLAW-118publ45``.
    Never accepts the hard-coded token ``latest``.
    """

    if value is None:
        raise PublicLawChangeError("public_law number is required")
    text = _require_non_empty_str(str(value), "public_law")
    reject_hard_coded_latest(text, field_name="public_law")

    pkg = _PACKAGE_ID_RE.fullmatch(text.replace("_", "-"))
    if pkg:
        congress = normalize_congress(pkg.group("congress"))
        law = normalize_law_number(pkg.group("law"))
        return f"Pub. L. {congress}-{law}", congress, law

    match = _PL_NUMBER_RE.search(text)
    if not match:
        raise PublicLawChangeError(f"unrecognized public law number: {value!r}")
    congress = normalize_congress(match.group("congress"))
    law = normalize_law_number(match.group("law"))
    return f"Pub. L. {congress}-{law}", congress, law


def govinfo_plaw_package_id(*, congress: Any, law_number: Any) -> str:
    """Build a concrete GovInfo PLAW package id (never ``latest``)."""

    c = normalize_congress(congress)
    n = normalize_law_number(law_number)
    return f"PLAW-{c}publ{n}"


def govinfo_plaw_package_url(package_id: Any) -> str:
    pid = normalize_plaw_package_id(package_id)
    return f"{GOVINFO_CONTENT_BASE}/{pid}"


def normalize_plaw_package_id(package_id: Any) -> str:
    text = _require_non_empty_str(str(package_id), "package_id")
    reject_hard_coded_latest(text, field_name="package_id")
    upper = text.upper().replace("_", "-")
    match = _PACKAGE_ID_RE.fullmatch(upper)
    if match:
        return f"PLAW-{normalize_congress(match.group('congress'))}publ{normalize_law_number(match.group('law'))}"
    # Allow STATUTE- style and other concrete package ids; still reject latest.
    if "LATEST" in upper:
        raise HardCodedLatestEditionError(
            "package_id must not be the hard-coded token 'latest'"
        )
    return upper


def stable_public_law_identity(*, congress: Any, law_number: Any) -> str:
    c = normalize_congress(congress)
    n = normalize_law_number(law_number)
    return f"plaw:us:{c}:{n}"


def classify_patent_relevance(
    *,
    title: Optional[str] = None,
    text_excerpt: Optional[str] = None,
    subjects: Sequence[str] | None = None,
    affects_titles: Sequence[str] | None = None,
    explicit: Optional[bool] = None,
) -> bool:
    """Heuristic patent-relevance flag (not a legal determination).

    When *explicit* is provided it wins. Otherwise Title 35 touches or keyword
    matches in title/text/subjects mark the law as patent-relevant.
    """

    if explicit is not None:
        return bool(explicit)
    for t in affects_titles or ():
        if str(t).strip() in {"35", "Title 35", "title 35"}:
            return True
    haystacks = [title or "", text_excerpt or ""]
    haystacks.extend(str(s) for s in (subjects or ()))
    blob = " ".join(haystacks).lower()
    return any(kw in blob for kw in _PATENT_KEYWORDS)


def assert_cross_check_only(
    *,
    provider: Any,
    role: IdentityRole | str | None = None,
    authority_tier: AuthorityTier | str | None = None,
    cross_check_role: CrossCheckRole | str | None = None,
) -> None:
    """Fail closed when a cross-check provider is labeled as official."""

    provider_text = str(provider or "").strip().lower()
    is_cross = provider_text in CROSS_CHECK_PROVIDERS or (
        cross_check_role is not None
        and CrossCheckRole.coerce(cross_check_role) is not CrossCheckRole.NONE
    )
    if not is_cross:
        return

    role_obj = None if role is None else (
        role if isinstance(role, IdentityRole) else IdentityRole(str(role))
    )
    tier_obj = None
    if authority_tier is not None:
        if isinstance(authority_tier, AuthorityTier):
            tier_obj = authority_tier
        else:
            tier_obj = AuthorityTier(str(authority_tier).replace("_", "-"))

    if role_obj is IdentityRole.OFFICIAL_ARTIFACT:
        raise CrossCheckMasqueradeError(
            f"provider {provider!r} is cross-check-only and cannot carry "
            f"IdentityRole.OFFICIAL_ARTIFACT"
        )
    if tier_obj in (AuthorityTier.OFFICIAL_BASE, AuthorityTier.OFFICIAL_CHANGE):
        raise CrossCheckMasqueradeError(
            f"provider {provider!r} is cross-check-only and cannot carry "
            f"authority_tier={tier_obj.value}"
        )


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FormatArtifact:
    """One content format for a Public Law package or granule."""

    format: SourceFormat
    artifact_sha256: str
    source_url: str
    media_type: Optional[str] = None
    byte_size: Optional[int] = None
    upstream_package_id: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "format", SourceFormat.coerce(self.format))
        object.__setattr__(
            self, "artifact_sha256", _require_sha256(self.artifact_sha256, "artifact_sha256")
        )
        object.__setattr__(
            self, "source_url", _require_non_empty_str(self.source_url, "source_url")
        )
        if self.media_type is None:
            object.__setattr__(self, "media_type", _media_type_for_format(self.format))
        else:
            object.__setattr__(
                self, "media_type", _require_non_empty_str(self.media_type, "media_type")
            )
        if self.byte_size is not None:
            if not isinstance(self.byte_size, int) or self.byte_size < 0:
                raise PublicLawChangeError("byte_size must be a non-negative int")
        if self.upstream_package_id is not None:
            object.__setattr__(
                self,
                "upstream_package_id",
                normalize_plaw_package_id(self.upstream_package_id),
            )
        if not isinstance(self.metadata, Mapping):
            raise PublicLawChangeError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_artifact_identity(
        self,
        *,
        provider: str = DEFAULT_PROVIDER,
        source_id: str,
        role: IdentityRole = IdentityRole.OFFICIAL_ARTIFACT,
    ) -> ArtifactIdentity:
        return ArtifactIdentity(
            provider=provider,
            source_id=source_id,
            artifact_sha256=self.artifact_sha256,
            source_url=self.source_url,
            media_type=self.media_type,
            byte_size=self.byte_size,
            upstream_package_id=self.upstream_package_id,
            role=role,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_sha256": self.artifact_sha256,
            "byte_size": self.byte_size,
            "format": self.format.value,
            "media_type": self.media_type,
            "metadata": _deep_sorted(self.metadata),
            "source_url": self.source_url,
            "upstream_package_id": self.upstream_package_id,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "FormatArtifact":
        if not isinstance(value, Mapping):
            raise FixtureSchemaError("format artifact must be a mapping")
        return cls(
            format=value.get("format", SourceFormat.PDF),
            artifact_sha256=value["artifact_sha256"],
            source_url=value["source_url"],
            media_type=value.get("media_type"),
            byte_size=value.get("byte_size"),
            upstream_package_id=value.get("upstream_package_id")
            or value.get("package_id"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """Character or page span anchoring extracted text to an official artifact."""

    start: int
    end: int
    unit: str = "char"  # char | page | line
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    excerpt: Optional[str] = None
    format: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.start, int) or not isinstance(self.end, int):
            raise PublicLawChangeError("source span start/end must be ints")
        if self.start < 0 or self.end < self.start:
            raise PublicLawChangeError("source span requires 0 <= start <= end")
        unit = _require_non_empty_str(self.unit, "unit").lower()
        if unit not in {"char", "page", "line"}:
            raise PublicLawChangeError(f"unsupported source span unit: {unit!r}")
        object.__setattr__(self, "unit", unit)
        if self.excerpt is not None:
            object.__setattr__(
                self, "excerpt", _require_non_empty_str(self.excerpt, "excerpt")
            )
        if self.format is not None:
            object.__setattr__(
                self, "format", _require_non_empty_str(self.format, "format")
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "end": self.end,
            "excerpt": self.excerpt,
            "format": self.format,
            "page_end": self.page_end,
            "page_start": self.page_start,
            "start": self.start,
            "unit": self.unit,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "SourceSpan":
        if not isinstance(value, Mapping):
            raise FixtureSchemaError("source_span must be a mapping")
        return cls(
            start=int(value["start"]),
            end=int(value["end"]),
            unit=str(value.get("unit") or "char"),
            page_start=value.get("page_start"),
            page_end=value.get("page_end"),
            excerpt=value.get("excerpt"),
            format=value.get("format"),
        )


@dataclass(frozen=True, slots=True)
class CrossCheckView:
    """House / eCFR / FederalRegister.gov view used only for cross-check."""

    provider: str
    role: CrossCheckRole
    source_url: Optional[str] = None
    content_sha256: Optional[str] = None
    notes: Optional[str] = None
    derived_presentation: Optional[ArtifactIdentity] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provider", _require_non_empty_str(self.provider, "provider")
        )
        object.__setattr__(self, "role", CrossCheckRole.coerce(self.role))
        if self.role is CrossCheckRole.NONE:
            raise PublicLawChangeError("cross-check view requires a non-none role")
        assert_cross_check_only(
            provider=self.provider,
            role=IdentityRole.DERIVED_PRESENTATION,
            authority_tier=AuthorityTier.UNOFFICIAL_CURRENT,
            cross_check_role=self.role,
        )
        if self.source_url is not None:
            object.__setattr__(
                self, "source_url", _require_non_empty_str(self.source_url, "source_url")
            )
        if self.content_sha256 is not None:
            object.__setattr__(
                self,
                "content_sha256",
                _require_sha256(self.content_sha256, "content_sha256"),
            )
        if self.notes is not None:
            object.__setattr__(self, "notes", _require_non_empty_str(self.notes, "notes"))
        if self.derived_presentation is not None:
            raw_dp = self.derived_presentation
            if not isinstance(raw_dp, ArtifactIdentity):
                # Reject official role on the raw payload before coercion.
                if isinstance(raw_dp, Mapping):
                    raw_role = raw_dp.get("role")
                    if raw_role is not None:
                        role_text = (
                            raw_role.value
                            if isinstance(raw_role, IdentityRole)
                            else str(raw_role)
                        )
                        if role_text in {
                            IdentityRole.OFFICIAL_ARTIFACT.value,
                            "official_artifact",
                            "OFFICIAL_ARTIFACT",
                        }:
                            raise CrossCheckMasqueradeError(
                                f"cross-check provider {self.provider!r} cannot carry "
                                f"IdentityRole.OFFICIAL_ARTIFACT"
                            )
                object.__setattr__(
                    self,
                    "derived_presentation",
                    ArtifactIdentity.from_dict(raw_dp),  # type: ignore[arg-type]
                )
            dp = self.derived_presentation
            if dp.role is IdentityRole.OFFICIAL_ARTIFACT:
                raise CrossCheckMasqueradeError(
                    f"cross-check provider {self.provider!r} cannot carry "
                    f"IdentityRole.OFFICIAL_ARTIFACT"
                )
            if dp.role is not IdentityRole.DERIVED_PRESENTATION:
                object.__setattr__(
                    self,
                    "derived_presentation",
                    ArtifactIdentity(
                        provider=dp.provider,
                        source_id=dp.source_id,
                        artifact_sha256=dp.artifact_sha256,
                        source_url=dp.source_url,
                        media_type=dp.media_type,
                        byte_size=dp.byte_size,
                        upstream_package_id=dp.upstream_package_id,
                        role=IdentityRole.DERIVED_PRESENTATION,
                    ),
                )
            assert_cross_check_only(
                provider=self.derived_presentation.provider,
                role=self.derived_presentation.role,
                authority_tier=AuthorityTier.UNOFFICIAL_CURRENT,
                cross_check_role=self.role,
            )
        if not isinstance(self.metadata, Mapping):
            raise PublicLawChangeError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def is_official(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_sha256": self.content_sha256,
            "derived_presentation": (
                None
                if self.derived_presentation is None
                else self.derived_presentation.to_dict()
            ),
            "is_official": False,
            "metadata": _deep_sorted(self.metadata),
            "notes": self.notes,
            "provider": self.provider,
            "role": self.role.value,
            "source_url": self.source_url,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "CrossCheckView":
        if not isinstance(value, Mapping):
            raise FixtureSchemaError("cross_check must be a mapping")
        dp_raw = value.get("derived_presentation")
        return cls(
            provider=str(value.get("provider") or ""),
            role=value.get("role") or CrossCheckRole.OTHER,
            source_url=value.get("source_url"),
            content_sha256=value.get("content_sha256"),
            notes=value.get("notes"),
            derived_presentation=(
                None if dp_raw is None else ArtifactIdentity.from_dict(dp_raw)
            ),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class PublicLawRecord:
    """One examined Public Law package (patent-relevant or not)."""

    congress: str
    law_number: str
    title: str
    citation: str
    package_id: str
    stable_id: str
    patent_relevant: bool
    date_enacted: Optional[date] = None
    date_approved: Optional[date] = None
    subjects: tuple[str, ...] = ()
    affects_titles: tuple[str, ...] = ()
    text_excerpt: Optional[str] = None
    source_spans: tuple[SourceSpan, ...] = ()
    formats: Mapping[str, FormatArtifact] = field(default_factory=dict)
    official_artifact: Optional[ArtifactIdentity] = None
    cross_checks: tuple[CrossCheckView, ...] = ()
    content_sha256: Optional[str] = None
    source_url: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    verification_state: VerificationState = VerificationState.UNVERIFIED
    status: ResolutionStatus = ResolutionStatus.RESOLVED
    receipt: Optional[SourceReceipt] = None
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        congress = normalize_congress(self.congress)
        law_number = normalize_law_number(self.law_number)
        object.__setattr__(self, "congress", congress)
        object.__setattr__(self, "law_number", law_number)
        object.__setattr__(self, "title", _require_non_empty_str(self.title, "title"))
        if self.citation:
            object.__setattr__(
                self, "citation", _require_non_empty_str(self.citation, "citation")
            )
        else:
            object.__setattr__(self, "citation", f"Pub. L. {congress}-{law_number}")
        object.__setattr__(
            self, "package_id", normalize_plaw_package_id(self.package_id)
        )
        if not self.stable_id:
            object.__setattr__(
                self,
                "stable_id",
                stable_public_law_identity(congress=congress, law_number=law_number),
            )
        else:
            object.__setattr__(
                self, "stable_id", _require_non_empty_str(self.stable_id, "stable_id")
            )
        object.__setattr__(self, "patent_relevant", bool(self.patent_relevant))
        object.__setattr__(
            self, "date_enacted", _parse_optional_date(self.date_enacted, name="date_enacted")
        )
        object.__setattr__(
            self,
            "date_approved",
            _parse_optional_date(self.date_approved, name="date_approved"),
        )
        object.__setattr__(
            self,
            "subjects",
            tuple(
                _require_non_empty_str(str(s), "subject")
                for s in (self.subjects or ())
                if s is not None and str(s).strip()
            ),
        )
        object.__setattr__(
            self,
            "affects_titles",
            tuple(
                str(t).strip()
                for t in (self.affects_titles or ())
                if t is not None and str(t).strip()
            ),
        )
        if self.text_excerpt is not None:
            object.__setattr__(
                self,
                "text_excerpt",
                _require_non_empty_str(self.text_excerpt, "text_excerpt"),
            )
        spans: list[SourceSpan] = []
        for raw in self.source_spans or ():
            if isinstance(raw, SourceSpan):
                spans.append(raw)
            elif isinstance(raw, Mapping):
                spans.append(SourceSpan.from_dict(raw))
            else:
                raise PublicLawChangeError("source_spans entries must be mappings")
        object.__setattr__(self, "source_spans", tuple(spans))
        fmt_map: dict[str, FormatArtifact] = {}
        for key, raw in dict(self.formats or {}).items():
            if isinstance(raw, FormatArtifact):
                art = raw
            elif isinstance(raw, Mapping):
                payload = dict(raw)
                payload.setdefault("format", key)
                payload.setdefault("upstream_package_id", self.package_id)
                art = FormatArtifact.from_dict(payload)
            else:
                raise PublicLawChangeError(f"format entry {key!r} must be a mapping")
            fmt_map[art.format.value] = art
        object.__setattr__(self, "formats", fmt_map)
        if self.official_artifact is not None:
            if not isinstance(self.official_artifact, ArtifactIdentity):
                object.__setattr__(
                    self,
                    "official_artifact",
                    ArtifactIdentity.from_dict(self.official_artifact),  # type: ignore[arg-type]
                )
            oa = self.official_artifact
            if oa.role is not IdentityRole.OFFICIAL_ARTIFACT:
                object.__setattr__(
                    self,
                    "official_artifact",
                    ArtifactIdentity(
                        provider=oa.provider,
                        source_id=oa.source_id,
                        artifact_sha256=oa.artifact_sha256,
                        source_url=oa.source_url,
                        media_type=oa.media_type,
                        byte_size=oa.byte_size,
                        upstream_package_id=oa.upstream_package_id,
                        role=IdentityRole.OFFICIAL_ARTIFACT,
                    ),
                )
            # Official artifact provider must not be a cross-check source.
            assert_cross_check_only(
                provider=self.official_artifact.provider,
                role=self.official_artifact.role,
                authority_tier=AuthorityTier.OFFICIAL_CHANGE,
            )
        checks: list[CrossCheckView] = []
        for raw in self.cross_checks or ():
            if isinstance(raw, CrossCheckView):
                checks.append(raw)
            elif isinstance(raw, Mapping):
                checks.append(CrossCheckView.from_dict(raw))
            else:
                raise PublicLawChangeError("cross_checks entries must be mappings")
        object.__setattr__(self, "cross_checks", tuple(checks))
        if self.content_sha256 is not None:
            object.__setattr__(
                self,
                "content_sha256",
                _require_sha256(self.content_sha256, "content_sha256"),
            )
        if self.source_url is not None:
            object.__setattr__(
                self, "source_url", _require_non_empty_str(self.source_url, "source_url")
            )
        if self.retrieved_at is not None:
            object.__setattr__(
                self, "retrieved_at", _parse_utc(self.retrieved_at, name="retrieved_at")
            )
        if not isinstance(self.verification_state, VerificationState):
            object.__setattr__(
                self,
                "verification_state",
                VerificationState(str(self.verification_state)),
            )
        if not isinstance(self.status, ResolutionStatus):
            object.__setattr__(self, "status", ResolutionStatus(str(self.status)))
        if self.receipt is not None and not isinstance(self.receipt, SourceReceipt):
            object.__setattr__(
                self, "receipt", SourceReceipt.from_dict(self.receipt)  # type: ignore[arg-type]
            )
        if self.notes is not None:
            object.__setattr__(self, "notes", _require_non_empty_str(self.notes, "notes"))
        if not isinstance(self.metadata, Mapping):
            raise PublicLawChangeError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def authority_tier(self) -> AuthorityTier:
        return AuthorityTier.OFFICIAL_CHANGE

    def preferred_format(self) -> Optional[FormatArtifact]:
        for key in (
            SourceFormat.PDF.value,
            SourceFormat.XML.value,
            SourceFormat.MODS.value,
            SourceFormat.HTML.value,
        ):
            if key in self.formats:
                return self.formats[key]
        if self.formats:
            return next(iter(self.formats.values()))
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "affects_titles": list(self.affects_titles),
            "authority_tier": self.authority_tier.value,
            "citation": self.citation,
            "congress": self.congress,
            "content_sha256": self.content_sha256,
            "cross_checks": [c.to_dict() for c in self.cross_checks],
            "date_approved": _date_to_str(self.date_approved),
            "date_enacted": _date_to_str(self.date_enacted),
            "formats": {k: v.to_dict() for k, v in sorted(self.formats.items())},
            "law_number": self.law_number,
            "metadata": _deep_sorted(self.metadata),
            "notes": self.notes,
            "official_artifact": (
                None if self.official_artifact is None else self.official_artifact.to_dict()
            ),
            "package_id": self.package_id,
            "patent_relevant": self.patent_relevant,
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "retrieved_at": (
                None if self.retrieved_at is None else _format_utc(self.retrieved_at)
            ),
            "source_spans": [s.to_dict() for s in self.source_spans],
            "source_url": self.source_url,
            "stable_id": self.stable_id,
            "status": self.status.value,
            "subjects": list(self.subjects),
            "text_excerpt": self.text_excerpt,
            "title": self.title,
            "verification_state": self.verification_state.value,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "PublicLawRecord":
        if not isinstance(value, Mapping):
            raise FixtureSchemaError("public law record must be a mapping")
        congress = value.get("congress")
        law_number = value.get("law_number") or value.get("number")
        package_id = value.get("package_id")
        citation = value.get("citation")
        if (congress is None or law_number is None) and (
            citation or value.get("public_law") or package_id
        ):
            cite, congress, law_number = parse_public_law_number(
                package_id or citation or value.get("public_law")
            )
            citation = citation or cite
        if congress is None or law_number is None:
            raise FixtureSchemaError("public law requires congress and law_number")
        if not package_id:
            package_id = govinfo_plaw_package_id(congress=congress, law_number=law_number)
        cite = citation or f"Pub. L. {normalize_congress(congress)}-{normalize_law_number(law_number)}"
        patent_relevant = value.get("patent_relevant")
        if patent_relevant is None:
            patent_relevant = classify_patent_relevance(
                title=value.get("title"),
                text_excerpt=value.get("text_excerpt"),
                subjects=value.get("subjects") or (),
                affects_titles=value.get("affects_titles") or (),
            )
        oa_raw = value.get("official_artifact")
        receipt_raw = value.get("receipt")
        return cls(
            congress=str(congress),
            law_number=str(law_number),
            title=str(value.get("title") or cite),
            citation=str(cite),
            package_id=str(package_id),
            stable_id=str(
                value.get("stable_id")
                or stable_public_law_identity(congress=congress, law_number=law_number)
            ),
            patent_relevant=bool(patent_relevant),
            date_enacted=value.get("date_enacted") or value.get("date_approved"),
            date_approved=value.get("date_approved"),
            subjects=tuple(value.get("subjects") or ()),
            affects_titles=tuple(value.get("affects_titles") or ()),
            text_excerpt=value.get("text_excerpt"),
            source_spans=tuple(value.get("source_spans") or ()),
            formats=value.get("formats") or {},
            official_artifact=(
                None if oa_raw is None else ArtifactIdentity.from_dict(oa_raw)
            ),
            cross_checks=tuple(value.get("cross_checks") or ()),
            content_sha256=value.get("content_sha256"),
            source_url=value.get("source_url"),
            retrieved_at=value.get("retrieved_at"),
            verification_state=value.get("verification_state")
            or VerificationState.UNVERIFIED,
            status=value.get("status") or ResolutionStatus.RESOLVED,
            receipt=None if receipt_raw is None else SourceReceipt.from_dict(receipt_raw),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class PublicLawManifest:
    """Examination manifest: every examined Public Law remains present.

    Patent relevance is recorded per entry; non-patent laws are never dropped.
    """

    examined: Mapping[str, PublicLawRecord]
    discovered_at: Optional[datetime] = None
    inventory_source: Optional[str] = None
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        items: dict[str, PublicLawRecord] = {}
        for key, raw in dict(self.examined or {}).items():
            if isinstance(raw, PublicLawRecord):
                rec = raw
            elif isinstance(raw, Mapping):
                rec = PublicLawRecord.from_dict(raw)
            else:
                raise PublicLawChangeError("manifest entries must be PublicLawRecord mappings")
            items[rec.stable_id] = rec
        object.__setattr__(self, "examined", items)
        if self.discovered_at is not None:
            object.__setattr__(
                self, "discovered_at", _parse_utc(self.discovered_at, name="discovered_at")
            )
        if self.inventory_source is not None:
            object.__setattr__(
                self,
                "inventory_source",
                _require_non_empty_str(self.inventory_source, "inventory_source"),
            )
            reject_hard_coded_latest(self.inventory_source, field_name="inventory_source")
        if self.notes is not None:
            object.__setattr__(self, "notes", _require_non_empty_str(self.notes, "notes"))
        if not isinstance(self.metadata, Mapping):
            raise PublicLawChangeError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def total_examined(self) -> int:
        return len(self.examined)

    @property
    def patent_relevant_count(self) -> int:
        return sum(1 for r in self.examined.values() if r.patent_relevant)

    @property
    def non_patent_count(self) -> int:
        return self.total_examined - self.patent_relevant_count

    def all_package_ids(self) -> tuple[str, ...]:
        return tuple(sorted({r.package_id for r in self.examined.values()}))

    def get(self, public_law: Any) -> PublicLawRecord:
        if public_law in self.examined:
            return self.examined[str(public_law)]
        cite, congress, law = parse_public_law_number(public_law)
        sid = stable_public_law_identity(congress=congress, law_number=law)
        try:
            return self.examined[sid]
        except KeyError as exc:
            raise PublicLawNotFoundError(
                f"Public Law {cite} not present in examination manifest"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "discovered_at": (
                None if self.discovered_at is None else _format_utc(self.discovered_at)
            ),
            "examined": {
                k: v.to_dict() for k, v in sorted(self.examined.items(), key=lambda kv: kv[0])
            },
            "inventory_source": self.inventory_source,
            "metadata": _deep_sorted(self.metadata),
            "non_patent_count": self.non_patent_count,
            "notes": self.notes,
            "patent_relevant_count": self.patent_relevant_count,
            "schema_version": SCHEMA_VERSION,
            "total_examined": self.total_examined,
        }


@dataclass(frozen=True, slots=True)
class PublicLawAcquisition:
    """Result of acquiring and examining a set of Public Law packages."""

    status: ResolutionStatus
    manifest: PublicLawManifest
    authority_sources: tuple[AuthoritySourceRecord, ...] = ()
    receipt: Optional[SourceReceipt] = None
    notes: Optional[str] = None
    unknown_reason: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, ResolutionStatus):
            object.__setattr__(self, "status", ResolutionStatus(str(self.status)))
        if not isinstance(self.manifest, PublicLawManifest):
            raise PublicLawChangeError("manifest must be a PublicLawManifest")
        if not isinstance(self.metadata, Mapping):
            raise PublicLawChangeError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def list_all(self) -> tuple[PublicLawRecord, ...]:
        return tuple(
            self.manifest.examined[k] for k in sorted(self.manifest.examined.keys())
        )

    def list_patent_relevant(self) -> tuple[PublicLawRecord, ...]:
        return tuple(r for r in self.list_all() if r.patent_relevant)

    def list_non_patent(self) -> tuple[PublicLawRecord, ...]:
        return tuple(r for r in self.list_all() if not r.patent_relevant)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_sources": [a.to_dict() for a in self.authority_sources],
            "manifest": self.manifest.to_dict(),
            "metadata": _deep_sorted(self.metadata),
            "notes": self.notes,
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "schema_version": SCHEMA_VERSION,
            "status": self.status.value,
            "unknown_reason": self.unknown_reason,
        }


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def default_fixture_dir() -> Path:
    """Return the repository Public Law fixture directory when present."""

    here = Path(__file__).resolve()
    candidates = [
        here.parents[4]
        / "tests"
        / "fixtures"
        / "legal_data"
        / "patent_authorities"
        / "public_laws",
        Path.cwd()
        / "tests"
        / "fixtures"
        / "legal_data"
        / "patent_authorities"
        / "public_laws",
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
    raw_formats: Any,
    *,
    package_id: str,
) -> dict[str, FormatArtifact]:
    out: dict[str, FormatArtifact] = {}
    if not raw_formats:
        return out
    if not isinstance(raw_formats, Mapping):
        raise FixtureSchemaError("formats must be a mapping")
    for key, raw in raw_formats.items():
        if isinstance(raw, FormatArtifact):
            art = raw
        elif isinstance(raw, Mapping):
            payload = dict(raw)
            payload.setdefault("format", key)
            payload.setdefault("upstream_package_id", package_id)
            if "source_url" not in payload:
                fmt = SourceFormat.coerce(payload.get("format", key))
                payload["source_url"] = (
                    f"{GOVINFO_CONTENT_BASE}/{package_id}/{fmt.value}/"
                    f"{package_id}.{fmt.value}"
                )
            if "artifact_sha256" not in payload:
                payload["artifact_sha256"] = content_sha256(
                    f"{package_id}|{key}|{payload.get('source_url')}"
                )
            art = FormatArtifact.from_dict(payload)
        else:
            raise FixtureSchemaError(f"format {key!r} must be a mapping")
        out[art.format.value] = art
    return out


def _build_authority_source(record: PublicLawRecord) -> AuthoritySourceRecord:
    preferred = record.preferred_format()
    official = record.official_artifact
    if official is None and preferred is not None:
        official = preferred.to_artifact_identity(
            provider=DEFAULT_PROVIDER,
            source_id=f"govinfo:{record.package_id}:{preferred.format.value}",
            role=IdentityRole.OFFICIAL_ARTIFACT,
        )
    derived = None
    if record.cross_checks:
        first = record.cross_checks[0]
        derived = first.derived_presentation
    return AuthoritySourceRecord(
        source_key=f"plaw:{record.package_id}",
        authority_tier=AuthorityTier.OFFICIAL_CHANGE,
        collection=COLLECTION_PLAW,
        jurisdiction=DEFAULT_JURISDICTION,
        title=None,
        citation=record.citation,
        edition=f"plaw-{record.congress}-{record.law_number}",
        version=record.package_id,
        date_issued=record.date_enacted,
        publication_date=record.date_approved or record.date_enacted,
        official_artifact=official,
        derived_presentation=derived,
        receipt=record.receipt,
        verification_state=record.verification_state,
        notes=(
            "Official GovInfo Public Law package; House/eCFR/FR.gov views "
            "remain cross-check-only when present."
        ),
        metadata={
            "patent_relevant": record.patent_relevant,
            "stable_id": record.stable_id,
            "authority_schema": AUTHORITY_SCHEMA_VERSION,
            "processor_schema": SCHEMA_VERSION,
        },
    )


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class PublicLawChangeProcessor:
    """Acquire Public Law packages and retain a full examination manifest.

    Primary path is fixture replay. Every examined Public Law remains in the
    manifest regardless of patent relevance.
    """

    def __init__(
        self,
        *,
        fixture_dir: PathLike | None = None,
        retry_cache_policy: RetryCachePolicy | None = None,
        registry: AuthoritySourceRegistry | None = None,
    ) -> None:
        self.fixture_dir = Path(fixture_dir) if fixture_dir else default_fixture_dir()
        self.retry_cache_policy = retry_cache_policy or RetryCachePolicy()
        self.registry = registry or AuthoritySourceRegistry()
        self._acquisitions: list[PublicLawAcquisition] = []

    def load_fixture_payload(self, path: PathLike | None = None) -> dict[str, Any]:
        target = Path(path) if path is not None else self._default_recipe_path()
        if target.is_dir():
            for name in (
                "public_laws_recipe.json",
                "public_law_change_recipe.json",
            ):
                candidate = target / name
                if candidate.is_file():
                    target = candidate
                    break
            else:
                raise FixtureSchemaError(
                    f"fixture directory {target} lacks public_laws_recipe.json"
                )
        payload = load_json_fixture(target)
        schema = payload.get("schema_version")
        if schema and not (
            str(schema).startswith("public-law")
            or str(schema).startswith("plaw")
            or schema in {FIXTURE_SCHEMA_VERSION, SCHEMA_VERSION}
        ):
            raise FixtureSchemaError(
                f"unsupported fixture schema_version {schema!r} in {target}"
            )
        return payload

    def _default_recipe_path(self) -> Path:
        for name in ("public_laws_recipe.json", "public_law_change_recipe.json"):
            recipe = self.fixture_dir / name
            if recipe.is_file():
                return recipe
        return self.fixture_dir / "public_laws_recipe.json"

    def acquire_from_fixture(
        self,
        path: PathLike | None = None,
        *,
        register: bool = True,
    ) -> PublicLawAcquisition:
        payload = self.load_fixture_payload(path)
        return self.acquire_from_payload(payload, register=register)

    def acquire_from_payload(
        self,
        payload: JsonMapping,
        *,
        register: bool = True,
    ) -> PublicLawAcquisition:
        if not isinstance(payload, Mapping):
            raise FixtureSchemaError("payload must be a mapping")

        raw_laws = (
            payload.get("public_laws")
            or payload.get("laws")
            or payload.get("examined")
            or payload.get("records")
            or []
        )
        if isinstance(raw_laws, Mapping):
            iterable: Sequence[Any] = list(raw_laws.values())
        elif isinstance(raw_laws, Sequence) and not isinstance(raw_laws, (str, bytes)):
            iterable = raw_laws
        else:
            iterable = []

        examined: dict[str, PublicLawRecord] = {}
        authority_sources: list[AuthoritySourceRecord] = []

        for item in iterable:
            if not isinstance(item, Mapping):
                continue
            package_id = item.get("package_id")
            if not package_id and item.get("congress") is not None:
                package_id = govinfo_plaw_package_id(
                    congress=item["congress"],
                    law_number=item.get("law_number") or item.get("number"),
                )
            formats = _build_format_map(
                item.get("formats"),
                package_id=str(package_id or "PLAW-UNKNOWN"),
            )
            preferred = formats.get("pdf") or formats.get("xml") or (
                next(iter(formats.values())) if formats else None
            )
            official = item.get("official_artifact")
            if official is None and preferred is not None:
                official = preferred.to_artifact_identity(
                    provider=str(item.get("provider") or DEFAULT_PROVIDER),
                    source_id=f"govinfo:{package_id}:{preferred.format.value}",
                    role=IdentityRole.OFFICIAL_ARTIFACT,
                ).to_dict()

            receipt = None
            if item.get("receipt"):
                receipt = SourceReceipt.from_dict(item["receipt"])
            elif preferred is not None:
                receipt = SourceReceipt(
                    endpoint=preferred.source_url,
                    retrieved_at=item.get("retrieved_at")
                    or "2024-09-01T12:00:00Z",
                    response_status=200,
                    sanitized_request={"method": "GET", "path": preferred.source_url},
                    upstream_id=str(package_id),
                    content_sha256=preferred.artifact_sha256,
                    media_type=preferred.media_type,
                    metadata={"provider": DEFAULT_PROVIDER, "collection": COLLECTION_PLAW},
                )

            record_payload = dict(item)
            record_payload["formats"] = {k: v.to_dict() for k, v in formats.items()}
            if official is not None and "official_artifact" not in record_payload:
                record_payload["official_artifact"] = official
            if receipt is not None and "receipt" not in record_payload:
                record_payload["receipt"] = receipt.to_dict()
            if not record_payload.get("source_url") and preferred is not None:
                record_payload["source_url"] = preferred.source_url
            if not record_payload.get("content_sha256") and preferred is not None:
                record_payload["content_sha256"] = preferred.artifact_sha256

            record = PublicLawRecord.from_dict(record_payload)
            # Acceptance: every examined law stays in the manifest.
            examined[record.stable_id] = record
            auth = _build_authority_source(record)
            authority_sources.append(auth)
            if register:
                self.registry.register(auth, overwrite=True)
                if record.receipt is not None:
                    self.registry.attach_receipt(auth.source_key, record.receipt)

        if not examined:
            acquisition = PublicLawAcquisition(
                status=ResolutionStatus.UNKNOWN,
                manifest=PublicLawManifest(examined={}),
                notes=payload.get("notes") or "No Public Law packages examined.",
                unknown_reason="missing public law data",
                metadata={
                    "schema_version": payload.get("schema_version") or FIXTURE_SCHEMA_VERSION,
                    "fixture_id": payload.get("fixture_id"),
                },
            )
            self._acquisitions.append(acquisition)
            return acquisition

        manifest = PublicLawManifest(
            examined=examined,
            discovered_at=payload.get("discovered_at") or "2024-09-01T12:00:00Z",
            inventory_source=payload.get("inventory_source")
            or payload.get("fixture_id")
            or "fixture-inventory",
            notes=payload.get("notes"),
            metadata={
                "fixture_id": payload.get("fixture_id"),
                "schema_version": payload.get("schema_version") or FIXTURE_SCHEMA_VERSION,
            },
        )
        # Non-success statuses from fixture-level markers.
        status_raw = payload.get("status")
        if status_raw:
            status = ResolutionStatus(str(status_raw))
        else:
            status = ResolutionStatus.RESOLVED

        acquisition = PublicLawAcquisition(
            status=status,
            manifest=manifest,
            authority_sources=tuple(authority_sources),
            notes=payload.get("notes"),
            metadata={
                "schema_version": payload.get("schema_version") or FIXTURE_SCHEMA_VERSION,
                "fixture_id": payload.get("fixture_id"),
                "examined_count": manifest.total_examined,
                "patent_relevant_count": manifest.patent_relevant_count,
                "non_patent_count": manifest.non_patent_count,
            },
        )
        self._acquisitions.append(acquisition)
        return acquisition

    def examine_public_laws(
        self,
        laws: Sequence[JsonMapping | PublicLawRecord],
        *,
        register: bool = True,
        inventory_source: str = "runtime-examination",
    ) -> PublicLawAcquisition:
        """Examine an explicit list of Public Laws into a full manifest.

        Non-patent-relevant laws are retained. This is the runtime path used
        when inventory discovery yields a set of package ids.
        """

        reject_hard_coded_latest(inventory_source, field_name="inventory_source")
        payload_laws: list[dict[str, Any]] = []
        for item in laws:
            if isinstance(item, PublicLawRecord):
                payload_laws.append(item.to_dict())
            elif isinstance(item, Mapping):
                payload_laws.append(dict(item))
            else:
                raise PublicLawChangeError("laws entries must be mappings or PublicLawRecord")
        return self.acquire_from_payload(
            {
                "schema_version": FIXTURE_SCHEMA_VERSION,
                "fixture_id": inventory_source,
                "inventory_source": inventory_source,
                "discovered_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "public_laws": payload_laws,
                "notes": "Runtime examination manifest; every examined Public Law retained.",
            },
            register=register,
        )

    def get_latest_acquisition(self) -> Optional[PublicLawAcquisition]:
        if not self._acquisitions:
            return None
        return self._acquisitions[-1]


# ---------------------------------------------------------------------------
# Fixture generators
# ---------------------------------------------------------------------------


def _pl_formats(*, package_id: str, seed: str) -> dict[str, Any]:
    formats: dict[str, Any] = {}
    for fmt in (SourceFormat.PDF, SourceFormat.XML, SourceFormat.MODS, SourceFormat.PREMIS):
        formats[fmt.value] = {
            "format": fmt.value,
            "media_type": _media_type_for_format(fmt),
            "artifact_sha256": content_sha256(f"{seed}|{fmt.value}"),
            "source_url": (
                f"{GOVINFO_CONTENT_BASE}/{package_id}/{fmt.value}/"
                f"{package_id}.{fmt.value}"
            ),
            "byte_size": 5000 + (10 if fmt is SourceFormat.PDF else 0),
            "upstream_package_id": package_id,
            "role": IdentityRole.OFFICIAL_ARTIFACT.value,
        }
    return formats


def build_public_laws_fixture_recipe(
    *,
    fixture_id: str = "public-laws-examination-118",
) -> dict[str, Any]:
    """Compact deterministic Public Law examination recipe.

    Includes patent-relevant and non-patent Public Laws so the manifest
    acceptance criterion (retain all examined laws) is testable.
    """

    laws: list[dict[str, Any]] = []

    # Patent-relevant: Leahy-Smith America Invents Act style fixture.
    pkg_aia = govinfo_plaw_package_id(congress=112, law_number=29)
    laws.append(
        {
            "congress": "112",
            "law_number": "29",
            "package_id": pkg_aia,
            "citation": "Pub. L. 112-29",
            "title": "Leahy-Smith America Invents Act",
            "patent_relevant": True,
            "date_enacted": "2011-09-16",
            "subjects": ["patents", "USPTO", "inter partes review"],
            "affects_titles": ["35"],
            "text_excerpt": (
                "An Act to amend title 35, United States Code, to provide for "
                "patent reform."
            ),
            "source_spans": [
                {
                    "start": 0,
                    "end": 72,
                    "unit": "char",
                    "page_start": 1,
                    "page_end": 1,
                    "excerpt": "An Act to amend title 35, United States Code",
                    "format": "pdf",
                }
            ],
            "formats": _pl_formats(package_id=pkg_aia, seed=f"{pkg_aia}|aia"),
            "source_url": govinfo_plaw_package_url(pkg_aia),
            "content_sha256": content_sha256(f"{pkg_aia}|package"),
            "retrieved_at": "2024-09-01T12:00:00Z",
            "cross_checks": [
                {
                    "provider": "ushouse",
                    "role": "house_codification",
                    "source_url": "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title35",
                    "content_sha256": content_sha256("house|title35|crosscheck"),
                    "notes": "House OLRC codification view; cross-check only.",
                    "derived_presentation": {
                        "provider": "ushouse",
                        "source_id": "ushouse:title35:crosscheck-pl112-29",
                        "artifact_sha256": content_sha256("house|title35|crosscheck"),
                        "source_url": "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title35",
                        "media_type": "text/html",
                        "role": IdentityRole.DERIVED_PRESENTATION.value,
                    },
                }
            ],
            "verification_state": VerificationState.UNVERIFIED.value,
        }
    )

    # Patent-relevant modern fee adjustment.
    pkg_fee = govinfo_plaw_package_id(congress=118, law_number=45)
    laws.append(
        {
            "congress": "118",
            "law_number": "45",
            "package_id": pkg_fee,
            "citation": "Pub. L. 118-45",
            "title": "Unleashing American Innovators Act of 2022 (fixture)",
            "patent_relevant": True,
            "date_enacted": "2022-12-29",
            "subjects": ["patent fees", "USPTO"],
            "affects_titles": ["35"],
            "text_excerpt": (
                "Adjustments to patent fees and small entity definitions under "
                "title 35, United States Code."
            ),
            "source_spans": [
                {
                    "start": 0,
                    "end": 80,
                    "unit": "char",
                    "page_start": 1,
                    "page_end": 1,
                    "excerpt": "Adjustments to patent fees and small entity definitions",
                    "format": "xml",
                }
            ],
            "formats": _pl_formats(package_id=pkg_fee, seed=f"{pkg_fee}|fee"),
            "source_url": govinfo_plaw_package_url(pkg_fee),
            "content_sha256": content_sha256(f"{pkg_fee}|package"),
            "retrieved_at": "2024-09-01T12:05:00Z",
            "verification_state": VerificationState.UNVERIFIED.value,
        }
    )

    # Non-patent: infrastructure — must remain in the examination manifest.
    pkg_infra = govinfo_plaw_package_id(congress=117, law_number=58)
    laws.append(
        {
            "congress": "117",
            "law_number": "58",
            "package_id": pkg_infra,
            "citation": "Pub. L. 117-58",
            "title": "Infrastructure Investment and Jobs Act",
            "patent_relevant": False,
            "date_enacted": "2021-11-15",
            "subjects": ["infrastructure", "transportation", "broadband"],
            "affects_titles": ["23", "49"],
            "text_excerpt": (
                "An Act to authorize funds for Federal-aid highways, highway "
                "safety programs, and transit programs."
            ),
            "source_spans": [
                {
                    "start": 0,
                    "end": 90,
                    "unit": "char",
                    "page_start": 1,
                    "page_end": 1,
                    "excerpt": "An Act to authorize funds for Federal-aid highways",
                    "format": "pdf",
                }
            ],
            "formats": _pl_formats(package_id=pkg_infra, seed=f"{pkg_infra}|infra"),
            "source_url": govinfo_plaw_package_url(pkg_infra),
            "content_sha256": content_sha256(f"{pkg_infra}|package"),
            "retrieved_at": "2024-09-01T12:10:00Z",
            "cross_checks": [
                {
                    "provider": "federalregister.gov",
                    "role": "federal_register_discovery",
                    "source_url": "https://www.federalregister.gov/documents/search?conditions%5Bterm%5D=117-58",
                    "content_sha256": content_sha256("fr.gov|pl117-58|discovery"),
                    "notes": "FederalRegister.gov discovery; cross-check only.",
                    "derived_presentation": {
                        "provider": "federalregister.gov",
                        "source_id": "fr.gov:discovery:pl117-58",
                        "artifact_sha256": content_sha256("fr.gov|pl117-58|discovery"),
                        "source_url": "https://www.federalregister.gov/documents/search?conditions%5Bterm%5D=117-58",
                        "media_type": "application/json",
                        "role": IdentityRole.DERIVED_PRESENTATION.value,
                    },
                }
            ],
            "verification_state": VerificationState.UNVERIFIED.value,
        }
    )

    # Non-patent: appropriations — also retained.
    pkg_approps = govinfo_plaw_package_id(congress=118, law_number=47)
    laws.append(
        {
            "congress": "118",
            "law_number": "47",
            "package_id": pkg_approps,
            "citation": "Pub. L. 118-47",
            "title": "Further Consolidated Appropriations Act, 2024 (fixture)",
            "patent_relevant": False,
            "date_enacted": "2024-03-23",
            "subjects": ["appropriations", "budget"],
            "affects_titles": [],
            "text_excerpt": (
                "Making further consolidated appropriations for the fiscal year "
                "ending September 30, 2024."
            ),
            "formats": _pl_formats(package_id=pkg_approps, seed=f"{pkg_approps}|approps"),
            "source_url": govinfo_plaw_package_url(pkg_approps),
            "content_sha256": content_sha256(f"{pkg_approps}|package"),
            "retrieved_at": "2024-09-01T12:15:00Z",
            "verification_state": VerificationState.UNVERIFIED.value,
        }
    )

    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "fixture_id": fixture_id,
        "inventory_source": "fixture-runtime-inventory-v1",
        "discovered_at": "2024-09-01T12:00:00Z",
        "notes": (
            "Compact Public Law examination recipe. Patent-relevant and "
            "non-patent laws are both examined; the manifest retains every "
            "examined Public Law. House/eCFR/FederalRegister.gov views are "
            "cross-check-only."
        ),
        "public_laws": laws,
    }


def write_default_fixtures(directory: PathLike | None = None) -> Path:
    """Materialize default Public Law fixtures under *directory*."""

    root = Path(directory) if directory is not None else default_fixture_dir()
    root.mkdir(parents=True, exist_ok=True)

    recipe = build_public_laws_fixture_recipe()
    recipe_path = root / "public_laws_recipe.json"
    recipe_path.write_text(
        json.dumps(recipe, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Missing-package case for unknown / incomplete inventory tests.
    missing = {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "fixture_id": "public-laws-missing",
        "inventory_source": "empty-inventory",
        "notes": "No Public Law packages present; acquisition is unknown.",
        "public_laws": [],
        "status": ResolutionStatus.UNKNOWN.value,
    }
    (root / "public_laws_missing.json").write_text(
        json.dumps(missing, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Public Law examination fixtures\n\n"
            "Compact recipes for PATLAW-018. Prefer `public_laws_recipe.json` "
            "over bulk golden dumps. Every examined Public Law remains in the "
            "manifest even when not patent-relevant. House/eCFR/"
            "FederalRegister.gov views are cross-check-only.\n",
            encoding="utf-8",
        )
    return root


__all__ = [
    "COLLECTION_PLAW",
    "COLLECTION_STATUTE",
    "CROSS_CHECK_PROVIDERS",
    "DEFAULT_JURISDICTION",
    "DEFAULT_PROVIDER",
    "FIXTURE_SCHEMA_VERSION",
    "GOVINFO_API_BASE",
    "GOVINFO_CONTENT_BASE",
    "SCHEMA_VERSION",
    "CrossCheckMasqueradeError",
    "CrossCheckRole",
    "CrossCheckView",
    "FixtureSchemaError",
    "FormatArtifact",
    "MissingPackageError",
    "PublicLawAcquisition",
    "PublicLawChangeError",
    "PublicLawChangeProcessor",
    "PublicLawManifest",
    "PublicLawNotFoundError",
    "PublicLawRecord",
    "ResolutionStatus",
    "SourceFormat",
    "SourceSpan",
    "assert_cross_check_only",
    "build_public_laws_fixture_recipe",
    "classify_patent_relevance",
    "content_sha256",
    "default_fixture_dir",
    "govinfo_plaw_package_id",
    "govinfo_plaw_package_url",
    "load_json_fixture",
    "normalize_congress",
    "normalize_law_number",
    "normalize_plaw_package_id",
    "parse_public_law_number",
    "stable_public_law_identity",
    "write_default_fixtures",
]
