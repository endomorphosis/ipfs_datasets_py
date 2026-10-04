"""Rank complete missing-proof plans by authority and utility.

FVT-G035 / FVT-026: ``GoalDirectedProofPlanRanker@1``

Construct complete alternatives suitable for the existing AND/OR and
proof-aware plan evaluators, hard-reject invalid or insufficient-authority
branches, and rank remaining plans by:

* discharged coverage of the goal graph;
* downstream unlock value;
* critical-path reduction;
* proof / assumption authority;
* assumption cost and risk (assumption-heavy plans pay explicit cost);
* proof cost;
* cache value of independently validated evidence; and
* fallback / recovery quality.

Program invariants:

* rankings are deterministic and explainable (integer millionths + rationale);
* incomplete, structurally invalid, or insufficient-authority branches are
  hard-pruned before soft scoring (never compensated by utility);
* every step names dependencies, expected receipts, validation, fallback,
  resources, and completion conditions;
* plans never claim proof or goal completion (``GoalDirectedProofPlan@1``);
* adapters project onto existing plan-evaluator primitives without changing
  unrelated implementation-task routing.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
    GOAL_DIRECTED_PROOF_PLAN_INTERFACE,
    GOAL_DIRECTED_PROOF_PLAN_SCHEMA,
    AuthorityCeiling,
    CandidateProofStep,
    CandidateStatus,
    GoalDirectedProofPlan,
    PlanStatus,
    ResourceBounds,
    SourceSpanBinding,
    TacticianContractError,
    content_identity,
)

# ---------------------------------------------------------------------------
# Interface / schema constants
# ---------------------------------------------------------------------------

GOAL_DIRECTED_PROOF_PLAN_RANKER_INTERFACE: Final = "GoalDirectedProofPlanRanker@1"
PROOF_PLAN_STEP_SPEC_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/proof-plan-step-spec@1"
)
MISSING_PROOF_PLAN_ALTERNATIVE_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/"
    "missing-proof-plan-alternative@1"
)
PLAN_RANKING_POLICY_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/plan-ranking-policy@1"
)
RANKED_PROOF_PLAN_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/ranked-proof-plan@1"
)
PROOF_PLAN_RANKING_RESULT_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/proof-plan-ranking-result@1"
)
PROOF_PLAN_HARD_FAILURE_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/proof-plan-hard-failure@1"
)
RANKER_ALGORITHM_VERSION: Final = "goal-directed-proof-plan-ranker/1.0.0"

DEFAULT_BOUNDS: Final = ResourceBounds(
    wall_time_ms=30_000,
    memory_bytes=256 * 1024 * 1024,
    max_steps=64,
    max_depth=16,
    max_nodes=128,
    max_candidates=32,
    model_token_limit=0,
    network_allowed=False,
)

# Step fields that must be non-empty for a complete plan alternative.
REQUIRED_STEP_FIELD_NAMES: Final[tuple[str, ...]] = (
    "dependencies",
    "expected_receipts",
    "validation",
    "fallback",
    "resources",
    "completion_conditions",
)

# Soft-score dimensions exposed in every ranked rationale (explainability).
RANKING_SCORE_DIMENSIONS: Final[tuple[str, ...]] = (
    "discharged_coverage",
    "downstream_unlock",
    "critical_path",
    "authority",
    "assumption_cost",
    "risk",
    "proof_cost",
    "cache_value",
    "fallback_quality",
)

# Authority total order for "insufficient" checks (higher is stronger).
_AUTHORITY_RANK: Final[Mapping[AuthorityCeiling, int]] = {
    AuthorityCeiling.NONE: 0,
    AuthorityCeiling.ADVISORY: 1,
    AuthorityCeiling.CANDIDATE: 2,
    AuthorityCeiling.BOUNDED: 3,
    AuthorityCeiling.SATISFIABILITY: 4,
    AuthorityCeiling.MODEL_CHECK: 5,
    AuthorityCeiling.MONITOR: 6,
    AuthorityCeiling.AUTHORIZATION: 7,
    AuthorityCeiling.PROTOCOL: 8,
    AuthorityCeiling.HYPERPROPERTY: 9,
    AuthorityCeiling.RECONSTRUCTION: 10,
    AuthorityCeiling.ATTESTATION: 11,
    AuthorityCeiling.THEOREM: 12,
    AuthorityCeiling.DECLARATIVE: 12,
}

# Proposal-class authorities that cannot alone discharge trusted obligations.
_PROPOSAL_AUTHORITIES: Final[frozenset[AuthorityCeiling]] = frozenset(
    {
        AuthorityCeiling.NONE,
        AuthorityCeiling.ADVISORY,
        AuthorityCeiling.CANDIDATE,
    }
)


# ---------------------------------------------------------------------------
# Errors and closed vocabularies
# ---------------------------------------------------------------------------


class ProofPlanError(ValueError):
    """Raised when proof-plan construction or ranking inputs are malformed."""


class HardPruneReason(StrEnum):
    """Closed set of non-compensable hard-prune reasons."""

    INCOMPLETE_STEP = "incomplete_step"
    INVALID_STRUCTURE = "invalid_structure"
    INSUFFICIENT_AUTHORITY = "insufficient_authority"
    EMPTY_PLAN = "empty_plan"
    PROOF_CLAIM = "proof_claim"
    COMPLETION_CLAIM = "completion_claim"
    CYCLIC_DEPENDENCIES = "cyclic_dependencies"
    UNKNOWN_DEPENDENCY = "unknown_dependency"
    MISSING_COVERAGE = "missing_coverage"
    RESOURCE_BOUND = "resource_bound"


class StepKind(StrEnum):
    """Closed vocabulary of missing-proof step kinds."""

    SOLVE = "solve"
    VALIDATE = "validate"
    DISCHARGE = "discharge"
    ABDUCE = "abduce"
    REPAIR = "repair"
    FALLBACK = "fallback"
    CACHE_REPLAY = "cache_replay"
    ASSUMPTION_REVIEW = "assumption_review"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(
    value: object,
    label: str,
    *,
    optional: bool = False,
    maximum: int = 4096,
) -> str:
    if optional and (value is None or value == ""):
        return ""
    if not isinstance(value, str):
        raise ProofPlanError(f"{label} must be a string")
    text = value.strip()
    if "\x00" in text:
        raise ProofPlanError(f"{label} must not contain NUL")
    if not optional and not text:
        raise ProofPlanError(f"{label} is required")
    if len(text) > maximum:
        raise ProofPlanError(f"{label} exceeds maximum length of {maximum}")
    return text


def _string_tuple(
    value: object,
    label: str,
    *,
    allow_empty: bool = False,
    preserve_order: bool = True,
    maximum_item: int = 512,
) -> tuple[str, ...]:
    if value is None:
        items: list[str] = []
    elif isinstance(value, (str, bytes, bytearray)):
        raise ProofPlanError(f"{label} must be an array of strings")
    elif isinstance(value, Sequence):
        items = [
            _text(item, f"{label}[{index}]", maximum=maximum_item)
            for index, item in enumerate(value)
        ]
    else:
        raise ProofPlanError(f"{label} must be an array of strings")
    if not preserve_order:
        items = sorted(set(items))
    else:
        seen: set[str] = set()
        ordered: list[str] = []
        for item in items:
            if item not in seen:
                seen.add(item)
                ordered.append(item)
        items = ordered
    if not items and not allow_empty:
        raise ProofPlanError(f"{label} must contain at least one value")
    return tuple(items)


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ProofPlanError(f"{label} must be a boolean")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProofPlanError(f"{label} must be a non-negative integer")
    if value < 0:
        raise ProofPlanError(f"{label} must be a non-negative integer")
    return value


def _number(
    value: object,
    label: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProofPlanError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ProofPlanError(f"{label} must be a finite number")
    if minimum is not None and number < minimum:
        raise ProofPlanError(f"{label} must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise ProofPlanError(f"{label} must be <= {maximum}")
    return number


def _enum(value: object, enum_cls: type[StrEnum], label: str) -> StrEnum:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(str(value).strip())
    except ValueError as error:
        raise ProofPlanError(
            f"{label} must be one of "
            f"{', '.join(item.value for item in enum_cls)}"
        ) from error


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ProofPlanError(f"{label} must be an object")
    return dict(value)


def _to_millionths(value: float | Decimal | int) -> int:
    quant = (Decimal(str(value)) * Decimal(1_000_000)).quantize(
        Decimal(1), rounding=ROUND_HALF_UP
    )
    return int(quant)


def _bounded_benefit(value: float) -> Decimal:
    raw = Decimal(str(value))
    return raw / (Decimal(1) + raw)


def _authority(value: object, label: str) -> AuthorityCeiling:
    if isinstance(value, AuthorityCeiling):
        return value
    try:
        return AuthorityCeiling(str(value).strip())
    except ValueError as error:
        raise ProofPlanError(f"{label} is not a valid AuthorityCeiling") from error


def authority_rank(authority: AuthorityCeiling | str) -> int:
    """Return total-order rank for an authority ceiling."""

    resolved = (
        authority
        if isinstance(authority, AuthorityCeiling)
        else _authority(authority, "authority")
    )
    return _AUTHORITY_RANK.get(resolved, 0)


def authority_meets_minimum(
    authority: AuthorityCeiling | str,
    minimum: AuthorityCeiling | str,
) -> bool:
    """True when ``authority`` is at least as strong as ``minimum``."""

    return authority_rank(authority) >= authority_rank(minimum)


def _stable_id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256(
        json.dumps(
            [str(part) for part in parts],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _detect_cycle(depends: Mapping[str, Sequence[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visited:
            return False
        if node in visiting:
            return True
        visiting.add(node)
        for dep in depends.get(node, ()):
            if dep in depends and visit(dep):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in depends)


# ---------------------------------------------------------------------------
# Policy / weights
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProofPlanRankingWeights:
    """Deterministic soft-score weights for complete missing-proof plans.

    Weights are non-negative and need not sum to one; they are normalized at
    scoring time so relative emphasis is stable across policies.
    """

    SCHEMA: ClassVar[str] = PLAN_RANKING_POLICY_SCHEMA

    discharged_coverage: float = 0.18
    downstream_unlock: float = 0.14
    critical_path: float = 0.14
    authority: float = 0.12
    assumption_cost: float = 0.12
    risk: float = 0.10
    proof_cost: float = 0.08
    cache_value: float = 0.07
    fallback_quality: float = 0.05

    def __post_init__(self) -> None:
        total = Decimal(0)
        for name in self.__dataclass_fields__:
            if name == "SCHEMA":
                continue
            value = _number(getattr(self, name), name, minimum=0.0)
            object.__setattr__(self, name, value)
            total += Decimal(str(value))
        if total <= 0:
            raise ProofPlanError("at least one ranking weight must be positive")

    @property
    def total(self) -> Decimal:
        return sum(
            (
                Decimal(str(getattr(self, name)))
                for name in self.__dataclass_fields__
                if name != "SCHEMA"
            ),
            Decimal(0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "SCHEMA"
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProofPlanRankingWeights":
        if not isinstance(payload, Mapping):
            raise ProofPlanError("ranking weights must be an object")
        allowed = set(cls.__dataclass_fields__) - {"SCHEMA"}
        unknown = sorted(str(key) for key in payload if key not in allowed)
        if unknown:
            raise ProofPlanError(
                "unknown ranking weight fields: " + ", ".join(unknown)
            )
        return cls(**{key: payload[key] for key in payload if key in allowed})


@dataclass(frozen=True, slots=True)
class ProofPlanRankingPolicy:
    """Scheduler observations used while ranking missing-proof plans."""

    SCHEMA: ClassVar[str] = PLAN_RANKING_POLICY_SCHEMA

    minimum_authority: AuthorityCeiling = AuthorityCeiling.BOUNDED
    available_resource_classes: tuple[str, ...] = ()
    satisfied_dependencies: tuple[str, ...] = ()
    required_obligation_ids: tuple[str, ...] = ()
    weights: ProofPlanRankingWeights = field(
        default_factory=ProofPlanRankingWeights
    )
    # Per-new-assumption soft cost in [0, 1] before weighting.
    assumption_unit_cost: float = 0.25
    max_new_assumptions: int = 16

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "minimum_authority",
            _authority(self.minimum_authority, "minimum_authority"),
        )
        object.__setattr__(
            self,
            "available_resource_classes",
            _string_tuple(
                self.available_resource_classes,
                "available_resource_classes",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "satisfied_dependencies",
            _string_tuple(
                self.satisfied_dependencies,
                "satisfied_dependencies",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "required_obligation_ids",
            _string_tuple(
                self.required_obligation_ids,
                "required_obligation_ids",
                allow_empty=True,
            ),
        )
        weights = self.weights
        if isinstance(weights, Mapping):
            weights = ProofPlanRankingWeights.from_dict(weights)
        elif not isinstance(weights, ProofPlanRankingWeights):
            raise ProofPlanError("weights must be ProofPlanRankingWeights")
        object.__setattr__(self, "weights", weights)
        object.__setattr__(
            self,
            "assumption_unit_cost",
            _number(
                self.assumption_unit_cost,
                "assumption_unit_cost",
                minimum=0.0,
                maximum=1.0,
            ),
        )
        object.__setattr__(
            self,
            "max_new_assumptions",
            _nonnegative_int(self.max_new_assumptions, "max_new_assumptions"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "minimum_authority": self.minimum_authority.value,
            "available_resource_classes": list(self.available_resource_classes),
            "satisfied_dependencies": list(self.satisfied_dependencies),
            "required_obligation_ids": list(self.required_obligation_ids),
            "weights": self.weights.to_dict(),
            "assumption_unit_cost": self.assumption_unit_cost,
            "max_new_assumptions": self.max_new_assumptions,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProofPlanRankingPolicy":
        if not isinstance(payload, Mapping):
            raise ProofPlanError("ranking policy must be an object")
        return cls(
            minimum_authority=payload.get(
                "minimum_authority", AuthorityCeiling.BOUNDED
            ),
            available_resource_classes=tuple(
                payload.get("available_resource_classes") or ()
            ),
            satisfied_dependencies=tuple(
                payload.get("satisfied_dependencies") or ()
            ),
            required_obligation_ids=tuple(
                payload.get("required_obligation_ids") or ()
            ),
            weights=payload.get("weights") or ProofPlanRankingWeights(),
            assumption_unit_cost=payload.get("assumption_unit_cost", 0.25),
            max_new_assumptions=int(payload.get("max_new_assumptions", 16)),
        )


# ---------------------------------------------------------------------------
# Step and plan alternative contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProofPlanStepSpec:
    """One complete missing-proof step (every required field is first-class).

    Completeness requirements (acceptance): each step names dependencies,
    expected receipts, validation, fallback, resources, and completion
    conditions.  Steps are proposals and never claim proof or completion.
    """

    SCHEMA: ClassVar[str] = PROOF_PLAN_STEP_SPEC_SCHEMA

    step_id: str
    obligation_id: str
    kind: StepKind = StepKind.SOLVE
    statement: str = ""
    dependencies: tuple[str, ...] = ()
    expected_receipts: tuple[str, ...] = ()
    validation: tuple[str, ...] = ()
    fallback: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    completion_conditions: tuple[str, ...] = ()
    authority: AuthorityCeiling = AuthorityCeiling.BOUNDED
    new_assumption_ids: tuple[str, ...] = ()
    provider_ids: tuple[str, ...] = ()
    proof_cost: float = 1.0
    cache_value: float = 0.0
    risk: float = 0.2
    downstream_unlock: float = 0.0
    critical_path_contribution: float = 1.0
    proof_claimed: bool = False
    completion_claimed: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "step_id", _text(self.step_id, "step_id", maximum=256)
        )
        object.__setattr__(
            self,
            "obligation_id",
            _text(self.obligation_id, "obligation_id", maximum=256),
        )
        object.__setattr__(self, "kind", _enum(self.kind, StepKind, "kind"))
        object.__setattr__(
            self,
            "statement",
            _text(
                self.statement or f"close obligation {self.obligation_id}",
                "statement",
                maximum=8192,
            ),
        )
        # Required completeness fields: empty is incomplete (detected later),
        # but type/shape is validated here with allow_empty for partial drafts.
        object.__setattr__(
            self,
            "dependencies",
            _string_tuple(
                self.dependencies, "dependencies", allow_empty=True
            ),
        )
        object.__setattr__(
            self,
            "expected_receipts",
            _string_tuple(
                self.expected_receipts, "expected_receipts", allow_empty=True
            ),
        )
        object.__setattr__(
            self,
            "validation",
            _string_tuple(self.validation, "validation", allow_empty=True),
        )
        object.__setattr__(
            self,
            "fallback",
            _string_tuple(self.fallback, "fallback", allow_empty=True),
        )
        object.__setattr__(
            self,
            "resources",
            _string_tuple(self.resources, "resources", allow_empty=True),
        )
        object.__setattr__(
            self,
            "completion_conditions",
            _string_tuple(
                self.completion_conditions,
                "completion_conditions",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self, "authority", _authority(self.authority, "authority")
        )
        object.__setattr__(
            self,
            "new_assumption_ids",
            _string_tuple(
                self.new_assumption_ids, "new_assumption_ids", allow_empty=True
            ),
        )
        object.__setattr__(
            self,
            "provider_ids",
            _string_tuple(self.provider_ids, "provider_ids", allow_empty=True),
        )
        object.__setattr__(
            self,
            "proof_cost",
            _number(self.proof_cost, "proof_cost", minimum=0.0),
        )
        object.__setattr__(
            self,
            "cache_value",
            _number(self.cache_value, "cache_value", minimum=0.0, maximum=1.0),
        )
        object.__setattr__(
            self, "risk", _number(self.risk, "risk", minimum=0.0, maximum=1.0)
        )
        object.__setattr__(
            self,
            "downstream_unlock",
            _number(self.downstream_unlock, "downstream_unlock", minimum=0.0),
        )
        object.__setattr__(
            self,
            "critical_path_contribution",
            _number(
                self.critical_path_contribution,
                "critical_path_contribution",
                minimum=0.0,
            ),
        )
        object.__setattr__(
            self, "proof_claimed", _bool(self.proof_claimed, "proof_claimed")
        )
        object.__setattr__(
            self,
            "completion_claimed",
            _bool(self.completion_claimed, "completion_claimed"),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))
        if self.step_id in self.dependencies:
            raise ProofPlanError("a step cannot depend on itself")

    def missing_required_fields(self) -> tuple[str, ...]:
        """Return required completeness fields that are empty."""

        missing: list[str] = []
        if not self.dependencies:
            # Root steps may declare an explicit empty-dependency marker.
            if self.metadata.get("root") is not True:
                missing.append("dependencies")
        if not self.expected_receipts:
            missing.append("expected_receipts")
        if not self.validation:
            missing.append("validation")
        if not self.fallback:
            missing.append("fallback")
        if not self.resources:
            missing.append("resources")
        if not self.completion_conditions:
            missing.append("completion_conditions")
        return tuple(missing)

    def is_complete(self) -> bool:
        return not self.missing_required_fields()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "step_id": self.step_id,
            "obligation_id": self.obligation_id,
            "kind": self.kind.value,
            "statement": self.statement,
            "dependencies": list(self.dependencies),
            "expected_receipts": list(self.expected_receipts),
            "validation": list(self.validation),
            "fallback": list(self.fallback),
            "resources": list(self.resources),
            "completion_conditions": list(self.completion_conditions),
            "authority": self.authority.value,
            "new_assumption_ids": list(self.new_assumption_ids),
            "provider_ids": list(self.provider_ids),
            "proof_cost": self.proof_cost,
            "cache_value": self.cache_value,
            "risk": self.risk,
            "downstream_unlock": self.downstream_unlock,
            "critical_path_contribution": self.critical_path_contribution,
            "proof_claimed": False,
            "completion_claimed": False,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProofPlanStepSpec":
        if not isinstance(payload, Mapping):
            raise ProofPlanError("step payload must be an object")
        return cls(
            step_id=payload.get("step_id", ""),
            obligation_id=payload.get("obligation_id", ""),
            kind=payload.get("kind", StepKind.SOLVE),
            statement=payload.get("statement", ""),
            dependencies=tuple(payload.get("dependencies") or ()),
            expected_receipts=tuple(payload.get("expected_receipts") or ()),
            validation=tuple(payload.get("validation") or ()),
            fallback=tuple(payload.get("fallback") or ()),
            resources=tuple(payload.get("resources") or ()),
            completion_conditions=tuple(
                payload.get("completion_conditions") or ()
            ),
            authority=payload.get("authority", AuthorityCeiling.BOUNDED),
            new_assumption_ids=tuple(payload.get("new_assumption_ids") or ()),
            provider_ids=tuple(payload.get("provider_ids") or ()),
            proof_cost=payload.get("proof_cost", 1.0),
            cache_value=payload.get("cache_value", 0.0),
            risk=payload.get("risk", 0.2),
            downstream_unlock=payload.get("downstream_unlock", 0.0),
            critical_path_contribution=payload.get(
                "critical_path_contribution", 1.0
            ),
            proof_claimed=bool(payload.get("proof_claimed", False)),
            completion_claimed=bool(payload.get("completion_claimed", False)),
            metadata=payload.get("metadata") or {},
        )

    def to_candidate_proof_step(
        self,
        *,
        tree_id: str = "",
        rank_score_millionths: int = 0,
    ) -> CandidateProofStep:
        """Project onto the shared ``CandidateProofStep`` wire contract."""

        return CandidateProofStep(
            candidate_id=self.step_id,
            hole_id=self.obligation_id,
            kind=self.kind.value,
            statement=self.statement,
            status=CandidateStatus.PROPOSED,
            source=SourceSpanBinding(tree_id=tree_id),
            provider_ids=self.provider_ids,
            authority=AuthorityCeiling.CANDIDATE,
            rank_score_millionths=rank_score_millionths,
            new_assumption_ids=self.new_assumption_ids,
            evidence_ids=self.expected_receipts,
            provenance={
                "from": "ProofPlanStepSpec",
                "resources": list(self.resources),
                "validation": list(self.validation),
                "fallback": list(self.fallback),
                "completion_conditions": list(self.completion_conditions),
                "step_authority": self.authority.value,
            },
            proof_claimed=False,
            completion_claimed=False,
        )


@dataclass(frozen=True, slots=True)
class ProofPlanHardFailure:
    """Typed hard-gate failure retained without provider reasoning prose."""

    SCHEMA: ClassVar[str] = PROOF_PLAN_HARD_FAILURE_SCHEMA

    reason: HardPruneReason
    reason_codes: tuple[str, ...] = ()
    step_id: str = ""
    detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "reason", _enum(self.reason, HardPruneReason, "reason")
        )
        object.__setattr__(
            self,
            "reason_codes",
            _string_tuple(
                self.reason_codes, "reason_codes", allow_empty=True
            ),
        )
        object.__setattr__(
            self,
            "step_id",
            _text(self.step_id, "step_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self,
            "detail",
            _text(self.detail, "detail", optional=True, maximum=4096),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "reason": self.reason.value,
            "reason_codes": list(self.reason_codes),
            "step_id": self.step_id,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProofPlanHardFailure":
        if not isinstance(payload, Mapping):
            raise ProofPlanError("hard failure payload must be an object")
        return cls(
            reason=payload.get("reason", HardPruneReason.INVALID_STRUCTURE),
            reason_codes=tuple(payload.get("reason_codes") or ()),
            step_id=payload.get("step_id", ""),
            detail=payload.get("detail", ""),
        )


@dataclass(frozen=True, slots=True)
class MissingProofPlanAlternative:
    """One complete alternative for closing the open missing-proof graph.

    Alternatives are complete selections over OR branches of the AND/OR
    obligation graph.  Soft utility is computed only after hard pruning.
    """

    SCHEMA: ClassVar[str] = MISSING_PROOF_PLAN_ALTERNATIVE_SCHEMA

    plan_id: str
    formal_goal_id: str
    graph_id: str
    tree_id: str
    steps: tuple[ProofPlanStepSpec, ...]
    covered_obligation_ids: tuple[str, ...] = ()
    required_obligation_ids: tuple[str, ...] = ()
    alternative_ids: tuple[str, ...] = ()
    producer_kinds: tuple[str, ...] = ()
    hard_failures: tuple[ProofPlanHardFailure, ...] = ()
    bounds: ResourceBounds = field(default_factory=lambda: DEFAULT_BOUNDS)
    root_goal_id: str = ""
    proof_claimed: bool = False
    completion_claimed: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "plan_id", _text(self.plan_id, "plan_id", maximum=256)
        )
        object.__setattr__(
            self,
            "formal_goal_id",
            _text(self.formal_goal_id, "formal_goal_id", maximum=256),
        )
        object.__setattr__(
            self, "graph_id", _text(self.graph_id, "graph_id", maximum=256)
        )
        object.__setattr__(
            self, "tree_id", _text(self.tree_id, "tree_id", maximum=256)
        )
        steps: list[ProofPlanStepSpec] = []
        for item in self.steps or ():
            if isinstance(item, ProofPlanStepSpec):
                steps.append(item)
            elif isinstance(item, Mapping):
                steps.append(ProofPlanStepSpec.from_dict(item))
            else:
                raise ProofPlanError("steps must contain ProofPlanStepSpec values")
        by_id = {step.step_id: step for step in steps}
        if len(by_id) != len(steps):
            raise ProofPlanError("step_id values must be unique")
        object.__setattr__(
            self,
            "steps",
            tuple(sorted(steps, key=lambda step: step.step_id)),
        )
        object.__setattr__(
            self,
            "covered_obligation_ids",
            _string_tuple(
                self.covered_obligation_ids or tuple(
                    step.obligation_id for step in steps
                ),
                "covered_obligation_ids",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "required_obligation_ids",
            _string_tuple(
                self.required_obligation_ids,
                "required_obligation_ids",
                allow_empty=True,
            ),
        )
        alternative_ids = _string_tuple(
            self.alternative_ids or (self.plan_id,),
            "alternative_ids",
        )
        producer_kinds = _string_tuple(
            self.producer_kinds
            or tuple("proof_plan_step" for _ in alternative_ids),
            "producer_kinds",
        )
        if len(alternative_ids) != len(producer_kinds):
            raise ProofPlanError(
                "alternative_ids and producer_kinds must have equal length"
            )
        object.__setattr__(self, "alternative_ids", alternative_ids)
        object.__setattr__(self, "producer_kinds", producer_kinds)
        failures = tuple(
            item
            if isinstance(item, ProofPlanHardFailure)
            else ProofPlanHardFailure.from_dict(item)
            for item in (self.hard_failures or ())
        )
        object.__setattr__(
            self,
            "hard_failures",
            tuple(sorted(failures, key=lambda item: (item.reason.value, item.step_id))),
        )
        bounds = self.bounds
        if isinstance(bounds, Mapping):
            bounds = ResourceBounds.from_dict(bounds)
        elif not isinstance(bounds, ResourceBounds):
            raise ProofPlanError("bounds must be a ResourceBounds")
        object.__setattr__(self, "bounds", bounds)
        object.__setattr__(
            self,
            "root_goal_id",
            _text(
                self.root_goal_id or self.formal_goal_id,
                "root_goal_id",
                maximum=256,
            ),
        )
        object.__setattr__(
            self, "proof_claimed", _bool(self.proof_claimed, "proof_claimed")
        )
        object.__setattr__(
            self,
            "completion_claimed",
            _bool(self.completion_claimed, "completion_claimed"),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    @property
    def step_order(self) -> tuple[str, ...]:
        """Dependency-first topological order (deterministic)."""

        remaining = {
            step.step_id: set(
                dep for dep in step.dependencies if dep in {s.step_id for s in self.steps}
            )
            for step in self.steps
        }
        ordered: list[str] = []
        while remaining:
            ready = sorted(
                step_id
                for step_id, deps in remaining.items()
                if not deps
            )
            if not ready:
                # Cycle or external-only deps — fall back to lexical order.
                return tuple(step.step_id for step in self.steps)
            ordered.extend(ready)
            for step_id in ready:
                del remaining[step_id]
            for deps in remaining.values():
                deps.difference_update(ready)
        return tuple(ordered)

    @property
    def new_assumption_ids(self) -> tuple[str, ...]:
        seen: set[str] = set()
        ordered: list[str] = []
        for step in self.steps:
            for assumption_id in step.new_assumption_ids:
                if assumption_id not in seen:
                    seen.add(assumption_id)
                    ordered.append(assumption_id)
        return tuple(ordered)

    @property
    def resource_classes(self) -> tuple[str, ...]:
        seen: set[str] = set()
        ordered: list[str] = []
        for step in self.steps:
            for resource in step.resources:
                if resource not in seen:
                    seen.add(resource)
                    ordered.append(resource)
        return tuple(ordered)

    @property
    def total_proof_cost(self) -> float:
        return float(sum(step.proof_cost for step in self.steps))

    @property
    def mean_cache_value(self) -> float:
        if not self.steps:
            return 0.0
        return float(sum(step.cache_value for step in self.steps) / len(self.steps))

    @property
    def mean_risk(self) -> float:
        if not self.steps:
            return 1.0
        return float(sum(step.risk for step in self.steps) / len(self.steps))

    @property
    def total_downstream_unlock(self) -> float:
        return float(sum(step.downstream_unlock for step in self.steps))

    @property
    def critical_path_length(self) -> float:
        return float(
            sum(step.critical_path_contribution for step in self.steps)
        )

    @property
    def fallback_quality(self) -> float:
        """Fraction of steps that declare at least one non-empty fallback."""

        if not self.steps:
            return 0.0
        with_fallback = sum(1 for step in self.steps if step.fallback)
        return with_fallback / len(self.steps)

    @property
    def min_step_authority(self) -> AuthorityCeiling:
        if not self.steps:
            return AuthorityCeiling.NONE
        return min(
            (step.authority for step in self.steps),
            key=authority_rank,
        )

    @property
    def admissible(self) -> bool:
        return not self.hard_failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "plan_id": self.plan_id,
            "formal_goal_id": self.formal_goal_id,
            "graph_id": self.graph_id,
            "tree_id": self.tree_id,
            "steps": [step.to_dict() for step in self.steps],
            "covered_obligation_ids": list(self.covered_obligation_ids),
            "required_obligation_ids": list(self.required_obligation_ids),
            "alternative_ids": list(self.alternative_ids),
            "producer_kinds": list(self.producer_kinds),
            "hard_failures": [item.to_dict() for item in self.hard_failures],
            "bounds": self.bounds.to_dict(),
            "root_goal_id": self.root_goal_id,
            "proof_claimed": False,
            "completion_claimed": False,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "MissingProofPlanAlternative":
        if not isinstance(payload, Mapping):
            raise ProofPlanError("plan alternative payload must be an object")
        bounds_raw = payload.get("bounds") or {}
        return cls(
            plan_id=payload.get("plan_id", ""),
            formal_goal_id=payload.get("formal_goal_id", ""),
            graph_id=payload.get("graph_id", ""),
            tree_id=payload.get("tree_id", ""),
            steps=tuple(payload.get("steps") or ()),
            covered_obligation_ids=tuple(
                payload.get("covered_obligation_ids") or ()
            ),
            required_obligation_ids=tuple(
                payload.get("required_obligation_ids") or ()
            ),
            alternative_ids=tuple(payload.get("alternative_ids") or ()),
            producer_kinds=tuple(payload.get("producer_kinds") or ()),
            hard_failures=tuple(payload.get("hard_failures") or ()),
            bounds=(
                ResourceBounds.from_dict(bounds_raw)
                if isinstance(bounds_raw, Mapping) and bounds_raw.get("schema")
                else (
                    ResourceBounds(**{
                        k: v
                        for k, v in bounds_raw.items()
                        if k
                        in {
                            "wall_time_ms",
                            "memory_bytes",
                            "max_steps",
                            "max_depth",
                            "max_nodes",
                            "max_candidates",
                            "model_token_limit",
                            "network_allowed",
                            "extra",
                        }
                    })
                    if isinstance(bounds_raw, Mapping)
                    else DEFAULT_BOUNDS
                )
            ),
            root_goal_id=payload.get("root_goal_id", ""),
            proof_claimed=bool(payload.get("proof_claimed", False)),
            completion_claimed=bool(payload.get("completion_claimed", False)),
            metadata=payload.get("metadata") or {},
        )


# ---------------------------------------------------------------------------
# Hard prune + soft score
# ---------------------------------------------------------------------------


def collect_hard_failures(
    plan: MissingProofPlanAlternative,
    policy: ProofPlanRankingPolicy,
) -> tuple[ProofPlanHardFailure, ...]:
    """Return every non-compensable failure for a plan alternative."""

    failures: list[ProofPlanHardFailure] = []

    if plan.proof_claimed:
        failures.append(
            ProofPlanHardFailure(
                reason=HardPruneReason.PROOF_CLAIM,
                reason_codes=("plan_proof_claimed",),
                detail="plans cannot claim proof",
            )
        )
    if plan.completion_claimed:
        failures.append(
            ProofPlanHardFailure(
                reason=HardPruneReason.COMPLETION_CLAIM,
                reason_codes=("plan_completion_claimed",),
                detail="plans cannot claim goal completion",
            )
        )
    if not plan.steps:
        failures.append(
            ProofPlanHardFailure(
                reason=HardPruneReason.EMPTY_PLAN,
                reason_codes=("no_steps",),
                detail="plan has no steps",
            )
        )
        return tuple(failures)

    step_ids = {step.step_id for step in plan.steps}
    depends = {step.step_id: step.dependencies for step in plan.steps}
    if _detect_cycle(
        {
            sid: tuple(dep for dep in deps if dep in step_ids)
            for sid, deps in depends.items()
        }
    ):
        failures.append(
            ProofPlanHardFailure(
                reason=HardPruneReason.CYCLIC_DEPENDENCIES,
                reason_codes=("dependency_cycle",),
                detail="step dependency graph contains a cycle",
            )
        )

    for step in plan.steps:
        if step.proof_claimed:
            failures.append(
                ProofPlanHardFailure(
                    reason=HardPruneReason.PROOF_CLAIM,
                    reason_codes=("step_proof_claimed",),
                    step_id=step.step_id,
                    detail=f"step {step.step_id} claims proof",
                )
            )
        if step.completion_claimed:
            failures.append(
                ProofPlanHardFailure(
                    reason=HardPruneReason.COMPLETION_CLAIM,
                    reason_codes=("step_completion_claimed",),
                    step_id=step.step_id,
                    detail=f"step {step.step_id} claims completion",
                )
            )
        missing = step.missing_required_fields()
        if missing:
            failures.append(
                ProofPlanHardFailure(
                    reason=HardPruneReason.INCOMPLETE_STEP,
                    reason_codes=tuple(f"missing_{name}" for name in missing),
                    step_id=step.step_id,
                    detail=(
                        f"step {step.step_id} incomplete: "
                        + ", ".join(missing)
                    ),
                )
            )
        unknown = [
            dep for dep in step.dependencies if dep not in step_ids
        ]
        # External deps are allowed only when marked satisfied by policy or
        # declared as root-external via the "external:" prefix.
        unresolved = [
            dep
            for dep in unknown
            if dep not in policy.satisfied_dependencies
            and not dep.startswith("external:")
            and not dep.startswith("root:")
        ]
        if unresolved:
            failures.append(
                ProofPlanHardFailure(
                    reason=HardPruneReason.UNKNOWN_DEPENDENCY,
                    reason_codes=tuple(
                        f"unknown_dep:{dep}" for dep in sorted(unresolved)
                    ),
                    step_id=step.step_id,
                    detail=(
                        f"step {step.step_id} references unknown dependencies"
                    ),
                )
            )
        if not authority_meets_minimum(
            step.authority, policy.minimum_authority
        ):
            failures.append(
                ProofPlanHardFailure(
                    reason=HardPruneReason.INSUFFICIENT_AUTHORITY,
                    reason_codes=(
                        f"authority:{step.authority.value}",
                        f"minimum:{policy.minimum_authority.value}",
                    ),
                    step_id=step.step_id,
                    detail=(
                        f"step {step.step_id} authority "
                        f"{step.authority.value} below minimum "
                        f"{policy.minimum_authority.value}"
                    ),
                )
            )

    required = set(policy.required_obligation_ids or plan.required_obligation_ids)
    if required:
        covered = set(plan.covered_obligation_ids)
        missing_cov = sorted(required - covered)
        if missing_cov:
            failures.append(
                ProofPlanHardFailure(
                    reason=HardPruneReason.MISSING_COVERAGE,
                    reason_codes=tuple(
                        f"uncovered:{oid}" for oid in missing_cov
                    ),
                    detail=(
                        "plan fails to cover required obligations: "
                        + ", ".join(missing_cov)
                    ),
                )
            )

    if (
        plan.bounds.max_candidates
        and len(plan.steps) > plan.bounds.max_candidates
    ):
        failures.append(
            ProofPlanHardFailure(
                reason=HardPruneReason.RESOURCE_BOUND,
                reason_codes=("max_candidates_exceeded",),
                detail="plan exceeds max_candidates resource bound",
            )
        )

    if (
        policy.max_new_assumptions
        and len(plan.new_assumption_ids) > policy.max_new_assumptions
    ):
        failures.append(
            ProofPlanHardFailure(
                reason=HardPruneReason.RESOURCE_BOUND,
                reason_codes=("max_new_assumptions_exceeded",),
                detail=(
                    f"plan introduces {len(plan.new_assumption_ids)} "
                    f"assumptions exceeding max {policy.max_new_assumptions}"
                ),
            )
        )

    # Stable unique by (reason, step_id, reason_codes)
    unique: dict[tuple[Any, ...], ProofPlanHardFailure] = {}
    for failure in failures:
        key = (
            failure.reason.value,
            failure.step_id,
            failure.reason_codes,
        )
        unique[key] = failure
    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (item.reason.value, item.step_id, item.reason_codes),
        )
    )


def with_hard_failures(
    plan: MissingProofPlanAlternative,
    policy: ProofPlanRankingPolicy,
) -> MissingProofPlanAlternative:
    """Return a copy of ``plan`` with computed hard failures attached."""

    failures = collect_hard_failures(plan, policy)
    if failures == plan.hard_failures:
        return plan
    return MissingProofPlanAlternative(
        plan_id=plan.plan_id,
        formal_goal_id=plan.formal_goal_id,
        graph_id=plan.graph_id,
        tree_id=plan.tree_id,
        steps=plan.steps,
        covered_obligation_ids=plan.covered_obligation_ids,
        required_obligation_ids=plan.required_obligation_ids,
        alternative_ids=plan.alternative_ids,
        producer_kinds=plan.producer_kinds,
        hard_failures=failures,
        bounds=plan.bounds,
        root_goal_id=plan.root_goal_id,
        proof_claimed=False,
        completion_claimed=False,
        metadata=plan.metadata,
    )


def score_missing_proof_plan(
    plan: MissingProofPlanAlternative,
    policy: ProofPlanRankingPolicy,
) -> tuple[int, Mapping[str, int], tuple[str, ...]]:
    """Soft-score an *admissible* plan.  Hard-pruned plans score ``None``.

    Returns ``(score_millionths, soft_scores, rationale)``.
    """

    if plan.hard_failures:
        raise ProofPlanError(
            "hard-pruned plans must not receive a soft score; "
            f"failures={[f.reason.value for f in plan.hard_failures]}"
        )

    required = set(policy.required_obligation_ids or plan.required_obligation_ids)
    covered = set(plan.covered_obligation_ids)
    if required:
        coverage_ratio = Decimal(len(required & covered)) / Decimal(len(required))
    elif covered:
        coverage_ratio = Decimal(1)
    else:
        coverage_ratio = Decimal(0)

    # Assumption cost: each new assumption costs ``assumption_unit_cost`` of
    # the soft factor; many assumptions drive the factor toward zero.
    assumption_count = len(plan.new_assumption_ids)
    assumption_penalty = min(
        Decimal(1),
        Decimal(assumption_count) * Decimal(str(policy.assumption_unit_cost)),
    )
    assumption_factor = Decimal(1) - assumption_penalty

    available = {item.casefold() for item in policy.available_resource_classes}
    required_resources = {item.casefold() for item in plan.resource_classes}
    if available and required_resources:
        resource_hit = Decimal(len(required_resources & available)) / Decimal(
            len(required_resources)
        )
    else:
        resource_hit = Decimal(1)

    # Authority factor: min step authority relative to minimum (at least 1.0
    # when meeting minimum; stronger authorities score higher up to 1.0).
    min_auth = plan.min_step_authority
    min_rank = authority_rank(policy.minimum_authority)
    plan_rank = authority_rank(min_auth)
    if min_rank <= 0:
        authority_factor = Decimal(1)
    else:
        # At minimum: ~0.7; at theorem: 1.0; below minimum never scored.
        span = max(1, max(_AUTHORITY_RANK.values()) - min_rank)
        authority_factor = Decimal("0.7") + Decimal("0.3") * Decimal(
            max(0, plan_rank - min_rank)
        ) / Decimal(span)
        if authority_factor > 1:
            authority_factor = Decimal(1)

    # Critical path: shorter is better (bounded inverse).
    critical_factor = Decimal(1) / (
        Decimal(1) + Decimal(str(plan.critical_path_length))
    )

    factors: dict[str, Decimal] = {
        "discharged_coverage": coverage_ratio,
        "downstream_unlock": _bounded_benefit(plan.total_downstream_unlock),
        "critical_path": critical_factor,
        "authority": authority_factor,
        "assumption_cost": assumption_factor,
        "risk": Decimal(1) - Decimal(str(plan.mean_risk)),
        "proof_cost": Decimal(1)
        / (Decimal(1) + Decimal(str(plan.total_proof_cost))),
        "cache_value": Decimal(str(plan.mean_cache_value)),
        "fallback_quality": Decimal(str(plan.fallback_quality))
        * resource_hit,  # fallbacks that need unavailable resources degrade
    }

    weights = policy.weights
    weighted: list[tuple[str, Decimal]] = []
    for name in RANKING_SCORE_DIMENSIONS:
        weight = Decimal(str(getattr(weights, name)))
        factor = factors[name]
        weighted.append((name, weight * factor / weights.total))

    score = sum((contribution for _, contribution in weighted), Decimal(0))
    score_millionths = _to_millionths(score)
    soft_scores = {
        name: _to_millionths(factor) for name, factor in factors.items()
    }
    rationale = tuple(
        f"{name} contributes {_to_millionths(contribution)} millionths "
        f"(factor={soft_scores[name]})"
        for name, contribution in weighted
    ) + (
        f"assumption count is {assumption_count} "
        f"(unit_cost={policy.assumption_unit_cost})",
        f"min step authority is {min_auth.value}",
        f"covers {len(covered)} obligation(s)",
        f"total deterministic proof-plan priority is {score_millionths} millionths",
    )
    return score_millionths, MappingProxyType(soft_scores), rationale


# ---------------------------------------------------------------------------
# Ranking results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RankedProofPlan:
    """One evaluated alternative with score and explainable rationale."""

    SCHEMA: ClassVar[str] = RANKED_PROOF_PLAN_SCHEMA

    plan: MissingProofPlanAlternative
    score_millionths: int | None
    soft_scores: Mapping[str, int] = field(default_factory=dict)
    rationale: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.plan, MissingProofPlanAlternative):
            raise ProofPlanError("plan must be a MissingProofPlanAlternative")
        if self.plan.admissible != (self.score_millionths is not None):
            raise ProofPlanError(
                "hard-pruned plans must not receive a soft score"
            )
        if self.score_millionths is not None:
            object.__setattr__(
                self,
                "score_millionths",
                _nonnegative_int(self.score_millionths, "score_millionths"),
            )
            scores = dict(self.soft_scores)
            if set(scores) != set(RANKING_SCORE_DIMENSIONS):
                raise ProofPlanError(
                    "admissible plan is missing a ranking soft-score dimension"
                )
            object.__setattr__(self, "soft_scores", MappingProxyType(scores))
            rationale = tuple(
                str(item).strip() for item in self.rationale if str(item).strip()
            )
            if not rationale:
                raise ProofPlanError("ranked plans require a rationale")
            object.__setattr__(self, "rationale", rationale)
        else:
            if self.soft_scores:
                raise ProofPlanError(
                    "hard-pruned plan cannot contain soft scores"
                )
            object.__setattr__(self, "soft_scores", MappingProxyType({}))
            # Hard-pruned plans still carry an explainable prune rationale.
            rationale = tuple(
                str(item).strip() for item in self.rationale if str(item).strip()
            )
            if not rationale:
                rationale = tuple(
                    f"hard-pruned: {failure.reason.value}"
                    + (f" ({failure.detail})" if failure.detail else "")
                    for failure in self.plan.hard_failures
                ) or ("hard-pruned: unknown",)
            object.__setattr__(self, "rationale", rationale)

    @property
    def plan_id(self) -> str:
        return self.plan.plan_id

    @property
    def admissible(self) -> bool:
        return self.score_millionths is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "plan": self.plan.to_dict(),
            "score_millionths": self.score_millionths,
            "soft_scores": dict(sorted(self.soft_scores.items())),
            "rationale": list(self.rationale),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RankedProofPlan":
        if not isinstance(payload, Mapping):
            raise ProofPlanError("ranked plan payload must be an object")
        return cls(
            plan=MissingProofPlanAlternative.from_dict(
                payload.get("plan") or {}
            ),
            score_millionths=payload.get("score_millionths"),
            soft_scores=payload.get("soft_scores") or {},
            rationale=tuple(payload.get("rationale") or ()),
        )


@dataclass(frozen=True, slots=True)
class ProofPlanRankingResult:
    """Selected plan and rejected / pruned alternatives in deterministic order."""

    SCHEMA: ClassVar[str] = PROOF_PLAN_RANKING_RESULT_SCHEMA

    selected: RankedProofPlan | None
    ranked: tuple[RankedProofPlan, ...]
    pruned: tuple[RankedProofPlan, ...]
    policy: ProofPlanRankingPolicy
    evaluator_version: str = RANKER_ALGORITHM_VERSION
    interface: str = GOAL_DIRECTED_PROOF_PLAN_RANKER_INTERFACE

    def __post_init__(self) -> None:
        if any(item.score_millionths is None for item in self.ranked):
            raise ProofPlanError("ranked plans must be scored")
        if any(item.score_millionths is not None for item in self.pruned):
            raise ProofPlanError("pruned plans must be unscored")
        if self.selected != (self.ranked[0] if self.ranked else None):
            raise ProofPlanError(
                "selected plan must be the first deterministic rank"
            )
        ids = [item.plan_id for item in (*self.ranked, *self.pruned)]
        if len(ids) != len(set(ids)):
            raise ProofPlanError("ranking result contains duplicate plan ids")
        if not isinstance(self.policy, ProofPlanRankingPolicy):
            raise ProofPlanError("policy must be a ProofPlanRankingPolicy")

    @property
    def rejected(self) -> tuple[RankedProofPlan, ...]:
        """Admissible plans that lost the ranking, plus hard-pruned ones."""

        if not self.ranked:
            return self.pruned
        return (*self.ranked[1:], *self.pruned)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "interface": self.interface,
            "evaluator_version": self.evaluator_version,
            "selected": self.selected.to_dict() if self.selected else None,
            "ranked": [item.to_dict() for item in self.ranked],
            "pruned": [item.to_dict() for item in self.pruned],
            "policy": self.policy.to_dict(),
        }

    def to_goal_directed_proof_plan(self) -> GoalDirectedProofPlan | None:
        """Materialize the selected alternative as ``GoalDirectedProofPlan@1``."""

        if self.selected is None:
            return None
        plan = self.selected.plan
        candidates = tuple(
            step.to_candidate_proof_step(
                tree_id=plan.tree_id,
                rank_score_millionths=int(self.selected.score_millionths or 0),
            )
            for step in plan.steps
        )
        try:
            return GoalDirectedProofPlan(
                plan_id=plan.plan_id,
                formal_goal_id=plan.formal_goal_id,
                graph_id=plan.graph_id,
                tree_id=plan.tree_id,
                candidates=candidates,
                step_order=plan.step_order,
                status=PlanStatus.RANKED,
                bounds=plan.bounds,
                provider_ids=tuple(
                    sorted(
                        {
                            provider
                            for step in plan.steps
                            for provider in step.provider_ids
                        }
                    )
                ),
                rank_score_millionths=int(self.selected.score_millionths or 0),
                root_goal_id=plan.root_goal_id,
                authority=AuthorityCeiling.CANDIDATE,
                proof_claimed=False,
                completion_claimed=False,
                metadata={
                    "ranker": self.evaluator_version,
                    "interface": self.interface,
                    "soft_scores": dict(self.selected.soft_scores),
                    "rationale": list(self.selected.rationale),
                },
            )
        except TacticianContractError as error:
            raise ProofPlanError(
                f"failed to build GoalDirectedProofPlan: {error}"
            ) from error


# ---------------------------------------------------------------------------
# Ranker
# ---------------------------------------------------------------------------


class GoalDirectedProofPlanRanker:
    """``GoalDirectedProofPlanRanker@1`` — construct, hard-prune, and rank.

    Owns proof-plan construction and ranking.  Reuses plan-evaluator scoring
    primitives via explicit adapters without mutating implementation-task
    routing.
    """

    INTERFACE: ClassVar[str] = GOAL_DIRECTED_PROOF_PLAN_RANKER_INTERFACE
    ALGORITHM_VERSION: ClassVar[str] = RANKER_ALGORITHM_VERSION

    def __init__(
        self,
        *,
        policy: ProofPlanRankingPolicy | Mapping[str, Any] | None = None,
        bounds: ResourceBounds | Mapping[str, Any] | None = None,
    ) -> None:
        if policy is None:
            resolved_policy = ProofPlanRankingPolicy()
        elif isinstance(policy, ProofPlanRankingPolicy):
            resolved_policy = policy
        elif isinstance(policy, Mapping):
            resolved_policy = ProofPlanRankingPolicy.from_dict(policy)
        else:
            raise ProofPlanError("policy must be a ProofPlanRankingPolicy")
        self.policy = resolved_policy
        if bounds is None:
            self.bounds = DEFAULT_BOUNDS
        elif isinstance(bounds, ResourceBounds):
            self.bounds = bounds
        elif isinstance(bounds, Mapping):
            self.bounds = ResourceBounds.from_dict(bounds)
        else:
            raise ProofPlanError("bounds must be a ResourceBounds")

    def rank(
        self,
        alternatives: Iterable[
            MissingProofPlanAlternative | Mapping[str, Any]
        ],
        *,
        policy: ProofPlanRankingPolicy | Mapping[str, Any] | None = None,
    ) -> ProofPlanRankingResult:
        """Hard-prune invalid alternatives, then soft-score the admissible set."""

        resolved_policy = self._resolve_policy(policy)
        normalized: list[MissingProofPlanAlternative] = []
        for item in alternatives:
            if isinstance(item, MissingProofPlanAlternative):
                plan = item
            elif isinstance(item, Mapping):
                plan = MissingProofPlanAlternative.from_dict(item)
            else:
                raise ProofPlanError(
                    "alternatives must be MissingProofPlanAlternative values"
                )
            normalized.append(with_hard_failures(plan, resolved_policy))

        if not normalized:
            raise ProofPlanError(
                "at least one missing-proof plan alternative is required"
            )
        ids = [item.plan_id for item in normalized]
        duplicates = sorted({pid for pid in ids if ids.count(pid) > 1})
        if duplicates:
            raise ProofPlanError(
                "plan ids must be unique: " + ", ".join(duplicates)
            )

        evaluated: list[RankedProofPlan] = []
        for plan in normalized:
            if plan.hard_failures:
                evaluated.append(
                    RankedProofPlan(
                        plan=plan,
                        score_millionths=None,
                        soft_scores={},
                        rationale=tuple(
                            f"hard-pruned: {failure.reason.value}"
                            + (
                                f" step={failure.step_id}"
                                if failure.step_id
                                else ""
                            )
                            + (f" — {failure.detail}" if failure.detail else "")
                            for failure in plan.hard_failures
                        ),
                    )
                )
            else:
                score, soft, rationale = score_missing_proof_plan(
                    plan, resolved_policy
                )
                evaluated.append(
                    RankedProofPlan(
                        plan=plan,
                        score_millionths=score,
                        soft_scores=dict(soft),
                        rationale=rationale,
                    )
                )

        ranked = tuple(
            sorted(
                (item for item in evaluated if item.score_millionths is not None),
                key=lambda item: (
                    -int(item.score_millionths or 0),
                    item.plan_id,
                    json.dumps(
                        item.plan.to_dict(),
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ),
                ),
            )
        )
        # Annotate non-winners with comparative rejection rationale.
        if ranked:
            winner = ranked[0]
            annotated: list[RankedProofPlan] = [winner]
            for item in ranked[1:]:
                annotated.append(
                    RankedProofPlan(
                        plan=item.plan,
                        score_millionths=item.score_millionths,
                        soft_scores=dict(item.soft_scores),
                        rationale=(
                            *item.rationale,
                            f"rejected in favor of {winner.plan_id!r} by "
                            f"{int(winner.score_millionths or 0) - int(item.score_millionths or 0)} "
                            "priority millionths",
                        ),
                    )
                )
            ranked = tuple(annotated)

        pruned = tuple(
            sorted(
                (item for item in evaluated if item.score_millionths is None),
                key=lambda item: (
                    tuple(
                        (f.reason.value, f.step_id, f.reason_codes)
                        for f in item.plan.hard_failures
                    ),
                    item.plan_id,
                ),
            )
        )
        return ProofPlanRankingResult(
            selected=ranked[0] if ranked else None,
            ranked=ranked,
            pruned=pruned,
            policy=resolved_policy,
            evaluator_version=self.ALGORITHM_VERSION,
            interface=self.INTERFACE,
        )

    def _resolve_policy(
        self,
        policy: ProofPlanRankingPolicy | Mapping[str, Any] | None,
    ) -> ProofPlanRankingPolicy:
        if policy is None:
            return self.policy
        if isinstance(policy, ProofPlanRankingPolicy):
            return policy
        if isinstance(policy, Mapping):
            return ProofPlanRankingPolicy.from_dict(policy)
        raise ProofPlanError("policy must be a ProofPlanRankingPolicy")


def rank_missing_proof_plans(
    alternatives: Iterable[MissingProofPlanAlternative | Mapping[str, Any]],
    *,
    policy: ProofPlanRankingPolicy | Mapping[str, Any] | None = None,
    bounds: ResourceBounds | Mapping[str, Any] | None = None,
) -> ProofPlanRankingResult:
    """Convenience entry point for ``GoalDirectedProofPlanRanker@1``."""

    return GoalDirectedProofPlanRanker(policy=policy, bounds=bounds).rank(
        alternatives, policy=policy
    )


# ---------------------------------------------------------------------------
# Construction helpers
# ---------------------------------------------------------------------------


def complete_step(
    step_id: str,
    obligation_id: str,
    *,
    kind: StepKind | str = StepKind.SOLVE,
    statement: str = "",
    dependencies: Sequence[str] = ("root:goal",),
    expected_receipts: Sequence[str] | None = None,
    validation: Sequence[str] | None = None,
    fallback: Sequence[str] | None = None,
    resources: Sequence[str] = ("solver",),
    completion_conditions: Sequence[str] | None = None,
    authority: AuthorityCeiling | str = AuthorityCeiling.BOUNDED,
    new_assumption_ids: Sequence[str] = (),
    provider_ids: Sequence[str] = (),
    proof_cost: float = 1.0,
    cache_value: float = 0.5,
    risk: float = 0.2,
    downstream_unlock: float = 1.0,
    critical_path_contribution: float = 1.0,
    root: bool = False,
    metadata: Mapping[str, Any] | None = None,
) -> ProofPlanStepSpec:
    """Build a complete step with sensible defaults for every required field."""

    meta = dict(metadata or {})
    if root:
        meta["root"] = True
        dependencies = ()
    receipts = (
        tuple(expected_receipts)
        if expected_receipts is not None
        else (f"receipt:{obligation_id}",)
    )
    validation_cmds = (
        tuple(validation)
        if validation is not None
        else (f"validate:{obligation_id}",)
    )
    fallbacks = (
        tuple(fallback)
        if fallback is not None
        else (f"fallback:replay:{obligation_id}",)
    )
    conditions = (
        tuple(completion_conditions)
        if completion_conditions is not None
        else (f"{obligation_id}:discharged",)
    )
    return ProofPlanStepSpec(
        step_id=step_id,
        obligation_id=obligation_id,
        kind=kind,  # type: ignore[arg-type]
        statement=statement or f"close {obligation_id}",
        dependencies=tuple(dependencies),
        expected_receipts=receipts,
        validation=validation_cmds,
        fallback=fallbacks,
        resources=tuple(resources),
        completion_conditions=conditions,
        authority=authority,  # type: ignore[arg-type]
        new_assumption_ids=tuple(new_assumption_ids),
        provider_ids=tuple(provider_ids),
        proof_cost=proof_cost,
        cache_value=cache_value,
        risk=risk,
        downstream_unlock=downstream_unlock,
        critical_path_contribution=critical_path_contribution,
        proof_claimed=False,
        completion_claimed=False,
        metadata=meta,
    )


def build_missing_proof_plan(
    plan_id: str,
    *,
    formal_goal_id: str,
    graph_id: str,
    tree_id: str,
    steps: Sequence[ProofPlanStepSpec | Mapping[str, Any]],
    required_obligation_ids: Sequence[str] = (),
    covered_obligation_ids: Sequence[str] | None = None,
    alternative_ids: Sequence[str] | None = None,
    producer_kinds: Sequence[str] | None = None,
    bounds: ResourceBounds | None = None,
    root_goal_id: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> MissingProofPlanAlternative:
    """Construct one complete missing-proof plan alternative."""

    normalized_steps = tuple(
        item
        if isinstance(item, ProofPlanStepSpec)
        else ProofPlanStepSpec.from_dict(item)
        for item in steps
    )
    covered = (
        tuple(covered_obligation_ids)
        if covered_obligation_ids is not None
        else tuple(step.obligation_id for step in normalized_steps)
    )
    required = tuple(required_obligation_ids) or covered
    return MissingProofPlanAlternative(
        plan_id=plan_id,
        formal_goal_id=formal_goal_id,
        graph_id=graph_id,
        tree_id=tree_id,
        steps=normalized_steps,
        covered_obligation_ids=covered,
        required_obligation_ids=required,
        alternative_ids=tuple(alternative_ids or (plan_id,)),
        producer_kinds=tuple(
            producer_kinds
            or tuple("proof_plan_step" for _ in (alternative_ids or (plan_id,)))
        ),
        hard_failures=(),
        bounds=bounds or DEFAULT_BOUNDS,
        root_goal_id=root_goal_id or formal_goal_id,
        proof_claimed=False,
        completion_claimed=False,
        metadata=dict(metadata or {}),
    )


# ---------------------------------------------------------------------------
# Plan-evaluator adapters (reuse existing scoring primitives)
# ---------------------------------------------------------------------------


def to_and_or_plan_branch(plan: MissingProofPlanAlternative) -> dict[str, Any]:
    """Project a plan alternative onto the closed AND/OR branch schema.

    Returns a mapping accepted by ``AndOrPlanBranch.from_dict`` /
    ``evaluate_and_or_plan_branches``.  Hard failures map onto the closed
    ``PlanSearchHardConstraint`` vocabulary.
    """

    constraint_map = {
        HardPruneReason.INSUFFICIENT_AUTHORITY: "authority",
        HardPruneReason.UNKNOWN_DEPENDENCY: "dependency",
        HardPruneReason.CYCLIC_DEPENDENCIES: "dependency",
        HardPruneReason.MISSING_COVERAGE: "scope",
        HardPruneReason.RESOURCE_BOUND: "resource",
        HardPruneReason.INCOMPLETE_STEP: "validation",
        HardPruneReason.INVALID_STRUCTURE: "validation",
        HardPruneReason.EMPTY_PLAN: "validation",
        HardPruneReason.PROOF_CLAIM: "proof",
        HardPruneReason.COMPLETION_CLAIM: "proof",
    }
    # At most one hard failure per constraint (AND/OR evaluator rule).
    by_constraint: dict[str, list[str]] = {}
    for failure in plan.hard_failures:
        constraint = constraint_map.get(failure.reason, "validation")
        codes = list(failure.reason_codes) or [failure.reason.value]
        by_constraint.setdefault(constraint, []).extend(codes)
    hard_failures = [
        {
            "constraint": constraint,
            "reason_codes": sorted(set(codes)),
        }
        for constraint, codes in sorted(by_constraint.items())
    ]
    cost_micro = max(0, int(round(plan.total_proof_cost * 1_000_000)))
    risk_millionths = max(
        0, min(1_000_000, int(round(plan.mean_risk * 1_000_000)))
    )
    # Assumption cost surfaces as historical_failure-like soft penalty input.
    assumption_penalty = min(
        1_000_000, len(plan.new_assumption_ids) * 100_000
    )
    return {
        "branch_id": plan.plan_id,
        "goal_content_id": plan.formal_goal_id,
        "repository_tree_id": plan.tree_id,
        "context_id": plan.graph_id,
        "alternative_ids": list(plan.alternative_ids),
        "producer_kinds": list(plan.producer_kinds),
        "required_obligation_ids": list(
            plan.required_obligation_ids or plan.covered_obligation_ids
        ),
        "covered_obligation_ids": list(plan.covered_obligation_ids),
        "required_uncertainty_ids": list(plan.new_assumption_ids),
        "reduced_uncertainty_ids": [],
        "critical_path_length": max(0, int(round(plan.critical_path_length))),
        "conflict_risk_millionths": risk_millionths,
        "estimated_cost_microunits": cost_micro,
        "estimated_tokens": 0,
        "estimated_time_milliseconds": 0,
        "historical_failure_millionths": assumption_penalty,
        "hard_failures": hard_failures,
    }


def to_proof_aware_plan_candidate(
    plan: MissingProofPlanAlternative,
    *,
    summary: str | None = None,
) -> dict[str, Any]:
    """Project a plan onto the proof-aware plan-evaluator candidate schema.

    Returns a mapping accepted by ``ProofAwarePlanCandidate.from_dict`` /
    ``evaluate_proof_aware_plans``.  Branch fields satisfy the closed
    ``PlanBranch`` contract used by the supervisor plan evaluator.
    """

    if plan.hard_failures:
        raise ProofPlanError(
            "cannot project a hard-pruned plan to a proof-aware candidate"
        )
    branch_id = plan.plan_id
    predicted_files = [
        f"proof/{plan.formal_goal_id}/{step.step_id}.lean"
        for step in plan.steps
    ] or [f"proof/{plan.formal_goal_id}/plan.lean"]
    predicted_symbols = [
        f"{plan.formal_goal_id}.{step.step_id}" for step in plan.steps
    ] or [plan.formal_goal_id]
    validation_commands = [
        cmd for step in plan.steps for cmd in step.validation
    ] or ["validate:proof-plan"]
    validation_proof = [
        f"step {step.step_id} expects {', '.join(step.expected_receipts)}"
        for step in plan.steps
    ] or ["plan declares expected receipts"]
    dependencies = sorted(
        {
            dep
            for step in plan.steps
            for dep in step.dependencies
            if dep.startswith("external:") or dep.startswith("root:")
        }
    ) or ["root:goal"]
    return {
        "candidate_id": branch_id,
        "branch": {
            "branch_id": branch_id,
            "summary": summary
            or f"Missing-proof plan {plan.plan_id} for {plan.formal_goal_id}",
            "predicted_files": predicted_files,
            "predicted_symbols": predicted_symbols,
            "dependencies": dependencies,
            "validation_commands": validation_commands,
            "validation_proof": validation_proof,
            "estimated_cost": max(0.01, plan.total_proof_cost),
            "risk": plan.mean_risk,
            "expected_objective_delta": min(
                1.0, max(0.0, plan.fallback_quality)
            ),
            "source": "goal_directed_proof_plan_ranker",
        },
        "obligation_impact": list(
            plan.covered_obligation_ids
            or tuple(step.obligation_id for step in plan.steps)
        ),
        "required_assurance": plan.min_step_authority.value,
        "proof_cost": plan.total_proof_cost,
        "cache_likelihood": plan.mean_cache_value,
        "dependencies": dependencies,
        "expected_evidence_delta": [
            receipt
            for step in plan.steps
            for receipt in step.expected_receipts
        ]
        or [f"receipt:{plan.plan_id}"],
        "resource_classes": list(plan.resource_classes) or ["solver"],
        "proof_critical_path": plan.critical_path_length,
        "downstream_unlock_value": plan.total_downstream_unlock,
        "risk": plan.mean_risk,
        "freshness": 1.0,
    }


def rank_via_and_or_evaluator(
    alternatives: Iterable[MissingProofPlanAlternative | Mapping[str, Any]],
    *,
    policy: ProofPlanRankingPolicy | Mapping[str, Any] | None = None,
) -> Any:
    """Hard-prune locally, then rank admitted branches with the AND/OR evaluator.

    Lazy-imports ``evaluate_and_or_plan_branches`` so the datasets package
    remains importable without the supervisor on the path.  Local hard failures
    are projected onto the evaluator's closed hard-constraint vocabulary.
    """

    try:
        from ipfs_accelerate_py.agent_supervisor.planning.plan_evaluator import (
            evaluate_and_or_plan_branches,
        )
    except ImportError as error:  # pragma: no cover - environment specific
        raise ProofPlanError(
            "plan-evaluator AND/OR adapter requires ipfs_accelerate_py"
        ) from error

    resolved_policy = (
        policy
        if isinstance(policy, ProofPlanRankingPolicy)
        else (
            ProofPlanRankingPolicy.from_dict(policy)
            if isinstance(policy, Mapping)
            else ProofPlanRankingPolicy()
        )
    )
    plans = [
        with_hard_failures(
            item
            if isinstance(item, MissingProofPlanAlternative)
            else MissingProofPlanAlternative.from_dict(item),
            resolved_policy,
        )
        for item in alternatives
    ]
    if not plans:
        raise ProofPlanError("at least one plan alternative is required")
    branches = [to_and_or_plan_branch(plan) for plan in plans]
    return evaluate_and_or_plan_branches(branches)


def rank_via_proof_aware_evaluator(
    alternatives: Iterable[MissingProofPlanAlternative | Mapping[str, Any]],
    *,
    policy: ProofPlanRankingPolicy | Mapping[str, Any] | None = None,
) -> Any:
    """Hard-prune locally, then rank admitted plans with the proof-aware evaluator.

    Hard-pruned plans are excluded from soft scoring (the proof-aware
    evaluator has no hard-failure channel); callers that need the pruned set
    should use :func:`rank_missing_proof_plans` and adapt winners only.
    """

    try:
        from ipfs_accelerate_py.agent_supervisor.planning.plan_evaluator import (
            ProofAwarePlanPolicy,
            evaluate_proof_aware_plans,
        )
    except ImportError as error:  # pragma: no cover - environment specific
        raise ProofPlanError(
            "plan-evaluator proof-aware adapter requires ipfs_accelerate_py"
        ) from error

    resolved_policy = (
        policy
        if isinstance(policy, ProofPlanRankingPolicy)
        else (
            ProofPlanRankingPolicy.from_dict(policy)
            if isinstance(policy, Mapping)
            else ProofPlanRankingPolicy()
        )
    )
    plans = [
        with_hard_failures(
            item
            if isinstance(item, MissingProofPlanAlternative)
            else MissingProofPlanAlternative.from_dict(item),
            resolved_policy,
        )
        for item in alternatives
    ]
    admitted = [plan for plan in plans if plan.admissible]
    if not admitted:
        raise ProofPlanError(
            "no admissible plan remains after hard pruning; "
            "cannot invoke proof-aware evaluator"
        )
    candidates = [to_proof_aware_plan_candidate(plan) for plan in admitted]
    return evaluate_proof_aware_plans(
        candidates,
        policy=ProofAwarePlanPolicy(
            available_resource_classes=resolved_policy.available_resource_classes,
            satisfied_dependencies=resolved_policy.satisfied_dependencies,
        ),
    )


def every_step_names_required_fields(
    plan: MissingProofPlanAlternative,
) -> bool:
    """True when every step names all acceptance-required completeness fields."""

    return all(step.is_complete() for step in plan.steps)


def rankings_are_deterministic(
    left: ProofPlanRankingResult,
    right: ProofPlanRankingResult,
) -> bool:
    """Structural equality of ranking payloads (explainable + stable)."""

    return left.to_dict() == right.to_dict()


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "GOAL_DIRECTED_PROOF_PLAN_RANKER_INTERFACE",
    "GOAL_DIRECTED_PROOF_PLAN_INTERFACE",
    "GOAL_DIRECTED_PROOF_PLAN_SCHEMA",
    "PROOF_PLAN_STEP_SPEC_SCHEMA",
    "MISSING_PROOF_PLAN_ALTERNATIVE_SCHEMA",
    "PLAN_RANKING_POLICY_SCHEMA",
    "RANKED_PROOF_PLAN_SCHEMA",
    "PROOF_PLAN_RANKING_RESULT_SCHEMA",
    "PROOF_PLAN_HARD_FAILURE_SCHEMA",
    "RANKER_ALGORITHM_VERSION",
    "DEFAULT_BOUNDS",
    "REQUIRED_STEP_FIELD_NAMES",
    "RANKING_SCORE_DIMENSIONS",
    "ProofPlanError",
    "HardPruneReason",
    "StepKind",
    "ProofPlanRankingWeights",
    "ProofPlanRankingPolicy",
    "ProofPlanStepSpec",
    "ProofPlanHardFailure",
    "MissingProofPlanAlternative",
    "RankedProofPlan",
    "ProofPlanRankingResult",
    "GoalDirectedProofPlanRanker",
    "rank_missing_proof_plans",
    "complete_step",
    "build_missing_proof_plan",
    "collect_hard_failures",
    "with_hard_failures",
    "score_missing_proof_plan",
    "to_and_or_plan_branch",
    "to_proof_aware_plan_candidate",
    "rank_via_and_or_evaluator",
    "rank_via_proof_aware_evaluator",
    "authority_rank",
    "authority_meets_minimum",
    "every_step_names_required_fields",
    "rankings_are_deterministic",
    "content_identity",
]
