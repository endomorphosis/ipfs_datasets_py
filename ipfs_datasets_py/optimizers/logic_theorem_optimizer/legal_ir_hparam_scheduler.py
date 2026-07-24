"""Resource-aware successive-halving scheduler for LegalIR hparam search.

The scheduler owns policy and evidence validation only.  It does not train
models, mutate baselines, or decide proof authority.  Runtime wrappers can use
it to pick deterministic candidate/rung work, admit that work through the
host-global resource scheduler, and rank only complete snapshots that share the
same immutable baseline and metric lineage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler,
    ResourceLane,
    ResourceLease,
    ResourceSchedulerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_eval_splits import (
    HPARAM_SELECTION_OPERATION,
    split_guard_blocks_operation,
)


LEGAL_IR_HPARAM_SCHEDULER_SCHEMA_VERSION: Final = "legal-ir-hparam-scheduler-v2"

DEFAULT_REQUIRED_FAMILIES: Final = (
    "deontic",
    "frame_logic",
    "tdfol",
    "kg",
    "cec",
    "external_provers",
    "decompiler",
)
HIGHER_IS_BETTER: Final = frozenset(
    {
        "autoencoder_cosine_similarity",
        "compiler_ir_cosine",
        "ir_cosine_similarity",
        "semantic_equivalence",
        "semantic_equivalence_score",
        "structural_validity",
        "symbolic_validity_success_rate",
        "hammer_proof_success_rate",
        "hammer_reconstruction_success_rate",
        "proof_reconstruction_success_rate",
        "reconstruction_success_rate",
        "round_trip_success_rate",
        "decompiler_round_trip_preservation",
        "anti_copy_success_rate",
    }
)
LOWER_IS_BETTER: Final = frozenset(
    {
        "autoencoder_cross_entropy_loss",
        "calibration_error",
        "expected_calibration_error",
        "compiler_ir_cross_entropy_loss",
        "ir_cross_entropy_loss",
        "source_copy_penalty",
        "source_copy_reward_hack_penalty",
        "source_copy_rate",
        "hammer_failure_rate",
        "reconstruction_failure_rate",
    }
)

# These are the jointly-ranked signals for the tensorized search.  Aliases are
# accepted at ingestion, but the canonical names are emitted in decisions so a
# promotion consumer never has to guess which objective was evaluated.
TENSORIZED_OBJECTIVE_METRICS: Final = (
    "ir_cross_entropy_loss",
    "ir_cosine_similarity",
    "autoencoder_cross_entropy_loss",
    "autoencoder_cosine_similarity",
    "symbolic_validity_success_rate",
    "hammer_proof_success_rate",
    "reconstruction_success_rate",
    "round_trip_success_rate",
    "calibration_error",
    "source_copy_penalty",
)
TENSORIZED_METRIC_DIRECTIONS: Final = MappingProxyType(
    {
        "ir_cross_entropy_loss": "lower",
        "ir_cosine_similarity": "higher",
        "autoencoder_cross_entropy_loss": "lower",
        "autoencoder_cosine_similarity": "higher",
        "symbolic_validity_success_rate": "higher",
        "hammer_proof_success_rate": "higher",
        "reconstruction_success_rate": "higher",
        "round_trip_success_rate": "higher",
        "calibration_error": "lower",
        "source_copy_penalty": "lower",
    }
)
TENSORIZED_METRIC_ALIASES: Final = MappingProxyType(
    {
        "ir_cross_entropy_loss": (
            "ir_cross_entropy_loss",
            "compiler_ir_cross_entropy_loss",
            "best_validation_ir_ce",
        ),
        "ir_cosine_similarity": (
            "ir_cosine_similarity",
            "compiler_ir_cosine",
            "best_validation_ir_cosine",
        ),
        "autoencoder_cross_entropy_loss": (
            "autoencoder_cross_entropy_loss",
            "best_validation_ce",
            "validation_ce",
        ),
        "autoencoder_cosine_similarity": (
            "autoencoder_cosine_similarity",
            "best_validation_cosine",
            "validation_cosine",
        ),
        "symbolic_validity_success_rate": (
            "symbolic_validity_success_rate",
            "structural_validity",
        ),
        "hammer_proof_success_rate": ("hammer_proof_success_rate",),
        "reconstruction_success_rate": (
            "reconstruction_success_rate",
            "hammer_reconstruction_success_rate",
            "proof_reconstruction_success_rate",
        ),
        "round_trip_success_rate": (
            "round_trip_success_rate",
            "decompiler_round_trip_preservation",
        ),
        "calibration_error": ("calibration_error", "expected_calibration_error"),
        "source_copy_penalty": (
            "source_copy_penalty",
            "source_copy_reward_hack_penalty",
            "source_copy_rate",
        ),
    }
)
TENSORIZED_FAMILY_METRICS: Final = (
    "ir_cross_entropy_loss",
    "ir_cosine_similarity",
    "autoencoder_cross_entropy_loss",
    "autoencoder_cosine_similarity",
    "semantic_equivalence",
    "symbolic_validity_success_rate",
    "hammer_proof_success_rate",
    "reconstruction_success_rate",
    "round_trip_success_rate",
    "calibration_error",
    "source_copy_penalty",
)
GUARDRAIL_BOOLEAN_KEYS: Final = (
    "semantic_regression",
    "provenance_regression",
    "anti_copy_regression",
    "hammer_proof_regression",
    "lean_reconstruction_regression",
    "process_lifecycle_regression",
    "queue_lag_regression",
)

DEFAULT_PARAM_SETS: Final = (
    {"lr": 0.28, "ce": 1.75, "rec": 0.60, "cos": 0.60, "legal": 1.35, "hard": 0.55, "fam": 1.05, "emb": 0.45},
    {"lr": 0.30, "ce": 1.50, "rec": 0.70, "cos": 0.70, "legal": 1.25, "hard": 0.60, "fam": 0.95, "emb": 0.55},
    {"lr": 0.33, "ce": 1.35, "rec": 0.80, "cos": 0.80, "legal": 1.15, "hard": 0.70, "fam": 1.15, "emb": 0.50},
    {"lr": 0.26, "ce": 2.00, "rec": 0.50, "cos": 0.50, "legal": 1.50, "hard": 0.45, "fam": 0.85, "emb": 0.65},
    {"lr": 0.31, "ce": 1.60, "rec": 0.65, "cos": 0.75, "legal": 1.40, "hard": 0.50, "fam": 1.10, "emb": 0.40},
    {"lr": 0.29, "ce": 1.40, "rec": 0.75, "cos": 0.65, "legal": 1.30, "hard": 0.65, "fam": 1.00, "emb": 0.60},
    {"lr": 0.24, "ce": 2.15, "rec": 0.55, "cos": 0.85, "legal": 1.55, "hard": 0.40, "fam": 1.20, "emb": 0.35},
    {"lr": 0.35, "ce": 1.25, "rec": 0.90, "cos": 0.95, "legal": 1.05, "hard": 0.75, "fam": 0.90, "emb": 0.70},
    {"lr": 0.27, "ce": 1.90, "rec": 0.85, "cos": 0.55, "legal": 1.45, "hard": 0.50, "fam": 1.25, "emb": 0.50},
    {"lr": 0.32, "ce": 1.70, "rec": 0.60, "cos": 0.90, "legal": 1.20, "hard": 0.80, "fam": 0.80, "emb": 0.55},
    {"lr": 0.25, "ce": 1.30, "rec": 0.95, "cos": 0.70, "legal": 1.60, "hard": 0.60, "fam": 1.05, "emb": 0.75},
    {"lr": 0.34, "ce": 1.85, "rec": 0.45, "cos": 0.65, "legal": 1.10, "hard": 0.35, "fam": 1.30, "emb": 0.45},
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, allow_nan=False, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _finite(value: Any, *, name: str, minimum: float | None = None) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        suffix = f" >= {minimum:g}" if minimum is not None else ""
        raise ValueError(f"{name} must be finite{suffix}")
    return result


def _int(value: Any, *, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _freeze(value: Any) -> Any:
    """Recursively freeze JSON-like evidence instead of only its top level."""

    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in sorted(value.items())})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((_freeze(item) for item in value), key=repr))
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _immutable_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return _freeze(value)


@dataclass(frozen=True, slots=True)
class CompilerArtifactSet:
    """Content identity of the one deterministic compiler input set.

    Candidate training is allowed to change learned parameters, never these
    inputs.  The artifact payload is recursively immutable and its digest binds
    the compiler revision, configuration, dataset, and every artifact digest.
    """

    compiler_revision: str
    dataset_digest: str
    artifacts: Mapping[str, Any]
    compiler_config_digest: str = ""
    deterministic: bool = True
    complete: bool = True

    def __post_init__(self) -> None:
        for name in ("compiler_revision", "dataset_digest"):
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"{name} must be non-empty")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "compiler_config_digest", str(self.compiler_config_digest or "").strip())
        if not isinstance(self.deterministic, bool) or not isinstance(self.complete, bool):
            raise ValueError("compiler artifact deterministic and complete flags must be bools")
        if not self.artifacts:
            raise ValueError("compiler artifact set must contain at least one artifact")
        object.__setattr__(self, "artifacts", _immutable_mapping(self.artifacts))

    @property
    def digest(self) -> str:
        return _digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        result = {
            "compiler_revision": self.compiler_revision,
            "compiler_config_digest": self.compiler_config_digest,
            "dataset_digest": self.dataset_digest,
            "deterministic": self.deterministic,
            "complete": self.complete,
            "artifacts": _thaw(self.artifacts),
        }
        if include_digest:
            result["artifact_set_digest"] = self.digest
        return result


@dataclass(frozen=True, slots=True)
class SharedBaseline:
    """Immutable baseline identity shared by every hparam candidate."""

    baseline_id: str
    revision: str
    dataset_digest: str
    metric_lineage_id: str
    metrics: Mapping[str, Any] = field(default_factory=dict)
    family_metrics: Mapping[str, Any] = field(default_factory=dict)
    split_guard: Mapping[str, Any] = field(default_factory=dict)
    compiler_artifact_set: CompilerArtifactSet | Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        for name in ("baseline_id", "revision", "dataset_digest", "metric_lineage_id"):
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"{name} must be non-empty")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "metrics", _immutable_mapping(self.metrics))
        object.__setattr__(self, "family_metrics", _immutable_mapping(self.family_metrics))
        object.__setattr__(self, "split_guard", _immutable_mapping(self.split_guard))
        artifact_set = self.compiler_artifact_set
        if artifact_set is not None and not isinstance(artifact_set, CompilerArtifactSet):
            data = dict(artifact_set)
            artifact_set = CompilerArtifactSet(
                compiler_revision=str(data.get("compiler_revision") or self.revision),
                compiler_config_digest=str(data.get("compiler_config_digest") or ""),
                dataset_digest=str(data.get("dataset_digest") or self.dataset_digest),
                artifacts=data.get("artifacts", {}),
                deterministic=data.get("deterministic") is True,
                complete=data.get("complete") is True,
            )
        object.__setattr__(self, "compiler_artifact_set", artifact_set)

    @property
    def compiler_artifact_set_digest(self) -> str:
        return self.compiler_artifact_set.digest if self.compiler_artifact_set is not None else ""

    @property
    def digest(self) -> str:
        return _digest(self.to_dict(include_digest=False))

    @property
    def lineage_digest(self) -> str:
        return _digest(
            {
                "baseline_digest": self.digest,
                "compiler_artifact_set_digest": self.compiler_artifact_set_digest,
                "metric_lineage_id": self.metric_lineage_id,
                "schema_version": LEGAL_IR_HPARAM_SCHEDULER_SCHEMA_VERSION,
            }
        )

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        result = {
            "baseline_id": self.baseline_id,
            "revision": self.revision,
            "dataset_digest": self.dataset_digest,
            "metric_lineage_id": self.metric_lineage_id,
            "metrics": _thaw(self.metrics),
            "family_metrics": _thaw(self.family_metrics),
            "split_guard": _thaw(self.split_guard),
            "compiler_artifact_set": (
                None
                if self.compiler_artifact_set is None
                else self.compiler_artifact_set.to_dict()
            ),
        }
        if include_digest:
            result["baseline_digest"] = self.digest
            result["lineage_digest"] = self.lineage_digest
        return result


@dataclass(frozen=True, slots=True)
class HParamCandidate:
    """Deterministic candidate with a baseline-bound seed."""

    candidate_id: str
    index: int
    seed: int
    params: tuple[tuple[str, float], ...]
    baseline_digest: str
    lineage_digest: str
    seeds: tuple[int, ...] = ()
    compiler_artifact_set_digest: str = ""

    @classmethod
    def build(
        cls,
        *,
        index: int,
        seed: int,
        params: Mapping[str, Any],
        baseline: SharedBaseline,
        seeds: Sequence[int] | None = None,
    ) -> "HParamCandidate":
        _int(index, name="index")
        _int(seed, name="seed")
        stable_params = tuple(
            (str(key), _finite(value, name=f"params.{key}"))
            for key, value in sorted(dict(params).items())
        )
        stable_seeds = tuple(int(item) for item in (seeds or (seed,)))
        if not stable_seeds or len(set(stable_seeds)) != len(stable_seeds) or any(item < 0 for item in stable_seeds):
            raise ValueError("candidate seeds must be unique non-negative integers")
        candidate_id = "hparam-" + _digest(
            {
                "baseline_digest": baseline.digest,
                "index": index,
                "params": stable_params,
                "seeds": stable_seeds,
            }
        )[:16]
        return cls(
            candidate_id=candidate_id,
            index=index,
            seed=seed,
            params=stable_params,
            baseline_digest=baseline.digest,
            lineage_digest=baseline.lineage_digest,
            seeds=stable_seeds,
            compiler_artifact_set_digest=baseline.compiler_artifact_set_digest,
        )

    def param_dict(self) -> dict[str, float]:
        return dict(self.params)

    def config_string(self) -> str:
        return " ".join(f"{key}={value:g}" for key, value in self.params)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "index": self.index,
            "seed": self.seed,
            "seeds": list(self.seeds or (self.seed,)),
            "params": self.param_dict(),
            "baseline_digest": self.baseline_digest,
            "lineage_digest": self.lineage_digest,
            "compiler_artifact_set_digest": self.compiler_artifact_set_digest,
            "config_string": self.config_string(),
        }


@dataclass(frozen=True, slots=True)
class HParamRung:
    index: int
    budget_seconds: int
    survivor_count: int

    def __post_init__(self) -> None:
        _int(self.index, name="rung.index")
        _int(self.budget_seconds, name="rung.budget_seconds", minimum=1)
        _int(self.survivor_count, name="rung.survivor_count", minimum=1)

    def to_dict(self) -> dict[str, int]:
        return {
            "index": self.index,
            "budget_seconds": self.budget_seconds,
            "survivor_count": self.survivor_count,
        }


@dataclass(frozen=True, slots=True)
class FamilyGuardrailConfig:
    required_families: tuple[str, ...] = DEFAULT_REQUIRED_FAMILIES
    min_confidence: float = 0.80
    require_paired_metrics: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "required_families",
            tuple(str(family).strip() for family in self.required_families if str(family).strip()),
        )
        if not self.required_families:
            raise ValueError("required_families must be non-empty")
        value = _finite(self.min_confidence, name="min_confidence", minimum=0.0)
        if value > 1.0:
            raise ValueError("min_confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class ResourceRequirements:
    evaluation_cpu_slots: int = 1
    evaluation_memory_mb: int = 1024
    trainer_cpu_slots: int = 2
    trainer_memory_mb: int = 8192
    trainer_gpu_memory_mb: int = 12288
    trainer_unified_memory_mb: int = 12288
    proof_cpu_slots: int = 2
    proof_memory_mb: int = 2048
    proof_child_process_slots: int = 2
    lease_timeout_seconds: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "evaluation_cpu_slots",
            "evaluation_memory_mb",
            "trainer_cpu_slots",
            "trainer_memory_mb",
            "trainer_gpu_memory_mb",
            "trainer_unified_memory_mb",
            "proof_cpu_slots",
            "proof_memory_mb",
            "proof_child_process_slots",
        ):
            minimum = 1 if name.endswith("cpu_slots") else 0
            _int(getattr(self, name), name=name, minimum=minimum)
        _finite(self.lease_timeout_seconds, name="lease_timeout_seconds", minimum=0.0)


@dataclass(frozen=True, slots=True)
class HParamResourcePressure:
    """Measured pressure required before admitting a second CUDA trainer."""

    telemetry_known: bool = False
    unified_memory_pressure: float = 1.0
    gpu_memory_pressure: float = 1.0
    memory_pressure: float = 1.0
    swap_pressure: float = 1.0
    service_pressure: float = 1.0
    proof_queue_pressure: float = 1.0
    validation_queue_pressure: float = 1.0
    measured_at_epoch: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.telemetry_known, bool):
            raise ValueError("telemetry_known must be a bool")
        for name in (
            "unified_memory_pressure",
            "gpu_memory_pressure",
            "memory_pressure",
            "swap_pressure",
            "service_pressure",
            "proof_queue_pressure",
            "validation_queue_pressure",
        ):
            value = _finite(getattr(self, name), name=name, minimum=0.0)
            if value > 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        _finite(self.measured_at_epoch, name="measured_at_epoch", minimum=0.0)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "HParamResourcePressure":
        data = dict(value or {})
        aliases = {
            "gpu_telemetry_known": "telemetry_known",
            "leanstral_service_pressure": "service_pressure",
            "hammer_queue_pressure": "proof_queue_pressure",
            "validation_backlog_pressure": "validation_queue_pressure",
            "timestamp": "measured_at_epoch",
        }
        for old, new in aliases.items():
            if new not in data and old in data:
                data[new] = data[old]
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: item for key, item in data.items() if key in allowed})

    @classmethod
    def measure(
        cls,
        scheduler: GlobalResourceScheduler,
        *,
        service_pressure: float,
        proof_queue_pressure: float,
        validation_queue_pressure: float,
    ) -> "HParamResourcePressure":
        """Capture one fresh host-global and downstream-service observation."""

        measured = scheduler.pressure_summary()
        return cls(
            telemetry_known=(
                measured.get("gpu_telemetry_known") is True
                and scheduler.snapshot().get("capacity", {}).get("unified_memory_mb") is not None
            ),
            unified_memory_pressure=measured.get("unified_memory_pressure", 1.0),
            gpu_memory_pressure=measured.get("gpu_memory_pressure", 1.0),
            memory_pressure=measured.get("memory_pressure", 1.0),
            swap_pressure=measured.get("swap_pressure", 1.0),
            service_pressure=service_pressure,
            proof_queue_pressure=proof_queue_pressure,
            validation_queue_pressure=validation_queue_pressure,
            measured_at_epoch=time.time(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class HParamSearchConfig:
    baseline: SharedBaseline
    total_budget_seconds: int = 3600
    initial_candidate_count: int = 12
    rung_budgets_seconds: tuple[int, ...] = (150, 300, 600)
    reduction_factor: int = 2
    base_seed: int = 8675309
    max_concurrent_evaluations: int = 4
    max_concurrent_trainers: int = 1
    allow_concurrent_trainers: bool = False
    seeds_per_candidate: int = 1
    require_multi_seed_evidence: bool = False
    require_cuda_evidence: bool = False
    require_compiler_artifact_set: bool = False
    require_complete_parallel_lanes: bool = False
    require_tensorized_objective: bool = False
    max_evidence_age_seconds: float = 0.0
    require_measured_second_trainer_pressure: bool = False
    max_second_trainer_pressure: float = 0.65
    max_service_pressure: float = 0.70
    pressure_max_age_seconds: float = 60.0
    min_validation_cosine: float = 0.0
    cosine_penalty: float = 4.0
    ir_ce_weight: float = 0.25
    ir_cosine_penalty: float = 2.0
    metric_regression_tolerances: Mapping[str, float] = field(default_factory=dict)
    guardrails: FamilyGuardrailConfig = field(default_factory=FamilyGuardrailConfig)
    resources: ResourceRequirements = field(default_factory=ResourceRequirements)

    def __post_init__(self) -> None:
        if split_guard_blocks_operation(
            self.baseline.split_guard,
            HPARAM_SELECTION_OPERATION,
        ):
            raise ValueError("LegalIR split guard blocks hparam selection")
        _int(self.total_budget_seconds, name="total_budget_seconds", minimum=1)
        _int(self.initial_candidate_count, name="initial_candidate_count", minimum=2)
        _int(self.reduction_factor, name="reduction_factor", minimum=2)
        _int(self.base_seed, name="base_seed")
        _int(self.max_concurrent_evaluations, name="max_concurrent_evaluations", minimum=1)
        _int(self.max_concurrent_trainers, name="max_concurrent_trainers", minimum=1)
        _int(self.seeds_per_candidate, name="seeds_per_candidate", minimum=1)
        if self.require_multi_seed_evidence and self.seeds_per_candidate < 2:
            raise ValueError("multi-seed evidence requires seeds_per_candidate >= 2")
        if self.require_compiler_artifact_set:
            artifact_set = self.baseline.compiler_artifact_set
            if artifact_set is None:
                raise ValueError("tensorized search requires a compiler artifact set")
            if not artifact_set.deterministic or not artifact_set.complete:
                raise ValueError("compiler artifact set must be deterministic and complete")
        budgets = tuple(int(value) for value in self.rung_budgets_seconds)
        if len(budgets) < 2 or any(value <= 0 for value in budgets):
            raise ValueError("rung_budgets_seconds must contain at least two positive budgets")
        if tuple(sorted(budgets)) != budgets or len(set(budgets)) != len(budgets):
            raise ValueError("rung_budgets_seconds must be strictly increasing")
        object.__setattr__(self, "rung_budgets_seconds", budgets)
        for name in ("min_validation_cosine", "cosine_penalty", "ir_ce_weight", "ir_cosine_penalty"):
            _finite(getattr(self, name), name=name, minimum=0.0)
        if not isinstance(self.metric_regression_tolerances, Mapping):
            raise ValueError("metric_regression_tolerances must be a mapping")
        tolerances: dict[str, float] = {}
        for raw_name, raw_value in self.metric_regression_tolerances.items():
            name = str(raw_name).strip()
            if name not in TENSORIZED_OBJECTIVE_METRICS:
                raise ValueError(f"unsupported metric regression tolerance: {name or '<empty>'}")
            tolerances[name] = _finite(
                raw_value,
                name=f"metric_regression_tolerances[{name}]",
                minimum=0.0,
            )
        object.__setattr__(
            self,
            "metric_regression_tolerances",
            MappingProxyType(dict(sorted(tolerances.items()))),
        )
        _finite(self.max_evidence_age_seconds, name="max_evidence_age_seconds", minimum=0.0)
        _finite(self.pressure_max_age_seconds, name="pressure_max_age_seconds", minimum=0.0)
        for name in ("max_second_trainer_pressure", "max_service_pressure"):
            value = _finite(getattr(self, name), name=name, minimum=0.0)
            if value > 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.planned_resource_seconds > self.total_budget_seconds:
            raise ValueError(
                f"successive-halving plan spends {self.planned_resource_seconds}s "
                f"above fixed budget {self.total_budget_seconds}s"
            )

    @property
    def rungs(self) -> tuple[HParamRung, ...]:
        survivor_count = self.initial_candidate_count
        rungs: list[HParamRung] = []
        for index, budget in enumerate(self.rung_budgets_seconds):
            rungs.append(HParamRung(index=index, budget_seconds=budget, survivor_count=survivor_count))
            survivor_count = max(1, math.ceil(survivor_count / self.reduction_factor))
        return tuple(rungs)

    @property
    def planned_resource_seconds(self) -> int:
        total = 0
        previous = 0
        for rung in self.rungs:
            total += rung.survivor_count * (rung.budget_seconds - previous)
            previous = rung.budget_seconds
        return total


@dataclass(frozen=True, slots=True)
class TrialWorkItem:
    candidate: HParamCandidate
    rung: HParamRung
    previous_budget_seconds: int = 0

    @property
    def run_id_suffix(self) -> str:
        return f"{self.candidate.candidate_id}-rung-{self.rung.index:02d}"

    @property
    def additional_budget_seconds(self) -> int:
        return self.rung.budget_seconds - self.previous_budget_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "rung": self.rung.to_dict(),
            "previous_budget_seconds": self.previous_budget_seconds,
            "additional_budget_seconds": self.additional_budget_seconds,
            "run_id_suffix": self.run_id_suffix,
            "immutable_inputs": {
                "baseline_digest": self.candidate.baseline_digest,
                "lineage_digest": self.candidate.lineage_digest,
                "compiler_artifact_set_digest": self.candidate.compiler_artifact_set_digest,
            },
            "seed_set": list(self.candidate.seeds or (self.candidate.seed,)),
            "parallel_lanes": ("snapshot_evaluation", "proof_reconstruction"),
        }


@dataclass(frozen=True, slots=True)
class TrialLaneResults:
    """Results from independent immutable evaluation and proof lanes."""

    evaluation: Any
    proof: Any
    started_at_epoch: float
    completed_at_epoch: float

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, self.completed_at_epoch - self.started_at_epoch)


@dataclass(frozen=True, slots=True)
class TrialSnapshot:
    candidate_id: str
    rung_index: int
    budget_seconds: int
    elapsed_seconds: float
    status: str
    snapshot_complete: bool
    baseline_digest: str
    lineage_digest: str
    metrics: Mapping[str, Any] = field(default_factory=dict)
    family_metrics: Mapping[str, Any] = field(default_factory=dict)
    snapshot_id: str = ""
    compiler_artifact_set_digest: str = ""
    seed_ids: tuple[int, ...] = ()
    multi_seed_evidence_complete: bool = False
    compute_backend: str = ""
    cpu_fallback_used: bool = False
    state_revision: str = ""
    evidence_created_at_epoch: float = 0.0
    stale: bool = False
    evaluation_lane_complete: bool = False
    proof_lane_complete: bool = False
    metric_confidence: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TrialSnapshot":
        return cls(
            candidate_id=str(value.get("candidate_id") or value.get("hparam_candidate_id") or ""),
            rung_index=int(value.get("rung_index", value.get("hparam_rung_index", -1))),
            budget_seconds=int(value.get("budget_seconds", value.get("duration_seconds", 0)) or 0),
            elapsed_seconds=float(value.get("elapsed_seconds", value.get("wall_clock_seconds", 0.0)) or 0.0),
            status=str(value.get("status") or ""),
            snapshot_complete=value.get("snapshot_complete") is True,
            baseline_digest=str(value.get("baseline_digest") or ""),
            lineage_digest=str(value.get("lineage_digest") or value.get("metric_lineage_digest") or ""),
            metrics=value.get("metrics", value) if isinstance(value.get("metrics", value), Mapping) else {},
            family_metrics=value.get("family_metrics", {}) if isinstance(value.get("family_metrics", {}), Mapping) else {},
            snapshot_id=str(value.get("snapshot_id") or value.get("run_id") or ""),
            compiler_artifact_set_digest=str(
                value.get("compiler_artifact_set_digest")
                or value.get("compiler_artifacts_digest")
                or ""
            ),
            seed_ids=tuple(
                int(item)
                for item in value.get("seed_ids", value.get("seed_set", ()))
                if not isinstance(item, bool)
            ),
            multi_seed_evidence_complete=value.get("multi_seed_evidence_complete") is True,
            compute_backend=str(
                value.get("compute_backend")
                or value.get("autoencoder_compute_backend")
                or value.get("device")
                or ""
            ),
            cpu_fallback_used=(
                value.get("cpu_fallback_used") is True
                or value.get("cpu_fallback") is True
            ),
            state_revision=str(value.get("state_revision") or value.get("evaluated_revision") or ""),
            evidence_created_at_epoch=float(
                value.get("evidence_created_at_epoch", value.get("created_at_epoch", 0.0)) or 0.0
            ),
            stale=value.get("stale") is True or value.get("is_stale") is True,
            evaluation_lane_complete=(
                value.get("evaluation_lane_complete") is True
                or value.get("snapshot_evaluation_complete") is True
            ),
            proof_lane_complete=(
                value.get("proof_lane_complete") is True
                or value.get("proof_reconstruction_complete") is True
            ),
            metric_confidence=(
                value.get("metric_confidence", {})
                if isinstance(value.get("metric_confidence", {}), Mapping)
                else {}
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "rung_index": self.rung_index,
            "budget_seconds": self.budget_seconds,
            "elapsed_seconds": self.elapsed_seconds,
            "status": self.status,
            "snapshot_complete": self.snapshot_complete,
            "baseline_digest": self.baseline_digest,
            "lineage_digest": self.lineage_digest,
            "metrics": _thaw(self.metrics),
            "family_metrics": _thaw(self.family_metrics),
            "snapshot_id": self.snapshot_id,
            "compiler_artifact_set_digest": self.compiler_artifact_set_digest,
            "seed_ids": list(self.seed_ids),
            "multi_seed_evidence_complete": self.multi_seed_evidence_complete,
            "compute_backend": self.compute_backend,
            "cpu_fallback_used": self.cpu_fallback_used,
            "state_revision": self.state_revision,
            "evidence_created_at_epoch": self.evidence_created_at_epoch,
            "stale": self.stale,
            "evaluation_lane_complete": self.evaluation_lane_complete,
            "proof_lane_complete": self.proof_lane_complete,
            "metric_confidence": _thaw(self.metric_confidence),
        }


@dataclass(frozen=True, slots=True)
class TrialDecision:
    snapshot: TrialSnapshot
    eligible: bool
    score: float
    failures: tuple[str, ...] = ()
    objective_improvements: Mapping[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.snapshot.candidate_id,
            "rung_index": self.snapshot.rung_index,
            "eligible": self.eligible,
            "score": self.score,
            "failures": list(self.failures),
            "snapshot_id": self.snapshot.snapshot_id,
            "objective_improvements": dict(self.objective_improvements),
        }


@dataclass(slots=True)
class TrialLeaseBundle:
    work_item: TrialWorkItem
    evaluation_lease: ResourceLease
    trainer_lease: ResourceLease | None = None
    proof_lease: ResourceLease | None = None

    def release(self) -> None:
        if self.proof_lease is not None:
            self.proof_lease.release()
        if self.trainer_lease is not None:
            self.trainer_lease.release()
        self.evaluation_lease.release()

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_item": self.work_item.to_dict(),
            "evaluation_lease": self.evaluation_lease.to_dict(),
            "trainer_lease": None if self.trainer_lease is None else self.trainer_lease.to_dict(),
            "proof_lease": None if self.proof_lease is None else self.proof_lease.to_dict(),
        }


class LegalIRHParamScheduler:
    """Deterministic successive-halving scheduler with fail-closed evidence gates."""

    def __init__(
        self,
        config: HParamSearchConfig,
        *,
        candidates: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        self.config = config
        param_sets = tuple(candidates or DEFAULT_PARAM_SETS)
        if len(param_sets) < config.initial_candidate_count:
            raise ValueError("not enough parameter sets for initial_candidate_count")
        self.candidates = tuple(
            HParamCandidate.build(
                index=index,
                seed=self._candidate_seeds(index, params)[0],
                seeds=self._candidate_seeds(index, params),
                params=params,
                baseline=config.baseline,
            )
            for index, params in enumerate(param_sets[: config.initial_candidate_count])
        )
        self._candidate_by_id = {candidate.candidate_id: candidate for candidate in self.candidates}
        self._results: dict[tuple[int, str], TrialSnapshot] = {}
        self._active_candidate_ids_by_rung: dict[int, tuple[str, ...]] = {
            0: tuple(candidate.candidate_id for candidate in self.candidates)
        }

    def _candidate_seed(self, index: int, params: Mapping[str, Any]) -> int:
        digest = _digest(
            {
                "base_seed": self.config.base_seed,
                "baseline_digest": self.config.baseline.digest,
                "index": index,
                "params": dict(sorted(params.items())),
            }
        )
        return int(digest[:8], 16)

    def _candidate_seeds(self, index: int, params: Mapping[str, Any]) -> tuple[int, ...]:
        root = self._candidate_seed(index, params)
        seeds: list[int] = []
        for seed_index in range(self.config.seeds_per_candidate):
            digest = _digest(
                {
                    "candidate_root_seed": root,
                    "seed_index": seed_index,
                    "baseline_digest": self.config.baseline.digest,
                }
            )
            seeds.append(int(digest[:8], 16))
        return tuple(seeds)

    def plan_dict(self) -> dict[str, Any]:
        return {
            "schema_version": LEGAL_IR_HPARAM_SCHEDULER_SCHEMA_VERSION,
            "baseline": self.config.baseline.to_dict(),
            "total_budget_seconds": self.config.total_budget_seconds,
            "planned_resource_seconds": self.config.planned_resource_seconds,
            "successive_halving": {
                "reduction_factor": self.config.reduction_factor,
                "rungs": [rung.to_dict() for rung in self.config.rungs],
            },
            "candidate_count": len(self.candidates),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "resource_policy": {
                "max_concurrent_evaluations": self.config.max_concurrent_evaluations,
                "max_concurrent_trainers": self.config.max_concurrent_trainers,
                "allow_concurrent_trainers": self.config.allow_concurrent_trainers,
                "default_cuda_trainers": 1,
                "conditional_max_cuda_trainers": min(2, self.config.max_concurrent_trainers),
                "second_trainer_requires_measured_pressure": self.config.require_measured_second_trainer_pressure,
                "parallel_lanes": ["snapshot_evaluation", "proof_reconstruction", "validation"],
            },
            "immutable_input_policy": {
                "one_shared_baseline": True,
                "baseline_digest": self.config.baseline.digest,
                "compiler_artifact_set_digest": self.config.baseline.compiler_artifact_set_digest,
                "deterministic_compiler_artifacts": bool(
                    self.config.baseline.compiler_artifact_set
                    and self.config.baseline.compiler_artifact_set.deterministic
                ),
            },
            "promotion_policy": {
                "required_seed_count": self.config.seeds_per_candidate,
                "require_multi_seed_evidence": self.config.require_multi_seed_evidence,
                "require_cuda_evidence": self.config.require_cuda_evidence,
                "require_complete_parallel_lanes": self.config.require_complete_parallel_lanes,
                "required_objective_metrics": (
                    list(TENSORIZED_OBJECTIVE_METRICS)
                    if self.config.require_tensorized_objective
                    else []
                ),
                "required_families": list(self.config.guardrails.required_families),
                "required_metrics_per_family": (
                    list(TENSORIZED_FAMILY_METRICS)
                    if self.config.require_tensorized_objective
                    else []
                ),
                "metric_regression_tolerances": dict(
                    self.config.metric_regression_tolerances
                ),
                "min_confidence": self.config.guardrails.min_confidence,
            },
        }

    def run_independent_lanes(
        self,
        work_item: TrialWorkItem,
        *,
        evaluation_lane: Any,
        proof_lane: Any,
    ) -> TrialLaneResults:
        """Execute read-only evaluation and proof work concurrently.

        Callables receive the same work item, hence the same immutable baseline,
        compiler artifact digest, lineage, and seed set.  No training or
        canonical mutation is performed by this helper.
        """

        started = time.time()
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="legal-ir-hparam") as pool:
            evaluation_future: Future[Any] = pool.submit(evaluation_lane, work_item)
            proof_future: Future[Any] = pool.submit(proof_lane, work_item)
            evaluation = evaluation_future.result()
            proof = proof_future.result()
        return TrialLaneResults(evaluation, proof, started, time.time())

    def ready_work(self) -> tuple[TrialWorkItem, ...]:
        rung_index = self.current_rung_index()
        if rung_index is None:
            return ()
        rung = self.config.rungs[rung_index]
        previous_budget = 0 if rung_index == 0 else self.config.rungs[rung_index - 1].budget_seconds
        ready: list[TrialWorkItem] = []
        for candidate_id in self._active_candidate_ids_by_rung[rung_index]:
            if (rung_index, candidate_id) in self._results:
                continue
            ready.append(
                TrialWorkItem(
                    candidate=self._candidate_by_id[candidate_id],
                    rung=rung,
                    previous_budget_seconds=previous_budget,
                )
            )
        return tuple(ready)

    def current_rung_index(self) -> int | None:
        for rung in self.config.rungs:
            ids = self._active_candidate_ids_by_rung.get(rung.index)
            if not ids:
                return None
            if any((rung.index, candidate_id) not in self._results for candidate_id in ids):
                return rung.index
        return None

    def record_result(self, snapshot: TrialSnapshot | Mapping[str, Any]) -> TrialDecision:
        trial = snapshot if isinstance(snapshot, TrialSnapshot) else TrialSnapshot.from_mapping(snapshot)
        if trial.candidate_id not in self._candidate_by_id:
            raise ValueError(f"unknown candidate_id: {trial.candidate_id!r}")
        if trial.rung_index < 0 or trial.rung_index >= len(self.config.rungs):
            raise ValueError(f"unknown rung_index: {trial.rung_index!r}")
        expected_ids = self._active_candidate_ids_by_rung.get(trial.rung_index, ())
        if trial.candidate_id not in expected_ids:
            raise ValueError("candidate is not active for this rung")
        if (trial.rung_index, trial.candidate_id) in self._results:
            raise ValueError("trial result already recorded for candidate and rung")
        expected_budget = self.config.rungs[trial.rung_index].budget_seconds
        if trial.budget_seconds != expected_budget:
            raise ValueError(
                f"trial budget mismatch for rung {trial.rung_index}: "
                f"{trial.budget_seconds} != {expected_budget}"
            )
        candidate = self._candidate_by_id[trial.candidate_id]
        if trial.baseline_digest != candidate.baseline_digest:
            raise ValueError("baseline digest mismatch")
        if trial.lineage_digest != candidate.lineage_digest:
            raise ValueError("metric lineage digest mismatch")
        if (
            self.config.require_compiler_artifact_set
            and trial.compiler_artifact_set_digest != candidate.compiler_artifact_set_digest
        ):
            raise ValueError("compiler artifact set digest mismatch")
        decision = self.score_snapshot(trial)
        self._results[(trial.rung_index, trial.candidate_id)] = trial
        self._maybe_promote_locked(trial.rung_index)
        return decision

    def _maybe_promote_locked(self, rung_index: int) -> None:
        next_index = rung_index + 1
        if next_index >= len(self.config.rungs) or next_index in self._active_candidate_ids_by_rung:
            return
        active_ids = self._active_candidate_ids_by_rung.get(rung_index, ())
        if not active_ids or any((rung_index, candidate_id) not in self._results for candidate_id in active_ids):
            return
        decisions = [
            self.score_snapshot(self._results[(rung_index, candidate_id)])
            for candidate_id in active_ids
        ]
        eligible = [decision for decision in decisions if decision.eligible]
        if not eligible:
            self._active_candidate_ids_by_rung[next_index] = ()
            return
        survivor_count = self.config.rungs[next_index].survivor_count
        promoted = sorted(
            eligible,
            key=lambda decision: (
                decision.score,
                self._candidate_by_id[decision.snapshot.candidate_id].seed,
                decision.snapshot.candidate_id,
            ),
        )[:survivor_count]
        self._active_candidate_ids_by_rung[next_index] = tuple(
            decision.snapshot.candidate_id for decision in promoted
        )

    def score_snapshot(self, snapshot: TrialSnapshot) -> TrialDecision:
        failures: list[str] = []
        if not snapshot.snapshot_complete:
            failures.append("incomplete_snapshot")
        if snapshot.status.lower() not in {"succeeded", "success", "completed"}:
            failures.append(f"status:{snapshot.status or 'missing'}")
        if snapshot.elapsed_seconds <= 0 or snapshot.elapsed_seconds > snapshot.budget_seconds * 1.50:
            failures.append("elapsed_seconds_invalid")
        candidate = self._candidate_by_id.get(snapshot.candidate_id)
        if self.config.require_compiler_artifact_set:
            if not snapshot.compiler_artifact_set_digest:
                failures.append("compiler_artifact_set_missing")
            elif candidate is not None and snapshot.compiler_artifact_set_digest != candidate.compiler_artifact_set_digest:
                failures.append("compiler_artifact_set_mismatch")
        if self.config.require_multi_seed_evidence:
            expected_seeds = set(candidate.seeds if candidate is not None else ())
            observed_seeds = set(snapshot.seed_ids)
            if not snapshot.multi_seed_evidence_complete:
                failures.append("multi_seed_evidence_incomplete")
            if len(observed_seeds) < self.config.seeds_per_candidate:
                failures.append(
                    f"single_seed_or_incomplete:{len(observed_seeds)}<{self.config.seeds_per_candidate}"
                )
            if expected_seeds and observed_seeds != expected_seeds:
                failures.append("multi_seed_set_mismatch")
        if self.config.require_cuda_evidence:
            backend = snapshot.compute_backend.strip().lower()
            if backend not in {"cuda", "torch_cuda", "cuda_resident"}:
                failures.append(f"cuda_backend_required:{backend or 'missing'}")
            if snapshot.cpu_fallback_used:
                failures.append("cpu_fallback_used")
        if snapshot.stale:
            failures.append("stale_evidence")
        if self.config.max_evidence_age_seconds > 0:
            if snapshot.evidence_created_at_epoch <= 0:
                failures.append("evidence_timestamp_missing")
            elif time.time() - snapshot.evidence_created_at_epoch > self.config.max_evidence_age_seconds:
                failures.append("stale_evidence")
        if snapshot.state_revision and snapshot.state_revision != self.config.baseline.revision:
            failures.append("state_revision_mismatch")
        if self.config.require_complete_parallel_lanes:
            if not snapshot.evaluation_lane_complete:
                failures.append("evaluation_lane_incomplete")
            if not snapshot.proof_lane_complete:
                failures.append("proof_lane_incomplete")
        failures.extend(self._family_guardrail_failures(snapshot.family_metrics))
        improvements: dict[str, float] = {}
        if self.config.require_tensorized_objective:
            objective_failures, improvements = self._tensorized_objective(snapshot)
            failures.extend(objective_failures)
            score = -sum(improvements.values()) / max(1, len(improvements))
        else:
            score = self._objective_score(snapshot.metrics)
        return TrialDecision(
            snapshot=snapshot,
            eligible=not failures and math.isfinite(score),
            score=score,
            failures=tuple(failures),
            objective_improvements=MappingProxyType(dict(sorted(improvements.items()))),
        )

    def _tensorized_objective(self, snapshot: TrialSnapshot) -> tuple[list[str], dict[str, float]]:
        failures: list[str] = []
        improvements: dict[str, float] = {}
        for name in TENSORIZED_OBJECTIVE_METRICS:
            aliases = TENSORIZED_METRIC_ALIASES[name]
            before = _metric_value(self.config.baseline.metrics, aliases)
            after = _metric_value(snapshot.metrics, aliases)
            if before is None or after is None:
                failures.append(f"objective_metric_missing:{name}")
                continue
            direction = TENSORIZED_METRIC_DIRECTIONS[name]
            raw_improvement = after - before if direction == "higher" else before - after
            regression_tolerance = _metric_regression_tolerance(
                self.config.metric_regression_tolerances,
                name,
            )
            # Normalize disparate losses/rates without allowing tiny baselines
            # to explode the rank.  Guardrails still operate on the raw pair.
            improvements[name] = raw_improvement / max(abs(before), 1.0e-6, 1.0)
            if not _confidence_proves_no_regression(
                name=name,
                direction=direction,
                baseline_value=before,
                candidate_value=after,
                baseline_metrics=self.config.baseline.metrics,
                candidate_metrics=snapshot.metrics,
                confidence=snapshot.metric_confidence,
                min_confidence=self.config.guardrails.min_confidence,
                regression_tolerance=regression_tolerance,
            ):
                failures.append(f"objective_confidence_guardrail:{name}")
            if raw_improvement < -regression_tolerance - 1.0e-12:
                failures.append(f"objective_metric_regression:{name}")
        return failures, improvements

    def _objective_score(self, metrics: Mapping[str, Any]) -> float:
        ce = _metric(metrics, "best_validation_ce", "validation_ce", default=1e12)
        cosine = _metric(metrics, "best_validation_cosine", "validation_cosine", default=-1.0)
        ir_ce = _metric(metrics, "best_validation_ir_ce", "compiler_ir_cross_entropy_loss", default=ce)
        ir_cosine = _metric(metrics, "best_validation_ir_cosine", "compiler_ir_cosine", default=cosine)
        score = ce + self.config.ir_ce_weight * ir_ce
        score += self.config.cosine_penalty * max(0.0, self.config.min_validation_cosine - cosine)
        score += self.config.ir_cosine_penalty * max(0.0, self.config.min_validation_cosine - ir_cosine)
        return score if math.isfinite(score) else 1e12

    def _family_guardrail_failures(self, family_metrics: Mapping[str, Any]) -> list[str]:
        failures: list[str] = []
        for family in self.config.guardrails.required_families:
            raw = family_metrics.get(family)
            if not isinstance(raw, Mapping):
                failures.append(f"family_guardrail_missing:{family}")
                continue
            for key in GUARDRAIL_BOOLEAN_KEYS:
                if raw.get(key) is True:
                    failures.append(f"{key}:{family}")
            confidence = _confidence(raw)
            if confidence is None or confidence < self.config.guardrails.min_confidence:
                failures.append(f"family_confidence:{family}:{confidence if confidence is not None else 'missing'}")
            baseline = raw.get("baseline")
            candidate = raw.get("candidate")
            compared = False
            semantic_compared = False
            if isinstance(baseline, Mapping) and isinstance(candidate, Mapping):
                for metric in HIGHER_IS_BETTER:
                    before = _maybe_float(baseline.get(metric))
                    after = _maybe_float(candidate.get(metric))
                    if before is not None and after is not None:
                        tolerance = _metric_regression_tolerance(
                            self.config.metric_regression_tolerances,
                            metric,
                        )
                        compared = True
                        if metric in {"semantic_equivalence", "semantic_equivalence_score"}:
                            semantic_compared = True
                        if after < before - tolerance - 1e-12:
                            failures.append(f"family_metric_regression:{family}:{metric}")
                for metric in LOWER_IS_BETTER:
                    before = _maybe_float(baseline.get(metric))
                    after = _maybe_float(candidate.get(metric))
                    if before is not None and after is not None:
                        tolerance = _metric_regression_tolerance(
                            self.config.metric_regression_tolerances,
                            metric,
                        )
                        compared = True
                        if after > before + tolerance + 1e-12:
                            failures.append(f"family_metric_regression:{family}:{metric}")
            if self.config.guardrails.require_paired_metrics and not compared:
                failures.append(f"family_paired_metric_missing:{family}")
            if self.config.require_tensorized_objective and not semantic_compared:
                failures.append(f"family_semantic_equivalence_missing:{family}")
            if self.config.require_tensorized_objective and isinstance(baseline, Mapping) and isinstance(candidate, Mapping):
                for metric in TENSORIZED_FAMILY_METRICS:
                    if metric == "semantic_equivalence":
                        aliases = ("semantic_equivalence", "semantic_equivalence_score")
                        direction = "higher"
                    else:
                        aliases = TENSORIZED_METRIC_ALIASES[metric]
                        direction = TENSORIZED_METRIC_DIRECTIONS[metric]
                    before = _metric_value(baseline, aliases)
                    after = _metric_value(candidate, aliases)
                    tolerance = _metric_regression_tolerance(
                        self.config.metric_regression_tolerances,
                        metric,
                    )
                    if before is None or after is None:
                        failures.append(f"family_objective_metric_missing:{family}:{metric}")
                    elif (direction == "higher" and after < before - tolerance - 1.0e-12) or (
                        direction == "lower" and after > before + tolerance + 1.0e-12
                    ):
                        failure = f"family_metric_regression:{family}:{metric}"
                        if failure not in failures:
                            failures.append(failure)
        return failures

    def rung_decisions(self, rung_index: int) -> tuple[TrialDecision, ...]:
        ids = self._active_candidate_ids_by_rung.get(rung_index, ())
        return tuple(
            self.score_snapshot(self._results[(rung_index, candidate_id)])
            for candidate_id in ids
            if (rung_index, candidate_id) in self._results
        )

    def selected_candidate(self) -> HParamCandidate | None:
        final_index = len(self.config.rungs) - 1
        decisions = [decision for decision in self.rung_decisions(final_index) if decision.eligible]
        if not decisions:
            return None
        best = min(
            decisions,
            key=lambda decision: (
                decision.score,
                self._candidate_by_id[decision.snapshot.candidate_id].seed,
                decision.snapshot.candidate_id,
            ),
        )
        return self._candidate_by_id[best.snapshot.candidate_id]

    def report_dict(self) -> dict[str, Any]:
        """Return a compact, content-addressable search/promotion report."""

        selected = self.selected_candidate()
        completed = self.current_rung_index() is None and bool(
            self._active_candidate_ids_by_rung.get(len(self.config.rungs) - 1)
        )
        rungs = []
        for rung in self.config.rungs:
            decisions = self.rung_decisions(rung.index)
            rungs.append(
                {
                    **rung.to_dict(),
                    "completed_result_count": len(decisions),
                    "eligible_result_count": sum(item.eligible for item in decisions),
                    "decisions": [item.to_dict() for item in decisions],
                }
            )
        result = {
            "schema_version": LEGAL_IR_HPARAM_SCHEDULER_SCHEMA_VERSION,
            "baseline_digest": self.config.baseline.digest,
            "lineage_digest": self.config.baseline.lineage_digest,
            "compiler_artifact_set_digest": self.config.baseline.compiler_artifact_set_digest,
            "search_complete": completed,
            "promotion_eligible": completed and selected is not None,
            "selected_candidate": None if selected is None else selected.to_dict(),
            "rungs": rungs,
        }
        result["report_digest"] = _digest(result)
        return result

    def admit_work(
        self,
        scheduler: GlobalResourceScheduler,
        work_items: Sequence[TrialWorkItem] | None = None,
        *,
        pressure: HParamResourcePressure | Mapping[str, Any] | None = None,
    ) -> tuple[TrialLeaseBundle, ...]:
        """Acquire resource leases for ready work without overcommitting memory."""

        selected = tuple(work_items or self.ready_work())
        bundles: list[TrialLeaseBundle] = []
        trainer_count = 0
        measured_pressure = (
            pressure
            if isinstance(pressure, HParamResourcePressure)
            else HParamResourcePressure.from_mapping(pressure)
            if pressure is not None
            else None
        )
        safe_trainer_limit = self._safe_trainer_limit(scheduler, measured_pressure)
        scheduler_snapshot = scheduler.snapshot()
        gpu_capacity_known = (
            scheduler_snapshot.get("capacity", {}).get("usable_gpu_memory_mb") is not None
        )
        for item in selected:
            if len(bundles) >= self.config.max_concurrent_evaluations:
                break
            eval_lease = scheduler.try_acquire(
                (
                    ResourceLane.SNAPSHOT_EVALUATION
                    if self.config.require_complete_parallel_lanes
                    else ResourceLane.VALIDATION
                ),
                cpu_slots=self.config.resources.evaluation_cpu_slots,
                memory_mb=self.config.resources.evaluation_memory_mb,
                timeout=self.config.resources.lease_timeout_seconds,
                request_id=f"{item.run_id_suffix}:evaluation",
            )
            if eval_lease is None:
                break
            trainer_lease = None
            if trainer_count < safe_trainer_limit:
                trainer_lease = scheduler.try_acquire(
                    (
                        ResourceLane.TRAINER
                        if self.config.require_complete_parallel_lanes
                        else ResourceLane.HAMMER_LEAN
                    ),
                    cpu_slots=self.config.resources.trainer_cpu_slots,
                    memory_mb=self.config.resources.trainer_memory_mb,
                    gpu_memory_mb=(
                        self.config.resources.trainer_gpu_memory_mb if gpu_capacity_known else 0
                    ),
                    unified_memory_mb=(
                        self.config.resources.trainer_unified_memory_mb
                        if self.config.require_measured_second_trainer_pressure
                        else 0
                    ),
                    requires_gpu=gpu_capacity_known and self.config.resources.trainer_gpu_memory_mb > 0,
                    timeout=self.config.resources.lease_timeout_seconds,
                    request_id=f"{item.run_id_suffix}:trainer",
                )
                if trainer_lease is not None:
                    trainer_count += 1
            if trainer_lease is None:
                eval_lease.release()
                if bundles:
                    break
                break
            proof_lease = None
            if self.config.require_complete_parallel_lanes:
                proof_lease = scheduler.try_acquire(
                    ResourceLane.HAMMER,
                    cpu_slots=self.config.resources.proof_cpu_slots,
                    memory_mb=self.config.resources.proof_memory_mb,
                    child_process_slots=self.config.resources.proof_child_process_slots,
                    timeout=self.config.resources.lease_timeout_seconds,
                    request_id=f"{item.run_id_suffix}:proof",
                )
                if proof_lease is None:
                    trainer_lease.release()
                    eval_lease.release()
                    break
            bundles.append(TrialLeaseBundle(item, eval_lease, trainer_lease, proof_lease))
        return tuple(bundles)

    def trainer_limit(
        self,
        scheduler: GlobalResourceScheduler,
        pressure: HParamResourcePressure | Mapping[str, Any] | None = None,
    ) -> int:
        measured = (
            pressure
            if isinstance(pressure, HParamResourcePressure)
            else HParamResourcePressure.from_mapping(pressure)
            if pressure is not None
            else None
        )
        return self._safe_trainer_limit(scheduler, measured)

    def _safe_trainer_limit(
        self,
        scheduler: GlobalResourceScheduler,
        pressure: HParamResourcePressure | None = None,
    ) -> int:
        if self.config.max_concurrent_trainers <= 1 or not self.config.allow_concurrent_trainers:
            return 1
        snapshot = scheduler.snapshot()
        capacity = snapshot.get("capacity", {})
        available = snapshot.get("available", {})
        total_gpu = capacity.get("usable_gpu_memory_mb")
        available_gpu = available.get("gpu_memory_mb")
        if total_gpu is None or available_gpu is None:
            return 1
        per_trainer = max(1, self.config.resources.trainer_gpu_memory_mb)
        memory_fit = max(1, int(float(available_gpu) // per_trainer))
        if memory_fit < 2:
            return 1
        if self.config.require_measured_second_trainer_pressure:
            if pressure is None or not pressure.telemetry_known:
                return 1
            if self.config.pressure_max_age_seconds > 0 and (
                pressure.measured_at_epoch <= 0
                or time.time() - pressure.measured_at_epoch > self.config.pressure_max_age_seconds
            ):
                return 1
            worst_resource_pressure = max(
                pressure.unified_memory_pressure,
                pressure.gpu_memory_pressure,
                pressure.memory_pressure,
                pressure.swap_pressure,
            )
            worst_service_pressure = max(
                pressure.service_pressure,
                pressure.proof_queue_pressure,
                pressure.validation_queue_pressure,
            )
            if worst_resource_pressure > self.config.max_second_trainer_pressure:
                return 1
            if worst_service_pressure > self.config.max_service_pressure:
                return 1
            capacity = snapshot.get("capacity", {})
            available = snapshot.get("available", {})
            total_unified = capacity.get("unified_memory_mb")
            available_unified = available.get("unified_memory_mb")
            if total_unified is None or available_unified is None:
                return 1
            unified_per_trainer = max(1, self.config.resources.trainer_unified_memory_mb)
            if int(float(available_unified) // unified_per_trainer) < 2:
                return 1
        return max(1, min(2, self.config.max_concurrent_trainers, memory_fit))


def _metric_value(metrics: Mapping[str, Any], keys: Sequence[str]) -> float | None:
    for key in keys:
        raw = metrics.get(key)
        if isinstance(raw, Mapping):
            for value_key in ("value", "mean", "candidate", "observed"):
                value = _maybe_float(raw.get(value_key))
                if value is not None:
                    return value
        value = _maybe_float(raw)
        if value is not None:
            return value
    return None


def _metric_regression_tolerance(
    tolerances: Mapping[str, float],
    metric: str,
) -> float:
    """Resolve a canonical tolerance for either a canonical metric or an alias."""

    canonical = metric
    if canonical not in TENSORIZED_METRIC_DIRECTIONS:
        for name, aliases in TENSORIZED_METRIC_ALIASES.items():
            if metric in aliases:
                canonical = name
                break
    value = _maybe_float(tolerances.get(canonical))
    return max(0.0, value) if value is not None else 0.0


def _bound(payload: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _maybe_float(payload.get(key))
        if value is not None:
            return value
    return None


def _confidence_proves_no_regression(
    *,
    name: str,
    direction: str,
    baseline_value: float,
    candidate_value: float,
    baseline_metrics: Mapping[str, Any],
    candidate_metrics: Mapping[str, Any],
    confidence: Mapping[str, Any],
    min_confidence: float,
    regression_tolerance: float = 0.0,
) -> bool:
    """Apply conservative paired confidence bounds for a hard metric gate."""

    raw = confidence.get(name)
    if not isinstance(raw, Mapping):
        # Also accept bounds adjacent to a structured metric value.
        for alias in TENSORIZED_METRIC_ALIASES.get(name, (name,)):
            candidate_raw = candidate_metrics.get(alias)
            if isinstance(candidate_raw, Mapping):
                raw = candidate_raw
                break
    if not isinstance(raw, Mapping):
        return False
    confidence_value = _bound(raw, "confidence", "confidence_level", "sample_confidence")
    if confidence_value is None or confidence_value < min_confidence:
        return False
    baseline_raw: Mapping[str, Any] = {}
    for alias in TENSORIZED_METRIC_ALIASES.get(name, (name,)):
        item = baseline_metrics.get(alias)
        if isinstance(item, Mapping):
            baseline_raw = item
            break
    if direction == "higher":
        candidate_conservative = _bound(
            raw, "candidate_lower_bound", "confidence_lower_bound", "lower_bound"
        )
        baseline_conservative = _bound(
            raw, "baseline_upper_bound"
        )
        if baseline_conservative is None:
            baseline_conservative = _bound(baseline_raw, "upper_bound", "confidence_upper_bound")
        return (
            candidate_conservative if candidate_conservative is not None else candidate_value
        ) >= (
            baseline_conservative if baseline_conservative is not None else baseline_value
        ) - regression_tolerance - 1.0e-12
    candidate_conservative = _bound(
        raw, "candidate_upper_bound", "confidence_upper_bound", "upper_bound"
    )
    baseline_conservative = _bound(raw, "baseline_lower_bound")
    if baseline_conservative is None:
        baseline_conservative = _bound(baseline_raw, "lower_bound", "confidence_lower_bound")
    return (
        candidate_conservative if candidate_conservative is not None else candidate_value
    ) <= (
        baseline_conservative if baseline_conservative is not None else baseline_value
    ) + regression_tolerance + 1.0e-12


def _metric(metrics: Mapping[str, Any], *keys: str, default: float) -> float:
    for key in keys:
        value = _maybe_float(metrics.get(key))
        if value is not None:
            return value
    return default


def _maybe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _confidence(raw: Mapping[str, Any]) -> float | None:
    for key in ("confidence_lower_bound", "sample_confidence", "confidence"):
        value = _maybe_float(raw.get(key))
        if value is not None:
            return max(0.0, min(1.0, value))
    candidate = raw.get("candidate")
    if isinstance(candidate, Mapping):
        for key in ("confidence_lower_bound", "sample_confidence", "confidence"):
            value = _maybe_float(candidate.get(key))
            if value is not None:
                return max(0.0, min(1.0, value))
    return None


def default_baseline_from_env() -> SharedBaseline:
    revision = os.environ.get("LEGAL_IR_HPARAM_BASELINE_REVISION", "workspace")
    dataset_digest = os.environ.get(
        "LEGAL_IR_HPARAM_DATASET_DIGEST", "sha256:unknown-dataset"
    )
    artifact_manifest_digest = os.environ.get(
        "LEGAL_IR_HPARAM_COMPILER_ARTIFACT_DIGEST",
        "sha256:" + _digest(
            {
                "compiler_revision": revision,
                "dataset_digest": dataset_digest,
                "source": "legal-ir-hparam-default-artifact-manifest",
            }
        ),
    )
    return SharedBaseline(
        baseline_id=os.environ.get("LEGAL_IR_HPARAM_BASELINE_ID", "legal-ir-shared-baseline"),
        revision=revision,
        dataset_digest=dataset_digest,
        metric_lineage_id=os.environ.get("LEGAL_IR_HPARAM_METRIC_LINEAGE_ID", "legal-ir-current-metrics"),
        compiler_artifact_set=CompilerArtifactSet(
            compiler_revision=revision,
            compiler_config_digest=os.environ.get(
                "LEGAL_IR_HPARAM_COMPILER_CONFIG_DIGEST", "sha256:default-compiler-config"
            ),
            dataset_digest=dataset_digest,
            artifacts={"manifest": artifact_manifest_digest},
        ),
    )


def build_default_scheduler(
    *,
    total_budget_seconds: int = 3600,
    candidate_count: int = 12,
    base_seed: int = 8675309,
    allow_concurrent_trainers: bool = True,
    max_concurrent_trainers: int = 2,
    seeds_per_candidate: int = 3,
) -> LegalIRHParamScheduler:
    config = HParamSearchConfig(
        baseline=default_baseline_from_env(),
        total_budget_seconds=total_budget_seconds,
        initial_candidate_count=candidate_count,
        base_seed=base_seed,
        allow_concurrent_trainers=allow_concurrent_trainers,
        max_concurrent_trainers=max_concurrent_trainers,
        seeds_per_candidate=seeds_per_candidate,
        require_multi_seed_evidence=True,
        require_cuda_evidence=True,
        require_compiler_artifact_set=True,
        require_complete_parallel_lanes=True,
        require_tensorized_objective=True,
        max_evidence_age_seconds=900.0,
        require_measured_second_trainer_pressure=True,
    )
    return LegalIRHParamScheduler(config)


def _format_env(plan: Mapping[str, Any], *, run_id: str) -> str:
    rungs = plan["successive_halving"]["rungs"]
    return "\n".join(
        [
            f"hparam_scheduler_schema={plan['schema_version']}",
            f"hparam_run_id={run_id}",
            f"hparam_candidate_count={plan['candidate_count']}",
            f"hparam_planned_resource_seconds={plan['planned_resource_seconds']}",
            f"hparam_total_budget_seconds={plan['total_budget_seconds']}",
            "hparam_rung_budgets="
            + ",".join(str(rung["budget_seconds"]) for rung in rungs),
            "hparam_rung_survivors="
            + ",".join(str(rung["survivor_count"]) for rung in rungs),
            "hparam_parallel_lanes="
            + ",".join(plan["resource_policy"]["parallel_lanes"]),
            f"hparam_default_cuda_trainers={plan['resource_policy']['default_cuda_trainers']}",
            f"hparam_allow_concurrent_trainers={str(plan['resource_policy']['allow_concurrent_trainers']).lower()}",
            f"hparam_conditional_max_cuda_trainers={plan['resource_policy']['conditional_max_cuda_trainers']}",
            "hparam_second_trainer_requires_measured_pressure="
            + str(plan["resource_policy"]["second_trainer_requires_measured_pressure"]).lower(),
            f"hparam_seed_count={plan['promotion_policy']['required_seed_count']}",
            f"hparam_baseline_digest={plan['immutable_input_policy']['baseline_digest']}",
            "hparam_compiler_artifact_set_digest="
            + plan["immutable_input_policy"]["compiler_artifact_set_digest"],
            "hparam_required_objective_metrics="
            + ",".join(plan["promotion_policy"]["required_objective_metrics"]),
            "hparam_required_metrics_per_family="
            + ",".join(plan["promotion_policy"]["required_metrics_per_family"]),
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan", help="emit deterministic hparam search plan")
    plan_parser.add_argument("--run-id", default="legal-ir-hparam")
    plan_parser.add_argument("--budget-seconds", type=int, default=3600)
    plan_parser.add_argument("--candidate-count", type=int, default=12)
    plan_parser.add_argument("--base-seed", type=int, default=8675309)
    plan_parser.add_argument(
        "--allow-concurrent-trainers",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    plan_parser.add_argument("--max-concurrent-trainers", type=int, default=2)
    plan_parser.add_argument("--seeds-per-candidate", type=int, default=3)
    plan_parser.add_argument("--format", choices=("json", "env"), default="json")
    plan_parser.add_argument("--resource-state-path", default="")
    args = parser.parse_args(argv)

    if args.command == "plan":
        scheduler = build_default_scheduler(
            total_budget_seconds=args.budget_seconds,
            candidate_count=args.candidate_count,
            base_seed=args.base_seed,
            allow_concurrent_trainers=args.allow_concurrent_trainers,
            max_concurrent_trainers=args.max_concurrent_trainers,
            seeds_per_candidate=args.seeds_per_candidate,
        )
        plan = scheduler.plan_dict()
        if args.resource_state_path:
            resource_scheduler = GlobalResourceScheduler(
                ResourceSchedulerConfig(state_path=Path(args.resource_state_path))
            )
            plan["resource_scheduler"] = resource_scheduler.snapshot()
        if args.format == "env":
            print(_format_env(plan, run_id=args.run_id))
        else:
            print(_canonical_json({"run_id": args.run_id, **plan}))
        return 0
    return 2


__all__ = [
    "LEGAL_IR_HPARAM_SCHEDULER_SCHEMA_VERSION",
    "TENSORIZED_OBJECTIVE_METRICS",
    "TENSORIZED_FAMILY_METRICS",
    "SharedBaseline",
    "CompilerArtifactSet",
    "HParamCandidate",
    "HParamRung",
    "FamilyGuardrailConfig",
    "ResourceRequirements",
    "HParamResourcePressure",
    "HParamSearchConfig",
    "TrialWorkItem",
    "TrialLaneResults",
    "TrialSnapshot",
    "TrialDecision",
    "TrialLeaseBundle",
    "LegalIRHParamScheduler",
    "build_default_scheduler",
    "default_baseline_from_env",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
