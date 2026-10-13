"""Bounded numerical syntax with source-bound, explicitly guarded evaluation.

ProgramIR@1 has eager expression operands. Its opaque extension nodes therefore
contain only eager operands; the required guarded regions retain conditional
branches and lazy assertion messages. Neither representation proves Python,
formatting, numerical, or runtime library semantics. Consumers must validate and
use the entire v2 document, never interpret its ProgramIR alone as complete.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import PurePosixPath

from . import numerical_source as v1
from .program import ProgramIR

PROFILE = "python-numerical-guarded-structure@2"
SCHEMA = "numerical-source-structure@2"
REGION_SCHEMA = "numerical-guarded-region@1"
AUTHORITY = dict(v1.AUTHORITY)
IF_POLICY = "test_once_then_truthiness_once_then_selected_branch"
ASSERT_POLICY = "enabled_then_test_once_then_truthiness_once_then_message_only_on_failure"
EXCEPTION_POLICY = "propagate_before_later_phase"
FORMAT_POLICY = "value_then_format_spec_then_conversion_then_format"


@dataclass(frozen=True)
class NumericalSourceResult:
    path: str
    source_sha256: str
    program: ProgramIR | None
    diagnostics: tuple[dict, ...]
    import_bindings: tuple[dict, ...]
    function_coverage: tuple[dict, ...]
    guarded_regions: tuple[dict, ...]

    @property
    def status(self):
        if self.program is None or not self.program.functions:
            return "unsupported"
        return "partial" if self.diagnostics else "translated"

    def to_dict(self):
        return json.loads(v1._wire(dict(schema=SCHEMA, profile=PROFILE,
            path=self.path, source_sha256=self.source_sha256, status=self.status,
            program=self.program.to_dict() if self.program is not None else None,
            diagnostics=list(self.diagnostics), import_bindings=list(self.import_bindings),
            function_coverage=list(self.function_coverage), guarded_regions=list(self.guarded_regions),
            guarded_extension_required=True, standalone_program_evaluation_complete=False,
            structural_completeness_scope="program_and_guarded_regions",
            source_translation_complete=self.status == "translated",
            provider_calls=0, solver_calls=0, source_executed=False, **AUTHORITY)))


class _Frontend(v1._Frontend):
    def __init__(self, *args):
        self.guarded_regions = []
        self._local, self._function_name = {}, ""
        super().__init__(*args)

    def _diagnostic(self, code, node, function=""):
        # v1 emits this before _command. v2 attempts the actual message graph
        # there and restores this diagnostic if lowering is incomplete.
        if code != "python.assert.message_expression_deferred":
            super()._diagnostic(code, node, function)

    def _span(self, node):
        key = super()._span(node)
        span = self.spans[-1]
        if span.start_byte == span.end_byte:
            # Python 3.12 inserts empty f-string components at exact byte
            # boundaries. Inclusive line-column ranges cannot express those;
            # keep the exact zero-width byte span without inventing a column.
            self.spans[-1] = replace(span, start_line=None, start_column=None,
                                    end_line=None, end_column=None)
        return key

    def _expr(self, node, local, function):
        self._local, self._function_name = local, function
        first_expression, first_region = len(self.expressions), len(self.guarded_regions)
        result = self._guarded_expr(node, local, function)
        if result is None:
            # A failed outer expression must not expose successful inner
            # branches as independently reachable/executed source operations.
            for expression in self.expressions[first_expression:]:
                self.expression_reads.pop(expression.expression_id, None)
            del self.expressions[first_expression:]
            del self.guarded_regions[first_region:]
        return result

    def _region(self, kind, item, **fields):
        return dict(schema=REGION_SCHEMA, region_id=self._id("guarded-region"),
            kind=kind, function_id="", source_ref_ids=list(item.source_ref_ids),
            span_ids=list(item.span_ids), exceptions_policy=EXCEPTION_POLICY, **fields)

    def _guarded_expr(self, node, local, function):
        if isinstance(node, ast.IfExp):
            test = self._expr(node.test, local, function)
            then = self._expr(node.body, local, function)
            otherwise = self._expr(node.orelse, local, function)
            if None in (test, then, otherwise):
                return None
            root = self._expression(node, "call", operands=(test,), operator="python.if_expression",
                attributes=dict(call_kind="python.guarded_if", opaque=True,
                    eager_operands_only=True, truthiness_semantics_verified=False,
                    read_scope="may_read_across_guarded_alternatives"))
            region = self._region("if_expression", self.expressions[-1],
                root_expression_id=root, test_expression_id=test,
                then_expression_id=then, else_expression_id=otherwise,
                evaluation_policy=IF_POLICY, truthiness_semantics_verified=False)
            self.expressions[-1] = replace(self.expressions[-1], attributes={
                **self.expressions[-1].attributes.to_dict(), "guarded_region_id": region["region_id"]})
            self.expression_reads[root] |= self.expression_reads[then] | self.expression_reads[otherwise]
            self.guarded_regions.append(region)
            return root
        if isinstance(node, ast.FormattedValue):
            if node.conversion not in (-1, ord("s"), ord("r"), ord("a")):
                self._diagnostic("python.format.unsupported_conversion", node, function)
                return None
            value = self._expr(node.value, local, function)
            spec = self._expr(node.format_spec, local, function) if node.format_spec is not None else None
            if value is None or (node.format_spec is not None and spec is None):
                return None
            return self._expression(node, "call", operands=(value, spec) if spec else (value,),
                operator="python.format_value", type_ref="python.str",
                attributes=dict(call_kind="python.format_value", opaque=True,
                    conversion=node.conversion, has_format_spec=spec is not None,
                    evaluation_policy=FORMAT_POLICY, exceptions_policy=EXCEPTION_POLICY,
                    format_semantics_verified=False, span_interpretation="python_ast_node_span"))
        if isinstance(node, ast.JoinedStr):
            parts = [self._expr(part, local, function) for part in node.values]
            if any(part is None for part in parts):
                return None
            return self._expression(node, "call", operands=parts, operator="python.joined_string",
                type_ref="python.str", attributes=dict(call_kind="python.joined_string", opaque=True,
                    evaluation_policy="lexical_components_left_to_right",
                    exceptions_policy=EXCEPTION_POLICY, format_semantics_verified=False,
                    span_interpretation="python_ast_node_span"))
        return super()._expr(node, local, function)

    def _command(self, node, kind, *, expressions=(), targets=(), attributes=None):
        attrs = dict(attributes or {})
        attrs["read_scope"] = "may_read_including_guarded_regions"
        message = None
        is_assert = isinstance(node, ast.Assert) and kind == "assert" and len(expressions) == 1
        if isinstance(node, ast.Assert) and node.msg is not None:
            if is_assert:
                message = self._expr(node.msg, self._local, self._function_name)
            if message is None:
                super()._diagnostic("python.assert.message_expression_deferred", node.msg, self._function_name)
            attrs["assertion_message_structure_lowered"] = message is not None
        key = super()._command(node, kind, expressions=expressions, targets=targets, attributes=attrs)
        if is_assert:
            command = self.commands[-1]
            region = self._region("assert_statement", command, command_id=key,
                predicate_expression_id=expressions[0], message_expression_id=message,
                message_status="absent" if node.msg is None else "lowered" if message else "unsupported",
                predicate_guard="assertions_enabled",
                message_guard="assertions_enabled_and_predicate_false", evaluation_policy=ASSERT_POLICY)
            attrs = command.attributes.to_dict()
            attrs.update(guarded_region_id=region["region_id"], assertion_message_expression_id=message)
            reads = set(command.effects.reads) | (self.expression_reads[message] if message else set())
            self.commands[-1] = replace(command, attributes=attrs,
                effects=replace(command.effects, reads=tuple(sorted(reads))))
            self.guarded_regions.append(region)
        return key

    def _function(self, node):
        first = len(self.guarded_regions)
        self._function_name = node.name
        super()._function(node)
        for region in self.guarded_regions[first:]:
            region["function_id"] = self.functions[-1].function_id

    def lower(self):
        program = super().lower()
        if program is None:
            return None
        expressions = {e.expression_id: e for e in program.expressions}
        conditional = {r["root_expression_id"]: r for r in self.guarded_regions if r["kind"] == "if_expression"}
        assertions = {r["command_id"]: r for r in self.guarded_regions if r["kind"] == "assert_statement"}
        reachable, pending = set(), [e for c in program.commands for e in c.expression_ids]
        pending.extend(r["message_expression_id"] for r in assertions.values() if r["message_expression_id"])
        while pending:
            key = pending.pop()
            if key in reachable:
                continue
            reachable.add(key)
            pending.extend(expressions[key].operand_ids)
            if key in conditional:
                pending.extend(conditional[key][field] for field in ("then_expression_id", "else_expression_id"))
        self.guarded_regions = [r for r in self.guarded_regions
            if r["kind"] == "assert_statement" or r["root_expression_id"] in reachable]
        program = replace(program, program_id="",
            expressions=tuple(e for e in program.expressions if e.expression_id in reachable),
            metadata={**program.metadata.to_dict(), "profile": PROFILE,
                "guarded_extension_required": True, "standalone_program_evaluation_complete": False,
                "read_scope": "may_read_including_guarded_regions"})
        validate_guarded_structure(program, self.guarded_regions)
        return program


def validate_guarded_structure(program, guarded_regions):
    """Validate closure/ownership; source correspondence additionally needs replay.

    All side roots must be reachable from an owning command, within the exact
    source/function span and symbol scope. Effects are conservative MAY-read
    unions, not assertions that any conditional operation actually executes.
    """
    if not isinstance(program, ProgramIR) or type(guarded_regions) not in (list, tuple):
        raise ValueError("guarded structure requires ProgramIR and region rows")
    if (program.metadata.get("profile") != PROFILE
            or program.metadata.get("guarded_extension_required") is not True
            or program.metadata.get("standalone_program_evaluation_complete") is not False):
        raise ValueError("guarded extension metadata required")
    expressions = {e.expression_id: e for e in program.expressions}
    commands = {c.command_id: c for c in program.commands}
    functions = {f.function_id: f for f in program.functions}
    spans = {s.span_id: s for s in program.spans}
    conditionals, assertions, seen_ids = {}, {}, set()

    def contained(inner, outer):
        return (set(inner.source_ref_ids) <= set(outer.source_ref_ids) and bool(inner.span_ids)
            and all(any(spans[parent].source_ref_id == spans[child].source_ref_id
                        and spans[parent].start_byte <= spans[child].start_byte
                        and spans[child].end_byte <= spans[parent].end_byte
                        for parent in outer.span_ids) for child in inner.span_ids))

    common = {"schema", "region_id", "kind", "function_id", "source_ref_ids", "span_ids", "exceptions_policy", "evaluation_policy"}
    for region in guarded_regions:
        if not isinstance(region, dict):
            raise ValueError("guarded region must be an object")
        kind = region.get("kind")
        extra = ({"root_expression_id", "test_expression_id", "then_expression_id", "else_expression_id", "truthiness_semantics_verified"}
            if kind == "if_expression" else {"command_id", "predicate_expression_id", "message_expression_id", "message_status", "predicate_guard", "message_guard"}
            if kind == "assert_statement" else set())
        if not extra or set(region) != common | extra:
            raise ValueError("unknown guarded region shape")
        id_fields = ("region_id", "function_id", "root_expression_id", "test_expression_id", "then_expression_id", "else_expression_id") if kind == "if_expression" else ("region_id", "function_id", "command_id", "predicate_expression_id")
        if any(type(region[field]) is not str or not region[field] for field in id_fields):
            raise ValueError("guarded region IDs must be nonempty strings")
        if kind == "assert_statement" and region["message_expression_id"] is not None and type(region["message_expression_id"]) is not str:
            raise ValueError("guarded message ID must be a string or null")
        rid = region["region_id"]
        if not isinstance(rid, str) or not rid or rid in seen_ids:
            raise ValueError("duplicate or invalid guarded region identity")
        seen_ids.add(rid)
        if (region["schema"] != REGION_SCHEMA or region["function_id"] not in functions
                or region["exceptions_policy"] != EXCEPTION_POLICY):
            raise ValueError("invalid guarded region contract")
        if kind == "if_expression":
            root = expressions.get(region["root_expression_id"])
            if (root is None or root.attributes.get("call_kind") != "python.guarded_if"
                    or root.operator != "python.if_expression" or root.attributes.get("guarded_region_id") != rid
                    or tuple(root.operand_ids) != (region["test_expression_id"],)
                    or region["evaluation_policy"] != IF_POLICY or region["truthiness_semantics_verified"] is not False
                    or root.expression_id in conditionals):
                raise ValueError("invalid conditional eager operands or policy")
            if any(region[field] not in expressions for field in ("test_expression_id", "then_expression_id", "else_expression_id")):
                raise ValueError("dangling guarded expression")
            if not all(contained(expressions[region[field]], root) for field in ("test_expression_id", "then_expression_id", "else_expression_id")):
                raise ValueError("conditional child escapes guarded source span")
            conditionals[root.expression_id] = region
        else:
            root = commands.get(region["command_id"])
            status, message = region["message_status"], region["message_expression_id"]
            if (root is None or root.kind.value != "assert" or tuple(root.expression_ids) != (region["predicate_expression_id"],)
                    or root.attributes.get("guarded_region_id") != rid
                    or root.attributes.get("assertion_message_expression_id") != message
                    or region["evaluation_policy"] != ASSERT_POLICY
                    or region["predicate_guard"] != "assertions_enabled"
                    or region["message_guard"] != "assertions_enabled_and_predicate_false"
                    or status not in ("absent", "lowered", "unsupported")
                    or (status == "lowered" and message not in expressions)
                    or (status != "lowered" and message is not None)
                    or root.command_id in assertions):
                raise ValueError("invalid guarded assertion contract")
            if not contained(expressions[region["predicate_expression_id"]], root) or (message and not contained(expressions[message], root)):
                raise ValueError("assertion child escapes guarded source span")
            assertions[root.command_id] = region
        if region["source_ref_ids"] != list(root.source_ref_ids) or region["span_ids"] != list(root.span_ids):
            raise ValueError("guarded region source binding differs from root")

    visited_regions, owners = set(), {}
    for function in program.functions:
        allowed = set(program.global_symbol_ids) | set(function.parameter_symbol_ids) | set(function.local_symbol_ids)
        allowed |= set(function.exception_symbol_ids) | {function.result_symbol_id}
        function_spans = [spans[s] for s in function.span_ids]
        memo, visiting = {}, set()

        def visit(key):
            if key in visiting:
                raise ValueError("cycle in guarded expression graph")
            if key in memo:
                return memo[key]
            if key not in expressions:
                raise ValueError("dangling guarded expression")
            item = expressions[key]
            if owners.setdefault(key, function.function_id) != function.function_id:
                raise ValueError("cross-function guarded expression")
            if (not set(item.symbol_ids) <= allowed or not item.span_ids
                    or not set(item.source_ref_ids) <= set(function.source_ref_ids)):
                raise ValueError("guarded expression escapes function scope")
            for span_id in item.span_ids:
                span = spans[span_id]
                if not any(s.source_ref_id == span.source_ref_id and s.start_byte <= span.start_byte
                           and span.end_byte <= s.end_byte for s in function_spans):
                    raise ValueError("guarded expression escapes function source span")
            visiting.add(key)
            children = list(item.operand_ids)
            if item.attributes.get("call_kind") == "python.guarded_if":
                region = conditionals.get(key)
                if region is None or region["function_id"] != function.function_id:
                    raise ValueError("missing or foreign conditional region")
                visited_regions.add(region["region_id"])
                children.extend(region[field] for field in ("then_expression_id", "else_expression_id"))
            reads = set(item.symbol_ids)
            for child in children:
                reads |= visit(child)
            visiting.remove(key)
            memo[key] = reads
            return reads

        function_reads = set()
        for block in function.cfg.blocks:
            for command_id in block.command_ids:
                command = commands[command_id]
                roots = list(command.expression_ids)
                if command.kind.value == "assert":
                    region = assertions.get(command_id)
                    if region is None or region["function_id"] != function.function_id:
                        raise ValueError("missing or foreign assertion region")
                    visited_regions.add(region["region_id"])
                    if region["message_expression_id"]:
                        roots.append(region["message_expression_id"])
                reads = set().union(*(visit(key) for key in roots))
                if reads != set(command.effects.reads):
                    raise ValueError("command MAY-read effects omit guarded sources")
                function_reads |= reads
        if function_reads != set(function.effects.reads):
            raise ValueError("function MAY-read effects differ from guarded closure")
    if visited_regions != seen_ids or set(owners) != set(expressions):
        raise ValueError("unreachable guarded region or expression")
    return True


def adapt_numerical_source(source_text, *, path="source.py"):
    """Lower bounded Python syntax without source, model, or solver execution."""
    if type(source_text) is not str or type(path) is not str:
        raise ValueError("source text and path must be strings")
    relative = PurePosixPath(path)
    if (not path or relative.is_absolute() or "\\" in path or "\x00" in path
            or any(part in ("", ".", "..") for part in path.split("/"))):
        raise ValueError("canonical relative Python source path required")
    try:
        raw = source_text.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError("valid UTF-8 source required") from exc
    if not 0 < len(raw) <= v1.MAX_SOURCE_BYTES:
        raise ValueError("numerical source byte bound exceeded")
    digest = hashlib.sha256(raw).hexdigest()
    try:
        tree = ast.parse(source_text, type_comments=True)
    except (SyntaxError, ValueError, RecursionError):
        return NumericalSourceResult(path, digest, None,
            (dict(code="python.syntax", function="", source_ref_ids=[], span_ids=[]),), (), (), ())
    pending, count, functions = [(tree, 0)], 0, 0
    while pending:
        node, depth = pending.pop()
        count += 1
        functions += isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        if count > v1.MAX_AST_NODES or depth > v1.MAX_AST_DEPTH or functions > v1.MAX_FUNCTIONS:
            raise ValueError("numerical source AST resource bound exceeded")
        pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    frontend = _Frontend(source_text, path, tree)
    program = frontend.lower()
    return NumericalSourceResult(path, digest, program, tuple(frontend.diagnostics),
        tuple(frontend.import_bindings), tuple(frontend.function_coverage), tuple(frontend.guarded_regions))


def verify_numerical_source(result, source_text, *, path="source.py"):
    """Validate archived guarded claims by exact original-source replay."""
    actual = result.to_dict() if isinstance(result, NumericalSourceResult) else result
    expected = adapt_numerical_source(source_text, path=path)
    if v1._wire(actual) != v1._wire(expected.to_dict()):
        raise ValueError("numerical guarded source structure differs from exact replay")
    return expected


__all__ = ["PROFILE", "SCHEMA", "NumericalSourceResult", "adapt_numerical_source",
           "verify_numerical_source", "validate_guarded_structure"]
