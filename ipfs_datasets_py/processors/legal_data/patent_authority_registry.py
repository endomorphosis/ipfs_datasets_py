"""Patent temporal authority graph and as-of resolver.

This module materializes authority tiers and amendment / supersession /
correction / withdrawal / stay / effective-date edges into a deterministic
temporal graph, then resolves exact mailing-date and response-date authority
views.

Design invariants (PATLAW-016 / source-authority policy):

* Historical replay is deterministic (sorted keys, stable candidate order).
* Proposed, future-effective, and withdrawn text is excluded unless the
  caller explicitly opts in via the as-of query flags.
* Conflicts and missing covering intervals return ``unknown`` with competing
  sources listed — never a silent pick.
* Official artifact identity and derived presentation identity remain
  separate views; derived text never replaces official authority.
* Authority tier ranking does not elevate guidance or candidates over
  enacted statute / promulgated regulation.
* Connector modules own I/O; this module owns graph + resolution only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Iterable, Iterator, Mapping, Optional, Sequence

from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    AuthoritySourceRecord,
    AuthoritySourceRegistry,
    AuthorityTier,
    ArtifactIdentity,
    IdentityRole,
    PatentAuthoritySourcesError,
    VerificationState,
    _deep_sorted_mapping,
    _parse_optional_date,
    _require_non_empty_str,
    _require_sha256,
    canonical_json_bytes,
    canonical_json_dumps,
    reject_hard_coded_latest,
)


SCHEMA_VERSION = "patent-authority-registry-v1"

# Higher rank = more controlling for selection among same-citation candidates.
_TIER_RANK: Mapping[AuthorityTier, int] = {
    AuthorityTier.OFFICIAL_BASE: 100,
    AuthorityTier.OFFICIAL_CHANGE: 90,
    AuthorityTier.UNOFFICIAL_CURRENT: 40,
    AuthorityTier.GUIDANCE: 20,
    AuthorityTier.CANDIDATE: 10,
}


class PatentAuthorityRegistryError(ValueError):
    """Base error for temporal authority graph and resolver failures."""


class DuplicateNodeError(PatentAuthorityRegistryError):
    """Raised when a node_id is registered twice without overwrite."""


class DuplicateEdgeError(PatentAuthorityRegistryError):
    """Raised when an edge_id is registered twice without overwrite."""


class UnknownNodeError(PatentAuthorityRegistryError):
    """Raised when an edge or query references a missing node."""


class TemporalRelation(str, Enum):
    """Directed lifecycle relation between authority text nodes.

    Aligns with Federal Register change relations and the plan's temporal
    graph vocabulary (amends, supersedes, corrects, withdraws, stays,
    delays_effective_date).
    """

    AMENDS = "amends"
    SUPERSEDES = "supersedes"
    CORRECTS = "corrects"
    WITHDRAWS = "withdraws"
    STAYS = "stays"
    DELAYS_EFFECTIVE_DATE = "delays_effective_date"
    REINSTATES = "reinstates"
    ENACTS = "enacts"
    RELATED = "related"

    @classmethod
    def coerce(cls, value: Any) -> "TemporalRelation":
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        for rel in cls:
            if rel.value == text or rel.name.lower() == text:
                return rel
        raise PatentAuthorityRegistryError(f"unsupported temporal relation: {value!r}")


class AsOfViewRole(str, Enum):
    """Which temporal anchor the query uses.

    Mailing-date and proposed-response-date views are resolved separately so a
    newer web page never silently rewrites a historical instruction.
    """

    MAILING_DATE = "mailing_date"
    RESPONSE_DATE = "response_date"
    AS_OF = "as_of"

    @classmethod
    def coerce(cls, value: Any) -> "AsOfViewRole":
        if isinstance(value, cls):
            return value
        text = str(value or "as_of").strip().lower().replace("-", "_")
        for role in cls:
            if role.value == text or role.name.lower() == text:
                return role
        raise PatentAuthorityRegistryError(f"unsupported as-of view role: {value!r}")


class AuthorityViewKind(str, Enum):
    """Which identity surface the resolver should prefer."""

    OFFICIAL = "official"
    DERIVED = "derived"
    BOTH_SEPARATE = "both_separate"

    @classmethod
    def coerce(cls, value: Any) -> "AuthorityViewKind":
        if isinstance(value, cls):
            return value
        text = str(value or "official").strip().lower().replace("-", "_")
        for kind in cls:
            if kind.value == text or kind.name.lower() == text:
                return kind
        raise PatentAuthorityRegistryError(f"unsupported authority view kind: {value!r}")


class ResolutionStatus(str, Enum):
    """Outcome of an as-of resolution."""

    RESOLVED = "resolved"
    UNKNOWN = "unknown"


class ExclusionReason(str, Enum):
    """Why a candidate node was excluded from selection."""

    PROPOSED = "proposed"
    FUTURE = "future"
    WITHDRAWN = "withdrawn"
    STAYED = "stayed"
    SUPERSEDED = "superseded"
    OUTSIDE_INTERVAL = "outside_interval"
    NOT_BINDING = "not_binding"
    WRONG_VIEW_KIND = "wrong_view_kind"
    WRONG_JURISDICTION = "wrong_jurisdiction"
    GUIDANCE_FILTERED = "guidance_filtered"
    EXPLICITLY_EXCLUDED = "explicitly_excluded"
    REPLACED_BY_EDGE = "replaced_by_edge"


class DiagnosticCode(str, Enum):
    """Typed diagnostics for as-of resolution and graph validation."""

    MISSING_INTERVAL = "missing_interval"
    CONFLICTING_SOURCES = "conflicting_sources"
    NO_CANDIDATES = "no_candidates"
    QUERY_DATE_MISSING = "query_date_missing"
    NODE_MISSING = "node_missing"
    EDGE_TARGET_MISSING = "edge_target_missing"
    EDGE_SOURCE_MISSING = "edge_source_missing"
    DUPLICATE_NODE = "duplicate_node"
    DUPLICATE_EDGE = "duplicate_edge"
    INVALID_INTERVAL = "invalid_interval"
    PROPOSED_EXCLUDED = "proposed_excluded"
    FUTURE_EXCLUDED = "future_excluded"
    WITHDRAWN_EXCLUDED = "withdrawn_excluded"
    OFFICIAL_DERIVED_SEPARATE = "official_derived_separate"
    TIER_PREEMPTED = "tier_preempted"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_date(value: Any, *, name: str = "date") -> Optional[date]:
    return _parse_optional_date(value, name=name)


def _require_date(value: Any, *, name: str) -> date:
    parsed = _parse_date(value, name=name)
    if parsed is None:
        raise PatentAuthorityRegistryError(f"{name} is required")
    return parsed


def _date_to_str(value: Optional[date]) -> Optional[str]:
    return None if value is None else value.isoformat()


def _coerce_authority_tier(value: Any) -> AuthorityTier:
    if isinstance(value, AuthorityTier):
        return value
    if value is None or (isinstance(value, str) and not value.strip()):
        raise PatentAuthorityRegistryError("authority_tier is required")
    text = str(value).strip().lower().replace("_", "-")
    for tier in AuthorityTier:
        if tier.value == text:
            return tier
    raise PatentAuthorityRegistryError(f"unknown authority_tier: {value!r}")


def _tier_rank(tier: AuthorityTier) -> int:
    return int(_TIER_RANK.get(tier, 0))


def _stable_hash(payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return digest


def _optional_artifact(
    value: ArtifactIdentity | Mapping[str, Any] | None,
) -> Optional[ArtifactIdentity]:
    if value is None:
        return None
    if isinstance(value, ArtifactIdentity):
        return value
    if isinstance(value, Mapping):
        return ArtifactIdentity.from_dict(value)
    raise PatentAuthorityRegistryError("artifact identity must be ArtifactIdentity or mapping")


def _deep_sorted(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _deep_sorted_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_deep_sorted(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Core records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthoritySpan:
    """Exact source span for a cited authority text fragment.

    Downstream citation resolvers (PATLAW-017) consume these spans to compare
    quoted text against the exact temporal source.
    """

    section: Optional[str] = None
    quote: Optional[str] = None
    artifact_sha256: Optional[str] = None
    start_offset: Optional[int] = None
    end_offset: Optional[int] = None
    page: Optional[int] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.section is not None:
            object.__setattr__(
                self, "section", _require_non_empty_str(self.section, "section")
            )
        if self.quote is not None:
            object.__setattr__(self, "quote", str(self.quote))
        if self.artifact_sha256 is not None:
            object.__setattr__(
                self,
                "artifact_sha256",
                _require_sha256(self.artifact_sha256, "artifact_sha256"),
            )
        for name in ("start_offset", "end_offset", "page", "line_start", "line_end"):
            raw = getattr(self, name)
            if raw is not None and (not isinstance(raw, int) or raw < 0):
                raise PatentAuthorityRegistryError(f"{name} must be a non-negative int")
        if (
            self.start_offset is not None
            and self.end_offset is not None
            and self.end_offset < self.start_offset
        ):
            raise PatentAuthorityRegistryError("end_offset must be >= start_offset")
        if not isinstance(self.metadata, Mapping):
            raise PatentAuthorityRegistryError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_sha256": self.artifact_sha256,
            "end_offset": self.end_offset,
            "line_end": self.line_end,
            "line_start": self.line_start,
            "metadata": _deep_sorted(self.metadata),
            "page": self.page,
            "quote": self.quote,
            "section": self.section,
            "start_offset": self.start_offset,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> Optional["AuthoritySpan"]:
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise PatentAuthorityRegistryError("authority span must be a mapping")
        return cls(
            section=value.get("section"),
            quote=value.get("quote"),
            artifact_sha256=value.get("artifact_sha256"),
            start_offset=value.get("start_offset"),
            end_offset=value.get("end_offset"),
            page=value.get("page"),
            line_start=value.get("line_start"),
            line_end=value.get("line_end"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class AuthorityTextNode:
    """One time-scoped authority text version in the temporal graph.

    A node may carry both an official artifact identity and a derived
    presentation identity. Resolution never conflates the two.
    """

    node_id: str
    citation_key: str
    authority_tier: AuthorityTier
    collection: str
    jurisdiction: str = "US"
    title: Optional[str] = None
    citation: Optional[str] = None
    edition: Optional[str] = None
    version: Optional[str] = None
    release_point: Optional[str] = None
    document_type: Optional[str] = None
    text_excerpt: Optional[str] = None
    publication_date: Optional[date] = None
    effective_start: Optional[date] = None
    effective_end: Optional[date] = None
    compliance_date: Optional[date] = None
    termination_date: Optional[date] = None
    is_binding: bool = False
    is_proposed: bool = False
    is_withdrawn: bool = False
    is_stayed: bool = False
    official_artifact: Optional[ArtifactIdentity] = None
    derived_presentation: Optional[ArtifactIdentity] = None
    source_key: Optional[str] = None
    span: Optional[AuthoritySpan] = None
    verification_state: VerificationState = VerificationState.UNVERIFIED
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "node_id", _require_non_empty_str(self.node_id, "node_id")
        )
        object.__setattr__(
            self,
            "citation_key",
            _require_non_empty_str(self.citation_key, "citation_key"),
        )
        object.__setattr__(
            self, "authority_tier", _coerce_authority_tier(self.authority_tier)
        )
        object.__setattr__(
            self, "collection", _require_non_empty_str(self.collection, "collection")
        )
        object.__setattr__(
            self,
            "jurisdiction",
            _require_non_empty_str(self.jurisdiction, "jurisdiction"),
        )
        for name in (
            "title",
            "citation",
            "document_type",
            "text_excerpt",
            "source_key",
            "notes",
        ):
            raw = getattr(self, name)
            if raw is not None:
                object.__setattr__(self, name, str(raw))

        for name in ("edition", "version", "release_point"):
            raw = getattr(self, name)
            if raw is not None:
                cleaned = _require_non_empty_str(raw, name)
                reject_hard_coded_latest(cleaned, field_name=name)
                object.__setattr__(self, name, cleaned)

        for name in (
            "publication_date",
            "effective_start",
            "effective_end",
            "compliance_date",
            "termination_date",
        ):
            object.__setattr__(
                self, name, _parse_date(getattr(self, name), name=name)
            )

        if self.effective_start and self.effective_end:
            if self.effective_end < self.effective_start:
                raise PatentAuthorityRegistryError(
                    "effective_end must be on or after effective_start"
                )

        # Proposed / withdrawn nodes cannot be binding.
        if self.is_proposed or self.is_withdrawn:
            object.__setattr__(self, "is_binding", False)

        # Document-type heuristics when flags not set explicitly.
        doc = (self.document_type or "").strip().lower().replace("-", "_")
        if doc in {"proposed_rule", "proposed", "pr"}:
            object.__setattr__(self, "is_proposed", True)
            object.__setattr__(self, "is_binding", False)
        if doc in {"withdrawal", "withdrawn"}:
            object.__setattr__(self, "is_withdrawn", True)
            object.__setattr__(self, "is_binding", False)

        official = _optional_artifact(self.official_artifact)
        if official is not None and official.role is not IdentityRole.OFFICIAL_ARTIFACT:
            official = replace(official, role=IdentityRole.OFFICIAL_ARTIFACT)
        object.__setattr__(self, "official_artifact", official)

        derived = _optional_artifact(self.derived_presentation)
        if derived is not None and derived.role is not IdentityRole.DERIVED_PRESENTATION:
            derived = replace(derived, role=IdentityRole.DERIVED_PRESENTATION)
        object.__setattr__(self, "derived_presentation", derived)

        if (
            self.authority_tier
            in (AuthorityTier.OFFICIAL_BASE, AuthorityTier.OFFICIAL_CHANGE)
            and self.official_artifact is None
            and self.derived_presentation is not None
        ):
            raise PatentAuthorityRegistryError(
                f"{self.authority_tier.value} nodes must not use only a derived "
                "presentation identity; attach official_artifact"
            )

        if self.span is not None and not isinstance(self.span, AuthoritySpan):
            if isinstance(self.span, Mapping):
                object.__setattr__(self, "span", AuthoritySpan.from_dict(self.span))
            else:
                raise PatentAuthorityRegistryError("span must be AuthoritySpan or mapping")

        if not isinstance(self.verification_state, VerificationState):
            text = str(self.verification_state).strip().lower().replace("-", "_")
            matched = None
            for state in VerificationState:
                if state.value == text or state.name.lower() == text:
                    matched = state
                    break
            if matched is None:
                raise PatentAuthorityRegistryError(
                    f"unknown verification_state: {self.verification_state!r}"
                )
            object.__setattr__(self, "verification_state", matched)

        if not isinstance(self.metadata, Mapping):
            raise PatentAuthorityRegistryError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def content_fingerprint(self) -> str:
        """Stable content key used to detect conflicting same-interval texts."""

        if self.official_artifact is not None:
            return f"official:{self.official_artifact.artifact_sha256}"
        if self.derived_presentation is not None:
            return f"derived:{self.derived_presentation.artifact_sha256}"
        if self.text_excerpt is not None:
            return f"text:{_stable_hash({'excerpt': self.text_excerpt})}"
        return f"node:{self.node_id}"

    @property
    def has_official_identity(self) -> bool:
        return self.official_artifact is not None

    @property
    def has_derived_identity(self) -> bool:
        return self.derived_presentation is not None

    def covers(self, as_of: date) -> bool:
        """Return whether *as_of* falls inside the node's effective interval."""

        if self.effective_start is not None and as_of < self.effective_start:
            return False
        end = self.effective_end or self.termination_date
        if end is not None and as_of > end:
            return False
        return True

    def is_future_as_of(self, as_of: date) -> bool:
        return self.effective_start is not None and as_of < self.effective_start

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_tier": self.authority_tier.value,
            "citation": self.citation,
            "citation_key": self.citation_key,
            "collection": self.collection,
            "compliance_date": _date_to_str(self.compliance_date),
            "derived_presentation": (
                None
                if self.derived_presentation is None
                else self.derived_presentation.to_dict()
            ),
            "document_type": self.document_type,
            "edition": self.edition,
            "effective_end": _date_to_str(self.effective_end),
            "effective_start": _date_to_str(self.effective_start),
            "is_binding": bool(self.is_binding),
            "is_proposed": bool(self.is_proposed),
            "is_stayed": bool(self.is_stayed),
            "is_withdrawn": bool(self.is_withdrawn),
            "jurisdiction": self.jurisdiction,
            "metadata": _deep_sorted(self.metadata),
            "node_id": self.node_id,
            "notes": self.notes,
            "official_artifact": (
                None if self.official_artifact is None else self.official_artifact.to_dict()
            ),
            "publication_date": _date_to_str(self.publication_date),
            "release_point": self.release_point,
            "source_key": self.source_key,
            "span": None if self.span is None else self.span.to_dict(),
            "termination_date": _date_to_str(self.termination_date),
            "text_excerpt": self.text_excerpt,
            "title": self.title,
            "verification_state": self.verification_state.value,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthorityTextNode":
        if not isinstance(value, Mapping):
            raise PatentAuthorityRegistryError("authority text node must be a mapping")
        return cls(
            node_id=str(value.get("node_id") or value.get("id") or ""),
            citation_key=str(value.get("citation_key") or value.get("key") or ""),
            authority_tier=value.get("authority_tier"),
            collection=str(value.get("collection") or ""),
            jurisdiction=str(value.get("jurisdiction") or "US"),
            title=value.get("title"),
            citation=value.get("citation"),
            edition=value.get("edition"),
            version=value.get("version"),
            release_point=value.get("release_point"),
            document_type=value.get("document_type"),
            text_excerpt=value.get("text_excerpt"),
            publication_date=value.get("publication_date"),
            effective_start=value.get("effective_start"),
            effective_end=value.get("effective_end"),
            compliance_date=value.get("compliance_date"),
            termination_date=value.get("termination_date"),
            is_binding=bool(value.get("is_binding", False)),
            is_proposed=bool(value.get("is_proposed", False)),
            is_withdrawn=bool(value.get("is_withdrawn", False)),
            is_stayed=bool(value.get("is_stayed", False)),
            official_artifact=value.get("official_artifact"),
            derived_presentation=value.get("derived_presentation"),
            source_key=value.get("source_key"),
            span=AuthoritySpan.from_dict(value.get("span")),
            verification_state=value.get(
                "verification_state", VerificationState.UNVERIFIED
            ),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )

    @classmethod
    def from_source_record(
        cls,
        record: AuthoritySourceRecord,
        *,
        node_id: str | None = None,
        citation_key: str | None = None,
        is_binding: bool | None = None,
        is_proposed: bool = False,
        is_withdrawn: bool = False,
        document_type: str | None = None,
        text_excerpt: str | None = None,
        span: AuthoritySpan | None = None,
    ) -> "AuthorityTextNode":
        """Project an :class:`AuthoritySourceRecord` into a graph node."""

        binding = is_binding
        if binding is None:
            binding = record.authority_tier in (
                AuthorityTier.OFFICIAL_BASE,
                AuthorityTier.OFFICIAL_CHANGE,
            ) and not is_proposed and not is_withdrawn
        return cls(
            node_id=node_id or record.source_key,
            citation_key=citation_key or record.citation or record.source_key,
            authority_tier=record.authority_tier,
            collection=record.collection,
            jurisdiction=record.jurisdiction,
            title=record.title,
            citation=record.citation,
            edition=record.edition,
            version=record.version,
            release_point=record.release_point,
            document_type=document_type,
            text_excerpt=text_excerpt,
            publication_date=record.publication_date,
            effective_start=record.effective_start,
            effective_end=record.effective_end,
            termination_date=record.termination_date,
            is_binding=bool(binding),
            is_proposed=is_proposed,
            is_withdrawn=is_withdrawn,
            official_artifact=record.official_artifact,
            derived_presentation=record.derived_presentation,
            source_key=record.source_key,
            span=span,
            verification_state=record.verification_state,
            notes=record.notes,
            metadata=dict(record.metadata),
        )


@dataclass(frozen=True, slots=True)
class AuthorityTemporalEdge:
    """Directed temporal relation between two authority text nodes.

    *source_node_id* is the changing instrument; *target_node_id* is the
    affected (amended / superseded / withdrawn / stayed) node.
    """

    edge_id: str
    relation: TemporalRelation
    source_node_id: str
    target_node_id: str
    effective_date: Optional[date] = None
    reason: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "edge_id", _require_non_empty_str(self.edge_id, "edge_id")
        )
        object.__setattr__(self, "relation", TemporalRelation.coerce(self.relation))
        object.__setattr__(
            self,
            "source_node_id",
            _require_non_empty_str(self.source_node_id, "source_node_id"),
        )
        object.__setattr__(
            self,
            "target_node_id",
            _require_non_empty_str(self.target_node_id, "target_node_id"),
        )
        object.__setattr__(
            self,
            "effective_date",
            _parse_date(self.effective_date, name="effective_date"),
        )
        if self.reason is not None:
            object.__setattr__(
                self, "reason", _require_non_empty_str(self.reason, "reason")
            )
        if not isinstance(self.metadata, Mapping):
            raise PatentAuthorityRegistryError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "effective_date": _date_to_str(self.effective_date),
            "metadata": _deep_sorted(self.metadata),
            "reason": self.reason,
            "relation": self.relation.value,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthorityTemporalEdge":
        if not isinstance(value, Mapping):
            raise PatentAuthorityRegistryError("authority temporal edge must be a mapping")
        edge_id = value.get("edge_id") or value.get("id")
        if not edge_id:
            payload = {
                "relation": str(value.get("relation") or ""),
                "source": str(value.get("source_node_id") or value.get("source") or ""),
                "target": str(value.get("target_node_id") or value.get("target") or ""),
                "effective_date": str(value.get("effective_date") or ""),
            }
            edge_id = f"edge-{_stable_hash(payload)[:20]}"
        return cls(
            edge_id=str(edge_id),
            relation=value.get("relation", TemporalRelation.RELATED),
            source_node_id=str(
                value.get("source_node_id")
                or value.get("source")
                or value.get("from")
                or ""
            ),
            target_node_id=str(
                value.get("target_node_id")
                or value.get("target")
                or value.get("to")
                or ""
            ),
            effective_date=value.get("effective_date"),
            reason=value.get("reason"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class AsOfQuery:
    """As-of query against the temporal authority graph."""

    as_of: date
    citation_key: Optional[str] = None
    node_ids: tuple[str, ...] = ()
    view_role: AsOfViewRole = AsOfViewRole.AS_OF
    view_kind: AuthorityViewKind = AuthorityViewKind.OFFICIAL
    include_proposed: bool = False
    include_future: bool = False
    include_withdrawn: bool = False
    include_stayed: bool = False
    include_guidance: bool = True
    include_nonbinding: bool = False
    jurisdiction: str = "US"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", _require_date(self.as_of, name="as_of"))
        if self.citation_key is not None:
            object.__setattr__(
                self,
                "citation_key",
                _require_non_empty_str(self.citation_key, "citation_key"),
            )
        object.__setattr__(self, "view_role", AsOfViewRole.coerce(self.view_role))
        object.__setattr__(self, "view_kind", AuthorityViewKind.coerce(self.view_kind))
        ids = tuple(
            _require_non_empty_str(str(i), "node_id")
            for i in (self.node_ids or ())
        )
        object.__setattr__(self, "node_ids", ids)
        object.__setattr__(
            self,
            "jurisdiction",
            _require_non_empty_str(self.jurisdiction, "jurisdiction"),
        )
        if not isinstance(self.metadata, Mapping):
            raise PatentAuthorityRegistryError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": _date_to_str(self.as_of),
            "citation_key": self.citation_key,
            "include_future": bool(self.include_future),
            "include_guidance": bool(self.include_guidance),
            "include_nonbinding": bool(self.include_nonbinding),
            "include_proposed": bool(self.include_proposed),
            "include_stayed": bool(self.include_stayed),
            "include_withdrawn": bool(self.include_withdrawn),
            "jurisdiction": self.jurisdiction,
            "metadata": _deep_sorted(self.metadata),
            "node_ids": list(self.node_ids),
            "view_kind": self.view_kind.value,
            "view_role": self.view_role.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AsOfQuery":
        if not isinstance(value, Mapping):
            raise PatentAuthorityRegistryError("as-of query must be a mapping")
        raw_ids = value.get("node_ids") or ()
        return cls(
            as_of=value.get("as_of") or value.get("query_date") or value.get("date"),
            citation_key=value.get("citation_key"),
            node_ids=tuple(raw_ids),
            view_role=value.get("view_role", AsOfViewRole.AS_OF),
            view_kind=value.get("view_kind", AuthorityViewKind.OFFICIAL),
            include_proposed=bool(value.get("include_proposed", False)),
            include_future=bool(value.get("include_future", False)),
            include_withdrawn=bool(value.get("include_withdrawn", False)),
            include_stayed=bool(value.get("include_stayed", False)),
            include_guidance=bool(value.get("include_guidance", True)),
            include_nonbinding=bool(value.get("include_nonbinding", False)),
            jurisdiction=str(value.get("jurisdiction") or "US"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class CompetingSource:
    """One competing authority node when resolution is unknown/conflicted."""

    node_id: str
    authority_tier: AuthorityTier
    citation: Optional[str] = None
    version: Optional[str] = None
    effective_start: Optional[date] = None
    content_fingerprint: Optional[str] = None
    reason: str = "competing"

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_tier": self.authority_tier.value,
            "citation": self.citation,
            "content_fingerprint": self.content_fingerprint,
            "effective_start": _date_to_str(self.effective_start),
            "node_id": self.node_id,
            "reason": self.reason,
            "version": self.version,
        }

    @classmethod
    def from_node(
        cls,
        node: AuthorityTextNode,
        *,
        reason: str = "competing",
    ) -> "CompetingSource":
        return cls(
            node_id=node.node_id,
            authority_tier=node.authority_tier,
            citation=node.citation,
            version=node.version,
            effective_start=node.effective_start,
            content_fingerprint=node.content_fingerprint,
            reason=reason,
        )


@dataclass(frozen=True, slots=True)
class ResolutionDiagnostic:
    """Typed diagnostic attached to an as-of resolution."""

    code: DiagnosticCode
    message: str
    severity: str = "info"
    node_id: Optional[str] = None
    edge_id: Optional[str] = None
    field_path: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "edge_id": self.edge_id,
            "field_path": self.field_path,
            "message": self.message,
            "node_id": self.node_id,
            "severity": self.severity,
        }


@dataclass(frozen=True, slots=True)
class ExcludedCandidate:
    """A candidate excluded during as-of filtering."""

    node_id: str
    reason: ExclusionReason
    detail: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "detail": self.detail,
            "node_id": self.node_id,
            "reason": self.reason.value,
        }


@dataclass(frozen=True, slots=True)
class AsOfResolution:
    """Result of resolving authority as of a date.

    Official and derived views are exposed as separate optional snapshots so
    callers never treat presentation as the official record.
    """

    status: ResolutionStatus
    query: AsOfQuery
    selected_node_id: Optional[str] = None
    official_node_id: Optional[str] = None
    derived_node_id: Optional[str] = None
    selected_span: Optional[AuthoritySpan] = None
    authority_tier: Optional[AuthorityTier] = None
    competing_sources: tuple[CompetingSource, ...] = ()
    excluded: tuple[ExcludedCandidate, ...] = ()
    diagnostics: tuple[ResolutionDiagnostic, ...] = ()
    applied_edge_ids: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    @property
    def is_resolved(self) -> bool:
        return self.status is ResolutionStatus.RESOLVED

    @property
    def is_unknown(self) -> bool:
        return self.status is ResolutionStatus.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied_edge_ids": list(self.applied_edge_ids),
            "authority_tier": (
                None if self.authority_tier is None else self.authority_tier.value
            ),
            "competing_sources": [c.to_dict() for c in self.competing_sources],
            "derived_node_id": self.derived_node_id,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "excluded": [e.to_dict() for e in self.excluded],
            "official_node_id": self.official_node_id,
            "query": self.query.to_dict(),
            "schema_version": self.schema_version,
            "selected_node_id": self.selected_node_id,
            "selected_span": (
                None if self.selected_span is None else self.selected_span.to_dict()
            ),
            "status": self.status.value,
        }

    def to_canonical_json(self) -> str:
        return canonical_json_dumps(self.to_dict())


@dataclass(frozen=True, slots=True)
class DualDateViews:
    """Mailing-date and response-date resolutions kept separate."""

    mailing: AsOfResolution
    response: AsOfResolution

    def to_dict(self) -> dict[str, Any]:
        return {
            "mailing": self.mailing.to_dict(),
            "response": self.response.to_dict(),
            "schema_version": SCHEMA_VERSION,
        }

    def to_canonical_json(self) -> str:
        return canonical_json_dumps(self.to_dict())


# ---------------------------------------------------------------------------
# Graph + registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PatentTemporalAuthorityGraph:
    """Immutable temporal authority graph (nodes + edges)."""

    graph_id: str
    nodes: tuple[AuthorityTextNode, ...]
    edges: tuple[AuthorityTemporalEdge, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "graph_id", _require_non_empty_str(self.graph_id, "graph_id")
        )
        # Deterministic ordering for replay.
        nodes = tuple(sorted(self.nodes, key=lambda n: n.node_id))
        edges = tuple(sorted(self.edges, key=lambda e: e.edge_id))
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "edges", edges)
        if not isinstance(self.metadata, Mapping):
            raise PatentAuthorityRegistryError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def node_by_id(self) -> Mapping[str, AuthorityTextNode]:
        return {n.node_id: n for n in self.nodes}

    @property
    def edge_by_id(self) -> Mapping[str, AuthorityTemporalEdge]:
        return {e.edge_id: e for e in self.edges}

    def nodes_for_citation(self, citation_key: str) -> tuple[AuthorityTextNode, ...]:
        key = citation_key.strip()
        return tuple(n for n in self.nodes if n.citation_key == key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "edges": [e.to_dict() for e in self.edges],
            "graph_id": self.graph_id,
            "metadata": _deep_sorted(self.metadata),
            "nodes": [n.to_dict() for n in self.nodes],
            "schema_version": self.schema_version,
        }

    def to_canonical_json(self) -> str:
        return canonical_json_dumps(self.to_dict())

    def to_canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PatentTemporalAuthorityGraph":
        if not isinstance(value, Mapping):
            raise PatentAuthorityRegistryError("temporal graph must be a mapping")
        return cls(
            graph_id=str(value.get("graph_id") or value.get("temporal_authority_graph_id") or ""),
            nodes=tuple(
                AuthorityTextNode.from_dict(item)
                for item in (value.get("nodes") or [])
            ),
            edges=tuple(
                AuthorityTemporalEdge.from_dict(item)
                for item in (value.get("edges") or [])
            ),
            metadata=value.get("metadata") or {},
            schema_version=str(value.get("schema_version") or SCHEMA_VERSION),
        )


class PatentTemporalAuthorityGraphBuilder:
    """Mutable builder for the patent temporal authority graph."""

    def __init__(
        self,
        *,
        graph_id: str = "patent-temporal-authority",
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.graph_id = graph_id
        self.metadata = dict(metadata or {})
        self._nodes: dict[str, AuthorityTextNode] = {}
        self._edges: dict[str, AuthorityTemporalEdge] = {}

    def add_node(
        self,
        node: AuthorityTextNode | Mapping[str, Any],
        *,
        overwrite: bool = False,
    ) -> AuthorityTextNode:
        typed = (
            node
            if isinstance(node, AuthorityTextNode)
            else AuthorityTextNode.from_dict(node)
        )
        if typed.node_id in self._nodes and not overwrite:
            raise DuplicateNodeError(f"node already registered: {typed.node_id!r}")
        self._nodes[typed.node_id] = typed
        return typed

    def add_edge(
        self,
        edge: AuthorityTemporalEdge | Mapping[str, Any],
        *,
        overwrite: bool = False,
        require_nodes: bool = True,
    ) -> AuthorityTemporalEdge:
        typed = (
            edge
            if isinstance(edge, AuthorityTemporalEdge)
            else AuthorityTemporalEdge.from_dict(edge)
        )
        if typed.edge_id in self._edges and not overwrite:
            raise DuplicateEdgeError(f"edge already registered: {typed.edge_id!r}")
        if require_nodes:
            if typed.source_node_id not in self._nodes:
                raise UnknownNodeError(
                    f"edge source node missing: {typed.source_node_id!r}"
                )
            if typed.target_node_id not in self._nodes:
                raise UnknownNodeError(
                    f"edge target node missing: {typed.target_node_id!r}"
                )
        self._edges[typed.edge_id] = typed
        return typed

    def add_source_record(
        self,
        record: AuthoritySourceRecord,
        **kwargs: Any,
    ) -> AuthorityTextNode:
        return self.add_node(AuthorityTextNode.from_source_record(record, **kwargs))

    def build(self) -> PatentTemporalAuthorityGraph:
        return PatentTemporalAuthorityGraph(
            graph_id=self.graph_id,
            nodes=tuple(self._nodes.values()),
            edges=tuple(self._edges.values()),
            metadata=self.metadata,
        )


def validate_temporal_authority_graph(
    graph: PatentTemporalAuthorityGraph | Mapping[str, Any],
) -> tuple[ResolutionDiagnostic, ...]:
    """Validate node intervals and edge endpoints; returns diagnostics only."""

    if not isinstance(graph, PatentTemporalAuthorityGraph):
        graph = PatentTemporalAuthorityGraph.from_dict(graph)
    diagnostics: list[ResolutionDiagnostic] = []
    seen_nodes: set[str] = set()
    for node in graph.nodes:
        if node.node_id in seen_nodes:
            diagnostics.append(
                ResolutionDiagnostic(
                    code=DiagnosticCode.DUPLICATE_NODE,
                    message=f"duplicate node_id {node.node_id!r}",
                    severity="error",
                    node_id=node.node_id,
                )
            )
        seen_nodes.add(node.node_id)
        if (
            node.effective_start is not None
            and node.effective_end is not None
            and node.effective_end < node.effective_start
        ):
            diagnostics.append(
                ResolutionDiagnostic(
                    code=DiagnosticCode.INVALID_INTERVAL,
                    message="effective_end before effective_start",
                    severity="error",
                    node_id=node.node_id,
                    field_path="effective_end",
                )
            )
    node_ids = set(graph.node_by_id)
    seen_edges: set[str] = set()
    for edge in graph.edges:
        if edge.edge_id in seen_edges:
            diagnostics.append(
                ResolutionDiagnostic(
                    code=DiagnosticCode.DUPLICATE_EDGE,
                    message=f"duplicate edge_id {edge.edge_id!r}",
                    severity="error",
                    edge_id=edge.edge_id,
                )
            )
        seen_edges.add(edge.edge_id)
        if edge.source_node_id not in node_ids:
            diagnostics.append(
                ResolutionDiagnostic(
                    code=DiagnosticCode.EDGE_SOURCE_MISSING,
                    message=f"edge source missing: {edge.source_node_id!r}",
                    severity="error",
                    edge_id=edge.edge_id,
                    node_id=edge.source_node_id,
                )
            )
        if edge.target_node_id not in node_ids:
            diagnostics.append(
                ResolutionDiagnostic(
                    code=DiagnosticCode.EDGE_TARGET_MISSING,
                    message=f"edge target missing: {edge.target_node_id!r}",
                    severity="error",
                    edge_id=edge.edge_id,
                    node_id=edge.target_node_id,
                )
            )
    diagnostics.sort(key=lambda d: (d.code.value, d.node_id or "", d.edge_id or "", d.message))
    return tuple(diagnostics)


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def _edges_active_on_or_before(
    edges: Sequence[AuthorityTemporalEdge],
    as_of: date,
) -> list[AuthorityTemporalEdge]:
    active: list[AuthorityTemporalEdge] = []
    for edge in edges:
        if edge.effective_date is None or edge.effective_date <= as_of:
            active.append(edge)
    # Deterministic application order: by effective_date, then edge_id.
    active.sort(
        key=lambda e: (
            e.effective_date or date.min,
            e.edge_id,
        )
    )
    return active


def _apply_edges(
    nodes: Mapping[str, AuthorityTextNode],
    edges: Sequence[AuthorityTemporalEdge],
    as_of: date,
) -> tuple[dict[str, AuthorityTextNode], tuple[str, ...], set[str]]:
    """Apply lifecycle edges, returning mutated node views and replaced ids.

    Returns:
        (working_nodes, applied_edge_ids, replaced_node_ids)

    *replaced_node_ids* are nodes that should not win selection because a
    superseding / amending / correcting edge has replaced them as of *as_of*.
    """

    working: dict[str, AuthorityTextNode] = dict(nodes)
    applied: list[str] = []
    replaced: set[str] = set()

    for edge in _edges_active_on_or_before(edges, as_of):
        if edge.source_node_id not in working or edge.target_node_id not in working:
            continue
        applied.append(edge.edge_id)
        target = working[edge.target_node_id]
        source = working[edge.source_node_id]
        rel = edge.relation

        if rel is TemporalRelation.WITHDRAWS:
            working[edge.target_node_id] = replace(
                target, is_withdrawn=True, is_binding=False
            )
            # The withdrawal instrument itself is nonbinding context.
            working[edge.source_node_id] = replace(
                source, is_withdrawn=True, is_binding=False
            )
        elif rel is TemporalRelation.STAYS:
            working[edge.target_node_id] = replace(
                target, is_stayed=True, is_binding=False
            )
        elif rel is TemporalRelation.DELAYS_EFFECTIVE_DATE:
            new_start = edge.effective_date or target.effective_start
            # Delay pushes the target's effective start forward when the edge
            # carries a later effective date encoded on the source.
            delay_to = source.effective_start or edge.effective_date
            if delay_to is not None:
                if target.effective_start is None or delay_to > target.effective_start:
                    working[edge.target_node_id] = replace(
                        target, effective_start=delay_to
                    )
                else:
                    working[edge.target_node_id] = replace(
                        target, effective_start=new_start
                    )
        elif rel is TemporalRelation.SUPERSEDES:
            # Source supersedes target from the edge effective date forward.
            end = edge.effective_date
            if end is not None:
                # Target ends the day before supersession when possible.
                prior = date.fromordinal(max(end.toordinal() - 1, date.min.toordinal()))
                if target.effective_end is None or prior < target.effective_end:
                    working[edge.target_node_id] = replace(target, effective_end=prior)
            if edge.effective_date is None or edge.effective_date <= as_of:
                replaced.add(edge.target_node_id)
        elif rel in (TemporalRelation.AMENDS, TemporalRelation.CORRECTS):
            # Amendment/correction replaces the prior text for the interval
            # after the edge is effective.
            if edge.effective_date is None or edge.effective_date <= as_of:
                replaced.add(edge.target_node_id)
                end = edge.effective_date
                if end is not None:
                    prior = date.fromordinal(
                        max(end.toordinal() - 1, date.min.toordinal())
                    )
                    if target.effective_end is None or prior < target.effective_end:
                        working[edge.target_node_id] = replace(
                            target, effective_end=prior
                        )
        elif rel is TemporalRelation.REINSTATES:
            working[edge.target_node_id] = replace(
                target, is_stayed=False, is_withdrawn=False
            )
            replaced.discard(edge.target_node_id)

    return working, tuple(applied), replaced


def _filter_candidate(
    node: AuthorityTextNode,
    query: AsOfQuery,
    *,
    replaced: set[str],
) -> Optional[ExcludedCandidate]:
    """Return an exclusion record if *node* should not be selected."""

    if node.jurisdiction != query.jurisdiction:
        return ExcludedCandidate(
            node.node_id, ExclusionReason.WRONG_JURISDICTION, node.jurisdiction
        )
    if node.node_id in replaced:
        return ExcludedCandidate(node.node_id, ExclusionReason.REPLACED_BY_EDGE)
    if node.is_proposed and not query.include_proposed:
        return ExcludedCandidate(node.node_id, ExclusionReason.PROPOSED)
    if node.is_withdrawn and not query.include_withdrawn:
        return ExcludedCandidate(node.node_id, ExclusionReason.WITHDRAWN)
    if node.is_stayed and not query.include_stayed:
        return ExcludedCandidate(node.node_id, ExclusionReason.STAYED)
    if node.is_future_as_of(query.as_of) and not query.include_future:
        return ExcludedCandidate(
            node.node_id,
            ExclusionReason.FUTURE,
            detail=_date_to_str(node.effective_start),
        )
    if not node.covers(query.as_of):
        # Missing or non-covering interval.
        if node.effective_start is None and node.effective_end is None:
            # Open-ended with no start: treat as missing interval (unknown later).
            return ExcludedCandidate(node.node_id, ExclusionReason.OUTSIDE_INTERVAL)
        return ExcludedCandidate(node.node_id, ExclusionReason.OUTSIDE_INTERVAL)
    if (
        node.authority_tier is AuthorityTier.GUIDANCE
        and not query.include_guidance
    ):
        return ExcludedCandidate(node.node_id, ExclusionReason.GUIDANCE_FILTERED)
    if not node.is_binding and not query.include_nonbinding:
        # Guidance is allowed when include_guidance is true even if nonbinding.
        if node.authority_tier is AuthorityTier.GUIDANCE and query.include_guidance:
            pass
        else:
            return ExcludedCandidate(node.node_id, ExclusionReason.NOT_BINDING)
    if query.view_kind is AuthorityViewKind.OFFICIAL:
        if not node.has_official_identity and node.has_derived_identity:
            # Pure derived presentation is wrong view for official queries.
            if node.authority_tier is AuthorityTier.UNOFFICIAL_CURRENT:
                return ExcludedCandidate(node.node_id, ExclusionReason.WRONG_VIEW_KIND)
    if query.view_kind is AuthorityViewKind.DERIVED:
        if not node.has_derived_identity and node.has_official_identity:
            # Prefer nodes that expose derived identity for derived view.
            pass
    return None


def _selection_key(node: AuthorityTextNode) -> tuple:
    """Deterministic ranking key: higher is better (we sort reverse)."""

    return (
        _tier_rank(node.authority_tier),
        1 if node.is_binding else 0,
        node.effective_start or date.min,
        node.publication_date or date.min,
        # Prefer official identity when present.
        1 if node.has_official_identity else 0,
        # Stable tie-break: reverse node_id so sort is fully deterministic.
        node.node_id,
    )


def _pick_unique(
    candidates: Sequence[AuthorityTextNode],
) -> tuple[Optional[AuthorityTextNode], tuple[CompetingSource, ...], list[ResolutionDiagnostic]]:
    """Pick a single winner or return unknown with competing sources."""

    if not candidates:
        return None, (), [
            ResolutionDiagnostic(
                code=DiagnosticCode.NO_CANDIDATES,
                message="no authority candidates remain after filters",
                severity="warning",
            )
        ]

    ranked = sorted(candidates, key=_selection_key, reverse=True)
    best = ranked[0]
    # Collect all candidates at the same controlling tier that cover the
    # interval and compare content fingerprints for conflict.
    top_tier = best.authority_tier
    same_tier = [n for n in ranked if n.authority_tier is top_tier]
    fingerprints = {n.content_fingerprint for n in same_tier}
    if len(fingerprints) > 1:
        competing = tuple(
            CompetingSource.from_node(n, reason="conflicting_content")
            for n in sorted(same_tier, key=lambda x: x.node_id)
        )
        return None, competing, [
            ResolutionDiagnostic(
                code=DiagnosticCode.CONFLICTING_SOURCES,
                message=(
                    f"{len(competing)} competing sources at tier "
                    f"{top_tier.value} with distinct content"
                ),
                severity="error",
            )
        ]
    # Same content (or single candidate): resolve to the best-ranked node.
    # If multiple node_ids share the fingerprint, pick best by selection key.
    return best, (), []


def resolve_as_of(
    graph: PatentTemporalAuthorityGraph | Mapping[str, Any],
    query: AsOfQuery | Mapping[str, Any] | date,
    *,
    citation_key: str | None = None,
) -> AsOfResolution:
    """Resolve the governing authority text as of a date.

    Default behavior excludes proposed, future-effective, and withdrawn text.
    Conflicts and missing covering intervals return ``unknown`` with competing
    sources. Official and derived views stay separate.
    """

    if not isinstance(graph, PatentTemporalAuthorityGraph):
        graph = PatentTemporalAuthorityGraph.from_dict(graph)

    if isinstance(query, date) and not isinstance(query, datetime):
        query = AsOfQuery(as_of=query, citation_key=citation_key)
    elif isinstance(query, datetime):
        query = AsOfQuery(as_of=query.date(), citation_key=citation_key)
    elif isinstance(query, Mapping):
        query = AsOfQuery.from_dict(query)
    elif not isinstance(query, AsOfQuery):
        raise PatentAuthorityRegistryError("query must be AsOfQuery, mapping, or date")

    if citation_key and not query.citation_key:
        query = replace(query, citation_key=citation_key)

    diagnostics: list[ResolutionDiagnostic] = []
    excluded: list[ExcludedCandidate] = []

    # Seed candidates.
    if query.node_ids:
        candidates = []
        for nid in query.node_ids:
            node = graph.node_by_id.get(nid)
            if node is None:
                diagnostics.append(
                    ResolutionDiagnostic(
                        code=DiagnosticCode.NODE_MISSING,
                        message=f"unknown node_id {nid!r}",
                        severity="error",
                        node_id=nid,
                    )
                )
            else:
                candidates.append(node)
    elif query.citation_key:
        candidates = list(graph.nodes_for_citation(query.citation_key))
    else:
        candidates = list(graph.nodes)

    if not candidates:
        return AsOfResolution(
            status=ResolutionStatus.UNKNOWN,
            query=query,
            diagnostics=tuple(
                diagnostics
                + [
                    ResolutionDiagnostic(
                        code=DiagnosticCode.NO_CANDIDATES,
                        message="no nodes matched the query",
                        severity="warning",
                    )
                ]
            ),
        )

    # Restrict edge application to the relevant citation family when possible.
    citation_keys = {c.citation_key for c in candidates}
    related_ids = {
        n.node_id for n in graph.nodes if n.citation_key in citation_keys
    }
    # Also include edge endpoints that touch related nodes.
    for edge in graph.edges:
        if edge.source_node_id in related_ids or edge.target_node_id in related_ids:
            related_ids.add(edge.source_node_id)
            related_ids.add(edge.target_node_id)

    working_seed = {
        nid: graph.node_by_id[nid]
        for nid in sorted(related_ids)
        if nid in graph.node_by_id
    }
    working, applied_edges, replaced = _apply_edges(
        working_seed, graph.edges, query.as_of
    )

    # Re-map candidates through edge-applied working set.
    working_candidates = [
        working.get(c.node_id, c) for c in candidates if c.node_id in working or c.node_id in graph.node_by_id
    ]
    # Prefer working versions.
    working_candidates = [
        working[c.node_id] if c.node_id in working else c for c in candidates
    ]

    filtered: list[AuthorityTextNode] = []
    missing_interval_nodes: list[AuthorityTextNode] = []
    for node in working_candidates:
        exclusion = _filter_candidate(node, query, replaced=replaced)
        if exclusion is not None:
            excluded.append(exclusion)
            if exclusion.reason is ExclusionReason.OUTSIDE_INTERVAL:
                missing_interval_nodes.append(node)
            if exclusion.reason is ExclusionReason.PROPOSED:
                diagnostics.append(
                    ResolutionDiagnostic(
                        code=DiagnosticCode.PROPOSED_EXCLUDED,
                        message="proposed rule excluded unless include_proposed=True",
                        severity="info",
                        node_id=node.node_id,
                    )
                )
            elif exclusion.reason is ExclusionReason.FUTURE:
                diagnostics.append(
                    ResolutionDiagnostic(
                        code=DiagnosticCode.FUTURE_EXCLUDED,
                        message="future-effective text excluded unless include_future=True",
                        severity="info",
                        node_id=node.node_id,
                    )
                )
            elif exclusion.reason is ExclusionReason.WITHDRAWN:
                diagnostics.append(
                    ResolutionDiagnostic(
                        code=DiagnosticCode.WITHDRAWN_EXCLUDED,
                        message="withdrawn text excluded unless include_withdrawn=True",
                        severity="info",
                        node_id=node.node_id,
                    )
                )
            continue
        filtered.append(node)

    # Sort exclusions for deterministic output.
    excluded.sort(key=lambda e: (e.reason.value, e.node_id))

    # View-kind handling: official vs derived remain separate.
    official_candidates = [n for n in filtered if n.has_official_identity or (
        n.authority_tier in (AuthorityTier.OFFICIAL_BASE, AuthorityTier.OFFICIAL_CHANGE)
    )]
    derived_candidates = [n for n in filtered if n.has_derived_identity]
    # For guidance without official identity, still allow official view pick.
    if query.view_kind is AuthorityViewKind.OFFICIAL:
        pool = official_candidates or [
            n for n in filtered
            if n.authority_tier is AuthorityTier.GUIDANCE
            or not n.has_derived_identity
        ]
    elif query.view_kind is AuthorityViewKind.DERIVED:
        pool = derived_candidates or filtered
    else:
        pool = filtered

    winner, competing, pick_diagnostics = _pick_unique(pool)
    diagnostics.extend(pick_diagnostics)

    if winner is None:
        # Missing interval: no covering candidate.
        if not filtered and missing_interval_nodes:
            competing = tuple(
                CompetingSource.from_node(n, reason="missing_interval")
                for n in sorted(missing_interval_nodes, key=lambda x: x.node_id)
            )
            diagnostics.append(
                ResolutionDiagnostic(
                    code=DiagnosticCode.MISSING_INTERVAL,
                    message="no node covers the as-of date",
                    severity="warning",
                )
            )
        # If we have competing from conflict, status unknown.
        diagnostics.sort(
            key=lambda d: (d.code.value, d.node_id or "", d.message)
        )
        return AsOfResolution(
            status=ResolutionStatus.UNKNOWN,
            query=query,
            competing_sources=tuple(
                sorted(competing, key=lambda c: (c.reason, c.node_id))
            ),
            excluded=tuple(excluded),
            diagnostics=tuple(diagnostics),
            applied_edge_ids=applied_edges,
        )

    official_id: Optional[str] = None
    derived_id: Optional[str] = None
    if query.view_kind is AuthorityViewKind.BOTH_SEPARATE:
        off_winner, off_competing, off_diag = _pick_unique(
            official_candidates or [winner]
        )
        der_winner, der_competing, der_diag = _pick_unique(
            derived_candidates
        )
        diagnostics.extend(off_diag)
        diagnostics.extend(der_diag)
        official_id = None if off_winner is None else off_winner.node_id
        derived_id = None if der_winner is None else der_winner.node_id
        if off_winner is None and der_winner is None:
            merged = tuple(
                sorted(
                    list(off_competing) + list(der_competing),
                    key=lambda c: (c.reason, c.node_id),
                )
            )
            return AsOfResolution(
                status=ResolutionStatus.UNKNOWN,
                query=query,
                competing_sources=merged,
                excluded=tuple(excluded),
                diagnostics=tuple(
                    sorted(diagnostics, key=lambda d: (d.code.value, d.node_id or "", d.message))
                ),
                applied_edge_ids=applied_edges,
            )
        # Prefer official as selected when both_separate; derived is parallel.
        selected = off_winner or der_winner or winner
        if off_winner is not None and der_winner is not None:
            diagnostics.append(
                ResolutionDiagnostic(
                    code=DiagnosticCode.OFFICIAL_DERIVED_SEPARATE,
                    message="official and derived views resolved independently",
                    severity="info",
                    node_id=selected.node_id,
                )
            )
        winner = selected
    else:
        if winner.has_official_identity:
            official_id = winner.node_id
        if winner.has_derived_identity:
            derived_id = winner.node_id
        if query.view_kind is AuthorityViewKind.OFFICIAL:
            official_id = winner.node_id
        if query.view_kind is AuthorityViewKind.DERIVED:
            derived_id = winner.node_id

    diagnostics.sort(key=lambda d: (d.code.value, d.node_id or "", d.message))
    return AsOfResolution(
        status=ResolutionStatus.RESOLVED,
        query=query,
        selected_node_id=winner.node_id,
        official_node_id=official_id,
        derived_node_id=derived_id,
        selected_span=winner.span,
        authority_tier=winner.authority_tier,
        competing_sources=(),
        excluded=tuple(excluded),
        diagnostics=tuple(diagnostics),
        applied_edge_ids=applied_edges,
    )


def resolve_mailing_and_response(
    graph: PatentTemporalAuthorityGraph | Mapping[str, Any],
    *,
    mailing_date: date | str,
    response_date: date | str,
    citation_key: str | None = None,
    view_kind: AuthorityViewKind | str = AuthorityViewKind.OFFICIAL,
    **query_kwargs: Any,
) -> DualDateViews:
    """Resolve mailing-date and response-date views independently."""

    mailing_q = AsOfQuery(
        as_of=_require_date(mailing_date, name="mailing_date"),
        citation_key=citation_key,
        view_role=AsOfViewRole.MAILING_DATE,
        view_kind=AuthorityViewKind.coerce(view_kind),
        **{k: v for k, v in query_kwargs.items() if k in AsOfQuery.__dataclass_fields__},
    )
    response_q = AsOfQuery(
        as_of=_require_date(response_date, name="response_date"),
        citation_key=citation_key,
        view_role=AsOfViewRole.RESPONSE_DATE,
        view_kind=AuthorityViewKind.coerce(view_kind),
        **{k: v for k, v in query_kwargs.items() if k in AsOfQuery.__dataclass_fields__},
    )
    return DualDateViews(
        mailing=resolve_as_of(graph, mailing_q),
        response=resolve_as_of(graph, response_q),
    )


class PatentAuthorityRegistry:
    """Temporal authority graph registry with as-of resolution.

    Composes optional :class:`AuthoritySourceRegistry` source records with a
    :class:`PatentTemporalAuthorityGraph`. Connectors feed sources/nodes/edges;
    this class owns deterministic historical replay and dual date views.
    """

    def __init__(
        self,
        *,
        graph_id: str = "patent-authority-registry",
        source_registry: AuthoritySourceRegistry | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self._builder = PatentTemporalAuthorityGraphBuilder(
            graph_id=graph_id, metadata=metadata
        )
        self._source_registry = source_registry or AuthoritySourceRegistry()
        self._frozen: Optional[PatentTemporalAuthorityGraph] = None

    @property
    def source_registry(self) -> AuthoritySourceRegistry:
        return self._source_registry

    def register_source(
        self,
        record: AuthoritySourceRecord | Mapping[str, Any],
        *,
        also_as_node: bool = True,
        overwrite: bool = False,
        **node_kwargs: Any,
    ) -> AuthoritySourceRecord:
        """Register a source record and optionally project it as a graph node."""

        stored = self._source_registry.register(record, overwrite=overwrite)
        if also_as_node:
            self._frozen = None
            self._builder.add_node(
                AuthorityTextNode.from_source_record(stored, **node_kwargs),
                overwrite=overwrite,
            )
        return stored

    def add_node(
        self,
        node: AuthorityTextNode | Mapping[str, Any],
        *,
        overwrite: bool = False,
    ) -> AuthorityTextNode:
        self._frozen = None
        return self._builder.add_node(node, overwrite=overwrite)

    def add_edge(
        self,
        edge: AuthorityTemporalEdge | Mapping[str, Any],
        *,
        overwrite: bool = False,
        require_nodes: bool = True,
    ) -> AuthorityTemporalEdge:
        self._frozen = None
        return self._builder.add_edge(
            edge, overwrite=overwrite, require_nodes=require_nodes
        )

    def graph(self) -> PatentTemporalAuthorityGraph:
        if self._frozen is None:
            self._frozen = self._builder.build()
        return self._frozen

    def freeze(self) -> PatentTemporalAuthorityGraph:
        """Materialize and cache the immutable graph snapshot."""

        self._frozen = self._builder.build()
        return self._frozen

    def validate(self) -> tuple[ResolutionDiagnostic, ...]:
        return validate_temporal_authority_graph(self.graph())

    def resolve(
        self,
        query: AsOfQuery | Mapping[str, Any] | date,
        *,
        citation_key: str | None = None,
    ) -> AsOfResolution:
        return resolve_as_of(self.graph(), query, citation_key=citation_key)

    def resolve_mailing_and_response(
        self,
        *,
        mailing_date: date | str,
        response_date: date | str,
        citation_key: str | None = None,
        view_kind: AuthorityViewKind | str = AuthorityViewKind.OFFICIAL,
        **query_kwargs: Any,
    ) -> DualDateViews:
        return resolve_mailing_and_response(
            self.graph(),
            mailing_date=mailing_date,
            response_date=response_date,
            citation_key=citation_key,
            view_kind=view_kind,
            **query_kwargs,
        )

    def get_node(self, node_id: str) -> AuthorityTextNode:
        node = self.graph().node_by_id.get(node_id)
        if node is None:
            raise UnknownNodeError(f"unknown node_id: {node_id!r}")
        return node

    def nodes(self) -> tuple[AuthorityTextNode, ...]:
        return self.graph().nodes

    def edges(self) -> tuple[AuthorityTemporalEdge, ...]:
        return self.graph().edges

    def __len__(self) -> int:
        return len(self.graph().nodes)

    def __contains__(self, node_id: object) -> bool:
        return isinstance(node_id, str) and node_id in self.graph().node_by_id

    def __iter__(self) -> Iterator[AuthorityTextNode]:
        return iter(self.graph().nodes)

    def to_fixture_dict(self) -> dict[str, Any]:
        """Deterministic fixture payload for historical replay tests."""

        return {
            "graph": self.graph().to_dict(),
            "schema_version": SCHEMA_VERSION,
            "sources": self._source_registry.to_fixture_dict(),
        }

    def to_canonical_json(self) -> str:
        return canonical_json_dumps(self.to_fixture_dict())

    def to_canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_fixture_dict())

    @classmethod
    def from_fixture_dict(cls, value: Mapping[str, Any]) -> "PatentAuthorityRegistry":
        if not isinstance(value, Mapping):
            raise PatentAuthorityRegistryError("fixture payload must be a mapping")
        sources_raw = value.get("sources")
        source_registry = (
            AuthoritySourceRegistry.from_fixture_dict(sources_raw)
            if isinstance(sources_raw, Mapping)
            else AuthoritySourceRegistry()
        )
        graph_raw = value.get("graph") or value
        graph = PatentTemporalAuthorityGraph.from_dict(graph_raw)
        registry = cls(
            graph_id=graph.graph_id,
            source_registry=source_registry,
            metadata=graph.metadata,
        )
        for node in graph.nodes:
            registry.add_node(node, overwrite=True)
        for edge in graph.edges:
            registry.add_edge(edge, overwrite=True, require_nodes=True)
        registry.freeze()
        return registry

    @classmethod
    def from_canonical_json(cls, text: str | bytes) -> "PatentAuthorityRegistry":
        if isinstance(text, bytes):
            text = text.decode("utf-8")
        payload = json.loads(text)
        if not isinstance(payload, Mapping):
            raise PatentAuthorityRegistryError("canonical JSON must decode to a mapping")
        return cls.from_fixture_dict(payload)


# ---------------------------------------------------------------------------
# Fixture recipe helpers (compact, for integration replay)
# ---------------------------------------------------------------------------


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def build_historical_replay_fixture() -> dict[str, Any]:
    """Compact recipe for deterministic historical replay integration tests.

    Scenario (37 C.F.R. § 1.56 duty of disclosure):

    * 2020 official base text effective 2020-01-01.
    * 2022 final-rule amendment effective 2022-06-01 (supersedes base for text).
    * 2023 proposed rule (nonbinding; excluded by default).
    * 2023-09-01 withdrawal of the proposed rule.
    * 2024-01-01 future final rule (excluded before effective date).
    * Parallel eCFR derived presentation of the 2022 text (separate view).
    * MPEP guidance node (lower tier; never outranks regulation).
    * Conflicting official change with distinct content for conflict case.
    """

    builder = PatentTemporalAuthorityGraphBuilder(
        graph_id="patlaw-016-historical-replay",
        metadata={"recipe": "37-cfr-1.56-duty-of-disclosure"},
    )

    base = AuthorityTextNode(
        node_id="cfr-1.56-2020-base",
        citation_key="37-cfr-1.56",
        authority_tier=AuthorityTier.OFFICIAL_BASE,
        collection="CFR",
        citation="37 C.F.R. § 1.56",
        edition="2020",
        version="2020-title37",
        document_type="final_rule",
        text_excerpt="Duty of disclosure (2020 base text).",
        publication_date=date(2019, 12, 15),
        effective_start=date(2020, 1, 1),
        is_binding=True,
        official_artifact=ArtifactIdentity(
            provider="govinfo",
            source_id="CFR-2020-title37-1.56",
            artifact_sha256=_sha("official-2020-base"),
            source_url="https://www.govinfo.gov/content/pkg/CFR-2020-title37-vol1/xml/1.56.xml",
            role=IdentityRole.OFFICIAL_ARTIFACT,
        ),
        span=AuthoritySpan(section="1.56", quote="Duty of disclosure (2020 base text)."),
        verification_state=VerificationState.VERIFIED,
    )
    amend = AuthorityTextNode(
        node_id="cfr-1.56-2022-amendment",
        citation_key="37-cfr-1.56",
        authority_tier=AuthorityTier.OFFICIAL_CHANGE,
        collection="FR",
        citation="37 C.F.R. § 1.56",
        edition="2022",
        version="87-FR-12345",
        document_type="final_rule",
        text_excerpt="Duty of disclosure (2022 amended text).",
        publication_date=date(2022, 5, 1),
        effective_start=date(2022, 6, 1),
        is_binding=True,
        official_artifact=ArtifactIdentity(
            provider="govinfo",
            source_id="FR-2022-05512",
            artifact_sha256=_sha("official-2022-amend"),
            source_url="https://www.govinfo.gov/content/pkg/FR-2022-05-01/pdf/2022-05512.pdf",
            role=IdentityRole.OFFICIAL_ARTIFACT,
        ),
        derived_presentation=ArtifactIdentity(
            provider="ecfr",
            source_id="ecfr-37-1.56-2022",
            artifact_sha256=_sha("derived-2022-ecfr"),
            source_url="https://www.ecfr.gov/current/title-37/section-1.56",
            role=IdentityRole.DERIVED_PRESENTATION,
        ),
        span=AuthoritySpan(
            section="1.56",
            quote="Duty of disclosure (2022 amended text).",
            artifact_sha256=_sha("official-2022-amend"),
        ),
        verification_state=VerificationState.VERIFIED,
    )
    proposed = AuthorityTextNode(
        node_id="cfr-1.56-2023-proposed",
        citation_key="37-cfr-1.56",
        authority_tier=AuthorityTier.UNOFFICIAL_CURRENT,
        collection="FR",
        citation="37 C.F.R. § 1.56",
        version="88-FR-99999",
        document_type="proposed_rule",
        text_excerpt="Duty of disclosure (2023 proposed text — nonbinding).",
        publication_date=date(2023, 3, 1),
        effective_start=date(2023, 3, 1),
        is_binding=False,
        is_proposed=True,
        derived_presentation=ArtifactIdentity(
            provider="federalregister.gov",
            source_id="FR-2023-10001",
            artifact_sha256=_sha("proposed-2023"),
            source_url="https://www.federalregister.gov/documents/2023/03/01/2023-10001",
            role=IdentityRole.DERIVED_PRESENTATION,
        ),
    )
    withdrawal = AuthorityTextNode(
        node_id="cfr-1.56-2023-withdrawal",
        citation_key="37-cfr-1.56",
        authority_tier=AuthorityTier.OFFICIAL_CHANGE,
        collection="FR",
        citation="37 C.F.R. § 1.56",
        version="88-FR-10002",
        document_type="withdrawal",
        text_excerpt="Withdrawal of proposed rule 2023-10001.",
        publication_date=date(2023, 9, 1),
        effective_start=date(2023, 9, 1),
        is_binding=False,
        is_withdrawn=True,
        official_artifact=ArtifactIdentity(
            provider="govinfo",
            source_id="FR-2023-10002",
            artifact_sha256=_sha("official-2023-withdrawal"),
            source_url="https://www.govinfo.gov/content/pkg/FR-2023-09-01/pdf/2023-10002.pdf",
            role=IdentityRole.OFFICIAL_ARTIFACT,
        ),
    )
    future = AuthorityTextNode(
        node_id="cfr-1.56-2024-future",
        citation_key="37-cfr-1.56",
        authority_tier=AuthorityTier.OFFICIAL_CHANGE,
        collection="FR",
        citation="37 C.F.R. § 1.56",
        version="89-FR-20001",
        document_type="final_rule",
        text_excerpt="Duty of disclosure (2024 future-effective text).",
        publication_date=date(2023, 12, 1),
        effective_start=date(2024, 1, 1),
        is_binding=True,
        official_artifact=ArtifactIdentity(
            provider="govinfo",
            source_id="FR-2023-20001",
            artifact_sha256=_sha("official-2024-future"),
            source_url="https://www.govinfo.gov/content/pkg/FR-2023-12-01/pdf/2023-20001.pdf",
            role=IdentityRole.OFFICIAL_ARTIFACT,
        ),
    )
    guidance = AuthorityTextNode(
        node_id="mpep-2001-guidance",
        citation_key="37-cfr-1.56",
        authority_tier=AuthorityTier.GUIDANCE,
        collection="MPEP",
        citation="MPEP § 2001",
        edition="9th-rev-07.2022",
        version="mpep-2001-r07-2022",
        document_type="guidance",
        text_excerpt="MPEP discussion of duty of disclosure (guidance only).",
        publication_date=date(2022, 7, 1),
        effective_start=date(2022, 7, 1),
        is_binding=False,
        official_artifact=ArtifactIdentity(
            provider="uspto",
            source_id="mpep-e9r07-2001",
            artifact_sha256=_sha("mpep-2001"),
            source_url="https://www.uspto.gov/web/offices/pac/mpep/s2001.html",
            role=IdentityRole.OFFICIAL_ARTIFACT,
        ),
    )
    # Second official change with different content same interval → conflict fixture.
    conflict_a = AuthorityTextNode(
        node_id="conflict-statute-a",
        citation_key="35-usc-102-conflict",
        authority_tier=AuthorityTier.OFFICIAL_BASE,
        collection="USCODE",
        citation="35 U.S.C. § 102",
        version="usc-35-102-olrc-a",
        text_excerpt="Conflict variant A.",
        effective_start=date(2021, 1, 1),
        is_binding=True,
        official_artifact=ArtifactIdentity(
            provider="govinfo",
            source_id="USCODE-2021-title35-102-a",
            artifact_sha256=_sha("conflict-a"),
            source_url="https://www.govinfo.gov/content/pkg/USCODE-2021-title35/html/a.html",
            role=IdentityRole.OFFICIAL_ARTIFACT,
        ),
    )
    conflict_b = AuthorityTextNode(
        node_id="conflict-statute-b",
        citation_key="35-usc-102-conflict",
        authority_tier=AuthorityTier.OFFICIAL_BASE,
        collection="USCODE",
        citation="35 U.S.C. § 102",
        version="usc-35-102-olrc-b",
        text_excerpt="Conflict variant B.",
        effective_start=date(2021, 1, 1),
        is_binding=True,
        official_artifact=ArtifactIdentity(
            provider="govinfo",
            source_id="USCODE-2021-title35-102-b",
            artifact_sha256=_sha("conflict-b"),
            source_url="https://www.govinfo.gov/content/pkg/USCODE-2021-title35/html/b.html",
            role=IdentityRole.OFFICIAL_ARTIFACT,
        ),
    )
    # Gap case: interval ends before query.
    gap = AuthorityTextNode(
        node_id="gap-rule-expired",
        citation_key="37-cfr-1.999-gap",
        authority_tier=AuthorityTier.OFFICIAL_BASE,
        collection="CFR",
        citation="37 C.F.R. § 1.999",
        version="gap-2018",
        text_excerpt="Expired temporary rule.",
        effective_start=date(2018, 1, 1),
        effective_end=date(2019, 12, 31),
        is_binding=True,
        official_artifact=ArtifactIdentity(
            provider="govinfo",
            source_id="CFR-2018-1.999",
            artifact_sha256=_sha("gap-2018"),
            source_url="https://www.govinfo.gov/content/pkg/CFR-2018/xml/1.999.xml",
            role=IdentityRole.OFFICIAL_ARTIFACT,
        ),
    )

    for node in (
        base,
        amend,
        proposed,
        withdrawal,
        future,
        guidance,
        conflict_a,
        conflict_b,
        gap,
    ):
        builder.add_node(node)

    builder.add_edge(
        AuthorityTemporalEdge(
            edge_id="edge-2022-amends-base",
            relation=TemporalRelation.AMENDS,
            source_node_id=amend.node_id,
            target_node_id=base.node_id,
            effective_date=date(2022, 6, 1),
            reason="Final rule amends 37 CFR 1.56",
        )
    )
    builder.add_edge(
        AuthorityTemporalEdge(
            edge_id="edge-2023-withdraws-proposed",
            relation=TemporalRelation.WITHDRAWS,
            source_node_id=withdrawal.node_id,
            target_node_id=proposed.node_id,
            effective_date=date(2023, 9, 1),
            reason="Withdrawal of proposed rule",
        )
    )
    builder.add_edge(
        AuthorityTemporalEdge(
            edge_id="edge-2024-supersedes-amend",
            relation=TemporalRelation.SUPERSEDES,
            source_node_id=future.node_id,
            target_node_id=amend.node_id,
            effective_date=date(2024, 1, 1),
            reason="Future final rule supersedes 2022 amendment",
        )
    )

    graph = builder.build()
    return {
        "graph": graph.to_dict(),
        "schema_version": SCHEMA_VERSION,
        "expected": {
            "mailing_2021_06_01": "cfr-1.56-2020-base",
            "mailing_2022_07_01": "cfr-1.56-2022-amendment",
            "response_2023_06_01_excludes_proposed": "cfr-1.56-2022-amendment",
            "as_of_2023_10_01_withdrawn_proposed_excluded": "cfr-1.56-2022-amendment",
            "as_of_2023_12_15_future_excluded": "cfr-1.56-2022-amendment",
            "as_of_2024_02_01_future_selected": "cfr-1.56-2024-future",
            "conflict_citation": "35-usc-102-conflict",
            "gap_citation": "37-cfr-1.999-gap",
            "gap_as_of": "2021-06-01",
        },
    }


__all__ = [
    "SCHEMA_VERSION",
    "AsOfQuery",
    "AsOfResolution",
    "AsOfViewRole",
    "AuthoritySpan",
    "AuthorityTemporalEdge",
    "AuthorityTextNode",
    "AuthorityViewKind",
    "CompetingSource",
    "DiagnosticCode",
    "DualDateViews",
    "DuplicateEdgeError",
    "DuplicateNodeError",
    "ExcludedCandidate",
    "ExclusionReason",
    "PatentAuthorityRegistry",
    "PatentAuthorityRegistryError",
    "PatentTemporalAuthorityGraph",
    "PatentTemporalAuthorityGraphBuilder",
    "ResolutionDiagnostic",
    "ResolutionStatus",
    "TemporalRelation",
    "UnknownNodeError",
    "build_historical_replay_fixture",
    "resolve_as_of",
    "resolve_mailing_and_response",
    "validate_temporal_authority_graph",
]
