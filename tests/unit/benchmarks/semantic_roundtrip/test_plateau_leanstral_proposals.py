"""Unit tests for PLAT-040 / PLAT2-040 Leanstral selective proposal teacher.

PLAT-040 covers the pilot dry-run fixture pack and general teacher contracts.
PLAT2-040 also seals the holdout Leanstral proposal pack
(``holdout_leanstral_proposal_receipts.json``) and the repair-development
multi-teacher composite (``repair_dev_teacher_receipts.json``).
"""

from __future__ import annotations

import hashlib
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
from benchmarks.semantic_roundtrip.model_output_recovery import (
    DIRECT_ROUTE_ID,
    ModelRejectionReason,
    SYMAI_ROUTE,
    classify_model_rejection,
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

# PLAT2-040 repair-development multi-teacher receipts (evidence-gated).
# Additive to the holdout Leanstral proposal pack above — do not replace it.
REPAIR_DEV_TEACHER_RECEIPTS_RELATIVE_PATH = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "repair_dev_teacher_receipts.json"
)
REPAIR_DEV_TEACHER_RECEIPTS_PATH = ROOT / REPAIR_DEV_TEACHER_RECEIPTS_RELATIVE_PATH
REPAIR_DEV_CASES_PATH = (
    ROOT / "tests/fixtures/semantic_roundtrip/repair_dev_cases.json"
)
REPAIR_DEV_CATALOG_PATH = (
    ROOT
    / "workspace/benchmarks/semantic-roundtrip-compositions/"
    / "repair_dev_residual_catalog.json"
)
REPAIR_DEV_REGISTRY_PATH = (
    ROOT
    / "workspace/benchmarks/semantic-roundtrip-compositions/"
    / "repair_dev_intervention_registry.json"
)
REPAIR_DEV_PACKET_METRICS_PATH = (
    ROOT
    / "workspace/benchmarks/semantic-roundtrip-compositions/"
    / "repair_dev_packet_context_metrics.json"
)
REPAIR_DEV_TASK_ID = "PLAT2-040"
REPAIR_DEV_GOAL_ID = "PLAT2-G040"
REPAIR_DEV_BOARD_NAMESPACE = "semantic-roundtrip-plateau-holdout-v2"
REPAIR_DEV_EVIDENCE = "PLAT2EV040TCH"
REPAIR_DEV_FIXTURE_PACK_ID = "repair-dev-teacher-dry-run-fixtures@1"
REPAIR_DEV_TEACHER_INTERFACE = "RepairDevTeacherReceipts@1"
REPAIR_DEV_TEACHER_SCHEMA = (
    "ipfs-datasets.semantic-roundtrip-repair-dev-teacher-receipts.v1"
)
REPAIR_DEV_POPULATION_KIND = "repair_development"
REPAIR_DEV_ACTIVATION_CASE_IDS = (
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


# ---------------------------------------------------------------------------
# PLAT2-040 — evidence-gated teachers on repair-development residuals
# Additive suite: holdout tests above remain authoritative for
# holdout_leanstral_proposal_receipts.json; this section seals
# repair_dev_teacher_receipts.json without weakening prior assertions.
# ---------------------------------------------------------------------------


def _repair_dev_activation_rows() -> list[dict[str, Any]]:
    assert REPAIR_DEV_CASES_PATH.is_file(), (
        "repair_dev_cases.json must exist (PLAT2-020)"
    )
    rows = json.loads(REPAIR_DEV_CASES_PATH.read_text(encoding="utf-8"))
    assert isinstance(rows, list)
    activation: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        bindings = row.get("score_bindings") or {}
        if isinstance(bindings, dict) and bindings.get("triggers"):
            activation.append(row)
    by_id = {str(row["id"]): row for row in activation}
    missing = [
        cid for cid in REPAIR_DEV_ACTIVATION_CASE_IDS if cid not in by_id
    ]
    assert not missing, f"missing repair-dev activation cases: {missing}"
    return [by_id[cid] for cid in REPAIR_DEV_ACTIVATION_CASE_IDS]


def repair_dev_dry_run_fixture_pack() -> tuple[DryRunFixtureCase, ...]:
    """Offline repair-dev fixture pack (no live Leanstral model required).

    Covers the three selective-repair activation cases plus admission reject,
    retry_exhausted, and not_triggered control outcomes so dry-run always
    exercises StructuralAdmission and reliability counters.
    """

    activation = _repair_dev_activation_rows()
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
                detail=f"repair-dev dry-run selective proposal for {row['id']}",
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
            case_id="repair_dev_admission_reject_untriggered",
            baseline_l1=lc_baseline,
            triggers=lc_triggers,
            candidate_l1=lc_illegal,
            expected_outcome=ProposalOutcome.ADMISSION_REJECTED,
            residual_field_paths=tuple(
                str(item["path"]) for item in lc_bindings["triggers"]
            ),
            detail=(
                "repair-dev dry-run candidate changes untriggered field; "
                "gate retains prior L1"
            ),
            source_text=str(lc["source_text"]),
        )
    )
    fixtures.append(
        DryRunFixtureCase(
            case_id="repair_dev_retry_exhausted",
            baseline_l1=lc_baseline,
            triggers=lc_triggers,
            candidate_l1=None,
            expected_outcome=ProposalOutcome.RETRY_EXHAUSTED,
            residual_field_paths=tuple(
                str(item["path"]) for item in lc_bindings["triggers"]
            ),
            force_retry_exhausted=True,
            detail=(
                "repair-dev dry-run live-path analogue: all model calls failed"
            ),
            source_text=str(lc["source_text"]),
        )
    )
    mt = next(row for row in activation if row["id"] == "missing_temporal")
    fixtures.append(
        DryRunFixtureCase(
            case_id="repair_dev_not_triggered",
            baseline_l1=CanonicalRuleIR.from_dict(
                mt["score_bindings"]["baseline_ir"]
            ),
            triggers=(),
            candidate_l1=None,
            expected_outcome=ProposalOutcome.NOT_TRIGGERED,
            residual_field_paths=(),
            detail="repair-dev dry-run control: empty triggers emit no proposal",
            source_text=str(mt["source_text"]),
        )
    )
    return tuple(fixtures)


def build_repair_dev_leanstral_proposal_receipts(
    *,
    fixtures: tuple[DryRunFixtureCase, ...] | None = None,
    admission_gate: StructuralAdmissionGate | None = None,
) -> PlateauLeanstralProposalReceipts:
    """Seal repair-dev Leanstral proposal cases under the PLAT2 board namespace."""

    pack = fixtures if fixtures is not None else repair_dev_dry_run_fixture_pack()
    teacher = LeanstralSelectiveProposalTeacher(
        mode=ProposalMode.DRY_RUN,
        admission_gate=admission_gate,
    )
    case_receipts = tuple(teacher.propose_fixture(item) for item in pack)
    reliability = aggregate_proposal_reliability(case_receipts)
    catalog_cid: str | None = None
    if REPAIR_DEV_CATALOG_PATH.is_file():
        catalog = json.loads(REPAIR_DEV_CATALOG_PATH.read_text(encoding="utf-8"))
        raw_cid = catalog.get("catalog_cid")
        if isinstance(raw_cid, str) and raw_cid.strip():
            catalog_cid = raw_cid
    return PlateauLeanstralProposalReceipts(
        cases=case_receipts,
        mode=ProposalMode.DRY_RUN,
        reliability=reliability,
        fixture_pack_id=REPAIR_DEV_FIXTURE_PACK_ID,
        catalog_cid=catalog_cid,
        task_id=REPAIR_DEV_TASK_ID,
        board_namespace=REPAIR_DEV_BOARD_NAMESPACE,
        evidence=REPAIR_DEV_EVIDENCE,
    ).with_receipts_cid()


def validate_repair_dev_leanstral_fixture_pack(
    receipts: PlateauLeanstralProposalReceipts | None = None,
) -> PlateauLeanstralProposalReceipts:
    """Fail closed when repair-dev dry-run fixtures miss PLAT2-040 acceptance."""

    sealed = receipts or build_repair_dev_leanstral_proposal_receipts()
    if sealed.mode is not ProposalMode.DRY_RUN:
        raise PlateauLeanstralProposalError(
            "repair-dev fixture pack validation requires dry_run mode"
        )
    if sealed.task_id != REPAIR_DEV_TASK_ID:
        raise PlateauLeanstralProposalError(
            f"repair-dev receipts task_id must be {REPAIR_DEV_TASK_ID}"
        )
    if sealed.board_namespace != REPAIR_DEV_BOARD_NAMESPACE:
        raise PlateauLeanstralProposalError(
            "repair-dev receipts board_namespace must be "
            f"{REPAIR_DEV_BOARD_NAMESPACE}"
        )
    by_id = sealed.by_case_id()
    expected = {item.case_id: item for item in repair_dev_dry_run_fixture_pack()}
    for case_id, fixture in expected.items():
        if case_id not in by_id:
            raise PlateauLeanstralProposalError(
                f"missing repair-dev dry-run fixture receipt: {case_id}"
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
        if receipt.semantic_authority is not False:
            raise PlateauLeanstralProposalError(
                f"{case_id}: teacher receipt claimed semantic_authority"
            )
    rel = sealed.reliability
    if rel.accept_rate is None or rel.retry_exhausted_rate is None:
        raise PlateauLeanstralProposalError(
            "repair-dev fixture pack must record accept_rate and "
            "retry_exhausted_rate"
        )
    rel_payload = rel.to_dict()
    if rel_payload.get("end_to_end_loss") is not None:
        raise PlateauLeanstralProposalError(
            "repair-dev proposal reliability must not report end_to_end_loss"
        )
    if sealed.leanstral_is_default_realizer is not False:
        raise PlateauLeanstralProposalError(
            "Leanstral must not be the default realizer on repair-dev path"
        )
    if sealed.structural_admission_required is not True:
        raise PlateauLeanstralProposalError(
            "StructuralAdmission required on repair-dev teacher path"
        )
    if not sealed.receipts_cid:
        raise PlateauLeanstralProposalError(
            "repair-dev leanstral receipts must be CID-bindable"
        )
    return sealed


def load_repair_dev_teacher_receipts(
    path: Path | None = None,
) -> dict[str, Any]:
    """Load and validate the composite PLAT2-040 teacher receipts artifact."""

    target = path or REPAIR_DEV_TEACHER_RECEIPTS_PATH
    assert target.is_file(), f"missing teacher receipts: {target}"
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    validate_repair_dev_teacher_receipts(payload)
    return payload


def validate_repair_dev_teacher_receipts(payload: dict[str, Any]) -> None:
    """Fail closed when composite teacher receipts miss PLAT2-040 acceptance."""

    if payload.get("interface") != REPAIR_DEV_TEACHER_INTERFACE:
        raise PlateauLeanstralProposalError("teacher receipts interface mismatch")
    if payload.get("schema_version") != REPAIR_DEV_TEACHER_SCHEMA:
        raise PlateauLeanstralProposalError(
            "teacher receipts schema_version mismatch"
        )
    if payload.get("task_id") != REPAIR_DEV_TASK_ID:
        raise PlateauLeanstralProposalError(
            f"teacher receipts task_id must be {REPAIR_DEV_TASK_ID}"
        )
    if payload.get("board_namespace") != REPAIR_DEV_BOARD_NAMESPACE:
        raise PlateauLeanstralProposalError(
            "teacher receipts board_namespace mismatch"
        )
    if payload.get("population_kind") != REPAIR_DEV_POPULATION_KIND:
        raise PlateauLeanstralProposalError(
            "teacher receipts must target repair_development population"
        )
    if payload.get("mode") != ProposalMode.DRY_RUN.value:
        raise PlateauLeanstralProposalError(
            "checked-in teacher receipts must be dry_run when live model "
            "unavailable"
        )
    if payload.get("evidence") != REPAIR_DEV_EVIDENCE:
        raise PlateauLeanstralProposalError("teacher receipts evidence mismatch")

    # Bindings: packet, tree, intervention, provider/toolchain, assumptions, status.
    bindings = payload.get("bindings")
    if not isinstance(bindings, dict):
        raise PlateauLeanstralProposalError("bindings object required")
    for key in (
        "catalog_cid",
        "tree_cid",
        "population_cid",
        "intervention_registry_cid",
        "contract_cid",
        "baseline_report_cid",
        "packet_metrics_cid",
        "assumptions_digest",
    ):
        value = bindings.get(key)
        if not isinstance(value, str) or not value.strip():
            raise PlateauLeanstralProposalError(f"bindings.{key} required")

    assumptions = payload.get("assumptions")
    if not isinstance(assumptions, list) or not assumptions:
        raise PlateauLeanstralProposalError("assumptions must be a non-empty list")
    expected_digest = hashlib.sha256(
        json.dumps(
            assumptions, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    if bindings["assumptions_digest"] != expected_digest:
        raise PlateauLeanstralProposalError("assumptions_digest mismatch")

    # Direct / SyMAI route identities remain distinct; SyMAI no proof credit.
    routes = payload.get("route_identities")
    if not isinstance(routes, dict):
        raise PlateauLeanstralProposalError("route_identities required")
    if routes.get("routes_are_distinct") is not True:
        raise PlateauLeanstralProposalError("direct and SyMAI routes must be distinct")
    if routes.get("symai_proof_credit") is not False:
        raise PlateauLeanstralProposalError("SyMAI cannot receive proof credit")
    if routes.get("symai_cannot_receive_proof_credit") is not True:
        raise PlateauLeanstralProposalError(
            "symai_cannot_receive_proof_credit must be true"
        )
    if routes.get("direct_route") != DIRECT_ROUTE_ID:
        raise PlateauLeanstralProposalError("direct_route identity mismatch")
    if routes.get("symai_route") != SYMAI_ROUTE:
        raise PlateauLeanstralProposalError("symai_route identity mismatch")
    if routes.get("leanstral_route") == routes.get("symai_route"):
        raise PlateauLeanstralProposalError(
            "leanstral and symai routes must remain distinct"
        )

    symai = payload.get("symai_orchestration") or payload.get("methods", {}).get(
        "symai"
    )
    if not isinstance(symai, dict) or symai.get("proof_credit") is not False:
        raise PlateauLeanstralProposalError("SyMAI proof_credit must be false")
    if symai.get("executed") is not False:
        raise PlateauLeanstralProposalError(
            "SyMAI orchestration must not execute as a proof teacher"
        )

    # spaCy / AE remain diagnostics/guidance at declared status.
    spacy = payload.get("spacy_diagnostics") or {}
    ae = payload.get("autoencoder_guidance") or {}
    if not isinstance(spacy, dict) or spacy.get("semantic_authority") is not False:
        raise PlateauLeanstralProposalError(
            "spaCy diagnostics cannot claim semantic_authority"
        )
    if spacy.get("output_kind") != "diagnostics":
        raise PlateauLeanstralProposalError("spaCy output_kind must be diagnostics")
    if not isinstance(ae, dict) or ae.get("semantic_authority") is not False:
        raise PlateauLeanstralProposalError(
            "AE guidance cannot claim semantic_authority"
        )
    if ae.get("eligible") is not False or ae.get("executed") is not False:
        raise PlateauLeanstralProposalError(
            "terminal AE guidance must remain ineligible and unexecuted"
        )

    # StructuralAdmission: declared properties only; not e2e substitute.
    admission = payload.get("structural_admission")
    if not isinstance(admission, dict):
        raise PlateauLeanstralProposalError("structural_admission required")
    if admission.get("required") is not True:
        raise PlateauLeanstralProposalError("StructuralAdmission is required")
    if admission.get("may_substitute_for_e2e_loss") is not False:
        raise PlateauLeanstralProposalError(
            "StructuralAdmission cannot substitute for e2e loss"
        )
    if admission.get("semantic_authority") is not False:
        raise PlateauLeanstralProposalError(
            "StructuralAdmission semantic_authority must be false"
        )
    if admission.get("checks_declared_structural_properties_only") is not True:
        raise PlateauLeanstralProposalError(
            "StructuralAdmission must check only declared structural properties"
        )

    # Dry-run / negative controls always pass.
    neg = payload.get("negative_controls")
    if not isinstance(neg, dict):
        raise PlateauLeanstralProposalError("negative_controls required")
    for control_id in ("nc_no_edit", "nc_withhold_optional_teacher"):
        row = neg.get(control_id)
        if not isinstance(row, dict) or row.get("status") != "pass":
            raise PlateauLeanstralProposalError(
                f"negative control {control_id} must pass"
            )
        if row.get("always_pass") is not True:
            raise PlateauLeanstralProposalError(
                f"negative control {control_id} must be always_pass"
            )

    # Only registry-eligible methods/residuals; residual attempts are bounded.
    attempts = payload.get("residual_teacher_attempts")
    if not isinstance(attempts, list) or not attempts:
        raise PlateauLeanstralProposalError(
            "residual_teacher_attempts required for eligibility audit"
        )
    for attempt in attempts:
        if not isinstance(attempt, dict):
            raise PlateauLeanstralProposalError(
                "residual_teacher_attempts rows must be objects"
            )
        if attempt.get("population_kind") != REPAIR_DEV_POPULATION_KIND:
            raise PlateauLeanstralProposalError(
                "teacher attempts must stay on repair_development"
            )
        if attempt.get("blind_data_used") is not False:
            raise PlateauLeanstralProposalError(
                "teacher attempts must not use blind data"
            )
        for adv in attempt.get("executed_advisories") or ():
            if not isinstance(adv, dict) or adv.get("eligible") is not True:
                raise PlateauLeanstralProposalError(
                    "executed advisories must be registry-eligible"
                )
            if adv.get("semantic_authority") is not False:
                raise PlateauLeanstralProposalError(
                    "advisory semantic_authority must be false"
                )
        for adv in attempt.get("skipped_advisories") or ():
            if not isinstance(adv, dict):
                raise PlateauLeanstralProposalError("skipped advisories malformed")
            if adv.get("eligible") is True and adv.get("method_id") in (
                "leanstral",
                "spacy",
            ):
                raise PlateauLeanstralProposalError(
                    "eligible leanstral/spacy must not be skipped as ineligible"
                )
            if adv.get("method_id") == "symai" and adv.get("eligible") is not False:
                raise PlateauLeanstralProposalError(
                    "SyMAI must remain ineligible for proof-credit advisory"
                )
            if (
                adv.get("method_id") == "autoencoder"
                and adv.get("eligible") is not False
            ):
                raise PlateauLeanstralProposalError(
                    "autoencoder must remain ineligible without scored_supported"
                )
        for gate in attempt.get("structural_gates") or ():
            if not isinstance(gate, dict):
                raise PlateauLeanstralProposalError("structural gate row malformed")
            if gate.get("may_substitute_for_e2e") is not False:
                raise PlateauLeanstralProposalError(
                    "structural gates cannot substitute for e2e"
                )
            if gate.get("semantic_authority") is not False:
                raise PlateauLeanstralProposalError(
                    "structural gates semantic_authority must be false"
                )
        for control in attempt.get("negative_controls") or ():
            if not isinstance(control, dict) or control.get("status") != "pass":
                raise PlateauLeanstralProposalError(
                    "per-residual negative controls must pass"
                )

    # Leanstral nested proposals: parse + fixture acceptance.
    leanstral = payload.get("leanstral_proposals")
    if not isinstance(leanstral, dict):
        raise PlateauLeanstralProposalError("leanstral_proposals required")
    sealed = parse_plateau_leanstral_proposal_receipts(leanstral)
    validate_repair_dev_leanstral_fixture_pack(sealed)

    # Typed blank/schema/polarity/empty_rules/timeout/retry-exhausted taxonomy.
    typed = payload.get("typed_model_outcomes")
    if not isinstance(typed, dict):
        raise PlateauLeanstralProposalError("typed_model_outcomes required")
    taxonomy = set(typed.get("taxonomy") or ())
    required_tax = {
        "blank",
        "schema",
        "polarity",
        "empty_rules",
        "timeout",
        "retry_exhausted",
    }
    if not required_tax.issubset(taxonomy):
        raise PlateauLeanstralProposalError(
            f"typed_model_outcomes taxonomy missing {required_tax - taxonomy}"
        )
    dry_controls = typed.get("dry_run_controls") or {}
    if not isinstance(dry_controls, dict):
        raise PlateauLeanstralProposalError("typed dry_run_controls required")
    if not dry_controls.get("retry_exhausted", {}).get("recorded"):
        raise PlateauLeanstralProposalError(
            "retry_exhausted must be recorded in dry-run controls"
        )
    live = typed.get("live_inference") or {}
    if live.get("health_only_cannot_establish_inference") is not True:
        raise PlateauLeanstralProposalError(
            "health-only probes cannot establish model inference"
        )

    # Blind holdout never accessed.
    blind = payload.get("blind_holdout")
    if not isinstance(blind, dict):
        raise PlateauLeanstralProposalError("blind_holdout block required")
    if blind.get("access_receipt_count") != 0:
        raise PlateauLeanstralProposalError("blind access_receipt_count must be 0")
    if blind.get("blind_seal_unopened") is not True:
        raise PlateauLeanstralProposalError("blind seal must remain unopened")
    for flag in (
        "private_content_accessed",
        "cases_accessed",
        "sources_accessed",
        "gold_accessed",
        "residuals_accessed",
        "prompt_examples_accessed",
        "cache_namespaces_accessed",
    ):
        if blind.get(flag) is not False:
            raise PlateauLeanstralProposalError(
                f"blind_holdout.{flag} must be false"
            )

    doctrine = payload.get("doctrine") or {}
    if not isinstance(doctrine, dict):
        raise PlateauLeanstralProposalError("doctrine required")
    for key in (
        "only_registry_eligible_methods_and_residuals",
        "only_triggered_fields_change",
        "semantic_authority_false_for_model_and_solver_outputs",
        "leanstral_not_default_realizer",
        "structural_admission_cannot_substitute_for_e2e",
        "direct_and_symai_routes_distinct",
        "symai_no_proof_credit",
        "dry_run_and_negative_controls_always_pass",
    ):
        if doctrine.get(key) is not True:
            raise PlateauLeanstralProposalError(f"doctrine.{key} must be true")
    if doctrine.get("blind_data_accessed") is not False:
        raise PlateauLeanstralProposalError("doctrine.blind_data_accessed must be false")

    # CID binding over payload without receipts_cid fields.
    receipts_cid = payload.get("receipts_cid")
    if not isinstance(receipts_cid, str) or not receipts_cid.strip():
        raise PlateauLeanstralProposalError("receipts_cid required")
    bindable = dict(payload)
    bindable.pop("receipts_cid", None)
    bindable.pop("receipts_cid_codec", None)
    bindable.pop("receipts_cid_scope", None)
    expected_cid = cid_for_dag_json(bindable)
    if receipts_cid != expected_cid:
        raise PlateauLeanstralProposalError(
            "receipts_cid does not match teacher receipts payload"
        )


def test_repair_dev_dry_run_fixture_pack_covers_activation_and_controls() -> None:
    pack = repair_dev_dry_run_fixture_pack()
    outcomes = {item.case_id: item.expected_outcome for item in pack}
    for case_id in REPAIR_DEV_ACTIVATION_CASE_IDS:
        assert outcomes[case_id] is ProposalOutcome.ACCEPTED
    assert (
        outcomes["repair_dev_admission_reject_untriggered"]
        is ProposalOutcome.ADMISSION_REJECTED
    )
    assert outcomes["repair_dev_retry_exhausted"] is ProposalOutcome.RETRY_EXHAUSTED
    assert outcomes["repair_dev_not_triggered"] is ProposalOutcome.NOT_TRIGGERED


def test_repair_dev_dry_run_fixtures_pass_without_live_model() -> None:
    # No LeanstralClient; dry-run must not touch the network.
    sealed = build_repair_dev_leanstral_proposal_receipts()
    validate_repair_dev_leanstral_fixture_pack(sealed)

    assert sealed.mode is ProposalMode.DRY_RUN
    assert sealed.task_id == REPAIR_DEV_TASK_ID
    assert sealed.board_namespace == REPAIR_DEV_BOARD_NAMESPACE
    assert sealed.evidence == REPAIR_DEV_EVIDENCE
    assert sealed.fixture_pack_id == REPAIR_DEV_FIXTURE_PACK_ID
    assert sealed.leanstral_is_default_realizer is False
    assert sealed.production_runtime_unchanged is True
    assert sealed.structural_admission_required is True
    assert sealed.receipts_cid
    assert sealed.accept_rate is not None
    assert sealed.retry_exhausted_rate is not None
    assert sealed.catalog_cid  # bound to repair-dev residual catalog

    by_id = sealed.by_case_id()
    for case_id in REPAIR_DEV_ACTIVATION_CASE_IDS:
        accepted = by_id[case_id]
        assert accepted.outcome is ProposalOutcome.ACCEPTED
        assert accepted.implementable is True
        assert accepted.admission_disposition == AdmissionDisposition.ACCEPTED.value
        assert accepted.only_triggered_fields_changed is True
        assert accepted.prior_l1_unchanged is False
        assert accepted.semantic_authority is False
        assert accepted.packet is not None
        assert accepted.packet.implementable is True
        assert accepted.packet.proposals[0].teacher == "leanstral"
        assert accepted.packet.proposals[0].semantic_authority is False
        assert all(
            item.disposition is AdmissionDisposition.ACCEPTED
            for item in accepted.packet.admission_receipts
        )

    rejected = by_id["repair_dev_admission_reject_untriggered"]
    assert rejected.outcome is ProposalOutcome.ADMISSION_REJECTED
    assert rejected.implementable is False
    assert rejected.prior_l1_unchanged is True
    assert rejected.admitted_l1_digest == rejected.baseline_l1_digest
    assert rejected.admission_disposition == (
        AdmissionDisposition.VALIDATOR_REJECT.value
    )

    exhausted = by_id["repair_dev_retry_exhausted"]
    assert exhausted.outcome is ProposalOutcome.RETRY_EXHAUSTED
    assert exhausted.retry_exhausted is True
    assert exhausted.implementable is False
    assert exhausted.prior_l1_unchanged is True

    control = by_id["repair_dev_not_triggered"]
    assert control.outcome is ProposalOutcome.NOT_TRIGGERED
    assert control.implementable is False


def test_repair_dev_only_triggered_fields_change_on_accepted() -> None:
    for row in _repair_dev_activation_rows():
        bindings = row["score_bindings"]
        baseline = CanonicalRuleIR.from_dict(bindings["baseline_ir"])
        candidate = CanonicalRuleIR.from_dict(bindings["repaired_ir"])
        triggers = tuple(
            _repair_trigger_from_binding(item) for item in bindings["triggers"]
        )
        assert only_triggered_fields_changed(baseline, candidate, triggers) is True
        if not triggers:
            continue
        triggered = {item.canonical_field for item in triggers}
        rule_index = triggers[0].rule_index
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


def test_repair_dev_structural_admission_required_before_implementable() -> None:
    row = next(
        item
        for item in _repair_dev_activation_rows()
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
                detail="forced repair-dev reject",
            ),
        ),
    )
    teacher = LeanstralSelectiveProposalTeacher(
        mode=ProposalMode.DRY_RUN,
        admission_gate=reject_gate,
    )
    receipt = teacher.propose(
        case_id="repair-dev-gate-reject",
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
        case_id="repair-dev-gate-accept",
        baseline_l1=baseline,
        triggers=triggers,
        candidate_l1=candidate,
    )
    assert accepted.implementable is True
    assert accepted.outcome is ProposalOutcome.ACCEPTED
    assert accepted.admission_disposition == AdmissionDisposition.ACCEPTED.value
    assert accepted.only_triggered_fields_changed is True
    assert accepted.semantic_authority is False
    assert accepted.packet is not None
    assert accepted.packet.implementable is True


def test_repair_dev_leanstral_receipts_are_cid_bindable(tmp_path: Path) -> None:
    sealed = build_repair_dev_leanstral_proposal_receipts()
    payload = sealed.to_dict()
    assert payload["receipts_cid"] == sealed.receipts_cid
    assert payload["receipts_cid_codec"] == RECEIPTS_CID_CODEC
    assert payload["receipts_cid_scope"] == RECEIPTS_CID_SCOPE

    bindable = dict(payload)
    bindable.pop("receipts_cid", None)
    bindable.pop("receipts_cid_codec", None)
    bindable.pop("receipts_cid_scope", None)
    assert cid_for_dag_json(bindable) == sealed.receipts_cid

    path = tmp_path / "repair_dev_leanstral_proposal_receipts.json"
    written = write_plateau_leanstral_proposal_receipts(path, receipts=sealed)
    loaded = load_plateau_leanstral_proposal_receipts(path)
    assert loaded.receipts_cid == sealed.receipts_cid
    assert loaded.task_id == REPAIR_DEV_TASK_ID
    assert loaded.board_namespace == REPAIR_DEV_BOARD_NAMESPACE
    assert written["catalog_cid"] == sealed.catalog_cid
    parse_plateau_leanstral_proposal_receipts(written)


def test_repair_dev_checked_in_teacher_receipts_artifact() -> None:
    assert REPAIR_DEV_TEACHER_RECEIPTS_PATH.is_file(), (
        "repair_dev_teacher_receipts.json must be written by PLAT2-040"
    )
    payload = load_repair_dev_teacher_receipts()

    assert payload["task_id"] == REPAIR_DEV_TASK_ID
    assert payload["goal_id"] == REPAIR_DEV_GOAL_ID
    assert payload["board_namespace"] == REPAIR_DEV_BOARD_NAMESPACE
    assert payload["evidence"] == REPAIR_DEV_EVIDENCE
    assert payload["fixture_pack_id"] == REPAIR_DEV_FIXTURE_PACK_ID
    assert payload["population_kind"] == REPAIR_DEV_POPULATION_KIND
    assert payload["mode"] == ProposalMode.DRY_RUN.value
    assert payload["production_runtime_unchanged"] is True
    assert payload["production_realizer"] == "deterministic"

    # Bindings match frozen PLAT2-030/035/010/025 artifacts.
    catalog = json.loads(REPAIR_DEV_CATALOG_PATH.read_text(encoding="utf-8"))
    registry = json.loads(REPAIR_DEV_REGISTRY_PATH.read_text(encoding="utf-8"))
    packet_metrics = json.loads(
        REPAIR_DEV_PACKET_METRICS_PATH.read_text(encoding="utf-8")
    )
    bindings = payload["bindings"]
    assert bindings["catalog_cid"] == catalog["catalog_cid"]
    assert bindings["tree_cid"] == catalog["tree_cid"]
    assert bindings["population_cid"] == catalog["population_cid"]
    assert bindings["intervention_registry_cid"] == registry["registry_cid"]
    assert bindings["contract_cid"] == registry["contract_cid"]
    assert bindings["baseline_report_cid"] == catalog["baseline"]["report_cid"]
    assert bindings["packet_metrics_cid"] == packet_metrics["metrics_cid"]

    # Nested leanstral proposals regenerate with matching structural outcomes.
    nested = parse_plateau_leanstral_proposal_receipts(payload["leanstral_proposals"])
    regenerated = build_repair_dev_leanstral_proposal_receipts()
    assert regenerated.catalog_cid == nested.catalog_cid
    assert regenerated.task_id == nested.task_id
    assert regenerated.board_namespace == nested.board_namespace
    assert regenerated.mode is nested.mode
    assert regenerated.with_receipts_cid().receipts_cid == regenerated.receipts_cid

    by_id = nested.by_case_id()
    regen_by_id = regenerated.by_case_id()
    assert set(by_id) == set(regen_by_id)
    for case_id in REPAIR_DEV_ACTIVATION_CASE_IDS:
        assert by_id[case_id].implementable is True
        assert by_id[case_id].only_triggered_fields_changed is True
        assert by_id[case_id].admission_disposition == (
            AdmissionDisposition.ACCEPTED.value
        )
        assert by_id[case_id].semantic_authority is False
        assert regen_by_id[case_id].implementable is True
        assert regen_by_id[case_id].outcome is by_id[case_id].outcome
    assert by_id["repair_dev_admission_reject_untriggered"].implementable is False
    assert by_id["repair_dev_admission_reject_untriggered"].prior_l1_unchanged is True
    assert by_id["repair_dev_retry_exhausted"].retry_exhausted is True
    assert by_id["repair_dev_not_triggered"].outcome is ProposalOutcome.NOT_TRIGGERED

    # Provider / toolchain identities present.
    toolchain = payload["provider_toolchain"]
    assert toolchain["leanstral"]["provider_id"] == "leanstral-local"
    assert toolchain["leanstral"]["route"] == DIRECT_ROUTE_ID
    assert toolchain["symai"]["route"] == SYMAI_ROUTE
    assert toolchain["symai"]["proof_credit"] is False
    assert "hammer" in toolchain["structural_gates"]


def test_repair_dev_reliability_separate_from_e2e() -> None:
    sealed = build_repair_dev_leanstral_proposal_receipts()
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


def test_repair_dev_route_identities_and_symai_no_proof_credit() -> None:
    payload = load_repair_dev_teacher_receipts()
    routes = payload["route_identities"]
    assert routes["direct_route"] == DIRECT_ROUTE_ID
    assert routes["symai_route"] == SYMAI_ROUTE
    assert routes["leanstral_route"] == DIRECT_ROUTE_ID
    assert routes["routes_are_distinct"] is True
    assert routes["symai_proof_credit"] is False
    assert payload["symai_orchestration"]["proof_credit"] is False
    assert payload["symai_orchestration"]["executed"] is False
    assert payload["symai_orchestration"]["cannot_receive_proof_credit"] is True
    # Registry identities agree.
    registry = json.loads(REPAIR_DEV_REGISTRY_PATH.read_text(encoding="utf-8"))
    methods = {m["method_id"]: m for m in registry["method_records"]}
    assert methods["leanstral"]["identity"]["route"] == DIRECT_ROUTE_ID
    assert methods["symai"]["identity"]["route"] == SYMAI_ROUTE
    assert methods["symai"]["identity"]["proof_credit"] is False


def test_repair_dev_only_eligible_methods_and_residuals_execute() -> None:
    payload = load_repair_dev_teacher_receipts()
    registry = json.loads(REPAIR_DEV_REGISTRY_PATH.read_text(encoding="utf-8"))
    mapping_ids = {m["mapping_id"] for m in registry["residual_mappings"]}
    attempt_ids = {
        row["mapping_id"] for row in payload["residual_teacher_attempts"]
    }
    assert attempt_ids == mapping_ids

    for attempt in payload["residual_teacher_attempts"]:
        assert attempt["population_kind"] == REPAIR_DEV_POPULATION_KIND
        assert attempt["blind_data_used"] is False
        for adv in attempt["executed_advisories"]:
            assert adv["eligible"] is True
            assert adv["method_id"] in ("leanstral", "spacy")
            assert adv["semantic_authority"] is False
        for adv in attempt["skipped_advisories"]:
            assert adv["executed"] is False
            if adv["method_id"] in ("autoencoder", "symai"):
                assert adv["eligible"] is False
        # Cross-check against registry residual mapping.
        reg_map = next(
            m
            for m in registry["residual_mappings"]
            if m["mapping_id"] == attempt["mapping_id"]
        )
        reg_by_method = {
            a["method_id"]: a for a in reg_map["optional_advisories"]
        }
        for adv in attempt["executed_advisories"]:
            assert reg_by_method[adv["method_id"]]["eligible"] is True
        for adv in attempt["skipped_advisories"]:
            assert reg_by_method[adv["method_id"]]["eligible"] is False

    assert payload["methods"]["leanstral"]["eligible"] is True
    assert payload["methods"]["leanstral"]["executed"] is True
    assert payload["methods"]["leanstral"]["semantic_authority"] is False
    assert payload["methods"]["autoencoder"]["eligible"] is False
    assert payload["methods"]["symai"]["eligible"] is False


def test_repair_dev_spacy_ae_declared_status_diagnostics_only() -> None:
    payload = load_repair_dev_teacher_receipts()
    spacy = payload["spacy_diagnostics"]
    ae = payload["autoencoder_guidance"]
    assert spacy["semantic_authority"] is False
    assert spacy["output_kind"] == "diagnostics"
    assert spacy["declared_status_preserved"] is True
    assert spacy["role"] == "non_authoritative_diagnostics"
    assert ae["semantic_authority"] is False
    assert ae["eligible"] is False
    assert ae["executed"] is False
    assert ae["output_kind"] == "causal_guidance"
    assert ae["status"] == "terminal_unsupported"
    assert ae["declared_status_preserved"] is True


def test_repair_dev_structural_admission_not_e2e_substitute() -> None:
    payload = load_repair_dev_teacher_receipts()
    admission = payload["structural_admission"]
    assert admission["required"] is True
    assert admission["may_substitute_for_e2e_loss"] is False
    assert admission["semantic_authority"] is False
    assert admission["checks_declared_structural_properties_only"] is True
    assert payload["doctrine"]["structural_admission_cannot_substitute_for_e2e"] is True
    # Reliability still separate from e2e.
    assert payload["reliability"]["end_to_end_loss"] is None
    assert payload["reliability"]["separate_from_end_to_end_loss"] is True


def test_repair_dev_negative_controls_always_pass() -> None:
    payload = load_repair_dev_teacher_receipts()
    for control_id in ("nc_no_edit", "nc_withhold_optional_teacher"):
        row = payload["negative_controls"][control_id]
        assert row["status"] == "pass"
        assert row["always_pass"] is True
    for attempt in payload["residual_teacher_attempts"]:
        statuses = {nc["control_id"]: nc["status"] for nc in attempt["negative_controls"]}
        assert statuses["nc_no_edit"] == "pass"
        assert statuses["nc_withhold_optional_teacher"] == "pass"


def test_repair_dev_typed_model_outcome_taxonomy() -> None:
    payload = load_repair_dev_teacher_receipts()
    taxonomy = set(payload["typed_model_outcomes"]["taxonomy"])
    assert {
        "blank",
        "schema",
        "polarity",
        "empty_rules",
        "timeout",
        "retry_exhausted",
    }.issubset(taxonomy)
    # Closed ModelOutputRecovery taxonomy maps detailed labels correctly.
    assert classify_model_rejection("blank_output") is ModelRejectionReason.BLANK
    assert classify_model_rejection("malformed_output") is ModelRejectionReason.SCHEMA
    assert (
        classify_model_rejection("polarity_ambiguous") is ModelRejectionReason.POLARITY
    )
    assert classify_model_rejection("empty_output") is ModelRejectionReason.EMPTY_RULES
    assert classify_model_rejection("call_timeout") is ModelRejectionReason.TIMEOUT
    # Dry-run control records retry_exhausted separately.
    dry = payload["typed_model_outcomes"]["dry_run_controls"]
    assert dry["retry_exhausted"]["recorded"] is True
    assert dry["retry_exhausted"]["outcome"] == "retry_exhausted"
    # Live path records timeout → retry_exhausted via scripted client.
    baseline = _baseline()
    trigger = _object_trigger()
    client = RecordingClient(
        [
            LeanstralTimeoutError("timeout blank path"),
            LeanstralTimeoutError("timeout schema path"),
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
        {"case_id": "repair-dev-live-timeout"},
    )
    receipt = teacher.propose(
        case_id="repair-dev-live-timeout",
        baseline_l1=baseline,
        triggers=(trigger,),
        request=request,
    )
    assert receipt.mode is ProposalMode.LIVE
    assert receipt.outcome is ProposalOutcome.RETRY_EXHAUSTED
    assert receipt.retry_exhausted is True
    assert receipt.implementable is False
    assert receipt.semantic_authority is False
    assert receipt.model_calls == 2
    assert len(client.calls) == 2
    # Health-only cannot establish inference doctrine is sealed.
    live = payload["typed_model_outcomes"]["live_inference"]
    assert live["health_only_cannot_establish_inference"] is True
    assert live["required_for_proposal_credit"] is True


def test_repair_dev_no_blind_access() -> None:
    payload = load_repair_dev_teacher_receipts()
    blind = payload["blind_holdout"]
    assert blind["access_receipt_count"] == 0
    assert blind["blind_seal_unopened"] is True
    assert blind["private_content_accessed"] is False
    assert blind["cases_accessed"] is False
    assert blind["sources_accessed"] is False
    assert blind["gold_accessed"] is False
    assert blind["residuals_accessed"] is False
    assert blind["prompt_examples_accessed"] is False
    assert blind["cache_namespaces_accessed"] is False
    assert payload["doctrine"]["blind_data_accessed"] is False
    # Repair-dev fixtures path only — never holdout private sources.
    assert REPAIR_DEV_CASES_PATH.is_file()
    assert "repair_dev" in REPAIR_DEV_CASES_PATH.name
    # Residual attempts stay on repair_development.
    for attempt in payload["residual_teacher_attempts"]:
        assert attempt["population_kind"] == REPAIR_DEV_POPULATION_KIND
        assert attempt["blind_data_used"] is False
