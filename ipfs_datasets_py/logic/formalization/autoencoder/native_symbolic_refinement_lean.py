"""Explicit typed-store interpretations for opaque native refinement declarations.

The original RefinementIR is immutable. Native arithmetic state text is parsed
against caller-declared ProgramIR variable types and must match the selected
expression DAG exactly. Edges have no native assignment syntax; every edge
therefore requires a separately declared, hash-bound before/after relation.
"""
from __future__ import annotations

import ast
import re

from ...software_verification.refinement import RefinementIR
from . import native_interpretation_expressions as expressions
from .native_family_lean_emitters import UnsupportedNativeLean, require, string

PROFILE = "native-symbolic-bounded-refinement-lean/v1"
INTERPRETATION_SCHEMA = "native-symbolic-refinement-interpretation/v1"
PRODUCERS = (expressions, *expressions.PRODUCERS)

PRELUDE = '''set_option linter.unusedVariables false
structure SymbolicConfiguration (Store : Type) where
  node : String
  values : Store
  deriving DecidableEq, Repr
structure SymbolicSystem (Store : Type) where
  valid : SymbolicConfiguration Store → Bool
  initial : SymbolicConfiguration Store → Bool
  terminal : SymbolicConfiguration Store → Bool
  visible : SymbolicConfiguration Store → String → SymbolicConfiguration Store → Bool
  silent : SymbolicConfiguration Store → SymbolicConfiguration Store → Bool
-- A trailing match has zero or more explicitly declared silent steps and
-- exactly one visible action. Every silent or visible edge consumes one unit.
def symbolicVisibleMatch {Store : Type} (system : SymbolicSystem Store) :
    Nat → SymbolicConfiguration Store → String → SymbolicConfiguration Store → Prop
  | 0, _, _, _ => False
  | budget + 1, before, label, after =>
      system.visible before label after = true ∨
      ∃ middle, system.silent before middle = true ∧
        symbolicVisibleMatch system budget middle label after

def boundedSymbolicMatch {Left Right : Type}
    (leading : SymbolicSystem Left) (trailing : SymbolicSystem Right)
    (related : SymbolicConfiguration Left → SymbolicConfiguration Right → Prop)
    (matchingLimit : Nat) : Nat → SymbolicConfiguration Left → SymbolicConfiguration Right → Prop
  | 0, left, right => related left right
  | steps + 1, left, right =>
      related left right ∧ ∀ label next,
        leading.visible left label next = true →
        ∃ other, symbolicVisibleMatch trailing matchingLimit right label other ∧
          boundedSymbolicMatch leading trailing related matchingLimit steps next other

def boundedSymbolicSimulation {Left Right : Type}
    (leading : SymbolicSystem Left) (trailing : SymbolicSystem Right)
    (related : SymbolicConfiguration Left → SymbolicConfiguration Right → Prop)
    (matchingLimit scheduleLimit : Nat) : Prop :=
  (∃ state, leading.initial state = true) ∧
  (∃ state, trailing.initial state = true) ∧
  (∀ left, leading.initial left = true → ∃ right, trailing.initial right = true ∧
    boundedSymbolicMatch leading trailing related matchingLimit scheduleLimit left right) ∧
  (∀ left right, related left right →
    boundedSymbolicMatch leading trailing related matchingLimit scheduleLimit left right)

theorem zero_matching_budget_rejects_visible_action {Store : Type}
    (system : SymbolicSystem Store) (before after : SymbolicConfiguration Store) (label : String) :
    ¬ symbolicVisibleMatch system 0 before label after := by
  simp [symbolicVisibleMatch]

def sourceProgramRefinementProved : Bool := false
def unboundedRefinementClaimed : Bool := false
'''


def _closed(value, fields, reason):
    require(type(value) is dict and set(value) == set(fields), reason)


def _reference(value):
    require(type(value) is str and value.strip() == value and 1 <= len(value) <= 1024,
            "explicit_refinement_interpretation_evidence_reference_required")
    string(value)


def _rows(values, identity, expected, fields, reason):
    require(type(values) is list and len(values) <= 256, reason)
    result = {}
    for row in values:
        _closed(row, fields, reason)
        key = row[identity]
        require(type(key) is str and key not in result, reason)
        result[key] = row
    require(set(result) == set(expected), reason)
    return result


def _carrier_tree(carrier, key, depth=0, *, rows=None, budget=None):
    require(depth <= 32, "bounded_refinement_predicate_expression_required")
    if rows is None: rows = {row["expression_id"]: row for row in carrier.payload["expressions"]}
    if budget is None: budget = [0]
    budget[0] += 1
    require(budget[0] <= 256, "bounded_refinement_predicate_expression_required")
    row = rows[key]
    kind = row["kind"]
    if kind == "literal": return ("literal", row["type_ref"], row["attributes"]["value"])
    if kind == "symbol": return ("symbol", row["symbol_ids"][0])
    require(kind in ("unary", "binary", "conditional"),
            "refinement_predicate_requires_first_state_scalar_expression")
    return (row["operator"] if kind != "conditional" else "if", *(
        _carrier_tree(carrier, operand, depth + 1, rows=rows, budget=budget) for operand in row["operand_ids"]))


def _parsed_tree(text, carrier):
    """Parse only the closed source arithmetic fragment, never evaluate Python."""
    require(type(text) is str and len(text) <= 4096, "bounded_refinement_state_statement_required")
    aliases = {}
    for row in carrier.payload["symbols"]:
        key = row["symbol_id"]
        for alias in (key, row["name"]):
            require(alias not in aliases or aliases[alias] == key, "ambiguous_refinement_symbol_alias")
            aliases[alias] = key
    normalized = re.sub(r"\btrue\b", "True", re.sub(r"\bfalse\b", "False", text))
    normalized = re.sub(r"(?<![<>=!])=(?!=)", "==", normalized)
    try:
        tree = ast.parse(normalized, mode="eval")
    except (SyntaxError, ValueError, RecursionError) as error:
        raise UnsupportedNativeLean("refinement_state_statement_requires_supported_scalar_grammar") from error
    operators = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.Eq: "eq", ast.NotEq: "ne",
                 ast.Lt: "lt", ast.LtE: "le", ast.Gt: "gt", ast.GtE: "ge",
                 ast.Not: "not", ast.USub: "neg", ast.UAdd: "pos"}
    visits = 0
    def visit(node, depth=0):
        nonlocal visits
        visits += 1
        require(depth <= 32 and visits <= 256, "bounded_refinement_state_AST_required")
        if isinstance(node, ast.Constant):
            require(type(node.value) in (int, bool), "refinement_state_literal_type_not_supported")
            return ("literal", "boolean" if type(node.value) is bool else "integer", node.value)
        if isinstance(node, ast.Name):
            require(node.id in aliases, "refinement_state_variable_requires_explicit_type")
            return ("symbol", aliases[node.id])
        if isinstance(node, ast.UnaryOp):
            require(type(node.op) in operators, "refinement_state_unary_operator_not_supported")
            return (operators[type(node.op)], visit(node.operand, depth + 1))
        if isinstance(node, ast.BinOp):
            require(type(node.op) in operators, "refinement_state_binary_operator_not_supported")
            return (operators[type(node.op)], visit(node.left, depth + 1), visit(node.right, depth + 1))
        if isinstance(node, ast.Compare):
            require(len(node.ops) == len(node.comparators) == 1 and type(node.ops[0]) in operators,
                    "refinement_state_comparison_not_supported")
            return (operators[type(node.ops[0])], visit(node.left, depth + 1), visit(node.comparators[0], depth + 1))
        if isinstance(node, ast.BoolOp):
            name = "and" if isinstance(node.op, ast.And) else "or"
            values = [visit(child, depth + 1) for child in node.values]
            result = values[0]
            for value in values[1:]: result = (name, result, value)
            return result
        if isinstance(node, ast.IfExp):
            return ("if", visit(node.test, depth + 1), visit(node.body, depth + 1), visit(node.orelse, depth + 1))
        raise UnsupportedNativeLean("refinement_state_AST_node_not_supported:" + type(node).__name__)
    return visit(tree.body)


def _and(parts):
    return " && ".join("(" + item + ")" for item in parts) or "true"


def _or(parts):
    return " || ".join("(" + item + ")" for item in parts) or "false"


def _symbol_value(value, kind):
    require(type(value) is (int if kind == "integer" else bool), "typed_refinement_initial_witness_value_required")
    if kind == "integer":
        require(abs(value) <= 10 ** 100, "bounded_refinement_witness_integer_required")
        return "(" + str(value) + " : Int)"
    return str(value).lower()


def _statement_bindings(payload, interpretation):
    expected = {}
    for collection, identity, meaning in (("simulations", "relation_id", "simulation"),
            ("obligations", "obligation_id", "simulation"), ("boundedness", "boundedness_id", "bounded_simulation")):
        for row in payload[collection]:
            expected[(collection, row[identity])] = (row["statement"], meaning)
    rows = interpretation["statement_bindings"]
    require(type(rows) is list and len(rows) == len(expected), "complete_refinement_statement_bindings_required")
    seen = set()
    for row in rows:
        _closed(row, {"collection", "record_id", "statement", "semantics", "evidence_ref"},
                "closed_refinement_statement_binding_required")
        require(type(row["collection"]) is str and type(row["record_id"]) is str,
                "refinement_statement_binding_differs_from_original")
        key = (row["collection"], row["record_id"])
        require(key not in seen and key in expected and (row["statement"], row["semantics"]) == expected[key],
                "refinement_statement_binding_differs_from_original")
        _reference(row["evidence_ref"]); seen.add(key)


def emit_refinement(payload, *, interpretation):
    require(type(payload) is dict and len(expressions.canonical(payload).encode()) <= 512 * 1024,
            "bounded_native_refinement_document_required")
    native = RefinementIR.from_dict(payload)
    require(native.to_dict() == payload, "exact_native_refinement_roundtrip_required")
    _closed(interpretation, {"schema", "native_document_sha256", "systems", "statement_bindings", "metadata_annotation"},
            "closed_symbolic_refinement_interpretation_required")
    require(interpretation["schema"] == INTERPRETATION_SCHEMA and
            interpretation["native_document_sha256"] == expressions.digest(payload),
            "symbolic_refinement_interpretation_native_document_differs")
    require(len(expressions.canonical(interpretation).encode()) <= 2 * 1024 * 1024,
            "bounded_symbolic_refinement_interpretation_required")
    annotation = interpretation["metadata_annotation"]
    _closed(annotation, {"metadata", "role", "evidence_ref"}, "closed_refinement_metadata_annotation_required")
    require(annotation["metadata"] == payload["metadata"] and annotation["role"] == "descriptive_annotation"
            and set(payload["metadata"]) <= {"example", "name", "description", "version"},
            "refinement_metadata_requires_exact_descriptive_annotation")
    _reference(annotation["evidence_ref"])
    _statement_bindings(payload, interpretation)
    require(2 <= len(payload["systems"]) <= 8 and 1 <= len(payload["simulations"]) <= 16
            and 1 <= len(payload["boundedness"]) <= 16 and 1 <= len(payload["obligations"]) <= 32,
            "nonempty_bounded_symbolic_refinement_required")
    system_rows = _rows(interpretation["systems"], "system_id", [s["system_id"] for s in payload["systems"]],
        {"system_id", "expression_program", "state_predicates", "transition_relations", "initial_witness"},
        "exact_refinement_system_interpretations_required")
    lines = [PRELUDE]; system_symbols = {}; carriers = {}; state_symbols = {}; edge_symbols = {}
    for index, system in enumerate(payload["systems"]):
        require(not system["attributes"] and not system["concurrency_document_id"],
                "symbolic_refinement_system_extra_or_concurrency_semantics_not_lowered")
        require(1 <= len(system["states"]) <= 64 and len(system["transitions"]) <= 256,
                "bounded_symbolic_refinement_graph_required")
        name = "System_" + str(index); system_symbols[system["system_id"]] = name
        evidence = system_rows[system["system_id"]]
        carrier = expressions.TypedExpressions(evidence["expression_program"])
        carriers[system["system_id"]] = carrier
        lines.extend(["namespace " + name, carrier.store_declaration(), "abbrev Configuration := SymbolicConfiguration Store"])
        predicates = _rows(evidence["state_predicates"], "state_id", [s["state_id"] for s in system["states"]],
            {"state_id", "statement", "expression_id", "evidence_ref"}, "complete_refinement_state_predicate_bindings_required")
        clauses = []; initial = []; terminal = []
        for i, state in enumerate(system["states"]):
            require(not state["attributes"], "symbolic_refinement_state_attributes_not_lowered")
            binding = predicates[state["state_id"]]; _reference(binding["evidence_ref"])
            require(binding["statement"] == state["predicate_statement"], "refinement_state_statement_binding_differs")
            root = carrier.require_root(binding["expression_id"], "boolean")
            require(_parsed_tree(state["predicate_statement"], carrier) == _carrier_tree(carrier, root),
                    "refinement_state_predicate_expression_does_not_match_source")
            predicate = "statePredicate_" + str(i)
            lines.append("def " + predicate + " (s : Store) : Bool := " + carrier.render(root, current="s", initial="s"))
            state_symbols[(system["system_id"], state["state_id"])] = name + "." + predicate
            clauses.append(_and(["state.node == " + string(state["state_id"]), predicate + " state.values"]))
            if state["is_initial"]: initial.append(string(state["state_id"]))
            if state["is_terminal"]: terminal.append(string(state["state_id"]))
        lines.append("def valid (state : Configuration) : Bool := " + _or(clauses))
        lines.append("def initial (state : Configuration) : Bool := valid state && [" + ", ".join(initial) + "].contains state.node")
        lines.append("def terminal (state : Configuration) : Bool := valid state && [" + ", ".join(terminal) + "].contains state.node")
        relations = _rows(evidence["transition_relations"], "transition_id", [t["transition_id"] for t in system["transitions"]],
            {"transition_id", "expression_id", "semantics", "evidence_ref"}, "complete_refinement_transition_relations_required")
        visible = []; silent = []
        for i, edge in enumerate(system["transitions"]):
            require(not edge["attributes"], "symbolic_refinement_transition_attributes_not_lowered")
            binding = relations[edge["transition_id"]]; _reference(binding["evidence_ref"])
            require(binding["semantics"] == "caller_declared_before_after_relation", "explicit_refinement_transition_relation_scope_required")
            root = carrier.require_root(binding["expression_id"], "boolean", allow_old=True)
            relation = "edgeRelation_" + str(i)
            lines.append("def " + relation + " (before after : Store) : Bool := " + carrier.render(root))
            name_edge = "edge_" + str(i)
            lines.append("def " + name_edge + " (before after : Configuration) : Bool := " + _and([
                "before.node == " + string(edge["source_state_id"]), "after.node == " + string(edge["target_state_id"]),
                "valid before", "valid after", relation + " before.values after.values"]))
            edge_symbols[(system["system_id"], edge["transition_id"])] = name + "." + name_edge
            if edge["is_stutter"]: silent.append(name_edge + " before after")
            else: visible.append(_and(["label == " + string(edge["action_label"]), name_edge + " before after"]))
        lines.append("def visible (before : Configuration) (label : String) (after : Configuration) : Bool := " + _or(visible))
        lines.append("def silent (before after : Configuration) : Bool := " + _or(silent))
        lines.append("def system : SymbolicSystem Store := ⟨valid, initial, terminal, visible, silent⟩")
        witness = evidence["initial_witness"]
        _closed(witness, {"state_id", "values"}, "closed_refinement_initial_witness_required")
        require(witness["state_id"] in [s["state_id"] for s in system["states"] if s["is_initial"]]
                and type(witness["values"]) is dict and set(witness["values"]) == set(carrier.fields),
                "complete_refinement_initial_witness_required")
        store = "{ " + ", ".join(carrier.fields[key] + " := " + _symbol_value(witness["values"][key], carrier.symbol_types[key])
            for key in carrier.fields) + " }"
        lines.append("def initialWitness : Configuration := ⟨" + string(witness["state_id"]) + ", " + store + "⟩")
        lines.append("example : initial initialWitness = true := by decide")
        lines.append("end " + name)

    systems = {s["system_id"]: s for s in payload["systems"]}; relation_symbols = {}
    for index, relation in enumerate(payload["simulations"]):
        require(not relation["attributes"] and not relation["claims_unbounded_refinement"],
                "symbolic_refinement_relation_extra_claims_not_lowered")
        require(type(relation["max_matching_steps"]) is int and 1 <= relation["max_matching_steps"] <= 64,
                "explicit_bounded_symbolic_refinement_matching_steps_required")
        require(1 <= len(relation["couples"]) <= 256 and all(not c["attributes"] and c["statement"] == "related"
            for c in relation["couples"]), "symbolic_refinement_couple_data_relation_not_lowered")
        forward = relation["direction"] == "forward"
        leading_id, trailing_id = (relation["abstract_system_id"], relation["concrete_system_id"]) if forward else (
            relation["concrete_system_id"], relation["abstract_system_id"])
        require(not any(edge["is_stutter"] for edge in systems[leading_id]["transitions"]),
                "leading_symbolic_refinement_stutters_require_separate_simulation_semantics")
        leading_labels = {edge["action_label"] for edge in systems[leading_id]["transitions"]}
        require(not any(edge["is_stutter"] and edge["action_label"] in leading_labels
                        for edge in systems[trailing_id]["transitions"]),
                "stutter_label_visible_match_requires_separate_simulation_semantics")
        leading, trailing = system_symbols[leading_id], system_symbols[trailing_id]
        pairs = [(c["abstract_state_id"], c["concrete_state_id"]) if forward else (c["concrete_state_id"], c["abstract_state_id"])
                 for c in relation["couples"]]
        related = "related_" + str(index); simulation = "simulation_" + str(index)
        pair_conditions = " ∨ ".join("(left.node = " + string(a) + " ∧ right.node = " + string(b) + ")" for a, b in pairs)
        lines.append("def " + related + " (left : " + leading + ".Configuration) (right : " + trailing + ".Configuration) : Prop :=\n  " +
            leading + ".valid left = true ∧ " + trailing + ".valid right = true ∧ (" + pair_conditions + ")")
        lines.append("def " + simulation + " (scheduleLimit : Nat) : Prop := boundedSymbolicSimulation " +
            leading + ".system " + trailing + ".system " + related + " " + str(relation["max_matching_steps"]) + " scheduleLimit")
        relation_symbols[relation["relation_id"]] = simulation

    bounds = {b["boundedness_id"]: b for b in payload["boundedness"]}
    for bound in bounds.values():
        require(bound["kind"] == "bounded" and not bound["claims_unbounded_refinement"] and not bound["attributes"]
                and type(bound["max_steps"]) is int and 1 <= bound["max_steps"] <= 64 and bound["max_states"] is None,
                "symbolic_refinement_requires_explicit_step_bound_without_state_bound")
    relations = {r["relation_id"]: r for r in payload["simulations"]}; obligation_symbols = {}
    for index, obligation in enumerate(payload["obligations"]):
        require(obligation["kind"] == "simulation" and not obligation["attributes"] and not obligation["claims_unbounded_refinement"]
                and obligation["simulation_relation_id"] in relation_symbols and obligation["boundedness_id"] in bounds,
                "symbolic_refinement_requires_bounded_simulation_obligation")
        relation = relations[obligation["simulation_relation_id"]]
        require(all(obligation[key] == relation[key] for key in ("abstract_system_id", "concrete_system_id")),
                "symbolic_refinement_obligation_system_pair_differs")
        name = "obligation_" + str(index); obligation_symbols[obligation["obligation_id"]] = name
        lines.append("def " + name + " : Prop := " + relation_symbols[relation["relation_id"]] + " " +
            str(bounds[obligation["boundedness_id"]]["max_steps"]))
    lines.extend([expressions.evidence_strings("originalRefinementDeclaration", payload),
        expressions.evidence_strings("explicitRefinementInterpretation", interpretation)])
    return "\n\n".join(lines), {"profile": PROFILE,
        "validator": "exact_native_refinement_with_typed_source_predicates_and_explicit_edge_relations",
        "payload_sha256": expressions.digest(payload), "interpretation_sha256": expressions.digest(interpretation),
        "native_document_rewritten": False, "source_meaning_inferred": False,
        "expression_carrier_sha256": {key: carrier.sha256 for key, carrier in carriers.items()},
        "system_symbols": system_symbols, "state_predicate_symbols": {system + "/" + state: symbol for (system, state), symbol in state_symbols.items()},
        "transition_symbols": {system + "/" + edge: symbol for (system, edge), symbol in edge_symbols.items()},
        "simulation_symbols": relation_symbols, "obligation_symbols": obligation_symbols,
        "operators": ["typed_unbounded_integer_and_Boolean_store", "exact_scalar_state_predicate_AST", "declared_before_after_relation",
            "explicit_silent_prefix", "bounded_directional_symbolic_simulation", "checked_initial_witness"],
        "assumptions": [
            "ProgramIR expression carriers declare mathematical integer/Boolean types; their return-true body is never emitted as program behavior.",
            "State predicates must parse exactly to the supplied typed expression DAG; unknown variables and unsupported grammar fail closed.",
            "Every edge relation is explicit caller interpretation. No arithmetic update, frame condition or source effect is inferred from a transition label.",
            "Caller statement bindings interpret exact original prose using native directional simulation and finite step-bound fields, without proving prose equivalence.",
            "Metadata is retained as explicitly declared descriptive annotation; other semantic metadata and record attributes remain unsupported.",
            "Silent trailing edges consume matching budget; leading-side silent simulation and opaque couple data constraints remain unsupported.",
            "Initial witness checks establish satisfiability only for the supplied symbolic model. Simulation propositions are not asserted true.",
            "Unbounded integer stores are quantified symbolically; finite trace depth is not a finite state-space or unbounded refinement proof."],
        "provided_capabilities": ["typed_symbolic_bounded_simulation_formulas", "explicit_trailing_stutter_matching"],
        "missing_capabilities": ["source_program_equivalence", "leading_stutter_simulation", "opaque_couple_data_relations"],
        "capability_floor_eligible": False, "source_semantics_verified": False, "proof_obligations_asserted": False,
        "unbounded_refinement_proved": False, "model_checker_executed": False, "admitted": False,
        "obligation_decision_procedure_executed": False,
    }


__all__ = ["PROFILE", "INTERPRETATION_SCHEMA", "PRODUCERS", "emit_refinement"]
