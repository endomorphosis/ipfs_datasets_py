"""Unit tests for PLAT-040 / PLAT2-040 Leanstral selective proposal teacher.

PLAT-040 covers the pilot dry-run fixture pack and general teacher contracts.
PLAT2-040 extends the same StructuralAdmission-gated pipeline to the
preregistered holdout residual population (activation cases + control
outcomes) and seals ``holdout_leanstral_proposal_receipts.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json
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
    RECEIPTS_CID_CODEC,
    RECEIPTS_CID_SCOPE,
    RETRY_EXHAUSTED_RATE_DEFINITION,
    TEACHER_IDENTITY,
    DryRunFixtureCase,
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

# PLAT2-040 holdout teacher receipts (prover-gated on holdout residuals).
HOLDOUT_RECEIPTS_RELATIVE_PATH = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "holdout_leanstral_proposal_receipts.json"
)
HOLDOUT_RECEIPTS_PATH = ROOT / HOLDOUT_RECEIPTS_RELATIVE_PATH
HOLDOUT_CASES_PATH = (
    ROOT / "tests/fixtures/semantic_roundtrip/holdout_cases.json"
)
HOLDOUT_CATALOG_PATH = (
    ROOT
    / "workspace/benchmarks/semantic-roundtrip-compositions/"
    / "holdout_residual_catalog.json"
)
HOLDOUT_TASK_ID = "PLAT2-040"
HOLDOUT_BOARD_NAMESPACE = "semantic-roundtrip-plateau-holdout-v1"
HOLDOUT_EVIDENCE = "PLAT2EV040TCH"
HOLDOUT_FIXTURE_PACK_ID = "holdout-leanstral-proposal-dry-run-fixtures@1"
HOLDOUT_ACTIVATION_CASE_IDS = (
    "missing_temporal",
    "low_confidence_object",
    "contradictory_modality",
)

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


# ---------------------------------------------------------------------------
# PLAT2-040 — prover-gated teachers on holdout residuals
# ---------------------------------------------------------------------------


def _repair_trigger_from_binding(raw: dict[str, Any]) -> RepairTrigger:
    """Build a RepairTrigger from a holdout score_bindings trigger row."""

    return RepairTrigger(
        rule_index=int(raw["rule_index"]),
        canonical_field=str(raw["canonical_field"]),
        kind=RepairTriggerKind(raw["kind"]),
        confidence=raw.get("confidence"),  # type: ignore[arg-type]
        evidence=raw.get("evidence"),  # type: ignore[arg-type]
    )


def _holdout_activation_rows() -> list[dict[str, Any]]:
    assert HOLDOUT_CASES_PATH.is_file(), (
        "holdout_cases.json must exist (PLAT2-020)"
    )
    rows = json.loads(HOLDOUT_CASES_PATH.read_text(encoding="utf-8"))
    assert isinstance(rows, list)
    activation: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        bindings = row.get("score_bindings") or {}
        if isinstance(bindings, dict) and bindings.get("triggers"):
            activation.append(row)
    by_id = {str(row["id"]): row for row in activation}
    missing = [cid for cid in HOLDOUT_ACTIVATION_CASE_IDS if cid not in by_id]
    assert not missing, f"missing holdout activation cases: {missing}"
    return [by_id[cid] for cid in HOLDOUT_ACTIVATION_CASE_IDS]


def holdout_dry_run_fixture_pack() -> tuple[DryRunFixtureCase, ...]:
    """Offline holdout fixture pack (no live Leanstral model required).

    Covers the three selective-repair activation holdout cases plus admission
    reject, retry_exhausted, and not_triggered control outcomes so dry-run
    always exercises StructuralAdmission and reliability counters.
    """

    activation = _holdout_activation_rows()
    fixtures: list[DryRunFixtureCase] = []
    for row in activation:
        bindings = row["score_bindings"]
        baseline = CanonicalRuleIR.from_dict(bindings["baseline_ir"])
        candidate = CanonicalRuleIR.from_dict(bindings["repaired_ir"])
        triggers = tuple(
            _repair_trigger_from_binding(item) for item in bindings["triggers"]
        )
        vocab = (
            AllowedAtomVocabulary.from_dict(row["allowed_atoms"])
            if row.get("allowed_atoms")
            else None
        )
        fixtures.append(
            DryRunFixtureCase(
                case_id=str(row["id"]),
                baseline_l1=baseline,
                triggers=triggers,
                candidate_l1=candidate,
                expected_outcome=ProposalOutcome.ACCEPTED,
                residual_field_paths=tuple(
                    str(item["path"]) for item in bindings["triggers"]
                ),
                detail=f"holdout dry-run selective proposal for {row['id']}",
                source_text=str(row["source_text"]),
                vocabulary=vocab,
            )
        )

    # Admission reject: object trigger only, but candidate also mutates actor.
    lc = next(row for row in activation if row["id"] == "low_confidence_object")
    lc_bindings = lc["score_bindings"]
    lc_baseline = CanonicalRuleIR.from_dict(lc_bindings["baseline_ir"])
    lc_legal = CanonicalRuleIR.from_dict(lc_bindings["repaired_ir"])
    lc_illegal = apply_field_patch(
        lc_legal, rule_index=0, canonical_field="actor", value="processor"
    )
    lc_triggers = tuple(
        _repair_trigger_from_binding(item) for item in lc_bindings["triggers"]
    )
    fixtures.append(
        DryRunFixtureCase(
            case_id="holdout_admission_reject_untriggered",
            baseline_l1=lc_baseline,
            triggers=lc_triggers,
            candidate_l1=lc_illegal,
            expected_outcome=ProposalOutcome.ADMISSION_REJECTED,
            residual_field_paths=tuple(
                str(item["path"]) for item in lc_bindings["triggers"]
            ),
            detail=(
                "holdout dry-run candidate changes untriggered field; "
                "gate retains prior L1"
            ),
            source_text=str(lc["source_text"]),
        )
    )
    fixtures.append(
        DryRunFixtureCase(
            case_id="holdout_retry_exhausted",
            baseline_l1=lc_baseline,
            triggers=lc_triggers,
            candidate_l1=None,
            expected_outcome=ProposalOutcome.RETRY_EXHAUSTED,
            residual_field_paths=tuple(
                str(item["path"]) for item in lc_bindings["triggers"]
            ),
            force_retry_exhausted=True,
            detail="holdout dry-run live-path analogue: all model calls failed",
            source_text=str(lc["source_text"]),
        )
    )
    mt = next(row for row in activation if row["id"] == "missing_temporal")
    fixtures.append(
        DryRunFixtureCase(
            case_id="holdout_not_triggered",
            baseline_l1=CanonicalRuleIR.from_dict(
                mt["score_bindings"]["baseline_ir"]
            ),
            triggers=(),
            candidate_l1=None,
            expected_outcome=ProposalOutcome.NOT_TRIGGERED,
            residual_field_paths=(),
            detail="holdout dry-run control: empty triggers emit no proposal",
            source_text=str(mt["source_text"]),
        )
    )
    return tuple(fixtures)


def build_holdout_dry_run_proposal_receipts(
    *,
    fixtures: tuple[DryRunFixtureCase, ...] | None = None,
    admission_gate: StructuralAdmissionGate | None = None,
) -> PlateauLeanstralProposalReceipts:
    """Seal holdout teacher receipts under the PLAT2 board namespace."""

    pack = fixtures if fixtures is not None else holdout_dry_run_fixture_pack()
    teacher = LeanstralSelectiveProposalTeacher(
        mode=ProposalMode.DRY_RUN,
        admission_gate=admission_gate,
    )
    case_receipts = tuple(teacher.propose_fixture(item) for item in pack)
    reliability = aggregate_proposal_reliability(case_receipts)
    catalog_cid: str | None = None
    if HOLDOUT_CATALOG_PATH.is_file():
        catalog = json.loads(HOLDOUT_CATALOG_PATH.read_text(encoding="utf-8"))
        raw_cid = catalog.get("catalog_cid")
        if isinstance(raw_cid, str) and raw_cid.strip():
            catalog_cid = raw_cid
    return PlateauLeanstralProposalReceipts(
        cases=case_receipts,
        mode=ProposalMode.DRY_RUN,
        reliability=reliability,
        fixture_pack_id=HOLDOUT_FIXTURE_PACK_ID,
        catalog_cid=catalog_cid,
        task_id=HOLDOUT_TASK_ID,
        board_namespace=HOLDOUT_BOARD_NAMESPACE,
        evidence=HOLDOUT_EVIDENCE,
    ).with_receipts_cid()


def validate_holdout_dry_run_fixture_pack(
    receipts: PlateauLeanstralProposalReceipts | None = None,
) -> PlateauLeanstralProposalReceipts:
    """Fail closed when holdout dry-run fixtures miss PLAT2-040 acceptance."""

    sealed = receipts or build_holdout_dry_run_proposal_receipts()
    if sealed.mode is not ProposalMode.DRY_RUN:
        raise PlateauLeanstralProposalError(
            "holdout fixture pack validation requires dry_run mode"
        )
    if sealed.task_id != HOLDOUT_TASK_ID:
        raise PlateauLeanstralProposalError(
            f"holdout receipts task_id must be {HOLDOUT_TASK_ID}"
        )
    if sealed.board_namespace != HOLDOUT_BOARD_NAMESPACE:
        raise PlateauLeanstralProposalError(
            f"holdout receipts board_namespace must be {HOLDOUT_BOARD_NAMESPACE}"
        )
    by_id = sealed.by_case_id()
    expected = {item.case_id: item for item in holdout_dry_run_fixture_pack()}
    for case_id, fixture in expected.items():
        if case_id not in by_id:
            raise PlateauLeanstralProposalError(
                f"missing holdout dry-run fixture receipt: {case_id}"
            )
        receipt = by_id[case_id]
        if receipt.outcome is not fixture.expected_outcome:
            raise PlateauLeanstralProposalError(
                f"{case_id}: expected outcome {fixture.expected_outcome.value}, "
                f"got {receipt.outcome.value}"
            )
        if receipt.implementable and receipt.admission_disposition != (
            AdmissionDisposition.ACCEPTED.value
        ):
            raise PlateauLeanstralProposalError(
                f"{case_id}: implementable without StructuralAdmissionGate accept"
            )
        if (
            receipt.outcome is ProposalOutcome.ACCEPTED
            and not receipt.only_triggered_fields_changed
        ):
            raise PlateauLeanstralProposalError(
                f"{case_id}: accepted proposal changed untriggered fields"
            )
        if (
            receipt.outcome is ProposalOutcome.ADMISSION_REJECTED
            and not receipt.prior_l1_unchanged
        ):
            raise PlateauLeanstralProposalError(
                f"{case_id}: reject must retain prior L1"
            )
        if (
            receipt.outcome is ProposalOutcome.RETRY_EXHAUSTED
            and not receipt.retry_exhausted
        ):
            raise PlateauLeanstralProposalError(
                f"{case_id}: retry_exhausted outcome missing flag"
            )
    rel = sealed.reliability
    if rel.accept_rate is None or rel.retry_exhausted_rate is None:
        raise PlateauLeanstralProposalError(
            "holdout fixture pack must record accept_rate and retry_exhausted_rate"
        )
    rel_payload = rel.to_dict()
    if rel_payload.get("end_to_end_loss") is not None:
        raise PlateauLeanstralProposalError(
            "holdout proposal reliability must not report end_to_end_loss"
        )
    if sealed.leanstral_is_default_realizer is not False:
        raise PlateauLeanstralProposalError(
            "Leanstral must not be the default realizer on holdout path"
        )
    if sealed.structural_admission_required is not True:
        raise PlateauLeanstralProposalError(
            "StructuralAdmission required on holdout teacher path"
        )
    if not sealed.receipts_cid:
        raise PlateauLeanstralProposalError(
            "holdout receipts must be CID-bindable (receipts_cid missing)"
        )
    return sealed


def test_holdout_dry_run_fixture_pack_covers_activation_and_controls() -> None:
    pack = holdout_dry_run_fixture_pack()
    outcomes = {item.case_id: item.expected_outcome for item in pack}
    for case_id in HOLDOUT_ACTIVATION_CASE_IDS:
        assert outcomes[case_id] is ProposalOutcome.ACCEPTED
    assert (
        outcomes["holdout_admission_reject_untriggered"]
        is ProposalOutcome.ADMISSION_REJECTED
    )
    assert outcomes["holdout_retry_exhausted"] is ProposalOutcome.RETRY_EXHAUSTED
    assert outcomes["holdout_not_triggered"] is ProposalOutcome.NOT_TRIGGERED


def test_holdout_dry_run_fixtures_pass_without_live_model() -> None:
    # No LeanstralClient; dry-run must not touch the network.
    sealed = build_holdout_dry_run_proposal_receipts()
    validate_holdout_dry_run_fixture_pack(sealed)

    assert sealed.mode is ProposalMode.DRY_RUN
    assert sealed.task_id == HOLDOUT_TASK_ID
    assert sealed.board_namespace == HOLDOUT_BOARD_NAMESPACE
    assert sealed.evidence == HOLDOUT_EVIDENCE
    assert sealed.fixture_pack_id == HOLDOUT_FIXTURE_PACK_ID
    assert sealed.leanstral_is_default_realizer is False
    assert sealed.production_runtime_unchanged is True
    assert sealed.structural_admission_required is True
    assert sealed.receipts_cid
    assert sealed.accept_rate is not None
    assert sealed.retry_exhausted_rate is not None
    assert sealed.catalog_cid  # bound to holdout residual catalog

    by_id = sealed.by_case_id()
    for case_id in HOLDOUT_ACTIVATION_CASE_IDS:
        accepted = by_id[case_id]
        assert accepted.outcome is ProposalOutcome.ACCEPTED
        assert accepted.implementable is True
        assert accepted.admission_disposition == AdmissionDisposition.ACCEPTED.value
        assert accepted.only_triggered_fields_changed is True
        assert accepted.prior_l1_unchanged is False
        assert accepted.packet is not None
        assert accepted.packet.implementable is True
        assert accepted.packet.proposals[0].teacher == "leanstral"
        assert accepted.packet.proposals[0].semantic_authority is False
        assert all(
            item.disposition is AdmissionDisposition.ACCEPTED
            for item in accepted.packet.admission_receipts
        )

    rejected = by_id["holdout_admission_reject_untriggered"]
    assert rejected.outcome is ProposalOutcome.ADMISSION_REJECTED
    assert rejected.implementable is False
    assert rejected.prior_l1_unchanged is True
    assert rejected.admitted_l1_digest == rejected.baseline_l1_digest
    assert rejected.admission_disposition == (
        AdmissionDisposition.VALIDATOR_REJECT.value
    )

    exhausted = by_id["holdout_retry_exhausted"]
    assert exhausted.outcome is ProposalOutcome.RETRY_EXHAUSTED
    assert exhausted.retry_exhausted is True
    assert exhausted.implementable is False
    assert exhausted.prior_l1_unchanged is True

    control = by_id["holdout_not_triggered"]
    assert control.outcome is ProposalOutcome.NOT_TRIGGERED
    assert control.implementable is False


def test_holdout_only_triggered_fields_change_on_accepted() -> None:
    for row in _holdout_activation_rows():
        bindings = row["score_bindings"]
        baseline = CanonicalRuleIR.from_dict(bindings["baseline_ir"])
        candidate = CanonicalRuleIR.from_dict(bindings["repaired_ir"])
        triggers = tuple(
            _repair_trigger_from_binding(item) for item in bindings["triggers"]
        )
        assert only_triggered_fields_changed(baseline, candidate, triggers) is True
        # Mutating an untriggered field must fail the invariant.
        if not triggers:
            continue
        triggered = {item.canonical_field for item in triggers}
        rule_index = triggers[0].rule_index
        # Prefer actor; fall back to object when actor is already triggered.
        if "actor" not in triggered:
            other_field = "actor"
            current = candidate.rules[rule_index].actor
            other_value = "controller" if current != "controller" else "processor"
        else:
            other_field = "object"
            current = candidate.rules[rule_index].object
            other_value = "records" if current != "records" else "personal_data"
        illegal = apply_field_patch(
            candidate,
            rule_index=rule_index,
            canonical_field=other_field,
            value=other_value,
        )
        assert only_triggered_fields_changed(baseline, illegal, triggers) is False


def test_holdout_structural_admission_required_before_implementable() -> None:
    row = next(
        item
        for item in _holdout_activation_rows()
        if item["id"] == "missing_temporal"
    )
    bindings = row["score_bindings"]
    baseline = CanonicalRuleIR.from_dict(bindings["baseline_ir"])
    candidate = CanonicalRuleIR.from_dict(bindings["repaired_ir"])
    triggers = tuple(
        _repair_trigger_from_binding(item) for item in bindings["triggers"]
    )

    reject_gate = StructuralAdmissionGate(
        StructuralAdmissionPolicy(tools=(StructuralTool.HAMMER_CVC5,)),
        validators=(
            make_rejecting_binding(
                validator_id="hammer_cvc5",
                tool=StructuralTool.HAMMER_CVC5,
                detail="forced holdout reject",
            ),
        ),
    )
    teacher = LeanstralSelectiveProposalTeacher(
        mode=ProposalMode.DRY_RUN,
        admission_gate=reject_gate,
    )
    receipt = teacher.propose(
        case_id="holdout-gate-reject",
        baseline_l1=baseline,
        triggers=triggers,
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
        case_id="holdout-gate-accept",
        baseline_l1=baseline,
        triggers=triggers,
        candidate_l1=candidate,
    )
    assert accepted.implementable is True
    assert accepted.outcome is ProposalOutcome.ACCEPTED
    assert accepted.admission_disposition == AdmissionDisposition.ACCEPTED.value
    assert accepted.only_triggered_fields_changed is True
    assert accepted.packet is not None
    assert accepted.packet.implementable is True


def test_holdout_receipts_are_cid_bindable(tmp_path: Path) -> None:
    sealed = build_holdout_dry_run_proposal_receipts()
    payload = sealed.to_dict()
    assert payload["receipts_cid"] == sealed.receipts_cid
    assert payload["receipts_cid_codec"] == RECEIPTS_CID_CODEC
    assert payload["receipts_cid_scope"] == RECEIPTS_CID_SCOPE

    # CID is bound over the payload without the receipts_cid fields.
    bindable = dict(payload)
    bindable.pop("receipts_cid", None)
    bindable.pop("receipts_cid_codec", None)
    bindable.pop("receipts_cid_scope", None)
    assert cid_for_dag_json(bindable) == sealed.receipts_cid

    path = tmp_path / "holdout_leanstral_proposal_receipts.json"
    written = write_plateau_leanstral_proposal_receipts(path, receipts=sealed)
    loaded = load_plateau_leanstral_proposal_receipts(path)
    assert loaded.receipts_cid == sealed.receipts_cid
    assert loaded.task_id == HOLDOUT_TASK_ID
    assert loaded.board_namespace == HOLDOUT_BOARD_NAMESPACE
    assert written["catalog_cid"] == sealed.catalog_cid
    # Round-trip must re-validate CID binding.
    parse_plateau_leanstral_proposal_receipts(written)


def test_holdout_checked_in_receipts_artifact() -> None:
    assert HOLDOUT_RECEIPTS_PATH.is_file(), (
        "holdout_leanstral_proposal_receipts.json must be written by PLAT2-040"
    )
    checked_in = load_plateau_leanstral_proposal_receipts(HOLDOUT_RECEIPTS_PATH)
    validate_holdout_dry_run_fixture_pack(checked_in)

    assert checked_in.mode is ProposalMode.DRY_RUN
    assert checked_in.task_id == HOLDOUT_TASK_ID
    assert checked_in.board_namespace == HOLDOUT_BOARD_NAMESPACE
    assert checked_in.evidence == HOLDOUT_EVIDENCE
    assert checked_in.fixture_pack_id == HOLDOUT_FIXTURE_PACK_ID
    assert checked_in.structural_admission_required is True
    assert checked_in.leanstral_is_default_realizer is False
    assert checked_in.receipts_cid
    assert checked_in.catalog_cid

    # Regenerating from fixtures is deterministic. Packet digests may advance
    # when PLAT2-030 repair-dev packets are rewritten; structural teacher
    # outcomes and catalog binding must still match the checked-in artifact.
    regenerated = build_holdout_dry_run_proposal_receipts()
    assert regenerated.catalog_cid == checked_in.catalog_cid
    assert regenerated.task_id == checked_in.task_id
    assert regenerated.board_namespace == checked_in.board_namespace
    assert regenerated.mode is checked_in.mode
    # Self-consistent CID binding on the live seal.
    assert regenerated.with_receipts_cid().receipts_cid == regenerated.receipts_cid

    by_id = checked_in.by_case_id()
    regen_by_id = regenerated.by_case_id()
    assert set(by_id) == set(regen_by_id)
    for case_id in HOLDOUT_ACTIVATION_CASE_IDS:
        assert case_id in by_id
        assert by_id[case_id].implementable is True
        assert by_id[case_id].only_triggered_fields_changed is True
        assert by_id[case_id].admission_disposition == (
            AdmissionDisposition.ACCEPTED.value
        )
        assert regen_by_id[case_id].implementable is True
        assert regen_by_id[case_id].outcome is by_id[case_id].outcome
        assert (
            regen_by_id[case_id].admission_disposition
            == by_id[case_id].admission_disposition
        )
    assert by_id["holdout_admission_reject_untriggered"].implementable is False
    assert by_id["holdout_admission_reject_untriggered"].prior_l1_unchanged is True
    assert (
        regen_by_id["holdout_admission_reject_untriggered"].implementable is False
    )
    assert (
        regen_by_id["holdout_admission_reject_untriggered"].prior_l1_unchanged
        is True
    )


def test_holdout_reliability_separate_from_e2e() -> None:
    sealed = build_holdout_dry_run_proposal_receipts()
    rel = sealed.reliability
    payload = rel.to_dict()
    assert payload["separate_from_end_to_end_loss"] is True
    assert payload["end_to_end_loss"] is None
    assert "accept_rate" in payload and "retry_exhausted_rate" in payload
    assert rel.accepted_proposals >= 3  # three activation accepts
    assert rel.retry_exhausted_proposals >= 1
    assert rel.admission_rejected_proposals >= 1
    assert rel.not_triggered >= 1
    assert rel.proposal_attempts == (
        rel.accepted_proposals
        + rel.retry_exhausted_proposals
        + rel.admission_rejected_proposals
        + rel.model_rejected_proposals
        + rel.failed_proposals
    )
    assert sealed.accept_rate == pytest.approx(
        rel.accepted_proposals / rel.proposal_attempts
    )
    assert sealed.retry_exhausted_rate == pytest.approx(
        rel.retry_exhausted_proposals / rel.proposal_attempts
    )
