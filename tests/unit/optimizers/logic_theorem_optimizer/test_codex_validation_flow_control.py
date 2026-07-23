"""End-to-end Codex generation, validation, and merge flow-control contracts."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.codex_scope_scheduler import (
    CodexFlowControlSignals,
    CodexPatchThroughputLedger,
    CodexScopeTask,
    CodexServiceRates,
    CodexValidationMergeFlowController,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.incremental_validation import (
    ChangedScopeValidationPlan,
    IncrementalCandidateValidator,
    TransientValidationError,
    ValidationBoundary,
)


def _task(
    task_id: str,
    scope: str,
    *,
    priority: float = 1.0,
    path: str,
    ready: bool = True,
) -> CodexScopeTask:
    return CodexScopeTask(
        task_id=task_id,
        scope=scope,
        priority=priority,
        correlation_key=task_id,
        explicit_paths=(path,),
        readiness_verified=ready,
        readiness_evidence=("dependency-gate",) if ready else (),
        ready_blockers=() if ready else ("dependency-not-confirmed",),
    )


def test_flow_controller_starts_only_ready_disjoint_work_sized_to_downstream_rates() -> None:
    controller = CodexValidationMergeFlowController(max_workers=4)
    tasks = [
        _task("blocked", "compiler_parser", priority=20, path="compiler.py", ready=False),
        _task("deontic", "deontic", priority=10, path="deontic.py"),
        _task("cec", "CEC", priority=9, path="cec.py"),
        _task("kg", "KG", priority=8, path="kg.py"),
    ]

    flow = controller.schedule(
        tasks,
        service_rates=CodexServiceRates(
            generation_patches_per_hour_per_worker=2.0,
            validation_patches_per_hour=5.0,
            merge_patches_per_hour=20.0,
            validation_utilization_target=0.80,
            merge_utilization_target=0.80,
        ),
    )

    assert flow.flow_decision.effective_workers == 2
    assert "validation_service_rate_bottleneck" in flow.flow_decision.reasons
    assert flow.worker_count == 2
    assert {assignment.scope for assignment in flow.assignments} == {"deontic", "cec"}
    assert all(assignment.bundle.readiness_verified for assignment in flow.assignments)
    assert all(
        not left.write_set.conflicts_with(right.write_set)
        for index, left in enumerate(flow.assignments)
        for right in flow.assignments[index + 1 :]
    )
    assert "readiness_not_verified" in flow.deferred.values()


def test_flow_controller_pauses_on_validation_backlog_and_conflict_growth() -> None:
    controller = CodexValidationMergeFlowController(max_workers=4)
    tasks = [
        _task("deontic", "deontic", path="deontic.py"),
        _task("cec", "CEC", path="cec.py"),
    ]

    validation_blocked = controller.schedule(
        tasks,
        signals=CodexFlowControlSignals(ready_depth=2, validation_backlog=8),
    )
    conflict_blocked = controller.schedule(
        tasks,
        signals=CodexFlowControlSignals(ready_depth=2, conflict_growth_rate=0.4),
    )

    assert validation_blocked.worker_count == 0
    assert validation_blocked.flow_decision.paused
    assert "validation_backlog" in validation_blocked.flow_decision.reasons
    assert set(validation_blocked.deferred.values()) == {"validation_backlog"}
    assert conflict_blocked.worker_count == 0
    assert "conflict_growth" in conflict_blocked.flow_decision.reasons


def test_primary_throughput_counts_next_cycle_confirmed_patches_not_claims_or_diffs() -> None:
    ledger = CodexPatchThroughputLedger()
    ledger.record(claimed_tasks=100, generated_diffs=80, validation_accepted=10, merged_patches=7)

    assert ledger.accepted_next_cycle_confirmed_patches_per_hour(
        wall_clock_seconds=1800.0
    ) == 0.0

    ledger.record(next_cycle_confirmed_patches=3)
    snapshot = ledger.to_dict(wall_clock_seconds=3600.0)

    assert snapshot["primary_throughput_metric"] == (
        "accepted_next_cycle_confirmed_patches_per_hour"
    )
    assert snapshot["accepted_next_cycle_confirmed_patches_per_hour"] == 3.0


def test_transient_validation_rescue_does_not_poison_semantic_statistics() -> None:
    plan = ChangedScopeValidationPlan(
        boundary=ValidationBoundary.CANDIDATE,
        changed_files=("ipfs_datasets_py/logic/modal/codec.py",),
        typed_ast_scopes=(),
        focused_tests=(),
        legal_ir_families=(),
        replay_samples=(),
        mutation_cases=("invert_modality",),
        proof_obligations=(),
    )
    attempts = {"syntax": 0, "mutation:invert_modality": 0}

    def syntax(request):
        attempts[request.check_id] += 1
        if request.attempt == 1:
            raise TransientValidationError("temporary isolated worker loss")
        return True

    def deterministic_mutation_failure(request):
        attempts[request.check_id] += 1
        return {"accepted": False, "error": "mutant survived"}

    report = IncrementalCandidateValidator(max_transient_retries=2).validate(
        plan,
        {
            "syntax": syntax,
            "mutation:invert_modality": deterministic_mutation_failure,
        },
    )

    assert not report.accepted
    assert report.transient_rescued_check_ids == ("syntax",)
    assert report.transient_unresolved_check_ids == ()
    assert report.semantic_failure_check_ids == ("mutation:invert_modality",)
    assert report.semantic_statistics_update_allowed
    assert report.semantic_statistics_delta["poison_semantic_statistics"] is False


def test_unresolved_transient_validation_failure_is_excluded_from_semantic_stats() -> None:
    plan = ChangedScopeValidationPlan(
        boundary=ValidationBoundary.CANDIDATE,
        changed_files=("ipfs_datasets_py/logic/modal/codec.py",),
        typed_ast_scopes=(),
        focused_tests=(),
        legal_ir_families=(),
        replay_samples=(),
        mutation_cases=(),
        proof_obligations=(),
    )

    report = IncrementalCandidateValidator(max_transient_retries=1).validate(
        plan,
        {"syntax": lambda request: (_ for _ in ()).throw(TransientValidationError("timeout"))},
    )

    assert not report.accepted
    assert report.transient_unresolved_check_ids == ("syntax",)
    assert report.semantic_failure_check_ids == ()
    assert not report.semantic_statistics_update_allowed
