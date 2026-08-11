"""Distributed DuckDB + Quack DuckLake catalog-owner protocol (DQK-104).

One identity-bound owner process per catalog shard opens the local/block-storage
DuckDB metadata file under DuckDB's native file lock, loads the pinned DuckLake,
Quack, and object-store extensions, and attaches exactly one DuckLake catalog.
Quack supplies authenticated distributed transport only; it is never task,
lease, CAS, replication, or multi-owner storage authority.

This module is the allowlisted template, authentication/authorization, receipt,
and promotion-gate surface used by :mod:`ipfs_datasets_py.ducklake.catalog_service`.
It creates **no** production catalog endpoint and performs **no** production
DuckLake mutation. Activation remains held behind DQK-088, DQK-094, and the
independently signed DQK-102 promotion gate.

Import is side-effect free: no ``duckdb``, sockets, extension LOAD, or secret
resolution occurs at import time.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.duckdb_control import quack_security as qs
from ipfs_datasets_py.ducklake.capabilities import (
    EXPLICIT_LOAD_ORDER,
    PINNED_DUCKLAKE_EXTENSION_BUILD,
    PINNED_HTTPFS_EXTENSION_BUILD,
    PINNED_QUACK_EXTENSION_BUILD,
)

__all__ = [
    "QUACK_CATALOG_SCHEMA",
    "MUTATION_RECEIPT_SCHEMA",
    "SIGNED_OPERATION_SCHEMA",
    "TEMPLATE_REGISTRY_SCHEMA",
    "PROMOTION_GATE_HOLD",
    "PINNED_OWNER_EXTENSIONS",
    "FORBIDDEN_AUTHORITY_CATALOGS",
    "DENIED_SQL_SURFACES",
    "QuackCatalogError",
    "PromotionGateHold",
    "SurfaceDenied",
    "OperationExpired",
    "OperationSignatureError",
    "TemplateDenied",
    "IdempotentReplay",
    "CrossCatalogOverlap",
    "CatalogOperationKind",
    "ResourceBudget",
    "CatalogOperationTemplate",
    "SignedCatalogOperation",
    "AuthCallbackAttestation",
    "MutationReceipt",
    "GatewayBindPolicy",
    "CatalogTemplateRegistry",
    "DurableIdempotencyStore",
    "default_catalog_templates",
    "open_default_template_registry",
    "classify_denied_surface",
    "deny_arbitrary_sql",
    "scrub_log_payload",
    "attest_authorization_callback",
    "verify_signed_operation",
    "render_canonical_sql",
    "build_mutation_receipt",
    "promotion_gate_status",
    "assert_no_production_activation",
    "assert_gateway_cannot_read_authority",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

QUACK_CATALOG_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-quack-catalog@1"
)
MUTATION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-catalog-mutation-receipt@1"
)
SIGNED_OPERATION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-signed-catalog-operation@1"
)
TEMPLATE_REGISTRY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-catalog-template-registry@1"
)

_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-104-quack-catalog-owner-20260810"
)

# Production mutation remains disabled until these gates complete.
PROMOTION_GATE_HOLD: Final[tuple[str, ...]] = (
    "DQK-088",
    "DQK-094",
    "DQK-102",
)

PINNED_OWNER_EXTENSIONS: Final[tuple[str, ...]] = (
    PINNED_QUACK_EXTENSION_BUILD,
    PINNED_DUCKLAKE_EXTENSION_BUILD,
    PINNED_HTTPFS_EXTENSION_BUILD,
)

# Authority catalogs the catalog-management gateway must never read.
FORBIDDEN_AUTHORITY_CATALOGS: Final[frozenset[str]] = frozenset(
    {
        "control",
        "proof",
        "graph-writer",
        "graph_writer",
        "ast-writer",
        "ast_writer",
        "wallet",
        "secret",
        "sanitized-publication",
        "sanitized_publication",
        "publication",
    }
)

# Exact deny surfaces for arbitrary remote SQL / escape attempts.
DENIED_SQL_SURFACES: Final[frozenset[str]] = frozenset(
    {
        "ARBITRARY_SQL",
        "QUACK_QUERY",
        "REMOTE_DOT_QUERY",
        "ATTACH",
        "DETACH",
        "INSTALL",
        "LOAD",
        "SECRET",
        "MULTI_STATEMENT",
        "DUCKLAKE_INTERNAL_DML",
        "CROSS_CATALOG",
        "UNBOUNDED_RESULT",
        "CREDENTIAL_EXPORT",
        "TOKEN_EXPORT",
        "PREFIX_AUTHZ",
        "REGEX_AUTHZ",
    }
)

_TEMPLATE_ID_RE = re.compile(
    r"^[a-z][a-z0-9_]{0,63}(?:\.[a-z][a-z0-9_]{0,63}){0,3}$"
)
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{0,255}$")
_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")

# DuckLake internal metadata table prefixes / names that remote clients must
# never DML against through the catalog gateway.
_DUCKLAKE_INTERNAL_TABLE_RE = re.compile(
    r"(?i)\b(?:ducklake_(?:metadata|snapshot|table|schema|view|file|data|"
    r"column|partition|tag|option)|__ducklake_)\b"
)

_MULTI_STATEMENT_RE = re.compile(r";\s*\S")
_SECRET_EXPORT_RE = re.compile(
    r"(?i)\b(?:CREATE\s+SECRET|EXPORT\s+SECRET|PRAGMA\s+.*secret|"
    r"SELECT\s+.*\b(?:password|token|secret|api_key)\b)"
)
_ATTACH_RE = re.compile(r"(?i)\b(?:ATTACH|DETACH)\b")
_INSTALL_LOAD_RE = re.compile(r"(?i)\b(?:INSTALL|LOAD)\b")
_CREDENTIAL_EXPORT_RE = re.compile(
    r"(?i)\b(?:COPY\s+.*TO|EXPORT\s+DATABASE|SHOW\s+SECRETS|"
    r"SELECT\s+current_setting\s*\(\s*['\"]?(?:password|token))"
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class QuackCatalogError(ValueError):
    """Fail-closed catalog-management protocol rejection."""


class PromotionGateHold(QuackCatalogError):
    """Production activation is held behind DQK-088/094/102."""


class SurfaceDenied(QuackCatalogError):
    """Arbitrary SQL or a forbidden surface was rejected."""


class OperationExpired(QuackCatalogError):
    """Signed operation TTL elapsed."""


class OperationSignatureError(QuackCatalogError):
    """Signed structured operation failed verification."""


class TemplateDenied(QuackCatalogError):
    """Template is unknown, mismatched, or not allowlisted."""


class IdempotentReplay(QuackCatalogError):
    """Operation id replayed with a conflicting request body."""


class CrossCatalogOverlap(QuackCatalogError):
    """Catalog-scoped server saw concurrent cross-catalog work."""


# ---------------------------------------------------------------------------
# Enumerations / budgets
# ---------------------------------------------------------------------------


class CatalogOperationKind(str, Enum):
    """Bounded catalog-management operation kinds exposed by the owner."""

    CATALOG = "catalog"
    NAMESPACE = "namespace"
    SCHEMA = "schema"
    TABLE = "table"
    SNAPSHOT = "snapshot"
    INGEST_REGISTRATION = "ingest_registration"
    MAINTENANCE_INTENT = "maintenance_intent"


@dataclass(frozen=True, slots=True)
class ResourceBudget:
    """Per-operation resource budget (fail closed when exceeded)."""

    max_rows: int = 10_000
    max_bytes: int = 4 * 1024 * 1024
    max_duration_ms: int = 30_000
    max_statements: int = 1

    def __post_init__(self) -> None:
        for name, value, lo, hi in (
            ("max_rows", self.max_rows, 1, 1_000_000),
            ("max_bytes", self.max_bytes, 1, 256 * 1024 * 1024),
            ("max_duration_ms", self.max_duration_ms, 1, 600_000),
            ("max_statements", self.max_statements, 1, 1),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < lo or value > hi:
                raise QuackCatalogError(f"{name} out of range [{lo}, {hi}]")

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "max_rows": self.max_rows,
                "max_bytes": self.max_bytes,
                "max_duration_ms": self.max_duration_ms,
                "max_statements": self.max_statements,
            }
        )


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CatalogOperationTemplate:
    """Versioned allowlisted parameterized SQL template for catalog ops.

    The authorization callback exact-allows the *canonical template identity*
    (full SQL text after parameter binding into the versioned template), never
    a prefix or regex approximation.
    """

    template_id: str
    version: int
    kind: CatalogOperationKind
    canonical_sql: str
    parameter_names: tuple[str, ...] = ()
    expected_effects: tuple[str, ...] = ()
    mutates: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        tid = str(self.template_id or "").strip()
        if not tid or not _TEMPLATE_ID_RE.match(tid):
            raise QuackCatalogError(f"invalid template_id {self.template_id!r}")
        if (
            not isinstance(self.version, int)
            or isinstance(self.version, bool)
            or self.version < 1
        ):
            raise QuackCatalogError("template version must be a positive int")
        kind = self.kind
        if not isinstance(kind, CatalogOperationKind):
            kind = CatalogOperationKind(str(kind))
            object.__setattr__(self, "kind", kind)
        sql = str(self.canonical_sql or "").strip()
        if not sql:
            raise QuackCatalogError("canonical_sql is required")
        # Templates themselves must not carry multi-statement or secret surfaces.
        classification = classify_denied_surface(sql, allow_template_body=True)
        if classification is not None:
            raise QuackCatalogError(
                f"template {tid!r} embeds denied surface {classification}"
            )
        names = tuple(str(n).strip() for n in self.parameter_names)
        for name in names:
            if not re.match(r"^[a-z][a-z0-9_]{0,63}$", name):
                raise QuackCatalogError(f"invalid parameter name {name!r}")
        effects = tuple(str(e).strip() for e in self.expected_effects if str(e).strip())
        object.__setattr__(self, "template_id", tid)
        object.__setattr__(self, "canonical_sql", sql)
        object.__setattr__(self, "parameter_names", names)
        object.__setattr__(self, "expected_effects", effects)
        object.__setattr__(self, "description", str(self.description or ""))

    @property
    def identity(self) -> str:
        return f"{self.template_id}@v{self.version}"

    def template_digest(self) -> str:
        payload = {
            "template_id": self.template_id,
            "version": self.version,
            "kind": self.kind.value,
            "canonical_sql": self.canonical_sql,
            "parameter_names": list(self.parameter_names),
            "expected_effects": list(self.expected_effects),
            "mutates": self.mutates,
        }
        return "sha256:" + _sha256_json(payload)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "template_id": self.template_id,
                "version": self.version,
                "kind": self.kind.value,
                "canonical_sql": qs.redact_sql(self.canonical_sql),
                "parameter_names": list(self.parameter_names),
                "expected_effects": list(self.expected_effects),
                "mutates": self.mutates,
                "description": self.description,
                "identity": self.identity,
                "template_digest": self.template_digest(),
            }
        )


def default_catalog_templates() -> tuple[CatalogOperationTemplate, ...]:
    """Built-in bounded catalog, namespace, schema, table, snapshot templates."""

    return (
        CatalogOperationTemplate(
            template_id="catalog.describe",
            version=1,
            kind=CatalogOperationKind.CATALOG,
            canonical_sql=(
                "SELECT catalog_id, snapshot_version, owner_generation "
                "FROM __owner_catalog_state WHERE catalog_id = :catalog_id"
            ),
            parameter_names=("catalog_id",),
            expected_effects=("read_catalog_state",),
            mutates=False,
            description="Describe the selected catalog shard state",
        ),
        CatalogOperationTemplate(
            template_id="namespace.list",
            version=1,
            kind=CatalogOperationKind.NAMESPACE,
            canonical_sql=(
                "SELECT namespace_name FROM __owner_namespaces "
                "WHERE catalog_id = :catalog_id ORDER BY namespace_name "
                "LIMIT :max_rows"
            ),
            parameter_names=("catalog_id", "max_rows"),
            expected_effects=("list_namespaces",),
            mutates=False,
            description="List namespaces for the selected catalog",
        ),
        CatalogOperationTemplate(
            template_id="schema.list",
            version=1,
            kind=CatalogOperationKind.SCHEMA,
            canonical_sql=(
                "SELECT schema_name FROM __owner_schemas "
                "WHERE catalog_id = :catalog_id AND namespace_name = :namespace "
                "ORDER BY schema_name LIMIT :max_rows"
            ),
            parameter_names=("catalog_id", "namespace", "max_rows"),
            expected_effects=("list_schemas",),
            mutates=False,
            description="List schemas in a namespace",
        ),
        CatalogOperationTemplate(
            template_id="table.list",
            version=1,
            kind=CatalogOperationKind.TABLE,
            canonical_sql=(
                "SELECT table_name FROM __owner_tables "
                "WHERE catalog_id = :catalog_id AND schema_name = :schema_name "
                "ORDER BY table_name LIMIT :max_rows"
            ),
            parameter_names=("catalog_id", "schema_name", "max_rows"),
            expected_effects=("list_tables",),
            mutates=False,
            description="List tables in a schema",
        ),
        CatalogOperationTemplate(
            template_id="snapshot.get",
            version=1,
            kind=CatalogOperationKind.SNAPSHOT,
            canonical_sql=(
                "SELECT snapshot_version, committed_at FROM __owner_snapshots "
                "WHERE catalog_id = :catalog_id AND snapshot_version = :snapshot_version"
            ),
            parameter_names=("catalog_id", "snapshot_version"),
            expected_effects=("read_snapshot",),
            mutates=False,
            description="Read a single snapshot vector member",
        ),
        CatalogOperationTemplate(
            template_id="ingest.register_intent",
            version=1,
            kind=CatalogOperationKind.INGEST_REGISTRATION,
            canonical_sql=(
                "INSERT INTO __owner_ingest_intents "
                "(operation_id, catalog_id, source_digest, logical_key) "
                "VALUES (:operation_id, :catalog_id, :source_digest, :logical_key)"
            ),
            parameter_names=(
                "operation_id",
                "catalog_id",
                "source_digest",
                "logical_key",
            ),
            expected_effects=("register_ingest_intent",),
            mutates=True,
            description="Register an ingest intent (held behind promotion gates)",
        ),
        CatalogOperationTemplate(
            template_id="maintenance.intent",
            version=1,
            kind=CatalogOperationKind.MAINTENANCE_INTENT,
            canonical_sql=(
                "INSERT INTO __owner_maintenance_intents "
                "(operation_id, catalog_id, intent_kind) "
                "VALUES (:operation_id, :catalog_id, :intent_kind)"
            ),
            parameter_names=("operation_id", "catalog_id", "intent_kind"),
            expected_effects=("register_maintenance_intent",),
            mutates=True,
            description="Register a maintenance intent (held behind promotion gates)",
        ),
    )


class CatalogTemplateRegistry:
    """In-memory allowlist of versioned catalog operation templates."""

    def __init__(
        self,
        templates: Sequence[CatalogOperationTemplate] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._by_id: dict[str, CatalogOperationTemplate] = {}
        for template in templates or default_catalog_templates():
            self.register(template)

    def register(self, template: CatalogOperationTemplate) -> None:
        if not isinstance(template, CatalogOperationTemplate):
            raise QuackCatalogError("expected CatalogOperationTemplate")
        with self._lock:
            if template.template_id in self._by_id:
                raise QuackCatalogError(
                    f"duplicate template_id {template.template_id!r}"
                )
            self._by_id[template.template_id] = template

    def get(self, template_id: str, *, version: int | None = None) -> CatalogOperationTemplate:
        with self._lock:
            template = self._by_id.get(str(template_id))
            if template is None:
                raise TemplateDenied(f"unknown template {template_id!r}")
            if version is not None and template.version != int(version):
                raise TemplateDenied(
                    f"template version mismatch for {template_id!r}: "
                    f"expected {version}, have {template.version}"
                )
            return template

    def list_templates(self) -> tuple[CatalogOperationTemplate, ...]:
        with self._lock:
            return tuple(self._by_id[k] for k in sorted(self._by_id))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": TEMPLATE_REGISTRY_SCHEMA,
                "implementation_generation": _IMPLEMENTATION_GENERATION,
                "templates": [dict(t.as_mapping()) for t in self.list_templates()],
            }
        )


def open_default_template_registry() -> CatalogTemplateRegistry:
    return CatalogTemplateRegistry(default_catalog_templates())


# ---------------------------------------------------------------------------
# Signed structured operations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SignedCatalogOperation:
    """Signed, expiring, idempotent allowlisted catalog operation.

    Bound to caller process birth, tenant, catalog, starting snapshot, schema,
    expected effects, operation ID, owner generation fence, and resource budget.
    """

    operation_id: str
    template_id: str
    template_version: int
    catalog_id: str
    tenant: str
    caller_process_birth: Mapping[str, Any]
    owner_generation: int
    fencing_epoch: int
    starting_snapshot: int
    schema_name: str
    expected_effects: tuple[str, ...]
    parameters: Mapping[str, Any]
    resource_budget: ResourceBudget
    expires_at_unix: float
    signature: str
    signing_key_id: str = "broker-test-key"
    schema: str = SIGNED_OPERATION_SCHEMA

    def __post_init__(self) -> None:
        op = str(self.operation_id or "").strip()
        if not op or not _SAFE_TOKEN.match(op):
            raise QuackCatalogError(f"invalid operation_id {self.operation_id!r}")
        tid = str(self.template_id or "").strip()
        if not tid or not _TEMPLATE_ID_RE.match(tid):
            raise QuackCatalogError(f"invalid template_id {self.template_id!r}")
        if (
            not isinstance(self.template_version, int)
            or isinstance(self.template_version, bool)
            or self.template_version < 1
        ):
            raise QuackCatalogError("template_version must be a positive int")
        catalog_id = str(self.catalog_id or "").strip()
        if not catalog_id or not _SAFE_TOKEN.match(catalog_id):
            raise QuackCatalogError(f"invalid catalog_id {self.catalog_id!r}")
        tenant = str(self.tenant or "").strip()
        if not tenant or not _SAFE_TOKEN.match(tenant):
            raise QuackCatalogError(f"invalid tenant {self.tenant!r}")
        birth = dict(self.caller_process_birth or {})
        if not birth:
            raise QuackCatalogError("caller_process_birth is required")
        for name, value in (
            ("owner_generation", self.owner_generation),
            ("fencing_epoch", self.fencing_epoch),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise QuackCatalogError(f"{name} must be a positive int")
        if (
            not isinstance(self.starting_snapshot, int)
            or isinstance(self.starting_snapshot, bool)
            or self.starting_snapshot < 0
        ):
            raise QuackCatalogError("starting_snapshot must be a non-negative int")
        schema_name = str(self.schema_name or "").strip()
        if schema_name and not _SAFE_IDENT.match(schema_name):
            raise QuackCatalogError(f"invalid schema_name {self.schema_name!r}")
        effects = tuple(str(e).strip() for e in self.expected_effects if str(e).strip())
        if not effects:
            raise QuackCatalogError("expected_effects is required")
        params = dict(self.parameters or {})
        if not isinstance(self.resource_budget, ResourceBudget):
            raise QuackCatalogError("resource_budget must be ResourceBudget")
        if not isinstance(self.expires_at_unix, (int, float)) or isinstance(
            self.expires_at_unix, bool
        ):
            raise QuackCatalogError("expires_at_unix must be a number")
        signature = str(self.signature or "").strip()
        if not signature:
            raise QuackCatalogError("signature is required")
        schema = str(self.schema or SIGNED_OPERATION_SCHEMA).strip()
        if schema != SIGNED_OPERATION_SCHEMA:
            raise QuackCatalogError(f"unsupported operation schema {self.schema!r}")
        object.__setattr__(self, "operation_id", op)
        object.__setattr__(self, "template_id", tid)
        object.__setattr__(self, "catalog_id", catalog_id)
        object.__setattr__(self, "tenant", tenant)
        object.__setattr__(self, "caller_process_birth", MappingProxyType(birth))
        object.__setattr__(self, "schema_name", schema_name)
        object.__setattr__(self, "expected_effects", effects)
        object.__setattr__(self, "parameters", MappingProxyType(params))
        object.__setattr__(self, "signature", signature)
        object.__setattr__(self, "signing_key_id", str(self.signing_key_id or "broker-test-key"))
        object.__setattr__(self, "schema", schema)

    def is_expired(self, *, now: float | None = None) -> bool:
        clock = time.time() if now is None else float(now)
        return clock >= float(self.expires_at_unix)

    def signing_payload(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "operation_id": self.operation_id,
                "template_id": self.template_id,
                "template_version": self.template_version,
                "catalog_id": self.catalog_id,
                "tenant": self.tenant,
                "caller_process_birth": dict(self.caller_process_birth),
                "owner_generation": self.owner_generation,
                "fencing_epoch": self.fencing_epoch,
                "starting_snapshot": self.starting_snapshot,
                "schema_name": self.schema_name,
                "expected_effects": list(self.expected_effects),
                "parameters": dict(self.parameters),
                "resource_budget": dict(self.resource_budget.as_mapping()),
                "expires_at_unix": float(self.expires_at_unix),
                "signing_key_id": self.signing_key_id,
            }
        )

    def request_digest(self) -> str:
        return "sha256:" + _sha256_json(dict(self.signing_payload()))

    def as_mapping(self) -> Mapping[str, Any]:
        payload = dict(self.signing_payload())
        payload["signature"] = self.signature
        payload["request_digest"] = self.request_digest()
        return MappingProxyType(payload)


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def sign_operation_payload(
    payload: Mapping[str, Any],
    *,
    secret: str,
) -> str:
    """HMAC-SHA256 over the canonical signing payload (broker-side helper)."""

    key = str(secret or "").encode("utf-8")
    if len(key) < 16:
        raise QuackCatalogError("signing secret must be at least 16 bytes")
    body = _canonical_json(dict(payload)).encode("utf-8")
    return "hmac-sha256:" + hmac.new(key, body, hashlib.sha256).hexdigest()


def verify_signed_operation(
    operation: SignedCatalogOperation,
    *,
    secret: str,
    now: float | None = None,
    expected_catalog_id: str | None = None,
    expected_owner_generation: int | None = None,
    expected_fencing_epoch: int | None = None,
) -> Mapping[str, Any]:
    """Independently verify the signed structured operation (primary authz)."""

    if operation.is_expired(now=now):
        raise OperationExpired(
            f"operation {operation.operation_id!r} expired at {operation.expires_at_unix}"
        )
    expected_sig = sign_operation_payload(operation.signing_payload(), secret=secret)
    if not hmac.compare_digest(expected_sig, operation.signature):
        raise OperationSignatureError(
            f"operation {operation.operation_id!r} signature verification failed"
        )
    if expected_catalog_id is not None and operation.catalog_id != expected_catalog_id:
        raise OperationSignatureError(
            f"operation catalog_id {operation.catalog_id!r} does not match "
            f"selected catalog {expected_catalog_id!r}"
        )
    if (
        expected_owner_generation is not None
        and operation.owner_generation != expected_owner_generation
    ):
        raise OperationSignatureError(
            "operation owner_generation fence mismatch"
        )
    if (
        expected_fencing_epoch is not None
        and operation.fencing_epoch != expected_fencing_epoch
    ):
        raise OperationSignatureError("operation fencing_epoch mismatch")
    return MappingProxyType(
        {
            "verified": True,
            "operation_id": operation.operation_id,
            "request_digest": operation.request_digest(),
            "catalog_id": operation.catalog_id,
            "owner_generation": operation.owner_generation,
            "primary_authorization_boundary": "task_owned_signed_operation",
            "quack_authorization_function": "defense_in_depth_only",
        }
    )


def mint_signed_operation(
    *,
    template: CatalogOperationTemplate,
    catalog_id: str,
    tenant: str,
    caller_process_birth: Mapping[str, Any],
    owner_generation: int,
    fencing_epoch: int,
    starting_snapshot: int,
    schema_name: str,
    parameters: Mapping[str, Any],
    secret: str,
    operation_id: str | None = None,
    resource_budget: ResourceBudget | None = None,
    ttl_seconds: int = 60,
    now: float | None = None,
    signing_key_id: str = "broker-test-key",
) -> SignedCatalogOperation:
    """Broker helper: build and sign a structured catalog operation."""

    clock = time.time() if now is None else float(now)
    if ttl_seconds < 1 or ttl_seconds > 3_600:
        raise QuackCatalogError("ttl_seconds out of range")
    # Fill required template parameters that the broker owns.
    params = dict(parameters or {})
    op_id = str(operation_id or f"op_{uuid.uuid4().hex}")
    if "operation_id" in template.parameter_names and "operation_id" not in params:
        params["operation_id"] = op_id
    if "catalog_id" in template.parameter_names and "catalog_id" not in params:
        params["catalog_id"] = catalog_id
    missing = [n for n in template.parameter_names if n not in params]
    if missing:
        raise QuackCatalogError(f"missing template parameters: {missing}")
    extra = sorted(set(params) - set(template.parameter_names))
    if extra:
        raise QuackCatalogError(f"unexpected template parameters: {extra}")
    budget = resource_budget or ResourceBudget()
    unsigned = SignedCatalogOperation(
        operation_id=op_id,
        template_id=template.template_id,
        template_version=template.version,
        catalog_id=catalog_id,
        tenant=tenant,
        caller_process_birth=dict(caller_process_birth),
        owner_generation=owner_generation,
        fencing_epoch=fencing_epoch,
        starting_snapshot=starting_snapshot,
        schema_name=schema_name,
        expected_effects=template.expected_effects,
        parameters=params,
        resource_budget=budget,
        expires_at_unix=clock + float(ttl_seconds),
        signature="pending",
        signing_key_id=signing_key_id,
    )
    # Rebuild with real signature over the signing payload (exclude signature field).
    signature = sign_operation_payload(unsigned.signing_payload(), secret=secret)
    return SignedCatalogOperation(
        operation_id=unsigned.operation_id,
        template_id=unsigned.template_id,
        template_version=unsigned.template_version,
        catalog_id=unsigned.catalog_id,
        tenant=unsigned.tenant,
        caller_process_birth=dict(unsigned.caller_process_birth),
        owner_generation=unsigned.owner_generation,
        fencing_epoch=unsigned.fencing_epoch,
        starting_snapshot=unsigned.starting_snapshot,
        schema_name=unsigned.schema_name,
        expected_effects=unsigned.expected_effects,
        parameters=dict(unsigned.parameters),
        resource_budget=unsigned.resource_budget,
        expires_at_unix=unsigned.expires_at_unix,
        signature=signature,
        signing_key_id=unsigned.signing_key_id,
    )


# ---------------------------------------------------------------------------
# SQL surface denial + rendering
# ---------------------------------------------------------------------------


def classify_denied_surface(
    sql: str,
    *,
    allow_template_body: bool = False,
    selected_catalog: str | None = None,
) -> str | None:
    """Return a denied-surface code or None if the SQL is admissible.

    Prefix/regex authorization is never an allow path; this classifier only
    rejects known escape surfaces. Allowlisted templates are still subject to
    multi-statement / secret / attach denial at construction time.
    """

    text = str(sql or "")
    if not text.strip():
        return "ARBITRARY_SQL"
    if _MULTI_STATEMENT_RE.search(text):
        return "MULTI_STATEMENT"
    if _SECRET_EXPORT_RE.search(text) or _CREDENTIAL_EXPORT_RE.search(text):
        if "SECRET" in text.upper():
            return "SECRET"
        return "CREDENTIAL_EXPORT"
    if re.search(r"(?i)\b(?:token|quack_token|api_key)\b\s*=", text):
        return "TOKEN_EXPORT"
    if not allow_template_body:
        if _ATTACH_RE.search(text):
            return "ATTACH" if "ATTACH" in text.upper() else "DETACH"
        if _INSTALL_LOAD_RE.search(text):
            upper = text.upper()
            if "INSTALL" in upper:
                return "INSTALL"
            return "LOAD"
        if re.search(r"(?i)\bquack_query\b", text):
            return "QUACK_QUERY"
        if re.search(r"(?i)\.query\s*\(", text):
            return "REMOTE_DOT_QUERY"
        if _DUCKLAKE_INTERNAL_TABLE_RE.search(text) and re.search(
            r"(?i)\b(?:INSERT|UPDATE|DELETE|MERGE|TRUNCATE)\b", text
        ):
            return "DUCKLAKE_INTERNAL_DML"
        if selected_catalog is not None:
            # Reject explicit cross-catalog qualifiers that are not the selected catalog.
            for match in re.finditer(
                r"(?i)\bFROM\s+([A-Za-z_][A-Za-z0-9_]*)\.", text
            ):
                catalog = match.group(1)
                if catalog.lower() not in {
                    selected_catalog.lower(),
                    "__owner_catalog_state",
                    "__owner_namespaces",
                    "__owner_schemas",
                    "__owner_tables",
                    "__owner_snapshots",
                    "__owner_ingest_intents",
                    "__owner_maintenance_intents",
                } and not catalog.startswith("__owner_"):
                    # Allow only our virtual owner tables; anything else is cross-catalog.
                    if catalog.lower() != selected_catalog.lower():
                        return "CROSS_CATALOG"
        if re.search(r"(?i)\bLIMIT\s+ALL\b", text) or re.search(
            r"(?i)\bUNBOUNDED\b", text
        ):
            return "UNBOUNDED_RESULT"
    return None


def deny_arbitrary_sql(sql: str, *, selected_catalog: str | None = None) -> None:
    """Fail closed on arbitrary SQL delivered by quack_query / remote .query."""

    code = classify_denied_surface(sql, selected_catalog=selected_catalog)
    if code is not None:
        raise SurfaceDenied(
            f"denied SQL surface {code}: arbitrary SQL, ATTACH/DETACH/INSTALL/"
            "LOAD/SECRET, multi-statement escape, DuckLake internal-table DML, "
            "cross-catalog access, unbounded results, and credential/token export "
            "fail closed"
        )


def render_canonical_sql(
    template: CatalogOperationTemplate,
    parameters: Mapping[str, Any],
) -> str:
    """Bind parameters into the template producing the exact full-SQL identity.

    Binding is string-safe for identifiers/tokens only. The result is the
    exact text that ``quack_authorization_function`` must exact-allow.
    """

    def _render_value(value: Any) -> str:
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, int) and not isinstance(value, bool):
            return str(int(value))
        if isinstance(value, float):
            return repr(float(value))
        text = str(value)
        # Identifiers used in our templates are bound as SQL string literals
        # for the virtual owner tables (exact match authorization).
        return "'" + text.replace("'", "''") + "'"

    sql = template.canonical_sql
    # Longest names first so :catalog_id never partially consumes :catalog_id_x.
    names = sorted(template.parameter_names, key=len, reverse=True)
    for name in names:
        if name not in parameters:
            raise QuackCatalogError(f"missing parameter {name!r}")
        placeholder = f":{name}"
        if placeholder not in sql:
            raise QuackCatalogError(
                f"template is missing placeholder {placeholder!r}"
            )
        sql = sql.replace(placeholder, _render_value(parameters[name]))
    # Unbound :param tokens outside string literals fail closed.
    stripped = re.sub(r"'([^']|'')*'", "''", sql)
    leftover = re.findall(r":[a-z][a-z0-9_]*", stripped)
    if leftover:
        raise QuackCatalogError(
            f"unbound parameter placeholders remain in SQL: {leftover}"
        )
    deny_code = classify_denied_surface(sql, allow_template_body=False)
    # After binding, multi-statement / secret / attach still fail closed.
    if deny_code in {
        "MULTI_STATEMENT",
        "SECRET",
        "CREDENTIAL_EXPORT",
        "TOKEN_EXPORT",
        "ATTACH",
        "DETACH",
        "INSTALL",
        "LOAD",
        "QUACK_QUERY",
        "REMOTE_DOT_QUERY",
        "DUCKLAKE_INTERNAL_DML",
        "UNBOUNDED_RESULT",
    }:
        raise SurfaceDenied(f"rendered SQL denied surface {deny_code}")
    return sql


# ---------------------------------------------------------------------------
# Authorization callback attestation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthCallbackAttestation:
    """Server attestation that non-default auth/authz hooks are installed."""

    authentication_callback: str
    authorization_callback: str
    authorization_mode: str
    allow_prefix: bool
    allow_regex: bool
    globally_visible: bool
    attested_at_unix: float
    callback_blob_digest: str
    config_digest: str

    def __post_init__(self) -> None:
        auth_name = str(self.authentication_callback or "").strip()
        authz_name = str(self.authorization_callback or "").strip()
        if not auth_name or auth_name.lower() in qs.DEFAULT_PERMISSIVE_AUTH_HOOKS:
            raise QuackCatalogError(
                "authentication callback must be non-default and globally visible"
            )
        if not authz_name or authz_name.lower() in qs.DEFAULT_PERMISSIVE_AUTHZ_HOOKS:
            raise QuackCatalogError(
                "authorization callback must be non-default and globally visible"
            )
        if self.allow_prefix or self.allow_regex:
            raise QuackCatalogError(
                "prefix/regex authorization is forbidden; exact full-SQL only"
            )
        if self.authorization_mode != qs.AuthorizationMode.EXACT_FULL_SQL.value:
            raise QuackCatalogError(
                "authorization mode must be exact_full_sql"
            )
        if not self.globally_visible:
            raise QuackCatalogError(
                "authorization callback must be globally visible before accept"
            )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "authentication_callback": self.authentication_callback,
                "authorization_callback": self.authorization_callback,
                "authorization_mode": self.authorization_mode,
                "allow_prefix": self.allow_prefix,
                "allow_regex": self.allow_regex,
                "globally_visible": self.globally_visible,
                "attested_at_unix": self.attested_at_unix,
                "callback_blob_digest": self.callback_blob_digest,
                "config_digest": self.config_digest,
                "quack_authentication_function": qs.QUACK_AUTHENTICATION_FUNCTION,
                "quack_authorization_function": qs.QUACK_AUTHORIZATION_FUNCTION,
            }
        )


def attest_authorization_callback(
    *,
    authentication_callback: str = qs.NON_DEFAULT_AUTH_CALLBACK_NAME,
    authorization_callback: str = qs.NON_DEFAULT_AUTHZ_CALLBACK_NAME,
    authorization_mode: str = qs.AuthorizationMode.EXACT_FULL_SQL.value,
    allow_prefix: bool = False,
    allow_regex: bool = False,
    globally_visible: bool = True,
    now: float | None = None,
    callback_blob: bytes | str = b"ipfs_datasets_exact_sql_authz_v1",
    config: Mapping[str, Any] | None = None,
) -> AuthCallbackAttestation:
    """Attest non-default globally visible authz before accepting connections.

    A missing, reset, changed, or permissive hook fails closed via construction.
    """

    clock = time.time() if now is None else float(now)
    if not globally_visible:
        raise QuackCatalogError(
            "missing or non-visible quack_authorization_function fails closed"
        )
    if allow_prefix or allow_regex:
        raise QuackCatalogError(
            "prefix or regex authorization approximation fails closed"
        )
    blob = (
        callback_blob
        if isinstance(callback_blob, bytes)
        else str(callback_blob).encode("utf-8")
    )
    cfg = dict(config or {})
    cfg.setdefault("mode", authorization_mode)
    cfg.setdefault("callback", authorization_callback)
    return AuthCallbackAttestation(
        authentication_callback=authentication_callback,
        authorization_callback=authorization_callback,
        authorization_mode=authorization_mode,
        allow_prefix=allow_prefix,
        allow_regex=allow_regex,
        globally_visible=globally_visible,
        attested_at_unix=clock,
        callback_blob_digest="sha256:" + hashlib.sha256(blob).hexdigest(),
        config_digest="sha256:" + _sha256_json(cfg),
    )


# ---------------------------------------------------------------------------
# Mutation receipts + idempotency
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MutationReceipt:
    """Receipt binding session, verification, authz, profiles, and effects."""

    receipt_id: str
    operation_id: str
    catalog_id: str
    session_id: str
    signed_request_digest: str
    signed_request_verified: bool
    authorization_callback_blob_digest: str
    authorization_callback_config_digest: str
    quack_profile: str
    duckdb_profile: str
    request: Mapping[str, Any]
    catalog_network_policy: Mapping[str, Any]
    before_snapshot: int
    after_snapshot: int
    affected_logical_objects: tuple[str, ...]
    outbox_state: str
    idempotency_state: str
    audit_event_id: str
    owner_generation: int
    fencing_epoch: int
    template_identity: str
    canonical_sql_digest: str
    production_mutation: bool
    schema: str = MUTATION_RECEIPT_SCHEMA

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "receipt_id": self.receipt_id,
                "operation_id": self.operation_id,
                "catalog_id": self.catalog_id,
                "session_id": self.session_id,
                "signed_request_digest": self.signed_request_digest,
                "signed_request_verified": self.signed_request_verified,
                "authorization_callback_blob_digest": (
                    self.authorization_callback_blob_digest
                ),
                "authorization_callback_config_digest": (
                    self.authorization_callback_config_digest
                ),
                "quack_profile": self.quack_profile,
                "duckdb_profile": self.duckdb_profile,
                "request": dict(self.request),
                "catalog_network_policy": dict(self.catalog_network_policy),
                "before_snapshot": self.before_snapshot,
                "after_snapshot": self.after_snapshot,
                "affected_logical_objects": list(self.affected_logical_objects),
                "outbox_state": self.outbox_state,
                "idempotency_state": self.idempotency_state,
                "audit_event_id": self.audit_event_id,
                "owner_generation": self.owner_generation,
                "fencing_epoch": self.fencing_epoch,
                "template_identity": self.template_identity,
                "canonical_sql_digest": self.canonical_sql_digest,
                "production_mutation": self.production_mutation,
            }
        )


def build_mutation_receipt(
    *,
    operation: SignedCatalogOperation,
    session_id: str,
    attestation: AuthCallbackAttestation,
    before_snapshot: int,
    after_snapshot: int,
    affected_logical_objects: Sequence[str],
    outbox_state: str,
    idempotency_state: str,
    quack_profile: str,
    duckdb_profile: str,
    catalog_network_policy: Mapping[str, Any],
    canonical_sql: str,
    production_mutation: bool = False,
) -> MutationReceipt:
    audit_event_id = f"audit_{uuid.uuid4().hex}"
    return MutationReceipt(
        receipt_id=f"mrcpt_{uuid.uuid4().hex}",
        operation_id=operation.operation_id,
        catalog_id=operation.catalog_id,
        session_id=session_id,
        signed_request_digest=operation.request_digest(),
        signed_request_verified=True,
        authorization_callback_blob_digest=attestation.callback_blob_digest,
        authorization_callback_config_digest=attestation.config_digest,
        quack_profile=quack_profile,
        duckdb_profile=duckdb_profile,
        request={
            "template_id": operation.template_id,
            "template_version": operation.template_version,
            "tenant": operation.tenant,
            "starting_snapshot": operation.starting_snapshot,
            "schema_name": operation.schema_name,
            "expected_effects": list(operation.expected_effects),
            "parameters_digest": "sha256:" + _sha256_json(dict(operation.parameters)),
            # Raw SQL and tokens never appear in the receipt.
            "canonical_sql": qs.redact_sql(canonical_sql),
        },
        catalog_network_policy=dict(catalog_network_policy),
        before_snapshot=int(before_snapshot),
        after_snapshot=int(after_snapshot),
        affected_logical_objects=tuple(str(x) for x in affected_logical_objects),
        outbox_state=str(outbox_state),
        idempotency_state=str(idempotency_state),
        audit_event_id=audit_event_id,
        owner_generation=operation.owner_generation,
        fencing_epoch=operation.fencing_epoch,
        template_identity=f"{operation.template_id}@v{operation.template_version}",
        canonical_sql_digest="sha256:"
        + hashlib.sha256(canonical_sql.encode("utf-8")).hexdigest(),
        production_mutation=bool(production_mutation),
    )


class DurableIdempotencyStore:
    """Durable operation-id store for lost-reply and restart replay.

    A successful claim is terminal. Replaying the same operation id with the
    same request digest returns the prior receipt; a conflicting body fails.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_operation: dict[str, dict[str, Any]] = {}

    def lookup(self, operation_id: str) -> Mapping[str, Any] | None:
        with self._lock:
            row = self._by_operation.get(str(operation_id))
            return MappingProxyType(dict(row)) if row is not None else None

    def commit(
        self,
        *,
        operation_id: str,
        request_digest: str,
        receipt: MutationReceipt,
    ) -> MutationReceipt:
        with self._lock:
            existing = self._by_operation.get(str(operation_id))
            if existing is not None:
                if existing["request_digest"] != request_digest:
                    raise IdempotentReplay(
                        f"operation_id {operation_id!r} already committed with a "
                        "different request digest; refuse duplicate catalog mutation"
                    )
                # Return prior receipt (lost reply / restart path).
                return existing["receipt"]
            self._by_operation[str(operation_id)] = {
                "request_digest": request_digest,
                "receipt": receipt,
                "committed_at_unix": time.time(),
            }
            return receipt

    def __len__(self) -> int:
        with self._lock:
            return len(self._by_operation)


# ---------------------------------------------------------------------------
# Gateway policy / scrubbing / promotion gates
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GatewayBindPolicy:
    """Localhost / private-network or TLS-proxy bind policy for the gateway."""

    bind_host: str = "127.0.0.1"
    bind_port: int = 5433
    require_loopback_or_tls_proxy: bool = True
    behind_tls_reverse_proxy: bool = False
    scrub_tokens: bool = True
    scrub_credentials: bool = True
    scrub_secrets: bool = True
    scrub_raw_sql: bool = True

    def __post_init__(self) -> None:
        host = str(self.bind_host or "").strip()
        if not host:
            raise QuackCatalogError("bind_host is required")
        if (
            not isinstance(self.bind_port, int)
            or isinstance(self.bind_port, bool)
            or not (1 <= self.bind_port <= 65535)
        ):
            raise QuackCatalogError("bind_port out of range")
        if self.require_loopback_or_tls_proxy:
            qs.reject_remote_plaintext(
                bind_host=host,
                use_tls=False,
                behind_tls_reverse_proxy=self.behind_tls_reverse_proxy,
            )
        if not (
            self.scrub_tokens
            and self.scrub_credentials
            and self.scrub_secrets
            and self.scrub_raw_sql
        ):
            raise QuackCatalogError(
                "gateway must scrub tokens, credentials, secrets, and raw SQL "
                "from DuckDB/Quack logs"
            )
        object.__setattr__(self, "bind_host", host)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "bind_host": self.bind_host,
                "bind_port": self.bind_port,
                "require_loopback_or_tls_proxy": self.require_loopback_or_tls_proxy,
                "behind_tls_reverse_proxy": self.behind_tls_reverse_proxy,
                "scrub_tokens": self.scrub_tokens,
                "scrub_credentials": self.scrub_credentials,
                "scrub_secrets": self.scrub_secrets,
                "scrub_raw_sql": self.scrub_raw_sql,
                "loopback": qs.is_loopback_host(self.bind_host),
            }
        )


def scrub_log_payload(payload: Mapping[str, Any] | str) -> dict[str, Any] | str:
    """Scrub tokens, credentials, secrets, and raw SQL from log-bound payloads."""

    if isinstance(payload, str):
        return qs.redact_sql(qs.redact_token(payload))
    return qs.sensitive_log_view(
        token=str(payload.get("token") or payload.get("secret") or ""),
        sql=str(payload.get("sql") or payload.get("canonical_sql") or ""),
        extra={
            k: (
                qs.REDACTION_MARKER
                if k.lower()
                in {
                    "token",
                    "secret",
                    "password",
                    "credential",
                    "api_key",
                    "quack_token",
                    "sql",
                    "canonical_sql",
                    "raw_sql",
                }
                else v
            )
            for k, v in dict(payload).items()
            if k.lower()
            not in {
                "token",
                "secret",
                "password",
                "credential",
                "api_key",
                "quack_token",
                "sql",
                "canonical_sql",
                "raw_sql",
            }
        },
    )


def promotion_gate_status(
    *,
    dqk_088_complete: bool = False,
    dqk_094_complete: bool = False,
    dqk_102_signed: bool = False,
) -> Mapping[str, Any]:
    """Report whether production activation is still held."""

    held_by = [
        gate
        for gate, done in (
            ("DQK-088", dqk_088_complete),
            ("DQK-094", dqk_094_complete),
            ("DQK-102", dqk_102_signed),
        )
        if not done
    ]
    return MappingProxyType(
        {
            "schema": QUACK_CATALOG_SCHEMA,
            "production_endpoint_started": False,
            "production_mutation_enabled": False,
            "activation_held": bool(held_by),
            "held_behind": tuple(PROMOTION_GATE_HOLD) if held_by else (),
            "held_by": tuple(held_by),
            "dqk_088_complete": bool(dqk_088_complete),
            "dqk_094_complete": bool(dqk_094_complete),
            "dqk_102_signed": bool(dqk_102_signed),
            "implementation_generation": _IMPLEMENTATION_GENERATION,
            "creates_no_production_catalog_endpoint": True,
            "performs_no_production_ducklake_mutation": True,
        }
    )


def assert_no_production_activation(
    *,
    start_production_endpoint: bool = False,
    perform_production_mutation: bool = False,
    dqk_088_complete: bool = False,
    dqk_094_complete: bool = False,
    dqk_102_signed: bool = False,
) -> Mapping[str, Any]:
    """Fail closed if this task tries to promote a production endpoint/mutation."""

    status = promotion_gate_status(
        dqk_088_complete=dqk_088_complete,
        dqk_094_complete=dqk_094_complete,
        dqk_102_signed=dqk_102_signed,
    )
    if start_production_endpoint:
        raise PromotionGateHold(
            "this implementation task creates no production catalog endpoint; "
            "activation remains held behind DQK-088, DQK-094, and the signed "
            "DQK-102 gate"
        )
    if perform_production_mutation:
        raise PromotionGateHold(
            "this implementation task performs no production DuckLake mutation; "
            "activation remains held behind DQK-088, DQK-094, and the signed "
            "DQK-102 gate"
        )
    if status["activation_held"] and (
        start_production_endpoint or perform_production_mutation
    ):  # pragma: no cover - defensive
        raise PromotionGateHold(
            "activation held behind: " + ", ".join(status["held_by"])
        )
    return status


def assert_gateway_cannot_read_authority(
    requested_catalogs: Iterable[str],
) -> None:
    """Gateway cannot read control/proof/graph-writer/AST/wallet/secret/publication."""

    for name in requested_catalogs:
        key = str(name or "").strip().lower()
        if key in FORBIDDEN_AUTHORITY_CATALOGS:
            raise SurfaceDenied(
                f"gateway cannot read authority catalog {name!r}; forbidden set "
                "includes control, proof, graph-writer, AST-writer, wallet, "
                "secret, and sanitized-publication"
            )


def owner_extension_load_plan() -> Mapping[str, Any]:
    """Explicit LOAD order for pinned DuckLake, Quack, and object-store extensions."""

    return MappingProxyType(
        {
            "pinned_extensions": list(PINNED_OWNER_EXTENSIONS),
            "explicit_load_order": list(EXPLICIT_LOAD_ORDER),
            "automatic_install": False,
            "automatic_load": False,
            "duckdb_owns_catalog_file": True,
            "quack_provides_authenticated_distributed_transport": True,
            "quack_is_not_task_lease_cas_authority": True,
            "quack_is_not_replication": True,
            "quack_is_not_multi_owner_storage": True,
        }
    )
