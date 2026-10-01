"""Real native projectors plus optional actual Lake execution; no proof doubles."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import projections_v2 as api
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import contracts as c
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import profiles
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.projection_context_contract import bind_context
from ipfs_datasets_py.logic.formalization.autoencoder import native_formula_evidence
from ipfs_datasets_py.logic.intent_ir.schema import IntentKind, IntentModality
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.authored_semantic_projection_panel import FORMULAS, _intent
from tests.fixtures.logic.source_reconstruction_v3 import rows
from .test_distributed_384_projection_inputs import unit_for, security_inputs

DOMAINS = ("intent_ir", "security_ir", "ui_ux_ir", "legal_ir")
FORMULA_FAMILIES = sorted(row["family_id"] for row in native_formula_evidence.named_logic_routes())


def sample(domain):
    return deepcopy(rows(domain, "train")[0])


def declarative_intent_sample():
    source = _intent(0)
    text = "Authored declaration: officer must publish report."
    reference = replace(source["document"].sources[0], content_sha256=hashlib.sha256(text.encode()).hexdigest())
    document = replace(source["document"], sources=(reference,), intent_kind=IntentKind.DECLARATIVE,
        statements=(source["document"].statements[0],), actions=(), entry_action_ids=(), terminal_action_ids=())
    return dict(target=document.to_dict(), source_text=text)


def formula_inputs(domain, row):
    inputs = {"formula_inputs": [{"requirement_id": key, "formula": value} for key, value in FORMULAS.items()]}
    if domain == "security_ir":
        inputs["code_unit"] = unit_for(row["source_text"]).to_dict()
    return inputs


def prepared(domain, *, families=None, context_inputs=None, row=None):
    row = sample(domain) if row is None else row
    context = None if context_inputs is None else bind_context(domain, row["target"], row["source_text"], context_inputs)
    return api.prepare_candidate_projection(domain, row["target"], row["source_text"],
        context=context, required_families=families)


def family_index(report):
    return {family["family_id"]: family for family in report["families"]}


@pytest.mark.parametrize("domain,families", [
    ("intent_ir", ["deontic", "dcec", "tdfol", "frame_logic"]),
    ("security_ir", ["program"]), ("ui_ux_ir", ["frame_logic"]), ("legal_ir", ["deontic"]),
])
def test_old_supported_candidate_scopes_are_retained_without_proof_claim(domain, families):
    row = sample(domain)
    before = deepcopy(row)
    old = profiles.project_candidate(domain, row["target"], row["source_text"], families)
    new = prepared(domain, families=families, row=row).report
    assert old["all_required_families_supported"] and new["all_required_families_supported"]
    assert row == before
    assert new["candidate_sha256"] == old["candidate_sha256"] == c.digest(row["target"])
    assert new["source_sha256"] == hashlib.sha256(row["source_text"].encode()).hexdigest()
    assert all(item["projections"] for item in new["families"])
    assert not any(new[key] for key in (*c.FALSE, "execution_authority", "context_inferred_by_model",
        "target_rewritten", "lake_build_executed", "all_requested_native_checks_passed"))


@pytest.mark.parametrize("domain", DOMAINS)
def test_formula_context_exercises_all_eight_actual_parser_and_lean_lowering_routes(domain):
    row = sample(domain)
    inputs = formula_inputs(domain, row)
    saved = deepcopy(inputs)
    result = prepared(domain, families=FORMULA_FAMILIES, context_inputs=inputs, row=row)
    report = result.report
    formulas = [value for value in result.native_report["projections"] if "/native_formula/" in value["projection_id"]]
    assert len(formulas) == 8 and {p["logic_family"] for p in formulas} == set(FORMULA_FAMILIES)
    assert all(value["ready_for_training"] and value["payload"]["native_ast"] for value in formulas)
    assert all(value["payload"]["source_ref"]["content_sha256"] == report["source_sha256"] for value in formulas)
    assert all(not value["payload"]["source_meaning_verified"] for value in formulas)
    formula_lowerings = [item for family in report["families"] for item in family["native_lowering"]
                         if "/native_formula/" in item["projection_id"]]
    assert len(formula_lowerings) == 8 and all(item["semantic_lowering_supported"] for item in formula_lowerings)
    if domain == "intent_ir":
        # The source action emits a workflow that needs an auxiliary state
        # projection. Its incomplete abstraction remains visible as evidence.
        assert report["all_required_families_supported"]
        assert "transition_system" in report["auxiliary_families"]
        state = [value for value in report["native_report"]["projections"]
                 if value["logic_family"] == "transition_system"]
        assert state and any("partial_native_projection" in value["qualification_gaps"] for value in state)
        assert not report["complete_target_semantics"]
    else:
        assert report["all_required_families_supported"]
        assert all(item["status"] == "supported" for item in report["families"])
    assert inputs == saved
    assert result.source_inputs["formula_inputs"][0].__class__ is native_formula_evidence.NativeFormulaEvidence
    assert not report["source_semantics_verified"] and not report["lake_build_executed"]


@pytest.mark.parametrize("domain", DOMAINS)
def test_expanded_catalog_inventory_does_not_fabricate_missing_context(domain):
    catalog = api.family_catalog(domain)
    assert len(catalog["family_inventory"]) == 40
    assert set(FORMULA_FAMILIES) <= set(catalog["default_required_families"])
    report = prepared(domain).report
    assert not report["all_required_families_supported"]
    assert any(item["status"] == "missing_context" for item in report["families"])


def test_declarative_intent_without_workflow_supports_eight_native_formula_families():
    row = declarative_intent_sample()
    report = prepared("intent_ir", families=FORMULA_FAMILIES, row=row,
        context_inputs=formula_inputs("intent_ir", row)).report
    assert report["all_required_families_supported"]
    assert not report["auxiliary_families"]
    assert not report["source_semantics_verified"]


def test_native_semantic_reclassification_cannot_retain_retired_legacy_fact_coverage():
    report = prepared("intent_ir", families=["first_order"], row=declarative_intent_sample()).report
    assert report["candidate_valid"]
    assert all(value["logic_family"] != "first_order" for value in report["native_report"]["projections"])
    retired = report["native_report"]["superseded_intent_observations"]
    assert any(value["projection_id"] == "intent-route/facts/v1" and not value["active_for_training"]
               for value in retired)
    family = family_index(report)["first_order"]
    assert family["status"] == "missing_context"
    assert not family["projections"]
    assert not report["all_required_families_supported"]


@pytest.mark.parametrize("domain", DOMAINS)
@pytest.mark.parametrize("part", ["source", "candidate", "source_hash", "authority"])
def test_context_cannot_be_reused_after_exact_source_or_candidate_changes(domain, part):
    row = sample(domain)
    context = bind_context(domain, row["target"], row["source_text"], formula_inputs(domain, row))
    if part == "source": row["source_text"] += " Changed."
    elif part == "candidate": context["candidate_sha256"] = "0" * 64
    elif part == "source_hash": context["source_sha256"] = "0" * 64
    else: context["proof_authority"] = True
    with pytest.raises(ValueError, match="context"):
        api.prepare_candidate_projection(domain, row["target"], row["source_text"], context=context)


def test_security_supplemental_source_ref_mismatch_is_rejected_even_with_rehashed_context():
    row = sample("security_ir")
    inputs = security_inputs(row)
    inputs["supplemental_inputs"][0]["document"]["sources"][0]["content_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        prepared("security_ir", row=row, context_inputs=inputs)


def test_empty_native_intent_routes_do_not_count_as_family_coverage():
    source = _intent(0)
    document = replace(source["document"], intent_kind=IntentKind.DECLARATIVE,
        statements=(replace(source["document"].statements[0], modality=IntentModality.ASSERTED),),
        actions=(), entry_action_ids=(), terminal_action_ids=())
    result = prepared("intent_ir", row=dict(target=document.to_dict(), source_text=source["source_text"]),
        families=["deontic", "program", "temporal"]).report
    assert result["candidate_valid"] and not result["all_required_families_supported"]
    assert all(item["status"] != "supported" and not item["projections"] for item in result["families"])


@pytest.mark.parametrize("family", ["first_order", "datalog", "horn_chc"])
def test_intent_subset_request_retains_native_semantic_dependencies(family):
    report = prepared("intent_ir", families=[family]).report
    assert report["requested_families"] == [family]
    if family == "first_order":
        # An obligation is reclassified into deontic, never an asserted fact.
        assert not report["all_required_families_supported"]
        assert family_index(report)[family]["status"] == "missing_context"
    else:
        assert report["all_required_families_supported"]
        assert family_index(report)[family]["status"] == "supported"
    assert not report["complete_target_semantics"]


@pytest.mark.parametrize("payload", [[], {"facts": []}, {"formulas": []}, {"rules": []},
    {"format": "tdfol", "payload": {"formulas": []}}])
def test_empty_supported_representation_shapes_are_explicitly_empty(payload):
    assert api._empty_projection({"payload": payload})


def test_simple_extra_formula_cannot_hide_an_uninterpreted_rule_in_same_family():
    row = sample("legal_ir")
    row["target"]["rules"][0]["conditions"] = ["opaque unexplained qualifier"]
    inputs = {"formula_inputs": [{"requirement_id": "DFOL", "formula": FORMULAS["DFOL"]}]}
    result = prepared("legal_ir", families=["deontic"], row=row, context_inputs=inputs)
    family = family_index(result.report)["deontic"]
    assert len(family["projections"]) == 2
    assert any(value["semantic_lowering_supported"] for value in family["native_lowering"])
    assert any(not value["semantic_lowering_supported"] for value in family["native_lowering"])
    assert family["status"] == "missing_context"
    assert not result.report["all_required_families_supported"]


@pytest.mark.parametrize("domain", DOMAINS)
def test_detached_report_native_report_and_source_input_copies_cannot_mutate_issued_state(domain):
    row = sample(domain)
    handle = prepared(domain, families=FORMULA_FAMILIES, row=row, context_inputs=formula_inputs(domain, row))
    before = handle.report
    detached = handle.report
    detached["proof_authority"] = True
    detached["families"].clear()
    native = handle.native_report
    native["projections"].clear()
    source = handle.source_inputs
    source["formula_inputs"].clear()
    source["source_text"] = "tampered local copy"
    assert handle.report == before
    assert handle.native_report["projections"]
    assert len(handle.source_inputs["formula_inputs"]) == 8
    assert handle.report["report_sha256"] == c.digest({key: value for key, value in before.items() if key != "report_sha256"})


@pytest.mark.parametrize("value", [None, {}, {"report": {"qualified": True}}, "saved-receipt.json"])
def test_saved_or_invented_values_are_not_live_preparation_handles(value, tmp_path):
    with pytest.raises(ValueError, match="prepared native"):
        api.check_candidate_projection(value, lake_executable="must-not-run", output_directory=tmp_path)
    assert not list(tmp_path.iterdir())


def test_unissued_correct_class_instance_is_rejected_before_backend(tmp_path):
    fake = api.PreparedCandidateProjection()
    with pytest.raises(ValueError, match="issued"):
        api.check_candidate_projection(fake, lake_executable="must-not-run", output_directory=tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("domain", DOMAINS)
def test_actual_lake_build_for_eight_declared_fragments(domain, tmp_path):
    executable = os.environ.get("IR384_TEST_LAKE_EXECUTABLE")
    if not executable:
        pytest.skip("Set IR384_TEST_LAKE_EXECUTABLE to opt into real native Lake integration")
    assert Path(executable).is_file()
    # The declarative Intent fixture has no source action requiring a separate
    # state model. The authored action fixture's missing workflow stays blocked
    # in the ordinary test above.
    row = declarative_intent_sample() if domain == "intent_ir" else sample(domain)
    handle = prepared(domain, families=FORMULA_FAMILIES, row=row, context_inputs=formula_inputs(domain, row))
    report = api.check_candidate_projection(handle, lake_executable=executable, output_directory=tmp_path / "actual-lake")
    assert report["lake_build_executed"]
    assert report["all_requested_native_checks_passed"]
    assert report["live_issued_handle_verified"] and not report["saved_receipt_is_live_authority"]
    assert all(family["native_checks_passed"] for family in report["families"])
    assert not report["proof_authority"] and not report["source_semantics_verified"]


def test_actual_partial_lake_build_does_not_hide_blocked_native_semantics(tmp_path):
    executable = os.environ.get("IR384_TEST_LAKE_EXECUTABLE")
    if not executable:
        pytest.skip("Set IR384_TEST_LAKE_EXECUTABLE to opt into real native Lake integration")
    row = sample("legal_ir")
    row["target"]["rules"][0]["conditions"] = ["opaque unexplained qualifier"]
    handle = prepared("legal_ir", row=row, families=["deontic"], context_inputs={
        "formula_inputs": [{"requirement_id": "DFOL", "formula": FORMULAS["DFOL"]}]})
    report = api.check_candidate_projection(handle, lake_executable=executable,
        output_directory=tmp_path / "actual-partial-lake")
    assert report["lake_build_executed"]
    assert not report["all_requested_native_checks_passed"]
    assert not report["all_required_families_supported"]
    assert not family_index(report)["deontic"]["native_checks_passed"]
    assert not report["proof_authority"]


def test_partial_auxiliary_state_has_distinct_coverage_from_selected_formula_families():
    row = sample("intent_ir")
    report = prepared("intent_ir", families=FORMULA_FAMILIES, row=row,
        context_inputs=formula_inputs("intent_ir", row)).report
    auxiliary = {item["family_id"]: item for item in report["auxiliary_family_coverage"]}
    assert set(auxiliary) == set(report["auxiliary_families"]) == {"program", "transition_system"}
    assert report["all_required_families_supported"]
    assert auxiliary["program"]["status"] == "supported"
    assert auxiliary["transition_system"]["status"] == "missing_context"
    assert not report["all_auxiliary_families_supported"]
    assert not report["all_requested_dependencies_supported"]
    assert report["native_check_scope"] == "syntax_and_types_only"
    assert not report["all_requested_native_checks_passed"]
    assert not report["complete_target_semantics"]


def test_guarded_effect_context_completes_the_actual_auxiliary_state_contract():
    from .test_distributed_384_projection_inputs import guarded_row
    row, context = guarded_row()
    report = prepared("intent_ir", families=["temporal"], row=row, context_inputs=context).report
    auxiliary = {item["family_id"]: item for item in report["auxiliary_family_coverage"]}
    assert set(auxiliary) == {"program", "transition_system"}
    assert all(item["status"] == "supported" and item["projections"] for item in auxiliary.values())
    assert report["all_required_families_supported"] and report["all_auxiliary_families_supported"]
    assert report["all_requested_dependencies_supported"]
    assert not report["all_requested_native_checks_passed"]
    assert report["native_check_scope"] == "syntax_and_types_only"
    assert not report["source_semantics_verified"]


def test_absent_auxiliary_families_neither_invent_targets_nor_bypass_missing_requested_family():
    row = sample("legal_ir")
    complete = prepared("legal_ir", families=["deontic"], row=row).report
    absent = prepared("legal_ir", families=["cryptographic_protocol"], row=row).report
    for report in (complete, absent):
        assert report["auxiliary_family_coverage"] == [] and report["all_auxiliary_families_supported"]
    assert complete["all_requested_dependencies_supported"]
    assert not absent["all_requested_dependencies_supported"]
    assert not absent["all_required_families_supported"]


def test_actual_native_syntax_success_does_not_complete_partial_auxiliary_state(tmp_path):
    executable = os.environ.get("IR384_TEST_LAKE_EXECUTABLE")
    java = os.environ.get("IR384_TEST_JAVA_EXECUTABLE")
    jar = os.environ.get("IR384_TEST_TLA2TOOLS_JAR")
    if not all((executable, java, jar)):
        pytest.skip("Set IR384_TEST_LAKE_EXECUTABLE, IR384_TEST_JAVA_EXECUTABLE and IR384_TEST_TLA2TOOLS_JAR for real syntax checks")
    row = sample("intent_ir")
    handle = prepared("intent_ir", families=FORMULA_FAMILIES, row=row,
        context_inputs=formula_inputs("intent_ir", row))
    report = api.check_candidate_projection(handle, lake_executable=executable,
        java_executable=java, tla2tools_jar=jar, output_directory=tmp_path / "actual-auxiliary-check")
    assert report["lake_build_executed"] and report["all_requested_native_checks_passed"]
    assert report["native_check_scope"] == "syntax_and_types_only"
    assert all(item["native_checks_passed"] for item in report["families"])
    assert report["all_required_families_supported"]
    assert not report["all_auxiliary_families_supported"]
    assert not report["all_requested_dependencies_supported"]
    assert not report["complete_target_semantics"] and not report["source_semantics_verified"]
