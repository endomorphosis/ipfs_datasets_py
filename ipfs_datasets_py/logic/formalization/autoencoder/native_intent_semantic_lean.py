"""Exact typed Intent formulas and ground Horn satisfaction definitions for Lean.

No generated axiom asserts an intention, assumption, obligation or action true.
The outer Lake gate must replay the complete v5 source report.
"""
from __future__ import annotations

import importlib
from copy import deepcopy
from . import intent_semantic_training_views as views
from . import family_training as core
from . import native_family_lean_emitters as old
from . import native_intent_lean as intent

_PINS = {name: sha for module in (views, core, old, intent, importlib.import_module(__name__))
         for name, sha in core._pin(module).items()}
_FAMILIES = {"first_order", "deontic", "intention_agency", "datalog", "horn_chc"}


def _guard():
    from ....optimizers.logic_theorem_optimizer.autoencoder_schema_lake import _pin_imported_module
    for name, sha in _PINS.items():
        old.require(_pin_imported_module(importlib.import_module(name)) == sha, "Intent_semantic_Lean_producer_drift")


def _formula(record):
    # verify_payload has already recreated the full record from its native
    # document, including the asserted-goal to intention distinction.
    atom = "(fun t => " + intent._atom(record["body"]) + ")"
    operator = record["operator"]
    if operator == "predicate":
        old.require(record["logic_family"] == "first_order", "ordinary_predicate_family_required")
        return atom
    if operator in ("O", "P", "F"):
        old.require(record["logic_family"] == "deontic", "deontic_operator_family_required")
        return 'i.modal ' + old.string("deontic:" + operator) + ' [] none ' + atom
    old.require(operator == "I" and record["actor"] and record["logic_family"] == "intention_agency",
        "exact_native_intention_actor_required")
    return 'i.cognitive "I" (i.agent ' + old.string(record["actor"]) + ') ' + atom


def emit_projection(row, *, report=None):
    """Lower only new semantic rows, fail closed on unhandled native statements."""
    if type(row) is not dict or not row.get("projection_id", "").startswith(views.PREFIX):
        raise NotImplementedError
    _guard()
    old.require(type(report) is dict and report.get("domain_id") == "intent_ir"
        and row.get("source_digest") == report.get("source_digest")
        and [r for r in report["projections"] if r["projection_id"] == row["projection_id"]] == [row],
        "exact_Intent_semantic_report_binding_required")
    payload = views.verify_payload(row["payload"])
    family = payload["family"]
    old.require(family in _FAMILIES and row.get("logic_family") == family
        and row["projection_id"] == views.PREFIX + family + "/v1", "unreviewed_Intent_semantic_family")
    old.require(row.get("ready_for_training") is True and payload["records"], "nonempty_ready_Intent_semantic_projection_required")
    if family in ("datalog", "horn_chc"):
        old.require(not payload["semantic_source"]["blocked"] and payload["rule_program"],
            "unknown_Intent_semantics_cannot_enter_ground_program")
    lines, operators = [], []
    for index, record in enumerate(payload["records"]):
        lines.append(f"def formula_{index} {{Entity Agent : Type}} (i : Interpretation Entity Agent) : Nat → Prop := " + _formula(record))
        operators.append(record["operator"])
    if family in ("datalog", "horn_chc"):
        clauses = [f"formula_{index} i t" for index in range(len(payload["records"]))]
        lines.append("def programSatisfaction {Entity Agent : Type} (i : Interpretation Entity Agent) (t : Nat) : Prop := "
            + " ∧ ".join("(" + c + ")" for c in clauses))
        eligible = payload["rule_program"]["capability_floor_eligible"]
    else:
        eligible = True
    return "\n".join(lines), {"validator": "native_Intent_exact_role_force_and_RuleFrontend_semantic_binding_replay",
        "operators": operators, "capability_floor_eligible": eligible,
        "capability_floor_reason": "typed_native_predicate_or_modal_view" if family not in ("datalog", "horn_chc") else
            "actual_assumed_domain_predicate_constraints" if eligible else "modal_atom_abstraction_is_not_domain_rule_inference",
        "retained_native_semantic_source": deepcopy(payload),
        "assumptions": ["These Lean definitions state interpretation constraints, never assert those constraints true.",
            "An asserted goal is intention I; required/permitted/prohibited remain O/P/F, never an event fact.",
            "Datalog/CHC ground atoms abbreviate explicit typed formulas. There is no closed-world negation, least-fixed-point execution, permission grant or modal inference calculus.",
            "Action declarations remain in their source-bound native partial-correctness projection, not in a fact database.",
            "Source-language meaning and execution/compliance are unverified."],
        "goals_asserted_true": False, "source_semantics_verified": False, "execution_authority": False}
