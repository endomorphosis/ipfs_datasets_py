"""Bind a learned expression to a conservative, typed Python source fragment.

This adapter checks a decoder candidate; it never repairs or replaces a wrong
candidate.  The native source adapter supplies the CFG and exact byte spans.
Only explicit ``int`` parameter annotations admit integer model refinement.
Annotations are a declared input contract, not a runtime type check or a proof
of Python equivalence.  No source is executed and no model or solver is called.
"""
from __future__ import annotations

import ast
import hashlib
import json

from ....software_verification.program import ProgramExpression, ProgramIR
from ....software_verification.source_adapters import (
    SourceAdapterStatus, adapt_source_to_software_verification,
)
from ....software_verification.syntax_bridge import SoftwareVerificationSyntaxBridge

SCHEMA = "security-source-program-binding-384/v1"
MAX_SOURCE_BYTES = 65_536
MAX_AST_NODES = 256
_OPERATORS = {
    ast.Add: ("+", "add", "integer"), ast.Sub: ("-", "sub", "integer"),
    ast.Mult: ("*", "mul", "integer"),
    ast.Lt: ("<", "lt", "boolean"), ast.LtE: ("<=", "le", "boolean"),
    ast.Gt: (">", "gt", "boolean"), ast.GtE: (">=", "ge", "boolean"),
    ast.Eq: ("==", "eq", "boolean"), ast.NotEq: ("!=", "ne", "boolean"),
}
_AUTHORITY = dict(proof_authority=False, execution_authority=False,
    completion_authority=False, source_semantics_verified=False,
    security_specification_inferred=False, whole_program_semantics_verified=False)
_ASSUMPTIONS = [
    "The annotation name int denotes exact built-in Python integers; annotations do not enforce runtime types.",
    "The mathematical integer model excludes resource exhaustion and concurrent environment changes.",
    "Native effects and purity retain the source adapter's conservative classification.",
]


class _Rejected(ValueError):
    def __init__(self, code, *, status="unsupported"):
        super().__init__(code)
        self.code, self.status = code, status


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _require(condition, code, *, status="unsupported"):
    if not condition:
        raise _Rejected(code, status=status)


def _guard(source):
    _require(source.isascii() and all(ord(c) >= 32 or c in "\n\t" for c in source)
             and "\x7f" not in source, "source_encoding_unsupported")
    try:
        tree = ast.parse(source, type_comments=True)
    except (ValueError, SyntaxError, RecursionError) as exc:
        raise _Rejected("python_syntax_unsupported") from exc
    pending, count = [(tree, 0)], 0
    while pending:
        node, depth = pending.pop()
        count += 1
        _require(count <= MAX_AST_NODES and depth <= 24, "ast_resource_bound")
        pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    _require(len(tree.body) == 1 and type(tree.body[0]) is ast.FunctionDef
             and not tree.type_ignores, "one_plain_function_required")
    function = tree.body[0]
    args = function.args
    _require(not (function.decorator_list or function.type_comment
        or getattr(function, "type_params", ()) or args.posonlyargs or args.kwonlyargs
        or args.vararg or args.kwarg or args.defaults or args.kw_defaults),
        "function_signature_unsupported")
    _require(len(args.args) == 2 and len({arg.arg for arg in args.args}) == 2,
             "two_distinct_parameters_required")
    _require(all(arg.arg != "result" for arg in args.args),
             "candidate_expression_reference_collision")
    _require(all(type(arg.annotation) is ast.Name and arg.annotation.id == "int"
                 and not arg.type_comment and arg.arg not in {"int", "bool"}
                 for arg in args.args), "explicit_integer_parameter_annotations_required")
    statements = function.body
    _require(len(statements) in {1, 2} and type(statements[-1]) is ast.Return,
             "direct_return_or_single_temporary_required")
    temporary = None
    if len(statements) == 2:
        assignment = statements[0]
        _require(type(assignment) is ast.Assign and len(assignment.targets) == 1
            and type(assignment.targets[0]) is ast.Name and not assignment.type_comment,
            "single_fresh_temporary_required")
        temporary = assignment.targets[0].id
        _require(temporary not in {arg.arg for arg in args.args}, "parameter_reassignment_unsupported")
        _require(type(statements[-1].value) is ast.Name
                 and statements[-1].value.id == temporary, "temporary_return_mismatch")
        expression = assignment.value
    else:
        expression = statements[0].value
    if type(expression) is ast.BinOp:
        operator, left, right = expression.op, expression.left, expression.right
    elif type(expression) is ast.Compare and len(expression.ops) == len(expression.comparators) == 1:
        operator, left, right = expression.ops[0], expression.left, expression.comparators[0]
    else:
        raise _Rejected("single_binary_expression_required")
    _require(type(operator) in _OPERATORS, "operator_semantics_unsupported")
    _require(type(left) is ast.Name and type(right) is ast.Name
             and {left.id, right.id} == {arg.arg for arg in args.args},
             "both_distinct_parameters_must_be_operands")
    symbol, native_operator, result_type = _OPERATORS[type(operator)]
    expected_annotation = "bool" if result_type == "boolean" else "int"
    _require(function.returns is None or (type(function.returns) is ast.Name
             and function.returns.id == expected_annotation), "return_annotation_mismatch")
    return function, expression, (left, right), temporary, symbol, native_operator, result_type


def _candidate(candidate, operands, operator, result_type):
    _require(type(candidate) is dict and set(candidate) == {"kind", "document"}
             and candidate["kind"] == "program_expression",
             "program_expression_candidate_required", status="mismatch")
    ids = tuple("expr:" + operand.id for operand in operands)
    expected = ProgramExpression("expr:result", "binary", result_type,
        operand_ids=ids, evaluation_order=ids, operator=operator,
        source_ref_ids=("source",)).to_dict()
    document = candidate["document"]
    _require(type(document) is dict, "candidate_document_required", status="mismatch")
    # Compare the closed wire form, not from_dict defaults: never ignore extra
    # attributes, foreign references, omitted order, or boolean/integer drift.
    _require(_wire(document) == _wire(expected),
             "candidate_does_not_match_source_expression", status="mismatch")


def _native_context(source, guarded):
    function, expression, operands, temporary, operator, native_operator, result_type = guarded
    result = adapt_source_to_software_verification(source, path="source.py", language="python",
        max_source_bytes=MAX_SOURCE_BYTES, include_supervisor_evidence=False)
    _require(result.status is SourceAdapterStatus.SUCCESS and result.program is not None
             and not result.unsupported_constructs and not result.diagnostics,
             "native_source_lowering_incomplete")
    program = result.program
    _require(len(program.sources) == len(program.functions) == 1 and not program.global_symbol_ids,
             "native_program_shape_changed")
    source_ref = program.sources[0]
    raw = source.encode("utf-8")
    _require(source_ref.content_sha256 == _sha(raw), "native_source_hash_changed")
    native_function = program.functions[0]
    cfg = native_function.cfg
    _require(native_function.name == function.name and len(cfg.blocks) == 1 and not cfg.edges
             and len(cfg.command_ids) == len(function.body), "native_control_flow_changed")
    symbols = {item.symbol_id: item for item in program.symbols}
    expressions = {item.expression_id: item for item in program.expressions}
    commands = {item.command_id: item for item in program.commands}
    spans = {item.span_id: item for item in program.spans}
    parameters = [symbols[key] for key in native_function.parameter_symbol_ids]
    _require([p.name for p in parameters] == [arg.arg for arg in function.args.args]
             and all(p.kind.value == "parameter" for p in parameters), "native_parameters_changed")
    expected_symbols = {(arg.arg, "parameter") for arg in function.args.args} | {("result", "result")}
    if temporary:
        expected_symbols.add((temporary, "local"))
    _require({(item.name, item.kind.value) for item in symbols.values()} == expected_symbols
             and all(item.type_ref == "any" for item in symbols.values())
             and native_function.return_type == "any", "native_symbol_scope_changed")
    bindings = {item.name: item.symbol_id for item in symbols.values() if item.kind.value != "result"}
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    seen = set()
    expression_binding = {}

    def check_span(item, node):
        _require(item.source_ref_ids == (source_ref.ref_id,) and len(item.span_ids) == 1,
                 "native_source_reference_changed")
        span = spans[item.span_ids[0]]
        expected = (offsets[node.lineno - 1] + node.col_offset,
                    offsets[node.end_lineno - 1] + node.end_col_offset)
        _require(span.source_ref_id == source_ref.ref_id
                 and (span.start_byte, span.end_byte) == expected, "native_source_span_changed")

    def check_expression(key, node):
        item = expressions[key]
        seen.add(key)
        check_span(item, node)
        _require(not item.attributes, "native_expression_attributes_changed")
        if type(node) is ast.Name:
            _require(item.kind.value == "symbol" and item.symbol_ids == (bindings[node.id],)
                and not item.operand_ids and not item.operator and item.type_ref == "any",
                "native_operand_changed")
            if node is operands[0] or node is operands[1]:
                expression_binding["expr:" + node.id] = key
        else:
            _require(node is expression and item.kind.value == "binary"
                and item.operator == native_operator and len(item.operand_ids) == 2
                and item.evaluation_order == item.operand_ids and not item.symbol_ids
                and item.type_ref == ("boolean" if result_type == "boolean" else "any"),
                "native_operation_changed")
            expression_binding["expr:result"] = key
            for child_key, child in zip(item.operand_ids, operands):
                check_expression(child_key, child)

    for key, statement in zip(cfg.command_ids, function.body):
        command = commands[key]
        check_span(command, statement)
        _require(len(command.expression_ids) == 1 and command.evaluation_order == command.expression_ids
                 and not command.attributes and not command.undefined_behavior,
                 "native_command_changed")
        if type(statement) is ast.Assign:
            _require(command.kind.value == "assign" and command.target_symbol_ids == (bindings[temporary],),
                     "native_assignment_changed")
        else:
            _require(command.kind.value == "return" and not command.target_symbol_ids,
                     "native_return_changed")
        check_expression(command.expression_ids[0], statement.value)
    _require(seen == set(expressions) and set(cfg.command_ids) == set(commands),
             "native_unaccounted_expressions_or_commands")
    for span in spans.values():
        _require(span.source_ref_id == source_ref.ref_id
                 and 0 <= span.start_byte <= span.end_byte <= len(raw), "native_span_bounds_changed")

    wire = program.to_dict()
    del wire["program_id"]
    refinements = []
    parameter_ids = set(native_function.parameter_symbol_ids)
    types = {key: "integer" if key in parameter_ids else result_type for key in symbols}
    for row in wire["symbols"]:
        row["type_ref"] = types[row["symbol_id"]]
        refinements.append(dict(kind="symbol", id=row["symbol_id"], before="any", after=row["type_ref"]))
    for row in wire["expressions"]:
        before = row["type_ref"]
        row["type_ref"] = types[row["symbol_ids"][0]] if row["kind"] == "symbol" else result_type
        if before != row["type_ref"]:
            refinements.append(dict(kind="expression", id=row["expression_id"], before=before, after=row["type_ref"]))
    wire["functions"][0]["return_type"] = result_type
    refinements.append(dict(kind="function", id=native_function.function_id, before="any", after=result_type))
    wire["metadata"].update(source_binding_schema=SCHEMA, input_type_basis="explicit_int_annotations",
        assumptions=_ASSUMPTIONS, source_sha256=_sha(raw), **_AUTHORITY)
    refined = ProgramIR.from_dict(wire)
    bridge = SoftwareVerificationSyntaxBridge()
    roundtrip = bridge.round_trip(refined)
    _require(roundtrip.exact, "native_program_projection_not_exact")
    route = bridge.route_for("program")
    projection = dict(kind="program", family_id=route.family_id, profile_id=route.profile_id,
        native_document=refined.to_dict(), bridge=roundtrip.to_dict(), **_AUTHORITY)
    binding = dict(source_sha256=_sha(raw), native_program_id=refined.program_id,
        source_references={"source": source_ref.ref_id}, expression_references=expression_binding,
        operator_mapping={"candidate": operator, "native": native_operator}, type_refinements=refinements,
        spans=[dict(span_id=s.span_id, start_byte=s.start_byte, end_byte=s.end_byte,
            sha256=_sha(raw[s.start_byte:s.end_byte])) for s in program.spans])
    return projection, binding


def qualify_source_candidate(source_text, candidate):
    """Return a fail-open qualification report; only ``qualified`` emits a program.

    Supported input is one synchronous two-parameter function, both parameters
    annotated ``int``, returning one ``+ - * < <= > >= == !=`` operation on
    those parameters, directly or through one fresh local assignment. Optional
    return annotations must agree. Division, calls and other control flow are
    explicit frontiers. The original candidate is never changed.
    """
    report = dict(schema=SCHEMA, status="unsupported", qualified=False, source_sha256=None,
        candidate_sha256=None, checks=[], projections=[], source_binding=None,
        assumptions=list(_ASSUMPTIONS), qualification_gaps=["runtime_input_types_not_verified",
            "source_runtime_equivalence_not_proved", "security_contract_not_inferred",
            "external_proof_tools_not_run"], provider_calls=0, solver_calls=0,
        executes_source=False, **_AUTHORITY)
    try:
        _require(type(source_text) is str, "source_text_required")
        raw = source_text.encode("utf-8")
        _require(0 < len(raw) <= MAX_SOURCE_BYTES, "source_size_bound")
        report["source_sha256"] = _sha(raw)
        try:
            candidate_raw = _wire(candidate)
        except (ValueError, TypeError, RecursionError) as exc:
            raise _Rejected("inert_json_candidate_required", status="mismatch") from exc
        _require(len(candidate_raw) <= MAX_SOURCE_BYTES, "candidate_size_bound", status="mismatch")
        report["candidate_sha256"] = _sha(candidate_raw)
        guarded = _guard(source_text)
        report["checks"].append(dict(check="closed_source_ast_and_declared_types", status="passed"))
        _candidate(candidate, guarded[2], guarded[4], guarded[6])
        report["checks"].append(dict(check="learned_expression_matches_source", status="passed"))
        projection, binding = _native_context(source_text, guarded)
        report.update(status="qualified", qualified=True, projections=[projection], source_binding=binding)
        report["checks"].append(dict(check="source_bound_native_program_roundtrip", status="passed"))
    except _Rejected as exc:
        report.update(status=exc.status, reason=exc.code)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError) as exc:
        # Malformed source/candidates and a changed native contract abstain.
        # Avoid leaking arbitrary source fragments through exception messages.
        report.update(status="unsupported", reason="native_contract_or_input_error", error_type=type(exc).__name__)
    return report


def verify_source_qualification(report, source_text, candidate):
    """Replay exact source/candidate binding rather than trust a saved report."""
    expected = qualify_source_candidate(source_text, candidate)
    if _wire(report) != _wire(expected):
        raise ValueError("source qualification report does not match exact replay")
    return expected
