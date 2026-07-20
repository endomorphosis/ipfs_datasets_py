"""Contracts for conflict-aware Codex scope scheduling and merge serialization."""

from __future__ import annotations

import threading
import time

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.codex_scope_scheduler import (
    CODEX_OWNERSHIP_SCOPES,
    MAX_INITIAL_CODEX_WORKERS,
    AdaptiveWorkerController,
    CodexOwnershipScope,
    CodexScopeScheduler,
    CodexScopeTask,
    ConflictAwareMergeSerializer,
    IsolatedValidationExecutor,
    PredictedWriteSet,
    SchedulerOutcome,
    SchedulerSignals,
    ScopeAssignment,
    ScopeEvidenceBundle,
    ScopeEvidenceBundler,
    WriteSetPredictor,
    canonical_codex_scope,
)


def _task(
    task_id: str,
    scope: str,
    *,
    priority: float = 1.0,
    correlation: str = "",
    paths: tuple[str, ...] = (),
) -> CodexScopeTask:
    return CodexScopeTask(
        task_id=task_id,
        scope=scope,
        priority=priority,
        correlation_key=correlation or task_id,
        explicit_paths=paths,
    )


def _assignment(
    assignment_id: str,
    scope: str,
    paths: tuple[str, ...],
) -> ScopeAssignment:
    task = _task(assignment_id, scope)
    bundle = ScopeEvidenceBundle(
        bundle_id=f"bundle-{assignment_id}",
        scope=task.scope,
        correlation_key=task.correlation_key,
        tasks=(task,),
        write_set=PredictedWriteSet(paths=paths),
        priority=task.priority,
    )
    return ScopeAssignment(assignment_id, f"worker-{assignment_id}", bundle)


def test_acceptance_scope_catalog_and_aliases_are_canonical() -> None:
    assert len(CODEX_OWNERSHIP_SCOPES) == 9
    assert set(CODEX_OWNERSHIP_SCOPES) == {
        "compiler_parser",
        "compiler_registry",
        "ir_decompiler",
        "deontic",
        "frame_logic",
        "tdfol",
        "knowledge_graphs",
        "cec",
        "external_provers",
    }
    assert canonical_codex_scope("TDFOL") == "tdfol"
    assert canonical_codex_scope("KG") == "knowledge_graphs"
    assert canonical_codex_scope("CEC") == "cec"
    assert canonical_codex_scope("external_prover") == "external_provers"
    assert CodexOwnershipScope.coerce("compiler_ambiguity") is CodexOwnershipScope.COMPILER_REGISTRY


def test_task_normalization_reads_existing_modal_todo_metadata() -> None:
    task = CodexScopeTask.from_value(
        {
            "todo_id": "todo-1",
            "action": "repair_tdfol_bridge_parse",
            "priority": 7,
            "sample_ids": ["sample-a"],
            "metadata": {
                "program_synthesis_scope": "TDFOL",
                "semantic_bundle_key": "tdfol:parse",
                "allowed_paths": ["ipfs_datasets_py/logic/TDFOL/tdfol_parser.py"],
                "validation_commands": ["python -m pytest tests/unit/logic/TDFOL"],
            },
        }
    )
    assert task.task_id == "todo-1"
    assert task.scope == "tdfol"
    assert task.correlation_key == "tdfol:parse"
    assert task.explicit_paths == ("ipfs_datasets_py/logic/TDFOL/tdfol_parser.py",)
    assert task.validation_commands == ("python -m pytest tests/unit/logic/TDFOL",)


def test_correlated_evidence_is_bundled_only_within_one_scope() -> None:
    bundles = ScopeEvidenceBundler().bundle(
        [
            _task("d-1", "deontic", priority=5, correlation="contract-9"),
            _task("d-2", "deontic", priority=4, correlation="contract-9"),
            _task("c-1", "CEC", priority=3, correlation="contract-9"),
        ]
    )
    assert len(bundles) == 2
    deontic = next(bundle for bundle in bundles if bundle.scope == "deontic")
    assert deontic.task_ids == ("d-1", "d-2")
    assert all(task.scope == deontic.scope for task in deontic.tasks)


def test_bundling_is_deterministic_and_bounded() -> None:
    tasks = [_task(f"t-{index}", "deontic", correlation="same") for index in range(5)]
    bundler = ScopeEvidenceBundler(max_tasks=2)
    first = bundler.bundle(reversed(tasks))
    second = bundler.bundle(tasks)
    assert [bundle.bundle_id for bundle in first] == [bundle.bundle_id for bundle in second]
    assert sorted(len(bundle.tasks) for bundle in first) == [1, 2, 2]


def test_write_set_predictor_includes_explicit_and_owned_paths() -> None:
    predicted = WriteSetPredictor().predict(
        _task(
            "parser",
            "compiler_parser",
            paths=("tests/unit/custom_parser_contract.py",),
        )
    )
    assert "tests/unit/custom_parser_contract.py" in predicted.paths
    assert "ipfs_datasets_py/logic/modal/compiler.py" in predicted.paths
    assert set(predicted.sources) == {"scope_ownership", "task"}
    assert predicted.unknown is False


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (("pkg/shared.py",), ("pkg/shared.py",)),
        (("pkg/**",), ("pkg/nested/file.py",)),
    ],
)
def test_write_set_conflicts_cover_exact_and_directory_patterns(left, right) -> None:
    assert PredictedWriteSet(paths=left).conflicts_with(PredictedWriteSet(paths=right))


def test_typed_symbol_conflicts_are_detected_without_path_overlap() -> None:
    left = PredictedWriteSet(paths=("a.py",), symbols=("Registry.modal_rules",))
    right = PredictedWriteSet(paths=("b.py",), symbols=("Registry.modal_rules",))
    assert left.conflicts_with(right)


def test_scheduler_starts_at_most_four_unique_disjoint_scopes() -> None:
    tasks = [
        _task(f"task-{scope}", scope, priority=20 - index)
        for index, scope in enumerate(CODEX_OWNERSHIP_SCOPES)
    ]
    plan = CodexScopeScheduler().schedule(tasks)
    assert plan.worker_count == MAX_INITIAL_CODEX_WORKERS
    assert len({assignment.scope for assignment in plan.assignments}) == plan.worker_count
    for index, assignment in enumerate(plan.assignments):
        assert all(
            not assignment.write_set.conflicts_with(other.write_set)
            for other in plan.assignments[index + 1 :]
        )
    assert set(plan.deferred.values()) == {"worker_limit"}


def test_scheduler_defers_shared_file_and_active_write_conflicts() -> None:
    shared = "ipfs_datasets_py/logic/bridge/shared_contract.py"
    tasks = [
        _task("parser", "compiler_parser", priority=9, paths=(shared,)),
        _task("deontic", "deontic", priority=8, paths=(shared,)),
        _task("cec", "CEC", priority=7),
    ]
    active = PredictedWriteSet(paths=("ipfs_datasets_py/logic/CEC/**",))
    plan = CodexScopeScheduler().schedule(tasks, active_write_sets=(active,))
    assert [item.scope for item in plan.assignments] == ["compiler_parser"]
    assert "predicted_write_conflict" in plan.deferred.values()
    assert "active_write_conflict" in plan.deferred.values()


@pytest.mark.parametrize(
    "signals,reason",
    [
        (SchedulerSignals(validation_failure_rate=0.3), "validation_failures"),
        (SchedulerSignals(apply_conflict_rate=0.2), "apply_conflicts"),
        (SchedulerSignals(memory_pressure=0.9), "memory_pressure"),
        (SchedulerSignals(transient_failure_rate=0.3), "transient_failures"),
    ],
)
def test_adaptive_controller_reduces_each_required_pressure(signals, reason) -> None:
    decision = AdaptiveWorkerController().recommend(signals)
    assert decision.effective_workers < MAX_INITIAL_CODEX_WORKERS
    assert reason in decision.reasons


def test_adaptive_controller_uses_severe_memory_pressure_as_single_worker_gate() -> None:
    decision = AdaptiveWorkerController().recommend(SchedulerSignals(memory_pressure=0.97))
    assert decision.effective_workers == 1


def test_adaptive_controller_recovers_slowly_after_healthy_outcomes() -> None:
    controller = AdaptiveWorkerController(recovery_successes=2, window_size=2)
    reduced = controller.observe(SchedulerOutcome(validation_failed=True))
    assert reduced.effective_workers < 4
    before = reduced.effective_workers
    controller.observe(SchedulerOutcome(accepted=True))
    recovered = controller.observe(SchedulerOutcome(accepted=True))
    assert recovered.effective_workers == min(4, before + 1)


def test_isolated_validation_runs_distinct_worktrees_concurrently(tmp_path) -> None:
    assignments = [
        _assignment("a", "deontic", ("a.py",)).with_worktree(tmp_path / "a"),
        _assignment("b", "CEC", ("b.py",)).with_worktree(tmp_path / "b"),
        _assignment("c", "KG", ("c.py",)).with_worktree(tmp_path / "c"),
    ]
    lock = threading.Lock()
    active = 0
    maximum = 0

    def validate(assignment):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.04)
        with lock:
            active -= 1
        return {"passed": True, "worktree": assignment.worktree_path}

    results = IsolatedValidationExecutor(max_workers=3).validate(assignments, validate)
    assert maximum >= 2
    assert all(result.accepted for result in results.values())
    assert {result.evidence["worktree"] for result in results.values()} == {
        str(tmp_path / "a"),
        str(tmp_path / "b"),
        str(tmp_path / "c"),
    }


def test_isolated_validation_rejects_reused_or_missing_worktrees(tmp_path) -> None:
    assignments = [
        _assignment("a", "deontic", ("a.py",)).with_worktree(tmp_path / "same"),
        _assignment("b", "CEC", ("b.py",)).with_worktree(tmp_path / "same"),
    ]
    with pytest.raises(ValueError, match="distinct worktree"):
        IsolatedValidationExecutor().validate(assignments, lambda _: True)


def test_overlapping_merges_are_serialized() -> None:
    assignments = [
        _assignment("a", "deontic", ("shared.py",)),
        _assignment("b", "CEC", ("shared.py",)),
    ]
    lock = threading.Lock()
    active = 0
    maximum = 0

    def merge(_assignment):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.04)
        with lock:
            active -= 1
        return True

    serializer = ConflictAwareMergeSerializer()
    results = serializer.merge(assignments, merge, max_workers=2)
    assert maximum == 1
    assert all(result.status == "merged" for result in results.values())
    assert serializer.telemetry()["contended_acquisitions"] >= 1


def test_disjoint_merges_may_progress_together() -> None:
    assignments = [
        _assignment("a", "deontic", ("a.py",)),
        _assignment("b", "CEC", ("b.py",)),
    ]
    barrier = threading.Barrier(2)

    def merge(_assignment):
        barrier.wait(timeout=1.0)
        return {"passed": True}

    serializer = ConflictAwareMergeSerializer()
    results = serializer.merge(assignments, merge, max_workers=2)
    assert all(result.accepted for result in results.values())
    assert serializer.telemetry()["max_parallel_merges"] == 2


def test_validation_and_merge_callbacks_fail_closed() -> None:
    assignment = _assignment("a", "deontic", ("a.py",)).with_worktree("worktree-a")

    def explode(_assignment):
        raise RuntimeError("boom")

    validation = IsolatedValidationExecutor().validate([assignment], explode)
    merge = ConflictAwareMergeSerializer().merge([assignment], explode)
    assert validation["a"].accepted is False
    assert "RuntimeError" in validation["a"].error
    assert merge["a"].accepted is False
    assert merge["a"].status == "failed"


def test_daemon_default_initial_wave_uses_conflict_aware_four_worker_cap() -> None:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
        uscode_modal_daemon_runner as runner,
    )

    args = runner.build_uscode_modal_daemon_arg_parser().parse_args(
        [
            "--run-id",
            "scope-scheduler",
            "--duration-seconds",
            "1",
            "--loop-role",
            "paired",
            "--codex-parallel-scopes",
            "all",
        ]
    )
    paired = runner.build_paired_daemon_commands(args, module_name=runner.__name__)
    children = paired["codex_children"]
    assert len(children) == MAX_INITIAL_CODEX_WORKERS
    assert len({child["ownership_scope"] for child in children}) == len(children)
    assert all(child["predicted_write_set"]["unknown"] is False for child in children)
    assert paired["codex_scope_schedule"]["enabled"] is True


def test_daemon_initial_wave_uses_recent_failure_rates_to_reduce_workers() -> None:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
        uscode_modal_daemon_runner as runner,
    )

    args = runner.build_uscode_modal_daemon_arg_parser().parse_args(
        [
            "--run-id",
            "scope-scheduler-backoff",
            "--duration-seconds",
            "1",
            "--loop-role",
            "paired",
            "--codex-parallel-scopes",
            "all",
            "--codex-validation-failure-rate",
            "0.3",
        ]
    )
    paired = runner.build_paired_daemon_commands(args, module_name=runner.__name__)
    assert len(paired["codex_children"]) == 3
    decision = paired["codex_scope_schedule"]["worker_decision"]
    assert decision["effective_workers"] == 3
    assert "validation_failures" in decision["reasons"]
