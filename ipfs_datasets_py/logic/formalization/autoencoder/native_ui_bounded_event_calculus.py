"""Source-bound finite discrete EC with explicitly supplied signed occurrences.

An authored prefix is a declaration, not authenticated history. Exact clocks,
initial fluents, occurrence completeness and successor/inertia conventions are
caller inputs. Unknown observations, conflicting effects and timeouts fail closed.
"""
from dataclasses import dataclass
import importlib
import json

from . import family_training as core
from . import native_family_lean_emitters as lean
from . import native_ui_guarded_lean as guards
from . import ui_source_contract_384_v4 as previous
from ...software_verification import trace
from ...parsers import event_calculus as syntax

SCHEMA = "native-ui-bounded-discrete-event-calculus/v1"
EVIDENCE_SCHEMA = "ui-bounded-discrete-ec-interpretation/v1"
PROJECTION_ID = "ui_ux_ir/explicit_guards/bounded_event_calculus/v1"
PROFILE = "explicit_ui_bounded_discrete_event_calculus/v1"
REPORT_SCHEMA = "ui-bounded-event-family-training-targets/v1"
POLICY = {"declaration_scope": "caller_declared_prefix_not_authenticated_occurrences",
    "time_semantics": "explicit_discrete_clock_ticks",
    "effect_timing": "next_resolution_tick",
    "inertia": "persists_unless_terminated",
    "event_multiplicity": "at_most_one_transition_per_tick",
    "occurrence_completeness": "explicit_positive_or_negative_for_every_transition_each_tick",
    "initial_fluents": "exact_declared_single_initial_control_state",
    "unknown_boundary": "happenings_unknown_at_prefix_end_state_known_one_successor_then_unknown",
    "conflicting_effects": "reject", "self_loop_effects": "reject"}
require, wire, digest = guards.require, guards.wire, guards.digest
_PINS = {name: sha for module in (core, lean, guards, previous, trace, syntax, importlib.import_module(__name__))
         for name, sha in core._pin(module).items()}


def producer_pins():
    from ....optimizers.logic_theorem_optimizer.autoencoder_schema_lake import _pin_imported_module
    for name, sha in _PINS.items():
        require(_pin_imported_module(importlib.import_module(name)) == sha, "bounded UI EC producer changed: " + name)
    return dict(_PINS)


def occurrence_key(transition_id):
    return "ui-transition:" + transition_id.encode("utf-8").hex()


@dataclass(frozen=True, slots=True)
class UIBoundedECInterpretation:
    _encoded: bytes

    def __post_init__(self):
        require(type(self._encoded) is bytes and 0 < len(self._encoded) <= 262144,
                "bounded immutable EC interpretation required")
        value = json.loads(self._encoded)
        previous.previous._closed(value, {"schema", "source_sha256", "candidate_sha256", "behavior_sha256",
            "guard_sha256", "policy", "origin", "initial_true_fluents", "trace"}, "bounded EC declaration")
        require(value["schema"] == EVIDENCE_SCHEMA and value["policy"] == POLICY,
                "complete explicit bounded EC policy required")
        for name in ("source_sha256", "candidate_sha256", "behavior_sha256", "guard_sha256"):
            require(type(value[name]) is str and len(value[name]) == 64 and
                all(c in "0123456789abcdef" for c in value[name]), "exact bounded EC binding hash required")
        require(type(value["origin"]) is int and 0 <= value["origin"] <= 10**9,
                "explicit nonnegative integer clock origin required")
        require(type(value["initial_true_fluents"]) is list and len(value["initial_true_fluents"]) == 1 and
            type(value["initial_true_fluents"][0]) is str, "explicit single initial fluent required")
        native = trace.TraceIR.from_dict(value["trace"])
        require(native.to_dict() == value["trace"], "complete native trace wire required; no defaults inferred")
        require(wire(value) == self._encoded, "canonical bounded EC interpretation bytes required")

    @classmethod
    def from_dict(cls, value): return cls(wire(value))

    def to_dict(self): return json.loads(self._encoded)


def _shape(node):
    """Inspect parser-owned constructors, arity, polarity and typed Time terms."""
    kind = node.kind.value
    if kind == "extension":
        ext = node.extension
        require(ext.family.value == "event_calculus" and ext.payload_schema == syntax.EVENT_CALCULUS_ATOM_PAYLOAD_SCHEMA,
                "actual native EC extension required")
        require(ext.payload["arity"] == len(ext.children), "native EC extension arity differs")
        return ["ec", ext.payload["kind"], *[_shape(child) for child in ext.children]]
    if kind == "constant":
        if "literal" in node.metadata:
            require(node.sort.name == "Time" and str(node.metadata["literal"]).isdigit(), "native integer Time term required")
            return ["time", int(node.metadata["literal"])]
        require(node.sort.name == "Object", "native EC constant sort convention differs")
        return ["constant", node.symbol]
    if kind == "variable": return ["variable", node.symbol, node.sort.name]
    if kind == "predicate": return ["predicate", node.symbol, *[_shape(child) for child in node.arguments]]
    if kind == "forall": return [kind, [[b.name, b.sort.name] for b in node.binders], *[_shape(c) for c in node.arguments]]
    require(kind in {"true", "false", "not", "and", "or", "implies", "iff"}, "unsupported EC AST constructor")
    return [kind, *[_shape(child) for child in node.arguments]]


def _parsed(text, expected):
    first, second, equal = syntax.parse_print_parse(text)
    require(first.ok and second.ok and equal and _shape(first.root) == expected and _shape(second.root) == expected,
            "independent native EC AST/operator/argument/Time replay differs")
    require(not syntax.free_variables(first.root), "native EC formula has unbound variables")
    return {"formula": text, "canonical_formula": first.printed, "checked_ast": expected,
        "typed_role_scope": "operator_positions_and_reversible_event_fluent_tables_Time_native_sort",
        "native_constant_sort": "Object", "parse_print_parse_exact": True}


def _fact(kind, terms, truth):
    rendered = ", ".join(str(value) for value in terms)
    expected = ["ec", kind, *[["time", x] if type(x) is int else ["constant", x] for x in terms]]
    text = kind + "(" + rendered + ")"
    if not truth: text, expected = "not " + text, ["not", expected]
    return _parsed(text, expected)


def prepare_payload(source_text, target, behavior_interpretation, guard_interpretation, event_interpretation):
    pins = producer_pins()
    require(type(event_interpretation) is UIBoundedECInterpretation, "immutable explicit bounded EC interpretation required")
    guarded = guards.prepare_guarded_payload(source_text, target, behavior_interpretation, guard_interpretation)
    declaration = event_interpretation.to_dict()
    expected_hashes = {"source_sha256": guards.ui.previous._source(source_text), "candidate_sha256": digest(target),
        "behavior_sha256": digest(behavior_interpretation.to_dict()), "guard_sha256": digest(guard_interpretation.to_dict())}
    require(all(declaration[name] == value for name, value in expected_hashes.items()), "bounded EC source/model/guard binding differs")
    model = behavior_interpretation.to_dict()["behavior_model"]
    states = sorted(row["state_id"] for row in model["states"])
    edges = sorted(model["transitions"], key=lambda row: row["transition_id"])
    require(len(states) <= 32 and len(edges) <= 8, "bounded EC requires at most32 fluents and8 transitions")
    require(all(row["source_state_ids"][0] != row["target_state_id"] for row in edges),
            "EC self-loop initiation/termination conflict requires additional semantics")
    require(declaration["initial_true_fluents"] == model["initial_state_ids"], "EC initial fluents differ from complete behavior declaration")
    native = trace.TraceIR.from_dict(declaration["trace"])
    require(native.kind.value == "finite_prefix" and native.loop_start is None and len(native.clocks) == 1,
            "one explicit clock and incomplete finite prefix required")
    clock = native.clocks[0]
    require(type(clock.epoch) is str and bool(clock.epoch.strip()),
            "explicit nonempty clock epoch required")
    require(clock.domain.value == "discrete" and native.observation_policy.kind.value == "explicit",
            "discrete clock and signed explicit observation policy required")
    require(1 <= len(native.events) <= 16 and clock.resolution.denominator == 1,
            "bounded complete integer tick prefix required")
    resolution, origin = clock.resolution.numerator, declaration["origin"]
    require(1 <= resolution <= 10**6, "bounded explicit integer clock resolution required")
    require(origin % resolution == 0, "explicit origin must align with declared clock resolution")
    keys = {occurrence_key(edge["transition_id"]): edge for edge in edges}
    refs = {row["ref_id"] for row in target["document"]["sources"]}
    occurrences, observations = [], []
    for index, event in enumerate(native.events):
        require(event.time.value.denominator == 1 and event.time.value.numerator == origin + index * resolution,
                "prefix ticks must match exact origin plus declared resolution")
        require(event.event_type == "ui_signed_tick" and not event.payload,
                "explicit UI signed-tick observation without opaque behavioral payload required")
        require(event.source_ref_ids and set(event.source_ref_ids) <= refs, "signed tick source references must join original UI source")
        positive, negative = set(event.propositions), set(event.false_propositions)
        require(positive | negative == set(keys) and not positive & negative,
                "unknown or extra occurrence atom: exhaustive explicit signs required")
        require(len(positive) <= 1, "simultaneous UI events/conflicting effects unsupported")
        chosen = keys[next(iter(positive))]["transition_id"] if positive else None
        occurrences.append(chosen)
        observations.append({"tick": index, "clock_time": origin + index * resolution,
            "positive": sorted(positive), "negative": sorted(negative), "transition_id": chosen})
    initial_values = {row["variable_id"]: row["initial_value"] for row in guard_interpretation.to_dict()["variables"]}
    expressions = {row["native_guard"]["guard_id"]: row["expression"] for row in guarded["all_declared_guards"]}
    enabled = {edge["transition_id"]: guards.evaluate_expression(expressions[edge["guard_id"]], initial_values)
               if edge["guard_id"] else True for edge in edges}
    by_id = {edge["transition_id"]: edge for edge in edges}
    values = [list(declaration["initial_true_fluents"])]
    effects = []
    for tick, occurrence in enumerate(occurrences):
        before = set(values[-1])
        require(len(before) == 1, "one-hot UI control fluent invariant differs")
        if occurrence is not None:
            edge = by_id[occurrence]
            require(enabled[occurrence] and edge["source_state_ids"][0] in before,
                    "positive occurrence has false guard or wrong source state")
        initiations, terminations = set(), set()
        for edge in edges:
            possible = enabled[edge["transition_id"]] and edge["source_state_ids"][0] in before
            for fluent in states:
                starts = possible and fluent == edge["target_state_id"]
                stops = possible and fluent == edge["source_state_ids"][0]
                effects.append({"tick": tick, "transition_id": edge["transition_id"], "fluent": fluent,
                    "initiates": starts, "terminates": stops})
                if occurrence == edge["transition_id"]:
                    if starts: initiations.add(fluent)
                    if stops: terminations.add(fluent)
        require(not initiations & terminations, "simultaneous initiation/termination conflict")
        after = sorted(initiations | (before - terminations))
        require(len(after) == 1, "EC successor violates one-hot UI control invariant")
        values.append(after)
    event_symbols = {edge["transition_id"]: "e_" + wire([edge["transition_id"], edge["event_id"]]).hex() for edge in edges}
    fluent_symbols = {name: "f_" + name.encode().hex() for name in states}
    formulas = []
    t = ["variable", "t", "Time"]
    for edge in edges:
        e = event_symbols[edge["transition_id"]]
        before = fluent_symbols[edge["source_state_ids"][0]]
        truth = "true" if enabled[edge["transition_id"]] else "false"
        for kind, fluent in (("initiates", edge["target_state_id"]), ("terminates", edge["source_state_ids"][0])):
            f = fluent_symbols[fluent]
            text = f"forall t:Time. in_prefix(t) implies ({kind}({e}, {f}, t) iff (holds_at({before}, t) and {truth}))"
            expected = ["forall", [["t", "Time"]], ["implies", ["predicate", "in_prefix", t],
                ["iff", ["ec", kind, ["constant", e], ["constant", f], t],
                    ["and", ["ec", "holds_at", ["constant", before], t], [truth]]]]]
            formulas.append(_parsed(text, expected))
    for tick, occurrence in enumerate(occurrences):
        for identity, symbol in event_symbols.items():
            formulas.append(_fact("happens", (symbol, origin + tick * resolution), identity == occurrence))
    for tick, true_fluents in enumerate(values):
        for name, symbol in fluent_symbols.items():
            formulas.append(_fact("holds_at", (symbol, origin + tick * resolution), name in true_fluents))
    payload = {"schema": SCHEMA, "source_text": source_text, "candidate": target,
        "behavior_interpretation": behavior_interpretation.to_dict(), "guard_interpretation": guard_interpretation.to_dict(),
        "event_interpretation": declaration, "guarded_payload_sha256": digest(guarded), "clock": clock.to_dict(),
        "origin": origin, "resolution": resolution, "states": states, "edges": edges, "enabled_guards": enabled,
        "occurrences": occurrences, "observations": observations, "fluent_values": values, "effect_table": effects,
        "event_symbols": event_symbols, "fluent_symbols": fluent_symbols, "native_ec_formulas": formulas,
        "producer_pins": pins, "source_semantics_verified": False, "event_authenticity_verified": False,
        "actual_runtime_execution": False, "timeout_semantics_inferred": False, "progress_proven": False,
        "admitted": False, "qualified": False,
        "limitations": ["explicit_caller_occurrence_declarations_not_authenticated_history",
            "finite_discrete_complete_signed_prefix_only", "frozen_boolean_parameters_only",
            "no_timeout_simultaneous_event_release_or_self_loop_semantics", "source_fidelity_not_proven",
            "happenings_unknown_at_prefix_end_state_known_one_successor_then_unknown", "actual_Lake_execution_required"]}
    require(len(wire(payload)) <= 4 * 1024 * 1024, "bounded EC payload capacity exceeded; no pruning")
    producer_pins()
    return json.loads(wire(payload))


def _strings(values): return "[" + ", ".join(lean.string(v) for v in values) + "]"
def _bool(value): return str(value).lower()


def _lean(payload):
    rows = payload["occurrences"]
    lines = ["structure ECEdge where", "  identity : String", "  source : String", "  target : String",
        "  guardEnabled : Bool", "  deriving DecidableEq, Repr", "def edges : List ECEdge := [" + ", ".join(
            "⟨" + ", ".join((lean.string(e["transition_id"]), lean.string(e["source_state_ids"][0]),
                lean.string(e["target_state_id"]), _bool(payload["enabled_guards"][e["transition_id"]]))) + "⟩"
            for e in payload["edges"]) + "]", "def knownFluents : List String := " + _strings(payload["states"]),
        "def initialFluents : List String := " + _strings(payload["fluent_values"][0]),
        "def signedOccurrences : List (Option String) := [" + ", ".join("none" if e is None else "some " + lean.string(e) for e in rows) + "]",
        "def declaredClock : String := " + lean.string(wire(payload["clock"]).decode()),
        "def eventSymbolTable : String := " + lean.string(wire(payload["event_symbols"]).decode()),
        "def fluentSymbolTable : String := " + lean.string(wire(payload["fluent_symbols"]).decode()),
        f"def origin : Nat := {payload['origin']}", f"def resolution : Nat := {payload['resolution']}",
        "def cause (before : List String) (event fluent : String) (initiate : Bool) : Bool :=\n"
        "  edges.any fun e => e.identity == event && e.guardEnabled && before.contains e.source &&\n"
        "    (if initiate then e.target == fluent else e.source == fluent)",
        "def stepFluents (before : List String) (event : Option String) : List String :=\n"
        "  knownFluents.filter fun f =>\n"
        "    event.any (fun e => cause before e f true) ||\n"
        "    (before.contains f && !(event.any (fun e => cause before e f false)))",
        "def fluentAt : Nat → List String\n  | 0 => initialFluents\n"
        "  | n + 1 => stepFluents (fluentAt n) ((signedOccurrences[n]?).getD none)",
        "def tickIndex (time : Nat) : Option Nat :=\n"
        "  if origin ≤ time ∧ (time - origin) % resolution = 0 then some ((time - origin) / resolution) else none",
        "def happens (event : String) (time : Nat) : Option Bool := do\n"
        "  let tick ← tickIndex time\n  let occurrence ← signedOccurrences[tick]?\n"
        "  if edges.any (fun e => e.identity == event) then some (occurrence == some event) else none",
        "def holdsAt (fluent : String) (time : Nat) : Option Bool := do\n"
        "  let tick ← tickIndex time\n  if tick ≤ signedOccurrences.length ∧ knownFluents.contains fluent = true\n"
        "  then some ((fluentAt tick).contains fluent) else none",
        "def effectAt (event fluent : String) (time : Nat) (initiate : Bool) : Option Bool := do\n"
        "  let tick ← tickIndex time\n  if tick < signedOccurrences.length ∧ knownFluents.contains fluent = true ∧\n"
        "      edges.any (fun e => e.identity == event) = true\n"
        "  then some (cause (fluentAt tick) event fluent initiate) else none",
        "def initiates (event fluent : String) (time : Nat) : Option Bool := effectAt event fluent time true",
        "def terminates (event fluent : String) (time : Nat) : Option Bool := effectAt event fluent time false",
        "def occurrenceEnabled (tick : Nat) : Bool :=\n"
        "  ((signedOccurrences[tick]?).getD none).all fun event =>\n"
        "    edges.any fun e => e.identity == event && e.guardEnabled && (fluentAt tick).contains e.source",
        "theorem successor_inertia (tick : Nat) : fluentAt (tick + 1) =\n"
        "    stepFluents (fluentAt tick) ((signedOccurrences[tick]?).getD none) := rfl"]
    for tick, occurrence in enumerate(rows):
        time = payload["origin"] + tick * payload["resolution"]
        lines.append(f"example : occurrenceEnabled {tick} = true := by decide")
        for edge in payload["edges"]:
            identity = edge["transition_id"]
            lines.append(f"example : happens {lean.string(identity)} {time} = some {_bool(identity == occurrence)} := by decide")
    for tick, values in enumerate(payload["fluent_values"]):
        time = payload["origin"] + tick * payload["resolution"]
        lines.append(f"example : (fluentAt {tick}).length = 1 := by decide")
        for fluent in payload["states"]:
            lines.append(f"example : holdsAt {lean.string(fluent)} {time} = some {_bool(fluent in values)} := by decide")
    for row in payload["effect_table"]:
        time = payload["origin"] + row["tick"] * payload["resolution"]
        for kind in ("initiates", "terminates"):
            lines.append(f"example : {kind} {lean.string(row['transition_id'])} {lean.string(row['fluent'])} {time} = some {_bool(row[kind])} := by decide")
    boundary = payload["origin"] + len(rows) * payload["resolution"]
    for edge in payload["edges"]:
        lines.append(f"example : happens {lean.string(edge['transition_id'])} {boundary} = none := by decide")
    for fluent in payload["states"]:
        lines.append(f"example : holdsAt {lean.string(fluent)} {boundary + payload['resolution']} = none := by decide")
    lines.append("def declaredNativeECFormulas : List String := " + _strings([r["formula"] for r in payload["native_ec_formulas"]]))
    return "\n".join(lines)


def emit_projection(row, *, report=None):
    is_ec = row.get("projection_id") == PROJECTION_ID
    is_old_guard = (type(report) is dict and report.get("schema") == REPORT_SCHEMA and
        row.get("projection_id", "").startswith(guards.PREFIX))
    if not is_ec and not is_old_guard: raise NotImplementedError
    require(type(report) is dict and report.get("schema") == REPORT_SCHEMA and report.get("domain_id") == "ui_ux_ir" and
        row.get("source_digest") == report.get("source_digest") and sum(p == row for p in report.get("projections", [])) == 1,
        "exact live bounded EC report/domain/source/row binding required")
    from . import ui_source_contract_384_v5 as adapter
    binding = report["bounded_event_source_binding"]
    options = {"behavior_interpretation": previous.UIBehaviorInterpretation.from_dict(binding["behavior_interpretation"]),
        "guard_interpretation": previous.UIGuardInterpretation.from_dict(binding["guard_interpretation"]),
        "event_interpretation": UIBoundedECInterpretation.from_dict(binding["event_interpretation"])}
    adapter.validate_family_training_report(report, source_text=binding["source_text"], target=binding["candidate"],
        requested_families=report["requested_families"], **options)
    if not is_ec:
        old = previous.prepare_family_targets(binding["source_text"], binding["candidate"], report["requested_families"],
            behavior_interpretation=options["behavior_interpretation"], guard_interpretation=options["guard_interpretation"])
        matches = [p for p in old["report"]["projections"] if p["projection_id"] == row["projection_id"]]
        require(len(matches) == 1 and matches[0]["payload"] == row["payload"], "exact preserved v4 guard row required")
        source, checks = guards.emit_projection(matches[0], report=old["report"])
        checks = dict(checks, preserved_v4_report_sha256=old["report"]["report_sha256"],
            bounded_ec_report_sha256=report["report_sha256"], preserved_payload_sha256=digest(row["payload"]))
        return source, checks
    require(row.get("logic_family") == "event_calculus" and row.get("profile") == PROFILE,
            "bounded EC projection route differs")
    expected = prepare_payload(binding["source_text"], binding["candidate"], **options)
    require(expected == row["payload"], "complete bounded EC projection replay differs")
    return _lean(expected), {"validator": "native_EC_AST_and_signed_discrete_inertia_complete_source_replay",
        "operators": ["Happens", "HoldsAt", "Initiates", "Terminates", "discrete_successor_inertia", "explicit_initial_fluents"],
        "capability_floor_eligible": True, "capability_scope": "explicit_bounded_discrete_EC_with_complete_signed_occurrences",
        "assumptions": expected["limitations"], "source_semantics_verified": False,
        "event_authenticity_verified": False, "timeout_semantics_inferred": False,
        "native_formula_count": len(expected["native_ec_formulas"]), "exhaustive_effect_cell_count": len(expected["effect_table"]),
        "signed_occurrence_tick_count": len(expected["occurrences"]), "syntax_requirements": []}


__all__ = ["UIBoundedECInterpretation", "prepare_payload", "emit_projection", "producer_pins", "occurrence_key"]
