"""Contract tests for the auditable extended semantic round-trip matrix."""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace

from benchmarks.logic_pipeline.content_addressing import (
    cid_for_dag_json,
    validate_cid,
)
from benchmarks.semantic_roundtrip.contracts import (
    AllowedAtomVocabulary,
    CanonicalRule,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ConstructorResult,
    FailureReason,
    RealizerRequest,
    RealizerResult,
)
from benchmarks.semantic_roundtrip.extended_matrix import (
    SHARED_MODEL_RESOURCE_ID,
    CompositionSpec,
    ExtendedConstructorArm,
    ExtendedMatrixPlan,
    ExtendedRealizerArm,
    ExtendedSemanticRoundTripMatrix,
    GuidanceMode,
    ModelRoute,
    OmissionReason,
    RealizerMode,
    RealizerSpec,
    RepairMode,
    ValidationOverlaySpec,
    build_extended_matrix_plan,
)
from benchmarks.semantic_roundtrip.matrix import (
    MatrixCase,
    SemanticRoundTripMatrix,
)


VOCABULARY = AllowedAtomVocabulary(
    actors=("agency",),
    actions=("file",),
    objects=("notice",),
    qualifiers=("under_policy",),
)
IR = CanonicalRuleIR(
    (
        CanonicalRule(
            modality="O",
            actor="agency",
            action="file",
            object="notice",
            conditions=("under_policy",),
        ),
    )
)
TEXT = "Agency shall file notice under policy."


def _case(
    case_id: str = "case-1",
    source_text: str = "Under policy the agency must file a public notice.",
) -> MatrixCase:
    return MatrixCase(case_id, source_text, VOCABULARY, IR)


class FixedConstructor:
    def __init__(
        self,
        identity: str,
        *,
        model_backed: bool = False,
        fail_marker: str | None = None,
    ) -> None:
        self.identity = identity
        if model_backed:
            self.provider_id = "leanstral-local"
        self.fail_marker = fail_marker
        self.requests: list[ConstructorRequest] = []

    def construct(self, request: ConstructorRequest) -> ConstructorResult:
        self.requests.append(request)
        if self.fail_marker and self.fail_marker in request.source_text:
            return ConstructorResult(
                ComponentStatus.FAILED,
                failure_reason=FailureReason.CAPABILITY_UNAVAILABLE,
                failure_detail="fixture capability unavailable",
            )
        return ConstructorResult(ComponentStatus.SUCCESS, canonical_ir=IR)


class FixedRealizer:
    def __init__(self, identity: str, *, model_backed: bool = False) -> None:
        self.identity = identity
        if model_backed:
            self.provider_id = "leanstral-local"
        self.requests: list[RealizerRequest] = []

    def realize(self, request: RealizerRequest) -> RealizerResult:
        self.requests.append(request)
        return RealizerResult(ComponentStatus.SUCCESS, text=TEXT)


def _registries(
    plan: ExtendedMatrixPlan,
    *,
    fail_marker: str | None = None,
) -> tuple[
    tuple[ExtendedConstructorArm, ...],
    tuple[ExtendedRealizerArm, ...],
]:
    constructors = tuple(
        ExtendedConstructorArm(
            spec,
            FixedConstructor(
                f"constructor:{spec.arm_id}",
                model_backed=spec.repair is RepairMode.ALWAYS_ON,
                fail_marker=fail_marker,
            ),
        )
        for spec in plan.compositions
    )
    realizers = tuple(
        ExtendedRealizerArm(
            spec,
            FixedRealizer(
                f"realizer:{spec.realizer_id}",
                model_backed=spec.mode is RealizerMode.MODEL,
            ),
        )
        for spec in plan.realizers
    )
    return constructors, realizers


def _validator(
    left: CanonicalRuleIR,
    right: CanonicalRuleIR,
    request_id: str,
) -> Mapping[str, object]:
    return {
        "status": "success",
        "request_id": request_id,
        "equivalent": left == right,
        "semantic_authority": False,
    }


def test_plan_covers_required_axes_and_types_every_omission() -> None:
    plan = build_extended_matrix_plan()

    assert len(plan.compositions) == 10
    assert len(plan.realizers) == 3
    assert len(plan.cell_ids) == 30
    assert {item.guidance for item in plan.compositions} == {
        GuidanceMode.NO_GUIDANCE,
        GuidanceMode.GUIDED,
        GuidanceMode.NOT_APPLICABLE,
    }
    assert {item.repair for item in plan.compositions} == {
        RepairMode.NO_REPAIR,
        RepairMode.SELECTIVE,
        RepairMode.ALWAYS_ON,
    }
    assert {
        item.constructor_route
        for item in plan.compositions
        if item.repair is RepairMode.ALWAYS_ON
    } == {ModelRoute.DIRECT, ModelRoute.SYMAI}
    assert {(item.mode, item.route) for item in plan.realizers} == {
        (RealizerMode.DETERMINISTIC, ModelRoute.NOT_APPLICABLE),
        (RealizerMode.MODEL, ModelRoute.DIRECT),
        (RealizerMode.MODEL, ModelRoute.SYMAI),
    }
    assert {item.validator_id for item in plan.validation_overlays} == {
        "hammer_cvc5",
        "lean",
    }
    reasons = {item.reason for item in plan.omissions}
    assert reasons == set(OmissionReason)
    assert all(item.axes and item.detail for item in plan.omissions)
    assert all(
        overlay.candidate_mutation_allowed is False
        and overlay.score_mutation_allowed is False
        for overlay in plan.validation_overlays
    )


def test_all_thirty_cells_use_core_cases_scores_and_validation_overlays() -> None:
    plan = build_extended_matrix_plan()
    constructors, realizers = _registries(plan)
    validators = {"hammer_cvc5": _validator, "lean": _validator}
    result = ExtendedSemanticRoundTripMatrix(
        constructors,
        realizers,
        plan=plan,
        validators=validators,
    ).run((_case(),))

    assert len(result.cases) == 1
    assert len(result.coordinates) == 30
    assert tuple(item.cell_id for item in result.coordinates) == plan.cell_ids
    assert all(item.status is ComponentStatus.SUCCESS for item in result.coordinates)
    assert all(item.primary_loss == 0.0 for item in result.coordinates)
    assert all(item.result.forward_loss == 0.0 for item in result.coordinates)
    assert all(item.result.cycle_loss == 0.0 for item in result.coordinates)
    assert result.cases[0].case_cid == _case().case_cid
    assert result.cases[0].source_text_cid == _case().source_text_cid
    assert result.cases[0].gold_ir_cid == _case().gold_ir_cid

    for coordinate in result.coordinates:
        actions = coordinate.execution["validation_actions"]
        assert len(actions) == 2
        assert {item["validator_id"] for item in actions} == {
            "hammer_cvc5",
            "lean",
        }
        assert all(item["candidate_unchanged"] is True for item in actions)
        assert all(item["score_mutation_allowed"] is False for item in actions)
        assert coordinate.semantic_record.validation["candidate_cid"] == (
            coordinate.candidate_cid
        )

    # The extension delegates the full semantic payload to the core runner.
    plain_constructors = {
        arm.spec.arm_id: FixedConstructor(
            f"constructor:{arm.spec.arm_id}",
            model_backed=arm.spec.repair is RepairMode.ALWAYS_ON,
        )
        for arm in constructors
    }
    plain_realizers = {
        arm.spec.realizer_id: FixedRealizer(
            f"realizer:{arm.spec.realizer_id}",
            model_backed=arm.spec.mode is RealizerMode.MODEL,
        )
        for arm in realizers
    }
    core = SemanticRoundTripMatrix(
        plain_constructors,
        plain_realizers,
        validators=validators,
        require_eight_cells=False,
    ).run((_case(),))
    assert result.core_run_cid == core.run_cid
    assert result.summaries == core.summaries


def test_every_call_fallback_model_action_and_resource_is_exposed() -> None:
    plan = build_extended_matrix_plan()
    constructors, realizers = _registries(plan)
    validators = {"hammer_cvc5": _validator, "lean": _validator}
    result = ExtendedSemanticRoundTripMatrix(
        constructors,
        realizers,
        plan=plan,
        validators=validators,
    ).run((_case(),))

    deterministic_cell = next(
        item
        for item in result.coordinates
        if item.composition.repair is RepairMode.NO_REPAIR
        and item.realizer.mode is RealizerMode.DETERMINISTIC
    )
    assert [
        call["phase"]
        for call in deterministic_cell.execution["component_calls"]
    ] == ["t0_to_l1", "l1_to_t1", "t1_to_l2"]
    assert deterministic_cell.execution["model_calls"] == ()
    assert len(deterministic_cell.execution["fallbacks"]) == 3
    assert all(
        fallback["used"] is False
        for fallback in deterministic_cell.execution["fallbacks"]
    )

    model_cell = next(
        item
        for item in result.coordinates
        if item.composition.repair is RepairMode.ALWAYS_ON
        and item.composition.constructor_route is ModelRoute.SYMAI
        and item.realizer.route is ModelRoute.DIRECT
    )
    calls = model_cell.execution["model_calls"]
    assert len(calls) == 3
    assert len({call["slot_sequence"] for call in calls}) == 3
    assert all(call["serialized"] is True for call in calls)
    assert all(call["shared_capacity"] == 1 for call in calls)
    assert all(
        call["resource_id"] == SHARED_MODEL_RESOURCE_ID for call in calls
    )
    resources = model_cell.execution["resource_identities"]
    assert resources[SHARED_MODEL_RESOURCE_ID]["capacity"] == 1
    assert resources["symai_route"]["independent_model"] is False
    assert resources["autoencoder_state"]["read_only"] is True
    assert resources["spacy_pipeline"]["fallback_allowed"] is False


def test_selective_receipt_preserves_exact_model_calls_and_fallback() -> None:
    spec = CompositionSpec(
        "typed_deontic",
        GuidanceMode.GUIDED,
        RepairMode.SELECTIVE,
        ModelRoute.NOT_APPLICABLE,
    )
    realizer_spec = RealizerSpec(
        "deterministic",
        RealizerMode.DETERMINISTIC,
        ModelRoute.NOT_APPLICABLE,
    )
    plan = ExtendedMatrixPlan((spec,), (realizer_spec,), (), ())

    class SelectiveLeanstralRepairFixture(FixedConstructor):
        provider_id = "leanstral-local"

        def __init__(self) -> None:
            super().__init__("SelectiveLeanstralRepair@1:fixture")
            self.ordinal = 0

        def construct_with_diagnostics(
            self, request: ConstructorRequest
        ) -> object:
            self.requests.append(request)
            current = self.ordinal
            self.ordinal += 1
            result = ConstructorResult(
                ComponentStatus.SUCCESS, canonical_ir=IR
            )
            return SimpleNamespace(
                result=result,
                diagnostics={
                    "status": "accepted",
                    "fallback_used": current == 1,
                    "model_calls": [
                        {
                            "call_id": f"repair-{current}",
                            "ordinal": 0,
                            "status": "returned",
                            "endpoint": "http://127.0.0.1:8080/v1",
                            "model": "fixture-model",
                        }
                    ],
                },
            )

    result = ExtendedSemanticRoundTripMatrix(
        (ExtendedConstructorArm(spec, SelectiveLeanstralRepairFixture()),),
        (
            ExtendedRealizerArm(
                realizer_spec, FixedRealizer("deterministic@1")
            ),
        ),
        plan=plan,
        validators={},
    ).run((_case(),))
    coordinate = result.coordinates[0]

    assert [
        call["call_id"] for call in coordinate.execution["model_calls"]
    ] == ["repair-0", "repair-1"]
    assert [call["slot_sequence"] for call in coordinate.execution["model_calls"]] == [
        1,
        2,
    ]
    assert [item["used"] for item in coordinate.execution["fallbacks"]] == [
        False,
        False,
        True,
    ]


def test_failures_remain_loss_one_and_validation_is_not_applicable() -> None:
    plan = build_extended_matrix_plan()
    constructors, realizers = _registries(plan, fail_marker="fail")
    validators = {"hammer_cvc5": _validator, "lean": _validator}
    result = ExtendedSemanticRoundTripMatrix(
        constructors,
        realizers,
        plan=plan,
        validators=validators,
    ).run((_case(), _case("failed", "fail this scheduled case")))

    failed = result.cases[1]
    assert len(failed.coordinates) == 30
    assert all(item.primary_loss == 1.0 for item in failed.coordinates)
    assert all(item.status is ComponentStatus.FAILED for item in failed.coordinates)
    assert all(
        len(item.execution["component_calls"]) == 1
        for item in failed.coordinates
    )
    assert all(
        action["receipt"]["status"] == "not_applicable"
        for item in failed.coordinates
        for action in item.execution["validation_actions"]
    )
    for summary in result.summaries.values():
        assert summary["scheduled_case_count"] == 2
        assert summary["success_count"] == 1
        assert summary["failure_count"] == 1
        assert summary["mean_end_to_end_loss"] == 0.5


def test_extended_records_are_content_addressed() -> None:
    spec = CompositionSpec(
        "typed_deontic",
        GuidanceMode.NO_GUIDANCE,
        RepairMode.NO_REPAIR,
        ModelRoute.NOT_APPLICABLE,
    )
    realizer_spec = RealizerSpec(
        "deterministic",
        RealizerMode.DETERMINISTIC,
        ModelRoute.NOT_APPLICABLE,
    )
    plan = ExtendedMatrixPlan(
        (spec,),
        (realizer_spec,),
        (
            ValidationOverlaySpec(
                "hammer_cvc5", "hammer/cvc5 fixture"
            ),
        ),
        (),
    )
    result = ExtendedSemanticRoundTripMatrix(
        (
            ExtendedConstructorArm(
                spec, FixedConstructor("typed-no-guidance@1")
            ),
        ),
        (
            ExtendedRealizerArm(
                realizer_spec, FixedRealizer("deterministic@1")
            ),
        ),
        plan=plan,
        validators={"hammer_cvc5": _validator},
    ).run((_case(),))

    assert validate_cid(result.run_cid, codecs=("dag-json",)) == result.run_cid
    run_payload = result.to_dict()
    assert cid_for_dag_json(
        {key: value for key, value in run_payload.items() if key != "run_cid"}
    ) == result.run_cid
    case_payload = result.cases[0].to_dict()
    assert cid_for_dag_json(
        {
            key: value
            for key, value in case_payload.items()
            if key != "record_cid"
        }
    ) == result.cases[0].record_cid
    coordinate_payload = result.coordinates[0].to_dict()
    assert cid_for_dag_json(
        {
            key: value
            for key, value in coordinate_payload.items()
            if key != "record_cid"
        }
    ) == result.coordinates[0].record_cid
