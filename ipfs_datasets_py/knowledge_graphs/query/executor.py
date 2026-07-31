"""Target-bound GraphQueryExecutor (KGP-015).

Routes scans, lookup, neighbors, paths, Cypher IR, hybrid/vector search, and
explicit federation through a single executor. Every operation names a
declared :class:`GraphTarget` (or a pre-bound backend for that target).

Distributed / federated execution uses only the backends registered for
declared targets and **never** constructs an empty ``KnowledgeGraph`` as a
fallback.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
    Union,
)

from ipfs_datasets_py.knowledge_graphs.query.backend import (
    BACKEND_API_VERSION,
    BackendQueryResult,
    Expand,
    ExecutionResult,
    FederatedGraphQueryBackend,
    GraphQueryBackend,
    GraphQueryBackendError,
    InMemoryGraphQueryBackend,
    Limit,
    Project,
    QueryIR,
    ScanType,
    SeedEntities,
    open_federated_backend,
)

logger = logging.getLogger(__name__)

JSONDict = Dict[str, Any]
BackendLike = GraphQueryBackend
TargetLike = Any  # GraphTarget | mapping | kg:// uri


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclass
class ExecutorResult:
    """Versioned executor result (maps cleanly onto QueryResultEnvelope)."""

    kind: str
    columns: List[str]
    rows: List[Any]
    schema: str
    target_uri: Optional[str] = None
    revision: Optional[str] = None
    cursor: Optional[str] = None
    statistics: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    truncated: bool = False
    query: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: Optional[Dict[str, Any]] = None

    def to_json_dict(self) -> JSONDict:
        return {
            "kind": self.kind,
            "schema": self.schema,
            "columns": list(self.columns),
            "rows": list(self.rows),
            "row_count": len(self.rows),
            "target_uri": self.target_uri,
            "revision": self.revision,
            "cursor": self.cursor,
            "statistics": dict(self.statistics),
            "warnings": list(self.warnings),
            "truncated": bool(self.truncated),
            "query": dict(self.query),
            "success": bool(self.success),
            "error": self.error,
            "backend_api_version": BACKEND_API_VERSION,
        }


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class GraphQueryExecutor:
    """Execute queries against target-bound :class:`GraphQueryBackend` instances.

    Backends are registered under their target URI (or an explicit key). The
    executor refuses ambient empty-graph fallbacks.
    """

    def __init__(
        self,
        backends: Optional[Mapping[str, BackendLike]] = None,
        *,
        default_backend: Optional[BackendLike] = None,
    ) -> None:
        self._backends: MutableMapping[str, BackendLike] = {}
        if backends:
            for key, backend in backends.items():
                self.register(backend, key=key)
        self._default = default_backend
        if default_backend is not None:
            self._validate_backend(default_backend)

    # -- registration -------------------------------------------------------

    @staticmethod
    def _validate_backend(backend: BackendLike) -> None:
        if backend is None:
            raise GraphQueryBackendError(
                "INVALID_REQUEST",
                "backend must not be None",
            )
        # Hard rule: never accept a raw empty KnowledgeGraph stand-in.
        if type(backend).__name__ == "KnowledgeGraph":
            raise GraphQueryBackendError(
                "INVALID_REQUEST",
                "GraphQueryExecutor refuses KnowledgeGraph instances; "
                "register a target-bound GraphQueryBackend instead",
            )
        if getattr(backend, "target", None) is None:
            raise GraphQueryBackendError(
                "INVALID_TARGET",
                "backend must be bound to an explicit GraphTarget",
            )

    @staticmethod
    def _target_key(target: TargetLike) -> str:
        if target is None:
            raise GraphQueryBackendError(
                "INVALID_TARGET",
                "operation requires an explicit GraphTarget",
            )
        from ipfs_datasets_py.knowledge_graphs.service import (
            GraphTarget,
            GraphTargetError,
        )

        try:
            if isinstance(target, GraphTarget):
                return target.uri
            if isinstance(target, str):
                # Allow either a bare registry key or a kg:// URI.
                if target.startswith("kg://"):
                    return GraphTarget.from_uri(target).uri
                return target
            if isinstance(target, Mapping):
                return GraphTarget.from_mapping(target).uri
        except GraphTargetError as exc:
            raise GraphQueryBackendError(
                "INVALID_TARGET",
                str(exc),
                details=getattr(exc, "details", None) or {},
            ) from exc
        # Backend instance used as target handle.
        if hasattr(target, "target") and getattr(target, "target") is not None:
            return GraphQueryExecutor._target_key(getattr(target, "target"))
        raise GraphQueryBackendError(
            "INVALID_TARGET",
            f"unsupported target type: {type(target).__name__}",
        )

    def register(
        self,
        backend: BackendLike,
        *,
        key: Optional[str] = None,
    ) -> str:
        """Register a target-bound backend. Returns the registry key (URI)."""
        self._validate_backend(backend)
        reg_key = key or self._target_key(backend.target)
        self._backends[reg_key] = backend
        return reg_key

    def unregister(self, key: str) -> None:
        self._backends.pop(key, None)

    def registered_targets(self) -> List[str]:
        return sorted(self._backends.keys())

    def resolve(
        self,
        target: Optional[TargetLike] = None,
        *,
        backend: Optional[BackendLike] = None,
    ) -> BackendLike:
        """Resolve a declared backend; never invent an empty graph."""
        if backend is not None:
            self._validate_backend(backend)
            return backend
        if target is not None:
            # Direct backend pass-through.
            if isinstance(target, GraphQueryBackend) or (
                hasattr(target, "scan")
                and hasattr(target, "lookup")
                and hasattr(target, "target")
            ):
                self._validate_backend(target)  # type: ignore[arg-type]
                return target  # type: ignore[return-value]
            key = self._target_key(target)
            if key in self._backends:
                return self._backends[key]
            raise GraphQueryBackendError(
                "NOT_FOUND",
                f"no backend registered for target {key!r}",
                details={"target": key, "registered": self.registered_targets()},
            )
        if self._default is not None:
            return self._default
        if len(self._backends) == 1:
            return next(iter(self._backends.values()))
        raise GraphQueryBackendError(
            "INVALID_TARGET",
            "GraphQueryExecutor requires an explicit GraphTarget; "
            "no default backend and no unique registered backend",
            details={"registered": self.registered_targets()},
        )

    # -- helpers ------------------------------------------------------------

    def _wrap(
        self,
        kind: str,
        result: Union[BackendQueryResult, ExecutionResult],
        *,
        backend: BackendLike,
        query: Optional[Mapping[str, Any]] = None,
        started: Optional[float] = None,
    ) -> ExecutorResult:
        elapsed_ms = None
        if started is not None:
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)

        if isinstance(result, ExecutionResult):
            stats = dict(result.stats or {})
            if elapsed_ms is not None:
                stats.setdefault("elapsed_ms", elapsed_ms)
            return ExecutorResult(
                kind=kind,
                columns=list(result.items[0].keys()) if result.items else [],
                rows=list(result.items),
                schema="kg-ir-result/v1",
                target_uri=getattr(getattr(backend, "target", None), "uri", None),
                revision=getattr(backend, "revision", None),
                statistics=stats,
                query=dict(query or {}),
            )

        stats = dict(result.statistics or {})
        if elapsed_ms is not None:
            stats.setdefault("elapsed_ms", elapsed_ms)
        return ExecutorResult(
            kind=kind,
            columns=list(result.columns),
            rows=list(result.rows),
            schema=result.schema,
            target_uri=result.target_uri
            or getattr(getattr(backend, "target", None), "uri", None),
            revision=result.revision or getattr(backend, "revision", None),
            cursor=result.cursor,
            statistics=stats,
            warnings=list(result.warnings),
            truncated=bool(result.truncated),
            query=dict(query or {}),
        )

    # -- public operations --------------------------------------------------

    def scan(
        self,
        target: Optional[TargetLike] = None,
        *,
        backend: Optional[BackendLike] = None,
        entity_type: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
        scope: Optional[Sequence[str]] = None,
    ) -> ExecutorResult:
        b = self.resolve(target, backend=backend)
        started = time.perf_counter()
        res = b.scan(
            entity_type=entity_type,
            limit=limit,
            cursor=cursor,
            scope=scope,
        )
        return self._wrap(
            "scan",
            res,
            backend=b,
            query={"language": "scan", "entity_type": entity_type, "limit": limit},
            started=started,
        )

    def lookup(
        self,
        entity_ids: Sequence[str],
        target: Optional[TargetLike] = None,
        *,
        backend: Optional[BackendLike] = None,
    ) -> ExecutorResult:
        b = self.resolve(target, backend=backend)
        started = time.perf_counter()
        res = b.lookup(entity_ids)
        return self._wrap(
            "lookup",
            res,
            backend=b,
            query={"language": "lookup", "entity_ids": list(entity_ids)},
            started=started,
        )

    def neighbors(
        self,
        entity_id: str,
        target: Optional[TargetLike] = None,
        *,
        backend: Optional[BackendLike] = None,
        relationship_types: Optional[Sequence[str]] = None,
        direction: str = "both",
        limit: int = 1000,
        cursor: Optional[str] = None,
    ) -> ExecutorResult:
        b = self.resolve(target, backend=backend)
        started = time.perf_counter()
        res = b.neighbors(
            entity_id,
            relationship_types=relationship_types,
            direction=direction,  # type: ignore[arg-type]
            limit=limit,
            cursor=cursor,
        )
        return self._wrap(
            "neighbors",
            res,
            backend=b,
            query={
                "language": "neighbors",
                "entity_id": entity_id,
                "direction": direction,
                "limit": limit,
            },
            started=started,
        )

    def paths(
        self,
        seed_id: str,
        target: Optional[TargetLike] = None,
        *,
        backend: Optional[BackendLike] = None,
        max_depth: int = 2,
        max_fan_out: int = 32,
        relationship_types: Optional[Sequence[str]] = None,
        limit: int = 100,
    ) -> ExecutorResult:
        b = self.resolve(target, backend=backend)
        started = time.perf_counter()
        res = b.paths(
            seed_id,
            max_depth=max_depth,
            max_fan_out=max_fan_out,
            relationship_types=relationship_types,
            limit=limit,
        )
        return self._wrap(
            "paths",
            res,
            backend=b,
            query={
                "language": "paths",
                "seed_id": seed_id,
                "max_depth": max_depth,
                "limit": limit,
            },
            started=started,
        )

    def execute_ir(
        self,
        ir: QueryIR,
        target: Optional[TargetLike] = None,
        *,
        backend: Optional[BackendLike] = None,
        budgets: Optional[Mapping[str, Any]] = None,
    ) -> ExecutorResult:
        b = self.resolve(target, backend=backend)
        started = time.perf_counter()
        res = b.execute_ir(ir, budgets=budgets)
        return self._wrap(
            "cypher_ir",
            res,
            backend=b,
            query={
                "language": "cypher-ir",
                "ops": [type(op).__name__ for op in ir.ops],
            },
            started=started,
        )

    def execute_cypher_ir(
        self,
        ir: QueryIR,
        target: Optional[TargetLike] = None,
        *,
        backend: Optional[BackendLike] = None,
        budgets: Optional[Mapping[str, Any]] = None,
    ) -> ExecutorResult:
        """Alias for :meth:`execute_ir` (Cypher-compiled pipelines)."""
        return self.execute_ir(ir, target, backend=backend, budgets=budgets)

    def hybrid_search(
        self,
        query: str,
        target: Optional[TargetLike] = None,
        *,
        backend: Optional[BackendLike] = None,
        k: int = 10,
        vector_weight: float = 0.6,
        graph_weight: float = 0.4,
        max_hops: int = 1,
        embeddings: Optional[Mapping[str, Sequence[float]]] = None,
        query_vector: Optional[Sequence[float]] = None,
    ) -> ExecutorResult:
        b = self.resolve(target, backend=backend)
        started = time.perf_counter()
        res = b.hybrid_search(
            query,
            k=k,
            vector_weight=vector_weight,
            graph_weight=graph_weight,
            max_hops=max_hops,
            embeddings=embeddings,
            query_vector=query_vector,
        )
        return self._wrap(
            "hybrid",
            res,
            backend=b,
            query={
                "language": "hybrid",
                "text": query,
                "k": k,
                "vector_weight": vector_weight,
                "graph_weight": graph_weight,
                "max_hops": max_hops,
            },
            started=started,
        )

    def vector_search(
        self,
        query_vector: Sequence[float],
        target: Optional[TargetLike] = None,
        *,
        backend: Optional[BackendLike] = None,
        k: int = 10,
        embeddings: Optional[Mapping[str, Sequence[float]]] = None,
    ) -> ExecutorResult:
        b = self.resolve(target, backend=backend)
        started = time.perf_counter()
        res = b.vector_search(query_vector, k=k, embeddings=embeddings)
        return self._wrap(
            "vector",
            res,
            backend=b,
            query={"language": "vector", "k": k},
            started=started,
        )

    def federate(
        self,
        targets: Sequence[TargetLike],
        *,
        federation_target: Optional[TargetLike] = None,
        operation: str = "scan",
        **kwargs: Any,
    ) -> ExecutorResult:
        """Run *operation* over an explicit list of declared targets.

        Never constructs an empty KnowledgeGraph. Every target must resolve to
        a registered (or directly provided) backend.
        """
        if not targets:
            raise GraphQueryBackendError(
                "INVALID_REQUEST",
                "federation requires a non-empty declared target list",
            )

        leaves: List[BackendLike] = []
        for t in targets:
            if isinstance(t, GraphQueryBackend) or (
                hasattr(t, "scan") and hasattr(t, "target")
            ):
                self._validate_backend(t)  # type: ignore[arg-type]
                leaves.append(t)  # type: ignore[arg-type]
            else:
                leaves.append(self.resolve(t))

        # Federation control-plane target: explicit, or first leaf's target.
        fed_target = federation_target
        if fed_target is None:
            fed_target = leaves[0].target

        fed = open_federated_backend(fed_target, leaves)
        started = time.perf_counter()
        op = (operation or "scan").lower().strip()

        if op == "scan":
            res = fed.scan(
                entity_type=kwargs.get("entity_type"),
                limit=int(kwargs.get("limit", 1000)),
                cursor=kwargs.get("cursor"),
                scope=kwargs.get("scope"),
            )
            kind = "federated_scan"
        elif op == "lookup":
            entity_ids = kwargs.get("entity_ids") or kwargs.get("ids") or []
            res = fed.federate_lookup(list(entity_ids))
            kind = "federated_lookup"
        elif op == "neighbors":
            entity_id = kwargs.get("entity_id")
            if not entity_id:
                raise GraphQueryBackendError(
                    "INVALID_REQUEST", "neighbors federation requires entity_id"
                )
            res = fed.neighbors(
                str(entity_id),
                relationship_types=kwargs.get("relationship_types"),
                direction=kwargs.get("direction", "both"),
                limit=int(kwargs.get("limit", 1000)),
                cursor=kwargs.get("cursor"),
            )
            kind = "federated_neighbors"
        elif op in {"hybrid", "hybrid_search"}:
            res = fed.hybrid_search(
                str(kwargs.get("query") or kwargs.get("text") or ""),
                k=int(kwargs.get("k", 10)),
                vector_weight=float(kwargs.get("vector_weight", 0.6)),
                graph_weight=float(kwargs.get("graph_weight", 0.4)),
                max_hops=int(kwargs.get("max_hops", 1)),
                embeddings=kwargs.get("embeddings"),
                query_vector=kwargs.get("query_vector"),
            )
            kind = "federated_hybrid"
        elif op in {"ir", "cypher_ir", "execute_ir"}:
            ir = kwargs.get("ir")
            if not isinstance(ir, QueryIR):
                raise GraphQueryBackendError(
                    "INVALID_REQUEST", "execute_ir federation requires QueryIR ir="
                )
            exec_res = fed.execute_ir(ir, budgets=kwargs.get("budgets"))
            return self._wrap(
                "federated_cypher_ir",
                exec_res,
                backend=fed,
                query={
                    "language": "federated-cypher-ir",
                    "targets": [
                        getattr(getattr(b, "target", None), "uri", None)
                        for b in leaves
                    ],
                },
                started=started,
            )
        else:
            raise GraphQueryBackendError(
                "QUERY_PARSE",
                f"unsupported federation operation: {operation!r}",
            )

        out = self._wrap(
            kind,
            res,
            backend=fed,
            query={
                "language": f"federated-{op}",
                "targets": [
                    getattr(getattr(b, "target", None), "uri", None) for b in leaves
                ],
            },
            started=started,
        )
        out.statistics["declared_targets"] = len(leaves)
        return out

    def execute(
        self,
        *,
        language: str,
        target: Optional[TargetLike] = None,
        backend: Optional[BackendLike] = None,
        text: Optional[str] = None,
        params: Optional[Mapping[str, Any]] = None,
        budgets: Optional[Mapping[str, Any]] = None,
        federation_targets: Optional[Sequence[TargetLike]] = None,
        ir: Optional[QueryIR] = None,
        **kwargs: Any,
    ) -> ExecutorResult:
        """Generic entry point used by GraphService-style callers."""
        lang = (language or "scan").lower().strip()
        params = dict(params or {})
        params.update(kwargs)

        if federation_targets is not None:
            return self.federate(
                federation_targets,
                federation_target=target,
                operation=lang,
                query=text,
                ir=ir,
                budgets=budgets,
                **params,
            )

        if lang in {"scan", "node-scan", "nodes"}:
            return self.scan(
                target,
                backend=backend,
                entity_type=params.get("entity_type") or params.get("type"),
                limit=int(params.get("limit") or params.get("max_rows") or 100),
                cursor=params.get("cursor"),
                scope=params.get("scope"),
            )
        if lang == "lookup":
            ids = params.get("entity_ids") or params.get("ids") or []
            if text and not ids:
                ids = [text]
            return self.lookup(list(ids), target, backend=backend)
        if lang == "neighbors":
            entity_id = params.get("entity_id") or text
            if not entity_id:
                raise GraphQueryBackendError(
                    "INVALID_REQUEST", "neighbors requires entity_id"
                )
            return self.neighbors(
                str(entity_id),
                target,
                backend=backend,
                relationship_types=params.get("relationship_types"),
                direction=str(params.get("direction") or "both"),
                limit=int(params.get("limit") or 1000),
                cursor=params.get("cursor"),
            )
        if lang in {"paths", "path"}:
            seed = params.get("seed_id") or params.get("entity_id") or text
            if not seed:
                raise GraphQueryBackendError(
                    "INVALID_REQUEST", "paths requires seed_id"
                )
            return self.paths(
                str(seed),
                target,
                backend=backend,
                max_depth=int(params.get("max_depth") or 2),
                max_fan_out=int(params.get("max_fan_out") or 32),
                relationship_types=params.get("relationship_types"),
                limit=int(params.get("limit") or 100),
            )
        if lang in {"cypher-ir", "ir", "cypher_ir"}:
            if ir is None:
                raise GraphQueryBackendError(
                    "INVALID_REQUEST", "cypher-ir language requires ir="
                )
            return self.execute_ir(ir, target, backend=backend, budgets=budgets)
        if lang in {"hybrid", "hybrid_search"}:
            q = text or params.get("query") or ""
            return self.hybrid_search(
                str(q),
                target,
                backend=backend,
                k=int(params.get("k") or 10),
                vector_weight=float(params.get("vector_weight", 0.6)),
                graph_weight=float(params.get("graph_weight", 0.4)),
                max_hops=int(params.get("max_hops") or 1),
                embeddings=params.get("embeddings"),
                query_vector=params.get("query_vector"),
            )
        if lang in {"vector", "vector_search"}:
            qv = params.get("query_vector")
            if qv is None:
                raise GraphQueryBackendError(
                    "INVALID_REQUEST", "vector search requires query_vector"
                )
            return self.vector_search(
                list(qv),
                target,
                backend=backend,
                k=int(params.get("k") or 10),
                embeddings=params.get("embeddings"),
            )
        if lang in {"federate", "federation"}:
            targets = params.get("targets") or federation_targets
            if not targets:
                raise GraphQueryBackendError(
                    "INVALID_REQUEST",
                    "federation language requires targets= declared list",
                )
            return self.federate(
                list(targets),
                federation_target=target,
                operation=str(params.get("operation") or "scan"),
                **{k: v for k, v in params.items() if k not in {"targets", "operation"}},
            )

        raise GraphQueryBackendError(
            "QUERY_PARSE",
            f"unsupported query language: {language!r}",
            details={"language": language},
        )


# ---------------------------------------------------------------------------
# Compatibility adapter for search.graph_query.GraphQueryExecutor
# ---------------------------------------------------------------------------


class LegacyGraphBackendAdapter:
    """Expose :class:`BaseGraphQueryBackend` as search ``GraphBackend``.

    ``neighbors`` returns :class:`NeighborPage` (legacy) while the unified
    protocol returns :class:`BackendQueryResult`.
    """

    def __init__(self, backend: GraphQueryBackend) -> None:
        if type(backend).__name__ == "KnowledgeGraph":
            raise GraphQueryBackendError(
                "INVALID_REQUEST",
                "LegacyGraphBackendAdapter refuses KnowledgeGraph instances",
            )
        self._backend = backend

    @property
    def target(self) -> Any:
        return getattr(self._backend, "target", None)

    def get_entity_headers(self, entity_ids: Sequence[str]):
        return self._backend.get_entity_headers(entity_ids)

    def seed_exists(self, entity_id: str) -> bool:
        return self._backend.seed_exists(entity_id)

    def scan_type(
        self,
        entity_type: str,
        *,
        scope: Sequence[str] | None = None,
        limit: int = 100,
        cursor: str | None = None,
        shard_hints: Sequence[str] | None = None,
    ):
        return self._backend.scan_type(
            entity_type,
            scope=scope,
            limit=limit,
            cursor=cursor,
            shard_hints=shard_hints,
        )

    def neighbors(
        self,
        entity_id: str,
        *,
        relationship_types: Sequence[str] | None = None,
        direction: str = "both",
        limit: int = 1000,
        cursor: str | None = None,
    ):
        # Prefer neighbors_page when available.
        if hasattr(self._backend, "neighbors_page"):
            return self._backend.neighbors_page(  # type: ignore[attr-defined]
                entity_id,
                relationship_types=relationship_types,
                direction=direction,  # type: ignore[arg-type]
                limit=limit,
                cursor=cursor,
            )
        from ipfs_datasets_py.knowledge_graphs.query.backend import (
            NeighborEdge,
            NeighborPage,
        )

        page = self._backend.neighbors(
            entity_id,
            relationship_types=relationship_types,
            direction=direction,  # type: ignore[arg-type]
            limit=limit,
            cursor=cursor,
        )
        edges = [
            NeighborEdge(
                relationship_type=str(r.get("relationship_type") or ""),
                source_id=str(r.get("source_id") or ""),
                target_id=str(r.get("target_id") or ""),
                relationship_id=str(r.get("relationship_id") or "") or None,
                direction=str(r.get("direction") or "outgoing"),
                properties=dict(r.get("properties") or {}) or None,
                cross_shard=bool(r.get("cross_shard", False)),
            )
            for r in page.rows
        ]
        return NeighborPage(edges=edges, next_cursor=page.cursor, rows=list(page.rows))


def build_simple_ir(
    *,
    entity_type: Optional[str] = None,
    seed_ids: Optional[Sequence[str]] = None,
    expand: bool = False,
    relationship_types: Optional[Sequence[str]] = None,
    direction: str = "both",
    limit: Optional[int] = None,
    project_fields: Sequence[str] = ("id", "type", "name"),
) -> QueryIR:
    """Helper to construct a common Scan/Seed → Expand → Limit → Project IR."""
    ir = QueryIR()
    if seed_ids is not None:
        ir.add(SeedEntities(list(seed_ids)))
    elif entity_type is not None:
        ir.add(ScanType(entity_type=entity_type))
    else:
        ir.add(ScanType(entity_type="*"))
    if expand:
        ir.add(
            Expand(
                relationship_types=relationship_types,
                direction=direction,  # type: ignore[arg-type]
            )
        )
    if limit is not None:
        ir.add(Limit(int(limit)))
    ir.add(Project(fields=tuple(project_fields)))
    return ir


__all__ = [
    "ExecutorResult",
    "GraphQueryExecutor",
    "LegacyGraphBackendAdapter",
    "build_simple_ir",
    "QueryIR",
    "SeedEntities",
    "ScanType",
    "Expand",
    "Limit",
    "Project",
    "ExecutionResult",
    "InMemoryGraphQueryBackend",
    "FederatedGraphQueryBackend",
]
