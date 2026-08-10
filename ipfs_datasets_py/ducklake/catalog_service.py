"""Trusted broker and catalog-management service for DQK-104.

The broker independently validates each signed structured operation outside
the Quack SQL callback, injects a one-use endpoint credential only into an
identity-bound trusted worker, emits a versioned allowlisted parameterized SQL
transaction, serializes same-shard mutations, and returns typed results and
receipts. Untrusted agents receive neither raw SQL nor reusable Quack tokens.

Independent catalog shards may execute concurrently; federation of receipted
snapshot vectors is left to DQK-091.

This module never starts or promotes a production catalog endpoint and never
performs production DuckLake mutation. Activation remains held behind
DQK-088, DQK-094, and the signed DQK-102 gate.

Import is side-effect free.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Sequence

from ipfs_datasets_py.duckdb_control import quack_security as qs
from ipfs_datasets_py.ducklake import catalog as cat
from ipfs_datasets_py.ducklake import config as cfg
from ipfs_datasets_py.ducklake import quack_catalog as qc

__all__ = [
    "ALLOWLISTED_TEMPLATES",
    "CATALOG_SERVICE_SCHEMA",
    "IMPLEMENTATION_GENERATION",
    "TEMPLATE_REGISTRY_VERSION",
    "BoundedOperationResult",
    "CatalogManagementService",
    "CatalogServiceError",
    "OperationTemplate",
    "TrustedCatalogBroker",
    "UntrustedAgentDenied",
    "WorkerInjection",
    "assert_production_activation_held",
    "build_signed_operation",
    "canonical_template_sql",
    "default_template_registry",
    "sign_operation_payload",
]


CATALOG_SERVICE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-catalog-management-service@1"
)
IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-104-catalog-management-service-20260810"
)
TEMPLATE_REGISTRY_VERSION: Final[str] = qc.TEMPLATE_REGISTRY_VERSION


class CatalogServiceError(ValueError):
    """Fail-closed catalog management / broker rejection."""


class UntrustedAgentDenied(CatalogServiceError):
    """Untrusted agents never receive capabilities, tokens, or raw SQL."""


# ---------------------------------------------------------------------------
# Allowlisted versioned templates
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OperationTemplate:
    """Versioned allowlisted parameterized SQL template."""

    template_id: str
    version: str
    kind: str
    canonical_sql: str
    description: str
    mutating: bool = False
    max_rows_default: int = 1000

    def __post_init__(self) -> None:
        if self.kind not in qc.ALLOWED_OPERATION_KINDS:
            raise CatalogServiceError(
                f"template kind {self.kind!r} is not allowlisted"
            )
        if not self.canonical_sql.strip():
            raise CatalogServiceError("template canonical_sql is required")
        surface = qc.classify_denied_sql_surface(self.canonical_sql)
        if surface.denied:
            raise CatalogServiceError(
                f"template SQL denied: {surface.reason}"
            )
        # Templates must not be multi-statement.
        if ";" in self.canonical_sql.rstrip().rstrip(";"):
            # Allow a single trailing semicolon only.
            body = self.canonical_sql.rstrip()
            if body.endswith(";"):
                body = body[:-1]
            if ";" in body:
                raise CatalogServiceError(
                    "templates must be single-statement (no multi-statement escape)"
                )

    @property
    def identity(self) -> str:
        return qc.exact_template_identity(self.canonical_sql)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "template_id": self.template_id,
                "version": self.version,
                "kind": self.kind,
                "canonical_sql_digest": self.identity,
                "canonical_sql_redacted": qs.redact_sql(self.canonical_sql),
                "description": self.description,
                "mutating": self.mutating,
                "max_rows_default": self.max_rows_default,
            }
        )


def canonical_template_sql(kind: str, *, catalog_alias: str = "lake") -> str:
    """Return the broker's versioned canonical SQL for an allowlisted kind."""

    alias = str(catalog_alias or "lake").strip() or "lake"
    templates = {
        "catalog.describe": (
            f"SELECT catalog_id, path, snapshot FROM {alias}.catalog_describe "
            f"WHERE catalog_id = $catalog_id"
        ),
        "namespace.list": f"SELECT namespace_name FROM {alias}.namespaces ORDER BY 1",
        "schema.list": f"SELECT schema_name FROM {alias}.schemas ORDER BY 1",
        "schema.describe": (
            f"SELECT schema_name, metadata FROM {alias}.schema_describe "
            f"WHERE schema_name = $schema_name"
        ),
        "table.list": f"SELECT table_name FROM {alias}.tables ORDER BY 1",
        "table.describe": (
            f"SELECT table_name, metadata FROM {alias}.table_describe "
            f"WHERE table_name = $table_name"
        ),
        "snapshot.list": (
            f"SELECT snapshot_version FROM {alias}.snapshots ORDER BY 1"
        ),
        "snapshot.select": (
            f"SELECT * FROM {alias}.snapshot_rows "
            f"WHERE snapshot_version = $snapshot_version LIMIT $max_rows"
        ),
        "ingest.register_intent": (
            f"INSERT INTO {alias}.ingest_intent "
            f"(operation_id, source_id, payload) "
            f"VALUES ($operation_id, $source_id, $payload)"
        ),
        "maintenance.intent": (
            f"INSERT INTO {alias}.maintenance_intent "
            f"(operation_id, action, payload) "
            f"VALUES ($operation_id, $action, $payload)"
        ),
        "mutation.bounded_insert": (
            f"INSERT INTO {alias}.events (id, payload) "
            f"VALUES ($id, $payload)"
        ),
        "mutation.bounded_replace": (
            f"INSERT INTO {alias}.events_replace (id, payload) "
            f"VALUES ($id, $payload)"
        ),
    }
    try:
        return templates[kind]
    except KeyError as exc:
        raise CatalogServiceError(f"no canonical SQL for kind {kind!r}") from exc


def default_template_registry(
    *, catalog_alias: str = "lake"
) -> Mapping[str, OperationTemplate]:
    """Build the versioned allowlisted template registry."""

    specs: list[tuple[str, str, bool, str]] = [
        ("catalog.describe", "catalog.describe", False, "Describe the selected catalog"),
        ("namespace.list", "namespace.list", False, "List namespaces"),
        ("schema.list", "schema.list", False, "List schemas"),
        ("schema.describe", "schema.describe", False, "Describe one schema"),
        ("table.list", "table.list", False, "List tables"),
        ("table.describe", "table.describe", False, "Describe one table"),
        ("snapshot.list", "snapshot.list", False, "List snapshot versions"),
        ("snapshot.select", "snapshot.select", False, "Select a snapshot (bounded)"),
        (
            "ingest.register_intent",
            "ingest.register_intent",
            True,
            "Register ingest intent (hermetic)",
        ),
        (
            "maintenance.intent",
            "maintenance.intent",
            True,
            "Register maintenance intent (hermetic)",
        ),
        (
            "mutation.bounded_insert",
            "mutation.bounded_insert",
            True,
            "Bounded insert mutation (hermetic)",
        ),
        (
            "mutation.bounded_replace",
            "mutation.bounded_replace",
            True,
            "Bounded replace mutation (hermetic)",
        ),
    ]
    registry: dict[str, OperationTemplate] = {}
    for template_id, kind, mutating, description in specs:
        registry[template_id] = OperationTemplate(
            template_id=template_id,
            version=TEMPLATE_REGISTRY_VERSION,
            kind=kind,
            canonical_sql=canonical_template_sql(kind, catalog_alias=catalog_alias),
            description=description,
            mutating=mutating,
        )
    return MappingProxyType(registry)


ALLOWLISTED_TEMPLATES: Final[Mapping[str, OperationTemplate]] = (
    default_template_registry()
)


# ---------------------------------------------------------------------------
# Signing helpers
# ---------------------------------------------------------------------------


def sign_operation_payload(
    payload: Mapping[str, Any], *, signing_key: str
) -> str:
    body = json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    digest = hmac.new(
        signing_key.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return f"sha256:{digest}"


def build_signed_operation(
    *,
    kind: str,
    tenant_id: str,
    catalog_id: str,
    owner_generation: int,
    fencing_epoch: int,
    starting_snapshot: int,
    caller_process_birth: Mapping[str, Any],
    signing_key: str,
    schema_name: str = "main",
    parameters: Mapping[str, Any] | None = None,
    expected_effects: Mapping[str, Any] | None = None,
    resource_budget: Mapping[str, Any] | None = None,
    ttl_seconds: float = 60.0,
    now: float | None = None,
    operation_id: str | None = None,
    catalog_alias: str = "lake",
    nonce: str | None = None,
) -> qc.SignedCatalogOperation:
    """Construct a signed allowlisted operation for a trusted broker path."""

    if kind not in qc.ALLOWED_OPERATION_KINDS:
        raise CatalogServiceError(f"kind {kind!r} is not allowlisted")
    template = default_template_registry(catalog_alias=catalog_alias)[kind]
    clock = time.time() if now is None else float(now)
    op_id = operation_id or f"op:{uuid.uuid4().hex}"
    budget = dict(
        resource_budget
        or {"max_rows": template.max_rows_default, "max_bytes": 1_048_576}
    )
    effects = dict(
        expected_effects
        or {
            "mutating": template.mutating,
            "catalog_id": catalog_id,
            "kind": kind,
        }
    )
    params = dict(parameters or {})
    unsigned = {
        "schema": qc.SIGNED_OPERATION_SCHEMA,
        "operation_id": op_id,
        "template_id": template.template_id,
        "template_version": template.version,
        "kind": kind,
        "tenant_id": tenant_id,
        "catalog_id": catalog_id,
        "owner_generation": owner_generation,
        "fencing_epoch": fencing_epoch,
        "starting_snapshot": starting_snapshot,
        "schema_name": schema_name,
        "expected_effects": effects,
        "caller_process_birth": dict(caller_process_birth),
        "resource_budget": budget,
        "expires_at_unix": clock + float(ttl_seconds),
        "parameters": params,
        "canonical_sql": template.canonical_sql,
        "nonce": nonce or secrets.token_hex(16),
    }
    signature = sign_operation_payload(unsigned, signing_key=signing_key)
    return qc.SignedCatalogOperation(
        operation_id=op_id,
        template_id=template.template_id,
        template_version=template.version,
        kind=kind,
        tenant_id=tenant_id,
        catalog_id=catalog_id,
        owner_generation=owner_generation,
        fencing_epoch=fencing_epoch,
        starting_snapshot=starting_snapshot,
        schema_name=schema_name,
        expected_effects=effects,
        caller_process_birth=dict(caller_process_birth),
        resource_budget=budget,
        expires_at_unix=clock + float(ttl_seconds),
        signature=signature,
        parameters=params,
        canonical_sql=template.canonical_sql,
        nonce=unsigned["nonce"],
    )


def assert_production_activation_held() -> Mapping[str, Any]:
    return qc.assert_activation_held()


# ---------------------------------------------------------------------------
# Worker injection / results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorkerInjection:
    """One-use capability injected only into an identity-bound trusted worker."""

    worker_id: str
    capability_id: str
    operation_id: str
    catalog_id: str
    expires_at_ms: int
    _secret: str = field(repr=False, default="")

    def __post_init__(self) -> None:
        if not self._secret:
            raise CatalogServiceError("worker injection requires a capability secret")

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"WorkerInjection(worker_id={self.worker_id!r}, "
            f"capability_id={self.capability_id!r}, "
            f"operation_id={self.operation_id!r}, secret=***)"
        )

    def reveal_secret_for_trusted_worker(self) -> str:
        return self._secret

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "worker_id": self.worker_id,
                "capability_id": self.capability_id,
                "operation_id": self.operation_id,
                "catalog_id": self.catalog_id,
                "expires_at_ms": self.expires_at_ms,
                "secret": qs.REDACTION_MARKER,
            }
        )


@dataclass(frozen=True, slots=True)
class BoundedOperationResult:
    """Typed result/receipt returned to the trusted caller (never raw SQL)."""

    operation_id: str
    catalog_id: str
    kind: str
    receipt: Mapping[str, Any]
    rows: Sequence[Sequence[Any]]
    snapshot_vector: Mapping[str, Any]
    production_mutation: bool = False
    production_endpoint: bool = False

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "operation_id": self.operation_id,
                "catalog_id": self.catalog_id,
                "kind": self.kind,
                "receipt": dict(self.receipt),
                "rows": [list(r) for r in self.rows],
                "snapshot_vector": dict(self.snapshot_vector),
                "production_mutation": self.production_mutation,
                "production_endpoint": self.production_endpoint,
            }
        )


# ---------------------------------------------------------------------------
# Trusted broker
# ---------------------------------------------------------------------------


class TrustedCatalogBroker:
    """Trusted broker that retains reusable endpoint secrets.

    Injects only a one-use capability into an identity-bound trusted worker and
    returns typed results/receipts. Untrusted agents receive neither.
    Primary authorization is the signed structured operation; the Quack
    authorization callback is defense in depth only.
    """

    def __init__(
        self,
        *,
        signing_key: str,
        endpoint_secret: str | None = None,
    ) -> None:
        key = str(signing_key or "").strip()
        if len(key) < 16:
            raise CatalogServiceError("signing_key must be at least 16 characters")
        self._signing_key = key
        self._endpoint_secret = endpoint_secret or secrets.token_urlsafe(32)
        self._lock = threading.RLock()
        self._templates = default_template_registry()
        # Retain reusable endpoint secret privately (never returned to agents).
        self._endpoint_secret_fingerprint = hashlib.sha256(
            self._endpoint_secret.encode()
        ).hexdigest()[:16]

    @property
    def endpoint_secret_fingerprint(self) -> str:
        return self._endpoint_secret_fingerprint

    def retain_endpoint_secret(self) -> Mapping[str, Any]:
        """Public view: secret is retained, never exported."""

        return MappingProxyType(
            {
                "retained": True,
                "fingerprint": self._endpoint_secret_fingerprint,
                "exported_to_agents": False,
                "per_operation_authority": False,
                "reusable_default_token_is_authority": False,
            }
        )

    def authorize_worker(
        self,
        *,
        worker: cat.WorkerIdentity,
        operation: qc.SignedCatalogOperation,
        profile: cfg.CatalogShardProfile,
    ) -> Mapping[str, Any]:
        """Primary authorization outside the Quack SQL callback."""

        if not worker.trusted:
            raise UntrustedAgentDenied(
                "untrusted agents never receive raw SQL, reusable Quack tokens, "
                "catalog-file access, arbitrary ATTACH, extension-loading, or "
                "object-store access"
            )
        gate = cat.TrustedBrokerGate(profile=profile)
        kind = {
            "catalog.describe": cat.CatalogRequestKind.READ,
            "namespace.list": cat.CatalogRequestKind.READ,
            "schema.list": cat.CatalogRequestKind.READ,
            "schema.describe": cat.CatalogRequestKind.READ,
            "table.list": cat.CatalogRequestKind.READ,
            "table.describe": cat.CatalogRequestKind.READ,
            "snapshot.list": cat.CatalogRequestKind.SNAPSHOT,
            "snapshot.select": cat.CatalogRequestKind.SNAPSHOT,
            "ingest.register_intent": cat.CatalogRequestKind.WRITE,
            "maintenance.intent": cat.CatalogRequestKind.MAINTAIN,
            "mutation.bounded_insert": cat.CatalogRequestKind.WRITE,
            "mutation.bounded_replace": cat.CatalogRequestKind.WRITE,
        }.get(operation.kind, cat.CatalogRequestKind.READ)
        decision = gate.authorize(
            worker=worker,
            request_kind=kind,
            operation_id=operation.operation_id,
        )
        verification = qc.verify_signed_operation(
            operation,
            signing_key=self._signing_key,
            expected_catalog_id=profile.catalog_id,
            expected_owner_generation=profile.owner_lease.owner_generation,
            expected_fencing_epoch=profile.owner_lease.fencing_epoch,
        )
        return MappingProxyType(
            {
                "broker_authorized": True,
                "worker_decision": dict(decision),
                "signed_verification": dict(verification),
                "primary_authorization": "trusted_broker_signed_operation",
                "quack_authorization_function": "defense_in_depth_only",
            }
        )

    def inject_one_use_capability(
        self,
        *,
        owner: qc.CatalogOwnerProcess,
        worker: cat.WorkerIdentity,
        operation: qc.SignedCatalogOperation,
        ttl_ms: int = 30_000,
        now_ms: int | None = None,
    ) -> WorkerInjection:
        """Inject a one-use capability only into a trusted worker."""

        if not worker.trusted:
            raise UntrustedAgentDenied(
                "untrusted agents never receive a one-use Quack capability"
            )
        self.authorize_worker(
            worker=worker, operation=operation, profile=owner.profile
        )
        cap = owner.mint_one_use_capability(
            operation=operation, ttl_ms=ttl_ms, now_ms=now_ms
        )
        return WorkerInjection(
            worker_id=worker.worker_id,
            capability_id=cap.capability_id,
            operation_id=operation.operation_id,
            catalog_id=owner.catalog_id,
            expires_at_ms=cap.expires_at_ms,
            _secret=cap.secret,
        )

    def deny_untrusted_export(self, worker: cat.WorkerIdentity) -> None:
        if not worker.trusted:
            raise UntrustedAgentDenied(
                "untrusted agents receive neither reusable endpoint secrets "
                "nor one-use capabilities nor typed raw SQL"
            )


# ---------------------------------------------------------------------------
# Catalog management service (multi-shard coordinator)
# ---------------------------------------------------------------------------


class CatalogManagementService:
    """Coordinates one owner process per catalog shard without production promotion.

    Same-shard mutations are serialized by each owner. Independent shards run
    concurrently and expose receipted snapshot vectors for DQK-091 federation.
    """

    def __init__(
        self,
        *,
        signing_key: str,
        broker: TrustedCatalogBroker | None = None,
    ) -> None:
        self._signing_key = str(signing_key or "").strip()
        if len(self._signing_key) < 16:
            raise CatalogServiceError("signing_key must be at least 16 characters")
        self.broker = broker or TrustedCatalogBroker(signing_key=self._signing_key)
        self._owners: dict[str, qc.CatalogOwnerProcess] = {}
        self._lock = threading.RLock()
        self._templates = default_template_registry()

    def register_owner(
        self,
        profile: cfg.CatalogShardProfile,
        *,
        bootstrap: bool = True,
        native_file_lock_probe: Callable[[str], cat.NativeFileLockStatus]
        | None = None,
    ) -> qc.CatalogOwnerProcess:
        """Register and optionally bootstrap an internal owner (no production endpoint)."""

        qc.assert_not_production_endpoint()
        with self._lock:
            if profile.catalog_id in self._owners:
                raise CatalogServiceError(
                    f"catalog shard {profile.catalog_id!r} already has an owner "
                    "process; exactly one identity-bound owner per shard"
                )
            # Distinct metadata paths.
            for existing in self._owners.values():
                if (
                    existing.profile.catalog_metadata.path
                    == profile.catalog_metadata.path
                ):
                    raise CatalogServiceError(
                        "catalog metadata path is already bound to another shard"
                    )
            owner = qc.CatalogOwnerProcess(
                profile,
                signing_key=self._signing_key,
                native_file_lock_probe=native_file_lock_probe,
                production_mode=False,
            )
            if bootstrap:
                owner.bootstrap_internal_owner()
            self._owners[profile.catalog_id] = owner
            return owner

    def get_owner(self, catalog_id: str) -> qc.CatalogOwnerProcess:
        with self._lock:
            try:
                return self._owners[catalog_id]
            except KeyError as exc:
                raise CatalogServiceError(
                    f"unknown catalog owner {catalog_id!r}"
                ) from exc

    def catalog_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._owners))

    def submit(
        self,
        *,
        catalog_id: str,
        kind: str,
        worker: cat.WorkerIdentity,
        tenant_id: str,
        caller_process_birth: Mapping[str, Any],
        parameters: Mapping[str, Any] | None = None,
        starting_snapshot: int | None = None,
        schema_name: str = "main",
        operation_id: str | None = None,
        resource_budget: Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> BoundedOperationResult:
        """Validate, inject capability, execute, return typed result/receipt."""

        assert_production_activation_held()
        if not worker.trusted:
            raise UntrustedAgentDenied(
                "untrusted agents cannot invoke catalog management operations"
            )
        owner = self.get_owner(catalog_id)
        if not owner.admits_requests:
            raise CatalogServiceError(
                f"catalog owner {catalog_id!r} is not admitting requests"
            )
        if owner.lease is None:
            raise CatalogServiceError("owner lease missing")

        snap = (
            int(starting_snapshot)
            if starting_snapshot is not None
            else owner._last_snapshot  # hermetic snapshot cursor
        )
        operation = build_signed_operation(
            kind=kind,
            tenant_id=tenant_id,
            catalog_id=catalog_id,
            owner_generation=owner.lease.owner_generation,
            fencing_epoch=owner.lease.fencing_epoch,
            starting_snapshot=snap,
            caller_process_birth=caller_process_birth,
            signing_key=self._signing_key,
            schema_name=schema_name,
            parameters=parameters,
            resource_budget=resource_budget,
            operation_id=operation_id,
            now=now,
        )

        # Task-owned handler verifies signed operation before SQL construction
        # (primary authorization). Quack authz is defense in depth only.
        injection = self.broker.inject_one_use_capability(
            owner=owner,
            worker=worker,
            operation=operation,
        )
        secret = injection.reveal_secret_for_trusted_worker()

        # Serialize same-shard mutations through the owner process lock.
        def _run() -> Mapping[str, Any]:
            return owner.execute_signed_operation(
                operation,
                capability_secret=secret,
                allow_hermetic_mutation=True,
                now=now,
            )

        result = owner.quack_instance  # touch for lint
        _ = result
        # Use catalog owner handle serialization semantics via execute path
        # (owner.execute_signed_operation already holds the owner lock).
        public = _run()

        vector = {
            "catalog_id": catalog_id,
            "before_snapshot": public.get("before_snapshot"),
            "after_snapshot": public.get("after_snapshot"),
            "owner_generation": owner.lease.owner_generation,
            "fencing_epoch": owner.lease.fencing_epoch,
        }
        return BoundedOperationResult(
            operation_id=operation.operation_id,
            catalog_id=catalog_id,
            kind=kind,
            receipt=dict(public),
            rows=tuple(tuple(r) for r in public.get("rows", ())),
            snapshot_vector=vector,
            production_mutation=False,
            production_endpoint=False,
        )

    def submit_concurrent(
        self,
        requests: Sequence[Mapping[str, Any]],
    ) -> tuple[BoundedOperationResult | BaseException, ...]:
        """Run independent-shard requests concurrently; same-shard stays serialized."""

        results: list[BoundedOperationResult | BaseException | None] = [
            None
        ] * len(requests)
        threads: list[threading.Thread] = []

        def _worker(index: int, req: Mapping[str, Any]) -> None:
            try:
                results[index] = self.submit(**dict(req))
            except BaseException as exc:  # noqa: BLE001 - capture for caller
                results[index] = exc

        for i, req in enumerate(requests):
            t = threading.Thread(
                target=_worker, args=(i, req), name=f"catalog-svc-{i}"
            )
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        return tuple(
            r if r is not None else CatalogServiceError("missing concurrent result")
            for r in results
        )

    def snapshot_vectors(self) -> Mapping[str, Mapping[str, Any]]:
        """Explicit snapshot vectors for independent-shard federation (DQK-091)."""

        with self._lock:
            out: dict[str, Mapping[str, Any]] = {}
            for catalog_id, owner in self._owners.items():
                out[catalog_id] = MappingProxyType(
                    {
                        "catalog_id": catalog_id,
                        "last_snapshot": owner._last_snapshot,
                        "owner_generation": (
                            owner.lease.owner_generation if owner.lease else None
                        ),
                        "fencing_epoch": (
                            owner.lease.fencing_epoch if owner.lease else None
                        ),
                    }
                )
            return MappingProxyType(out)

    def stop_owner(self, catalog_id: str) -> qc.OwnerShutdownReceipt:
        owner = self.get_owner(catalog_id)
        receipt = owner.shutdown()
        with self._lock:
            self._owners.pop(catalog_id, None)
        return receipt

    def handle_lease_loss(self, catalog_id: str) -> Mapping[str, Any]:
        return self.get_owner(catalog_id).handle_lease_loss()

    def as_mapping(self) -> Mapping[str, Any]:
        with self._lock:
            payload = {
                "schema": CATALOG_SERVICE_SCHEMA,
                "implementation_generation": IMPLEMENTATION_GENERATION,
                "template_registry_version": TEMPLATE_REGISTRY_VERSION,
                "production_endpoint_enabled": qc.PRODUCTION_ENDPOINT_ENABLED,
                "production_mutation_enabled": qc.PRODUCTION_MUTATION_ENABLED,
                "activation_gates": list(qc.ACTIVATION_GATES),
                "owners": {
                    cid: dict(owner.as_mapping())
                    for cid, owner in self._owners.items()
                },
                "templates": {
                    tid: dict(tmpl.as_mapping())
                    for tid, tmpl in self._templates.items()
                },
                "endpoint_secret": dict(self.broker.retain_endpoint_secret()),
                "independent_shard_concurrency": True,
                "same_shard_serialization": True,
            }
        cfg.assert_no_secrets_in_projection(payload)
        return MappingProxyType(payload)
