"""Contract tests for HybridRoundTripArms@1 research evaluation modes."""

from __future__ import annotations

import pytest

from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json
from benchmarks.semantic_roundtrip.contracts import (
    AllowedAtomVocabulary,
    CanonicalRule,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ConstructorResult,
    ContractError,
    FailureReason,
    RealizerRequest,
    RealizerResult,
)
from benchmarks.semantic_roundtrip.hybrid_arms import (
    CONSTRUCTOR_ONLY_BASELINE_ARM_ID,
    CONSTRUCTOR_ONLY_MODEL_DIRECT_ARM_ID,
    CONSTRUCTOR_ONLY_MODAL_SPACY_ARM_ID,
    DETERMINISTIC_BASELINE_ARM_ID,
    HYBRID_CANONICAL_PATH_ARM_ID,
    HYBRID_COORDINATE_RECEIPT_SCHEMA,
    HYBRID_ROUND_TRIP_ARMS_INTERFACE,
    HYBRID_TYPED_DEONTIC_NO_REPAIR_ARM_ID,
    HYBRID_TYPED_DEONTIC_SELECTIVE_ARM_ID,
    PREREGISTERED_HYBRID_ARMS,
    REALIZER_ONLY_DETERMINISTIC_ARM_ID,
    REALIZER_ONLY_MODEL_DIRECT_ARM_ID,
    STAGE_ABSTAINED,
    STAGE_NOT_APPLICABLE,
    STAGE_SCORED,
    EvaluationMode,
    HybridDisposition,
    HybridPreflightError,
    HybridSuccessClaimError,
    arms_for_mode,
    assert_hybrid_mode_preflight,
    authorize_hybrid_success_claim,
    evaluate_hybrid_mode_preflight,
    get_hybrid_arm,
    hybrid_arm_registry,
    paired_bootstrap_vs_baseline,
    required_preflights_for_hybrid_arm,
    research_modes_do_not_alter_promotion_set,
    run_constructor_only,
    run_hybrid_path,
    run_realizer_only,
    select_evaluation_mode,
    select_hybrid_arm,
    separate_stage_losses,
)
from benchmarks.semantic_roundtrip.matrix import MatrixCoordinateRecord
from benchmarks.semantic_roundtrip.realizers.deterministic import (
    CanonicalDeterministicRealizer,
)
from benchmarks.semantic_roundtrip.statistics import RoundTripObservation
from benchmarks.semantic_roundtrip.contracts import RoundTripResult


VOCABULARY = AllowedAtomVocabulary(
    actors=("agency", "company_a"),
    actions=("file", "submit"),
    objects=("notice", "backup_report"),
    qualifiers=("within_deadline", "within_10_days", "emergency"),
)
GOLD = CanonicalRuleIR(
    (
        CanonicalRule(
            modality="O",
            actor="agency",
            action="file",
            object="notice",
            temporal=("within_deadline",),
        ),
    )
)
FIXED_L1 = GOLD


class FixedConstructor:
    identity = "FixedConstructor@1"

    def __init__(self, ir: CanonicalRuleIR = GOLD) -> None:
        self.ir = ir

    def construct(self, request: ConstructorRequest) -> ConstructorResult:
        del request
        return ConstructorResult(
            ComponentStatus.SUCCESS, canonical_ir=self.ir
        )


class FailingConstructor:
    identity = "FailingConstructor@1"

    def construct(self, request: ConstructorRequest) -> ConstructorResult:
        del request
        return ConstructorResult(
            ComponentStatus.FAILED,
            failure_reason=FailureReason.INVALID_OUTPUT,
            failure_detail="synthetic constructor failure",
        )


class FixedRealizer:
    identity = "FixedRealizer@1"

    def realize(self, request: RealizerRequest) -> RealizerResult:
        del request
        return RealizerResult(
            ComponentStatus.SUCCESS,
            text="The agency shall file notice within deadline.",
        )


def _live_smokes_ok(route: str = "direct") -> dict[str, object]:
    return {
        "routes": {
            route: {
                "status": "passed",
                "model_inference_performed": True,
            }
        }
    }


def test_required_modes_are_preregistered() -> None:
    modes = {arm.mode for arm in PREREGISTERED_HYBRID_ARMS}
    assert modes == {
        EvaluationMode.CONSTRUCTOR_ONLY,
        EvaluationMode.REALIZER_ONLY,
        EvaluationMode.HYBRID,
    }
    registry = hybrid_arm_registry()
    assert registry["interface"] == HYBRID_ROUND_TRIP_ARMS_INTERFACE
    assert set(registry["required_modes"]) == {
        "constructor_only",
        "realizer_only",
        "hybrid",
    }
    assert CONSTRUCTOR_ONLY_BASELINE_ARM_ID in registry["modes"][
        "constructor_only"
    ]
    assert REALIZER_ONLY_DETERMINISTIC_ARM_ID in registry["modes"][
        "realizer_only"
    ]
    assert HYBRID_CANONICAL_PATH_ARM_ID in registry["modes"]["hybrid"]
    hybrid = get_hybrid_arm(HYBRID_CANONICAL_PATH_ARM_ID)
    assert hybrid.pipeline[0] == "typed_deontic_construct"
    assert "optional_selective_or_model_repair" in hybrid.pipeline
    assert "deterministic_realize" in hybrid.pipeline
    body = dict(registry)
    cid = body.pop("registry_cid")
    assert cid == cid_for_dag_json(body)


def test_mode_selection_aliases_and_arm_resolution() -> None:
    assert select_evaluation_mode("constructor") is (
        EvaluationMode.CONSTRUCTOR_ONLY
    )
    assert select_evaluation_mode("realizer_only") is (
        EvaluationMode.REALIZER_ONLY
    )
    assert select_evaluation_mode({"mode": "hybrid"}) is EvaluationMode.HYBRID
    with pytest.raises(ContractError, match="unknown evaluation mode"):
        select_evaluation_mode("not_a_mode")

    baseline = select_hybrid_arm(mode="constructor_only")
    assert baseline.arm_id == CONSTRUCTOR_ONLY_BASELINE_ARM_ID
    assert baseline.baseline_role == "baseline"

    hybrid = select_hybrid_arm(mode=EvaluationMode.HYBRID)
    assert hybrid.arm_id == HYBRID_CANONICAL_PATH_ARM_ID

    by_id = select_hybrid_arm(arm_id=REALIZER_ONLY_DETERMINISTIC_ARM_ID)
    assert by_id.mode is EvaluationMode.REALIZER_ONLY

    candidates = arms_for_mode("constructor_only")
    assert {arm.arm_id for arm in candidates} >= {
        CONSTRUCTOR_ONLY_BASELINE_ARM_ID,
        CONSTRUCTOR_ONLY_MODAL_SPACY_ARM_ID,
        CONSTRUCTOR_ONLY_MODEL_DIRECT_ARM_ID,
    }

    with pytest.raises(ContractError, match="belongs to mode"):
        select_hybrid_arm(
            mode="hybrid",
            arm_id=CONSTRUCTOR_ONLY_BASELINE_ARM_ID,
        )


def test_fail_closed_missing_preflight_for_model_hybrid_arms() -> None:
    selective = get_hybrid_arm(HYBRID_TYPED_DEONTIC_SELECTIVE_ARM_ID)
    preflight = required_preflights_for_hybrid_arm(selective)
    assert "live_smoke" in preflight

    verdict = evaluate_hybrid_mode_preflight([selective], live_smokes=None)
    assert verdict["authorized"] is False
    assert verdict["fail_closed"] is True
    assert any(
        item["preflight"] == "live_smoke" for item in verdict["missing"]
    )

    with pytest.raises(HybridPreflightError, match="lack required preflight"):
        assert_hybrid_mode_preflight([selective], live_smokes=None)

    # Health-only smoke is not sufficient.
    health_only = {
        "routes": {
            "direct": {
                "status": "passed",
                "model_inference_performed": False,
                "health_only": True,
            }
        }
    }
    with pytest.raises(HybridPreflightError):
        assert_hybrid_mode_preflight([selective], live_smokes=health_only)

    ok = assert_hybrid_mode_preflight(
        [selective], live_smokes=_live_smokes_ok()
    )
    assert ok["authorized"] is True

    model_constructor = get_hybrid_arm(CONSTRUCTOR_ONLY_MODEL_DIRECT_ARM_ID)
    with pytest.raises(HybridPreflightError):
        assert_hybrid_mode_preflight([model_constructor])

    # Deterministic constructor-only and realizer-only need no live smoke.
    det = [
        get_hybrid_arm(CONSTRUCTOR_ONLY_BASELINE_ARM_ID),
        get_hybrid_arm(REALIZER_ONLY_DETERMINISTIC_ARM_ID),
        get_hybrid_arm(HYBRID_TYPED_DEONTIC_NO_REPAIR_ARM_ID),
    ]
    assert assert_hybrid_mode_preflight(det)["authorized"] is True


def test_constructor_only_reports_forward_separately() -> None:
    coordinate = run_constructor_only(
        case_id="case-a",
        source_text="Agency shall file notice within deadline.",
        vocabulary=VOCABULARY,
        gold_ir=GOLD,
        constructor=FixedConstructor(),
        arm=CONSTRUCTOR_ONLY_BASELINE_ARM_ID,
    )
    assert coordinate.mode is EvaluationMode.CONSTRUCTOR_ONLY
    assert coordinate.disposition is HybridDisposition.SEMANTIC_SCORED
    assert coordinate.stage_losses.forward_status == STAGE_SCORED
    assert coordinate.stage_losses.cycle_status == STAGE_NOT_APPLICABLE
    assert coordinate.stage_losses.end_to_end_status == STAGE_NOT_APPLICABLE
    assert coordinate.stage_losses.forward == 0.0
    assert coordinate.stage_losses.cycle is None
    assert coordinate.stage_losses.end_to_end is None
    payload = coordinate.to_dict()
    assert payload["interface"] == HYBRID_ROUND_TRIP_ARMS_INTERFACE
    assert payload["schema_version"] == HYBRID_COORDINATE_RECEIPT_SCHEMA
    assert payload["stage_losses"]["reported_separately"] is True
    body = dict(payload)
    receipt_cid = body.pop("receipt_cid")
    assert receipt_cid == cid_for_dag_json(body)

    failed = run_constructor_only(
        case_id="case-a",
        source_text="x",
        vocabulary=VOCABULARY,
        gold_ir=GOLD,
        constructor=FailingConstructor(),
        arm=CONSTRUCTOR_ONLY_BASELINE_ARM_ID,
    )
    assert failed.disposition is HybridDisposition.RUNTIME_FAILED
    assert failed.stage_losses.forward == 1.0


def test_realizer_only_on_fixed_l1_reports_all_losses() -> None:
    coordinate = run_realizer_only(
        case_id="case-a",
        fixed_l1=FIXED_L1,
        vocabulary=VOCABULARY,
        gold_ir=GOLD,
        realizer=FixedRealizer(),
        l2_constructor=FixedConstructor(),
        arm=REALIZER_ONLY_DETERMINISTIC_ARM_ID,
    )
    assert coordinate.mode is EvaluationMode.REALIZER_ONLY
    assert coordinate.disposition is HybridDisposition.SEMANTIC_SCORED
    losses = separate_stage_losses(coordinate)
    assert losses["forward"]["status"] == STAGE_SCORED
    assert losses["cycle"]["status"] == STAGE_SCORED
    assert losses["end_to_end"]["status"] == STAGE_SCORED
    assert losses["forward"]["loss"] == 0.0
    assert coordinate.result is not None
    assert coordinate.result.status is ComponentStatus.SUCCESS


def test_hybrid_path_scores_forward_cycle_end_to_end_separately() -> None:
    coordinate = run_hybrid_path(
        case_id="case-a",
        source_text="Agency shall file notice within deadline.",
        vocabulary=VOCABULARY,
        gold_ir=GOLD,
        arm=HYBRID_TYPED_DEONTIC_NO_REPAIR_ARM_ID,
        base_constructor=FixedConstructor(),
        realizer=CanonicalDeterministicRealizer(),
    )
    assert coordinate.mode is EvaluationMode.HYBRID
    assert coordinate.disposition is HybridDisposition.SEMANTIC_SCORED
    assert coordinate.stage_losses.forward_status == STAGE_SCORED
    assert coordinate.stage_losses.cycle_status == STAGE_SCORED
    assert coordinate.stage_losses.end_to_end_status == STAGE_SCORED
    assert set(coordinate.diagnostics["losses_separate"]) == {
        "forward",
        "cycle",
        "end_to_end",
    }
    # Deterministic realizer + fixed constructor yields zero losses on gold L1.
    assert coordinate.stage_losses.forward == 0.0
    assert coordinate.stage_losses.end_to_end == 0.0


def test_hybrid_optional_repair_fail_closed_abstention_missing_preflight() -> None:
    coordinate = run_hybrid_path(
        case_id="case-a",
        source_text="Agency shall file notice within deadline.",
        vocabulary=VOCABULARY,
        gold_ir=GOLD,
        arm=HYBRID_TYPED_DEONTIC_SELECTIVE_ARM_ID,
        base_constructor=FixedConstructor(),
        live_smokes=None,
        allow_missing_preflight_abstention=True,
    )
    assert coordinate.disposition is HybridDisposition.PREFLIGHT_BLOCKED
    assert coordinate.evaluation_status == "not_measured"
    assert coordinate.evaluation_reason == "preflight_blocked"
    assert coordinate.stage_losses.forward_status == STAGE_ABSTAINED
    assert coordinate.stage_losses.cycle_status == STAGE_ABSTAINED
    assert coordinate.stage_losses.end_to_end_status == STAGE_ABSTAINED
    assert coordinate.result is None
    assert "fail-closed abstention" in (coordinate.abstention_reason or "")

    with pytest.raises(HybridPreflightError):
        run_hybrid_path(
            case_id="case-a",
            source_text="Agency shall file notice within deadline.",
            vocabulary=VOCABULARY,
            gold_ir=GOLD,
            arm=HYBRID_TYPED_DEONTIC_SELECTIVE_ARM_ID,
            base_constructor=FixedConstructor(),
            live_smokes=None,
            allow_missing_preflight_abstention=False,
        )


def test_hybrid_selective_with_preflight_and_zero_triggers() -> None:
    coordinate = run_hybrid_path(
        case_id="case-a",
        source_text="Agency shall file notice within deadline.",
        vocabulary=VOCABULARY,
        gold_ir=GOLD,
        arm=HYBRID_TYPED_DEONTIC_SELECTIVE_ARM_ID,
        base_constructor=FixedConstructor(),
        realizer=CanonicalDeterministicRealizer(),
        live_smokes=_live_smokes_ok(),
    )
    assert coordinate.disposition is HybridDisposition.SEMANTIC_SCORED
    assert coordinate.repair_status == "not_triggered"
    assert coordinate.stage_losses.forward is not None
    assert coordinate.stage_losses.cycle is not None
    assert coordinate.stage_losses.end_to_end is not None


def test_hybrid_success_claim_requires_paired_bootstrap() -> None:
    with pytest.raises(HybridSuccessClaimError, match="paired bootstrap"):
        authorize_hybrid_success_claim(
            candidate_arm_id=HYBRID_CANONICAL_PATH_ARM_ID,
            paired_comparison=None,
        )

    baseline = DETERMINISTIC_BASELINE_ARM_ID
    candidate = HYBRID_TYPED_DEONTIC_NO_REPAIR_ARM_ID

    def _coordinate(case_id: str, arm_id: str, loss: float) -> MatrixCoordinateRecord:
        result = RoundTripResult(
            status=ComponentStatus.SUCCESS,
            l1=GOLD,
            reconstruction="The agency shall file notice within deadline.",
            l2=GOLD,
            forward_loss=loss,
            cycle_loss=loss,
            end_to_end_loss=loss,
        )
        return MatrixCoordinateRecord(
            case_id=case_id,
            case_cid=f"{case_id}-cid",
            cell_id=arm_id,
            constructor_id="typed_deontic",
            constructor_identity="typed@1",
            realizer_id="deterministic",
            realizer_identity="det@1",
            result=result,
            l1_cid=f"{case_id}-l1",
            reconstruction_cid=f"{case_id}-t1",
            l2_cid=f"{case_id}-l2",
            diagnostics={
                "semantic_comparisons": {
                    "end_to_end_gold_to_l2": {
                        "exact_rule_f1": 1.0 - loss,
                        "exact_ir": loss == 0.0,
                        "exact_ir_nonvacuous": loss == 0.0,
                        "facet_survival": {
                            "modality": 1.0,
                            "conditions": 1.0,
                            "exceptions": 1.0,
                            "temporal": 1.0,
                        },
                    }
                },
                "gates": {
                    "full_coverage": True,
                    "selection_eligible": True,
                },
            },
            candidate_cid=f"{case_id}-{arm_id}-cand",
            validation={},
            record_cid=f"{case_id}-{arm_id}-rec",
        )

    observations = []
    for case_id, base_loss, cand_loss in (
        ("case-a", 0.2, 0.1),
        ("case-b", 0.3, 0.1),
        ("case-c", 0.25, 0.05),
    ):
        observations.append(
            RoundTripObservation(
                coordinate=_coordinate(case_id, baseline, base_loss),
                repeat_index=0,
                cache_mode="not_applicable",
                cache_namespace=f"ns-{case_id}-{baseline}",
            )
        )
        observations.append(
            RoundTripObservation(
                coordinate=_coordinate(case_id, candidate, cand_loss),
                repeat_index=0,
                cache_mode="not_applicable",
                cache_namespace=f"ns-{case_id}-{candidate}",
            )
        )

    comparison = paired_bootstrap_vs_baseline(
        observations,
        baseline_arm_id=baseline,
        candidate_arm_ids=(candidate,),
        bootstrap_samples=50,
    )
    assert comparison["required_for_hybrid_success_claims"] is True
    auth = authorize_hybrid_success_claim(
        candidate_arm_id=candidate,
        paired_comparison=comparison,
        baseline_arm_id=baseline,
        metric="end_to_end",
    )
    assert auth["authorized"] is True
    assert auth["paired_bootstrap_required"] is True
    assert auth["mean_delta"] < 0.0
    assert "authorization_cid" in auth


def test_research_arms_do_not_collide_with_promotion_cells() -> None:
    promotion = [
        "typed_deontic__no_guidance__no_repair__not_applicable__deterministic",
        "typed_deontic__no_guidance__selective__not_applicable__deterministic",
    ]
    assert research_modes_do_not_alter_promotion_set(promotion) is True
    # A promotion set that incorrectly lists a research arm is rejected.
    colliding = list(promotion) + [CONSTRUCTOR_ONLY_BASELINE_ARM_ID]
    assert research_modes_do_not_alter_promotion_set(colliding) is False
    research_ids = {arm.arm_id for arm in PREREGISTERED_HYBRID_ARMS}
    assert DETERMINISTIC_BASELINE_ARM_ID not in research_ids
    assert REALIZER_ONLY_MODEL_DIRECT_ARM_ID in research_ids
