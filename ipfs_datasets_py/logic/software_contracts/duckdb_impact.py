"""Bounded AST impact, conflict, and dependency closure queries (DQK-033).

Provides revision-bound reverse-reference, call, import, effect, interface,
semantic-dependency, and conflict closures over the normalized DuckDB ``asts``
catalog projections produced by DQK-031/032.

Used for task scopes, validation selection, and proof invalidation.  Importing
this module is inert — no DuckDB, network, or filesystem I/O.

Closure results and impact selection deliberately agree with the supervisor
:class:`~ipfs_accelerate_py.agent_supervisor.code_evidence_graph.CodeImpactIndex`
analyzer and the datasets code-evidence ``impact_from_index`` helper for the
same symbol/path dependency fixtures.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, Final, Literal

from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
    ASTCatalogProjection,
    DuckDBASTStore,
    DUCKDB_AST_STORE_SCHEMA_VERSION,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

DUCKDB_IMPACT_INTERFACE: Final = "DuckDBImpact@1"
DUCKDB_IMPACT_SCHEMA_VERSION: Final = "duckdb-ast-impact/v1"

# Align result schema identity with the supervisor code-impact plane so
# validation selection and proof invalidation share one vocabulary.
CODE_IMPACT_RESULT_SCHEMA: Final = (
    "ipfs_accelerate_py.agent_supervisor.code-impact-result@1"
)
CODE_IMPACT_INDEX_SCHEMA: Final = (
    "ipfs_accelerate_py.agent_supervisor.code-impact-index@1"
)
CLOSURE_RESULT_SCHEMA: Final = "duckdb-ast-impact-closure/v1"

# Closed closure kind vocabulary (control-plane plan DQK-033).
CLOSURE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "reverse_reference",
        "call",
        "import",
        "effect",
        "interface",
        "semantic_dependency",
        "conflict",
        "impact",
    }
)

# Default and hard budgets.  Depth/row/time limits always apply; callers may
# tighten but never raise the hard caps without a schema bump.
DEFAULT_MAX_DEPTH: Final = 32
DEFAULT_MAX_ROWS: Final = 4_096
DEFAULT_MAX_EDGES: Final = 16_384
DEFAULT_TIME_BUDGET_MS: Final = 5_000

HARD_MAX_DEPTH: Final = 256
HARD_MAX_ROWS: Final = 65_536
HARD_MAX_EDGES: Final = 262_144
HARD_TIME_BUDGET_MS: Final = 60_000

BudgetPolicy = Literal["raise", "truncate"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DuckDBImpactError(ValueError):
    """Raised when an impact/closure query input or state is invalid."""


class DuckDBImpactBudgetError(DuckDBImpactError):
    """Raised when a depth, row, edge, or time budget is exceeded."""

    def __init__(
        self,
        message: str,
        *,
        budget: str,
        actual: int | float,
        limit: int | float,
    ) -> None:
        super().__init__(message)
        self.budget = budget
        self.actual = actual
        self.limit = limit


class DuckDBImpactRevisionError(DuckDBImpactError):
    """Raised when projections are not bound to a single exact revision."""


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


def _repo_path(value: object) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts or "\0" in raw:
        raise DuckDBImpactError(f"unsafe repository impact path: {value!r}")
    return path.as_posix()


def _positive_int(
    value: object,
    field_name: str,
    *,
    minimum: int = 1,
    maximum: int,
) -> int:
    if isinstance(value, bool) or type(value) is not int:
        raise DuckDBImpactError(f"{field_name} must be an exact int")
    if value < minimum:
        raise DuckDBImpactError(
            f"{field_name} must be >= {minimum}, got {value}"
        )
    return min(value, maximum)


def _non_negative_int(
    value: object,
    field_name: str,
    *,
    maximum: int,
) -> int:
    if isinstance(value, bool) or type(value) is not int:
        raise DuckDBImpactError(f"{field_name} must be an exact int")
    if value < 0:
        raise DuckDBImpactError(f"{field_name} must be >= 0, got {value}")
    return min(value, maximum)


def _sorted_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({item for item in values if item}))


def _strings(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    try:
        return _sorted_unique(str(item).strip() for item in value if str(item).strip())
    except TypeError as exc:
        raise DuckDBImpactError("dependency collections must be iterable") from exc


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ImpactBudgets:
    """Hard depth / row / edge / wall-clock budgets for one query.

    Every closure and impact walk enforces these limits.  Defaults are
    deliberately conservative for task-scope and validation-selection use.
    """

    max_depth: int = DEFAULT_MAX_DEPTH
    max_rows: int = DEFAULT_MAX_ROWS
    max_edges: int = DEFAULT_MAX_EDGES
    time_budget_ms: int = DEFAULT_TIME_BUDGET_MS
    on_exceed: BudgetPolicy = "raise"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_depth",
            _non_negative_int(
                self.max_depth, "max_depth", maximum=HARD_MAX_DEPTH
            ),
        )
        object.__setattr__(
            self,
            "max_rows",
            _positive_int(self.max_rows, "max_rows", maximum=HARD_MAX_ROWS),
        )
        object.__setattr__(
            self,
            "max_edges",
            _non_negative_int(
                self.max_edges, "max_edges", maximum=HARD_MAX_EDGES
            ),
        )
        object.__setattr__(
            self,
            "time_budget_ms",
            _positive_int(
                self.time_budget_ms,
                "time_budget_ms",
                maximum=HARD_TIME_BUDGET_MS,
            ),
        )
        if self.on_exceed not in {"raise", "truncate"}:
            raise DuckDBImpactError(
                "on_exceed must be 'raise' or 'truncate'"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_depth": self.max_depth,
            "max_rows": self.max_rows,
            "max_edges": self.max_edges,
            "time_budget_ms": self.time_budget_ms,
            "on_exceed": self.on_exceed,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "ImpactBudgets":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise DuckDBImpactError("budgets must be a mapping")
        return cls(
            max_depth=int(value.get("max_depth", DEFAULT_MAX_DEPTH)),
            max_rows=int(value.get("max_rows", DEFAULT_MAX_ROWS)),
            max_edges=int(value.get("max_edges", DEFAULT_MAX_EDGES)),
            time_budget_ms=int(
                value.get("time_budget_ms", DEFAULT_TIME_BUDGET_MS)
            ),
            on_exceed=str(value.get("on_exceed", "raise")),  # type: ignore[arg-type]
        )


class ImpactClosureKind(StrEnum):
    """Closed vocabulary of supported impact/closure query families."""

    REVERSE_REFERENCE = "reverse_reference"
    CALL = "call"
    IMPORT = "import"
    EFFECT = "effect"
    INTERFACE = "interface"
    SEMANTIC_DEPENDENCY = "semantic_dependency"
    CONFLICT = "conflict"
    IMPACT = "impact"


# ---------------------------------------------------------------------------
# Edge / node models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ImpactEdge:
    """One directed edge in a revision-bound impact graph.

    Orientation is always ``provider -> dependent`` for reverse/impact walks
    (changing a provider selects consumers).  Semantic forward walks flip the
    adjacency at query time.
    """

    edge_id: str
    kind: str
    source: str
    target: str
    path: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "edge_id", _text(self.edge_id, "edge_id"))
        kind = _text(self.kind, "kind")
        if kind not in CLOSURE_KINDS - {"impact"}:
            # impact is a composite query, not an edge family
            if kind not in CLOSURE_KINDS:
                raise DuckDBImpactError(f"unknown impact edge kind: {kind!r}")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "source", _text(self.source, "source"))
        object.__setattr__(self, "target", _text(self.target, "target"))
        if self.path is not None:
            object.__setattr__(self, "path", _repo_path(self.path))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "kind": self.kind,
            "source": self.source,
            "target": self.target,
            "path": self.path,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ClosureResult:
    """Bounded closure outcome for one seed set and edge family."""

    kind: str
    revision_id: str
    direction: str
    seeds: tuple[str, ...]
    node_ids: tuple[str, ...]
    edges: tuple[ImpactEdge, ...]
    paths: Mapping[str, tuple[str, ...]]
    depths: Mapping[str, int]
    budgets: ImpactBudgets
    truncated: bool = False
    truncation_reason: str = ""
    elapsed_ms: float = 0.0

    def __post_init__(self) -> None:
        kind = _text(self.kind, "kind")
        if kind not in CLOSURE_KINDS:
            raise DuckDBImpactError(f"unknown closure kind: {kind!r}")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self, "revision_id", _text(self.revision_id, "revision_id")
        )
        direction = _text(self.direction, "direction")
        if direction not in {"forward", "reverse", "both"}:
            raise DuckDBImpactError(
                f"invalid closure direction: {direction!r}"
            )
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "seeds", tuple(self.seeds))
        object.__setattr__(self, "node_ids", tuple(self.node_ids))
        object.__setattr__(self, "edges", tuple(self.edges))
        object.__setattr__(
            self,
            "paths",
            {str(k): tuple(v) for k, v in dict(self.paths or {}).items()},
        )
        object.__setattr__(
            self,
            "depths",
            {str(k): int(v) for k, v in dict(self.depths or {}).items()},
        )

    @property
    def node_count(self) -> int:
        return len(self.node_ids)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CLOSURE_RESULT_SCHEMA,
            "kind": self.kind,
            "revision_id": self.revision_id,
            "direction": self.direction,
            "seeds": list(self.seeds),
            "node_ids": list(self.node_ids),
            "node_count": self.node_count,
            "edges": [edge.to_dict() for edge in self.edges],
            "edge_count": self.edge_count,
            "paths": {k: list(v) for k, v in sorted(self.paths.items())},
            "depths": dict(sorted(self.depths.items())),
            "budgets": self.budgets.to_dict(),
            "truncated": self.truncated,
            "truncation_reason": self.truncation_reason,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass(frozen=True, slots=True)
class ImpactResult:
    """Complete reverse-dependency impact for one candidate change set.

    Field names and semantics match the supervisor ``CodeImpactResult`` so
    validation-selection and proof-invalidation consumers share one contract.
    """

    revision_id: str
    repository_tree_id: str
    index_id: str
    changed_symbols: tuple[str, ...]
    affected_symbols: tuple[str, ...]
    changed_paths: tuple[str, ...]
    affected_paths: tuple[str, ...]
    dependency_chains: Mapping[str, tuple[str, ...]]
    required_validation_ids: tuple[str, ...]
    validation_reasons: Mapping[str, tuple[str, ...]]
    uncovered_symbols: tuple[str, ...]
    uncovered_paths: tuple[str, ...]
    budgets: ImpactBudgets
    truncated: bool = False
    truncation_reason: str = ""
    elapsed_ms: float = 0.0
    closures: Mapping[str, ClosureResult] = field(default_factory=dict)

    @property
    def uncovered_impact(self) -> bool:
        return bool(self.uncovered_symbols or self.uncovered_paths)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CODE_IMPACT_RESULT_SCHEMA,
            "revision_id": self.revision_id,
            "repository_tree_id": self.repository_tree_id,
            "index_id": self.index_id,
            "changed_symbols": list(self.changed_symbols),
            "affected_symbols": list(self.affected_symbols),
            "changed_paths": list(self.changed_paths),
            "affected_paths": list(self.affected_paths),
            "dependency_chains": {
                key: list(value)
                for key, value in sorted(self.dependency_chains.items())
            },
            "required_validation_ids": list(self.required_validation_ids),
            "validation_reasons": {
                key: list(value)
                for key, value in sorted(self.validation_reasons.items())
            },
            "uncovered_symbols": list(self.uncovered_symbols),
            "uncovered_paths": list(self.uncovered_paths),
            "uncovered_impact": self.uncovered_impact,
            "budgets": self.budgets.to_dict(),
            "truncated": self.truncated,
            "truncation_reason": self.truncation_reason,
            "elapsed_ms": self.elapsed_ms,
            "closures": {
                key: value.to_dict()
                for key, value in sorted(self.closures.items())
            },
        }

    def to_code_impact_dict(self) -> dict[str, Any]:
        """Supervisor-compatible payload without DuckDB impact extensions."""

        payload = self.to_dict()
        for key in (
            "revision_id",
            "budgets",
            "truncated",
            "truncation_reason",
            "elapsed_ms",
            "closures",
        ):
            payload.pop(key, None)
        return payload


# ---------------------------------------------------------------------------
# Index construction from AST projections
# ---------------------------------------------------------------------------


def _symbol_match_keys(name: str) -> tuple[str, ...]:
    """Return lookup keys for a reference/call name against defined symbols."""

    text = name.strip()
    if not text:
        return ()
    keys = {text}
    if "." in text:
        keys.add(text.rsplit(".", 1)[-1])
    return tuple(keys)


def _resolve_symbol(
    name: str,
    *,
    by_qualified: Mapping[str, str],
    by_simple: Mapping[str, tuple[str, ...]],
) -> tuple[str, ...]:
    """Map a reference/call name onto known qualified symbols."""

    keys = _symbol_match_keys(name)
    found: set[str] = set()
    for key in keys:
        if key in by_qualified:
            found.add(key)
        for qualified in by_simple.get(key, ()):
            found.add(qualified)
        # Qualified suffix match: ref "pkg.mod.foo" vs symbol "pkg.mod.foo".
        for qualified in by_qualified:
            if qualified == key or qualified.endswith("." + key):
                found.add(qualified)
    return tuple(sorted(found))


def _scope_owner_map(
    projections: Sequence[ASTCatalogProjection],
) -> dict[tuple[str, str], str]:
    """Map (blob_id, scope_id) → owning symbol qualified_name when known."""

    owners: dict[tuple[str, str], str] = {}
    for projection in projections:
        symbols_by_id = {
            item.symbol_id: item.qualified_name for item in projection.symbols
        }
        for scope in projection.scopes:
            if scope.owner_symbol_id and scope.owner_symbol_id in symbols_by_id:
                owners[(projection.blob_id, scope.scope_id)] = symbols_by_id[
                    scope.owner_symbol_id
                ]
        # Module-level symbols live in the module scope without owner_symbol_id
        # on the scope row; fall back to the defining symbol's own scope.
        for symbol in projection.symbols:
            key = (projection.blob_id, symbol.scope_id)
            owners.setdefault(key, symbol.qualified_name)
    return owners


def _edge_id(kind: str, source: str, target: str, *extra: str) -> str:
    parts = (kind, source, target, *extra)
    return "edge:" + ":".join(parts)


@dataclass(frozen=True, slots=True)
class DuckDBImpactIndex:
    """Revision-bound impact index derived from AST catalog projections.

    All facts are pinned to exactly one ``revision_id``.  Semantic symbol/path
    dependencies use the supervisor orientation ``dependent -> providers``;
    reverse walks invert those edges for impact selection.
    """

    revision_id: str
    repository_id: str
    revision: str
    repository_tree_cid: str | None
    symbol_paths: Mapping[str, str]
    symbol_dependencies: Mapping[str, tuple[str, ...]]
    path_dependencies: Mapping[str, tuple[str, ...]]
    validation_targets: Mapping[str, tuple[str, ...]]
    edges: tuple[ImpactEdge, ...]
    blob_ids: tuple[str, ...]
    paths: tuple[str, ...]
    index_version: str = "duckdb-ast-impact-index-v1"
    schema_version: str = DUCKDB_IMPACT_SCHEMA_VERSION
    store_schema_version: str = DUCKDB_AST_STORE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "revision_id", _text(self.revision_id, "revision_id")
        )
        object.__setattr__(
            self, "repository_id", _text(self.repository_id, "repository_id")
        )
        object.__setattr__(self, "revision", _text(self.revision, "revision"))
        if self.repository_tree_cid is not None:
            object.__setattr__(
                self,
                "repository_tree_cid",
                _text(self.repository_tree_cid, "repository_tree_cid"),
            )
        symbol_paths = {
            _text(symbol, "symbol"): _repo_path(path)
            for symbol, path in dict(self.symbol_paths or {}).items()
        }
        object.__setattr__(
            self, "symbol_paths", dict(sorted(symbol_paths.items()))
        )

        known_symbols = set(symbol_paths)
        symbol_dependencies: dict[str, tuple[str, ...]] = {}
        for dependent, providers in dict(self.symbol_dependencies or {}).items():
            dep = _text(dependent, "symbol dependency dependent")
            prov = _strings(providers)
            unknown = ({dep, *prov} - known_symbols) if known_symbols else set()
            # Allow empty index (no symbols) only when no deps are declared.
            if known_symbols and unknown:
                raise DuckDBImpactError(
                    "symbol dependency references unknown symbols: "
                    + ", ".join(sorted(unknown))
                )
            if dep in prov:
                raise DuckDBImpactError(
                    "symbol dependency cannot reference itself"
                )
            symbol_dependencies[dep] = prov
        object.__setattr__(
            self,
            "symbol_dependencies",
            dict(sorted(symbol_dependencies.items())),
        )

        path_dependencies: dict[str, tuple[str, ...]] = {}
        for dependent, providers in dict(self.path_dependencies or {}).items():
            dep = _repo_path(dependent)
            prov = tuple(sorted({_repo_path(item) for item in _strings(providers)}))
            if dep in prov:
                raise DuckDBImpactError(
                    "path dependency cannot reference itself"
                )
            path_dependencies[dep] = prov
        object.__setattr__(
            self, "path_dependencies", dict(sorted(path_dependencies.items()))
        )

        targets: dict[str, tuple[str, ...]] = {}
        known_paths = set(symbol_paths.values())
        known_paths.update(path_dependencies)
        for deps in path_dependencies.values():
            known_paths.update(deps)
        known_targets = known_symbols | known_paths
        for validation_id, raw_targets in dict(
            self.validation_targets or {}
        ).items():
            vid = _text(validation_id, "validation_id")
            values = _strings(raw_targets)
            if not values:
                raise DuckDBImpactError(
                    f"validation {vid!r} has no impact targets"
                )
            if known_targets:
                unknown = set(values) - known_targets
                if unknown:
                    raise DuckDBImpactError(
                        "validation references unknown impact targets: "
                        + ", ".join(sorted(unknown))
                    )
            targets[vid] = values
        object.__setattr__(
            self, "validation_targets", dict(sorted(targets.items()))
        )

        edges = tuple(self.edges)
        for edge in edges:
            if type(edge) is not ImpactEdge:
                raise DuckDBImpactError("edges must be ImpactEdge instances")
        object.__setattr__(self, "edges", edges)
        object.__setattr__(self, "blob_ids", tuple(self.blob_ids))
        object.__setattr__(
            self,
            "paths",
            tuple(sorted({_repo_path(item) for item in self.paths})),
        )

    @property
    def index_id(self) -> str:
        """Stable content identity for the index payload."""

        payload = self.to_code_impact_index_dict()
        # Avoid importing content module cycles; use a deterministic digest.
        import hashlib
        import json

        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return "impact-sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @property
    def repository_tree_id(self) -> str:
        return self.repository_tree_cid or self.revision_id

    def edges_for_kind(self, kind: str) -> tuple[ImpactEdge, ...]:
        kind_text = _text(kind, "kind")
        return tuple(edge for edge in self.edges if edge.kind == kind_text)

    def reverse_adjacency(
        self, kind: str | None = None
    ) -> dict[str, tuple[str, ...]]:
        """provider -> dependents for the selected edge family (or all)."""

        reverse: dict[str, set[str]] = defaultdict(set)
        for edge in self.edges:
            if kind is not None and edge.kind != kind:
                continue
            reverse[edge.source].add(edge.target)
        # Also include semantic symbol/path deps (dependent -> providers)
        # inverted into provider -> dependents when kind is semantic or impact.
        if kind in (None, "semantic_dependency", "impact"):
            for dependent, providers in self.symbol_dependencies.items():
                for provider in providers:
                    reverse[provider].add(dependent)
            for dependent, providers in self.path_dependencies.items():
                for provider in providers:
                    reverse[provider].add(dependent)
        return {
            key: tuple(sorted(value)) for key, value in sorted(reverse.items())
        }

    def forward_adjacency(
        self, kind: str | None = None
    ) -> dict[str, tuple[str, ...]]:
        """dependent -> providers (semantic dependency orientation)."""

        forward: dict[str, set[str]] = defaultdict(set)
        for edge in self.edges:
            if kind is not None and edge.kind != kind:
                continue
            # Edges are stored provider -> dependent; invert for forward.
            forward[edge.target].add(edge.source)
        if kind in (None, "semantic_dependency", "impact"):
            for dependent, providers in self.symbol_dependencies.items():
                forward[dependent].update(providers)
            for dependent, providers in self.path_dependencies.items():
                forward[dependent].update(providers)
        return {
            key: tuple(sorted(value)) for key, value in sorted(forward.items())
        }

    def to_code_impact_index_dict(self) -> dict[str, Any]:
        """Supervisor ``CodeImpactIndex``-compatible payload."""

        return {
            "schema": CODE_IMPACT_INDEX_SCHEMA,
            "repository_tree_id": self.repository_tree_id,
            "index_version": self.index_version,
            "symbol_paths": dict(self.symbol_paths),
            "symbol_dependencies": {
                key: list(value)
                for key, value in self.symbol_dependencies.items()
            },
            "path_dependencies": {
                key: list(value)
                for key, value in self.path_dependencies.items()
            },
            "validation_targets": {
                key: list(value)
                for key, value in self.validation_targets.items()
            },
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DUCKDB_IMPACT_SCHEMA_VERSION,
            "interface": DUCKDB_IMPACT_INTERFACE,
            "revision_id": self.revision_id,
            "repository_id": self.repository_id,
            "revision": self.revision,
            "repository_tree_cid": self.repository_tree_cid,
            "index_id": self.index_id,
            "index_version": self.index_version,
            "store_schema_version": self.store_schema_version,
            "symbol_paths": dict(self.symbol_paths),
            "symbol_dependencies": {
                key: list(value)
                for key, value in self.symbol_dependencies.items()
            },
            "path_dependencies": {
                key: list(value)
                for key, value in self.path_dependencies.items()
            },
            "validation_targets": {
                key: list(value)
                for key, value in self.validation_targets.items()
            },
            "blob_ids": list(self.blob_ids),
            "paths": list(self.paths),
            "edge_count": len(self.edges),
            "edges": [edge.to_dict() for edge in self.edges],
        }


def build_impact_index_from_projections(
    projections: Sequence[ASTCatalogProjection],
    *,
    symbol_dependencies: Mapping[str, Sequence[str]] | None = None,
    path_dependencies: Mapping[str, Sequence[str]] | None = None,
    validation_targets: Mapping[str, Sequence[str]] | None = None,
    conflict_surfaces: Sequence[Mapping[str, Any]] | None = None,
    require_non_empty: bool = True,
) -> DuckDBImpactIndex:
    """Build a revision-bound impact index from AST catalog projections.

    All projections must share the same ``source_revision.revision_id``.
    Explicit semantic dependency maps are merged with edges inferred from
    references, calls, imports, effects, and interfaces.
    """

    if require_non_empty and not projections:
        raise DuckDBImpactError(
            "impact index requires at least one AST catalog projection"
        )
    if not projections:
        raise DuckDBImpactError(
            "empty projection set cannot bind an exact source revision"
        )

    revision_ids = {
        projection.source_revision.revision_id for projection in projections
    }
    if len(revision_ids) != 1:
        raise DuckDBImpactRevisionError(
            "impact closures must bind an exact source revision; got "
            f"{sorted(revision_ids)!r}"
        )
    first = projections[0].source_revision
    revision_id = first.revision_id
    repository_id = first.repository_id
    revision = first.revision
    repository_tree_cid = first.repository_tree_cid

    # Reject cross-revision leakage even if revision_id strings collide oddly.
    for projection in projections:
        rev = projection.source_revision
        if rev.repository_id != repository_id or rev.revision != revision:
            raise DuckDBImpactRevisionError(
                "projection repository/revision identity mismatch inside "
                f"revision_id={revision_id!r}"
            )

    symbol_paths: dict[str, str] = {}
    by_simple: dict[str, list[str]] = defaultdict(list)
    edges: list[ImpactEdge] = []
    blob_ids: list[str] = []
    paths: list[str] = []
    scope_owners = _scope_owner_map(projections)

    for projection in projections:
        path = _repo_path(projection.source_file.path)
        paths.append(path)
        blob_ids.append(projection.blob_id)
        for symbol in projection.symbols:
            previous = symbol_paths.get(symbol.qualified_name)
            if previous is not None and previous != path:
                raise DuckDBImpactError(
                    f"symbol {symbol.qualified_name!r} is defined by "
                    f"multiple paths: {previous!r} and {path!r}"
                )
            symbol_paths[symbol.qualified_name] = path
            by_simple[symbol.name].append(symbol.qualified_name)

    by_qualified = dict(symbol_paths)
    simple_map = {
        name: tuple(sorted(set(values))) for name, values in by_simple.items()
    }

    # Inferred semantic symbol deps from references/calls/imports.
    inferred_symbol_deps: dict[str, set[str]] = defaultdict(set)
    inferred_path_deps: dict[str, set[str]] = defaultdict(set)

    for projection in projections:
        path = _repo_path(projection.source_file.path)
        module_name = ""
        for node in projection.nodes:
            if node.node_kind == "module":
                module_name = node.label
                break

        # --- reverse references: provider symbol -> referencing owner ---
        for ref in projection.references:
            targets = _resolve_symbol(
                ref.name, by_qualified=by_qualified, by_simple=simple_map
            )
            owner = scope_owners.get((projection.blob_id, ref.scope_id))
            dependent = owner or f"ref:{path}:{ref.reference_id}"
            for provider in targets:
                if provider == dependent:
                    continue
                edges.append(
                    ImpactEdge(
                        edge_id=_edge_id(
                            "reverse_reference",
                            provider,
                            dependent,
                            ref.reference_id,
                        ),
                        kind="reverse_reference",
                        source=provider,
                        target=dependent,
                        path=path,
                        metadata={
                            "reference_id": ref.reference_id,
                            "name": ref.name,
                            "context": ref.context,
                        },
                    )
                )
                if owner and owner in symbol_paths and provider in symbol_paths:
                    inferred_symbol_deps[owner].add(provider)
                    provider_path = symbol_paths[provider]
                    if provider_path != path:
                        inferred_path_deps[path].add(provider_path)

        # --- call: callee symbol -> calling owner ---
        for call in projection.calls:
            targets = _resolve_symbol(
                call.callee_name,
                by_qualified=by_qualified,
                by_simple=simple_map,
            )
            owner = scope_owners.get((projection.blob_id, call.scope_id))
            dependent = owner or f"call:{path}:{call.call_id}"
            for provider in targets:
                if provider == dependent:
                    continue
                edges.append(
                    ImpactEdge(
                        edge_id=_edge_id(
                            "call", provider, dependent, call.call_id
                        ),
                        kind="call",
                        source=provider,
                        target=dependent,
                        path=path,
                        metadata={
                            "call_id": call.call_id,
                            "callee_name": call.callee_name,
                            "kind": call.kind,
                            "is_awaited": call.is_awaited,
                        },
                    )
                )
                if owner and owner in symbol_paths and provider in symbol_paths:
                    inferred_symbol_deps[owner].add(provider)
                    provider_path = symbol_paths[provider]
                    if provider_path != path:
                        inferred_path_deps[path].add(provider_path)

        # --- import: imported module/name -> importing path ---
        for item in projection.imports:
            module_key = item.module
            imported = (
                f"{item.module}.{item.imported_name}"
                if item.imported_name
                else item.module
            )
            for provider in (module_key, imported):
                edges.append(
                    ImpactEdge(
                        edge_id=_edge_id(
                            "import", provider, path, item.import_id
                        ),
                        kind="import",
                        source=provider,
                        target=path,
                        path=path,
                        metadata={
                            "import_id": item.import_id,
                            "module": item.module,
                            "imported_name": item.imported_name,
                            "local_name": item.local_name,
                            "kind": item.kind,
                        },
                    )
                )
            # Module-name path heuristic: "pkg.mod" -> "pkg/mod.py"
            module_path_guess = item.module.replace(".", "/") + ".py"
            if module_path_guess in {p for p in paths}:
                inferred_path_deps[path].add(module_path_guess)
            # Cross-file symbol import: imported symbol becomes a dependency.
            for symbol, symbol_path in symbol_paths.items():
                simple = symbol.rsplit(".", 1)[-1]
                if item.imported_name and simple == item.imported_name:
                    if module_name and symbol.startswith(item.module):
                        owner_symbols = [
                            s.qualified_name
                            for s in projection.symbols
                            if s.scope_id == item.scope_id
                            or s.kind == "module"
                        ]
                        for owner in owner_symbols or [f"module:{path}"]:
                            if owner in symbol_paths:
                                inferred_symbol_deps[owner].add(symbol)
                        if symbol_path != path:
                            inferred_path_deps[path].add(symbol_path)

        # --- effect: subject -> effect owner/path ---
        for effect in projection.effects:
            subject = effect.subject or effect.kind
            if not subject:
                continue
            owner = scope_owners.get((projection.blob_id, effect.scope_id))
            dependent = owner or path
            edges.append(
                ImpactEdge(
                    edge_id=_edge_id(
                        "effect", subject, dependent, effect.effect_id
                    ),
                    kind="effect",
                    source=subject,
                    target=dependent,
                    path=path,
                    metadata={
                        "effect_id": effect.effect_id,
                        "kind": effect.kind,
                        "operation": effect.operation,
                        "subject": effect.subject,
                    },
                )
            )
            # If subject resolves to a symbol, also record symbol impact edge.
            for provider in _resolve_symbol(
                subject, by_qualified=by_qualified, by_simple=simple_map
            ):
                if provider == dependent:
                    continue
                edges.append(
                    ImpactEdge(
                        edge_id=_edge_id(
                            "effect",
                            provider,
                            dependent,
                            effect.effect_id,
                            "symbol",
                        ),
                        kind="effect",
                        source=provider,
                        target=dependent,
                        path=path,
                        metadata={
                            "effect_id": effect.effect_id,
                            "resolved_symbol": provider,
                        },
                    )
                )

        # --- interface: interface symbol -> consumers via name match ---
        for interface in projection.interfaces:
            provider = interface.qualified_name
            # Self edge not useful; consumers come from other projections.
            edges.append(
                ImpactEdge(
                    edge_id=_edge_id(
                        "interface",
                        provider,
                        path,
                        interface.interface_id,
                        "def",
                    ),
                    kind="interface",
                    source=provider,
                    target=path,
                    path=path,
                    metadata={
                        "interface_id": interface.interface_id,
                        "kind": interface.kind,
                        "signature_text": interface.signature_text,
                        "role": "definition",
                    },
                )
            )

    # Second pass: interface consumers (references/calls to interface names).
    interface_names = {
        edge.source
        for edge in edges
        if edge.kind == "interface"
        and edge.metadata.get("role") == "definition"
    }
    for projection in projections:
        path = _repo_path(projection.source_file.path)
        for ref in projection.references:
            for provider in interface_names:
                if ref.name == provider or provider.endswith("." + ref.name):
                    owner = scope_owners.get(
                        (projection.blob_id, ref.scope_id)
                    ) or path
                    edges.append(
                        ImpactEdge(
                            edge_id=_edge_id(
                                "interface",
                                provider,
                                owner,
                                ref.reference_id,
                                "use",
                            ),
                            kind="interface",
                            source=provider,
                            target=owner,
                            path=path,
                            metadata={
                                "role": "use",
                                "reference_id": ref.reference_id,
                            },
                        )
                    )
        for call in projection.calls:
            for provider in interface_names:
                if call.callee_name == provider or provider.endswith(
                    "." + call.callee_name
                ):
                    owner = scope_owners.get(
                        (projection.blob_id, call.scope_id)
                    ) or path
                    edges.append(
                        ImpactEdge(
                            edge_id=_edge_id(
                                "interface",
                                provider,
                                owner,
                                call.call_id,
                                "call",
                            ),
                            kind="interface",
                            source=provider,
                            target=owner,
                            path=path,
                            metadata={
                                "role": "call",
                                "call_id": call.call_id,
                            },
                        )
                    )

    # --- conflict surfaces: shared symbols/paths co-occur ---
    for surface in conflict_surfaces or ():
        if not isinstance(surface, Mapping):
            raise DuckDBImpactError("conflict_surfaces items must be mappings")
        task_id = _text(
            surface.get("task_cid")
            or surface.get("task_id")
            or surface.get("id")
            or "task",
            "conflict task id",
        )
        surface_paths = [
            _repo_path(item)
            for item in (
                list(surface.get("paths") or ())
                + list(surface.get("changed_paths") or ())
                + list(surface.get("files") or ())
            )
            if str(item).strip()
        ]
        surface_symbols = [
            _text(item, "conflict symbol")
            for item in (
                list(surface.get("ast_symbols") or ())
                + list(surface.get("symbols") or ())
            )
            if str(item).strip()
        ]
        for path in surface_paths:
            edges.append(
                ImpactEdge(
                    edge_id=_edge_id("conflict", path, task_id, "path"),
                    kind="conflict",
                    source=path,
                    target=task_id,
                    path=path,
                    metadata={"surface": "path"},
                )
            )
        for symbol in surface_symbols:
            edges.append(
                ImpactEdge(
                    edge_id=_edge_id("conflict", symbol, task_id, "symbol"),
                    kind="conflict",
                    source=symbol,
                    target=task_id,
                    path=symbol_paths.get(symbol),
                    metadata={"surface": "symbol"},
                )
            )

    # Merge explicit + inferred semantic dependencies.
    merged_symbol_deps: dict[str, set[str]] = {
        key: set(value) for key, value in inferred_symbol_deps.items()
    }
    for dependent, providers in dict(symbol_dependencies or {}).items():
        merged_symbol_deps.setdefault(str(dependent), set()).update(
            _strings(providers)
        )
    merged_path_deps: dict[str, set[str]] = {
        key: set(value) for key, value in inferred_path_deps.items()
    }
    for dependent, providers in dict(path_dependencies or {}).items():
        merged_path_deps.setdefault(_repo_path(dependent), set()).update(
            _repo_path(item) for item in _strings(providers)
        )

    # Deduplicate edges by edge_id (stable first-wins).
    seen_ids: set[str] = set()
    unique_edges: list[ImpactEdge] = []
    for edge in sorted(
        edges, key=lambda item: (item.kind, item.source, item.target, item.edge_id)
    ):
        if edge.edge_id in seen_ids:
            continue
        seen_ids.add(edge.edge_id)
        unique_edges.append(edge)

    return DuckDBImpactIndex(
        revision_id=revision_id,
        repository_id=repository_id,
        revision=revision,
        repository_tree_cid=repository_tree_cid,
        symbol_paths=symbol_paths,
        symbol_dependencies={
            key: tuple(sorted(value))
            for key, value in sorted(merged_symbol_deps.items())
            if value
        },
        path_dependencies={
            key: tuple(sorted(value))
            for key, value in sorted(merged_path_deps.items())
            if value
        },
        validation_targets={
            str(key): _strings(value)
            for key, value in dict(validation_targets or {}).items()
        },
        edges=tuple(unique_edges),
        blob_ids=tuple(blob_ids),
        paths=tuple(sorted(set(paths))),
    )


def build_impact_index_from_maps(
    *,
    revision_id: str,
    repository_id: str,
    revision: str,
    repository_tree_cid: str | None = None,
    symbol_paths: Mapping[str, str],
    symbol_dependencies: Mapping[str, Sequence[str]] | None = None,
    path_dependencies: Mapping[str, Sequence[str]] | None = None,
    validation_targets: Mapping[str, Sequence[str]] | None = None,
    edges: Sequence[ImpactEdge] = (),
) -> DuckDBImpactIndex:
    """Build an index from explicit maps (for analyzer agreement fixtures)."""

    paths = sorted(set(symbol_paths.values()))
    return DuckDBImpactIndex(
        revision_id=_text(revision_id, "revision_id"),
        repository_id=_text(repository_id, "repository_id"),
        revision=_text(revision, "revision"),
        repository_tree_cid=repository_tree_cid,
        symbol_paths=symbol_paths,
        symbol_dependencies=dict(symbol_dependencies or {}),
        path_dependencies=dict(path_dependencies or {}),
        validation_targets=dict(validation_targets or {}),
        edges=tuple(edges),
        blob_ids=(),
        paths=tuple(paths),
    )


# ---------------------------------------------------------------------------
# Bounded BFS closure
# ---------------------------------------------------------------------------


def _check_time(started: float, budgets: ImpactBudgets) -> None:
    elapsed_ms = (time.monotonic() - started) * 1000.0
    if elapsed_ms > budgets.time_budget_ms:
        raise DuckDBImpactBudgetError(
            f"time_budget_ms exceeded ({elapsed_ms:.1f} > {budgets.time_budget_ms})",
            budget="time_budget_ms",
            actual=elapsed_ms,
            limit=budgets.time_budget_ms,
        )


def bounded_closure(
    *,
    seeds: Iterable[str],
    adjacency: Mapping[str, Sequence[str]],
    revision_id: str,
    kind: str,
    direction: str,
    budgets: ImpactBudgets | None = None,
    edge_lookup: Mapping[tuple[str, str], ImpactEdge] | None = None,
) -> ClosureResult:
    """Deterministic BFS closure with depth/row/edge/time budgets."""

    limits = budgets or ImpactBudgets()
    kind_text = _text(kind, "kind")
    if kind_text not in CLOSURE_KINDS:
        raise DuckDBImpactError(f"unknown closure kind: {kind_text!r}")
    direction_text = _text(direction, "direction")
    if direction_text not in {"forward", "reverse", "both"}:
        raise DuckDBImpactError(f"invalid direction: {direction_text!r}")

    normalized_seeds = _sorted_unique(
        _text(item, "seed") for item in seeds if str(item).strip()
    )
    if not normalized_seeds:
        raise DuckDBImpactError("closure requires at least one seed")

    started = time.monotonic()
    paths: dict[str, tuple[str, ...]] = {
        seed: (seed,) for seed in normalized_seeds
    }
    depths: dict[str, int] = {seed: 0 for seed in normalized_seeds}
    visited: set[str] = set(normalized_seeds)
    included_edges: list[ImpactEdge] = []
    seen_edge_keys: set[tuple[str, str]] = set()
    queue: deque[str] = deque(normalized_seeds)
    truncated = False
    truncation_reason = ""

    def exceed(budget: str, actual: int | float, limit: int | float) -> bool:
        nonlocal truncated, truncation_reason
        if limits.on_exceed == "truncate":
            truncated = True
            truncation_reason = budget
            return True
        raise DuckDBImpactBudgetError(
            f"{budget} exceeded ({actual} > {limit})",
            budget=budget,
            actual=actual,
            limit=limit,
        )

    while queue:
        try:
            _check_time(started, limits)
        except DuckDBImpactBudgetError:
            if limits.on_exceed == "truncate":
                truncated = True
                truncation_reason = "time_budget_ms"
                break
            raise

        current = queue.popleft()
        if depths[current] >= limits.max_depth:
            # Depth budget stops expansion from this node (not an error unless
            # there are pending deeper nodes that would need to expand).
            continue
        for neighbor in adjacency.get(current, ()):
            edge_key = (current, neighbor)
            if edge_key not in seen_edge_keys:
                if len(seen_edge_keys) >= limits.max_edges:
                    if exceed("max_edges", len(seen_edge_keys) + 1, limits.max_edges):
                        break
                seen_edge_keys.add(edge_key)
                if edge_lookup and edge_key in edge_lookup:
                    included_edges.append(edge_lookup[edge_key])
                else:
                    included_edges.append(
                        ImpactEdge(
                            edge_id=_edge_id(kind_text, current, neighbor),
                            kind=(
                                kind_text
                                if kind_text != "impact"
                                else "semantic_dependency"
                            ),
                            source=current,
                            target=neighbor,
                        )
                    )
            candidate = (*paths[current], neighbor)
            existing = paths.get(neighbor)
            depth = depths[current] + 1
            if existing is None:
                if len(visited) >= limits.max_rows:
                    if exceed("max_rows", len(visited) + 1, limits.max_rows):
                        break
                visited.add(neighbor)
                paths[neighbor] = candidate
                depths[neighbor] = depth
                queue.append(neighbor)
            elif (len(candidate), candidate) < (len(existing), existing):
                paths[neighbor] = candidate
                depths[neighbor] = depth
        else:
            continue
        # inner break from edge/row budget truncation
        if truncated:
            break

    # If seeds alone exceed max_rows (pathological), fail closed / truncate.
    if len(normalized_seeds) > limits.max_rows:
        if limits.on_exceed == "raise":
            raise DuckDBImpactBudgetError(
                f"max_rows exceeded by seeds ({len(normalized_seeds)} > "
                f"{limits.max_rows})",
                budget="max_rows",
                actual=len(normalized_seeds),
                limit=limits.max_rows,
            )
        truncated = True
        truncation_reason = truncation_reason or "max_rows"
        kept = normalized_seeds[: limits.max_rows]
        visited = set(kept)
        paths = {seed: (seed,) for seed in kept}
        depths = {seed: 0 for seed in kept}

    elapsed_ms = (time.monotonic() - started) * 1000.0
    return ClosureResult(
        kind=kind_text,
        revision_id=_text(revision_id, "revision_id"),
        direction=direction_text,
        seeds=normalized_seeds,
        node_ids=tuple(sorted(visited)),
        edges=tuple(included_edges),
        paths=paths,
        depths=depths,
        budgets=limits,
        truncated=truncated,
        truncation_reason=truncation_reason,
        elapsed_ms=elapsed_ms,
    )


# ---------------------------------------------------------------------------
# Query engine
# ---------------------------------------------------------------------------


class DuckDBImpactEngine:
    """Revision-bound impact and closure query surface (DuckDBImpact@1)."""

    def __init__(
        self,
        index: DuckDBImpactIndex,
        *,
        default_budgets: ImpactBudgets | None = None,
    ) -> None:
        if type(index) is not DuckDBImpactIndex:
            raise DuckDBImpactError(
                "DuckDBImpactEngine requires an exact DuckDBImpactIndex"
            )
        self._index = index
        self._default_budgets = default_budgets or ImpactBudgets()

    @property
    def interface(self) -> str:
        return DUCKDB_IMPACT_INTERFACE

    @property
    def schema_version(self) -> str:
        return DUCKDB_IMPACT_SCHEMA_VERSION

    @property
    def index(self) -> DuckDBImpactIndex:
        return self._index

    @property
    def revision_id(self) -> str:
        return self._index.revision_id

    def _budgets(self, budgets: ImpactBudgets | Mapping[str, Any] | None) -> ImpactBudgets:
        if budgets is None:
            return self._default_budgets
        if type(budgets) is ImpactBudgets:
            return budgets
        if isinstance(budgets, Mapping):
            return ImpactBudgets.from_mapping(budgets)
        raise DuckDBImpactError("budgets must be ImpactBudgets or a mapping")

    def _edge_lookup(self, kind: str | None = None) -> dict[tuple[str, str], ImpactEdge]:
        lookup: dict[tuple[str, str], ImpactEdge] = {}
        for edge in self._index.edges:
            if kind is not None and edge.kind != kind:
                continue
            lookup.setdefault((edge.source, edge.target), edge)
        return lookup

    def closure(
        self,
        kind: str | ImpactClosureKind,
        seeds: Iterable[str],
        *,
        direction: str = "reverse",
        budgets: ImpactBudgets | Mapping[str, Any] | None = None,
    ) -> ClosureResult:
        """Run a bounded closure of the requested kind from ``seeds``."""

        kind_text = kind.value if isinstance(kind, ImpactClosureKind) else _text(kind, "kind")
        if kind_text not in CLOSURE_KINDS:
            raise DuckDBImpactError(f"unknown closure kind: {kind_text!r}")
        if kind_text == "impact":
            raise DuckDBImpactError(
                "use impact() for composite impact selection; "
                "closure(kind='impact') is not supported"
            )
        limits = self._budgets(budgets)
        direction_text = _text(direction, "direction")

        if kind_text == "semantic_dependency":
            if direction_text == "forward":
                adjacency = self._index.forward_adjacency("semantic_dependency")
            elif direction_text == "reverse":
                adjacency = self._index.reverse_adjacency("semantic_dependency")
            else:
                # both: undirected union
                rev = self._index.reverse_adjacency("semantic_dependency")
                fwd = self._index.forward_adjacency("semantic_dependency")
                merged: dict[str, set[str]] = defaultdict(set)
                for mapping in (rev, fwd):
                    for key, values in mapping.items():
                        merged[key].update(values)
                adjacency = {
                    key: tuple(sorted(value))
                    for key, value in sorted(merged.items())
                }
            edge_lookup = None
        else:
            if direction_text == "forward":
                # Stored edges are provider->dependent; forward walks dependents
                # toward providers by inverting.
                adjacency = self._index.forward_adjacency(kind_text)
            elif direction_text == "reverse":
                adjacency = self._index.reverse_adjacency(kind_text)
            else:
                rev = self._index.reverse_adjacency(kind_text)
                fwd = self._index.forward_adjacency(kind_text)
                merged = defaultdict(set)
                for mapping in (rev, fwd):
                    for key, values in mapping.items():
                        merged[key].update(values)
                adjacency = {
                    key: tuple(sorted(value))
                    for key, value in sorted(merged.items())
                }
            edge_lookup = self._edge_lookup(kind_text)

        return bounded_closure(
            seeds=seeds,
            adjacency=adjacency,
            revision_id=self._index.revision_id,
            kind=kind_text,
            direction=direction_text,
            budgets=limits,
            edge_lookup=edge_lookup,
        )

    def reverse_reference_closure(
        self,
        seeds: Iterable[str],
        *,
        budgets: ImpactBudgets | Mapping[str, Any] | None = None,
    ) -> ClosureResult:
        return self.closure(
            ImpactClosureKind.REVERSE_REFERENCE,
            seeds,
            direction="reverse",
            budgets=budgets,
        )

    def call_closure(
        self,
        seeds: Iterable[str],
        *,
        budgets: ImpactBudgets | Mapping[str, Any] | None = None,
    ) -> ClosureResult:
        return self.closure(
            ImpactClosureKind.CALL, seeds, direction="reverse", budgets=budgets
        )

    def import_closure(
        self,
        seeds: Iterable[str],
        *,
        budgets: ImpactBudgets | Mapping[str, Any] | None = None,
    ) -> ClosureResult:
        return self.closure(
            ImpactClosureKind.IMPORT, seeds, direction="reverse", budgets=budgets
        )

    def effect_closure(
        self,
        seeds: Iterable[str],
        *,
        budgets: ImpactBudgets | Mapping[str, Any] | None = None,
    ) -> ClosureResult:
        return self.closure(
            ImpactClosureKind.EFFECT, seeds, direction="reverse", budgets=budgets
        )

    def interface_closure(
        self,
        seeds: Iterable[str],
        *,
        budgets: ImpactBudgets | Mapping[str, Any] | None = None,
    ) -> ClosureResult:
        return self.closure(
            ImpactClosureKind.INTERFACE,
            seeds,
            direction="reverse",
            budgets=budgets,
        )

    def semantic_dependency_closure(
        self,
        seeds: Iterable[str],
        *,
        direction: str = "forward",
        budgets: ImpactBudgets | Mapping[str, Any] | None = None,
    ) -> ClosureResult:
        return self.closure(
            ImpactClosureKind.SEMANTIC_DEPENDENCY,
            seeds,
            direction=direction,
            budgets=budgets,
        )

    def conflict_closure(
        self,
        seeds: Iterable[str],
        *,
        budgets: ImpactBudgets | Mapping[str, Any] | None = None,
    ) -> ClosureResult:
        return self.closure(
            ImpactClosureKind.CONFLICT,
            seeds,
            direction="reverse",
            budgets=budgets,
        )

    def impact(
        self,
        *,
        changed_symbols: Iterable[str] = (),
        changed_paths: Iterable[str] = (),
        budgets: ImpactBudgets | Mapping[str, Any] | None = None,
        include_ast_closures: bool = True,
    ) -> ImpactResult:
        """Compute reverse dependency impact for changed symbols/paths.

        Agrees with supervisor ``CodeImpactIndex.impact`` on the same
        symbol/path dependency fixtures.  Optionally attaches bounded AST
        family closures (references, calls, imports, effects, interfaces)
        for task-scope and proof-invalidation consumers.
        """

        limits = self._budgets(budgets)
        started = time.monotonic()
        index = self._index

        explicit_symbols = {
            _text(item, "changed symbol")
            for item in changed_symbols
            if str(item).strip()
        }
        explicit_paths = {
            _repo_path(item)
            for item in changed_paths
            if str(item).strip()
        }
        inferred_symbols = {
            symbol
            for symbol, path in index.symbol_paths.items()
            if path in explicit_paths
        }
        known_changed_symbols = (explicit_symbols | inferred_symbols) & set(
            index.symbol_paths
        )
        uncovered_symbols = tuple(
            sorted(explicit_symbols - set(index.symbol_paths))
        )

        # Reverse maps matching CodeImpactIndex orientation.
        rev_symbols: dict[str, list[str]] = defaultdict(list)
        for dependent, providers in index.symbol_dependencies.items():
            for provider in providers:
                rev_symbols[provider].append(dependent)
        for provider, dependents in rev_symbols.items():
            rev_symbols[provider] = sorted(set(dependents))

        rev_paths: dict[str, list[str]] = defaultdict(list)
        for dependent, providers in index.path_dependencies.items():
            for provider in providers:
                rev_paths[provider].append(dependent)
        for provider, dependents in rev_paths.items():
            rev_paths[provider] = sorted(set(dependents))

        def _closure_with_chains(
            roots: Iterable[str],
            reverse: Mapping[str, Sequence[str]],
        ) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]], bool, str]:
            normalized_roots = tuple(sorted(set(roots)))
            chains: dict[str, tuple[str, ...]] = {
                root: (root,) for root in normalized_roots
            }
            queue = deque(normalized_roots)
            truncated_local = False
            reason = ""
            while queue:
                try:
                    _check_time(started, limits)
                except DuckDBImpactBudgetError:
                    if limits.on_exceed == "truncate":
                        truncated_local = True
                        reason = "time_budget_ms"
                        break
                    raise
                current = queue.popleft()
                depth = len(chains[current]) - 1
                if depth >= limits.max_depth:
                    continue
                for dependent in reverse.get(current, ()):
                    candidate = (*chains[current], dependent)
                    existing = chains.get(dependent)
                    if existing is None:
                        if len(chains) >= limits.max_rows:
                            if limits.on_exceed == "truncate":
                                truncated_local = True
                                reason = "max_rows"
                                queue.clear()
                                break
                            raise DuckDBImpactBudgetError(
                                f"max_rows exceeded ({len(chains) + 1} > "
                                f"{limits.max_rows})",
                                budget="max_rows",
                                actual=len(chains) + 1,
                                limit=limits.max_rows,
                            )
                        chains[dependent] = candidate
                        queue.append(dependent)
                    elif (len(candidate), candidate) < (
                        len(existing),
                        existing,
                    ):
                        chains[dependent] = candidate
                        queue.append(dependent)
            return tuple(sorted(chains)), chains, truncated_local, reason

        affected_symbols, symbol_chains, trunc_s, reason_s = _closure_with_chains(
            known_changed_symbols, rev_symbols
        )
        symbol_affected_paths = {
            index.symbol_paths[symbol]
            for symbol in affected_symbols
            if symbol in index.symbol_paths
        }
        path_roots = explicit_paths | symbol_affected_paths
        known_paths = set(index.symbol_paths.values())
        known_paths.update(index.path_dependencies)
        for deps in index.path_dependencies.values():
            known_paths.update(deps)
        uncovered_paths = tuple(sorted(explicit_paths - known_paths))
        affected_paths, path_chains, trunc_p, reason_p = _closure_with_chains(
            path_roots, rev_paths
        )

        impacted_targets = set(affected_symbols) | set(affected_paths)
        validation_reasons = {
            validation_id: tuple(
                sorted(impacted_targets.intersection(targets))
            )
            for validation_id, targets in index.validation_targets.items()
            if impacted_targets.intersection(targets)
        }
        chains: dict[str, tuple[str, ...]] = dict(symbol_chains)
        for target, chain in path_chains.items():
            chains.setdefault(target, chain)

        truncated = trunc_s or trunc_p
        truncation_reason = reason_s or reason_p

        closures: dict[str, ClosureResult] = {}
        if include_ast_closures and (known_changed_symbols or explicit_paths):
            seed_symbols = tuple(
                sorted(known_changed_symbols | set(affected_symbols))
            )
            seed_paths = tuple(sorted(set(affected_paths) | explicit_paths))
            family_seeds = tuple(
                sorted(set(seed_symbols) | set(seed_paths) | explicit_symbols)
            )
            if family_seeds:
                for family in (
                    "reverse_reference",
                    "call",
                    "import",
                    "effect",
                    "interface",
                ):
                    # Only expand when the family has edges; empty adjacency
                    # still returns the seeds under reverse walk.
                    try:
                        closures[family] = self.closure(
                            family,
                            family_seeds,
                            direction="reverse",
                            budgets=limits,
                        )
                        if closures[family].truncated:
                            truncated = True
                            truncation_reason = (
                                truncation_reason
                                or closures[family].truncation_reason
                            )
                    except DuckDBImpactBudgetError:
                        if limits.on_exceed == "truncate":
                            truncated = True
                            truncation_reason = truncation_reason or "budget"
                        else:
                            raise

        elapsed_ms = (time.monotonic() - started) * 1000.0
        return ImpactResult(
            revision_id=index.revision_id,
            repository_tree_id=index.repository_tree_id,
            index_id=index.index_id,
            changed_symbols=tuple(
                sorted(explicit_symbols | inferred_symbols)
            ),
            affected_symbols=affected_symbols,
            changed_paths=tuple(sorted(explicit_paths)),
            affected_paths=affected_paths,
            dependency_chains=chains,
            required_validation_ids=tuple(sorted(validation_reasons)),
            validation_reasons=validation_reasons,
            uncovered_symbols=uncovered_symbols,
            uncovered_paths=uncovered_paths,
            budgets=limits,
            truncated=truncated,
            truncation_reason=truncation_reason,
            elapsed_ms=elapsed_ms,
            closures=closures,
        )


# ---------------------------------------------------------------------------
# Store / publication helpers
# ---------------------------------------------------------------------------


def build_impact_engine_from_projections(
    projections: Sequence[ASTCatalogProjection],
    *,
    symbol_dependencies: Mapping[str, Sequence[str]] | None = None,
    path_dependencies: Mapping[str, Sequence[str]] | None = None,
    validation_targets: Mapping[str, Sequence[str]] | None = None,
    conflict_surfaces: Sequence[Mapping[str, Any]] | None = None,
    default_budgets: ImpactBudgets | None = None,
) -> DuckDBImpactEngine:
    """Construct an engine from AST catalog projections."""

    index = build_impact_index_from_projections(
        projections,
        symbol_dependencies=symbol_dependencies,
        path_dependencies=path_dependencies,
        validation_targets=validation_targets,
        conflict_surfaces=conflict_surfaces,
    )
    return DuckDBImpactEngine(index, default_budgets=default_budgets)


def build_impact_engine_from_store(
    store: DuckDBASTStore,
    *,
    revision_id: str,
    blob_ids: Sequence[str] | None = None,
    file_ids: Sequence[str] | None = None,
    symbol_dependencies: Mapping[str, Sequence[str]] | None = None,
    path_dependencies: Mapping[str, Sequence[str]] | None = None,
    validation_targets: Mapping[str, Sequence[str]] | None = None,
    conflict_surfaces: Sequence[Mapping[str, Any]] | None = None,
    default_budgets: ImpactBudgets | None = None,
) -> DuckDBImpactEngine:
    """Construct an engine from a store by explicit blob/file identities.

    The in-process store does not expose a full scan API; callers (or
    revision publications from DQK-032) must supply the blob or file ids that
    belong to ``revision_id``.
    """

    revision = _text(revision_id, "revision_id")
    if not blob_ids and not file_ids:
        raise DuckDBImpactError(
            "build_impact_engine_from_store requires blob_ids or file_ids "
            "for the bound revision"
        )
    projections: list[ASTCatalogProjection] = []
    for blob_id in blob_ids or ():
        found = store.get(_text(blob_id, "blob_id"))
        if found is None:
            raise DuckDBImpactError(f"unknown blob_id: {blob_id!r}")
        if found.source_revision.revision_id != revision:
            raise DuckDBImpactRevisionError(
                f"blob {blob_id!r} is not bound to revision {revision!r}"
            )
        projections.append(found)
    for file_id in file_ids or ():
        found = store.get_by_file_id(_text(file_id, "file_id"))
        if found is None:
            raise DuckDBImpactError(f"unknown file_id: {file_id!r}")
        if found.source_revision.revision_id != revision:
            raise DuckDBImpactRevisionError(
                f"file {file_id!r} is not bound to revision {revision!r}"
            )
        projections.append(found)
    # Deduplicate by blob_id while preserving order.
    seen: set[str] = set()
    unique: list[ASTCatalogProjection] = []
    for projection in projections:
        if projection.blob_id in seen:
            continue
        seen.add(projection.blob_id)
        unique.append(projection)
    return build_impact_engine_from_projections(
        unique,
        symbol_dependencies=symbol_dependencies,
        path_dependencies=path_dependencies,
        validation_targets=validation_targets,
        conflict_surfaces=conflict_surfaces,
        default_budgets=default_budgets,
    )


def impact_schema_descriptor() -> dict[str, Any]:
    """Return a deterministic machine-readable impact interface statement."""

    return {
        "interface": DUCKDB_IMPACT_INTERFACE,
        "schema_version": DUCKDB_IMPACT_SCHEMA_VERSION,
        "closure_result_schema": CLOSURE_RESULT_SCHEMA,
        "code_impact_result_schema": CODE_IMPACT_RESULT_SCHEMA,
        "code_impact_index_schema": CODE_IMPACT_INDEX_SCHEMA,
        "closure_kinds": sorted(CLOSURE_KINDS),
        "default_budgets": ImpactBudgets().to_dict(),
        "hard_budgets": {
            "max_depth": HARD_MAX_DEPTH,
            "max_rows": HARD_MAX_ROWS,
            "max_edges": HARD_MAX_EDGES,
            "time_budget_ms": HARD_TIME_BUDGET_MS,
        },
        "guarantees": {
            "closures_bind_exact_source_revision": True,
            "depth_row_time_budgets_enforced": True,
            "agrees_with_code_impact_index": True,
            "import_inert": True,
        },
    }


__all__ = [
    "CLOSURE_KINDS",
    "CLOSURE_RESULT_SCHEMA",
    "CODE_IMPACT_INDEX_SCHEMA",
    "CODE_IMPACT_RESULT_SCHEMA",
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_EDGES",
    "DEFAULT_MAX_ROWS",
    "DEFAULT_TIME_BUDGET_MS",
    "DUCKDB_IMPACT_INTERFACE",
    "DUCKDB_IMPACT_SCHEMA_VERSION",
    "ClosureResult",
    "DuckDBImpactBudgetError",
    "DuckDBImpactEngine",
    "DuckDBImpactError",
    "DuckDBImpactIndex",
    "DuckDBImpactRevisionError",
    "HARD_MAX_DEPTH",
    "HARD_MAX_EDGES",
    "HARD_MAX_ROWS",
    "HARD_TIME_BUDGET_MS",
    "ImpactBudgets",
    "ImpactClosureKind",
    "ImpactEdge",
    "ImpactResult",
    "bounded_closure",
    "build_impact_engine_from_projections",
    "build_impact_engine_from_store",
    "build_impact_index_from_maps",
    "build_impact_index_from_projections",
    "impact_schema_descriptor",
]
