"""Two explicitly assumed companions of the unresolved Legal/UI audit fixtures.

These are synthetic interpretation fixtures, not context retrieval or source
qualification. Originals remain unchanged negative controls. Supplied policies
can support native lowering while reviews, floors and truth claims stay separate.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

from . import domain_reconstruction_panel as base

SCHEMA = "provisional-context-companion/v1"
DOMAINS = ("legal_ir", "ui_ux_ir")
_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
FALSE = {"source_semantics_verified": False, "qualified": False, "admitted": False,
         "formalized": False, "constitution_formalized": False,
         "context_retrieval_executed": False, "training_executed": False,
         "event_occurrences_attested": False, "backend_execution_verified": False}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _assumptions(domain):
    if domain == "legal_ir":
        return {
            "authority": "explicit_provisional_fixture_premises_not_retrieved_source_facts",
            "clock_domain": "discrete_natural_number_days_no_calendar_or_business_day_claim",
            "deadline_origin": "caller_supplied_evaluation_origin",
            "trigger_binding": "fixture_author_declares_origin_as_synthetic_receipt_trigger_no_occurrence_attestation",
            "quantity": 10, "unit": "day", "lower_inclusive": True, "upper_inclusive": True,
            "modal_scope": "obligation_of_bounded_eventually",
            "temporal_view_role": "auxiliary_body_of_obligation_not_asserted_actual_event",
            "concrete_origin_or_event_trace_supplied": False,
        }
    return {
        "authority": "explicit_provisional_fixture_premises_not_retrieved_application_policy",
        "event_order": "strict_sequence_position", "clock_order": "nondecreasing",
        "time_domain": "discrete_nat_ticks", "max_age_ticks": 10,
        "freshness_upper_inclusive": True, "correlation": "action_request_token",
        "cancellation": "since_latest_confirmation",
        "consumption": "every_prior_invocation_consumes_token",
        "trace_scope": "finite_observed_prefix", "unobserved_future": "unknown",
        "observation_origin": "caller_supplied_sequence_position",
        "request_token_trace_supplied": False,
        "whole_workflow_verified": False,
        "scope_note": "Synthetic activate and declared finished state establish neither invocation nor completion.",
    }


def _companion_inputs(domain, original, identity, assumptions):
    if domain == "legal_ir":
        from .modal_ir import ModalIRProvenance
        text = original["source_text"] + (
            " Provisional authored context: the caller-supplied evaluation origin denotes a synthetic receipt "
            "trigger. Time is discrete natural-number days with an inclusive ten-day interval. "
            "The temporal view is the auxiliary body inside the obligation, not an assertion of actual "
            "publication. No concrete trigger occurrence or calendar convention is attested.")
        old = deepcopy(original["document"])
        provenance = ModalIRProvenance(identity, 0, len(text))
        document = replace(old, document_id=identity, source=SCHEMA, normalized_text=text,
            formulas=[replace(f, provenance=provenance) for f in old.formulas],
            frame_logic=replace(old.frame_logic, graph_id=identity))
        return {"document": document, "source_text": text}
    row = deepcopy(original["ui_training_row"])
    # Keep the original group and partition to prevent companions leaking across
    # holdouts. The native closed row cannot carry arbitrary authority metadata.
    row["provenance"].update(dataset=SCHEMA, revision="authored-provisional-context-v1", row_id=identity)
    row["dom_aria"].update(document_id=identity, source_id=identity,
                           source_revision="authored-provisional-context-v1")
    row["dom_aria"]["root"]["description"] = (
        "Provisional authored request/token confirmation policy; not observed execution. "
        "Assumptions SHA256 " + _digest(assumptions))
    return {"ui_training_row": row}


def _envelope(module, row, source, declarations):
    return {"schema": module.EVIDENCE_SCHEMA, "source_ref": source.to_dict(),
        "original_projection_id": row["projection_id"], "original_source_digest": row["source_digest"],
        "original_payload_sha256": module.digest(row["payload"]),
        "declaration_scope": "caller_supplied_interpretation_not_source_translation", "formulas": declarations}


def _legal_declarations(report, source):
    from ...logic.formalization.autoencoder import native_legal_qualified_lean as legal
    declarations, rows = [], {}
    for family in ("deontic", "temporal"):
        row = next(p for p in report["projections"] if p["projection_id"] == f"legal-ir/modal-family/{family}/v3")
        formula, = row["payload"]["formulas"]
        _require(formula["conditions"] == ["within 10 days"] and formula["exceptions"] == [],
                 "exact unresolved Legal duration required")
        rows[family] = formula
        declaration = {"formula_index": 0, "original_formula_sha256": legal.digest(formula),
            "kind": "activation_guarded_legal_rule", "activation_scope": "all_conditions_at_evaluation_origin",
            "conditions": [], "temporal": {"source_index": 0, "source_text": "within 10 days",
                "temporal_kind": "within_duration", "quantity": 10, "unit": "day", "time_domain": "discrete_nat",
                "origin": "caller_supplied_evaluation_time", "lower_inclusive": True, "upper_inclusive": True},
            "exception_scope": "activation_time_waiver", "exceptions": []}
        declarations.append(legal.LegalQualifierInterpretation.from_dict(_envelope(legal, row, source, [declaration])))
    _require(rows["deontic"]["predicate"] == rows["temporal"]["predicate"], "auxiliary temporal body predicate differs")
    _require(rows["deontic"]["operator"] == {"family": "deontic", "system": "D", "symbol": "O", "label": "obligation"}
             and rows["temporal"]["operator"] == {"family": "temporal", "system": "LTL", "symbol": "F", "label": "eventually"},
             "exact obligation-of-eventually companion required")
    return declarations, {"kind": "declared_auxiliary_body_relation_not_independent_fact",
        "norm_formula_id": rows["deontic"]["formula_id"], "body_formula_id": rows["temporal"]["formula_id"],
        "norm_projection_id": "legal-ir/modal-family/deontic/v3/explicit-legal-interpretation/v1",
        "body_projection_id": "legal-ir/modal-family/temporal/v3/explicit-legal-interpretation/v1",
        "body_predicate_sha256": _digest(rows["deontic"]["predicate"]),
        "meaning": "O(bounded_eventually(publish)); temporal view is an auxiliary body, not actual publication",
        "independent_event_fact": False, "typed_AST_containment_verified": False,
        "scope": "fixture-level declaration; existing generic partition producer does not encode native AST containment"}


def _ui_declarations(report, source, action, assumptions):
    from ...logic.formalization.autoencoder import native_ui_confirmation_lean as ui
    row = next(p for p in report["projections"] if p["projection_id"] == "ui_ux_ir:tdfol")
    expected = [("obligation", f"confirm({action}) before invoke({action})", "strict"),
        ("prohibition", f"invoke({action}) before confirm({action})", "strict"),
        ("prohibition", f"weaken_norm({action})", "strict")]
    _require([(f["operator"], f["proposition"], f["strength"]) for f in row["payload"]["formulas"]] == expected,
             "exact unresolved UI formula partition required")
    policies = ("every_invocation_has_valid_confirmation", "unconfirmed_invocation")
    declarations = []
    for index, formula in enumerate(row["payload"]["formulas"]):
        declaration = {"formula_index": index, "original_formula_sha256": ui.digest(formula), "kind": "atomic_UI_norm"}
        if index < 2:
            declaration.update(kind="UI_request_token_confirmation_policy", action_id=action, policy=policies[index],
                **{key: assumptions[key] for key in ("event_order", "clock_order", "time_domain", "max_age_ticks",
                    "freshness_upper_inclusive", "correlation", "cancellation", "consumption", "trace_scope", "unobserved_future")})
        declarations.append(declaration)
    return [ui.UIConfirmationInterpretation.from_dict(_envelope(ui, row, source, declarations))]


def prepare_companion(domain):
    """Prepare one negative control and one explicitly assumed companion.

    Every original/native projection stays accounted for. This performs no
    retrieval, tool execution, training, applicability review or admission.
    """
    from ...logic.autoformal.tree_pin import require_workspace_logic_tree
    from ...logic.formalization.autoencoder import family_training_v6 as previous, family_training_v7 as targets
    from ...logic.formalization.autoencoder import projection_context_audit as audit
    from ...logic.formalization.autoencoder.native_formula_evidence import NativeFormulaEvidence
    require_workspace_logic_tree()
    _require(domain in DOMAINS, "closed Legal/UI companion domain required")
    _require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SOURCE_SHA256, "companion producer changed")
    _require(hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest() == audit.FIXTURE_SHA256,
             "negative fixture producer changed")
    row = base.rows(domain, "train")[0]
    original_inputs = base.source_inputs(row)
    original = audit._source_record(domain, row, original_inputs)
    assumptions = _assumptions(domain)
    identity = row["source_id"] + ":provisional-context-v1"
    inputs = _companion_inputs(domain, original_inputs, identity, assumptions)
    for collection in (original_inputs, inputs):
        source = targets.supplemental_source_ref(domain, **collection)
        collection["formula_inputs"] = [NativeFormulaEvidence(name, formula, source)
                                        for name, formula in audit.FORMULAS.items()]
    original_report = targets.prepare_family_training_targets_v7(domain, **original_inputs)
    unqualified = previous.prepare_family_training_targets_v6(domain, **inputs)
    source = targets.supplemental_source_ref(domain, **inputs)
    relation = None
    if domain == "legal_ir":
        inputs["legal_qualifier_inputs"], relation = _legal_declarations(unqualified, source)
        declaration_key = "legal_qualifier_inputs"
    else:
        declaration_key = "ui_confirmation_inputs"
        inputs[declaration_key] = _ui_declarations(unqualified, source,
            inputs["ui_training_row"]["bindings"][0]["action_id"], assumptions)
    report = targets.prepare_family_training_targets_v7(domain, **inputs)
    _require(len(report["requested_families"]) == len(report["family_inventory"]) == 40, "complete family inventory required")
    _require(len(report["projections"]) == len(original_report["projections"]), "companion omitted a projection")
    expected_ids = set(audit.BLOCKERS[domain])
    _require({p["projection_id"] for p in report["superseded_v7_qualifier_observations"]} == expected_ids,
             "companion must replace exactly the historically blocked projections")
    companion_payload = ({"source_text": inputs["source_text"], "document": inputs["document"].to_dict()}
        if domain == "legal_ir" else {"ui_training_row": deepcopy(inputs["ui_training_row"])})
    fixture = {"schema": SCHEMA, "domain_id": domain, "companion_source_id": identity,
        "original_source_id": row["source_id"], "original_group_id": row["group_id"],
        "original_input_payload": original["input_payload"], "original_input_payload_sha256": original["input_payload_sha256"],
        "original_report_sha256": original_report["report_sha256"], "original_source_digest": original_report["source_digest"],
        "companion_input_payload": companion_payload, "companion_input_payload_sha256": _digest(companion_payload),
        "companion_source_ref": source.to_dict(), "companion_source_digest": report["source_digest"],
        "companion_report_sha256": report["report_sha256"], "assumptions": assumptions,
        "assumptions_sha256": _digest(assumptions), "legal_auxiliary_view_relation": relation,
        "explicit_interpretations": [item.to_dict() for item in inputs[declaration_key]],
        "retained_negative_projection_ids": sorted(expected_ids),
        "native_AST_scope_repair_executed": False, "capability_floor_credit_from_interpretations": False,
        "scope": "provisional synthetic interpretation companion; source and runtime facts remain unverified",
        "producer_sha256": _SOURCE_SHA256, **FALSE}
    fixture["fixture_sha256"] = _digest(fixture)
    return {"original_source_inputs": original_inputs, "original_report": original_report,
        "source_inputs": inputs, "report": report, "fixture": fixture}


__all__ = ["SCHEMA", "DOMAINS", "prepare_companion"]
