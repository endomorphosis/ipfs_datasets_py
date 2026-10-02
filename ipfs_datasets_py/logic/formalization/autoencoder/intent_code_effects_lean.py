"""Check explicit Intent effect interpretations against finite code outcomes.

Intent instruction and code source identities stay distinct. The existing
source-state proofs are included unchanged; caller-supplied typed expressions
interpret the selected Intent preconditions and effects. A successfully checked
refutation is a negative contract verdict, never satisfaction or goal authority.
"""
from __future__ import annotations

from . import intent_code_effects as models
from . import native_interpretation_expressions as expressions
from . import source_state_lean as source_states
from .native_family_lean_emitters import require, string

PROFILE = "intent-code-finite-effect-correspondence-lean/v1"
PRODUCERS = tuple(dict.fromkeys((models, *models.PRODUCERS, expressions,
    *expressions.PRODUCERS, source_states, *source_states.PRODUCERS)))


def _bool(value):
    require(type(value) is bool, "exact_Intent_code_Boolean_verdict_required")
    return str(value).lower()


def _value(value):
    require(type(value) in (bool, int), "scalar_Intent_code_interpretation_value_required")
    return _bool(value) if type(value) is bool else "(" + str(value) + " : Int)"


def _record(fields, values):
    return "{ " + ", ".join(fields[key] + " := " + _value(value) for key, value in values.items()) + " }"


def _and(terms):
    return " && ".join("(" + term + ")" for term in terms) or "true"


def _case_split(action_ids, per_action, *, arguments, last_argument):
    lines = ["  rcases step with ⟨_, _, choices⟩",
        "  simp only [Code.DerivedState.transition_0] at choices"]
    if len(action_ids) == 1:
        lines.append("  exact " + per_action[action_ids[0]] + " " + arguments + " choices.2" + last_argument)
    else:
        lines.append("  rcases choices with " + " | ".join("h" + str(i) for i in range(len(action_ids))))
        lines.extend("  · exact " + per_action[action_id] + " " + arguments + " h" + str(i) + ".2" + last_argument
            for i, action_id in enumerate(action_ids))
    return lines


def emit_intent_code_effects(report):
    """Replay all original inputs and emit either proof, refutation, or no-enabled evidence."""
    require(type(report) is dict and len(expressions.canonical(report).encode()) <= 2 * 1024 * 1024,
        "bounded_complete_Intent_code_effect_report_required")
    models.verify_intent_code_effects(report, report["intent_source_text"], report["intent_candidate_ir"],
        report["code_source_text"], report["code_candidate_ir"], report["input_domains"], report["association"])
    status = report["status"]
    require(status in ("satisfied", "refuted", "no_enabled_cases"), "closed_Intent_code_disposition_required")
    code = report["source_state_model"]
    code_source, code_details = source_states.emit_source_state_model(code)
    association = report["association"]
    carrier = expressions.TypedExpressions(association["expression_program"])
    state = code["state_model"]
    state_fields = {row["variable_id"]: "v" + str(i) for i, row in enumerate(state["schema"]["variables"])}
    mapping = report["variable_symbols"]
    require(set(mapping) == set(state_fields) and set(mapping.values()) == set(carrier.fields),
        "complete_bijective_Intent_code_state_interpretation_required")
    native_predicates = {row["predicate_id"]: "Code.DerivedState.predicate_" + str(i)
        for i, row in enumerate(state["predicates"])}
    native_actions = {row["action_id"]: "Code.DerivedState.action_" + str(i) for i, row in enumerate(state["actions"])}
    require(len(state["transitions"]) == 1 and not state["transitions"][0]["allows_stutter"],
        "exact_nonstuttering_Intent_code_state_relation_required")
    action_ids = state["transitions"][0]["action_ids"]
    lines = ["set_option autoImplicit false", "set_option linter.unusedVariables false",
        "set_option linter.unusedSimpArgs false", "namespace Code", code_source, "end Code",
        "namespace BoundIntent", carrier.store_declaration()]
    roots = {"preconditions": association["precondition_bindings"], "effects": association["effect_bindings"]}
    names = {"preconditions": {}, "effects": {}}
    for collection, prefix in (("preconditions", "precondition"), ("effects", "effect")):
        for index, binding in enumerate(roots[collection]):
            key = carrier.require_root(binding["expression_id"], "boolean", allow_old=collection == "effects")
            name = prefix + "_" + str(index)
            names[collection][binding["statement_id"]] = "BoundIntent." + name
            arguments = " (before after : Store)" if collection == "effects" else " (before : Store)"
            expression = carrier.render(key, current="after" if collection == "effects" else "before", initial="before")
            lines.append("def " + name + arguments + " : Bool := " + expression)
    lines.extend(["end BoundIntent",
        "def interpretationStore (state : Code.DerivedState.State) : BoundIntent.Store := { " +
            ", ".join(carrier.fields[symbol] + " := state." + state_fields[variable] for variable, symbol in mapping.items()) + " }",
        "def preconditions (before : Code.DerivedState.State) : Bool := " + _and(
            [name + " (interpretationStore before)" for name in names["preconditions"].values()]),
        "def effects (before after : Code.DerivedState.State) : Bool := " + _and(
            [name + " (interpretationStore before) (interpretationStore after)" for name in names["effects"].values()]),
        "def boundedIntentContract : Prop := ∀ (label : String) (before after : Code.DerivedState.State),\n" +
            "  Code.DerivedState.next label before after → preconditions before = true → effects before after = true"])
    interpretation_definitions = ["preconditions", "effects", "interpretationStore",
        *names["preconditions"].values(), *names["effects"].values()]
    native_cases = {case["index"]: case for case in code["cases"]}
    action_proofs = {}; case_proofs = []
    for case in report["cases"]:
        i = case["index"]; native_case = native_cases[i]
        before, after = "before_" + str(i), "after_" + str(i)
        lines.extend(["def " + before + " : Code.DerivedState.State := " + _record(state_fields, case["before_state"]),
            "def " + after + " : Code.DerivedState.State := " + _record(state_fields, case["after_state"]),
            "theorem case_mapping_" + str(i) + " : interpretationStore " + before + " = " +
                _record(carrier.fields, case["before_symbols"]) + " ∧ interpretationStore " + after + " = " +
                _record(carrier.fields, case["after_symbols"]) + " := by exact ⟨rfl, rfl⟩"])
        for collection in ("preconditions", "effects"):
            for j, result in enumerate(case[collection]):
                invocation = names[collection][result["statement_id"]] + " (interpretationStore " + before + ")"
                if collection == "effects": invocation += " (interpretationStore " + after + ")"
                lines.append("theorem case_" + collection + "_" + str(i) + "_" + str(j) + " : " + invocation +
                    " = " + _bool(result["value"]) + " := by decide")
        lines.extend(["theorem case_preconditions_" + str(i) + " : preconditions " + before + " = " +
            _bool(case["preconditions_passed"]) + " := by decide",
            "theorem case_effects_" + str(i) + " : effects " + before + " " + after + " = " +
            _bool(case["effects_passed"]) + " := by decide"])
        implication = ("((!preconditions " + before + ") || effects " + before + " " + after + ") = " +
            _bool(not case["enabled"] or case["effects_passed"]))
        lines.append("theorem case_contract_" + str(i) + " : " + implication + " := by decide")
        case_proofs.append("case_contract_" + str(i))
        if status in ("satisfied", "no_enabled_cases"):
            action = native_actions[native_case["action_id"]]
            definitions = [action, native_predicates[native_case["guard_predicate_id"]],
                native_predicates[native_case["next_predicate_id"]], *interpretation_definitions]
            theorem = "action_effects_" + str(i)
            consequence = ("preconditions before = true → effects before after = true" if status == "satisfied" else
                "preconditions before = false")
            lines.append("theorem " + theorem + " (before after : Code.DerivedState.State)\n" +
                "    (step : " + action + " before after) : " + consequence + " := by\n" +
                "  simp_all [" + ", ".join(definitions) + "]")
            action_proofs[native_case["action_id"]] = theorem
    theorem_names = []
    if status == "satisfied":
        proof = ["theorem bounded_intent_contract_satisfied : boundedIntentContract := by",
            "  intro label before after step enabled", *_case_split(action_ids, action_proofs,
                arguments="before after", last_argument=" enabled")]
        lines.append("\n".join(proof)); theorem_names.append("bounded_intent_contract_satisfied")
        enabled = next(case for case in report["cases"] if case["enabled"])
        i = enabled["index"]; native_case = native_cases[i]
        lines.append("theorem enabled_contract_witness : ∃ (label : String) (before after : Code.DerivedState.State),\n" +
            "    Code.DerivedState.initial before ∧ Code.DerivedState.next label before after ∧ preconditions before = true := by\n" +
            "  exact ⟨" + string(native_case["action_id"]) + ", before_" + str(i) + ", after_" + str(i) +
            ", Code.case_initial_" + str(i) + ", Code.case_transition_" + str(i) + ", case_preconditions_" + str(i) + "⟩")
        theorem_names.append("enabled_contract_witness")
        lines.append("theorem all_enabled_code_outcomes_satisfy (base : Code.SourceProgram.Store) (label : String)\n" +
            "    (before after : Code.DerivedState.State) (step : Code.DerivedState.next label before after)\n" +
            "    (enabled : preconditions before = true) : Code.operationalCorrespondence base before after ∧\n" +
            "    effects before after = true := by\n" +
            "  exact ⟨Code.every_transition_matches_program base label before after step,\n" +
            "    bounded_intent_contract_satisfied label before after step enabled⟩")
        theorem_names.append("all_enabled_code_outcomes_satisfy")
    elif status == "refuted":
        i = report["counterexample_case_indices"][0]; native_case = native_cases[i]
        before, after = "before_" + str(i), "after_" + str(i)
        label = string(native_case["action_id"])
        lines.append("theorem code_counterexample (base : Code.SourceProgram.Store) :\n" +
            "    Code.DerivedState.initial " + before + " ∧ Code.DerivedState.next " + label + " " + before + " " + after + " ∧\n" +
            "    Code.operationalCorrespondence base " + before + " " + after + " ∧ preconditions " + before + " = true ∧\n" +
            "    effects " + before + " " + after + " = false := by\n" +
            "  exact ⟨Code.case_initial_" + str(i) + ", Code.case_transition_" + str(i) +
            ", Code.every_transition_matches_program base " + label + " " + before + " " + after +
            " Code.case_transition_" + str(i) + ", case_preconditions_" + str(i) + ", case_effects_" + str(i) + "⟩")
        lines.append("theorem bounded_intent_contract_refuted : ¬ boundedIntentContract := by\n" +
            "  intro satisfied\n" +
            "  have claim := satisfied " + label + " " + before + " " + after + " Code.case_transition_" + str(i) +
            " case_preconditions_" + str(i) + "\n" +
            "  rw [case_effects_" + str(i) + "] at claim\n  contradiction")
        theorem_names.extend(["code_counterexample", "bounded_intent_contract_refuted"])
    else:
        proof = ["theorem every_transition_has_disabled_precondition (label : String) (before after : Code.DerivedState.State)",
            "    (step : Code.DerivedState.next label before after) : preconditions before = false := by",
            *_case_split(action_ids, action_proofs, arguments="before after", last_argument="")]
        lines.append("\n".join(proof))
        lines.append("theorem no_enabled_contract_instances :\n" +
            "    ¬ ∃ (label : String) (before after : Code.DerivedState.State),\n" +
            "      Code.DerivedState.next label before after ∧ preconditions before = true := by\n" +
            "  rintro ⟨label, before, after, step, enabled⟩\n" +
            "  rw [every_transition_has_disabled_precondition label before after step] at enabled\n  contradiction")
        theorem_names.extend(["every_transition_has_disabled_precondition", "no_enabled_contract_instances"])
    lines.extend([expressions.evidence_strings("completeIntentCodeAssociationReport", report),
        "def instructionMeaningInferred : Bool := false", "def wholeIntentSatisfied : Bool := false",
        "def sourceProgramSecurityProved : Bool := false"])
    source = "\n\n".join(lines)
    require(len(source.encode()) <= 4 * 1024 * 1024, "bounded_Intent_code_Lean_source_required")
    return source, {"profile": PROFILE, "report_sha256": expressions.digest(report), "verdict": status,
        "evaluated_contract_satisfied": status == "satisfied", "counterexample_present": status == "refuted",
        "enabled_case_count": report["enabled_case_count"], "case_count": len(report["cases"]),
        "counterexample_case_indices": report["counterexample_case_indices"], "case_verdict_theorems": case_proofs,
        "theorems": theorem_names, "source_state_lowering": code_details, "bounded_tla": code_details["bounded_tla"],
        "interpretation_carrier_sha256": carrier.sha256,
        "proof_scope": "explicit selected Intent precondition/effect interpretation over all finite source-derived code outcomes",
        "instruction_semantics_verified": False, "whole_intent_satisfied": False, "source_semantics_verified": False,
        "security_specification_inferred": False, "normative_compliance_verified": False, "kernel_executed": False,
        "proof_authority": False, "completion_authority": False, "execution_authority": False,
        "admitted": False, "qualified": False, "capability_floor_eligible": False,
        "assumptions": [*code_details["assumptions"],
            "The caller supplies the association from native Intent atoms to typed old/current state predicates; instruction meaning is not inferred.",
            "Effects are conditional on all selected native preconditions, with disabled cases retained and no-enabled cases denied positive satisfaction.",
            "Intent and code source identities remain separate; this is a selected-action contract, not whole-goal or workflow completion.",
            "A compiled counterexample is a refutation. All declared case truth values are checked by the same kernel build."]}


__all__ = ["PROFILE", "PRODUCERS", "emit_intent_code_effects"]
