"""Source-bound finite Intent guards/effects with exact native state replay.

The explicit bindings interpret native predicates inside a supplied finite
model. They do not verify code, assert goals, or prove normative compliance.
Published enumerators and equality-state lowerings are deliberately unchanged.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import importlib
import json

from . import family_training as core
from . import native_family_lean_emitters as lean
from . import native_tla_projection as tla
from ...intent_ir import schema, decoder, canonicalize
from ...intent_ir.formalize import guarded_workflow as guarded
from ...intent_ir.formalize import state_projections, workflow_state, projection_contracts
from ...software_verification import state as state_types, transitions

SCHEMA = "native-intent-guarded-projection/v1"
BINDING_SCHEMA = "intent-guarded-effect-bindings/v1"
PREFIX = "intent_ir/guarded/"
KINDS = ("state", "workflow", "action_contract", "tla_plus")
ROUTES = {"state": ("transition_system", "guarded_intent_state/v1"),
    "workflow": ("temporal", "guarded_intent_workflow/v1"),
    "action_contract": ("program", "guarded_intent_action_contract/v1"),
    "tla_plus": ("transition_system", "tla_plus")}
_PINS = {name: sha for module in (core, lean, tla, schema, decoder, canonicalize,
    guarded, state_projections, workflow_state, projection_contracts, state_types,
    transitions, importlib.import_module(__name__)) for name, sha in core._pin(module).items()}


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def producer_pins():
    from ....optimizers.logic_theorem_optimizer.autoencoder_schema_lake import _pin_imported_module
    for name, sha in _PINS.items():
        _require(_pin_imported_module(importlib.import_module(name)) == sha,
                 "guarded Intent producer drift: " + name)
    return dict(_PINS)


@dataclass(frozen=True)
class IntentEffectBindings:
    """Immutable, explicitly authored interpretations for native effect IDs."""
    _canonical_json: str

    @classmethod
    def from_dict(cls, value):
        _require(type(value) is dict and set(value) == {"schema", "source_ir_sha256", "bindings"}
                 and value["schema"] == BINDING_SCHEMA, "closed guarded effect binding schema required")
        _require(type(value["source_ir_sha256"]) is str and len(value["source_ir_sha256"]) == 64,
                 "effect binding source digest required")
        rows = value["bindings"]
        _require(type(rows) is list and len(rows) <= 128, "bounded effect binding list required")
        seen = set()
        for row in rows:
            _require(type(row) is dict and set(row) == {"statement_id", "expression", "evidence_ref"},
                     "closed effect binding row required")
            _require(type(row["statement_id"]) is str and row["statement_id"] not in seen,
                     "unique effect statement bindings required")
            seen.add(row["statement_id"])
        raw = _json(value)
        _require(len(raw.encode()) <= 32768, "bounded effect bindings required")
        return cls(raw)

    def to_dict(self):
        return json.loads(self._canonical_json)


def _document(value):
    document = value if type(value) is schema.IntentIRDocument else decoder.decode_intent_ir(value)
    _require(type(document) is schema.IntentIRDocument, "native IntentIR document required")
    document.validate()
    wire = json.loads(canonicalize.canonical_intent_ir_bytes(document))
    _require(len(_json(wire).encode()) <= 128 * 1024, "bounded native Intent document required")
    if type(value) is dict:
        _require(_json(value) == _json(wire), "complete canonical native Intent document required")
    return document, wire


def _effect_rows(document, effect_bindings, variables, predicate_bindings):
    _require(type(effect_bindings) is IntentEffectBindings, "explicit immutable IntentEffectBindings required")
    wire = IntentEffectBindings.from_dict(effect_bindings.to_dict()).to_dict()
    _require(wire["source_ir_sha256"] == projection_contracts.source_ir_sha256(document),
             "effect bindings must match complete native Intent source")
    statements = {s.statement_id: s for s in document.statements}
    required = {sid for action in document.actions for sid in action.effect_ids}
    _require({r["statement_id"] for r in wire["bindings"]} == required,
             "exactly every native action effect requires a binding")
    expressions = dict(predicate_bindings)
    for row in wire["bindings"]:
        statement = statements[row["statement_id"]]
        _require(statement.kind in (schema.StatementKind.EFFECT, schema.StatementKind.POSTCONDITION)
                 and statement.modality is schema.IntentModality.ASSERTED,
                 "effect binding requires asserted native EFFECT or POSTCONDITION")
        guarded._reference(row["evidence_ref"], statement.source_ref_ids, "effect binding")
        guarded._expression(row["expression"], variables)
        expressions[row["statement_id"]] = row["expression"]
    meanings = {}
    for sid, expression in expressions.items():
        statement = statements[sid]
        _require(statement.predicate and len(statement.arguments) <= 32,
                 "explicit bounded native condition predicate required")
        identity = (statement.predicate, tuple(statement.arguments))
        meaning = _json(expression)
        _require(identity not in meanings or meanings[identity] == meaning,
                 "conflicting binding for same predicate and ordered arguments")
        meanings[identity] = meaning
    return wire, expressions


def _effect_checks(document, graph, updates, expressions):
    actions = {a.action_id: a for a in document.actions}
    configurations = {c["position"]: c for c in graph["configurations"]}
    edges = Counter((r["from_position"], r["to_position"], r["intent_action_id"])
                    for r in graph["transitions"] if r["transition_kind"] == "action")
    expected = Counter(); checks = []; enabled = set()
    for before in graph["configurations"]:
        if before["phase"] != "ready":
            continue
        action = actions[before["action_id"]]
        if not all(guarded._evaluate(expressions[sid], before["values"]) for sid in action.precondition_ids):
            continue
        enabled.add(action.action_id)
        for index, patch in enumerate(updates[action.action_id]):
            after_values = {**before["values"], **patch}
            after_phase = "done" if action.action_id in document.terminal_action_ids else "routing"
            matches = [c for c in configurations.values() if c["phase"] == after_phase
                and c["action_id"] == action.action_id and c["values"] == after_values
                and c["retry_counts"] == before["retry_counts"]]
            _require(len(matches) == 1, "every configured enabled outcome must have exact native successor")
            after = matches[0]
            expected[(before["position"], after["position"], action.action_id)] += 1
            results = [{"statement_id": sid, "expression": expressions[sid],
                        "passed": guarded._evaluate(expressions[sid], after_values)} for sid in action.effect_ids]
            checks.append({"action_id": action.action_id, "outcome_index": index,
                "from_position": before["position"], "to_position": after["position"],
                "simultaneous_update": patch, "before_values": before["values"], "after_values": after_values,
                "effects": results, "passed": all(r["passed"] for r in results)})
    _require(edges == expected, "native action graph must retain every configured reachable outcome")
    return checks, sorted(set(actions) - enabled)


def _kernel(native):
    """Remove only replay-verified provenance from the operational state model."""
    wire = native.to_dict()
    removed = {"metadata": wire["metadata"], "schema_metadata": wire["schema"]["metadata"],
               "action_attributes": {a["action_id"]: a["attributes"] for a in wire["actions"]}}
    wire["metadata"] = {}; wire["schema"]["metadata"] = {}
    wire["schema"].pop("schema_id", None)
    for action in wire["actions"]:
        action["attributes"] = {}
    # document_id is content-derived, not an independent semantic declaration.
    wire.pop("document_id", None)
    return transitions.StateTransitionIR.from_dict(wire), removed


def prepare_guarded_payload(document, context, effect_bindings):
    """Preserve complete counterexamples; readiness is a separate strict result."""
    pins = producer_pins()
    document, wire = _document(document)
    _require(type(context) is dict and len(_json(context).encode()) <= 65536,
             "bounded explicit guarded context required")
    context = deepcopy(context)
    options = state_projections._options(context)
    premise = options["workflow"]
    parts = guarded._premises(document, premise)
    variables, _, _, _, predicates, updates, _, _, _ = parts
    effects, expressions = _effect_rows(document, effect_bindings, variables, predicates)
    graph = guarded.guarded_workflow_graph(document, premise, options["max_steps"])
    native, origins = guarded.guarded_workflow_state(document, graph, options)
    checks, unreachable = _effect_checks(document, graph, updates, expressions)
    kernel, removed = _kernel(native)
    artifact = tla.compile_bounded_state(kernel, max_steps=options["max_steps"])
    ready = graph["deadlock_free"] and not unreachable and all(c["passed"] for c in checks)
    bindings = [{"statement_id": sid, "native_statement": next(s.to_dict() for s in document.statements if s.statement_id == sid),
                 "expression": expression} for sid, expression in sorted(expressions.items())]
    payload = {"schema": SCHEMA, "native_document": wire, "context": context, "effect_bindings": effects,
        "native_document_sha256": projection_contracts.source_ir_sha256(document), "graph": graph,
        "native_state": native.to_dict(), "state_origins": origins,
        "normalized_state": kernel.to_dict(), "retained_normalization_provenance": removed,
        "bounded_tla": artifact, "predicate_bindings": bindings, "effect_checks": checks,
        "unreachable_actions": unreachable, "ready_for_training": ready, "producer_pins": pins,
        "interpretation_scope": "caller_supplied_finite_predicate_model_not_source_code_equivalence",
        "source_semantics_verified": False, "code_effects_verified": False,
        "normative_compliance_verified": False, "goals_asserted_true": False,
        "admitted": False, "roundtrip_ok": False, "qualified": False,
        "limitations": [*guarded.ASSUMPTIONS, "Effect checks cover all reachable enabled configured outcomes; unreachable actions block readiness.",
            "The supplied predicate interpretations do not establish world facts or source-code behavior.",
            "Global declared and temporal stuttering remain separate from the explicit nonterminal deadlock scan."]}
    producer_pins()
    return payload


def _value(value):
    if type(value) is bool:
        return "(.boolean " + ("true" if value else "false") + ")"
    if type(value) is int:
        return "(.integer (" + str(value) + "))"
    return "(.enumeration " + lean.string(value) + ")"


def _values(values):
    return "[" + ", ".join("(" + lean.string(k) + ", " + _value(v) + ")" for k, v in sorted(values.items())) + "]"


def _expression(expression, values="values"):
    op = expression["op"]
    if op == "literal":
        return "true" if expression["value"] else "false"
    if op in ("eq", "ne"):
        text = "(lookup " + values + " " + lean.string(expression["variable_id"]) + " == some " + _value(expression["value"]) + ")"
        return text if op == "eq" else "(!" + text + ")"
    if op == "not":
        return "(!" + _expression(expression["arg"], values) + ")"
    return "(" + (" && " if op == "and" else " || ").join(_expression(arg, values) for arg in expression["args"]) + ")"


def _lean_semantics(payload):
    """Render actual finite predicates/updates and check their source joins."""
    graph, premise = payload["graph"], payload["context"]["state"]["workflow"]
    source = payload["bounded_tla"]["lean_source"]
    lines = [source, "namespace GuardedIntent", "inductive Value where", "  | boolean : Bool → Value",
        "  | integer : Int → Value", "  | enumeration : String → Value", "  deriving DecidableEq, BEq, Repr",
        "abbrev Values := List (String × Value)",
        "def lookup (values : Values) (key : String) : Option Value := (values.find? fun p => p.1 == key).map Prod.snd",
        "def update (values patch : Values) : Values := values.map fun p => (p.1, (lookup patch p.1).getD p.2)",
        "structure Configuration where", "  position : String", "  phase : String", "  actionId : String",
        "  values : Values", "  retries : List (String × Nat)", "  terminal : Bool", "  deriving DecidableEq, BEq, Repr"]
    configs = graph["configurations"]
    indices = {c["position"]: i for i, c in enumerate(configs)}
    for index, c in enumerate(configs):
        retries = "[" + ", ".join("(" + lean.string(k) + ", " + str(v) + ")" for k, v in sorted(c["retry_counts"].items())) + "]"
        lines.append(f"def configuration{index} : Configuration := ⟨" + ", ".join((lean.string(c["position"]),
            lean.string(c["phase"]), lean.string(c["action_id"] or ""), _values(c["values"]), retries,
            "true" if c["terminal"] else "false")) + "⟩")
    lines.append("def configurations : List Configuration := [" + ", ".join("configuration" + str(i) for i in range(len(configs))) + "]")
    binding_names = {}
    for index, row in enumerate(payload["predicate_bindings"]):
        name = "condition" + str(index); binding_names[row["statement_id"]] = name
        lines.append("def " + name + " (values : Values) : Bool := " + _expression(row["expression"]))
        record = row["native_statement"]
        lines.append(f"def {name}Source : String × String × List String := (" + lean.string(row["statement_id"]) + ", "
            + lean.string(record["predicate"]) + ", [" + ", ".join(lean.string(a) for a in record["arguments"]) + "])")
    actions = {a["action_id"]: a for a in payload["native_document"]["actions"]}
    for index, check in enumerate(payload["effect_checks"]):
        before = "configuration" + str(indices[check["from_position"]]); after = "configuration" + str(indices[check["to_position"]])
        action = actions[check["action_id"]]
        terms = [f"({before}.phase == \"ready\")", f"({before}.actionId == {lean.string(check['action_id'])})",
            f"({after}.actionId == {before}.actionId)", f"({after}.retries == {before}.retries)",
            f"({after}.values == update {before}.values {_values(check['simultaneous_update'])})",
            f"({after}.phase == " + lean.string("done" if check["action_id"] in payload["native_document"]["terminal_action_ids"] else "routing") + ")"]
        terms += [binding_names[sid] + " " + before + ".values" for sid in action["precondition_ids"]]
        terms += [binding_names[sid] + " " + after + ".values" for sid in action["effect_ids"]]
        lines.append(f"def actionCase{index} : Bool := " + " && ".join("(" + term + ")" for term in terms))
        lines.append(f"theorem action_case_{index}_checks : actionCase{index} = true := by decide")
    # The finite nonterminal scan uses only explicit graph successors, never
    # the TLA box stutter or the generic relation's declared global stutter.
    edges = graph["transitions"]
    native_edges = {e["edge_id"]: e for e in payload["native_document"]["control_edges"]}
    retry_bounds = {r["edge_id"]: r["max_traversals"] for r in premise["retry_bounds"]}
    lines.append("def retryCount (c : Configuration) (edge : String) : Nat := ((c.retries.find? fun p => p.1 == edge).map Prod.snd).getD 0")
    for index, edge in enumerate(edges):
        before = "configuration" + str(indices[edge["from_position"]]); after = "configuration" + str(indices[edge["to_position"]])
        kind = edge["transition_kind"]
        if kind == "action":
            cases = ["actionCase" + str(i) for i, c in enumerate(payload["effect_checks"])
                     if (c["from_position"], c["to_position"], c["action_id"]) ==
                     (edge["from_position"], edge["to_position"], edge["intent_action_id"])]
            terms = ["(" + " || ".join(cases) + ")"]
        elif kind == "initialize":
            terms = [f"({before}.phase == \"initial\")", f"({after}.phase == \"ready\")",
                f"({after}.actionId == " + lean.string(payload["native_document"]["entry_action_ids"][0]) + ")",
                f"({after}.retries.all fun p => p.2 == 0)"]
            for variable in premise["variables"]:
                options = "[" + ", ".join("some " + _value(v) for v in variable["initial_values"]) + "]"
                terms.append("(" + options + ".contains (lookup " + after + ".values " + lean.string(variable["variable_id"]) + "))")
        elif kind == "route":
            native_edge = native_edges[edge["intent_edge_ids"][0]]
            terms = [f"({before}.phase == \"routing\")", f"({after}.phase == \"ready\")",
                f"({before}.actionId == " + lean.string(native_edge["source_action_id"]) + ")",
                f"({after}.actionId == " + lean.string(native_edge["target_action_id"]) + ")",
                f"({before}.values == {after}.values)"]
            if native_edge["guard_statement_id"]:
                terms.append(binding_names[native_edge["guard_statement_id"]] + " " + before + ".values")
            for retry_id, bound in retry_bounds.items():
                b = "retryCount " + before + " " + lean.string(retry_id)
                a = "retryCount " + after + " " + lean.string(retry_id)
                changes = retry_id == native_edge["edge_id"]
                terms.append("(" + a + " == " + b + (" + 1" if changes else "") + ")")
                if changes:
                    terms.append("(decide (" + b + " < " + str(bound) + "))")
        else:
            _require(kind == "terminal_stutter", "unreviewed guarded transition kind")
            terms = [before + ".terminal", f"({before}.phase == \"done\")", f"({before} == {after})"]
        lines.append(f"def graphCase{index} : Bool := " + " && ".join("(" + term + ")" for term in terms))
        lines.append(f"theorem graph_case_{index}_checks : graphCase{index} = true := by decide")
    pairs = "[" + ", ".join("(" + lean.string(e["from_position"]) + ", " + lean.string(e["to_position"]) + ")" for e in edges) + "]"
    lines += ["def explicitSuccessors : List (String × String) := " + pairs,
        "def noAbstractDeadlock : Bool := configurations.all fun c => c.terminal || explicitSuccessors.any (fun e => e.1 == c.position)",
        "theorem complete_model_has_no_deadlock : noAbstractDeadlock = true := by decide"]
    # Every typed native state action is connected to the exact concrete pcs,
    # including initialization, routing and the terminal-only explicit loop.
    native_actions = payload["normalized_state"]["actions"]
    origins = {r["state_action_id"]: r for r in payload["state_origins"]}
    for index, action in enumerate(native_actions):
        origin = origins[action["action_id"]]
        predicate_indices = {p["predicate_id"]: i for i, p in enumerate(payload["normalized_state"]["predicates"])}
        definitions = [f"action_{index}", *["predicate_" + str(predicate_indices[action[key]])
            for key in ("guard_predicate_id", "next_predicate_id")]]
        lines.append(f"theorem kernel_edge_{index} : action_{index} ⟨{lean.string(origin['from_position'])}⟩ ⟨{lean.string(origin['to_position'])}⟩ := by simp [" + ", ".join(definitions) + "]")
    declared = "[" + ", ".join(lean.string(a) for a in actions) + "]"
    enabled = "[" + ", ".join(lean.string(c["action_id"]) for c in payload["effect_checks"]) + "]"
    lines += ["def declaredActions : List String := " + declared, "def enabledActions : List String := " + enabled,
        "def everyActionHasReachableExecution : Bool := declaredActions.all enabledActions.contains",
        "theorem all_actions_reachable : everyActionHasReachableExecution = true := by decide",
        "def callerSuppliedInterpretation : Bool := true", "def sourceCodeEquivalenceVerified : Bool := false",
        "def normativeComplianceVerified : Bool := false", "end GuardedIntent"]
    return "\n".join(lines) + "\n"


def emit_projection(row, *, report=None):
    identity = row.get("projection_id", "")
    if identity not in {PREFIX + kind + "/v1" for kind in KINDS}:
        raise NotImplementedError
    kind = identity[len(PREFIX):].split("/")[0]
    lean.require((row.get("logic_family"), row.get("profile")) == ROUTES[kind],
                 "guarded_Intent_route_family_profile_mismatch")
    payload = row.get("payload")
    lean.require(type(payload) is dict and payload.get("schema") == SCHEMA,
                 "exact_guarded_Intent_payload_required")
    replay = prepare_guarded_payload(payload["native_document"], payload["context"],
                                     IntentEffectBindings.from_dict(payload["effect_bindings"]))
    lean.require(replay == payload, "guarded_Intent_complete_source_replay_differs")
    lean.require(payload["ready_for_training"], "guarded_Intent_deadlock_unreachable_action_or_false_effect")
    artifact = payload["bounded_tla"]
    details = {"validator": "exact_native_guarded_Intent_replay_and_finite_effect_checks",
        "operators": ["typed_predicate_interpretation", "precondition_before_update", "simultaneous_update",
            "effect_after_update", "finite_guarded_state", "separate_routing_phase", "bounded_retry", "explicit_terminal_stutter"],
        "assumptions": payload["limitations"], "retained_native_records": payload["native_document"],
        "source_semantics_verified": False, "capability_floor_eligible": kind != "action_contract" or
            any(a["effect_ids"] for a in payload["native_document"]["actions"]),
        "syntax_requirements": [], "projection_kind": kind}
    if kind == "tla_plus":
        details["syntax_requirements"] = [{"kind": "SANY", "module_name": artifact["module_name"],
                                           "model_text": artifact["model_text"]}]
    return _lean_semantics(payload), details


__all__ = ["IntentEffectBindings", "prepare_guarded_payload", "emit_projection", "producer_pins"]
