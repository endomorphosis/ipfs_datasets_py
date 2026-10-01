"""Explicit source/effect metadata evidence for the bounded ProgramIR emitter.

Only the closed source-binding v2 profile is admitted. Metadata is checked and
rendered as named Lean evidence declarations; it is never silently discarded.
An internal, independently identified operational view reuses the reviewed v1
renderer after metadata extraction. The original document is not mutated.
Source bytes must be replayed by the caller's source qualification gate: this
emitter checks the consistency of declared hashes and effect provenance only.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re

from ...software_verification.program import ProgramIR
from . import native_program_lean as previous
from .native_family_lean_emitters import require, string

PROFILE = "native-source-program-straight-line-lean/v2"
AUTHORITY = dict(proof_authority=False, execution_authority=False,
    completion_authority=False, source_semantics_verified=False,
    whole_program_semantics_verified=False, security_specification_inferred=False)


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _closed(value, fields, reason):
    require(type(value) is dict and set(value) == set(fields), reason)


def _ids(values, symbols):
    require(type(values) is list and all(type(value) is str and value in symbols for value in values)
        and values == sorted(set(values)), "closed_canonical_effect_symbol_ids_required")


def _metadata(payload):
    from .security import source_program_binding_384 as origin
    from .security import source_program_binding_384_v2 as effects
    metadata = payload["metadata"]
    original_keys = {"adapter", "assumptions", "input_type_basis", "language", "path",
        "source_binding_schema", "source_sha256", *AUTHORITY}
    _closed(metadata, original_keys | set(effects.METADATA_EXTENSION_KEYS), "closed_source_effect_metadata_required")
    require(metadata["adapter"] == "SourceSoftwareVerificationAdapter@1"
        and metadata["source_binding_schema"] == origin.SCHEMA
        and metadata["input_type_basis"] == "explicit_int_annotations"
        and metadata["language"] == "python" and metadata["path"] == "source.py",
        "unsupported_source_metadata_profile")
    require(all(metadata[key] is False for key in AUTHORITY), "source_metadata_authority_must_remain_false")
    require(_wire(metadata["assumptions"]) == _wire(origin._ASSUMPTIONS), "source_metadata_assumptions_changed")
    require(metadata["source_binding_effects_schema"] == effects.EFFECTS_SCHEMA
        and metadata["effect_summary_contract"] == effects.EFFECT_SUMMARY_CONTRACT
        and metadata["effect_summary_assumption"] == effects.EFFECT_SUMMARY_ASSUMPTION,
        "source_effect_profile_or_assumption_changed")
    require(type(metadata["source_sha256"]) is str
        and re.fullmatch(r"[0-9a-f]{64}", metadata["source_sha256"]) is not None,
        "source_metadata_hash_required")
    require(len(_wire(metadata)) <= 16384, "bounded_source_effect_metadata_required")
    require(len(payload["sources"]) == 1, "one_source_reference_required")
    source = payload["sources"][0]
    require(source["content_sha256"] == metadata["source_sha256"], "source_reference_metadata_hash_mismatch")
    require(source["ref_id"] == "source:source.py" and source["source_id"] == "source.py"
        and source["source_uri"] == "file:///source.py" and source["source_revision"] == "workspace:local"
        and source["review_status"] == "unreviewed"
        and all(source[key] == "" for key in ("container_sha256", "container_uri", "content_cid", "license_expression")),
        "unsupported_source_reference_profile")
    _closed(source["metadata"], {"language", "path", "byte_length"}, "closed_source_reference_metadata_required")
    require(source["metadata"]["language"] == "python" and source["metadata"]["path"] == "source.py"
        and type(source["metadata"]["byte_length"]) is int
        and 0 < source["metadata"]["byte_length"] <= origin.MAX_SOURCE_BYTES,
        "source_reference_provenance_changed")
    require(payload["spans"] and all(span["source_ref_id"] == source["ref_id"]
        and 0 <= span["start_byte"] <= span["end_byte"] <= source["metadata"]["byte_length"]
        for span in payload["spans"]), "source_reference_span_bounds_changed")
    for collection in ("symbols", "expressions", "commands", "functions"):
        require(all(row["source_ref_ids"] == [source["ref_id"]] and row["span_ids"] for row in payload[collection]),
            "source_bound_native_records_required")
    return metadata, effects


def _audit(payload, metadata, effects, program):
    audit = metadata["effect_summary_audit"]
    _closed(audit, {"schema", "base_program_id", "base_program_sha256", "commands", "functions"},
        "closed_source_effect_audit_required")
    require(audit["schema"] == effects.EFFECT_AUDIT_SCHEMA, "source_effect_audit_schema_changed")
    require(type(audit["base_program_id"]) is str and type(audit["base_program_sha256"]) is str
        and re.fullmatch(r"[0-9a-f]{64}", audit["base_program_sha256"]) is not None,
        "source_effect_audit_base_identity_required")
    symbols = set(program.symbols)
    restored = deepcopy(payload)
    for collection, id_key in (("commands", "command_id"), ("functions", "function_id")):
        records = audit[collection]
        originals = {row[id_key]: row for row in payload[collection]}
        require(type(records) is list and len(records) == len(originals), "complete_effect_audit_records_required")
        ids = []
        for record in records:
            fields = {id_key, "before", "after", "retained_effects"} | ({"purity"} if collection == "functions" else set())
            _closed(record, fields, "closed_effect_audit_record_required")
            identity = record[id_key]
            require(type(identity) is str and identity in originals, "effect_audit_unknown_native_record")
            ids.append(identity)
            row = originals[identity]
            for phase in ("before", "after"):
                _closed(record[phase], {"reads", "writes"}, "closed_effect_audit_read_write_required")
                for direction in ("reads", "writes"):
                    _ids(record[phase][direction], symbols)
            _closed(record["retained_effects"], effects.EFFECT_OTHER_FIELDS, "closed_retained_effect_audit_required")
            require(_wire(record["retained_effects"]) == _wire({key: row["effects"][key]
                for key in effects.EFFECT_OTHER_FIELDS}), "non_read_write_effects_changed")
            if collection == "functions":
                require(record["purity"] == row["purity"], "native_purity_changed")
                actual = {"reads": sorted(program.actual_reads), "writes": sorted(program.actual_writes)}
            else:
                actual = {"reads": sorted(set().union(*(program.reads[key] for key in row["expression_ids"]))),
                    "writes": sorted(row["target_symbol_ids"])}
            require(_wire(record["after"]) == _wire(actual), "complete_exact_operational_effect_audit_required")
            for direction in ("reads", "writes"):
                require(record["after"][direction] == row["effects"][direction], "native_effect_summary_audit_mismatch")
                require(set(record["before"][direction]) <= set(record["after"][direction]),
                    "effect_refinement_must_not_erase_declared_bounds")
            restored_row = next(item for item in restored[collection] if item[id_key] == identity)
            restored_row["effects"].update(deepcopy(record["before"]))
        require(ids == sorted(originals), "canonical_complete_effect_audit_identity_order_required")
    for key in effects.METADATA_EXTENSION_KEYS:
        del restored["metadata"][key]
    restored.pop("program_id")
    original = ProgramIR.from_dict(restored).to_dict()
    require(original["program_id"] == audit["base_program_id"] and _digest(original) == audit["base_program_sha256"],
        "effect_audit_original_program_identity_mismatch")
    return audit


def _evidence(payload, metadata, audit, view):
    # Full JSON is emitted as explicit evidence data. The operational definitions
    # below derive semantics solely from the validated native typed program.
    entries = {
        "sourceEvidenceOriginalProgramSHA256": _digest(payload),
        "sourceEvidenceOperationalViewSHA256": _digest(view),
        "sourceEvidenceSourceSHA256": metadata["source_sha256"],
        "sourceEvidenceMetadataJSON": _wire(metadata).decode(),
        "sourceEvidenceSourceReferencesJSON": _wire(payload["sources"]).decode(),
        "sourceEvidenceEffectAuditJSON": _wire(audit).decode(),
    }
    lines = ["def " + name + " : String := " + string(value) for name, value in entries.items()]
    assumptions = [*metadata["assumptions"], metadata["effect_summary_assumption"]]
    lines.append("def sourceEvidenceAssumptions : List String := [" + ", ".join(map(string, assumptions)) + "]")
    for name in AUTHORITY:
        lines.append("def sourceEvidence_" + name + " : Bool := false")
    for collection, id_key in (("commands", "command_id"), ("functions", "function_id")):
        for direction in ("reads", "writes"):
            values = ["(" + string(row[id_key]) + ", [" + ", ".join(map(string, row["after"][direction])) + "])"
                for row in audit[collection]]
            lines.append("def sourceEvidence_" + collection + "_" + direction
                + " : List (String × List String) := [" + ", ".join(values) + "]")
    return "\n\n".join(lines)


def emit_program(payload):
    """Emit a source-binding v2 program with checked metadata and effect evidence."""
    native = ProgramIR.from_dict(payload)
    require(_wire(native.to_dict()) == _wire(payload), "native_program_exact_roundtrip_required")
    metadata, effects = _metadata(payload)
    view = deepcopy(payload)
    view["metadata"] = {}
    view.pop("program_id")
    view = ProgramIR.from_dict(view).to_dict()
    program = previous._Program(view)
    audit = _audit(payload, metadata, effects, program)
    source = _evidence(payload, metadata, audit, view) + "\n\n" + program.source()
    details = program.details()
    details.update(profile=PROFILE,
        validator="exact_source_bound_ProgramIR_closed_metadata_effect_lineage_and_operational_audit",
        program_sha256=_digest(payload), original_program_id=payload["program_id"],
        original_metadata_sha256=_digest(metadata), effect_audit_sha256=_digest(audit),
        original_source_references=deepcopy(payload["sources"]), effect_audit=deepcopy(audit),
        operational_view_program_id=view["program_id"], operational_view_sha256=_digest(view),
        operational_view_transformation="closed_validated_metadata_extracted_to_explicit_Lean_evidence_declarations",
        original_program_modified=False, source_bytes_replayed=False,
        source_hash_consistency_checked=True, complete_read_write_summaries_checked=True,
        metadata_emitted_as_explicit_evidence=True, **AUTHORITY)
    details["assumptions"].extend([*metadata["assumptions"], metadata["effect_summary_assumption"],
        "The caller must independently replay qualification against exact source bytes and the original candidate.",
        "Lean evidence declarations record provenance and assumptions; they are not proofs of source fidelity."])
    return source, details


def emit_projection(row, *, report=None):
    """Own only the explicit source-binding metadata-bearing ProgramIR profile."""
    payload = row.get("payload")
    if row.get("logic_family") != "program" or type(payload) is not dict or payload.get("schema_version") != "program-ir/v1":
        raise NotImplementedError
    return emit_program(payload)


__all__ = ["PROFILE", "emit_program", "emit_projection"]
