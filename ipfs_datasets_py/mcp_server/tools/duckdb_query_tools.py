"""Safe MCP/CLI query and export endpoints over the allowlisted registry.

DQK-043 — control-plane DuckDB query tools:

* ``query`` — execute an allowlisted template under tenant/snapshot policy
* ``explain`` — describe a prepared invocation without exposing raw SQL
* ``export`` — snapshot-bound deterministic export via the DQK-045 exporter
* ``status`` — inspect an in-flight or completed query handle
* ``cancel`` — cancel a handle-bound execution
* ``page`` — bounded pagination over a completed result set
* ``list_templates`` — enumerate allowlisted template ids

DQK-093 — DuckLake query/export tools (template registry + DQK-104 gateway):

* ``ducklake_discover_catalogs`` / ``ducklake_discover_datasets``
* ``ducklake_select_snapshot`` — snapshot / time-travel selection
* ``ducklake_explain`` / ``ducklake_query`` / ``ducklake_export``
* ``ducklake_cancel`` / ``ducklake_status`` / ``ducklake_page``
* ``ducklake_list_templates``

Security properties
-------------------
* Callers **cannot bypass** the query registry: raw SQL arguments, SQL-shaped
  parameter keys, and unregistered template ids fail closed.
* Catalog-management calls use DQK-104; query/export use bounded snapshot-bound
  workers or the sanitized publication plane.
* Cancellation and bounded pagination are first-class (hard page-size caps,
  handle-bound page tokens).
* Public errors never leak secrets, raw SQL, tokens, catalog credentials,
  encryption keys, Quack tokens, or unrestricted object URIs.
* Untrusted remote access remains a typed broker or sanitized publication
  operation rather than direct authority-catalog Quack access.
* Every successful operation binds a snapshot identity and capability pin
  summary so callers are tied to the control-plane version policy.

Importing this module is inert: no DuckDB, network, or filesystem I/O.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import (
    Any,
    Callable,
    Final,
    Mapping,
    MutableMapping,
    Sequence,
)

from ipfs_datasets_py.duckdb_control.capabilities import (
    policy_pin_summary,
)
from ipfs_datasets_py.duckdb_control.contracts import (
    ContractError,
    SnapshotId,
)
from ipfs_datasets_py.duckdb_control.exporter import (
    ExportFormat,
    ExportJob,
    SnapshotExporter,
    default_destination_policy,
)
from ipfs_datasets_py.duckdb_control import query_registry as qr
from ipfs_datasets_py.duckdb_control.quack_security import (
    REDACTION_MARKER,
    redact_sql,
)

__all__ = [
    "QUERY_TOOLS_SCHEMA",
    "QUERY_TOOLS_IMPLEMENTATION_GENERATION",
    "DUCKLAKE_TOOLS_SCHEMA",
    "DUCKLAKE_TOOLS_IMPLEMENTATION_GENERATION",
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "MAX_HANDLES",
    "HandleStatus",
    "QueryToolsError",
    "QueryHandle",
    "DuckDBQueryGateway",
    "open_default_gateway",
    "sanitize_public_error",
    "duckdb_query",
    "duckdb_explain",
    "duckdb_export",
    "duckdb_query_status",
    "duckdb_query_cancel",
    "duckdb_query_page",
    "duckdb_list_templates",
    # DQK-093 DuckLake surface
    "get_default_ducklake_api",
    "set_default_ducklake_api",
    "ducklake_discover_catalogs",
    "ducklake_discover_datasets",
    "ducklake_select_snapshot",
    "ducklake_list_templates",
    "ducklake_explain",
    "ducklake_query",
    "ducklake_export",
    "ducklake_query_status",
    "ducklake_query_cancel",
    "ducklake_query_page",
]


# ---------------------------------------------------------------------------
# Schema / bounds
# ---------------------------------------------------------------------------

QUERY_TOOLS_SCHEMA: Final[str] = (
    "ipfs_datasets_py/mcp-duckdb-query-tools@1"
)
QUERY_TOOLS_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-043-lane3-attempt1-20260810"
)
DUCKLAKE_TOOLS_SCHEMA: Final[str] = (
    "ipfs_datasets_py/mcp-ducklake-query-tools@1"
)
DUCKLAKE_TOOLS_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-093-ducklake-query-export-mcp-20260810"
)

DEFAULT_PAGE_SIZE: Final[int] = 100
MAX_PAGE_SIZE: Final[int] = 500
MAX_HANDLES: Final[int] = 10_000
MAX_ERROR_DETAIL_BYTES: Final[int] = 512

_SAFE_REASON = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+ -]{0,127}$")

# Patterns that must never appear in public error surfaces.
_SECRET_LEAK_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|"
               r"authorization|bearer|private[_-]?key|mnemonic|seed)\b"),
    re.compile(r"(?i)\b(quack[_-]?token|encryption[_-]?key|signing[_-]?key)\b"),
    re.compile(r"(?i)\b(SELECT|INSERT|UPDATE|DELETE|DROP|ATTACH|COPY|"
               r"INSTALL|LOAD|PRAGMA|CREATE|ALTER)\b"),
    re.compile(r"(?i)(https?://|s3://|gs://|az://|file://)"),
    re.compile(r"(?i)(/[A-Za-z0-9._-]+){3,}"),  # path-like
    re.compile(r"(?i)\\[A-Za-z]"),  # windows path fragments
)


# ---------------------------------------------------------------------------
# Errors / status
# ---------------------------------------------------------------------------


class QueryToolsError(ValueError):
    """Fail-closed rejection of an MCP/CLI query-tool invocation."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "query_tools.error",
        status: str = "error",
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.status = status


class HandleStatus(str, Enum):
    """Lifecycle status of a query handle."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    TRUNCATED = "truncated"
    CANCELLED = "cancelled"
    BUDGET_EXCEEDED = "budget_exceeded"
    FAILED = "failed"
    DENIED = "denied"


# ---------------------------------------------------------------------------
# Public error sanitization
# ---------------------------------------------------------------------------


def sanitize_public_error(
    exc: BaseException | str,
    *,
    reason_code: str | None = None,
    fallback: str = "request denied",
) -> dict[str, Any]:
    """Return a public error envelope free of secrets, SQL, tokens, and paths.

    Registry reason codes are preserved when present. Exception message text is
    rewritten to a closed, non-leaking vocabulary unless it is already safe.
    """

    code = reason_code
    if code is None and hasattr(exc, "reason_code"):
        raw = getattr(exc, "reason_code")
        if isinstance(raw, str) and raw.strip():
            code = raw.strip()
    if not code:
        if isinstance(exc, qr.UnknownTemplateError):
            code = "query.unknown_template"
        elif isinstance(exc, qr.SQLSurfaceDenied):
            code = "query.sql_surface_denied"
        elif isinstance(exc, qr.ParameterValidationError):
            code = "query.parameter_validation"
        elif isinstance(exc, qr.TenantPolicyViolation):
            code = "query.tenant_policy_violation"
        elif isinstance(exc, qr.ColumnPolicyError):
            code = "query.column_policy"
        elif isinstance(exc, qr.QueryBudgetExceeded):
            code = "query.budget_exceeded"
        elif isinstance(exc, qr.QueryCancelled):
            code = "query.cancelled"
        elif isinstance(exc, qr.QueryRegistryError):
            code = "query.registry_error"
        elif isinstance(exc, QueryToolsError):
            code = exc.reason_code
        else:
            code = "query_tools.error"

    # Prefer a closed message map over exception text for known codes.
    safe_messages: Mapping[str, str] = {
        "query.unknown_template": "query template not allowlisted",
        "query.sql_surface_denied": "arbitrary SQL and denied surfaces are forbidden",
        "query.parameter_validation": "parameter validation failed",
        "query.tenant_policy_violation": "tenant policy violation",
        "query.column_policy": "column policy violation",
        "query.budget_exceeded": "query budget exceeded",
        "query.cancelled": "query cancelled",
        "query.registry_error": "query registry rejected the request",
        "query_tools.missing_template_id": "template_id is required",
        "query_tools.missing_snapshot": "snapshot_id is required",
        "query_tools.missing_tenant": "tenant_id is required",
        "query_tools.missing_handle": "handle_id is required",
        "query_tools.unknown_handle": "unknown query handle",
        "query_tools.invalid_page_token": "invalid or expired page token",
        "query_tools.page_out_of_range": "page offset out of range",
        "query_tools.capability_mismatch": "capability pin mismatch",
        "query_tools.invalid_page_size": "page_size out of allowed range",
        "query_tools.export_failed": "export failed",
        "query_tools.handle_not_pageable": "handle has no pageable result set",
        "query_tools.already_terminal": "handle is already terminal",
    }
    message = safe_messages.get(code)
    if message is None:
        raw = str(exc) if not isinstance(exc, str) else exc
        message = _scrub_text(raw) or fallback

    return {
        "status": "error",
        "error": message,
        "reason_code": code,
        "schema": QUERY_TOOLS_SCHEMA,
    }


def _scrub_text(text: str) -> str:
    """Redact likely secret/SQL/token/path content from free-form text."""

    if not text:
        return ""
    cleaned = str(text)
    # Explicit token/SQL redactors first.
    cleaned = re.sub(
        r"(?i)\b(bearer\s+)[A-Za-z0-9\-._~+/]+=*",
        rf"\1{REDACTION_MARKER}",
        cleaned,
    )
    cleaned = re.sub(
        r"(?i)\b(token|password|secret|api_key|quack_token)\s*[:=]\s*\S+",
        rf"\1={REDACTION_MARKER}",
        cleaned,
    )
    for pattern in _SECRET_LEAK_PATTERNS:
        if pattern.search(cleaned):
            # Collapse to a non-informative safe phrase rather than partial leak.
            return "request denied"
    # Bound length.
    encoded = cleaned.encode("utf-8", errors="replace")
    if len(encoded) > MAX_ERROR_DETAIL_BYTES:
        cleaned = encoded[:MAX_ERROR_DETAIL_BYTES].decode(
            "utf-8", errors="ignore"
        ) + "…"
    return cleaned.strip() or "request denied"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _new_handle_id() -> str:
    return f"qh-{uuid.uuid4().hex}"


def _clamp_page_size(value: Any) -> int:
    if value is None:
        return DEFAULT_PAGE_SIZE
    if isinstance(value, bool) or not isinstance(value, int):
        raise QueryToolsError(
            "page_size must be a positive integer",
            reason_code="query_tools.invalid_page_size",
        )
    if value < 1 or value > MAX_PAGE_SIZE:
        raise QueryToolsError(
            f"page_size must be in [1, {MAX_PAGE_SIZE}]",
            reason_code="query_tools.invalid_page_size",
        )
    return value


def _capability_binding(
    *,
    require_duckdb_version: str | None = None,
    capability_pins: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return capability pin summary; fail closed on caller pin mismatch."""

    pins = dict(policy_pin_summary())
    if require_duckdb_version is not None:
        requested = str(require_duckdb_version).strip()
        if requested and requested != pins.get("duckdb"):
            raise QueryToolsError(
                "capability pin mismatch",
                reason_code="query_tools.capability_mismatch",
            )
    if capability_pins:
        for key in ("duckdb", "quack_build", "vss_build"):
            if key in capability_pins and capability_pins[key] is not None:
                if str(capability_pins[key]) != str(pins.get(key)):
                    raise QueryToolsError(
                        "capability pin mismatch",
                        reason_code="query_tools.capability_mismatch",
                    )
    return pins


def _parse_snapshot(
    snapshot_id: SnapshotId | str | Mapping[str, Any] | None,
    *,
    store_generation: int | None = None,
) -> SnapshotId:
    if snapshot_id is None or (
        isinstance(snapshot_id, str) and not snapshot_id.strip()
    ):
        raise QueryToolsError(
            "snapshot_id is required",
            reason_code="query_tools.missing_snapshot",
        )
    if isinstance(snapshot_id, SnapshotId):
        return snapshot_id
    if isinstance(snapshot_id, Mapping):
        value = snapshot_id.get("value") or snapshot_id.get("snapshot_id")
        gen = snapshot_id.get("store_generation", store_generation or 0)
        if value is None:
            raise QueryToolsError(
                "snapshot_id is required",
                reason_code="query_tools.missing_snapshot",
            )
        try:
            return SnapshotId(value=str(value), store_generation=int(gen or 0))
        except (ContractError, TypeError, ValueError) as exc:
            raise QueryToolsError(
                "invalid snapshot_id",
                reason_code="query.registry_error",
            ) from exc
    try:
        return SnapshotId(
            value=str(snapshot_id),
            store_generation=int(store_generation or 0),
        )
    except (ContractError, TypeError, ValueError) as exc:
        raise QueryToolsError(
            "invalid snapshot_id",
            reason_code="query.registry_error",
        ) from exc


def _parse_trust(trust: TrustLike) -> qr.TrustClass:
    if isinstance(trust, qr.TrustClass):
        return trust
    text = str(trust or "untrusted").strip().lower()
    try:
        return qr.TrustClass(text)
    except ValueError as exc:
        raise QueryToolsError(
            "invalid trust class",
            reason_code="query.registry_error",
        ) from exc


TrustLike = qr.TrustClass | str


def _public_receipt(receipt: qr.QueryReceipt) -> dict[str, Any]:
    """Serialize a receipt without template SQL or secret material."""

    return {
        "receipt_id": receipt.receipt_id,
        "template_id": receipt.template_id,
        "template_version": receipt.template_version,
        "template_identity": receipt.template_identity,
        "parameters_digest": receipt.parameters_digest,
        "snapshot": receipt.snapshot.to_dict(),
        "policy_id": receipt.policy_id,
        "tenant_id": receipt.tenant_id,
        "trust": receipt.trust.value,
        "status": receipt.status.value,
        "resource_usage": receipt.resource_usage.to_dict(),
        "budget": receipt.budget.to_dict(),
        "column_policy_identity": receipt.column_policy_identity,
        "parameter_schema_identity": receipt.parameter_schema_identity,
        "row_count": receipt.row_count,
        "truncated": receipt.truncated,
        "created_at": receipt.created_at,
        "domains": list(receipt.domains),
        "identity_id": receipt.identity_id,
    }


# ---------------------------------------------------------------------------
# Handles / pagination tokens
# ---------------------------------------------------------------------------


@dataclass
class QueryHandle:
    """Server-side state for one query/export invocation."""

    handle_id: str
    template_id: str
    snapshot: SnapshotId
    tenant_id: str
    trust: qr.TrustClass
    status: HandleStatus
    created_at: str
    cancellation: qr.CancellationToken = field(default_factory=qr.CancellationToken)
    page_size: int = DEFAULT_PAGE_SIZE
    rows: tuple[Mapping[str, Any], ...] = ()
    receipt: qr.QueryReceipt | None = None
    parameters_digest: str = ""
    error: dict[str, Any] | None = None
    operation: str = "query"
    export_summary: dict[str, Any] | None = None
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.updated_at:
            self.updated_at = self.created_at

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            HandleStatus.SUCCEEDED,
            HandleStatus.TRUNCATED,
            HandleStatus.CANCELLED,
            HandleStatus.BUDGET_EXCEEDED,
            HandleStatus.FAILED,
            HandleStatus.DENIED,
        }

    def public_status(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "handle_id": self.handle_id,
            "handle_status": self.status.value,
            "operation": self.operation,
            "template_id": self.template_id,
            "snapshot": self.snapshot.to_dict(),
            "tenant_id": self.tenant_id,
            "trust": self.trust.value,
            "page_size": self.page_size,
            "row_count": len(self.rows),
            "parameters_digest": self.parameters_digest,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "cancelled": self.cancellation.is_cancelled,
        }
        if self.receipt is not None:
            body["receipt"] = _public_receipt(self.receipt)
        if self.error is not None:
            body["error"] = self.error
        if self.export_summary is not None:
            body["export"] = self.export_summary
        return body


class _PageTokenCodec:
    """HMAC-bound page tokens so offsets cannot be forged across handles.

    Wire format (urlsafe base64, no padding)::

        payload_utf8 || hmac_sha256(secret, payload_utf8)

    The signature is a fixed 32-byte suffix so binary ``|`` bytes cannot
    corrupt framing.
    """

    _SIG_LEN: Final[int] = 32

    def __init__(self, secret: bytes | None = None) -> None:
        self._secret = secret if secret is not None else secrets.token_bytes(32)

    def mint(self, handle_id: str, offset: int) -> str | None:
        if offset < 0:
            return None
        payload = f"{handle_id}:{offset}".encode("utf-8")
        sig = hmac.new(self._secret, payload, hashlib.sha256).digest()
        raw = base64.urlsafe_b64encode(payload + sig).decode("ascii")
        return raw.rstrip("=")

    def parse(self, handle_id: str, token: str) -> int:
        if not token or not isinstance(token, str):
            raise QueryToolsError(
                "invalid or expired page token",
                reason_code="query_tools.invalid_page_token",
            )
        pad = "=" * (-len(token) % 4)
        try:
            raw = base64.urlsafe_b64decode(token + pad)
        except (ValueError, TypeError) as exc:
            raise QueryToolsError(
                "invalid or expired page token",
                reason_code="query_tools.invalid_page_token",
            ) from exc
        if len(raw) <= self._SIG_LEN:
            raise QueryToolsError(
                "invalid or expired page token",
                reason_code="query_tools.invalid_page_token",
            )
        payload, sig = raw[: -self._SIG_LEN], raw[-self._SIG_LEN :]
        expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            raise QueryToolsError(
                "invalid or expired page token",
                reason_code="query_tools.invalid_page_token",
            )
        try:
            hid, offset_s = payload.decode("utf-8").split(":", 1)
            offset = int(offset_s)
        except (ValueError, UnicodeDecodeError) as exc:
            raise QueryToolsError(
                "invalid or expired page token",
                reason_code="query_tools.invalid_page_token",
            ) from exc
        if hid != handle_id or offset < 0:
            raise QueryToolsError(
                "invalid or expired page token",
                reason_code="query_tools.invalid_page_token",
            )
        return offset


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------


class DuckDBQueryGateway:
    """In-process gateway binding MCP/CLI callers to the query registry.

    All execution paths resolve templates by id through :class:`QueryRegistry`
    / :class:`QueryExecutor`. Arbitrary SQL is denied at every entry point.
    """

    def __init__(
        self,
        registry: qr.QueryRegistry | None = None,
        *,
        backend: Any | None = None,
        executor: qr.QueryExecutor | None = None,
        exporter: SnapshotExporter | None = None,
        clock: Callable[[], str] | None = None,
        page_token_secret: bytes | None = None,
        max_handles: int = MAX_HANDLES,
    ) -> None:
        if registry is None:
            registry = qr.open_default_registry(include_builtins=True)
        if not isinstance(registry, qr.QueryRegistry):
            raise QueryToolsError(
                "registry must be a QueryRegistry",
                reason_code="query.registry_error",
            )
        self._registry = registry
        self._executor = executor or qr.QueryExecutor(
            registry,
            backend=backend,
            audit_log=qr.AuditLog(),
            clock=clock or _utc_now,
        )
        self._exporter = exporter or SnapshotExporter()
        self._clock = clock or _utc_now
        self._tokens = _PageTokenCodec(page_token_secret)
        self._handles: MutableMapping[str, QueryHandle] = {}
        self._lock = threading.RLock()
        self._max_handles = max(1, int(max_handles))

    @property
    def registry(self) -> qr.QueryRegistry:
        return self._registry

    @property
    def executor(self) -> qr.QueryExecutor:
        return self._executor

    # -- handle bookkeeping -------------------------------------------------

    def _store_handle(self, handle: QueryHandle) -> None:
        with self._lock:
            if len(self._handles) >= self._max_handles:
                # Evict oldest terminal handles first.
                terminal = [
                    (h.handle_id, h.updated_at)
                    for h in self._handles.values()
                    if h.is_terminal
                ]
                terminal.sort(key=lambda item: item[1])
                for hid, _ in terminal[: max(1, len(terminal) // 4 or 1)]:
                    self._handles.pop(hid, None)
                if len(self._handles) >= self._max_handles:
                    raise QueryToolsError(
                        "query handle capacity exceeded",
                        reason_code="query.budget_exceeded",
                    )
            self._handles[handle.handle_id] = handle

    def get_handle(self, handle_id: str) -> QueryHandle:
        hid = str(handle_id or "").strip()
        if not hid:
            raise QueryToolsError(
                "handle_id is required",
                reason_code="query_tools.missing_handle",
            )
        with self._lock:
            handle = self._handles.get(hid)
        if handle is None:
            raise QueryToolsError(
                "unknown query handle",
                reason_code="query_tools.unknown_handle",
            )
        return handle

    # -- list / explain -----------------------------------------------------

    def list_templates(
        self,
        *,
        trust: TrustLike = qr.TrustClass.UNTRUSTED,
        require_duckdb_version: str | None = None,
        capability_pins: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        caps = _capability_binding(
            require_duckdb_version=require_duckdb_version,
            capability_pins=capability_pins,
        )
        trust_cls = _parse_trust(trust)
        templates: list[dict[str, Any]] = []
        for tid in self._registry.list_templates():
            template = self._registry.get(tid)
            if not template.permits_trust(trust_cls):
                continue
            templates.append(
                {
                    "template_id": template.template_id,
                    "version": template.version,
                    "description": template.description,
                    "domains": list(template.domains),
                    "allowed_trust": sorted(t.value for t in template.allowed_trust),
                    "parameter_schema": template.parameter_schema.to_dict(),
                    "budget": template.budget.to_dict(),
                    "identity_id": template.identity_id,
                    # SQL intentionally omitted from public list surface.
                }
            )
        return {
            "status": "ok",
            "schema": QUERY_TOOLS_SCHEMA,
            "operation": "list_templates",
            "templates": templates,
            "count": len(templates),
            "capabilities": caps,
            "implementation_generation": QUERY_TOOLS_IMPLEMENTATION_GENERATION,
        }

    def explain(
        self,
        template_id: str | None,
        params: Mapping[str, Any] | None = None,
        *,
        snapshot_id: SnapshotId | str | Mapping[str, Any] | None = None,
        tenant_id: str | None = None,
        trust: TrustLike = qr.TrustClass.UNTRUSTED,
        require_duckdb_version: str | None = None,
        capability_pins: Mapping[str, Any] | None = None,
        store_generation: int | None = None,
        sql: str | None = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        """Prepare an allowlisted template and return a non-SQL plan summary."""

        caps = _capability_binding(
            require_duckdb_version=require_duckdb_version,
            capability_pins=capability_pins,
        )
        if not template_id or not str(template_id).strip():
            raise QueryToolsError(
                "template_id is required",
                reason_code="query_tools.missing_template_id",
            )
        # Hard deny any raw-SQL path on explain.
        try:
            qr.deny_arbitrary_sql(sql, template_id=template_id)
        except qr.QueryRegistryError as exc:
            raise QueryToolsError(
                "arbitrary SQL and denied surfaces are forbidden",
                reason_code=getattr(exc, "reason_code", "query.sql_surface_denied"),
            ) from exc
        if not tenant_id or not str(tenant_id).strip():
            raise QueryToolsError(
                "tenant_id is required",
                reason_code="query_tools.missing_tenant",
            )
        snap = _parse_snapshot(snapshot_id, store_generation=store_generation)
        trust_cls = _parse_trust(trust)
        tenant_policy = qr.TenantPolicy(tenant_id=str(tenant_id).strip())

        try:
            prepared = self._registry.prepare(
                str(template_id).strip(),
                params,
                trust=trust_cls,
                tenant_policy=tenant_policy,
                snapshot=snap,
            )
        except qr.QueryRegistryError as exc:
            raise QueryToolsError(
                sanitize_public_error(exc)["error"],
                reason_code=getattr(
                    exc, "reason_code", "query.registry_error"
                ),
            ) from exc
        budget = self._registry.effective_budget(prepared.template, prepared.trust)

        return {
            "status": "ok",
            "schema": QUERY_TOOLS_SCHEMA,
            "operation": "explain",
            "template_id": prepared.template.template_id,
            "template_version": prepared.template.version,
            "template_identity": prepared.template.identity_id,
            "description": prepared.template.description,
            "domains": list(prepared.template.domains),
            "parameters_digest": prepared.parameters_digest,
            "parameter_schema": prepared.template.parameter_schema.to_dict(),
            "column_policy": prepared.template.column_policy.to_dict(),
            "budget": budget.to_dict(),
            "trust": prepared.trust.value,
            "tenant_policy": prepared.tenant_policy.to_dict(),
            "snapshot": prepared.snapshot.to_dict(),
            "bind_value_count": len(prepared.bind_values),
            # Never return template SQL or bind values (may hold secrets).
            "sql_redacted": redact_sql(prepared.template.sql),
            "capabilities": caps,
            "implementation_generation": QUERY_TOOLS_IMPLEMENTATION_GENERATION,
        }

    # -- query / page / cancel / status -------------------------------------

    def query(
        self,
        template_id: str | None,
        params: Mapping[str, Any] | None = None,
        *,
        snapshot_id: SnapshotId | str | Mapping[str, Any] | None = None,
        tenant_id: str | None = None,
        trust: TrustLike = qr.TrustClass.UNTRUSTED,
        page_size: int | None = None,
        require_duckdb_version: str | None = None,
        capability_pins: Mapping[str, Any] | None = None,
        store_generation: int | None = None,
        sql: str | None = None,
        cancellation: qr.CancellationToken | None = None,
        row_source: Callable[..., Sequence[Mapping[str, Any]]] | None = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        """Execute an allowlisted template and return the first page of rows."""

        caps = _capability_binding(
            require_duckdb_version=require_duckdb_version,
            capability_pins=capability_pins,
        )
        if not template_id or not str(template_id).strip():
            raise QueryToolsError(
                "template_id is required",
                reason_code="query_tools.missing_template_id",
            )
        try:
            qr.deny_arbitrary_sql(sql, template_id=template_id)
        except qr.QueryRegistryError as exc:
            raise QueryToolsError(
                "arbitrary SQL and denied surfaces are forbidden",
                reason_code=getattr(exc, "reason_code", "query.sql_surface_denied"),
            ) from exc
        if not tenant_id or not str(tenant_id).strip():
            raise QueryToolsError(
                "tenant_id is required",
                reason_code="query_tools.missing_tenant",
            )
        snap = _parse_snapshot(snapshot_id, store_generation=store_generation)
        trust_cls = _parse_trust(trust)
        tenant = str(tenant_id).strip()
        tenant_policy = qr.TenantPolicy(tenant_id=tenant)
        page_sz = _clamp_page_size(page_size)
        now = self._clock()
        handle_id = _new_handle_id()
        cancel = cancellation or qr.CancellationToken()

        handle = QueryHandle(
            handle_id=handle_id,
            template_id=str(template_id).strip(),
            snapshot=snap,
            tenant_id=tenant,
            trust=trust_cls,
            status=HandleStatus.RUNNING,
            created_at=now,
            cancellation=cancel,
            page_size=page_sz,
            operation="query",
        )
        self._store_handle(handle)

        try:
            result = self._executor.execute(
                handle.template_id,
                params,
                trust=trust_cls,
                tenant_policy=tenant_policy,
                snapshot=snap,
                cancellation=cancel,
                row_source=row_source,
            )
        except qr.QueryCancelled as exc:
            handle.status = HandleStatus.CANCELLED
            handle.error = sanitize_public_error(exc)
            handle.updated_at = self._clock()
            return self._query_response(handle, caps, offset=0)
        except qr.QueryRegistryError as exc:
            handle.status = (
                HandleStatus.DENIED
                if isinstance(
                    exc,
                    (
                        qr.SQLSurfaceDenied,
                        qr.UnknownTemplateError,
                        qr.TenantPolicyViolation,
                        qr.ParameterValidationError,
                        qr.ColumnPolicyError,
                    ),
                )
                else HandleStatus.FAILED
            )
            handle.error = sanitize_public_error(exc)
            handle.updated_at = self._clock()
            # Re-raise as QueryToolsError with stable code for MCP wrappers.
            raise QueryToolsError(
                handle.error["error"],
                reason_code=handle.error["reason_code"],
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive
            handle.status = HandleStatus.FAILED
            handle.error = sanitize_public_error(exc)
            handle.updated_at = self._clock()
            raise QueryToolsError(
                handle.error["error"],
                reason_code=handle.error["reason_code"],
            ) from exc

        handle.rows = tuple(dict(r) for r in result.rows)
        handle.receipt = result.receipt
        handle.parameters_digest = result.receipt.parameters_digest
        handle.updated_at = self._clock()
        if result.receipt.status is qr.QueryStatus.CANCELLED:
            handle.status = HandleStatus.CANCELLED
        elif result.receipt.status is qr.QueryStatus.BUDGET_EXCEEDED:
            handle.status = HandleStatus.BUDGET_EXCEEDED
        elif result.receipt.truncated or result.receipt.status is qr.QueryStatus.TRUNCATED:
            handle.status = HandleStatus.TRUNCATED
        else:
            handle.status = HandleStatus.SUCCEEDED

        return self._query_response(handle, caps, offset=0)

    def _query_response(
        self,
        handle: QueryHandle,
        capabilities: Mapping[str, Any],
        *,
        offset: int,
    ) -> dict[str, Any]:
        total = len(handle.rows)
        page_sz = handle.page_size
        if offset > total:
            raise QueryToolsError(
                "page offset out of range",
                reason_code="query_tools.page_out_of_range",
            )
        end = min(total, offset + page_sz)
        page_rows = [dict(r) for r in handle.rows[offset:end]]
        next_offset = end if end < total else None
        next_token = (
            self._tokens.mint(handle.handle_id, next_offset)
            if next_offset is not None
            else None
        )
        body: dict[str, Any] = {
            "status": "ok" if handle.error is None else "error",
            "schema": QUERY_TOOLS_SCHEMA,
            "operation": "query" if offset == 0 else "page",
            "handle_id": handle.handle_id,
            "handle_status": handle.status.value,
            "template_id": handle.template_id,
            "snapshot": handle.snapshot.to_dict(),
            "tenant_id": handle.tenant_id,
            "trust": handle.trust.value,
            "rows": page_rows,
            "row_count": len(page_rows),
            "total_row_count": total,
            "offset": offset,
            "page_size": page_sz,
            "has_more": next_token is not None,
            "next_page_token": next_token,
            "parameters_digest": handle.parameters_digest,
            "capabilities": dict(capabilities),
            "implementation_generation": QUERY_TOOLS_IMPLEMENTATION_GENERATION,
        }
        if handle.receipt is not None:
            body["receipt"] = _public_receipt(handle.receipt)
        if handle.error is not None:
            body["error"] = handle.error
            body["reason_code"] = handle.error.get("reason_code")
        return body

    def page(
        self,
        handle_id: str | None,
        page_token: str | None,
        *,
        require_duckdb_version: str | None = None,
        capability_pins: Mapping[str, Any] | None = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        caps = _capability_binding(
            require_duckdb_version=require_duckdb_version,
            capability_pins=capability_pins,
        )
        if not handle_id:
            raise QueryToolsError(
                "handle_id is required",
                reason_code="query_tools.missing_handle",
            )
        handle = self.get_handle(str(handle_id).strip())
        if handle.operation not in {"query", "export"} and not handle.rows:
            # Export handles may not be pageable.
            if not handle.rows:
                raise QueryToolsError(
                    "handle has no pageable result set",
                    reason_code="query_tools.handle_not_pageable",
                )
        if handle.status is HandleStatus.CANCELLED and not handle.rows:
            return self._query_response(handle, caps, offset=0)
        offset = self._tokens.parse(handle.handle_id, str(page_token or ""))
        if offset > len(handle.rows):
            raise QueryToolsError(
                "page offset out of range",
                reason_code="query_tools.page_out_of_range",
            )
        return self._query_response(handle, caps, offset=offset)

    def status(
        self,
        handle_id: str | None,
        *,
        require_duckdb_version: str | None = None,
        capability_pins: Mapping[str, Any] | None = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        caps = _capability_binding(
            require_duckdb_version=require_duckdb_version,
            capability_pins=capability_pins,
        )
        if not handle_id:
            raise QueryToolsError(
                "handle_id is required",
                reason_code="query_tools.missing_handle",
            )
        handle = self.get_handle(str(handle_id).strip())
        body = handle.public_status()
        body.update(
            {
                "status": "ok",
                "schema": QUERY_TOOLS_SCHEMA,
                "operation": "status",
                "capabilities": caps,
                "implementation_generation": QUERY_TOOLS_IMPLEMENTATION_GENERATION,
            }
        )
        return body

    def cancel(
        self,
        handle_id: str | None,
        *,
        reason: str = "cancelled",
        require_duckdb_version: str | None = None,
        capability_pins: Mapping[str, Any] | None = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        caps = _capability_binding(
            require_duckdb_version=require_duckdb_version,
            capability_pins=capability_pins,
        )
        if not handle_id:
            raise QueryToolsError(
                "handle_id is required",
                reason_code="query_tools.missing_handle",
            )
        handle = self.get_handle(str(handle_id).strip())
        safe_reason = str(reason or "cancelled").strip() or "cancelled"
        if not _SAFE_REASON.fullmatch(safe_reason):
            safe_reason = "cancelled"
        already = handle.cancellation.is_cancelled or handle.is_terminal
        if not handle.cancellation.is_cancelled:
            handle.cancellation.cancel(safe_reason)
        if handle.status in {HandleStatus.PENDING, HandleStatus.RUNNING}:
            handle.status = HandleStatus.CANCELLED
        handle.updated_at = self._clock()
        return {
            "status": "ok",
            "schema": QUERY_TOOLS_SCHEMA,
            "operation": "cancel",
            "handle_id": handle.handle_id,
            "handle_status": handle.status.value,
            "cancelled": True,
            "idempotent_replay": already,
            "reason": safe_reason if handle.cancellation.is_cancelled else "cancelled",
            "capabilities": caps,
            "implementation_generation": QUERY_TOOLS_IMPLEMENTATION_GENERATION,
        }

    # -- export -------------------------------------------------------------

    def export(
        self,
        template_id: str | None,
        params: Mapping[str, Any] | None = None,
        *,
        snapshot_id: SnapshotId | str | Mapping[str, Any] | None = None,
        tenant_id: str | None = None,
        trust: TrustLike = qr.TrustClass.UNTRUSTED,
        format: ExportFormat | str = ExportFormat.JSON,
        location_hint: str = "exports/query/",
        require_duckdb_version: str | None = None,
        capability_pins: Mapping[str, Any] | None = None,
        store_generation: int | None = None,
        sql: str | None = None,
        row_source: Callable[..., Sequence[Mapping[str, Any]]] | None = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        """Run an allowlisted query and render a non-authoritative export."""

        caps = _capability_binding(
            require_duckdb_version=require_duckdb_version,
            capability_pins=capability_pins,
        )
        if not template_id or not str(template_id).strip():
            raise QueryToolsError(
                "template_id is required",
                reason_code="query_tools.missing_template_id",
            )
        try:
            qr.deny_arbitrary_sql(sql, template_id=template_id)
        except qr.QueryRegistryError as exc:
            raise QueryToolsError(
                "arbitrary SQL and denied surfaces are forbidden",
                reason_code=getattr(exc, "reason_code", "query.sql_surface_denied"),
            ) from exc
        if not tenant_id or not str(tenant_id).strip():
            raise QueryToolsError(
                "tenant_id is required",
                reason_code="query_tools.missing_tenant",
            )
        snap = _parse_snapshot(snapshot_id, store_generation=store_generation)
        trust_cls = _parse_trust(trust)
        tenant = str(tenant_id).strip()
        tenant_policy = qr.TenantPolicy(tenant_id=tenant)
        fmt = ExportFormat.parse(format)
        now = self._clock()
        handle_id = _new_handle_id()
        cancel = qr.CancellationToken()

        handle = QueryHandle(
            handle_id=handle_id,
            template_id=str(template_id).strip(),
            snapshot=snap,
            tenant_id=tenant,
            trust=trust_cls,
            status=HandleStatus.RUNNING,
            created_at=now,
            cancellation=cancel,
            page_size=DEFAULT_PAGE_SIZE,
            operation="export",
        )
        self._store_handle(handle)

        try:
            result = self._executor.execute(
                handle.template_id,
                params,
                trust=trust_cls,
                tenant_policy=tenant_policy,
                snapshot=snap,
                cancellation=cancel,
                row_source=row_source,
            )
            handle.rows = tuple(dict(r) for r in result.rows)
            handle.receipt = result.receipt
            handle.parameters_digest = result.receipt.parameters_digest

            job = ExportJob(
                job_id=f"export-{uuid.uuid4().hex[:16]}",
                template_id=handle.template_id,
                parameters_digest=result.receipt.parameters_digest,
                schema_version="1",
                snapshot=snap,
                format=fmt,
                destination_policy=default_destination_policy(),
                revision="1",
                template_version=result.receipt.template_version,
                location_hint=location_hint or "exports/query/",
                column_policy=self._registry.get(
                    handle.template_id
                ).column_policy,
                created_at=now,
            )
            export_result = self._exporter.export_rows(
                list(handle.rows),
                job,
            )
            # Public summary: digests/CIDs only — never payload or SQL.
            handle.export_summary = {
                "job_id": export_result.job.job_id,
                "template_id": export_result.template_id,
                "parameters_digest": export_result.parameters_digest,
                "content_digest": export_result.content_digest,
                "root_cid": export_result.root_cid,
                "format": export_result.artifact.format.value,
                "media_type": export_result.artifact.media_type.value,
                "row_count": export_result.artifact.row_count,
                "byte_size": export_result.artifact.byte_size,
                "projected_columns": list(
                    export_result.artifact.projected_columns
                ),
                "status": export_result.status.value,
                "read_only": True,
                "non_authoritative": True,
                "mutated_source": False,
                "snapshot": snap.to_dict(),
                "export_id": getattr(
                    export_result.receipt, "export_id", ""
                )
                or export_result.receipt.to_dict().get("export_id", ""),
            }
            handle.status = HandleStatus.SUCCEEDED
            handle.updated_at = self._clock()
        except qr.QueryRegistryError as exc:
            handle.status = HandleStatus.DENIED
            handle.error = sanitize_public_error(exc)
            handle.updated_at = self._clock()
            raise QueryToolsError(
                handle.error["error"],
                reason_code=handle.error["reason_code"],
            ) from exc
        except Exception as exc:
            handle.status = HandleStatus.FAILED
            handle.error = sanitize_public_error(
                exc, reason_code="query_tools.export_failed"
            )
            handle.updated_at = self._clock()
            raise QueryToolsError(
                handle.error["error"],
                reason_code="query_tools.export_failed",
            ) from exc

        return {
            "status": "ok",
            "schema": QUERY_TOOLS_SCHEMA,
            "operation": "export",
            "handle_id": handle.handle_id,
            "handle_status": handle.status.value,
            "template_id": handle.template_id,
            "snapshot": snap.to_dict(),
            "tenant_id": tenant,
            "trust": trust_cls.value,
            "export": handle.export_summary,
            "receipt": _public_receipt(handle.receipt)
            if handle.receipt is not None
            else None,
            "capabilities": caps,
            "implementation_generation": QUERY_TOOLS_IMPLEMENTATION_GENERATION,
        }


def open_default_gateway(
    *,
    include_builtins: bool = True,
    backend: Any | None = None,
    page_token_secret: bytes | None = None,
) -> DuckDBQueryGateway:
    """Create a gateway with the default allowlisted registry."""

    registry = qr.open_default_registry(include_builtins=include_builtins)
    return DuckDBQueryGateway(
        registry,
        backend=backend,
        page_token_secret=page_token_secret,
    )


# ---------------------------------------------------------------------------
# Process-local default gateway (tests inject via set_default_gateway)
# ---------------------------------------------------------------------------

_DEFAULT_GATEWAY: DuckDBQueryGateway | None = None
_DEFAULT_GATEWAY_LOCK = threading.Lock()


def get_default_gateway() -> DuckDBQueryGateway:
    global _DEFAULT_GATEWAY
    with _DEFAULT_GATEWAY_LOCK:
        if _DEFAULT_GATEWAY is None:
            _DEFAULT_GATEWAY = open_default_gateway(include_builtins=True)
        return _DEFAULT_GATEWAY


def set_default_gateway(gateway: DuckDBQueryGateway | None) -> None:
    global _DEFAULT_GATEWAY
    with _DEFAULT_GATEWAY_LOCK:
        _DEFAULT_GATEWAY = gateway


# ---------------------------------------------------------------------------
# MCP tool entrypoints (sync; async-compatible via anyio if needed)
# ---------------------------------------------------------------------------


def _ok_or_error(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return fn()
    except QueryToolsError as exc:
        return sanitize_public_error(exc)
    except qr.QueryRegistryError as exc:
        return sanitize_public_error(exc)
    except Exception as exc:  # pragma: no cover - defensive
        return sanitize_public_error(exc)


def duckdb_query(
    template_id: str | None = None,
    parameters: Mapping[str, Any] | None = None,
    *,
    params: Mapping[str, Any] | None = None,
    snapshot_id: SnapshotId | str | Mapping[str, Any] | None = None,
    tenant_id: str | None = None,
    trust: str = "untrusted",
    page_size: int | None = None,
    require_duckdb_version: str | None = None,
    sql: str | None = None,
    gateway: DuckDBQueryGateway | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """MCP tool: execute an allowlisted query template (no raw SQL)."""

    gw = gateway or get_default_gateway()
    bound = params if params is not None else parameters

    def _run() -> dict[str, Any]:
        return gw.query(
            template_id,
            bound,
            snapshot_id=snapshot_id,
            tenant_id=tenant_id,
            trust=trust,
            page_size=page_size,
            require_duckdb_version=require_duckdb_version,
            sql=sql,
            **kwargs,
        )

    return _ok_or_error(_run)


def duckdb_explain(
    template_id: str | None = None,
    parameters: Mapping[str, Any] | None = None,
    *,
    params: Mapping[str, Any] | None = None,
    snapshot_id: SnapshotId | str | Mapping[str, Any] | None = None,
    tenant_id: str | None = None,
    trust: str = "untrusted",
    require_duckdb_version: str | None = None,
    sql: str | None = None,
    gateway: DuckDBQueryGateway | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """MCP tool: explain an allowlisted template without exposing SQL."""

    gw = gateway or get_default_gateway()
    bound = params if params is not None else parameters

    def _run() -> dict[str, Any]:
        return gw.explain(
            template_id,
            bound,
            snapshot_id=snapshot_id,
            tenant_id=tenant_id,
            trust=trust,
            require_duckdb_version=require_duckdb_version,
            sql=sql,
            **kwargs,
        )

    return _ok_or_error(_run)


def duckdb_export(
    template_id: str | None = None,
    parameters: Mapping[str, Any] | None = None,
    *,
    params: Mapping[str, Any] | None = None,
    snapshot_id: SnapshotId | str | Mapping[str, Any] | None = None,
    tenant_id: str | None = None,
    trust: str = "untrusted",
    format: str = "json",
    location_hint: str = "exports/query/",
    require_duckdb_version: str | None = None,
    sql: str | None = None,
    gateway: DuckDBQueryGateway | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """MCP tool: export allowlisted query results as a non-authoritative artifact."""

    gw = gateway or get_default_gateway()
    bound = params if params is not None else parameters

    def _run() -> dict[str, Any]:
        return gw.export(
            template_id,
            bound,
            snapshot_id=snapshot_id,
            tenant_id=tenant_id,
            trust=trust,
            format=format,
            location_hint=location_hint,
            require_duckdb_version=require_duckdb_version,
            sql=sql,
            **kwargs,
        )

    return _ok_or_error(_run)


def duckdb_query_status(
    handle_id: str | None = None,
    *,
    gateway: DuckDBQueryGateway | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """MCP tool: status of a query/export handle."""

    gw = gateway or get_default_gateway()

    def _run() -> dict[str, Any]:
        return gw.status(handle_id, **kwargs)

    return _ok_or_error(_run)


def duckdb_query_cancel(
    handle_id: str | None = None,
    *,
    reason: str = "cancelled",
    gateway: DuckDBQueryGateway | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """MCP tool: cancel a query handle (idempotent)."""

    gw = gateway or get_default_gateway()

    def _run() -> dict[str, Any]:
        return gw.cancel(handle_id, reason=reason, **kwargs)

    return _ok_or_error(_run)


def duckdb_query_page(
    handle_id: str | None = None,
    page_token: str | None = None,
    *,
    gateway: DuckDBQueryGateway | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """MCP tool: fetch the next bounded page for a query handle."""

    gw = gateway or get_default_gateway()

    def _run() -> dict[str, Any]:
        return gw.page(handle_id, page_token, **kwargs)

    return _ok_or_error(_run)


def duckdb_list_templates(
    *,
    trust: str = "untrusted",
    gateway: DuckDBQueryGateway | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """MCP tool: list allowlisted templates visible to the caller trust class."""

    gw = gateway or get_default_gateway()

    def _run() -> dict[str, Any]:
        return gw.list_templates(trust=trust, **kwargs)

    return _ok_or_error(_run)


# ---------------------------------------------------------------------------
# DQK-093 DuckLake MCP tools (template registry + DQK-104 catalog gateway)
# ---------------------------------------------------------------------------


def _load_ducklake_api():
    """Lazy import to keep control-plane tool import free of lake deps when unused."""

    from ipfs_datasets_py.ducklake import api as lake_api

    return lake_api


_DEFAULT_DUCKLAKE_API: Any = None
_DEFAULT_DUCKLAKE_API_LOCK = threading.Lock()


def get_default_ducklake_api() -> Any:
    """Return the process-local DuckLake query API (created on first use)."""

    global _DEFAULT_DUCKLAKE_API
    with _DEFAULT_DUCKLAKE_API_LOCK:
        if _DEFAULT_DUCKLAKE_API is None:
            lake_api = _load_ducklake_api()
            _DEFAULT_DUCKLAKE_API = lake_api.open_default_api()
        return _DEFAULT_DUCKLAKE_API


def set_default_ducklake_api(api: Any | None) -> None:
    """Inject or clear the process-local DuckLake query API (tests)."""

    global _DEFAULT_DUCKLAKE_API
    with _DEFAULT_DUCKLAKE_API_LOCK:
        _DEFAULT_DUCKLAKE_API = api


def _ducklake_ok_or_error(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    lake_api = _load_ducklake_api()
    try:
        return fn()
    except lake_api.DuckLakeAPIError as exc:
        return lake_api.sanitize_public_error(exc)
    except qr.QueryRegistryError as exc:
        return lake_api.sanitize_public_error(exc)
    except QueryToolsError as exc:
        return sanitize_public_error(exc)
    except Exception as exc:  # pragma: no cover - defensive
        return lake_api.sanitize_public_error(exc)


def ducklake_discover_catalogs(
    *,
    tenant_id: str | None = None,
    trust: str = "untrusted",
    max_rows: int | None = None,
    sql: str | None = None,
    api: Any | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """MCP tool: discover sanitized DuckLake catalogs (no credentials/tokens)."""

    gateway = api or get_default_ducklake_api()

    def _run() -> dict[str, Any]:
        return gateway.discover_catalogs(
            tenant_id=tenant_id,
            trust=trust,
            max_rows=max_rows,
            sql=sql,
            **kwargs,
        )

    return _ducklake_ok_or_error(_run)


def ducklake_discover_datasets(
    *,
    catalog_id: str | None = None,
    tenant_id: str | None = None,
    namespace: str = "main",
    schema_name: str = "main",
    trust: str = "untrusted",
    max_rows: int | None = None,
    sql: str | None = None,
    api: Any | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """MCP tool: discover datasets via DQK-104 templates or publication plane."""

    gateway = api or get_default_ducklake_api()

    def _run() -> dict[str, Any]:
        return gateway.discover_datasets(
            catalog_id=catalog_id,
            tenant_id=tenant_id,
            namespace=namespace,
            schema_name=schema_name,
            trust=trust,
            max_rows=max_rows,
            sql=sql,
            **kwargs,
        )

    return _ducklake_ok_or_error(_run)


def ducklake_select_snapshot(
    *,
    catalog_id: str | None = None,
    snapshot_version: int | None = None,
    tenant_id: str | None = None,
    trust: str = "untrusted",
    time_travel: bool = False,
    logical_query_id: str | None = None,
    sql: str | None = None,
    api: Any | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """MCP tool: select a bounded snapshot / time-travel target."""

    gateway = api or get_default_ducklake_api()

    def _run() -> dict[str, Any]:
        return gateway.select_snapshot(
            catalog_id=catalog_id,
            snapshot_version=snapshot_version,
            tenant_id=tenant_id,
            trust=trust,
            time_travel=time_travel,
            logical_query_id=logical_query_id,
            sql=sql,
            **kwargs,
        )

    return _ducklake_ok_or_error(_run)


def ducklake_list_templates(
    *,
    trust: str = "untrusted",
    include_catalog_templates: bool = True,
    api: Any | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """MCP tool: list allowlisted DuckLake query + catalog templates."""

    gateway = api or get_default_ducklake_api()

    def _run() -> dict[str, Any]:
        return gateway.list_templates(
            trust=trust,
            include_catalog_templates=include_catalog_templates,
            **kwargs,
        )

    return _ducklake_ok_or_error(_run)


def ducklake_explain(
    template_id: str | None = None,
    parameters: Mapping[str, Any] | None = None,
    *,
    params: Mapping[str, Any] | None = None,
    snapshot_id: SnapshotId | str | Mapping[str, Any] | None = None,
    tenant_id: str | None = None,
    trust: str = "untrusted",
    sql: str | None = None,
    api: Any | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """MCP tool: explain a DuckLake template without exposing SQL."""

    gateway = api or get_default_ducklake_api()
    bound = params if params is not None else parameters

    def _run() -> dict[str, Any]:
        return gateway.explain(
            template_id,
            bound,
            snapshot_id=snapshot_id,
            tenant_id=tenant_id,
            trust=trust,
            sql=sql,
            **kwargs,
        )

    return _ducklake_ok_or_error(_run)


def ducklake_query(
    template_id: str | None = None,
    parameters: Mapping[str, Any] | None = None,
    *,
    params: Mapping[str, Any] | None = None,
    snapshot_id: SnapshotId | str | Mapping[str, Any] | None = None,
    tenant_id: str | None = None,
    trust: str = "untrusted",
    page_size: int | None = None,
    catalog_id: str | None = None,
    sql: str | None = None,
    api: Any | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """MCP tool: bounded DuckLake aggregate/query via allowlisted templates."""

    gateway = api or get_default_ducklake_api()
    bound = params if params is not None else parameters

    def _run() -> dict[str, Any]:
        return gateway.query(
            template_id,
            bound,
            snapshot_id=snapshot_id,
            tenant_id=tenant_id,
            trust=trust,
            page_size=page_size,
            catalog_id=catalog_id,
            sql=sql,
            **kwargs,
        )

    return _ducklake_ok_or_error(_run)


def ducklake_export(
    template_id: str | None = None,
    parameters: Mapping[str, Any] | None = None,
    *,
    params: Mapping[str, Any] | None = None,
    snapshot_id: SnapshotId | str | Mapping[str, Any] | None = None,
    tenant_id: str | None = None,
    trust: str = "untrusted",
    format: str = "json",
    location_hint: str = "exports/ducklake/",
    catalog_id: str | None = None,
    sql: str | None = None,
    api: Any | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """MCP tool: deterministic DuckLake export (digests only; no payload/SQL)."""

    gateway = api or get_default_ducklake_api()
    bound = params if params is not None else parameters

    def _run() -> dict[str, Any]:
        return gateway.export(
            template_id,
            bound,
            snapshot_id=snapshot_id,
            tenant_id=tenant_id,
            trust=trust,
            format=format,
            location_hint=location_hint,
            catalog_id=catalog_id,
            sql=sql,
            **kwargs,
        )

    return _ducklake_ok_or_error(_run)


def ducklake_query_status(
    handle_id: str | None = None,
    *,
    api: Any | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """MCP tool: status of a DuckLake query/export handle."""

    gateway = api or get_default_ducklake_api()

    def _run() -> dict[str, Any]:
        return gateway.status(handle_id, **kwargs)

    return _ducklake_ok_or_error(_run)


def ducklake_query_cancel(
    handle_id: str | None = None,
    *,
    reason: str = "cancelled",
    api: Any | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """MCP tool: cancel a DuckLake query handle (idempotent)."""

    gateway = api or get_default_ducklake_api()

    def _run() -> dict[str, Any]:
        return gateway.cancel(handle_id, reason=reason, **kwargs)

    return _ducklake_ok_or_error(_run)


def ducklake_query_page(
    handle_id: str | None = None,
    page_token: str | None = None,
    *,
    api: Any | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """MCP tool: fetch the next bounded page for a DuckLake query handle."""

    gateway = api or get_default_ducklake_api()

    def _run() -> dict[str, Any]:
        return gateway.page(handle_id, page_token, **kwargs)

    return _ducklake_ok_or_error(_run)
