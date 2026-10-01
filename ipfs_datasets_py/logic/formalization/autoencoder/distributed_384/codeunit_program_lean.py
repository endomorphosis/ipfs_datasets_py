"""Replay a CodeUnit source join before lowering the unchanged scalar program.

The source/candidate gate is rerun. Its original complete operational model is
compiled by the existing v2 emitter; the exact CodeUnit and joined program are
retained as explicit evidence declarations. Hashes alone never replace replay.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib

from .contracts import digest, raw, require
from .projection_inputs import _rebind_derived_program, security_source_ref

PROFILE = "distributed-codeunit-source-program-lean/v1"
SOURCE_JOIN_SCHEMA = "distributed-384-derived-program-source-join/v1"
_JOIN_FIELDS = {"schema", "original_program_sha256", "original_program_id",
    "original_source_identifier", "code_unit_cid", "source_sha256",
    "model_semantics_changed", "source_semantics_verified", "polarity_inferred"}


def replay_original_program(payload, *, code_unit, source_text, candidate):
    """Prove exact reversible identity transport by deterministic data replay."""
    from ..security.source_program_binding_384_v2 import qualify_source_candidate
    from ....software_verification.program import ProgramIR
    from ....security_ir.cvefixes.schemas import CodeUnit
    require(type(payload) is dict, "native CodeUnit program required")
    unit = CodeUnit.from_dict(code_unit) if type(code_unit) is dict else code_unit
    require(type(unit) is CodeUnit and unit.language.casefold() == "python", "explicit Python CodeUnit required")
    source = security_source_ref(unit, source_text)
    qualification = qualify_source_candidate(source_text, candidate)
    require(qualification["status"] == "qualified", "candidate must match exact source before lowering")
    original = qualification["projections"][0]["native_document"]
    expected = _rebind_derived_program(original, source).to_dict()
    require(raw(payload) == raw(expected), "joined program differs from fresh source/candidate/CodeUnit replay")
    join = payload["metadata"]["distributed_candidate_source_join"]
    require(type(join) is dict and set(join) == _JOIN_FIELDS
        and join["schema"] == SOURCE_JOIN_SCHEMA
        and all(join[key] is False for key in ("model_semantics_changed", "source_semantics_verified", "polarity_inferred")),
        "closed non-authoritative source join required")
    previous = original["sources"][0]

    def restore(value):
        if type(value) is list:
            return [restore(item) for item in value]
        if type(value) is dict:
            if "ref_id" in value and "content_sha256" in value:
                require(value == source.to_dict(), "joined source differs during inverse replay")
                return deepcopy(previous)
            result = {}
            for key, item in value.items():
                if key == "source_ref_ids":
                    require(all(ref == source.ref_id for ref in item), "foreign source ID during inverse replay")
                    result[key] = [previous["ref_id"] for _ in item]
                elif key == "source_ref_id":
                    require(item == source.ref_id, "foreign source span during inverse replay")
                    result[key] = previous["ref_id"]
                else:
                    result[key] = restore(item)
            return result
        return value

    restored = restore(payload)
    del restored["metadata"]["distributed_candidate_source_join"]
    restored.pop("program_id")
    restored = ProgramIR.from_dict(restored).to_dict()
    require(raw(restored) == raw(original) and digest(restored) == join["original_program_sha256"]
        and restored["program_id"] == join["original_program_id"], "inverse program identity replay differs")
    return deepcopy(original), dict(profile=PROFILE, joined_program_sha256=digest(payload),
        original_program_sha256=digest(original), code_unit_sha256=digest(unit.to_dict()),
        code_unit_cid=unit.cid, candidate_sha256=digest(candidate),
        source_sha256=hashlib.sha256(source_text.encode()).hexdigest(),
        source_join=deepcopy(join), inverse_source_join_verified=True,
        source_candidate_replayed=True, original_metadata_retained=True,
        original_program_modified=False, source_semantics_verified=False,
        whole_program_semantics_verified=False, proof_authority=False,
        execution_authority=False, security_specification_inferred=False,
        caller_polarity_verified=False)


def emit_program(payload, *, code_unit, source_text, candidate):
    """Emit operational definitions and every retained declaration separately."""
    from .. import native_program_lean_v2
    from ..native_family_lean_emitters import string
    from ....security_ir.cvefixes.schemas import CodeUnit
    original, audit = replay_original_program(payload, code_unit=code_unit,
        source_text=source_text, candidate=candidate)
    unit = CodeUnit.from_dict(code_unit) if type(code_unit) is dict else code_unit
    source, details = native_program_lean_v2.emit_program(original)
    declarations = {
        "distributedCodeUnitDeclarationJSON": raw(unit.to_dict()).decode(),
        "distributedCodeUnitJoinedProgramJSON": raw(payload).decode(),
        "distributedCodeUnitCandidateJSON": raw(candidate).decode(),
        "distributedCodeUnitJoinAuditJSON": raw(audit).decode(),
    }
    header = "\n\n".join("def " + key + " : String := " + string(value)
        for key, value in declarations.items())
    header += "\n\ndef distributedCodeUnitSourceSemanticsVerified : Bool := false"
    header += "\n\ndef distributedCodeUnitPolarityVerified : Bool := false"
    details = deepcopy(details)
    details.update(profile=PROFILE, source_join_audit=audit,
        joined_program_sha256=digest(payload), code_unit_evidence_emitted=True,
        source_bytes_replayed=True, candidate_rewritten=False,
        code_unit_polarity_inferred=False, source_join_is_semantic_proof=False)
    details["assumptions"].append("CodeUnit vulnerable/fixed polarity is a caller declaration; its truth is not established by this source join.")
    return header + "\n\n" + source, details


__all__ = ["PROFILE", "SOURCE_JOIN_SCHEMA", "replay_original_program", "emit_program"]
