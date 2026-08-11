"""Live USPTO MPEP, forms, fees, and examination guidance acquisition (PATLAW-132).

Discovers dated MPEP editions/revisions, official forms/instructions, fee
schedules, and examination guidance; acquires immutable bytes/metadata; detects
replacements; and preserves the guidance/nonbinding authority class and
applicable dates.

Design invariants:

* Authority class is always ``guidance`` (non-binding). This processor never
  classifies MPEP, forms, fee schedules, FAQs, or examination guides as
  statutes or regulations and never automates filing or payment.
* Recorded **rollover**, **removal**, and **conflict** fixtures retain both
  the old and new versions (never silent overwrite or silent latest selection).
* Every admitted item carries **source CID**, **source span**, **retrieved**,
  **published**, and **effective** metadata where supplied; unavailable dates
  and supersession remain **explicit**.
* Links and edition selectors never silently resolve to the hard-coded token
  ``\"latest\"``; concrete edition/revision/version identifiers are required.
* Live network I/O is opt-in via :class:`PatentSourceTransport`; integration
  tests use the compact recorded recipe only.
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

from ipfs_datasets_py.processors.legal_data.patent_authority_contracts_v2 import (
    AcquisitionOutcome,
    AcquisitionOutcomeKind,
    AcquisitionReceipt,
    ContentAddress,
    content_address_bytes,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    SCHEMA_VERSION as AUTHORITY_SCHEMA_VERSION,
    AuthorityTier,
    HardCodedLatestEditionError,
    VerificationState,
    reject_hard_coded_latest,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.mpep_guidance_processor import (
    BindingElevationError,
    FreshnessGap,
    FreshnessGapKind,
    GuidanceKind,
    SupersessionEdge,
    SupersessionRelation,
    normalize_form_paragraph,
    normalize_mpep_section,
    stable_guidance_identity,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.patent_source_transport import (
    PatentSourceTransport,
    SourceFetchRequest,
    SourceTransportError,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.public_law_change_processor import (
    SourceSpan,
)

SCHEMA_VERSION = "live-uspto-guidance-processor-v1"
FIXTURE_SCHEMA_VERSION = "live-uspto-guidance-recipe-v1"

DEFAULT_PROVIDER = "uspto"
DEFAULT_JURISDICTION = "US"
COLLECTION_GUIDANCE = "GUIDANCE"
COLLECTION_MPEP = "MPEP"

USPTO_MPEP_INDEX = "https://www.uspto.gov/web/offices/pac/mpep/index.html"
USPTO_FORMS_BASE = "https://www.uspto.gov/patents/apply/forms"
USPTO_FEES_BASE = "https://www.uspto.gov/learning-and-resources/fees-and-payment"
USPTO_EXAM_GUIDE_BASE = "https://www.uspto.gov/patents/laws/examination-policy"

# Acceptance scenario kinds required by PATLAW-132.
REQUIRED_SCENARIO_KINDS = frozenset(
    {
        "edition_rollover",
        "artifact_removal",
        "version_conflict",
        "supersession",
        "unavailable_date",
        "happy_path",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LATEST_TOKEN_RE = re.compile(r"^\s*latest\s*$", re.IGNORECASE)
_UNAVAILABLE_DATE_MARKERS = frozenset(
    {
        "unavailable",
        "unknown",
        "not_available",
        "n/a",
        "na",
        "null",
        "none",
        "missing",
    }
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LiveUsptoGuidanceError(ValueError):
    """Base error for live USPTO guidance acquisition."""


class FixtureSchemaError(LiveUsptoGuidanceError):
    """Raised when the recorded recipe is malformed."""


class HardCodedLatestError(HardCodedLatestEditionError, LiveUsptoGuidanceError):
    """Raised when a hard-coded ``latest`` edition/version token is supplied."""


class SilentLatestSelectionError(LiveUsptoGuidanceError):
    """Raised when a link would silently resolve to ``latest``."""


class GuidanceElevationError(BindingElevationError, LiveUsptoGuidanceError):
    """Raised when code attempts to elevate guidance to binding law."""


class VersionRetentionError(LiveUsptoGuidanceError):
    """Raised when rollover/removal/conflict drops the prior version."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ScenarioKind(str, Enum):
    """Recorded integration scenario kinds (PATLAW-132 acceptance)."""

    EDITION_ROLLOVER = "edition_rollover"
    ARTIFACT_REMOVAL = "artifact_removal"
    VERSION_CONFLICT = "version_conflict"
    SUPERSESSION = "supersession"
    UNAVAILABLE_DATE = "unavailable_date"
    HAPPY_PATH = "happy_path"
    FORM_REPLACEMENT = "form_replacement"
    FEE_SCHEDULE_ROLLOVER = "fee_schedule_rollover"
    FRESHNESS_GAP = "freshness_gap"

    @classmethod
    def coerce(cls, value: Any) -> "ScenarioKind":
        if isinstance(value, ScenarioKind):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "edition_rollover": cls.EDITION_ROLLOVER,
            "rollover": cls.EDITION_ROLLOVER,
            "mpep_rollover": cls.EDITION_ROLLOVER,
            "artifact_removal": cls.ARTIFACT_REMOVAL,
            "removal": cls.ARTIFACT_REMOVAL,
            "removed": cls.ARTIFACT_REMOVAL,
            "version_conflict": cls.VERSION_CONFLICT,
            "conflict": cls.VERSION_CONFLICT,
            "content_conflict": cls.VERSION_CONFLICT,
            "supersession": cls.SUPERSESSION,
            "supersedes": cls.SUPERSESSION,
            "unavailable_date": cls.UNAVAILABLE_DATE,
            "missing_date": cls.UNAVAILABLE_DATE,
            "date_unavailable": cls.UNAVAILABLE_DATE,
            "happy_path": cls.HAPPY_PATH,
            "success": cls.HAPPY_PATH,
            "acquired": cls.HAPPY_PATH,
            "form_replacement": cls.FORM_REPLACEMENT,
            "fee_schedule_rollover": cls.FEE_SCHEDULE_ROLLOVER,
            "fee_rollover": cls.FEE_SCHEDULE_ROLLOVER,
            "freshness_gap": cls.FRESHNESS_GAP,
            "gap": cls.FRESHNESS_GAP,
        }
        if text not in aliases:
            raise LiveUsptoGuidanceError(f"unsupported scenario kind: {value!r}")
        return aliases[text]


class CaseOutcome(str, Enum):
    """Terminal classification for one recorded / acquired case."""

    ACQUIRED = "acquired"
    ROLLOVER_RETAINED = "rollover_retained"
    REMOVAL_RETAINED = "removal_retained"
    CONFLICT_RETAINED = "conflict_retained"
    SUPERSEDED = "superseded"
    UNAVAILABLE = "unavailable"
    DATE_UNAVAILABLE = "date_unavailable"
    FRESHNESS_GAP = "freshness_gap"
    ERROR = "error"

    @classmethod
    def coerce(cls, value: Any) -> "CaseOutcome":
        if isinstance(value, CaseOutcome):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "acquired": cls.ACQUIRED,
            "verified": cls.ACQUIRED,
            "success": cls.ACQUIRED,
            "resolved": cls.ACQUIRED,
            "rollover_retained": cls.ROLLOVER_RETAINED,
            "rollover": cls.ROLLOVER_RETAINED,
            "removal_retained": cls.REMOVAL_RETAINED,
            "removed": cls.REMOVAL_RETAINED,
            "conflict_retained": cls.CONFLICT_RETAINED,
            "conflict": cls.CONFLICT_RETAINED,
            "superseded": cls.SUPERSEDED,
            "unavailable": cls.UNAVAILABLE,
            "missing": cls.UNAVAILABLE,
            "date_unavailable": cls.DATE_UNAVAILABLE,
            "freshness_gap": cls.FRESHNESS_GAP,
            "error": cls.ERROR,
            "failed": cls.ERROR,
        }
        if text not in aliases:
            raise LiveUsptoGuidanceError(f"unsupported case outcome: {value!r}")
        return aliases[text]


class DateAvailability(str, Enum):
    """Whether a temporal field is present or explicitly unavailable."""

    PRESENT = "present"
    UNAVAILABLE = "unavailable"
    NOT_SUPPLIED = "not_supplied"

    @classmethod
    def coerce(cls, value: Any) -> "DateAvailability":
        if isinstance(value, DateAvailability):
            return value
        if value is None or value == "":
            return cls.NOT_SUPPLIED
        text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        if text in _UNAVAILABLE_DATE_MARKERS or text == "unavailable":
            return cls.UNAVAILABLE
        if text in {"present", "available", "known", "supplied"}:
            return cls.PRESENT
        if text in {"not_supplied", "omitted", "absent"}:
            return cls.NOT_SUPPLIED
        # ISO dates and other concrete values imply present.
        return cls.PRESENT


class VersionRole(str, Enum):
    """Role of a retained guidance version within a multi-version case."""

    PRIOR = "prior"
    SUCCESSOR = "successor"
    CURRENT = "current"
    CONFLICTING_A = "conflicting_a"
    CONFLICTING_B = "conflicting_b"
    REMOVED = "removed"
    SUPERSEDED = "superseded"
    SUPERSEDING = "superseding"
    SOLE = "sole"

    @classmethod
    def coerce(cls, value: Any) -> "VersionRole":
        if isinstance(value, VersionRole):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        for role in cls:
            if role.value == text or role.name.lower() == text:
                return role
        raise LiveUsptoGuidanceError(f"unsupported version role: {value!r}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LiveUsptoGuidanceError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise LiveUsptoGuidanceError(f"{name} must not contain NUL")
    return value.strip()


def _optional_str(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, "value")


def _require_sha256(value: Any, name: str = "sha256") -> str:
    text = _require_non_empty_str(value, name).lower()
    if not _SHA256_RE.fullmatch(text):
        raise LiveUsptoGuidanceError(f"{name} must be a lowercase 64-char hex SHA-256")
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
            raise LiveUsptoGuidanceError(f"{name} must be ISO-8601 datetime") from exc
    else:
        raise LiveUsptoGuidanceError(f"{name} must be a datetime or ISO-8601 string")
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


def _parse_optional_date(value: Any, *, name: str = "date") -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if text.lower().replace("-", "_").replace(" ", "_") in _UNAVAILABLE_DATE_MARKERS:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise LiveUsptoGuidanceError(f"{name} must be an ISO date") from exc


def _date_to_str(value: Optional[date]) -> Optional[str]:
    return None if value is None else value.isoformat()


def _deep_sorted(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(k): _deep_sorted(value[k])
            for k in sorted(value.keys(), key=lambda x: str(x))
        }
    if isinstance(value, (list, tuple)):
        return [_deep_sorted(v) for v in value]
    return value


def content_sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def source_cid_for_bytes(data: bytes | str) -> str:
    """Content-address *data* and return the CID (or sha256 fallback form)."""

    if isinstance(data, str):
        raw = data.encode("utf-8")
    else:
        raw = bytes(data)
    address = content_address_bytes(raw)
    return address.cid


def source_cid_for_sha256(digest: str) -> str:
    """Stable CID-like address from a known content SHA-256."""

    digest = _require_sha256(digest, "digest")
    return content_address_bytes(bytes.fromhex(digest)).cid


def reject_latest_token(value: Any, *, field_name: str) -> str:
    """Reject hard-coded ``latest`` edition/version selectors."""

    text = _require_non_empty_str(str(value), field_name)
    reject_hard_coded_latest(text, field_name=field_name)
    if _LATEST_TOKEN_RE.fullmatch(text):
        raise HardCodedLatestError(
            f"{field_name} must not be the hard-coded token 'latest'"
        )
    # Also reject compound tokens that embed "latest" as a segment.
    segments = re.split(r"[-_./\s]+", text.lower())
    if "latest" in segments:
        raise HardCodedLatestError(
            f"{field_name} must not contain the hard-coded token 'latest': {text!r}"
        )
    return text


def resolve_guidance_link(
    *,
    link_target: str,
    available_versions: Mapping[str, str],
    prefer_version: str | None = None,
) -> str:
    """Resolve a guidance link to a concrete version id (never silent latest).

    Parameters
    ----------
    link_target:
        Requested version key or identity.
    available_versions:
        Mapping of version key → concrete identity (edition/revision/version id).
    prefer_version:
        Optional explicit preferred version key. When omitted the caller must
        supply a concrete ``link_target`` that exists in *available_versions*.
    """

    target = _require_non_empty_str(link_target, "link_target")
    if _LATEST_TOKEN_RE.fullmatch(target) or target.strip().lower() == "latest":
        raise SilentLatestSelectionError(
            "guidance links must not silently select 'latest'; supply a concrete "
            "edition/revision/version identity"
        )
    reject_latest_token(target, field_name="link_target")

    if prefer_version is not None:
        prefer = reject_latest_token(prefer_version, field_name="prefer_version")
        if prefer not in available_versions:
            raise LiveUsptoGuidanceError(
                f"prefer_version {prefer!r} not in available versions "
                f"{sorted(available_versions)}"
            )
        return available_versions[prefer]

    if target in available_versions:
        concrete = available_versions[target]
        reject_latest_token(concrete, field_name="resolved_version")
        return concrete

    # Direct concrete identity (not a lookup key).
    if target not in available_versions.values():
        # Allow passthrough of already-concrete identities.
        return reject_latest_token(target, field_name="link_target")
    return reject_latest_token(target, field_name="link_target")


def _span_for_excerpt(
    excerpt: str | None,
    *,
    fmt: str | None = None,
) -> SourceSpan:
    text = excerpt or ""
    return SourceSpan(
        start=0,
        end=max(0, len(text)),
        unit="char",
        excerpt=text or None,
        format=fmt or "text/html",
    )


def _date_availability_from_fields(
    *,
    date_value: Any,
    availability_flag: Any,
) -> DateAvailability:
    if availability_flag is not None and availability_flag != "":
        return DateAvailability.coerce(availability_flag)
    if date_value is None or date_value == "":
        return DateAvailability.NOT_SUPPLIED
    if isinstance(date_value, str):
        lowered = date_value.strip().lower().replace("-", "_").replace(" ", "_")
        if lowered in _UNAVAILABLE_DATE_MARKERS:
            return DateAvailability.UNAVAILABLE
    return DateAvailability.PRESENT


def default_fixture_dir() -> Path:
    """Repository fixture directory for the live USPTO guidance recipe."""

    here = Path(__file__).resolve()
    candidates = [
        here.parents[4]
        / "tests"
        / "fixtures"
        / "legal_data"
        / "patent_authorities"
        / "live",
        Path.cwd()
        / "tests"
        / "fixtures"
        / "legal_data"
        / "patent_authorities"
        / "live",
    ]
    for path in candidates:
        if (path / "uspto_guidance_recipe.json").is_file() or path.is_dir():
            return path
    return candidates[0]


def load_json_fixture(path: PathLike) -> dict[str, Any]:
    target = Path(path)
    if not target.is_file():
        raise FixtureSchemaError(f"fixture not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FixtureSchemaError(f"invalid JSON in {target}: {exc}") from exc
    if not isinstance(payload, dict):
        raise FixtureSchemaError(f"fixture root must be an object: {target}")
    return payload


# ---------------------------------------------------------------------------
# Domain records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TemporalField:
    """A date field that may be present, not supplied, or explicitly unavailable."""

    value: Optional[date] = None
    availability: DateAvailability = DateAvailability.NOT_SUPPLIED
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "availability", DateAvailability.coerce(self.availability)
        )
        if self.value is not None and not isinstance(self.value, date):
            object.__setattr__(
                self, "value", _parse_optional_date(self.value, name="value")
            )
        if self.availability is DateAvailability.UNAVAILABLE:
            object.__setattr__(self, "value", None)
        if self.availability is DateAvailability.PRESENT and self.value is None:
            # Present without a value is inconsistent; treat as unavailable.
            object.__setattr__(self, "availability", DateAvailability.UNAVAILABLE)
        if self.notes is not None:
            object.__setattr__(
                self, "notes", _require_non_empty_str(self.notes, "notes")
            )

    @property
    def is_unavailable(self) -> bool:
        return self.availability is DateAvailability.UNAVAILABLE

    @property
    def is_present(self) -> bool:
        return self.availability is DateAvailability.PRESENT and self.value is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "availability": self.availability.value,
            "notes": self.notes,
            "value": _date_to_str(self.value),
        }

    @classmethod
    def from_dict(cls, value: Any) -> "TemporalField":
        if value is None or value == "":
            return cls(value=None, availability=DateAvailability.NOT_SUPPLIED)
        if isinstance(value, TemporalField):
            return value
        if isinstance(value, (date, datetime, str)) and not isinstance(value, Mapping):
            # Bare date string or explicit unavailable marker.
            if isinstance(value, str):
                lowered = value.strip().lower().replace("-", "_").replace(" ", "_")
                if lowered in _UNAVAILABLE_DATE_MARKERS:
                    return cls(
                        value=None,
                        availability=DateAvailability.UNAVAILABLE,
                        notes="date explicitly marked unavailable",
                    )
            parsed = _parse_optional_date(value, name="temporal")
            return cls(value=parsed, availability=DateAvailability.PRESENT)
        if not isinstance(value, Mapping):
            raise LiveUsptoGuidanceError("temporal field must be a mapping or date")
        avail = _date_availability_from_fields(
            date_value=value.get("value") or value.get("date"),
            availability_flag=value.get("availability") or value.get("status"),
        )
        return cls(
            value=value.get("value") or value.get("date"),
            availability=avail,
            notes=value.get("notes"),
        )


@dataclass(frozen=True, slots=True)
class LiveGuidanceVersion:
    """One retained version of a guidance artifact (old or new).

    Rollover, removal, and conflict fixtures always retain multiple versions
    as distinct :class:`LiveGuidanceVersion` rows rather than overwriting.
    """

    version_id: str
    role: VersionRole
    content_sha256: str
    source_cid: str
    source_span: SourceSpan
    retrieved_at: datetime
    edition: Optional[str] = None
    revision: Optional[str] = None
    version_label: Optional[str] = None
    published: TemporalField = field(default_factory=TemporalField)
    effective: TemporalField = field(default_factory=TemporalField)
    source_url: Optional[str] = None
    media_type: str = "text/html"
    text_excerpt: Optional[str] = None
    body_text: Optional[str] = None
    http_status: Optional[int] = None
    removed: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "version_id",
            reject_latest_token(self.version_id, field_name="version_id"),
        )
        object.__setattr__(self, "role", VersionRole.coerce(self.role))
        object.__setattr__(
            self,
            "content_sha256",
            _require_sha256(self.content_sha256, "content_sha256"),
        )
        cid = _require_non_empty_str(self.source_cid, "source_cid")
        object.__setattr__(self, "source_cid", cid)
        if not isinstance(self.source_span, SourceSpan):
            object.__setattr__(
                self, "source_span", SourceSpan.from_dict(self.source_span)  # type: ignore[arg-type]
            )
        if not isinstance(self.retrieved_at, datetime):
            object.__setattr__(
                self, "retrieved_at", _parse_utc(self.retrieved_at, name="retrieved_at")
            )
        for name in ("edition", "revision", "version_label"):
            raw = getattr(self, name)
            if raw is not None:
                cleaned = reject_latest_token(str(raw), field_name=name)
                object.__setattr__(self, name, cleaned)
        if not isinstance(self.published, TemporalField):
            object.__setattr__(self, "published", TemporalField.from_dict(self.published))
        if not isinstance(self.effective, TemporalField):
            object.__setattr__(self, "effective", TemporalField.from_dict(self.effective))
        if self.source_url is not None:
            object.__setattr__(
                self,
                "source_url",
                _require_non_empty_str(self.source_url, "source_url"),
            )
        object.__setattr__(
            self, "media_type", _require_non_empty_str(self.media_type, "media_type")
        )
        if self.text_excerpt is not None:
            object.__setattr__(self, "text_excerpt", str(self.text_excerpt))
        if self.body_text is not None:
            object.__setattr__(self, "body_text", str(self.body_text))
        if self.http_status is not None:
            object.__setattr__(self, "http_status", int(self.http_status))
        if not isinstance(self.metadata, Mapping):
            raise LiveUsptoGuidanceError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "body_text": self.body_text,
            "content_sha256": self.content_sha256,
            "edition": self.edition,
            "effective": self.effective.to_dict(),
            "http_status": self.http_status,
            "media_type": self.media_type,
            "metadata": _deep_sorted(self.metadata),
            "published": self.published.to_dict(),
            "removed": bool(self.removed),
            "retrieved_at": _format_utc(self.retrieved_at),
            "revision": self.revision,
            "role": self.role.value,
            "source_cid": self.source_cid,
            "source_span": self.source_span.to_dict(),
            "source_url": self.source_url,
            "text_excerpt": self.text_excerpt,
            "version_id": self.version_id,
            "version_label": self.version_label,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "LiveGuidanceVersion":
        if not isinstance(value, Mapping):
            raise FixtureSchemaError("version must be a mapping")
        digest = value.get("content_sha256") or value.get("sha256")
        if not digest:
            seed = value.get("body_text") or value.get("text_excerpt") or value.get("version_id")
            digest = content_sha256(str(seed or "empty"))
        digest = _require_sha256(digest, "content_sha256")
        cid = value.get("source_cid") or value.get("cid")
        if not cid:
            cid = source_cid_for_sha256(digest)
        span_raw = value.get("source_span") or value.get("span")
        if span_raw is None:
            span_raw = _span_for_excerpt(
                value.get("text_excerpt") or value.get("body_text"),
                fmt=value.get("media_type"),
            )
        elif isinstance(span_raw, Mapping):
            span_raw = SourceSpan.from_dict(span_raw)
        retrieved = value.get("retrieved_at") or value.get("retrieved")
        if retrieved is None:
            retrieved = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        published = TemporalField.from_dict(
            value.get("published")
            if "published" in value
            else value.get("publication_date")
            if "publication_date" in value
            else {
                "value": value.get("publication_date") or value.get("published_at"),
                "availability": value.get("published_availability")
                or value.get("publication_date_availability"),
            }
        )
        effective = TemporalField.from_dict(
            value.get("effective")
            if "effective" in value
            else {
                "value": value.get("effective_start")
                or value.get("effective_date")
                or value.get("effective_at"),
                "availability": value.get("effective_availability")
                or value.get("effective_date_availability"),
            }
        )
        return cls(
            version_id=str(value.get("version_id") or value.get("id") or ""),
            role=VersionRole.coerce(value.get("role") or VersionRole.SOLE),
            content_sha256=digest,
            source_cid=str(cid),
            source_span=span_raw if isinstance(span_raw, SourceSpan) else SourceSpan.from_dict(span_raw),
            retrieved_at=retrieved,
            edition=value.get("edition"),
            revision=value.get("revision"),
            version_label=value.get("version_label") or value.get("label"),
            published=published,
            effective=effective,
            source_url=value.get("source_url"),
            media_type=str(value.get("media_type") or "text/html"),
            text_excerpt=value.get("text_excerpt"),
            body_text=value.get("body_text"),
            http_status=value.get("http_status"),
            removed=bool(value.get("removed", False)),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class LiveGuidanceItem:
    """Acquired guidance artifact with retained version history and provenance.

    Always ``authority_tier=guidance`` and ``is_binding=False``. Every item
    exposes source CID/span and retrieved/published/effective metadata on each
    retained version (unavailable dates stay explicit on the TemporalField).
    """

    item_id: str
    kind: GuidanceKind
    authority_tier: AuthorityTier = AuthorityTier.GUIDANCE
    is_binding: bool = False
    anchor: Optional[str] = None
    citation: Optional[str] = None
    title: Optional[str] = None
    stable_id: Optional[str] = None
    versions: tuple[LiveGuidanceVersion, ...] = ()
    supersedes: tuple[str, ...] = ()
    superseded_by: Optional[str] = None
    cutoff: Optional[date] = None
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "item_id", reject_latest_token(self.item_id, field_name="item_id")
        )
        object.__setattr__(self, "kind", GuidanceKind.coerce(self.kind))
        if isinstance(self.authority_tier, AuthorityTier):
            tier = self.authority_tier
        else:
            tier = AuthorityTier(
                str(self.authority_tier).strip().lower().replace("_", "-")
            )
        if tier is not AuthorityTier.GUIDANCE:
            raise GuidanceElevationError(
                f"guidance items must use authority_tier=guidance, got {tier.value!r}"
            )
        object.__setattr__(self, "authority_tier", AuthorityTier.GUIDANCE)
        if self.is_binding:
            raise GuidanceElevationError("guidance items must not be marked binding/law")
        object.__setattr__(self, "is_binding", False)

        if self.anchor is not None:
            if self.kind is GuidanceKind.MPEP_SECTION:
                object.__setattr__(self, "anchor", normalize_mpep_section(self.anchor))
            elif self.kind is GuidanceKind.FORM_PARAGRAPH:
                object.__setattr__(self, "anchor", normalize_form_paragraph(self.anchor))
            else:
                object.__setattr__(
                    self, "anchor", _require_non_empty_str(str(self.anchor), "anchor")
                )
        for name in ("citation", "title", "superseded_by", "notes"):
            raw = getattr(self, name)
            if raw is not None:
                object.__setattr__(self, name, _require_non_empty_str(str(raw), name))
        if self.cutoff is not None and not isinstance(self.cutoff, date):
            object.__setattr__(
                self, "cutoff", _parse_optional_date(self.cutoff, name="cutoff")
            )
        versions: list[LiveGuidanceVersion] = []
        for ver in self.versions or ():
            if isinstance(ver, LiveGuidanceVersion):
                versions.append(ver)
            elif isinstance(ver, Mapping):
                versions.append(LiveGuidanceVersion.from_dict(ver))
            else:
                raise LiveUsptoGuidanceError("versions must be LiveGuidanceVersion or mappings")
        if not versions:
            raise LiveUsptoGuidanceError(
                f"item {self.item_id!r} must retain at least one version"
            )
        object.__setattr__(self, "versions", tuple(versions))
        supersedes = tuple(
            reject_latest_token(str(s), field_name="supersedes item")
            for s in (self.supersedes or ())
        )
        object.__setattr__(self, "supersedes", supersedes)
        if self.stable_id is None and self.anchor is not None:
            object.__setattr__(
                self,
                "stable_id",
                stable_guidance_identity(kind=self.kind, anchor=self.anchor),
            )
        elif self.stable_id is not None:
            object.__setattr__(
                self,
                "stable_id",
                reject_latest_token(self.stable_id, field_name="stable_id"),
            )
        if not isinstance(self.metadata, Mapping):
            raise LiveUsptoGuidanceError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def version_ids(self) -> tuple[str, ...]:
        return tuple(v.version_id for v in self.versions)

    def version_for_role(self, role: VersionRole | str) -> Optional[LiveGuidanceVersion]:
        role_v = VersionRole.coerce(role)
        for ver in self.versions:
            if ver.role is role_v:
                return ver
        return None

    def retains_prior_and_successor(self) -> bool:
        roles = {v.role for v in self.versions}
        has_prior = bool(roles & {VersionRole.PRIOR, VersionRole.REMOVED, VersionRole.SUPERSEDED, VersionRole.CONFLICTING_A})
        has_new = bool(
            roles
            & {
                VersionRole.SUCCESSOR,
                VersionRole.CURRENT,
                VersionRole.SUPERSEDING,
                VersionRole.CONFLICTING_B,
            }
        )
        return has_prior and has_new and len(self.versions) >= 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor": self.anchor,
            "authority_tier": self.authority_tier.value,
            "citation": self.citation,
            "cutoff": _date_to_str(self.cutoff),
            "is_binding": False,
            "item_id": self.item_id,
            "kind": self.kind.value,
            "metadata": _deep_sorted(self.metadata),
            "notes": self.notes,
            "stable_id": self.stable_id,
            "superseded_by": self.superseded_by,
            "supersedes": list(self.supersedes),
            "title": self.title,
            "versions": [v.to_dict() for v in self.versions],
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "LiveGuidanceItem":
        if not isinstance(value, Mapping):
            raise FixtureSchemaError("item must be a mapping")
        raw_versions = value.get("versions") or value.get("retained_versions") or []
        if not raw_versions and value.get("content_sha256"):
            # Compact single-version form at the item root.
            raw_versions = [
                {
                    "version_id": value.get("version_id")
                    or value.get("item_id")
                    or value.get("guidance_id"),
                    "role": value.get("role") or VersionRole.SOLE.value,
                    "content_sha256": value.get("content_sha256"),
                    "source_cid": value.get("source_cid"),
                    "source_span": value.get("source_span"),
                    "retrieved_at": value.get("retrieved_at"),
                    "edition": value.get("edition"),
                    "revision": value.get("revision"),
                    "version_label": value.get("version_label"),
                    "published": value.get("published") or value.get("publication_date"),
                    "effective": value.get("effective") or value.get("effective_start"),
                    "published_availability": value.get("published_availability"),
                    "effective_availability": value.get("effective_availability"),
                    "source_url": value.get("source_url"),
                    "media_type": value.get("media_type"),
                    "text_excerpt": value.get("text_excerpt"),
                    "body_text": value.get("body_text"),
                    "http_status": value.get("http_status"),
                    "removed": value.get("removed", False),
                    "metadata": value.get("version_metadata") or {},
                }
            ]
        return cls(
            item_id=str(
                value.get("item_id") or value.get("guidance_id") or value.get("id") or ""
            ),
            kind=GuidanceKind.coerce(value.get("kind") or GuidanceKind.OTHER),
            authority_tier=value.get("authority_tier", AuthorityTier.GUIDANCE),
            is_binding=bool(value.get("is_binding", False)),
            anchor=value.get("anchor") or value.get("section") or value.get("form_paragraph"),
            citation=value.get("citation"),
            title=value.get("title"),
            stable_id=value.get("stable_id"),
            versions=tuple(raw_versions),
            supersedes=tuple(value.get("supersedes") or ()),
            superseded_by=value.get("superseded_by"),
            cutoff=value.get("cutoff"),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class GuidanceCase:
    """One recorded integration / acquisition case."""

    case_id: str
    scenario: ScenarioKind
    items: tuple[LiveGuidanceItem, ...]
    expected_outcome: Optional[CaseOutcome] = None
    prior_edition: Optional[str] = None
    successor_edition: Optional[str] = None
    supersessions: tuple[SupersessionEdge, ...] = ()
    freshness_gaps: tuple[FreshnessGap, ...] = ()
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "case_id", _require_non_empty_str(self.case_id, "case_id")
        )
        object.__setattr__(self, "scenario", ScenarioKind.coerce(self.scenario))
        items: list[LiveGuidanceItem] = []
        for item in self.items or ():
            if isinstance(item, LiveGuidanceItem):
                items.append(item)
            elif isinstance(item, Mapping):
                items.append(LiveGuidanceItem.from_dict(item))
            else:
                raise FixtureSchemaError("case items must be LiveGuidanceItem or mappings")
        object.__setattr__(self, "items", tuple(items))
        if self.expected_outcome is not None:
            object.__setattr__(
                self, "expected_outcome", CaseOutcome.coerce(self.expected_outcome)
            )
        for name in ("prior_edition", "successor_edition"):
            raw = getattr(self, name)
            if raw is not None:
                object.__setattr__(
                    self, name, reject_latest_token(str(raw), field_name=name)
                )
        edges: list[SupersessionEdge] = []
        for edge in self.supersessions or ():
            if isinstance(edge, SupersessionEdge):
                edges.append(edge)
            elif isinstance(edge, Mapping):
                edges.append(SupersessionEdge.from_dict(edge))
            else:
                raise FixtureSchemaError("supersessions must be edges or mappings")
        object.__setattr__(self, "supersessions", tuple(edges))
        gaps: list[FreshnessGap] = []
        for gap in self.freshness_gaps or ():
            if isinstance(gap, FreshnessGap):
                gaps.append(gap)
            elif isinstance(gap, Mapping):
                gaps.append(FreshnessGap.from_dict(gap))
            else:
                raise FixtureSchemaError("freshness_gaps must be FreshnessGap or mappings")
        object.__setattr__(self, "freshness_gaps", tuple(gaps))
        if self.notes is not None:
            object.__setattr__(
                self, "notes", _require_non_empty_str(self.notes, "notes")
            )
        if not isinstance(self.metadata, Mapping):
            raise LiveUsptoGuidanceError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "expected_outcome": (
                None if self.expected_outcome is None else self.expected_outcome.value
            ),
            "freshness_gaps": [g.to_dict() for g in self.freshness_gaps],
            "items": [i.to_dict() for i in self.items],
            "metadata": _deep_sorted(self.metadata),
            "notes": self.notes,
            "prior_edition": self.prior_edition,
            "scenario": self.scenario.value,
            "successor_edition": self.successor_edition,
            "supersessions": [e.to_dict() for e in self.supersessions],
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "GuidanceCase":
        if not isinstance(value, Mapping):
            raise FixtureSchemaError("case must be a mapping")
        return cls(
            case_id=str(value.get("case_id") or value.get("id") or ""),
            scenario=ScenarioKind.coerce(value.get("scenario") or value.get("kind")),
            items=tuple(value.get("items") or value.get("artifacts") or ()),
            expected_outcome=value.get("expected_outcome") or value.get("outcome"),
            prior_edition=value.get("prior_edition"),
            successor_edition=value.get("successor_edition"),
            supersessions=tuple(value.get("supersessions") or ()),
            freshness_gaps=tuple(value.get("freshness_gaps") or ()),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class GuidanceCaseResult:
    """Adjudicated result for one guidance acquisition case."""

    case: GuidanceCase
    outcome: CaseOutcome
    items: tuple[LiveGuidanceItem, ...]
    retained_version_ids: tuple[str, ...]
    reasons: tuple[str, ...] = ()
    supersessions: tuple[SupersessionEdge, ...] = ()
    freshness_gaps: tuple[FreshnessGap, ...] = ()
    verification_state: VerificationState = VerificationState.UNVERIFIED
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome", CaseOutcome.coerce(self.outcome))
        if not isinstance(self.verification_state, VerificationState):
            object.__setattr__(
                self,
                "verification_state",
                VerificationState(str(self.verification_state)),
            )
        object.__setattr__(self, "items", tuple(self.items or ()))
        object.__setattr__(
            self, "retained_version_ids", tuple(self.retained_version_ids or ())
        )
        object.__setattr__(self, "reasons", tuple(self.reasons or ()))
        object.__setattr__(self, "supersessions", tuple(self.supersessions or ()))
        object.__setattr__(self, "freshness_gaps", tuple(self.freshness_gaps or ()))

    @property
    def retains_old_and_new(self) -> bool:
        return len(self.retained_version_ids) >= 2

    def all_items_have_provenance(self) -> bool:
        """Every version has source CID/span/retrieved and published/effective fields."""

        for item in self.items:
            if item.authority_tier is not AuthorityTier.GUIDANCE:
                return False
            for ver in item.versions:
                if not ver.source_cid:
                    return False
                if ver.source_span is None:
                    return False
                if ver.retrieved_at is None:
                    return False
                # published / effective must be TemporalField instances (may be unavailable)
                if not isinstance(ver.published, TemporalField):
                    return False
                if not isinstance(ver.effective, TemporalField):
                    return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case.case_id,
            "freshness_gaps": [g.to_dict() for g in self.freshness_gaps],
            "items": [i.to_dict() for i in self.items],
            "notes": self.notes,
            "outcome": self.outcome.value,
            "reasons": list(self.reasons),
            "retained_version_ids": list(self.retained_version_ids),
            "scenario": self.case.scenario.value,
            "supersessions": [e.to_dict() for e in self.supersessions],
            "verification_state": self.verification_state.value,
        }


@dataclass(frozen=True, slots=True)
class LiveUsptoGuidanceReport:
    """Batch acquisition report over a recorded recipe (or live batch)."""

    results: tuple[GuidanceCaseResult, ...]
    schema_version: str = SCHEMA_VERSION
    recipe_id: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "results", tuple(self.results or ()))
        if self.retrieved_at is not None and not isinstance(self.retrieved_at, datetime):
            object.__setattr__(
                self,
                "retrieved_at",
                _parse_utc(self.retrieved_at, name="retrieved_at"),
            )
        if not isinstance(self.metadata, Mapping):
            raise LiveUsptoGuidanceError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def scenario_kinds(self) -> frozenset[str]:
        return frozenset(r.case.scenario.value for r in self.results)

    def results_for_scenario(
        self, scenario: ScenarioKind | str
    ) -> list[GuidanceCaseResult]:
        kind = ScenarioKind.coerce(scenario)
        return [r for r in self.results if r.case.scenario is kind]

    def covers_required_scenarios(self) -> bool:
        return REQUIRED_SCENARIO_KINDS <= self.scenario_kinds

    def missing_required_scenarios(self) -> frozenset[str]:
        return REQUIRED_SCENARIO_KINDS - self.scenario_kinds

    def all_items(self) -> list[LiveGuidanceItem]:
        items: list[LiveGuidanceItem] = []
        for result in self.results:
            items.extend(result.items)
        return items

    def all_versions(self) -> list[LiveGuidanceVersion]:
        versions: list[LiveGuidanceVersion] = []
        for item in self.all_items():
            versions.extend(item.versions)
        return versions

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": _deep_sorted(self.metadata),
            "notes": self.notes,
            "recipe_id": self.recipe_id,
            "results": [r.to_dict() for r in self.results],
            "retrieved_at": (
                None if self.retrieved_at is None else _format_utc(self.retrieved_at)
            ),
            "schema_version": self.schema_version,
            "scenario_kinds": sorted(self.scenario_kinds),
        }


# ---------------------------------------------------------------------------
# Case adjudication
# ---------------------------------------------------------------------------


def _collect_retained_version_ids(items: Sequence[LiveGuidanceItem]) -> tuple[str, ...]:
    ids: list[str] = []
    seen: set[str] = set()
    for item in items:
        for ver in item.versions:
            if ver.version_id not in seen:
                seen.add(ver.version_id)
                ids.append(ver.version_id)
    return tuple(ids)


def _assert_multi_version_retention(
    case: GuidanceCase,
    items: Sequence[LiveGuidanceItem],
) -> list[str]:
    """Ensure rollover/removal/conflict retain old and new versions."""

    reasons: list[str] = []
    multi_scenarios = {
        ScenarioKind.EDITION_ROLLOVER,
        ScenarioKind.ARTIFACT_REMOVAL,
        ScenarioKind.VERSION_CONFLICT,
        ScenarioKind.FORM_REPLACEMENT,
        ScenarioKind.FEE_SCHEDULE_ROLLOVER,
        ScenarioKind.SUPERSESSION,
    }
    if case.scenario not in multi_scenarios:
        return reasons

    retained = _collect_retained_version_ids(items)
    if len(retained) < 2:
        raise VersionRetentionError(
            f"case {case.case_id!r} scenario {case.scenario.value} must retain "
            f"old and new versions; got {retained!r}"
        )
    # Digests must differ across retained versions (true replacement/conflict).
    digests = {v.content_sha256 for item in items for v in item.versions}
    if len(digests) < 2 and case.scenario is not ScenarioKind.ARTIFACT_REMOVAL:
        # Removal may keep identical content with removed flag; still need 2 rows.
        if case.scenario is ScenarioKind.VERSION_CONFLICT:
            raise VersionRetentionError(
                f"conflict case {case.case_id!r} must retain distinct content digests"
            )
    for item in items:
        if case.scenario in {
            ScenarioKind.EDITION_ROLLOVER,
            ScenarioKind.VERSION_CONFLICT,
            ScenarioKind.ARTIFACT_REMOVAL,
            ScenarioKind.SUPERSESSION,
        }:
            if len(item.versions) < 2 and len(items) < 2:
                raise VersionRetentionError(
                    f"case {case.case_id!r} item {item.item_id!r} must retain "
                    "prior and successor versions"
                )
    reasons.append(
        f"retained {len(retained)} version(s): {', '.join(retained)}"
    )
    return reasons


def adjudicate_case(case: GuidanceCase) -> CaseOutcome:
    """Determine the terminal outcome for a recorded guidance case."""

    if case.expected_outcome is not None:
        return case.expected_outcome
    scenario = case.scenario
    if scenario is ScenarioKind.EDITION_ROLLOVER:
        return CaseOutcome.ROLLOVER_RETAINED
    if scenario is ScenarioKind.ARTIFACT_REMOVAL:
        return CaseOutcome.REMOVAL_RETAINED
    if scenario is ScenarioKind.VERSION_CONFLICT:
        return CaseOutcome.CONFLICT_RETAINED
    if scenario is ScenarioKind.SUPERSESSION:
        return CaseOutcome.SUPERSEDED
    if scenario is ScenarioKind.UNAVAILABLE_DATE:
        return CaseOutcome.DATE_UNAVAILABLE
    if scenario is ScenarioKind.FRESHNESS_GAP:
        return CaseOutcome.FRESHNESS_GAP
    if scenario in {
        ScenarioKind.HAPPY_PATH,
        ScenarioKind.FORM_REPLACEMENT,
        ScenarioKind.FEE_SCHEDULE_ROLLOVER,
    }:
        return CaseOutcome.ACQUIRED
    return CaseOutcome.ACQUIRED


def process_case(
    case: GuidanceCase,
    *,
    retrieved_at: datetime | None = None,
) -> GuidanceCaseResult:
    """Acquire (from recorded metadata) and adjudicate one guidance case."""

    when = retrieved_at or datetime(2024, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
    items = case.items
    reasons: list[str] = []

    # Stamp retrieved_at when a version omitted it (should already be set).
    stamped: list[LiveGuidanceItem] = []
    for item in items:
        new_versions: list[LiveGuidanceVersion] = []
        for ver in item.versions:
            if ver.retrieved_at is None:
                new_versions.append(
                    LiveGuidanceVersion.from_dict(
                        {**ver.to_dict(), "retrieved_at": _format_utc(when)}
                    )
                )
            else:
                new_versions.append(ver)
        stamped.append(
            LiveGuidanceItem.from_dict(
                {**item.to_dict(), "versions": [v.to_dict() for v in new_versions]}
            )
        )
    items = tuple(stamped)

    retention_reasons = _assert_multi_version_retention(case, items)
    reasons.extend(retention_reasons)

    if case.scenario is ScenarioKind.EDITION_ROLLOVER:
        if case.prior_edition:
            reasons.append(
                f"edition rollover {case.prior_edition!r} → "
                f"{case.successor_edition or 'successor'}"
            )
        reasons.append("prior and successor MPEP/guidance editions retained")
    if case.scenario is ScenarioKind.ARTIFACT_REMOVAL:
        removed = [
            v
            for item in items
            for v in item.versions
            if v.removed or v.role is VersionRole.REMOVED
        ]
        if not removed:
            raise VersionRetentionError(
                f"removal case {case.case_id!r} must mark at least one version removed"
            )
        reasons.append(
            f"{len(removed)} removed version(s) retained alongside current inventory"
        )
    if case.scenario is ScenarioKind.VERSION_CONFLICT:
        digests = {v.content_sha256 for item in items for v in item.versions}
        if len(digests) < 2:
            raise VersionRetentionError(
                f"conflict case {case.case_id!r} needs distinct version digests"
            )
        reasons.append("conflicting versions retained; neither silently selected as latest")
    if case.scenario is ScenarioKind.SUPERSESSION:
        if not case.supersessions and not any(i.supersedes for i in items):
            raise LiveUsptoGuidanceError(
                f"supersession case {case.case_id!r} must declare supersession edges"
            )
        for edge in case.supersessions:
            if edge.elevates_to_law or not edge.remains_guidance:
                raise GuidanceElevationError(
                    "guidance supersession must leave both sides as guidance, not law"
                )
        reasons.append("explicit supersession recorded; both sides remain guidance-tier")
    if case.scenario is ScenarioKind.UNAVAILABLE_DATE:
        unavailable_fields = 0
        for item in items:
            for ver in item.versions:
                if ver.published.is_unavailable:
                    unavailable_fields += 1
                if ver.effective.is_unavailable:
                    unavailable_fields += 1
        if unavailable_fields == 0:
            raise LiveUsptoGuidanceError(
                f"unavailable_date case {case.case_id!r} must mark published "
                "and/or effective as explicitly unavailable"
            )
        reasons.append(
            f"{unavailable_fields} date field(s) explicitly unavailable (not silently filled)"
        )
    if case.freshness_gaps:
        reasons.append(f"{len(case.freshness_gaps)} explicit freshness gap(s)")

    # Never allow latest tokens in retained identities.
    for item in items:
        reject_latest_token(item.item_id, field_name="item_id")
        for ver in item.versions:
            reject_latest_token(ver.version_id, field_name="version_id")
            if ver.edition:
                reject_latest_token(ver.edition, field_name="edition")
            if ver.revision:
                reject_latest_token(ver.revision, field_name="revision")

    outcome = adjudicate_case(case)
    retained = _collect_retained_version_ids(items)

    vstate = VerificationState.UNVERIFIED
    if outcome is CaseOutcome.CONFLICT_RETAINED:
        vstate = VerificationState.CONFLICT
    elif outcome in {
        CaseOutcome.ACQUIRED,
        CaseOutcome.ROLLOVER_RETAINED,
        CaseOutcome.REMOVAL_RETAINED,
        CaseOutcome.SUPERSEDED,
    }:
        vstate = VerificationState.VERIFIED
    elif outcome in {CaseOutcome.UNAVAILABLE, CaseOutcome.DATE_UNAVAILABLE, CaseOutcome.FRESHNESS_GAP}:
        vstate = VerificationState.INCONCLUSIVE

    return GuidanceCaseResult(
        case=case,
        outcome=outcome,
        items=items,
        retained_version_ids=retained,
        reasons=tuple(reasons),
        supersessions=case.supersessions,
        freshness_gaps=case.freshness_gaps,
        verification_state=vstate,
        notes=case.notes,
    )


# ---------------------------------------------------------------------------
# Recipe I/O
# ---------------------------------------------------------------------------


def parse_recipe(
    payload: JsonMapping,
) -> tuple[list[GuidanceCase], dict[str, Any]]:
    """Parse a compact USPTO guidance recipe into cases + metadata."""

    if not isinstance(payload, Mapping):
        raise FixtureSchemaError("recipe must be a mapping")
    schema = payload.get("schema_version")
    if schema and str(schema) not in {
        FIXTURE_SCHEMA_VERSION,
        SCHEMA_VERSION,
        "live-uspto-guidance-recipe-v1",
    }:
        if not str(schema).startswith("live-uspto-guidance"):
            raise FixtureSchemaError(
                f"unsupported recipe schema_version {schema!r}"
            )
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise FixtureSchemaError("recipe.cases must be a non-empty list")
    cases = [GuidanceCase.from_dict(c) for c in raw_cases]
    for case in cases:
        if case.prior_edition:
            reject_latest_token(case.prior_edition, field_name="prior_edition")
        if case.successor_edition:
            reject_latest_token(case.successor_edition, field_name="successor_edition")
        for item in case.items:
            for ver in item.versions:
                if ver.edition:
                    reject_latest_token(ver.edition, field_name="edition")
                if ver.revision:
                    reject_latest_token(ver.revision, field_name="revision")
    meta = {
        "recipe_id": payload.get("recipe_id") or payload.get("fixture_id"),
        "schema_version": schema or FIXTURE_SCHEMA_VERSION,
        "notes": payload.get("notes"),
        "discovered_at": payload.get("discovered_at"),
    }
    return cases, meta


def _version_payload(
    *,
    version_id: str,
    role: str,
    digest: str,
    retrieved_at: str,
    edition: str | None = None,
    revision: str | None = None,
    version_label: str | None = None,
    published: Any = None,
    effective: Any = None,
    source_url: str | None = None,
    media_type: str = "text/html",
    text_excerpt: str | None = None,
    body_text: str | None = None,
    http_status: int | None = 200,
    removed: bool = False,
    published_availability: str | None = None,
    effective_availability: str | None = None,
) -> dict[str, Any]:
    span = _span_for_excerpt(text_excerpt or body_text, fmt=media_type)
    payload: dict[str, Any] = {
        "version_id": version_id,
        "role": role,
        "content_sha256": digest,
        "source_cid": source_cid_for_sha256(digest),
        "source_span": span.to_dict(),
        "retrieved_at": retrieved_at,
        "edition": edition,
        "revision": revision,
        "version_label": version_label,
        "source_url": source_url,
        "media_type": media_type,
        "text_excerpt": text_excerpt,
        "body_text": body_text,
        "http_status": http_status,
        "removed": removed,
    }
    if published_availability == "unavailable" or (
        isinstance(published, str)
        and published.lower().replace("-", "_") in _UNAVAILABLE_DATE_MARKERS
    ):
        payload["published"] = {
            "availability": "unavailable",
            "value": None,
            "notes": "publication date unavailable from USPTO inventory",
        }
    elif published is not None:
        payload["published"] = {
            "availability": "present",
            "value": published if not isinstance(published, dict) else published.get("value"),
        }
    else:
        payload["published"] = {"availability": "not_supplied", "value": None}

    if effective_availability == "unavailable" or (
        isinstance(effective, str)
        and effective.lower().replace("-", "_") in _UNAVAILABLE_DATE_MARKERS
    ):
        payload["effective"] = {
            "availability": "unavailable",
            "value": None,
            "notes": "effective date unavailable from USPTO inventory",
        }
    elif effective is not None:
        payload["effective"] = {
            "availability": "present",
            "value": effective if not isinstance(effective, dict) else effective.get("value"),
        }
    else:
        payload["effective"] = {"availability": "not_supplied", "value": None}
    return payload


def build_default_recipe() -> dict[str, Any]:
    """Compact default recipe covering every PATLAW-132 acceptance scenario."""

    def _h(label: str) -> str:
        return content_sha256(f"patlaw-132:{label}")

    retrieved = "2024-09-15T12:00:00Z"
    cutoff = "2022-07-01"

    mpep_r072022 = _h("mpep-9-r07.2022-s2106")
    mpep_r012024 = _h("mpep-9-r01.2024-s2106")
    form_old = _h("form-pto-sb-08-2022")
    form_new = _h("form-pto-sb-08-2024")
    form_removed_prior = _h("form-pto-sb-01a-2021")
    form_removed_current = _h("form-pto-sb-01a-inventory-absent")
    conflict_a = _h("exam-guide-1-23-mirror-a")
    conflict_b = _h("exam-guide-1-23-mirror-b")
    fee_fy2023 = _h("fees-fy2023")
    fee_fy2024 = _h("fees-fy2024")
    notice_sha = _h("notice-2023-10-17")
    guide_sha = _h("exam-guide-1-23")
    mpep_706 = _h("mpep-9-r07.2022-s706.02")
    faq_sha = _h("faq-subject-matter-2023")

    cases: list[dict[str, Any]] = [
        {
            "case_id": "mpep-edition-rollover-r07.2022-to-r01.2024",
            "scenario": "edition_rollover",
            "prior_edition": "mpep-9-r07.2022",
            "successor_edition": "mpep-9-r01.2024",
            "expected_outcome": "rollover_retained",
            "notes": (
                "MPEP 9 Edition revision rollover r07.2022 → r01.2024. Both "
                "editions retained with concrete revision ids (never 'latest')."
            ),
            "items": [
                {
                    "item_id": "mpep-2106",
                    "kind": "mpep_section",
                    "anchor": "2106",
                    "citation": "MPEP § 2106",
                    "title": "Patent Subject Matter Eligibility",
                    "cutoff": cutoff,
                    "versions": [
                        _version_payload(
                            version_id="mpep-2106@9-r07.2022",
                            role="prior",
                            digest=mpep_r072022,
                            retrieved_at="2024-01-10T10:00:00Z",
                            edition="9",
                            revision="07.2022",
                            version_label="MPEP 9 r07.2022",
                            published=cutoff,
                            effective=cutoff,
                            source_url=f"{USPTO_MPEP_INDEX.rsplit('/', 1)[0]}/s2106.html",
                            text_excerpt=(
                                "Subject matter eligibility under 35 U.S.C. 101 "
                                "(r07.2022 manual text)."
                            ),
                            body_text=f"<mpep section=\"2106\" rev=\"07.2022\">{mpep_r072022}</mpep>",
                        ),
                        _version_payload(
                            version_id="mpep-2106@9-r01.2024",
                            role="successor",
                            digest=mpep_r012024,
                            retrieved_at=retrieved,
                            edition="9",
                            revision="01.2024",
                            version_label="MPEP 9 r01.2024",
                            published="2024-01-01",
                            effective="2024-01-01",
                            source_url=f"{USPTO_MPEP_INDEX.rsplit('/', 1)[0]}/s2106.html",
                            text_excerpt=(
                                "Subject matter eligibility under 35 U.S.C. 101 "
                                "(r01.2024 manual text with AI practice notes)."
                            ),
                            body_text=f"<mpep section=\"2106\" rev=\"01.2024\">{mpep_r012024}</mpep>",
                        ),
                    ],
                }
            ],
        },
        {
            "case_id": "form-pto-sb-01a-removal",
            "scenario": "artifact_removal",
            "expected_outcome": "removal_retained",
            "notes": (
                "Form PTO/SB/01A removed from the public forms inventory; prior "
                "version retained and marked removed rather than silently dropped."
            ),
            "items": [
                {
                    "item_id": "form-pto-sb-01a",
                    "kind": "form",
                    "anchor": "PTO/SB/01A",
                    "citation": "PTO/SB/01A",
                    "title": "Declaration (removed inventory)",
                    "cutoff": cutoff,
                    "versions": [
                        _version_payload(
                            version_id="form-pto-sb-01a@2021-06",
                            role="removed",
                            digest=form_removed_prior,
                            retrieved_at="2023-06-01T09:00:00Z",
                            version_label="2021-06",
                            published="2021-06-15",
                            effective="2021-06-15",
                            source_url=f"{USPTO_FORMS_BASE}/sb0001a.pdf",
                            media_type="application/pdf",
                            text_excerpt="Declaration form PTO/SB/01A (2021-06).",
                            body_text=f"%PDF-1.4 form-sb-01a {form_removed_prior}",
                            removed=True,
                        ),
                        _version_payload(
                            version_id="form-pto-sb-01a@inventory-2024-09",
                            role="current",
                            digest=form_removed_current,
                            retrieved_at=retrieved,
                            version_label="inventory-2024-09",
                            published="unavailable",
                            effective="unavailable",
                            source_url=f"{USPTO_FORMS_BASE}/sb0001a.pdf",
                            media_type="application/pdf",
                            text_excerpt="Form absent from 2024-09 public inventory (HTTP 404).",
                            body_text=None,
                            http_status=404,
                            removed=True,
                            published_availability="unavailable",
                            effective_availability="unavailable",
                        ),
                    ],
                }
            ],
        },
        {
            "case_id": "exam-guide-1-23-version-conflict",
            "scenario": "version_conflict",
            "expected_outcome": "conflict_retained",
            "notes": (
                "Two recorded mirrors of Examination Guide 1-23 disagree on bytes; "
                "both versions retained as conflict — neither silently selected as latest."
            ),
            "items": [
                {
                    "item_id": "exam-guide-1-23",
                    "kind": "examination_guide",
                    "anchor": "1-23",
                    "citation": "Examination Guide 1-23",
                    "title": "Updated Prior-Art Practice",
                    "cutoff": cutoff,
                    "versions": [
                        _version_payload(
                            version_id="exam-guide-1-23@mirror-a",
                            role="conflicting_a",
                            digest=conflict_a,
                            retrieved_at="2024-03-01T11:00:00Z",
                            version_label="mirror-a",
                            published="2023-03-15",
                            effective="2023-03-15",
                            source_url=f"{USPTO_EXAM_GUIDE_BASE}/examination-guide-1-23.pdf",
                            media_type="application/pdf",
                            text_excerpt="Examination Guide 1-23 mirror A bytes.",
                            body_text=f"%PDF-1.4 guide-1-23-a {conflict_a}",
                        ),
                        _version_payload(
                            version_id="exam-guide-1-23@mirror-b",
                            role="conflicting_b",
                            digest=conflict_b,
                            retrieved_at="2024-03-01T11:05:00Z",
                            version_label="mirror-b",
                            published="2023-03-15",
                            effective="2023-03-15",
                            source_url=f"{USPTO_EXAM_GUIDE_BASE}/examination-guide-1-23.pdf",
                            media_type="application/pdf",
                            text_excerpt="Examination Guide 1-23 mirror B bytes (conflict).",
                            body_text=f"%PDF-1.4 guide-1-23-b {conflict_b}",
                        ),
                    ],
                }
            ],
        },
        {
            "case_id": "exam-guide-supersedes-mpep-706.02",
            "scenario": "supersession",
            "expected_outcome": "superseded",
            "notes": (
                "Examination Guide 1-23 supersedes inconsistent MPEP § 706.02 "
                "manual text; both remain guidance-tier (not law)."
            ),
            "supersessions": [
                {
                    "successor_id": "exam-guide-1-23@2023-03-15",
                    "predecessor_id": "mpep-706.02@9-r07.2022",
                    "relation": "supersedes",
                    "effective_date": "2023-03-15",
                    "reason": (
                        "Examination Guide 1-23 supersedes inconsistent MPEP "
                        "§ 706.02 manual text for listed scenarios; both remain "
                        "guidance, not law."
                    ),
                    "remains_guidance": True,
                    "elevates_to_law": False,
                }
            ],
            "items": [
                {
                    "item_id": "mpep-706.02",
                    "kind": "mpep_section",
                    "anchor": "706.02",
                    "citation": "MPEP § 706.02",
                    "title": "Rejection on Prior Art",
                    "cutoff": cutoff,
                    "superseded_by": "exam-guide-1-23@2023-03-15",
                    "versions": [
                        _version_payload(
                            version_id="mpep-706.02@9-r07.2022",
                            role="superseded",
                            digest=mpep_706,
                            retrieved_at="2024-01-10T10:00:00Z",
                            edition="9",
                            revision="07.2022",
                            published=cutoff,
                            effective=cutoff,
                            source_url=f"{USPTO_MPEP_INDEX.rsplit('/', 1)[0]}/s706.02.html",
                            text_excerpt="Dual-framework prior-art manual text (r07.2022).",
                            body_text=f"<mpep section=\"706.02\">{mpep_706}</mpep>",
                        ),
                        _version_payload(
                            version_id="exam-guide-1-23@2023-03-15",
                            role="superseding",
                            digest=guide_sha,
                            retrieved_at=retrieved,
                            version_label="1-23",
                            published="2023-03-15",
                            effective="2023-03-15",
                            source_url=f"{USPTO_EXAM_GUIDE_BASE}/examination-guide-1-23.pdf",
                            media_type="application/pdf",
                            text_excerpt=(
                                "This examination guide supersedes inconsistent "
                                "MPEP § 706.02. Guidance only; not law."
                            ),
                            body_text=f"%PDF-1.4 exam-guide-1-23 {guide_sha}",
                        ),
                    ],
                    "supersedes": [],
                }
            ],
        },
        {
            "case_id": "fee-schedule-unavailable-effective-date",
            "scenario": "unavailable_date",
            "expected_outcome": "date_unavailable",
            "notes": (
                "FY2025 fee schedule listing lacks a published/effective date in "
                "the inventory feed; unavailability is explicit, not silently filled."
            ),
            "items": [
                {
                    "item_id": "fees-fy2025",
                    "kind": "fee_schedule",
                    "anchor": "FY2025",
                    "citation": "USPTO Fee Schedule FY2025",
                    "title": "Patent Fee Schedule FY2025 (dates unavailable)",
                    "cutoff": cutoff,
                    "versions": [
                        _version_payload(
                            version_id="fees-fy2025@inventory-stub",
                            role="sole",
                            digest=_h("fees-fy2025-stub"),
                            retrieved_at=retrieved,
                            version_label="FY2025-inventory-stub",
                            published="unavailable",
                            effective="unavailable",
                            source_url=f"{USPTO_FEES_BASE}/fy2025",
                            text_excerpt="FY2025 fee schedule listed; dates not yet published.",
                            body_text=f"<fees fy=\"2025\">{_h('fees-fy2025-stub')}</fees>",
                            published_availability="unavailable",
                            effective_availability="unavailable",
                        )
                    ],
                }
            ],
        },
        {
            "case_id": "happy-path-forms-fees-notice",
            "scenario": "happy_path",
            "expected_outcome": "acquired",
            "notes": (
                "Successful acquisition of form PTO/SB/08, FY2024 fee schedule, "
                "and OG eligibility notice with full provenance metadata."
            ),
            "items": [
                {
                    "item_id": "form-pto-sb-08",
                    "kind": "form",
                    "anchor": "PTO/SB/08",
                    "citation": "PTO/SB/08",
                    "title": "Information Disclosure Statement",
                    "cutoff": cutoff,
                    "versions": [
                        _version_payload(
                            version_id="form-pto-sb-08@2022-07",
                            role="sole",
                            digest=form_old,
                            retrieved_at=retrieved,
                            version_label="2022-07",
                            published=cutoff,
                            effective=cutoff,
                            source_url=f"{USPTO_FORMS_BASE}/sb0008.pdf",
                            media_type="application/pdf",
                            text_excerpt="Form for listing information disclosure references.",
                            body_text=f"%PDF-1.4 form-sb-08 {form_old}",
                        )
                    ],
                },
                {
                    "item_id": "fees-fy2024",
                    "kind": "fee_schedule",
                    "anchor": "FY2024",
                    "citation": "USPTO Fee Schedule FY2024",
                    "title": "Patent Fee Schedule FY2024",
                    "cutoff": cutoff,
                    "versions": [
                        _version_payload(
                            version_id="fees-fy2024@2023-10-01",
                            role="sole",
                            digest=fee_fy2024,
                            retrieved_at=retrieved,
                            version_label="FY2024",
                            published="2023-10-01",
                            effective="2023-10-01",
                            source_url=f"{USPTO_FEES_BASE}/fy2024",
                            text_excerpt="Fee amounts effective for fiscal year 2024.",
                            body_text=f"<fees fy=\"2024\">{fee_fy2024}</fees>",
                        )
                    ],
                },
                {
                    "item_id": "notice-2023-10-17",
                    "kind": "notice",
                    "anchor": "2023-10-17-eligibility",
                    "citation": "OG Notice 2023-10-17",
                    "title": "Subject Matter Eligibility Update Notice",
                    "cutoff": cutoff,
                    "versions": [
                        _version_payload(
                            version_id="notice-2023-10-17@2023-10-17",
                            role="sole",
                            digest=notice_sha,
                            retrieved_at=retrieved,
                            version_label="2023-10-17",
                            published="2023-10-17",
                            effective="2023-10-17",
                            source_url=f"{USPTO_EXAM_GUIDE_BASE}/notice-2023-10-17.html",
                            text_excerpt=(
                                "Clarifies examination practice under MPEP § 2106 "
                                "for certain AI-related claims. Guidance only; not law."
                            ),
                            body_text=f"<notice id=\"2023-10-17\">{notice_sha}</notice>",
                        )
                    ],
                },
            ],
        },
        {
            "case_id": "form-pto-sb-08-replacement",
            "scenario": "form_replacement",
            "expected_outcome": "acquired",
            "notes": (
                "Form PTO/SB/08 replacement: 2022 and 2024 versions both retained "
                "with distinct digests and effective dates."
            ),
            "items": [
                {
                    "item_id": "form-pto-sb-08-replaced",
                    "kind": "form",
                    "anchor": "PTO/SB/08",
                    "citation": "PTO/SB/08",
                    "title": "Information Disclosure Statement (replacement)",
                    "cutoff": cutoff,
                    "versions": [
                        _version_payload(
                            version_id="form-pto-sb-08@2022-07",
                            role="prior",
                            digest=form_old,
                            retrieved_at="2023-01-01T10:00:00Z",
                            version_label="2022-07",
                            published=cutoff,
                            effective=cutoff,
                            source_url=f"{USPTO_FORMS_BASE}/sb0008.pdf",
                            media_type="application/pdf",
                            text_excerpt="IDS form 2022-07 revision.",
                            body_text=f"%PDF-1.4 form-sb-08-2022 {form_old}",
                        ),
                        _version_payload(
                            version_id="form-pto-sb-08@2024-03",
                            role="successor",
                            digest=form_new,
                            retrieved_at=retrieved,
                            version_label="2024-03",
                            published="2024-03-01",
                            effective="2024-03-01",
                            source_url=f"{USPTO_FORMS_BASE}/sb0008.pdf",
                            media_type="application/pdf",
                            text_excerpt="IDS form 2024-03 revision (replacement).",
                            body_text=f"%PDF-1.4 form-sb-08-2024 {form_new}",
                        ),
                    ],
                }
            ],
        },
        {
            "case_id": "fee-schedule-rollover-fy2023-to-fy2024",
            "scenario": "fee_schedule_rollover",
            "expected_outcome": "rollover_retained",
            "prior_edition": "fees-fy2023",
            "successor_edition": "fees-fy2024",
            "notes": "Fee schedule fiscal-year rollover retains both FY2023 and FY2024.",
            "items": [
                {
                    "item_id": "fees-schedule",
                    "kind": "fee_schedule",
                    "anchor": "patent-fees",
                    "citation": "USPTO Patent Fee Schedule",
                    "title": "Patent Fee Schedule (FY rollover)",
                    "cutoff": cutoff,
                    "versions": [
                        _version_payload(
                            version_id="fees-fy2023@2022-10-01",
                            role="prior",
                            digest=fee_fy2023,
                            retrieved_at="2023-09-01T10:00:00Z",
                            version_label="FY2023",
                            published="2022-10-01",
                            effective="2022-10-01",
                            source_url=f"{USPTO_FEES_BASE}/fy2023",
                            text_excerpt="Fee amounts effective for fiscal year 2023.",
                            body_text=f"<fees fy=\"2023\">{fee_fy2023}</fees>",
                        ),
                        _version_payload(
                            version_id="fees-fy2024@2023-10-01",
                            role="successor",
                            digest=fee_fy2024,
                            retrieved_at=retrieved,
                            version_label="FY2024",
                            published="2023-10-01",
                            effective="2023-10-01",
                            source_url=f"{USPTO_FEES_BASE}/fy2024",
                            text_excerpt="Fee amounts effective for fiscal year 2024.",
                            body_text=f"<fees fy=\"2024\">{fee_fy2024}</fees>",
                        ),
                    ],
                }
            ],
        },
        {
            "case_id": "faq-freshness-gap-unavailable",
            "scenario": "freshness_gap",
            "expected_outcome": "freshness_gap",
            "notes": (
                "FAQ page listed in inventory but currently unavailable; explicit "
                "freshness gap (not silent omission)."
            ),
            "freshness_gaps": [
                {
                    "gap_id": "gap-unavailable-faq-sme-2023",
                    "kind": "unavailable",
                    "source_id": "faq-subject-matter-2023",
                    "reason": (
                        "Subject-matter eligibility FAQ listed in examination-policy "
                        "inventory but public page returns HTTP 404."
                    ),
                    "cutoff": cutoff,
                    "source_url": f"{USPTO_EXAM_GUIDE_BASE}/faq-subject-matter-eligibility.html",
                    "detected_at": retrieved,
                    "expected_sha256": faq_sha,
                }
            ],
            "items": [
                {
                    "item_id": "faq-subject-matter-2023",
                    "kind": "later_publication",
                    "anchor": "faq-sme-2023",
                    "citation": "SME FAQ 2023",
                    "title": "Subject Matter Eligibility FAQ",
                    "cutoff": cutoff,
                    "versions": [
                        _version_payload(
                            version_id="faq-sme-2023@inventory",
                            role="sole",
                            digest=faq_sha,
                            retrieved_at=retrieved,
                            version_label="inventory-stub",
                            published="2023-06-01",
                            effective="2023-06-01",
                            source_url=f"{USPTO_EXAM_GUIDE_BASE}/faq-subject-matter-eligibility.html",
                            text_excerpt="FAQ inventory stub; content unavailable.",
                            body_text=None,
                            http_status=404,
                        )
                    ],
                }
            ],
        },
    ]

    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "recipe_id": "live-uspto-guidance-v1",
        "fixture_id": "live-uspto-guidance-v1",
        "discovered_at": retrieved,
        "notes": (
            "Compact live USPTO guidance recipe (PATLAW-132). Covers MPEP edition "
            "rollover, form removal, version conflict, explicit supersession, "
            "unavailable dates, happy-path forms/fees/notices, form replacement, "
            "fee-schedule rollover, and freshness gaps. Every item retains source "
            "CID/span/retrieved/published/effective metadata; links never select "
            "'latest'. Guidance remains non-binding."
        ),
        "authority_class": "guidance",
        "is_binding": False,
        "cases": cases,
        "expected": {
            "required_scenarios": sorted(REQUIRED_SCENARIO_KINDS),
            "retain_old_and_new_for": [
                "edition_rollover",
                "artifact_removal",
                "version_conflict",
            ],
            "provenance_fields": [
                "source_cid",
                "source_span",
                "retrieved_at",
                "published",
                "effective",
            ],
            "never_silent_latest": True,
            "never_elevate_to_law": True,
        },
    }


def write_default_fixtures(directory: PathLike | None = None) -> Path:
    """Write the compact USPTO guidance recipe to *directory*."""

    target_dir = Path(directory) if directory is not None else default_fixture_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / "uspto_guidance_recipe.json"
    payload = build_default_recipe()
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class LiveUsptoGuidanceProcessor:
    """Acquire live/recorded USPTO MPEP, forms, fees, and examination guidance.

    Primary path is deterministic recipe replay. Optional
    :class:`PatentSourceTransport` enables bounded live fetches; transport
    success never elevates guidance to law and never selects ``latest``.
    """

    def __init__(
        self,
        *,
        fixture_dir: PathLike | None = None,
        transport: PatentSourceTransport | None = None,
        network_enabled: bool = False,
    ) -> None:
        self.fixture_dir = Path(fixture_dir) if fixture_dir else default_fixture_dir()
        self._transport = transport
        self._network_enabled = bool(network_enabled)
        self._last_report: Optional[LiveUsptoGuidanceReport] = None

    @property
    def transport(self) -> Optional[PatentSourceTransport]:
        return self._transport

    @property
    def last_report(self) -> Optional[LiveUsptoGuidanceReport]:
        return self._last_report

    def recipe_path(self) -> Path:
        return self.fixture_dir / "uspto_guidance_recipe.json"

    def load_recipe(self, path: PathLike | None = None) -> dict[str, Any]:
        target = Path(path) if path is not None else self.recipe_path()
        if not target.is_file():
            write_default_fixtures(target.parent if target.suffix else target)
            if target.is_dir():
                target = target / "uspto_guidance_recipe.json"
            if not target.is_file():
                alt = self.fixture_dir / "uspto_guidance_recipe.json"
                if alt.is_file():
                    target = alt
        return load_json_fixture(target)

    def acquire_from_fixture(
        self,
        path: PathLike | None = None,
        *,
        retrieved_at: datetime | None = None,
    ) -> LiveUsptoGuidanceReport:
        """Process the recorded recipe (no network I/O)."""

        payload = self.load_recipe(path)
        return self.acquire_from_payload(payload, retrieved_at=retrieved_at)

    def acquire_from_payload(
        self,
        payload: JsonMapping,
        *,
        retrieved_at: datetime | None = None,
    ) -> LiveUsptoGuidanceReport:
        cases, meta = parse_recipe(payload)
        when = retrieved_at
        if when is None and meta.get("discovered_at"):
            when = _parse_utc(meta["discovered_at"], name="discovered_at")
        if when is None:
            when = datetime(2024, 9, 15, 12, 0, 0, tzinfo=timezone.utc)

        results = [process_case(case, retrieved_at=when) for case in cases]
        report = LiveUsptoGuidanceReport(
            results=tuple(results),
            schema_version=SCHEMA_VERSION,
            recipe_id=meta.get("recipe_id"),
            retrieved_at=when,
            notes=meta.get("notes"),
            metadata={
                "fixture_schema": meta.get("schema_version"),
                "authority_schema": AUTHORITY_SCHEMA_VERSION,
                "authority_class": "guidance",
                "is_binding": False,
            },
        )
        self._last_report = report
        return report

    def acquire_live_urls(
        self,
        requests: Sequence[SourceFetchRequest],
    ) -> list[AcquisitionOutcome]:
        """Fetch *requests* via transport (opt-in network / injected opener).

        Returns acquisition outcomes only. Guidance remains non-binding and
        edition identity must still be supplied by the caller — never ``latest``.
        """

        if self._transport is None:
            self._transport = PatentSourceTransport(network_enabled=self._network_enabled)
        outcomes: list[AcquisitionOutcome] = []
        for request in requests:
            try:
                outcomes.append(self._transport.acquire_catching(request))
            except SourceTransportError as exc:
                when = datetime.now(timezone.utc)
                receipt = AcquisitionReceipt(
                    endpoint=request.url,
                    retrieved_at=when,
                    outcome_kind=AcquisitionOutcomeKind.NETWORK_ERROR,
                    response_status=0,
                    sanitized_request={"method": request.method, "path": request.url},
                    error_code=getattr(exc, "code", "transport_error"),
                    error_message=str(exc)[:500],
                    metadata={
                        "authority_class": "guidance",
                        "is_binding": False,
                        "https_is_not_authentication": True,
                    },
                )
                outcomes.append(
                    AcquisitionOutcome(
                        kind=AcquisitionOutcomeKind.NETWORK_ERROR,
                        receipt=receipt,
                        body=None,
                        network_used=True,
                    )
                )
        return outcomes

    def assert_acceptance_coverage(
        self, report: LiveUsptoGuidanceReport | None = None
    ) -> None:
        """Fail closed when required PATLAW-132 scenarios or provenance are missing."""

        target = report if report is not None else self._last_report
        if target is None:
            raise LiveUsptoGuidanceError("no report available for acceptance coverage")
        missing = target.missing_required_scenarios()
        if missing:
            raise LiveUsptoGuidanceError(
                f"missing required scenario kinds: {sorted(missing)}"
            )

        for result in target.results:
            if not result.all_items_have_provenance():
                raise LiveUsptoGuidanceError(
                    f"case {result.case.case_id!r} missing source CID/span/"
                    "retrieved/published/effective provenance"
                )
            if result.case.scenario in {
                ScenarioKind.EDITION_ROLLOVER,
                ScenarioKind.ARTIFACT_REMOVAL,
                ScenarioKind.VERSION_CONFLICT,
            }:
                if not result.retains_old_and_new:
                    raise VersionRetentionError(
                        f"case {result.case.case_id!r} must retain old and new versions"
                    )
            for item in result.items:
                if item.authority_tier is not AuthorityTier.GUIDANCE or item.is_binding:
                    raise GuidanceElevationError(
                        f"item {item.item_id!r} elevated above guidance tier"
                    )
                for ver in item.versions:
                    reject_latest_token(ver.version_id, field_name="version_id")
                    if ver.edition:
                        reject_latest_token(ver.edition, field_name="edition")
                    if ver.revision:
                        reject_latest_token(ver.revision, field_name="revision")

        # Supersession edges must remain guidance.
        for result in target.results_for_scenario(ScenarioKind.SUPERSESSION):
            if not result.supersessions and not any(
                i.supersedes or i.superseded_by for i in result.items
            ):
                raise LiveUsptoGuidanceError(
                    f"supersession case {result.case.case_id!r} lacks explicit edges"
                )
            for edge in result.supersessions:
                if edge.elevates_to_law or not edge.remains_guidance:
                    raise GuidanceElevationError(
                        "supersession must not elevate guidance to law"
                    )

        # Unavailable dates stay explicit.
        for result in target.results_for_scenario(ScenarioKind.UNAVAILABLE_DATE):
            found = False
            for item in result.items:
                for ver in item.versions:
                    if ver.published.is_unavailable or ver.effective.is_unavailable:
                        found = True
            if not found:
                raise LiveUsptoGuidanceError(
                    f"unavailable_date case {result.case.case_id!r} has no "
                    "explicit unavailable published/effective fields"
                )


__all__ = [
    "SCHEMA_VERSION",
    "FIXTURE_SCHEMA_VERSION",
    "REQUIRED_SCENARIO_KINDS",
    "DEFAULT_PROVIDER",
    "DEFAULT_JURISDICTION",
    "COLLECTION_GUIDANCE",
    "COLLECTION_MPEP",
    "USPTO_MPEP_INDEX",
    "USPTO_FORMS_BASE",
    "USPTO_FEES_BASE",
    "USPTO_EXAM_GUIDE_BASE",
    "LiveUsptoGuidanceError",
    "FixtureSchemaError",
    "HardCodedLatestError",
    "SilentLatestSelectionError",
    "GuidanceElevationError",
    "VersionRetentionError",
    "ScenarioKind",
    "CaseOutcome",
    "DateAvailability",
    "VersionRole",
    "TemporalField",
    "LiveGuidanceVersion",
    "LiveGuidanceItem",
    "GuidanceCase",
    "GuidanceCaseResult",
    "LiveUsptoGuidanceReport",
    "LiveUsptoGuidanceProcessor",
    "content_sha256",
    "source_cid_for_bytes",
    "source_cid_for_sha256",
    "reject_latest_token",
    "resolve_guidance_link",
    "adjudicate_case",
    "process_case",
    "parse_recipe",
    "build_default_recipe",
    "write_default_fixtures",
    "default_fixture_dir",
    "load_json_fixture",
]
