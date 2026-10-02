"""Complete CodebaseIR envelope over existing typed, source-bound artifacts.

The selected semantic lane is the existing closed integer-offset profile. This
module supplies inventory joins and identities; it does not invent a program
logic, execute a target/checker, train a decoder or authorize a proof-cache hit.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys

from . import codebase_integer_profile as integer
from .codebase_scan_policy import load_policy_receipt
from .content import canonical_dag_json_bytes, cid_for_bytes, cid_for_structured, validate_cid

SCHEMA = "codebase-ir-manifest@1"
PROFILE = "codebase-ir/python-integer-offset-artifacts@1"
MAX_CONTRACTS = 32
MAX_EVIDENCE = 64
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_AUTHORITY = dict(semantic_model_only=True, source_observed_live=False,
                 source_runtime_semantics_verified=False, proof_authority=False,
                 execution_authority=False, training_executed=False,
                 solver_executed=False, learned_latents_as_predicates=False)
_RESULT_FIELDS = {"schema", "profile", "status", "compiled_cid", "contract_cid", "source_cid",
    "revision", "assumptions", "solvers", "query_cid", "evidence_kind", "checker_identity",
    "kernel_checked", "behavior_authority", "model_checked_against_runtime", "bounds"}


class CodebaseSemanticManifestError(ValueError):
    """Native typed source records or complete inventory bindings differ."""


def _require(condition, message):
    if not condition:
        raise CodebaseSemanticManifestError(message)


def _wire(value, maximum=MAX_ARTIFACT_BYTES):
    raw = canonical_dag_json_bytes(value)
    _require(len(raw) <= maximum, "semantic artifact exceeds the bounded profile")
    return raw


def _implementation():
    from . import codebase_scan_policy, content
    from .semantic_index import identity, models
    from ..software_verification import codebase_pipeline, codebase_source_adapters, program, contracts, vc, ir, properties, translations
    from ..backends.smt import compiler, differential
    from ..ir_core import canonical, claims, identity as ir_identity, provenance
    modules = (sys.modules[__name__], codebase_scan_policy, content, integer, identity, models,
        codebase_pipeline, codebase_source_adapters, program, contracts, vc, ir, properties,
        translations, compiler, differential, canonical, claims, ir_identity, provenance)
    return {"files": {m.__name__: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest() for m in modules},
            "parser": sys.implementation.cache_tag, "python": sys.version}


def _contracts(values):
    _require(type(values) in (tuple, list) and len(values) <= MAX_CONTRACTS,
             "bounded explicit native integer contracts required")
    _require(all(type(value) is integer.IntegerOffsetContract for value in values),
             "only exact native IntegerOffsetContract declarations are accepted")
    result = tuple(sorted((integer.IntegerOffsetContract.from_dict(v.to_dict()) for v in values), key=lambda v: v.path))
    _require(len({v.path for v in result}) == len(result), "one explicit contract per selected source unit required")
    return result


def _references(values):
    _require(type(values) in (tuple, list) and len(values) <= MAX_EVIDENCE,
             "bounded explicit evidence references required")
    result = []
    for value in values:
        _require(type(value) is dict and set(value) == {"kind", "path", "artifact_cid"}
                 and value["kind"] == "conditional_smt_record" and type(value["path"]) is str,
                 "closed typed conditional SMT reference required")
        validate_cid(value["artifact_cid"], codecs={"dag-json"})
        result.append(dict(value))
    result.sort(key=lambda value: (value["path"], value["artifact_cid"]))
    _require(len({(v["path"], v["artifact_cid"]) for v in result}) == len(result),
             "duplicate evidence reference")
    return result


def _artifact(index, value, *, publish):
    _wire(value)
    cid = cid_for_structured(value)
    if publish:
        _require(index.artifacts.put(value) == cid, "native artifact publication differs")
    else:
        _require(_wire(index.artifacts.get(cid)) == _wire(value),
                 "native typed artifact does not reconstruct")
    return cid


def _evidence(index, refs, compiled):
    from ..backends.smt.differential import normalize_smtlib_for_solver
    script = "\n".join(line for line in normalize_smtlib_for_solver(compiled.compilation.smtlib).splitlines()
                       if line.strip() not in {"(get-model)", "(get-unsat-core)"}) + "\n"
    rows = []
    for reference in refs:
        value = index.artifacts.get(reference["artifact_cid"], expected_schema=integer.RESULT_SCHEMA)
        _wire(value)
        _require(type(value) is dict and set(value) == _RESULT_FIELDS
                 and value["profile"] == integer.PROFILE and value["evidence_kind"] == "conditional_smt"
                 and value["compiled_cid"] == compiled.cid and value["contract_cid"] == compiled.contract.cid
                 and value["source_cid"] == compiled.source_cid and value["revision"] == compiled.revision
                 and canonical_dag_json_bytes(value["assumptions"]) == canonical_dag_json_bytes(list(integer.ASSUMPTIONS))
                 and value["query_cid"] == cid_for_bytes(script.encode())
                 and all(value[field] is False for field in ("kernel_checked", "behavior_authority", "model_checked_against_runtime"))
                 and value["status"] in {"proved", "refuted", "unknown", "unavailable", "timeout", "error", "disagreement"}
                 and type(value["solvers"]) is list and len(value["solvers"]) == 2
                 and [v.get("solver") if type(v) is dict else None for v in value["solvers"]] == ["z3", "cvc5"]
                 and type(value["checker_identity"]) is dict and type(value["bounds"]) is dict,
                 "execution record type/source/contract/compilation/query or authority binding differs")
        rows.append({**reference, "source_cid": compiled.source_cid,
            "contract_cid": compiled.contract.cid, "compiled_cid": compiled.cid,
            "recorded_status": value["status"], "validation": "record_type_and_source_binding_only",
            "trusted_execution": False, "proof_authority": False})
    return rows


def _derive(index, *, policy_receipt_cid, contracts, evidence_refs, publish):
    policy = load_policy_receipt(index, policy_receipt_cid)
    structural = index.load(policy["head"]["manifest_cid"])
    declarations = _contracts(contracts)
    references = _references(evidence_refs)
    by_path = {value.path: value for value in declarations}
    entries = {entry.path: entry for entry in structural.snapshot.entries}
    _require(set(by_path) <= set(entries), "declared contract path is outside the complete admitted inventory")
    _require({value["path"] for value in references} <= set(by_path),
             "evidence reference requires a declared contract in the admitted inventory")
    native_units = {unit.source_key: unit for unit in structural.units}
    symbols = structural.semantic_state.symbols
    rows = []
    for entry in structural.snapshot.entries:
        unit = native_units[entry.source_key]
        contract = by_path.get(entry.path)
        stable = cid_for_structured({"schema": "codebase-logical-unit@1",
            "repository_id": structural.snapshot.repository_id, "raw_path_hex": entry.raw_path_hex})
        unit_symbols = [symbol.to_dict() for symbol in symbols if symbol.module_path == entry.path]
        symbol_ids = {value["stable_id"] for value in unit_symbols}
        edges = [edge.to_dict() for edge in structural.semantic_state.edges
                 if edge.source_id in symbol_ids or edge.target_id in symbol_ids]
        artifacts, compiled = {}, None
        if entry.is_opaque:
            status, reason = "opaque", entry.opaque_reason
        elif not entry.path.endswith(".py"):
            status, reason = "unsupported_language", "captured bytes have no admitted Python semantic profile"
        elif unit.parse_status != "ok":
            status, reason = "unsupported_parse", "native structural parse is " + unit.parse_status
        elif contract is None:
            status, reason = "missing_contract", "no owner-supplied declarative contract selected"
        else:
            source = index.artifacts.get_bytes(entry.source_cid)
            try:
                compiled = integer.compile_integer_offset(source, contract,
                    revision="snapshot:" + structural.snapshot.snapshot_cid)
            except integer.UnsupportedIntegerProfile as error:
                status, reason = "unsupported_source", str(error)[:1024]
            else:
                status, reason = "source_bound_model", None
                pipeline = compiled.pipeline
                values = {
                    "program": pipeline.program.to_dict(),
                    "contracts": [c.to_dict() for c in pipeline.contracts],
                    "source_correspondence": pipeline.bindings.to_dict(),
                    "effects": {"schema": "codebase-native-effects@1",
                        "functions": [{"function_id": f.function_id, "purity": f.purity.value,
                            "effects": f.effects.to_dict(), "cfg": f.cfg.to_dict()} for f in pipeline.program.functions],
                        "commands": [{"command_id": c.command_id, "effects": c.effects.to_dict()} for c in pipeline.program.commands]},
                    "vc_sets": [v.to_dict() for v in pipeline.vc_sets],
                    "compilation": compiled.to_dict(),
                }
                artifacts = {name: _artifact(index, value, publish=publish) for name, value in values.items()}
        bound_refs = [value for value in references if value["path"] == entry.path]
        _require(not bound_refs or compiled is not None,
                 "execution references cannot attach to an unsupported or missing source model")
        evidence = _evidence(index, bound_refs, compiled) if bound_refs else []
        row = dict(path=entry.path, source_key=entry.source_key, logical_unit_id=stable,
            entry_cid=entry.entry_cid, source_cid=entry.source_cid, ast_cid=unit.ast_cid,
            symbols=[{k: value[k] for k in ("stable_id", "version_cid", "qualified_name", "source_cid", "span")}
                     for value in unit_symbols],
            model_status=status, unsupported_reason=reason,
            declared_contract=None if contract is None else contract.to_dict(),
            declared_contract_cid=None if contract is None else contract.cid,
            declaration_status="owner_supplied_specification_not_established_truth" if contract else "absent",
            native_artifacts=artifacts,
            assumptions=list(integer.ASSUMPTIONS) if compiled else [],
            dependency_frontier={
                "status": "closed_local_expression_under_declared_runtime_assumptions" if compiled else "unresolved",
                "whole_program_closed": False,
                "structural_edge_references": [edge["edge_id"] for edge in edges],
                "unsupported_region": None if compiled else entry.entry_cid,
            },
            declared_execution_records=evidence, checked_evidence_references=[],
            proof_authority=False)
        row["version_cid"] = cid_for_structured({"schema": "codebase-exact-unit-version@1", "unit": row})
        rows.append(row)
    modeled = sum(row["model_status"] == "source_bound_model" for row in rows)
    coverage = {**structural.coverage, "source_bound_models": modeled,
        "unmodeled_inventory_units": len(rows) - modeled, "declared_contracts": len(declarations),
        "modeled_contracts": modeled, "unmodeled_contracts": len(declarations) - modeled,
        "formalized_properties": modeled, "checked_properties": 0,
        "declared_execution_records": len(references), "checked_evidence_records": 0}
    manifest = dict(schema=SCHEMA, profile=PROFILE, producer=_implementation(),
        policy_receipt_cid=policy_receipt_cid, structural_manifest_cid=structural.cid,
        source_head=policy["head"], semantic_state_cid=structural.semantic_state.state_cid,
        declarations=[value.to_dict() for value in declarations], evidence_requests=references,
        identity_policy={"logical_unit": "repository_view_and_raw_path",
            "logical_symbol": "native_repository_language_path_qualified_name_kind_namespace",
            "exact_version": "source_entry_and_full_native_artifact_reference_payload",
            "rename": "path_or_qualified_name_change_creates_new_logical_identity_no_equivalence_inference"},
        units=rows, coverage=coverage, authority=dict(_AUTHORITY),
        semantic_definitions="existing_native_ProgramIR_ProgramContract_and_closed_integer_offset_profile",
        global_dependency_graph_closed=False)
    _wire(manifest, MAX_MANIFEST_BYTES)
    return manifest


def build_codebase_semantic_manifest(index, *, policy_receipt_cid, contracts=(), evidence_refs=()):
    """Publish immutable deterministic model artifacts; never run a checker."""
    value = _derive(index, policy_receipt_cid=policy_receipt_cid,
                    contracts=contracts, evidence_refs=evidence_refs, publish=True)
    return {"manifest_cid": index.artifacts.put(value), "source_head": value["source_head"],
            "coverage": value["coverage"], "authority": dict(_AUTHORITY)}


def load_codebase_semantic_manifest(index, manifest_cid):
    """Reconstruct full inventory and native artifacts without live/model work."""
    value = index.artifacts.get(manifest_cid, expected_schema=SCHEMA)
    _wire(value, MAX_MANIFEST_BYTES)
    try:
        contracts = [integer.IntegerOffsetContract.from_dict(v) for v in value["declarations"]]
        expected = _derive(index, policy_receipt_cid=value["policy_receipt_cid"],
            contracts=contracts, evidence_refs=value["evidence_requests"], publish=False)
    except (KeyError, TypeError) as error:
        raise CodebaseSemanticManifestError("semantic manifest fields are incomplete") from error
    _require(_wire(value, MAX_MANIFEST_BYTES) == _wire(expected, MAX_MANIFEST_BYTES),
             "complete semantic manifest does not reconstruct from native typed source owners")
    return expected


__all__ = ["build_codebase_semantic_manifest", "load_codebase_semantic_manifest",
           "CodebaseSemanticManifestError", "SCHEMA", "PROFILE"]
