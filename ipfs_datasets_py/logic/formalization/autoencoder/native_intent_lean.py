"""Reviewed Intent operator/contract interpretations for the versioned Lake gate.

This helper emits definitions, never proofs of intent fulfillment. Field dumps,
unexecuted action facts and modality-bearing first-order views remain blocked.
The caller must replay the complete source report before using these emitters.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

from . import native_family_lean_emitters as old
from ...intent_ir.formalize import advisor
from ...intent_ir import schema

_SOURCE_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_MODAL = {"required": "O", "permitted": "P", "prohibited": "F"}
_ROUTES = {
    "intent-route/norms/v1": "deontic", "intent-route/facts/v1": "first_order",
    "intent-route/intentions/v1": "intention_agency",
    "intent-route/action-hoare/v1": "program", "intent-route/workflow-temporal/v1": "temporal",
    "intent-extended/transition_system/default/v1": "transition_system",
    "rich-intent/transition_system/default/v1": "transition_system",
    "intent-extended/datalog/default/v1": "datalog", "intent-extended/horn_chc/default/v1": "horn_chc",
}
require, string = old.require, old.string


def _guard():
    require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SOURCE_SHA,
        "Intent_Lean_producer_changed_after_import")
    from ....optimizers.logic_theorem_optimizer.autoencoder_schema_lake import _pin_imported_module
    for module in (sys.modules[__name__], old, advisor, schema):
        _pin_imported_module(module)


def _rows(value, label):
    require(type(value) is list and 1 <= len(value) <= 128, "bounded_nonempty_" + label)
    return value


def _closed(value, keys, label):
    require(type(value) is dict and set(value) == set(keys), "closed_" + label + "_required")


def _annotation(value):
    """Retain nonlogical provenance without treating confidence as truth."""
    return json.loads(json.dumps(value, allow_nan=False))


def _atom(body, *, at="t"):
    advisor._validate_statement_body(body, "Intent statement")
    require(type(body["predicate"]) is str and body["predicate"] and
        type(body["arguments"]) is list and len(body["arguments"]) <= 32,
        "explicit_bounded_predicate_arguments_required")
    args = ["(i.constant " + string(arg) + ")" for arg in body["arguments"]]
    return "i.atom " + string(body["predicate"]) + " [" + ", ".join(args) + "] " + at


def _actions(report):
    result = {}
    for row in report["projections"]:
        if row["projection_id"] != "intent-route/action-hoare/v1":
            continue
        for value in _rows(row["payload"], "action_contracts"):
            action = value["action"]
            advisor._validate_action(action, "Intent action")
            require(action["action_id"] not in result, "duplicate_Intent_action")
            result[action["action_id"]] = action
    return result


def _norms(payload, report):
    lines, retained, operators = [], [], []
    for index, value in enumerate(_rows(payload, "Intent_norms")):
        _closed(value, {"body", "kind", "operator"}, "Intent_norm")
        require(value["kind"] == "intention_deontic_formula", "native_Intent_norm_kind_required")
        body = value["body"]
        atom = "(fun t => " + _atom(body) + ")"
        require(body["statement_kind"] in ("goal", "assumption"), "Intent_statement_role_requires_separate_contract")
        expected = "intended" if body["statement_kind"] == "goal" and body["modality"] == "asserted" else body["modality"]
        require(value["operator"] == expected, "Intent_modal_operator_body_mismatch")
        if expected in _MODAL:
            operator = _MODAL[expected]
            expression = "i.modal " + string("deontic:" + operator) + " [] none " + atom
        elif expected == "intended":
            matches = [a for a in _actions(report).values() if a["verb"] == body["predicate"]
                and [a["actor"], *a["object_refs"]] == body["arguments"]]
            require(len(matches) == 1, "intention_requires_unique_exact_native_action_actor")
            operator = "I"
            expression = "i.cognitive \"I\" (i.agent " + string(matches[0]["actor"]) + ") " + atom
        else:
            raise old.UnsupportedNativeLean("recommendation_or_assertion_has_no_reviewed_Intent_norm_operator")
        lines.append(f"def norm_{index} {{Entity Agent : Type}} (i : Interpretation Entity Agent) : Nat → Prop := " + expression)
        retained.append(_annotation(value)); operators.append(operator)
    return "\n".join(lines), {"validator": "native_Intent_advisor_closed_body_and_operator_consistency",
        "operators": operators, "retained_native_records": retained,
        "assumptions": ["The predicate, ordered arguments and declared modal scope are interpreted exactly.",
            "Confidence, grounding, review status and source text are provenance, not probability or truth.",
            "No norm is asserted true, complied with, or executable; modality interpretations have no added axioms."]}


def _facts(payload):
    lines = []
    for index, value in enumerate(_rows(payload, "Intent_facts")):
        require(value.get("kind") == "typed_fact", "unexecuted_action_declaration_is_not_an_observed_FOL_fact")
        _closed(value, advisor._STATEMENT_BODY_FIELDS | {"kind"}, "Intent_fact")
        body = {key: value[key] for key in advisor._STATEMENT_BODY_FIELDS}
        require(body["modality"] == "asserted" and body["statement_kind"] == "assumption",
            "modal_goal_or_contract_cannot_be_flattened_to_FOL_truth")
        lines.append(f"def assumption_{index} {{Entity Agent : Type}} (i : Interpretation Entity Agent) (t : Nat) : Prop := " + _atom(body))
    return "\n".join(lines), {"validator": "native_Intent_asserted_assumption_predicate_fragment",
        "operators": ["ordered_ground_predicate"], "retained_native_records": _annotation(payload),
        "assumptions": ["These are supplied assumption formulas; the Lean definitions do not assert their truth.",
            "Modal goals and action declarations are explicitly excluded from this first-order fragment."]}


def _body_from_record(value):
    advisor._validate_statement_record(value, "Intent action predicate")
    require(value["modality"] == "asserted", "modal_action_condition_requires_explicit_state_semantics")
    return {"arguments": value["arguments"], "confidence": value["confidence"],
        "grounding": value["grounding"], "modality": value["modality"], "predicate": value["predicate"],
        "review_status": value["review_status"], "statement_kind": value["kind"], "text": value["normalized_text"]}


def _hoare(payload):
    lines = ["structure IntentActionInterpretation (World Entity : Type) where",
        "  constant : String → Entity", "  atom : String → List Entity → World → Prop",
        "  step : String → Entity → String → List Entity → World → World → Prop"]
    meaningful_postconditions = False
    for index, value in enumerate(_rows(payload, "Intent_Hoare_contracts")):
        _closed(value, {"kind", "action", "precondition", "postcondition", "effects", "verification"}, "Intent_Hoare")
        require(value["kind"] == "hoare_action_contract", "Intent_Hoare_kind_required")
        action = value["action"]
        advisor._validate_action(action, "Intent Hoare action")
        require(not any(action[key] for key in ("tool_refs", "input_refs", "output_refs")),
            "tool_or_IO_contract_requires_explicit_operational_model")
        require(not value["verification"] and not action["verification_ids"],
            "verification_claims_require_observation_semantics")
        require(value["effects"] == value["postcondition"], "action_effect_postcondition_mismatch")
        for name, id_key, kinds in (("precondition", "precondition_ids", {"precondition", "assumption"}),
                ("postcondition", "effect_ids", {"effect", "postcondition"})):
            records = value[name]
            require(type(records) is list and len(records) <= 64, "bounded_action_predicates_required")
            require([row["statement_id"] for row in records] == action[id_key] and
                len({row["statement_id"] for row in records}) == len(records), "closed_ordered_action_predicate_join_required")
            for record in records:
                _body_from_record(record)
                require(record["kind"] in kinds, "action_predicate_role_mismatch")
        pre = [_atom(_body_from_record(v), at="s") for v in value["precondition"]]
        post = [_atom(_body_from_record(v), at="t") for v in value["postcondition"]]
        meaningful_postconditions = meaningful_postconditions or bool(post)
        pre = " ∧ ".join("(" + p + ")" for p in pre) or "True"
        post = " ∧ ".join("(" + p + ")" for p in post) or "True"
        objects = ", ".join("(i.constant " + string(obj) + ")" for obj in action["object_refs"])
        step = "i.step " + string(action["action_id"]) + " (i.constant " + string(action["actor"]) + ") " + string(action["verb"]) + " [" + objects + "] s t"
        lines.append(f"def actionContract_{index} {{World Entity : Type}} (i : IntentActionInterpretation World Entity) : Prop :=\n"
            + "  ∀ s t, (" + pre + ") → (" + step + ") → (" + post + ")")
    return "\n".join(lines), {"validator": "native_Intent_action_and_complete_pre_post_reference_validation",
        "operators": ["universal_partial_correctness", "ordered_ground_predicates", "action_relation"],
        "capability_floor_eligible": meaningful_postconditions,
        "capability_floor_reason": "explicit_postcondition_contract" if meaningful_postconditions else "vacuous_contract_without_meaningful_postcondition",
        "retained_native_records": _annotation(payload),
        "assumptions": ["The supplied transition relation is a parameter, not a program inferred from the action verb.",
            "This is a partial-correctness contract, with no termination, execution, mutation-frame, or compliance proof.",
            "Empty postconditions are explicitly True; verification, tools and I/O semantics stay unsupported."]}


def _linear_native(payload):
    """Interpret the exact native default linear pc model, including self-loop."""
    from ...software_verification.transitions import StateTransitionIR
    _closed(payload, {"context", "format", "node_map", "payload", "source"}, "Intent_state_wrapper")
    require(payload["format"] == "StateTransitionIR@1" and payload["source"] == "native_intent_ir",
        "native_default_Intent_state_wrapper_required")
    context = payload["context"]
    _closed(context, {"abstraction", "max_steps"}, "Intent_linear_state_context")
    require(context["abstraction"] == "abstract_intent_control_flow" and type(context["max_steps"]) is int
        and 1 <= context["max_steps"] <= 256, "bounded_default_linear_Intent_context_required")
    native = StateTransitionIR.from_dict(payload["payload"])
    require(native.to_dict() == payload["payload"], "exact_native_Intent_state_roundtrip_required")
    require(native.schema.metadata.to_dict() == {"abstraction": "abstract_intent_control_flow"},
        "Intent_schema_annotations_not_lowered")
    require(all(not variable.attributes.to_dict() and variable.element_type_kind is None
        for variable in native.schema.variables), "Intent_variable_annotations_not_lowered")
    require(all(not predicate.attributes.to_dict() for predicate in native.predicates),
        "Intent_predicate_annotations_not_lowered")
    require(all(not transition.attributes.to_dict() for transition in native.transitions),
        "Intent_transition_annotations_not_lowered")
    mapping = _rows(payload["node_map"], "linear_Intent_positions")
    require(len(mapping) <= min(64, context["max_steps"]), "Intent_positions_exceed_declared_step_budget")
    expected_vars = native.schema.variables
    require(len(expected_vars) == 1 and expected_vars[0].variable_id == "var:pc" and expected_vars[0].name == "pc"
        and expected_vars[0].type_kind.value == "enumeration", "default_Intent_pc_schema_required")
    positions = ["position_" + str(i) for i in range(len(mapping))] + ["done"]
    require(list(expected_vars[0].domain_bound.members) == positions, "Intent_position_domain_differs")
    meta = native.metadata.to_dict()
    _closed(meta, {"abstraction", "intent_document_id", "intent_ir_sha256", "position_map", "max_steps", "code_effects_modeled", "normative_compliance_modeled"}, "Intent_state_metadata")
    require(meta["abstraction"] == context["abstraction"] and meta["max_steps"] == context["max_steps"]
        and meta["position_map"] == mapping and meta["code_effects_modeled"] is False
        and meta["normative_compliance_modeled"] is False, "Intent_native_state_scope_differs")
    actions = {a.action_id: a for a in native.actions}
    preds = {p.predicate_id: p for p in native.predicates}
    expected_actions = {"action:done"} | {"action:abstract:" + str(i) for i in range(len(mapping))}
    require(set(actions) == expected_actions, "Intent_native_actions_differ")
    ids = []
    for index, value in enumerate(mapping):
        _closed(value, {"state_action_id", "intent_action_id", "from_position", "to_position"}, "Intent_position_map")
        key = "action:abstract:" + str(index)
        require(value["state_action_id"] == key and value["from_position"] == positions[index]
            and value["to_position"] == positions[index + 1], "Intent_position_map_chain_differs")
        require(type(value["intent_action_id"]) is str and value["intent_action_id"] and value["intent_action_id"] not in ids,
            "unique_Intent_action_origins_required")
        ids.append(value["intent_action_id"])
        action = actions[key]
        require(action.attributes.to_dict() == {"abstract_event_only": True, "intent_action_id": value["intent_action_id"]}
            and not action.enables_stutter, "Intent_action_attributes_not_lowered")
        require(preds[action.guard_predicate_id].expression.to_dict() == {"var:pc": positions[index]}
            and preds[action.next_predicate_id].expression.to_dict() == {"var:pc": positions[index + 1]},
            "Intent_pc_step_differs_from_origin_mapping")
    done = actions["action:done"]
    require(done.enables_stutter and done.attributes.to_dict() == {"abstract_event_only": True,
        "origin": "adapter_generated_terminal_self_loop"}, "explicit_native_terminal_self_loop_required")
    guard, nxt = preds[done.guard_predicate_id], preds[done.next_predicate_id]
    require(guard.expression.to_dict() == nxt.expression.to_dict() == {"var:pc": "done"}, "terminal_loop_must_preserve_pc")
    # The native equality-map terminal action already includes (s,s) whenever
    # its guard holds. Prove that redundancy below before using the old exact
    # read/write/equality-map emitter on the equivalent flag-free model.
    normalized = replace(native, actions=tuple(replace(a, enables_stutter=False) if a.action_id == done.action_id else a
        for a in native.actions), document_id="")
    source, details = old.state_document(normalized.to_dict())
    action_index = next(i for i,a in enumerate(normalized.actions) if a.action_id == done.action_id)
    guard_index = next(i for i,p in enumerate(normalized.predicates) if p.predicate_id == guard.predicate_id)
    next_index = next(i for i,p in enumerate(normalized.predicates) if p.predicate_id == nxt.predicate_id)
    source += f"\nexample (s : State) (h : predicate_{guard_index} s) : action_{action_index} s s := by\n  simpa [action_{action_index}, predicate_{guard_index}, predicate_{next_index}] using And.intro h h\n"
    source += "def declaredMaxSteps : Nat := " + str(context["max_steps"]) + "\n"
    source += "def boundedControlRun (trace : Nat → State) (labels : Nat → String) : Prop :=\n  initial (trace 0) ∧ ∀ k, k < declaredMaxSteps → next (labels k) (trace k) (trace (k + 1))\n"
    source += "def intentActionOrigins : List (String × String) := [" + ", ".join("(" + string(v["state_action_id"]) + ", " + string(v["intent_action_id"]) + ")" for v in mapping) + "]\n"
    details.update(validator="native_StateTransitionIR_exact_linear_pc_and_terminal_self_loop",
        retained_native_context=_annotation(payload), operators=[*details["operators"], "terminal_self_loop", "bounded_control_trace"],
        assumptions=[*details["assumptions"], "The terminal local stutter flag is redundant with its equality-map action; a Lean example checks that fact.",
            "The separate bounded run uses the declared step budget. No eventual completion, code execution or normative compliance is inferred."])
    return source, details


def _workflow(payload, report):
    rows = _rows(payload, "Intent_workflow")
    boundaries = [v for v in rows if v.get("kind") == "workflow_boundary"]
    require(len(boundaries) == 1, "one_native_workflow_boundary_required")
    boundary = boundaries[0]
    _closed(boundary, {"kind", "entry_action_ids", "terminal_action_ids"}, "Intent_boundary")
    require(len(boundary["entry_action_ids"]) == len(boundary["terminal_action_ids"]) == 1, "single_linear_boundary_required")
    candidates = [r for r in report["projections"] if r["logic_family"] == "transition_system"
        and type(r["payload"]) is dict and r["payload"].get("format") == "StateTransitionIR@1"]
    require(len(candidates) == 1, "workflow_requires_unique_exact_native_linear_state_projection")
    source, details = _linear_native(candidates[0]["payload"])
    mapping = candidates[0]["payload"]["node_map"]
    ordered = [v["intent_action_id"] for v in mapping]
    require(ordered[0] == boundary["entry_action_ids"][0] and ordered[-1] == boundary["terminal_action_ids"][0],
        "workflow_boundaries_differ_from_native_state")
    edges = []
    for value in rows:
        if value is boundary: continue
        _closed(value, {"edge", "guard", "kind", "operator"}, "Intent_workflow_edge")
        require(value["kind"] == "workflow_temporal_transition" and value["operator"] == "next"
            and value["guard"] is None, "unguarded_NEXT_workflow_only")
        edge = value["edge"]
        advisor._validate_edge(edge, "Intent workflow edge")
        require(edge["kind"] == "next" and not edge["guard_statement_id"], "native_edge_operator_mismatch")
        edges.append((edge["source_action_id"], edge["target_action_id"]))
    require(len(edges) == len(set(edges)) and set(edges) == set(zip(ordered, ordered[1:])),
        "workflow_edges_differ_from_exact_native_linear_chain")
    source += "def completeDeclaredActionSequence (labels : List String) : Prop := labels = [" + ", ".join(string(x) for x in ordered) + "]\n"
    details.update(validator="native_workflow_boundary_edges_join_exact_linear_StateTransitionIR",
        retained_workflow_records=_annotation(payload), assumptions=[*details["assumptions"],
            "The finite declared sequence is a specification, not an observed trace or an eventual-completion theorem."])
    return source, details


def emit_projection(row, *, report=None):
    """Dispatch only owned Intent views; the outer gate must replay sources."""
    if type(row) is not dict or row.get("projection_id") not in _ROUTES:
        raise NotImplementedError
    _guard()
    require(type(report) is dict and report.get("domain_id") == "intent_ir", "same_domain_Intent_report_required")
    require(row.get("logic_family") == _ROUTES[row["projection_id"]] and
        row.get("source_digest") == report.get("source_digest") and
        [value for value in report["projections"] if value["projection_id"] == row["projection_id"]] == [row],
        "exact_Intent_projection_report_binding_required")
    identity, payload = row["projection_id"], row["payload"]
    if identity.endswith(("/norms/v1", "/intentions/v1")): result = _norms(payload, report)
    elif identity.endswith("/facts/v1"): result = _facts(payload)
    elif identity.endswith("/action-hoare/v1"): result = _hoare(payload)
    elif identity.endswith("/workflow-temporal/v1"): result = _workflow(payload, report)
    elif row["logic_family"] == "transition_system": result = _linear_native(payload)
    else: raise old.UnsupportedNativeLean("reified_Intent_declaration_data_is_not_domain_Datalog_or_CHC_semantics")
    _guard()
    return result


__all__ = ["emit_projection"]
