from __future__ import annotations

import json
from dataclasses import replace

import pytest

from scripts.ops.legal_ir.tune_hammer_leanstral_parallelism import (
    generate_candidate_profiles,
    tune_benchmark_trials,
)
from benchmarks.bench_legal_ir_optimizer_pipeline import (
    aggregate_pipeline_summaries,
    benchmark_document,
    dry_run_trials,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.parallelism_autotuner import (
    DGX_SPARK_PROFILE_SCHEMA_VERSION,
    BenchmarkTrial,
    GlobalResourceBounds,
    ParallelismAutotuner,
    ParallelismProfile,
    TrustBounds,
    canonical_digest,
    write_reproducible_profile,
)
def test_dry_run_trials_cover_fixed_baseline_and_balanced_candidate() -> None:
    trials = dry_run_trials()
    assert [item.profile.name for item in trials] == [
        "fixed_baseline",
        "balanced_dgx_spark",
        "cpu_saturated",
    ]
    result = tune_benchmark_trials(trials)
    assert result.promoted is True
    assert result.selected.profile.name == "balanced_dgx_spark"
    evaluations = {item.profile_name: item for item in result.evaluations}
    assert evaluations["balanced_dgx_spark"].eligible is True
    assert evaluations["cpu_saturated"].eligible is False
    assert any("cpu_utilization_above" in item for item in evaluations["cpu_saturated"].violations)


@pytest.mark.parametrize(
    ("changes", "violation"),
    [
        ({"trainer_count": 2}, "trainer_count:2!=1"),
        ({"hammer_workers": 7}, "hammer_lean_workers_exceed_lane"),
        ({"codex_workers": 5}, "codex_workers_exceed_lane"),
        ({"memory_budget_mb": 110 * 1024}, "memory_budget_mb"),
    ],
)
def test_global_bounds_reject_oversubscription(changes: dict[str, int], violation: str) -> None:
    profile = replace(ParallelismProfile(name="candidate"), **changes)
    failures = GlobalResourceBounds().profile_violations(profile)
    assert any(item.startswith(violation) for item in failures)


def test_quality_regression_blocks_faster_candidate() -> None:
    baseline, candidate, _ = dry_run_trials()
    degraded_quality = dict(candidate.metrics.quality_metrics)
    degraded_quality["hammer_proof_success_rate"] = baseline.metrics.quality_metrics[
        "hammer_proof_success_rate"
    ] - 0.01
    candidate = BenchmarkTrial(
        candidate.profile,
        replace(candidate.metrics, quality_metrics=degraded_quality),
    )
    evaluation = ParallelismAutotuner().evaluate(baseline, candidate)
    assert evaluation.eligible is False
    assert "quality_regression:hammer_proof_success_rate" in evaluation.violations
    assert "proof_success_rate_regression" in evaluation.violations


def test_failure_memory_swap_queue_and_cycle_bounds_fail_closed() -> None:
    baseline, candidate, _ = dry_run_trials()
    metrics = replace(
        candidate.metrics,
        transient_failure_rate=0.11,
        memory_percent_peak=91.0,
        swap_percent_peak=2.0,
        gpu_memory_percent_peak=93.0,
        queue_lag_p95_seconds=121.0,
        cycle_seconds=401.0,
    )
    evaluation = ParallelismAutotuner().evaluate(baseline, BenchmarkTrial(candidate.profile, metrics))
    assert evaluation.eligible is False
    assert set(evaluation.violations) >= {
        "transient_failure_rate_exceeded",
        "memory_percent_peak_exceeded",
        "swap_percent_peak_exceeded",
        "gpu_memory_percent_peak_exceeded",
        "queue_lag_p95_exceeded",
        "cycle_target_not_met",
    }


def test_no_eligible_improvement_keeps_fixed_baseline() -> None:
    baseline, candidate, _ = dry_run_trials()
    slow = replace(
        candidate.metrics,
        cold_cache_throughput_per_hour=baseline.metrics.cold_cache_throughput_per_hour * 0.5,
        warm_cache_throughput_per_hour=baseline.metrics.warm_cache_throughput_per_hour * 0.5,
    )
    result = ParallelismAutotuner().tune(baseline, [BenchmarkTrial(candidate.profile, slow)])
    assert result.promoted is False
    assert result.selected == baseline
    assert result.production_profile()["settings"]["name"] == "fixed_baseline"


def test_tie_break_and_profile_are_reproducible(tmp_path) -> None:
    baseline, candidate, _ = dry_run_trials()
    alpha = BenchmarkTrial(candidate.profile.with_name("alpha"), candidate.metrics)
    beta = BenchmarkTrial(candidate.profile.with_name("beta"), candidate.metrics)
    first = ParallelismAutotuner().tune(baseline, [beta, alpha])
    second = ParallelismAutotuner().tune(baseline, [alpha, beta])
    assert first.selected.profile.name == second.selected.profile.name == "alpha"
    assert first.production_profile() == second.production_profile()
    assert first.production_profile()["schema_version"] == DGX_SPARK_PROFILE_SCHEMA_VERSION
    assert "generated_at" not in first.production_profile()
    assert len(first.production_profile()["profile_digest"]) == 64

    left = write_reproducible_profile(tmp_path / "left.json", first)
    right = write_reproducible_profile(tmp_path / "right.json", second)
    assert left.read_bytes() == right.read_bytes()
    assert json.loads(left.read_text())["hardware"]["target"] == "NVIDIA DGX Spark"


def _summary(cache_state: str, *, cache_hit: float) -> dict:
    quality = {
        "compiler_ir_cosine": 0.9,
        "structural_validity": 0.98,
        "symbolic_validity_success_rate": 0.97,
        "hammer_proof_success_rate": 0.93,
        "hammer_reconstruction_success_rate": 0.91,
        "source_copy_penalty": 0.05,
    }
    resources = {
        "cpu_percent": 82.0,
        "gpu_utilization_percent": 70.0,
        "gpu_memory_percent": 75.0,
        "memory_percent": 65.0,
        "memory_used_bytes": 1024,
        "swap_percent": 0.0,
        "swap_used_bytes": 0,
        "child_process_count": 8,
        "queue_depth": 3,
    }
    spans = []
    for phase, duration, units in (
        ("compilation", 2.0, 10.0),
        ("projection_training", 2.0, 1.0),
        ("solver_execution", 1.0, 8.0),
        ("lean_reconstruction", 1.5, 6.0),
        ("leanstral_queue", 0.4, 2.0),
        ("codex_queue_wait", 0.8, 1.0),
    ):
        spans.append(
            {
                "phase": phase,
                "duration_seconds": duration,
                "unit_count": units,
                "resources_start": resources,
                "resources_end": resources,
            }
        )
    return {
        "benchmark_cache_state": cache_state,
        "benchmark_elapsed_seconds": 10.0,
        "benchmark_completed_units": 20,
        "benchmark_quality_metrics": quality,
        "codex_main_apply_count": 1,
        "program_synthesis_transient_failure_rate": 0.05,
        "runtime_telemetry": {"cache_hit_rate": cache_hit, "spans": spans},
        "leanstral_batch_telemetry": {
            "dispatched_item_count": 8,
            "formed_batch_count": 1,
            "batch_sizes": [8],
        },
    }


def test_aggregate_real_daemon_summaries_covers_complete_metric_contract() -> None:
    profile = ParallelismProfile(name="fixed_baseline")
    trial = aggregate_pipeline_summaries(
        [_summary("cold", cache_hit=0.0), _summary("warm", cache_hit=0.9)], profile
    )
    metrics = trial.metrics
    assert metrics.cold_cache_throughput_per_hour == pytest.approx(7200.0)
    assert metrics.warm_cache_throughput_per_hour == pytest.approx(7200.0)
    assert metrics.trainer_duty_cycle == pytest.approx(0.2)
    assert metrics.proof_throughput_per_hour == pytest.approx(2880.0)
    assert metrics.reconstruction_throughput_per_hour == pytest.approx(2160.0)
    assert metrics.leanstral_batch_efficiency == 1.0
    assert metrics.cpu_utilization_average == pytest.approx(0.82)
    assert metrics.gpu_utilization_average == pytest.approx(0.70)
    assert metrics.queue_lag_p50_seconds == pytest.approx(0.6)
    assert metrics.codex_accepted_patches_per_hour == pytest.approx(360.0)
    assert set(metrics.quality_metrics) == {
        "compiler_ir_cosine",
        "structural_validity",
        "symbolic_validity_success_rate",
        "hammer_proof_success_rate",
        "hammer_reconstruction_success_rate",
        "source_copy_penalty",
    }


def test_benchmark_document_digest_and_candidate_design_are_stable() -> None:
    first = benchmark_document(dry_run_trials(), dry_run=True)
    second = benchmark_document(dry_run_trials(), dry_run=True)
    assert first == second
    assert first["evidence_digest"] == second["evidence_digest"]
    assert canonical_digest({key: value for key, value in first.items() if key != "evidence_digest"}) == first["evidence_digest"]
    candidates = generate_candidate_profiles()
    assert len(candidates) == 3
    assert all(profile.trainer_count == 1 for profile in candidates)
    assert all(not GlobalResourceBounds().profile_violations(profile) for profile in candidates)


def test_baseline_name_and_candidate_uniqueness_are_enforced() -> None:
    baseline, candidate, _ = dry_run_trials()
    tuner = ParallelismAutotuner(trust_bounds=TrustBounds())
    with pytest.raises(ValueError, match="fixed_baseline"):
        tuner.tune(BenchmarkTrial(baseline.profile.with_name("other"), baseline.metrics), [candidate])
    with pytest.raises(ValueError, match="unique"):
        tuner.tune(baseline, [candidate, candidate])
