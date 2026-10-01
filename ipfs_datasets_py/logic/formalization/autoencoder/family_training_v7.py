"""Source-bound Legal qualifiers and request-correlated UI confirmation targets.

Declarations are explicit caller inputs. Missing declarations preserve native
blockers; reproducing a declaration does not establish natural-language fidelity.
"""
from copy import deepcopy
import importlib

from . import family_training as core
from . import family_training_v6 as previous
from . import native_legal_qualified_lean as legal
from . import native_ui_confirmation_lean as ui

SCHEMA = "domain-family-training-targets/v7"
TypedFamilyEvidence = previous.TypedFamilyEvidence
ExplicitProjectionInterpretation = previous.ExplicitProjectionInterpretation
IntentEffectBindings = previous.IntentEffectBindings
LegalQualifierInterpretation = legal.LegalQualifierInterpretation
UIConfirmationInterpretation = ui.UIConfirmationInterpretation
supplemental_source_ref = previous.supplemental_source_ref
_PINS = {name: sha for module in (core, previous, legal, ui, importlib.import_module(__name__))
         for name, sha in core._pin(module).items()}


def _guard():
    from ....optimizers.logic_theorem_optimizer.autoencoder_schema_lake import _pin_imported_module
    for name, sha in _PINS.items():
        if _pin_imported_module(importlib.import_module(name)) != sha:
            raise ValueError("v7 qualifier target producer changed")


def _inputs(items, kind, domain, expected_domain):
    if type(items) not in (tuple, list) or len(items) > 32 or any(type(item) is not kind for item in items):
        raise ValueError("bounded immutable qualifier declarations required")
    if items and domain != expected_domain:
        raise ValueError("qualifier declaration belongs to another domain")
    return [item.to_dict() for item in items]


def _ui_binding_accounting(source_inputs, declarations):
    """Do not hide richer native policy classes behind identical 'before' text."""
    from .ui_training_inputs import prepare_ui_training_row
    from ...ui_ux_ir.formalize.roundtrip import _as_document
    document = (prepare_ui_training_row(source_inputs["ui_training_row"]).document
                if source_inputs.get("ui_training_row") is not None else _as_document(source_inputs.get("document")))
    bindings = document.action_bindings
    if not bindings or any(binding.risk_class.value != "high" or binding.confirmation_class.value != "confirm"
                           for binding in bindings):
        raise ValueError("request/token profile requires high-risk single-confirm native bindings; richer policies unresolved")
    declared = {formula["action_id"] for item in declarations for formula in item["formulas"]
                if formula.get("kind") == "UI_request_token_confirmation_policy"}
    if declared != {binding.action_id for binding in bindings}:
        raise ValueError("request/token declarations must account for every exact native action binding")
    return [{"binding_id": binding.binding_id, "action_id": binding.action_id,
             "risk_class": binding.risk_class.value, "confirmation_class": binding.confirmation_class.value,
             "disposition": "explicit_request_token_policy_not_runtime_authority"} for binding in bindings]


def _legal_literal_accounting(declarations):
    """One exact qualifier literal cannot acquire contradictory partition meanings."""
    bindings = {}
    for declaration in declarations:
        for formula in declaration["formulas"]:
            rows = [(item["source_text"], {"kind": "predicate", "expression": item["expression"]})
                    for item in formula["conditions"] + formula["exceptions"]]
            if formula["temporal"] is not None:
                temporal = formula["temporal"]
                rows.append((temporal["source_text"], {"kind": "duration", "interpretation": {
                    k: v for k, v in temporal.items() if k not in {"source_index", "source_text"}}}))
            for literal, interpretation in rows:
                if literal in bindings and bindings[literal] != interpretation:
                    raise ValueError("same Legal qualifier literal has conflicting cross-projection interpretations")
                bindings[literal] = interpretation
    return [{"source_text": literal, **bindings[literal]} for literal in sorted(bindings)]


def prepare_family_training_targets_v7(domain_id, *, legal_qualifier_inputs=(), ui_confirmation_inputs=(),
                                       **source_inputs):
    _guard()
    legal_declarations = _inputs(legal_qualifier_inputs, LegalQualifierInterpretation, domain_id, "legal_ir")
    ui_declarations = _inputs(ui_confirmation_inputs, UIConfirmationInterpretation, domain_id, "ui_ux_ir")
    declarations = legal_declarations + ui_declarations
    identities = [item["original_projection_id"] for item in declarations]
    if len(set(identities)) != len(identities):
        raise ValueError("one qualifier interpretation per original projection required")
    base = previous.prepare_family_training_targets_v6(domain_id, **source_inputs)
    report = deepcopy(base)
    report.update(schema=SCHEMA, v6_report_sha256=base["report_sha256"], v6_source_digest=base["source_digest"],
                  legal_qualifier_inputs=deepcopy(legal_declarations), ui_confirmation_inputs=deepcopy(ui_declarations),
                  superseded_v7_qualifier_observations=[],
                  ui_confirmation_binding_accounting=_ui_binding_accounting(source_inputs, ui_declarations)
                      if ui_declarations else [])
    report["producer_pins"].update(_PINS)
    source = supplemental_source_ref(domain_id, **source_inputs) if declarations else None
    for items, prepare in ((legal_qualifier_inputs, legal.prepare_qualified_payload),
                           (ui_confirmation_inputs, ui.prepare_ui_confirmation_payload)):
        for evidence in items:
            identity = evidence.to_dict()["original_projection_id"]
            matches = [row for row in report["projections"] if row["projection_id"] == identity]
            if len(matches) != 1:
                raise ValueError("qualifier must bind one active original projection; conflicting replacements are forbidden")
            original = matches[0]
            replacement = prepare(original, evidence, expected_source_ref=source)
            report["producer_pins"].update(replacement.pop("producer_pins"))
            archived = deepcopy(original)
            archived.update(active_for_training=False, replacement_projection_id=replacement["projection_id"],
                            superseded_reason="explicit_qualifier_interpretation_without_source_fidelity_claim")
            report["superseded_v7_qualifier_observations"].append(archived)
            original.update(replacement, ready_for_training=True, validation=[{
                "validator_id": "exact_source_bound_qualifier_interpretation", "stage": "target", "status": "passed",
                "details": {"source_meaning_verified": False, "Lake_executed": False}}])
    report["legal_qualifier_literal_accounting"] = _legal_literal_accounting(legal_declarations)
    digest = core._sha({"v6_source_digest": base["source_digest"],
                       "legal_qualifier_inputs": legal_declarations, "ui_confirmation_inputs": ui_declarations})
    report["source_digest"] = report["typed_input_digest"] = digest
    projection_ids = [row["projection_id"] for row in report["projections"]]
    if len(set(projection_ids)) != len(projection_ids):
        raise ValueError("duplicate qualified projection identity")
    for row in report["projections"]:
        row["source_digest"] = digest
        row["target_sha256"] = core._sha({k: v for k, v in row.items() if k != "target_sha256"})
    report["projections"].sort(key=lambda row: (row["logic_family"], row["projection_id"]))
    ready = {row["logic_family"] for row in report["projections"] if row["ready_for_training"]}
    for row in report["family_inventory"]:
        targets = [p for p in report["projections"] if p["logic_family"] == row["family_id"]]
        row.update(target_count=len(targets), ready_target_count=sum(p["ready_for_training"] for p in targets),
                   ready_for_training=row["family_id"] in ready)
        row["status"] = ("not_requested" if not row["requested"] else
                         "targets_available" if row["ready_for_training"] else "unsupported")
    report["ready_for_training"] = bool(ready)
    report["all_requested_families_available"] = set(report["requested_families"]) <= ready
    report["report_sha256"] = core._sha({k: v for k, v in report.items() if k != "report_sha256"})
    validate_family_training_report_v7(report)
    return report


def validate_family_training_report_v7(report, **source_inputs):
    _guard()
    if type(report) is not dict or report.get("schema") != SCHEMA:
        raise ValueError("native v7 report required")
    if report.get("report_sha256") != core._sha({k: v for k, v in report.items() if k != "report_sha256"}):
        raise ValueError("v7 report digest differs")
    if any(report.get("producer_pins", {}).get(name) != sha for name, sha in _PINS.items()):
        raise ValueError("v7 source producer pin differs")
    compatible = deepcopy(report)
    compatible["schema"] = core.SCHEMA
    compatible["report_sha256"] = core._sha({k: v for k, v in compatible.items() if k != "report_sha256"})
    core.validate_family_training_report(compatible)
    if (report.get("source_text_to_native_formula_inference") is not False or
            report.get("structural_readiness_is_qualification") is not False):
        raise ValueError("qualifier target preparation cannot claim source qualification")
    if source_inputs:
        inputs = dict(source_inputs)
        requested = inputs.pop("requested_families", report["requested_families"])
        if list(requested) != report["requested_families"]:
            raise ValueError("v7 replay family request differs")
        expected = prepare_family_training_targets_v7(report["domain_id"],
            requested_families=report["requested_families"], **inputs)
        if core._wire(expected) != core._wire(report):
            raise ValueError("v7 report differs from exact source and qualifier replay")
    return report
