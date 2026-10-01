"""Finite, explicitly bounded simulation formulas for native RefinementIR.

The fragment has named states with constant predicates and labelled, nonstutter
edges. It does not assign an invented interpretation to opaque data predicates,
couple constraints, concurrency links, or prose. Native annotations are retained;
the generated propositions are obligations, never asserted source proofs.
"""
from __future__ import annotations

import hashlib
import json

from ...software_verification.refinement import RefinementIR
from .native_family_lean_emitters import require, string

PROFILE = "native-finite-bounded-refinement-lean/v1"

PRELUDE = '''set_option linter.unusedVariables false
structure RefinementNode where
  identifier : String
  enabled : Bool
  initial : Bool
  terminal : Bool
  deriving DecidableEq
structure RefinementEdge where
  identifier : String
  source : String
  target : String
  action : String
  deriving DecidableEq
structure RefinementGraph where
  identifier : String
  nodes : List RefinementNode
  edges : List RefinementEdge
  deriving DecidableEq
def enabledNode (graph : RefinementGraph) (identifier : String) : Bool :=
  graph.nodes.any (fun node => node.identifier == identifier && node.enabled)
def initialNode (graph : RefinementGraph) (identifier : String) : Bool :=
  graph.nodes.any (fun node => node.identifier == identifier && node.enabled && node.initial)
def enabledEdge (graph : RefinementGraph) (edge : RefinementEdge) : Bool :=
  enabledNode graph edge.source && enabledNode graph edge.target
def relatedPair (pairs : List (String × String)) (left right : String) : Bool :=
  pairs.contains (left, right)
-- Exactly one trailing edge matches each leading edge in this nonstutter
-- fragment. The recursion limits the number of leading schedule steps.
def boundedMatch (leading trailing : RefinementGraph) (pairs : List (String × String))
    (matchingLimit : Nat) : Nat → String → String → Bool
  | 0, left, right => enabledNode leading left && enabledNode trailing right && relatedPair pairs left right
  | steps + 1, left, right =>
    enabledNode leading left && enabledNode trailing right && relatedPair pairs left right &&
    leading.edges.all (fun edge =>
      if edge.source == left && enabledEdge leading edge then
        matchingLimit > 0 && trailing.edges.any (fun other =>
          other.source == right && other.action == edge.action && enabledEdge trailing other &&
          boundedMatch leading trailing pairs matchingLimit steps edge.target other.target)
      else true)
def boundedSimulation (leading trailing : RefinementGraph) (pairs : List (String × String))
    (matchingLimit scheduleLimit : Nat) : Bool :=
  leading.nodes.all (fun node =>
    if node.initial && node.enabled then
      trailing.nodes.any (fun other =>
        other.initial && other.enabled &&
        boundedMatch leading trailing pairs matchingLimit scheduleLimit node.identifier other.identifier)
    else true) &&
  pairs.all (fun pair =>
    if enabledNode leading pair.1 && enabledNode trailing pair.2 then
      boundedMatch leading trailing pairs matchingLimit scheduleLimit pair.1 pair.2
    else true)
def declaredStep (graph : RefinementGraph) (left : String) (action : String) (right : String) : Prop :=
  ∃ edge, edge ∈ graph.edges ∧ edge.source = left ∧ edge.action = action ∧
    edge.target = right ∧ enabledEdge graph edge = true
def boundedRun (graph : RefinementGraph) : Nat → String → List String → String → Prop
  | _, left, [], right => left = right ∧ enabledNode graph left = true
  | 0, _, _ :: _, _ => False
  | steps + 1, left, action :: actions, right =>
    ∃ middle, declaredStep graph left action middle ∧ boundedRun graph steps middle actions right
theorem zero_budget_cannot_take_step (graph : RefinementGraph) (left action right : String)
    (actions : List String) : ¬ boundedRun graph 0 left (action :: actions) right := by
  simp [boundedRun]
def sourceProgramRefinementProved : Bool := false
def unboundedRefinementClaimed : Bool := false
'''


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _bool(value):
    return "true" if value else "false"


def _list(values):
    return "[" + ", ".join(values) + "]"


def emit_refinement(payload, *, interpretation=None):
    """Lower exact native declarations, requiring explicit evidence for symbolic data."""
    if interpretation is not None:
        from .native_symbolic_refinement_lean import emit_refinement as emit_symbolic
        return emit_symbolic(payload, interpretation=interpretation)
    require(type(payload) is dict and len(_raw(payload).encode()) <= 512 * 1024,
            "bounded_native_refinement_document_required")
    native = RefinementIR.from_dict(payload)
    require(native.to_dict() == payload, "exact_native_refinement_roundtrip_required")
    require(not payload["metadata"], "refinement_metadata_requires_explicit_interpretation")
    systems, simulations, bounds, obligations = (payload[k] for k in
        ("systems", "simulations", "boundedness", "obligations"))
    require(2 <= len(systems) <= 8 and 1 <= len(simulations) <= 16 and
            1 <= len(bounds) <= 16 and 1 <= len(obligations) <= 32,
            "nonempty_bounded_refinement_systems_relations_and_obligations_required")
    lines = [PRELUDE]
    names = {system["system_id"]: "system_" + str(i) for i, system in enumerate(systems)}
    for system in systems:
        require(not system["attributes"] and not system["concurrency_document_id"],
                "refinement_system_attributes_or_concurrency_link_not_lowered")
        require(1 <= len(system["states"]) <= 64 and len(system["transitions"]) <= 256,
                "bounded_refinement_graph_required")
        states = []
        for state in system["states"]:
            require(not state["attributes"] and state["predicate_statement"] in ("true", "false"),
                    "refinement_state_predicate_requires_typed_interpretation")
            states.append("⟨" + ", ".join((string(state["state_id"]), state["predicate_statement"],
                _bool(state["is_initial"]), _bool(state["is_terminal"]))) + "⟩")
        require(any(state["is_initial"] and state["predicate_statement"] == "true" for state in system["states"]),
                "refinement_requires_satisfiable_initial_state_per_system")
        transitions = []
        for edge in system["transitions"]:
            require(not edge["attributes"] and not edge["is_stutter"],
                    "refinement_stutter_or_edge_attributes_not_lowered")
            transitions.append("⟨" + ", ".join(string(edge[k]) for k in
                ("transition_id", "source_state_id", "target_state_id", "action_label")) + "⟩")
        lines.append("def " + names[system["system_id"]] + " : RefinementGraph := ⟨" +
            string(system["system_id"]) + ", " + _list(states) + ", " + _list(transitions) + "⟩")

    relation_names = {}
    for index, simulation in enumerate(simulations):
        require(not simulation["attributes"] and not simulation["claims_unbounded_refinement"],
                "refinement_relation_extra_or_unbounded_semantics_not_lowered")
        require(simulation["statement"] == "simulation", "refinement_relation_statement_requires_typed_interpretation")
        require(type(simulation["max_matching_steps"]) is int and 1 <= simulation["max_matching_steps"] <= 64,
                "explicit_bounded_refinement_matching_steps_required")
        require(1 <= len(simulation["couples"]) <= 256, "bounded_refinement_couples_required")
        for couple in simulation["couples"]:
            require(not couple["attributes"] and couple["statement"] == "related",
                    "refinement_couple_predicate_requires_typed_interpretation")
        forward = simulation["direction"] == "forward"
        leading = names[simulation["abstract_system_id"] if forward else simulation["concrete_system_id"]]
        trailing = names[simulation["concrete_system_id"] if forward else simulation["abstract_system_id"]]
        left, right = ("abstract_state_id", "concrete_state_id") if forward else ("concrete_state_id", "abstract_state_id")
        pairs = _list("(" + string(c[left]) + ", " + string(c[right]) + ")" for c in simulation["couples"])
        name = "simulation_" + str(index)
        relation_names[simulation["relation_id"]] = name
        lines.append("def " + name + " (scheduleLimit : Nat) : Bool := boundedSimulation " +
            leading + " " + trailing + " " + pairs + " " + str(simulation["max_matching_steps"]) + " scheduleLimit")

    bound_map = {row["boundedness_id"]: row for row in bounds}
    for bound in bounds:
        require(bound["kind"] == "bounded" and not bound["claims_unbounded_refinement"] and not bound["attributes"],
                "finite_refinement_bound_without_extra_claims_required")
        require(bound["statement"] == "bounded simulation", "refinement_bound_statement_requires_typed_interpretation")
        require(type(bound["max_steps"]) is int and 1 <= bound["max_steps"] <= 64 and bound["max_states"] is None,
                "explicit_schedule_bound_without_state_budget_required")
    simulation_map = {row["relation_id"]: row for row in simulations}
    obligation_symbols = {}
    for index, obligation in enumerate(obligations):
        require(obligation["kind"] == "simulation" and not obligation["attributes"] and not obligation["claims_unbounded_refinement"],
                "bounded_simulation_obligation_only")
        require(obligation["statement"] == "simulation", "refinement_obligation_statement_requires_typed_interpretation")
        require(obligation["boundedness_id"] in bound_map and obligation["simulation_relation_id"] in relation_names,
                "obligation_requires_exact_bound_and_relation")
        simulation = simulation_map[obligation["simulation_relation_id"]]
        require(all(obligation[key] == simulation[key] for key in ("abstract_system_id", "concrete_system_id")),
                "obligation_system_pair_differs_from_simulation_relation")
        name = "obligation_" + str(index)
        expression = relation_names[obligation["simulation_relation_id"]] + " " + str(bound_map[obligation["boundedness_id"]]["max_steps"])
        lines.append("def " + name + " : Prop := " + expression + " = true")
        lines.append("def " + name + "_check : Bool := " + expression)
        obligation_symbols[obligation["obligation_id"]] = name
    # Descriptive names/statements, IDs and predicate spelling remain bound to
    # the emitted structured semantics. This is an audit supplement, not its body.
    lines.append("def nativeRefinementDeclaration : String := " + string(_raw(payload)))
    return "\n\n".join(lines), {
        "profile": PROFILE, "validator": "RefinementIR_exact_closed_finite_graph_bounded_simulation",
        "payload_sha256": hashlib.sha256(_raw(payload).encode()).hexdigest(),
        "operators": ["enabled_named_state", "labelled_nonstutter_edge", "directional_related_pairs",
                      "bounded_stepwise_simulation", "initial_state_coverage", "bounded_labelled_run"],
        "assumptions": [
            "Constant native state predicates are exact; opaque predicates, coupled data and stutters require another interpretation.",
            "Forward means abstract-leading and backward means concrete-leading, following this repository's explicit SimulationDirection contract.",
            "All transitions are explicitly declared edges, with no invented source effects or program execution.",
            "Names remain annotations; relation/obligation statements must be the literal simulation and bounds the literal bounded simulation. Stronger prose is rejected.",
            "Terminal markers are retained; the native model does not prohibit explicitly declared outgoing edges from terminal states.",
            "Each matched edge costs one step; schedule and matching caps never establish unbounded refinement."],
        "system_symbols": names, "simulation_symbols": relation_names, "obligation_symbols": obligation_symbols,
        "provided_capabilities": ["closed_finite_labelled_simulation_formulas"],
        "missing_capabilities": ["typed_data_refinement", "stuttering_simulation", "source_program_equivalence"],
        "capability_floor_eligible": False, "proof_obligations_asserted": False,
        "source_semantics_verified": False, "unbounded_refinement_proved": False,
        "model_checker_executed": False, "admitted": False,
    }


__all__ = ["PROFILE", "emit_refinement"]
