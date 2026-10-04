"""Explicit UI component declarations into source-bound ground FOL targets.

This additive adapter keeps the v1 frame projection and adds only declarations
present in the supplied wire object. It never converts loader defaults, event
declarations, privacy labels, or presentation labels into behavioral claims.
The original candidate and source are retained; a source hash is not fidelity.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import fields
import hashlib
import importlib
import json

from . import ui_source_contract_384 as previous

SCHEMA = "source-ui-component-qualification/v2"
FALSE = {**previous.FALSE, "qualified": False, "admitted": False,
         "formalized": False, "promotion_performed": False}
_CLASSIFICATIONS = {"privacy_sensitivity": ("UIPrivacy", "privacy"),
                    "presentation_classification": ("UIPresentation", "presentation")}
_UNPROJECTED = ["privacy_policy", "presentation_behavior", "accessibility_compliance",
    "temporal_interaction", "authorization", "program_bindings",
    "guard_effect_and_priority_semantics", "observed_events_and_actor_cognition"]


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _source(source_text):
    if type(source_text) is not str or not source_text.strip() or len(source_text.encode()) > 131072:
        raise ValueError("bounded nonempty UI source text required")
    return hashlib.sha256(source_text.encode()).hexdigest()


def _raw_document(target):
    if type(target) is not dict:
        raise ValueError("native UI target object required")
    wrapped = set(target) == {"kind", "document"}
    return (target["kind"], target["document"]) if wrapped else ("document", target)


def _field_accounting(kind, raw, component_rows, available_families):
    """Account for wire presence, not values introduced by a native loader."""
    from ...ui_ux_ir.schema import UIComponent, UIIRDocument
    component_fields = {f.name for f in fields(UIComponent)}
    result = []
    for index, row in enumerate(component_rows):
        prefix = "/document" if kind == "ui_component" else f"/document/components/{index}"
        for name in sorted(component_fields):
            present = name in row
            if not present:
                disposition, families = "absent_not_projected", []
            elif name in {"component_id", "role"}:
                disposition, families = "explicit_declaration_projected", ["first_order", "frame_logic"]
            elif name in _CLASSIFICATIONS:
                disposition, families = "explicit_classification_projected", ["first_order"]
            elif name in {"parent_id", "child_ids"}:
                disposition, families = "frame_relationship_declaration", ["frame_logic"]
            elif name == "source_ref_ids":
                disposition, families = "provenance_retained_not_logical_claim", []
            else:
                disposition, families = "retained_uninterpreted", []
            result.append({"path": prefix + "/" + name, "supplied": present,
                "disposition": disposition, "declaration_families": families,
                "represented_families": sorted(set(families) & set(available_families)),
                "value_sha256": _digest(row[name]) if present else None})
    document_fields = []
    if kind == "document":
        metadata = {"document_id", "title", "schema_version", "sources", "tags", "producer"}
        for field in fields(UIIRDocument):
            name, present = field.name, field.name in raw
            disposition = ("absent_not_projected" if not present else
                "component_fields_accounted_separately" if name == "components" else
                "frame_relationship_declaration" if name == "composition_edges" else
                "metadata_retained_not_logical_claim" if name in metadata else "retained_uninterpreted")
            document_fields.append({"path": "/document/" + name, "supplied": present,
                "disposition": disposition, "value_sha256": _digest(raw[name]) if present else None})
    return {"component_fields": result, "document_fields": document_fields,
            "original_candidate_retained": True, "unrepresented_fields_are_not_reconstructed": True}


def _conjunction(atoms):
    if len(atoms) == 1:
        return atoms[0]
    middle = len(atoms) // 2
    return "(" + _conjunction(atoms[:middle]) + " and " + _conjunction(atoms[middle:]) + ")"


def _declarations(component_rows):
    if not 1 <= len(component_rows) <= 64:
        raise ValueError("explicit UI declaration capacity is 1 through 64 components; no truncation")
    # Namespace each value's semantic role: a component named 'button' is not
    # the role value 'button'. Encode exact UTF-8, never sanitize identifiers or
    # assign candidate-local numbers that make distinct labels loss-identical.
    values = set()
    declarations = []
    for row in component_rows:
        identity = ("component", row["component_id"])
        role = ("role", row["role"])
        declarations.extend((("UIComponent", (identity,), "component_id"),
                             ("UIRole", (identity, role), "role")))
        for field, (predicate, category) in _CLASSIFICATIONS.items():
            if field in row:
                declarations.append((predicate, (identity, (category, row[field])), field))
    for _, args, _ in declarations:
        values.update(args)
    # The native TDFOL parser treats bare identifiers as variables. A colon
    # qualified, generated symbol is a Constant, checked again below.
    symbols = {(category, value): f"ui_{category}:v{value.encode('utf-8').hex()}"
               for category, value in sorted(values)}
    table = [{"symbol": symbol, "category": category, "value": value}
             for (category, value), symbol in symbols.items()]
    records = [{"predicate": predicate, "arguments": [symbols[arg] for arg in args],
                "component_id": args[0][1], "source_field": field}
               for predicate, args, field in declarations]
    records.sort(key=lambda row: (row["predicate"], row["arguments"]))
    formula = _conjunction([row["predicate"] + "(" + ",".join(row["arguments"]) + ")" for row in records])
    if len(formula.encode()) > 16384:
        raise ValueError("UI ground formula exceeds native formula byte bound; no truncation")
    return formula, table, records


def _check_ground_ast(payload, declarations, symbols):
    from .native_formula_evidence import _walk
    nodes = list(_walk(payload["native_ast"]))
    predicates = [node for node in nodes if node.get("node_type") == "Predicate"]
    if any(node.get("node_type") in {"Variable", "QuantifiedFormula", "FunctionApplication",
            "DeonticFormula", "TemporalFormula"} for node in nodes):
        raise ValueError("explicit ground UI declarations changed into another native operator")
    actual = sorted((node["name"], tuple(arg["name"] for arg in node["arguments"])) for node in predicates
                    if all(arg.get("node_type") == "Constant" for arg in node["arguments"]))
    expected = sorted((row["predicate"], tuple(row["arguments"])) for row in declarations)
    if actual != expected or len(predicates) != len(declarations):
        raise ValueError("native parser changed explicit UI declaration structure")
    used = {arg for _, args in actual for arg in args}
    if used != {row["symbol"] for row in symbols}:
        raise ValueError("UI native constant/symbol table accounting differs")
    connectives = [node for node in nodes if node.get("node_type") == "BinaryFormula"]
    if len(connectives) != len(declarations) - 1 or any(node["operator"]["value"] != "∧" for node in connectives):
        raise ValueError("native parser changed explicit UI conjunction structure")
    return {"predicates": len(predicates), "conjunctions": len(connectives),
            "distinct_constants": len(used), "free_variables": 0,
            "quantifiers": 0, "modal_operators": 0}


def prepare_family_targets(source_text, target, requested_families=None):
    """Return ``report``, typed ``source_inputs`` for Lake replay, and JSON audit.

    The v7 report remains unchanged and validates through its existing owner.
    The adapter audit is a separate candidate-bound envelope. Full documents
    retain all fields, but this version interprets their component graph only.
    Native behavior/trace/authorization models must be supplied through their
    existing explicit contracts; no model is inferred here.
    """
    source_sha = _source(source_text)
    from . import family_training as core
    from . import family_training_v7 as training
    from .native_formula_evidence import NativeFormulaEvidence, prepare_native_formula_evidence
    from ...ui_ux_ir.formalize.roundtrip import RoundTripDocument
    graph, scope = previous._native(target)
    graph.validate()  # A dangling fragment needs context, even if labels parse.
    kind, raw = _raw_document(target)
    rows = [raw] if kind == "ui_component" else raw["components"]
    formula, symbols, declarations = _declarations(rows)
    candidate_sha = _digest(target)
    document = RoundTripDocument(document_id="ui-candidate:" + candidate_sha, component_graph=graph)
    source_inputs = {"document": document, "source_text": source_text}
    if requested_families is not None:
        source_inputs["requested_families"] = requested_families
    source_ref = training.supplemental_source_ref("ui_ux_ir", **source_inputs)
    evidence = NativeFormulaEvidence("FOL", formula, source_ref)
    native_formula = prepare_native_formula_evidence(evidence, source_ref)
    ground_structure = _check_ground_ast(native_formula["payload"], declarations, symbols)
    source_inputs["formula_inputs"] = (evidence,)
    report = training.prepare_family_training_targets_v7("ui_ux_ir", **source_inputs)
    # The adapter's full-candidate hash in document_id participates in v7's
    # exact typed-input digest; no field is lost from that provenance binding.
    available = sorted({row["logic_family"] for row in report["projections"] if row["ready_for_training"]})
    requested = report["requested_families"]
    audit = {"schema": SCHEMA, "status": "projected_candidate", "scope": scope,
        "source_sha256": source_sha, "candidate_sha256": candidate_sha,
        "candidate": deepcopy(target), "candidate_rewritten": False,
        "source_fidelity_check_required": True, "continue_planning": True,
        "projection_scope": "explicit_component_ground_declarations_and_existing_frame_relationships",
        "formula_scope": "ground_first_order_declarations_not_quantified_or_modal_policy",
        "symbol_table": symbols, "declarations": declarations,
        "native_formula": native_formula, "declaration_count": len(declarations),
        "ground_structure": ground_structure,
        "field_accounting": _field_accounting(kind, raw, rows, available),
        "unprojected_facets": list(_UNPROJECTED), "requested_families": requested,
        "available_families": available, "missing_requested_families": sorted(set(requested) - set(available)),
        "family_report_sha256": report["report_sha256"], "family_source_digest": report["source_digest"],
        "producer_pins": core._pin(importlib.import_module(__name__)),
        "native_defaults_promoted": False, "source_text_to_formula_inference": False,
        "lake_executed": False, **FALSE}
    audit["audit_sha256"] = _digest(audit)
    return {"report": report, "source_inputs": source_inputs, "audit": audit}


def qualify_source_candidate(source_text, target, requested_families=None):
    """JSON-only audit; real Lake and source fidelity remain separate gates."""
    source_sha = _source(source_text)
    try:
        prepared = prepare_family_targets(source_text, target, requested_families)
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        return {"schema": SCHEMA, "status": "invalid_or_missing_context", "source_sha256": source_sha,
            "reason": str(error)[:1024], "continue_planning": True, "candidate_rewritten": False,
            "projections": [], "lake_executed": False, **FALSE}
    return {"audit": prepared["audit"], "report": prepared["report"],
            "status": "projected_candidate", **FALSE}


def validate_prepared(prepared, source_text, target):
    """Replay the exact adapter binding, symbol table, declarations and v7 report."""
    if type(prepared) is not dict or not {"report", "source_inputs", "audit"} <= set(prepared):
        raise ValueError("prepared UI adapter envelope required")
    expected = prepare_family_targets(source_text, target, prepared["source_inputs"].get("requested_families"))
    if (expected["report"] != prepared["report"] or expected["audit"] != prepared["audit"]
            or expected["source_inputs"] != prepared["source_inputs"]):
        raise ValueError("UI adapter source/candidate/symbol/report replay differs")
    return True


__all__ = ["prepare_family_targets", "qualify_source_candidate", "validate_prepared"]
