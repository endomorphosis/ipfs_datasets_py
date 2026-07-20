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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final, Mapping, Sequence


PARALLELISM_AUTOTUNER_SCHEMA_VERSION: Final = "legal-ir-parallelism-autotuner-v1"
PIPELINE_BENCHMARK_SCHEMA_VERSION: Final = "legal-ir-optimizer-pipeline-benchmark-v1"
DGX_SPARK_PROFILE_SCHEMA_VERSION: Final = "legal-ir-dgx-spark-production-profile-v1"

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
        ):
            _integer(getattr(self, field_name), name=field_name, minimum=1)
        if self.leanstral_batch_min > self.leanstral_batch_max:
            raise ValueError("leanstral_batch_min cannot exceed leanstral_batch_max")

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


@dataclass(frozen=True, slots=True)
class GlobalResourceBounds:
    """DGX Spark host limits and useful-utilization operating envelope."""

    total_cpu_slots: int = 20
    total_memory_mb: int = 128 * 1024
    max_profile_memory_fraction: float = 0.80
    useful_cpu_utilization_min: float = 0.75
    useful_cpu_utilization_max: float = 0.90
    max_memory_percent: float = 90.0
    max_swap_percent: float = 1.0
    max_gpu_memory_percent: float = 92.0
    max_child_processes: int = 64
    max_leanstral_workers: int = 4
    max_leanstral_batch_size: int = 16
    target_cycle_seconds: float = 400.0
    max_queue_lag_p95_seconds: float = 120.0

    def __post_init__(self) -> None:
        _integer(self.total_cpu_slots, name="total_cpu_slots", minimum=1)
        _integer(self.total_memory_mb, name="total_memory_mb", minimum=1)
        _integer(self.max_child_processes, name="max_child_processes", minimum=1)
        _integer(self.max_leanstral_workers, name="max_leanstral_workers", minimum=1)
        _integer(self.max_leanstral_batch_size, name="max_leanstral_batch_size", minimum=1)
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
    "DGX_SPARK_PROFILE_SCHEMA_VERSION", "FIXED_DGX_SPARK_BASELINE",
    "HIGHER_IS_BETTER_QUALITY", "LOWER_IS_BETTER_QUALITY",
    "PARALLELISM_AUTOTUNER_SCHEMA_VERSION", "PIPELINE_BENCHMARK_SCHEMA_VERSION",
    "AutotuneResult", "BenchmarkTrial", "CandidateEvaluation", "GlobalResourceBounds",
    "ParallelismAutotuner", "ParallelismProfile", "PhaseLatency",
    "PipelineBenchmarkMetrics", "TrustBounds", "autotune_parallelism",
    "canonical_digest", "write_reproducible_profile",
]
