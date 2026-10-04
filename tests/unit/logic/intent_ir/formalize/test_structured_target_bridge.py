"""Native retention never turns conditional norms into unconditional ones."""
from copy import deepcopy
from hashlib import sha256

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import structured_target_bridge as sut
from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip import intent_ir_to_frame
from ipfs_datasets_py.logic.intent_ir.schema import ControlEdgeKind, IntentModality, StatementKind


def target(kind="action", modality="required"):
    actions = [{"actor": "agent", "action": "inspect", "object": "cache", "modality": modality}]
    if kind == "sequence":
        actions.append({**actions[0], "action": "update"})
    return {"kind": kind, "actions": actions,
            "condition": "the cache exists" if kind == "conditional" else None}


def test_single_action_remains_compatible_and_preserves_exact_source():
    value = target()
    instruction = "  Agent must inspect cache.\n"
    doc = sut.build_structured_target_ir(value, instruction)
    assert intent_ir_to_frame(doc) == value["actions"][0]
    assert doc.sources[0].content_sha256 == sha256(instruction.encode()).hexdigest()
    assert doc.sources[0].span.start_char == 0
    assert doc.sources[0].span.end_char == len(instruction)
    report = sut.qualify_structured_target(value, instruction)
    assert report["training_supported"] is True
    assert report["unsupported"] == []
    assert report["learned_inference_executed"] is False
    assert all(report[key] is False for key in ("proof_authority", "execution_authority",
        "completion_authority", "omission_authority", "source_semantics_verified"))


def test_sequence_has_explicit_order_without_effects_or_existing_codec_admission():
    value = target("sequence")
    report = sut.qualify_structured_target(value, "Agent must inspect cache, then update cache.")
    doc = sut.build_structured_target_ir(value, "Agent must inspect cache, then update cache.")
    assert [action.verb for action in doc.actions] == ["inspect", "update"]
    assert len(doc.control_edges) == 1
    edge = doc.control_edges[0]
    assert (edge.kind, edge.source_action_id, edge.target_action_id) == (ControlEdgeKind.NEXT, "action", "action_2")
    assert doc.entry_action_ids == ("action",)
    assert doc.terminal_action_ids == ("action_2",)
    assert all(not action.precondition_ids and not action.effect_ids for action in doc.actions)
    assert report["training_supported"] is False
    assert report["unsupported"] == ["sequence_target_requires_separate_learned_codec"]
    assert report["candidate_ast"]["op"] == "sequence"
    assert report["projections"]["native_targets"]["ready_for_training"] is True


@pytest.mark.parametrize("kind", ["action", "sequence"])
def test_native_case_sensitive_object_is_preserved_without_codec_downcast(kind):
    value = target(kind)
    value["actions"][0]["object"] = "CSS custom property fallbacks"
    report = sut.qualify_structured_target(value, "Verify CSS custom property fallbacks.")
    doc = sut.build_structured_target_ir(value, "Verify CSS custom property fallbacks.")
    assert doc.actions[0].object_refs == ("CSS custom property fallbacks",)
    assert doc.statements[0].arguments == ("agent", "CSS custom property fallbacks")
    assert doc.statements[0].normalized_text == "agent must inspect CSS custom property fallbacks."
    assert report["target"]["actions"][0]["object"] == "CSS custom property fallbacks"
    assert report["training_supported"] is False
    assert "case_sensitive_object_outside_roundtrip_codec" in report["unsupported"]


@pytest.mark.parametrize("modality", ["required", "prohibited", "permitted", "recommended", "intended"])
def test_conditional_has_only_opaque_goal_and_never_unconditional_modal_formula(modality):
    value = target("conditional", modality)
    instruction = "If the cache exists, agent must inspect cache."
    report = sut.qualify_structured_target(value, instruction)
    doc = sut.build_structured_target_ir(value, instruction)
    assert len(doc.statements) == 1
    goal = doc.statements[0]
    assert goal.kind is StatementKind.GOAL
    assert goal.modality is IntentModality.INTENDED
    assert goal.normalized_text == instruction and goal.predicate == "" and goal.arguments == ()
    assert doc.actions[0].precondition_ids == ()
    assert report["candidate_ast"]["op"] == "implies"
    assert report["candidate_ast"]["antecedent"] == {"op": "opaque_condition", "text": value["condition"]}
    assert report["candidate_ast"]["consequent"]["frame"]["modality"] == modality
    assert report["training_supported"] is False
    assert "conditional_modality_relation" in report["unsupported"]
    assert report["projections"]["native_targets"]["ready_for_training"] is False
    for row in report["projections"]["projections"]:
        if row["family_id"] in {"dcec", "tdfol"}:
            assert row["representation"]["payload"]["formulas"] == []
            assert row["status"] == "unsupported"


@pytest.mark.parametrize("edit", [
    lambda value: value.update(extra=True),
    lambda value: value.update(kind="parallel"),
    lambda value: value.update(actions=[]),
    lambda value: value.update(actions=value["actions"] * 2),
    lambda value: value.update(condition="hidden guard"),
    lambda value: value["actions"][0].update(modality="asserted"),
    lambda value: value["actions"][0].update(effect="changed cache"),
])
def test_closed_target_rejects_dropped_or_unsupported_fields(edit):
    value = target()
    edit(value)
    with pytest.raises(ValueError):
        sut.validate_structured_target(value)


@pytest.mark.parametrize("guard", [None, "", " leading", "double  space", "line\nbreak", "x" * 257, "a " * 32 + "a"])
def test_condition_is_bounded_exact_normalized_opaque_text(guard):
    value = target("conditional")
    value["condition"] = guard
    with pytest.raises(ValueError):
        sut.validate_structured_target(value)


def test_opaque_guard_symbols_remain_data_without_native_predicates():
    value = target("conditional")
    value["condition"] = 'cache.ready() == True and "Ω" in flags'
    report = sut.qualify_structured_target(value, "If that opaque condition holds, inspect the cache.")
    assert report["candidate_ast"]["antecedent"]["text"] == value["condition"]
    assert report["native_intent_ir"]["statements"][0]["predicate"] == ""
    assert report["code_state_bound"] is report["state_effects_inferred"] is False


def test_replay_rejects_tampered_target_source_and_admission():
    value = target("conditional")
    instruction = "If the cache exists, agent must inspect cache."
    report = sut.qualify_structured_target(value, instruction)
    assert sut.validate_structured_target_report(report, value, instruction) is report
    tampered = deepcopy(report)
    tampered["training_supported"] = True
    with pytest.raises(ValueError, match="source replay"):
        sut.validate_structured_target_report(tampered, value, instruction)
    with pytest.raises(ValueError, match="source replay"):
        sut.validate_structured_target_report(report, value, instruction + " ")
    changed = deepcopy(value)
    changed["actions"][0]["modality"] = "permitted"
    with pytest.raises(ValueError, match="source replay"):
        sut.validate_structured_target_report(report, changed, instruction)
    assert sut.__name__ in report["producer_pins"]
