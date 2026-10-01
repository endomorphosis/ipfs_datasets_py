"""Closed authored fixtures for the four-domain live-gate training smoke.

The interpretations below are supplied author declarations, never a translator
for arbitrary source strings. This panel is neither federal-law gold nor heldout.
"""
from __future__ import annotations

import hashlib
from . import domain_reconstruction_panel as base

SCHEMA = "authored-semantic-projection-panel/v1"
DOMAINS = base.DOMAINS
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


def _require(value, message):
    if not value:
        raise ValueError(message)


def _intent(index, *, include_precondition=False):
    from ...logic.intent_ir.schema import (IntentIRDocument, IntentKind, IntentStatement,
        StatementKind, IntentModality, IntentAction, SourceRef)
    actor, verb = (("officer", "publish"), ("custodian", "archive"), ("registrar", "inspect"))[index]
    text = f"Authored native fixture {index}: {actor} requires and intends to {verb} report; report exists; the declared action yields completion."
    ref = SourceRef("source", "urn:authored:semantic-panel:"+str(index), "authored:"+str(index), "v1",
        content_sha256=hashlib.sha256(text.encode()).hexdigest())
    statements = (
        IntentStatement("goal:required", StatementKind.GOAL, IntentModality.REQUIRED,
            f"{actor} must {verb} report.", ("source",), verb, (actor,"report")),
        IntentStatement("goal:intended", StatementKind.GOAL, IntentModality.ASSERTED,
            f"{actor} intends to {verb} report.", ("source",), verb, (actor,"report")),
        IntentStatement("assumption", StatementKind.ASSUMPTION, IntentModality.ASSERTED,
            "Report exists.", ("source",), "exists", ("report",)),
        IntentStatement("effect", StatementKind.EFFECT, IntentModality.ASSERTED,
            "Report operation is complete.", ("source",), "complete", ("report",)))
    if include_precondition:
        statements += (IntentStatement("pre", StatementKind.PRECONDITION, IntentModality.ASSERTED,
            "Report exists.", ("source",), "exists", ("report",)),)
    action = IntentAction("action:declared", actor, verb, ("report",), ("source",),
        precondition_ids=("pre",) if include_precondition else (), effect_ids=("effect",))
    document = IntentIRDocument("intent:authored-semantic:"+str(index), "Authored semantic integration fixture", IntentKind.PROCEDURE,
        (ref,), statements, (action,), (), (action.action_id,), (action.action_id,))
    return {"document": document, "source_text": text}


def _evidence(row, declarations, source):
    from ...logic.formalization.autoencoder import native_qualified_lean as q
    return q.ExplicitProjectionInterpretation.from_dict({"schema":q.EVIDENCE_SCHEMA,
        "source_ref":source.to_dict(), "original_projection_id":row["projection_id"],
        "original_source_digest":row["source_digest"], "original_payload_sha256":q.digest(row["payload"]),
        "declaration_scope":"caller_supplied_interpretation_not_source_translation", "formulas":declarations})


def _declared_interpretations(domain, report, source, authored_row):
    from ...logic.formalization.autoencoder import native_qualified_lean as q
    declarations = []
    if domain == "legal_ir":
        for family in ("deontic", "temporal"):
            row = next(p for p in report["projections"] if p["projection_id"] == "legal-ir/modal-family/"+family+"/v3")
            formulas = row["payload"]["formulas"]
            _require(len(formulas) == 1 and formulas[0]["conditions"] == ["within 10 days"]
                and formulas[0]["exceptions"] == [] and formulas[0]["metadata"] == {},
                "authored closed-ten-day fixture changed; supply a new reviewed fixture version")
            item = {"formula_index":0, "original_formula_sha256":q.digest(formulas[0]),
                "kind":"bounded_temporal_qualification", "temporal":{"source_text":"within 10 days",
                    "temporal_kind":"within_duration", "quantity":10, "unit":"day", "time_domain":"discrete_nat",
                    "origin":"caller_supplied_evaluation_time", "lower_inclusive":True, "upper_inclusive":True},
                "exception_scope":"activation_time_waiver", "exceptions":[]}
            declarations.append(_evidence(row,[item],source))
    elif domain == "ui_ux_ir":
        row = next(p for p in report["projections"] if p["projection_id"] == "ui_ux_ir:tdfol")
        method = base.ACTIONS[authored_row["action"]]+"_"+base.OBJECTS[authored_row["actor"]]
        expected = [("obligation",f"confirm({method}) before invoke({method})","strict"),
            ("prohibition",f"invoke({method}) before confirm({method})","strict"),
            ("prohibition",f"weaken_norm({method})","strict")]
        formulas = row["payload"]["formulas"]
        _require([(f["operator"],f["proposition"],f["strength"]) for f in formulas] == expected
            and all(f["source_ref_ids"] == ["source:dom-aria:"+authored_row["source_id"]] for f in formulas),
            "authored UI source policies changed; this builder does not infer new policy semantics")
        items = []
        for index, formula in enumerate(formulas):
            item = {"formula_index":index,"original_formula_sha256":q.digest(formula),"kind":"atomic_UI_norm"}
            if index < 2:
                item.update(kind="UI_confirmation_policy",action_id=method,
                    policy="every_invocation_has_strict_prior_confirmation" if index==0 else "unconfirmed_invocation",
                    time_domain="discrete_nat",window_origin="caller_supplied_evaluation_time",strict_before=True,
                    correlation="action_id_only",freshness_modeled=False,token_consumption_modeled=False,cancellation_modeled=False)
            items.append(item)
        declarations.append(_evidence(row,items,source))
    return declarations


def prepare_case(domain, index, *, include_intent_precondition=False):
    """Prepare one of exactly three authored cases, with all eight formula inputs."""
    from ...logic.formalization.autoencoder import family_training_v4 as v4, family_training_v5 as v5
    from ...logic.formalization.autoencoder.native_formula_evidence import NativeFormulaEvidence
    _require(domain in DOMAINS and type(index) is int and 0 <= index < 3, "closed authored domain and case required")
    _require(type(include_intent_precondition) is bool and (domain == "intent_ir" or not include_intent_precondition),
        "explicit Intent-only precondition diagnostic required")
    selected = (base.rows(domain,"train")[0], base.rows(domain,"train")[2], base.rows(domain,"validation")[0])[index]
    _require(selected["variant"] == 0, "native variant-zero smoke fixture required")
    inputs = _intent(index, include_precondition=include_intent_precondition) if domain == "intent_ir" else base.source_inputs(selected)
    source = v4.supplemental_source_ref(domain, **inputs)
    inputs["formula_inputs"] = [NativeFormulaEvidence(name, formula, source) for name,formula in FORMULAS.items()]
    original = v4.prepare_family_training_targets_v4(domain, **inputs)
    explicit = _declared_interpretations(domain, original, source, selected)
    inputs["qualified_inputs"] = explicit
    report = v5.prepare_family_training_targets_v5(domain, **inputs)
    return {"source_inputs":inputs,"report":report,"original_report_sha256":original["report_sha256"],
        "fixture":{"schema":SCHEMA,"domain_id":domain,"index":index,"split":"train" if index < 2 else "tuning",
            "origin": "explicit_authored_Intent_contract" if domain == "intent_ir" else selected,
            "native_source_ref":source.to_dict(), "explicit_interpretations":[item.to_dict() for item in explicit],
            "formula_inputs":[{"requirement_id":name,"formula":formula} for name,formula in FORMULAS.items()],
            "source_semantics_verified":False,"heldout":False,"qualified":False,"admitted":False,
            "intent_contract_scope": ("diagnostic_precondition_plus_effect" if include_intent_precondition else
                "effect_only_contract_with_separate_assumption_no_state_guard") if domain == "intent_ir" else None,
            "known_unsupported_binding": "action_preconditions_have_no_reviewed_state_binding" if domain == "intent_ir" else None,
            "scope":"caller-authored native declarations and interpretation policies; not natural-language translation or corpus fidelity"}}
