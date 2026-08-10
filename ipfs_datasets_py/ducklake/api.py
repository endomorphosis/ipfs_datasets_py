"""Allowlisted DuckLake query and export Python API (DQK-093).

Exposes typed, parameterized operations for:

* catalog / dataset discovery
* snapshot selection and time-travel replay selection
* explain (no raw SQL surface)
* bounded aggregate query
* cancellation
* deterministic export

Security invariants
-------------------
* Every operation is an allowlisted parameterized template.
* Catalog-management calls use the DQK-104 DuckDB + Quack catalog-management
  gateway (signed templates + trusted broker). Query/export calls use bounded
  snapshot-bound workers (DQK-092) or the sanitized publication plane (DQK-058).
* Pagination, cancellation, snapshot/time-travel selection, and export digests
  are bounded and reproducible.
* Secrets, encryption keys, raw catalog strings, Quack tokens, and unrestricted
  object URIs are redacted from every public response.
* Untrusted remote access remains a typed broker or sanitized publication
  operation rather than direct authority-catalog Quack access.
* Callers never receive catalog credentials, Quack tokens, arbitrary ATTACH,
  or unrestricted SQL.

Importing this module is inert: no DuckDB, network, socket, or filesystem I/O.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    Callable,
    Final,
    Mapping,
    MutableMapping,
    Sequence,
)

from ipfs_datasets_py.duckdb_control.contracts import (
    SnapshotId,
    content_identity,
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
    redact_token,
)
from ipfs_datasets_py.ducklake import quack_catalog as qc
from ipfs_datasets_py.ducklake.catalog_service import (
    CatalogServiceManager,
    CatalogOwnerService,
    TrustedCatalogBroker,
)

__all__ = [
    "DUCKLAKE_API_SCHEMA",
    "DUCKLAKE_API_IMPLEMENTATION_GENERATION",
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "MAX_DISCOVERY_ROWS",
    "MAX_EXPORT_ROWS",
    "MAX_HANDLES",
    "AccessPlane",
    "HandleStatus",
    "DuckLakeAPIError",
    "CatalogProjection",
    "DatasetProjection",
    "SnapshotSelection",
    "QueryHandle",
    "DuckLakeQueryAPI",
    "open_default_api",
    "default_ducklake_query_templates",
    "sanitize_public_error",
    "redact_public_payload",
    # Convenience entrypoints (mirror MCP surface)
    "discover_catalogs",
    "discover_datasets",
    "select_snapshot",
    "list_templates",
    "explain",
    "query",
    "page",
    "status",
    "cancel",
    "export",
]


# ---------------------------------------------------------------------------
# Schema / bounds
# ---------------------------------------------------------------------------

DUCKLAKE_API_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-query-api@1"
DUCKLAKE_API_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-093-ducklake-query-export-api-20260810"
)

DEFAULT_PAGE_SIZE: Final[int] = 100
MAX_PAGE_SIZE: Final[int] = 500
MAX_DISCOVERY_ROWS: Final[int] = 1_000
MAX_EXPORT_ROWS: Final[int] = 10_000
MAX_HANDLES: Final[int] = 10_000
MAX_ERROR_DETAIL_BYTES: Final[int] = 512

_SAFE_REASON = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+ -]{0,127}$")
_SAFE_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_SECRET_KEY_NAMES: Final[frozenset[str]] = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "bearer",
        "private_key",
        "encryption_key",
        "signing_key",
        "quack_token",
        "quack_capability",
        "credential",
        "mnemonic",
        "seed",
        "canonical_sql",
        "raw_sql",
        "sql",
        "attach",
        "catalog_path",
        "catalog_metadata_path",
        "object_uri",
        "s3_uri",
        "endpoint_secret",
        "signing_secret",
    }
)

_SECRET_LEAK_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|"
        r"authorization|bearer|private[_-]?key|mnemonic|seed|"
        r"encryption[_-]?key|signing[_-]?key|quack[_-]?token)\b"
    ),
    re.compile(
        r"(?i)\b(SELECT|INSERT|UPDATE|DELETE|DROP|ATTACH|COPY|"
        r"INSTALL|LOAD|PRAGMA|CREATE|ALTER)\b"
    ),
    re.compile(r"(?i)(https?://|s3://|gs://|az://|file://|nfs://|smb://)"),
    re.compile(r"(?i)(/[A-Za-z0-9._-]+){3,}"),
    re.compile(r"(?i)\\[A-Za-z]"),
)


# ---------------------------------------------------------------------------
# Enums / errors
# ---------------------------------------------------------------------------


class AccessPlane(str, Enum):
    """Which trust boundary an operation is executed against."""

    CATALOG_MANAGEMENT = "dqk104_catalog_management"
    SNAPSHOT_BOUND_WORKER = "dqk092_snapshot_bound_worker"
    PUBLICATION_PLANE = "dqk058_sanitized_publication"


class HandleStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    TRUNCATED = "truncated"
    CANCELLED = "cancelled"
    BUDGET_EXCEEDED = "budget_exceeded"
    FAILED = "failed"
    DENIED = "denied"


class DuckLakeAPIError(ValueError):
    """Fail-closed rejection of a DuckLake API invocation."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "ducklake_api.error",
        status: str = "error",
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.status = status


# ---------------------------------------------------------------------------
# Public sanitization
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_handle_id() -> str:
    return f"dlqh-{uuid.uuid4().hex}"


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _scrub_text(text: str) -> str:
    cleaned = str(text or "")
    for pattern in _SECRET_LEAK_PATTERNS:
        cleaned = pattern.sub(REDACTION_MARKER, cleaned)
    cleaned = redact_token(cleaned)
    cleaned = redact_sql(cleaned)
    if len(cleaned.encode("utf-8")) > MAX_ERROR_DETAIL_BYTES:
        raw = cleaned.encode("utf-8")[: MAX_ERROR_DETAIL_BYTES - 1]
        while raw and (raw[-1] & 0xC0) == 0x80:
            raw = raw[:-1]
        cleaned = raw.decode("utf-8", errors="ignore") + "…"
    return cleaned


# Keys that may contain the substring "token" / "secret" but are not credentials.
_SAFE_PUBLIC_KEYS: Final[frozenset[str]] = frozenset(
    {
        "next_page_token",
        "page_token",
        "handle_id",
        "handle_status",
        "template_id",
        "template_identity",
        "template_version",
        "parameters_digest",
        "content_digest",
        "logical_result_digest",
        "canonical_sql_digest",
        "template_digest",
        "root_cid",
        "receipt_id",
        "operation_id",
        "export_id",
        "job_id",
        "audit_event_id",
        "vector_id",
        "snapshot_id",
        "snapshot_version",
        "catalog_id",
        "dataset_id",
        "tenant_id",
        "identity_id",
        "reason_code",
        "implementation_generation",
    }
)


def redact_public_payload(payload: Any) -> Any:
    """Recursively redact secret-bearing keys and unsafe strings."""

    if isinstance(payload, Mapping):
        out: dict[str, Any] = {}
        for key, value in payload.items():
            key_s = str(key)
            key_l = key_s.lower()
            if key_l in _SAFE_PUBLIC_KEYS:
                out[key_s] = (
                    value
                    if not isinstance(value, (Mapping, list, tuple))
                    else redact_public_payload(value)
                )
                continue
            if key_l in _SECRET_KEY_NAMES or any(
                frag in key_l
                for frag in (
                    "password",
                    "secret",
                    "token",
                    "credential",
                    "encryption",
                    "private_key",
                    "quack_token",
                    "object_uri",
                )
            ):
                out[key_s] = REDACTION_MARKER
            else:
                out[key_s] = redact_public_payload(value)
        return out
    if isinstance(payload, (list, tuple)):
        return [redact_public_payload(v) for v in payload]
    if isinstance(payload, str):
        return _scrub_text(payload) if _looks_sensitive(payload) else payload
    return payload


def _looks_sensitive(text: str) -> bool:
    for pattern in _SECRET_LEAK_PATTERNS:
        if pattern.search(text):
            return True
    return False


def sanitize_public_error(
    exc: BaseException | str,
    *,
    reason_code: str | None = None,
    fallback: str = "request denied",
) -> dict[str, Any]:
    """Return a public error envelope free of secrets, SQL, tokens, and paths."""

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
        elif isinstance(exc, qc.TemplateDenied):
            code = "catalog.template_denied"
        elif isinstance(exc, qc.SurfaceDenied):
            code = "catalog.surface_denied"
        elif isinstance(exc, DuckLakeAPIError):
            code = exc.reason_code
        else:
            code = "ducklake_api.error"

    safe_messages: Mapping[str, str] = {
        "query.unknown_template": "query template not allowlisted",
        "query.sql_surface_denied": "arbitrary SQL and denied surfaces are forbidden",
        "query.parameter_validation": "parameter validation failed",
        "query.tenant_policy_violation": "tenant policy violation",
        "query.column_policy": "column policy violation",
        "query.budget_exceeded": "query budget exceeded",
        "query.cancelled": "query cancelled",
        "query.registry_error": "query registry rejected the request",
        "catalog.template_denied": "catalog template not allowlisted",
        "catalog.surface_denied": "catalog surface denied",
        "ducklake_api.missing_template_id": "template_id is required",
        "ducklake_api.missing_tenant": "tenant_id is required",
        "ducklake_api.missing_snapshot": "snapshot_id is required",
        "ducklake_api.missing_catalog": "catalog_id is required",
        "ducklake_api.missing_handle": "handle_id is required",
        "ducklake_api.unknown_handle": "unknown query handle",
        "ducklake_api.unknown_catalog": "unknown catalog",
        "ducklake_api.invalid_page_size": "page_size out of bounds",
        "ducklake_api.invalid_page_token": "invalid page token",
        "ducklake_api.page_out_of_range": "page offset out of range",
        "ducklake_api.untrusted_catalog_access": (
            "untrusted access cannot open authority catalog Quack endpoints"
        ),
        "ducklake_api.missing_trust_worker": "trusted worker identity required",
        "ducklake_api.export_failed": "export failed",
        "ducklake_api.snapshot_not_retained": "snapshot outside retention window",
        "ducklake_api.error": fallback,
    }
    message = safe_messages.get(code, fallback)
    # Never echo raw exception text that may hold secrets.
    if isinstance(exc, DuckLakeAPIError) and code in safe_messages:
        message = safe_messages[code]
    return {
        "status": "error",
        "schema": DUCKLAKE_API_SCHEMA,
        "error": message,
        "reason_code": code,
        "implementation_generation": DUCKLAKE_API_IMPLEMENTATION_GENERATION,
    }


def _clamp_page_size(value: Any) -> int:
    if value is None:
        return DEFAULT_PAGE_SIZE
    try:
        size = int(value)
    except (TypeError, ValueError) as exc:
        raise DuckLakeAPIError(
            "page_size out of bounds",
            reason_code="ducklake_api.invalid_page_size",
        ) from exc
    if size < 1 or size > MAX_PAGE_SIZE:
        raise DuckLakeAPIError(
            "page_size out of bounds",
            reason_code="ducklake_api.invalid_page_size",
        )
    return size


def _parse_snapshot(
    snapshot_id: SnapshotId | str | Mapping[str, Any] | int | None,
    *,
    store_generation: int | None = None,
) -> SnapshotId:
    if snapshot_id is None or (
        isinstance(snapshot_id, str) and not snapshot_id.strip()
    ):
        raise DuckLakeAPIError(
            "snapshot_id is required",
            reason_code="ducklake_api.missing_snapshot",
        )
    if isinstance(snapshot_id, SnapshotId):
        return snapshot_id
    if isinstance(snapshot_id, int) and not isinstance(snapshot_id, bool):
        return SnapshotId(
            value=f"snap-v{snapshot_id}",
            store_generation=store_generation or 0,
        )
    if isinstance(snapshot_id, Mapping):
        value = snapshot_id.get("value") or snapshot_id.get("snapshot_id")
        gen = snapshot_id.get("store_generation", store_generation or 0)
        if value is None or (isinstance(value, str) and not str(value).strip()):
            raise DuckLakeAPIError(
                "snapshot_id is required",
                reason_code="ducklake_api.missing_snapshot",
            )
        return SnapshotId(value=str(value), store_generation=int(gen or 0))
    try:
        return SnapshotId(
            value=str(snapshot_id),
            store_generation=store_generation or 0,
        )
    except Exception as exc:
        raise DuckLakeAPIError(
            "invalid snapshot_id",
            reason_code="ducklake_api.missing_snapshot",
        ) from exc


def _parse_trust(trust: Any) -> qr.TrustClass:
    if isinstance(trust, qr.TrustClass):
        return trust
    text = str(trust or "untrusted").strip().lower()
    if text in {"trusted", "trust"}:
        return qr.TrustClass.TRUSTED
    if text in {"untrusted", "public", "remote"}:
        return qr.TrustClass.UNTRUSTED
    try:
        return qr.TrustClass(text)
    except Exception as exc:
        raise DuckLakeAPIError(
            "invalid trust class",
            reason_code="ducklake_api.error",
        ) from exc


def _public_receipt(receipt: qr.QueryReceipt) -> dict[str, Any]:
    return {
        "template_id": receipt.template_id,
        "template_version": receipt.template_version,
        "parameters_digest": receipt.parameters_digest,
        "snapshot": receipt.snapshot.to_dict(),
        "status": receipt.status.value,
        "row_count": receipt.row_count,
        "truncated": receipt.truncated,
        "identity_id": getattr(receipt, "template_identity", None)
        or getattr(receipt, "identity_id", ""),
    }


# ---------------------------------------------------------------------------
# Projections (sanitized public catalog views)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CatalogProjection:
    """Sanitized catalog descriptor visible to callers (no credentials/paths)."""

    catalog_id: str
    owner_generation: int | None = None
    fencing_epoch: int | None = None
    snapshot_version: int | None = None
    admits_requests: bool = False
    plane: AccessPlane = AccessPlane.CATALOG_MANAGEMENT

    def __post_init__(self) -> None:
        cid = str(self.catalog_id or "").strip()
        if not cid or not _SAFE_IDENT.match(cid):
            raise DuckLakeAPIError(
                "invalid catalog_id",
                reason_code="ducklake_api.missing_catalog",
            )
        object.__setattr__(self, "catalog_id", cid)

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_id": self.catalog_id,
            "owner_generation": self.owner_generation,
            "fencing_epoch": self.fencing_epoch,
            "snapshot_version": self.snapshot_version,
            "admits_requests": self.admits_requests,
            "plane": self.plane.value,
            # Explicit denials: never publish authority attachment facts.
            "catalog_path": REDACTION_MARKER,
            "quack_token": REDACTION_MARKER,
            "credentials": REDACTION_MARKER,
            "object_uri": REDACTION_MARKER,
        }


@dataclass(frozen=True, slots=True)
class DatasetProjection:
    """Sanitized dataset / table projection for discovery."""

    catalog_id: str
    namespace: str
    schema_name: str
    dataset_id: str
    snapshot_version: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_id": self.catalog_id,
            "namespace": self.namespace,
            "schema_name": self.schema_name,
            "dataset_id": self.dataset_id,
            "snapshot_version": self.snapshot_version,
            "catalog_path": REDACTION_MARKER,
            "object_uri": REDACTION_MARKER,
        }


@dataclass(frozen=True, slots=True)
class SnapshotSelection:
    """Bounded snapshot / time-travel selection result."""

    catalog_id: str
    snapshot_version: int
    snapshot_id: SnapshotId
    retained: bool = True
    vector_id: str = ""
    logical_result_digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_id": self.catalog_id,
            "snapshot_version": self.snapshot_version,
            "snapshot": self.snapshot_id.to_dict(),
            "retained": self.retained,
            "vector_id": self.vector_id,
            "logical_result_digest": self.logical_result_digest,
        }


# ---------------------------------------------------------------------------
# Handles / page tokens
# ---------------------------------------------------------------------------


@dataclass
class QueryHandle:
    """Server-side state for one lake query/export invocation."""

    handle_id: str
    template_id: str
    snapshot: SnapshotId
    tenant_id: str
    trust: qr.TrustClass
    status: HandleStatus
    created_at: str
    plane: AccessPlane
    cancellation: qr.CancellationToken = field(default_factory=qr.CancellationToken)
    page_size: int = DEFAULT_PAGE_SIZE
    operation: str = "query"
    rows: tuple[Mapping[str, Any], ...] = ()
    receipt: qr.QueryReceipt | None = None
    parameters_digest: str = ""
    export_summary: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    updated_at: str = ""
    catalog_id: str = ""

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
            "template_id": self.template_id,
            "handle_status": self.status.value,
            "operation": self.operation,
            "snapshot": self.snapshot.to_dict(),
            "tenant_id": self.tenant_id,
            "trust": self.trust.value,
            "plane": self.plane.value,
            "catalog_id": self.catalog_id or None,
            "row_count": len(self.rows),
            "cancelled": self.cancellation.is_cancelled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "parameters_digest": self.parameters_digest or None,
        }
        if self.export_summary is not None:
            body["export"] = self.export_summary
        if self.error is not None:
            body["error"] = self.error
        return body


class _PageTokenCodec:
    """HMAC-bound page tokens (handle_id + offset)."""

    def __init__(self, secret: bytes | None = None) -> None:
        self._secret = secret or secrets.token_bytes(32)

    def mint(self, handle_id: str, offset: int) -> str | None:
        if offset is None:  # pragma: no cover
            return None
        payload = f"{handle_id}:{int(offset)}".encode("utf-8")
        sig = hmac.new(self._secret, payload, hashlib.sha256).hexdigest()[:24]
        import base64

        token = base64.urlsafe_b64encode(payload + b"|" + sig.encode("ascii")).decode(
            "ascii"
        )
        return token

    def parse(self, handle_id: str, token: str) -> int:
        import base64

        try:
            raw = base64.urlsafe_b64decode(token.encode("ascii"))
            payload, sig = raw.rsplit(b"|", 1)
            expected = hmac.new(self._secret, payload, hashlib.sha256).hexdigest()[
                :24
            ]
            if not hmac.compare_digest(sig.decode("ascii"), expected):
                raise DuckLakeAPIError(
                    "invalid page token",
                    reason_code="ducklake_api.invalid_page_token",
                )
            hid, offset_s = payload.decode("utf-8").split(":", 1)
            if hid != handle_id:
                raise DuckLakeAPIError(
                    "invalid page token",
                    reason_code="ducklake_api.invalid_page_token",
                )
            return int(offset_s)
        except DuckLakeAPIError:
            raise
        except Exception as exc:
            raise DuckLakeAPIError(
                "invalid page token",
                reason_code="ducklake_api.invalid_page_token",
            ) from exc


# ---------------------------------------------------------------------------
# Default lake query templates (publication / aggregate plane)
# ---------------------------------------------------------------------------


def default_ducklake_query_templates() -> tuple[qr.QueryTemplate, ...]:
    """Allowlisted lake query templates for discovery aggregates and exports.

    These are executed on the sanitized publication plane or via snapshot-bound
    workers that materialize only projected public columns. They never ATTACH
    authority catalogs or accept raw SQL.
    """

    tenant_param = qr.ParameterSpec(
        name="tenant_id",
        param_type=qr.ParameterType.TENANT_ID,
        required=True,
        description="Tenant isolation key",
    )
    catalog_param = qr.ParameterSpec(
        name="catalog_id",
        param_type=qr.ParameterType.IDENTIFIER,
        required=True,
        description="Logical catalog shard id",
    )
    limit_param = qr.ParameterSpec(
        name="row_limit",
        param_type=qr.ParameterType.INTEGER,
        required=False,
        default=100,
        description="Caller-requested row cap (still bounded by budget)",
    )

    return (
        qr.QueryTemplate(
            template_id="ducklake.discover_datasets",
            version=1,
            sql=(
                "SELECT catalog_id, namespace, schema_name, dataset_id, "
                "snapshot_version FROM lake_dataset_projection "
                "WHERE tenant_id = ? AND catalog_id = ? "
                "ORDER BY dataset_id LIMIT ?"
            ),
            parameter_schema=qr.ParameterSchema(
                schema_version=1,
                parameters=(tenant_param, catalog_param, limit_param),
            ),
            column_policy=qr.ColumnPolicy(
                {
                    "catalog_id": qr.ColumnClassification.PUBLIC,
                    "namespace": qr.ColumnClassification.PUBLIC,
                    "schema_name": qr.ColumnClassification.PUBLIC,
                    "dataset_id": qr.ColumnClassification.PUBLIC,
                    "snapshot_version": qr.ColumnClassification.PUBLIC,
                }
            ),
            budget=qr.DEFAULT_UNTRUSTED_QUERY_BUDGET,
            allowed_trust=frozenset(
                {qr.TrustClass.TRUSTED, qr.TrustClass.UNTRUSTED}
            ),
            description="Bounded sanitized dataset discovery projection",
            domains=("ducklake", "publication"),
        ),
        qr.QueryTemplate(
            template_id="ducklake.aggregate_count",
            version=1,
            sql=(
                "SELECT catalog_id, dataset_id, tenant_id, row_count, "
                "snapshot_version FROM lake_aggregate_counts "
                "WHERE tenant_id = ? AND catalog_id = ? AND dataset_id = ? "
                "ORDER BY dataset_id LIMIT ?"
            ),
            parameter_schema=qr.ParameterSchema(
                schema_version=1,
                parameters=(
                    tenant_param,
                    catalog_param,
                    qr.ParameterSpec(
                        name="dataset_id",
                        param_type=qr.ParameterType.IDENTIFIER,
                        required=True,
                        description="Logical dataset / table id",
                    ),
                    limit_param,
                ),
            ),
            column_policy=qr.ColumnPolicy(
                {
                    "catalog_id": qr.ColumnClassification.PUBLIC,
                    "dataset_id": qr.ColumnClassification.PUBLIC,
                    "tenant_id": qr.ColumnClassification.PUBLIC,
                    "row_count": qr.ColumnClassification.PUBLIC,
                    "snapshot_version": qr.ColumnClassification.PUBLIC,
                }
            ),
            budget=qr.DEFAULT_UNTRUSTED_QUERY_BUDGET,
            allowed_trust=frozenset(
                {qr.TrustClass.TRUSTED, qr.TrustClass.UNTRUSTED}
            ),
            description="Bounded snapshot-bound aggregate counts",
            domains=("ducklake", "aggregate"),
        ),
        qr.QueryTemplate(
            template_id="ducklake.dataset_summary",
            version=1,
            sql=(
                "SELECT catalog_id, dataset_id, tenant_id, status, "
                "snapshot_version, updated_at FROM lake_dataset_summary "
                "WHERE tenant_id = ? AND catalog_id = ? AND dataset_id = ? "
                "LIMIT ?"
            ),
            parameter_schema=qr.ParameterSchema(
                schema_version=1,
                parameters=(
                    tenant_param,
                    catalog_param,
                    qr.ParameterSpec(
                        name="dataset_id",
                        param_type=qr.ParameterType.IDENTIFIER,
                        required=True,
                        description="Logical dataset id",
                    ),
                    limit_param,
                ),
            ),
            column_policy=qr.ColumnPolicy(
                {
                    "catalog_id": qr.ColumnClassification.PUBLIC,
                    "dataset_id": qr.ColumnClassification.PUBLIC,
                    "tenant_id": qr.ColumnClassification.PUBLIC,
                    "status": qr.ColumnClassification.PUBLIC,
                    "snapshot_version": qr.ColumnClassification.PUBLIC,
                    "updated_at": qr.ColumnClassification.PUBLIC,
                }
            ),
            budget=qr.DEFAULT_UNTRUSTED_QUERY_BUDGET,
            allowed_trust=frozenset(
                {qr.TrustClass.TRUSTED, qr.TrustClass.UNTRUSTED}
            ),
            description="Bounded sanitized dataset summary",
            domains=("ducklake", "publication"),
        ),
    )


# ---------------------------------------------------------------------------
# API gateway
# ---------------------------------------------------------------------------


class DuckLakeQueryAPI:
    """In-process allowlisted DuckLake query/export/catalog API.

    Catalog-management paths use DQK-104 templates via
    :class:`CatalogServiceManager` / :class:`TrustedCatalogBroker`.
    Query/export paths use the DQK-041 query-template registry against the
    sanitized publication plane (untrusted) or snapshot-bound workers
    (trusted + snapshot vector).
    """

    def __init__(
        self,
        *,
        catalog_manager: CatalogServiceManager | None = None,
        registry: qr.QueryRegistry | None = None,
        executor: qr.QueryExecutor | None = None,
        exporter: SnapshotExporter | None = None,
        backend: Any | None = None,
        clock: Callable[[], str] | None = None,
        page_token_secret: bytes | None = None,
        max_handles: int = MAX_HANDLES,
        include_lake_templates: bool = True,
        include_builtin_query_templates: bool = True,
        catalog_projections: Sequence[CatalogProjection] | None = None,
        dataset_projections: Sequence[DatasetProjection] | None = None,
        retained_snapshots: Mapping[str, Sequence[int]] | None = None,
    ) -> None:
        self._catalog_manager = catalog_manager or CatalogServiceManager()
        if registry is None:
            registry = qr.open_default_registry(
                include_builtins=include_builtin_query_templates
            )
        if include_lake_templates:
            for template in default_ducklake_query_templates():
                if template.template_id in registry:
                    registry.register(template, replace=True)
                else:
                    registry.register(template)
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
        self._catalog_projections: dict[str, CatalogProjection] = {
            p.catalog_id: p for p in (catalog_projections or ())
        }
        self._dataset_projections: list[DatasetProjection] = list(
            dataset_projections or ()
        )
        self._retained_snapshots: dict[str, tuple[int, ...]] = {
            str(k): tuple(int(v) for v in vals)
            for k, vals in dict(retained_snapshots or {}).items()
        }
        # Catalog template registry for DQK-104 catalog-management ops.
        self._catalog_templates = qc.open_default_template_registry()

    # -- properties ---------------------------------------------------------

    @property
    def registry(self) -> qr.QueryRegistry:
        return self._registry

    @property
    def catalog_manager(self) -> CatalogServiceManager:
        return self._catalog_manager

    @property
    def catalog_templates(self) -> qc.CatalogTemplateRegistry:
        return self._catalog_templates

    # -- projection seeding (tests / hermetic local) ------------------------

    def register_catalog_projection(self, projection: CatalogProjection) -> None:
        with self._lock:
            self._catalog_projections[projection.catalog_id] = projection

    def register_dataset_projection(self, projection: DatasetProjection) -> None:
        with self._lock:
            self._dataset_projections.append(projection)

    def register_retained_snapshot(
        self, catalog_id: str, snapshot_version: int
    ) -> None:
        with self._lock:
            existing = list(self._retained_snapshots.get(catalog_id, ()))
            version = int(snapshot_version)
            if version not in existing:
                existing.append(version)
            self._retained_snapshots[catalog_id] = tuple(sorted(existing))

    def register_owner_service(self, service: CatalogOwnerService) -> None:
        """Register a DQK-104 catalog owner and publish a sanitized projection."""

        self._catalog_manager.register(service)
        projection = CatalogProjection(
            catalog_id=service.catalog_id,
            owner_generation=service.owner_generation,
            fencing_epoch=getattr(service, "_fencing_epoch", None),
            snapshot_version=getattr(service, "_last_snapshot", None),
            admits_requests=bool(service.admits_requests),
            plane=AccessPlane.CATALOG_MANAGEMENT,
        )
        self.register_catalog_projection(projection)
        # Seed retained snapshots for time-travel selection.
        snap = getattr(service, "_last_snapshot", None)
        if snap is not None:
            self.register_retained_snapshot(service.catalog_id, int(snap))
        # Project in-memory tables as datasets (sanitized ids only).
        tables = getattr(service, "_tables", {}) or {}
        for schema_name, table_set in tables.items():
            for table in sorted(table_set):
                self.register_dataset_projection(
                    DatasetProjection(
                        catalog_id=service.catalog_id,
                        namespace="main",
                        schema_name=str(schema_name),
                        dataset_id=str(table),
                        snapshot_version=snap,
                    )
                )

    # -- handle bookkeeping -------------------------------------------------

    def _store_handle(self, handle: QueryHandle) -> None:
        with self._lock:
            if len(self._handles) >= self._max_handles:
                terminal = [
                    (h.handle_id, h.updated_at)
                    for h in self._handles.values()
                    if h.is_terminal
                ]
                terminal.sort(key=lambda item: item[1])
                for hid, _ in terminal[: max(1, len(terminal) // 4 or 1)]:
                    self._handles.pop(hid, None)
                if len(self._handles) >= self._max_handles:
                    raise DuckLakeAPIError(
                        "query handle capacity exceeded",
                        reason_code="query.budget_exceeded",
                    )
            self._handles[handle.handle_id] = handle

    def get_handle(self, handle_id: str) -> QueryHandle:
        hid = str(handle_id or "").strip()
        if not hid:
            raise DuckLakeAPIError(
                "handle_id is required",
                reason_code="ducklake_api.missing_handle",
            )
        with self._lock:
            handle = self._handles.get(hid)
        if handle is None:
            raise DuckLakeAPIError(
                "unknown query handle",
                reason_code="ducklake_api.unknown_handle",
            )
        return handle

    def _select_query_plane(self, trust: qr.TrustClass) -> AccessPlane:
        if trust is qr.TrustClass.TRUSTED:
            return AccessPlane.SNAPSHOT_BOUND_WORKER
        return AccessPlane.PUBLICATION_PLANE

    # -- catalog / dataset discovery (DQK-104 for management) ---------------

    def discover_catalogs(
        self,
        *,
        tenant_id: str | None = None,
        trust: Any = qr.TrustClass.UNTRUSTED,
        max_rows: int | None = None,
        sql: str | None = None,
    ) -> dict[str, Any]:
        """List sanitized catalog projections (never credentials or paths)."""

        try:
            qr.deny_arbitrary_sql(sql, template_id="catalog.discover")
        except qr.QueryRegistryError as exc:
            raise DuckLakeAPIError(
                "arbitrary SQL and denied surfaces are forbidden",
                reason_code=getattr(exc, "reason_code", "query.sql_surface_denied"),
            ) from exc

        trust_cls = _parse_trust(trust)
        limit = min(int(max_rows or MAX_DISCOVERY_ROWS), MAX_DISCOVERY_ROWS)
        if limit < 1:
            raise DuckLakeAPIError(
                "page_size out of bounds",
                reason_code="ducklake_api.invalid_page_size",
            )

        # Merge live manager catalogs into projections (sanitized).
        catalogs: list[dict[str, Any]] = []
        seen: set[str] = set()
        with self._lock:
            manager_ids = list(self._catalog_manager.list_catalogs())
            projections = dict(self._catalog_projections)

        for catalog_id in manager_ids:
            if catalog_id in seen:
                continue
            seen.add(catalog_id)
            proj = projections.get(catalog_id)
            if proj is None:
                try:
                    service = self._catalog_manager.get(catalog_id)
                    proj = CatalogProjection(
                        catalog_id=catalog_id,
                        owner_generation=service.owner_generation,
                        fencing_epoch=getattr(service, "_fencing_epoch", None),
                        snapshot_version=getattr(service, "_last_snapshot", None),
                        admits_requests=bool(service.admits_requests),
                        plane=AccessPlane.CATALOG_MANAGEMENT,
                    )
                except Exception:
                    proj = CatalogProjection(
                        catalog_id=catalog_id,
                        plane=AccessPlane.CATALOG_MANAGEMENT,
                    )
            catalogs.append(proj.to_dict())
            if len(catalogs) >= limit:
                break

        if len(catalogs) < limit:
            for catalog_id, proj in sorted(projections.items()):
                if catalog_id in seen:
                    continue
                seen.add(catalog_id)
                catalogs.append(proj.to_dict())
                if len(catalogs) >= limit:
                    break

        # Untrusted callers never receive authority attachment evidence.
        plane = (
            AccessPlane.CATALOG_MANAGEMENT
            if trust_cls is qr.TrustClass.TRUSTED
            else AccessPlane.PUBLICATION_PLANE
        )
        body = {
            "status": "ok",
            "schema": DUCKLAKE_API_SCHEMA,
            "operation": "discover_catalogs",
            "template_id": "catalog.discover",
            "plane": plane.value,
            "tenant_id": str(tenant_id).strip() if tenant_id else None,
            "trust": trust_cls.value,
            "catalogs": catalogs[:limit],
            "count": len(catalogs[:limit]),
            "bounded": True,
            "max_rows": limit,
            "direct_authority_quack_access": False,
            "implementation_generation": DUCKLAKE_API_IMPLEMENTATION_GENERATION,
        }
        return redact_public_payload(body)

    def discover_datasets(
        self,
        *,
        catalog_id: str | None = None,
        tenant_id: str | None = None,
        namespace: str = "main",
        schema_name: str = "main",
        trust: Any = qr.TrustClass.UNTRUSTED,
        max_rows: int | None = None,
        sql: str | None = None,
        worker: Any | None = None,
    ) -> dict[str, Any]:
        """Discover datasets via DQK-104 catalog templates or sanitized projection.

        Trusted + worker path: executes allowlisted ``table.list`` /
        ``namespace.list`` / ``schema.list`` through the catalog owner broker.
        Untrusted path: returns only pre-published sanitized projections —
        never direct authority-catalog Quack access.
        """

        try:
            qr.deny_arbitrary_sql(sql, template_id="table.list")
        except qr.QueryRegistryError as exc:
            raise DuckLakeAPIError(
                "arbitrary SQL and denied surfaces are forbidden",
                reason_code=getattr(exc, "reason_code", "query.sql_surface_denied"),
            ) from exc

        trust_cls = _parse_trust(trust)
        limit = min(int(max_rows or MAX_DISCOVERY_ROWS), MAX_DISCOVERY_ROWS)
        cid = str(catalog_id or "").strip()
        tenant = str(tenant_id).strip() if tenant_id else ""
        datasets: list[dict[str, Any]] = []
        plane = AccessPlane.PUBLICATION_PLANE
        catalog_receipt: dict[str, Any] | None = None

        if trust_cls is qr.TrustClass.TRUSTED and worker is not None and cid:
            # DQK-104 catalog-management path (typed broker, no raw SQL).
            plane = AccessPlane.CATALOG_MANAGEMENT
            try:
                service = self._catalog_manager.get(cid)
            except Exception as exc:
                raise DuckLakeAPIError(
                    "unknown catalog",
                    reason_code="ducklake_api.unknown_catalog",
                ) from exc
            if not getattr(worker, "trusted", False):
                raise DuckLakeAPIError(
                    "untrusted access cannot open authority catalog Quack endpoints",
                    reason_code="ducklake_api.untrusted_catalog_access",
                )
            broker = TrustedCatalogBroker(service)
            op = broker.mint_operation(
                template_id="table.list",
                tenant=tenant or "system",
                worker=worker,
                parameters={
                    "catalog_id": cid,
                    "schema_name": str(schema_name or "main"),
                    "max_rows": limit,
                },
            )
            receipt = broker.submit(op, worker=worker)
            catalog_receipt = {
                "operation_id": receipt.operation_id,
                "receipt_id": receipt.receipt_id,
                "template_identity": receipt.template_identity,
                "before_snapshot": receipt.before_snapshot,
                "after_snapshot": receipt.after_snapshot,
                "outbox_state": receipt.outbox_state,
                "canonical_sql_digest": receipt.canonical_sql_digest,
                # Never include canonical SQL or tokens.
            }
            # Project affected logical objects as datasets.
            for name in receipt.affected_logical_objects:
                datasets.append(
                    DatasetProjection(
                        catalog_id=cid,
                        namespace=str(namespace or "main"),
                        schema_name=str(schema_name or "main"),
                        dataset_id=str(name),
                        snapshot_version=receipt.after_snapshot,
                    ).to_dict()
                )
        else:
            # Sanitized publication-plane projection only.
            if trust_cls is qr.TrustClass.TRUSTED and cid and worker is None:
                # Trusted without worker still cannot hit authority Quack.
                plane = AccessPlane.PUBLICATION_PLANE
            with self._lock:
                projections = list(self._dataset_projections)
            for proj in projections:
                if cid and proj.catalog_id != cid:
                    continue
                if namespace and proj.namespace != namespace:
                    continue
                if schema_name and proj.schema_name != schema_name:
                    continue
                datasets.append(proj.to_dict())
                if len(datasets) >= limit:
                    break

        body: dict[str, Any] = {
            "status": "ok",
            "schema": DUCKLAKE_API_SCHEMA,
            "operation": "discover_datasets",
            "template_id": (
                "table.list"
                if plane is AccessPlane.CATALOG_MANAGEMENT
                else "ducklake.discover_datasets"
            ),
            "plane": plane.value,
            "catalog_id": cid or None,
            "namespace": namespace,
            "schema_name": schema_name,
            "tenant_id": tenant or None,
            "trust": trust_cls.value,
            "datasets": datasets[:limit],
            "count": len(datasets[:limit]),
            "bounded": True,
            "max_rows": limit,
            "direct_authority_quack_access": False,
            "implementation_generation": DUCKLAKE_API_IMPLEMENTATION_GENERATION,
        }
        if catalog_receipt is not None:
            body["catalog_receipt"] = catalog_receipt
        return redact_public_payload(body)

    def select_snapshot(
        self,
        *,
        catalog_id: str | None = None,
        snapshot_version: int | None = None,
        tenant_id: str | None = None,
        trust: Any = qr.TrustClass.UNTRUSTED,
        sql: str | None = None,
        worker: Any | None = None,
        time_travel: bool = False,
        logical_query_id: str | None = None,
    ) -> dict[str, Any]:
        """Select a bounded snapshot (optional time-travel) for a catalog.

        Trusted + worker: uses DQK-104 ``snapshot.get`` template.
        Untrusted: validates against retained snapshot projections only.
        """

        try:
            qr.deny_arbitrary_sql(sql, template_id="snapshot.get")
        except qr.QueryRegistryError as exc:
            raise DuckLakeAPIError(
                "arbitrary SQL and denied surfaces are forbidden",
                reason_code=getattr(exc, "reason_code", "query.sql_surface_denied"),
            ) from exc

        cid = str(catalog_id or "").strip()
        if not cid:
            raise DuckLakeAPIError(
                "catalog_id is required",
                reason_code="ducklake_api.missing_catalog",
            )
        if snapshot_version is None:
            raise DuckLakeAPIError(
                "snapshot_id is required",
                reason_code="ducklake_api.missing_snapshot",
            )
        version = int(snapshot_version)
        if version < 0:
            raise DuckLakeAPIError(
                "snapshot_id is required",
                reason_code="ducklake_api.missing_snapshot",
            )
        trust_cls = _parse_trust(trust)
        plane = AccessPlane.PUBLICATION_PLANE
        catalog_receipt: dict[str, Any] | None = None

        with self._lock:
            retained = set(self._retained_snapshots.get(cid, ()))

        if trust_cls is qr.TrustClass.TRUSTED and worker is not None:
            if not getattr(worker, "trusted", False):
                raise DuckLakeAPIError(
                    "untrusted access cannot open authority catalog Quack endpoints",
                    reason_code="ducklake_api.untrusted_catalog_access",
                )
            plane = AccessPlane.CATALOG_MANAGEMENT
            try:
                service = self._catalog_manager.get(cid)
            except Exception as exc:
                raise DuckLakeAPIError(
                    "unknown catalog",
                    reason_code="ducklake_api.unknown_catalog",
                ) from exc
            broker = TrustedCatalogBroker(service)
            op = broker.mint_operation(
                template_id="snapshot.get",
                tenant=str(tenant_id or "system").strip(),
                worker=worker,
                parameters={
                    "catalog_id": cid,
                    "snapshot_version": version,
                },
                starting_snapshot=version,
            )
            receipt = broker.submit(op, worker=worker)
            catalog_receipt = {
                "operation_id": receipt.operation_id,
                "receipt_id": receipt.receipt_id,
                "template_identity": receipt.template_identity,
                "before_snapshot": receipt.before_snapshot,
                "after_snapshot": receipt.after_snapshot,
                "canonical_sql_digest": receipt.canonical_sql_digest,
            }
            retained.add(version)
            self.register_retained_snapshot(cid, version)

        retained_flag = version in retained or not self._retained_snapshots
        if time_travel and not retained_flag and retained:
            raise DuckLakeAPIError(
                "snapshot outside retention window",
                reason_code="ducklake_api.snapshot_not_retained",
            )

        snap = SnapshotId(value=f"snap-v{version}", store_generation=version)
        digest = content_identity(
            {
                "catalog_id": cid,
                "snapshot_version": version,
                "logical_query_id": str(logical_query_id or "select_snapshot"),
                "time_travel": bool(time_travel),
            }
        )
        selection = SnapshotSelection(
            catalog_id=cid,
            snapshot_version=version,
            snapshot_id=snap,
            retained=retained_flag if retained else True,
            vector_id=f"vec-{cid}-v{version}",
            logical_result_digest=digest,
        )
        body: dict[str, Any] = {
            "status": "ok",
            "schema": DUCKLAKE_API_SCHEMA,
            "operation": "select_snapshot",
            "template_id": "snapshot.get",
            "plane": plane.value,
            "tenant_id": str(tenant_id).strip() if tenant_id else None,
            "trust": trust_cls.value,
            "selection": selection.to_dict(),
            "time_travel": bool(time_travel),
            "bounded": True,
            "reproducible": True,
            "direct_authority_quack_access": False,
            "implementation_generation": DUCKLAKE_API_IMPLEMENTATION_GENERATION,
        }
        if catalog_receipt is not None:
            body["catalog_receipt"] = catalog_receipt
        return redact_public_payload(body)

    # -- list / explain / query / export (template registry) ----------------

    def list_templates(
        self,
        *,
        trust: Any = qr.TrustClass.UNTRUSTED,
        include_catalog_templates: bool = True,
    ) -> dict[str, Any]:
        """List allowlisted query + catalog templates visible to trust class."""

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
                    "kind": "query",
                    "plane": (
                        AccessPlane.PUBLICATION_PLANE.value
                        if trust_cls is qr.TrustClass.UNTRUSTED
                        else AccessPlane.SNAPSHOT_BOUND_WORKER.value
                    ),
                    # SQL intentionally omitted.
                }
            )
        if include_catalog_templates and trust_cls is qr.TrustClass.TRUSTED:
            for ct in self._catalog_templates.list_templates():
                templates.append(
                    {
                        "template_id": ct.template_id,
                        "version": ct.version,
                        "description": ct.description,
                        "domains": ["catalog_management", ct.kind.value],
                        "allowed_trust": [qr.TrustClass.TRUSTED.value],
                        "parameter_schema": {
                            "parameter_names": list(ct.parameter_names),
                        },
                        "kind": "catalog_management",
                        "plane": AccessPlane.CATALOG_MANAGEMENT.value,
                        "mutates": ct.mutates,
                        "template_digest": ct.template_digest(),
                        # canonical_sql redacted at template as_mapping.
                    }
                )
        return {
            "status": "ok",
            "schema": DUCKLAKE_API_SCHEMA,
            "operation": "list_templates",
            "templates": templates,
            "count": len(templates),
            "trust": trust_cls.value,
            "implementation_generation": DUCKLAKE_API_IMPLEMENTATION_GENERATION,
        }

    def explain(
        self,
        template_id: str | None,
        params: Mapping[str, Any] | None = None,
        *,
        snapshot_id: SnapshotId | str | Mapping[str, Any] | int | None = None,
        tenant_id: str | None = None,
        trust: Any = qr.TrustClass.UNTRUSTED,
        sql: str | None = None,
        store_generation: int | None = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        """Prepare an allowlisted template and return a non-SQL plan summary."""

        if not template_id or not str(template_id).strip():
            raise DuckLakeAPIError(
                "template_id is required",
                reason_code="ducklake_api.missing_template_id",
            )
        try:
            qr.deny_arbitrary_sql(sql, template_id=template_id)
            if sql is not None and str(sql).strip():
                qc.deny_arbitrary_sql(str(sql))
        except (qr.QueryRegistryError, qc.SurfaceDenied, qc.QuackCatalogError) as exc:
            raise DuckLakeAPIError(
                "arbitrary SQL and denied surfaces are forbidden",
                reason_code=getattr(exc, "reason_code", "query.sql_surface_denied"),
            ) from exc
        if not tenant_id or not str(tenant_id).strip():
            raise DuckLakeAPIError(
                "tenant_id is required",
                reason_code="ducklake_api.missing_tenant",
            )
        snap = _parse_snapshot(snapshot_id, store_generation=store_generation)
        trust_cls = _parse_trust(trust)
        plane = self._select_query_plane(trust_cls)
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
            raise DuckLakeAPIError(
                sanitize_public_error(exc)["error"],
                reason_code=getattr(exc, "reason_code", "query.registry_error"),
            ) from exc
        budget = self._registry.effective_budget(prepared.template, prepared.trust)
        return {
            "status": "ok",
            "schema": DUCKLAKE_API_SCHEMA,
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
            "plane": plane.value,
            "bind_value_count": len(prepared.bind_values),
            "sql_redacted": redact_sql(prepared.template.sql),
            "direct_authority_quack_access": False,
            "implementation_generation": DUCKLAKE_API_IMPLEMENTATION_GENERATION,
        }

    def query(
        self,
        template_id: str | None,
        params: Mapping[str, Any] | None = None,
        *,
        snapshot_id: SnapshotId | str | Mapping[str, Any] | int | None = None,
        tenant_id: str | None = None,
        trust: Any = qr.TrustClass.UNTRUSTED,
        page_size: int | None = None,
        sql: str | None = None,
        cancellation: qr.CancellationToken | None = None,
        row_source: Callable[..., Sequence[Mapping[str, Any]]] | None = None,
        store_generation: int | None = None,
        catalog_id: str | None = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        """Execute a bounded allowlisted query (aggregate / discovery / export prep)."""

        if not template_id or not str(template_id).strip():
            raise DuckLakeAPIError(
                "template_id is required",
                reason_code="ducklake_api.missing_template_id",
            )
        try:
            qr.deny_arbitrary_sql(sql, template_id=template_id)
            if sql is not None and str(sql).strip():
                qc.deny_arbitrary_sql(str(sql))
        except (qr.QueryRegistryError, qc.SurfaceDenied, qc.QuackCatalogError) as exc:
            raise DuckLakeAPIError(
                "arbitrary SQL and denied surfaces are forbidden",
                reason_code=getattr(exc, "reason_code", "query.sql_surface_denied"),
            ) from exc
        if not tenant_id or not str(tenant_id).strip():
            raise DuckLakeAPIError(
                "tenant_id is required",
                reason_code="ducklake_api.missing_tenant",
            )
        # Reject SQL-smuggled parameter keys.
        if params:
            for key in params:
                key_l = str(key).lower()
                if key_l in {"sql", "query", "raw_sql", "attach", "statement"}:
                    raise DuckLakeAPIError(
                        "arbitrary SQL and denied surfaces are forbidden",
                        reason_code="query.sql_surface_denied",
                    )

        snap = _parse_snapshot(snapshot_id, store_generation=store_generation)
        trust_cls = _parse_trust(trust)
        plane = self._select_query_plane(trust_cls)
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
            plane=plane,
            cancellation=cancel,
            page_size=page_sz,
            operation="query",
            catalog_id=str(catalog_id or "").strip(),
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
            return self._query_response(handle, offset=0)
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
            raise DuckLakeAPIError(
                handle.error["error"],
                reason_code=handle.error["reason_code"],
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive
            handle.status = HandleStatus.FAILED
            handle.error = sanitize_public_error(exc)
            handle.updated_at = self._clock()
            raise DuckLakeAPIError(
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
        return self._query_response(handle, offset=0)

    def _query_response(
        self, handle: QueryHandle, *, offset: int
    ) -> dict[str, Any]:
        total = len(handle.rows)
        page_sz = handle.page_size
        if offset > total:
            raise DuckLakeAPIError(
                "page offset out of range",
                reason_code="ducklake_api.page_out_of_range",
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
            "schema": DUCKLAKE_API_SCHEMA,
            "operation": "query" if offset == 0 else "page",
            "handle_id": handle.handle_id,
            "handle_status": handle.status.value,
            "template_id": handle.template_id,
            "snapshot": handle.snapshot.to_dict(),
            "tenant_id": handle.tenant_id,
            "trust": handle.trust.value,
            "plane": handle.plane.value,
            "catalog_id": handle.catalog_id or None,
            "rows": page_rows,
            "row_count": len(page_rows),
            "total_row_count": total,
            "offset": offset,
            "page_size": page_sz,
            "has_more": next_token is not None,
            "next_page_token": next_token,
            "parameters_digest": handle.parameters_digest or None,
            "receipt": _public_receipt(handle.receipt)
            if handle.receipt is not None
            else None,
            "cancelled": handle.cancellation.is_cancelled,
            "bounded": True,
            "direct_authority_quack_access": False,
            "implementation_generation": DUCKLAKE_API_IMPLEMENTATION_GENERATION,
        }
        if handle.error is not None:
            body["error"] = handle.error
            body["reason_code"] = handle.error.get("reason_code")
        return redact_public_payload(body)

    def page(
        self,
        handle_id: str | None,
        page_token: str | None = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        handle = self.get_handle(str(handle_id or "").strip())
        if handle.operation not in {"query", "export"} and not handle.rows:
            raise DuckLakeAPIError(
                "handle does not support pagination",
                reason_code="ducklake_api.error",
            )
        if not page_token:
            offset = 0
        else:
            offset = self._tokens.parse(handle.handle_id, str(page_token))
        return self._query_response(handle, offset=offset)

    def status(self, handle_id: str | None, **_ignored: Any) -> dict[str, Any]:
        handle = self.get_handle(str(handle_id or "").strip())
        body = {
            "status": "ok",
            "schema": DUCKLAKE_API_SCHEMA,
            "operation": "status",
            **handle.public_status(),
            "implementation_generation": DUCKLAKE_API_IMPLEMENTATION_GENERATION,
        }
        return redact_public_payload(body)

    def cancel(
        self,
        handle_id: str | None,
        *,
        reason: str = "cancelled",
        **_ignored: Any,
    ) -> dict[str, Any]:
        if not handle_id or not str(handle_id).strip():
            raise DuckLakeAPIError(
                "handle_id is required",
                reason_code="ducklake_api.missing_handle",
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
            "schema": DUCKLAKE_API_SCHEMA,
            "operation": "cancel",
            "handle_id": handle.handle_id,
            "handle_status": handle.status.value,
            "cancelled": True,
            "idempotent_replay": already,
            "reason": safe_reason if handle.cancellation.is_cancelled else "cancelled",
            "plane": handle.plane.value,
            "bounded": True,
            "implementation_generation": DUCKLAKE_API_IMPLEMENTATION_GENERATION,
        }

    def export(
        self,
        template_id: str | None,
        params: Mapping[str, Any] | None = None,
        *,
        snapshot_id: SnapshotId | str | Mapping[str, Any] | int | None = None,
        tenant_id: str | None = None,
        trust: Any = qr.TrustClass.UNTRUSTED,
        format: ExportFormat | str = ExportFormat.JSON,
        location_hint: str = "exports/ducklake/",
        sql: str | None = None,
        row_source: Callable[..., Sequence[Mapping[str, Any]]] | None = None,
        store_generation: int | None = None,
        catalog_id: str | None = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        """Deterministic snapshot-bound export via allowlisted template."""

        if not template_id or not str(template_id).strip():
            raise DuckLakeAPIError(
                "template_id is required",
                reason_code="ducklake_api.missing_template_id",
            )
        try:
            qr.deny_arbitrary_sql(sql, template_id=template_id)
            if sql is not None and str(sql).strip():
                qc.deny_arbitrary_sql(str(sql))
        except (qr.QueryRegistryError, qc.SurfaceDenied, qc.QuackCatalogError) as exc:
            raise DuckLakeAPIError(
                "arbitrary SQL and denied surfaces are forbidden",
                reason_code=getattr(exc, "reason_code", "query.sql_surface_denied"),
            ) from exc
        if not tenant_id or not str(tenant_id).strip():
            raise DuckLakeAPIError(
                "tenant_id is required",
                reason_code="ducklake_api.missing_tenant",
            )
        if params:
            for key in params:
                if str(key).lower() in {"sql", "query", "raw_sql", "attach"}:
                    raise DuckLakeAPIError(
                        "arbitrary SQL and denied surfaces are forbidden",
                        reason_code="query.sql_surface_denied",
                    )

        snap = _parse_snapshot(snapshot_id, store_generation=store_generation)
        trust_cls = _parse_trust(trust)
        plane = self._select_query_plane(trust_cls)
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
            plane=plane,
            cancellation=cancel,
            page_size=DEFAULT_PAGE_SIZE,
            operation="export",
            catalog_id=str(catalog_id or "").strip(),
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
            # Hard cap export rows for reproducibility budgets.
            rows = [dict(r) for r in result.rows[:MAX_EXPORT_ROWS]]
            handle.rows = tuple(rows)
            handle.receipt = result.receipt
            handle.parameters_digest = result.receipt.parameters_digest

            # Deterministic job identity so repeated exports of one snapshot
            # produce byte-identical content digests.
            job_digest = content_identity(
                {
                    "template_id": handle.template_id,
                    "parameters_digest": result.receipt.parameters_digest,
                    "snapshot": snap.to_dict(),
                    "format": fmt.value,
                    "revision": "1",
                    "schema_version": "1",
                }
            )
            job_id = f"export-{job_digest.split(':', 1)[-1][:32]}"
            job = ExportJob(
                job_id=job_id,
                template_id=handle.template_id,
                parameters_digest=result.receipt.parameters_digest,
                schema_version="1",
                snapshot=snap,
                format=fmt,
                destination_policy=default_destination_policy(),
                revision="1",
                template_version=result.receipt.template_version,
                location_hint=location_hint or "exports/ducklake/",
                column_policy=self._registry.get(handle.template_id).column_policy,
                created_at=now,
            )
            export_result = self._exporter.export_rows(rows, job)
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
                "projected_columns": list(export_result.artifact.projected_columns),
                "status": export_result.status.value,
                "read_only": True,
                "non_authoritative": True,
                "mutated_source": False,
                "snapshot": snap.to_dict(),
                "plane": plane.value,
                "export_id": getattr(export_result.receipt, "export_id", "")
                or export_result.receipt.to_dict().get("export_id", ""),
                "reproducible": True,
                "bounded": True,
            }
            handle.status = HandleStatus.SUCCEEDED
            handle.updated_at = self._clock()
        except qr.QueryRegistryError as exc:
            handle.status = HandleStatus.DENIED
            handle.error = sanitize_public_error(exc)
            handle.updated_at = self._clock()
            raise DuckLakeAPIError(
                handle.error["error"],
                reason_code=handle.error["reason_code"],
            ) from exc
        except DuckLakeAPIError:
            raise
        except Exception as exc:
            handle.status = HandleStatus.FAILED
            handle.error = sanitize_public_error(
                exc, reason_code="ducklake_api.export_failed"
            )
            handle.updated_at = self._clock()
            raise DuckLakeAPIError(
                handle.error["error"],
                reason_code="ducklake_api.export_failed",
            ) from exc

        return redact_public_payload(
            {
                "status": "ok",
                "schema": DUCKLAKE_API_SCHEMA,
                "operation": "export",
                "handle_id": handle.handle_id,
                "handle_status": handle.status.value,
                "template_id": handle.template_id,
                "snapshot": snap.to_dict(),
                "tenant_id": tenant,
                "trust": trust_cls.value,
                "plane": plane.value,
                "catalog_id": handle.catalog_id or None,
                "export": handle.export_summary,
                "receipt": _public_receipt(handle.receipt)
                if handle.receipt is not None
                else None,
                "direct_authority_quack_access": False,
                "implementation_generation": DUCKLAKE_API_IMPLEMENTATION_GENERATION,
            }
        )


def open_default_api(
    *,
    include_lake_templates: bool = True,
    include_builtin_query_templates: bool = True,
    backend: Any | None = None,
    page_token_secret: bytes | None = None,
) -> DuckLakeQueryAPI:
    """Create an API with default allowlisted templates and empty catalog manager."""

    return DuckLakeQueryAPI(
        include_lake_templates=include_lake_templates,
        include_builtin_query_templates=include_builtin_query_templates,
        backend=backend,
        page_token_secret=page_token_secret,
    )


# ---------------------------------------------------------------------------
# Process-local default API
# ---------------------------------------------------------------------------

_DEFAULT_API: DuckLakeQueryAPI | None = None
_DEFAULT_API_LOCK = threading.Lock()


def get_default_api() -> DuckLakeQueryAPI:
    global _DEFAULT_API
    with _DEFAULT_API_LOCK:
        if _DEFAULT_API is None:
            _DEFAULT_API = open_default_api()
        return _DEFAULT_API


def set_default_api(api: DuckLakeQueryAPI | None) -> None:
    global _DEFAULT_API
    with _DEFAULT_API_LOCK:
        _DEFAULT_API = api


def _ok_or_error(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return fn()
    except DuckLakeAPIError as exc:
        return sanitize_public_error(exc)
    except qr.QueryRegistryError as exc:
        return sanitize_public_error(exc)
    except qc.QuackCatalogError as exc:
        return sanitize_public_error(exc)
    except Exception as exc:  # pragma: no cover - defensive
        return sanitize_public_error(exc)


# ---------------------------------------------------------------------------
# Convenience module-level entrypoints
# ---------------------------------------------------------------------------


def discover_catalogs(**kwargs: Any) -> dict[str, Any]:
    api = kwargs.pop("api", None) or get_default_api()
    return _ok_or_error(lambda: api.discover_catalogs(**kwargs))


def discover_datasets(**kwargs: Any) -> dict[str, Any]:
    api = kwargs.pop("api", None) or get_default_api()
    return _ok_or_error(lambda: api.discover_datasets(**kwargs))


def select_snapshot(**kwargs: Any) -> dict[str, Any]:
    api = kwargs.pop("api", None) or get_default_api()
    return _ok_or_error(lambda: api.select_snapshot(**kwargs))


def list_templates(**kwargs: Any) -> dict[str, Any]:
    api = kwargs.pop("api", None) or get_default_api()
    return _ok_or_error(lambda: api.list_templates(**kwargs))


def explain(
    template_id: str | None = None,
    parameters: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    api = kwargs.pop("api", None) or get_default_api()
    params = kwargs.pop("params", None)
    bound = params if params is not None else parameters
    return _ok_or_error(lambda: api.explain(template_id, bound, **kwargs))


def query(
    template_id: str | None = None,
    parameters: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    api = kwargs.pop("api", None) or get_default_api()
    params = kwargs.pop("params", None)
    bound = params if params is not None else parameters
    return _ok_or_error(lambda: api.query(template_id, bound, **kwargs))


def page(handle_id: str | None = None, page_token: str | None = None, **kwargs: Any) -> dict[str, Any]:
    api = kwargs.pop("api", None) or get_default_api()
    return _ok_or_error(lambda: api.page(handle_id, page_token, **kwargs))


def status(handle_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
    api = kwargs.pop("api", None) or get_default_api()
    return _ok_or_error(lambda: api.status(handle_id, **kwargs))


def cancel(handle_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
    api = kwargs.pop("api", None) or get_default_api()
    return _ok_or_error(lambda: api.cancel(handle_id, **kwargs))


def export(
    template_id: str | None = None,
    parameters: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    api = kwargs.pop("api", None) or get_default_api()
    params = kwargs.pop("params", None)
    bound = params if params is not None else parameters
    return _ok_or_error(lambda: api.export(template_id, bound, **kwargs))
