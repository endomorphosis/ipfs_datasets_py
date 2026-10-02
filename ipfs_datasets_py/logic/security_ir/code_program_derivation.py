"""Guarded, non-executing Python body to native structural ProgramIR targets.

This module deliberately admits less than the general native source adapter.
It preserves exact bytes, checks a closed AST fragment, verifies the adapter's
expression/command structure, and records every source-reference remapping.
It does not infer a security specification or establish runtime equivalence.
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys

from ..ir_core.identity import canonical_identity
from ..ir_core.provenance import SourceRef, SourceReviewStatus
from ..software_verification.program import ProgramIR
from ..software_verification.source_adapters import (
    SOURCE_ADAPTER_VERSION, SOURCE_SOFTWARE_VERIFICATION_ADAPTER,
    SourceAdapterStatus, adapt_source_to_software_verification,
)
from .code_logic_projection import CodeLogicEvidence, project_code_logic
from .cvefixes.schemas import CodeUnit

SCHEMA = "security-code-program-derivation/v1"
PROFILE_SCHEMA = "security-code-program-derivation-profile/v1"
MAX_SOURCE_BYTES = 65_536
MAX_AST_NODES = 512
MAX_AST_DEPTH = 32
MAX_LITERAL_BITS = 64
_BINARY = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul"}
_UNARY = {ast.UAdd: "pos", ast.USub: "neg"}
_AUTHORITY = {"authority": "candidate_structural_model", "proof_authority": False,
    "execution_authority": False, "completion_authority": False,
    "source_semantics_verified": False, "security_specification_inferred": False}


class CodeProgramDerivationError(ValueError):
    """A supplied result or an exact source binding has changed."""


class _Frontier(ValueError):
    pass


def _wire(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False).encode("utf-8")
    if len(raw) > 4_000_000:
        raise CodeProgramDerivationError("bounded code derivation payload required")
    return raw


def _cid(value, schema):
    return canonical_identity(value, domain="security-ir/code-program-derivation", schema_version=schema).cid


def describe_code_program_derivation_profile() -> dict:
    value = {"schema": PROFILE_SCHEMA, "adapter": SOURCE_SOFTWARE_VERIFICATION_ADAPTER,
        "adapter_version": SOURCE_ADAPTER_VERSION, "parser": sys.implementation.cache_tag,
        "language": "python", "target_kind": "program", "family": "program", "profile": "program_ir",
        "max_source_bytes": MAX_SOURCE_BYTES, "max_ast_nodes": MAX_AST_NODES,
        "max_ast_depth": MAX_AST_DEPTH, "max_integer_literal_bits": MAX_LITERAL_BITS,
        "whitelist": {"module": "one synchronous function, ASCII source; only LF and tab controls",
            "parameters": "simple positional parameters without defaults or annotations",
            "statements": ["fresh single-local assignment", "one terminal value return"],
            "expressions": ["integer literal excluding bool", "previously bound name",
                            "binary + - *", "unary + -"]},
        "assumptions": {"modeled_argument_type": "exact built-in Python int; not verified from source",
            "native_parameter_and_result_types": "any; no silent integer-sort refinement",
            "integer_values": "unbounded mathematical model; literal-size bound is a parser resource limit",
            "execution_model": "sequential calls under the declared input assumption",
            "excluded_runtime_behavior": ["operator overloading", "resource exhaustion", "concurrency"],
            "native_effects_may_overapproximate_parameter_reads": True},
        "requires_native_status": "success without unsupported constructs or diagnostics",
        "include_supervisor_evidence": False,
        "source_remapping": "exact source SHA/CID plus replayed source-ref and byte-span mapping",
        "unsupported": ["calls and keyword arguments", "defaults and annotations", "decorators",
            "branches and loops", "global reads", "reassignment", "imports", "multiple functions",
            "non-ASCII source", "heap and information-flow semantics", "contract inference"],
        "provider_calls": 0, "solver_calls": 0, "executes_source": False, **_AUTHORITY}
    return {**value, "profile_cid": _cid(value, PROFILE_SCHEMA)}


def _guard(source):
    if not source.isascii():
        raise _Frontier("non_ascii_source")
    if any(ord(char) < 32 and char not in "\n\t" or ord(char) == 127 for char in source):
        raise _Frontier("source_control_character_unsupported")
    try:
        tree = ast.parse(source, type_comments=True)
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise _Frontier("python_syntax_unsupported") from exc
    pending, count = [(tree, 0)], 0
    while pending:
        node, depth = pending.pop()
        count += 1
        if count > MAX_AST_NODES or depth > MAX_AST_DEPTH:
            raise _Frontier("ast_resource_bound")
        pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    if len(tree.body) != 1 or type(tree.body[0]) is not ast.FunctionDef or tree.type_ignores:
        raise _Frontier("one_plain_function_required")
    function = tree.body[0]
    args = function.args
    if (function.decorator_list or function.returns or function.type_comment
            or getattr(function, "type_params", ()) or args.posonlyargs or args.kwonlyargs
            or args.vararg or args.kwarg or args.defaults or args.kw_defaults
            or any(arg.annotation or arg.type_comment for arg in args.args)):
        raise _Frontier("function_signature_or_decorator_unsupported")
    defined = {arg.arg for arg in args.args}
    if len(defined) != len(args.args):
        raise _Frontier("duplicate_parameter")

    def expression(node):
        if type(node) is ast.Constant:
            if type(node.value) is not int or node.value.bit_length() > MAX_LITERAL_BITS:
                raise _Frontier("literal_type_or_size_unsupported")
        elif type(node) is ast.Name:
            if node.id not in defined:
                raise _Frontier("unbound_or_global_name")
        elif type(node) is ast.BinOp and type(node.op) in _BINARY:
            expression(node.left); expression(node.right)
        elif type(node) is ast.UnaryOp and type(node.op) in _UNARY:
            expression(node.operand)
        else:
            raise _Frontier("expression_unsupported:" + type(node).__name__)

    if not function.body or type(function.body[-1]) is not ast.Return or function.body[-1].value is None:
        raise _Frontier("terminal_value_return_required")
    for statement in function.body[:-1]:
        if (type(statement) is not ast.Assign or len(statement.targets) != 1
                or type(statement.targets[0]) is not ast.Name or statement.type_comment):
            raise _Frontier("statement_unsupported:" + type(statement).__name__)
        name = statement.targets[0].id
        if name in defined:
            raise _Frontier("reassignment_unsupported")
        expression(statement.value)
        defined.add(name)
    expression(function.body[-1].value)
    return function, count


def _check_structure(program, function, source):
    """Check the native result against admitted AST structure and byte spans."""
    if len(program.functions) != 1 or len(program.sources) != 1 or program.global_symbol_ids:
        raise _Frontier("native_program_shape_changed")
    native_function = program.functions[0]
    cfg = native_function.cfg
    if (native_function.name != function.name or len(cfg.blocks) != 1 or cfg.edges
            or len(cfg.command_ids) != len(function.body)):
        raise _Frontier("native_control_flow_changed")
    symbols = {item.symbol_id: item for item in program.symbols}
    if [symbols[key].name for key in native_function.parameter_symbol_ids] != [arg.arg for arg in function.args.args]:
        raise _Frontier("native_parameters_changed")
    expected_symbols = {(arg.arg, "parameter") for arg in function.args.args}
    expected_symbols |= {(stmt.targets[0].id, "local") for stmt in function.body[:-1]}
    expected_symbols.add(("result", "result"))
    if ({(symbol.name, symbol.kind.value) for symbol in symbols.values()} != expected_symbols
            or any(symbol.type_ref != "any" for symbol in symbols.values())
            or native_function.return_type != "any"):
        raise _Frontier("native_symbol_scope_changed")
    bindings = {}
    for ids, role in ((native_function.parameter_symbol_ids, "parameter"),
                      (native_function.local_symbol_ids, "local")):
        for key in ids:
            symbol = symbols[key]
            if symbol.kind.value != role or symbol.name in bindings:
                raise _Frontier("native_symbol_scope_changed")
            bindings[symbol.name] = key
    if (not native_function.result_symbol_id
            or symbols[native_function.result_symbol_id].kind.value != "result"
            or set(bindings.values()) | {native_function.result_symbol_id} != set(symbols)):
        raise _Frontier("native_symbol_scope_changed")
    expressions = {item.expression_id: item for item in program.expressions}
    commands = {item.command_id: item for item in program.commands}
    spans = {item.span_id: item for item in program.spans}
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    seen = set()

    def span_matches(item, node):
        expected = (offsets[node.lineno - 1] + node.col_offset,
                    offsets[node.end_lineno - 1] + node.end_col_offset)
        if len(item.span_ids) != 1:
            raise _Frontier("native_source_span_missing")
        span = spans[item.span_ids[0]]
        if (span.start_byte, span.end_byte) != expected:
            raise _Frontier("native_source_span_changed")

    def matches(key, node):
        expr = expressions[key]
        seen.add(key)
        span_matches(expr, node)
        if expr.type_ref != ("int" if type(node) is ast.Constant else "any"):
            raise _Frontier("native_expression_type_changed")
        if type(node) is ast.Constant:
            good = (expr.kind.value == "literal" and type(expr.attributes.get("value")) is int
                    and expr.attributes["value"] == node.value and not expr.operand_ids and not expr.symbol_ids)
        elif type(node) is ast.Name:
            good = (expr.kind.value == "symbol" and expr.symbol_ids == (bindings[node.id],)
                    and not expr.operand_ids)
        else:
            children = (node.left, node.right) if type(node) is ast.BinOp else (node.operand,)
            operator = (_BINARY if type(node) is ast.BinOp else _UNARY)[type(node.op)]
            good = (expr.kind.value == ("binary" if len(children) == 2 else "unary")
                    and expr.operator == operator and len(expr.operand_ids) == len(children)
                    and expr.evaluation_order == expr.operand_ids and not expr.symbol_ids)
            if good:
                for child_key, child in zip(expr.operand_ids, children):
                    matches(child_key, child)
        if not good:
            raise _Frontier("native_expression_structure_changed")

    for key, statement in zip(cfg.command_ids, function.body):
        command = commands[key]
        span_matches(command, statement)
        if len(command.expression_ids) != 1:
            raise _Frontier("native_statement_value_missing")
        if type(statement) is ast.Assign:
            if (command.kind.value != "assign" or len(command.target_symbol_ids) != 1
                    or command.target_symbol_ids != (bindings[statement.targets[0].id],)):
                raise _Frontier("native_assignment_changed")
        elif command.kind.value != "return" or command.target_symbol_ids:
            raise _Frontier("native_return_changed")
        matches(command.expression_ids[0], statement.value)
    if seen != set(expressions) or set(cfg.command_ids) != set(commands):
        raise _Frontier("native_unaccounted_expressions_or_commands")


def _remap(program, code_unit, raw):
    original = program.sources[0]
    original.validate()
    if original.content_sha256 != hashlib.sha256(raw).hexdigest():
        raise _Frontier("native_source_hash_changed")
    source = SourceRef(ref_id=code_unit.cid, source_uri="code-unit:" + code_unit.cid,
        source_id=code_unit.path, source_revision="code-unit:" + code_unit.cid,
        content_sha256=code_unit.payload["body_sha256"], content_cid=code_unit.payload["body_cid"],
        review_status=SourceReviewStatus.MACHINE_EXTRACTED)
    mappings = []
    for span in program.spans:
        if span.source_ref_id != original.ref_id or not 0 <= span.start_byte <= span.end_byte <= len(raw):
            raise _Frontier("native_span_source_or_bounds_changed")
        mappings.append({"span_id": span.span_id, "from_source": original.ref_id,
            "to_source": source.ref_id, "start_byte": span.start_byte, "end_byte": span.end_byte,
            "span_sha256": hashlib.sha256(raw[span.start_byte:span.end_byte]).hexdigest()})

    def rewrite(value):
        if type(value) is dict:
            updated = {}
            for key, item in value.items():
                if key == "source_ref_ids":
                    if any(ref != original.ref_id for ref in item):
                        raise _Frontier("native_foreign_source_reference")
                    updated[key] = [source.ref_id for _ in item]
                elif key == "source_ref_id":
                    if item != original.ref_id:
                        raise _Frontier("native_foreign_span_reference")
                    updated[key] = source.ref_id
                else:
                    updated[key] = rewrite(item)
            return updated
        return [rewrite(item) for item in value] if type(value) is list else value
    wire = rewrite(json.loads(_wire(program.to_dict())))
    wire["sources"], wire["program_id"] = [source.to_dict()], ""
    remapped = ProgramIR.from_dict(wire)
    receipt = {"from_source": original.to_dict(), "to_source": source.to_dict(),
        "before_program_id": program.program_id, "after_program_id": remapped.program_id,
        "byte_spans": sorted(mappings, key=lambda row: row["span_id"]),
        "operation": "source_reference_rebinding_only", "unchanged_body_sha256": original.content_sha256}
    return remapped, source, receipt


def derive_code_program(*, code_unit: CodeUnit, source_bytes: bytes | None) -> dict:
    """Derive only a guarded structural program target; never execute source."""
    baseline = project_code_logic(code_unit=code_unit, source_bytes=source_bytes, requested_kinds=["program"])
    profile = describe_code_program_derivation_profile()
    value = {"schema": SCHEMA, "profile_cid": profile["profile_cid"], "source": baseline["source"],
        "assumptions": profile["assumptions"], "status": "unsupported", "unsupported": [],
        "native_adapter": None, "source_remapping": None, "projection": None,
        "provider_calls": 0, "solver_calls": 0, "executes_source": False, **_AUTHORITY}
    if baseline["status"] == "quarantined":
        value.update(status="quarantined", unsupported=baseline["unsupported"])
    else:
        try:
            if len(source_bytes) > MAX_SOURCE_BYTES:
                raise _Frontier("source_resource_bound")
            if code_unit.language.lower() not in {"python", "py"}:
                raise _Frontier("language_unsupported")
            text = source_bytes.decode("utf-8")
            function, count = _guard(text)
            adapted = adapt_source_to_software_verification(text, path=code_unit.path,
                language="python", max_source_bytes=MAX_SOURCE_BYTES,
                include_supervisor_evidence=False)
            value["native_adapter"] = {"interface": adapted.interface, "version": adapted.adapter_version,
                "status": adapted.status.value, "unsupported": list(adapted.unsupported_constructs),
                "diagnostic_count": len(adapted.diagnostics), "ast_node_count": count}
            if (adapted.status is not SourceAdapterStatus.SUCCESS or adapted.unsupported_constructs
                    or adapted.diagnostics or adapted.program is None):
                raise _Frontier("native_adapter_not_complete")
            _check_structure(adapted.program, function, text)
            program, source, remapping = _remap(adapted.program, code_unit, source_bytes)
            projection = project_code_logic(code_unit=code_unit, source_bytes=source_bytes,
                typed_inputs=[CodeLogicEvidence(program, source)], requested_kinds=["program"])
            if projection["status"] != "projected" or projection["unsupported"]:
                raise _Frontier("native_program_projection_unsupported")
            value.update(status="derived", source_remapping=remapping, projection=projection)
        except _Frontier as exc:
            value["unsupported"] = [{"kind": "program", "reason": str(exc)}]
    _wire(value)
    return {**value, "derivation_cid": _cid(value, SCHEMA)}


def validate_code_program_derivation(payload: dict, *, code_unit: CodeUnit, source_bytes: bytes | None) -> dict:
    """Reparse current bytes and replay the native lowering, source map, and projection."""
    if type(payload) is not dict:
        raise CodeProgramDerivationError("code derivation object required")
    _wire(payload)
    actual = derive_code_program(code_unit=code_unit, source_bytes=source_bytes)
    if _wire(actual) != _wire(payload):
        raise CodeProgramDerivationError("source derivation identity or content differs")
    return actual


__all__ = ["CodeProgramDerivationError", "describe_code_program_derivation_profile",
           "derive_code_program", "validate_code_program_derivation"]
