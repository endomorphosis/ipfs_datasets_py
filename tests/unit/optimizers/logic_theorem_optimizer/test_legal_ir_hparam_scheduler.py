"""Tests for resource-aware LegalIR hyperparameter search scheduling."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_hparam_scheduler import (
    FamilyGuardrailConfig,
    HParamSearchConfig,
    LegalIRHParamScheduler,
    ResourceRequirements,
    SharedBaseline,
    TrialSnapshot,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler,
    ResourceSchedulerConfig,
)


def _baseline() -> SharedBaseline:
    families = {
        family: {
            "compiler_ir_cosine": 0.70,
            "hammer_proof_success_rate": 0.60,
            "source_copy_penalty": 0.10,
        }
        for family in ("deontic", "frame_logic")
    }
    return SharedBaseline(
        baseline_id="unit-baseline",
        revision="abc123",
        dataset_digest="sha256:" + "1" * 64,
        metric_lineage_id="unit-metric-lineage",
        metrics={"best_validation_ce": 1.0},
        family_metrics=families,
    )


def _scheduler(
    *,
    initial_candidate_count: int = 4,
    min_confidence: float = 0.80,
    allow_concurrent_trainers: bool = False,
    max_concurrent_trainers: int = 1,
    trainer_gpu_memory_mb: int = 100,
) -> LegalIRHParamScheduler:
    config = HParamSearchConfig(
        baseline=_baseline(),
        total_budget_seconds=1200,
        initial_candidate_count=initial_candidate_count,
        rung_budgets_seconds=(100, 200, 400),
        base_seed=42,
        max_concurrent_evaluations=4,
        max_concurrent_trainers=max_concurrent_trainers,
        allow_concurrent_trainers=allow_concurrent_trainers,
        guardrails=FamilyGuardrailConfig(
            required_families=("deontic", "frame_logic"),
            min_confidence=min_confidence,
        ),
        resources=ResourceRequirements(
            evaluation_cpu_slots=1,
            evaluation_memory_mb=10,
            trainer_cpu_slots=1,
            trainer_memory_mb=10,
            trainer_gpu_memory_mb=trainer_gpu_memory_mb,
            lease_timeout_seconds=0.0,
        ),
    )
    return LegalIRHParamScheduler(config)


def _family_metrics(*, confidence: float = 0.95, regression: bool = False) -> dict[str, dict[str, object]]:
    candidate_cosine = 0.69 if regression else 0.72
    return {
        family: {
            "confidence_lower_bound": confidence,
            "baseline": {
                "compiler_ir_cosine": 0.70,
                "hammer_proof_success_rate": 0.60,
                "source_copy_penalty": 0.10,
            },
            "candidate": {
                "compiler_ir_cosine": candidate_cosine,
                "hammer_proof_success_rate": 0.61,
                "source_copy_penalty": 0.09,
            },
            "semantic_regression": False,
            "provenance_regression": False,
            "anti_copy_regression": False,
            "hammer_proof_regression": False,
            "lean_reconstruction_regression": False,
            "process_lifecycle_regression": False,
            "queue_lag_regression": False,
        }
        for family in ("deontic", "frame_logic")
    }


def _snapshot(
    scheduler: LegalIRHParamScheduler,
    candidate_id: str,
    *,
    rung_index: int = 0,
    ce: float = 1.0,
    complete: bool = True,
    confidence: float = 0.95,
    regression: bool = False,
) -> TrialSnapshot:
    return TrialSnapshot(
        candidate_id=candidate_id,
        rung_index=rung_index,
        budget_seconds=scheduler.config.rungs[rung_index].budget_seconds,
        elapsed_seconds=scheduler.config.rungs[rung_index].budget_seconds,
        status="succeeded",
        snapshot_complete=complete,
        baseline_digest=scheduler.config.baseline.digest,
        lineage_digest=scheduler.config.baseline.lineage_digest,
        metrics={
            "best_validation_ce": ce,
            "best_validation_cosine": 0.90,
            "best_validation_ir_ce": ce + 0.1,
            "best_validation_ir_cosine": 0.91,
        },
        family_metrics=_family_metrics(confidence=confidence, regression=regression),
        snapshot_id=f"{candidate_id}-snapshot",
    )


def test_default_plan_uses_deterministic_seeds_and_successive_halving_budget() -> None:
    first = LegalIRHParamScheduler(
        HParamSearchConfig(baseline=_baseline(), base_seed=123)
    )
    second = LegalIRHParamScheduler(
        HParamSearchConfig(baseline=_baseline(), base_seed=123)
    )

    assert [candidate.seed for candidate in first.candidates] == [
        candidate.seed for candidate in second.candidates
    ]
    assert len(first.candidates) == 12
    assert len({candidate.baseline_digest for candidate in first.candidates}) == 1
    assert len({candidate.lineage_digest for candidate in first.candidates}) == 1
    assert first.config.planned_resource_seconds == 3600
    assert first.config.planned_resource_seconds == first.config.total_budget_seconds
    assert first.config.rungs[0].survivor_count > 6
    assert first.config.rungs[-1].survivor_count == 3


def test_incomplete_or_lineage_mismatched_snapshots_are_never_promoted() -> None:
    scheduler = _scheduler(initial_candidate_count=4)
    ready = scheduler.ready_work()
    candidate_ids = [item.candidate.candidate_id for item in ready]

    decision = scheduler.record_result(
        _snapshot(scheduler, candidate_ids[0], ce=0.1, complete=False)
    )
    assert decision.eligible is False
    assert "incomplete_snapshot" in decision.failures

    mismatched = _snapshot(scheduler, candidate_ids[1], ce=0.2)
    with pytest.raises(ValueError, match="metric lineage digest mismatch"):
        scheduler.record_result(
            TrialSnapshot(
                **{
                    **mismatched.to_dict(),
                    "lineage_digest": "sha256:different-lineage",
                }
            )
        )

    scheduler.record_result(_snapshot(scheduler, candidate_ids[1], ce=0.4))
    scheduler.record_result(_snapshot(scheduler, candidate_ids[2], ce=0.3))
    scheduler.record_result(_snapshot(scheduler, candidate_ids[3], ce=0.2))

    promoted_ids = {item.candidate.candidate_id for item in scheduler.ready_work()}
    assert candidate_ids[0] not in promoted_ids
    assert promoted_ids == {candidate_ids[2], candidate_ids[3]}


def test_confidence_aware_family_guardrails_filter_regressing_candidates() -> None:
    scheduler = _scheduler(initial_candidate_count=4, min_confidence=0.85)
    candidate_ids = [item.candidate.candidate_id for item in scheduler.ready_work()]

    low_confidence = scheduler.record_result(
        _snapshot(scheduler, candidate_ids[0], ce=0.05, confidence=0.60)
    )
    regressing = scheduler.record_result(
        _snapshot(scheduler, candidate_ids[1], ce=0.06, regression=True)
    )
    scheduler.record_result(_snapshot(scheduler, candidate_ids[2], ce=0.30))
    scheduler.record_result(_snapshot(scheduler, candidate_ids[3], ce=0.40))

    assert low_confidence.eligible is False
    assert any(failure.startswith("family_confidence:") for failure in low_confidence.failures)
    assert regressing.eligible is False
    assert any(
        failure.startswith("family_metric_regression:")
        for failure in regressing.failures
    )
    assert {item.candidate.candidate_id for item in scheduler.ready_work()} == {
        candidate_ids[2],
        candidate_ids[3],
    }


def _resource_scheduler(tmp_path: Path, *, gpu_memory_mb: int | None) -> GlobalResourceScheduler:
    return GlobalResourceScheduler(
        ResourceSchedulerConfig(
            total_cpu_slots=8,
            total_memory_mb=1000,
            total_gpu_memory_mb=gpu_memory_mb,
            lane_reservations={"validation": 4, "hammer_lean": 4},
            state_path=tmp_path / "resources.json",
            auto_renew_leases=False,
            poll_interval_seconds=0.005,
        )
    )


def test_trainer_concurrency_requires_known_gpu_memory_admission(tmp_path: Path) -> None:
    ready_scheduler = _scheduler(
        initial_candidate_count=4,
        allow_concurrent_trainers=True,
        max_concurrent_trainers=2,
        trainer_gpu_memory_mb=100,
    )
    unknown_gpu = _resource_scheduler(tmp_path / "unknown", gpu_memory_mb=None)
    unknown_bundles = ready_scheduler.admit_work(unknown_gpu)
    try:
        assert len(unknown_bundles) == 1
        assert unknown_bundles[0].trainer_lease is not None
    finally:
        for bundle in unknown_bundles:
            bundle.release()

    known_gpu_scheduler = _scheduler(
        initial_candidate_count=4,
        allow_concurrent_trainers=True,
        max_concurrent_trainers=2,
        trainer_gpu_memory_mb=100,
    )
    known_gpu = _resource_scheduler(tmp_path / "known", gpu_memory_mb=250)
    known_bundles = known_gpu_scheduler.admit_work(known_gpu)
    try:
        assert len(known_bundles) == 2
        assert all(bundle.trainer_lease is not None for bundle in known_bundles)
        snapshot = known_gpu.snapshot()
        assert snapshot["allocated_gpu_memory_mb"] == 200
    finally:
        for bundle in known_bundles:
            bundle.release()
