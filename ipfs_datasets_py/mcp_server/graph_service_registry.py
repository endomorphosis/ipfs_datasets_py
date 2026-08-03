"""Server-owned GraphService registry for MCP / MCP++ graph tools (KGP-019).

Conflict policy for KGP-019: resolve a **server-owned**
:class:`~ipfs_datasets_py.knowledge_graphs.service.GraphService` from request
or process context; never instantiate a fresh manager per tool invocation.

Surfaces (MCP tools, hierarchical MCP++ dispatch) call
:func:`get_graph_service` so transactions, cursors, and open handles survive
independent tool calls within the same process.
"""

from __future__ import annotations

import hashlib
import os
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Set, Union

from ipfs_datasets_py.knowledge_graphs.service import (
    AuthorizationDecision,
    GraphService,
    GraphTarget,
    _OP_ABILITIES,
)

PathLike = Union[str, Path]

ENV_CATALOG = "IPFS_DATASETS_KG_CATALOG"
ENV_STORE = "IPFS_DATASETS_KG_STORE"
ENV_HOLDER = "IPFS_DATASETS_KG_HOLDER_ID"

# Default abilities granted when auth does not list explicit abilities.
_DEFAULT_ABILITIES = frozenset(_OP_ABILITIES.values())


# ---------------------------------------------------------------------------
# Tenant / ability authorizer (MCP client isolation)
# ---------------------------------------------------------------------------


class TenantScopeAuthorizer:
    """Authorize graph ops with optional tenant + ability containment.

    Rules (fail closed when auth is present and scoped):

    * If ``auth`` is missing or empty → allow (trusted local / single-tenant
      server). Tools that need isolation must pass per-client ``auth``.
    * If ``auth.tenant`` or ``auth.allowed_tenants`` is set, the request target
      tenant must be in that set; otherwise ``FORBIDDEN``.
    * If ``auth.abilities`` is set, the operation ability must be granted;
      otherwise ``FORBIDDEN``.
    * If ``auth.required`` is true and principal is missing → ``UNAUTHORIZED``.
    """

    def __init__(
        self,
        *,
        default_allow_unauthenticated: bool = True,
    ) -> None:
        self._default_allow = bool(default_allow_unauthenticated)

    def authorize(
        self,
        *,
        operation: str,
        target: GraphTarget,
        auth: Optional[Mapping[str, Any]],
        request_id: Optional[str],
    ) -> AuthorizationDecision:
        ability = _OP_ABILITIES.get(operation, "graph/admin")
        principal = None
        if auth:
            principal = auth.get("principal") or auth.get("subject")
        digest = hashlib.sha256(
            f"{operation}|{target.uri}|{principal}|{request_id}|{ability}".encode(
                "utf-8"
            )
        ).hexdigest()[:24]
        receipt = f"auth-receipt-{digest}"

        if not auth:
            if self._default_allow:
                return AuthorizationDecision(
                    allowed=True,
                    principal=None,
                    ability=ability,
                    receipt_ref=receipt,
                    reason="allow_unauthenticated",
                )
            return AuthorizationDecision(
                allowed=False,
                principal=None,
                ability=ability,
                receipt_ref=receipt,
                reason="authentication required",
                code="UNAUTHORIZED",
            )

        required = bool(auth.get("required"))
        if required and not principal:
            return AuthorizationDecision(
                allowed=False,
                principal=None,
                ability=ability,
                receipt_ref=receipt,
                reason="missing principal",
                code="UNAUTHORIZED",
            )

        allowed_tenants: Set[str] = set()
        if auth.get("tenant"):
            allowed_tenants.add(str(auth["tenant"]))
        raw_list = auth.get("allowed_tenants") or auth.get("tenants")
        if raw_list:
            if isinstance(raw_list, (list, tuple, set, frozenset)):
                allowed_tenants.update(str(t) for t in raw_list)
            else:
                allowed_tenants.add(str(raw_list))

        if allowed_tenants and target.tenant not in allowed_tenants:
            return AuthorizationDecision(
                allowed=False,
                principal=str(principal) if principal else None,
                ability=ability,
                receipt_ref=receipt,
                reason=(
                    f"tenant {target.tenant!r} not in allowed tenants "
                    f"{sorted(allowed_tenants)}"
                ),
                code="FORBIDDEN",
            )

        abilities_raw = auth.get("abilities") or auth.get("capabilities")
        if abilities_raw is not None:
            if isinstance(abilities_raw, str):
                granted = {abilities_raw}
            else:
                granted = {str(a) for a in abilities_raw}
            # graph/admin implies all abilities for convenience.
            if "graph/admin" not in granted and ability not in granted:
                return AuthorizationDecision(
                    allowed=False,
                    principal=str(principal) if principal else None,
                    ability=ability,
                    receipt_ref=receipt,
                    reason=f"ability {ability} not granted",
                    code="FORBIDDEN",
                )

        return AuthorizationDecision(
            allowed=True,
            principal=str(principal) if principal else None,
            ability=ability,
            receipt_ref=receipt,
            reason="granted",
        )


# ---------------------------------------------------------------------------
# Cursor / stream session store (process-local, service-scoped)
# ---------------------------------------------------------------------------


@dataclass
class StreamSession:
    """In-process stream / cursor session for multi-call pagination."""

    session_id: str
    tenant: str
    graph_id: str
    revision: Optional[str]
    columns: list
    rows: list
    offset: int = 0
    page_size: int = 100
    cancelled: bool = False
    language: str = "scan"
    query_text: str = ""
    statistics: Dict[str, Any] = field(default_factory=dict)
    schema: str = "node-scan/v1"
    principal: Optional[str] = None

    def to_public_cursor(self) -> str:
        return self.session_id


class StreamSessionStore:
    """Thread-safe store of active stream sessions (cursors)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: Dict[str, StreamSession] = {}

    def create(
        self,
        *,
        tenant: str,
        graph_id: str,
        revision: Optional[str],
        columns: Sequence[Any],
        rows: Sequence[Any],
        page_size: int = 100,
        language: str = "scan",
        query_text: str = "",
        statistics: Optional[Mapping[str, Any]] = None,
        schema: str = "node-scan/v1",
        principal: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> StreamSession:
        sid = session_id or f"cur-{uuid.uuid4().hex}"
        session = StreamSession(
            session_id=sid,
            tenant=tenant,
            graph_id=graph_id,
            revision=revision,
            columns=list(columns),
            rows=list(rows),
            offset=0,
            page_size=max(1, int(page_size)),
            language=language,
            query_text=query_text,
            statistics=dict(statistics or {}),
            schema=schema,
            principal=principal,
        )
        with self._lock:
            self._sessions[sid] = session
        return session

    def get(self, session_id: str) -> Optional[StreamSession]:
        with self._lock:
            return self._sessions.get(session_id)

    def cancel(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session.cancelled = True
            return True

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    def next_page(
        self, session_id: str, *, page_size: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if session.cancelled:
                return {
                    "cancelled": True,
                    "session_id": session_id,
                    "columns": list(session.columns),
                    "rows": [],
                    "row_count": 0,
                    "offset": session.offset,
                    "exhausted": True,
                    "cursor": None,
                }
            size = max(1, int(page_size or session.page_size))
            start = session.offset
            end = min(len(session.rows), start + size)
            page_rows = session.rows[start:end]
            session.offset = end
            exhausted = end >= len(session.rows)
            cursor = None if exhausted else session.session_id
            if exhausted:
                # Keep session for a cancel/status race; callers may remove.
                pass
            return {
                "cancelled": False,
                "session_id": session_id,
                "columns": list(session.columns),
                "rows": page_rows,
                "row_count": len(page_rows),
                "offset": start,
                "page_index": start // size if size else 0,
                "exhausted": exhausted,
                "cursor": cursor,
                "revision": session.revision,
                "schema": session.schema,
                "statistics": dict(session.statistics),
                "tenant": session.tenant,
                "graph_id": session.graph_id,
            }


# ---------------------------------------------------------------------------
# Process / server registry
# ---------------------------------------------------------------------------


@dataclass
class GraphServiceBinding:
    """A bound GraphService plus stream store and ownership flag."""

    service: GraphService
    streams: StreamSessionStore
    owns_service: bool
    catalog_path: Optional[Path] = None
    storage_path: Optional[Path] = None


class GraphServiceRegistry:
    """Thread-safe registry for the process- or server-owned GraphService.

    Tools resolve the service via :meth:`get_or_open` so every invocation
    shares transactions and stream cursors.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._binding: Optional[GraphServiceBinding] = None
        # Named alternate bindings (e.g. multi-tenant isolation tests).
        self._named: Dict[str, GraphServiceBinding] = {}
        self._default_authorizer = TenantScopeAuthorizer()

    def bind(
        self,
        service: GraphService,
        *,
        owns_service: bool = False,
        catalog_path: Optional[PathLike] = None,
        storage_path: Optional[PathLike] = None,
        streams: Optional[StreamSessionStore] = None,
        name: Optional[str] = None,
    ) -> GraphServiceBinding:
        """Bind an existing service as the server-owned instance."""
        binding = GraphServiceBinding(
            service=service,
            streams=streams or StreamSessionStore(),
            owns_service=owns_service,
            catalog_path=Path(catalog_path).resolve() if catalog_path else None,
            storage_path=Path(storage_path).resolve() if storage_path else None,
        )
        with self._lock:
            if name:
                old = self._named.get(name)
                if old is not None and old.owns_service and old.service is not service:
                    try:
                        old.service.close()
                    except Exception:
                        pass
                self._named[name] = binding
            else:
                if (
                    self._binding is not None
                    and self._binding.owns_service
                    and self._binding.service is not service
                ):
                    try:
                        self._binding.service.close()
                    except Exception:
                        pass
                self._binding = binding
        return binding

    def open(
        self,
        catalog_path: PathLike,
        *,
        storage_path: Optional[PathLike] = None,
        authorizer: Any = None,
        holder_id: Optional[str] = None,
        name: Optional[str] = None,
        force: bool = False,
        **catalog_kwargs: Any,
    ) -> GraphServiceBinding:
        """Open (or reuse) a durable GraphService at the given paths."""
        cat = Path(catalog_path).resolve()
        store = Path(storage_path).resolve() if storage_path is not None else None
        with self._lock:
            existing = self._named.get(name) if name else self._binding
            if (
                existing is not None
                and not force
                and existing.catalog_path == cat
                and (store is None or existing.storage_path == store)
            ):
                return existing

        service = GraphService.open(
            cat,
            storage_path=store,
            authorizer=authorizer if authorizer is not None else self._default_authorizer,
            holder_id=holder_id
            or os.environ.get(ENV_HOLDER)
            or f"mcp-gs-{uuid.uuid4().hex[:10]}",
            **catalog_kwargs,
        )
        return self.bind(
            service,
            owns_service=True,
            catalog_path=cat,
            storage_path=store,
            name=name,
        )

    def get(
        self, *, name: Optional[str] = None
    ) -> Optional[GraphServiceBinding]:
        with self._lock:
            if name:
                return self._named.get(name)
            return self._binding

    def get_or_open(
        self,
        *,
        catalog_path: Optional[PathLike] = None,
        storage_path: Optional[PathLike] = None,
        name: Optional[str] = None,
        authorizer: Any = None,
        **catalog_kwargs: Any,
    ) -> GraphServiceBinding:
        """Return the bound service, opening from args/env if needed.

        Raises:
            RuntimeError: when no binding exists and catalog path cannot be
                resolved from arguments or environment.
        """
        with self._lock:
            existing = self._named.get(name) if name else self._binding
            if existing is not None:
                return existing

        cat = catalog_path or os.environ.get(ENV_CATALOG)
        store = storage_path or os.environ.get(ENV_STORE)
        if not cat:
            raise RuntimeError(
                "No GraphService bound and no catalog path available. "
                f"Pass catalog_path or set {ENV_CATALOG}."
            )
        return self.open(
            cat,
            storage_path=store,
            authorizer=authorizer,
            name=name,
            **catalog_kwargs,
        )

    def unbind(self, *, name: Optional[str] = None, close: bool = True) -> None:
        with self._lock:
            if name:
                binding = self._named.pop(name, None)
            else:
                binding = self._binding
                self._binding = None
        if binding is not None:
            binding.streams.clear()
            if close and binding.owns_service:
                try:
                    binding.service.close()
                except Exception:
                    pass

    def reset(self) -> None:
        """Close and clear all bindings (for tests)."""
        with self._lock:
            names = list(self._named.keys())
            default = self._binding
            self._named.clear()
            self._binding = None
        if default is not None and default.owns_service:
            try:
                default.service.close()
            except Exception:
                pass
        for n in names:
            # already popped
            pass

    @property
    def service(self) -> Optional[GraphService]:
        binding = self.get()
        return binding.service if binding else None

    @property
    def streams(self) -> Optional[StreamSessionStore]:
        binding = self.get()
        return binding.streams if binding else None


# Module-level process registry (one service per MCP server process by default).
_REGISTRY = GraphServiceRegistry()


def get_registry() -> GraphServiceRegistry:
    return _REGISTRY


def bind_graph_service(
    service: GraphService,
    *,
    owns_service: bool = False,
    catalog_path: Optional[PathLike] = None,
    storage_path: Optional[PathLike] = None,
    name: Optional[str] = None,
) -> GraphServiceBinding:
    return _REGISTRY.bind(
        service,
        owns_service=owns_service,
        catalog_path=catalog_path,
        storage_path=storage_path,
        name=name,
    )


def open_graph_service(
    catalog_path: PathLike,
    *,
    storage_path: Optional[PathLike] = None,
    authorizer: Any = None,
    name: Optional[str] = None,
    force: bool = False,
    **kwargs: Any,
) -> GraphServiceBinding:
    return _REGISTRY.open(
        catalog_path,
        storage_path=storage_path,
        authorizer=authorizer,
        name=name,
        force=force,
        **kwargs,
    )


def get_graph_service(
    *,
    catalog_path: Optional[PathLike] = None,
    storage_path: Optional[PathLike] = None,
    name: Optional[str] = None,
) -> GraphService:
    """Resolve the server-owned GraphService (open from env/args if needed)."""
    return _REGISTRY.get_or_open(
        catalog_path=catalog_path,
        storage_path=storage_path,
        name=name,
    ).service


def get_graph_service_binding(
    *,
    catalog_path: Optional[PathLike] = None,
    storage_path: Optional[PathLike] = None,
    name: Optional[str] = None,
) -> GraphServiceBinding:
    return _REGISTRY.get_or_open(
        catalog_path=catalog_path,
        storage_path=storage_path,
        name=name,
    )


def reset_graph_service_registry() -> None:
    """Test helper: close and clear the process registry."""
    _REGISTRY.reset()


__all__ = [
    "ENV_CATALOG",
    "ENV_STORE",
    "ENV_HOLDER",
    "TenantScopeAuthorizer",
    "StreamSession",
    "StreamSessionStore",
    "GraphServiceBinding",
    "GraphServiceRegistry",
    "get_registry",
    "bind_graph_service",
    "open_graph_service",
    "get_graph_service",
    "get_graph_service_binding",
    "reset_graph_service_registry",
]
