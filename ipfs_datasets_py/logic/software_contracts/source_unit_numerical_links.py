"""Exact function-unit links to whole-file numerical structural artifacts.

This is a deterministic provenance bridge, not a decoder or proof checker.
Both upstream reports are replayed from original bytes before their identities
can be joined. Whole-module imports are retained through the numerical report;
normalised isolated function text is never used to reconstruct those imports.
Artifact references do not establish runtime library identity or correctness.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..formalization.autoencoder import source_function_units as units
from ..formalization.autoencoder.security import source_program_binding_384 as scalar
from ..software_verification import numerical_logic, numerical_source

SCHEMA = "source-unit-numerical-links@1"
MAX_REPORT_BYTES = 8 * 1024 * 1024
_FALSE = dict(proof_authority=False, source_semantics_verified=False,
    whole_program_semantics_verified=False, execution_authority=False,
    completion_authority=False, source_executed=False,
    model_inference_executed=False, scalar_candidate_checked=False,
    autoencoder_coverage_changed=False)


class SourceUnitNumericalLinkError(ValueError):
    """A source, unit inventory, numerical artifact or link failed exact replay."""


def _wire(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise SourceUnitNumericalLinkError("inert bounded link JSON required") from exc
    if len(raw) > MAX_REPORT_BYTES:
        raise SourceUnitNumericalLinkError("link input or report exceeds byte bound")
    return raw


def _sha(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _pins(*, guarded=False):
    modules = (units, scalar, numerical_source, numerical_logic)
    if guarded:
        from ..software_verification import numerical_source_v2, numerical_logic_v2
        modules += (numerical_source_v2, numerical_logic_v2)
    return {Path(module.__file__).name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in modules} | {
                Path(__file__).name: hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def _scalar_shape(unit):
    # The existing guard assesses source shape only. No checkpoint is loaded,
    # candidate is supplied, or learned decoder coverage inferred from it.
    if unit["status"] != "eligible":
        return "not_checked", "unit_normalization_unsupported"
    try:
        scalar._guard(unit["normalized_source_text"])
    except scalar._Rejected as exc:
        return "unsupported", exc.code
    return "eligible_source_shape", None


def _artifacts(report):
    catalog, obligation_refs, whole_refs = [], {}, []

    def add(family, encoding, payload, pointer, obligation_id=None):
        digest = _sha(payload)
        artifact_id = family + ":" + digest
        row = dict(artifact_id=artifact_id, artifact_sha256=digest,
                   family=family, encoding=encoding, report_pointer=pointer)
        if obligation_id is not None:
            row["obligation_id"] = obligation_id
            obligation_refs.setdefault(obligation_id, []).append(artifact_id)
        else:
            whole_refs.append(artifact_id)
        if encoding == "Lean4":
            row["source_sha256"] = payload["source_sha256"]
            row["lake_executed"] = False
        catalog.append(row)

    projections = report["projections"]
    if projections["program"] is not None:
        add("program", "ProgramIR", projections["program"], "/projections/program")
    for key, family, encoding in (("first_order", "first_order", "TypedExpression"),
                                  ("smt", "first_order", "SMT-LIB")):
        for index, row in enumerate(projections[key]):
            add(family, encoding, row, f"/projections/{key}/{index}", row["obligation_id"])
    if projections["lean"] is not None:
        add("higher_order", "Lean4", projections["lean"], "/projections/lean")
        lean_id = whole_refs.pop()
        for binding in projections["lean"]["bindings"]:
            obligation_refs.setdefault(binding["obligation_id"], []).append(lean_id)
    return catalog, obligation_refs, whole_refs


def bind_function_unit_logic(*, source_bytes, unit_inventory, numerical_report):
    """Join replayed units to functions by full-file identity and exact byte span.

    ``unit_inventory`` must be the unmodified ``extract_function_units`` result,
    not an augmented inference preparation. Every unit and unmatched native
    function is accounted for; no containment or name-only fallback is used.
    Scalar shape information describes the existing source guard, not a learned
    candidate, checkpoint result, or proof. All artifact bodies stay upstream.
    """
    if type(source_bytes) is not bytes or not 0 < len(source_bytes) <= numerical_source.MAX_SOURCE_BYTES:
        raise SourceUnitNumericalLinkError("bounded exact original source bytes required")
    if type(unit_inventory) is not dict or type(numerical_report) is not dict:
        raise SourceUnitNumericalLinkError("native unit inventory and numerical report required")
    _wire(unit_inventory)
    _wire(numerical_report)
    try:
        inventory = units.validate_function_units(unit_inventory, source_bytes=source_bytes)
        path = inventory["source_path"]
        owner = numerical_logic
        guarded = (numerical_report.get("profile") == "python-numerical-guarded-structure@2"
                   and numerical_report.get("schema") == "numerical-source-logic/v2")
        if guarded:
            from ..software_verification import numerical_logic_v2
            owner = numerical_logic_v2
        native = owner.validate_numerical_logic_report(
            numerical_report, source_bytes.decode("utf-8"), path=path)
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise SourceUnitNumericalLinkError("source inventory or numerical report failed exact replay") from exc
    digest = hashlib.sha256(source_bytes).hexdigest()
    if native["source_sha256"] != digest or inventory["source_sha256"] != digest or native["path"] != path:
        raise SourceUnitNumericalLinkError("whole-file identity differs")
    structural = native["structural"]
    program = structural["program"] or dict(functions=[], spans=[], sources=[])
    sources = {r["ref_id"]: r for r in program["sources"]}
    spans = {r["span_id"]: r for r in program["spans"]}
    coverage = {r["function_id"]: r for r in structural["function_coverage"]}
    functions_by_range = {}
    for function in program["functions"]:
        # The frontend currently gives each top-level function one AST span.
        # Multiple or foreign spans must not become an approximate join.
        if len(function["span_ids"]) != 1:
            raise SourceUnitNumericalLinkError("one exact native function span required")
        span = spans[function["span_ids"][0]]
        source = sources[span["source_ref_id"]]
        if (source["content_sha256"] != digest or source["metadata"]["path"] != path
                or span["source_ref_id"] not in function["source_ref_ids"]):
            raise SourceUnitNumericalLinkError("native function source identity differs")
        key = (span["start_byte"], span["end_byte"])
        if key in functions_by_range:
            raise SourceUnitNumericalLinkError("ambiguous native function range")
        functions_by_range[key] = function
    catalog, obligation_refs, whole_refs = _artifacts(native)
    links, matched = [], set()
    for unit in inventory["units"]:
        shape, reason = _scalar_shape(unit)
        function = functions_by_range.get((unit["start_byte"], unit["end_byte"]))
        # Unsupported normalization cannot silently acquire a numerical link.
        if unit["status"] != "eligible":
            function = None
        fid = function["function_id"] if function else None
        status = coverage[fid] if fid is not None else None
        obligations = [r for r in native["pending_obligations"] if fid in r["function_ids"]] if fid else []
        contracts = [r["contract_id"] for r in native["compound_contracts"] if r["function_id"] == fid]
        assertions = [r["requirement_id"] for r in native["assertion_requirements"] if r["function_id"] == fid]
        refs = list(whole_refs) if function else []
        for obligation in obligations:
            refs.extend(obligation_refs.get(obligation["obligation_id"], []))
        if function:
            matched.add(fid)
        links.append(dict(unit_id=unit["unit_id"], normalized_body_sha256=unit["normalized_body_sha256"],
            start_byte=unit["start_byte"], end_byte=unit["end_byte"],
            raw_span_sha256=hashlib.sha256(source_bytes[unit["start_byte"]:unit["end_byte"]]).hexdigest(),
            status="matched" if function else "unmatched", function_id=fid,
            unmatched_reason=None if function else ("unit_normalization_unsupported"
                if unit["status"] != "eligible" else "no_exact_native_function_span"),
            source_ref_ids=list(function["source_ref_ids"]) if function else [],
            span_ids=list(function["span_ids"]) if function else [],
            structural_status=("structurally_complete" if status["structurally_complete"] else "partial") if status else None,
            unsupported_constructs=list(status["unsupported_constructs"]) if status else [],
            scalar_guard_status=shape, scalar_guard_reason=reason,
            pending_obligation_ids=[r["obligation_id"] for r in obligations],
            pending_obligation_count=len(obligations), compound_contract_ids=contracts,
            compound_contract_count=len(contracts), assertion_requirement_ids=assertions,
            assertion_requirement_count=len(assertions), family_artifact_ids=sorted(set(refs)),
            source_obligations_discharged=0, **_FALSE))
    unmatched = sorted(f["function_id"] for f in program["functions"] if f["function_id"] not in matched)
    linked_obligations = {oid for row in links for oid in row["pending_obligation_ids"]}
    report = dict(schema=SCHEMA, origin="deterministic_source_projection", path=path,
        source_sha256=digest, source_bytes=len(source_bytes),
        inventory_sha256=_sha(inventory), numerical_report_sha256=_sha(native),
        numerical_report_id=native["report_sha256"], producer=_pins(guarded=guarded),
        inventory_status=inventory["status"], inventory_frontier=inventory["frontier"],
        numerical_structural_status=structural["status"],
        import_context=dict(scope="whole_module_syntactic_bindings",
            bindings_sha256=_sha(structural["import_bindings"]),
            binding_count=len(structural["import_bindings"]), runtime_identity_verified=False),
        links=links, artifacts=catalog, unit_count=len(links), matched_unit_count=len(matched),
        unmatched_unit_count=sum(r["status"] == "unmatched" for r in links),
        native_function_count=len(program["functions"]), unmatched_native_function_ids=unmatched,
        unmatched_native_function_count=len(unmatched),
        pending_obligation_count=len(native["pending_obligations"]),
        linked_pending_obligation_count=len(linked_obligations),
        unlinked_pending_obligation_ids=sorted(r["obligation_id"] for r in native["pending_obligations"]
                                              if r["obligation_id"] not in linked_obligations),
        compound_contract_count=len(native["compound_contracts"]),
        assertion_requirement_count=len(native["assertion_requirements"]),
        source_obligations_discharged=0, provider_calls=0, solver_calls=0,
        training_performed=False, **_FALSE)
    report["report_sha256"] = _sha(report)
    return report


def validate_function_unit_logic_links(report, *, source_bytes, unit_inventory, numerical_report):
    """Rebuild links; metadata hashes, coverage and authority flags are untrusted."""
    if type(report) is not dict:
        raise SourceUnitNumericalLinkError("native function-unit links report required")
    _wire(report)
    expected = bind_function_unit_logic(source_bytes=source_bytes,
        unit_inventory=unit_inventory, numerical_report=numerical_report)
    if _wire(expected) != _wire(report):
        raise SourceUnitNumericalLinkError("function-unit numerical links differ from exact replay")
    return expected


__all__ = ["SCHEMA", "SourceUnitNumericalLinkError", "bind_function_unit_logic",
           "validate_function_unit_logic_links"]
