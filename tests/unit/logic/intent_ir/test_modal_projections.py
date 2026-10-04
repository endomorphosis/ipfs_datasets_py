"""Actual native syntax/operator checks for optional Intent modal projections."""
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize.modal_projections import project_modal_families
from ipfs_datasets_py.logic.intent_ir.formalize.projection_contracts import validate_projection
from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip import frame_to_intent_ir
from ipfs_datasets_py.logic.intent_ir.schema import IntentModality, StatementKind, IntentStatement, NodeGrounding


def document(modality="required"):
    return frame_to_intent_ir({"actor": "agent", "action": "read", "object": "cache", "modality": modality},
                              instruction="The agent is asked to read the cache.")


def families(doc, context=None):
    return {row["family_id"]: row for row in project_modal_families(doc, context)}


@pytest.mark.parametrize("modality,operator", [("required", "O"), ("permitted", "P"), ("prohibited", "F")])
def test_actual_native_deontic_parsers_preserve_force(modality, operator):
    doc = document(modality)
    reports = families(doc)
    for name in ("dcec", "tdfol"):
        report = reports[name]
        assert report["status"] == "projected"
        formula = report["representation"]["payload"]["formulas"][0]
        assert formula["source"].startswith(operator + "(")
        assert formula["ast"]["node_type"] == "DeonticFormula"
        assert formula["ast"]["operator"]["value"] == operator
        assert formula["native_ast_roundtrip_passed"]
        assert formula["free_variables"] == []
        assert report["validation"][0]["status"] == "passed"
        assert report["proof_authority"] is report["source_semantics_verified"] is False
        assert validate_projection(report, doc) == report


def test_intention_is_cognitive_not_knowledge_or_truth():
    reports = families(document("intended"))
    formula = reports["dcec"]["representation"]["payload"]["formulas"][0]
    assert formula["ast"]["node_type"] == "CognitiveFormula"
    assert formula["ast"]["operator"]["value"] == "I"
    assert formula["actor_binding_action_id"] == "action"
    assert reports["tdfol"]["status"] == "unsupported"
    assert "intention_agency" in reports["tdfol"]["unsupported"][0]["reason"]


def test_recommendation_never_becomes_obligation():
    reports = families(document("recommended"))
    for name in ("dcec", "tdfol"):
        assert reports[name]["status"] == "unsupported"
        assert reports[name]["validation"][0]["status"] == "not_run"
        assert reports[name]["representation"]["payload"]["formulas"] == []
        assert "recommendation" in reports[name]["unsupported"][0]["reason"]


def test_missing_and_ambiguous_actor_binding_abstains():
    doc = document("intended")
    absent = replace(doc, actions=(), entry_action_ids=(), terminal_action_ids=())
    assert families(absent)["dcec"]["status"] == "unsupported"
    ambiguous = replace(doc, actions=(doc.actions[0], replace(doc.actions[0], action_id="second")))
    assert families(ambiguous)["dcec"]["status"] == "unsupported"


def test_asserted_goal_is_not_an_achieved_fact():
    doc = document("intended")
    doc = replace(doc, statements=(replace(doc.statements[0], modality=IntentModality.ASSERTED),))
    formula = families(doc)["dcec"]["representation"]["payload"]["formulas"][0]
    assert formula["original_modality"] == "asserted"
    assert formula["effective_modality"] == "intended"
    assert formula["ast"]["node_type"] == "CognitiveFormula"


def test_native_constant_printer_adapter_and_tdfol_ground_constants():
    reports = families(document())
    dcec = reports["dcec"]["representation"]["payload"]["formulas"][0]
    assert "()" not in dcec["source"]
    assert dcec["native_ast_roundtrip_passed"]
    tdfol = reports["tdfol"]["representation"]["payload"]["formulas"][0]
    assert "entity:" in tdfol["source"]
    assert all(arg["node_type"] == "Constant" for arg in tdfol["ast"]["formula"]["arguments"])


def test_raw_symbols_are_inert_and_reversibly_bound():
    doc = document()
    statement = replace(doc.statements[0], predicate="read:cache", arguments=("agent", "cache; rm -rf /"))
    doc = replace(doc, statements=(statement,))
    reports = families(doc)
    for name in ("dcec", "tdfol"):
        payload = reports[name]["representation"]["payload"]
        assert "rm -rf" not in payload["formulas"][0]["source"]
        assert any(row["value"] == statement.predicate for row in payload["symbols"])
        assert any(row["value"] == statement.arguments[1] for row in payload["symbols"])


def test_intent_alone_never_asserts_an_event_happened():
    report = families(document())["event_calculus"]
    assert report["status"] == "unsupported"
    assert report["representation"]["payload"]["formulas"] == []
    assert report["validation"][0]["status"] == "not_run"


def test_explicit_occurrence_has_native_parser_and_source_evidence():
    doc = document()
    context = {"modal": {"event_occurrences": [{"action_id": "action", "time": 4, "evidence_ref": "source"}]}}
    report = families(doc, context)["event_calculus"]
    assert report["status"] == "partial"  # The original norm is still not an event.
    row = report["representation"]["payload"]["formulas"][0]
    assert row["source"].startswith("happens(")
    assert row["native_ast_roundtrip_passed"] is True
    assert row["evidence_verified"] is False
    assert "source" in row["source_node_ids"]
    validate_projection(report, doc)


def effect_document():
    doc = document()
    effect = IntentStatement(statement_id="updated", kind=StatementKind.EFFECT,
        modality=IntentModality.ASSERTED, normalized_text="cache updated", source_ref_ids=("source",),
        predicate="updated", arguments=("cache",), grounding=NodeGrounding.INFERRED)
    return replace(doc, statements=(*doc.statements, effect),
                   actions=(replace(doc.actions[0], effect_ids=("updated",)),))


@pytest.mark.parametrize("kind", ["initiates", "terminates"])
def test_explicit_effect_law_uses_bound_time_not_invented_instant(kind):
    doc = effect_document()
    context = {"modal": {"effect_bindings": [{"action_id": "action", "statement_id": "updated",
                                             "kind": kind, "evidence_ref": "source"}]}}
    report = families(doc, context)["event_calculus"]
    payload = report["representation"]["payload"]
    assert payload["formulas"][0]["source"].startswith("forall t:Time. " + kind + "(")
    assert payload["fluent_bindings"] == [{"statement_id": "updated", "predicate": "updated", "arguments": ["cache"]}]
    assert "happens(" not in report["representation"]["source"]


@pytest.mark.parametrize("row", [
    {"action_id": "action", "time": True, "evidence_ref": "source"},
    {"action_id": "action", "time": -1, "evidence_ref": "source"},
    {"action_id": "action", "time": 1, "evidence_ref": "missing"},
    {"action_id": "unknown", "time": 1, "evidence_ref": "source"},
])
def test_occurrence_rejects_missing_grounding_and_invalid_time(row):
    with pytest.raises(ValueError):
        families(document(), {"modal": {"event_occurrences": [row]}})


def test_effect_binding_cannot_skip_explicit_action_link():
    doc = effect_document()
    doc = replace(doc, actions=(replace(doc.actions[0], effect_ids=()),))
    with pytest.raises(ValueError, match="effect link"):
        families(doc, {"modal": {"effect_bindings": [{"action_id": "action", "statement_id": "updated",
                            "kind": "initiates", "evidence_ref": "source"}]}})


def test_empty_and_unknown_context_is_not_vacuous_success():
    with pytest.raises(ValueError, match="unknown modal"):
        families(document(), {"modal": {"pretend_proved": True}})
    assert families(document(), {"state": {}})["event_calculus"]["status"] == "unsupported"


@pytest.mark.parametrize("modality,norm", [("required", "O"), ("permitted", "P"), ("prohibited", "F")])
@pytest.mark.parametrize("operator,symbol", [("always", "□"), ("eventually", "◊"), ("next", "X")])
def test_explicit_temporal_norm_preserves_outer_scope_with_actual_native_parser(modality, norm, operator, symbol):
    doc = document(modality)
    context = {"modal": {"temporal_bindings": [{"statement_id": "goal", "operator": operator,
                                               "evidence_ref": "source"}]}}
    reports = families(doc, context)
    formula = reports["tdfol"]["representation"]["payload"]["formulas"][0]
    assert formula["source"].startswith(symbol + "(" + norm + "(")
    assert formula["ast"]["node_type"] == "TemporalFormula"
    assert formula["ast"]["operator"]["value"] == symbol
    assert formula["ast"]["formula"]["node_type"] == "DeonticFormula"
    assert formula["ast"]["formula"]["operator"]["value"] == norm
    assert formula["native_ast_roundtrip_passed"]
    assert formula["temporal_scope"]["placement"] == "outside_complete_modal_proposition"
    assert formula["temporal_scope"]["evidence_verified"] is False
    assert "source" in reports["tdfol"]["source_node_ids"]
    formula = reports["dcec"]["representation"]["payload"]["formulas"][0]
    assert formula["source"].startswith(operator + "(" + norm + "(")
    assert formula["ast"]["node_type"] == "TemporalFormula"
    assert formula["ast"]["operator"]["value"] == symbol
    assert formula["ast"]["formula"]["operator"]["value"] == norm
    assert formula["native_ast_roundtrip_passed"]
    assert reports["event_calculus"]["status"] == "unsupported"


@pytest.mark.parametrize("operator,symbol", [("always", "□"), ("eventually", "◊"), ("next", "X")])
def test_temporally_scoped_intention_retains_cognitive_operator(operator, symbol):
    context = {"modal": {"temporal_bindings": [{"statement_id": "goal", "operator": operator, "evidence_ref": "source"}]}}
    reports = families(document("intended"), context)
    formula = reports["dcec"]["representation"]["payload"]["formulas"][0]
    assert formula["ast"]["node_type"] == "TemporalFormula"
    assert formula["ast"]["operator"]["value"] == symbol
    assert formula["ast"]["formula"]["node_type"] == "CognitiveFormula"
    assert formula["ast"]["formula"]["operator"]["value"] == "I"
    assert formula["actor_binding_action_id"] == "action"
    assert formula["native_ast_roundtrip_passed"]
    assert reports["tdfol"]["status"] == "unsupported"


@pytest.mark.parametrize("binding", [
    {"statement_id": "missing", "operator": "always", "evidence_ref": "source"},
    {"statement_id": "goal", "operator": "always", "evidence_ref": "missing"},
    {"statement_id": "goal", "operator": "F", "evidence_ref": "source"},
    {"statement_id": "goal", "operator": [], "evidence_ref": "source"},
])
def test_temporal_scope_requires_unambiguous_operator_and_native_source_binding(binding):
    with pytest.raises(ValueError):
        families(document(), {"modal": {"temporal_bindings": [binding]}})


def test_duplicate_temporal_scope_does_not_invent_operator_order():
    with pytest.raises(ValueError, match="one explicit temporal"):
        families(document(), {"modal": {"temporal_bindings": [
            {"statement_id": "goal", "operator": "always", "evidence_ref": "source"},
            {"statement_id": "goal", "operator": "eventually", "evidence_ref": "source"}]}})


def test_no_temporal_context_preserves_existing_atemporal_reports():
    doc = document()
    assert families(doc) == families(doc, {"modal": {}})
    for family in ("dcec", "tdfol"):
        payload = families(doc)[family]["representation"]["payload"]
        assert "temporal_bindings" not in payload
        assert "temporal_scope" not in payload["formulas"][0]
