"""Closed ConcurrencyIR interpretations for labelled, state-preserving steps.

ConcurrencyIR carries textual guards and effects without an expression type
system. This interpreter consequently accepts only literal Boolean guards and
``skip`` effects. It does not assign an integer type to an untyped variable,
invent program counters, or replace opaque actions with propositions. Unsupported
features raise ``UnsupportedNativeLean`` before any source is returned.

The generated specification has real transition, ownership, fairness and finite
schedule semantics. Compiling these definitions does not prove their satisfaction
by a program, nor does a finite schedule establish infinite-trace fairness.
"""
from __future__ import annotations

import hashlib
import json

from ...software_verification.concurrency import ConcurrencyIR
from .native_family_lean_emitters import UnsupportedNativeLean, require, string
from . import native_concurrency_interpretation as interpreted

PROFILE = "native-concurrency-constant-guard-skip-lean/v1"
PRODUCERS = (interpreted, *interpreted.PRODUCERS)


def _list(values):
    return "[" + ", ".join(values) + "]"


def _conjunction(values):
    return " ∧ ".join("(" + value + ")" for value in values) or "True"


def _literal(text, label):
    require(text in ("true", "false"), label + "_requires_literal_Boolean")
    return {"true": "True", "false": "False"}[text]


def emit_concurrency(payload, *, interpretation=None):
    """Return a faithful closed-fragment interpretation, or reject the payload.

    Free-text *labels* and component names are provenance, never formulas.
    Statement fields which can carry semantic constraints accept only the
    explicit canonical strings documented below. This intentionally blocks the
    richer producer/consumer example until it has typed operational expressions.
    """
    if interpretation is not None:
        return interpreted.emit_interpreted_concurrency(payload, interpretation)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    require(len(encoded) <= 262144, "bounded_concurrency_payload_required")
    native = ConcurrencyIR.from_dict(payload)
    require(native.to_dict() == payload, "exact_native_concurrency_roundtrip_required")
    require(not payload["metadata"], "concurrency_metadata_semantics_not_lowered")
    for key in ("channels", "sessions", "linearizability_points"):
        require(not payload[key], "concurrency_" + key + "_semantics_not_lowered")
    collections = ("components", "steps", "atomic_regions", "interference", "fairness", "rely_guarantee", "schedules")
    require(all(len(payload[key]) <= 128 for key in collections), "bounded_concurrency_declarations_required")
    require(len(payload["shared_variable_ids"]) <= 128, "bounded_concurrency_variables_required")
    for key in collections:
        require(all(not row["attributes"] for row in payload[key]), "concurrency_" + key + "_attributes_not_lowered")

    components = payload["components"]
    steps = payload["steps"]
    component_symbols = {row["component_id"]: "Component.c" + str(index) for index, row in enumerate(components)}
    step_symbols = {row["step_id"]: "Step.s" + str(index) for index, row in enumerate(steps)}
    all_variables = list(payload["shared_variable_ids"])
    for component in components:
        require(len(component["local_variable_ids"]) <= 128, "bounded_concurrency_local_variables_required")
        all_variables.extend(component["local_variable_ids"])
    require(len(all_variables) == len(set(all_variables)), "concurrency_local_variable_ids_must_be_globally_distinct")
    for row in steps:
        _literal(row["guard_statement"], "concurrency_guard")
        require(row["effect_statement"] == "skip", "concurrency_effect_requires_typed_semantics_or_exact_skip")
        require(not row["read_variable_ids"] and not row["write_variable_ids"],
                "concurrency_skip_has_no_declared_reads_or_writes")

    region_steps = set()
    for row in payload["atomic_regions"]:
        require(row["atomicity"] == "atomic" and row["statement"] == "atomic" and len(row["step_ids"]) == 1,
                "concurrency_only_single_step_atomic_regions_supported")
        step = next(item for item in steps if item["step_id"] == row["step_ids"][0])
        require(step["atomic_region_id"] == row["region_id"] and step["step_id"] not in region_steps,
                "concurrency_atomic_region_membership_must_be_exact_and_disjoint")
        region_steps.add(step["step_id"])
    require(all(not row["atomic_region_id"] or row["step_id"] in region_steps for row in steps),
            "concurrency_step_atomic_membership_must_resolve_bidirectionally")

    interference_symbols = {}
    for index, row in enumerate(payload["interference"]):
        require(row["kind"] == "internal" and not row["shared_variable_ids"],
                "concurrency_only_internal_stateless_interference_supported")
        _literal(row["statement"], "concurrency_interference")
        interference_symbols[row["interference_id"]] = "interference_" + str(index)

    for row in payload["rely_guarantee"]:
        require(not row["shared_variable_ids"], "concurrency_rely_guarantee_shared_state_requires_typed_relations")
        _literal(row["rely_statement"], "concurrency_rely")
        _literal(row["guarantee_statement"], "concurrency_guarantee")
        for identifier in row["interference_ids"]:
            linked = next(item for item in payload["interference"] if item["interference_id"] == identifier)
            require(linked["subject_component_id"] == row["component_id"],
                    "concurrency_rely_interference_subject_differs")

    def selection(row, *, allow_empty):
        require(not (row["step_ids"] and row["component_ids"]), "concurrency_mixed_selector_interpretation_requires_explicit_semantics")
        if not row["step_ids"] and not row["component_ids"]:
            require(allow_empty, "concurrency_empty_fairness_selection")
            return list(step_symbols.values())
        if row["step_ids"]:
            return [step_symbols[key] for key in row["step_ids"]]
        require(len(row["component_ids"]) == 1, "concurrency_multiple_component_selector_requires_explicit_semantics")
        return [step_symbols[item["step_id"]] for item in steps if item["component_id"] in row["component_ids"]]

    for row in payload["fairness"]:
        require(row["statement"] == row["kind"], "concurrency_fairness_statement_requires_exact_kind")
        require(len(row["step_ids"]) <= 1, "concurrency_multiple_step_fairness_requires_explicit_semantics")
        require(selection(row, allow_empty=False), "concurrency_fairness_component_has_no_steps")
    for row in payload["schedules"]:
        require(row["statement"] == "bounded schedule", "concurrency_schedule_statement_requires_canonical_bound")
        require(row["max_steps"] <= 1048576, "bounded_concurrency_schedule_required")
        selection(row, allow_empty=True)

    lines = ["set_option linter.unusedVariables false", "inductive Component where\n" +
        "\n".join("  | c" + str(index) for index in range(len(components))) + "\n  deriving DecidableEq, Repr",
        "inductive ComponentKind where\n  | thread\n  | process\n  deriving DecidableEq, Repr",
        "inductive Actor where\n  | component (id : Component)\n  | environment\n  deriving DecidableEq, Repr",
        "inductive Step where\n" + "\n".join("  | s" + str(index) for index in range(len(steps))) + "\n  deriving DecidableEq, Repr"]

    def lookup(name, argument, codomain, pairs):
        lines.append("def " + name + " : " + argument + " → " + codomain + "\n" +
                     "\n".join("  | " + key + " => " + value for key, value in pairs))

    lookup("componentId", "Component", "String", [(component_symbols[row["component_id"]], string(row["component_id"])) for row in components])
    lookup("componentName", "Component", "String", [(component_symbols[row["component_id"]], string(row["name"])) for row in components])
    lookup("componentKind", "Component", "ComponentKind", [(component_symbols[row["component_id"]], "ComponentKind." + row["kind"]) for row in components])
    lookup("componentLocals", "Component", "List String", [(component_symbols[row["component_id"]], _list(map(string, row["local_variable_ids"]))) for row in components])
    lookup("stepId", "Step", "String", [(step_symbols[row["step_id"]], string(row["step_id"])) for row in steps])
    lookup("stepLabel", "Step", "String", [(step_symbols[row["step_id"]], string(row["label"])) for row in steps])
    lookup("stepActor", "Step", "Actor", [(step_symbols[row["step_id"]],
        "Actor.environment" if row["owner"] == "environment" else "Actor.component " + component_symbols[row["component_id"]]) for row in steps])
    lookup("stepEnabled", "Step", "Bool", [(step_symbols[row["step_id"]], row["guard_statement"]) for row in steps])
    lookup("stepAtomicRegion", "Step", "Option String", [(step_symbols[row["step_id"]],
        "some " + string(row["atomic_region_id"]) if row["atomic_region_id"] else "none") for row in steps])
    lines.extend([
        "def sharedVariables : List String := " + _list(map(string, payload["shared_variable_ids"])),
        "def declaredVariables : List String := " + _list(map(string, all_variables)),
        "def allSteps : List Step := " + _list(step_symbols.values()),
        "abbrev Store (Value : Type) := String → Value",
        "def stepRelation {Value : Type} (step : Step) (before after : Store Value) : Prop :=\n  stepEnabled step = true ∧ after = before",
        "def componentStep {Value : Type} (component : Component) (step : Step) (before after : Store Value) : Prop :=\n  stepActor step = Actor.component component ∧ stepRelation step before after",
        "def environmentStep {Value : Type} (step : Step) (before after : Store Value) : Prop :=\n  stepActor step = Actor.environment ∧ stepRelation step before after",
        "theorem step_preserves_store {Value : Type} (step : Step) (before after : Store Value)\n    (h : stepRelation step before after) : after = before := h.2",
        "theorem owners_disjoint {Value : Type} (component : Component) (step : Step) (before after : Store Value) :\n    ¬ (componentStep component step before after ∧ environmentStep step before after) := by\n  intro h\n  have wrong : Actor.component component = Actor.environment := h.1.1.symm.trans h.2.1\n  cases wrong",
        "structure Execution (Value : Type) where\n  state : Nat → Store Value\n  event : Nat → Step",
        "def validExecution {Value : Type} (trace : Execution Value) : Prop :=\n  ∀ time, stepRelation (trace.event time) (trace.state time) (trace.state (time + 1))",
        "def selectedEnabled (selected : List Step) : Prop := ∃ step, step ∈ selected ∧ stepEnabled step = true",
        "def infinitelyOften (predicate : Nat → Prop) : Prop := ∀ start, ∃ time, start ≤ time ∧ predicate time",
        "def continuouslyEventually (predicate : Nat → Prop) : Prop := ∃ start, ∀ time, start ≤ time → predicate time",
        "def weakFair {Value : Type} (selected : List Step) (trace : Execution Value) : Prop :=\n  continuouslyEventually (fun _ => selectedEnabled selected) → infinitelyOften (fun time => trace.event time ∈ selected)",
        "def strongFair {Value : Type} (selected : List Step) (trace : Execution Value) : Prop :=\n  infinitelyOften (fun _ => selectedEnabled selected) → infinitelyOften (fun time => trace.event time ∈ selected)",
        "def unconditionalFair {Value : Type} (selected : List Step) (trace : Execution Value) : Prop :=\n  infinitelyOften (fun time => trace.event time ∈ selected)",
        "def finiteExecution {Value : Type} (events : List Step) (before after : Store Value) : Prop :=\n  (∀ step ∈ events, stepEnabled step = true) ∧ after = before",
        "def requiresInterferenceDeclaration : Bool := " + str(payload["require_interference"]).lower(),
        "def requiresFairnessDeclaration : Bool := " + str(payload["require_fairness"]).lower(),
        "def documentIdentifier : String := " + string(payload["document_id"]),
    ])

    for index, row in enumerate(payload["atomic_regions"]):
        lines.append("def atomicRegion_" + str(index) + " : Component × Step := (" +
            component_symbols[row["component_id"]] + ", " + step_symbols[row["step_ids"][0]] + ")")
    for index, row in enumerate(payload["interference"]):
        actor = "Actor.environment" if row["interferer_is_environment"] else "Actor.component " + component_symbols[row["interferer_component_id"]]
        lines.extend([
            "def interferenceSubject_" + str(index) + " : Component := " + component_symbols[row["subject_component_id"]],
            "def interferenceId_" + str(index) + " : String := " + string(row["interference_id"]),
            "def interference_" + str(index) + " {Value : Type} (trace : Execution Value) : Prop :=\n  ∀ time, stepActor (trace.event time) = " + actor + " → " + _literal(row["statement"], "interference")])
    for index, row in enumerate(payload["fairness"]):
        function = {"weak": "weakFair", "strong": "strongFair", "unconditional": "unconditionalFair"}[row["kind"]]
        lines.extend([
            "def fairnessId_" + str(index) + " : String := " + string(row["fairness_id"]),
            "def fairness_" + str(index) + " {Value : Type} (trace : Execution Value) : Prop :=\n  " + function + " " + _list(selection(row, allow_empty=False)) + " trace"])
    for index, row in enumerate(payload["rely_guarantee"]):
        actor = "Actor.component " + component_symbols[row["component_id"]]
        assumptions = [interference_symbols[key] + " trace" for key in row["interference_ids"]]
        assumptions.append("∀ time, stepActor (trace.event time) ≠ " + actor + " → " + _literal(row["rely_statement"], "rely"))
        lines.extend([
            "def contractId_" + str(index) + " : String := " + string(row["contract_id"]),
            "def rely_" + str(index) + " {Value : Type} (trace : Execution Value) : Prop :=\n  " + _conjunction(assumptions),
            "def guarantee_" + str(index) + " {Value : Type} (trace : Execution Value) : Prop :=\n  ∀ time, stepActor (trace.event time) = " + actor + " → " + _literal(row["guarantee_statement"], "guarantee"),
            "def contract_" + str(index) + " {Value : Type} (trace : Execution Value) : Prop :=\n  rely_" + str(index) + " trace → guarantee_" + str(index) + " trace"])
    for index, row in enumerate(payload["schedules"]):
        lines.extend([
            "def scheduleId_" + str(index) + " : String := " + string(row["schedule_id"]),
            "def schedule_" + str(index) + " (events : List Step) : Prop :=\n  events.length ≤ " + str(row["max_steps"]) +
            " ∧ ∀ step ∈ events, step ∈ " + _list(selection(row, allow_empty=True)) + " ∧ stepEnabled step = true"])
    specification = ["validExecution trace"]
    for key, prefix in (("fairness", "fairness"), ("interference", "interference"), ("rely_guarantee", "contract")):
        specification.extend(prefix + "_" + str(index) + " trace" for index in range(len(payload[key])))
    lines.extend([
        "def declaredSpecification {Value : Type} (trace : Execution Value) : Prop :=\n  " + _conjunction(specification),
        "def sourceProgramVerified : Bool := false",
        "def unboundedRefinementProved : Bool := false",
    ])
    details = {
        "profile": PROFILE,
        "validator": "ConcurrencyIR_exact_constant_guard_skip_trace_interpretation",
        "payload_sha256": hashlib.sha256(encoded).hexdigest(),
        "component_symbols": component_symbols, "step_symbols": step_symbols,
        "operators": ["distinct_component_environment_actors", "literal_Boolean_guard", "unchanged_store", "labelled_execution", "weak_fairness", "strong_fairness", "unconditional_fairness", "finite_schedule_bound", "literal_rely_guarantee"],
        "assumptions": [
            "Only declared labelled steps occur; there is no invented stutter, program counter, source execution, or initial-state predicate.",
            "Every supported effect is exact skip and preserves an arbitrary Value-valued store; no state-variable sort is inferred.",
            "An atomic region must contain exactly one step; that transition has no internal interference point.",
            "Fairness constrains infinite labelled executions. Component selection denotes its step set; fairness is never inferred from finite schedules.",
            "Internal interference and rely/guarantee statements accept only literal true/false, retaining actor scopes and linked interference assumptions.",
            "Statement fields with other semantic content, channels, sessions, linearizability, multi-step atomicity, and shared-state contracts require separate typed lowerings.",
            "Specification and guarantee definitions are obligations, not asserted or discharged theorems about source software.",
        ],
        "capability_floor_eligible": False,
        "provided_capabilities": ["labelled_constant_guard_skip_concurrency", "distinct_environment_component_steps", "infinite_trace_fairness", "finite_schedule_bound"],
        "missing_capabilities": ["typed_state_mutation", "channel_session_semantics", "general_rely_guarantee", "linearizability"],
        "source_semantics_verified": False, "model_checker_executed": False,
        "unbounded_refinement_proved": False, "obligations_discharged": False, "admitted": False,
    }
    return "\n\n".join(lines), details


__all__ = ["emit_concurrency", "PROFILE", "UnsupportedNativeLean"]
