"""Symbol-local Python semantic extraction built on the shared frontend.

The shared :mod:`python_frontend` is the authority for parsing, lexical
scopes, and malformed-input diagnostics.  This module only adds the stable
semantic-index projection: it deliberately groups declarations which share a
logical binding, and never executes the source it examines.
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
_SAFE_DECORATORS = frozenset({"property", "staticmethod", "classmethod", "dataclass", "dataclasses.dataclass", "abstractmethod", "abc.abstractmethod", "override", "typing.override", "overload", "typing.overload"})
_NATIVE_ROOTS = frozenset({"ctypes", "cffi", "cython", "numpy.ctypeslib"})
_DYNAMIC = frozenset({"eval", "exec", "compile", "__import__", "importlib.import_module", "runpy.run_module", "runpy.run_path"})
_REFLECTION = frozenset({"getattr", "setattr", "delattr", "hasattr", "vars", "dir", "inspect.getmembers", "inspect.signature"})
_UNCONTROLLED = frozenset({"open", "subprocess.run", "subprocess.Popen", "os.system", "socket.socket", "requests.get", "requests.post"})


def _name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name): return node.id
    if isinstance(node, ast.Attribute):
        value = _name(node.value)
        return f"{value}.{node.attr}" if value else node.attr
    if isinstance(node, ast.Subscript): return (_name(node.value) or "<dynamic>") + "[]"
    if isinstance(node, ast.Call): return _name(node.func)
    return ""


def _render(node: ast.AST | None) -> str:
    """Render source syntax without normalising whitespace inside literals."""
    if node is None: return ""
    try: return ast.unparse(node)
    except (TypeError, ValueError, AttributeError): return type(node).__name__


def _module_name(path: str) -> str:
    parts = list(PurePosixPath(path.replace("\\", "/")).parts)
    if parts and parts[-1].endswith((".py", ".pyi")): parts[-1] = parts[-1].rsplit(".", 1)[0]
    if parts and parts[-1] == "__init__": parts.pop()
    return ".".join(parts) or "__main__"


def _span(path: str, node: ast.AST) -> SourceSpan:
    return SourceSpan(path, max(1, getattr(node, "lineno", 1)), max(0, getattr(node, "col_offset", 0)), max(1, getattr(node, "end_lineno", getattr(node, "lineno", 1))), max(0, getattr(node, "end_col_offset", getattr(node, "col_offset", 0))))


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
    args = node.args
    positional = [*args.posonlyargs, *args.args]
    defaults: list[ast.AST | None] = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    values: list[dict[str, Any]] = []
    for index, item in enumerate(positional):
        default = defaults[index]
        values.append({"name": item.arg, "kind": "positional_only" if index < len(args.posonlyargs) else "positional_or_keyword", "annotation": _render(item.annotation), "default": _render(default), "default_kind": "none" if default is None else type(default).__name__})
    if args.vararg: values.append({"name": args.vararg.arg, "kind": "var_positional", "annotation": _render(args.vararg.annotation), "default": "", "default_kind": "none"})
    for item, default in zip(args.kwonlyargs, args.kw_defaults): values.append({"name": item.arg, "kind": "keyword_only", "annotation": _render(item.annotation), "default": _render(default), "default_kind": "none" if default is None else type(default).__name__})
    if args.kwarg: values.append({"name": args.kwarg.arg, "kind": "var_keyword", "annotation": _render(args.kwarg.annotation), "default": "", "default_kind": "none"})
    return {"parameters": values, "return": _render(node.returns), "is_generator": any(isinstance(value, (ast.Yield, ast.YieldFrom)) for value in _own_nodes(node.body))}


def _own_nodes(nodes: Sequence[ast.AST]) -> Iterable[ast.AST]:
    """Yield nodes owned by a body, excluding nested callable/class bodies."""
    for node in nodes:
        yield node
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)): continue
            yield from _own_nodes((child,))


def _projection(node: ast.AST) -> Any:
    """A declaration's body projection excludes independently addressed children."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        # Nested definitions are their own logical symbols, not parent body text.
        clone = copy.copy(node)
        clone.body = [item for item in node.body if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        return normalize_ast(clone)
    if isinstance(node, ast.ClassDef):
        # Method bodies must not version the containing class; retain class fields
        # and member interfaces as evidence.
        body: list[ast.stmt] = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                body.append(ast.Expr(value=ast.Constant(value={"member": item.name, "signature": _signature(item), "decorators": [_render(x) for x in item.decorator_list]})))
            elif not isinstance(item, ast.ClassDef): body.append(item)
        clone = copy.copy(node)
        clone.body = body
        return normalize_ast(clone)
    if isinstance(node, ast.Module):
        return normalize_ast(ast.Module(body=[item for item in node.body if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))], type_ignores=node.type_ignores))
    return normalize_ast(node)


def _kind(node: ast.AST) -> SymbolKind:
    if isinstance(node, ast.AsyncFunctionDef): return SymbolKind.ASYNC_FUNCTION
    if isinstance(node, ast.FunctionDef): return SymbolKind.FUNCTION
    if isinstance(node, ast.ClassDef):
        bases = {_name(value).split(".")[-1] for value in node.bases}
        decorators = {_name(value).split(".")[-1] for value in node.decorator_list}
        if "TypedDict" in bases: return SymbolKind.TYPED_DICT
        if bases & {"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"}: return SymbolKind.ENUM
        if "dataclass" in decorators: return SymbolKind.DATACLASS
        return SymbolKind.CLASS
    return SymbolKind.VARIABLE


def _property_role(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    names = [_name(value) for value in node.decorator_list]
    if "property" in names: return "getter"
    for name in names:
        if name.endswith(".setter"): return "setter"
        if name.endswith(".deleter"): return "deleter"
        if name.endswith(".getter"): return "getter"
    return None


class ConfidenceClassifier(ast.NodeVisitor):
    def __init__(self, aliases: dict[str, str]) -> None: self.reasons: set[str] = set(); self.aliases = aliases
    @property
    def confidence(self) -> str:
        return classify_confidence(self.reasons)
    def visit_Call(self, node: ast.Call) -> None:
        name = self.aliases.get(_name(node.func), _name(node.func))
        if name in {"eval", "exec"}: self.reasons.add("eval_or_exec")
        elif name in _DYNAMIC: self.reasons.add("runtime_code_generation" if name == "compile" else "dynamic_import")
        elif name in _REFLECTION or name.endswith(".__setattr__") or name.endswith(".__getattribute__"):
            self.reasons.add("reflection")
            if len(node.args) < 2 or not isinstance(node.args[1], ast.Constant): self.reasons.add("constructed_attribute")
        elif name in _UNCONTROLLED: self.reasons.add("uncontrolled_effect")
        elif name.startswith("ctypes.") or name in {"CDLL", "PyDLL", "WinDLL"}: self.reasons.add("native_boundary")
        self.generic_visit(node)
    def visit_Import(self, node: ast.Import) -> None:
        if any(alias.name == root or alias.name.startswith(root + ".") for alias in node.names for root in _NATIVE_ROOTS): self.reasons.add("native_boundary")
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module and any(node.module == root or node.module.startswith(root + ".") for root in _NATIVE_ROOTS): self.reasons.add("native_boundary")
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if any(keyword.arg == "metaclass" for keyword in node.keywords): self.reasons.add("metaclass_mutation")
        self.generic_visit(node)


class _FactsVisitor(ast.NodeVisitor):
    def __init__(self, path: str, source_id: str, root: ast.AST, aliases: dict[str, str], module_bindings: set[str]) -> None:
        self.path, self.source_id, self.root, self.aliases, self.module_bindings = path, source_id, root, aliases, module_bindings
        self.edges: list[DependencyEdge] = []; self.globals: set[str] = set()
    def edge(self, node: ast.AST, relation: RelationType, target: str, method: str = "lexical", confidence: str = "conservative", **metadata: Any) -> None:
        self.edges.append(DependencyEdge(self.source_id, target, relation, method, confidence, EXTRACTOR_VERSION, _span(self.path, node), metadata))
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names: self.edge(node, RelationType.IMPORTS, "module:" + alias.name, "static_import", "exact", alias=alias.asname or alias.name.split(".")[0])
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = "." * node.level + (node.module or "")
        for alias in node.names: self.edge(node, RelationType.IMPORTS, "module:" + module + ("." if module else "") + alias.name, "static_import", "conservative" if alias.name == "*" else "exact", alias=alias.asname or alias.name)
    def visit_Call(self, node: ast.Call) -> None:
        raw = _name(node.func) or "<dynamic-call>"; name = self.aliases.get(raw, raw)
        native = name.startswith("ctypes.") or name in {"CDLL", "PyDLL", "WinDLL"}
        self.edge(node, RelationType.CALLS, "lexical:" + name, "lexical", "opaque" if native else "conservative", native_boundary=native)
        tail = name.rsplit(".", 1)[-1]
        target = "lexical:" + name
        if tail in {"dump", "dumps", "serialize", "to_dict", "to_json", "model_dump"}: self.edge(node, RelationType.SERIALIZES, target)
        if tail in {"load", "loads", "deserialize", "from_dict", "from_json", "model_validate_json"}: self.edge(node, RelationType.DESERIALIZES, target)
        if tail in {"validate", "validate_json", "parse_obj", "model_validate"}: self.edge(node, RelationType.VALIDATES, target)
        self.generic_visit(node)
    def visit_Raise(self, node: ast.Raise) -> None:
        self.edge(node, RelationType.RAISES, "exception:" + (_name(node.exc) or "<unknown>"), "direct_raise", "exact"); self.generic_visit(node)
    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        types = node.type.elts if isinstance(node.type, ast.Tuple) else (node.type,)
        for value in types: self.edge(value or node, RelationType.CATCHES, "exception:" + (_name(value) or "BaseException"), "direct_except", "exact")
        self.generic_visit(node)
    def visit_With(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items: self.edge(item.context_expr, RelationType.CALLS, "context:" + (_name(item.context_expr) or "<dynamic>"), "context_manager")
        self.generic_visit(node)
    visit_AsyncWith = visit_With
    def visit_Global(self, node: ast.Global) -> None: self.globals.update(node.names)
    def visit_Name(self, node: ast.Name) -> None:
        if node.id in self.globals or (node.id in self.module_bindings and self.root is not node):
            self.edge(node, RelationType.READS_STATE if isinstance(node.ctx, ast.Load) else RelationType.WRITES_STATE, "global:" + node.id, "global_binding", "exact")
    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        # Augmented assignment consumes the old binding before replacing it;
        # CPython's target context alone only exposes the write side.
        if isinstance(node.target, ast.Name) and (node.target.id in self.globals or node.target.id in self.module_bindings):
            self.edge(node.target, RelationType.READS_STATE, "global:" + node.target.id, "global_binding", "exact")
        self.generic_visit(node)
    def visit_Attribute(self, node: ast.Attribute) -> None:
        relation = RelationType.READS_STATE if isinstance(node.ctx, ast.Load) else RelationType.WRITES_STATE
        self.edge(node, relation, "state:" + (_name(node) or "<dynamic>"), "attribute_read" if relation == RelationType.READS_STATE else "attribute_write")
        self.generic_visit(node)
    def visit_Subscript(self, node: ast.Subscript) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.edge(node, RelationType.WRITES_STATE, "state:" + (_name(node.value) or "<dynamic>") + "[]", "subscript_write")
        self.generic_visit(node)
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.root: self.generic_visit(node)
    visit_AsyncFunctionDef = visit_FunctionDef
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node is self.root: self.generic_visit(node)


@dataclass(frozen=True, slots=True)
class PythonSymbolFacts:
    symbol: SymbolRecord
    normalized_ast: Any
    edges: tuple[DependencyEdge, ...]
    confidence_reasons: tuple[str, ...] = ()
    @property
    def confidence(self) -> str: return self.symbol.confidence


@dataclass(frozen=True, slots=True)
class PythonSemanticAnalysis:
    path: str; source_cid: str; symbols: tuple[PythonSymbolFacts, ...]; diagnostics: tuple[str, ...] = (); schema: str = PYTHON_SEMANTIC_ANALYSIS_SCHEMA
    @property
    def symbol_records(self) -> tuple[SymbolRecord, ...]: return tuple(item.symbol for item in self.symbols)
    @property
    def edges(self) -> tuple[DependencyEdge, ...]: return tuple(edge for item in self.symbols for edge in item.edges)


# Kept as an explicit v2 name for callers which distinguish the frontend's
# ASTRecord from this grouped semantic-index result.
PythonAnalysisResult = PythonSemanticAnalysis


def classify_confidence(reasons: Iterable[str]) -> str:
    """Classify already-observed source-bound uncertainty reasons."""
    values = set(reasons)
    if values & {"eval_or_exec", "reflection", "constructed_attribute", "native_boundary", "monkey_patch", "metaclass_mutation", "runtime_code_generation"}:
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
    def __init__(self, *, repository_id: str, namespace: str | None = None, extractor_name: str = DEFAULT_EXTRACTOR_NAME, extractor_version: str = DEFAULT_EXTRACTOR_VERSION) -> None:
        self.repository_id, self.namespace, self.extractor_name, self.extractor_version = repository_id, namespace, extractor_name, extractor_version
    def analyze(self, source: str | bytes, path: str) -> PythonSemanticAnalysis:
        raw = source.encode("utf-8") if isinstance(source, str) else source; source_cid = cid_for_bytes(raw)
        # The frontend is deliberately invoked first: its resource/encoding/parse
        # disposition is authoritative and its facts are retained as diagnostics.
        frontend = PythonASTExtractor().extract(raw, path=path, repository_id=self.repository_id)
        frontend_diagnostics = tuple(sorted({item.code for item in (*frontend.diagnostics, *frontend.unsupported)}))
        try: text = raw.decode("utf-8"); tree = ast.parse(text, filename=path, type_comments=True)
        except (UnicodeDecodeError, SyntaxError, ValueError): return PythonSemanticAnalysis(path, source_cid, (), frontend_diagnostics or ("parse_error",))
        module = _module_name(path); namespace = self.namespace or module.split(".")[0]
        aliases: dict[str, str] = {}
        module_bindings: set[str] = set()
        for item in tree.body:
            if isinstance(item, ast.Import):
                for alias in item.names: aliases[alias.asname or alias.name.split(".")[0]] = alias.name; module_bindings.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(item, ast.ImportFrom):
                for alias in item.names: aliases[alias.asname or alias.name] = (item.module + "." if item.module else "") + alias.name; module_bindings.add(alias.asname or alias.name)
            elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): module_bindings.add(item.name)
            elif isinstance(item, (ast.Assign, ast.AnnAssign)):
                for target in (item.targets if isinstance(item, ast.Assign) else [item.target]):
                    if isinstance(target, ast.Name): module_bindings.add(target.id)
        entries: list[tuple[ast.AST, str, SymbolKind, str]] = [(tree, module, SymbolKind.MODULE, "")]
        def collect(body: Sequence[ast.stmt], prefix: str, owner: str = "") -> None:
            for node in body:
                if isinstance(node, ast.ClassDef):
                    qualified = prefix + "." + node.name; entries.append((node, qualified, _kind(node), owner)); collect(node.body, qualified, "class")
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualified = prefix + "." + node.name; role = _property_role(node) if owner == "class" else None
                    entries.append((node, qualified, SymbolKind.PROPERTY if role else (SymbolKind.METHOD if owner == "class" else _kind(node)), owner))
                    collect(node.body, qualified, "function")
                elif isinstance(node, (ast.Assign, ast.AnnAssign)) and not owner:
                    for target in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                        if isinstance(target, ast.Name):
                            is_typed_dict = isinstance(getattr(node, "value", None), ast.Call) and _name(node.value.func).split(".")[-1] == "TypedDict"
                            entries.append((node, prefix + "." + target.id, SymbolKind.TYPED_DICT if is_typed_dict else (SymbolKind.CONSTANT if target.id.isupper() else SymbolKind.VARIABLE), owner))
                elif not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    # Definitions under if/try/with/match blocks are still real
                    # lexical bindings.  They are never silently dropped.
                    for child in ast.iter_child_nodes(node):
                        if isinstance(child, ast.stmt): collect((child,), prefix, owner)
        collect(tree.body, module)
        groups: dict[tuple[str, SymbolKind], list[tuple[ast.AST, str]]] = defaultdict(list)
        for node, qualified, kind, owner in entries: groups[qualified, kind].append((node, owner))
        monkey = {_name(target.value).split(".")[-1] for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign)) for target in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(target, ast.Attribute)}
        facts: list[PythonSymbolFacts] = []
        for (qualified, kind), facets in groups.items():
            nodes = [item[0] for item in facets]; decorators = tuple(value for node in nodes for value in getattr(node, "decorator_list", ()) for value in (_render(value),))
            classifier = ConfidenceClassifier(aliases)
            for node in nodes: classifier.visit(node)
            if any(value not in _SAFE_DECORATORS and value.rsplit(".", 1)[-1] not in {"setter", "getter", "deleter"} for value in (_name(item) for node in nodes for item in getattr(node, "decorator_list", ()) )): classifier.reasons.add("unknown_decorator")
            if any(qualified == module + "." + name or qualified.startswith(module + "." + name + ".") for name in monkey): classifier.reasons.add("monkey_patch")
            signatures = [_signature(node) for node in nodes if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
            signature: dict[str, Any] = signatures[-1] if signatures else {}
            roles = [_property_role(node) for node in nodes if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _property_role(node)]
            property_role = "property" if roles else None
            annotations: dict[str, Any] = {}
            if isinstance(nodes[0], ast.ClassDef):
                annotations["bases"] = [_render(base) for base in nodes[0].bases]
                fields = {item.target.id: _render(item.annotation) for item in nodes[0].body if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)}
                if fields: annotations["fields"] = dict(sorted(fields.items()))
                base_names = {_name(base).split(".")[-1] for base in nodes[0].bases}
                if "BaseModel" in base_names: annotations["pydantic_model"] = True
                enum_families = base_names & {"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"}
                if enum_families: annotations["enum_family"] = sorted(enum_families)[0]
            elif kind is SymbolKind.TYPED_DICT and isinstance(nodes[0], (ast.Assign, ast.AnnAssign)):
                call = getattr(nodes[0], "value", None)
                if isinstance(call, ast.Call) and len(call.args) > 1 and isinstance(call.args[1], ast.Dict):
                    annotations["fields"] = {key.value: _render(value) for key, value in zip(call.args[1].keys, call.args[1].values) if isinstance(key, ast.Constant) and isinstance(key.value, str)}
            elif signatures:
                annotations = {item["name"]: item["annotation"] for item in signature["parameters"] if item["annotation"]}
                if signature["return"]: annotations["return"] = signature["return"]
            projection = _projection(nodes[0]) if len(nodes) == 1 else {"_type": "LogicalBinding", "facets": [_projection(node) for node in nodes], "roles": roles}
            stable = stable_symbol_id(self.repository_id, "python", path, qualified, kind, namespace)
            version = symbol_version_cid(stable, projection, signature, decorators, annotations, extractor_name=self.extractor_name, extractor_version=self.extractor_version, property_role=property_role)
            metadata = {"confidence_reasons": sorted(classifier.reasons), "frontend_diagnostics": list(frontend_diagnostics), "facet_count": len(nodes), "facets": [{"role": role, "version_evidence": _projection(node)} for node, role in zip(nodes, roles or [None] * len(nodes))]}
            record = SymbolRecord(stable, version, self.repository_id, "python", path, qualified, kind, namespace, source_cid, _span(path, nodes[0]), classifier.confidence, signature, decorators, annotations, metadata, projection, self.extractor_name, self.extractor_version, property_role)
            edges: list[DependencyEdge] = []
            for node in nodes:
                visitor = _FactsVisitor(path, stable, node, aliases, module_bindings); visitor.visit(node); edges.extend(visitor.edges)
                if isinstance(node, ast.ClassDef):
                    for base in node.bases: visitor.edge(base, RelationType.INHERITS, "lexical:" + (_name(base) or "<dynamic-base>"), "class_base", "exact")
            facts.append(PythonSymbolFacts(record, projection, tuple(sorted({edge.edge_id: edge for edge in edges}.values(), key=lambda edge: edge.edge_id)), tuple(sorted(classifier.reasons))))
        return PythonSemanticAnalysis(path, source_cid, tuple(sorted(facts, key=lambda item: item.symbol.stable_id)), frontend_diagnostics)


def analyze_python_source(source: str | bytes, path: str, repository_id: str, *, namespace: str | None = None) -> PythonSemanticAnalysis:
    return PythonSemanticAnalyzer(repository_id=repository_id, namespace=namespace).analyze(source, path)
