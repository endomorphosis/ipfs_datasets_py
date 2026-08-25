"""All-title official-source authority contract (USCIR-004).

Generalizes the exact release-point, checksum, exclusion, receipt, and
currentness-disclaimer contracts used by the Title 35 processor to every
U.S. Code title in the sealed baseline span (Titles 1–52 and 54; 53 titles).

Design invariants
-----------------
* ``proposed_latest`` discovery may surface a candidate release but **cannot**
  be the final provenance value for any admitted package.
* An ``approved_exact`` release point is required for corpus admission.
* Every title package records official source URL, package/granule id,
  content checksum, acquisition time, and verification result.
* Unapproved mixed vintages fail closed.
* Resume receipts are deterministic (canonical JSON + SHA-256) so a verified
  package is never redownloaded on checkpoint resume.
* Publication / acquisition timestamps are **not** legal-currentness claims.
* Live network I/O is out of scope here; unit tests use sealed fixtures only.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Optional, Sequence, Union

from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    HardCodedLatestEditionError,
    reject_hard_coded_latest,
)

SCHEMA_VERSION = "uscode-source-policy-v1"
FIXTURE_SCHEMA_VERSION = "uscode-release-receipts-v1"

# Sealed baseline span: Titles 1 through 52 and 54 (Title 53 reserved/unused).
CANONICAL_USCODE_TITLE_NUMBERS: tuple[int, ...] = tuple(range(1, 53)) + (54,)
CANONICAL_USCODE_TITLES: tuple[str, ...] = tuple(
    str(n) for n in CANONICAL_USCODE_TITLE_NUMBERS
)
EXPECTED_TITLE_COUNT = 53

DEFAULT_JURISDICTION = "US"
DEFAULT_PROVIDER_OLRC = "olrc_house"
DEFAULT_PROVIDER_GOVINFO = "govinfo"

USHOUSE_DOWNLOAD_PAGE = "https://uscode.house.gov/download/download.shtml"
USHOUSE_RELEASEPOINT_BASE = "https://uscode.house.gov/download/releasepoints"
GOVINFO_CONTENT_BASE = "https://www.govinfo.gov/content/pkg"

CURRENTNESS_DISCLAIMER = (
    "Acquisition and publication timestamps record when a package was "
    "retrieved or sealed; they are not a claim that the codified text is "
    "legally current as of wall-clock time. Retrieval output is a research "
    "aid and is not a substitute for the official source."
)

# Compact fixture defaults (deterministic seeds, no network).
DEFAULT_APPROVED_RELEASE_POINT = "us/pl/118/45"
DEFAULT_APPROVED_CONGRESS = "118"
DEFAULT_APPROVED_RELEASE = "45"
DEFAULT_APPROVED_BY = "uscir-004-fixture-seal"
DEFAULT_APPROVED_AT = "2024-09-20T12:00:00Z"
DEFAULT_DISCOVERED_AT = "2024-09-18T09:30:00Z"
DEFAULT_ACQUIRED_AT = "2024-09-20T12:05:00Z"

_RELEASE_POINT_RE = re.compile(
    r"(?:us/pl/)?(?P<congress>\d+)(?:[/\-])(?P<release>[A-Za-z0-9]+)",
    re.IGNORECASE,
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LATEST_TOKEN_RE = re.compile(r"^\s*latest\s*$", re.IGNORECASE)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UscodeSourcePolicyError(ValueError):
    """Base error for official-source authority contract failures."""


class UnapprovedProposedReleaseError(UscodeSourcePolicyError):
    """Raised when a proposed-latest discovery is used as final provenance."""


class UnapprovedMixedVintageError(UscodeSourcePolicyError):
    """Raised when titles disagree on release point without explicit approval."""


class MissingApprovedReleaseError(UscodeSourcePolicyError):
    """Raised when admission is attempted without an approved exact release."""


class TitleProvenanceError(UscodeSourcePolicyError):
    """Raised when per-title provenance is incomplete or inconsistent."""


class ResumeReceiptError(UscodeSourcePolicyError):
    """Raised when a resume receipt is malformed or non-deterministic."""


class FixtureSchemaError(UscodeSourcePolicyError):
    """Raised when the sealed release-receipts fixture is malformed."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ReleasePointRole(str, Enum):
    """Whether a release identity is discovery-only or admission-ready."""

    PROPOSED_LATEST = "proposed_latest"
    APPROVED_EXACT = "approved_exact"


class SourceProvider(str, Enum):
    """Official U.S. Code package providers."""

    OLRC_HOUSE = "olrc_house"
    GOVINFO = "govinfo"
    USHOUSE = "ushouse"  # alias accepted for Title 35 processor compatibility

    @classmethod
    def coerce(cls, value: Any) -> "SourceProvider":
        if isinstance(value, SourceProvider):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "olrc_house": cls.OLRC_HOUSE,
            "olrc": cls.OLRC_HOUSE,
            "house": cls.OLRC_HOUSE,
            "house_olrc": cls.OLRC_HOUSE,
            "ushouse": cls.USHOUSE,
            "uscode.house.gov": cls.OLRC_HOUSE,
            "govinfo": cls.GOVINFO,
            "gpo": cls.GOVINFO,
            "www.govinfo.gov": cls.GOVINFO,
        }
        if text not in aliases:
            raise UscodeSourcePolicyError(f"unsupported source provider: {value!r}")
        return aliases[text]

    def canonical(self) -> "SourceProvider":
        """Collapse compatibility aliases onto the policy-canonical provider."""

        if self is SourceProvider.USHOUSE:
            return SourceProvider.OLRC_HOUSE
        return self


class TitlePackageStatus(str, Enum):
    """Lifecycle status of one title package under an approved release."""

    PENDING = "pending"
    ACQUIRED = "acquired"
    VERIFIED = "verified"
    EXCLUDED = "excluded"
    FAILED = "failed"
    SKIPPED = "skipped"

    @classmethod
    def coerce(cls, value: Any) -> "TitlePackageStatus":
        if isinstance(value, TitlePackageStatus):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        for status in cls:
            if status.value == text or status.name.lower() == text:
                return status
        raise UscodeSourcePolicyError(f"unknown title package status: {value!r}")


class VerificationResult(str, Enum):
    """Checksum / identity verification outcome for one title package."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    CONFLICT = "conflict"
    MISSING = "missing"
    FAILED = "failed"

    @classmethod
    def coerce(cls, value: Any) -> "VerificationResult":
        if isinstance(value, VerificationResult):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        for result in cls:
            if result.value == text or result.name.lower() == text:
                return result
        raise UscodeSourcePolicyError(f"unknown verification result: {value!r}")


class ExclusionKind(str, Enum):
    """Kinds of title-level or package-level exclusions."""

    UNCODIFIED_SLIP_LAW = "uncodified_slip_law"
    CLASSIFICATION_GAP = "classification_gap"
    POSITIVE_LAW_PENDING = "positive_law_pending"
    TITLE_RESERVED = "title_reserved"
    PACKAGE_UNAVAILABLE = "package_unavailable"
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


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UscodeSourcePolicyError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise UscodeSourcePolicyError(f"{name} must not contain NUL")
    return value.strip()


def _optional_str(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, "value")


def _require_sha256(value: Any, name: str = "content_sha256") -> str:
    text = _require_non_empty_str(value, name).lower()
    if not _SHA256_RE.fullmatch(text):
        raise UscodeSourcePolicyError(f"{name} must be a lowercase 64-char hex SHA-256")
    return text


def _parse_utc(value: Any, *, name: str = "timestamp") -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise UscodeSourcePolicyError(f"{name} must be ISO-8601 datetime") from exc
    else:
        raise UscodeSourcePolicyError(f"{name} must be a datetime or ISO-8601 string")
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


def _deep_sorted(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(k): _deep_sorted(value[k]) for k in sorted(value.keys(), key=lambda x: str(x))
        }
    if isinstance(value, (list, tuple)):
        return [_deep_sorted(v) for v in value]
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


def normalize_title(title: Any) -> str:
    """Normalize a U.S. Code title number (``\"35\"``, ``\"10a\"``)."""

    text = str(title if title is not None else "").strip()
    if not text:
        raise UscodeSourcePolicyError("title must be non-empty")
    if text.isdigit():
        return str(int(text))
    return text.lower()


def is_canonical_title(title: Any) -> bool:
    """Return True when *title* is one of the 53 sealed baseline titles."""

    try:
        return normalize_title(title) in CANONICAL_USCODE_TITLES
    except UscodeSourcePolicyError:
        return False


def require_canonical_title(title: Any) -> str:
    """Normalize and require a sealed-baseline title number."""

    normalized = normalize_title(title)
    if normalized not in CANONICAL_USCODE_TITLES:
        raise UscodeSourcePolicyError(
            f"title {title!r} is outside the sealed baseline span "
            f"(expected one of Titles 1–52 and 54; got {normalized!r})"
        )
    return normalized


def ushouse_title_code(title: Any) -> str:
    """Return the two-digit (or lettered) House OLRC title code."""

    text = normalize_title(title)
    if text.isdigit():
        return f"{int(text):02d}"
    return text.lower()


def parse_release_point_id(value: Any) -> tuple[str, str, str]:
    """Parse a release-point token into ``(canonical_id, congress, release)``.

    Accepts ``us/pl/118/45``, ``118-45``, ``118/45``. Rejects ``latest``.
    """

    text = _require_non_empty_str(value, "release_point")
    reject_hard_coded_latest(text, field_name="release_point")
    if _LATEST_TOKEN_RE.fullmatch(text):
        raise HardCodedLatestEditionError(
            "release_point must not use the hard-coded token 'latest'"
        )
    match = _RELEASE_POINT_RE.fullmatch(text.replace(" ", ""))
    if not match:
        match = _RELEASE_POINT_RE.search(text)
    if not match:
        raise UscodeSourcePolicyError(f"unrecognized release_point: {value!r}")
    congress = str(int(match.group("congress")))
    release = str(match.group("release")).strip()
    if not release or release.lower() == "latest":
        raise HardCodedLatestEditionError(
            "release_point must not use the hard-coded token 'latest'"
        )
    canonical = f"us/pl/{congress}/{release}"
    return canonical, congress, release


def ushouse_releasepoint_zip_url(
    *,
    congress: Any,
    release: Any,
    title: Any,
    format_kind: str = "xml",
) -> str:
    """Build a House OLRC release-point zip URL for one title package."""

    _, congress_s, release_s = parse_release_point_id(f"{congress}/{release}")
    code = ushouse_title_code(title)
    fmt = str(format_kind or "xml").strip().lower()
    prefix = {
        "html": "htm",
        "htm": "htm",
        "xml": "xml",
        "uslm": "xml",
        "pdf": "pdf",
        "zip": "htm",
    }.get(fmt, "xml")
    return (
        f"{USHOUSE_RELEASEPOINT_BASE}/us/pl/{congress_s}/{release_s}/"
        f"{prefix}_usc{code}@{congress_s}-{release_s}.zip"
    )


def govinfo_title_package_id(*, year: Any, title: Any) -> str:
    """Return a concrete GovInfo USCODE package id (never ``latest``)."""

    year_s = _require_non_empty_str(str(year), "year")
    reject_hard_coded_latest(year_s, field_name="year")
    if not year_s.isdigit():
        raise UscodeSourcePolicyError(f"year must be numeric, got {year!r}")
    title_n = normalize_title(title)
    return f"USCODE-{year_s}-title{title_n}"


def govinfo_title_zip_url(*, year: Any, title: Any) -> str:
    package = govinfo_title_package_id(year=year, title=title)
    return f"{GOVINFO_CONTENT_BASE}/{package}/zip/{package}.zip"


def title_package_seed(
    *,
    release_point: str,
    title: Any,
    provider: SourceProvider | str = SourceProvider.OLRC_HOUSE,
) -> str:
    """Deterministic content seed used for fixture checksums."""

    provider_n = SourceProvider.coerce(provider).canonical().value
    title_n = normalize_title(title)
    return f"{provider_n}|{release_point}|title-{title_n}|package"


def expected_title_package_sha256(
    *,
    release_point: str,
    title: Any,
    provider: SourceProvider | str = SourceProvider.OLRC_HOUSE,
) -> str:
    """Return the deterministic fixture checksum for a title package."""

    return content_sha256(
        title_package_seed(release_point=release_point, title=title, provider=provider)
    )


# ---------------------------------------------------------------------------
# Release point records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProposedReleasePoint:
    """Discovery-only candidate from a ``latest`` endpoint or catalog scrape.

    A proposed release **must not** be written as final provenance. Call
    :meth:`UscodeSourcePolicy.approve_exact_release` to promote it.
    """

    release_point: str
    provider: SourceProvider
    discovered_at: datetime
    discovery_source: str
    congress: Optional[str] = None
    release: Optional[str] = None
    edition: Optional[str] = None
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    role: ReleasePointRole = ReleasePointRole.PROPOSED_LATEST

    def __post_init__(self) -> None:
        canonical, congress, release = parse_release_point_id(self.release_point)
        object.__setattr__(self, "release_point", canonical)
        object.__setattr__(self, "provider", SourceProvider.coerce(self.provider).canonical())
        object.__setattr__(
            self, "discovered_at", _parse_utc(self.discovered_at, name="discovered_at")
        )
        object.__setattr__(
            self,
            "discovery_source",
            _require_non_empty_str(self.discovery_source, "discovery_source"),
        )
        object.__setattr__(self, "congress", congress if self.congress is None else str(int(str(self.congress))))
        object.__setattr__(
            self,
            "release",
            release if self.release is None else _require_non_empty_str(str(self.release), "release"),
        )
        reject_hard_coded_latest(self.release, field_name="release")
        if self.edition is not None:
            ed = _require_non_empty_str(self.edition, "edition")
            reject_hard_coded_latest(ed, field_name="edition")
            object.__setattr__(self, "edition", ed)
        if self.notes is not None:
            object.__setattr__(self, "notes", _require_non_empty_str(self.notes, "notes"))
        object.__setattr__(self, "role", ReleasePointRole.PROPOSED_LATEST)
        if not isinstance(self.metadata, Mapping):
            raise UscodeSourcePolicyError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "congress": self.congress,
            "discovered_at": _format_utc(self.discovered_at),
            "discovery_source": self.discovery_source,
            "edition": self.edition,
            "metadata": _deep_sorted(self.metadata),
            "notes": self.notes,
            "provider": self.provider.value,
            "release": self.release,
            "release_point": self.release_point,
            "role": self.role.value,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "ProposedReleasePoint":
        if not isinstance(value, Mapping):
            raise UscodeSourcePolicyError("proposed release point must be a mapping")
        return cls(
            release_point=str(value.get("release_point") or value.get("value")),
            provider=SourceProvider.coerce(value.get("provider") or DEFAULT_PROVIDER_OLRC),
            discovered_at=value.get("discovered_at") or DEFAULT_DISCOVERED_AT,
            discovery_source=str(
                value.get("discovery_source") or value.get("source") or USHOUSE_DOWNLOAD_PAGE
            ),
            congress=value.get("congress"),
            release=value.get("release"),
            edition=value.get("edition"),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class ApprovedReleasePoint:
    """Exact release identity approved for all-title corpus admission.

    The hard-coded token ``latest`` is never admissible. Approval identity
    (``approved_by`` / ``approved_at``) is mandatory so discovery alone cannot
    mint a release.
    """

    release_point: str
    provider: SourceProvider
    approved_by: str
    approved_at: datetime
    congress: Optional[str] = None
    release: Optional[str] = None
    edition: Optional[str] = None
    year: Optional[str] = None
    govinfo_package_prefix: Optional[str] = None
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    role: ReleasePointRole = ReleasePointRole.APPROVED_EXACT

    def __post_init__(self) -> None:
        # GovInfo annual packages use package ids rather than us/pl paths.
        raw_point = _require_non_empty_str(self.release_point, "release_point")
        reject_hard_coded_latest(raw_point, field_name="release_point")
        if raw_point.upper().startswith("USCODE-"):
            object.__setattr__(self, "release_point", raw_point)
            if self.year is None:
                # USCODE-2023-title35 → year 2023
                parts = raw_point.split("-")
                if len(parts) >= 2 and parts[1].isdigit():
                    object.__setattr__(self, "year", parts[1])
        else:
            canonical, congress, release = parse_release_point_id(raw_point)
            object.__setattr__(self, "release_point", canonical)
            object.__setattr__(
                self,
                "congress",
                congress if self.congress is None else str(int(str(self.congress))),
            )
            object.__setattr__(
                self,
                "release",
                release
                if self.release is None
                else _require_non_empty_str(str(self.release), "release"),
            )
            reject_hard_coded_latest(self.release, field_name="release")

        object.__setattr__(self, "provider", SourceProvider.coerce(self.provider).canonical())
        object.__setattr__(
            self, "approved_by", _require_non_empty_str(self.approved_by, "approved_by")
        )
        object.__setattr__(
            self, "approved_at", _parse_utc(self.approved_at, name="approved_at")
        )
        if self.edition is not None:
            ed = _require_non_empty_str(self.edition, "edition")
            reject_hard_coded_latest(ed, field_name="edition")
            object.__setattr__(self, "edition", ed)
        if self.year is not None:
            year_s = _require_non_empty_str(str(self.year), "year")
            reject_hard_coded_latest(year_s, field_name="year")
            object.__setattr__(self, "year", year_s)
        if self.govinfo_package_prefix is not None:
            prefix = _require_non_empty_str(
                self.govinfo_package_prefix, "govinfo_package_prefix"
            )
            reject_hard_coded_latest(prefix, field_name="govinfo_package_prefix")
            object.__setattr__(self, "govinfo_package_prefix", prefix)
        if self.notes is not None:
            object.__setattr__(self, "notes", _require_non_empty_str(self.notes, "notes"))
        object.__setattr__(self, "role", ReleasePointRole.APPROVED_EXACT)
        if not isinstance(self.metadata, Mapping):
            raise UscodeSourcePolicyError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def canonical_id(self) -> str:
        return self.release_point

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved_at": _format_utc(self.approved_at),
            "approved_by": self.approved_by,
            "congress": self.congress,
            "edition": self.edition,
            "govinfo_package_prefix": self.govinfo_package_prefix,
            "metadata": _deep_sorted(self.metadata),
            "notes": self.notes,
            "provider": self.provider.value,
            "release": self.release,
            "release_point": self.release_point,
            "role": self.role.value,
            "year": self.year,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "ApprovedReleasePoint":
        if not isinstance(value, Mapping):
            raise UscodeSourcePolicyError("approved release point must be a mapping")
        release_point = value.get("release_point")
        if not release_point and value.get("congress") is not None and value.get("release") is not None:
            release_point, _, _ = parse_release_point_id(
                f"{value.get('congress')}/{value.get('release')}"
            )
        if not release_point:
            raise MissingApprovedReleaseError(
                "approved release_point (or congress/release) is required"
            )
        approved_by = value.get("approved_by")
        approved_at = value.get("approved_at")
        if not approved_by or not approved_at:
            raise MissingApprovedReleaseError(
                "approved_by and approved_at are required for an approved exact release"
            )
        return cls(
            release_point=str(release_point),
            provider=SourceProvider.coerce(value.get("provider") or DEFAULT_PROVIDER_OLRC),
            approved_by=str(approved_by),
            approved_at=approved_at,
            congress=value.get("congress"),
            release=value.get("release"),
            edition=value.get("edition"),
            year=value.get("year"),
            govinfo_package_prefix=value.get("govinfo_package_prefix"),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )


def require_approved_exact(
    value: Any,
    *,
    field_name: str = "release_point",
) -> ApprovedReleasePoint:
    """Fail closed when *value* is proposed-latest or otherwise unapproved."""

    if isinstance(value, ApprovedReleasePoint):
        return value
    if isinstance(value, ProposedReleasePoint):
        raise UnapprovedProposedReleaseError(
            f"{field_name} is proposed_latest ({value.release_point!r}); "
            "approve an exact release point before recording final provenance"
        )
    if isinstance(value, Mapping):
        role = str(value.get("role") or "").strip().lower()
        if role == ReleasePointRole.PROPOSED_LATEST.value or role == "proposed":
            raise UnapprovedProposedReleaseError(
                f"{field_name} is proposed_latest; cannot use discovery as final provenance"
            )
        if role == ReleasePointRole.APPROVED_EXACT.value or (
            value.get("approved_by") and value.get("approved_at")
        ):
            return ApprovedReleasePoint.from_dict(value)
        raise MissingApprovedReleaseError(
            f"{field_name} mapping lacks approved_by/approved_at (role={role!r})"
        )
    raise MissingApprovedReleaseError(
        f"{field_name} must be an ApprovedReleasePoint, not {type(value).__name__}"
    )


# ---------------------------------------------------------------------------
# Per-title provenance and exclusions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TitleExclusion:
    """A recorded exclusion or classification gap for one title package."""

    kind: ExclusionKind
    title: str
    reason: str
    citation: Optional[str] = None
    public_law: Optional[str] = None
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", ExclusionKind.coerce(self.kind))
        object.__setattr__(self, "title", require_canonical_title(self.title))
        object.__setattr__(self, "reason", _require_non_empty_str(self.reason, "reason"))
        if self.citation is not None:
            object.__setattr__(
                self, "citation", _require_non_empty_str(self.citation, "citation")
            )
        if self.public_law is not None:
            object.__setattr__(
                self, "public_law", _require_non_empty_str(self.public_law, "public_law")
            )
        if self.notes is not None:
            object.__setattr__(self, "notes", _require_non_empty_str(self.notes, "notes"))
        if not isinstance(self.metadata, Mapping):
            raise UscodeSourcePolicyError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation": self.citation,
            "kind": self.kind.value,
            "metadata": _deep_sorted(self.metadata),
            "notes": self.notes,
            "public_law": self.public_law,
            "reason": self.reason,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "TitleExclusion":
        if not isinstance(value, Mapping):
            raise UscodeSourcePolicyError("exclusion must be a mapping")
        return cls(
            kind=ExclusionKind.coerce(value.get("kind") or ExclusionKind.OTHER),
            title=str(value.get("title") or "35"),
            reason=str(value.get("reason") or "exclusion"),
            citation=value.get("citation"),
            public_law=value.get("public_law"),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class TitlePackageProvenance:
    """Per-title official-source provenance bound to one release point."""

    title: str
    release_point: str
    provider: SourceProvider
    package_id: str
    source_url: str
    content_sha256: str
    acquired_at: datetime
    verification: VerificationResult
    status: TitlePackageStatus = TitlePackageStatus.VERIFIED
    media_type: str = "application/zip"
    byte_size: Optional[int] = None
    format_kind: str = "xml"
    exclusion: Optional[TitleExclusion] = None
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", require_canonical_title(self.title))
        # Allow govinfo package ids or us/pl release points.
        rp = _require_non_empty_str(self.release_point, "release_point")
        reject_hard_coded_latest(rp, field_name="release_point")
        if not rp.upper().startswith("USCODE-"):
            rp, _, _ = parse_release_point_id(rp)
        object.__setattr__(self, "release_point", rp)
        object.__setattr__(self, "provider", SourceProvider.coerce(self.provider).canonical())
        object.__setattr__(
            self, "package_id", _require_non_empty_str(self.package_id, "package_id")
        )
        reject_hard_coded_latest(self.package_id, field_name="package_id")
        object.__setattr__(
            self, "source_url", _require_non_empty_str(self.source_url, "source_url")
        )
        object.__setattr__(
            self, "content_sha256", _require_sha256(self.content_sha256, "content_sha256")
        )
        object.__setattr__(
            self, "acquired_at", _parse_utc(self.acquired_at, name="acquired_at")
        )
        object.__setattr__(self, "verification", VerificationResult.coerce(self.verification))
        object.__setattr__(self, "status", TitlePackageStatus.coerce(self.status))
        object.__setattr__(
            self, "media_type", _require_non_empty_str(self.media_type, "media_type")
        )
        if self.byte_size is not None and (
            not isinstance(self.byte_size, int) or self.byte_size < 0
        ):
            raise TitleProvenanceError("byte_size must be a non-negative int")
        object.__setattr__(
            self, "format_kind", _require_non_empty_str(self.format_kind, "format_kind").lower()
        )
        if self.exclusion is not None and not isinstance(self.exclusion, TitleExclusion):
            if isinstance(self.exclusion, Mapping):
                object.__setattr__(self, "exclusion", TitleExclusion.from_dict(self.exclusion))
            else:
                raise TitleProvenanceError("exclusion must be a TitleExclusion or mapping")
        if self.notes is not None:
            object.__setattr__(self, "notes", _require_non_empty_str(self.notes, "notes"))
        if not isinstance(self.metadata, Mapping):
            raise TitleProvenanceError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

        # Status / verification consistency.
        if self.status is TitlePackageStatus.EXCLUDED and self.exclusion is None:
            raise TitleProvenanceError(
                f"title {self.title} status=excluded requires an exclusion record"
            )
        if self.status is TitlePackageStatus.VERIFIED and self.verification is not VerificationResult.VERIFIED:
            raise TitleProvenanceError(
                f"title {self.title} status=verified requires verification=verified"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "acquired_at": _format_utc(self.acquired_at),
            "byte_size": self.byte_size,
            "content_sha256": self.content_sha256,
            "exclusion": None if self.exclusion is None else self.exclusion.to_dict(),
            "format_kind": self.format_kind,
            "media_type": self.media_type,
            "metadata": _deep_sorted(self.metadata),
            "notes": self.notes,
            "package_id": self.package_id,
            "provider": self.provider.value,
            "release_point": self.release_point,
            "source_url": self.source_url,
            "status": self.status.value,
            "title": self.title,
            "verification": self.verification.value,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "TitlePackageProvenance":
        if not isinstance(value, Mapping):
            raise TitleProvenanceError("title provenance must be a mapping")
        exclusion_raw = value.get("exclusion")
        return cls(
            title=str(value.get("title")),
            release_point=str(value.get("release_point")),
            provider=SourceProvider.coerce(value.get("provider") or DEFAULT_PROVIDER_OLRC),
            package_id=str(value.get("package_id") or value.get("upstream_package_id")),
            source_url=str(value.get("source_url")),
            content_sha256=str(value.get("content_sha256") or value.get("artifact_sha256")),
            acquired_at=value.get("acquired_at") or value.get("retrieved_at") or DEFAULT_ACQUIRED_AT,
            verification=VerificationResult.coerce(
                value.get("verification") or VerificationResult.UNVERIFIED
            ),
            status=TitlePackageStatus.coerce(
                value.get("status") or TitlePackageStatus.PENDING
            ),
            media_type=str(value.get("media_type") or "application/zip"),
            byte_size=value.get("byte_size"),
            format_kind=str(value.get("format_kind") or value.get("format") or "xml"),
            exclusion=exclusion_raw,
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )


# ---------------------------------------------------------------------------
# Resume receipts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TitleResumeReceipt:
    """Deterministic per-title acquisition checkpoint for resume.

    When ``status`` is ``verified`` and the on-disk checksum matches
    ``content_sha256``, acquisition must skip redownload.
    """

    title: str
    release_point: str
    package_id: str
    content_sha256: str
    status: TitlePackageStatus
    verification: VerificationResult
    source_url: str
    acquired_at: datetime
    checkpoint_seq: int
    provider: SourceProvider = SourceProvider.OLRC_HOUSE
    receipt_digest: Optional[str] = None
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", require_canonical_title(self.title))
        rp = _require_non_empty_str(self.release_point, "release_point")
        reject_hard_coded_latest(rp, field_name="release_point")
        if not rp.upper().startswith("USCODE-"):
            rp, _, _ = parse_release_point_id(rp)
        object.__setattr__(self, "release_point", rp)
        object.__setattr__(
            self, "package_id", _require_non_empty_str(self.package_id, "package_id")
        )
        reject_hard_coded_latest(self.package_id, field_name="package_id")
        object.__setattr__(
            self, "content_sha256", _require_sha256(self.content_sha256, "content_sha256")
        )
        object.__setattr__(self, "status", TitlePackageStatus.coerce(self.status))
        object.__setattr__(self, "verification", VerificationResult.coerce(self.verification))
        object.__setattr__(
            self, "source_url", _require_non_empty_str(self.source_url, "source_url")
        )
        object.__setattr__(
            self, "acquired_at", _parse_utc(self.acquired_at, name="acquired_at")
        )
        if not isinstance(self.checkpoint_seq, int) or self.checkpoint_seq < 0:
            raise ResumeReceiptError("checkpoint_seq must be a non-negative int")
        object.__setattr__(self, "provider", SourceProvider.coerce(self.provider).canonical())
        if self.notes is not None:
            object.__setattr__(self, "notes", _require_non_empty_str(self.notes, "notes"))
        if not isinstance(self.metadata, Mapping):
            raise ResumeReceiptError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

        # Compute digest over the body without the digest field itself.
        body = self._body_dict()
        digest = digest_mapping(body)
        if self.receipt_digest is not None:
            expected = _require_sha256(self.receipt_digest, "receipt_digest")
            if expected != digest:
                raise ResumeReceiptError(
                    f"receipt_digest mismatch for title {self.title}: "
                    f"expected {digest}, got {expected}"
                )
        object.__setattr__(self, "receipt_digest", digest)

    def _body_dict(self) -> dict[str, Any]:
        return {
            "acquired_at": _format_utc(self.acquired_at),
            "checkpoint_seq": int(self.checkpoint_seq),
            "content_sha256": self.content_sha256,
            "metadata": _deep_sorted(self.metadata),
            "notes": self.notes,
            "package_id": self.package_id,
            "provider": self.provider.value,
            "release_point": self.release_point,
            "source_url": self.source_url,
            "status": self.status.value,
            "title": self.title,
            "verification": self.verification.value,
        }

    def to_dict(self) -> dict[str, Any]:
        body = self._body_dict()
        body["receipt_digest"] = self.receipt_digest
        return body

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "TitleResumeReceipt":
        if not isinstance(value, Mapping):
            raise ResumeReceiptError("resume receipt must be a mapping")
        return cls(
            title=str(value.get("title")),
            release_point=str(value.get("release_point")),
            package_id=str(value.get("package_id")),
            content_sha256=str(value.get("content_sha256")),
            status=TitlePackageStatus.coerce(
                value.get("status") or TitlePackageStatus.PENDING
            ),
            verification=VerificationResult.coerce(
                value.get("verification") or VerificationResult.UNVERIFIED
            ),
            source_url=str(value.get("source_url")),
            acquired_at=value.get("acquired_at") or DEFAULT_ACQUIRED_AT,
            checkpoint_seq=int(value.get("checkpoint_seq", 0)),
            provider=SourceProvider.coerce(value.get("provider") or DEFAULT_PROVIDER_OLRC),
            receipt_digest=value.get("receipt_digest"),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )

    @property
    def is_verified(self) -> bool:
        return (
            self.status is TitlePackageStatus.VERIFIED
            and self.verification is VerificationResult.VERIFIED
        )

    def should_skip_redownload(self, *, on_disk_sha256: Optional[str] = None) -> bool:
        """Return True when a verified receipt matches the on-disk checksum."""

        if not self.is_verified:
            return False
        if on_disk_sha256 is None:
            return True
        return _require_sha256(on_disk_sha256, "on_disk_sha256") == self.content_sha256


# ---------------------------------------------------------------------------
# All-title manifest
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AllTitleReleaseManifest:
    """Exact all-title release admission record.

    Binds one approved exact release point to per-title provenance and
    deterministic resume receipts. Mixed unapproved vintages are rejected at
    construction time.
    """

    approved_release: ApprovedReleasePoint
    titles: Mapping[str, TitlePackageProvenance]
    resume_receipts: Mapping[str, TitleResumeReceipt]
    proposed_release: Optional[ProposedReleasePoint] = None
    approved_mixed_overrides: Mapping[str, str] = field(default_factory=dict)
    currentness_disclaimer: str = CURRENTNESS_DISCLAIMER
    schema_version: str = SCHEMA_VERSION
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.approved_release, ApprovedReleasePoint):
            object.__setattr__(
                self, "approved_release", require_approved_exact(self.approved_release)
            )
        title_map: dict[str, TitlePackageProvenance] = {}
        for key, prov in (self.titles or {}).items():
            if isinstance(prov, TitlePackageProvenance):
                record = prov
            elif isinstance(prov, Mapping):
                record = TitlePackageProvenance.from_dict(prov)
            else:
                raise TitleProvenanceError("titles values must be mappings or records")
            title_map[record.title] = record
        object.__setattr__(self, "titles", title_map)

        receipt_map: dict[str, TitleResumeReceipt] = {}
        for key, receipt in (self.resume_receipts or {}).items():
            if isinstance(receipt, TitleResumeReceipt):
                record = receipt
            elif isinstance(receipt, Mapping):
                record = TitleResumeReceipt.from_dict(receipt)
            else:
                raise ResumeReceiptError("resume_receipts values must be mappings or records")
            receipt_map[record.title] = record
        object.__setattr__(self, "resume_receipts", receipt_map)

        if self.proposed_release is not None and not isinstance(
            self.proposed_release, ProposedReleasePoint
        ):
            if isinstance(self.proposed_release, Mapping):
                object.__setattr__(
                    self,
                    "proposed_release",
                    ProposedReleasePoint.from_dict(self.proposed_release),
                )
            else:
                raise UscodeSourcePolicyError(
                    "proposed_release must be a ProposedReleasePoint or mapping"
                )

        overrides: dict[str, str] = {}
        for title, alt_rp in (self.approved_mixed_overrides or {}).items():
            t = require_canonical_title(title)
            alt = _require_non_empty_str(str(alt_rp), "approved_mixed_overrides value")
            reject_hard_coded_latest(alt, field_name="approved_mixed_overrides")
            if not alt.upper().startswith("USCODE-"):
                alt, _, _ = parse_release_point_id(alt)
            overrides[t] = alt
        object.__setattr__(self, "approved_mixed_overrides", overrides)

        object.__setattr__(
            self,
            "currentness_disclaimer",
            _require_non_empty_str(self.currentness_disclaimer, "currentness_disclaimer"),
        )
        object.__setattr__(
            self, "schema_version", _require_non_empty_str(self.schema_version, "schema_version")
        )
        if self.notes is not None:
            object.__setattr__(self, "notes", _require_non_empty_str(self.notes, "notes"))
        if not isinstance(self.metadata, Mapping):
            raise UscodeSourcePolicyError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

        # Fail closed on unapproved mixed vintages.
        validate_no_unapproved_mixed_vintages(
            self.titles.values(),
            approved=self.approved_release,
            approved_mixed_overrides=self.approved_mixed_overrides,
        )

        # Resume receipts must agree with provenance when both present.
        for title, receipt in self.resume_receipts.items():
            prov = self.titles.get(title)
            if prov is None:
                continue
            if receipt.release_point != prov.release_point:
                raise ResumeReceiptError(
                    f"resume receipt release_point for title {title} disagrees "
                    f"with provenance ({receipt.release_point!r} vs {prov.release_point!r})"
                )
            if receipt.content_sha256 != prov.content_sha256 and prov.status is TitlePackageStatus.VERIFIED:
                raise ResumeReceiptError(
                    f"resume receipt checksum for title {title} disagrees with provenance"
                )

    @property
    def title_count(self) -> int:
        return len(self.titles)

    @property
    def verified_titles(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                t
                for t, p in self.titles.items()
                if p.status is TitlePackageStatus.VERIFIED
            )
        )

    def manifest_digest(self) -> str:
        return digest_mapping(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved_mixed_overrides": dict(
                sorted(self.approved_mixed_overrides.items(), key=lambda kv: kv[0])
            ),
            "approved_release": self.approved_release.to_dict(),
            "currentness_disclaimer": self.currentness_disclaimer,
            "metadata": _deep_sorted(self.metadata),
            "notes": self.notes,
            "proposed_release": (
                None if self.proposed_release is None else self.proposed_release.to_dict()
            ),
            "resume_receipts": {
                k: v.to_dict()
                for k, v in sorted(self.resume_receipts.items(), key=lambda kv: kv[0])
            },
            "schema_version": self.schema_version,
            "titles": {
                k: v.to_dict() for k, v in sorted(self.titles.items(), key=lambda kv: kv[0])
            },
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "AllTitleReleaseManifest":
        if not isinstance(value, Mapping):
            raise UscodeSourcePolicyError("manifest must be a mapping")
        approved_raw = value.get("approved_release") or value.get("approved")
        if approved_raw is None:
            raise MissingApprovedReleaseError("approved_release is required")
        return cls(
            approved_release=require_approved_exact(approved_raw),
            titles=value.get("titles") or {},
            resume_receipts=value.get("resume_receipts") or {},
            proposed_release=value.get("proposed_release"),
            approved_mixed_overrides=value.get("approved_mixed_overrides") or {},
            currentness_disclaimer=str(
                value.get("currentness_disclaimer") or CURRENTNESS_DISCLAIMER
            ),
            schema_version=str(value.get("schema_version") or SCHEMA_VERSION),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_no_unapproved_mixed_vintages(
    provenances: Iterable[TitlePackageProvenance],
    *,
    approved: ApprovedReleasePoint,
    approved_mixed_overrides: Optional[Mapping[str, str]] = None,
) -> None:
    """Reject title packages that do not share the approved release point.

    Per-title alternate release points are permitted only when listed in
    *approved_mixed_overrides* (title → alternate release_point). Unknown or
    unlisted disagreement fails closed.
    """

    approved = require_approved_exact(approved)
    overrides = {
        require_canonical_title(t): (
            parse_release_point_id(rp)[0]
            if not str(rp).upper().startswith("USCODE-")
            else str(rp)
        )
        for t, rp in (approved_mixed_overrides or {}).items()
    }
    mismatches: list[str] = []
    for prov in provenances:
        if not isinstance(prov, TitlePackageProvenance):
            raise TitleProvenanceError("provenance entries must be TitlePackageProvenance")
        expected = overrides.get(prov.title, approved.release_point)
        if prov.release_point != expected:
            mismatches.append(
                f"title {prov.title}: package release_point={prov.release_point!r} "
                f"expected={expected!r}"
            )
    if mismatches:
        raise UnapprovedMixedVintageError(
            "unapproved mixed vintages detected: " + "; ".join(mismatches)
        )


def titles_missing_from_manifest(
    manifest: AllTitleReleaseManifest,
    *,
    required: Sequence[str] = CANONICAL_USCODE_TITLES,
) -> tuple[str, ...]:
    """Return required titles absent from *manifest* (sorted)."""

    present = set(manifest.titles)
    return tuple(t for t in required if t not in present)


# ---------------------------------------------------------------------------
# Policy engine
# ---------------------------------------------------------------------------


class UscodeSourcePolicy:
    """Official-source authority contract for all U.S. Code titles.

    Distinguishes proposed-latest discovery from approved exact release points,
    records per-title provenance, rejects unapproved mixed vintages, and
    produces deterministic resume receipts.
    """

    def __init__(
        self,
        *,
        approved_release: Optional[ApprovedReleasePoint] = None,
        proposed_release: Optional[ProposedReleasePoint] = None,
        approved_mixed_overrides: Optional[Mapping[str, str]] = None,
        required_titles: Sequence[str] = CANONICAL_USCODE_TITLES,
    ) -> None:
        self._proposed: Optional[ProposedReleasePoint] = proposed_release
        self._approved: Optional[ApprovedReleasePoint] = (
            None if approved_release is None else require_approved_exact(approved_release)
        )
        self._overrides: dict[str, str] = {}
        if approved_mixed_overrides:
            for title, rp in approved_mixed_overrides.items():
                self.approve_mixed_override(title, rp)
        self._required_titles: tuple[str, ...] = tuple(
            require_canonical_title(t) for t in required_titles
        )
        self._provenances: dict[str, TitlePackageProvenance] = {}
        self._receipts: dict[str, TitleResumeReceipt] = {}
        self._checkpoint_seq = 0

    # -- discovery vs approval ---------------------------------------------

    @property
    def proposed_release(self) -> Optional[ProposedReleasePoint]:
        return self._proposed

    @property
    def approved_release(self) -> Optional[ApprovedReleasePoint]:
        return self._approved

    def propose_latest_from_discovery(
        self,
        *,
        release_point: Any,
        provider: SourceProvider | str = SourceProvider.OLRC_HOUSE,
        discovered_at: Any = DEFAULT_DISCOVERED_AT,
        discovery_source: str = USHOUSE_DOWNLOAD_PAGE,
        edition: Optional[str] = None,
        notes: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> ProposedReleasePoint:
        """Record a discovery-only proposed release (not final provenance)."""

        proposed = ProposedReleasePoint(
            release_point=str(release_point),
            provider=SourceProvider.coerce(provider),
            discovered_at=discovered_at,
            discovery_source=discovery_source,
            edition=edition,
            notes=notes
            or (
                "Discovery candidate from latest-style catalog scrape; "
                "not admissible as final provenance until approved."
            ),
            metadata=metadata or {},
        )
        self._proposed = proposed
        return proposed

    def approve_exact_release(
        self,
        release: Any,
        *,
        approved_by: str,
        approved_at: Any = DEFAULT_APPROVED_AT,
        provider: Optional[SourceProvider | str] = None,
        edition: Optional[str] = None,
        notes: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> ApprovedReleasePoint:
        """Promote a concrete release identity to approved exact.

        Accepts a :class:`ProposedReleasePoint`, release-point string, or
        mapping. The hard-coded token ``latest`` is always rejected.
        """

        if isinstance(release, ProposedReleasePoint):
            release_point = release.release_point
            provider_v = provider or release.provider
            congress = release.congress
            rel = release.release
            edition_v = edition or release.edition
            meta = dict(release.metadata)
            meta.setdefault("promoted_from", "proposed_latest")
            meta.setdefault("discovery_source", release.discovery_source)
            if metadata:
                meta.update(dict(metadata))
        elif isinstance(release, ApprovedReleasePoint):
            # Re-seal with new approver identity if supplied.
            release_point = release.release_point
            provider_v = provider or release.provider
            congress = release.congress
            rel = release.release
            edition_v = edition or release.edition
            meta = dict(release.metadata)
            if metadata:
                meta.update(dict(metadata))
        elif isinstance(release, Mapping):
            if str(release.get("role") or "").lower() == ReleasePointRole.PROPOSED_LATEST.value:
                proposed = ProposedReleasePoint.from_dict(release)
                return self.approve_exact_release(
                    proposed,
                    approved_by=approved_by,
                    approved_at=approved_at,
                    provider=provider,
                    edition=edition,
                    notes=notes,
                    metadata=metadata,
                )
            release_point = str(release.get("release_point") or release.get("value"))
            provider_v = provider or release.get("provider") or DEFAULT_PROVIDER_OLRC
            congress = release.get("congress")
            rel = release.get("release")
            edition_v = edition or release.get("edition")
            meta = dict(release.get("metadata") or {})
            if metadata:
                meta.update(dict(metadata))
        else:
            release_point = str(release)
            provider_v = provider or DEFAULT_PROVIDER_OLRC
            congress = None
            rel = None
            edition_v = edition
            meta = dict(metadata or {})

        reject_hard_coded_latest(release_point, field_name="release_point")
        approved = ApprovedReleasePoint(
            release_point=release_point,
            provider=SourceProvider.coerce(provider_v),
            approved_by=approved_by,
            approved_at=approved_at,
            congress=congress,
            release=rel,
            edition=edition_v,
            notes=notes,
            metadata=meta,
        )
        self._approved = approved
        return approved

    def require_approved(self) -> ApprovedReleasePoint:
        if self._approved is None:
            raise MissingApprovedReleaseError(
                "no approved exact release point; call approve_exact_release first"
            )
        return self._approved

    def approve_mixed_override(self, title: Any, alternate_release_point: Any) -> None:
        """Explicitly approve a different release point for one title.

        Without this call, any disagreement with the approved release fails
        closed as an unapproved mixed vintage.
        """

        t = require_canonical_title(title)
        alt = _require_non_empty_str(str(alternate_release_point), "alternate_release_point")
        reject_hard_coded_latest(alt, field_name="alternate_release_point")
        if not alt.upper().startswith("USCODE-"):
            alt, _, _ = parse_release_point_id(alt)
        self._overrides[t] = alt

    # -- per-title provenance ----------------------------------------------

    def expected_release_for_title(self, title: Any) -> str:
        approved = self.require_approved()
        t = require_canonical_title(title)
        return self._overrides.get(t, approved.release_point)

    def build_title_provenance(
        self,
        title: Any,
        *,
        content_sha256_value: Optional[str] = None,
        acquired_at: Any = DEFAULT_ACQUIRED_AT,
        verification: VerificationResult | str = VerificationResult.VERIFIED,
        status: TitlePackageStatus | str = TitlePackageStatus.VERIFIED,
        format_kind: str = "xml",
        byte_size: Optional[int] = None,
        exclusion: Optional[TitleExclusion | Mapping[str, Any]] = None,
        notes: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        source_url: Optional[str] = None,
        package_id: Optional[str] = None,
        release_point: Optional[str] = None,
        provider: Optional[SourceProvider | str] = None,
    ) -> TitlePackageProvenance:
        """Build provenance for one title under the approved release."""

        approved = self.require_approved()
        title_n = require_canonical_title(title)
        rp = release_point or self.expected_release_for_title(title_n)
        reject_hard_coded_latest(rp, field_name="release_point")
        if not str(rp).upper().startswith("USCODE-"):
            rp, congress, release = parse_release_point_id(rp)
        else:
            congress = approved.congress
            release = approved.release

        provider_v = SourceProvider.coerce(provider or approved.provider).canonical()
        if package_id is None:
            if provider_v is SourceProvider.GOVINFO and approved.year:
                package_id = govinfo_title_package_id(year=approved.year, title=title_n)
            else:
                package_id = rp
        if source_url is None:
            if provider_v is SourceProvider.GOVINFO and approved.year:
                source_url = govinfo_title_zip_url(year=approved.year, title=title_n)
            else:
                source_url = ushouse_releasepoint_zip_url(
                    congress=congress or approved.congress or DEFAULT_APPROVED_CONGRESS,
                    release=release or approved.release or DEFAULT_APPROVED_RELEASE,
                    title=title_n,
                    format_kind=format_kind,
                )
        checksum = content_sha256_value or expected_title_package_sha256(
            release_point=rp, title=title_n, provider=provider_v
        )
        excl: Optional[TitleExclusion]
        if exclusion is None:
            excl = None
        elif isinstance(exclusion, TitleExclusion):
            excl = exclusion
        else:
            excl = TitleExclusion.from_dict(exclusion)

        return TitlePackageProvenance(
            title=title_n,
            release_point=rp,
            provider=provider_v,
            package_id=package_id,
            source_url=source_url,
            content_sha256=checksum,
            acquired_at=acquired_at,
            verification=VerificationResult.coerce(verification),
            status=TitlePackageStatus.coerce(status),
            media_type="application/zip",
            byte_size=byte_size,
            format_kind=format_kind,
            exclusion=excl,
            notes=notes,
            metadata=metadata or {},
        )

    def record_title_provenance(
        self,
        provenance: TitlePackageProvenance | Mapping[str, Any],
        *,
        build_receipt: bool = True,
    ) -> TitlePackageProvenance:
        """Admit one title's provenance after mixed-vintage validation."""

        if isinstance(provenance, Mapping):
            provenance = TitlePackageProvenance.from_dict(provenance)
        if not isinstance(provenance, TitlePackageProvenance):
            raise TitleProvenanceError("provenance must be a TitlePackageProvenance")

        approved = self.require_approved()
        validate_no_unapproved_mixed_vintages(
            [provenance],
            approved=approved,
            approved_mixed_overrides=self._overrides,
        )
        self._provenances[provenance.title] = provenance
        if build_receipt:
            self.build_resume_receipt(provenance)
        return provenance

    def record_all_canonical_titles(
        self,
        *,
        acquired_at: Any = DEFAULT_ACQUIRED_AT,
        format_kind: str = "xml",
        excluded_titles: Optional[Mapping[str, TitleExclusion | Mapping[str, Any]]] = None,
    ) -> dict[str, TitlePackageProvenance]:
        """Record deterministic provenance for every sealed-baseline title."""

        excluded = {
            require_canonical_title(t): (
                e if isinstance(e, TitleExclusion) else TitleExclusion.from_dict(e)
            )
            for t, e in (excluded_titles or {}).items()
        }
        for title in self._required_titles:
            if title in excluded:
                excl = excluded[title]
                prov = self.build_title_provenance(
                    title,
                    acquired_at=acquired_at,
                    verification=VerificationResult.MISSING,
                    status=TitlePackageStatus.EXCLUDED,
                    format_kind=format_kind,
                    exclusion=excl,
                    notes=excl.reason,
                )
            else:
                prov = self.build_title_provenance(
                    title,
                    acquired_at=acquired_at,
                    format_kind=format_kind,
                )
            self.record_title_provenance(prov, build_receipt=True)
        return dict(self._provenances)

    # -- resume receipts ---------------------------------------------------

    def build_resume_receipt(
        self,
        provenance: TitlePackageProvenance | Mapping[str, Any],
        *,
        checkpoint_seq: Optional[int] = None,
    ) -> TitleResumeReceipt:
        """Build a deterministic resume receipt from title provenance."""

        if isinstance(provenance, Mapping):
            provenance = TitlePackageProvenance.from_dict(provenance)
        if checkpoint_seq is None:
            self._checkpoint_seq += 1
            seq = self._checkpoint_seq
        else:
            if not isinstance(checkpoint_seq, int) or checkpoint_seq < 0:
                raise ResumeReceiptError("checkpoint_seq must be a non-negative int")
            seq = checkpoint_seq
            self._checkpoint_seq = max(self._checkpoint_seq, seq)

        receipt = TitleResumeReceipt(
            title=provenance.title,
            release_point=provenance.release_point,
            package_id=provenance.package_id,
            content_sha256=provenance.content_sha256,
            status=provenance.status,
            verification=provenance.verification,
            source_url=provenance.source_url,
            acquired_at=provenance.acquired_at,
            checkpoint_seq=seq,
            provider=provenance.provider,
            notes=provenance.notes,
            metadata={
                "schema_version": SCHEMA_VERSION,
                "format_kind": provenance.format_kind,
            },
        )
        self._receipts[receipt.title] = receipt
        return receipt

    def resume_from_receipt(
        self,
        receipt: TitleResumeReceipt | Mapping[str, Any],
        *,
        on_disk_sha256: Optional[str] = None,
    ) -> dict[str, Any]:
        """Evaluate a resume receipt and report whether redownload is needed.

        Returns a disposition mapping::

            {
              "title": ...,
              "action": "skip" | "redownload" | "verify_failed",
              "receipt_digest": ...,
              "should_skip_redownload": bool,
            }
        """

        if isinstance(receipt, Mapping):
            receipt = TitleResumeReceipt.from_dict(receipt)
        # Re-parse to enforce digest integrity.
        receipt = TitleResumeReceipt.from_dict(receipt.to_dict())
        self._receipts[receipt.title] = receipt

        if receipt.should_skip_redownload(on_disk_sha256=on_disk_sha256):
            action = "skip"
        elif on_disk_sha256 is not None and receipt.is_verified:
            action = "verify_failed"
        else:
            action = "redownload"

        return {
            "action": action,
            "receipt_digest": receipt.receipt_digest,
            "should_skip_redownload": action == "skip",
            "status": receipt.status.value,
            "title": receipt.title,
            "verification": receipt.verification.value,
        }

    # -- manifest ----------------------------------------------------------

    def build_manifest(
        self,
        *,
        notes: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> AllTitleReleaseManifest:
        """Seal the current policy state into an all-title release manifest."""

        approved = self.require_approved()
        return AllTitleReleaseManifest(
            approved_release=approved,
            titles=dict(self._provenances),
            resume_receipts=dict(self._receipts),
            proposed_release=self._proposed,
            approved_mixed_overrides=dict(self._overrides),
            currentness_disclaimer=CURRENTNESS_DISCLAIMER,
            schema_version=SCHEMA_VERSION,
            notes=notes,
            metadata=metadata or {},
        )

    def missing_required_titles(self) -> tuple[str, ...]:
        present = set(self._provenances)
        return tuple(t for t in self._required_titles if t not in present)

    def provenances(self) -> Mapping[str, TitlePackageProvenance]:
        return dict(self._provenances)

    def resume_receipts(self) -> Mapping[str, TitleResumeReceipt]:
        return dict(self._receipts)


# ---------------------------------------------------------------------------
# Fixture recipe / IO
# ---------------------------------------------------------------------------


def default_receipt_fixture_path() -> Path:
    """Return the sealed all-title release-receipts fixture path."""

    here = Path(__file__).resolve()
    # processors/legal_data/thisfile → repo root is parents[3]
    candidates = [
        here.parents[3] / "tests" / "fixtures" / "legal_ir" / "uscode_release_receipts.json",
        Path.cwd() / "tests" / "fixtures" / "legal_ir" / "uscode_release_receipts.json",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def build_default_receipt_fixture_payload(
    *,
    release_point: str = DEFAULT_APPROVED_RELEASE_POINT,
    congress: str = DEFAULT_APPROVED_CONGRESS,
    release: str = DEFAULT_APPROVED_RELEASE,
    approved_by: str = DEFAULT_APPROVED_BY,
    approved_at: str = DEFAULT_APPROVED_AT,
    discovered_at: str = DEFAULT_DISCOVERED_AT,
    acquired_at: str = DEFAULT_ACQUIRED_AT,
) -> dict[str, Any]:
    """Build a compact recipe for the sealed all-title receipt fixture.

    The recipe stores generators and shared release identity rather than 53
    fully expanded envelopes, keeping the fixture under admission budgets.
    """

    canonical, congress_s, release_s = parse_release_point_id(
        release_point if release_point else f"{congress}/{release}"
    )
    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "policy_schema_version": SCHEMA_VERSION,
        "fixture_id": f"uscode-all-titles-{canonical.replace('/', '-')}",
        "expected_title_count": EXPECTED_TITLE_COUNT,
        "canonical_titles": list(CANONICAL_USCODE_TITLES),
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "notes": (
            "Compact all-title official-source receipt recipe (USCIR-004). "
            "Proposed-latest discovery is recorded separately from the approved "
            "exact release point. Expand via expand_receipt_fixture()."
        ),
        "proposed_release": {
            "role": ReleasePointRole.PROPOSED_LATEST.value,
            "release_point": canonical,
            "provider": DEFAULT_PROVIDER_OLRC,
            "congress": congress_s,
            "release": release_s,
            "discovered_at": discovered_at,
            "discovery_source": USHOUSE_DOWNLOAD_PAGE,
            "edition": f"olrc-proposed-{canonical.replace('/', '-')}",
            "notes": (
                "Catalog scrape candidate from the House OLRC download page; "
                "not final provenance."
            ),
        },
        "approved_release": {
            "role": ReleasePointRole.APPROVED_EXACT.value,
            "release_point": canonical,
            "provider": DEFAULT_PROVIDER_OLRC,
            "congress": congress_s,
            "release": release_s,
            "approved_by": approved_by,
            "approved_at": approved_at,
            "edition": f"olrc-{canonical.replace('/', '-')}",
            "notes": "Human-sealed exact release point for all-title admission.",
        },
        "approved_mixed_overrides": {},
        "generators": {
            "title_provenance": {
                "provider": DEFAULT_PROVIDER_OLRC,
                "format_kind": "xml",
                "status": TitlePackageStatus.VERIFIED.value,
                "verification": VerificationResult.VERIFIED.value,
                "acquired_at": acquired_at,
                "media_type": "application/zip",
                "checksum_seed_template": "{provider}|{release_point}|title-{title}|package",
                "source_url_template": (
                    f"{USHOUSE_RELEASEPOINT_BASE}/us/pl/{{congress}}/{{release}}/"
                    "xml_usc{title_code}@{congress}-{release}.zip"
                ),
            },
            "resume_receipt": {
                "checkpoint_seq_start": 1,
            },
        },
        "seed_overrides": {
            # Title 53 is reserved/unused and intentionally absent from
            # CANONICAL_USCODE_TITLES; no override needed. Keep a sample
            # exclusion-style note on a present title for recipe coverage.
        },
        "sample_exclusions": [
            {
                "kind": ExclusionKind.CLASSIFICATION_GAP.value,
                "title": "35",
                "citation": "Pub. L. 117-328 div. W",
                "public_law": "Pub. L. 117-328",
                "reason": (
                    "Classification table records a pending editorial "
                    "reclassification affecting cross-references in Title 35; "
                    "package itself remains admitted."
                ),
            }
        ],
    }


def expand_receipt_fixture(payload: JsonMapping) -> AllTitleReleaseManifest:
    """Expand a compact receipt recipe into a full all-title manifest."""

    if not isinstance(payload, Mapping):
        raise FixtureSchemaError("fixture root must be a mapping")
    schema = payload.get("schema_version")
    if schema != FIXTURE_SCHEMA_VERSION:
        raise FixtureSchemaError(
            f"unsupported fixture schema_version {schema!r}; "
            f"expected {FIXTURE_SCHEMA_VERSION!r}"
        )

    expected = int(payload.get("expected_title_count") or EXPECTED_TITLE_COUNT)
    titles_list = payload.get("canonical_titles") or list(CANONICAL_USCODE_TITLES)
    if len(titles_list) != expected:
        raise FixtureSchemaError(
            f"canonical_titles length {len(titles_list)} != expected_title_count {expected}"
        )

    proposed_raw = payload.get("proposed_release")
    proposed = (
        None if proposed_raw is None else ProposedReleasePoint.from_dict(proposed_raw)
    )
    approved = require_approved_exact(
        payload.get("approved_release") or payload.get("approved")
    )

    gen = payload.get("generators") or {}
    prov_gen = gen.get("title_provenance") or {}
    receipt_gen = gen.get("resume_receipt") or {}
    seq_start = int(receipt_gen.get("checkpoint_seq_start", 1))

    provider = SourceProvider.coerce(
        prov_gen.get("provider") or approved.provider
    ).canonical()
    format_kind = str(prov_gen.get("format_kind") or "xml")
    acquired_at = prov_gen.get("acquired_at") or DEFAULT_ACQUIRED_AT
    status = TitlePackageStatus.coerce(
        prov_gen.get("status") or TitlePackageStatus.VERIFIED
    )
    verification = VerificationResult.coerce(
        prov_gen.get("verification") or VerificationResult.VERIFIED
    )

    seed_overrides = payload.get("seed_overrides") or {}
    titles: dict[str, TitlePackageProvenance] = {}
    receipts: dict[str, TitleResumeReceipt] = {}

    # Optional fully-expanded inline titles take precedence when present.
    inline_titles = payload.get("titles") or {}
    inline_receipts = payload.get("resume_receipts") or {}

    congress = approved.congress or DEFAULT_APPROVED_CONGRESS
    release = approved.release or DEFAULT_APPROVED_RELEASE

    for index, title in enumerate(titles_list):
        title_n = require_canonical_title(title)
        if title_n in inline_titles:
            prov = TitlePackageProvenance.from_dict(inline_titles[title_n])
        else:
            override = seed_overrides.get(title_n) or {}
            rp = str(override.get("release_point") or approved.release_point)
            checksum = str(
                override.get("content_sha256")
                or expected_title_package_sha256(
                    release_point=rp, title=title_n, provider=provider
                )
            )
            package_id = str(override.get("package_id") or rp)
            source_url = str(
                override.get("source_url")
                or ushouse_releasepoint_zip_url(
                    congress=congress,
                    release=release,
                    title=title_n,
                    format_kind=format_kind,
                )
            )
            prov = TitlePackageProvenance(
                title=title_n,
                release_point=rp,
                provider=provider,
                package_id=package_id,
                source_url=source_url,
                content_sha256=checksum,
                acquired_at=override.get("acquired_at") or acquired_at,
                verification=VerificationResult.coerce(
                    override.get("verification") or verification
                ),
                status=TitlePackageStatus.coerce(override.get("status") or status),
                media_type=str(override.get("media_type") or "application/zip"),
                byte_size=override.get("byte_size"),
                format_kind=str(override.get("format_kind") or format_kind),
                exclusion=override.get("exclusion"),
                notes=override.get("notes"),
                metadata=override.get("metadata") or {},
            )
        titles[title_n] = prov

        if title_n in inline_receipts:
            receipt = TitleResumeReceipt.from_dict(inline_receipts[title_n])
        else:
            receipt = TitleResumeReceipt(
                title=title_n,
                release_point=prov.release_point,
                package_id=prov.package_id,
                content_sha256=prov.content_sha256,
                status=prov.status,
                verification=prov.verification,
                source_url=prov.source_url,
                acquired_at=prov.acquired_at,
                checkpoint_seq=seq_start + index,
                provider=prov.provider,
                notes=prov.notes,
                metadata={"schema_version": SCHEMA_VERSION, "format_kind": prov.format_kind},
            )
        receipts[title_n] = receipt

    return AllTitleReleaseManifest(
        approved_release=approved,
        titles=titles,
        resume_receipts=receipts,
        proposed_release=proposed,
        approved_mixed_overrides=payload.get("approved_mixed_overrides") or {},
        currentness_disclaimer=str(
            payload.get("currentness_disclaimer") or CURRENTNESS_DISCLAIMER
        ),
        schema_version=str(payload.get("policy_schema_version") or SCHEMA_VERSION),
        notes=payload.get("notes"),
        metadata={
            "fixture_id": payload.get("fixture_id"),
            "fixture_schema_version": FIXTURE_SCHEMA_VERSION,
            "sample_exclusions": payload.get("sample_exclusions") or [],
        },
    )


def load_receipt_fixture_payload(path: PathLike | None = None) -> dict[str, Any]:
    """Load the sealed compact receipt fixture recipe from disk."""

    p = Path(path) if path is not None else default_receipt_fixture_path()
    with p.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise FixtureSchemaError(f"fixture root must be a mapping: {p}")
    return dict(payload)


def load_receipt_fixture(path: PathLike | None = None) -> AllTitleReleaseManifest:
    """Load and expand the sealed all-title release-receipts fixture."""

    return expand_receipt_fixture(load_receipt_fixture_payload(path))


def write_default_receipt_fixture(path: PathLike | None = None) -> Path:
    """Materialize the compact default receipt fixture recipe."""

    p = Path(path) if path is not None else default_receipt_fixture_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = build_default_receipt_fixture_payload()
    p.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return p


__all__ = [
    "CANONICAL_USCODE_TITLES",
    "CANONICAL_USCODE_TITLE_NUMBERS",
    "CURRENTNESS_DISCLAIMER",
    "DEFAULT_APPROVED_RELEASE_POINT",
    "EXPECTED_TITLE_COUNT",
    "FIXTURE_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "AllTitleReleaseManifest",
    "ApprovedReleasePoint",
    "ExclusionKind",
    "FixtureSchemaError",
    "HardCodedLatestEditionError",
    "MissingApprovedReleaseError",
    "ProposedReleasePoint",
    "ReleasePointRole",
    "ResumeReceiptError",
    "SourceProvider",
    "TitleExclusion",
    "TitlePackageProvenance",
    "TitlePackageStatus",
    "TitleProvenanceError",
    "TitleResumeReceipt",
    "UnapprovedMixedVintageError",
    "UnapprovedProposedReleaseError",
    "UscodeSourcePolicy",
    "UscodeSourcePolicyError",
    "VerificationResult",
    "build_default_receipt_fixture_payload",
    "canonical_json_dumps",
    "content_sha256",
    "default_receipt_fixture_path",
    "digest_mapping",
    "expand_receipt_fixture",
    "expected_title_package_sha256",
    "govinfo_title_package_id",
    "govinfo_title_zip_url",
    "is_canonical_title",
    "load_receipt_fixture",
    "load_receipt_fixture_payload",
    "normalize_title",
    "parse_release_point_id",
    "require_approved_exact",
    "require_canonical_title",
    "titles_missing_from_manifest",
    "ushouse_releasepoint_zip_url",
    "ushouse_title_code",
    "validate_no_unapproved_mixed_vintages",
    "write_default_receipt_fixture",
]
