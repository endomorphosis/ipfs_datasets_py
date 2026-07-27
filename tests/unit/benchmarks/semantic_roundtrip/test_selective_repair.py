"""Tests for selective Leanstral repair and structural candidate selection."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from benchmarks.semantic_roundtrip import (
    AllowedAtomVocabulary,
    CanonicalRule,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ConstructorResult,
    ContractError,
    FailureReason,
    RoundTripConstructor,
)
from benchmarks.semantic_roundtrip.constructors.leanstral import (
    LEANSTRAL_ENDPOINT,
    LEANSTRAL_MODEL,
    LeanstralTimeoutError,
)
from benchmarks.semantic_roundtrip.selective_repair import (
    DECLARED_SELECTION_RULES,
    DECLARED_STRUCTURAL_CONSTRAINTS,
    HAMMER_CANDIDATE_SELECTOR_INTERFACE,
    REPAIR_MAX_TOKENS,
    SELECTIVE_LEANSTRAL_REPAIR_INTERFACE,
    CandidateSelection,
    HammerCandidateSelector,
    ModelCallStatus,
    RepairAttemptStatus,
    RepairTrigger,
    RepairTriggerKind,
    SelectiveLeanstralRepair,
    SelectiveRepairPolicy,
    StructuralTool,
    StructuralValidationReceipt,
    StructuralValidationRequest,
    StructuralValidatorBinding,
)


VOCABULARY = AllowedAtomVocabulary(
    actors=("controller", "processor"),
    actions=("delete", "retain"),
    objects=("records",),
    qualifiers=("after_30_days", "unless_required_by_law"),
)
BASELINE_IR = CanonicalRuleIR(
    (
        CanonicalRule(
            modality="O",
            actor="controller",
            action="delete",
            object="",
        ),
    )
)
REPAIRED_IR = CanonicalRuleIR(
    (
        CanonicalRule(
            modality="O",
            actor="controller",
            action="delete",
            object="records",
        ),
    )
)
OBJECT_TRIGGER = RepairTrigger(
    rule_index=0,
    canonical_field="object",
    kind=RepairTriggerKind.MISSING,
    evidence="typed compiler left the object slot empty",
)


class FixedConstructor:
    identity = "FixedTypedConstructor@1"

    def __init__(self, result: ConstructorResult | None = None) -> None:
        self.result = result or ConstructorResult(
            ComponentStatus.SUCCESS, canonical_ir=BASELINE_IR
        )
        self.calls: list[ConstructorRequest] = []

    def construct(self, request: ConstructorRequest) -> ConstructorResult:
        self.calls.append(request)
        return self.result


class RecordingClient:
    endpoint = LEANSTRAL_ENDPOINT
    model = LEANSTRAL_MODEL

    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def complete_json(self, **kwargs: object) -> Any:
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def request(config: dict[str, object] | None = None) -> ConstructorRequest:
    return ConstructorRequest(
        "The controller must delete the records.",
        VOCABULARY,
        config or {},
    )


def passing_binding(
    *,
    seen: list[StructuralValidationRequest] | None = None,
) -> StructuralValidatorBinding:
    def validate(
        structural_request: StructuralValidationRequest,
    ) -> StructuralValidationReceipt:
        if seen is not None:
            seen.append(structural_request)
        return StructuralValidationReceipt(
            validator_id="hammer-cvc5-pinned",
            tool=StructuralTool.HAMMER_CVC5,
            constraints=DECLARED_STRUCTURAL_CONSTRAINTS,
            passed=True,
        )

    return StructuralValidatorBinding(
        validator_id="hammer-cvc5-pinned",
        tool=StructuralTool.HAMMER_CVC5,
        constraints=DECLARED_STRUCTURAL_CONSTRAINTS,
        validate=validate,
    )


def selector(
    policy: SelectiveRepairPolicy | None = None,
    *,
    seen: list[StructuralValidationRequest] | None = None,
) -> HammerCandidateSelector:
    return HammerCandidateSelector(
        policy,
        validators=(passing_binding(seen=seen),),
    )


def repair(
    responses: list[object],
    *,
    policy: SelectiveRepairPolicy | None = None,
    selected_by: HammerCandidateSelector | None = None,
    baseline: FixedConstructor | None = None,
) -> tuple[SelectiveLeanstralRepair, RecordingClient]:
    client = RecordingClient(responses)
    repairer = SelectiveLeanstralRepair(
        baseline or FixedConstructor(),
        client=client,
        policy=policy,
        selector=selected_by or selector(policy),
    )
    return repairer, client


def test_policy_preregisters_exact_triggers_budgets_and_selection_rules() -> None:
    policy = SelectiveRepairPolicy()

    assert policy.selection_rules == DECLARED_SELECTION_RULES
    assert policy.structural_constraints == DECLARED_STRUCTURAL_CONSTRAINTS
    assert policy.eligible_triggers == tuple(RepairTriggerKind)
    assert policy.digest == policy.digest
    assert policy.to_dict()["interface"] == "SelectiveRepairPolicy@1"

    with pytest.raises(ContractError, match="selection_rules"):
        SelectiveRepairPolicy(selection_rules=("prefer_semantic_score",))
    with pytest.raises(ContractError, match="threshold"):
        policy.validate_triggers(
            BASELINE_IR,
            (
                RepairTrigger(
                    0,
                    "object",
                    RepairTriggerKind.LOW_CONFIDENCE,
                    confidence=policy.low_confidence_threshold,
                ),
            ),
        )
    with pytest.raises(ContractError, match="nonempty"):
        policy.validate_triggers(
            REPAIRED_IR,
            (RepairTrigger(0, "object", RepairTriggerKind.MISSING),),
        )


def test_selective_repair_records_every_call_and_changed_field() -> None:
    seen: list[StructuralValidationRequest] = []
    policy = SelectiveRepairPolicy(candidate_count=2)
    invalid_scope = CanonicalRuleIR(
        (
            replace(
                REPAIRED_IR.rules[0],
                modality="F",
            ),
        )
    )
    repairer, client = repair(
        [invalid_scope.to_dict(), REPAIRED_IR.to_dict()],
        policy=policy,
        selected_by=selector(policy, seen=seen),
    )

    construction = repairer.construct_with_diagnostics(
        request(), triggers=(OBJECT_TRIGGER,)
    )

    assert isinstance(repairer, RoundTripConstructor)
    assert repairer.identity.startswith(SELECTIVE_LEANSTRAL_REPAIR_INTERFACE)
    assert repairer.selector.identity.startswith(
        HAMMER_CANDIDATE_SELECTOR_INTERFACE
    )
    assert construction.result.status is ComponentStatus.SUCCESS
    assert construction.result.canonical_ir == REPAIRED_IR
    assert construction.baseline_result.canonical_ir == BASELINE_IR
    assert construction.receipt.status is RepairAttemptStatus.ACCEPTED
    assert construction.receipt.baseline_retained is True
    assert construction.receipt.score_disposition == "selected_candidate"
    assert construction.receipt.forced_loss is None
    assert len(construction.receipt.model_calls) == 2
    assert all(
        item.status is ModelCallStatus.RETURNED
        for item in construction.receipt.model_calls
    )
    assert construction.receipt.selection is not None
    first, second = construction.receipt.selection.evaluations
    assert first.accepted is False
    assert first.changed_fields == ("modality", "object")
    assert "untriggered_fields_changed:rules[0].modality" in (
        first.rejection_reasons
    )
    assert second.accepted is True
    assert second.changed_fields == ("object",)
    assert construction.receipt.changed_fields == ("modality", "object")
    assert len(seen) == 1  # locally invalid candidate never reaches proof tools
    assert set(seen[0].to_dict()) == {
        "allowed_field_paths",
        "baseline_ir",
        "candidate_ir",
        "changed_field_paths",
        "constraints",
        "semantic_authority",
    }
    assert "source" not in str(seen[0].to_dict()).lower()
    assert "gold" not in str(seen[0].to_dict()).lower()
    assert len(client.calls) == 2
    assert all(call["max_tokens"] == REPAIR_MAX_TOKENS for call in client.calls)


def test_only_schema_valid_nonempty_candidates_reach_validators() -> None:
    seen: list[StructuralValidationRequest] = []
    policy = SelectiveRepairPolicy(candidate_count=2)
    repairer, _ = repair(
        [
            {"rules": []},
            {
                "rules": [
                    {
                        **REPAIRED_IR.rules[0].to_dict(),
                        "undeclared": True,
                    }
                ]
            },
        ],
        policy=policy,
        selected_by=selector(policy, seen=seen),
    )

    construction = repairer.construct_with_diagnostics(
        request(), triggers=(OBJECT_TRIGGER,)
    )

    assert construction.result.status is ComponentStatus.FAILED
    assert construction.result.failure_reason is FailureReason.INVALID_OUTPUT
    assert construction.receipt.status is RepairAttemptStatus.REJECTED
    assert construction.receipt.score_disposition == "failure_loss_one"
    assert construction.receipt.forced_loss == 1.0
    assert construction.baseline_result.canonical_ir == BASELINE_IR
    assert seen == []
    assert construction.receipt.selection is not None
    empty, invalid = construction.receipt.selection.evaluations
    assert empty.schema_valid is True and empty.nonempty is False
    assert invalid.schema_valid is False and invalid.nonempty is False
    assert empty.accepted is invalid.accepted is False


def test_structural_rejection_is_visible_and_scores_as_failure() -> None:
    requests: list[StructuralValidationRequest] = []

    def reject(
        structural_request: StructuralValidationRequest,
    ) -> StructuralValidationReceipt:
        requests.append(structural_request)
        return StructuralValidationReceipt(
            validator_id="lean-pinned",
            tool=StructuralTool.LEAN,
            constraints=DECLARED_STRUCTURAL_CONSTRAINTS,
            passed=False,
            detail="reconstruction constraint failed",
        )

    binding = StructuralValidatorBinding(
        "lean-pinned",
        StructuralTool.LEAN,
        DECLARED_STRUCTURAL_CONSTRAINTS,
        reject,
    )
    policy = SelectiveRepairPolicy(candidate_count=1)
    repairer, _ = repair(
        [REPAIRED_IR.to_dict()],
        policy=policy,
        selected_by=HammerCandidateSelector(
            policy, validators=(binding,)
        ),
    )

    construction = repairer.construct_with_diagnostics(
        request(), triggers=(OBJECT_TRIGGER,)
    )

    assert construction.result.failure_reason is FailureReason.INVALID_OUTPUT
    assert construction.receipt.status is RepairAttemptStatus.REJECTED
    assert construction.receipt.score_disposition == "failure_loss_one"
    assert construction.unrepaired_baseline.canonical_ir == BASELINE_IR
    assert len(requests) == 1
    assert construction.receipt.selection is not None
    evaluation = construction.receipt.selection.evaluations[0]
    assert evaluation.canonical_ir == REPAIRED_IR
    assert evaluation.changed_fields == ("object",)
    assert evaluation.structural_receipts[0].passed is False
    assert evaluation.rejection_reasons == (
        "structural_rejection:lean-pinned",
    )


def test_missing_structural_capability_fails_closed_without_hiding_candidate() -> None:
    policy = SelectiveRepairPolicy(candidate_count=1)
    repairer, _ = repair(
        [REPAIRED_IR.to_dict()],
        policy=policy,
        selected_by=HammerCandidateSelector(policy),
    )

    construction = repairer.construct_with_diagnostics(
        request(), triggers=(OBJECT_TRIGGER,)
    )

    assert construction.result.failure_reason is FailureReason.INVALID_OUTPUT
    assert construction.receipt.selection is not None
    evaluation = construction.receipt.selection.evaluations[0]
    assert evaluation.canonical_ir == REPAIRED_IR
    assert evaluation.rejection_reasons == (
        "structural_validator_unavailable",
    )


def test_failed_model_calls_are_all_recorded_and_receive_failure_loss() -> None:
    policy = SelectiveRepairPolicy(candidate_count=2)
    repairer, client = repair(
        [
            LeanstralTimeoutError("first timeout"),
            RuntimeError("second failure"),
        ],
        policy=policy,
    )

    construction = repairer.construct_with_diagnostics(
        request(), triggers=(OBJECT_TRIGGER,)
    )

    assert len(client.calls) == 2
    assert construction.result.failure_reason is FailureReason.RETRY_EXHAUSTED
    assert construction.receipt.status is RepairAttemptStatus.FAILED
    assert construction.receipt.score_disposition == "failure_loss_one"
    assert construction.baseline_result.canonical_ir == BASELINE_IR
    first, second = construction.receipt.model_calls
    assert first.failure_reason is FailureReason.TIMEOUT
    assert second.failure_reason is FailureReason.EXCEPTION
    assert first.status is second.status is ModelCallStatus.FAILED
    assert construction.receipt.selection == CandidateSelection((), None)


def test_no_trigger_returns_exact_baseline_without_model_or_proof_calls() -> None:
    seen: list[StructuralValidationRequest] = []
    repairer, client = repair(
        [],
        selected_by=selector(seen=seen),
    )

    construction = repairer.construct_with_diagnostics(
        request(), triggers=()
    )

    assert construction.result is construction.baseline_result
    assert construction.result.canonical_ir == BASELINE_IR
    assert construction.receipt.status is RepairAttemptStatus.NOT_TRIGGERED
    assert construction.receipt.score_disposition == "unrepaired_baseline"
    assert construction.receipt.model_calls == ()
    assert client.calls == []
    assert seen == []


def test_candidate_ranking_uses_fewest_changes_then_call_order() -> None:
    policy = SelectiveRepairPolicy(candidate_count=2)
    triggers = (
        OBJECT_TRIGGER,
        RepairTrigger(
            0,
            "temporal",
            RepairTriggerKind.LOW_CONFIDENCE,
            confidence=0.2,
        ),
    )
    two_changes = CanonicalRuleIR(
        (replace(REPAIRED_IR.rules[0], temporal=("after_30_days",)),)
    )
    repairer, _ = repair(
        [two_changes.to_dict(), REPAIRED_IR.to_dict()],
        policy=policy,
    )

    construction = repairer.construct_with_diagnostics(
        request(), triggers=triggers
    )

    assert construction.result.canonical_ir == REPAIRED_IR
    assert construction.receipt.selection is not None
    assert construction.receipt.selection.selected_ordinal == 1
    assert all(
        item.accepted
        for item in construction.receipt.selection.evaluations
    )


def test_confident_fields_cannot_be_silently_rewritten() -> None:
    policy = SelectiveRepairPolicy(candidate_count=1)
    rewritten = CanonicalRuleIR(
        (replace(REPAIRED_IR.rules[0], modality="F"),)
    )
    repairer, _ = repair([rewritten.to_dict()], policy=policy)

    construction = repairer.construct_with_diagnostics(
        request(), triggers=(OBJECT_TRIGGER,)
    )

    assert construction.result.status is ComponentStatus.FAILED
    assert construction.receipt.selection is not None
    evaluation = construction.receipt.selection.evaluations[0]
    assert evaluation.changed_fields == ("modality", "object")
    assert not evaluation.accepted
    assert evaluation.structural_receipts == ()


def test_proof_receipts_cannot_claim_semantic_authority() -> None:
    with pytest.raises(ContractError, match="semantic authority"):
        StructuralValidationReceipt(
            validator_id="hammer",
            tool=StructuralTool.HAMMER_CVC5,
            constraints=DECLARED_STRUCTURAL_CONSTRAINTS,
            passed=True,
            semantic_authority=True,
        )


def test_validator_failure_is_a_recorded_rejection_not_an_exception() -> None:
    def explode(
        structural_request: StructuralValidationRequest,
    ) -> StructuralValidationReceipt:
        del structural_request
        raise RuntimeError("validator unavailable")

    policy = SelectiveRepairPolicy(candidate_count=1)
    binding = StructuralValidatorBinding(
        "hammer-crash",
        StructuralTool.HAMMER_CVC5,
        DECLARED_STRUCTURAL_CONSTRAINTS,
        explode,
    )
    repairer, _ = repair(
        [REPAIRED_IR.to_dict()],
        policy=policy,
        selected_by=HammerCandidateSelector(policy, validators=(binding,)),
    )

    construction = repairer.construct_with_diagnostics(
        request(), triggers=(OBJECT_TRIGGER,)
    )

    assert construction.result.failure_reason is FailureReason.INVALID_OUTPUT
    assert construction.receipt.selection is not None
    receipt = construction.receipt.selection.evaluations[
        0
    ].structural_receipts[0]
    assert receipt.passed is False
    assert receipt.semantic_authority is False
    assert "RuntimeError" in (receipt.detail or "")


def test_baseline_failure_is_retained_and_prevents_model_calls() -> None:
    failed = ConstructorResult(
        ComponentStatus.FAILED,
        failure_reason=FailureReason.EMPTY_L1,
        failure_detail="typed baseline was empty",
    )
    base = FixedConstructor(failed)
    repairer, client = repair([], baseline=base)

    construction = repairer.construct_with_diagnostics(request())

    assert construction.result is failed
    assert construction.baseline_result is failed
    assert construction.receipt.status is RepairAttemptStatus.BASELINE_FAILED
    assert construction.receipt.score_disposition == "failure_loss_one"
    assert construction.receipt.model_calls == ()
    assert client.calls == []


def test_prompt_ignores_gold_config_and_binds_fixed_schema_and_budget() -> None:
    policy = SelectiveRepairPolicy(candidate_count=1)
    repairer, client = repair([REPAIRED_IR.to_dict()], policy=policy)

    construction = repairer.construct_with_diagnostics(
        request({"gold_ir": {"secret": True}, "gold_rule_count": 99}),
        triggers=(OBJECT_TRIGGER,),
    )

    assert construction.result.status is ComponentStatus.SUCCESS
    call = client.calls[0]
    assert call["max_tokens"] == REPAIR_MAX_TOKENS
    assert "gold" not in str(call).lower()
    rules_schema = call["schema"]["properties"]["rules"]  # type: ignore[index]
    assert rules_schema["maxItems"] == 16
