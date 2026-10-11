"""Opt-in, source-bound Python numerical *structure*, without numerical proofs.

This frontend preserves tuples, qualified calls, indexing and slices that the
reviewed scalar Source384 profile cannot express. Python/NumPy operations stay
uninterpreted: annotations and import spellings do not prove runtime types or
library identity. Unsupported control flow remains a diagnostic fence, never a
linearized loop. No source, model, provider, or solver is executed.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import PurePosixPath

from .program import (
    BasicBlock, ControlFlowGraph, EffectSummary, ProgramCommand,
    ProgramExpression, ProgramFunction, ProgramIR, ProgramSymbol, Purity,
)
from .source_adapters import (
    _ast_byte_span, _line_byte_offsets, _make_span, _mapped, _source_ref,
)

PROFILE = "python-numerical-structure@1"
SCHEMA = "numerical-source-structure@1"
MAX_SOURCE_BYTES = 65_536
MAX_AST_NODES = 4096
MAX_AST_DEPTH = 48
MAX_FUNCTIONS = 32
AUTHORITY = dict(proof_authority=False, execution_authority=False,
    completion_authority=False, source_semantics_verified=False,
    numerical_semantics_verified=False, learned_inference_performed=False)


def _wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


@dataclass(frozen=True)
class NumericalSourceResult:
    """Structural result. Replay original source before using archived claims."""

    path: str
    source_sha256: str
    program: ProgramIR | None
    diagnostics: tuple[dict, ...]
    import_bindings: tuple[dict, ...]
    function_coverage: tuple[dict, ...]

    @property
    def status(self):
        if self.program is None or not self.program.functions:
            return "unsupported"
        return "partial" if self.diagnostics else "translated"

    def to_dict(self):
        # A detached wire form cannot mutate the result's nested metadata.
        return json.loads(_wire(dict(schema=SCHEMA, profile=PROFILE,
            path=self.path, source_sha256=self.source_sha256, status=self.status,
            program=self.program.to_dict() if self.program is not None else None,
            diagnostics=list(self.diagnostics), import_bindings=list(self.import_bindings),
            function_coverage=list(self.function_coverage),
            source_translation_complete=self.status == "translated",
            provider_calls=0, solver_calls=0, source_executed=False, **AUTHORITY)))


class _Frontend:
    def __init__(self, source, path, tree):
        self.source, self.raw, self.tree = source, source.encode("utf-8"), tree
        self.source_ref = _source_ref(path=path, source=source, language="python")
        self.offsets = _line_byte_offsets(source)
        self.spans, self.symbols, self.expressions, self.commands, self.functions = [], [], [], [], []
        self.diagnostics, self.import_bindings, self.function_coverage = [], [], []
        self.globals, self.aliases, self.expression_reads = {}, {}, {}
        self.mutated_import_roots = set()
        self.counter = 0
        self._module_bindings()

    def _id(self, kind):
        self.counter += 1
        return f"{kind}:{self.counter}"

    def _span(self, node):
        start, end, sl, sc, el, ec = _ast_byte_span(node, source=self.source, offsets=self.offsets)
        span = _make_span(span_id=self._id("span"), source_ref_id=self.source_ref.ref_id,
            start_byte=start, end_byte=end, start_line=sl, start_column=sc,
            end_line=el, end_column=ec)
        self.spans.append(span)
        return span.span_id

    def _text(self, node):
        start, end, *_ = _ast_byte_span(node, source=self.source, offsets=self.offsets)
        return self.raw[start:end].decode("utf-8")

    def _mapped(self, span):
        return _mapped(self.source_ref.ref_id, span)

    def _diagnostic(self, code, node, function=""):
        self.diagnostics.append(dict(code=code, function=function,
            source_ref_ids=[self.source_ref.ref_id], span_ids=[self._span(node)]))

    def _module_bindings(self):
        rebound = set()
        wildcard_import = False
        for node in self.tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom) and (node.level or any(a.name == "*" for a in node.names)):
                    self._diagnostic("python.import.relative_or_star", node)
                    rebound.update(alias.asname or alias.name for alias in node.names)
                    wildcard_import |= any(alias.name == "*" for alias in node.names)
                    continue
                for alias in node.names:
                    if isinstance(node, ast.Import):
                        local = alias.asname or alias.name.split(".")[0]
                        qualified = alias.name if alias.asname else alias.name.split(".")[0]
                    else:
                        local = alias.asname or alias.name
                        qualified = (node.module + "." if node.module else "") + alias.name
                    if local in self.aliases:
                        rebound.add(local)
                    self.aliases[local] = qualified
                    self.import_bindings.append(dict(local_name=local, imported_name=qualified,
                        source_ref_ids=[self.source_ref.ref_id], span_ids=[self._span(node)],
                        runtime_identity_verified=False))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                rebound.add(node.name)
            else:
                for child in ast.walk(node):
                    if isinstance(child, (ast.Import, ast.ImportFrom)):
                        rebound.update(alias.asname or (alias.name.split(".")[0]
                            if isinstance(child, ast.Import) else alias.name) for alias in child.names)
                        wildcard_import |= any(alias.name == "*" for alias in child.names)
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        rebound.add(child.name)
                    if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
                        rebound.add(child.id)
                    if isinstance(child, ast.Attribute) and isinstance(child.ctx, (ast.Store, ast.Del)):
                        value = child.value
                        while isinstance(value, ast.Attribute):
                            value = value.value
                        if isinstance(value, ast.Name):
                            rebound.add(value.id)
        if wildcard_import:
            rebound.update(self.aliases)
        for name in rebound:
            self.aliases.pop(name, None)
        for row in self.import_bindings:
            row["statically_unshadowed"] = row["local_name"] in self.aliases

    def _symbol(self, name, kind, span, *, annotation=None):
        key = self._id("symbol")
        attributes = dict(structural_only=True, runtime_type_verified=False)
        if annotation is not None:
            attributes["declared_annotation"] = self._text(annotation)
            attributes["annotation_span_ids"] = [self._span(annotation)]
        self.symbols.append(ProgramSymbol(key, name, "python.object", kind,
            attributes=attributes, **self._mapped(span)))
        return key

    def _expression(self, node, kind, *, operands=(), symbols=(), operator="",
                    attributes=None, type_ref="python.object"):
        key = self._id("expr")
        self.expressions.append(ProgramExpression(key, kind, type_ref,
            operand_ids=tuple(operands), evaluation_order=tuple(operands),
            symbol_ids=tuple(symbols), operator=operator,
            attributes={"structural_only": True, **(attributes or {})},
            **self._mapped(self._span(node))))
        self.expression_reads[key] = set(symbols).union(
            *(self.expression_reads[child] for child in operands))
        return key

    def _qualified(self, node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            prefix = self._qualified(node.value)
            return prefix + "." + node.attr if prefix is not None else None
        return None

    def _expr(self, node, local, function):
        if isinstance(node, ast.Constant):
            value = node.value
            if type(value) not in (str, int, float, bool, type(None)) or (
                    type(value) is float and not math.isfinite(value)):
                self._diagnostic("python.literal.unsupported", node, function)
                return None
            # The shared logic bridge accepts lossless integer/string atoms,
            # not JSON floats. Hex spelling preserves the exact Python binary
            # float without pretending it is a formal real number.
            literal = ({"value_hex": value.hex(), "source_spelling": self._text(node),
                        "literal_encoding": "python.float.hex"} if type(value) is float
                       else {"value": value})
            return self._expression(node, "literal", attributes=literal,
                                    type_ref="python.literal." + type(value).__name__)
        if isinstance(node, ast.Name):
            symbol = local.get(node.id)
            if symbol is None:
                symbol = self.globals.get(node.id)
                if symbol is None:
                    symbol = self._symbol(node.id, "global", self._span(node))
                    self.globals[node.id] = symbol
            return self._expression(node, "symbol", symbols=(symbol,))
        if isinstance(node, ast.Attribute):
            base = self._expr(node.value, local, function)
            if base is not None:
                return self._expression(node, "field", operands=(base,), operator=node.attr,
                    attributes={"opaque": True, "attribute_name": node.attr})
            return None
        if isinstance(node, (ast.Tuple, ast.List)):
            values = [self._expr(child, local, function) for child in node.elts]
            if any(value is None for value in values):
                return None
            constructor = "python.tuple" if isinstance(node, ast.Tuple) else "python.list"
            return self._expression(node, "call", operands=values, operator=constructor,
                type_ref=constructor, attributes={"call_kind": constructor,
                                                 "opaque": True, "element_count": len(values)})
        if isinstance(node, ast.Slice):
            values, present = [], []
            for label, child in (("lower", node.lower), ("upper", node.upper), ("step", node.step)):
                present.append(child is not None)
                # Missing bounds are explicit structural None literals sharing
                # the exact slice span, not invented source coordinates.
                value = (self._expr(child, local, function) if child is not None else
                    self._expression(node, "literal", attributes={"value": None,
                        "synthetic_missing_slice_bound": label}, type_ref="python.literal.NoneType"))
                values.append(value)
            if any(value is None for value in values):
                return None
            return self._expression(node, "call", operands=values, operator="python.slice",
                type_ref="python.slice", attributes={"call_kind": "python.slice", "opaque": True,
                                                     "explicit_bounds": present})
        if isinstance(node, ast.Subscript):
            base = self._expr(node.value, local, function)
            index = self._expr(node.slice, local, function)
            if base is not None and index is not None:
                return self._expression(node, "index", operands=(base, index), operator="python.getitem",
                                        attributes={"opaque": True})
            return None
        if isinstance(node, ast.Call):
            if (any(isinstance(child, ast.Starred) for child in node.args)
                    or any(keyword.arg is None for keyword in node.keywords)
                    or len({keyword.arg for keyword in node.keywords}) != len(node.keywords)):
                self._diagnostic("python.call.argument_expansion_or_duplicate_keyword", node, function)
                return None
            # Callee lookup precedes positional and then keyword evaluation.
            callee = self._expr(node.func, local, function)
            args = [self._expr(arg, local, function) for arg in node.args]
            keywords = [self._expr(row.value, local, function) for row in node.keywords]
            operands = [callee, *args, *keywords]
            if any(value is None for value in operands):
                return None
            qualified = self._qualified(node.func)
            imported = None
            resolution = "dynamic_receiver" if qualified is None else "unresolved_or_shadowed"
            if qualified is not None:
                root, *tail = qualified.split(".")
                if root in self.aliases and root not in local and root not in self.mutated_import_roots:
                    imported = ".".join((self.aliases[root], *tail))
                    resolution = "declared_import"
            return self._expression(node, "call", operands=operands,
                operator=qualified or "python.dynamic_call", attributes={"opaque": True,
                    "call_kind": "python.call", "positional_count": len(args),
                    "keyword_names": [row.arg for row in node.keywords],
                    "qualified_callee": qualified, "imported_callee": imported,
                    "callee_resolution": resolution, "runtime_identity_verified": False})
        binary = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.MatMult: "matmul",
                  ast.Div: "div", ast.FloorDiv: "floordiv", ast.Mod: "mod", ast.Pow: "pow"}
        if isinstance(node, ast.BinOp) and type(node.op) in binary:
            values = [self._expr(node.left, local, function), self._expr(node.right, local, function)]
            if all(value is not None for value in values):
                return self._expression(node, "binary", operands=values, operator=binary[type(node.op)],
                                        attributes={"opaque": True})
            return None
        unary = {ast.Not: "not", ast.USub: "neg", ast.UAdd: "pos", ast.Invert: "invert"}
        if isinstance(node, ast.UnaryOp) and type(node.op) in unary:
            value = self._expr(node.operand, local, function)
            if value is not None:
                return self._expression(node, "unary", operands=(value,), operator=unary[type(node.op)],
                                        attributes={"opaque": True})
            return None
        compare = {ast.Eq: "eq", ast.NotEq: "ne", ast.Lt: "lt", ast.LtE: "le", ast.Gt: "gt", ast.GtE: "ge"}
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in compare:
            values = [self._expr(node.left, local, function), self._expr(node.comparators[0], local, function)]
            if all(value is not None for value in values):
                return self._expression(node, "binary", operands=values, operator=compare[type(node.ops[0])],
                                        attributes={"opaque": True})
            return None
        self._diagnostic("python.expr." + type(node).__name__, node, function)
        return None

    def _pattern(self, node, local):
        if isinstance(node, ast.Name):
            return dict(kind="name", symbol_id=local[node.id], span_ids=[self._span(node)])
        if isinstance(node, (ast.Tuple, ast.List)):
            children = [self._pattern(child, local) for child in node.elts]
            if all(child is not None for child in children):
                return dict(kind="tuple" if isinstance(node, ast.Tuple) else "list", elements=children,
                            span_ids=[self._span(node)])
        return None

    @staticmethod
    def _pattern_ids(pattern):
        if pattern["kind"] == "name":
            return [pattern["symbol_id"]]
        return [key for child in pattern["elements"] for key in _Frontend._pattern_ids(child)]

    def _command(self, node, kind, *, expressions=(), targets=(), attributes=None):
        key = self._id("command")
        reads = set().union(*(self.expression_reads[e] for e in expressions))
        self.commands.append(ProgramCommand(key, kind, expression_ids=tuple(expressions),
            evaluation_order=tuple(expressions), target_symbol_ids=tuple(sorted(set(targets))),
            effects=EffectSummary(reads=tuple(sorted(reads)), writes=tuple(sorted(set(targets))),
                raises=("BaseException",), performs_io=True, nondeterministic=True, synchronizes=True),
            attributes={"structural_only": True, "external_effects_known": False, **(attributes or {})},
            **self._mapped(self._span(node))))
        return key

    def _function(self, node):
        first_diagnostic = len(self.diagnostics)
        self.mutated_import_roots = set()
        name, function_id, span = node.name, self._id("function"), self._span(node)
        local, parameters = {}, []
        args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        if node.args.vararg is not None:
            args.append(node.args.vararg)
        if node.args.kwarg is not None:
            args.append(node.args.kwarg)
        for arg in args:
            key = self._symbol(arg.arg, "parameter", self._span(arg), annotation=arg.annotation)
            local[arg.arg] = key
            parameters.append(key)
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute) and isinstance(child.ctx, (ast.Store, ast.Del)):
                value = child.value
                while isinstance(value, ast.Attribute):
                    value = value.value
                if isinstance(value, ast.Name):
                    self.mutated_import_roots.add(value.id)
            bound_names = []
            if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
                bound_names.append(child.id)
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                bound_names.extend(alias.asname or (alias.name.split(".")[0]
                    if isinstance(child, ast.Import) else alias.name) for alias in child.names)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and child is not node:
                bound_names.append(child.name)
            elif isinstance(child, ast.ExceptHandler) and child.name:
                bound_names.append(child.name)
            for bound in bound_names:
                if bound not in local:
                    local[bound] = self._symbol(bound, "local", self._span(child))
        if (node.decorator_list or node.args.defaults or any(v is not None for v in node.args.kw_defaults)
                or node.args.vararg or node.args.kwarg or getattr(node, "type_params", ())):
            self._diagnostic("python.function.definition_evaluation_or_variadics", node, name)
        # A global/nonlocal mutation can invalidate every apparent import path.
        if any(isinstance(child, (ast.Global, ast.Nonlocal)) for child in ast.walk(node)):
            self._diagnostic("python.function.global_or_nonlocal", node, name)
            for alias in self.aliases:
                if alias not in local:
                    local[alias] = self._symbol(alias, "local", span)
        result = self._symbol("result", "result", span, annotation=node.returns)
        commands, returned = [], False
        for position, statement in enumerate(node.body):
            if returned:
                self._diagnostic("python.stmt.after_return", statement, name)
                continue
            attributes = {}
            expressions, targets, kind = [], [], "skip"
            if (position == 0 and isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Constant) and type(statement.value.value) is str):
                attributes["docstring"] = statement.value.value
            elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
                target_nodes = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                patterns = [self._pattern(target, local) for target in target_nodes]
                value = self._expr(statement.value, local, name) if statement.value is not None else None
                if len(patterns) != 1 or patterns[0] is None or value is None:
                    self._diagnostic("python.assignment.unsupported_target_or_value", statement, name)
                    attributes["unsupported_construct"] = type(statement).__name__
                else:
                    kind, expressions = "assign", [value]
                    targets = self._pattern_ids(patterns[0])
                    attributes["assignment_pattern"] = patterns[0]
                    if isinstance(statement, ast.AnnAssign):
                        attributes["declared_annotation"] = self._text(statement.annotation)
            elif isinstance(statement, ast.Return):
                value = self._expr(statement.value, local, name) if statement.value is not None else None
                if statement.value is not None and value is None:
                    attributes["unsupported_construct"] = "Return.value"
                else:
                    kind, expressions = "return", [value] if value is not None else []
                returned = True
            elif isinstance(statement, ast.Assert):
                value = self._expr(statement.test, local, name)
                if value is not None:
                    kind, expressions = "assert", [value]
                if statement.msg is not None:
                    attributes.update(assertion_message_source=self._text(statement.msg),
                        assertion_message_span_ids=[self._span(statement.msg)], message_evaluated_only_on_failure=True)
                    if not isinstance(statement.msg, ast.Constant):
                        self._diagnostic("python.assert.message_expression_deferred", statement.msg, name)
                        attributes["assertion_message_structure_lowered"] = False
                attributes["assertion_semantics_verified"] = False
            elif isinstance(statement, ast.Expr):
                value = self._expr(statement.value, local, name)
                if value is not None:
                    expressions = [value]
                    kind = "call" if isinstance(statement.value, ast.Call) else "skip"
            elif not isinstance(statement, ast.Pass):
                code = "python.stmt." + type(statement).__name__
                self._diagnostic(code, statement, name)
                attributes.update(unsupported_construct=code, body_not_linearized=True)
            commands.append(self._command(statement, kind, expressions=expressions,
                                          targets=targets, attributes=attributes))
        block = self._id("block")
        cfg = ControlFlowGraph(self._id("cfg"), block,
            (BasicBlock(block, tuple(commands), **self._mapped(span)),), (), (block,))
        relevant = [row for row in self.commands if row.command_id in commands]
        effects = EffectSummary(reads=tuple(sorted({v for c in relevant for v in c.effects.reads})),
            writes=tuple(sorted({v for c in relevant for v in c.effects.writes})),
            raises=("BaseException",), performs_io=True, nondeterministic=True, synchronizes=True)
        self.functions.append(ProgramFunction(function_id, name, cfg,
            parameter_symbol_ids=tuple(parameters),
            local_symbol_ids=tuple(key for key in local.values() if key not in parameters),
            result_symbol_id=result, return_type="python.object", purity=Purity.UNKNOWN,
            effects=effects, declared_exceptions=("BaseException",), **self._mapped(span)))
        self.function_coverage.append(dict(function_id=function_id, name=name,
            source_ref_ids=[self.source_ref.ref_id], span_ids=[span],
            structurally_complete=len(self.diagnostics) == first_diagnostic,
            unsupported_constructs=sorted({row["code"] for row in self.diagnostics[first_diagnostic:]})))

    def lower(self):
        for node in self.tree.body:
            if isinstance(node, ast.FunctionDef):
                self._function(node)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and type(node.value.value) is str:
                continue
            else:
                self._diagnostic("python.module." + type(node).__name__, node)
        if not self.functions:
            self.diagnostics.append(dict(code="python.module.no_sync_function", function="",
                source_ref_ids=[self.source_ref.ref_id], span_ids=[]))
            return None
        return ProgramIR(sources=(self.source_ref,), spans=tuple(self.spans), symbols=tuple(self.symbols),
            expressions=tuple(self.expressions), commands=tuple(self.commands), functions=tuple(self.functions),
            global_symbol_ids=tuple(self.globals.values()), metadata=dict(profile=PROFILE,
                structural_only=True, scalar_source384_profile_widened=False,
                cfg_interpretation="source_order_with_explicit_uninterpreted_control_fences",
                annotations_are_declared_syntax=True, external_effects_known=False,
                import_resolution="syntactic_binding_only_not_runtime_identity", **AUTHORITY))


def adapt_numerical_source(source_text, *, path="source.py"):
    """Translate bounded source into opt-in structural ProgramIR, never run it."""
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
    if not 0 < len(raw) <= MAX_SOURCE_BYTES:
        raise ValueError("numerical source byte bound exceeded")
    digest = hashlib.sha256(raw).hexdigest()
    try:
        tree = ast.parse(source_text, type_comments=True)
    except (SyntaxError, ValueError, RecursionError):
        return NumericalSourceResult(path, digest, None,
            (dict(code="python.syntax", function="", source_ref_ids=[], span_ids=[]),), (), ())
    pending, count, functions = [(tree, 0)], 0, 0
    while pending:
        node, depth = pending.pop()
        count += 1
        functions += isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        if count > MAX_AST_NODES or depth > MAX_AST_DEPTH or functions > MAX_FUNCTIONS:
            raise ValueError("numerical source AST resource bound exceeded")
        pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    frontend = _Frontend(source_text, path, tree)
    program = frontend.lower()
    return NumericalSourceResult(path, digest, program, tuple(frontend.diagnostics),
                                 tuple(frontend.import_bindings), tuple(frontend.function_coverage))


def verify_numerical_source(result, source_text, *, path="source.py"):
    """Replay exact original bytes; serialized structure is not trusted evidence."""
    actual = result.to_dict() if isinstance(result, NumericalSourceResult) else result
    expected = adapt_numerical_source(source_text, path=path)
    if _wire(actual) != _wire(expected.to_dict()):
        raise ValueError("numerical source structure differs from exact replay")
    return expected


__all__ = ["PROFILE", "SCHEMA", "NumericalSourceResult", "adapt_numerical_source", "verify_numerical_source"]
