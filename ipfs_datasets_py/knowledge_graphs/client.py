"""Stable versioned Python client surface for knowledge graphs (KGP-017).

``Client`` / ``AsyncClient`` are thin, production façades over a long-lived
:class:`~ipfs_datasets_py.knowledge_graphs.service.GraphService`. They:

* bind to configured catalog (+ payload storage) state and never invent an
  ambient empty graph;
* share that service among multiple client handles when desired;
* reopen committed graphs after process restart via the same durable paths;
* expose sync/async streaming of query rows and context-manager lifecycle;
* import only the service control plane — optional backends (spaCy, torch,
  neo4j drivers, ipfs_kit, …) are **not** import-time requirements.

Contract: ``kg-python-client/v1`` over ``kg-service-contract/v1``.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    AsyncIterator,
    Dict,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from ipfs_datasets_py.knowledge_graphs.service import (
    CONTRACT_VERSION,
    QUERY_ENVELOPE_VERSION,
    TYPED_ERROR_CODES,
    GraphService,
    GraphTarget,
    GraphTargetError,
    LifecycleRequest,
    LifecycleResult,
    QueryResultEnvelope,
    TypedError,
)

# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

CLIENT_API_VERSION = "kg-python-client/v1"
"""Public Python client API version (independent of service contract)."""

PathLike = Union[str, Path]
TargetLike = Union[GraphTarget, Mapping[str, Any], str]
JSONDict = Dict[str, Any]


# ---------------------------------------------------------------------------
# Typed errors raised by the client surface
# ---------------------------------------------------------------------------


class ServiceError(Exception):
    """Raised when a lifecycle result has ``status=error``.

    Surfaces map :class:`TypedError` into this exception so callers can catch
    a closed vocabulary of ``code`` values without inspecting envelopes.
    """

    def __init__(
        self,
        error: TypedError,
        *,
        operation: Optional[str] = None,
        target: Optional[GraphTarget] = None,
        request_id: Optional[str] = None,
        result: Optional[LifecycleResult] = None,
    ) -> None:
        super().__init__(error.message)
        self.error = error
        self.code = error.code
        self.message = error.message
        self.retryable = error.retryable
        self.details = dict(error.details or {})
        self.cause_code = error.cause_code
        self.operation = operation
        self.target = target
        self.request_id = request_id
        self.result = result

    def to_json_dict(self) -> JSONDict:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": dict(self.details),
            "cause_code": self.cause_code,
            "operation": self.operation,
            "target": self.target.to_json_dict() if self.target else None,
            "request_id": self.request_id,
        }

    @classmethod
    def from_result(cls, result: LifecycleResult) -> "ServiceError":
        if result.error is None:
            raise ValueError("LifecycleResult has no error")
        return cls(
            result.error,
            operation=result.operation,
            target=result.target,
            request_id=result.request_id,
            result=result,
        )


class ClientClosedError(ServiceError):
    """Raised when a method is called on a closed client."""

    def __init__(self, message: str = "Client is closed") -> None:
        err = TypedError.of("INVALID_REQUEST", message)
        super().__init__(err, operation=None)


def raise_for_status(result: LifecycleResult) -> LifecycleResult:
    """Return *result* or raise :class:`ServiceError` when ``status=error``."""
    if not result.ok:
        raise ServiceError.from_result(result)
    return result


# ---------------------------------------------------------------------------
# Configuration (shared across client handles bound to the same paths)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClientConfig:
    """Durable configuration shared by clients bound to the same catalog."""

    catalog_path: Path
    storage_path: Optional[Path] = None
    holder_id: Optional[str] = None

    def to_json_dict(self) -> JSONDict:
        return {
            "catalog_path": str(self.catalog_path),
            "storage_path": str(self.storage_path) if self.storage_path else None,
            "holder_id": self.holder_id,
            "client_api_version": CLIENT_API_VERSION,
            "contract_version": CONTRACT_VERSION,
        }


# ---------------------------------------------------------------------------
# Query stream pages (lightweight; no query.runtime / optional deps)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StreamPage:
    """One page of query rows yielded by :meth:`Client.stream_query`."""

    columns: List[str]
    rows: List[Any]
    page_index: int
    offset: int
    row_count: int
    exhausted: bool
    truncated: bool
    revision: Optional[str]
    target: Optional[GraphTarget]
    statistics: Dict[str, Any]
    schema: str
    warnings: Tuple[str, ...] = ()
    envelope_version: str = QUERY_ENVELOPE_VERSION

    def to_json_dict(self) -> JSONDict:
        return {
            "envelope_version": self.envelope_version,
            "schema": self.schema,
            "columns": list(self.columns),
            "rows": list(self.rows),
            "page_index": self.page_index,
            "offset": self.offset,
            "row_count": self.row_count,
            "exhausted": self.exhausted,
            "truncated": self.truncated,
            "revision": self.revision,
            "target": self.target.to_json_dict() if self.target else None,
            "statistics": dict(self.statistics),
            "warnings": list(self.warnings),
        }


def _page_rows(
    columns: Sequence[str],
    rows: Sequence[Any],
    *,
    page_size: int,
    revision: Optional[str],
    target: Optional[GraphTarget],
    statistics: Mapping[str, Any],
    schema: str,
    truncated: bool,
    warnings: Sequence[str],
) -> Iterator[StreamPage]:
    if page_size < 1:
        raise ValueError("page_size must be >= 1")
    total = len(rows)
    if total == 0:
        yield StreamPage(
            columns=list(columns),
            rows=[],
            page_index=0,
            offset=0,
            row_count=0,
            exhausted=True,
            truncated=bool(truncated),
            revision=revision,
            target=target,
            statistics=dict(statistics),
            schema=schema,
            warnings=tuple(warnings),
        )
        return
    page_index = 0
    offset = 0
    while offset < total:
        chunk = list(rows[offset : offset + page_size])
        next_offset = offset + len(chunk)
        exhausted = next_offset >= total
        yield StreamPage(
            columns=list(columns),
            rows=chunk,
            page_index=page_index,
            offset=offset,
            row_count=len(chunk),
            exhausted=exhausted,
            truncated=bool(truncated) and exhausted,
            revision=revision,
            target=target,
            statistics=dict(statistics),
            schema=schema,
            warnings=tuple(warnings),
        )
        page_index += 1
        offset = next_offset


# ---------------------------------------------------------------------------
# Transaction handle (context manager)
# ---------------------------------------------------------------------------


class Transaction:
    """Explicit transaction boundary bound to a :class:`Client` and target.

    On successful exit of the context manager the transaction is committed
    (requires ``idempotency_key``). On exception it is rolled back.
    """

    def __init__(
        self,
        client: "Client",
        target: TargetLike,
        *,
        idempotency_key: Optional[str] = None,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
        raise_on_error: bool = True,
    ) -> None:
        self._client = client
        self._target = target
        self._idempotency_key = idempotency_key
        self._params = dict(params or {})
        self._auth = auth
        self._request_id = request_id
        self._budgets = budgets
        self._raise_on_error = raise_on_error
        self.transaction_id: Optional[str] = None
        self.begin_result: Optional[LifecycleResult] = None
        self.commit_result: Optional[LifecycleResult] = None
        self.rollback_result: Optional[LifecycleResult] = None
        self.state: str = "init"
        self._entered = False

    def __enter__(self) -> "Transaction":
        self._entered = True
        result = self._client.begin_tx(
            self._target,
            params=self._params,
            auth=self._auth,
            request_id=self._request_id,
            budgets=self._budgets,
            idempotency_key=self._idempotency_key,
            raise_on_error=self._raise_on_error,
        )
        self.begin_result = result
        if result.ok and result.result:
            self.transaction_id = str(result.result.get("transaction_id"))
            self.state = str(result.result.get("state") or "open")
        else:
            self.state = "error"
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.transaction_id is None:
            return None
        params = {"transaction_id": self.transaction_id}
        if exc_type is not None:
            self.rollback_result = self._client.rollback_tx(
                self._target,
                params=params,
                auth=self._auth,
                raise_on_error=False,
            )
            self.state = "rolled_back"
            return None
        if not self._idempotency_key:
            # Cannot commit without idempotency key; roll back to free lease.
            self.rollback_result = self._client.rollback_tx(
                self._target,
                params=params,
                auth=self._auth,
                raise_on_error=False,
            )
            self.state = "rolled_back"
            raise ValueError(
                "Transaction.commit requires idempotency_key; "
                "pass idempotency_key= to Client.transaction()"
            )
        self.commit_result = self._client.commit_tx(
            self._target,
            idempotency_key=self._idempotency_key,
            params=params,
            auth=self._auth,
            raise_on_error=self._raise_on_error,
        )
        if self.commit_result.ok:
            self.state = "committed"
        else:
            self.state = "error"
        return None

    def stage(
        self,
        *,
        entities: Optional[Sequence[Mapping[str, Any]]] = None,
        relationships: Optional[Sequence[Mapping[str, Any]]] = None,
        delete_entity_ids: Optional[Sequence[Any]] = None,
        **extra: Any,
    ) -> LifecycleResult:
        """Stage mutations into this open transaction via ``write``."""
        if self.transaction_id is None:
            raise RuntimeError("transaction is not open")
        params: JSONDict = {
            "transaction_id": self.transaction_id,
            "entities": list(entities or []),
            "relationships": list(relationships or []),
        }
        if delete_entity_ids is not None:
            params["delete_entity_ids"] = list(delete_entity_ids)
        params.update(extra)
        return self._client.write(
            self._target,
            idempotency_key=self._idempotency_key
            or f"tx-stage-{self.transaction_id}",
            params=params,
            auth=self._auth,
            raise_on_error=self._raise_on_error,
        )


# ---------------------------------------------------------------------------
# Sync Client
# ---------------------------------------------------------------------------


class Client:
    """Synchronous, versioned Python client for production graph lifecycle.

    Prefer :meth:`open` against durable catalog/storage paths. Multiple
    :class:`Client` instances may :meth:`share` the same underlying
    :class:`GraphService` so configured catalog state is process-shared.
    A **new process** reopens committed graphs by constructing another
    client with the same paths (OSR-6).
    """

    api_version: str = CLIENT_API_VERSION

    def __init__(
        self,
        service: GraphService,
        *,
        owns_service: bool = False,
        config: Optional[ClientConfig] = None,
        default_auth: Optional[Mapping[str, Any]] = None,
        raise_on_error: bool = False,
    ) -> None:
        if service is None:
            raise ValueError("service is required")
        self._service = service
        self._owns_service = bool(owns_service)
        self._config = config
        self._default_auth = dict(default_auth) if default_auth else None
        self._raise_on_error = bool(raise_on_error)
        self._closed = False
        self._lock = threading.RLock()

    # -- construction -------------------------------------------------------

    @classmethod
    def open(
        cls,
        catalog_path: PathLike,
        *,
        storage_path: Optional[PathLike] = None,
        authorizer: Any = None,
        clock: Any = None,
        audit: Any = None,
        faults: Any = None,
        holder_id: Optional[str] = None,
        default_auth: Optional[Mapping[str, Any]] = None,
        raise_on_error: bool = False,
        **catalog_kwargs: Any,
    ) -> "Client":
        """Open a client bound to durable catalog (+ payload) paths.

        Does **not** create a default graph. Callers must ``create`` or
        ``open_graph`` an explicit :class:`GraphTarget`.
        """
        cat = Path(catalog_path)
        store = Path(storage_path) if storage_path is not None else None
        service = GraphService.open(
            cat,
            storage_path=store,
            authorizer=authorizer,
            clock=clock,
            audit=audit,
            faults=faults,
            holder_id=holder_id,
            **catalog_kwargs,
        )
        config = ClientConfig(
            catalog_path=cat.resolve(),
            storage_path=store.resolve() if store is not None else None,
            holder_id=holder_id or service.holder_id,
        )
        return cls(
            service,
            owns_service=True,
            config=config,
            default_auth=default_auth,
            raise_on_error=raise_on_error,
        )

    @classmethod
    def from_service(
        cls,
        service: GraphService,
        *,
        owns_service: bool = False,
        config: Optional[ClientConfig] = None,
        default_auth: Optional[Mapping[str, Any]] = None,
        raise_on_error: bool = False,
    ) -> "Client":
        """Wrap an existing :class:`GraphService` (shared control plane)."""
        return cls(
            service,
            owns_service=owns_service,
            config=config,
            default_auth=default_auth,
            raise_on_error=raise_on_error,
        )

    def share(
        self,
        *,
        default_auth: Optional[Mapping[str, Any]] = None,
        raise_on_error: Optional[bool] = None,
    ) -> "Client":
        """Return a new client handle that shares this client's service.

        The returned client never owns the service; closing it does not close
        the underlying catalog/storage.
        """
        self._ensure_open()
        return Client(
            self._service,
            owns_service=False,
            config=self._config,
            default_auth=default_auth
            if default_auth is not None
            else self._default_auth,
            raise_on_error=self._raise_on_error
            if raise_on_error is None
            else raise_on_error,
        )

    # -- properties ---------------------------------------------------------

    @property
    def service(self) -> GraphService:
        self._ensure_open()
        return self._service

    @property
    def config(self) -> Optional[ClientConfig]:
        return self._config

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def contract_version(self) -> str:
        return CONTRACT_VERSION

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._owns_service:
                try:
                    self._service.close()
                except Exception:
                    pass

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise ClientClosedError()

    def _auth(
        self, auth: Optional[Mapping[str, Any]]
    ) -> Optional[Mapping[str, Any]]:
        if auth is not None:
            return auth
        return self._default_auth

    def _finish(
        self, result: LifecycleResult, *, raise_on_error: Optional[bool]
    ) -> LifecycleResult:
        should = self._raise_on_error if raise_on_error is None else raise_on_error
        if should:
            return raise_for_status(result)
        return result

    # -- lifecycle operations -----------------------------------------------

    def execute(
        self,
        request: LifecycleRequest,
        *,
        raise_on_error: Optional[bool] = None,
    ) -> LifecycleResult:
        self._ensure_open()
        return self._finish(self._service.execute(request), raise_on_error=raise_on_error)

    def create(
        self,
        target: TargetLike,
        *,
        idempotency_key: Optional[str] = None,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
        raise_on_error: Optional[bool] = None,
    ) -> LifecycleResult:
        self._ensure_open()
        return self._finish(
            self._service.create(
                target,
                idempotency_key=idempotency_key,
                params=params,
                auth=self._auth(auth),
                request_id=request_id,
                budgets=budgets,
            ),
            raise_on_error=raise_on_error,
        )

    def list(
        self,
        target: TargetLike,
        *,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
        raise_on_error: Optional[bool] = None,
    ) -> LifecycleResult:
        self._ensure_open()
        return self._finish(
            self._service.list(
                target,
                params=params,
                auth=self._auth(auth),
                request_id=request_id,
                budgets=budgets,
            ),
            raise_on_error=raise_on_error,
        )

    def describe(
        self,
        target: TargetLike,
        *,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
        raise_on_error: Optional[bool] = None,
    ) -> LifecycleResult:
        self._ensure_open()
        return self._finish(
            self._service.describe(
                target,
                params=params,
                auth=self._auth(auth),
                request_id=request_id,
                budgets=budgets,
            ),
            raise_on_error=raise_on_error,
        )

    def open_graph(
        self,
        target: TargetLike,
        *,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
        raise_on_error: Optional[bool] = None,
    ) -> LifecycleResult:
        """Resolve a target to an immutable revision snapshot (operation ``open``)."""
        self._ensure_open()
        return self._finish(
            self._service.open_graph(
                target,
                params=params,
                auth=self._auth(auth),
                request_id=request_id,
                budgets=budgets,
            ),
            raise_on_error=raise_on_error,
        )

    def branch(
        self,
        target: TargetLike,
        *,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        raise_on_error: Optional[bool] = None,
    ) -> LifecycleResult:
        self._ensure_open()
        return self._finish(
            self._service.branch(
                target,
                params=params,
                auth=self._auth(auth),
                request_id=request_id,
                budgets=budgets,
                idempotency_key=idempotency_key,
            ),
            raise_on_error=raise_on_error,
        )

    def delete(
        self,
        target: TargetLike,
        *,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        raise_on_error: Optional[bool] = None,
    ) -> LifecycleResult:
        self._ensure_open()
        return self._finish(
            self._service.delete(
                target,
                params=params,
                auth=self._auth(auth),
                request_id=request_id,
                budgets=budgets,
                idempotency_key=idempotency_key,
            ),
            raise_on_error=raise_on_error,
        )

    def write(
        self,
        target: TargetLike,
        *,
        idempotency_key: str,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
        raise_on_error: Optional[bool] = None,
    ) -> LifecycleResult:
        self._ensure_open()
        return self._finish(
            self._service.write(
                target,
                idempotency_key=idempotency_key,
                params=params,
                auth=self._auth(auth),
                request_id=request_id,
                budgets=budgets,
            ),
            raise_on_error=raise_on_error,
        )

    def query(
        self,
        target: TargetLike,
        *,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
        raise_on_error: Optional[bool] = None,
    ) -> LifecycleResult:
        self._ensure_open()
        return self._finish(
            self._service.query(
                target,
                params=params,
                auth=self._auth(auth),
                request_id=request_id,
                budgets=budgets,
            ),
            raise_on_error=raise_on_error,
        )

    def begin_tx(
        self,
        target: TargetLike,
        *,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        raise_on_error: Optional[bool] = None,
    ) -> LifecycleResult:
        self._ensure_open()
        return self._finish(
            self._service.begin_tx(
                target,
                params=params,
                auth=self._auth(auth),
                request_id=request_id,
                budgets=budgets,
                idempotency_key=idempotency_key,
            ),
            raise_on_error=raise_on_error,
        )

    def commit_tx(
        self,
        target: TargetLike,
        *,
        idempotency_key: str,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
        raise_on_error: Optional[bool] = None,
    ) -> LifecycleResult:
        self._ensure_open()
        return self._finish(
            self._service.commit_tx(
                target,
                idempotency_key=idempotency_key,
                params=params,
                auth=self._auth(auth),
                request_id=request_id,
                budgets=budgets,
            ),
            raise_on_error=raise_on_error,
        )

    def rollback_tx(
        self,
        target: TargetLike,
        *,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
        raise_on_error: Optional[bool] = None,
    ) -> LifecycleResult:
        self._ensure_open()
        return self._finish(
            self._service.rollback_tx(
                target,
                params=params,
                auth=self._auth(auth),
                request_id=request_id,
                budgets=budgets,
            ),
            raise_on_error=raise_on_error,
        )

    def transaction(
        self,
        target: TargetLike,
        *,
        idempotency_key: Optional[str] = None,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
        raise_on_error: bool = True,
    ) -> Transaction:
        """Return a context-managed :class:`Transaction` on this client."""
        self._ensure_open()
        return Transaction(
            self,
            target,
            idempotency_key=idempotency_key,
            params=params,
            auth=self._auth(auth),
            request_id=request_id,
            budgets=budgets,
            raise_on_error=raise_on_error,
        )

    # -- streaming ----------------------------------------------------------

    def stream_query(
        self,
        target: TargetLike,
        *,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
        page_size: int = 100,
        raise_on_error: Optional[bool] = None,
    ) -> Iterator[StreamPage]:
        """Run a query and yield :class:`StreamPage` chunks of rows.

        Fetches via the service once (respecting budgets), then pages locally
        so streaming does not pull optional query backends at import time.
        """
        result = self.query(
            target,
            params=params,
            auth=auth,
            request_id=request_id,
            budgets=budgets,
            raise_on_error=raise_on_error,
        )
        if not result.ok:
            # When raise_on_error is False, yield nothing (caller inspects result).
            return
            yield  # pragma: no cover — makes this a generator
        payload = result.result or {}
        columns = list(payload.get("columns") or [])
        rows = list(payload.get("rows") or [])
        yield from _page_rows(
            columns,
            rows,
            page_size=page_size,
            revision=payload.get("revision"),
            target=result.target,
            statistics=payload.get("statistics") or {},
            schema=str(payload.get("schema") or "kg-query-row/v1"),
            truncated=bool(payload.get("truncated")),
            warnings=payload.get("warnings") or [],
        )

    def stream_rows(
        self,
        target: TargetLike,
        *,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
        raise_on_error: Optional[bool] = None,
    ) -> Iterator[Any]:
        """Yield individual rows from a query (sync streaming)."""
        for page in self.stream_query(
            target,
            params=params,
            auth=auth,
            request_id=request_id,
            budgets=budgets,
            page_size=max(
                1,
                int((budgets or {}).get("page_size") or 256),
            ),
            raise_on_error=raise_on_error,
        ):
            for row in page.rows:
                yield row


# ---------------------------------------------------------------------------
# Async Client
# ---------------------------------------------------------------------------


class AsyncClient:
    """Async façade over :class:`Client` / :class:`GraphService`.

    Lifecycle methods run the shared sync service via ``asyncio.to_thread``
    so the event loop is not blocked. Streaming is exposed as async
    iterators. Multiple async clients may share one configured service.
    """

    api_version: str = CLIENT_API_VERSION

    def __init__(self, client: Client, *, owns_client: bool = False) -> None:
        if client is None:
            raise ValueError("client is required")
        self._client = client
        self._owns_client = bool(owns_client)
        self._closed = False

    @classmethod
    async def open(
        cls,
        catalog_path: PathLike,
        *,
        storage_path: Optional[PathLike] = None,
        authorizer: Any = None,
        clock: Any = None,
        audit: Any = None,
        faults: Any = None,
        holder_id: Optional[str] = None,
        default_auth: Optional[Mapping[str, Any]] = None,
        raise_on_error: bool = False,
        **catalog_kwargs: Any,
    ) -> "AsyncClient":
        def _open() -> Client:
            return Client.open(
                catalog_path,
                storage_path=storage_path,
                authorizer=authorizer,
                clock=clock,
                audit=audit,
                faults=faults,
                holder_id=holder_id,
                default_auth=default_auth,
                raise_on_error=raise_on_error,
                **catalog_kwargs,
            )

        client = await asyncio.to_thread(_open)
        return cls(client, owns_client=True)

    @classmethod
    def from_client(
        cls, client: Client, *, owns_client: bool = False
    ) -> "AsyncClient":
        return cls(client, owns_client=owns_client)

    @classmethod
    def from_service(
        cls,
        service: GraphService,
        *,
        owns_service: bool = False,
        config: Optional[ClientConfig] = None,
        default_auth: Optional[Mapping[str, Any]] = None,
        raise_on_error: bool = False,
    ) -> "AsyncClient":
        sync = Client.from_service(
            service,
            owns_service=owns_service,
            config=config,
            default_auth=default_auth,
            raise_on_error=raise_on_error,
        )
        return cls(sync, owns_client=True)

    def share(self, **kwargs: Any) -> "AsyncClient":
        return AsyncClient(self._client.share(**kwargs), owns_client=True)

    @property
    def client(self) -> Client:
        self._ensure_open()
        return self._client

    @property
    def service(self) -> GraphService:
        return self._client.service

    @property
    def config(self) -> Optional[ClientConfig]:
        return self._client.config

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def contract_version(self) -> str:
        return CONTRACT_VERSION

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            await asyncio.to_thread(self._client.close)

    async def __aenter__(self) -> "AsyncClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise ClientClosedError("AsyncClient is closed")

    async def _run(self, fn, *args: Any, **kwargs: Any) -> Any:
        self._ensure_open()
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def create(self, target: TargetLike, **kwargs: Any) -> LifecycleResult:
        return await self._run(self._client.create, target, **kwargs)

    async def list(self, target: TargetLike, **kwargs: Any) -> LifecycleResult:
        return await self._run(self._client.list, target, **kwargs)

    async def describe(self, target: TargetLike, **kwargs: Any) -> LifecycleResult:
        return await self._run(self._client.describe, target, **kwargs)

    async def open_graph(self, target: TargetLike, **kwargs: Any) -> LifecycleResult:
        return await self._run(self._client.open_graph, target, **kwargs)

    async def branch(self, target: TargetLike, **kwargs: Any) -> LifecycleResult:
        return await self._run(self._client.branch, target, **kwargs)

    async def delete(self, target: TargetLike, **kwargs: Any) -> LifecycleResult:
        return await self._run(self._client.delete, target, **kwargs)

    async def write(
        self, target: TargetLike, *, idempotency_key: str, **kwargs: Any
    ) -> LifecycleResult:
        return await self._run(
            self._client.write, target, idempotency_key=idempotency_key, **kwargs
        )

    async def query(self, target: TargetLike, **kwargs: Any) -> LifecycleResult:
        return await self._run(self._client.query, target, **kwargs)

    async def begin_tx(self, target: TargetLike, **kwargs: Any) -> LifecycleResult:
        return await self._run(self._client.begin_tx, target, **kwargs)

    async def commit_tx(
        self, target: TargetLike, *, idempotency_key: str, **kwargs: Any
    ) -> LifecycleResult:
        return await self._run(
            self._client.commit_tx,
            target,
            idempotency_key=idempotency_key,
            **kwargs,
        )

    async def rollback_tx(self, target: TargetLike, **kwargs: Any) -> LifecycleResult:
        return await self._run(self._client.rollback_tx, target, **kwargs)

    async def execute(
        self, request: LifecycleRequest, **kwargs: Any
    ) -> LifecycleResult:
        return await self._run(self._client.execute, request, **kwargs)

    async def stream_query(
        self,
        target: TargetLike,
        *,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
        page_size: int = 100,
        raise_on_error: Optional[bool] = None,
    ) -> AsyncIterator[StreamPage]:
        pages = await self._run(
            lambda: list(
                self._client.stream_query(
                    target,
                    params=params,
                    auth=auth,
                    request_id=request_id,
                    budgets=budgets,
                    page_size=page_size,
                    raise_on_error=raise_on_error,
                )
            )
        )
        for page in pages:
            yield page

    async def stream_rows(
        self,
        target: TargetLike,
        *,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
        raise_on_error: Optional[bool] = None,
    ) -> AsyncIterator[Any]:
        async for page in self.stream_query(
            target,
            params=params,
            auth=auth,
            request_id=request_id,
            budgets=budgets,
            raise_on_error=raise_on_error,
        ):
            for row in page.rows:
                yield row


__all__ = [
    "CLIENT_API_VERSION",
    "CONTRACT_VERSION",
    "QUERY_ENVELOPE_VERSION",
    "TYPED_ERROR_CODES",
    "ClientConfig",
    "Client",
    "AsyncClient",
    "Transaction",
    "StreamPage",
    "ServiceError",
    "ClientClosedError",
    "raise_for_status",
    "GraphTarget",
    "GraphTargetError",
    "TypedError",
    "LifecycleRequest",
    "LifecycleResult",
    "QueryResultEnvelope",
    "GraphService",
]
