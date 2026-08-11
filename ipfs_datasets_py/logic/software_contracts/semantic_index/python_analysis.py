"""Static, symbol-local Python semantic extraction.

This module deliberately uses only :mod:`ast`.  Its call and import facts are
lexical observations, not a claim that Python dispatch or import resolution is
complete.  When syntax exposes a construct whose runtime meaning cannot be
bounded, the affected symbol is marked ``opaque`` and the reason is retained.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable, Sequence

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_index.identity import (
    DEFAULT_EXTRACTOR_NAME,
    DEFAULT_EXTRACTOR_VERSION,
    normalize_ast,
    stable_symbol_id,
    symbol_version_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    DependencyEdge,
    RelationType,
    SourceSpan,
    SymbolKind,
    SymbolRecord,
)


PYTHON_SEMANTIC_ANALYSIS_SCHEMA = "ipfs-datasets.software-contracts.python-semantic-analysis@1"
EXTRACTOR_VERSION = "1"

_RANK = {"exact": 0, "conservative": 1, "heuristic": 2, "opaque": 3}
_SAFE_DECORATORS = {
    "property", "staticmethod", "classmethod", "dataclass", "dataclasses.dataclass",
    "abstractmethod", "abc.abstractmethod", "override", "typing.override",
}
_DYNAMIC_CALLS = {"eval", "exec", "compile", "__import__", "importlib.import_module", "runpy.run_module", "runpy.run_path"}
_REFLECTION_CALLS = {"getattr", "setattr", "delattr", "hasattr", "vars", "dir", "inspect.getmembers", "inspect.signature"}
_PLUGIN_CALLS = {"importlib.metadata.entry_points", "pkg_resources.iter_entry_points", "pluggy.PluginManager", "stevedore.ExtensionManager"}
_NATIVE_MODULES = {"ctypes", "cffi", "cython", "numpy.ctypeslib"}
_UNCONTROLLED_CALLS = {"open", "subprocess.run", "subprocess.Popen", "os.system", "socket.socket", "requests.get", "requests.post"}


def _name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Call):
        return _name(node.func)
    if isinstance(node, ast.Subscript):
        return _name(node.value) + "[]"
    return ""


def _render(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return " ".join(ast.unparse(node).split())
    except (ValueError, TypeError):
        return type(node).__name__


def _module_name(path: str) -> str:
    pure = PurePosixPath(path.replace("\\", "/"))
    parts = list(pure.parts)
    if parts and parts[-1].endswith((".py", ".pyi")):
        parts[-1] = parts[-1].rsplit(".", 1)[0]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or "__main__"


def _span(path: str, node: ast.AST) -> SourceSpan:
    return SourceSpan(path, max(1, getattr(node, "lineno", 1)), max(0, getattr(node, "col_offset", 0)), max(1, getattr(node, "end_lineno", getattr(node, "lineno", 1))), max(0, getattr(node, "end_col_offset", getattr(node, "col_offset", 0))))


def _confidence(values: Iterable[str]) -> str:
    return max(values, key=lambda item: _RANK[item], default="exact")


def _kind(node: ast.AST) -> SymbolKind:
    if isinstance(node, ast.AsyncFunctionDef):
        return SymbolKind.ASYNC_FUNCTION
    if isinstance(node, (ast.FunctionDef, ast.Lambda)):
        return SymbolKind.FUNCTION
    if isinstance(node, ast.ClassDef):
        bases = {_name(base).split(".")[-1] for base in node.bases}
        decorators = {_name(item) for item in node.decorator_list}
        if "TypedDict" in bases:
            return SymbolKind.TYPED_DICT
        if "Enum" in bases:
            return SymbolKind.ENUM
        if "dataclass" in decorators or "dataclass" in {name.split(".")[-1] for name in decorators}:
            return SymbolKind.DATACLASS
        return SymbolKind.CLASS
    return SymbolKind.VARIABLE


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
    args = node.args
    positional = list(args.posonlyargs) + list(args.args)
    defaults: list[ast.AST | None] = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    parameters = []
    for index, arg in enumerate(positional):
        parameters.append({"name": arg.arg, "kind": "positional_only" if index < len(args.posonlyargs) else "positional_or_keyword", "annotation": _render(arg.annotation), "default": _render(defaults[index]), "default_kind": "none" if defaults[index] is None else type(defaults[index]).__name__})
    if args.vararg:
        parameters.append({"name": args.vararg.arg, "kind": "var_positional", "annotation": _render(args.vararg.annotation), "default": "", "default_kind": "none"})
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        parameters.append({"name": arg.arg, "kind": "keyword_only", "annotation": _render(arg.annotation), "default": _render(default), "default_kind": "none" if default is None else type(default).__name__})
    if args.kwarg:
        parameters.append({"name": args.kwarg.arg, "kind": "var_keyword", "annotation": _render(args.kwarg.annotation), "default": "", "default_kind": "none"})
    return {"parameters": parameters, "return": _render(node.returns), "is_generator": any(isinstance(item, (ast.Yield, ast.YieldFrom)) for item in ast.walk(node))}


class ConfidenceClassifier(ast.NodeVisitor):
    """Classify dynamic constructs in one symbol body without executing it."""

    def __init__(self, root: ast.AST | None = None) -> None:
        self.reasons: set[str] = set()
        self.root = root

    @property
    def confidence(self) -> str:
        opaque = {"eval_or_exec", "runtime_code_generation", "reflection", "constructed_attribute", "plugin_discovery", "metaclass_mutation", "native_boundary", "monkey_patch"}
        if self.reasons & opaque:
            return "opaque"
        return "conservative" if self.reasons else "exact"

    def visit_Call(self, node: ast.Call) -> None:
        name = _name(node.func)
        if name in {"eval", "exec"}:
            self.reasons.add("eval_or_exec")
        elif name in _DYNAMIC_CALLS or name in {"type", "types.new_class"}:
            self.reasons.add("runtime_code_generation" if name in {"compile", "type", "types.new_class"} else "dynamic_import")
        elif name in _REFLECTION_CALLS or name.endswith(".__setattr__") or name.endswith(".__getattribute__"):
            self.reasons.add("reflection")
            if (name in {"getattr", "setattr", "delattr"} or name.endswith(".__setattr__") or name.endswith(".__getattribute__")) and (len(node.args) < 2 or not isinstance(node.args[1], ast.Constant)):
                self.reasons.add("constructed_attribute")
        elif name in _PLUGIN_CALLS:
            self.reasons.add("plugin_discovery")
        elif name in _UNCONTROLLED_CALLS:
            self.reasons.add("uncontrolled_effect")
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        if any(alias.name == item or alias.name.startswith(item + ".") for alias in node.names for item in _NATIVE_MODULES):
            self.reasons.add("native_boundary")

    visit_ImportFrom = visit_Import

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node is not self.root:
            return
        if any(keyword.arg == "metaclass" for keyword in node.keywords):
            self.reasons.add("metaclass_mutation")
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.root:
            self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef


class _FactsVisitor(ast.NodeVisitor):
    def __init__(self, path: str, source_id: str, root: ast.AST) -> None:
        self.path, self.source_id = path, source_id
        self.root = root
        self.edges: list[DependencyEdge] = []
        self.global_names: set[str] = set()

    def edge(self, node: ast.AST, relation: RelationType, target: str, method: str = "lexical", confidence: str = "conservative") -> None:
        self.edges.append(DependencyEdge(self.source_id, target, relation, method, confidence, EXTRACTOR_VERSION, _span(self.path, node)))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names: self.edge(node, RelationType.IMPORTS, "module:" + alias.name, "static_import", "exact")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = "." * node.level + (node.module or "")
        for alias in node.names: self.edge(node, RelationType.IMPORTS, "module:" + module + ("." if module else "") + alias.name, "static_import", "exact")

    def visit_Call(self, node: ast.Call) -> None:
        name = _name(node.func) or "<dynamic-call>"
        self.edge(node, RelationType.CALLS, "lexical:" + name)
        terminal = name.rsplit(".", 1)[-1]
        if terminal in {"dump", "dumps", "serialize", "to_dict", "to_json"}: self.edge(node, RelationType.SERIALIZES, "lexical:" + name)
        if terminal in {"load", "loads", "deserialize", "from_dict", "from_json"}: self.edge(node, RelationType.DESERIALIZES, "lexical:" + name)
        if terminal in {"validate", "validate_json", "parse_obj", "model_validate"}: self.edge(node, RelationType.VALIDATES, "lexical:" + name)
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        self.edge(node, RelationType.RAISES, "exception:" + (_name(node.exc) or "<unknown>"), "direct_raise", "exact")
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.edge(node, RelationType.CATCHES, "exception:" + (_name(node.type) or "BaseException"), "direct_except", "exact")
        self.generic_visit(node)

    def visit_With(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items: self.edge(item.context_expr, RelationType.CALLS, "context:" + (_name(item.context_expr) or "<dynamic>"), "context_manager")
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets: self._assignment(target, node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._assignment(node.target, node); self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._assignment(node.target, node); self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        self.global_names.update(node.names)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in self.global_names:
            relation = RelationType.READS_STATE if isinstance(node.ctx, ast.Load) else RelationType.WRITES_STATE
            self.edge(node, relation, "global:" + node.id, "global_binding", "exact")

    def _assignment(self, target: ast.AST, node: ast.AST) -> None:
        if isinstance(target, ast.Attribute):
            relation = RelationType.WRITES_STATE
            self.edge(node, relation, "state:" + (_name(target) or "<dynamic>"), "attribute_write")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, ast.Load): self.edge(node, RelationType.READS_STATE, "state:" + (_name(node) or "<dynamic>"), "attribute_read")
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node is self.root:
            self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.root:
            self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef


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
    """Deterministic result of analyzing one source file."""
    path: str
    source_cid: str
    symbols: tuple[PythonSymbolFacts, ...]
    diagnostics: tuple[str, ...] = ()
    schema: str = PYTHON_SEMANTIC_ANALYSIS_SCHEMA

    @property
    def symbol_records(self) -> tuple[SymbolRecord, ...]: return tuple(item.symbol for item in self.symbols)
    @property
    def edges(self) -> tuple[DependencyEdge, ...]: return tuple(edge for item in self.symbols for edge in item.edges)


class PythonSemanticAnalyzer:
    def __init__(self, *, repository_id: str, namespace: str | None = None, extractor_name: str = DEFAULT_EXTRACTOR_NAME, extractor_version: str = DEFAULT_EXTRACTOR_VERSION) -> None:
        self.repository_id, self.namespace = repository_id, namespace
        self.extractor_name, self.extractor_version = extractor_name, extractor_version

    def analyze(self, source: str | bytes, path: str) -> PythonSemanticAnalysis:
        raw = source.encode("utf-8") if isinstance(source, str) else source
        source_cid = cid_for_bytes(raw)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return PythonSemanticAnalysis(path, source_cid, (), ("decode_error:utf8",))
        try:
            tree = ast.parse(text, filename=path, type_comments=True)
        except (SyntaxError, ValueError) as exc:
            return PythonSemanticAnalysis(path, source_cid, (), (f"parse_error:{exc.__class__.__name__}",))
        module = _module_name(path)
        namespace = self.namespace or module.split(".")[0]
        entries: list[tuple[ast.AST, str, SymbolKind, str]] = [(tree, module, SymbolKind.MODULE, "")]
        def collect(body: Sequence[ast.stmt], prefix: str, owner: str = "") -> None:
            for node in body:
                if isinstance(node, ast.ClassDef):
                    qualified = prefix + "." + node.name
                    entries.append((node, qualified, _kind(node), owner))
                    collect(node.body, qualified, "class")
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualified = prefix + "." + node.name
                    kind = SymbolKind.METHOD if owner == "class" else _kind(node)
                    if owner == "class" and any(_name(decorator) == "property" for decorator in node.decorator_list): kind = SymbolKind.PROPERTY
                    entries.append((node, qualified, kind, owner))
                elif isinstance(node, (ast.Assign, ast.AnnAssign)) and not owner:
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if isinstance(target, ast.Name): entries.append((node, prefix + "." + target.id, SymbolKind.CONSTANT if target.id.isupper() else SymbolKind.VARIABLE, owner))
        collect(tree.body, module)
        facts: list[PythonSymbolFacts] = []
        monkey_targets: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Attribute):
                        owner = _name(target.value).split(".")[-1]
                        if owner:
                            monkey_targets.add(owner)
        for node, qualified, kind, owner in entries:
            decorators = tuple(sorted(_render(item) for item in getattr(node, "decorator_list", ())))
            classifier = ConfidenceClassifier(node); classifier.visit(node)
            if any(item not in _SAFE_DECORATORS and item.split(".")[-1] not in {"setter", "getter", "deleter"} for item in decorators): classifier.reasons.add("unknown_decorator")
            if any(qualified == module + "." + target or qualified.startswith(module + "." + target + ".") for target in monkey_targets): classifier.reasons.add("monkey_patch")
            sig = _signature(node) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else {}
            annotations: dict[str, Any] = {}
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                annotations = {item["name"]: item["annotation"] for item in sig["parameters"] if item["annotation"]}
                if sig["return"]: annotations["return"] = sig["return"]
            if isinstance(node, ast.ClassDef):
                annotations["bases"] = [_render(base) for base in node.bases]
                fields = {}
                for statement in node.body:
                    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                        fields[statement.target.id] = _render(statement.annotation)
                if fields:
                    annotations["fields"] = dict(sorted(fields.items()))
            stable = stable_symbol_id(self.repository_id, "python", path, qualified, kind, namespace)
            role = "property" if kind is SymbolKind.PROPERTY else None
            version = symbol_version_cid(stable, node, sig, decorators, annotations, extractor_name=self.extractor_name, extractor_version=self.extractor_version, property_role=role)
            record = SymbolRecord(stable, version, self.repository_id, "python", path, qualified, kind, namespace, source_cid, _span(path, node), classifier.confidence, sig, decorators, annotations, {"confidence_reasons": sorted(classifier.reasons), "property_role": role})
            visitor = _FactsVisitor(path, stable, node); visitor.visit(node)
            if isinstance(node, ast.ClassDef):
                for base in node.bases: visitor.edge(base, RelationType.INHERITS, "lexical:" + (_name(base) or "<dynamic-base>"), "class_base", "exact")
            facts.append(PythonSymbolFacts(record, normalize_ast(node), tuple(sorted(visitor.edges, key=lambda edge: edge.edge_id)), tuple(sorted(classifier.reasons))))
        return PythonSemanticAnalysis(path, source_cid, tuple(sorted(facts, key=lambda item: item.symbol.stable_id)))


def analyze_python_source(source: str | bytes, path: str, repository_id: str, *, namespace: str | None = None) -> PythonSemanticAnalysis:
    """Analyze source without importing or executing the target module."""
    return PythonSemanticAnalyzer(repository_id=repository_id, namespace=namespace).analyze(source, path)
