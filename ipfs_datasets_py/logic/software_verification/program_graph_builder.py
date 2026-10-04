"""Deterministic static program-graph construction and invalidation.

This module owns datasets ``sawm/program-graph-build@1`` construction.  It
projects admitted Python source units onto the SAWM-005
``ProgramGraphSnapshot@1`` family (AST, symbol, import, call, CFG, data-flow,
exception, type/effect, contract, test, and proof) and computes exact deltas
plus dependency-aware invalidation.

Normative rules:

* Construction binds exact source bytes and environment/sealed binding CIDs.
* Node/edge identity is content-addressed; repeated builds are bit-identical.
* Logical cycles (CFG back-edges, cyclic imports, mutual recursion) are
  immutable records; the physical CID graph stays acyclic.
* Unknown dynamic behavior (eval/exec, reflection, native calls, unresolved
  callees) widens an explicit frontier and never becomes absence.
* Incremental rebuilds of unchanged units must match a full rebuild.
* Invalidation follows dependency edges and never omits a dependent; unrelated
  subroots stay retained.
* Importing this module performs no repository scan, network, subprocess,
  socket, or filesystem walk.
"""

from __future__ import annotations

import ast
import builtins
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.python_frontend import PythonASTExtractor
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_graph import (
    CALLSITE_RECORD_SCHEMA,
    CONTRACT_STATE_RECORD_SCHEMA,
    DYNAMIC_FRONTIER_RECORD_SCHEMA,
    FUNCTION_SYMBOL_RECORD_SCHEMA,
    PROGRAM_GRAPH_DELTA_SCHEMA,
    PROGRAM_GRAPH_EDGE_SCHEMA,
    PROGRAM_GRAPH_NODE_SCHEMA,
    PROGRAM_GRAPH_SNAPSHOT_SCHEMA,
    PROOF_OBLIGATION_GRAPH_SCHEMA,
    STATIC_SUCCESSOR_SET_SCHEMA,
    CallsiteRecord,
    ContractKind,
    ContractStateRecord,
    DynamicFrontierReason,
    DynamicFrontierRecord,
    FunctionSymbolRecord,
    ProgramGraphDelta,
    ProgramGraphEdge,
    ProgramGraphEdgeKind,
    ProgramGraphError,
    ProgramGraphIndexKind,
    ProgramGraphIndexManifest,
    ProgramGraphNode,
    ProgramGraphNodeKind,
    ProgramGraphSnapshot,
    ProgramLanguage,
    ProofObligationGraph,
    ResolutionStatus,
    StaticSuccessorSet,
    assemble_program_graph_snapshot,
    bind_index_manifest,
    delta_between_snapshots,
    directed_logical_cycles,
    is_unresolved_dynamic_edge,
    is_unresolved_dynamic_node,
    program_graph_cid_for,
    verify_program_graph_catalog,
)


PROGRAM_GRAPH_BUILDER_INTERFACE: Final[str] = "ProgramGraphBuilder@1"
PROGRAM_GRAPH_BUILD_RECEIPT_INTERFACE: Final[str] = "ProgramGraphBuildReceipt@1"
PROGRAM_GRAPH_INVALIDATION_PLANNER_INTERFACE: Final[str] = (
    "ProgramGraphInvalidationPlanner@1"
)
PROGRAM_GRAPH_BUILDER_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-graph-builder@1"
)
PROGRAM_GRAPH_BUILD_RECEIPT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-graph-build-receipt@1"
)
PROGRAM_GRAPH_INVALIDATION_PLAN_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-graph-invalidation-plan@1"
)
PROGRAM_GRAPH_SOURCE_UNIT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-graph-source-unit@1"
)
PROGRAM_GRAPH_DECLARATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-graph-declaration@1"
)
PROGRAM_GRAPH_ENVIRONMENT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-graph-builder.environment@1"
)
PROGRAM_GRAPH_SEALED_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-graph-builder.sealed-binding@1"
)

GRAPH_PROJECTIONS: Final[tuple[str, ...]] = (
    "ast",
    "symbol",
    "import",
    "call",
    "cfg",
    "data_flow",
    "exception",
    "type",
    "effect",
    "contract",
    "test",
    "proof",
)

_PYTHON_SUFFIXES: Final[tuple[str, ...]] = (".py", ".pyi")
_BUILTIN_NAMES: Final[frozenset[str]] = frozenset(dir(builtins)) | frozenset(
    {"self", "cls", "super", "NotImplemented", "Ellipsis"}
)
_DYNAMIC_CALLS: Final[frozenset[str]] = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "importlib.import_module",
        "runpy.run_module",
        "runpy.run_path",
        "builtins.eval",
        "builtins.exec",
        "builtins.compile",
        "builtins.__import__",
    }
)
_REFLECTION_CALLS: Final[frozenset[str]] = frozenset(
    {
        "getattr",
        "setattr",
        "delattr",
        "hasattr",
        "vars",
        "dir",
        "globals",
        "locals",
        "inspect.getmembers",
        "inspect.signature",
        "builtins.getattr",
        "builtins.setattr",
        "builtins.delattr",
        "builtins.hasattr",
        "builtins.vars",
        "builtins.dir",
    }
)
_NATIVE_CALLS: Final[frozenset[str]] = frozenset(
    {
        "CDLL",
        "PyDLL",
        "WinDLL",
        "cdll",
        "pydll",
        "windll",
        "ctypes.CDLL",
        "ctypes.PyDLL",
        "ctypes.WinDLL",
        "ctypes.cdll",
        "ctypes.pydll",
        "ctypes.windll",
    }
)
_NATIVE_ROOTS: Final[frozenset[str]] = frozenset(
    {"ctypes", "cffi", "cython", "numpy.ctypeslib"}
)
_PLUGIN_CALLS: Final[frozenset[str]] = frozenset(
    {
        "importlib.metadata.entry_points",
        "importlib_metadata.entry_points",
    }
)
_EFFECT_CALLS: Final[frozenset[str]] = frozenset(
    {
        "open",
        "builtins.open",
        "os.system",
        "os.popen",
        "subprocess.run",
        "subprocess.Popen",
        "subprocess.call",
        "socket.socket",
        "requests.get",
        "requests.post",
    }
)
_TEST_DECORATOR_TAILS: Final[frozenset[str]] = frozenset(
    {"fixture", "mark", "parametrize", "usefixtures"}
)
_CONTRACT_PREFIXES: Final[tuple[tuple[str, str], ...]] = (
    ("requires:", ContractKind.PRECONDITION.value),
    ("require:", ContractKind.PRECONDITION.value),
    ("precondition:", ContractKind.PRECONDITION.value),
    ("pre:", ContractKind.PRECONDITION.value),
    ("ensures:", ContractKind.POSTCONDITION.value),
    ("ensure:", ContractKind.POSTCONDITION.value),
    ("postcondition:", ContractKind.POSTCONDITION.value),
    ("post:", ContractKind.POSTCONDITION.value),
    ("invariant:", ContractKind.INVARIANT.value),
    ("raises:", ContractKind.EXCEPTIONAL.value),
    ("frame:", ContractKind.FRAME.value),
)

_RERUN_FORWARD_KINDS: Final[frozenset[str]] = frozenset(
    {
        ProgramGraphEdgeKind.TESTED_BY.value,
        ProgramGraphEdgeKind.PROVED_BY.value,
        ProgramGraphEdgeKind.USES_FIXTURE.value,
    }
)
_REVERSE_INVALIDATION_KINDS: Final[frozenset[str]] = frozenset(
    {
        ProgramGraphEdgeKind.IMPORTS.value,
        ProgramGraphEdgeKind.CYCLIC_IMPORT.value,
        ProgramGraphEdgeKind.SUCCESSOR.value,
        ProgramGraphEdgeKind.MUTUAL_RECURSION.value,
        ProgramGraphEdgeKind.INHERITS.value,
        ProgramGraphEdgeKind.IMPLEMENTS.value,
        ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value,
    }
)


class ProgramGraphBuilderError(ProgramGraphError):
    """Raised when static graph construction inputs or outputs fail closed."""


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProgramGraphBuilderError(
            f"{name} must be a nonempty trimmed string"
        )
    if "\x00" in value:
        raise ProgramGraphBuilderError(f"{name} must not contain NUL bytes")
    return value


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise ProgramGraphBuilderError(f"{name} must be a boolean")
    return value


def _cid_or_none(value: object, name: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value:
        raise ProgramGraphBuilderError(f"{name} must be a CID string")
    return value


def _normalize_path(path: object) -> str:
    text = _text(path, "path").replace("\\", "/")
    if text.startswith("/") or text.startswith("../") or text == "..":
        raise ProgramGraphBuilderError("path must be repository-relative")
    pure = PurePosixPath(text)
    if pure.is_absolute() or ".." in pure.parts:
        raise ProgramGraphBuilderError("path must be repository-relative")
    normalized = str(pure)
    if normalized in {".", ""}:
        raise ProgramGraphBuilderError("path must be a nonempty relative file path")
    return normalized


def _module_name(path: str, explicit: str | None = None) -> str:
    if explicit is not None:
        return _text(explicit, "module_name")
    parts = list(PurePosixPath(path).parts)
    if parts and parts[-1].endswith(_PYTHON_SUFFIXES):
        name = parts[-1]
        suffix = ".pyi" if name.endswith(".pyi") else ".py"
        parts[-1] = name[: -len(suffix)]
    if parts and parts[-1] == "__init__":
        parts.pop()
    cleaned = [part.replace(" ", "_") for part in parts if part not in {".", ""}]
    return ".".join(cleaned) or "__main__"


def _is_python_path(path: str) -> bool:
    return path.endswith(_PYTHON_SUFFIXES)


def _is_init_path(path: str) -> bool:
    return PurePosixPath(path).name in {"__init__.py", "__init__.pyi"}


def _source_bytes(source: object) -> bytes:
    if type(source) is str:
        try:
            return source.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ProgramGraphBuilderError(
                "source must be strict UTF-8 text"
            ) from exc
    if type(source) is bytes:
        return source
    raise ProgramGraphBuilderError("source must be text or UTF-8 bytes")


def _source_text(source: object) -> str:
    if type(source) is str:
        return source
    if type(source) is bytes:
        try:
            return source.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProgramGraphBuilderError(
                "source bytes must be strict UTF-8"
            ) from exc
    raise ProgramGraphBuilderError("source must be text or UTF-8 bytes")


def _expr_name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _expr_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Subscript):
        base = _expr_name(node.value)
        return f"{base}[]" if base else "subscript"
    if isinstance(node, ast.Call):
        return _expr_name(node.func)
    return ""


def _simple_name(name: str) -> str:
    return name.rsplit(".", 1)[-1] if name else ""


def _render(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return " ".join(ast.unparse(node).split())
    except (AttributeError, TypeError, ValueError):
        return type(node).__name__


def _store_names(target: ast.AST | None) -> tuple[str, ...]:
    names: list[str] = []

    def walk(node: ast.AST | None) -> None:
        if node is None:
            return
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Starred):
            walk(node.value)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for item in node.elts:
                walk(item)

    walk(target)
    return tuple(names)


def _loaded_names(node: ast.AST | None) -> tuple[str, ...]:
    if node is None:
        return ()
    names: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            names.append(child.id)
    return tuple(dict.fromkeys(names))


def _lineno(node: ast.AST | None) -> int:
    if node is None:
        return 1
    return max(1, int(getattr(node, "lineno", 1) or 1))


def _docstring(node: ast.AST) -> str:
    body = getattr(node, "body", None)
    if not body:
        return ""
    first = body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and type(first.value.value) is str
    ):
        return first.value.value
    return ""


def _decorator_names(node: ast.AST) -> tuple[str, ...]:
    names: list[str] = []
    for item in getattr(node, "decorator_list", ()):
        rendered = _expr_name(item) or _render(item)
        if rendered:
            names.append(rendered)
    return tuple(names)


def _is_test_function(name: str, decorators: Sequence[str], path: str) -> bool:
    if name.startswith("test_") or name.endswith("_test"):
        return True
    filename = PurePosixPath(path).name
    if filename.startswith("test_") or filename.endswith("_test.py"):
        if name.startswith("test"):
            return True
    for decorator in decorators:
        simple = _simple_name(decorator)
        if simple in _TEST_DECORATOR_TAILS or "pytest.mark" in decorator:
            return True
    return False


def _is_fixture(decorators: Sequence[str]) -> bool:
    return any(
        _simple_name(item) == "fixture" or item.endswith(".fixture")
        for item in decorators
    )


def _is_test_class(name: str) -> bool:
    return name.startswith("Test") and name != "Test"


def _doc_contracts(doc: str) -> tuple[tuple[str, str], ...]:
    found: list[tuple[str, str]] = []
    for raw in doc.splitlines():
        line = raw.strip()
        if not line:
            continue
        lowered = line.lower()
        for prefix, kind in _CONTRACT_PREFIXES:
            if lowered.startswith(prefix):
                body = line[len(prefix) :].strip() or prefix[:-1]
                found.append((kind, body))
                break
    return tuple(found)


def _future_reason(name: str, call: ast.Call) -> str | None:
    simple = _simple_name(name)
    if name in {"eval", "exec"} or simple in {"eval", "exec"}:
        return DynamicFrontierReason.EVAL.value if simple == "eval" else DynamicFrontierReason.EXEC.value
    if name in _DYNAMIC_CALLS or simple in {"eval", "exec", "compile", "__import__"}:
        if simple == "exec":
            return DynamicFrontierReason.EXEC.value
        if simple == "eval":
            return DynamicFrontierReason.EVAL.value
        if simple == "__import__" or "importlib" in name or name.startswith("runpy."):
            return DynamicFrontierReason.IMPORT_HOOK.value
        return DynamicFrontierReason.EVAL.value
    if name in _REFLECTION_CALLS or simple in _REFLECTION_CALLS:
        return DynamicFrontierReason.REFLECTION.value
    if (
        name in _NATIVE_CALLS
        or simple in _NATIVE_CALLS
        or name.startswith("ctypes.")
        or any(name == root or name.startswith(root + ".") for root in _NATIVE_ROOTS)
    ):
        return DynamicFrontierReason.NATIVE_CALL.value
    if name in _PLUGIN_CALLS or (
        simple == "entry_points" and "importlib" in name and "metadata" in name
    ):
        return DynamicFrontierReason.PLUGIN.value
    if simple == "type" and len(getattr(call, "args", ())) >= 3:
        return DynamicFrontierReason.DYNAMIC_DISPATCH.value
    if isinstance(call.func, ast.Attribute) and not _expr_name(call.func.value):
        return DynamicFrontierReason.DYNAMIC_DISPATCH.value
    if isinstance(call.func, ast.Subscript):
        return DynamicFrontierReason.DYNAMIC_DISPATCH.value
    if not name:
        return DynamicFrontierReason.UNKNOWN_CALLEE.value
    return None


def _default_environment_binding_set_cid() -> str:
    return cid_for_structured(
        {
            "schema": PROGRAM_GRAPH_ENVIRONMENT_SCHEMA,
            "language": ProgramLanguage.PYTHON.value,
            "profile": "admitted-python-v1",
        }
    )


def _default_sealed_binding_cid(environment_binding_set_cid: str) -> str:
    return cid_for_structured(
        {
            "schema": PROGRAM_GRAPH_SEALED_BINDING_SCHEMA,
            "environment_binding_set_cid": environment_binding_set_cid,
        }
    )


def _declaration_cid(
    *,
    kind: str,
    name: str,
    path: str,
    source_cid: str,
    start_line: int,
) -> str:
    return cid_for_structured(
        {
            "schema": PROGRAM_GRAPH_DECLARATION_SCHEMA,
            "kind": kind,
            "name": name,
            "path": path,
            "source_cid": source_cid,
            "start_line": start_line,
        }
    )


def _metadata(**values: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            continue
        if type(value) is tuple:
            payload[key] = list(value)
        else:
            payload[key] = value
    return payload


def _qualified(module_name: str, *parts: str) -> str:
    items = [module_name, *[part for part in parts if part]]
    return ".".join(item for item in items if item)


def _package_of(path: str, module_name: str) -> tuple[str, ...]:
    if _is_init_path(path):
        return tuple(part for part in module_name.split(".") if part)
    parts = [part for part in module_name.split(".") if part]
    return tuple(parts[:-1])


def _absolute_import(
    package_parts: Sequence[str],
    level: int,
    module: str | None,
) -> str | None:
    if level < 0:
        return None
    if level == 0:
        return module or None
    if level - 1 > len(package_parts):
        return None
    prefix_parts = list(package_parts[: len(package_parts) - (level - 1)])
    if not prefix_parts and level > 1:
        return None
    prefix = ".".join(prefix_parts)
    if module:
        return f"{prefix}.{module}" if prefix else module
    return prefix or None


def _seal_logical_cycles(
    edges: Mapping[str, ProgramGraphEdge],
) -> dict[str, ProgramGraphEdge]:
    """Ensure every directed logical cycle cites an immutable cycle record."""

    updated = dict(edges)
    for _ in range(len(updated) + 1):
        items = tuple(updated.values())
        cycles = directed_logical_cycles(items)
        by_cid = {edge.program_graph_edge_cid: edge for edge in items}
        pending: list[ProgramGraphEdge] = []
        for cycle in cycles:
            if any(by_cid[cid].logical_cycle for cid in cycle):
                continue
            preferred = None
            for cid in cycle:
                kind = str(by_cid[cid].edge_kind)
                if kind in {
                    ProgramGraphEdgeKind.SUCCESSOR.value,
                    ProgramGraphEdgeKind.CFG_NEXT.value,
                    ProgramGraphEdgeKind.CFG_BRANCH.value,
                    ProgramGraphEdgeKind.INHERITS.value,
                }:
                    preferred = by_cid[cid]
                    break
            pending.append(preferred or by_cid[cycle[0]])
        if not pending:
            return updated
        for edge in pending:
            replacement = ProgramGraphEdge(
                edge_kind=edge.edge_kind,
                source_node_cid=edge.source_node_cid,
                target_node_cid=edge.target_node_cid,
                language=edge.language,
                environment_binding_cid=edge.environment_binding_cid,
                resolution_status=edge.resolution_status,
                logical_cycle=True,
                unavailable_dimensions=edge.unavailable_dimensions,
                metadata=dict(edge.metadata),
            )
            updated.pop(edge.program_graph_edge_cid, None)
            updated[replacement.program_graph_edge_cid] = replacement
    raise ProgramGraphBuilderError("logical cycles could not be sealed")


def _strongly_connected(nodes: Sequence[str], edges: Sequence[tuple[str, str]]) -> tuple[tuple[str, ...], ...]:
    adjacency: dict[str, list[str]] = {node: [] for node in nodes}
    for source, target in edges:
        if source in adjacency and target in adjacency:
            adjacency[source].append(target)
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    components: list[tuple[str, ...]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlink[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for nxt in adjacency[node]:
            if nxt not in indices:
                strongconnect(nxt)
                lowlink[node] = min(lowlink[node], lowlink[nxt])
            elif nxt in on_stack:
                lowlink[node] = min(lowlink[node], indices[nxt])
        if lowlink[node] == indices[node]:
            component: list[str] = []
            while True:
                item = stack.pop()
                on_stack.remove(item)
                component.append(item)
                if item == node:
                    break
            components.append(tuple(sorted(component)))

    for node in nodes:
        if node not in indices:
            strongconnect(node)
    return tuple(sorted(components))


@dataclass(frozen=True, slots=True)
class ProgramGraphSourceUnit:
    """Explicit source unit; construction never discovers files by scan."""

    path: str
    source: str | bytes
    language: str = ProgramLanguage.PYTHON.value
    module_name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _normalize_path(self.path))
        language = (
            self.language.value
            if isinstance(self.language, ProgramLanguage)
            else _text(self.language, "language")
        )
        if language != ProgramLanguage.PYTHON.value:
            raise ProgramGraphBuilderError(
                f"language {language!r} is typed unavailable in this profile"
            )
        object.__setattr__(self, "language", language)
        object.__setattr__(
            self, "module_name", _optional_text(self.module_name, "module_name")
        )
        if not _is_python_path(self.path):
            raise ProgramGraphBuilderError(
                "initial builder supports the admitted Python profile only"
            )
        _source_bytes(self.source)

    @property
    def resolved_module_name(self) -> str:
        return _module_name(self.path, self.module_name)

    @property
    def source_bytes(self) -> bytes:
        return _source_bytes(self.source)

    @property
    def source_text(self) -> str:
        return _source_text(self.source)

    @property
    def source_cid(self) -> str:
        return cid_for_bytes(self.source_bytes)


@dataclass(frozen=True, slots=True)
class ProgramGraphCallFact:
    caller_logical_name: str
    callee_logical_name: str
    ordinal: int
    start_line: int
    intrinsic_reason: str | None = None
    call_kind: str = "direct"


@dataclass(frozen=True, slots=True)
class ProgramGraphImportFact:
    module: str
    imported_name: str | None
    local_name: str | None
    level: int
    start_line: int
    dynamic: bool = False


@dataclass(frozen=True, slots=True)
class ProgramGraphUnitFacts:
    path: str
    module_name: str
    source_cid: str
    parse_error: bool
    functions: tuple[str, ...]
    classes: tuple[str, ...]
    imports: tuple[ProgramGraphImportFact, ...]
    calls: tuple[ProgramGraphCallFact, ...]
    tests: tuple[str, ...]
    fixtures: tuple[str, ...]
    bases: tuple[tuple[str, str], ...]
    aliases: tuple[tuple[str, str], ...]
    incomplete_dimensions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProgramGraphUnitCatalog:
    """Unit-local records that do not depend on other source units."""

    facts: ProgramGraphUnitFacts
    nodes: tuple[ProgramGraphNode, ...]
    edges: tuple[ProgramGraphEdge, ...]
    callsites: tuple[CallsiteRecord, ...]
    function_symbols: tuple[FunctionSymbolRecord, ...]
    contract_states: tuple[ContractStateRecord, ...]
    proof_obligation_graphs: tuple[ProofObligationGraph, ...]


@dataclass(frozen=True, slots=True)
class ProgramGraphBuildReceipt:
    """Coverage receipt for one deterministic static graph construction."""

    snapshot: ProgramGraphSnapshot
    nodes: tuple[ProgramGraphNode, ...]
    edges: tuple[ProgramGraphEdge, ...]
    callsites: tuple[CallsiteRecord, ...]
    function_symbols: tuple[FunctionSymbolRecord, ...]
    contract_states: tuple[ContractStateRecord, ...]
    proof_obligation_graphs: tuple[ProofObligationGraph, ...]
    successor_sets: tuple[StaticSuccessorSet, ...]
    frontiers: tuple[DynamicFrontierRecord, ...]
    index_manifest: ProgramGraphIndexManifest
    unit_catalogs: tuple[ProgramGraphUnitCatalog, ...]
    coverage: tuple[tuple[str, int], ...]
    incomplete_dimensions: tuple[str, ...]
    incremental: bool
    environment_binding_set_cid: str
    sealed_binding_cid: str

    SCHEMA: Final[str] = PROGRAM_GRAPH_BUILD_RECEIPT_SCHEMA
    INTERFACE: Final[str] = PROGRAM_GRAPH_BUILD_RECEIPT_INTERFACE

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "snapshot_cid": self.snapshot.program_graph_snapshot_cid,
            "canonical_program_graph_cid": self.snapshot.canonical_program_graph_cid,
            "environment_binding_set_cid": self.environment_binding_set_cid,
            "sealed_binding_cid": self.sealed_binding_cid,
            "node_cids": list(self.snapshot.node_cids),
            "edge_cids": list(self.snapshot.edge_cids),
            "coverage": [[name, count] for name, count in self.coverage],
            "incomplete_dimensions": list(self.incomplete_dimensions),
            "incremental": self.incremental,
            "unit_source_cids": [
                [item.facts.path, item.facts.source_cid] for item in self.unit_catalogs
            ],
        }

    @property
    def program_graph_build_receipt_cid(self) -> str:
        return program_graph_cid_for(self.identity_payload())

    def node_by_logical_name(
        self, logical_name: str, kind: str | None = None
    ) -> ProgramGraphNode | None:
        matches = [
            node
            for node in self.nodes
            if node.logical_name == logical_name
            and (kind is None or str(node.node_kind) == kind)
        ]
        return matches[0] if len(matches) == 1 else None

    def nodes_of_kind(self, kind: str) -> tuple[ProgramGraphNode, ...]:
        return tuple(node for node in self.nodes if str(node.node_kind) == kind)

    def edges_of_kind(self, kind: str) -> tuple[ProgramGraphEdge, ...]:
        return tuple(edge for edge in self.edges if str(edge.edge_kind) == kind)


@dataclass(frozen=True, slots=True)
class ProgramGraphInvalidationPlan:
    """Dependency-aware invalidation; dependents are never omitted."""

    previous_snapshot_cid: str
    current_snapshot_cid: str | None
    delta_cid: str | None
    invalidated_node_cids: tuple[str, ...]
    invalidated_edge_cids: tuple[str, ...]
    retained_subroot_cids: tuple[str, ...]
    affected_node_cids: tuple[str, ...]
    full_fallback: bool
    reasons: tuple[str, ...]
    environment_changed: bool

    SCHEMA: Final[str] = PROGRAM_GRAPH_INVALIDATION_PLAN_SCHEMA
    INTERFACE: Final[str] = PROGRAM_GRAPH_INVALIDATION_PLANNER_INTERFACE

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "previous_snapshot_cid": self.previous_snapshot_cid,
            "current_snapshot_cid": self.current_snapshot_cid,
            "delta_cid": self.delta_cid,
            "invalidated_node_cids": list(self.invalidated_node_cids),
            "invalidated_edge_cids": list(self.invalidated_edge_cids),
            "retained_subroot_cids": list(self.retained_subroot_cids),
            "affected_node_cids": list(self.affected_node_cids),
            "full_fallback": self.full_fallback,
            "reasons": list(self.reasons),
            "environment_changed": self.environment_changed,
        }

    @property
    def program_graph_invalidation_plan_cid(self) -> str:
        return program_graph_cid_for(self.identity_payload())


class _Block:
    __slots__ = ("name", "kind", "start_line")

    def __init__(self, name: str, kind: str, start_line: int) -> None:
        self.name = name
        self.kind = kind
        self.start_line = start_line


class _CFGBuilder:
    def __init__(self, qualifier: str) -> None:
        self.qualifier = qualifier
        self.blocks: list[_Block] = []
        self.edges: list[tuple[int, int, str, bool, int]] = []
        self._loop_stack: list[tuple[int, int]] = []
        self._try_stack: list[list[int]] = []
        self._counter = 0

    def block(self, suffix: str, start_line: int, kind: str = "cfg_block") -> int:
        index = len(self.blocks)
        self._counter += 1
        name = f"{self.qualifier}.cfg.{suffix}.{self._counter}"
        self.blocks.append(_Block(name, kind, start_line))
        if self._try_stack and kind == "cfg_block":
            for handler in self._try_stack[-1]:
                self.edges.append(
                    (index, handler, ProgramGraphEdgeKind.EXCEPTION_EDGE.value, False, start_line)
                )
        return index

    def edge(
        self,
        source: int | None,
        target: int | None,
        kind: str = ProgramGraphEdgeKind.CFG_NEXT.value,
        *,
        back: bool = False,
        start_line: int = 1,
    ) -> None:
        if source is None or target is None:
            return
        self.edges.append((source, target, kind, back, start_line))

    def lower_stmts(self, stmts: Sequence[ast.stmt], current: int | None) -> int | None:
        for stmt in stmts:
            current = self.lower_stmt(stmt, current)
            if current is None:
                return None
        return current

    def lower_stmt(self, stmt: ast.stmt, current: int | None) -> int | None:
        if current is None:
            return None
        line = _lineno(stmt)
        if isinstance(stmt, ast.If):
            then_b = self.block("then", line)
            else_b = self.block("else", line)
            self.edge(
                current,
                then_b,
                ProgramGraphEdgeKind.CFG_BRANCH.value,
                start_line=line,
            )
            self.edge(
                current,
                else_b,
                ProgramGraphEdgeKind.CFG_BRANCH.value,
                start_line=line,
            )
            then_end = self.lower_stmts(stmt.body, then_b)
            else_end = self.lower_stmts(stmt.orelse, else_b)
            if then_end is None and else_end is None:
                return None
            join = self.block("join", line)
            self.edge(then_end, join, start_line=line)
            self.edge(else_end, join, start_line=line)
            return join
        if isinstance(stmt, (ast.While, ast.For, ast.AsyncFor)):
            header = self.block("loop_header", line)
            body_b = self.block("loop_body", line)
            after = self.block("loop_after", line)
            self.edge(current, header, start_line=line)
            self.edge(
                header,
                body_b,
                ProgramGraphEdgeKind.CFG_BRANCH.value,
                start_line=line,
            )
            self.edge(
                header,
                after,
                ProgramGraphEdgeKind.CFG_BRANCH.value,
                start_line=line,
            )
            self._loop_stack.append((header, after))
            body_end = self.lower_stmts(stmt.body, body_b)
            if body_end is not None:
                self.edge(body_end, header, back=True, start_line=line)
            self._loop_stack.pop()
            if getattr(stmt, "orelse", None):
                return self.lower_stmts(stmt.orelse, after)
            return after
        if isinstance(stmt, ast.Try):
            body_b = self.block("try_body", line)
            self.edge(current, body_b, start_line=line)
            handlers = [
                self.block(
                    "except",
                    _lineno(handler),
                    kind="exception_handler",
                )
                for handler in stmt.handlers
            ]
            self._try_stack.append(handlers)
            body_end = self.lower_stmts(stmt.body, body_b)
            self._try_stack.pop()
            for handler_index, handler in zip(handlers, stmt.handlers):
                self.edge(
                    body_b,
                    handler_index,
                    ProgramGraphEdgeKind.EXCEPTION_EDGE.value,
                    start_line=_lineno(handler),
                )
            after = self.block("try_after", line)
            final_b = self.block("finally", line) if stmt.finalbody else None
            handler_ends: list[int | None] = []
            for handler_index, handler in zip(handlers, stmt.handlers):
                handler_ends.append(self.lower_stmts(handler.body, handler_index))
            else_end: int | None = None
            if stmt.orelse:
                else_b = self.block("try_else", line)
                self.edge(body_end, else_b, start_line=line)
                else_end = self.lower_stmts(stmt.orelse, else_b)
            elif body_end is not None:
                else_end = body_end
            exits = [else_end, *handler_ends]
            if final_b is not None:
                for item in exits:
                    self.edge(item, final_b, start_line=line)
                final_end = self.lower_stmts(stmt.finalbody, final_b)
                self.edge(final_end, after, start_line=line)
                return after if final_end is not None else None
            living = [item for item in exits if item is not None]
            if not living:
                return None
            for item in living:
                self.edge(item, after, start_line=line)
            return after
        if isinstance(stmt, ast.With) or isinstance(stmt, ast.AsyncWith):
            body_b = self.block("with_body", line)
            self.edge(current, body_b, start_line=line)
            return self.lower_stmts(stmt.body, body_b)
        if isinstance(stmt, ast.Match):
            after = self.block("match_after", line)
            living = False
            for case in stmt.cases:
                case_b = self.block("match_case", _lineno(case))
                self.edge(
                    current,
                    case_b,
                    ProgramGraphEdgeKind.CFG_BRANCH.value,
                    start_line=_lineno(case),
                )
                end = self.lower_stmts(case.body, case_b)
                if end is not None:
                    self.edge(end, after, start_line=_lineno(case))
                    living = True
            return after if living else None
        if isinstance(stmt, ast.Return):
            return None
        if isinstance(stmt, ast.Raise):
            if self._try_stack:
                for handler in self._try_stack[-1]:
                    self.edge(
                        current,
                        handler,
                        ProgramGraphEdgeKind.EXCEPTION_EDGE.value,
                        start_line=line,
                    )
            return None
        if isinstance(stmt, ast.Break):
            if self._loop_stack:
                self.edge(current, self._loop_stack[-1][1], start_line=line)
            return None
        if isinstance(stmt, ast.Continue):
            if self._loop_stack:
                self.edge(
                    current,
                    self._loop_stack[-1][0],
                    back=True,
                    start_line=line,
                )
            return None
        return current


@dataclass
class _UnitWork:
    unit: ProgramGraphSourceUnit
    source_cid: str
    tree: ast.AST | None
    extractor_record: Any
    parse_error: bool
    incomplete: set[str] = field(default_factory=set)


class ProgramGraphBuilder:
    """Construct a sealed current-tree static program graph from explicit units."""

    INTERFACE: Final[str] = PROGRAM_GRAPH_BUILDER_INTERFACE
    SCHEMA: Final[str] = PROGRAM_GRAPH_BUILDER_SCHEMA

    def __init__(
        self,
        *,
        environment_binding_set_cid: str | None = None,
        sealed_binding_cid: str | None = None,
        language: str = ProgramLanguage.PYTHON.value,
    ) -> None:
        language_value = (
            language.value
            if isinstance(language, ProgramLanguage)
            else _text(language, "language")
        )
        if language_value != ProgramLanguage.PYTHON.value:
            raise ProgramGraphBuilderError(
                f"language {language_value!r} is typed unavailable in this profile"
            )
        env = environment_binding_set_cid or _default_environment_binding_set_cid()
        sealed = sealed_binding_cid or _default_sealed_binding_cid(env)
        self.language = language_value
        self.environment_binding_set_cid = env
        self.sealed_binding_cid = sealed
        self._extractor = PythonASTExtractor()

    def build(
        self,
        units: Mapping[str, str | bytes] | Sequence[ProgramGraphSourceUnit | Mapping[str, Any]],
        *,
        previous: ProgramGraphBuildReceipt | None = None,
        incremental: bool = False,
    ) -> ProgramGraphBuildReceipt:
        normalized = _normalize_units(units)
        previous_by_path: dict[str, ProgramGraphUnitCatalog] = {}
        if incremental:
            if previous is None:
                raise ProgramGraphBuilderError(
                    "incremental construction requires a previous build receipt"
                )
            if (
                previous.environment_binding_set_cid != self.environment_binding_set_cid
                or previous.sealed_binding_cid != self.sealed_binding_cid
            ):
                previous_by_path = {}
            else:
                previous_by_path = {
                    item.facts.path: item for item in previous.unit_catalogs
                }
        catalogs: list[ProgramGraphUnitCatalog] = []
        for unit in normalized:
            prior = previous_by_path.get(unit.path)
            if (
                incremental
                and prior is not None
                and prior.facts.source_cid == unit.source_cid
                and prior.facts.module_name == unit.resolved_module_name
            ):
                catalogs.append(prior)
                continue
            catalogs.append(self._analyze_unit(unit))
        return self._assemble(catalogs, incremental=incremental)

    def _analyze_unit(self, unit: ProgramGraphSourceUnit) -> ProgramGraphUnitCatalog:
        source_cid = unit.source_cid
        text = unit.source_text
        parse_error = False
        tree: ast.Module | None
        try:
            tree = ast.parse(text, filename=unit.path)
        except SyntaxError:
            tree = None
            parse_error = True
        extractor_record = None
        if not parse_error:
            extractor_record = self._extractor.extract_from_source(
                text,
                path=unit.path,
                module_name=unit.resolved_module_name,
            )
        work = _UnitWork(
            unit=unit,
            source_cid=source_cid,
            tree=tree,
            extractor_record=extractor_record,
            parse_error=parse_error,
        )
        if parse_error:
            work.incomplete.add(DynamicFrontierReason.INCOMPLETE_ANALYSIS.value)
        elif work.extractor_record is not None:
            for notice in work.extractor_record.unsupported:
                code = str(getattr(notice, "code", ""))
                if code == "python.dynamic_execution":
                    work.incomplete.add(DynamicFrontierReason.EVAL.value)
                elif code in {"python.wildcard_import", "python.dynamic_exports"}:
                    work.incomplete.add(DynamicFrontierReason.IMPORT_HOOK.value)
                elif code == "python.dynamic_scope":
                    work.incomplete.add(
                        DynamicFrontierReason.INCOMPLETE_ANALYSIS.value
                    )
        return self._project_unit(work)

    def _node(
        self,
        *,
        kind: str,
        logical_name: str,
        source_cid: str,
        path: str,
        start_line: int = 1,
        declaration_cid: str | None = None,
        record_cid: str | None = None,
        subject_cid: str | None = None,
        unavailable: Sequence[str] = (),
        extra: Mapping[str, Any] | None = None,
    ) -> ProgramGraphNode:
        metadata = _metadata(
            path=path,
            start_line=start_line,
            **dict(extra or {}),
        )
        return ProgramGraphNode(
            node_kind=kind,
            language=self.language,
            logical_name=logical_name,
            source_cid=source_cid,
            declaration_cid=declaration_cid
            or _declaration_cid(
                kind=kind,
                name=logical_name,
                path=path,
                source_cid=source_cid,
                start_line=start_line,
            ),
            environment_binding_cid=self.sealed_binding_cid,
            subject_cid=subject_cid,
            record_cid=record_cid,
            unavailable_dimensions=unavailable,
            metadata=metadata,
        )

    def _edge(
        self,
        kind: str,
        source: ProgramGraphNode,
        target: ProgramGraphNode,
        *,
        path: str,
        start_line: int = 1,
        status: str = ResolutionStatus.DEFINITE.value,
        logical_cycle: bool = False,
        unavailable: Sequence[str] = (),
        extra: Mapping[str, Any] | None = None,
        scope: str = "unit",
    ) -> ProgramGraphEdge:
        metadata = _metadata(
            path=path,
            start_line=start_line,
            scope=scope,
            **dict(extra or {}),
        )
        if kind in {
            ProgramGraphEdgeKind.CYCLIC_IMPORT.value,
            ProgramGraphEdgeKind.MUTUAL_RECURSION.value,
        }:
            logical_cycle = True
        return ProgramGraphEdge(
            edge_kind=kind,
            source_node_cid=source.program_graph_node_cid,
            target_node_cid=target.program_graph_node_cid,
            language=self.language,
            environment_binding_cid=self.sealed_binding_cid,
            resolution_status=status,
            logical_cycle=logical_cycle,
            unavailable_dimensions=unavailable,
            metadata=metadata,
        )

    def _project_unit(self, work: _UnitWork) -> ProgramGraphUnitCatalog:
        unit = work.unit
        path = unit.path
        module_name = unit.resolved_module_name
        source_cid = work.source_cid
        nodes: list[ProgramGraphNode] = []
        edges: list[ProgramGraphEdge] = []
        callsites: list[CallsiteRecord] = []
        function_symbols: list[FunctionSymbolRecord] = []
        contract_states: list[ContractStateRecord] = []
        proof_graphs: list[ProofObligationGraph] = []
        functions: list[str] = []
        classes: list[str] = []
        tests: list[str] = []
        fixtures: list[str] = []
        imports: list[ProgramGraphImportFact] = []
        calls: list[ProgramGraphCallFact] = []
        bases: list[tuple[str, str]] = []
        aliases: dict[str, str] = {}
        incomplete = set(work.incomplete)

        source_node = self._node(
            kind=ProgramGraphNodeKind.SOURCE.value,
            logical_name=path,
            source_cid=source_cid,
            path=path,
            extra={"role": "source"},
        )
        ast_node = self._node(
            kind=ProgramGraphNodeKind.AST.value,
            logical_name=f"{module_name}.<ast>",
            source_cid=source_cid,
            path=path,
            extra={"role": "ast"},
        )
        module_unavailable = (
            (DynamicFrontierReason.INCOMPLETE_ANALYSIS.value,)
            if work.parse_error
            else ()
        )
        module_node = self._node(
            kind=ProgramGraphNodeKind.MODULE.value,
            logical_name=module_name,
            source_cid=source_cid,
            path=path,
            unavailable=module_unavailable,
            extra={"role": "module"},
        )
        nodes.extend((source_node, ast_node, module_node))
        edges.append(self._edge(ProgramGraphEdgeKind.CONTAINS.value, source_node, ast_node, path=path))
        edges.append(self._edge(ProgramGraphEdgeKind.CONTAINS.value, source_node, module_node, path=path))
        edges.append(self._edge(ProgramGraphEdgeKind.CONTAINS.value, ast_node, module_node, path=path))

        if work.parse_error:
            hole = self._node(
                kind=ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value,
                logical_name=f"{module_name}.<parse-error>",
                source_cid=source_cid,
                path=path,
                unavailable=(DynamicFrontierReason.INCOMPLETE_ANALYSIS.value,),
                extra={"reason": DynamicFrontierReason.INCOMPLETE_ANALYSIS.value},
            )
            nodes.append(hole)
            edges.append(
                self._edge(
                    ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value,
                    module_node,
                    hole,
                    path=path,
                    status=ResolutionStatus.UNRESOLVED.value,
                    unavailable=(DynamicFrontierReason.INCOMPLETE_ANALYSIS.value,),
                )
            )
            facts = ProgramGraphUnitFacts(
                path=path,
                module_name=module_name,
                source_cid=source_cid,
                parse_error=True,
                functions=(),
                classes=(),
                imports=(),
                calls=(),
                tests=(),
                fixtures=(),
                bases=(),
                aliases=(),
                incomplete_dimensions=tuple(sorted(incomplete)),
            )
            return ProgramGraphUnitCatalog(
                facts=facts,
                nodes=tuple(nodes),
                edges=tuple(edges),
                callsites=(),
                function_symbols=(),
                contract_states=(),
                proof_obligation_graphs=(),
            )

        tree = work.tree
        assert tree is not None
        package_parts = _package_of(path, module_name)

        for stmt in tree.body:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                import_facts = self._import_facts(stmt, package_parts)
                imports.extend(import_facts)
                for fact in import_facts:
                    local = fact.local_name or fact.imported_name or fact.module
                    if local:
                        aliases[local] = (
                            f"{fact.module}.{fact.imported_name}"
                            if fact.imported_name
                            else fact.module
                        )
                    binding_name = f"{module_name}.<import>.{local or fact.module}"
                    status = (
                        ResolutionStatus.UNRESOLVED.value
                        if fact.dynamic
                        else ResolutionStatus.DEFINITE.value
                    )
                    unavailable = (
                        (DynamicFrontierReason.IMPORT_HOOK.value,)
                        if fact.dynamic
                        else ()
                    )
                    binding = self._node(
                        kind=ProgramGraphNodeKind.IMPORT_BINDING.value,
                        logical_name=binding_name,
                        source_cid=source_cid,
                        path=path,
                        start_line=fact.start_line,
                        unavailable=unavailable,
                        extra={"imported_module": fact.module},
                    )
                    nodes.append(binding)
                    edges.append(
                        self._edge(
                            ProgramGraphEdgeKind.DECLARES.value,
                            module_node,
                            binding,
                            path=path,
                            start_line=fact.start_line,
                        )
                    )
                    if fact.dynamic:
                        hole = self._node(
                            kind=ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value,
                            logical_name=f"{binding_name}.<dynamic>",
                            source_cid=source_cid,
                            path=path,
                            start_line=fact.start_line,
                            unavailable=unavailable,
                            extra={"reason": DynamicFrontierReason.IMPORT_HOOK.value},
                        )
                        nodes.append(hole)
                        edges.append(
                            self._edge(
                                ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value,
                                binding,
                                hole,
                                path=path,
                                start_line=fact.start_line,
                                status=status,
                                unavailable=unavailable,
                            )
                        )
                        incomplete.add(DynamicFrontierReason.IMPORT_HOOK.value)

        class_stack: list[str] = []

        def qualify(name: str) -> str:
            return _qualified(module_name, *class_stack, name)

        def project_function(
            node: ast.FunctionDef | ast.AsyncFunctionDef,
            *,
            owner: ProgramGraphNode,
        ) -> None:
            qual = qualify(node.name)
            functions.append(qual)
            decorators = _decorator_names(node)
            params = [
                item.arg
                for item in (
                    *node.args.posonlyargs,
                    *node.args.args,
                    *(([node.args.vararg] if node.args.vararg else [])),
                    *node.args.kwonlyargs,
                    *(([node.args.kwarg] if node.args.kwarg else [])),
                )
            ]
            annotation = _render(node.returns)
            fn_record = FunctionSymbolRecord(
                language=self.language,
                logical_name=qual,
                source_cid=source_cid,
                declaration_cid=_declaration_cid(
                    kind="function",
                    name=qual,
                    path=path,
                    source_cid=source_cid,
                    start_line=_lineno(node),
                ),
                parameter_names=tuple(params),
                return_annotation=annotation,
            )
            function_symbols.append(fn_record)
            fn_node = self._node(
                kind=ProgramGraphNodeKind.FUNCTION.value,
                logical_name=qual,
                source_cid=source_cid,
                path=path,
                start_line=_lineno(node),
                declaration_cid=fn_record.declaration_cid,
                record_cid=fn_record.function_symbol_record_cid,
            )
            nodes.append(fn_node)
            edges.append(
                self._edge(
                    ProgramGraphEdgeKind.DECLARES.value,
                    owner,
                    fn_node,
                    path=path,
                    start_line=_lineno(node),
                )
            )
            edges.append(
                self._edge(
                    ProgramGraphEdgeKind.CONTAINS.value,
                    owner,
                    fn_node,
                    path=path,
                    start_line=_lineno(node),
                )
            )
            for param, item in zip(
                params,
                (
                    *node.args.posonlyargs,
                    *node.args.args,
                    *(([node.args.vararg] if node.args.vararg else [])),
                    *node.args.kwonlyargs,
                    *(([node.args.kwarg] if node.args.kwarg else [])),
                ),
            ):
                symbol = self._node(
                    kind=ProgramGraphNodeKind.SYMBOL.value,
                    logical_name=f"{qual}.{param}",
                    source_cid=source_cid,
                    path=path,
                    start_line=_lineno(item),
                    extra={"symbol_role": "parameter"},
                )
                nodes.append(symbol)
                edges.append(
                    self._edge(
                        ProgramGraphEdgeKind.DECLARES.value,
                        fn_node,
                        symbol,
                        path=path,
                        start_line=_lineno(item),
                    )
                )
                if getattr(item, "annotation", None) is not None:
                    type_node = self._node(
                        kind=ProgramGraphNodeKind.TYPE_BINDING.value,
                        logical_name=f"{qual}.{param}.:type",
                        source_cid=source_cid,
                        path=path,
                        start_line=_lineno(item),
                        extra={"annotation": _render(item.annotation)},
                    )
                    nodes.append(type_node)
                    edges.append(
                        self._edge(
                            ProgramGraphEdgeKind.TYPE_OF.value,
                            symbol,
                            type_node,
                            path=path,
                            start_line=_lineno(item),
                        )
                    )
            if node.returns is not None:
                ret_type = self._node(
                    kind=ProgramGraphNodeKind.TYPE_BINDING.value,
                    logical_name=f"{qual}.:return",
                    source_cid=source_cid,
                    path=path,
                    start_line=_lineno(node),
                    extra={"annotation": annotation},
                )
                nodes.append(ret_type)
                edges.append(
                    self._edge(
                        ProgramGraphEdgeKind.TYPE_OF.value,
                        fn_node,
                        ret_type,
                        path=path,
                        start_line=_lineno(node),
                    )
                )
            if _is_fixture(decorators):
                fixtures.append(qual)
                fixture_node = self._node(
                    kind=ProgramGraphNodeKind.FIXTURE.value,
                    logical_name=f"{qual}.<fixture>",
                    source_cid=source_cid,
                    path=path,
                    start_line=_lineno(node),
                )
                nodes.append(fixture_node)
                edges.append(
                    self._edge(
                        ProgramGraphEdgeKind.DECLARES.value,
                        fn_node,
                        fixture_node,
                        path=path,
                        start_line=_lineno(node),
                    )
                )
            if _is_test_function(node.name, decorators, path) or _is_test_function(
                qual, decorators, path
            ):
                tests.append(qual)
                test_node = self._node(
                    kind=ProgramGraphNodeKind.TEST.value,
                    logical_name=f"{qual}.<test>",
                    source_cid=source_cid,
                    path=path,
                    start_line=_lineno(node),
                )
                nodes.append(test_node)
                edges.append(
                    self._edge(
                        ProgramGraphEdgeKind.DECLARES.value,
                        fn_node,
                        test_node,
                        path=path,
                        start_line=_lineno(node),
                    )
                )
                for decorator in decorators:
                    if _simple_name(decorator) == "usefixtures" or decorator.endswith(
                        "usefixtures"
                    ):
                        continue
                    if _simple_name(decorator) == "fixture":
                        continue
            self._project_contracts(
                node,
                fn_node,
                qual,
                path,
                source_cid,
                nodes,
                edges,
                contract_states,
                proof_graphs,
            )
            self._project_cfg_and_flow(
                node,
                fn_node,
                qual,
                path,
                source_cid,
                nodes,
                edges,
                callsites,
                calls,
                incomplete,
            )

        def project_class(node: ast.ClassDef, owner: ProgramGraphNode) -> None:
            qual = qualify(node.name)
            classes.append(qual)
            class_node = self._node(
                kind=ProgramGraphNodeKind.CLASS.value,
                logical_name=qual,
                source_cid=source_cid,
                path=path,
                start_line=_lineno(node),
            )
            nodes.append(class_node)
            edges.append(
                self._edge(
                    ProgramGraphEdgeKind.DECLARES.value,
                    owner,
                    class_node,
                    path=path,
                    start_line=_lineno(node),
                )
            )
            for base in node.bases:
                base_name = _expr_name(base)
                if base_name:
                    bases.append((qual, base_name))
            if _is_test_class(node.name):
                tests.append(qual)
                test_node = self._node(
                    kind=ProgramGraphNodeKind.TEST.value,
                    logical_name=f"{qual}.<test>",
                    source_cid=source_cid,
                    path=path,
                    start_line=_lineno(node),
                )
                nodes.append(test_node)
                edges.append(
                    self._edge(
                        ProgramGraphEdgeKind.DECLARES.value,
                        class_node,
                        test_node,
                        path=path,
                        start_line=_lineno(node),
                    )
                )
            class_stack.append(node.name)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    project_function(child, owner=class_node)
                elif isinstance(child, ast.ClassDef):
                    project_class(child, class_node)
                elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                    symbol = self._node(
                        kind=ProgramGraphNodeKind.SYMBOL.value,
                        logical_name=f"{qual}.{child.target.id}",
                        source_cid=source_cid,
                        path=path,
                        start_line=_lineno(child),
                        extra={"symbol_role": "field"},
                    )
                    nodes.append(symbol)
                    edges.append(
                        self._edge(
                            ProgramGraphEdgeKind.DECLARES.value,
                            class_node,
                            symbol,
                            path=path,
                            start_line=_lineno(child),
                        )
                    )
                    if child.annotation is not None:
                        type_node = self._node(
                            kind=ProgramGraphNodeKind.TYPE_BINDING.value,
                            logical_name=f"{qual}.{child.target.id}.:type",
                            source_cid=source_cid,
                            path=path,
                            start_line=_lineno(child),
                            extra={"annotation": _render(child.annotation)},
                        )
                        nodes.append(type_node)
                        edges.append(
                            self._edge(
                                ProgramGraphEdgeKind.TYPE_OF.value,
                                symbol,
                                type_node,
                                path=path,
                                start_line=_lineno(child),
                            )
                        )
            class_stack.pop()

        for stmt in tree.body:
            if isinstance(stmt, ast.ClassDef):
                project_class(stmt, module_node)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                project_function(stmt, owner=module_node)
            elif isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                target = stmt.targets[0] if isinstance(stmt, ast.Assign) else stmt.target
                for name in _store_names(target if isinstance(target, ast.AST) else None):
                    if name == "__all__":
                        continue
                    symbol = self._node(
                        kind=ProgramGraphNodeKind.SYMBOL.value,
                        logical_name=f"{module_name}.{name}",
                        source_cid=source_cid,
                        path=path,
                        start_line=_lineno(stmt),
                        extra={"symbol_role": "module_variable"},
                    )
                    nodes.append(symbol)
                    edges.append(
                        self._edge(
                            ProgramGraphEdgeKind.DECLARES.value,
                            module_node,
                            symbol,
                            path=path,
                            start_line=_lineno(stmt),
                        )
                    )

        unique_nodes: dict[str, ProgramGraphNode] = {}
        for node in nodes:
            unique_nodes[node.program_graph_node_cid] = node
        unique_edges: dict[str, ProgramGraphEdge] = {}
        for edge in edges:
            unique_edges[edge.program_graph_edge_cid] = edge
        facts = ProgramGraphUnitFacts(
            path=path,
            module_name=module_name,
            source_cid=source_cid,
            parse_error=False,
            functions=tuple(sorted(set(functions))),
            classes=tuple(sorted(set(classes))),
            imports=tuple(imports),
            calls=tuple(calls),
            tests=tuple(sorted(set(tests))),
            fixtures=tuple(sorted(set(fixtures))),
            bases=tuple(sorted(set(bases))),
            aliases=tuple(sorted(aliases.items())),
            incomplete_dimensions=tuple(sorted(incomplete)),
        )
        return ProgramGraphUnitCatalog(
            facts=facts,
            nodes=tuple(unique_nodes[cid] for cid in sorted(unique_nodes)),
            edges=tuple(unique_edges[cid] for cid in sorted(unique_edges)),
            callsites=tuple(sorted(callsites, key=lambda item: item.callsite_record_cid)),
            function_symbols=tuple(
                sorted(function_symbols, key=lambda item: item.function_symbol_record_cid)
            ),
            contract_states=tuple(
                sorted(contract_states, key=lambda item: item.contract_state_record_cid)
            ),
            proof_obligation_graphs=tuple(
                sorted(proof_graphs, key=lambda item: item.proof_obligation_graph_cid)
            ),
        )

    def _import_facts(
        self, stmt: ast.Import | ast.ImportFrom, package_parts: Sequence[str]
    ) -> tuple[ProgramGraphImportFact, ...]:
        facts: list[ProgramGraphImportFact] = []
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                module = alias.name
                facts.append(
                    ProgramGraphImportFact(
                        module=module,
                        imported_name=None,
                        local_name=alias.asname or module.split(".", 1)[0],
                        level=0,
                        start_line=_lineno(stmt),
                    )
                )
            return tuple(facts)
        abs_module = _absolute_import(package_parts, stmt.level, stmt.module)
        dynamic = abs_module is None
        module = abs_module or (stmt.module or "")
        if not module and not stmt.names:
            return ()
        for alias in stmt.names:
            facts.append(
                ProgramGraphImportFact(
                    module=module or (stmt.module or ""),
                    imported_name=None if alias.name == "*" else alias.name,
                    local_name=alias.asname or alias.name,
                    level=stmt.level,
                    start_line=_lineno(stmt),
                    dynamic=dynamic or alias.name == "*",
                )
            )
        return tuple(facts)

    def _project_contracts(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        fn_node: ProgramGraphNode,
        qual: str,
        path: str,
        source_cid: str,
        nodes: list[ProgramGraphNode],
        edges: list[ProgramGraphEdge],
        contract_states: list[ContractStateRecord],
        proof_graphs: list[ProofObligationGraph],
    ) -> None:
        contracts = list(_doc_contracts(_docstring(node)))
        obligation_nodes: list[ProgramGraphNode] = []
        obligation_edges: list[ProgramGraphEdge] = []
        for index, stmt in enumerate(node.body):
            if (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and type(stmt.value.value) is str
                and index == 0
            ):
                continue
            if isinstance(stmt, ast.Assert):
                spec = _render(stmt.test)
                contracts.append((ContractKind.PRECONDITION.value, spec or "assert"))
                obligation = self._node(
                    kind=ProgramGraphNodeKind.PROOF_OBLIGATION.value,
                    logical_name=f"{qual}.assert.{_lineno(stmt)}",
                    source_cid=source_cid,
                    path=path,
                    start_line=_lineno(stmt),
                    extra={"kind": "assert"},
                )
                nodes.append(obligation)
                edge = self._edge(
                    ProgramGraphEdgeKind.PROVED_BY.value,
                    fn_node,
                    obligation,
                    path=path,
                    start_line=_lineno(stmt),
                )
                edges.append(edge)
                obligation_nodes.append(obligation)
                obligation_edges.append(edge)
        for ordinal, (kind, spec) in enumerate(contracts):
            record = ContractStateRecord(
                language=self.language,
                subject_logical_name=qual,
                contract_kind=kind,
                specification_cid=cid_for_bytes(spec.encode("utf-8")),
                discharge_status="unknown",
            )
            contract_states.append(record)
            contract_node = self._node(
                kind=ProgramGraphNodeKind.CONTRACT_STATE.value,
                logical_name=f"{qual}.{kind}.{ordinal}",
                source_cid=source_cid,
                path=path,
                start_line=_lineno(node),
                record_cid=record.contract_state_record_cid,
                extra={"contract_kind": kind},
            )
            nodes.append(contract_node)
            edges.append(
                self._edge(
                    ProgramGraphEdgeKind.BINDS_CONTRACT.value,
                    fn_node,
                    contract_node,
                    path=path,
                    start_line=_lineno(node),
                )
            )
            obligation = self._node(
                kind=ProgramGraphNodeKind.PROOF_OBLIGATION.value,
                logical_name=f"{qual}.{kind}.obligation.{ordinal}",
                source_cid=source_cid,
                path=path,
                start_line=_lineno(node),
            )
            nodes.append(obligation)
            edge = self._edge(
                ProgramGraphEdgeKind.PROVED_BY.value,
                fn_node,
                obligation,
                path=path,
                start_line=_lineno(node),
            )
            edges.append(edge)
            obligation_nodes.append(obligation)
            obligation_edges.append(edge)
        if obligation_nodes:
            proof_graphs.append(
                ProofObligationGraph(
                    language=self.language,
                    root_obligation_cid=obligation_nodes[0].program_graph_node_cid,
                    obligation_node_cids=[
                        item.program_graph_node_cid for item in obligation_nodes
                    ],
                    obligation_edge_cids=[
                        item.program_graph_edge_cid for item in obligation_edges
                    ],
                    environment_binding_cid=self.sealed_binding_cid,
                )
            )

    def _project_cfg_and_flow(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        fn_node: ProgramGraphNode,
        qual: str,
        path: str,
        source_cid: str,
        nodes: list[ProgramGraphNode],
        edges: list[ProgramGraphEdge],
        callsites: list[CallsiteRecord],
        calls: list[ProgramGraphCallFact],
        incomplete: set[str],
    ) -> None:
        cfg = _CFGBuilder(qual)
        entry = cfg.block("entry", _lineno(node))
        body_end = cfg.lower_stmts(list(node.body), entry)
        exit_block = cfg.block("exit", _lineno(node))
        cfg.edge(body_end, exit_block, start_line=_lineno(node))
        block_nodes: list[ProgramGraphNode] = []
        for block in cfg.blocks:
            kind = (
                ProgramGraphNodeKind.EXCEPTION_HANDLER.value
                if block.kind == "exception_handler"
                else ProgramGraphNodeKind.CFG_BLOCK.value
            )
            cfg_node = self._node(
                kind=kind,
                logical_name=block.name,
                source_cid=source_cid,
                path=path,
                start_line=block.start_line,
            )
            block_nodes.append(cfg_node)
            nodes.append(cfg_node)
            edges.append(
                self._edge(
                    ProgramGraphEdgeKind.CONTAINS.value,
                    fn_node,
                    cfg_node,
                    path=path,
                    start_line=block.start_line,
                )
            )
        if block_nodes:
            edges.append(
                self._edge(
                    ProgramGraphEdgeKind.SUCCESSOR.value,
                    fn_node,
                    block_nodes[0],
                    path=path,
                    start_line=_lineno(node),
                )
            )
        for source, target, kind, back, line in cfg.edges:
            edge_kind = kind
            if edge_kind == ProgramGraphEdgeKind.EXCEPTION_EDGE.value:
                edges.append(
                    self._edge(
                        ProgramGraphEdgeKind.CATCHES.value,
                        block_nodes[target],
                        block_nodes[source],
                        path=path,
                        start_line=line,
                    )
                )
            edges.append(
                self._edge(
                    edge_kind,
                    block_nodes[source],
                    block_nodes[target],
                    path=path,
                    start_line=line,
                    logical_cycle=back,
                )
            )

        ordinal = 0
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                callee = _expr_name(child.func) or "<dynamic>"
                reason = _future_reason(callee, child)
                record_status = ResolutionStatus.DEFINITE.value
                unavailable: tuple[str, ...] = ()
                callee_decl: str | None = None
                if reason is not None:
                    record_status = ResolutionStatus.UNRESOLVED.value
                    unavailable = (reason,)
                    incomplete.add(reason)
                else:
                    callee_decl = _declaration_cid(
                        kind="callsite-lexical",
                        name=f"{qual}->{callee}",
                        path=path,
                        source_cid=source_cid,
                        start_line=_lineno(child),
                    )
                # Local callsite records stay lexical; cross-unit resolution is
                # a later global SUCCESSOR edge.  Definite records still need a
                # declaration CID, which here identifies the lexical site.
                if record_status == ResolutionStatus.DEFINITE.value:
                    callee_decl = _declaration_cid(
                        kind="lexical-callee",
                        name=callee,
                        path=path,
                        source_cid=source_cid,
                        start_line=_lineno(child),
                    )
                record = CallsiteRecord(
                    language=self.language,
                    caller_logical_name=qual,
                    callee_logical_name=callee,
                    source_cid=source_cid,
                    ordinal=ordinal,
                    resolution_status=record_status,
                    callee_declaration_cid=callee_decl,
                    unavailable_dimensions=unavailable,
                )
                callsites.append(record)
                site = self._node(
                    kind=ProgramGraphNodeKind.CALLSITE.value,
                    logical_name=f"{qual}#{ordinal}",
                    source_cid=source_cid,
                    path=path,
                    start_line=_lineno(child),
                    record_cid=record.callsite_record_cid,
                    unavailable=unavailable,
                )
                nodes.append(site)
                edges.append(
                    self._edge(
                        ProgramGraphEdgeKind.CALLS.value,
                        fn_node,
                        site,
                        path=path,
                        start_line=_lineno(child),
                        status=record_status,
                        unavailable=unavailable,
                    )
                )
                if reason is not None:
                    hole = self._node(
                        kind=ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value,
                        logical_name=f"{qual}#{ordinal}.<dynamic>",
                        source_cid=source_cid,
                        path=path,
                        start_line=_lineno(child),
                        unavailable=unavailable,
                        extra={"reason": reason},
                    )
                    nodes.append(hole)
                    edges.append(
                        self._edge(
                            ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value,
                            site,
                            hole,
                            path=path,
                            start_line=_lineno(child),
                            status=ResolutionStatus.UNRESOLVED.value,
                            unavailable=unavailable,
                        )
                    )
                if callee in _EFFECT_CALLS or _simple_name(callee) in {
                    "open",
                    "system",
                    "Popen",
                    "run",
                }:
                    effect = self._node(
                        kind=ProgramGraphNodeKind.EFFECT.value,
                        logical_name=f"{qual}#{ordinal}.<effect>",
                        source_cid=source_cid,
                        path=path,
                        start_line=_lineno(child),
                        extra={"effect": callee},
                    )
                    nodes.append(effect)
                    edges.append(
                        self._edge(
                            ProgramGraphEdgeKind.EFFECT_OF.value,
                            fn_node,
                            effect,
                            path=path,
                            start_line=_lineno(child),
                        )
                    )
                calls.append(
                    ProgramGraphCallFact(
                        caller_logical_name=qual,
                        callee_logical_name=callee,
                        ordinal=ordinal,
                        start_line=_lineno(child),
                        intrinsic_reason=reason,
                        call_kind="method"
                        if isinstance(child.func, ast.Attribute)
                        else "direct",
                    )
                )
                ordinal += 1
            if isinstance(child, ast.Raise):
                exc_name = _expr_name(child.exc) or "raise"
                effect = self._node(
                    kind=ProgramGraphNodeKind.EFFECT.value,
                    logical_name=f"{qual}.raise.{_lineno(child)}",
                    source_cid=source_cid,
                    path=path,
                    start_line=_lineno(child),
                    extra={"exception": exc_name},
                )
                nodes.append(effect)
                edges.append(
                    self._edge(
                        ProgramGraphEdgeKind.EFFECT_OF.value,
                        fn_node,
                        effect,
                        path=path,
                        start_line=_lineno(child),
                    )
                )
                edges.append(
                    self._edge(
                        ProgramGraphEdgeKind.RAISES.value,
                        fn_node,
                        effect,
                        path=path,
                        start_line=_lineno(child),
                    )
                )
            if isinstance(child, ast.Await):
                effect = self._node(
                    kind=ProgramGraphNodeKind.EFFECT.value,
                    logical_name=f"{qual}.await.{_lineno(child)}",
                    source_cid=source_cid,
                    path=path,
                    start_line=_lineno(child),
                    extra={"effect": "await"},
                )
                nodes.append(effect)
                edges.append(
                    self._edge(
                        ProgramGraphEdgeKind.EFFECT_OF.value,
                        fn_node,
                        effect,
                        path=path,
                        start_line=_lineno(child),
                    )
                )
            if isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                target = (
                    child.targets[0]
                    if isinstance(child, ast.Assign)
                    else child.target
                )
                value = getattr(child, "value", None)
                flow = self._node(
                    kind=ProgramGraphNodeKind.DATA_FLOW.value,
                    logical_name=f"{qual}.store.{_lineno(child)}",
                    source_cid=source_cid,
                    path=path,
                    start_line=_lineno(child),
                    extra={
                        "writes": list(_store_names(target if isinstance(target, ast.AST) else None)),
                        "reads": list(_loaded_names(value)),
                    },
                )
                nodes.append(flow)
                edges.append(
                    self._edge(
                        ProgramGraphEdgeKind.DATA_FLOW.value,
                        fn_node,
                        flow,
                        path=path,
                        start_line=_lineno(child),
                    )
                )
                for name in _store_names(target if isinstance(target, ast.AST) else None):
                    edges.append(
                        self._edge(
                            ProgramGraphEdgeKind.WRITES_STATE.value,
                            fn_node,
                            flow,
                            path=path,
                            start_line=_lineno(child),
                            extra={"symbol": name},
                        )
                    )
                for name in _loaded_names(value):
                    edges.append(
                        self._edge(
                            ProgramGraphEdgeKind.READS_STATE.value,
                            fn_node,
                            flow,
                            path=path,
                            start_line=_lineno(child),
                            extra={"symbol": name},
                        )
                    )

    def _assemble(
        self,
        catalogs: Sequence[ProgramGraphUnitCatalog],
        *,
        incremental: bool,
    ) -> ProgramGraphBuildReceipt:
        nodes: dict[str, ProgramGraphNode] = {}
        edges: dict[str, ProgramGraphEdge] = {}
        callsites: dict[str, CallsiteRecord] = {}
        function_symbols: dict[str, FunctionSymbolRecord] = {}
        contract_states: dict[str, ContractStateRecord] = {}
        proof_graphs: dict[str, ProofObligationGraph] = {}
        by_kind_name: dict[tuple[str, str], ProgramGraphNode] = {}
        functions_by_name: dict[str, ProgramGraphNode] = {}
        classes_by_name: dict[str, ProgramGraphNode] = {}
        modules_by_name: dict[str, ProgramGraphNode] = {}
        tests_by_name: dict[str, ProgramGraphNode] = {}
        fixtures_by_name: dict[str, ProgramGraphNode] = {}
        callsite_nodes: dict[tuple[str, int], ProgramGraphNode] = {}
        incomplete: set[str] = set()

        def add_node(node: ProgramGraphNode) -> ProgramGraphNode:
            cid = node.program_graph_node_cid
            existing = nodes.get(cid)
            if existing is not None:
                return existing
            nodes[cid] = node
            by_kind_name[(str(node.node_kind), node.logical_name)] = node
            return node

        def add_edge(edge: ProgramGraphEdge) -> ProgramGraphEdge:
            cid = edge.program_graph_edge_cid
            existing = edges.get(cid)
            if existing is not None:
                return existing
            edges[cid] = edge
            return edge

        for catalog in catalogs:
            incomplete.update(catalog.facts.incomplete_dimensions)
            for node in catalog.nodes:
                add_node(node)
                kind = str(node.node_kind)
                if kind == ProgramGraphNodeKind.FUNCTION.value:
                    functions_by_name[node.logical_name] = node
                elif kind == ProgramGraphNodeKind.CLASS.value:
                    classes_by_name[node.logical_name] = node
                elif kind == ProgramGraphNodeKind.MODULE.value:
                    modules_by_name[node.logical_name] = node
                elif kind == ProgramGraphNodeKind.TEST.value:
                    tests_by_name[node.logical_name] = node
                elif kind == ProgramGraphNodeKind.FIXTURE.value:
                    fixtures_by_name[node.logical_name] = node
                elif kind == ProgramGraphNodeKind.CALLSITE.value:
                    if "#" in node.logical_name:
                        caller, ordinal_text = node.logical_name.rsplit("#", 1)
                        try:
                            callsite_nodes[(caller, int(ordinal_text))] = node
                        except ValueError:
                            pass
            for edge in catalog.edges:
                add_edge(edge)
            for item in catalog.callsites:
                callsites[item.callsite_record_cid] = item
            for item in catalog.function_symbols:
                function_symbols[item.function_symbol_record_cid] = item
            for item in catalog.contract_states:
                contract_states[item.contract_state_record_cid] = item
            for item in catalog.proof_obligation_graphs:
                proof_graphs[item.proof_obligation_graph_cid] = item

        init_source: dict[str, str] = {}
        for catalog in catalogs:
            package = ".".join(_package_of(catalog.facts.path, catalog.facts.module_name))
            if _is_init_path(catalog.facts.path):
                init_source[catalog.facts.module_name] = catalog.facts.source_cid
            elif package:
                init_source.setdefault(
                    package, cid_for_bytes(package.encode("utf-8"))
                )

        packages = sorted({key for key in init_source if key})
        package_nodes: dict[str, ProgramGraphNode] = {}
        for name in packages:
            package_node = add_node(
                self._node(
                    kind=ProgramGraphNodeKind.PACKAGE.value,
                    logical_name=name,
                    source_cid=init_source[name],
                    path=name.replace(".", "/") + "/__init__.py",
                    extra={"role": "package"},
                )
            )
            package_nodes[name] = package_node
        for parent, child in (
            (name.rsplit(".", 1)[0], name)
            for name in packages
            if "." in name
        ):
            if parent in package_nodes:
                add_edge(
                    self._edge(
                        ProgramGraphEdgeKind.CONTAINS.value,
                        package_nodes[parent],
                        package_nodes[child],
                        path=child.replace(".", "/"),
                        scope="global",
                    )
                )
        for catalog in catalogs:
            module_node = modules_by_name.get(catalog.facts.module_name)
            if module_node is None:
                continue
            package = ".".join(_package_of(catalog.facts.path, catalog.facts.module_name))
            parent = package_nodes.get(package)
            if parent is not None:
                add_edge(
                    self._edge(
                        ProgramGraphEdgeKind.CONTAINS.value,
                        parent,
                        module_node,
                        path=catalog.facts.path,
                        scope="global",
                    )
                )

        import_pairs: list[tuple[str, str]] = []
        for catalog in catalogs:
            source_module = modules_by_name.get(catalog.facts.module_name)
            if source_module is None:
                continue
            for fact in catalog.facts.imports:
                target = None
                if fact.imported_name and fact.module:
                    target = modules_by_name.get(f"{fact.module}.{fact.imported_name}")
                if target is None:
                    target = modules_by_name.get(fact.module)
                if target is None and fact.module:
                    target = modules_by_name.get(fact.module.split(".", 1)[0])
                if target is None:
                    if fact.module and fact.module.split(".", 1)[0] not in {
                        "typing",
                        "collections",
                        "dataclasses",
                        "functools",
                        "itertools",
                        "sys",
                        "os",
                        "ast",
                        "json",
                        "re",
                        "abc",
                        "enum",
                        "pathlib",
                        "builtins",
                        "__future__",
                    }:
                        incomplete.add(DynamicFrontierReason.INCOMPLETE_ANALYSIS.value)
                    continue
                import_pairs.append(
                    (source_module.logical_name, target.logical_name)
                )

        module_names = tuple(sorted(modules_by_name))
        import_sccs = {
            frozenset(component)
            for component in _strongly_connected(module_names, import_pairs)
            if len(component) > 1 or (len(component) == 1 and (component[0], component[0]) in import_pairs)
        }
        cyclic_modules = set().union(*import_sccs) if import_sccs else set()
        seen_import_edges: set[tuple[str, str]] = set()
        for source_name, target_name in import_pairs:
            key = (source_name, target_name)
            if key in seen_import_edges:
                continue
            seen_import_edges.add(key)
            source = modules_by_name[source_name]
            target = modules_by_name[target_name]
            kind = (
                ProgramGraphEdgeKind.CYCLIC_IMPORT.value
                if source_name in cyclic_modules and target_name in cyclic_modules
                else ProgramGraphEdgeKind.IMPORTS.value
            )
            add_edge(
                self._edge(
                    kind,
                    source,
                    target,
                    path=str((source.metadata or {}).get("path") or source.logical_name),
                    scope="global",
                    logical_cycle=kind == ProgramGraphEdgeKind.CYCLIC_IMPORT.value,
                )
            )

        alias_maps: dict[str, dict[str, str]] = {
            catalog.facts.module_name: dict(catalog.facts.aliases) for catalog in catalogs
        }
        resolved_calls: list[tuple[str, str]] = []
        finite_may: dict[tuple[str, int], tuple[ProgramGraphNode, ...]] = {}
        for catalog in catalogs:
            aliases = alias_maps.get(catalog.facts.module_name, {})
            for fact in catalog.facts.calls:
                site = callsite_nodes.get((fact.caller_logical_name, fact.ordinal))
                if site is None or fact.intrinsic_reason is not None:
                    continue
                matches, status = self._resolve_callee(
                    fact.callee_logical_name,
                    caller_module=catalog.facts.module_name,
                    aliases=aliases,
                    functions_by_name=functions_by_name,
                    classes_by_name=classes_by_name,
                    call_kind=fact.call_kind,
                )
                if status == ResolutionStatus.DEFINITE.value and len(matches) == 1:
                    add_edge(
                        self._edge(
                            ProgramGraphEdgeKind.SUCCESSOR.value,
                            site,
                            matches[0],
                            path=catalog.facts.path,
                            start_line=fact.start_line,
                            scope="global",
                        )
                    )
                    resolved_calls.append((fact.caller_logical_name, matches[0].logical_name))
                elif status == ResolutionStatus.FINITE_MAY.value and matches:
                    finite_may[(fact.caller_logical_name, fact.ordinal)] = matches
                    incomplete.add(DynamicFrontierReason.DYNAMIC_DISPATCH.value)
                    for match in matches:
                        add_edge(
                            self._edge(
                                ProgramGraphEdgeKind.SUCCESSOR.value,
                                site,
                                match,
                                path=catalog.facts.path,
                                start_line=fact.start_line,
                                status=ResolutionStatus.FINITE_MAY.value,
                                scope="global",
                                extra={"resolution": "finite_may"},
                            )
                        )
                        resolved_calls.append((fact.caller_logical_name, match.logical_name))
                elif status == ResolutionStatus.UNRESOLVED.value:
                    incomplete.add(DynamicFrontierReason.UNKNOWN_CALLEE.value)
                    hole = add_node(
                        self._node(
                            kind=ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value,
                            logical_name=(
                                f"{fact.caller_logical_name}#{fact.ordinal}"
                                f".<unknown:{fact.callee_logical_name}>"
                            ),
                            source_cid=catalog.facts.source_cid,
                            path=catalog.facts.path,
                            start_line=fact.start_line,
                            unavailable=(DynamicFrontierReason.UNKNOWN_CALLEE.value,),
                            extra={"reason": DynamicFrontierReason.UNKNOWN_CALLEE.value},
                        )
                    )
                    add_edge(
                        self._edge(
                            ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value,
                            site,
                            hole,
                            path=catalog.facts.path,
                            start_line=fact.start_line,
                            status=ResolutionStatus.UNRESOLVED.value,
                            unavailable=(DynamicFrontierReason.UNKNOWN_CALLEE.value,),
                            scope="global",
                        )
                    )

        function_names = tuple(sorted(functions_by_name))
        call_sccs = {
            frozenset(component)
            for component in _strongly_connected(function_names, resolved_calls)
            if len(component) > 1
            or (len(component) == 1 and (component[0], component[0]) in resolved_calls)
        }
        for component in call_sccs:
            members = sorted(component)
            for left in members:
                for right in members:
                    if left == right and (left, right) not in resolved_calls:
                        continue
                    add_edge(
                        self._edge(
                            ProgramGraphEdgeKind.MUTUAL_RECURSION.value,
                            functions_by_name[left],
                            functions_by_name[right],
                            path=str(
                                (functions_by_name[left].metadata or {}).get("path")
                                or left
                            ),
                            scope="global",
                            logical_cycle=True,
                        )
                    )

        for catalog in catalogs:
            for class_name, base_name in catalog.facts.bases:
                class_node = classes_by_name.get(class_name)
                if class_node is None:
                    continue
                aliases = alias_maps.get(catalog.facts.module_name, {})
                expanded = _expand_alias(base_name, aliases)
                target = classes_by_name.get(expanded) or classes_by_name.get(
                    _qualified(catalog.facts.module_name, expanded)
                )
                if target is None:
                    matches = [
                        item
                        for name, item in classes_by_name.items()
                        if name == expanded or name.endswith("." + expanded)
                    ]
                    target = matches[0] if len(matches) == 1 else None
                if target is not None:
                    add_edge(
                        self._edge(
                            ProgramGraphEdgeKind.INHERITS.value,
                            class_node,
                            target,
                            path=catalog.facts.path,
                            scope="global",
                        )
                    )

        imported_modules_by_unit: dict[str, tuple[str, ...]] = {}
        for catalog in catalogs:
            found: set[str] = set()
            for fact in catalog.facts.imports:
                if fact.imported_name and fact.module:
                    candidate = f"{fact.module}.{fact.imported_name}"
                    if candidate in modules_by_name:
                        found.add(candidate)
                        continue
                if fact.module in modules_by_name:
                    found.add(fact.module)
            imported_modules_by_unit[catalog.facts.module_name] = tuple(sorted(found))
        for catalog in catalogs:
            if not catalog.facts.tests:
                continue
            for test_name in catalog.facts.tests:
                test_node = tests_by_name.get(f"{test_name}.<test>") or tests_by_name.get(
                    test_name
                )
                if test_node is None:
                    continue
                for imported in imported_modules_by_unit.get(catalog.facts.module_name, ()):
                    imported_module = modules_by_name.get(imported)
                    if imported_module is None:
                        continue
                    add_edge(
                        self._edge(
                            ProgramGraphEdgeKind.TESTED_BY.value,
                            imported_module,
                            test_node,
                            path=catalog.facts.path,
                            scope="global",
                        )
                    )
                    for fn_name, fn_node in functions_by_name.items():
                        if fn_name == test_name or fn_name.startswith(test_name + "."):
                            continue
                        if fn_name.startswith(imported + ".") or (
                            "." not in fn_name and imported.endswith("." + fn_name)
                        ):
                            add_edge(
                                self._edge(
                                    ProgramGraphEdgeKind.TESTED_BY.value,
                                    fn_node,
                                    test_node,
                                    path=catalog.facts.path,
                                    scope="global",
                                )
                            )
                for fixture_name in catalog.facts.fixtures:
                    fixture_node = fixtures_by_name.get(f"{fixture_name}.<fixture>")
                    if fixture_node is not None:
                        add_edge(
                            self._edge(
                                ProgramGraphEdgeKind.USES_FIXTURE.value,
                                test_node,
                                fixture_node,
                                path=catalog.facts.path,
                                scope="global",
                            )
                        )

        edges = _seal_logical_cycles(edges)
        successor_sets: list[StaticSuccessorSet] = []
        outgoing: dict[str, list[ProgramGraphEdge]] = defaultdict(list)
        for edge in edges.values():
            outgoing[edge.source_node_cid].append(edge)
        for fn_node in functions_by_name.values():
            succ_nodes: set[str] = set()
            succ_edges: set[str] = set()
            complete = True
            unavailable: set[str] = set()
            for edge in outgoing.get(fn_node.program_graph_node_cid, ()):
                if str(edge.edge_kind) in {
                    ProgramGraphEdgeKind.CALLS.value,
                    ProgramGraphEdgeKind.SUCCESSOR.value,
                    ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value,
                    ProgramGraphEdgeKind.MUTUAL_RECURSION.value,
                }:
                    succ_nodes.add(edge.target_node_cid)
                    succ_edges.add(edge.program_graph_edge_cid)
                if is_unresolved_dynamic_edge(edge):
                    complete = False
                    unavailable.update(edge.unavailable_dimensions)
                if str(edge.resolution_status) == ResolutionStatus.FINITE_MAY.value:
                    complete = False
                    unavailable.add(DynamicFrontierReason.DYNAMIC_DISPATCH.value)
            for edge in outgoing.get(fn_node.program_graph_node_cid, ()):
                if str(edge.edge_kind) != ProgramGraphEdgeKind.CALLS.value:
                    continue
                for child in outgoing.get(edge.target_node_cid, ()):
                    if str(child.edge_kind) in {
                        ProgramGraphEdgeKind.SUCCESSOR.value,
                        ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value,
                    }:
                        succ_nodes.add(child.target_node_cid)
                        succ_edges.add(child.program_graph_edge_cid)
                    if is_unresolved_dynamic_edge(child):
                        complete = False
                        unavailable.update(child.unavailable_dimensions)
                    if str(child.resolution_status) == ResolutionStatus.FINITE_MAY.value:
                        complete = False
                        unavailable.add(DynamicFrontierReason.DYNAMIC_DISPATCH.value)
            if not complete and not unavailable:
                unavailable.add(DynamicFrontierReason.INCOMPLETE_ANALYSIS.value)
            successor_sets.append(
                StaticSuccessorSet(
                    language=self.language,
                    subject_node_cid=fn_node.program_graph_node_cid,
                    successor_node_cids=tuple(sorted(succ_nodes)),
                    successor_edge_cids=tuple(sorted(succ_edges)),
                    complete=complete,
                    unavailable_dimensions=tuple(sorted(unavailable)),
                )
            )

        unresolved_nodes = [
            node for node in nodes.values() if is_unresolved_dynamic_node(node)
        ]
        unresolved_edges = [
            edge for edge in edges.values() if is_unresolved_dynamic_edge(edge)
        ]
        incomplete_successors = [item for item in successor_sets if item.complete is False]
        frontiers: list[DynamicFrontierRecord] = []
        if unresolved_nodes or unresolved_edges or incomplete_successors:
            reasons = sorted(
                {
                    *[
                        str(item)
                        for node in unresolved_nodes
                        for item in node.unavailable_dimensions
                        if item in {reason.value for reason in DynamicFrontierReason}
                    ],
                    *[
                        str(item)
                        for edge in unresolved_edges
                        for item in edge.unavailable_dimensions
                        if item in {reason.value for reason in DynamicFrontierReason}
                    ],
                    *incomplete,
                }
            )
            if not reasons:
                reasons = [DynamicFrontierReason.INCOMPLETE_ANALYSIS.value]
            unavailable = tuple(sorted(set(reasons) | incomplete))
            frontiers.append(
                DynamicFrontierRecord(
                    language=self.language,
                    unresolved_node_cids=[
                        node.program_graph_node_cid for node in unresolved_nodes
                    ],
                    unresolved_edge_cids=[
                        edge.program_graph_edge_cid for edge in unresolved_edges
                    ],
                    reasons=reasons,
                    unavailable_dimensions=unavailable,
                )
            )
            incomplete.update(unavailable)

        node_list = tuple(nodes[cid] for cid in sorted(nodes))
        edge_list = tuple(edges[cid] for cid in sorted(edges))
        snapshot = assemble_program_graph_snapshot(
            language=self.language,
            nodes=node_list,
            edges=edge_list,
            environment_binding_set_cid=self.environment_binding_set_cid,
            sealed_binding_cid=self.sealed_binding_cid,
            callsites=tuple(callsites[cid] for cid in sorted(callsites)),
            function_symbols=tuple(
                function_symbols[cid] for cid in sorted(function_symbols)
            ),
            contract_states=tuple(
                contract_states[cid] for cid in sorted(contract_states)
            ),
            proof_obligation_graphs=tuple(
                proof_graphs[cid] for cid in sorted(proof_graphs)
            ),
            successor_sets=tuple(
                sorted(successor_sets, key=lambda item: item.static_successor_set_cid)
            ),
            frontiers=tuple(
                sorted(frontiers, key=lambda item: item.dynamic_frontier_record_cid)
            ),
            retained_subroot_cids=(),
            unavailable_dimensions=tuple(sorted(incomplete)),
        )
        verify_program_graph_catalog(
            snapshot,
            nodes=node_list,
            edges=edge_list,
            callsites=tuple(callsites[cid] for cid in sorted(callsites)),
            function_symbols=tuple(
                function_symbols[cid] for cid in sorted(function_symbols)
            ),
            contract_states=tuple(
                contract_states[cid] for cid in sorted(contract_states)
            ),
            proof_obligation_graphs=tuple(
                proof_graphs[cid] for cid in sorted(proof_graphs)
            ),
            successor_sets=tuple(
                sorted(successor_sets, key=lambda item: item.static_successor_set_cid)
            ),
            frontiers=tuple(
                sorted(frontiers, key=lambda item: item.dynamic_frontier_record_cid)
            ),
        )
        coverage = _coverage_counts(node_list, edge_list)
        manifest = ProgramGraphIndexManifest(
            snapshot_cid=snapshot.program_graph_snapshot_cid,
            index_kind=ProgramGraphIndexKind.ADJACENCY,
            schema_ids=(
                PROGRAM_GRAPH_SNAPSHOT_SCHEMA,
                PROGRAM_GRAPH_NODE_SCHEMA,
                PROGRAM_GRAPH_EDGE_SCHEMA,
                PROGRAM_GRAPH_DELTA_SCHEMA,
                CALLSITE_RECORD_SCHEMA,
                FUNCTION_SYMBOL_RECORD_SCHEMA,
                CONTRACT_STATE_RECORD_SCHEMA,
                PROOF_OBLIGATION_GRAPH_SCHEMA,
                STATIC_SUCCESSOR_SET_SCHEMA,
                DYNAMIC_FRONTIER_RECORD_SCHEMA,
            ),
        )
        bind_index_manifest(manifest, snapshot)
        return ProgramGraphBuildReceipt(
            snapshot=snapshot,
            nodes=node_list,
            edges=edge_list,
            callsites=tuple(callsites[cid] for cid in sorted(callsites)),
            function_symbols=tuple(
                function_symbols[cid] for cid in sorted(function_symbols)
            ),
            contract_states=tuple(
                contract_states[cid] for cid in sorted(contract_states)
            ),
            proof_obligation_graphs=tuple(
                proof_graphs[cid] for cid in sorted(proof_graphs)
            ),
            successor_sets=tuple(
                sorted(successor_sets, key=lambda item: item.static_successor_set_cid)
            ),
            frontiers=tuple(
                sorted(frontiers, key=lambda item: item.dynamic_frontier_record_cid)
            ),
            index_manifest=manifest,
            unit_catalogs=tuple(
                sorted(catalogs, key=lambda item: item.facts.path)
            ),
            coverage=coverage,
            incomplete_dimensions=tuple(sorted(incomplete)),
            incremental=incremental,
            environment_binding_set_cid=self.environment_binding_set_cid,
            sealed_binding_cid=self.sealed_binding_cid,
        )

    def _resolve_callee(
        self,
        callee: str,
        *,
        caller_module: str,
        aliases: Mapping[str, str],
        functions_by_name: Mapping[str, ProgramGraphNode],
        classes_by_name: Mapping[str, ProgramGraphNode],
        call_kind: str,
    ) -> tuple[tuple[ProgramGraphNode, ...], str]:
        expanded = _expand_alias(callee, aliases)
        candidates = (
            expanded,
            _qualified(caller_module, expanded),
            _qualified(caller_module, callee),
        )
        for name in candidates:
            if name in functions_by_name:
                return (functions_by_name[name],), ResolutionStatus.DEFINITE.value
        simple = _simple_name(expanded)
        if simple in _BUILTIN_NAMES and "." not in expanded:
            return (), ResolutionStatus.DEFINITE.value
        suffix_matches = [
            node
            for name, node in functions_by_name.items()
            if name == simple or name.endswith("." + simple)
        ]
        if call_kind == "method" and simple:
            class_methods = [
                node
                for name, node in functions_by_name.items()
                if name.endswith("." + simple)
            ]
            if len(class_methods) == 1:
                return (class_methods[0],), ResolutionStatus.DEFINITE.value
            if len(class_methods) > 1:
                return tuple(class_methods), ResolutionStatus.FINITE_MAY.value
        if len(suffix_matches) == 1:
            return (suffix_matches[0],), ResolutionStatus.DEFINITE.value
        if len(suffix_matches) > 1:
            return tuple(suffix_matches), ResolutionStatus.FINITE_MAY.value
        if expanded in classes_by_name:
            ctor = functions_by_name.get(f"{expanded}.__init__")
            if ctor is not None:
                return (ctor,), ResolutionStatus.DEFINITE.value
        if simple in _BUILTIN_NAMES:
            return (), ResolutionStatus.DEFINITE.value
        return (), ResolutionStatus.UNRESOLVED.value


def _expand_alias(name: str, aliases: Mapping[str, str]) -> str:
    if not name:
        return name
    root, dot, rest = name.partition(".")
    mapped = aliases.get(root, root)
    return mapped + (("." + rest) if dot else "")


def _coverage_counts(
    nodes: Sequence[ProgramGraphNode],
    edges: Sequence[ProgramGraphEdge],
) -> tuple[tuple[str, int], ...]:
    node_kinds = [str(node.node_kind) for node in nodes]
    edge_kinds = [str(edge.edge_kind) for edge in edges]
    mapping = {
        "ast": node_kinds.count(ProgramGraphNodeKind.AST.value),
        "symbol": node_kinds.count(ProgramGraphNodeKind.SYMBOL.value)
        + node_kinds.count(ProgramGraphNodeKind.FUNCTION.value)
        + node_kinds.count(ProgramGraphNodeKind.CLASS.value),
        "import": node_kinds.count(ProgramGraphNodeKind.IMPORT_BINDING.value)
        + edge_kinds.count(ProgramGraphEdgeKind.IMPORTS.value)
        + edge_kinds.count(ProgramGraphEdgeKind.CYCLIC_IMPORT.value),
        "call": node_kinds.count(ProgramGraphNodeKind.CALLSITE.value),
        "cfg": node_kinds.count(ProgramGraphNodeKind.CFG_BLOCK.value),
        "data_flow": node_kinds.count(ProgramGraphNodeKind.DATA_FLOW.value),
        "exception": node_kinds.count(ProgramGraphNodeKind.EXCEPTION_HANDLER.value)
        + edge_kinds.count(ProgramGraphEdgeKind.EXCEPTION_EDGE.value),
        "type": node_kinds.count(ProgramGraphNodeKind.TYPE_BINDING.value),
        "effect": node_kinds.count(ProgramGraphNodeKind.EFFECT.value),
        "contract": node_kinds.count(ProgramGraphNodeKind.CONTRACT_STATE.value),
        "test": node_kinds.count(ProgramGraphNodeKind.TEST.value)
        + node_kinds.count(ProgramGraphNodeKind.FIXTURE.value),
        "proof": node_kinds.count(ProgramGraphNodeKind.PROOF_OBLIGATION.value),
    }
    return tuple((name, mapping[name]) for name in GRAPH_PROJECTIONS)


def _normalize_units(
    units: Mapping[str, str | bytes]
    | Sequence[ProgramGraphSourceUnit | Mapping[str, Any]],
) -> tuple[ProgramGraphSourceUnit, ...]:
    collected: list[ProgramGraphSourceUnit] = []
    if isinstance(units, Mapping) and not isinstance(units, ProgramGraphSourceUnit):
        for path, source in units.items():
            collected.append(ProgramGraphSourceUnit(path=str(path), source=source))
    elif isinstance(units, Sequence) and type(units) not in {str, bytes, bytearray}:
        for item in units:
            if isinstance(item, ProgramGraphSourceUnit):
                collected.append(item)
            elif isinstance(item, Mapping):
                collected.append(
                    ProgramGraphSourceUnit(
                        path=str(item.get("path")),
                        source=item.get("source"),  # type: ignore[arg-type]
                        language=str(item.get("language") or ProgramLanguage.PYTHON.value),
                        module_name=item.get("module_name"),
                    )
                )
            else:
                raise ProgramGraphBuilderError(
                    "units must be source-unit records or path/source mappings"
                )
    else:
        raise ProgramGraphBuilderError(
            "units must be a mapping of path to source or a sequence of units"
        )
    if not collected:
        raise ProgramGraphBuilderError("at least one source unit is required")
    by_path: dict[str, ProgramGraphSourceUnit] = {}
    for item in collected:
        if item.path in by_path:
            raise ProgramGraphBuilderError(f"duplicate source unit path {item.path!r}")
        by_path[item.path] = item
    return tuple(by_path[path] for path in sorted(by_path))


def _as_receipt(
    value: ProgramGraphBuildReceipt | ProgramGraphSnapshot,
    label: str,
) -> ProgramGraphBuildReceipt | None:
    if isinstance(value, ProgramGraphBuildReceipt):
        return value
    if isinstance(value, ProgramGraphSnapshot):
        return None
    raise ProgramGraphBuilderError(f"{label} must be a build receipt or snapshot")


def _as_snapshot(
    value: ProgramGraphBuildReceipt | ProgramGraphSnapshot,
    label: str,
) -> ProgramGraphSnapshot:
    if isinstance(value, ProgramGraphBuildReceipt):
        return value.snapshot
    if isinstance(value, ProgramGraphSnapshot):
        return value
    raise ProgramGraphBuilderError(f"{label} must be a build receipt or snapshot")


def build_program_graph(
    units: Mapping[str, str | bytes]
    | Sequence[ProgramGraphSourceUnit | Mapping[str, Any]],
    *,
    environment_binding_set_cid: str | None = None,
    sealed_binding_cid: str | None = None,
    previous: ProgramGraphBuildReceipt | None = None,
    incremental: bool = False,
    language: str = ProgramLanguage.PYTHON.value,
) -> ProgramGraphBuildReceipt:
    """Construct a deterministic static program graph from explicit units."""

    builder = ProgramGraphBuilder(
        environment_binding_set_cid=environment_binding_set_cid,
        sealed_binding_cid=sealed_binding_cid,
        language=language,
    )
    return builder.build(units, previous=previous, incremental=incremental)


def compute_program_graph_delta(
    previous: ProgramGraphBuildReceipt | ProgramGraphSnapshot,
    current: ProgramGraphBuildReceipt | ProgramGraphSnapshot,
) -> ProgramGraphDelta:
    """Return the exact node/edge delta, retaining unchanged subroot CIDs."""

    previous_snapshot = _as_snapshot(previous, "previous")
    current_snapshot = _as_snapshot(current, "current")
    return delta_between_snapshots(previous_snapshot, current_snapshot)


def _walk_dependents(
    seeds: Iterable[str],
    edges: Sequence[ProgramGraphEdge],
) -> set[str]:
    rerun: dict[str, list[str]] = defaultdict(list)
    reverse: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        kind = str(edge.edge_kind)
        if kind in _RERUN_FORWARD_KINDS:
            rerun[edge.source_node_cid].append(edge.target_node_cid)
        if kind in _REVERSE_INVALIDATION_KINDS:
            reverse[edge.target_node_cid].append(edge.source_node_cid)
    seen: set[str] = set()
    queue = deque(seeds)
    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        for nxt in rerun.get(node, ()):
            if nxt not in seen:
                queue.append(nxt)
        for nxt in reverse.get(node, ()):
            if nxt not in seen:
                queue.append(nxt)
    return seen


class ProgramGraphInvalidationPlanner:
    """Plan precise dependency-aware invalidation over sealed snapshots."""

    INTERFACE: Final[str] = PROGRAM_GRAPH_INVALIDATION_PLANNER_INTERFACE

    def plan(
        self,
        previous: ProgramGraphBuildReceipt | ProgramGraphSnapshot,
        current: ProgramGraphBuildReceipt | ProgramGraphSnapshot | None = None,
        *,
        delta: ProgramGraphDelta | None = None,
        environment_changed: bool = False,
    ) -> ProgramGraphInvalidationPlan:
        return plan_program_graph_invalidation(
            previous,
            current,
            delta=delta,
            environment_changed=environment_changed,
        )


def plan_program_graph_invalidation(
    previous: ProgramGraphBuildReceipt | ProgramGraphSnapshot,
    current: ProgramGraphBuildReceipt | ProgramGraphSnapshot | None = None,
    *,
    delta: ProgramGraphDelta | None = None,
    environment_changed: bool = False,
) -> ProgramGraphInvalidationPlan:
    """Compute dependency-aware invalidation without unsound omission."""

    previous_snapshot = _as_snapshot(previous, "previous")
    previous_receipt = _as_receipt(previous, "previous")
    environment_changed = _bool(environment_changed, "environment_changed")
    if current is None:
        invalidated_nodes = tuple(previous_snapshot.node_cids)
        invalidated_edges = tuple(previous_snapshot.edge_cids)
        return ProgramGraphInvalidationPlan(
            previous_snapshot_cid=previous_snapshot.program_graph_snapshot_cid,
            current_snapshot_cid=None,
            delta_cid=None,
            invalidated_node_cids=invalidated_nodes,
            invalidated_edge_cids=invalidated_edges,
            retained_subroot_cids=(),
            affected_node_cids=invalidated_nodes,
            full_fallback=True,
            reasons=("snapshot_deleted",),
            environment_changed=environment_changed,
        )
    current_snapshot = _as_snapshot(current, "current")
    current_receipt = _as_receipt(current, "current")
    computed = delta if delta is not None else compute_program_graph_delta(
        previous_snapshot, current_snapshot
    )
    if computed.previous_snapshot_cid != previous_snapshot.program_graph_snapshot_cid:
        raise ProgramGraphBuilderError("delta is not bound to the previous snapshot")
    env_changed = environment_changed or (
        previous_snapshot.environment_binding_set_cid
        != current_snapshot.environment_binding_set_cid
        or previous_snapshot.sealed_binding_cid != current_snapshot.sealed_binding_cid
    )
    if env_changed:
        all_nodes = tuple(
            sorted(set(previous_snapshot.node_cids) | set(current_snapshot.node_cids))
        )
        all_edges = tuple(
            sorted(set(previous_snapshot.edge_cids) | set(current_snapshot.edge_cids))
        )
        return ProgramGraphInvalidationPlan(
            previous_snapshot_cid=previous_snapshot.program_graph_snapshot_cid,
            current_snapshot_cid=current_snapshot.program_graph_snapshot_cid,
            delta_cid=computed.program_graph_delta_cid,
            invalidated_node_cids=all_nodes,
            invalidated_edge_cids=all_edges,
            retained_subroot_cids=(),
            affected_node_cids=all_nodes,
            full_fallback=True,
            reasons=("environment_binding_changed",),
            environment_changed=True,
        )
    if previous_receipt is None or current_receipt is None:
        # Snapshots alone cannot prove independence of retained identities.
        all_nodes = tuple(
            sorted(set(previous_snapshot.node_cids) | set(current_snapshot.node_cids))
        )
        all_edges = tuple(
            sorted(set(previous_snapshot.edge_cids) | set(current_snapshot.edge_cids))
        )
        return ProgramGraphInvalidationPlan(
            previous_snapshot_cid=previous_snapshot.program_graph_snapshot_cid,
            current_snapshot_cid=current_snapshot.program_graph_snapshot_cid,
            delta_cid=computed.program_graph_delta_cid,
            invalidated_node_cids=all_nodes,
            invalidated_edge_cids=all_edges,
            retained_subroot_cids=(),
            affected_node_cids=all_nodes,
            full_fallback=True,
            reasons=("catalog_unavailable",),
            environment_changed=False,
        )

    seeds = set(computed.removed_node_cids) | set(computed.added_node_cids)
    previous_dependents = _walk_dependents(computed.removed_node_cids, previous_receipt.edges)
    current_dependents = _walk_dependents(computed.added_node_cids, current_receipt.edges)
    affected = set(previous_dependents) | set(current_dependents) | seeds
    # Incident edges: any node touching an added/removed edge is affected.
    changed_edges = set(computed.removed_edge_cids) | set(computed.added_edge_cids)
    previous_by_cid = {
        edge.program_graph_edge_cid: edge for edge in previous_receipt.edges
    }
    current_by_cid = {
        edge.program_graph_edge_cid: edge for edge in current_receipt.edges
    }
    for cid in computed.removed_edge_cids:
        edge = previous_by_cid.get(cid)
        if edge is not None:
            affected.add(edge.source_node_cid)
            affected.add(edge.target_node_cid)
    for cid in computed.added_edge_cids:
        edge = current_by_cid.get(cid)
        if edge is not None:
            affected.add(edge.source_node_cid)
            affected.add(edge.target_node_cid)
    retained = tuple(
        sorted(set(computed.retained_subroot_cids) - affected)
    )
    invalidated_nodes = tuple(sorted(affected))
    invalidated_edges = tuple(sorted(changed_edges))
    reasons: list[str] = []
    if computed.removed_node_cids or computed.added_node_cids:
        reasons.append("node_identity_changed")
    if changed_edges:
        reasons.append("incident_edge_changed")
    if previous_dependents or current_dependents:
        reasons.append("dependency_closure")
    if not reasons:
        reasons.append("unchanged")
    return ProgramGraphInvalidationPlan(
        previous_snapshot_cid=previous_snapshot.program_graph_snapshot_cid,
        current_snapshot_cid=current_snapshot.program_graph_snapshot_cid,
        delta_cid=computed.program_graph_delta_cid,
        invalidated_node_cids=invalidated_nodes,
        invalidated_edge_cids=invalidated_edges,
        retained_subroot_cids=retained,
        affected_node_cids=tuple(sorted(affected)),
        full_fallback=False,
        reasons=tuple(sorted(set(reasons))),
        environment_changed=False,
    )


__all__ = [
    "GRAPH_PROJECTIONS",
    "PROGRAM_GRAPH_BUILD_RECEIPT_INTERFACE",
    "PROGRAM_GRAPH_BUILD_RECEIPT_SCHEMA",
    "PROGRAM_GRAPH_BUILDER_INTERFACE",
    "PROGRAM_GRAPH_BUILDER_SCHEMA",
    "PROGRAM_GRAPH_INVALIDATION_PLANNER_INTERFACE",
    "ProgramGraphBuildReceipt",
    "ProgramGraphBuilder",
    "ProgramGraphBuilderError",
    "ProgramGraphInvalidationPlan",
    "ProgramGraphInvalidationPlanner",
    "ProgramGraphSourceUnit",
    "build_program_graph",
    "compute_program_graph_delta",
    "plan_program_graph_invalidation",
]
