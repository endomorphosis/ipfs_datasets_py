"""Explicit Intent/Security context joins for the existing native v7 projectors.

Context supplies declarations, not observations or inferred source truth. The
learned candidate is validated before these joins and is never repaired. In
particular, Security CodeUnit polarity must come from a caller declaration.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib

from .contracts import digest, raw, require
from .projection_context_contract import validate_context

_INTENT = {"rich_slot_context", "projection_context", "supplemental_inputs",
    "formula_inputs", "guarded_effect_bindings"}
_SECURITY = {"code_unit", "typed_inputs", "supplemental_inputs", "formula_inputs"}
_SUPPLEMENTAL = {
    "intent_ir": {"authorization", "trace", "program", "contract", "state", "transition", "temporal"},
    "security_ir": {"authorization", "protocol", "concurrency", "refinement", "trace"},
}


def _models(rows, owners, source, size):
    from ....security_ir.code_logic_projection import _validate_mapped_refs
    require(type(rows) is list and len(rows) <= 16, "bounded native model input list required")
    result, seen = [], set()
    for row in rows:
        require(type(row) is dict and set(row) == {"kind", "document"}
            and type(row["kind"]) is str and row["kind"] in owners
            and row["kind"] not in seen and type(row["document"]) is dict,
            "closed unique applicable native model kind required")
        seen.add(row["kind"])
        owner = owners[row["kind"]]
        native = owner.from_dict(row["document"])
        require(raw(native.to_dict()) == raw(row["document"]), "native model reconstruction changed declaration")
        _validate_mapped_refs(row["document"], source, size)
        result.append((row["kind"], native))
    return result


def decode_supplemental_inputs(domain, rows, source, source_size):
    """Decode a fixed owner registry; serialized class names are never loaded."""
    from ..family_training_v7 import TypedFamilyEvidence
    from ....software_verification.syntax_bridge import _KIND_TO_TYPE
    require(domain in _SUPPLEMENTAL, "Intent or Security supplemental domain required")
    owners = {kind.value: owner for kind, owner in _KIND_TO_TYPE.items()
        if kind.value in _SUPPLEMENTAL[domain]}
    return [TypedFamilyEvidence(native, source)
        for _, native in _models(rows, owners, source, source_size)]


def decode_formula_inputs(rows, source):
    from ..native_formula_evidence import NativeFormulaEvidence
    require(type(rows) is list and len(rows) <= 32, "bounded native formula input list required")
    result, seen = [], set()
    for row in rows:
        require(type(row) is dict and set(row) == {"requirement_id", "formula"},
            "closed native formula declaration required")
        value = NativeFormulaEvidence(row["requirement_id"], row["formula"], source)
        require(value.requirement_id not in seen, "duplicate native formula requirement")
        seen.add(value.requirement_id)
        result.append(value)
    return result


def security_source_ref(code_unit, source_text):
    """Return the exact native join for a caller's existing CodeUnit record."""
    from ....security_ir.cvefixes.schemas import CodeUnit
    from ..family_training_v7 import supplemental_source_ref
    require(type(source_text) is str and source_text.strip(), "exact nonempty source text required")
    unit = CodeUnit.from_dict(code_unit) if type(code_unit) is dict else code_unit
    require(type(unit) is CodeUnit, "explicit native CodeUnit required")
    return supplemental_source_ref("security_ir", code_unit=unit, source_bytes=source_text.encode("utf-8"))


def _intent(validated, source_text, inputs):
    from ....intent_ir.decoder import decode_intent_ir
    from ....intent_ir.formalize.rich_grammar import parse_instruction
    require(set(inputs) <= _INTENT, "unknown Intent projection context input")
    require(not ({"rich_slot_context", "projection_context"} <= set(inputs)),
        "rich slot and native projection contexts are distinct and exclusive")
    native = validated["native_ir"]
    if validated["kind"] == "intent_rich_ast":
        require(parse_instruction(source_text) == native, "intent candidate differs from exact source")
        if "projection_context" in inputs or "guarded_effect_bindings" in inputs:
            require(native["kind"] == "atom", "native projection context requires atomic or native Intent document")
            from ....intent_ir.formalize.rich_logic import project_rich_intent_logic
            native = decode_intent_ir(project_rich_intent_logic(native,
                instruction=source_text)["native_intent_ir"])
    else:
        require("rich_slot_context" not in inputs, "rich slot context requires a rich Intent AST")
        native = decode_intent_ir(native)
        source_sha = hashlib.sha256(source_text.encode()).hexdigest()
        require(bool(native.sources) and all(source.content_sha256 == source_sha for source in native.sources),
            "Intent native source hash differs")
    result = {"document": native, "source_text": source_text}
    for key in ("rich_slot_context", "projection_context"):
        if key in inputs:
            require(type(inputs[key]) is dict, "structured Intent context required")
            result["context"] = deepcopy(inputs[key])
    if "guarded_effect_bindings" in inputs:
        from ..family_training_v7 import IntentEffectBindings
        require("projection_context" in inputs, "guarded effect bindings require explicit native projection context")
        result["guarded_effect_bindings"] = IntentEffectBindings.from_dict(inputs["guarded_effect_bindings"])
    return result


def _rebind_derived_program(program, source):
    """Join an already verified scalar-source model to its declared CodeUnit.

    Only source identity references change. Original model identity remains in
    metadata, and native reconstruction validates the resulting source maps.
    Caller-supplied models never pass through this rebinder.
    """
    from ....software_verification.program import ProgramIR
    from ....security_ir.code_logic_projection import _validate_mapped_refs
    native = ProgramIR.from_dict(program)
    require(len(native.sources) == 1, "one exact derived program source required")
    previous = native.sources[0]
    require(previous.content_sha256 == source.content_sha256, "derived program source hash differs")
    original_sha, original_id = digest(program), native.program_id

    def rebind(value):
        if type(value) is list:
            return [rebind(item) for item in value]
        if type(value) is dict:
            if "ref_id" in value and "content_sha256" in value:
                require(value == previous.to_dict(), "derived program contains foreign source")
                return source.to_dict()
            result = {}
            for key, item in value.items():
                if key == "source_ref_ids":
                    require(all(ref == previous.ref_id for ref in item), "derived program contains foreign source ID")
                    result[key] = [source.ref_id for _ in item]
                elif key == "source_ref_id":
                    require(item == previous.ref_id, "derived program contains foreign source span")
                    result[key] = source.ref_id
                else:
                    result[key] = rebind(item)
            return result
        return value

    wire = rebind(deepcopy(program))
    wire.pop("program_id")
    wire["metadata"]["distributed_candidate_source_join"] = {
        "schema": "distributed-384-derived-program-source-join/v1",
        "original_program_sha256": original_sha, "original_program_id": original_id,
        "original_source_identifier": previous.ref_id, "code_unit_cid": source.ref_id,
        "source_sha256": source.content_sha256, "model_semantics_changed": False,
        "source_semantics_verified": False, "polarity_inferred": False}
    rebound = ProgramIR.from_dict(wire)
    # The family projector repeats bounds checking against the exact body.
    _validate_mapped_refs(rebound.to_dict(), source, 4_000_000)
    return rebound


def _security(validated, target, source_text, inputs):
    from ....security_ir.cvefixes.schemas import CodeUnit
    from ....security_ir.code_logic_projection import CodeLogicEvidence, _OWNERS
    require(set(inputs) <= _SECURITY, "unknown Security projection context input")
    require("code_unit" in inputs, "Security broader projections require an explicit CodeUnit including declared polarity")
    require(type(inputs["code_unit"]) is dict, "serialized CodeUnit declaration required")
    unit = CodeUnit.from_dict(inputs["code_unit"])
    require(raw(unit.to_dict()) == raw(inputs["code_unit"]), "CodeUnit reconstruction changed declaration")
    source = security_source_ref(unit, source_text)
    result = {"code_unit": unit, "source_bytes": source_text.encode("utf-8")}
    models = _models(inputs.get("typed_inputs", []), _OWNERS, source, len(result["source_bytes"]))
    if validated["kind"] == "program_expression":
        from ..security.source_program_binding_384_v2 import qualify_source_candidate
        require(unit.language.casefold() == "python", "scalar Security source binding requires Python CodeUnit")
        report = qualify_source_candidate(source_text, target)
        require(report["status"] == "qualified", "Security candidate source binding failed:" + report.get("reason", "unknown"))
        require(not any(kind == "program" for kind, _ in models), "supplied program cannot replace the learned scalar source model")
        program = report["projections"][0]["native_document"]
        models.insert(0, ("program", _rebind_derived_program(program, source)))
    else:
        require(validated["kind"] == "document", "supported Security target kind required")
        sources = validated["native_ir"]["sources"]
        require(any(row["content_sha256"] == source.content_sha256 for row in sources),
            "Security document requires an exact code source hash")
    result["typed_inputs"] = [CodeLogicEvidence(native, source) for _, native in models]
    return result


def prepare_source_inputs(domain, target, source_text, *, context=None):
    """Reconstruct typed native inputs without changing the learned candidate."""
    from ..source_training_v2 import validate_target
    from ..family_training_v7 import supplemental_source_ref
    require(domain in {"intent_ir", "security_ir"}, "Intent or Security projection domain required")
    require(type(source_text) is str and source_text.strip() and len(source_text.encode()) <= 1048576,
        "bounded exact source text required")
    validated = validate_target(domain, target)
    inputs = {} if context is None else validate_context(context, domain, target, source_text)
    result = _intent(validated, source_text, inputs) if domain == "intent_ir" else _security(validated, target, source_text, inputs)
    source = supplemental_source_ref(domain, **result)
    if "supplemental_inputs" in inputs:
        result["supplemental_inputs"] = decode_supplemental_inputs(domain,
            inputs["supplemental_inputs"], source, len(source_text.encode()))
    if "formula_inputs" in inputs:
        result["formula_inputs"] = decode_formula_inputs(inputs["formula_inputs"], source)
    return result


__all__ = ["prepare_source_inputs", "security_source_ref", "decode_supplemental_inputs", "decode_formula_inputs"]
