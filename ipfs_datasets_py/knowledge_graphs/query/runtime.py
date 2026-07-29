"""Query execution runtime: budgets, cursors, cancellation, and streaming (KGP-016).

Budget enforcement lives **below every transport**. Surfaces (Python client,
CLI, MCP, MCP++) may only **narrow** limits; they never widen them after a
session has started.

Contract alignment (``kg-service-contract/v1`` §7):

* ``time_ms`` — hard timeout → ``BUDGET_EXCEEDED`` (or truncated page when
  ``truncate_on_budget`` is enabled for soft limits)
* ``max_rows`` — caps rows per response page
* ``max_bytes`` — caps serialized payload size per page
* ``max_depth`` — caps path / traversal depth
* ``max_fanout`` — caps adjacency expansion per hop
* ``max_memory_bytes`` — service-side working-set guard
* ``max_shard_fetches`` — caps remote/local shard materializations

Cursors are opaque strings bound to
``(tenant, graph_id, revision, query_digest, authorization_digest)``.
Replaying a cursor against another graph or revision returns
``INVALID_REQUEST``.

This module is intentionally independent of optional storage backends so
contract tests and every surface can share one enforcement path.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from dataclasses import dataclass, field, replace
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    Iterable,
    Iterator,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RUNTIME_API_VERSION: str = "kg-query-runtime/v1"
CURSOR_VERSION: int = 1
CURSOR_PREFIX: str = "kgc1."

# Shared typed-error vocabulary (kg-service-contract/v1).
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
        "CANCELLED",
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
    "CANCELLED": False,
}

# Soft limits that may produce a truncated page instead of a hard error when
# ``truncate_on_budget`` is True on the session.
_SOFT_BUDGET_NAMES = frozenset({"max_rows", "max_bytes"})

JSONDict = Dict[str, Any]
ClockFn = Callable[[], float]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class QueryRuntimeError(Exception):
    """Typed query-runtime error with service-contract ``code``."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: Optional[bool] = None,
        details: Optional[Mapping[str, Any]] = None,
        cause_code: Optional[str] = None,
    ) -> None:
        if code not in TYPED_ERROR_CODES:
            raise ValueError(f"unknown typed error code: {code!r}")
        self.code = code
        self.message = message
        self.retryable = (
            bool(_DEFAULT_RETRYABLE.get(code, False))
            if retryable is None
            else bool(retryable)
        )
        self.details = dict(details or {})
        self.cause_code = cause_code
        super().__init__(f"[{code}] {message}")

    def to_typed_dict(self) -> JSONDict:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": dict(self.details),
            "cause_code": self.cause_code,
        }

    def to_json_dict(self) -> JSONDict:
        """Alias used by surfaces that expect TypedError-shaped payloads."""
        return self.to_typed_dict()


class BudgetExceededError(QueryRuntimeError):
    """Raised when a hard budget is exceeded."""

    def __init__(
        self,
        budget: str,
        *,
        actual: Union[int, float],
        limit: Union[int, float],
        unit: Optional[str] = None,
        detail: Optional[str] = None,
        message: Optional[str] = None,
    ) -> None:
        suffix = unit or ""
        msg = message or f"{budget} exceeded ({actual}{suffix} > {limit}{suffix})"
        details: JSONDict = {
            "budget": budget,
            "actual": actual,
            "limit": limit,
        }
        if unit is not None:
            details["unit"] = unit
        if detail is not None:
            details["detail"] = detail
        super().__init__("BUDGET_EXCEEDED", msg, details=details)
        self.budget = budget
        self.actual = actual
        self.limit = limit
        self.unit = unit

    @classmethod
    def exceeded(
        cls,
        budget: str,
        *,
        actual: Union[int, float],
        limit: Union[int, float],
        unit: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> "BudgetExceededError":
        return cls(
            budget,
            actual=actual,
            limit=limit,
            unit=unit,
            detail=detail,
        )


class CancellationError(QueryRuntimeError):
    """Raised when cooperative cancellation is observed."""

    def __init__(
        self,
        message: str = "query cancelled",
        *,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__("CANCELLED", message, details=dict(details or {}))


class InvalidCursorError(QueryRuntimeError):
    """Raised for malformed, forged, or mis-bound cursors."""

    def __init__(
        self,
        message: str,
        *,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__("INVALID_REQUEST", message, details=dict(details or {}))


# ---------------------------------------------------------------------------
# Budgets and usage
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QueryBudgets:
    """Hard limits for a single query session / page stream.

    Zero means *unlimited* for optional caps (``max_bytes``, ``max_memory_bytes``,
    ``max_shard_fetches``). ``time_ms``, ``max_rows``, ``max_depth``, and
    ``max_fanout`` always have positive defaults.
    """

    time_ms: int = 10_000
    max_rows: int = 1_000
    max_bytes: int = 0  # 0 = unlimited
    max_depth: int = 8
    max_fanout: int = 10_000
    max_memory_bytes: int = 0  # 0 = unlimited
    max_shard_fetches: int = 0  # 0 = unlimited
    page_size: int = 100  # streaming page bound (narrowed by max_rows)

    def __post_init__(self) -> None:
        for name in (
            "time_ms",
            "max_rows",
            "max_bytes",
            "max_depth",
            "max_fanout",
            "max_memory_bytes",
            "max_shard_fetches",
            "page_size",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise QueryRuntimeError(
                    "INVALID_REQUEST",
                    f"budget {name} must be an int",
                    details={"field": name, "value": value},
                )
            if value < 0:
                raise QueryRuntimeError(
                    "INVALID_REQUEST",
                    f"budget {name} must be non-negative",
                    details={"field": name, "value": value},
                )
        if self.time_ms == 0:
            raise QueryRuntimeError(
                "INVALID_REQUEST",
                "time_ms must be positive (0 is not unlimited)",
                details={"field": "time_ms"},
            )
        if self.max_rows == 0:
            raise QueryRuntimeError(
                "INVALID_REQUEST",
                "max_rows must be positive",
                details={"field": "max_rows"},
            )
        if self.page_size == 0:
            raise QueryRuntimeError(
                "INVALID_REQUEST",
                "page_size must be positive",
                details={"field": "page_size"},
            )

    def effective_page_size(self) -> int:
        """Rows per stream page, never exceeding ``max_rows``."""
        return min(self.page_size, self.max_rows)

    def narrow(self, other: Optional[Mapping[str, Any] | "QueryBudgets"] = None) -> "QueryBudgets":
        """Return budgets that are component-wise at most as large as ``self``.

        Wrappers may only **narrow** limits. Unknown keys are ignored; values
        larger than the current limit are clamped to the current limit.
        """
        if other is None:
            return self
        if isinstance(other, QueryBudgets):
            mapping: Mapping[str, Any] = {
                "time_ms": other.time_ms,
                "max_rows": other.max_rows,
                "max_bytes": other.max_bytes,
                "max_depth": other.max_depth,
                "max_fanout": other.max_fanout,
                "max_memory_bytes": other.max_memory_bytes,
                "max_shard_fetches": other.max_shard_fetches,
                "page_size": other.page_size,
            }
        else:
            mapping = other

        def _narrow_positive(current: int, key: str, *, zero_unlimited: bool = False) -> int:
            if key not in mapping or mapping[key] is None:
                return current
            try:
                requested = int(mapping[key])
            except (TypeError, ValueError) as exc:
                raise QueryRuntimeError(
                    "INVALID_REQUEST",
                    f"budget {key} must be an int",
                    details={"field": key, "value": mapping[key]},
                ) from exc
            if requested < 0:
                raise QueryRuntimeError(
                    "INVALID_REQUEST",
                    f"budget {key} must be non-negative",
                    details={"field": key, "value": requested},
                )
            if zero_unlimited:
                if current == 0:
                    return requested
                if requested == 0:
                    return current
                return min(current, requested)
            if requested == 0:
                # Non-unlimited fields reject 0.
                return current
            return min(current, requested)

        return QueryBudgets(
            time_ms=_narrow_positive(self.time_ms, "time_ms"),
            max_rows=_narrow_positive(self.max_rows, "max_rows"),
            max_bytes=_narrow_positive(self.max_bytes, "max_bytes", zero_unlimited=True),
            max_depth=_narrow_positive(self.max_depth, "max_depth"),
            max_fanout=_narrow_positive(self.max_fanout, "max_fanout"),
            max_memory_bytes=_narrow_positive(
                self.max_memory_bytes, "max_memory_bytes", zero_unlimited=True
            ),
            max_shard_fetches=_narrow_positive(
                self.max_shard_fetches, "max_shard_fetches", zero_unlimited=True
            ),
            page_size=_narrow_positive(self.page_size, "page_size"),
        )

    def to_json_dict(self) -> JSONDict:
        return {
            "time_ms": self.time_ms,
            "max_rows": self.max_rows,
            "max_bytes": self.max_bytes,
            "max_depth": self.max_depth,
            "max_fanout": self.max_fanout,
            "max_memory_bytes": self.max_memory_bytes,
            "max_shard_fetches": self.max_shard_fetches,
            "page_size": self.page_size,
        }

    @classmethod
    def from_mapping(cls, data: Optional[Mapping[str, Any]] = None) -> "QueryBudgets":
        if not data:
            return cls()
        # Accept service-contract aliases.
        normalized: Dict[str, Any] = dict(data)
        if "timeout_ms" in normalized and "time_ms" not in normalized:
            normalized["time_ms"] = normalized.pop("timeout_ms")
        known = {
            "time_ms",
            "max_rows",
            "max_bytes",
            "max_depth",
            "max_fanout",
            "max_memory_bytes",
            "max_shard_fetches",
            "page_size",
        }
        kwargs = {k: int(normalized[k]) for k in known if k in normalized and normalized[k] is not None}
        return cls(**kwargs)


@dataclass
class QueryUsage:
    """Mutable consumption counters for a query session."""

    rows_emitted: int = 0
    bytes_emitted: int = 0
    depth: int = 0
    fanout: int = 0  # max expansion observed at any hop
    fanout_current: int = 0
    memory_bytes: int = 0
    shard_fetches: int = 0
    nodes_visited: int = 0
    edges_visited: int = 0
    pages_emitted: int = 0
    started_mono: float = field(default_factory=time.monotonic)
    finished_mono: Optional[float] = None
    truncated: bool = False
    truncated_budget: Optional[str] = None
    cancelled: bool = False

    def elapsed_ms(self, *, now: Optional[float] = None) -> float:
        end = now if now is not None else (self.finished_mono or time.monotonic())
        return max(0.0, (end - self.started_mono) * 1000.0)

    def mark_finished(self) -> None:
        if self.finished_mono is None:
            self.finished_mono = time.monotonic()

    def to_json_dict(self) -> JSONDict:
        return {
            "rows_emitted": self.rows_emitted,
            "bytes_emitted": self.bytes_emitted,
            "depth": self.depth,
            "fanout": self.fanout,
            "memory_bytes": self.memory_bytes,
            "shard_fetches": self.shard_fetches,
            "nodes_visited": self.nodes_visited,
            "edges_visited": self.edges_visited,
            "pages_emitted": self.pages_emitted,
            "elapsed_ms": round(self.elapsed_ms(), 3),
            "truncated": self.truncated,
            "truncated_budget": self.truncated_budget,
            "cancelled": self.cancelled,
        }


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


class CancellationToken:
    """Thread-safe cooperative cancellation token.

    Callers set the token; the runtime checks it between row/page advances
    and before budget-sensitive work. Cancellation is sticky.
    """

    def __init__(self) -> None:
        self._event = threading.Event()
        self._reason: Optional[str] = None
        self._lock = threading.Lock()

    def cancel(self, reason: str = "cancelled by client") -> None:
        with self._lock:
            if not self._event.is_set():
                self._reason = reason
            self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> Optional[str]:
        return self._reason

    def check(self) -> None:
        if self._event.is_set():
            raise CancellationError(
                self._reason or "query cancelled",
                details={"reason": self._reason},
            )

    def wait(self, timeout: Optional[float] = None) -> bool:
        return self._event.wait(timeout)


# ---------------------------------------------------------------------------
# Query binding / digests
# ---------------------------------------------------------------------------


def canonicalize_json(value: Any) -> str:
    """Deterministic JSON for digests (sorted keys, no NaN, compact)."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    )


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (bytes, bytearray)):
        return base64.b64encode(bytes(obj)).decode("ascii")
    if isinstance(obj, set):
        return sorted(obj)
    raise TypeError(f"object of type {type(obj).__name__} is not JSON serializable")


def digest_query(
    language: str,
    text: str,
    params: Optional[Mapping[str, Any]] = None,
) -> str:
    """Content digest of the logical query (language + text + params)."""
    payload = {
        "language": str(language or ""),
        "text": str(text or ""),
        "params": dict(params or {}),
    }
    raw = canonicalize_json(payload).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def digest_authorization(auth: Optional[Mapping[str, Any]] = None) -> str:
    """Stable digest of authorization context bound into cursors.

    Empty / missing auth uses a well-known zero digest so unauthenticated
    sessions still get revision-bound cursors.
    """
    if not auth:
        return "0" * 64
    # Prefer explicit principal / ability / resource if present; fall back to
    # the full mapping so caveats cannot be swapped under a cursor.
    raw = canonicalize_json(dict(auth)).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def estimate_row_bytes(row: Any) -> int:
    """Approximate UTF-8 JSON byte size of a single row."""
    try:
        return len(canonicalize_json(row).encode("utf-8"))
    except (TypeError, ValueError):
        return len(repr(row).encode("utf-8", errors="replace"))


def estimate_rows_bytes(rows: Sequence[Any]) -> int:
    # Account for array brackets and commas roughly.
    if not rows:
        return 2
    total = 2  # []
    for i, row in enumerate(rows):
        total += estimate_row_bytes(row)
        if i:
            total += 1  # comma
    return total


# ---------------------------------------------------------------------------
# Opaque cursors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CursorBinding:
    """Identity a cursor is sealed to."""

    tenant: str
    graph_id: str
    revision: str
    query_digest: str
    authorization_digest: str

    def to_json_dict(self) -> JSONDict:
        return {
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "revision": self.revision,
            "query_digest": self.query_digest,
            "authorization_digest": self.authorization_digest,
        }

    @classmethod
    def from_target(
        cls,
        *,
        tenant: str,
        graph_id: str,
        revision: str,
        query_digest: str,
        authorization_digest: str = "0" * 64,
    ) -> "CursorBinding":
        if not tenant or not graph_id or not revision:
            raise QueryRuntimeError(
                "INVALID_TARGET",
                "cursor binding requires tenant, graph_id, and revision",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "revision": revision,
                },
            )
        return cls(
            tenant=str(tenant),
            graph_id=str(graph_id),
            revision=str(revision),
            query_digest=str(query_digest),
            authorization_digest=str(authorization_digest or ("0" * 64)),
        )


@dataclass(frozen=True, slots=True)
class CursorState:
    """Decoded cursor payload (offset + optional opaque state blob)."""

    offset: int
    state: Optional[JSONDict] = None

    def to_json_dict(self) -> JSONDict:
        return {
            "offset": self.offset,
            "state": dict(self.state) if self.state else None,
        }


class CursorCodec:
    """Encode / decode opaque revision-bound cursors.

    Wire format::

        kgc1.<urlsafe-b64(json-payload)>.<urlsafe-b64(hmac-sha256)>

    Payload fields: ``v``, binding fields, ``offset``, optional ``state``.
    """

    def __init__(self, secret: Union[str, bytes, None] = None) -> None:
        if secret is None:
            # Deterministic process-local default so unit tests and single-
            # process services work without configuration. Production
            # deployments should inject a stable secret so cursors survive
            # process restarts within a fleet.
            secret = b"kg-query-runtime-default-cursor-secret-v1"
        if isinstance(secret, str):
            secret = secret.encode("utf-8")
        self._secret = bytes(secret)

    def encode(
        self,
        binding: CursorBinding,
        *,
        offset: int,
        state: Optional[Mapping[str, Any]] = None,
    ) -> str:
        if offset < 0:
            raise QueryRuntimeError(
                "INVALID_REQUEST",
                "cursor offset must be non-negative",
                details={"offset": offset},
            )
        payload: JSONDict = {
            "v": CURSOR_VERSION,
            "tenant": binding.tenant,
            "graph_id": binding.graph_id,
            "revision": binding.revision,
            "query_digest": binding.query_digest,
            "authorization_digest": binding.authorization_digest,
            "offset": int(offset),
        }
        if state:
            payload["state"] = dict(state)
        body = canonicalize_json(payload).encode("utf-8")
        body_b64 = base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")
        mac = hmac.new(self._secret, body, hashlib.sha256).digest()
        mac_b64 = base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")
        return f"{CURSOR_PREFIX}{body_b64}.{mac_b64}"

    def decode(
        self,
        token: str,
        *,
        expected: CursorBinding,
    ) -> CursorState:
        if token is None or not isinstance(token, str) or not token:
            raise InvalidCursorError(
                "cursor must be a non-empty string",
                details={"cursor": token},
            )
        if not token.startswith(CURSOR_PREFIX):
            raise InvalidCursorError(
                "unrecognized cursor format",
                details={"prefix": token[:8] if token else ""},
            )
        rest = token[len(CURSOR_PREFIX) :]
        parts = rest.split(".")
        if len(parts) != 2:
            raise InvalidCursorError(
                "malformed cursor encoding",
                details={"parts": len(parts)},
            )
        body_b64, mac_b64 = parts
        try:
            body = _b64url_decode(body_b64)
            mac = _b64url_decode(mac_b64)
        except (ValueError, TypeError) as exc:
            raise InvalidCursorError(
                "cursor base64 decode failed",
                details={"error": str(exc)},
            ) from exc

        expected_mac = hmac.new(self._secret, body, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, expected_mac):
            raise InvalidCursorError(
                "cursor integrity check failed",
                details={"reason": "bad_mac"},
            )

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidCursorError(
                "cursor payload is not valid JSON",
                details={"error": str(exc)},
            ) from exc

        if not isinstance(payload, dict):
            raise InvalidCursorError("cursor payload must be an object")

        if int(payload.get("v", -1)) != CURSOR_VERSION:
            raise InvalidCursorError(
                "unsupported cursor version",
                details={"version": payload.get("v")},
            )

        self._assert_binding(payload, expected)

        try:
            offset = int(payload.get("offset", 0))
        except (TypeError, ValueError) as exc:
            raise InvalidCursorError(
                "cursor offset is not an integer",
                details={"offset": payload.get("offset")},
            ) from exc
        if offset < 0:
            raise InvalidCursorError(
                "cursor offset must be non-negative",
                details={"offset": offset},
            )

        state_raw = payload.get("state")
        state: Optional[JSONDict]
        if state_raw is None:
            state = None
        elif isinstance(state_raw, Mapping):
            state = dict(state_raw)
        else:
            raise InvalidCursorError(
                "cursor state must be an object or null",
                details={"state_type": type(state_raw).__name__},
            )
        return CursorState(offset=offset, state=state)

    @staticmethod
    def _assert_binding(payload: Mapping[str, Any], expected: CursorBinding) -> None:
        checks = (
            ("tenant", expected.tenant),
            ("graph_id", expected.graph_id),
            ("revision", expected.revision),
            ("query_digest", expected.query_digest),
            ("authorization_digest", expected.authorization_digest),
        )
        mismatches: Dict[str, Any] = {}
        for key, want in checks:
            got = payload.get(key)
            if got != want:
                mismatches[key] = {"expected": want, "actual": got}
        if mismatches:
            # Service contract: reusing a cursor against a different revision
            # (or graph) returns INVALID_REQUEST.
            raise InvalidCursorError(
                "cursor is not valid for this target/query/authorization",
                details={"mismatches": mismatches},
            )


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


# ---------------------------------------------------------------------------
# Statistics and pages
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QueryStatistics:
    """JSON-safe execution statistics for a page or completed session."""

    elapsed_ms: float
    rows_emitted: int = 0
    bytes_emitted: int = 0
    nodes_visited: int = 0
    edges_visited: int = 0
    depth: int = 0
    fanout: int = 0
    memory_bytes: int = 0
    shard_fetches: int = 0
    pages_emitted: int = 0
    truncated: bool = False
    truncated_budget: Optional[str] = None
    budgets: Optional[JSONDict] = None
    extra: JSONDict = field(default_factory=dict)

    def to_json_dict(self) -> JSONDict:
        out: JSONDict = {
            "elapsed_ms": round(float(self.elapsed_ms), 3),
            "rows_emitted": int(self.rows_emitted),
            "bytes_emitted": int(self.bytes_emitted),
            "nodes_visited": int(self.nodes_visited),
            "edges_visited": int(self.edges_visited),
            "depth": int(self.depth),
            "fanout": int(self.fanout),
            "memory_bytes": int(self.memory_bytes),
            "shard_fetches": int(self.shard_fetches),
            "pages_emitted": int(self.pages_emitted),
            "truncated": bool(self.truncated),
            "truncated_budget": self.truncated_budget,
        }
        if self.budgets is not None:
            out["budgets"] = dict(self.budgets)
        if self.extra:
            for k, v in self.extra.items():
                if k not in out:
                    out[k] = v
        # Guarantee JSON safety (finite numbers only).
        return json.loads(canonicalize_json(out))

    @classmethod
    def from_usage(
        cls,
        usage: QueryUsage,
        *,
        budgets: Optional[QueryBudgets] = None,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> "QueryStatistics":
        return cls(
            elapsed_ms=usage.elapsed_ms(),
            rows_emitted=usage.rows_emitted,
            bytes_emitted=usage.bytes_emitted,
            nodes_visited=usage.nodes_visited,
            edges_visited=usage.edges_visited,
            depth=usage.depth,
            fanout=usage.fanout,
            memory_bytes=usage.memory_bytes,
            shard_fetches=usage.shard_fetches,
            pages_emitted=usage.pages_emitted,
            truncated=usage.truncated,
            truncated_budget=usage.truncated_budget,
            budgets=budgets.to_json_dict() if budgets is not None else None,
            extra=dict(extra or {}),
        )


@dataclass(frozen=True, slots=True)
class QueryPage:
    """One bounded streaming page of query results."""

    columns: List[str]
    rows: List[Any]
    cursor: Optional[str]
    statistics: QueryStatistics
    truncated: bool = False
    warnings: Tuple[str, ...] = ()
    schema: str = "kg-query-row/v1"

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def to_json_dict(self) -> JSONDict:
        return {
            "schema": self.schema,
            "columns": list(self.columns),
            "rows": list(self.rows),
            "row_count": len(self.rows),
            "cursor": self.cursor,
            "statistics": self.statistics.to_json_dict(),
            "truncated": bool(self.truncated),
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Session + runtime
# ---------------------------------------------------------------------------


class QuerySession:
    """Stateful enforcement context for one bound query execution.

    Tracks usage, checks budgets and cancellation, issues and validates
    cursors, and emits bounded streaming pages.
    """

    def __init__(
        self,
        *,
        binding: CursorBinding,
        budgets: QueryBudgets,
        codec: CursorCodec,
        cancel: Optional[CancellationToken] = None,
        truncate_on_budget: bool = True,
        clock: Optional[ClockFn] = None,
        columns: Optional[Sequence[str]] = None,
        schema: str = "kg-query-row/v1",
    ) -> None:
        self.binding = binding
        self.budgets = budgets
        self.codec = codec
        self.cancel = cancel or CancellationToken()
        self.truncate_on_budget = bool(truncate_on_budget)
        self._clock: ClockFn = clock or time.monotonic
        self.columns = list(columns or [])
        self.schema = schema
        self.usage = QueryUsage(started_mono=self._clock())
        self._lock = threading.RLock()
        self._closed = False

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self.usage.mark_finished()
            self._closed = True

    def __enter__(self) -> "QuerySession":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
        return None

    # -- checks -------------------------------------------------------------

    def check_cancelled(self) -> None:
        try:
            self.cancel.check()
        except CancellationError:
            self.usage.cancelled = True
            self.usage.mark_finished()
            raise

    def check_time(self) -> None:
        elapsed = self.usage.elapsed_ms(now=self._clock())
        if elapsed > self.budgets.time_ms:
            raise BudgetExceededError.exceeded(
                "time_ms",
                actual=int(elapsed),
                limit=self.budgets.time_ms,
                unit="ms",
            )

    def check_depth(self) -> None:
        if self.usage.depth > self.budgets.max_depth:
            raise BudgetExceededError.exceeded(
                "max_depth",
                actual=self.usage.depth,
                limit=self.budgets.max_depth,
            )

    def check_fanout(self) -> None:
        if self.usage.fanout > self.budgets.max_fanout:
            raise BudgetExceededError.exceeded(
                "max_fanout",
                actual=self.usage.fanout,
                limit=self.budgets.max_fanout,
            )

    def check_memory(self) -> None:
        limit = self.budgets.max_memory_bytes
        if limit > 0 and self.usage.memory_bytes > limit:
            raise BudgetExceededError.exceeded(
                "max_memory_bytes",
                actual=self.usage.memory_bytes,
                limit=limit,
                unit="B",
            )

    def check_shard_fetches(self) -> None:
        limit = self.budgets.max_shard_fetches
        if limit > 0 and self.usage.shard_fetches > limit:
            raise BudgetExceededError.exceeded(
                "max_shard_fetches",
                actual=self.usage.shard_fetches,
                limit=limit,
            )

    def check_all_hard(self) -> None:
        """Check cancellation and hard budgets (time/depth/fanout/memory/shards)."""
        self.check_cancelled()
        self.check_time()
        self.check_depth()
        self.check_fanout()
        self.check_memory()
        self.check_shard_fetches()

    # -- counters -----------------------------------------------------------

    def record_depth(self, depth: int) -> None:
        with self._lock:
            self.usage.depth = max(self.usage.depth, int(depth))
            self.check_depth()

    def record_fanout(self, expansion: int) -> None:
        with self._lock:
            expansion = int(expansion)
            self.usage.fanout_current = expansion
            self.usage.fanout = max(self.usage.fanout, expansion)
            self.check_fanout()

    def record_memory(self, bytes_used: int) -> None:
        with self._lock:
            self.usage.memory_bytes = max(self.usage.memory_bytes, int(bytes_used))
            self.check_memory()

    def add_memory(self, delta: int) -> None:
        with self._lock:
            self.usage.memory_bytes += int(delta)
            self.check_memory()

    def record_shard_fetch(self, count: int = 1) -> None:
        with self._lock:
            self.usage.shard_fetches += int(count)
            self.check_shard_fetches()

    def record_nodes(self, count: int = 1) -> None:
        with self._lock:
            self.usage.nodes_visited += int(count)

    def record_edges(self, count: int = 1) -> None:
        with self._lock:
            self.usage.edges_visited += int(count)

    # -- cursors ------------------------------------------------------------

    def issue_cursor(
        self,
        *,
        offset: int,
        state: Optional[Mapping[str, Any]] = None,
    ) -> str:
        return self.codec.encode(self.binding, offset=offset, state=state)

    def open_cursor(self, token: Optional[str]) -> CursorState:
        """Validate and open a client-supplied cursor for this binding.

        ``None`` / empty starts at offset 0.
        """
        if token is None or token == "":
            return CursorState(offset=0, state=None)
        return self.codec.decode(token, expected=self.binding)

    # -- paging / streaming -------------------------------------------------

    def stream_pages(
        self,
        rows: Iterable[Any],
        *,
        cursor: Optional[str] = None,
        columns: Optional[Sequence[str]] = None,
    ) -> Iterator[QueryPage]:
        """Emit bounded streaming pages from an iterable of rows.

        Respects ``page_size`` / ``max_rows`` / ``max_bytes`` / ``time_ms``,
        propagates cancellation, and binds continuation cursors to this
        session's target/query/authorization.
        """
        cols = list(columns if columns is not None else self.columns)
        start = self.open_cursor(cursor)
        offset = start.offset
        page_size = self.budgets.effective_page_size()
        max_bytes = self.budgets.max_bytes

        # Skip to offset without materializing the entire stream when possible.
        iterator = iter(rows)
        skipped = 0
        while skipped < offset:
            self.check_all_hard()
            try:
                next(iterator)
            except StopIteration:
                # Cursor past end → empty exhausted page.
                self.usage.mark_finished()
                yield self._make_page(
                    columns=cols,
                    rows=[],
                    next_offset=None,
                    page_truncated=False,
                )
                return
            skipped += 1

        exhausted = False
        while not exhausted:
            self.check_all_hard()
            page_rows: List[Any] = []
            page_bytes = 2  # []
            page_truncated = False
            truncated_budget: Optional[str] = None

            while len(page_rows) < page_size:
                self.check_all_hard()
                # Global row cap across the whole session (not just this page).
                if self.usage.rows_emitted + len(page_rows) >= self.budgets.max_rows:
                    # More input may exist; soft truncate if configured.
                    try:
                        peek = next(iterator)
                    except StopIteration:
                        exhausted = True
                        break
                    # Put peek back by prepending a chain.
                    iterator = _chain_one(peek, iterator)
                    if self.truncate_on_budget:
                        page_truncated = True
                        truncated_budget = "max_rows"
                        exhausted = True
                        break
                    raise BudgetExceededError.exceeded(
                        "max_rows",
                        actual=self.usage.rows_emitted + len(page_rows) + 1,
                        limit=self.budgets.max_rows,
                    )

                try:
                    row = next(iterator)
                except StopIteration:
                    exhausted = True
                    break

                row_bytes = estimate_row_bytes(row)
                projected = page_bytes + row_bytes + (1 if page_rows else 0)
                if max_bytes > 0 and page_rows and projected > max_bytes:
                    # Do not take this row; emit page and continue with row next.
                    iterator = _chain_one(row, iterator)
                    if self.truncate_on_budget:
                        page_truncated = True
                        truncated_budget = "max_bytes"
                        break
                    raise BudgetExceededError.exceeded(
                        "max_bytes",
                        actual=projected,
                        limit=max_bytes,
                        unit="B",
                    )
                if max_bytes > 0 and not page_rows and row_bytes + 2 > max_bytes:
                    # Single row exceeds byte budget — hard error.
                    raise BudgetExceededError.exceeded(
                        "max_bytes",
                        actual=row_bytes + 2,
                        limit=max_bytes,
                        unit="B",
                        detail="single row exceeds max_bytes",
                    )

                page_rows.append(row)
                page_bytes = projected
                # Approximate working-set growth.
                self.usage.memory_bytes = max(
                    self.usage.memory_bytes,
                    self.usage.bytes_emitted + page_bytes,
                )
                try:
                    self.check_memory()
                except BudgetExceededError:
                    if self.truncate_on_budget and len(page_rows) > 0:
                        # Drop the last row to stay under memory if possible.
                        dropped = page_rows.pop()
                        iterator = _chain_one(dropped, iterator)
                        page_truncated = True
                        truncated_budget = "max_memory_bytes"
                        # Recompute page_bytes roughly.
                        page_bytes = estimate_rows_bytes(page_rows)
                        self.usage.memory_bytes = self.usage.bytes_emitted + page_bytes
                        break
                    raise

            # If this page consumed the global row budget, detect leftover input
            # so soft-truncate / hard-error policies can fire even when the
            # page filled exactly to ``effective_page_size == max_rows``.
            if (
                not exhausted
                and truncated_budget is None
                and (self.usage.rows_emitted + len(page_rows)) >= self.budgets.max_rows
            ):
                try:
                    peek = next(iterator)
                    iterator = _chain_one(peek, iterator)
                    if self.truncate_on_budget:
                        page_truncated = True
                        truncated_budget = "max_rows"
                        exhausted = True
                    else:
                        raise BudgetExceededError.exceeded(
                            "max_rows",
                            actual=self.usage.rows_emitted + len(page_rows) + 1,
                            limit=self.budgets.max_rows,
                        )
                except StopIteration:
                    exhausted = True

            if not page_rows and exhausted:
                # Final empty page only when we never emitted anything this loop
                # after starting mid-stream exhaustion — still yield once if
                # this is the first page (cursor at/ past end already handled).
                if self.usage.pages_emitted == 0:
                    self.usage.mark_finished()
                    yield self._make_page(
                        columns=cols,
                        rows=[],
                        next_offset=None,
                        page_truncated=False,
                    )
                break

            if not page_rows:
                break

            next_offset: Optional[int]
            if exhausted and not page_truncated:
                next_offset = None
            else:
                # More data remains (or soft truncate implies continuation).
                # When truncated due to max_rows, do not issue a cursor that
                # would allow exceeding the global row budget.
                if truncated_budget == "max_rows":
                    next_offset = None
                else:
                    # Peek whether anything remains.
                    try:
                        peek = next(iterator)
                        iterator = _chain_one(peek, iterator)
                        next_offset = offset + len(page_rows)
                    except StopIteration:
                        exhausted = True
                        next_offset = None

            with self._lock:
                self.usage.rows_emitted += len(page_rows)
                self.usage.bytes_emitted += page_bytes
                self.usage.pages_emitted += 1
                if page_truncated:
                    self.usage.truncated = True
                    self.usage.truncated_budget = truncated_budget

            page = self._make_page(
                columns=cols,
                rows=page_rows,
                next_offset=next_offset,
                page_truncated=page_truncated,
                truncated_budget=truncated_budget,
            )
            yield page
            if next_offset is None:
                break
            offset = next_offset
            if truncated_budget == "max_rows":
                break

        self.usage.mark_finished()

    def page_from_sequence(
        self,
        rows: Sequence[Any],
        *,
        cursor: Optional[str] = None,
        columns: Optional[Sequence[str]] = None,
    ) -> QueryPage:
        """Return a single page from a random-access sequence (scan helpers)."""
        pages = list(self.stream_pages(rows, cursor=cursor, columns=columns))
        if not pages:
            return self._make_page(
                columns=list(columns if columns is not None else self.columns),
                rows=[],
                next_offset=None,
                page_truncated=False,
            )
        # When streaming yields multiple pages, callers that want one page
        # receive the first; remaining data is reachable via the cursor.
        return pages[0]

    def statistics(self, *, extra: Optional[Mapping[str, Any]] = None) -> QueryStatistics:
        return QueryStatistics.from_usage(
            self.usage,
            budgets=self.budgets,
            extra=extra,
        )

    def _make_page(
        self,
        *,
        columns: Sequence[str],
        rows: List[Any],
        next_offset: Optional[int],
        page_truncated: bool,
        truncated_budget: Optional[str] = None,
    ) -> QueryPage:
        cursor_token: Optional[str] = None
        if next_offset is not None:
            cursor_token = self.issue_cursor(offset=next_offset)
        stats = QueryStatistics.from_usage(
            self.usage,
            budgets=self.budgets,
            extra={
                "page_rows": len(rows),
                "page_truncated_budget": truncated_budget,
            },
        )
        # Reflect this page's truncation even if usage was already updated.
        if page_truncated and not stats.truncated:
            stats = replace(
                stats,
                truncated=True,
                truncated_budget=truncated_budget or stats.truncated_budget,
            )
        return QueryPage(
            columns=list(columns),
            rows=list(rows),
            cursor=cursor_token,
            statistics=stats,
            truncated=bool(page_truncated or self.usage.truncated),
            schema=self.schema,
        )


def _chain_one(first: Any, rest: Iterator[Any]) -> Iterator[Any]:
    yield first
    yield from rest


class QueryRuntime:
    """Factory for budgeted, cancellation-aware query sessions.

    Intended to sit under GraphService / GraphQueryExecutor so every surface
    shares identical budget, cursor, and cancellation semantics.
    """

    def __init__(
        self,
        *,
        default_budgets: Optional[QueryBudgets] = None,
        cursor_secret: Union[str, bytes, None] = None,
        truncate_on_budget: bool = True,
        clock: Optional[ClockFn] = None,
    ) -> None:
        self.default_budgets = default_budgets or QueryBudgets()
        self.codec = CursorCodec(cursor_secret)
        self.truncate_on_budget = bool(truncate_on_budget)
        self._clock = clock

    @property
    def api_version(self) -> str:
        return RUNTIME_API_VERSION

    def open_session(
        self,
        *,
        tenant: str,
        graph_id: str,
        revision: str,
        language: str = "scan",
        text: str = "",
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        budgets: Optional[Mapping[str, Any] | QueryBudgets] = None,
        cancel: Optional[CancellationToken] = None,
        columns: Optional[Sequence[str]] = None,
        schema: str = "kg-query-row/v1",
        query_digest: Optional[str] = None,
        authorization_digest: Optional[str] = None,
        truncate_on_budget: Optional[bool] = None,
    ) -> QuerySession:
        q_digest = query_digest or digest_query(language, text, params)
        a_digest = authorization_digest or digest_authorization(auth)
        binding = CursorBinding.from_target(
            tenant=tenant,
            graph_id=graph_id,
            revision=revision,
            query_digest=q_digest,
            authorization_digest=a_digest,
        )
        effective = self.default_budgets.narrow(budgets)
        return QuerySession(
            binding=binding,
            budgets=effective,
            codec=self.codec,
            cancel=cancel,
            truncate_on_budget=(
                self.truncate_on_budget
                if truncate_on_budget is None
                else bool(truncate_on_budget)
            ),
            clock=self._clock,
            columns=columns,
            schema=schema,
        )

    def stream(
        self,
        rows: Iterable[Any],
        *,
        tenant: str,
        graph_id: str,
        revision: str,
        language: str = "scan",
        text: str = "",
        params: Optional[Mapping[str, Any]] = None,
        auth: Optional[Mapping[str, Any]] = None,
        budgets: Optional[Mapping[str, Any] | QueryBudgets] = None,
        cursor: Optional[str] = None,
        cancel: Optional[CancellationToken] = None,
        columns: Optional[Sequence[str]] = None,
    ) -> Generator[QueryPage, None, QuerySession]:
        """Stream pages and return the session as the generator's value."""
        session = self.open_session(
            tenant=tenant,
            graph_id=graph_id,
            revision=revision,
            language=language,
            text=text,
            params=params,
            auth=auth,
            budgets=budgets,
            cancel=cancel,
            columns=columns,
        )
        try:
            yield from session.stream_pages(rows, cursor=cursor, columns=columns)
        finally:
            session.close()
        return session


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "RUNTIME_API_VERSION",
    "CURSOR_VERSION",
    "CURSOR_PREFIX",
    "TYPED_ERROR_CODES",
    "QueryRuntimeError",
    "BudgetExceededError",
    "CancellationError",
    "InvalidCursorError",
    "QueryBudgets",
    "QueryUsage",
    "CancellationToken",
    "CursorBinding",
    "CursorState",
    "CursorCodec",
    "QueryStatistics",
    "QueryPage",
    "QuerySession",
    "QueryRuntime",
    "canonicalize_json",
    "digest_query",
    "digest_authorization",
    "estimate_row_bytes",
    "estimate_rows_bytes",
]
