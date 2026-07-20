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
quality metrics.  ``--dry-run`` produces deterministic representative evidence
without launching models or provers and is suitable for installation checks.
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
        BenchmarkTrial(balanced_profile, _dry_metrics(1.45, cpu=0.83, cycle=365.0, quality_delta=0.002)),
        BenchmarkTrial(saturated_profile, _dry_metrics(1.50, cpu=0.97, cycle=350.0)),
    ]


def benchmark_document(trials: Sequence[BenchmarkTrial], *, dry_run: bool = False) -> dict[str, Any]:
    if not trials:
        raise ValueError("benchmark report requires at least one trial")
    payload: dict[str, Any] = {
        "schema_version": PIPELINE_BENCHMARK_SCHEMA_VERSION,
        "dry_run": bool(dry_run),
        "measurement_contract": list(REQUIRED_MEASUREMENTS),
        "trials": [trial.to_dict() for trial in trials],
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


def _trials_from_inputs(paths: Sequence[Path]) -> list[BenchmarkTrial]:
    raw: list[Mapping[str, Any]] = []
    for path in paths:
        raw.extend(_load_json_documents(path))
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
    trials = dry_run_trials() if args.dry_run else _trials_from_inputs(args.input)
    document = benchmark_document(trials, dry_run=args.dry_run)
    rendered = json.dumps(document, allow_nan=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
