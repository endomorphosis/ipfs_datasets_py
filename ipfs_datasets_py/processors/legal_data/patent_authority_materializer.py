"""Scheduled temporal patent-authority snapshot materializer (PATLAW-135).

Runs incremental acquisitions on explicit schedules, normalizes and
cross-links versioned authority records, builds immutable content-addressed
as-of snapshots with freshness manifests, retains conflicts and research
gaps, and never mutates prior snapshots.

Design invariants:

* Replaying identical inputs yields byte-identical snapshots.
* Changed sources create new snapshots; old snapshot bytes are never rewritten.
* As-of queries exclude records whose effective_start is after the query date
  (later law never leaks into earlier views).
* Authority kind, tier, and rendition legal status remain independent fields.
* Absent adjudicatory coverage is a visible blocking research gap.
* Stale, missing, or conflicting mandatory sources block authoritative-ready.
* No network I/O on import or fixture replay; connectors own live fetches.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Mapping, Optional, Sequence, Union

from ipfs_datasets_py.processors.legal_data.patent_authority_contracts_v2 import (
    AuthorityKind,
    ContentAddress,
    RenditionLegalStatus,
    acceptance_class_for_kind,
    assert_dimensions_independent,
    canonical_json_bytes,
    canonical_json_dumps,
    coerce_authority_kind,
    coerce_authority_tier,
    coerce_rendition_legal_status,
    coerce_verification_state,
    content_address_bytes,
    content_address_mapping,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_registry import (
    AsOfQuery,
    AsOfViewRole,
    AuthorityTemporalEdge,
    AuthorityTextNode,
    AuthorityViewKind,
    PatentTemporalAuthorityGraph,
    PatentTemporalAuthorityGraphBuilder,
    ResolutionStatus,
    TemporalRelation,
    resolve_as_of,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    ArtifactIdentity,
    AuthorityTier,
    HardCodedLatestEditionError,
    IdentityRole,
    VerificationState,
    reject_hard_coded_latest,
)

SCHEMA_VERSION: Final = "patent-authority-materializer-v1"
FIXTURE_SCHEMA_VERSION: Final = "temporal-materialization-recipe-v1"
SNAPSHOT_MANIFEST_NAME: Final = "snapshot.json"
FRESHNESS_MANIFEST_NAME: Final = "freshness.json"
INDEX_NAME: Final = "index.json"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LATEST_TOKEN_RE = re.compile(r"^\s*latest\s*$", re.IGNORECASE)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PatentAuthorityMaterializerError(ValueError):
    """Base error for temporal authority materialization failures."""


class RecipeSchemaError(PatentAuthorityMaterializerError):
    """Raised when a temporal materialization recipe fails schema validation."""


class SnapshotImmutabilityError(PatentAuthorityMaterializerError):
    """Raised when an attempt is made to mutate an existing snapshot payload."""


class SnapshotNotFoundError(PatentAuthorityMaterializerError):
    """Raised when a requested snapshot content address is absent."""


class HardCodedLatestError(PatentAuthorityMaterializerError, HardCodedLatestEditionError):
    """Raised when a source uses the hard-coded edition token ``latest``."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SourceFreshnessStatus(str, Enum):
    """Freshness classification for one scheduled source."""

    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"

    @classmethod
    def coerce(cls, value: Any) -> "SourceFreshnessStatus":
        if isinstance(value, cls):
            return value
        text = str(value or "unknown").strip().lower().replace("-", "_")
        for member in cls:
            if member.value == text or member.name.lower() == text:
                return member
        raise PatentAuthorityMaterializerError(
            f"unsupported source freshness status: {value!r}"
        )


class AuthoritativeBlockReason(str, Enum):
    """Why a snapshot is not authoritative-ready."""

    STALE_MANDATORY_SOURCE = "stale_mandatory_source"
    MISSING_MANDATORY_SOURCE = "missing_mandatory_source"
    CONFLICTING_MANDATORY_SOURCE = "conflicting_mandatory_source"
    ADJUDICATORY_RESEARCH_GAP = "adjudicatory_research_gap"
    VERIFICATION_CONFLICT = "verification_conflict"
    HARD_CODED_LATEST = "hard_coded_latest"
    EMPTY_SNAPSHOT = "empty_snapshot"


class ScheduleKind(str, Enum):
    """How the materialization schedule advances."""

    INCREMENTAL = "incremental"
    FULL = "full"
    REPLAY = "replay"

    @classmethod
    def coerce(cls, value: Any) -> "ScheduleKind":
        if isinstance(value, cls):
            return value
        text = str(value or "incremental").strip().lower().replace("-", "_")
        for member in cls:
            if member.value == text or member.name.lower() == text:
                return member
        raise PatentAuthorityMaterializerError(f"unsupported schedule kind: {value!r}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PatentAuthorityMaterializerError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise PatentAuthorityMaterializerError(f"{name} must not contain NUL")
    return value.strip()


def _optional_str(value: Any, name: str) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, name)


def _require_sha256(value: Any, name: str = "sha256") -> str:
    text = _require_non_empty_str(value, name).lower()
    if not _SHA256_RE.fullmatch(text):
        raise PatentAuthorityMaterializerError(
            f"{name} must be a lowercase 64-char hex SHA-256"
        )
    return text


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
            raise PatentAuthorityMaterializerError(
                f"{name} must be an ISO date"
            ) from exc
    raise PatentAuthorityMaterializerError(f"{name} must be a date or ISO date string")


def _require_date(value: Any, *, name: str) -> date:
    parsed = _parse_optional_date(value, name=name)
    if parsed is None:
        raise PatentAuthorityMaterializerError(f"{name} is required")
    return parsed


def _date_to_str(value: Optional[date]) -> Optional[str]:
    return None if value is None else value.isoformat()


def _parse_utc_datetime(value: Any, *, name: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise PatentAuthorityMaterializerError(
                f"{name} must be an ISO-8601 datetime"
            ) from exc
    else:
        raise PatentAuthorityMaterializerError(
            f"{name} must be a datetime or ISO-8601 string"
        )
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
            str(k): _deep_sorted(value[k])
            for k in sorted(value.keys(), key=lambda x: str(x))
        }
    if isinstance(value, (list, tuple)):
        return [_deep_sorted(v) for v in value]
    return value


def _reject_latest(value: Any, *, field_name: str) -> None:
    if value is None:
        return
    if isinstance(value, str) and _LATEST_TOKEN_RE.fullmatch(value):
        raise HardCodedLatestError(
            f"{field_name} must not be the hard-coded token 'latest'; "
            "discover the concrete edition/release at runtime and record it"
        )
    try:
        reject_hard_coded_latest(value, field_name=field_name)
    except HardCodedLatestEditionError as exc:
        raise HardCodedLatestError(str(exc)) from exc


def _stable_label_sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _optional_artifact(
    value: ArtifactIdentity | Mapping[str, Any] | None,
    *,
    role: IdentityRole,
) -> Optional[ArtifactIdentity]:
    if value is None:
        return None
    if isinstance(value, ArtifactIdentity):
        if value.role is not role:
            return ArtifactIdentity(
                provider=value.provider,
                source_id=value.source_id,
                artifact_sha256=value.artifact_sha256,
                source_url=value.source_url,
                role=role,
                media_type=value.media_type,
                upstream_package_id=value.upstream_package_id,
                byte_size=value.byte_size,
            )
        return value
    if isinstance(value, Mapping):
        payload = dict(value)
        payload.setdefault("role", role.value)
        return ArtifactIdentity.from_dict(payload)
    raise PatentAuthorityMaterializerError(
        "artifact identity must be ArtifactIdentity or mapping"
    )


# ---------------------------------------------------------------------------
# Adjudicatory coverage (blocking research gap when absent)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdjudicatoryCoverage:
    """Adjudicatory authority coverage status for complete-law claims.

    When coverage is absent, :attr:`is_blocking_research_gap` is True and no
    complete-law / authoritative-ready conclusion may be drawn.
    """

    present: bool
    status: str  # present | research_gap | partial
    notes: str
    authorities: tuple[str, ...] = ()
    is_blocking_research_gap: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "status", _require_non_empty_str(self.status, "status").lower()
        )
        object.__setattr__(self, "notes", _require_non_empty_str(self.notes, "notes"))
        cleaned = tuple(
            _require_non_empty_str(a, "authorities[]") for a in self.authorities
        )
        object.__setattr__(self, "authorities", cleaned)
        object.__setattr__(self, "present", bool(self.present))
        if not self.present:
            object.__setattr__(self, "is_blocking_research_gap", True)
            if self.status not in {"research_gap", "missing", "absent"}:
                object.__setattr__(self, "status", "research_gap")
        else:
            object.__setattr__(self, "is_blocking_research_gap", False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorities": list(self.authorities),
            "is_blocking_research_gap": bool(self.is_blocking_research_gap),
            "notes": self.notes,
            "present": bool(self.present),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping | None) -> "AdjudicatoryCoverage":
        if value is None:
            return cls.research_gap()
        if not isinstance(value, Mapping):
            raise RecipeSchemaError("adjudicatory_coverage must be a mapping")
        present = bool(value.get("present", False))
        status = str(
            value.get("status") or ("present" if present else "research_gap")
        )
        notes = str(
            value.get("notes")
            or (
                "Adjudicatory authorities recorded."
                if present
                else (
                    "Missing adjudicatory coverage is a declared research-coverage "
                    "gap and cannot support a complete-law conclusion."
                )
            )
        )
        raw_auth = value.get("authorities") or ()
        if not isinstance(raw_auth, (list, tuple)):
            raise RecipeSchemaError("adjudicatory authorities must be a sequence")
        return cls(
            present=present,
            status=status,
            notes=notes,
            authorities=tuple(str(a) for a in raw_auth),
            is_blocking_research_gap=not present,
        )

    @classmethod
    def research_gap(cls, notes: str | None = None) -> "AdjudicatoryCoverage":
        return cls(
            present=False,
            status="research_gap",
            notes=notes
            or (
                "Missing adjudicatory coverage is a declared research-coverage "
                "gap and cannot support a complete-law conclusion."
            ),
            authorities=(),
            is_blocking_research_gap=True,
        )


# ---------------------------------------------------------------------------
# Source records for materialization
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MaterializedAuthorityRecord:
    """One versioned authority record admitted into a temporal snapshot.

    Kind, tier, and rendition legal status are independent and must not
    collapse into a single field.
    """

    record_id: str
    citation_key: str
    authority_kind: AuthorityKind
    authority_tier: AuthorityTier
    rendition_legal_status: RenditionLegalStatus
    collection: str
    source_key: str
    jurisdiction: str = "US"
    citation: Optional[str] = None
    title: Optional[str] = None
    edition: Optional[str] = None
    version: Optional[str] = None
    release_point: Optional[str] = None
    package_id: Optional[str] = None
    granule_id: Optional[str] = None
    text_excerpt: Optional[str] = None
    publication_date: Optional[date] = None
    effective_start: Optional[date] = None
    effective_end: Optional[date] = None
    retrieved_at: Optional[datetime] = None
    is_binding: bool = False
    is_proposed: bool = False
    is_withdrawn: bool = False
    is_mandatory: bool = False
    verification_state: VerificationState = VerificationState.UNVERIFIED
    official_artifact: Optional[ArtifactIdentity] = None
    derived_presentation: Optional[ArtifactIdentity] = None
    content_sha256: Optional[str] = None
    media_type: Optional[str] = None
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    freshness_max_age_days: Optional[int] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "record_id", _require_non_empty_str(self.record_id, "record_id")
        )
        object.__setattr__(
            self,
            "citation_key",
            _require_non_empty_str(self.citation_key, "citation_key"),
        )
        object.__setattr__(
            self, "source_key", _require_non_empty_str(self.source_key, "source_key")
        )
        object.__setattr__(
            self, "collection", _require_non_empty_str(self.collection, "collection")
        )
        object.__setattr__(
            self,
            "jurisdiction",
            _require_non_empty_str(self.jurisdiction, "jurisdiction"),
        )

        kind, tier, rendition = assert_dimensions_independent(
            authority_kind=self.authority_kind,
            authority_tier=self.authority_tier,
            rendition_legal_status=self.rendition_legal_status,
            allow_incompatible=False,
        )
        object.__setattr__(self, "authority_kind", kind)
        object.__setattr__(self, "authority_tier", tier)
        object.__setattr__(self, "rendition_legal_status", rendition)

        for name in ("edition", "version", "release_point", "package_id", "granule_id"):
            raw = getattr(self, name)
            if raw is not None:
                cleaned = _require_non_empty_str(raw, name)
                _reject_latest(cleaned, field_name=name)
                object.__setattr__(self, name, cleaned)

        for name in ("publication_date", "effective_start", "effective_end"):
            object.__setattr__(
                self, name, _parse_optional_date(getattr(self, name), name=name)
            )
        if self.effective_start and self.effective_end:
            if self.effective_end < self.effective_start:
                raise PatentAuthorityMaterializerError(
                    "effective_end must be on or after effective_start"
                )

        if self.retrieved_at is not None:
            object.__setattr__(
                self,
                "retrieved_at",
                _parse_utc_datetime(self.retrieved_at, name="retrieved_at"),
            )

        object.__setattr__(
            self,
            "verification_state",
            coerce_verification_state(self.verification_state),
        )
        object.__setattr__(
            self,
            "official_artifact",
            _optional_artifact(
                self.official_artifact, role=IdentityRole.OFFICIAL_ARTIFACT
            ),
        )
        object.__setattr__(
            self,
            "derived_presentation",
            _optional_artifact(
                self.derived_presentation, role=IdentityRole.DERIVED_PRESENTATION
            ),
        )

        if self.content_sha256 is not None:
            object.__setattr__(
                self, "content_sha256", _require_sha256(self.content_sha256, "content_sha256")
            )
        elif self.official_artifact is not None:
            object.__setattr__(
                self, "content_sha256", self.official_artifact.artifact_sha256
            )
        elif self.derived_presentation is not None:
            object.__setattr__(
                self, "content_sha256", self.derived_presentation.artifact_sha256
            )

        if self.is_proposed or self.is_withdrawn:
            object.__setattr__(self, "is_binding", False)

        if self.freshness_max_age_days is not None:
            if (
                not isinstance(self.freshness_max_age_days, int)
                or isinstance(self.freshness_max_age_days, bool)
                or self.freshness_max_age_days < 0
            ):
                raise PatentAuthorityMaterializerError(
                    "freshness_max_age_days must be a non-negative int"
                )

        if not isinstance(self.metadata, Mapping):
            raise PatentAuthorityMaterializerError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def acceptance_class(self) -> str:
        return acceptance_class_for_kind(self.authority_kind)

    def covers(self, as_of: date) -> bool:
        """Return whether *as_of* falls inside the record's effective interval."""

        if self.effective_start is not None and as_of < self.effective_start:
            return False
        if self.effective_end is not None and as_of > self.effective_end:
            return False
        return True

    def is_future_as_of(self, as_of: date) -> bool:
        return self.effective_start is not None and as_of < self.effective_start

    def to_dict(self) -> dict[str, Any]:
        return {
            "acceptance_class": self.acceptance_class,
            "authority_kind": self.authority_kind.value,
            "authority_tier": self.authority_tier.value,
            "citation": self.citation,
            "citation_key": self.citation_key,
            "collection": self.collection,
            "content_sha256": self.content_sha256,
            "derived_presentation": (
                None
                if self.derived_presentation is None
                else self.derived_presentation.to_dict()
            ),
            "edition": self.edition,
            "effective_end": _date_to_str(self.effective_end),
            "effective_start": _date_to_str(self.effective_start),
            "freshness_max_age_days": self.freshness_max_age_days,
            "granule_id": self.granule_id,
            "is_binding": bool(self.is_binding),
            "is_mandatory": bool(self.is_mandatory),
            "is_proposed": bool(self.is_proposed),
            "is_withdrawn": bool(self.is_withdrawn),
            "jurisdiction": self.jurisdiction,
            "media_type": self.media_type,
            "metadata": _deep_sorted(self.metadata),
            "notes": self.notes,
            "official_artifact": (
                None
                if self.official_artifact is None
                else self.official_artifact.to_dict()
            ),
            "package_id": self.package_id,
            "publication_date": _date_to_str(self.publication_date),
            "record_id": self.record_id,
            "release_point": self.release_point,
            "rendition_legal_status": self.rendition_legal_status.value,
            "retrieved_at": (
                None if self.retrieved_at is None else _format_utc(self.retrieved_at)
            ),
            "source_key": self.source_key,
            "text_excerpt": self.text_excerpt,
            "title": self.title,
            "verification_state": self.verification_state.value,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "MaterializedAuthorityRecord":
        if not isinstance(value, Mapping):
            raise RecipeSchemaError("authority record must be a mapping")
        return cls(
            record_id=str(value.get("record_id") or value.get("id") or ""),
            citation_key=str(value.get("citation_key") or value.get("key") or ""),
            authority_kind=coerce_authority_kind(
                value.get("authority_kind") or value.get("kind")
            ),
            authority_tier=coerce_authority_tier(
                value.get("authority_tier") or value.get("tier")
            ),
            rendition_legal_status=coerce_rendition_legal_status(
                value.get("rendition_legal_status") or value.get("rendition")
            ),
            collection=str(value.get("collection") or ""),
            source_key=str(value.get("source_key") or value.get("record_id") or ""),
            jurisdiction=str(value.get("jurisdiction") or "US"),
            citation=value.get("citation"),
            title=value.get("title"),
            edition=value.get("edition"),
            version=value.get("version"),
            release_point=value.get("release_point"),
            package_id=value.get("package_id"),
            granule_id=value.get("granule_id"),
            text_excerpt=value.get("text_excerpt"),
            publication_date=value.get("publication_date"),
            effective_start=value.get("effective_start"),
            effective_end=value.get("effective_end"),
            retrieved_at=value.get("retrieved_at"),
            is_binding=bool(value.get("is_binding", False)),
            is_proposed=bool(value.get("is_proposed", False)),
            is_withdrawn=bool(value.get("is_withdrawn", False)),
            is_mandatory=bool(value.get("is_mandatory", False)),
            verification_state=value.get(
                "verification_state", VerificationState.UNVERIFIED
            ),
            official_artifact=value.get("official_artifact"),
            derived_presentation=value.get("derived_presentation"),
            content_sha256=value.get("content_sha256"),
            media_type=value.get("media_type"),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
            freshness_max_age_days=value.get("freshness_max_age_days"),
        )

    def to_authority_text_node(self) -> AuthorityTextNode:
        """Project into a registry node for as-of graph resolution."""

        return AuthorityTextNode(
            node_id=self.record_id,
            citation_key=self.citation_key,
            authority_tier=self.authority_tier,
            collection=self.collection,
            jurisdiction=self.jurisdiction,
            title=self.title,
            citation=self.citation,
            edition=self.edition,
            version=self.version,
            release_point=self.release_point,
            text_excerpt=self.text_excerpt,
            publication_date=self.publication_date,
            effective_start=self.effective_start,
            effective_end=self.effective_end,
            is_binding=self.is_binding,
            is_proposed=self.is_proposed,
            is_withdrawn=self.is_withdrawn,
            official_artifact=self.official_artifact,
            derived_presentation=self.derived_presentation,
            source_key=self.source_key,
            verification_state=self.verification_state,
            notes=self.notes,
            metadata={
                **dict(self.metadata),
                "authority_kind": self.authority_kind.value,
                "rendition_legal_status": self.rendition_legal_status.value,
                "acceptance_class": self.acceptance_class,
            },
        )


@dataclass(frozen=True, slots=True)
class MaterializationEdge:
    """Cross-link between versioned authority records."""

    edge_id: str
    relation: TemporalRelation
    source_record_id: str
    target_record_id: str
    effective_date: Optional[date] = None
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "edge_id", _require_non_empty_str(self.edge_id, "edge_id")
        )
        object.__setattr__(
            self,
            "source_record_id",
            _require_non_empty_str(self.source_record_id, "source_record_id"),
        )
        object.__setattr__(
            self,
            "target_record_id",
            _require_non_empty_str(self.target_record_id, "target_record_id"),
        )
        object.__setattr__(self, "relation", TemporalRelation.coerce(self.relation))
        object.__setattr__(
            self,
            "effective_date",
            _parse_optional_date(self.effective_date, name="effective_date"),
        )
        if self.reason is not None:
            object.__setattr__(
                self, "reason", _require_non_empty_str(self.reason, "reason")
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "effective_date": _date_to_str(self.effective_date),
            "reason": self.reason,
            "relation": self.relation.value,
            "source_record_id": self.source_record_id,
            "target_record_id": self.target_record_id,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "MaterializationEdge":
        if not isinstance(value, Mapping):
            raise RecipeSchemaError("edge must be a mapping")
        return cls(
            edge_id=str(value.get("edge_id") or value.get("id") or ""),
            relation=value.get("relation") or value.get("type") or "related",
            source_record_id=str(
                value.get("source_record_id")
                or value.get("source_node_id")
                or value.get("source")
                or ""
            ),
            target_record_id=str(
                value.get("target_record_id")
                or value.get("target_node_id")
                or value.get("target")
                or ""
            ),
            effective_date=value.get("effective_date"),
            reason=value.get("reason"),
        )

    def to_temporal_edge(self) -> AuthorityTemporalEdge:
        return AuthorityTemporalEdge(
            edge_id=self.edge_id,
            relation=self.relation,
            source_node_id=self.source_record_id,
            target_node_id=self.target_record_id,
            effective_date=self.effective_date,
            reason=self.reason,
        )


# ---------------------------------------------------------------------------
# Freshness and readiness
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceFreshnessEntry:
    """Freshness status for one source inside a materialized snapshot."""

    source_key: str
    record_id: Optional[str]
    status: SourceFreshnessStatus
    is_mandatory: bool
    retrieved_at: Optional[datetime] = None
    max_age_days: Optional[int] = None
    age_days: Optional[int] = None
    content_sha256: Optional[str] = None
    notes: Optional[str] = None
    competing_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_key", _require_non_empty_str(self.source_key, "source_key")
        )
        object.__setattr__(self, "status", SourceFreshnessStatus.coerce(self.status))
        if self.retrieved_at is not None:
            object.__setattr__(
                self,
                "retrieved_at",
                _parse_utc_datetime(self.retrieved_at, name="retrieved_at"),
            )
        if self.content_sha256 is not None:
            object.__setattr__(
                self,
                "content_sha256",
                _require_sha256(self.content_sha256, "content_sha256"),
            )
        object.__setattr__(
            self,
            "competing_record_ids",
            tuple(str(x) for x in self.competing_record_ids),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "age_days": self.age_days,
            "competing_record_ids": list(self.competing_record_ids),
            "content_sha256": self.content_sha256,
            "is_mandatory": bool(self.is_mandatory),
            "max_age_days": self.max_age_days,
            "notes": self.notes,
            "record_id": self.record_id,
            "retrieved_at": (
                None if self.retrieved_at is None else _format_utc(self.retrieved_at)
            ),
            "source_key": self.source_key,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "SourceFreshnessEntry":
        if not isinstance(value, Mapping):
            raise PatentAuthorityMaterializerError(
                "freshness entry must be a mapping"
            )
        return cls(
            source_key=str(value.get("source_key") or ""),
            record_id=value.get("record_id"),
            status=value.get("status") or SourceFreshnessStatus.UNKNOWN,
            is_mandatory=bool(value.get("is_mandatory", False)),
            retrieved_at=value.get("retrieved_at"),
            max_age_days=value.get("max_age_days"),
            age_days=value.get("age_days"),
            content_sha256=value.get("content_sha256"),
            notes=value.get("notes"),
            competing_record_ids=tuple(value.get("competing_record_ids") or ()),
        )


@dataclass(frozen=True, slots=True)
class FreshnessManifest:
    """Per-source freshness inventory for one snapshot."""

    as_of: date
    schedule_id: str
    entries: tuple[SourceFreshnessEntry, ...]
    evaluated_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", _require_date(self.as_of, name="as_of"))
        object.__setattr__(
            self,
            "schedule_id",
            _require_non_empty_str(self.schedule_id, "schedule_id"),
        )
        object.__setattr__(self, "entries", tuple(self.entries))
        if self.evaluated_at is not None:
            object.__setattr__(
                self,
                "evaluated_at",
                _parse_utc_datetime(self.evaluated_at, name="evaluated_at"),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": _date_to_str(self.as_of),
            "entries": [e.to_dict() for e in sorted(self.entries, key=lambda x: x.source_key)],
            "evaluated_at": (
                None if self.evaluated_at is None else _format_utc(self.evaluated_at)
            ),
            "schedule_id": self.schedule_id,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "FreshnessManifest":
        if not isinstance(value, Mapping):
            raise PatentAuthorityMaterializerError(
                "freshness manifest must be a mapping"
            )
        raw_entries = value.get("entries") or ()
        if not isinstance(raw_entries, (list, tuple)):
            raise PatentAuthorityMaterializerError("entries must be a sequence")
        return cls(
            as_of=value["as_of"],
            schedule_id=str(value.get("schedule_id") or ""),
            entries=tuple(SourceFreshnessEntry.from_dict(e) for e in raw_entries),
            evaluated_at=value.get("evaluated_at"),
        )

    @property
    def mandatory_blocks(self) -> tuple[SourceFreshnessEntry, ...]:
        blocked = {
            SourceFreshnessStatus.STALE,
            SourceFreshnessStatus.MISSING,
            SourceFreshnessStatus.CONFLICT,
        }
        return tuple(
            e
            for e in self.entries
            if e.is_mandatory and e.status in blocked
        )


@dataclass(frozen=True, slots=True)
class AuthoritativeReadiness:
    """Whether a snapshot may be treated as authoritative-ready.

    Stale, missing, or conflicting mandatory sources and an adjudicatory
    research gap always block readiness.
    """

    ready: bool
    block_reasons: tuple[AuthoritativeBlockReason, ...]
    details: tuple[str, ...] = ()
    adjudicatory_is_blocking_research_gap: bool = False

    def __post_init__(self) -> None:
        reasons = tuple(
            r
            if isinstance(r, AuthoritativeBlockReason)
            else AuthoritativeBlockReason(str(r))
            for r in self.block_reasons
        )
        object.__setattr__(self, "block_reasons", reasons)
        object.__setattr__(self, "details", tuple(str(d) for d in self.details))
        object.__setattr__(self, "ready", bool(self.ready) and not reasons)
        if reasons:
            object.__setattr__(self, "ready", False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adjudicatory_is_blocking_research_gap": bool(
                self.adjudicatory_is_blocking_research_gap
            ),
            "block_reasons": [r.value for r in self.block_reasons],
            "details": list(self.details),
            "ready": bool(self.ready),
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "AuthoritativeReadiness":
        if not isinstance(value, Mapping):
            raise PatentAuthorityMaterializerError("readiness must be a mapping")
        raw_reasons = value.get("block_reasons") or ()
        return cls(
            ready=bool(value.get("ready", False)),
            block_reasons=tuple(
                AuthoritativeBlockReason(str(r)) for r in raw_reasons
            ),
            details=tuple(value.get("details") or ()),
            adjudicatory_is_blocking_research_gap=bool(
                value.get("adjudicatory_is_blocking_research_gap", False)
            ),
        )


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TemporalAuthoritySnapshot:
    """Immutable content-addressed temporal authority snapshot.

    Serialization is deterministic. Content identity is derived from the
    canonical payload excluding only wall-clock fields that are fixed at
    materialization time and stored inside the payload itself.
    """

    snapshot_id: str
    schedule_id: str
    as_of: date
    records: tuple[MaterializedAuthorityRecord, ...]
    edges: tuple[MaterializationEdge, ...]
    adjudicatory_coverage: AdjudicatoryCoverage
    freshness: FreshnessManifest
    readiness: AuthoritativeReadiness
    schedule_kind: ScheduleKind = ScheduleKind.INCREMENTAL
    materialized_at: Optional[datetime] = None
    parent_snapshot_sha256: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "snapshot_id", _require_non_empty_str(self.snapshot_id, "snapshot_id")
        )
        object.__setattr__(
            self,
            "schedule_id",
            _require_non_empty_str(self.schedule_id, "schedule_id"),
        )
        object.__setattr__(self, "as_of", _require_date(self.as_of, name="as_of"))
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "edges", tuple(self.edges))
        object.__setattr__(
            self, "schedule_kind", ScheduleKind.coerce(self.schedule_kind)
        )
        if self.materialized_at is not None:
            object.__setattr__(
                self,
                "materialized_at",
                _parse_utc_datetime(self.materialized_at, name="materialized_at"),
            )
        if self.parent_snapshot_sha256 is not None:
            object.__setattr__(
                self,
                "parent_snapshot_sha256",
                _require_sha256(
                    self.parent_snapshot_sha256, "parent_snapshot_sha256"
                ),
            )
        if not isinstance(self.metadata, Mapping):
            raise PatentAuthorityMaterializerError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )

        # Stable ordering for deterministic serialization.
        records = tuple(sorted(self.records, key=lambda r: r.record_id))
        edges = tuple(sorted(self.edges, key=lambda e: e.edge_id))
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "edges", edges)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adjudicatory_coverage": self.adjudicatory_coverage.to_dict(),
            "as_of": _date_to_str(self.as_of),
            "edges": [e.to_dict() for e in self.edges],
            "freshness": self.freshness.to_dict(),
            "materialized_at": (
                None
                if self.materialized_at is None
                else _format_utc(self.materialized_at)
            ),
            "metadata": _deep_sorted(self.metadata),
            "parent_snapshot_sha256": self.parent_snapshot_sha256,
            "readiness": self.readiness.to_dict(),
            "records": [r.to_dict() for r in self.records],
            "schedule_id": self.schedule_id,
            "schedule_kind": self.schedule_kind.value,
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
        }

    def to_canonical_json(self) -> str:
        return canonical_json_dumps(self.to_dict())

    def to_canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def content_address(self) -> ContentAddress:
        return content_address_mapping(self.to_dict())

    @property
    def content_sha256(self) -> str:
        return self.content_address().sha256

    @property
    def content_cid(self) -> str:
        return self.content_address().cid

    def record_by_id(self) -> Mapping[str, MaterializedAuthorityRecord]:
        return MappingProxyType({r.record_id: r for r in self.records})

    def records_for_citation(self, citation_key: str) -> tuple[MaterializedAuthorityRecord, ...]:
        key = citation_key.strip().lower()
        return tuple(
            r for r in self.records if r.citation_key.strip().lower() == key
        )

    def as_of_records(self, as_of: date | str) -> tuple[MaterializedAuthorityRecord, ...]:
        """Return records covering *as_of* without later-law leakage."""

        query_date = _require_date(as_of, name="as_of")
        return tuple(
            r
            for r in self.records
            if r.covers(query_date) and not r.is_future_as_of(query_date)
        )

    def to_temporal_graph(self) -> PatentTemporalAuthorityGraph:
        builder = PatentTemporalAuthorityGraphBuilder(
            graph_id=f"snapshot:{self.snapshot_id}",
            metadata={
                "schedule_id": self.schedule_id,
                "as_of": _date_to_str(self.as_of),
                "snapshot_sha256": self.content_sha256,
            },
        )
        for record in self.records:
            builder.add_node(record.to_authority_text_node(), overwrite=True)
        for edge in self.edges:
            builder.add_edge(edge.to_temporal_edge(), overwrite=True, require_nodes=True)
        return builder.build()

    def resolve_as_of(
        self,
        as_of: date | str,
        *,
        citation_key: str | None = None,
        view_role: AsOfViewRole | str = AsOfViewRole.AS_OF,
        view_kind: AuthorityViewKind | str = AuthorityViewKind.OFFICIAL,
        include_proposed: bool = False,
        include_future: bool = False,
        include_withdrawn: bool = False,
    ):
        """Resolve governing authority as of a date; later law never leaks."""

        query_date = _require_date(as_of, name="as_of")
        graph = self.to_temporal_graph()
        query = AsOfQuery(
            as_of=query_date,
            citation_key=citation_key,
            view_role=view_role,
            view_kind=view_kind,
            include_proposed=include_proposed,
            include_future=include_future,
            include_withdrawn=include_withdrawn,
        )
        return resolve_as_of(graph, query)

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "TemporalAuthoritySnapshot":
        if not isinstance(value, Mapping):
            raise PatentAuthorityMaterializerError("snapshot must be a mapping")
        raw_records = value.get("records") or ()
        raw_edges = value.get("edges") or ()
        if not isinstance(raw_records, (list, tuple)):
            raise PatentAuthorityMaterializerError("records must be a sequence")
        if not isinstance(raw_edges, (list, tuple)):
            raise PatentAuthorityMaterializerError("edges must be a sequence")
        freshness_raw = value.get("freshness")
        readiness_raw = value.get("readiness")
        return cls(
            snapshot_id=str(value.get("snapshot_id") or ""),
            schedule_id=str(value.get("schedule_id") or ""),
            as_of=value["as_of"],
            records=tuple(
                MaterializedAuthorityRecord.from_dict(r) for r in raw_records
            ),
            edges=tuple(MaterializationEdge.from_dict(e) for e in raw_edges),
            adjudicatory_coverage=AdjudicatoryCoverage.from_dict(
                value.get("adjudicatory_coverage")
            ),
            freshness=(
                FreshnessManifest.from_dict(freshness_raw)
                if isinstance(freshness_raw, Mapping)
                else FreshnessManifest(
                    as_of=value["as_of"],
                    schedule_id=str(value.get("schedule_id") or ""),
                    entries=(),
                )
            ),
            readiness=(
                AuthoritativeReadiness.from_dict(readiness_raw)
                if isinstance(readiness_raw, Mapping)
                else AuthoritativeReadiness(ready=False, block_reasons=())
            ),
            schedule_kind=value.get("schedule_kind") or ScheduleKind.INCREMENTAL,
            materialized_at=value.get("materialized_at"),
            parent_snapshot_sha256=value.get("parent_snapshot_sha256"),
            metadata=value.get("metadata") or {},
            schema_version=str(
                value.get("schema_version") or SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_canonical_json(cls, text: str | bytes) -> "TemporalAuthoritySnapshot":
        if isinstance(text, bytes):
            text = text.decode("utf-8")
        payload = json.loads(text)
        if not isinstance(payload, Mapping):
            raise PatentAuthorityMaterializerError(
                "canonical JSON must decode to a mapping"
            )
        return cls.from_dict(payload)


# ---------------------------------------------------------------------------
# Immutable snapshot store
# ---------------------------------------------------------------------------


class ImmutableSnapshotStore:
    """Content-addressed snapshot store that never mutates prior payloads.

    Snapshots are stored under ``{root}/{sha256}/snapshot.json``. Writing an
    identical payload is idempotent; writing a different payload under the same
    content address raises :class:`SnapshotImmutabilityError`. Changed inputs
    produce a new content address and leave existing snapshots intact.
    """

    def __init__(self, root: PathLike) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, sha256: str) -> Path:
        digest = _require_sha256(sha256, "sha256")
        return self.root / digest

    def snapshot_path(self, sha256: str) -> Path:
        return self.path_for(sha256) / SNAPSHOT_MANIFEST_NAME

    def contains(self, sha256: str) -> bool:
        return self.snapshot_path(sha256).is_file()

    def list_sha256(self) -> tuple[str, ...]:
        if not self.root.is_dir():
            return ()
        digests: list[str] = []
        for child in sorted(self.root.iterdir()):
            if child.is_dir() and _SHA256_RE.fullmatch(child.name):
                if (child / SNAPSHOT_MANIFEST_NAME).is_file():
                    digests.append(child.name)
        return tuple(digests)

    def put(self, snapshot: TemporalAuthoritySnapshot) -> ContentAddress:
        """Persist *snapshot* immutably; return its content address."""

        address = snapshot.content_address()
        dest_dir = self.path_for(address.sha256)
        dest_file = dest_dir / SNAPSHOT_MANIFEST_NAME
        payload = snapshot.to_canonical_bytes()

        if dest_file.is_file():
            existing = dest_file.read_bytes()
            if existing != payload:
                raise SnapshotImmutabilityError(
                    f"refusing to mutate snapshot {address.sha256}: "
                    "existing bytes differ from new payload"
                )
            # Idempotent rewrite of identical bytes is a no-op.
            return address

        dest_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_bytes(dest_file, payload)

        freshness_path = dest_dir / FRESHNESS_MANIFEST_NAME
        _atomic_write_bytes(
            freshness_path,
            canonical_json_bytes(snapshot.freshness.to_dict()),
        )

        # Update content-address index without rewriting prior entries.
        self._index_append(address, snapshot)
        return address

    def get(self, sha256: str) -> TemporalAuthoritySnapshot:
        path = self.snapshot_path(sha256)
        if not path.is_file():
            raise SnapshotNotFoundError(f"snapshot not found: {sha256}")
        return TemporalAuthoritySnapshot.from_canonical_json(path.read_bytes())

    def get_bytes(self, sha256: str) -> bytes:
        path = self.snapshot_path(sha256)
        if not path.is_file():
            raise SnapshotNotFoundError(f"snapshot not found: {sha256}")
        return path.read_bytes()

    def _index_append(
        self, address: ContentAddress, snapshot: TemporalAuthoritySnapshot
    ) -> None:
        index_path = self.root / INDEX_NAME
        if index_path.is_file():
            try:
                index = json.loads(index_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                index = {"schema_version": SCHEMA_VERSION, "entries": []}
        else:
            index = {"schema_version": SCHEMA_VERSION, "entries": []}
        if not isinstance(index, dict):
            index = {"schema_version": SCHEMA_VERSION, "entries": []}
        entries = list(index.get("entries") or [])
        # Never rewrite an existing content-address entry's payload fields.
        by_sha = {
            e.get("sha256"): e
            for e in entries
            if isinstance(e, Mapping) and e.get("sha256")
        }
        if address.sha256 not in by_sha:
            entries.append(
                {
                    "as_of": _date_to_str(snapshot.as_of),
                    "cid": address.cid,
                    "ready": bool(snapshot.readiness.ready),
                    "schedule_id": snapshot.schedule_id,
                    "sha256": address.sha256,
                    "snapshot_id": snapshot.snapshot_id,
                }
            )
            entries.sort(key=lambda e: (e.get("sha256") or "", e.get("snapshot_id") or ""))
            index = {
                "entries": entries,
                "schema_version": SCHEMA_VERSION,
            }
            _atomic_write_bytes(index_path, canonical_json_bytes(index))


# ---------------------------------------------------------------------------
# Materializer
# ---------------------------------------------------------------------------


def assess_source_freshness(
    records: Sequence[MaterializedAuthorityRecord],
    *,
    as_of: date,
    schedule_id: str,
    required_source_keys: Sequence[str] | None = None,
    evaluated_at: datetime | None = None,
) -> FreshnessManifest:
    """Build a freshness manifest for *records* relative to *as_of*."""

    eval_at = evaluated_at or datetime(
        as_of.year, as_of.month, as_of.day, tzinfo=timezone.utc
    )
    if eval_at.tzinfo is None:
        eval_at = eval_at.replace(tzinfo=timezone.utc)

    by_source: dict[str, list[MaterializedAuthorityRecord]] = {}
    for record in records:
        by_source.setdefault(record.source_key, []).append(record)

    required = set(required_source_keys or ())
    for record in records:
        if record.is_mandatory:
            required.add(record.source_key)

    entries: list[SourceFreshnessEntry] = []
    seen_sources: set[str] = set()

    for source_key in sorted(by_source.keys()):
        group = by_source[source_key]
        seen_sources.add(source_key)
        is_mandatory = any(r.is_mandatory for r in group) or source_key in required

        # Conflict: multiple distinct content digests covering the same as_of.
        covering = [r for r in group if r.covers(as_of)]
        digests = {
            r.content_sha256
            for r in covering
            if r.content_sha256 and r.verification_state is not VerificationState.CONFLICT
        }
        conflict_flagged = any(
            r.verification_state is VerificationState.CONFLICT for r in covering
        )
        if conflict_flagged or (len(digests) > 1 and is_mandatory):
            competing = tuple(sorted(r.record_id for r in covering))
            entries.append(
                SourceFreshnessEntry(
                    source_key=source_key,
                    record_id=covering[0].record_id if covering else group[0].record_id,
                    status=SourceFreshnessStatus.CONFLICT,
                    is_mandatory=is_mandatory,
                    retrieved_at=covering[0].retrieved_at if covering else group[0].retrieved_at,
                    max_age_days=covering[0].freshness_max_age_days
                    if covering
                    else group[0].freshness_max_age_days,
                    content_sha256=(
                        covering[0].content_sha256 if covering else group[0].content_sha256
                    ),
                    notes="conflicting content digests or verification_state=conflict",
                    competing_record_ids=competing,
                )
            )
            continue

        chosen = covering[0] if covering else group[0]
        max_age = chosen.freshness_max_age_days
        age_days: Optional[int] = None
        status = SourceFreshnessStatus.FRESH
        notes: Optional[str] = None

        if chosen.retrieved_at is None and is_mandatory and max_age is not None:
            status = SourceFreshnessStatus.STALE
            notes = "mandatory source missing retrieved_at with freshness window"
        elif chosen.retrieved_at is not None and max_age is not None:
            delta = eval_at - chosen.retrieved_at
            age_days = max(0, int(delta.total_seconds() // 86400))
            if age_days > max_age:
                status = SourceFreshnessStatus.STALE
                notes = f"age_days={age_days} exceeds max_age_days={max_age}"

        if not covering and is_mandatory:
            status = SourceFreshnessStatus.MISSING
            notes = notes or f"no covering record as of {as_of.isoformat()}"

        entries.append(
            SourceFreshnessEntry(
                source_key=source_key,
                record_id=chosen.record_id,
                status=status,
                is_mandatory=is_mandatory,
                retrieved_at=chosen.retrieved_at,
                max_age_days=max_age,
                age_days=age_days,
                content_sha256=chosen.content_sha256,
                notes=notes,
            )
        )

    for source_key in sorted(required - seen_sources):
        entries.append(
            SourceFreshnessEntry(
                source_key=source_key,
                record_id=None,
                status=SourceFreshnessStatus.MISSING,
                is_mandatory=True,
                notes="required mandatory source absent from materialization inputs",
            )
        )

    return FreshnessManifest(
        as_of=as_of,
        schedule_id=schedule_id,
        entries=tuple(entries),
        evaluated_at=eval_at,
    )


def assess_authoritative_readiness(
    *,
    records: Sequence[MaterializedAuthorityRecord],
    freshness: FreshnessManifest,
    adjudicatory: AdjudicatoryCoverage,
) -> AuthoritativeReadiness:
    """Decide whether a snapshot is authoritative-ready (fail-closed)."""

    reasons: list[AuthoritativeBlockReason] = []
    details: list[str] = []

    if not records:
        reasons.append(AuthoritativeBlockReason.EMPTY_SNAPSHOT)
        details.append("snapshot has no authority records")

    for entry in freshness.entries:
        if not entry.is_mandatory:
            continue
        if entry.status is SourceFreshnessStatus.STALE:
            reasons.append(AuthoritativeBlockReason.STALE_MANDATORY_SOURCE)
            details.append(f"stale mandatory source: {entry.source_key}")
        elif entry.status is SourceFreshnessStatus.MISSING:
            reasons.append(AuthoritativeBlockReason.MISSING_MANDATORY_SOURCE)
            details.append(f"missing mandatory source: {entry.source_key}")
        elif entry.status is SourceFreshnessStatus.CONFLICT:
            reasons.append(AuthoritativeBlockReason.CONFLICTING_MANDATORY_SOURCE)
            details.append(f"conflicting mandatory source: {entry.source_key}")

    for record in records:
        if record.verification_state is VerificationState.CONFLICT and record.is_mandatory:
            if AuthoritativeBlockReason.VERIFICATION_CONFLICT not in reasons:
                reasons.append(AuthoritativeBlockReason.VERIFICATION_CONFLICT)
            details.append(f"verification conflict on {record.record_id}")
        for field_name in ("edition", "version", "release_point", "package_id"):
            val = getattr(record, field_name)
            if isinstance(val, str) and _LATEST_TOKEN_RE.fullmatch(val):
                reasons.append(AuthoritativeBlockReason.HARD_CODED_LATEST)
                details.append(f"{record.record_id}.{field_name}=latest")

    adjudicatory_gap = bool(adjudicatory.is_blocking_research_gap)
    if adjudicatory_gap:
        reasons.append(AuthoritativeBlockReason.ADJUDICATORY_RESEARCH_GAP)
        details.append(
            "adjudicatory coverage is a blocking research-coverage gap; "
            "cannot support a complete-law conclusion"
        )

    # De-duplicate while preserving order.
    seen: set[AuthoritativeBlockReason] = set()
    ordered: list[AuthoritativeBlockReason] = []
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            ordered.append(reason)

    return AuthoritativeReadiness(
        ready=not ordered,
        block_reasons=tuple(ordered),
        details=tuple(details),
        adjudicatory_is_blocking_research_gap=adjudicatory_gap,
    )


def filter_records_as_of(
    records: Sequence[MaterializedAuthorityRecord],
    as_of: date | str,
    *,
    include_proposed: bool = False,
    include_future: bool = False,
    include_withdrawn: bool = False,
) -> tuple[MaterializedAuthorityRecord, ...]:
    """Filter records for an as-of view without later-law leakage."""

    query_date = _require_date(as_of, name="as_of")
    out: list[MaterializedAuthorityRecord] = []
    for record in records:
        if record.is_future_as_of(query_date) and not include_future:
            continue
        if not record.covers(query_date):
            continue
        if record.is_proposed and not include_proposed:
            continue
        if record.is_withdrawn and not include_withdrawn:
            continue
        out.append(record)
    return tuple(sorted(out, key=lambda r: r.record_id))


class PatentAuthorityMaterializer:
    """Materialize scheduled temporal patent-authority snapshots.

    Primary entry points:

    * :meth:`materialize` — build an immutable snapshot from records/edges
    * :meth:`materialize_from_recipe` — replay a compact fixture recipe
    * :meth:`put_snapshot` — persist without mutating prior snapshots
    * :meth:`query_as_of` — as-of view that never leaks later law
    """

    def __init__(
        self,
        *,
        store: ImmutableSnapshotStore | PathLike | None = None,
        default_schedule_id: str = "default-schedule",
    ) -> None:
        self.default_schedule_id = _require_non_empty_str(
            default_schedule_id, "default_schedule_id"
        )
        if store is None:
            self.store: Optional[ImmutableSnapshotStore] = None
        elif isinstance(store, ImmutableSnapshotStore):
            self.store = store
        else:
            self.store = ImmutableSnapshotStore(store)

    def materialize(
        self,
        records: Sequence[MaterializedAuthorityRecord | Mapping[str, Any]],
        *,
        as_of: date | str,
        schedule_id: str | None = None,
        edges: Sequence[MaterializationEdge | Mapping[str, Any]] | None = None,
        adjudicatory_coverage: AdjudicatoryCoverage | Mapping[str, Any] | None = None,
        schedule_kind: ScheduleKind | str = ScheduleKind.INCREMENTAL,
        snapshot_id: str | None = None,
        parent_snapshot_sha256: str | None = None,
        required_source_keys: Sequence[str] | None = None,
        materialized_at: datetime | str | None = None,
        metadata: Mapping[str, Any] | None = None,
        persist: bool = False,
    ) -> TemporalAuthoritySnapshot:
        """Normalize inputs, build freshness/readiness, and return a snapshot."""

        as_of_date = _require_date(as_of, name="as_of")
        sched = _require_non_empty_str(
            schedule_id or self.default_schedule_id, "schedule_id"
        )
        normalized_records = tuple(
            r
            if isinstance(r, MaterializedAuthorityRecord)
            else MaterializedAuthorityRecord.from_dict(r)
            for r in records
        )
        normalized_edges = tuple(
            e
            if isinstance(e, MaterializationEdge)
            else MaterializationEdge.from_dict(e)
            for e in (edges or ())
        )
        if adjudicatory_coverage is None:
            adjudicatory = AdjudicatoryCoverage.research_gap()
        elif isinstance(adjudicatory_coverage, AdjudicatoryCoverage):
            adjudicatory = adjudicatory_coverage
        else:
            adjudicatory = AdjudicatoryCoverage.from_dict(adjudicatory_coverage)

        mat_at: Optional[datetime]
        if materialized_at is None:
            # Deterministic materialization clock anchored to as_of (no wall clock).
            mat_at = datetime(
                as_of_date.year,
                as_of_date.month,
                as_of_date.day,
                12,
                0,
                0,
                tzinfo=timezone.utc,
            )
        else:
            mat_at = _parse_utc_datetime(materialized_at, name="materialized_at")

        freshness = assess_source_freshness(
            normalized_records,
            as_of=as_of_date,
            schedule_id=sched,
            required_source_keys=required_source_keys,
            evaluated_at=mat_at,
        )
        readiness = assess_authoritative_readiness(
            records=normalized_records,
            freshness=freshness,
            adjudicatory=adjudicatory,
        )

        sid = snapshot_id or self._derive_snapshot_id(
            schedule_id=sched,
            as_of=as_of_date,
            records=normalized_records,
            edges=normalized_edges,
        )

        snapshot = TemporalAuthoritySnapshot(
            snapshot_id=sid,
            schedule_id=sched,
            as_of=as_of_date,
            records=normalized_records,
            edges=normalized_edges,
            adjudicatory_coverage=adjudicatory,
            freshness=freshness,
            readiness=readiness,
            schedule_kind=schedule_kind,
            materialized_at=mat_at,
            parent_snapshot_sha256=parent_snapshot_sha256,
            metadata=dict(metadata or {}),
        )

        if persist:
            self.put_snapshot(snapshot)
        return snapshot

    def materialize_from_recipe(
        self,
        recipe: Mapping[str, Any] | PathLike,
        *,
        schedule_id: str | None = None,
        as_of: date | str | None = None,
        persist: bool = False,
        store: ImmutableSnapshotStore | PathLike | None = None,
    ) -> TemporalAuthoritySnapshot:
        """Materialize from a compact temporal materialization recipe."""

        payload = self.load_recipe(recipe)
        schedules = payload.get("schedules") or []
        if not isinstance(schedules, list) or not schedules:
            raise RecipeSchemaError("recipe must declare at least one schedule")

        chosen: Mapping[str, Any] | None = None
        if schedule_id is not None:
            for sched in schedules:
                if isinstance(sched, Mapping) and sched.get("schedule_id") == schedule_id:
                    chosen = sched
                    break
            if chosen is None:
                raise RecipeSchemaError(f"schedule not found: {schedule_id!r}")
        else:
            first = schedules[0]
            if not isinstance(first, Mapping):
                raise RecipeSchemaError("schedule entries must be mappings")
            chosen = first

        assert chosen is not None
        as_of_value = as_of or chosen.get("as_of") or payload.get("default_as_of")
        if as_of_value is None:
            raise RecipeSchemaError("as_of is required on schedule or recipe")

        sources = chosen.get("sources") or payload.get("sources") or []
        if not isinstance(sources, (list, tuple)):
            raise RecipeSchemaError("sources must be a sequence")
        edges = chosen.get("edges") or payload.get("edges") or []
        if not isinstance(edges, (list, tuple)):
            raise RecipeSchemaError("edges must be a sequence")

        adjudicatory_raw = (
            chosen.get("adjudicatory_coverage")
            or payload.get("adjudicatory_coverage")
        )
        required = chosen.get("required_source_keys") or payload.get(
            "required_source_keys"
        )
        meta = {
            "recipe_schema_version": payload.get("schema_version"),
            "recipe_id": payload.get("recipe_id"),
            **dict(chosen.get("metadata") or {}),
        }
        parent = chosen.get("parent_snapshot_sha256") or payload.get(
            "parent_snapshot_sha256"
        )
        materialized_at = chosen.get("materialized_at") or payload.get(
            "materialized_at"
        )

        # Optional store override for this call.
        previous_store = self.store
        if store is not None:
            self.store = (
                store
                if isinstance(store, ImmutableSnapshotStore)
                else ImmutableSnapshotStore(store)
            )
        try:
            return self.materialize(
                sources,
                as_of=as_of_value,
                schedule_id=str(chosen.get("schedule_id") or self.default_schedule_id),
                edges=edges,
                adjudicatory_coverage=adjudicatory_raw,
                schedule_kind=chosen.get("schedule_kind")
                or payload.get("schedule_kind")
                or ScheduleKind.REPLAY,
                snapshot_id=chosen.get("snapshot_id"),
                parent_snapshot_sha256=parent,
                required_source_keys=required,
                materialized_at=materialized_at,
                metadata=meta,
                persist=persist,
            )
        finally:
            self.store = previous_store

    def put_snapshot(
        self, snapshot: TemporalAuthoritySnapshot
    ) -> ContentAddress:
        if self.store is None:
            raise PatentAuthorityMaterializerError(
                "no snapshot store configured; pass store= to the materializer"
            )
        return self.store.put(snapshot)

    def get_snapshot(self, sha256: str) -> TemporalAuthoritySnapshot:
        if self.store is None:
            raise PatentAuthorityMaterializerError("no snapshot store configured")
        return self.store.get(sha256)

    def query_as_of(
        self,
        snapshot: TemporalAuthoritySnapshot,
        as_of: date | str,
        *,
        citation_key: str | None = None,
        include_proposed: bool = False,
        include_future: bool = False,
        include_withdrawn: bool = False,
        use_graph_resolver: bool = True,
    ) -> dict[str, Any]:
        """Return a deterministic as-of view that never includes later law."""

        query_date = _require_date(as_of, name="as_of")
        filtered = filter_records_as_of(
            snapshot.records,
            query_date,
            include_proposed=include_proposed,
            include_future=include_future,
            include_withdrawn=include_withdrawn,
        )
        if citation_key is not None:
            key = citation_key.strip().lower()
            filtered = tuple(
                r for r in filtered if r.citation_key.strip().lower() == key
            )

        # Explicit non-leakage check: no record may start after the query date.
        for record in filtered:
            if record.is_future_as_of(query_date):
                raise PatentAuthorityMaterializerError(
                    f"as-of leak: record {record.record_id} has effective_start "
                    f"{record.effective_start} after as_of {query_date}"
                )

        graph_resolution: Optional[dict[str, Any]] = None
        if use_graph_resolver and citation_key:
            result = snapshot.resolve_as_of(
                query_date,
                citation_key=citation_key,
                include_proposed=include_proposed,
                include_future=include_future,
                include_withdrawn=include_withdrawn,
            )
            graph_resolution = {
                "selected_node_id": result.selected_node_id,
                "status": result.status.value
                if isinstance(result.status, ResolutionStatus)
                else str(result.status),
            }
            # Graph selection must also never pick later law.
            if result.selected_node_id:
                selected = snapshot.record_by_id().get(result.selected_node_id)
                if selected is not None and selected.is_future_as_of(query_date):
                    raise PatentAuthorityMaterializerError(
                        f"as-of leak via graph resolver: {result.selected_node_id}"
                    )

        view = {
            "as_of": query_date.isoformat(),
            "citation_key": citation_key,
            "graph_resolution": graph_resolution,
            "record_ids": [r.record_id for r in filtered],
            "records": [r.to_dict() for r in filtered],
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_sha256": snapshot.content_sha256,
        }
        return _deep_sorted(view)

    def materialize_schedule_delta(
        self,
        prior: TemporalAuthoritySnapshot,
        updated_records: Sequence[MaterializedAuthorityRecord | Mapping[str, Any]],
        *,
        as_of: date | str | None = None,
        schedule_id: str | None = None,
        edges: Sequence[MaterializationEdge | Mapping[str, Any]] | None = None,
        adjudicatory_coverage: AdjudicatoryCoverage | Mapping[str, Any] | None = None,
        persist: bool = False,
        required_source_keys: Sequence[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> TemporalAuthoritySnapshot:
        """Create a new snapshot from prior + updates without mutating *prior*."""

        by_id: dict[str, MaterializedAuthorityRecord] = {
            r.record_id: r for r in prior.records
        }
        for raw in updated_records:
            record = (
                raw
                if isinstance(raw, MaterializedAuthorityRecord)
                else MaterializedAuthorityRecord.from_dict(raw)
            )
            by_id[record.record_id] = record

        merged_edges: dict[str, MaterializationEdge] = {
            e.edge_id: e for e in prior.edges
        }
        for raw in edges or ():
            edge = (
                raw
                if isinstance(raw, MaterializationEdge)
                else MaterializationEdge.from_dict(raw)
            )
            merged_edges[edge.edge_id] = edge

        adj = adjudicatory_coverage
        if adj is None:
            adj = prior.adjudicatory_coverage

        return self.materialize(
            list(by_id.values()),
            as_of=as_of or prior.as_of,
            schedule_id=schedule_id or prior.schedule_id,
            edges=list(merged_edges.values()),
            adjudicatory_coverage=adj,
            schedule_kind=ScheduleKind.INCREMENTAL,
            parent_snapshot_sha256=prior.content_sha256,
            required_source_keys=required_source_keys,
            metadata={
                **dict(prior.metadata),
                **dict(metadata or {}),
                "parent_snapshot_id": prior.snapshot_id,
            },
            persist=persist,
        )

    @staticmethod
    def load_recipe(recipe: Mapping[str, Any] | PathLike) -> dict[str, Any]:
        if isinstance(recipe, Mapping):
            payload = dict(recipe)
        else:
            path = Path(recipe)
            if not path.is_file():
                raise RecipeSchemaError(f"recipe file not found: {path}")
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                raise RecipeSchemaError("recipe root must be a mapping")
            payload = dict(payload)

        schema = str(payload.get("schema_version") or "")
        if schema not in {
            FIXTURE_SCHEMA_VERSION,
            SCHEMA_VERSION,
            "temporal-materialization-recipe-v1",
        }:
            # Accept known recipe schema; reject empty.
            if not schema:
                raise RecipeSchemaError("recipe schema_version is required")
        if "schedules" not in payload and "sources" not in payload:
            raise RecipeSchemaError(
                "recipe must provide schedules[] and/or top-level sources[]"
            )
        return payload

    @staticmethod
    def _derive_snapshot_id(
        *,
        schedule_id: str,
        as_of: date,
        records: Sequence[MaterializedAuthorityRecord],
        edges: Sequence[MaterializationEdge],
    ) -> str:
        seed = {
            "as_of": as_of.isoformat(),
            "edge_ids": sorted(e.edge_id for e in edges),
            "record_ids": sorted(r.record_id for r in records),
            "schedule_id": schedule_id,
        }
        digest = content_address_mapping(seed).sha256[:16]
        return f"{schedule_id}:{as_of.isoformat()}:{digest}"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def default_fixture_dir() -> Path:
    """Locate the live patent-authority fixture directory when present."""

    here = Path(__file__).resolve()
    candidates = [
        here.parents[3]
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
    for candidate in candidates:
        if (candidate / "temporal_materialization_recipe.json").is_file():
            return candidate
    return candidates[0]


def build_default_recipe() -> dict[str, Any]:
    """Compact recipe covering all PATLAW-135 acceptance scenarios.

    Cases:

    * baseline schedule with statute/regulation/guidance/editorial tiers
    * later-law source that must not leak into earlier as-of queries
    * changed-source delta schedule producing a new snapshot identity
    * conflict + missing mandatory source (blocks authoritative-ready)
    * absent adjudicatory coverage as a blocking research gap
    * optional schedule with adjudicatory coverage present
    """

    def _art(
        *,
        provider: str,
        source_id: str,
        label: str,
        url: str,
        role: str = "official_artifact",
    ) -> dict[str, Any]:
        return {
            "artifact_sha256": _stable_label_sha(label),
            "provider": provider,
            "role": role,
            "source_id": source_id,
            "source_url": url,
        }

    baseline_sources = [
        {
            "record_id": "usc-35-101-2023",
            "citation_key": "35-usc-101",
            "authority_kind": "codified_statute",
            "authority_tier": "official-base",
            "rendition_legal_status": "official_source_artifact",
            "collection": "USCODE",
            "source_key": "govinfo-uscode-35-101",
            "citation": "35 U.S.C. § 101",
            "edition": "govinfo-2023-title35",
            "version": "USCODE-2023-title35-101",
            "package_id": "USCODE-2023-title35",
            "text_excerpt": "Whoever invents or discovers any new and useful process… (2023).",
            "effective_start": "2020-01-01",
            "retrieved_at": "2024-06-01T10:00:00Z",
            "is_binding": True,
            "is_mandatory": True,
            "verification_state": "verified",
            "freshness_max_age_days": 365,
            "official_artifact": _art(
                provider="govinfo",
                source_id="USCODE-2023-title35-101",
                label="usc-35-101-2023",
                url="https://www.govinfo.gov/content/pkg/USCODE-2023-title35/xml/101.xml",
            ),
        },
        {
            "record_id": "cfr-1.56-2022",
            "citation_key": "37-cfr-1.56",
            "authority_kind": "promulgated_regulation",
            "authority_tier": "official-change",
            "rendition_legal_status": "official_electronic",
            "collection": "FR",
            "source_key": "govinfo-fr-1.56-2022",
            "citation": "37 C.F.R. § 1.56",
            "edition": "87-FR-12345",
            "version": "2022-final",
            "package_id": "FR-2022-05512",
            "text_excerpt": "Duty of disclosure (2022 amended text).",
            "effective_start": "2022-06-01",
            "retrieved_at": "2024-06-01T10:05:00Z",
            "is_binding": True,
            "is_mandatory": True,
            "verification_state": "verified",
            "freshness_max_age_days": 180,
            "official_artifact": _art(
                provider="govinfo",
                source_id="FR-2022-05512",
                label="cfr-1.56-2022",
                url="https://www.govinfo.gov/content/pkg/FR-2022-05-01/pdf/2022-05512.pdf",
            ),
        },
        {
            "record_id": "cfr-1.56-2024-future",
            "citation_key": "37-cfr-1.56",
            "authority_kind": "promulgated_regulation",
            "authority_tier": "official-change",
            "rendition_legal_status": "official_electronic",
            "collection": "FR",
            "source_key": "govinfo-fr-1.56-2024",
            "citation": "37 C.F.R. § 1.56",
            "edition": "89-FR-20001",
            "version": "2024-final",
            "package_id": "FR-2023-20001",
            "text_excerpt": "Duty of disclosure (2024 future-effective text — must not leak early).",
            "effective_start": "2024-01-01",
            "retrieved_at": "2024-06-01T10:06:00Z",
            "is_binding": True,
            "is_mandatory": False,
            "verification_state": "verified",
            "freshness_max_age_days": 180,
            "official_artifact": _art(
                provider="govinfo",
                source_id="FR-2023-20001",
                label="cfr-1.56-2024-future",
                url="https://www.govinfo.gov/content/pkg/FR-2023-12-01/pdf/2023-20001.pdf",
            ),
        },
        {
            "record_id": "ecfr-1.56-editorial",
            "citation_key": "37-cfr-1.56",
            "authority_kind": "unofficial_editorial_aid",
            "authority_tier": "unofficial-current",
            "rendition_legal_status": "unofficial_editorial_presentation",
            "collection": "eCFR",
            "source_key": "ecfr-37-1.56",
            "citation": "37 C.F.R. § 1.56 (eCFR)",
            "edition": "ecfr-as-of-2023-07-01",
            "version": "ecfr-2023-07-01",
            "text_excerpt": "eCFR editorial presentation of § 1.56.",
            "effective_start": "2022-06-01",
            "retrieved_at": "2024-06-01T10:07:00Z",
            "is_binding": False,
            "is_mandatory": False,
            "verification_state": "unverified",
            "freshness_max_age_days": 30,
            "derived_presentation": _art(
                provider="ecfr",
                source_id="ecfr-37-1.56-2023",
                label="ecfr-1.56-editorial",
                url="https://www.ecfr.gov/current/title-37/section-1.56",
                role="derived_presentation",
            ),
        },
        {
            "record_id": "mpep-2001-guidance",
            "citation_key": "37-cfr-1.56",
            "authority_kind": "official_agency_guidance",
            "authority_tier": "guidance",
            "rendition_legal_status": "official_electronic",
            "collection": "MPEP",
            "source_key": "uspto-mpep-2001",
            "citation": "MPEP § 2001",
            "edition": "9",
            "version": "mpep-9-r01.2024-2001",
            "release_point": "r01.2024",
            "text_excerpt": "MPEP discussion of duty of disclosure (guidance only).",
            "effective_start": "2024-01-01",
            "retrieved_at": "2024-06-01T10:08:00Z",
            "is_binding": False,
            "is_mandatory": False,
            "verification_state": "verified",
            "freshness_max_age_days": 365,
            "official_artifact": _art(
                provider="uspto",
                source_id="mpep-e9r01-2001",
                label="mpep-2001",
                url="https://www.uspto.gov/web/offices/pac/mpep/s2001.html",
            ),
        },
        {
            "record_id": "ptab-precedential-gap-placeholder",
            "citation_key": "ptab-coverage",
            "authority_kind": "extracted_candidate",
            "authority_tier": "candidate",
            "rendition_legal_status": "candidate_only",
            "collection": "PTAB",
            "source_key": "ptab-precedential-batch",
            "citation": "PTAB precedential (not acquired)",
            "edition": "none-acquired",
            "version": "gap-placeholder",
            "text_excerpt": "Placeholder only — adjudicatory batch not acquired.",
            "effective_start": "2020-01-01",
            "retrieved_at": "2024-06-01T10:09:00Z",
            "is_binding": False,
            "is_mandatory": False,
            "verification_state": "unverified",
            "notes": "Does not fill adjudicatory research gap.",
        },
    ]

    baseline_edges = [
        {
            "edge_id": "edge-2024-supersedes-2022",
            "relation": "supersedes",
            "source_record_id": "cfr-1.56-2024-future",
            "target_record_id": "cfr-1.56-2022",
            "effective_date": "2024-01-01",
            "reason": "2024 final rule supersedes 2022 amendment",
        }
    ]

    # Changed source: 2022 regulation content digest updates after re-fetch.
    changed_reg = dict(baseline_sources[1])
    changed_reg = {
        **changed_reg,
        "text_excerpt": "Duty of disclosure (2022 amended text — re-fetched body).",
        "retrieved_at": "2024-09-01T12:00:00Z",
        "official_artifact": _art(
            provider="govinfo",
            source_id="FR-2022-05512",
            label="cfr-1.56-2022-refetch",
            url="https://www.govinfo.gov/content/pkg/FR-2022-05-01/pdf/2022-05512.pdf",
        ),
        "content_sha256": _stable_label_sha("cfr-1.56-2022-refetch"),
    }

    # Conflict schedule: two mandatory statute digests for same citation/as-of.
    conflict_sources = [
        {
            "record_id": "usc-35-102-conflict-a",
            "citation_key": "35-usc-102",
            "authority_kind": "codified_statute",
            "authority_tier": "official-base",
            "rendition_legal_status": "official_source_artifact",
            "collection": "USCODE",
            "source_key": "govinfo-uscode-35-102",
            "citation": "35 U.S.C. § 102",
            "edition": "govinfo-2021-title35",
            "version": "variant-a",
            "package_id": "USCODE-2021-title35",
            "text_excerpt": "Conflict variant A.",
            "effective_start": "2021-01-01",
            "retrieved_at": "2024-06-01T10:00:00Z",
            "is_binding": True,
            "is_mandatory": True,
            "verification_state": "conflict",
            "freshness_max_age_days": 365,
            "official_artifact": _art(
                provider="govinfo",
                source_id="USCODE-2021-title35-102-a",
                label="conflict-a",
                url="https://www.govinfo.gov/content/pkg/USCODE-2021-title35/html/a.html",
            ),
        },
        {
            "record_id": "usc-35-102-conflict-b",
            "citation_key": "35-usc-102",
            "authority_kind": "codified_statute",
            "authority_tier": "official-base",
            "rendition_legal_status": "official_source_artifact",
            "collection": "USCODE",
            "source_key": "govinfo-uscode-35-102",
            "citation": "35 U.S.C. § 102",
            "edition": "govinfo-2021-title35",
            "version": "variant-b",
            "package_id": "USCODE-2021-title35",
            "text_excerpt": "Conflict variant B.",
            "effective_start": "2021-01-01",
            "retrieved_at": "2024-06-01T10:00:00Z",
            "is_binding": True,
            "is_mandatory": True,
            "verification_state": "conflict",
            "freshness_max_age_days": 365,
            "official_artifact": _art(
                provider="govinfo",
                source_id="USCODE-2021-title35-102-b",
                label="conflict-b",
                url="https://www.govinfo.gov/content/pkg/USCODE-2021-title35/html/b.html",
            ),
        },
    ]

    # Stale mandatory: retrieved long before as_of relative to max age.
    stale_sources = [
        {
            "record_id": "cfr-annual-37-stale",
            "citation_key": "37-cfr-title",
            "authority_kind": "promulgated_regulation",
            "authority_tier": "official-base",
            "rendition_legal_status": "official_print_equivalent",
            "collection": "CFR",
            "source_key": "govinfo-cfr-37-annual",
            "citation": "37 C.F.R. (annual)",
            "edition": "CFR-2020-title37",
            "version": "annual-2020",
            "package_id": "CFR-2020-title37",
            "text_excerpt": "Annual Title 37 baseline (stale for 2024 as-of).",
            "effective_start": "2020-07-01",
            "retrieved_at": "2020-08-01T00:00:00Z",
            "is_binding": True,
            "is_mandatory": True,
            "verification_state": "verified",
            "freshness_max_age_days": 90,
            "official_artifact": _art(
                provider="govinfo",
                source_id="CFR-2020-title37",
                label="cfr-annual-stale",
                url="https://www.govinfo.gov/content/pkg/CFR-2020-title37/xml/CFR-2020-title37.xml",
            ),
        }
    ]

    # Present adjudicatory coverage (readiness may still fail other gates).
    ready_sources = [
        dict(baseline_sources[0]),
        dict(baseline_sources[1]),
        {
            "record_id": "cafc-alice-holding",
            "citation_key": "cafc-alice",
            "authority_kind": "binding_adjudicatory_authority",
            "authority_tier": "official-change",
            "rendition_legal_status": "official_electronic",
            "collection": "CAFC",
            "source_key": "cafc-alice-2014",
            "citation": "Alice Corp. v. CLS Bank Int'l, 573 U.S. 208 (2014)",
            "edition": "us-reports-573",
            "version": "alice-2014",
            "text_excerpt": "Two-step framework for patent-eligible subject matter.",
            "effective_start": "2014-06-19",
            "retrieved_at": "2024-06-01T11:00:00Z",
            "is_binding": True,
            "is_mandatory": True,
            "verification_state": "verified",
            "freshness_max_age_days": 730,
            "official_artifact": _art(
                provider="govinfo",
                source_id="USREPORTS-573-208",
                label="alice-2014",
                url="https://www.govinfo.gov/content/pkg/USCOURTS-ca2-13-00298/pdf/alice.pdf",
            ),
        },
    ]

    recipe = {
        "adjudicatory_coverage": {
            "authorities": [],
            "is_blocking_research_gap": True,
            "notes": (
                "Missing adjudicatory coverage is a declared research-coverage "
                "gap and cannot support a complete-law conclusion. PTAB "
                "precedential decisions and Federal Circuit holdings are out "
                "of scope for the baseline batch."
            ),
            "present": False,
            "status": "research_gap",
        },
        "default_as_of": "2023-10-01",
        "expected": {
            "as_of_2023_10_01_excludes_2024_future": {
                "citation_key": "37-cfr-1.56",
                "excluded_record_ids": ["cfr-1.56-2024-future"],
                "must_include_record_ids": ["cfr-1.56-2022"],
            },
            "as_of_2024_02_01_includes_future": {
                "citation_key": "37-cfr-1.56",
                "must_include_record_ids": ["cfr-1.56-2024-future"],
            },
            "baseline_acceptance_classes": [
                "statute",
                "regulation",
                "guidance",
                "editorial_aid",
                "extracted_candidate",
            ],
            "baseline_not_authoritative_ready": True,
            "changed_snapshot_differs": True,
            "conflict_blocks_ready": True,
            "stale_blocks_ready": True,
            "with_adjudicatory_may_be_ready": True,
        },
        "recipe_id": "patlaw-135-temporal-materialization",
        "schedules": [
            {
                "as_of": "2023-10-01",
                "edges": baseline_edges,
                "materialized_at": "2023-10-01T12:00:00Z",
                "notes": "Baseline multi-tier snapshot; adjudicatory gap blocks ready.",
                "required_source_keys": [
                    "govinfo-uscode-35-101",
                    "govinfo-fr-1.56-2022",
                ],
                "schedule_id": "baseline-2023-10-01",
                "schedule_kind": "replay",
                "snapshot_id": "snap-baseline-2023-10-01",
                "sources": baseline_sources,
            },
            {
                "as_of": "2023-10-01",
                "edges": baseline_edges,
                "materialized_at": "2023-10-01T12:00:00Z",
                "notes": "Identical inputs to baseline — must be byte-stable.",
                "required_source_keys": [
                    "govinfo-uscode-35-101",
                    "govinfo-fr-1.56-2022",
                ],
                "schedule_id": "baseline-2023-10-01",
                "schedule_kind": "replay",
                "snapshot_id": "snap-baseline-2023-10-01",
                "sources": baseline_sources,
            },
            {
                "as_of": "2023-10-01",
                "edges": baseline_edges,
                "materialized_at": "2023-10-01T12:00:00Z",
                "notes": "Changed regulation body creates a new snapshot identity.",
                "required_source_keys": [
                    "govinfo-uscode-35-101",
                    "govinfo-fr-1.56-2022",
                ],
                "schedule_id": "baseline-2023-10-01-changed",
                "schedule_kind": "incremental",
                "snapshot_id": "snap-baseline-2023-10-01-changed",
                "sources": [
                    baseline_sources[0],
                    changed_reg,
                    baseline_sources[2],
                    baseline_sources[3],
                    baseline_sources[4],
                    baseline_sources[5],
                ],
            },
            {
                "adjudicatory_coverage": {
                    "authorities": [],
                    "is_blocking_research_gap": True,
                    "notes": (
                        "Conflict schedule retains adjudicatory research gap "
                        "and mandatory source conflict."
                    ),
                    "present": False,
                    "status": "research_gap",
                },
                "as_of": "2023-06-01",
                "edges": [],
                "materialized_at": "2023-06-01T12:00:00Z",
                "notes": "Mandatory conflict blocks authoritative-ready.",
                "schedule_id": "conflict-35-usc-102",
                "schedule_kind": "replay",
                "snapshot_id": "snap-conflict-102",
                "sources": conflict_sources,
            },
            {
                "adjudicatory_coverage": {
                    "authorities": [],
                    "is_blocking_research_gap": True,
                    "notes": "Stale mandatory annual CFR with adjudicatory gap.",
                    "present": False,
                    "status": "research_gap",
                },
                "as_of": "2024-06-01",
                "edges": [],
                "materialized_at": "2024-06-01T12:00:00Z",
                "notes": "Stale mandatory source blocks authoritative-ready.",
                "required_source_keys": ["govinfo-cfr-37-annual", "missing-mandatory"],
                "schedule_id": "stale-and-missing",
                "schedule_kind": "replay",
                "snapshot_id": "snap-stale-missing",
                "sources": stale_sources,
            },
            {
                "adjudicatory_coverage": {
                    "authorities": [
                        "Alice Corp. v. CLS Bank Int'l, 573 U.S. 208 (2014)"
                    ],
                    "is_blocking_research_gap": False,
                    "notes": "Sample adjudicatory authority present for readiness path.",
                    "present": True,
                    "status": "present",
                },
                "as_of": "2024-06-15",
                "edges": [],
                "materialized_at": "2024-06-15T12:00:00Z",
                "notes": (
                    "Adjudicatory present + fresh mandatory sources may be "
                    "authoritative-ready."
                ),
                "schedule_id": "with-adjudicatory-2024-06",
                "schedule_kind": "replay",
                "snapshot_id": "snap-with-adjudicatory",
                "sources": ready_sources,
            },
        ],
        "schema_version": FIXTURE_SCHEMA_VERSION,
    }
    return recipe


def write_default_fixtures(fixture_dir: PathLike | None = None) -> Path:
    """Write the compact temporal materialization recipe to *fixture_dir*."""

    target = Path(fixture_dir) if fixture_dir is not None else default_fixture_dir()
    target.mkdir(parents=True, exist_ok=True)
    path = target / "temporal_materialization_recipe.json"
    payload = build_default_recipe()
    _atomic_write_bytes(path, canonical_json_bytes(payload))
    return path


__all__ = [
    "SCHEMA_VERSION",
    "FIXTURE_SCHEMA_VERSION",
    "AdjudicatoryCoverage",
    "AuthoritativeBlockReason",
    "AuthoritativeReadiness",
    "FreshnessManifest",
    "HardCodedLatestError",
    "ImmutableSnapshotStore",
    "MaterializationEdge",
    "MaterializedAuthorityRecord",
    "PatentAuthorityMaterializer",
    "PatentAuthorityMaterializerError",
    "RecipeSchemaError",
    "ScheduleKind",
    "SnapshotImmutabilityError",
    "SnapshotNotFoundError",
    "SourceFreshnessEntry",
    "SourceFreshnessStatus",
    "TemporalAuthoritySnapshot",
    "assess_authoritative_readiness",
    "assess_source_freshness",
    "build_default_recipe",
    "default_fixture_dir",
    "filter_records_as_of",
    "write_default_fixtures",
]
