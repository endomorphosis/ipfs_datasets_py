"""Per-shard DuckDB + Quack catalog owner service (DQK-104).

Each identity-bound process:

1. Acquires a durable catalog-owner generation lease
2. Exclusively opens the shard's local/block-storage DuckDB metadata file
3. Acquires DuckDB's native file lock
4. Explicitly loads pinned DuckLake, Quack, and object-store extensions
5. Attaches exactly one DuckLake catalog on the Quack-serving DatabaseInstance
6. Coordinates with a separate private DQK-086 companion-registry DatabaseInstance
   that is never ATTACHed to or visible from the Quack-serving instance

Distributed readers and writers connect only through Quack. No second process
may open, copy into place, or network-mount the live catalog file.

Production catalog mutation remains disabled until DQK-088, DQK-094, and the
signed DQK-102 gate authorize cutover. This module never starts a production
endpoint.

Import is side-effect free.
"""

from __future__ import annotations

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
from ipfs_datasets_py.ducklake import quack_catalog as qc
from ipfs_datasets_py.ducklake.capabilities import (
    PINNED_DUCKLAKE_EXTENSION_BUILD,
    PINNED_HTTPFS_EXTENSION_BUILD,
    PINNED_QUACK_EXTENSION_BUILD,
)
from ipfs_datasets_py.ducklake.registry import (
    CompanionLakeRegistry,
    DatabaseInstanceBinding,
    DatabaseInstanceKind,
    MemoryRegistryStore,
)

__all__ = [
    "CATALOG_SERVICE_SCHEMA",
    "CatalogServiceError",
    "LeaseLost",
    "AdmissionClosed",
    "OwnerNotActive",
    "DatabaseInstanceRole",
    "OwnerProcessIdentity",
    "EndpointToken",
    "CatalogOwnerService",
    "CatalogServiceManager",
    "TrustedCatalogBroker",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

CATALOG_SERVICE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-catalog-service@1"
)

_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-104-catalog-owner-service-20260810"
)

# Process-local exclusive lease table: one active owner generation per catalog
# metadata path. Models the durable single-owner invariant inside hermetic tests
# and co-located processes without requiring live DuckDB file locks.
_ACTIVE_CATALOG_LEASES: dict[str, str] = {}
_ACTIVE_CATALOG_LEASES_LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CatalogServiceError(ValueError):
    """Fail-closed catalog owner service rejection."""


class LeaseLost(CatalogServiceError):
    """Owner generation lease was lost; admission must stop."""


class AdmissionClosed(CatalogServiceError):
    """Owner is not admitting requests."""


class OwnerNotActive(CatalogServiceError):
    """Owner process is not in the ACTIVE state."""


# ---------------------------------------------------------------------------
# Identity / endpoint
# ---------------------------------------------------------------------------


class DatabaseInstanceRole(str, Enum):
    """Distinct DuckDB DatabaseInstance roles inside the owner process."""

    QUACK_SERVING = "quack_serving"
    COMPANION_REGISTRY = "companion_registry"


@dataclass(frozen=True, slots=True)
class OwnerProcessIdentity:
    """OS/network identity of the Quack catalog-owner process.

    Distinct from the sanitized publication gateway identity. The owner can
    reach only its selected DuckDB catalog file and owned storage namespace.
    """

    process_id: str
    os_identity: str
    network_identity: str
    process_birth: Mapping[str, Any]
    selected_catalog_path: str
    owned_storage_namespace: str
    distinct_from_publication_gateway: bool = True

    def __post_init__(self) -> None:
        if not str(self.process_id or "").strip():
            raise CatalogServiceError("process_id is required")
        if not str(self.os_identity or "").strip():
            raise CatalogServiceError("os_identity is required")
        if not str(self.network_identity or "").strip():
            raise CatalogServiceError("network_identity is required")
        if not self.distinct_from_publication_gateway:
            raise CatalogServiceError(
                "catalog-owner OS/network identity must be distinct from the "
                "sanitized publication gateway"
            )
        birth = dict(self.process_birth or {})
        if not birth:
            raise CatalogServiceError("process_birth is required")
        object.__setattr__(self, "process_birth", MappingProxyType(birth))
        object.__setattr__(self, "process_id", str(self.process_id).strip())
        object.__setattr__(self, "os_identity", str(self.os_identity).strip())
        object.__setattr__(
            self, "network_identity", str(self.network_identity).strip()
        )
        object.__setattr__(
            self, "selected_catalog_path", str(self.selected_catalog_path).strip()
        )
        object.__setattr__(
            self,
            "owned_storage_namespace",
            str(self.owned_storage_namespace).strip(),
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "process_id": self.process_id,
                "os_identity": self.os_identity,
                "network_identity": self.network_identity,
                "process_birth": dict(self.process_birth),
                "selected_catalog_path": self.selected_catalog_path,
                "owned_storage_namespace": self.owned_storage_namespace,
                "distinct_from_publication_gateway": True,
            }
        )


@dataclass
class EndpointToken:
    """Rotatable endpoint identity/token (not a per-operation authority)."""

    endpoint_id: str
    token_id: str
    _token: str = field(repr=False, default="")
    revoked: bool = False
    generation: int = 1

    def __post_init__(self) -> None:
        if not self._token:
            self._token = secrets.token_urlsafe(32)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"EndpointToken(endpoint_id={self.endpoint_id!r}, "
            f"token_id={self.token_id!r}, token=***, revoked={self.revoked}, "
            f"generation={self.generation})"
        )

    def revoke(self) -> None:
        self.revoked = True
        self._token = ""

    def reveal_for_broker(self) -> str:
        if self.revoked:
            raise CatalogServiceError("endpoint token has been revoked")
        return self._token

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "endpoint_id": self.endpoint_id,
                "token_id": self.token_id,
                "token": qs.REDACTION_MARKER,
                "revoked": self.revoked,
                "generation": self.generation,
                "reusable_default_is_not_per_operation_authority": True,
            }
        )


# ---------------------------------------------------------------------------
# Catalog owner service
# ---------------------------------------------------------------------------


class CatalogOwnerService:
    """One dedicated internal DuckDB + Quack owner service per catalog shard.

    Hermetic runtime: does not import ``duckdb`` or bind production sockets.
    File-lock probes and optional companion stores are injected.
    """

    def __init__(
        self,
        profile: cfg.CatalogShardProfile,
        *,
        process_identity: OwnerProcessIdentity | None = None,
        gateway_policy: qc.GatewayBindPolicy | None = None,
        companion_store: MemoryRegistryStore | None = None,
        native_file_lock_probe: Callable[[str], cat.NativeFileLockStatus]
        | None = None,
        signing_secret: str | None = None,
        duckdb_profile: str = "duckdb@1.5.5+core",
        production_gates: Mapping[str, bool] | None = None,
    ) -> None:
        if not isinstance(profile, cfg.CatalogShardProfile):
            raise CatalogServiceError("profile must be CatalogShardProfile")
        self.profile = profile
        self._lock = threading.RLock()
        self._native_file_lock_probe = native_file_lock_probe
        self._signing_secret = signing_secret or secrets.token_urlsafe(32)
        self._duckdb_profile = duckdb_profile
        gates = dict(production_gates or {})
        self._gates = {
            "dqk_088_complete": bool(gates.get("dqk_088_complete", False)),
            "dqk_094_complete": bool(gates.get("dqk_094_complete", False)),
            "dqk_102_signed": bool(gates.get("dqk_102_signed", False)),
        }

        self.process_identity = process_identity or OwnerProcessIdentity(
            process_id=f"ownerproc_{uuid.uuid4().hex[:12]}",
            os_identity=profile.owner_lease.os_identity,
            network_identity=profile.owner_lease.endpoint_identity,
            process_birth=dict(profile.owner_lease.process_birth.as_mapping())
            if hasattr(profile.owner_lease.process_birth, "as_mapping")
            else dict(profile.owner_lease.process_birth),
            selected_catalog_path=profile.catalog_metadata.path,
            owned_storage_namespace=profile.parquet_namespace.data_path,
        )
        if (
            self.process_identity.selected_catalog_path
            != profile.catalog_metadata.path
        ):
            raise CatalogServiceError(
                "process identity selected_catalog_path must match profile"
            )

        self.gateway_policy = gateway_policy or qc.GatewayBindPolicy(
            bind_host=profile.quack_endpoint.host
            if qs.is_loopback_host(profile.quack_endpoint.host)
            else "127.0.0.1",
            bind_port=int(profile.quack_endpoint.port),
        )

        # Dual DatabaseInstance model.
        self._quack_instance = DatabaseInstanceBinding(
            instance_id=f"quack_{profile.catalog_id}",
            kind=DatabaseInstanceKind.QUACK_SERVING,
            path=profile.catalog_metadata.path,
            private=True,
            attachable_from_quack=False,
        )
        self._companion_instance = DatabaseInstanceBinding(
            instance_id=f"companion_{profile.catalog_id}",
            kind=DatabaseInstanceKind.COMPANION_PRIVATE,
            path=profile.companion_registry.path,
            private=True,
            attachable_from_quack=False,
        )
        # Companion registry lives in a separate private DatabaseInstance.
        self._companion_store = companion_store
        self.companion_registry = CompanionLakeRegistry(
            shard_id=profile.catalog_id,
            store=self._companion_store,
            owner_id=f"companion-owner-{profile.catalog_id}",
            instance=self._companion_instance,
        )

        self.owner_handle = cat.CatalogOwnerHandle(
            profile=profile,
            _native_file_lock_probe=native_file_lock_probe,
        )
        self.broker_gate = cat.TrustedBrokerGate(profile=profile)

        self.templates = qc.open_default_template_registry()
        self.idempotency = qc.DurableIdempotencyStore()
        self._cap_store = qs.OperationCapabilityStore()
        self._auth = qs.AuthenticationCallback(
            self._cap_store,
            profile=qs.ServerProfile.CATALOG_OWNER,
            policy=qs.AuthenticationPolicy(
                mode=qs.AuthenticationMode.ONE_USE_CAPABILITY_CALLBACK,
                callback_name=qs.NON_DEFAULT_AUTH_CALLBACK_NAME,
            ),
        )
        self._authz = qs.AuthorizationCallback(
            self._auth,
            policy=qs.AuthorizationPolicy(
                mode=qs.AuthorizationMode.EXACT_FULL_SQL,
                callback_name=qs.NON_DEFAULT_AUTHZ_CALLBACK_NAME,
            ),
        )
        self._attestation: qc.AuthCallbackAttestation | None = None

        self._endpoint = EndpointToken(
            endpoint_id=profile.quack_endpoint.endpoint_id,
            token_id=f"etok_{uuid.uuid4().hex[:12]}",
            generation=profile.owner_lease.owner_generation,
        )
        # Reusable endpoint secret retained by the trusted broker only.
        self._endpoint_secret = secrets.token_urlsafe(32)

        self._selected_catalog = profile.catalog_id
        self._attached_catalog: str | None = None
        self._extensions_loaded: tuple[str, ...] = ()
        self._catalog_file_open = False
        self._native_file_lock = cat.NativeFileLockStatus.NOT_ATTEMPTED
        self._lease_held = False
        self._owner_generation: int | None = None
        self._fencing_epoch: int | None = None
        self._last_snapshot = 1
        self._namespaces: dict[str, set[str]] = {"main": set()}
        self._schemas: dict[str, set[str]] = {"main": {"main"}}
        self._tables: dict[str, set[str]] = {"main": set()}
        self._ingest_intents: list[dict[str, Any]] = []
        self._maintenance_intents: list[dict[str, Any]] = []
        self._sessions: dict[str, dict[str, Any]] = {}
        self._handles_open = 0
        self._production_endpoint_started = False
        self._storage_capabilities_expired = False
        self._audit: list[dict[str, Any]] = []

    # -- properties --------------------------------------------------------

    @property
    def catalog_id(self) -> str:
        return self.profile.catalog_id

    @property
    def admits_requests(self) -> bool:
        return self.owner_handle.admits_requests and self._lease_held

    @property
    def owner_generation(self) -> int | None:
        return self._owner_generation

    @property
    def signing_secret_for_tests(self) -> str:
        """Test-only access to the broker signing secret."""

        return self._signing_secret

    @property
    def endpoint_secret_for_broker(self) -> str:
        """Trusted broker retains the reusable endpoint secret."""

        if self._endpoint.revoked:
            raise CatalogServiceError("endpoint revoked")
        return self._endpoint_secret

    # -- lifecycle ---------------------------------------------------------

    def acquire_ownership(
        self,
        *,
        bootstrap: bool = False,
        preconditions: cat.TakeoverPreconditions | None = None,
    ) -> Mapping[str, Any]:
        """Acquire generation lease, native file lock, load extensions, attach."""

        with self._lock:
            qc.assert_no_production_activation(
                start_production_endpoint=False,
                perform_production_mutation=False,
                **self._gates,
            )
            # Storage class: local/block only.
            if self.profile.catalog_metadata.storage_kind not in {
                cfg.AuthorityStorageKind.LOCAL_BLOCK,
                cfg.AuthorityStorageKind.ATTACHED_BLOCK,
            }:
                raise CatalogServiceError(
                    "catalog file is local/block-storage only; NFS, SMB, object "
                    "URLs, and shared filesystem mounts fail closed"
                )

            catalog_path = self.profile.catalog_metadata.path
            process_key = self.process_identity.process_id
            with _ACTIVE_CATALOG_LEASES_LOCK:
                holder = _ACTIVE_CATALOG_LEASES.get(catalog_path)
                if holder is not None and holder != process_key:
                    raise CatalogServiceError(
                        f"catalog shard {self.catalog_id!r} already has an "
                        "active identity-bound owner process; exactly one "
                        "owner process and generation lease exist per catalog "
                        "shard (metadata path already leased)"
                    )

            result = self.owner_handle.acquire_ownership(
                bootstrap=bootstrap,
                preconditions=preconditions,
            )
            generation = int(result["owner_generation"])
            self._owner_generation = generation
            # Fencing epoch tracks owner generation fence; rotate on takeover.
            if preconditions is not None:
                self._fencing_epoch = int(preconditions.successor_owner_generation)
                # Endpoint/token rotation on takeover.
                self._rotate_endpoint_locked(
                    generation=preconditions.successor_owner_generation
                )
            else:
                self._fencing_epoch = int(self.profile.owner_lease.fencing_epoch)
            self._lease_held = True
            self._native_file_lock = self.owner_handle.native_file_lock
            if self._native_file_lock is not cat.NativeFileLockStatus.ACQUIRED:
                self._lease_held = False
                raise CatalogServiceError(
                    "native DuckDB file lock required before opening catalog"
                )
            with _ACTIVE_CATALOG_LEASES_LOCK:
                _ACTIVE_CATALOG_LEASES[catalog_path] = process_key

            # Open catalog file exclusively (modeled; no second process may open).
            self._catalog_file_open = True
            self._handles_open = 1

            # Explicit load of pinned extensions.
            self._extensions_loaded = (
                PINNED_QUACK_EXTENSION_BUILD,
                PINNED_DUCKLAKE_EXTENSION_BUILD,
                PINNED_HTTPFS_EXTENSION_BUILD,
            )

            # Attach exactly one DuckLake catalog on the Quack-serving instance.
            attach = self.owner_handle.safe_attach_statement()
            if self._attached_catalog is not None:
                raise CatalogServiceError(
                    "catalog-scoped server already has a selected catalog attached"
                )
            self._attached_catalog = self._selected_catalog

            # Attest non-default auth/authz before accepting connections.
            self._attestation = qc.attest_authorization_callback(
                authentication_callback=self._auth.name,
                authorization_callback=self._authz.name,
            )

            # Companion instance remains private / never attached to Quack instance.
            if self._companion_instance.attachable_from_quack:
                raise CatalogServiceError(
                    "companion registry must never be attachable from Quack"
                )
            if not self._companion_instance.private:
                raise CatalogServiceError(
                    "companion registry DatabaseInstance must remain private"
                )
            if self._companion_instance.kind is not DatabaseInstanceKind.COMPANION_PRIVATE:
                raise CatalogServiceError(
                    "companion registry requires COMPANION_PRIVATE DatabaseInstance"
                )

            return MappingProxyType(
                {
                    "catalog_id": self.catalog_id,
                    "owner_generation": self._owner_generation,
                    "fencing_epoch": self._fencing_epoch,
                    "lease_held": True,
                    "native_file_lock": self._native_file_lock.value,
                    "catalog_file_open": True,
                    "extensions_loaded": list(self._extensions_loaded),
                    "attached_catalog": self._attached_catalog,
                    "attach_sql_digest": "sha256:"
                    + __import__("hashlib")
                    .sha256(attach.sql().encode("utf-8"))
                    .hexdigest(),
                    "quack_serving_instance": self._quack_instance.instance_id,
                    "companion_instance": self._companion_instance.instance_id,
                    "companion_visible_from_quack": False,
                    "companion_attached_to_quack": False,
                    "companion_private": True,
                    "production_endpoint_started": False,
                    "auth_attestation": dict(self._attestation.as_mapping()),
                    "single_owner": True,
                    "remote_clients_may_open_catalog_file": False,
                }
            )

    def _rotate_endpoint_locked(self, *, generation: int) -> None:
        self._endpoint.revoke()
        self._endpoint = EndpointToken(
            endpoint_id=f"{self.profile.quack_endpoint.endpoint_id}#g{generation}",
            token_id=f"etok_{uuid.uuid4().hex[:12]}",
            generation=generation,
        )
        self._endpoint_secret = secrets.token_urlsafe(32)

    # -- remote access denial ----------------------------------------------

    def assert_remote_catalog_file_access_denied(
        self,
        *,
        action: str,
    ) -> None:
        """Remote clients cannot open, copy, or mount the catalog metadata file."""

        cat.assert_remote_catalog_access_denied(action)

    # -- lease loss / shutdown ---------------------------------------------

    def _release_process_lease_locked(self) -> None:
        catalog_path = self.profile.catalog_metadata.path
        process_key = self.process_identity.process_id
        with _ACTIVE_CATALOG_LEASES_LOCK:
            holder = _ACTIVE_CATALOG_LEASES.get(catalog_path)
            if holder == process_key:
                _ACTIVE_CATALOG_LEASES.pop(catalog_path, None)

    def on_lease_loss(self) -> Mapping[str, Any]:
        """Lease loss: stop admission, revoke endpoint, expire caps, teardown."""

        with self._lock:
            # Order is load-bearing: admission stop + endpoint revoke before
            # capability expiry and session/file-handle teardown.
            self.owner_handle.stop_admission()
            self._lease_held = False
            self._endpoint.revoke()
            endpoint_revoked = True
            # Let storage capabilities expire before teardown of sessions/handles.
            self._storage_capabilities_expired = True
            # Close every session and file handle.
            session_ids = list(self._sessions)
            for sid in session_ids:
                self._sessions[sid]["closed"] = True
            self._sessions.clear()
            self._catalog_file_open = False
            self._handles_open = 0
            self._attached_catalog = None
            self._release_process_lease_locked()
            self.owner_handle.fence_and_stop()
            return MappingProxyType(
                {
                    "catalog_id": self.catalog_id,
                    "admission_stopped": True,
                    "endpoint_revoked": endpoint_revoked,
                    "storage_capabilities_expired": True,
                    "sessions_closed": True,
                    "file_handles_closed": True,
                    "lease_released": True,
                    "stale_incumbent_cannot_keep_serving": True,
                    "order": (
                        "stop_admission",
                        "revoke_endpoint_token",
                        "expire_storage_capabilities",
                        "close_sessions_and_handles",
                        "release_lease",
                    ),
                }
            )

    def shutdown(self) -> Mapping[str, Any]:
        """Shutdown: close every connection and file handle before lease release."""

        with self._lock:
            self.owner_handle.stop_admission()
            session_ids = list(self._sessions)
            for sid in session_ids:
                self._sessions[sid]["closed"] = True
            closed_sessions = len(session_ids)
            self._sessions.clear()
            self._catalog_file_open = False
            handles_closed = self._handles_open
            self._handles_open = 0
            self._attached_catalog = None
            self._endpoint.revoke()
            self._lease_held = False
            prior = self._owner_generation
            self._release_process_lease_locked()
            self.owner_handle.fence_and_stop()
            self._owner_generation = None
            return MappingProxyType(
                {
                    "catalog_id": self.catalog_id,
                    "connections_closed": closed_sessions,
                    "file_handles_closed": handles_closed,
                    "owner_lease_released": True,
                    "token_invalidated": True,
                    "prior_owner_generation": prior,
                    "state": self.owner_handle.state.value,
                }
            )

    # -- auth / sessions ---------------------------------------------------

    def mint_one_use_capability(
        self,
        *,
        operation: qc.SignedCatalogOperation,
        canonical_sql: str,
        ttl_ms: int = 60_000,
        now_ms: int | None = None,
    ) -> qs.OperationCapability:
        """Broker injects only a one-use capability (never reusable token)."""

        if self._attestation is None:
            raise CatalogServiceError(
                "server must attest non-default quack_authorization_function "
                "before accepting a connection"
            )
        cap = qs.mint_operation_capability(
            operation_id=operation.operation_id,
            profile=qs.ServerProfile.CATALOG_OWNER,
            canonical_sql=canonical_sql,
            ttl_ms=ttl_ms,
            now_ms=now_ms,
        )
        self._cap_store.insert(cap)
        return cap

    def open_authenticated_session(
        self,
        *,
        capability_secret: str,
        now_ms: int | None = None,
    ) -> qs.AuthenticatedSession:
        if not self.admits_requests:
            raise AdmissionClosed(
                f"catalog shard {self.catalog_id!r} is not admitting requests"
            )
        if self._attestation is None:
            raise CatalogServiceError(
                "missing authorization callback attestation fails closed"
            )
        if self._authz.name.lower() in qs.DEFAULT_PERMISSIVE_AUTHZ_HOOKS:
            raise CatalogServiceError(
                "permissive or default quack_authorization_function fails closed"
            )
        session = self._auth.authenticate(
            capability_secret=capability_secret,
            now_ms=now_ms,
        )
        with self._lock:
            self._sessions[session.session_id] = {
                "session": session,
                "closed": False,
            }
        return session

    # -- operation execution -----------------------------------------------

    def execute_signed_operation(
        self,
        operation: qc.SignedCatalogOperation,
        *,
        worker: cat.WorkerIdentity,
        now: float | None = None,
        now_ms: int | None = None,
    ) -> qc.MutationReceipt:
        """Primary path: verify signed op, inject one-use cap, execute, receipt.

        Same-shard mutations are serialized through the owner lock. Production
        DuckLake mutation remains disabled when promotion gates are held.
        """

        with self._lock:
            return self._execute_signed_operation_locked(
                operation,
                worker=worker,
                now=now,
                now_ms=now_ms,
            )

    def _execute_signed_operation_locked(
        self,
        operation: qc.SignedCatalogOperation,
        *,
        worker: cat.WorkerIdentity,
        now: float | None,
        now_ms: int | None,
    ) -> qc.MutationReceipt:
        if not self.admits_requests:
            raise AdmissionClosed(
                f"catalog shard {self.catalog_id!r} is not admitting requests"
            )
        if not self._lease_held:
            raise LeaseLost("owner lease is not held; refuse operation")

        # Cross-catalog overlap rejection.
        if operation.catalog_id != self._selected_catalog:
            raise qc.CrossCatalogOverlap(
                f"catalog-scoped server selected {self._selected_catalog!r}; "
                f"rejected concurrent cross-catalog operation for "
                f"{operation.catalog_id!r}"
            )
        if (
            self._attached_catalog is not None
            and self._attached_catalog != operation.catalog_id
        ):
            raise qc.CrossCatalogOverlap(
                "rejects concurrent cross-catalog overlap"
            )

        # Idempotent replay from durable operation id.
        prior = self.idempotency.lookup(operation.operation_id)
        if prior is not None:
            if prior["request_digest"] != operation.request_digest():
                raise qc.IdempotentReplay(
                    f"operation_id {operation.operation_id!r} conflict"
                )
            return prior["receipt"]

        # Task-owned handler independently verifies the signed structured op
        # before SQL construction (primary authorization boundary).
        verification = qc.verify_signed_operation(
            operation,
            secret=self._signing_secret,
            now=now,
            expected_catalog_id=self.catalog_id,
            expected_owner_generation=self._owner_generation,
            expected_fencing_epoch=self._fencing_epoch,
        )

        template = self.templates.get(
            operation.template_id, version=operation.template_version
        )
        if set(operation.expected_effects) != set(template.expected_effects):
            raise qc.TemplateDenied("expected_effects do not match template")

        # Trusted broker authorizes the worker independently of Quack.
        request_kind = (
            cat.CatalogRequestKind.WRITE
            if template.mutates
            else cat.CatalogRequestKind.READ
        )
        if template.kind is qc.CatalogOperationKind.MAINTENANCE_INTENT:
            request_kind = cat.CatalogRequestKind.MAINTAIN
        self.broker_gate.authorize(
            worker=worker,
            request_kind=request_kind,
            operation_id=operation.operation_id,
        )

        # Untrusted agents never receive raw SQL, reusable tokens, or capabilities.
        if not worker.trusted:
            raise cat.CatalogAccessDenied(
                "untrusted agents never receive raw SQL, reusable Quack tokens, "
                "catalog-file access, arbitrary ATTACH, extension-loading, or "
                "object-store access"
            )

        canonical_sql = qc.render_canonical_sql(template, operation.parameters)
        # Defense in depth: deny arbitrary surfaces even on allowlisted paths
        # if parameters smuggled something hostile.
        qc.deny_arbitrary_sql(canonical_sql, selected_catalog=self.catalog_id)

        # Production mutation hold.
        production_mutation = False
        if template.mutates:
            try:
                qc.assert_no_production_activation(
                    perform_production_mutation=True,
                    **self._gates,
                )
                production_mutation = True
            except qc.PromotionGateHold:
                # Record intent only; do not mutate the production lake.
                production_mutation = False

        # Inject one-use capability only into the trusted worker path.
        capability = self.mint_one_use_capability(
            operation=operation,
            canonical_sql=canonical_sql,
            now_ms=now_ms,
        )
        session = self.open_authenticated_session(
            capability_secret=capability.secret,
            now_ms=now_ms,
        )

        # quack_authorization_function is exact full-SQL defense-in-depth.
        self._authz.authorize(session_id=session.session_id, sql=canonical_sql)

        before = self._last_snapshot
        affected: list[str] = []
        outbox_state = "none"
        if template.mutates and not production_mutation:
            # Intent-only under promotion hold (no production DuckLake mutation).
            if template.kind is qc.CatalogOperationKind.INGEST_REGISTRATION:
                self._ingest_intents.append(dict(operation.parameters))
                affected.append(
                    f"ingest_intent:{operation.parameters.get('logical_key', '')}"
                )
                outbox_state = "intent_recorded_pending_promotion"
            elif template.kind is qc.CatalogOperationKind.MAINTENANCE_INTENT:
                self._maintenance_intents.append(dict(operation.parameters))
                affected.append(
                    f"maintenance_intent:{operation.parameters.get('intent_kind', '')}"
                )
                outbox_state = "intent_recorded_pending_promotion"
            after = before  # no snapshot advance without production mutation
        elif template.mutates and production_mutation:
            # Gated path (only when DQK-088/094/102 complete).
            after = before + 1
            self._last_snapshot = after
            outbox_state = "committed"
            affected.append(template.identity)
        else:
            # Read path.
            after = before
            if template.kind is qc.CatalogOperationKind.NAMESPACE:
                affected.extend(sorted(self._namespaces.keys()))
            elif template.kind is qc.CatalogOperationKind.SCHEMA:
                affected.extend(sorted(self._schemas.get("main", ())))
            elif template.kind is qc.CatalogOperationKind.TABLE:
                affected.extend(sorted(self._tables.get("main", ())))
            elif template.kind is qc.CatalogOperationKind.SNAPSHOT:
                affected.append(f"snapshot:{operation.parameters.get('snapshot_version')}")
            elif template.kind is qc.CatalogOperationKind.CATALOG:
                affected.append(self.catalog_id)
            outbox_state = "read_only"

        if self._attestation is None:  # pragma: no cover
            raise CatalogServiceError("missing attestation")

        receipt = qc.build_mutation_receipt(
            operation=operation,
            session_id=session.session_id,
            attestation=self._attestation,
            before_snapshot=before,
            after_snapshot=after,
            affected_logical_objects=affected,
            outbox_state=outbox_state,
            idempotency_state="committed",
            quack_profile=qs.ServerProfile.CATALOG_OWNER.value,
            duckdb_profile=self._duckdb_profile,
            catalog_network_policy=dict(self.gateway_policy.as_mapping()),
            canonical_sql=canonical_sql,
            production_mutation=production_mutation,
        )
        # Bind verification evidence into audit (tokens/SQL scrubbed).
        scrubbed = qc.scrub_log_payload(
            {
                "event": "catalog_operation",
                "operation_id": operation.operation_id,
                "session_id": session.session_id,
                "verified": verification["verified"],
                "result": "ok",
                "sql": canonical_sql,
                "token": capability.secret,
            }
        )
        self._audit.append(
            scrubbed if isinstance(scrubbed, dict) else {"event": "catalog_operation"}
        )

        return self.idempotency.commit(
            operation_id=operation.operation_id,
            request_digest=operation.request_digest(),
            receipt=receipt,
        )

    def reject_arbitrary_sql(self, sql: str) -> None:
        """Public denial of quack_query / remote .query arbitrary SQL."""

        qc.deny_arbitrary_sql(sql, selected_catalog=self.catalog_id)

    def prove_single_selected_catalog(self) -> Mapping[str, Any]:
        with self._lock:
            if self._attached_catalog is None:
                raise CatalogServiceError("no catalog attached")
            if self._attached_catalog != self._selected_catalog:
                raise qc.CrossCatalogOverlap("attached catalog mismatch")
            return MappingProxyType(
                {
                    "selected_catalog": self._selected_catalog,
                    "attached_catalog": self._attached_catalog,
                    "exactly_one": True,
                    "companion_attached": False,
                    "companion_visible": False,
                }
            )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": CATALOG_SERVICE_SCHEMA,
                "implementation_generation": _IMPLEMENTATION_GENERATION,
                "catalog_id": self.catalog_id,
                "owner_generation": self._owner_generation,
                "fencing_epoch": self._fencing_epoch,
                "lease_held": self._lease_held,
                "admits_requests": self.admits_requests,
                "native_file_lock": self._native_file_lock.value,
                "catalog_file_open": self._catalog_file_open,
                "extensions_loaded": list(self._extensions_loaded),
                "attached_catalog": self._attached_catalog,
                "process_identity": dict(self.process_identity.as_mapping()),
                "endpoint": dict(self._endpoint.as_mapping()),
                "gateway_policy": dict(self.gateway_policy.as_mapping()),
                "promotion_gate": dict(qc.promotion_gate_status(**self._gates)),
                "production_endpoint_started": self._production_endpoint_started,
                "quack_serving_instance": {
                    "instance_id": self._quack_instance.instance_id,
                    "kind": self._quack_instance.kind.value
                    if hasattr(self._quack_instance.kind, "value")
                    else str(self._quack_instance.kind),
                    "path": self._quack_instance.path,
                },
                "companion_instance": {
                    "instance_id": self._companion_instance.instance_id,
                    "kind": self._companion_instance.kind.value
                    if hasattr(self._companion_instance.kind, "value")
                    else str(self._companion_instance.kind),
                    "path": self._companion_instance.path,
                    "private": True,
                    "attachable_from_quack": False,
                    "visible_from_quack": False,
                },
                "owner_extension_load_plan": dict(qc.owner_extension_load_plan()),
                "reusable_default_server_token_is_authority": False,
                "auth_callback": self._auth.name,
                "authz_callback": self._authz.name,
            }
        )


# ---------------------------------------------------------------------------
# Trusted broker facade (retains secrets; returns typed results)
# ---------------------------------------------------------------------------


class TrustedCatalogBroker:
    """Trusted broker that retains reusable endpoint secrets.

    Injects only a one-use capability into an identity-bound trusted worker and
    returns typed results/receipts. Untrusted agents receive neither.
    """

    def __init__(self, service: CatalogOwnerService) -> None:
        self._service = service
        self._retained_endpoint_secret = service.endpoint_secret_for_broker

    @property
    def retains_reusable_endpoint_secret(self) -> bool:
        return bool(self._retained_endpoint_secret)

    def submit(
        self,
        operation: qc.SignedCatalogOperation,
        *,
        worker: cat.WorkerIdentity,
        now: float | None = None,
    ) -> qc.MutationReceipt:
        if not worker.trusted:
            raise cat.CatalogAccessDenied(
                "untrusted agents receive neither endpoint secrets nor one-use "
                "capabilities nor typed mutation receipts from the trusted broker"
            )
        # Broker never hands the reusable endpoint secret to the worker.
        return self._service.execute_signed_operation(
            operation, worker=worker, now=now
        )

    def mint_operation(
        self,
        *,
        template_id: str,
        tenant: str,
        worker: cat.WorkerIdentity,
        parameters: Mapping[str, Any],
        starting_snapshot: int | None = None,
        schema_name: str = "main",
        ttl_seconds: int = 60,
    ) -> qc.SignedCatalogOperation:
        if not worker.trusted:
            raise cat.CatalogAccessDenied(
                "untrusted agents never receive signed operations from the broker"
            )
        if self._service.owner_generation is None:
            raise OwnerNotActive("owner is not active")
        template = self._service.templates.get(template_id)
        return qc.mint_signed_operation(
            template=template,
            catalog_id=self._service.catalog_id,
            tenant=tenant,
            caller_process_birth=dict(worker.process_birth),
            owner_generation=int(self._service.owner_generation),
            fencing_epoch=int(self._service._fencing_epoch or 1),
            starting_snapshot=(
                int(starting_snapshot)
                if starting_snapshot is not None
                else self._service._last_snapshot
            ),
            schema_name=schema_name,
            parameters=parameters,
            secret=self._service.signing_secret_for_tests,
            ttl_seconds=ttl_seconds,
        )


# ---------------------------------------------------------------------------
# Multi-shard manager (independent concurrency)
# ---------------------------------------------------------------------------


class CatalogServiceManager:
    """Registry of independent catalog-owner services.

    Same-shard mutations serialize inside each owner. Independent shards run
    concurrently and are federated only through explicit snapshot vectors
    (DQK-091).
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._services: dict[str, CatalogOwnerService] = {}

    def register(self, service: CatalogOwnerService) -> CatalogOwnerService:
        with self._lock:
            if service.catalog_id in self._services:
                raise CatalogServiceError(
                    f"catalog {service.catalog_id!r} already has an owner service"
                )
            for existing in self._services.values():
                if (
                    existing.profile.catalog_metadata.path
                    == service.profile.catalog_metadata.path
                ):
                    raise CatalogServiceError(
                        "exactly one identity-bound owner process and generation "
                        "lease exist per catalog shard; catalog metadata path "
                        "already bound"
                    )
            self._services[service.catalog_id] = service
            return service

    def get(self, catalog_id: str) -> CatalogOwnerService:
        with self._lock:
            service = self._services.get(str(catalog_id))
            if service is None:
                raise CatalogServiceError(f"unknown catalog {catalog_id!r}")
            return service

    def list_catalogs(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._services))

    def federate_snapshot_vector(
        self,
        *,
        catalog_snapshots: Mapping[str, int],
    ) -> Mapping[str, Any]:
        """Build an explicit snapshot vector across independent shards.

        Federation is only through explicit snapshot vectors — never through
        shared mutable session state or multi-owner catalog opens.
        """

        with self._lock:
            vector: dict[str, int] = {}
            for catalog_id, snapshot in catalog_snapshots.items():
                if catalog_id not in self._services:
                    raise CatalogServiceError(
                        f"cannot federate unknown catalog {catalog_id!r}"
                    )
                vector[str(catalog_id)] = int(snapshot)
            return MappingProxyType(
                {
                    "schema": "ipfs_datasets_py/ducklake-snapshot-vector@1",
                    "members": vector,
                    "federation": "explicit_snapshot_vectors_only",
                    "shared_mutable_session": False,
                    "multi_owner": False,
                }
            )

    def as_mapping(self) -> Mapping[str, Any]:
        with self._lock:
            return MappingProxyType(
                {
                    "schema": CATALOG_SERVICE_SCHEMA,
                    "catalogs": {
                        cid: dict(svc.as_mapping())
                        for cid, svc in self._services.items()
                    },
                    "independent_shard_concurrency": True,
                    "same_shard_serialization": True,
                }
            )
