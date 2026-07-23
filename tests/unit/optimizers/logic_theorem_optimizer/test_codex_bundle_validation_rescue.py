"""Integrated contracts for Codex TODO bundles and failed-validation rescue."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.codex_scope_scheduler import (
    CodexScopeScheduler,
    CodexScopeTask,
    ConflictAwareMergeSerializer,
    ScopeEvidenceBundler,
    WriteSetPredictor,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.incremental_validation import (
    ChangedScopeValidationPlan,
    IncrementalCandidateValidator,
    IncrementalValidationStage,
    TransientValidationError,
    ValidationBoundary,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.program_synthesis_failures import (
    ValidationRescueOperations,
    ValidationRescueStatus,
    ValidationWorktreeRescueCoordinator,
    ValidationWorktreeRescueRequest,
)


def _rich_task(
    task_id: str,
    *,
    scope: str = "compiler_parser",
    ast: str = "compiler.rule",
    family: str = "deontic",
    path: str = "ipfs_datasets_py/logic/modal/compiler.py",
    validations: tuple[str, ...] = ("pytest focused", "python -m compileall"),
    ready: bool = True,
    throughput: float = 0.0,
    priority: float = 1.0,
) -> CodexScopeTask:
    return CodexScopeTask(
        task_id=task_id,
        scope=scope,
        priority=priority,
        correlation_key=task_id,
        explicit_paths=(path,),
        validation_commands=validations,
        readiness_verified=ready,
        ready_blockers=() if ready else ("proof-not-verified",),
        ast_ownership=(ast,),
        logic_families=(family,),
        observed_confirmed_patches_per_hour=throughput,
    )


def _bundler() -> ScopeEvidenceBundler:
    return ScopeEvidenceBundler(
        predictor=WriteSetPredictor(include_scope_defaults=False), max_tasks=8
    )


def _candidate_plan() -> ChangedScopeValidationPlan:
    return ChangedScopeValidationPlan(
        boundary=ValidationBoundary.CANDIDATE,
        changed_files=("ipfs_datasets_py/logic/modal/compiler.py",),
        typed_ast_scopes=(),
        focused_tests=("tests/focused.py",),
        legal_ir_families=("deontic",),
        replay_samples=("case-1",),
        mutation_cases=(),
        proof_obligations=("modal_operator_preserved",),
    )


def test_bundles_only_verified_four_factor_compatible_todos() -> None:
    tasks = [
        _rich_task("a"),
        _rich_task("b", validations=("pytest focused", "pytest shared")),
        _rich_task("other-ast", ast="compiler.registry"),
        _rich_task("other-family", family="temporal"),
        _rich_task("other-write", path="ipfs_datasets_py/logic/modal/other.py"),
        _rich_task("blocked", ready=False),
    ]

    bundles = _bundler().bundle(tasks)
    compatible = next(bundle for bundle in bundles if set(bundle.task_ids) == {"a", "b"})

    assert compatible.ast_ownership == ("compiler.rule",)
    assert compatible.logic_families == ("deontic",)
    assert compatible.shared_validation_commands == ("pytest focused",)
    assert len(bundles) == 5
    assert next(bundle for bundle in bundles if bundle.task_ids == ("blocked",)).readiness_verified is False


def test_task_packet_aliases_and_observed_throughput_drive_selection() -> None:
    normalized = CodexScopeTask.from_value(
        {
            "task_id": "packet",
            "metadata": {
                "owned_ast_scope": "compiler.parser.rule",
                "logic_family": "deontic",
                "leanstral_verified": True,
                "allowed_paths": ["ipfs_datasets_py/logic/modal/compiler.py"],
                "validation_set": {"commands": ["pytest focused"]},
                "accepted_next_cycle_confirmed_patches_per_hour": 2.5,
            },
        }
    )
    assert normalized.scope == "compiler_parser"
    assert normalized.ast_ownership == ("compiler.parser.rule",)
    assert normalized.logic_families == ("deontic",)
    assert normalized.observed_confirmed_patches_per_hour == 2.5

    scheduled = CodexScopeScheduler(max_workers=1, bundler=_bundler()).schedule(
        [
            _rich_task("many-diffs", scope="deontic", priority=100, throughput=0.1),
            _rich_task(
                "confirmed-value",
                scope="cec",
                ast="cec.event",
                family="cec",
                path="ipfs_datasets_py/logic/CEC/event.py",
                priority=1,
                throughput=3.0,
            ),
        ]
    )
    assert scheduled.assignments[0].bundle.task_ids == ("confirmed-value",)


def test_conflicting_scopes_stay_isolated_and_failed_receipt_never_merges() -> None:
    shared_path = "ipfs_datasets_py/logic/modal/shared.py"
    plan = CodexScopeScheduler(max_workers=2, bundler=_bundler()).schedule(
        [
            _rich_task("parser", path=shared_path, priority=2),
            _rich_task(
                "deontic",
                scope="deontic",
                ast="deontic.rule",
                path=shared_path,
                priority=1,
            ),
        ]
    )
    assert plan.worker_count == 1
    assert "predicted_write_conflict" in plan.deferred.values()

    assignment = plan.assignments[0]
    calls: list[str] = []
    serializer = ConflictAwareMergeSerializer()
    rejected = serializer.merge_validated(
        [assignment],
        {assignment.assignment_id: {"accepted": False}},
        lambda item: calls.append(item.assignment_id) or True,
    )
    missing = serializer.merge_validated(
        [assignment], {}, lambda item: calls.append(item.assignment_id) or True
    )
    accepted = serializer.merge_validated(
        [assignment],
        {assignment.assignment_id: {"merge_allowed": True}},
        lambda item: calls.append(item.assignment_id) or True,
    )

    assert rejected[assignment.assignment_id].status == "validation_rejected"
    assert missing[assignment.assignment_id].error == "validation_receipt_missing"
    assert accepted[assignment.assignment_id].status == "merged"
    assert calls == [assignment.assignment_id]


def test_syntax_and_focused_preflight_short_circuit_expensive_validation() -> None:
    plan = _candidate_plan()
    calls: list[str] = []

    def callback(request):
        calls.append(request.check_id)
        return request.check_id != "test:tests/focused.py"

    report = IncrementalCandidateValidator().validate_staged(
        plan, {check_id: callback for check_id in plan.required_check_ids}
    )

    assert calls == ["syntax", "test:tests/focused.py"]
    assert not report.preflight_accepted
    assert not report.expensive_validation_started
    assert set(report.skipped_check_ids) == {
        "family:deontic",
        "replay:case-1",
        "proof:modal_operator_preserved",
    }
    assert not report.merge_allowed


def test_transient_preflight_requeues_without_quality_statistics() -> None:
    plan = _candidate_plan()

    def syntax(_request):
        raise TransientValidationError("isolated worker vanished")

    report = IncrementalCandidateValidator(max_transient_retries=1).validate_staged(
        plan,
        {
            check_id: (syntax if check_id == "syntax" else lambda _request: True)
            for check_id in plan.required_check_ids
        },
    )

    assert report.transient_requeue_required
    assert report.transient_unresolved_check_ids == ("syntax",)
    assert not report.semantic_statistics_update_allowed
    assert report.semantic_failure_check_ids == ()
    assert report.stage(IncrementalValidationStage.EXPENSIVE).status == "skipped"


def test_merge_boundary_runs_promotion_gates_last_and_authorizes_only_full_success() -> None:
    plan = ChangedScopeValidationPlan(
        boundary=ValidationBoundary.MERGE,
        changed_files=("ipfs_datasets_py/logic/modal/compiler.py",),
        typed_ast_scopes=(),
        focused_tests=("tests/focused.py",),
        legal_ir_families=("deontic",),
        replay_samples=(),
        mutation_cases=(),
        proof_obligations=(),
        complete_frozen_canary_required=True,
        complete_promotion_proofs_required=True,
    )
    calls: list[str] = []

    def passed(request):
        calls.append(request.check_id)
        return True

    report = IncrementalCandidateValidator().validate_staged(
        plan, {check_id: passed for check_id in plan.required_check_ids}
    )

    assert report.merge_allowed
    assert set(calls[-2:]) == {"frozen_canary", "promotion_proof_set"}
    assert report.stage(IncrementalValidationStage.PROMOTION).accepted


def test_failed_worktree_is_repaired_revalidated_and_preserved(tmp_path: Path) -> None:
    worktree = tmp_path / "failed-worktree"
    worktree.mkdir()
    seen_stages: list[str] = []
    coordinator = ValidationWorktreeRescueCoordinator(
        tmp_path / "evidence",
        operations=ValidationRescueOperations(
            preserve=lambda context: seen_stages.append(context.stage.value) or True,
            diagnose=lambda _context: {"status": "diagnosed", "failed_test": "test_modal"},
            repair=lambda _context: {
                "status": "repaired",
                "patch": "diff --git a/compiler.py b/compiler.py\n+fixed\n",
            },
            revalidate=lambda _context: {
                "accepted": True,
                "merge_allowed": True,
                "promotion_gates_complete": True,
            },
        ),
    )
    request = ValidationWorktreeRescueRequest(
        task_id="bundle-1",
        scope="compiler_parser",
        worktree_path=worktree,
        validation_report={"accepted": False, "semantic_statistics_update_allowed": True},
        patch="diff --git a/compiler.py b/compiler.py\n+useful original change\n",
        changed_files=("compiler.py",),
        useful_changes=("parser fix",),
    )

    outcome = coordinator.rescue(request)

    assert outcome.status is ValidationRescueStatus.REPAIRED
    assert outcome.merge_eligible and outcome.fresh_post_repair_validation
    assert outcome.preserve_worktree
    assert seen_stages == ["initial", "pre_repair", "post_repair", "post_validation"]
    assert all(Path(path).exists() for path in outcome.evidence_paths)
    patches = [path.read_text() for path in (tmp_path / "evidence").rglob("*.patch")]
    assert any("useful original change" in patch for patch in patches)
    assert any("fixed" in patch for patch in patches)
    payload = json.loads(Path(outcome.evidence_paths[-1]).read_text())
    assert payload["details"]["fresh_post_repair_validation"] is True


def test_validation_repair_is_bounded_and_still_failed_work_never_merges(tmp_path: Path) -> None:
    repairs: list[int] = []
    coordinator = ValidationWorktreeRescueCoordinator(
        tmp_path / "evidence",
        max_diagnosis_attempts=1,
        max_repair_attempts=2,
        operations=ValidationRescueOperations(
            diagnose=lambda _context: {"status": "diagnosed"},
            repair=lambda context: repairs.append(context.attempt) or {"status": "repaired"},
            revalidate=lambda _context: {"accepted": False, "error": "tests still fail"},
        ),
    )

    outcome = coordinator.rescue(
        ValidationWorktreeRescueRequest(
            "bounded",
            "deontic",
            tmp_path / "worktree",
            validation_report={"accepted": False},
            patch="useful change",
        )
    )

    assert repairs == [1, 2]
    assert outcome.status is ValidationRescueStatus.REPAIR_EXHAUSTED
    assert not outcome.merge_eligible
    assert outcome.reason == "repair_budget_exhausted"


def test_transient_failed_worktree_requeues_without_diagnosis_or_quality_update(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    coordinator = ValidationWorktreeRescueCoordinator(
        tmp_path / "evidence",
        operations=ValidationRescueOperations(
            diagnose=lambda _context: calls.append("diagnose") or True,
            requeue=lambda _context: calls.append("requeue") or {"status": "requeued"},
        ),
    )

    outcome = coordinator.handle(
        {
            "packet_id": "transient-packet",
            "scope": "cec",
            "worktree_path": str(tmp_path / "worktree"),
            "failed_validation_report": {
                "accepted": False,
                "transient_unresolved_check_ids": ["syntax"],
                "semantic_statistics_update_allowed": False,
            },
            "patch": "preserved transient diff",
        }
    )

    assert calls == ["requeue"]
    assert outcome.status is ValidationRescueStatus.REQUEUED_TRANSIENT
    assert outcome.requeued and not outcome.merge_eligible
    assert not outcome.semantic_statistics_update_allowed
    assert outcome.semantic_statistics_delta["deterministic_semantic_failure_count"] == 0


def test_new_runtime_types_are_available_from_optimizer_namespace() -> None:
    import ipfs_datasets_py.optimizers.logic_theorem_optimizer as optimizer

    assert optimizer.IncrementalValidationStage is IncrementalValidationStage
    assert optimizer.ValidationWorktreeRescueCoordinator is ValidationWorktreeRescueCoordinator
