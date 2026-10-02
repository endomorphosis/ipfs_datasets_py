"""Kernel-checkable finite correspondence between source ProgramIR and state IR.

The source adapter and explicit bounded input domains are replayed. Generated
theorems compare the existing native operational renderer with every finite
case and every native state action. They prove a correspondence of those two
models, conditional on the source adapter's stated Python assumptions; they do
not infer a security policy or execute the original Python source.
"""
from __future__ import annotations

from . import native_interpretation_expressions as evidence
from . import native_program_lean_v2 as program
from . import native_tla_projection as tla
from .native_family_lean_emitters import require, string
from .security import source_state_model as models
from ...software_verification.transitions import StateTransitionIR

PROFILE = "source-state-finite-operational-correspondence-lean/v1"
PRODUCERS = tuple(dict.fromkeys((models, *models.PRODUCERS, program, program.previous,
    tla, tla.lean, evidence, *evidence.PRODUCERS)))


def _literal(value):
    require(type(value) in (int, bool), "source_state_scalar_literal_required")
    return str(value).lower() if type(value) is bool else "(" + str(value) + " : Int)"


def _conjunction(parts):
    return " ∧ ".join("(" + part + ")" for part in parts)


def _disjunction(parts):
    return " ∨ ".join("(" + part + ")" for part in parts)


def _choice(index, count, value):
    """Construct a proof of a right-associated finite disjunction."""
    for offset in reversed(range(index + (index < count - 1))):
        value = ("Or.inl (" if offset == index else "Or.inr (") + value + ")"
    return value


def _store_update(fields, values, base="base"):
    return "{ " + base + " with " + ", ".join(fields[key] + " := " + value for key, value in values.items()) + " }"


def emit_source_state_model(model):
    """Replay the complete model and emit proofs over the existing renderers."""
    require(type(model) is dict and len(evidence.canonical(model).encode()) <= 1024 * 1024,
            "bounded_complete_source_state_model_required")
    models.verify_source_state_model(model, model["source_text"], model["candidate_ir"], model["input_domains"])
    require(model["status"] == "derived" and 1 <= len(model["cases"]) <= 64,
            "derived_nonempty_finite_source_state_model_required")
    original = model["source_program"]
    native_source, program_details = program.emit_program(original)
    bounded = tla.compile_bounded_state(StateTransitionIR.from_dict(model["state_model"]), max_steps=1)
    state = bounded["native_document"]
    fields = {row["symbol_id"]: "v" + str(i) for i, row in enumerate(original["symbols"])}
    state_fields = {row["variable_id"]: "v" + str(i) for i, row in enumerate(state["schema"]["variables"])}
    function = original["functions"][0]
    parameters = model["parameter_order"]
    param_symbols = model["parameter_symbols"]
    param_fields = {name: state_fields[model["parameter_variables"][name]] for name in parameters}
    result_field = state_fields[model["result_variable_id"]]
    returned_field = state_fields[model["returned_variable_id"]]
    reads = {param_symbols[name]: "s." + param_fields[name] for name in parameters}
    writes = {param_symbols[name]: "t." + param_fields[name] for name in parameters}
    writes.update({symbol: "t." + result_field for symbol in function["local_symbol_ids"]})
    lines = ["set_option autoImplicit false", "set_option linter.unusedVariables false",
        "set_option linter.unusedSimpArgs false",
        "namespace SourceProgram", native_source, "end SourceProgram",
        "namespace DerivedState", bounded["lean_source"], "end DerivedState",
        "def programInput (base : SourceProgram.Store) (s : DerivedState.State) : SourceProgram.Store := " +
            _store_update(fields, reads),
        "def programFinal (base : SourceProgram.Store) (t : DerivedState.State) : SourceProgram.Store := " +
            _store_update(fields, writes),
        "def operationalCorrespondence (base : SourceProgram.Store) (s t : DerivedState.State) : Prop :=\n  " +
            "t." + returned_field + " = true ∧ SourceProgram.run (programInput base s) = " +
            "SourceProgram.Outcome.returned (programFinal base t) t." + result_field]
    domains = model["input_domains"]
    clauses = [_literal(domains[name]["lower"]) + " ≤ s." + param_fields[name] + " ∧ s." +
        param_fields[name] + " ≤ " + _literal(domains[name]["upper"]) for name in parameters]
    lines.append("def inParameterDomain (s : DerivedState.State) : Prop := " + _conjunction(clauses))
    predicates = {row["predicate_id"]: "DerivedState.predicate_" + str(i) for i, row in enumerate(state["predicates"])}
    initial_predicates = [predicates[row["predicate_id"]] for row in state["predicates"] if row["role"] == "initial"]
    action_names = {row["action_id"]: "DerivedState.action_" + str(i) for i, row in enumerate(state["actions"])}
    require(len(state["transitions"]) == 1 and not state["transitions"][0]["allows_stutter"],
            "one_nonstuttering_source_state_transition_relation_required")
    action_ids = state["transitions"][0]["action_ids"]
    expression_names = ["SourceProgram.expression_" + str(i) for i, _ in enumerate(original["expressions"])]
    operational_defs = ["operationalCorrespondence", "programInput", "programFinal", "SourceProgram.run", *expression_names]
    all_cases = []; all_case_proofs = []; covered_inputs = []; action_theorems = {}
    initial_cases = []; initial_case_proofs = []; terminal_theorems = {}
    for case in model["cases"]:
        i = case["index"]
        first = "caseInitial_" + str(i); final = "caseFinal_" + str(i)
        input_values = {key: _literal(value) for key, value in case["initial_symbols"].items()}
        final_values = {key: _literal(value) for key, value in case["final_symbols"].items()}
        lines.extend(["def " + first + " (base : SourceProgram.Store) : SourceProgram.Store := " + _store_update(fields, input_values),
            "def " + final + " (base : SourceProgram.Store) : SourceProgram.Store := " + _store_update(fields, final_values)])
        fact = "SourceProgram.run (" + first + " base) = SourceProgram.Outcome.returned (" + final + " base) " + _literal(case["result"])
        theorem = "case_run_" + str(i)
        lines.append("theorem " + theorem + " (base : SourceProgram.Store) : " + fact + " := by rfl")
        all_cases.append(fact); all_case_proofs.append(theorem + " base")
        match_input = "caseInput_" + str(i)
        equalities = ["s." + param_fields[name] + " = " + _literal(case["parameter_values"][name]) for name in parameters]
        lines.append("def " + match_input + " (s : DerivedState.State) : Prop := " + _conjunction(equalities))
        covered_inputs.append(match_input + " s")
        before = "{ " + ", ".join(state_fields[key] + " := " + _literal(value) for key, value in case["initial_state"].items()) + " }"
        after = "{ " + ", ".join(state_fields[key] + " := " + _literal(value) for key, value in case["final_state"].items()) + " }"
        initial_fact = "DerivedState.initial " + before
        initial_theorem = "case_initial_" + str(i)
        lines.append("theorem " + initial_theorem + " : " + initial_fact + " := by\n  simp [" +
            ", ".join(["DerivedState.initial", "DerivedState.typeOK", *initial_predicates]) + "]")
        initial_cases.append(initial_fact); initial_case_proofs.append(initial_theorem)
        action = action_names[case["action_id"]]
        relevant = [action, predicates[case["guard_predicate_id"]], predicates[case["next_predicate_id"]]]
        chosen = _choice(action_ids.index(case["action_id"]), len(action_ids),
            "⟨rfl, by simp [" + ", ".join(relevant) + "]⟩")
        lines.append("theorem case_transition_" + str(i) + " : DerivedState.next " + string(case["action_id"]) +
            " " + before + " " + after + " := by\n" +
            "  unfold DerivedState.next DerivedState.transition_0\n" +
            "  exact ⟨by simp [DerivedState.typeOK], by simp [DerivedState.typeOK], " + chosen + "⟩")
        action_theorem = "action_matches_program_" + str(i)
        lines.append("theorem " + action_theorem + " (base : SourceProgram.Store) (s t : DerivedState.State)\n" +
            "    (h : " + action + " s t) : operationalCorrespondence base s t := by\n" +
            "  simp_all [" + ", ".join([*relevant, *operational_defs]) + "]")
        action_theorems[case["action_id"]] = action_theorem
        terminal_theorem = "returned_blocks_action_" + str(i)
        lines.append("theorem " + terminal_theorem + " (s t : DerivedState.State)\n" +
            "    (returned : s." + returned_field + " = true) : ¬ " + action + " s t := by\n" +
            "  simp_all [" + ", ".join([action, predicates[case["guard_predicate_id"]]]) + "]")
        terminal_theorems[case["action_id"]] = terminal_theorem
    lines.append("theorem all_finite_cases_match (base : SourceProgram.Store) : " + _conjunction(all_cases) +
        " := by\n  exact " + ("⟨" + ", ".join(all_case_proofs) + "⟩" if len(all_cases) > 1 else all_case_proofs[0]))
    lines.append("theorem all_finite_cases_initial : " + _conjunction(initial_cases) +
        " := by\n  exact " + ("⟨" + ", ".join(initial_case_proofs) + "⟩" if len(initial_cases) > 1 else initial_case_proofs[0]))
    coverage = ["theorem parameter_domain_covered (s : DerivedState.State) (h : inParameterDomain s) :\n  " +
        _disjunction(covered_inputs) + " := by"]
    for i, name in enumerate(parameters):
        values = range(domains[name]["lower"], domains[name]["upper"] + 1)
        coverage.append("  have covered_" + str(i) + " : " + _disjunction(
            ["s." + param_fields[name] + " = " + _literal(value) for value in values]) +
            " := by\n    simp only [inParameterDomain] at h\n    omega")
    # Split each coordinate separately. Asking omega to refute the negation of
    # a full Cartesian disjunction grows exponentially even at 8 by 8 inputs.
    for i, name in enumerate(parameters):
        count = domains[name]["upper"] - domains[name]["lower"] + 1
        command = ("have value_" + str(i) + " := covered_" + str(i) if count == 1 else
            "rcases covered_" + str(i) + " with " + " | ".join(["value_" + str(i)] * count))
        coverage.append("  " + ("all_goals " if i else "") + command)
    coverage.extend("  · exact " + _choice(case["index"], len(model["cases"]), "⟨value_0, value_1⟩")
        for case in model["cases"])
    lines.append("\n".join(coverage))
    relation_names = ["DerivedState.transition_" + str(i) for i, _ in enumerate(state["transitions"])]
    proof = ["theorem every_transition_matches_program (base : SourceProgram.Store) (label : String)",
        "    (s t : DerivedState.State) (h : DerivedState.next label s t) : operationalCorrespondence base s t := by",
        "  rcases h with ⟨_, _, choices⟩", "  simp only [" + ", ".join(relation_names) + "] at choices"]
    if len(action_ids) == 1:
        proof.append("  exact " + action_theorems[action_ids[0]] + " base s t choices.2")
    else:
        proof.append("  rcases choices with " + " | ".join("h" + str(i) for i in range(len(action_ids))))
        proof.extend("  · exact " + action_theorems[action_id] + " base s t h" + str(i) + ".2"
            for i, action_id in enumerate(action_ids))
    lines.append("\n".join(proof))
    lines.append("theorem every_bounded_transition_matches_program (base : SourceProgram.Store)\n" +
        "    (s t : DerivedState.BoundedState) (h : DerivedState.boundedNext s t) :\n" +
        "    operationalCorrespondence base s.state t.state := by\n" +
        "  exact every_transition_matches_program base t.lastLabel s.state t.state h.2.2.2.2")
    terminal_proof = ["theorem returned_states_are_terminal (label : String) (s t : DerivedState.State)",
        "    (returned : s." + returned_field + " = true) : ¬ DerivedState.next label s t := by",
        "  intro step", "  rcases step with ⟨_, _, choices⟩",
        "  simp only [" + ", ".join(relation_names) + "] at choices"]
    if len(action_ids) == 1:
        terminal_proof.append("  exact " + terminal_theorems[action_ids[0]] + " s t returned choices.2")
    else:
        terminal_proof.append("  rcases choices with " + " | ".join("h" + str(i) for i in range(len(action_ids))))
        terminal_proof.extend("  · exact " + terminal_theorems[action_id] + " s t returned h" + str(i) + ".2"
            for i, action_id in enumerate(action_ids))
    lines.append("\n".join(terminal_proof))
    lines.append("theorem returned_bounded_states_are_terminal (s t : DerivedState.BoundedState)\n" +
        "    (returned : s.state." + returned_field + " = true) : ¬ DerivedState.boundedNext s t := by\n" +
        "  intro step\n" +
        "  exact returned_states_are_terminal t.lastLabel s.state t.state returned step.2.2.2.2")
    lines.extend([evidence.evidence_strings("completeSourceStateModel", model),
        "def sourcePythonExecutionObserved : Bool := false", "def securityPolicyInferred : Bool := false",
        "def unboundedInputCorrespondenceProved : Bool := false"])
    source = "\n\n".join(lines)
    require(len(source.encode()) < 4 * 1024 * 1024, "bounded_source_state_Lean_artifact_required")
    return source, {"profile": PROFILE, "validator": "exact_source_candidate_domains_model_replay_and_kernel_correspondence_obligations",
        "model_sha256": evidence.digest(model), "case_count": len(model["cases"]),
        "program_lowering": program_details, "bounded_tla": bounded,
        "theorems": ["all_finite_cases_match", "all_finite_cases_initial", "parameter_domain_covered",
            "every_transition_matches_program", "every_bounded_transition_matches_program",
            "returned_states_are_terminal", "returned_bounded_states_are_terminal"],
        "assumptions": [*program_details["assumptions"],
            "Only the explicit finite Cartesian parameter domains are covered.",
            "An arbitrary initial Program Store is quantified; only source parameters are initialized, and only actual assignments change local slots.",
            "The returned flag and output sentinel are observation-model state, not source-local initialization.",
            "Generated theorem declarations must pass a real Lean kernel build before they are evidence of bounded model correspondence.",
            "TLA specification stuttering is separate from the nonstuttering derived action relation; no liveness or security policy is inferred."],
        "source_executed": False, "source_semantics_verified": False, "security_specification_inferred": False,
        "unbounded_proof": False, "model_checker_executed": False, "kernel_executed": False,
        "proof_authority": False, "execution_authority": False, "completion_authority": False,
        "capability_floor_eligible": False, "admitted": False}


__all__ = ["PROFILE", "PRODUCERS", "emit_source_state_model"]
