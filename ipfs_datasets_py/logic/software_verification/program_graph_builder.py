"""Deterministic static program-graph construction and invalidation.

This module owns datasets ``build_program_graph``, ``compute_program_graph_delta``,
and ``plan_program_graph_invalidation``.  It projects admitted Python source into
the SAWM-005 ``ProgramGraphSnapshot@1`` family: AST, symbol, import, call, CFG,
data-flow, exception, type/effect, contract, test, and proof records.

Authority rules (normative):

* Construction is static and non-executing.  Analyzed source is never imported,
  compiled to bytecode, or evaluated.  Cold import of this module performs no
  repository scan, network I/O, subprocess, or environment mutation.
* Graphs are deterministic: source order, dict iteration, and set iteration do
  not affect snapshot or receipt CIDs.  Collection identity is CID-sorted.
* Unknown, dynamic, native, plugin, and unsupported behavior widens an explicit
  frontier and marks successor sets incomplete.  It is never encoded as absence.
* Invalidation is dependency-closed and conservative: importers, callers, and
  other cross-file dependents of a changed unit are rebuilt; unresolved dynamic
  imports are rebuilt when the module set changes.  Unrelated units stay retained.
* Incremental linking of retained module graphs must match a full rebuild of the
  same current sources (incremental/full parity).
* Datasets defines graph meaning.  This module does not create an accelerator
  planning graph, HNSW/ANN index, or operational authority.
"""

from __future__ import annotations

import ast
import unicodedata
from collections import defaultdict, deque
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
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
    ProofObligationGraph,
    ResolutionStatus,
    StaticSuccessorSet,
    apply_program_graph_delta,
    assemble_program_graph_snapshot,
    bind_index_manifest,
    delta_between_snapshots,
    directed_logical_cycles,
    program_graph_cid_for,
    verify_program_graph_catalog,
)
# ProgramGraphError is owned by the contract module; construction wraps failures.


PROGRAM_GRAPH_BUILDER_INTERFACE: Final[str] = "ProgramGraphBuilder@1"
PROGRAM_GRAPH_BUILD_RECEIPT_INTERFACE: Final[str] = "ProgramGraphBuildReceipt@1"
PROGRAM_GRAPH_INVALIDATION_PLANNER_INTERFACE: Final[str] = (
    "ProgramGraphInvalidationPlanner@1"
)
PROGRAM_GRAPH_BUILD_RECEIPT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-graph-build-receipt@1"
)
PROGRAM_GRAPH_COVERAGE_RECEIPT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-graph-coverage-receipt@1"
)
PROGRAM_GRAPH_INVALIDATION_PLAN_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-graph-invalidation-plan@1"
)
PROGRAM_GRAPH_BUILDER_VERSION: Final[str] = "1"
ADMITTED_SOURCE_EXTENSIONS: Final[tuple[str, ...]] = (".py", ".pyi")
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
BUILTINS_PROFILE_BYTES: Final[bytes] = b"python-admitted-builtins-profile:v1"
PACKAGE_PROFILE_PREFIX: Final[bytes] = b"python-package-identity:"
PYTHON_BUILTINS: Final[frozenset[str]] = frozenset(
    {
        "abs",
        "all",
        "any",
        "bool",
        "bytes",
        "callable",
        "chr",
        "dict",
        "enumerate",
        "filter",
        "float",
        "format",
        "frozenset",
        "getattr",
        "hasattr",
        "hash",
        "id",
        "int",
        "isinstance",
        "issubclass",
        "iter",
        "len",
        "list",
        "map",
        "max",
        "min",
        "next",
        "object",
        "open",
        "ord",
        "print",
        "range",
        "repr",
        "reversed",
        "set",
        "setattr",
        "slice",
        "sorted",
        "str",
        "sum",
        "tuple",
        "type",
        "zip",
        "Exception",
        "ValueError",
        "TypeError",
        "RuntimeError",
        "KeyError",
        "AttributeError",
        "ImportError",
        "StopIteration",
        "AssertionError",
        "NotImplementedError",
    }
)
_DYNAMIC_CALLS: Final[frozenset[str]] = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "builtins.eval",
        "builtins.exec",
        "builtins.compile",
        "builtins.__import__",
        "importlib.import_module",
        "importlib.__import__",
        "runpy.run_module",
        "runpy.run_path",
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
        "builtins.getattr",
        "builtins.setattr",
        "builtins.delattr",
        "builtins.hasattr",
        "builtins.vars",
        "builtins.dir",
        "inspect.getattr_static",
        "inspect.getmembers",
        "inspect.signature",
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
_NATIVE_MODULES: Final[frozenset[str]] = frozenset(
    {"ctypes", "cffi", "cython", "numpy.ctypeslib"}
)
_EFFECT_CALLS: Final[frozenset[str]] = frozenset(
    {
        "open",
        "print",
        "input",
        "write",
        "writelines",
        "os.system",
        "os.remove",
        "os.popen",
        "subprocess.run",
        "subprocess.Popen",
        "subprocess.call",
        "socket.socket",
        "requests.get",
        "requests.post",
        "pathlib.Path.write_text",
        "pathlib.Path.write_bytes",
    }
)
_PLUGIN_CALLS: Final[frozenset[str]] = frozenset(
    {
        "importlib.metadata.entry_points",
        "importlib_metadata.entry_points",
        "pkg_resources.iter_entry_points",
    }
)
_CONTRACT_HEADINGS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "pre": ContractKind.PRECONDITION.value,
        "precondition": ContractKind.PRECONDITION.value,
        "preconditions": ContractKind.PRECONDITION.value,
        "requires": ContractKind.PRECONDITION.value,
        "require": ContractKind.PRECONDITION.value,
        "post": ContractKind.POSTCONDITION.value,
        "postcondition": ContractKind.POSTCONDITION.value,
        "postconditions": ContractKind.POSTCONDITION.value,
        "ensures": ContractKind.POSTCONDITION.value,
        "ensure": ContractKind.POSTCONDITION.value,
        "invariant": ContractKind.INVARIANT.value,
        "invariants": ContractKind.INVARIANT.value,
        "raises": ContractKind.EXCEPTIONAL.value,
        "raise": ContractKind.EXCEPTIONAL.value,
        "except": ContractKind.EXCEPTIONAL.value,
        "frame": ContractKind.FRAME.value,
        "modifies": ContractKind.FRAME.value,
    }
)
_SELF_ARGS: Final[frozenset[str]] = frozenset({"self", "cls"})


class ProgramGraphBuildError(ValueError):
    """Raised when static graph construction inputs or results fail closed."""


class InvalidationReasonCode(str, Enum):
    SOURCE_CHANGED = "source_changed"
    SOURCE_ADDED = "source_added"
    SOURCE_REMOVED = "source_removed"
    IMPORT_DEPENDENT = "import_dependent"
    CALL_DEPENDENT = "call_dependent"
    CROSS_FILE_DEPENDENT = "cross_file_dependent"
    UNRESOLVED_IMPORT_FRONTIER = "unresolved_import_frontier"
    ENVIRONMENT_BINDING_CHANGED = "environment_binding_changed"
    SEALED_BINDING_CHANGED = "sealed_binding_changed"
    LANGUAGE_UNAVAILABLE = "language_unavailable"


@dataclass(frozen=True, slots=True)
class ProgramSourceUnit:
    """One explicit current-tree source unit; never discovered by scanning."""

    path: str
    source_text: str


@dataclass(frozen=True, slots=True)
class ProgramGraphCoverageReceipt:
    """Honest projection coverage; incomplete dimensions stay explicit."""

    projections: tuple[str, ...]
    complete_projections: tuple[str, ...]
    incomplete_projections: tuple[str, ...]
    node_kind_counts: Mapping[str, int]
    edge_kind_counts: Mapping[str, int]
    frontier_reasons: tuple[str, ...]
    unavailable_dimensions: tuple[str, ...]
    source_count: int
    parse_error_paths: tuple[str, ...]

    SCHEMA: ClassVar[str] = PROGRAM_GRAPH_COVERAGE_RECEIPT_SCHEMA

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "projections": list(self.projections),
            "complete_projections": list(self.complete_projections),
            "incomplete_projections": list(self.incomplete_projections),
            "node_kind_counts": {key: self.node_kind_counts[key] for key in sorted(self.node_kind_counts)},
            "edge_kind_counts": {key: self.edge_kind_counts[key] for key in sorted(self.edge_kind_counts)},
            "frontier_reasons": list(self.frontier_reasons),
            "unavailable_dimensions": list(self.unavailable_dimensions),
            "source_count": self.source_count,
            "parse_error_paths": list(self.parse_error_paths),
        }

    @property
    def program_graph_coverage_receipt_cid(self) -> str:
        return program_graph_cid_for(self.identity_payload())


@dataclass(frozen=True, slots=True)
class ProgramGraphInvalidationPlan:
    """Dependency-closed rebuild set; unrelated subroots remain retained."""

    changed_paths: tuple[str, ...]
    added_paths: tuple[str, ...]
    removed_paths: tuple[str, ...]
    invalidated_paths: tuple[str, ...]
    retained_paths: tuple[str, ...]
    retained_subroot_cids: tuple[str, ...]
    invalidated_node_cids: tuple[str, ...]
    full_rebuild_required: bool
    environment_changed: bool
    reasons: tuple[str, ...]

    SCHEMA: ClassVar[str] = PROGRAM_GRAPH_INVALIDATION_PLAN_SCHEMA

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "changed_paths": list(self.changed_paths),
            "added_paths": list(self.added_paths),
            "removed_paths": list(self.removed_paths),
            "invalidated_paths": list(self.invalidated_paths),
            "retained_paths": list(self.retained_paths),
            "retained_subroot_cids": list(self.retained_subroot_cids),
            "invalidated_node_cids": list(self.invalidated_node_cids),
            "full_rebuild_required": self.full_rebuild_required,
            "environment_changed": self.environment_changed,
            "reasons": list(self.reasons),
        }

    @property
    def program_graph_invalidation_plan_cid(self) -> str:
        return program_graph_cid_for(self.identity_payload())


@dataclass(frozen=True, slots=True)
class _ImportSpec:
    module_name: str
    alias: str
    level: int
    is_star: bool
    lineno: int
    col: int
    native: bool
    dynamic: bool


@dataclass(frozen=True, slots=True)
class _CallSpec:
    caller_logical_name: str
    callee_name: str
    ordinal: int
    lineno: int
    col: int
    reasons: tuple[str, ...]
    effect: bool


@dataclass(frozen=True, slots=True)
class _InheritSpec:
    child_logical_name: str
    base_name: str
    lineno: int
    protocol: bool


@dataclass(frozen=True, slots=True)
class _TypeSpec:
    owner_logical_name: str
    binding_logical_name: str
    annotation: str
    lineno: int


@dataclass(frozen=True, slots=True)
class _RaiseSpec:
    owner_logical_name: str
    exception_name: str
    lineno: int


@dataclass(frozen=True, slots=True)
class _FixtureUseSpec:
    test_logical_name: str
    fixture_name: str


@dataclass(frozen=True, slots=True)
class _TestTargetSpec:
    test_logical_name: str
    callee_name: str


@dataclass(frozen=True, slots=True)
class ModuleGraph:
    """Path-local graph plus unresolved cross-file specs for later linking."""

    path: str
    module_name: str
    source_cid: str
    is_package: bool
    parse_error: bool
    nodes: tuple[ProgramGraphNode, ...]
    edges: tuple[ProgramGraphEdge, ...]
    function_symbols: tuple[FunctionSymbolRecord, ...]
    contract_states: tuple[ContractStateRecord, ...]
    exports: Mapping[str, str]
    functions: Mapping[str, str]
    classes: Mapping[str, str]
    fixtures: Mapping[str, str]
    tests: tuple[str, ...]
    import_specs: tuple[_ImportSpec, ...]
    call_specs: tuple[_CallSpec, ...]
    inherit_specs: tuple[_InheritSpec, ...]
    type_specs: tuple[_TypeSpec, ...]
    raise_specs: tuple[_RaiseSpec, ...]
    fixture_uses: tuple[_FixtureUseSpec, ...]
    test_targets: tuple[_TestTargetSpec, ...]
    unavailable_dimensions: tuple[str, ...]
    frontier_reasons: tuple[str, ...]
    incomplete_projections: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProgramGraphBuildReceipt:
    """Sealed construction result: snapshot, catalog, coverage, and module graphs."""

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
    path_source_cids: Mapping[str, str]
    node_cids_by_path: Mapping[str, tuple[str, ...]]
    module_graphs: Mapping[str, ModuleGraph]
    cross_file_deps: tuple[tuple[str, str], ...]
    unresolved_import_paths: tuple[str, ...]
    environment_binding_set_cid: str
    sealed_binding_cid: str
    builder_version: str = PROGRAM_GRAPH_BUILDER_VERSION

    SCHEMA: ClassVar[str] = PROGRAM_GRAPH_BUILD_RECEIPT_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_GRAPH_BUILD_RECEIPT_INTERFACE

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "builder_version": self.builder_version,
            "snapshot_cid": self.snapshot.program_graph_snapshot_cid,
            "coverage_cid": self.coverage.program_graph_coverage_receipt_cid,
            "environment_binding_set_cid": self.environment_binding_set_cid,
            "sealed_binding_cid": self.sealed_binding_cid,
            "path_source_cids": [
                {"path": path, "source_cid": self.path_source_cids[path]}
                for path in sorted(self.path_source_cids)
            ],
        }

    @property
    def program_graph_build_receipt_cid(self) -> str:
        return program_graph_cid_for(self.identity_payload())

    def verify(self) -> None:
        verify_program_graph_catalog(
            self.snapshot,
            nodes=self.nodes,
            edges=self.edges,
            callsites=self.callsites,
            function_symbols=self.function_symbols,
            contract_states=self.contract_states,
            proof_obligation_graphs=self.proof_obligation_graphs,
            successor_sets=self.successor_sets,
            frontiers=self.frontiers,
        )
        for manifest in self.index_manifests:
            bind_index_manifest(manifest, self.snapshot)


def _nfc(value: str) -> str:
    if type(value) is not str:
        raise ProgramGraphBuildError("text must be a string")
    return unicodedata.normalize("NFC", value)


def _repo_path(path: str) -> str:
    text = _nfc(path.replace("\\", "/")).strip()
    if not text:
        raise ProgramGraphBuildError("source path must be nonempty")
    posix = PurePosixPath(text)
    if posix.is_absolute() or posix.anchor or ".." in posix.parts or posix.parts[:1] == (".",):
        raise ProgramGraphBuildError(f"path must be repository-relative: {path!r}")
    rendered = posix.as_posix()
    if rendered != text.rstrip("/"):
        # Collapse redundant separators while remaining relative.
        text = rendered
    if text.endswith("/"):
        raise ProgramGraphBuildError(f"source path must name a file: {path!r}")
    return text


def _source_cid(source_text: str) -> str:
    if type(source_text) is not str:
        raise ProgramGraphBuildError("source_text must be a string")
    return cid_for_bytes(source_text.encode("utf-8"))


def _module_name(path: str) -> tuple[str, bool]:
    parts = list(PurePosixPath(path).parts)
    is_package = False
    if parts and parts[-1].endswith(ADMITTED_SOURCE_EXTENSIONS):
        stem = parts[-1]
        is_package = stem in {"__init__.py", "__init__.pyi"}
        parts[-1] = stem.rsplit(".", 1)[0]
        if parts[-1] == "__init__":
            parts.pop()
            is_package = True
    name = ".".join(part for part in parts if part not in {".", ""})
    return (name or "__main__"), is_package


def _package_names(module_name: str) -> tuple[str, ...]:
    parts = [part for part in module_name.split(".") if part]
    return tuple(".".join(parts[:index]) for index in range(1, len(parts)))


def _expr_name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _expr_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Subscript):
        parent = _expr_name(node.value)
        return f"{parent}[]" if parent else "subscript"
    if isinstance(node, ast.Call):
        return _expr_name(node.func)
    if isinstance(node, ast.Constant):
        return type(node.value).__name__.lower() + "_literal"
    return type(node).__name__


def _render(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return " ".join(ast.unparse(node).split())
    except (AttributeError, TypeError, ValueError):
        return type(node).__name__


def _simple_name(name: str) -> str:
    return name.rsplit(".", 1)[-1] if name else ""


def _lineno(node: ast.AST) -> int:
    return max(1, int(getattr(node, "lineno", 1) or 1))


def _col(node: ast.AST) -> int:
    return max(0, int(getattr(node, "col_offset", 0) or 0))


def _declaration_cid(
    *,
    path: str,
    kind: str,
    name: str,
    lineno: int,
    col: int,
) -> str:
    return program_graph_cid_for(
        {
            "path": path,
            "kind": kind,
            "name": name,
            "lineno": lineno,
            "col": col,
        }
    )


def _meta(
    *,
    path: str,
    projection: str,
    lineno: int = 1,
    col: int = 0,
    ordinal: int | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": path,
        "projection": projection,
        "lineno": lineno,
        "col": col,
    }
    if ordinal is not None:
        payload["ordinal"] = ordinal
    if extra:
        for key, value in extra.items():
            payload[key] = value
    return payload


def _sorted_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def _parameter_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    args = node.args
    names = [item.arg for item in (*args.posonlyargs, *args.args)]
    if args.vararg:
        names.append(args.vararg.arg)
    names.extend(item.arg for item in args.kwonlyargs)
    if args.kwarg:
        names.append(args.kwarg.arg)
    return tuple(names)


def _decorator_names(node: ast.AST) -> tuple[str, ...]:
    decorators = getattr(node, "decorator_list", ())
    return tuple(_expr_name(item) for item in decorators)


def _is_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        name in {"fixture", "pytest.fixture"} or name.endswith(".fixture")
        for name in _decorator_names(node)
    )


def _is_protocol_name(name: str) -> bool:
    simple = _simple_name(name)
    return simple == "Protocol" or name in {
        "typing.Protocol",
        "typing_extensions.Protocol",
    }


def _is_test_function(name: str, class_name: str | None) -> bool:
    if name.startswith("test_") or name.endswith("_test"):
        return True
    if class_name and class_name.startswith("Test") and name.startswith("test"):
        return True
    return False


def _call_reasons(name: str) -> tuple[str, ...]:
    simple = _simple_name(name)
    reasons: list[str] = []
    if name in {"eval", "builtins.eval"} or simple == "eval":
        reasons.append(DynamicFrontierReason.EVAL.value)
    if name in {"exec", "builtins.exec"} or simple == "exec":
        reasons.append(DynamicFrontierReason.EXEC.value)
    if name in _DYNAMIC_CALLS or simple == "__import__" or name.endswith(".__import__"):
        if DynamicFrontierReason.EVAL.value not in reasons and simple != "eval":
            if simple in {"exec"} or name.endswith(".exec"):
                reasons.append(DynamicFrontierReason.EXEC.value)
            elif simple == "compile" or name.endswith(".compile"):
                reasons.append(DynamicFrontierReason.EVAL.value)
            else:
                reasons.append(DynamicFrontierReason.IMPORT_HOOK.value)
    if name in _REFLECTION_CALLS or name.endswith(".__getattribute__") or name.endswith(
        ".__setattr__"
    ):
        reasons.append(DynamicFrontierReason.REFLECTION.value)
    if (
        name in _NATIVE_CALLS
        or name.startswith("ctypes.")
        or simple in {"CDLL", "PyDLL", "WinDLL"}
    ):
        reasons.append(DynamicFrontierReason.NATIVE_CALL.value)
    if name in _PLUGIN_CALLS or (
        simple == "entry_points" and "importlib" in name and "metadata" in name
    ):
        reasons.append(DynamicFrontierReason.PLUGIN.value)
    if name == "type" or name == "types.new_class" or simple == "new_class":
        reasons.append(DynamicFrontierReason.DYNAMIC_DISPATCH.value)
    return _sorted_unique(reasons)


def _is_effect_call(name: str) -> bool:
    simple = _simple_name(name)
    if name in _EFFECT_CALLS or simple in _EFFECT_CALLS:
        return True
    if name.startswith("subprocess.") or name.startswith("os.") or name.startswith("requests."):
        return simple in {"system", "Popen", "run", "call", "remove", "popen", "get", "post", "socket"}
    return False


def _doc_contracts(doc: str | None) -> tuple[tuple[str, str], ...]:
    if not doc:
        return ()
    found: list[tuple[str, str]] = []
    current_kind = ""
    pending: list[str] = []

    def flush() -> None:
        nonlocal current_kind, pending
        if current_kind and pending:
            spec = " ".join(part.strip() for part in pending if part.strip())
            if spec:
                found.append((current_kind, spec[:512]))
        current_kind = ""
        pending = []

    for raw in doc.splitlines():
        line = raw.strip()
        if not line:
            continue
        lowered = line.lower()
        heading = ""
        rest = ""
        if ":" in line:
            label, remainder = line.split(":", 1)
            heading = _CONTRACT_HEADINGS.get(label.strip().lower(), "")
            rest = remainder.strip()
        if heading:
            flush()
            current_kind = heading
            pending = [rest] if rest else []
            continue
        if current_kind:
            pending.append(line)
            continue
        for prefix, kind in _CONTRACT_HEADINGS.items():
            token = prefix + " "
            if lowered.startswith(token):
                found.append((kind, line[len(token) :].strip()[:512]))
                break
    flush()
    unique = {(kind, spec) for kind, spec in found if spec}
    return tuple(sorted(unique))


def _absolute_import(
    module_name: str,
    is_package: bool,
    level: int,
    target: str | None,
) -> str | None:
    if level == 0:
        return target or ""
    parts = [part for part in module_name.split(".") if part]
    package = tuple(parts if is_package else parts[:-1])
    drop = level - 1
    if drop > len(package):
        return None
    base = package[: len(package) - drop]
    if target:
        return ".".join((*base, *target.split("."))) if base else target
    return ".".join(base)


def _normalize_sources(
    sources: Mapping[str, str] | Sequence[ProgramSourceUnit] | Sequence[tuple[str, str]],
) -> dict[str, str]:
    if isinstance(sources, Mapping):
        items = list(sources.items())
    else:
        items = []
        for item in sources:
            if isinstance(item, ProgramSourceUnit):
                items.append((item.path, item.source_text))
            elif isinstance(item, tuple) and len(item) == 2:
                items.append((str(item[0]), str(item[1])))
            else:
                raise ProgramGraphBuildError("sources must be path/text units")
    normalized: dict[str, str] = {}
    for path, text in items:
        key = _repo_path(path)
        if key in normalized:
            raise ProgramGraphBuildError(f"duplicate source path {key!r}")
        suffix = PurePosixPath(key).suffix
        if suffix not in ADMITTED_SOURCE_EXTENSIONS:
            raise ProgramGraphBuildError(
                f"admitted Python profile rejects source extension {suffix!r}"
            )
        if type(text) is not str:
            raise ProgramGraphBuildError("source_text must be a string")
        normalized[key] = text
    return dict(sorted(normalized.items()))


def _node(
    *,
    kind: str,
    logical_name: str,
    source_cid: str,
    sealed_binding_cid: str,
    path: str,
    projection: str,
    lineno: int = 1,
    col: int = 0,
    ordinal: int | None = None,
    declaration_cid: str | None = None,
    record_cid: str | None = None,
    subject_cid: str | None = None,
    unavailable: Sequence[str] = (),
    extra: Mapping[str, Any] | None = None,
) -> ProgramGraphNode:
    return ProgramGraphNode(
        node_kind=kind,
        language="python",
        logical_name=_nfc(logical_name),
        source_cid=source_cid,
        declaration_cid=declaration_cid,
        environment_binding_cid=sealed_binding_cid,
        subject_cid=subject_cid,
        record_cid=record_cid,
        unavailable_dimensions=unavailable,
        metadata=_meta(
            path=path,
            projection=projection,
            lineno=lineno,
            col=col,
            ordinal=ordinal,
            extra=extra,
        ),
    )


def _edge(
    *,
    kind: str,
    source: ProgramGraphNode | str,
    target: ProgramGraphNode | str,
    sealed_binding_cid: str,
    path: str,
    projection: str,
    lineno: int = 1,
    col: int = 0,
    ordinal: int | None = None,
    status: str = ResolutionStatus.DEFINITE.value,
    logical_cycle: bool = False,
    unavailable: Sequence[str] = (),
    extra: Mapping[str, Any] | None = None,
) -> ProgramGraphEdge:
    source_cid = source if isinstance(source, str) else source.program_graph_node_cid
    target_cid = target if isinstance(target, str) else target.program_graph_node_cid
    if kind == ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value and status == ResolutionStatus.DEFINITE.value:
        status = ResolutionStatus.UNRESOLVED.value
    if status in {ResolutionStatus.UNRESOLVED.value, ResolutionStatus.UNAVAILABLE.value} and not unavailable:
        unavailable = ("incomplete_analysis",)
    if kind in {
        ProgramGraphEdgeKind.CYCLIC_IMPORT.value,
        ProgramGraphEdgeKind.MUTUAL_RECURSION.value,
    }:
        logical_cycle = True
    return ProgramGraphEdge(
        edge_kind=kind,
        source_node_cid=source_cid,
        target_node_cid=target_cid,
        language="python",
        environment_binding_cid=sealed_binding_cid,
        resolution_status=status,
        logical_cycle=logical_cycle,
        unavailable_dimensions=unavailable,
        metadata=_meta(
            path=path,
            projection=projection,
            lineno=lineno,
            col=col,
            ordinal=ordinal,
            extra=extra,
        ),
    )


def _own_nodes(body: Sequence[ast.AST]) -> Iterable[ast.AST]:
    for node in body:
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


class _ModuleAnalyzer:
    def __init__(self, path: str, source_text: str, sealed_binding_cid: str) -> None:
        self.path = path
        self.source_text = source_text
        self.sealed = sealed_binding_cid
        self.source_cid = _source_cid(source_text)
        self.module_name, self.is_package = _module_name(path)
        self.nodes: list[ProgramGraphNode] = []
        self.edges: list[ProgramGraphEdge] = []
        self.function_symbols: list[FunctionSymbolRecord] = []
        self.contract_states: list[ContractStateRecord] = []
        self.exports: dict[str, str] = {}
        self.functions: dict[str, str] = {}
        self.classes: dict[str, str] = {}
        self.fixtures: dict[str, str] = {}
        self.tests: list[str] = []
        self.import_specs: list[_ImportSpec] = []
        self.call_specs: list[_CallSpec] = []
        self.inherit_specs: list[_InheritSpec] = []
        self.type_specs: list[_TypeSpec] = []
        self.raise_specs: list[_RaiseSpec] = []
        self.fixture_uses: list[_FixtureUseSpec] = []
        self.test_targets: list[_TestTargetSpec] = []
        self.unavailable: set[str] = set()
        self.frontier_reasons: set[str] = set()
        self.incomplete: set[str] = set()
        self.parse_error = False
        self._call_ordinals: dict[str, int] = defaultdict(int)
        self._cfg_ordinals: dict[str, int] = defaultdict(int)
        self._dflow_ordinals: dict[str, int] = defaultdict(int)
        self._aliases: dict[str, str] = {}
        self._protocol_names: set[str] = set()

    def add_node(self, node: ProgramGraphNode) -> ProgramGraphNode:
        self.nodes.append(node)
        return node

    def add_edge(self, edge: ProgramGraphEdge) -> ProgramGraphEdge:
        self.edges.append(edge)
        return edge

    def node(
        self,
        kind: str,
        logical_name: str,
        *,
        projection: str,
        lineno: int = 1,
        col: int = 0,
        ordinal: int | None = None,
        declaration_cid: str | None = None,
        record_cid: str | None = None,
        subject_cid: str | None = None,
        unavailable: Sequence[str] = (),
        extra: Mapping[str, Any] | None = None,
    ) -> ProgramGraphNode:
        return self.add_node(
            _node(
                kind=kind,
                logical_name=logical_name,
                source_cid=self.source_cid,
                sealed_binding_cid=self.sealed,
                path=self.path,
                projection=projection,
                lineno=lineno,
                col=col,
                ordinal=ordinal,
                declaration_cid=declaration_cid,
                record_cid=record_cid,
                subject_cid=subject_cid,
                unavailable=unavailable,
                extra=extra,
            )
        )

    def edge(
        self,
        kind: str,
        source: ProgramGraphNode | str,
        target: ProgramGraphNode | str,
        *,
        projection: str,
        lineno: int = 1,
        col: int = 0,
        ordinal: int | None = None,
        status: str = ResolutionStatus.DEFINITE.value,
        logical_cycle: bool = False,
        unavailable: Sequence[str] = (),
        extra: Mapping[str, Any] | None = None,
    ) -> ProgramGraphEdge:
        return self.add_edge(
            _edge(
                kind=kind,
                source=source,
                target=target,
                sealed_binding_cid=self.sealed,
                path=self.path,
                projection=projection,
                lineno=lineno,
                col=col,
                ordinal=ordinal,
                status=status,
                logical_cycle=logical_cycle,
                unavailable=unavailable,
                extra=extra,
            )
        )

    def analyze(self) -> ModuleGraph:
        module = self.node(
            ProgramGraphNodeKind.MODULE.value,
            self.module_name,
            projection="symbol",
            declaration_cid=_declaration_cid(
                path=self.path,
                kind="module",
                name=self.module_name,
                lineno=1,
                col=0,
            ),
        )
        source = self.node(
            ProgramGraphNodeKind.SOURCE.value,
            f"{self.module_name}#source",
            projection="ast",
            declaration_cid=_declaration_cid(
                path=self.path,
                kind="source",
                name=self.module_name,
                lineno=1,
                col=0,
            ),
        )
        self.edge(ProgramGraphEdgeKind.CONTAINS.value, module, source, projection="ast")
        try:
            tree = ast.parse(self.source_text, filename=self.path)
        except SyntaxError:
            self.parse_error = True
            self.unavailable.add("parse_error")
            self.incomplete.update(PROJECTION_NAMES)
            self.frontier_reasons.add(DynamicFrontierReason.INCOMPLETE_ANALYSIS.value)
            dynamic = self.node(
                ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value,
                f"{self.module_name}#dynamic:parse_error",
                projection="ast",
                unavailable=("parse_error",),
            )
            self.edge(
                ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value,
                module,
                dynamic,
                projection="ast",
                status=ResolutionStatus.UNAVAILABLE.value,
                unavailable=("parse_error",),
            )
            ast_node = self.node(
                ProgramGraphNodeKind.AST.value,
                f"{self.module_name}#ast",
                projection="ast",
                unavailable=("parse_error",),
            )
            self.edge(ProgramGraphEdgeKind.CONTAINS.value, source, ast_node, projection="ast")
            return self._finish(module)

        ast_node = self.node(
            ProgramGraphNodeKind.AST.value,
            f"{self.module_name}#ast",
            projection="ast",
            declaration_cid=_declaration_cid(
                path=self.path,
                kind="ast",
                name=self.module_name,
                lineno=1,
                col=0,
            ),
        )
        self.edge(ProgramGraphEdgeKind.CONTAINS.value, source, ast_node, projection="ast")
        self._collect_imports(tree)
        self._walk_body(tree.body, owner=module, class_name=None, function_name=None)
        return self._finish(module)

    def _finish(self, module: ProgramGraphNode) -> ModuleGraph:
        self.exports[self.module_name.rsplit(".", 1)[-1]] = module.program_graph_node_cid
        self.exports[self.module_name] = module.program_graph_node_cid
        return ModuleGraph(
            path=self.path,
            module_name=self.module_name,
            source_cid=self.source_cid,
            is_package=self.is_package,
            parse_error=self.parse_error,
            nodes=tuple(self.nodes),
            edges=tuple(self.edges),
            function_symbols=tuple(self.function_symbols),
            contract_states=tuple(self.contract_states),
            exports=MappingProxyType(dict(self.exports)),
            functions=MappingProxyType(dict(self.functions)),
            classes=MappingProxyType(dict(self.classes)),
            fixtures=MappingProxyType(dict(self.fixtures)),
            tests=tuple(self.tests),
            import_specs=tuple(self.import_specs),
            call_specs=tuple(self.call_specs),
            inherit_specs=tuple(self.inherit_specs),
            type_specs=tuple(self.type_specs),
            raise_specs=tuple(self.raise_specs),
            fixture_uses=tuple(self.fixture_uses),
            test_targets=tuple(self.test_targets),
            unavailable_dimensions=_sorted_unique(self.unavailable),
            frontier_reasons=_sorted_unique(self.frontier_reasons),
            incomplete_projections=_sorted_unique(self.incomplete),
        )

    def _collect_imports(self, tree: ast.AST) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    bound = alias.asname or alias.name.split(".", 1)[0]
                    self._aliases[bound] = alias.name
                    native = any(
                        alias.name == root or alias.name.startswith(root + ".")
                        for root in _NATIVE_MODULES
                    )
                    self.import_specs.append(
                        _ImportSpec(
                            module_name=alias.name,
                            alias=bound,
                            level=0,
                            is_star=False,
                            lineno=_lineno(node),
                            col=_col(node),
                            native=native,
                            dynamic=False,
                        )
                    )
                    if native:
                        self.unavailable.add("native_call")
                        self.frontier_reasons.add(DynamicFrontierReason.NATIVE_CALL.value)
                        self.incomplete.add("import")
            elif isinstance(node, ast.ImportFrom):
                target = node.module or ""
                native = bool(
                    target
                    and any(target == root or target.startswith(root + ".") for root in _NATIVE_MODULES)
                )
                module_path = _absolute_import(
                    self.module_name, self.is_package, node.level, target or None
                )
                for alias in node.names:
                    is_star = alias.name == "*"
                    bound = "*" if is_star else (alias.asname or alias.name)
                    if is_star:
                        imported = module_path or target
                    elif node.module is None:
                        imported = (
                            f"{module_path}.{alias.name}" if module_path else alias.name
                        )
                    else:
                        imported = module_path or target
                    if not is_star and imported:
                        if node.module is None:
                            self._aliases[bound] = imported
                        else:
                            self._aliases[bound] = (
                                f"{imported}.{alias.name}" if imported else alias.name
                            )
                    self.import_specs.append(
                        _ImportSpec(
                            module_name=imported,
                            alias=bound,
                            level=node.level,
                            is_star=is_star,
                            lineno=_lineno(node),
                            col=_col(node),
                            native=native,
                            dynamic=is_star,
                        )
                    )
                    if is_star:
                        self.unavailable.add("star_import")
                        self.frontier_reasons.add(
                            DynamicFrontierReason.INCOMPLETE_ANALYSIS.value
                        )
                        self.incomplete.add("import")
                    if native:
                        self.unavailable.add("native_call")
                        self.frontier_reasons.add(DynamicFrontierReason.NATIVE_CALL.value)
                        self.incomplete.add("import")

    def _walk_body(
        self,
        body: Sequence[ast.stmt],
        *,
        owner: ProgramGraphNode,
        class_name: str | None,
        function_name: str | None,
    ) -> None:
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._function(stmt, owner=owner, class_name=class_name)
            elif isinstance(stmt, ast.ClassDef):
                self._class(stmt, owner=owner)
            elif isinstance(stmt, ast.Assign):
                self._assign(stmt, owner=owner, class_name=class_name)
            elif isinstance(stmt, ast.AnnAssign):
                self._annassign(stmt, owner=owner, class_name=class_name)
            elif isinstance(stmt, ast.If):
                self._walk_body(stmt.body, owner=owner, class_name=class_name, function_name=function_name)
                self._walk_body(stmt.orelse, owner=owner, class_name=class_name, function_name=function_name)
            elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
                self._walk_body(stmt.body, owner=owner, class_name=class_name, function_name=function_name)
                self._walk_body(stmt.orelse, owner=owner, class_name=class_name, function_name=function_name)
            elif isinstance(stmt, ast.Try):
                self._walk_body(stmt.body, owner=owner, class_name=class_name, function_name=function_name)
                for handler in stmt.handlers:
                    self._walk_body(
                        handler.body, owner=owner, class_name=class_name, function_name=function_name
                    )
                self._walk_body(stmt.orelse, owner=owner, class_name=class_name, function_name=function_name)
                self._walk_body(
                    stmt.finalbody, owner=owner, class_name=class_name, function_name=function_name
                )
            elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                self._walk_body(stmt.body, owner=owner, class_name=class_name, function_name=function_name)
            elif isinstance(stmt, ast.Match):
                for case in stmt.cases:
                    self._walk_body(
                        case.body, owner=owner, class_name=class_name, function_name=function_name
                    )

    def _assign(
        self,
        stmt: ast.Assign,
        *,
        owner: ProgramGraphNode,
        class_name: str | None,
    ) -> None:
        for name in _store_names(stmt.targets[0] if stmt.targets else None):
            logical = f"{self.module_name}.{name}" if class_name is None else f"{class_name}.{name}"
            symbol = self.node(
                ProgramGraphNodeKind.SYMBOL.value,
                logical,
                projection="symbol",
                lineno=_lineno(stmt),
                col=_col(stmt),
                declaration_cid=_declaration_cid(
                    path=self.path, kind="symbol", name=logical, lineno=_lineno(stmt), col=_col(stmt)
                ),
            )
            self.edge(ProgramGraphEdgeKind.DECLARES.value, owner, symbol, projection="symbol")
            self.exports[name] = symbol.program_graph_node_cid

    def _annassign(
        self,
        stmt: ast.AnnAssign,
        *,
        owner: ProgramGraphNode,
        class_name: str | None,
    ) -> None:
        for name in _store_names(stmt.target):
            logical = f"{self.module_name}.{name}" if class_name is None else f"{class_name}.{name}"
            symbol = self.node(
                ProgramGraphNodeKind.SYMBOL.value,
                logical,
                projection="symbol",
                lineno=_lineno(stmt),
                col=_col(stmt),
                declaration_cid=_declaration_cid(
                    path=self.path, kind="symbol", name=logical, lineno=_lineno(stmt), col=_col(stmt)
                ),
            )
            self.edge(ProgramGraphEdgeKind.DECLARES.value, owner, symbol, projection="symbol")
            self.exports[name] = symbol.program_graph_node_cid
            annotation = _expr_name(stmt.annotation) or _render(stmt.annotation)
            if annotation:
                binding = self.node(
                    ProgramGraphNodeKind.TYPE_BINDING.value,
                    f"{logical}#type",
                    projection="type",
                    lineno=_lineno(stmt),
                    extra={"annotation": annotation[:128]},
                )
                self.edge(ProgramGraphEdgeKind.TYPE_OF.value, symbol, binding, projection="type")
                self.type_specs.append(
                    _TypeSpec(logical, binding.logical_name, annotation, _lineno(stmt))
                )

    def _class(self, stmt: ast.ClassDef, *, owner: ProgramGraphNode) -> None:
        logical = f"{self.module_name}.{stmt.name}"
        class_node = self.node(
            ProgramGraphNodeKind.CLASS.value,
            logical,
            projection="symbol",
            lineno=_lineno(stmt),
            col=_col(stmt),
            declaration_cid=_declaration_cid(
                path=self.path, kind="class", name=logical, lineno=_lineno(stmt), col=_col(stmt)
            ),
        )
        self.edge(ProgramGraphEdgeKind.DECLARES.value, owner, class_node, projection="symbol")
        self.edge(ProgramGraphEdgeKind.CONTAINS.value, owner, class_node, projection="symbol")
        self.exports[stmt.name] = class_node.program_graph_node_cid
        self.classes[logical] = class_node.program_graph_node_cid
        protocol_class = False
        for base in stmt.bases:
            name = self._resolve_alias(_expr_name(base))
            if not name:
                continue
            is_protocol = (
                _is_protocol_name(name)
                or name in self._protocol_names
                or _simple_name(name) in self._protocol_names
            )
            protocol_class = protocol_class or is_protocol
            self.inherit_specs.append(
                _InheritSpec(logical, name, _lineno(stmt), is_protocol)
            )
        if protocol_class:
            self._protocol_names.add(logical)
            self._protocol_names.add(stmt.name)
        if any(keyword.arg == "metaclass" for keyword in stmt.keywords):
            self.unavailable.add("dynamic_dispatch")
            self.frontier_reasons.add(DynamicFrontierReason.DYNAMIC_DISPATCH.value)
            self.incomplete.add("symbol")
            dynamic = self.node(
                ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value,
                f"{logical}#dynamic:metaclass",
                projection="symbol",
                lineno=_lineno(stmt),
                unavailable=("dynamic_dispatch",),
            )
            self.edge(
                ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value,
                class_node,
                dynamic,
                projection="symbol",
                status=ResolutionStatus.UNRESOLVED.value,
                unavailable=("dynamic_dispatch",),
            )
        self._walk_body(stmt.body, owner=class_node, class_name=logical, function_name=None)

    def _function(
        self,
        stmt: ast.FunctionDef | ast.AsyncFunctionDef,
        *,
        owner: ProgramGraphNode,
        class_name: str | None,
    ) -> None:
        parent = class_name or self.module_name
        logical = f"{parent}.{stmt.name}"
        is_async = isinstance(stmt, ast.AsyncFunctionDef)
        is_fixture = _is_fixture(stmt)
        is_test = _is_test_function(stmt.name, class_name.split(".")[-1] if class_name else None)
        if is_async:
            self.unavailable.add("async")
            self.incomplete.update(("cfg", "call", "data_flow"))
        kind = ProgramGraphNodeKind.FUNCTION.value
        if is_fixture:
            kind = ProgramGraphNodeKind.FIXTURE.value
        elif is_test:
            kind = ProgramGraphNodeKind.TEST.value
        record_cid = None
        if kind == ProgramGraphNodeKind.FUNCTION.value:
            record = FunctionSymbolRecord(
                language="python",
                logical_name=logical,
                source_cid=self.source_cid,
                declaration_cid=_declaration_cid(
                    path=self.path,
                    kind="function",
                    name=logical,
                    lineno=_lineno(stmt),
                    col=_col(stmt),
                ),
                parameter_names=_parameter_names(stmt),
                return_annotation=_render(stmt.returns),
                unavailable_dimensions=("async",) if is_async else (),
            )
            self.function_symbols.append(record)
            record_cid = record.function_symbol_record_cid
        fn = self.node(
            kind,
            logical,
            projection="symbol",
            lineno=_lineno(stmt),
            col=_col(stmt),
            declaration_cid=_declaration_cid(
                path=self.path, kind=kind, name=logical, lineno=_lineno(stmt), col=_col(stmt)
            ),
            record_cid=record_cid,
            unavailable=("async",) if is_async else (),
        )
        self.edge(ProgramGraphEdgeKind.DECLARES.value, owner, fn, projection="symbol")
        self.edge(ProgramGraphEdgeKind.CONTAINS.value, owner, fn, projection="symbol")
        self.exports[stmt.name] = fn.program_graph_node_cid
        self.functions[logical] = fn.program_graph_node_cid
        if is_fixture:
            self.fixtures[stmt.name] = fn.program_graph_node_cid
            self.incomplete.add("test")
        if is_test:
            self.tests.append(logical)
            params = [name for name in _parameter_names(stmt) if name not in _SELF_ARGS]
            for name in params:
                self.fixture_uses.append(_FixtureUseSpec(logical, name))
        self._function_types(stmt, fn, logical)
        self._function_contracts(stmt, fn, logical)
        self._function_cfg(stmt, fn, logical)
        self._function_dataflow(stmt, fn, logical)
        self._function_effects_and_calls(stmt, fn, logical, is_test=is_test)
        if is_async:
            dynamic = self.node(
                ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value,
                f"{logical}#dynamic:async",
                projection="cfg",
                lineno=_lineno(stmt),
                unavailable=("async",),
            )
            self.edge(
                ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value,
                fn,
                dynamic,
                projection="cfg",
                status=ResolutionStatus.UNRESOLVED.value,
                unavailable=("async",),
            )
            self.frontier_reasons.add(DynamicFrontierReason.INCOMPLETE_ANALYSIS.value)

    def _function_types(
        self,
        stmt: ast.FunctionDef | ast.AsyncFunctionDef,
        fn: ProgramGraphNode,
        logical: str,
    ) -> None:
        returns = _expr_name(stmt.returns) or _render(stmt.returns)
        if returns:
            binding = self.node(
                ProgramGraphNodeKind.TYPE_BINDING.value,
                f"{logical}#type:return",
                projection="type",
                lineno=_lineno(stmt),
                extra={"annotation": returns[:128]},
            )
            self.edge(ProgramGraphEdgeKind.TYPE_OF.value, fn, binding, projection="type")
            self.type_specs.append(_TypeSpec(logical, binding.logical_name, returns, _lineno(stmt)))
        for item in (*stmt.args.posonlyargs, *stmt.args.args, *stmt.args.kwonlyargs):
            annotation = _expr_name(item.annotation) or _render(item.annotation)
            if not annotation:
                self.incomplete.add("type")
                self.unavailable.add("type_inference")
                continue
            binding = self.node(
                ProgramGraphNodeKind.TYPE_BINDING.value,
                f"{logical}#type:{item.arg}",
                projection="type",
                lineno=_lineno(stmt),
                extra={"annotation": annotation[:128]},
            )
            self.edge(ProgramGraphEdgeKind.TYPE_OF.value, fn, binding, projection="type")
            self.type_specs.append(
                _TypeSpec(logical, binding.logical_name, annotation, _lineno(stmt))
            )

    def _function_contracts(
        self,
        stmt: ast.FunctionDef | ast.AsyncFunctionDef,
        fn: ProgramGraphNode,
        logical: str,
    ) -> None:
        doc = ast.get_docstring(stmt)
        clauses = list(_doc_contracts(doc))
        for child in _own_nodes(stmt.body):
            if isinstance(child, ast.Assert):
                spec = _render(child.test) or "assert"
                clauses.append((ContractKind.PRECONDITION.value, spec[:512]))
        seen: set[tuple[str, str]] = set()
        for kind, spec in clauses:
            key = (kind, spec)
            if key in seen:
                continue
            seen.add(key)
            record = ContractStateRecord(
                language="python",
                subject_logical_name=logical,
                contract_kind=kind,
                specification_cid=cid_for_bytes(spec.encode("utf-8")),
                discharge_status="unknown",
            )
            self.contract_states.append(record)
            contract = self.node(
                ProgramGraphNodeKind.CONTRACT_STATE.value,
                f"{logical}#contract:{kind}",
                projection="contract",
                lineno=_lineno(stmt),
                record_cid=record.contract_state_record_cid,
            )
            self.edge(ProgramGraphEdgeKind.BINDS_CONTRACT.value, fn, contract, projection="contract")
            obligation = self.node(
                ProgramGraphNodeKind.PROOF_OBLIGATION.value,
                f"{logical}#proof:{kind}",
                projection="proof",
                lineno=_lineno(stmt),
                subject_cid=contract.program_graph_node_cid,
            )
            self.edge(ProgramGraphEdgeKind.PROVED_BY.value, fn, obligation, projection="proof")
            self.edge(ProgramGraphEdgeKind.PROVED_BY.value, contract, obligation, projection="proof")

    def _new_cfg(self, logical: str, lineno: int) -> ProgramGraphNode:
        ordinal = self._cfg_ordinals[logical]
        self._cfg_ordinals[logical] += 1
        return self.node(
            ProgramGraphNodeKind.CFG_BLOCK.value,
            f"{logical}#cfg:{ordinal}",
            projection="cfg",
            lineno=lineno,
            ordinal=ordinal,
            extra={"block": ordinal},
        )

    def _function_cfg(
        self,
        stmt: ast.FunctionDef | ast.AsyncFunctionDef,
        fn: ProgramGraphNode,
        logical: str,
    ) -> None:
        entry = self._new_cfg(logical, _lineno(stmt))
        self.edge(ProgramGraphEdgeKind.CONTAINS.value, fn, entry, projection="cfg")
        self.edge(ProgramGraphEdgeKind.SUCCESSOR.value, fn, entry, projection="cfg")
        self._cfg_stmts(stmt.body, entry, logical, None, None)

    def _cfg_connect(
        self,
        source: ProgramGraphNode | None,
        target: ProgramGraphNode | None,
        kind: str = ProgramGraphEdgeKind.CFG_NEXT.value,
        *,
        logical: str,
        lineno: int,
        cycle: bool = False,
    ) -> None:
        if source is None or target is None:
            return
        self.edge(
            kind,
            source,
            target,
            projection="cfg",
            lineno=lineno,
            logical_cycle=cycle,
        )

    def _cfg_stmts(
        self,
        body: Sequence[ast.stmt],
        current: ProgramGraphNode | None,
        logical: str,
        break_target: ProgramGraphNode | None,
        continue_target: ProgramGraphNode | None,
    ) -> ProgramGraphNode | None:
        cursor = current
        for stmt in body:
            cursor = self._cfg_stmt(stmt, cursor, logical, break_target, continue_target)
        return cursor

    def _cfg_stmt(
        self,
        stmt: ast.stmt,
        current: ProgramGraphNode | None,
        logical: str,
        break_target: ProgramGraphNode | None,
        continue_target: ProgramGraphNode | None,
    ) -> ProgramGraphNode | None:
        if current is None:
            current = self._new_cfg(logical, _lineno(stmt))
        if isinstance(stmt, ast.If):
            then_b = self._new_cfg(logical, _lineno(stmt.body[0]) if stmt.body else _lineno(stmt))
            join = self._new_cfg(logical, _lineno(stmt))
            self._cfg_connect(
                current, then_b, ProgramGraphEdgeKind.CFG_BRANCH.value, logical=logical, lineno=_lineno(stmt)
            )
            then_end = self._cfg_stmts(stmt.body, then_b, logical, break_target, continue_target)
            self._cfg_connect(then_end, join, logical=logical, lineno=_lineno(stmt))
            if stmt.orelse:
                else_b = self._new_cfg(logical, _lineno(stmt.orelse[0]))
                self._cfg_connect(
                    current,
                    else_b,
                    ProgramGraphEdgeKind.CFG_BRANCH.value,
                    logical=logical,
                    lineno=_lineno(stmt),
                )
                else_end = self._cfg_stmts(stmt.orelse, else_b, logical, break_target, continue_target)
                self._cfg_connect(else_end, join, logical=logical, lineno=_lineno(stmt))
            else:
                self._cfg_connect(
                    current, join, ProgramGraphEdgeKind.CFG_BRANCH.value, logical=logical, lineno=_lineno(stmt)
                )
            return join
        if isinstance(stmt, (ast.While, ast.For, ast.AsyncFor)):
            header = self._new_cfg(logical, _lineno(stmt))
            body_b = self._new_cfg(logical, _lineno(stmt.body[0]) if stmt.body else _lineno(stmt))
            exit_b = self._new_cfg(logical, _lineno(stmt))
            self._cfg_connect(current, header, logical=logical, lineno=_lineno(stmt))
            self._cfg_connect(
                header, body_b, ProgramGraphEdgeKind.CFG_BRANCH.value, logical=logical, lineno=_lineno(stmt)
            )
            self._cfg_connect(
                header, exit_b, ProgramGraphEdgeKind.CFG_BRANCH.value, logical=logical, lineno=_lineno(stmt)
            )
            body_end = self._cfg_stmts(stmt.body, body_b, logical, exit_b, header)
            self._cfg_connect(body_end, header, logical=logical, lineno=_lineno(stmt), cycle=True)
            if stmt.orelse:
                else_b = self._new_cfg(logical, _lineno(stmt.orelse[0]))
                self._cfg_connect(exit_b, else_b, logical=logical, lineno=_lineno(stmt))
                else_end = self._cfg_stmts(stmt.orelse, else_b, logical, break_target, continue_target)
                join = self._new_cfg(logical, _lineno(stmt))
                self._cfg_connect(else_end, join, logical=logical, lineno=_lineno(stmt))
                return join
            return exit_b
        if isinstance(stmt, ast.Try):
            try_b = self._new_cfg(logical, _lineno(stmt))
            self._cfg_connect(current, try_b, logical=logical, lineno=_lineno(stmt))
            join = self._new_cfg(logical, _lineno(stmt))
            try_end = self._cfg_stmts(stmt.body, try_b, logical, break_target, continue_target)
            for handler in stmt.handlers:
                handler_b = self.node(
                    ProgramGraphNodeKind.EXCEPTION_HANDLER.value,
                    f"{logical}#exc:{self._cfg_ordinals[logical]}",
                    projection="exception",
                    lineno=_lineno(handler),
                    ordinal=self._cfg_ordinals[logical],
                )
                self._cfg_ordinals[logical] += 1
                self.edge(
                    ProgramGraphEdgeKind.EXCEPTION_EDGE.value,
                    try_b,
                    handler_b,
                    projection="exception",
                    lineno=_lineno(handler),
                )
                self.edge(
                    ProgramGraphEdgeKind.CATCHES.value,
                    try_b,
                    handler_b,
                    projection="exception",
                    lineno=_lineno(handler),
                )
                if try_end is not None:
                    self.edge(
                        ProgramGraphEdgeKind.EXCEPTION_EDGE.value,
                        try_end,
                        handler_b,
                        projection="exception",
                        lineno=_lineno(handler),
                    )
                handler_end = self._cfg_stmts(
                    handler.body, handler_b, logical, break_target, continue_target
                )
                self._cfg_connect(handler_end, join, logical=logical, lineno=_lineno(handler))
                name = _expr_name(handler.type)
                if name:
                    self.raise_specs.append(_RaiseSpec(logical, self._resolve_alias(name), _lineno(handler)))
            if stmt.orelse:
                else_b = self._new_cfg(logical, _lineno(stmt.orelse[0]) if stmt.orelse else _lineno(stmt))
                self._cfg_connect(try_end, else_b, logical=logical, lineno=_lineno(stmt))
                else_end = self._cfg_stmts(stmt.orelse, else_b, logical, break_target, continue_target)
                self._cfg_connect(else_end, join, logical=logical, lineno=_lineno(stmt))
            else:
                self._cfg_connect(try_end, join, logical=logical, lineno=_lineno(stmt))
            if stmt.finalbody:
                final_b = self._new_cfg(logical, _lineno(stmt.finalbody[0]))
                self._cfg_connect(join, final_b, logical=logical, lineno=_lineno(stmt))
                return self._cfg_stmts(stmt.finalbody, final_b, logical, break_target, continue_target)
            return join
        if isinstance(stmt, ast.Return):
            term = self._new_cfg(logical, _lineno(stmt))
            self._cfg_connect(current, term, logical=logical, lineno=_lineno(stmt))
            return None
        if isinstance(stmt, ast.Raise):
            term = self._new_cfg(logical, _lineno(stmt))
            self._cfg_connect(current, term, logical=logical, lineno=_lineno(stmt))
            name = _expr_name(stmt.exc)
            if name:
                self.raise_specs.append(_RaiseSpec(logical, self._resolve_alias(name), _lineno(stmt)))
            return None
        if isinstance(stmt, ast.Break):
            self._cfg_connect(current, break_target, logical=logical, lineno=_lineno(stmt))
            return None
        if isinstance(stmt, ast.Continue):
            self._cfg_connect(
                current, continue_target, logical=logical, lineno=_lineno(stmt), cycle=True
            )
            return None
        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            inner = self._new_cfg(logical, _lineno(stmt))
            self._cfg_connect(current, inner, logical=logical, lineno=_lineno(stmt))
            return self._cfg_stmts(stmt.body, inner, logical, break_target, continue_target)
        if isinstance(stmt, ast.Match):
            join = self._new_cfg(logical, _lineno(stmt))
            for case in stmt.cases:
                case_b = self._new_cfg(logical, _lineno(case.pattern) if hasattr(case, "pattern") else _lineno(stmt))
                self._cfg_connect(
                    current,
                    case_b,
                    ProgramGraphEdgeKind.CFG_BRANCH.value,
                    logical=logical,
                    lineno=_lineno(stmt),
                )
                case_end = self._cfg_stmts(case.body, case_b, logical, break_target, continue_target)
                self._cfg_connect(case_end, join, logical=logical, lineno=_lineno(stmt))
            return join
        return current

    def _function_dataflow(
        self,
        stmt: ast.FunctionDef | ast.AsyncFunctionDef,
        fn: ProgramGraphNode,
        logical: str,
    ) -> None:
        defs: dict[str, list[ProgramGraphNode]] = defaultdict(list)
        for name in _parameter_names(stmt):
            node = self.node(
                ProgramGraphNodeKind.DATA_FLOW.value,
                f"{logical}#dflow:{name}:param",
                projection="data_flow",
                lineno=_lineno(stmt),
                extra={"name": name},
            )
            defs[name].append(node)
            self.edge(ProgramGraphEdgeKind.CONTAINS.value, fn, node, projection="data_flow")
            self.edge(ProgramGraphEdgeKind.READS_STATE.value, fn, node, projection="data_flow")
        for child in _own_nodes(stmt.body):
            if isinstance(child, ast.Assign):
                for name in _store_names(child.targets[0] if child.targets else None):
                    ordinal = self._dflow_ordinals[f"{logical}:{name}"]
                    self._dflow_ordinals[f"{logical}:{name}"] += 1
                    node = self.node(
                        ProgramGraphNodeKind.DATA_FLOW.value,
                        f"{logical}#dflow:{name}:{ordinal}",
                        projection="data_flow",
                        lineno=_lineno(child),
                        ordinal=ordinal,
                        extra={"name": name},
                    )
                    for previous in defs[name]:
                        self.edge(
                            ProgramGraphEdgeKind.DATA_FLOW.value,
                            previous,
                            node,
                            projection="data_flow",
                            lineno=_lineno(child),
                        )
                    defs[name].append(node)
                    self.edge(ProgramGraphEdgeKind.CONTAINS.value, fn, node, projection="data_flow")
                    self.edge(ProgramGraphEdgeKind.WRITES_STATE.value, fn, node, projection="data_flow")
            elif isinstance(child, ast.AugAssign):
                for name in _store_names(child.target):
                    ordinal = self._dflow_ordinals[f"{logical}:{name}"]
                    self._dflow_ordinals[f"{logical}:{name}"] += 1
                    node = self.node(
                        ProgramGraphNodeKind.DATA_FLOW.value,
                        f"{logical}#dflow:{name}:{ordinal}",
                        projection="data_flow",
                        lineno=_lineno(child),
                        ordinal=ordinal,
                        extra={"name": name},
                    )
                    for previous in defs[name]:
                        self.edge(
                            ProgramGraphEdgeKind.DATA_FLOW.value,
                            previous,
                            node,
                            projection="data_flow",
                            lineno=_lineno(child),
                        )
                    defs[name].append(node)
                    self.edge(ProgramGraphEdgeKind.WRITES_STATE.value, fn, node, projection="data_flow")
            elif isinstance(child, ast.AnnAssign):
                for name in _store_names(child.target):
                    ordinal = self._dflow_ordinals[f"{logical}:{name}"]
                    self._dflow_ordinals[f"{logical}:{name}"] += 1
                    node = self.node(
                        ProgramGraphNodeKind.DATA_FLOW.value,
                        f"{logical}#dflow:{name}:{ordinal}",
                        projection="data_flow",
                        lineno=_lineno(child),
                        ordinal=ordinal,
                        extra={"name": name},
                    )
                    for previous in defs[name]:
                        self.edge(
                            ProgramGraphEdgeKind.DATA_FLOW.value,
                            previous,
                            node,
                            projection="data_flow",
                            lineno=_lineno(child),
                        )
                    defs[name].append(node)
                    self.edge(ProgramGraphEdgeKind.WRITES_STATE.value, fn, node, projection="data_flow")
            elif isinstance(child, ast.Global):
                for name in child.names:
                    self.incomplete.add("data_flow")
                    self.unavailable.add("data_flow")
            elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                ordinal = self._dflow_ordinals[f"{logical}:{child.id}:use"]
                self._dflow_ordinals[f"{logical}:{child.id}:use"] += 1
                use = self.node(
                    ProgramGraphNodeKind.DATA_FLOW.value,
                    f"{logical}#dflow:{child.id}:use:{ordinal}",
                    projection="data_flow",
                    lineno=_lineno(child),
                    ordinal=ordinal,
                    extra={"name": child.id},
                )
                self.edge(ProgramGraphEdgeKind.CONTAINS.value, fn, use, projection="data_flow")
                self.edge(
                    ProgramGraphEdgeKind.READS_STATE.value,
                    fn,
                    use,
                    projection="data_flow",
                    lineno=_lineno(child),
                )
                for defn in defs.get(child.id, ()):
                    self.edge(
                        ProgramGraphEdgeKind.DATA_FLOW.value,
                        defn,
                        use,
                        projection="data_flow",
                        lineno=_lineno(child),
                    )

    def _resolve_alias(self, name: str) -> str:
        if not name:
            return name
        root, dot, rest = name.partition(".")
        mapped = self._aliases.get(root, root)
        return mapped + (dot + rest if dot else "")

    def _function_effects_and_calls(
        self,
        stmt: ast.FunctionDef | ast.AsyncFunctionDef,
        fn: ProgramGraphNode,
        logical: str,
        *,
        is_test: bool,
    ) -> None:
        for child in _own_nodes(stmt.body):
            if not isinstance(child, ast.Call):
                continue
            raw = _expr_name(child.func)
            name = self._resolve_alias(raw)
            ordinal = self._call_ordinals[logical]
            self._call_ordinals[logical] += 1
            reasons = _call_reasons(name)
            effect = _is_effect_call(name)
            if name == "type" and len(child.args) < 3:
                reasons = tuple(r for r in reasons if r != DynamicFrontierReason.DYNAMIC_DISPATCH.value)
            self.call_specs.append(
                _CallSpec(
                    caller_logical_name=logical,
                    callee_name=name or "<unknown>",
                    ordinal=ordinal,
                    lineno=_lineno(child),
                    col=_col(child),
                    reasons=reasons,
                    effect=effect,
                )
            )
            if is_test and name:
                self.test_targets.append(_TestTargetSpec(logical, name))
            if reasons:
                self.frontier_reasons.update(reasons)
                self.unavailable.update(reasons)
                self.incomplete.add("call")
                if DynamicFrontierReason.EVAL.value in reasons:
                    self.incomplete.update(("cfg", "data_flow", "effect"))
                if DynamicFrontierReason.EXEC.value in reasons:
                    self.incomplete.update(("cfg", "data_flow", "effect", "import"))
                if DynamicFrontierReason.NATIVE_CALL.value in reasons:
                    self.incomplete.add("effect")
            if effect:
                effect_node = self.node(
                    ProgramGraphNodeKind.EFFECT.value,
                    f"{logical}#effect:{ordinal}",
                    projection="effect",
                    lineno=_lineno(child),
                    ordinal=ordinal,
                    extra={"callee": name[:128]},
                )
                self.edge(
                    ProgramGraphEdgeKind.EFFECT_OF.value,
                    fn,
                    effect_node,
                    projection="effect",
                    lineno=_lineno(child),
                )
                self.incomplete.add("effect")
                self.unavailable.add("effect_analysis")
            if isinstance(child.func, ast.Attribute) and not isinstance(child.func.value, ast.Name):
                self.frontier_reasons.add(DynamicFrontierReason.DYNAMIC_DISPATCH.value)
                self.unavailable.add("dynamic_dispatch")
                self.incomplete.add("call")


def _dedupe_edges(edges: Sequence[ProgramGraphEdge]) -> list[ProgramGraphEdge]:
    unique: dict[str, ProgramGraphEdge] = {}
    for edge in edges:
        unique[edge.program_graph_edge_cid] = edge
    return [unique[cid] for cid in sorted(unique)]


def _dedupe_nodes(nodes: Sequence[ProgramGraphNode]) -> list[ProgramGraphNode]:
    unique: dict[str, ProgramGraphNode] = {}
    for node in nodes:
        unique[node.program_graph_node_cid] = node
    return [unique[cid] for cid in sorted(unique)]


def _mark_logical_cycles(edges: Sequence[ProgramGraphEdge]) -> list[ProgramGraphEdge]:
    current = _dedupe_edges(edges)
    guard = 0
    while guard < 10_000:
        guard += 1
        by_cid = {edge.program_graph_edge_cid: edge for edge in current}
        unmarked = None
        for cycle in directed_logical_cycles(current):
            if cycle and not any(by_cid[cid].logical_cycle for cid in cycle):
                unmarked = max(cycle)
                break
        if unmarked is None:
            return current
        victim = by_cid[unmarked]
        replacement = ProgramGraphEdge(
            edge_kind=victim.edge_kind,
            source_node_cid=victim.source_node_cid,
            target_node_cid=victim.target_node_cid,
            language=victim.language,
            environment_binding_cid=victim.environment_binding_cid,
            resolution_status=victim.resolution_status,
            logical_cycle=True,
            unavailable_dimensions=victim.unavailable_dimensions,
            metadata=dict(victim.metadata),
        )
        current = [
            replacement if edge.program_graph_edge_cid == unmarked else edge for edge in current
        ]
        current = _dedupe_edges(current)
    raise ProgramGraphBuildError("logical-cycle marking did not converge")


def _package_node(name: str, sealed_binding_cid: str) -> ProgramGraphNode:
    source_cid = cid_for_bytes(PACKAGE_PROFILE_PREFIX + name.encode("utf-8"))
    return _node(
        kind=ProgramGraphNodeKind.PACKAGE.value,
        logical_name=name,
        source_cid=source_cid,
        sealed_binding_cid=sealed_binding_cid,
        path=f"package:{name}",
        projection="symbol",
        declaration_cid=_declaration_cid(
            path=f"package:{name}", kind="package", name=name, lineno=1, col=0
        ),
    )


def _builtin_function(name: str, sealed_binding_cid: str) -> tuple[ProgramGraphNode, FunctionSymbolRecord]:
    source_cid = cid_for_bytes(BUILTINS_PROFILE_BYTES)
    logical = f"builtins.{name}"
    declaration = _declaration_cid(
        path="builtins.py", kind="function", name=logical, lineno=1, col=0
    )
    record = FunctionSymbolRecord(
        language="python",
        logical_name=logical,
        source_cid=source_cid,
        declaration_cid=declaration,
        parameter_names=(),
        return_annotation="",
        unavailable_dimensions=("native_call",) if name in {"open"} else (),
    )
    node = _node(
        kind=ProgramGraphNodeKind.FUNCTION.value,
        logical_name=logical,
        source_cid=source_cid,
        sealed_binding_cid=sealed_binding_cid,
        path="builtins.py",
        projection="symbol",
        declaration_cid=declaration,
        record_cid=record.function_symbol_record_cid,
        unavailable=("native_call",) if name in {"open"} else (),
    )
    return node, record


def _lookup_name(
    name: str,
    *,
    functions: Mapping[str, ProgramGraphNode],
    classes: Mapping[str, ProgramGraphNode],
    exports: Mapping[str, Mapping[str, ProgramGraphNode]],
    builtins: Mapping[str, ProgramGraphNode],
    module_nodes: Mapping[str, ProgramGraphNode],
    prefer_module: str | None = None,
) -> ProgramGraphNode | None:
    if not name:
        return None
    if name in functions:
        return functions[name]
    if name in classes:
        return classes[name]
    if name in module_nodes:
        return module_nodes[name]
    simple = _simple_name(name)
    if prefer_module:
        local = exports.get(prefer_module, {})
        if name in local:
            return local[name]
        if simple in local:
            return local[simple]
        qualified = f"{prefer_module}.{simple}"
        if qualified in functions:
            return functions[qualified]
        if qualified in classes:
            return classes[qualified]
    if name in PYTHON_BUILTINS or simple in PYTHON_BUILTINS:
        return builtins.get(simple) or builtins.get(name)
    if "." in name:
        module, _, tail = name.rpartition(".")
        exported = exports.get(module, {})
        if name in exported:
            return exported[name]
        if tail in exported:
            return exported[tail]
        qualified = name
        if qualified in functions:
            return functions[qualified]
        if qualified in classes:
            return classes[qualified]
    return None


def _strongly_connected(adjacency: Mapping[str, set[str]]) -> list[set[str]]:
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
        for nxt in sorted(adjacency.get(node, ())):
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

    for node in sorted(adjacency):
        if node not in indices:
            strongconnect(node)
    return result


def _coverage_for(
    *,
    nodes: Sequence[ProgramGraphNode],
    edges: Sequence[ProgramGraphEdge],
    module_graphs: Mapping[str, ModuleGraph],
    frontier_reasons: Sequence[str],
    unavailable: Sequence[str],
) -> ProgramGraphCoverageReceipt:
    node_counts: dict[str, int] = defaultdict(int)
    edge_counts: dict[str, int] = defaultdict(int)
    for node in nodes:
        node_counts[str(node.node_kind)] += 1
    for edge in edges:
        edge_counts[str(edge.edge_kind)] += 1
    incomplete: set[str] = set()
    for graph in module_graphs.values():
        incomplete.update(graph.incomplete_projections)
        if graph.parse_error:
            incomplete.update(PROJECTION_NAMES)
    if any(kind == ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value for kind in node_counts):
        incomplete.update(("call", "import"))
    if "type_inference" in unavailable:
        incomplete.add("type")
    if "effect_analysis" in unavailable:
        incomplete.add("effect")
    if "star_import" in unavailable:
        incomplete.add("import")
    if "async" in unavailable:
        incomplete.update(("cfg", "call"))
    if DynamicFrontierReason.EVAL.value in frontier_reasons or DynamicFrontierReason.EXEC.value in frontier_reasons:
        incomplete.update(("call", "cfg", "data_flow", "effect"))
    if DynamicFrontierReason.REFLECTION.value in frontier_reasons:
        incomplete.add("call")
    if DynamicFrontierReason.NATIVE_CALL.value in frontier_reasons:
        incomplete.update(("call", "effect"))
    if DynamicFrontierReason.PLUGIN.value in frontier_reasons:
        incomplete.update(("import", "call"))
    if "test" not in {str(node.node_kind) for node in nodes}:
        # Absence of tests is complete coverage of the test projection (none present).
        pass
    complete = tuple(name for name in PROJECTION_NAMES if name not in incomplete)
    parse_errors = tuple(sorted(path for path, graph in module_graphs.items() if graph.parse_error))
    return ProgramGraphCoverageReceipt(
        projections=PROJECTION_NAMES,
        complete_projections=complete,
        incomplete_projections=tuple(name for name in PROJECTION_NAMES if name in incomplete),
        node_kind_counts=MappingProxyType(dict(sorted(node_counts.items()))),
        edge_kind_counts=MappingProxyType(dict(sorted(edge_counts.items()))),
        frontier_reasons=_sorted_unique(frontier_reasons),
        unavailable_dimensions=_sorted_unique(unavailable),
        source_count=len(module_graphs),
        parse_error_paths=parse_errors,
    )


def _link_module_graphs(
    module_graphs: Mapping[str, ModuleGraph],
    *,
    environment_binding_set_cid: str,
    sealed_binding_cid: str,
    retained_subroot_cids: Sequence[str] = (),
) -> ProgramGraphBuildReceipt:
    graphs = {path: module_graphs[path] for path in sorted(module_graphs)}
    nodes: list[ProgramGraphNode] = []
    edges: list[ProgramGraphEdge] = []
    function_symbols: list[FunctionSymbolRecord] = []
    contract_states: list[ContractStateRecord] = []
    module_nodes: dict[str, ProgramGraphNode] = {}
    function_nodes: dict[str, ProgramGraphNode] = {}
    class_nodes: dict[str, ProgramGraphNode] = {}
    fixture_nodes: dict[str, ProgramGraphNode] = {}
    test_nodes: dict[str, ProgramGraphNode] = {}
    exports: dict[str, dict[str, ProgramGraphNode]] = {}
    path_by_module: dict[str, str] = {}
    node_path: dict[str, str] = {}
    unavailable: set[str] = set()
    frontier_reasons: set[str] = set()

    package_nodes: dict[str, ProgramGraphNode] = {}
    for graph in graphs.values():
        for name in _package_names(graph.module_name):
            if name not in package_nodes:
                package_nodes[name] = _package_node(name, sealed_binding_cid)
    nodes.extend(package_nodes[name] for name in sorted(package_nodes))

    for path, graph in graphs.items():
        nodes.extend(graph.nodes)
        edges.extend(graph.edges)
        function_symbols.extend(graph.function_symbols)
        contract_states.extend(graph.contract_states)
        unavailable.update(graph.unavailable_dimensions)
        frontier_reasons.update(graph.frontier_reasons)
        path_by_module[graph.module_name] = path
        export_nodes: dict[str, ProgramGraphNode] = {}
        for node in graph.nodes:
            node_path[node.program_graph_node_cid] = path
            kind = str(node.node_kind)
            if kind == ProgramGraphNodeKind.MODULE.value:
                module_nodes[graph.module_name] = node
            elif kind == ProgramGraphNodeKind.FUNCTION.value:
                function_nodes[node.logical_name] = node
            elif kind == ProgramGraphNodeKind.CLASS.value:
                class_nodes[node.logical_name] = node
            elif kind == ProgramGraphNodeKind.FIXTURE.value:
                fixture_nodes[node.logical_name] = node
                fixture_nodes[_simple_name(node.logical_name)] = node
            elif kind == ProgramGraphNodeKind.TEST.value:
                test_nodes[node.logical_name] = node
            export_nodes[node.logical_name] = node
            export_nodes[_simple_name(node.logical_name)] = node
        exports[graph.module_name] = export_nodes
        parent = ".".join(graph.module_name.split(".")[:-1])
        if parent and parent in package_nodes and graph.module_name in module_nodes:
            edges.append(
                _edge(
                    kind=ProgramGraphEdgeKind.CONTAINS.value,
                    source=package_nodes[parent],
                    target=module_nodes[graph.module_name],
                    sealed_binding_cid=sealed_binding_cid,
                    path=path,
                    projection="symbol",
                )
            )
        if graph.module_name in package_nodes and graph.is_package and graph.module_name in module_nodes:
            edges.append(
                _edge(
                    kind=ProgramGraphEdgeKind.CONTAINS.value,
                    source=package_nodes[graph.module_name],
                    target=module_nodes[graph.module_name],
                    sealed_binding_cid=sealed_binding_cid,
                    path=path,
                    projection="symbol",
                )
            )

    referenced_builtins: set[str] = set()
    for graph in graphs.values():
        for spec in graph.call_specs:
            simple = _simple_name(spec.callee_name)
            if spec.callee_name in PYTHON_BUILTINS or simple in PYTHON_BUILTINS:
                referenced_builtins.add(simple)
        for spec in graph.raise_specs:
            simple = _simple_name(spec.exception_name)
            if spec.exception_name in PYTHON_BUILTINS or simple in PYTHON_BUILTINS:
                referenced_builtins.add(simple)
        for spec in graph.type_specs:
            simple = _simple_name(spec.annotation.split("[", 1)[0])
            if simple in PYTHON_BUILTINS:
                referenced_builtins.add(simple)

    builtin_nodes: dict[str, ProgramGraphNode] = {}
    builtin_source = cid_for_bytes(BUILTINS_PROFILE_BYTES)
    if referenced_builtins:
        builtin_module = _node(
            kind=ProgramGraphNodeKind.MODULE.value,
            logical_name="builtins",
            source_cid=builtin_source,
            sealed_binding_cid=sealed_binding_cid,
            path="builtins.py",
            projection="symbol",
            declaration_cid=_declaration_cid(
                path="builtins.py", kind="module", name="builtins", lineno=1, col=0
            ),
        )
        nodes.append(builtin_module)
        module_nodes["builtins"] = builtin_module
        for name in sorted(referenced_builtins):
            fn_node, record = _builtin_function(name, sealed_binding_cid)
            builtin_nodes[name] = fn_node
            function_nodes[fn_node.logical_name] = fn_node
            function_symbols.append(record)
            nodes.append(fn_node)
            edges.append(
                _edge(
                    kind=ProgramGraphEdgeKind.DECLARES.value,
                    source=builtin_module,
                    target=fn_node,
                    sealed_binding_cid=sealed_binding_cid,
                    path="builtins.py",
                    projection="symbol",
                )
            )

    callsites: list[CallsiteRecord] = []
    unresolved_nodes: list[ProgramGraphNode] = []
    unresolved_edges: list[ProgramGraphEdge] = []
    import_adj: dict[str, set[str]] = {name: set() for name in module_nodes}
    call_adj: dict[str, set[str]] = defaultdict(set)
    cross_file: set[tuple[str, str]] = set()
    unresolved_import_paths: set[str] = set()

    def note_cross(src_path: str, dst_node: ProgramGraphNode | None) -> None:
        if dst_node is None:
            return
        dst_path = node_path.get(dst_node.program_graph_node_cid)
        if dst_path and dst_path != src_path:
            cross_file.add((src_path, dst_path))

    for path, graph in graphs.items():
        module = module_nodes.get(graph.module_name)
        if module is None:
            continue
        for spec in graph.import_specs:
            target_module = spec.module_name
            binding = _node(
                kind=ProgramGraphNodeKind.IMPORT_BINDING.value,
                logical_name=f"{graph.module_name}#import:{spec.alias}:{spec.lineno}",
                source_cid=graph.source_cid,
                sealed_binding_cid=sealed_binding_cid,
                path=path,
                projection="import",
                lineno=spec.lineno,
                col=spec.col,
                extra={"alias": spec.alias[:128], "module": (target_module or "")[:128]},
                unavailable=(
                    ("star_import",) if spec.is_star else (("native_call",) if spec.native else ())
                ),
            )
            nodes.append(binding)
            node_path[binding.program_graph_node_cid] = path
            edges.append(
                _edge(
                    kind=ProgramGraphEdgeKind.DECLARES.value,
                    source=module,
                    target=binding,
                    sealed_binding_cid=sealed_binding_cid,
                    path=path,
                    projection="import",
                    lineno=spec.lineno,
                )
            )
            target = module_nodes.get(target_module)
            if target is not None:
                edges.append(
                    _edge(
                        kind=ProgramGraphEdgeKind.IMPORTS.value,
                        source=module,
                        target=target,
                        sealed_binding_cid=sealed_binding_cid,
                        path=path,
                        projection="import",
                        lineno=spec.lineno,
                    )
                )
                import_adj.setdefault(graph.module_name, set()).add(target_module)
                note_cross(path, target)
            else:
                unresolved_import_paths.add(path)
                unavailable.add("unknown_callee" if not spec.native else "native_call")
                frontier_reasons.add(
                    DynamicFrontierReason.NATIVE_CALL.value
                    if spec.native
                    else DynamicFrontierReason.UNKNOWN_CALLEE.value
                )
                if spec.is_star or spec.dynamic:
                    frontier_reasons.add(DynamicFrontierReason.INCOMPLETE_ANALYSIS.value)
                    unavailable.add("star_import")
                if spec.level > 0 and target is None:
                    frontier_reasons.add(DynamicFrontierReason.INCOMPLETE_ANALYSIS.value)
                dynamic = _node(
                    kind=ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value,
                    logical_name=f"{graph.module_name}#dynamic:import:{spec.alias}:{spec.lineno}",
                    source_cid=graph.source_cid,
                    sealed_binding_cid=sealed_binding_cid,
                    path=path,
                    projection="import",
                    lineno=spec.lineno,
                    unavailable=_sorted_unique(
                        [
                            *(["star_import"] if spec.is_star else []),
                            *(["native_call"] if spec.native else ["unknown_callee"]),
                        ]
                    ),
                )
                nodes.append(dynamic)
                node_path[dynamic.program_graph_node_cid] = path
                unresolved_nodes.append(dynamic)
                edge = _edge(
                    kind=ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value,
                    source=binding,
                    target=dynamic,
                    sealed_binding_cid=sealed_binding_cid,
                    path=path,
                    projection="import",
                    lineno=spec.lineno,
                    status=ResolutionStatus.UNRESOLVED.value,
                    unavailable=dynamic.unavailable_dimensions,
                )
                edges.append(edge)
                unresolved_edges.append(edge)
                edges.append(
                    _edge(
                        kind=ProgramGraphEdgeKind.IMPORTS.value,
                        source=module,
                        target=dynamic,
                        sealed_binding_cid=sealed_binding_cid,
                        path=path,
                        projection="import",
                        lineno=spec.lineno,
                        status=ResolutionStatus.UNRESOLVED.value,
                        unavailable=dynamic.unavailable_dimensions,
                    )
                )

        for spec in graph.call_specs:
            caller = (
                function_nodes.get(spec.caller_logical_name)
                or test_nodes.get(spec.caller_logical_name)
                or fixture_nodes.get(spec.caller_logical_name)
            )
            if caller is None:
                continue
            target = _lookup_name(
                spec.callee_name,
                functions=function_nodes,
                classes=class_nodes,
                exports=exports,
                builtins=builtin_nodes,
                module_nodes=module_nodes,
                prefer_module=graph.module_name,
            )
            dynamic_reasons = spec.reasons
            resolved = target is not None and not dynamic_reasons
            if target is not None and str(target.node_kind) == ProgramGraphNodeKind.FUNCTION.value:
                callee_decl = target.declaration_cid
            elif target is not None:
                callee_decl = target.declaration_cid
            else:
                callee_decl = None
            if dynamic_reasons or target is None:
                status = ResolutionStatus.UNRESOLVED.value
                unavailable_dims = dynamic_reasons or (DynamicFrontierReason.UNKNOWN_CALLEE.value,)
                if target is None:
                    frontier_reasons.add(DynamicFrontierReason.UNKNOWN_CALLEE.value)
                    unavailable.add("unknown_callee")
                frontier_reasons.update(dynamic_reasons)
                unavailable.update(dynamic_reasons)
                callee_decl = None
                resolved = False
            else:
                status = ResolutionStatus.DEFINITE.value
                unavailable_dims = ()
            record = CallsiteRecord(
                language="python",
                caller_logical_name=spec.caller_logical_name,
                callee_logical_name=spec.callee_name,
                source_cid=graph.source_cid,
                ordinal=spec.ordinal,
                resolution_status=status,
                callee_declaration_cid=callee_decl if status == ResolutionStatus.DEFINITE.value else None,
                unavailable_dimensions=unavailable_dims,
            )
            callsites.append(record)
            site = _node(
                kind=ProgramGraphNodeKind.CALLSITE.value,
                logical_name=f"{spec.caller_logical_name}#call:{spec.ordinal}",
                source_cid=graph.source_cid,
                sealed_binding_cid=sealed_binding_cid,
                path=path,
                projection="call",
                lineno=spec.lineno,
                col=spec.col,
                ordinal=spec.ordinal,
                record_cid=record.callsite_record_cid,
                unavailable=unavailable_dims,
            )
            nodes.append(site)
            node_path[site.program_graph_node_cid] = path
            edges.append(
                _edge(
                    kind=ProgramGraphEdgeKind.CALLS.value,
                    source=caller,
                    target=site,
                    sealed_binding_cid=sealed_binding_cid,
                    path=path,
                    projection="call",
                    lineno=spec.lineno,
                    ordinal=spec.ordinal,
                    status=status,
                    unavailable=unavailable_dims,
                )
            )
            edges.append(
                _edge(
                    kind=ProgramGraphEdgeKind.SUCCESSOR.value,
                    source=caller,
                    target=site,
                    sealed_binding_cid=sealed_binding_cid,
                    path=path,
                    projection="call",
                    lineno=spec.lineno,
                    ordinal=spec.ordinal,
                    status=status,
                    unavailable=unavailable_dims,
                )
            )
            if resolved and target is not None:
                call_adj[spec.caller_logical_name].add(target.logical_name)
                note_cross(path, target)
            elif not resolved:
                dyn_target = _node(
                    kind=ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value,
                    logical_name=f"{spec.caller_logical_name}#dynamic:call:{spec.ordinal}",
                    source_cid=graph.source_cid,
                    sealed_binding_cid=sealed_binding_cid,
                    path=path,
                    projection="call",
                    lineno=spec.lineno,
                    ordinal=spec.ordinal,
                    unavailable=unavailable_dims,
                )
                nodes.append(dyn_target)
                node_path[dyn_target.program_graph_node_cid] = path
                unresolved_nodes.append(dyn_target)
                edge = _edge(
                    kind=ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value,
                    source=site,
                    target=dyn_target,
                    sealed_binding_cid=sealed_binding_cid,
                    path=path,
                    projection="call",
                    lineno=spec.lineno,
                    status=ResolutionStatus.UNRESOLVED.value,
                    unavailable=unavailable_dims,
                )
                edges.append(edge)
                unresolved_edges.append(edge)

        for spec in graph.inherit_specs:
            child = class_nodes.get(spec.child_logical_name)
            if child is None:
                continue
            base = _lookup_name(
                spec.base_name,
                functions=function_nodes,
                classes=class_nodes,
                exports=exports,
                builtins=builtin_nodes,
                module_nodes=module_nodes,
                prefer_module=graph.module_name,
            )
            kind = (
                ProgramGraphEdgeKind.IMPLEMENTS.value
                if spec.protocol
                else ProgramGraphEdgeKind.INHERITS.value
            )
            if base is not None:
                edges.append(
                    _edge(
                        kind=kind,
                        source=child,
                        target=base,
                        sealed_binding_cid=sealed_binding_cid,
                        path=path,
                        projection="symbol",
                        lineno=spec.lineno,
                    )
                )
                note_cross(path, base)
            else:
                unavailable.add("type_inference")
                frontier_reasons.add(DynamicFrontierReason.INCOMPLETE_ANALYSIS.value)
                dynamic = _node(
                    kind=ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value,
                    logical_name=f"{spec.child_logical_name}#dynamic:base:{spec.lineno}",
                    source_cid=graph.source_cid,
                    sealed_binding_cid=sealed_binding_cid,
                    path=path,
                    projection="symbol",
                    lineno=spec.lineno,
                    unavailable=("type_inference",),
                )
                nodes.append(dynamic)
                unresolved_nodes.append(dynamic)
                edge = _edge(
                    kind=ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value,
                    source=child,
                    target=dynamic,
                    sealed_binding_cid=sealed_binding_cid,
                    path=path,
                    projection="symbol",
                    lineno=spec.lineno,
                    status=ResolutionStatus.UNRESOLVED.value,
                    unavailable=("type_inference",),
                )
                edges.append(edge)
                unresolved_edges.append(edge)

        for spec in graph.type_specs:
            owner = (
                function_nodes.get(spec.owner_logical_name)
                or class_nodes.get(spec.owner_logical_name)
                or test_nodes.get(spec.owner_logical_name)
                or fixture_nodes.get(spec.owner_logical_name)
            )
            annotation = spec.annotation.split("[", 1)[0].strip()
            target = _lookup_name(
                annotation,
                functions=function_nodes,
                classes=class_nodes,
                exports=exports,
                builtins=builtin_nodes,
                module_nodes=module_nodes,
                prefer_module=graph.module_name,
            )
            binding = next(
                (node for node in graph.nodes if node.logical_name == spec.binding_logical_name),
                None,
            )
            if owner is not None and target is not None and binding is not None:
                edges.append(
                    _edge(
                        kind=ProgramGraphEdgeKind.TYPE_OF.value,
                        source=binding,
                        target=target,
                        sealed_binding_cid=sealed_binding_cid,
                        path=path,
                        projection="type",
                        lineno=spec.lineno,
                    )
                )
                note_cross(path, target)
            else:
                unavailable.add("type_inference")

        for spec in graph.raise_specs:
            owner = (
                function_nodes.get(spec.owner_logical_name)
                or test_nodes.get(spec.owner_logical_name)
            )
            if owner is None:
                continue
            target = _lookup_name(
                spec.exception_name,
                functions=function_nodes,
                classes=class_nodes,
                exports=exports,
                builtins=builtin_nodes,
                module_nodes=module_nodes,
                prefer_module=graph.module_name,
            )
            if target is not None:
                edges.append(
                    _edge(
                        kind=ProgramGraphEdgeKind.RAISES.value,
                        source=owner,
                        target=target,
                        sealed_binding_cid=sealed_binding_cid,
                        path=path,
                        projection="exception",
                        lineno=spec.lineno,
                    )
                )
                note_cross(path, target)

        for spec in graph.fixture_uses:
            test = test_nodes.get(spec.test_logical_name)
            fixture = fixture_nodes.get(spec.fixture_name) or fixture_nodes.get(
                f"{graph.module_name}.{spec.fixture_name}"
            )
            if test is None:
                continue
            if fixture is not None:
                edges.append(
                    _edge(
                        kind=ProgramGraphEdgeKind.USES_FIXTURE.value,
                        source=test,
                        target=fixture,
                        sealed_binding_cid=sealed_binding_cid,
                        path=path,
                        projection="test",
                    )
                )
                note_cross(path, fixture)
            else:
                unavailable.add("plugin")
                frontier_reasons.add(DynamicFrontierReason.PLUGIN.value)

        for spec in graph.test_targets:
            test = test_nodes.get(spec.test_logical_name)
            target = _lookup_name(
                spec.callee_name,
                functions=function_nodes,
                classes=class_nodes,
                exports=exports,
                builtins=builtin_nodes,
                module_nodes=module_nodes,
                prefer_module=graph.module_name,
            )
            if test is not None and target is not None:
                edges.append(
                    _edge(
                        kind=ProgramGraphEdgeKind.TESTED_BY.value,
                        source=target,
                        target=test,
                        sealed_binding_cid=sealed_binding_cid,
                        path=path,
                        projection="test",
                    )
                )
                note_cross(path, target)

    for component in _strongly_connected(import_adj):
        members = sorted(name for name in component if name in module_nodes)
        if len(members) < 2:
            continue
        for source_name in members:
            for target_name in members:
                if source_name == target_name:
                    continue
                if target_name not in import_adj.get(source_name, ()):
                    continue
                edges.append(
                    _edge(
                        kind=ProgramGraphEdgeKind.CYCLIC_IMPORT.value,
                        source=module_nodes[source_name],
                        target=module_nodes[target_name],
                        sealed_binding_cid=sealed_binding_cid,
                        path=path_by_module[source_name],
                        projection="import",
                        logical_cycle=True,
                    )
                )

    for component in _strongly_connected(call_adj):
        members = sorted(
            name
            for name in component
            if name in function_nodes or name in test_nodes or name in fixture_nodes
        )
        if not members:
            continue
        if len(members) == 1 and members[0] not in call_adj.get(members[0], ()):
            continue
        lookup = {**function_nodes, **test_nodes, **fixture_nodes}
        for source_name in members:
            for target_name in members:
                if target_name not in call_adj.get(source_name, ()):
                    continue
                edges.append(
                    _edge(
                        kind=ProgramGraphEdgeKind.MUTUAL_RECURSION.value,
                        source=lookup[source_name],
                        target=lookup[target_name],
                        sealed_binding_cid=sealed_binding_cid,
                        path=node_path.get(lookup[source_name].program_graph_node_cid, "unknown"),
                        projection="call",
                        logical_cycle=True,
                    )
                )

    nodes = _dedupe_nodes(nodes)
    edges = _mark_logical_cycles(edges)
    node_by_cid = {node.program_graph_node_cid: node for node in nodes}
    edge_by_source: dict[str, list[ProgramGraphEdge]] = defaultdict(list)
    for edge in edges:
        edge_by_source[edge.source_node_cid].append(edge)

    successor_sets: list[StaticSuccessorSet] = []
    subject_kinds = {
        ProgramGraphNodeKind.FUNCTION.value,
        ProgramGraphNodeKind.TEST.value,
        ProgramGraphNodeKind.FIXTURE.value,
        ProgramGraphNodeKind.MODULE.value,
    }
    incomplete_successors = False
    for node in nodes:
        if str(node.node_kind) not in subject_kinds:
            continue
        outgoing = edge_by_source.get(node.program_graph_node_cid, ())
        successor_edges = [
            edge
            for edge in outgoing
            if str(edge.edge_kind)
            in {
                ProgramGraphEdgeKind.SUCCESSOR.value,
                ProgramGraphEdgeKind.CFG_NEXT.value,
                ProgramGraphEdgeKind.CFG_BRANCH.value,
                ProgramGraphEdgeKind.CALLS.value,
                ProgramGraphEdgeKind.EXCEPTION_EDGE.value,
                ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value,
            }
        ]
        successor_node_cids = _sorted_unique(edge.target_node_cid for edge in successor_edges)
        successor_edge_cids = _sorted_unique(edge.program_graph_edge_cid for edge in successor_edges)
        unresolved = [
            edge
            for edge in successor_edges
            if str(edge.edge_kind) == ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value
            or str(edge.resolution_status) in {ResolutionStatus.UNRESOLVED.value, ResolutionStatus.UNAVAILABLE.value}
        ]
        dims = _sorted_unique(
            dim for edge in unresolved for dim in edge.unavailable_dimensions
        )
        complete = not unresolved
        if not complete:
            incomplete_successors = True
            if not dims:
                dims = ("incomplete_analysis",)
        successor_sets.append(
            StaticSuccessorSet(
                language="python",
                subject_node_cid=node.program_graph_node_cid,
                successor_node_cids=successor_node_cids,
                successor_edge_cids=successor_edge_cids,
                complete=complete,
                unavailable_dimensions=() if complete else dims,
            )
        )

    proof_graphs: list[ProofObligationGraph] = []
    obligations = [
        node for node in nodes if str(node.node_kind) == ProgramGraphNodeKind.PROOF_OBLIGATION.value
    ]
    proved = [
        edge for edge in edges if str(edge.edge_kind) == ProgramGraphEdgeKind.PROVED_BY.value
    ]
    by_subject: dict[str, list[ProgramGraphNode]] = defaultdict(list)
    for node in obligations:
        owner = node.logical_name.split("#proof:", 1)[0]
        by_subject[owner].append(node)
    for owner in sorted(by_subject):
        group = sorted(by_subject[owner], key=lambda item: item.logical_name)
        root = group[0]
        related_edges = [
            edge
            for edge in proved
            if edge.target_node_cid in {item.program_graph_node_cid for item in group}
        ]
        proof_graphs.append(
            ProofObligationGraph(
                language="python",
                root_obligation_cid=root.program_graph_node_cid,
                obligation_node_cids=[item.program_graph_node_cid for item in group],
                obligation_edge_cids=[edge.program_graph_edge_cid for edge in related_edges],
                environment_binding_cid=sealed_binding_cid,
                unavailable_dimensions=("solver_unknown",),
            )
        )
        unavailable.add("solver_unknown")
        frontier_reasons.add(DynamicFrontierReason.SOLVER_UNKNOWN.value)

    unresolved_node_cids = _sorted_unique(
        node.program_graph_node_cid
        for node in nodes
        if str(node.node_kind) == ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value
    )
    unresolved_edge_cids = _sorted_unique(
        edge.program_graph_edge_cid
        for edge in edges
        if str(edge.edge_kind) == ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value
        or str(edge.resolution_status)
        in {ResolutionStatus.UNRESOLVED.value, ResolutionStatus.UNAVAILABLE.value}
    )
    frontiers: list[DynamicFrontierRecord] = []
    if unresolved_node_cids or unresolved_edge_cids or incomplete_successors or unavailable:
        if not frontier_reasons:
            frontier_reasons.add(DynamicFrontierReason.INCOMPLETE_ANALYSIS.value)
        if not unavailable:
            unavailable.add("incomplete_analysis")
        frontiers.append(
            DynamicFrontierRecord(
                language="python",
                unresolved_node_cids=unresolved_node_cids,
                unresolved_edge_cids=unresolved_edge_cids,
                reasons=_sorted_unique(frontier_reasons),
                unavailable_dimensions=_sorted_unique(unavailable),
            )
        )

    nodes = _dedupe_nodes(nodes)
    edges = _dedupe_edges(edges)
    callsites = tuple(sorted(callsites, key=lambda item: item.callsite_record_cid))
    function_symbols = tuple(
        sorted({item.function_symbol_record_cid: item for item in function_symbols}.values(),
               key=lambda item: item.function_symbol_record_cid)
    )
    contract_states = tuple(
        sorted({item.contract_state_record_cid: item for item in contract_states}.values(),
               key=lambda item: item.contract_state_record_cid)
    )
    successor_sets = tuple(
        sorted(successor_sets, key=lambda item: item.static_successor_set_cid)
    )
    proof_graphs = tuple(
        sorted(proof_graphs, key=lambda item: item.proof_obligation_graph_cid)
    )
    frontiers = tuple(
        sorted(frontiers, key=lambda item: item.dynamic_frontier_record_cid)
    )

    retained = tuple(
        cid for cid in sorted(set(retained_subroot_cids)) if cid in {node.program_graph_node_cid for node in nodes}
    )
    try:
        snapshot = assemble_program_graph_snapshot(
            language="python",
            nodes=nodes,
            edges=edges,
            environment_binding_set_cid=environment_binding_set_cid,
            sealed_binding_cid=sealed_binding_cid,
            callsites=callsites,
            function_symbols=function_symbols,
            contract_states=contract_states,
            proof_obligation_graphs=proof_graphs,
            successor_sets=successor_sets,
            frontiers=frontiers,
            retained_subroot_cids=retained,
            unavailable_dimensions=_sorted_unique(unavailable),
        )
    except ProgramGraphError as exc:
        raise ProgramGraphBuildError(str(exc)) from exc
    manifests = (
        ProgramGraphIndexManifest(
            snapshot_cid=snapshot.program_graph_snapshot_cid,
            index_kind=ProgramGraphIndexKind.ADJACENCY,
            schema_ids=(PROGRAM_GRAPH_NODE_SCHEMA, PROGRAM_GRAPH_EDGE_SCHEMA, PROGRAM_GRAPH_SNAPSHOT_SCHEMA),
        ),
        ProgramGraphIndexManifest(
            snapshot_cid=snapshot.program_graph_snapshot_cid,
            index_kind=ProgramGraphIndexKind.SUCCESSOR,
            schema_ids=(STATIC_SUCCESSOR_SET_SCHEMA, PROGRAM_GRAPH_SNAPSHOT_SCHEMA),
        ),
        ProgramGraphIndexManifest(
            snapshot_cid=snapshot.program_graph_snapshot_cid,
            index_kind=ProgramGraphIndexKind.FRONTIER,
            schema_ids=(DYNAMIC_FRONTIER_RECORD_SCHEMA, PROGRAM_GRAPH_SNAPSHOT_SCHEMA),
        ),
        ProgramGraphIndexManifest(
            snapshot_cid=snapshot.program_graph_snapshot_cid,
            index_kind=ProgramGraphIndexKind.STRUCTURAL,
            schema_ids=(
                CALLSITE_RECORD_SCHEMA,
                FUNCTION_SYMBOL_RECORD_SCHEMA,
                CONTRACT_STATE_RECORD_SCHEMA,
                PROOF_OBLIGATION_GRAPH_SCHEMA,
                PROGRAM_GRAPH_DELTA_SCHEMA,
            ),
        ),
    )
    for manifest in manifests:
        bind_index_manifest(manifest, snapshot)

    coverage = _coverage_for(
        nodes=nodes,
        edges=edges,
        module_graphs=graphs,
        frontier_reasons=tuple(frontier_reasons),
        unavailable=tuple(unavailable),
    )
    node_cids_by_path: dict[str, tuple[str, ...]] = {}
    for path, graph in graphs.items():
        cids = [node.program_graph_node_cid for node in nodes if node_path.get(node.program_graph_node_cid) == path]
        node_cids_by_path[path] = tuple(sorted(set(cids)))
    path_source_cids = {path: graphs[path].source_cid for path in sorted(graphs)}
    return ProgramGraphBuildReceipt(
        snapshot=snapshot,
        nodes=tuple(nodes),
        edges=tuple(edges),
        callsites=callsites,
        function_symbols=function_symbols,
        contract_states=contract_states,
        proof_obligation_graphs=proof_graphs,
        successor_sets=successor_sets,
        frontiers=frontiers,
        index_manifests=manifests,
        coverage=coverage,
        path_source_cids=MappingProxyType(path_source_cids),
        node_cids_by_path=MappingProxyType(node_cids_by_path),
        module_graphs=MappingProxyType(graphs),
        cross_file_deps=tuple(sorted(cross_file)),
        unresolved_import_paths=_sorted_unique(unresolved_import_paths),
        environment_binding_set_cid=environment_binding_set_cid,
        sealed_binding_cid=sealed_binding_cid,
    )


class ProgramGraphInvalidationPlanner:
    """Compute precise, conservative rebuild sets from a previous receipt."""

    INTERFACE: Final[str] = PROGRAM_GRAPH_INVALIDATION_PLANNER_INTERFACE

    def plan(
        self,
        previous: ProgramGraphBuildReceipt,
        current_sources: Mapping[str, str] | Sequence[ProgramSourceUnit] | Sequence[tuple[str, str]],
        *,
        environment_binding_set_cid: str,
        sealed_binding_cid: str,
    ) -> ProgramGraphInvalidationPlan:
        if not isinstance(previous, ProgramGraphBuildReceipt):
            raise ProgramGraphBuildError("previous must be a ProgramGraphBuildReceipt")
        sources = _normalize_sources(current_sources)
        reasons: list[str] = []
        environment_changed = (
            previous.environment_binding_set_cid != environment_binding_set_cid
            or previous.snapshot.environment_binding_set_cid != environment_binding_set_cid
        )
        sealed_changed = (
            previous.sealed_binding_cid != sealed_binding_cid
            or previous.snapshot.sealed_binding_cid != sealed_binding_cid
        )
        previous_paths = set(previous.path_source_cids)
        current_paths = set(sources)
        added = tuple(sorted(current_paths - previous_paths))
        removed = tuple(sorted(previous_paths - current_paths))
        changed = []
        for path in sorted(current_paths & previous_paths):
            if previous.path_source_cids[path] != _source_cid(sources[path]):
                changed.append(path)
        changed_paths = tuple(changed)
        if environment_changed:
            reasons.append(InvalidationReasonCode.ENVIRONMENT_BINDING_CHANGED.value)
        if sealed_changed:
            reasons.append(InvalidationReasonCode.SEALED_BINDING_CHANGED.value)
        for path in added:
            reasons.append(f"{InvalidationReasonCode.SOURCE_ADDED.value}:{path}")
        for path in removed:
            reasons.append(f"{InvalidationReasonCode.SOURCE_REMOVED.value}:{path}")
        for path in changed_paths:
            reasons.append(f"{InvalidationReasonCode.SOURCE_CHANGED.value}:{path}")

        full = environment_changed or sealed_changed
        if full:
            invalidated = tuple(sorted(current_paths | previous_paths))
            retained: tuple[str, ...] = ()
            retained_cids: tuple[str, ...] = ()
            invalidated_cids = tuple(sorted(previous.snapshot.node_cids))
            return ProgramGraphInvalidationPlan(
                changed_paths=changed_paths,
                added_paths=added,
                removed_paths=removed,
                invalidated_paths=invalidated,
                retained_paths=retained,
                retained_subroot_cids=retained_cids,
                invalidated_node_cids=invalidated_cids,
                full_rebuild_required=True,
                environment_changed=environment_changed or sealed_changed,
                reasons=_sorted_unique(reasons),
            )

        seeds = set(changed_paths) | set(removed) | set(added)
        reverse: dict[str, set[str]] = defaultdict(set)
        for src, dst in previous.cross_file_deps:
            reverse[dst].add(src)
        invalidated_set = set(seeds)
        queue = deque(sorted(seeds))
        while queue:
            item = queue.popleft()
            for dependent in sorted(reverse.get(item, ())):
                if dependent not in invalidated_set:
                    invalidated_set.add(dependent)
                    queue.append(dependent)
                    reasons.append(f"{InvalidationReasonCode.CROSS_FILE_DEPENDENT.value}:{dependent}")
        module_set_changed = bool(added or removed)
        if module_set_changed:
            for path in previous.unresolved_import_paths:
                if path not in invalidated_set:
                    invalidated_set.add(path)
                    reasons.append(
                        f"{InvalidationReasonCode.UNRESOLVED_IMPORT_FRONTIER.value}:{path}"
                    )
        retained_set = (current_paths & previous_paths) - invalidated_set
        retained_cids: list[str] = []
        invalidated_cids: list[str] = []
        for path, cids in previous.node_cids_by_path.items():
            if path in retained_set:
                retained_cids.extend(cids)
            else:
                invalidated_cids.extend(cids)
        return ProgramGraphInvalidationPlan(
            changed_paths=changed_paths,
            added_paths=added,
            removed_paths=removed,
            invalidated_paths=tuple(sorted(invalidated_set & current_paths)),
            retained_paths=tuple(sorted(retained_set)),
            retained_subroot_cids=_sorted_unique(retained_cids),
            invalidated_node_cids=_sorted_unique(invalidated_cids),
            full_rebuild_required=False,
            environment_changed=False,
            reasons=_sorted_unique(reasons),
        )


class ProgramGraphBuilder:
    """Deterministic Python static-graph builder with incremental linking."""

    INTERFACE: Final[str] = PROGRAM_GRAPH_BUILDER_INTERFACE
    VERSION: Final[str] = PROGRAM_GRAPH_BUILDER_VERSION

    def __init__(
        self,
        *,
        environment_binding_set_cid: str,
        sealed_binding_cid: str,
        language: str = "python",
    ) -> None:
        if language != "python":
            raise ProgramGraphBuildError(
                f"language {language!r} is typed unavailable in this profile"
            )
        self.environment_binding_set_cid = environment_binding_set_cid
        self.sealed_binding_cid = sealed_binding_cid
        self.planner = ProgramGraphInvalidationPlanner()

    def analyze_module(self, path: str, source_text: str) -> ModuleGraph:
        return _ModuleAnalyzer(path, source_text, self.sealed_binding_cid).analyze()

    def build(
        self,
        sources: Mapping[str, str] | Sequence[ProgramSourceUnit] | Sequence[tuple[str, str]],
        *,
        previous: ProgramGraphBuildReceipt | None = None,
    ) -> ProgramGraphBuildReceipt:
        normalized = _normalize_sources(sources)
        graphs: dict[str, ModuleGraph] = {}
        retained_cids: tuple[str, ...] = ()
        if previous is not None:
            plan = self.planner.plan(
                previous,
                normalized,
                environment_binding_set_cid=self.environment_binding_set_cid,
                sealed_binding_cid=self.sealed_binding_cid,
            )
            if not plan.full_rebuild_required:
                for path in plan.retained_paths:
                    graph = previous.module_graphs.get(path)
                    if graph is None or graph.source_cid != _source_cid(normalized[path]):
                        continue
                    graphs[path] = graph
                retained_cids = plan.retained_subroot_cids
        pending = [path for path in normalized if path not in graphs]
        for path in pending:
            graphs[path] = self.analyze_module(path, normalized[path])
        receipt = _link_module_graphs(
            graphs,
            environment_binding_set_cid=self.environment_binding_set_cid,
            sealed_binding_cid=self.sealed_binding_cid,
            retained_subroot_cids=retained_cids,
        )
        try:
            receipt.verify()
        except ProgramGraphError as exc:
            raise ProgramGraphBuildError(str(exc)) from exc
        return receipt


def build_program_graph(
    sources: Mapping[str, str] | Sequence[ProgramSourceUnit] | Sequence[tuple[str, str]],
    *,
    environment_binding_set_cid: str,
    sealed_binding_cid: str,
    previous: ProgramGraphBuildReceipt | None = None,
    language: str = "python",
) -> ProgramGraphBuildReceipt:
    """Construct a sealed current-tree static program graph.

    ``sources`` are explicit path/text units.  This function never walks the
    filesystem or imports the analyzed program.
    """

    builder = ProgramGraphBuilder(
        environment_binding_set_cid=environment_binding_set_cid,
        sealed_binding_cid=sealed_binding_cid,
        language=language,
    )
    return builder.build(sources, previous=previous)


def compute_program_graph_delta(
    previous: ProgramGraphSnapshot | ProgramGraphBuildReceipt,
    current: ProgramGraphSnapshot | ProgramGraphBuildReceipt,
) -> ProgramGraphDelta:
    """Return the exact node/edge delta, retaining unchanged subroot CIDs."""

    previous_snapshot = (
        previous.snapshot if isinstance(previous, ProgramGraphBuildReceipt) else previous
    )
    current_snapshot = (
        current.snapshot if isinstance(current, ProgramGraphBuildReceipt) else current
    )
    if not isinstance(previous_snapshot, ProgramGraphSnapshot) or not isinstance(
        current_snapshot, ProgramGraphSnapshot
    ):
        raise ProgramGraphBuildError("delta comparison requires program-graph snapshots")
    try:
        delta = delta_between_snapshots(previous_snapshot, current_snapshot)
        applied = apply_program_graph_delta(previous_snapshot, delta)
    except ProgramGraphError as exc:
        raise ProgramGraphBuildError(str(exc)) from exc
    if set(applied["node_cids"]) != set(current_snapshot.node_cids):
        raise ProgramGraphBuildError("delta application does not reconstruct current nodes")
    if set(applied["edge_cids"]) != set(current_snapshot.edge_cids):
        raise ProgramGraphBuildError("delta application does not reconstruct current edges")
    return delta


def plan_program_graph_invalidation(
    previous: ProgramGraphBuildReceipt,
    current_sources: Mapping[str, str] | Sequence[ProgramSourceUnit] | Sequence[tuple[str, str]],
    *,
    environment_binding_set_cid: str,
    sealed_binding_cid: str,
) -> ProgramGraphInvalidationPlan:
    """Plan dependency-aware invalidation without unsound omission."""

    planner = ProgramGraphInvalidationPlanner()
    return planner.plan(
        previous,
        current_sources,
        environment_binding_set_cid=environment_binding_set_cid,
        sealed_binding_cid=sealed_binding_cid,
    )


__all__ = [
    "ADMITTED_SOURCE_EXTENSIONS",
    "PROGRAM_GRAPH_BUILDER_INTERFACE",
    "PROGRAM_GRAPH_BUILDER_VERSION",
    "PROGRAM_GRAPH_BUILD_RECEIPT_INTERFACE",
    "PROGRAM_GRAPH_BUILD_RECEIPT_SCHEMA",
    "PROGRAM_GRAPH_COVERAGE_RECEIPT_SCHEMA",
    "PROGRAM_GRAPH_INVALIDATION_PLANNER_INTERFACE",
    "PROGRAM_GRAPH_INVALIDATION_PLAN_SCHEMA",
    "PROJECTION_NAMES",
    "InvalidationReasonCode",
    "ModuleGraph",
    "ProgramGraphBuildError",
    "ProgramGraphBuildReceipt",
    "ProgramGraphBuilder",
    "ProgramGraphCoverageReceipt",
    "ProgramGraphInvalidationPlan",
    "ProgramGraphInvalidationPlanner",
    "ProgramSourceUnit",
    "build_program_graph",
    "compute_program_graph_delta",
    "plan_program_graph_invalidation",
]
