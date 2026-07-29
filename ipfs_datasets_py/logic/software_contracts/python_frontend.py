"""Versioned, non-executing Python frontend for the shared AST IR.

The frontend uses only :mod:`ast`; it never imports, evaluates, compiles to
bytecode, or otherwise executes analyzed source.  It emits lexical parsing
facts into the language-neutral records owned by :mod:`.ast_ir`.  References
and calls deliberately remain unresolved.  A later resolver may join those
records, but this module does not attach target or confidence claims.

Malformed input, unsupported encodings and resource exhaustion are represented
as deterministic diagnostics and ``UnsupportedConstruct`` records in a valid
``ASTRecord``.  They are not converted into an apparently successful parse.
"""

from __future__ import annotations

import ast
import builtins
import sys
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Final, Iterable, Sequence

from ipfs_datasets_py.logic.software_contracts.ast_ir import (
    ASTRecord,
    CallRecord,
    DiagnosticRecord,
    EffectRecord,
    FrontendCapability,
    ImportDefinition,
    ModuleDefinition,
    ParameterDefinition,
    ReferenceRecord,
    ScopeDefinition,
    SignatureDefinition,
    SourceProvenance,
    SourceSpan,
    SymbolDefinition,
    UnsupportedConstruct,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)


PYTHON_FRONTEND_VERSION: Final[str] = "1.2.0"
PYTHON_FRONTEND_NAME: Final[str] = "cpython-ast"
PYTHON_SOURCE_EXTENSIONS: Final[tuple[str, ...]] = (".py", ".pyi")
DEFAULT_MAX_SOURCE_BYTES: Final[int] = 8 * 1024 * 1024
DEFAULT_MAX_AST_NODES: Final[int] = 5_000_000
_BUILTIN_NAMES: Final[frozenset[str]] = frozenset(dir(builtins))
_DYNAMIC_CALLS: Final[frozenset[str]] = frozenset(
    {
        "__import__",
        "compile",
        "eval",
        "exec",
        "importlib.import_module",
        "runpy.run_module",
        "runpy.run_path",
    }
)


def _expression_name(node: ast.AST | None) -> str:
    """Return a compact lexical expression name without claiming resolution."""

    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _expression_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Subscript):
        parent = _expression_name(node.value)
        return f"{parent}[]" if parent else "subscript"
    if isinstance(node, ast.Call):
        return _expression_name(node.func)
    if isinstance(node, ast.Constant):
        # Literal contents are values, not lexical target names.  Returning a
        # string literal verbatim made calls such as ``" ".join(...)`` emit
        # names containing whitespace/control characters and crash the closed
        # AST IR instead of producing a bounded dynamic-call fact.
        literal_type = type(node.value).__name__.lower()
        return f"{literal_type}_literal"
    return type(node).__name__


def _render(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return " ".join(ast.unparse(node).split())
    except (AttributeError, ValueError, TypeError):
        return type(node).__name__


def _default_kind(node: ast.AST | None) -> str:
    if node is None:
        return "none"
    if isinstance(
        node,
        (
            ast.Constant,
            ast.List,
            ast.Tuple,
            ast.Set,
            ast.Dict,
        ),
    ):
        return "literal"
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        return "factory"
    return "expression"


def _visibility(name: str) -> str:
    if name.startswith("__") and not name.endswith("__"):
        return "private"
    if name.startswith("_") and name not in {"__init__", "__call__"}:
        return "protected"
    return "public"


def _bound_names(node: ast.AST) -> Iterable[ast.Name]:
    """Yield assignment bindings without treating attribute bases as binds."""

    if isinstance(node, ast.Name):
        yield node
    elif isinstance(node, ast.Starred):
        yield from _bound_names(node.value)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for item in node.elts:
            yield from _bound_names(item)


def _contains_yield(node: ast.AST) -> bool:
    """Detect yields in this callable without entering nested callables."""

    pending = list(ast.iter_child_nodes(node))
    while pending:
        item = pending.pop()
        if isinstance(item, (ast.Yield, ast.YieldFrom)):
            return True
        if isinstance(
            item,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef),
        ):
            continue
        pending.extend(ast.iter_child_nodes(item))
    return False


def _module_name(path: str) -> str:
    pure = PurePosixPath(path)
    parts = list(pure.parts)
    if parts and parts[-1].endswith((".py", ".pyi")):
        suffix = ".pyi" if parts[-1].endswith(".pyi") else ".py"
        parts[-1] = parts[-1][: -len(suffix)]
    if parts and parts[-1] == "__init__":
        parts.pop()
    name = ".".join(part.replace(" ", "_") for part in parts if part not in {".", ""})
    return name or "__main__"


class _SourceMap:
    """Translate CPython AST UTF-8 line/column positions to absolute bytes."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.encoded = source.encode("utf-8")
        lines = source.splitlines(keepends=True)
        if not lines:
            lines = [""]
        self.lines = lines
        offsets: list[int] = []
        cursor = 0
        for line in lines:
            offsets.append(cursor)
            cursor += len(line.encode("utf-8"))
        self.offsets = offsets

    def whole_span(self) -> SourceSpan:
        final_line = len(self.lines)
        final_text = self.lines[-1]
        if final_text.endswith("\n"):
            final_line += 1
            final_column = 0
        else:
            final_column = len(final_text.encode("utf-8"))
        return SourceSpan(
            start_byte=0,
            end_byte=len(self.encoded),
            start_line=1,
            start_column=0,
            end_line=final_line,
            end_column=final_column,
        )

    def span(self, node: ast.AST | None) -> SourceSpan:
        if node is None or not hasattr(node, "lineno"):
            return self.whole_span()
        start_line = max(1, int(getattr(node, "lineno", 1) or 1))
        start_column = max(0, int(getattr(node, "col_offset", 0) or 0))
        end_line = max(
            start_line,
            int(getattr(node, "end_lineno", start_line) or start_line),
        )
        end_column = max(
            0,
            int(getattr(node, "end_col_offset", start_column) or start_column),
        )
        start_offset = self.offsets[min(start_line - 1, len(self.offsets) - 1)]
        end_offset = self.offsets[min(end_line - 1, len(self.offsets) - 1)]
        return SourceSpan(
            start_byte=min(start_offset + start_column, len(self.encoded)),
            end_byte=min(end_offset + end_column, len(self.encoded)),
            start_line=start_line,
            start_column=start_column,
            end_line=end_line,
            end_column=end_column,
        )

    def syntax_error_span(self, error: SyntaxError) -> SourceSpan:
        line = max(1, int(error.lineno or 1))
        end_line = max(line, int(getattr(error, "end_lineno", None) or line))
        # SyntaxError offsets are one-based Unicode columns, unlike AST byte
        # columns.  Re-encode the relevant prefix to preserve byte identity.
        start_character = max(0, int(error.offset or 1) - 1)
        end_character = max(
            start_character,
            int(getattr(error, "end_offset", None) or start_character + 1) - 1,
        )

        def byte_column(line_number: int, character: int) -> int:
            text = self.lines[min(line_number - 1, len(self.lines) - 1)]
            return len(text[:character].encode("utf-8"))

        start_column = byte_column(line, start_character)
        end_column = byte_column(end_line, end_character)
        start_offset = self.offsets[min(line - 1, len(self.offsets) - 1)]
        end_offset = self.offsets[min(end_line - 1, len(self.offsets) - 1)]
        return SourceSpan(
            start_byte=min(start_offset + start_column, len(self.encoded)),
            end_byte=min(end_offset + end_column, len(self.encoded)),
            start_line=line,
            start_column=start_column,
            end_line=end_line,
            end_column=end_column,
        )


class _PythonVisitor(ast.NodeVisitor):
    def __init__(self, source_map: _SourceMap, module_name: str) -> None:
        self.source_map = source_map
        self.module_name = module_name
        self.scopes: list[ScopeDefinition] = []
        self.symbols: list[SymbolDefinition] = []
        self.imports: list[ImportDefinition] = []
        self.references: list[ReferenceRecord] = []
        self.calls: list[CallRecord] = []
        self.effects: list[EffectRecord] = []
        self.diagnostics: list[DiagnosticRecord] = []
        self.unsupported: list[UnsupportedConstruct] = []
        self.export_names: set[str] = set()
        self._scope_stack: list[str] = ["scope:module"]
        self._qualifier_stack: list[str] = []
        self._scope_qualifiers: dict[str, tuple[str, ...]] = {
            "scope:module": (),
        }
        self._scope_kinds: dict[str, str] = {"scope:module": "module"}
        self._parent_scope: dict[str, str | None] = {"scope:module": None}
        self._defined_names: dict[str, set[str]] = defaultdict(set)
        self._definition_ordinals: dict[tuple[str, str], int] = defaultdict(int)
        self._counters: dict[str, int] = defaultdict(int)
        self._parents: dict[ast.AST, ast.AST] = {}
        self._reference_context: str | None = None
        self._scope_kind_stack: list[str] = ["module"]
        self._has_explicit_exports = False

    @property
    def scope_id(self) -> str:
        return self._scope_stack[-1]

    def _next(self, kind: str) -> int:
        value = self._counters[kind]
        self._counters[kind] += 1
        return value

    def prepare(self, tree: ast.AST) -> None:
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                self._parents[child] = parent

    def _record_id(self, kind: str, node: ast.AST) -> str:
        span = self.source_map.span(node)
        return f"{kind}:{span.start_byte}:{self._next(kind)}"

    def _qualified(self, name: str) -> str:
        return ".".join((self.module_name, *self._qualifier_stack, name))

    def _register_bound_name(self, name: str) -> None:
        """Record a lexical binding without manufacturing a resolution fact."""

        self._defined_names[self.scope_id].add(name)
        if (
            self.scope_id == "scope:module"
            and not self._has_explicit_exports
            and not name.startswith("_")
        ):
            self.export_names.add(name)

    def _set_explicit_exports(
        self,
        node: ast.AST,
        value: ast.AST | None,
    ) -> None:
        """Record a statically declared ``__all__`` or fail it explicitly."""

        self._has_explicit_exports = True
        if isinstance(value, (ast.List, ast.Tuple)):
            names = [
                item.value
                for item in value.elts
                if isinstance(item, ast.Constant) and type(item.value) is str
            ]
            if len(names) == len(value.elts):
                self.export_names = set(names)
                return
        self.export_names.clear()
        self._add_unsupported(
            node,
            "python.dynamic_exports",
            "dynamic_all",
            "__all__ is not a literal list or tuple of export names.",
        )

    def _add_symbol(
        self,
        node: ast.AST,
        name: str,
        kind: str,
        *,
        signature: SignatureDefinition | None = None,
        decorators: Sequence[str] = (),
        flags: Sequence[str] = (),
    ) -> SymbolDefinition:
        ordinal_key = (self.scope_id, name)
        ordinal = self._definition_ordinals[ordinal_key]
        self._definition_ordinals[ordinal_key] += 1
        symbol = SymbolDefinition(
            symbol_id=self._record_id("symbol", node),
            name=name,
            qualified_name=self._qualified(name),
            kind=kind,
            scope_id=self.scope_id,
            span=self.source_map.span(node),
            definition_ordinal=ordinal,
            signature=signature,
            visibility=_visibility(name),
            decorator_names=tuple(decorators),
            flags=tuple(flags),
        )
        self.symbols.append(symbol)
        if name in self._defined_names[self.scope_id]:
            self.diagnostics.append(
                DiagnosticRecord(
                    code="python.duplicate_definition",
                    severity="warning",
                    message=(
                        f"{name} is redefined in the same lexical scope; "
                        "definitions remain distinct until resolution."
                    ),
                    span=symbol.span,
                )
            )
        elif self._defined_in_parent(name, self.scope_id):
            self.diagnostics.append(
                DiagnosticRecord(
                    code="python.shadowed_definition",
                    severity="info",
                    message=f"{name} shadows a definition in an enclosing scope.",
                    span=symbol.span,
                )
            )
        self._register_bound_name(name)
        return symbol

    def _defined_in_parent(self, name: str, scope_id: str) -> bool:
        parent = self._parent_scope.get(scope_id)
        while parent is not None:
            if name in self._defined_names[parent]:
                return True
            parent = self._parent_scope.get(parent)
        return False

    def _add_scope(
        self,
        node: ast.AST,
        kind: str,
        *,
        owner_symbol_id: str | None = None,
    ) -> str:
        scope_id = self._record_id(f"scope:{kind}", node)
        self.scopes.append(
            ScopeDefinition(
                scope_id=scope_id,
                kind=kind,
                span=self.source_map.span(node),
                parent_scope_id=self.scope_id,
                owner_symbol_id=owner_symbol_id,
            )
        )
        self._parent_scope[scope_id] = self.scope_id
        self._scope_qualifiers[scope_id] = tuple(self._qualifier_stack)
        self._scope_kinds[scope_id] = kind
        return scope_id

    def _add_reference(
        self,
        node: ast.AST,
        name: str,
        context: str,
        *,
        qualified: bool = False,
    ) -> ReferenceRecord:
        reference = ReferenceRecord(
            reference_id=self._record_id("reference", node),
            name=name,
            scope_id=self.scope_id,
            context=context,
            span=self.source_map.span(node),
            is_qualified=qualified,
        )
        self.references.append(reference)
        return reference

    def _add_effect(
        self,
        node: ast.AST,
        kind: str,
        operation: str,
        subject: str = "",
    ) -> None:
        self.effects.append(
            EffectRecord(
                effect_id=self._record_id("effect", node),
                scope_id=self.scope_id,
                kind=kind,
                operation=operation,
                span=self.source_map.span(node),
                subject=subject,
            )
        )

    def _add_unsupported(
        self,
        node: ast.AST,
        code: str,
        construct: str,
        reason: str,
    ) -> None:
        self.unsupported.append(
            UnsupportedConstruct(
                unsupported_id=self._record_id("unsupported", node),
                code=code,
                construct=construct,
                reason=reason,
                span=self.source_map.span(node),
            )
        )

    def _visit_as(self, node: ast.AST | None, context: str) -> None:
        if node is None:
            return
        previous = self._reference_context
        self._reference_context = context
        self.visit(node)
        self._reference_context = previous

    def _signature(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> SignatureDefinition:
        arguments = node.args
        positional = [*arguments.posonlyargs, *arguments.args]
        positional_defaults: list[ast.AST | None] = [
            *([None] * (len(positional) - len(arguments.defaults))),
            *arguments.defaults,
        ]
        entries: list[tuple[ast.arg, str, ast.AST | None]] = []
        entries.extend(
            (item, "positional_only", default)
            for item, default in zip(
                arguments.posonlyargs,
                positional_defaults[: len(arguments.posonlyargs)],
            )
        )
        remaining_defaults = positional_defaults[len(arguments.posonlyargs) :]
        entries.extend(
            (item, "positional_or_named", default)
            for item, default in zip(arguments.args, remaining_defaults)
        )
        if arguments.vararg is not None:
            entries.append((arguments.vararg, "variadic_positional", None))
        entries.extend(
            (item, "named_only", default)
            for item, default in zip(arguments.kwonlyargs, arguments.kw_defaults)
        )
        if arguments.kwarg is not None:
            entries.append((arguments.kwarg, "variadic_named", None))

        parameters: list[ParameterDefinition] = []
        for position, (argument, kind, default) in enumerate(entries):
            if (
                position == 0
                and self._scope_kind_stack[-1] == "class"
                and argument.arg in {"self", "cls"}
                and kind == "positional_or_named"
            ):
                kind = "receiver"
            parameters.append(
                ParameterDefinition(
                    name=argument.arg,
                    kind=kind,
                    position=position,
                    annotation=_render(argument.annotation),
                    default_kind=_default_kind(default),
                )
            )
        is_generator = _contains_yield(node)
        return SignatureDefinition(
            parameters=tuple(parameters),
            return_annotation=_render(node.returns),
            is_async=isinstance(node, ast.AsyncFunctionDef),
            is_generator=is_generator,
        )

    def _visit_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        signature = self._signature(node)
        raw_decorators = tuple(
            _expression_name(item) for item in node.decorator_list
        )
        decorators = tuple(dict.fromkeys(raw_decorators))
        if len(decorators) != len(raw_decorators):
            self._add_unsupported(
                node,
                "python.repeated_decorator",
                "repeated_decorator",
                "The shared symbol IR requires unique decorator names.",
            )
        flags: list[str] = []
        if signature.is_async:
            flags.append("coroutine")
        if signature.is_generator:
            flags.append("generator")
        if signature.is_async and signature.is_generator:
            flags.append("async_generator")
        for name in decorators:
            tail = name.rsplit(".", 1)[-1]
            if tail in {"classmethod", "staticmethod", "abstractmethod"}:
                flags.append(tail)
        in_class_scope = self._scope_kind_stack[-1] == "class"
        kind = "method" if in_class_scope else "function"
        if in_class_scope and node.name == "__init__":
            kind = "constructor"
        symbol = self._add_symbol(
            node,
            node.name,
            kind,
            signature=signature,
            decorators=decorators,
            flags=flags,
        )
        for decorator in node.decorator_list:
            self._visit_as(decorator, "decorator")
        self._visit_as(node.returns, "type")
        for argument in (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        ):
            self._visit_as(argument.annotation, "type")
        if node.args.vararg is not None:
            self._visit_as(node.args.vararg.annotation, "type")
        if node.args.kwarg is not None:
            self._visit_as(node.args.kwarg.annotation, "type")
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)

        child_scope = self._add_scope(
            node,
            "function",
            owner_symbol_id=symbol.symbol_id,
        )
        self._scope_stack.append(child_scope)
        self._scope_kind_stack.append("function")
        self._qualifier_stack.append(node.name)
        parameter_nodes = [
            *node.args.posonlyargs,
            *node.args.args,
            *([node.args.vararg] if node.args.vararg is not None else []),
            *node.args.kwonlyargs,
            *([node.args.kwarg] if node.args.kwarg is not None else []),
        ]
        for argument in parameter_nodes:
            self._add_symbol(argument, argument.arg, "parameter")
        for statement in node.body:
            self.visit(statement)
        self._qualifier_stack.pop()
        self._scope_kind_stack.pop()
        self._scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        raw_decorators = tuple(
            _expression_name(item) for item in node.decorator_list
        )
        decorators = tuple(dict.fromkeys(raw_decorators))
        if len(decorators) != len(raw_decorators):
            self._add_unsupported(
                node,
                "python.repeated_decorator",
                "repeated_decorator",
                "The shared symbol IR requires unique decorator names.",
            )
        symbol = self._add_symbol(
            node,
            node.name,
            "class",
            decorators=decorators,
        )
        for decorator in node.decorator_list:
            self._visit_as(decorator, "decorator")
        for base in node.bases:
            self._visit_as(base, "base")
        for keyword in node.keywords:
            self._visit_as(keyword.value, "base")
        child_scope = self._add_scope(
            node,
            "class",
            owner_symbol_id=symbol.symbol_id,
        )
        self._scope_stack.append(child_scope)
        self._scope_kind_stack.append("class")
        self._qualifier_stack.append(node.name)
        for statement in node.body:
            self.visit(statement)
        self._qualifier_stack.pop()
        self._scope_kind_stack.pop()
        self._scope_stack.pop()

    def visit_Lambda(self, node: ast.Lambda) -> None:
        # Defaults are evaluated in the containing scope, before the lambda's
        # parameter scope exists.
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        child_scope = self._add_scope(node, "lambda")
        self._scope_stack.append(child_scope)
        self._scope_kind_stack.append("lambda")
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            self._add_symbol(argument, argument.arg, "parameter")
        if node.args.vararg is not None:
            self._add_symbol(node.args.vararg, node.args.vararg.arg, "parameter")
        if node.args.kwarg is not None:
            self._add_symbol(node.args.kwarg, node.args.kwarg.arg, "parameter")
        self.visit(node.body)
        self._scope_kind_stack.pop()
        self._scope_stack.pop()

    def _visit_comprehension_scope(
        self,
        node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    ) -> None:
        # Python evaluates the outermost iterable in the containing scope.
        # Targets, filters, subsequent iterables, and the result expression are
        # evaluated in the comprehension's implicit function scope.
        generators = node.generators
        self.visit(generators[0].iter)
        child_scope = self._add_scope(node, "comprehension")
        self._scope_stack.append(child_scope)
        self._scope_kind_stack.append("comprehension")
        for index, generator in enumerate(generators):
            if index:
                self.visit(generator.iter)
            self.visit(generator.target)
            if generator.is_async:
                self._add_effect(generator.iter, "await", "await", "async_for")
            for condition in generator.ifs:
                self.visit(condition)
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
        else:
            self.visit(node.elt)
        self._scope_kind_stack.pop()
        self._scope_stack.pop()

    visit_ListComp = _visit_comprehension_scope
    visit_SetComp = _visit_comprehension_scope
    visit_DictComp = _visit_comprehension_scope
    visit_GeneratorExp = _visit_comprehension_scope

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local_name = alias.asname or alias.name.split(".", 1)[0]
            self.imports.append(
                ImportDefinition(
                    import_id=self._record_id("import", node),
                    scope_id=self.scope_id,
                    module=alias.name,
                    kind="module",
                    span=self.source_map.span(node),
                    local_name=local_name,
                )
            )
            self._register_bound_name(local_name)
            self._add_effect(node, "import", "read", alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = "." * int(node.level or 0) + (node.module or "")
        for alias in node.names:
            local_name = alias.asname or alias.name
            self.imports.append(
                ImportDefinition(
                    import_id=self._record_id("import", node),
                    scope_id=self.scope_id,
                    module=module or ".",
                    kind="symbol",
                    span=self.source_map.span(node),
                    imported_name=alias.name,
                    local_name=local_name,
                )
            )
            if alias.name != "*":
                self._register_bound_name(local_name)
            self._add_effect(node, "import", "read", f"{module}.{alias.name}")
            if alias.name == "*":
                self._add_unsupported(
                    node,
                    "python.wildcard_import",
                    "wildcard_import",
                    "Wildcard bindings require cross-module export resolution.",
                )

    def visit_Name(self, node: ast.Name) -> None:
        if self._reference_context is not None:
            context = self._reference_context
        elif isinstance(node.ctx, ast.Store):
            context = "write"
        elif isinstance(node.ctx, ast.Del):
            context = "delete"
        else:
            context = "read"
        if context == "write":
            self._register_bound_name(node.id)
        self._add_reference(node, node.id, context)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        name = _expression_name(node)
        if self._reference_context is not None:
            context = self._reference_context
        elif isinstance(node.ctx, ast.Store):
            context = "write"
        elif isinstance(node.ctx, ast.Del):
            context = "delete"
        else:
            context = "read"
        self._add_reference(node, name, context, qualified=True)
        if name.startswith(("self.", "cls.")):
            operation = "read"
            if context == "write":
                operation = "write"
            elif context == "delete":
                operation = "delete"
            self._add_effect(node, "object_state", operation, name)
        self.visit(node.value)

    def visit_Assign(self, node: ast.Assign) -> None:
        if any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            self._set_explicit_exports(node, node.value)
        if self._scope_kind_stack[-1] in {"module", "class"}:
            for target in node.targets:
                for name_node in _bound_names(target):
                    self._add_symbol(name_node, name_node.id, "variable")
                    if self._scope_kind_stack[-1] == "module":
                        self._add_effect(
                            name_node,
                            "global_state",
                            "write",
                            name_node.id,
                        )
        for target in node.targets:
            self.visit(target)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and node.target.id == "__all__":
            self._set_explicit_exports(node, node.value)
        if (
            self._scope_kind_stack[-1] in {"module", "class"}
            and isinstance(node.target, ast.Name)
        ):
            self._add_symbol(node.target, node.target.id, "variable")
            if self._scope_kind_stack[-1] == "module":
                self._add_effect(
                    node.target,
                    "global_state",
                    "write",
                    node.target.id,
                )
        self.visit(node.target)
        self._visit_as(node.annotation, "type")
        if node.value is not None:
            self.visit(node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name) and node.target.id == "__all__":
            self._set_explicit_exports(node, None)
        if isinstance(node.target, ast.Name) and self._scope_kind_stack[-1] == "module":
            self._add_effect(
                node.target,
                "global_state",
                "mutate",
                node.target.id,
            )
        self.generic_visit(node)

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name) and self._scope_kind_stack[-1] == "module":
                self._add_effect(target, "global_state", "delete", target.id)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        if isinstance(node.target, ast.Name):
            if node.target.id == "__all__":
                self._set_explicit_exports(node, node.value)
            self._register_bound_name(node.target.id)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is not None:
            self.visit(node.type)
        if node.name is not None:
            # CPython stores the handler binding as a string rather than a
            # Name(Store) node, so register it explicitly in this scope.
            self._register_bound_name(node.name)
        for statement in node.body:
            self.visit(statement)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.pattern is not None:
            self.visit(node.pattern)
        if node.name is not None:
            self._register_bound_name(node.name)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            self._register_bound_name(node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        for key in node.keys:
            self.visit(key)
        for pattern in node.patterns:
            self.visit(pattern)
        if node.rest is not None:
            self._register_bound_name(node.rest)

    def visit_Global(self, node: ast.Global) -> None:
        self._add_unsupported(
            node,
            "python.dynamic_scope",
            "global",
            "Global rebinding requires a separate scope-resolution pass.",
        )

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self._add_unsupported(
            node,
            "python.dynamic_scope",
            "nonlocal",
            "Nonlocal rebinding requires a separate scope-resolution pass.",
        )

    def visit_Call(self, node: ast.Call) -> None:
        callee_name = _expression_name(node.func) or "dynamic"
        call_reference = self._add_reference(
            node.func,
            callee_name,
            "call",
            qualified=isinstance(node.func, (ast.Attribute, ast.Subscript)),
        )
        parent = self._parents.get(node)
        is_awaited = isinstance(parent, ast.Await)
        kind = "direct"
        if isinstance(node.func, ast.Attribute):
            kind = "method"
        elif not isinstance(node.func, ast.Name):
            kind = "dynamic"
        self.calls.append(
            CallRecord(
                call_id=self._record_id("call", node),
                scope_id=self.scope_id,
                callee_name=callee_name,
                kind=kind,
                argument_count=len(node.args) + len(node.keywords),
                span=self.source_map.span(node),
                callee_reference_id=call_reference.reference_id,
                named_argument_names=tuple(
                    item.arg for item in node.keywords if item.arg is not None
                ),
                is_awaited=is_awaited,
            )
        )
        if callee_name in _DYNAMIC_CALLS:
            self._add_unsupported(
                node,
                "python.dynamic_execution",
                callee_name.replace(".", "_"),
                "The call target or executed source cannot be bounded statically.",
            )
        self.generic_visit(node)

    def visit_Await(self, node: ast.Await) -> None:
        self._add_effect(node, "await", "await", _expression_name(node.value))
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        self._add_effect(node, "exception", "raise", _expression_name(node.exc))
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        self._add_effect(node, "context_manager", "enter", "with")
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._add_effect(node, "context_manager", "enter", "async_with")
        self.generic_visit(node)

    def finalize(self) -> None:
        """Emit conservative undefined-reference candidate diagnostics."""

        for reference in self.references:
            if reference.context not in {"read", "call", "decorator", "base", "type"}:
                continue
            root_name = reference.name.split(".", 1)[0]
            if root_name in _BUILTIN_NAMES:
                continue
            scope_id: str | None = reference.scope_id
            found = False
            while scope_id is not None:
                # A class body is a lexical scope for its own expressions, but
                # it is not a closure captured by methods, comprehensions, or
                # nested classes.
                is_non_closure_class = (
                    scope_id != reference.scope_id
                    and self._scope_kinds.get(scope_id) == "class"
                )
                if (
                    not is_non_closure_class
                    and root_name in self._defined_names[scope_id]
                ):
                    found = True
                    break
                scope_id = self._parent_scope.get(scope_id)
            if not found:
                self.diagnostics.append(
                    DiagnosticRecord(
                        code="python.undefined_reference_candidate",
                        severity="warning",
                        message=(
                            f"{root_name} has no lexical definition in this source "
                            "blob; cross-module resolution is required."
                        ),
                        span=reference.span,
                    )
                )


class PythonASTExtractor:
    """Build deterministic shared AST records from Python source."""

    def __init__(
        self,
        *,
        feature_version: tuple[int, int] | None = None,
        max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
        max_ast_nodes: int = DEFAULT_MAX_AST_NODES,
    ) -> None:
        if type(max_source_bytes) is not int or max_source_bytes <= 0:
            raise ValueError("max_source_bytes must be a positive exact integer")
        if max_source_bytes > DEFAULT_MAX_SOURCE_BYTES:
            raise ValueError(
                f"max_source_bytes cannot exceed {DEFAULT_MAX_SOURCE_BYTES}"
            )
        if type(max_ast_nodes) is not int or max_ast_nodes <= 0:
            raise ValueError("max_ast_nodes must be a positive exact integer")
        if max_ast_nodes > DEFAULT_MAX_AST_NODES:
            raise ValueError(f"max_ast_nodes cannot exceed {DEFAULT_MAX_AST_NODES}")
        if feature_version is not None:
            if (
                type(feature_version) is not tuple
                or len(feature_version) != 2
                or any(type(item) is not int or item < 0 for item in feature_version)
            ):
                raise ValueError("feature_version must be an exact (major, minor) tuple")
        self.feature_version = feature_version
        self.max_source_bytes = max_source_bytes
        self.max_ast_nodes = max_ast_nodes

    @property
    def capability(self) -> FrontendCapability:
        language_version = (
            ".".join(str(item) for item in self.feature_version)
            if self.feature_version is not None
            else f"{sys.version_info.major}.{sys.version_info.minor}"
        )
        toolchain = {
            "frontend": PYTHON_FRONTEND_NAME,
            "frontend_version": PYTHON_FRONTEND_VERSION,
            "implementation": sys.implementation.name,
            "parser_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "feature_version": language_version,
            "execution": False,
        }
        return FrontendCapability(
            frontend_name=PYTHON_FRONTEND_NAME,
            frontend_version=PYTHON_FRONTEND_VERSION,
            language="python",
            language_version=language_version,
            capabilities=(
                "annotations",
                "awaits",
                "calls",
                "decorators",
                "diagnostics",
                "duplicate_definitions",
                "effects",
                "generators",
                "imports",
                "modules",
                "raises",
                "references",
                "scopes",
                "signatures",
                "source_spans",
                "state_access",
                "symbols",
                "undefined_reference_candidates",
                "unsupported_constructs",
            ),
            source_extensions=PYTHON_SOURCE_EXTENSIONS,
            toolchain_cid=cid_for_structured(toolchain),
        )

    def extract(
        self,
        source: str | bytes,
        *,
        path: str = "source.py",
        repository_id: str = "repository:unknown",
        revision: str = "unversioned",
        repository_tree_cid: str | None = None,
        module_name: str | None = None,
    ) -> ASTRecord:
        return self.extract_from_source(
            source,
            path=path,
            repository_id=repository_id,
            revision=revision,
            repository_tree_cid=repository_tree_cid,
            module_name=module_name,
        )

    def parse(self, source: str | bytes, **kwargs: Any) -> ASTRecord:
        return self.extract_from_source(source, **kwargs)

    def extract_from_source(
        self,
        source: str | bytes,
        *,
        path: str = "source.py",
        repository_id: str = "repository:unknown",
        revision: str = "unversioned",
        repository_tree_cid: str | None = None,
        module_name: str | None = None,
    ) -> ASTRecord:
        if type(source) is str:
            try:
                source_bytes = source.encode("utf-8")
            except UnicodeEncodeError as exc:
                # Lone surrogates cannot participate in the reviewed UTF-8
                # span convention.
                source_bytes = b""
                source_text = ""
                return self._failure_record(
                    source_bytes,
                    source_text,
                    path=path,
                    repository_id=repository_id,
                    revision=revision,
                    repository_tree_cid=repository_tree_cid,
                    module_name=module_name,
                    code="python.invalid_encoding",
                    construct="source_encoding",
                    reason=f"Source is not strict UTF-8: {exc.reason}.",
                )
            source_text = source
        elif type(source) is bytes:
            source_bytes = source
            try:
                source_text = source.decode("utf-8")
            except UnicodeDecodeError as exc:
                return self._failure_record(
                    source_bytes,
                    "",
                    path=path,
                    repository_id=repository_id,
                    revision=revision,
                    repository_tree_cid=repository_tree_cid,
                    module_name=module_name,
                    code="python.invalid_encoding",
                    construct="source_encoding",
                    reason=f"Source is not strict UTF-8 at byte {exc.start}.",
                )
        else:
            raise TypeError("source must be an exact str or bytes value")

        if len(source_bytes) > self.max_source_bytes:
            return self._failure_record(
                source_bytes,
                source_text,
                path=path,
                repository_id=repository_id,
                revision=revision,
                repository_tree_cid=repository_tree_cid,
                module_name=module_name,
                code="python.resource_limit",
                construct="source_size",
                reason=(
                    f"Source has {len(source_bytes)} bytes; limit is "
                    f"{self.max_source_bytes}."
                ),
            )

        source_map = _SourceMap(source_text)
        try:
            tree = ast.parse(
                source_text,
                filename=path,
                type_comments=True,
                feature_version=self.feature_version,
            )
        except (SyntaxError, ValueError, MemoryError, RecursionError) as exc:
            if isinstance(exc, SyntaxError):
                error_span = source_map.syntax_error_span(exc)
                message = f"{exc.msg} at line {exc.lineno or 1}"
                construct = "syntax_error"
            else:
                error_span = source_map.whole_span()
                message = f"{type(exc).__name__}: {exc}"
                construct = "parser_error"
            return self._failure_record(
                source_bytes,
                source_text,
                path=path,
                repository_id=repository_id,
                revision=revision,
                repository_tree_cid=repository_tree_cid,
                module_name=module_name,
                code="python.parse_error",
                construct=construct,
                reason=message,
                span=error_span,
            )

        try:
            node_count = sum(1 for _ in ast.walk(tree))
        except MemoryError:
            return self._failure_record(
                source_bytes,
                source_text,
                path=path,
                repository_id=repository_id,
                revision=revision,
                repository_tree_cid=repository_tree_cid,
                module_name=module_name,
                code="python.resource_limit",
                construct="ast_node_count",
                reason="MemoryError: AST node counting exceeded its resource budget.",
            )
        if node_count > self.max_ast_nodes:
            return self._failure_record(
                source_bytes,
                source_text,
                path=path,
                repository_id=repository_id,
                revision=revision,
                repository_tree_cid=repository_tree_cid,
                module_name=module_name,
                code="python.resource_limit",
                construct="ast_node_count",
                reason=f"AST has {node_count} nodes; limit is {self.max_ast_nodes}.",
            )

        normalized_module_name = module_name or _module_name(path)
        visitor = _PythonVisitor(source_map, normalized_module_name)
        visitor.scopes.append(
            ScopeDefinition(
                scope_id="scope:module",
                kind="module",
                span=source_map.whole_span(),
            )
        )
        try:
            visitor.prepare(tree)
            visitor.visit(tree)
            visitor.finalize()
        except (MemoryError, RecursionError) as exc:
            return self._failure_record(
                source_bytes,
                source_text,
                path=path,
                repository_id=repository_id,
                revision=revision,
                repository_tree_cid=repository_tree_cid,
                module_name=module_name,
                code="python.resource_limit",
                construct="frontend_traversal",
                reason=(
                    f"{type(exc).__name__}: frontend traversal exceeded its "
                    "resource budget."
                ),
            )
        provenance = SourceProvenance(
            source_cid=cid_for_bytes(source_bytes),
            path=path,
            repository_id=repository_id,
            revision=revision,
            repository_tree_cid=repository_tree_cid,
        )
        return ASTRecord(
            provenance=provenance,
            frontend=self.capability,
            module=ModuleDefinition(
                module_id=f"module:{provenance.source_cid}",
                name=normalized_module_name,
                scope_id="scope:module",
                span=source_map.whole_span(),
                export_names=tuple(visitor.export_names),
            ),
            scopes=tuple(visitor.scopes),
            symbols=tuple(visitor.symbols),
            imports=tuple(visitor.imports),
            references=tuple(visitor.references),
            calls=tuple(visitor.calls),
            effects=tuple(visitor.effects),
            diagnostics=tuple(visitor.diagnostics),
            unsupported=tuple(visitor.unsupported),
        )

    def extract_path(
        self,
        path: str | Path,
        *,
        repository_id: str = "repository:unknown",
        revision: str = "unversioned",
        repository_tree_cid: str | None = None,
        logical_path: str | None = None,
        module_name: str | None = None,
    ) -> ASTRecord:
        source_path = Path(path)
        if logical_path is None:
            try:
                selected_path = source_path.resolve().relative_to(
                    Path.cwd().resolve()
                ).as_posix()
            except ValueError:
                selected_path = source_path.name
        else:
            selected_path = logical_path
        return self.extract_from_source(
            source_path.read_bytes(),
            path=selected_path,
            repository_id=repository_id,
            revision=revision,
            repository_tree_cid=repository_tree_cid,
            module_name=module_name,
        )

    def _failure_record(
        self,
        source_bytes: bytes,
        source_text: str,
        *,
        path: str,
        repository_id: str,
        revision: str,
        repository_tree_cid: str | None,
        module_name: str | None,
        code: str,
        construct: str,
        reason: str,
        span: SourceSpan | None = None,
    ) -> ASTRecord:
        source_map = _SourceMap(source_text)
        failure_span = span or source_map.whole_span()
        provenance = SourceProvenance(
            source_cid=cid_for_bytes(source_bytes),
            path=path,
            repository_id=repository_id,
            revision=revision,
            repository_tree_cid=repository_tree_cid,
        )
        return ASTRecord(
            provenance=provenance,
            frontend=self.capability,
            module=ModuleDefinition(
                module_id=f"module:{provenance.source_cid}",
                name=module_name or _module_name(path),
                scope_id="scope:module",
                span=source_map.whole_span(),
            ),
            scopes=(
                ScopeDefinition(
                    scope_id="scope:module",
                    kind="module",
                    span=source_map.whole_span(),
                ),
            ),
            diagnostics=(
                DiagnosticRecord(
                    code=code,
                    severity="error",
                    message=reason,
                    span=failure_span,
                ),
            ),
            unsupported=(
                UnsupportedConstruct(
                    unsupported_id="unsupported:frontend:0",
                    code=code,
                    construct=construct,
                    reason=reason,
                    span=failure_span,
                ),
            ),
        )


def build_python_ast_blob_record(
    source: str | bytes,
    *,
    path: str = "source.py",
    repository_id: str = "repository:unknown",
    revision: str = "unversioned",
    repository_tree_cid: str | None = None,
    module_name: str | None = None,
    feature_version: tuple[int, int] | None = None,
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
    max_ast_nodes: int = DEFAULT_MAX_AST_NODES,
) -> ASTRecord:
    """Compatibility constructor for one normalized Python AST blob record."""

    return PythonASTExtractor(
        feature_version=feature_version,
        max_source_bytes=max_source_bytes,
        max_ast_nodes=max_ast_nodes,
    ).extract_from_source(
        source,
        path=path,
        repository_id=repository_id,
        revision=revision,
        repository_tree_cid=repository_tree_cid,
        module_name=module_name,
    )


# The packet AST query uses the established accelerator noun.  This is a
# compatibility alias to the shared, versioned record rather than a second
# schema.
ASTBlobRecord = ASTRecord


__all__ = [
    "ASTBlobRecord",
    "DEFAULT_MAX_AST_NODES",
    "DEFAULT_MAX_SOURCE_BYTES",
    "PYTHON_FRONTEND_NAME",
    "PYTHON_FRONTEND_VERSION",
    "PYTHON_SOURCE_EXTENSIONS",
    "PythonASTExtractor",
    "build_python_ast_blob_record",
]
