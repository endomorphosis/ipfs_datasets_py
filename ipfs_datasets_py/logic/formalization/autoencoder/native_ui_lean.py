"""Bounded Lean meanings for explicit UI declarations and observed trace prefixes.

No source-text inference, real event attestation, capability grant, or cognitive
truth is introduced. In particular, the old UI ``happens(event,from,to)`` tuple
is an untimed declared edge, never a timed event-calculus occurrence. Ambiguous
``before`` prose and timeout declarations need further owner semantics.
"""
from __future__ import annotations

import hashlib
import json
import re
from . import native_family_lean_emitters as old

require, string = old.require, old.string
_VERSION = "native-ui-lean/v1"
_ATOM = re.compile(r"([A-Za-z][A-Za-z0-9_]*)\(([A-Za-z0-9][A-Za-z0-9._:/-]{0,255})\)")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}")


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _closed(value, keys, label):
    require(type(value) is dict and set(value) == set(keys), "closed_UI_" + label + "_required")


def _array(value, label, *, nonempty=True, bound=1024):
    require(type(value) is list and (not nonempty or value) and len(value) <= bound,
            "bounded_UI_" + label + "_required")
    return value


def _strings(value):
    _array(value, "source_refs", nonempty=False)
    require(all(type(item) is str and _ID.fullmatch(item) for item in value), "UI_source_ref_identifier_required")
    return "[" + ", ".join(string(x) for x in value) + "]"


def _details(payload, validator, operators, assumptions, **extra):
    return {"validator": validator, "implementation": _VERSION,
        "payload_sha256": hashlib.sha256(_raw(payload).encode()).hexdigest(),
        "operators": operators, "assumptions": assumptions, "source_semantics_verified": False,
        "event_occurrences_attested": False, "runtime_authority_granted": False, **extra}


def _atom(value):
    require(type(value) is str and len(value) <= 1024, "bounded_UI_atomic_content_required")
    match = _ATOM.fullmatch(value)
    require(match is not None, "UI_content_requires_single_explicit_atom")
    return match.groups()


def cognitive(payload):
    _closed(payload, {"formulas"}, "cognitive_payload")
    rows = _array(payload["formulas"], "cognitive_formulas")
    lines, operators = [], []
    for index, row in enumerate(rows):
        _closed(row, {"kind", "actor", "content", "source_ref_ids"}, "cognitive_formula")
        require(row["kind"] in {"knows", "believes", "intends", "observes", "delegates"}, "unsupported_UI_cognitive_operator")
        require(type(row["actor"]) is str and row["actor"].strip(), "UI_cognitive_actor_required")
        name, arg = _atom(row["content"])
        # ``maybe_intent`` and ``not_auto_intent`` remain their exact distinct
        # atoms. Neither is promoted to an established user intention.
        body = "(fun t => i.atom " + string(name) + " [i.constant " + string(arg) + "] t)"
        lines.append(f"def cognitive_{index} {{Entity Agent : Type}} (i : Interpretation Entity Agent) : Nat → Prop := "
            + "i.cognitive " + string(row["kind"]) + " (i.agent " + string(row["actor"]) + ") " + body)
        lines.append(f"def sources_{index} : List String := " + _strings(row["source_ref_ids"]))
        operators.append("actor_indexed:" + row["kind"])
    return "\n".join(lines), _details(payload, "closed_UI_cognitive_records_and_single_atom_grammar", operators, [
        "Each cognitive operator is an explicit interpretation parameter; no knowledge, belief, intention or delegation is asserted.",
        "The native UI projection carries no observation timestamp; Nat is a free evaluation index, not invented event time.",
        "Speculative maybe_intent and not_auto_intent retain distinct atomic names."],
        capability_floor_eligible=False,
        provided_capabilities=["actor_indexed_cognitive_interpretation"],
        missing_capabilities=["explicit_deontic_cognitive_event_calculus_composition"])


def deontic(payload):
    _closed(payload, {"formulas"}, "deontic_payload")
    lines, operators = [], []
    for index, row in enumerate(_array(payload["formulas"], "deontic_formulas")):
        _closed(row, {"operator", "proposition", "strength", "source_ref_ids"}, "deontic_formula")
        require(row["operator"] in {"obligation", "permission", "prohibition"}, "unsupported_UI_deontic_operator")
        require(row["strength"] in {"strict", "weak"}, "unsupported_UI_deontic_strength")
        require(" before " not in row["proposition"], "UI_before_requires_explicit_occurrence_and_precedence_semantics")
        name, action = _atom(row["proposition"])
        require(name in {"invoke", "weaken_norm"}, "unsupported_UI_deontic_action_atom")
        modality = {"obligation": "O", "permission": "P", "prohibition": "F"}[row["operator"]]
        body = "(fun t => i.atom " + string(name) + " [i.constant " + string(action) + "] t)"
        lines.append(f"def norm_{index} {{Entity Agent : Type}} (i : Interpretation Entity Agent) : Nat → Prop := "
            + "i.modal " + string("deontic:" + modality) + " [] (some " + string("UI-strength:" + row["strength"]) + ") " + body)
        lines.append(f"def sources_{index} : List String := " + _strings(row["source_ref_ids"]))
        operators.append("deontic:" + modality + ":" + row["strength"])
    return "\n".join(lines), _details(payload, "closed_UI_atomic_norm_records", operators, [
        "Strength is a retained modal context; no weakening, execution authorization or norm truth is inferred.",
        "Only atomic native actions are supported. Ambiguous temporal before strings are explicitly blocked."],
        capability_floor_eligible=False, provided_capabilities=["atomic_deontic_interpretation"],
        missing_capabilities=["explicit_temporal_deontic_composition"])


def declared_edges(payload):
    _closed(payload, {"formulas"}, "event_declarations")
    states, edges, starts, stops, sources = [], [], [], [], []
    for row in _array(payload["formulas"], "event_declarations"):
        _closed(row, {"kind", "args", "source_ref_ids"}, "event_declaration")
        args = _array(row["args"], "event_arguments", bound=8)
        require(all(type(x) is str for x in args), "UI_event_arguments_require_symbols")
        sources.append(_strings(row["source_ref_ids"]))
        kind = row["kind"]
        if kind == "fluent":
            require(len(args) == 1, "UI_fluent_arity")
            op, state = _atom(args[0]); require(op == "in_state", "UI_state_fluent_required")
            require(state not in states, "duplicate_UI_state_declaration"); states.append(state)
        elif kind == "happens":
            require(len(args) == 3 and all(_ID.fullmatch(x) for x in args),
                    "UI_happens_is_single_source_untimed_edge_only_timeout_or_multi_source_requires_semantics")
            require(tuple(args) not in edges, "duplicate_UI_edge_declaration"); edges.append(tuple(args))
        elif kind in {"initiates", "terminates"}:
            require(len(args) == 2 and _ID.fullmatch(args[0]), "UI_effect_arity")
            op, state = _atom(args[1]); require(op == "in_state", "UI_state_effect_required")
            pair = (args[0], state); target = starts if kind == "initiates" else stops
            require(pair not in target, "duplicate_UI_effect_declaration"); target.append(pair)
        else:
            raise old.UnsupportedNativeLean("unsupported_UI_event_calculus_declaration:" + str(kind))
    require(states and edges, "UI_declared_states_and_edges_required")
    require(all(a in states and b in states for _,a,b in edges), "UI_edge_references_undeclared_state")
    require(set(starts) == {(event,to) for event,_,to in edges} and set(stops) == {(event,fr) for event,fr,_ in edges},
            "UI_initiates_terminates_must_match_exact_declared_edges")
    tuples = lambda rows: "[" + ", ".join("(" + ", ".join(string(x) for x in row) + ")" for row in rows) + "]"
    lines = ["def declaredStates : List String := " + _strings(states),
        "def declaredEdges : List (String × String × String) := " + tuples(edges),
        "def declaredInitiates : List (String × String) := " + tuples(starts),
        "def declaredTerminates : List (String × String) := " + tuples(stops),
        "def step (event beforeState afterState : String) : Prop := (event, beforeState, afterState) ∈ declaredEdges",
        "def initiates (event state : String) : Prop := (event, state) ∈ declaredInitiates",
        "def terminates (event state : String) : Prop := (event, state) ∈ declaredTerminates",
        "def sourceReferences : List (List String) := [" + ", ".join(sources) + "]"]
    for index,(event,before,after) in enumerate(edges):
        lines.append(f"theorem declared_edge_{index} : step {string(event)} {string(before)} {string(after)} := by simp [step, declaredEdges]")
    return "\n".join(lines), _details(payload, "closed_UI_untimed_edge_and_exact_effect_consistency", ["declared_transition", "initiates", "terminates"], [
        "The UI compiler's three-argument happens record denotes an untimed declared edge, never an actual timed occurrence.",
        "Step is membership in the explicitly declared relation; no run, initial-state reachability, inertia or event-calculus axiom is asserted.",
        "Only a single source state is supported; timeout and multi-source records remain blocked."],
        semantics_scope="UI_declared_transition_relation_not_timed_event_occurrence",
        capability_floor_eligible=False, provided_capabilities=["untimed_declared_transition_relation"],
        missing_capabilities=["timed_event_calculus"])


def _schema(schema, name, declarations, mappings, depth=0):
    require(depth <= 8 and type(schema) is dict, "bounded_UI_interface_type_required")
    kind = schema.get("type")
    if kind in {"string", "boolean", "integer", "null"}:
        _closed(schema, {"type"}, "primitive_interface_type")
        return {"string": "String", "boolean": "Bool", "integer": "Int", "null": "Unit"}[kind]
    if kind == "array":
        _closed(schema, {"type", "items"}, "array_interface_type")
        return "List (" + _schema(schema["items"], name + "Item", declarations, mappings, depth+1) + ")"
    require(kind == "object", "unsupported_UI_interface_type_or_constraint")
    _closed(schema, {"type", "properties", "required", "additionalProperties"}, "object_interface_type")
    props, required = schema["properties"], schema["required"]
    require(schema["additionalProperties"] is False and type(props) is dict and len(props) <= 64,
            "UI_interface_requires_bounded_closed_object")
    _array(required, "required_fields", nonempty=False, bound=64)
    require(all(type(x) is str for x in required) and len(set(required)) == len(required) and set(required) <= set(props),
            "UI_interface_required_fields_invalid")
    fields = []
    for index, (field, child) in enumerate(sorted(props.items())):
        require(type(field) is str and field, "UI_interface_field_name_required")
        typ = _schema(child, name + "Field" + str(index), declarations, mappings, depth+1)
        if field not in required: typ = "Option (" + typ + ")"
        fields.append("  f" + str(index) + " : " + typ)
        mappings.append({"record": name, "lean_field": "f" + str(index), "source_field": field, "required": field in required})
    # Empty object has a single inhabitant; it is never a free-form JSON map.
    declarations.append(("structure " + name + " where\n" + "\n".join(fields)) if fields else "abbrev " + name + " := Unit")
    declarations.append("def " + name + "FieldNames : List String := [" + ", ".join(string(x) for x in sorted(props)) + "]")
    return name


def interface_bindings(payload):
    _closed(payload, {"identity_profile", "interface_cid", "bindings"}, "interface_payload")
    require(payload["identity_profile"] == "mcp-idl-interface-identity-v1", "unsupported_UI_interface_identity_profile")
    require(type(payload["interface_cid"]) is str and payload["interface_cid"], "UI_interface_identity_required")
    lines, mappings, seen, actions, joins = [], [], set(), set(), set()
    fields = ("binding_id", "action_id", "component_id", "dom_action", "interface_cid", "method_name", "risk_class", "confirmation_class", "idempotency")
    for index, row in enumerate(_array(payload["bindings"], "interface_bindings", bound=128)):
        _closed(row, {*fields, "method_contract"}, "interface_binding")
        require(all(type(row[key]) is str and row[key] for key in fields), "UI_binding_string_fields_required")
        require(row["binding_id"] not in seen and row["action_id"] not in actions and (row["component_id"],row["dom_action"]) not in joins,
                "duplicate_or_ambiguous_UI_binding")
        seen.add(row["binding_id"]); actions.add(row["action_id"]); joins.add((row["component_id"],row["dom_action"]))
        require(row["interface_cid"] == payload["interface_cid"], "UI_binding_interface_identity_differs")
        require(row["risk_class"] in {"low", "medium", "high", "destructive"} and
                row["confirmation_class"] in {"none", "confirm", "double_confirm", "consent"} and
                row["idempotency"] in {"unknown", "idempotent", "non_idempotent"}, "unsupported_UI_binding_classification")
        method = row["method_contract"]
        _closed(method, {"name", "input_schema", "output_schema"}, "method_contract")
        require(method["name"] == row["method_name"], "UI_binding_method_identity_differs")
        inp = _schema(method["input_schema"], "Input" + str(index), lines, mappings)
        out = _schema(method["output_schema"], "Output" + str(index), lines, mappings)
        lines += [f"structure Binding{index} where"] + ["  " + key + " : String" for key in fields]
        values = ", ".join(key + " := " + string(row[key]) for key in fields)
        lines.append(f"def declaredBinding{index} : Binding{index} := {{ " + values + " }")
        matches = " ∧ ".join("b." + key + " = " + string(row[key]) for key in fields)
        lines.append(f"def bindingMatches{index} (b : Binding{index}) : Prop := " + matches)
        lines.append(f"structure Contract{index} where\n  invoke : {inp} → {out} → Prop")
        lines.append(f"def boundInvocation{index} (c : Contract{index}) (b : Binding{index}) (request : {inp}) (result : {out}) : Prop := bindingMatches{index} b ∧ c.invoke request result")
        lines.append(f"theorem declared_binding_matches_{index} : bindingMatches{index} declaredBinding{index} := by simp [bindingMatches{index}, declaredBinding{index}]")
    return "\n".join(lines), _details(payload, "closed_verified_UI_binding_join_and_typed_method_contract", ["typed_request", "typed_result", "interface_action_binding"], [
        "Input/output record types preserve required versus optional fields; closed records forbid extra fields.",
        "The invocation relation is supplied by an interpretation, not an executed backend method or a verified implementation.",
        "Risk, confirmation and idempotency classifications are preserved declarations; they do not grant permission or assert runtime confirmation."], field_mapping=mappings)


def trace_prefix(payload):
    from ...software_verification.trace import TraceIR
    from ...software_verification.syntax_bridge import SoftwareVerificationSyntaxBridge
    _closed(payload, {"native_document", "typed_expression", "bridge"}, "trace_projection")
    native = TraceIR.from_dict(payload["native_document"])
    wire = native.to_dict()
    require(wire == payload["native_document"], "UI_trace_exact_native_roundtrip_required")
    replay = SoftwareVerificationSyntaxBridge().round_trip(native).to_dict()
    require(replay == payload["bridge"] and replay["expression"] == payload["typed_expression"], "UI_trace_bridge_replay_differs")
    require(wire["kind"] == "finite_prefix" and wire["loop_start"] is None, "UI_trace_requires_incomplete_finite_prefix")
    _array(wire["events"], "prefix_events", nonempty=False, bound=1024)
    clocks = wire["clocks"]
    require(len(clocks) <= 16, "bounded_UI_clocks_required")
    lines = ["structure UIClock where\n  identifier : String\n  domain : String\n  unit : String\n  epoch : String\n  numerator : Nat\n  denominator : Nat",
        "structure UIEvent where\n  identifier : String\n  eventType : String\n  clock : String\n  numerator : Nat\n  denominator : Nat\n  trueAtoms : List String\n  falseAtoms : List String\n  payload : String\n  sourceRefs : List String"]
    clock_values = []
    for clock in clocks:
        n,d = clock["resolution"]["numerator"],clock["resolution"]["denominator"]
        require(n.bit_length() <= 64 and d.bit_length() <= 64, "bounded_UI_clock_resolution_required")
        clock_values.append("{ identifier := " + string(clock["clock_id"]) + ", domain := " + string(clock["domain"]) + ", unit := " + string(clock["unit"]) + ", epoch := " + string(clock["epoch"]) + f", numerator := {n}, denominator := {d}" + " }")
    lines.append("def declaredClocks : List UIClock := [" + ", ".join(clock_values) + "]")
    events = []
    for event in wire["events"]:
        n,d = event["time"]["value"]["numerator"],event["time"]["value"]["denominator"]
        require(n.bit_length() <= 64 and d.bit_length() <= 64, "bounded_UI_event_time_required")
        events.append("{ identifier := " + string(event["event_id"]) + ", eventType := " + string(event["event_type"]) + ", clock := " + string(event["time"]["clock_id"]) + f", numerator := {n}, denominator := {d}, trueAtoms := " + _strings(event["propositions"]) + ", falseAtoms := " + _strings(event["false_propositions"]) + ", payload := " + string(_raw(event["payload"])) + ", sourceRefs := " + _strings(event["source_ref_ids"]) + " }")
    policy = wire["observation_policy"]
    lines += ["def observedEvents : List UIEvent := [" + ", ".join(events) + "]",
        "def primaryClock : String := " + string(wire["primary_clock_id"]),
        "def traceKind : String := \"finite_prefix\"", "def completeWorkflowAsserted : Bool := false",
        "def traceMetadata : String := " + string(_raw(wire["metadata"])),
        "def observationPolicy : String := " + string(policy["kind"]),
        "def observationPolicyId : String := " + string(policy["policy_id"]),
        "def visibleAtoms : List String := " + _strings(policy["visible_propositions"]),
        "def eventAt (position : Nat) : Option UIEvent := observedEvents[position]?",
        "def observation (position : Nat) (atom : String) : Option Bool :=\n  match eventAt position with\n  | none => none\n  | some event =>\n    if atom ∈ event.trueAtoms then some true\n    else if atom ∈ event.falseAtoms then some false\n    else " + ("some false" if policy["kind"] == "closed_world" else "if atom ∈ visibleAtoms then some false else none" if policy["kind"] == "projected" else "none"),
        "def atOrBefore (left right : UIEvent) : Prop := left.clock = right.clock ∧ left.numerator * right.denominator ≤ right.numerator * left.denominator",
        f"theorem boundary_is_unknown (atom : String) : observation {len(events)} atom = none := by simp [observation, eventAt, observedEvents]"]
    return "\n".join(lines), _details(payload, "TraceIR_exact_roundtrip_bridge_and_observation_policy", ["finite_prefix", "ordered_events", "exact_rational_time", "three_valued_observation:" + policy["kind"]], [
        "Observed positions retain the native policy: explicit, closed-world, or projected; positions beyond the prefix always remain unknown.",
        "Event index is order, not clock time. Rational clock units, resolution, epoch and equal-time order are retained.",
        "Event payload and trace metadata are retained opaque annotations, not interpreted authority or independently attested occurrences.",
        "No infinite future, complete workflow, temporal satisfaction or runtime event truth is asserted."], trace_id=native.trace_id, events=len(events),
        observation_policy=policy["kind"], future_observation="unknown", capability_floor_eligible=False,
        provided_capabilities=["finite_prefix_observation_semantics"],
        missing_capabilities=["temporal_formula_semantics"])


def emit_projection(row, *, report=None):
    """Return a supported declaration; unrelated routes delegate via NotImplementedError."""
    routes = {
        "ui_ux_ir:interface_bindings": ("frame_logic", "ui-verified-interface-bindings/v1", interface_bindings),
        "ui_ux_ir:dcec": ("dcec", "ui-dcec-compilation/v1", cognitive),
        "ui_ux_ir:tdfol": ("tdfol", "ui-tdfol-compilation/v1", deontic),
        "ui_ux_ir:event_calculus": ("event_calculus", "ui-event-calculus-compilation/v1", declared_edges),
        "ui_ux_ir/event_prefix/native/v2": ("temporal", "finite_trace", trace_prefix),
    }
    if row.get("projection_id") not in routes:
        raise NotImplementedError
    family, profile, render = routes[row["projection_id"]]
    require(row.get("logic_family") == family and row.get("profile") == profile, "UI_projection_route_identity_differs")
    return render(row["payload"])


__all__ = ["emit_projection"]
