"""Projection profiler and sparse-batch trainer tests."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.projection_profiler import (
    PROJECTION_PROFILE_COST_FAMILIES,
    PROJECTION_PROFILE_SCHEMA_VERSION,
    ProjectionProfiler,
    summarize_projection_profiles,
)


def _samples():
    return [
        build_us_code_sample(
            title="5",
            section="552-profile",
            text="The agency shall provide notice before the permit takes effect.",
        ),
        build_us_code_sample(
            title="12",
            section="1841-profile",
            text="The applicant may appeal unless the board denies jurisdiction.",
        ),
    ]


def _stable_training_payload(report):
    return {
        "accepted_epochs": report["accepted_epochs"],
        "after": report["after"],
        "before": report["before"],
        "candidate_update_order": report["candidate_update_order"],
        "sample_memory_used": report["sample_memory_used"],
    }


def test_projection_profiler_aggregates_required_cost_families_by_family_and_head() -> None:
    profiler = ProjectionProfiler(enabled=True)

    with profiler.phase(
        "optimizer",
        stage="projection_update_batch",
        legal_family="deontic",
        feature_head="family_logits",
    ):
        sum(range(10))
    profiler.transfer(0.002, stage="metric_input", legal_family="deontic", count=2, bytes_moved=128)
    profiler.kernel(0.003, stage="metric_kernel", legal_family="deontic", count=1)
    profiler.record("synchronization", 0.001, stage="deferred_sync", legal_family="deontic")
    profiler.record("python_loop", 0.004, stage="hard_examples", legal_family="frame")
    profiler.record(
        "feature_head",
        0.005,
        stage="projection_update_head",
        legal_family="deontic",
        feature_head="family_logits",
    )

    summary = profiler.summarize()

    assert summary["schema_version"] == PROJECTION_PROFILE_SCHEMA_VERSION
    assert tuple(summary["cost_families"]) == PROJECTION_PROFILE_COST_FAMILIES
    assert summary["by_cost_family"]["host_device_transfer"]["count"] == pytest.approx(1.0)
    assert summary["by_cost_family"]["kernel"]["seconds"] == pytest.approx(0.003)
    assert summary["by_cost_family"]["synchronization"]["seconds"] == pytest.approx(0.001)
    assert summary["by_cost_family"]["python_loop"]["seconds"] == pytest.approx(0.004)
    assert "deontic" in summary["by_legal_family"]
    assert "family_logits" in summary["by_feature_head"]
    assert summary["counters"]["host_device_transfer_count"] == 2
    assert summary["counters"]["kernel_launch_count"] == 1
    assert summary["warm_p95_projection_seconds"] > 0.0


def test_profile_comparison_reports_40_percent_target() -> None:
    comparison = summarize_projection_profiles(
        baseline={"warm_p95_projection_seconds": 10.0},
        optimized={"warm_p95_projection_seconds": 5.5},
    )

    assert comparison["warm_p95_reduction_ratio"] == pytest.approx(0.45)
    assert comparison["meets_40_percent_target"] is True


def test_projection_training_emits_profile_and_batch_counters() -> None:
    profiler = ProjectionProfiler(enabled=True)
    autoencoder = AdaptiveModalAutoencoder(compute_device="python")

    report = autoencoder.train_generalizable_projection(
        _samples(),
        validation_samples=_samples(),
        epochs=1,
        learning_rate=0.2,
        max_line_search_attempts=1,
        projection_profiler=profiler,
        projection_update_backend="python_sparse_batch",
    )

    profile = report["projection_profile"]
    assert report["projection_profile_enabled"] is True
    assert report["projection_update_backend"] == "python_sparse_batch"
    assert profile["schema_version"] == PROJECTION_PROFILE_SCHEMA_VERSION
    assert profile["by_cost_family"]["optimizer"]["count"] >= 1.0
    assert profile["by_cost_family"]["feature_head"]["count"] >= 1.0
    assert profile["by_cost_family"]["python_loop"]["count"] >= 1.0
    assert profile["counters"]["projection_update_batch_count"] >= 1
    assert profile["counters"]["projection_update_sample_count"] >= 1


def test_sparse_batch_backend_preserves_deterministic_training_outputs() -> None:
    samples = _samples()
    validation = list(samples)
    native = AdaptiveModalAutoencoder(compute_device="python")
    sparse = AdaptiveModalAutoencoder(compute_device="python")

    native_report = native.train_generalizable_projection(
        samples,
        validation_samples=validation,
        epochs=1,
        learning_rate=0.2,
        max_line_search_attempts=2,
        projection_update_backend="native",
    )
    sparse_report = sparse.train_generalizable_projection(
        samples,
        validation_samples=validation,
        epochs=1,
        learning_rate=0.2,
        max_line_search_attempts=2,
        projection_update_backend="python_sparse_batch",
    )

    assert json.dumps(
        _stable_training_payload(sparse_report),
        sort_keys=True,
    ) == json.dumps(
        _stable_training_payload(native_report),
        sort_keys=True,
    )
