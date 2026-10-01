"""Closed authored Legal/UI qualifiers for native coverage and training checks.

These declarations are fixture premises, not a translator or corpus gold data.
The three sources per domain permit a small numerical handoff test only.
"""
from __future__ import annotations

from . import domain_reconstruction_panel as base
from .authored_semantic_projection_panel import FORMULAS

SCHEMA = "authored-legal-ui-qualifier-panel/v1"
DOMAINS = ("legal_ir", "ui_ux_ir")


def _atom(name, *arguments):
    return {"op": "atom", "predicate": {"name": name, "arguments": list(arguments)}}


def _legal_source(index):
    from .modal_ir import (ModalIRDocument, ModalIRFormula, ModalIROperator, ModalIRPredicate,
        ModalIRProvenance, ModalIRFrameLogic, ModalIRFrameLogicTriple)
    actor, verb = (("custodian", "submit"), ("registrar", "retain"), ("inspector", "preserve"))[index]
    symbol, label = (("O", "obligation"), ("P", "permission"), ("F", "prohibition"))[index]
    duration = ("within 10 days", "for at least 20 days", "for at least 24 hours")[index]
    condition = "request received and not withdrawn"
    exception = "emergency or closure"
    text = (f"Authored qualifier fixture {index}: {actor} has the declared {label} to {verb} record "
            f"{duration}, conditioned on {condition}, except {exception}. The separate interval view is an interpretation declaration.")
    identity = f"authored:legal-qualifier:{index}"
    provenance = ModalIRProvenance(identity, 0, len(text))
    formulas = [ModalIRFormula("norm:one", ModalIROperator("deontic", "D", symbol, label),
        ModalIRPredicate(verb, [actor, "record"], "clause"), provenance,
        conditions=[condition, duration], exceptions=[exception]),
        ModalIRFormula("time:one", ModalIROperator("temporal", "LTL", "F" if index == 0 else "G",
            "eventually" if index == 0 else "always"), ModalIRPredicate(verb, [actor, "record"], "clause"),
            provenance, conditions=[condition, duration], exceptions=[exception])]
    document = ModalIRDocument(identity, SCHEMA, text, formulas=formulas,
        frame_logic=ModalIRFrameLogic(selected_frame=verb, graph_id=identity,
            triples=[ModalIRFrameLogicTriple(actor, verb, "record")]))
    return {"document": document, "source_text": text}


def _envelope(module, row, source, formulas):
    return {"schema": module.EVIDENCE_SCHEMA, "source_ref": source.to_dict(),
        "original_projection_id": row["projection_id"], "original_source_digest": row["source_digest"],
        "original_payload_sha256": module.digest(row["payload"]),
        "declaration_scope": "caller_supplied_interpretation_not_source_translation", "formulas": formulas}


def _legal_declarations(index, report, source):
    from ...logic.formalization.autoencoder import native_legal_qualified_lean as legal
    declarations = []
    for family in ("deontic", "temporal"):
        row = next(p for p in report["projections"] if p["projection_id"] == f"legal-ir/modal-family/{family}/v3")
        formula, = row["payload"]["formulas"]
        expected_duration = ("within 10 days", "for at least 20 days", "for at least 24 hours")[index]
        if formula["conditions"] != ["request received and not withdrawn", expected_duration] or formula["exceptions"] != ["emergency or closure"]:
            raise ValueError("closed authored Legal qualifier fixture changed")
        declaration = {"formula_index": 0, "original_formula_sha256": legal.digest(formula),
            "kind": "activation_guarded_legal_rule", "activation_scope": "all_conditions_at_evaluation_origin",
            "conditions": [{"source_index": 0, "source_text": "request received and not withdrawn",
                "expression": {"op": "all", "operands": [_atom("request_received", "record"),
                    {"op": "not", "operand": _atom("withdrawn", "record")} ]}}],
            "temporal": {"source_index": 1, "source_text": expected_duration,
                "temporal_kind": "within_duration" if index == 0 else "minimum_duration",
                "quantity": (10, 20, 24)[index], "unit": "hour" if index == 2 else "day",
                "time_domain": "discrete_nat", "origin": "caller_supplied_evaluation_time",
                "lower_inclusive": True, "upper_inclusive": True},
            "exception_scope": "activation_time_waiver" if index == 0 else "per_tick_exemption",
            "exceptions": [{"source_index": 0, "source_text": "emergency or closure",
                "expression": {"op": "any", "operands": [_atom("emergency"), _atom("closure")]}}]}
        declarations.append(legal.LegalQualifierInterpretation.from_dict(_envelope(legal, row, source, [declaration])))
    return declarations


def _ui_declarations(index, report, source, action):
    from ...logic.formalization.autoencoder import native_ui_confirmation_lean as ui
    row = next(p for p in report["projections"] if p["projection_id"] == "ui_ux_ir:tdfol")
    expected = [("obligation", f"confirm({action}) before invoke({action})", "strict"),
        ("prohibition", f"invoke({action}) before confirm({action})", "strict"),
        ("prohibition", f"weaken_norm({action})", "strict")]
    if [(f["operator"], f["proposition"], f["strength"]) for f in row["payload"]["formulas"]] != expected:
        raise ValueError("closed authored UI qualifier fixture changed")
    declarations = []
    for offset, formula in enumerate(row["payload"]["formulas"]):
        item = {"formula_index": offset, "original_formula_sha256": ui.digest(formula), "kind": "atomic_UI_norm"}
        if offset < 2:
            item.update(kind="UI_request_token_confirmation_policy", action_id=action,
                policy="every_invocation_has_valid_confirmation" if offset == 0 else "unconfirmed_invocation",
                event_order="strict_sequence_position", time_domain="discrete_nat_ticks", clock_order="nondecreasing",
                max_age_ticks=(5, 10, 15)[index], freshness_upper_inclusive=True, correlation="action_request_token",
                cancellation="since_latest_confirmation", consumption="every_prior_invocation_consumes_token",
                trace_scope="finite_observed_prefix", unobserved_future="unknown")
        declarations.append(item)
    return [ui.UIConfirmationInterpretation.from_dict(_envelope(ui, row, source, declarations))]


def prepare_case(domain, index):
    from ...logic.formalization.autoencoder import family_training_v6 as previous, family_training_v7 as native
    from ...logic.formalization.autoencoder.native_formula_evidence import NativeFormulaEvidence
    if domain not in DOMAINS or type(index) is not int or not 0 <= index < 3:
        raise ValueError("closed authored Legal/UI case required")
    if domain == "legal_ir":
        inputs = _legal_source(index)
    else:
        selected = (base.rows(domain, "train")[0], base.rows(domain, "train")[2], base.rows(domain, "validation")[0])[index]
        inputs = base.source_inputs(selected)
    source = native.supplemental_source_ref(domain, **inputs)
    inputs["formula_inputs"] = [NativeFormulaEvidence(name, formula, source) for name, formula in FORMULAS.items()]
    original = previous.prepare_family_training_targets_v6(domain, **inputs)
    key = "legal_qualifier_inputs" if domain == "legal_ir" else "ui_confirmation_inputs"
    inputs[key] = (_legal_declarations(index, original, source) if domain == "legal_ir" else
                  _ui_declarations(index, original, source, inputs["ui_training_row"]["bindings"][0]["action_id"]))
    report = native.prepare_family_training_targets_v7(domain, **inputs)
    return {"source_inputs": inputs, "report": report, "original_report_sha256": original["report_sha256"],
        "fixture": {"schema": SCHEMA, "domain_id": domain, "index": index, "split": "train" if index < 2 else "tuning",
            "native_source_ref": source.to_dict(), "explicit_interpretations": [item.to_dict() for item in inputs[key]],
            "formula_inputs": [{"requirement_id": name, "formula": formula} for name, formula in FORMULAS.items()],
            "source_semantics_verified": False, "heldout": False, "qualified": False, "admitted": False,
            "scope": "authored source-bound policies; no corpus or natural-language fidelity claim"}}
