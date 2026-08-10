"""Bounded AST impact, conflict, and dependency closures (DQK-033).

Provides revision-bound reverse-reference, call, import, effect, interface,
semantic-dependency, and conflict closure queries over the normalized
``asts`` catalog (DQK-031) and CodeImpactIndex-compatible evidence.

Used for task scopes, validation selection, and proof invalidation:

* every closure binds an exact source revision identity;
* depth, row, and wall-clock budgets are enforced;
* known impact fixtures agree with the existing code-evidence /
  CodeImpactIndex analyzers.

Importing this module is inert — no DuckDB, network, or filesystem I/O.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
    ASTCatalogProjection,
    DuckDBASTStore,
    DUCKDB_AST_STORE_SCHEMA_VERSION,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

DUCKDB_IMPACT_INTERFACE: Final = "DuckDBImpactQuery@1"
DUCKDB_IMPACT_SCHEMA_VERSION: Final = "duckdb-impact/v1"
IMPACT_CLOSURE_RESULT_SCHEMA: Final = "duckdb-impact-closure-result/v1"
IMPACT_GRAPH_SCHEMA: Final = "duckdb-impact-graph/v1"
IMPACT_REVISION_BINDING_SCHEMA: Final = "duckdb-impact-revision-binding/v1"
CODE_IMPACT_RESULT_SCHEMA: Final = (
    "ipfs_accelerate_py.agent_supervisor.code-impact-result@1"
)
CODE_IMPACT_INDEX_SCHEMA: Final = (
    "ipfs_accelerate_py.agent_supervisor.code-impact-index@1"
)

DEFAULT_MAX_DEPTH: Final = 16
DEFAULT_MAX_ROWS: Final = 10_000
DEFAULT_MAX_TIME_MS: Final = 5_000.0
HARD_MAX_DEPTH: Final = 256
HARD_MAX_ROWS: Final = 100_000
HARD_MAX_TIME_MS: Final = 60_000.0

# Closed vocabulary of impact edge / closure kinds (DQK-033).
IMPACT_CLOSURE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "reverse_reference",
        "call",
        "import",
        "effect",
        "interface",
        "semantic_dependency",
        "conflict",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DuckDBImpactError(ValueError):
    """Raised when an impact query input, budget, or binding is invalid."""


class ImpactBudgetExceeded(DuckDBImpactError):
    """Raised when a hard budget is exhausted under fail-closed mode."""


class ImpactRevisionError(DuckDBImpactError):
    """Raised when a closure cannot bind an exact source revision."""


# ---------------------------------------------------------------------------
# Enums and budgets
# ---------------------------------------------------------------------------


class ImpactClosureKind(StrEnum):
    """Closed set of impact / dependency / conflict closure families."""

    REVERSE_REFERENCE = "reverse_reference"
    CALL = "call"
    IMPORT = "import"
    EFFECT = "effect"
    INTERFACE = "interface"
    SEMANTIC_DEPENDENCY = "semantic_dependency"
    CONFLICT = "conflict"


class ImpactDirection(StrEnum):
    """Traversal direction over dependent→provider edges.

    * ``forward`` — seed → providers (dependencies of the seed)
    * ``reverse`` — seed ← dependents (impact-style consumers of the seed)
    * ``both`` — undirected union
    """

    FORWARD = "forward"
    REVERSE = "reverse"
    BOTH = "both"


@dataclass(frozen=True, slots=True)
class ImpactBudget:
    """Hard bounds for one impact / dependency closure walk.

    * ``max_depth`` — maximum edge hops from any seed
    * ``max_rows`` — maximum nodes + edges retained in the result
    * ``max_time_ms`` — wall-clock budget for the walk
    """

    max_depth: int = DEFAULT_MAX_DEPTH
    max_rows: int = DEFAULT_MAX_ROWS
    max_time_ms: float = DEFAULT_MAX_TIME_MS

    def __post_init__(self) -> None:
        depth = self.max_depth
        rows = self.max_rows
        millis = self.max_time_ms
        if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
            raise DuckDBImpactError("max_depth must be a non-negative integer")
        if isinstance(rows, bool) or not isinstance(rows, int) or rows < 1:
            raise DuckDBImpactError("max_rows must be a positive integer")
        if isinstance(millis, bool) or not isinstance(millis, (int, float)):
            raise DuckDBImpactError("max_time_ms must be a finite number")
        millis_f = float(millis)
        if millis_f <= 0.0:
            raise DuckDBImpactError("max_time_ms must be positive")
        object.__setattr__(self, "max_depth", min(int(depth), HARD_MAX_DEPTH))
        object.__setattr__(self, "max_rows", min(int(rows), HARD_MAX_ROWS))
        object.__setattr__(
            self, "max_time_ms", min(millis_f, HARD_MAX_TIME_MS)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_depth": self.max_depth,
            "max_rows": self.max_rows,
            "max_time_ms": self.max_time_ms,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "ImpactBudget":
        if value is None:
            return cls()
        return cls(
            max_depth=int(value.get("max_depth", DEFAULT_MAX_DEPTH)),
            max_rows=int(value.get("max_rows", DEFAULT_MAX_ROWS)),
            max_time_ms=float(value.get("max_time_ms", DEFAULT_MAX_TIME_MS)),
        )


# ---------------------------------------------------------------------------
# Graph rows
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ImpactNode:
    """One revision-bound impact node (symbol, path, module, subject, …)."""

    node_id: str
    kind: str
    label: str
    revision_id: str
    path: str = ""
    qualified_name: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "label": self.label,
            "revision_id": self.revision_id,
            "path": self.path,
            "qualified_name": self.qualified_name,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ImpactEdge:
    """Dependent → provider edge bound to an exact source revision.

    Orientation matches CodeImpactIndex: dependents list their providers.
    Reverse (impact) walks follow the inverse adjacency.
    """

    edge_id: str
    kind: str
    source: str  # dependent
    target: str  # provider
    revision_id: str
    path: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "kind": self.kind,
            "source": self.source,
            "target": self.target,
            "revision_id": self.revision_id,
            "path": self.path,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ImpactRevisionBinding:
    """Exact source-revision identity bound to every closure result."""

    revision_id: str
    repository_id: str
    revision: str
    repository_tree_cid: str | None = None
    schema_version: str = DUCKDB_AST_STORE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        revision_id = _text(self.revision_id, "revision_id")
        repository_id = _text(self.repository_id, "repository_id")
        revision = _text(self.revision, "revision")
        object.__setattr__(self, "revision_id", revision_id)
        object.__setattr__(self, "repository_id", repository_id)
        object.__setattr__(self, "revision", revision)
        tree = self.repository_tree_cid
        if tree is not None:
            tree_text = str(tree).strip()
            object.__setattr__(
                self, "repository_tree_cid", tree_text or None
            )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": IMPACT_REVISION_BINDING_SCHEMA,
            "revision_id": self.revision_id,
            "repository_id": self.repository_id,
            "revision": self.revision,
            "repository_tree_cid": self.repository_tree_cid,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class ImpactGraph:
    """Revision-bound impact edge set derived from the asts catalog."""

    binding: ImpactRevisionBinding
    nodes: tuple[ImpactNode, ...]
    edges: tuple[ImpactEdge, ...]
    symbol_paths: Mapping[str, str] = field(default_factory=dict)
    symbol_dependencies: Mapping[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    path_dependencies: Mapping[str, tuple[str, ...]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if type(self.binding) is not ImpactRevisionBinding:
            raise DuckDBImpactError("ImpactGraph requires an ImpactRevisionBinding")
        object.__setattr__(
            self,
            "nodes",
            tuple(sorted(self.nodes, key=lambda item: item.node_id)),
        )
        object.__setattr__(
            self,
            "edges",
            tuple(sorted(self.edges, key=lambda item: item.edge_id)),
        )
        object.__setattr__(
            self,
            "symbol_paths",
            dict(sorted({str(k): str(v) for k, v in dict(self.symbol_paths).items()}.items())),
        )
        object.__setattr__(
            self,
            "symbol_dependencies",
            {
                str(k): tuple(sorted({str(x) for x in v if str(x).strip()}))
                for k, v in sorted(dict(self.symbol_dependencies).items())
            },
        )
        object.__setattr__(
            self,
            "path_dependencies",
            {
                str(k): tuple(sorted({str(x) for x in v if str(x).strip()}))
                for k, v in sorted(dict(self.path_dependencies).items())
            },
        )
        # Fail closed: every edge/node must bind the same revision.
        for node in self.nodes:
            if node.revision_id != self.binding.revision_id:
                raise ImpactRevisionError(
                    "impact node revision does not match graph binding"
                )
        for edge in self.edges:
            if edge.revision_id != self.binding.revision_id:
                raise ImpactRevisionError(
                    "impact edge revision does not match graph binding"
                )
            if edge.kind not in IMPACT_CLOSURE_KINDS:
                raise DuckDBImpactError(f"unknown impact edge kind: {edge.kind}")

    @property
    def revision_id(self) -> str:
        return self.binding.revision_id

    def edges_of_kind(self, kind: str | ImpactClosureKind) -> tuple[ImpactEdge, ...]:
        key = str(kind)
        if key not in IMPACT_CLOSURE_KINDS:
            raise DuckDBImpactError(f"unknown impact closure kind: {key}")
        return tuple(edge for edge in self.edges if edge.kind == key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": IMPACT_GRAPH_SCHEMA,
            "interface": DUCKDB_IMPACT_INTERFACE,
            "store_schema_version": DUCKDB_IMPACT_SCHEMA_VERSION,
            "binding": self.binding.to_dict(),
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "nodes": [item.to_dict() for item in self.nodes],
            "edges": [item.to_dict() for item in self.edges],
            "symbol_paths": dict(self.symbol_paths),
            "symbol_dependencies": {
                key: list(value) for key, value in self.symbol_dependencies.items()
            },
            "path_dependencies": {
                key: list(value) for key, value in self.path_dependencies.items()
            },
        }


@dataclass(frozen=True, slots=True)
class ImpactClosureResult:
    """Bounded reverse / forward / both closure over one edge family."""

    kind: str
    direction: str
    binding: ImpactRevisionBinding
    seeds: tuple[str, ...]
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    paths: Mapping[str, tuple[str, ...]]
    depths: Mapping[str, int]
    budget: ImpactBudget
    truncated: bool = False
    truncation_reasons: tuple[str, ...] = ()
    elapsed_ms: float = 0.0
    rows_used: int = 0

    def __post_init__(self) -> None:
        if self.kind not in IMPACT_CLOSURE_KINDS:
            raise DuckDBImpactError(f"unknown impact closure kind: {self.kind}")
        if self.direction not in {item.value for item in ImpactDirection}:
            raise DuckDBImpactError(f"invalid impact direction: {self.direction}")
        if type(self.binding) is not ImpactRevisionBinding:
            raise ImpactRevisionError("closure result requires an exact revision binding")
        object.__setattr__(self, "seeds", tuple(sorted({_text(s, "seed") for s in self.seeds})))
        object.__setattr__(self, "node_ids", tuple(sorted(set(self.node_ids))))
        object.__setattr__(self, "edge_ids", tuple(sorted(set(self.edge_ids))))
        object.__setattr__(
            self,
            "paths",
            {
                str(key): tuple(str(item) for item in value)
                for key, value in sorted(dict(self.paths).items())
            },
        )
        object.__setattr__(
            self,
            "depths",
            {str(key): int(value) for key, value in sorted(dict(self.depths).items())},
        )
        object.__setattr__(
            self,
            "truncation_reasons",
            tuple(sorted({str(item) for item in self.truncation_reasons if str(item)})),
        )

    @property
    def revision_id(self) -> str:
        return self.binding.revision_id

    @property
    def node_count(self) -> int:
        return len(self.node_ids)

    @property
    def edge_count(self) -> int:
        return len(self.edge_ids)

    @property
    def complete(self) -> bool:
        return not self.truncated

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": IMPACT_CLOSURE_RESULT_SCHEMA,
            "interface": DUCKDB_IMPACT_INTERFACE,
            "store_schema_version": DUCKDB_IMPACT_SCHEMA_VERSION,
            "kind": self.kind,
            "direction": self.direction,
            "binding": self.binding.to_dict(),
            "revision_id": self.revision_id,
            "seeds": list(self.seeds),
            "node_ids": list(self.node_ids),
            "node_count": self.node_count,
            "edge_ids": list(self.edge_ids),
            "edge_count": self.edge_count,
            "paths": {key: list(value) for key, value in self.paths.items()},
            "depths": dict(self.depths),
            "budget": self.budget.to_dict(),
            "truncated": self.truncated,
            "truncation_reasons": list(self.truncation_reasons),
            "elapsed_ms": self.elapsed_ms,
            "rows_used": self.rows_used,
            "complete": self.complete,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise DuckDBImpactError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_path(value: object) -> str:
    text = _optional_text(value).replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def _module_from_path(path: str) -> str:
    normalized = _normalize_path(path)
    if not normalized:
        return ""
    if normalized.endswith(".py"):
        normalized = normalized[: -len(".py")]
    elif normalized.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")):
        for suffix in (".tsx", ".ts", ".jsx", ".mjs", ".cjs", ".js"):
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)]
                break
    return normalized.replace("/", ".")


def _symbol_names(symbol_qname: str, symbol_name: str) -> frozenset[str]:
    names = {symbol_name, symbol_qname}
    if "." in symbol_qname:
        names.add(symbol_qname.rsplit(".", 1)[-1])
    return frozenset(item for item in names if item)


def _match_symbol(
    token: str,
    *,
    by_name: Mapping[str, list[str]],
    by_qname: Mapping[str, str],
) -> tuple[str, ...]:
    """Resolve a reference/callee token to known qualified symbol names."""

    token = token.strip()
    if not token:
        return ()
    if token in by_qname:
        return (token,)
    # Unqualified or dotted suffix match.
    if token in by_name:
        return tuple(sorted(set(by_name[token])))
    if "." in token:
        short = token.rsplit(".", 1)[-1]
        if short in by_name:
            return tuple(sorted(set(by_name[short])))
        # Prefer exact trailing qualified match.
        matches = [
            qname
            for qname in by_qname
            if qname == token or qname.endswith("." + token)
        ]
        return tuple(sorted(set(matches)))
    return ()


def _scope_owner_symbol(
    scope_id: str,
    *,
    scope_to_owner: Mapping[str, str | None],
    symbol_by_id: Mapping[str, str],
) -> str | None:
    owner = scope_to_owner.get(scope_id)
    if owner:
        return symbol_by_id.get(owner) or owner
    # Fall back to the scope id itself when no owner symbol is recorded.
    return None


def _edge_id(
    kind: str, source: str, target: str, revision_id: str, detail: str = ""
) -> str:
    base = f"{kind}:{revision_id}:{source}->{target}"
    if detail:
        return f"{base}:{detail}"
    return base


def snapshot_store_projections(
    store: DuckDBASTStore,
) -> tuple[ASTCatalogProjection, ...]:
    """Snapshot catalog projections from an in-process AST store.

    The store is process-local; this helper is the single bridge used by
    impact queries so callers do not poke private fields.
    """

    if not isinstance(store, DuckDBASTStore):
        raise DuckDBImpactError("store must be a DuckDBASTStore")
    with store._lock:  # noqa: SLF001 — intentional same-package snapshot
        return tuple(store._by_blob.values())  # noqa: SLF001


def binding_from_projection(
    projection: ASTCatalogProjection,
) -> ImpactRevisionBinding:
    rev = projection.source_revision
    return ImpactRevisionBinding(
        revision_id=rev.revision_id,
        repository_id=rev.repository_id,
        revision=rev.revision,
        repository_tree_cid=rev.repository_tree_cid,
        schema_version=rev.schema_version,
    )


def binding_from_parts(
    *,
    repository_id: str,
    revision: str,
    repository_tree_cid: str | None = None,
    revision_id: str | None = None,
    schema_version: str = DUCKDB_AST_STORE_SCHEMA_VERSION,
) -> ImpactRevisionBinding:
    """Build a revision binding from explicit repository identity parts."""

    repo = _text(repository_id, "repository_id")
    rev = _text(revision, "revision")
    rid = revision_id or f"rev:{repo}:{rev}"
    return ImpactRevisionBinding(
        revision_id=_text(rid, "revision_id"),
        repository_id=repo,
        revision=rev,
        repository_tree_cid=repository_tree_cid,
        schema_version=schema_version,
    )


# ---------------------------------------------------------------------------
# Graph construction from AST catalog projections
# ---------------------------------------------------------------------------


def build_impact_graph(
    projections: Sequence[ASTCatalogProjection],
    *,
    revision_id: str | None = None,
    repository_id: str | None = None,
    revision: str | None = None,
) -> ImpactGraph:
    """Project catalog rows into a revision-bound impact graph.

    Exactly one source revision must be selected.  When ``revision_id`` is
    omitted the projections must all share one revision; mixed revisions fail
    closed.
    """

    if not projections:
        raise DuckDBImpactError("impact graph requires at least one projection")

    selected: list[ASTCatalogProjection] = []
    bindings: dict[str, ImpactRevisionBinding] = {}
    for projection in projections:
        if type(projection) is not ASTCatalogProjection:
            raise DuckDBImpactError(
                "build_impact_graph requires exact ASTCatalogProjection rows"
            )
        binding = binding_from_projection(projection)
        bindings[binding.revision_id] = binding
        if revision_id is not None and binding.revision_id != revision_id:
            continue
        if repository_id is not None and binding.repository_id != repository_id:
            continue
        if revision is not None and binding.revision != revision:
            continue
        selected.append(projection)

    if not selected:
        raise ImpactRevisionError(
            "no projections match the requested source revision"
        )

    revision_ids = {item.source_revision.revision_id for item in selected}
    if len(revision_ids) != 1:
        raise ImpactRevisionError(
            "impact closures require an exact single source revision; "
            f"got {sorted(revision_ids)}"
        )
    bound_id = next(iter(revision_ids))
    binding = bindings[bound_id]

    nodes: dict[str, ImpactNode] = {}
    edges: dict[str, ImpactEdge] = {}
    symbol_paths: dict[str, str] = {}
    symbol_dependencies: dict[str, set[str]] = defaultdict(set)
    path_dependencies: dict[str, set[str]] = defaultdict(set)

    # Indexes across the selected revision.
    by_qname: dict[str, str] = {}  # qname -> qname
    by_name: dict[str, list[str]] = defaultdict(list)
    symbol_by_id: dict[str, str] = {}  # symbol_id -> qname
    scope_to_owner: dict[str, str | None] = {}
    path_by_blob: dict[str, str] = {}
    module_by_path: dict[str, str] = {}
    effects_by_subject: dict[tuple[str, str], list[tuple[str, str, str]]] = (
        defaultdict(list)
    )
    # (kind, subject) -> list of (scope_owner_or_path, operation, path)
    interface_by_qname: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    # qname -> list of (signature_text, path, symbol_id)

    def add_node(
        node_id: str,
        *,
        kind: str,
        label: str,
        path: str = "",
        qualified_name: str = "",
        detail: str = "",
    ) -> None:
        if node_id in nodes:
            return
        nodes[node_id] = ImpactNode(
            node_id=node_id,
            kind=kind,
            label=label,
            revision_id=bound_id,
            path=path,
            qualified_name=qualified_name,
            detail=detail,
        )

    def add_edge(
        *,
        kind: str,
        source: str,
        target: str,
        path: str = "",
        detail: str = "",
    ) -> None:
        if not source or not target or source == target:
            return
        edge_id = _edge_id(kind, source, target, bound_id, detail)
        if edge_id in edges:
            return
        edges[edge_id] = ImpactEdge(
            edge_id=edge_id,
            kind=kind,
            source=source,
            target=target,
            revision_id=bound_id,
            path=path,
            detail=detail,
        )

    for projection in selected:
        path = _normalize_path(projection.source_file.path)
        path_by_blob[projection.blob_id] = path
        module_name = _module_from_path(path)
        module_by_path[path] = module_name
        add_node(path, kind="path", label=path, path=path)
        if module_name:
            add_node(
                f"module:{module_name}",
                kind="module",
                label=module_name,
                path=path,
                qualified_name=module_name,
            )

        for scope in projection.scopes:
            scope_to_owner[scope.scope_id] = scope.owner_symbol_id

        for symbol in projection.symbols:
            qname = symbol.qualified_name
            symbol_by_id[symbol.symbol_id] = qname
            by_qname[qname] = qname
            by_name[symbol.name].append(qname)
            symbol_paths[qname] = path
            add_node(
                qname,
                kind="symbol",
                label=symbol.name,
                path=path,
                qualified_name=qname,
                detail=symbol.kind,
            )

        for interface in projection.interfaces:
            qname = interface.qualified_name
            add_node(
                f"interface:{qname}",
                kind="interface",
                label=interface.name,
                path=path,
                qualified_name=qname,
                detail=interface.signature_text,
            )
            interface_by_qname[qname].append(
                (interface.signature_text, path, interface.symbol_id or "")
            )

        for effect in projection.effects:
            subject = effect.subject or effect.operation
            owner = _scope_owner_symbol(
                effect.scope_id,
                scope_to_owner=scope_to_owner,
                symbol_by_id=symbol_by_id,
            ) or path
            add_node(
                f"effect-subject:{subject}",
                kind="effect_subject",
                label=subject,
                path=path,
                detail=effect.kind,
            )
            effects_by_subject[(effect.kind, subject)].append(
                (owner, effect.operation, path)
            )

    # Second pass: edges that need the global symbol index.
    for projection in selected:
        path = path_by_blob[projection.blob_id]
        module_name = module_by_path.get(path, "")

        for scope in projection.scopes:
            scope_to_owner.setdefault(scope.scope_id, scope.owner_symbol_id)
        for symbol in projection.symbols:
            symbol_by_id.setdefault(symbol.symbol_id, symbol.qualified_name)

        for reference in projection.references:
            owner = _scope_owner_symbol(
                reference.scope_id,
                scope_to_owner=scope_to_owner,
                symbol_by_id=symbol_by_id,
            )
            dependent = owner or path
            targets = _match_symbol(
                reference.name, by_name=by_name, by_qname=by_qname
            )
            for target in targets:
                add_edge(
                    kind=ImpactClosureKind.REVERSE_REFERENCE.value,
                    source=dependent,
                    target=target,
                    path=path,
                    detail=reference.context,
                )
                if dependent in symbol_paths or dependent in by_qname:
                    symbol_dependencies[dependent].add(target)

        for call in projection.calls:
            owner = _scope_owner_symbol(
                call.scope_id,
                scope_to_owner=scope_to_owner,
                symbol_by_id=symbol_by_id,
            )
            dependent = owner or path
            targets = _match_symbol(
                call.callee_name, by_name=by_name, by_qname=by_qname
            )
            if not targets:
                # Keep unresolved callees as opaque provider tokens so call
                # closures still surface direct sites under budgets.
                unresolved = call.callee_name.strip()
                if unresolved:
                    add_node(
                        unresolved,
                        kind="unresolved_callee",
                        label=unresolved,
                        path=path,
                    )
                    targets = (unresolved,)
            for target in targets:
                add_edge(
                    kind=ImpactClosureKind.CALL.value,
                    source=dependent,
                    target=target,
                    path=path,
                    detail=call.kind,
                )
                if dependent in symbol_paths or dependent in by_qname:
                    symbol_dependencies[dependent].add(target)

        for item in projection.imports:
            # Importing file depends on the imported module identity.
            imported_module = item.module.strip()
            if not imported_module:
                continue
            provider_path = ""
            # Resolve relative/absolute module path against known modules.
            for candidate_path, candidate_module in module_by_path.items():
                if candidate_module == imported_module or candidate_module.endswith(
                    "." + imported_module
                ):
                    provider_path = candidate_path
                    break
            provider = provider_path or f"module:{imported_module}"
            add_node(
                provider,
                kind="module" if provider.startswith("module:") else "path",
                label=imported_module,
                path=provider_path,
                qualified_name=imported_module,
            )
            add_edge(
                kind=ImpactClosureKind.IMPORT.value,
                source=path,
                target=provider,
                path=path,
                detail=item.kind,
            )
            path_dependencies[path].add(provider if provider_path else provider)
            if item.imported_name:
                targets = _match_symbol(
                    item.imported_name
                    if "." in item.imported_name
                    else f"{imported_module}.{item.imported_name}",
                    by_name=by_name,
                    by_qname=by_qname,
                )
                owner = _scope_owner_symbol(
                    item.scope_id,
                    scope_to_owner=scope_to_owner,
                    symbol_by_id=symbol_by_id,
                )
                dependent = owner or path
                for target in targets:
                    add_edge(
                        kind=ImpactClosureKind.IMPORT.value,
                        source=dependent,
                        target=target,
                        path=path,
                        detail=f"from:{imported_module}",
                    )
                    if dependent in symbol_paths or dependent in by_qname:
                        symbol_dependencies[dependent].add(target)

        for interface in projection.interfaces:
            qname = interface.qualified_name
            # Callers / referencers of the interface surface form reverse edges.
            # Those are already captured by call/reference when names match; also
            # link the interface node to its defining symbol.
            if interface.symbol_id and interface.symbol_id in symbol_by_id:
                symbol_qname = symbol_by_id[interface.symbol_id]
                add_edge(
                    kind=ImpactClosureKind.INTERFACE.value,
                    source=f"interface:{qname}",
                    target=symbol_qname,
                    path=path,
                    detail="defines",
                )
            # Module export surface depends on the module path.
            if interface.kind == "module":
                add_edge(
                    kind=ImpactClosureKind.INTERFACE.value,
                    source=f"interface:{qname}",
                    target=path,
                    path=path,
                    detail="module-exports",
                )

        for effect in projection.effects:
            subject = effect.subject or effect.operation
            owner = _scope_owner_symbol(
                effect.scope_id,
                scope_to_owner=scope_to_owner,
                symbol_by_id=symbol_by_id,
            ) or path
            subject_node = f"effect-subject:{subject}"
            add_edge(
                kind=ImpactClosureKind.EFFECT.value,
                source=owner,
                target=subject_node,
                path=path,
                detail=f"{effect.kind}:{effect.operation}",
            )

    # Effect co-use edges: scopes/symbols that touch the same subject.
    for (kind, subject), owners in effects_by_subject.items():
        subject_node = f"effect-subject:{subject}"
        unique_owners = sorted({owner for owner, _op, _path in owners})
        for owner in unique_owners:
            add_edge(
                kind=ImpactClosureKind.EFFECT.value,
                source=owner,
                target=subject_node,
                detail=f"subject:{kind}",
            )
        # Pairwise conflict when operations disagree on the same subject.
        by_operation: dict[str, list[str]] = defaultdict(list)
        for owner, operation, _path in owners:
            by_operation[operation].append(owner)
        operations = sorted(by_operation)
        if len(operations) >= 2:
            for left_op, right_op in zip(operations, operations[1:]):
                for left in sorted(set(by_operation[left_op])):
                    for right in sorted(set(by_operation[right_op])):
                        if left == right:
                            continue
                        a, b = sorted((left, right))
                        add_edge(
                            kind=ImpactClosureKind.CONFLICT.value,
                            source=a,
                            target=b,
                            detail=f"effect:{subject}:{left_op}!={right_op}",
                        )

    # Interface signature conflicts for the same qualified name.
    for qname, rows in interface_by_qname.items():
        signatures = sorted({signature for signature, _path, _sid in rows})
        if len(signatures) >= 2:
            add_edge(
                kind=ImpactClosureKind.CONFLICT.value,
                source=f"interface:{qname}",
                target=qname if qname in nodes else f"interface:{qname}",
                detail=f"signature-mismatch:{len(signatures)}",
            )

    # Semantic dependency = union of call + import + reverse_reference edges.
    for edge in list(edges.values()):
        if edge.kind in {
            ImpactClosureKind.CALL.value,
            ImpactClosureKind.IMPORT.value,
            ImpactClosureKind.REVERSE_REFERENCE.value,
        }:
            add_edge(
                kind=ImpactClosureKind.SEMANTIC_DEPENDENCY.value,
                source=edge.source,
                target=edge.target,
                path=edge.path,
                detail=edge.kind,
            )

    return ImpactGraph(
        binding=binding,
        nodes=tuple(nodes.values()),
        edges=tuple(edges.values()),
        symbol_paths=symbol_paths,
        symbol_dependencies={
            key: tuple(sorted(value)) for key, value in symbol_dependencies.items()
        },
        path_dependencies={
            key: tuple(sorted(value)) for key, value in path_dependencies.items()
        },
    )


def build_impact_graph_from_store(
    store: DuckDBASTStore,
    *,
    revision_id: str | None = None,
    repository_id: str | None = None,
    revision: str | None = None,
) -> ImpactGraph:
    """Build a revision-bound impact graph from a DuckDBASTStore snapshot."""

    return build_impact_graph(
        snapshot_store_projections(store),
        revision_id=revision_id,
        repository_id=repository_id,
        revision=revision,
    )


# ---------------------------------------------------------------------------
# Bounded closure engine
# ---------------------------------------------------------------------------


def _adjacency(
    edges: Sequence[ImpactEdge],
) -> tuple[dict[str, list[ImpactEdge]], dict[str, list[ImpactEdge]]]:
    outgoing: dict[str, list[ImpactEdge]] = defaultdict(list)
    incoming: dict[str, list[ImpactEdge]] = defaultdict(list)
    for edge in edges:
        outgoing[edge.source].append(edge)
        incoming[edge.target].append(edge)
    return outgoing, incoming


def bounded_closure(
    *,
    kind: str | ImpactClosureKind,
    seeds: Iterable[str],
    edges: Sequence[ImpactEdge],
    binding: ImpactRevisionBinding,
    direction: str | ImpactDirection = ImpactDirection.REVERSE,
    budget: ImpactBudget | Mapping[str, Any] | None = None,
    fail_closed: bool = False,
) -> ImpactClosureResult:
    """Run a budgeted BFS closure over dependent→provider edges.

    Default direction is reverse (impact): changing a provider selects its
    dependents.  Budgets cap depth, total rows (nodes + edges), and wall time.
    """

    kind_key = str(kind)
    if kind_key not in IMPACT_CLOSURE_KINDS:
        raise DuckDBImpactError(f"unknown impact closure kind: {kind_key}")
    direction_key = str(direction)
    if direction_key not in {item.value for item in ImpactDirection}:
        raise DuckDBImpactError(f"invalid impact direction: {direction_key}")
    if type(binding) is not ImpactRevisionBinding:
        raise ImpactRevisionError("closure requires an exact ImpactRevisionBinding")
    bounds = (
        budget
        if isinstance(budget, ImpactBudget)
        else ImpactBudget.from_mapping(budget)
    )

    seed_set = tuple(sorted({_text(item, "seed") for item in seeds if _optional_text(item)}))
    if not seed_set:
        raise DuckDBImpactError("closure requires at least one seed")

    # Filter edges to the bound revision and requested kind (semantic already
    # materialised; others filter by exact kind).
    scoped = [
        edge
        for edge in edges
        if edge.revision_id == binding.revision_id and edge.kind == kind_key
    ]
    for edge in scoped:
        if edge.revision_id != binding.revision_id:
            raise ImpactRevisionError(
                "edge revision drifted from closure binding"
            )

    outgoing, incoming = _adjacency(scoped)
    started = time.monotonic()
    deadline = started + (bounds.max_time_ms / 1000.0)

    visited: set[str] = set(seed_set)
    paths: dict[str, tuple[str, ...]] = {seed: (seed,) for seed in seed_set}
    depths: dict[str, int] = {seed: 0 for seed in seed_set}
    included_edges: list[ImpactEdge] = []
    seen_edge_ids: set[str] = set()
    queue: deque[str] = deque(seed_set)
    truncated = False
    reasons: list[str] = []

    def rows_used() -> int:
        return len(visited) + len(seen_edge_ids)

    def budget_hit(reason: str) -> bool:
        nonlocal truncated
        truncated = True
        if reason not in reasons:
            reasons.append(reason)
        if fail_closed:
            raise ImpactBudgetExceeded(
                f"impact closure exceeded {reason} "
                f"(budget={bounds.to_dict()})"
            )
        return True

    while queue:
        if time.monotonic() >= deadline:
            budget_hit("time")
            break
        current = queue.popleft()
        if depths[current] >= bounds.max_depth:
            if depths[current] > bounds.max_depth:
                budget_hit("depth")
            continue

        neighbors: list[ImpactEdge] = []
        if direction_key in {
            ImpactDirection.FORWARD.value,
            ImpactDirection.BOTH.value,
        }:
            neighbors.extend(outgoing.get(current, ()))
        if direction_key in {
            ImpactDirection.REVERSE.value,
            ImpactDirection.BOTH.value,
        }:
            neighbors.extend(incoming.get(current, ()))

        for edge in neighbors:
            if time.monotonic() >= deadline:
                budget_hit("time")
                break
            if direction_key == ImpactDirection.FORWARD.value:
                nxt = edge.target
            elif direction_key == ImpactDirection.REVERSE.value:
                nxt = edge.source
            else:
                # both: walk whichever endpoint is not current
                nxt = edge.target if edge.source == current else edge.source

            if edge.edge_id not in seen_edge_ids:
                if rows_used() >= bounds.max_rows:
                    budget_hit("rows")
                    break
                seen_edge_ids.add(edge.edge_id)
                included_edges.append(edge)

            candidate = (*paths[current], nxt)
            previous = paths.get(nxt)
            depth = depths[current] + 1
            if depth > bounds.max_depth:
                budget_hit("depth")
                continue
            if previous is None:
                if rows_used() >= bounds.max_rows:
                    budget_hit("rows")
                    break
                visited.add(nxt)
                paths[nxt] = candidate
                depths[nxt] = depth
                queue.append(nxt)
            elif (len(candidate), candidate) < (len(previous), previous):
                paths[nxt] = candidate
                depths[nxt] = depth

        if truncated and fail_closed:
            break

    elapsed_ms = (time.monotonic() - started) * 1000.0
    return ImpactClosureResult(
        kind=kind_key,
        direction=direction_key,
        binding=binding,
        seeds=seed_set,
        node_ids=tuple(sorted(visited)),
        edge_ids=tuple(sorted(seen_edge_ids)),
        paths=paths,
        depths=depths,
        budget=bounds,
        truncated=truncated,
        truncation_reasons=tuple(reasons),
        elapsed_ms=elapsed_ms,
        rows_used=rows_used(),
    )


# ---------------------------------------------------------------------------
# Code-impact-index agreement (existing analyzers)
# ---------------------------------------------------------------------------


def _reverse_map(
    dependencies: Mapping[str, Sequence[str]],
) -> dict[str, tuple[str, ...]]:
    reverse: dict[str, set[str]] = {}
    for dependent, providers in dependencies.items():
        reverse.setdefault(str(dependent), set())
        for provider in providers:
            reverse.setdefault(str(provider), set()).add(str(dependent))
    return {key: tuple(sorted(value)) for key, value in sorted(reverse.items())}


def _closure_with_chains(
    roots: Iterable[str],
    reverse: Mapping[str, Sequence[str]],
    *,
    budget: ImpactBudget,
    fail_closed: bool,
    started: float,
) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]], bool, tuple[str, ...]]:
    normalized = tuple(sorted({str(item).strip() for item in roots if str(item).strip()}))
    chains: dict[str, tuple[str, ...]] = {root: (root,) for root in normalized}
    depths: dict[str, int] = {root: 0 for root in normalized}
    queue: deque[str] = deque(normalized)
    truncated = False
    reasons: list[str] = []
    deadline = started + (budget.max_time_ms / 1000.0)

    def hit(reason: str) -> None:
        nonlocal truncated
        truncated = True
        if reason not in reasons:
            reasons.append(reason)
        if fail_closed:
            raise ImpactBudgetExceeded(
                f"impact index closure exceeded {reason}"
            )

    while queue:
        if time.monotonic() >= deadline:
            hit("time")
            break
        current = queue.popleft()
        if depths[current] >= budget.max_depth:
            continue
        for dependent in reverse.get(current, ()):
            if time.monotonic() >= deadline:
                hit("time")
                break
            candidate = (*chains[current], dependent)
            existing = chains.get(dependent)
            depth = depths[current] + 1
            if depth > budget.max_depth:
                hit("depth")
                continue
            if existing is None:
                if len(chains) + 1 > budget.max_rows:
                    hit("rows")
                    break
                chains[dependent] = candidate
                depths[dependent] = depth
                queue.append(dependent)
            elif (len(candidate), candidate) < (len(existing), existing):
                chains[dependent] = candidate
                depths[dependent] = depth
    return tuple(sorted(chains)), chains, truncated, tuple(reasons)


def impact_from_code_impact_index(
    index: Mapping[str, Any],
    *,
    changed_symbols: Iterable[str] = (),
    changed_paths: Iterable[str] = (),
    budget: ImpactBudget | Mapping[str, Any] | None = None,
    fail_closed: bool = False,
    revision_id: str | None = None,
) -> dict[str, Any]:
    """Deterministic reverse dependency impact agreeing with existing analyzers.

    Algorithm mirrors
    ``ipfs_datasets_py.knowledge_graphs.adapters.code_evidence.impact_from_index``
    and ``CodeImpactIndex.impact`` (dependent→provider reverse walk), with
    explicit depth/row/time budgets and an exact revision binding.
    """

    bounds = (
        budget
        if isinstance(budget, ImpactBudget)
        else ImpactBudget.from_mapping(budget)
    )
    repository_tree_id = _optional_text(index.get("repository_tree_id"))
    index_id = _optional_text(index.get("index_id"))
    revision = _optional_text(index.get("revision"))
    # Exact revision identity is the source commit/tree; ``revision_id`` is the
    # catalog key and must not overwrite the human/git revision field.
    bound_revision = revision or repository_tree_id
    if not bound_revision:
        raise ImpactRevisionError(
            "code impact index requires revision or repository_tree_id"
        )
    bound_revision_id = (
        _text(revision_id, "revision_id")
        if revision_id
        else f"rev:impact-index:{bound_revision}"
    )

    symbol_paths = {
        str(k): _normalize_path(v)
        for k, v in dict(index.get("symbol_paths") or {}).items()
        if str(k).strip()
    }
    symbol_dependencies = {
        str(k): tuple(str(x) for x in v)
        for k, v in dict(index.get("symbol_dependencies") or {}).items()
    }
    path_dependencies = {
        _normalize_path(k): tuple(_normalize_path(x) for x in v)
        for k, v in dict(index.get("path_dependencies") or {}).items()
    }
    validation_targets = {
        str(k): tuple(str(x) for x in v)
        for k, v in dict(index.get("validation_targets") or {}).items()
    }

    explicit_symbols = {str(s).strip() for s in changed_symbols if str(s).strip()}
    explicit_paths = {
        _normalize_path(p) for p in changed_paths if str(p).strip()
    }
    inferred_symbols = {
        symbol for symbol, path in symbol_paths.items() if path in explicit_paths
    }
    known_changed_symbols = (explicit_symbols | inferred_symbols) & set(symbol_paths)
    uncovered_symbols = tuple(sorted(explicit_symbols - set(symbol_paths)))

    known_paths = set(symbol_paths.values())
    known_paths.update(path_dependencies)
    for deps in path_dependencies.values():
        known_paths.update(deps)
    uncovered_paths = tuple(sorted(explicit_paths - known_paths))

    started = time.monotonic()
    affected_symbols, symbol_chains, trunc_s, reasons_s = _closure_with_chains(
        known_changed_symbols,
        _reverse_map(symbol_dependencies),
        budget=bounds,
        fail_closed=fail_closed,
        started=started,
    )
    symbol_affected_paths = {
        symbol_paths[symbol]
        for symbol in affected_symbols
        if symbol in symbol_paths
    }
    path_roots = explicit_paths | symbol_affected_paths
    affected_paths, path_chains, trunc_p, reasons_p = _closure_with_chains(
        path_roots,
        _reverse_map(path_dependencies),
        budget=bounds,
        fail_closed=fail_closed,
        started=started,
    )

    impacted_targets = set(affected_symbols) | set(affected_paths)
    validation_reasons = {
        validation_id: tuple(sorted(impacted_targets.intersection(targets)))
        for validation_id, targets in validation_targets.items()
        if impacted_targets.intersection(targets)
    }
    chains = {key: list(value) for key, value in symbol_chains.items()}
    for target, chain in path_chains.items():
        chains.setdefault(target, list(chain))

    truncated = trunc_s or trunc_p
    reasons = tuple(sorted(set(reasons_s) | set(reasons_p)))
    elapsed_ms = (time.monotonic() - started) * 1000.0

    binding = ImpactRevisionBinding(
        revision_id=bound_revision_id,
        repository_id=_optional_text(index.get("repository_id")) or "impact-index",
        revision=bound_revision,
        repository_tree_cid=repository_tree_id or None,
        schema_version=DUCKDB_IMPACT_SCHEMA_VERSION,
    )

    return {
        "schema": CODE_IMPACT_RESULT_SCHEMA,
        "repository_tree_id": repository_tree_id,
        "index_id": index_id,
        "changed_symbols": sorted(explicit_symbols | inferred_symbols),
        "affected_symbols": list(affected_symbols),
        "changed_paths": sorted(explicit_paths),
        "affected_paths": list(affected_paths),
        "dependency_chains": {
            key: value for key, value in sorted(chains.items())
        },
        "required_validation_ids": sorted(validation_reasons),
        "validation_reasons": {
            key: list(value) for key, value in sorted(validation_reasons.items())
        },
        "uncovered_symbols": list(uncovered_symbols),
        "uncovered_paths": list(uncovered_paths),
        "uncovered_impact": bool(uncovered_symbols or uncovered_paths),
        # Extension fields retained for DuckDB impact consumers.
        "binding": binding.to_dict(),
        "revision_id": binding.revision_id,
        "revision": bound_revision,
        "budget": bounds.to_dict(),
        "truncated": truncated,
        "truncation_reasons": list(reasons),
        "elapsed_ms": elapsed_ms,
        "interface": DUCKDB_IMPACT_INTERFACE,
        "store_schema_version": DUCKDB_IMPACT_SCHEMA_VERSION,
    }


def known_impact_fixture_index(
    *,
    repository_tree_id: str = "tree-fixture",
    revision: str = "0" * 40,
) -> dict[str, Any]:
    """Return the canonical impact fixture used by existing analyzers.

    Matches the code-evidence corpus fixture (``pkg.mod.helper`` graph).
    """

    return {
        "schema": CODE_IMPACT_INDEX_SCHEMA,
        "repository_tree_id": repository_tree_id,
        "index_version": "code-impact-index-v1",
        "symbol_paths": {
            "pkg.mod.helper": "pkg/mod.py",
            "pkg.mod.caller": "pkg/mod.py",
            "pkg.other.use": "pkg/other.py",
        },
        "symbol_dependencies": {
            "pkg.mod.caller": ["pkg.mod.helper"],
            "pkg.other.use": ["pkg.mod.helper"],
        },
        "path_dependencies": {
            "pkg/other.py": ["pkg/mod.py"],
            "tests/test_mod.py": ["pkg/mod.py"],
        },
        "validation_targets": {
            "test_code_evidence": ["pkg.mod.helper", "pkg/mod.py"],
            "test_other": ["pkg.other.use", "pkg/other.py"],
        },
        "revision": revision,
    }


# ---------------------------------------------------------------------------
# Engine surface
# ---------------------------------------------------------------------------


class DuckDBImpactEngine:
    """Revision-bound impact / conflict / dependency query engine.

    Builds an :class:`ImpactGraph` from AST catalog projections (or an explicit
    CodeImpactIndex) and answers the seven DQK-033 closure families under
    depth/row/time budgets.
    """

    def __init__(
        self,
        *,
        store: DuckDBASTStore | None = None,
        graph: ImpactGraph | None = None,
        projections: Sequence[ASTCatalogProjection] | None = None,
        revision_id: str | None = None,
        repository_id: str | None = None,
        revision: str | None = None,
        default_budget: ImpactBudget | None = None,
    ) -> None:
        self._store = store
        self._default_budget = default_budget or ImpactBudget()
        self._graph = graph
        self._projections = tuple(projections) if projections is not None else None
        self._revision_id = revision_id
        self._repository_id = repository_id
        self._revision = revision

    @property
    def interface(self) -> str:
        return DUCKDB_IMPACT_INTERFACE

    @property
    def schema_version(self) -> str:
        return DUCKDB_IMPACT_SCHEMA_VERSION

    @property
    def default_budget(self) -> ImpactBudget:
        return self._default_budget

    def graph(self) -> ImpactGraph:
        if self._graph is not None:
            return self._graph
        if self._projections is not None:
            self._graph = build_impact_graph(
                self._projections,
                revision_id=self._revision_id,
                repository_id=self._repository_id,
                revision=self._revision,
            )
            return self._graph
        if self._store is not None:
            self._graph = build_impact_graph_from_store(
                self._store,
                revision_id=self._revision_id,
                repository_id=self._repository_id,
                revision=self._revision,
            )
            return self._graph
        raise DuckDBImpactError(
            "DuckDBImpactEngine requires a store, projections, or graph"
        )

    def rebind(
        self,
        *,
        revision_id: str | None = None,
        repository_id: str | None = None,
        revision: str | None = None,
    ) -> "DuckDBImpactEngine":
        """Return a new engine bound to an exact source revision."""

        return DuckDBImpactEngine(
            store=self._store,
            projections=self._projections,
            revision_id=revision_id if revision_id is not None else self._revision_id,
            repository_id=(
                repository_id if repository_id is not None else self._repository_id
            ),
            revision=revision if revision is not None else self._revision,
            default_budget=self._default_budget,
        )

    def closure(
        self,
        kind: str | ImpactClosureKind,
        seeds: Iterable[str],
        *,
        direction: str | ImpactDirection = ImpactDirection.REVERSE,
        budget: ImpactBudget | Mapping[str, Any] | None = None,
        fail_closed: bool = False,
    ) -> ImpactClosureResult:
        graph = self.graph()
        return bounded_closure(
            kind=kind,
            seeds=seeds,
            edges=graph.edges,
            binding=graph.binding,
            direction=direction,
            budget=budget or self._default_budget,
            fail_closed=fail_closed,
        )

    def reverse_reference_closure(
        self, seeds: Iterable[str], **kwargs: Any
    ) -> ImpactClosureResult:
        return self.closure(ImpactClosureKind.REVERSE_REFERENCE, seeds, **kwargs)

    def call_closure(
        self, seeds: Iterable[str], **kwargs: Any
    ) -> ImpactClosureResult:
        return self.closure(ImpactClosureKind.CALL, seeds, **kwargs)

    def import_closure(
        self, seeds: Iterable[str], **kwargs: Any
    ) -> ImpactClosureResult:
        return self.closure(ImpactClosureKind.IMPORT, seeds, **kwargs)

    def effect_closure(
        self, seeds: Iterable[str], **kwargs: Any
    ) -> ImpactClosureResult:
        return self.closure(ImpactClosureKind.EFFECT, seeds, **kwargs)

    def interface_closure(
        self, seeds: Iterable[str], **kwargs: Any
    ) -> ImpactClosureResult:
        return self.closure(ImpactClosureKind.INTERFACE, seeds, **kwargs)

    def semantic_dependency_closure(
        self, seeds: Iterable[str], **kwargs: Any
    ) -> ImpactClosureResult:
        return self.closure(ImpactClosureKind.SEMANTIC_DEPENDENCY, seeds, **kwargs)

    def conflict_closure(
        self, seeds: Iterable[str], **kwargs: Any
    ) -> ImpactClosureResult:
        return self.closure(ImpactClosureKind.CONFLICT, seeds, **kwargs)

    def impact(
        self,
        *,
        changed_symbols: Iterable[str] = (),
        changed_paths: Iterable[str] = (),
        budget: ImpactBudget | Mapping[str, Any] | None = None,
        fail_closed: bool = False,
    ) -> dict[str, Any]:
        """Composite reverse impact over the graph's symbol/path dependencies."""

        graph = self.graph()
        index = {
            "schema": CODE_IMPACT_INDEX_SCHEMA,
            "repository_tree_id": (
                graph.binding.repository_tree_cid
                or graph.binding.revision
            ),
            "index_version": "code-impact-index-v1",
            "symbol_paths": dict(graph.symbol_paths),
            "symbol_dependencies": {
                key: list(value)
                for key, value in graph.symbol_dependencies.items()
            },
            "path_dependencies": {
                key: list(value) for key, value in graph.path_dependencies.items()
            },
            "validation_targets": {},
            "revision": graph.binding.revision,
            "repository_id": graph.binding.repository_id,
        }
        return impact_from_code_impact_index(
            index,
            changed_symbols=changed_symbols,
            changed_paths=changed_paths,
            budget=budget or self._default_budget,
            fail_closed=fail_closed,
            revision_id=graph.binding.revision_id,
        )


def build_duckdb_impact_engine(
    *,
    store: DuckDBASTStore | None = None,
    graph: ImpactGraph | None = None,
    projections: Sequence[ASTCatalogProjection] | None = None,
    revision_id: str | None = None,
    repository_id: str | None = None,
    revision: str | None = None,
    default_budget: ImpactBudget | None = None,
) -> DuckDBImpactEngine:
    """Construct a :class:`DuckDBImpactEngine` with standard defaults."""

    return DuckDBImpactEngine(
        store=store,
        graph=graph,
        projections=projections,
        revision_id=revision_id,
        repository_id=repository_id,
        revision=revision,
        default_budget=default_budget,
    )


def impact_schema_descriptor() -> dict[str, Any]:
    """Return a deterministic machine-readable impact query statement."""

    return {
        "interface": DUCKDB_IMPACT_INTERFACE,
        "store_schema_version": DUCKDB_IMPACT_SCHEMA_VERSION,
        "closure_result_schema": IMPACT_CLOSURE_RESULT_SCHEMA,
        "graph_schema": IMPACT_GRAPH_SCHEMA,
        "revision_binding_schema": IMPACT_REVISION_BINDING_SCHEMA,
        "closure_kinds": sorted(IMPACT_CLOSURE_KINDS),
        "directions": sorted(item.value for item in ImpactDirection),
        "default_budget": ImpactBudget().to_dict(),
        "hard_limits": {
            "max_depth": HARD_MAX_DEPTH,
            "max_rows": HARD_MAX_ROWS,
            "max_time_ms": HARD_MAX_TIME_MS,
        },
        "guarantees": {
            "closures_bind_exact_source_revision": True,
            "depth_row_time_budgets_enforced": True,
            "agrees_with_code_impact_index_analyzers": True,
            "import_inert": True,
        },
    }


__all__ = [
    "CODE_IMPACT_INDEX_SCHEMA",
    "CODE_IMPACT_RESULT_SCHEMA",
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_ROWS",
    "DEFAULT_MAX_TIME_MS",
    "DUCKDB_IMPACT_INTERFACE",
    "DUCKDB_IMPACT_SCHEMA_VERSION",
    "DuckDBImpactEngine",
    "DuckDBImpactError",
    "HARD_MAX_DEPTH",
    "HARD_MAX_ROWS",
    "HARD_MAX_TIME_MS",
    "IMPACT_CLOSURE_KINDS",
    "IMPACT_CLOSURE_RESULT_SCHEMA",
    "IMPACT_GRAPH_SCHEMA",
    "IMPACT_REVISION_BINDING_SCHEMA",
    "ImpactBudget",
    "ImpactBudgetExceeded",
    "ImpactClosureKind",
    "ImpactClosureResult",
    "ImpactDirection",
    "ImpactEdge",
    "ImpactGraph",
    "ImpactNode",
    "ImpactRevisionBinding",
    "ImpactRevisionError",
    "binding_from_parts",
    "binding_from_projection",
    "bounded_closure",
    "build_duckdb_impact_engine",
    "build_impact_graph",
    "build_impact_graph_from_store",
    "impact_from_code_impact_index",
    "impact_schema_descriptor",
    "known_impact_fixture_index",
    "snapshot_store_projections",
]
