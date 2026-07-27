"""Qualification contract for the immutable SRT replacement matrix."""

from __future__ import annotations

import copy
from collections import Counter
from pathlib import Path

import pytest

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
    ContractError,
    FailureReason,
    RealizerRequest,
)
from benchmarks.semantic_roundtrip.model_output_recovery import (
    BoundedModelOutputRecovery,
)
from benchmarks.semantic_roundtrip.replacement_matrix import (
    CAPABILITY_UNAVAILABLE,
    DEFAULT_REPLACEMENT_QUALIFICATION_PATH,
    MODEL_REPEAT_COUNT,
    PHYSICAL_MODEL_SLOT_COUNT,
    QUALIFIED_CANDIDATE,
    QUALIFIED_REPLACEMENT_MATRIX_INTERFACE,
    REPLACEMENT_COORDINATE_RECEIPT_SCHEMA,
    REPLACEMENT_COORDINATE_RUNNER_INTERFACE,
    REPLACEMENT_QUALIFICATION_SCHEMA,
    ROLE_AWARE_MODEL_RECOVERY_INTERFACE,
    TERMINAL_UNSUPPORTED,
    ReplacementQualificationError,
    RoleAwareModelRecovery,
    build_balanced_model_schedule,
    build_replacement_coordinate_runner,
    build_replacement_qualification,
    load_replacement_qualification,
    run_deterministic_pilot_smoke,
    validate_replacement_qualification,
)
from benchmarks.semantic_roundtrip_capabilities import (
    LEANSTRAL_ENDPOINT,
    LEANSTRAL_MODEL,
)
from benchmarks.semantic_roundtrip.matrix import MatrixCase, load_matrix_cases


ROOT = Path(__file__).resolve().parents[4]
FIXTURE = ROOT / "tests/fixtures/semantic_roundtrip/pilot_cases.json"


@pytest.fixture(scope="module")
def qualification() -> dict[str, object]:
    return load_replacement_qualification(
        DEFAULT_REPLACEMENT_QUALIFICATION_PATH,
        repo_root=ROOT,
    )


def _passing_validator(
    left: CanonicalRuleIR,
    right: CanonicalRuleIR,
    request_id: str,
) -> dict[str, object]:
    return {
        "status": "passed",
        "exact": left == right,
        "request_id": request_id,
    }


FAKE_VALIDATORS = {
    "hammer_cvc5": _passing_validator,
    "lean": _passing_validator,
}


@pytest.fixture(scope="module")
def cases() -> tuple[MatrixCase, ...]:
    return load_matrix_cases(FIXTURE)


@pytest.fixture(scope="module")
def coordinate_runner(
    qualification: dict[str, object],
):
    return build_replacement_coordinate_runner(
        qualification,
        validators=FAKE_VALIDATORS,
    )


def test_checked_qualification_preserves_exact_matrix_and_protocol(
    qualification: dict[str, object],
) -> None:
    assert qualification["schema_version"] == REPLACEMENT_QUALIFICATION_SCHEMA
    assert qualification["interface"] == (
        QUALIFIED_REPLACEMENT_MATRIX_INTERFACE
    )
    assert qualification["frozen_before_scored_execution"] is True
    plan = qualification["plan"]
    assert isinstance(plan, dict)
    assert plan["cell_count"] == 30
    assert len(plan["deterministic_cell_ids"]) == 4
    assert len(plan["model_backed_cell_ids"]) == 26
    assert len(
        set(plan["deterministic_cell_ids"])
        | set(plan["model_backed_cell_ids"])
    ) == 30
    assert plan["selection_gates"] == [
        "source_copy_exclusion",
        "polarity_preservation",
        "full_coverage",
    ]
    assert plan["loss_policy"] == {
        "aggregation": "per_case_first_macro_mean",
        "failure_loss": 1.0,
        "missing_coordinate_allowed": False,
        "primary": "end_to_end",
    }
    assert plan["physical_model_slots"] == PHYSICAL_MODEL_SLOT_COUNT
    assert plan["coordinate_execution"] == {
        "arguments": [
            "case",
            "cell_id",
            "repeat_index",
            "cache_namespace",
        ],
        "deterministic_realizer_configuration_cid": (
            qualification["bindings"]["adapters"][
                "source_withheld_paraphrase"
            ]["configuration_cid"]
        ),
        "factory": "build_replacement_coordinate_runner",
        "frozen_coordinate_count": 670,
        "interface": REPLACEMENT_COORDINATE_RUNNER_INTERFACE,
        "method": "run_coordinate",
        "native_stage_receipts_required": True,
        "post_hoc_validation_receipts_required": True,
        "receipt_schema": REPLACEMENT_COORDINATE_RECEIPT_SCHEMA,
        "role_dispatch": {
            "l1": "recover_l1",
            "l2": "recover_l2_requires_exact_l1",
            "t1": "recover_t1",
        },
        "terminal_unsupported_is_typed_loss_one": True,
    }
    assert plan["historical_plan_preserved"] is True
    lineage = qualification["lineage"]
    assert isinstance(lineage, dict)
    fixture = lineage["fixture"]
    assert fixture["unchanged"] is True
    assert fixture["case_count"] == 5
    assert fixture["case_ids"] == [
        "exception_with_window",
        "legal_doc_1",
        "exec_order_1",
        "corp_policy_1",
        "construction_contract",
    ]
    assert lineage["historical"]["protocol_immutable"] is True


def test_every_arm_has_unique_exact_identity_and_honest_terminal_state(
    qualification: dict[str, object],
) -> None:
    arms = qualification["plan"]["arms"]
    assert len(arms) == 30
    assert len({arm["cell_id"] for arm in arms}) == 30
    assert len({arm["arm_identity_cid"] for arm in arms}) == 30
    assert all(
        validate_cid(
            arm["arm_identity_cid"], codecs=("dag-json",)
        )
        == arm["arm_identity_cid"]
        for arm in arms
    )
    statuses = Counter(arm["qualification_status"] for arm in arms)
    assert statuses[QUALIFIED_CANDIDATE] >= 1
    assert statuses[TERMINAL_UNSUPPORTED] == 12
    assert statuses[CAPABILITY_UNAVAILABLE] == 0
    guided = [
        arm
        for arm in arms
        if arm["composition"]["guidance"] == "guided"
    ]
    assert len(guided) == 12
    assert all(
        arm["qualification_status"] == TERMINAL_UNSUPPORTED
        and arm["qualification_reason"]
        == "unavailable_no_reviewed_causal_l1_adapter"
        and arm["selection_eligibility"] is False
        for arm in guided
    )
    candidates = [
        arm
        for arm in arms
        if arm["qualification_status"] == QUALIFIED_CANDIDATE
    ]
    assert all(
        arm["selection_eligibility"] == "pending_scored_execution"
        and arm["fallback_allowed"] is False
        and arm["substitute_allowed"] is False
        for arm in candidates
    )


def test_exact_capability_adapter_prompt_and_schema_bindings(
    qualification: dict[str, object],
) -> None:
    bindings = qualification["bindings"]
    capabilities = bindings["capabilities"]
    assert set(capabilities) == {
        "python",
        "multiformats",
        "spacy_pipeline",
        "autoencoder_state",
        "leanstral_direct",
        "symai_leanstral_route",
        "hammer_cvc5",
        "lean",
    }
    assert all(
        record["status"] == "available"
        and record["substitute_used"] is False
        and validate_cid(record["record_cid"], codecs=("dag-json",))
        for record in capabilities.values()
    )
    adapters = bindings["adapters"]
    assert {
        "coordinate_runner",
        "source_withheld_paraphrase",
        "model_output_recovery",
        "causal_guidance",
        "symai_router_contract",
    }.issubset(adapters)
    model = adapters["model_output_recovery"]
    assert model["role_dispatch"] == {
        "implicit_role_inference_allowed": False,
        "interface": ROLE_AWARE_MODEL_RECOVERY_INTERFACE,
        "l1": "construct_l1",
        "l2": "construct_l2_requires_exact_l1",
        "t1": "realize_t1",
    }
    assert model["call_contract"]["response_format"] == "strict_json_schema"
    assert model["call_contract"]["seed"] == 0
    assert model["call_contract"]["cache_prompt"] is False
    assert model["call_contract"]["stop"] == ["<|im_end|>"]
    assert model["call_contract"]["physical_model_slots"] == 1
    router = adapters["symai_router_contract"]
    assert router["gitlink_commit"] == (
        "f979431ac5fe3c4a088a2f15ec6379fba48bbde6"
    )
    assert validate_cid(router["source_raw_cid"], codecs=("raw",))


def test_non_scored_positive_and_negative_smokes_are_complete(
    qualification: dict[str, object],
) -> None:
    smokes = qualification["smokes"]
    assert smokes["scored"] is False
    deterministic = smokes["deterministic_five_case"]
    assert deterministic["status"] == "passed"
    assert deterministic["case_count"] == 5
    assert all(
        record["nonempty_l1_t1_l2"] is True
        and all(record["gates"].values())
        for record in deterministic["records"]
    )
    model = smokes["model_routes"]
    assert set(model["routes"]) == {"direct", "symai"}
    for route in model["routes"].values():
        assert route["status"] == "passed"
        assert route["fallback_used"] is False
        assert route["physical_model_slots"] == 1
        assert route["nonempty_l1_t1_l2"] is True
        assert route["opf_preserved"] is True
        assert [record["role"] for record in route["roles"]] == [
            "l1",
            "t1",
            "l2",
        ] * 3
        assert [record["probe_modality"] for record in route["roles"]] == [
            "O",
            "O",
            "O",
            "P",
            "P",
            "P",
            "F",
            "F",
            "F",
        ]
        assert all(
            record["status"] == "success"
            and validate_cid(record["prompt_cid"], codecs=("raw",))
            and validate_cid(record["schema_cid"], codecs=("dag-json",))
            and validate_cid(
                record["recovery_receipt_cid"], codecs=("dag-json",)
            )
            for record in route["roles"]
        )
    assert all(model["negative_controls"].values())


def test_schedule_is_frozen_unique_uncached_and_position_balanced(
    qualification: dict[str, object],
) -> None:
    schedule = qualification["schedule"]
    model_arms = qualification["plan"]["model_backed_cell_ids"]
    assert schedule["repeat_count"] == MODEL_REPEAT_COUNT
    assert schedule["physical_model_slots"] == 1
    assert schedule["block_count"] == 25
    assert schedule["coordinate_count"] == 650
    assert len(schedule["blocks"]) == 25
    namespaces = [
        coordinate["cache_namespace"]
        for block in schedule["blocks"]
        for coordinate in block["coordinates"]
    ]
    assert len(namespaces) == len(set(namespaces)) == 650
    assert all(
        coordinate["cache_mode"] == "uncached"
        for block in schedule["blocks"]
        for coordinate in block["coordinates"]
    )
    per_arm = Counter(
        coordinate["arm_id"]
        for block in schedule["blocks"]
        for coordinate in block["coordinates"]
    )
    assert set(per_arm) == set(model_arms)
    assert set(per_arm.values()) == {25}
    for position in range(26):
        counts = Counter(
            block["arm_order"][position] for block in schedule["blocks"]
        )
        observed = [counts[arm_id] for arm_id in model_arms]
        assert max(observed) - min(observed) <= 1
    assert 5 * 4 + schedule["coordinate_count"] == 670


def test_schedule_builder_is_content_addressed_and_deterministic() -> None:
    plan_cid = cid_for_dag_json({"plan": "fixture"})
    arms = [f"model-arm-{index:02d}" for index in range(26)]
    cases = [f"case-{index}" for index in range(5)]
    first = build_balanced_model_schedule(
        model_arm_ids=arms, case_ids=cases, plan_cid=plan_cid
    )
    second = build_balanced_model_schedule(
        model_arm_ids=arms, case_ids=cases, plan_cid=plan_cid
    )
    assert first == second
    body = dict(first)
    supplied = body.pop("schedule_cid")
    assert supplied == cid_for_dag_json(body)
    assert len(
        {
            coordinate["cache_namespace"]
            for block in first["blocks"]
            for coordinate in block["coordinates"]
        }
    ) == 650


def test_coordinate_registry_exactly_preserves_frozen_rotated_schedule_order(
    qualification: dict[str, object],
    coordinate_runner,
) -> None:
    coordinates = coordinate_runner.frozen_coordinates()
    assert len(coordinates) == 670
    assert len(
        {
            (
                item["case_id"],
                item["cell_id"],
                item["repeat_index"],
                item["cache_namespace"],
            )
            for item in coordinates
        }
    ) == 670
    expected_model_tail = [
        {
            "case_id": block["case_id"],
            "cell_id": coordinate["arm_id"],
            "repeat_index": block["repeat_index"],
            "cache_namespace": coordinate["cache_namespace"],
        }
        for block in qualification["schedule"]["blocks"]
        for coordinate in block["coordinates"]
    ]
    assert list(coordinates[20:]) == expected_model_tail


def test_coordinate_runner_executes_deterministic_path_with_paraphraser_receipt(
    qualification: dict[str, object],
    cases: tuple[MatrixCase, ...],
    coordinate_runner,
) -> None:
    case = cases[0]
    cell_id = (
        "typed_deontic__no_guidance__no_repair__not_applicable"
        "__deterministic"
    )
    namespace = coordinate_runner.cache_namespace_for(
        case_id=case.case_id,
        cell_id=cell_id,
        repeat_index=0,
    )
    execution = coordinate_runner.run_coordinate(
        case,
        cell_id,
        0,
        namespace,
    )
    assert execution.status is ComponentStatus.SUCCESS
    assert execution.to_dict()["schema_version"] == (
        REPLACEMENT_COORDINATE_RECEIPT_SCHEMA
    )
    receipt = execution.to_dict()
    assert receipt["execution_disposition"] == "executed_complete"
    assert receipt["stage_count"] == 3
    assert [stage["role"] for stage in receipt["stages"]] == [
        "l1",
        "t1",
        "l2",
    ]
    paraphraser = receipt["stages"][1]["component_receipt"]
    assert paraphraser["interface"] == (
        "SourceWithheldParaphraseAttribution@1"
    )
    assert paraphraser["input_attribution"][
        "frozen_replacement_config_cid"
    ] == qualification["bindings"]["adapters"][
        "source_withheld_paraphrase"
    ]["configuration_cid"]
    assert all(
        validate_cid(
            stage["stage_receipt_cid"],
            codecs=("dag-json",),
        )
        for stage in receipt["stages"]
    )
    semantic = receipt["semantic_record"]
    assert set(semantic) == {
        "interface",
        "case_id",
        "case_cid",
        "cell_id",
        "constructor",
        "realizer",
        "status",
        "failure",
        "artifacts",
        "losses",
        "diagnostics",
        "candidate_cid",
        "validation",
        "record_cid",
    }
    assert semantic["cell_id"] == cell_id
    assert semantic["record_cid"] == receipt["semantic_record_cid"]
    semantic_body = dict(semantic)
    semantic_record_cid = semantic_body.pop("record_cid")
    assert semantic_record_cid == cid_for_dag_json(semantic_body)
    assert set(semantic["diagnostics"]) == {
        "semantic_comparisons",
        "source_copy",
        "polarity",
        "gates",
        "l1_payload_cid",
        "constructor_config_cid",
        "realizer_config_cid",
        "same_constructor_reapplied",
    }
    assert set(semantic["validation"]) == {
        "phase",
        "status",
        "candidate_cid",
        "candidate_unchanged",
        "scope",
        "results",
        "hammer_cvc5",
        "lean",
    }
    assert semantic["candidate_cid"] == receipt["candidate_cid"]
    assert semantic["validation"]["candidate_unchanged"] is True
    assert receipt["semantic_contract_unchanged"] is True
    assert receipt["candidate_bound_before_post_hoc_validation"] is True


def test_coordinate_runner_returns_typed_loss_one_for_guided_arm(
    cases: tuple[MatrixCase, ...],
    coordinate_runner,
) -> None:
    case = cases[0]
    cell_id = (
        "typed_deontic__guided__no_repair__not_applicable"
        "__deterministic"
    )
    namespace = coordinate_runner.cache_namespace_for(
        case_id=case.case_id,
        cell_id=cell_id,
        repeat_index=0,
    )
    execution = coordinate_runner.run_coordinate(
        case,
        cell_id,
        0,
        namespace,
    )
    assert execution.status is ComponentStatus.FAILED
    assert execution.result.failure_reason is (
        FailureReason.CAPABILITY_UNAVAILABLE
    )
    assert execution.primary_loss == 1.0
    receipt = execution.to_dict()
    assert receipt["execution_disposition"] == TERMINAL_UNSUPPORTED
    assert receipt["stage_count"] == 0
    assert receipt["qualification_reason"] == (
        "unavailable_no_reviewed_causal_l1_adapter"
    )
    assert receipt["fallback_used"] is False
    assert receipt["substitute_used"] is False


class CoordinateScriptedClient:
    endpoint = LEANSTRAL_ENDPOINT
    model = LEANSTRAL_MODEL
    cache_prompt = False

    def __init__(self, case: MatrixCase) -> None:
        polarity = {
            "O": "obligation",
            "P": "permission",
            "F": "prohibition",
        }
        realized = []
        for index, rule in enumerate(case.gold_ir.rules):
            modal = {
                "O": "must",
                "P": "may",
                "F": "must not",
            }[rule.modality]
            realized.append(
                {
                    "index": index,
                    "modality": rule.modality,
                    "polarity": polarity[rule.modality],
                    "text": (
                        f"{rule.actor.replace('_', ' ').title()} {modal} "
                        f"{rule.action.replace('_', ' ')} "
                        f"{rule.object.replace('_', ' ')}."
                    ),
                }
            )
        self.outputs = [
            case.gold_ir.to_dict(),
            {"rules": realized},
            case.gold_ir.to_dict(),
        ]

    def complete_json(self, **_: object) -> dict[str, object]:
        return self.outputs.pop(0)


def test_model_coordinate_retains_raw_role_explicit_recovery_receipts(
    qualification: dict[str, object],
    cases: tuple[MatrixCase, ...],
) -> None:
    case = cases[0]
    runner = build_replacement_coordinate_runner(
        qualification,
        client_factories={
            "direct": lambda: CoordinateScriptedClient(case),
        },
        validators=FAKE_VALIDATORS,
    )
    cell_id = (
        "model__not_applicable__always_on__direct"
        "__leanstral_direct"
    )
    namespace = runner.cache_namespace_for(
        case_id=case.case_id,
        cell_id=cell_id,
        repeat_index=0,
    )
    execution = runner.run_coordinate(case, cell_id, 0, namespace)
    assert execution.status is ComponentStatus.SUCCESS
    receipt = execution.to_dict()
    assert receipt["route_mapping"] == {
        "constructor": "direct",
        "realizer": "direct",
        "selective_repair": "not_applicable",
    }
    assert [stage["role"] for stage in receipt["stages"]] == [
        "l1",
        "t1",
        "l2",
    ]
    for stage, role in zip(
        receipt["stages"],
        ("l1", "t1", "l2"),
        strict=True,
    ):
        native = stage["component_receipt"]
        assert native["interface"] == "RoleExplicitModelRecoveryResult@1"
        assert native["role"] == role
        assert native["status"] == "success"
        assert native["recovery_receipt"]["role"] == role
        assert native["recovery_receipt"]["boundary"][
            "fallback_allowed"
        ] is False
        assert validate_cid(
            native["recovery_receipt_cid"],
            codecs=("dag-json",),
        )
        assert validate_cid(
            native["result_receipt_cid"],
            codecs=("dag-json",),
        )


class NeverCalledDirectClient:
    endpoint = LEANSTRAL_ENDPOINT
    model = LEANSTRAL_MODEL
    cache_prompt = False

    def complete_json(self, **_: object) -> dict[str, object]:
        raise AssertionError("complete canonical baselines must not trigger repair")


def test_selective_coordinate_retains_repair_and_paraphraser_receipts(
    qualification: dict[str, object],
    cases: tuple[MatrixCase, ...],
) -> None:
    case = cases[0]
    runner = build_replacement_coordinate_runner(
        qualification,
        client_factories={
            "direct": NeverCalledDirectClient,
        },
        validators=FAKE_VALIDATORS,
    )
    cell_id = (
        "typed_deontic__no_guidance__selective__not_applicable"
        "__deterministic"
    )
    namespace = runner.cache_namespace_for(
        case_id=case.case_id,
        cell_id=cell_id,
        repeat_index=0,
    )
    execution = runner.run_coordinate(case, cell_id, 0, namespace)
    assert execution.status is ComponentStatus.SUCCESS
    stages = execution.to_dict()["stages"]
    assert stages[0]["component_receipt"]["interface"] == (
        "SelectiveRepairCausalReceipt@1"
    )
    assert stages[0]["component_receipt"]["status"] == "not_triggered"
    assert stages[1]["component_receipt"]["interface"] == (
        "SourceWithheldParaphraseAttribution@1"
    )
    assert stages[2]["component_receipt"]["interface"] == (
        "SelectiveRepairCausalReceipt@1"
    )


IR = CanonicalRuleIR(
    (
        CanonicalRule(
            "O",
            "agency",
            "file",
            "notice",
            temporal=("within_deadline",),
        ),
    )
)
VOCABULARY = AllowedAtomVocabulary(
    actors=("agency",),
    actions=("file",),
    objects=("notice",),
    qualifiers=("within_deadline",),
)


class ScriptedClient:
    endpoint = LEANSTRAL_ENDPOINT
    model = LEANSTRAL_MODEL
    cache_prompt = False

    def __init__(self) -> None:
        self.outputs = [
            IR.to_dict(),
            {
                "rules": [
                    {
                        "index": 0,
                        "modality": "O",
                        "polarity": "obligation",
                        "text": "The agency must file the notice.",
                    }
                ]
            },
            IR.to_dict(),
        ]

    def complete_json(self, **_: object) -> dict[str, object]:
        return self.outputs.pop(0)


def test_role_aware_adapter_never_infers_l1_or_l2_from_call_order() -> None:
    adapter = RoleAwareModelRecovery(
        BoundedModelOutputRecovery(ScriptedClient(), route="direct")
    )
    assert adapter.identity.startswith(ROLE_AWARE_MODEL_RECOVERY_INTERFACE)
    l1 = adapter.construct_l1(
        ConstructorRequest("The agency must file notice.", VOCABULARY, {})
    )
    assert l1.status is ComponentStatus.SUCCESS
    assert l1.canonical_ir == IR
    t1 = adapter.realize_t1(RealizerRequest(IR, VOCABULARY, {}))
    assert t1.status is ComponentStatus.SUCCESS
    assert t1.text == "The agency must file the notice."
    l2 = adapter.construct_l2(
        ConstructorRequest(t1.text, VOCABULARY, {}),
        expected_l1=IR,
    )
    assert l2.status is ComponentStatus.SUCCESS
    assert l2.canonical_ir == IR
    with pytest.raises(ContractError, match="exact nonempty preceding L1"):
        adapter.construct_l2(
            ConstructorRequest(t1.text, VOCABULARY, {}),
            expected_l1=CanonicalRuleIR(()),
        )
    assert not hasattr(adapter, "construct")


def test_unavailable_symai_preflight_is_explicit_not_substituted(
    qualification: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smokes = copy.deepcopy(qualification["smokes"]["model_routes"])
    smokes["routes"]["symai"].update(
        {
            "status": "unavailable",
            "reason": "typed_model_preflight:route_contract_failure",
            "nonempty_l1_t1_l2": False,
            "opf_preserved": False,
        }
    )
    body = dict(smokes)
    body.pop("smoke_cid")
    smokes["smoke_cid"] = cid_for_dag_json(body)
    monkeypatch.setattr(
        "benchmarks.semantic_roundtrip.replacement_matrix."
        "run_deterministic_pilot_smoke",
        lambda cases: qualification["smokes"]["deterministic_five_case"],
    )
    rebuilt = build_replacement_qualification(
        repo_root=ROOT, model_smokes=smokes
    )
    affected = [
        arm
        for arm in rebuilt["plan"]["arms"]
        if "symai" in arm["route_requirements"]
        and arm["composition"]["guidance"] != "guided"
    ]
    assert affected
    assert all(
        arm["qualification_status"] == CAPABILITY_UNAVAILABLE
        and arm["qualification_reason"]
        == "route_preflight_unavailable:symai"
        and arm["fallback_allowed"] is False
        for arm in affected
    )
    assert rebuilt["summary"]["at_least_one_fully_qualified_candidate"] is True


def test_cids_and_fresh_evidence_reject_readdressed_tampering(
    qualification: dict[str, object],
) -> None:
    body = copy.deepcopy(qualification)
    supplied = body.pop("qualification_cid")
    assert supplied == cid_for_dag_json(body)
    tampered = copy.deepcopy(qualification)
    tampered["schedule"]["blocks"][0]["arm_order"].reverse()
    schedule_body = dict(tampered["schedule"])
    schedule_body.pop("schedule_cid")
    tampered["schedule"]["schedule_cid"] = cid_for_dag_json(schedule_body)
    qualification_body = dict(tampered)
    qualification_body.pop("qualification_cid")
    tampered["qualification_cid"] = cid_for_dag_json(qualification_body)
    with pytest.raises(
        ReplacementQualificationError, match="contradicts|schedule"
    ):
        validate_replacement_qualification(tampered, repo_root=ROOT)


def test_deterministic_smoke_recomputes_all_five_cases() -> None:
    from benchmarks.semantic_roundtrip.matrix import load_matrix_cases

    smoke = run_deterministic_pilot_smoke(load_matrix_cases(FIXTURE))
    assert smoke["status"] == "passed"
    assert smoke["case_count"] == 5
    assert all(
        record["nonempty_l1_t1_l2"] is True
        and all(record["gates"].values())
        for record in smoke["records"]
    )


def test_qualification_uses_cids_instead_of_new_legacy_digest_fields() -> None:
    source = (
        ROOT / "benchmarks/semantic_roundtrip/replacement_matrix.py"
    ).read_text(encoding="utf-8")
    assert "hashlib" not in source
    assert "sha256" not in source.lower()
    assert DEFAULT_REPLACEMENT_QUALIFICATION_PATH.is_file()
