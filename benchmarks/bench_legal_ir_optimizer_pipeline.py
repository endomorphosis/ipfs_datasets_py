#!/usr/bin/env python3
"""Benchmark the complete parallel Hammer/Leanstral/LegalIR optimizer pipeline.

This harness aggregates source-free daemon summaries rather than replacing the
real pipeline with a microbenchmark.  Run the daemon once with an empty/new
cache (``benchmark_cache_state=cold``) and again against the retained immutable
cache (``warm``), then pass both JSON summaries with ``--input``.  Multiple
profiles can be supplied in one invocation; each summary must contain either a
``benchmark_profile`` object or a top-level ``profile`` object.

The report covers throughput, phase p50/p95, trainer duty cycle, proof and Lean
reconstruction throughput, Leanstral batch efficiency, host/GPU/memory/swap,
queue lag, accepted Codex patches per hour, transient failures, and the rollout
quality metrics.  Promotion-grade raw summaries additionally bind matched
sample/revision/model/hardware identities, explicit cycle and sample counts,
state-to-accepted-patch lag, CUDA service activity, artifact bounds, ablations,
and every per-family quality guardrail.  Missing evidence remains visible and
ineligible.  ``--dry-run`` produces deterministic representative evidence
without launching models or provers and can never qualify as execution proof.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.parallelism_autotuner import (  # noqa: E402
    HIGHER_IS_BETTER_QUALITY,
    LOWER_IS_BETTER_QUALITY,
    PIPELINE_BENCHMARK_SCHEMA_VERSION,
    BenchmarkTrial,
    ParallelismProfile,
    PhaseLatency,
    PipelineBenchmarkMetrics,
    canonical_digest,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_family_evaluator import (  # noqa: E402
    LEGAL_IR_EVALUATION_FAMILIES,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.runtime_telemetry import (  # noqa: E402
    RUNTIME_PHASES,
)


REQUIRED_MEASUREMENTS = (
    "cold_cache_throughput_per_hour",
    "warm_cache_throughput_per_hour",
    "phase_latency_p50_p95",
    "trainer_duty_cycle",
    "proof_throughput_per_hour",
    "reconstruction_throughput_per_hour",
    "leanstral_batch_efficiency",
    "cpu_gpu_utilization",
    "memory_and_swap",
    "queue_lag",
    "codex_accepted_patches_per_hour",
    "quality_metrics",
)

THROUGHPUT_REMEDIATION_SCHEMA_VERSION = (
    "legal-ir-throughput-remediation-benchmark-v1"
)
MINIMUM_WARM_CYCLES_PER_HOUR_RATIO = 1.8
MINIMUM_SAMPLES_PER_SECOND_RATIO = 1.5

# Every family is compared independently.  A mean across families can hide a
# serious regression in a rare logic representation, so it is deliberately
# not part of this contract.
PER_FAMILY_QUALITY_METRICS: Mapping[str, str] = {
    "ir_cross_entropy_loss": "lower",
    "ir_cosine_similarity": "higher",
    "autoencoder_cross_entropy_loss": "lower",
    "autoencoder_cosine_similarity": "higher",
    "semantic_equivalence": "higher",
    "proof_success_rate": "higher",
    "reconstruction_success_rate": "higher",
    "provenance": "higher",
    "round_trip": "higher",
    "uncertainty": "lower",
    "holdout": "higher",
    "source_copy_penalty": "lower",
}

_DRY_SAMPLE_IDS = tuple(f"legal-ir-remediation-{index:02d}" for index in range(1, 129))

QUALITY_ALIASES: Mapping[str, tuple[str, ...]] = {
    "compiler_ir_cosine": (
        "compiler_ir_cosine", "latest_compiler_ir_cosine", "best_validation_ir_cosine"
    ),
    "structural_validity": (
        "structural_validity", "latest_structural_validity", "symbolic_validity_success_rate"
    ),
    "symbolic_validity_success_rate": (
        "symbolic_validity_success_rate", "latest_symbolic_validity_success_rate",
        "structural_validity",
    ),
    "hammer_proof_success_rate": (
        "hammer_proof_success_rate", "latest_hammer_proof_success_rate"
    ),
    "hammer_reconstruction_success_rate": (
        "hammer_reconstruction_success_rate", "reconstruction_success_rate",
        "latest_hammer_reconstruction_success_rate",
    ),
    "source_copy_penalty": (
        "source_copy_penalty", "latest_compiler_ir_source_copy_reward_hack_penalty",
        "source_copy_reward_hack_penalty",
    ),
}


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _ratio(value: Any) -> float | None:
    result = _finite(value)
    if result is None:
        return None
    return max(0.0, min(1.0, result / 100.0 if result > 1.0 else result))


def _percentile(values: Sequence[float], percentile: float) -> float:
    """Linear-interpolated percentile, matching common telemetry backends."""

    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _nested_mappings(value: Any, *, max_depth: int = 5) -> Iterable[Mapping[str, Any]]:
    if max_depth < 0:
        return
    if isinstance(value, Mapping):
        yield value
        for item in value.values():
            yield from _nested_mappings(item, max_depth=max_depth - 1)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            yield from _nested_mappings(item, max_depth=max_depth - 1)


def _first_number(summary: Mapping[str, Any], names: Sequence[str]) -> float | None:
    for block in _nested_mappings(summary):
        for name in names:
            value = _finite(block.get(name))
            if value is not None:
                return value
    return None


def _runtime_block(summary: Mapping[str, Any]) -> Mapping[str, Any]:
    for name in ("runtime_telemetry", "latest_runtime_phase_telemetry"):
        block = summary.get(name)
        if isinstance(block, Mapping):
            return block
    return {}


def _spans(summary: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    spans = _runtime_block(summary).get("spans", ())
    return [item for item in spans if isinstance(item, Mapping)] if isinstance(spans, Sequence) else []


def _elapsed(summary: Mapping[str, Any]) -> float:
    direct = _first_number(summary, ("benchmark_elapsed_seconds", "latest_cycle_seconds", "elapsed_seconds"))
    if direct is not None and direct > 0.0:
        return direct
    cycles = [
        float(item.get("duration_seconds", 0.0))
        for item in _spans(summary)
        if item.get("phase") == "cycle" and _finite(item.get("duration_seconds")) is not None
    ]
    return sum(cycles) if cycles else 0.0


def _completed_units(summary: Mapping[str, Any]) -> float:
    explicit = _first_number(
        summary,
        ("benchmark_completed_units", "latest_compiler_ir_validation_sample_count", "sample_count"),
    )
    if explicit is not None:
        return max(0.0, explicit)
    cycles = _first_number(summary, ("cycles",))
    return max(0.0, cycles or 0.0)


def _cache_state(summary: Mapping[str, Any]) -> str:
    state = str(summary.get("benchmark_cache_state") or summary.get("cache_state") or "").lower()
    if state not in {"cold", "warm"}:
        raise ValueError("each raw summary must declare benchmark_cache_state as cold or warm")
    return state


def _quality(summary: Mapping[str, Any]) -> dict[str, float]:
    supplied = summary.get("benchmark_quality_metrics") or summary.get("quality_metrics")
    supplied = supplied if isinstance(supplied, Mapping) else {}
    result: dict[str, float] = {}
    for canonical, aliases in QUALITY_ALIASES.items():
        value = _first_number(supplied, aliases) if supplied else None
        if value is None:
            value = _first_number(summary, aliases)
        if value is not None:
            result[canonical] = value
    missing = sorted(set(QUALITY_ALIASES) - set(result))
    if missing:
        raise ValueError(f"summary is missing required quality evidence: {', '.join(missing)}")
    return result


def _leanstral_batch_counts(summary: Mapping[str, Any]) -> tuple[float, float, float]:
    """Return dispatched items, formed batches, and summed configured capacity."""

    for block in _nested_mappings(summary):
        dispatched = _finite(block.get("dispatched_item_count"))
        formed = _finite(block.get("formed_batch_count"))
        if dispatched is not None and formed is not None:
            sizes = block.get("batch_sizes")
            capacity = 0.0
            if isinstance(sizes, Sequence) and not isinstance(sizes, (str, bytes, bytearray)):
                numeric = [float(item) for item in sizes if _finite(item) is not None]
                maximum = _first_number(summary, ("batch_size", "leanstral_batch_max"))
                capacity = len(numeric) * (maximum or (max(numeric) if numeric else 0.0))
            return max(0.0, dispatched), max(0.0, formed), max(0.0, capacity)
    return 0.0, 0.0, 0.0


def _resource_records(summary: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    for span in _spans(summary):
        for name in ("resources_start", "resources_end"):
            value = span.get(name)
            if isinstance(value, Mapping):
                result.append(value)
    latest = _runtime_block(summary).get("resources")
    if isinstance(latest, Mapping) and isinstance(latest.get("latest"), Mapping):
        result.append(latest["latest"])
    return result


def aggregate_pipeline_summaries(
    summaries: Sequence[Mapping[str, Any]], profile: ParallelismProfile
) -> BenchmarkTrial:
    """Aggregate repeated cold/warm daemon summaries into one complete trial."""

    if not summaries:
        raise ValueError("at least one daemon summary is required")
    by_cache: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for summary in summaries:
        by_cache[_cache_state(summary)].append(summary)
    if not by_cache["cold"] or not by_cache["warm"]:
        raise ValueError("each profile requires at least one cold and one warm cache run")

    throughput: dict[str, float] = {}
    cache_rates: dict[str, float] = {}
    for state in ("cold", "warm"):
        elapsed = sum(_elapsed(item) for item in by_cache[state])
        if elapsed <= 0.0:
            raise ValueError(f"{state} summaries have no positive elapsed time")
        throughput[state] = sum(_completed_units(item) for item in by_cache[state]) / elapsed * 3600.0
        hit_values = [
            value for item in by_cache[state]
            for value in [_ratio(_runtime_block(item).get("cache_hit_rate"))]
            if value is not None
        ]
        cache_rates[state] = statistics.fmean(hit_values) if hit_values else 0.0

    phase_durations: dict[str, list[float]] = defaultdict(list)
    resources: list[Mapping[str, Any]] = []
    queue_lags: list[float] = []
    trainer_seconds = proof_units = reconstruction_units = total_elapsed = 0.0
    dispatched = batches = batch_capacity = accepted_patches = 0.0
    quality_samples: dict[str, list[float]] = defaultdict(list)
    transient_rates: list[float] = []
    cycle_samples: list[float] = []
    sample_count = 0

    for summary in summaries:
        elapsed = _elapsed(summary)
        total_elapsed += elapsed
        sample_count += int(_completed_units(summary))
        cycle = _first_number(summary, ("latest_cycle_seconds", "benchmark_elapsed_seconds"))
        if cycle is not None:
            cycle_samples.append(cycle)
        for name, value in _quality(summary).items():
            quality_samples[name].append(value)
        transient = _first_number(
            summary,
            (
                "program_synthesis_transient_failure_rate",
                "codex_transient_failure_rate",
                "transient_failure_rate",
            ),
        )
        if transient is not None:
            transient_rates.append(max(0.0, min(1.0, transient)))
        accepted_patches += max(
            0.0,
            _first_number(
                summary, ("codex_main_apply_count", "codex_accepted_patch_count")
            )
            or 0.0,
        )
        item_count, batch_count, capacity = _leanstral_batch_counts(summary)
        dispatched += item_count
        batches += batch_count
        batch_capacity += capacity or batch_count * profile.leanstral_batch_max
        resources.extend(_resource_records(summary))
        for span in _spans(summary):
            phase = str(span.get("phase") or "")
            duration = _finite(span.get("duration_seconds"))
            units = _finite(span.get("unit_count")) or 0.0
            if not phase or duration is None:
                continue
            if phase != "cycle":
                phase_durations[phase].append(duration)
            if phase == "projection_training":
                trainer_seconds += duration
            elif phase == "solver_execution":
                proof_units += units
            elif phase == "lean_reconstruction":
                reconstruction_units += units
            if phase in {"leanstral_queue", "codex_queue_wait"}:
                queue_lags.append(duration)

    if total_elapsed <= 0.0:
        raise ValueError("summaries have no positive total elapsed time")
    phase_latency = {
        name: PhaseLatency(
            p50_seconds=round(_percentile(values, 0.50), 9),
            p95_seconds=round(_percentile(values, 0.95), 9),
        )
        for name, values in sorted(phase_durations.items())
    }
    if not phase_latency:
        raise ValueError("summaries contain no runtime phase spans")

    def resource_values(name: str) -> list[float]:
        return [float(item[name]) for item in resources if _finite(item.get(name)) is not None]

    cpu = [_ratio(value) for value in resource_values("cpu_percent")]
    gpu = [_ratio(value) for value in resource_values("gpu_utilization_percent")]
    cpu_values = [value for value in cpu if value is not None]
    gpu_values = [value for value in gpu if value is not None]
    gpu_telemetry_known = any(
        item.get("gpu_telemetry_available") is True
        or _finite(item.get("gpu_utilization_percent")) is not None
        or _finite(item.get("gpu_memory_percent")) is not None
        or _finite(item.get("gpu_memory_used_bytes")) is not None
        or (_finite(item.get("gpu_device_count")) or 0.0) > 0.0
        for item in resources
    )
    memory_percent = resource_values("memory_percent")
    memory_bytes = resource_values("memory_used_bytes")
    swap_percent = resource_values("swap_percent")
    swap_bytes = resource_values("swap_used_bytes")
    gpu_memory_percent = resource_values("gpu_memory_percent")
    children = resource_values("child_process_count")
    queue_depths = resource_values("queue_depth")
    # A strong warm-cache result must never mask a cold-run trust regression.
    # Keep the least favorable observation across all repetitions.
    quality = {
        name: (
            max(values)
            if name in LOWER_IS_BETTER_QUALITY
            else min(values)
            if name in HIGHER_IS_BETTER_QUALITY
            else statistics.fmean(values)
        )
        for name, values in sorted(quality_samples.items())
    }

    metrics = PipelineBenchmarkMetrics(
        cold_cache_throughput_per_hour=throughput["cold"],
        warm_cache_throughput_per_hour=throughput["warm"],
        phase_latency=phase_latency,
        trainer_duty_cycle=min(1.0, trainer_seconds / total_elapsed),
        proof_throughput_per_hour=proof_units / total_elapsed * 3600.0,
        reconstruction_throughput_per_hour=reconstruction_units / total_elapsed * 3600.0,
        leanstral_batch_efficiency=min(1.0, dispatched / batch_capacity) if batch_capacity else 0.0,
        leanstral_average_batch_size=dispatched / batches if batches else 0.0,
        cpu_utilization_average=statistics.fmean(cpu_values) if cpu_values else 0.0,
        cpu_utilization_peak=max(cpu_values, default=0.0),
        gpu_utilization_average=statistics.fmean(gpu_values) if gpu_values else 0.0,
        gpu_utilization_peak=max(gpu_values, default=0.0),
        gpu_memory_percent_peak=max(gpu_memory_percent, default=0.0),
        gpu_telemetry_known=gpu_telemetry_known,
        memory_percent_peak=max(memory_percent, default=0.0),
        memory_used_bytes_peak=int(max(memory_bytes, default=0.0)),
        swap_percent_peak=max(swap_percent, default=0.0),
        swap_used_bytes_peak=int(max(swap_bytes, default=0.0)),
        child_process_count_peak=int(max(children, default=0.0)),
        queue_lag_p50_seconds=_percentile(queue_lags, 0.50),
        queue_lag_p95_seconds=_percentile(queue_lags, 0.95),
        queue_depth_peak=int(max(queue_depths, default=0.0)),
        codex_accepted_patches_per_hour=accepted_patches / total_elapsed * 3600.0,
        transient_failure_rate=max(transient_rates, default=0.0),
        cycle_seconds=(
            statistics.fmean(cycle_samples)
            if cycle_samples
            else total_elapsed / len(summaries)
        ),
        cold_cache_hit_rate=cache_rates["cold"],
        warm_cache_hit_rate=cache_rates["warm"],
        quality_metrics=quality,
        sample_count=sample_count,
    )
    return BenchmarkTrial(profile=profile, metrics=metrics)


def _dry_metrics(
    multiplier: float,
    *,
    cpu: float,
    cycle: float,
    quality_delta: float = 0.0,
) -> PipelineBenchmarkMetrics:
    phase_latency = {
        phase: PhaseLatency(
            p50_seconds=round((0.05 + index * 0.003) / multiplier, 6),
            p95_seconds=round((0.09 + index * 0.006) / multiplier, 6),
        )
        for index, phase in enumerate(RUNTIME_PHASES)
    }
    quality = {
        "compiler_ir_cosine": 0.82 + quality_delta,
        "structural_validity": 0.96 + quality_delta,
        "symbolic_validity_success_rate": 0.95 + quality_delta,
        "hammer_proof_success_rate": 0.91 + quality_delta,
        "hammer_reconstruction_success_rate": 0.89 + quality_delta,
        "source_copy_penalty": 0.08 - quality_delta,
    }
    return PipelineBenchmarkMetrics(
        cold_cache_throughput_per_hour=180.0 * multiplier,
        warm_cache_throughput_per_hour=360.0 * multiplier,
        phase_latency=phase_latency,
        trainer_duty_cycle=min(0.90, 0.58 * multiplier),
        proof_throughput_per_hour=520.0 * multiplier,
        reconstruction_throughput_per_hour=310.0 * multiplier,
        leanstral_batch_efficiency=min(1.0, 0.68 * multiplier),
        leanstral_average_batch_size=min(8.0, 5.4 * multiplier),
        cpu_utilization_average=cpu,
        cpu_utilization_peak=min(0.98, cpu + 0.08),
        gpu_utilization_average=min(0.95, 0.62 * multiplier),
        gpu_utilization_peak=min(0.98, 0.78 * multiplier),
        gpu_memory_percent_peak=78.0,
        memory_percent_peak=72.0,
        memory_used_bytes_peak=92 * 1024**3,
        swap_percent_peak=0.0,
        swap_used_bytes_peak=0,
        child_process_count_peak=22,
        queue_lag_p50_seconds=12.0 / multiplier,
        queue_lag_p95_seconds=42.0 / multiplier,
        queue_depth_peak=14,
        codex_accepted_patches_per_hour=1.8 * multiplier,
        transient_failure_rate=0.06,
        cycle_seconds=cycle,
        cold_cache_hit_rate=0.02,
        warm_cache_hit_rate=0.88,
        quality_metrics=quality,
        sample_count=128,
    )


def dry_run_trials() -> list[BenchmarkTrial]:
    """Deterministic schema-complete trials used only to validate the harness."""

    baseline = BenchmarkTrial(ParallelismProfile(name="fixed_baseline"), _dry_metrics(1.0, cpu=0.72, cycle=737.526))
    balanced_profile = ParallelismProfile(
        name="balanced_dgx_spark",
        hammer_workers=4,
        lean_reconstruction_workers=2,
        leanstral_workers=2,
        legal_ir_family_workers=4,
        incremental_validation_workers=4,
        snapshot_evaluator_workers=2,
        codex_workers=4,
    )
    saturated_profile = ParallelismProfile(
        name="cpu_saturated",
        hammer_workers=6,
        lean_reconstruction_workers=1,
        leanstral_workers=1,
    )
    return [
        baseline,
        BenchmarkTrial(
            balanced_profile,
            _dry_metrics(
                1.90,
                cpu=0.83,
                cycle=round(737.526 / 1.90, 9),
                quality_delta=0.002,
            ),
        ),
        BenchmarkTrial(saturated_profile, _dry_metrics(1.50, cpu=0.97, cycle=350.0)),
    ]


def _profile_observation(trial: BenchmarkTrial, *, dry_run: bool) -> dict[str, Any]:
    """Project legacy aggregate metrics into the rollout comparison contract."""

    metrics = trial.metrics
    warm_cycles_per_hour = 3600.0 / metrics.cycle_seconds if metrics.cycle_seconds else 0.0
    return {
        "profile_name": trial.profile.name,
        "cold_cycles_per_hour": round(3600.0 / metrics.cycle_seconds, 9)
        if metrics.cycle_seconds
        else 0.0,
        "warm_cycles_per_hour": round(warm_cycles_per_hour, 9),
        "cold_samples_per_second": round(
            metrics.cold_cache_throughput_per_hour / 3600.0, 12
        ),
        "samples_per_second": round(metrics.warm_cache_throughput_per_hour / 3600.0, 12),
        # Queue residence is not interchangeable with state-to-accepted-patch
        # lag.  Legacy aggregate trials did not retain the latter, so only the
        # deterministic fixture may populate it here.  Raw production inputs
        # are handled by _source_profile_observation below.
        "state_to_accepted_patch_lag_p95_seconds": (
            round(metrics.queue_lag_p95_seconds, 9) if dry_run else None
        ),
        "cold_state_to_accepted_patch_lag_p95_seconds": (
            round(metrics.queue_lag_p95_seconds * 1.25, 9) if dry_run else None
        ),
        "canonical_sample_digest": (
            canonical_digest(list(_DRY_SAMPLE_IDS)) if dry_run else None
        ),
        "cold_cache_throughput_per_hour": round(
            metrics.cold_cache_throughput_per_hour, 9
        ),
        "warm_cache_throughput_per_hour": round(
            metrics.warm_cache_throughput_per_hour, 9
        ),
        "sample_count": metrics.sample_count,
        "aggregate_evidence_digest": canonical_digest(trial.to_dict()),
    }


def _comparison_ratio(candidate: float, baseline: float) -> float | None:
    if baseline <= 0.0:
        return None
    return round(candidate / baseline, 12)


def _first_value(summary: Mapping[str, Any], names: Sequence[str]) -> Any:
    for block in _nested_mappings(summary):
        for name in names:
            if name in block:
                return block[name]
    return None


def _declared_sample_digest(summary: Mapping[str, Any]) -> str | None:
    supplied = _first_value(
        summary,
        ("canonical_sample_digest", "benchmark_sample_digest", "sample_digest"),
    )
    if isinstance(supplied, str) and supplied.strip():
        return supplied.strip()
    ids = _first_value(summary, ("benchmark_sample_ids", "canonical_sample_ids"))
    if isinstance(ids, Sequence) and not isinstance(ids, (str, bytes, bytearray)):
        normalized = [str(item).strip() for item in ids]
        if normalized and all(normalized):
            return canonical_digest(normalized)
    return None


def _source_profile_observation(
    summaries: Sequence[Mapping[str, Any]], profile_name: str
) -> tuple[dict[str, Any], list[str]]:
    by_cache: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for summary in summaries:
        try:
            by_cache[_cache_state(summary)].append(summary)
        except ValueError:
            continue
    missing: list[str] = []
    rates: dict[str, dict[str, float | None]] = {}
    digests: dict[str, list[str]] = {}
    for state in ("cold", "warm"):
        state_summaries = by_cache[state]
        if not state_summaries:
            missing.append(f"{profile_name}:{state}_run")
            rates[state] = {"cycles_per_hour": None, "samples_per_second": None}
            digests[state] = []
            continue
        elapsed = sum(_elapsed(item) for item in state_summaries)
        cycle_values = [
            _first_number(
                item,
                ("benchmark_completed_cycles", "completed_cycle_count", "cycle_count"),
            )
            for item in state_summaries
        ]
        sample_values = [
            _first_number(
                item,
                (
                    "benchmark_processed_sample_count",
                    "processed_sample_count",
                    "samples_processed",
                    "benchmark_completed_units",
                ),
            )
            for item in state_summaries
        ]
        cycles = sum(value for value in cycle_values if value is not None)
        samples = sum(value for value in sample_values if value is not None)
        if elapsed <= 0.0:
            missing.append(f"{profile_name}:{state}_positive_elapsed_seconds")
        if any(value is None for value in cycle_values):
            missing.append(f"{profile_name}:{state}_completed_cycle_count")
        if any(value is None for value in sample_values):
            missing.append(f"{profile_name}:{state}_processed_sample_count")
        rates[state] = {
            "cycles_per_hour": round(cycles / elapsed * 3600.0, 9)
            if elapsed > 0.0 and all(value is not None for value in cycle_values)
            else None,
            "samples_per_second": round(samples / elapsed, 12)
            if elapsed > 0.0 and all(value is not None for value in sample_values)
            else None,
        }
        digests[state] = [canonical_digest(dict(item)) for item in state_summaries]
    cache_lags: dict[str, float | None] = {}
    for state in ("cold", "warm"):
        values = [
            _first_number(
                item,
                (
                    "state_to_accepted_patch_lag_p95_seconds",
                    "state_to_accepted_patch_p95_seconds",
                    "accepted_patch_lag_p95_seconds",
                ),
            )
            for item in by_cache[state]
        ]
        if not values or any(value is None for value in values):
            missing.append(
                f"{profile_name}:{state}_state_to_accepted_patch_lag_p95_seconds"
            )
            cache_lags[state] = None
        else:
            cache_lags[state] = max(
                float(value) for value in values if value is not None
            )
    sample_digests = {
        value
        for item in summaries
        for value in [_declared_sample_digest(item)]
        if value is not None
    }
    if len(sample_digests) != 1 or len(sample_digests) != len(
        {_declared_sample_digest(item) for item in summaries}
    ):
        missing.append(f"{profile_name}:consistent_canonical_sample_digest")
    return {
        "profile_name": profile_name,
        "cold_cycles_per_hour": rates["cold"]["cycles_per_hour"],
        "warm_cycles_per_hour": rates["warm"]["cycles_per_hour"],
        "cold_samples_per_second": rates["cold"]["samples_per_second"],
        "samples_per_second": rates["warm"]["samples_per_second"],
        "cold_state_to_accepted_patch_lag_p95_seconds": cache_lags["cold"],
        "state_to_accepted_patch_lag_p95_seconds": cache_lags["warm"],
        "canonical_sample_digest": next(iter(sample_digests), None),
        "cold_source_evidence_digests": digests["cold"],
        "warm_source_evidence_digests": digests["warm"],
        "cold_observation_count": len(by_cache["cold"]),
        "warm_observation_count": len(by_cache["warm"]),
    }, missing


_FAMILY_ALIASES = {"kg": "knowledge_graphs", "knowledge_graph": "knowledge_graphs"}
_FAMILY_METRIC_ALIASES: Mapping[str, tuple[str, ...]] = {
    "ir_cross_entropy_loss": ("ir_cross_entropy_loss", "compiler_ir_cross_entropy_loss"),
    "ir_cosine_similarity": ("ir_cosine_similarity", "compiler_ir_cosine"),
    "autoencoder_cross_entropy_loss": ("autoencoder_cross_entropy_loss", "autoencoder_ce"),
    "autoencoder_cosine_similarity": ("autoencoder_cosine_similarity", "autoencoder_cosine"),
    "semantic_equivalence": ("semantic_equivalence", "semantic_equivalence_score"),
    "proof_success_rate": ("proof_success_rate", "hammer_proof_success_rate"),
    "reconstruction_success_rate": (
        "reconstruction_success_rate",
        "hammer_reconstruction_success_rate",
    ),
    "provenance": (
        "provenance",
        "provenance_success_rate",
        "provenance_alignment_score",
        "provenance_coverage",
    ),
    "round_trip": (
        "round_trip",
        "round_trip_success_rate",
        "decompiler_round_trip_preservation",
    ),
    "uncertainty": (
        "uncertainty",
        "expected_calibration_error",
        "calibration_error",
    ),
    "holdout": ("holdout", "holdout_success_rate", "holdout_score"),
    "source_copy_penalty": (
        "source_copy_penalty",
        "source_copy_reward_hack_penalty",
    ),
}


def _source_family_quality(
    summaries: Sequence[Mapping[str, Any]], profile_name: str
) -> tuple[dict[str, dict[str, float]], list[str]]:
    candidates: list[Mapping[str, Any]] = []
    for summary in summaries:
        raw = _first_value(
            summary,
            (
                "benchmark_family_metrics",
                "legal_ir_view_family_metrics",
                "legal_ir_family_metrics",
            ),
        )
        if isinstance(raw, Mapping):
            candidates.append(raw)
    missing: list[str] = []
    result: dict[str, dict[str, float]] = {}
    for family in LEGAL_IR_EVALUATION_FAMILIES:
        observations: list[Mapping[str, Any]] = []
        for block in candidates:
            value = block.get(family)
            if value is None:
                value = block.get(next((key for key, target in _FAMILY_ALIASES.items() if target == family and key in block), ""))
            if isinstance(value, Mapping):
                observations.append(value)
        if not observations:
            missing.append(f"{profile_name}:family:{family}")
            continue
        result[family] = {}
        for metric, direction in PER_FAMILY_QUALITY_METRICS.items():
            values: list[float] = []
            for observation in observations:
                value = _first_number(observation, _FAMILY_METRIC_ALIASES[metric])
                if value is None and metric == "semantic_equivalence":
                    semantic = observation.get("semantic_equivalence")
                    if isinstance(semantic, Mapping):
                        semantic_values = [
                            number
                            for item in semantic.values()
                            for number in [_finite(item)]
                            if number is not None
                        ]
                        value = min(semantic_values) if semantic_values else None
                if value is not None:
                    values.append(value)
            if not values:
                missing.append(f"{profile_name}:family:{family}:{metric}")
                continue
            result[family][metric] = max(values) if direction == "lower" else min(values)
    return result, missing


def _source_runtime_and_artifacts(
    summaries: Sequence[Mapping[str, Any]], profile_name: str
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    warm = [item for item in summaries if str(item.get("benchmark_cache_state", "")).lower() == "warm"]
    source = warm[-1] if warm else (summaries[-1] if summaries else {})
    missing: list[str] = []

    def number(names: Sequence[str]) -> float | None:
        return _first_number(source, names)

    autoencoder_device = str(
        _first_value(source, ("autoencoder_training_device", "training_device")) or ""
    ).lower()
    cpu_fallback = _first_value(
        source, ("autoencoder_cpu_fallback", "cpu_fallback", "used_cpu_fallback")
    )
    autoencoder_counts = {
        "forward_count": number(("autoencoder_forward_count", "cuda_forward_count")),
        "loss_count": number(("autoencoder_loss_count", "finite_loss_count")),
        "backward_count": number(("autoencoder_backward_count", "cuda_backward_count")),
        "optimizer_step_count": number(
            ("autoencoder_optimizer_step_count", "optimizer_step_count")
        ),
    }
    autoencoder_passed = (
        autoencoder_device.startswith("cuda")
        and cpu_fallback is False
        and all(value is not None and value > 0 for value in autoencoder_counts.values())
    )
    if not autoencoder_passed:
        missing.append(f"{profile_name}:cuda_autoencoder_training")

    lean_device = str(
        _first_value(source, ("leanstral_device", "inference_device", "service_device"))
        or ""
    ).lower()
    reuse_count = number(("leanstral_reuse_count", "warm_reuse_count", "service_reuse_count"))
    weight_reload_count = number(
        ("leanstral_weight_reload_count", "warm_weight_reload_count", "weight_reload_count")
    )
    lean_service_ids = {
        str(value)
        for item in summaries
        for value in [
            _first_value(item, ("leanstral_service_id", "service_instance_id"))
        ]
        if value is not None and str(value).strip()
    }
    lean_passed = (
        lean_device.startswith("cuda")
        and reuse_count is not None
        and reuse_count > 0
        and weight_reload_count == 0
        and len(lean_service_ids) == 1
    )
    if not lean_passed:
        missing.append(f"{profile_name}:persistent_cuda_leanstral_reuse")

    hammer_healthy = _first_value(source, ("hammer_healthy", "hammer_path_healthy"))
    hammer_count = number(("hammer_attempt_count", "hammer_obligation_count"))
    proof_count = number(("hammer_proved_count", "hammer_proof_count"))
    reconstruction_count = number(
        ("hammer_reconstruction_success_count", "reconstruction_success_count")
    )
    hammer_passed = (
        hammer_healthy is True
        and hammer_count is not None
        and hammer_count > 0
        and proof_count is not None
        and proof_count > 0
        and reconstruction_count is not None
        and reconstruction_count > 0
    )
    if not hammer_passed:
        missing.append(f"{profile_name}:healthy_hammer_path")

    codex_healthy = _first_value(source, ("codex_healthy", "codex_path_healthy"))
    codex_attempts = number(("codex_attempt_count", "codex_invocation_count"))
    codex_outcomes = number(
        (
            "codex_accepted_or_safely_rejected_count",
            "codex_terminal_safe_outcome_count",
            "codex_accepted_patch_count",
        )
    )
    codex_passed = (
        codex_healthy is True
        and codex_attempts is not None
        and codex_attempts > 0
        and codex_outcomes is not None
        and codex_outcomes > 0
    )
    if not codex_passed:
        missing.append(f"{profile_name}:healthy_codex_path")

    orphan_count = number(("orphaned_child_count", "orphan_process_count"))
    no_orphans = orphan_count == 0
    if not no_orphans:
        missing.append(f"{profile_name}:zero_orphaned_children")

    checkpoint_bytes = number(("checkpoint_bytes", "checkpoint_size_bytes"))
    checkpoint_max = number(("checkpoint_bytes_max", "max_checkpoint_bytes"))
    summary_bytes = number(("summary_bytes", "summary_size_bytes"))
    summary_max = number(("summary_bytes_max", "max_summary_bytes"))
    checkpoint_bounded = (
        checkpoint_bytes is not None
        and checkpoint_max is not None
        and 0 <= checkpoint_bytes <= checkpoint_max
    )
    summary_bounded = (
        summary_bytes is not None
        and summary_max is not None
        and 0 <= summary_bytes <= summary_max
    )
    if not checkpoint_bounded:
        missing.append(f"{profile_name}:bounded_checkpoint_bytes")
    if not summary_bounded:
        missing.append(f"{profile_name}:bounded_summary_bytes")

    runtime = {
        "observed": True,
        "autoencoder": {
            "device": autoencoder_device or None,
            "cpu_fallback": cpu_fallback,
            **autoencoder_counts,
            "passed": autoencoder_passed,
        },
        "leanstral": {
            "device": lean_device or None,
            "service_id": next(iter(lean_service_ids), None),
            "reuse_count": reuse_count,
            "warm_weight_reload_count": weight_reload_count,
            "passed": lean_passed,
        },
        "hammer": {
            "healthy": hammer_healthy,
            "attempt_count": hammer_count,
            "proof_count": proof_count,
            "reconstruction_count": reconstruction_count,
            "passed": hammer_passed,
        },
        "codex": {
            "healthy": codex_healthy,
            "attempt_count": codex_attempts,
            "accepted_or_safely_rejected_count": codex_outcomes,
            "passed": codex_passed,
        },
        "orphaned_child_count": orphan_count,
        "passed": autoencoder_passed and lean_passed and hammer_passed and codex_passed and no_orphans,
    }
    artifacts = {
        "observed": True,
        "checkpoint_bytes": {
            "observed": checkpoint_bytes,
            "maximum": checkpoint_max,
            "bounded": checkpoint_bounded,
        },
        "summary_bytes": {
            "observed": summary_bytes,
            "maximum": summary_max,
            "bounded": summary_bounded,
        },
        "passed": checkpoint_bounded and summary_bounded,
    }
    return runtime, artifacts, missing


def _profile_groups(
    summaries: Sequence[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    result: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in summaries:
        profile_value = item.get("benchmark_profile") or item.get("profile")
        if not isinstance(profile_value, Mapping) or "benchmark_cache_state" not in item:
            continue
        try:
            profile = ParallelismProfile.from_dict(profile_value)
        except (TypeError, ValueError):
            continue
        result[profile.name].append(item)
    return result


def _source_promotion_contract(
    trials: Sequence[BenchmarkTrial], summaries: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, Any], Mapping[str, Mapping[str, Any]]]:
    baselines = [item for item in trials if item.profile.name == "fixed_baseline"]
    candidates = [
        item
        for item in trials
        if item.profile.name != "fixed_baseline"
        and "saturated" not in item.profile.name.lower()
    ]
    if len(baselines) != 1 or not candidates:
        return _promotion_contract(trials, dry_run=False), {}
    candidate_trial = max(
        candidates,
        key=lambda item: (item.metrics.warm_cache_throughput_per_hour, item.profile.name),
    )
    groups = _profile_groups(summaries)
    names = ("fixed_baseline", candidate_trial.profile.name)
    missing: list[str] = []
    observations: dict[str, Mapping[str, Any]] = {}
    qualities: dict[str, Mapping[str, Mapping[str, float]]] = {}
    runtimes: dict[str, Any] = {}
    artifacts: dict[str, Any] = {}
    for name in names:
        group = groups.get(name, [])
        observation, observation_missing = _source_profile_observation(group, name)
        quality, quality_missing = _source_family_quality(group, name)
        runtime, artifact, runtime_missing = _source_runtime_and_artifacts(group, name)
        observations[name] = observation
        qualities[name] = quality
        runtimes[name] = runtime
        artifacts[name] = artifact
        missing.extend(observation_missing)
        missing.extend(quality_missing)
        missing.extend(runtime_missing)

    matching_dimensions: dict[str, Any] = {}
    identity_aliases: Mapping[str, tuple[str, ...]] = {
        "code_revision": ("code_revision", "git_revision", "promotion_revision"),
        "compiler_artifact_digest": (
            "compiler_artifact_digest",
            "compiler_digest",
        ),
        "model_and_context_digest": (
            "model_and_context_digest",
            "model_context_digest",
        ),
        "hardware_identity": ("hardware_identity", "hardware_digest"),
        "random_seeds": ("random_seeds", "benchmark_seeds"),
    }
    raw_selected = [item for name in names for item in groups.get(name, [])]
    for dimension, aliases in identity_aliases.items():
        values = [
            _first_value(item, aliases)
            for item in raw_selected
        ]
        normalized = {
            canonical_digest(value) if isinstance(value, (Mapping, Sequence)) and not isinstance(value, str) else str(value)
            for value in values
            if value is not None and str(value).strip()
        }
        if len(values) != len(raw_selected) or len(normalized) != 1:
            missing.append(f"matched_identity:{dimension}")
            matching_dimensions[dimension] = None
        else:
            matching_dimensions[dimension] = values[0]
    baseline_digest = observations["fixed_baseline"].get("canonical_sample_digest")
    candidate_digest = observations[candidate_trial.profile.name].get(
        "canonical_sample_digest"
    )
    sample_matched = bool(baseline_digest and baseline_digest == candidate_digest)
    if not sample_matched:
        missing.append("matched_identity:canonical_sample_digest")

    quality_comparison = _family_quality_comparison(
        qualities["fixed_baseline"], qualities[candidate_trial.profile.name]
    )
    missing.extend(quality_comparison["failures"])

    candidate_sources = groups.get(candidate_trial.profile.name, [])
    required_ablation_components = {
        "cuda_autoencoder_training",
        "persistent_leanstral_reuse",
        "hammer_and_reconstruction_parallelism",
        "codex_bundle_and_validation_rescue",
        "resource_aware_pipeline_scheduling",
    }
    ablation = _first_value(candidate_sources[-1], ("ablation_evidence",)) if candidate_sources else None
    raw_ablation_observations = ablation.get("observations") if isinstance(ablation, Mapping) else None
    observed_components = {
        str(item.get("component") or "")
        for item in raw_ablation_observations
        if isinstance(item, Mapping)
    } if isinstance(raw_ablation_observations, Sequence) else set()
    ablation_complete = (
        isinstance(ablation, Mapping)
        and ablation.get("complete") is True
        and required_ablation_components <= observed_components
        and all(
            all(_finite(item.get(metric)) is not None for metric in (
                "warm_cycles_per_hour",
                "samples_per_second",
                "state_to_accepted_patch_lag_p95_seconds",
            ))
            for item in raw_ablation_observations
            if isinstance(item, Mapping)
        )
    )
    if not ablation_complete:
        missing.append("ablation_evidence:complete")
    ablation_payload = (
        dict(ablation)
        if isinstance(ablation, Mapping)
        else {
            "required_components": sorted(required_ablation_components),
            "observations": [],
            "complete": False,
        }
    )
    missing = sorted(set(missing))
    contract = {
        "reproducibility": {
            "canonical_sample_digest": baseline_digest if sample_matched else None,
            "matching_dimensions": matching_dimensions,
            "matched": sample_matched and all(
                value is not None for value in matching_dimensions.values()
            ),
            "cold_definition": "isolated empty cache namespace",
            "warm_definition": "retained cache and persistent service from the paired cold run",
            "run_order": ["baseline_cold", "baseline_warm", "candidate_cold", "candidate_warm"],
        },
        "runtime_evidence": runtimes,
        "artifact_bounds": artifacts,
        "quality_guardrails": quality_comparison,
        "ablation_evidence": ablation_payload,
        "missing_production_evidence": missing,
        "schema_complete": True,
        "production_evidence_complete": not missing,
    }
    return contract, observations


def _dry_family_quality(*, candidate: bool) -> dict[str, dict[str, float]]:
    """Return deterministic non-regressing values for every evaluation family."""

    adjustment = 0.002 if candidate else 0.0
    result: dict[str, dict[str, float]] = {}
    for index, family in enumerate(LEGAL_IR_EVALUATION_FAMILIES):
        family_adjustment = index * 0.001
        result[family] = {
            "ir_cross_entropy_loss": round(0.40 - family_adjustment - adjustment, 6),
            "ir_cosine_similarity": round(0.90 + family_adjustment + adjustment, 6),
            "autoencoder_cross_entropy_loss": round(
                0.34 - family_adjustment - adjustment, 6
            ),
            "autoencoder_cosine_similarity": round(
                0.91 + family_adjustment + adjustment, 6
            ),
            "semantic_equivalence": round(0.94 + family_adjustment + adjustment, 6),
            "proof_success_rate": round(
                0.91 + family_adjustment + adjustment, 6
            ),
            "reconstruction_success_rate": round(
                0.89 + family_adjustment + adjustment, 6
            ),
            "provenance": round(
                0.97 + min(family_adjustment, 0.007) + adjustment, 6
            ),
            "round_trip": round(
                0.93 + family_adjustment + adjustment, 6
            ),
            "uncertainty": round(
                0.12 - min(family_adjustment, 0.007) - adjustment, 6
            ),
            "holdout": round(
                0.90 + family_adjustment + adjustment, 6
            ),
            "source_copy_penalty": round(max(0.0, 0.05 - adjustment), 6),
        }
    return result


def _family_quality_comparison(
    baseline: Mapping[str, Mapping[str, float]],
    candidate: Mapping[str, Mapping[str, float]],
) -> dict[str, Any]:
    failures: list[str] = []
    comparisons: dict[str, Any] = {}
    for family in LEGAL_IR_EVALUATION_FAMILIES:
        family_result: dict[str, Any] = {}
        before = baseline.get(family)
        after = candidate.get(family)
        if not isinstance(before, Mapping) or not isinstance(after, Mapping):
            failures.append(f"missing_family:{family}")
            continue
        for metric, direction in PER_FAMILY_QUALITY_METRICS.items():
            before_value = _finite(before.get(metric))
            after_value = _finite(after.get(metric))
            if before_value is None or after_value is None:
                failures.append(f"missing_metric:{family}:{metric}")
                continue
            regression = (
                after_value > before_value + 1.0e-12
                if direction == "lower"
                else after_value < before_value - 1.0e-12
            )
            family_result[metric] = {
                "baseline": before_value,
                "candidate": after_value,
                "direction": direction,
                "regression": regression,
            }
            if regression:
                failures.append(f"quality_regression:{family}:{metric}")
        comparisons[family] = family_result
    return {
        "required_families": list(LEGAL_IR_EVALUATION_FAMILIES),
        "required_metrics": dict(PER_FAMILY_QUALITY_METRICS),
        "comparisons": comparisons,
        "failures": failures,
        "passed": not failures,
    }


def matched_benchmark_evidence(
    trials: Sequence[BenchmarkTrial],
    *,
    dry_run: bool = False,
    source_observations: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the direct baseline/candidate evidence consumed by rollout gates.

    This adapter intentionally keeps the established :class:`BenchmarkTrial`
    schema stable.  It chooses one named fixed baseline and the highest warm
    throughput non-saturated candidate, then publishes ratios with their raw
    values so a gate never has to infer units.
    """

    baselines = [item for item in trials if item.profile.name == "fixed_baseline"]
    if len(baselines) != 1:
        raise ValueError("matched benchmark requires exactly one fixed_baseline trial")
    candidates = [
        item
        for item in trials
        if item.profile.name != "fixed_baseline"
        and "saturated" not in item.profile.name.lower()
    ]
    if not candidates:
        raise ValueError("matched benchmark requires at least one candidate trial")
    baseline_trial = baselines[0]
    candidate_trial = max(
        candidates,
        key=lambda item: (item.metrics.warm_cache_throughput_per_hour, item.profile.name),
    )
    source_observations = source_observations or {}
    baseline = dict(
        source_observations.get(baseline_trial.profile.name)
        or _profile_observation(baseline_trial, dry_run=dry_run)
    )
    candidate = dict(
        source_observations.get(candidate_trial.profile.name)
        or _profile_observation(candidate_trial, dry_run=dry_run)
    )
    required_values = (
        "cold_cycles_per_hour",
        "cold_samples_per_second",
        "cold_state_to_accepted_patch_lag_p95_seconds",
        "warm_cycles_per_hour",
        "samples_per_second",
        "state_to_accepted_patch_lag_p95_seconds",
    )
    missing = [
        f"{role}:{name}"
        for role, observation in (("baseline", baseline), ("candidate", candidate))
        for name in required_values
        if _finite(observation.get(name)) is None
    ]
    baseline_warm = _finite(baseline.get("warm_cycles_per_hour")) or 0.0
    candidate_warm = _finite(candidate.get("warm_cycles_per_hour")) or 0.0
    baseline_samples = _finite(baseline.get("samples_per_second")) or 0.0
    candidate_samples = _finite(candidate.get("samples_per_second")) or 0.0
    warm_ratio = _comparison_ratio(
        candidate_warm, baseline_warm
    )
    samples_ratio = _comparison_ratio(
        candidate_samples, baseline_samples
    )
    lag_before = _finite(baseline.get("state_to_accepted_patch_lag_p95_seconds"))
    lag_after = _finite(candidate.get("state_to_accepted_patch_lag_p95_seconds"))
    checks = {
        "warm_cycles_per_hour": {
            "minimum_candidate_over_baseline": MINIMUM_WARM_CYCLES_PER_HOUR_RATIO,
            "observed_candidate_over_baseline": warm_ratio,
            "passed": warm_ratio is not None
            and warm_ratio >= MINIMUM_WARM_CYCLES_PER_HOUR_RATIO,
        },
        "samples_per_second": {
            "minimum_candidate_over_baseline": MINIMUM_SAMPLES_PER_SECOND_RATIO,
            "observed_candidate_over_baseline": samples_ratio,
            "passed": samples_ratio is not None
            and samples_ratio >= MINIMUM_SAMPLES_PER_SECOND_RATIO,
        },
        "state_to_accepted_patch_lag_p95_seconds": {
            "rule": "candidate_strictly_lower_than_baseline",
            "baseline": lag_before,
            "candidate": lag_after,
            "passed": lag_before is not None
            and lag_after is not None
            and lag_before > 0.0
            and 0.0 <= lag_after < lag_before,
        },
    }
    fixture_digest = baseline.get("canonical_sample_digest")
    reproducible = bool(
        fixture_digest
        and fixture_digest == candidate.get("canonical_sample_digest")
        and not missing
    )
    cold = {
        "baseline": {
            "cycles_per_hour": baseline.get("cold_cycles_per_hour"),
            "samples_per_second": baseline.get("cold_samples_per_second"),
            "state_to_accepted_patch_lag_p95_seconds": baseline.get(
                "cold_state_to_accepted_patch_lag_p95_seconds"
            ),
        },
        "candidate": {
            "cycles_per_hour": candidate.get("cold_cycles_per_hour"),
            "samples_per_second": candidate.get("cold_samples_per_second"),
            "state_to_accepted_patch_lag_p95_seconds": candidate.get(
                "cold_state_to_accepted_patch_lag_p95_seconds"
            ),
        },
    }
    warm = {
        "baseline": {
            "cycles_per_hour": baseline.get("warm_cycles_per_hour"),
            "samples_per_second": baseline.get("samples_per_second"),
            "state_to_accepted_patch_lag_p95_seconds": baseline.get(
                "state_to_accepted_patch_lag_p95_seconds"
            ),
        },
        "candidate": {
            "cycles_per_hour": candidate.get("warm_cycles_per_hour"),
            "samples_per_second": candidate.get("samples_per_second"),
            "state_to_accepted_patch_lag_p95_seconds": candidate.get(
                "state_to_accepted_patch_lag_p95_seconds"
            ),
        },
    }
    return {
        "schema_version": THROUGHPUT_REMEDIATION_SCHEMA_VERSION,
        "benchmark_kind": "matched_cold_warm_baseline_candidate",
        "dry_run": bool(dry_run),
        "reproducible": reproducible,
        "fixture_digest": fixture_digest,
        "configuration_digest": canonical_digest(
            {
                "baseline": baseline_trial.profile.to_dict(),
                "candidate": candidate_trial.profile.to_dict(),
            }
        ),
        "cold": cold,
        "warm": warm,
        "baseline": baseline,
        "candidate": candidate,
        "comparison": {
            "warm_cycles_per_hour_ratio": warm_ratio,
            "samples_per_second_ratio": samples_ratio,
            "state_to_accepted_patch_lag_p95_delta_seconds": round(
                lag_after - lag_before, 9
            ) if lag_before is not None and lag_after is not None else None,
        },
        "threshold_checks": checks,
        "missing_evidence": missing,
        "performance_passed": not missing and all(item["passed"] for item in checks.values()),
        # A dry run proves only schema and decision-path operation.  It cannot
        # be replayed as execution evidence by a production promotion gate.
        "promotion_eligible": not dry_run and not missing and all(
            item["passed"] for item in checks.values()
        ),
    }


def _promotion_contract(trials: Sequence[BenchmarkTrial], *, dry_run: bool) -> dict[str, Any]:
    baseline_quality = _dry_family_quality(candidate=False) if dry_run else {}
    candidate_quality = _dry_family_quality(candidate=True) if dry_run else {}
    quality = _family_quality_comparison(baseline_quality, candidate_quality)
    sample_digest = canonical_digest(list(_DRY_SAMPLE_IDS)) if dry_run else None
    missing = [
        "matched_canonical_sample_identity",
        "per_family_quality_metrics",
        "cuda_autoencoder_training",
        "persistent_cuda_leanstral_reuse",
        "hammer_health",
        "codex_health",
        "checkpoint_and_summary_byte_bounds",
        "orphan_process_audit",
    ]
    if dry_run:
        missing = ["non_dry_execution_evidence", "measured_ablation_evidence"]
    return {
        "reproducibility": {
            "canonical_sample_digest": sample_digest,
            "canonical_sample_count": len(_DRY_SAMPLE_IDS) if dry_run else 0,
            "random_seeds": [1701, 1702, 1703],
            "run_order": ["baseline_cold", "baseline_warm", "candidate_cold", "candidate_warm"],
            "cold_definition": "new isolated cache namespace; no retained model or compiler cache",
            "warm_definition": "same immutable inputs and process lineage; retained caches and Leanstral service",
            "matching_dimensions": [
                "ordered_sample_ids",
                "code_revision",
                "compiler_artifact_digest",
                "model_and_context_digest",
                "hardware_identity",
                "random_seeds",
            ],
        },
        "runtime_evidence": {
            "observed": not dry_run,
            "autoencoder": {
                "required_device": "cuda",
                "requires_forward_loss_backward_optimizer_step": True,
                "cpu_fallback_allowed": False,
            },
            "leanstral": {
                "required_device": "cuda",
                "persistent_service_required": True,
                "warm_reuse_required": True,
                "warm_weight_reload_allowed": False,
            },
            "hammer": {"healthy_path_required": True, "proof_activity_required": True},
            "codex": {
                "healthy_path_required": True,
                "accepted_or_safely_rejected_activity_required": True,
            },
            "orphaned_child_count_maximum": 0,
        },
        "artifact_bounds": {
            "observed": not dry_run,
            "checkpoint_bytes": {"required": True, "bounded": False if dry_run else None},
            "summary_bytes": {"required": True, "bounded": False if dry_run else None},
        },
        "quality_guardrails": quality,
        "ablation_evidence": {
            "required_components": [
                "cuda_autoencoder_training",
                "persistent_leanstral_reuse",
                "hammer_and_reconstruction_parallelism",
                "codex_bundle_and_validation_rescue",
                "resource_aware_pipeline_scheduling",
            ],
            "required_measurements": [
                "warm_cycles_per_hour",
                "samples_per_second",
                "state_to_accepted_patch_lag_p95_seconds",
            ],
            "observations": [],
            "complete": False,
            "note": "Dry-run and legacy aggregate trials define the ablation contract; production runs must supply measured one-change-at-a-time observations.",
        },
        "missing_production_evidence": missing,
        "schema_complete": True,
        "production_evidence_complete": not dry_run and not missing and quality["passed"],
    }


def _rollout_quality_pairs(quality: Mapping[str, Any]) -> dict[str, Any]:
    """Render the family-pair shape accepted by the rollout promotion gate."""

    comparisons = quality.get("comparisons")
    if not isinstance(comparisons, Mapping):
        return {}
    rollout_names = {
        "deontic": "deontic",
        "frame_logic": "frame_logic",
        "tdfol": "tdfol",
        "knowledge_graphs": "kg",
        "cec": "cec",
        "external_provers": "external_provers",
        "decompiler": "decompiler",
    }
    result: dict[str, Any] = {}
    for source_name, rollout_name in rollout_names.items():
        family = comparisons.get(source_name)
        if not isinstance(family, Mapping):
            continue
        before: dict[str, float] = {}
        after: dict[str, float] = {}
        for metric in PER_FAMILY_QUALITY_METRICS:
            item = family.get(metric)
            if not isinstance(item, Mapping):
                continue
            baseline = _finite(item.get("baseline"))
            candidate = _finite(item.get("candidate"))
            if baseline is not None and candidate is not None:
                before[metric] = baseline
                after[metric] = candidate
        result[rollout_name] = {"baseline": before, "candidate": after}
    return result


def benchmark_document(
    trials: Sequence[BenchmarkTrial],
    *,
    dry_run: bool = False,
    source_summaries: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    if not trials:
        raise ValueError("benchmark report requires at least one trial")
    source_observations: Mapping[str, Mapping[str, Any]] = {}
    if not dry_run and source_summaries:
        contract, source_observations = _source_promotion_contract(
            trials, source_summaries
        )
    else:
        contract = _promotion_contract(trials, dry_run=dry_run)
    has_baseline = sum(item.profile.name == "fixed_baseline" for item in trials) == 1
    has_candidate = any(
        item.profile.name != "fixed_baseline"
        and "saturated" not in item.profile.name.lower()
        for item in trials
    )
    matched: dict[str, Any]
    if has_baseline and has_candidate:
        matched = matched_benchmark_evidence(
            trials,
            dry_run=dry_run,
            source_observations=source_observations,
        )
    else:
        matched = {
            "schema_version": THROUGHPUT_REMEDIATION_SCHEMA_VERSION,
            "benchmark_kind": "matched_cold_warm_baseline_candidate",
            "dry_run": bool(dry_run),
            "baseline": None,
            "candidate": None,
            "comparison": {},
            "threshold_checks": {},
            "performance_passed": False,
            "promotion_eligible": False,
            "missing_evidence": ["fixed_baseline_and_candidate_trials"],
        }
    payload: dict[str, Any] = {
        "schema_version": PIPELINE_BENCHMARK_SCHEMA_VERSION,
        "promotion_schema_version": THROUGHPUT_REMEDIATION_SCHEMA_VERSION,
        "dry_run": bool(dry_run),
        "measurement_contract": list(REQUIRED_MEASUREMENTS),
        "trials": [trial.to_dict() for trial in trials],
        "matched_benchmark": matched,
        "reproducibility": contract["reproducibility"],
        "runtime_services": contract["runtime_evidence"],
        "artifact_bounds": contract["artifact_bounds"],
        "quality_guardrails": contract["quality_guardrails"],
        "quality_families": _rollout_quality_pairs(contract["quality_guardrails"]),
        "ablation_evidence": contract["ablation_evidence"],
        "evidence_completeness": {
            "schema_complete": contract["schema_complete"],
            "production_evidence_complete": contract["production_evidence_complete"],
            "missing_production_evidence": contract["missing_production_evidence"],
            "promotion_eligible": bool(
                matched.get("promotion_eligible")
                and contract["production_evidence_complete"]
                and not dry_run
            ),
        },
    }
    payload["evidence_digest"] = canonical_digest(payload)
    return payload


def _load_json_documents(path: Path) -> list[Mapping[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        result = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        value = json.loads(text)
        result = value if isinstance(value, list) else [value]
    if not all(isinstance(item, Mapping) for item in result):
        raise ValueError(f"input contains a non-object JSON value: {path}")
    return result


def _trials_from_documents(raw: Sequence[Mapping[str, Any]]) -> list[BenchmarkTrial]:
    direct: list[BenchmarkTrial] = []
    summaries_by_profile: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    profile_by_name: dict[str, ParallelismProfile] = {}
    for item in raw:
        if isinstance(item.get("trials"), Sequence):
            direct.extend(BenchmarkTrial.from_dict(trial) for trial in item["trials"])
            continue
        if isinstance(item.get("metrics"), Mapping) and isinstance(item.get("profile"), Mapping):
            direct.append(BenchmarkTrial.from_dict(item))
            continue
        profile_value = item.get("benchmark_profile") or item.get("profile")
        if not isinstance(profile_value, Mapping):
            raise ValueError("raw daemon summaries require a benchmark_profile object")
        profile = ParallelismProfile.from_dict(profile_value)
        profile_by_name.setdefault(profile.name, profile)
        if profile_by_name[profile.name] != profile:
            raise ValueError(f"profile settings changed between repetitions: {profile.name}")
        summaries_by_profile[profile.name].append(item)
    for name in sorted(summaries_by_profile):
        direct.append(aggregate_pipeline_summaries(summaries_by_profile[name], profile_by_name[name]))
    names = [trial.profile.name for trial in direct]
    if len(names) != len(set(names)):
        raise ValueError("benchmark input contains duplicate aggregate profile names")
    return sorted(
        direct,
        key=lambda trial: (trial.profile.name != "fixed_baseline", trial.profile.name),
    )


def _trials_from_inputs(paths: Sequence[Path]) -> list[BenchmarkTrial]:
    raw: list[Mapping[str, Any]] = []
    for path in paths:
        raw.extend(_load_json_documents(path))
    return _trials_from_documents(raw)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        type=Path,
        help="Daemon summary JSON/JSONL or an existing benchmark report; repeatable.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write report JSON (stdout is always emitted).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Emit deterministic schema-complete trial evidence without running the pipeline.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.dry_run and args.input:
        raise SystemExit("--dry-run cannot be combined with --input")
    if not args.dry_run and not args.input:
        raise SystemExit("provide at least one --input or use --dry-run")
    source_summaries: list[Mapping[str, Any]] = []
    if args.dry_run:
        trials = dry_run_trials()
    else:
        for path in args.input:
            source_summaries.extend(_load_json_documents(path))
        trials = _trials_from_documents(source_summaries)
    document = benchmark_document(
        trials,
        dry_run=args.dry_run,
        source_summaries=source_summaries,
    )
    rendered = json.dumps(document, allow_nan=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
