"""Deterministic current-tree static program-graph construction and invalidation.

This module is the datasets construction authority for SAWM-006.  It extends
the SAWM-005 ``ProgramGraph*@1`` records with an admitted-Python builder that
emits AST, symbol, import, call, CFG, data-flow, exception, type/effect,
contract, test, and proof projections, then computes exact deltas and a
dependency-aware invalidation plan.

Normative constraints:

* Importing this module never scans a repository or analyzes source.
* Construction binds exact source bytes and environment identities.
* Node/edge/snapshot identities are CID-addressed and order-canonical.
* Unknown, dynamic, native, and unsupported behavior widens an explicit
  frontier; it is never encoded as absence.
* Invalidation over-approximates when resolution is incomplete and never
  omits a resolved dependent.
* Logical cycles (imports, mutual recursion, CFG back-edges) are immutable
  records; the physical CID catalog remains acyclic.
"""

from __future__ import annotations

import ast
import unicodedata
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_graph import (
    PROGRAM_GRAPH_SNAPSHOT_SCHEMA,
    CallsiteRecord,
    ContractDischargeStatus,
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
    ProofObligationGraph,
    ResolutionStatus,
    StaticSuccessorSet,
    assemble_program_graph_snapshot,
    bind_index_manifest,
    delta_between_snapshots,
    is_unresolved_dynamic_edge,
    is_unresolved_dynamic_node,
    program_graph_cid_for,
)


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

PROGRAM_GRAPH_BUILDER_INTERFACE: Final[str] = "ProgramGraphBuilder@1"
PROGRAM_GRAPH_BUILD_RECEIPT_INTERFACE: Final[str] = "ProgramGraphBuildReceipt@1"
PROGRAM_GRAPH_INVALIDATION_PLANNER_INTERFACE: Final[str] = (
    "ProgramGraphInvalidationPlanner@1"
)
PROGRAM_GRAPH_BUILDER_VERSION: Final[str] = "1"
PROGRAM_GRAPH_BUILD_RECEIPT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-graph-build-receipt@1"
)
PROGRAM_GRAPH_COVERAGE_RECEIPT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-graph-coverage-receipt@1"
)
PROGRAM_GRAPH_INVALIDATION_PLAN_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-graph-invalidation-plan@1"
)
PROGRAM_GRAPH_ENVIRONMENT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-graph-environment@1"
)
PROGRAM_GRAPH_SOURCE_MANIFEST_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-graph-source-manifest@1"
)
PROGRAM_GRAPH_DECLARATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-graph-declaration@1"
)

# Importing this module must remain a no-scan operation.  Construction is
# explicit via :func:`build_program_graph` / :class:`ProgramGraphBuilder`.
IMPORT_SCAN_PERFORMED: Final[bool] = False

ADMITTED_LANGUAGE: Final[str] = "python"
PYTHON_SOURCE_SUFFIXES: Final[tuple[str, ...]] = (".py", ".pyi")
CONSTRUCTED_DIMENSIONS: Final[tuple[str, ...]] = (
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

_DYNAMIC_CALLS: Final[frozenset[str]] = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "getattr",
        "setattr",
        "delattr",
        "hasattr",
        "vars",
        "globals",
        "locals",
        "importlib.import_module",
        "importlib.reload",
        "runpy.run_module",
        "runpy.run_path",
        "builtins.eval",
        "builtins.exec",
        "builtins.__import__",
        "builtins.getattr",
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
        "cffi.FFI",
    }
)
_IO_EFFECTS: Final[frozenset[str]] = frozenset(
    {
        "open",
        "print",
        "input",
        "write",
        "read",
        "os.system",
        "subprocess.run",
        "subprocess.Popen",
        "socket.socket",
        "requests.get",
        "requests.post",
    }
)
_SAFE_DECORATORS: Final[frozenset[str]] = frozenset(
    {
        "property",
        "staticmethod",
        "classmethod",
        "dataclass",
        "dataclasses.dataclass",
        "abstractmethod",
        "abc.abstractmethod",
        "override",
        "typing.override",
        "overload",
        "typing.overload",
        "pytest.fixture",
        "fixture",
        "staticmethod",
    }
)
_DOC_CONTRACT_PREFIXES: Final[tuple[tuple[str, str], ...]] = (
    ("requires:", ContractKind.PRECONDITION.value),
    ("pre:", ContractKind.PRECONDITION.value),
    ("precondition:", ContractKind.PRECONDITION.value),
    ("ensures:", ContractKind.POSTCONDITION.value),
    ("post:", ContractKind.POSTCONDITION.value),
    ("postcondition:", ContractKind.POSTCONDITION.value),
    ("raises:", ContractKind.EXCEPTIONAL.value),
)
_DEPENDENCY_EDGE_KINDS: Final[frozenset[str]] = frozenset(
    {
        ProgramGraphEdgeKind.CALLS.value,
        ProgramGraphEdgeKind.IMPORTS.value,
        ProgramGraphEdgeKind.SUCCESSOR.value,
        ProgramGraphEdgeKind.INHERITS.value,
        ProgramGraphEdgeKind.IMPLEMENTS.value,
        ProgramGraphEdgeKind.USES_FIXTURE.value,
        ProgramGraphEdgeKind.TYPE_OF.value,
        ProgramGraphEdgeKind.EFFECT_OF.value,
        ProgramGraphEdgeKind.BINDS_CONTRACT.value,
        ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value,
        ProgramGraphEdgeKind.READS_STATE.value,
        ProgramGraphEdgeKind.WRITES_STATE.value,
        ProgramGraphEdgeKind.RAISES.value,
        ProgramGraphEdgeKind.CATCHES.value,
        ProgramGraphEdgeKind.CFG_NEXT.value,
        ProgramGraphEdgeKind.CFG_BRANCH.value,
        ProgramGraphEdgeKind.DATA_FLOW.value,
        ProgramGraphEdgeKind.EXCEPTION_EDGE.value,
        ProgramGraphEdgeKind.CYCLIC_IMPORT.value,
        ProgramGraphEdgeKind.MUTUAL_RECURSION.value,
    }
)
_FORWARD_INVALIDATION_KINDS: Final[frozenset[str]] = frozenset(
    {
        ProgramGraphEdgeKind.TESTED_BY.value,
        ProgramGraphEdgeKind.PROVED_BY.value,
        ProgramGraphEdgeKind.CONTAINS.value,
        ProgramGraphEdgeKind.DECLARES.value,
    }
)


class ProgramGraphBuilderError(ValueError):
    """Raised when static graph construction inputs or results are unsound."""


class ProgramGraphInvalidationCause(str, Enum):
    SOURCE_CHANGED = "source_changed"
    ENVIRONMENT_CHANGED = "environment_changed"
    DEPENDENT_OF_CHANGED = "dependent_of_changed"
    UNRESOLVED_DYNAMIC_OVERAPPROX = "unresolved_dynamic_overapprox"
    TEST_OF_CHANGED = "test_of_changed"
    PROOF_OF_CHANGED = "proof_of_changed"
    DELETED = "deleted"


# ---------------------------------------------------------------------------
# Frozen construction facts (incremental reuse is source-CID keyed)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProgramGraphCallFact:
    ordinal: int
    callee_name: str
    dynamic_reason: str
    native: bool
    lineno: int


@dataclass(frozen=True, slots=True)
class ProgramGraphCfgEdgeFact:
    source_block: str
    target_block: str
    kind: str
    logical_cycle: bool


@dataclass(frozen=True, slots=True)
class ProgramGraphHandlerFact:
    ordinal: int
    exception_type: str
    name: str


@dataclass(frozen=True, slots=True)
class ProgramGraphNameFact:
    name: str
    ordinal: int
    is_def: bool


@dataclass(frozen=True, slots=True)
class ProgramGraphImportFact:
    module: str
    names: tuple[tuple[str, str], ...]
    level: int
    lineno: int
    is_star: bool
    is_from: bool


@dataclass(frozen=True, slots=True)
class ProgramGraphFunctionFact:
    name: str
    qualified_name: str
    lineno: int
    col_offset: int
    parameters: tuple[str, ...]
    return_annotation: str
    is_async: bool
    class_qualified_name: str
    decorators: tuple[str, ...]
    docstring: str
    calls: tuple[ProgramGraphCallFact, ...]
    cfg_blocks: tuple[str, ...]
    cfg_edges: tuple[ProgramGraphCfgEdgeFact, ...]
    names: tuple[ProgramGraphNameFact, ...]
    raises: tuple[str, ...]
    handlers: tuple[ProgramGraphHandlerFact, ...]
    asserts: tuple[str, ...]
    annotations: tuple[tuple[str, str], ...]
    effects: tuple[str, ...]
    writes: tuple[str, ...]
    incomplete: tuple[str, ...]
    is_test: bool
    is_fixture: bool
    is_proof: bool
    fixture_params: tuple[str, ...]
    bases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProgramGraphClassFact:
    name: str
    qualified_name: str
    lineno: int
    col_offset: int
    bases: tuple[str, ...]
    incomplete: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProgramGraphSymbolFact:
    name: str
    qualified_name: str
    lineno: int


@dataclass(frozen=True, slots=True)
class ProgramGraphUnitFacts:
    """Per-file facts derived only from that file's bytes and path."""

    path: str
    source_cid: str
    module_name: str
    package_name: str
    is_package_init: bool
    parse_error: bool
    language_admitted: bool
    imports: tuple[ProgramGraphImportFact, ...]
    functions: tuple[ProgramGraphFunctionFact, ...]
    classes: tuple[ProgramGraphClassFact, ...]
    symbols: tuple[ProgramGraphSymbolFact, ...]
    incomplete: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProgramGraphCoverageReceipt:
    """Explicit coverage of constructed and incomplete static dimensions."""

    constructed_dimensions: tuple[str, ...]
    incomplete_dimensions: tuple[str, ...]
    unit_count: int
    node_count: int
    edge_count: int
    frontier_count: int
    logical_cycle_edge_count: int
    parse_error_paths: tuple[str, ...]
    dynamic_reasons: tuple[str, ...]

    SCHEMA: ClassVar[str] = PROGRAM_GRAPH_COVERAGE_RECEIPT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "constructed_dimensions": list(self.constructed_dimensions),
            "incomplete_dimensions": list(self.incomplete_dimensions),
            "unit_count": self.unit_count,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "frontier_count": self.frontier_count,
            "logical_cycle_edge_count": self.logical_cycle_edge_count,
            "parse_error_paths": list(self.parse_error_paths),
            "dynamic_reasons": list(self.dynamic_reasons),
        }


@dataclass(frozen=True, slots=True)
class ProgramGraphBuildReceipt:
    """Sealed construction result: snapshot, catalog, and coverage receipt."""

    snapshot: ProgramGraphSnapshot
    nodes: tuple[ProgramGraphNode, ...]
    edges: tuple[ProgramGraphEdge, ...]
    callsites: tuple[CallsiteRecord, ...]
    function_symbols: tuple[FunctionSymbolRecord, ...]
    contract_states: tuple[ContractStateRecord, ...]
    proof_obligation_graphs: tuple[ProofObligationGraph, ...]
    successor_sets: tuple[StaticSuccessorSet, ...]
    frontiers: tuple[DynamicFrontierRecord, ...]
    index_manifests: tuple[ProgramGraphIndexManifest, ...]
    coverage: ProgramGraphCoverageReceipt
    source_cids: tuple[tuple[str, str], ...]
    environment_binding_cid: str
    sealed_binding_cid: str
    incremental: bool
    builder_version: str = PROGRAM_GRAPH_BUILDER_VERSION
    unit_facts: tuple[ProgramGraphUnitFacts, ...] = ()

    SCHEMA: ClassVar[str] = PROGRAM_GRAPH_BUILD_RECEIPT_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_GRAPH_BUILD_RECEIPT_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "edges", tuple(self.edges))
        object.__setattr__(self, "source_cids", tuple(self.source_cids))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "builder_version": self.builder_version,
            "incremental": self.incremental,
            "snapshot_cid": self.snapshot.program_graph_snapshot_cid,
            "canonical_program_graph_cid": self.snapshot.canonical_program_graph_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "sealed_binding_cid": self.sealed_binding_cid,
            "source_cids": [{"path": path, "source_cid": cid} for path, cid in self.source_cids],
            "coverage": self.coverage.to_dict(),
        }

    @property
    def program_graph_build_receipt_cid(self) -> str:
        return program_graph_cid_for(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["program_graph_build_receipt_cid"] = self.program_graph_build_receipt_cid
        payload["snapshot"] = self.snapshot.to_dict()
        return payload

    def source_cid_map(self) -> dict[str, str]:
        return {path: cid for path, cid in self.source_cids}

    def node_by_name(self, kind: str, logical_name: str) -> ProgramGraphNode:
        matches = [
            node
            for node in self.nodes
            if str(node.node_kind) == kind and node.logical_name == logical_name
        ]
        if len(matches) != 1:
            raise KeyError(f"expected one {kind} node named {logical_name!r}, found {len(matches)}")
        return matches[0]

    def nodes_of_kind(self, kind: str) -> tuple[ProgramGraphNode, ...]:
        return tuple(node for node in self.nodes if str(node.node_kind) == kind)

    def edges_of_kind(self, kind: str) -> tuple[ProgramGraphEdge, ...]:
        return tuple(edge for edge in self.edges if str(edge.edge_kind) == kind)


@dataclass(frozen=True, slots=True)
class ProgramGraphInvalidationReason:
    node_cid: str
    cause: str
    origin_cid: str

    def to_dict(self) -> dict[str, str]:
        return {
            "node_cid": self.node_cid,
            "cause": self.cause,
            "origin_cid": self.origin_cid,
        }


@dataclass(frozen=True, slots=True)
class ProgramGraphInvalidationPlan:
    """Dependency-closed invalidation; dependents are never omitted."""

    previous_snapshot_cid: str
    current_snapshot_cid: str
    delta: ProgramGraphDelta
    invalidated_node_cids: tuple[str, ...]
    stale_node_cids: tuple[str, ...]
    dependent_node_cids: tuple[str, ...]
    retained_subroot_cids: tuple[str, ...]
    reasons: tuple[ProgramGraphInvalidationReason, ...]
    omitted_dependents: bool
    conservative: bool
    environment_changed: bool

    SCHEMA: ClassVar[str] = PROGRAM_GRAPH_INVALIDATION_PLAN_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_GRAPH_INVALIDATION_PLANNER_INTERFACE

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "previous_snapshot_cid": self.previous_snapshot_cid,
            "current_snapshot_cid": self.current_snapshot_cid,
            "delta": self.delta.to_dict(),
            "invalidated_node_cids": list(self.invalidated_node_cids),
            "stale_node_cids": list(self.stale_node_cids),
            "dependent_node_cids": list(self.dependent_node_cids),
            "retained_subroot_cids": list(self.retained_subroot_cids),
            "reasons": [item.to_dict() for item in self.reasons],
            "omitted_dependents": self.omitted_dependents,
            "conservative": self.conservative,
            "environment_changed": self.environment_changed,
        }


# ---------------------------------------------------------------------------
# Path / AST helpers
# ---------------------------------------------------------------------------


def _nfc(value: str, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ProgramGraphBuilderError(f"{name} must be a nonempty trimmed string")
    normalized = unicodedata.normalize("NFC", value)
    if any(not char.isprintable() for char in normalized):
        raise ProgramGraphBuilderError(f"{name} must be printable")
    return normalized


def _normalize_path(path: str) -> str:
    value = _nfc(path.replace("\\", "/"), "path")
    normalized = str(PurePosixPath(value))
    if normalized in {".", ".."} or normalized.startswith("../") or normalized.startswith("/"):
        raise ProgramGraphBuilderError("path must be repository-relative")
    return normalized


def _source_bytes(source: str | bytes, path: str) -> bytes:
    if isinstance(source, bytes):
        return source
    if isinstance(source, str):
        return source.encode("utf-8")
    raise ProgramGraphBuilderError(f"source for {path} must be text or bytes")


def _module_name(path: str) -> tuple[str, str, bool]:
    parts = list(PurePosixPath(path).parts)
    is_init = False
    if parts and parts[-1].endswith(PYTHON_SOURCE_SUFFIXES):
        stem = parts[-1].rsplit(".", 1)[0]
        is_init = stem == "__init__"
        parts[-1] = stem
        if is_init:
            parts.pop()
    module = ".".join(parts) or "__main__"
    if is_init:
        package = module
    elif "." in module:
        package = module.rsplit(".", 1)[0]
    else:
        package = ""
    return module, package, is_init


def _is_python_path(path: str) -> bool:
    return path.endswith(PYTHON_SOURCE_SUFFIXES)


def _is_test_path(path: str) -> bool:
    posix = PurePosixPath(path)
    name = posix.name
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
        or "tests" in posix.parts
        or "test" in posix.parts
    )


def _expr_name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _expr_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return _expr_name(node.func)
    if isinstance(node, ast.Subscript):
        return ""
    return ""


def _render(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        text = ast.unparse(node)
    except (AttributeError, TypeError, ValueError):
        return type(node).__name__
    compact = " ".join(text.split())
    return compact[:256]


def _docstring(node: ast.AST) -> str:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
        return ""
    if not node.body:
        return ""
    first = node.body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        value = first.value.value
        if isinstance(value, str):
            return value
    return ""


def _parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    args = node.args
    names = [item.arg for item in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
    if args.vararg:
        names.append(args.vararg.arg)
    if args.kwarg:
        names.append(args.kwarg.arg)
    return tuple(names)


def _decorators(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> tuple[str, ...]:
    values: list[str] = []
    for item in node.decorator_list:
        name = _expr_name(item) or type(item).__name__
        values.append(name)
    return tuple(values)


def _own_nodes(nodes: Sequence[ast.AST]) -> Iterable[ast.AST]:
    for node in nodes:
        yield node
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            yield from _own_nodes((child,))


def _store_names(target: ast.AST | None) -> Iterable[str]:
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            yield from _store_names(element)
    elif isinstance(target, ast.Starred):
        yield from _store_names(target.value)


def _call_reason(name: str) -> tuple[str, bool]:
    simple = name.rsplit(".", 1)[-1] if name else ""
    if name in _DYNAMIC_CALLS or simple in _DYNAMIC_CALLS:
        if simple in {"eval", "exec"} or name.endswith(".eval") or name.endswith(".exec"):
            return DynamicFrontierReason.EVAL.value if simple == "eval" else DynamicFrontierReason.EXEC.value, False
        if simple in {"getattr", "setattr", "delattr", "hasattr", "vars"}:
            return DynamicFrontierReason.REFLECTION.value, False
        if "import" in name or simple == "__import__":
            return DynamicFrontierReason.IMPORT_HOOK.value, False
        return DynamicFrontierReason.DYNAMIC_DISPATCH.value, False
    if name in _NATIVE_CALLS or simple in _NATIVE_CALLS or name.startswith("ctypes."):
        return DynamicFrontierReason.NATIVE_CALL.value, True
    if not name:
        return DynamicFrontierReason.UNKNOWN_CALLEE.value, False
    return "", False


def _sorted_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def _declaration_cid(path: str, qualified_name: str, kind: str, lineno: int, source_cid: str) -> str:
    return cid_for_structured(
        {
            "schema": PROGRAM_GRAPH_DECLARATION_SCHEMA,
            "path": path,
            "qualified_name": qualified_name,
            "kind": kind,
            "lineno": lineno,
            "source_cid": source_cid,
        }
    )


def _environment_cid(bindings: Mapping[str, str] | None) -> str:
    items: list[dict[str, str]] = []
    if bindings is None:
        bindings = {}
    if not isinstance(bindings, Mapping):
        raise ProgramGraphBuilderError("environment_binding must be a string mapping")
    for key, value in bindings.items():
        items.append(
            {
                "key": _nfc(str(key), "environment key"),
                "value": _nfc(str(value), "environment value"),
            }
        )
    items.sort(key=lambda item: (item["key"], item["value"]))
    return cid_for_structured({"schema": PROGRAM_GRAPH_ENVIRONMENT_SCHEMA, "bindings": items})


def _source_manifest_cid(source_cids: Sequence[tuple[str, str]], environment_cid: str) -> str:
    return cid_for_structured(
        {
            "schema": PROGRAM_GRAPH_SOURCE_MANIFEST_SCHEMA,
            "environment_binding_cid": environment_cid,
            "sources": [{"path": path, "source_cid": cid} for path, cid in source_cids],
        }
    )


def _sealed_binding_cid(environment_set_cid: str, environment_cid: str) -> str:
    return cid_for_structured(
        {
            "schema": PROGRAM_GRAPH_ENVIRONMENT_SCHEMA + "#sealed",
            "builder_version": PROGRAM_GRAPH_BUILDER_VERSION,
            "environment_binding_cid": environment_cid,
            "environment_binding_set_cid": environment_set_cid,
            "language": ADMITTED_LANGUAGE,
        }
    )


# ---------------------------------------------------------------------------
# CFG construction
# ---------------------------------------------------------------------------


class _CfgBuilder:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.blocks: list[str] = []
        self.edges: list[ProgramGraphCfgEdgeFact] = []
        self.incomplete: set[str] = set()
        self.loops: list[tuple[str, str]] = []
        self.entry = self.new_block()
        self.exit = ""

    def new_block(self) -> str:
        name = f"{self.prefix}.cfg.{len(self.blocks)}"
        self.blocks.append(name)
        return name

    def edge(self, source: str | None, target: str, kind: str, *, cycle: bool = False) -> None:
        if source is None:
            return
        self.edges.append(
            ProgramGraphCfgEdgeFact(source, target, kind, cycle)
        )

    def statements(self, body: Sequence[ast.stmt], current: str | None) -> str | None:
        for stmt in body:
            if current is None:
                current = self.new_block()
            current = self.statement(stmt, current)
        return current

    def statement(self, stmt: ast.stmt, current: str) -> str | None:
        if isinstance(stmt, ast.If):
            then_block = self.new_block()
            join = self.new_block()
            self.edge(current, then_block, ProgramGraphEdgeKind.CFG_BRANCH.value)
            then_end = self.statements(stmt.body, then_block)
            self.edge(then_end, join, ProgramGraphEdgeKind.CFG_NEXT.value)
            if stmt.orelse:
                else_block = self.new_block()
                self.edge(current, else_block, ProgramGraphEdgeKind.CFG_BRANCH.value)
                else_end = self.statements(stmt.orelse, else_block)
                self.edge(else_end, join, ProgramGraphEdgeKind.CFG_NEXT.value)
            else:
                self.edge(current, join, ProgramGraphEdgeKind.CFG_BRANCH.value)
            return join
        if isinstance(stmt, (ast.While, ast.For, ast.AsyncFor)):
            header = self.new_block()
            body_block = self.new_block()
            after = self.new_block()
            self.edge(current, header, ProgramGraphEdgeKind.CFG_NEXT.value)
            self.edge(header, body_block, ProgramGraphEdgeKind.CFG_BRANCH.value)
            self.edge(header, after, ProgramGraphEdgeKind.CFG_BRANCH.value)
            self.loops.append((header, after))
            body_end = self.statements(stmt.body, body_block)
            self.edge(body_end, header, ProgramGraphEdgeKind.CFG_NEXT.value, cycle=True)
            self.loops.pop()
            if stmt.orelse:
                self.incomplete.add("cfg")
                else_block = self.new_block()
                self.edge(header, else_block, ProgramGraphEdgeKind.CFG_BRANCH.value)
                else_end = self.statements(stmt.orelse, else_block)
                self.edge(else_end, after, ProgramGraphEdgeKind.CFG_NEXT.value)
            return after
        if isinstance(stmt, ast.Try):
            self.incomplete.add("cfg")
            self.incomplete.add("exception")
            body_block = self.new_block()
            join = self.new_block()
            self.edge(current, body_block, ProgramGraphEdgeKind.CFG_NEXT.value)
            body_end = self.statements(stmt.body, body_block)
            self.edge(body_end, join, ProgramGraphEdgeKind.CFG_NEXT.value)
            for handler in stmt.handlers:
                handler_block = self.new_block()
                self.edge(body_block, handler_block, ProgramGraphEdgeKind.EXCEPTION_EDGE.value)
                handler_end = self.statements(handler.body, handler_block)
                self.edge(handler_end, join, ProgramGraphEdgeKind.CFG_NEXT.value)
            if stmt.orelse:
                else_block = self.new_block()
                self.edge(body_end, else_block, ProgramGraphEdgeKind.CFG_NEXT.value)
                else_end = self.statements(stmt.orelse, else_block)
                self.edge(else_end, join, ProgramGraphEdgeKind.CFG_NEXT.value)
            if stmt.finalbody:
                final_block = self.new_block()
                self.edge(join, final_block, ProgramGraphEdgeKind.CFG_NEXT.value)
                final_end = self.statements(stmt.finalbody, final_block)
                return final_end
            return join
        if isinstance(stmt, ast.Return):
            if not self.exit:
                self.exit = self.new_block()
            self.edge(current, self.exit, ProgramGraphEdgeKind.CFG_NEXT.value)
            return None
        if isinstance(stmt, ast.Raise):
            if not self.exit:
                self.exit = self.new_block()
            self.edge(current, self.exit, ProgramGraphEdgeKind.EXCEPTION_EDGE.value)
            return None
        if isinstance(stmt, ast.Break):
            if self.loops:
                self.edge(current, self.loops[-1][1], ProgramGraphEdgeKind.CFG_NEXT.value)
            else:
                self.incomplete.add("cfg")
            return None
        if isinstance(stmt, ast.Continue):
            if self.loops:
                self.edge(
                    current,
                    self.loops[-1][0],
                    ProgramGraphEdgeKind.CFG_NEXT.value,
                    cycle=True,
                )
            else:
                self.incomplete.add("cfg")
            return None
        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            return self.statements(
                stmt.body,
                current,
            )
        if isinstance(stmt, ast.Match):
            self.incomplete.add("cfg")
            join = self.new_block()
            for case in stmt.cases:
                case_block = self.new_block()
                self.edge(current, case_block, ProgramGraphEdgeKind.CFG_BRANCH.value)
                case_end = self.statements(case.body, case_block)
                self.edge(case_end, join, ProgramGraphEdgeKind.CFG_NEXT.value)
            return join
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return current
        return current

    def finish(self, last: str | None) -> tuple[tuple[str, ...], tuple[ProgramGraphCfgEdgeFact, ...], tuple[str, ...]]:
        if not self.exit:
            self.exit = self.new_block()
        self.edge(last, self.exit, ProgramGraphEdgeKind.CFG_NEXT.value)
        unique_edges: dict[tuple[str, str, str, bool], ProgramGraphCfgEdgeFact] = {}
        for edge in self.edges:
            unique_edges[(edge.source_block, edge.target_block, edge.kind, edge.logical_cycle)] = edge
        ordered = tuple(
            sorted(
                unique_edges.values(),
                key=lambda item: (item.source_block, item.target_block, item.kind, item.logical_cycle),
            )
        )
        return tuple(self.blocks), ordered, _sorted_unique(self.incomplete)


def _function_cfg(node: ast.FunctionDef | ast.AsyncFunctionDef, prefix: str) -> tuple[tuple[str, ...], tuple[ProgramGraphCfgEdgeFact, ...], tuple[str, ...]]:
    builder = _CfgBuilder(prefix)
    last = builder.statements(node.body, builder.entry)
    return builder.finish(last)


# ---------------------------------------------------------------------------
# Per-file extraction
# ---------------------------------------------------------------------------


def _bases(node: ast.ClassDef) -> tuple[str, ...]:
    names: list[str] = []
    for base in node.bases:
        name = _expr_name(base)
        if name:
            names.append(name)
        else:
            names.append("<dynamic-base>")
    return tuple(names)


def _doc_contracts(docstring: str) -> list[tuple[str, str]]:
    clauses: list[tuple[str, str]] = []
    for raw_line in docstring.splitlines():
        line = raw_line.strip()
        lower = line.lower()
        for prefix, kind in _DOC_CONTRACT_PREFIXES:
            if lower.startswith(prefix):
                rest = line[len(prefix) :].strip() or prefix.rstrip(":")
                clauses.append((kind, rest[:256]))
                break
    return clauses


def _is_fixture(decorators: Sequence[str], name: str, path: str) -> bool:
    if any(item == "fixture" or item.endswith(".fixture") for item in decorators):
        return True
    return PurePosixPath(path).name == "conftest.py" and not name.startswith("test_")


def _is_test_function(name: str, path: str, class_name: str) -> bool:
    if name.startswith("test_"):
        return True
    if class_name.rsplit(".", 1)[-1].startswith("Test") and not name.startswith("_"):
        return _is_test_path(path)
    return False


def _is_proof_function(name: str, decorators: Sequence[str]) -> bool:
    if name.startswith(("proof_", "lemma_", "theorem_")):
        return True
    return any("prove" in item.lower() or item.endswith(".proof") for item in decorators)


def _extract_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    module: str,
    class_qualified: str,
    path: str,
    under_control: bool,
) -> ProgramGraphFunctionFact:
    qualified = f"{class_qualified}.{node.name}" if class_qualified else f"{module}.{node.name}"
    decorators = _decorators(node)
    incomplete: set[str] = set()
    if under_control:
        incomplete.add("symbol")
    if any(
        item not in _SAFE_DECORATORS and not item.endswith((".fixture", ".setter", ".getter", ".deleter"))
        for item in decorators
    ):
        incomplete.add("effect")
        incomplete.add("call")
    calls: list[ProgramGraphCallFact] = []
    names: list[ProgramGraphNameFact] = []
    raises: list[str] = []
    handlers: list[ProgramGraphHandlerFact] = []
    asserts: list[str] = []
    annotations: list[tuple[str, str]] = []
    effects: list[str] = []
    writes: list[str] = []
    call_ordinal = 0
    name_ordinal = 0
    handler_ordinal = 0
    if node.returns is not None:
        rendered = _render(node.returns)
        annotations.append(("return", rendered or "dynamic"))
        if not rendered:
            incomplete.add("type")
    for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
        if arg.arg in {"self", "cls"}:
            continue
        if arg.annotation is not None:
            rendered = _render(arg.annotation)
            annotations.append((arg.arg, rendered or "dynamic"))
            if not rendered:
                incomplete.add("type")
        else:
            incomplete.add("type")
    if node.returns is None:
        incomplete.add("type")
    for child in _own_nodes(node.body):
        if isinstance(child, ast.Call):
            callee = _expr_name(child.func)
            reason, native = _call_reason(callee)
            if isinstance(child.func, ast.Subscript) or callee == "":
                reason = reason or DynamicFrontierReason.DYNAMIC_DISPATCH.value
                incomplete.add("call")
            if reason:
                incomplete.add("call")
                if reason in {
                    DynamicFrontierReason.EVAL.value,
                    DynamicFrontierReason.EXEC.value,
                    DynamicFrontierReason.REFLECTION.value,
                    DynamicFrontierReason.IMPORT_HOOK.value,
                    DynamicFrontierReason.NATIVE_CALL.value,
                }:
                    incomplete.add("effect")
            if callee in _IO_EFFECTS or callee.rsplit(".", 1)[-1] in {"open", "print", "write"}:
                effects.append("io")
                incomplete.add("effect")
            if native:
                effects.append("native")
            calls.append(
                ProgramGraphCallFact(call_ordinal, callee or "<dynamic-call>", reason, native, getattr(child, "lineno", 0))
            )
            call_ordinal += 1
        elif isinstance(child, ast.Raise):
            raises.append(_expr_name(child.exc) or "<unknown-exception>")
        elif isinstance(child, ast.ExceptHandler):
            types = child.type.elts if isinstance(child.type, ast.Tuple) else (child.type,)
            for item in types:
                handlers.append(
                    ProgramGraphHandlerFact(
                        handler_ordinal,
                        _expr_name(item) or "BaseException",
                        child.name or "",
                    )
                )
                handler_ordinal += 1
        elif isinstance(child, ast.Assert):
            asserts.append(_render(child.test) or "assert")
        elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
            rendered = _render(child.annotation)
            annotations.append((child.target.id, rendered or "dynamic"))
            names.append(ProgramGraphNameFact(child.target.id, name_ordinal, True))
            name_ordinal += 1
        elif isinstance(child, ast.Assign):
            for target in child.targets:
                for stored in _store_names(target):
                    names.append(ProgramGraphNameFact(stored, name_ordinal, True))
                    name_ordinal += 1
                if isinstance(target, ast.Attribute):
                    writes.append(_expr_name(target) or target.attr)
                    effects.append("write_state")
        elif isinstance(child, ast.AugAssign):
            for stored in _store_names(child.target):
                names.append(ProgramGraphNameFact(stored, name_ordinal, True))
                name_ordinal += 1
            if isinstance(child.target, ast.Attribute):
                writes.append(_expr_name(child.target) or child.target.attr)
                effects.append("write_state")
        elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            names.append(ProgramGraphNameFact(child.id, name_ordinal, False))
            name_ordinal += 1
        elif isinstance(child, (ast.Yield, ast.YieldFrom, ast.Await)):
            incomplete.add("cfg")
            incomplete.add("data_flow")
    cfg_blocks, cfg_edges, cfg_incomplete = _function_cfg(node, qualified)
    incomplete.update(cfg_incomplete)
    if any(not item.is_def for item in names) and any(
        edge.logical_cycle for edge in cfg_edges
    ):
        incomplete.add("data_flow")
    parameters = _parameters(node)
    fixture_params = tuple(
        item for item in parameters if item not in {"self", "cls"}
    )
    return ProgramGraphFunctionFact(
        name=node.name,
        qualified_name=qualified,
        lineno=getattr(node, "lineno", 1),
        col_offset=getattr(node, "col_offset", 0),
        parameters=parameters,
        return_annotation=_render(node.returns),
        is_async=isinstance(node, ast.AsyncFunctionDef),
        class_qualified_name=class_qualified,
        decorators=decorators,
        docstring=_docstring(node),
        calls=tuple(calls),
        cfg_blocks=cfg_blocks,
        cfg_edges=cfg_edges,
        names=tuple(names),
        raises=tuple(raises),
        handlers=tuple(handlers),
        asserts=tuple(asserts),
        annotations=tuple(annotations),
        effects=_sorted_unique(effects),
        writes=_sorted_unique(writes),
        incomplete=_sorted_unique(incomplete),
        is_test=_is_test_function(node.name, path, class_qualified),
        is_fixture=_is_fixture(decorators, node.name, path),
        is_proof=_is_proof_function(node.name, decorators),
        fixture_params=fixture_params,
        bases=(),
    )


def _walk_definitions(
    nodes: Sequence[ast.stmt],
    *,
    module: str,
    path: str,
    class_qualified: str = "",
    under_control: bool = False,
) -> tuple[list[ProgramGraphFunctionFact], list[ProgramGraphClassFact], list[ProgramGraphSymbolFact]]:
    functions: list[ProgramGraphFunctionFact] = []
    classes: list[ProgramGraphClassFact] = []
    symbols: list[ProgramGraphSymbolFact] = []
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                _extract_function(
                    node,
                    module=module,
                    class_qualified=class_qualified,
                    path=path,
                    under_control=under_control,
                )
            )
            nested_fn, nested_cls, nested_sym = _walk_definitions(
                node.body,
                module=module,
                path=path,
                class_qualified=f"{class_qualified}.{node.name}" if class_qualified else f"{module}.{node.name}",
                under_control=under_control,
            )
            # Nested classes inside functions stay associated with the nested qualifier.
            functions.extend(nested_fn)
            classes.extend(nested_cls)
            symbols.extend(nested_sym)
        elif isinstance(node, ast.ClassDef):
            qualified = f"{class_qualified}.{node.name}" if class_qualified else f"{module}.{node.name}"
            bases = _bases(node)
            incomplete = []
            if under_control:
                incomplete.append("symbol")
            if any(item == "<dynamic-base>" for item in bases):
                incomplete.append("type")
            classes.append(
                ProgramGraphClassFact(
                    name=node.name,
                    qualified_name=qualified,
                    lineno=getattr(node, "lineno", 1),
                    col_offset=getattr(node, "col_offset", 0),
                    bases=tuple(item for item in bases if item != "<dynamic-base>"),
                    incomplete=_sorted_unique(incomplete),
                )
            )
            child_fn, child_cls, child_sym = _walk_definitions(
                node.body,
                module=module,
                path=path,
                class_qualified=qualified,
                under_control=under_control,
            )
            functions.extend(child_fn)
            classes.extend(child_cls)
            symbols.extend(child_sym)
        elif isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.Match)):
            bodies: list[Sequence[ast.stmt]] = []
            if isinstance(node, ast.If):
                bodies.extend((node.body, node.orelse))
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                bodies.extend((node.body, node.orelse))
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                bodies.append(node.body)
            elif isinstance(node, ast.Try):
                bodies.append(node.body)
                bodies.extend(handler.body for handler in node.handlers)
                bodies.extend((node.orelse, node.finalbody))
            elif isinstance(node, ast.Match):
                bodies.extend(case.body for case in node.cases)
            for body in bodies:
                child_fn, child_cls, child_sym = _walk_definitions(
                    body,
                    module=module,
                    path=path,
                    class_qualified=class_qualified,
                    under_control=True,
                )
                functions.extend(child_fn)
                classes.extend(child_cls)
                symbols.extend(child_sym)
        elif isinstance(node, ast.Assign) and not class_qualified:
            for target in node.targets:
                for stored in _store_names(target):
                    symbols.append(
                        ProgramGraphSymbolFact(
                            name=stored,
                            qualified_name=f"{module}.{stored}",
                            lineno=getattr(node, "lineno", 1),
                        )
                    )
        elif isinstance(node, ast.AnnAssign) and not class_qualified and isinstance(node.target, ast.Name):
            symbols.append(
                ProgramGraphSymbolFact(
                    name=node.target.id,
                    qualified_name=f"{module}.{node.target.id}",
                    lineno=getattr(node, "lineno", 1),
                )
            )
    return functions, classes, symbols


def _extract_imports(tree: ast.AST) -> tuple[ProgramGraphImportFact, ...]:
    facts: list[ProgramGraphImportFact] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                facts.append(
                    ProgramGraphImportFact(
                        module=alias.name,
                        names=((alias.name, local),),
                        level=0,
                        lineno=getattr(node, "lineno", 1),
                        is_star=False,
                        is_from=False,
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            pairs: list[tuple[str, str]] = []
            is_star = False
            for alias in node.names:
                if alias.name == "*":
                    is_star = True
                    pairs.append(("*", "*"))
                else:
                    pairs.append((alias.name, alias.asname or alias.name))
            facts.append(
                ProgramGraphImportFact(
                    module=module,
                    names=tuple(pairs),
                    level=int(node.level or 0),
                    lineno=getattr(node, "lineno", 1),
                    is_star=is_star,
                    is_from=True,
                )
            )
    facts.sort(key=lambda item: (item.lineno, item.module, item.names))
    return tuple(facts)


def extract_unit_facts(path: str, source: str | bytes) -> ProgramGraphUnitFacts:
    """Extract source-local facts.  Never imports or executes the unit."""

    path = _normalize_path(path)
    raw = _source_bytes(source, path)
    source_cid = cid_for_bytes(raw)
    module, package, is_init = _module_name(path)
    if not _is_python_path(path):
        return ProgramGraphUnitFacts(
            path=path,
            source_cid=source_cid,
            module_name=module,
            package_name=package,
            is_package_init=is_init,
            parse_error=False,
            language_admitted=False,
            imports=(),
            functions=(),
            classes=(),
            symbols=(),
            incomplete=("ast", "symbol"),
        )
    try:
        text = raw.decode("utf-8")
        tree = ast.parse(text, filename=path, type_comments=True)
    except (UnicodeDecodeError, SyntaxError, ValueError, RecursionError):
        return ProgramGraphUnitFacts(
            path=path,
            source_cid=source_cid,
            module_name=module,
            package_name=package,
            is_package_init=is_init,
            parse_error=True,
            language_admitted=True,
            imports=(),
            functions=(),
            classes=(),
            symbols=(),
            incomplete=CONSTRUCTED_DIMENSIONS,
        )
    functions, classes, symbols = _walk_definitions(tree.body, module=module, path=path)
    functions.sort(key=lambda item: (item.qualified_name, item.lineno, item.col_offset))
    classes.sort(key=lambda item: (item.qualified_name, item.lineno, item.col_offset))
    symbols.sort(key=lambda item: (item.qualified_name, item.lineno))
    imports = _extract_imports(tree)
    incomplete = {item for fn in functions for item in fn.incomplete}
    incomplete.update(item for cls in classes for item in cls.incomplete)
    if any(fact.is_star for fact in imports):
        incomplete.add("import")
    return ProgramGraphUnitFacts(
        path=path,
        source_cid=source_cid,
        module_name=module,
        package_name=package,
        is_package_init=is_init,
        parse_error=False,
        language_admitted=True,
        imports=imports,
        functions=tuple(functions),
        classes=tuple(classes),
        symbols=tuple(symbols),
        incomplete=_sorted_unique(incomplete),
    )


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------


@dataclass
class _NodeBag:
    language: str
    source_cid: str
    env_cid: str
    nodes: dict[str, ProgramGraphNode] = field(default_factory=dict)
    edges: dict[str, ProgramGraphEdge] = field(default_factory=dict)
    callsites: dict[str, CallsiteRecord] = field(default_factory=dict)
    functions: dict[str, FunctionSymbolRecord] = field(default_factory=dict)
    contracts: dict[str, ContractStateRecord] = field(default_factory=dict)
    by_logical: dict[tuple[str, str], ProgramGraphNode] = field(default_factory=dict)

    def add_node(
        self,
        kind: str,
        logical_name: str,
        *,
        source_cid: str | None = None,
        declaration_cid: str | None = None,
        record_cid: str | None = None,
        unavailable: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> ProgramGraphNode:
        node = ProgramGraphNode(
            node_kind=kind,
            language=self.language,
            logical_name=logical_name,
            source_cid=source_cid or self.source_cid,
            declaration_cid=declaration_cid,
            environment_binding_cid=self.env_cid,
            record_cid=record_cid,
            unavailable_dimensions=tuple(unavailable),
            metadata=dict(metadata or {}),
        )
        self.nodes[node.program_graph_node_cid] = node
        self.by_logical[(kind, logical_name)] = node
        return node

    def add_edge(
        self,
        kind: str,
        source: ProgramGraphNode,
        target: ProgramGraphNode,
        *,
        status: str = ResolutionStatus.DEFINITE.value,
        cycle: bool = False,
        unavailable: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> ProgramGraphEdge:
        if kind in {
            ProgramGraphEdgeKind.CYCLIC_IMPORT.value,
            ProgramGraphEdgeKind.MUTUAL_RECURSION.value,
        }:
            cycle = True
        if kind == ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value and status == ResolutionStatus.DEFINITE.value:
            status = ResolutionStatus.UNRESOLVED.value
        if status in {ResolutionStatus.UNRESOLVED.value, ResolutionStatus.UNAVAILABLE.value} and not unavailable:
            unavailable = ("incomplete_analysis",)
        edge = ProgramGraphEdge(
            edge_kind=kind,
            source_node_cid=source.program_graph_node_cid,
            target_node_cid=target.program_graph_node_cid,
            language=self.language,
            environment_binding_cid=self.env_cid,
            resolution_status=status,
            logical_cycle=cycle,
            unavailable_dimensions=tuple(unavailable),
            metadata=dict(metadata or {}),
        )
        self.edges[edge.program_graph_edge_cid] = edge
        return edge


def _package_names(module_name: str) -> tuple[str, ...]:
    parts = module_name.split(".")
    names = []
    for index in range(len(parts)):
        names.append(".".join(parts[: index + 1]))
    return tuple(names)


def _resolve_relative(current_package: str, level: int, module: str) -> str | None:
    if level <= 0:
        return module
    parts = current_package.split(".") if current_package else []
    climb = level - 1
    if climb > len(parts):
        return None
    if climb:
        parts = parts[: len(parts) - climb]
    if module:
        parts = [*parts, *module.split(".")] if parts else module.split(".")
    return ".".join(item for item in parts if item)


def _sccs(pairs: Sequence[tuple[str, str]]) -> list[set[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    nodes: set[str] = set()
    for source, target in pairs:
        graph[source].add(target)
        nodes.add(source)
        nodes.add(target)
    index = 0
    stack: list[str] = []
    onstack: set[str] = set()
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    result: list[set[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlink[node] = index
        index += 1
        stack.append(node)
        onstack.add(node)
        for nxt in graph.get(node, ()):
            if nxt not in indices:
                strongconnect(nxt)
                lowlink[node] = min(lowlink[node], lowlink[nxt])
            elif nxt in onstack:
                lowlink[node] = min(lowlink[node], indices[nxt])
        if lowlink[node] == indices[node]:
            component: set[str] = set()
            while True:
                item = stack.pop()
                onstack.remove(item)
                component.add(item)
                if item == node:
                    break
            result.append(component)

    for node in sorted(nodes):
        if node not in indices:
            strongconnect(node)
    return result


def _seal_logical_cycle_edges(
    edges: Mapping[str, ProgramGraphEdge],
) -> dict[str, ProgramGraphEdge]:
    """Rewrite unmarked directed cycles as immutable logical-cycle records.

    Physical CIDs stay acyclic; only the logical ``logical_cycle`` bit is set.
    CALLS/IMPORTS/TESTED_BY/SUCCESSOR paths can close a cycle without a
    dedicated mutual-recursion or cyclic-import edge.  Snapshot verification
    requires every directed cycle to carry at least one such bit, so every
    intra-SCC edge of a cyclic component is sealed.
    """

    pairs = [
        (edge.source_node_cid, edge.target_node_cid) for edge in edges.values()
    ]
    cyclic_component: dict[str, int] = {}
    for index, component in enumerate(_sccs(pairs)):
        cyclic = len(component) > 1 or any(
            source == target and source in component for source, target in pairs
        )
        if not cyclic:
            continue
        for node in component:
            cyclic_component[node] = index
    sealed: dict[str, ProgramGraphEdge] = {}
    for edge in edges.values():
        source_scc = cyclic_component.get(edge.source_node_cid)
        target_scc = cyclic_component.get(edge.target_node_cid)
        if (
            not edge.logical_cycle
            and source_scc is not None
            and source_scc == target_scc
        ):
            edge = replace(edge, logical_cycle=True)
        sealed[edge.program_graph_edge_cid] = edge
    return sealed


def _link_units(
    units: Sequence[ProgramGraphUnitFacts],
    *,
    language: str,
    env_cid: str,
    environment_set_cid: str,
    sealed_cid: str,
    incremental: bool,
) -> ProgramGraphBuildReceipt:
    bags: dict[str, _NodeBag] = {}
    module_nodes: dict[str, ProgramGraphNode] = {}
    package_nodes: dict[str, ProgramGraphNode] = {}
    function_nodes: dict[str, ProgramGraphNode] = {}
    class_nodes: dict[str, ProgramGraphNode] = {}
    function_decls: dict[str, str] = {}
    class_decls: dict[str, str] = {}
    source_nodes: dict[str, ProgramGraphNode] = {}
    aliases: dict[str, dict[str, str]] = defaultdict(dict)
    import_targets: dict[str, list[tuple[ProgramGraphNode, str, bool]]] = defaultdict(list)
    all_nodes: dict[str, ProgramGraphNode] = {}
    all_edges: dict[str, ProgramGraphEdge] = {}
    all_callsites: dict[str, CallsiteRecord] = {}
    all_functions: dict[str, FunctionSymbolRecord] = {}
    all_contracts: dict[str, ContractStateRecord] = {}
    incomplete: set[str] = set()
    parse_errors: list[str] = []
    package_source: dict[str, str] = {}

    for unit in units:
        bags[unit.path] = _NodeBag(language, unit.source_cid, env_cid)
        if unit.parse_error or not unit.language_admitted:
            incomplete.update(unit.incomplete)
            if unit.parse_error:
                parse_errors.append(unit.path)
        if unit.is_package_init and unit.module_name:
            package_source[unit.module_name] = unit.source_cid
        incomplete.update(unit.incomplete)

    # Package and module skeleton.
    for unit in units:
        bag = bags[unit.path]
        source_node = bag.add_node(
            ProgramGraphNodeKind.SOURCE.value,
            unit.path,
            metadata={"path": unit.path},
            unavailable=unit.incomplete if not unit.language_admitted or unit.parse_error else (),
        )
        source_nodes[unit.path] = source_node
        ast_unavailable = ("ast",) if (unit.parse_error or not unit.language_admitted) else ()
        ast_node = bag.add_node(
            ProgramGraphNodeKind.AST.value,
            f"{unit.module_name}#ast",
            unavailable=ast_unavailable,
            metadata={"path": unit.path},
        )
        bag.add_edge(ProgramGraphEdgeKind.CONTAINS.value, source_node, ast_node)
        for package in _package_names(unit.package_name or unit.module_name):
            if package in package_nodes:
                continue
            pkg_source = package_source.get(package) or cid_for_bytes(package.encode("utf-8"))
            pkg_bag = bag if package in {unit.package_name, unit.module_name} else bags[unit.path]
            package_nodes[package] = pkg_bag.add_node(
                ProgramGraphNodeKind.PACKAGE.value,
                package,
                source_cid=pkg_source,
                metadata={"package": package},
            )
        parent = None
        for package in _package_names(unit.package_name or unit.module_name):
            node = package_nodes[package]
            if parent is not None and parent.program_graph_node_cid != node.program_graph_node_cid:
                bags[unit.path].add_edge(ProgramGraphEdgeKind.CONTAINS.value, parent, node)
            parent = node
        module_node = bag.add_node(
            ProgramGraphNodeKind.MODULE.value,
            unit.module_name,
            unavailable=unit.incomplete,
            metadata={"path": unit.path},
        )
        module_nodes[unit.module_name] = module_node
        bag.add_edge(ProgramGraphEdgeKind.CONTAINS.value, source_node, module_node)
        bag.add_edge(ProgramGraphEdgeKind.CONTAINS.value, module_node, ast_node)
        if unit.package_name and unit.package_name in package_nodes and unit.package_name != unit.module_name:
            bag.add_edge(ProgramGraphEdgeKind.CONTAINS.value, package_nodes[unit.package_name], module_node)
        elif unit.module_name in package_nodes:
            bag.add_edge(ProgramGraphEdgeKind.CONTAINS.value, package_nodes[unit.module_name], module_node)

        current_package = unit.module_name if unit.is_package_init else unit.package_name
        for fact in unit.imports:
            resolved = _resolve_relative(current_package, fact.level, fact.module)
            status = ResolutionStatus.DEFINITE.value
            unavailable: tuple[str, ...] = ()
            if fact.is_star:
                status = ResolutionStatus.UNRESOLVED.value
                unavailable = ("import",)
                incomplete.add("import")
            if resolved is None:
                status = ResolutionStatus.UNRESOLVED.value
                unavailable = ("import",)
                incomplete.add("import")
                resolved = fact.module or "<relative-import>"
            for imported, local in fact.names:
                logical = f"{unit.module_name} imports {resolved}" + (f".{imported}" if fact.is_from and imported != "*" else "")
                binding = bag.add_node(
                    ProgramGraphNodeKind.IMPORT_BINDING.value,
                    logical,
                    unavailable=unavailable,
                    metadata={"lineno": fact.lineno, "local": local},
                )
                bag.add_edge(
                    ProgramGraphEdgeKind.IMPORTS.value,
                    module_node,
                    binding,
                    status=status,
                    unavailable=unavailable,
                )
                target_name = resolved if not fact.is_from or imported == "*" else f"{resolved}.{imported}" if resolved else imported
                if status == ResolutionStatus.DEFINITE.value and local != "*":
                    aliases[unit.module_name][local] = target_name
                    if not fact.is_from:
                        # ``import pkg.mod`` binds ``pkg`` to the package root.
                        aliases[unit.module_name][local] = resolved
                import_targets[unit.module_name].append((binding, target_name if fact.is_from else resolved, fact.is_star))

        for cls in unit.classes:
            decl = _declaration_cid(unit.path, cls.qualified_name, "class", cls.lineno, unit.source_cid)
            class_decls[cls.qualified_name] = decl
            node = bag.add_node(
                ProgramGraphNodeKind.CLASS.value,
                cls.qualified_name,
                declaration_cid=decl,
                unavailable=cls.incomplete,
                metadata={"lineno": cls.lineno},
            )
            class_nodes[cls.qualified_name] = node
            bag.add_edge(ProgramGraphEdgeKind.DECLARES.value, module_node, node)
            bag.add_edge(ProgramGraphEdgeKind.CONTAINS.value, module_node, node)

        for symbol in unit.symbols:
            node = bag.add_node(
                ProgramGraphNodeKind.SYMBOL.value,
                symbol.qualified_name,
                declaration_cid=_declaration_cid(unit.path, symbol.qualified_name, "symbol", symbol.lineno, unit.source_cid),
                metadata={"lineno": symbol.lineno},
            )
            bag.add_edge(ProgramGraphEdgeKind.DECLARES.value, module_node, node)

        for fn in unit.functions:
            decl = _declaration_cid(unit.path, fn.qualified_name, "function", fn.lineno, unit.source_cid)
            function_decls[fn.qualified_name] = decl
            record = FunctionSymbolRecord(
                language=language,
                logical_name=fn.qualified_name,
                source_cid=unit.source_cid,
                declaration_cid=decl,
                parameter_names=fn.parameters,
                return_annotation=fn.return_annotation,
                unavailable_dimensions=fn.incomplete,
            )
            bag.functions[record.function_symbol_record_cid] = record
            kind = ProgramGraphNodeKind.FUNCTION.value
            if fn.is_test:
                kind = ProgramGraphNodeKind.TEST.value
            elif fn.is_fixture:
                kind = ProgramGraphNodeKind.FIXTURE.value
            node = bag.add_node(
                kind,
                fn.qualified_name,
                declaration_cid=decl,
                record_cid=record.function_symbol_record_cid if kind == ProgramGraphNodeKind.FUNCTION.value else None,
                unavailable=fn.incomplete,
                metadata={"lineno": fn.lineno, "path": unit.path},
            )
            if fn.is_test or fn.is_fixture:
                # Tests/fixtures still participate in the function index for call resolution.
                function_nodes[fn.qualified_name] = node
            else:
                function_nodes[fn.qualified_name] = node
            owner = class_nodes.get(fn.class_qualified_name, module_node)
            bag.add_edge(ProgramGraphEdgeKind.DECLARES.value, owner, node)
            bag.add_edge(ProgramGraphEdgeKind.CONTAINS.value, owner, node)
            if fn.is_async:
                incomplete.add("cfg")

    # Resolve inheritance against the current tree.
    for unit in units:
        bag = bags[unit.path]
        for cls in unit.classes:
            node = class_nodes[cls.qualified_name]
            for base in cls.bases:
                target_name = aliases[unit.module_name].get(base, base)
                if "." not in target_name and unit.module_name:
                    candidate = f"{unit.module_name}.{target_name}"
                else:
                    candidate = target_name
                target = class_nodes.get(candidate) or class_nodes.get(target_name)
                if target is not None:
                    bag.add_edge(ProgramGraphEdgeKind.INHERITS.value, node, target)
                else:
                    incomplete.add("type")
                    dynamic = bag.add_node(
                        ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value,
                        f"{cls.qualified_name} inherits {base}",
                        unavailable=("type",),
                    )
                    bag.add_edge(
                        ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value,
                        node,
                        dynamic,
                        status=ResolutionStatus.UNRESOLVED.value,
                        unavailable=("type",),
                    )

    # Import successors and cyclic imports.
    import_pairs: list[tuple[str, str]] = []
    for unit in units:
        for binding, target_name, is_star in import_targets[unit.module_name]:
            module_target = None
            if target_name in module_nodes:
                module_target = module_nodes[target_name]
            else:
                # ``from pkg.mod import fn`` may target a function or the module prefix.
                if "." in target_name:
                    prefix = target_name.rsplit(".", 1)[0]
                    module_target = module_nodes.get(prefix)
            if module_target is not None:
                bags[unit.path].add_edge(
                    ProgramGraphEdgeKind.SUCCESSOR.value,
                    binding,
                    module_target,
                    status=ResolutionStatus.UNRESOLVED.value if is_star else ResolutionStatus.DEFINITE.value,
                    unavailable=("import",) if is_star else (),
                )
                import_pairs.append((unit.module_name, module_target.logical_name))
            elif is_star or target_name:
                incomplete.add("import")
                dynamic = bags[unit.path].add_node(
                    ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value,
                    f"{unit.module_name} unresolved import {target_name}",
                    unavailable=("import",),
                )
                bags[unit.path].add_edge(
                    ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value,
                    binding,
                    dynamic,
                    status=ResolutionStatus.UNRESOLVED.value,
                    unavailable=("import",),
                )
    for component in _sccs(import_pairs):
        if len(component) < 2 and not any(
            source == target for source, target in import_pairs if source in component
        ):
            continue
        members = sorted(component)
        for source_name in members:
            for target_name in members:
                if source_name == target_name and (source_name, target_name) not in import_pairs:
                    continue
                if (source_name, target_name) in import_pairs or source_name != target_name:
                    if source_name in module_nodes and target_name in module_nodes:
                        source_path = next(
                            (unit.path for unit in units if unit.module_name == source_name),
                            None,
                        )
                        if source_path is None:
                            continue
                        bags[source_path].add_edge(
                            ProgramGraphEdgeKind.CYCLIC_IMPORT.value,
                            module_nodes[source_name],
                            module_nodes[target_name],
                            cycle=True,
                        )

    def resolve_callee(unit: ProgramGraphUnitFacts, fn: ProgramGraphFunctionFact, callee: str) -> str | None:
        if not callee or callee.startswith("<"):
            return None
        local = aliases[unit.module_name].get(callee)
        candidates = [
            callee,
            local or "",
            f"{unit.module_name}.{callee}",
            f"{fn.class_qualified_name}.{callee.split('.')[-1]}" if fn.class_qualified_name else "",
            f"{fn.qualified_name.rsplit('.', 1)[0]}.{callee}" if "." not in callee else "",
        ]
        if callee.startswith("self.") and fn.class_qualified_name:
            candidates.append(f"{fn.class_qualified_name}.{callee.split('.', 1)[1]}")
        for item in candidates:
            if item and item in function_nodes:
                return item
            if item and item in class_nodes:
                return item
        if "." in callee:
            root, _, rest = callee.partition(".")
            aliased = aliases[unit.module_name].get(root)
            if aliased:
                joined = f"{aliased}.{rest}"
                if joined in function_nodes or joined in class_nodes:
                    return joined
                if aliased in module_nodes:
                    candidate = f"{aliased}.{rest}"
                    if candidate in function_nodes:
                        return candidate
        return None

    call_pairs: list[tuple[str, str]] = []
    callsite_nodes: list[tuple[ProgramGraphNode, str | None, ProgramGraphUnitFacts, ProgramGraphFunctionFact]] = []
    fixture_nodes = {
        fn.qualified_name: function_nodes[fn.qualified_name]
        for unit in units
        for fn in unit.functions
        if fn.is_fixture and fn.qualified_name in function_nodes
    }
    fixture_by_name: dict[str, list[str]] = defaultdict(list)
    for qualified in fixture_nodes:
        fixture_by_name[qualified.rsplit(".", 1)[-1]].append(qualified)

    for unit in units:
        bag = bags[unit.path]
        module_node = module_nodes[unit.module_name]
        for fn in unit.functions:
            fn_node = function_nodes[fn.qualified_name]
            # CFG
            cfg_map: dict[str, ProgramGraphNode] = {}
            for block in fn.cfg_blocks:
                cfg_map[block] = bag.add_node(
                    ProgramGraphNodeKind.CFG_BLOCK.value,
                    block,
                    metadata={"function": fn.qualified_name},
                )
                bag.add_edge(ProgramGraphEdgeKind.CONTAINS.value, fn_node, cfg_map[block])
            for edge in fn.cfg_edges:
                bag.add_edge(
                    edge.kind,
                    cfg_map[edge.source_block],
                    cfg_map[edge.target_block],
                    cycle=edge.logical_cycle,
                )
            # Data-flow: defs to later uses of the same name (acyclic).
            defs_by_name: dict[str, list[ProgramGraphNameFact]] = defaultdict(list)
            uses_by_name: dict[str, list[ProgramGraphNameFact]] = defaultdict(list)
            df_nodes: dict[tuple[str, int, bool], ProgramGraphNode] = {}
            for fact in fn.names:
                (defs_by_name if fact.is_def else uses_by_name)[fact.name].append(fact)
                df_nodes[(fact.name, fact.ordinal, fact.is_def)] = bag.add_node(
                    ProgramGraphNodeKind.DATA_FLOW.value,
                    f"{fn.qualified_name}.df.{fact.name}.{fact.ordinal}.{'def' if fact.is_def else 'use'}",
                    metadata={"name": fact.name, "ordinal": fact.ordinal},
                )
                bag.add_edge(ProgramGraphEdgeKind.CONTAINS.value, fn_node, df_nodes[(fact.name, fact.ordinal, fact.is_def)])
            for name, uses in uses_by_name.items():
                prior_defs = defs_by_name.get(name, ())
                for use in uses:
                    for definition in prior_defs:
                        if definition.ordinal < use.ordinal:
                            bag.add_edge(
                                ProgramGraphEdgeKind.DATA_FLOW.value,
                                df_nodes[(name, definition.ordinal, True)],
                                df_nodes[(name, use.ordinal, False)],
                            )
            if fn.incomplete and "data_flow" in fn.incomplete:
                incomplete.add("data_flow")
            # Types
            for index, (target, annotation) in enumerate(fn.annotations):
                type_node = bag.add_node(
                    ProgramGraphNodeKind.TYPE_BINDING.value,
                    f"{fn.qualified_name}.type.{target}.{index}",
                    metadata={"annotation": annotation[:128]},
                    unavailable=("type",) if annotation in {"", "dynamic", "Any"} else (),
                )
                bag.add_edge(ProgramGraphEdgeKind.TYPE_OF.value, fn_node, type_node)
                if annotation in {"", "dynamic", "Any"}:
                    incomplete.add("type")
            # Effects
            for effect in fn.effects:
                effect_node = bag.add_node(
                    ProgramGraphNodeKind.EFFECT.value,
                    f"{fn.qualified_name}.effect.{effect}",
                    unavailable=("effect",) if effect in {"native", "io"} else (),
                )
                bag.add_edge(ProgramGraphEdgeKind.EFFECT_OF.value, fn_node, effect_node)
            for write in fn.writes:
                write_node = bag.add_node(
                    ProgramGraphNodeKind.EFFECT.value,
                    f"{fn.qualified_name}.write.{write}",
                )
                bag.add_edge(ProgramGraphEdgeKind.WRITES_STATE.value, fn_node, write_node)
            # Exceptions
            for index, raised in enumerate(fn.raises):
                raise_node = bag.add_node(
                    ProgramGraphNodeKind.EXCEPTION_HANDLER.value,
                    f"{fn.qualified_name}.raise.{index}.{raised}",
                    metadata={"exception": raised},
                )
                bag.add_edge(ProgramGraphEdgeKind.RAISES.value, fn_node, raise_node)
            for handler in fn.handlers:
                handler_node = bag.add_node(
                    ProgramGraphNodeKind.EXCEPTION_HANDLER.value,
                    f"{fn.qualified_name}.except.{handler.ordinal}.{handler.exception_type}",
                    metadata={"exception": handler.exception_type},
                )
                bag.add_edge(ProgramGraphEdgeKind.CATCHES.value, fn_node, handler_node)
            # Contracts and proof obligations
            contract_kinds: list[tuple[str, str]] = []
            for statement in fn.asserts:
                contract_kinds.append((ContractKind.PRECONDITION.value, statement))
            contract_kinds.extend(_doc_contracts(fn.docstring))
            obligation_nodes: list[ProgramGraphNode] = []
            for index, (kind, statement) in enumerate(contract_kinds):
                spec_cid = cid_for_structured(
                    {
                        "schema": PROGRAM_GRAPH_DECLARATION_SCHEMA + "#contract",
                        "function": fn.qualified_name,
                        "kind": kind,
                        "statement": statement,
                        "ordinal": index,
                        "source_cid": unit.source_cid,
                    }
                )
                record = ContractStateRecord(
                    language=language,
                    subject_logical_name=fn.qualified_name,
                    contract_kind=kind,
                    specification_cid=spec_cid,
                    discharge_status=ContractDischargeStatus.UNKNOWN.value,
                    unavailable_dimensions=("proof",),
                )
                bag.contracts[record.contract_state_record_cid] = record
                contract_node = bag.add_node(
                    ProgramGraphNodeKind.CONTRACT_STATE.value,
                    f"{fn.qualified_name}.contract.{index}.{kind}",
                    record_cid=record.contract_state_record_cid,
                    unavailable=("proof",),
                )
                bag.add_edge(ProgramGraphEdgeKind.BINDS_CONTRACT.value, fn_node, contract_node)
                obligation = bag.add_node(
                    ProgramGraphNodeKind.PROOF_OBLIGATION.value,
                    f"{fn.qualified_name}.obligation.{index}",
                    unavailable=("proof",),
                )
                bag.add_edge(ProgramGraphEdgeKind.PROVED_BY.value, fn_node, obligation)
                obligation_nodes.append(obligation)
            if fn.is_proof:
                obligation = bag.add_node(
                    ProgramGraphNodeKind.PROOF_OBLIGATION.value,
                    f"{fn.qualified_name}.proof",
                    unavailable=("proof",),
                )
                bag.add_edge(ProgramGraphEdgeKind.PROVED_BY.value, fn_node, obligation)
                obligation_nodes.append(obligation)
            if not obligation_nodes:
                incomplete.add("proof")
                incomplete.add("contract")
            else:
                incomplete.add("proof")
            # Fixtures
            if fn.is_test:
                for param in fn.fixture_params:
                    matches = fixture_by_name.get(param, ())
                    if not matches:
                        incomplete.add("test")
                        continue
                    for fixture_name in matches:
                        bag.add_edge(
                            ProgramGraphEdgeKind.USES_FIXTURE.value,
                            fn_node,
                            fixture_nodes[fixture_name],
                        )
            # Calls
            for call in fn.calls:
                resolved = None if call.dynamic_reason else resolve_callee(unit, fn, call.callee_name)
                status = ResolutionStatus.DEFINITE.value
                unavailable: tuple[str, ...] = ()
                callee_decl = None
                if call.dynamic_reason:
                    status = ResolutionStatus.UNRESOLVED.value
                    unavailable = (call.dynamic_reason,)
                    incomplete.add("call")
                elif resolved is None:
                    status = ResolutionStatus.UNAVAILABLE.value
                    unavailable = ("external_runtime",)
                    incomplete.add("call")
                else:
                    callee_decl = function_decls.get(resolved) or class_decls.get(resolved)
                    if callee_decl is None:
                        status = ResolutionStatus.UNRESOLVED.value
                        unavailable = ("unknown_callee",)
                record = CallsiteRecord(
                    language=language,
                    caller_logical_name=fn.qualified_name,
                    callee_logical_name=call.callee_name or "<dynamic-call>",
                    source_cid=unit.source_cid,
                    ordinal=call.ordinal,
                    resolution_status=status,
                    callee_declaration_cid=callee_decl if status == ResolutionStatus.DEFINITE.value else None,
                    unavailable_dimensions=unavailable,
                )
                bag.callsites[record.callsite_record_cid] = record
                site = bag.add_node(
                    ProgramGraphNodeKind.CALLSITE.value,
                    f"{fn.qualified_name}#{call.ordinal}",
                    record_cid=record.callsite_record_cid,
                    unavailable=unavailable,
                    metadata={"lineno": call.lineno},
                )
                bag.add_edge(ProgramGraphEdgeKind.CALLS.value, fn_node, site, status=status, unavailable=unavailable)
                if status != ResolutionStatus.DEFINITE.value:
                    dynamic = bag.add_node(
                        ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value,
                        f"{fn.qualified_name}#{call.ordinal}.dynamic",
                        unavailable=unavailable or ("unknown_callee",),
                    )
                    bag.add_edge(
                        ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value,
                        site,
                        dynamic,
                        status=status if status != ResolutionStatus.DEFINITE.value else ResolutionStatus.UNRESOLVED.value,
                        unavailable=unavailable or ("unknown_callee",),
                    )
                callsite_nodes.append((site, resolved, unit, fn))
                if resolved is not None:
                    call_pairs.append((fn.qualified_name, resolved))
                    if fn.is_test and resolved in function_nodes:
                        target_fn = None
                        for item_unit in units:
                            for item in item_unit.functions:
                                if item.qualified_name == resolved:
                                    target_fn = item
                                    break
                            if target_fn is not None:
                                break
                        if (
                            target_fn is not None
                            and not target_fn.is_test
                            and not target_fn.is_fixture
                        ):
                            bag.add_edge(
                                ProgramGraphEdgeKind.TESTED_BY.value,
                                function_nodes[resolved],
                                fn_node,
                            )

    cyclic_callers = set()
    for component in _sccs(call_pairs):
        cyclic = len(component) > 1 or any(
            source == target and source in component for source, target in call_pairs
        )
        if not cyclic:
            continue
        cyclic_callers.update(component)
        members = sorted(component)
        for source_name in members:
            for target_name in members:
                if source_name in function_nodes and target_name in function_nodes:
                    if source_name == target_name and (source_name, target_name) not in call_pairs:
                        continue
                    source_unit = next(
                        (
                            unit
                            for unit in units
                            if any(fn.qualified_name == source_name for fn in unit.functions)
                        ),
                        None,
                    )
                    if source_unit is None:
                        continue
                    bags[source_unit.path].add_edge(
                        ProgramGraphEdgeKind.MUTUAL_RECURSION.value,
                        function_nodes[source_name],
                        function_nodes[target_name],
                        cycle=True,
                    )

    for site, resolved, unit, fn in callsite_nodes:
        if resolved is None:
            continue
        target = function_nodes.get(resolved) or class_nodes.get(resolved)
        if target is None:
            continue
        cycle = fn.qualified_name in cyclic_callers and resolved in cyclic_callers
        bags[unit.path].add_edge(
            ProgramGraphEdgeKind.SUCCESSOR.value,
            site,
            target,
            cycle=cycle,
        )

    # Merge bags.
    for bag in bags.values():
        all_nodes.update(bag.nodes)
        all_edges.update(bag.edges)
        all_callsites.update(bag.callsites)
        all_functions.update(bag.functions)
        all_contracts.update(bag.contracts)

    all_edges = _seal_logical_cycle_edges(all_edges)
    nodes = tuple(sorted(all_nodes.values(), key=lambda item: (str(item.node_kind), item.logical_name, item.program_graph_node_cid)))
    edges = tuple(sorted(all_edges.values(), key=lambda item: item.program_graph_edge_cid))
    callsites = tuple(sorted(all_callsites.values(), key=lambda item: item.callsite_record_cid))
    function_symbols = tuple(sorted(all_functions.values(), key=lambda item: item.function_symbol_record_cid))
    contract_states = tuple(sorted(all_contracts.values(), key=lambda item: item.contract_state_record_cid))

    # Successor sets and frontier.
    outgoing: dict[str, list[ProgramGraphEdge]] = defaultdict(list)
    for edge in edges:
        outgoing[edge.source_node_cid].append(edge)
    successor_sets: list[StaticSuccessorSet] = []
    unresolved_nodes = [node for node in nodes if is_unresolved_dynamic_node(node)]
    unresolved_edges = [edge for edge in edges if is_unresolved_dynamic_edge(edge)]
    for node in nodes:
        if str(node.node_kind) not in {
            ProgramGraphNodeKind.FUNCTION.value,
            ProgramGraphNodeKind.TEST.value,
            ProgramGraphNodeKind.FIXTURE.value,
            ProgramGraphNodeKind.MODULE.value,
        }:
            continue
        succ_edges = outgoing.get(node.program_graph_node_cid, ())
        succ_node_cids = _sorted_unique(edge.target_node_cid for edge in succ_edges)
        succ_edge_cids = _sorted_unique(edge.program_graph_edge_cid for edge in succ_edges)
        incomplete_here = any(is_unresolved_dynamic_edge(edge) for edge in succ_edges) or bool(node.unavailable_dimensions)
        dimensions = _sorted_unique(
            [
                *node.unavailable_dimensions,
                *(dim for edge in succ_edges for dim in edge.unavailable_dimensions),
            ]
        )
        if incomplete_here and not dimensions:
            dimensions = ("incomplete_analysis",)
        successor_sets.append(
            StaticSuccessorSet(
                language=language,
                subject_node_cid=node.program_graph_node_cid,
                successor_node_cids=succ_node_cids,
                successor_edge_cids=succ_edge_cids,
                complete=not incomplete_here,
                unavailable_dimensions=dimensions if incomplete_here else (),
            )
        )
    successor_sets_t = tuple(sorted(successor_sets, key=lambda item: item.static_successor_set_cid))

    frontiers: tuple[DynamicFrontierRecord, ...] = ()
    if unresolved_nodes or unresolved_edges or any(item.complete is False for item in successor_sets_t):
        reasons = []
        for node in unresolved_nodes:
            reasons.extend(node.unavailable_dimensions)
        for edge in unresolved_edges:
            reasons.extend(edge.unavailable_dimensions)
        allowed = {item.value for item in DynamicFrontierReason}
        frontier_reasons = tuple(sorted({item for item in reasons if item in allowed}))
        if not frontier_reasons:
            frontier_reasons = (DynamicFrontierReason.INCOMPLETE_ANALYSIS.value,)
        unavailable = _sorted_unique([*reasons, *incomplete, DynamicFrontierReason.INCOMPLETE_ANALYSIS.value])
        frontiers = (
            DynamicFrontierRecord(
                language=language,
                unresolved_node_cids=tuple(item.program_graph_node_cid for item in unresolved_nodes),
                unresolved_edge_cids=tuple(item.program_graph_edge_cid for item in unresolved_edges),
                reasons=frontier_reasons,
                unavailable_dimensions=unavailable,
            ),
        )

    proof_graphs: list[ProofObligationGraph] = []
    obligation_nodes = [node for node in nodes if str(node.node_kind) == ProgramGraphNodeKind.PROOF_OBLIGATION.value]
    obligation_edges = [
        edge
        for edge in edges
        if str(edge.edge_kind) == ProgramGraphEdgeKind.PROVED_BY.value
    ]
    if obligation_nodes:
        root = sorted(obligation_nodes, key=lambda item: item.logical_name)[0]
        proof_graphs.append(
            ProofObligationGraph(
                language=language,
                root_obligation_cid=root.program_graph_node_cid,
                obligation_node_cids=tuple(item.program_graph_node_cid for item in obligation_nodes),
                obligation_edge_cids=tuple(item.program_graph_edge_cid for item in obligation_edges),
                environment_binding_cid=env_cid,
                unavailable_dimensions=("proof",),
            )
        )
    proof_graphs_t = tuple(proof_graphs)

    snapshot_unavailable = _sorted_unique(incomplete)
    snapshot = assemble_program_graph_snapshot(
        language=language,
        nodes=nodes,
        edges=edges,
        environment_binding_set_cid=environment_set_cid,
        sealed_binding_cid=sealed_cid,
        callsites=callsites,
        function_symbols=function_symbols,
        contract_states=contract_states,
        proof_obligation_graphs=proof_graphs_t,
        successor_sets=successor_sets_t,
        frontiers=frontiers,
        retained_subroot_cids=(),
        unavailable_dimensions=snapshot_unavailable,
    )
    manifests = tuple(
        bind_index_manifest(
            ProgramGraphIndexManifest(
                snapshot_cid=snapshot.program_graph_snapshot_cid,
                index_kind=kind,
                schema_ids=(PROGRAM_GRAPH_SNAPSHOT_SCHEMA,),
            ),
            snapshot,
        )
        for kind in (
            ProgramGraphIndexKind.ADJACENCY,
            ProgramGraphIndexKind.SUCCESSOR,
            ProgramGraphIndexKind.FRONTIER,
            ProgramGraphIndexKind.STRUCTURAL,
        )
    )
    coverage = ProgramGraphCoverageReceipt(
        constructed_dimensions=CONSTRUCTED_DIMENSIONS,
        incomplete_dimensions=snapshot_unavailable,
        unit_count=len(units),
        node_count=len(nodes),
        edge_count=len(edges),
        frontier_count=len(frontiers),
        logical_cycle_edge_count=sum(1 for edge in edges if edge.logical_cycle),
        parse_error_paths=_sorted_unique(parse_errors),
        dynamic_reasons=_sorted_unique(
            reason
            for frontier in frontiers
            for reason in frontier.reasons
        ),
    )
    source_cids = tuple(sorted((unit.path, unit.source_cid) for unit in units))
    return ProgramGraphBuildReceipt(
        snapshot=snapshot,
        nodes=nodes,
        edges=edges,
        callsites=callsites,
        function_symbols=function_symbols,
        contract_states=contract_states,
        proof_obligation_graphs=proof_graphs_t,
        successor_sets=successor_sets_t,
        frontiers=frontiers,
        index_manifests=manifests,
        coverage=coverage,
        source_cids=source_cids,
        environment_binding_cid=env_cid,
        sealed_binding_cid=sealed_cid,
        incremental=incremental,
        unit_facts=tuple(sorted(units, key=lambda item: item.path)),
    )


# ---------------------------------------------------------------------------
# Public builder / planner
# ---------------------------------------------------------------------------


def _normalize_sources(sources: Mapping[str, str | bytes]) -> dict[str, bytes]:
    if not isinstance(sources, Mapping):
        raise ProgramGraphBuilderError("sources must be a mapping of repository-relative paths")
    normalized: dict[str, bytes] = {}
    for path, source in sources.items():
        key = _normalize_path(str(path))
        if key in normalized:
            raise ProgramGraphBuilderError(f"duplicate source path {key}")
        normalized[key] = _source_bytes(source, key)
    return dict(sorted(normalized.items()))


class ProgramGraphBuilder:
    """Deterministic admitted-Python static graph builder."""

    INTERFACE: ClassVar[str] = PROGRAM_GRAPH_BUILDER_INTERFACE
    VERSION: ClassVar[str] = PROGRAM_GRAPH_BUILDER_VERSION

    def __init__(
        self,
        *,
        language: str = ADMITTED_LANGUAGE,
        environment_binding: Mapping[str, str] | None = None,
    ) -> None:
        if language != ADMITTED_LANGUAGE:
            raise ProgramGraphBuilderError(
                f"language {language!r} is typed unavailable in this builder profile"
            )
        self.language = language
        self.environment_binding = dict(environment_binding or {})
        self.environment_binding_cid = _environment_cid(self.environment_binding)

    def build(
        self,
        sources: Mapping[str, str | bytes],
        *,
        previous: ProgramGraphBuildReceipt | None = None,
        incremental: bool = False,
    ) -> ProgramGraphBuildReceipt:
        units_map = _normalize_sources(sources)
        source_cids = tuple((path, cid_for_bytes(payload)) for path, payload in units_map.items())
        environment_set_cid = _source_manifest_cid(source_cids, self.environment_binding_cid)
        sealed_cid = _sealed_binding_cid(environment_set_cid, self.environment_binding_cid)
        previous_facts = {
            item.path: item
            for item in (previous.unit_facts if previous is not None and incremental else ())
        }
        previous_sources = previous.source_cid_map() if previous is not None else {}
        facts: list[ProgramGraphUnitFacts] = []
        for path, payload in units_map.items():
            cid = cid_for_bytes(payload)
            reused = previous_facts.get(path)
            if (
                incremental
                and reused is not None
                and previous_sources.get(path) == cid
                and reused.source_cid == cid
            ):
                facts.append(reused)
            else:
                facts.append(extract_unit_facts(path, payload))
        facts.sort(key=lambda item: item.path)
        return _link_units(
            facts,
            language=self.language,
            env_cid=self.environment_binding_cid,
            environment_set_cid=environment_set_cid,
            sealed_cid=sealed_cid,
            incremental=bool(incremental and previous is not None),
        )


def build_program_graph(
    sources: Mapping[str, str | bytes],
    *,
    environment_binding: Mapping[str, str] | None = None,
    previous: ProgramGraphBuildReceipt | None = None,
    incremental: bool = False,
    language: str = ADMITTED_LANGUAGE,
) -> ProgramGraphBuildReceipt:
    """Construct a sealed current-tree program graph from in-memory sources."""

    return ProgramGraphBuilder(
        language=language,
        environment_binding=environment_binding,
    ).build(sources, previous=previous, incremental=incremental)


def compute_program_graph_delta(
    previous: ProgramGraphSnapshot | ProgramGraphBuildReceipt,
    current: ProgramGraphSnapshot | ProgramGraphBuildReceipt,
) -> ProgramGraphDelta:
    """Return the exact node/edge delta, retaining every unchanged subroot CID."""

    previous_snapshot = previous.snapshot if isinstance(previous, ProgramGraphBuildReceipt) else previous
    current_snapshot = current.snapshot if isinstance(current, ProgramGraphBuildReceipt) else current
    if not isinstance(previous_snapshot, ProgramGraphSnapshot) or not isinstance(
        current_snapshot, ProgramGraphSnapshot
    ):
        raise ProgramGraphBuilderError("delta comparison requires program-graph snapshots")
    return delta_between_snapshots(previous_snapshot, current_snapshot)


class ProgramGraphInvalidationPlanner:
    """Precise, conservative invalidation over a previous sealed graph."""

    INTERFACE: ClassVar[str] = PROGRAM_GRAPH_INVALIDATION_PLANNER_INTERFACE

    def plan(
        self,
        previous: ProgramGraphBuildReceipt,
        current: ProgramGraphBuildReceipt,
        *,
        delta: ProgramGraphDelta | None = None,
    ) -> ProgramGraphInvalidationPlan:
        if not isinstance(previous, ProgramGraphBuildReceipt) or not isinstance(
            current, ProgramGraphBuildReceipt
        ):
            raise ProgramGraphBuilderError("invalidation requires sealed build receipts")
        if delta is None:
            delta = compute_program_graph_delta(previous, current)
        environment_changed = previous.environment_binding_cid != current.environment_binding_cid
        previous_nodes = {node.program_graph_node_cid: node for node in previous.nodes}
        current_ids = set(current.snapshot.node_cids)
        stale = set(delta.removed_node_cids)
        if environment_changed:
            stale.update(previous_nodes)
        depends_on: dict[str, set[str]] = defaultdict(set)
        forward: dict[str, set[str]] = defaultdict(set)
        for edge in previous.edges:
            kind = str(edge.edge_kind)
            if kind in _DEPENDENCY_EDGE_KINDS:
                # Source depends on target (caller depends on callee/successor).
                depends_on[edge.source_node_cid].add(edge.target_node_cid)
            if kind in _FORWARD_INVALIDATION_KINDS:
                forward[edge.source_node_cid].add(edge.target_node_cid)
        reverse: dict[str, set[str]] = defaultdict(set)
        for source, targets in depends_on.items():
            for target in targets:
                reverse[target].add(source)

        overapprox: set[str] = set()
        if stale:
            for node in previous.nodes:
                if is_unresolved_dynamic_node(node):
                    overapprox.add(node.program_graph_node_cid)
            for edge in previous.edges:
                if str(edge.resolution_status) not in {
                    ResolutionStatus.UNRESOLVED.value,
                    ResolutionStatus.UNAVAILABLE.value,
                }:
                    continue
                overapprox.add(edge.source_node_cid)
                overapprox.add(edge.target_node_cid)

        dependents: set[str] = set()
        reasons: list[ProgramGraphInvalidationReason] = []
        queue = deque(sorted(set(stale) | overapprox))
        seen: set[str] = set()
        while queue:
            node_cid = queue.popleft()
            if node_cid in seen:
                continue
            seen.add(node_cid)
            for dependent in sorted(reverse.get(node_cid, ())):
                if dependent not in dependents and dependent not in stale:
                    dependents.add(dependent)
                    reasons.append(
                        ProgramGraphInvalidationReason(
                            dependent,
                            ProgramGraphInvalidationCause.DEPENDENT_OF_CHANGED.value,
                            node_cid,
                        )
                    )
                if dependent not in seen:
                    queue.append(dependent)
            for child in sorted(forward.get(node_cid, ())):
                if child not in dependents and child not in stale:
                    node = previous_nodes.get(child)
                    cause = ProgramGraphInvalidationCause.DEPENDENT_OF_CHANGED.value
                    if node is not None and str(node.node_kind) == ProgramGraphNodeKind.TEST.value:
                        cause = ProgramGraphInvalidationCause.TEST_OF_CHANGED.value
                    elif node is not None and str(node.node_kind) == ProgramGraphNodeKind.PROOF_OBLIGATION.value:
                        cause = ProgramGraphInvalidationCause.PROOF_OF_CHANGED.value
                    dependents.add(child)
                    reasons.append(ProgramGraphInvalidationReason(child, cause, node_cid))
                if child not in seen:
                    queue.append(child)

        origin = next(iter(sorted(stale)), "")
        for node_cid in sorted(overapprox - stale):
            dependents.add(node_cid)
            reasons.append(
                ProgramGraphInvalidationReason(
                    node_cid,
                    ProgramGraphInvalidationCause.UNRESOLVED_DYNAMIC_OVERAPPROX.value,
                    origin or node_cid,
                )
            )

        for node_cid in sorted(stale):
            cause = (
                ProgramGraphInvalidationCause.ENVIRONMENT_CHANGED.value
                if environment_changed
                else ProgramGraphInvalidationCause.DELETED.value
                if node_cid not in current_ids
                else ProgramGraphInvalidationCause.SOURCE_CHANGED.value
            )
            reasons.append(ProgramGraphInvalidationReason(node_cid, cause, node_cid))

        invalidated = set(stale) | set(dependents)
        retained = tuple(sorted(cid for cid in previous.snapshot.node_cids if cid not in invalidated))
        reasons_t = tuple(
            sorted(reasons, key=lambda item: (item.node_cid, item.cause, item.origin_cid))
        )
        # Soundness check: every reverse-dependent of an invalidated node is included.
        omitted = False
        for node_cid in list(invalidated):
            for dependent in reverse.get(node_cid, ()):
                if dependent not in invalidated:
                    omitted = True
            for child in forward.get(node_cid, ()):
                if child not in invalidated:
                    omitted = True
        if omitted:
            raise ProgramGraphBuilderError("invalidation omitted a dependent; refusing unsound plan")
        return ProgramGraphInvalidationPlan(
            previous_snapshot_cid=previous.snapshot.program_graph_snapshot_cid,
            current_snapshot_cid=current.snapshot.program_graph_snapshot_cid,
            delta=delta,
            invalidated_node_cids=tuple(sorted(invalidated)),
            stale_node_cids=tuple(sorted(stale)),
            dependent_node_cids=tuple(sorted(dependents)),
            retained_subroot_cids=retained,
            reasons=reasons_t,
            omitted_dependents=False,
            conservative=True,
            environment_changed=environment_changed,
        )


def plan_program_graph_invalidation(
    previous: ProgramGraphBuildReceipt,
    current: ProgramGraphBuildReceipt,
    *,
    delta: ProgramGraphDelta | None = None,
) -> ProgramGraphInvalidationPlan:
    """Plan dependency-aware invalidation without unsound omission."""

    return ProgramGraphInvalidationPlanner().plan(previous, current, delta=delta)


__all__ = [
    "ADMITTED_LANGUAGE",
    "CONSTRUCTED_DIMENSIONS",
    "IMPORT_SCAN_PERFORMED",
    "PROGRAM_GRAPH_BUILDER_INTERFACE",
    "PROGRAM_GRAPH_BUILDER_VERSION",
    "PROGRAM_GRAPH_BUILD_RECEIPT_INTERFACE",
    "PROGRAM_GRAPH_INVALIDATION_PLANNER_INTERFACE",
    "ProgramGraphBuildReceipt",
    "ProgramGraphBuilder",
    "ProgramGraphBuilderError",
    "ProgramGraphCoverageReceipt",
    "ProgramGraphInvalidationCause",
    "ProgramGraphInvalidationPlan",
    "ProgramGraphInvalidationPlanner",
    "ProgramGraphInvalidationReason",
    "ProgramGraphUnitFacts",
    "build_program_graph",
    "compute_program_graph_delta",
    "extract_unit_facts",
    "plan_program_graph_invalidation",
]
