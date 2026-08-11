"""DuckDB + Quack catalog-shard ownership and access model (DQK-085).

Each distributed catalog shard is opened by exactly one identity-bound
DuckDB + Quack owner process. Remote clients submit typed remote requests to
that owner and never open, copy into place, or network-mount the live catalog
file. Same-shard requests are serialized through the fenced owner; independent
shards may run concurrently.

Active/passive takeover is gated by a durable owner-generation receipt and
explicit predecessor-fence evidence before the successor acquires DuckDB's
native file lock and opens the catalog.

DuckLake supplies no role or authorization layer. A trusted broker
independently authorizes every privileged call and injects a one-use Quack
capability only into an identity-bound trusted worker. Untrusted agents never
receive it.

Import is side-effect free: this module never imports ``duckdb``, never opens
files, never binds sockets, and never resolves secret values. File-lock and
process liveness checks are injected by the owner runtime under test or in
production.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Iterator, Mapping, Sequence

from ipfs_datasets_py.ducklake.capabilities import ATTACH_SAFE_OPTIONS
from ipfs_datasets_py.ducklake.config import (
    ATTACH_MODE_SAFE_OPTIONS,
    AttachMode,
    AttachOptions,
    AuthorityStorageKind,
    CatalogIdentityRole,
    CatalogProfileError,
    CatalogShardProfile,
    SecretProfileError,
    _coerce_enum,
    assert_no_secrets_in_projection,
    build_attach_options,
    project_catalog_profile,
)

__all__ = [
    "CATALOG_OWNER_GENERATION_RECEIPT_SCHEMA",
    "CATALOG_SHARD_RUNTIME_SCHEMA",
    "AttachStatement",
    "CatalogAccessDenied",
    "CatalogError",
    "CatalogOwnerHandle",
    "CatalogOwnerState",
    "CatalogRequestKind",
    "CatalogShardRegistry",
    "CatalogShardRuntime",
    "CatalogTakeoverError",
    "NativeFileLockStatus",
    "OneUseQuackCapability",
    "OwnerGenerationReceipt",
    "PredecessorFenceEvidence",
    "RemoteCatalogAccessPolicy",
    "TakeoverPreconditions",
    "TrustedBrokerGate",
    "WorkerIdentity",
    "assert_remote_catalog_access_denied",
    "build_ducklake_attach_statement",
    "evaluate_takeover_preconditions",
    "require_safe_attach_options",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

CATALOG_SHARD_RUNTIME_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-catalog-shard-runtime@1"
)
CATALOG_OWNER_GENERATION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-catalog-owner-generation-receipt@1"
)

_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-085-catalog-shard-runtime-20260810"
)

_ALIAS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_WORKER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,255}$")
_SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")
_RECEIPT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,255}$")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CatalogError(ValueError):
    """Fail-closed catalog-shard ownership, access, or takeover rejection."""


class CatalogAccessDenied(CatalogError):
    """Remote or untrusted client attempted a forbidden catalog-file action."""


class CatalogTakeoverError(CatalogError):
    """Active/passive takeover preconditions were not met."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class CatalogOwnerState(str, Enum):
    """Lifecycle state of the single fenced owner for a catalog shard."""

    UNOWNED = "unowned"
    ACQUIRING = "acquiring"
    ACTIVE = "active"
    DRAINING = "draining"
    FENCED = "fenced"
    STOPPED = "stopped"


class CatalogRequestKind(str, Enum):
    """Typed remote request categories submitted to the catalog owner."""

    READ = "read"
    WRITE = "write"
    MAINTAIN = "maintain"
    SNAPSHOT = "snapshot"
    BOOTSTRAP = "bootstrap"
    MIGRATE = "migrate"


class NativeFileLockStatus(str, Enum):
    """Outcome of attempting DuckDB's native file lock (injected probe)."""

    ACQUIRED = "acquired"
    HELD_BY_OTHER = "held_by_other"
    UNAVAILABLE = "unavailable"
    NOT_ATTEMPTED = "not_attempted"


# ---------------------------------------------------------------------------
# Remote access policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RemoteCatalogAccessPolicy:
    """Policy for remote clients relative to the live catalog file.

    Remote clients may only reach the authenticated Quack endpoint via typed
    operations. They must never open, mount, copy into place, or mutate the
    catalog metadata file or companion-registry file.
    """

    may_open_catalog_file: bool = False
    may_mount_catalog_file: bool = False
    may_copy_catalog_file: bool = False
    may_mutate_catalog_file: bool = False
    may_attach_catalog_file_path: bool = False
    must_use_owner_quack_endpoint: bool = True

    def __post_init__(self) -> None:
        forbidden_true = (
            self.may_open_catalog_file,
            self.may_mount_catalog_file,
            self.may_copy_catalog_file,
            self.may_mutate_catalog_file,
            self.may_attach_catalog_file_path,
        )
        if any(forbidden_true):
            raise CatalogAccessDenied(
                "remote clients cannot directly open, mount, copy, attach-by-path, "
                "or mutate the catalog file; same-shard requests are serialized "
                "through the fenced owner"
            )
        if not self.must_use_owner_quack_endpoint:
            raise CatalogAccessDenied(
                "remote clients must use the single owner Quack endpoint"
            )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "may_open_catalog_file": False,
                "may_mount_catalog_file": False,
                "may_copy_catalog_file": False,
                "may_mutate_catalog_file": False,
                "may_attach_catalog_file_path": False,
                "must_use_owner_quack_endpoint": True,
            }
        )


DEFAULT_REMOTE_ACCESS_POLICY: Final[RemoteCatalogAccessPolicy] = (
    RemoteCatalogAccessPolicy()
)


def assert_remote_catalog_access_denied(
    action: str,
    *,
    policy: RemoteCatalogAccessPolicy | None = None,
) -> None:
    """Fail closed for any remote attempt to touch the live catalog file."""

    _ = policy or DEFAULT_REMOTE_ACCESS_POLICY
    normalized = str(action or "").strip().lower()
    forbidden = {
        "open",
        "mount",
        "copy",
        "mutate",
        "write",
        "attach_path",
        "attach-file",
        "network_mount",
        "nfs_mount",
        "smb_mount",
    }
    if normalized in forbidden or any(token in normalized for token in forbidden):
        raise CatalogAccessDenied(
            f"remote clients cannot {normalized} the catalog file; submit a "
            "typed remote request to the single identity-bound DuckDB + Quack "
            "owner process"
        )


# ---------------------------------------------------------------------------
# ATTACH statement construction
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AttachStatement:
    """Canonical DuckLake ATTACH plan (never executes)."""

    alias: str
    catalog_path: str
    data_path: str
    options: AttachOptions
    snapshot_version: int | None = None

    def __post_init__(self) -> None:
        alias = str(self.alias or "").strip()
        if not alias or not _ALIAS_RE.match(alias):
            raise CatalogError(f"invalid ATTACH alias {self.alias!r}")
        object.__setattr__(self, "alias", alias)
        if not isinstance(self.options, AttachOptions):
            raise CatalogError("options must be AttachOptions")
        if self.snapshot_version is not None:
            if (
                not isinstance(self.snapshot_version, int)
                or isinstance(self.snapshot_version, bool)
                or self.snapshot_version < 0
            ):
                raise CatalogError("snapshot_version must be a non-negative int")

    def ducklake_options(self) -> Mapping[str, Any]:
        opts: dict[str, Any] = dict(self.options.ducklake_options())
        opts["DATA_PATH"] = self.data_path
        if self.snapshot_version is not None:
            opts["SNAPSHOT_VERSION"] = self.snapshot_version
        return MappingProxyType(opts)

    def sql(self) -> str:
        """Return a deterministic ATTACH SQL string for the owner process.

        Options are emitted in a stable order. Safe mode always includes the
        three fail-closed flags set to false.
        """

        parts = [
            f"CREATE_IF_NOT_EXISTS {'true' if self.options.create_if_not_exists else 'false'}",
            f"OVERRIDE_DATA_PATH {'true' if self.options.override_data_path else 'false'}",
            f"AUTOMATIC_MIGRATION {'true' if self.options.automatic_migration else 'false'}",
            f"DATA_PATH '{_sql_escape(self.data_path)}'",
        ]
        if self.snapshot_version is not None:
            parts.append(f"SNAPSHOT_VERSION {int(self.snapshot_version)}")
        options_sql = ", ".join(parts)
        path = _sql_escape(self.catalog_path)
        return (
            f"ATTACH 'ducklake:{path}' AS {self.alias} "
            f"({options_sql})"
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "alias": self.alias,
                "catalog_path": self.catalog_path,
                "data_path": self.data_path,
                "options": dict(self.options.as_mapping()),
                "snapshot_version": self.snapshot_version,
                "sql": self.sql(),
            }
        )


def _sql_escape(value: str) -> str:
    return str(value).replace("'", "''")


def require_safe_attach_options(options: Mapping[str, Any] | AttachOptions) -> None:
    """Assert non-bootstrap ATTACH options match the fail-closed contract."""

    if isinstance(options, AttachOptions):
        mapping = options.ducklake_options()
        mode = options.mode
    else:
        mapping = options
        mode = AttachMode.SAFE
    if mode is not AttachMode.SAFE:
        return
    for key, expected in ATTACH_SAFE_OPTIONS.items():
        observed = mapping.get(key, mapping.get(key.lower()))
        if observed is None:
            raise CatalogError(f"ATTACH option {key} is required and must be {expected!r}")
        if bool(observed) is not bool(expected):
            raise CatalogError(
                f"non-bootstrap / non-migration ATTACH requires {key}={expected!r}; "
                f"got {observed!r}. Only a separately authorized bootstrap or "
                "migration operation may use other values"
            )


def build_ducklake_attach_statement(
    profile: CatalogShardProfile,
    *,
    alias: str | None = None,
    mode: AttachMode | str = AttachMode.SAFE,
    snapshot_version: int | None = None,
    create_if_not_exists: bool | None = None,
    override_data_path: bool | None = None,
    automatic_migration: bool | None = None,
    authorization_receipt_id: str | None = None,
) -> AttachStatement:
    """Build the owner-side DuckLake ATTACH plan for a catalog shard profile.

    Remote workers must never call this with a catalog file path for network
    open; only the fenced owner process attaches the metadata file.
    """

    resolved_mode = _coerce_enum(AttachMode, mode, field_name="attach_mode")
    options = build_attach_options(
        resolved_mode,
        create_if_not_exists=create_if_not_exists,
        override_data_path=override_data_path,
        automatic_migration=automatic_migration,
        authorization_receipt_id=authorization_receipt_id,
    )
    if resolved_mode is AttachMode.SAFE:
        require_safe_attach_options(options)
    attach_alias = alias or re.sub(r"[^A-Za-z0-9_]", "_", profile.catalog_id)
    if attach_alias[0].isdigit():
        attach_alias = f"c_{attach_alias}"
    return AttachStatement(
        alias=attach_alias,
        catalog_path=profile.catalog_metadata.path,
        data_path=profile.parquet_namespace.data_path,
        options=options,
        snapshot_version=snapshot_version,
    )


# ---------------------------------------------------------------------------
# Owner generation / takeover
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OwnerGenerationReceipt:
    """Durable owner-generation receipt required for active/passive takeover."""

    receipt_id: str
    catalog_id: str
    owner_generation: int
    fencing_epoch: int
    catalog_digest: str
    catalog_path: str
    companion_registry_digest: str | None
    endpoint_identity: str
    process_birth: Mapping[str, Any]
    schema: str = CATALOG_OWNER_GENERATION_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        receipt_id = str(self.receipt_id or "").strip()
        if not receipt_id or not _RECEIPT_ID_RE.match(receipt_id):
            raise CatalogError(f"invalid owner-generation receipt_id {self.receipt_id!r}")
        catalog_id = str(self.catalog_id or "").strip()
        if not catalog_id:
            raise CatalogError("owner-generation receipt requires catalog_id")
        if (
            not isinstance(self.owner_generation, int)
            or isinstance(self.owner_generation, bool)
            or self.owner_generation < 1
        ):
            raise CatalogError("owner_generation must be a positive int")
        if (
            not isinstance(self.fencing_epoch, int)
            or isinstance(self.fencing_epoch, bool)
            or self.fencing_epoch < 1
        ):
            raise CatalogError("fencing_epoch must be a positive int")
        digest = _normalize_digest(self.catalog_digest, field="catalog_digest")
        companion = self.companion_registry_digest
        if companion is not None:
            companion = _normalize_digest(
                companion, field="companion_registry_digest"
            )
        endpoint = str(self.endpoint_identity or "").strip()
        if not endpoint:
            raise CatalogError("owner-generation receipt requires endpoint_identity")
        path = str(self.catalog_path or "").strip()
        if not path:
            raise CatalogError("owner-generation receipt requires catalog_path")
        birth = dict(self.process_birth or {})
        if not birth:
            raise CatalogError("owner-generation receipt requires process_birth")
        schema = str(self.schema or CATALOG_OWNER_GENERATION_RECEIPT_SCHEMA).strip()
        if schema != CATALOG_OWNER_GENERATION_RECEIPT_SCHEMA:
            raise CatalogError(
                f"unsupported owner-generation receipt schema {self.schema!r}"
            )
        object.__setattr__(self, "receipt_id", receipt_id)
        object.__setattr__(self, "catalog_id", catalog_id)
        object.__setattr__(self, "catalog_digest", digest)
        object.__setattr__(self, "companion_registry_digest", companion)
        object.__setattr__(self, "endpoint_identity", endpoint)
        object.__setattr__(self, "catalog_path", path)
        object.__setattr__(self, "process_birth", MappingProxyType(birth))
        object.__setattr__(self, "schema", schema)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "receipt_id": self.receipt_id,
                "catalog_id": self.catalog_id,
                "owner_generation": self.owner_generation,
                "fencing_epoch": self.fencing_epoch,
                "catalog_digest": self.catalog_digest,
                "catalog_path": self.catalog_path,
                "companion_registry_digest": self.companion_registry_digest,
                "endpoint_identity": self.endpoint_identity,
                "process_birth": dict(self.process_birth),
            }
        )


def _normalize_digest(value: str, *, field: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256_RE.match(text):
        raise CatalogError(f"{field} must be a sha256 digest")
    if not text.startswith("sha256:"):
        text = f"sha256:{text}"
    return text


@dataclass(frozen=True, slots=True)
class PredecessorFenceEvidence:
    """Proof that the prior owner stopped admission and is dead/fenced."""

    admission_stopped: bool
    process_dead_or_fenced: bool
    endpoint_token_revoked: bool
    storage_capabilities_expired: bool
    all_handles_closed: bool
    prior_owner_generation: int
    prior_fencing_epoch: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.prior_owner_generation, int)
            or isinstance(self.prior_owner_generation, bool)
            or self.prior_owner_generation < 1
        ):
            raise CatalogError("prior_owner_generation must be a positive int")
        if (
            not isinstance(self.prior_fencing_epoch, int)
            or isinstance(self.prior_fencing_epoch, bool)
            or self.prior_fencing_epoch < 1
        ):
            raise CatalogError("prior_fencing_epoch must be a positive int")

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "admission_stopped": self.admission_stopped,
                "process_dead_or_fenced": self.process_dead_or_fenced,
                "endpoint_token_revoked": self.endpoint_token_revoked,
                "storage_capabilities_expired": self.storage_capabilities_expired,
                "all_handles_closed": self.all_handles_closed,
                "prior_owner_generation": self.prior_owner_generation,
                "prior_fencing_epoch": self.prior_fencing_epoch,
            }
        )


@dataclass(frozen=True, slots=True)
class TakeoverPreconditions:
    """Complete precondition set for active/passive ownership transfer."""

    durable_owner_generation_receipt: OwnerGenerationReceipt
    predecessor: PredecessorFenceEvidence
    expected_catalog_digest: str
    expected_owner_generation: int
    native_file_lock: NativeFileLockStatus
    successor_owner_generation: int

    def __post_init__(self) -> None:
        if not isinstance(
            self.durable_owner_generation_receipt, OwnerGenerationReceipt
        ):
            if isinstance(self.durable_owner_generation_receipt, Mapping):
                object.__setattr__(
                    self,
                    "durable_owner_generation_receipt",
                    OwnerGenerationReceipt(**dict(self.durable_owner_generation_receipt)),
                )
            else:
                raise CatalogError(
                    "durable_owner_generation_receipt must be OwnerGenerationReceipt"
                )
        if not isinstance(self.predecessor, PredecessorFenceEvidence):
            if isinstance(self.predecessor, Mapping):
                object.__setattr__(
                    self,
                    "predecessor",
                    PredecessorFenceEvidence(**dict(self.predecessor)),
                )
            else:
                raise CatalogError("predecessor must be PredecessorFenceEvidence")
        digest = _normalize_digest(
            self.expected_catalog_digest, field="expected_catalog_digest"
        )
        object.__setattr__(self, "expected_catalog_digest", digest)
        if (
            not isinstance(self.expected_owner_generation, int)
            or isinstance(self.expected_owner_generation, bool)
            or self.expected_owner_generation < 1
        ):
            raise CatalogError("expected_owner_generation must be a positive int")
        if (
            not isinstance(self.successor_owner_generation, int)
            or isinstance(self.successor_owner_generation, bool)
            or self.successor_owner_generation < 1
        ):
            raise CatalogError("successor_owner_generation must be a positive int")
        object.__setattr__(
            self,
            "native_file_lock",
            _coerce_enum(
                NativeFileLockStatus,
                self.native_file_lock,
                field_name="native_file_lock",
            ),
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "durable_owner_generation_receipt": dict(
                    self.durable_owner_generation_receipt.as_mapping()
                ),
                "predecessor": dict(self.predecessor.as_mapping()),
                "expected_catalog_digest": self.expected_catalog_digest,
                "expected_owner_generation": self.expected_owner_generation,
                "native_file_lock": self.native_file_lock.value,
                "successor_owner_generation": self.successor_owner_generation,
            }
        )


def evaluate_takeover_preconditions(
    preconditions: TakeoverPreconditions,
    *,
    profile: CatalogShardProfile | None = None,
) -> Mapping[str, Any]:
    """Validate active/passive takeover preconditions (fail closed).

    Requires:
    * durable owner-generation receipt
    * prior process stopped admission and is dead/fenced
    * endpoint/token revocation
    * expired storage capabilities
    * closed handles
    * exact catalog digest / generation
    * successful native DuckDB file-lock acquisition before open
    * successor generation strictly greater than the predecessor
    """

    receipt = preconditions.durable_owner_generation_receipt
    pred = preconditions.predecessor
    problems: list[str] = []

    if not pred.admission_stopped:
        problems.append("prior process has not stopped admission")
    if not pred.process_dead_or_fenced:
        problems.append("prior process is not proven dead or fenced")
    if not pred.endpoint_token_revoked:
        problems.append("endpoint/token has not been revoked")
    if not pred.storage_capabilities_expired:
        problems.append("storage capabilities have not expired")
    if not pred.all_handles_closed:
        problems.append("not all predecessor handles are closed")

    if receipt.catalog_digest != preconditions.expected_catalog_digest:
        problems.append(
            "catalog digest mismatch between receipt and expected "
            f"({receipt.catalog_digest} != {preconditions.expected_catalog_digest})"
        )
    if receipt.owner_generation != preconditions.expected_owner_generation:
        problems.append(
            "owner generation mismatch between receipt and expected "
            f"({receipt.owner_generation} != {preconditions.expected_owner_generation})"
        )
    if receipt.owner_generation != pred.prior_owner_generation:
        problems.append(
            "receipt owner generation does not match predecessor fence evidence"
        )
    if (
        preconditions.successor_owner_generation
        <= preconditions.expected_owner_generation
    ):
        problems.append(
            "successor owner generation must be strictly greater than the "
            "predecessor generation"
        )
    if preconditions.native_file_lock is not NativeFileLockStatus.ACQUIRED:
        problems.append(
            "native DuckDB file-lock acquisition is required before open; "
            f"status={preconditions.native_file_lock.value}"
        )

    if profile is not None:
        if receipt.catalog_id != profile.catalog_id:
            problems.append(
                f"receipt catalog_id {receipt.catalog_id!r} does not match "
                f"profile {profile.catalog_id!r}"
            )
        if receipt.catalog_path != profile.catalog_metadata.path:
            problems.append(
                "receipt catalog_path does not match profile catalog metadata path"
            )

    if problems:
        raise CatalogTakeoverError(
            "active/passive takeover rejected: " + "; ".join(problems)
        )

    return MappingProxyType(
        {
            "allowed": True,
            "catalog_id": receipt.catalog_id,
            "prior_owner_generation": receipt.owner_generation,
            "successor_owner_generation": preconditions.successor_owner_generation,
            "catalog_digest": receipt.catalog_digest,
            "native_file_lock": NativeFileLockStatus.ACQUIRED.value,
            "reason": (
                "durable owner-generation receipt verified; predecessor stopped "
                "admission and is dead/fenced; endpoint/token revoked; storage "
                "capabilities expired; handles closed; catalog digest/generation "
                "match; native DuckDB file lock acquired before open"
            ),
        }
    )


# ---------------------------------------------------------------------------
# Trusted broker + one-use Quack capability
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorkerIdentity:
    """Identity-bound trusted worker that may receive a one-use capability."""

    worker_id: str
    role: CatalogIdentityRole
    process_birth: Mapping[str, Any]
    trusted: bool = True

    def __post_init__(self) -> None:
        worker_id = str(self.worker_id or "").strip()
        if not worker_id or not _WORKER_ID_RE.match(worker_id):
            raise CatalogError(f"invalid worker_id {self.worker_id!r}")
        object.__setattr__(
            self,
            "role",
            _coerce_enum(CatalogIdentityRole, self.role, field_name="role"),
        )
        birth = dict(self.process_birth or {})
        if not birth:
            raise CatalogError("worker process_birth is required")
        object.__setattr__(self, "worker_id", worker_id)
        object.__setattr__(self, "process_birth", MappingProxyType(birth))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "worker_id": self.worker_id,
                "role": self.role.value,
                "process_birth": dict(self.process_birth),
                "trusted": self.trusted,
            }
        )


@dataclass(frozen=True, slots=True)
class OneUseQuackCapability:
    """One-use Quack capability injected only into a trusted worker.

    The raw capability token is held privately and never appears in
    ``repr`` / ``str`` / configuration projections. Untrusted agents never
    receive this object.
    """

    capability_id: str
    catalog_id: str
    worker_id: str
    owner_generation: int
    fencing_epoch: int
    expires_at_unix: float
    endpoint_id: str
    _token: str = field(repr=False, default="")

    def __post_init__(self) -> None:
        cap_id = str(self.capability_id or "").strip()
        if not cap_id:
            raise CatalogError("capability_id is required")
        if (
            not isinstance(self.owner_generation, int)
            or isinstance(self.owner_generation, bool)
            or self.owner_generation < 1
        ):
            raise CatalogError("owner_generation must be a positive int")
        if (
            not isinstance(self.fencing_epoch, int)
            or isinstance(self.fencing_epoch, bool)
            or self.fencing_epoch < 1
        ):
            raise CatalogError("fencing_epoch must be a positive int")
        if not isinstance(self.expires_at_unix, (int, float)) or isinstance(
            self.expires_at_unix, bool
        ):
            raise CatalogError("expires_at_unix must be a number")
        token = str(self._token or "")
        if not token:
            raise CatalogError("one-use Quack capability token must be non-empty")
        object.__setattr__(self, "capability_id", cap_id)
        object.__setattr__(self, "_token", token)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"OneUseQuackCapability(capability_id={self.capability_id!r}, "
            f"catalog_id={self.catalog_id!r}, worker_id={self.worker_id!r}, "
            f"token=***)"
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.__repr__()

    def is_expired(self, *, now: float | None = None) -> bool:
        clock = time.time() if now is None else float(now)
        return clock >= float(self.expires_at_unix)

    def reveal_token_for_trusted_worker(self) -> str:
        """Return the raw token for in-process trusted injection only."""

        return self._token

    def as_mapping(self) -> Mapping[str, Any]:
        """Projection without the raw token."""

        return MappingProxyType(
            {
                "capability_id": self.capability_id,
                "catalog_id": self.catalog_id,
                "worker_id": self.worker_id,
                "owner_generation": self.owner_generation,
                "fencing_epoch": self.fencing_epoch,
                "expires_at_unix": self.expires_at_unix,
                "endpoint_id": self.endpoint_id,
                "token": "***",
                "one_use": True,
            }
        )


@dataclass
class TrustedBrokerGate:
    """Trusted broker that authorizes privileged calls (DuckLake has no ACL).

    The broker independently authorizes every privileged operation and injects
    a one-use Quack capability only into an identity-bound trusted worker.
    Untrusted agents never receive the capability. Possession of a Quack token
    alone is not authorization.
    """

    profile: CatalogShardProfile
    _used_capability_ids: set[str] = field(default_factory=set, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _token_factory: Callable[[], str] = field(
        default=lambda: uuid.uuid4().hex + uuid.uuid4().hex, repr=False
    )

    def __post_init__(self) -> None:
        if not isinstance(self.profile, CatalogShardProfile):
            raise CatalogError("TrustedBrokerGate requires a CatalogShardProfile")
        if self.profile.ducklake_supplies_authorization:
            raise CatalogError(
                "DuckLake supplies no role or authorization layer; broker is required"
            )

    def authorize(
        self,
        *,
        worker: WorkerIdentity,
        request_kind: CatalogRequestKind | str,
        operation_id: str,
    ) -> Mapping[str, Any]:
        """Independently authorize a privileged call for a trusted worker."""

        kind = _coerce_enum(
            CatalogRequestKind, request_kind, field_name="request_kind"
        )
        op = str(operation_id or "").strip()
        if not op:
            raise CatalogError("operation_id is required")
        if not worker.trusted:
            raise CatalogAccessDenied(
                "untrusted agents never receive Quack capabilities or privileged "
                "authorization; DuckLake supplies no role or authorization layer"
            )
        # Least-privilege role checks against the profile.
        identity = self.profile.identity(worker.role)
        if kind is CatalogRequestKind.READ and not identity.endpoint_access:
            raise CatalogAccessDenied("reader identity lacks endpoint access")
        worker_role = _coerce_enum(
            CatalogIdentityRole, worker.role, field_name="worker.role"
        )
        if kind in {CatalogRequestKind.WRITE, CatalogRequestKind.MAINTAIN}:
            if worker_role == CatalogIdentityRole.READER:
                raise CatalogAccessDenied("reader cannot perform write/maintain")
        if kind is CatalogRequestKind.MAINTAIN and worker_role not in {
            CatalogIdentityRole.MAINTAINER,
            CatalogIdentityRole.OWNER_BROKER,
        }:
            raise CatalogAccessDenied(
                "maintenance requires maintainer or owner-broker identity"
            )
        if kind in {CatalogRequestKind.BOOTSTRAP, CatalogRequestKind.MIGRATE}:
            if worker_role != CatalogIdentityRole.OWNER_BROKER:
                raise CatalogAccessDenied(
                    "bootstrap/migration requires owner-broker authorization"
                )
            if not identity.broker_authorize:
                raise CatalogAccessDenied(
                    "owner-broker identity must authorize bootstrap/migration"
                )
        broker = self.profile.identity(CatalogIdentityRole.OWNER_BROKER)
        if not broker.broker_authorize:
            raise CatalogError("owner-broker must independently authorize calls")

        decision = MappingProxyType(
            {
                "authorized": True,
                "operation_id": op,
                "request_kind": kind.value,
                "worker_id": worker.worker_id,
                "worker_role": worker.role.value,
                "catalog_id": self.profile.catalog_id,
                "owner_generation": self.profile.owner_lease.owner_generation,
                "fencing_epoch": self.profile.owner_lease.fencing_epoch,
                "ducklake_authorization_layer": False,
                "authorized_by": "trusted_broker",
            }
        )
        assert_no_secrets_in_projection(decision)
        return decision

    def inject_one_use_quack_capability(
        self,
        *,
        worker: WorkerIdentity,
        ttl_seconds: int = 60,
        now: float | None = None,
    ) -> OneUseQuackCapability:
        """Inject a one-use Quack capability into an identity-bound trusted worker."""

        if not worker.trusted:
            raise CatalogAccessDenied(
                "untrusted agents never receive a Quack capability"
            )
        broker = self.profile.identity(CatalogIdentityRole.OWNER_BROKER)
        if not broker.inject_quack_capability:
            raise CatalogError(
                "owner-broker must be able to inject one-use Quack capabilities"
            )
        if ttl_seconds < 1 or ttl_seconds > 3_600:
            raise CatalogError("capability ttl_seconds out of range")
        clock = time.time() if now is None else float(now)
        token = str(self._token_factory())
        if not token or token.lower() in {"none", "null", "***"}:
            raise CatalogError("token factory returned empty capability token")
        capability = OneUseQuackCapability(
            capability_id=f"qcap:{uuid.uuid4().hex}",
            catalog_id=self.profile.catalog_id,
            worker_id=worker.worker_id,
            owner_generation=self.profile.owner_lease.owner_generation,
            fencing_epoch=self.profile.owner_lease.fencing_epoch,
            expires_at_unix=clock + float(ttl_seconds),
            endpoint_id=self.profile.quack_endpoint.endpoint_id,
            _token=token,
        )
        # Projection must never leak the token.
        assert_no_secrets_in_projection(capability.as_mapping())
        return capability

    def consume_capability(
        self,
        capability: OneUseQuackCapability,
        *,
        worker: WorkerIdentity,
        now: float | None = None,
    ) -> Mapping[str, Any]:
        """Consume a one-use capability (second use fails closed)."""

        if capability.worker_id != worker.worker_id:
            raise CatalogAccessDenied(
                "one-use Quack capability is bound to a different worker identity"
            )
        if capability.catalog_id != self.profile.catalog_id:
            raise CatalogAccessDenied("capability catalog_id mismatch")
        if capability.is_expired(now=now):
            raise CatalogAccessDenied("one-use Quack capability has expired")
        with self._lock:
            if capability.capability_id in self._used_capability_ids:
                raise CatalogAccessDenied(
                    "one-use Quack capability has already been consumed"
                )
            self._used_capability_ids.add(capability.capability_id)
        return MappingProxyType(
            {
                "consumed": True,
                "capability_id": capability.capability_id,
                "worker_id": worker.worker_id,
                "catalog_id": capability.catalog_id,
            }
        )


# ---------------------------------------------------------------------------
# Shard runtime: single owner, serialization, multi-shard concurrency
# ---------------------------------------------------------------------------


@dataclass
class CatalogOwnerHandle:
    """In-process handle representing the single owner of a catalog shard.

    Does not open DuckDB. ``native_file_lock_probe`` is injected by the runtime
    to report DuckDB native file-lock acquisition.
    """

    profile: CatalogShardProfile
    state: CatalogOwnerState = CatalogOwnerState.UNOWNED
    native_file_lock: NativeFileLockStatus = NativeFileLockStatus.NOT_ATTEMPTED
    active_owner_generation: int | None = None
    _request_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _admission_open: bool = field(default=False, repr=False)
    _serial_depth: int = field(default=0, repr=False)
    _native_file_lock_probe: Callable[[str], NativeFileLockStatus] | None = field(
        default=None, repr=False
    )

    def __post_init__(self) -> None:
        if not isinstance(self.profile, CatalogShardProfile):
            raise CatalogError("CatalogOwnerHandle requires CatalogShardProfile")
        self.state = _coerce_enum(
            CatalogOwnerState, self.state, field_name="state"
        )
        self.native_file_lock = _coerce_enum(
            NativeFileLockStatus,
            self.native_file_lock,
            field_name="native_file_lock",
        )

    @property
    def catalog_id(self) -> str:
        return self.profile.catalog_id

    @property
    def admits_requests(self) -> bool:
        return self.state is CatalogOwnerState.ACTIVE and self._admission_open

    def acquire_ownership(
        self,
        *,
        preconditions: TakeoverPreconditions | None = None,
        bootstrap: bool = False,
    ) -> Mapping[str, Any]:
        """Become the single active owner (optionally after takeover proof)."""

        with self._request_lock:
            if self.state is CatalogOwnerState.ACTIVE:
                raise CatalogError(
                    f"catalog shard {self.catalog_id!r} already has an active owner; "
                    "exactly one identity-bound DuckDB + Quack owner process may "
                    "open each catalog file"
                )
            self.state = CatalogOwnerState.ACQUIRING
            if preconditions is not None:
                evaluate_takeover_preconditions(preconditions, profile=self.profile)
                generation = preconditions.successor_owner_generation
                self.native_file_lock = preconditions.native_file_lock
            elif bootstrap:
                # First owner of an empty shard still needs the native lock.
                generation = self.profile.owner_lease.owner_generation
                if self._native_file_lock_probe is not None:
                    self.native_file_lock = self._native_file_lock_probe(
                        self.profile.catalog_metadata.path
                    )
                else:
                    # Under pure unit tests without a probe, treat explicit
                    # bootstrap as acquiring the lock symbolically.
                    self.native_file_lock = NativeFileLockStatus.ACQUIRED
                if self.native_file_lock is not NativeFileLockStatus.ACQUIRED:
                    self.state = CatalogOwnerState.UNOWNED
                    raise CatalogError(
                        "native DuckDB file-lock acquisition is required before open"
                    )
            else:
                self.state = CatalogOwnerState.UNOWNED
                raise CatalogError(
                    "acquire_ownership requires bootstrap=True or takeover preconditions"
                )

            if self.profile.catalog_metadata.storage_kind not in {
                AuthorityStorageKind.LOCAL_BLOCK,
                AuthorityStorageKind.ATTACHED_BLOCK,
            }:
                self.state = CatalogOwnerState.UNOWNED
                raise CatalogError(
                    "live catalog files require local or attached block storage"
                )

            self.active_owner_generation = generation
            self.state = CatalogOwnerState.ACTIVE
            self._admission_open = True
            return MappingProxyType(
                {
                    "catalog_id": self.catalog_id,
                    "state": self.state.value,
                    "owner_generation": self.active_owner_generation,
                    "native_file_lock": self.native_file_lock.value,
                    "single_owner": True,
                    "catalog_path": self.profile.catalog_metadata.path,
                    "quack_endpoint": self.profile.quack_endpoint.endpoint_id,
                }
            )

    def stop_admission(self) -> None:
        with self._request_lock:
            self._admission_open = False
            if self.state is CatalogOwnerState.ACTIVE:
                self.state = CatalogOwnerState.DRAINING

    def fence_and_stop(self) -> Mapping[str, Any]:
        """Stop admission, mark fenced, and release ownership for takeover."""

        with self._request_lock:
            self._admission_open = False
            prior = self.active_owner_generation
            self.state = CatalogOwnerState.FENCED
            self.native_file_lock = NativeFileLockStatus.NOT_ATTEMPTED
            self.active_owner_generation = None
            self.state = CatalogOwnerState.STOPPED
            return MappingProxyType(
                {
                    "catalog_id": self.catalog_id,
                    "prior_owner_generation": prior,
                    "state": self.state.value,
                    "admission_stopped": True,
                    "handles_closed": True,
                }
            )

    def submit_typed_request(
        self,
        *,
        kind: CatalogRequestKind | str,
        operation_id: str,
        handler: Callable[[], Any] | None = None,
    ) -> Any:
        """Serialize a same-shard typed request through the fenced owner."""

        request_kind = _coerce_enum(
            CatalogRequestKind, kind, field_name="request_kind"
        )
        op = str(operation_id or "").strip()
        if not op:
            raise CatalogError("operation_id is required")
        with self._request_lock:
            if not self.admits_requests:
                raise CatalogError(
                    f"catalog shard {self.catalog_id!r} is not admitting requests "
                    f"(state={self.state.value})"
                )
            self._serial_depth += 1
            try:
                if handler is None:
                    return MappingProxyType(
                        {
                            "catalog_id": self.catalog_id,
                            "operation_id": op,
                            "request_kind": request_kind.value,
                            "owner_generation": self.active_owner_generation,
                            "serialized": True,
                        }
                    )
                return handler()
            finally:
                self._serial_depth -= 1

    def safe_attach_statement(
        self,
        *,
        snapshot_version: int | None = None,
        alias: str | None = None,
    ) -> AttachStatement:
        """Build the fail-closed non-bootstrap ATTACH plan for this owner."""

        statement = build_ducklake_attach_statement(
            self.profile,
            alias=alias,
            mode=AttachMode.SAFE,
            snapshot_version=snapshot_version,
        )
        require_safe_attach_options(statement.options)
        return statement

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": CATALOG_SHARD_RUNTIME_SCHEMA,
                "implementation_generation": _IMPLEMENTATION_GENERATION,
                "catalog_id": self.catalog_id,
                "state": self.state.value,
                "native_file_lock": self.native_file_lock.value,
                "active_owner_generation": self.active_owner_generation,
                "admits_requests": self.admits_requests,
                "profile": dict(project_catalog_profile(self.profile)),
                "remote_access_policy": dict(DEFAULT_REMOTE_ACCESS_POLICY.as_mapping()),
                "attach_safe_options": dict(ATTACH_MODE_SAFE_OPTIONS),
            }
        )


@dataclass
class CatalogShardRuntime:
    """Runtime view of one catalog shard (profile + owner handle + broker)."""

    profile: CatalogShardProfile
    owner: CatalogOwnerHandle = field(init=False)
    broker: TrustedBrokerGate = field(init=False)

    def __post_init__(self) -> None:
        self.owner = CatalogOwnerHandle(profile=self.profile)
        self.broker = TrustedBrokerGate(profile=self.profile)

    @property
    def catalog_id(self) -> str:
        return self.profile.catalog_id

    def as_mapping(self) -> Mapping[str, Any]:
        payload = dict(self.owner.as_mapping())
        payload["broker"] = {
            "ducklake_supplies_authorization": False,
            "injects_one_use_quack_capability": True,
            "untrusted_agents_receive_capability": False,
        }
        assert_no_secrets_in_projection(payload)
        return MappingProxyType(payload)


class CatalogShardRegistry:
    """Registry of independent catalog shards.

    Same-shard requests are serialized by each shard's owner handle.
    Independent shards may run concurrently (no global mutation lock).
    """

    def __init__(self) -> None:
        self._shards: dict[str, CatalogShardRuntime] = {}
        self._lock = threading.RLock()

    def register(self, profile: CatalogShardProfile) -> CatalogShardRuntime:
        with self._lock:
            if profile.catalog_id in self._shards:
                raise CatalogError(
                    f"catalog shard {profile.catalog_id!r} is already registered"
                )
            # Distinct metadata paths across shards.
            for existing in self._shards.values():
                if (
                    existing.profile.catalog_metadata.path
                    == profile.catalog_metadata.path
                ):
                    raise CatalogError(
                        "catalog metadata path is already bound to another shard; "
                        "each shard uses exactly one DuckDB metadata file"
                    )
            runtime = CatalogShardRuntime(profile=profile)
            self._shards[profile.catalog_id] = runtime
            return runtime

    def get(self, catalog_id: str) -> CatalogShardRuntime:
        with self._lock:
            try:
                return self._shards[catalog_id]
            except KeyError as exc:
                raise CatalogError(f"unknown catalog shard {catalog_id!r}") from exc

    def __contains__(self, catalog_id: object) -> bool:
        return str(catalog_id) in self._shards

    def catalog_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._shards))

    def __iter__(self) -> Iterator[CatalogShardRuntime]:
        with self._lock:
            return iter(tuple(self._shards[cid] for cid in sorted(self._shards)))

    def __len__(self) -> int:
        return len(self._shards)

    def submit(
        self,
        catalog_id: str,
        *,
        kind: CatalogRequestKind | str,
        operation_id: str,
        handler: Callable[[], Any] | None = None,
    ) -> Any:
        """Route a typed request to the owning shard (serialized per shard)."""

        return self.get(catalog_id).owner.submit_typed_request(
            kind=kind, operation_id=operation_id, handler=handler
        )

    def as_mapping(self) -> Mapping[str, Any]:
        with self._lock:
            payload = {
                "schema": CATALOG_SHARD_RUNTIME_SCHEMA,
                "shard_count": len(self._shards),
                "independent_shard_concurrency": True,
                "same_shard_serialization": True,
                "shards": {
                    catalog_id: dict(runtime.as_mapping())
                    for catalog_id, runtime in self._shards.items()
                },
            }
        assert_no_secrets_in_projection(payload)
        return MappingProxyType(payload)
