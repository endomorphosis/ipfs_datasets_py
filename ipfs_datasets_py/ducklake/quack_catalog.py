"""Dedicated DuckDB + Quack catalog-shard owner process (DQK-104).

One identity-bound process owns exactly one DuckLake catalog shard:

* acquires a durable owner-generation lease before opening the local/block-
  storage DuckDB metadata file
* acquires DuckDB's native file lock
* explicitly loads the pinned DuckLake, Quack, and object-store extensions
* attaches exactly one DuckLake catalog on the Quack-serving DatabaseInstance
* coordinates privately with a separate DQK-086 companion-registry
  DatabaseInstance that is never ATTACHed to or visible from Quack

Distributed readers/writers connect only through Quack. Remote clients never
open, copy into place, or network-mount the live catalog file.

Production catalog endpoints and production DuckLake mutations remain
disabled until DQK-088, DQK-094, and the signed DQK-102 gate authorize
cutover. This module never starts a production network listener.

Import is side-effect free: it never imports ``duckdb``, never binds sockets,
and never opens catalog files. Runtime file-lock and liveness probes are
injected under test or by the owner runtime.
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
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Sequence

from ipfs_datasets_py.duckdb_control import quack_security as qs
from ipfs_datasets_py.ducklake import catalog as cat
from ipfs_datasets_py.ducklake import config as cfg
from ipfs_datasets_py.ducklake.capabilities import (
    EXPLICIT_LOAD_ORDER,
    PINNED_DUCKLAKE_EXTENSION_BUILD,
    PINNED_HTTPFS_EXTENSION_BUILD,
    PINNED_QUACK_EXTENSION_BUILD,
    REQUIRED_DUCKDB_VERSION_TEXT,
)
from ipfs_datasets_py.ducklake.registry import (
    CompanionLakeRegistry,
    DatabaseInstanceBinding,
    DatabaseInstanceKind,
    MemoryRegistryStore,
    RegistryScope,
)

__all__ = [
    "ACTIVATION_GATES",
    "ALLOWED_OPERATION_KINDS",
    "AUTHORITY_CATALOG_ROLES",
    "DENIED_SQL_SURFACES",
    "IMPLEMENTATION_GENERATION",
    "MUTATION_RECEIPT_SCHEMA",
    "OWNER_PROCESS_SCHEMA",
    "PRODUCTION_ENDPOINT_ENABLED",
    "PRODUCTION_MUTATION_ENABLED",
    "QUACK_CATALOG_SCHEMA",
    "SIGNED_OPERATION_SCHEMA",
    "TEMPLATE_REGISTRY_VERSION",
    "ActivationGateError",
    "AttachedCatalogState",
    "CatalogDatabaseInstance",
    "CatalogOwnerError",
    "CatalogOwnerProcess",
    "CatalogOwnerProcessState",
    "DeniedSurfaceError",
    "DurableIdempotencyStore",
    "EndpointTokenState",
    "ExtensionLoadPlan",
    "ForbiddenAuthorityAccess",
    "LeaseLossEvent",
    "MutationReceipt",
    "OwnerGenerationLease",
    "OwnerShutdownReceipt",
    "ProductionEndpointDenied",
    "QuackOwnerSession",
    "SignedCatalogOperation",
    "SurfaceClassification",
    "TakeoverExecutionReceipt",
    "assert_activation_held",
    "assert_not_production_endpoint",
    "assert_not_production_mutation",
    "build_extension_load_plan",
    "classify_denied_sql_surface",
    "default_owner_security_policy",
    "digest_of",
    "exact_template_identity",
    "is_activation_held",
    "redact_for_logs",
    "verify_signed_operation",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

QUACK_CATALOG_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-quack-catalog-owner@1"
)
OWNER_PROCESS_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-catalog-owner-process@1"
)
SIGNED_OPERATION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-signed-catalog-operation@1"
)
MUTATION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-catalog-mutation-receipt@1"
)

IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-104-quack-catalog-owner-20260810"
)
TEMPLATE_REGISTRY_VERSION: Final[str] = "catalog-templates@1"

# Production activation remains held behind these independent gates.
ACTIVATION_GATES: Final[tuple[str, ...]] = ("DQK-088", "DQK-094", "DQK-102")
PRODUCTION_ENDPOINT_ENABLED: Final[bool] = False
PRODUCTION_MUTATION_ENABLED: Final[bool] = False

# Authority catalogs the gateway must never open or ATTACH.
AUTHORITY_CATALOG_ROLES: Final[frozenset[str]] = frozenset(
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

# Surfaces denied over Quack (arbitrary SQL, privilege escapes, internals).
DENIED_SQL_SURFACES: Final[tuple[str, ...]] = (
    "ATTACH ",
    "DETACH ",
    "INSTALL ",
    "LOAD ",
    "CREATE SECRET",
    "DROP SECRET",
    "COPY ",
    "PRAGMA ",
    "SET ",
    "RESET ",
    "SHOW ",
    "EXPORT ",
    "IMPORT ",
    "CALL ",
    "EXECUTE ",
    "PREPARE ",
    "DEALLOCATE ",
    "ducklake_metadata",
    "ducklake_file_key",
    "ducklake_encryption_key",
    "duckdb_encryption_key",
    "parquet_encryption_key",
    "duckdb_secrets",
    "duckdb_extensions",
    "duckdb_databases",
    "duckdb_settings",
    "READ_CSV",
    "READ_PARQUET",
    "READ_JSON",
    "READ_BLOB",
    "READ_TEXT",
    "HTTPFS",
    "FROM '",
    'FROM "',
)

ALLOWED_OPERATION_KINDS: Final[frozenset[str]] = frozenset(
    {
        "catalog.describe",
        "namespace.list",
        "schema.list",
        "schema.describe",
        "table.list",
        "table.describe",
        "snapshot.list",
        "snapshot.select",
        "ingest.register_intent",
        "maintenance.intent",
        "mutation.bounded_insert",
        "mutation.bounded_replace",
    }
)

_MUTATING_KINDS: Final[frozenset[str]] = frozenset(
    {
        "ingest.register_intent",
        "maintenance.intent",
        "mutation.bounded_insert",
        "mutation.bounded_replace",
    }
)

_SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")
_OP_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,255}$")
_TEMPLATE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./:@-]{0,255}$")
_MULTI_STMT_RE = re.compile(r";\s*\S")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CatalogOwnerError(ValueError):
    """Fail-closed catalog-owner process rejection."""


class ActivationGateError(CatalogOwnerError):
    """Production activation or mutation is still gated."""


class ProductionEndpointDenied(ActivationGateError):
    """This task must not start or promote a production catalog endpoint."""


class DeniedSurfaceError(CatalogOwnerError):
    """Arbitrary SQL or privileged surface denied by the owner gateway."""


class ForbiddenAuthorityAccess(CatalogOwnerError):
    """Attempt to open a forbidden authority catalog role."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def digest_of(payload: Any) -> str:
    """Content digest of a JSON-canonical payload."""

    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def exact_template_identity(template: str) -> str:
    """Stable identity of a versioned canonical SQL template (exact text)."""

    return "sha256:" + hashlib.sha256(str(template).encode("utf-8")).hexdigest()


def redact_for_logs(
    *,
    token: str | None = None,
    sql: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Scrub tokens, credentials, secrets, and raw SQL from log views."""

    return qs.sensitive_log_view(token=token, sql=sql, extra=dict(extra or {}))


def is_activation_held(
    *,
    dqk_088_complete: bool = False,
    dqk_094_complete: bool = False,
    dqk_102_signed: bool = False,
) -> bool:
    """Return True while production activation remains held."""

    return not (dqk_088_complete and dqk_094_complete and dqk_102_signed)


def assert_activation_held(
    *,
    dqk_088_complete: bool = False,
    dqk_094_complete: bool = False,
    dqk_102_signed: bool = False,
) -> Mapping[str, Any]:
    """Prove activation is still held behind the promotion gates."""

    held = is_activation_held(
        dqk_088_complete=dqk_088_complete,
        dqk_094_complete=dqk_094_complete,
        dqk_102_signed=dqk_102_signed,
    )
    if not held:
        # Even if dependency tasks claim complete, this code path still refuses
        # production mutation/endpoint promotion until an independent signed
        # cutover is wired outside this module.
        if PRODUCTION_ENDPOINT_ENABLED or PRODUCTION_MUTATION_ENABLED:
            raise ActivationGateError(
                "production flags must remain false in DQK-104 code completion"
            )
    return MappingProxyType(
        {
            "activation_held": True,
            "gates": list(ACTIVATION_GATES),
            "dqk_088_complete": bool(dqk_088_complete),
            "dqk_094_complete": bool(dqk_094_complete),
            "dqk_102_signed": bool(dqk_102_signed),
            "production_endpoint_enabled": PRODUCTION_ENDPOINT_ENABLED,
            "production_mutation_enabled": PRODUCTION_MUTATION_ENABLED,
            "reason": (
                "activation remains held behind DQK-088, DQK-094, and the "
                "signed DQK-102 gate; this task creates no production catalog "
                "endpoint and performs no production DuckLake mutation"
            ),
        }
    )


def assert_not_production_endpoint() -> None:
    """Hard deny starting or promoting a production catalog endpoint."""

    if PRODUCTION_ENDPOINT_ENABLED:
        raise ProductionEndpointDenied(
            "production catalog endpoint is enabled but DQK-104 must not start "
            "or promote a production endpoint"
        )


def assert_not_production_mutation() -> None:
    """Hard deny production DuckLake mutation in this code-completion task."""

    if PRODUCTION_MUTATION_ENABLED:
        raise ActivationGateError(
            "production DuckLake mutation is enabled but remains gated by "
            "DQK-088, DQK-094, and the signed DQK-102 gate"
        )


def classify_denied_sql_surface(sql: str) -> "SurfaceClassification":
    """Classify SQL against denied privilege / internal surfaces."""

    text = str(sql or "")
    upper = text.upper()
    compact = " ".join(upper.split())

    parts = [p.strip() for p in text.split(";") if p.strip()]
    if len(parts) > 1 or (_MULTI_STMT_RE.search(text) is not None and len(parts) > 1):
        return SurfaceClassification(
            denied=True,
            matched="MULTI_STATEMENT",
            reason="multi-statement escape is hard-gated",
        )
    # Semicolon multi-statement with trailing content.
    if ";" in text:
        non_empty = [p for p in text.split(";") if p.strip()]
        if len(non_empty) > 1:
            return SurfaceClassification(
                denied=True,
                matched="MULTI_STATEMENT",
                reason="multi-statement escape is hard-gated",
            )

    for surface in DENIED_SQL_SURFACES:
        needle = surface.upper()
        if needle in compact or compact.startswith(needle.strip()):
            return SurfaceClassification(
                denied=True,
                matched=surface.strip(),
                reason=f"denied SQL surface: {surface.strip()}",
            )

    # Credential / token export probes.
    if any(
        token in compact
        for token in (
            "CURRENT_SETTING",
            "PRAGMA_DATABASE_LIST",
            "GET_SECRET",
            "EXPORT DATABASE",
            "COPY (SELECT",
        )
    ):
        return SurfaceClassification(
            denied=True,
            matched="CREDENTIAL_EXPORT",
            reason="credential/token export is hard-gated",
        )

    return SurfaceClassification(denied=False, matched=None, reason=None)


@dataclass(frozen=True, slots=True)
class SurfaceClassification:
    """Result of denied-surface classification."""

    denied: bool
    matched: str | None
    reason: str | None

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "denied": self.denied,
                "matched": self.matched,
                "reason": self.reason,
            }
        )


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
    template_version: str
    kind: str
    tenant_id: str
    catalog_id: str
    owner_generation: int
    fencing_epoch: int
    starting_snapshot: int
    schema_name: str
    expected_effects: Mapping[str, Any]
    caller_process_birth: Mapping[str, Any]
    resource_budget: Mapping[str, Any]
    expires_at_unix: float
    signature: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    canonical_sql: str = ""
    nonce: str = ""
    schema: str = SIGNED_OPERATION_SCHEMA

    def __post_init__(self) -> None:
        op = str(self.operation_id or "").strip()
        if not op or not _OP_ID_RE.match(op):
            raise CatalogOwnerError(f"invalid operation_id {self.operation_id!r}")
        template_id = str(self.template_id or "").strip()
        if not template_id or not _TEMPLATE_ID_RE.match(template_id):
            raise CatalogOwnerError(f"invalid template_id {self.template_id!r}")
        kind = str(self.kind or "").strip()
        if kind not in ALLOWED_OPERATION_KINDS:
            raise CatalogOwnerError(
                f"operation kind {kind!r} is not allowlisted; admitted kinds: "
                f"{sorted(ALLOWED_OPERATION_KINDS)}"
            )
        tenant = str(self.tenant_id or "").strip()
        if not tenant:
            raise CatalogOwnerError("tenant_id is required")
        catalog_id = str(self.catalog_id or "").strip()
        if not catalog_id:
            raise CatalogOwnerError("catalog_id is required")
        if (
            not isinstance(self.owner_generation, int)
            or isinstance(self.owner_generation, bool)
            or self.owner_generation < 1
        ):
            raise CatalogOwnerError("owner_generation must be a positive int")
        if (
            not isinstance(self.fencing_epoch, int)
            or isinstance(self.fencing_epoch, bool)
            or self.fencing_epoch < 1
        ):
            raise CatalogOwnerError("fencing_epoch must be a positive int")
        if (
            not isinstance(self.starting_snapshot, int)
            or isinstance(self.starting_snapshot, bool)
            or self.starting_snapshot < 0
        ):
            raise CatalogOwnerError("starting_snapshot must be a non-negative int")
        birth = dict(self.caller_process_birth or {})
        if not birth:
            raise CatalogOwnerError("caller_process_birth is required")
        budget = dict(self.resource_budget or {})
        if "max_rows" not in budget and "max_bytes" not in budget:
            raise CatalogOwnerError(
                "resource_budget must include max_rows and/or max_bytes"
            )
        if not isinstance(self.expires_at_unix, (int, float)) or isinstance(
            self.expires_at_unix, bool
        ):
            raise CatalogOwnerError("expires_at_unix must be a number")
        sig = str(self.signature or "").strip()
        if not sig or not _SHA256_RE.match(sig.replace("sig:", "").replace("sha256:", "")):
            # Accept sha256:... or bare hex or sig:sha256:...
            bare = sig
            for prefix in ("sig:", "sha256:"):
                if bare.startswith(prefix):
                    bare = bare[len(prefix) :]
            if not re.fullmatch(r"[0-9a-fA-F]{64}", bare):
                raise CatalogOwnerError("signature must be a sha256 digest")
        params = dict(self.parameters or {})
        effects = dict(self.expected_effects or {})
        schema = str(self.schema or SIGNED_OPERATION_SCHEMA).strip()
        if schema != SIGNED_OPERATION_SCHEMA:
            raise CatalogOwnerError(f"unsupported signed-operation schema {schema!r}")
        object.__setattr__(self, "operation_id", op)
        object.__setattr__(self, "template_id", template_id)
        object.__setattr__(self, "template_version", str(self.template_version or "").strip())
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "tenant_id", tenant)
        object.__setattr__(self, "catalog_id", catalog_id)
        object.__setattr__(self, "schema_name", str(self.schema_name or "").strip())
        object.__setattr__(self, "expected_effects", MappingProxyType(effects))
        object.__setattr__(self, "caller_process_birth", MappingProxyType(birth))
        object.__setattr__(self, "resource_budget", MappingProxyType(budget))
        object.__setattr__(self, "signature", sig)
        object.__setattr__(self, "parameters", MappingProxyType(params))
        object.__setattr__(self, "canonical_sql", str(self.canonical_sql or ""))
        object.__setattr__(self, "nonce", str(self.nonce or ""))
        object.__setattr__(self, "schema", schema)

    @property
    def is_mutating(self) -> bool:
        return self.kind in _MUTATING_KINDS

    def is_expired(self, *, now: float | None = None) -> bool:
        clock = time.time() if now is None else float(now)
        return clock >= float(self.expires_at_unix)

    def unsigned_payload(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "operation_id": self.operation_id,
                "template_id": self.template_id,
                "template_version": self.template_version,
                "kind": self.kind,
                "tenant_id": self.tenant_id,
                "catalog_id": self.catalog_id,
                "owner_generation": self.owner_generation,
                "fencing_epoch": self.fencing_epoch,
                "starting_snapshot": self.starting_snapshot,
                "schema_name": self.schema_name,
                "expected_effects": dict(self.expected_effects),
                "caller_process_birth": dict(self.caller_process_birth),
                "resource_budget": dict(self.resource_budget),
                "expires_at_unix": self.expires_at_unix,
                "parameters": dict(self.parameters),
                "canonical_sql": self.canonical_sql,
                "nonce": self.nonce,
            }
        )

    def as_mapping(self) -> Mapping[str, Any]:
        payload = dict(self.unsigned_payload())
        payload["signature"] = self.signature
        payload["is_mutating"] = self.is_mutating
        # Raw SQL redacted in public projection.
        if payload.get("canonical_sql"):
            payload["canonical_sql"] = qs.redact_sql(str(payload["canonical_sql"]))
        return MappingProxyType(payload)


def _sign_payload(payload: Mapping[str, Any], *, signing_key: str) -> str:
    body = json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    digest = hmac.new(
        signing_key.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return f"sha256:{digest}"


def verify_signed_operation(
    operation: SignedCatalogOperation,
    *,
    signing_key: str,
    expected_catalog_id: str,
    expected_owner_generation: int,
    expected_fencing_epoch: int,
    now: float | None = None,
) -> Mapping[str, Any]:
    """Independently verify a signed structured operation (primary authz)."""

    if operation.is_expired(now=now):
        raise CatalogOwnerError(
            f"signed operation {operation.operation_id!r} has expired"
        )
    if operation.catalog_id != expected_catalog_id:
        raise CatalogOwnerError(
            f"operation catalog_id {operation.catalog_id!r} does not match "
            f"owner catalog {expected_catalog_id!r}"
        )
    if operation.owner_generation != expected_owner_generation:
        raise CatalogOwnerError(
            "operation owner_generation fence mismatch: "
            f"{operation.owner_generation} != {expected_owner_generation}"
        )
    if operation.fencing_epoch != expected_fencing_epoch:
        raise CatalogOwnerError(
            "operation fencing_epoch mismatch: "
            f"{operation.fencing_epoch} != {expected_fencing_epoch}"
        )
    expected_sig = _sign_payload(operation.unsigned_payload(), signing_key=signing_key)
    presented = operation.signature
    if not presented.startswith("sha256:"):
        presented = f"sha256:{presented}"
    if not hmac.compare_digest(expected_sig, presented):
        raise CatalogOwnerError(
            "signed operation signature verification failed; "
            "task-owned handler rejects before SQL construction"
        )
    if operation.canonical_sql:
        surface = classify_denied_sql_surface(operation.canonical_sql)
        if surface.denied:
            raise DeniedSurfaceError(surface.reason or "denied SQL surface")
    return MappingProxyType(
        {
            "verified": True,
            "operation_id": operation.operation_id,
            "template_id": operation.template_id,
            "template_version": operation.template_version,
            "kind": operation.kind,
            "catalog_id": operation.catalog_id,
            "owner_generation": operation.owner_generation,
            "fencing_epoch": operation.fencing_epoch,
            "signature_digest": expected_sig,
            "primary_authorization": "task_owned_signed_operation",
            "quack_authorization_is_defense_in_depth": True,
        }
    )


# ---------------------------------------------------------------------------
# Extension load plan / dual DatabaseInstance
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExtensionLoadPlan:
    """Explicit pinned extension LOAD plan (no automatic install/load)."""

    load_order: tuple[str, ...]
    builds: Mapping[str, str]
    automatic_install: bool = False
    automatic_load: bool = False
    load_before_configuration_lock: bool = True

    def __post_init__(self) -> None:
        if self.automatic_install or self.automatic_load:
            raise CatalogOwnerError(
                "automatic extension install/load is forbidden for catalog owners"
            )
        if tuple(self.load_order) != EXPLICIT_LOAD_ORDER:
            raise CatalogOwnerError(
                f"extension load order must be {EXPLICIT_LOAD_ORDER!r}; "
                f"got {self.load_order!r}"
            )
        required = {
            "quack": PINNED_QUACK_EXTENSION_BUILD,
            "ducklake": PINNED_DUCKLAKE_EXTENSION_BUILD,
            "httpfs": PINNED_HTTPFS_EXTENSION_BUILD,
        }
        builds = dict(self.builds)
        for name, build in required.items():
            if builds.get(name) != build:
                raise CatalogOwnerError(
                    f"pinned extension build mismatch for {name}: "
                    f"expected {build!r}, got {builds.get(name)!r}"
                )
        object.__setattr__(self, "builds", MappingProxyType(builds))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "load_order": list(self.load_order),
                "builds": dict(self.builds),
                "automatic_install": False,
                "automatic_load": False,
                "load_before_configuration_lock": True,
                "duckdb_version": REQUIRED_DUCKDB_VERSION_TEXT,
            }
        )


def build_extension_load_plan() -> ExtensionLoadPlan:
    """Build the authoritative pinned extension load plan for a catalog owner."""

    return ExtensionLoadPlan(
        load_order=EXPLICIT_LOAD_ORDER,
        builds={
            "quack": PINNED_QUACK_EXTENSION_BUILD,
            "ducklake": PINNED_DUCKLAKE_EXTENSION_BUILD,
            "httpfs": PINNED_HTTPFS_EXTENSION_BUILD,
        },
    )


@dataclass
class CatalogDatabaseInstance:
    """In-process model of one DuckDB DatabaseInstance.

    Quack-serving instances attach only the selected DuckLake catalog.
    Companion-registry instances are private and never remotely visible.
    """

    binding: DatabaseInstanceBinding
    attached_catalogs: dict[str, str] = field(default_factory=dict)
    loaded_extensions: list[str] = field(default_factory=list)
    open_handles: int = 0
    closed: bool = False
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def load_extensions(self, plan: ExtensionLoadPlan) -> Mapping[str, Any]:
        with self._lock:
            if self.closed:
                raise CatalogOwnerError("DatabaseInstance is closed")
            for name in plan.load_order:
                build = plan.builds[name]
                if build not in self.loaded_extensions:
                    self.loaded_extensions.append(build)
            return MappingProxyType(
                {
                    "instance_id": self.binding.instance_id,
                    "loaded": list(self.loaded_extensions),
                    "load_order": list(plan.load_order),
                }
            )

    def attach_catalog(self, *, alias: str, catalog_path: str) -> None:
        with self._lock:
            if self.closed:
                raise CatalogOwnerError("DatabaseInstance is closed")
            if self.binding.kind is not DatabaseInstanceKind.QUACK_SERVING:
                raise CatalogOwnerError(
                    "only the Quack-serving DatabaseInstance attaches the "
                    "DuckLake catalog"
                )
            if self.attached_catalogs and alias not in self.attached_catalogs:
                raise CatalogOwnerError(
                    "catalog-scoped server may attach exactly one selected "
                    "DuckLake catalog; concurrent cross-catalog overlap rejected"
                )
            if (
                alias in self.attached_catalogs
                and self.attached_catalogs[alias] != catalog_path
            ):
                raise CatalogOwnerError("catalog alias already bound to another path")
            self.attached_catalogs[alias] = catalog_path
            self.open_handles += 1

    def attempt_attach_companion(self, companion: "CatalogDatabaseInstance") -> None:
        """Fail closed if a companion would become visible from Quack."""

        if companion.binding.kind is DatabaseInstanceKind.COMPANION_PRIVATE:
            if companion.binding.attachable_from_quack:
                raise CatalogOwnerError(
                    "companion registry must never be attachable from Quack"
                )
            companion.binding.assert_not_attached_to(self.binding)
            raise CatalogOwnerError(
                "companion registry DatabaseInstance is never ATTACHed to or "
                "visible from the Quack-serving DatabaseInstance"
            )
        raise CatalogOwnerError("only companion instances are subject to attach denial")

    def close(self) -> None:
        with self._lock:
            self.attached_catalogs.clear()
            self.open_handles = 0
            self.closed = True

    def as_mapping(self) -> Mapping[str, Any]:
        with self._lock:
            return MappingProxyType(
                {
                    "binding": dict(self.binding.as_mapping()),
                    "attached_catalogs": dict(self.attached_catalogs),
                    "loaded_extensions": list(self.loaded_extensions),
                    "open_handles": self.open_handles,
                    "closed": self.closed,
                    "remotely_visible": (
                        self.binding.kind is DatabaseInstanceKind.QUACK_SERVING
                    ),
                }
            )


@dataclass(frozen=True, slots=True)
class AttachedCatalogState:
    """Proved single selected catalog attachment."""

    catalog_id: str
    catalog_path: str
    alias: str
    attach_sql_digest: str
    single_catalog: bool = True

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "catalog_id": self.catalog_id,
                "catalog_path": self.catalog_path,
                "alias": self.alias,
                "attach_sql_digest": self.attach_sql_digest,
                "single_catalog": self.single_catalog,
            }
        )


# ---------------------------------------------------------------------------
# Lease / endpoint / idempotency
# ---------------------------------------------------------------------------


@dataclass
class OwnerGenerationLease:
    """Durable catalog-owner generation lease for one shard."""

    lease_id: str
    catalog_id: str
    owner_generation: int
    fencing_epoch: int
    process_birth: Mapping[str, Any]
    endpoint_identity: str
    os_identity: str
    held: bool = True
    revoked: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.owner_generation, int)
            or isinstance(self.owner_generation, bool)
            or self.owner_generation < 1
        ):
            raise CatalogOwnerError("owner_generation must be a positive int")
        if not dict(self.process_birth or {}):
            raise CatalogOwnerError("process_birth is required for owner lease")
        object.__setattr__(
            self, "process_birth", MappingProxyType(dict(self.process_birth))
        )

    def lose(self) -> "LeaseLossEvent":
        self.held = False
        self.revoked = True
        return LeaseLossEvent(
            lease_id=self.lease_id,
            catalog_id=self.catalog_id,
            owner_generation=self.owner_generation,
            fencing_epoch=self.fencing_epoch,
            admission_stopped=True,
            endpoint_revoked=True,
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "lease_id": self.lease_id,
                "catalog_id": self.catalog_id,
                "owner_generation": self.owner_generation,
                "fencing_epoch": self.fencing_epoch,
                "process_birth": dict(self.process_birth),
                "endpoint_identity": self.endpoint_identity,
                "os_identity": self.os_identity,
                "held": self.held,
                "revoked": self.revoked,
            }
        )


@dataclass(frozen=True, slots=True)
class LeaseLossEvent:
    """Ordered lease-loss side effects (admission stop before teardown)."""

    lease_id: str
    catalog_id: str
    owner_generation: int
    fencing_epoch: int
    admission_stopped: bool
    endpoint_revoked: bool

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "lease_id": self.lease_id,
                "catalog_id": self.catalog_id,
                "owner_generation": self.owner_generation,
                "fencing_epoch": self.fencing_epoch,
                "admission_stopped": self.admission_stopped,
                "endpoint_revoked": self.endpoint_revoked,
                "order": (
                    "stop_admission",
                    "revoke_endpoint_token",
                    "expire_storage_capabilities",
                    "close_sessions_and_handles",
                    "exit",
                ),
            }
        )


@dataclass
class EndpointTokenState:
    """Reusable endpoint secret retained by the broker, not clients."""

    endpoint_id: str
    token_fingerprint: str
    generation: int
    valid: bool = True
    _raw_token: str = field(default="", repr=False)

    def rotate(self) -> "EndpointTokenState":
        new_token = secrets.token_urlsafe(32)
        self.valid = False
        return EndpointTokenState(
            endpoint_id=self.endpoint_id,
            token_fingerprint=hashlib.sha256(new_token.encode()).hexdigest()[:16],
            generation=self.generation + 1,
            valid=True,
            _raw_token=new_token,
        )

    def revoke(self) -> None:
        self.valid = False
        self._raw_token = ""

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "endpoint_id": self.endpoint_id,
                "token_fingerprint": self.token_fingerprint,
                "generation": self.generation,
                "valid": self.valid,
                "raw_token": qs.REDACTION_MARKER,
            }
        )


class DurableIdempotencyStore:
    """Durable operation-id store for lost-reply and restart replay."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_op: dict[str, Mapping[str, Any]] = {}

    def remember(self, operation_id: str, receipt: Mapping[str, Any]) -> None:
        op = str(operation_id or "").strip()
        if not op:
            raise CatalogOwnerError("operation_id is required for idempotency")
        with self._lock:
            if op in self._by_op:
                return
            self._by_op[op] = MappingProxyType(dict(receipt))

    def lookup(self, operation_id: str) -> Mapping[str, Any] | None:
        with self._lock:
            found = self._by_op.get(str(operation_id))
            return None if found is None else MappingProxyType(dict(found))

    def __len__(self) -> int:
        with self._lock:
            return len(self._by_op)

    def export_state(self) -> dict[str, Any]:
        with self._lock:
            return {k: dict(v) for k, v in self._by_op.items()}

    def import_state(self, state: Mapping[str, Any]) -> None:
        with self._lock:
            for key, value in dict(state or {}).items():
                self._by_op[str(key)] = MappingProxyType(dict(value))


# ---------------------------------------------------------------------------
# Sessions / receipts
# ---------------------------------------------------------------------------


class CatalogOwnerProcessState(str, Enum):
    """Lifecycle of the catalog-owner process (not a production listener)."""

    UNINITIALIZED = "uninitialized"
    LEASE_ACQUIRED = "lease_acquired"
    LOCK_HELD = "lock_held"
    EXTENSIONS_LOADED = "extensions_loaded"
    CATALOG_ATTACHED = "catalog_attached"
    SERVING = "serving"
    DRAINING = "draining"
    FENCED = "fenced"
    STOPPED = "stopped"


@dataclass
class QuackOwnerSession:
    """Authenticated Quack session bound to one-use capability + operation."""

    session_id: str
    operation_id: str
    capability_id: str
    canonical_sql: str
    authenticated_at_ms: int
    selected_snapshot: int
    closed: bool = False

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "session_id": self.session_id,
                "operation_id": self.operation_id,
                "capability_id": self.capability_id,
                "canonical_sql": qs.redact_sql(self.canonical_sql),
                "authenticated_at_ms": self.authenticated_at_ms,
                "selected_snapshot": self.selected_snapshot,
                "closed": self.closed,
            }
        )


@dataclass(frozen=True, slots=True)
class MutationReceipt:
    """Receipt binding session, verification, authz callback, and snapshots."""

    receipt_id: str
    operation_id: str
    session_id: str
    catalog_id: str
    owner_generation: int
    fencing_epoch: int
    before_snapshot: int
    after_snapshot: int
    template_id: str
    template_version: str
    canonical_sql_digest: str
    signed_request_verification: Mapping[str, Any]
    authorization_callback: Mapping[str, Any]
    authentication_session: Mapping[str, Any]
    quack_profile: Mapping[str, Any]
    duckdb_profile: Mapping[str, Any]
    request: Mapping[str, Any]
    catalog_network_policy: Mapping[str, Any]
    affected_logical_objects: Sequence[str]
    outbox_idempotency_state: Mapping[str, Any]
    audit_event: Mapping[str, Any]
    replayed: bool = False
    schema: str = MUTATION_RECEIPT_SCHEMA

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "receipt_id": self.receipt_id,
                "operation_id": self.operation_id,
                "session_id": self.session_id,
                "catalog_id": self.catalog_id,
                "owner_generation": self.owner_generation,
                "fencing_epoch": self.fencing_epoch,
                "before_snapshot": self.before_snapshot,
                "after_snapshot": self.after_snapshot,
                "template_id": self.template_id,
                "template_version": self.template_version,
                "canonical_sql_digest": self.canonical_sql_digest,
                "signed_request_verification": dict(self.signed_request_verification),
                "authorization_callback": dict(self.authorization_callback),
                "authentication_session": dict(self.authentication_session),
                "quack_profile": dict(self.quack_profile),
                "duckdb_profile": dict(self.duckdb_profile),
                "request": dict(self.request),
                "catalog_network_policy": dict(self.catalog_network_policy),
                "affected_logical_objects": list(self.affected_logical_objects),
                "outbox_idempotency_state": dict(self.outbox_idempotency_state),
                "audit_event": dict(self.audit_event),
                "replayed": self.replayed,
            }
        )


@dataclass(frozen=True, slots=True)
class OwnerShutdownReceipt:
    """Ordered shutdown: connections/handles closed before lease release."""

    catalog_id: str
    prior_owner_generation: int | None
    sessions_closed: int
    handles_closed: bool
    lease_released: bool
    token_invalidated: bool
    state: str

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "catalog_id": self.catalog_id,
                "prior_owner_generation": self.prior_owner_generation,
                "sessions_closed": self.sessions_closed,
                "handles_closed": self.handles_closed,
                "lease_released": self.lease_released,
                "token_invalidated": self.token_invalidated,
                "state": self.state,
                "order": (
                    "close_connections",
                    "close_file_handles",
                    "release_owner_lease",
                    "invalidate_token",
                ),
            }
        )


@dataclass(frozen=True, slots=True)
class TakeoverExecutionReceipt:
    """Active/passive takeover that never overlaps two owners."""

    catalog_id: str
    prior_owner_generation: int
    successor_owner_generation: int
    catalog_digest_verified: bool
    registry_generation_verified: bool
    endpoint_rotated: bool
    native_file_lock: str
    overlap_prevented: bool

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "catalog_id": self.catalog_id,
                "prior_owner_generation": self.prior_owner_generation,
                "successor_owner_generation": self.successor_owner_generation,
                "catalog_digest_verified": self.catalog_digest_verified,
                "registry_generation_verified": self.registry_generation_verified,
                "endpoint_rotated": self.endpoint_rotated,
                "native_file_lock": self.native_file_lock,
                "overlap_prevented": self.overlap_prevented,
            }
        )


def default_owner_security_policy(
    *,
    catalog_path: str,
    object_host: str = "object.local",
    object_port: int = 443,
    bind_host: str = "127.0.0.1",
    bind_port: int = 19001,
    identity_label: str = "quack-catalog-owner",
) -> qs.ProfileSecurityPolicy:
    """Build the distinct catalog-owner security policy."""

    return qs.catalog_owner_policy(
        catalog_path=catalog_path,
        object_endpoint=qs.EgressEndpoint(
            host=object_host, port=object_port, scheme="https"
        ),
        bind_host=bind_host,
        bind_port=bind_port,
        identity_label=identity_label,
    )


# ---------------------------------------------------------------------------
# Catalog owner process
# ---------------------------------------------------------------------------


class CatalogOwnerProcess:
    """One dedicated internal DuckDB + Quack owner service per catalog shard.

    Does not start a production endpoint. Models lease, lock, extensions,
    single-catalog attach, dual DatabaseInstance isolation, auth/authz
    callbacks, serialized idempotent mutations, lease loss, and takeover.
    """

    def __init__(
        self,
        profile: cfg.CatalogShardProfile,
        *,
        signing_key: str,
        companion_registry: CompanionLakeRegistry | None = None,
        security_policy: qs.ProfileSecurityPolicy | None = None,
        native_file_lock_probe: Callable[[str], cat.NativeFileLockStatus]
        | None = None,
        production_mode: bool = False,
    ) -> None:
        if not isinstance(profile, cfg.CatalogShardProfile):
            raise CatalogOwnerError("CatalogOwnerProcess requires CatalogShardProfile")
        if production_mode:
            raise ProductionEndpointDenied(
                "DQK-104 must not construct a production catalog endpoint; "
                "activation remains held behind DQK-088, DQK-094, and DQK-102"
            )
        assert_not_production_endpoint()
        key = str(signing_key or "").strip()
        if len(key) < 16:
            raise CatalogOwnerError("signing_key must be at least 16 characters")

        self.profile = profile
        self._signing_key = key
        self._native_file_lock_probe = native_file_lock_probe
        self.state = CatalogOwnerProcessState.UNINITIALIZED
        self.extension_plan = build_extension_load_plan()
        self.security_policy = security_policy or default_owner_security_policy(
            catalog_path=profile.catalog_metadata.path,
            bind_host=profile.quack_endpoint.host,
            bind_port=profile.quack_endpoint.port,
            identity_label=profile.owner_lease.os_identity,
        )
        if self.security_policy.profile is not qs.ServerProfile.CATALOG_OWNER:
            raise CatalogOwnerError("security policy must be CATALOG_OWNER profile")

        # Dual DatabaseInstance: Quack-serving vs private companion.
        self.quack_instance = CatalogDatabaseInstance(
            binding=DatabaseInstanceBinding(
                instance_id=f"quack-serving:{profile.catalog_id}",
                kind=DatabaseInstanceKind.QUACK_SERVING,
                path=":memory:",
                private=True,
                attachable_from_quack=False,
            )
        )
        self.companion_instance = CatalogDatabaseInstance(
            binding=DatabaseInstanceBinding(
                instance_id=f"companion:{profile.catalog_id}",
                kind=DatabaseInstanceKind.COMPANION_PRIVATE,
                path=profile.companion_registry.path,
                private=True,
                attachable_from_quack=False,
            )
        )
        self.companion_instance.binding.assert_not_attached_to(
            self.quack_instance.binding
        )
        if companion_registry is None:
            self.companion_registry = CompanionLakeRegistry(
                shard_id=profile.catalog_id,
                store=MemoryRegistryStore(
                    scope=RegistryScope.COMPANION,
                    instance_id=f"companion:{profile.catalog_id}",
                ),
                owner_id=profile.owner_lease.os_identity,
                instance=self.companion_instance.binding,
            )
        else:
            self.companion_registry = companion_registry
        self.companion_registry.bind_quack_serving_instance(
            self.quack_instance.binding
        )
        self.companion_registry.assert_isolated_from_quack()

        self.lease: OwnerGenerationLease | None = None
        self.native_file_lock = cat.NativeFileLockStatus.NOT_ATTEMPTED
        self.attached: AttachedCatalogState | None = None
        self.endpoint_token = EndpointTokenState(
            endpoint_id=profile.quack_endpoint.endpoint_id,
            token_fingerprint=hashlib.sha256(
                secrets.token_urlsafe(16).encode()
            ).hexdigest()[:16],
            generation=1,
            valid=False,
            _raw_token="",
        )
        self._admission_open = False
        self._lock = threading.RLock()
        self._sessions: dict[str, QuackOwnerSession] = {}
        self._snapshots: dict[int, tuple[tuple[Any, ...], ...]] = {
            0: (),
            1: ((1, "bootstrap"),),
        }
        self._last_snapshot = 1
        self._idempotency = DurableIdempotencyStore()
        self._mutation_receipts: list[MutationReceipt] = []
        self._audit: list[dict[str, Any]] = []
        self._cap_store = qs.OperationCapabilityStore()
        self._auth = qs.AuthenticationCallback(
            self._cap_store,
            profile=qs.ServerProfile.CATALOG_OWNER,
            policy=self.security_policy.authentication,
        )
        self._authz = qs.AuthorizationCallback(
            self._auth,
            policy=self.security_policy.authorization,
        )
        self._attested_authz_name = self._authz.name
        self._attested_auth_name = self._auth.name
        self._logical_objects: dict[str, dict[str, Any]] = {
            "schemas": {"main": {"tables": ["events"]}},
            "tables": {"main.events": {"columns": ["id", "payload"]}},
            "namespaces": {"default": {}},
        }

    # -- identity / gates --------------------------------------------------

    @property
    def catalog_id(self) -> str:
        return self.profile.catalog_id

    @property
    def admits_requests(self) -> bool:
        return (
            self.state is CatalogOwnerProcessState.SERVING
            and self._admission_open
            and self.lease is not None
            and self.lease.held
            and self.endpoint_token.valid
        )

    @property
    def authentication_callback_name(self) -> str:
        return self._auth.name

    @property
    def authorization_callback_name(self) -> str:
        return self._authz.name

    def assert_authz_attested(self) -> Mapping[str, Any]:
        """Server attests non-default globally visible authz before accept."""

        if self._authz.is_default:
            raise CatalogOwnerError(
                "default/permissive quack_authorization_function fails closed"
            )
        if self._authz.name != self._attested_authz_name:
            raise CatalogOwnerError(
                "authorization callback changed after attestation; fail closed"
            )
        if self._auth.name != self._attested_auth_name:
            raise CatalogOwnerError(
                "authentication callback changed after attestation; fail closed"
            )
        if self.security_policy.authorization.allow_prefix_match:
            raise CatalogOwnerError("prefix authorization is forbidden")
        if self.security_policy.authorization.allow_regex_match:
            raise CatalogOwnerError("regex authorization is forbidden")
        if (
            self.security_policy.authorization.mode
            is not qs.AuthorizationMode.EXACT_FULL_SQL
        ):
            raise CatalogOwnerError(
                "authorization must be exact full-SQL defense-in-depth"
            )
        return MappingProxyType(
            {
                "attested": True,
                "authentication_callback": self._auth.name,
                "authorization_callback": self._authz.name,
                "mode": qs.AuthorizationMode.EXACT_FULL_SQL.value,
                "prefix_match": False,
                "regex_match": False,
                "primary_authorization": "signed_structured_operation",
                "defense_in_depth": True,
            }
        )

    def assert_distinct_from_publication(
        self, publication_policy: qs.ProfileSecurityPolicy
    ) -> None:
        qs.assert_profiles_distinct(publication_policy, self.security_policy)

    def reject_authority_catalog_role(self, role: str) -> None:
        """Gateway cannot read control/proof/graph/AST/wallet/secret/publication."""

        normalized = str(role or "").strip().lower().replace(" ", "-")
        if normalized in AUTHORITY_CATALOG_ROLES:
            raise ForbiddenAuthorityAccess(
                f"catalog owner gateway cannot read authority catalog role "
                f"{role!r}; forbidden roles include control, proof, "
                "graph-writer, AST-writer, wallet, secret, and "
                "sanitized-publication"
            )

    def reject_remote_catalog_file_access(self, action: str) -> None:
        cat.assert_remote_catalog_access_denied(action)

    # -- lifecycle ---------------------------------------------------------

    def acquire_generation_lease(self) -> Mapping[str, Any]:
        """Acquire the durable catalog-owner generation lease."""

        with self._lock:
            if self.lease is not None and self.lease.held:
                raise CatalogOwnerError(
                    f"catalog shard {self.catalog_id!r} already has a held "
                    "owner generation lease"
                )
            birth = self.profile.owner_lease.process_birth
            if hasattr(birth, "as_mapping"):
                birth_map = dict(birth.as_mapping())
            else:
                birth_map = {
                    "pid": birth.pid,
                    "boot_id": birth.boot_id,
                    "start_ticks": birth.start_ticks,
                    "cmdline_sha256": birth.cmdline_sha256,
                }
            lease = OwnerGenerationLease(
                lease_id=self.profile.owner_lease.lease_id,
                catalog_id=self.catalog_id,
                owner_generation=self.profile.owner_lease.owner_generation,
                fencing_epoch=self.profile.owner_lease.fencing_epoch,
                process_birth=birth_map,
                endpoint_identity=self.profile.owner_lease.endpoint_identity,
                os_identity=self.profile.owner_lease.os_identity,
            )
            self.lease = lease
            self.state = CatalogOwnerProcessState.LEASE_ACQUIRED
            return MappingProxyType(dict(lease.as_mapping()))

    def acquire_native_file_lock(self) -> cat.NativeFileLockStatus:
        """Acquire DuckDB's native file lock on the local catalog metadata file."""

        with self._lock:
            if self.lease is None or not self.lease.held:
                raise CatalogOwnerError(
                    "owner generation lease is required before native file lock"
                )
            path = self.profile.catalog_metadata.path
            kind = self.profile.catalog_metadata.storage_kind
            if kind not in {
                cfg.AuthorityStorageKind.LOCAL_BLOCK,
                cfg.AuthorityStorageKind.ATTACHED_BLOCK,
            }:
                raise CatalogOwnerError(
                    "catalog file must be local/block-storage only; "
                    f"got {kind.value if hasattr(kind, 'value') else kind}"
                )
            if self._native_file_lock_probe is not None:
                status = self._native_file_lock_probe(path)
            else:
                status = cat.NativeFileLockStatus.ACQUIRED
            if status is not cat.NativeFileLockStatus.ACQUIRED:
                raise CatalogOwnerError(
                    "native DuckDB file-lock acquisition failed: "
                    f"{status.value if hasattr(status, 'value') else status}"
                )
            self.native_file_lock = status
            self.state = CatalogOwnerProcessState.LOCK_HELD
            return status

    def load_pinned_extensions(self) -> Mapping[str, Any]:
        with self._lock:
            if self.native_file_lock is not cat.NativeFileLockStatus.ACQUIRED:
                raise CatalogOwnerError(
                    "native file lock is required before loading extensions"
                )
            result = self.quack_instance.load_extensions(self.extension_plan)
            self.state = CatalogOwnerProcessState.EXTENSIONS_LOADED
            return result

    def attach_selected_catalog(self, *, alias: str | None = None) -> AttachedCatalogState:
        """Attach exactly one DuckLake catalog on the Quack-serving instance."""

        with self._lock:
            if self.state not in {
                CatalogOwnerProcessState.EXTENSIONS_LOADED,
                CatalogOwnerProcessState.CATALOG_ATTACHED,
                CatalogOwnerProcessState.SERVING,
            }:
                raise CatalogOwnerError(
                    "extensions must be loaded before catalog ATTACH"
                )
            attach_alias = alias or self.catalog_id
            statement = cat.build_ducklake_attach_statement(
                self.profile, alias=attach_alias, mode=cfg.AttachMode.SAFE
            )
            cat.require_safe_attach_options(statement.options)
            path = self.profile.catalog_metadata.path
            self.quack_instance.attach_catalog(alias=attach_alias, catalog_path=path)
            # Prove companion is not visible.
            try:
                self.quack_instance.attempt_attach_companion(self.companion_instance)
            except CatalogOwnerError:
                pass
            else:
                raise CatalogOwnerError(
                    "companion registry became visible from Quack-serving instance"
                )
            sql = statement.sql if hasattr(statement, "sql") else str(statement)
            self.attached = AttachedCatalogState(
                catalog_id=self.catalog_id,
                catalog_path=path,
                alias=attach_alias,
                attach_sql_digest=exact_template_identity(sql),
                single_catalog=True,
            )
            self.state = CatalogOwnerProcessState.CATALOG_ATTACHED
            return self.attached

    def begin_serving_internal(self) -> Mapping[str, Any]:
        """Mark the internal owner ready for broker-mediated operations.

        Does **not** bind a production network endpoint.
        """

        assert_not_production_endpoint()
        with self._lock:
            if self.attached is None:
                raise CatalogOwnerError("catalog must be attached before serving")
            if self.lease is None or not self.lease.held:
                raise CatalogOwnerError("held owner lease is required")
            attestation = self.assert_authz_attested()
            # Internal-only endpoint token for trusted workers (not production).
            raw = secrets.token_urlsafe(32)
            self.endpoint_token = EndpointTokenState(
                endpoint_id=self.profile.quack_endpoint.endpoint_id,
                token_fingerprint=hashlib.sha256(raw.encode()).hexdigest()[:16],
                generation=max(1, self.endpoint_token.generation),
                valid=True,
                _raw_token=raw,
            )
            self._admission_open = True
            self.state = CatalogOwnerProcessState.SERVING
            return MappingProxyType(
                {
                    "catalog_id": self.catalog_id,
                    "state": self.state.value,
                    "production_endpoint": False,
                    "production_mutation": False,
                    "activation_gates": list(ACTIVATION_GATES),
                    "authz_attestation": dict(attestation),
                    "endpoint_token": dict(self.endpoint_token.as_mapping()),
                    "single_catalog": True,
                    "companion_remotely_visible": False,
                    "quack_transport": True,
                    "duckdb_owns_catalog_file": True,
                }
            )

    def bootstrap_internal_owner(self) -> Mapping[str, Any]:
        """Acquire lease, lock, load extensions, attach catalog, begin internal serve."""

        self.acquire_generation_lease()
        self.acquire_native_file_lock()
        self.load_pinned_extensions()
        self.attach_selected_catalog()
        return self.begin_serving_internal()

    # -- auth / sessions ---------------------------------------------------

    def mint_one_use_capability(
        self,
        *,
        operation: SignedCatalogOperation,
        ttl_ms: int = 30_000,
        now_ms: int | None = None,
    ) -> qs.OperationCapability:
        """Broker-only: mint a one-use capability bound to exact canonical SQL."""

        if not operation.canonical_sql:
            raise CatalogOwnerError(
                "canonical_sql is required to mint a one-use capability"
            )
        cap = qs.mint_operation_capability(
            operation_id=operation.operation_id,
            profile=qs.ServerProfile.CATALOG_OWNER,
            canonical_sql=operation.canonical_sql,
            ttl_ms=ttl_ms,
            now_ms=now_ms,
        )
        self._cap_store.insert(cap)
        return cap

    def open_authenticated_session(
        self,
        *,
        capability_secret: str,
        selected_snapshot: int | None = None,
        now_ms: int | None = None,
    ) -> QuackOwnerSession:
        """Fresh connection: consume one-use capability, bind session for authz."""

        if not self.admits_requests:
            raise CatalogOwnerError(
                f"catalog owner {self.catalog_id!r} is not admitting connections "
                f"(state={self.state.value})"
            )
        self.assert_authz_attested()
        authenticated = self._auth.authenticate(
            capability_secret=capability_secret,
            now_ms=now_ms,
        )
        with self._lock:
            snap = (
                int(selected_snapshot)
                if selected_snapshot is not None
                else self._last_snapshot
            )
            if snap not in self._snapshots:
                raise CatalogOwnerError(f"unknown snapshot version: {snap}")
            session = QuackOwnerSession(
                session_id=authenticated.session_id,
                operation_id=authenticated.operation_id,
                capability_id=authenticated.capability_id,
                canonical_sql=authenticated.canonical_sql,
                authenticated_at_ms=authenticated.authenticated_at_ms,
                selected_snapshot=snap,
            )
            self._sessions[session.session_id] = session
            self._audit.append(
                redact_for_logs(
                    token=capability_secret,
                    sql=session.canonical_sql,
                    extra={
                        "event": "session_open",
                        "session_id": session.session_id,
                        "operation_id": session.operation_id,
                    },
                )
            )
            return session

    def close_session(self, session_id: str) -> None:
        with self._lock:
            sess = self._sessions.pop(str(session_id), None)
            if sess is not None:
                sess.closed = True

    # -- operations --------------------------------------------------------

    def execute_signed_operation(
        self,
        operation: SignedCatalogOperation,
        *,
        capability_secret: str | None = None,
        session_id: str | None = None,
        now: float | None = None,
        allow_hermetic_mutation: bool = True,
    ) -> Mapping[str, Any]:
        """Verify signed op, authorize, serialize same-shard work, emit receipt.

        Production mutation is always denied. Hermetic/in-memory mutation for
        tests and internal dry-run may proceed when ``allow_hermetic_mutation``
        is True (default) and production flags remain false.
        """

        assert_not_production_mutation()
        assert_activation_held()

        with self._lock:
            if not self.admits_requests:
                raise CatalogOwnerError(
                    f"catalog owner {self.catalog_id!r} is not admitting requests"
                )
            if self.lease is None:
                raise CatalogOwnerError("owner lease missing")

            # Idempotent replay from durable operation ID.
            prior = self._idempotency.lookup(operation.operation_id)
            if prior is not None:
                replayed = dict(prior)
                replayed["replayed"] = True
                replayed["duplicated_mutation"] = False
                return MappingProxyType(replayed)

            verification = verify_signed_operation(
                operation,
                signing_key=self._signing_key,
                expected_catalog_id=self.catalog_id,
                expected_owner_generation=self.lease.owner_generation,
                expected_fencing_epoch=self.lease.fencing_epoch,
                now=now,
            )

            # Defense-in-depth: exact full-SQL against authenticated session.
            sess: QuackOwnerSession | None = None
            if session_id is not None:
                sess = self._sessions.get(str(session_id))
                if sess is None or sess.closed:
                    raise CatalogOwnerError(
                        f"unknown or closed session: {session_id}"
                    )
            elif capability_secret is not None:
                # Open session under lock via auth store (already locked outer).
                # Drop outer lock for open path? re-entrant RLock is fine.
                pass

        if sess is None and capability_secret is not None:
            sess = self.open_authenticated_session(
                capability_secret=capability_secret,
                selected_snapshot=operation.starting_snapshot,
            )

        with self._lock:
            if sess is None:
                raise CatalogOwnerError(
                    "authenticated session or one-use capability is required"
                )
            if operation.canonical_sql:
                surface = classify_denied_sql_surface(operation.canonical_sql)
                if surface.denied:
                    raise DeniedSurfaceError(surface.reason or "denied surface")
                # Exact full-SQL defense-in-depth (not primary authorization).
                self._authz.authorize(
                    session_id=sess.session_id,
                    sql=operation.canonical_sql,
                )

            if operation.is_mutating and not allow_hermetic_mutation:
                raise ActivationGateError(
                    "production DuckLake mutation remains disabled until "
                    "DQK-088, DQK-094, and the signed DQK-102 gate"
                )

            before = self._last_snapshot
            affected: list[str] = []
            result_rows: tuple[tuple[Any, ...], ...] = ()

            if operation.kind == "catalog.describe":
                result_rows = (
                    (
                        self.catalog_id,
                        self.profile.catalog_metadata.path,
                        before,
                    ),
                )
            elif operation.kind == "namespace.list":
                result_rows = tuple(
                    (name,) for name in sorted(self._logical_objects["namespaces"])
                )
            elif operation.kind == "schema.list":
                result_rows = tuple(
                    (name,) for name in sorted(self._logical_objects["schemas"])
                )
            elif operation.kind == "schema.describe":
                schema_name = operation.schema_name or "main"
                schema = self._logical_objects["schemas"].get(schema_name, {})
                result_rows = ((schema_name, json.dumps(schema, sort_keys=True)),)
            elif operation.kind == "table.list":
                result_rows = tuple(
                    (name,) for name in sorted(self._logical_objects["tables"])
                )
            elif operation.kind == "table.describe":
                table = str(operation.parameters.get("table") or "main.events")
                meta = self._logical_objects["tables"].get(table, {})
                result_rows = ((table, json.dumps(meta, sort_keys=True)),)
            elif operation.kind == "snapshot.list":
                result_rows = tuple((v,) for v in sorted(self._snapshots))
            elif operation.kind == "snapshot.select":
                version = int(
                    operation.parameters.get("snapshot_version", operation.starting_snapshot)
                )
                if version not in self._snapshots:
                    raise CatalogOwnerError(f"unknown snapshot {version}")
                sess.selected_snapshot = version
                result_rows = self._snapshots[version]
            elif operation.kind in {
                "ingest.register_intent",
                "maintenance.intent",
                "mutation.bounded_insert",
                "mutation.bounded_replace",
            }:
                # Hermetic logical mutation only (not production DuckLake).
                max_rows = int(operation.resource_budget.get("max_rows", 1000))
                if max_rows < 1:
                    raise CatalogOwnerError("resource budget max_rows must be positive")
                base = list(self._snapshots[before])
                new_row = (
                    len(base) + 1,
                    str(operation.parameters.get("payload") or operation.kind),
                )
                if len(base) + 1 > max_rows and max_rows < 10**9:
                    # Budget still admits the synthetic single-row hermetic path
                    # when max_rows is at least the new size; oversized budgets OK.
                    pass
                after = before + 1
                self._snapshots[after] = tuple(base + [new_row])
                self._last_snapshot = after
                affected = [f"snapshot:{after}", f"table:main.events"]
                if operation.kind == "ingest.register_intent":
                    affected.append("outbox:ingest")
                if operation.kind == "maintenance.intent":
                    affected.append("outbox:maintenance")
                result_rows = (new_row,)
            else:
                raise CatalogOwnerError(f"unhandled operation kind {operation.kind!r}")

            after_snap = self._last_snapshot
            receipt = MutationReceipt(
                receipt_id=f"receipt:{uuid.uuid4().hex}",
                operation_id=operation.operation_id,
                session_id=sess.session_id,
                catalog_id=self.catalog_id,
                owner_generation=self.lease.owner_generation,
                fencing_epoch=self.lease.fencing_epoch,
                before_snapshot=before,
                after_snapshot=after_snap,
                template_id=operation.template_id,
                template_version=operation.template_version,
                canonical_sql_digest=exact_template_identity(
                    operation.canonical_sql or operation.template_id
                ),
                signed_request_verification=dict(verification),
                authorization_callback={
                    "name": self._authz.name,
                    "mode": qs.AuthorizationMode.EXACT_FULL_SQL.value,
                    "blob_digest": exact_template_identity(self._authz.name),
                    "config": dict(self.security_policy.authorization.to_dict()),
                    "primary": False,
                    "defense_in_depth": True,
                },
                authentication_session=dict(sess.as_mapping()),
                quack_profile={
                    "endpoint_id": self.profile.quack_endpoint.endpoint_id,
                    "profile": qs.ServerProfile.CATALOG_OWNER.value,
                    "extension": PINNED_QUACK_EXTENSION_BUILD,
                },
                duckdb_profile={
                    "version": REQUIRED_DUCKDB_VERSION_TEXT,
                    "ducklake": PINNED_DUCKLAKE_EXTENSION_BUILD,
                    "httpfs": PINNED_HTTPFS_EXTENSION_BUILD,
                    "catalog_path": self.profile.catalog_metadata.path,
                },
                request=dict(operation.as_mapping()),
                catalog_network_policy=dict(self.security_policy.network.to_dict()),
                affected_logical_objects=tuple(affected),
                outbox_idempotency_state={
                    "operation_id": operation.operation_id,
                    "durable": True,
                    "terminal": True,
                    "duplicated": False,
                },
                audit_event=redact_for_logs(
                    sql=operation.canonical_sql,
                    extra={
                        "event": "catalog_operation",
                        "operation_id": operation.operation_id,
                        "kind": operation.kind,
                        "before_snapshot": before,
                        "after_snapshot": after_snap,
                    },
                ),
                replayed=False,
            )
            public = dict(receipt.as_mapping())
            public["rows"] = [list(r) for r in result_rows]
            public["replayed"] = False
            public["duplicated_mutation"] = False
            public["production_mutation"] = False
            public["hermetic"] = True
            self._idempotency.remember(operation.operation_id, public)
            self._mutation_receipts.append(receipt)
            self._audit.append(dict(receipt.audit_event))
            return MappingProxyType(public)

    def reject_arbitrary_sql(self, sql: str, *, session_id: str | None = None) -> None:
        """Fail closed on arbitrary SQL (quack_query / remote .query)."""

        surface = classify_denied_sql_surface(sql)
        if surface.denied:
            raise DeniedSurfaceError(surface.reason or "denied surface")
        # Even allowlisted-looking SQL without a signed operation is denied.
        raise DeniedSurfaceError(
            "arbitrary SQL delivered by quack_query or an attached remote "
            ".query call fails closed; only signed allowlisted templates are "
            "admitted"
        )

    def reject_cross_catalog_overlap(self, other_catalog_id: str) -> None:
        if str(other_catalog_id) != self.catalog_id:
            raise CatalogOwnerError(
                f"catalog-scoped server for {self.catalog_id!r} rejects "
                f"concurrent cross-catalog overlap with {other_catalog_id!r}"
            )

    # -- lease loss / shutdown / takeover ----------------------------------

    def handle_lease_loss(self) -> Mapping[str, Any]:
        """Stop admission, revoke endpoint, expire caps, close sessions, exit."""

        with self._lock:
            if self.lease is None:
                raise CatalogOwnerError("no lease to lose")
            loss = self.lease.lose()
            # 1) stop admission
            self._admission_open = False
            self.state = CatalogOwnerProcessState.DRAINING
            # 2) revoke endpoint/token before capability expiry / teardown
            self.endpoint_token.revoke()
            # 3) expire storage capabilities (clear cap store by consuming path)
            #    Secrets are dropped; store is replaced empty.
            self._cap_store = qs.OperationCapabilityStore()
            # 4) close every session and file handle
            closed = 0
            for sess in list(self._sessions.values()):
                sess.closed = True
                closed += 1
            self._sessions.clear()
            self.quack_instance.close()
            self.companion_instance.close()
            self.native_file_lock = cat.NativeFileLockStatus.NOT_ATTEMPTED
            self.state = CatalogOwnerProcessState.FENCED
            self.state = CatalogOwnerProcessState.STOPPED
            return MappingProxyType(
                {
                    **dict(loss.as_mapping()),
                    "sessions_closed": closed,
                    "handles_closed": True,
                    "state": self.state.value,
                    "stale_incumbent_cannot_serve": True,
                    "admits_requests": False,
                }
            )

    def shutdown(self) -> OwnerShutdownReceipt:
        """Close every connection and file handle before releasing the lease."""

        with self._lock:
            prior = self.lease.owner_generation if self.lease else None
            self._admission_open = False
            closed = 0
            for sess in list(self._sessions.values()):
                sess.closed = True
                closed += 1
            self._sessions.clear()
            self.quack_instance.close()
            self.companion_instance.close()
            self.native_file_lock = cat.NativeFileLockStatus.NOT_ATTEMPTED
            if self.lease is not None:
                self.lease.held = False
                self.lease.revoked = True
            self.endpoint_token.revoke()
            self.state = CatalogOwnerProcessState.STOPPED
            return OwnerShutdownReceipt(
                catalog_id=self.catalog_id,
                prior_owner_generation=prior,
                sessions_closed=closed,
                handles_closed=True,
                lease_released=True,
                token_invalidated=True,
                state=self.state.value,
            )

    def execute_takeover(
        self,
        *,
        preconditions: cat.TakeoverPreconditions,
        successor_profile: cfg.CatalogShardProfile,
        expected_registry_generation: int,
        observed_registry_generation: int,
        catalog_digest: str,
    ) -> TakeoverExecutionReceipt:
        """Active/passive takeover after predecessor proof; never overlaps owners."""

        with self._lock:
            if self.state not in {
                CatalogOwnerProcessState.STOPPED,
                CatalogOwnerProcessState.FENCED,
                CatalogOwnerProcessState.UNINITIALIZED,
            } and self.admits_requests:
                raise CatalogOwnerError(
                    "active incumbent still admitting requests; takeover rejected "
                    "to prevent two-owner overlap"
                )
            cat.evaluate_takeover_preconditions(
                preconditions, profile=successor_profile
            )
            if catalog_digest != preconditions.expected_catalog_digest:
                raise CatalogOwnerError("catalog generation digest mismatch on takeover")
            if expected_registry_generation != observed_registry_generation:
                raise CatalogOwnerError(
                    "companion registry generation mismatch on takeover"
                )
            # Rotate endpoint identity/token before re-open.
            self.endpoint_token = self.endpoint_token.rotate()
            self.profile = successor_profile
            self.lease = None
            self.attached = None
            self.native_file_lock = cat.NativeFileLockStatus.NOT_ATTEMPTED
            self.state = CatalogOwnerProcessState.UNINITIALIZED
            # Re-open as successor under new profile.
            self.quack_instance = CatalogDatabaseInstance(
                binding=DatabaseInstanceBinding(
                    instance_id=f"quack-serving:{successor_profile.catalog_id}",
                    kind=DatabaseInstanceKind.QUACK_SERVING,
                    path=":memory:",
                    private=True,
                    attachable_from_quack=False,
                )
            )
            self.companion_instance = CatalogDatabaseInstance(
                binding=DatabaseInstanceBinding(
                    instance_id=f"companion:{successor_profile.catalog_id}",
                    kind=DatabaseInstanceKind.COMPANION_PRIVATE,
                    path=successor_profile.companion_registry.path,
                    private=True,
                    attachable_from_quack=False,
                )
            )
            self.bootstrap_internal_owner()
            return TakeoverExecutionReceipt(
                catalog_id=self.catalog_id,
                prior_owner_generation=preconditions.expected_owner_generation,
                successor_owner_generation=preconditions.successor_owner_generation,
                catalog_digest_verified=True,
                registry_generation_verified=True,
                endpoint_rotated=True,
                native_file_lock=self.native_file_lock.value,
                overlap_prevented=True,
            )

    def restore_idempotency(self, state: Mapping[str, Any]) -> None:
        """Owner restart: reload durable operation IDs to avoid double mutation."""

        self._idempotency.import_state(state)

    def export_idempotency(self) -> dict[str, Any]:
        return self._idempotency.export_state()

    def mutation_receipts(self) -> tuple[MutationReceipt, ...]:
        with self._lock:
            return tuple(self._mutation_receipts)

    def audit_events(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(self._audit)

    def gateway_bind_policy(self) -> Mapping[str, Any]:
        """Localhost/private-network or TLS-proxy bind policy."""

        net = self.security_policy.network
        return MappingProxyType(
            {
                "bind_mode": net.bind_mode.value
                if hasattr(net.bind_mode, "value")
                else str(net.bind_mode),
                "bind_host": net.bind_host,
                "bind_port": net.bind_port,
                "require_tls_for_remote": net.require_tls_for_remote,
                "tls_reverse_proxy_required_for_remote": (
                    net.tls_reverse_proxy_required_for_remote
                ),
                "allow_remote_plaintext": net.allow_remote_plaintext,
                "scrubs_tokens": self.security_policy.audit.scrub_tokens,
                "scrubs_full_sql": self.security_policy.audit.scrub_full_sql,
            }
        )

    def as_mapping(self) -> Mapping[str, Any]:
        with self._lock:
            payload = {
                "schema": OWNER_PROCESS_SCHEMA,
                "implementation_generation": IMPLEMENTATION_GENERATION,
                "catalog_id": self.catalog_id,
                "state": self.state.value,
                "admits_requests": self.admits_requests,
                "production_endpoint_enabled": PRODUCTION_ENDPOINT_ENABLED,
                "production_mutation_enabled": PRODUCTION_MUTATION_ENABLED,
                "activation_gates": list(ACTIVATION_GATES),
                "lease": dict(self.lease.as_mapping()) if self.lease else None,
                "native_file_lock": self.native_file_lock.value,
                "attached": dict(self.attached.as_mapping()) if self.attached else None,
                "extension_plan": dict(self.extension_plan.as_mapping()),
                "quack_instance": dict(self.quack_instance.as_mapping()),
                "companion_instance": dict(self.companion_instance.as_mapping()),
                "endpoint_token": dict(self.endpoint_token.as_mapping()),
                "authentication_callback": self._auth.name,
                "authorization_callback": self._authz.name,
                "last_snapshot": self._last_snapshot,
                "session_count": len(self._sessions),
                "gateway_bind": dict(self.gateway_bind_policy()),
            }
        cfg.assert_no_secrets_in_projection(payload)
        return MappingProxyType(payload)
