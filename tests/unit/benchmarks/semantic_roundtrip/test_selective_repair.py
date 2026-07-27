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
from benchmarks.semantic_roundtrip.constructors.typed_deontic import (
    TypedDeonticCanonicalConstructor,
    TypedDeonticConstructorDiagnostics,
    TypedDeonticDiagnosticTriggerDetector,
    TypedDeonticSlotDiagnostic,
    derive_slot_diagnostics,
    project_legal_norms,
    project_legal_norms_with_diagnostics,
)
from benchmarks.semantic_roundtrip.selective_repair import (
    ACTIVATION_FIXTURE_PACK_ID,
    DECLARED_SELECTION_RULES,
    DECLARED_STRUCTURAL_CONSTRAINTS,
    HAMMER_CANDIDATE_SELECTOR_INTERFACE,
    REPAIR_MAX_TOKENS,
    REQUIRED_ACTIVATION_TRIGGER_KINDS,
    SELECTIVE_LEANSTRAL_REPAIR_INTERFACE,
    SELECTIVE_REPAIR_ACTIVATION_INTERFACE,
    SELECTIVE_REPAIR_COORDINATE_RECEIPT_INTERFACE,
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
    ZeroTriggerDetector,
    activation_fixture_pack,
    coordinate_receipt_from_construction,
    run_selective_repair_activation,
    validate_selective_repair_activation,
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


# ---------------------------------------------------------------------------
# EVAL-005: selective repair activation harness
# ---------------------------------------------------------------------------


class _Norm:
    def __init__(self, data: dict[str, object]) -> None:
        self._data = data

    def to_dict(self) -> dict[str, object]:
        return dict(self._data)


def test_activation_fixture_pack_forces_required_trigger_kinds() -> None:
    pack = activation_fixture_pack()
    assert len(pack) >= 3
    kinds = {
        trigger.kind
        for case in pack
        for trigger in case.triggers
    }
    assert set(REQUIRED_ACTIVATION_TRIGGER_KINDS) <= kinds
    fields = {
        trigger.canonical_field
        for case in pack
        for trigger in case.triggers
    }
    assert "temporal" in fields
    assert any(
        trigger.kind is RepairTriggerKind.LOW_CONFIDENCE
        for case in pack
        for trigger in case.triggers
    )
    assert any(
        trigger.kind is RepairTriggerKind.CONTRADICTORY
        for case in pack
        for trigger in case.triggers
    )


def test_activation_harness_fires_triggers_attempts_repair_and_scopes_fields() -> None:
    report = validate_selective_repair_activation()

    assert report.fixture_pack_id == ACTIVATION_FIXTURE_PACK_ID
    assert report.validation_passed is True
    assert report.any_trigger is True
    assert report.total_model_calls > 0
    assert report.to_dict()["interface"] == SELECTIVE_REPAIR_ACTIVATION_INTERFACE

    observed_kinds: set[str] = set()
    for receipt in report.coordinate_receipts:
        payload = receipt.to_dict()
        assert payload["interface"] == (
            SELECTIVE_REPAIR_COORDINATE_RECEIPT_INTERFACE
        )
        assert "repair_triggered" in payload
        assert "repair_applied" in payload
        assert "model_calls" in payload
        assert receipt.repair_triggered is True
        assert receipt.model_calls >= 1
        assert receipt.repair_attempted is True
        assert receipt.repair_applied is True
        assert receipt.only_triggered_fields_changed is True
        observed_kinds.update(receipt.trigger_kinds)
        # Accepted repair may only touch trigger fields.
        assert set(receipt.changed_fields) <= set(receipt.trigger_fields)

    assert set(item.value for item in REQUIRED_ACTIVATION_TRIGGER_KINDS) <= (
        observed_kinds
    )


def test_selective_arm_with_zero_triggers_on_fixture_pack_fails_validation() -> None:
    report = run_selective_repair_activation(
        trigger_detector_factory=lambda _case: ZeroTriggerDetector(),
        require_triggers=True,
    )

    assert report.validation_passed is False
    assert report.any_trigger is False
    assert report.total_model_calls == 0
    assert report.detail is not None
    assert "zero triggers" in report.detail
    with pytest.raises(ContractError, match="zero triggers"):
        validate_selective_repair_activation(report)


def test_coordinate_receipt_from_construction_reports_activation_metrics() -> None:
    repairer, _ = repair([REPAIRED_IR.to_dict()], policy=SelectiveRepairPolicy(candidate_count=1))
    construction = repairer.construct_with_diagnostics(
        request(), triggers=(OBJECT_TRIGGER,)
    )
    receipt = coordinate_receipt_from_construction(
        "object_slot", construction
    )

    assert receipt.repair_triggered is True
    assert receipt.repair_applied is True
    assert receipt.model_calls == 1
    assert receipt.changed_fields == ("object",)
    assert receipt.only_triggered_fields_changed is True
    assert receipt.to_dict()["repair_triggered"] is True


def test_typed_deontic_emits_triggers_from_diagnostics_without_breaking_baseline() -> None:
    vocabulary = AllowedAtomVocabulary(
        actors=("controller",),
        actions=("delete",),
        objects=("records",),
        qualifiers=("after_30_days", "unless_required_by_law"),
    )
    norms = [
        _Norm(
            {
                "modality": "obligation",
                "norm_type": "obligation",
                "actor": "controller",
                "action": "delete",
                "action_verb": "delete",
                "action_object": "records",
                "conditions": [],
                "exceptions": [],
                "temporal_constraints": [],
            }
        )
    ]
    source = (
        "The controller must delete the records after 30 days and shall not "
        "delete the records unless required by law."
    )
    projected, diagnostics = project_legal_norms_with_diagnostics(
        norms, vocabulary, source_text=source
    )
    # Projection path used by the no-repair baseline remains pure IR.
    baseline_only = project_legal_norms(norms, vocabulary)
    assert baseline_only == projected
    assert projected.rules[0].temporal == ()
    assert isinstance(diagnostics, TypedDeonticConstructorDiagnostics)
    triggers = diagnostics.repair_triggers()
    assert triggers
    assert any(
        getattr(item, "canonical_field") == "temporal"
        and getattr(item, "kind") is RepairTriggerKind.MISSING
        for item in triggers
    )

    # Explicit low-confidence and contradictory diagnostic slots convert too.
    slots = derive_slot_diagnostics(
        projected,
        source_text=source,
        field_confidences={(0, "object"): 0.2},
        modality_raw={0: "obligation prohibition"},
    )
    kinds = {slot.kind for slot in slots}
    assert "missing" in kinds
    assert "low_confidence" in kinds
    assert "contradictory" in kinds

    detector = TypedDeonticDiagnosticTriggerDetector(
        field_confidences={(0, "object"): 0.2}
    )
    detected = detector.detect(
        ConstructorRequest(source, vocabulary, {}),
        projected,
    )
    assert detected
    assert detector.identity.startswith("TypedDeonticDiagnosticTriggerDetector")

    # No-repair baseline arm: construct returns ConstructorResult only and does
    # not require selective repair to import or run.
    constructor = TypedDeonticCanonicalConstructor()
    assert isinstance(constructor, RoundTripConstructor)
    # construct_with_diagnostics is available for selective arms; construct
    # remains the scored baseline surface.
    assert callable(constructor.construct_with_diagnostics)
    assert callable(constructor.construct)


def test_typed_deontic_diagnostic_triggers_drive_selective_repair() -> None:
    vocabulary = AllowedAtomVocabulary(
        actors=("controller",),
        actions=("delete",),
        objects=("records",),
        qualifiers=("after_30_days",),
    )
    baseline_ir = CanonicalRuleIR(
        (
            CanonicalRule(
                modality="O",
                actor="controller",
                action="delete",
                object="records",
                temporal=(),
            ),
        )
    )
    repaired_ir = CanonicalRuleIR(
        (
            CanonicalRule(
                modality="O",
                actor="controller",
                action="delete",
                object="records",
                temporal=("after_30_days",),
            ),
        )
    )
    source = "The controller must delete the records after 30 days."
    detector = TypedDeonticDiagnosticTriggerDetector()
    client = RecordingClient([repaired_ir.to_dict()])
    repairer = SelectiveLeanstralRepair(
        FixedConstructor(
            ConstructorResult(ComponentStatus.SUCCESS, canonical_ir=baseline_ir)
        ),
        client=client,
        policy=SelectiveRepairPolicy(candidate_count=1),
        selector=selector(SelectiveRepairPolicy(candidate_count=1)),
        trigger_detector=detector,
    )
    construction = repairer.construct_with_diagnostics(
        ConstructorRequest(source, vocabulary, {})
    )
    receipt = coordinate_receipt_from_construction(
        "typed_deontic_temporal", construction
    )

    assert construction.receipt.triggers
    assert any(
        item.canonical_field == "temporal"
        and item.kind is RepairTriggerKind.MISSING
        for item in construction.receipt.triggers
    )
    assert receipt.repair_triggered is True
    assert receipt.model_calls == 1
    assert receipt.repair_applied is True
    assert receipt.changed_fields == ("temporal",)
    assert receipt.only_triggered_fields_changed is True


def test_slot_diagnostic_rejects_unknown_fields() -> None:
    with pytest.raises(ContractError, match="unknown slot diagnostic field"):
        TypedDeonticSlotDiagnostic(
            rule_index=0,
            canonical_field="not_a_field",
            kind="missing",
        )

