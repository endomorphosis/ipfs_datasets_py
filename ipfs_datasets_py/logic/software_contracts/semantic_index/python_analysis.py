"""Symbol-local Python semantic extraction built on the shared frontend.

The shared :mod:`python_frontend` is the authority for parsing, lexical
scopes, declarations, diagnostics, and unsupported-construct notices.
This module only adds the stable semantic-index projection: it groups
frontend declarations that share a logical binding and never executes the
source it examines.
"""
from __future__ import annotations

import ast
import copy
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable, Sequence

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.python_frontend import PythonASTExtractor
from ipfs_datasets_py.logic.software_contracts.semantic_index.identity import (
    DEFAULT_EXTRACTOR_NAME, DEFAULT_EXTRACTOR_VERSION, normalize_ast,
    stable_symbol_id, symbol_version_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    DependencyEdge, RelationType, SourceSpan, SymbolKind, SymbolRecord,
)

PYTHON_SEMANTIC_ANALYSIS_SCHEMA = "ipfs-datasets.software-contracts.python-semantic-analysis@2"
EXTRACTOR_VERSION = "2"
_SAFE_DECORATORS = frozenset({
    "property", "staticmethod", "classmethod", "dataclass", "dataclasses.dataclass",
    "abstractmethod", "abc.abstractmethod", "override", "typing.override",
    "overload", "typing.overload",
})
_NATIVE_ROOTS = frozenset({"ctypes", "cffi", "cython", "numpy.ctypeslib"})
_DYNAMIC = frozenset({
    "eval", "exec", "compile", "__import__",
    "importlib.import_module", "runpy.run_module", "runpy.run_path",
})
_REFLECTION = frozenset({
    "getattr", "setattr", "delattr", "hasattr", "vars", "dir",
    "inspect.getmembers", "inspect.signature",
})
_UNCONTROLLED = frozenset({
    "open", "subprocess.run", "subprocess.Popen", "os.system",
    "socket.socket", "requests.get", "requests.post",
})
_FATAL_DIAGNOSTIC_CODES = frozenset({
    "python.invalid_encoding",
    "python.parse_error",
    "python.resource_limit",
})
_FRONTEND_ADDRESSABLE_KINDS = frozenset({
    "class", "constructor", "function", "method", "variable",
})
_CONTROL_FLOW = (
    ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.ExceptHandler,
    ast.With, ast.AsyncWith, ast.Match, ast.match_case,
)


def _name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        value = _name(node.value)
        return f"{value}.{node.attr}" if value else node.attr
    if isinstance(node, ast.Subscript):
        return (_name(node.value) or "<dynamic>") + "[]"
    if isinstance(node, ast.Call):
        return _name(node.func)
    return ""


def _render(node: ast.AST | None) -> str:
    """Render source syntax without normalising whitespace inside literals."""
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except (TypeError, ValueError, AttributeError):
        return type(node).__name__


def _module_name(path: str) -> str:
    parts = list(PurePosixPath(path.replace("\\", "/")).parts)
    if parts and parts[-1].endswith((".py", ".pyi")):
        parts[-1] = parts[-1].rsplit(".", 1)[0]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or "__main__"


def _span(path: str, node: ast.AST) -> SourceSpan:
    return SourceSpan(
        path,
        max(1, getattr(node, "lineno", 1)),
        max(0, getattr(node, "col_offset", 0)),
        max(1, getattr(node, "end_lineno", getattr(node, "lineno", 1))),
        max(0, getattr(node, "end_col_offset", getattr(node, "col_offset", 0))),
    )


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
    args = node.args
    positional = [*args.posonlyargs, *args.args]
    defaults: list[ast.AST | None] = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    values: list[dict[str, Any]] = []
    for index, item in enumerate(positional):
        default = defaults[index]
        values.append({
            "name": item.arg,
            "kind": "positional_only" if index < len(args.posonlyargs) else "positional_or_keyword",
            "annotation": _render(item.annotation),
            "default": _render(default),
            "default_kind": "none" if default is None else type(default).__name__,
        })
    if args.vararg:
        values.append({
            "name": args.vararg.arg, "kind": "var_positional",
            "annotation": _render(args.vararg.annotation), "default": "", "default_kind": "none",
        })
    for item, default in zip(args.kwonlyargs, args.kw_defaults):
        values.append({
            "name": item.arg, "kind": "keyword_only",
            "annotation": _render(item.annotation), "default": _render(default),
            "default_kind": "none" if default is None else type(default).__name__,
        })
    if args.kwarg:
        values.append({
            "name": args.kwarg.arg, "kind": "var_keyword",
            "annotation": _render(args.kwarg.annotation), "default": "", "default_kind": "none",
        })
    return {
        "parameters": values,
        "return": _render(node.returns),
        "is_generator": any(
            isinstance(value, (ast.Yield, ast.YieldFrom)) for value in _own_nodes(node.body)
        ),
    }


def _own_nodes(nodes: Sequence[ast.AST]) -> Iterable[ast.AST]:
    """Yield nodes owned by a body, excluding nested callable/class bodies."""
    for node in nodes:
        yield node
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            yield from _own_nodes((child,))


class _ChildProjection(ast.NodeTransformer):
    """Remove independently addressable children at every nesting depth."""

    def __init__(self, root: ast.AST) -> None:
        self.root = root
        self.class_root = isinstance(root, ast.ClassDef)

    def _member_interface(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.Expr:
        return ast.copy_location(ast.Expr(value=ast.Constant(value={
            "member": node.name,
            "signature": _signature(node),
            "decorators": [_render(value) for value in node.decorator_list],
        })), node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST | None:
        if node is self.root:
            return self.generic_visit(node)
        return self._member_interface(node) if self.class_root else None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST | None:
        if node is self.root:
            return self.generic_visit(node)
        return self._member_interface(node) if self.class_root else None

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST | None:
        if node is self.root:
            return self.generic_visit(node)
        return None


def _projection(node: ast.AST) -> Any:
    """A declaration projection retains interfaces, never child implementation bodies.

    Definitions can occur below ``if``, ``try``, ``with`` and ``match`` nodes, so a
    direct ``body`` filter is insufficient: use a transformer to elide them
    recursively without dropping the enclosing control-flow syntax.
    """
    clone = copy.deepcopy(node)
    return normalize_ast(_ChildProjection(clone).visit(clone) or clone)


def _resolved_name(node: ast.AST | None, aliases: dict[str, str]) -> str:
    """Expand a lexical prefix alias once, preserving attribute tails."""
    raw = _name(node)
    if not raw:
        return raw
    root, dot, rest = raw.partition(".")
    return aliases.get(root, root) + (dot + rest if dot else "")


def _kind(node: ast.AST, aliases: dict[str, str] | None = None) -> SymbolKind:
    aliases = aliases or {}
    if isinstance(node, ast.AsyncFunctionDef):
        return SymbolKind.ASYNC_FUNCTION
    if isinstance(node, ast.FunctionDef):
        return SymbolKind.FUNCTION
    if isinstance(node, ast.ClassDef):
        bases = {_resolved_name(value, aliases).split(".")[-1] for value in node.bases}
        decorators = {_resolved_name(value, aliases).split(".")[-1] for value in node.decorator_list}
        if "TypedDict" in bases:
            return SymbolKind.TYPED_DICT
        if bases & {"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"}:
            return SymbolKind.ENUM
        if "dataclass" in decorators:
            return SymbolKind.DATACLASS
        return SymbolKind.CLASS
    return SymbolKind.VARIABLE


def _property_role(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    names = [_name(value) for value in node.decorator_list]
    if "property" in names:
        return "getter"
    for name in names:
        if name.endswith(".setter"):
            return "setter"
        if name.endswith(".deleter"):
            return "deleter"
        if name.endswith(".getter"):
            return "getter"
    return None


def _has_overload_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(_name(item).split(".")[-1] == "overload" for item in node.decorator_list)


def _public_signature(
    nodes: Sequence[ast.AST],
    signatures: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Build the public signature facet, treating overload decls as authoritative."""
    if not signatures:
        return {}
    overload_sigs = [
        _signature(node)
        for node in nodes
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _has_overload_decorator(node)
    ]
    implementation = signatures[-1]
    if overload_sigs:
        return {
            "parameters": implementation["parameters"],
            "return": implementation["return"],
            "is_generator": implementation["is_generator"],
            "overloads": list(overload_sigs),
            "implementation": implementation,
        }
    return dict(implementation)


def _under_control_flow(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """True when the declaration itself is nested under control-flow syntax."""
    current = parents.get(node)
    while current is not None:
        if isinstance(current, _CONTROL_FLOW):
            return True
        current = parents.get(current)
    return False


def _notices_for_nodes(
    notices: Sequence[Any],
    nodes: Sequence[ast.AST],
) -> list[str]:
    codes: set[str] = set()
    for node in nodes:
        start = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", start)
        for notice in notices:
            span = getattr(notice, "span", None)
            if span is None:
                continue
            if start <= span.start_line <= end:
                codes.add(notice.code)
    return sorted(codes)


class ConfidenceClassifier(ast.NodeVisitor):
    def __init__(self, aliases: dict[str, str]) -> None:
        self.reasons: set[str] = set()
        self.aliases = aliases

    @property
    def confidence(self) -> str:
        return classify_confidence(self.reasons)

    def visit_Call(self, node: ast.Call) -> None:
        name = _resolved_name(node.func, self.aliases)
        if name in {"eval", "exec"}:
            self.reasons.add("eval_or_exec")
        elif name in _DYNAMIC:
            self.reasons.add("runtime_code_generation" if name == "compile" else "dynamic_import")
        elif name in _REFLECTION or name.endswith(".__setattr__") or name.endswith(".__getattribute__"):
            self.reasons.add("reflection")
            if len(node.args) < 2 or not isinstance(node.args[1], ast.Constant):
                self.reasons.add("constructed_attribute")
        elif name in _UNCONTROLLED:
            self.reasons.add("uncontrolled_effect")
        elif name.startswith("ctypes.") or name in {"CDLL", "PyDLL", "WinDLL"}:
            self.reasons.add("native_boundary")
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        if any(
            alias.name == root or alias.name.startswith(root + ".")
            for alias in node.names for root in _NATIVE_ROOTS
        ):
            self.reasons.add("native_boundary")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module and any(
            node.module == root or node.module.startswith(root + ".")
            for root in _NATIVE_ROOTS
        ):
            self.reasons.add("native_boundary")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if any(keyword.arg == "metaclass" for keyword in node.keywords):
            self.reasons.add("metaclass_mutation")
        self.generic_visit(node)


class _FactsVisitor(ast.NodeVisitor):
    def __init__(
        self,
        path: str,
        source_id: str,
        root: ast.AST,
        aliases: dict[str, str],
        module_bindings: set[str],
    ) -> None:
        self.path = path
        self.source_id = source_id
        self.root = root
        self.aliases = aliases
        self.module_bindings = module_bindings
        self.edges: list[DependencyEdge] = []
        self.globals: set[str] = set()

    def edge(
        self,
        node: ast.AST,
        relation: RelationType,
        target: str,
        method: str = "lexical",
        confidence: str = "conservative",
        **metadata: Any,
    ) -> None:
        self.edges.append(DependencyEdge(
            self.source_id, target, relation, method, confidence,
            EXTRACTOR_VERSION, _span(self.path, node), metadata,
        ))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.edge(
                node, RelationType.IMPORTS, "module:" + alias.name,
                "static_import", "exact", alias=alias.asname or alias.name.split(".")[0],
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = "." * node.level + (node.module or "")
        for alias in node.names:
            self.edge(
                node, RelationType.IMPORTS,
                "module:" + module + ("." if module else "") + alias.name,
                "static_import", "conservative" if alias.name == "*" else "exact",
                alias=alias.asname or alias.name,
            )

    def visit_Call(self, node: ast.Call) -> None:
        raw = _name(node.func) or "<dynamic-call>"
        name = _resolved_name(node.func, self.aliases) or raw
        native = name.startswith("ctypes.") or name in {"CDLL", "PyDLL", "WinDLL"}
        self.edge(
            node, RelationType.CALLS, "lexical:" + name, "lexical",
            "opaque" if native else "conservative", native_boundary=native,
        )
        tail = name.rsplit(".", 1)[-1]
        target = "lexical:" + name
        if tail in {"dump", "dumps", "serialize", "to_dict", "to_json", "model_dump"}:
            self.edge(node, RelationType.SERIALIZES, target)
        if tail in {"load", "loads", "deserialize", "from_dict", "from_json", "model_validate_json"}:
            self.edge(node, RelationType.DESERIALIZES, target)
        if tail in {"validate", "validate_json", "parse_obj", "model_validate"}:
            self.edge(node, RelationType.VALIDATES, target)
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        self.edge(
            node, RelationType.RAISES,
            "exception:" + (_name(node.exc) or "<unknown>"),
            "direct_raise", "exact",
        )
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        types = node.type.elts if isinstance(node.type, ast.Tuple) else (node.type,)
        for value in types:
            self.edge(
                value or node, RelationType.CATCHES,
                "exception:" + (_name(value) or "BaseException"),
                "direct_except", "exact",
            )
        self.generic_visit(node)

    def visit_With(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            self.edge(
                item.context_expr, RelationType.CALLS,
                "context:" + (_name(item.context_expr) or "<dynamic>"),
                "context_manager",
            )
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def visit_Global(self, node: ast.Global) -> None:
        self.globals.update(node.names)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in self.globals or (node.id in self.module_bindings and self.root is not node):
            self.edge(
                node,
                RelationType.READS_STATE if isinstance(node.ctx, ast.Load) else RelationType.WRITES_STATE,
                "global:" + node.id, "global_binding", "exact",
            )

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        # Augmented assignment consumes the old binding before replacing it;
        # CPython's target context alone only exposes the write side.
        if isinstance(node.target, ast.Name) and (
            node.target.id in self.globals or node.target.id in self.module_bindings
        ):
            self.edge(
                node.target, RelationType.READS_STATE,
                "global:" + node.target.id, "global_binding", "exact",
            )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        relation = RelationType.READS_STATE if isinstance(node.ctx, ast.Load) else RelationType.WRITES_STATE
        self.edge(
            node, relation, "state:" + (_name(node) or "<dynamic>"),
            "attribute_read" if relation == RelationType.READS_STATE else "attribute_write",
        )
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.edge(
                node, RelationType.WRITES_STATE,
                "state:" + (_name(node.value) or "<dynamic>") + "[]",
                "subscript_write",
            )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.root:
            self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node is self.root:
            self.generic_visit(node)


@dataclass(frozen=True, slots=True)
class PythonFrontendDisposition:
    """Fatal-versus-nonfatal disposition of a frontend extraction."""

    fatal_diagnostics: tuple[str, ...] = ()
    notices: tuple[Any, ...] = ()

    @property
    def is_fatal(self) -> bool:
        return bool(self.fatal_diagnostics)


@dataclass(frozen=True, slots=True)
class PythonSymbolFacts:
    symbol: SymbolRecord
    normalized_ast: Any
    edges: tuple[DependencyEdge, ...]
    confidence_reasons: tuple[str, ...] = ()

    @property
    def confidence(self) -> str:
        return self.symbol.confidence


@dataclass(frozen=True, slots=True)
class PythonSemanticAnalysis:
    path: str
    source_cid: str
    symbols: tuple[PythonSymbolFacts, ...]
    diagnostics: tuple[str, ...] = ()
    schema: str = PYTHON_SEMANTIC_ANALYSIS_SCHEMA

    @property
    def symbol_records(self) -> tuple[SymbolRecord, ...]:
        return tuple(item.symbol for item in self.symbols)

    @property
    def edges(self) -> tuple[DependencyEdge, ...]:
        return tuple(edge for item in self.symbols for edge in item.edges)


# Kept as an explicit v2 name for callers which distinguish the frontend's
# ASTRecord from this grouped semantic-index result.
PythonAnalysisResult = PythonSemanticAnalysis


def classify_confidence(reasons: Iterable[str]) -> str:
    """Classify already-observed source-bound uncertainty reasons."""
    values = set(reasons)
    if values & {
        "eval_or_exec", "reflection", "constructed_attribute", "native_boundary",
        "monkey_patch", "metaclass_mutation", "runtime_code_generation",
    }:
        return "opaque"
    return "conservative" if values else "exact"


def aggregate_logical_bindings(facts: Iterable[PythonSymbolFacts]) -> tuple[PythonSymbolFacts, ...]:
    """Return one deterministic fact per stable logical binding.

    ``PythonSemanticAnalyzer`` performs aggregation before constructing
    records; this helper is the safe public normalizer for already grouped
    results and rejects an ambiguous duplicate instead of inventing an ID.
    """
    result = tuple(sorted(facts, key=lambda item: item.symbol.stable_id))
    if len({item.symbol.stable_id for item in result}) != len(result):
        raise ValueError("logical binding facts must not duplicate stable IDs")
    return result


class PythonSemanticAnalyzer:
    def __init__(
        self,
        *,
        repository_id: str,
        namespace: str | None = None,
        extractor_name: str = DEFAULT_EXTRACTOR_NAME,
        extractor_version: str = DEFAULT_EXTRACTOR_VERSION,
    ) -> None:
        self.repository_id = repository_id
        self.namespace = namespace
        self.extractor_name = extractor_name
        self.extractor_version = extractor_version

    def analyze(self, source: str | bytes, path: str) -> PythonSemanticAnalysis:
        raw = source.encode("utf-8") if isinstance(source, str) else source
        source_cid = cid_for_bytes(raw)
        # The frontend is the declaration and scope authority.  AST nodes below
        # are only syntax payloads keyed back to those canonical facts.
        frontend = PythonASTExtractor().extract(raw, path=path, repository_id=self.repository_id)
        notices = tuple((*frontend.diagnostics, *frontend.unsupported))
        disposition = PythonFrontendDisposition(
            fatal_diagnostics=tuple(sorted({
                item.code for item in notices if item.code in _FATAL_DIAGNOSTIC_CODES
            })),
            notices=notices,
        )
        if disposition.is_fatal:
            return PythonSemanticAnalysis(path, source_cid, (), disposition.fatal_diagnostics)
        try:
            text = raw.decode("utf-8")
            tree = ast.parse(text, filename=path, type_comments=True)
        except (UnicodeDecodeError, SyntaxError, ValueError):
            return PythonSemanticAnalysis(path, source_cid, (), ("python.parse_error",))

        module = _module_name(path)
        namespace = self.namespace or module.split(".")[0]
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        ast_nodes: dict[tuple[int, int, str], ast.AST] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                ast_nodes[(node.lineno, node.col_offset, node.name)] = node
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        ast_nodes[(target.lineno, target.col_offset, target.id)] = node

        scope_parent = {scope.scope_id: scope.parent_scope_id for scope in frontend.scopes}
        scope_imports: dict[str, dict[str, str]] = defaultdict(dict)
        for item in frontend.imports:
            if item.local_name and item.local_name != "*":
                if item.kind == "module":
                    target = item.module
                else:
                    target = item.module.rstrip(".") + "." + (item.imported_name or item.local_name)
                scope_imports[item.scope_id][item.local_name] = target

        def aliases_for(scope_id: str | None) -> dict[str, str]:
            chain: list[str] = []
            while scope_id is not None:
                chain.append(scope_id)
                scope_id = scope_parent.get(scope_id)
            result: dict[str, str] = {}
            for item in reversed(chain):
                result.update(scope_imports[item])
            return result

        body_scopes = {
            scope.owner_symbol_id: scope.scope_id
            for scope in frontend.scopes if scope.owner_symbol_id
        }
        module_bindings = {
            symbol.name for symbol in frontend.symbols if symbol.scope_id == "scope:module"
        }
        module_bindings.update(scope_imports["scope:module"])

        # Projection of frontend.symbols rather than a second declaration walk.
        # A failed span/name correspondence is omitted rather than guessed.
        entries: list[tuple[ast.AST, Any, SymbolKind]] = []
        for definition in frontend.symbols:
            if definition.kind not in _FRONTEND_ADDRESSABLE_KINDS:
                continue
            node = ast_nodes.get((definition.span.start_line, definition.span.start_column, definition.name))
            if node is None:
                continue
            aliases = aliases_for(definition.scope_id)
            if isinstance(node, ast.ClassDef):
                kind = _kind(node, aliases)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                role = _property_role(node) if definition.kind in {"method", "constructor"} else None
                kind = (
                    SymbolKind.PROPERTY if role
                    else (SymbolKind.METHOD if definition.kind in {"method", "constructor"} else _kind(node, aliases))
                )
            else:
                value = getattr(node, "value", None)
                typed = (
                    isinstance(value, ast.Call)
                    and _resolved_name(value.func, aliases).split(".")[-1] == "TypedDict"
                )
                kind = (
                    SymbolKind.TYPED_DICT if typed
                    else (SymbolKind.CONSTANT if definition.name.isupper() else SymbolKind.VARIABLE)
                )
            entries.append((node, definition, kind))

        groups: dict[tuple[str, SymbolKind], list[tuple[ast.AST, Any]]] = defaultdict(list)
        for node, definition, kind in entries:
            groups[definition.qualified_name, kind].append((node, definition))
        groups[(module, SymbolKind.MODULE)].append((tree, None))

        monkey = {
            _name(target.value).split(".")[-1]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
            if isinstance(target, ast.Attribute)
        }

        facts: list[PythonSymbolFacts] = []
        for (qualified, kind), facets in groups.items():
            facets.sort(key=lambda item: (
                -1 if item[1] is None else item[1].definition_ordinal,
                getattr(item[0], "lineno", 0),
                getattr(item[0], "col_offset", 0),
            ))
            nodes = [item[0] for item in facets]
            definition = facets[0][1]
            definition_scope = definition.scope_id if definition is not None else "scope:module"
            aliases = aliases_for(definition_scope)
            decorators = tuple(
                value
                for node in nodes
                for value in getattr(node, "decorator_list", ())
                for value in (_render(value),)
            )
            classifier = ConfidenceClassifier(aliases)
            for node in nodes:
                classifier.visit(node)
            if len(nodes) > 1:
                classifier.reasons.add("rebound_binding")
            if any(_under_control_flow(node, parents) for node in nodes):
                classifier.reasons.add("conditional_binding")
            decorator_names = [
                _resolved_name(item, aliases)
                for node in nodes
                for item in getattr(node, "decorator_list", ())
            ]
            if any(
                value not in _SAFE_DECORATORS
                and value.rsplit(".", 1)[-1] not in {"setter", "getter", "deleter"}
                for value in decorator_names
            ):
                classifier.reasons.add("unknown_decorator")
            if any(
                qualified == module + "." + name or qualified.startswith(module + "." + name + ".")
                for name in monkey
            ):
                classifier.reasons.add("monkey_patch")

            frontend_notices = _notices_for_nodes(notices, nodes)
            # Nonfatal frontend evidence must lower confidence and stay attached.
            classifier.reasons.update(frontend_notices)

            signatures = [
                _signature(node)
                for node in nodes
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            signature = _public_signature(nodes, signatures)
            roles = [
                _property_role(node)
                for node in nodes
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _property_role(node)
            ]
            property_role = "property" if roles else None
            annotations: dict[str, Any] = {}
            if isinstance(nodes[0], ast.ClassDef):
                annotations["bases"] = [_render(base) for base in nodes[0].bases]
                fields = {
                    item.target.id: _render(item.annotation)
                    for item in nodes[0].body
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
                }
                if fields:
                    annotations["fields"] = dict(sorted(fields.items()))
                base_names = {_resolved_name(base, aliases).split(".")[-1] for base in nodes[0].bases}
                if "BaseModel" in base_names:
                    annotations["pydantic_model"] = True
                enum_families = base_names & {"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"}
                if enum_families:
                    annotations["enum_family"] = sorted(enum_families)[0]
            elif kind is SymbolKind.TYPED_DICT and isinstance(nodes[0], (ast.Assign, ast.AnnAssign)):
                call = getattr(nodes[0], "value", None)
                if isinstance(call, ast.Call):
                    fields_map: dict[str, str] = {}
                    if len(call.args) > 1 and isinstance(call.args[1], ast.Dict):
                        fields_map.update({
                            key.value: _render(value)
                            for key, value in zip(call.args[1].keys, call.args[1].values)
                            if isinstance(key, ast.Constant) and isinstance(key.value, str)
                        })
                    fields_map.update({
                        keyword.arg: _render(keyword.value)
                        for keyword in call.keywords
                        if keyword.arg not in {None, "total"}
                    })
                    if fields_map:
                        annotations["fields"] = dict(sorted(fields_map.items()))
                    for keyword in call.keywords:
                        if keyword.arg == "total":
                            annotations["total"] = _render(keyword.value)
            elif signatures:
                impl = signature.get("implementation", signature)
                annotations = {
                    item["name"]: item["annotation"]
                    for item in impl.get("parameters", ())
                    if item.get("annotation")
                }
                if impl.get("return"):
                    annotations["return"] = impl["return"]

            projection = (
                _projection(nodes[0]) if len(nodes) == 1
                else {
                    "_type": "LogicalBinding",
                    "facets": [_projection(node) for node in nodes],
                    "roles": roles,
                }
            )
            stable = stable_symbol_id(
                self.repository_id, "python", path, qualified, kind, namespace,
            )
            version = symbol_version_cid(
                stable, projection, signature, decorators, annotations,
                extractor_name=self.extractor_name,
                extractor_version=self.extractor_version,
                property_role=property_role,
            )
            facet_roles = [
                _property_role(node) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else None
                for node in nodes
            ]
            metadata = {
                "confidence_reasons": sorted(classifier.reasons),
                "frontend_notices": frontend_notices,
                "frontend_declarations": [
                    None if item is None else item.symbol_id for _, item in facets
                ],
                "facet_count": len(nodes),
                "facets": [
                    {"role": role, "version_evidence": _projection(node)}
                    for node, role in zip(nodes, facet_roles)
                ],
            }
            record = SymbolRecord(
                stable, version, self.repository_id, "python", path, qualified, kind,
                namespace, source_cid, _span(path, nodes[0]), classifier.confidence,
                signature, decorators, annotations, metadata, projection,
                self.extractor_name, self.extractor_version, property_role,
            )
            edges: list[DependencyEdge] = []
            for node, facet_definition in facets:
                body_scope = (
                    body_scopes.get(facet_definition.symbol_id, definition_scope)
                    if facet_definition is not None else "scope:module"
                )
                visitor = _FactsVisitor(
                    path, stable, node, aliases_for(body_scope), module_bindings,
                )
                visitor.visit(node)
                edges.extend(visitor.edges)
                if isinstance(node, ast.ClassDef):
                    for base in node.bases:
                        visitor.edge(
                            base, RelationType.INHERITS,
                            "lexical:" + (_resolved_name(base, aliases_for(body_scope)) or _name(base) or "<dynamic-base>"),
                            "class_base", "exact",
                        )
            facts.append(PythonSymbolFacts(
                record,
                projection,
                tuple(sorted({edge.edge_id: edge for edge in edges}.values(), key=lambda edge: edge.edge_id)),
                tuple(sorted(classifier.reasons)),
            ))
        return PythonSemanticAnalysis(
            path, source_cid,
            tuple(sorted(facts, key=lambda item: item.symbol.stable_id)),
        )


def analyze_python_source(
    source: str | bytes,
    path: str,
    repository_id: str,
    *,
    namespace: str | None = None,
) -> PythonSemanticAnalysis:
    return PythonSemanticAnalyzer(repository_id=repository_id, namespace=namespace).analyze(source, path)
