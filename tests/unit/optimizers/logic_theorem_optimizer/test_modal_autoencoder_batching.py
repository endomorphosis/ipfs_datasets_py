"""Deterministic collation and resource-safe batch autotuning tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_batching import (
    ResourceSafeBatchRunner,
    SparseFeatureExample,
    SplitIsolationError,
    collate_sparse_minibatch,
    iter_collated_minibatches,
    plan_gradient_accumulation,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.parallelism_autotuner import (
    BatchAutotuneConfig,
    BatchSizeAutotuner,
    BatchSizeMeasurement,
    GlobalResourceBounds,
    ParallelismProfile,
)


def _row(sample_id: str, features, *, split: str = "train") -> SparseFeatureExample:
    return SparseFeatureExample(
        sample_id=sample_id,
        features=features,
        targets={"positive": 1.0},
        split=split,
    )


def test_variable_sparse_features_are_packed_canonically() -> None:
    rows = [
        _row("z", [("beta", 2.0), ("alpha", 1.0), ("beta", -0.5)]),
        _row("a", {"gamma": 3.0}),
        _row("m", {}),
    ]

    first = collate_sparse_minibatch(rows)
    second = collate_sparse_minibatch(list(reversed(rows)))

    assert first == second
    assert first.sample_ids == ("a", "m", "z")
    assert first.feature_keys == ("alpha", "beta", "gamma")
    assert first.row_offsets == (0, 1, 1, 3)
    assert first.row(2) == (("alpha", 1.0), ("beta", 1.5))
    assert first.nonzero_count == 3
    assert len(first.split_fingerprint) == 64


def test_split_isolation_is_enforced_and_iterator_never_crosses_it() -> None:
    train = _row("train-1", {"x": 1.0}, split="train")
    holdout = _row("holdout-1", {"y": 1.0}, split="holdout")

    with pytest.raises(SplitIsolationError):
        collate_sparse_minibatch([train, holdout])

    batches = list(iter_collated_minibatches([train, holdout], batch_size=64))
    assert [batch.split for batch in batches] == ["holdout", "train"]
    assert all(batch.batch_size == 1 for batch in batches)


def test_accumulation_ranges_cover_each_sample_once_with_weighted_loss() -> None:
    plan = plan_gradient_accumulation(10, accumulation_steps=3)

    assert plan.ranges == ((0, 4), (4, 8), (8, 10))
    assert plan.accumulation_steps == 3
    assert sum(stop - start for start, stop in plan.ranges) == 10
    assert sum(plan.loss_scales) == pytest.approx(1.0)
    assert plan.loss_scales == pytest.approx((0.4, 0.4, 0.2))


def _measurement(
    batch_size: int,
    throughput: float,
    *,
    peak: int,
    efficiency: float,
    quality: float = 0.90,
    split: str = "frozen-split",
) -> BatchSizeMeasurement:
    return BatchSizeMeasurement(
        batch_size=batch_size,
        samples_per_second=throughput,
        peak_memory_bytes=peak,
        memory_capacity_bytes=1_000,
        kernel_efficiency=efficiency,
        quality_metrics={"compiler_ir_cosine": quality, "compiler_ir_cross_entropy_loss": 0.2},
        split_fingerprint=split,
        sample_count=64,
    )


def test_autotuner_uses_measured_headroom_kernel_efficiency_and_quality() -> None:
    baseline = _measurement(1, 10.0, peak=200, efficiency=0.10)
    candidates = [
        _measurement(8, 14.0, peak=350, efficiency=0.70),  # below 1.5x
        _measurement(16, 17.0, peak=500, efficiency=0.40),  # weak kernels
        _measurement(32, 21.0, peak=700, efficiency=0.80),
        _measurement(64, 30.0, peak=950, efficiency=0.90),  # too little reserve
    ]

    decision = BatchSizeAutotuner().tune(baseline, candidates)
    evaluations = {item.batch_size: item for item in decision.evaluations}

    assert decision.promoted is True
    assert decision.selected_batch_size == 32
    assert "throughput_gain_below_minimum" in evaluations[8].violations
    assert "kernel_efficiency_below_minimum" in evaluations[16].violations
    assert "insufficient_memory_headroom" in evaluations[64].violations


def test_quality_or_split_regression_blocks_an_otherwise_fast_batch() -> None:
    baseline = _measurement(1, 10.0, peak=200, efficiency=0.1)
    degraded = _measurement(32, 30.0, peak=700, efficiency=0.9, quality=0.89)
    wrong_split = _measurement(
        64, 40.0, peak=700, efficiency=0.9, split="contaminated-split"
    )

    decision = BatchSizeAutotuner().tune(baseline, [wrong_split, degraded])
    violations = {item.batch_size: item.violations for item in decision.evaluations}

    assert decision.promoted is False
    assert "quality_regression:compiler_ir_cosine" in violations[32]
    assert "split_isolation_mismatch" in violations[64]


def test_dgx_spark_policy_admits_32_through_64_when_memory_allows() -> None:
    tuner = BatchSizeAutotuner(
        BatchAutotuneConfig(minimum_throughput_gain=1.5)
    )
    assert tuner.choose_batch_size(
        memory_capacity_bytes=128_000,
        memory_used_bytes=20_000,
        bytes_per_sample=1_000,
        kernel_efficiency_by_batch={8: 0.6, 16: 0.7, 32: 0.8, 64: 0.9},
    ) == 64
    assert not GlobalResourceBounds().profile_violations(
        replace(
            ParallelismProfile(name="dgx-batch"),
            modal_autoencoder_batch_min=32,
            modal_autoencoder_batch_max=64,
        )
    )


def test_recoverable_oom_retries_smaller_batch_and_restores_state_identity() -> None:
    state = ModalAutoencoderTrainingState(
        feature_embedding_weights={"counter": [0.0]}
    )
    object_id = id(state)
    identity_before = state.state_identity_record()
    oom_identities = []

    def update(chunk) -> int:
        state.feature_embedding_weights["counter"][0] += len(chunk)
        if len(chunk) > 16:
            oom_identities.append(state.state_identity_record())
            raise RuntimeError("CUDA out of memory while allocating activation")
        return len(chunk)

    result = ResourceSafeBatchRunner().run(
        list(range(40)),
        update,
        initial_batch_size=64,
        state=state,
    )

    assert result.selected_batch_size == 16
    assert result.retry_count == 2
    assert all(attempt.state_identity_restored for attempt in result.attempts)
    assert id(state) == object_id
    assert state.feature_embedding_weights["counter"] == [40.0]
    assert state.state_identity_record() != identity_before
    assert oom_identities


def test_non_oom_failure_is_not_retried() -> None:
    calls = []

    def fail(chunk):
        calls.append(len(chunk))
        raise ValueError("bad target")

    with pytest.raises(ValueError, match="bad target"):
        ResourceSafeBatchRunner().run(
            list(range(32)), fail, initial_batch_size=32
        )
    assert calls == [32]
