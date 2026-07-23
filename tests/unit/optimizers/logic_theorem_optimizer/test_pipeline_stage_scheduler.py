"""Contracts for resource-aware scheduling of the LegalIR pipeline DAG."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.pipeline_stage_scheduler import (
    DGX_SPARK_INITIAL_STAGE_LIMITS,
    PipelineSchedulerSignals,
    PipelineStage,
    PipelineStageScheduler,
    PipelineTask,
    StageResourceRequest,
    build_canonical_pipeline_dag,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler,
    LeaseTimeoutError,
    ResourceSchedulerConfig,
)


def _resources(
    *,
    cpu: int = 1,
    memory: int = 16,
    unified: int = 0,
    gpu: int = 0,
    children: int = 1,
    requires_gpu: bool = False,
) -> StageResourceRequest:
    return StageResourceRequest(
        cpu_slots=cpu,
        memory_mb=memory,
        unified_memory_mb=unified,
        gpu_memory_mb=gpu,
        child_process_slots=children,
        requires_gpu=requires_gpu,
    )


def _resource_scheduler(
    state_path: Path,
    *,
    cpu: int = 32,
    memory: int = 16 * 1024,
    unified_memory: int = 16 * 1024,
    gpu_memory: int = 16 * 1024,
    child_processes: int = 64,
) -> GlobalResourceScheduler:
    return GlobalResourceScheduler(
        ResourceSchedulerConfig(
            total_cpu_slots=cpu,
            total_memory_mb=memory,
            total_unified_memory_mb=unified_memory,
            total_gpu_memory_mb=gpu_memory,
            total_child_process_slots=child_processes,
            lane_reservations={},
            state_path=state_path,
            auto_renew_leases=False,
            require_known_gpu_for_gpu_work=False,
        )
    )


def _stage_counts(admissions) -> Counter[PipelineStage]:
    return Counter(admission.task.stage for admission in admissions)


def test_canonical_dag_has_all_stages_and_explicit_dependencies() -> None:
    tasks = build_canonical_pipeline_dag(prefix="cycle-17")
    by_stage = {task.stage: task for task in tasks}

    assert len(tasks) == 8
    assert set(by_stage) == set(PipelineStage)
    assert [stage.value for stage in PipelineStage] == [
        "canonical_trainer",
        "snapshot_evaluation",
        "hammer",
        "leanstral_service",
        "codex_generation",
        "validation",
        "persistence",
        "merge",
    ]
    assert by_stage[PipelineStage.CANONICAL_TRAINER].dependencies == ()
    assert by_stage[PipelineStage.SNAPSHOT_EVALUATION].dependencies == (
        by_stage[PipelineStage.CANONICAL_TRAINER].task_id,
    )
    assert by_stage[PipelineStage.HAMMER].dependencies == (
        by_stage[PipelineStage.SNAPSHOT_EVALUATION].task_id,
    )
    assert by_stage[PipelineStage.LEANSTRAL_SERVICE].dependencies == (
        by_stage[PipelineStage.SNAPSHOT_EVALUATION].task_id,
    )
    assert set(by_stage[PipelineStage.CODEX_GENERATION].dependencies) == {
        by_stage[PipelineStage.HAMMER].task_id,
        by_stage[PipelineStage.LEANSTRAL_SERVICE].task_id,
    }
    assert by_stage[PipelineStage.VALIDATION].dependencies == (
        by_stage[PipelineStage.CODEX_GENERATION].task_id,
    )
    assert by_stage[PipelineStage.PERSISTENCE].dependencies == (
        by_stage[PipelineStage.VALIDATION].task_id,
    )
    assert by_stage[PipelineStage.MERGE].dependencies == (
        by_stage[PipelineStage.PERSISTENCE].task_id,
    )
    assert {
        task.stage for task in tasks if task.canonical_write
    } == {
        PipelineStage.CANONICAL_TRAINER,
        PipelineStage.PERSISTENCE,
        PipelineStage.MERGE,
    }


def test_run_executes_dependency_dag_and_passes_results(tmp_path: Path) -> None:
    scheduler = PipelineStageScheduler(
        resource_scheduler=_resource_scheduler(tmp_path / "resources.json")
    )
    tasks = build_canonical_pipeline_dag(prefix="run")
    for task in tasks:
        scheduler.submit(task)

    calls: list[tuple[PipelineStage, str]] = []

    def handler(task: PipelineTask):
        calls.append((task.stage, task.task_id))
        return {"task_id": task.task_id, "stage": task.stage.value}

    results = scheduler.run({stage: handler for stage in PipelineStage})
    positions = {stage: index for index, (stage, _) in enumerate(calls)}

    assert set(results) == {task.task_id for task in tasks}
    for task in tasks:
        for dependency in task.dependencies:
            dependency_stage = next(item.stage for item in tasks if item.task_id == dependency)
            assert positions[dependency_stage] < positions[task.stage]
    assert scheduler.snapshot()["active_admission_count"] == 0


def test_healthy_initial_admission_matches_dgx_spark_roles(tmp_path: Path) -> None:
    scheduler = PipelineStageScheduler(
        resource_scheduler=_resource_scheduler(tmp_path / "resources.json", cpu=32),
        signals=PipelineSchedulerSignals(),
    )
    expected = {
        PipelineStage.CANONICAL_TRAINER: 1,
        PipelineStage.LEANSTRAL_SERVICE: 1,
        PipelineStage.CODEX_GENERATION: 6,
        PipelineStage.VALIDATION: 4,
        PipelineStage.HAMMER: 2,
    }
    assert {stage: DGX_SPARK_INITIAL_STAGE_LIMITS[stage] for stage in expected} == expected

    for stage, count in expected.items():
        for index in range(count + 3):
            scheduler.submit(
                PipelineTask(
                    task_id=f"{stage.value}-{index}",
                    stage=stage,
                    resources=_resources(),
                )
            )

    admissions = scheduler.admit_ready()
    counts = _stage_counts(admissions)
    assert {stage: counts[stage] for stage in expected} == expected
    assert len({admission.task_id for admission in admissions}) == len(admissions)

    snapshot = scheduler.resource_scheduler.snapshot()
    assert snapshot["allocated"]["cpu_slots"] == len(admissions)
    assert snapshot["allocated_child_process_slots"] == len(admissions)
    for admission in admissions:
        scheduler.complete(admission.task_id)
    assert scheduler.resource_scheduler.snapshot()["active_lease_count"] == 0


def test_global_resource_budget_limits_admission_and_is_released(tmp_path: Path) -> None:
    resources = _resource_scheduler(
        tmp_path / "resources.json",
        cpu=3,
        memory=300,
        child_processes=3,
    )
    scheduler = PipelineStageScheduler(resource_scheduler=resources)
    for index in range(6):
        scheduler.submit(
            PipelineTask(
                task_id=f"codex-{index}",
                stage=PipelineStage.CODEX_GENERATION,
                resources=_resources(cpu=1, memory=100, children=1),
            )
        )

    first = scheduler.admit_ready()
    assert len(first) == 3
    snapshot = resources.snapshot()
    assert snapshot["allocated"] == {"cpu_slots": 3, "memory_mb": 300}
    assert snapshot["allocated_child_process_slots"] == 3
    assert scheduler.admit_ready() == ()

    scheduler.complete(first[0].task_id)
    replacement = scheduler.admit_ready()
    assert len(replacement) == 1
    for admission in (*first[1:], *replacement):
        scheduler.complete(admission.task_id)
    assert resources.snapshot()["active_lease_count"] == 0


def test_unified_gpu_and_child_budgets_are_one_global_envelope(tmp_path: Path) -> None:
    resources = _resource_scheduler(
        tmp_path / "resources.json",
        memory=1024,
        unified_memory=1024,
        gpu_memory=512,
        child_processes=4,
    )
    scheduler = PipelineStageScheduler(resource_scheduler=resources)
    for index in range(3):
        scheduler.submit(
            PipelineTask(
                task_id=f"gpu-codex-{index}",
                stage=PipelineStage.CODEX_GENERATION,
                resources=_resources(
                    memory=128,
                    unified=600,
                    gpu=300,
                    children=3,
                    requires_gpu=True,
                ),
            )
        )

    # The Codex lane would admit six workers, but any second request exceeds
    # all three host-global envelopes. Releasing is required before replacement.
    first = scheduler.admit_ready()
    assert len(first) == 1
    snapshot = resources.snapshot()
    assert snapshot["allocated_unified_memory_mb"] == 600
    assert snapshot["allocated_gpu_memory_mb"] == 300
    assert snapshot["allocated_child_process_slots"] == 3
    assert scheduler.admit_ready() == ()
    scheduler.complete(first[0].task_id)
    second = scheduler.admit_ready()
    assert len(second) == 1
    scheduler.complete(second[0].task_id)


def test_nested_solver_children_share_parent_process_and_memory_envelope(
    tmp_path: Path,
) -> None:
    resources = _resource_scheduler(
        tmp_path / "resources.json",
        cpu=4,
        memory=1024,
        unified_memory=1024,
        child_processes=8,
    )
    scheduler = PipelineStageScheduler(resource_scheduler=resources)
    scheduler.submit(
        PipelineTask(
            "hammer-root",
            PipelineStage.HAMMER,
            resources=_resources(cpu=2, memory=512, unified=600, children=4),
        )
    )
    root = scheduler.admit_ready()[0]
    first = root.lease.acquire_child(
        cpu_slots=1,
        memory_mb=256,
        unified_memory_mb=300,
        child_process_slots=2,
        timeout=0,
    )
    second = root.lease.acquire_child(
        cpu_slots=1,
        memory_mb=256,
        unified_memory_mb=300,
        child_process_slots=2,
        timeout=0,
    )
    snapshot = resources.snapshot()
    assert snapshot["allocated"] == {"cpu_slots": 2, "memory_mb": 512}
    assert snapshot["allocated_unified_memory_mb"] == 600
    assert snapshot["allocated_child_process_slots"] == 4
    assert snapshot["active_child_lease_count"] == 2
    with pytest.raises(LeaseTimeoutError):
        root.lease.acquire_child(
            cpu_slots=1,
            unified_memory_mb=1,
            child_process_slots=1,
            timeout=0,
        )
    first.release()
    second.release()
    scheduler.complete(root.task_id)


def test_canonical_writes_never_overlap_even_across_stages(tmp_path: Path) -> None:
    scheduler = PipelineStageScheduler(
        resource_scheduler=_resource_scheduler(tmp_path / "resources.json")
    )
    canonical = (
        PipelineTask("trainer", PipelineStage.CANONICAL_TRAINER, resources=_resources()),
        PipelineTask("persist", PipelineStage.PERSISTENCE, resources=_resources()),
        PipelineTask("merge", PipelineStage.MERGE, resources=_resources()),
    )
    scheduler.submit(PipelineTask("codex", PipelineStage.CODEX_GENERATION, resources=_resources()))
    for task in canonical:
        scheduler.submit(task)

    first = scheduler.admit_ready()
    active_writes = [item for item in first if item.task.canonical_write]
    assert len(active_writes) == 1
    assert any(item.task_id == "codex" for item in first)

    # Finishing unrelated read/worktree work cannot admit a second canonical writer.
    scheduler.complete("codex")
    assert not any(item.task.canonical_write for item in scheduler.admit_ready())
    scheduler.complete(active_writes[0].task_id)
    next_admission = scheduler.admit_ready()
    assert sum(item.task.canonical_write for item in next_admission) == 1


def test_canonical_write_lock_is_shared_by_independent_scheduler_facades(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "resources.json"
    first = PipelineStageScheduler(resource_scheduler=_resource_scheduler(state_path))
    second = PipelineStageScheduler(resource_scheduler=_resource_scheduler(state_path))
    first.submit(
        PipelineTask("trainer", PipelineStage.CANONICAL_TRAINER, resources=_resources())
    )
    second.submit(
        PipelineTask("merge", PipelineStage.MERGE, resources=_resources())
    )

    trainer = first.admit_ready()
    assert [item.task_id for item in trainer] == ["trainer"]
    assert second.admit_ready() == ()
    first.complete("trainer")
    merge = second.admit_ready()
    assert [item.task_id for item in merge] == ["merge"]
    second.complete("merge")


def _admit_workload(
    tmp_path: Path,
    name: str,
    signals: PipelineSchedulerSignals,
) -> Counter[PipelineStage]:
    scheduler = PipelineStageScheduler(
        resource_scheduler=_resource_scheduler(tmp_path / f"{name}.json", cpu=64),
        signals=signals,
    )
    for stage in (
        PipelineStage.HAMMER,
        PipelineStage.LEANSTRAL_SERVICE,
        PipelineStage.CODEX_GENERATION,
        PipelineStage.VALIDATION,
        PipelineStage.SNAPSHOT_EVALUATION,
    ):
        for index in range(12):
            scheduler.submit(
                PipelineTask(
                    task_id=f"{name}-{stage.value}-{index}",
                    stage=stage,
                    resources=_resources(),
                )
            )
    return _stage_counts(scheduler.admit_ready())


def test_live_queue_conflict_throughput_and_resource_pressure_scale_lanes(
    tmp_path: Path,
) -> None:
    ready = {stage.value: 12 for stage in PipelineStage}
    rates = {stage.value: 1.0 for stage in PipelineStage}
    healthy = _admit_workload(
        tmp_path,
        "healthy",
        PipelineSchedulerSignals(
            ready_depth_by_stage=ready,
            service_rate_by_stage=rates,
            nested_solver_children=2,
            validation_backlog=8,
            validation_capacity=4,
            conflict_rate=0.0,
            cpu_pressure=0.65,
            memory_pressure=0.55,
            unified_memory_pressure=0.50,
            gpu_memory_pressure=0.50,
            swap_pressure=0.0,
            child_process_count=4,
            child_process_limit=64,
            disjoint_codex_scopes=6,
            accepted_patches_per_hour=6.0,
            accepted_patch_target_per_hour=4.0,
        ),
    )
    pressured = _admit_workload(
        tmp_path,
        "pressured",
        PipelineSchedulerSignals(
            ready_depth_by_stage=ready,
            service_rate_by_stage=rates,
            nested_solver_children=50,
            validation_backlog=24,
            validation_capacity=2,
            conflict_rate=0.30,
            cpu_pressure=0.94,
            memory_pressure=0.94,
            unified_memory_pressure=0.94,
            gpu_memory_pressure=0.94,
            swap_pressure=0.05,
            child_process_count=58,
            child_process_limit=64,
            disjoint_codex_scopes=6,
            accepted_patches_per_hour=0.0,
            accepted_patch_target_per_hour=4.0,
        ),
    )

    assert sum(pressured.values()) < sum(healthy.values())
    assert pressured[PipelineStage.CODEX_GENERATION] < healthy[PipelineStage.CODEX_GENERATION]
    assert pressured[PipelineStage.HAMMER] <= healthy[PipelineStage.HAMMER]
    assert pressured[PipelineStage.VALIDATION] <= 2
    assert healthy[PipelineStage.VALIDATION] == 4
    assert healthy[PipelineStage.LEANSTRAL_SERVICE] == 1
    assert pressured[PipelineStage.LEANSTRAL_SERVICE] <= 1


def test_signal_update_reacts_to_validation_backlog_and_disjoint_scopes(
    tmp_path: Path,
) -> None:
    scheduler = PipelineStageScheduler(
        resource_scheduler=_resource_scheduler(tmp_path / "resources.json", cpu=32),
        signals=PipelineSchedulerSignals(
            ready_depth_by_stage={
                PipelineStage.CODEX_GENERATION.value: 10,
                PipelineStage.VALIDATION.value: 10,
            },
            validation_backlog=10,
            validation_capacity=1,
            disjoint_codex_scopes=2,
        ),
    )
    for stage in (PipelineStage.CODEX_GENERATION, PipelineStage.VALIDATION):
        for index in range(10):
            scheduler.submit(
                PipelineTask(
                    task_id=f"{stage.value}-{index}",
                    stage=stage,
                    resources=_resources(),
                )
            )

    first = scheduler.admit_ready()
    counts = _stage_counts(first)
    assert counts[PipelineStage.CODEX_GENERATION] <= 2
    assert counts[PipelineStage.VALIDATION] <= 1
    for admission in first:
        scheduler.complete(admission.task_id)

    scheduler.update_signals(
        PipelineSchedulerSignals(
            ready_depth_by_stage={
                PipelineStage.CODEX_GENERATION.value: 8,
                PipelineStage.VALIDATION.value: 8,
            },
            validation_backlog=8,
            validation_capacity=4,
            disjoint_codex_scopes=6,
        )
    )
    second = _stage_counts(scheduler.admit_ready())
    assert second[PipelineStage.CODEX_GENERATION] > counts[PipelineStage.CODEX_GENERATION]
    assert second[PipelineStage.VALIDATION] > counts[PipelineStage.VALIDATION]


def test_failed_dependency_blocks_all_descendants(tmp_path: Path) -> None:
    scheduler = PipelineStageScheduler(
        resource_scheduler=_resource_scheduler(tmp_path / "resources.json")
    )
    tasks = build_canonical_pipeline_dag(prefix="failure")
    by_stage = {task.stage: task for task in tasks}
    for task in tasks:
        scheduler.submit(task)

    trainer = scheduler.admit_ready()
    assert [item.task.stage for item in trainer] == [PipelineStage.CANONICAL_TRAINER]
    scheduler.complete(trainer[0].task_id)
    snapshot = scheduler.admit_ready()
    assert [item.task.stage for item in snapshot] == [PipelineStage.SNAPSHOT_EVALUATION]
    scheduler.complete(snapshot[0].task_id)
    branches = scheduler.admit_ready()
    assert {item.task.stage for item in branches} == {
        PipelineStage.HAMMER,
        PipelineStage.LEANSTRAL_SERVICE,
    }
    for admission in branches:
        if admission.task.stage is PipelineStage.HAMMER:
            scheduler.fail(admission.task_id, "solver child crashed")
        else:
            scheduler.complete(admission.task_id)

    assert scheduler.admit_ready() == ()
    assert by_stage[PipelineStage.CODEX_GENERATION] not in scheduler.ready_tasks()
    state = scheduler.snapshot()
    assert state["tasks"][by_stage[PipelineStage.HAMMER].task_id]["status"] == "failed"
    assert state["tasks"][by_stage[PipelineStage.CODEX_GENERATION].task_id]["status"] == "blocked"


def test_duplicate_and_unknown_dependency_are_rejected(tmp_path: Path) -> None:
    scheduler = PipelineStageScheduler(
        resource_scheduler=_resource_scheduler(tmp_path / "resources.json")
    )
    scheduler.submit(PipelineTask("known", PipelineStage.HAMMER, resources=_resources()))

    with pytest.raises(ValueError, match="duplicate"):
        scheduler.submit(PipelineTask("known", PipelineStage.HAMMER, resources=_resources()))
    with pytest.raises(ValueError, match="unknown dependency"):
        scheduler.submit(
            PipelineTask(
                "orphan",
                PipelineStage.CODEX_GENERATION,
                dependencies=("missing",),
                resources=_resources(),
            )
        )
