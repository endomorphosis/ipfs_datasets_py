"""Auditable conditional-delegation policies for the logic benchmark.

The router in this module is deliberately a pure planning boundary.  It does
not import or call an optional backend, and a :class:`DelegationDecision`
cannot claim that a proof is true.  All four policies end at the same native
kernel verification stage and carry the same recorded
:class:`~benchmarks.logic_pipeline.ablation.ResourceLimits`.

P0 through P2 are deterministic functions of pre-outcome routing signals.  P3
uses caller-supplied scores from one pinned development-trained selector; its
model, feature schema, training manifest, feature vector, and thresholds are
retained in the decision.  Learned routing may select only the same bounded
routes as the deterministic policies.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import math
import re
from types import MappingProxyType
from typing import Final, Iterable, Mapping, Self

from .ablation import ResourceLimits
from .contracts import (
    DEFAULT_PROTOCOL_SHA256,
    CacheMode,
    ProtocolContractError,
    Split,
    StageName,
    VerificationAuthority,
    canonical_json,
)


DELEGATION_POLICY_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.delegation-policy.v1"
)
DELEGATION_DECISION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.delegation-decision.v1"
)
DELEGATION_OBSERVATION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.delegation-observation.v1"
)
DELEGATION_COMPARISON_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.delegation-comparison.v1"
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_OPTIONAL_COMPONENTS: Final = frozenset(
    {StageName.SYMAI, StageName.HAMMER, StageName.LEANSTRAL}
)
_MODEL_COMPONENTS: Final = frozenset({StageName.SYMAI, StageName.LEANSTRAL})
_PROOF_COMPONENTS: Final = frozenset({StageName.HAMMER, StageName.LEANSTRAL})
_CANONICAL_POSITION: Final = {
    stage: position for position, stage in enumerate(StageName)
}


class DelegationContractError(ProtocolContractError):
    """Raised when routing or comparison evidence violates the benchmark."""


def HSSLEV0533D02() -> str:
    """Return AST-verifiable evidence for conditional policy comparison."""

    return (
        "bounded P0-P3 conditional delegation with frozen learned provenance, "
        "shared kernel verification and resource limits, and paired "
        "unnecessary-call accounting"
    )


class DelegationPolicy(str, Enum):
    """The four preregistered policy candidates."""

    P0_ALWAYS_ON = "P0"
    P1_DETERMINISTIC_FIRST = "P1"
    P2_PROOF_FAMILY = "P2"
    P3_BOUNDED_LEARNED = "P3"


POLICY_ORDER: Final = tuple(DelegationPolicy)


class ProofFamily(str, Enum):
    """Proof-family evidence available before proof execution."""

    NONE = "none"
    FIRST_ORDER = "first_order"
    SMT = "smt"
    LEAN_NATIVE = "lean_native"
    DEPENDENT_TYPE = "dependent_type"
    TACTIC_HEAVY = "tactic_heavy"
    UNKNOWN = "unknown"

    @property
    def lean_first(self) -> bool:
        return self in {
            ProofFamily.LEAN_NATIVE,
            ProofFamily.DEPENDENT_TYPE,
            ProofFamily.TACTIC_HEAVY,
        }


class ProofAttemptOutcome(str, Enum):
    """Observed disposition of an earlier bounded proof attempt."""

    NOT_ATTEMPTED = "not_attempted"
    CANDIDATE_READY = "candidate_ready"
    INCONCLUSIVE = "inconclusive"
    RECONSTRUCTION_FAILED = "reconstruction_failed"
    FAILED = "failed"

    @property
    def permits_fallback(self) -> bool:
        return self in {
            ProofAttemptOutcome.INCONCLUSIVE,
            ProofAttemptOutcome.RECONSTRUCTION_FAILED,
            ProofAttemptOutcome.FAILED,
        }


def _safe_id(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or value in {".", ".."}
        or not _SAFE_ID.fullmatch(value)
    ):
        raise DelegationContractError(
            f"{field} must be a safe 1-128 character identifier"
        )
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise DelegationContractError(
            f"{field} must be a lowercase SHA-256 digest"
        )
    return value


def _bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise DelegationContractError(f"{field} must be a boolean")
    return value


def _score(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DelegationContractError(f"{field} must be a finite score from 0 to 1")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise DelegationContractError(f"{field} must be a finite score from 0 to 1")
    return result


def _enum(enum_type: type[Enum], value: object, field: str) -> Enum:
    if not isinstance(value, str):
        raise DelegationContractError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise DelegationContractError(f"unsupported {field}: {value!r}") from exc


def _exact_keys(
    value: Mapping[str, object], expected: set[str], field: str
) -> None:
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing or unknown:
        raise DelegationContractError(
            f"{field} fields invalid: missing={sorted(missing)}, "
            f"unknown={sorted(unknown)}"
        )


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise DelegationContractError(f"{field} must be an object")
    return value


def _sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _limits_digest(limits: ResourceLimits) -> str:
    if not isinstance(limits, ResourceLimits):
        raise DelegationContractError("resource_limits must be ResourceLimits")
    return _sha256_json(limits.to_dict())


@dataclass(frozen=True, slots=True)
class DelegationThresholds:
    """Thresholds frozen before any holdout decision is permitted."""

    deterministic_confidence_min: float = 0.75
    learned_symai_min: float = 0.50
    learned_lean_first_min: float = 0.50
    frozen_before_holdout: bool = True

    def __post_init__(self) -> None:
        for field in (
            "deterministic_confidence_min",
            "learned_symai_min",
            "learned_lean_first_min",
        ):
            object.__setattr__(self, field, _score(getattr(self, field), field))
        _bool(self.frozen_before_holdout, "frozen_before_holdout")

    def to_dict(self) -> dict[str, object]:
        return {
            "deterministic_confidence_min": self.deterministic_confidence_min,
            "learned_symai_min": self.learned_symai_min,
            "learned_lean_first_min": self.learned_lean_first_min,
            "frozen_before_holdout": self.frozen_before_holdout,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "thresholds")
        _exact_keys(data, set(cls.__dataclass_fields__), "thresholds")
        return cls(
            deterministic_confidence_min=_score(
                data["deterministic_confidence_min"],
                "deterministic_confidence_min",
            ),
            learned_symai_min=_score(
                data["learned_symai_min"], "learned_symai_min"
            ),
            learned_lean_first_min=_score(
                data["learned_lean_first_min"], "learned_lean_first_min"
            ),
            frozen_before_holdout=_bool(
                data["frozen_before_holdout"], "frozen_before_holdout"
            ),
        )

    @property
    def digest(self) -> str:
        return _sha256_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class LearnedRouterProvenance:
    """Pinned provenance for scores produced outside this dependency-free module."""

    selector_sha256: str
    feature_schema_sha256: str
    training_manifest_sha256: str
    training_splits: tuple[Split, ...]
    algorithm: str
    seed: int

    def __post_init__(self) -> None:
        _digest(self.selector_sha256, "selector_sha256")
        _digest(self.feature_schema_sha256, "feature_schema_sha256")
        _digest(self.training_manifest_sha256, "training_manifest_sha256")
        if (
            not isinstance(self.training_splits, tuple)
            or not self.training_splits
            or any(not isinstance(item, Split) for item in self.training_splits)
        ):
            raise DelegationContractError(
                "training_splits must be a nonempty tuple of Split values"
            )
        if len(set(self.training_splits)) != len(self.training_splits):
            raise DelegationContractError(
                "training_splits must not contain duplicates"
            )
        if set(self.training_splits) != {Split.DEVELOPMENT}:
            raise DelegationContractError(
                "the learned router may be trained only on development telemetry"
            )
        if not isinstance(self.algorithm, str) or not self.algorithm.strip():
            raise DelegationContractError("algorithm must be nonempty")
        if len(self.algorithm.encode("utf-8")) > 256:
            raise DelegationContractError("algorithm exceeds 256 encoded bytes")
        if (
            isinstance(self.seed, bool)
            or not isinstance(self.seed, int)
            or self.seed < 0
        ):
            raise DelegationContractError("seed must be a nonnegative integer")

    def to_dict(self) -> dict[str, object]:
        return {
            "selector_sha256": self.selector_sha256,
            "feature_schema_sha256": self.feature_schema_sha256,
            "training_manifest_sha256": self.training_manifest_sha256,
            "training_splits": [item.value for item in self.training_splits],
            "algorithm": self.algorithm,
            "seed": self.seed,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "learned_provenance")
        _exact_keys(data, set(cls.__dataclass_fields__), "learned_provenance")
        raw_splits = data["training_splits"]
        if not isinstance(raw_splits, list):
            raise DelegationContractError("training_splits must be an array")
        return cls(
            selector_sha256=_digest(data["selector_sha256"], "selector_sha256"),
            feature_schema_sha256=_digest(
                data["feature_schema_sha256"], "feature_schema_sha256"
            ),
            training_manifest_sha256=_digest(
                data["training_manifest_sha256"], "training_manifest_sha256"
            ),
            training_splits=tuple(
                _enum(Split, item, "training_splits[]") for item in raw_splits
            ),  # type: ignore[arg-type]
            algorithm=str(data["algorithm"]),
            seed=data["seed"],  # type: ignore[arg-type]
        )

    @property
    def digest(self) -> str:
        return _sha256_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class DelegationPolicyConfig:
    """One immutable policy configuration with shared scientific limits."""

    policy: DelegationPolicy
    thresholds: DelegationThresholds = DelegationThresholds()
    resource_limits: ResourceLimits = ResourceLimits()
    learned_provenance: LearnedRouterProvenance | None = None
    protocol_sha256: str = DEFAULT_PROTOCOL_SHA256
    max_cross_family_fallbacks: int = 1
    max_component_calls: int = 3
    schema: str = DELEGATION_POLICY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != DELEGATION_POLICY_SCHEMA:
            raise DelegationContractError("unsupported delegation-policy schema")
        if not isinstance(self.policy, DelegationPolicy):
            raise DelegationContractError("policy must be a DelegationPolicy")
        if not isinstance(self.thresholds, DelegationThresholds):
            raise DelegationContractError("thresholds must be DelegationThresholds")
        _limits_digest(self.resource_limits)
        _digest(self.protocol_sha256, "protocol_sha256")
        if (
            isinstance(self.max_cross_family_fallbacks, bool)
            or self.max_cross_family_fallbacks != 1
        ):
            raise DelegationContractError(
                "max_cross_family_fallbacks is fixed at exactly one"
            )
        if (
            isinstance(self.max_component_calls, bool)
            or self.max_component_calls != len(_OPTIONAL_COMPONENTS)
        ):
            raise DelegationContractError(
                "max_component_calls is fixed to the three allowlisted components"
            )
        if self.policy is DelegationPolicy.P3_BOUNDED_LEARNED:
            if not isinstance(self.learned_provenance, LearnedRouterProvenance):
                raise DelegationContractError(
                    "P3 requires pinned learned-router provenance"
                )
        elif self.learned_provenance is not None:
            raise DelegationContractError(
                "deterministic policies cannot carry learned-router provenance"
            )

    @property
    def resource_limits_sha256(self) -> str:
        return _limits_digest(self.resource_limits)

    @property
    def deterministic(self) -> bool:
        return self.policy is not DelegationPolicy.P3_BOUNDED_LEARNED

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "policy": self.policy.value,
            "protocol_sha256": self.protocol_sha256,
            "thresholds": self.thresholds.to_dict(),
            "resource_limits": self.resource_limits.to_dict(),
            "resource_limits_sha256": self.resource_limits_sha256,
            "max_cross_family_fallbacks": self.max_cross_family_fallbacks,
            "max_component_calls": self.max_component_calls,
            "allowlisted_components": sorted(
                stage.value for stage in _OPTIONAL_COMPONENTS
            ),
            "verification_authority": VerificationAuthority.NATIVE_KERNEL.value,
            "learned_provenance": (
                None
                if self.learned_provenance is None
                else self.learned_provenance.to_dict()
            ),
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "policy_config")
        expected = {
            "schema",
            "policy",
            "protocol_sha256",
            "thresholds",
            "resource_limits",
            "resource_limits_sha256",
            "max_cross_family_fallbacks",
            "max_component_calls",
            "allowlisted_components",
            "verification_authority",
            "learned_provenance",
        }
        _exact_keys(data, expected, "policy_config")
        allowed = data["allowlisted_components"]
        if allowed != sorted(stage.value for stage in _OPTIONAL_COMPONENTS):
            raise DelegationContractError("allowlisted_components changed")
        if (
            data["verification_authority"]
            != VerificationAuthority.NATIVE_KERNEL.value
        ):
            raise DelegationContractError(
                "verification authority must be native kernel"
            )
        provenance = data["learned_provenance"]
        result = cls(
            schema=str(data["schema"]),
            policy=_enum(
                DelegationPolicy, data["policy"], "policy"
            ),  # type: ignore[arg-type]
            protocol_sha256=_digest(data["protocol_sha256"], "protocol_sha256"),
            thresholds=DelegationThresholds.from_dict(data["thresholds"]),
            resource_limits=ResourceLimits.from_dict(data["resource_limits"]),
            max_cross_family_fallbacks=data[
                "max_cross_family_fallbacks"
            ],  # type: ignore[arg-type]
            max_component_calls=data["max_component_calls"],  # type: ignore[arg-type]
            learned_provenance=(
                None
                if provenance is None
                else LearnedRouterProvenance.from_dict(provenance)
            ),
        )
        if result.resource_limits_sha256 != _digest(
            data["resource_limits_sha256"], "resource_limits_sha256"
        ):
            raise DelegationContractError("resource-limits digest changed")
        return result

    @property
    def digest(self) -> str:
        return _sha256_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class RoutingSignals:
    """Pre-outcome evidence from which one complete bounded route is planned."""

    case_id: str
    case_manifest_sha256: str
    input_sha256: str
    split: Split
    cache_mode: CacheMode
    deterministic_confidence: float
    semantic_ambiguity: bool = False
    missing_predicates: bool = False
    schema_rejected: bool = False
    obligation_valid: bool = True
    proof_family: ProofFamily = ProofFamily.UNKNOWN
    hammer_outcome: ProofAttemptOutcome = ProofAttemptOutcome.NOT_ATTEMPTED
    leanstral_outcome: ProofAttemptOutcome = ProofAttemptOutcome.NOT_ATTEMPTED
    learned_symai_score: float | None = None
    learned_lean_first_score: float | None = None
    feature_vector_sha256: str | None = None

    def __post_init__(self) -> None:
        _safe_id(self.case_id, "case_id")
        _digest(self.case_manifest_sha256, "case_manifest_sha256")
        _digest(self.input_sha256, "input_sha256")
        if not isinstance(self.split, Split):
            raise DelegationContractError("split must be a Split")
        if not isinstance(self.cache_mode, CacheMode):
            raise DelegationContractError("cache_mode must be a CacheMode")
        object.__setattr__(
            self,
            "deterministic_confidence",
            _score(self.deterministic_confidence, "deterministic_confidence"),
        )
        for field in (
            "semantic_ambiguity",
            "missing_predicates",
            "schema_rejected",
            "obligation_valid",
        ):
            _bool(getattr(self, field), field)
        if not isinstance(self.proof_family, ProofFamily):
            raise DelegationContractError("proof_family must be a ProofFamily")
        for field in ("hammer_outcome", "leanstral_outcome"):
            if not isinstance(getattr(self, field), ProofAttemptOutcome):
                raise DelegationContractError(
                    f"{field} must be a ProofAttemptOutcome"
                )
        learned = (
            self.learned_symai_score,
            self.learned_lean_first_score,
            self.feature_vector_sha256,
        )
        if any(item is not None for item in learned):
            if any(item is None for item in learned):
                raise DelegationContractError(
                    "learned scores and feature-vector digest must be supplied together"
                )
            object.__setattr__(
                self,
                "learned_symai_score",
                _score(self.learned_symai_score, "learned_symai_score"),
            )
            object.__setattr__(
                self,
                "learned_lean_first_score",
                _score(
                    self.learned_lean_first_score, "learned_lean_first_score"
                ),
            )
            _digest(self.feature_vector_sha256, "feature_vector_sha256")

    def routing_payload(self) -> dict[str, object]:
        """Return only routing-safe features; corpus truth is never accepted."""

        return {
            "case_id": self.case_id,
            "case_manifest_sha256": self.case_manifest_sha256,
            "input_sha256": self.input_sha256,
            "split": self.split.value,
            "cache_mode": self.cache_mode.value,
            "deterministic_confidence": self.deterministic_confidence,
            "semantic_ambiguity": self.semantic_ambiguity,
            "missing_predicates": self.missing_predicates,
            "schema_rejected": self.schema_rejected,
            "obligation_valid": self.obligation_valid,
            "proof_family": self.proof_family.value,
            "hammer_outcome": self.hammer_outcome.value,
            "leanstral_outcome": self.leanstral_outcome.value,
            "learned_symai_score": self.learned_symai_score,
            "learned_lean_first_score": self.learned_lean_first_score,
            "feature_vector_sha256": self.feature_vector_sha256,
        }

    @property
    def digest(self) -> str:
        return _sha256_json(self.routing_payload())


@dataclass(frozen=True, slots=True)
class DelegationDecision:
    """Content-addressed, replayable plan for one case and policy."""

    policy: DelegationPolicy
    policy_sha256: str
    protocol_sha256: str
    case_id: str
    case_manifest_sha256: str
    input_sha256: str
    split: Split
    cache_mode: CacheMode
    signal_sha256: str
    canonical_stages: tuple[StageName, ...]
    invocation_order: tuple[StageName, ...]
    proof_order: tuple[StageName, ...]
    reasons: tuple[str, ...]
    deterministic: bool
    resource_limits: ResourceLimits
    resource_limits_sha256: str
    cross_family_fallback_count: int
    learned_provenance_sha256: str | None = None
    learned_symai_score: float | None = None
    learned_lean_first_score: float | None = None
    feature_vector_sha256: str | None = None
    schema: str = DELEGATION_DECISION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != DELEGATION_DECISION_SCHEMA:
            raise DelegationContractError("unsupported delegation-decision schema")
        if not isinstance(self.policy, DelegationPolicy):
            raise DelegationContractError("policy must be a DelegationPolicy")
        for field in (
            "policy_sha256",
            "protocol_sha256",
            "case_manifest_sha256",
            "input_sha256",
            "signal_sha256",
            "resource_limits_sha256",
        ):
            _digest(getattr(self, field), field)
        if _limits_digest(self.resource_limits) != self.resource_limits_sha256:
            raise DelegationContractError("decision resource-limits digest changed")
        _safe_id(self.case_id, "case_id")
        if not isinstance(self.split, Split) or not isinstance(
            self.cache_mode, CacheMode
        ):
            raise DelegationContractError("split/cache_mode use protocol enums")
        if not isinstance(self.canonical_stages, tuple) or not self.canonical_stages:
            raise DelegationContractError("canonical_stages must be nonempty")
        if len(set(self.canonical_stages)) != len(self.canonical_stages):
            raise DelegationContractError("canonical_stages must be unique")
        if tuple(sorted(self.canonical_stages, key=_CANONICAL_POSITION.get)) != (
            self.canonical_stages
        ):
            raise DelegationContractError("canonical_stages are not in wire order")
        if self.canonical_stages[-1] is not StageName.KERNEL:
            raise DelegationContractError("native kernel must be the terminal stage")
        if set(self.invocation_order) != set(self.canonical_stages):
            raise DelegationContractError(
                "invocation_order and canonical_stages must select the same stages"
            )
        if len(set(self.invocation_order)) != len(self.invocation_order):
            raise DelegationContractError("route re-entry is forbidden")
        if self.invocation_order[-1] is not StageName.KERNEL:
            raise DelegationContractError("kernel must be invoked last")
        if (
            any(stage not in _PROOF_COMPONENTS for stage in self.proof_order)
            or tuple(
                stage for stage in self.invocation_order if stage in _PROOF_COMPONENTS
            )
            != self.proof_order
        ):
            raise DelegationContractError(
                "proof_order must match proof invocation order"
            )
        required_stages = {
            StageName.COMPILER,
            StageName.SPACY,
            StageName.KERNEL,
        }
        if not required_stages <= set(self.canonical_stages):
            raise DelegationContractError(
                "every route requires compiler, spaCy, and native kernel"
            )
        if self.policy is DelegationPolicy.P0_ALWAYS_ON and (
            set(self.canonical_stages) != set(StageName)
            or self.proof_order != (StageName.HAMMER, StageName.LEANSTRAL)
            or self.cross_family_fallback_count != 0
        ):
            raise DelegationContractError(
                "P0 must invoke the complete stack once without fallback"
            )
        if self.policy is DelegationPolicy.P1_DETERMINISTIC_FIRST and (
            self.proof_order
            not in {
                (),
                (StageName.HAMMER,),
                (StageName.HAMMER, StageName.LEANSTRAL),
            }
        ):
            raise DelegationContractError(
                "P1 proof routing must be Hammer-first"
            )
        optional_count = len(set(self.canonical_stages) & _OPTIONAL_COMPONENTS)
        if optional_count > len(_OPTIONAL_COMPONENTS):
            raise DelegationContractError("too many component calls")
        if (
            isinstance(self.cross_family_fallback_count, bool)
            or self.cross_family_fallback_count not in {0, 1}
        ):
            raise DelegationContractError(
                "cross-family fallback count must be zero or one"
            )
        expected_fallbacks = int(len(self.proof_order) == 2)
        if (
            self.policy is not DelegationPolicy.P0_ALWAYS_ON
            and self.cross_family_fallback_count != expected_fallbacks
        ):
            raise DelegationContractError(
                "fallback count does not match the bounded proof route"
            )
        if self.model_call_count > self.resource_limits.max_model_calls_per_case:
            raise DelegationContractError(
                "decision exceeds its model-call resource limit"
            )
        if (
            self.solver_process_count
            > self.resource_limits.max_solver_processes_per_case
        ):
            raise DelegationContractError(
                "decision exceeds its solver-process resource limit"
            )
        if not isinstance(self.reasons, tuple) or not self.reasons:
            raise DelegationContractError("decision requires route reasons")
        if (
            len(self.reasons) > 16
            or any(not isinstance(item, str) or not item for item in self.reasons)
            or len(canonical_json(list(self.reasons)).encode("utf-8")) > 4096
        ):
            raise DelegationContractError("decision reasons are invalid or too large")
        _bool(self.deterministic, "deterministic")
        learned_fields = (
            self.learned_provenance_sha256,
            self.learned_symai_score,
            self.learned_lean_first_score,
            self.feature_vector_sha256,
        )
        if self.policy is DelegationPolicy.P3_BOUNDED_LEARNED:
            if self.deterministic or any(item is None for item in learned_fields):
                raise DelegationContractError(
                    "P3 decisions require complete learned provenance"
                )
            _digest(self.learned_provenance_sha256, "learned_provenance_sha256")
            _digest(self.feature_vector_sha256, "feature_vector_sha256")
            object.__setattr__(
                self,
                "learned_symai_score",
                _score(self.learned_symai_score, "learned_symai_score"),
            )
            object.__setattr__(
                self,
                "learned_lean_first_score",
                _score(
                    self.learned_lean_first_score, "learned_lean_first_score"
                ),
            )
        elif not self.deterministic or any(item is not None for item in learned_fields):
            raise DelegationContractError(
                "P0-P2 decisions must be deterministic and carry no learned fields"
            )

    @property
    def component_calls(self) -> tuple[StageName, ...]:
        return tuple(
            stage for stage in self.invocation_order if stage in _OPTIONAL_COMPONENTS
        )

    @property
    def model_call_count(self) -> int:
        return sum(stage in _MODEL_COMPONENTS for stage in self.component_calls)

    @property
    def solver_process_count(self) -> int:
        return int(StageName.HAMMER in self.component_calls)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "policy": self.policy.value,
            "policy_sha256": self.policy_sha256,
            "protocol_sha256": self.protocol_sha256,
            "case_id": self.case_id,
            "case_manifest_sha256": self.case_manifest_sha256,
            "input_sha256": self.input_sha256,
            "split": self.split.value,
            "cache_mode": self.cache_mode.value,
            "signal_sha256": self.signal_sha256,
            "canonical_stages": [item.value for item in self.canonical_stages],
            "invocation_order": [item.value for item in self.invocation_order],
            "proof_order": [item.value for item in self.proof_order],
            "reasons": list(self.reasons),
            "deterministic": self.deterministic,
            "resource_limits": self.resource_limits.to_dict(),
            "resource_limits_sha256": self.resource_limits_sha256,
            "cross_family_fallback_count": self.cross_family_fallback_count,
            "verification_authority": VerificationAuthority.NATIVE_KERNEL.value,
            "learned_provenance_sha256": self.learned_provenance_sha256,
            "learned_symai_score": self.learned_symai_score,
            "learned_lean_first_score": self.learned_lean_first_score,
            "feature_vector_sha256": self.feature_vector_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "decision")
        expected = {
            "schema",
            "policy",
            "policy_sha256",
            "protocol_sha256",
            "case_id",
            "case_manifest_sha256",
            "input_sha256",
            "split",
            "cache_mode",
            "signal_sha256",
            "canonical_stages",
            "invocation_order",
            "proof_order",
            "reasons",
            "deterministic",
            "resource_limits",
            "resource_limits_sha256",
            "cross_family_fallback_count",
            "verification_authority",
            "learned_provenance_sha256",
            "learned_symai_score",
            "learned_lean_first_score",
            "feature_vector_sha256",
        }
        _exact_keys(data, expected, "decision")
        if (
            data["verification_authority"]
            != VerificationAuthority.NATIVE_KERNEL.value
        ):
            raise DelegationContractError(
                "verification authority must be native kernel"
            )

        def stages(field: str) -> tuple[StageName, ...]:
            raw = data[field]
            if not isinstance(raw, list):
                raise DelegationContractError(f"{field} must be an array")
            return tuple(
                _enum(StageName, item, f"{field}[]") for item in raw
            )  # type: ignore[return-value]

        reasons = data["reasons"]
        if not isinstance(reasons, list) or any(
            not isinstance(item, str) for item in reasons
        ):
            raise DelegationContractError("reasons must be an array")
        return cls(
            schema=str(data["schema"]),
            policy=_enum(
                DelegationPolicy, data["policy"], "policy"
            ),  # type: ignore[arg-type]
            policy_sha256=_digest(data["policy_sha256"], "policy_sha256"),
            protocol_sha256=_digest(data["protocol_sha256"], "protocol_sha256"),
            case_id=_safe_id(data["case_id"], "case_id"),
            case_manifest_sha256=_digest(
                data["case_manifest_sha256"], "case_manifest_sha256"
            ),
            input_sha256=_digest(data["input_sha256"], "input_sha256"),
            split=_enum(Split, data["split"], "split"),  # type: ignore[arg-type]
            cache_mode=_enum(
                CacheMode, data["cache_mode"], "cache_mode"
            ),  # type: ignore[arg-type]
            signal_sha256=_digest(data["signal_sha256"], "signal_sha256"),
            canonical_stages=stages("canonical_stages"),
            invocation_order=stages("invocation_order"),
            proof_order=stages("proof_order"),
            reasons=tuple(str(item) for item in reasons),
            deterministic=_bool(data["deterministic"], "deterministic"),
            resource_limits=ResourceLimits.from_dict(data["resource_limits"]),
            resource_limits_sha256=_digest(
                data["resource_limits_sha256"], "resource_limits_sha256"
            ),
            cross_family_fallback_count=data[
                "cross_family_fallback_count"
            ],  # type: ignore[arg-type]
            learned_provenance_sha256=data[
                "learned_provenance_sha256"
            ],  # type: ignore[arg-type]
            learned_symai_score=data[
                "learned_symai_score"
            ],  # type: ignore[arg-type]
            learned_lean_first_score=data[
                "learned_lean_first_score"
            ],  # type: ignore[arg-type]
            feature_vector_sha256=data[
                "feature_vector_sha256"
            ],  # type: ignore[arg-type]
        )

    @property
    def digest(self) -> str:
        return _sha256_json(self.to_dict())


def build_policy_configs(
    learned_provenance: LearnedRouterProvenance,
    *,
    thresholds: DelegationThresholds = DelegationThresholds(),
    resource_limits: ResourceLimits = ResourceLimits(),
    protocol_sha256: str = DEFAULT_PROTOCOL_SHA256,
) -> Mapping[DelegationPolicy, DelegationPolicyConfig]:
    """Return all P0-P3 configurations with exactly shared limits/thresholds."""

    if not isinstance(learned_provenance, LearnedRouterProvenance):
        raise DelegationContractError(
            "learned_provenance must be LearnedRouterProvenance"
        )
    result = {
        policy: DelegationPolicyConfig(
            policy=policy,
            thresholds=thresholds,
            resource_limits=resource_limits,
            learned_provenance=(
                learned_provenance
                if policy is DelegationPolicy.P3_BOUNDED_LEARNED
                else None
            ),
            protocol_sha256=protocol_sha256,
        )
        for policy in POLICY_ORDER
    }
    return MappingProxyType(result)


def _deterministic_symai_gate(
    signals: RoutingSignals, thresholds: DelegationThresholds
) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    if signals.semantic_ambiguity:
        reasons.append("semantic_ambiguity")
    if signals.missing_predicates:
        reasons.append("missing_predicates")
    if signals.schema_rejected:
        reasons.append("schema_rejected")
    if signals.deterministic_confidence < thresholds.deterministic_confidence_min:
        reasons.append("low_deterministic_confidence")
    return bool(reasons), tuple(reasons)


def route_case(
    config: DelegationPolicyConfig,
    signals: RoutingSignals,
) -> DelegationDecision:
    """Plan one bounded P0-P3 route without invoking a backend.

    A caller may invoke this function again after recording the first proof
    attempt's disposition, but a returned route never repeats a component and
    can include at most one cross-family fallback.
    """

    if not isinstance(config, DelegationPolicyConfig):
        raise DelegationContractError("config must be DelegationPolicyConfig")
    if not isinstance(signals, RoutingSignals):
        raise DelegationContractError("signals must be RoutingSignals")
    if (
        signals.split is Split.HOLDOUT
        and not config.thresholds.frozen_before_holdout
    ):
        raise DelegationContractError(
            "holdout routing requires thresholds frozen before access"
        )

    stages: list[StageName] = [StageName.COMPILER, StageName.SPACY]
    proof_order: list[StageName] = []
    reasons: list[str] = [config.policy.value]
    fallback_count = 0
    learned_fields: tuple[str | float | None, ...] = (None, None, None, None)

    if config.policy is DelegationPolicy.P0_ALWAYS_ON:
        stages.extend((StageName.SYMAI, StageName.HAMMER, StageName.LEANSTRAL))
        proof_order.extend((StageName.HAMMER, StageName.LEANSTRAL))
        reasons.append("always_on_full_stack")

    elif config.policy is DelegationPolicy.P1_DETERMINISTIC_FIRST:
        use_symai, gate_reasons = _deterministic_symai_gate(
            signals, config.thresholds
        )
        if use_symai:
            stages.append(StageName.SYMAI)
            reasons.extend(gate_reasons)
        else:
            reasons.append("deterministic_frontend_sufficient")
        if signals.obligation_valid:
            stages.append(StageName.HAMMER)
            proof_order.append(StageName.HAMMER)
            reasons.append("valid_obligation_hammer_first")
            if signals.hammer_outcome.permits_fallback:
                stages.append(StageName.LEANSTRAL)
                proof_order.append(StageName.LEANSTRAL)
                fallback_count = 1
                reasons.append(f"hammer_{signals.hammer_outcome.value}_fallback")
        else:
            reasons.append("invalid_obligation_no_proof_delegation")

    elif config.policy is DelegationPolicy.P2_PROOF_FAMILY:
        use_symai, gate_reasons = _deterministic_symai_gate(
            signals, config.thresholds
        )
        if use_symai:
            stages.append(StageName.SYMAI)
            reasons.extend(gate_reasons)
        else:
            reasons.append("deterministic_frontend_sufficient")
        if signals.obligation_valid:
            lean_first = signals.proof_family.lean_first
            primary = StageName.LEANSTRAL if lean_first else StageName.HAMMER
            secondary = StageName.HAMMER if lean_first else StageName.LEANSTRAL
            primary_outcome = (
                signals.leanstral_outcome if lean_first else signals.hammer_outcome
            )
            stages.append(primary)
            proof_order.append(primary)
            reasons.append(f"{signals.proof_family.value}_{primary.value}_first")
            if primary_outcome.permits_fallback:
                stages.append(secondary)
                proof_order.append(secondary)
                fallback_count = 1
                reasons.append(
                    f"{primary.value}_{primary_outcome.value}_single_fallback"
                )
        else:
            reasons.append("invalid_obligation_no_proof_delegation")

    else:
        provenance = config.learned_provenance
        if provenance is None:  # pragma: no cover - config guards this
            raise DelegationContractError("P3 has no learned provenance")
        if (
            signals.learned_symai_score is None
            or signals.learned_lean_first_score is None
            or signals.feature_vector_sha256 is None
        ):
            raise DelegationContractError(
                "P3 requires both learned scores and a feature-vector digest"
            )
        if signals.learned_symai_score >= config.thresholds.learned_symai_min:
            stages.append(StageName.SYMAI)
            reasons.append("learned_symai_threshold_met")
        else:
            reasons.append("learned_symai_threshold_not_met")
        if signals.obligation_valid:
            lean_first = (
                signals.learned_lean_first_score
                >= config.thresholds.learned_lean_first_min
            )
            primary = StageName.LEANSTRAL if lean_first else StageName.HAMMER
            secondary = StageName.HAMMER if lean_first else StageName.LEANSTRAL
            primary_outcome = (
                signals.leanstral_outcome if lean_first else signals.hammer_outcome
            )
            stages.append(primary)
            proof_order.append(primary)
            reasons.append(f"learned_{primary.value}_first")
            if primary_outcome.permits_fallback:
                stages.append(secondary)
                proof_order.append(secondary)
                fallback_count = 1
                reasons.append(
                    f"{primary.value}_{primary_outcome.value}_single_fallback"
                )
        else:
            reasons.append("invalid_obligation_no_proof_delegation")
        learned_fields = (
            provenance.digest,
            signals.learned_symai_score,
            signals.learned_lean_first_score,
            signals.feature_vector_sha256,
        )

    stages.append(StageName.KERNEL)
    invocation_order = tuple(
        stage for stage in stages if stage not in _PROOF_COMPONENTS
    )
    # Proof calls occur after language stages and before the kernel.  Keep their
    # selected execution order separate from canonical StageRecord wire order.
    kernel_position = invocation_order.index(StageName.KERNEL)
    invocation_order = (
        invocation_order[:kernel_position]
        + tuple(proof_order)
        + invocation_order[kernel_position:]
    )
    canonical_stages = tuple(sorted(set(stages), key=_CANONICAL_POSITION.get))

    component_calls = set(canonical_stages) & _OPTIONAL_COMPONENTS
    model_calls = len(component_calls & _MODEL_COMPONENTS)
    solver_processes = int(StageName.HAMMER in component_calls)
    if len(component_calls) > config.max_component_calls:
        raise DelegationContractError("route exceeds component-call bound")
    if model_calls > config.resource_limits.max_model_calls_per_case:
        raise DelegationContractError("route exceeds shared model-call limit")
    if solver_processes > config.resource_limits.max_solver_processes_per_case:
        raise DelegationContractError("route exceeds shared solver-process limit")

    return DelegationDecision(
        policy=config.policy,
        policy_sha256=config.digest,
        protocol_sha256=config.protocol_sha256,
        case_id=signals.case_id,
        case_manifest_sha256=signals.case_manifest_sha256,
        input_sha256=signals.input_sha256,
        split=signals.split,
        cache_mode=signals.cache_mode,
        signal_sha256=signals.digest,
        canonical_stages=canonical_stages,
        invocation_order=invocation_order,
        proof_order=tuple(proof_order),
        reasons=tuple(reasons),
        deterministic=config.deterministic,
        resource_limits=config.resource_limits,
        resource_limits_sha256=config.resource_limits_sha256,
        cross_family_fallback_count=fallback_count,
        learned_provenance_sha256=learned_fields[0],  # type: ignore[arg-type]
        learned_symai_score=learned_fields[1],  # type: ignore[arg-type]
        learned_lean_first_score=learned_fields[2],  # type: ignore[arg-type]
        feature_vector_sha256=learned_fields[3],  # type: ignore[arg-type]
    )


@dataclass(frozen=True, slots=True)
class DelegationObservation:
    """Kernel-bound outcome and leave-one-out usefulness for one decision."""

    decision: DelegationDecision
    result_sha256: str
    kernel_verified: bool
    kernel_receipt_sha256: str | None
    useful_components: frozenset[StageName]
    deterministically_resolved: bool
    improvable: bool
    schema: str = DELEGATION_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != DELEGATION_OBSERVATION_SCHEMA:
            raise DelegationContractError("unsupported delegation-observation schema")
        if not isinstance(self.decision, DelegationDecision):
            raise DelegationContractError("decision must be DelegationDecision")
        _digest(self.result_sha256, "result_sha256")
        _bool(self.kernel_verified, "kernel_verified")
        _bool(self.deterministically_resolved, "deterministically_resolved")
        _bool(self.improvable, "improvable")
        if self.kernel_verified:
            _digest(self.kernel_receipt_sha256, "kernel_receipt_sha256")
        elif self.kernel_receipt_sha256 is not None:
            raise DelegationContractError(
                "non-verified observations cannot carry a kernel receipt"
            )
        if not isinstance(self.useful_components, frozenset) or any(
            not isinstance(item, StageName) for item in self.useful_components
        ):
            raise DelegationContractError(
                "useful_components must be a frozenset of StageName values"
            )
        if not self.useful_components <= set(self.decision.component_calls):
            raise DelegationContractError(
                "useful components must be invoked optional components"
            )
        if self.useful_components and not self.kernel_verified:
            raise DelegationContractError(
                "usefulness requires a native-kernel-verified gain"
            )
        if self.deterministically_resolved and self.useful_components:
            raise DelegationContractError(
                "a deterministic resolution cannot attribute delegation usefulness"
            )

    @property
    def unnecessary_call_count(self) -> int:
        return len(self.decision.component_calls) - len(self.useful_components)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "decision": self.decision.to_dict(),
            "decision_sha256": self.decision.digest,
            "result_sha256": self.result_sha256,
            "kernel_verified": self.kernel_verified,
            "verification_authority": VerificationAuthority.NATIVE_KERNEL.value,
            "kernel_receipt_sha256": self.kernel_receipt_sha256,
            "useful_components": sorted(
                item.value for item in self.useful_components
            ),
            "deterministically_resolved": self.deterministically_resolved,
            "improvable": self.improvable,
        }

    @property
    def digest(self) -> str:
        return _sha256_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class PolicyEfficiency:
    """Non-collapsed routing and outcome metrics for one policy."""

    policy: DelegationPolicy
    case_count: int
    kernel_verified_count: int
    component_call_count: int
    model_call_count: int
    solver_process_count: int
    useful_call_count: int
    unnecessary_call_count: int
    escalated_case_count: int
    useful_escalated_case_count: int
    improvable_case_count: int
    escalated_improvable_case_count: int
    resolved_before_symai_count: int
    resolved_before_leanstral_count: int
    kernel_verified_rate: float
    unnecessary_call_rate: float
    escalation_precision: float
    escalation_recall: float

    def to_dict(self) -> dict[str, object]:
        return {
            field: (
                getattr(self, field).value
                if field == "policy"
                else getattr(self, field)
            )
            for field in self.__dataclass_fields__
        }


@dataclass(frozen=True, slots=True)
class DelegationComparison:
    """Balanced P0-P3 pilot/development comparison with shared invariants."""

    protocol_sha256: str
    case_manifest_sha256: str
    resource_limits: ResourceLimits
    resource_limits_sha256: str
    policies: tuple[DelegationPolicy, ...]
    case_keys: tuple[tuple[str, str, str], ...]
    summaries: Mapping[DelegationPolicy, PolicyEfficiency]
    observation_sha256s: tuple[str, ...]
    pareto_policies: tuple[DelegationPolicy, ...]
    verification_authority: VerificationAuthority = (
        VerificationAuthority.NATIVE_KERNEL
    )
    schema: str = DELEGATION_COMPARISON_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != DELEGATION_COMPARISON_SCHEMA:
            raise DelegationContractError("unsupported delegation-comparison schema")
        for field in (
            "protocol_sha256",
            "case_manifest_sha256",
            "resource_limits_sha256",
        ):
            _digest(getattr(self, field), field)
        if _limits_digest(self.resource_limits) != self.resource_limits_sha256:
            raise DelegationContractError(
                "comparison resource-limits digest changed"
            )
        if self.policies != POLICY_ORDER:
            raise DelegationContractError("comparison must contain ordered P0-P3")
        if self.verification_authority is not VerificationAuthority.NATIVE_KERNEL:
            raise DelegationContractError("comparison authority must be native kernel")
        if not self.case_keys or len(self.case_keys) != len(set(self.case_keys)):
            raise DelegationContractError("case_keys must be unique and nonempty")
        if set(self.summaries) != set(POLICY_ORDER):
            raise DelegationContractError("summaries must contain exactly P0-P3")
        if any(
            not isinstance(value, PolicyEfficiency)
            or value.policy is not policy
            for policy, value in self.summaries.items()
        ):
            raise DelegationContractError("summary policy identities do not match")
        object.__setattr__(
            self, "summaries", MappingProxyType(dict(self.summaries))
        )
        if len(self.observation_sha256s) != len(self.case_keys) * len(POLICY_ORDER):
            raise DelegationContractError("comparison evidence matrix is incomplete")
        for digest in self.observation_sha256s:
            _digest(digest, "observation_sha256s[]")
        if not self.pareto_policies or any(
            item not in POLICY_ORDER for item in self.pareto_policies
        ):
            raise DelegationContractError("pareto_policies are invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "protocol_sha256": self.protocol_sha256,
            "case_manifest_sha256": self.case_manifest_sha256,
            "resource_limits": self.resource_limits.to_dict(),
            "resource_limits_sha256": self.resource_limits_sha256,
            "verification_authority": self.verification_authority.value,
            "policies": [item.value for item in self.policies],
            "case_keys": [list(item) for item in self.case_keys],
            "summaries": {
                policy.value: self.summaries[policy].to_dict()
                for policy in POLICY_ORDER
            },
            "observation_sha256s": list(self.observation_sha256s),
            "pareto_policies": [item.value for item in self.pareto_policies],
            "unnecessary_call_rate_definition": (
                "(component calls - kernel-verified useful component calls) / "
                "component calls; zero when there are no component calls"
            ),
        }

    @property
    def digest(self) -> str:
        return _sha256_json(self.to_dict())


def _efficiency(
    policy: DelegationPolicy,
    observations: tuple[DelegationObservation, ...],
) -> PolicyEfficiency:
    case_count = len(observations)
    calls = sum(len(item.decision.component_calls) for item in observations)
    useful = sum(len(item.useful_components) for item in observations)
    unnecessary = calls - useful
    escalated = tuple(item for item in observations if item.decision.component_calls)
    useful_escalated = sum(bool(item.useful_components) for item in escalated)
    improvable = tuple(item for item in observations if item.improvable)
    escalated_improvable = sum(
        bool(item.decision.component_calls) for item in improvable
    )
    return PolicyEfficiency(
        policy=policy,
        case_count=case_count,
        kernel_verified_count=sum(item.kernel_verified for item in observations),
        component_call_count=calls,
        model_call_count=sum(
            item.decision.model_call_count for item in observations
        ),
        solver_process_count=sum(
            item.decision.solver_process_count for item in observations
        ),
        useful_call_count=useful,
        unnecessary_call_count=unnecessary,
        escalated_case_count=len(escalated),
        useful_escalated_case_count=useful_escalated,
        improvable_case_count=len(improvable),
        escalated_improvable_case_count=escalated_improvable,
        resolved_before_symai_count=sum(
            StageName.SYMAI not in item.decision.component_calls
            for item in observations
        ),
        resolved_before_leanstral_count=sum(
            StageName.LEANSTRAL not in item.decision.component_calls
            for item in observations
        ),
        kernel_verified_rate=sum(item.kernel_verified for item in observations)
        / case_count,
        unnecessary_call_rate=0.0 if not calls else unnecessary / calls,
        escalation_precision=0.0 if not calls else useful / calls,
        escalation_recall=(
            0.0 if not improvable else escalated_improvable / len(improvable)
        ),
    )


def summarize_policy_efficiency(
    policy: DelegationPolicy,
    observations: Iterable[DelegationObservation],
) -> PolicyEfficiency:
    """Summarize one policy, including defined zero-call metric denominators."""

    if not isinstance(policy, DelegationPolicy):
        raise DelegationContractError("policy must be a DelegationPolicy")
    records = tuple(observations)
    if not records:
        raise DelegationContractError("policy summary requires observations")
    if any(
        not isinstance(item, DelegationObservation)
        or item.decision.policy is not policy
        for item in records
    ):
        raise DelegationContractError(
            "every observation must belong to the summarized policy"
        )
    return _efficiency(policy, records)


def compare_delegation_policies(
    observations: Iterable[DelegationObservation],
) -> DelegationComparison:
    """Compare a complete paired P0-P3 pilot/development evidence matrix."""

    records = tuple(observations)
    if not records:
        raise DelegationContractError("comparison requires observations")
    if any(not isinstance(item, DelegationObservation) for item in records):
        raise DelegationContractError(
            "observations must contain DelegationObservation values"
        )
    if any(item.decision.split is Split.HOLDOUT for item in records):
        raise DelegationContractError(
            "policy development comparison cannot inspect holdout results"
        )

    protocols = {item.decision.protocol_sha256 for item in records}
    manifests = {item.decision.case_manifest_sha256 for item in records}
    limits = {item.decision.resource_limits_sha256 for item in records}
    limit_values = {item.decision.resource_limits for item in records}
    if (
        len(protocols) != 1
        or len(manifests) != 1
        or len(limits) != 1
        or len(limit_values) != 1
    ):
        raise DelegationContractError(
            "all policies require identical protocol, manifest, and resource limits"
        )

    matrix: dict[
        tuple[str, str, str], dict[DelegationPolicy, DelegationObservation]
    ] = {}
    for item in records:
        decision = item.decision
        key = (
            decision.case_id,
            decision.split.value,
            decision.cache_mode.value,
        )
        row = matrix.setdefault(key, {})
        if decision.policy in row:
            raise DelegationContractError(
                f"duplicate policy observation for case block {key}"
            )
        row[decision.policy] = item
    for key, row in matrix.items():
        if set(row) != set(POLICY_ORDER):
            raise DelegationContractError(
                f"case block {key} does not contain exactly P0-P3"
            )
        input_digests = {item.decision.input_sha256 for item in row.values()}
        if len(input_digests) != 1:
            raise DelegationContractError(
                f"case block {key} does not use identical input"
            )
        improvable = {item.improvable for item in row.values()}
        deterministic = {item.deterministically_resolved for item in row.values()}
        if len(improvable) != 1 or len(deterministic) != 1:
            raise DelegationContractError(
                f"case block {key} has inconsistent paired labels"
            )

    case_keys = tuple(sorted(matrix))
    summaries = {
        policy: summarize_policy_efficiency(
            policy,
            tuple(matrix[key][policy] for key in case_keys),
        )
        for policy in POLICY_ORDER
    }
    pareto: list[DelegationPolicy] = []
    for candidate in POLICY_ORDER:
        current = summaries[candidate]
        dominated = False
        for other_policy in POLICY_ORDER:
            if other_policy is candidate:
                continue
            other = summaries[other_policy]
            no_worse = (
                other.kernel_verified_rate >= current.kernel_verified_rate
                and other.component_call_count <= current.component_call_count
                and other.unnecessary_call_rate <= current.unnecessary_call_rate
            )
            strictly_better = (
                other.kernel_verified_rate > current.kernel_verified_rate
                or other.component_call_count < current.component_call_count
                or other.unnecessary_call_rate < current.unnecessary_call_rate
            )
            if no_worse and strictly_better:
                dominated = True
                break
        if not dominated:
            pareto.append(candidate)

    ordered_observations = tuple(
        matrix[key][policy] for key in case_keys for policy in POLICY_ORDER
    )
    return DelegationComparison(
        protocol_sha256=next(iter(protocols)),
        case_manifest_sha256=next(iter(manifests)),
        resource_limits=next(iter(limit_values)),
        resource_limits_sha256=next(iter(limits)),
        policies=POLICY_ORDER,
        case_keys=case_keys,
        summaries=summaries,
        observation_sha256s=tuple(item.digest for item in ordered_observations),
        pareto_policies=tuple(pareto),
    )


# Concise compatibility aliases for callers that use generic router vocabulary.
PolicyConfig = DelegationPolicyConfig
RouteDecision = DelegationDecision
decide = route_case
compare_policies = compare_delegation_policies


__all__ = [
    "DELEGATION_COMPARISON_SCHEMA",
    "DELEGATION_DECISION_SCHEMA",
    "DELEGATION_OBSERVATION_SCHEMA",
    "DELEGATION_POLICY_SCHEMA",
    "POLICY_ORDER",
    "DelegationComparison",
    "DelegationContractError",
    "DelegationDecision",
    "DelegationObservation",
    "DelegationPolicy",
    "DelegationPolicyConfig",
    "DelegationThresholds",
    "HSSLEV0533D02",
    "LearnedRouterProvenance",
    "PolicyConfig",
    "PolicyEfficiency",
    "ProofAttemptOutcome",
    "ProofFamily",
    "RouteDecision",
    "RoutingSignals",
    "build_policy_configs",
    "compare_delegation_policies",
    "compare_policies",
    "decide",
    "route_case",
    "summarize_policy_efficiency",
]
