"""Native parsed UI declarations retain limited, explicitly supplied meaning."""
from copy import deepcopy
from dataclasses import fields
import hashlib

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import ui_source_contract_384_v2 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v7 as training
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v5 as lake
from ipfs_datasets_py.logic.ui_ux_ir.schema import (
    UIComponent, UIIRDocument, UISourceRef, UITerminalOutcome, TerminalOutcomeKind,
    UIState, UIEvent, UITransition, EventKind,
)

SOURCE = "Present the interactive submit button with restricted privacy."


def component(**fields):
    return {"kind": "ui_component", "document": {"component_id": "submit", "role": "button",
        "privacy_sensitivity": "restricted", "presentation_classification": "interactive", **fields}}


def document():
    ref = UISourceRef(ref_id="source", source_uri="fixture://authored-ui", source_id="authored-ui",
        source_revision="v1", content_sha256=hashlib.sha256(SOURCE.encode()).hexdigest())
    node = UIComponent(component_id="submit", role="button", source_ref_ids=("source",),
        privacy_sensitivity="restricted", presentation_classification="interactive")
    outcome = UITerminalOutcome(outcome_id="done", kind=TerminalOutcomeKind.SUCCESS,
                               source_ref_ids=("source",))
    return {"kind": "document", "document": UIIRDocument(document_id="ui", title="Authored UI",
        sources=(ref,), components=(node,), entry_components=("submit",), terminal_outcomes=(outcome,)).to_dict()}


def prepare(target=None, **kwargs):
    return subject.prepare_family_targets(SOURCE, component() if target is None else target, **kwargs)


def test_actual_ground_native_parser_has_four_declarations_and_no_new_authority():
    target = component()
    before = deepcopy(target)
    prepared = prepare(target)
    audit, report = prepared["audit"], prepared["report"]
    assert target == before and audit["candidate"] == target
    assert audit["declaration_count"] == 4
    assert audit["native_formula"]["payload"]["operator_counts"] == {
        "deontic": 0, "temporal": 0, "quantifier": 0, "predicate": 4}
    assert audit["ground_structure"] == {"predicates": 4, "conjunctions": 3,
        "distinct_constants": 4, "free_variables": 0, "quantifiers": 0, "modal_operators": 0}
    assert {row["predicate"] for row in audit["declarations"]} == {
        "UIComponent", "UIRole", "UIPrivacy", "UIPresentation"}
    assert audit["available_families"] == ["first_order", "frame_logic"]
    assert len(report["requested_families"]) == 40
    assert len(audit["missing_requested_families"]) == 38
    assert report["all_requested_families_available"] is False
    assert audit["native_defaults_promoted"] is False
    assert all(audit[name] is False for name in subject.FALSE)
    training.validate_family_training_report_v7(report, **prepared["source_inputs"])
    assert subject.validate_prepared(prepared, SOURCE, target)
    native = lake.prepare_native_family_lean(report, source_inputs=prepared["source_inputs"])
    assert len(native["per_projection"]) == 2
    assert all(row["parser_status"] == "passed" for row in native["per_projection"])
    assert "def formula" in native["lean_source"] and "def frame_0" in native["lean_source"]
    assert native["backend_executed"] is False  # Preparation is not a Lake build.


@pytest.mark.parametrize("omit", ["privacy_sensitivity", "presentation_classification", "both"])
@pytest.mark.parametrize("build", [component, document])
def test_absent_loader_defaults_do_not_gain_facts(omit, build):
    target = build()
    row = target["document"] if build is component else target["document"]["components"][0]
    omitted = set(subject._CLASSIFICATIONS) if omit == "both" else {omit}
    for key in omitted:
        row.pop(key)
    audit = prepare(target)["audit"]
    assert audit["declaration_count"] == 4 - len(omitted)
    assert not ({item["source_field"] for item in audit["declarations"]} & omitted)
    for item in audit["field_accounting"]["component_fields"]:
        if item["path"].rsplit("/", 1)[-1] in omitted:
            assert item["disposition"] == "absent_not_projected"
            assert item["represented_families"] == [] and item["supplied"] is False


def test_identity_collisions_are_lossless_typed_symbols_not_sanitized_strings():
    left = prepare(component(component_id="button"))["audit"]
    names = {(row["category"], row["value"]): row["symbol"] for row in left["symbol_table"]}
    assert names[("component", "button")] != names[("role", "button")]
    for identity in ("ui:submit", "ui-submit", "ui_submit"):
        audit = prepare(component(component_id=identity))["audit"]
        assert any(row["category"] == "component" and row["value"] == identity
                   for row in audit["symbol_table"])
        assert identity not in audit["native_formula"]["payload"]["formula"]
        assert audit["native_formula"]["payload"]["operator_counts"]["predicate"] == 4


def test_native_training_atoms_retain_value_identity_across_candidates():
    original = prepare()["audit"]
    changed = prepare(component(role="link", privacy_sensitivity="high", presentation_classification="static"))["audit"]
    assert original["native_formula"]["payload"]["native_ast"] != changed["native_formula"]["payload"]["native_ast"]
    assert original["native_formula"]["payload"]["formula"] != changed["native_formula"]["payload"]["formula"]
    old_symbols = {(row["category"], row["value"]): row["symbol"] for row in original["symbol_table"]}
    changed_symbols = {(row["category"], row["value"]): row["symbol"] for row in changed["symbol_table"]}
    assert old_symbols[("component", "submit")] == changed_symbols[("component", "submit")]
    other = prepare(component(component_id="other"))["audit"]
    assert old_symbols[("privacy", "restricted")] == next(row["symbol"] for row in other["symbol_table"]
        if row["category"] == "privacy")
    for audit in (original, changed, other):
        for row in audit["symbol_table"]:
            namespace, hexadecimal = row["symbol"].split(":v", 1)
            assert namespace == "ui_" + row["category"]
            assert bytes.fromhex(hexadecimal).decode("utf-8") == row["value"]


@pytest.mark.parametrize("change", [{"role": "link"}, {"privacy_sensitivity": "high"},
    {"presentation_classification": "static"}])
def test_each_explicit_critical_value_changes_actual_formula_loss_atoms(change):
    original = prepare()["audit"]["native_formula"]["payload"]
    changed = prepare(component(**change))["audit"]["native_formula"]["payload"]
    assert original["formula"] != changed["formula"]
    assert original["native_ast"] != changed["native_ast"]


def test_existing_frame_target_is_preserved_exactly():
    prepared = prepare()
    source = {key: value for key, value in prepared["source_inputs"].items() if key != "formula_inputs"}
    before = training.prepare_family_training_targets_v7("ui_ux_ir", **source)
    old = {row["projection_id"]: row["payload"] for row in before["projections"]}
    new = {row["projection_id"]: row["payload"] for row in prepared["report"]["projections"]}
    assert old and all(new[key] == value for key, value in old.items())


@pytest.mark.parametrize("fields", [
    {"component_id": 'submit) or Injected(x)'}, {"privacy_sensitivity": "interactive"},
    {"presentation_classification": "restricted"}, {"ignored_policy": "must not disappear"},
    {"role": "button); axiom unsafe"},
])
def test_injection_unknown_fields_and_crossfield_tokens_refuse(fields):
    result = subject.qualify_source_candidate(SOURCE, component(**fields))
    assert result["status"] == "invalid_or_missing_context"
    assert not result["projections"] and result["admitted"] is False


def test_full_wire_fields_are_retained_but_behavior_is_not_fabricated():
    target = document()
    raw = target["document"]
    # These are transition declarations, not actual observed events. Priority
    # is explicitly supplied, so a future state adapter must also account for it.
    raw["states"] = [UIState("after").to_dict(), UIState("before").to_dict()]
    raw["events"] = [UIEvent("submit-event", EventKind.INPUT).to_dict()]
    raw["transitions"] = [UITransition("edge", "before", "after", "submit-event", priority=7).to_dict()]
    raw["initial_states"] = ["before"]
    prepared = prepare(target)
    audit = prepared["audit"]
    assert audit["candidate"] == target
    coverage = {row["path"].rsplit("/", 1)[-1]: row for row in audit["field_accounting"]["document_fields"]}
    assert set(coverage) == {field.name for field in fields(UIIRDocument)}
    for name in ("states", "events", "transitions", "initial_states"):
        assert coverage[name]["supplied"] and coverage[name]["disposition"] == "retained_uninterpreted"
    assert prepared["source_inputs"]["document"].behavior_model is None
    assert not prepared["source_inputs"]["document"].events
    assert not prepared["source_inputs"]["document"].action_bindings
    assert set(audit["available_families"]) == {"frame_logic", "first_order"}
    assert {"event_calculus", "transition_system", "dcec", "tdfol", "temporal"} <= set(audit["missing_requested_families"])


def test_requested_subset_is_explicit_and_does_not_relabel_missing_work():
    prepared = prepare(requested_families=("frame_logic", "dcec"))
    audit, report = prepared["audit"], prepared["report"]
    assert audit["available_families"] == ["frame_logic"]
    assert audit["missing_requested_families"] == ["dcec"]
    assert {row["logic_family"] for row in report["projections"]} == {"frame_logic"}
    privacy = next(row for row in audit["field_accounting"]["component_fields"]
                   if row["path"].endswith("/privacy_sensitivity"))
    assert privacy["represented_families"] == []
    assert report["all_requested_families_available"] is False


def test_disagreeing_source_does_not_become_verified_or_rewrite_candidate():
    original = prepare()
    changed = subject.prepare_family_targets("Delete the submit control entirely.", component())
    assert original["audit"]["candidate_sha256"] == changed["audit"]["candidate_sha256"]
    assert original["report"]["source_digest"] != changed["report"]["source_digest"]
    assert changed["audit"]["source_fidelity_check_required"] is True
    assert changed["audit"]["source_semantics_verified"] is False
    assert changed["audit"]["candidate_rewritten"] is False


def test_uninterpreted_field_changes_exact_candidate_and_report_binding():
    original = prepare()
    changed = prepare(component(purpose="Important purpose retained without an inferred predicate."))
    assert original["audit"]["native_formula"]["payload"]["formula"] == changed["audit"]["native_formula"]["payload"]["formula"]
    assert original["audit"]["candidate_sha256"] != changed["audit"]["candidate_sha256"]
    assert original["report"]["source_digest"] != changed["report"]["source_digest"]
    with pytest.raises(ValueError, match="replay differs"):
        subject.validate_prepared(original, SOURCE, changed["audit"]["candidate"])


def test_symbol_table_and_constant_ast_tampering_refuse():
    prepared = prepare()
    prepared["audit"]["symbol_table"][0]["value"] = "invented"
    with pytest.raises(ValueError, match="replay differs"):
        subject.validate_prepared(prepared, SOURCE, component())
    prepared = prepare()
    payload = deepcopy(prepared["audit"]["native_formula"]["payload"])
    from ipfs_datasets_py.logic.formalization.autoencoder.native_formula_evidence import _walk
    constant = next(node for node in _walk(payload["native_ast"]) if node.get("node_type") == "Constant")
    constant["node_type"] = "Variable"
    with pytest.raises(ValueError, match="ground UI declarations"):
        subject._check_ground_ast(payload, prepared["audit"]["declarations"], prepared["audit"]["symbol_table"])


def test_dangling_fragment_keeps_missing_context_and_bounds_never_truncate():
    result = subject.qualify_source_candidate(SOURCE, component(parent_id="absent"))
    assert result["status"] == "invalid_or_missing_context" and result["projections"] == []
    with pytest.raises(ValueError, match="no truncation"):
        subject._declarations([component()["document"]] * 65)
