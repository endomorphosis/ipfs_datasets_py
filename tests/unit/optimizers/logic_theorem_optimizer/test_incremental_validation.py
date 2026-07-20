"""Contracts for changed-scope incremental LegalIR candidate validation."""

from __future__ import annotations

import threading

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.incremental_validation import (
    DEFAULT_MUTATION_CASES,
    DEFAULT_PROOF_OBLIGATIONS,
    DEFAULT_REPLAY_CASES,
    ChangedScopeValidationPlan,
    FrozenBaselineEvidence,
    IncrementalCandidateValidator,
    TransientValidationError,
    TypedASTScope,
    ValidationBoundary,
    ValidationScopeCatalog,
    plan_incremental_validation,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_family_evaluator import (
    LEGAL_IR_EVALUATION_FAMILIES,
)


def test_changed_file_and_typed_ast_scope_map_every_validation_dimension() -> None:
    plan = plan_incremental_validation(
        ("ipfs_datasets_py/logic/modal/codec.py",),
        typed_ast_scopes=(
            TypedASTScope(
                path="ipfs_datasets_py/logic/modal/codec.py",
                node_type="FunctionDef",
                qualified_name="compile_temporal_deadline",
                symbols=("exception_scope",),
                legal_ir_families=("external_provers",),
                replay_samples=("backend-unavailable",),
                mutation_cases=("unsupported_modal_system",),
                proof_obligations=("proof-custom-deadline",),
                start_line=40,
                end_line=72,
            ),
        ),
    )

    assert plan.boundary is ValidationBoundary.CANDIDATE
    assert plan.is_incremental
    assert "modal_compiler" in plan.matched_rules
    assert "tdfol_temporal" in plan.matched_rules
    assert "exception" in plan.matched_rules
    assert "tests/unit_tests/logic/modal/test_leanstral_validation.py" in plan.focused_tests
    assert {"deontic", "temporal", "tdfol", "external_provers"}.issubset(
        plan.legal_ir_families
    )
    assert {"accepted-candidate", "hammer-unproved", "backend-unavailable"}.issubset(
        plan.replay_samples
    )
    assert {"invert_modality", "remove_exception", "alter_deadline"}.issubset(
        plan.mutation_cases
    )
    assert {
        "modal_operator_preserved",
        "exception_scope_preserved",
        "source_provenance_preserved",
        "proof-custom-deadline",
    }.issubset(plan.proof_obligations)
    assert plan.plan_id == plan_incremental_validation(
        ("ipfs_datasets_py/logic/modal/codec.py",),
        typed_ast_scopes=(
            {
                "path": "ipfs_datasets_py/logic/modal/codec.py",
                "kind": "FunctionDef",
                "qualname": "compile_temporal_deadline",
                "symbols": ["exception_scope"],
                "semantic_family": "external_provers",
                "replay_case_ids": ["backend-unavailable"],
                "mutation_cases": ["unsupported_modal_system"],
                "proof_obligation_ids": ["proof-custom-deadline"],
                "lineno": 40,
                "end_lineno": 72,
            },
        ),
    ).plan_id


def test_changed_test_file_is_itself_focused_and_unknown_code_fails_closed_to_full_scope() -> None:
    test_plan = plan_incremental_validation(
        ("tests/unit/logic/integration/test_hammer_failure_replay.py",)
    )
    assert test_plan.focused_tests == (
        "tests/unit/logic/integration/test_hammer_failure_replay.py",
    )
    assert test_plan.legal_ir_families == ()

    unknown = plan_incremental_validation(("ipfs_datasets_py/new_runtime/unknown.py",))
    assert unknown.conservative_fallback
    assert not unknown.is_incremental
    assert unknown.legal_ir_families == LEGAL_IR_EVALUATION_FAMILIES
    assert unknown.replay_samples == tuple(sorted(DEFAULT_REPLAY_CASES))
    assert unknown.mutation_cases == tuple(sorted(DEFAULT_MUTATION_CASES))
    assert unknown.proof_obligations == tuple(sorted(DEFAULT_PROOF_OBLIGATIONS))


@pytest.mark.parametrize("boundary", [ValidationBoundary.MERGE, ValidationBoundary.ROLLOUT])
def test_merge_and_rollout_ignore_scope_reduction_and_require_full_gates(boundary) -> None:
    catalog = ValidationScopeCatalog()
    plan = plan_incremental_validation(
        ("ipfs_datasets_py/logic/modal/codec.py",), boundary=boundary
    )

    assert plan.legal_ir_families == catalog.legal_ir_families
    assert plan.replay_samples == catalog.replay_samples
    assert plan.mutation_cases == catalog.mutation_cases
    assert plan.proof_obligations == catalog.proof_obligations
    assert plan.complete_frozen_canary_required
    assert plan.complete_promotion_proofs_required
    assert "frozen_canary" in plan.required_check_ids
    assert "promotion_proof_set" in plan.required_check_ids


def test_frozen_baseline_is_content_addressed_deeply_immutable_and_shared() -> None:
    source = {"metrics": {"deontic": [0.7, 0.8]}}
    baseline = FrozenBaselineEvidence(
        version="compiler-a/holdout-v1",
        payload=source,
        frozen_canary_ids=("canary-2", "canary-1"),
        promotion_proof_ids=("proof-1",),
    )
    source["metrics"]["deontic"].append(999)

    assert baseline.payload["metrics"]["deontic"] == (0.7, 0.8)
    with pytest.raises(TypeError):
        baseline.payload["new"] = True
    assert baseline.evidence_id == FrozenBaselineEvidence(
        version="compiler-a/holdout-v1",
        payload={"metrics": {"deontic": [0.7, 0.8]}},
        frozen_canary_ids=("canary-1", "canary-2"),
        promotion_proof_ids=("proof-1",),
    ).evidence_id


def _small_candidate_plan() -> ChangedScopeValidationPlan:
    return ChangedScopeValidationPlan(
        boundary=ValidationBoundary.CANDIDATE,
        changed_files=("ipfs_datasets_py/logic/modal/codec.py",),
        typed_ast_scopes=(),
        focused_tests=(),
        legal_ir_families=("deontic", "temporal", "provenance"),
        replay_samples=(),
        mutation_cases=(),
        proof_obligations=(),
    )


def test_independent_checks_run_concurrently_over_same_immutable_baseline() -> None:
    plan = _small_candidate_plan()
    baseline = FrozenBaselineEvidence(version="baseline-v1", payload={"score": 0.9})
    barrier = threading.Barrier(len(plan.required_check_ids))
    thread_ids: set[int] = set()
    baseline_ids: set[int] = set()
    lock = threading.Lock()

    def check(request):
        with lock:
            thread_ids.add(threading.get_ident())
            baseline_ids.add(id(request.baseline_evidence))
        barrier.wait(timeout=2.0)
        assert request.baseline_evidence.payload["score"] == 0.9
        return {"accepted": True, "target": request.check_id}

    callbacks = {check_id: check for check_id in plan.required_check_ids}
    report = IncrementalCandidateValidator(max_workers=8).validate(
        plan, callbacks, baseline_evidence=baseline
    )

    assert report.accepted
    assert len(thread_ids) == len(plan.required_check_ids)
    assert baseline_ids == {id(baseline)}
    assert {result.baseline_evidence_id for result in report.results.values()} == {
        baseline.evidence_id
    }


def test_only_explicit_transient_failure_is_retried() -> None:
    plan = ChangedScopeValidationPlan(
        boundary="candidate",
        changed_files=("ipfs_datasets_py/logic/modal/codec.py",),
        typed_ast_scopes=(),
        focused_tests=(),
        legal_ir_families=(),
        replay_samples=(),
        mutation_cases=("invert_modality",),
        proof_obligations=(),
    )
    attempts = {check_id: 0 for check_id in plan.required_check_ids}

    def syntax(request):
        attempts[request.check_id] += 1
        if request.attempt == 1:
            raise TransientValidationError("temporary worker disconnect")
        return True

    def deterministic_failure(request):
        attempts[request.check_id] += 1
        return {
            "accepted": False,
            "error": "mutation expectation failed",
            "retryable": True,  # not enough without an explicit transient classification
        }

    report = IncrementalCandidateValidator(max_transient_retries=5).validate(
        plan,
        {
            "syntax": syntax,
            "mutation:invert_modality": deterministic_failure,
        },
    )

    assert not report.accepted
    assert attempts == {"syntax": 2, "mutation:invert_modality": 1}
    assert report.results["syntax"].attempts == 2
    assert report.results["syntax"].transient_failures == 1
    assert report.results["mutation:invert_modality"].attempts == 1


def test_missing_check_fails_closed_and_boundary_gates_must_actually_run() -> None:
    plan = ChangedScopeValidationPlan(
        boundary="merge",
        changed_files=("ipfs_datasets_py/logic/modal/codec.py",),
        typed_ast_scopes=(),
        focused_tests=(),
        legal_ir_families=(),
        replay_samples=(),
        mutation_cases=(),
        proof_obligations=(),
        complete_frozen_canary_required=True,
        complete_promotion_proofs_required=True,
    )
    callbacks = {
        "syntax": lambda request: True,
        "frozen_canary": lambda request: {"accepted": True, "case_count": 50},
        # promotion_proof_set intentionally absent
    }

    report = IncrementalCandidateValidator().validate(plan, callbacks)

    assert not report.accepted
    assert report.failed_check_ids == ("promotion_proof_set",)
    assert not report.promotion_gates_complete
    assert report.results["promotion_proof_set"].error == "required_check_not_registered"


def test_callback_must_explicitly_classify_a_transient_result_to_retry() -> None:
    plan = ChangedScopeValidationPlan(
        boundary="candidate",
        changed_files=("tests/unit/test_example.py",),
        typed_ast_scopes=(),
        focused_tests=("tests/unit/test_example.py",),
        legal_ir_families=(),
        replay_samples=(),
        mutation_cases=(),
        proof_obligations=(),
    )
    attempts = {check_id: 0 for check_id in plan.required_check_ids}

    def callback(request):
        attempts[request.check_id] += 1
        if request.check_id.startswith("test:") and request.attempt == 1:
            return {"accepted": False, "transient": True, "error": "provider timeout"}
        return True

    report = IncrementalCandidateValidator(max_transient_retries=1).validate(
        plan, {check_id: callback for check_id in plan.required_check_ids}
    )

    assert report.accepted
    assert attempts["syntax"] == 1
    assert attempts["test:tests/unit/test_example.py"] == 2
    assert report.report_id.startswith("incremental-validation-")
