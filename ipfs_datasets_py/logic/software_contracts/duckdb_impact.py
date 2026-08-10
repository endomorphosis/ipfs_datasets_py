"""Bounded AST impact, conflict, and dependency closures (DQK-033).

Queries the normalized DuckDB ``asts`` catalog (and the in-process
:class:`~.duckdb_ast_store.DuckDBASTStore` projection of that catalog) for
revision-bound reverse closures used by:

* task scopes
* validation selection
* proof invalidation

Supported closure kinds (closed vocabulary):

* reverse-reference
* call
* import
* effect
* interface
* semantic-dependency (union of reference/call/import reverse edges)
* conflict (duplicate definitions and contradictory effect surfaces)

Every closure binds an exact ``revision_id`` from ``source_revisions``.
Depth, row, and wall-clock budgets are enforced; results are deterministic
and explainable (shortest dependency chains).

The reverse-dependency orientation matches the supervisor
:class:`~ipfs_accelerate_py.agent_supervisor.code_evidence_graph.CodeImpactIndex`
(``dependent -> providers``, reverse walk for impact).  Known fixtures must
agree with that analyzer on the same edge population.

Importing this module is inert — no DuckDB, network, or filesystem I/O.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Protocol, runtime_checkable

from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
    ASTCatalogProjection,
    DuckDBASTStore,
    SymbolRow,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

DUCKDB_IMPACT_INTERFACE: Final = "DuckDBASTImpact@1"
DUCKDB_IMPACT_SCHEMA_VERSION: Final = "duckdb-ast-impact/v1"

# Closed closure vocabulary declared by DQK-033.
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

# Default / hard budgets.  Callers may tighten but not exceed the hard caps.
DEFAULT_MAX_DEPTH: Final = 32
DEFAULT_MAX_ROWS: Final = 10_000
DEFAULT_MAX_TIME_MS: Final = 5_000.0
HARD_MAX_DEPTH: Final = 4_096
HARD_MAX_ROWS: Final = 1_000_000
HARD_MAX_TIME_MS: Final = 300_000.0

# Entity kinds emitted in closure nodes (closed).
IMPACT_ENTITY_KINDS: Final[frozenset[str]] = frozenset(
    {
        "symbol",
        "path",
        "module",
        "scope",
        "interface",
        "effect",
        "conflict",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DuckDBImpactError(ValueError):
    """Raised when an impact query input or revision binding is invalid."""


class ImpactBudgetExceeded(DuckDBImpactError):
    """Raised when a hard depth/row/time budget is exceeded in fail-closed mode."""

    def __init__(
        self,
        message: str,
        *,
        dimension: str,
        limit: int | float,
        observed: int | float,
    ) -> None:
        super().__init__(message)
        self.dimension = dimension
        self.limit = limit
        self.observed = observed


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ImpactBudget:
    """Depth / row / wall-clock budgets for one closure query.

    * ``max_depth`` — maximum BFS hop distance from seed roots.
    * ``max_rows`` — maximum distinct closure nodes retained.
    * ``max_time_ms`` — wall-clock budget in milliseconds.
    * ``fail_closed`` — when true, exceeding a budget raises
      :class:`ImpactBudgetExceeded`; when false, the result is truncated
      with an explicit reason.
    """

    max_depth: int = DEFAULT_MAX_DEPTH
    max_rows: int = DEFAULT_MAX_ROWS
    max_time_ms: float = DEFAULT_MAX_TIME_MS
    fail_closed: bool = True

    def __post_init__(self) -> None:
        depth = self.max_depth
        rows = self.max_rows
        ms = self.max_time_ms
        if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
            raise DuckDBImpactError("max_depth must be a non-negative integer")
        if isinstance(rows, bool) or not isinstance(rows, int) or rows < 1:
            raise DuckDBImpactError("max_rows must be a positive integer")
        if isinstance(ms, bool) or not isinstance(ms, (int, float)) or ms <= 0:
            raise DuckDBImpactError("max_time_ms must be a positive number")
        object.__setattr__(self, "max_depth", min(int(depth), HARD_MAX_DEPTH))
        object.__setattr__(self, "max_rows", min(int(rows), HARD_MAX_ROWS))
        object.__setattr__(
            self, "max_time_ms", min(float(ms), HARD_MAX_TIME_MS)
        )
        object.__setattr__(self, "fail_closed", bool(self.fail_closed))

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_depth": self.max_depth,
            "max_rows": self.max_rows,
            "max_time_ms": self.max_time_ms,
            "fail_closed": self.fail_closed,
        }


class ImpactClosureKind(StrEnum):
    """Closed vocabulary of impact closure kinds."""

    REVERSE_REFERENCE = "reverse_reference"
    CALL = "call"
    IMPORT = "import"
    EFFECT = "effect"
    INTERFACE = "interface"
    SEMANTIC_DEPENDENCY = "semantic_dependency"
    CONFLICT = "conflict"


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ImpactNode:
    """One entity retained in a revision-bound impact closure."""

    node_id: str
    entity_kind: str
    label: str
    path: str
    blob_id: str
    symbol_id: str | None = None
    qualified_name: str | None = None
    depth: int = 0

    def __post_init__(self) -> None:
        if self.entity_kind not in IMPACT_ENTITY_KINDS:
            raise DuckDBImpactError(
                f"entity_kind must be one of {sorted(IMPACT_ENTITY_KINDS)}, "
                f"got {self.entity_kind!r}"
            )
        if isinstance(self.depth, bool) or not isinstance(self.depth, int) or self.depth < 0:
            raise DuckDBImpactError("depth must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "entity_kind": self.entity_kind,
            "label": self.label,
            "path": self.path,
            "blob_id": self.blob_id,
            "symbol_id": self.symbol_id,
            "qualified_name": self.qualified_name,
            "depth": self.depth,
        }


@dataclass(frozen=True, slots=True)
class ImpactEdge:
    """Directed reverse-dependency edge: ``provider`` impacts ``dependent``."""

    edge_id: str
    kind: str
    provider_id: str
    dependent_id: str
    reason: str
    depth: int = 1

    def __post_init__(self) -> None:
        if self.kind not in IMPACT_CLOSURE_KINDS:
            raise DuckDBImpactError(
                f"edge kind must be one of {sorted(IMPACT_CLOSURE_KINDS)}, "
                f"got {self.kind!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "kind": self.kind,
            "provider_id": self.provider_id,
            "dependent_id": self.dependent_id,
            "reason": self.reason,
            "depth": self.depth,
        }


@dataclass(frozen=True, slots=True)
class ImpactClosure:
    """Revision-bound, budgeted reverse-dependency closure result."""

    revision_id: str
    repository_id: str
    revision: str
    kind: str
    seed_ids: tuple[str, ...]
    nodes: tuple[ImpactNode, ...]
    edges: tuple[ImpactEdge, ...]
    chains: Mapping[str, tuple[str, ...]]
    budget: ImpactBudget
    truncated: bool = False
    truncation_reason: str = ""
    elapsed_ms: float = 0.0
    schema_version: str = DUCKDB_IMPACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.revision_id:
            raise DuckDBImpactError("ImpactClosure requires revision_id")
        if self.kind not in IMPACT_CLOSURE_KINDS:
            raise DuckDBImpactError(
                f"closure kind must be one of {sorted(IMPACT_CLOSURE_KINDS)}"
            )
        object.__setattr__(
            self,
            "seed_ids",
            tuple(sorted({item for item in self.seed_ids if item})),
        )
        object.__setattr__(
            self,
            "nodes",
            tuple(
                sorted(
                    self.nodes,
                    key=lambda item: (item.depth, item.entity_kind, item.node_id),
                )
            ),
        )
        object.__setattr__(
            self,
            "edges",
            tuple(
                sorted(
                    self.edges,
                    key=lambda item: (item.kind, item.provider_id, item.dependent_id),
                )
            ),
        )
        object.__setattr__(
            self,
            "chains",
            {
                str(key): tuple(str(step) for step in value)
                for key, value in sorted(dict(self.chains or {}).items())
            },
        )

    @property
    def node_ids(self) -> tuple[str, ...]:
        return tuple(item.node_id for item in self.nodes)

    @property
    def affected_symbols(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    item.qualified_name or item.label
                    for item in self.nodes
                    if item.entity_kind == "symbol"
                }
            )
        )

    @property
    def affected_paths(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    item.path
                    for item in self.nodes
                    if item.path and item.entity_kind in {"path", "symbol", "module"}
                }
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DUCKDB_IMPACT_SCHEMA_VERSION,
            "interface": DUCKDB_IMPACT_INTERFACE,
            "revision_id": self.revision_id,
            "repository_id": self.repository_id,
            "revision": self.revision,
            "kind": self.kind,
            "seed_ids": list(self.seed_ids),
            "nodes": [item.to_dict() for item in self.nodes],
            "edges": [item.to_dict() for item in self.edges],
            "chains": {key: list(value) for key, value in self.chains.items()},
            "budget": self.budget.to_dict(),
            "truncated": self.truncated,
            "truncation_reason": self.truncation_reason,
            "elapsed_ms": self.elapsed_ms,
            "affected_symbols": list(self.affected_symbols),
            "affected_paths": list(self.affected_paths),
        }


@dataclass(frozen=True, slots=True)
class ConflictFinding:
    """A structural conflict discovered within one source revision."""

    conflict_id: str
    kind: str
    subject: str
    left_id: str
    right_id: str
    message: str
    path: str = ""
    severity: str = "error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "kind": self.kind,
            "subject": self.subject,
            "left_id": self.left_id,
            "right_id": self.right_id,
            "message": self.message,
            "path": self.path,
            "severity": self.severity,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise DuckDBImpactError(f"{field_name} must be a string")
    if value != value.strip() and value:
        raise DuckDBImpactError(
            f"{field_name} must not contain surrounding whitespace"
        )
    if not allow_empty and not value:
        raise DuckDBImpactError(f"{field_name} must not be empty")
    if "\x00" in value:
        raise DuckDBImpactError(f"{field_name} must not contain NUL")
    return value


def _choice(value: object, field_name: str, allowed: frozenset[str]) -> str:
    result = _text(value, field_name)
    if result not in allowed:
        raise DuckDBImpactError(
            f"{field_name} must be one of {sorted(allowed)}, got {result!r}"
        )
    return result


def path_to_module(path: str) -> str:
    """Convert a repository path into a dotted module-ish name."""

    normalized = path.replace("\\", "/").lstrip("./")
    for suffix in (".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    parts = [
        part
        for part in normalized.split("/")
        if part and part not in {"__pycache__", "."}
    ]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _symbol_aliases(symbol: SymbolRow) -> frozenset[str]:
    aliases = {symbol.name, symbol.qualified_name, symbol.symbol_id}
    if "." in symbol.qualified_name:
        aliases.add(symbol.qualified_name.rsplit(".", 1)[-1])
    return frozenset(item for item in aliases if item)


def _name_matches(candidate: str, aliases: frozenset[str]) -> bool:
    if not candidate:
        return False
    if candidate in aliases:
        return True
    # Qualified reference to an unqualified definition (and vice versa).
    if "." in candidate:
        return candidate.rsplit(".", 1)[-1] in aliases
    return any(
        alias == candidate or alias.endswith(f".{candidate}") for alias in aliases
    )


# ---------------------------------------------------------------------------
# Pure reverse-closure algorithm (CodeImpactIndex-compatible)
# ---------------------------------------------------------------------------


def reverse_dependency_map(
    dependencies: Mapping[str, Sequence[str]],
) -> dict[str, tuple[str, ...]]:
    """Invert ``dependent -> providers`` into ``provider -> dependents``."""

    reverse: dict[str, set[str]] = {}
    for dependent, providers in dependencies.items():
        dependent_key = str(dependent)
        reverse.setdefault(dependent_key, set())
        for provider in providers:
            provider_key = str(provider)
            reverse.setdefault(provider_key, set()).add(dependent_key)
    return {
        key: tuple(sorted(value))
        for key, value in sorted(reverse.items())
    }


def bounded_reverse_closure(
    roots: Iterable[str],
    reverse: Mapping[str, Sequence[str]],
    *,
    budget: ImpactBudget | None = None,
) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]], bool, str]:
    """BFS reverse-dependency closure with depth/row/time budgets.

    Matches supervisor ``CodeImpactIndex._closure_with_chains`` selection of
    the lexicographically shortest chain, with explicit budgets layered on top.

    Returns ``(node_ids, chains, truncated, truncation_reason)``.
    """

    limits = budget or ImpactBudget()
    started = time.monotonic()
    normalized_roots = tuple(sorted({str(item) for item in roots if str(item)}))
    chains: dict[str, tuple[str, ...]] = {
        root: (root,) for root in normalized_roots
    }
    depths: dict[str, int] = {root: 0 for root in normalized_roots}
    queue: deque[str] = deque(normalized_roots)
    truncated = False
    reason = ""

    def _elapsed_ms() -> float:
        return (time.monotonic() - started) * 1000.0

    def _hit(dimension: str, limit: int | float, observed: int | float) -> None:
        nonlocal truncated, reason
        message = (
            f"impact closure budget exceeded on {dimension} "
            f"({observed} > {limit})"
        )
        if limits.fail_closed:
            raise ImpactBudgetExceeded(
                message,
                dimension=dimension,
                limit=limit,
                observed=observed,
            )
        truncated = True
        reason = message

    while queue:
        if _elapsed_ms() > limits.max_time_ms:
            _hit("time_ms", limits.max_time_ms, _elapsed_ms())
            break
        if len(chains) > limits.max_rows:
            # Already accepted one too many; trim is handled by fail path.
            _hit("rows", limits.max_rows, len(chains))
            break
        current = queue.popleft()
        current_depth = depths[current]
        for dependent in reverse.get(current, ()):
            next_depth = current_depth + 1
            if next_depth > limits.max_depth:
                _hit("depth", limits.max_depth, next_depth)
                if truncated and not limits.fail_closed:
                    continue
                break
            if _elapsed_ms() > limits.max_time_ms:
                _hit("time_ms", limits.max_time_ms, _elapsed_ms())
                queue.clear()
                break
            candidate = (*chains[current], dependent)
            existing = chains.get(dependent)
            if existing is None:
                if len(chains) + 1 > limits.max_rows:
                    _hit("rows", limits.max_rows, len(chains) + 1)
                    queue.clear()
                    break
                chains[dependent] = candidate
                depths[dependent] = next_depth
                queue.append(dependent)
            elif (len(candidate), candidate) < (len(existing), existing):
                chains[dependent] = candidate
                depths[dependent] = next_depth
                queue.append(dependent)

    return tuple(sorted(chains)), chains, truncated, reason


def pure_impact_closure(
    *,
    roots: Iterable[str],
    dependencies: Mapping[str, Sequence[str]],
    budget: ImpactBudget | None = None,
) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]], bool, str]:
    """Impact selection over ``dependent -> providers`` (CodeImpactIndex parity)."""

    return bounded_reverse_closure(
        roots,
        reverse_dependency_map(dependencies),
        budget=budget,
    )


# ---------------------------------------------------------------------------
# Revision graph built from AST catalog projections
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _SymbolLoc:
    symbol: SymbolRow
    path: str
    blob_id: str
    module_name: str
    revision_id: str
    node_id: str


@dataclass
class RevisionImpactGraph:
    """Precomputed reverse edges for one exact source revision."""

    revision_id: str
    repository_id: str
    revision: str
    repository_tree_cid: str | None
    projections: tuple[ASTCatalogProjection, ...]
    symbols: dict[str, _SymbolLoc] = field(default_factory=dict)
    symbols_by_alias: dict[str, list[str]] = field(default_factory=dict)
    path_nodes: dict[str, str] = field(default_factory=dict)
    module_nodes: dict[str, str] = field(default_factory=dict)
    scope_owner: dict[tuple[str, str], str] = field(default_factory=dict)
    # provider_id -> list[(dependent_id, edge_kind, reason)]
    reverse_edges: dict[str, list[tuple[str, str, str]]] = field(
        default_factory=dict
    )
    # dependent_id -> providers (CodeImpactIndex orientation)
    symbol_dependencies: dict[str, set[str]] = field(default_factory=dict)
    path_dependencies: dict[str, set[str]] = field(default_factory=dict)
    conflicts: list[ConflictFinding] = field(default_factory=list)

    def add_reverse(
        self,
        *,
        provider_id: str,
        dependent_id: str,
        kind: str,
        reason: str,
    ) -> None:
        if not provider_id or not dependent_id or provider_id == dependent_id:
            return
        bucket = self.reverse_edges.setdefault(provider_id, [])
        triple = (dependent_id, kind, reason)
        if triple not in bucket:
            bucket.append(triple)
        if kind in {
            ImpactClosureKind.REVERSE_REFERENCE.value,
            ImpactClosureKind.CALL.value,
            ImpactClosureKind.IMPORT.value,
            ImpactClosureKind.INTERFACE.value,
            ImpactClosureKind.SEMANTIC_DEPENDENCY.value,
        }:
            # Only symbol-named nodes participate in the pure analyzer map.
            if provider_id.startswith("symbol:") and dependent_id.startswith(
                "symbol:"
            ):
                self.symbol_dependencies.setdefault(dependent_id, set()).add(
                    provider_id
                )


def _symbol_node_id(path: str, symbol_id: str) -> str:
    return f"symbol:{path}:{symbol_id}"


def _path_node_id(path: str) -> str:
    return f"path:{path}"


def _module_node_id(module: str) -> str:
    return f"module:{module}"


def _scope_key(blob_id: str, scope_id: str) -> tuple[str, str]:
    return (blob_id, scope_id)


def build_revision_impact_graph(
    projections: Sequence[ASTCatalogProjection],
    *,
    revision_id: str,
) -> RevisionImpactGraph:
    """Build reverse-dependency edges for one exact revision_id."""

    revision_id = _text(revision_id, "revision_id")
    selected = [
        item
        for item in projections
        if item.source_revision.revision_id == revision_id
    ]
    if not selected:
        raise DuckDBImpactError(
            f"no AST projections bound to revision_id {revision_id!r}"
        )
    # Homogeneous revision metadata (exact binding).
    head = selected[0].source_revision
    for item in selected[1:]:
        rev = item.source_revision
        if rev.revision_id != head.revision_id:
            raise DuckDBImpactError("mixed revision_id in impact graph")
        if rev.repository_id != head.repository_id:
            raise DuckDBImpactError(
                "mixed repository_id within the same revision_id"
            )
        if rev.revision != head.revision:
            raise DuckDBImpactError(
                "mixed Git revision identity within the same revision_id"
            )

    graph = RevisionImpactGraph(
        revision_id=head.revision_id,
        repository_id=head.repository_id,
        revision=head.revision,
        repository_tree_cid=head.repository_tree_cid,
        projections=tuple(selected),
    )

    # Pass 1: index symbols, paths, modules, scope owners.
    qname_defs: dict[str, list[_SymbolLoc]] = {}
    for projection in selected:
        path = projection.source_file.path
        blob_id = projection.blob_id
        module_name = path_to_module(path)
        # Prefer IR module name when present on the payload.
        try:
            payload = __import__("json").loads(projection.ast_blob.payload_json)
            module_payload = payload.get("module") if isinstance(payload, dict) else None
            if isinstance(module_payload, dict) and module_payload.get("name"):
                module_name = str(module_payload["name"])
        except Exception:
            pass

        path_id = _path_node_id(path)
        graph.path_nodes[path] = path_id
        module_id = _module_node_id(module_name)
        graph.module_nodes[module_name] = module_id

        symbol_by_id: dict[str, SymbolRow] = {
            item.symbol_id: item for item in projection.symbols
        }
        for scope in projection.scopes:
            owner = scope.owner_symbol_id
            if owner and owner in symbol_by_id:
                graph.scope_owner[_scope_key(blob_id, scope.scope_id)] = (
                    _symbol_node_id(path, owner)
                )

        for symbol in projection.symbols:
            loc = _SymbolLoc(
                symbol=symbol,
                path=path,
                blob_id=blob_id,
                module_name=module_name,
                revision_id=revision_id,
                node_id=_symbol_node_id(path, symbol.symbol_id),
            )
            graph.symbols[loc.node_id] = loc
            for alias in _symbol_aliases(symbol):
                graph.symbols_by_alias.setdefault(alias, []).append(loc.node_id)
            qname_defs.setdefault(symbol.qualified_name, []).append(loc)
            # Scope that contains the definition is owned by the symbol when
            # no explicit owner is set.
            graph.scope_owner.setdefault(
                _scope_key(blob_id, symbol.scope_id), loc.node_id
            )

    # Pass 2: conflicts (duplicate qualified names across blobs/paths).
    for qname, locs in sorted(qname_defs.items()):
        if len(locs) < 2:
            continue
        # Distinct paths or distinct kinds → conflict.
        paths = {item.path for item in locs}
        kinds = {item.symbol.kind for item in locs}
        if len(paths) > 1 or len(kinds) > 1 or len({item.blob_id for item in locs}) > 1:
            left, right = locs[0], locs[1]
            graph.conflicts.append(
                ConflictFinding(
                    conflict_id=f"conflict:dup:{qname}:{left.node_id}:{right.node_id}",
                    kind="duplicate_definition",
                    subject=qname,
                    left_id=left.node_id,
                    right_id=right.node_id,
                    message=(
                        f"qualified name {qname!r} defined in multiple places "
                        f"({left.path} and {right.path})"
                    ),
                    path=left.path,
                )
            )

    # Pass 3: edges from references, calls, imports, effects, interfaces.
    for projection in selected:
        path = projection.source_file.path
        blob_id = projection.blob_id
        path_id = _path_node_id(path)
        module_name = path_to_module(path)
        try:
            payload = __import__("json").loads(projection.ast_blob.payload_json)
            module_payload = payload.get("module") if isinstance(payload, dict) else None
            if isinstance(module_payload, dict) and module_payload.get("name"):
                module_name = str(module_payload["name"])
        except Exception:
            pass

        def _owner_for_scope(scope_id: str) -> str:
            owned = graph.scope_owner.get(_scope_key(blob_id, scope_id))
            if owned is not None:
                return owned
            # Fall back to the file path node when the scope has no owner.
            return path_id

        # Reverse references: name uses of a defined symbol.
        for reference in projection.references:
            dependent = _owner_for_scope(reference.scope_id)
            matched = _match_symbols(graph, reference.name)
            for provider in matched:
                graph.add_reverse(
                    provider_id=provider,
                    dependent_id=dependent,
                    kind=ImpactClosureKind.REVERSE_REFERENCE.value,
                    reason=f"reference:{reference.name}",
                )

        # Calls: callee name reverse edges.
        for call in projection.calls:
            dependent = _owner_for_scope(call.scope_id)
            matched = _match_symbols(graph, call.callee_name)
            for provider in matched:
                graph.add_reverse(
                    provider_id=provider,
                    dependent_id=dependent,
                    kind=ImpactClosureKind.CALL.value,
                    reason=f"call:{call.callee_name}",
                )
            # Also attach path-level dependency for call edges.
            for provider in matched:
                provider_path = graph.symbols[provider].path
                if provider_path != path:
                    graph.path_dependencies.setdefault(path, set()).add(
                        provider_path
                    )

        # Imports: module reverse edges.
        for item in projection.imports:
            dependent = path_id
            provider_module = item.module
            provider_id = graph.module_nodes.get(provider_module)
            if provider_id is None:
                # External or not-yet-indexed module still becomes a node key.
                provider_id = _module_node_id(provider_module)
                graph.module_nodes.setdefault(provider_module, provider_id)
            graph.add_reverse(
                provider_id=provider_id,
                dependent_id=dependent,
                kind=ImpactClosureKind.IMPORT.value,
                reason=f"import:{provider_module}",
            )
            # Path-level import edges when the module is local.
            for local_path, local_path_id in graph.path_nodes.items():
                if path_to_module(local_path) == provider_module or (
                    local_path.replace("\\", "/").replace("/", ".")
                    .removesuffix(".py")
                    .endswith(provider_module)
                ):
                    graph.add_reverse(
                        provider_id=local_path_id,
                        dependent_id=dependent,
                        kind=ImpactClosureKind.IMPORT.value,
                        reason=f"import_path:{provider_module}",
                    )
                    graph.path_dependencies.setdefault(path, set()).add(local_path)
            # Imported symbol reverse edges.
            if item.imported_name:
                for provider in _match_symbols(graph, item.imported_name):
                    # Prefer providers from the imported module.
                    loc = graph.symbols[provider]
                    if (
                        loc.module_name == provider_module
                        or loc.symbol.name == item.imported_name
                        or loc.symbol.qualified_name.endswith(
                            f".{item.imported_name}"
                        )
                    ):
                        graph.add_reverse(
                            provider_id=provider,
                            dependent_id=dependent,
                            kind=ImpactClosureKind.IMPORT.value,
                            reason=(
                                f"import_symbol:{provider_module}."
                                f"{item.imported_name}"
                            ),
                        )

        # Effects: shared subject surface.
        for effect in projection.effects:
            dependent = _owner_for_scope(effect.scope_id)
            subject = effect.subject
            effect_node = (
                f"effect:{path}:{effect.effect_id}:{effect.kind}:{effect.operation}"
            )
            # Subject may be a symbol alias.
            for provider in _match_symbols(graph, subject):
                graph.add_reverse(
                    provider_id=provider,
                    dependent_id=dependent,
                    kind=ImpactClosureKind.EFFECT.value,
                    reason=f"effect:{effect.kind}:{effect.operation}:{subject}",
                )
            # Same-subject effects across the revision form a co-effect cluster.
            for other in selected:
                if other.blob_id == blob_id:
                    continue
                for other_effect in other.effects:
                    if (
                        other_effect.subject == subject
                        and other_effect.kind == effect.kind
                        and other_effect.operation != effect.operation
                    ):
                        other_owner = graph.scope_owner.get(
                            _scope_key(other.blob_id, other_effect.scope_id),
                            _path_node_id(other.source_file.path),
                        )
                        graph.conflicts.append(
                            ConflictFinding(
                                conflict_id=(
                                    f"conflict:effect:{subject}:"
                                    f"{effect.effect_id}:{other_effect.effect_id}"
                                ),
                                kind="effect_contradiction",
                                subject=subject,
                                left_id=dependent,
                                right_id=other_owner,
                                message=(
                                    f"effect operations conflict on subject "
                                    f"{subject!r}: {effect.operation!r} vs "
                                    f"{other_effect.operation!r}"
                                ),
                                path=path,
                            )
                        )
                    if other_effect.subject == subject:
                        other_owner = graph.scope_owner.get(
                            _scope_key(other.blob_id, other_effect.scope_id),
                            _path_node_id(other.source_file.path),
                        )
                        graph.add_reverse(
                            provider_id=dependent,
                            dependent_id=other_owner,
                            kind=ImpactClosureKind.EFFECT.value,
                            reason=f"shared_effect_subject:{subject}",
                        )
            del effect_node  # reserved for future direct effect-node exposure

        # Interfaces: public surface reverse edges.
        for interface in projection.interfaces:
            interface_id = f"interface:{path}:{interface.interface_id}"
            # Changing an interface impacts importers/callers of its name.
            for provider in _match_symbols(
                graph, interface.qualified_name
            ) or _match_symbols(graph, interface.name):
                # Provider is the defining symbol; dependents are other
                # symbols that reference/call the same name — already
                # captured by ref/call edges.  Also link interface node.
                graph.add_reverse(
                    provider_id=provider,
                    dependent_id=interface_id,
                    kind=ImpactClosureKind.INTERFACE.value,
                    reason=f"interface:{interface.qualified_name}",
                )
            # Cross-file same qualified interface name is a conflict.
            for other in selected:
                if other.blob_id == blob_id:
                    continue
                for other_iface in other.interfaces:
                    if (
                        other_iface.qualified_name == interface.qualified_name
                        and other_iface.signature_text != interface.signature_text
                    ):
                        graph.conflicts.append(
                            ConflictFinding(
                                conflict_id=(
                                    f"conflict:interface:{interface.qualified_name}:"
                                    f"{path}:{other.source_file.path}"
                                ),
                                kind="interface_mismatch",
                                subject=interface.qualified_name,
                                left_id=interface_id,
                                right_id=(
                                    f"interface:{other.source_file.path}:"
                                    f"{other_iface.interface_id}"
                                ),
                                message=(
                                    f"interface signature mismatch for "
                                    f"{interface.qualified_name!r}"
                                ),
                                path=path,
                            )
                        )

    return graph


def _match_symbols(graph: RevisionImpactGraph, name: str) -> list[str]:
    if not name:
        return []
    direct = list(graph.symbols_by_alias.get(name, ()))
    if direct:
        return sorted(set(direct))
    # Qualified / bare fallback scan (bounded by revision population).
    matched: list[str] = []
    for node_id, loc in graph.symbols.items():
        if _name_matches(name, _symbol_aliases(loc.symbol)):
            matched.append(node_id)
    return sorted(set(matched))


# ---------------------------------------------------------------------------
# Query engine
# ---------------------------------------------------------------------------


@runtime_checkable
class DuckDBASTImpactProtocol(Protocol):
    """Protocol surface for DuckDBASTImpact@1."""

    @property
    def interface(self) -> str: ...

    @property
    def schema_version(self) -> str: ...

    def reverse_reference_closure(
        self,
        revision_id: str,
        seeds: Sequence[str],
        *,
        budget: ImpactBudget | None = ...,
    ) -> ImpactClosure: ...

    def call_closure(
        self,
        revision_id: str,
        seeds: Sequence[str],
        *,
        budget: ImpactBudget | None = ...,
    ) -> ImpactClosure: ...

    def import_closure(
        self,
        revision_id: str,
        seeds: Sequence[str],
        *,
        budget: ImpactBudget | None = ...,
    ) -> ImpactClosure: ...

    def effect_closure(
        self,
        revision_id: str,
        seeds: Sequence[str],
        *,
        budget: ImpactBudget | None = ...,
    ) -> ImpactClosure: ...

    def interface_closure(
        self,
        revision_id: str,
        seeds: Sequence[str],
        *,
        budget: ImpactBudget | None = ...,
    ) -> ImpactClosure: ...

    def semantic_dependency_closure(
        self,
        revision_id: str,
        seeds: Sequence[str],
        *,
        budget: ImpactBudget | None = ...,
    ) -> ImpactClosure: ...

    def conflict_closure(
        self,
        revision_id: str,
        seeds: Sequence[str] | None = ...,
        *,
        budget: ImpactBudget | None = ...,
    ) -> ImpactClosure: ...


def _iter_store_projections(
    store: DuckDBASTStore,
) -> tuple[ASTCatalogProjection, ...]:
    """List catalog projections from a store (public or in-memory fallback)."""

    list_fn = getattr(store, "list_projections", None)
    if callable(list_fn):
        return tuple(list_fn())
    # In-memory store used by unit tests — read under the store lock.
    lock = getattr(store, "_lock", None)
    by_blob = getattr(store, "_by_blob", None)
    if by_blob is None:
        raise DuckDBImpactError(
            "AST store does not expose projections for impact queries"
        )
    if lock is not None:
        with lock:
            return tuple(by_blob.values())
    return tuple(by_blob.values())


class DuckDBASTImpact:
    """Revision-bound impact query plane over the AST catalog.

    Accepts an optional :class:`DuckDBASTStore` and/or explicit projections.
    Every query requires an exact ``revision_id`` and enforces depth/row/time
    budgets.
    """

    def __init__(
        self,
        store: DuckDBASTStore | None = None,
        *,
        projections: Sequence[ASTCatalogProjection] | None = None,
    ) -> None:
        self._store = store
        self._projections: list[ASTCatalogProjection] = list(projections or ())
        self._graph_cache: dict[str, RevisionImpactGraph] = {}
        self._stats = {
            "queries": 0,
            "budget_hits": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        }

    @property
    def interface(self) -> str:
        return DUCKDB_IMPACT_INTERFACE

    @property
    def schema_version(self) -> str:
        return DUCKDB_IMPACT_SCHEMA_VERSION

    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    def index(self, projection: ASTCatalogProjection) -> None:
        """Register a projection for subsequent revision-bound queries."""

        if type(projection) is not ASTCatalogProjection:
            raise DuckDBImpactError(
                "index requires an exact ASTCatalogProjection"
            )
        self._projections.append(projection)
        self._graph_cache.pop(projection.source_revision.revision_id, None)
        if self._store is not None:
            self._store.put_projection(projection)

    def _all_projections(self) -> tuple[ASTCatalogProjection, ...]:
        items: list[ASTCatalogProjection] = list(self._projections)
        if self._store is not None:
            items.extend(_iter_store_projections(self._store))
        # Deduplicate by blob_id, last write wins.
        by_blob: dict[str, ASTCatalogProjection] = {}
        for item in items:
            by_blob[item.blob_id] = item
        return tuple(by_blob.values())

    def graph_for_revision(self, revision_id: str) -> RevisionImpactGraph:
        """Return (and cache) the reverse-edge graph for one revision."""

        revision_id = _text(revision_id, "revision_id")
        cached = self._graph_cache.get(revision_id)
        if cached is not None:
            self._stats["cache_hits"] += 1
            return cached
        self._stats["cache_misses"] += 1
        graph = build_revision_impact_graph(
            self._all_projections(), revision_id=revision_id
        )
        self._graph_cache[revision_id] = graph
        return graph

    def invalidate_revision(self, revision_id: str) -> None:
        self._graph_cache.pop(_text(revision_id, "revision_id"), None)

    def _resolve_seeds(
        self,
        graph: RevisionImpactGraph,
        seeds: Sequence[str],
    ) -> tuple[str, ...]:
        resolved: set[str] = set()
        for raw in seeds:
            seed = _text(raw, "seed", allow_empty=False)
            if seed in graph.symbols:
                resolved.add(seed)
                continue
            if seed in graph.path_nodes.values() or seed.startswith("path:"):
                path = seed.removeprefix("path:")
                if path in graph.path_nodes:
                    resolved.add(graph.path_nodes[path])
                else:
                    resolved.add(seed)
                continue
            if seed in graph.module_nodes or seed.startswith("module:"):
                module = seed.removeprefix("module:")
                resolved.add(graph.module_nodes.get(module, seed))
                continue
            # Bare path.
            if seed in graph.path_nodes:
                resolved.add(graph.path_nodes[seed])
                continue
            # Symbol aliases / qualified names.
            matched = _match_symbols(graph, seed)
            if matched:
                resolved.update(matched)
                continue
            # Qualified-name exact match against symbol labels.
            for node_id, loc in graph.symbols.items():
                if loc.symbol.qualified_name == seed or loc.symbol.name == seed:
                    resolved.add(node_id)
            if seed not in resolved and not matched:
                # Retain unknown seeds so the closure still binds them
                # (mirrors CodeImpactIndex uncovered handling).
                resolved.add(seed)
        return tuple(sorted(resolved))

    def _filter_reverse(
        self,
        graph: RevisionImpactGraph,
        kinds: frozenset[str],
    ) -> dict[str, tuple[str, ...]]:
        reverse: dict[str, set[str]] = {}
        for provider, edges in graph.reverse_edges.items():
            for dependent, kind, _reason in edges:
                if kind in kinds:
                    reverse.setdefault(provider, set()).add(dependent)
        return {
            key: tuple(sorted(value))
            for key, value in sorted(reverse.items())
        }

    def _materialize_closure(
        self,
        *,
        graph: RevisionImpactGraph,
        kind: ImpactClosureKind,
        seed_ids: Sequence[str],
        reverse: Mapping[str, Sequence[str]],
        budget: ImpactBudget,
        extra_nodes: Sequence[ImpactNode] = (),
        extra_edges: Sequence[ImpactEdge] = (),
        started: float,
    ) -> ImpactClosure:
        node_ids, chains, truncated, reason = bounded_reverse_closure(
            seed_ids, reverse, budget=budget
        )
        if truncated:
            self._stats["budget_hits"] += 1

        nodes_by_id: dict[str, ImpactNode] = {}
        for node_id in node_ids:
            depth = max(0, len(chains.get(node_id, (node_id,))) - 1)
            if node_id in graph.symbols:
                loc = graph.symbols[node_id]
                nodes_by_id[node_id] = ImpactNode(
                    node_id=node_id,
                    entity_kind="symbol",
                    label=loc.symbol.qualified_name,
                    path=loc.path,
                    blob_id=loc.blob_id,
                    symbol_id=loc.symbol.symbol_id,
                    qualified_name=loc.symbol.qualified_name,
                    depth=depth,
                )
            elif node_id.startswith("path:"):
                path = node_id.removeprefix("path:")
                nodes_by_id[node_id] = ImpactNode(
                    node_id=node_id,
                    entity_kind="path",
                    label=path,
                    path=path,
                    blob_id="",
                    depth=depth,
                )
            elif node_id.startswith("module:"):
                module = node_id.removeprefix("module:")
                nodes_by_id[node_id] = ImpactNode(
                    node_id=node_id,
                    entity_kind="module",
                    label=module,
                    path="",
                    blob_id="",
                    depth=depth,
                )
            elif node_id.startswith("interface:"):
                nodes_by_id[node_id] = ImpactNode(
                    node_id=node_id,
                    entity_kind="interface",
                    label=node_id.removeprefix("interface:"),
                    path=node_id.split(":", 2)[1] if node_id.count(":") >= 2 else "",
                    blob_id="",
                    depth=depth,
                )
            elif node_id.startswith("conflict:"):
                nodes_by_id[node_id] = ImpactNode(
                    node_id=node_id,
                    entity_kind="conflict",
                    label=node_id,
                    path="",
                    blob_id="",
                    depth=depth,
                )
            else:
                nodes_by_id[node_id] = ImpactNode(
                    node_id=node_id,
                    entity_kind="symbol",
                    label=node_id,
                    path="",
                    blob_id="",
                    depth=depth,
                )

        for item in extra_nodes:
            nodes_by_id.setdefault(item.node_id, item)

        edges: list[ImpactEdge] = list(extra_edges)
        for provider, dependents in reverse.items():
            if provider not in nodes_by_id:
                continue
            for dependent in dependents:
                if dependent not in nodes_by_id:
                    continue
                # Prefer original reason/kind from the graph when available.
                matched_kind = kind.value
                matched_reason = matched_kind
                for dep, edge_kind, edge_reason in graph.reverse_edges.get(
                    provider, ()
                ):
                    if dep == dependent and (
                        edge_kind == kind.value
                        or kind is ImpactClosureKind.SEMANTIC_DEPENDENCY
                    ):
                        matched_kind = edge_kind
                        matched_reason = edge_reason
                        break
                edges.append(
                    ImpactEdge(
                        edge_id=f"edge:{matched_kind}:{provider}->{dependent}",
                        kind=matched_kind
                        if matched_kind in IMPACT_CLOSURE_KINDS
                        else kind.value,
                        provider_id=provider,
                        dependent_id=dependent,
                        reason=matched_reason,
                        depth=nodes_by_id[dependent].depth,
                    )
                )

        elapsed = (time.monotonic() - started) * 1000.0
        self._stats["queries"] += 1
        return ImpactClosure(
            revision_id=graph.revision_id,
            repository_id=graph.repository_id,
            revision=graph.revision,
            kind=kind.value,
            seed_ids=tuple(seed_ids),
            nodes=tuple(nodes_by_id.values()),
            edges=tuple(edges),
            chains=chains,
            budget=budget,
            truncated=truncated,
            truncation_reason=reason,
            elapsed_ms=elapsed,
        )

    def _run(
        self,
        *,
        revision_id: str,
        seeds: Sequence[str],
        kind: ImpactClosureKind,
        edge_kinds: frozenset[str],
        budget: ImpactBudget | None,
    ) -> ImpactClosure:
        started = time.monotonic()
        limits = budget or ImpactBudget()
        graph = self.graph_for_revision(revision_id)
        seed_ids = self._resolve_seeds(graph, seeds)
        reverse = self._filter_reverse(graph, edge_kinds)
        return self._materialize_closure(
            graph=graph,
            kind=kind,
            seed_ids=seed_ids,
            reverse=reverse,
            budget=limits,
            started=started,
        )

    def reverse_reference_closure(
        self,
        revision_id: str,
        seeds: Sequence[str],
        *,
        budget: ImpactBudget | None = None,
    ) -> ImpactClosure:
        """Bounded reverse-reference closure for symbol seeds."""

        return self._run(
            revision_id=revision_id,
            seeds=seeds,
            kind=ImpactClosureKind.REVERSE_REFERENCE,
            edge_kinds=frozenset({ImpactClosureKind.REVERSE_REFERENCE.value}),
            budget=budget,
        )

    def call_closure(
        self,
        revision_id: str,
        seeds: Sequence[str],
        *,
        budget: ImpactBudget | None = None,
    ) -> ImpactClosure:
        """Bounded reverse call-graph closure (callees → callers)."""

        return self._run(
            revision_id=revision_id,
            seeds=seeds,
            kind=ImpactClosureKind.CALL,
            edge_kinds=frozenset({ImpactClosureKind.CALL.value}),
            budget=budget,
        )

    def import_closure(
        self,
        revision_id: str,
        seeds: Sequence[str],
        *,
        budget: ImpactBudget | None = None,
    ) -> ImpactClosure:
        """Bounded reverse import closure (modules/paths → importers)."""

        return self._run(
            revision_id=revision_id,
            seeds=seeds,
            kind=ImpactClosureKind.IMPORT,
            edge_kinds=frozenset({ImpactClosureKind.IMPORT.value}),
            budget=budget,
        )

    def effect_closure(
        self,
        revision_id: str,
        seeds: Sequence[str],
        *,
        budget: ImpactBudget | None = None,
    ) -> ImpactClosure:
        """Bounded effect-surface closure for shared subjects."""

        return self._run(
            revision_id=revision_id,
            seeds=seeds,
            kind=ImpactClosureKind.EFFECT,
            edge_kinds=frozenset({ImpactClosureKind.EFFECT.value}),
            budget=budget,
        )

    def interface_closure(
        self,
        revision_id: str,
        seeds: Sequence[str],
        *,
        budget: ImpactBudget | None = None,
    ) -> ImpactClosure:
        """Bounded public-interface impact closure."""

        return self._run(
            revision_id=revision_id,
            seeds=seeds,
            kind=ImpactClosureKind.INTERFACE,
            edge_kinds=frozenset({ImpactClosureKind.INTERFACE.value}),
            budget=budget,
        )

    def semantic_dependency_closure(
        self,
        revision_id: str,
        seeds: Sequence[str],
        *,
        budget: ImpactBudget | None = None,
    ) -> ImpactClosure:
        """Union reverse closure over references, calls, and imports.

        This is the primary query used for task scopes, validation selection,
        and proof invalidation.  On the symbol-dependency subpopulation it
        agrees with supervisor ``CodeImpactIndex.impact``.
        """

        return self._run(
            revision_id=revision_id,
            seeds=seeds,
            kind=ImpactClosureKind.SEMANTIC_DEPENDENCY,
            edge_kinds=frozenset(
                {
                    ImpactClosureKind.REVERSE_REFERENCE.value,
                    ImpactClosureKind.CALL.value,
                    ImpactClosureKind.IMPORT.value,
                    ImpactClosureKind.INTERFACE.value,
                }
            ),
            budget=budget,
        )

    def conflict_closure(
        self,
        revision_id: str,
        seeds: Sequence[str] | None = None,
        *,
        budget: ImpactBudget | None = None,
    ) -> ImpactClosure:
        """Bounded conflict population for a revision (optionally seed-filtered)."""

        started = time.monotonic()
        limits = budget or ImpactBudget()
        graph = self.graph_for_revision(revision_id)
        findings = list(graph.conflicts)
        seed_set: set[str] | None = None
        seed_qnames: set[str] = set()
        if seeds is not None:
            seed_set = set(self._resolve_seeds(graph, seeds))
            for seed in seed_set:
                if seed in graph.symbols:
                    seed_qnames.add(graph.symbols[seed].symbol.qualified_name)
                seed_qnames.add(seed)

        nodes: list[ImpactNode] = []
        edges: list[ImpactEdge] = []
        chains: dict[str, tuple[str, ...]] = {}
        seed_ids: list[str] = []
        truncated = False
        reason = ""

        for finding in findings:
            if seed_set is not None:
                involved = {finding.left_id, finding.right_id, finding.subject}
                if not (
                    involved & seed_set
                    or finding.subject in seed_qnames
                    or finding.left_id in seed_set
                    or finding.right_id in seed_set
                ):
                    continue

            conflict_node_id = finding.conflict_id
            projected_count = len(nodes) + 1 + (
                (1 if finding.left_id in graph.symbols else 0)
                + (1 if finding.right_id in graph.symbols else 0)
            )
            if projected_count > limits.max_rows:
                message = (
                    f"impact closure budget exceeded on rows "
                    f"({projected_count} > {limits.max_rows})"
                )
                if limits.fail_closed:
                    raise ImpactBudgetExceeded(
                        message,
                        dimension="rows",
                        limit=limits.max_rows,
                        observed=projected_count,
                    )
                truncated = True
                reason = message
                break

            elapsed_probe = (time.monotonic() - started) * 1000.0
            if elapsed_probe > limits.max_time_ms:
                message = (
                    f"impact closure budget exceeded on time_ms "
                    f"({elapsed_probe} > {limits.max_time_ms})"
                )
                if limits.fail_closed:
                    raise ImpactBudgetExceeded(
                        message,
                        dimension="time_ms",
                        limit=limits.max_time_ms,
                        observed=elapsed_probe,
                    )
                truncated = True
                reason = message
                break

            nodes.append(
                ImpactNode(
                    node_id=conflict_node_id,
                    entity_kind="conflict",
                    label=finding.subject,
                    path=finding.path,
                    blob_id="",
                    depth=0,
                )
            )
            chains[conflict_node_id] = (conflict_node_id,)
            seed_ids.append(conflict_node_id)
            for endpoint in (finding.left_id, finding.right_id):
                if endpoint in graph.symbols:
                    loc = graph.symbols[endpoint]
                    nodes.append(
                        ImpactNode(
                            node_id=endpoint,
                            entity_kind="symbol",
                            label=loc.symbol.qualified_name,
                            path=loc.path,
                            blob_id=loc.blob_id,
                            symbol_id=loc.symbol.symbol_id,
                            qualified_name=loc.symbol.qualified_name,
                            depth=1,
                        )
                    )
                    chains[endpoint] = (conflict_node_id, endpoint)
                edges.append(
                    ImpactEdge(
                        edge_id=f"edge:conflict:{conflict_node_id}->{endpoint}",
                        kind=ImpactClosureKind.CONFLICT.value,
                        provider_id=conflict_node_id,
                        dependent_id=endpoint,
                        reason=finding.kind,
                        depth=1,
                    )
                )

        elapsed = (time.monotonic() - started) * 1000.0
        self._stats["queries"] += 1
        if truncated:
            self._stats["budget_hits"] += 1
        return ImpactClosure(
            revision_id=graph.revision_id,
            repository_id=graph.repository_id,
            revision=graph.revision,
            kind=ImpactClosureKind.CONFLICT.value,
            seed_ids=tuple(sorted(set(seed_ids))),
            nodes=tuple(nodes),
            edges=tuple(edges),
            chains=chains,
            budget=limits,
            truncated=truncated,
            truncation_reason=reason,
            elapsed_ms=elapsed,
        )

    def list_conflicts(self, revision_id: str) -> tuple[ConflictFinding, ...]:
        graph = self.graph_for_revision(revision_id)
        return tuple(graph.conflicts)

    def symbol_dependency_map(
        self, revision_id: str
    ) -> dict[str, tuple[str, ...]]:
        """Return ``dependent -> providers`` for CodeImpactIndex parity."""

        graph = self.graph_for_revision(revision_id)
        # Remap node ids to qualified names for analyzer agreement.
        qname_deps: dict[str, set[str]] = {}
        for dependent_id, providers in graph.symbol_dependencies.items():
            if dependent_id not in graph.symbols:
                continue
            dependent_qn = graph.symbols[dependent_id].symbol.qualified_name
            for provider_id in providers:
                if provider_id not in graph.symbols:
                    continue
                provider_qn = graph.symbols[provider_id].symbol.qualified_name
                qname_deps.setdefault(dependent_qn, set()).add(provider_qn)
        return {
            key: tuple(sorted(value))
            for key, value in sorted(qname_deps.items())
        }

    def path_dependency_map(
        self, revision_id: str
    ) -> dict[str, tuple[str, ...]]:
        graph = self.graph_for_revision(revision_id)
        return {
            key: tuple(sorted(value))
            for key, value in sorted(graph.path_dependencies.items())
        }

    def impact_symbols(
        self,
        revision_id: str,
        changed_symbols: Sequence[str],
        *,
        budget: ImpactBudget | None = None,
    ) -> ImpactClosure:
        """High-level impact over changed qualified names / aliases."""

        return self.semantic_dependency_closure(
            revision_id, changed_symbols, budget=budget
        )


# ---------------------------------------------------------------------------
# Constructors / descriptors
# ---------------------------------------------------------------------------


def build_duckdb_ast_impact(
    store: DuckDBASTStore | None = None,
    *,
    projections: Sequence[ASTCatalogProjection] | None = None,
) -> DuckDBASTImpact:
    """Construct a :class:`DuckDBASTImpact` query plane."""

    return DuckDBASTImpact(store, projections=projections)


def impact_schema_descriptor() -> dict[str, Any]:
    """Return a deterministic machine-readable impact schema statement."""

    return {
        "interface": DUCKDB_IMPACT_INTERFACE,
        "schema_version": DUCKDB_IMPACT_SCHEMA_VERSION,
        "closure_kinds": sorted(IMPACT_CLOSURE_KINDS),
        "entity_kinds": sorted(IMPACT_ENTITY_KINDS),
        "budgets": {
            "default_max_depth": DEFAULT_MAX_DEPTH,
            "default_max_rows": DEFAULT_MAX_ROWS,
            "default_max_time_ms": DEFAULT_MAX_TIME_MS,
            "hard_max_depth": HARD_MAX_DEPTH,
            "hard_max_rows": HARD_MAX_ROWS,
            "hard_max_time_ms": HARD_MAX_TIME_MS,
        },
        "guarantees": {
            "closures_bind_exact_source_revision": True,
            "depth_row_time_budgets_enforced": True,
            "agrees_with_code_impact_index_on_symbol_deps": True,
            "import_inert": True,
        },
    }


__all__ = [
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_ROWS",
    "DEFAULT_MAX_TIME_MS",
    "DUCKDB_IMPACT_INTERFACE",
    "DUCKDB_IMPACT_SCHEMA_VERSION",
    "HARD_MAX_DEPTH",
    "HARD_MAX_ROWS",
    "HARD_MAX_TIME_MS",
    "IMPACT_CLOSURE_KINDS",
    "IMPACT_ENTITY_KINDS",
    "ConflictFinding",
    "DuckDBASTImpact",
    "DuckDBASTImpactProtocol",
    "DuckDBImpactError",
    "ImpactBudget",
    "ImpactBudgetExceeded",
    "ImpactClosure",
    "ImpactClosureKind",
    "ImpactEdge",
    "ImpactNode",
    "RevisionImpactGraph",
    "bounded_reverse_closure",
    "build_duckdb_ast_impact",
    "build_revision_impact_graph",
    "impact_schema_descriptor",
    "path_to_module",
    "pure_impact_closure",
    "reverse_dependency_map",
]
