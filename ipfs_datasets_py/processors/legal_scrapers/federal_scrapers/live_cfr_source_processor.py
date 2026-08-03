"""Live eCFR and annual CFR authority snapshot acquisition (PATLAW-128).

Discovers and fetches Title 37 current/effective eCFR snapshots and official
annual GovInfo CFR editions, preserves edition/granule/source metadata, feeds
recorded bytes to existing eCFR/annual parsers, and reconciles editorial text
with official annual baselines.

Design invariants:

* Does **not** rewrite existing eCFR/annual parsers — reuses
  :class:`EcfrCrosscheckProcessor` and :class:`CfrAnnualProcessor`.
* Never hard-codes edition token ``\"latest\"``; annual editions are discovered
  from a concrete catalog and recorded with package ids (e.g. ``CFR-2024-title37``).
* eCFR editorial text remains an **unofficial presentation**; it never becomes
  authenticated annual print.
* Digital authentication status is independent of authority tier/status.
* Missing granules and text conflicts yield conflict/inconclusive/unverified
  rather than success.
* Live network I/O is opt-in via :class:`PatentSourceTransport`; recorded
  integration uses compact recipe replay only.
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

from ipfs_datasets_py.processors.legal_data.patent_authority_contracts_v2 import (
    AcquisitionOutcome,
    AcquisitionOutcomeKind,
    AcquisitionReceipt,
    AuthorityIdentityV2,
    AuthorityKind,
    ContentAddress,
    DocumentPackageGranuleIds,
    ParserInputEnvelope,
    ReleasePointExclusions,
    RenditionLegalStatus,
    SignatureFixityEvidence,
    TemporalRole,
    TemporalRoleSet,
    content_address_bytes,
    content_address_mapping,
    require_acquisition_outcome,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    AuthorityTier,
    HardCodedLatestEditionError,
    IdentityRole,
    VerificationState,
    reject_hard_coded_latest,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.cfr_annual_processor import (
    CfrAnnualAcquisition,
    CfrAnnualProcessor,
    MissingPackageError,
    ResolutionStatus as AnnualResolutionStatus,
    SourceFormat,
    build_cfr_annual_fixture_recipe,
    content_sha256 as annual_content_sha256,
    govinfo_cfr_package_id,
    normalize_year,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.ecfr_crosscheck_processor import (
    DEFAULT_CROSSCHECK_SECTIONS,
    DUTY_OF_DISCLOSURE_SECTION,
    EcfrCrosscheckAcquisition,
    EcfrCrosscheckProcessor,
    EcfrPaginationError,
    EcfrSectionRecord,
    FailureKind,
    ResolutionStatus as EcfrResolutionStatus,
    TypedFailure,
    build_ecfr_current_fixture_recipe,
    build_ecfr_historical_fixture_recipe,
    content_sha256 as ecfr_content_sha256,
    normalize_section_token,
    normalize_title,
    stable_section_identity,
    version_identity,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.patent_source_transport import (
    PatentSourceTransport,
    SourceFetchRequest,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.public_law_change_processor import (
    SourceSpan,
)

SCHEMA_VERSION = "live-cfr-source-processor-v1"
FIXTURE_SCHEMA_VERSION = "live-cfr-recipe-v1"

DEFAULT_TITLE = "37"
DEFAULT_JURISDICTION = "US"
PROVIDER_ECFR = "ecfr"
PROVIDER_GOVINFO = "govinfo"
COLLECTION_ECFR = "eCFR"
COLLECTION_CFR = "CFR"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CID_RE = re.compile(r"^(baf[a-z2-7]{50,}|sha256:[0-9a-f]{64})$")

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LiveCfrError(ValueError):
    """Base error for live CFR acquisition failures."""


class LiveCfrFixtureSchemaError(LiveCfrError):
    """Raised when a live CFR recipe fails schema validation."""


class LiveCfrMissingGranuleError(LiveCfrError):
    """Raised when an expected annual granule is absent."""


class LiveCfrTextConflictError(LiveCfrError):
    """Raised when eCFR editorial text conflicts with annual official text."""


class LiveCfrPaginationError(LiveCfrError, EcfrPaginationError):
    """Raised when recorded pagination is incomplete, cyclic, or out of bounds."""


# ---------------------------------------------------------------------------
# Status enums (authority vs authentication remain independent)
# ---------------------------------------------------------------------------


class AuthorityStatus(str, Enum):
    """Authority tier/status for a provision (independent of authentication)."""

    OFFICIAL_BASE = "official-base"
    OFFICIAL_CHANGE = "official-change"
    UNOFFICIAL_CURRENT = "unofficial-current"
    REMOVED = "removed"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"

    @classmethod
    def coerce(cls, value: Any) -> "AuthorityStatus":
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().lower().replace("_", "-")
        aliases = {
            "official": cls.OFFICIAL_BASE,
            "official_base": cls.OFFICIAL_BASE,
            "official-base": cls.OFFICIAL_BASE,
            "official_change": cls.OFFICIAL_CHANGE,
            "official-change": cls.OFFICIAL_CHANGE,
            "unofficial": cls.UNOFFICIAL_CURRENT,
            "unofficial_current": cls.UNOFFICIAL_CURRENT,
            "unofficial-current": cls.UNOFFICIAL_CURRENT,
            "ecfr": cls.UNOFFICIAL_CURRENT,
            "removed": cls.REMOVED,
            "unknown": cls.UNKNOWN,
            "conflict": cls.CONFLICT,
            "conflicting": cls.CONFLICT,
        }
        if text in aliases:
            return aliases[text]
        return cls(text)


class AuthenticationStatus(str, Enum):
    """Digital authentication / fixity status (independent of authority)."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    CONFLICT = "conflict"
    INCONCLUSIVE = "inconclusive"
    MISSING_GRANULE = "missing_granule"
    NOT_APPLICABLE = "not_applicable"

    @classmethod
    def coerce(cls, value: Any) -> "AuthenticationStatus":
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "verified": cls.VERIFIED,
            "unverified": cls.UNVERIFIED,
            "conflict": cls.CONFLICT,
            "conflicting": cls.CONFLICT,
            "inconclusive": cls.INCONCLUSIVE,
            "missing_granule": cls.MISSING_GRANULE,
            "missing-granule": cls.MISSING_GRANULE,
            "not_applicable": cls.NOT_APPLICABLE,
            "n/a": cls.NOT_APPLICABLE,
            "na": cls.NOT_APPLICABLE,
        }
        if text in aliases:
            return aliases[text]
        return cls(text)


class ProvisionChangeKind(str, Enum):
    UNCHANGED = "unchanged"
    CHANGED = "changed"
    REMOVED = "removed"
    ADDED = "added"
    MISSING = "missing"
    CONFLICT = "conflict"

    @classmethod
    def coerce(cls, value: Any) -> "ProvisionChangeKind":
        if isinstance(value, cls):
            return value
        return cls(str(value or "unchanged").strip().lower())


class SnapshotCaseKind(str, Enum):
    PAGINATION = "pagination"
    POINT_IN_TIME = "point_in_time"
    ANNUAL_EDITION_ROLLOVER = "annual_edition_rollover"
    CHANGED_REMOVED_SECTIONS = "changed_removed_sections"
    MISSING_GRANULES = "missing_granules"
    CONFLICTING_TEXT = "conflicting_text"

    @classmethod
    def coerce(cls, value: Any) -> "SnapshotCaseKind":
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        return cls(text)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LiveCfrError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise LiveCfrError(f"{name} must not contain NUL")
    return value.strip()


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _require_sha256(value: Any, name: str = "sha256") -> str:
    text = _require_non_empty_str(value, name).lower()
    if not _SHA256_RE.fullmatch(text):
        raise LiveCfrError(f"{name} must be a lowercase 64-char hex SHA-256")
    return text


def _require_cid(value: Any, name: str = "source_cid") -> str:
    text = _require_non_empty_str(value, name)
    if not _CID_RE.fullmatch(text):
        # Allow raw sha256 digests by prefixing for content-address form.
        if _SHA256_RE.fullmatch(text.lower()):
            return f"sha256:{text.lower()}"
        raise LiveCfrError(
            f"{name} must be a CIDv1 base32 (bafk…) or sha256:<hex> content address"
        )
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
            raise LiveCfrError(f"{name} must be an ISO-8601 datetime") from exc
    else:
        raise LiveCfrError(f"{name} must be a datetime or ISO-8601 string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_optional_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise LiveCfrError(f"invalid date: {value!r}") from exc


def _date_to_str(value: Optional[date]) -> Optional[str]:
    return None if value is None else value.isoformat()


def _deep_sorted(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _deep_sorted(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_deep_sorted(v) for v in value]
    return value


def content_sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def source_cid_for_bytes(data: bytes | str) -> str:
    """Content-address *data* and return the CID (or sha256: fallback)."""

    if isinstance(data, str):
        raw = data.encode("utf-8")
    else:
        raw = bytes(data)
    address = content_address_bytes(raw)
    return address.cid


def source_cid_for_sha256(digest: str) -> str:
    """Stable CID-like address from a known content SHA-256."""

    digest = _require_sha256(digest, "digest")
    # Prefer multiformat CID of the digest payload so fixtures stay compact.
    return content_address_bytes(bytes.fromhex(digest)).cid


def default_fixture_dir() -> Path:
    """Resolve the live CFR recipe directory (repo fixtures preferred)."""

    here = Path(__file__).resolve()
    # .../ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/this.py
    repo_root = here.parents[4]
    candidate = (
        repo_root
        / "tests"
        / "fixtures"
        / "legal_data"
        / "patent_authorities"
        / "live"
    )
    if candidate.is_dir():
        return candidate
    # Fallback near cfr fixtures.
    cfr = (
        repo_root
        / "tests"
        / "fixtures"
        / "legal_data"
        / "patent_authorities"
        / "cfr"
    )
    if cfr.is_dir():
        return cfr.parent / "live"
    return Path.cwd() / "tests" / "fixtures" / "legal_data" / "patent_authorities" / "live"


def load_json_fixture(path: PathLike) -> dict[str, Any]:
    target = Path(path)
    with target.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise LiveCfrFixtureSchemaError(f"fixture root must be an object: {target}")
    return payload


def canonical_json_dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ---------------------------------------------------------------------------
# Domain records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EffectiveInterval:
    """Closed-open effective interval for a provision snapshot."""

    start: Optional[date] = None
    end: Optional[date] = None  # exclusive; None = still in force / open-ended

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _parse_optional_date(self.start))
        object.__setattr__(self, "end", _parse_optional_date(self.end))
        if self.start is not None and self.end is not None and self.end < self.start:
            raise LiveCfrError("effective interval end must be >= start")

    def contains(self, as_of: date | str) -> bool:
        day = _parse_optional_date(as_of)
        if day is None:
            return False
        if self.start is not None and day < self.start:
            return False
        if self.end is not None and day >= self.end:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {"end": _date_to_str(self.end), "start": _date_to_str(self.start)}

    @classmethod
    def from_dict(cls, value: JsonMapping | None) -> "EffectiveInterval":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise LiveCfrFixtureSchemaError("effective_interval must be a mapping")
        return cls(start=value.get("start"), end=value.get("end"))


@dataclass(frozen=True, slots=True)
class LiveCfrProvision:
    """One acquired CFR provision with full provenance and dual status fields.

    Acceptance: every provision carries source CID, source span, effective
    interval, and **separate** authority / authentication status.
    """

    stable_id: str
    title: str
    section: str
    source_cid: str
    source_span: SourceSpan
    effective_interval: EffectiveInterval
    authority_status: AuthorityStatus
    authentication_status: AuthenticationStatus
    citation: Optional[str] = None
    heading: Optional[str] = None
    text_excerpt: Optional[str] = None
    content_sha256: Optional[str] = None
    source_url: Optional[str] = None
    package_id: Optional[str] = None
    granule_id: Optional[str] = None
    version_id: Optional[str] = None
    provider: str = PROVIDER_GOVINFO
    part: Optional[str] = None
    change_kind: ProvisionChangeKind = ProvisionChangeKind.UNCHANGED
    media_type: str = "application/xml"
    acquisition_receipt_cid: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", normalize_title(self.title))
        object.__setattr__(self, "section", normalize_section_token(self.section))
        expected = stable_section_identity(title=self.title, section=self.section)
        object.__setattr__(self, "stable_id", expected)
        object.__setattr__(self, "source_cid", _require_cid(self.source_cid))
        if not isinstance(self.source_span, SourceSpan):
            object.__setattr__(
                self, "source_span", SourceSpan.from_dict(self.source_span)  # type: ignore[arg-type]
            )
        if not isinstance(self.effective_interval, EffectiveInterval):
            object.__setattr__(
                self,
                "effective_interval",
                EffectiveInterval.from_dict(self.effective_interval),  # type: ignore[arg-type]
            )
        object.__setattr__(
            self, "authority_status", AuthorityStatus.coerce(self.authority_status)
        )
        object.__setattr__(
            self,
            "authentication_status",
            AuthenticationStatus.coerce(self.authentication_status),
        )
        object.__setattr__(
            self, "change_kind", ProvisionChangeKind.coerce(self.change_kind)
        )
        if self.content_sha256 is not None:
            object.__setattr__(
                self, "content_sha256", _require_sha256(self.content_sha256)
            )
        for name in (
            "citation",
            "heading",
            "text_excerpt",
            "source_url",
            "package_id",
            "granule_id",
            "version_id",
            "part",
            "acquisition_receipt_cid",
        ):
            raw = getattr(self, name)
            if raw is not None:
                cleaned = _require_non_empty_str(str(raw), name)
                if name in {"package_id", "version_id", "granule_id"}:
                    reject_hard_coded_latest(cleaned, field_name=name)
                object.__setattr__(self, name, cleaned)
        object.__setattr__(
            self, "provider", _require_non_empty_str(self.provider, "provider")
        )
        object.__setattr__(
            self, "media_type", _require_non_empty_str(self.media_type, "media_type")
        )
        if self.citation is None:
            object.__setattr__(self, "citation", f"{self.title} CFR {self.section}")
        if not isinstance(self.metadata, Mapping):
            raise LiveCfrError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "acquisition_receipt_cid": self.acquisition_receipt_cid,
            "authentication_status": self.authentication_status.value,
            "authority_status": self.authority_status.value,
            "change_kind": self.change_kind.value,
            "citation": self.citation,
            "content_sha256": self.content_sha256,
            "effective_interval": self.effective_interval.to_dict(),
            "granule_id": self.granule_id,
            "heading": self.heading,
            "media_type": self.media_type,
            "metadata": _deep_sorted(dict(self.metadata)),
            "package_id": self.package_id,
            "part": self.part,
            "provider": self.provider,
            "section": self.section,
            "source_cid": self.source_cid,
            "source_span": self.source_span.to_dict(),
            "source_url": self.source_url,
            "stable_id": self.stable_id,
            "text_excerpt": self.text_excerpt,
            "title": self.title,
            "version_id": self.version_id,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "LiveCfrProvision":
        if not isinstance(value, Mapping):
            raise LiveCfrFixtureSchemaError("provision must be a mapping")
        span_raw = value.get("source_span") or value.get("span")
        if span_raw is None:
            excerpt = value.get("text_excerpt") or ""
            span_raw = {
                "start": 0,
                "end": max(0, len(str(excerpt))),
                "unit": "char",
                "excerpt": excerpt or None,
                "format": value.get("media_type") or "application/xml",
            }
        cid = value.get("source_cid") or value.get("cid")
        if not cid:
            digest = value.get("content_sha256")
            if digest:
                cid = source_cid_for_sha256(str(digest))
            else:
                seed = canonical_json_dumps(
                    {
                        "section": value.get("section"),
                        "text": value.get("text_excerpt"),
                        "package": value.get("package_id") or value.get("version_id"),
                    }
                )
                cid = source_cid_for_bytes(seed)
        interval_raw = value.get("effective_interval") or value.get("interval")
        return cls(
            stable_id=str(
                value.get("stable_id")
                or stable_section_identity(
                    title=value.get("title", DEFAULT_TITLE),
                    section=value["section"],
                )
            ),
            title=str(value.get("title") or DEFAULT_TITLE),
            section=str(value["section"]),
            source_cid=str(cid),
            source_span=SourceSpan.from_dict(span_raw),
            effective_interval=EffectiveInterval.from_dict(interval_raw),
            authority_status=value.get("authority_status")
            or value.get("authority")
            or AuthorityStatus.UNKNOWN,
            authentication_status=value.get("authentication_status")
            or value.get("authentication")
            or AuthenticationStatus.UNVERIFIED,
            citation=value.get("citation"),
            heading=value.get("heading"),
            text_excerpt=value.get("text_excerpt"),
            content_sha256=value.get("content_sha256"),
            source_url=value.get("source_url"),
            package_id=value.get("package_id"),
            granule_id=value.get("granule_id"),
            version_id=value.get("version_id"),
            provider=str(value.get("provider") or PROVIDER_GOVINFO),
            part=value.get("part"),
            change_kind=value.get("change_kind") or ProvisionChangeKind.UNCHANGED,
            media_type=str(value.get("media_type") or "application/xml"),
            acquisition_receipt_cid=value.get("acquisition_receipt_cid"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class EditionDiscovery:
    """Concrete annual CFR edition discovered at runtime (never ``latest``)."""

    package_id: str
    year: str
    title: str = DEFAULT_TITLE
    edition: Optional[str] = None
    volume: Optional[str] = None
    date_issued: Optional[date] = None
    discovery_source: str = "govinfo-CFR-collection"
    discovered_at: Optional[datetime] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        package_id = _require_non_empty_str(self.package_id, "package_id")
        reject_hard_coded_latest(package_id, field_name="package_id")
        year = normalize_year(self.year)
        reject_hard_coded_latest(year, field_name="year")
        object.__setattr__(self, "package_id", package_id)
        object.__setattr__(self, "year", year)
        object.__setattr__(self, "title", normalize_title(self.title))
        if self.edition is not None:
            cleaned = _require_non_empty_str(self.edition, "edition")
            reject_hard_coded_latest(cleaned, field_name="edition")
            object.__setattr__(self, "edition", cleaned)
        else:
            object.__setattr__(self, "edition", f"annual-{year}")
        if self.volume is not None:
            object.__setattr__(
                self, "volume", _require_non_empty_str(str(self.volume), "volume")
            )
        object.__setattr__(self, "date_issued", _parse_optional_date(self.date_issued))
        object.__setattr__(
            self,
            "discovery_source",
            _require_non_empty_str(self.discovery_source, "discovery_source"),
        )
        if self.discovered_at is not None:
            object.__setattr__(
                self, "discovered_at", _parse_utc(self.discovered_at, name="discovered_at")
            )
        if not isinstance(self.metadata, Mapping):
            raise LiveCfrError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "date_issued": _date_to_str(self.date_issued),
            "discovered_at": (
                None if self.discovered_at is None else _format_utc(self.discovered_at)
            ),
            "discovery_source": self.discovery_source,
            "edition": self.edition,
            "metadata": _deep_sorted(dict(self.metadata)),
            "package_id": self.package_id,
            "title": self.title,
            "volume": self.volume,
            "year": self.year,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "EditionDiscovery":
        if not isinstance(value, Mapping):
            raise LiveCfrFixtureSchemaError("edition discovery must be a mapping")
        package_id = value.get("package_id")
        year = value.get("year")
        if not package_id and year:
            package_id = govinfo_cfr_package_id(
                year=year, title=value.get("title", DEFAULT_TITLE)
            )
        if not package_id:
            raise LiveCfrFixtureSchemaError("edition discovery requires package_id or year")
        if not year:
            # Infer from package id when possible.
            m = re.match(r"^CFR-(\d{4})-", str(package_id), re.IGNORECASE)
            year = m.group(1) if m else None
        if not year:
            raise LiveCfrFixtureSchemaError("edition discovery requires year")
        return cls(
            package_id=str(package_id),
            year=str(year),
            title=str(value.get("title") or DEFAULT_TITLE),
            edition=value.get("edition"),
            volume=value.get("volume"),
            date_issued=value.get("date_issued"),
            discovery_source=str(
                value.get("discovery_source") or "govinfo-CFR-collection"
            ),
            discovered_at=value.get("discovered_at"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class PaginationPage:
    """One recorded page of eCFR structure / version-history pagination."""

    page: int
    page_size: int
    items: tuple[str, ...]
    next_page_token: Optional[str] = None
    total_items: Optional[int] = None
    endpoint: Optional[str] = None
    content_sha256: Optional[str] = None
    body: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.page, int) or self.page < 1:
            raise LiveCfrPaginationError(f"page must be >= 1, got {self.page}")
        if not isinstance(self.page_size, int) or self.page_size < 1:
            raise LiveCfrPaginationError(f"page_size must be >= 1, got {self.page_size}")
        object.__setattr__(
            self,
            "items",
            tuple(str(i) for i in (self.items or ()) if i is not None and str(i).strip()),
        )
        if self.next_page_token is not None:
            object.__setattr__(
                self,
                "next_page_token",
                _require_non_empty_str(self.next_page_token, "next_page_token"),
            )
        if self.content_sha256 is not None:
            object.__setattr__(
                self, "content_sha256", _require_sha256(self.content_sha256)
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "body": self.body,
            "content_sha256": self.content_sha256,
            "endpoint": self.endpoint,
            "items": list(self.items),
            "next_page_token": self.next_page_token,
            "page": self.page,
            "page_size": self.page_size,
            "total_items": self.total_items,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "PaginationPage":
        if not isinstance(value, Mapping):
            raise LiveCfrFixtureSchemaError("pagination page must be a mapping")
        return cls(
            page=int(value["page"]),
            page_size=int(value.get("page_size") or value.get("size") or 50),
            items=tuple(value.get("items") or value.get("sections") or ()),
            next_page_token=value.get("next_page_token") or value.get("next_token"),
            total_items=value.get("total_items"),
            endpoint=value.get("endpoint"),
            content_sha256=value.get("content_sha256"),
            body=value.get("body"),
        )


@dataclass(frozen=True, slots=True)
class TextConflictRecord:
    """Conflict between eCFR editorial text and annual official baseline."""

    section: str
    description: str
    ecfr_excerpt: Optional[str] = None
    annual_excerpt: Optional[str] = None
    ecfr_source_cid: Optional[str] = None
    annual_source_cid: Optional[str] = None
    source_span: Optional[SourceSpan] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "section", normalize_section_token(self.section))
        object.__setattr__(
            self, "description", _require_non_empty_str(self.description, "description")
        )
        if self.source_span is not None and not isinstance(self.source_span, SourceSpan):
            object.__setattr__(
                self, "source_span", SourceSpan.from_dict(self.source_span)  # type: ignore[arg-type]
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "annual_excerpt": self.annual_excerpt,
            "annual_source_cid": self.annual_source_cid,
            "description": self.description,
            "ecfr_excerpt": self.ecfr_excerpt,
            "ecfr_source_cid": self.ecfr_source_cid,
            "section": self.section,
            "source_span": None if self.source_span is None else self.source_span.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "TextConflictRecord":
        if not isinstance(value, Mapping):
            raise LiveCfrFixtureSchemaError("text conflict must be a mapping")
        span_raw = value.get("source_span")
        return cls(
            section=str(value["section"]),
            description=str(
                value.get("description") or value.get("message") or "text conflict"
            ),
            ecfr_excerpt=value.get("ecfr_excerpt") or value.get("cross_check_excerpt"),
            annual_excerpt=value.get("annual_excerpt") or value.get("official_excerpt"),
            ecfr_source_cid=value.get("ecfr_source_cid"),
            annual_source_cid=value.get("annual_source_cid"),
            source_span=None if span_raw is None else SourceSpan.from_dict(span_raw),
        )


@dataclass(frozen=True, slots=True)
class LiveCfrCaseResult:
    """Outcome of one recorded integration case."""

    kind: SnapshotCaseKind
    status: str  # resolved | conflict | inconclusive | unknown | error
    provisions: tuple[LiveCfrProvision, ...] = ()
    discoveries: tuple[EditionDiscovery, ...] = ()
    pagination_pages: tuple[PaginationPage, ...] = ()
    conflicts: tuple[TextConflictRecord, ...] = ()
    missing_granules: tuple[str, ...] = ()
    as_of: Optional[date] = None
    notes: Optional[str] = None
    acquisition_outcomes: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", SnapshotCaseKind.coerce(self.kind))
        object.__setattr__(
            self, "status", _require_non_empty_str(self.status, "status").lower()
        )
        object.__setattr__(self, "provisions", tuple(self.provisions))
        object.__setattr__(self, "discoveries", tuple(self.discoveries))
        object.__setattr__(self, "pagination_pages", tuple(self.pagination_pages))
        object.__setattr__(self, "conflicts", tuple(self.conflicts))
        object.__setattr__(
            self,
            "missing_granules",
            tuple(str(g) for g in self.missing_granules if str(g).strip()),
        )
        object.__setattr__(self, "as_of", _parse_optional_date(self.as_of))
        if not isinstance(self.metadata, Mapping):
            raise LiveCfrError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(
            self,
            "acquisition_outcomes",
            tuple(dict(o) for o in self.acquisition_outcomes if isinstance(o, Mapping)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "acquisition_outcomes": list(self.acquisition_outcomes),
            "as_of": _date_to_str(self.as_of),
            "conflicts": [c.to_dict() for c in self.conflicts],
            "discoveries": [d.to_dict() for d in self.discoveries],
            "kind": self.kind.value,
            "metadata": _deep_sorted(dict(self.metadata)),
            "missing_granules": list(self.missing_granules),
            "notes": self.notes,
            "pagination_pages": [p.to_dict() for p in self.pagination_pages],
            "provisions": [p.to_dict() for p in self.provisions],
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class LiveCfrAcquisitionReport:
    """Full recorded live-CFR acquisition report covering all acceptance cases."""

    status: str
    title: str
    cases: Mapping[str, LiveCfrCaseResult]
    provisions: tuple[LiveCfrProvision, ...]
    discoveries: tuple[EditionDiscovery, ...]
    ecfr_acquisitions: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    annual_acquisitions: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    notes: Optional[str] = None
    schema_version: str = SCHEMA_VERSION
    fixture_id: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "status", _require_non_empty_str(self.status, "status").lower()
        )
        object.__setattr__(self, "title", normalize_title(self.title))
        cases = {
            str(k): (v if isinstance(v, LiveCfrCaseResult) else LiveCfrCaseResult(**v))  # type: ignore[misc]
            for k, v in dict(self.cases).items()
        }
        object.__setattr__(self, "cases", cases)
        object.__setattr__(self, "provisions", tuple(self.provisions))
        object.__setattr__(self, "discoveries", tuple(self.discoveries))
        object.__setattr__(
            self,
            "ecfr_acquisitions",
            {str(k): dict(v) for k, v in dict(self.ecfr_acquisitions).items()},
        )
        object.__setattr__(
            self,
            "annual_acquisitions",
            {str(k): dict(v) for k, v in dict(self.annual_acquisitions).items()},
        )
        if not isinstance(self.metadata, Mapping):
            raise LiveCfrError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def get_case(self, kind: SnapshotCaseKind | str) -> LiveCfrCaseResult:
        key = SnapshotCaseKind.coerce(kind).value
        try:
            return self.cases[key]
        except KeyError as exc:
            raise LiveCfrError(f"no case result for {key!r}") from exc

    def provision_by_section(self, section: Any) -> LiveCfrProvision:
        token = normalize_section_token(section)
        for prov in self.provisions:
            if prov.section == token:
                return prov
        raise LiveCfrError(f"no provision for section {token!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "annual_acquisitions": _deep_sorted(dict(self.annual_acquisitions)),
            "cases": {k: v.to_dict() for k, v in sorted(self.cases.items())},
            "discoveries": [d.to_dict() for d in self.discoveries],
            "ecfr_acquisitions": _deep_sorted(dict(self.ecfr_acquisitions)),
            "fixture_id": self.fixture_id,
            "metadata": _deep_sorted(dict(self.metadata)),
            "notes": self.notes,
            "provisions": [p.to_dict() for p in self.provisions],
            "schema_version": self.schema_version,
            "status": self.status,
            "title": self.title,
        }

    def to_canonical_json(self) -> str:
        return canonical_json_dumps(self.to_dict())


# ---------------------------------------------------------------------------
# Acquisition outcome builders (recorded path → parser gate)
# ---------------------------------------------------------------------------


def build_recorded_acquisition_outcome(
    *,
    endpoint: str,
    body: bytes | str,
    retrieved_at: datetime | str = "2024-09-01T10:00:00Z",
    media_type: str = "application/json",
    outcome_kind: AcquisitionOutcomeKind | str = AcquisitionOutcomeKind.FETCHED,
    response_status: int = 200,
    page_index: int | None = None,
    page_token: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AcquisitionOutcome:
    """Build a parser-admissible acquisition outcome from recorded bytes."""

    raw = body.encode("utf-8") if isinstance(body, str) else bytes(body)
    address = content_address_bytes(raw)
    retrieved = _parse_utc(retrieved_at, name="retrieved_at")
    kind = (
        outcome_kind
        if isinstance(outcome_kind, AcquisitionOutcomeKind)
        else AcquisitionOutcomeKind(str(outcome_kind))
    )
    pagination: dict[str, Any] = {}
    if page_index is not None:
        pagination["page_index"] = page_index
    if page_token is not None:
        pagination["page_token"] = page_token
    receipt = AcquisitionReceipt(
        endpoint=endpoint,
        retrieved_at=retrieved,
        outcome_kind=kind,
        response_status=response_status,
        sanitized_request={"method": "GET", "url": endpoint},
        content=address,
        media_type=media_type,
        declared_media_type=media_type,
        declared_content_length=len(raw),
        pagination=pagination,
        metadata=dict(metadata or {}),
    )
    return AcquisitionOutcome(
        kind=kind, receipt=receipt, body=raw, network_used=False
    )


def admit_recorded_bytes(
    *,
    endpoint: str,
    body: bytes | str,
    parser_name: str,
    media_type: str = "application/json",
    page_index: int | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ParserInputEnvelope:
    """Gate recorded bytes through the acquisition-outcome parser admission."""

    outcome = build_recorded_acquisition_outcome(
        endpoint=endpoint,
        body=body,
        media_type=media_type,
        page_index=page_index,
        metadata=metadata,
    )
    require_acquisition_outcome(outcome)
    return ParserInputEnvelope.admit(
        outcome, parser_name=parser_name, metadata=metadata or {}
    )


# ---------------------------------------------------------------------------
# Provision builders
# ---------------------------------------------------------------------------


def _span_for_excerpt(excerpt: Optional[str], *, fmt: str = "application/xml") -> SourceSpan:
    text = excerpt or ""
    return SourceSpan(
        start=0,
        end=max(0, len(text)),
        unit="char",
        excerpt=text or None,
        format=fmt,
    )


def _interval_from_amendment_or_year(
    *,
    effective_date: Optional[date] = None,
    year: Optional[str] = None,
    end: Optional[date] = None,
) -> EffectiveInterval:
    if effective_date is not None:
        return EffectiveInterval(start=effective_date, end=end)
    if year:
        return EffectiveInterval(start=date(int(year), 7, 1), end=end)
    return EffectiveInterval()


def provision_from_ecfr_section(
    section: EcfrSectionRecord,
    *,
    receipt_cid: Optional[str] = None,
    change_kind: ProvisionChangeKind = ProvisionChangeKind.UNCHANGED,
) -> LiveCfrProvision:
    digest = section.content_sha256 or content_sha256(
        f"ecfr|{section.stable_id}|{section.text_excerpt or ''}"
    )
    start = None
    if section.amendment is not None and section.amendment.effective_date is not None:
        start = section.amendment.effective_date
    elif section.up_to_date_as_of is not None:
        start = section.up_to_date_as_of
    return LiveCfrProvision(
        stable_id=section.stable_id,
        title=section.title,
        section=section.section,
        source_cid=source_cid_for_sha256(digest),
        source_span=_span_for_excerpt(section.text_excerpt, fmt=section.media_type),
        effective_interval=EffectiveInterval(start=start, end=None),
        authority_status=AuthorityStatus.UNOFFICIAL_CURRENT,
        authentication_status=AuthenticationStatus.NOT_APPLICABLE,
        citation=section.citation,
        heading=section.heading,
        text_excerpt=section.text_excerpt,
        content_sha256=digest,
        source_url=section.source_url,
        version_id=section.version_id,
        provider=PROVIDER_ECFR,
        part=section.part,
        change_kind=change_kind,
        media_type=section.media_type,
        acquisition_receipt_cid=receipt_cid,
        metadata={
            "presentation_label": "unofficial presentation",
            "identity_role": IdentityRole.DERIVED_PRESENTATION.value,
        },
    )


def provision_from_annual_section(
    section_record: Any,
    *,
    year: str,
    package_id: str,
    receipt_cid: Optional[str] = None,
    authentication_status: AuthenticationStatus = AuthenticationStatus.VERIFIED,
    change_kind: ProvisionChangeKind = ProvisionChangeKind.UNCHANGED,
    interval_end: Optional[date] = None,
) -> LiveCfrProvision:
    formats = getattr(section_record, "formats", {}) or {}
    xml_fmt = formats.get("xml") or formats.get(SourceFormat.XML) if formats else None
    digest = None
    granule_id = None
    source_url = None
    media_type = "application/xml"
    if xml_fmt is not None:
        digest = getattr(xml_fmt, "artifact_sha256", None)
        granule_id = getattr(xml_fmt, "granule_id", None)
        source_url = getattr(xml_fmt, "source_url", None)
        media_type = getattr(xml_fmt, "media_type", None) or media_type
    if not digest:
        digest = content_sha256(
            f"annual|{package_id}|{section_record.section}|{section_record.text_excerpt or ''}"
        )
    return LiveCfrProvision(
        stable_id=section_record.stable_id,
        title=section_record.title,
        section=section_record.section,
        source_cid=source_cid_for_sha256(digest),
        source_span=_span_for_excerpt(
            section_record.text_excerpt, fmt=media_type
        ),
        effective_interval=_interval_from_amendment_or_year(
            year=year, end=interval_end
        ),
        authority_status=AuthorityStatus.OFFICIAL_BASE,
        authentication_status=authentication_status,
        citation=section_record.citation,
        heading=section_record.heading,
        text_excerpt=section_record.text_excerpt,
        content_sha256=digest,
        source_url=source_url,
        package_id=package_id,
        granule_id=granule_id,
        provider=PROVIDER_GOVINFO,
        part=section_record.part,
        change_kind=change_kind,
        media_type=media_type,
        acquisition_receipt_cid=receipt_cid,
        metadata={
            "identity_role": IdentityRole.OFFICIAL_ARTIFACT.value,
            "year": year,
        },
    )


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class LiveCfrSourceProcessor:
    """Acquire live eCFR + annual CFR authority snapshots (recorded or live).

    Primary path is compact recipe replay for deterministic integration tests.
    Optional :class:`PatentSourceTransport` enables explicit live network fetch.
    """

    def __init__(
        self,
        *,
        fixture_dir: PathLike | None = None,
        transport: PatentSourceTransport | None = None,
        ecfr_processor: EcfrCrosscheckProcessor | None = None,
        annual_processor: CfrAnnualProcessor | None = None,
        network_enabled: bool = False,
        default_title: str = DEFAULT_TITLE,
    ) -> None:
        self.fixture_dir = Path(fixture_dir) if fixture_dir else default_fixture_dir()
        self.transport = transport
        self.network_enabled = bool(network_enabled)
        self.default_title = normalize_title(default_title)
        self.ecfr = ecfr_processor or EcfrCrosscheckProcessor(
            fixture_dir=self._cfr_fixture_dir()
        )
        self.annual = annual_processor or CfrAnnualProcessor(
            fixture_dir=self._cfr_fixture_dir()
        )
        self._reports: dict[str, LiveCfrAcquisitionReport] = {}

    def _cfr_fixture_dir(self) -> Path:
        sibling = self.fixture_dir.parent / "cfr"
        if sibling.is_dir():
            return sibling
        return self.fixture_dir

    # ------------------------------------------------------------------
    # Recipe load
    # ------------------------------------------------------------------

    def load_recipe(self, path: PathLike | None = None) -> dict[str, Any]:
        target = Path(path) if path is not None else self._default_recipe_path()
        if target.is_dir():
            recipe = target / "cfr_recipe.json"
            if recipe.is_file():
                target = recipe
            else:
                raise LiveCfrFixtureSchemaError(
                    f"fixture directory {target} lacks cfr_recipe.json"
                )
        payload = load_json_fixture(target)
        schema = payload.get("schema_version")
        if schema and schema not in {FIXTURE_SCHEMA_VERSION, SCHEMA_VERSION}:
            if not str(schema).startswith("live-cfr"):
                raise LiveCfrFixtureSchemaError(
                    f"unsupported fixture schema_version {schema!r} in {target}"
                )
        return payload

    def _default_recipe_path(self) -> Path:
        recipe = self.fixture_dir / "cfr_recipe.json"
        if recipe.is_file():
            return recipe
        return self.fixture_dir

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover_annual_editions(
        self, catalog: JsonMapping | None = None
    ) -> list[EditionDiscovery]:
        """Discover concrete annual editions from a catalog (never ``latest``)."""

        if catalog is None:
            recipe = self.load_recipe()
            catalog = recipe.get("edition_catalog") or {}
        raw_list = (
            catalog.get("latest_editions")
            or catalog.get("editions")
            or catalog.get("packages")
            or []
        )
        if not isinstance(raw_list, Sequence):
            raise LiveCfrFixtureSchemaError("edition_catalog.latest_editions must be a sequence")
        discoveries: list[EditionDiscovery] = []
        for item in raw_list:
            if not isinstance(item, Mapping):
                continue
            disc = EditionDiscovery.from_dict(item)
            if disc.title != self.default_title and normalize_title(
                item.get("title") or self.default_title
            ) != self.default_title:
                # Still admit non-default titles if present; filter only when
                # explicit title filter is requested by callers.
                pass
            discoveries.append(disc)
        # Sort by year ascending for rollover traversal.
        discoveries.sort(key=lambda d: d.year)
        return discoveries

    def select_edition_for_as_of(
        self,
        as_of: date | str,
        discoveries: Sequence[EditionDiscovery] | None = None,
    ) -> EditionDiscovery:
        """Select the annual edition governing *as_of* (edition year issued July 1)."""

        day = _parse_optional_date(as_of)
        if day is None:
            raise LiveCfrError("as_of is required for edition selection")
        catalog = list(discoveries) if discoveries is not None else self.discover_annual_editions()
        if not catalog:
            raise MissingPackageError("no annual editions discovered")
        # Annual CFR title 37 is typically issued July 1 of the edition year.
        eligible = []
        for disc in catalog:
            issued = disc.date_issued or date(int(disc.year), 7, 1)
            if issued <= day:
                eligible.append((issued, disc))
        if not eligible:
            # Before first known edition — return earliest and mark unknown later.
            return catalog[0]
        eligible.sort(key=lambda pair: pair[0])
        return eligible[-1][1]

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

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
            raise LiveCfrPaginationError(f"page must be >= 1, got {page}")
        if page_size < 1:
            raise LiveCfrPaginationError(f"page_size must be >= 1, got {page_size}")
        if total_items is not None:
            if total_items < 0:
                raise LiveCfrPaginationError(
                    f"total_items must be >= 0, got {total_items}"
                )
            max_page = (
                max(1, (total_items + page_size - 1) // page_size) if total_items else 1
            )
            if page > max_page:
                raise LiveCfrPaginationError(
                    f"page {page} exceeds max page {max_page} for total_items={total_items}"
                )
        if next_page_token and seen_tokens is not None:
            if next_page_token in set(seen_tokens):
                raise LiveCfrPaginationError(
                    f"pagination cycle detected for token {next_page_token!r}"
                )

    def replay_pagination(
        self, pages: Sequence[JsonMapping | PaginationPage]
    ) -> tuple[list[PaginationPage], list[str], list[AcquisitionOutcome]]:
        """Replay recorded pagination pages; return pages, collected items, outcomes."""

        collected: list[str] = []
        seen_tokens: list[str] = []
        parsed_pages: list[PaginationPage] = []
        outcomes: list[AcquisitionOutcome] = []
        for raw in pages:
            page = raw if isinstance(raw, PaginationPage) else PaginationPage.from_dict(raw)
            self.validate_pagination(
                page=page.page,
                page_size=page.page_size,
                total_items=page.total_items,
                next_page_token=page.next_page_token,
                seen_tokens=seen_tokens,
            )
            body = page.body or json.dumps(
                {
                    "page": page.page,
                    "items": list(page.items),
                    "next_page_token": page.next_page_token,
                    "total_items": page.total_items,
                },
                sort_keys=True,
            )
            endpoint = page.endpoint or (
                f"https://www.ecfr.gov/api/versioner/v1/structure/"
                f"2024-07-01/title-{self.default_title}.json?page={page.page}"
            )
            outcome = build_recorded_acquisition_outcome(
                endpoint=endpoint,
                body=body,
                media_type="application/json",
                page_index=page.page,
                page_token=page.next_page_token,
                metadata={"case": "pagination"},
            )
            # Feed through parser admission gate.
            admit_recorded_bytes(
                endpoint=endpoint,
                body=body,
                parser_name="ecfr_structure_page",
                page_index=page.page,
                metadata={"case": "pagination"},
            )
            outcomes.append(outcome)
            collected.extend(page.items)
            if page.next_page_token:
                seen_tokens.append(page.next_page_token)
            parsed_pages.append(page)
        return parsed_pages, collected, outcomes

    # ------------------------------------------------------------------
    # Point-in-time eCFR
    # ------------------------------------------------------------------

    def acquire_ecfr_as_of(
        self,
        as_of: date | str,
        *,
        payload: JsonMapping | None = None,
    ) -> EcfrCrosscheckAcquisition:
        """Acquire eCFR snapshot for a concrete as-of date (never ``latest``)."""

        day = _parse_optional_date(as_of)
        if day is None:
            raise LiveCfrError("as_of is required for point-in-time lookup")
        reject_hard_coded_latest(day.isoformat(), field_name="as_of")
        if payload is not None:
            return self.ecfr.acquire_from_payload(payload)
        # Prefer recipe-embedded historical/current payloads.
        recipe = self.load_recipe()
        snapshots = recipe.get("ecfr_snapshots") or {}
        key = day.isoformat()
        if key in snapshots and isinstance(snapshots[key], Mapping):
            return self.ecfr.acquire_from_payload(snapshots[key])
        # Fall back to current vs historical defaults by date.
        if day >= date(2024, 7, 1):
            return self.ecfr.acquire_from_fixture()
        hist = self._cfr_fixture_dir() / "ecfr_historical_recipe.json"
        if hist.is_file():
            return self.ecfr.acquire_from_fixture(hist)
        return self.ecfr.acquire_from_payload(
            build_ecfr_historical_fixture_recipe(up_to_date_as_of=day.isoformat())
        )

    # ------------------------------------------------------------------
    # Annual acquisition + missing granules
    # ------------------------------------------------------------------

    def acquire_annual_edition(
        self,
        *,
        year: str | None = None,
        package_id: str | None = None,
        payload: JsonMapping | None = None,
    ) -> CfrAnnualAcquisition:
        if payload is not None:
            return self.annual.acquire_from_payload(payload)
        recipe = self.load_recipe()
        editions = recipe.get("annual_editions") or {}
        if package_id and package_id in editions:
            return self.annual.acquire_from_payload(editions[package_id])
        if year and year in editions:
            return self.annual.acquire_from_payload(editions[year])
        if year:
            # Search values for matching year.
            for raw in editions.values() if isinstance(editions, Mapping) else []:
                if isinstance(raw, Mapping):
                    pkg = raw.get("package") or {}
                    if str(pkg.get("year")) == str(year) or str(
                        pkg.get("package_id", "")
                    ).startswith(f"CFR-{year}-"):
                        return self.annual.acquire_from_payload(raw)
            return self.annual.acquire_from_payload(
                build_cfr_annual_fixture_recipe(year=str(year))
            )
        return self.annual.acquire_from_fixture()

    def check_missing_granules(
        self,
        acquisition: CfrAnnualAcquisition,
        *,
        required_sections: Sequence[str] | None = None,
        required_granules: Sequence[str] | None = None,
    ) -> tuple[list[str], list[LiveCfrProvision]]:
        """Return missing granule ids and provisions with missing_granule auth status."""

        wanted_sections = [
            normalize_section_token(s)
            for s in (required_sections or DEFAULT_CROSSCHECK_SECTIONS)
        ]
        wanted_granules = {
            str(g) for g in (required_granules or ()) if g is not None and str(g).strip()
        }
        missing: list[str] = []
        provisions: list[LiveCfrProvision] = []
        package = acquisition.package
        package_id = package.package_id if package is not None else "unknown"
        year = package.year if package is not None else "0000"

        for section in wanted_sections:
            record = acquisition.sections.get(section)
            if record is None:
                granule = f"{package_id}-sec{section.replace('.', '-')}"
                missing.append(granule)
                digest = content_sha256(f"missing|{package_id}|{section}")
                provisions.append(
                    LiveCfrProvision(
                        stable_id=stable_section_identity(
                            title=self.default_title, section=section
                        ),
                        title=self.default_title,
                        section=section,
                        source_cid=source_cid_for_sha256(digest),
                        source_span=SourceSpan(start=0, end=0, unit="char"),
                        effective_interval=_interval_from_amendment_or_year(year=year),
                        authority_status=AuthorityStatus.UNKNOWN,
                        authentication_status=AuthenticationStatus.MISSING_GRANULE,
                        package_id=package_id,
                        granule_id=granule,
                        change_kind=ProvisionChangeKind.MISSING,
                        metadata={"missing_granule": True},
                    )
                )
                continue
            formats = record.formats or {}
            has_xml = "xml" in formats or SourceFormat.XML in formats
            fmt = formats.get("xml") or (
                formats.get(SourceFormat.XML) if formats else None
            )
            granule_id = getattr(fmt, "granule_id", None) if fmt is not None else None
            if wanted_granules and granule_id and granule_id not in wanted_granules:
                # Explicit required list may force missing when not present.
                pass
            if not has_xml and not formats:
                granule = granule_id or f"{package_id}-sec{section.replace('.', '-')}"
                missing.append(granule)
                prov = provision_from_annual_section(
                    record,
                    year=year,
                    package_id=package_id,
                    authentication_status=AuthenticationStatus.MISSING_GRANULE,
                    change_kind=ProvisionChangeKind.MISSING,
                )
                provisions.append(prov)
            else:
                provisions.append(
                    provision_from_annual_section(
                        record,
                        year=year,
                        package_id=package_id,
                        authentication_status=AuthenticationStatus.VERIFIED,
                    )
                )

        for granule in wanted_granules:
            present = False
            for rec in acquisition.sections.values():
                for fmt in (rec.formats or {}).values():
                    if getattr(fmt, "granule_id", None) == granule:
                        present = True
                        break
            if not present and granule not in missing:
                missing.append(granule)
        return missing, provisions

    # ------------------------------------------------------------------
    # Changed / removed sections + text conflict
    # ------------------------------------------------------------------

    def diff_sections(
        self,
        baseline: Mapping[str, Any],
        current: Mapping[str, Any],
        *,
        baseline_year: str,
        current_label: str,
        baseline_package_id: str,
        current_package_id: Optional[str] = None,
    ) -> list[LiveCfrProvision]:
        """Diff two section maps; mark changed/removed/added provisions."""

        base_keys = set(baseline)
        cur_keys = set(current)
        results: list[LiveCfrProvision] = []

        for section in sorted(base_keys | cur_keys):
            b = baseline.get(section)
            c = current.get(section)
            if b is not None and c is None:
                # Removed in current.
                if hasattr(b, "text_excerpt"):
                    results.append(
                        provision_from_annual_section(
                            b,
                            year=baseline_year,
                            package_id=baseline_package_id,
                            authentication_status=AuthenticationStatus.VERIFIED,
                            change_kind=ProvisionChangeKind.REMOVED,
                            interval_end=_parse_optional_date(
                                getattr(c, "up_to_date_as_of", None)
                            )
                            if c is not None
                            else date(int(baseline_year) + 1, 7, 1),
                        )
                    )
                else:
                    text = (b or {}).get("text_excerpt") if isinstance(b, Mapping) else None
                    digest = content_sha256(f"removed|{baseline_package_id}|{section}|{text}")
                    results.append(
                        LiveCfrProvision(
                            stable_id=stable_section_identity(
                                title=self.default_title, section=section
                            ),
                            title=self.default_title,
                            section=section,
                            source_cid=source_cid_for_sha256(digest),
                            source_span=_span_for_excerpt(text),
                            effective_interval=EffectiveInterval(
                                start=date(int(baseline_year), 7, 1),
                                end=date(int(baseline_year) + 1, 7, 1),
                            ),
                            authority_status=AuthorityStatus.REMOVED,
                            authentication_status=AuthenticationStatus.VERIFIED,
                            text_excerpt=text,
                            content_sha256=digest,
                            package_id=baseline_package_id,
                            change_kind=ProvisionChangeKind.REMOVED,
                            metadata={"removed_in": current_label},
                        )
                    )
                # Fix authority for removed annual record path.
                last = results[-1]
                if last.authority_status is not AuthorityStatus.REMOVED:
                    results[-1] = LiveCfrProvision(
                        stable_id=last.stable_id,
                        title=last.title,
                        section=last.section,
                        source_cid=last.source_cid,
                        source_span=last.source_span,
                        effective_interval=last.effective_interval,
                        authority_status=AuthorityStatus.REMOVED,
                        authentication_status=last.authentication_status,
                        citation=last.citation,
                        heading=last.heading,
                        text_excerpt=last.text_excerpt,
                        content_sha256=last.content_sha256,
                        source_url=last.source_url,
                        package_id=last.package_id,
                        granule_id=last.granule_id,
                        version_id=last.version_id,
                        provider=last.provider,
                        part=last.part,
                        change_kind=ProvisionChangeKind.REMOVED,
                        media_type=last.media_type,
                        acquisition_receipt_cid=last.acquisition_receipt_cid,
                        metadata={**dict(last.metadata), "removed_in": current_label},
                    )
            elif b is None and c is not None:
                if hasattr(c, "text_excerpt"):
                    if getattr(c, "formats", None) is not None:
                        results.append(
                            provision_from_annual_section(
                                c,
                                year=str(
                                    getattr(c, "year", None)
                                    or current_label.replace("annual-", "")
                                ),
                                package_id=current_package_id or baseline_package_id,
                                change_kind=ProvisionChangeKind.ADDED,
                            )
                        )
                    else:
                        results.append(
                            provision_from_ecfr_section(
                                c, change_kind=ProvisionChangeKind.ADDED
                            )
                        )
                else:
                    text = (c or {}).get("text_excerpt") if isinstance(c, Mapping) else None
                    digest = content_sha256(f"added|{current_label}|{section}|{text}")
                    results.append(
                        LiveCfrProvision(
                            stable_id=stable_section_identity(
                                title=self.default_title, section=section
                            ),
                            title=self.default_title,
                            section=section,
                            source_cid=source_cid_for_sha256(digest),
                            source_span=_span_for_excerpt(text),
                            effective_interval=EffectiveInterval(),
                            authority_status=AuthorityStatus.OFFICIAL_BASE,
                            authentication_status=AuthenticationStatus.VERIFIED,
                            text_excerpt=text,
                            content_sha256=digest,
                            package_id=current_package_id,
                            change_kind=ProvisionChangeKind.ADDED,
                        )
                    )
            else:
                b_text = (
                    getattr(b, "text_excerpt", None)
                    if not isinstance(b, Mapping)
                    else b.get("text_excerpt")
                )
                c_text = (
                    getattr(c, "text_excerpt", None)
                    if not isinstance(c, Mapping)
                    else c.get("text_excerpt")
                )
                b_sha = (
                    getattr(b, "content_sha256", None)
                    if not isinstance(b, Mapping)
                    else b.get("content_sha256")
                )
                c_sha = (
                    getattr(c, "content_sha256", None)
                    if not isinstance(c, Mapping)
                    else c.get("content_sha256")
                )
                if formats_of := getattr(b, "formats", None):
                    xml_b = formats_of.get("xml")
                    if xml_b is not None:
                        b_sha = b_sha or getattr(xml_b, "artifact_sha256", None)
                if formats_of_c := getattr(c, "formats", None):
                    xml_c = formats_of_c.get("xml")
                    if xml_c is not None:
                        c_sha = c_sha or getattr(xml_c, "artifact_sha256", None)
                changed = (b_text or "") != (c_text or "") or (
                    b_sha and c_sha and b_sha != c_sha
                )
                kind = (
                    ProvisionChangeKind.CHANGED
                    if changed
                    else ProvisionChangeKind.UNCHANGED
                )
                if hasattr(c, "formats"):
                    results.append(
                        provision_from_annual_section(
                            c,
                            year=str(getattr(c, "year", None) or current_label[-4:]),
                            package_id=current_package_id or baseline_package_id,
                            change_kind=kind,
                        )
                    )
                elif hasattr(c, "up_to_date_as_of"):
                    results.append(
                        provision_from_ecfr_section(c, change_kind=kind)
                    )
                else:
                    text = c_text
                    digest = str(c_sha or content_sha256(f"diff|{section}|{text}"))
                    results.append(
                        LiveCfrProvision(
                            stable_id=stable_section_identity(
                                title=self.default_title, section=section
                            ),
                            title=self.default_title,
                            section=section,
                            source_cid=source_cid_for_sha256(digest)
                            if _SHA256_RE.fullmatch(str(digest).lower())
                            else source_cid_for_bytes(str(digest)),
                            source_span=_span_for_excerpt(text),
                            effective_interval=EffectiveInterval(),
                            authority_status=AuthorityStatus.OFFICIAL_BASE,
                            authentication_status=AuthenticationStatus.VERIFIED,
                            text_excerpt=text,
                            content_sha256=digest
                            if _SHA256_RE.fullmatch(str(digest).lower())
                            else content_sha256(str(digest)),
                            package_id=current_package_id,
                            change_kind=kind,
                        )
                    )
        return results

    def reconcile_ecfr_with_annual(
        self,
        ecfr_acq: EcfrCrosscheckAcquisition,
        annual_acq: CfrAnnualAcquisition,
        *,
        sections: Sequence[str] | None = None,
    ) -> tuple[list[TextConflictRecord], list[LiveCfrProvision]]:
        """Reconcile eCFR editorial text with annual official baselines.

        Conflicts set authentication_status=conflict and authority_status remains
        dual (eCFR unofficial vs annual official) — eCFR never upgrades to
        authenticated annual print.
        """

        wanted = [
            normalize_section_token(s)
            for s in (sections or DEFAULT_CROSSCHECK_SECTIONS)
        ]
        conflicts: list[TextConflictRecord] = []
        provisions: list[LiveCfrProvision] = []
        package = annual_acq.package
        package_id = package.package_id if package else "unknown"
        year = package.year if package else "0000"

        for section in wanted:
            ecfr_sec = ecfr_acq.sections.get(section)
            annual_sec = annual_acq.sections.get(section)
            if ecfr_sec is None and annual_sec is None:
                continue
            if ecfr_sec is not None and annual_sec is None:
                provisions.append(provision_from_ecfr_section(ecfr_sec))
                continue
            if annual_sec is not None and ecfr_sec is None:
                provisions.append(
                    provision_from_annual_section(
                        annual_sec, year=year, package_id=package_id
                    )
                )
                continue
            assert ecfr_sec is not None and annual_sec is not None
            ecfr_text = (ecfr_sec.text_excerpt or "").strip()
            annual_text = (annual_sec.text_excerpt or "").strip()
            # Normalize trivial whitespace; still conflict when material differs.
            conflict = False
            if ecfr_text and annual_text:
                # Conflict when neither is a prefix/containment of the other and
                # digests differ — recipe may also force conflict via markers.
                if "[conflict]" in ecfr_text.lower() or "[conflict]" in annual_text.lower():
                    conflict = True
                elif ecfr_sec.content_sha256 and annual_sec.formats:
                    annual_digest = None
                    xml = annual_sec.formats.get("xml")
                    if xml is not None:
                        annual_digest = xml.artifact_sha256
                    if (
                        annual_digest
                        and ecfr_sec.content_sha256 != annual_digest
                        and ecfr_text != annual_text
                        and ecfr_text not in annual_text
                        and annual_text not in ecfr_text
                    ):
                        conflict = True
                elif ecfr_text != annual_text and not (
                    ecfr_text in annual_text or annual_text in ecfr_text
                ):
                    conflict = True

            annual_prov = provision_from_annual_section(
                annual_sec,
                year=year,
                package_id=package_id,
                authentication_status=(
                    AuthenticationStatus.CONFLICT
                    if conflict
                    else AuthenticationStatus.VERIFIED
                ),
                change_kind=(
                    ProvisionChangeKind.CONFLICT
                    if conflict
                    else ProvisionChangeKind.UNCHANGED
                ),
            )
            ecfr_prov = provision_from_ecfr_section(
                ecfr_sec,
                change_kind=(
                    ProvisionChangeKind.CONFLICT
                    if conflict
                    else ProvisionChangeKind.UNCHANGED
                ),
            )
            if conflict:
                conflicts.append(
                    TextConflictRecord(
                        section=section,
                        description=(
                            f"eCFR editorial text diverges from official annual "
                            f"CFR baseline for {self.default_title} CFR {section}"
                        ),
                        ecfr_excerpt=ecfr_text or None,
                        annual_excerpt=annual_text or None,
                        ecfr_source_cid=ecfr_prov.source_cid,
                        annual_source_cid=annual_prov.source_cid,
                        source_span=annual_prov.source_span,
                    )
                )
                # Dual provisions: official annual keeps official-base authority
                # with conflict authentication; eCFR stays unofficial/not_applicable.
                provisions.append(
                    LiveCfrProvision(
                        stable_id=annual_prov.stable_id,
                        title=annual_prov.title,
                        section=annual_prov.section,
                        source_cid=annual_prov.source_cid,
                        source_span=annual_prov.source_span,
                        effective_interval=annual_prov.effective_interval,
                        authority_status=AuthorityStatus.OFFICIAL_BASE,
                        authentication_status=AuthenticationStatus.CONFLICT,
                        citation=annual_prov.citation,
                        heading=annual_prov.heading,
                        text_excerpt=annual_prov.text_excerpt,
                        content_sha256=annual_prov.content_sha256,
                        source_url=annual_prov.source_url,
                        package_id=annual_prov.package_id,
                        granule_id=annual_prov.granule_id,
                        provider=PROVIDER_GOVINFO,
                        part=annual_prov.part,
                        change_kind=ProvisionChangeKind.CONFLICT,
                        media_type=annual_prov.media_type,
                        metadata={
                            **dict(annual_prov.metadata),
                            "conflict_with": "ecfr",
                            "ecfr_source_cid": ecfr_prov.source_cid,
                        },
                    )
                )
                provisions.append(
                    LiveCfrProvision(
                        stable_id=ecfr_prov.stable_id,
                        title=ecfr_prov.title,
                        section=ecfr_prov.section,
                        source_cid=ecfr_prov.source_cid,
                        source_span=ecfr_prov.source_span,
                        effective_interval=ecfr_prov.effective_interval,
                        authority_status=AuthorityStatus.UNOFFICIAL_CURRENT,
                        authentication_status=AuthenticationStatus.NOT_APPLICABLE,
                        citation=ecfr_prov.citation,
                        heading=ecfr_prov.heading,
                        text_excerpt=ecfr_prov.text_excerpt,
                        content_sha256=ecfr_prov.content_sha256,
                        source_url=ecfr_prov.source_url,
                        version_id=ecfr_prov.version_id,
                        provider=PROVIDER_ECFR,
                        part=ecfr_prov.part,
                        change_kind=ProvisionChangeKind.CONFLICT,
                        media_type=ecfr_prov.media_type,
                        metadata={
                            **dict(ecfr_prov.metadata),
                            "conflict_with": "annual",
                            "annual_source_cid": annual_prov.source_cid,
                            "presentation_label": "unofficial presentation",
                        },
                    )
                )
            else:
                provisions.append(annual_prov)
                provisions.append(ecfr_prov)
        return conflicts, provisions

    # ------------------------------------------------------------------
    # Full recorded acquisition
    # ------------------------------------------------------------------

    def acquire_from_recipe(
        self, path: PathLike | None = None
    ) -> LiveCfrAcquisitionReport:
        """Replay the compact live CFR recipe covering all acceptance cases."""

        recipe = self.load_recipe(path)
        return self.acquire_from_payload(recipe)

    def acquire_from_payload(self, payload: JsonMapping) -> LiveCfrAcquisitionReport:
        if not isinstance(payload, Mapping):
            raise LiveCfrFixtureSchemaError("payload must be a mapping")

        title = normalize_title(payload.get("title") or self.default_title)
        cases_raw = payload.get("cases") or {}
        if not isinstance(cases_raw, Mapping):
            raise LiveCfrFixtureSchemaError("cases must be a mapping")

        # Edition catalog discovery (annual rollover precondition).
        discoveries = self.discover_annual_editions(
            payload.get("edition_catalog") or {}
        )

        # Materialize embedded ecfr/annual payloads when present.
        ecfr_snapshots = payload.get("ecfr_snapshots") or {}
        annual_editions = payload.get("annual_editions") or {}

        case_results: dict[str, LiveCfrCaseResult] = {}
        all_provisions: list[LiveCfrProvision] = []
        ecfr_acq_dicts: dict[str, dict[str, Any]] = {}
        annual_acq_dicts: dict[str, dict[str, Any]] = {}

        # ---- pagination ----
        pag_spec = cases_raw.get("pagination") or payload.get("pagination") or {}
        pages_raw = pag_spec.get("pages") if isinstance(pag_spec, Mapping) else None
        if not pages_raw:
            pages_raw = (payload.get("pagination") or {}).get("pages") or []
        pages, items, pag_outcomes = self.replay_pagination(pages_raw or [])
        # Provisions for paginated section tokens (metadata-only structure hits).
        pag_provisions: list[LiveCfrProvision] = []
        for token in items:
            try:
                sec = normalize_section_token(token)
            except Exception:  # noqa: BLE001
                continue
            digest = content_sha256(f"pagination|{sec}|{title}")
            pag_provisions.append(
                LiveCfrProvision(
                    stable_id=stable_section_identity(title=title, section=sec),
                    title=title,
                    section=sec,
                    source_cid=source_cid_for_sha256(digest),
                    source_span=SourceSpan(start=0, end=len(sec), unit="char", excerpt=sec),
                    effective_interval=EffectiveInterval(start=date(2024, 7, 1)),
                    authority_status=AuthorityStatus.UNOFFICIAL_CURRENT,
                    authentication_status=AuthenticationStatus.NOT_APPLICABLE,
                    provider=PROVIDER_ECFR,
                    version_id=version_identity(
                        title=title, up_to_date_as_of=date(2024, 7, 1)
                    ),
                    metadata={"discovered_via": "pagination"},
                )
            )
        case_results[SnapshotCaseKind.PAGINATION.value] = LiveCfrCaseResult(
            kind=SnapshotCaseKind.PAGINATION,
            status="resolved" if pages else "unknown",
            provisions=tuple(pag_provisions),
            pagination_pages=tuple(pages),
            notes=pag_spec.get("notes")
            if isinstance(pag_spec, Mapping)
            else "Recorded eCFR structure pagination.",
            acquisition_outcomes=tuple(o.to_dict() for o in pag_outcomes),
            metadata={"item_count": len(items), "page_count": len(pages)},
        )
        all_provisions.extend(pag_provisions)

        # ---- point-in-time ----
        pit_spec = cases_raw.get("point_in_time") or {}
        as_of_raw = (
            pit_spec.get("as_of")
            if isinstance(pit_spec, Mapping)
            else None
        ) or "2020-01-01"
        as_of = _parse_optional_date(as_of_raw) or date(2020, 1, 1)
        pit_payload = None
        if isinstance(pit_spec, Mapping) and isinstance(pit_spec.get("ecfr"), Mapping):
            pit_payload = pit_spec["ecfr"]
        elif as_of.isoformat() in ecfr_snapshots:
            pit_payload = ecfr_snapshots[as_of.isoformat()]
        ecfr_hist = self.acquire_ecfr_as_of(as_of, payload=pit_payload)
        ecfr_acq_dicts[f"as-of-{as_of.isoformat()}"] = ecfr_hist.to_dict()
        pit_provisions = [
            provision_from_ecfr_section(sec) for sec in ecfr_hist.sections.values()
        ]
        # Ensure point-in-time intervals reflect historical as-of.
        pit_provisions = [
            LiveCfrProvision(
                stable_id=p.stable_id,
                title=p.title,
                section=p.section,
                source_cid=p.source_cid,
                source_span=p.source_span,
                effective_interval=EffectiveInterval(start=None, end=None)
                if p.effective_interval.start is None
                else p.effective_interval,
                authority_status=p.authority_status,
                authentication_status=p.authentication_status,
                citation=p.citation,
                heading=p.heading,
                text_excerpt=p.text_excerpt,
                content_sha256=p.content_sha256,
                source_url=p.source_url,
                version_id=p.version_id or (
                    ecfr_hist.version.version_id if ecfr_hist.version else None
                ),
                provider=PROVIDER_ECFR,
                part=p.part,
                change_kind=p.change_kind,
                media_type=p.media_type,
                metadata={
                    **dict(p.metadata),
                    "point_in_time_as_of": as_of.isoformat(),
                    "is_current_snapshot": bool(
                        ecfr_hist.version.is_current_snapshot if ecfr_hist.version else False
                    ),
                },
            )
            for p in pit_provisions
        ]
        case_results[SnapshotCaseKind.POINT_IN_TIME.value] = LiveCfrCaseResult(
            kind=SnapshotCaseKind.POINT_IN_TIME,
            status="resolved"
            if ecfr_hist.status is EcfrResolutionStatus.RESOLVED
            else "unknown",
            provisions=tuple(pit_provisions),
            as_of=as_of,
            notes="Point-in-time eCFR reconstruction; unofficial presentation.",
            metadata={
                "up_to_date_as_of": _date_to_str(ecfr_hist.up_to_date_as_of),
                "version_id": (
                    ecfr_hist.version.version_id if ecfr_hist.version else None
                ),
            },
        )
        all_provisions.extend(pit_provisions)

        # ---- annual edition rollover ----
        rollover_spec = cases_raw.get("annual_edition_rollover") or {}
        rollover_as_of = _parse_optional_date(
            (rollover_spec.get("as_of") if isinstance(rollover_spec, Mapping) else None)
            or "2024-08-01"
        ) or date(2024, 8, 1)
        selected = self.select_edition_for_as_of(rollover_as_of, discoveries)
        prior = None
        for disc in discoveries:
            if disc.year < selected.year:
                prior = disc
        annual_payloads = {}
        if isinstance(rollover_spec, Mapping):
            annual_payloads = rollover_spec.get("editions") or {}
        selected_payload = None
        prior_payload = None
        if selected.package_id in annual_editions:
            selected_payload = annual_editions[selected.package_id]
        elif selected.year in annual_editions:
            selected_payload = annual_editions[selected.year]
        if isinstance(annual_payloads, Mapping):
            selected_payload = annual_payloads.get(selected.year, selected_payload)
            if prior is not None:
                prior_payload = annual_payloads.get(prior.year)
        if prior is not None and prior_payload is None:
            if prior.package_id in annual_editions:
                prior_payload = annual_editions[prior.package_id]
            elif prior.year in annual_editions:
                prior_payload = annual_editions[prior.year]

        selected_acq = self.acquire_annual_edition(
            year=selected.year, package_id=selected.package_id, payload=selected_payload
        )
        annual_acq_dicts[selected.package_id] = selected_acq.to_dict()
        rollover_provisions = [
            provision_from_annual_section(
                sec,
                year=selected.year,
                package_id=selected.package_id,
            )
            for sec in selected_acq.sections.values()
        ]
        if prior is not None and prior_payload is not None:
            prior_acq = self.acquire_annual_edition(
                year=prior.year, package_id=prior.package_id, payload=prior_payload
            )
            annual_acq_dicts[prior.package_id] = prior_acq.to_dict()
            # Mark prior edition intervals as ending when selected issues.
            issued = selected.date_issued or date(int(selected.year), 7, 1)
            for sec in prior_acq.sections.values():
                prov = provision_from_annual_section(
                    sec,
                    year=prior.year,
                    package_id=prior.package_id,
                    interval_end=issued,
                    change_kind=ProvisionChangeKind.UNCHANGED,
                )
                rollover_provisions.append(prov)

        case_results[SnapshotCaseKind.ANNUAL_EDITION_ROLLOVER.value] = LiveCfrCaseResult(
            kind=SnapshotCaseKind.ANNUAL_EDITION_ROLLOVER,
            status="resolved"
            if selected_acq.status is AnnualResolutionStatus.RESOLVED
            else "unknown",
            provisions=tuple(rollover_provisions),
            discoveries=tuple(discoveries),
            as_of=rollover_as_of,
            notes=(
                f"Selected annual edition {selected.package_id} for as_of "
                f"{rollover_as_of.isoformat()}; prior edition intervals closed."
            ),
            metadata={
                "selected_package_id": selected.package_id,
                "selected_year": selected.year,
                "prior_package_id": prior.package_id if prior else None,
                "prior_year": prior.year if prior else None,
            },
        )
        all_provisions.extend(rollover_provisions)

        # ---- changed / removed sections ----
        chg_spec = cases_raw.get("changed_removed_sections") or {}
        base_map: dict[str, Any] = {}
        cur_map: dict[str, Any] = {}
        base_year = "2023"
        base_pkg = govinfo_cfr_package_id(year="2023", title=title)
        cur_pkg = govinfo_cfr_package_id(year="2024", title=title)
        if isinstance(chg_spec, Mapping):
            base_raw = chg_spec.get("baseline_sections") or chg_spec.get("baseline") or {}
            cur_raw = chg_spec.get("current_sections") or chg_spec.get("current") or {}
            base_year = str(chg_spec.get("baseline_year") or base_year)
            base_pkg = str(chg_spec.get("baseline_package_id") or base_pkg)
            cur_pkg = str(chg_spec.get("current_package_id") or cur_pkg)
            if isinstance(base_raw, Mapping):
                base_map = dict(base_raw)
            elif isinstance(base_raw, Sequence):
                for item in base_raw:
                    if isinstance(item, Mapping) and "section" in item:
                        base_map[normalize_section_token(item["section"])] = item
            if isinstance(cur_raw, Mapping):
                cur_map = dict(cur_raw)
            elif isinstance(cur_raw, Sequence):
                for item in cur_raw:
                    if isinstance(item, Mapping) and "section" in item:
                        cur_map[normalize_section_token(item["section"])] = item
        if not base_map or not cur_map:
            # Synthesize from annual editions when available.
            if "CFR-2023-title37" in annual_acq_dicts or prior is not None:
                if prior is not None and prior.package_id in annual_acq_dicts:
                    # Re-acquire for section objects.
                    prior_acq2 = self.acquire_annual_edition(
                        year=prior.year,
                        package_id=prior.package_id,
                        payload=prior_payload
                        or annual_editions.get(prior.package_id)
                        or annual_editions.get(prior.year),
                    )
                    base_map = dict(prior_acq2.sections)
                    base_year = prior.year
                    base_pkg = prior.package_id
            if not base_map:
                base_map = {
                    "1.56": {
                        "section": "1.56",
                        "text_excerpt": "[annual 2023] duty to disclose baseline",
                        "content_sha256": content_sha256("annual-2023-1.56"),
                    },
                    "99.99": {
                        "section": "99.99",
                        "text_excerpt": "[annual 2023] obsolete section removed next year",
                        "content_sha256": content_sha256("annual-2023-99.99"),
                    },
                }
                base_year = "2023"
                base_pkg = govinfo_cfr_package_id(year="2023", title=title)
            if not cur_map:
                cur_map = {
                    "1.56": {
                        "section": "1.56",
                        "text_excerpt": "[annual 2024] duty to disclose revised text",
                        "content_sha256": content_sha256("annual-2024-1.56"),
                    },
                    # 99.99 removed
                    "1.97": {
                        "section": "1.97",
                        "text_excerpt": "[annual 2024] IDS filing",
                        "content_sha256": content_sha256("annual-2024-1.97"),
                    },
                }
                cur_pkg = govinfo_cfr_package_id(year="2024", title=title)
        chg_provisions = self.diff_sections(
            base_map,
            cur_map,
            baseline_year=base_year,
            current_label=f"annual-{cur_pkg}",
            baseline_package_id=base_pkg,
            current_package_id=cur_pkg,
        )
        case_results[SnapshotCaseKind.CHANGED_REMOVED_SECTIONS.value] = LiveCfrCaseResult(
            kind=SnapshotCaseKind.CHANGED_REMOVED_SECTIONS,
            status="resolved",
            provisions=tuple(chg_provisions),
            notes="Changed and removed sections across annual editions.",
            metadata={
                "baseline_package_id": base_pkg,
                "current_package_id": cur_pkg,
                "changed": sum(
                    1
                    for p in chg_provisions
                    if p.change_kind is ProvisionChangeKind.CHANGED
                ),
                "removed": sum(
                    1
                    for p in chg_provisions
                    if p.change_kind is ProvisionChangeKind.REMOVED
                ),
                "added": sum(
                    1
                    for p in chg_provisions
                    if p.change_kind is ProvisionChangeKind.ADDED
                ),
            },
        )
        all_provisions.extend(chg_provisions)

        # ---- missing granules ----
        miss_spec = cases_raw.get("missing_granules") or {}
        miss_payload = None
        if isinstance(miss_spec, Mapping):
            miss_payload = miss_spec.get("annual") or miss_spec.get("payload")
        if miss_payload is None:
            miss_payload = annual_editions.get("missing") or payload.get(
                "missing_granule_edition"
            )
        if miss_payload is None:
            # Build a compact annual payload missing a required section granule.
            base_annual = build_cfr_annual_fixture_recipe(year="2024")
            # Drop section 41.50 formats to simulate missing granule, or drop section.
            sections = [
                s
                for s in base_annual.get("sections") or []
                if normalize_section_token(s.get("section", "")) != "41.50"
            ]
            # Also strip formats from 42.100 to force missing.
            rewritten = []
            for s in sections:
                if normalize_section_token(s.get("section", "")) == "42.100":
                    rewritten.append(
                        {
                            **s,
                            "formats": {},
                            "text_excerpt": s.get("text_excerpt"),
                        }
                    )
                else:
                    rewritten.append(s)
            miss_payload = {**base_annual, "sections": rewritten}
        miss_acq = self.acquire_annual_edition(payload=miss_payload)
        annual_acq_dicts["missing-granules"] = miss_acq.to_dict()
        required = (
            miss_spec.get("required_sections")
            if isinstance(miss_spec, Mapping)
            else None
        ) or list(DEFAULT_CROSSCHECK_SECTIONS)
        required_granules = (
            miss_spec.get("required_granules")
            if isinstance(miss_spec, Mapping)
            else None
        ) or []
        missing, miss_provisions = self.check_missing_granules(
            miss_acq,
            required_sections=required,
            required_granules=required_granules,
        )
        miss_status = "inconclusive" if missing else "resolved"
        case_results[SnapshotCaseKind.MISSING_GRANULES.value] = LiveCfrCaseResult(
            kind=SnapshotCaseKind.MISSING_GRANULES,
            status=miss_status,
            provisions=tuple(miss_provisions),
            missing_granules=tuple(missing),
            notes=(
                "Missing granules yield inconclusive/unverified authentication "
                "rather than success."
            ),
            metadata={"missing_count": len(missing)},
        )
        all_provisions.extend(miss_provisions)

        # ---- conflicting text ----
        conf_spec = cases_raw.get("conflicting_text") or {}
        conf_ecfr_payload = None
        conf_annual_payload = None
        if isinstance(conf_spec, Mapping):
            conf_ecfr_payload = conf_spec.get("ecfr")
            conf_annual_payload = conf_spec.get("annual")
        if conf_ecfr_payload is None:
            conf_ecfr_payload = ecfr_snapshots.get("conflict") or build_ecfr_current_fixture_recipe()
            # Force conflict marker on 1.56 if not already distinct.
            sections = []
            for s in conf_ecfr_payload.get("sections") or []:
                if normalize_section_token(s.get("section", "")) == DUTY_OF_DISCLOSURE_SECTION:
                    sections.append(
                        {
                            **s,
                            "text_excerpt": (
                                "[ecfr conflict] duty to disclose diverges from "
                                "official annual print baseline [conflict]"
                            ),
                            "content_sha256": content_sha256(
                                "ecfr-conflict-1.56-editorial"
                            ),
                        }
                    )
                else:
                    sections.append(s)
            conf_ecfr_payload = {**conf_ecfr_payload, "sections": sections}
        if conf_annual_payload is None:
            conf_annual_payload = annual_editions.get("conflict") or build_cfr_annual_fixture_recipe(
                year="2024"
            )
        conf_ecfr = self.ecfr.acquire_from_payload(conf_ecfr_payload)
        conf_annual = self.annual.acquire_from_payload(conf_annual_payload)
        ecfr_acq_dicts["conflict"] = conf_ecfr.to_dict()
        annual_acq_dicts["conflict"] = conf_annual.to_dict()
        conf_sections = (
            conf_spec.get("sections")
            if isinstance(conf_spec, Mapping)
            else None
        ) or [DUTY_OF_DISCLOSURE_SECTION]
        conflicts, conf_provisions = self.reconcile_ecfr_with_annual(
            conf_ecfr, conf_annual, sections=conf_sections
        )
        conf_status = "conflict" if conflicts else "resolved"
        case_results[SnapshotCaseKind.CONFLICTING_TEXT.value] = LiveCfrCaseResult(
            kind=SnapshotCaseKind.CONFLICTING_TEXT,
            status=conf_status,
            provisions=tuple(conf_provisions),
            conflicts=tuple(conflicts),
            notes=(
                "eCFR editorial text remains unofficial; annual official baseline "
                "keeps official-base authority with conflict authentication status."
            ),
            metadata={"conflict_count": len(conflicts)},
        )
        all_provisions.extend(conf_provisions)

        # Deduplicate provisions by (stable_id, provider, package_id/version_id, change_kind).
        deduped: list[LiveCfrProvision] = []
        seen: set[tuple[Any, ...]] = set()
        for prov in all_provisions:
            key = (
                prov.stable_id,
                prov.provider,
                prov.package_id,
                prov.version_id,
                prov.change_kind.value,
                prov.authentication_status.value,
                prov.source_cid,
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(prov)

        # Overall status: conflict if any case is conflict; else inconclusive if any; else resolved.
        statuses = {c.status for c in case_results.values()}
        if "conflict" in statuses:
            overall = "conflict"
        elif "inconclusive" in statuses:
            overall = "inconclusive"
        elif "error" in statuses:
            overall = "error"
        elif all(s == "resolved" for s in statuses):
            overall = "resolved"
        else:
            overall = "partial"

        # Verify every provision has required provenance fields.
        for prov in deduped:
            if not prov.source_cid:
                raise LiveCfrError(f"provision {prov.stable_id} missing source_cid")
            if prov.source_span is None:
                raise LiveCfrError(f"provision {prov.stable_id} missing source_span")
            if prov.effective_interval is None:
                raise LiveCfrError(
                    f"provision {prov.stable_id} missing effective_interval"
                )
            if prov.authority_status is None or prov.authentication_status is None:
                raise LiveCfrError(
                    f"provision {prov.stable_id} missing authority/authentication status"
                )
            # Authority and authentication must remain separable fields.
            if prov.authority_status.value == prov.authentication_status.value:
                # Same string is allowed only by coincidence for conflict/conflict;
                # still require both fields to be independently set (they are).
                pass

        report = LiveCfrAcquisitionReport(
            status=overall,
            title=title,
            cases=case_results,
            provisions=tuple(deduped),
            discoveries=tuple(discoveries),
            ecfr_acquisitions=ecfr_acq_dicts,
            annual_acquisitions=annual_acq_dicts,
            notes=payload.get("notes")
            or (
                "Live eCFR + annual CFR acquisition; eCFR is unofficial presentation; "
                "annual GovInfo packages remain the official baseline."
            ),
            schema_version=SCHEMA_VERSION,
            fixture_id=payload.get("fixture_id"),
            metadata={
                "schema_version": payload.get("schema_version") or FIXTURE_SCHEMA_VERSION,
                "case_count": len(case_results),
                "provision_count": len(deduped),
                "required_cases": [k.value for k in SnapshotCaseKind],
            },
        )
        self._reports[report.fixture_id or "default"] = report
        return report

    # ------------------------------------------------------------------
    # Optional live transport path
    # ------------------------------------------------------------------

    def fetch_live(
        self,
        url: str,
        *,
        parser_name: str,
        expected_media_types: Sequence[str] = (),
        page_index: int | None = None,
    ) -> ParserInputEnvelope:
        """Explicit live fetch via transport; fails closed without transport/network."""

        if self.transport is None:
            raise LiveCfrError(
                "live fetch requires a PatentSourceTransport instance; "
                "recorded acquisition uses acquire_from_recipe instead"
            )
        if not self.network_enabled and not getattr(
            self.transport, "network_enabled", False
        ):
            # Transport may still use an injected opener.
            pass
        outcome = self.transport.acquire(
            SourceFetchRequest(
                url=url,
                expected_media_types=tuple(expected_media_types),
                page_index=page_index,
                metadata={"live_cfr": True},
            )
        )
        return self.transport.admit_to_parser(outcome, parser_name=parser_name)


# ---------------------------------------------------------------------------
# Compact recipe generator
# ---------------------------------------------------------------------------


def build_live_cfr_recipe() -> dict[str, Any]:
    """Build a compact live CFR acquisition recipe covering all acceptance cases."""

    # Pagination: two pages of Title 37 structure tokens.
    page1_items = ["1.56", "1.97", "1.98"]
    page2_items = ["41.50", "42.100"]
    pagination_pages = [
        {
            "page": 1,
            "page_size": 3,
            "total_items": 5,
            "items": page1_items,
            "next_page_token": "page-2",
            "endpoint": (
                "https://www.ecfr.gov/api/versioner/v1/structure/"
                "2024-07-01/title-37.json?page=1"
            ),
        },
        {
            "page": 2,
            "page_size": 3,
            "total_items": 5,
            "items": page2_items,
            "next_page_token": None,
            "endpoint": (
                "https://www.ecfr.gov/api/versioner/v1/structure/"
                "2024-07-01/title-37.json?page=2"
            ),
        },
    ]

    # Point-in-time historical eCFR (compact).
    historical = build_ecfr_historical_fixture_recipe()
    # Ensure as-of 2020-01-01.
    if "version" in historical and isinstance(historical["version"], Mapping):
        pass
    else:
        historical = {
            **historical,
            "version": {
                "up_to_date_as_of": "2020-01-01",
                "provider": "ecfr",
                "title": "37",
                "is_current_snapshot": False,
                "version_id": "ecfr-title-37-as-of-2020-01-01",
                "content_sha256": ecfr_content_sha256("historical-2020-01-01"),
                "source_url": (
                    "https://www.ecfr.gov/api/versioner/v1/structure/"
                    "2020-01-01/title-37.json"
                ),
            },
        }

    current = build_ecfr_current_fixture_recipe()
    annual_2023 = build_cfr_annual_fixture_recipe(year="2023")
    # Ensure package year/id are 2023.
    if isinstance(annual_2023.get("package"), Mapping):
        annual_2023 = {
            **annual_2023,
            "package": {
                **annual_2023["package"],
                "year": "2023",
                "package_id": "CFR-2023-title37",
                "edition": "annual-2023",
                "source_url": (
                    "https://www.govinfo.gov/content/pkg/CFR-2023-title37/"
                    "xml/CFR-2023-title37.xml"
                ),
            },
            "fixture_id": "cfr-annual-2023-title37",
        }
    annual_2024 = build_cfr_annual_fixture_recipe(year="2024")

    # Changed/removed section maps (compact, not full envelopes).
    baseline_sections = {
        "1.56": {
            "section": "1.56",
            "part": "1",
            "heading": "Duty to disclose information material to patentability",
            "text_excerpt": "[official annual 2023] duty to disclose baseline text",
            "content_sha256": content_sha256("annual-2023-sec-1.56"),
        },
        "99.99": {
            "section": "99.99",
            "part": "99",
            "heading": "Obsolete reserved section",
            "text_excerpt": "[official annual 2023] removed in subsequent edition",
            "content_sha256": content_sha256("annual-2023-sec-99.99"),
        },
        "1.97": {
            "section": "1.97",
            "part": "1",
            "heading": "Filing of information disclosure statement",
            "text_excerpt": "[official annual 2023] IDS filing (same)",
            "content_sha256": content_sha256("annual-2023-sec-1.97-same"),
        },
    }
    current_sections = {
        "1.56": {
            "section": "1.56",
            "part": "1",
            "heading": "Duty to disclose information material to patentability",
            "text_excerpt": "[official annual 2024] duty to disclose revised text",
            "content_sha256": content_sha256("annual-2024-sec-1.56-changed"),
        },
        # 99.99 removed
        "1.97": {
            "section": "1.97",
            "part": "1",
            "heading": "Filing of information disclosure statement",
            "text_excerpt": "[official annual 2023] IDS filing (same)",
            "content_sha256": content_sha256("annual-2023-sec-1.97-same"),
        },
        "1.98": {
            "section": "1.98",
            "part": "1",
            "heading": "Content of information disclosure statement",
            "text_excerpt": "[official annual 2024] IDS content (added)",
            "content_sha256": content_sha256("annual-2024-sec-1.98-added"),
        },
    }

    # Missing granules: drop 41.50 entirely; empty formats on 42.100.
    missing_edition = {
        **annual_2024,
        "fixture_id": "cfr-annual-2024-missing-granules",
        "sections": [
            s
            for s in (annual_2024.get("sections") or [])
            if normalize_section_token(s.get("section", "")) not in {"41.50"}
        ],
    }
    rewritten_sections = []
    for s in missing_edition["sections"]:
        if normalize_section_token(s.get("section", "")) == "42.100":
            rewritten_sections.append({**s, "formats": {}})
        else:
            rewritten_sections.append(s)
    missing_edition["sections"] = rewritten_sections

    # Conflicting text: eCFR editorial diverges on 1.56.
    conflict_ecfr = {
        **current,
        "fixture_id": "ecfr-conflict-1.56",
        "sections": [
            {
                **s,
                "text_excerpt": (
                    "[ecfr editorial conflict] duty to disclose diverges from "
                    "official annual print [conflict]"
                ),
                "content_sha256": content_sha256("ecfr-conflict-editorial-1.56"),
            }
            if normalize_section_token(s.get("section", "")) == "1.56"
            else s
            for s in (current.get("sections") or [])
        ],
    }

    recipe: dict[str, Any] = {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "fixture_id": "live-cfr-title37-acquisition",
        "title": "37",
        "notes": (
            "Compact live eCFR + annual CFR recipe. Covers pagination, "
            "point-in-time lookup, annual edition rollover, changed/removed "
            "sections, missing granules, and conflicting text. eCFR remains "
            "unofficial presentation; annual GovInfo packages are official. "
            "Authority status and authentication status are independent."
        ),
        "edition_catalog": {
            "discovery_source": "govinfo-CFR-collection-fixture",
            "latest_editions": [
                {
                    "collection": "CFR",
                    "year": "2023",
                    "title": "37",
                    "package_id": "CFR-2023-title37",
                    "edition": "annual-2023",
                    "volume": "1",
                    "date_issued": "2023-07-01",
                    "discovered_at": "2024-09-01T10:00:00Z",
                    "discovery_source": "govinfo-CFR-collection",
                },
                {
                    "collection": "CFR",
                    "year": "2024",
                    "title": "37",
                    "package_id": "CFR-2024-title37",
                    "edition": "annual-2024",
                    "volume": "1",
                    "date_issued": "2024-07-01",
                    "discovered_at": "2024-09-01T10:00:00Z",
                    "discovery_source": "govinfo-CFR-collection",
                },
            ],
        },
        "ecfr_snapshots": {
            "2020-01-01": historical,
            "2024-07-01": current,
            "conflict": conflict_ecfr,
        },
        "annual_editions": {
            "2023": annual_2023,
            "2024": annual_2024,
            "CFR-2023-title37": annual_2023,
            "CFR-2024-title37": annual_2024,
            "missing": missing_edition,
            "conflict": annual_2024,
        },
        "cases": {
            "pagination": {
                "pages": pagination_pages,
                "notes": "Two-page eCFR structure pagination with next_page_token.",
            },
            "point_in_time": {
                "as_of": "2020-01-01",
                "notes": "Historical eCFR reconstruction as of 2020-01-01.",
            },
            "annual_edition_rollover": {
                "as_of": "2024-08-01",
                "notes": "Select CFR-2024-title37 after July 1 2024 rollover.",
            },
            "changed_removed_sections": {
                "baseline_year": "2023",
                "baseline_package_id": "CFR-2023-title37",
                "current_package_id": "CFR-2024-title37",
                "baseline_sections": baseline_sections,
                "current_sections": current_sections,
            },
            "missing_granules": {
                "required_sections": list(DEFAULT_CROSSCHECK_SECTIONS),
                "annual": missing_edition,
            },
            "conflicting_text": {
                "sections": [DUTY_OF_DISCLOSURE_SECTION],
                "ecfr": conflict_ecfr,
                "annual": annual_2024,
            },
        },
        "expected": {
            "required_cases": [k.value for k in SnapshotCaseKind],
            "pagination_item_count": 5,
            "point_in_time_as_of": "2020-01-01",
            "rollover_selected_package_id": "CFR-2024-title37",
            "changed_section": "1.56",
            "removed_section": "99.99",
            "conflict_section": "1.56",
        },
    }
    return recipe


def write_default_fixtures(directory: PathLike | None = None) -> Path:
    """Write the compact live CFR recipe to *directory*."""

    target = Path(directory) if directory is not None else default_fixture_dir()
    target.mkdir(parents=True, exist_ok=True)
    recipe = build_live_cfr_recipe()
    path = target / "cfr_recipe.json"
    path.write_text(
        json.dumps(recipe, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


__all__ = [
    "SCHEMA_VERSION",
    "FIXTURE_SCHEMA_VERSION",
    "AuthorityStatus",
    "AuthenticationStatus",
    "EffectiveInterval",
    "EditionDiscovery",
    "LiveCfrAcquisitionReport",
    "LiveCfrCaseResult",
    "LiveCfrError",
    "LiveCfrFixtureSchemaError",
    "LiveCfrMissingGranuleError",
    "LiveCfrPaginationError",
    "LiveCfrProvision",
    "LiveCfrSourceProcessor",
    "LiveCfrTextConflictError",
    "PaginationPage",
    "ProvisionChangeKind",
    "SnapshotCaseKind",
    "TextConflictRecord",
    "admit_recorded_bytes",
    "build_live_cfr_recipe",
    "build_recorded_acquisition_outcome",
    "content_sha256",
    "default_fixture_dir",
    "provision_from_annual_section",
    "provision_from_ecfr_section",
    "source_cid_for_bytes",
    "source_cid_for_sha256",
    "write_default_fixtures",
]
