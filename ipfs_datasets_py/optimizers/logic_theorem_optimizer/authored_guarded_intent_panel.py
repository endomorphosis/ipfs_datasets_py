"""Closed authored precondition/effect fixtures for the guarded Intent path.

Finite initial values and updates are explicit modeling assumptions, not facts
inferred from instructions. The negative fixture preserves a false precondition.
No corpus, heldout quality, source-code execution or normative truth is claimed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCHEMA = "authored-guarded-intent-panel/v1"
_SOURCE_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
FORMULAS = {
    "FOL": "forall x. Person(x) -> Reports(x)",
    "DFOL": "forall x. O(Reports(x))",
    "TFOL": "forall x. □(Reports(x))",
    "TDFOL": "forall x. O(□(Reports(x)))",
    "CEC": "K(Officer,Happens(Submit,Time))",
    "DCEC": "O(K(Officer,Happens(Submit,Time)))",
    "frame_logic": "alice[role -> officer].",
    "propositional": "p and q",
}


def _guard():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _SOURCE_SHA:
        raise ValueError("authored guarded fixture producer changed since import")


def source_inputs(index, *, include_false_precondition=False):
    """Return one exact native source and its complete explicit finite premises."""
    from ...logic.intent_ir.schema import (IntentIRDocument, IntentKind, IntentStatement,
        StatementKind, IntentModality, IntentAction, SourceRef)
    from ...logic.intent_ir.formalize.projection_contracts import source_ir_sha256
    _guard()
    if type(index) is not int or not 0 <= index < 3 or type(include_false_precondition) is not bool:
        raise ValueError("one of three authored fixtures and an explicit Boolean diagnostic mode required")
    actor, verb = (("officer", "publish"), ("custodian", "archive"), ("registrar", "inspect"))[index]
    initial_description = "false or true" if include_false_precondition else "true"
    text = (f"Authored guarded fixture {index}: {actor} is required and intends to {verb} report. "
        "The declared action requires report readiness and establishes completion. "
        f"Explicit finite model assumption: ready initially {initial_description}; completed initially false; "
        "the action sets completed true and preserves readiness. These are supplied abstract modeling declarations.")
    ref = SourceRef("source", "urn:authored:guarded-intent:" + str(index), "authored-guarded:" + str(index), "v1",
        content_sha256=hashlib.sha256(text.encode()).hexdigest())
    statements = (
        IntentStatement("goal:required", StatementKind.GOAL, IntentModality.REQUIRED,
            f"{actor} must {verb} report.", ("source",), verb, (actor, "report")),
        IntentStatement("goal:intended", StatementKind.GOAL, IntentModality.ASSERTED,
            f"{actor} intends to {verb} report.", ("source",), verb, (actor, "report")),
        IntentStatement("pre", StatementKind.PRECONDITION, IntentModality.ASSERTED,
            "Report is ready.", ("source",), "ready", ("report",)),
        IntentStatement("effect", StatementKind.EFFECT, IntentModality.ASSERTED,
            "Report operation is complete.", ("source",), "complete", ("report",)))
    action = IntentAction("action:declared", actor, verb, ("report",), ("source",),
        precondition_ids=("pre",), effect_ids=("effect",))
    document = IntentIRDocument("intent:authored-guarded:" + str(index), "Authored guarded Intent fixture",
        IntentKind.PROCEDURE, (ref,), statements, (action,), (), (action.action_id,), (action.action_id,))
    document.validate()
    workflow = {"semantics": "finite_guarded_state_flow", "source_ir_sha256": source_ir_sha256(document),
        "evidence_ref": "source", "variables": [
            {"variable_id": "ready", "kind": "boolean", "domain": [False, True],
             "initial_values": [False, True] if include_false_precondition else [True], "evidence_ref": "source"},
            {"variable_id": "completed", "kind": "boolean", "domain": [False, True],
             "initial_values": [False], "evidence_ref": "source"}],
        "predicate_bindings": [{"statement_id": "pre", "expression": {"op": "eq", "variable_id": "ready", "value": True},
                                "evidence_ref": "source"}],
        "action_updates": [{"action_id": "action:declared", "outcomes": [
            {"values": {"completed": True}, "evidence_ref": "source"}], "evidence_ref": "source"}],
        "retry_bounds": []}
    return {"document": document, "source_text": text,
            "context": {"state": {"max_steps": 4, "workflow": workflow}}}


def applicability_reviews(report, index):
    """Scope declarations for this closed fixture only; never waive a floor."""
    _guard()
    if report.get("domain_id") != "intent_ir" or type(index) is not int or not 0 <= index < 3:
        raise ValueError("closed authored Intent source required")
    present = {row["logic_family"] for row in report["projections"]}
    return [{"family_id": row["family_id"], "source_digest": report["source_digest"],
        "disposition": "inapplicable", "reason": "This authored integration fixture declares its exact Intent precondition/effect workflow, finite modeling assumptions, and eight explicit formulas; no additional model is supplied.",
        "evidence_refs": ["urn:authored-guarded-intent-panel:v1:" + str(index)]}
        for row in report["family_inventory"] if row["family_id"] not in present]


def effect_bindings(inputs):
    """One explicit interpretation of the exact authored completion statement."""
    from ...logic.formalization.autoencoder.native_intent_guarded_lean import IntentEffectBindings
    from ...logic.intent_ir.formalize.projection_contracts import source_ir_sha256
    _guard()
    return IntentEffectBindings.from_dict({"schema": "intent-guarded-effect-bindings/v1",
        "source_ir_sha256": source_ir_sha256(inputs["document"]),
        "bindings": [{"statement_id": "effect", "expression": {"op": "eq", "variable_id": "completed", "value": True},
                      "evidence_ref": "source"}]})


def prepare_case(index, *, include_false_precondition=False):
    """Prepare all requested families while retaining the full original premises."""
    from ...logic.formalization.autoencoder import family_training_v6 as targets
    from ...logic.formalization.autoencoder.native_formula_evidence import NativeFormulaEvidence
    _guard()
    inputs = source_inputs(index, include_false_precondition=include_false_precondition)
    source = targets.supplemental_source_ref("intent_ir", **inputs)
    inputs["formula_inputs"] = [NativeFormulaEvidence(name, formula, source) for name, formula in FORMULAS.items()]
    inputs["guarded_effect_bindings"] = effect_bindings(inputs)
    report = targets.prepare_family_training_targets_v6("intent_ir", **inputs)
    fixture = {"schema": SCHEMA, "index": index, "split": "diagnostic" if include_false_precondition else "train" if index < 2 else "tuning",
        "document": inputs["document"].to_dict(), "source_text": inputs["source_text"], "context": inputs["context"],
        "native_source_ref": source.to_dict(), "guarded_effect_bindings": inputs["guarded_effect_bindings"].to_dict(),
        "formula_inputs": [{"requirement_id": name, "formula": formula} for name, formula in FORMULAS.items()],
        "supplied_initial_values_are_modeling_assumptions": True,
        "false_precondition_in_initial_domain": include_false_precondition,
        "heldout": False, "qualified": False, "admitted": False, "source_semantics_verified": False,
        "scope": "caller-authored native precondition/effect records and explicit finite bindings; no inference of predicate truth"}
    return {"source_inputs": inputs, "report": report, "fixture": json.loads(json.dumps(fixture, allow_nan=False))}


__all__ = ["SCHEMA", "FORMULAS", "source_inputs", "effect_bindings", "prepare_case", "applicability_reviews"]
