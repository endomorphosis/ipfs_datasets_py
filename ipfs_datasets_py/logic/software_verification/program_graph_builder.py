"""Deterministic static program-graph construction and invalidation (SAWM-006).

This module constructs current-tree ``ProgramGraphSnapshot@1`` values from an
explicit Python path-to-source mapping.  It never walks the filesystem, never
imports analyzed modules, and does no work at import time.  Unsupported and
dynamic dimensions stay explicit on nodes, successor sets, and the dynamic
frontier.  Incremental rebuilds reuse unchanged per-file analyses and must
match a full rebuild of the same inputs.

Authority rules (normative):

* Datasets software-verification owns construction of the static logical graph.
  This module does not introduce accelerator planning graphs or mutate
  operational state.
* Callers supply exact source bytes and environment bindings.  There is no
  repository scanner, watch loop, or implicit discovery pass.
* Physical IPLD remains acyclic.  Logical cycles (CFG back-edges, mutual
  recursion, cyclic imports) are immutable ``logical_cycle`` records.
* Unknown dynamic behavior widens the frontier; it is never encoded as absence.
* Invalidation follows dependency edges and must not omit a dependent of a
  changed subroot.
"""

from __future__ import annotations

import ast
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.python_frontend import PythonASTExtractor
from ipfs_datasets_py.logic.software_contracts.semantic_index.pytest_analysis import (
    PytestAnalyzer,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    EnvironmentBinding,
    EnvironmentBindingSet,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_graph import (
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
)


# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

PROGRAM_GRAPH_BUILDER_INTERFACE: Final[str] = "ProgramGraphBuilder@1"
PROGRAM_GRAPH_BUILDER_VERSION: Final[str] = "1"
PROGRAM_GRAPH_BUILD_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-graph-build@1"
)
PROGRAM_GRAPH_BUILD_RECEIPT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-graph-build-receipt@1"
)
PROGRAM_GRAPH_COVERAGE_RECEIPT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-graph-coverage-receipt@1"
)
PROGRAM_GRAPH_SEALED_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-graph-sealed-binding@1"
)
PROGRAM_GRAPH_INVALIDATION_PLAN_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-graph-invalidation-plan@1"
)
PROGRAM_GRAPH_INVALIDATION_OBLIGATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-graph-invalidation-obligation@1"
)
PYTHON_STATIC_PROFILE: Final[str] = "python-static-v1"

PROJECTION_NAMES: Final[tuple[str, ...]] = (
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

ALWAYS_INCOMPLETE_DIMENSIONS: Final[tuple[str, ...]] = (
    "type_inference",
    "proof_discharge",
)

PYTHON_SOURCE_SUFFIXES: Final[tuple[str, ...]] = (".py", ".pyi")

_BUILTIN_CALLEES: Final[frozenset[str]] = frozenset(
    {
        "abs",
        "all",
        "any",
        "bool",
        "dict",
        "enumerate",
        "float",
        "int",
        "len",
        "list",
        "max",
        "min",
        "print",
        "range",
        "repr",
        "set",
        "sorted",
        "str",
        "sum",
        "tuple",
        "zip",
    }
)
_DYNAMIC_CALLS: Final[frozenset[str]] = frozenset(
    {
        "__import__",
        "compile",
        "eval",
        "exec",
        "importlib.import_module",
        "runpy.run_module",
        "runpy.run_path",
        "builtins.__import__",
        "builtins.eval",
        "builtins.exec",
        "builtins.compile",
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
_EFFECT_CALLS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "open": "filesystem",
        "builtins.open": "filesystem",
        "os.remove": "filesystem",
        "os.system": "subprocess",
        "subprocess.run": "subprocess",
        "subprocess.Popen": "subprocess",
        "socket.socket": "network",
        "requests.get": "network",
        "requests.post": "network",
    }
)
_CONTRACT_DECORATORS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "require": ContractKind.PRECONDITION.value,
        "requires": ContractKind.PRECONDITION.value,
        "pre": ContractKind.PRECONDITION.value,
        "precondition": ContractKind.PRECONDITION.value,
        "ensure": ContractKind.POSTCONDITION.value,
        "ensures": ContractKind.POSTCONDITION.value,
        "post": ContractKind.POSTCONDITION.value,
        "postcondition": ContractKind.POSTCONDITION.value,
        "invariant": ContractKind.INVARIANT.value,
        "inv": ContractKind.INVARIANT.value,
        "frame": ContractKind.FRAME.value,
    }
)
_DEPENDENCY_EDGE_KINDS: Final[frozenset[str]] = frozenset(
    {
        ProgramGraphEdgeKind.IMPORTS.value,
        ProgramGraphEdgeKind.CYCLIC_IMPORT.value,
        ProgramGraphEdgeKind.CALLS.value,
        ProgramGraphEdgeKind.MUTUAL_RECURSION.value,
        ProgramGraphEdgeKind.SUCCESSOR.value,
        ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value,
        ProgramGraphEdgeKind.TESTED_BY.value,
        ProgramGraphEdgeKind.PROVED_BY.value,
        ProgramGraphEdgeKind.BINDS_CONTRACT.value,
        ProgramGraphEdgeKind.USES_FIXTURE.value,
        ProgramGraphEdgeKind.INHERITS.value,
        ProgramGraphEdgeKind.IMPLEMENTS.value,
        ProgramGraphEdgeKind.RAISES.value,
        ProgramGraphEdgeKind.CATCHES.value,
    }
)


class ProgramGraphBuilderError(ProgramGraphError):
    """Raised when static graph construction inputs fail closed."""


class ProjectionStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    EMPTY = "empty"


class InvalidationReason(str, Enum):
    SOURCE_CHANGED = "source_changed"
    SOURCE_REMOVED = "source_removed"
    SOURCE_ADDED = "source_added"
    ENVIRONMENT_CHANGED = "environment_changed"
    DEPENDENT_OF_CHANGED = "dependent_of_changed"
    IMPORT_TARGET_CHANGED = "import_target_changed"
    CALLEE_CHANGED = "callee_changed"
    TESTED_SUBJECT_CHANGED = "tested_subject_changed"
    PROOF_SUBJECT_CHANGED = "proof_subject_changed"
    UNRESOLVED_FRONTIER = "unresolved_frontier"
    DELETED_DEPENDENCY = "deleted_dependency"


class InvalidationRemediation(str, Enum):
    REBUILD_SUBGRAPH = "rebuild_subgraph"
    RERESOLVE = "reresolve"
    RERUN_TEST = "rerun_test"
    RERUN_PROOF = "rerun_proof"
    FULL_REBUILD = "full_rebuild"


# ---------------------------------------------------------------------------
# Path / name / CID helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProgramGraphBuilderError(f"{name} must be nonempty trimmed text")
    return value


def _normalize_path(path: str) -> str:
    value = str(PurePosixPath(_text(path, "path").replace("\\", "/")))
    if value in {".", ".."} or value.startswith("../") or value.startswith("/"):
        raise ProgramGraphBuilderError("path must be repository-relative")
    return value


def _source_bytes(source: str | bytes) -> bytes:
    if type(source) is bytes:
        return source
    if type(source) is str:
        return source.encode("utf-8")
    raise ProgramGraphBuilderError("source must be text or UTF-8 bytes")


def _module_name(path: str) -> str:
    parts = list(PurePosixPath(path).parts)
    if parts and parts[-1].endswith(PYTHON_SOURCE_SUFFIXES):
        parts[-1] = parts[-1].rsplit(".", 1)[0]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or "__main__"


def _package_name(module_name: str) -> str:
    if "." not in module_name:
        return module_name
    return module_name.rsplit(".", 1)[0]


def _is_python_path(path: str) -> bool:
    return path.endswith(PYTHON_SOURCE_SUFFIXES)


def _expression_name(node: ast.AST | None) -> str:
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
        return type(node.value).__name__.lower() + "_literal"
    return type(node).__name__


def _simple_name(name: str) -> str:
    return name.rsplit(".", 1)[-1] if name else ""


def _render(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return " ".join(ast.unparse(node).split())
    except (AttributeError, TypeError, ValueError):
        return type(node).__name__


def _decorator_name(node: ast.AST) -> str:
    target = node.func if isinstance(node, ast.Call) else node
    return _expression_name(target)


def _declaration_cid(
    *,
    path: str,
    logical_name: str,
    kind: str,
    source_cid: str,
) -> str:
    return cid_for_structured(
        {
            "kind": kind,
            "logical_name": logical_name,
            "path": path,
            "source_cid": source_cid,
        }
    )


def _meta(path: str, **fields: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"path": path}
    for key, value in fields.items():
        if value is None:
            continue
        payload[key] = value
    return payload


def _thaw_meta(value: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            result[str(key)] = _thaw_meta(item)
        elif isinstance(item, tuple):
            result[str(key)] = list(item)
        else:
            result[str(key)] = item
    return result


def _qualify(*parts: str) -> str:
    return ".".join(part for part in parts if part)


def _expand_relative(module_name: str, imported: str | None, level: int) -> str:
    if level <= 0:
        return imported or ""
    parts = module_name.split(".") if module_name != "__main__" else []
    if level > len(parts):
        return imported or ""
    parent = parts[:-level]
    if imported:
        return ".".join((*parent, *imported.split("."))) if parent else imported
    return ".".join(parent)


def _default_binding_set(
    bindings: Sequence[EnvironmentBinding] | None,
) -> EnvironmentBindingSet:
    if bindings is None:
        return EnvironmentBindingSet(bindings=())
    if not isinstance(bindings, Sequence) or isinstance(bindings, (str, bytes)):
        raise ProgramGraphBuilderError("environment_bindings must be a sequence")
    return EnvironmentBindingSet(bindings=tuple(bindings))


def _seal_binding_cid(environment_binding_set_cid: str) -> str:
    return cid_for_structured(
        {
            "schema": PROGRAM_GRAPH_SEALED_BINDING_SCHEMA,
            "builder": PROGRAM_GRAPH_BUILDER_INTERFACE,
            "builder_version": PROGRAM_GRAPH_BUILDER_VERSION,
            "environment_binding_set_cid": environment_binding_set_cid,
            "language": ProgramLanguage.PYTHON.value,
            "profile": PYTHON_STATIC_PROFILE,
        }
    )


def _call_frontier_reason(name: str, node: ast.Call) -> str | None:
    simple = _simple_name(name)
    if name in {"eval"} or simple == "eval":
        return DynamicFrontierReason.EVAL.value
    if name in {"exec"} or simple == "exec":
        return DynamicFrontierReason.EXEC.value
    if name in _DYNAMIC_CALLS or simple == "__import__" or name.endswith(".__import__"):
        if simple == "compile":
            return DynamicFrontierReason.INCOMPLETE_ANALYSIS.value
        return DynamicFrontierReason.IMPORT_HOOK.value
    if (
        name in {"importlib.metadata.entry_points", "importlib_metadata.entry_points"}
        or (simple == "entry_points" and "importlib" in name)
    ):
        return DynamicFrontierReason.PLUGIN.value
    if name == "type" and len(node.args) >= 3:
        return DynamicFrontierReason.DYNAMIC_DISPATCH.value
    if name == "types.new_class" or (
        simple == "new_class" and (name == "new_class" or name.startswith("types."))
    ):
        return DynamicFrontierReason.DYNAMIC_DISPATCH.value
    if name in _REFLECTION_CALLS or name.endswith(".__setattr__") or name.endswith(
        ".__getattribute__"
    ):
        return DynamicFrontierReason.REFLECTION.value
    if (
        name in _NATIVE_CALLS
        or name.startswith("ctypes.")
        or simple in {"CDLL", "PyDLL", "WinDLL"}
    ):
        return DynamicFrontierReason.NATIVE_CALL.value
    if isinstance(node.func, ast.Call) or not name or name in {"Call", "subscript", "[]"}:
        return DynamicFrontierReason.UNKNOWN_CALLEE.value
    if isinstance(node.func, ast.Attribute) and not isinstance(
        node.func.value, (ast.Name, ast.Attribute)
    ):
        return DynamicFrontierReason.DYNAMIC_DISPATCH.value
    return None


def _effect_kind(name: str) -> str | None:
    if name in _EFFECT_CALLS:
        return _EFFECT_CALLS[name]
    simple = _simple_name(name)
    if name.startswith("os.") and simple in {"remove", "unlink", "mkdir", "open"}:
        return "filesystem"
    if name.startswith("subprocess."):
        return "subprocess"
    if name.startswith("socket.") or name.startswith("requests."):
        return "network"
    return None


# ---------------------------------------------------------------------------
# Record constructors
# ---------------------------------------------------------------------------


def _node(
    *,
    kind: ProgramGraphNodeKind | str,
    logical_name: str,
    source_cid: str,
    env_cid: str,
    path: str,
    declaration_cid: str | None = None,
    record_cid: str | None = None,
    unavailable: Sequence[str] = (),
    **metadata: Any,
) -> ProgramGraphNode:
    return ProgramGraphNode(
        node_kind=kind,
        language=ProgramLanguage.PYTHON,
        logical_name=logical_name,
        source_cid=source_cid,
        declaration_cid=declaration_cid,
        environment_binding_cid=env_cid,
        record_cid=record_cid,
        unavailable_dimensions=tuple(unavailable),
        metadata=_meta(path, **metadata),
    )


def _edge(
    *,
    kind: ProgramGraphEdgeKind | str,
    source: ProgramGraphNode,
    target: ProgramGraphNode,
    env_cid: str,
    status: ResolutionStatus | str = ResolutionStatus.DEFINITE,
    logical_cycle: bool = False,
    unavailable: Sequence[str] = (),
    **metadata: Any,
) -> ProgramGraphEdge:
    return ProgramGraphEdge(
        edge_kind=kind,
        source_node_cid=source.program_graph_node_cid,
        target_node_cid=target.program_graph_node_cid,
        language=ProgramLanguage.PYTHON,
        environment_binding_cid=env_cid,
        resolution_status=status,
        logical_cycle=logical_cycle,
        unavailable_dimensions=tuple(unavailable),
        metadata=_meta(str(source.metadata.get("path", "")), **metadata)
        if source.metadata.get("path")
        else (metadata or {}),
    )


def _with_logical_cycle(edge: ProgramGraphEdge) -> ProgramGraphEdge:
    if edge.logical_cycle:
        return edge
    return ProgramGraphEdge(
        edge_kind=edge.edge_kind,
        source_node_cid=edge.source_node_cid,
        target_node_cid=edge.target_node_cid,
        language=edge.language,
        environment_binding_cid=edge.environment_binding_cid,
        resolution_status=edge.resolution_status,
        logical_cycle=True,
        unavailable_dimensions=edge.unavailable_dimensions,
        metadata=_thaw_meta(edge.metadata),
    )


def _index_by_cid(records: Iterable[Any]) -> dict[str, Any]:
    indexed: dict[str, Any] = {}
    for item in records:
        cid = getattr(item, item.CID_FIELD)
        indexed[cid] = item
    return indexed


def _seal_unmarked_cycles(edges: Sequence[ProgramGraphEdge]) -> tuple[ProgramGraphEdge, ...]:
    current = list(edges)
    while True:
        cycles = directed_logical_cycles(current)
        by_cid = {item.program_graph_edge_cid: item for item in current}
        unmarked: set[str] = set()
        for cycle in cycles:
            if not any(by_cid[cid].logical_cycle for cid in cycle):
                unmarked.update(cycle)
        if not unmarked:
            return tuple(current)
        current = [
            _with_logical_cycle(item)
            if item.program_graph_edge_cid in unmarked
            else item
            for item in current
        ]


# ---------------------------------------------------------------------------
# Coverage / receipts / invalidation records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProgramGraphCoverageReceipt:
    """Closed coverage of the projections this builder actually constructed."""

    projections: Mapping[str, str]
    incomplete_dimensions: Sequence[str] = ()
    observed_frontier_reasons: Sequence[str] = ()
    file_count: int = 0
    node_count: int = 0
    edge_count: int = 0
    rebuilt_path_count: int = 0
    reused_path_count: int = 0

    SCHEMA: ClassVar[str] = PROGRAM_GRAPH_COVERAGE_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.projections, Mapping):
            raise ProgramGraphBuilderError("projections must be a mapping")
        missing = set(PROJECTION_NAMES) - set(self.projections)
        extra = set(self.projections) - set(PROJECTION_NAMES)
        if missing or extra:
            raise ProgramGraphBuilderError("coverage projections must be the closed set")
        normalized = {
            key: ProjectionStatus(self.projections[key]).value for key in PROJECTION_NAMES
        }
        object.__setattr__(self, "projections", MappingProxyType(normalized))
        object.__setattr__(
            self,
            "incomplete_dimensions",
            tuple(sorted(set(self.incomplete_dimensions))),
        )
        object.__setattr__(
            self,
            "observed_frontier_reasons",
            tuple(sorted(set(self.observed_frontier_reasons))),
        )
        for name in (
            "file_count",
            "node_count",
            "edge_count",
            "rebuilt_path_count",
            "reused_path_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or isinstance(value, bool) or value < 0:
                raise ProgramGraphBuilderError(f"{name} must be a nonnegative integer")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "projections": dict(self.projections),
            "incomplete_dimensions": list(self.incomplete_dimensions),
            "observed_frontier_reasons": list(self.observed_frontier_reasons),
            "file_count": self.file_count,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "rebuilt_path_count": self.rebuilt_path_count,
            "reused_path_count": self.reused_path_count,
        }

    @property
    def coverage_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["coverage_cid"] = self.coverage_cid
        return value


@dataclass(frozen=True, slots=True)
class ProgramGraphInvalidationObligation:
    """One dependency-aware invalidation obligation; never an unsound skip."""

    subject_cid: str
    subject_kind: str
    reason: str
    remediation: str
    confidence: str = "exact"
    supporting_edge_cids: Sequence[str] = ()
    logical_name: str = ""

    SCHEMA: ClassVar[str] = PROGRAM_GRAPH_INVALIDATION_OBLIGATION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_cid", _text(self.subject_cid, "subject_cid"))
        object.__setattr__(self, "subject_kind", _text(self.subject_kind, "subject_kind"))
        object.__setattr__(self, "reason", InvalidationReason(self.reason).value)
        object.__setattr__(
            self, "remediation", InvalidationRemediation(self.remediation).value
        )
        if self.confidence not in {"exact", "conservative"}:
            raise ProgramGraphBuilderError("confidence must be exact or conservative")
        object.__setattr__(
            self,
            "supporting_edge_cids",
            tuple(sorted(set(self.supporting_edge_cids))),
        )
        name = self.logical_name
        if name != "":
            object.__setattr__(self, "logical_name", _text(name, "logical_name"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "subject_cid": self.subject_cid,
            "subject_kind": self.subject_kind,
            "reason": self.reason,
            "remediation": self.remediation,
            "confidence": self.confidence,
            "supporting_edge_cids": list(self.supporting_edge_cids),
            "logical_name": self.logical_name,
        }

    @property
    def obligation_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["obligation_cid"] = self.obligation_cid
        return value


@dataclass(frozen=True, slots=True)
class ProgramGraphInvalidationPlan:
    """Precise invalidation over a snapshot delta; retained subroots stay valid."""

    previous_snapshot_cid: str
    current_snapshot_cid: str
    delta_cid: str
    invalidated_node_cids: Sequence[str]
    invalidated_edge_cids: Sequence[str]
    retained_subroot_cids: Sequence[str]
    obligations: Sequence[ProgramGraphInvalidationObligation] = ()
    full_rebuild: bool = False

    SCHEMA: ClassVar[str] = PROGRAM_GRAPH_INVALIDATION_PLAN_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "previous_snapshot_cid", _text(self.previous_snapshot_cid, "previous")
        )
        object.__setattr__(
            self, "current_snapshot_cid", _text(self.current_snapshot_cid, "current")
        )
        object.__setattr__(self, "delta_cid", _text(self.delta_cid, "delta_cid"))
        object.__setattr__(
            self,
            "invalidated_node_cids",
            tuple(sorted(set(self.invalidated_node_cids))),
        )
        object.__setattr__(
            self,
            "invalidated_edge_cids",
            tuple(sorted(set(self.invalidated_edge_cids))),
        )
        object.__setattr__(
            self,
            "retained_subroot_cids",
            tuple(sorted(set(self.retained_subroot_cids))),
        )
        if any(
            not isinstance(item, ProgramGraphInvalidationObligation)
            for item in self.obligations
        ):
            raise ProgramGraphBuilderError("obligations must be typed records")
        ordered = tuple(
            sorted(self.obligations, key=lambda item: item.obligation_cid)
        )
        object.__setattr__(self, "obligations", ordered)
        if type(self.full_rebuild) is not bool:
            raise ProgramGraphBuilderError("full_rebuild must be a boolean")
        overlap = set(self.invalidated_node_cids) & set(self.retained_subroot_cids)
        if overlap:
            raise ProgramGraphBuilderError(
                "invalidation cannot both retain and invalidate the same subroot"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "previous_snapshot_cid": self.previous_snapshot_cid,
            "current_snapshot_cid": self.current_snapshot_cid,
            "delta_cid": self.delta_cid,
            "invalidated_node_cids": list(self.invalidated_node_cids),
            "invalidated_edge_cids": list(self.invalidated_edge_cids),
            "retained_subroot_cids": list(self.retained_subroot_cids),
            "obligations": [item.to_dict() for item in self.obligations],
            "full_rebuild": self.full_rebuild,
        }

    @property
    def plan_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["plan_cid"] = self.plan_cid
        return value


@dataclass(frozen=True, slots=True)
class _PendingImport:
    module_logical_name: str
    imported_module: str
    imported_name: str
    local_name: str
    binding: ProgramGraphNode
    dynamic: bool


@dataclass(frozen=True, slots=True)
class _PendingCall:
    caller_logical_name: str
    callee_name: str
    expanded_name: str
    callsite: ProgramGraphNode
    record: CallsiteRecord
    function: ProgramGraphNode
    ordinal: int
    frontier_reason: str | None
    local_target: str | None


@dataclass(frozen=True, slots=True)
class _PendingInherit:
    class_logical_name: str
    base_name: str
    class_node: ProgramGraphNode
    implements: bool


@dataclass(frozen=True, slots=True)
class _FileAnalysis:
    path: str
    source_cid: str
    module_name: str
    package_name: str
    nodes: tuple[ProgramGraphNode, ...]
    edges: tuple[ProgramGraphEdge, ...]
    callsites: tuple[CallsiteRecord, ...]
    function_symbols: tuple[FunctionSymbolRecord, ...]
    contract_states: tuple[ContractStateRecord, ...]
    pending_imports: tuple[_PendingImport, ...]
    pending_calls: tuple[_PendingCall, ...]
    pending_inherits: tuple[_PendingInherit, ...]
    aliases: Mapping[str, str]
    function_qns: tuple[str, ...]
    module_node: ProgramGraphNode
    source_node: ProgramGraphNode
    incomplete_dimensions: tuple[str, ...]
    parse_ok: bool
    test_qns: tuple[str, ...]
    fixture_qns: tuple[str, ...]
    tested_pairs: tuple[tuple[str, str], ...]
    fixture_pairs: tuple[tuple[str, str], ...]
    diagnostics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProgramGraphBuildReceipt:
    """Sealed construction result: snapshot, catalog, coverage, and reuse cache."""

    snapshot: ProgramGraphSnapshot
    nodes: tuple[ProgramGraphNode, ...]
    edges: tuple[ProgramGraphEdge, ...]
    callsites: tuple[CallsiteRecord, ...] = ()
    function_symbols: tuple[FunctionSymbolRecord, ...] = ()
    contract_states: tuple[ContractStateRecord, ...] = ()
    proof_obligation_graphs: tuple[ProofObligationGraph, ...] = ()
    successor_sets: tuple[StaticSuccessorSet, ...] = ()
    frontiers: tuple[DynamicFrontierRecord, ...] = ()
    index_manifests: tuple[ProgramGraphIndexManifest, ...] = ()
    coverage: ProgramGraphCoverageReceipt | None = None
    source_cids: Mapping[str, str] = field(default_factory=dict)
    nodes_by_path: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    rebuilt_paths: tuple[str, ...] = ()
    reused_paths: tuple[str, ...] = ()
    mode: str = "full"
    environment_binding_set_cid: str = ""
    sealed_binding_cid: str = ""
    file_analyses: tuple[_FileAnalysis, ...] = ()
    diagnostics: tuple[str, ...] = ()

    SCHEMA: ClassVar[str] = PROGRAM_GRAPH_BUILD_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, ProgramGraphSnapshot):
            raise ProgramGraphBuilderError("snapshot must be a ProgramGraphSnapshot")
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "edges", tuple(self.edges))
        object.__setattr__(
            self,
            "source_cids",
            MappingProxyType({key: self.source_cids[key] for key in sorted(self.source_cids)}),
        )
        object.__setattr__(
            self,
            "nodes_by_path",
            MappingProxyType(
                {
                    key: tuple(self.nodes_by_path[key])
                    for key in sorted(self.nodes_by_path)
                }
            ),
        )
        object.__setattr__(self, "rebuilt_paths", tuple(sorted(set(self.rebuilt_paths))))
        object.__setattr__(self, "reused_paths", tuple(sorted(set(self.reused_paths))))
        if self.mode not in {"full", "incremental"}:
            raise ProgramGraphBuilderError("mode must be full or incremental")
        if self.coverage is None:
            raise ProgramGraphBuilderError("coverage receipt is required")
        object.__setattr__(self, "diagnostics", tuple(sorted(set(self.diagnostics))))

    def identity_payload(self) -> dict[str, Any]:
        assert self.coverage is not None
        return {
            "schema": self.SCHEMA,
            "builder": PROGRAM_GRAPH_BUILDER_INTERFACE,
            "builder_version": PROGRAM_GRAPH_BUILDER_VERSION,
            "snapshot_cid": self.snapshot.program_graph_snapshot_cid,
            "coverage_cid": self.coverage.coverage_cid,
            "source_cids": dict(self.source_cids),
            "rebuilt_paths": list(self.rebuilt_paths),
            "reused_paths": list(self.reused_paths),
            "mode": self.mode,
            "environment_binding_set_cid": self.environment_binding_set_cid,
            "sealed_binding_cid": self.sealed_binding_cid,
            "diagnostics": list(self.diagnostics),
        }

    @property
    def receipt_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["receipt_cid"] = self.receipt_cid
        value["snapshot"] = self.snapshot.to_dict()
        value["coverage"] = self.coverage.to_dict() if self.coverage is not None else {}
        return value

    def node_by_cid(self) -> dict[str, ProgramGraphNode]:
        return {item.program_graph_node_cid: item for item in self.nodes}

    def nodes_of_kind(self, kind: str) -> tuple[ProgramGraphNode, ...]:
        return tuple(item for item in self.nodes if item.node_kind == kind)

    def edges_of_kind(self, kind: str) -> tuple[ProgramGraphEdge, ...]:
        return tuple(item for item in self.edges if item.edge_kind == kind)


# ---------------------------------------------------------------------------
# Per-file analysis
# ---------------------------------------------------------------------------


@dataclass
class _FileBuilder:
    path: str
    source_cid: str
    env_cid: str
    module_name: str
    package_name: str
    source_node: ProgramGraphNode
    module_node: ProgramGraphNode
    nodes: list[ProgramGraphNode] = field(default_factory=list)
    edges: list[ProgramGraphEdge] = field(default_factory=list)
    callsites: list[CallsiteRecord] = field(default_factory=list)
    function_symbols: list[FunctionSymbolRecord] = field(default_factory=list)
    contract_states: list[ContractStateRecord] = field(default_factory=list)
    pending_imports: list[_PendingImport] = field(default_factory=list)
    pending_calls: list[_PendingCall] = field(default_factory=list)
    pending_inherits: list[_PendingInherit] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)
    function_nodes: dict[str, ProgramGraphNode] = field(default_factory=dict)
    class_nodes: dict[str, ProgramGraphNode] = field(default_factory=dict)
    incomplete: set[str] = field(default_factory=set)
    diagnostics: list[str] = field(default_factory=list)
    test_qns: list[str] = field(default_factory=list)
    fixture_qns: list[str] = field(default_factory=list)
    tested_pairs: list[tuple[str, str]] = field(default_factory=list)
    fixture_pairs: list[tuple[str, str]] = field(default_factory=list)

    def add_node(self, node: ProgramGraphNode) -> ProgramGraphNode:
        self.nodes.append(node)
        return node

    def add_edge(self, edge: ProgramGraphEdge) -> ProgramGraphEdge:
        self.edges.append(edge)
        return edge

    def link(
        self,
        kind: ProgramGraphEdgeKind | str,
        source: ProgramGraphNode,
        target: ProgramGraphNode,
        **kwargs: Any,
    ) -> ProgramGraphEdge:
        return self.add_edge(
            _edge(kind=kind, source=source, target=target, env_cid=self.env_cid, **kwargs)
        )

    def make_node(
        self,
        kind: ProgramGraphNodeKind | str,
        logical_name: str,
        *,
        declaration_cid: str | None = None,
        record_cid: str | None = None,
        unavailable: Sequence[str] = (),
        **metadata: Any,
    ) -> ProgramGraphNode:
        if declaration_cid is None:
            declaration_cid = _declaration_cid(
                path=self.path,
                logical_name=logical_name,
                kind=str(kind.value if isinstance(kind, ProgramGraphNodeKind) else kind),
                source_cid=self.source_cid,
            )
        return self.add_node(
            _node(
                kind=kind,
                logical_name=logical_name,
                source_cid=self.source_cid,
                env_cid=self.env_cid,
                path=self.path,
                declaration_cid=declaration_cid,
                record_cid=record_cid,
                unavailable=unavailable,
                **metadata,
            )
        )


def _emit_cfg(
    builder: _FileBuilder,
    function: ProgramGraphNode,
    func_qn: str,
    body: Sequence[ast.stmt],
) -> tuple[ProgramGraphNode, tuple[ProgramGraphNode, ...]]:
    ordinal = 0
    blocks: list[ProgramGraphNode] = []
    loop_stack: list[tuple[ProgramGraphNode, list[ProgramGraphNode]]] = []
    exit_block: ProgramGraphNode | None = None

    def block(kind: str) -> ProgramGraphNode:
        nonlocal ordinal
        node = builder.make_node(
            ProgramGraphNodeKind.CFG_BLOCK,
            f"{func_qn}#cfg:{ordinal}",
            projection="cfg",
            block_kind=kind,
            ordinal=ordinal,
        )
        ordinal += 1
        blocks.append(node)
        builder.link(ProgramGraphEdgeKind.CONTAINS, function, node)
        return node

    def link(
        source: ProgramGraphNode,
        target: ProgramGraphNode,
        kind: ProgramGraphEdgeKind = ProgramGraphEdgeKind.CFG_NEXT,
        *,
        cycle: bool = False,
        branch: str | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {"logical_cycle": cycle}
        if branch is not None:
            kwargs["branch"] = branch
            kind = ProgramGraphEdgeKind.CFG_BRANCH
        builder.link(kind, source, target, **kwargs)

    entry = block("entry")
    exit_block = block("exit")

    def seq(stmts: Sequence[ast.stmt], start: ProgramGraphNode) -> list[ProgramGraphNode]:
        current = start
        live = True
        for stmt in stmts:
            if not live:
                break
            current, live = emit(stmt, current)
        return [current] if live else []

    def emit(stmt: ast.stmt, pred: ProgramGraphNode) -> tuple[ProgramGraphNode, bool]:
        if isinstance(stmt, ast.If):
            header = block("if")
            link(pred, header)
            then_entry = block("if_then")
            link(header, then_entry, branch="true")
            then_exits = seq(stmt.body, then_entry)
            if stmt.orelse:
                else_entry = block("if_else")
                link(header, else_entry, branch="false")
                else_exits = seq(stmt.orelse, else_entry)
            else:
                fallthrough = block("if_fallthrough")
                link(header, fallthrough, branch="false")
                else_exits = [fallthrough]
            join = block("if_join")
            reachable = False
            for item in (*then_exits, *else_exits):
                link(item, join)
                reachable = True
            return (join, reachable)
        if isinstance(stmt, (ast.While, ast.For, ast.AsyncFor)):
            header = block("loop_header")
            link(pred, header)
            body_entry = block("loop_body")
            after = block("loop_after")
            link(header, body_entry, branch="true")
            link(header, after, branch="false")
            breaks: list[ProgramGraphNode] = []
            loop_stack.append((header, breaks))
            body_exits = seq(stmt.body, body_entry)
            loop_stack.pop()
            for item in body_exits:
                link(item, header, cycle=True)
            for item in breaks:
                link(item, after)
            else_exits = seq(stmt.orelse, after) if stmt.orelse else [after]
            join = else_exits[0] if len(else_exits) == 1 else after
            if len(else_exits) > 1:
                join = block("loop_join")
                for item in else_exits:
                    link(item, join)
            elif not else_exits:
                return (after, False)
            return (join, True)
        if isinstance(stmt, (ast.Try, getattr(ast, "TryStar", ast.Try))):
            body_entry = block("try_body")
            link(pred, body_entry)
            body_exits = seq(stmt.body, body_entry)
            handlers: list[ProgramGraphNode] = []
            for index, handler in enumerate(stmt.handlers):
                handler_block = block("except")
                handler_node = builder.make_node(
                    ProgramGraphNodeKind.EXCEPTION_HANDLER,
                    f"{func_qn}#exc:{index}",
                    projection="exception",
                    ordinal=index,
                    exception_type=_render(handler.type) or "bare",
                )
                builder.link(ProgramGraphEdgeKind.CONTAINS, function, handler_node)
                builder.link(ProgramGraphEdgeKind.EXCEPTION_EDGE, body_entry, handler_block)
                builder.link(ProgramGraphEdgeKind.CATCHES, handler_node, handler_block)
                caught = _expression_name(handler.type) if handler.type is not None else "BaseException"
                builder.link(
                    ProgramGraphEdgeKind.CATCHES,
                    function,
                    handler_node,
                    exception_type=caught,
                )
                handler_exits = seq(handler.body, handler_block)
                handlers.extend(handler_exits)
            else_exits = seq(stmt.orelse, body_exits[0]) if stmt.orelse and body_exits else body_exits
            join = block("try_join")
            for item in (*else_exits, *handlers):
                link(item, join)
            if stmt.finalbody:
                final_entry = block("finally")
                link(join, final_entry)
                final_exits = seq(stmt.finalbody, final_entry)
                return (final_exits[0], bool(final_exits)) if final_exits else (join, False)
            return (join, True)
        if isinstance(stmt, ast.Match):
            header = block("match")
            link(pred, header)
            join = block("match_join")
            any_live = False
            for case_index, case in enumerate(stmt.cases):
                case_entry = block("match_case")
                link(header, case_entry, branch=f"case_{case_index}")
                exits = seq(case.body, case_entry)
                for item in exits:
                    link(item, join)
                    any_live = True
            return (join, any_live)
        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            header = block("with")
            link(pred, header)
            exits = seq(stmt.body, header)
            return (exits[0], bool(exits)) if exits else (header, False)
        if isinstance(stmt, ast.Return):
            terminal = block("return")
            link(pred, terminal)
            link(terminal, exit_block)
            return (terminal, False)
        if isinstance(stmt, ast.Raise):
            terminal = block("raise")
            link(pred, terminal)
            link(terminal, exit_block)
            exc_name = _expression_name(stmt.exc) or "unknown"
            raise_node = builder.make_node(
                ProgramGraphNodeKind.EFFECT,
                f"{func_qn}#raises:{exc_name}",
                projection="exception",
                effect_kind="raises",
                exception_type=exc_name,
                unavailable=("exceptional_control",),
            )
            builder.link(ProgramGraphEdgeKind.RAISES, function, raise_node)
            builder.link(ProgramGraphEdgeKind.EXCEPTION_EDGE, terminal, exit_block)
            builder.incomplete.add("exception")
            return (terminal, False)
        if isinstance(stmt, ast.Break):
            terminal = block("break")
            link(pred, terminal)
            if loop_stack:
                loop_stack[-1][1].append(terminal)
            return (terminal, False)
        if isinstance(stmt, ast.Continue):
            terminal = block("continue")
            link(pred, terminal)
            if loop_stack:
                link(terminal, loop_stack[-1][0], cycle=True)
            return (terminal, False)
        current = block("stmt")
        link(pred, current)
        return (current, True)

    fallthrough = seq(body, entry)
    for item in fallthrough:
        link(item, exit_block)
    builder.link(ProgramGraphEdgeKind.SUCCESSOR, function, entry)
    return entry, tuple(blocks)


def _emit_data_flow(
    builder: _FileBuilder,
    function: ProgramGraphNode,
    func_qn: str,
    tree: ast.AST,
) -> None:
    stores: dict[str, int] = {}
    loads: dict[str, int] = {}
    opaque = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Store):
                stores[node.id] = stores.get(node.id, 0) + 1
            elif isinstance(node.ctx, ast.Load):
                loads[node.id] = loads.get(node.id, 0) + 1
        elif isinstance(node, ast.Starred):
            opaque = True
        elif isinstance(node, ast.Call):
            name = _expression_name(node.func)
            if name in {"globals", "locals", "vars", "setattr"}:
                opaque = True
    names = tuple(sorted(set(stores) | set(loads)))
    for name in names:
        df_node = builder.make_node(
            ProgramGraphNodeKind.DATA_FLOW,
            f"{func_qn}#df:{name}",
            projection="data_flow",
            symbol=name,
            unavailable=("path_sensitivity",) if opaque else (),
        )
        builder.link(ProgramGraphEdgeKind.DATA_FLOW, function, df_node)
        if name in stores:
            builder.link(ProgramGraphEdgeKind.WRITES_STATE, function, df_node)
        if name in loads:
            builder.link(ProgramGraphEdgeKind.READS_STATE, function, df_node)
    if opaque:
        builder.incomplete.add("data_flow")


def _emit_type_binding(
    builder: _FileBuilder,
    owner: ProgramGraphNode,
    logical_name: str,
    annotation: ast.AST | None,
) -> None:
    rendered = _render(annotation)
    unavailable = ["type_inference"]
    type_node = builder.make_node(
        ProgramGraphNodeKind.TYPE_BINDING,
        f"{logical_name}:type",
        projection="type",
        annotation=rendered,
        unavailable=unavailable,
    )
    builder.link(ProgramGraphEdgeKind.TYPE_OF, owner, type_node)
    builder.incomplete.add("type")


def _emit_contracts_and_proofs(
    builder: _FileBuilder,
    function: ProgramGraphNode,
    func_qn: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> None:
    for decorator in node.decorator_list:
        simple = _simple_name(_decorator_name(decorator))
        kind = _CONTRACT_DECORATORS.get(simple)
        if kind is None:
            continue
        spec = cid_for_bytes(f"{func_qn}:{kind}:{_render(decorator)}".encode("utf-8"))
        record = ContractStateRecord(
            language=ProgramLanguage.PYTHON,
            subject_logical_name=func_qn,
            contract_kind=kind,
            specification_cid=spec,
            discharge_status=ContractDischargeStatus.UNKNOWN,
            unavailable_dimensions=("proof_discharge",),
        )
        builder.contract_states.append(record)
        contract_node = builder.make_node(
            ProgramGraphNodeKind.CONTRACT_STATE,
            f"{func_qn}.{kind}",
            record_cid=record.contract_state_record_cid,
            projection="contract",
            contract_kind=kind,
            unavailable=("proof_discharge",),
        )
        builder.link(ProgramGraphEdgeKind.BINDS_CONTRACT, function, contract_node)
        builder.incomplete.add("contract")
        builder.incomplete.add("proof")

    asserts = [
        item
        for item in ast.walk(node)
        if isinstance(item, ast.Assert)
    ]
    obligation_nodes: list[ProgramGraphNode] = []
    for index, item in enumerate(asserts):
        obligation = builder.make_node(
            ProgramGraphNodeKind.PROOF_OBLIGATION,
            f"{func_qn}.assert:{index}",
            projection="proof",
            ordinal=index,
            unavailable=("proof_discharge",),
        )
        builder.link(ProgramGraphEdgeKind.PROVED_BY, function, obligation)
        spec = cid_for_bytes(f"{func_qn}:assert:{index}:{_render(item.test)}".encode("utf-8"))
        record = ContractStateRecord(
            language=ProgramLanguage.PYTHON,
            subject_logical_name=func_qn,
            contract_kind=ContractKind.PRECONDITION,
            specification_cid=spec,
            discharge_status=ContractDischargeStatus.UNKNOWN,
            unavailable_dimensions=("proof_discharge",),
        )
        builder.contract_states.append(record)
        contract_node = builder.make_node(
            ProgramGraphNodeKind.CONTRACT_STATE,
            f"{func_qn}.assert:{index}.pre",
            record_cid=record.contract_state_record_cid,
            projection="contract",
            contract_kind=ContractKind.PRECONDITION.value,
            unavailable=("proof_discharge",),
        )
        builder.link(ProgramGraphEdgeKind.BINDS_CONTRACT, function, contract_node)
        obligation_nodes.append(obligation)
        builder.incomplete.add("proof")
        builder.incomplete.add("contract")
    if obligation_nodes:
        builder.link(
            ProgramGraphEdgeKind.SUCCESSOR,
            function,
            obligation_nodes[0],
            projection="proof",
        )


def _emit_function(
    builder: _FileBuilder,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: ProgramGraphNode,
    prefix: str,
    *,
    is_test: bool,
    is_fixture: bool,
    fixture_params: Sequence[str],
) -> ProgramGraphNode:
    func_qn = _qualify(prefix, node.name) if prefix else _qualify(builder.module_name, node.name)
    params = tuple(
        item.arg
        for item in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
    )
    record = FunctionSymbolRecord(
        language=ProgramLanguage.PYTHON,
        logical_name=func_qn,
        source_cid=builder.source_cid,
        declaration_cid=_declaration_cid(
            path=builder.path,
            logical_name=func_qn,
            kind="function",
            source_cid=builder.source_cid,
        ),
        parameter_names=params,
        return_annotation=_render(node.returns),
        unavailable_dimensions=("type_inference",),
    )
    kind: ProgramGraphNodeKind | str
    if is_test:
        kind = ProgramGraphNodeKind.TEST
        record_cid = None
    elif is_fixture:
        kind = ProgramGraphNodeKind.FIXTURE
        record_cid = None
    else:
        kind = ProgramGraphNodeKind.FUNCTION
        record_cid = record.function_symbol_record_cid
        builder.function_symbols.append(record)
    unavailable = ["type_inference"]
    if any(isinstance(item, (ast.Yield, ast.YieldFrom, ast.Await)) for item in ast.walk(node)):
        unavailable.append("incomplete_analysis")
        builder.incomplete.add("call")
    if any(
        isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
        and item is not node
        for item in ast.walk(node)
    ):
        unavailable.append("incomplete_analysis")
        builder.incomplete.add("symbol")
    function = builder.make_node(
        kind,
        func_qn,
        declaration_cid=record.declaration_cid,
        record_cid=record_cid,
        projection="symbol",
        async_function=isinstance(node, ast.AsyncFunctionDef),
        unavailable=unavailable,
    )
    builder.function_nodes[func_qn] = function
    builder.function_nodes[node.name] = function
    builder.link(ProgramGraphEdgeKind.DECLARES, owner, function)
    builder.link(ProgramGraphEdgeKind.CONTAINS, owner, function)
    _emit_cfg(builder, function, func_qn, node.body)
    _emit_data_flow(builder, function, func_qn, node)
    _emit_type_binding(builder, function, func_qn, node.returns)
    _emit_contracts_and_proofs(builder, function, func_qn, node)
    if is_test:
        builder.test_qns.append(func_qn)
        for item in ast.walk(node):
            if isinstance(item, ast.Call):
                callee = _expression_name(item.func)
                if callee:
                    builder.tested_pairs.append((func_qn, callee))
        for name in fixture_params:
            builder.fixture_pairs.append((func_qn, name))
    if is_fixture:
        builder.fixture_qns.append(func_qn)
    return function


def _emit_class(
    builder: _FileBuilder,
    node: ast.ClassDef,
    owner: ProgramGraphNode,
    prefix: str,
    pytest_tests: Mapping[str, Any],
    pytest_fixtures: Mapping[str, Any],
) -> None:
    class_qn = _qualify(prefix, node.name) if prefix else _qualify(builder.module_name, node.name)
    class_node = builder.make_node(
        ProgramGraphNodeKind.CLASS,
        class_qn,
        projection="symbol",
    )
    builder.class_nodes[class_qn] = class_node
    builder.link(ProgramGraphEdgeKind.DECLARES, owner, class_node)
    builder.link(ProgramGraphEdgeKind.CONTAINS, owner, class_node)
    for base in node.bases:
        base_name = _expression_name(base)
        if not base_name:
            continue
        implements = _simple_name(base_name) in {"Protocol", "ABC", "Hashable", "Iterable"}
        builder.pending_inherits.append(
            _PendingInherit(class_qn, base_name, class_node, implements)
        )
    nested_prefix = class_qn
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            local = f"{node.name}.{item.name}"
            _emit_function(
                builder,
                item,
                class_node,
                nested_prefix,
                is_test=local in pytest_tests or item.name.startswith("test_"),
                is_fixture=local in pytest_fixtures,
                fixture_params=getattr(pytest_tests.get(local), "fixture_names", ()),
            )
        elif isinstance(item, ast.ClassDef):
            _emit_class(builder, item, class_node, nested_prefix, pytest_tests, pytest_fixtures)
        elif isinstance(item, (ast.Assign, ast.AnnAssign)):
            targets = item.targets if isinstance(item, ast.Assign) else [item.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    symbol = builder.make_node(
                        ProgramGraphNodeKind.SYMBOL,
                        _qualify(class_qn, target.id),
                        projection="symbol",
                    )
                    builder.link(ProgramGraphEdgeKind.DECLARES, class_node, symbol)


def _emit_imports(builder: _FileBuilder, tree: ast.Module) -> None:
    ordinal = 0
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                imported = alias.name
                builder.aliases[local] = imported
                binding = builder.make_node(
                    ProgramGraphNodeKind.IMPORT_BINDING,
                    f"{builder.module_name}!{local}",
                    projection="import",
                    local_name=local,
                    imported_module=imported,
                    ordinal=ordinal,
                )
                builder.link(ProgramGraphEdgeKind.IMPORTS, builder.module_node, binding)
                builder.pending_imports.append(
                    _PendingImport(
                        builder.module_name,
                        imported,
                        "",
                        local,
                        binding,
                        False,
                    )
                )
                ordinal += 1
        elif isinstance(node, ast.ImportFrom):
            module = _expand_relative(builder.module_name, node.module, node.level)
            for alias in node.names:
                local = alias.asname or alias.name
                dynamic = alias.name == "*"
                imported_name = "" if dynamic else alias.name
                if not dynamic:
                    builder.aliases[local] = (
                        f"{module}.{imported_name}" if module else imported_name
                    )
                binding = builder.make_node(
                    ProgramGraphNodeKind.IMPORT_BINDING,
                    f"{builder.module_name}!{local}",
                    projection="import",
                    local_name=local,
                    imported_module=module or builder.package_name,
                    imported_name=imported_name or "*",
                    ordinal=ordinal,
                    unavailable=("star_import",) if dynamic else (),
                )
                status = (
                    ResolutionStatus.UNRESOLVED if dynamic else ResolutionStatus.DEFINITE
                )
                unavailable = ("star_import",) if dynamic else ()
                builder.link(
                    ProgramGraphEdgeKind.IMPORTS,
                    builder.module_node,
                    binding,
                    status=status,
                    unavailable=unavailable,
                )
                builder.pending_imports.append(
                    _PendingImport(
                        builder.module_name,
                        module,
                        imported_name,
                        local,
                        binding,
                        dynamic,
                    )
                )
                if dynamic:
                    builder.incomplete.add("import")
                ordinal += 1


def _emit_calls(builder: _FileBuilder, func_qn: str, function: ProgramGraphNode, node: ast.AST) -> None:
    ordinal = 0
    for item in ast.walk(node):
        if not isinstance(item, ast.Call):
            continue
        raw = _expression_name(item.func) or "<dynamic-call>"
        root, _, rest = raw.partition(".")
        expanded = builder.aliases.get(root, root)
        expanded_name = f"{expanded}.{rest}" if rest else expanded
        reason = _call_frontier_reason(expanded_name, item) or _call_frontier_reason(raw, item)
        local_target = None
        if expanded_name in builder.function_nodes:
            local_target = expanded_name
        elif raw in builder.function_nodes:
            local_target = raw
        elif _qualify(builder.module_name, raw) in builder.function_nodes:
            local_target = _qualify(builder.module_name, raw)
        if reason is not None:
            status = ResolutionStatus.UNRESOLVED
            unavailable = (reason,)
            callee_decl = None
            builder.incomplete.add("call")
        elif local_target is not None:
            status = ResolutionStatus.DEFINITE
            unavailable = ()
            callee_decl = builder.function_nodes[local_target].declaration_cid
        elif _simple_name(expanded_name) in _BUILTIN_CALLEES and "." not in expanded_name:
            status = ResolutionStatus.FINITE_MAY
            unavailable = ()
            callee_decl = None
        else:
            # May still resolve against another current-tree module.  Keep the
            # callsite identity stable and mark the successor set incomplete.
            status = ResolutionStatus.FINITE_MAY
            unavailable = ()
            callee_decl = None
            builder.incomplete.add("call")
        record = CallsiteRecord(
            language=ProgramLanguage.PYTHON,
            caller_logical_name=func_qn,
            callee_logical_name=expanded_name or raw,
            source_cid=builder.source_cid,
            ordinal=ordinal,
            resolution_status=status,
            callee_declaration_cid=callee_decl,
            unavailable_dimensions=unavailable,
        )
        builder.callsites.append(record)
        callsite = builder.make_node(
            ProgramGraphNodeKind.CALLSITE,
            f"{func_qn}#{ordinal}",
            record_cid=record.callsite_record_cid,
            projection="call",
            callee=expanded_name or raw,
            ordinal=ordinal,
            unavailable=unavailable,
        )
        builder.link(ProgramGraphEdgeKind.CALLS, function, callsite, status=status, unavailable=unavailable)
        builder.link(ProgramGraphEdgeKind.CONTAINS, function, callsite)
        builder.link(ProgramGraphEdgeKind.SUCCESSOR, function, callsite, status=status, unavailable=unavailable)
        if reason is not None:
            dynamic = builder.make_node(
                ProgramGraphNodeKind.UNRESOLVED_DYNAMIC,
                f"{func_qn}#dynamic:{reason}:{ordinal}",
                projection="call",
                reason=reason,
                callee=expanded_name or raw,
                unavailable=(reason,),
            )
            builder.link(
                ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC,
                function,
                dynamic,
                status=ResolutionStatus.UNRESOLVED,
                unavailable=(reason,),
            )
            builder.link(
                ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC,
                callsite,
                dynamic,
                status=ResolutionStatus.UNRESOLVED,
                unavailable=(reason,),
            )
        effect = _effect_kind(expanded_name) or _effect_kind(raw)
        if effect is not None:
            effect_node = builder.make_node(
                ProgramGraphNodeKind.EFFECT,
                f"{func_qn}#effect:{effect}:{ordinal}",
                projection="effect",
                effect_kind=effect,
                callee=expanded_name or raw,
            )
            builder.link(ProgramGraphEdgeKind.EFFECT_OF, function, effect_node)
            builder.incomplete.add("effect")
        builder.pending_calls.append(
            _PendingCall(
                func_qn,
                raw,
                expanded_name or raw,
                callsite,
                record,
                function,
                ordinal,
                reason,
                local_target,
            )
        )
        ordinal += 1


def _analyze_python_file(
    *,
    path: str,
    source: str | bytes,
    env_cid: str,
    repository_id: str,
    pytest_by_path: Mapping[str, Any],
) -> _FileAnalysis:
    raw = _source_bytes(source)
    source_cid = cid_for_bytes(raw)
    module_name = _module_name(path)
    package_name = _package_name(module_name)
    source_node = _node(
        kind=ProgramGraphNodeKind.SOURCE,
        logical_name=path,
        source_cid=source_cid,
        env_cid=env_cid,
        path=path,
        declaration_cid=_declaration_cid(
            path=path, logical_name=path, kind="source", source_cid=source_cid
        ),
        projection="source",
    )
    module_node = _node(
        kind=ProgramGraphNodeKind.MODULE,
        logical_name=module_name,
        source_cid=source_cid,
        env_cid=env_cid,
        path=path,
        declaration_cid=_declaration_cid(
            path=path, logical_name=module_name, kind="module", source_cid=source_cid
        ),
        projection="symbol",
    )
    builder = _FileBuilder(
        path=path,
        source_cid=source_cid,
        env_cid=env_cid,
        module_name=module_name,
        package_name=package_name,
        source_node=source_node,
        module_node=module_node,
    )
    builder.add_node(source_node)
    builder.add_node(module_node)
    builder.link(ProgramGraphEdgeKind.CONTAINS, source_node, module_node)
    extractor = PythonASTExtractor()
    frontend = extractor.extract(raw, path=path, repository_id=repository_id)
    try:
        text = raw.decode("utf-8")
        tree = ast.parse(text, filename=path, type_comments=True)
        parse_ok = True
    except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
        builder.diagnostics.append(f"parse_error:{type(exc).__name__}")
        builder.incomplete.update({"ast", "symbol", "import", "call", "cfg"})
        ast_node = builder.make_node(
            ProgramGraphNodeKind.AST,
            f"{path}#ast",
            projection="ast",
            unavailable=("parse_error",),
        )
        builder.link(ProgramGraphEdgeKind.CONTAINS, source_node, ast_node)
        builder.link(ProgramGraphEdgeKind.CONTAINS, module_node, ast_node)
        parse_ok = False
        tree = None
    if parse_ok and tree is not None:
        dump = ast.dump(tree, include_attributes=False)
        ast_cid = cid_for_bytes(dump.encode("utf-8"))
        ast_node = builder.make_node(
            ProgramGraphNodeKind.AST,
            f"{path}#ast",
            projection="ast",
            ast_cid=ast_cid,
            frontend_cid=frontend.cid,
        )
        builder.link(ProgramGraphEdgeKind.CONTAINS, source_node, ast_node)
        builder.link(ProgramGraphEdgeKind.CONTAINS, module_node, ast_node)
        facts = pytest_by_path.get(path)
        tests = {}
        fixtures = {}
        if facts is not None:
            tests = {item.qualified_name: item for item in facts.tests}
            fixtures = {item.qualified_name: item for item in facts.fixtures}
        _emit_imports(builder, tree)
        for item in tree.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function = _emit_function(
                    builder,
                    item,
                    module_node,
                    builder.module_name,
                    is_test=item.name in tests or item.name.startswith("test_"),
                    is_fixture=item.name in fixtures,
                    fixture_params=getattr(tests.get(item.name), "fixture_names", ()),
                )
                _emit_calls(builder, function.logical_name, function, item)
            elif isinstance(item, ast.ClassDef):
                _emit_class(builder, item, module_node, builder.module_name, tests, fixtures)
                class_qn = _qualify(builder.module_name, item.name)
                class_node = builder.class_nodes[class_qn]
                for child in item.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        func_qn = _qualify(class_qn, child.name)
                        function = builder.function_nodes[func_qn]
                        _emit_calls(builder, func_qn, function, child)
            elif isinstance(item, (ast.Assign, ast.AnnAssign)):
                targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        symbol = builder.make_node(
                            ProgramGraphNodeKind.SYMBOL,
                            _qualify(builder.module_name, target.id),
                            projection="symbol",
                        )
                        builder.link(ProgramGraphEdgeKind.DECLARES, module_node, symbol)
                        if isinstance(item, ast.AnnAssign):
                            _emit_type_binding(
                                builder, symbol, symbol.logical_name, item.annotation
                            )
        if frontend.unsupported:
            builder.incomplete.add("ast")
            builder.diagnostics.extend(sorted({item.code for item in frontend.unsupported}))
        for effect in frontend.effects:
            effect_node = builder.make_node(
                ProgramGraphNodeKind.EFFECT,
                f"{module_name}#effect:{effect.kind}:{effect.effect_id}",
                projection="effect",
                effect_kind=effect.kind,
                operation=effect.operation,
            )
            builder.link(ProgramGraphEdgeKind.EFFECT_OF, module_node, effect_node)
            builder.incomplete.add("effect")
    return _FileAnalysis(
        path=path,
        source_cid=source_cid,
        module_name=module_name,
        package_name=package_name,
        nodes=tuple(_index_by_cid(builder.nodes).values()),
        edges=tuple(_index_by_cid(builder.edges).values()),
        callsites=tuple(_index_by_cid(builder.callsites).values()),
        function_symbols=tuple(_index_by_cid(builder.function_symbols).values()),
        contract_states=tuple(_index_by_cid(builder.contract_states).values()),
        pending_imports=tuple(builder.pending_imports),
        pending_calls=tuple(builder.pending_calls),
        pending_inherits=tuple(builder.pending_inherits),
        aliases=MappingProxyType(dict(builder.aliases)),
        function_qns=tuple(sorted(builder.function_nodes)),
        module_node=module_node,
        source_node=source_node,
        incomplete_dimensions=tuple(sorted(builder.incomplete)),
        parse_ok=parse_ok,
        test_qns=tuple(sorted(set(builder.test_qns))),
        fixture_qns=tuple(sorted(set(builder.fixture_qns))),
        tested_pairs=tuple(sorted(set(builder.tested_pairs))),
        fixture_pairs=tuple(sorted(set(builder.fixture_pairs))),
        diagnostics=tuple(sorted(set(builder.diagnostics))),
    )


# ---------------------------------------------------------------------------
# Global resolution / assembly
# ---------------------------------------------------------------------------


def _strongly_connected(nodes: Sequence[str], edges: Sequence[tuple[str, str]]) -> list[set[str]]:
    graph: dict[str, list[str]] = {node: [] for node in nodes}
    for source, target in edges:
        if source in graph and target in graph:
            graph[source].append(target)
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    components: list[set[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlink[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for nxt in graph[node]:
            if nxt not in indices:
                strongconnect(nxt)
                lowlink[node] = min(lowlink[node], lowlink[nxt])
            elif nxt in on_stack:
                lowlink[node] = min(lowlink[node], indices[nxt])
        if lowlink[node] == indices[node]:
            component: set[str] = set()
            while True:
                item = stack.pop()
                on_stack.remove(item)
                component.add(item)
                if item == node:
                    break
            components.append(component)

    for node in nodes:
        if node not in indices:
            strongconnect(node)
    return components


def _lookup_qn(
    name: str,
    *,
    qn_nodes: Mapping[str, ProgramGraphNode],
    aliases: Mapping[str, str],
    module_name: str,
) -> ProgramGraphNode | None:
    candidates = [
        name,
        aliases.get(name, name),
        _qualify(module_name, name),
    ]
    root, _, rest = name.partition(".")
    if root in aliases:
        candidates.append(f"{aliases[root]}.{rest}" if rest else aliases[root])
    for item in candidates:
        if item in qn_nodes:
            return qn_nodes[item]
    return None


def _assemble_analyses(
    analyses: Sequence[_FileAnalysis],
    *,
    env_cid: str,
    environment_binding_set_cid: str,
    sealed_binding_cid: str,
) -> dict[str, Any]:
    nodes: dict[str, ProgramGraphNode] = {}
    edges: dict[str, ProgramGraphEdge] = {}
    callsites: dict[str, CallsiteRecord] = {}
    function_symbols: dict[str, FunctionSymbolRecord] = {}
    contract_states: dict[str, ContractStateRecord] = {}
    qn_nodes: dict[str, ProgramGraphNode] = {}
    modules: dict[str, ProgramGraphNode] = {}
    packages: dict[str, ProgramGraphNode] = {}

    def add_node(node: ProgramGraphNode) -> ProgramGraphNode:
        nodes[node.program_graph_node_cid] = node
        return node

    def add_edge(edge: ProgramGraphEdge) -> ProgramGraphEdge:
        edges[edge.program_graph_edge_cid] = edge
        return edge

    def link(
        kind: ProgramGraphEdgeKind | str,
        source: ProgramGraphNode,
        target: ProgramGraphNode,
        **kwargs: Any,
    ) -> ProgramGraphEdge:
        return add_edge(
            _edge(kind=kind, source=source, target=target, env_cid=env_cid, **kwargs)
        )

    for analysis in analyses:
        for node in analysis.nodes:
            add_node(node)
            qn_nodes.setdefault(node.logical_name, node)
        for edge in analysis.edges:
            add_edge(edge)
        for item in analysis.callsites:
            callsites[item.callsite_record_cid] = item
        for item in analysis.function_symbols:
            function_symbols[item.function_symbol_record_cid] = item
        for item in analysis.contract_states:
            contract_states[item.contract_state_record_cid] = item
        modules[analysis.module_name] = analysis.module_node
        if analysis.package_name and analysis.package_name not in packages:
            package_source = cid_for_bytes(f"package:{analysis.package_name}".encode("utf-8"))
            package = _node(
                kind=ProgramGraphNodeKind.PACKAGE,
                logical_name=analysis.package_name,
                source_cid=package_source,
                env_cid=env_cid,
                path=analysis.path,
                declaration_cid=_declaration_cid(
                    path=analysis.package_name,
                    logical_name=analysis.package_name,
                    kind="package",
                    source_cid=package_source,
                ),
                projection="symbol",
            )
            packages[analysis.package_name] = add_node(package)
        package = packages.get(analysis.package_name)
        if package is not None:
            link(ProgramGraphEdgeKind.CONTAINS, package, analysis.module_node)
            link(ProgramGraphEdgeKind.CONTAINS, package, analysis.source_node)

    import_pairs: list[tuple[str, str]] = []
    for analysis in analyses:
        for pending in analysis.pending_imports:
            if pending.dynamic:
                continue
            target_module = pending.imported_module
            if pending.imported_name and target_module:
                target = qn_nodes.get(f"{target_module}.{pending.imported_name}")
                if target is None:
                    target = modules.get(target_module)
            else:
                target = modules.get(target_module)
            if target is None:
                continue
            import_pairs.append((pending.module_logical_name, target_module if target_module in modules else pending.module_logical_name))
            link(ProgramGraphEdgeKind.IMPORTS, pending.binding, target)

    module_names = tuple(sorted(modules))
    sccs = _strongly_connected(module_names, import_pairs)
    cyclic_modules = {name for component in sccs if len(component) > 1 for name in component}
    for source_name, target_name in sorted(set(import_pairs)):
        if source_name not in modules or target_name not in modules:
            continue
        source = modules[source_name]
        target = modules[target_name]
        if source_name in cyclic_modules and target_name in cyclic_modules and source_name != target_name:
            link(
                ProgramGraphEdgeKind.CYCLIC_IMPORT,
                source,
                target,
                logical_cycle=True,
            )
        elif source_name != target_name:
            link(ProgramGraphEdgeKind.IMPORTS, source, target)

    call_pairs: list[tuple[str, str]] = []
    for analysis in analyses:
        for pending in analysis.pending_calls:
            if pending.frontier_reason is not None:
                continue
            target = None
            if pending.local_target is not None:
                target = qn_nodes.get(pending.local_target)
            if target is None:
                target = _lookup_qn(
                    pending.expanded_name,
                    qn_nodes=qn_nodes,
                    aliases=analysis.aliases,
                    module_name=analysis.module_name,
                )
            if target is None:
                continue
            status = pending.record.resolution_status
            link(
                ProgramGraphEdgeKind.SUCCESSOR,
                pending.callsite,
                target,
                status=status,
            )
            link(
                ProgramGraphEdgeKind.CALLS,
                pending.callsite,
                target,
                status=status,
            )
            call_pairs.append((pending.caller_logical_name, target.logical_name))

    function_names = tuple(
        sorted(
            {
                node.logical_name
                for node in nodes.values()
                if node.node_kind in {
                    ProgramGraphNodeKind.FUNCTION.value,
                    ProgramGraphNodeKind.TEST.value,
                    ProgramGraphNodeKind.FIXTURE.value,
                }
            }
        )
    )
    for component in _strongly_connected(function_names, call_pairs):
        if len(component) == 1:
            name = next(iter(component))
            if (name, name) in call_pairs and name in qn_nodes:
                node = qn_nodes[name]
                link(ProgramGraphEdgeKind.MUTUAL_RECURSION, node, node, logical_cycle=True)
            continue
        ordered = tuple(sorted(component))
        for left in ordered:
            for right in ordered:
                if left == right or left not in qn_nodes or right not in qn_nodes:
                    continue
                link(
                    ProgramGraphEdgeKind.MUTUAL_RECURSION,
                    qn_nodes[left],
                    qn_nodes[right],
                    logical_cycle=True,
                )

    for analysis in analyses:
        for pending in analysis.pending_inherits:
            target = _lookup_qn(
                pending.base_name,
                qn_nodes=qn_nodes,
                aliases=analysis.aliases,
                module_name=analysis.module_name,
            )
            if target is None:
                continue
            link(ProgramGraphEdgeKind.INHERITS, pending.class_node, target)
            if pending.implements:
                link(ProgramGraphEdgeKind.IMPLEMENTS, pending.class_node, target)
        for test_qn, callee in analysis.tested_pairs:
            test_node = qn_nodes.get(test_qn)
            if test_node is None:
                continue
            target = _lookup_qn(
                callee,
                qn_nodes=qn_nodes,
                aliases=analysis.aliases,
                module_name=analysis.module_name,
            )
            if target is None or target.program_graph_node_cid == test_node.program_graph_node_cid:
                continue
            if target.node_kind in {
                ProgramGraphNodeKind.FUNCTION.value,
                ProgramGraphNodeKind.CLASS.value,
            }:
                link(ProgramGraphEdgeKind.TESTED_BY, target, test_node)
        for test_qn, fixture_name in analysis.fixture_pairs:
            test_node = qn_nodes.get(test_qn)
            if test_node is None:
                continue
            fixture = None
            for item in nodes.values():
                if item.node_kind == ProgramGraphNodeKind.FIXTURE.value and (
                    item.logical_name == fixture_name
                    or item.logical_name.endswith("." + fixture_name)
                ):
                    fixture = item
                    break
            if fixture is not None:
                link(ProgramGraphEdgeKind.USES_FIXTURE, test_node, fixture)

    sealed_edges = _seal_unmarked_cycles(tuple(edges.values()))
    edges = {item.program_graph_edge_cid: item for item in sealed_edges}

    outgoing: dict[str, list[ProgramGraphEdge]] = defaultdict(list)
    for edge in edges.values():
        outgoing[edge.source_node_cid].append(edge)

    successor_sets: list[StaticSuccessorSet] = []
    unresolved_nodes = [
        node for node in nodes.values() if is_unresolved_dynamic_node(node)
    ]
    unresolved_edges = [
        edge for edge in edges.values() if is_unresolved_dynamic_edge(edge)
    ]
    frontier_reasons: set[str] = set()
    for node in unresolved_nodes:
        reason = node.metadata.get("reason")
        if type(reason) is str:
            frontier_reasons.add(reason)
        frontier_reasons.update(node.unavailable_dimensions)
    for edge in unresolved_edges:
        frontier_reasons.update(edge.unavailable_dimensions)

    subject_kinds = {
        ProgramGraphNodeKind.FUNCTION.value,
        ProgramGraphNodeKind.TEST.value,
        ProgramGraphNodeKind.FIXTURE.value,
        ProgramGraphNodeKind.MODULE.value,
    }
    for node in nodes.values():
        if node.node_kind not in subject_kinds:
            continue
        succ_edges = [
            edge
            for edge in outgoing.get(node.program_graph_node_cid, ())
            if edge.edge_kind
            in {
                ProgramGraphEdgeKind.SUCCESSOR.value,
                ProgramGraphEdgeKind.CFG_NEXT.value,
                ProgramGraphEdgeKind.CFG_BRANCH.value,
                ProgramGraphEdgeKind.CALLS.value,
                ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value,
            }
        ]
        succ_nodes = tuple(sorted({edge.target_node_cid for edge in succ_edges}))
        incomplete = any(
            edge.resolution_status != ResolutionStatus.DEFINITE.value
            or edge.edge_kind == ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value
            for edge in succ_edges
        ) or bool(node.unavailable_dimensions and "incomplete_analysis" in node.unavailable_dimensions)
        unavailable = tuple(
            sorted(
                {
                    *node.unavailable_dimensions,
                    *(
                        dim
                        for edge in succ_edges
                        for dim in edge.unavailable_dimensions
                    ),
                }
            )
        )
        if incomplete and not unavailable:
            unavailable = (DynamicFrontierReason.INCOMPLETE_ANALYSIS.value,)
        successor_sets.append(
            StaticSuccessorSet(
                language=ProgramLanguage.PYTHON,
                subject_node_cid=node.program_graph_node_cid,
                successor_node_cids=succ_nodes,
                successor_edge_cids=tuple(sorted(edge.program_graph_edge_cid for edge in succ_edges)),
                complete=not incomplete,
                unavailable_dimensions=unavailable,
            )
        )

    incomplete_successors = [item for item in successor_sets if item.complete is False]
    frontiers: list[DynamicFrontierRecord] = []
    if unresolved_nodes or unresolved_edges or incomplete_successors:
        reasons = tuple(
            sorted(
                reason
                for reason in frontier_reasons
                if reason in {item.value for item in DynamicFrontierReason}
            )
        )
        if not reasons:
            reasons = (DynamicFrontierReason.INCOMPLETE_ANALYSIS.value,)
        unavailable = tuple(
            sorted(
                {
                    *reasons,
                    *(
                        dim
                        for item in incomplete_successors
                        for dim in item.unavailable_dimensions
                    ),
                }
            )
        )
        frontiers.append(
            DynamicFrontierRecord(
                language=ProgramLanguage.PYTHON,
                unresolved_node_cids=tuple(
                    sorted(node.program_graph_node_cid for node in unresolved_nodes)
                ),
                unresolved_edge_cids=tuple(
                    sorted(edge.program_graph_edge_cid for edge in unresolved_edges)
                ),
                reasons=reasons,
                unavailable_dimensions=unavailable or reasons,
            )
        )

    obligation_nodes = [
        node
        for node in nodes.values()
        if node.node_kind == ProgramGraphNodeKind.PROOF_OBLIGATION.value
    ]
    proof_graphs: list[ProofObligationGraph] = []
    proved_by = [
        edge
        for edge in edges.values()
        if edge.edge_kind == ProgramGraphEdgeKind.PROVED_BY.value
    ]
    by_function: dict[str, list[ProgramGraphNode]] = defaultdict(list)
    obligation_by_cid = {node.program_graph_node_cid: node for node in obligation_nodes}
    for edge in proved_by:
        target = obligation_by_cid.get(edge.target_node_cid)
        if target is not None:
            by_function[edge.source_node_cid].append(target)
    for source_cid, items in sorted(by_function.items()):
        ordered = tuple(sorted(items, key=lambda item: item.logical_name))
        proof_graphs.append(
            ProofObligationGraph(
                language=ProgramLanguage.PYTHON,
                root_obligation_cid=ordered[0].program_graph_node_cid,
                obligation_node_cids=tuple(item.program_graph_node_cid for item in ordered),
                obligation_edge_cids=tuple(
                    sorted(
                        edge.program_graph_edge_cid
                        for edge in proved_by
                        if edge.source_node_cid == source_cid
                    )
                ),
                environment_binding_cid=env_cid,
                unavailable_dimensions=("proof_discharge",),
            )
        )

    snapshot_unavailable = tuple(
        sorted(
            {
                *ALWAYS_INCOMPLETE_DIMENSIONS,
                *(dim for analysis in analyses for dim in analysis.incomplete_dimensions),
                *(dim for frontier in frontiers for dim in frontier.unavailable_dimensions),
            }
        )
    )
    node_list = tuple(nodes.values())
    edge_list = tuple(edges.values())
    callsite_list = tuple(callsites.values())
    function_list = tuple(function_symbols.values())
    contract_list = tuple(contract_states.values())
    snapshot = assemble_program_graph_snapshot(
        language=ProgramLanguage.PYTHON,
        nodes=node_list,
        edges=edge_list,
        environment_binding_set_cid=environment_binding_set_cid,
        sealed_binding_cid=sealed_binding_cid,
        callsites=callsite_list,
        function_symbols=function_list,
        contract_states=contract_list,
        proof_obligation_graphs=tuple(proof_graphs),
        successor_sets=tuple(successor_sets),
        frontiers=tuple(frontiers),
        unavailable_dimensions=snapshot_unavailable,
    )
    return {
        "snapshot": snapshot,
        "nodes": tuple(sorted(nodes.values(), key=lambda item: item.program_graph_node_cid)),
        "edges": tuple(sorted(edges.values(), key=lambda item: item.program_graph_edge_cid)),
        "callsites": tuple(sorted(callsites.values(), key=lambda item: item.callsite_record_cid)),
        "function_symbols": tuple(
            sorted(function_symbols.values(), key=lambda item: item.function_symbol_record_cid)
        ),
        "contract_states": tuple(
            sorted(contract_states.values(), key=lambda item: item.contract_state_record_cid)
        ),
        "proof_obligation_graphs": tuple(
            sorted(proof_graphs, key=lambda item: item.proof_obligation_graph_cid)
        ),
        "successor_sets": tuple(
            sorted(successor_sets, key=lambda item: item.static_successor_set_cid)
        ),
        "frontiers": tuple(
            sorted(frontiers, key=lambda item: item.dynamic_frontier_record_cid)
        ),
        "qn_nodes": qn_nodes,
        "unavailable_dimensions": snapshot_unavailable,
        "environment_binding_set_cid": environment_binding_set_cid,
        "sealed_binding_cid": sealed_binding_cid,
    }


def _bind_manifests(
    snapshot: ProgramGraphSnapshot,
    frontiers: Sequence[DynamicFrontierRecord],
) -> tuple[ProgramGraphIndexManifest, ...]:
    frontier_projection = (
        frontiers[0].dynamic_frontier_record_cid if frontiers else None
    )
    return (
        bind_index_manifest(
            ProgramGraphIndexManifest(
                snapshot_cid=snapshot.program_graph_snapshot_cid,
                index_kind=ProgramGraphIndexKind.ADJACENCY,
                schema_ids=(snapshot.SCHEMA,),
            ),
            snapshot,
        ),
        bind_index_manifest(
            ProgramGraphIndexManifest(
                snapshot_cid=snapshot.program_graph_snapshot_cid,
                index_kind=ProgramGraphIndexKind.SUCCESSOR,
                schema_ids=(StaticSuccessorSet.SCHEMA,),
            ),
            snapshot,
        ),
        bind_index_manifest(
            ProgramGraphIndexManifest(
                snapshot_cid=snapshot.program_graph_snapshot_cid,
                index_kind=ProgramGraphIndexKind.FRONTIER,
                schema_ids=(DynamicFrontierRecord.SCHEMA,),
                authoritative=False,
                projection_cid=frontier_projection,
            ),
            snapshot,
        ),
    )


def _coverage_for(
    *,
    analyses: Sequence[_FileAnalysis],
    nodes: Sequence[ProgramGraphNode],
    edges: Sequence[ProgramGraphEdge],
    rebuilt_paths: Sequence[str],
    reused_paths: Sequence[str],
    frontiers: Sequence[DynamicFrontierRecord],
) -> ProgramGraphCoverageReceipt:
    by_kind = {kind: 0 for kind in PROJECTION_NAMES}
    projection_of = {
        ProgramGraphNodeKind.AST.value: "ast",
        ProgramGraphNodeKind.SYMBOL.value: "symbol",
        ProgramGraphNodeKind.FUNCTION.value: "symbol",
        ProgramGraphNodeKind.CLASS.value: "symbol",
        ProgramGraphNodeKind.MODULE.value: "symbol",
        ProgramGraphNodeKind.PACKAGE.value: "symbol",
        ProgramGraphNodeKind.IMPORT_BINDING.value: "import",
        ProgramGraphNodeKind.CALLSITE.value: "call",
        ProgramGraphNodeKind.CFG_BLOCK.value: "cfg",
        ProgramGraphNodeKind.DATA_FLOW.value: "data_flow",
        ProgramGraphNodeKind.EXCEPTION_HANDLER.value: "exception",
        ProgramGraphNodeKind.TYPE_BINDING.value: "type",
        ProgramGraphNodeKind.EFFECT.value: "effect",
        ProgramGraphNodeKind.CONTRACT_STATE.value: "contract",
        ProgramGraphNodeKind.TEST.value: "test",
        ProgramGraphNodeKind.FIXTURE.value: "test",
        ProgramGraphNodeKind.PROOF_OBLIGATION.value: "proof",
        ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value: "call",
    }
    incomplete = {item for analysis in analyses for item in analysis.incomplete_dimensions}
    incomplete.update(ALWAYS_INCOMPLETE_DIMENSIONS)
    for node in nodes:
        projection = projection_of.get(node.node_kind)
        if projection is not None:
            by_kind[projection] += 1
        if node.unavailable_dimensions:
            incomplete.update(node.unavailable_dimensions)
    statuses: dict[str, str] = {}
    for name in PROJECTION_NAMES:
        if by_kind[name] == 0:
            statuses[name] = ProjectionStatus.EMPTY.value
        elif name in incomplete or name in {"type", "proof", "contract"}:
            statuses[name] = ProjectionStatus.INCOMPLETE.value
        else:
            statuses[name] = ProjectionStatus.COMPLETE.value
    reasons = tuple(
        sorted({reason for frontier in frontiers for reason in frontier.reasons})
    )
    return ProgramGraphCoverageReceipt(
        projections=statuses,
        incomplete_dimensions=tuple(sorted(incomplete)),
        observed_frontier_reasons=reasons,
        file_count=len(analyses),
        node_count=len(nodes),
        edge_count=len(edges),
        rebuilt_path_count=len(tuple(rebuilt_paths)),
        reused_path_count=len(tuple(reused_paths)),
    )


# ---------------------------------------------------------------------------
# Builder / planner
# ---------------------------------------------------------------------------


class ProgramGraphBuilder:
    """Construct deterministic, conservative current-tree program graphs."""

    interface: ClassVar[str] = PROGRAM_GRAPH_BUILDER_INTERFACE
    version: ClassVar[str] = PROGRAM_GRAPH_BUILDER_VERSION

    def __init__(self, *, repository_id: str = "repository:unknown") -> None:
        self.repository_id = _text(repository_id, "repository_id")

    def build(
        self,
        sources: Mapping[str, str | bytes],
        *,
        environment_bindings: Sequence[EnvironmentBinding] | None = None,
        environment_binding_set_cid: str | None = None,
        sealed_binding_cid: str | None = None,
        previous: ProgramGraphBuildReceipt | None = None,
    ) -> ProgramGraphBuildReceipt:
        if not isinstance(sources, Mapping):
            raise ProgramGraphBuilderError("sources must be a path-to-bytes mapping")
        normalized: dict[str, bytes] = {}
        for raw_path, payload in sources.items():
            path = _normalize_path(str(raw_path))
            normalized[path] = _source_bytes(payload)
        binding_set = _default_binding_set(environment_bindings)
        binding_set_cid = environment_binding_set_cid or binding_set.binding_set_cid
        sealed_cid = sealed_binding_cid or _seal_binding_cid(binding_set_cid)
        source_cids = {
            path: cid_for_bytes(payload) for path, payload in sorted(normalized.items())
        }
        previous_by_path: dict[str, _FileAnalysis] = {}
        can_reuse = (
            previous is not None
            and previous.sealed_binding_cid == sealed_cid
            and previous.environment_binding_set_cid == binding_set_cid
        )
        if can_reuse and previous is not None:
            previous_by_path = {item.path: item for item in previous.file_analyses}
        rebuilt: list[str] = []
        reused: list[str] = []
        analyses: list[_FileAnalysis] = []
        python_sources = {
            path: payload
            for path, payload in normalized.items()
            if _is_python_path(path)
        }
        pytest_by_path: dict[str, Any] = {}
        if python_sources:
            pytest_result = PytestAnalyzer(repository_id=self.repository_id).analyze_files(
                python_sources
            )
            grouped: dict[str, Any] = {}
            for item in pytest_result.tests:
                grouped.setdefault(item.path, []).append(("test", item))
            for item in pytest_result.fixtures:
                grouped.setdefault(item.path, []).append(("fixture", item))

            @dataclass(frozen=True)
            class _PytestFacts:
                tests: tuple[Any, ...]
                fixtures: tuple[Any, ...]

            for path, items in grouped.items():
                pytest_by_path[path] = _PytestFacts(
                    tests=tuple(item for kind, item in items if kind == "test"),
                    fixtures=tuple(item for kind, item in items if kind == "fixture"),
                )
        diagnostics: list[str] = []
        for path, payload in sorted(normalized.items()):
            if not _is_python_path(path):
                diagnostics.append(f"skipped_non_python:{path}")
                continue
            cached = previous_by_path.get(path) if can_reuse else None
            if cached is not None and cached.source_cid == source_cids[path]:
                analyses.append(cached)
                reused.append(path)
                continue
            analyses.append(
                _analyze_python_file(
                    path=path,
                    source=payload,
                    env_cid=sealed_cid,
                    repository_id=self.repository_id,
                    pytest_by_path=pytest_by_path,
                )
            )
            rebuilt.append(path)
        assembled = _assemble_analyses(
            analyses,
            env_cid=sealed_cid,
            environment_binding_set_cid=binding_set_cid,
            sealed_binding_cid=sealed_cid,
        )
        path_groups: dict[str, list[str]] = defaultdict(list)
        for node in assembled["nodes"]:
            path = node.metadata.get("path")
            if type(path) is str:
                path_groups[path].append(node.program_graph_node_cid)
        nodes_by_path = {
            path: tuple(sorted(cids)) for path, cids in sorted(path_groups.items())
        }
        mode = "incremental" if reused and previous is not None else "full"
        coverage = _coverage_for(
            analyses=analyses,
            nodes=assembled["nodes"],
            edges=assembled["edges"],
            rebuilt_paths=rebuilt,
            reused_paths=reused,
            frontiers=assembled["frontiers"],
        )
        assembled["index_manifests"] = _bind_manifests(
            assembled["snapshot"], assembled["frontiers"]
        )
        for analysis in analyses:
            diagnostics.extend(analysis.diagnostics)
        return ProgramGraphBuildReceipt(
            snapshot=assembled["snapshot"],
            nodes=assembled["nodes"],
            edges=assembled["edges"],
            callsites=assembled["callsites"],
            function_symbols=assembled["function_symbols"],
            contract_states=assembled["contract_states"],
            proof_obligation_graphs=assembled["proof_obligation_graphs"],
            successor_sets=assembled["successor_sets"],
            frontiers=assembled["frontiers"],
            index_manifests=assembled["index_manifests"],
            coverage=coverage,
            source_cids=source_cids,
            nodes_by_path=nodes_by_path,
            rebuilt_paths=tuple(rebuilt),
            reused_paths=tuple(reused),
            mode=mode,
            environment_binding_set_cid=binding_set_cid,
            sealed_binding_cid=sealed_cid,
            file_analyses=tuple(analyses),
            diagnostics=tuple(diagnostics),
        )


class ProgramGraphInvalidationPlanner:
    """Plan precise, conservative invalidation from two sealed graph receipts."""

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
        computed = delta or delta_between_snapshots(previous.snapshot, current.snapshot)
        if computed.previous_snapshot_cid != previous.snapshot.program_graph_snapshot_cid:
            raise ProgramGraphBuilderError("delta is not bound to the previous snapshot")
        full_rebuild = (
            previous.sealed_binding_cid != current.sealed_binding_cid
            or previous.environment_binding_set_cid != current.environment_binding_set_cid
        )
        prev_nodes = previous.node_by_cid()
        curr_nodes = current.node_by_cid()
        removed = set(computed.removed_node_cids)
        added = set(computed.added_node_cids)
        retained = set(computed.retained_subroot_cids)
        if full_rebuild:
            invalidated = set(previous.snapshot.node_cids) | set(current.snapshot.node_cids)
            obligations = [
                ProgramGraphInvalidationObligation(
                    subject_cid=current.snapshot.program_graph_snapshot_cid,
                    subject_kind="snapshot",
                    reason=InvalidationReason.ENVIRONMENT_CHANGED.value,
                    remediation=InvalidationRemediation.FULL_REBUILD.value,
                    confidence="exact",
                )
            ]
            return ProgramGraphInvalidationPlan(
                previous_snapshot_cid=previous.snapshot.program_graph_snapshot_cid,
                current_snapshot_cid=current.snapshot.program_graph_snapshot_cid,
                delta_cid=computed.program_graph_delta_cid,
                invalidated_node_cids=tuple(invalidated),
                invalidated_edge_cids=tuple(
                    set(previous.snapshot.edge_cids) | set(current.snapshot.edge_cids)
                ),
                retained_subroot_cids=(),
                obligations=tuple(obligations),
                full_rebuild=True,
            )

        adjacency: dict[str, list[tuple[ProgramGraphEdge, str]]] = defaultdict(list)
        for edge in (*previous.edges, *current.edges):
            if edge.edge_kind not in _DEPENDENCY_EDGE_KINDS:
                continue
            adjacency[edge.source_node_cid].append((edge, edge.target_node_cid))
            adjacency[edge.target_node_cid].append((edge, edge.source_node_cid))

        seeds = set(removed)
        changed_paths = [
            path
            for path, cid in current.source_cids.items()
            if previous.source_cids.get(path) != cid
        ]
        removed_paths = [path for path in previous.source_cids if path not in current.source_cids]
        added_paths = [path for path in current.source_cids if path not in previous.source_cids]
        for path in (*changed_paths, *removed_paths):
            seeds.update(previous.nodes_by_path.get(path, ()))
        for path in (*changed_paths, *added_paths):
            seeds.update(current.nodes_by_path.get(path, ()))

        dependents: set[str] = set()
        supporting: dict[str, set[str]] = defaultdict(set)
        reasons: dict[str, str] = {}
        queue = deque(seeds)
        seen = set(seeds)
        while queue:
            node_cid = queue.popleft()
            for edge, other in adjacency.get(node_cid, ()):
                if other in seen:
                    supporting[other].add(edge.program_graph_edge_cid)
                    continue
                seen.add(other)
                supporting[other].add(edge.program_graph_edge_cid)
                if other in retained:
                    dependents.add(other)
                    reasons.setdefault(other, InvalidationReason.DEPENDENT_OF_CHANGED.value)
                    if edge.edge_kind in {
                        ProgramGraphEdgeKind.IMPORTS.value,
                        ProgramGraphEdgeKind.CYCLIC_IMPORT.value,
                    }:
                        reasons[other] = InvalidationReason.IMPORT_TARGET_CHANGED.value
                    elif edge.edge_kind in {
                        ProgramGraphEdgeKind.CALLS.value,
                        ProgramGraphEdgeKind.SUCCESSOR.value,
                        ProgramGraphEdgeKind.MUTUAL_RECURSION.value,
                    }:
                        reasons[other] = InvalidationReason.CALLEE_CHANGED.value
                    elif edge.edge_kind == ProgramGraphEdgeKind.TESTED_BY.value:
                        reasons[other] = InvalidationReason.TESTED_SUBJECT_CHANGED.value
                    elif edge.edge_kind == ProgramGraphEdgeKind.PROVED_BY.value:
                        reasons[other] = InvalidationReason.PROOF_SUBJECT_CHANGED.value
                    elif edge.edge_kind == ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value:
                        reasons[other] = InvalidationReason.UNRESOLVED_FRONTIER.value
                queue.append(other)

        invalidated_nodes = set(removed) | set(added) | dependents
        valid_retained = tuple(sorted(retained - dependents))
        invalidated_edges = set(computed.removed_edge_cids) | set(computed.added_edge_cids)
        for edge in (*previous.edges, *current.edges):
            if (
                edge.source_node_cid in invalidated_nodes
                or edge.target_node_cid in invalidated_nodes
            ):
                invalidated_edges.add(edge.program_graph_edge_cid)

        obligations: list[ProgramGraphInvalidationObligation] = []
        for path in changed_paths:
            for cid in current.nodes_by_path.get(path, ()):
                node = curr_nodes.get(cid)
                obligations.append(
                    ProgramGraphInvalidationObligation(
                        subject_cid=cid,
                        subject_kind="node",
                        reason=InvalidationReason.SOURCE_CHANGED.value,
                        remediation=InvalidationRemediation.REBUILD_SUBGRAPH.value,
                        logical_name="" if node is None else node.logical_name,
                    )
                )
        for path in removed_paths:
            for cid in previous.nodes_by_path.get(path, ()):
                node = prev_nodes.get(cid)
                obligations.append(
                    ProgramGraphInvalidationObligation(
                        subject_cid=cid,
                        subject_kind="node",
                        reason=InvalidationReason.SOURCE_REMOVED.value,
                        remediation=InvalidationRemediation.REBUILD_SUBGRAPH.value,
                        logical_name="" if node is None else node.logical_name,
                    )
                )
        for path in added_paths:
            for cid in current.nodes_by_path.get(path, ()):
                node = curr_nodes.get(cid)
                obligations.append(
                    ProgramGraphInvalidationObligation(
                        subject_cid=cid,
                        subject_kind="node",
                        reason=InvalidationReason.SOURCE_ADDED.value,
                        remediation=InvalidationRemediation.REBUILD_SUBGRAPH.value,
                        logical_name="" if node is None else node.logical_name,
                    )
                )
        for cid in sorted(dependents):
            node = curr_nodes.get(cid) or prev_nodes.get(cid)
            reason = reasons.get(cid, InvalidationReason.DEPENDENT_OF_CHANGED.value)
            if reason == InvalidationReason.TESTED_SUBJECT_CHANGED.value:
                remediation = InvalidationRemediation.RERUN_TEST.value
            elif reason == InvalidationReason.PROOF_SUBJECT_CHANGED.value:
                remediation = InvalidationRemediation.RERUN_PROOF.value
            else:
                remediation = InvalidationRemediation.RERESOLVE.value
            obligations.append(
                ProgramGraphInvalidationObligation(
                    subject_cid=cid,
                    subject_kind="node",
                    reason=reason,
                    remediation=remediation,
                    confidence="conservative"
                    if reason == InvalidationReason.UNRESOLVED_FRONTIER.value
                    else "exact",
                    supporting_edge_cids=tuple(supporting.get(cid, ())),
                    logical_name="" if node is None else node.logical_name,
                )
            )
        if removed and not added and not dependents:
            for cid in sorted(removed):
                obligations.append(
                    ProgramGraphInvalidationObligation(
                        subject_cid=cid,
                        subject_kind="node",
                        reason=InvalidationReason.DELETED_DEPENDENCY.value,
                        remediation=InvalidationRemediation.REBUILD_SUBGRAPH.value,
                    )
                )
        return ProgramGraphInvalidationPlan(
            previous_snapshot_cid=previous.snapshot.program_graph_snapshot_cid,
            current_snapshot_cid=current.snapshot.program_graph_snapshot_cid,
            delta_cid=computed.program_graph_delta_cid,
            invalidated_node_cids=tuple(invalidated_nodes),
            invalidated_edge_cids=tuple(invalidated_edges),
            retained_subroot_cids=valid_retained,
            obligations=tuple(obligations),
            full_rebuild=False,
        )


def build_program_graph(
    sources: Mapping[str, str | bytes],
    *,
    repository_id: str = "repository:unknown",
    environment_bindings: Sequence[EnvironmentBinding] | None = None,
    environment_binding_set_cid: str | None = None,
    sealed_binding_cid: str | None = None,
    previous: ProgramGraphBuildReceipt | None = None,
) -> ProgramGraphBuildReceipt:
    """Construct a sealed current-tree program graph from explicit sources."""

    return ProgramGraphBuilder(repository_id=repository_id).build(
        sources,
        environment_bindings=environment_bindings,
        environment_binding_set_cid=environment_binding_set_cid,
        sealed_binding_cid=sealed_binding_cid,
        previous=previous,
    )


def compute_program_graph_delta(
    previous: ProgramGraphBuildReceipt | ProgramGraphSnapshot,
    current: ProgramGraphBuildReceipt | ProgramGraphSnapshot,
) -> ProgramGraphDelta:
    """Return the exact node/edge delta, retaining every unchanged subroot CID."""

    previous_snapshot = (
        previous.snapshot if isinstance(previous, ProgramGraphBuildReceipt) else previous
    )
    current_snapshot = (
        current.snapshot if isinstance(current, ProgramGraphBuildReceipt) else current
    )
    if not isinstance(previous_snapshot, ProgramGraphSnapshot) or not isinstance(
        current_snapshot, ProgramGraphSnapshot
    ):
        raise ProgramGraphBuilderError("delta comparison requires program-graph snapshots")
    return delta_between_snapshots(previous_snapshot, current_snapshot)


def plan_program_graph_invalidation(
    previous: ProgramGraphBuildReceipt,
    current: ProgramGraphBuildReceipt,
    *,
    delta: ProgramGraphDelta | None = None,
) -> ProgramGraphInvalidationPlan:
    """Plan dependency-aware invalidation without unsound omission."""

    return ProgramGraphInvalidationPlanner().plan(previous, current, delta=delta)


__all__ = [
    "ALWAYS_INCOMPLETE_DIMENSIONS",
    "PROGRAM_GRAPH_BUILDER_INTERFACE",
    "PROGRAM_GRAPH_BUILDER_VERSION",
    "PROGRAM_GRAPH_BUILD_RECEIPT_SCHEMA",
    "PROGRAM_GRAPH_BUILD_SCHEMA",
    "PROGRAM_GRAPH_COVERAGE_RECEIPT_SCHEMA",
    "PROGRAM_GRAPH_INVALIDATION_OBLIGATION_SCHEMA",
    "PROGRAM_GRAPH_INVALIDATION_PLAN_SCHEMA",
    "PROJECTION_NAMES",
    "PYTHON_STATIC_PROFILE",
    "InvalidationReason",
    "InvalidationRemediation",
    "ProgramGraphBuildReceipt",
    "ProgramGraphBuilder",
    "ProgramGraphBuilderError",
    "ProgramGraphCoverageReceipt",
    "ProgramGraphInvalidationObligation",
    "ProgramGraphInvalidationPlan",
    "ProgramGraphInvalidationPlanner",
    "ProjectionStatus",
    "build_program_graph",
    "compute_program_graph_delta",
    "plan_program_graph_invalidation",
]
