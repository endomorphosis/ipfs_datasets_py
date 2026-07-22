"""Evidence-driven autotuning for the parallel LegalIR optimizer pipeline.

The tuner deliberately does not launch workloads.  Benchmarking and process
ownership belong to the daemon/benchmark harness; this module consumes their
source-free aggregate evidence and makes a deterministic production-profile
decision.  Keeping the decision pure makes trials repeatable and prevents a
search process from weakening proof or reconstruction trust boundaries.

The important policy distinction is that CPU utilization is a constraint and
small scoring signal, not the objective.  Useful end-to-end throughput,
tail-latency, accepted patches, proof/reconstruction work, queue health, and
quality are optimized together.  A fast candidate is never eligible when it
regresses trusted quality, overcommits the global scheduler, uses more than one
trainer, or exceeds memory/swap/GPU/process bounds.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, Mapping, Sequence


PARALLELISM_AUTOTUNER_SCHEMA_VERSION: Final = "legal-ir-parallelism-autotuner-v1"
PIPELINE_BENCHMARK_SCHEMA_VERSION: Final = "legal-ir-optimizer-pipeline-benchmark-v1"
DGX_SPARK_PROFILE_SCHEMA_VERSION: Final = "legal-ir-dgx-spark-production-profile-v1"
ADAPTIVE_PIPELINE_PARALLELISM_SCHEMA_VERSION: Final = (
    "legal-ir-adaptive-pipeline-parallelism-v1"
)
BATCH_SIZE_AUTOTUNER_SCHEMA_VERSION: Final = "modal-autoencoder-batch-autotuner-v1"

HIGHER_IS_BETTER_QUALITY: Final = frozenset(
    {
        "compiler_ir_cosine",
        "hammer_proof_success_rate",
        "hammer_reconstruction_success_rate",
        "structural_validity",
        "symbolic_validity_success_rate",
    }
)
LOWER_IS_BETTER_QUALITY: Final = frozenset(
    {
        "compiler_ir_cross_entropy_loss",
        "source_copy_penalty",
        "source_copy_reward_hack_penalty",
    }
)
REQUIRED_QUALITY_METRICS: Final = (
    "compiler_ir_cosine",
    "structural_validity",
    "symbolic_validity_success_rate",
    "hammer_proof_success_rate",
    "hammer_reconstruction_success_rate",
    "source_copy_penalty",
)


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


def _integer(value: Any, *, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _ratio(value: Any, *, name: str) -> float:
    result = _finite(value, name=name, minimum=0.0)
    if result > 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return result


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_digest(value: Any) -> str:
    """Return a stable SHA-256 digest for JSON-compatible evidence."""

    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ParallelismProfile:
    """All knobs that affect concurrency or bounded queueing in one trial."""

    name: str
    hammer_workers: int = 4
    lean_reconstruction_workers: int = 2
    leanstral_workers: int = 2
    legal_ir_family_workers: int = 4
    incremental_validation_workers: int = 4
    snapshot_evaluator_workers: int = 2
    codex_workers: int = 4
    orchestration_workers: int = 2
    trainer_count: int = 1
    leanstral_batch_min: int = 4
    leanstral_batch_max: int = 8
    snapshot_queue_capacity: int = 4
    leanstral_queue_capacity: int = 64
    codex_queue_capacity: int = 32
    hammer_lean_cpu_slots: int = 8
    validation_cpu_slots: int = 4
    codex_cpu_slots: int = 4
    orchestration_cpu_slots: int = 2
    reserve_cpu_slots: int = 2
    memory_budget_mb: int = 96 * 1024
    modal_autoencoder_batch_min: int = 32
    modal_autoencoder_batch_max: int = 64

    def __post_init__(self) -> None:
        name = str(self.name or "").strip()
        portable = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        if not name or len(name) > 96 or any(ch not in portable for ch in name):
            raise ValueError("profile name must be a non-empty portable identifier")
        object.__setattr__(self, "name", name)
        for field_name in (
            "hammer_workers", "lean_reconstruction_workers", "leanstral_workers",
            "legal_ir_family_workers", "incremental_validation_workers",
            "snapshot_evaluator_workers", "codex_workers", "orchestration_workers",
            "trainer_count", "leanstral_batch_min", "leanstral_batch_max",
            "snapshot_queue_capacity", "leanstral_queue_capacity", "codex_queue_capacity",
            "hammer_lean_cpu_slots", "validation_cpu_slots", "codex_cpu_slots",
            "orchestration_cpu_slots", "reserve_cpu_slots", "memory_budget_mb",
            "modal_autoencoder_batch_min", "modal_autoencoder_batch_max",
        ):
            _integer(getattr(self, field_name), name=field_name, minimum=1)
        if self.leanstral_batch_min > self.leanstral_batch_max:
            raise ValueError("leanstral_batch_min cannot exceed leanstral_batch_max")
        if self.modal_autoencoder_batch_min > self.modal_autoencoder_batch_max:
            raise ValueError(
                "modal_autoencoder_batch_min cannot exceed modal_autoencoder_batch_max"
            )

    @property
    def allocated_cpu_slots(self) -> int:
        return (
            self.hammer_lean_cpu_slots + self.validation_cpu_slots + self.codex_cpu_slots
            + self.orchestration_cpu_slots + self.reserve_cpu_slots
        )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ParallelismProfile":
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: item for key, item in dict(value).items() if key in allowed})

    def with_name(self, name: str) -> "ParallelismProfile":
        return replace(self, name=name)


FIXED_DGX_SPARK_BASELINE: Final = ParallelismProfile(name="fixed_baseline")

# Admission ceiling for the dependency-DAG runtime.  The persistent
# Leanstral lane is deliberately a singleton; batching and request concurrency
# happen inside that service rather than by loading another model.  The CPU
# lane allocation remains valid under the default 20-slot global bound.
DGX_SPARK_INITIAL_PIPELINE_PROFILE: Final = ParallelismProfile(
    name="dgx_spark_pipeline_initial",
    hammer_workers=2,
    lean_reconstruction_workers=2,
    leanstral_workers=1,
    legal_ir_family_workers=4,
    incremental_validation_workers=4,
    snapshot_evaluator_workers=4,
    codex_workers=6,
    orchestration_workers=2,
    trainer_count=1,
    hammer_lean_cpu_slots=5,
    validation_cpu_slots=4,
    codex_cpu_slots=6,
    orchestration_cpu_slots=2,
    reserve_cpu_slots=3,
)
# More concise compatibility alias for callers that describe it as stage
# rather than pipeline parallelism.
DGX_SPARK_INITIAL_STAGE_PROFILE: Final = DGX_SPARK_INITIAL_PIPELINE_PROFILE


@dataclass(frozen=True, slots=True)
class GlobalResourceBounds:
    """DGX Spark host limits and useful-utilization operating envelope."""

    total_cpu_slots: int = 20
    total_memory_mb: int = 128 * 1024
    max_profile_memory_fraction: float = 0.80
    useful_cpu_utilization_min: float = 0.70
    useful_cpu_utilization_max: float = 0.90
    max_memory_percent: float = 90.0
    max_swap_percent: float = 1.0
    max_gpu_memory_percent: float = 92.0
    max_child_processes: int = 64
    max_leanstral_workers: int = 4
    max_leanstral_batch_size: int = 16
    max_modal_autoencoder_batch_size: int = 64
    target_cycle_seconds: float = 400.0
    max_queue_lag_p95_seconds: float = 120.0

    def __post_init__(self) -> None:
        _integer(self.total_cpu_slots, name="total_cpu_slots", minimum=1)
        _integer(self.total_memory_mb, name="total_memory_mb", minimum=1)
        _integer(self.max_child_processes, name="max_child_processes", minimum=1)
        _integer(self.max_leanstral_workers, name="max_leanstral_workers", minimum=1)
        _integer(self.max_leanstral_batch_size, name="max_leanstral_batch_size", minimum=1)
        _integer(
            self.max_modal_autoencoder_batch_size,
            name="max_modal_autoencoder_batch_size",
            minimum=1,
        )
        _ratio(self.max_profile_memory_fraction, name="max_profile_memory_fraction")
        low = _ratio(self.useful_cpu_utilization_min, name="useful_cpu_utilization_min")
        high = _ratio(self.useful_cpu_utilization_max, name="useful_cpu_utilization_max")
        if low >= high:
            raise ValueError("useful CPU utilization minimum must be below maximum")
        for name in ("max_memory_percent", "max_swap_percent", "max_gpu_memory_percent"):
            value = _finite(getattr(self, name), name=name, minimum=0.0)
            if value > 100.0:
                raise ValueError(f"{name} cannot exceed 100")
        _finite(self.target_cycle_seconds, name="target_cycle_seconds", minimum=0.001)
        _finite(self.max_queue_lag_p95_seconds, name="max_queue_lag_p95_seconds", minimum=0.0)

    def profile_violations(self, profile: ParallelismProfile) -> list[str]:
        failures: list[str] = []
        if profile.allocated_cpu_slots > self.total_cpu_slots:
            failures.append(f"cpu_slots:{profile.allocated_cpu_slots}>{self.total_cpu_slots}")
        max_memory = int(self.total_memory_mb * self.max_profile_memory_fraction)
        if profile.memory_budget_mb > max_memory:
            failures.append(f"memory_budget_mb:{profile.memory_budget_mb}>{max_memory}")
        if profile.trainer_count != 1:
            failures.append(f"trainer_count:{profile.trainer_count}!=1")
        hammer_lane_workers = (
            profile.hammer_workers
            + profile.lean_reconstruction_workers
            + profile.leanstral_workers
        )
        if hammer_lane_workers > profile.hammer_lean_cpu_slots:
            failures.append("hammer_lean_workers_exceed_lane")
        if (
            max(profile.legal_ir_family_workers, profile.incremental_validation_workers)
            > profile.validation_cpu_slots
        ):
            failures.append("validation_workers_exceed_lane")
        if profile.snapshot_evaluator_workers > profile.validation_cpu_slots:
            failures.append("snapshot_evaluator_workers_exceed_lane")
        if profile.codex_workers > profile.codex_cpu_slots:
            failures.append("codex_workers_exceed_lane")
        if profile.orchestration_workers > profile.orchestration_cpu_slots:
            failures.append("orchestration_workers_exceed_lane")
        if profile.leanstral_workers > self.max_leanstral_workers:
            failures.append("leanstral_workers_exceed_global_bound")
        if profile.leanstral_batch_max > self.max_leanstral_batch_size:
            failures.append("leanstral_batch_exceeds_global_bound")
        if profile.modal_autoencoder_batch_max > self.max_modal_autoencoder_batch_size:
            failures.append("modal_autoencoder_batch_exceeds_global_bound")
        return failures

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class TrustBounds:
    """Fail-closed correctness gates applied before performance ranking."""

    max_transient_failure_rate: float = 0.10
    max_relative_throughput_regression: float = 0.05
    max_latency_regression: float = 0.05
    max_quality_regression: float = 0.0
    max_proof_rate_regression: float = 0.0
    max_reconstruction_rate_regression: float = 0.0
    minimum_sample_count: int = 1
    required_quality_metrics: tuple[str, ...] = REQUIRED_QUALITY_METRICS

    def __post_init__(self) -> None:
        for name in (
            "max_transient_failure_rate", "max_relative_throughput_regression",
            "max_latency_regression", "max_quality_regression",
            "max_proof_rate_regression", "max_reconstruction_rate_regression",
        ):
            _ratio(getattr(self, name), name=name)
        _integer(self.minimum_sample_count, name="minimum_sample_count", minimum=1)
        normalized = tuple(str(item).strip() for item in self.required_quality_metrics)
        if not normalized or any(not item for item in normalized):
            raise ValueError("required_quality_metrics must not be empty")
        object.__setattr__(self, "required_quality_metrics", normalized)

    def to_dict(self) -> dict[str, Any]:
        payload = {name: getattr(self, name) for name in self.__dataclass_fields__}
        payload["required_quality_metrics"] = list(self.required_quality_metrics)
        return payload


@dataclass(frozen=True, slots=True)
class PhaseLatency:
    p50_seconds: float
    p95_seconds: float

    def __post_init__(self) -> None:
        p50 = _finite(self.p50_seconds, name="p50_seconds", minimum=0.0)
        p95 = _finite(self.p95_seconds, name="p95_seconds", minimum=0.0)
        if p95 < p50:
            raise ValueError("p95_seconds cannot be below p50_seconds")

    def to_dict(self) -> dict[str, float]:
        return {"p50_seconds": self.p50_seconds, "p95_seconds": self.p95_seconds}


@dataclass(frozen=True, slots=True)
class PipelineBenchmarkMetrics:
    """Complete aggregate evidence for one parallelism profile."""

    cold_cache_throughput_per_hour: float
    warm_cache_throughput_per_hour: float
    phase_latency: Mapping[str, PhaseLatency | Mapping[str, Any]]
    trainer_duty_cycle: float
    proof_throughput_per_hour: float
    reconstruction_throughput_per_hour: float
    leanstral_batch_efficiency: float
    leanstral_average_batch_size: float
    cpu_utilization_average: float
    cpu_utilization_peak: float
    gpu_utilization_average: float
    gpu_utilization_peak: float
    gpu_memory_percent_peak: float
    memory_percent_peak: float
    memory_used_bytes_peak: int
    swap_percent_peak: float
    swap_used_bytes_peak: int
    child_process_count_peak: int
    queue_lag_p50_seconds: float
    queue_lag_p95_seconds: float
    queue_depth_peak: int
    codex_accepted_patches_per_hour: float
    transient_failure_rate: float
    cycle_seconds: float
    cold_cache_hit_rate: float
    warm_cache_hit_rate: float
    quality_metrics: Mapping[str, float]
    sample_count: int = 0
    gpu_telemetry_known: bool = True

    def __post_init__(self) -> None:
        nonnegative = (
            "cold_cache_throughput_per_hour", "warm_cache_throughput_per_hour",
            "proof_throughput_per_hour", "reconstruction_throughput_per_hour",
            "leanstral_average_batch_size", "gpu_memory_percent_peak", "memory_percent_peak", "swap_percent_peak",
            "queue_lag_p50_seconds", "queue_lag_p95_seconds",
            "codex_accepted_patches_per_hour", "cycle_seconds",
        )
        for name in nonnegative:
            _finite(getattr(self, name), name=name, minimum=0.0)
        for name in (
            "trainer_duty_cycle", "leanstral_batch_efficiency", "cpu_utilization_average",
            "cpu_utilization_peak", "gpu_utilization_average", "gpu_utilization_peak",
            "cold_cache_hit_rate", "warm_cache_hit_rate", "transient_failure_rate",
        ):
            _ratio(getattr(self, name), name=name)
        if not isinstance(self.gpu_telemetry_known, bool):
            raise ValueError("gpu_telemetry_known must be a bool")
        for name in (
            "memory_used_bytes_peak", "swap_used_bytes_peak", "child_process_count_peak",
            "queue_depth_peak", "sample_count",
        ):
            _integer(getattr(self, name), name=name, minimum=0)
        if self.cpu_utilization_peak < self.cpu_utilization_average:
            raise ValueError("CPU utilization peak cannot be below its average")
        if self.gpu_utilization_peak < self.gpu_utilization_average:
            raise ValueError("GPU utilization peak cannot be below its average")
        if self.queue_lag_p95_seconds < self.queue_lag_p50_seconds:
            raise ValueError("queue lag p95 cannot be below p50")
        phases: dict[str, PhaseLatency] = {}
        for raw_name, raw_latency in dict(self.phase_latency).items():
            name = str(raw_name or "").strip()
            if not name:
                raise ValueError("phase latency names must be non-empty")
            phases[name] = (
                raw_latency
                if isinstance(raw_latency, PhaseLatency)
                else PhaseLatency(**dict(raw_latency))
            )
        if not phases:
            raise ValueError("phase_latency must contain at least one measured phase")
        object.__setattr__(self, "phase_latency", phases)
        quality = {
            str(name): _finite(value, name=f"quality_metrics.{name}")
            for name, value in dict(self.quality_metrics).items()
        }
        object.__setattr__(self, "quality_metrics", quality)

    def to_dict(self) -> dict[str, Any]:
        payload = {name: getattr(self, name) for name in self.__dataclass_fields__}
        payload["phase_latency"] = {
            name: value.to_dict() for name, value in sorted(self.phase_latency.items())
        }
        payload["quality_metrics"] = dict(sorted(self.quality_metrics.items()))
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PipelineBenchmarkMetrics":
        payload = dict(value)
        if (
            payload.get("schema_version") == PIPELINE_BENCHMARK_SCHEMA_VERSION
            and isinstance(payload.get("metrics"), Mapping)
        ):
            payload = dict(payload["metrics"])
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: item for key, item in payload.items() if key in allowed})


@dataclass(frozen=True, slots=True)
class BenchmarkTrial:
    profile: ParallelismProfile
    metrics: PipelineBenchmarkMetrics

    def to_dict(self) -> dict[str, Any]:
        return {"profile": self.profile.to_dict(), "metrics": self.metrics.to_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BenchmarkTrial":
        return cls(
            profile=ParallelismProfile.from_dict(dict(value["profile"])),
            metrics=PipelineBenchmarkMetrics.from_dict(dict(value["metrics"])),
        )


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    profile_name: str
    eligible: bool
    score: float
    violations: tuple[str, ...]
    deltas: Mapping[str, float]
    trial_evidence_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_name": self.profile_name,
            "eligible": self.eligible,
            "score": round(self.score, 9),
            "violations": list(self.violations),
            "deltas": {key: round(value, 9) for key, value in sorted(self.deltas.items())},
            "trial_evidence_digest": self.trial_evidence_digest,
        }


@dataclass(frozen=True, slots=True)
class AutotuneResult:
    baseline: BenchmarkTrial
    selected: BenchmarkTrial
    promoted: bool
    evaluations: tuple[CandidateEvaluation, ...]
    resource_bounds: GlobalResourceBounds
    trust_bounds: TrustBounds

    def production_profile(self) -> dict[str, Any]:
        settings = self.selected.profile
        evidence = {
            "baseline": self.baseline.to_dict(),
            "candidates": [item.to_dict() for item in self.evaluations],
            "selected_metrics": self.selected.metrics.to_dict(),
        }
        selected_comparison = next(
            (item.to_dict() for item in self.evaluations if item.profile_name == self.selected.profile.name),
            {
                "profile_name": self.baseline.profile.name,
                "eligible": True,
                "score": 0.0,
                "violations": [],
                "deltas": {},
                "trial_evidence_digest": canonical_digest(self.baseline.to_dict()),
            },
        )
        body: dict[str, Any] = {
            "schema_version": DGX_SPARK_PROFILE_SCHEMA_VERSION,
            "autotuner_schema_version": PARALLELISM_AUTOTUNER_SCHEMA_VERSION,
            "hardware": {
                "target": "NVIDIA DGX Spark",
                "cpu": "20-core Arm",
                "gpu_count": 1,
                "unified_memory_mb": self.resource_bounds.total_memory_mb,
            },
            "promotion": {
                "baseline_profile": self.baseline.profile.name,
                "selected_profile": self.selected.profile.name,
                "promoted": self.promoted,
                "selection_rule": "highest_balanced_score_with_resource_and_trust_gates",
            },
            "settings": settings.to_dict(),
            "application": {
                "environment": {
                    "IPFS_DATASETS_RESOURCE_CPU_SLOTS": str(self.resource_bounds.total_cpu_slots),
                    "IPFS_DATASETS_RESOURCE_MEMORY_MB": str(settings.memory_budget_mb),
                    "IPFS_DATASETS_LEGAL_IR_PARALLEL_WORKERS": str(settings.legal_ir_family_workers),
                },
                "daemon_arguments": {
                    "--autoencoder-bridge-workers": settings.legal_ir_family_workers,
                    "--codex-initial-max-workers": settings.codex_workers,
                    "--daemon-hammer-guidance-parallel-workers": settings.hammer_workers,
                    "--snapshot-evaluation-queue-capacity": settings.snapshot_queue_capacity,
                },
                "leanstral_worker_arguments": {
                    "--batch-max-workers": settings.leanstral_workers,
                    "--batch-min-size": settings.leanstral_batch_min,
                    "--batch-size": settings.leanstral_batch_max,
                    "--lean-parallel-workers": settings.lean_reconstruction_workers,
                },
                "lane_cpu_reservations": {
                    "hammer_lean": settings.hammer_lean_cpu_slots,
                    "validation": settings.validation_cpu_slots,
                    "codex": settings.codex_cpu_slots,
                    "orchestration": settings.orchestration_cpu_slots,
                    "reserve": settings.reserve_cpu_slots,
                },
            },
            "baseline_comparison": selected_comparison,
            "resource_bounds": self.resource_bounds.to_dict(),
            "trust_bounds": self.trust_bounds.to_dict(),
            "evidence_digest": canonical_digest(evidence),
        }
        body["profile_digest"] = canonical_digest(body)
        return body

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PARALLELISM_AUTOTUNER_SCHEMA_VERSION,
            "baseline": self.baseline.to_dict(),
            "selected": self.selected.to_dict(),
            "promoted": self.promoted,
            "evaluations": [item.to_dict() for item in self.evaluations],
            "production_profile": self.production_profile(),
        }


def _relative(candidate: float, baseline: float) -> float:
    if baseline <= 0.0:
        return 0.0 if candidate <= 0.0 else 1.0
    return (candidate - baseline) / baseline


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _bounded_ratio(value: Any, *, name: str, allow_percent: bool = True) -> float:
    result = _finite(value, name=name, minimum=0.0)
    if allow_percent and result > 1.0:
        result /= 100.0
    return max(0.0, min(1.0, result))


def _normalized_count_mapping(value: Mapping[str, Any], *, name: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for raw_key, raw_value in dict(value or {}).items():
        key = str(raw_key or "").strip().lower()
        if not key:
            raise ValueError(f"{name} keys must be non-empty")
        result[key] = _integer(raw_value, name=f"{name}.{key}", minimum=0)
    return result


def _normalized_float_mapping(value: Mapping[str, Any], *, name: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for raw_key, raw_value in dict(value or {}).items():
        key = str(raw_key or "").strip().lower()
        if not key:
            raise ValueError(f"{name} keys must be non-empty")
        result[key] = _finite(raw_value, name=f"{name}.{key}", minimum=0.0)
    return result


def _first_named(mapping: Mapping[str, Any], names: Sequence[str], default: Any = 0) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return default


@dataclass(frozen=True, slots=True)
class RuntimeResourcePressure:
    """Current source-free host pressure normalized for adaptive worker control."""

    cpu_utilization: float = 0.0
    memory_pressure: float = 0.0
    swap_pressure: float = 0.0
    gpu_memory_pressure: float = 0.0
    unified_memory_pressure: float = 0.0
    gpu_utilization: float = 0.0
    gpu_telemetry_known: bool = True
    child_process_count: int = 0
    child_process_limit: int = 64

    def __post_init__(self) -> None:
        for name in (
            "cpu_utilization",
            "memory_pressure",
            "swap_pressure",
            "gpu_memory_pressure",
            "unified_memory_pressure",
            "gpu_utilization",
        ):
            object.__setattr__(
                self,
                name,
                _bounded_ratio(getattr(self, name), name=name),
            )
        if not isinstance(self.gpu_telemetry_known, bool):
            raise ValueError("gpu_telemetry_known must be a bool")
        _integer(self.child_process_count, name="child_process_count", minimum=0)
        _integer(self.child_process_limit, name="child_process_limit", minimum=1)

    @property
    def child_process_pressure(self) -> float:
        return max(0.0, min(1.0, self.child_process_count / self.child_process_limit))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "RuntimeResourcePressure":
        data = dict(value or {})
        gpu_known = data.get("gpu_telemetry_known", data.get("gpu_telemetry_available", True))
        gpu_status = str(data.get("collector_status", "") or "")
        if gpu_known is None:
            gpu_known = "gpu_unavailable" not in gpu_status
        memory = data.get("memory_pressure")
        if memory is None:
            memory = data.get("memory_percent", 0.0)
        swap = data.get("swap_pressure")
        if swap is None:
            swap = data.get("swap_percent", 0.0)
        gpu_memory = data.get("gpu_memory_pressure")
        if gpu_memory is None:
            gpu_memory = data.get("gpu_memory_percent", 0.0)
        unified_memory = data.get("unified_memory_pressure")
        if unified_memory is None:
            unified_memory = data.get(
                "unified_memory_percent",
                max(
                    _bounded_ratio(memory, name="memory_pressure"),
                    _bounded_ratio(gpu_memory, name="gpu_memory_pressure"),
                ),
            )
        return cls(
            cpu_utilization=data.get("cpu_utilization", data.get("cpu_percent", 0.0)),
            memory_pressure=memory,
            swap_pressure=swap,
            gpu_memory_pressure=gpu_memory,
            unified_memory_pressure=unified_memory,
            gpu_utilization=data.get("gpu_utilization", data.get("gpu_utilization_percent", 0.0)),
            gpu_telemetry_known=bool(gpu_known),
            child_process_count=int(data.get("child_process_count", 0) or 0),
            child_process_limit=int(data.get("child_process_limit", 64) or 64),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "child_process_count": self.child_process_count,
            "child_process_limit": self.child_process_limit,
            "child_process_pressure": round(self.child_process_pressure, 9),
            "cpu_utilization": self.cpu_utilization,
            "gpu_memory_pressure": self.gpu_memory_pressure,
            "unified_memory_pressure": self.unified_memory_pressure,
            "gpu_telemetry_known": self.gpu_telemetry_known,
            "gpu_utilization": self.gpu_utilization,
            "memory_pressure": self.memory_pressure,
            "swap_pressure": self.swap_pressure,
        }


@dataclass(frozen=True, slots=True)
class AdaptivePipelineSignals:
    """Live demand and pressure evidence for one adaptive scheduling decision."""

    ready_queue_depth: Mapping[str, int] = field(default_factory=dict)
    measured_service_time_seconds: Mapping[str, float] = field(default_factory=dict)
    disjoint_codex_scope_count: int = 0
    nested_child_count: int = 0
    validation_capacity: int = 1
    validation_backlog: int = 0
    merge_conflict_rate: float = 0.0
    accepted_patch_throughput_per_hour: float = 0.0
    accepted_patch_target_per_hour: float = 0.0
    resource_pressure: RuntimeResourcePressure | Mapping[str, Any] = field(
        default_factory=RuntimeResourcePressure
    )
    active_worker_counts: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "ready_queue_depth",
            _normalized_count_mapping(self.ready_queue_depth, name="ready_queue_depth"),
        )
        object.__setattr__(
            self,
            "measured_service_time_seconds",
            _normalized_float_mapping(
                self.measured_service_time_seconds,
                name="measured_service_time_seconds",
            ),
        )
        object.__setattr__(
            self,
            "active_worker_counts",
            _normalized_count_mapping(self.active_worker_counts, name="active_worker_counts"),
        )
        _integer(self.disjoint_codex_scope_count, name="disjoint_codex_scope_count", minimum=0)
        _integer(self.nested_child_count, name="nested_child_count", minimum=0)
        _integer(self.validation_capacity, name="validation_capacity", minimum=0)
        _integer(self.validation_backlog, name="validation_backlog", minimum=0)
        for name in (
            "accepted_patch_throughput_per_hour",
            "accepted_patch_target_per_hour",
        ):
            object.__setattr__(
                self,
                name,
                _finite(getattr(self, name), name=name, minimum=0.0),
            )
        object.__setattr__(
            self,
            "merge_conflict_rate",
            _bounded_ratio(self.merge_conflict_rate, name="merge_conflict_rate"),
        )
        pressure = self.resource_pressure
        if not isinstance(pressure, RuntimeResourcePressure):
            pressure = RuntimeResourcePressure.from_mapping(dict(pressure or {}))
        object.__setattr__(self, "resource_pressure", pressure)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "AdaptivePipelineSignals":
        data = dict(value or {})
        return cls(
            ready_queue_depth=dict(data.get("ready_queue_depth") or data.get("queues") or {}),
            measured_service_time_seconds=dict(
                data.get("measured_service_time_seconds") or data.get("service_time_seconds") or {}
            ),
            disjoint_codex_scope_count=int(
                data.get("disjoint_codex_scope_count", data.get("disjoint_scope_count", 0)) or 0
            ),
            nested_child_count=int(
                data.get("nested_child_count", data.get("child_process_count", 0)) or 0
            ),
            validation_capacity=int(data.get("validation_capacity", 1) or 0),
            validation_backlog=int(
                data.get(
                    "validation_backlog",
                    data.get("pending_validation_count", 0),
                )
                or 0
            ),
            merge_conflict_rate=data.get("merge_conflict_rate", data.get("apply_conflict_rate", 0.0)),
            accepted_patch_throughput_per_hour=data.get(
                "accepted_patch_throughput_per_hour",
                data.get("accepted_patches_per_hour", 0.0),
            ),
            accepted_patch_target_per_hour=data.get(
                "accepted_patch_target_per_hour",
                data.get("target_accepted_patches_per_hour", 0.0),
            ),
            resource_pressure=data.get("resource_pressure", data),
            active_worker_counts=dict(data.get("active_worker_counts") or {}),
        )

    def queue_depth_for(self, *names: str) -> int:
        return int(_first_named(self.ready_queue_depth, names, 0) or 0)

    def service_time_for(self, *names: str) -> float:
        return float(_first_named(self.measured_service_time_seconds, names, 1.0) or 1.0)

    def active_count_for(self, *names: str) -> int:
        return int(_first_named(self.active_worker_counts, names, 0) or 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_worker_counts": dict(sorted(self.active_worker_counts.items())),
            "accepted_patch_target_per_hour": self.accepted_patch_target_per_hour,
            "accepted_patch_throughput_per_hour": self.accepted_patch_throughput_per_hour,
            "disjoint_codex_scope_count": self.disjoint_codex_scope_count,
            "measured_service_time_seconds": dict(
                sorted(self.measured_service_time_seconds.items())
            ),
            "merge_conflict_rate": self.merge_conflict_rate,
            "nested_child_count": self.nested_child_count,
            "ready_queue_depth": dict(sorted(self.ready_queue_depth.items())),
            "resource_pressure": self.resource_pressure.to_dict(),
            "validation_capacity": self.validation_capacity,
            "validation_backlog": self.validation_backlog,
        }


@dataclass(frozen=True, slots=True)
class AdaptiveWorkerCounts:
    """Concrete runtime worker counts for every parallel LegalIR lane."""

    hammer_workers: int
    lean_reconstruction_workers: int
    leanstral_workers: int
    legal_ir_family_workers: int
    incremental_validation_workers: int
    snapshot_evaluator_workers: int
    codex_workers: int
    orchestration_workers: int
    trainer_count: int = 1
    overlapping_write_merge_workers: int = 1

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            minimum = 1 if name in {"trainer_count", "overlapping_write_merge_workers"} else 0
            _integer(getattr(self, name), name=name, minimum=minimum)
        if self.trainer_count != 1:
            raise ValueError("adaptive pipeline must preserve one canonical trainer")
        if self.overlapping_write_merge_workers != 1:
            raise ValueError("adaptive pipeline must preserve one overlapping-write merge lane")

    @property
    def total_non_trainer_workers(self) -> int:
        return (
            self.hammer_workers
            + self.lean_reconstruction_workers
            + self.leanstral_workers
            + self.legal_ir_family_workers
            + self.incremental_validation_workers
            + self.snapshot_evaluator_workers
            + self.codex_workers
            + self.orchestration_workers
            + self.overlapping_write_merge_workers
        )

    @property
    def hammer_coordinator_workers(self) -> int:
        """Pipeline-stage name for the bounded Hammer root processes."""

        return self.hammer_workers

    @property
    def leanstral_service_count(self) -> int:
        """Number of persistent Leanstral service generations admitted."""

        return min(1, self.leanstral_workers)

    @property
    def validation_workers(self) -> int:
        """The independently runnable incremental-validation lane size."""

        return self.incremental_validation_workers

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class AdaptivePipelineDecision:
    """Serializable adaptive worker recommendation plus its pressure evidence."""

    counts: AdaptiveWorkerCounts
    target_useful_cpu_range: tuple[float, float]
    useful_cpu_occupancy: float
    reasons: tuple[str, ...]
    signals: AdaptivePipelineSignals
    profile_name: str
    schema_version: str = ADAPTIVE_PIPELINE_PARALLELISM_SCHEMA_VERSION

    def __post_init__(self) -> None:
        low, high = self.target_useful_cpu_range
        _ratio(low, name="target_useful_cpu_range[0]")
        _ratio(high, name="target_useful_cpu_range[1]")
        if low >= high:
            raise ValueError("target useful CPU range must be increasing")
        object.__setattr__(
            self,
            "useful_cpu_occupancy",
            _bounded_ratio(self.useful_cpu_occupancy, name="useful_cpu_occupancy"),
        )
        object.__setattr__(self, "reasons", tuple(sorted(set(self.reasons))) or ("healthy",))

    def to_dict(self) -> dict[str, Any]:
        return {
            "counts": self.counts.to_dict(),
            "profile_name": self.profile_name,
            "reasons": list(self.reasons),
            "schema_version": self.schema_version,
            "signals": self.signals.to_dict(),
            "target_useful_cpu_range": list(self.target_useful_cpu_range),
            "useful_cpu_occupancy": self.useful_cpu_occupancy,
        }


class AdaptivePipelineParallelismController:
    """Choose useful worker counts from live queue, conflict, and pressure signals."""

    def __init__(
        self,
        profile: ParallelismProfile | None = None,
        resource_bounds: GlobalResourceBounds | None = None,
        *,
        target_queue_seconds: float = 30.0,
        min_workers_per_active_lane: int = 1,
    ) -> None:
        self.profile = profile or FIXED_DGX_SPARK_BASELINE
        self.resource_bounds = resource_bounds or GlobalResourceBounds()
        self.target_queue_seconds = _finite(
            target_queue_seconds,
            name="target_queue_seconds",
            minimum=0.001,
        )
        self.min_workers_per_active_lane = _integer(
            min_workers_per_active_lane,
            name="min_workers_per_active_lane",
            minimum=1,
        )

    def _demand_workers(
        self,
        signals: AdaptivePipelineSignals,
        names: Sequence[str],
        *,
        capacity: int,
        queue_depth: int | None = None,
    ) -> int:
        queue_depth = (
            signals.queue_depth_for(*names)
            if queue_depth is None
            else _integer(queue_depth, name="queue_depth", minimum=0)
        )
        if queue_depth <= 0 or capacity <= 0:
            return 0
        service = max(0.001, signals.service_time_for(*names))
        demand = math.ceil(queue_depth * service / self.target_queue_seconds)
        return max(self.min_workers_per_active_lane, min(capacity, queue_depth, demand))

    @staticmethod
    def _apply_cap(count: int, cap: int) -> int:
        return max(0, min(int(count), int(cap)))

    def _pressure_cap(
        self,
        signals: AdaptivePipelineSignals,
        counts: dict[str, int],
    ) -> tuple[int, list[str]]:
        pressure = signals.resource_pressure
        reasons: list[str] = []
        factor = 1.0
        low = self.resource_bounds.useful_cpu_utilization_min
        high = self.resource_bounds.useful_cpu_utilization_max
        soft_high = max(low, high - 0.05)
        if pressure.cpu_utilization >= high:
            factor = min(factor, 0.50)
            reasons.append("cpu_contention")
        elif pressure.cpu_utilization >= soft_high:
            factor = min(factor, 0.75)
            reasons.append("cpu_precontention")
        elif (
            pressure.cpu_utilization < low
            and sum(signals.ready_queue_depth.values()) > 0
        ):
            reasons.append("cpu_under_target_with_ready_work")
        if pressure.memory_pressure >= 0.90:
            factor = min(factor, 0.40)
            reasons.append("ram_contention")
        elif pressure.memory_pressure >= 0.82:
            factor = min(factor, 0.70)
            reasons.append("ram_precontention")
        if pressure.unified_memory_pressure >= 0.90:
            factor = min(factor, 0.40)
            reasons.append("unified_memory_contention")
        elif pressure.unified_memory_pressure >= 0.82:
            factor = min(factor, 0.70)
            reasons.append("unified_memory_precontention")
        if pressure.swap_pressure > 0.0:
            factor = min(factor, 0.50)
            reasons.append("swap_pressure")
        if pressure.gpu_memory_pressure >= 0.90:
            factor = min(factor, 0.50)
            reasons.append("gpu_memory_contention")
        elif pressure.gpu_memory_pressure >= 0.82:
            factor = min(factor, 0.70)
            reasons.append("gpu_memory_precontention")
        if not pressure.gpu_telemetry_known:
            reasons.append("gpu_telemetry_unknown")
        if pressure.child_process_pressure >= 0.90:
            factor = min(factor, 0.50)
            reasons.append("child_process_contention")
        elif pressure.child_process_pressure >= 0.75:
            factor = min(factor, 0.75)
            reasons.append("child_process_precontention")
        if signals.nested_child_count:
            nested_ratio = signals.nested_child_count / max(1, pressure.child_process_limit)
            if nested_ratio >= 0.75:
                factor = min(factor, 0.75)
                reasons.append("nested_child_precontention")
        if signals.merge_conflict_rate >= 0.20:
            factor = min(factor, 0.50)
            reasons.append("merge_conflicts")
        elif signals.merge_conflict_rate >= 0.10:
            factor = min(factor, 0.75)
            reasons.append("merge_conflict_precontention")
        current_total = sum(counts.values())
        pressure_total_cap = max(0, math.floor(current_total * factor))
        child_cap = max(
            0,
            pressure.child_process_limit
            - max(pressure.child_process_count, signals.nested_child_count),
        )
        pressure_total_cap = min(pressure_total_cap, child_cap)
        if not reasons:
            reasons.append("healthy")
        return pressure_total_cap, reasons

    @staticmethod
    def _reduce_to_total_cap(counts: dict[str, int], total_cap: int) -> dict[str, int]:
        priority = (
            "orchestration_workers",
            "codex_workers",
            "snapshot_evaluator_workers",
            "leanstral_workers",
            "incremental_validation_workers",
            "lean_reconstruction_workers",
            "legal_ir_family_workers",
            "hammer_workers",
        )
        result = dict(counts)
        while sum(result.values()) > total_cap and any(result[name] > 0 for name in priority):
            for name in priority:
                if sum(result.values()) <= total_cap:
                    break
                if result[name] > 0:
                    result[name] -= 1
        return result

    def recommend(
        self,
        signals: AdaptivePipelineSignals | Mapping[str, Any],
        *,
        profile: ParallelismProfile | None = None,
    ) -> AdaptivePipelineDecision:
        if isinstance(signals, Mapping):
            signals = AdaptivePipelineSignals.from_mapping(signals)
        selected_profile = profile or self.profile
        policy_reasons: list[str] = []
        validation_cap = max(
            1,
            min(selected_profile.validation_cpu_slots, signals.validation_capacity or 1),
        )
        hammer_lane_capacity = max(1, selected_profile.hammer_lean_cpu_slots)
        hammer = self._demand_workers(
            signals,
            ("hammer", "proof", "solver_execution", "hammer_lean"),
            capacity=min(selected_profile.hammer_workers, hammer_lane_capacity),
        )
        nested_ratio = signals.nested_child_count / max(
            1, signals.resource_pressure.child_process_limit
        )
        if nested_ratio >= 0.75 and hammer > 1:
            hammer = max(1, math.floor(hammer * 0.50))
            policy_reasons.append("nested_solver_children_throttle_hammer")
        elif nested_ratio >= 0.50 and hammer > 1:
            hammer = max(1, math.floor(hammer * 0.75))
            policy_reasons.append("nested_solver_children_limit_hammer")
        lean_reconstruction = self._demand_workers(
            signals,
            ("lean_reconstruction", "reconstruction"),
            capacity=min(
                selected_profile.lean_reconstruction_workers,
                max(1, hammer_lane_capacity - hammer),
            ),
        )
        leanstral = self._demand_workers(
            signals,
            ("leanstral", "leanstral_queue", "leanstral_inference"),
            capacity=min(
                selected_profile.leanstral_workers,
                max(1, hammer_lane_capacity - hammer - lean_reconstruction),
            ),
        )
        if not signals.resource_pressure.gpu_telemetry_known:
            leanstral = min(leanstral, max(1, signals.active_count_for("leanstral_workers", "leanstral")))

        legal_ir = self._demand_workers(
            signals,
            ("evaluator", "legal_ir", "bridge_evaluation", "family"),
            capacity=min(selected_profile.legal_ir_family_workers, validation_cap),
        )
        incremental_validation = self._demand_workers(
            signals,
            ("validation", "incremental_validation"),
            capacity=min(selected_profile.incremental_validation_workers, validation_cap),
            queue_depth=max(
                signals.validation_backlog,
                signals.queue_depth_for("validation", "incremental_validation"),
            ),
        )
        if signals.validation_backlog:
            # Backlog represents accepted generated work waiting on the trust
            # gate, not merely speculative ready work.  Drain at least two
            # queued patches per admitted validator window when capacity is
            # available, while never exceeding the measured validation cap.
            incremental_validation = max(
                incremental_validation,
                min(validation_cap, math.ceil(signals.validation_backlog / 2)),
            )
        snapshot_evaluator = self._demand_workers(
            signals,
            ("snapshot", "snapshot_evaluator", "snapshot_evaluation"),
            capacity=min(selected_profile.snapshot_evaluator_workers, validation_cap),
        )
        codex_capacity = min(
            selected_profile.codex_workers,
            selected_profile.codex_cpu_slots,
            max(1, signals.disjoint_codex_scope_count or selected_profile.codex_workers),
        )
        codex = self._demand_workers(
            signals,
            ("codex", "program_synthesis"),
            capacity=codex_capacity,
        )
        if signals.merge_conflict_rate >= 0.10:
            codex = max(1, math.floor(codex * (0.75 if signals.merge_conflict_rate < 0.20 else 0.50)))
        backlog_high_watermark = max(2, validation_cap * 2)
        if signals.validation_backlog > backlog_high_watermark and codex > 1:
            codex = max(1, math.floor(codex * 0.50))
            policy_reasons.append("validation_backlog_throttles_codex")
        if signals.accepted_patch_target_per_hour > 0.0:
            accepted_ratio = (
                signals.accepted_patch_throughput_per_hour
                / signals.accepted_patch_target_per_hour
            )
            if accepted_ratio < 0.50 and codex > 1:
                codex = max(1, math.floor(codex * 0.75))
                policy_reasons.append("accepted_patch_throughput_below_target")
            elif accepted_ratio >= 1.0:
                policy_reasons.append("accepted_patch_throughput_on_target")
        orchestration = self._demand_workers(
            signals,
            ("orchestration",),
            capacity=selected_profile.orchestration_workers,
        )

        counts = {
            "hammer_workers": hammer,
            "lean_reconstruction_workers": lean_reconstruction,
            "leanstral_workers": leanstral,
            "legal_ir_family_workers": legal_ir,
            "incremental_validation_workers": incremental_validation,
            "snapshot_evaluator_workers": snapshot_evaluator,
            "codex_workers": codex,
            "orchestration_workers": orchestration,
        }
        pressure_total_cap, reasons = self._pressure_cap(signals, counts)
        reasons.extend(policy_reasons)
        counts = self._reduce_to_total_cap(counts, pressure_total_cap)
        counts["hammer_workers"] = self._apply_cap(counts["hammer_workers"], selected_profile.hammer_workers)
        counts["lean_reconstruction_workers"] = self._apply_cap(
            counts["lean_reconstruction_workers"],
            selected_profile.lean_reconstruction_workers,
        )
        counts["leanstral_workers"] = self._apply_cap(
            counts["leanstral_workers"],
            selected_profile.leanstral_workers,
        )
        counts["legal_ir_family_workers"] = self._apply_cap(
            counts["legal_ir_family_workers"],
            min(selected_profile.legal_ir_family_workers, validation_cap),
        )
        counts["incremental_validation_workers"] = self._apply_cap(
            counts["incremental_validation_workers"],
            min(selected_profile.incremental_validation_workers, validation_cap),
        )
        counts["snapshot_evaluator_workers"] = self._apply_cap(
            counts["snapshot_evaluator_workers"],
            min(selected_profile.snapshot_evaluator_workers, validation_cap),
        )
        counts["codex_workers"] = self._apply_cap(counts["codex_workers"], codex_capacity)
        counts["orchestration_workers"] = self._apply_cap(
            counts["orchestration_workers"],
            selected_profile.orchestration_workers,
        )
        hammer_lane_total = (
            counts["hammer_workers"]
            + counts["lean_reconstruction_workers"]
            + counts["leanstral_workers"]
        )
        while hammer_lane_total > hammer_lane_capacity:
            if counts["leanstral_workers"] > 1:
                counts["leanstral_workers"] -= 1
            elif counts["lean_reconstruction_workers"] > 1:
                counts["lean_reconstruction_workers"] -= 1
            else:
                counts["hammer_workers"] = max(1, counts["hammer_workers"] - 1)
            hammer_lane_total = (
                counts["hammer_workers"]
                + counts["lean_reconstruction_workers"]
                + counts["leanstral_workers"]
            )
        if signals.resource_pressure.cpu_utilization > self.resource_bounds.useful_cpu_utilization_max:
            reasons.append("scaled_down_before_contention")
        elif (
            signals.resource_pressure.cpu_utilization
            >= self.resource_bounds.useful_cpu_utilization_max - 0.05
        ):
            reasons.append("scaled_down_before_contention")

        worker_counts = AdaptiveWorkerCounts(**counts)
        return AdaptivePipelineDecision(
            counts=worker_counts,
            target_useful_cpu_range=(
                self.resource_bounds.useful_cpu_utilization_min,
                self.resource_bounds.useful_cpu_utilization_max,
            ),
            useful_cpu_occupancy=signals.resource_pressure.cpu_utilization,
            reasons=tuple(reasons),
            signals=signals,
            profile_name=selected_profile.name,
        )


@dataclass(frozen=True, slots=True)
class BatchSizeMeasurement:
    """Measured resource, kernel, throughput, and trust evidence for one size."""

    batch_size: int
    samples_per_second: float
    peak_memory_bytes: int
    memory_capacity_bytes: int
    kernel_efficiency: float
    quality_metrics: Mapping[str, float] = field(default_factory=dict)
    split_fingerprint: str = ""
    gpu_telemetry_known: bool = True
    recoverable_oom: bool = False
    state_identity_preserved: bool = True
    sample_count: int = 1

    def __post_init__(self) -> None:
        _integer(self.batch_size, name="batch_size", minimum=1)
        _finite(self.samples_per_second, name="samples_per_second", minimum=0.0)
        _integer(self.peak_memory_bytes, name="peak_memory_bytes", minimum=0)
        _integer(self.memory_capacity_bytes, name="memory_capacity_bytes", minimum=0)
        _ratio(self.kernel_efficiency, name="kernel_efficiency")
        _integer(self.sample_count, name="sample_count", minimum=1)
        for name, value in self.quality_metrics.items():
            if not str(name or "").strip():
                raise ValueError("quality metric names must not be empty")
            _finite(value, name=f"quality_metrics[{name}]")

    @classmethod
    def from_observation(
        cls,
        *,
        batch_size: int,
        sample_count: int,
        elapsed_seconds: float,
        peak_memory_bytes: int,
        memory_capacity_bytes: int,
        kernel_active_seconds: float,
        kernel_elapsed_seconds: float,
        quality_metrics: Mapping[str, float] | None = None,
        split_fingerprint: str = "",
        gpu_telemetry_known: bool = True,
        recoverable_oom: bool = False,
        state_identity_preserved: bool = True,
    ) -> "BatchSizeMeasurement":
        """Derive throughput and kernel occupancy from raw timed telemetry."""

        elapsed = _finite(elapsed_seconds, name="elapsed_seconds", minimum=1.0e-12)
        kernel_elapsed = _finite(
            kernel_elapsed_seconds,
            name="kernel_elapsed_seconds",
            minimum=1.0e-12,
        )
        active = _finite(
            kernel_active_seconds,
            name="kernel_active_seconds",
            minimum=0.0,
        )
        samples = _integer(sample_count, name="sample_count", minimum=1)
        return cls(
            batch_size=batch_size,
            samples_per_second=samples / elapsed,
            peak_memory_bytes=peak_memory_bytes,
            memory_capacity_bytes=memory_capacity_bytes,
            kernel_efficiency=min(1.0, active / kernel_elapsed),
            quality_metrics=quality_metrics or {},
            split_fingerprint=split_fingerprint,
            gpu_telemetry_known=gpu_telemetry_known,
            recoverable_oom=recoverable_oom,
            state_identity_preserved=state_identity_preserved,
            sample_count=samples,
        )

    @property
    def memory_headroom_bytes(self) -> int:
        return max(0, self.memory_capacity_bytes - self.peak_memory_bytes)

    @property
    def memory_headroom_fraction(self) -> float:
        if self.memory_capacity_bytes <= 0:
            return 0.0
        return self.memory_headroom_bytes / self.memory_capacity_bytes

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_size": self.batch_size,
            "gpu_telemetry_known": self.gpu_telemetry_known,
            "kernel_efficiency": self.kernel_efficiency,
            "memory_capacity_bytes": self.memory_capacity_bytes,
            "memory_headroom_bytes": self.memory_headroom_bytes,
            "memory_headroom_fraction": self.memory_headroom_fraction,
            "peak_memory_bytes": self.peak_memory_bytes,
            "quality_metrics": {
                str(name): float(value)
                for name, value in sorted(self.quality_metrics.items())
            },
            "recoverable_oom": self.recoverable_oom,
            "sample_count": self.sample_count,
            "samples_per_second": self.samples_per_second,
            "split_fingerprint": self.split_fingerprint,
            "state_identity_preserved": self.state_identity_preserved,
        }


# Compatibility aliases make the evidence object readable in both resource
# telemetry and benchmark call sites.
BatchCandidateMeasurement = BatchSizeMeasurement
BatchResourceMeasurement = BatchSizeMeasurement


@dataclass(frozen=True, slots=True)
class BatchAutotuneConfig:
    """Fail-closed promotion policy for autoencoder minibatch sizes."""

    candidate_batch_sizes: tuple[int, ...] = (8, 16, 32, 64)
    minimum_memory_headroom_fraction: float = 0.08
    minimum_kernel_efficiency: float = 0.50
    minimum_throughput_gain: float = 1.50
    quality_tolerance: float = 0.0
    quality_tolerances: Mapping[str, float] = field(default_factory=dict)
    require_gpu_telemetry: bool = True
    require_split_fingerprint: bool = True
    minimum_sample_count: int = 1

    def __post_init__(self) -> None:
        candidates = tuple(sorted(set(self.candidate_batch_sizes)))
        if not candidates or any(
            isinstance(size, bool) or not isinstance(size, int) or size < 1
            for size in candidates
        ):
            raise ValueError("candidate_batch_sizes must contain positive integers")
        object.__setattr__(self, "candidate_batch_sizes", candidates)
        _ratio(
            self.minimum_memory_headroom_fraction,
            name="minimum_memory_headroom_fraction",
        )
        _ratio(self.minimum_kernel_efficiency, name="minimum_kernel_efficiency")
        _finite(self.minimum_throughput_gain, name="minimum_throughput_gain", minimum=1.0)
        _finite(self.quality_tolerance, name="quality_tolerance", minimum=0.0)
        _integer(self.minimum_sample_count, name="minimum_sample_count", minimum=1)
        for name, value in self.quality_tolerances.items():
            _finite(value, name=f"quality_tolerances[{name}]", minimum=0.0)


DGX_SPARK_BATCH_AUTOTUNE_CONFIG: Final = BatchAutotuneConfig()


@dataclass(frozen=True, slots=True)
class BatchCandidateEvaluation:
    batch_size: int
    eligible: bool
    violations: tuple[str, ...]
    throughput_gain: float
    score: float
    measurement: BatchSizeMeasurement

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_size": self.batch_size,
            "eligible": self.eligible,
            "measurement": self.measurement.to_dict(),
            "score": self.score,
            "throughput_gain": self.throughput_gain,
            "violations": list(self.violations),
        }


@dataclass(frozen=True, slots=True)
class BatchAutotuneDecision:
    """Deterministic selected size and all evidence used to choose it."""

    selected_batch_size: int
    baseline_batch_size: int
    promoted: bool
    evaluations: tuple[BatchCandidateEvaluation, ...]
    schema_version: str = BATCH_SIZE_AUTOTUNER_SCHEMA_VERSION

    @property
    def fallback_batch_sizes(self) -> tuple[int, ...]:
        sizes = {
            evaluation.batch_size
            for evaluation in self.evaluations
            if evaluation.batch_size <= self.selected_batch_size
        }
        sizes.add(1)
        return tuple(sorted(sizes, reverse=True))

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_batch_size": self.baseline_batch_size,
            "evaluations": [evaluation.to_dict() for evaluation in self.evaluations],
            "fallback_batch_sizes": list(self.fallback_batch_sizes),
            "promoted": self.promoted,
            "schema_version": self.schema_version,
            "selected_batch_size": self.selected_batch_size,
        }


def _quality_is_lower_better(name: str) -> bool:
    if name in LOWER_IS_BETTER_QUALITY:
        return True
    lowered = name.lower()
    return any(
        marker in lowered
        for marker in ("loss", "penalty", "error", "cross_entropy", "latency")
    )


class BatchSizeAutotuner:
    """Choose a measured batch size from headroom, occupancy, speed, and quality."""

    def __init__(self, config: BatchAutotuneConfig | None = None) -> None:
        self.config = config or DGX_SPARK_BATCH_AUTOTUNE_CONFIG

    def evaluate(
        self,
        baseline: BatchSizeMeasurement,
        candidate: BatchSizeMeasurement,
    ) -> BatchCandidateEvaluation:
        failures: list[str] = []
        config = self.config
        if candidate.batch_size not in config.candidate_batch_sizes:
            failures.append("batch_size_not_configured")
        if candidate.recoverable_oom:
            failures.append("recoverable_oom")
        if not candidate.state_identity_preserved:
            failures.append("state_identity_not_preserved")
        if config.require_gpu_telemetry and not candidate.gpu_telemetry_known:
            failures.append("gpu_telemetry_unknown")
        if candidate.memory_capacity_bytes <= 0:
            failures.append("memory_capacity_unknown")
        elif (
            candidate.memory_headroom_fraction + 1.0e-12
            < config.minimum_memory_headroom_fraction
        ):
            failures.append("insufficient_memory_headroom")
        if candidate.peak_memory_bytes > candidate.memory_capacity_bytes:
            failures.append("memory_capacity_exceeded")
        if candidate.kernel_efficiency + 1.0e-12 < config.minimum_kernel_efficiency:
            failures.append("kernel_efficiency_below_minimum")
        if candidate.sample_count < config.minimum_sample_count:
            failures.append("insufficient_sample_count")
        if config.require_split_fingerprint:
            if not baseline.split_fingerprint or not candidate.split_fingerprint:
                failures.append("split_fingerprint_missing")
            elif candidate.split_fingerprint != baseline.split_fingerprint:
                failures.append("split_isolation_mismatch")

        baseline_names = set(baseline.quality_metrics)
        candidate_names = set(candidate.quality_metrics)
        for name in sorted(baseline_names - candidate_names):
            failures.append(f"quality_metric_missing:{name}")
        for name in sorted(baseline_names & candidate_names):
            base = float(baseline.quality_metrics[name])
            trial = float(candidate.quality_metrics[name])
            tolerance = float(config.quality_tolerances.get(name, config.quality_tolerance))
            if _quality_is_lower_better(name):
                regressed = trial > base + tolerance + 1.0e-12
            else:
                regressed = trial + tolerance + 1.0e-12 < base
            if regressed:
                failures.append(f"quality_regression:{name}")

        throughput_gain = (
            candidate.samples_per_second / baseline.samples_per_second
            if baseline.samples_per_second > 0.0
            else 0.0
        )
        if throughput_gain + 1.0e-12 < config.minimum_throughput_gain:
            failures.append("throughput_gain_below_minimum")
        # Throughput remains the objective; kernel efficiency resolves close
        # candidates and prevents launch-heavy measurements from looking good
        # solely because of noisy elapsed time.
        score = candidate.samples_per_second * (0.5 + 0.5 * candidate.kernel_efficiency)
        return BatchCandidateEvaluation(
            batch_size=candidate.batch_size,
            eligible=not failures,
            violations=tuple(sorted(set(failures))),
            throughput_gain=throughput_gain,
            score=score,
            measurement=candidate,
        )

    def tune(
        self,
        baseline: BatchSizeMeasurement,
        candidates: Sequence[BatchSizeMeasurement],
    ) -> BatchAutotuneDecision:
        if baseline.batch_size != 1:
            raise ValueError("batch autotuning requires a matched batch-one baseline")
        sizes = [candidate.batch_size for candidate in candidates]
        if len(sizes) != len(set(sizes)):
            raise ValueError("candidate batch sizes must be unique")
        evaluations = tuple(
            self.evaluate(baseline, candidate)
            for candidate in sorted(candidates, key=lambda item: item.batch_size)
        )
        eligible = [evaluation for evaluation in evaluations if evaluation.eligible]
        if not eligible:
            selected = baseline.batch_size
            promoted = False
        else:
            best = max(
                eligible,
                key=lambda item: (
                    item.score,
                    item.measurement.samples_per_second,
                    item.measurement.kernel_efficiency,
                    item.batch_size,
                ),
            )
            selected = best.batch_size
            promoted = selected != baseline.batch_size
        return BatchAutotuneDecision(
            selected_batch_size=selected,
            baseline_batch_size=baseline.batch_size,
            promoted=promoted,
            evaluations=evaluations,
        )

    def choose_batch_size(
        self,
        *,
        memory_capacity_bytes: int,
        memory_used_bytes: int,
        fixed_memory_bytes: int = 0,
        bytes_per_sample: int,
        kernel_efficiency_by_batch: Mapping[int, float],
    ) -> int:
        """Conservatively choose from live headroom when benchmark rows are absent.

        This admission helper never extrapolates past the configured candidate
        set.  Benchmark-based :meth:`tune` remains the promotion authority.
        """

        capacity = _integer(memory_capacity_bytes, name="memory_capacity_bytes", minimum=1)
        used = _integer(memory_used_bytes, name="memory_used_bytes", minimum=0)
        fixed = _integer(fixed_memory_bytes, name="fixed_memory_bytes", minimum=0)
        per_sample = _integer(bytes_per_sample, name="bytes_per_sample", minimum=1)
        usable = max(
            0,
            int(capacity * (1.0 - self.config.minimum_memory_headroom_fraction))
            - used
            - fixed,
        )
        admitted = [
            size
            for size in self.config.candidate_batch_sizes
            if size * per_sample <= usable
            and float(kernel_efficiency_by_batch.get(size, 0.0))
            >= self.config.minimum_kernel_efficiency
        ]
        return max(admitted, default=1)


ResourceSafeBatchAutotuner = BatchSizeAutotuner
BatchAutotuner = BatchSizeAutotuner
BatchTuningConfig = BatchAutotuneConfig
BatchTuningResult = BatchAutotuneDecision


def autotune_batch_size(
    baseline: BatchSizeMeasurement,
    candidates: Sequence[BatchSizeMeasurement],
    config: BatchAutotuneConfig | None = None,
) -> BatchAutotuneDecision:
    return BatchSizeAutotuner(config).tune(baseline, candidates)


class ParallelismAutotuner:
    """Select the fastest trustworthy measured DGX Spark profile."""

    def __init__(
        self,
        resource_bounds: GlobalResourceBounds | None = None,
        trust_bounds: TrustBounds | None = None,
    ) -> None:
        self.resource_bounds = resource_bounds or GlobalResourceBounds()
        self.trust_bounds = trust_bounds or TrustBounds()

    def evaluate(self, baseline: BenchmarkTrial, candidate: BenchmarkTrial) -> CandidateEvaluation:
        base, trial = baseline.metrics, candidate.metrics
        failures = self.resource_bounds.profile_violations(candidate.profile)
        bounds, trust = self.resource_bounds, self.trust_bounds

        cpu = trial.cpu_utilization_average
        if cpu < bounds.useful_cpu_utilization_min:
            failures.append(f"cpu_utilization_below_useful_min:{cpu:.6f}")
        if cpu > bounds.useful_cpu_utilization_max:
            failures.append(f"cpu_utilization_above_useful_max:{cpu:.6f}")
        if trial.memory_percent_peak > bounds.max_memory_percent:
            failures.append("memory_percent_peak_exceeded")
        if trial.swap_percent_peak > bounds.max_swap_percent:
            failures.append("swap_percent_peak_exceeded")
        if trial.gpu_memory_percent_peak > bounds.max_gpu_memory_percent:
            failures.append("gpu_memory_percent_peak_exceeded")
        if not trial.gpu_telemetry_known:
            failures.append("gpu_telemetry_unknown")
        if trial.memory_percent_peak > 100.0 or trial.swap_percent_peak > 100.0:
            failures.append("invalid_host_resource_percentage")
        if trial.child_process_count_peak > bounds.max_child_processes:
            failures.append("child_process_count_peak_exceeded")
        if trial.queue_lag_p95_seconds > bounds.max_queue_lag_p95_seconds:
            failures.append("queue_lag_p95_exceeded")
        if trial.cycle_seconds > bounds.target_cycle_seconds:
            failures.append("cycle_target_not_met")
        if trial.transient_failure_rate > trust.max_transient_failure_rate:
            failures.append("transient_failure_rate_exceeded")
        if trial.sample_count < trust.minimum_sample_count:
            failures.append("insufficient_benchmark_samples")

        throughput_floor = 1.0 - trust.max_relative_throughput_regression
        for name in (
            "cold_cache_throughput_per_hour",
            "warm_cache_throughput_per_hour",
            "proof_throughput_per_hour",
            "reconstruction_throughput_per_hour",
        ):
            if getattr(trial, name) + 1e-12 < getattr(base, name) * throughput_floor:
                failures.append(f"throughput_regression:{name}")
        if trial.queue_lag_p95_seconds > base.queue_lag_p95_seconds * (
            1.0 + trust.max_latency_regression
        ):
            failures.append("queue_lag_regression")

        for name in trust.required_quality_metrics:
            if name not in base.quality_metrics:
                failures.append(f"baseline_quality_metric_missing:{name}")
                continue
            if name not in trial.quality_metrics:
                failures.append(f"candidate_quality_metric_missing:{name}")
                continue
            baseline_value = base.quality_metrics[name]
            candidate_value = trial.quality_metrics[name]
            allowance = trust.max_quality_regression
            if name in LOWER_IS_BETTER_QUALITY:
                if candidate_value > baseline_value + allowance:
                    failures.append(f"quality_regression:{name}")
            elif candidate_value < baseline_value - allowance:
                failures.append(f"quality_regression:{name}")

        proof_base = base.quality_metrics.get("hammer_proof_success_rate", 0.0)
        proof_trial = trial.quality_metrics.get("hammer_proof_success_rate", 0.0)
        if proof_trial < proof_base - trust.max_proof_rate_regression:
            failures.append("proof_success_rate_regression")
        reconstruction_base = base.quality_metrics.get(
            "hammer_reconstruction_success_rate", 0.0
        )
        reconstruction_trial = trial.quality_metrics.get(
            "hammer_reconstruction_success_rate", 0.0
        )
        if reconstruction_trial < reconstruction_base - trust.max_reconstruction_rate_regression:
            failures.append("reconstruction_success_rate_regression")

        quality_improvements: list[float] = []
        for name in trust.required_quality_metrics:
            if name not in base.quality_metrics or name not in trial.quality_metrics:
                continue
            if name in LOWER_IS_BETTER_QUALITY:
                quality_improvements.append(
                    base.quality_metrics[name] - trial.quality_metrics[name]
                )
            else:
                quality_improvements.append(
                    trial.quality_metrics[name] - base.quality_metrics[name]
                )

        common_phases = sorted(set(base.phase_latency) & set(trial.phase_latency))
        tail_delta = _mean(
            [
                _relative(
                    base.phase_latency[name].p95_seconds,
                    trial.phase_latency[name].p95_seconds,
                )
                for name in common_phases
            ]
        )
        deltas = {
            "cold_cache_throughput": _relative(
                trial.cold_cache_throughput_per_hour,
                base.cold_cache_throughput_per_hour,
            ),
            "warm_cache_throughput": _relative(
                trial.warm_cache_throughput_per_hour,
                base.warm_cache_throughput_per_hour,
            ),
            "proof_throughput": _relative(trial.proof_throughput_per_hour, base.proof_throughput_per_hour),
            "reconstruction_throughput": _relative(
                trial.reconstruction_throughput_per_hour,
                base.reconstruction_throughput_per_hour,
            ),
            "accepted_patches_per_hour": _relative(
                trial.codex_accepted_patches_per_hour,
                base.codex_accepted_patches_per_hour,
            ),
            "cycle_time_improvement": _relative(base.cycle_seconds, trial.cycle_seconds),
            "queue_tail_improvement": _relative(base.queue_lag_p95_seconds, trial.queue_lag_p95_seconds),
            "phase_tail_improvement": tail_delta,
            "leanstral_batch_efficiency": trial.leanstral_batch_efficiency - base.leanstral_batch_efficiency,
            "trainer_duty_cycle": trial.trainer_duty_cycle - base.trainer_duty_cycle,
            "quality_improvement": _mean(quality_improvements),
        }
        # End-to-end work dominates; CPU proximity contributes only 3% and
        # cannot compensate for a failed gate.
        utilization_midpoint = (bounds.useful_cpu_utilization_min + bounds.useful_cpu_utilization_max) / 2.0
        utilization_signal = 1.0 - min(1.0, abs(cpu - utilization_midpoint) / 0.25)
        score = (
            0.13 * deltas["cold_cache_throughput"]
            + 0.15 * deltas["warm_cache_throughput"]
            + 0.10 * deltas["proof_throughput"]
            + 0.10 * deltas["reconstruction_throughput"]
            + 0.13 * deltas["accepted_patches_per_hour"]
            + 0.13 * deltas["cycle_time_improvement"]
            + 0.08 * deltas["queue_tail_improvement"]
            + 0.08 * deltas["phase_tail_improvement"]
            + 0.03 * deltas["leanstral_batch_efficiency"]
            + 0.02 * deltas["trainer_duty_cycle"]
            + 0.03 * deltas["quality_improvement"]
            + 0.02 * utilization_signal
        )
        return CandidateEvaluation(
            profile_name=candidate.profile.name,
            eligible=not failures,
            score=score,
            violations=tuple(sorted(set(failures))),
            deltas=deltas,
            trial_evidence_digest=canonical_digest(candidate.to_dict()),
        )

    def tune(self, baseline: BenchmarkTrial, candidates: Sequence[BenchmarkTrial]) -> AutotuneResult:
        if baseline.profile.name != "fixed_baseline":
            raise ValueError("baseline profile must be named 'fixed_baseline'")
        baseline_profile_failures = self.resource_bounds.profile_violations(baseline.profile)
        if baseline_profile_failures:
            raise ValueError(
                "fixed baseline violates configured global resources: "
                + ", ".join(baseline_profile_failures)
            )
        missing_baseline_quality = sorted(
            set(self.trust_bounds.required_quality_metrics)
            - set(baseline.metrics.quality_metrics)
        )
        if missing_baseline_quality:
            raise ValueError(
                "fixed baseline is missing required quality evidence: "
                + ", ".join(missing_baseline_quality)
            )
        if baseline.metrics.sample_count < self.trust_bounds.minimum_sample_count:
            raise ValueError("fixed baseline has insufficient benchmark samples")
        if not candidates:
            raise ValueError("at least one measured candidate is required")
        names = [candidate.profile.name for candidate in candidates]
        if len(names) != len(set(names)) or "fixed_baseline" in names:
            raise ValueError("candidate profile names must be unique and cannot reuse fixed_baseline")
        evaluated = [(candidate, self.evaluate(baseline, candidate)) for candidate in candidates]
        eligible = [(candidate, result) for candidate, result in evaluated if result.eligible and result.score > 0.0]
        if eligible:
            # Canonical name tie-break makes output independent of input order.
            selected, _ = min(eligible, key=lambda pair: (-pair[1].score, pair[0].profile.name))
            promoted = True
        else:
            selected, promoted = baseline, False
        evaluations = tuple(result for _, result in sorted(evaluated, key=lambda pair: pair[0].profile.name))
        return AutotuneResult(
            baseline=baseline,
            selected=selected,
            promoted=promoted,
            evaluations=evaluations,
            resource_bounds=self.resource_bounds,
            trust_bounds=self.trust_bounds,
        )


def autotune_parallelism(
    baseline: BenchmarkTrial,
    candidates: Sequence[BenchmarkTrial],
    *,
    resource_bounds: GlobalResourceBounds | None = None,
    trust_bounds: TrustBounds | None = None,
) -> AutotuneResult:
    return ParallelismAutotuner(resource_bounds, trust_bounds).tune(baseline, candidates)


def write_reproducible_profile(path: str | os.PathLike[str], result: AutotuneResult) -> Path:
    """Atomically write canonical profile JSON; identical input yields identical bytes."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_json(result.production_profile()) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return destination


__all__ = [
    "ADAPTIVE_PIPELINE_PARALLELISM_SCHEMA_VERSION",
    "BATCH_SIZE_AUTOTUNER_SCHEMA_VERSION", "DGX_SPARK_BATCH_AUTOTUNE_CONFIG",
    "DGX_SPARK_PROFILE_SCHEMA_VERSION", "FIXED_DGX_SPARK_BASELINE",
    "DGX_SPARK_INITIAL_PIPELINE_PROFILE", "DGX_SPARK_INITIAL_STAGE_PROFILE",
    "HIGHER_IS_BETTER_QUALITY", "LOWER_IS_BETTER_QUALITY",
    "PARALLELISM_AUTOTUNER_SCHEMA_VERSION", "PIPELINE_BENCHMARK_SCHEMA_VERSION",
    "AdaptivePipelineDecision", "AdaptivePipelineParallelismController",
    "AdaptivePipelineSignals", "AdaptiveWorkerCounts", "AutotuneResult",
    "BatchAutotuneConfig", "BatchAutotuneDecision", "BatchCandidateEvaluation",
    "BatchAutotuner", "BatchTuningConfig", "BatchTuningResult",
    "BatchCandidateMeasurement", "BatchResourceMeasurement", "BatchSizeAutotuner",
    "BatchSizeMeasurement", "ResourceSafeBatchAutotuner", "autotune_batch_size",
    "BenchmarkTrial", "CandidateEvaluation", "GlobalResourceBounds",
    "ParallelismAutotuner", "ParallelismProfile", "PhaseLatency",
    "PipelineBenchmarkMetrics", "TrustBounds", "autotune_parallelism",
    "RuntimeResourcePressure", "canonical_digest", "write_reproducible_profile",
]
