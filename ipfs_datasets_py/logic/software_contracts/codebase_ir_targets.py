"""Captured-source CodebaseIR targets for structural feature reconstruction.

The existing source adapter and syntax bridge remain the representation
owners.  This adapter retains their complete records and a deterministic
feature view without source or checkpoint identifiers.  An exact byte join or
feature reconstruction does not establish source semantics, a proof, or tool
authority.  Preparation reads immutable history; the caller owns live fences.
"""
from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
from typing import Any

from .ast_ir import ASTRecord
from .cache import ImmutableCAS
from .codebase_ir import CodebaseIRError, CodebaseIRManifest, CodebaseUnit, RepositoryCodebaseIndex
from .content import cid_for_bytes, cid_for_structured
from .semantic_index.snapshot import SnapshotEntry
from ..formalization.autoencoder.domain_targets import DomainTargetEnvelope, build_target_envelope
from ..security_ir.code_logic_projection import describe_code_logic_projection_profile
from ..software_verification.contracts import ProgramContract
from ..software_verification.pipeline import ContractSpec, PipelineError, attach_contract_specs
from ..software_verification.program import ProgramIR
from ..software_verification.source_adapters import SourceAdapterStatus, adapt_source_to_software_verification
from ..software_verification.syntax_bridge import SoftwareVerificationSyntaxBridge, SoftwareVerificationBridgeError

CODEBASE_TARGET_SCHEMA = "codebase-ir-source-bound-feature-targets@1"
CODEBASE_FEATURE_VIEW_SCHEMA = "codebase-ir-native-structural-feature-view@1"
CODEBASE_PROGRAM_PROJECTION = "codebase_ir.program@1"
CODEBASE_CONTRACTS_PROJECTION = "codebase_ir.contracts@1"
_VALIDATOR = "codebase_ir.exact_native_target_replay@1"
_BINDING_SCHEMA = "codebase-ir-feature-source-binding@1"
_AUTHORITY = {
    "feature_only": True, "source_semantics_verified": False,
    "proof_authority": False, "execution_authority": False,
    "completion_authority": False, "semantic_formula_decoder": False,
}
_GAPS = ("source_runtime_semantics_not_verified", "backend_proofs_not_run",
         "kernel_proofs_not_run", "feature_reconstruction_is_not_formalization")


class CodebaseTargetError(CodebaseIRError):
    """A captured binding, native target, or bounded profile is invalid."""


@dataclass(frozen=True, slots=True)
class CodebaseTargetLimits:
    max_source_bytes: int = 64 * 1024
    max_ast_nodes: int = 2048
    max_ast_depth: int = 48
    max_functions: int = 16
    max_contracts: int = 8
    max_condition_bytes: int = 16 * 1024
    max_target_bytes: int = 4 * 1024 * 1024

    def __post_init__(self) -> None:
        ceilings = (64 * 1024, 2048, 48, 16, 8, 16 * 1024, 4 * 1024 * 1024)
        for name, ceiling in zip(self.__dataclass_fields__, ceilings):
            value = getattr(self, name)
            if type(value) is not int or not 0 < value <= ceiling:
                raise CodebaseTargetError(f"{name} must be an exact integer within the native profile")

    def to_dict(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def _wire(value: Any, maximum: int = 4 * 1024 * 1024) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise CodebaseTargetError("bounded finite native JSON required") from exc
    if len(raw) > maximum:
        raise CodebaseTargetError("CodebaseIR target exceeds its byte bound")
    return raw


def describe_codebase_target_profile() -> dict[str, Any]:
    routes = {row["kind"]: row for row in describe_code_logic_projection_profile()["projections"]
              if row["kind"] in {"program", "contract"}}
    return {
        "schema": CODEBASE_TARGET_SCHEMA, "feature_view_schema": CODEBASE_FEATURE_VIEW_SCHEMA,
        "domain_id": "codebase_ir", "projection_ids": [CODEBASE_PROGRAM_PROJECTION, CODEBASE_CONTRACTS_PROJECTION],
        "native_routes": routes, "limits": CodebaseTargetLimits().to_dict(),
        "feature_view": "native documents with stable positional references; provenance retained outside learned expressions",
        "readiness": "complete supported source adapter, exact native bridge, no unsupported inventory",
        "unsupported_policy": "retain source-bound frontiers and deny training readiness",
        "solver_calls": 0, "provider_calls": 0, "executes_source": False, **_AUTHORITY,
    }


def _specs(values: Sequence[ContractSpec], limits: CodebaseTargetLimits) -> tuple[ContractSpec, ...]:
    if type(values) not in {tuple, list} or len(values) > limits.max_contracts:
        raise CodebaseTargetError("bounded list/tuple of native ContractSpec values required")
    result = []
    for item in values:
        if type(item) is not ContractSpec:
            raise CodebaseTargetError("native ContractSpec required")
        data = item.to_dict()
        if (len(data["preconditions"]) + len(data["postconditions"]) > 32
                or any(type(value) is not str or len(value.encode("utf-8")) > 512
                       for value in (data["function_name"], data["contract_id"]))):
            raise CodebaseTargetError("contract identity or condition inventory exceeds the profile")
        copied = ContractSpec(item.function_name, tuple(item.preconditions), tuple(item.postconditions), item.contract_id)
        if copied.to_dict() != data:
            raise CodebaseTargetError("contract normalization changed supplied values")
        result.append(copied)
    if len({item.contract_id for item in result}) != len(result):
        raise CodebaseTargetError("duplicate contract identities")
    _wire([item.to_dict() for item in result], limits.max_condition_bytes)
    # Native injection parses expression syntax. Bound that work first.
    for item in result:
        for condition in (*item.preconditions, *item.postconditions):
            try:
                tree = ast.parse(condition, mode="eval")
            except (SyntaxError, ValueError, RecursionError) as exc:
                raise CodebaseTargetError("invalid contract expression syntax") from exc
            _ast_bound(tree, limits)
    return tuple(result)


def _ast_bound(tree: ast.AST, limits: CodebaseTargetLimits) -> int:
    pending, count = [(tree, 0)], 0
    while pending:
        node, depth = pending.pop()
        count += 1
        if count > limits.max_ast_nodes or depth > limits.max_ast_depth:
            raise CodebaseTargetError("source or contract AST exceeds the bounded target profile")
        pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    return count


def _source_frontiers(tree: ast.Module, limits: CodebaseTargetLimits) -> list[dict[str, Any]]:
    """Close omissions in the general adapter without changing its semantics."""
    rows = []

    def reject(reason: str, node: ast.AST) -> None:
        row = {"kind": "program", "reason": reason, "node_kind": type(node).__name__,
               "line": getattr(node, "lineno", 0), "column_byte": getattr(node, "col_offset", 0)}
        if row not in rows:
            rows.append(row)

    functions = [node for node in tree.body if type(node) is ast.FunctionDef]
    if len(functions) > limits.max_functions:
        raise CodebaseTargetError("function inventory exceeds the target profile")
    for node in tree.body:
        if type(node) is not ast.FunctionDef:
            reject("plain_function_module_required", node)
    for function in functions:
        args = function.args
        if (function.decorator_list or function.type_comment or getattr(function, "type_params", ())
                or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg
                or args.defaults or args.kw_defaults):
            reject("function_signature_or_decorator_unsupported", function)
        annotations = [arg.annotation for arg in args.args] + [function.returns]
        annotations.extend(node.annotation for node in ast.walk(function) if type(node) is ast.AnnAssign)
        annotation_nodes = {id(node) for annotation in annotations if annotation is not None
                            for node in ast.walk(annotation)}
        for annotation in annotations:
            if annotation is None:
                continue
            if (type(annotation) is ast.Name and annotation.id in {"int", "bool"}
                    or type(annotation) is ast.Constant and type(annotation.value) is str
                    and annotation.value in {"int", "bool"}):
                continue
            reject("annotation_outside_int_bool_feature_profile", annotation)
        bound = {arg.arg for arg in args.args}
        bound.update(node.id for node in ast.walk(function)
                     if type(node) is ast.Name and type(node.ctx) is ast.Store)
        for node in ast.walk(function):
            if type(node) is ast.Name and type(node.ctx) is ast.Load:
                if node.id not in bound and id(node) not in annotation_nodes:
                    reject("global_or_unbound_name", node)
            if type(node) is ast.Constant and type(node.value) not in {int, bool}:
                # The only admitted strings are annotations, already checked.
                if node not in annotations:
                    reject("literal_outside_int_bool_feature_profile", node)
            if type(node) in {ast.Return, ast.Assign, ast.AnnAssign, ast.Pass, ast.If}:
                if type(node) is ast.Return and node.value is None:
                    reject("value_return_required", node)
                if type(node) is ast.Assign and (len(node.targets) != 1 or type(node.targets[0]) is not ast.Name
                                                 or node.type_comment):
                    reject("single_name_assignment_required", node)
                if type(node) is ast.AnnAssign and (type(node.target) is not ast.Name or node.value is None):
                    reject("initialized_name_annotation_required", node)
            elif isinstance(node, ast.stmt) and node is not function:
                reject("statement_outside_native_feature_profile", node)
            if isinstance(node, ast.expr) and type(node) not in {
                    ast.Name, ast.Constant, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare}:
                reject("expression_outside_native_feature_profile", node)
    return rows


def _feature_view(program: ProgramIR, contracts: tuple[ProgramContract, ...]) -> tuple[dict, dict]:
    """Keep native structure and values; normalize only identity references."""
    native = program.to_dict()
    identities = {}
    for collection, key, prefix in (("symbols", "symbol_id", "symbol"),
                                     ("expressions", "expression_id", "expression"),
                                     ("commands", "command_id", "command"),
                                     ("functions", "function_id", "function")):
        identities.update({row[key]: f"{prefix}:{index}" for index, row in enumerate(native[collection])})
    for index, function in enumerate(native["functions"]):
        identities[function["cfg"]["graph_id"]] = f"graph:{index}"
        identities.update({row["block_id"]: f"block:{position}" for position, row in enumerate(function["cfg"]["blocks"])})
    omitted = {"sources", "spans", "source_ref_ids", "source_ref_id", "span_ids", "metadata",
               "program_id", "contract_id", "clause_id", "statement"}
    reference_attributes = {"branch_condition", "then_commands", "else_commands"}

    def rewrite(value: Any, name: str = "") -> Any:
        if type(value) is dict:
            return {key: rewrite(child, key) for key, child in value.items() if key not in omitted}
        if type(value) is list:
            return [rewrite(child, name) for child in value]
        if type(value) is str and (name.endswith("_id") or name.endswith("_ids")
                                  or name in reference_attributes):
            return identities.get(value, value)
        return value

    return ({"schema": CODEBASE_FEATURE_VIEW_SCHEMA, "native_kind": "program", "document": rewrite(native)},
            {"schema": CODEBASE_FEATURE_VIEW_SCHEMA, "native_kind": "contracts",
             "documents": [rewrite(contract.to_dict()) for contract in contracts]})


def _correspondence(program: ProgramIR, raw: bytes) -> dict[str, Any]:
    spans = []
    for span in program.spans:
        if not 0 <= span.start_byte <= span.end_byte <= len(raw):
            raise CodebaseTargetError("native span is outside captured source")
        try:
            raw[:span.start_byte].decode("utf-8")
            text = raw[span.start_byte:span.end_byte].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CodebaseTargetError("native span cuts a UTF-8 source coordinate") from exc
        spans.append({"span_id": span.span_id, "source_ref_id": span.source_ref_id,
                      "start_byte": span.start_byte, "end_byte": span.end_byte, "source_text": text})
    subjects = []
    for collection, key in (("symbols", "symbol_id"), ("expressions", "expression_id"),
                             ("commands", "command_id"), ("functions", "function_id")):
        for row in program.to_dict()[collection]:
            subjects.append({"native_kind": collection, "native_id": row[key],
                             "source_ref_ids": row["source_ref_ids"], "span_ids": row["span_ids"]})
    return {"operation": "native_source_maps_retained_without_rebinding", "spans": spans,
            "subjects": subjects, "is_runtime_equivalence_proof": False}


def _binding(head: Any, manifest: CodebaseIRManifest, entry: SnapshotEntry, unit: CodebaseUnit, raw: bytes) -> dict:
    return {"schema": _BINDING_SCHEMA, "head": head.to_dict(), "repository_id": head.repository_id,
            "path": entry.path, "source_key": entry.source_key, "entry": entry.to_dict(), "unit": unit.to_dict(),
            "source_cid": entry.source_cid, "content_sha256": hashlib.sha256(raw).hexdigest(),
            "ast_cid": unit.ast_cid, "source_revision": "snapshot:" + manifest.snapshot.snapshot_cid}


def _prepare_bound(*, binding: dict, manifest: CodebaseIRManifest, receipt: Any,
                   ast_record: ASTRecord | None, raw: bytes, specs: tuple[ContractSpec, ...],
                   limits: CodebaseTargetLimits) -> DomainTargetEnvelope:
    if len(raw) > limits.max_source_bytes:
        raise CodebaseTargetError("captured source exceeds the target profile")
    path = binding["path"]
    if (type(path) is not str or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts
            or PurePosixPath(path).as_posix() != path):
        raise CodebaseTargetError("canonical captured repository-relative path required")
    unsupported, projections = [], []
    adapted, program, contracts, correspondence, bridge_rows = None, None, (), None, []
    ast_count = 0
    try:
        text = raw.decode("utf-8", errors="strict")
        if not path.endswith(".py"):
            unsupported.append({"kind": "program", "reason": "python_feature_profile_required"})
        else:
            try:
                tree = ast.parse(text, filename=path, type_comments=True)
                ast_count = _ast_bound(tree, limits)
                unsupported.extend(_source_frontiers(tree, limits))
            except (SyntaxError, ValueError, RecursionError) as exc:
                if isinstance(exc, CodebaseTargetError):
                    raise
                unsupported.append({"kind": "program", "reason": "malformed_python_source"})
            adapted = adapt_source_to_software_verification(text, path=path, language="python",
                revision=binding["source_revision"], max_source_bytes=limits.max_source_bytes,
                include_supervisor_evidence=False, preserve_type_annotations=True)
            unsupported.extend({"kind": "program", "reason": reason} for reason in adapted.unsupported_constructs)
            unsupported.extend({"kind": "program", "reason": "native_adapter_diagnostic", "diagnostic": item.to_dict()}
                               for item in adapted.diagnostics)
            if adapted.status is not SourceAdapterStatus.SUCCESS:
                unsupported.append({"kind": "program", "reason": "native_adapter_not_complete", "status": adapted.status.value})
            program = adapted.program
            if program is not None:
                program.validate()
                if (len(program.sources) != 1 or program.sources[0].content_sha256 != binding["content_sha256"]
                        or program.sources[0].source_revision != binding["source_revision"]
                        or program.metadata.get("path") != path):
                    raise CodebaseTargetError("native ProgramIR differs from captured source")
                if specs:
                    try:
                        program, contracts = attach_contract_specs(program, specs)
                        for contract in contracts:
                            contract.validate_against(program)
                    except PipelineError as exc:
                        unsupported.append({"kind": "contract", "reason": "native_contract_injection_unsupported",
                                            "diagnostic": str(exc)})
                        contracts = ()
                correspondence = _correspondence(program, raw)
                bridge = SoftwareVerificationSyntaxBridge()
                for kind, document in [("program", program), *(("contract", item) for item in contracts)]:
                    try:
                        observation = bridge.round_trip(document)
                    except SoftwareVerificationBridgeError as exc:
                        unsupported.append({"kind": kind, "reason": "native_bridge_unsupported", "diagnostic": exc.to_dict()})
                        continue
                    bridge_rows.append({"kind": kind, "native_id": getattr(document, "program_id", getattr(document, "contract_id", "")),
                                        "result": observation.to_dict()})
                    if not observation.exact:
                        unsupported.append({"kind": kind, "reason": "native_bridge_not_exact"})
                program_view, contract_view = _feature_view(program, contracts)
                for kind, identity, expression in (("program", CODEBASE_PROGRAM_PROJECTION, program_view),
                                                    ("contract", CODEBASE_CONTRACTS_PROJECTION, contract_view)):
                    route = bridge.route_for(kind)
                    projections.append({"projection_id": identity, "view_id": route.payload_schema,
                        "logic_family": route.family_id, "profile": route.profile_id, "properties": [],
                        "view_role": route.view_role or None, "expression": expression,
                        "representation_kind": "native_structural_feature_view", "producer_id": "codebase-source-target-adapter",
                        "producer_version": CODEBASE_TARGET_SCHEMA, "target_schema": CODEBASE_TARGET_SCHEMA,
                        "feature_only": True})
    except UnicodeDecodeError:
        unsupported.append({"kind": "program", "reason": "non_utf8_captured_source"})
    if program is None:
        unsupported.append({"kind": "program", "reason": "missing_native_program"})
    if specs and len(contracts) != len(specs):
        unsupported.append({"kind": "contract", "reason": "incomplete_authored_contract_inventory"})
    if ast_record is None or binding["unit"]["parse_status"] != "ok":
        unsupported.append({"kind": "captured_ast", "reason": "structural_ast_not_complete"})
    details = {"target_schema": CODEBASE_TARGET_SCHEMA, "source_binding": binding,
        "manifest": manifest.to_dict(), "publication_receipt": receipt.to_dict(),
        "captured_ast": None if ast_record is None else ast_record.to_dict(), "source_bytes_hex": raw.hex(),
        "authored_contracts": [item.to_dict() for item in specs], "limits": limits.to_dict(),
        "native_adapter": None if adapted is None else adapted.to_dict(),
        "native_program": None if program is None else program.to_dict(),
        "native_contracts": [item.to_dict() for item in contracts],
        "authored_contract_cids": [cid_for_structured(item.to_dict()) for item in specs],
        "lowered_contract_sha256": [hashlib.sha256(_wire(item.to_dict())).hexdigest() for item in contracts],
        "correspondence": correspondence, "native_bridge_results": bridge_rows,
        "ast_node_count": ast_count, "profile": describe_codebase_target_profile(), **_AUTHORITY}
    details["unknown_inventory"] = ([] if program is None else [
        {"native_kind": collection, "native_id": getattr(item, identity), "field": "type_ref", "value": "any"}
        for collection, identity in (("symbols", "symbol_id"), ("expressions", "expression_id"))
        for item in getattr(program, collection) if item.type_ref == "any"
    ])
    details["unknown_inventory"].extend([] if program is None else [
        {"native_kind": "functions", "native_id": item.function_id, "field": "purity", "value": "unknown"}
        for item in program.functions if item.purity.value == "unknown"
    ])
    source_digest = hashlib.sha256(_wire({"target_schema": CODEBASE_TARGET_SCHEMA,
        "source_binding": binding, "authored_contracts": details["authored_contracts"]})).hexdigest()
    result = build_target_envelope(domain_id="codebase_ir", source_digest=source_digest, projections=projections,
        validation=[{"validator_id": _VALIDATOR, "stage": "target", "required": True,
                     "status": "passed" if program is not None and not unsupported else "unsupported", "details": details}],
        unsupported=unsupported, qualification_gaps=_GAPS)
    _wire(result.to_dict(), limits.max_target_bytes)
    return result


def prepare_codebase_targets(index: RepositoryCodebaseIndex, *, expected_head: Any, path: str,
                            contracts: Sequence[ContractSpec] = (), limits: CodebaseTargetLimits | None = None) -> DomainTargetEnvelope:
    """Read captured native history and produce feature targets without live I/O.

    A historical head remains usable after a checkout edit.  Current training
    and admission require separate observations by the owning coordinator.
    """
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog, CodebaseHead
    if (type(index) is not RepositoryCodebaseIndex or type(index.artifacts) is not ImmutableCAS
            or type(index.catalog) is not CodebaseCatalog or type(expected_head) is not CodebaseHead):
        raise CodebaseTargetError("native catalog-owned codebase index, artifact owner and CodebaseHead required")
    if type(path) is not str:
        raise CodebaseTargetError("exact captured path required")
    limits = CodebaseTargetLimits() if limits is None else limits
    if type(limits) is not CodebaseTargetLimits:
        raise CodebaseTargetError("native CodebaseTargetLimits required")
    specs = _specs(contracts, limits)
    manifest = index.load(expected_head.manifest_cid)
    # Native publication receipts live in the closed structural owner's SQL
    # operations history, rather than the CAS.  Reuse its bounded replay.
    with index.catalog.store._lock:
        index.catalog._ensure_owner()
        with index.catalog.store._transaction():
            index.catalog._check_schema()
            receipt = index.catalog._read_receipt("receipt_cid", expected_head.receipt_cid)
    if (receipt is None or receipt.head != expected_head or manifest.snapshot.repository_id != expected_head.repository_id
            or manifest.snapshot.snapshot_cid != expected_head.snapshot_cid
            or manifest.ast_revision_id != expected_head.ast_revision_id):
        raise CodebaseTargetError("head does not bind its captured manifest and publication")
    entry = next((item for item in manifest.snapshot.entries if item.path == path), None)
    if entry is None or entry.is_opaque:
        raise CodebaseTargetError("path must name a captured nonopaque source member")
    unit = next(item for item in manifest.units if item.source_key == entry.source_key)
    ast_record = index.load_ast_artifact(manifest, path)
    raw = index.artifacts.get_bytes(entry.source_cid)
    if entry.size_bytes != len(raw):
        raise CodebaseTargetError("captured entry byte count differs")
    return _prepare_bound(binding=_binding(expected_head, manifest, entry, unit, raw), manifest=manifest,
                          receipt=receipt, ast_record=ast_record, raw=raw, specs=specs, limits=limits)


def validate_codebase_targets(target: DomainTargetEnvelope) -> DomainTargetEnvelope:
    """Pure native replay of the complete captured declaration, never a prover.

    The embedded historical records are integrity claims.  Replay neither
    observes a checkout nor attests original producer/checker execution.
    """
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead, CodebasePublicationReceipt
    if type(target) is not DomainTargetEnvelope:
        raise CodebaseTargetError("native immutable DomainTargetEnvelope required")
    value = target.to_dict()
    _wire(value)
    if (value["domain_id"] != "codebase_ir" or len(value["validation"]) != 1
            or value["validation"][0].get("validator_id") != _VALIDATOR):
        raise CodebaseTargetError("exact native CodebaseIR target profile required")
    details = value["validation"][0]["details"]
    try:
        limits = CodebaseTargetLimits(**details["limits"])
        binding = details["source_binding"]
        head = CodebaseHead.from_dict(binding["head"])
        manifest = CodebaseIRManifest.from_dict(details["manifest"])
        receipt = CodebasePublicationReceipt.from_dict(details["publication_receipt"])
        entry = SnapshotEntry.from_dict(binding["entry"])
        unit = CodebaseUnit.from_dict(binding["unit"])
        raw_hex = details["source_bytes_hex"]
        if type(raw_hex) is not str or len(raw_hex) > limits.max_source_bytes * 2:
            raise CodebaseTargetError("bounded exact source hexadecimal required")
        raw = bytes.fromhex(raw_hex)
        if raw.hex() != raw_hex or cid_for_bytes(raw) != entry.source_cid or len(raw) != entry.size_bytes:
            raise CodebaseTargetError("embedded source bytes differ from the captured entry")
        if (manifest.cid != head.manifest_cid or receipt.head != head
                or manifest.snapshot.snapshot_cid != head.snapshot_cid
                or manifest.snapshot.repository_id != head.repository_id
                or manifest.ast_revision_id != head.ast_revision_id
                or entry not in manifest.snapshot.entries or unit not in manifest.units
                or unit.source_key != entry.source_key or unit.entry_cid != entry.entry_cid
                or _binding(head, manifest, entry, unit, raw) != binding):
            raise CodebaseTargetError("embedded source/head/unit binding differs")
        ast_record = None if details["captured_ast"] is None else ASTRecord.from_dict(details["captured_ast"])
        if ast_record is not None:
            provenance = ast_record.provenance
            if (cid_for_structured(ast_record.to_dict()) != unit.ast_cid
                    or provenance.source_cid != entry.source_cid or provenance.path != entry.path
                    or provenance.repository_id != head.repository_id
                    or provenance.revision != binding["source_revision"]
                    or provenance.repository_tree_cid != head.snapshot_cid):
                raise CodebaseTargetError("embedded AST does not bind the captured source")
        elif unit.ast_cid is not None:
            raise CodebaseTargetError("captured AST is missing")
        specs = _specs([ContractSpec(**row) for row in details["authored_contracts"]], limits)
        if [item.to_dict() for item in specs] != details["authored_contracts"]:
            raise CodebaseTargetError("authored contract fields are not canonical")
        rebuilt = _prepare_bound(binding=binding, manifest=manifest, receipt=receipt,
            ast_record=ast_record, raw=raw, specs=specs, limits=limits)
    except CodebaseTargetError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise CodebaseTargetError("malformed native CodebaseIR target binding") from exc
    if rebuilt.canonical_bytes != target.canonical_bytes:
        raise CodebaseTargetError("CodebaseIR target native replay differs")
    return rebuilt


def source_binding_from_target(target: DomainTargetEnvelope) -> dict[str, Any]:
    """Return a detached replay-validated source binding and authored contracts."""
    details = validate_codebase_targets(target).to_dict()["validation"][0]["details"]
    return {**details["source_binding"], "authored_contracts": details["authored_contracts"]}


__all__ = ["CODEBASE_TARGET_SCHEMA", "CODEBASE_FEATURE_VIEW_SCHEMA", "CODEBASE_PROGRAM_PROJECTION",
           "CODEBASE_CONTRACTS_PROJECTION", "CodebaseTargetError", "CodebaseTargetLimits",
           "describe_codebase_target_profile", "prepare_codebase_targets", "validate_codebase_targets",
           "source_binding_from_target"]
