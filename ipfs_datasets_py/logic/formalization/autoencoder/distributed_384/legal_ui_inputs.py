"""Bind unchanged Legal/UI decoder candidates to existing native projections.

Supplementary models, formula strings and UI behavior are caller declarations,
not inferred consequences of a decoded rule or component. Exact source and
candidate identity prevent reuse; they do not establish semantic fidelity.
"""
from dataclasses import fields

from .contracts import digest, raw, require
from .projection_context_contract import validate_context

ALLOWED_INPUTS = {
    "legal_ir": frozenset({"formula_inputs", "supplemental_inputs"}),
    "ui_ux_ir": frozenset({"ui_training_row", "formula_inputs", "supplemental_inputs",
                            "ui_confirmation_inputs"}),
}
SUPPLEMENTAL_KINDS = {
    "legal_ir": frozenset({"authorization", "temporal", "trace"}),
    "ui_ux_ir": frozenset({"program", "contract", "state", "transition", "temporal",
                            "trace", "authorization"}),
}


def _sequence(inputs, key, bound):
    values = inputs.get(key, [])
    require(type(values) is list and len(values) <= bound, "bounded JSON " + key + " list required")
    return values


def _ui_document(validated, target, row):
    from ..ui_source_contract_384 import _native
    from ....ui_ux_ir.schema import UIComponent
    from ....ui_ux_ir.formalize.roundtrip import RoundTripDocument
    graph, _ = _native(target)
    if row is None:
        return {"document": RoundTripDocument("candidate:" + digest(target), component_graph=graph)}
    # The prepared row is a wider model. Its one component must be exactly the
    # candidate, including provenance and binding IDs, not merely share its ID.
    require(validated["kind"] == "ui_component",
            "UI training context requires an exact component candidate; full document widening is unsupported")
    from ..ui_training_inputs import prepare_ui_training_row
    prepared = prepare_ui_training_row(row)
    candidate = validated["native_ir"]
    matches = [component for component in prepared.document.component_graph.components
               if component.component_id == candidate["component_id"]]
    require(len(matches) == 1, "UI training context must contain one unique candidate component")
    component = matches[0]
    envelope = UIComponent(**{field.name: getattr(component, field.name) for field in fields(UIComponent)})
    require(raw(envelope.to_dict()) == raw(candidate),
            "UI training context component differs from exact decoded candidate")
    # Check richer semantic fields too, so dropping an unexpressed field cannot
    # manufacture an exact match under a narrower envelope schema.
    require(raw(component.to_dict()) == raw(graph.components[0].to_dict()),
            "UI training context adds undeclared component semantics")
    # The family core makes ui_training_row exclusive with source_text. Pass
    # the validated native document so supplemental refs can still bind the
    # actual prompt. The portable context separately retains the full row.
    return {"document": prepared.document}


def _supplemental(domain, declarations, source, source_text):
    from ..family_training_v7 import TypedFamilyEvidence
    from ....software_verification import syntax_bridge
    from ....security_ir.code_logic_projection import _validate_mapped_refs
    result, seen = [], set()
    for declaration in declarations:
        require(type(declaration) is dict and set(declaration) == {"kind", "document"},
                "closed supplemental kind/document declaration required")
        kind, wire = declaration["kind"], declaration["document"]
        require(type(kind) is str and kind in SUPPLEMENTAL_KINDS[domain],
                "supplemental native kind is not applicable to this domain")
        require(kind not in seen, "duplicate supplemental native kind")
        require(type(wire) is dict, "supplemental document object required")
        seen.add(kind)
        owner = syntax_bridge._KIND_TO_TYPE[syntax_bridge.SoftwareVerificationIRKind(kind)]
        native = owner.from_dict(wire)
        require(raw(native.to_dict()) == raw(wire), "supplemental native reconstruction changed declaration")
        _validate_mapped_refs(wire, source, len(source_text.encode()))
        result.append(TypedFamilyEvidence(native, source))
    return result


def prepare_source_inputs(domain, target, source_text, *, context=None):
    """Return v7 kwargs without rewriting the predicted rule or component.

The optional portable context must be issued by ``bind_context`` for these
exact candidate/source bytes. Formula and supplementary rows are rehydrated
only through the native whitelist, with SourceRef derived from the source.
    """
    from ..source_training_v2 import validate_target
    from ..family_training_v7 import supplemental_source_ref, UIConfirmationInterpretation
    from ..native_formula_evidence import NativeFormulaEvidence, prepare_native_formula_evidence
    require(domain in ALLOWED_INPUTS, "Legal or UI domain required")
    require(type(source_text) is str and source_text.strip()
            and len(source_text.encode()) <= 1048576, "bounded nonempty exact source text required")
    validated = validate_target(domain, target)
    supplied = {} if context is None else validate_context(context, domain, target, source_text)
    require(type(supplied) is dict and set(supplied) <= ALLOWED_INPUTS[domain],
            "closed " + domain + " projection context inputs required")
    if domain == "legal_ir":
        from ....legal_ir.canonical_contracts import CanonicalRoundTripIR
        result = {"document": CanonicalRoundTripIR.from_dict(validated["canonical_ir"])}
    else:
        if "ui_training_row" in supplied:
            require(type(supplied["ui_training_row"]) is dict, "UI training row object required")
        result = _ui_document(validated, target, supplied.get("ui_training_row"))
    result["source_text"] = source_text
    source = supplemental_source_ref(domain, **result)
    if "formula_inputs" in supplied:
        formulas, seen = [], set()
        for declaration in _sequence(supplied, "formula_inputs", 32):
            require(type(declaration) is dict and set(declaration) == {"requirement_id", "formula"},
                    "closed requirement_id/formula declaration required")
            item = NativeFormulaEvidence(declaration["requirement_id"], declaration["formula"], source)
            require(item.requirement_id not in seen, "duplicate named formula requirement")
            seen.add(item.requirement_id)
            prepare_native_formula_evidence(item, source)
            formulas.append(item)
        result["formula_inputs"] = formulas
    if "supplemental_inputs" in supplied:
        result["supplemental_inputs"] = _supplemental(domain,
            _sequence(supplied, "supplemental_inputs", 16), source, source_text)
    if "ui_confirmation_inputs" in supplied:
        require("ui_training_row" in supplied, "UI confirmation interpretation requires matched native training row")
        declarations, seen = [], set()
        for wire in _sequence(supplied, "ui_confirmation_inputs", 32):
            item = UIConfirmationInterpretation.from_dict(wire)
            frozen = item.to_dict()
            require(frozen["source_ref"] == source.to_dict(), "UI confirmation source differs from exact source text")
            require(frozen["original_projection_id"] not in seen, "duplicate UI confirmation projection")
            seen.add(frozen["original_projection_id"])
            declarations.append(item)
        result["ui_confirmation_inputs"] = declarations
    return result


__all__ = ["ALLOWED_INPUTS", "SUPPLEMENTAL_KINDS", "prepare_source_inputs"]
