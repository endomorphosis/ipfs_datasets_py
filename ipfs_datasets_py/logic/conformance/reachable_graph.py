"""Sparse reachable domain-to-provider capability graph (LFP2-003).

``ReachableCapabilityGraph@1`` replaces flat Cartesian interpretation of the
capability matrix with a sparse join:

    domain view -> typed family/profile -> translation path
        -> provider feature -> evidence kind -> lifecycle -> authority ceiling

Every **admitted** route is explainable. Every **unreachable** coordinate is
recorded as an exclusion with a typed reason. Full Cartesian *unsupported*
cells are never work items.

This module is side-effect-free at import time: it never probes PATH, installs
packages, starts solvers, or upgrades authority. Availability remains a
declaration posture inherited from the sealed capability matrix.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.logic.conformance.matrix import (
    DEFAULT_MATRIX,
    AuthorityCeiling,
    AvailabilityStatus,
    CapabilityCell,
    LogicCapabilityMatrix,
    SupportStatus,
    build_default_matrix,
    cell_id as matrix_cell_id,
)
from ipfs_datasets_py.logic.families.registry import (
    DEFAULT_REGISTRY,
    LogicFamilyRegistry,
)

# ---------------------------------------------------------------------------
# Interface / schema
# ---------------------------------------------------------------------------

REACHABLE_CAPABILITY_GRAPH_INTERFACE: Final = "ReachableCapabilityGraph@1"
REACHABLE_CAPABILITY_GRAPH_SCHEMA: Final = "logic-reachable-capability-graph/v1"
ROUTE_SCHEMA: Final = "logic-reachable-capability-route/v1"
EXCLUSION_SCHEMA: Final = "logic-reachable-capability-exclusion/v1"
EXPLANATION_SCHEMA: Final = "logic-reachable-capability-explanation/v1"
GRAPH_VERSION: Final = "1.0.0"
TASK_ID: Final = "LFP2-003"
GOAL_ID: Final = "LFP2-G010"
PROGRAM_ID: Final = "ipfs-datasets-logic-family-parser-v2"

DEFAULT_BASELINE_RELATIVE_PATH: Final = (
    "docs/architecture/logic/logic_parser_v2_baseline/reachable_capability_graph.json"
)
MATERIALIZATION_TARGET: Final = (
    "ipfs_datasets_py.logic.conformance.reachable_graph:build_default_graph"
)

# Support statuses that admit a reachable route (not full Cartesian).
ADMITTED_SUPPORT_STATUSES: Final[frozenset[SupportStatus]] = frozenset(
    {
        SupportStatus.NATIVE,
        SupportStatus.TRANSLATED,
        SupportStatus.APPROXIMATE,
        SupportStatus.BOUNDED,
        SupportStatus.ADVISORY,
    }
)

# Evidence subset required by LFP2-003 acceptance surface.
REQUIRED_EVIDENCE_DIMENSIONS: Final[tuple[str, ...]] = (
    "domain",
    "view",
    "family",
    "profile",
    "translation",
    "provider",
    "evidence",
    "reachability",
)

LIFECYCLE_STAGES: Final[tuple[str, ...]] = (
    "declared",
    "parsed",
    "elaborated",
    "translatable",
    "compilable",
    "executable",
    "replayed",
    "independently_validated",
)


class ReachableCapabilityGraphError(ValueError):
    """Raised when the reachable capability graph is malformed or contradictory."""


class RouteDisposition(StrEnum):
    """Whether a matrix coordinate is admitted as a reachable route."""

    ADMITTED = "admitted"
    EXCLUDED = "excluded"


class ExclusionReason(StrEnum):
    """Typed reason a coordinate is unreachable (never silent)."""

    NO_NATIVE_OR_TRANSLATED_ROUTE = "no_native_or_translated_route"
    PROVIDER_FAMILY_INCOMPATIBLE = "provider_family_incompatible"
    SOURCE_MISSING = "source_missing"
    DECLARATION_ONLY_FAMILY = "declaration_only_family"
    DECLARATION_ONLY_DOMAIN = "declaration_only_domain"
    UNKNOWN_CAPABILITY = "unknown_capability"
    ADVISORY_SCOPE_MISMATCH = "advisory_scope_mismatch"
    UNSUPPORTED_SUPPORT = "unsupported_support"


class TranslationPathKind(StrEnum):
    """How a domain-family reaches a provider feature."""

    NATIVE = "native"
    TRANSLATED = "translated"
    APPROXIMATE = "approximate"
    BOUNDED = "bounded"
    ADVISORY = "advisory"
    IDENTITY = "identity"


class EvidenceKind(StrEnum):
    """Evidence kind claimed by an admitted route (static, not a proof)."""

    NATIVE_SOLVER = "native_solver"
    TRANSLATION_RECEIPT = "translation_receipt"
    BOUNDED_CHECK = "bounded_check"
    APPROXIMATE_PROTOCOL = "approximate_protocol"
    ADVISORY_CANDIDATE = "advisory_candidate"
    AUTHORIZATION_PROFILE = "authorization_profile"
    KERNEL_TARGET = "kernel_target"
    FINITE_TRACE = "finite_trace"
    DECLARATION = "declaration"


class LifecycleStage(StrEnum):
    """Static lifecycle ceiling for a route (not a live probe result)."""

    DECLARED = "declared"
    PARSED = "parsed"
    ELABORATED = "elaborated"
    TRANSLATABLE = "translatable"
    COMPILABLE = "compilable"
    EXECUTABLE = "executable"
    REPLAYED = "replayed"
    INDEPENDENTLY_VALIDATED = "independently_validated"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ReachableCapabilityGraphError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if "\x00" in value:
        raise ReachableCapabilityGraphError(
            f"{field_name} must not contain NUL bytes"
        )
    return value


def _identifier(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if any(character.isspace() for character in result):
        raise ReachableCapabilityGraphError(
            f"{field_name} must not contain whitespace; got {result!r}"
        )
    return result


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise ReachableCapabilityGraphError(
            f"{field_name} must be one of {choices}"
        ) from error


def _bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ReachableCapabilityGraphError(f"{field_name} must be a boolean")
    return value


def _stable_digest(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def route_id(
    domain_id: str,
    formal_view_id: str,
    family_id: str,
    profile_id: str,
    provider_id: str,
) -> str:
    """Stable admitted-route identity (matches matrix cell coordinates)."""

    return matrix_cell_id(
        domain_id, formal_view_id, family_id, profile_id, provider_id
    )


# ---------------------------------------------------------------------------
# Core records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RouteExplanation:
    """Explainable join for one admitted domain-to-provider route.

    Every field is required so an admitted route is never an opaque success.
    """

    domain_id: str
    formal_view_id: str
    family_id: str
    profile_id: str
    translation_path_kind: TranslationPathKind
    translation_path_id: str
    provider_id: str
    provider_feature: str
    evidence_kind: EvidenceKind
    lifecycle_stage: LifecycleStage
    authority_ceiling: AuthorityCeiling
    support: SupportStatus
    rationale: str
    schema_version: str = EXPLANATION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "domain_id", _identifier(self.domain_id, "domain_id")
        )
        object.__setattr__(
            self,
            "formal_view_id",
            _identifier(self.formal_view_id, "formal_view_id"),
        )
        object.__setattr__(
            self, "family_id", _identifier(self.family_id, "family_id")
        )
        object.__setattr__(
            self,
            "profile_id",
            _identifier(self.profile_id or "default", "profile_id"),
        )
        object.__setattr__(
            self,
            "translation_path_kind",
            _enum(
                self.translation_path_kind,
                TranslationPathKind,
                "translation_path_kind",
            ),
        )
        object.__setattr__(
            self,
            "translation_path_id",
            _identifier(self.translation_path_id, "translation_path_id"),
        )
        object.__setattr__(
            self, "provider_id", _identifier(self.provider_id, "provider_id")
        )
        object.__setattr__(
            self,
            "provider_feature",
            _identifier(self.provider_feature, "provider_feature"),
        )
        object.__setattr__(
            self,
            "evidence_kind",
            _enum(self.evidence_kind, EvidenceKind, "evidence_kind"),
        )
        object.__setattr__(
            self,
            "lifecycle_stage",
            _enum(self.lifecycle_stage, LifecycleStage, "lifecycle_stage"),
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            _enum(self.authority_ceiling, AuthorityCeiling, "authority_ceiling"),
        )
        object.__setattr__(
            self, "support", _enum(self.support, SupportStatus, "support")
        )
        object.__setattr__(
            self, "rationale", _text(self.rationale, "rationale")
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling.value,
            "domain_id": self.domain_id,
            "evidence_kind": self.evidence_kind.value,
            "family_id": self.family_id,
            "formal_view_id": self.formal_view_id,
            "lifecycle_stage": self.lifecycle_stage.value,
            "profile_id": self.profile_id,
            "provider_feature": self.provider_feature,
            "provider_id": self.provider_id,
            "rationale": self.rationale,
            "schema_version": self.schema_version,
            "support": self.support.value,
            "translation_path_id": self.translation_path_id,
            "translation_path_kind": self.translation_path_kind.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RouteExplanation:
        if not isinstance(value, Mapping):
            raise ReachableCapabilityGraphError("explanation must be an object")
        return cls(
            domain_id=str(value.get("domain_id", "")),
            formal_view_id=str(value.get("formal_view_id", "")),
            family_id=str(value.get("family_id", "")),
            profile_id=str(value.get("profile_id", "default") or "default"),
            translation_path_kind=str(
                value.get("translation_path_kind", TranslationPathKind.NATIVE.value)
            ),
            translation_path_id=str(value.get("translation_path_id", "")),
            provider_id=str(value.get("provider_id", "")),
            provider_feature=str(value.get("provider_feature", "")),
            evidence_kind=str(
                value.get("evidence_kind", EvidenceKind.DECLARATION.value)
            ),
            lifecycle_stage=str(
                value.get("lifecycle_stage", LifecycleStage.DECLARED.value)
            ),
            authority_ceiling=str(
                value.get("authority_ceiling", AuthorityCeiling.NONE.value)
            ),
            support=str(value.get("support", SupportStatus.UNKNOWN.value)),
            rationale=str(value.get("rationale", "")),
            schema_version=str(value.get("schema_version", EXPLANATION_SCHEMA)),
        )


@dataclass(frozen=True, slots=True)
class AdmittedRoute:
    """One sparse, explainable domain-to-provider capability route."""

    route_id: str
    domain_id: str
    formal_view_id: str
    family_id: str
    profile_id: str
    provider_id: str
    support: SupportStatus
    availability: AvailabilityStatus
    authority_ceiling: AuthorityCeiling
    explanation: RouteExplanation
    work_eligible: bool
    unimplemented: bool = False
    notes: str = ""
    evidence_paths: tuple[str, ...] = ()
    disposition: RouteDisposition = RouteDisposition.ADMITTED
    schema_version: str = ROUTE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "route_id", _identifier(self.route_id, "route_id")
        )
        object.__setattr__(
            self, "domain_id", _identifier(self.domain_id, "domain_id")
        )
        object.__setattr__(
            self,
            "formal_view_id",
            _identifier(self.formal_view_id, "formal_view_id"),
        )
        object.__setattr__(
            self, "family_id", _identifier(self.family_id, "family_id")
        )
        object.__setattr__(
            self,
            "profile_id",
            _identifier(self.profile_id or "default", "profile_id"),
        )
        object.__setattr__(
            self, "provider_id", _identifier(self.provider_id, "provider_id")
        )
        object.__setattr__(
            self, "support", _enum(self.support, SupportStatus, "support")
        )
        object.__setattr__(
            self,
            "availability",
            _enum(self.availability, AvailabilityStatus, "availability"),
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            _enum(self.authority_ceiling, AuthorityCeiling, "authority_ceiling"),
        )
        if not isinstance(self.explanation, RouteExplanation):
            raise ReachableCapabilityGraphError(
                "admitted route requires a RouteExplanation"
            )
        # Explanation must match route coordinates.
        if (
            self.explanation.domain_id != self.domain_id
            or self.explanation.formal_view_id != self.formal_view_id
            or self.explanation.family_id != self.family_id
            or self.explanation.profile_id != self.profile_id
            or self.explanation.provider_id != self.provider_id
        ):
            raise ReachableCapabilityGraphError(
                f"route {self.route_id!r} explanation coordinates disagree"
            )
        if self.support not in ADMITTED_SUPPORT_STATUSES:
            raise ReachableCapabilityGraphError(
                f"admitted route {self.route_id!r} has non-admitted support "
                f"{self.support.value!r}"
            )
        if self.explanation.support is not self.support:
            raise ReachableCapabilityGraphError(
                f"route {self.route_id!r} explanation support disagrees with route"
            )
        if self.explanation.authority_ceiling is not self.authority_ceiling:
            raise ReachableCapabilityGraphError(
                f"route {self.route_id!r} explanation authority disagrees with route"
            )
        object.__setattr__(
            self, "work_eligible", _bool(self.work_eligible, "work_eligible")
        )
        object.__setattr__(
            self, "unimplemented", _bool(self.unimplemented, "unimplemented")
        )
        object.__setattr__(
            self, "notes", _text(self.notes, "notes") if self.notes else ""
        )
        if isinstance(self.evidence_paths, (str, bytes, bytearray)) or not isinstance(
            self.evidence_paths, Sequence
        ):
            raise ReachableCapabilityGraphError("evidence_paths must be a sequence")
        paths = tuple(
            _text(item, "evidence_paths item").replace("\\", "/")
            for item in self.evidence_paths
        )
        if len(set(paths)) != len(paths):
            raise ReachableCapabilityGraphError(
                "evidence_paths must not contain duplicates"
            )
        object.__setattr__(self, "evidence_paths", tuple(sorted(paths)))
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, RouteDisposition, "disposition"),
        )
        if self.disposition is not RouteDisposition.ADMITTED:
            raise ReachableCapabilityGraphError(
                "AdmittedRoute disposition must be admitted"
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        expected = route_id(
            self.domain_id,
            self.formal_view_id,
            self.family_id,
            self.profile_id,
            self.provider_id,
        )
        if self.route_id != expected:
            raise ReachableCapabilityGraphError(
                f"route_id {self.route_id!r} does not match coordinates {expected!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling.value,
            "availability": self.availability.value,
            "disposition": self.disposition.value,
            "domain_id": self.domain_id,
            "evidence_paths": list(self.evidence_paths),
            "explanation": self.explanation.to_dict(),
            "family_id": self.family_id,
            "formal_view_id": self.formal_view_id,
            "notes": self.notes,
            "profile_id": self.profile_id,
            "provider_id": self.provider_id,
            "route_id": self.route_id,
            "schema_version": self.schema_version,
            "support": self.support.value,
            "unimplemented": self.unimplemented,
            "work_eligible": self.work_eligible,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AdmittedRoute:
        if not isinstance(value, Mapping):
            raise ReachableCapabilityGraphError("route must be an object")
        explanation_raw = value.get("explanation")
        if not isinstance(explanation_raw, Mapping):
            raise ReachableCapabilityGraphError("route explanation must be an object")
        return cls(
            route_id=str(value.get("route_id", "")),
            domain_id=str(value.get("domain_id", "")),
            formal_view_id=str(value.get("formal_view_id", "")),
            family_id=str(value.get("family_id", "")),
            profile_id=str(value.get("profile_id", "default") or "default"),
            provider_id=str(value.get("provider_id", "")),
            support=str(value.get("support", SupportStatus.UNKNOWN.value)),
            availability=str(
                value.get("availability", AvailabilityStatus.UNKNOWN.value)
            ),
            authority_ceiling=str(
                value.get("authority_ceiling", AuthorityCeiling.UNKNOWN.value)
            ),
            explanation=RouteExplanation.from_dict(explanation_raw),
            work_eligible=bool(value.get("work_eligible", False)),
            unimplemented=bool(value.get("unimplemented", False)),
            notes=str(value.get("notes", "")),
            evidence_paths=tuple(value.get("evidence_paths", ())),
            disposition=str(
                value.get("disposition", RouteDisposition.ADMITTED.value)
            ),
            schema_version=str(value.get("schema_version", ROUTE_SCHEMA)),
        )


@dataclass(frozen=True, slots=True)
class ExcludedCell:
    """One unreachable coordinate excluded with a typed reason.

    Cartesian *unsupported* exclusions are never work items
    (``work_eligible`` is always false for unsupported support).
    """

    cell_id: str
    domain_id: str
    formal_view_id: str
    family_id: str
    profile_id: str
    provider_id: str
    support: SupportStatus
    reason: ExclusionReason
    detail: str
    work_eligible: bool = False
    availability: AvailabilityStatus = AvailabilityStatus.DECLARED
    authority_ceiling: AuthorityCeiling = AuthorityCeiling.NONE
    disposition: RouteDisposition = RouteDisposition.EXCLUDED
    schema_version: str = EXCLUSION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "cell_id", _identifier(self.cell_id, "cell_id"))
        object.__setattr__(
            self, "domain_id", _identifier(self.domain_id, "domain_id")
        )
        object.__setattr__(
            self,
            "formal_view_id",
            _identifier(self.formal_view_id, "formal_view_id"),
        )
        object.__setattr__(
            self, "family_id", _identifier(self.family_id, "family_id")
        )
        object.__setattr__(
            self,
            "profile_id",
            _identifier(self.profile_id or "default", "profile_id"),
        )
        object.__setattr__(
            self, "provider_id", _identifier(self.provider_id, "provider_id")
        )
        object.__setattr__(
            self, "support", _enum(self.support, SupportStatus, "support")
        )
        object.__setattr__(
            self, "reason", _enum(self.reason, ExclusionReason, "reason")
        )
        object.__setattr__(self, "detail", _text(self.detail, "detail"))
        object.__setattr__(
            self, "work_eligible", _bool(self.work_eligible, "work_eligible")
        )
        object.__setattr__(
            self,
            "availability",
            _enum(self.availability, AvailabilityStatus, "availability"),
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            _enum(self.authority_ceiling, AuthorityCeiling, "authority_ceiling"),
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, RouteDisposition, "disposition"),
        )
        if self.disposition is not RouteDisposition.EXCLUDED:
            raise ReachableCapabilityGraphError(
                "ExcludedCell disposition must be excluded"
            )
        # Fail closed: unsupported Cartesian cells never become work.
        if (
            self.support is SupportStatus.UNSUPPORTED
            and self.work_eligible
        ):
            raise ReachableCapabilityGraphError(
                f"unsupported exclusion {self.cell_id!r} cannot be work-eligible"
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        expected = route_id(
            self.domain_id,
            self.formal_view_id,
            self.family_id,
            self.profile_id,
            self.provider_id,
        )
        if self.cell_id != expected:
            raise ReachableCapabilityGraphError(
                f"cell_id {self.cell_id!r} does not match coordinates {expected!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling.value,
            "availability": self.availability.value,
            "cell_id": self.cell_id,
            "detail": self.detail,
            "disposition": self.disposition.value,
            "domain_id": self.domain_id,
            "family_id": self.family_id,
            "formal_view_id": self.formal_view_id,
            "profile_id": self.profile_id,
            "provider_id": self.provider_id,
            "reason": self.reason.value,
            "schema_version": self.schema_version,
            "support": self.support.value,
            "work_eligible": self.work_eligible,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ExcludedCell:
        if not isinstance(value, Mapping):
            raise ReachableCapabilityGraphError("exclusion must be an object")
        return cls(
            cell_id=str(value.get("cell_id", "")),
            domain_id=str(value.get("domain_id", "")),
            formal_view_id=str(value.get("formal_view_id", "")),
            family_id=str(value.get("family_id", "")),
            profile_id=str(value.get("profile_id", "default") or "default"),
            provider_id=str(value.get("provider_id", "")),
            support=str(value.get("support", SupportStatus.UNSUPPORTED.value)),
            reason=str(
                value.get(
                    "reason", ExclusionReason.NO_NATIVE_OR_TRANSLATED_ROUTE.value
                )
            ),
            detail=str(value.get("detail", "")),
            work_eligible=bool(value.get("work_eligible", False)),
            availability=str(
                value.get("availability", AvailabilityStatus.DECLARED.value)
            ),
            authority_ceiling=str(
                value.get("authority_ceiling", AuthorityCeiling.NONE.value)
            ),
            disposition=str(
                value.get("disposition", RouteDisposition.EXCLUDED.value)
            ),
            schema_version=str(value.get("schema_version", EXCLUSION_SCHEMA)),
        )


@dataclass(frozen=True, slots=True)
class ReachableCapabilityGraph:
    """Versioned sparse reachable capability graph.

    Stores admitted routes and typed exclusions. The Cartesian product of
    domain views × providers is never treated as the work surface.
    """

    routes: tuple[AdmittedRoute, ...]
    exclusions: tuple[ExcludedCell, ...]
    version: str = GRAPH_VERSION
    schema_version: str = REACHABLE_CAPABILITY_GRAPH_SCHEMA
    interface: str = REACHABLE_CAPABILITY_GRAPH_INTERFACE
    description: str = (
        "Sparse reachable domain-view-family/profile-translation-provider "
        "capability graph. Admitted routes are explainable; unreachable cells "
        "are excluded with typed reasons; Cartesian unsupported cells are not work."
    )
    notes: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    cartesian_cell_count: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.routes, (str, bytes, bytearray)) or not isinstance(
            self.routes, Sequence
        ):
            raise ReachableCapabilityGraphError("routes must be a sequence")
        routes = tuple(
            item if isinstance(item, AdmittedRoute) else AdmittedRoute.from_dict(item)
            for item in self.routes
        )
        routes = tuple(sorted(routes, key=lambda item: item.route_id))
        route_ids = [item.route_id for item in routes]
        if len(set(route_ids)) != len(route_ids):
            raise ReachableCapabilityGraphError("routes must have unique route_id values")
        object.__setattr__(self, "routes", routes)

        if isinstance(self.exclusions, (str, bytes, bytearray)) or not isinstance(
            self.exclusions, Sequence
        ):
            raise ReachableCapabilityGraphError("exclusions must be a sequence")
        exclusions = tuple(
            item if isinstance(item, ExcludedCell) else ExcludedCell.from_dict(item)
            for item in self.exclusions
        )
        exclusions = tuple(sorted(exclusions, key=lambda item: item.cell_id))
        exclusion_ids = [item.cell_id for item in exclusions]
        if len(set(exclusion_ids)) != len(exclusion_ids):
            raise ReachableCapabilityGraphError(
                "exclusions must have unique cell_id values"
            )
        object.__setattr__(self, "exclusions", exclusions)

        # No coordinate may appear as both admitted and excluded.
        overlap = set(route_ids) & set(exclusion_ids)
        if overlap:
            sample = sorted(overlap)[0]
            raise ReachableCapabilityGraphError(
                f"coordinate {sample!r} is both admitted and excluded"
            )

        object.__setattr__(self, "version", _text(self.version, "version"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        object.__setattr__(self, "interface", _text(self.interface, "interface"))
        object.__setattr__(
            self,
            "description",
            _text(self.description, "description") if self.description else "",
        )
        object.__setattr__(
            self, "notes", _text(self.notes, "notes") if self.notes else ""
        )
        if not isinstance(self.metadata, Mapping):
            raise ReachableCapabilityGraphError("metadata must be a mapping")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        if not isinstance(self.cartesian_cell_count, int) or self.cartesian_cell_count < 0:
            raise ReachableCapabilityGraphError(
                "cartesian_cell_count must be a non-negative integer"
            )
        expected_total = len(routes) + len(exclusions)
        if self.cartesian_cell_count and self.cartesian_cell_count != expected_total:
            raise ReachableCapabilityGraphError(
                "cartesian_cell_count must equal admitted + excluded counts "
                f"({self.cartesian_cell_count} != {expected_total})"
            )
        # Every admitted route must be explainable (enforced by construction).
        for route in routes:
            if not route.explanation.rationale:
                raise ReachableCapabilityGraphError(
                    f"admitted route {route.route_id!r} lacks explanation rationale"
                )
        # Every exclusion must carry a typed reason (enum already required).
        for exclusion in exclusions:
            if not exclusion.detail:
                raise ReachableCapabilityGraphError(
                    f"exclusion {exclusion.cell_id!r} lacks detail"
                )
        # Hard acceptance: unsupported Cartesian cells never become work.
        for exclusion in exclusions:
            if (
                exclusion.support is SupportStatus.UNSUPPORTED
                and exclusion.work_eligible
            ):
                raise ReachableCapabilityGraphError(
                    f"unsupported exclusion {exclusion.cell_id!r} is work-eligible"
                )

    @property
    def admitted_count(self) -> int:
        return len(self.routes)

    @property
    def excluded_count(self) -> int:
        return len(self.exclusions)

    def work_items(self) -> tuple[AdmittedRoute, ...]:
        """Admitted routes that remain eligible for later implementation work."""

        return tuple(item for item in self.routes if item.work_eligible)

    def unsupported_exclusions(self) -> tuple[ExcludedCell, ...]:
        return tuple(
            item
            for item in self.exclusions
            if item.support is SupportStatus.UNSUPPORTED
        )

    def exclusion_reason_histogram(self) -> Mapping[str, int]:
        counts: dict[str, int] = {reason.value: 0 for reason in ExclusionReason}
        for item in self.exclusions:
            counts[item.reason.value] += 1
        return MappingProxyType(counts)

    def support_histogram_routes(self) -> Mapping[str, int]:
        counts: dict[str, int] = {status.value: 0 for status in SupportStatus}
        for item in self.routes:
            counts[item.support.value] += 1
        return MappingProxyType(counts)

    def support_histogram_exclusions(self) -> Mapping[str, int]:
        counts: dict[str, int] = {status.value: 0 for status in SupportStatus}
        for item in self.exclusions:
            counts[item.support.value] += 1
        return MappingProxyType(counts)

    def routes_for_domain(self, domain_id: str) -> tuple[AdmittedRoute, ...]:
        canonical = _identifier(domain_id, "domain_id")
        return tuple(item for item in self.routes if item.domain_id == canonical)

    def routes_for_provider(self, provider_id: str) -> tuple[AdmittedRoute, ...]:
        canonical = _identifier(provider_id, "provider_id")
        return tuple(item for item in self.routes if item.provider_id == canonical)

    def get_route(self, route_key: str) -> AdmittedRoute | None:
        for item in self.routes:
            if item.route_id == route_key:
                return item
        return None

    def get_exclusion(self, cell_key: str) -> ExcludedCell | None:
        for item in self.exclusions:
            if item.cell_id == cell_key:
                return item
        return None

    def summary(self) -> dict[str, Any]:
        work = self.work_items()
        unsupported = self.unsupported_exclusions()
        return {
            "admitted_count": self.admitted_count,
            "cartesian_cell_count": self.cartesian_cell_count
            or (self.admitted_count + self.excluded_count),
            "excluded_count": self.excluded_count,
            "exclusion_reason_histogram": dict(self.exclusion_reason_histogram()),
            "route_support_histogram": dict(self.support_histogram_routes()),
            "exclusion_support_histogram": dict(self.support_histogram_exclusions()),
            "sparsity_ratio": (
                round(self.admitted_count / (self.admitted_count + self.excluded_count), 6)
                if (self.admitted_count + self.excluded_count)
                else 0.0
            ),
            "unsupported_exclusion_count": len(unsupported),
            "unsupported_work_eligible_count": sum(
                1 for item in unsupported if item.work_eligible
            ),
            "work_eligible_count": len(work),
            "work_eligible_route_ids": [item.route_id for item in work],
        }

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "cartesian_cell_count": self.cartesian_cell_count
            or (self.admitted_count + self.excluded_count),
            "description": self.description,
            "exclusions": [item.to_dict() for item in self.exclusions],
            "interface": self.interface,
            "metadata": dict(self.metadata),
            "notes": self.notes,
            "routes": [item.to_dict() for item in self.routes],
            "schema_version": self.schema_version,
            "summary": self.summary(),
            "version": self.version,
        }
        payload["content_digest"] = f"sha256:{_stable_digest(payload)}"
        return payload

    def content_digest(self) -> str:
        body = self.to_dict()
        body.pop("content_digest", None)
        return f"sha256:{_stable_digest(body)}"

    def to_baseline_dict(self) -> dict[str, Any]:
        """Baseline JSON body with materialization pointer and task metadata."""

        body = self.to_dict()
        body["materialization"] = MATERIALIZATION_TARGET
        body["task_id"] = TASK_ID
        body["goal_id"] = GOAL_ID
        body["program_id"] = PROGRAM_ID
        body["required_evidence_dimensions"] = list(REQUIRED_EVIDENCE_DIMENSIONS)
        body["lifecycle_stages"] = list(LIFECYCLE_STAGES)
        body["admitted_support_statuses"] = sorted(
            status.value for status in ADMITTED_SUPPORT_STATUSES
        )
        digest_body = dict(body)
        digest_body.pop("content_digest", None)
        body["content_digest"] = f"sha256:{_stable_digest(digest_body)}"
        return body

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ReachableCapabilityGraph:
        if not isinstance(value, Mapping):
            raise ReachableCapabilityGraphError("graph must be an object")
        return cls(
            routes=tuple(
                AdmittedRoute.from_dict(item) for item in value.get("routes", ())
            ),
            exclusions=tuple(
                ExcludedCell.from_dict(item) for item in value.get("exclusions", ())
            ),
            version=str(value.get("version", GRAPH_VERSION)),
            schema_version=str(
                value.get("schema_version", REACHABLE_CAPABILITY_GRAPH_SCHEMA)
            ),
            interface=str(
                value.get("interface", REACHABLE_CAPABILITY_GRAPH_INTERFACE)
            ),
            description=str(value.get("description", "")),
            notes=str(value.get("notes", "")),
            metadata=dict(value.get("metadata", {}) or {}),
            cartesian_cell_count=int(value.get("cartesian_cell_count", 0) or 0),
        )


# ---------------------------------------------------------------------------
# Classification / materialization
# ---------------------------------------------------------------------------


def _registry_translation_id(
    family_id: str,
    provider_native_families: frozenset[str],
    registry: LogicFamilyRegistry,
) -> str | None:
    """Return a reviewed translation edge id when family maps into provider natives."""

    for descriptor in registry.translations.values():
        if (
            descriptor.source_family_id == family_id
            and descriptor.target_family_id in provider_native_families
        ):
            return descriptor.translation_id
    return None


def _translation_path(
    cell: CapabilityCell,
    *,
    provider_native_families: frozenset[str],
    registry: LogicFamilyRegistry,
) -> tuple[TranslationPathKind, str]:
    """Derive translation path kind and stable path id for an admitted cell."""

    if cell.support is SupportStatus.NATIVE:
        return (
            TranslationPathKind.NATIVE,
            f"native:{cell.family_id}->{cell.provider_id}",
        )
    if cell.support is SupportStatus.TRANSLATED:
        reviewed = _registry_translation_id(
            cell.family_id, provider_native_families, registry
        )
        if reviewed:
            return TranslationPathKind.TRANSLATED, reviewed
        return (
            TranslationPathKind.TRANSLATED,
            f"translated:{cell.family_id}->{cell.provider_id}",
        )
    if cell.support is SupportStatus.APPROXIMATE:
        return (
            TranslationPathKind.APPROXIMATE,
            f"approximate:{cell.family_id}->{cell.provider_id}",
        )
    if cell.support is SupportStatus.BOUNDED:
        return (
            TranslationPathKind.BOUNDED,
            f"bounded:{cell.family_id}->{cell.provider_id}",
        )
    if cell.support is SupportStatus.ADVISORY:
        return (
            TranslationPathKind.ADVISORY,
            f"advisory:{cell.family_id}->{cell.provider_id}",
        )
    raise ReachableCapabilityGraphError(
        f"cannot build translation path for non-admitted support {cell.support.value}"
    )


def _provider_feature(cell: CapabilityCell) -> str:
    """Stable provider feature tag for the admitted edge."""

    if cell.support is SupportStatus.ADVISORY:
        return f"{cell.provider_id}:advisory"
    if cell.authority_ceiling is AuthorityCeiling.KERNEL:
        return f"{cell.provider_id}:kernel"
    if cell.authority_ceiling is AuthorityCeiling.AUTHORIZATION_PROFILE:
        return f"{cell.provider_id}:authorization"
    if cell.authority_ceiling is AuthorityCeiling.FINITE_TRACE:
        return f"{cell.provider_id}:finite_trace"
    if cell.authority_ceiling is AuthorityCeiling.PROTOCOL_SYMBOLIC:
        return f"{cell.provider_id}:protocol_symbolic"
    if cell.support is SupportStatus.BOUNDED:
        return f"{cell.provider_id}:bounded"
    if cell.support is SupportStatus.APPROXIMATE:
        return f"{cell.provider_id}:approximate"
    if cell.support is SupportStatus.TRANSLATED:
        return f"{cell.provider_id}:via_translation"
    return f"{cell.provider_id}:native"


def _evidence_kind(cell: CapabilityCell) -> EvidenceKind:
    if cell.authority_ceiling is AuthorityCeiling.KERNEL:
        return EvidenceKind.KERNEL_TARGET
    if cell.authority_ceiling is AuthorityCeiling.AUTHORIZATION_PROFILE:
        return EvidenceKind.AUTHORIZATION_PROFILE
    if cell.authority_ceiling is AuthorityCeiling.FINITE_TRACE:
        return EvidenceKind.FINITE_TRACE
    if cell.support is SupportStatus.TRANSLATED:
        return EvidenceKind.TRANSLATION_RECEIPT
    if cell.support is SupportStatus.BOUNDED:
        return EvidenceKind.BOUNDED_CHECK
    if cell.support is SupportStatus.APPROXIMATE:
        return EvidenceKind.APPROXIMATE_PROTOCOL
    if cell.support is SupportStatus.ADVISORY:
        return EvidenceKind.ADVISORY_CANDIDATE
    if cell.support is SupportStatus.NATIVE:
        return EvidenceKind.NATIVE_SOLVER
    return EvidenceKind.DECLARATION


def _lifecycle_stage(cell: CapabilityCell) -> LifecycleStage:
    """Static lifecycle ceiling for an admitted route (not live execution)."""

    if cell.support is SupportStatus.TRANSLATED:
        # Translated routes are admitted at the translatable stage; closing
        # the edge may later raise lifecycle through other audits.
        return LifecycleStage.TRANSLATABLE
    if cell.support is SupportStatus.ADVISORY:
        return LifecycleStage.DECLARED
    if cell.support in {
        SupportStatus.NATIVE,
        SupportStatus.BOUNDED,
        SupportStatus.APPROXIMATE,
    }:
        # Provider compilers/runners are declared in the matrix; live
        # executable status remains owned by claim-runtime audit / probes.
        return LifecycleStage.COMPILABLE
    return LifecycleStage.DECLARED


def _exclusion_reason(cell: CapabilityCell) -> ExclusionReason:
    if cell.domain_id == "ui_ux_ir" or (
        cell.availability is AvailabilityStatus.SOURCE_MISSING
        and cell.support is SupportStatus.DECLARATION_ONLY
    ):
        if cell.domain_id == "ui_ux_ir":
            return ExclusionReason.DECLARATION_ONLY_DOMAIN
        return ExclusionReason.SOURCE_MISSING
    if cell.support is SupportStatus.DECLARATION_ONLY:
        return ExclusionReason.DECLARATION_ONLY_FAMILY
    if cell.support is SupportStatus.UNKNOWN:
        return ExclusionReason.UNKNOWN_CAPABILITY
    if cell.support is SupportStatus.UNSUPPORTED:
        # Distinguish advisor scope mismatch when notes mention it.
        notes = (cell.notes or "").lower()
        if "advisor" in notes or "advisory" in notes:
            return ExclusionReason.ADVISORY_SCOPE_MISMATCH
        if "no native or reviewed translated route" in notes:
            return ExclusionReason.NO_NATIVE_OR_TRANSLATED_ROUTE
        return ExclusionReason.PROVIDER_FAMILY_INCOMPATIBLE
    return ExclusionReason.UNSUPPORTED_SUPPORT


def _is_admitted(cell: CapabilityCell) -> bool:
    return cell.support in ADMITTED_SUPPORT_STATUSES


def _work_eligible_for_route(cell: CapabilityCell) -> bool:
    """Only admitted incomplete routes become work; never Cartesian unsupported."""

    if not _is_admitted(cell):
        return False
    # Unimplemented translated/advisory/declaration-shaped admitted edges.
    return bool(cell.unimplemented) or cell.support is SupportStatus.TRANSLATED


def explain_cell(
    cell: CapabilityCell,
    *,
    provider_native_families: frozenset[str] | None = None,
    registry: LogicFamilyRegistry | None = None,
) -> RouteExplanation:
    """Build a structured explanation for an admitted capability cell."""

    if not _is_admitted(cell):
        raise ReachableCapabilityGraphError(
            f"cell {cell.id!r} is not admitted; cannot explain as a route"
        )
    reg = registry if registry is not None else DEFAULT_REGISTRY
    natives = (
        provider_native_families
        if provider_native_families is not None
        else frozenset()
    )
    path_kind, path_id = _translation_path(
        cell, provider_native_families=natives, registry=reg
    )
    evidence_kind = _evidence_kind(cell)
    lifecycle = _lifecycle_stage(cell)
    feature = _provider_feature(cell)
    rationale = (
        f"Domain view {cell.formal_view_id} (family {cell.family_id}/"
        f"profile {cell.profile_id}) reaches provider {cell.provider_id} "
        f"via {path_kind.value} path {path_id}; support={cell.support.value}, "
        f"evidence={evidence_kind.value}, lifecycle={lifecycle.value}, "
        f"authority_ceiling={cell.authority_ceiling.value}."
    )
    if cell.notes:
        rationale = f"{rationale} {cell.notes}"
    return RouteExplanation(
        domain_id=cell.domain_id,
        formal_view_id=cell.formal_view_id,
        family_id=cell.family_id,
        profile_id=cell.profile_id,
        translation_path_kind=path_kind,
        translation_path_id=path_id,
        provider_id=cell.provider_id,
        provider_feature=feature,
        evidence_kind=evidence_kind,
        lifecycle_stage=lifecycle,
        authority_ceiling=cell.authority_ceiling,
        support=cell.support,
        rationale=rationale,
    )


def project_cell(
    cell: CapabilityCell,
    *,
    provider_native_families: frozenset[str] | None = None,
    registry: LogicFamilyRegistry | None = None,
) -> AdmittedRoute | ExcludedCell:
    """Project one matrix cell into an admitted route or typed exclusion."""

    if _is_admitted(cell):
        explanation = explain_cell(
            cell,
            provider_native_families=provider_native_families,
            registry=registry,
        )
        evidence_paths = tuple(item.path for item in cell.evidence)
        return AdmittedRoute(
            route_id=cell.id,
            domain_id=cell.domain_id,
            formal_view_id=cell.formal_view_id,
            family_id=cell.family_id,
            profile_id=cell.profile_id,
            provider_id=cell.provider_id,
            support=cell.support,
            availability=cell.availability,
            authority_ceiling=cell.authority_ceiling,
            explanation=explanation,
            work_eligible=_work_eligible_for_route(cell),
            unimplemented=bool(cell.unimplemented),
            notes=cell.notes or "",
            evidence_paths=evidence_paths,
        )

    reason = _exclusion_reason(cell)
    detail = cell.notes or (
        f"Coordinate excluded: support={cell.support.value}, "
        f"reason={reason.value}."
    )
    # Full Cartesian unsupported (and all other exclusions) are never work.
    return ExcludedCell(
        cell_id=cell.id,
        domain_id=cell.domain_id,
        formal_view_id=cell.formal_view_id,
        family_id=cell.family_id,
        profile_id=cell.profile_id,
        provider_id=cell.provider_id,
        support=cell.support,
        reason=reason,
        detail=detail,
        work_eligible=False,
        availability=cell.availability,
        authority_ceiling=cell.authority_ceiling,
    )


def build_reachable_graph(
    matrix: LogicCapabilityMatrix | None = None,
    *,
    registry: LogicFamilyRegistry | None = None,
) -> ReachableCapabilityGraph:
    """Project a capability matrix into the sparse reachable graph.

    Only admitted support statuses become routes. Every other cell is an
    exclusion with a typed reason. Unsupported exclusions are never work.
    """

    source = matrix if matrix is not None else build_default_matrix()
    reg = registry if registry is not None else DEFAULT_REGISTRY

    provider_natives: dict[str, frozenset[str]] = {
        provider.provider_id: frozenset(provider.native_families)
        for provider in source.providers
    }

    routes: list[AdmittedRoute] = []
    exclusions: list[ExcludedCell] = []
    for cell in source.cells:
        projected = project_cell(
            cell,
            provider_native_families=provider_natives.get(
                cell.provider_id, frozenset()
            ),
            registry=reg,
        )
        if isinstance(projected, AdmittedRoute):
            routes.append(projected)
        else:
            exclusions.append(projected)

    return ReachableCapabilityGraph(
        routes=tuple(routes),
        exclusions=tuple(exclusions),
        cartesian_cell_count=len(source.cells),
        metadata={
            "objective_id": TASK_ID,
            "goal_id": GOAL_ID,
            "program_id": PROGRAM_ID,
            "source_matrix_interface": source.interface,
            "source_matrix_schema": source.schema_version,
            "source_matrix_cell_count": len(source.cells),
            "source_matrix_digest_sha256": source.content_digest(),
            "sparsity_policy": (
                "Only native/translated/approximate/bounded/advisory cells are "
                "admitted as routes. Unsupported, unknown, and declaration-only "
                "coordinates are typed exclusions and are not work items."
            ),
            "work_policy": (
                "Work eligibility is limited to admitted incomplete routes "
                "(unimplemented or translated). Full Cartesian unsupported "
                "cells never become work."
            ),
            "availability_policy": (
                "Graph materialization never probes the environment. "
                "Availability is inherited declaration posture only."
            ),
            "authority_policy": (
                "Authority ceilings are inherited from the matrix support route "
                "and never promote advisory/candidate evidence to kernel authority."
            ),
            "evidence_subset": list(REQUIRED_EVIDENCE_DIMENSIONS),
        },
        notes=(
            "Sparse projection of LogicCapabilityMatrix@1. Every admitted route "
            "carries a structured explanation; every unreachable cell carries a "
            "typed exclusion reason."
        ),
    )


def build_default_graph() -> ReachableCapabilityGraph:
    """Build the sealed LFP2-003 reachable capability graph."""

    return build_reachable_graph(DEFAULT_MATRIX)


DEFAULT_GRAPH: Final = build_default_graph()


def assert_graph_acceptance(graph: ReachableCapabilityGraph) -> None:
    """Fail closed when LFP2-003 acceptance criteria are violated."""

    if graph.interface != REACHABLE_CAPABILITY_GRAPH_INTERFACE:
        raise ReachableCapabilityGraphError(
            f"interface drift: {graph.interface!r}"
        )
    if graph.schema_version != REACHABLE_CAPABILITY_GRAPH_SCHEMA:
        raise ReachableCapabilityGraphError(
            f"schema drift: {graph.schema_version!r}"
        )
    if not graph.routes:
        raise ReachableCapabilityGraphError("graph has no admitted routes")
    if not graph.exclusions:
        raise ReachableCapabilityGraphError(
            "graph has no exclusions; Cartesian product was not partitioned"
        )

    # Every admitted route is explainable.
    for route in graph.routes:
        if route.disposition is not RouteDisposition.ADMITTED:
            raise ReachableCapabilityGraphError(
                f"route {route.route_id!r} is not admitted"
            )
        explanation = route.explanation
        if not explanation.rationale.strip():
            raise ReachableCapabilityGraphError(
                f"route {route.route_id!r} lacks explanation"
            )
        if not explanation.translation_path_id:
            raise ReachableCapabilityGraphError(
                f"route {route.route_id!r} lacks translation path"
            )
        if explanation.support not in ADMITTED_SUPPORT_STATUSES:
            raise ReachableCapabilityGraphError(
                f"route {route.route_id!r} support is not admitted"
            )

    # Every unreachable cell is excluded with a typed reason.
    for exclusion in graph.exclusions:
        if exclusion.disposition is not RouteDisposition.EXCLUDED:
            raise ReachableCapabilityGraphError(
                f"exclusion {exclusion.cell_id!r} is not marked excluded"
            )
        if not isinstance(exclusion.reason, ExclusionReason):
            raise ReachableCapabilityGraphError(
                f"exclusion {exclusion.cell_id!r} lacks typed reason"
            )
        if not exclusion.detail.strip():
            raise ReachableCapabilityGraphError(
                f"exclusion {exclusion.cell_id!r} lacks detail"
            )

    # Full Cartesian unsupported cells do not become work.
    for exclusion in graph.exclusions:
        if exclusion.support is SupportStatus.UNSUPPORTED and exclusion.work_eligible:
            raise ReachableCapabilityGraphError(
                f"unsupported cell {exclusion.cell_id!r} became work"
            )
    summary = graph.summary()
    if summary["unsupported_work_eligible_count"] != 0:
        raise ReachableCapabilityGraphError(
            "unsupported Cartesian cells must not be work-eligible"
        )

    # Sparse: admitted routes must be a proper subset of Cartesian size.
    total = graph.admitted_count + graph.excluded_count
    if graph.cartesian_cell_count and graph.cartesian_cell_count != total:
        raise ReachableCapabilityGraphError(
            "cartesian partition is incomplete"
        )
    if graph.admitted_count >= total:
        raise ReachableCapabilityGraphError(
            "graph is not sparse; every Cartesian cell was admitted"
        )

    # Work items must be drawn only from admitted routes.
    work_ids = {item.route_id for item in graph.work_items()}
    admitted_ids = {item.route_id for item in graph.routes}
    if not work_ids.issubset(admitted_ids):
        raise ReachableCapabilityGraphError(
            "work items must be a subset of admitted routes"
        )
    exclusion_ids = {item.cell_id for item in graph.exclusions}
    if work_ids & exclusion_ids:
        raise ReachableCapabilityGraphError(
            "work items must not include excluded cells"
        )


def to_graph_seal_dict(graph: ReachableCapabilityGraph) -> dict[str, Any]:
    """Compact sealed baseline: summary + policies + materialization pointer.

    Full route and exclusion bodies remain available from
    :func:`build_default_graph` / :func:`build_reachable_graph`.  The seal is
    the durable evidence surface; live materialization is the authority for
    coordinate bodies.
    """

    summary = graph.summary()
    return {
        "schema_version": graph.schema_version,
        "interface": graph.interface,
        "version": graph.version,
        "description": graph.description,
        "notes": graph.notes,
        "metadata": dict(graph.metadata),
        "materialization": MATERIALIZATION_TARGET,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "required_evidence_dimensions": list(REQUIRED_EVIDENCE_DIMENSIONS),
        "lifecycle_stages": list(LIFECYCLE_STAGES),
        "admitted_support_statuses": sorted(
            status.value for status in ADMITTED_SUPPORT_STATUSES
        ),
        "acceptance": {
            "admitted_routes_explainable": True,
            "unreachable_cells_typed_exclusion": True,
            "unsupported_cartesian_cells_are_not_work": True,
        },
        "cartesian_cell_count": summary["cartesian_cell_count"],
        "admitted_count": summary["admitted_count"],
        "excluded_count": summary["excluded_count"],
        "work_eligible_count": summary["work_eligible_count"],
        "work_eligible_route_ids": list(summary["work_eligible_route_ids"]),
        "unsupported_exclusion_count": summary["unsupported_exclusion_count"],
        "unsupported_work_eligible_count": summary[
            "unsupported_work_eligible_count"
        ],
        "sparsity_ratio": summary["sparsity_ratio"],
        "exclusion_reason_histogram": dict(summary["exclusion_reason_histogram"]),
        "route_support_histogram": dict(summary["route_support_histogram"]),
        "exclusion_support_histogram": dict(
            summary["exclusion_support_histogram"]
        ),
        "content_digest": graph.content_digest(),
    }


def render_graph_json(graph: ReachableCapabilityGraph) -> str:
    """Deterministic full baseline JSON rendering with trailing newline."""

    return (
        json.dumps(
            graph.to_baseline_dict(),
            ensure_ascii=True,
            indent=2,
            sort_keys=False,
            allow_nan=False,
        )
        + "\n"
    )


def render_graph_seal_json(graph: ReachableCapabilityGraph) -> str:
    """Deterministic compact seal JSON with trailing newline."""

    return (
        json.dumps(
            to_graph_seal_dict(graph),
            ensure_ascii=True,
            indent=2,
            sort_keys=False,
            allow_nan=False,
        )
        + "\n"
    )


def write_graph_baseline(
    graph: ReachableCapabilityGraph,
    path: str | Path,
    *,
    full_routes: bool = False,
) -> Path:
    """Atomically write the baseline report to *path*.

    By default write the compact seal (summary + materialization pointer).
    Pass ``full_routes=True`` to persist the full admitted/exclusion expansion.
    """

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = (
        render_graph_json(graph) if full_routes else render_graph_seal_json(graph)
    )
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(target)
    return target


def _validate_seal_against_graph(
    payload: Mapping[str, Any],
    graph: ReachableCapabilityGraph,
) -> None:
    if payload.get("schema_version") != REACHABLE_CAPABILITY_GRAPH_SCHEMA:
        raise ReachableCapabilityGraphError(
            f"unsupported schema_version {payload.get('schema_version')!r}"
        )
    if payload.get("interface") != REACHABLE_CAPABILITY_GRAPH_INTERFACE:
        raise ReachableCapabilityGraphError(
            f"unsupported interface {payload.get('interface')!r}"
        )
    if payload.get("materialization") != MATERIALIZATION_TARGET:
        raise ReachableCapabilityGraphError(
            f"unsupported materialization {payload.get('materialization')!r}"
        )
    if payload.get("task_id") not in {None, TASK_ID}:
        raise ReachableCapabilityGraphError(
            f"task_id drift: {payload.get('task_id')!r}"
        )
    if payload.get("goal_id") not in {None, GOAL_ID}:
        raise ReachableCapabilityGraphError(
            f"goal_id drift: {payload.get('goal_id')!r}"
        )
    if payload.get("program_id") not in {None, PROGRAM_ID}:
        raise ReachableCapabilityGraphError(
            f"program_id drift: {payload.get('program_id')!r}"
        )
    live_seal = to_graph_seal_dict(graph)
    # Structural identity always required when present.
    for key in (
        "version",
        "admitted_support_statuses",
        "required_evidence_dimensions",
        "lifecycle_stages",
    ):
        if key in payload and payload[key] != live_seal[key]:
            raise ReachableCapabilityGraphError(
                f"seal field {key!r} disagrees with materialization"
            )
    # Quantitative fields are validated when the seal carries them (full seal).
    for key in (
        "cartesian_cell_count",
        "admitted_count",
        "excluded_count",
        "work_eligible_count",
        "work_eligible_route_ids",
        "unsupported_exclusion_count",
        "unsupported_work_eligible_count",
        "sparsity_ratio",
        "exclusion_reason_histogram",
        "route_support_histogram",
        "exclusion_support_histogram",
        "content_digest",
    ):
        if key in payload and payload[key] != live_seal[key]:
            raise ReachableCapabilityGraphError(
                f"seal field {key!r} disagrees with materialization"
            )
    acceptance = payload.get("acceptance")
    if isinstance(acceptance, Mapping):
        if acceptance.get("unsupported_cartesian_cells_are_not_work") is not True:
            raise ReachableCapabilityGraphError(
                "seal acceptance must declare unsupported Cartesian cells are not work"
            )
        if live_seal["unsupported_work_eligible_count"] != 0:
            raise ReachableCapabilityGraphError(
                "live graph has work-eligible unsupported cells"
            )


def load_graph_baseline(path: str | Path) -> ReachableCapabilityGraph:
    """Load and validate a baseline reachable-capability graph report.

    Accepts either a full route/exclusion expansion or a compact materialization
    seal. Compact seals re-materialize through :func:`build_default_graph` and
    validate that sealed summary fields still match.
    """

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ReachableCapabilityGraphError("baseline must be a JSON object")
    if payload.get("materialization") and "routes" not in payload:
        graph = build_default_graph()
        _validate_seal_against_graph(payload, graph)
        return graph
    graph = ReachableCapabilityGraph.from_dict(payload)
    if graph.schema_version != REACHABLE_CAPABILITY_GRAPH_SCHEMA:
        raise ReachableCapabilityGraphError(
            f"unsupported schema_version {graph.schema_version!r}"
        )
    if graph.interface != REACHABLE_CAPABILITY_GRAPH_INTERFACE:
        raise ReachableCapabilityGraphError(
            f"unsupported interface {graph.interface!r}"
        )
    return graph


def default_datasets_repo_root() -> Path:
    """Resolve the nested ``ipfs_datasets_py`` repository root."""

    # .../ipfs_datasets_py/logic/conformance/reachable_graph.py -> datasets root
    return Path(__file__).resolve().parents[3]


def default_baseline_path(*, datasets_root: str | Path | None = None) -> Path:
    """Resolve the sealed baseline path under the nested datasets repository."""

    if datasets_root is None:
        datasets_root = default_datasets_repo_root()
    return Path(datasets_root) / DEFAULT_BASELINE_RELATIVE_PATH


def ensure_baseline_seal(
    path: str | Path | None = None,
    *,
    datasets_root: str | Path | None = None,
) -> ReachableCapabilityGraph:
    """Re-materialize the graph and verify it matches the sealed baseline."""

    root = (
        Path(datasets_root).resolve()
        if datasets_root is not None
        else default_datasets_repo_root()
    )
    target = (
        Path(path) if path is not None else default_baseline_path(datasets_root=root)
    )
    live = build_default_graph()
    assert_graph_acceptance(live)
    if not target.is_file():
        raise ReachableCapabilityGraphError(f"baseline missing: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ReachableCapabilityGraphError("baseline must be a JSON object")
    if payload.get("materialization") and "routes" not in payload:
        _validate_seal_against_graph(payload, live)
        return live
    sealed = ReachableCapabilityGraph.from_dict(payload)
    if sealed.interface != live.interface:
        raise ReachableCapabilityGraphError(
            f"baseline interface drift: {sealed.interface!r} != {live.interface!r}"
        )
    if sealed.schema_version != live.schema_version:
        raise ReachableCapabilityGraphError(
            f"baseline schema drift: {sealed.schema_version!r} != {live.schema_version!r}"
        )
    if sealed.version != live.version:
        raise ReachableCapabilityGraphError(
            f"baseline version drift: {sealed.version!r} != {live.version!r}"
        )
    live_routes = [item.to_dict() for item in live.routes]
    sealed_routes = [item.to_dict() for item in sealed.routes]
    if live_routes != sealed_routes:
        raise ReachableCapabilityGraphError(
            "baseline routes drifted from live materialization"
        )
    live_exclusions = [item.to_dict() for item in live.exclusions]
    sealed_exclusions = [item.to_dict() for item in sealed.exclusions]
    if live_exclusions != sealed_exclusions:
        raise ReachableCapabilityGraphError(
            "baseline exclusions drifted from live materialization"
        )
    if live.summary() != sealed.summary():
        raise ReachableCapabilityGraphError(
            "baseline summary drifted from live materialization"
        )
    return live


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: write the reachable capability graph baseline report."""

    import argparse

    parser = argparse.ArgumentParser(
        description="Materialize ReachableCapabilityGraph@1 baseline report"
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output path (default: docs/architecture/logic/logic_parser_v2_baseline/...)",
    )
    parser.add_argument(
        "--full-routes",
        action="store_true",
        help="Write the full route/exclusion expansion instead of the compact seal",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    graph = build_default_graph()
    assert_graph_acceptance(graph)
    target = Path(args.output) if args.output else default_baseline_path()
    write_graph_baseline(graph, target, full_routes=bool(args.full_routes))
    summary = graph.summary()
    print(
        f"wrote {target} routes={summary['admitted_count']} "
        f"exclusions={summary['excluded_count']} "
        f"work={summary['work_eligible_count']} "
        f"digest={graph.content_digest()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ADMITTED_SUPPORT_STATUSES",
    "DEFAULT_BASELINE_RELATIVE_PATH",
    "DEFAULT_GRAPH",
    "EvidenceKind",
    "EXCLUSION_SCHEMA",
    "EXPLANATION_SCHEMA",
    "ExclusionReason",
    "ExcludedCell",
    "GOAL_ID",
    "GRAPH_VERSION",
    "LIFECYCLE_STAGES",
    "LifecycleStage",
    "MATERIALIZATION_TARGET",
    "PROGRAM_ID",
    "REACHABLE_CAPABILITY_GRAPH_INTERFACE",
    "REACHABLE_CAPABILITY_GRAPH_SCHEMA",
    "REQUIRED_EVIDENCE_DIMENSIONS",
    "ROUTE_SCHEMA",
    "AdmittedRoute",
    "ReachableCapabilityGraph",
    "ReachableCapabilityGraphError",
    "RouteDisposition",
    "RouteExplanation",
    "TASK_ID",
    "TranslationPathKind",
    "assert_graph_acceptance",
    "build_default_graph",
    "build_reachable_graph",
    "default_baseline_path",
    "default_datasets_repo_root",
    "ensure_baseline_seal",
    "explain_cell",
    "load_graph_baseline",
    "main",
    "project_cell",
    "render_graph_json",
    "render_graph_seal_json",
    "route_id",
    "to_graph_seal_dict",
    "write_graph_baseline",
]

