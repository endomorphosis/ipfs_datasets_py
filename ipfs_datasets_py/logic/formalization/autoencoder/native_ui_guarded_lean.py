"""Explicit frozen Boolean guard interpretations for declared UI transitions.

No guard meaning, initial value, clock, update or event occurrence is inferred.
Every Boolean assignment is retained, including disabled transitions. This is
a finite caller model, not a translation or proof of natural-language meaning.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
import importlib
import json

from . import family_training as core
from . import native_family_lean_emitters as lean
from . import native_tla_projection as tla
from . import ui_source_contract_384_v3 as ui
from ...software_verification import state, transitions

SCHEMA = "native-ui-frozen-boolean-guards/v1"
EVIDENCE_SCHEMA = "ui-frozen-boolean-guard-interpretation/v1"
SCOPE = "caller_supplied_frozen_boolean_parameters_not_source_translation"
PREFIX = "ui_ux_ir/explicit_guards/"
ROUTES = {"state": ("transition_system", "explicit_ui_frozen_boolean_state/v1"),
          "tla_plus": ("transition_system", "tla_plus")}
_PINS = {name: sha for module in (core, lean, tla, ui, state, transitions,
    importlib.import_module(__name__)) for name, sha in core._pin(module).items()}
require = ui._require
wire, digest = ui.previous._wire, ui.previous._digest


def producer_pins():
    from ....optimizers.logic_theorem_optimizer.autoencoder_schema_lake import _pin_imported_module
    for name, sha in _PINS.items():
        require(_pin_imported_module(importlib.import_module(name)) == sha,
                "UI guarded producer changed: " + name)
    return dict(_PINS)


def _identifier(value):
    require(type(value) is str and 0 < len(value.encode()) <= 256,
            "bounded explicit Boolean variable identifier required")
    lean.string(value)


def _expression(value, variables, depth=0):
    require(type(value) is dict and depth <= 6, "bounded closed Boolean expression required")
    op = value.get("op")
    if op == "literal":
        ui._closed(value, {"op", "value"}, "Boolean literal")
        require(type(value["value"]) is bool, "typed Boolean literal required")
        return set()
    if op == "variable":
        ui._closed(value, {"op", "variable_id"}, "Boolean variable")
        require(type(value["variable_id"]) is str and value["variable_id"] in variables,
                "declared Boolean variable required")
        return {value["variable_id"]}
    if op == "not":
        ui._closed(value, {"op", "arg"}, "Boolean negation")
        return _expression(value["arg"], variables, depth + 1)
    require(op in {"and", "or"}, "unsupported Boolean guard operator")
    ui._closed(value, {"op", "args"}, "Boolean connective")
    require(type(value["args"]) is list and 2 <= len(value["args"]) <= 8,
            "bounded nontrivial Boolean connective required")
    return set().union(*(_expression(arg, variables, depth + 1) for arg in value["args"]))


def evaluate_expression(expression, values):
    """Evaluate only an already validated, typed finite expression."""
    op = expression["op"]
    if op == "literal": return expression["value"]
    if op == "variable": return values[expression["variable_id"]]
    if op == "not": return not evaluate_expression(expression["arg"], values)
    args = [evaluate_expression(arg, values) for arg in expression["args"]]
    return all(args) if op == "and" else any(args)


def _validate(value):
    ui._closed(value, {"schema", "source_sha256", "candidate_sha256", "behavior_sha256",
        "declaration_scope", "parameter_update_semantics", "variables", "guards", "max_steps"},
        "UI Boolean guard interpretation")
    require(value["schema"] == EVIDENCE_SCHEMA and value["declaration_scope"] == SCOPE,
            "explicit UI Boolean guard scope required")
    require(value["parameter_update_semantics"] == "unchanged_by_all_transitions_no_external_updates",
            "explicit frozen Boolean persistence required")
    for key in ("source_sha256", "candidate_sha256", "behavior_sha256"):
        require(type(value[key]) is str and len(value[key]) == 64 and
                all(c in "0123456789abcdef" for c in value[key]), "exact UI guard binding hash required")
    require(type(value["max_steps"]) is int and 1 <= value["max_steps"] <= 64,
            "explicit bounded UI step count required")
    require(type(value["variables"]) is list and len(value["variables"]) <= 4,
            "at most four explicit Boolean parameters supported")
    names = []
    for row in value["variables"]:
        ui._closed(row, {"variable_id", "type", "initial_value"}, "Boolean parameter")
        _identifier(row["variable_id"])
        require(row["type"] == "boolean" and type(row["initial_value"]) is bool,
                "explicit Boolean type and initial value required")
        names.append(row["variable_id"])
    require(len(set(names)) == len(names), "unique Boolean parameters required")
    require(type(value["guards"]) is list and 1 <= len(value["guards"]) <= 32,
            "bounded nonempty explicit UI guard declarations required")
    used, guards = set(), []
    for row in value["guards"]:
        ui._closed(row, {"native_guard", "expression"}, "UI guard declaration")
        require(type(row["native_guard"]) is dict and type(row["native_guard"].get("guard_id")) is str,
                "complete original UI guard required")
        guards.append(row["native_guard"]["guard_id"])
        used |= _expression(row["expression"], set(names))
    require(len(set(guards)) == len(guards), "unique explicit guard bindings required")
    require(used == set(names), "every declared Boolean parameter must occur in a guard")


@dataclass(frozen=True, slots=True)
class UIGuardInterpretation:
    """Canonical immutable explicit declaration; all decoded views are copies."""
    _encoded: bytes

    def __post_init__(self):
        require(type(self._encoded) is bytes and 0 < len(self._encoded) <= 65536,
                "bounded immutable UI guard bytes required")
        value = json.loads(self._encoded)
        _validate(value)
        require(wire(value) == self._encoded, "canonical UI guard bytes required")

    @classmethod
    def from_dict(cls, value):
        return cls(wire(value))

    def to_dict(self):
        return json.loads(self._encoded)


def _model(source_text, target, behavior_interpretation, guard_interpretation):
    require(type(behavior_interpretation) is ui.UIBehaviorInterpretation and
            type(guard_interpretation) is UIGuardInterpretation,
            "explicit immutable behavior and guard interpretations required")
    graph, _ = ui.previous.previous._native(target)
    graph.validate()
    kind, raw = ui.previous._raw_document(target)
    model, receipt = ui._behavior(behavior_interpretation, source_text, target, kind, raw)
    declaration = guard_interpretation.to_dict()
    require(declaration["source_sha256"] == ui.previous._source(source_text) and
        declaration["candidate_sha256"] == digest(target) and declaration["behavior_sha256"] == digest(receipt),
        "UI guard source/candidate/behavior binding differs")
    require(len(model.states) * 2 ** len(declaration["variables"]) <= 256 and
        len(model.transitions) * 2 ** len(declaration["variables"]) <= 512 and
        len(model.initial_state_ids) == 1, "bounded single-initial UI Boolean product required")
    require(not any(s.parallel_region for s in model.states), "UI parallel regions remain unsupported")
    require(not raw.get("effects"), "UI effect declarations remain unsupported")
    native_guards = {row["guard_id"]: row for row in raw.get("guards", [])}
    declared_guards = {row["native_guard"]["guard_id"]: row for row in declaration["guards"]}
    required = {edge.guard_id for edge in model.transitions if edge.guard_id}
    require(required and required <= set(native_guards) == set(declared_guards),
            "every original UI guard needs an exact declaration; at least one transition must use it")
    for key, row in declared_guards.items():
        require(row["native_guard"] == native_guards[key], "complete native UI guard record differs")
    meanings = {}
    for row in declared_guards.values():
        for field in ("constraint_ref", "formal_constraint_id"):
            reference = row["native_guard"].get(field)
            if not reference: continue
            key = (field, reference)
            require(key not in meanings or meanings[key] == row["expression"],
                    "same explicit UI guard reference has conflicting Boolean meanings")
            meanings[key] = row["expression"]
    terminal = {s.state_id for s in model.states if s.terminal}
    for edge in model.transitions:
        require(len(edge.source_state_ids) == 1 and edge.join_kind.value == "all",
                "UI guard profile requires single-source all join")
        require(not edge.effect_ids, "UI guard effects remain unsupported")
        require(edge.timeout_ms is None, "UI guard timing requires explicit clock semantics; unsupported")
        require(edge.priority == 0 and edge.cancelable and not edge.retryable and not edge.undoable
                and not edge.rollback_target_state_id, "UI priority or recovery semantics remain unsupported")
        require(edge.source_state_ids[0] not in terminal, "terminal UI state has outgoing transition")
    return model, declaration, declared_guards


def prepare_guarded_payload(source_text, target, behavior_interpretation, guard_interpretation):
    pins = producer_pins()
    model, declaration, guards = _model(source_text, target, behavior_interpretation, guard_interpretation)
    variable_names = sorted(row["variable_id"] for row in declaration["variables"])
    valuations = [dict(zip(variable_names, values)) for values in product((False, True), repeat=len(variable_names))]
    state_ids = sorted(s.state_id for s in model.states)
    state_map = {name: "state_" + str(i) for i, name in enumerate(state_ids)}
    aliases = {name: "var:ui-param:" + str(i) for i, name in enumerate(variable_names)}
    variables = [state.StateVariable("var:ui-control", "ui_control", "enumeration", "finite",
        domain_bound=state.FiniteDomainBound("bound:ui-control", members=tuple(state_map.values())))]
    variables += [state.StateVariable(aliases[name], "ui_parameter_" + str(i), "boolean", "finite",
        domain_bound=state.FiniteDomainBound("bound:ui-param:" + str(i), cardinality=2))
        for i, name in enumerate(variable_names)]
    initial_values = {row["variable_id"]: row["initial_value"] for row in declaration["variables"]}
    initial = {"var:ui-control": state_map[model.initial_state_ids[0]],
               **{aliases[name]: initial_values[name] for name in variable_names}}
    predicates = [state.StatePredicate("pred:ui-init", "initial", "Explicit caller initial configuration.",
        expression=initial, subject_variable_ids=tuple(initial))]
    table, edges, actions = [], [], []
    for index, edge in enumerate(sorted(model.transitions, key=lambda row: row.transition_id)):
        for vi, values in enumerate(valuations):
            enabled = evaluate_expression(guards[edge.guard_id]["expression"], values) if edge.guard_id else True
            row = {"transition_id": edge.transition_id, "event_id": edge.event_id, "guard_id": edge.guard_id,
                "valuation_index": vi, "values": values, "enabled": enabled,
                "source_state": edge.source_state_ids[0], "target_state": edge.target_state_id}
            table.append(row)
            if not enabled:
                continue
            identity = "action:ui-guard:" + str(index) + ":" + str(vi)
            before = {"var:ui-control": state_map[edge.source_state_ids[0]],
                      **{aliases[name]: values[name] for name in variable_names}}
            after = {"var:ui-control": state_map[edge.target_state_id]}
            guard_id, next_id = "pred:" + identity + ":guard", "pred:" + identity + ":next"
            predicates += [state.StatePredicate(guard_id, "guard", "Exhaustive enabled Boolean assignment.",
                expression=before, subject_variable_ids=tuple(before)),
                state.StatePredicate(next_id, "next", "Declared UI successor; parameters persist.",
                expression=after, subject_variable_ids=tuple(after))]
            actions.append(transitions.Action(identity, "UIGuardAction" + str(len(actions)),
                transitions.ActionFrame(reads=tuple(before), writes=("var:ui-control",)),
                guard_predicate_id=guard_id, next_predicate_id=next_id))
            edges.append({**row, "action_id": identity})
    require(actions, "empty guarded action relation unsupported; no edge or stutter fabricated")
    relation = transitions.TransitionRelation("transition:ui-guards", "action", "Explicit frozen Boolean UI steps.",
        action_ids=tuple(a.action_id for a in actions), allows_stutter=False)
    native = transitions.StateTransitionIR(schema=state.StateSchema(variables=tuple(variables)),
        predicates=tuple(predicates), actions=tuple(actions), transitions=(relation,))
    artifact = tla.compile_bounded_state(native, max_steps=declaration["max_steps"])
    # Reachability is diagnostic. A disabled initial guard is not silently made
    # true and does not require an invented edge to make a progress check pass.
    reached = {model.initial_state_ids[0]}
    for _ in state_ids:
        expanded = reached | {row["target_state"] for row in edges
            if row["source_state"] in reached and row["values"] == initial_values}
        if expanded == reached: break
        reached = expanded
    terminal = {s.state_id for s in model.states if s.terminal}
    deadlocks = sorted(s for s in reached if s not in terminal and not any(
        row["source_state"] == s and row["values"] == initial_values for row in edges))
    payload = {"schema": SCHEMA, "source_text": source_text, "candidate": target,
        "behavior_interpretation": behavior_interpretation.to_dict(), "guard_interpretation": declaration,
        "state_map": state_map, "variable_aliases": aliases, "valuations": valuations,
        "truth_table": table, "enabled_edges": edges, "native_state": native.to_dict(), "bounded_tla": artifact,
        "reachable_states": sorted(reached), "reachable_nonterminal_deadlocks": deadlocks,
        "all_declared_guards": [guards[key] for key in sorted(guards)], "producer_pins": pins,
        "source_semantics_verified": False, "actual_event_occurrence_asserted": False,
        "runtime_parameter_updates_modeled": False, "clock_semantics_supplied": False,
        "admitted": False, "qualified": False,
        "limitations": [SCOPE, "guard_constraint_references_not_proven", "frozen_parameters_not_dynamic_UI_state",
            "no_timing_effects_priority_parallel_or_recovery_semantics", "disabled_cases_retained",
            "reachable_deadlocks_are_diagnostics_not_a_progress_claim", "bounded_TLA_allows_specification_stuttering",
            "actual_Lake_required_no_source_truth_or_event_authenticity"]}
    require(len(wire(payload)) <= 1048576, "UI guarded payload exceeds explicit byte bound")
    producer_pins()
    return json.loads(wire(payload))


def _lean_expression(expression, names):
    op = expression["op"]
    if op == "literal": return str(expression["value"]).lower()
    if op == "variable": return "values[" + str(names.index(expression["variable_id"])) + "]!"
    if op == "not": return "(!" + _lean_expression(expression["arg"], names) + ")"
    return "(" + (" && " if op == "and" else " || ").join(_lean_expression(arg, names)
        for arg in expression["args"]) + ")"


def _lean(payload):
    names = sorted(payload["variable_aliases"])
    guards = payload["all_declared_guards"]
    lines = [payload["bounded_tla"]["lean_source"], "namespace ExplicitUIGuards"]
    for i, guard in enumerate(guards):
        lines.append(f"def guard_{i} (values : List Bool) : Bool := " + _lean_expression(guard["expression"], names))
        lines.append(f"def guardRecord_{i} : String := " + lean.string(wire(guard["native_guard"]).decode()))
        for vi, values in enumerate(payload["valuations"]):
            inputs = "[" + ", ".join(str(values[name]).lower() for name in names) + "]"
            expected = str(evaluate_expression(guard["expression"], values)).lower()
            lines.append(f"example : guard_{i} {inputs} = {expected} := by decide")
    lines += ["def completeTruthTable : String := " + lean.string(wire(payload["truth_table"]).decode()),
        "def stateIdentityMap : String := " + lean.string(wire(payload["state_map"]).decode()),
        "def parameterIdentityMap : String := " + lean.string(wire(payload["variable_aliases"]).decode()),
        "def reachableNonterminalDeadlocks : List String := [" + ", ".join(
            lean.string(s) for s in payload["reachable_nonterminal_deadlocks"]) + "]"]
    native = payload["native_state"]
    action_index = {row["action_id"]: i for i, row in enumerate(native["actions"])}
    predicate_index = {row["predicate_id"]: i for i, row in enumerate(native["predicates"])}
    def configuration(source, valuation):
        values = {"var:ui-control": payload["state_map"][source], **{
            payload["variable_aliases"][name]: valuation[name] for name in names}}
        return "⟨" + ", ".join(lean.string(values[row["variable_id"]]) if row["type_kind"] == "enumeration"
            else str(values[row["variable_id"]]).lower() for row in native["schema"]["variables"]) + "⟩"
    for edge in payload["enabled_edges"]:
        index = action_index[edge["action_id"]]
        action = native["actions"][index]
        defs = [f"action_{index}", *("predicate_" + str(predicate_index[action[key]]) for key in
            ("guard_predicate_id", "next_predicate_id"))]
        lines.append(f"example : action_{index} {configuration(edge['source_state'], edge['values'])} "
            + configuration(edge["target_state"], edge["values"]) + " := by simp [" + ", ".join(defs) + "]")
    for row in payload["truth_table"]:
        if row["enabled"]: continue
        choices, defs = [], []
        for edge in payload["enabled_edges"]:
            if edge["transition_id"] != row["transition_id"]: continue
            index = action_index[edge["action_id"]]
            action = native["actions"][index]
            choices.append(f"action_{index} {configuration(row['source_state'], row['values'])} t")
            defs.extend([f"action_{index}", *("predicate_" + str(predicate_index[action[key]]) for key in
                ("guard_predicate_id", "next_predicate_id"))])
        proposition = " ∨ ".join(choices) if choices else "False"
        lines.append("-- A disabled original transition has no expanded native successor, for any target state.")
        lines.append("example (t : State) : ¬ (" + proposition + ") := by simp [" + ", ".join(defs) + "]")
    lines += ["end ExplicitUIGuards"]
    return "\n".join(lines)


def emit_projection(row, *, report=None):
    identity = row.get("projection_id")
    if identity not in {PREFIX + kind + "/v1" for kind in ROUTES}:
        raise NotImplementedError
    kind = identity[len(PREFIX):].split("/")[0]
    require((row.get("logic_family"), row.get("profile")) == ROUTES[kind], "UI guarded route identity differs")
    payload = row.get("payload")
    require(type(payload) is dict and payload.get("schema") == SCHEMA, "UI guarded payload required")
    require(type(report) is dict and report.get("domain_id") == "ui_ux_ir" and
        row.get("source_digest") == report.get("source_digest") and
        sum(item == row for item in report.get("projections", [])) == 1,
        "UI guarded lowering requires exact live report domain/source/row binding")
    from . import ui_source_contract_384_v4 as adapter
    adapter.validate_family_training_report(report, source_text=payload["source_text"], target=payload["candidate"],
        behavior_interpretation=ui.UIBehaviorInterpretation.from_dict(payload["behavior_interpretation"]),
        guard_interpretation=UIGuardInterpretation.from_dict(payload["guard_interpretation"]),
        requested_families=report["requested_families"])
    expected = prepare_guarded_payload(payload["source_text"], payload["candidate"],
        ui.UIBehaviorInterpretation.from_dict(payload["behavior_interpretation"]),
        UIGuardInterpretation.from_dict(payload["guard_interpretation"]))
    require(expected == payload, "complete UI guard source/interpretation/edge replay differs")
    requirements = []
    if kind == "tla_plus":
        artifact = payload["bounded_tla"]
        requirements = [{"kind": "SANY", "module_name": artifact["module_name"], "model_text": artifact["model_text"]}]
    return _lean(payload), {"validator": "complete_explicit_UI_Boolean_truth_table_and_native_state_replay",
        "operators": ["finite_boolean_guard", "explicit_initial_values", "frozen_parameter_frame", "declared_labelled_transition"],
        "assumptions": payload["limitations"], "syntax_requirements": requirements,
        "source_semantics_verified": False, "actual_event_occurrence_asserted": False,
        "timing_supported": False, "guard_truth_table_rows": len(payload["truth_table"]),
        "enabled_edge_count": len(payload["enabled_edges"]), "reachable_nonterminal_deadlocks": payload["reachable_nonterminal_deadlocks"]}


__all__ = ["UIGuardInterpretation", "prepare_guarded_payload", "emit_projection", "producer_pins"]
