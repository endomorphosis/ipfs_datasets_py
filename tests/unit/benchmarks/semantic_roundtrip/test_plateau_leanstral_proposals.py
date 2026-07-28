"""Unit tests for PLAT-040 Leanstral selective proposal teacher."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from benchmarks.semantic_roundtrip.constructors.leanstral import (
    LEANSTRAL_ENDPOINT,
    LEANSTRAL_MODEL,
    LeanstralTimeoutError,
)
from benchmarks.semantic_roundtrip.contracts import (
    AllowedAtomVocabulary,
    CanonicalRule,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ConstructorResult,
)
from benchmarks.semantic_roundtrip.plateau_leanstral_proposals import (
    ACCEPT_RATE_DEFINITION,
    DEFAULT_RECEIPTS_RELATIVE_PATH,
    DRY_RUN_FIXTURE_PACK_ID,
    PLATEAU_BREAK_TASK_ID,
    PLATEAU_LEANSTRAL_PROPOSALS_EVIDENCE,
    PLATEAU_LEANSTRAL_PROPOSALS_INTERFACE,
    PLATEAU_LEANSTRAL_PROPOSAL_RECEIPTS_INTERFACE,
    PLATEAU_LEANSTRAL_PROPOSAL_RECEIPTS_SCHEMA,
    RETRY_EXHAUSTED_RATE_DEFINITION,
    TEACHER_IDENTITY,
    LeanstralProposalCaseReceipt,
    LeanstralSelectiveProposalTeacher,
    PlateauLeanstralProposalError,
    PlateauLeanstralProposalReceipts,
    ProposalMode,
    ProposalOutcome,
    aggregate_proposal_reliability,
    apply_field_patch,
    build_dry_run_proposal_receipts,
    dry_run_fixture_pack,
    load_plateau_leanstral_proposal_receipts,
    only_triggered_fields_changed,
    parse_plateau_leanstral_proposal_receipts,
    trigger_paths,
    validate_dry_run_fixture_pack,
    write_plateau_leanstral_proposal_receipts,
)
from benchmarks.semantic_roundtrip.selective_repair import (
    DECLARED_STRUCTURAL_CONSTRAINTS,
    HammerCandidateSelector,
    RepairTrigger,
    RepairTriggerKind,
    SelectiveLeanstralRepair,
    SelectiveRepairPolicy,
    StructuralTool,
    StructuralValidationReceipt,
    StructuralValidationRequest,
    StructuralValidatorBinding,
)
from benchmarks.semantic_roundtrip.structural_admission import (
    AdmissionDisposition,
    StructuralAdmissionGate,
    StructuralAdmissionPolicy,
    make_passing_binding,
    make_rejecting_binding,
)


ROOT = Path(__file__).resolve().parents[4]
RECEIPTS_PATH = ROOT / DEFAULT_RECEIPTS_RELATIVE_PATH

VOCABULARY = AllowedAtomVocabulary(
    actors=("controller", "processor"),
    actions=("delete", "retain"),
    objects=("records",),
    qualifiers=("after_30_days", "until_released", "active_hold"),
)


def _baseline() -> CanonicalRuleIR:
    return CanonicalRuleIR(
        (
            CanonicalRule(
                modality="O",
                actor="controller",
                action="delete",
                object="",
            ),
            CanonicalRule(
                modality="O",
                actor="processor",
                action="retain",
                object="records",
                conditions=("active_hold",),
                temporal=("until_released",),
            ),
        )
    )


def _object_trigger() -> RepairTrigger:
    return RepairTrigger(
        rule_index=0,
        canonical_field="object",
        kind=RepairTriggerKind.MISSING,
        evidence="unit test missing object slot",
    )


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


class FixedConstructor:
    identity = "FixedTypedConstructor@1"

    def __init__(self, ir: CanonicalRuleIR) -> None:
        self.ir = ir

    def construct(self, request: ConstructorRequest) -> ConstructorResult:
        del request
        return ConstructorResult(ComponentStatus.SUCCESS, canonical_ir=self.ir)


def _passing_selector(
    policy: SelectiveRepairPolicy | None = None,
) -> HammerCandidateSelector:
    def validate(
        structural_request: StructuralValidationRequest,
    ) -> StructuralValidationReceipt:
        del structural_request
        return StructuralValidationReceipt(
            validator_id="hammer-cvc5-pinned",
            tool=StructuralTool.HAMMER_CVC5,
            constraints=DECLARED_STRUCTURAL_CONSTRAINTS,
            passed=True,
        )

    return HammerCandidateSelector(
        policy,
        validators=(
            StructuralValidatorBinding(
                validator_id="hammer-cvc5-pinned",
                tool=StructuralTool.HAMMER_CVC5,
                constraints=DECLARED_STRUCTURAL_CONSTRAINTS,
                validate=validate,
            ),
        ),
    )


def test_interface_constants_are_frozen() -> None:
    assert PLATEAU_LEANSTRAL_PROPOSALS_INTERFACE == "PlateauLeanstralProposals@1"
    assert PLATEAU_LEANSTRAL_PROPOSAL_RECEIPTS_INTERFACE == (
        "PlateauLeanstralProposalReceipts@1"
    )
    assert PLATEAU_LEANSTRAL_PROPOSAL_RECEIPTS_SCHEMA.startswith("ipfs-datasets.")
    assert PLATEAU_LEANSTRAL_PROPOSALS_EVIDENCE == "PLATEV040LLM"
    assert PLATEAU_BREAK_TASK_ID == "PLAT-040"
    assert TEACHER_IDENTITY == "leanstral"
    assert DRY_RUN_FIXTURE_PACK_ID.startswith("plateau-leanstral-proposal")
    assert "accept_rate" in ACCEPT_RATE_DEFINITION
    assert "retry_exhausted" in RETRY_EXHAUSTED_RATE_DEFINITION
    assert "end-to-end" in ACCEPT_RATE_DEFINITION or "e2e" in ACCEPT_RATE_DEFINITION.lower() or "end-to-end" in ACCEPT_RATE_DEFINITION


def test_dry_run_fixture_pack_covers_acceptance_outcomes() -> None:
    pack = dry_run_fixture_pack()
    outcomes = {item.case_id: item.expected_outcome for item in pack}
    assert outcomes["fixture_accept_missing_object"] is ProposalOutcome.ACCEPTED
    assert (
        outcomes["fixture_admission_reject_untriggered"]
        is ProposalOutcome.ADMISSION_REJECTED
    )
    assert outcomes["fixture_retry_exhausted"] is ProposalOutcome.RETRY_EXHAUSTED
    assert outcomes["fixture_not_triggered"] is ProposalOutcome.NOT_TRIGGERED


def test_dry_run_fixtures_pass_without_live_model() -> None:
    # No LeanstralClient constructed; dry-run must not touch the network.
    teacher = LeanstralSelectiveProposalTeacher(mode=ProposalMode.DRY_RUN)
    sealed = teacher.run_dry_run_fixtures()
    validate_dry_run_fixture_pack(sealed)

    assert sealed.mode is ProposalMode.DRY_RUN
    assert sealed.leanstral_is_default_realizer is False
    assert sealed.production_runtime_unchanged is True
    assert sealed.structural_admission_required is True
    assert sealed.receipts_cid
    assert sealed.accept_rate is not None
    assert sealed.retry_exhausted_rate is not None

    accepted = sealed.by_case_id()["fixture_accept_missing_object"]
    assert accepted.outcome is ProposalOutcome.ACCEPTED
    assert accepted.implementable is True
    assert accepted.admission_disposition == AdmissionDisposition.ACCEPTED.value
    assert accepted.only_triggered_fields_changed is True
    assert accepted.prior_l1_unchanged is False
    assert accepted.packet is not None
    assert accepted.packet.implementable is True
    assert accepted.packet.to_dict()["semantic_authority"] is False
    assert accepted.packet.proposals[0].teacher == "leanstral"
    assert accepted.packet.proposals[0].semantic_authority is False

    rejected = sealed.by_case_id()["fixture_admission_reject_untriggered"]
    assert rejected.outcome is ProposalOutcome.ADMISSION_REJECTED
    assert rejected.implementable is False
    assert rejected.prior_l1_unchanged is True
    assert rejected.admitted_l1_digest == rejected.baseline_l1_digest
    assert rejected.admission_disposition == (
        AdmissionDisposition.VALIDATOR_REJECT.value
    )

    exhausted = sealed.by_case_id()["fixture_retry_exhausted"]
    assert exhausted.outcome is ProposalOutcome.RETRY_EXHAUSTED
    assert exhausted.retry_exhausted is True
    assert exhausted.implementable is False
    assert exhausted.prior_l1_unchanged is True

    control = sealed.by_case_id()["fixture_not_triggered"]
    assert control.outcome is ProposalOutcome.NOT_TRIGGERED
    assert control.implementable is False


def test_accept_rate_and_retry_exhausted_recorded_separately() -> None:
    sealed = build_dry_run_proposal_receipts()
    rel = sealed.reliability
    payload = rel.to_dict()

    assert "accept_rate" in payload
    assert "retry_exhausted_rate" in payload
    assert payload["separate_from_end_to_end_loss"] is True
    assert payload["end_to_end_loss"] is None
    assert rel.accepted_proposals >= 1
    assert rel.retry_exhausted_proposals >= 1
    assert rel.proposal_attempts == (
        rel.accepted_proposals
        + rel.retry_exhausted_proposals
        + rel.admission_rejected_proposals
        + rel.model_rejected_proposals
        + rel.failed_proposals
        + 0  # not_applicable not present in fixture pack triggered set
    )
    # not_triggered is outside the denominator
    assert rel.not_triggered >= 1
    assert rel.accept_rate == pytest.approx(
        rel.accepted_proposals / rel.proposal_attempts
    )
    assert rel.retry_exhausted_rate == pytest.approx(
        rel.retry_exhausted_proposals / rel.proposal_attempts
    )
    # Rates are independent fields (not folded into one score / e2e loss).
    assert "accept_rate" in payload and "retry_exhausted_rate" in payload
    assert payload["accept_rate"] is not None
    assert payload["retry_exhausted_rate"] is not None
    # Both counters are present as separate tallies even when equal numerically.
    assert "accepted_proposals" in payload
    assert "retry_exhausted_proposals" in payload
    assert payload["accepted_proposals"] + payload["retry_exhausted_proposals"] <= (
        payload["proposal_attempts"]
    )


def test_only_triggered_fields_may_change() -> None:
    baseline = _baseline()
    trigger = _object_trigger()
    legal = apply_field_patch(
        baseline, rule_index=0, canonical_field="object", value="records"
    )
    illegal = apply_field_patch(
        legal, rule_index=1, canonical_field="actor", value="controller"
    )
    assert only_triggered_fields_changed(baseline, legal, (trigger,)) is True
    assert only_triggered_fields_changed(baseline, illegal, (trigger,)) is False
    assert trigger_paths((trigger,)) == ("rules[0].object",)


def test_structural_admission_gate_required_before_implementable() -> None:
    baseline = _baseline()
    trigger = _object_trigger()
    candidate = apply_field_patch(
        baseline, rule_index=0, canonical_field="object", value="records"
    )

    reject_gate = StructuralAdmissionGate(
        StructuralAdmissionPolicy(tools=(StructuralTool.HAMMER_CVC5,)),
        validators=(
            make_rejecting_binding(
                validator_id="hammer_cvc5",
                tool=StructuralTool.HAMMER_CVC5,
                detail="forced reject",
            ),
        ),
    )
    teacher = LeanstralSelectiveProposalTeacher(
        mode=ProposalMode.DRY_RUN,
        admission_gate=reject_gate,
    )
    receipt = teacher.propose(
        case_id="gate-reject",
        baseline_l1=baseline,
        triggers=(trigger,),
        candidate_l1=candidate,
    )
    assert receipt.implementable is False
    assert receipt.outcome is ProposalOutcome.ADMISSION_REJECTED
    assert receipt.prior_l1_unchanged is True
    assert receipt.admission_disposition == (
        AdmissionDisposition.VALIDATOR_REJECT.value
    )

    accept_gate = StructuralAdmissionGate(
        StructuralAdmissionPolicy(
            tools=(StructuralTool.HAMMER_CVC5, StructuralTool.LEAN),
        ),
        validators=(
            make_passing_binding(
                validator_id="hammer_cvc5",
                tool=StructuralTool.HAMMER_CVC5,
            ),
            make_passing_binding(
                validator_id="lean",
                tool=StructuralTool.LEAN,
            ),
        ),
    )
    teacher_ok = LeanstralSelectiveProposalTeacher(
        mode=ProposalMode.DRY_RUN,
        admission_gate=accept_gate,
    )
    accepted = teacher_ok.propose(
        case_id="gate-accept",
        baseline_l1=baseline,
        triggers=(trigger,),
        candidate_l1=candidate,
    )
    assert accepted.implementable is True
    assert accepted.outcome is ProposalOutcome.ACCEPTED
    assert accepted.admission_disposition == AdmissionDisposition.ACCEPTED.value
    assert accepted.packet is not None
    assert accepted.packet.implementable is True
    # Gate accept is what authorized implementable — packet admissions agree.
    assert all(
        item.disposition is AdmissionDisposition.ACCEPTED
        for item in accepted.packet.admission_receipts
    )


def test_implementable_true_impossible_without_admission_accept() -> None:
    with pytest.raises(
        PlateauLeanstralProposalError,
        match="StructuralAdmissionGate accept|admission",
    ):
        LeanstralProposalCaseReceipt(
            case_id="bad",
            outcome=ProposalOutcome.ACCEPTED,
            mode=ProposalMode.DRY_RUN,
            baseline_l1_digest="a" * 64,
            admitted_l1_digest="b" * 64,
            prior_l1_unchanged=False,
            only_triggered_fields_changed=True,
            implementable=True,
            admission_disposition=AdmissionDisposition.VALIDATOR_REJECT.value,
            triggers=(_object_trigger(),),
            allowed_field_paths=("rules[0].object",),
        )


def test_live_path_records_retry_exhausted_separately() -> None:
    baseline = _baseline()
    trigger = _object_trigger()
    client = RecordingClient(
        [
            LeanstralTimeoutError("timeout 1"),
            LeanstralTimeoutError("timeout 2"),
        ]
    )
    policy = SelectiveRepairPolicy(candidate_count=2)
    repairer = SelectiveLeanstralRepair(
        FixedConstructor(baseline),
        client=client,
        policy=policy,
        selector=_passing_selector(policy),
    )
    teacher = LeanstralSelectiveProposalTeacher(
        mode=ProposalMode.LIVE,
        client=client,
        selective_repair=repairer,
        repair_policy=policy,
    )
    request = ConstructorRequest(
        "The controller must delete the records.",
        VOCABULARY,
        {"case_id": "live-retry"},
    )
    receipt = teacher.propose(
        case_id="live-retry",
        baseline_l1=baseline,
        triggers=(trigger,),
        request=request,
    )
    assert receipt.mode is ProposalMode.LIVE
    assert receipt.outcome is ProposalOutcome.RETRY_EXHAUSTED
    assert receipt.retry_exhausted is True
    assert receipt.implementable is False
    assert receipt.prior_l1_unchanged is True
    assert receipt.model_calls == 2
    assert len(client.calls) == 2

    sealed = PlateauLeanstralProposalReceipts(
        cases=(receipt,),
        mode=ProposalMode.LIVE,
        reliability=aggregate_proposal_reliability((receipt,)),
        fixture_pack_id=None,
    )
    assert sealed.retry_exhausted_rate == pytest.approx(1.0)
    assert sealed.accept_rate == pytest.approx(0.0)
    assert sealed.reliability.to_dict()["end_to_end_loss"] is None


def test_live_path_accepts_only_triggered_repair_after_admission() -> None:
    baseline = _baseline()
    trigger = _object_trigger()
    repaired = apply_field_patch(
        baseline, rule_index=0, canonical_field="object", value="records"
    )
    client = RecordingClient([repaired.to_dict(), repaired.to_dict()])
    policy = SelectiveRepairPolicy(candidate_count=2)
    repairer = SelectiveLeanstralRepair(
        FixedConstructor(baseline),
        client=client,
        policy=policy,
        selector=_passing_selector(policy),
    )
    teacher = LeanstralSelectiveProposalTeacher(
        mode=ProposalMode.LIVE,
        client=client,
        selective_repair=repairer,
        repair_policy=policy,
    )
    request = ConstructorRequest(
        "The controller must delete the records.",
        VOCABULARY,
        {"case_id": "live-accept"},
    )
    receipt = teacher.propose(
        case_id="live-accept",
        baseline_l1=baseline,
        triggers=(trigger,),
        request=request,
    )
    assert receipt.outcome is ProposalOutcome.ACCEPTED
    assert receipt.implementable is True
    assert receipt.only_triggered_fields_changed is True
    assert receipt.admission_disposition == AdmissionDisposition.ACCEPTED.value
    assert receipt.model_calls >= 1
    assert receipt.packet is not None
    assert receipt.packet.implementable is True
    assert receipt.retry_exhausted is False


def test_rejects_retain_prior_l1_digest() -> None:
    baseline = _baseline()
    trigger = _object_trigger()
    illegal = apply_field_patch(
        apply_field_patch(
            baseline, rule_index=0, canonical_field="object", value="records"
        ),
        rule_index=1,
        canonical_field="action",
        value="delete",
    )
    teacher = LeanstralSelectiveProposalTeacher(mode=ProposalMode.DRY_RUN)
    receipt = teacher.propose(
        case_id="retain-prior",
        baseline_l1=baseline,
        triggers=(trigger,),
        candidate_l1=illegal,
    )
    assert receipt.outcome is ProposalOutcome.ADMISSION_REJECTED
    assert receipt.prior_l1_unchanged is True
    assert receipt.admitted_l1_digest == receipt.baseline_l1_digest
    assert receipt.implementable is False
    if receipt.admitted_l1 is not None:
        assert receipt.admitted_l1 == baseline


def test_receipts_round_trip_and_checked_in_artifact(tmp_path: Path) -> None:
    sealed = build_dry_run_proposal_receipts()
    path = tmp_path / "plateau_leanstral_proposal_receipts.json"
    payload = write_plateau_leanstral_proposal_receipts(path, receipts=sealed)
    loaded = load_plateau_leanstral_proposal_receipts(path)
    assert loaded.receipts_cid == sealed.receipts_cid
    assert loaded.accept_rate == sealed.accept_rate
    assert loaded.retry_exhausted_rate == sealed.retry_exhausted_rate
    assert payload["interface"] == PLATEAU_LEANSTRAL_PROPOSAL_RECEIPTS_INTERFACE
    assert payload["schema_version"] == PLATEAU_LEANSTRAL_PROPOSAL_RECEIPTS_SCHEMA
    assert payload["leanstral_is_default_realizer"] is False
    assert payload["doctrine"]["structural_admission_before_implementable"] is True
    assert payload["reliability"]["separate_from_end_to_end_loss"] is True

    # Checked-in workspace artifact must parse and validate.
    if RECEIPTS_PATH.is_file():
        checked_in = load_plateau_leanstral_proposal_receipts(RECEIPTS_PATH)
        validate_dry_run_fixture_pack(checked_in)
        assert checked_in.mode is ProposalMode.DRY_RUN
        assert checked_in.task_id == PLATEAU_BREAK_TASK_ID


def test_teacher_never_marks_leanstral_as_default_realizer() -> None:
    sealed = build_dry_run_proposal_receipts()
    assert sealed.leanstral_is_default_realizer is False
    assert sealed.production_realizer == "deterministic"
    with pytest.raises(PlateauLeanstralProposalError, match="default realizer"):
        PlateauLeanstralProposalReceipts(
            cases=sealed.cases,
            mode=ProposalMode.DRY_RUN,
            reliability=sealed.reliability,
            leanstral_is_default_realizer=True,
        )


def test_dry_run_does_not_require_constructor_request() -> None:
    teacher = LeanstralSelectiveProposalTeacher(mode=ProposalMode.DRY_RUN)
    baseline = _baseline()
    candidate = apply_field_patch(
        baseline, rule_index=0, canonical_field="object", value="records"
    )
    receipt = teacher.propose(
        case_id="no-request",
        baseline_l1=baseline,
        triggers=(_object_trigger(),),
        candidate_l1=candidate,
    )
    assert receipt.implementable is True


def test_live_mode_requires_request_when_candidate_missing() -> None:
    teacher = LeanstralSelectiveProposalTeacher(
        mode=ProposalMode.LIVE,
        client=RecordingClient([]),
    )
    with pytest.raises(PlateauLeanstralProposalError, match="ConstructorRequest"):
        teacher.propose(
            case_id="needs-request",
            baseline_l1=_baseline(),
            triggers=(_object_trigger(),),
        )


def test_parse_rejects_metric_drift() -> None:
    sealed = build_dry_run_proposal_receipts()
    payload = sealed.to_dict()
    payload["reliability"] = dict(payload["reliability"])  # type: ignore[arg-type]
    # Keep counts internally consistent but drift from case rows.
    payload["reliability"]["accepted_proposals"] = 0  # type: ignore[index]
    payload["reliability"]["admission_rejected_proposals"] = (
        int(payload["reliability"]["admission_rejected_proposals"]) + 1  # type: ignore[index]
    )
    with pytest.raises(
        PlateauLeanstralProposalError,
        match="reliability|accepted_proposals",
    ):
        parse_plateau_leanstral_proposal_receipts(payload)
