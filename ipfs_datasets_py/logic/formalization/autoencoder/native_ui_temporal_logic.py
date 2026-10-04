"""Actual UI state temporal interpretations over a declared EC prefix.

Known states come from exact replay of the signed discrete EC declaration. The
unobserved future remains an arbitrary extension over the declared state type.
Native temporal operators keep their unbounded Nat semantics; O/P/F are distinct
state-norm interpretation parameters, not inferred actor duties or proven facts.
"""
from copy import deepcopy
import importlib
import json

from . import family_training as core
from . import native_family_lean_emitters as lean
from . import native_formula_evidence as formulas
from . import native_ui_bounded_event_calculus as events
from . import ui_declared_source_fidelity as source_wire

SCHEMA = "native-ui-state-temporal-logic/v1"
DESCRIPTOR_SCHEMA = "ui-state-temporal-declaration/v1"
REPORT_SCHEMA = "ui-declared-logic-family-targets/v1"
ROUTES = {
    "TFOL": ("ui_ux_ir/declared_state_logic/TFOL/v1", "temporal", "explicit_ui_state_temporal/v1"),
    "TDFOL": ("ui_ux_ir/declared_state_logic/TDFOL/v1", "tdfol", "explicit_ui_state_deontic_temporal/v1"),
}
PROJECTION_IDS = {key: route[0] for key, route in ROUTES.items()}
PROFILES = {key: route[2] for key, route in ROUTES.items()}
TIME_SEMANTICS = {
    "index_domain": "discrete_nat_logical_steps",
    "step_zero": "bounded_EC_origin",
    "physical_time_mapping": "origin_plus_resolution_times_step",
    "known_state_steps": "zero_through_declared_event_count_inclusive",
    "unobserved_future": "arbitrary_extension_over_declared_control_states",
    "prefix_status": "caller_declared_not_authenticated_history",
}
DEONTIC_SEMANTICS = "distinct_state_norm_operator_parameters_no_modal_axioms_or_actor_duties"
PRODUCERS = (core, lean, formulas, events, source_wire, importlib.import_module(__name__))
_PINS = {name: sha for module in PRODUCERS for name, sha in core._pin(module).items()}
require, digest, wire = events.require, events.digest, events.wire


def producer_pins():
    from ....optimizers.logic_theorem_optimizer.autoencoder_schema_lake import _pin_imported_module
    for name, expected in _PINS.items():
        require(_pin_imported_module(importlib.import_module(name)) == expected,
                "UI temporal logic producer changed: " + name)
    return dict(_PINS)


def state_symbol(state_id):
    require(type(state_id) is str and 0 < len(state_id.encode()) <= 256, "bounded explicit UI state identifier required")
    return "ui_state:v" + state_id.encode().hex()


def _closed(value, keys, name):
    require(type(value) is dict and set(value) == set(keys), "complete explicit " + name + " fields required")


def _replay_ec(source_text, candidate, ec_payload):
    require(type(ec_payload) is dict and ec_payload.get("schema") == events.SCHEMA,
            "actual bounded EC payload required")
    target = {"kind": "document", "document": candidate["document"]}
    require(ec_payload.get("source_text") == source_text and wire(ec_payload.get("candidate")) == wire(target),
            "bounded EC source/native-document binding differs")
    expected = events.prepare_payload(source_text, target,
        events.previous.UIBehaviorInterpretation.from_dict(ec_payload["behavior_interpretation"]),
        events.previous.UIGuardInterpretation.from_dict(ec_payload["guard_interpretation"]),
        events.UIBoundedECInterpretation.from_dict(ec_payload["event_interpretation"]))
    require(wire(expected) == wire(ec_payload), "complete bounded EC replay differs")
    return expected


def _source_candidate(source_text, candidate, descriptor, requirement_id):
    require(type(source_text) is str and 0 < len(source_text.encode()) <= 65536,
            "bounded original declared logic source required")
    source_wire.json_audit._json_input(candidate)
    _closed(candidate, {"kind", "document", "logic"}, "compound UI candidate")
    require(candidate["kind"] == "ui_declared_logic", "explicit compound UI logic candidate required")
    _closed(candidate["logic"], {"temporal", "tdfol", "dcec"}, "compound UI logic")
    source_wire._complete_document(candidate["document"])
    source = json.loads(source_text, object_pairs_hook=source_wire._unique, parse_constant=source_wire._constant)
    source_wire.json_audit._json_input(source)
    _closed(source, {"schema", "candidate", "interpretations"}, "declared logic source")
    require(source["schema"] == "ui-declared-logic-source/v1", "declared logic source schema required")
    _closed(source["interpretations"], {"behavior", "guard", "event"}, "UI logic interpretation bodies")
    require(all(type(body) is dict for body in source["interpretations"].values()),
            "complete explicit behavior/guard/event semantic bodies required")
    require(all(body is None or type(body) is dict for body in candidate["logic"].values()),
            "each candidate logic declaration must be explicit object or null")
    require(wire(source["candidate"]) == wire(candidate), "whole source/candidate logic differs")
    key = {"TFOL": "temporal", "TDFOL": "tdfol"}.get(requirement_id)
    require(key is not None, "actual TFOL or TDFOL requirement required")
    require(wire(candidate["logic"][key]) == wire(descriptor), "original candidate logic descriptor differs")
    return source


def _expression(node, binding_indices, referenced, operators, depth=0):
    require(type(node) is dict and depth <= 24, "bounded native temporal AST required")
    kind = node.get("node_type")
    operators.append(kind)
    if kind == "Predicate":
        require(node.get("name") == "UIState" and type(node.get("arguments")) is list and len(node["arguments"]) == 1,
                "only explicitly bound unary UIState predicates supported")
        term = node["arguments"][0]
        require(type(term) is dict and term.get("node_type") == "Constant" and term.get("sort") in
                (None, {"enum": "Sort", "value": "Object"}) and term.get("name") in binding_indices,
                "exact bound ground UI state constant required")
        symbol = term["name"]
        referenced.add(symbol)
        return "(fun step => uiTemporalStateAt future step = .s" + str(binding_indices[symbol]) + ")"
    if kind in {"TemporalFormula", "BinaryTemporalFormula"}:
        require(node.get("time_bound") is None and node.get("time") is None,
                "bounded metric or annotated time is not this unbounded logical-step profile")
        op = node["operator"]["value"]
        operators.append(op)
        allowed = {"□": ("alwaysTime", 1), "◊": ("eventuallyTime", 1), "X": ("nextTime", 1), "U": ("untilTime", 2)}
        require(op in allowed, "unsupported native UI temporal operator")
        name, arity = allowed[op]
        children = [node["formula"]] if kind == "TemporalFormula" else [node["left"], node["right"]]
        require(len(children) == arity, "native temporal operator arity differs")
        return "(" + name + " " + " ".join(_expression(c, binding_indices, referenced, operators, depth + 1)
                                              for c in children) + ")"
    if kind == "DeonticFormula":
        op = node["operator"]["value"]
        require(op in {"O", "P", "F"} and node.get("agent") is None and node.get("context") is None,
                "only explicit unindexed state norms O/P/F supported; no actor/context inference")
        operators.append("deontic:" + op)
        return "(i.modal " + lean.string("deontic:" + op) + " [] none " + _expression(
            node["formula"], binding_indices, referenced, operators, depth + 1) + ")"
    if kind in {"UnaryFormula", "BinaryFormula"}:
        op = node["operator"]["value"]
        operators.append(op)
        children = [node["formula"]] if kind == "UnaryFormula" else [node["left"], node["right"]]
        values = [_expression(c, binding_indices, referenced, operators, depth + 1) + " step" for c in children]
        if op == "¬":
            require(len(values) == 1, "native Boolean negation arity differs")
            return "(fun step => ¬ (" + values[0] + "))"
        require(op in {"∧", "∨", "→", "↔"} and len(values) == 2, "unsupported native Boolean connective")
        return "(fun step => (" + values[0] + ") " + op + " (" + values[1] + "))"
    raise ValueError("unsupported native UI temporal AST constructor: " + str(kind))


def prepare_payload(source_text, candidate, *, ec_payload, descriptor, requirement_id):
    """Recheck full source, compound prediction, EC state values and native ASTs."""
    pins = producer_pins()
    before = wire(candidate)
    source = _source_candidate(source_text, candidate, descriptor, requirement_id)
    ec = _replay_ec(source_text, candidate, ec_payload)
    # Source bodies are the ONLY permitted origins for the replayed EC meaning.
    options = source_wire._bound_options(source_text, {"kind": "document", "document": candidate["document"]},
                                         source["interpretations"])
    for key in ("behavior_interpretation", "guard_interpretation", "event_interpretation"):
        require(key in options and wire(options[key].to_dict()) == wire(ec[key]),
                "EC semantics differ from original source declaration: " + key)
    _closed(descriptor, {"schema", "time_semantics", "deontic_semantics", "state_bindings", "formulas"},
            "UI temporal descriptor")
    require(descriptor["schema"] == DESCRIPTOR_SCHEMA and descriptor["time_semantics"] == TIME_SEMANTICS,
            "complete explicit arbitrary-continuation logical-step time policy required")
    require(descriptor["deontic_semantics"] == DEONTIC_SEMANTICS, "explicit state-norm parameter scope required")
    states = ec["states"]
    require(type(states) is list and 1 <= len(states) <= 32 and len(set(states)) == len(states),
            "bounded complete declared UI state vocabulary required")
    bindings = descriptor["state_bindings"]
    require(type(bindings) is list and 1 <= len(bindings) <= 32, "explicit bounded state bindings required")
    indices = {}
    for binding in bindings:
        _closed(binding, {"symbol", "state_id"}, "state binding")
        require(binding["state_id"] in states and binding["symbol"] == state_symbol(binding["state_id"]),
                "state binding must preserve exact declared UI identity")
        require(binding["symbol"] not in indices, "duplicate state binding")
        indices[binding["symbol"]] = states.index(binding["state_id"])
    declared = descriptor["formulas"]
    require(type(declared) is list and 1 <= len(declared) <= 8, "one to eight explicit temporal formulas required")
    records, identities, all_referenced = [], set(), set()
    for item in declared:
        _closed(item, {"formula_id", "formula"}, "temporal formula declaration")
        identity, text = item["formula_id"], item["formula"]
        require(type(identity) is str and 0 < len(identity.encode()) <= 128 and identity not in identities,
                "bounded unique formula identity required")
        identities.add(identity)
        require(type(text) is str and 0 < len(text.encode()) <= 16384, "bounded actual native temporal formula required")
        ast, printed, fmt, counts, parser_modules = formulas._tdfol(text, requirement_id)
        references, operators = set(), []
        _expression(ast, indices, references, operators)
        all_referenced |= references
        for module_name in parser_modules:
            pins.update(core._pin(importlib.import_module(module_name)))
        records.append({"formula_id": identity, "formula": text, "printed": printed, "native_ast": ast,
            "ast_format": fmt, "operator_counts": counts, "operators": operators,
            "referenced_state_symbols": sorted(references), "native_parse_print_parse_exact": True})
    require(all_referenced == set(indices), "all supplied state bindings must be used; no ignored semantic inputs")
    require(all(type(values) is list and len(values) == 1 and values[0] in states for values in ec["fluent_values"]),
            "known EC prefix must retain exactly one declared control state per step")
    payload = {"schema": SCHEMA, "requirement_id": requirement_id, "source_text": source_text,
        "candidate": deepcopy(candidate), "candidate_sha256": digest(candidate), "source_sha256": events.guards.ui.previous._source(source_text),
        "descriptor": deepcopy(descriptor), "ec_payload": ec, "ec_payload_sha256": digest(ec),
        "state_indices": {symbol: indices[symbol] for symbol in sorted(indices)}, "states": list(states),
        "known_state_indices": [states.index(values[0]) for values in ec["fluent_values"]],
        "known_state_step_count": len(ec["fluent_values"]), "formulas": records,
        "clock": ec["clock"], "origin": ec["origin"], "resolution": ec["resolution"],
        "producer_pins": pins, "time_semantics": deepcopy(TIME_SEMANTICS),
        "capability_scope": "explicit_UI_state_formulas_over_declared_prefix_and_arbitrary_unbounded_state_extension",
        "source_semantics_verified": False, "event_authenticity_verified": False, "formula_truth_proven": False,
        "actor_duties_inferred": False, "actual_runtime_execution": False, "admitted": False, "qualified": False,
        "limitations": ["caller_declared_prefix_not_authenticated_history",
            "arbitrary_future_extension_not_verified_behavior", "state_norm_operators_are_parameters_without_modal_axioms",
            "no_actor_duties_or_event_occurrences_inferred", "formula_truth_not_asserted", "actual_Lake_execution_required"]}
    require(len(wire(payload)) <= 8 * 1024 * 1024, "bounded UI temporal payload exceeded; no truncation")
    require(wire(candidate) == before, "temporal preparation changed original candidate")
    producer_pins()
    return json.loads(wire(payload))


def _lean(payload):
    states, known = payload["states"], payload["known_state_indices"]
    lines = ["namespace UITemporalEC", events._lean(payload["ec_payload"]), "end UITemporalEC",
        "inductive UITemporalState where", *["  | s" + str(i) for i in range(len(states))],
        "  deriving DecidableEq, Repr", "def uiTemporalStateIdentity : UITemporalState → String",
        *["  | .s" + str(i) + " => " + lean.string(state) for i, state in enumerate(states)],
        "def uiTemporalKnownStates : List UITemporalState := [" + ", ".join(".s" + str(i) for i in known) + "]",
        "def uiTemporalStateAt (future : Nat → UITemporalState) (step : Nat) : UITemporalState :=",
        "  (uiTemporalKnownStates[step]?).getD (future step)",
        "def uiTemporalPhysicalTick (step : Nat) : Nat := " + str(payload["origin"]) + " + " + str(payload["resolution"]) + " * step",
        "def uiTemporalClockDeclaration : String := " + lean.string(wire(payload["clock"]).decode())]
    for tick, state in enumerate(known):
        lines.append("example (future : Nat → UITemporalState) : uiTemporalStateAt future " + str(tick) +
                     " = .s" + str(state) + " := by rfl")
        lines.append("example : uiTemporalPhysicalTick " + str(tick) + " = " +
                     str(payload["origin"] + payload["resolution"] * tick) + " := by decide")
        lines.append("example (future : Nat → UITemporalState) : UITemporalEC.holdsAt "
            "(uiTemporalStateIdentity (uiTemporalStateAt future " + str(tick) + ")) "
            "(uiTemporalPhysicalTick " + str(tick) + ") = some true := by\n  change UITemporalEC.holdsAt " +
            lean.string(states[state]) + " " + str(payload["origin"] + payload["resolution"] * tick) +
            " = some true\n  decide")
        for index in range(len(states)):
            lines.append("example (future : Nat → UITemporalState) : UITemporalEC.holdsAt "
                "(uiTemporalStateIdentity .s" + str(index) + ") (uiTemporalPhysicalTick " + str(tick) + ") = "
                "some (decide (uiTemporalStateAt future " + str(tick) + " = .s" + str(index) + ")) := by\n  change UITemporalEC.holdsAt " +
                lean.string(states[index]) + " " + str(payload["origin"] + payload["resolution"] * tick) +
                " = some " + str(index == state).lower() + "\n  decide")
    end = len(known)
    lines.append("example (future : Nat → UITemporalState) : uiTemporalStateAt future " + str(end) +
                 " = future " + str(end) + " := by rfl")
    lines.append("example (future : Nat → UITemporalState) : uiTemporalStateAt future " + str(end + 1) +
                 " = future " + str(end + 1) + " := by rfl")
    for index, record in enumerate(payload["formulas"]):
        expression = _expression(record["native_ast"], payload["state_indices"], set(), [])
        lines.append("def uiTemporalFormula_" + str(index) +
            " (i : Interpretation UITemporalState String) (future : Nat → UITemporalState) : Nat → Prop := " + expression)
        lines.append("def uiTemporalFormulaIdentity_" + str(index) + " : String := " + lean.string(record["formula_id"]))
    return "\n".join(lines)


def emit_projection(row, *, report=None):
    identities = {values[0]: requirement for requirement, values in ROUTES.items()}
    if type(row) is not dict or row.get("projection_id") not in identities:
        raise NotImplementedError
    producer_pins()
    requirement = identities[row["projection_id"]]
    identity, family, profile = ROUTES[requirement]
    require(row.get("logic_family") == family and row.get("profile") == profile, "owned UI temporal route differs")
    require(type(report) is dict and report.get("schema") == REPORT_SCHEMA and report.get("domain_id") == "ui_ux_ir"
        and row.get("source_digest") == report.get("source_digest") and sum(p == row for p in report.get("projections", [])) == 1,
        "exact complete declared-logic report/source/row binding required")
    from . import ui_declared_logic_source as adapter
    binding = report["declared_logic_source_binding"]
    adapter.validate_family_training_report(report, source_text=binding["source_text"], candidate=binding["candidate"])
    payload = row["payload"]
    expected = prepare_payload(binding["source_text"], binding["candidate"], ec_payload=payload["ec_payload"],
        descriptor=payload["descriptor"], requirement_id=requirement)
    require(wire(expected) == wire(payload), "complete UI temporal source/native AST replay differs")
    return _lean(expected), {"validator": "source_candidate_EC_prefix_native_temporal_AST_and_state_binding_replay",
        "operators": sorted({op for item in expected["formulas"] for op in item["operators"]}),
        "native_formula_count": len(expected["formulas"]), "payload_sha256": digest(expected),
        "capability_floor_eligible": True, "capability_scope": expected["capability_scope"],
        "known_state_step_count": expected["known_state_step_count"],
        "Lean_EC_state_mapping_cells": expected["known_state_step_count"] * len(expected["states"]),
        "EC_state_mapping_checked_in_same_Lean_lowering": True,
        "future_semantics": TIME_SEMANTICS["unobserved_future"],
        "temporal_operator_semantics": "existing_unbounded_discrete_Nat_G_eventually_X_U",
        "deontic_operator_semantics": DEONTIC_SEMANTICS,
        "source_semantics_verified": False, "event_authenticity_verified": False,
        "formula_truth_proven": False, "actor_duties_inferred": False, "execution_authority": False}


__all__ = ["SCHEMA", "DESCRIPTOR_SCHEMA", "REPORT_SCHEMA", "TIME_SEMANTICS", "DEONTIC_SEMANTICS", "ROUTES",
           "PROJECTION_IDS", "PROFILES", "PRODUCERS", "producer_pins", "state_symbol", "prepare_payload", "emit_projection"]
