"""New profiles preserve native outputs and cannot bypass binding or proof gates."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib.util
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import family_training as core
from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v2 as old
from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v3 as api
from ipfs_datasets_py.logic.formalization.autoencoder.native_formula_evidence import NativeFormulaEvidence
from ipfs_datasets_py.logic.security_ir.code_logic_projection import CodeLogicEvidence, project_code_logic
from ipfs_datasets_py.logic.software_verification.temporal import TemporalFormula, TemporalLogic


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


HERE = Path(__file__).resolve().parent
fixtures = _load("family_v3_fixtures", HERE / "test_family_training.py")
v2_fixtures = _load("family_v3_supplement_fixtures", HERE / "test_family_training_v2.py")
security = fixtures._security
binding = fixtures.binding


def _intent():
    text = "agent must inspect cache."
    return dict(document=fixtures.parse_instruction(text), source_text=text)


def _rehash(report):
    for row in report["projections"]:
        row["target_sha256"] = core._sha({key: value for key, value in row.items() if key != "target_sha256"})
    report["report_sha256"] = core._sha({key: value for key, value in report.items() if key != "report_sha256"})
    return report


@pytest.mark.parametrize("domain", core.DOMAINS)
def test_catalog_has40_families_and8_distinct_native_formula_profiles(domain):
    catalog = api.family_training_catalog_v3(domain)
    assert len(catalog["family_inventory"]) == 40
    assert not any(row["ready_for_training"] for row in catalog["family_inventory"])
    routes = {row["requirement_id"]: (row["family_id"], row["profile"]) for row in catalog["named_formula_routes"]}
    assert routes["CEC"] == ("event_calculus", "cognitive_event_calculus")
    assert routes["DCEC"] == ("dcec", "deontic_cognitive_event_calculus")
    assert not catalog["source_text_to_native_formula_inference"]
    assert "tla_plus" not in {row["family_id"] for row in catalog["family_inventory"]}


def test_security_tla_is_distinct_profile_of_exact_existing_native_artifact(binding):
    unit, source = binding
    inputs = [CodeLogicEvidence(security.transition(source), source)]
    kwargs = dict(code_unit=unit, source_bytes=fixtures.BODY, typed_inputs=inputs)
    old_before = old.prepare_family_training_targets_v2("security_ir", requested_families=["transition_system"], **kwargs)
    report = api.prepare_family_training_targets_v3("security_ir", requested_families=["transition_system"], **kwargs)
    assert len(old_before["projections"]) == 1 and len(report["projections"]) == 2
    target = next(row for row in report["projections"] if row["profile"] == "tla_plus")
    actual = project_code_logic(requested_kinds=["transition"], **kwargs)
    assert target["projection_id"] == "security_ir/transition/tla_plus/v3"
    assert target["payload"]["artifact"] == actual["targets"][0]["encoding"]["artifact"]
    assert target["payload"]["native_document"] == security.transition(source).to_dict()
    assert target["payload"]["native_bridge"] == actual["targets"][0]["bridge"]
    assert target["payload"]["source_binding"] == actual["source"]
    artifact = target["payload"]["artifact"]
    assert artifact["losses"] and artifact["bounded"] and not artifact["unbounded_proof"]
    assert "MODULE CodeTransition" in artifact["model_text"]
    checks = target["validation"][0]["details"]
    assert not checks["syntax_checker_executed"] and not checks["model_checker_executed"]
    assert checks["native_generated_properties_are_not_source_obligations"]
    assert api.validate_family_training_report_v3(report, **kwargs) == report
    assert old.prepare_family_training_targets_v2("security_ir", requested_families=["transition_system"], **kwargs) == old_before
    assert not any(report[name] for name in core.AUTHORITY)
    assert not report["structural_readiness_is_qualification"]


def test_security_labels_or_program_alone_do_not_create_tla(binding):
    unit, source = binding
    for inputs in ([], [CodeLogicEvidence(security.program(source), source)]):
        report = api.prepare_family_training_targets_v3("security_ir", code_unit=unit,
            source_bytes=fixtures.BODY, typed_inputs=inputs, requested_families=["transition_system"])
        assert report["projections"] == [] and not report["all_requested_families_available"]


def test_security_source_mutation_refuses_separate_tla(binding):
    unit, source = binding
    with pytest.raises(ValueError, match="SHA differs"):
        api.prepare_family_training_targets_v3("security_ir", code_unit=unit, source_bytes=fixtures.BODY + b"\n",
            typed_inputs=[CodeLogicEvidence(security.transition(source), source)])


def test_intent_explicit_program_contract_state_transition_temporal_are_separate_targets():
    kwargs = _intent()
    source = api.supplemental_source_ref("intent_ir", **kwargs)
    state = security.transition(source)
    native = [security.program(source), security.contract(source), state.schema, state,
        TemporalFormula("always", operands=(TemporalFormula("atom", proposition="safe"),))]
    supplied = [api.TypedFamilyEvidence(value, source) for value in native]
    report = api.prepare_family_training_targets_v3("intent_ir", supplemental_inputs=supplied, **kwargs)
    values = {row["projection_id"]: row for row in report["projections"] if "/supplemental/" in row["projection_id"]}
    assert len(values) == 5 and len(report["additional_native_inputs"]) == 5
    assert values["intent_ir/supplemental/contract/v3"]["profile"] == "dynamic_hoare"
    assert values["intent_ir/supplemental/transition/v3"]["payload"]["native_document"] == state.to_dict()
    assert api.validate_family_training_report_v3(report, supplemental_inputs=supplied, **kwargs) == report
    reversed_report = api.prepare_family_training_targets_v3("intent_ir", supplemental_inputs=list(reversed(supplied)), **kwargs)
    assert reversed_report == report
    with pytest.raises(ValueError, match="not applicable"):
        old.prepare_family_training_targets_v2("intent_ir", supplemental_inputs=supplied, **kwargs)


def test_intent_contract_without_program_retains_explicit_frontier():
    kwargs = _intent()
    source = api.supplemental_source_ref("intent_ir", **kwargs)
    report = api.prepare_family_training_targets_v3("intent_ir",
        supplemental_inputs=[api.TypedFamilyEvidence(security.contract(source), source)], **kwargs)
    assert not any("/supplemental/contract/" in row["projection_id"] for row in report["projections"])
    assert any(row["reason"] == "supplemental_contract_requires_matching_native_program" for row in report["frontier"])


@pytest.mark.parametrize("bad", ["outer_ref", "embedded_ref", "duplicate", "raw_dict"])
def test_intent_supplement_binding_and_type_are_not_labels(bad):
    kwargs = _intent()
    source = api.supplemental_source_ref("intent_ir", **kwargs)
    other = replace(source, source_revision="different")
    model = security.program(source if bad != "embedded_ref" else other)
    inputs = [api.TypedFamilyEvidence(model, other if bad == "outer_ref" else source)]
    if bad == "duplicate": inputs *= 2
    if bad == "raw_dict": inputs = [model.to_dict()]
    with pytest.raises(ValueError):
        api.prepare_family_training_targets_v3("intent_ir", supplemental_inputs=inputs, **kwargs)


def test_non_ltl_native_temporal_remains_unsupported():
    kwargs = _intent()
    source = api.supplemental_source_ref("intent_ir", **kwargs)
    native = TemporalFormula("atom", proposition="safe", logic=TemporalLogic.CTL)
    report = api.prepare_family_training_targets_v3("intent_ir", **kwargs,
        supplemental_inputs=[api.TypedFamilyEvidence(native, source)])
    assert not any("/supplemental/temporal/" in row["projection_id"] for row in report["projections"])
    assert any(row["reason"] == "native_bridge_profile_is_LTL_only" for row in report["frontier"])


def test_explicit_native_fol_formula_has_source_and_actual_parser_evidence():
    kwargs = _intent()
    source = api.supplemental_source_ref("intent_ir", **kwargs)
    supplied = [NativeFormulaEvidence("FOL", "Inspect(agent, cache)", source)]
    report = api.prepare_family_training_targets_v3("intent_ir", formula_inputs=supplied, **kwargs)
    row = next(row for row in report["projections"] if "/native_formula/" in row["projection_id"])
    assert row["logic_family"] == "first_order" and row["profile"] == "first_order"
    assert row["payload"]["source_ref"] == source.to_dict()
    assert row["payload"]["native_ast"] and row["payload"]["ast_format"]
    assert len(row["validation"]) == 3 and all(check["status"] == "passed" for check in row["validation"])
    assert api.validate_family_training_report_v3(report, formula_inputs=supplied, **kwargs) == report
    assert not row["source_semantics_verified"] and not row["proof_authority"]


@pytest.mark.parametrize("domain", core.DOMAINS)
def test_all8_native_formula_profiles_stay_distinct_in_each_domain(domain, binding):
    if domain == "intent_ir": kwargs = _intent()
    elif domain == "ui_ux_ir": kwargs = dict(ui_training_row=v2_fixtures.untimed_row())
    elif domain == "security_ir": kwargs = dict(code_unit=binding[0], source_bytes=fixtures.BODY)
    else: kwargs = dict(document=fixtures.legal_document(), source_text="Officer must report.")
    source = api.supplemental_source_ref(domain, **kwargs)
    values = {"FOL": "forall x. Person(x) -> Reports(x)", "DFOL": "forall x. O(Reports(x))",
        "TFOL": "forall x. □(Reports(x))", "TDFOL": "forall x. O(□(Reports(x)))",
        "CEC": "K(Officer,Happens(Submit,Time))", "DCEC": "O(K(Officer,Happens(Submit,Time)))",
        "frame_logic": "alice[role -> officer].", "propositional": "p and q"}
    supplied = [NativeFormulaEvidence(key, value, source) for key, value in values.items()]
    report = api.prepare_family_training_targets_v3(domain, formula_inputs=supplied, **kwargs)
    actual = [row for row in report["projections"] if "/native_formula/" in row["projection_id"]]
    assert len(actual) == 8 and len({row["profile"] for row in actual}) == 8
    assert all(row["ready_for_training"] for row in actual)
    assert len(report["family_inventory"]) == 40 and not report["all_requested_families_available"]
    assert api.validate_family_training_report_v3(report, formula_inputs=supplied, **kwargs) == report
    assert not any(report[key] for key in core.AUTHORITY)


@pytest.mark.parametrize("bad", ["wrong_ref", "duplicate", "raw_dict"])
def test_formula_evidence_rejects_invalid_join_or_duplicate_requirement(bad):
    kwargs = _intent()
    source = api.supplemental_source_ref("intent_ir", **kwargs)
    item = NativeFormulaEvidence("FOL", "Inspect(agent, cache)",
        replace(source, source_revision="wrong") if bad == "wrong_ref" else source)
    inputs = [item, item] if bad == "duplicate" else [{"formula": item.formula}] if bad == "raw_dict" else [item]
    with pytest.raises(ValueError):
        api.prepare_family_training_targets_v3("intent_ir", formula_inputs=inputs, **kwargs)


def test_rehashed_target_tampering_still_fails_exact_source_replay(binding):
    unit, source = binding
    kwargs = dict(code_unit=unit, source_bytes=fixtures.BODY,
        typed_inputs=[CodeLogicEvidence(security.transition(source), source)])
    report = api.prepare_family_training_targets_v3("security_ir", requested_families=["transition_system"], **kwargs)
    tampered = deepcopy(report)
    next(row for row in tampered["projections"] if row["profile"] == "tla_plus")["payload"]["artifact"]["model_text"] += "\n\\* forged"
    _rehash(tampered)
    with pytest.raises(ValueError, match="exact typed source replay"):
        api.validate_family_training_report_v3(tampered, **kwargs)


def test_v3_import_pin_guard_fails_closed(monkeypatch):
    original = api._IMPORT_PINS[api.__name__]
    monkeypatch.setitem(api._IMPORT_PINS, api.__name__, "0" * 64)
    with pytest.raises(ValueError, match="imported projection producer changed"):
        api.family_training_catalog_v3("intent_ir")
    assert original == hashlib.sha256(Path(api.__file__).read_bytes()).hexdigest()


def test_missing_producer_pin_and_authority_escalation_fail():
    report = api.prepare_family_training_targets_v3("intent_ir", **_intent())
    bad = deepcopy(report)
    del bad["producer_pins"][api.__name__]
    with pytest.raises(ValueError, match="producer pin required"):
        api.validate_family_training_report_v3(_rehash(bad))
    bad = deepcopy(report)
    bad["structural_readiness_is_qualification"] = True
    with pytest.raises(ValueError, match="cannot claim"):
        api.validate_family_training_report_v3(_rehash(bad))


def test_ui_existing_unlowered_timeout_semantics_stay_explicit():
    report = api.prepare_family_training_targets_v3("ui_ux_ir", ui_training_row=fixtures.native_row(),
        requested_families=["transition_system"])
    assert not report["projections"]
    assert any(row["reason"] == "UI_timeout_semantics_not_lowered" for row in report["frontier"])


def test_legal_temporal_F_never_becomes_prohibition_or_combined_TDFOL():
    document = fixtures.modal_document()
    original = old.prepare_family_training_targets_v2("legal_ir", document=document)
    legacy = next(row for row in original["projections"] if row["projection_id"] == "legal-ir/modal-view/deontic/v1")
    assert any(row["formula_id"] == "time:one" and row["norm_type"] == "prohibition" for row in legacy["payload"])
    report = api.prepare_family_training_targets_v3("legal_ir", document=document)
    rows = {row["projection_id"]: row for row in report["projections"]}
    deontic = rows["legal-ir/modal-family/deontic/v3"]
    temporal = rows["legal-ir/modal-family/temporal/v3"]
    assert deontic["logic_family"] == "deontic" and temporal["logic_family"] == "temporal"
    assert deontic["payload"]["formulas"] == [document.formulas[0].to_dict()]
    assert temporal["payload"]["formulas"] == [document.formulas[1].to_dict()]
    assert temporal["payload"]["formulas"][0]["operator"]["symbol"] == "F"
    assert not deontic["ready_for_training"] and not temporal["ready_for_training"]
    assert any(row["reason"] == "ModalIR_opaque_qualifiers_require_native_interpretation" for row in report["frontier"])
    assert not any(row["logic_family"] == "tdfol" for row in rows.values())
    assert legacy["projection_id"] not in rows
    archived = {row["original_projection"]["projection_id"]: row for row in report["superseded_projection_observations"]}
    assert archived[legacy["projection_id"]]["original_projection"] == legacy
    assert all(not row["active_for_training"] for row in archived.values())
    assert not deontic["validation"][0]["details"]["native_family_AST_parser_executed"]
    assert api.validate_family_training_report_v3(report, document=document) == report
    assert old.prepare_family_training_targets_v2("legal_ir", document=document) == original


def test_modal_partition_preserves_all_fields_and_unknown_families_fail_closed():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import ModalIROperator
    document = fixtures.modal_document()
    norm = replace(document.formulas[0], predicate=replace(document.formulas[0].predicate,
        arguments=["agency", "notice", "recipient"]), conditions=["if authorized", "within 10 days"],
        exceptions=["unless emergency"], metadata={"scope": {"uninterpreted": True}})
    unknown = replace(document.formulas[1], operator=ModalIROperator("unreviewed_logic", "custom", "O", "opaque"))
    document = replace(document, formulas=[unknown, norm])
    report = api.prepare_family_training_targets_v3("legal_ir", document=document)
    rows = {row["projection_id"]: row for row in report["projections"]}
    assert rows["legal-ir/modal-family/deontic/v3"]["payload"]["formulas"] == [norm.to_dict()]
    blocked = rows["legal-ir/modal-family/unreviewed/v3"]
    assert blocked["payload"]["formulas"] == [unknown.to_dict()]
    assert not blocked["ready_for_training"]
    assert any(row["reason"] == "unreviewed_declared_ModalIR_operator_family" for row in report["frontier"])
    assert api.validate_family_training_report_v3(report, document=document) == report


def test_temporal_only_narrow_deontic_request_cannot_relabel_temporal_F():
    document = fixtures.modal_document()
    document = replace(document, formulas=[document.formulas[1]])
    report = api.prepare_family_training_targets_v3("legal_ir", document=document, requested_families=["deontic"])
    assert not report["projections"] and not report["ready_for_training"]
    assert report["superseded_projection_observations"]
    assert report["unrequested_modal_formula_observations"][0]["native_formula_records"] == [document.formulas[0].to_dict()]


def test_actual_deontic_F_keeps_declared_prohibition_family():
    document = fixtures.modal_document()
    norm = replace(document.formulas[0], operator=replace(document.formulas[0].operator, symbol="F", label="prohibition"))
    document = replace(document, formulas=[norm])
    report = api.prepare_family_training_targets_v3("legal_ir", document=document, requested_families=["deontic"])
    assert len(report["projections"]) == 1
    row = report["projections"][0]
    assert row["logic_family"] == "deontic" and row["payload"]["formulas"] == [norm.to_dict()]
