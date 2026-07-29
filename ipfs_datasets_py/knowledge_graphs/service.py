"""Long-lived GraphService orchestration (KGP-006).

All production graph lifecycle operations enter through :class:`GraphService`.
Every request resolves an explicit :class:`GraphTarget`; the service never
invents an ambient empty graph or a process-local identity.

Dependency injection (authorization, storage, clock, faults, audit) keeps the
control plane testable without coupling to transport or optional backends.

Contract: ``kg-service-contract/v1``
(``docs/architecture/knowledge_graphs_service_contract.md``).
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    Union,
)

from ipfs_datasets_py.knowledge_graphs.catalog import (
    CatalogError,
    DEFAULT_BRANCH,
    DEFAULT_STORAGE_PROFILE,
    GraphCatalog,
    bootstrap_revision_id,
    open_catalog,
    request_hash,
)

# ---------------------------------------------------------------------------
# Contract constants
# ---------------------------------------------------------------------------

CONTRACT_VERSION = "kg-service-contract/v1"
QUERY_ENVELOPE_VERSION = "kg-query-envelope/v1"

LIFECYCLE_OPERATIONS = frozenset(
    {
        "create",
        "list",
        "describe",
        "open",
        "branch",
        "delete",
        "write",
        "query",
        "begin_tx",
        "commit_tx",
        "rollback_tx",
    }
)

TYPED_ERROR_CODES = frozenset(
    {
        "INVALID_REQUEST",
        "INVALID_TARGET",
        "NOT_FOUND",
        "ALREADY_EXISTS",
        "CONFLICT",
        "FENCED",
        "UNAUTHORIZED",
        "FORBIDDEN",
        "BUDGET_EXCEEDED",
        "QUERY_PARSE",
        "QUERY_EXECUTION",
        "STORAGE",
        "INTEGRITY",
        "NOT_IMPLEMENTED",
        "INTERNAL",
    }
)

_DEFAULT_RETRYABLE: Mapping[str, bool] = {
    "INVALID_REQUEST": False,
    "INVALID_TARGET": False,
    "NOT_FOUND": False,
    "ALREADY_EXISTS": False,
    "CONFLICT": True,
    "FENCED": False,
    "UNAUTHORIZED": False,
    "FORBIDDEN": False,
    "BUDGET_EXCEEDED": True,
    "QUERY_PARSE": False,
    "QUERY_EXECUTION": False,
    "STORAGE": True,
    "INTEGRITY": False,
    "NOT_IMPLEMENTED": False,
    "INTERNAL": False,
}

STORAGE_PROFILES = frozenset({"parquet", "ipfs_ipld", "ipfs_kit", "hybrid"})

_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]{0,62}[a-z0-9])?$")
# Revisions (CIDs / catalog ids) are not slugs.
_REVISION_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")

_URI_BRANCH = re.compile(
    r"^kg://(?P<tenant>[^/]+)/(?P<graph_id>[^/]+)/branches/(?P<branch>[^/]+)$"
)
_URI_REV = re.compile(
    r"^kg://(?P<tenant>[^/]+)/(?P<graph_id>[^/]+)/revisions/(?P<revision>[^/]+)$"
)
_URI_BASE = re.compile(r"^kg://(?P<tenant>[^/]+)/(?P<graph_id>[^/]+)$")

# Ability map used by the default authorizer (MCP++ UCAN vocabulary).
_OP_ABILITIES: Mapping[str, str] = {
    "create": "graph/admin",
    "list": "graph/list",
    "describe": "graph/read",
    "open": "graph/read",
    "branch": "graph/admin",
    "delete": "graph/admin",
    "write": "graph/write",
    "query": "graph/query",
    "begin_tx": "graph/write",
    "commit_tx": "graph/write",
    "rollback_tx": "graph/write",
}

PathLike = Union[str, Path]
JSONDict = Dict[str, Any]


# ---------------------------------------------------------------------------
# Target validation
# ---------------------------------------------------------------------------


class GraphTargetError(ValueError):
    """Invalid GraphTarget; ``code`` matches service-contract TARGET_* codes."""

    def __init__(self, code: str, message: str, *, details: Optional[JSONDict] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: JSONDict = dict(details or {})


def _validate_slug(value: Any, *, field: str, code_empty: str) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise GraphTargetError(code_empty, f"{field} must be non-empty", details={"field": field})
    if not isinstance(value, str):
        raise GraphTargetError(
            "TARGET_BAD_SLUG",
            f"{field} must be a string",
            details={"field": field},
        )
    if value != value.strip():
        raise GraphTargetError(
            "TARGET_BAD_SLUG",
            f"{field} must not have surrounding whitespace",
            details={"field": field, "value": value},
        )
    if not _SLUG_RE.fullmatch(value):
        raise GraphTargetError(
            "TARGET_BAD_SLUG",
            f"{field} failed slug validation",
            details={"field": field, "value": value},
        )
    return value


def _validate_revision(value: Any, *, field: str = "revision") -> str:
    if value is None or not isinstance(value, str) or not value:
        raise GraphTargetError(
            "TARGET_BAD_URI",
            f"{field} must be a non-empty string",
            details={"field": field},
        )
    if not _REVISION_RE.fullmatch(value):
        raise GraphTargetError(
            "TARGET_BAD_URI",
            f"invalid revision id: {value!r}",
            details={"field": field, "value": value},
        )
    return value


def _validate_target_fields(
    tenant: str,
    graph_id: str,
    branch: Optional[str],
    revision: Optional[str],
    storage_profile: Optional[str],
    *,
    allow_empty_graph_id: bool = False,
) -> None:
    _validate_slug(tenant, field="tenant", code_empty="TARGET_EMPTY_TENANT")
    if allow_empty_graph_id and (graph_id is None or graph_id == ""):
        pass
    else:
        _validate_slug(graph_id, field="graph_id", code_empty="TARGET_EMPTY_GRAPH")
    if branch is not None:
        _validate_slug(branch, field="branch", code_empty="TARGET_BAD_SLUG")
    if revision is not None:
        _validate_revision(revision)
    if branch is not None and revision is not None:
        raise GraphTargetError(
            "TARGET_BRANCH_AND_REVISION",
            "branch and revision are mutually exclusive on GraphTarget",
        )
    if storage_profile is not None and storage_profile not in STORAGE_PROFILES:
        raise GraphTargetError(
            "TARGET_BAD_PROFILE",
            f"storage_profile must be one of {sorted(STORAGE_PROFILES)} or null",
            details={"value": storage_profile},
        )


@dataclass(frozen=True, slots=True)
class GraphTarget:
    """Canonical public address for a graph snapshot or branch head."""

    tenant: str
    graph_id: str
    branch: Optional[str] = None
    revision: Optional[str] = None
    storage_profile: Optional[str] = None

    def __post_init__(self) -> None:
        _validate_target_fields(
            self.tenant,
            self.graph_id,
            self.branch,
            self.revision,
            self.storage_profile,
        )

    @property
    def uri(self) -> str:
        base = f"kg://{self.tenant}/{self.graph_id}"
        if self.revision is not None:
            return f"{base}/revisions/{self.revision}"
        if self.branch is not None:
            return f"{base}/branches/{self.branch}"
        return base

    def to_json_dict(self) -> JSONDict:
        return {
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "branch": self.branch,
            "revision": self.revision,
            "storage_profile": self.storage_profile,
            "uri": self.uri,
        }

    def with_branch(self, branch: Optional[str]) -> "GraphTarget":
        return GraphTarget(
            tenant=self.tenant,
            graph_id=self.graph_id,
            branch=branch,
            revision=None,
            storage_profile=self.storage_profile,
        )

    def with_revision(self, revision: str) -> "GraphTarget":
        return GraphTarget(
            tenant=self.tenant,
            graph_id=self.graph_id,
            branch=None,
            revision=revision,
            storage_profile=self.storage_profile,
        )

    def with_profile(self, storage_profile: Optional[str]) -> "GraphTarget":
        return GraphTarget(
            tenant=self.tenant,
            graph_id=self.graph_id,
            branch=self.branch,
            revision=self.revision,
            storage_profile=storage_profile,
        )

    @classmethod
    def from_uri(
        cls,
        uri: str,
        *,
        storage_profile: Optional[str] = None,
    ) -> "GraphTarget":
        return parse_graph_target_uri(uri, storage_profile=storage_profile)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "GraphTarget":
        if not isinstance(data, Mapping):
            raise GraphTargetError("TARGET_BAD_URI", "target must be a mapping")
        return cls(
            tenant=data.get("tenant"),  # type: ignore[arg-type]
            graph_id=data.get("graph_id"),  # type: ignore[arg-type]
            branch=data.get("branch"),
            revision=data.get("revision"),
            storage_profile=data.get("storage_profile"),
        )


def parse_graph_target_uri(
    uri: str,
    *,
    storage_profile: Optional[str] = None,
) -> GraphTarget:
    if not isinstance(uri, str) or not uri:
        raise GraphTargetError("TARGET_BAD_URI", "uri must be a non-empty string")
    if not uri.startswith("kg://"):
        raise GraphTargetError("TARGET_BAD_URI", f"uri must use kg:// scheme: {uri!r}")
    for pattern in (_URI_BRANCH, _URI_REV, _URI_BASE):
        match = pattern.fullmatch(uri)
        if match:
            groups = match.groupdict()
            return GraphTarget(
                tenant=groups["tenant"],
                graph_id=groups["graph_id"],
                branch=groups.get("branch"),
                revision=groups.get("revision"),
                storage_profile=storage_profile,
            )
    raise GraphTargetError("TARGET_BAD_URI", f"uri does not match kg:// grammar: {uri!r}")


def require_open_selector(target: GraphTarget) -> None:
    """open/query require branch or revision (service contract §4.1)."""
    if target.branch is None and target.revision is None:
        raise GraphTargetError(
            "TARGET_AMBIGUOUS",
            "operation requires branch or revision",
        )


def require_write_branch(target: GraphTarget) -> str:
    if target.branch is None:
        raise GraphTargetError(
            "TARGET_AMBIGUOUS",
            "write/begin_tx require a branch",
        )
    if target.revision is not None:
        raise GraphTargetError(
            "TARGET_BRANCH_AND_REVISION",
            "writers must name a branch, not a revision pin",
        )
    return target.branch


# ---------------------------------------------------------------------------
# Lifecycle envelopes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypedError:
    code: str
    message: str
    retryable: bool
    details: Dict[str, Any] = field(default_factory=dict)
    cause_code: Optional[str] = None

    def __post_init__(self) -> None:
        if self.code not in TYPED_ERROR_CODES:
            raise ValueError(f"unknown error code: {self.code!r}")
        object.__setattr__(self, "details", dict(self.details or {}))

    def to_json_dict(self) -> JSONDict:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": dict(self.details),
            "cause_code": self.cause_code,
        }

    @classmethod
    def of(
        cls,
        code: str,
        message: str,
        *,
        retryable: Optional[bool] = None,
        details: Optional[Mapping[str, Any]] = None,
        cause_code: Optional[str] = None,
    ) -> "TypedError":
        if code not in TYPED_ERROR_CODES:
            code = "INTERNAL"
        retry = (
            bool(_DEFAULT_RETRYABLE.get(code, False))
            if retryable is None
            else bool(retryable)
        )
        return cls(
            code=code,
            message=message,
            retryable=retry,
            details=dict(details or {}),
            cause_code=cause_code,
        )


@dataclass(frozen=True, slots=True)
class LifecycleRequest:
    operation: str
    target: GraphTarget
    contract_version: str = CONTRACT_VERSION
    idempotency_key: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    budgets: Optional[Dict[str, Any]] = None
    auth: Optional[Dict[str, Any]] = None
    request_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError(f"unsupported contract_version: {self.contract_version}")
        if self.operation not in LIFECYCLE_OPERATIONS:
            raise ValueError(f"unknown operation: {self.operation}")
        object.__setattr__(self, "params", dict(self.params or {}))
        if self.budgets is not None:
            object.__setattr__(self, "budgets", dict(self.budgets))
        if self.auth is not None:
            object.__setattr__(self, "auth", dict(self.auth))

    def to_json_dict(self) -> JSONDict:
        return {
            "contract_version": self.contract_version,
            "operation": self.operation,
            "target": self.target.to_json_dict(),
            "idempotency_key": self.idempotency_key,
            "params": dict(self.params or {}),
            "budgets": self.budgets,
            "auth": self.auth,
            "request_id": self.request_id,
        }


@dataclass(frozen=True, slots=True)
class LifecycleResult:
    status: str
    operation: str
    target: Optional[GraphTarget]
    result: Optional[Dict[str, Any]] = None
    error: Optional[TypedError] = None
    warnings: Tuple[str, ...] = ()
    request_id: Optional[str] = None
    authorization_receipt_ref: Optional[str] = None
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.status not in {"success", "error"}:
            raise ValueError("status must be success|error")
        if self.status == "error" and self.error is None:
            raise ValueError("error result requires TypedError")
        if self.status == "success" and self.error is not None:
            raise ValueError("success result must not include error")
        if self.error is not None and self.error.code not in TYPED_ERROR_CODES:
            raise ValueError(f"unknown error code: {self.error.code}")
        if self.warnings is None:
            object.__setattr__(self, "warnings", ())
        else:
            object.__setattr__(self, "warnings", tuple(self.warnings))
        if self.result is not None:
            object.__setattr__(self, "result", dict(self.result))

    def to_json_dict(self) -> JSONDict:
        return {
            "contract_version": self.contract_version,
            "status": self.status,
            "operation": self.operation,
            "target": self.target.to_json_dict() if self.target else None,
            "result": self.result,
            "error": self.error.to_json_dict() if self.error else None,
            "warnings": list(self.warnings),
            "request_id": self.request_id,
            "authorization_receipt_ref": self.authorization_receipt_ref,
        }

    @property
    def ok(self) -> bool:
        return self.status == "success"


@dataclass(frozen=True, slots=True)
class QueryResultEnvelope:
    """Versioned JSON-safe query envelope (``kg-query-envelope/v1``)."""

    schema: str
    target: GraphTarget
    revision: str
    columns: List[str]
    rows: List[Any]
    statistics: Dict[str, Any]
    query: Dict[str, Any]
    envelope_version: str = QUERY_ENVELOPE_VERSION
    cursor: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    provenance: Optional[Dict[str, Any]] = None
    authorization_receipt_ref: Optional[str] = None
    truncated: bool = False

    def to_json_dict(self) -> JSONDict:
        return {
            "envelope_version": self.envelope_version,
            "schema": self.schema,
            "target": self.target.to_json_dict(),
            "revision": self.revision,
            "columns": list(self.columns),
            "rows": list(self.rows),
            "row_count": len(self.rows),
            "cursor": self.cursor,
            "statistics": dict(self.statistics),
            "warnings": list(self.warnings),
            "provenance": self.provenance,
            "authorization_receipt_ref": self.authorization_receipt_ref,
            "truncated": bool(self.truncated),
            "query": dict(self.query),
        }


# ---------------------------------------------------------------------------
# Injectable dependency protocols and defaults
# ---------------------------------------------------------------------------


class Clock(Protocol):
    def now_iso(self) -> str:
        """Return ISO-8601 UTC timestamp with millisecond precision."""


class SystemClock:
    def now_iso(self) -> str:
        return (
            datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    allowed: bool
    principal: Optional[str]
    ability: str
    receipt_ref: str
    reason: Optional[str] = None
    code: Optional[str] = None  # UNAUTHORIZED | FORBIDDEN when denied

    def to_json_dict(self) -> JSONDict:
        return {
            "allowed": self.allowed,
            "principal": self.principal,
            "ability": self.ability,
            "receipt_ref": self.receipt_ref,
            "reason": self.reason,
            "code": self.code,
        }


class Authorizer(Protocol):
    def authorize(
        self,
        *,
        operation: str,
        target: GraphTarget,
        auth: Optional[Mapping[str, Any]],
        request_id: Optional[str],
    ) -> AuthorizationDecision:
        ...


class AllowAllAuthorizer:
    """Permissive authorizer for trusted in-process / test use."""

    def authorize(
        self,
        *,
        operation: str,
        target: GraphTarget,
        auth: Optional[Mapping[str, Any]],
        request_id: Optional[str],
    ) -> AuthorizationDecision:
        principal = None
        if auth:
            principal = auth.get("principal") or auth.get("subject")
        ability = _OP_ABILITIES.get(operation, "graph/admin")
        digest = hashlib.sha256(
            f"allow|{operation}|{target.uri}|{principal}|{request_id}".encode("utf-8")
        ).hexdigest()[:24]
        return AuthorizationDecision(
            allowed=True,
            principal=str(principal) if principal is not None else None,
            ability=ability,
            receipt_ref=f"auth-receipt-{digest}",
            reason="allow_all",
        )


class PrincipalAuthorizer:
    """Require a principal string in ``auth``; optional ability allow-list."""

    def __init__(
        self,
        *,
        allowed_abilities: Optional[Sequence[str]] = None,
        required_principal: bool = True,
    ) -> None:
        self._allowed = (
            frozenset(allowed_abilities) if allowed_abilities is not None else None
        )
        self._required_principal = required_principal

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
        digest_base = f"{operation}|{target.uri}|{principal}|{request_id}|{ability}"
        digest = hashlib.sha256(digest_base.encode("utf-8")).hexdigest()[:24]
        receipt = f"auth-receipt-{digest}"
        if self._required_principal and not principal:
            return AuthorizationDecision(
                allowed=False,
                principal=None,
                ability=ability,
                receipt_ref=receipt,
                reason="missing principal",
                code="UNAUTHORIZED",
            )
        if self._allowed is not None and ability not in self._allowed:
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


class AuditSink(Protocol):
    def emit(self, event: Mapping[str, Any]) -> None:
        ...


class NullAuditSink:
    def emit(self, event: Mapping[str, Any]) -> None:
        return None


class InMemoryAuditSink:
    """Collects audit events for tests."""

    def __init__(self) -> None:
        self.events: List[JSONDict] = []
        self._lock = threading.Lock()

    def emit(self, event: Mapping[str, Any]) -> None:
        with self._lock:
            self.events.append(dict(event))


class FaultInjector(Protocol):
    def maybe_raise(self, operation: str, phase: str) -> None:
        """Raise a controlled fault before/after a phase, or no-op."""


class NoFaults:
    def maybe_raise(self, operation: str, phase: str) -> None:
        return None


class ScriptedFaultInjector:
    """Raise once when ``(operation, phase)`` matches a scripted fault."""

    def __init__(
        self,
        faults: Optional[Mapping[Tuple[str, str], BaseException]] = None,
    ) -> None:
        self._faults: Dict[Tuple[str, str], BaseException] = dict(faults or {})
        self._hits: Dict[Tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def arm(self, operation: str, phase: str, exc: BaseException) -> None:
        with self._lock:
            self._faults[(operation, phase)] = exc

    def maybe_raise(self, operation: str, phase: str) -> None:
        key = (operation, phase)
        with self._lock:
            exc = self._faults.get(key)
            if exc is None:
                return
            self._hits[key] = self._hits.get(key, 0) + 1
            # One-shot by default.
            del self._faults[key]
        raise exc


# ---------------------------------------------------------------------------
# Snapshot storage (payload; catalog remains control-plane only)
# ---------------------------------------------------------------------------


@dataclass
class GraphSnapshot:
    """JSON-safe graph payload bound to an immutable revision."""

    tenant: str
    graph_id: str
    revision: str
    parent_revision: Optional[str]
    entities: List[JSONDict] = field(default_factory=list)
    relationships: List[JSONDict] = field(default_factory=list)
    metadata: JSONDict = field(default_factory=dict)

    def to_json_dict(self) -> JSONDict:
        return {
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "revision": self.revision,
            "parent_revision": self.parent_revision,
            "entities": list(self.entities),
            "relationships": list(self.relationships),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def empty(
        cls,
        tenant: str,
        graph_id: str,
        revision: str,
        *,
        parent_revision: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> "GraphSnapshot":
        return cls(
            tenant=tenant,
            graph_id=graph_id,
            revision=revision,
            parent_revision=parent_revision,
            entities=[],
            relationships=[],
            metadata=dict(metadata or {}),
        )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "GraphSnapshot":
        return cls(
            tenant=str(data["tenant"]),
            graph_id=str(data["graph_id"]),
            revision=str(data["revision"]),
            parent_revision=data.get("parent_revision"),
            entities=list(data.get("entities") or []),
            relationships=list(data.get("relationships") or []),
            metadata=dict(data.get("metadata") or {}),
        )

    def clone_for_revision(
        self,
        new_revision: str,
        *,
        parent_revision: Optional[str] = None,
    ) -> "GraphSnapshot":
        return GraphSnapshot(
            tenant=self.tenant,
            graph_id=self.graph_id,
            revision=new_revision,
            parent_revision=parent_revision if parent_revision is not None else self.revision,
            entities=[dict(e) for e in self.entities],
            relationships=[dict(r) for r in self.relationships],
            metadata=dict(self.metadata),
        )


class GraphStorage(Protocol):
    """Payload store for revision snapshots (durable across process restarts)."""

    def put_snapshot(self, snapshot: GraphSnapshot) -> None:
        ...

    def get_snapshot(
        self,
        tenant: str,
        graph_id: str,
        revision: str,
    ) -> Optional[GraphSnapshot]:
        ...

    def close(self) -> None:
        ...


class InMemoryGraphStorage:
    """Process-local snapshot store (not durable across process boundaries)."""

    def __init__(self) -> None:
        self._data: Dict[Tuple[str, str, str], GraphSnapshot] = {}
        self._lock = threading.RLock()

    def put_snapshot(self, snapshot: GraphSnapshot) -> None:
        key = (snapshot.tenant, snapshot.graph_id, snapshot.revision)
        with self._lock:
            self._data[key] = GraphSnapshot.from_mapping(snapshot.to_json_dict())

    def get_snapshot(
        self,
        tenant: str,
        graph_id: str,
        revision: str,
    ) -> Optional[GraphSnapshot]:
        with self._lock:
            snap = self._data.get((tenant, graph_id, revision))
            if snap is None:
                return None
            return GraphSnapshot.from_mapping(snap.to_json_dict())

    def close(self) -> None:
        with self._lock:
            self._data.clear()


class FileGraphStorage:
    """Directory-backed durable snapshot store (JSON files per revision)."""

    def __init__(self, root: PathLike) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._closed = False

    @property
    def path(self) -> Path:
        return self._root

    def _snapshot_path(self, tenant: str, graph_id: str, revision: str) -> Path:
        # Hash revision so filesystem-hostile CID characters stay safe.
        digest = hashlib.sha256(revision.encode("utf-8")).hexdigest()
        return self._root / tenant / graph_id / f"{digest}.json"

    def put_snapshot(self, snapshot: GraphSnapshot) -> None:
        if self._closed:
            raise CatalogError("STORAGE", "graph storage is closed")
        path = self._snapshot_path(snapshot.tenant, snapshot.graph_id, snapshot.revision)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = snapshot.to_json_dict()
        # Atomic replace: write temp then rename.
        tmp = path.with_suffix(path.suffix + f".tmp-{uuid.uuid4().hex}")
        with self._lock:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, sort_keys=True, separators=(",", ":"), allow_nan=False)
                fh.flush()
            tmp.replace(path)

    def get_snapshot(
        self,
        tenant: str,
        graph_id: str,
        revision: str,
    ) -> Optional[GraphSnapshot]:
        if self._closed:
            raise CatalogError("STORAGE", "graph storage is closed")
        path = self._snapshot_path(tenant, graph_id, revision)
        if not path.is_file():
            return None
        with self._lock:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        return GraphSnapshot.from_mapping(data)

    def close(self) -> None:
        self._closed = True


# ---------------------------------------------------------------------------
# Service-level transaction state (boundaries; full MVCC is KGP-007)
# ---------------------------------------------------------------------------


@dataclass
class _OpenTransaction:
    transaction_id: str
    tenant: str
    graph_id: str
    branch: str
    base_revision: str
    state: str  # open | prepared | committed | rolled_back
    staged_entities: List[JSONDict] = field(default_factory=list)
    staged_relationships: List[JSONDict] = field(default_factory=list)
    mutation_count: int = 0
    created_at: str = ""
    lease_id: Optional[str] = None
    lease_epoch: Optional[int] = None
    idempotency_key: Optional[str] = None


# ---------------------------------------------------------------------------
# GraphService
# ---------------------------------------------------------------------------


class GraphService:
    """Long-lived orchestration type for production graph lifecycle.

    The service is bound to a durable catalog (and optional payload storage).
    Construction never creates or attaches an ambient empty graph. Callers
    must pass an explicit :class:`GraphTarget` on every operation.

    A second :class:`GraphService` opened against the same catalog and storage
    paths reopens committed graphs after restart (OSR-6).
    """

    def __init__(
        self,
        catalog: GraphCatalog,
        *,
        storage: Optional[GraphStorage] = None,
        authorizer: Optional[Authorizer] = None,
        clock: Optional[Clock] = None,
        audit: Optional[AuditSink] = None,
        faults: Optional[FaultInjector] = None,
        close_catalog_on_close: bool = False,
        close_storage_on_close: bool = False,
        holder_id: Optional[str] = None,
    ) -> None:
        if catalog is None:
            raise ValueError("catalog is required")
        self._catalog = catalog
        self._storage: GraphStorage = storage if storage is not None else InMemoryGraphStorage()
        self._authorizer: Authorizer = (
            authorizer if authorizer is not None else AllowAllAuthorizer()
        )
        self._clock: Clock = clock if clock is not None else SystemClock()
        self._audit: AuditSink = audit if audit is not None else NullAuditSink()
        self._faults: FaultInjector = faults if faults is not None else NoFaults()
        self._close_catalog = close_catalog_on_close
        self._close_storage = close_storage_on_close
        self._holder_id = holder_id or f"gs-{uuid.uuid4().hex[:12]}"
        self._tx_lock = threading.RLock()
        self._transactions: Dict[str, _OpenTransaction] = {}
        self._closed = False
        # Intentionally no ambient / current graph handle.
        self._open_handles: Dict[str, JSONDict] = {}

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def open(
        cls,
        catalog_path: PathLike,
        *,
        storage_path: Optional[PathLike] = None,
        authorizer: Optional[Authorizer] = None,
        clock: Optional[Clock] = None,
        audit: Optional[AuditSink] = None,
        faults: Optional[FaultInjector] = None,
        holder_id: Optional[str] = None,
        **catalog_kwargs: Any,
    ) -> "GraphService":
        """Open a long-lived service bound to durable catalog (+ payload) paths.

        Does **not** create a default graph. Callers must ``create`` or ``open``
        an explicit :class:`GraphTarget`.
        """
        catalog = open_catalog(catalog_path, **catalog_kwargs)
        if storage_path is not None:
            storage: GraphStorage = FileGraphStorage(storage_path)
            close_storage = True
        else:
            # Co-locate payload storage next to the catalog for durable reopen.
            cat_path = Path(catalog_path)
            default_store = cat_path.parent / f"{cat_path.stem}.payloads"
            storage = FileGraphStorage(default_store)
            close_storage = True
        return cls(
            catalog,
            storage=storage,
            authorizer=authorizer,
            clock=clock,
            audit=audit,
            faults=faults,
            close_catalog_on_close=True,
            close_storage_on_close=close_storage,
            holder_id=holder_id,
        )

    @property
    def catalog(self) -> GraphCatalog:
        return self._catalog

    @property
    def storage(self) -> GraphStorage:
        return self._storage

    @property
    def holder_id(self) -> str:
        return self._holder_id

    def close(self) -> None:
        with self._tx_lock:
            if self._closed:
                return
            self._closed = True
            self._transactions.clear()
            self._open_handles.clear()
            if self._close_storage:
                try:
                    self._storage.close()
                except Exception:
                    pass
            if self._close_catalog:
                try:
                    self._catalog.close()
                except Exception:
                    pass

    def __enter__(self) -> "GraphService":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise CatalogError("STORAGE", "GraphService is closed")

    # ------------------------------------------------------------------
    # Public lifecycle methods (typed convenience wrappers)
    # ------------------------------------------------------------------

    def create(
        self,
        target: Union[GraphTarget, Mapping[str, Any], str],
        *,
        idempotency_key: Optional[str] = None,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
    ) -> LifecycleResult:
        return self.execute(
            self._make_request(
                "create",
                target,
                idempotency_key=idempotency_key,
                params=params,
                auth=auth,
                request_id=request_id,
                budgets=budgets,
            )
        )

    def list(
        self,
        target: Union[GraphTarget, Mapping[str, Any], str],
        *,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
    ) -> LifecycleResult:
        return self.execute(
            self._make_request(
                "list",
                target,
                params=params,
                auth=auth,
                request_id=request_id,
                budgets=budgets,
            )
        )

    def describe(
        self,
        target: Union[GraphTarget, Mapping[str, Any], str],
        *,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
    ) -> LifecycleResult:
        return self.execute(
            self._make_request(
                "describe",
                target,
                params=params,
                auth=auth,
                request_id=request_id,
                budgets=budgets,
            )
        )

    def open_graph(
        self,
        target: Union[GraphTarget, Mapping[str, Any], str],
        *,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
    ) -> LifecycleResult:
        """Resolve a target to an immutable revision snapshot handle.

        Named ``open_graph`` to avoid shadowing the :meth:`open` classmethod.
        The lifecycle operation name remains ``open``.
        """
        return self.execute(
            self._make_request(
                "open",
                target,
                params=params,
                auth=auth,
                request_id=request_id,
                budgets=budgets,
            )
        )

    def branch(
        self,
        target: Union[GraphTarget, Mapping[str, Any], str],
        *,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> LifecycleResult:
        return self.execute(
            self._make_request(
                "branch",
                target,
                params=params,
                auth=auth,
                request_id=request_id,
                budgets=budgets,
                idempotency_key=idempotency_key,
            )
        )

    def delete(
        self,
        target: Union[GraphTarget, Mapping[str, Any], str],
        *,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> LifecycleResult:
        return self.execute(
            self._make_request(
                "delete",
                target,
                params=params,
                auth=auth,
                request_id=request_id,
                budgets=budgets,
                idempotency_key=idempotency_key,
            )
        )

    def write(
        self,
        target: Union[GraphTarget, Mapping[str, Any], str],
        *,
        idempotency_key: str,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
    ) -> LifecycleResult:
        return self.execute(
            self._make_request(
                "write",
                target,
                idempotency_key=idempotency_key,
                params=params,
                auth=auth,
                request_id=request_id,
                budgets=budgets,
            )
        )

    def query(
        self,
        target: Union[GraphTarget, Mapping[str, Any], str],
        *,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
    ) -> LifecycleResult:
        return self.execute(
            self._make_request(
                "query",
                target,
                params=params,
                auth=auth,
                request_id=request_id,
                budgets=budgets,
            )
        )

    def begin_tx(
        self,
        target: Union[GraphTarget, Mapping[str, Any], str],
        *,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> LifecycleResult:
        return self.execute(
            self._make_request(
                "begin_tx",
                target,
                params=params,
                auth=auth,
                request_id=request_id,
                budgets=budgets,
                idempotency_key=idempotency_key,
            )
        )

    def commit_tx(
        self,
        target: Union[GraphTarget, Mapping[str, Any], str],
        *,
        idempotency_key: str,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
    ) -> LifecycleResult:
        return self.execute(
            self._make_request(
                "commit_tx",
                target,
                idempotency_key=idempotency_key,
                params=params,
                auth=auth,
                request_id=request_id,
                budgets=budgets,
            )
        )

    def rollback_tx(
        self,
        target: Union[GraphTarget, Mapping[str, Any], str],
        *,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
    ) -> LifecycleResult:
        return self.execute(
            self._make_request(
                "rollback_tx",
                target,
                params=params,
                auth=auth,
                request_id=request_id,
                budgets=budgets,
            )
        )

    # ------------------------------------------------------------------
    # Unified execute boundary
    # ------------------------------------------------------------------

    def execute(self, request: LifecycleRequest) -> LifecycleResult:
        """Run one lifecycle operation and return a JSON-safe result envelope."""
        self._ensure_open()
        request_id = request.request_id or f"req-{uuid.uuid4().hex}"
        op = request.operation
        started = time.perf_counter()
        auth_receipt: Optional[str] = None
        try:
            self._faults.maybe_raise(op, "before_auth")
            decision = self._authorizer.authorize(
                operation=op,
                target=request.target,
                auth=request.auth,
                request_id=request_id,
            )
            auth_receipt = decision.receipt_ref
            self._audit.emit(
                {
                    "event": "authorization",
                    "operation": op,
                    "target": request.target.to_json_dict(),
                    "request_id": request_id,
                    "decision": decision.to_json_dict(),
                    "at": self._clock.now_iso(),
                }
            )
            if not decision.allowed:
                code = decision.code or "FORBIDDEN"
                return self._error(
                    op,
                    request.target,
                    TypedError.of(
                        code,
                        decision.reason or "authorization denied",
                        details={"ability": decision.ability},
                    ),
                    request_id=request_id,
                    auth_receipt=auth_receipt,
                )

            self._faults.maybe_raise(op, "before_handler")
            handler = {
                "create": self._op_create,
                "list": self._op_list,
                "describe": self._op_describe,
                "open": self._op_open,
                "branch": self._op_branch,
                "delete": self._op_delete,
                "write": self._op_write,
                "query": self._op_query,
                "begin_tx": self._op_begin_tx,
                "commit_tx": self._op_commit_tx,
                "rollback_tx": self._op_rollback_tx,
            }[op]
            target, payload, warnings = handler(request)
            self._faults.maybe_raise(op, "after_handler")
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self._audit.emit(
                {
                    "event": "lifecycle_success",
                    "operation": op,
                    "target": target.to_json_dict() if target else None,
                    "request_id": request_id,
                    "elapsed_ms": elapsed_ms,
                    "at": self._clock.now_iso(),
                }
            )
            return LifecycleResult(
                status="success",
                operation=op,
                target=target,
                result=payload,
                warnings=tuple(warnings),
                request_id=request_id,
                authorization_receipt_ref=auth_receipt,
            )
        except GraphTargetError as exc:
            return self._error(
                op,
                getattr(request, "target", None),
                TypedError.of(
                    "INVALID_TARGET",
                    exc.message,
                    details={"target_code": exc.code, **exc.details},
                ),
                request_id=request_id,
                auth_receipt=auth_receipt,
            )
        except CatalogError as exc:
            return self._error(
                op,
                getattr(request, "target", None),
                TypedError.of(
                    exc.code if exc.code in TYPED_ERROR_CODES else "INTERNAL",
                    exc.message,
                    retryable=exc.retryable,
                    details=dict(exc.details),
                ),
                request_id=request_id,
                auth_receipt=auth_receipt,
            )
        except Exception as exc:  # noqa: BLE001 — map unexpected to INTERNAL
            self._audit.emit(
                {
                    "event": "lifecycle_error",
                    "operation": op,
                    "request_id": request_id,
                    "error_type": type(exc).__name__,
                    "at": self._clock.now_iso(),
                }
            )
            return self._error(
                op,
                getattr(request, "target", None),
                TypedError.of(
                    "INTERNAL",
                    "unexpected service failure",
                    details={"error_type": type(exc).__name__},
                ),
                request_id=request_id,
                auth_receipt=auth_receipt,
            )

    # ------------------------------------------------------------------
    # Operation implementations
    # ------------------------------------------------------------------

    def _op_create(
        self, request: LifecycleRequest
    ) -> Tuple[GraphTarget, JSONDict, List[str]]:
        target = request.target
        if target.revision is not None:
            raise GraphTargetError(
                "TARGET_BRANCH_AND_REVISION",
                "create must not pin a revision",
            )
        params = request.params or {}
        branch = target.branch or params.get("branch") or DEFAULT_BRANCH
        branch = _validate_slug(branch, field="branch", code_empty="TARGET_BAD_SLUG")
        profile = target.storage_profile or params.get("storage_profile")
        graph_kind = params.get("graph_kind")
        metadata = params.get("metadata") if isinstance(params.get("metadata"), Mapping) else None
        pin_root = params.get("pin_root")
        idem = request.idempotency_key or params.get("idempotency_key")

        record = self._catalog.create_graph(
            target.tenant,
            target.graph_id,
            branch=branch,
            storage_profile=profile,
            graph_kind=graph_kind,
            pin_root=pin_root,
            idempotency_key=idem,
            metadata=metadata,
        )
        boot = bootstrap_revision_id(record.tenant, record.graph_id)
        # Ensure bootstrap payload exists so open/query never invent ambient data.
        if self._storage.get_snapshot(record.tenant, record.graph_id, boot) is None:
            self._storage.put_snapshot(
                GraphSnapshot.empty(
                    record.tenant,
                    record.graph_id,
                    boot,
                    metadata={"bootstrap": True},
                )
            )
        resolved = GraphTarget(
            tenant=record.tenant,
            graph_id=record.graph_id,
            branch=branch,
            revision=None,
            storage_profile=record.storage_profile,
        )
        payload = {
            "graph_id": record.graph_id,
            "uri": record.uri,
            "branch": branch,
            "revision": boot,
            "storage_profile": record.storage_profile,
            "graph_kind": record.graph_kind,
            "created_at": record.created_at,
        }
        return resolved, payload, []

    def _op_list(
        self, request: LifecycleRequest
    ) -> Tuple[GraphTarget, JSONDict, List[str]]:
        target = request.target
        params = request.params or {}
        include_tombstoned = bool(params.get("include_tombstoned", False))
        graphs = self._catalog.list_graphs(
            target.tenant, include_tombstoned=include_tombstoned
        )
        # Optional graph_id filter when target carries one (list may use tenant-only
        # partial targets via a synthetic graph_id of "" is not allowed; filter
        # via params instead, or use the target graph_id when not a list wildcard).
        filter_id = params.get("graph_id") or (
            target.graph_id if params.get("filter_by_target_graph") else None
        )
        summaries: List[JSONDict] = []
        for g in graphs:
            if filter_id and g.graph_id != filter_id:
                continue
            try:
                desc = self._catalog.describe_graph(g.tenant, g.graph_id)
                summaries.append(
                    {
                        "tenant": desc.tenant,
                        "graph_id": desc.graph_id,
                        "uri": desc.uri,
                        "storage_profile": desc.storage_profile,
                        "graph_kind": desc.graph_kind,
                        "status": desc.status,
                        "head_revision": desc.head_revision,
                        "default_branch": desc.default_branch,
                        "created_at": desc.created_at,
                        "updated_at": desc.updated_at,
                    }
                )
            except CatalogError:
                summaries.append(
                    {
                        "tenant": g.tenant,
                        "graph_id": g.graph_id,
                        "uri": g.uri,
                        "storage_profile": g.storage_profile,
                        "graph_kind": g.graph_kind,
                        "status": g.status,
                        "head_revision": None,
                        "default_branch": g.default_branch,
                        "created_at": g.created_at,
                        "updated_at": g.updated_at,
                    }
                )
        list_target = GraphTarget(
            tenant=target.tenant,
            graph_id=target.graph_id,
            branch=None,
            revision=None,
            storage_profile=target.storage_profile,
        )
        return list_target, {"graphs": summaries}, []

    def _op_describe(
        self, request: LifecycleRequest
    ) -> Tuple[GraphTarget, JSONDict, List[str]]:
        target = request.target
        params = request.params or {}
        branch = target.branch or params.get("branch")
        desc = self._catalog.describe_graph(
            target.tenant,
            target.graph_id,
            branch=branch,
            include_tombstoned_branches=bool(
                params.get("include_tombstoned_branches", False)
            ),
        )
        resolved = GraphTarget(
            tenant=desc.tenant,
            graph_id=desc.graph_id,
            branch=branch,
            revision=None,
            storage_profile=desc.storage_profile,
        )
        payload = {
            "uri": desc.uri,
            "branches": list(desc.branches),
            "head_revision": desc.head_revision,
            "storage_profile": desc.storage_profile,
            "graph_kind": desc.graph_kind,
            "status": desc.status,
            "default_branch": desc.default_branch,
            "created_at": desc.created_at,
            "updated_at": desc.updated_at,
            "tombstoned_at": desc.tombstoned_at,
            "metadata": dict(desc.metadata),
        }
        return resolved, payload, []

    def _op_open(
        self, request: LifecycleRequest
    ) -> Tuple[GraphTarget, JSONDict, List[str]]:
        require_open_selector(request.target)
        resolved_revision, resolved_branch, profile = self._resolve_snapshot(
            request.target
        )
        target = request.target
        # Ensure payload exists (bootstrap may predate storage adapter bind).
        snap = self._storage.get_snapshot(
            target.tenant, target.graph_id, resolved_revision
        )
        if snap is None:
            # Catalog has the revision; synthesize empty durable snapshot.
            snap = GraphSnapshot.empty(
                target.tenant,
                target.graph_id,
                resolved_revision,
            )
            self._storage.put_snapshot(snap)

        snapshot_id = self._snapshot_id(
            target.tenant, target.graph_id, resolved_revision
        )
        handle = {
            "snapshot_id": snapshot_id,
            "revision": resolved_revision,
            "branch": resolved_branch,
            "tenant": target.tenant,
            "graph_id": target.graph_id,
            "opened_at": self._clock.now_iso(),
        }
        with self._tx_lock:
            self._open_handles[snapshot_id] = handle
        payload = {
            "uri": (
                f"kg://{target.tenant}/{target.graph_id}/revisions/{resolved_revision}"
            ),
            "revision": resolved_revision,
            "branch": resolved_branch,
            "snapshot_id": snapshot_id,
            "storage_profile": profile,
            "entity_count": len(snap.entities),
            "relationship_count": len(snap.relationships),
        }
        # Return a target that includes the resolved revision for durability proofs.
        out_target = GraphTarget(
            tenant=target.tenant,
            graph_id=target.graph_id,
            branch=None,
            revision=resolved_revision,
            storage_profile=profile or target.storage_profile,
        )
        return out_target, payload, []
    def _op_branch(
        self, request: LifecycleRequest
    ) -> Tuple[GraphTarget, JSONDict, List[str]]:
        target = request.target
        params = request.params or {}
        branch_name = target.branch or params.get("branch")
        if not branch_name:
            raise GraphTargetError(
                "TARGET_AMBIGUOUS",
                "branch operation requires a branch name",
            )
        branch_name = _validate_slug(
            branch_name, field="branch", code_empty="TARGET_BAD_SLUG"
        )
        from_revision = params.get("from_revision") or params.get("revision")
        from_branch = params.get("from_branch")
        if target.revision and from_revision is None:
            from_revision = target.revision
        rec = self._catalog.create_branch(
            target.tenant,
            target.graph_id,
            branch_name,
            from_revision=from_revision,
            from_branch=from_branch,
        )
        resolved = GraphTarget(
            tenant=rec.tenant,
            graph_id=rec.graph_id,
            branch=rec.branch,
            revision=None,
            storage_profile=target.storage_profile,
        )
        return (
            resolved,
            {"branch": rec.branch, "revision": rec.head_revision, "uri": rec.uri},
            [],
        )

    def _op_delete(
        self, request: LifecycleRequest
    ) -> Tuple[GraphTarget, JSONDict, List[str]]:
        target = request.target
        params = request.params or {}
        reason = params.get("reason")
        if target.branch is not None:
            tomb = self._catalog.delete_branch(
                target.tenant,
                target.graph_id,
                target.branch,
                reason=reason,
            )
            resolved = target.with_branch(target.branch)
            return (
                resolved,
                {
                    "tombstone": True,
                    "uri": resolved.uri,
                    "entity_type": tomb.entity_type,
                    "tombstoned_at": tomb.tombstoned_at,
                },
                [],
            )
        tomb = self._catalog.delete_graph(
            target.tenant,
            target.graph_id,
            reason=reason,
            idempotency_key=request.idempotency_key,
        )
        resolved = GraphTarget(
            tenant=target.tenant,
            graph_id=target.graph_id,
            branch=None,
            revision=None,
            storage_profile=target.storage_profile,
        )
        return (
            resolved,
            {
                "tombstone": True,
                "uri": resolved.uri,
                "entity_type": tomb.entity_type,
                "tombstoned_at": tomb.tombstoned_at,
            },
            [],
        )

    def _op_write(
        self, request: LifecycleRequest
    ) -> Tuple[GraphTarget, JSONDict, List[str]]:
        target = request.target
        branch = require_write_branch(target)
        params = dict(request.params or {})
        idem = request.idempotency_key
        if not idem:
            raise CatalogError(
                "INVALID_REQUEST",
                "idempotency_key is required for write",
            )
        if not _KEY_RE.fullmatch(idem) or not (1 <= len(idem) <= 128):
            raise CatalogError(
                "INVALID_REQUEST",
                "idempotency_key failed validation",
                details={"idempotency_key": idem},
            )

        tx_id = params.get("transaction_id")
        if tx_id:
            return self._write_into_transaction(request, str(tx_id), branch)

        # Auto-commit write: stage mutations, put revision, CAS head.
        parent_revision, _, profile = self._resolve_snapshot(
            target.with_branch(branch)
        )
        parent_snap = self._load_or_empty(
            target.tenant, target.graph_id, parent_revision
        )
        new_revision = self._new_revision_id(
            target.tenant, target.graph_id, parent_revision, params
        )
        child = parent_snap.clone_for_revision(
            new_revision, parent_revision=parent_revision
        )
        mutation_count = self._apply_mutations(child, params)
        if mutation_count == 0 and not params.get("allow_empty", False):
            # Still allow empty commit when explicitly requested; otherwise reject.
            if not params.get("force_empty"):
                raise CatalogError(
                    "INVALID_REQUEST",
                    "write requires at least one mutation "
                    "(entities/relationships) or force_empty=true",
                )

        self._storage.put_snapshot(child)
        checksum = self._snapshot_checksum(child)
        self._catalog.put_revision(
            target.tenant,
            target.graph_id,
            new_revision,
            parent_revision=parent_revision,
            storage_profile=profile,
            pin_root=params.get("pin_root"),
            checksum=checksum,
            metadata={"mutation_count": mutation_count, "via": "write"},
        )
        self._catalog.cas_set_head(
            target.tenant,
            target.graph_id,
            branch,
            expected_revision=parent_revision,
            new_revision=new_revision,
            pin_root=params.get("pin_root"),
            idempotency_key=idem,
            lease_id=params.get("lease_id"),
            lease_epoch=params.get("lease_epoch"),
        )
        out = GraphTarget(
            tenant=target.tenant,
            graph_id=target.graph_id,
            branch=branch,
            revision=None,
            storage_profile=profile or target.storage_profile,
        )
        payload = {
            "revision": new_revision,
            "parent_revision": parent_revision,
            "mutation_count": mutation_count,
            "branch": branch,
            "uri": f"kg://{target.tenant}/{target.graph_id}/revisions/{new_revision}",
        }
        return out, payload, []

    def _write_into_transaction(
        self,
        request: LifecycleRequest,
        tx_id: str,
        branch: str,
    ) -> Tuple[GraphTarget, JSONDict, List[str]]:
        params = dict(request.params or {})
        with self._tx_lock:
            tx = self._transactions.get(tx_id)
            if tx is None:
                raise CatalogError(
                    "NOT_FOUND",
                    "transaction not found",
                    details={"transaction_id": tx_id},
                )
            if tx.state != "open":
                raise CatalogError(
                    "INVALID_REQUEST",
                    f"transaction is not open (state={tx.state})",
                    details={"transaction_id": tx_id, "state": tx.state},
                )
            if (
                tx.tenant != request.target.tenant
                or tx.graph_id != request.target.graph_id
                or tx.branch != branch
            ):
                raise CatalogError(
                    "INVALID_REQUEST",
                    "transaction target mismatch",
                    details={"transaction_id": tx_id},
                )
            entities = params.get("entities") or []
            relationships = params.get("relationships") or []
            if not isinstance(entities, list) or not isinstance(relationships, list):
                raise CatalogError(
                    "INVALID_REQUEST",
                    "entities and relationships must be lists",
                )
            for e in entities:
                if not isinstance(e, Mapping):
                    raise CatalogError("INVALID_REQUEST", "entity must be a mapping")
                tx.staged_entities.append(dict(e))
            for r in relationships:
                if not isinstance(r, Mapping):
                    raise CatalogError(
                        "INVALID_REQUEST", "relationship must be a mapping"
                    )
                tx.staged_relationships.append(dict(r))
            added = len(entities) + len(relationships)
            # delete_entity_ids also count
            dels = params.get("delete_entity_ids") or []
            if isinstance(dels, list):
                for eid in dels:
                    tx.staged_entities.append({"_op": "delete", "id": eid})
                    added += 1
            tx.mutation_count += added
            mutation_count = tx.mutation_count
            state = tx.state
        out = request.target.with_branch(branch)
        return (
            out,
            {
                "transaction_id": tx_id,
                "state": state,
                "mutation_count": mutation_count,
                "staged": True,
            },
            [],
        )

    def _op_query(
        self, request: LifecycleRequest
    ) -> Tuple[GraphTarget, JSONDict, List[str]]:
        require_open_selector(request.target)
        params = dict(request.params or {})
        revision, branch, profile = self._resolve_snapshot(request.target)
        snap = self._load_or_empty(
            request.target.tenant, request.target.graph_id, revision
        )
        language = str(params.get("language") or params.get("query_language") or "scan")
        text = params.get("text") or params.get("query") or ""
        qparams = params.get("params") if isinstance(params.get("params"), Mapping) else {}
        budgets = request.budgets or {}
        max_rows = int(budgets.get("max_rows") or params.get("max_rows") or 1000)
        if max_rows < 0:
            raise CatalogError("INVALID_REQUEST", "max_rows must be non-negative")

        started = time.perf_counter()
        columns, rows, schema, truncated, warnings = self._run_query(
            snap,
            language=language,
            text=str(text),
            qparams=dict(qparams or {}),
            max_rows=max_rows,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        resolved_target = GraphTarget(
            tenant=request.target.tenant,
            graph_id=request.target.graph_id,
            branch=None,
            revision=revision,
            storage_profile=profile or request.target.storage_profile,
        )
        envelope = QueryResultEnvelope(
            schema=schema,
            target=resolved_target,
            revision=revision,
            columns=columns,
            rows=rows,
            statistics={
                "elapsed_ms": round(elapsed_ms, 3),
                "nodes_visited": len(snap.entities),
                "edges_visited": len(snap.relationships),
            },
            query={
                "language": language,
                "text": str(text),
                "params": dict(qparams or {}),
            },
            warnings=warnings,
            truncated=truncated,
            authorization_receipt_ref=None,
        )
        # Contract: query envelope may be the entire result.
        return resolved_target, envelope.to_json_dict(), warnings

    def _op_begin_tx(
        self, request: LifecycleRequest
    ) -> Tuple[GraphTarget, JSONDict, List[str]]:
        target = request.target
        branch = require_write_branch(target)
        params = dict(request.params or {})
        parent_revision, _, profile = self._resolve_snapshot(target.with_branch(branch))
        ttl = float(params.get("lease_ttl_seconds") or 300.0)
        acquire_lease = bool(params.get("acquire_lease", True))
        lease_id = None
        lease_epoch = None
        if acquire_lease:
            lease = self._catalog.acquire_lease(
                target.tenant,
                target.graph_id,
                branch,
                holder=self._holder_id,
                ttl_seconds=ttl,
            )
            lease_id = lease.lease_id
            lease_epoch = lease.epoch
        tx_id = str(params.get("transaction_id") or f"tx-{uuid.uuid4().hex}")
        with self._tx_lock:
            if tx_id in self._transactions:
                raise CatalogError(
                    "ALREADY_EXISTS",
                    "transaction_id already in use",
                    details={"transaction_id": tx_id},
                )
            self._transactions[tx_id] = _OpenTransaction(
                transaction_id=tx_id,
                tenant=target.tenant,
                graph_id=target.graph_id,
                branch=branch,
                base_revision=parent_revision,
                state="open",
                created_at=self._clock.now_iso(),
                lease_id=lease_id,
                lease_epoch=lease_epoch,
                idempotency_key=request.idempotency_key,
            )
        out = target.with_branch(branch)
        return (
            out,
            {
                "transaction_id": tx_id,
                "state": "open",
                "base_revision": parent_revision,
                "branch": branch,
                "lease_id": lease_id,
                "lease_epoch": lease_epoch,
            },
            [],
        )

    def _op_commit_tx(
        self, request: LifecycleRequest
    ) -> Tuple[GraphTarget, JSONDict, List[str]]:
        target = request.target
        params = dict(request.params or {})
        tx_id = params.get("transaction_id")
        if not tx_id:
            raise CatalogError(
                "INVALID_REQUEST",
                "commit_tx requires params.transaction_id",
            )
        idem = request.idempotency_key
        if not idem:
            raise CatalogError(
                "INVALID_REQUEST",
                "idempotency_key is required for commit_tx",
            )
        with self._tx_lock:
            tx = self._transactions.get(str(tx_id))
            if tx is None:
                raise CatalogError(
                    "NOT_FOUND",
                    "transaction not found",
                    details={"transaction_id": tx_id},
                )
            if tx.state != "open":
                if tx.state == "committed":
                    # Idempotent re-commit is not stored; require open.
                    raise CatalogError(
                        "INVALID_REQUEST",
                        "transaction already committed",
                        details={"transaction_id": tx_id},
                    )
                raise CatalogError(
                    "INVALID_REQUEST",
                    f"transaction is not open (state={tx.state})",
                    details={"transaction_id": tx_id, "state": tx.state},
                )
            tx.state = "prepared"
            staged_entities = list(tx.staged_entities)
            staged_relationships = list(tx.staged_relationships)
            base_revision = tx.base_revision
            branch = tx.branch
            lease_id = tx.lease_id
            lease_epoch = tx.lease_epoch
            mutation_count = tx.mutation_count
            tenant = tx.tenant
            graph_id = tx.graph_id

        # Verify head has not moved under us before publishing.
        current = self._catalog.get_branch(tenant, graph_id, branch)
        if current.head_revision != base_revision:
            with self._tx_lock:
                if str(tx_id) in self._transactions:
                    self._transactions[str(tx_id)].state = "open"
            raise CatalogError(
                "CONFLICT",
                "branch head moved since begin_tx",
                details={
                    "expected_revision": base_revision,
                    "current_revision": current.head_revision,
                    "transaction_id": tx_id,
                },
            )

        parent_snap = self._load_or_empty(tenant, graph_id, base_revision)
        new_revision = self._new_revision_id(
            tenant,
            graph_id,
            base_revision,
            {
                "entities": staged_entities,
                "relationships": staged_relationships,
                "transaction_id": tx_id,
            },
        )
        child = parent_snap.clone_for_revision(
            new_revision, parent_revision=base_revision
        )
        applied = self._apply_mutations(
            child,
            {
                "entities": [e for e in staged_entities if e.get("_op") != "delete"],
                "relationships": staged_relationships,
                "delete_entity_ids": [
                    e.get("id") for e in staged_entities if e.get("_op") == "delete"
                ],
            },
        )
        graph = self._catalog.get_graph(tenant, graph_id)
        self._storage.put_snapshot(child)
        checksum = self._snapshot_checksum(child)
        self._catalog.put_revision(
            tenant,
            graph_id,
            new_revision,
            parent_revision=base_revision,
            storage_profile=graph.storage_profile,
            checksum=checksum,
            metadata={
                "mutation_count": applied,
                "via": "commit_tx",
                "transaction_id": tx_id,
            },
        )
        self._catalog.cas_set_head(
            tenant,
            graph_id,
            branch,
            expected_revision=base_revision,
            new_revision=new_revision,
            lease_id=lease_id,
            lease_epoch=lease_epoch,
            idempotency_key=idem,
        )
        with self._tx_lock:
            if str(tx_id) in self._transactions:
                self._transactions[str(tx_id)].state = "committed"
        out = GraphTarget(
            tenant=tenant,
            graph_id=graph_id,
            branch=branch,
            revision=None,
            storage_profile=graph.storage_profile,
        )
        return (
            out,
            {
                "transaction_id": tx_id,
                "state": "committed",
                "revision": new_revision,
                "parent_revision": base_revision,
                "mutation_count": applied if applied else mutation_count,
                "branch": branch,
            },
            [],
        )

    def _op_rollback_tx(
        self, request: LifecycleRequest
    ) -> Tuple[GraphTarget, JSONDict, List[str]]:
        params = dict(request.params or {})
        tx_id = params.get("transaction_id")
        if not tx_id:
            raise CatalogError(
                "INVALID_REQUEST",
                "rollback_tx requires params.transaction_id",
            )
        with self._tx_lock:
            tx = self._transactions.get(str(tx_id))
            if tx is None:
                raise CatalogError(
                    "NOT_FOUND",
                    "transaction not found",
                    details={"transaction_id": tx_id},
                )
            if tx.state in {"committed", "rolled_back"}:
                raise CatalogError(
                    "INVALID_REQUEST",
                    f"transaction already {tx.state}",
                    details={"transaction_id": tx_id, "state": tx.state},
                )
            tx.state = "rolled_back"
            tx.staged_entities.clear()
            tx.staged_relationships.clear()
            branch = tx.branch
            tenant = tx.tenant
            graph_id = tx.graph_id
        out = GraphTarget(
            tenant=tenant,
            graph_id=graph_id,
            branch=branch,
            revision=None,
            storage_profile=request.target.storage_profile,
        )
        return (
            out,
            {"transaction_id": tx_id, "state": "rolled_back"},
            [],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_request(
        self,
        operation: str,
        target: Union[GraphTarget, Mapping[str, Any], str],
        *,
        idempotency_key: Optional[str] = None,
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        budgets: Optional[Mapping[str, Any]] = None,
    ) -> LifecycleRequest:
        return LifecycleRequest(
            operation=operation,
            target=self._coerce_target(target, operation=operation),
            idempotency_key=idempotency_key,
            params=dict(params or {}),
            auth=dict(auth) if auth is not None else None,
            request_id=request_id,
            budgets=dict(budgets) if budgets is not None else None,
        )

    def _coerce_target(
        self,
        target: Union[GraphTarget, Mapping[str, Any], str],
        *,
        operation: str,
    ) -> GraphTarget:
        if isinstance(target, GraphTarget):
            return target
        if isinstance(target, str):
            return GraphTarget.from_uri(target)
        if isinstance(target, Mapping):
            # list may be tenant-scoped; allow placeholder graph_id via params
            data = dict(target)
            if operation == "list" and not data.get("graph_id"):
                # Use a deterministic placeholder that passes slug validation for
                # the request envelope; list ignores graph_id unless filtered.
                data = {**data, "graph_id": data.get("graph_id") or "list"}
            return GraphTarget.from_mapping(data)
        raise GraphTargetError(
            "TARGET_BAD_URI",
            "target must be GraphTarget, mapping, or kg:// URI",
        )

    def _resolve_snapshot(
        self, target: GraphTarget
    ) -> Tuple[str, Optional[str], Optional[str]]:
        """Return (revision_id, branch_or_none, storage_profile)."""
        graph = self._catalog.get_graph(target.tenant, target.graph_id)
        profile = target.storage_profile or graph.storage_profile
        if target.revision is not None:
            rev = self._catalog.get_revision(
                target.tenant, target.graph_id, target.revision
            )
            return rev.revision_id, None, profile
        branch = target.branch or graph.default_branch
        brow = self._catalog.get_branch(target.tenant, target.graph_id, branch)
        return brow.head_revision, branch, profile

    def _load_or_empty(
        self, tenant: str, graph_id: str, revision: str
    ) -> GraphSnapshot:
        snap = self._storage.get_snapshot(tenant, graph_id, revision)
        if snap is not None:
            return snap
        empty = GraphSnapshot.empty(tenant, graph_id, revision)
        # Persist so subsequent reopens of the same service see consistency.
        self._storage.put_snapshot(empty)
        return empty

    def _apply_mutations(self, snap: GraphSnapshot, params: Mapping[str, Any]) -> int:
        count = 0
        entities = params.get("entities") or []
        relationships = params.get("relationships") or []
        delete_ids = params.get("delete_entity_ids") or []
        if not isinstance(entities, list):
            raise CatalogError("INVALID_REQUEST", "entities must be a list")
        if not isinstance(relationships, list):
            raise CatalogError("INVALID_REQUEST", "relationships must be a list")
        if not isinstance(delete_ids, list):
            raise CatalogError("INVALID_REQUEST", "delete_entity_ids must be a list")

        by_id: Dict[str, JSONDict] = {}
        for e in snap.entities:
            eid = str(e.get("id") or e.get("entity_id") or "")
            if eid:
                by_id[eid] = dict(e)

        for eid in delete_ids:
            key = str(eid)
            if key in by_id:
                del by_id[key]
                count += 1

        for e in entities:
            if not isinstance(e, Mapping):
                raise CatalogError("INVALID_REQUEST", "entity must be a mapping")
            ent = dict(e)
            if ent.get("_op") == "delete":
                key = str(ent.get("id") or "")
                if key and key in by_id:
                    del by_id[key]
                    count += 1
                continue
            eid = str(ent.get("id") or ent.get("entity_id") or uuid.uuid4().hex)
            ent["id"] = eid
            by_id[eid] = ent
            count += 1

        snap.entities = list(by_id.values())

        rel_by_id: Dict[str, JSONDict] = {}
        for r in snap.relationships:
            rid = str(r.get("id") or r.get("relationship_id") or "")
            if rid:
                rel_by_id[rid] = dict(r)
            else:
                # Keep anonymous edges with synthetic ids.
                rid = uuid.uuid4().hex
                rr = dict(r)
                rr["id"] = rid
                rel_by_id[rid] = rr

        for r in relationships:
            if not isinstance(r, Mapping):
                raise CatalogError("INVALID_REQUEST", "relationship must be a mapping")
            rel = dict(r)
            rid = str(rel.get("id") or rel.get("relationship_id") or uuid.uuid4().hex)
            rel["id"] = rid
            rel_by_id[rid] = rel
            count += 1

        # Drop relationships whose endpoints were deleted.
        live = set(by_id.keys())
        cleaned: List[JSONDict] = []
        for rel in rel_by_id.values():
            src = rel.get("source_id") or rel.get("start_id") or rel.get("from")
            dst = rel.get("target_id") or rel.get("end_id") or rel.get("to")
            if src is not None and str(src) not in live:
                continue
            if dst is not None and str(dst) not in live:
                continue
            cleaned.append(rel)
        snap.relationships = cleaned
        return count

    def _run_query(
        self,
        snap: GraphSnapshot,
        *,
        language: str,
        text: str,
        qparams: Mapping[str, Any],
        max_rows: int,
    ) -> Tuple[List[str], List[Any], str, bool, List[str]]:
        lang = language.lower().strip()
        warnings: List[str] = []
        if lang in {"scan", "node-scan", "nodes"}:
            columns = ["id", "type", "name", "properties"]
            rows: List[Any] = []
            for e in snap.entities:
                rows.append(
                    [
                        e.get("id"),
                        e.get("type") or e.get("entity_type"),
                        e.get("name"),
                        e.get("properties") or {},
                    ]
                )
            truncated = False
            if max_rows and len(rows) > max_rows:
                rows = rows[:max_rows]
                truncated = True
            return columns, rows, "node-scan/v1", truncated, warnings

        if lang in {"count", "stats"}:
            columns = ["entities", "relationships"]
            rows = [[len(snap.entities), len(snap.relationships)]]
            return columns, rows, "stats/v1", False, warnings

        if lang in {"cypher", "cypher-lite"}:
            return self._run_cypher_lite(snap, text, qparams, max_rows, warnings)

        raise CatalogError(
            "QUERY_PARSE",
            f"unsupported query language: {language!r}",
            details={"language": language},
        )

    def _run_cypher_lite(
        self,
        snap: GraphSnapshot,
        text: str,
        qparams: Mapping[str, Any],
        max_rows: int,
        warnings: List[str],
    ) -> Tuple[List[str], List[Any], str, bool, List[str]]:
        """Minimal Cypher subset for smoke tests: MATCH (n) RETURN n / counts."""
        cleaned = " ".join(text.split())
        upper = cleaned.upper()
        if not cleaned:
            raise CatalogError("QUERY_PARSE", "empty cypher query")

        if "RETURN" not in upper:
            raise CatalogError(
                "QUERY_PARSE",
                "cypher-lite requires a RETURN clause",
            )

        # count(n) style
        if re.search(r"RETURN\s+count\s*\(", cleaned, re.IGNORECASE):
            columns = ["count"]
            rows: List[Any] = [[len(snap.entities)]]
            return columns, rows, "cypher-table/v1", False, warnings

        # MATCH (n:Label) filter
        label_match = re.search(
            r"MATCH\s*\(\s*\w+\s*(?::\s*(\w+))?\s*\)", cleaned, re.IGNORECASE
        )
        label = label_match.group(1) if label_match else None
        entities = snap.entities
        if label:
            entities = [
                e
                for e in entities
                if (e.get("type") or e.get("entity_type") or "") == label
            ]

        # RETURN n.name AS name patterns — emit full node objects as JSON maps.
        columns = ["n"]
        rows = []
        for e in entities:
            rows.append([dict(e)])
        truncated = False
        if max_rows and len(rows) > max_rows:
            rows = rows[:max_rows]
            truncated = True
        if "WHERE" in upper:
            warnings.append("cypher-lite ignores WHERE predicates")
        return columns, rows, "cypher-table/v1", truncated, warnings

    @staticmethod
    def _new_revision_id(
        tenant: str,
        graph_id: str,
        parent_revision: str,
        params: Mapping[str, Any],
    ) -> str:
        body = {
            "tenant": tenant,
            "graph_id": graph_id,
            "parent": parent_revision,
            "params": params,
            "nonce": uuid.uuid4().hex,
        }
        digest = request_hash(body)[:32]
        return f"kg-rev-{digest}"

    @staticmethod
    def _snapshot_id(tenant: str, graph_id: str, revision: str) -> str:
        digest = hashlib.sha256(
            f"{tenant}|{graph_id}|{revision}".encode("utf-8")
        ).hexdigest()[:24]
        return f"snap-{digest}"

    @staticmethod
    def _snapshot_checksum(snap: GraphSnapshot) -> str:
        payload = json.dumps(
            snap.to_json_dict(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _error(
        self,
        operation: str,
        target: Optional[GraphTarget],
        error: TypedError,
        *,
        request_id: str,
        auth_receipt: Optional[str],
    ) -> LifecycleResult:
        self._audit.emit(
            {
                "event": "lifecycle_error",
                "operation": operation,
                "target": target.to_json_dict() if target else None,
                "request_id": request_id,
                "error": error.to_json_dict(),
                "at": self._clock.now_iso(),
            }
        )
        return LifecycleResult(
            status="error",
            operation=operation,
            target=target,
            result=None,
            error=error,
            request_id=request_id,
            authorization_receipt_ref=auth_receipt,
        )


__all__ = [
    "CONTRACT_VERSION",
    "QUERY_ENVELOPE_VERSION",
    "LIFECYCLE_OPERATIONS",
    "TYPED_ERROR_CODES",
    "STORAGE_PROFILES",
    "GraphTargetError",
    "GraphTarget",
    "parse_graph_target_uri",
    "require_open_selector",
    "require_write_branch",
    "TypedError",
    "LifecycleRequest",
    "LifecycleResult",
    "QueryResultEnvelope",
    "Clock",
    "SystemClock",
    "AuthorizationDecision",
    "Authorizer",
    "AllowAllAuthorizer",
    "PrincipalAuthorizer",
    "AuditSink",
    "NullAuditSink",
    "InMemoryAuditSink",
    "FaultInjector",
    "NoFaults",
    "ScriptedFaultInjector",
    "GraphSnapshot",
    "GraphStorage",
    "InMemoryGraphStorage",
    "FileGraphStorage",
    "GraphService",
]
