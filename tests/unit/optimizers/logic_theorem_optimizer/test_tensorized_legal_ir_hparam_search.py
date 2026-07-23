"""Production contracts for the tensorized multi-fidelity LegalIR search."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_hparam_scheduler import (
    CompilerArtifactSet,
    FamilyGuardrailConfig,
    HParamResourcePressure,
    HParamSearchConfig,
    LegalIRHParamScheduler,
    ResourceRequirements,
    SharedBaseline,
    TENSORIZED_OBJECTIVE_METRICS,
    TrialSnapshot,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler,
    ResourceSchedulerConfig,
)


FAMILIES = ("deontic", "frame_logic")


def _metrics(delta: float = 0.0) -> dict[str, float]:
    return {
        "ir_cross_entropy_loss": 0.60 - delta,
        "ir_cosine_similarity": 0.80 + delta,
        "autoencoder_cross_entropy_loss": 0.70 - delta,
        "autoencoder_cosine_similarity": 0.75 + delta,
        "symbolic_validity_success_rate": 0.90 + delta,
        "hammer_proof_success_rate": 0.80 + delta,
        "reconstruction_success_rate": 0.78 + delta,
        "round_trip_success_rate": 0.88 + delta,
        "calibration_error": 0.10 - delta,
        "source_copy_penalty": 0.08 - delta,
    }


def _baseline() -> SharedBaseline:
    return SharedBaseline(
        baseline_id="immutable-unit-baseline",
        revision="compiler-revision-1",
        dataset_digest="sha256:" + "d" * 64,
        metric_lineage_id="tensorized-objective-v1",
        metrics=_metrics(),
        family_metrics={family: {"semantic_equivalence": 0.90} for family in FAMILIES},
        compiler_artifact_set=CompilerArtifactSet(
            compiler_revision="compiler-revision-1",
            compiler_config_digest="sha256:" + "c" * 64,
            dataset_digest="sha256:" + "d" * 64,
            artifacts={
                "compiled_ir": "sha256:" + "1" * 64,
                "proof_obligations": "sha256:" + "2" * 64,
                "evaluation_split": "sha256:" + "3" * 64,
            },
        ),
    )


def _scheduler(*, candidates: int = 4) -> LegalIRHParamScheduler:
    return LegalIRHParamScheduler(
        HParamSearchConfig(
            baseline=_baseline(),
            total_budget_seconds=240,
            initial_candidate_count=candidates,
            rung_budgets_seconds=(20, 40, 80),
            reduction_factor=2,
            base_seed=115,
            seeds_per_candidate=3,
            require_multi_seed_evidence=True,
            require_cuda_evidence=True,
            require_compiler_artifact_set=True,
            require_complete_parallel_lanes=True,
            require_tensorized_objective=True,
            max_evidence_age_seconds=60.0,
            guardrails=FamilyGuardrailConfig(
                required_families=FAMILIES,
                min_confidence=0.90,
            ),
        )
    )


def _family_metrics(delta: float = 0.01) -> dict[str, object]:
    baseline = _metrics()
    baseline["semantic_equivalence"] = 0.90
    candidate = _metrics(delta)
    candidate["semantic_equivalence"] = 0.90 + delta
    return {
        family: {
            "confidence_lower_bound": 0.97,
            "baseline": dict(baseline),
            "candidate": dict(candidate),
        }
        for family in FAMILIES
    }


def _snapshot(
    scheduler: LegalIRHParamScheduler,
    candidate_id: str,
    *,
    rung: int = 0,
    delta: float = 0.01,
    **overrides: object,
) -> TrialSnapshot:
    candidate = next(item for item in scheduler.candidates if item.candidate_id == candidate_id)
    values: dict[str, object] = {
        "candidate_id": candidate_id,
        "rung_index": rung,
        "budget_seconds": scheduler.config.rungs[rung].budget_seconds,
        "elapsed_seconds": scheduler.config.rungs[rung].budget_seconds,
        "status": "succeeded",
        "snapshot_complete": True,
        "baseline_digest": scheduler.config.baseline.digest,
        "lineage_digest": scheduler.config.baseline.lineage_digest,
        "compiler_artifact_set_digest": scheduler.config.baseline.compiler_artifact_set_digest,
        "seed_ids": candidate.seeds,
        "multi_seed_evidence_complete": True,
        "compute_backend": "torch_cuda",
        "cpu_fallback_used": False,
        "state_revision": scheduler.config.baseline.revision,
        "evidence_created_at_epoch": time.time(),
        "evaluation_lane_complete": True,
        "proof_lane_complete": True,
        "metrics": _metrics(delta),
        "metric_confidence": {
            name: {"confidence": 0.97} for name in TENSORIZED_OBJECTIVE_METRICS
        },
        "family_metrics": _family_metrics(delta),
        "snapshot_id": f"{candidate_id}-rung-{rung}",
    }
    values.update(overrides)
    return TrialSnapshot(**values)  # type: ignore[arg-type]


def test_plan_reuses_one_deeply_immutable_baseline_artifact_and_seed_set() -> None:
    scheduler = _scheduler()
    plan = scheduler.plan_dict()

    assert plan["successive_halving"]["rungs"] == [
        {"index": 0, "budget_seconds": 20, "survivor_count": 4},
        {"index": 1, "budget_seconds": 40, "survivor_count": 2},
        {"index": 2, "budget_seconds": 80, "survivor_count": 1},
    ]
    assert len({item.baseline_digest for item in scheduler.candidates}) == 1
    assert len({item.compiler_artifact_set_digest for item in scheduler.candidates}) == 1
    assert all(len(item.seeds) == 3 for item in scheduler.candidates)
    with pytest.raises(TypeError):
        scheduler.config.baseline.compiler_artifact_set.artifacts["new"] = "tampered"  # type: ignore[index,union-attr]


def test_successive_halving_jointly_ranks_every_quality_dimension() -> None:
    scheduler = _scheduler()
    candidate_ids = [item.candidate.candidate_id for item in scheduler.ready_work()]

    for index, candidate_id in enumerate(candidate_ids):
        scheduler.record_result(_snapshot(scheduler, candidate_id, delta=0.01 * (index + 1)))
    assert {item.candidate.candidate_id for item in scheduler.ready_work()} == set(candidate_ids[-2:])

    rung_one = scheduler.ready_work()
    for index, item in enumerate(rung_one):
        scheduler.record_result(_snapshot(scheduler, item.candidate.candidate_id, rung=1, delta=0.04 + index * 0.01))
    assert len(scheduler.ready_work()) == 1
    winner = scheduler.ready_work()[0].candidate
    scheduler.record_result(_snapshot(scheduler, winner.candidate_id, rung=2, delta=0.06))
    assert scheduler.selected_candidate() == winner
    report = scheduler.report_dict()
    assert report["search_complete"] is True
    assert report["promotion_eligible"] is True
    assert report["selected_candidate"]["candidate_id"] == winner.candidate_id
    assert len(report["report_digest"]) == 64


@pytest.mark.parametrize(
    ("change", "failure"),
    [
        ({"snapshot_complete": False}, "incomplete_snapshot"),
        ({"seed_ids": (1,), "multi_seed_evidence_complete": False}, "single_seed_or_incomplete"),
        ({"compute_backend": "cpu"}, "cuda_backend_required"),
        ({"cpu_fallback_used": True}, "cpu_fallback_used"),
        ({"stale": True}, "stale_evidence"),
        ({"proof_lane_complete": False}, "proof_lane_incomplete"),
    ],
)
def test_incomplete_stale_single_seed_or_cpu_trials_cannot_win(
    change: dict[str, object], failure: str
) -> None:
    scheduler = _scheduler()
    candidate_id = scheduler.ready_work()[0].candidate.candidate_id
    decision = scheduler.score_snapshot(_snapshot(scheduler, candidate_id, **change))

    assert decision.eligible is False
    assert any(item.startswith(failure) for item in decision.failures)


def test_any_metric_or_family_confidence_regression_is_a_hard_guardrail() -> None:
    scheduler = _scheduler()
    candidate_id = scheduler.ready_work()[0].candidate.candidate_id
    regressed = _metrics(0.02)
    regressed["calibration_error"] = 0.20
    family = _family_metrics()
    family["deontic"]["candidate"]["semantic_equivalence"] = 0.80  # type: ignore[index]

    decision = scheduler.score_snapshot(
        _snapshot(scheduler, candidate_id, metrics=regressed, family_metrics=family)
    )

    assert decision.eligible is False
    assert "objective_metric_regression:calibration_error" in decision.failures
    assert "family_metric_regression:deontic:semantic_equivalence" in decision.failures


def test_evaluation_and_proof_lanes_execute_concurrently_on_same_inputs() -> None:
    scheduler = _scheduler()
    work = scheduler.ready_work()[0]
    barrier = threading.Barrier(2)

    def lane(item: object) -> str:
        assert item is work
        barrier.wait(timeout=1.0)
        return threading.current_thread().name

    results = scheduler.run_independent_lanes(work, evaluation_lane=lane, proof_lane=lane)

    assert results.evaluation != results.proof
    assert results.elapsed_seconds < 1.0


def _resources(tmp_path: Path) -> GlobalResourceScheduler:
    return GlobalResourceScheduler(
        ResourceSchedulerConfig(
            total_cpu_slots=16,
            total_memory_mb=64000,
            total_gpu_memory_mb=48000,
            total_unified_memory_mb=64000,
            total_child_process_slots=32,
            lane_reservations={},
            state_path=tmp_path / "hparam-resources.json",
            auto_renew_leases=False,
        )
    )


def test_second_trainer_requires_fresh_low_unified_memory_and_service_pressure(
    tmp_path: Path,
) -> None:
    baseline = _baseline()
    scheduler = LegalIRHParamScheduler(
        HParamSearchConfig(
            baseline=baseline,
            total_budget_seconds=240,
            initial_candidate_count=4,
            rung_budgets_seconds=(20, 40, 80),
            allow_concurrent_trainers=True,
            max_concurrent_trainers=2,
            seeds_per_candidate=3,
            require_compiler_artifact_set=True,
            require_measured_second_trainer_pressure=True,
            resources=ResourceRequirements(
                trainer_gpu_memory_mb=12000,
                trainer_unified_memory_mb=12000,
            ),
            guardrails=FamilyGuardrailConfig(required_families=FAMILIES),
        )
    )
    resources = _resources(tmp_path)
    healthy = HParamResourcePressure(
        telemetry_known=True,
        unified_memory_pressure=0.20,
        gpu_memory_pressure=0.20,
        memory_pressure=0.20,
        swap_pressure=0.0,
        service_pressure=0.30,
        proof_queue_pressure=0.20,
        validation_queue_pressure=0.20,
        measured_at_epoch=time.time(),
    )

    assert scheduler.trainer_limit(resources, healthy) == 2
    assert scheduler.trainer_limit(
        resources,
        HParamResourcePressure(**{**healthy.to_dict(), "service_pressure": 0.95}),
    ) == 1
    assert scheduler.trainer_limit(resources, None) == 1
