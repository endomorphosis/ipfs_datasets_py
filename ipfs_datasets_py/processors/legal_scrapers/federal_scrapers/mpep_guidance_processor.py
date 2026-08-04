"""Versioned MPEP, forms, fees, and later guidance acquisition (PATLAW-015).

Ingests USPTO examination guidance as lower-tier versioned artifacts:

* MPEP sections and form-paragraph anchors
* Official forms and fee schedules
* Examination Guides and later publications (notices, operational guidance)

Design invariants:

* Every admitted record carries ``authority_tier=guidance`` and an explicit
  edition/revision **cutoff** date. Guidance never outranks statute or
  regulation and is never elevated to law.
* Later guidance may **supersede** inconsistent MPEP manual text while both
  the predecessor and successor remain guidance-tier artifacts.
* Unavailable or byte-changed documents yield explicit **freshness gaps**
  rather than silent omission or silent overwrite.
* Edition identity is never the hard-coded token ``\"latest\"``; connectors
  record concrete edition/revision identifiers.
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
from typing import Any, Iterable, Iterator, Mapping, Optional, Sequence, Union

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

SCHEMA_VERSION = "mpep-guidance-processor-v1"
FIXTURE_SCHEMA_VERSION = "mpep-guidance-fixture-v1"

DEFAULT_PROVIDER = "uspto"
DEFAULT_JURISDICTION = "US"
COLLECTION_GUIDANCE = "GUIDANCE"
COLLECTION_MPEP = "MPEP"

# Public USPTO anchors (discovered endpoints are recorded at runtime; these are
# documentation defaults only and never claim to be "latest").
USPTO_MPEP_INDEX = "https://www.uspto.gov/web/offices/pac/mpep/index.html"
USPTO_FORMS_BASE = "https://www.uspto.gov/patents/apply/forms"
USPTO_FEES_BASE = "https://www.uspto.gov/learning-and-resources/fees-and-payment"
USPTO_EXAM_GUIDE_BASE = "https://www.uspto.gov/patents/laws/examination-policy"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SECTION_TOKEN_RE = re.compile(
    r"(?:§+\s*)?(?:sec(?:tion)?\.?\s*)?(?P<section>\d+[A-Za-z0-9.\-]*)",
    re.IGNORECASE,
)
_FORM_PARAGRAPH_RE = re.compile(
    r"(?:fp|form\s*paragraph|¶)\s*[#:]?\s*(?P<fp>[\d.]+)",
    re.IGNORECASE,
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors and enums
# ---------------------------------------------------------------------------


class MpepGuidanceError(ValueError):
    """Base error for MPEP / guidance acquisition failures."""


class MissingCutoffError(MpepGuidanceError):
    """Raised when a guidance record lacks a required cutoff date."""


class FixtureSchemaError(MpepGuidanceError):
    """Raised when a fixture package is malformed."""


class GuidanceNotFoundError(MpepGuidanceError):
    """Raised when a requested guidance artifact is not present."""


class BindingElevationError(MpepGuidanceError):
    """Raised when code attempts to treat guidance as binding law."""


class ResolutionStatus(str, Enum):
    """Outcome of guidance edition or artifact resolution."""

    RESOLVED = "resolved"
    UNKNOWN = "unknown"
    PARTIAL = "partial"
    ERROR = "error"
    FRESHNESS_GAP = "freshness_gap"


class GuidanceKind(str, Enum):
    """Kinds of USPTO examination / operational guidance artifacts."""

    MPEP_SECTION = "mpep_section"
    FORM_PARAGRAPH = "form_paragraph"
    FORM = "form"
    FEE_SCHEDULE = "fee_schedule"
    EXAMINATION_GUIDE = "examination_guide"
    NOTICE = "notice"
    LATER_PUBLICATION = "later_publication"
    OTHER = "other"

    @classmethod
    def coerce(cls, value: Any) -> "GuidanceKind":
        if isinstance(value, GuidanceKind):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "mpep": cls.MPEP_SECTION,
            "mpep_section": cls.MPEP_SECTION,
            "section": cls.MPEP_SECTION,
            "form_paragraph": cls.FORM_PARAGRAPH,
            "fp": cls.FORM_PARAGRAPH,
            "formparagraph": cls.FORM_PARAGRAPH,
            "form": cls.FORM,
            "forms": cls.FORM,
            "fee": cls.FEE_SCHEDULE,
            "fees": cls.FEE_SCHEDULE,
            "fee_schedule": cls.FEE_SCHEDULE,
            "examination_guide": cls.EXAMINATION_GUIDE,
            "exam_guide": cls.EXAMINATION_GUIDE,
            "guide": cls.EXAMINATION_GUIDE,
            "notice": cls.NOTICE,
            "og_notice": cls.NOTICE,
            "later_publication": cls.LATER_PUBLICATION,
            "later": cls.LATER_PUBLICATION,
            "other": cls.OTHER,
        }
        if text not in aliases:
            raise MpepGuidanceError(f"unsupported guidance kind: {value!r}")
        return aliases[text]


class FreshnessGapKind(str, Enum):
    """Explicit retrieval / inventory freshness gap kinds."""

    UNAVAILABLE = "unavailable"
    CONTENT_CHANGED = "content_changed"
    DELAYED_INVENTORY = "delayed_inventory"
    HASH_MISMATCH = "hash_mismatch"
    RETRIEVAL_FAILED = "retrieval_failed"
    SUPERSEDED_UNAVAILABLE = "superseded_unavailable"
    OTHER = "other"

    @classmethod
    def coerce(cls, value: Any) -> "FreshnessGapKind":
        if isinstance(value, FreshnessGapKind):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        for kind in cls:
            if kind.value == text or kind.name.lower() == text:
                return kind
        return cls.OTHER


class SupersessionRelation(str, Enum):
    """How later guidance relates to earlier manual or guidance text."""

    SUPERSEDES = "supersedes"
    PARTIALLY_SUPERSEDES = "partially_supersedes"
    CLARIFIES = "clarifies"
    WITHDRAWS = "withdraws"
    RESTORES = "restores"

    @classmethod
    def coerce(cls, value: Any) -> "SupersessionRelation":
        if isinstance(value, SupersessionRelation):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        for rel in cls:
            if rel.value == text or rel.name.lower() == text:
                return rel
        raise MpepGuidanceError(f"unsupported supersession relation: {value!r}")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MpepGuidanceError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise MpepGuidanceError(f"{name} must not contain NUL")
    return value.strip()


def _optional_str(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, "value")


def _require_sha256(value: Any, name: str = "sha256") -> str:
    text = _require_non_empty_str(value, name).lower()
    if not _SHA256_RE.fullmatch(text):
        raise MpepGuidanceError(f"{name} must be a lowercase 64-char hex SHA-256")
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
            raise MpepGuidanceError(f"{name} must be ISO-8601 datetime") from exc
    else:
        raise MpepGuidanceError(f"{name} must be a datetime or ISO-8601 string")
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


def _parse_required_date(value: Any, *, name: str = "cutoff") -> date:
    if value is None or value == "":
        raise MissingCutoffError(f"{name} is required on every guidance record")
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError as exc:
            raise MpepGuidanceError(f"{name} must be an ISO date") from exc
    raise MpepGuidanceError(f"{name} must be a date or ISO date string")


def _parse_optional_date(value: Any, *, name: str = "date") -> Optional[date]:
    if value is None or value == "":
        return None
    return _parse_required_date(value, name=name)


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


def normalize_mpep_section(section: Any) -> str:
    """Normalize an MPEP section token (e.g. ``2106``, ``§ 2106.04(a)``)."""

    if section is None:
        raise MpepGuidanceError("section must be non-empty")
    text = str(section).strip()
    if not text:
        raise MpepGuidanceError("section must be non-empty")
    candidates = list(_SECTION_TOKEN_RE.finditer(text))
    raw = candidates[-1].group("section") if candidates else text
    raw = raw.strip().lstrip("§").strip()
    raw = re.sub(r"\s+", "", raw)
    # Drop a trailing bare period used as a sentence terminator, not a subsection.
    if raw.endswith(".") and raw.count(".") == 1 and not re.search(r"\d\.\d", raw):
        raw = raw[:-1]
    return raw


def normalize_form_paragraph(token: Any) -> str:
    """Normalize a form-paragraph id (e.g. ``7.05``, ``FP 7.05``, ``¶7.05``)."""

    if token is None:
        raise MpepGuidanceError("form_paragraph must be non-empty")
    text = str(token).strip()
    if not text:
        raise MpepGuidanceError("form_paragraph must be non-empty")
    match = _FORM_PARAGRAPH_RE.search(text)
    if match:
        return match.group("fp").strip()
    # Bare numeric form-paragraph ids.
    cleaned = text.lstrip("#¶").strip()
    cleaned = re.sub(r"^(?:fp|form\s*paragraph)\s*[#:]?\s*", "", cleaned, flags=re.I)
    cleaned = cleaned.strip()
    if not cleaned:
        raise MpepGuidanceError(f"unrecognized form paragraph token: {token!r}")
    return cleaned


def stable_guidance_identity(
    *,
    kind: GuidanceKind | str,
    anchor: Any,
    jurisdiction: str = DEFAULT_JURISDICTION,
) -> str:
    """Return a stable identity independent of edition packaging format.

    Shape: ``guidance:{jurisdiction}:{kind}:{anchor}``
    """

    kind_v = GuidanceKind.coerce(kind)
    if kind_v is GuidanceKind.MPEP_SECTION:
        token = normalize_mpep_section(anchor)
    elif kind_v is GuidanceKind.FORM_PARAGRAPH:
        token = normalize_form_paragraph(anchor)
    else:
        token = _require_non_empty_str(str(anchor), "anchor").lower().replace(" ", "-")
    jur = _require_non_empty_str(jurisdiction, "jurisdiction").lower()
    return f"guidance:{jur}:{kind_v.value}:{token}"


def parse_mpep_edition_revision(
    *,
    edition: Any,
    revision: Any,
) -> tuple[str, str]:
    """Validate concrete MPEP edition + revision (never ``latest``)."""

    edition_s = _require_non_empty_str(str(edition), "edition")
    revision_s = _require_non_empty_str(str(revision), "revision")
    reject_hard_coded_latest(edition_s, field_name="edition")
    reject_hard_coded_latest(revision_s, field_name="revision")
    return edition_s, revision_s


def mpep_source_url(*, section: Any | None = None) -> str:
    if section is None:
        return USPTO_MPEP_INDEX
    sec = normalize_mpep_section(section)
    return f"https://www.uspto.gov/web/offices/pac/mpep/s{sec}.html"


# ---------------------------------------------------------------------------
# Core records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GuidanceEdition:
    """Concrete MPEP (or guidance corpus) edition/revision with cutoff date.

    The cutoff is the as-of boundary for the manual text; separately listed
    post-cutoff publications are modeled as their own guidance records and may
    supersede inconsistent manual text without elevating either to law.
    """

    edition: str
    revision: str
    cutoff: date
    provider: str = DEFAULT_PROVIDER
    publication_date: Optional[date] = None
    source_url: Optional[str] = None
    content_sha256: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        edition_s, revision_s = parse_mpep_edition_revision(
            edition=self.edition, revision=self.revision
        )
        object.__setattr__(self, "edition", edition_s)
        object.__setattr__(self, "revision", revision_s)
        object.__setattr__(self, "cutoff", _parse_required_date(self.cutoff, name="cutoff"))
        object.__setattr__(
            self, "provider", _require_non_empty_str(self.provider, "provider")
        )
        if self.publication_date is not None:
            object.__setattr__(
                self,
                "publication_date",
                _parse_required_date(self.publication_date, name="publication_date"),
            )
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
        if self.notes is not None:
            object.__setattr__(self, "notes", _require_non_empty_str(self.notes, "notes"))
        if not isinstance(self.metadata, Mapping):
            raise MpepGuidanceError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def edition_key(self) -> str:
        """Stable edition/revision identity token (never ``latest``)."""

        return f"mpep-{self.edition}-r{self.revision}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_sha256": self.content_sha256,
            "cutoff": _date_to_str(self.cutoff),
            "edition": self.edition,
            "edition_key": self.edition_key,
            "metadata": _deep_sorted(self.metadata),
            "notes": self.notes,
            "provider": self.provider,
            "publication_date": _date_to_str(self.publication_date),
            "retrieved_at": (
                None if self.retrieved_at is None else _format_utc(self.retrieved_at)
            ),
            "revision": self.revision,
            "source_url": self.source_url,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "GuidanceEdition":
        if not isinstance(value, Mapping):
            raise MpepGuidanceError("guidance edition must be a mapping")
        if value.get("cutoff") in (None, ""):
            raise MissingCutoffError("cutoff is required on every guidance edition")
        return cls(
            edition=str(value.get("edition") or value.get("edition_key") or ""),
            revision=str(value.get("revision") or ""),
            cutoff=value["cutoff"],
            provider=str(value.get("provider") or DEFAULT_PROVIDER),
            publication_date=value.get("publication_date"),
            source_url=value.get("source_url"),
            content_sha256=value.get("content_sha256"),
            retrieved_at=value.get("retrieved_at"),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class SupersessionEdge:
    """Later guidance superseding earlier guidance/manual text.

    Both endpoints remain guidance-tier. The edge never elevates either side
    to statute, regulation, or other binding law.
    """

    successor_id: str
    predecessor_id: str
    relation: SupersessionRelation = SupersessionRelation.SUPERSEDES
    effective_date: Optional[date] = None
    reason: Optional[str] = None
    remains_guidance: bool = True
    elevates_to_law: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "successor_id", _require_non_empty_str(self.successor_id, "successor_id")
        )
        object.__setattr__(
            self,
            "predecessor_id",
            _require_non_empty_str(self.predecessor_id, "predecessor_id"),
        )
        object.__setattr__(self, "relation", SupersessionRelation.coerce(self.relation))
        if self.effective_date is not None:
            object.__setattr__(
                self,
                "effective_date",
                _parse_required_date(self.effective_date, name="effective_date"),
            )
        if self.reason is not None:
            object.__setattr__(self, "reason", _require_non_empty_str(self.reason, "reason"))
        # Fail closed: supersession of guidance must not elevate to law.
        if self.elevates_to_law:
            raise BindingElevationError(
                "guidance supersession must not elevate either side to law"
            )
        if not self.remains_guidance:
            raise BindingElevationError(
                "guidance supersession must leave both sides as guidance-tier"
            )
        object.__setattr__(self, "remains_guidance", True)
        object.__setattr__(self, "elevates_to_law", False)
        if not isinstance(self.metadata, Mapping):
            raise MpepGuidanceError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "effective_date": _date_to_str(self.effective_date),
            "elevates_to_law": False,
            "metadata": _deep_sorted(self.metadata),
            "predecessor_id": self.predecessor_id,
            "reason": self.reason,
            "relation": self.relation.value,
            "remains_guidance": True,
            "successor_id": self.successor_id,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "SupersessionEdge":
        if not isinstance(value, Mapping):
            raise MpepGuidanceError("supersession edge must be a mapping")
        return cls(
            successor_id=str(value.get("successor_id") or value.get("later_id") or ""),
            predecessor_id=str(
                value.get("predecessor_id") or value.get("earlier_id") or ""
            ),
            relation=SupersessionRelation.coerce(
                value.get("relation", SupersessionRelation.SUPERSEDES)
            ),
            effective_date=value.get("effective_date"),
            reason=value.get("reason"),
            remains_guidance=bool(value.get("remains_guidance", True)),
            elevates_to_law=bool(value.get("elevates_to_law", False)),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class FreshnessGap:
    """Explicit gap when a guidance document is unavailable or has changed.

    Freshness gaps are first-class outcomes: delayed inventory and content
    change are never treated as non-receipt of a USPTO filing, and unavailable
    public guidance is never silently omitted.
    """

    gap_id: str
    kind: FreshnessGapKind
    source_id: str
    reason: str
    authority_tier: AuthorityTier = AuthorityTier.GUIDANCE
    cutoff: Optional[date] = None
    expected_sha256: Optional[str] = None
    observed_sha256: Optional[str] = None
    source_url: Optional[str] = None
    detected_at: Optional[datetime] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "gap_id", _require_non_empty_str(self.gap_id, "gap_id"))
        object.__setattr__(self, "kind", FreshnessGapKind.coerce(self.kind))
        object.__setattr__(
            self, "source_id", _require_non_empty_str(self.source_id, "source_id")
        )
        object.__setattr__(self, "reason", _require_non_empty_str(self.reason, "reason"))
        # Always guidance tier for this processor's gaps.
        if isinstance(self.authority_tier, AuthorityTier):
            tier = self.authority_tier
        else:
            tier = AuthorityTier(str(self.authority_tier))
        if tier is not AuthorityTier.GUIDANCE:
            # Gaps about guidance documents still label guidance; do not elevate.
            tier = AuthorityTier.GUIDANCE
        object.__setattr__(self, "authority_tier", tier)
        if self.cutoff is not None:
            object.__setattr__(
                self, "cutoff", _parse_required_date(self.cutoff, name="cutoff")
            )
        if self.expected_sha256 is not None:
            object.__setattr__(
                self,
                "expected_sha256",
                _require_sha256(self.expected_sha256, "expected_sha256"),
            )
        if self.observed_sha256 is not None:
            object.__setattr__(
                self,
                "observed_sha256",
                _require_sha256(self.observed_sha256, "observed_sha256"),
            )
        if self.source_url is not None:
            object.__setattr__(
                self, "source_url", _require_non_empty_str(self.source_url, "source_url")
            )
        if self.detected_at is not None:
            object.__setattr__(
                self, "detected_at", _parse_utc(self.detected_at, name="detected_at")
            )
        if not isinstance(self.metadata, Mapping):
            raise MpepGuidanceError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_tier": self.authority_tier.value,
            "cutoff": _date_to_str(self.cutoff),
            "detected_at": (
                None if self.detected_at is None else _format_utc(self.detected_at)
            ),
            "expected_sha256": self.expected_sha256,
            "gap_id": self.gap_id,
            "kind": self.kind.value,
            "metadata": _deep_sorted(self.metadata),
            "observed_sha256": self.observed_sha256,
            "reason": self.reason,
            "source_id": self.source_id,
            "source_url": self.source_url,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "FreshnessGap":
        if not isinstance(value, Mapping):
            raise MpepGuidanceError("freshness gap must be a mapping")
        return cls(
            gap_id=str(value.get("gap_id") or value.get("id") or ""),
            kind=FreshnessGapKind.coerce(value.get("kind", FreshnessGapKind.OTHER)),
            source_id=str(value.get("source_id") or value.get("guidance_id") or ""),
            reason=str(value.get("reason") or "freshness gap"),
            authority_tier=value.get("authority_tier", AuthorityTier.GUIDANCE),
            cutoff=value.get("cutoff"),
            expected_sha256=value.get("expected_sha256"),
            observed_sha256=value.get("observed_sha256"),
            source_url=value.get("source_url"),
            detected_at=value.get("detected_at"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class GuidanceRecord:
    """One versioned guidance artifact with visible tier and cutoff.

    ``is_binding`` is always ``False``: MPEP, forms, fees, and examination
    guidance never become law through this processor.
    """

    guidance_id: str
    kind: GuidanceKind
    cutoff: date
    authority_tier: AuthorityTier = AuthorityTier.GUIDANCE
    anchor: Optional[str] = None
    citation: Optional[str] = None
    title: Optional[str] = None
    text_excerpt: Optional[str] = None
    edition: Optional[str] = None
    revision: Optional[str] = None
    publication_date: Optional[date] = None
    effective_start: Optional[date] = None
    source_url: Optional[str] = None
    content_sha256: Optional[str] = None
    media_type: Optional[str] = None
    supersedes: tuple[str, ...] = ()
    superseded_by: Optional[str] = None
    is_binding: bool = False
    is_post_cutoff_publication: bool = False
    status: ResolutionStatus = ResolutionStatus.RESOLVED
    stable_id: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "guidance_id", _require_non_empty_str(self.guidance_id, "guidance_id")
        )
        object.__setattr__(self, "kind", GuidanceKind.coerce(self.kind))
        object.__setattr__(self, "cutoff", _parse_required_date(self.cutoff, name="cutoff"))

        if isinstance(self.authority_tier, AuthorityTier):
            tier = self.authority_tier
        else:
            tier = AuthorityTier(
                str(self.authority_tier).strip().lower().replace("_", "-")
            )
        if tier is not AuthorityTier.GUIDANCE:
            raise BindingElevationError(
                f"guidance records must use authority_tier=guidance, got {tier.value!r}"
            )
        object.__setattr__(self, "authority_tier", AuthorityTier.GUIDANCE)

        if self.is_binding:
            raise BindingElevationError(
                "guidance records must not be marked binding/law"
            )
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

        for name in ("citation", "title", "source_url", "media_type", "superseded_by"):
            raw = getattr(self, name)
            if raw is not None:
                object.__setattr__(self, name, _require_non_empty_str(raw, name))

        if self.text_excerpt is not None:
            object.__setattr__(self, "text_excerpt", str(self.text_excerpt))

        if self.edition is not None:
            ed = _require_non_empty_str(self.edition, "edition")
            reject_hard_coded_latest(ed, field_name="edition")
            object.__setattr__(self, "edition", ed)
        if self.revision is not None:
            rev = _require_non_empty_str(self.revision, "revision")
            reject_hard_coded_latest(rev, field_name="revision")
            object.__setattr__(self, "revision", rev)

        for name in ("publication_date", "effective_start"):
            raw = getattr(self, name)
            if raw is not None:
                object.__setattr__(
                    self, name, _parse_required_date(raw, name=name)
                )

        if self.content_sha256 is not None:
            object.__setattr__(
                self, "content_sha256", _require_sha256(self.content_sha256, "content_sha256")
            )

        supersedes = tuple(
            _require_non_empty_str(str(item), "supersedes item")
            for item in (self.supersedes or ())
        )
        object.__setattr__(self, "supersedes", supersedes)

        if not isinstance(self.status, ResolutionStatus):
            object.__setattr__(self, "status", ResolutionStatus(str(self.status)))

        if self.stable_id is None and self.anchor is not None:
            object.__setattr__(
                self,
                "stable_id",
                stable_guidance_identity(kind=self.kind, anchor=self.anchor),
            )
        elif self.stable_id is not None:
            object.__setattr__(
                self, "stable_id", _require_non_empty_str(self.stable_id, "stable_id")
            )

        if not isinstance(self.metadata, Mapping):
            raise MpepGuidanceError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor": self.anchor,
            "authority_tier": self.authority_tier.value,
            "citation": self.citation,
            "content_sha256": self.content_sha256,
            "cutoff": _date_to_str(self.cutoff),
            "edition": self.edition,
            "effective_start": _date_to_str(self.effective_start),
            "guidance_id": self.guidance_id,
            "is_binding": False,
            "is_post_cutoff_publication": bool(self.is_post_cutoff_publication),
            "kind": self.kind.value,
            "media_type": self.media_type,
            "metadata": _deep_sorted(self.metadata),
            "publication_date": _date_to_str(self.publication_date),
            "revision": self.revision,
            "source_url": self.source_url,
            "stable_id": self.stable_id,
            "status": self.status.value,
            "superseded_by": self.superseded_by,
            "supersedes": list(self.supersedes),
            "text_excerpt": self.text_excerpt,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "GuidanceRecord":
        if not isinstance(value, Mapping):
            raise MpepGuidanceError("guidance record must be a mapping")
        if value.get("cutoff") in (None, ""):
            raise MissingCutoffError("cutoff is required on every guidance record")
        status_raw = value.get("status", ResolutionStatus.RESOLVED.value)
        status = (
            status_raw
            if isinstance(status_raw, ResolutionStatus)
            else ResolutionStatus(str(status_raw))
        )
        supersedes_raw = value.get("supersedes") or ()
        return cls(
            guidance_id=str(value.get("guidance_id") or value.get("id") or ""),
            kind=GuidanceKind.coerce(value.get("kind", GuidanceKind.OTHER)),
            cutoff=value["cutoff"],
            authority_tier=value.get("authority_tier", AuthorityTier.GUIDANCE),
            anchor=value.get("anchor") or value.get("section") or value.get("form_paragraph"),
            citation=value.get("citation"),
            title=value.get("title"),
            text_excerpt=value.get("text_excerpt"),
            edition=value.get("edition"),
            revision=value.get("revision"),
            publication_date=value.get("publication_date"),
            effective_start=value.get("effective_start"),
            source_url=value.get("source_url"),
            content_sha256=value.get("content_sha256"),
            media_type=value.get("media_type"),
            supersedes=tuple(supersedes_raw),
            superseded_by=value.get("superseded_by"),
            is_binding=bool(value.get("is_binding", False)),
            is_post_cutoff_publication=bool(value.get("is_post_cutoff_publication", False)),
            status=status,
            stable_id=value.get("stable_id"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class GuidanceAcquisition:
    """Result of acquiring one MPEP edition plus post-cutoff publications."""

    status: ResolutionStatus
    edition: Optional[GuidanceEdition]
    records: Mapping[str, GuidanceRecord]
    supersessions: tuple[SupersessionEdge, ...]
    freshness_gaps: tuple[FreshnessGap, ...]
    authority_sources: Mapping[str, AuthoritySourceRecord] = field(default_factory=dict)
    receipt: Optional[SourceReceipt] = None
    notes: Optional[str] = None
    unknown_reason: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, ResolutionStatus):
            object.__setattr__(self, "status", ResolutionStatus(str(self.status)))
        rec_map: dict[str, GuidanceRecord] = {}
        for key, rec in (self.records or {}).items():
            if isinstance(rec, GuidanceRecord):
                record = rec
            elif isinstance(rec, Mapping):
                record = GuidanceRecord.from_dict(rec)
            else:
                raise MpepGuidanceError("records values must be mappings or GuidanceRecord")
            rec_map[record.guidance_id] = record
        object.__setattr__(self, "records", rec_map)
        object.__setattr__(self, "supersessions", tuple(self.supersessions or ()))
        object.__setattr__(self, "freshness_gaps", tuple(self.freshness_gaps or ()))
        auth_map: dict[str, AuthoritySourceRecord] = {}
        for key, auth in (self.authority_sources or {}).items():
            if isinstance(auth, AuthoritySourceRecord):
                auth_map[auth.source_key] = auth
            elif isinstance(auth, Mapping):
                a = AuthoritySourceRecord.from_dict(auth)
                auth_map[a.source_key] = a
            else:
                raise MpepGuidanceError("authority_sources values must be records or mappings")
        object.__setattr__(self, "authority_sources", auth_map)
        if not isinstance(self.metadata, Mapping):
            raise MpepGuidanceError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def is_unknown(self) -> bool:
        return self.status is ResolutionStatus.UNKNOWN

    @property
    def cutoff(self) -> Optional[date]:
        return None if self.edition is None else self.edition.cutoff

    def get_record(self, guidance_id: str) -> GuidanceRecord:
        try:
            return self.records[guidance_id]
        except KeyError as exc:
            raise GuidanceNotFoundError(
                f"guidance_id {guidance_id!r} not present in acquisition"
            ) from exc

    def records_by_kind(self, kind: GuidanceKind | str) -> list[GuidanceRecord]:
        resolved = GuidanceKind.coerce(kind)
        return [r for r in self.records.values() if r.kind is resolved]

    def post_cutoff_publications(self) -> list[GuidanceRecord]:
        return [r for r in self.records.values() if r.is_post_cutoff_publication]

    def apply_supersession(self, edge: SupersessionEdge) -> "GuidanceAcquisition":
        """Return a copy with *edge* applied (predecessor/successor links).

        Both records remain guidance-tier and non-binding.
        """

        if edge.elevates_to_law or not edge.remains_guidance:
            raise BindingElevationError(
                "cannot apply supersession that elevates guidance to law"
            )
        if edge.successor_id not in self.records:
            raise GuidanceNotFoundError(
                f"successor {edge.successor_id!r} not in acquisition"
            )
        if edge.predecessor_id not in self.records:
            raise GuidanceNotFoundError(
                f"predecessor {edge.predecessor_id!r} not in acquisition"
            )

        successor = self.records[edge.successor_id]
        predecessor = self.records[edge.predecessor_id]

        # Both must stay guidance / non-binding.
        if (
            successor.authority_tier is not AuthorityTier.GUIDANCE
            or predecessor.authority_tier is not AuthorityTier.GUIDANCE
        ):
            raise BindingElevationError("supersession endpoints must remain guidance-tier")

        new_supersedes = tuple(
            dict.fromkeys([*successor.supersedes, edge.predecessor_id])
        )
        updated_successor = GuidanceRecord.from_dict(
            {
                **successor.to_dict(),
                "supersedes": list(new_supersedes),
            }
        )
        updated_predecessor = GuidanceRecord.from_dict(
            {
                **predecessor.to_dict(),
                "superseded_by": edge.successor_id,
            }
        )
        new_records = dict(self.records)
        new_records[updated_successor.guidance_id] = updated_successor
        new_records[updated_predecessor.guidance_id] = updated_predecessor
        new_edges = tuple([*self.supersessions, edge])
        return GuidanceAcquisition(
            status=self.status,
            edition=self.edition,
            records=new_records,
            supersessions=new_edges,
            freshness_gaps=self.freshness_gaps,
            authority_sources=self.authority_sources,
            receipt=self.receipt,
            notes=self.notes,
            unknown_reason=self.unknown_reason,
            metadata=self.metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_sources": {
                k: v.to_dict()
                for k, v in sorted(self.authority_sources.items(), key=lambda kv: kv[0])
            },
            "edition": None if self.edition is None else self.edition.to_dict(),
            "freshness_gaps": [g.to_dict() for g in self.freshness_gaps],
            "metadata": _deep_sorted(self.metadata),
            "notes": self.notes,
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "records": {
                k: v.to_dict()
                for k, v in sorted(self.records.items(), key=lambda kv: kv[0])
            },
            "schema_version": SCHEMA_VERSION,
            "status": self.status.value,
            "supersessions": [e.to_dict() for e in self.supersessions],
            "unknown_reason": self.unknown_reason,
        }

    def to_canonical_json(self) -> str:
        return canonical_json_dumps(self.to_dict())


# ---------------------------------------------------------------------------
# Fixture paths / builders
# ---------------------------------------------------------------------------


def default_fixture_dir() -> Path:
    """Return the repository guidance fixture directory when present."""

    here = Path(__file__).resolve()
    candidates = [
        here.parents[4] / "tests" / "fixtures" / "legal_data" / "patent_authorities" / "guidance",
        Path.cwd() / "tests" / "fixtures" / "legal_data" / "patent_authorities" / "guidance",
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


def _build_authority_source_for_record(
    record: GuidanceRecord,
    *,
    receipt: SourceReceipt | None = None,
) -> AuthoritySourceRecord:
    official: Optional[ArtifactIdentity] = None
    if record.content_sha256 and record.source_url:
        official = ArtifactIdentity(
            provider=DEFAULT_PROVIDER,
            source_id=record.guidance_id,
            artifact_sha256=record.content_sha256,
            source_url=record.source_url,
            media_type=record.media_type,
            role=IdentityRole.OFFICIAL_ARTIFACT,
            upstream_package_id=(
                f"mpep-{record.edition}-r{record.revision}"
                if record.edition and record.revision
                else record.guidance_id
            ),
        )
    collection = (
        COLLECTION_MPEP
        if record.kind in (GuidanceKind.MPEP_SECTION, GuidanceKind.FORM_PARAGRAPH)
        else COLLECTION_GUIDANCE
    )
    return AuthoritySourceRecord(
        source_key=record.guidance_id,
        authority_tier=AuthorityTier.GUIDANCE,
        collection=collection,
        jurisdiction=DEFAULT_JURISDICTION,
        citation=record.citation,
        edition=record.edition,
        version=record.revision,
        revision=record.revision,
        date_issued=record.publication_date,
        publication_date=record.publication_date,
        effective_start=record.effective_start or record.cutoff,
        official_artifact=official,
        receipt=receipt,
        verification_state=VerificationState.UNVERIFIED,
        notes=(
            "USPTO examination/operational guidance; not binding law. "
            f"cutoff={record.cutoff.isoformat()}"
        ),
        metadata={
            "anchor": record.anchor,
            "authority_schema": AUTHORITY_SCHEMA_VERSION,
            "cutoff": record.cutoff.isoformat(),
            "guidance_kind": record.kind.value,
            "is_binding": False,
            "is_post_cutoff_publication": bool(record.is_post_cutoff_publication),
            "processor_schema": SCHEMA_VERSION,
            "stable_id": record.stable_id,
            "supersedes": list(record.supersedes),
            "superseded_by": record.superseded_by,
        },
    )


def _build_receipt_for_edition(edition: GuidanceEdition) -> Optional[SourceReceipt]:
    if not edition.source_url and not edition.content_sha256:
        return None
    endpoint = edition.source_url or USPTO_MPEP_INDEX
    retrieved = edition.retrieved_at or datetime(1970, 1, 1, tzinfo=timezone.utc)
    return SourceReceipt(
        endpoint=endpoint,
        retrieved_at=retrieved,
        response_status=200,
        sanitized_request={"method": "GET", "path": endpoint},
        upstream_id=edition.edition_key,
        content_sha256=edition.content_sha256,
        retry_count=0,
        cache_hit=False,
        media_type="text/html",
        metadata={"provider": edition.provider, "cutoff": edition.cutoff.isoformat()},
    )


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class MpepGuidanceProcessor:
    """Acquire versioned MPEP, forms, fees, and later guidance artifacts.

    Primary path is fixture replay. Live network discovery is deliberately not
    performed by default so tests and offline operators remain deterministic.
    """

    def __init__(
        self,
        *,
        fixture_dir: PathLike | None = None,
        registry: AuthoritySourceRegistry | None = None,
        retry_cache_policy: RetryCachePolicy | None = None,
    ) -> None:
        self.fixture_dir = Path(fixture_dir) if fixture_dir else default_fixture_dir()
        self.registry = (
            registry
            if registry is not None
            else AuthoritySourceRegistry(default_retry_cache_policy=retry_cache_policy)
        )
        self._acquisitions: dict[str, GuidanceAcquisition] = {}

    # ------------------------------------------------------------------
    # Fixture acquisition
    # ------------------------------------------------------------------

    def load_fixture_package(self, path: PathLike | None = None) -> dict[str, Any]:
        target = Path(path) if path is not None else self._default_package_path()
        if target.is_dir():
            recipe = target / "mpep_guidance_recipe.json"
            if recipe.is_file():
                target = recipe
            else:
                raise FixtureSchemaError(
                    f"fixture directory {target} lacks mpep_guidance_recipe.json"
                )
        payload = load_json_fixture(target)
        schema = payload.get("schema_version")
        if schema and schema not in {FIXTURE_SCHEMA_VERSION, SCHEMA_VERSION}:
            if not str(schema).startswith("mpep-guidance"):
                raise FixtureSchemaError(
                    f"unsupported fixture schema_version {schema!r} in {target}"
                )
        return payload

    def _default_package_path(self) -> Path:
        recipe = self.fixture_dir / "mpep_guidance_recipe.json"
        if recipe.is_file():
            return recipe
        return self.fixture_dir

    def acquire_from_fixture(
        self,
        path: PathLike | None = None,
        *,
        register: bool = True,
    ) -> GuidanceAcquisition:
        payload = self.load_fixture_package(path)
        return self.acquire_from_payload(payload, register=register)

    def acquire_from_payload(
        self,
        payload: JsonMapping,
        *,
        register: bool = True,
    ) -> GuidanceAcquisition:
        if not isinstance(payload, Mapping):
            raise FixtureSchemaError("payload must be a mapping")

        edition_raw = payload.get("edition") or payload.get("mpep_edition")
        if not edition_raw:
            return GuidanceAcquisition(
                status=ResolutionStatus.UNKNOWN,
                edition=None,
                records={},
                supersessions=(),
                freshness_gaps=tuple(
                    FreshnessGap.from_dict(g)
                    for g in (payload.get("freshness_gaps") or [])
                    if isinstance(g, Mapping)
                ),
                notes="MPEP edition/cutoff unavailable; guidance authority is unknown.",
                unknown_reason="missing edition/cutoff data",
                metadata={"schema_version": payload.get("schema_version")},
            )

        if not isinstance(edition_raw, Mapping):
            raise FixtureSchemaError("edition must be a mapping")

        # Explicit null cutoff / missing edition identity → unknown.
        if edition_raw.get("cutoff") in (None, "") or edition_raw.get("edition") in (
            None,
            "",
        ):
            return GuidanceAcquisition(
                status=ResolutionStatus.UNKNOWN,
                edition=None,
                records={},
                supersessions=(),
                freshness_gaps=tuple(
                    FreshnessGap.from_dict(g)
                    for g in (payload.get("freshness_gaps") or [])
                    if isinstance(g, Mapping)
                ),
                notes="Edition mapping present but no concrete edition/cutoff.",
                unknown_reason="missing edition/cutoff data",
                metadata={"schema_version": payload.get("schema_version")},
            )

        try:
            edition = GuidanceEdition.from_dict(edition_raw)
        except (MissingCutoffError, HardCodedLatestEditionError, MpepGuidanceError) as exc:
            return GuidanceAcquisition(
                status=ResolutionStatus.UNKNOWN,
                edition=None,
                records={},
                supersessions=(),
                freshness_gaps=(),
                notes="Failed to parse guidance edition; treating authority as unknown.",
                unknown_reason=str(exc),
                metadata={
                    "schema_version": payload.get("schema_version"),
                    "error": str(exc),
                },
            )

        records: dict[str, GuidanceRecord] = {}
        for raw in payload.get("records") or payload.get("documents") or []:
            if not isinstance(raw, Mapping):
                continue
            item = dict(raw)
            # Inherit edition cutoff when a document omits its own cutoff so
            # every admitted record still surfaces a visible cutoff.
            if item.get("cutoff") in (None, ""):
                item["cutoff"] = edition.cutoff.isoformat()
            if item.get("edition") in (None, ""):
                item["edition"] = edition.edition
            if item.get("revision") in (None, ""):
                item["revision"] = edition.revision
            # Post-cutoff publications keep their own publication_date but still
            # record the manual cutoff they were listed against.
            pub = item.get("publication_date")
            if pub:
                try:
                    pub_date = _parse_required_date(pub, name="publication_date")
                    if pub_date > edition.cutoff:
                        item["is_post_cutoff_publication"] = True
                except MpepGuidanceError:
                    pass
            record = GuidanceRecord.from_dict(item)
            records[record.guidance_id] = record

        # Apply supersession edges from the fixture (and backfill link fields).
        edges: list[SupersessionEdge] = []
        for raw_edge in payload.get("supersessions") or []:
            if not isinstance(raw_edge, Mapping):
                continue
            edge = SupersessionEdge.from_dict(raw_edge)
            edges.append(edge)
            if edge.successor_id in records and edge.predecessor_id in records:
                successor = records[edge.successor_id]
                predecessor = records[edge.predecessor_id]
                new_supersedes = tuple(
                    dict.fromkeys([*successor.supersedes, edge.predecessor_id])
                )
                records[edge.successor_id] = GuidanceRecord.from_dict(
                    {**successor.to_dict(), "supersedes": list(new_supersedes)}
                )
                records[edge.predecessor_id] = GuidanceRecord.from_dict(
                    {**predecessor.to_dict(), "superseded_by": edge.successor_id}
                )

        gaps = tuple(
            FreshnessGap.from_dict(g)
            for g in (payload.get("freshness_gaps") or [])
            if isinstance(g, Mapping)
        )
        # Stamp edition cutoff onto gaps that omit it so tier/cutoff visibility
        # remains uniform even for gap outcomes.
        stamped_gaps: list[FreshnessGap] = []
        for gap in gaps:
            if gap.cutoff is None:
                stamped_gaps.append(
                    FreshnessGap.from_dict({**gap.to_dict(), "cutoff": edition.cutoff.isoformat()})
                )
            else:
                stamped_gaps.append(gap)
        gaps = tuple(stamped_gaps)

        receipt = _build_receipt_for_edition(edition)
        authority_sources: dict[str, AuthoritySourceRecord] = {}
        for record in records.values():
            if record.status is ResolutionStatus.FRESHNESS_GAP:
                continue
            auth = _build_authority_source_for_record(record, receipt=receipt)
            authority_sources[auth.source_key] = auth
            if register:
                self.registry.register(auth, overwrite=True)

        # Also register the edition package as a guidance authority source.
        if edition.content_sha256 and edition.source_url:
            package_auth = AuthoritySourceRecord(
                source_key=f"mpep-edition-{edition.edition_key}",
                authority_tier=AuthorityTier.GUIDANCE,
                collection=COLLECTION_MPEP,
                jurisdiction=DEFAULT_JURISDICTION,
                citation=f"MPEP {edition.edition} rev. {edition.revision}",
                edition=edition.edition,
                version=edition.revision,
                revision=edition.revision,
                publication_date=edition.publication_date or edition.cutoff,
                effective_start=edition.cutoff,
                official_artifact=ArtifactIdentity(
                    provider=edition.provider,
                    source_id=edition.edition_key,
                    artifact_sha256=edition.content_sha256,
                    source_url=edition.source_url,
                    role=IdentityRole.OFFICIAL_ARTIFACT,
                    upstream_package_id=edition.edition_key,
                ),
                receipt=receipt,
                verification_state=VerificationState.UNVERIFIED,
                notes=(
                    "MPEP edition package; guidance only, not binding law. "
                    f"cutoff={edition.cutoff.isoformat()}"
                ),
                metadata={
                    "cutoff": edition.cutoff.isoformat(),
                    "edition_key": edition.edition_key,
                    "is_binding": False,
                    "processor_schema": SCHEMA_VERSION,
                },
            )
            authority_sources[package_auth.source_key] = package_auth
            if register:
                self.registry.register(package_auth, overwrite=True)

        status = ResolutionStatus.RESOLVED
        if gaps and not records:
            status = ResolutionStatus.FRESHNESS_GAP
        elif gaps:
            status = ResolutionStatus.PARTIAL

        acquisition = GuidanceAcquisition(
            status=status,
            edition=edition,
            records=records,
            supersessions=tuple(edges),
            freshness_gaps=gaps,
            authority_sources=authority_sources,
            receipt=receipt,
            notes=payload.get("notes"),
            metadata={
                "schema_version": payload.get("schema_version") or FIXTURE_SCHEMA_VERSION,
                "fixture_id": payload.get("fixture_id"),
                "record_count": len(records),
                "gap_count": len(gaps),
                "supersession_count": len(edges),
                "cutoff": edition.cutoff.isoformat(),
            },
        )
        self._acquisitions[edition.edition_key] = acquisition
        return acquisition

    def acquire_unknown(
        self, *, reason: str = "missing edition/cutoff data"
    ) -> GuidanceAcquisition:
        return GuidanceAcquisition(
            status=ResolutionStatus.UNKNOWN,
            edition=None,
            records={},
            supersessions=(),
            freshness_gaps=(),
            notes="MPEP edition/cutoff unavailable; guidance authority is unknown.",
            unknown_reason=reason,
        )

    # ------------------------------------------------------------------
    # Freshness / change detection
    # ------------------------------------------------------------------

    def detect_content_change(
        self,
        *,
        source_id: str,
        expected_sha256: str,
        observed_sha256: str,
        source_url: Optional[str] = None,
        cutoff: date | str | None = None,
        detected_at: datetime | str | None = None,
    ) -> FreshnessGap:
        """Build an explicit freshness gap when artifact bytes change."""

        expected = _require_sha256(expected_sha256, "expected_sha256")
        observed = _require_sha256(observed_sha256, "observed_sha256")
        if expected == observed:
            raise MpepGuidanceError(
                "detect_content_change requires differing digests; "
                "identical content is not a freshness gap"
            )
        return FreshnessGap(
            gap_id=f"gap-changed-{source_id}",
            kind=FreshnessGapKind.CONTENT_CHANGED,
            source_id=source_id,
            reason=(
                f"Document bytes changed for {source_id}: expected {expected[:12]}… "
                f"observed {observed[:12]}…. Recorded as a new version boundary, "
                "not a silent overwrite."
            ),
            cutoff=_parse_optional_date(cutoff, name="cutoff"),
            expected_sha256=expected,
            observed_sha256=observed,
            source_url=source_url,
            detected_at=detected_at or datetime.now(timezone.utc),
            metadata={"change_kind": "content_sha256_mismatch"},
        )

    def detect_unavailable(
        self,
        *,
        source_id: str,
        reason: str,
        source_url: Optional[str] = None,
        cutoff: date | str | None = None,
        expected_sha256: Optional[str] = None,
        detected_at: datetime | str | None = None,
    ) -> FreshnessGap:
        """Build an explicit freshness gap when a document is unavailable."""

        return FreshnessGap(
            gap_id=f"gap-unavailable-{source_id}",
            kind=FreshnessGapKind.UNAVAILABLE,
            source_id=source_id,
            reason=reason,
            cutoff=_parse_optional_date(cutoff, name="cutoff"),
            expected_sha256=expected_sha256,
            source_url=source_url,
            detected_at=detected_at or datetime.now(timezone.utc),
        )

    def reconcile_observed_digest(
        self,
        acquisition: GuidanceAcquisition,
        *,
        guidance_id: str,
        observed_sha256: str,
    ) -> FreshnessGap | None:
        """Return a content-changed gap when *observed_sha256* differs, else None."""

        record = acquisition.get_record(guidance_id)
        if record.content_sha256 is None:
            return None
        observed = _require_sha256(observed_sha256, "observed_sha256")
        if observed == record.content_sha256:
            return None
        return self.detect_content_change(
            source_id=guidance_id,
            expected_sha256=record.content_sha256,
            observed_sha256=observed,
            source_url=record.source_url,
            cutoff=record.cutoff,
        )

    # ------------------------------------------------------------------
    # Supersession API
    # ------------------------------------------------------------------

    def supersede_manual_text(
        self,
        acquisition: GuidanceAcquisition,
        *,
        later_guidance_id: str,
        manual_guidance_id: str,
        relation: SupersessionRelation | str = SupersessionRelation.SUPERSEDES,
        effective_date: date | str | None = None,
        reason: str | None = None,
    ) -> GuidanceAcquisition:
        """Apply later guidance superseding inconsistent MPEP manual text.

        Both artifacts remain ``authority_tier=guidance`` and non-binding.
        """

        edge = SupersessionEdge(
            successor_id=later_guidance_id,
            predecessor_id=manual_guidance_id,
            relation=SupersessionRelation.coerce(relation),
            effective_date=effective_date,
            reason=reason
            or (
                "Later examination guidance supersedes inconsistent MPEP manual "
                "text for operational practice; neither is elevated to law."
            ),
            remains_guidance=True,
            elevates_to_law=False,
        )
        updated = acquisition.apply_supersession(edge)
        # Keep processor cache consistent when the acquisition is known.
        if acquisition.edition is not None:
            self._acquisitions[acquisition.edition.edition_key] = updated
        return updated

    def assert_not_elevated_to_law(self, acquisition: GuidanceAcquisition) -> None:
        """Fail closed if any admitted record is binding or non-guidance."""

        for record in acquisition.records.values():
            if record.is_binding:
                raise BindingElevationError(
                    f"{record.guidance_id} is marked binding; guidance cannot be law"
                )
            if record.authority_tier is not AuthorityTier.GUIDANCE:
                raise BindingElevationError(
                    f"{record.guidance_id} has tier {record.authority_tier.value}; "
                    "expected guidance"
                )
        for edge in acquisition.supersessions:
            if edge.elevates_to_law or not edge.remains_guidance:
                raise BindingElevationError(
                    f"supersession {edge.successor_id}->{edge.predecessor_id} "
                    "must not elevate guidance to law"
                )

    def every_record_exposes_tier_and_cutoff(
        self, acquisition: GuidanceAcquisition
    ) -> bool:
        """Return True when every record exposes guidance tier and cutoff."""

        if not acquisition.records:
            return acquisition.status is ResolutionStatus.UNKNOWN
        for record in acquisition.records.values():
            if record.authority_tier is not AuthorityTier.GUIDANCE:
                return False
            if record.cutoff is None:
                return False
            if record.is_binding:
                return False
        for gap in acquisition.freshness_gaps:
            if gap.authority_tier is not AuthorityTier.GUIDANCE:
                return False
        return True

    def get_acquisition(self, edition_key: str) -> GuidanceAcquisition:
        try:
            return self._acquisitions[edition_key]
        except KeyError as exc:
            raise MpepGuidanceError(
                f"no acquisition for edition_key {edition_key!r}"
            ) from exc


# ---------------------------------------------------------------------------
# Compact fixture recipe generators
# ---------------------------------------------------------------------------


def build_mpep_guidance_fixture_recipe(
    *,
    edition: str = "9",
    revision: str = "07.2022",
    cutoff: str = "2022-07-01",
    fixture_id: str = "mpep-9-r07.2022",
) -> dict[str, Any]:
    """Build a compact deterministic MPEP/guidance fixture recipe.

    Prefer this generator over bulk golden dumps that re-emit full envelopes.
    """

    edition_s, revision_s = parse_mpep_edition_revision(edition=edition, revision=revision)
    cutoff_date = date.fromisoformat(cutoff)
    edition_key = f"mpep-{edition_s}-r{revision_s}"
    package_sha = content_sha256(f"uspto|{edition_key}|package")
    source_url = USPTO_MPEP_INDEX

    mpep_2106_sha = content_sha256(f"{edition_key}|section|2106")
    mpep_706_sha = content_sha256(f"{edition_key}|section|706.02")
    fp_705_sha = content_sha256(f"{edition_key}|fp|7.05")
    form_sb08_sha = content_sha256(f"{edition_key}|form|PTO/SB/08")
    fee_fy2024_sha = content_sha256(f"{edition_key}|fees|fy2024")
    guide_sha = content_sha256(f"{edition_key}|exam-guide|1-23")
    notice_sha = content_sha256(f"{edition_key}|notice|2023-10-17")

    records = [
        {
            "guidance_id": "mpep-2106",
            "kind": "mpep_section",
            "anchor": "2106",
            "citation": "MPEP § 2106",
            "title": "Patent Subject Matter Eligibility",
            "text_excerpt": (
                "Subject matter eligibility under 35 U.S.C. 101 is determined "
                "using the two-part framework..."
            ),
            "edition": edition_s,
            "revision": revision_s,
            "cutoff": cutoff,
            "publication_date": cutoff,
            "source_url": mpep_source_url(section="2106"),
            "content_sha256": mpep_2106_sha,
            "media_type": "text/html",
            "is_post_cutoff_publication": False,
        },
        {
            "guidance_id": "mpep-706.02",
            "kind": "mpep_section",
            "anchor": "706.02",
            "citation": "MPEP § 706.02",
            "title": "Rejection on Prior Art",
            "text_excerpt": (
                "Under the dual patenting and prior-art framework described in "
                "this revision, examiners apply the manual text unless later "
                "guidance states otherwise..."
            ),
            "edition": edition_s,
            "revision": revision_s,
            "cutoff": cutoff,
            "publication_date": cutoff,
            "source_url": mpep_source_url(section="706.02"),
            "content_sha256": mpep_706_sha,
            "media_type": "text/html",
            "is_post_cutoff_publication": False,
        },
        {
            "guidance_id": "fp-7.05",
            "kind": "form_paragraph",
            "anchor": "7.05",
            "citation": "Form Paragraph 7.05",
            "title": "Rejection, 35 U.S.C. 101, Non-Statutory",
            "text_excerpt": (
                "Claim [1] is rejected under 35 U.S.C. 101 because the claimed "
                "invention is directed to a judicial exception..."
            ),
            "edition": edition_s,
            "revision": revision_s,
            "cutoff": cutoff,
            "publication_date": cutoff,
            "source_url": f"{USPTO_MPEP_INDEX}#fp-7.05",
            "content_sha256": fp_705_sha,
            "media_type": "text/html",
            "is_post_cutoff_publication": False,
        },
        {
            "guidance_id": "form-pto-sb-08",
            "kind": "form",
            "anchor": "PTO/SB/08",
            "citation": "PTO/SB/08",
            "title": "Information Disclosure Statement",
            "text_excerpt": "Form for listing information disclosure references.",
            "edition": edition_s,
            "revision": revision_s,
            "cutoff": cutoff,
            "publication_date": cutoff,
            "source_url": f"{USPTO_FORMS_BASE}/sb0008.pdf",
            "content_sha256": form_sb08_sha,
            "media_type": "application/pdf",
            "is_post_cutoff_publication": False,
        },
        {
            "guidance_id": "fees-fy2024",
            "kind": "fee_schedule",
            "anchor": "FY2024",
            "citation": "USPTO Fee Schedule FY2024",
            "title": "Patent Fee Schedule FY2024",
            "text_excerpt": "Fee amounts effective for fiscal year 2024.",
            "edition": edition_s,
            "revision": revision_s,
            "cutoff": cutoff,
            # Fee schedule published after MPEP cutoff — later publication.
            "publication_date": "2023-10-01",
            "effective_start": "2023-10-01",
            "source_url": f"{USPTO_FEES_BASE}/fy2024",
            "content_sha256": fee_fy2024_sha,
            "media_type": "text/html",
            "is_post_cutoff_publication": True,
        },
        {
            "guidance_id": "exam-guide-1-23",
            "kind": "examination_guide",
            "anchor": "1-23",
            "citation": "Examination Guide 1-23",
            "title": "Updated Prior-Art Practice (post-cutoff)",
            "text_excerpt": (
                "This examination guide supersedes inconsistent MPEP § 706.02 "
                "manual text regarding dual-framework application for the "
                "scenarios listed herein. This guide is guidance only and does "
                "not have the force and effect of law."
            ),
            "edition": edition_s,
            "revision": revision_s,
            "cutoff": cutoff,
            "publication_date": "2023-03-15",
            "effective_start": "2023-03-15",
            "source_url": f"{USPTO_EXAM_GUIDE_BASE}/examination-guide-1-23.pdf",
            "content_sha256": guide_sha,
            "media_type": "application/pdf",
            "is_post_cutoff_publication": True,
            "supersedes": ["mpep-706.02"],
        },
        {
            "guidance_id": "notice-2023-10-17",
            "kind": "notice",
            "anchor": "2023-10-17-eligibility",
            "citation": "OG Notice 2023-10-17",
            "title": "Subject Matter Eligibility Update Notice",
            "text_excerpt": (
                "This notice clarifies examination practice under MPEP § 2106 "
                "for certain AI-related claims. Guidance only; not law."
            ),
            "edition": edition_s,
            "revision": revision_s,
            "cutoff": cutoff,
            "publication_date": "2023-10-17",
            "effective_start": "2023-10-17",
            "source_url": f"{USPTO_EXAM_GUIDE_BASE}/notice-2023-10-17.html",
            "content_sha256": notice_sha,
            "media_type": "text/html",
            "is_post_cutoff_publication": True,
            "supersedes": ["mpep-2106"],
        },
    ]

    supersessions = [
        {
            "successor_id": "exam-guide-1-23",
            "predecessor_id": "mpep-706.02",
            "relation": "supersedes",
            "effective_date": "2023-03-15",
            "reason": (
                "Examination Guide 1-23 supersedes inconsistent MPEP § 706.02 "
                "manual text for listed scenarios; both remain guidance, not law."
            ),
            "remains_guidance": True,
            "elevates_to_law": False,
        },
        {
            "successor_id": "notice-2023-10-17",
            "predecessor_id": "mpep-2106",
            "relation": "partially_supersedes",
            "effective_date": "2023-10-17",
            "reason": (
                "OG notice partially supersedes MPEP § 2106 practice notes for "
                "AI-related claims; neither is elevated to statute or regulation."
            ),
            "remains_guidance": True,
            "elevates_to_law": False,
        },
    ]

    freshness_gaps = [
        {
            "gap_id": "gap-unavailable-exam-guide-2-23",
            "kind": "unavailable",
            "source_id": "exam-guide-2-23",
            "reason": (
                "Examination Guide 2-23 is listed in the post-cutoff inventory "
                "but the public PDF is currently unavailable (HTTP 404)."
            ),
            "cutoff": cutoff,
            "source_url": f"{USPTO_EXAM_GUIDE_BASE}/examination-guide-2-23.pdf",
            "detected_at": "2024-06-01T12:00:00Z",
            "expected_sha256": content_sha256(f"{edition_key}|exam-guide|2-23"),
        },
        {
            "gap_id": "gap-changed-form-pto-sb-08",
            "kind": "content_changed",
            "source_id": "form-pto-sb-08",
            "reason": (
                "Form PTO/SB/08 bytes changed relative to the recorded edition "
                "snapshot; treat as a new version, not a silent overwrite."
            ),
            "cutoff": cutoff,
            "expected_sha256": form_sb08_sha,
            "observed_sha256": content_sha256(f"{edition_key}|form|PTO/SB/08|changed"),
            "source_url": f"{USPTO_FORMS_BASE}/sb0008.pdf",
            "detected_at": "2024-06-01T12:05:00Z",
        },
        {
            "gap_id": "gap-delayed-fee-inventory",
            "kind": "delayed_inventory",
            "source_id": "fees-fy2025-inventory",
            "reason": (
                "FY2025 fee schedule inventory is delayed upstream; this is a "
                "freshness gap, not evidence of non-receipt of any filing."
            ),
            "cutoff": cutoff,
            "source_url": f"{USPTO_FEES_BASE}/fy2025",
            "detected_at": "2024-06-01T12:10:00Z",
        },
    ]

    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "fixture_id": fixture_id,
        "notes": (
            "Compact MPEP/forms/fees/later-guidance recipe. Every record exposes "
            "authority_tier=guidance and the edition cutoff. Later Examination "
            "Guides and notices supersede inconsistent manual text without "
            "elevating either to law. Unavailable/changed documents are explicit "
            "freshness gaps."
        ),
        "edition": {
            "provider": DEFAULT_PROVIDER,
            "edition": edition_s,
            "revision": revision_s,
            "cutoff": cutoff,
            "publication_date": cutoff,
            "source_url": source_url,
            "content_sha256": package_sha,
            "retrieved_at": "2024-06-01T10:00:00Z",
            "notes": f"MPEP {edition_s} Edition, Revision {revision_s}",
        },
        "records": records,
        "supersessions": supersessions,
        "freshness_gaps": freshness_gaps,
    }


def build_unavailable_guidance_fixture() -> dict[str, Any]:
    """Fixture where the entire edition package is unavailable."""

    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "fixture_id": "mpep-unavailable-edition",
        "notes": "Edition identity omitted; resolves as unknown with freshness gaps.",
        "edition": {
            "provider": DEFAULT_PROVIDER,
            "edition": None,
            "revision": None,
            "cutoff": None,
        },
        "records": [],
        "supersessions": [],
        "freshness_gaps": [
            {
                "gap_id": "gap-unavailable-mpep-index",
                "kind": "unavailable",
                "source_id": "mpep-index",
                "reason": "MPEP index page unavailable during retrieval window.",
                "source_url": USPTO_MPEP_INDEX,
                "detected_at": "2024-06-01T09:00:00Z",
            }
        ],
    }


def write_default_fixtures(directory: PathLike | None = None) -> Path:
    """Materialize the default guidance recipe and unavailable-edition case."""

    root = Path(directory) if directory is not None else default_fixture_dir()
    root.mkdir(parents=True, exist_ok=True)

    recipe = build_mpep_guidance_fixture_recipe()
    recipe_path = root / "mpep_guidance_recipe.json"
    recipe_path.write_text(
        json.dumps(recipe, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    missing = build_unavailable_guidance_fixture()
    missing_path = root / "mpep_unavailable_edition.json"
    missing_path.write_text(
        json.dumps(missing, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(
            "# USPTO MPEP / guidance fixtures\n\n"
            "Compact recipes for PATLAW-015. Prefer `mpep_guidance_recipe.json` "
            "over bulk golden dumps. Unavailable edition data is modeled in "
            "`mpep_unavailable_edition.json` and must resolve as `unknown` with "
            "explicit freshness gaps. Later guidance may supersede manual text "
            "without elevating either artifact to law.\n",
            encoding="utf-8",
        )
    return root


__all__ = [
    "COLLECTION_GUIDANCE",
    "COLLECTION_MPEP",
    "DEFAULT_JURISDICTION",
    "DEFAULT_PROVIDER",
    "FIXTURE_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "USPTO_EXAM_GUIDE_BASE",
    "USPTO_FEES_BASE",
    "USPTO_FORMS_BASE",
    "USPTO_MPEP_INDEX",
    "BindingElevationError",
    "FixtureSchemaError",
    "FreshnessGap",
    "FreshnessGapKind",
    "GuidanceAcquisition",
    "GuidanceEdition",
    "GuidanceKind",
    "GuidanceNotFoundError",
    "GuidanceRecord",
    "MissingCutoffError",
    "MpepGuidanceError",
    "MpepGuidanceProcessor",
    "ResolutionStatus",
    "SupersessionEdge",
    "SupersessionRelation",
    "build_mpep_guidance_fixture_recipe",
    "build_unavailable_guidance_fixture",
    "content_sha256",
    "default_fixture_dir",
    "load_json_fixture",
    "mpep_source_url",
    "normalize_form_paragraph",
    "normalize_mpep_section",
    "parse_mpep_edition_revision",
    "stable_guidance_identity",
    "write_default_fixtures",
]
