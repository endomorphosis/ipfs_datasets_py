"""DuckLake owner-broker security boundary (DQK-097).

DuckLake exposes **no** native role or authorization layer. A Quack token is
only a transport capability and is never sufficient to authorize a privileged
lake call. A trusted owner broker, distinct from workers and from the
credential issuer, independently authorizes every privileged operation and
issues short-lived, operation-scoped Quack/object capabilities bound to:

* the exact operation
* caller / process birth
* endpoint owner generation
* resource
* nonce
* expiry

Readers, writers, maintainers, and catalog owners hold distinct
endpoint/OS/storage capabilities. Only an independently authorized deletion
receives a separate scoped object-delete IAM grant. Remote workers cannot
open, copy, replace, or mount authority catalog files or companion registries.
Encryption keys and credentials never appear in logs, exports, receipts, or
agent-visible Quack responses.

Import is side-effect free: no ``duckdb``, sockets, extension LOAD, or secret
resolution occurs at import time.
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

__all__ = [
    "DUCKLAKE_SECURITY_SCHEMA",
    "OPERATION_CAPABILITY_SCHEMA",
    "OBJECT_DELETE_IAM_SCHEMA",
    "AUDIT_EVENT_SCHEMA",
    "DUCKLAKE_HAS_NATIVE_ROLE_LAYER",
    "QUACK_TOKEN_IS_TRANSPORT_ONLY",
    "REDACTION_MARKER",
    "SENSITIVE_LOG_KEYS",
    "FORBIDDEN_REMOTE_CATALOG_ACTIONS",
    "PRIVILEGED_OPERATIONS",
    "SecurityError",
    "AuthorizationDenied",
    "CapabilityError",
    "CredentialLeakError",
    "RemoteAccessDenied",
    "AuditError",
    "LakeIdentityRole",
    "PrivilegedOperation",
    "CapabilityKind",
    "ProcessBirth",
    "QuackTransportToken",
    "OperationScopedCapability",
    "ObjectDeleteIamGrant",
    "IdentityEndpointCapabilities",
    "TenantSchemaPrefix",
    "EncryptedParquetPolicy",
    "AuditEvent",
    "CredentialIssuer",
    "TrustedOwnerBroker",
    "DuckLakeSecurityBoundary",
    "assert_ducklake_has_no_native_role_layer",
    "assert_quack_token_cannot_authorize",
    "assert_remote_authority_action_denied",
    "default_identity_capabilities",
    "default_encrypted_parquet_policy",
    "scrub_sensitive_projection",
    "is_sensitive_key",
    "is_sensitive_value",
    "redact_for_log",
    "redact_for_export",
    "redact_for_receipt",
    "redact_for_agent_quack_response",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

DUCKLAKE_SECURITY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-security-boundary@1"
)
OPERATION_CAPABILITY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-operation-scoped-capability@1"
)
OBJECT_DELETE_IAM_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-object-delete-iam@1"
)
AUDIT_EVENT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-security-audit-event@1"
)

_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-097-ducklake-owner-broker-boundary-20260810"
)

# DuckLake itself is not a security boundary.
DUCKLAKE_HAS_NATIVE_ROLE_LAYER: Final[bool] = False
QUACK_TOKEN_IS_TRANSPORT_ONLY: Final[bool] = True

REDACTION_MARKER: Final[str] = "***REDACTED***"

_DEFAULT_CAPABILITY_TTL_SECONDS: Final[int] = 60
_MAX_CAPABILITY_TTL_SECONDS: Final[int] = 3_600
_MIN_CAPABILITY_TTL_SECONDS: Final[int] = 1
_DEFAULT_DELETE_IAM_TTL_SECONDS: Final[int] = 120

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{0,255}$")
_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")
_TENANT_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SCHEMA_PREFIX_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

SENSITIVE_LOG_KEYS: Final[frozenset[str]] = frozenset(
    {
        "token",
        "secret",
        "password",
        "credential",
        "credentials",
        "api_key",
        "apikey",
        "access_key",
        "secret_key",
        "private_key",
        "encryption_key",
        "encryption_keys",
        "file_key",
        "ducklake_key",
        "catalog_key",
        "quack_token",
        "raw_token",
        "bearer",
        "authorization_header",
        "signing_key",
        "session_token",
        "iam_secret",
        "object_delete_secret",
        "capability_secret",
        "capability_token",
        "auth_token",
        "writer_token",
        "authority_token",
    }
)

FORBIDDEN_REMOTE_CATALOG_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "open",
        "copy",
        "replace",
        "mount",
        "network_mount",
        "nfs_mount",
        "smb_mount",
        "attach_path",
        "attach-file",
        "write_file",
        "overwrite",
        "hardlink",
        "symlink",
    }
)

PRIVILEGED_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "read",
        "write",
        "maintain",
        "delete",
        "attach",
        "snapshot",
        "migrate",
        "bootstrap",
        "expire",
        "compact",
        "orphan_cleanup",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SecurityError(ValueError):
    """Fail-closed DuckLake security boundary rejection."""


class AuthorizationDenied(SecurityError):
    """Privileged call was not independently authorized by the owner broker."""


class CapabilityError(SecurityError):
    """Operation-scoped capability missing, expired, mismatched, or reused."""


class CredentialLeakError(SecurityError):
    """Encryption keys or credentials would leak into a visible surface."""


class RemoteAccessDenied(SecurityError):
    """Remote worker attempted a forbidden authority-file action."""


class AuditError(SecurityError):
    """Endpoint or owner-generation audit binding failed."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class LakeIdentityRole(str, Enum):
    """Distinct endpoint/OS/storage identity roles (outside DuckLake)."""

    READER = "reader"
    WRITER = "writer"
    MAINTAINER = "maintainer"
    CATALOG_OWNER = "catalog_owner"


class PrivilegedOperation(str, Enum):
    """Privileged lake call kinds that require independent broker authorization."""

    READ = "read"
    WRITE = "write"
    MAINTAIN = "maintain"
    DELETE = "delete"
    ATTACH = "attach"
    SNAPSHOT = "snapshot"
    MIGRATE = "migrate"
    BOOTSTRAP = "bootstrap"
    EXPIRE = "expire"
    COMPACT = "compact"
    ORPHAN_CLEANUP = "orphan_cleanup"


class CapabilityKind(str, Enum):
    """Short-lived capability kinds issued after independent authorization."""

    QUACK_TRANSPORT = "quack_transport"
    OBJECT_READ = "object_read"
    OBJECT_WRITE = "object_write"
    OBJECT_DELETE_IAM = "object_delete_iam"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_nonempty(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise SecurityError(f"{field_name} is required")
    return text


def _require_safe_token(value: Any, *, field_name: str) -> str:
    text = _require_nonempty(value, field_name=field_name)
    if not _SAFE_TOKEN.match(text):
        raise SecurityError(f"invalid {field_name} {value!r}")
    return text


def _require_positive_int(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise SecurityError(f"{field_name} must be a positive int")
    return value


def _require_nonneg_int(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SecurityError(f"{field_name} must be a non-negative int")
    return value


def _normalize_digest(value: str, *, field_name: str = "digest") -> str:
    text = str(value or "").strip().lower()
    if not _SHA256_RE.match(text):
        raise SecurityError(f"{field_name} must be a sha256 digest")
    if not text.startswith("sha256:"):
        text = f"sha256:{text}"
    return text


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _coerce_role(role: LakeIdentityRole | str) -> LakeIdentityRole:
    if isinstance(role, LakeIdentityRole):
        return role
    try:
        return LakeIdentityRole(str(role).strip().lower())
    except ValueError as exc:
        raise SecurityError(f"unknown lake identity role {role!r}") from exc


def _coerce_operation(op: PrivilegedOperation | str) -> PrivilegedOperation:
    if isinstance(op, PrivilegedOperation):
        return op
    try:
        return PrivilegedOperation(str(op).strip().lower())
    except ValueError as exc:
        raise SecurityError(f"unknown privileged operation {op!r}") from exc


def _coerce_capability_kind(kind: CapabilityKind | str) -> CapabilityKind:
    if isinstance(kind, CapabilityKind):
        return kind
    try:
        return CapabilityKind(str(kind).strip().lower())
    except ValueError as exc:
        raise SecurityError(f"unknown capability kind {kind!r}") from exc


# ---------------------------------------------------------------------------
# Public assertions (acceptance surface)
# ---------------------------------------------------------------------------


def assert_ducklake_has_no_native_role_layer() -> Mapping[str, Any]:
    """Prove DuckLake exposes no native role or authorization layer."""

    if DUCKLAKE_HAS_NATIVE_ROLE_LAYER:
        raise SecurityError(
            "DuckLake must not expose a native role layer; authorization is "
            "enforced exclusively by the trusted owner broker"
        )
    return MappingProxyType(
        {
            "schema": DUCKLAKE_SECURITY_SCHEMA,
            "ducklake_native_role_layer": False,
            "ducklake_authorization_layer": False,
            "security_boundary": "owner_broker",
            "implementation_generation": _IMPLEMENTATION_GENERATION,
        }
    )


def assert_quack_token_cannot_authorize(
    token: "QuackTransportToken | str | None",
    *,
    operation: PrivilegedOperation | str,
) -> None:
    """Fail closed: a Quack token alone never authorizes a privileged lake call."""

    op = _coerce_operation(operation)
    if not QUACK_TOKEN_IS_TRANSPORT_ONLY:
        raise SecurityError("Quack token must be transport-only")
    # Presence of any non-empty token material does not confer authority.
    has_token = False
    if isinstance(token, QuackTransportToken):
        has_token = bool(token.token_id)
    elif token is not None and str(token).strip():
        has_token = True
    if has_token:
        raise AuthorizationDenied(
            f"Quack token alone cannot authorize privileged lake call "
            f"{op.value!r}; independent owner-broker authorization is required"
        )
    raise AuthorizationDenied(
        f"missing owner-broker authorization for privileged lake call {op.value!r}; "
        "a Quack transport token is never sufficient"
    )


def assert_remote_authority_action_denied(
    action: str,
    *,
    target: str = "authority_catalog",
) -> None:
    """Fail closed for remote open/copy/replace/mount of authority files."""

    normalized = str(action or "").strip().lower().replace(" ", "_")
    if not normalized:
        raise RemoteAccessDenied("remote authority action is required")
    forbidden = FORBIDDEN_REMOTE_CATALOG_ACTIONS
    if normalized in forbidden or any(token in normalized for token in forbidden):
        raise RemoteAccessDenied(
            f"remote worker identity cannot {normalized} {target}; submit a "
            "typed request to the single fenced DuckDB + Quack catalog owner"
        )
    raise RemoteAccessDenied(
        f"remote worker identity cannot perform {normalized!r} against {target}"
    )


# ---------------------------------------------------------------------------
# Process birth / transport token
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProcessBirth:
    """Caller / process birth identity bound into every short-lived capability."""

    process_id: str
    boot_id: str
    started_at: str
    hostname: str = ""
    pid: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "process_id",
            _require_safe_token(self.process_id, field_name="process_id"),
        )
        object.__setattr__(
            self, "boot_id", _require_safe_token(self.boot_id, field_name="boot_id")
        )
        object.__setattr__(
            self,
            "started_at",
            _require_nonempty(self.started_at, field_name="started_at"),
        )
        if self.pid is not None:
            object.__setattr__(
                self, "pid", _require_positive_int(self.pid, field_name="pid")
            )
        object.__setattr__(self, "hostname", str(self.hostname or "").strip())

    def fingerprint(self) -> str:
        return _sha256_text(
            _canonical_json(
                {
                    "process_id": self.process_id,
                    "boot_id": self.boot_id,
                    "started_at": self.started_at,
                    "hostname": self.hostname,
                    "pid": self.pid,
                }
            )
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "process_id": self.process_id,
                "boot_id": self.boot_id,
                "started_at": self.started_at,
                "hostname": self.hostname,
                "pid": self.pid,
                "fingerprint": self.fingerprint(),
            }
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ProcessBirth":
        return cls(
            process_id=str(payload.get("process_id") or ""),
            boot_id=str(payload.get("boot_id") or ""),
            started_at=str(payload.get("started_at") or ""),
            hostname=str(payload.get("hostname") or ""),
            pid=payload.get("pid"),
        )


@dataclass(frozen=True, slots=True)
class QuackTransportToken:
    """Quack transport capability only — never operation authorization.

    Possession of this token permits authenticated transport to an endpoint
    under separate authorization callbacks; it does **not** authorize any
    privileged lake call.
    """

    token_id: str
    endpoint_id: str
    expires_at_unix: float
    _secret: str = field(repr=False, default="")

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "token_id", _require_safe_token(self.token_id, field_name="token_id")
        )
        object.__setattr__(
            self,
            "endpoint_id",
            _require_safe_token(self.endpoint_id, field_name="endpoint_id"),
        )
        if not isinstance(self.expires_at_unix, (int, float)) or isinstance(
            self.expires_at_unix, bool
        ):
            raise SecurityError("expires_at_unix must be a number")
        secret = str(self._secret or "")
        if not secret:
            raise SecurityError("Quack transport token secret must be non-empty")
        object.__setattr__(self, "_secret", secret)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"QuackTransportToken(token_id={self.token_id!r}, "
            f"endpoint_id={self.endpoint_id!r}, secret=***)"
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.__repr__()

    @property
    def is_transport_only(self) -> bool:
        return True

    @property
    def authorizes_privileged_calls(self) -> bool:
        return False

    def is_expired(self, *, now: float | None = None) -> bool:
        clock = time.time() if now is None else float(now)
        return clock >= float(self.expires_at_unix)

    def reveal_for_trusted_transport(self) -> str:
        """Return the raw secret for in-process trusted transport only."""

        return self._secret

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "token_id": self.token_id,
                "endpoint_id": self.endpoint_id,
                "expires_at_unix": self.expires_at_unix,
                "is_transport_only": True,
                "authorizes_privileged_calls": False,
                "secret": REDACTION_MARKER,
            }
        )


# ---------------------------------------------------------------------------
# Identity capabilities / policies
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IdentityEndpointCapabilities:
    """Least-privilege endpoint / OS / storage capabilities for one role."""

    role: LakeIdentityRole
    os_identity: str
    network_identity: str
    endpoint_access: bool
    object_read: bool
    object_write: bool
    object_delete: bool = False
    open_catalog_file: bool = False
    open_companion_registry: bool = False
    mount_authority_files: bool = False
    may_request_object_delete_iam: bool = False
    is_catalog_owner_process: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", _coerce_role(self.role))
        object.__setattr__(
            self,
            "os_identity",
            _require_safe_token(self.os_identity, field_name="os_identity"),
        )
        object.__setattr__(
            self,
            "network_identity",
            _require_safe_token(self.network_identity, field_name="network_identity"),
        )
        role = self.role
        if role is LakeIdentityRole.READER:
            if self.object_write or self.object_delete:
                raise SecurityError("reader must not write or delete objects")
            if self.open_catalog_file or self.open_companion_registry:
                raise SecurityError("reader must not open authority files")
            if self.mount_authority_files:
                raise SecurityError("reader must not mount authority files")
            if self.may_request_object_delete_iam or self.is_catalog_owner_process:
                raise SecurityError(
                    "reader cannot request object-delete IAM or own the catalog"
                )
        if role is LakeIdentityRole.WRITER:
            if self.object_delete:
                raise SecurityError("writer must not hold ambient object_delete")
            if self.open_catalog_file or self.open_companion_registry:
                raise SecurityError("writer must not open authority files")
            if self.mount_authority_files:
                raise SecurityError("writer must not mount authority files")
            if self.may_request_object_delete_iam or self.is_catalog_owner_process:
                raise SecurityError(
                    "writer cannot request object-delete IAM or own the catalog"
                )
        if role is LakeIdentityRole.MAINTAINER:
            if self.open_catalog_file or self.open_companion_registry:
                raise SecurityError(
                    "maintainer must not open authority files; only the catalog "
                    "owner process may open them"
                )
            if self.mount_authority_files:
                raise SecurityError("maintainer must not mount authority files")
            if self.object_delete:
                raise SecurityError(
                    "maintainer ambient object_delete must be false; delete "
                    "requires separate scoped object-delete IAM"
                )
            if not self.may_request_object_delete_iam:
                raise SecurityError(
                    "maintainer may request object-delete IAM for authorized "
                    "destructive maintenance"
                )
            if self.is_catalog_owner_process:
                raise SecurityError(
                    "maintainer is not the catalog owner process"
                )
        if role is LakeIdentityRole.CATALOG_OWNER:
            if not self.is_catalog_owner_process:
                raise SecurityError(
                    "catalog_owner identity must mark is_catalog_owner_process"
                )
            if not self.open_catalog_file:
                raise SecurityError(
                    "only the catalog owner process may open the catalog file"
                )
            if self.object_delete:
                raise SecurityError(
                    "catalog owner ambient object_delete must be false; "
                    "deletion still requires separate scoped object-delete IAM"
                )
            # Owner process may open companion registry for private control.
            if self.mount_authority_files:
                raise SecurityError(
                    "catalog owner must open authority files via DuckDB native "
                    "lock, not network mount"
                )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "role": self.role.value,
                "os_identity": self.os_identity,
                "network_identity": self.network_identity,
                "endpoint_access": self.endpoint_access,
                "object_read": self.object_read,
                "object_write": self.object_write,
                "object_delete": self.object_delete,
                "open_catalog_file": self.open_catalog_file,
                "open_companion_registry": self.open_companion_registry,
                "mount_authority_files": self.mount_authority_files,
                "may_request_object_delete_iam": self.may_request_object_delete_iam,
                "is_catalog_owner_process": self.is_catalog_owner_process,
            }
        )


def default_identity_capabilities(
    *,
    catalog_id: str,
) -> Mapping[LakeIdentityRole, IdentityEndpointCapabilities]:
    """Return distinct least-privilege defaults for all four lake roles."""

    safe = re.sub(r"[^A-Za-z0-9_]+", "_", catalog_id).strip("_").lower() or "catalog"
    return MappingProxyType(
        {
            LakeIdentityRole.READER: IdentityEndpointCapabilities(
                role=LakeIdentityRole.READER,
                os_identity=f"ducklake_{safe}_reader",
                network_identity=f"net_{safe}_reader",
                endpoint_access=True,
                object_read=True,
                object_write=False,
                object_delete=False,
                open_catalog_file=False,
                open_companion_registry=False,
                mount_authority_files=False,
                may_request_object_delete_iam=False,
                is_catalog_owner_process=False,
            ),
            LakeIdentityRole.WRITER: IdentityEndpointCapabilities(
                role=LakeIdentityRole.WRITER,
                os_identity=f"ducklake_{safe}_writer",
                network_identity=f"net_{safe}_writer",
                endpoint_access=True,
                object_read=True,
                object_write=True,
                object_delete=False,
                open_catalog_file=False,
                open_companion_registry=False,
                mount_authority_files=False,
                may_request_object_delete_iam=False,
                is_catalog_owner_process=False,
            ),
            LakeIdentityRole.MAINTAINER: IdentityEndpointCapabilities(
                role=LakeIdentityRole.MAINTAINER,
                os_identity=f"ducklake_{safe}_maintainer",
                network_identity=f"net_{safe}_maintainer",
                endpoint_access=True,
                object_read=True,
                object_write=True,
                object_delete=False,
                open_catalog_file=False,
                open_companion_registry=False,
                mount_authority_files=False,
                may_request_object_delete_iam=True,
                is_catalog_owner_process=False,
            ),
            LakeIdentityRole.CATALOG_OWNER: IdentityEndpointCapabilities(
                role=LakeIdentityRole.CATALOG_OWNER,
                os_identity=f"ducklake_{safe}_catalog_owner",
                network_identity=f"net_{safe}_catalog_owner",
                endpoint_access=True,
                object_read=True,
                object_write=True,
                object_delete=False,
                open_catalog_file=True,
                open_companion_registry=True,
                mount_authority_files=False,
                may_request_object_delete_iam=True,
                is_catalog_owner_process=True,
            ),
        }
    )


@dataclass(frozen=True, slots=True)
class TenantSchemaPrefix:
    """Tenant and schema prefix applied to lake namespaces."""

    tenant_id: str
    schema_prefix: str

    def __post_init__(self) -> None:
        tenant = str(self.tenant_id or "").strip().lower()
        if not tenant or not _TENANT_RE.match(tenant):
            raise SecurityError(f"invalid tenant_id {self.tenant_id!r}")
        prefix = str(self.schema_prefix or "").strip().lower()
        if not prefix or not _SCHEMA_PREFIX_RE.match(prefix):
            raise SecurityError(f"invalid schema_prefix {self.schema_prefix!r}")
        object.__setattr__(self, "tenant_id", tenant)
        object.__setattr__(self, "schema_prefix", prefix)

    def qualified_schema(self) -> str:
        return f"{self.tenant_id}__{self.schema_prefix}"

    def qualify_table(self, table: str) -> str:
        name = str(table or "").strip()
        if not name or not _SAFE_IDENT.match(name):
            raise SecurityError(f"invalid table name {table!r}")
        return f"{self.qualified_schema()}.{name}"

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "tenant_id": self.tenant_id,
                "schema_prefix": self.schema_prefix,
                "qualified_schema": self.qualified_schema(),
            }
        )


@dataclass(frozen=True, slots=True)
class EncryptedParquetPolicy:
    """Encrypted Parquet policy (keys remain external references only)."""

    required: bool = True
    algorithm: str = "aes-256-gcm"
    key_ref_id: str | None = None
    transit_tls_required: bool = True

    def __post_init__(self) -> None:
        algo = str(self.algorithm or "").strip().lower()
        if algo not in {"aes-256-gcm", "aes-256-cbc", "chacha20-poly1305"}:
            raise SecurityError(f"unsupported encryption algorithm {self.algorithm!r}")
        object.__setattr__(self, "algorithm", algo)
        if self.key_ref_id is not None:
            object.__setattr__(
                self,
                "key_ref_id",
                _require_safe_token(self.key_ref_id, field_name="key_ref_id"),
            )
        if self.required and not self.transit_tls_required:
            raise SecurityError(
                "encrypted Parquet policy requires transit TLS when encryption "
                "is required"
            )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "required": self.required,
                "algorithm": self.algorithm,
                "key_ref_id": self.key_ref_id,
                "transit_tls_required": self.transit_tls_required,
                "key_material_embedded": False,
            }
        )


def default_encrypted_parquet_policy(
    *,
    key_ref_id: str | None = None,
) -> EncryptedParquetPolicy:
    return EncryptedParquetPolicy(
        required=True,
        algorithm="aes-256-gcm",
        key_ref_id=key_ref_id,
        transit_tls_required=True,
    )


# ---------------------------------------------------------------------------
# Operation-scoped capabilities / object-delete IAM
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OperationScopedCapability:
    """Short-lived capability bound to exact operation + caller + generation.

    Raw secrets never appear in ``repr`` / ``str`` / public projections.
    """

    capability_id: str
    kind: CapabilityKind
    operation: PrivilegedOperation
    operation_id: str
    caller_id: str
    process_birth: ProcessBirth
    endpoint_id: str
    owner_generation: int
    resource: str
    nonce: str
    expires_at_unix: float
    issuer_id: str
    authorization_id: str
    _secret: str = field(repr=False, default="")
    used: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capability_id",
            _require_safe_token(self.capability_id, field_name="capability_id"),
        )
        object.__setattr__(self, "kind", _coerce_capability_kind(self.kind))
        object.__setattr__(self, "operation", _coerce_operation(self.operation))
        object.__setattr__(
            self,
            "operation_id",
            _require_safe_token(self.operation_id, field_name="operation_id"),
        )
        object.__setattr__(
            self, "caller_id", _require_safe_token(self.caller_id, field_name="caller_id")
        )
        if not isinstance(self.process_birth, ProcessBirth):
            if isinstance(self.process_birth, Mapping):
                object.__setattr__(
                    self, "process_birth", ProcessBirth.from_mapping(self.process_birth)
                )
            else:
                raise CapabilityError("process_birth is required")
        object.__setattr__(
            self,
            "endpoint_id",
            _require_safe_token(self.endpoint_id, field_name="endpoint_id"),
        )
        object.__setattr__(
            self,
            "owner_generation",
            _require_positive_int(self.owner_generation, field_name="owner_generation"),
        )
        object.__setattr__(
            self, "resource", _require_nonempty(self.resource, field_name="resource")
        )
        object.__setattr__(
            self, "nonce", _require_nonempty(self.nonce, field_name="nonce")
        )
        if not isinstance(self.expires_at_unix, (int, float)) or isinstance(
            self.expires_at_unix, bool
        ):
            raise CapabilityError("expires_at_unix must be a number")
        object.__setattr__(
            self, "issuer_id", _require_safe_token(self.issuer_id, field_name="issuer_id")
        )
        object.__setattr__(
            self,
            "authorization_id",
            _require_safe_token(self.authorization_id, field_name="authorization_id"),
        )
        secret = str(self._secret or "")
        if not secret:
            raise CapabilityError("capability secret must be non-empty")
        object.__setattr__(self, "_secret", secret)
        if self.issuer_id == self.caller_id:
            raise CapabilityError(
                "capability issuer must be distinct from the caller/worker"
            )

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"OperationScopedCapability(capability_id={self.capability_id!r}, "
            f"kind={self.kind.value!r}, operation={self.operation.value!r}, "
            f"secret=***)"
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.__repr__()

    def is_expired(self, *, now: float | None = None) -> bool:
        clock = time.time() if now is None else float(now)
        return clock >= float(self.expires_at_unix)

    def binding_digest(self) -> str:
        body = {
            "capability_id": self.capability_id,
            "kind": self.kind.value,
            "operation": self.operation.value,
            "operation_id": self.operation_id,
            "caller_id": self.caller_id,
            "process_birth": dict(self.process_birth.as_mapping()),
            "endpoint_id": self.endpoint_id,
            "owner_generation": self.owner_generation,
            "resource": self.resource,
            "nonce": self.nonce,
            "expires_at_unix": self.expires_at_unix,
            "issuer_id": self.issuer_id,
            "authorization_id": self.authorization_id,
        }
        return _sha256_text(_canonical_json(body))

    def reveal_for_trusted_use(self) -> str:
        return self._secret

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": OPERATION_CAPABILITY_SCHEMA,
                "capability_id": self.capability_id,
                "kind": self.kind.value,
                "operation": self.operation.value,
                "operation_id": self.operation_id,
                "caller_id": self.caller_id,
                "process_birth": dict(self.process_birth.as_mapping()),
                "endpoint_id": self.endpoint_id,
                "owner_generation": self.owner_generation,
                "resource": self.resource,
                "nonce": self.nonce,
                "expires_at_unix": self.expires_at_unix,
                "issuer_id": self.issuer_id,
                "authorization_id": self.authorization_id,
                "used": self.used,
                "binding_digest": self.binding_digest(),
                "secret": REDACTION_MARKER,
            }
        )

    def mark_used(self) -> "OperationScopedCapability":
        if self.used:
            raise CapabilityError(
                f"capability {self.capability_id!r} already used; short-lived "
                "capabilities are one-use"
            )
        return OperationScopedCapability(
            capability_id=self.capability_id,
            kind=self.kind,
            operation=self.operation,
            operation_id=self.operation_id,
            caller_id=self.caller_id,
            process_birth=self.process_birth,
            endpoint_id=self.endpoint_id,
            owner_generation=self.owner_generation,
            resource=self.resource,
            nonce=self.nonce,
            expires_at_unix=self.expires_at_unix,
            issuer_id=self.issuer_id,
            authorization_id=self.authorization_id,
            _secret=self._secret,
            used=True,
        )


@dataclass(frozen=True, slots=True)
class ObjectDeleteIamGrant:
    """Separate scoped object-delete IAM (never ambient on readers/writers)."""

    grant_id: str
    operation_id: str
    caller_id: str
    process_birth: ProcessBirth
    owner_generation: int
    resource: str
    nonce: str
    expires_at_unix: float
    authorization_id: str
    issuer_id: str
    scope_prefix: str
    _secret: str = field(repr=False, default="")
    used: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "grant_id", _require_safe_token(self.grant_id, field_name="grant_id")
        )
        object.__setattr__(
            self,
            "operation_id",
            _require_safe_token(self.operation_id, field_name="operation_id"),
        )
        object.__setattr__(
            self, "caller_id", _require_safe_token(self.caller_id, field_name="caller_id")
        )
        if not isinstance(self.process_birth, ProcessBirth):
            if isinstance(self.process_birth, Mapping):
                object.__setattr__(
                    self, "process_birth", ProcessBirth.from_mapping(self.process_birth)
                )
            else:
                raise CapabilityError("process_birth is required for object-delete IAM")
        object.__setattr__(
            self,
            "owner_generation",
            _require_positive_int(self.owner_generation, field_name="owner_generation"),
        )
        object.__setattr__(
            self, "resource", _require_nonempty(self.resource, field_name="resource")
        )
        object.__setattr__(
            self, "nonce", _require_nonempty(self.nonce, field_name="nonce")
        )
        object.__setattr__(
            self,
            "authorization_id",
            _require_safe_token(self.authorization_id, field_name="authorization_id"),
        )
        object.__setattr__(
            self, "issuer_id", _require_safe_token(self.issuer_id, field_name="issuer_id")
        )
        object.__setattr__(
            self,
            "scope_prefix",
            _require_nonempty(self.scope_prefix, field_name="scope_prefix"),
        )
        secret = str(self._secret or "")
        if not secret:
            raise CapabilityError("object-delete IAM secret must be non-empty")
        object.__setattr__(self, "_secret", secret)
        if self.issuer_id == self.caller_id:
            raise CapabilityError(
                "object-delete IAM must be issued by a credential issuer "
                "distinct from the caller"
            )

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"ObjectDeleteIamGrant(grant_id={self.grant_id!r}, "
            f"operation_id={self.operation_id!r}, secret=***)"
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.__repr__()

    def is_expired(self, *, now: float | None = None) -> bool:
        clock = time.time() if now is None else float(now)
        return clock >= float(self.expires_at_unix)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": OBJECT_DELETE_IAM_SCHEMA,
                "grant_id": self.grant_id,
                "operation_id": self.operation_id,
                "caller_id": self.caller_id,
                "process_birth": dict(self.process_birth.as_mapping()),
                "owner_generation": self.owner_generation,
                "resource": self.resource,
                "nonce": self.nonce,
                "expires_at_unix": self.expires_at_unix,
                "authorization_id": self.authorization_id,
                "issuer_id": self.issuer_id,
                "scope_prefix": self.scope_prefix,
                "used": self.used,
                "secret": REDACTION_MARKER,
                "ambient": False,
            }
        )


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Endpoint and owner-generation audit event (no secrets)."""

    event_id: str
    event_type: str
    endpoint_id: str
    owner_generation: int
    operation_id: str
    caller_id: str
    decision: str
    resource: str
    timestamp_unix: float
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "event_id", _require_safe_token(self.event_id, field_name="event_id")
        )
        object.__setattr__(
            self,
            "event_type",
            _require_safe_token(self.event_type, field_name="event_type"),
        )
        object.__setattr__(
            self,
            "endpoint_id",
            _require_safe_token(self.endpoint_id, field_name="endpoint_id"),
        )
        object.__setattr__(
            self,
            "owner_generation",
            _require_positive_int(self.owner_generation, field_name="owner_generation"),
        )
        object.__setattr__(
            self,
            "operation_id",
            _require_safe_token(self.operation_id, field_name="operation_id"),
        )
        object.__setattr__(
            self, "caller_id", _require_safe_token(self.caller_id, field_name="caller_id")
        )
        decision = str(self.decision or "").strip().lower()
        if decision not in {"allow", "deny", "issue", "consume", "audit"}:
            raise AuditError(f"invalid audit decision {self.decision!r}")
        object.__setattr__(self, "decision", decision)
        object.__setattr__(
            self, "resource", _require_nonempty(self.resource, field_name="resource")
        )
        if not isinstance(self.timestamp_unix, (int, float)):
            raise AuditError("timestamp_unix must be a number")
        details = scrub_sensitive_projection(dict(self.details or {}))
        object.__setattr__(self, "details", MappingProxyType(dict(details)))

    def as_mapping(self) -> Mapping[str, Any]:
        payload = {
            "schema": AUDIT_EVENT_SCHEMA,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "endpoint_id": self.endpoint_id,
            "owner_generation": self.owner_generation,
            "operation_id": self.operation_id,
            "caller_id": self.caller_id,
            "decision": self.decision,
            "resource": self.resource,
            "timestamp_unix": self.timestamp_unix,
            "details": dict(self.details),
        }
        return MappingProxyType(scrub_sensitive_projection(payload))


# ---------------------------------------------------------------------------
# Credential issuer (distinct from broker and workers)
# ---------------------------------------------------------------------------


class CredentialIssuer:
    """Issues short-lived operation-scoped capabilities after broker auth.

    The issuer is identity-distinct from the trusted owner broker and from
    workers. It never authorizes operations itself.
    """

    def __init__(
        self,
        *,
        issuer_id: str,
        broker_id: str,
        clock: Callable[[], float] | None = None,
        secret_factory: Callable[[], str] | None = None,
    ) -> None:
        self.issuer_id = _require_safe_token(issuer_id, field_name="issuer_id")
        self.broker_id = _require_safe_token(broker_id, field_name="broker_id")
        if self.issuer_id == self.broker_id:
            raise SecurityError(
                "credential issuer must be distinct from the trusted owner broker"
            )
        self._clock = clock or time.time
        self._secret_factory = secret_factory or (
            lambda: secrets.token_hex(32)
        )
        self._lock = threading.RLock()
        self._issued: dict[str, OperationScopedCapability | ObjectDeleteIamGrant] = {}
        self._used: set[str] = set()

    def issue_capability(
        self,
        *,
        authorization: Mapping[str, Any],
        kind: CapabilityKind | str,
        process_birth: ProcessBirth,
        ttl_seconds: int = _DEFAULT_CAPABILITY_TTL_SECONDS,
        capability_id: str | None = None,
    ) -> OperationScopedCapability:
        """Issue a short-lived capability bound to a broker authorization."""

        if not authorization.get("authorized"):
            raise AuthorizationDenied(
                "credential issuer refuses capability without broker authorization"
            )
        if str(authorization.get("authorized_by") or "") != "trusted_owner_broker":
            raise AuthorizationDenied(
                "capability issuance requires trusted_owner_broker authorization"
            )
        broker_id = str(authorization.get("broker_id") or "")
        if broker_id != self.broker_id:
            raise AuthorizationDenied(
                f"authorization broker_id {broker_id!r} does not match issuer "
                f"binding {self.broker_id!r}"
            )
        if (
            not isinstance(ttl_seconds, int)
            or isinstance(ttl_seconds, bool)
            or ttl_seconds < _MIN_CAPABILITY_TTL_SECONDS
            or ttl_seconds > _MAX_CAPABILITY_TTL_SECONDS
        ):
            raise CapabilityError("ttl_seconds out of range")

        caller_id = _require_safe_token(
            authorization.get("caller_id"), field_name="caller_id"
        )
        if caller_id in {self.issuer_id, self.broker_id}:
            raise CapabilityError(
                "capabilities must be issued to workers distinct from broker "
                "and credential issuer"
            )
        operation = _coerce_operation(str(authorization.get("operation") or ""))
        now = float(self._clock())
        cap = OperationScopedCapability(
            capability_id=capability_id
            or f"cap-{uuid.uuid4().hex}",
            kind=_coerce_capability_kind(kind),
            operation=operation,
            operation_id=_require_safe_token(
                authorization.get("operation_id"), field_name="operation_id"
            ),
            caller_id=caller_id,
            process_birth=process_birth,
            endpoint_id=_require_safe_token(
                authorization.get("endpoint_id"), field_name="endpoint_id"
            ),
            owner_generation=_require_positive_int(
                authorization.get("owner_generation"), field_name="owner_generation"
            ),
            resource=_require_nonempty(
                authorization.get("resource"), field_name="resource"
            ),
            nonce=secrets.token_hex(16),
            expires_at_unix=now + float(ttl_seconds),
            issuer_id=self.issuer_id,
            authorization_id=_require_safe_token(
                authorization.get("authorization_id"), field_name="authorization_id"
            ),
            _secret=str(self._secret_factory()),
        )
        # Enforce process-birth binding against the authorization.
        auth_birth = authorization.get("process_birth")
        if isinstance(auth_birth, ProcessBirth):
            expected_fp = auth_birth.fingerprint()
        elif isinstance(auth_birth, Mapping):
            expected_fp = ProcessBirth.from_mapping(auth_birth).fingerprint()
        else:
            raise CapabilityError(
                "authorization must bind process_birth for capability issuance"
            )
        if process_birth.fingerprint() != expected_fp:
            raise CapabilityError(
                "process_birth mismatch between authorization and capability"
            )
        with self._lock:
            self._issued[cap.capability_id] = cap
        return cap

    def issue_object_delete_iam(
        self,
        *,
        authorization: Mapping[str, Any],
        process_birth: ProcessBirth,
        scope_prefix: str,
        ttl_seconds: int = _DEFAULT_DELETE_IAM_TTL_SECONDS,
        grant_id: str | None = None,
    ) -> ObjectDeleteIamGrant:
        """Issue separate scoped object-delete IAM after delete authorization."""

        if not authorization.get("authorized"):
            raise AuthorizationDenied(
                "object-delete IAM requires independent broker authorization"
            )
        operation = _coerce_operation(str(authorization.get("operation") or ""))
        if operation is not PrivilegedOperation.DELETE:
            raise AuthorizationDenied(
                "object-delete IAM is issued only for independently authorized "
                f"delete operations; got {operation.value!r}"
            )
        if not authorization.get("object_delete_iam_approved"):
            raise AuthorizationDenied(
                "broker must explicitly approve object-delete IAM for this call"
            )
        role = str(authorization.get("caller_role") or "").strip().lower()
        if role in {LakeIdentityRole.READER.value, LakeIdentityRole.WRITER.value}:
            raise AuthorizationDenied(
                "ordinary readers and writers cannot obtain object-delete IAM"
            )
        caller_id = _require_safe_token(
            authorization.get("caller_id"), field_name="caller_id"
        )
        if caller_id in {self.issuer_id, self.broker_id}:
            raise CapabilityError(
                "object-delete IAM caller must be distinct from broker and issuer"
            )
        now = float(self._clock())
        grant = ObjectDeleteIamGrant(
            grant_id=grant_id or f"odel-{uuid.uuid4().hex}",
            operation_id=_require_safe_token(
                authorization.get("operation_id"), field_name="operation_id"
            ),
            caller_id=caller_id,
            process_birth=process_birth,
            owner_generation=_require_positive_int(
                authorization.get("owner_generation"), field_name="owner_generation"
            ),
            resource=_require_nonempty(
                authorization.get("resource"), field_name="resource"
            ),
            nonce=secrets.token_hex(16),
            expires_at_unix=now + float(ttl_seconds),
            authorization_id=_require_safe_token(
                authorization.get("authorization_id"), field_name="authorization_id"
            ),
            issuer_id=self.issuer_id,
            scope_prefix=_require_nonempty(scope_prefix, field_name="scope_prefix"),
            _secret=str(self._secret_factory()),
        )
        with self._lock:
            self._issued[grant.grant_id] = grant
        return grant

    def mark_consumed(self, capability_id: str) -> None:
        with self._lock:
            self._used.add(capability_id)

    def was_consumed(self, capability_id: str) -> bool:
        with self._lock:
            return capability_id in self._used


# ---------------------------------------------------------------------------
# Trusted owner broker
# ---------------------------------------------------------------------------


class TrustedOwnerBroker:
    """Independently authorizes every privileged lake call.

    Distinct from workers and from the credential issuer. DuckLake is never
    consulted for roles; a Quack transport token never satisfies authorization.
    """

    def __init__(
        self,
        *,
        broker_id: str,
        catalog_id: str,
        endpoint_id: str,
        owner_generation: int,
        identities: Mapping[LakeIdentityRole, IdentityEndpointCapabilities] | None = None,
        tenant_schema: TenantSchemaPrefix | None = None,
        encryption: EncryptedParquetPolicy | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.broker_id = _require_safe_token(broker_id, field_name="broker_id")
        self.catalog_id = _require_safe_token(catalog_id, field_name="catalog_id")
        self.endpoint_id = _require_safe_token(endpoint_id, field_name="endpoint_id")
        self.owner_generation = _require_positive_int(
            owner_generation, field_name="owner_generation"
        )
        self.identities = MappingProxyType(
            dict(identities or default_identity_capabilities(catalog_id=catalog_id))
        )
        self.tenant_schema = tenant_schema or TenantSchemaPrefix(
            tenant_id="default", schema_prefix="lake"
        )
        self.encryption = encryption or default_encrypted_parquet_policy(
            key_ref_id=f"enc-ref-{catalog_id}"
        )
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._authorizations: dict[str, Mapping[str, Any]] = {}
        self._audit_log: list[AuditEvent] = []
        # Prove ducklake has no role layer at construction.
        assert_ducklake_has_no_native_role_layer()

    def identity(self, role: LakeIdentityRole | str) -> IdentityEndpointCapabilities:
        resolved = _coerce_role(role)
        try:
            return self.identities[resolved]
        except KeyError as exc:
            raise SecurityError(f"no identity profile for role {resolved.value}") from exc

    def authorize(
        self,
        *,
        operation: PrivilegedOperation | str,
        operation_id: str,
        caller_id: str,
        caller_role: LakeIdentityRole | str,
        process_birth: ProcessBirth,
        resource: str,
        quack_token: QuackTransportToken | str | None = None,
        owner_generation: int | None = None,
        approve_object_delete_iam: bool = False,
    ) -> Mapping[str, Any]:
        """Independently authorize a privileged call (Quack token ignored)."""

        op = _coerce_operation(operation)
        role = _coerce_role(caller_role)
        caller = _require_safe_token(caller_id, field_name="caller_id")
        if caller == self.broker_id:
            raise AuthorizationDenied(
                "broker cannot authorize itself as caller; keep broker and "
                "worker identities distinct"
            )
        gen = (
            self.owner_generation
            if owner_generation is None
            else _require_positive_int(owner_generation, field_name="owner_generation")
        )
        if gen != self.owner_generation:
            raise AuthorizationDenied(
                f"endpoint owner generation mismatch: broker {self.owner_generation}, "
                f"caller {gen}"
            )
        if not isinstance(process_birth, ProcessBirth):
            raise AuthorizationDenied("process_birth is required")
        resource_text = _require_nonempty(resource, field_name="resource")
        op_id = _require_safe_token(operation_id, field_name="operation_id")

        # Quack token presence is irrelevant and never sufficient.
        # We deliberately do not treat a valid token as authorization evidence.
        _ = quack_token

        identity = self.identity(role)
        self._assert_role_may_perform(role, identity, op)

        object_delete_iam_approved = False
        if op is PrivilegedOperation.DELETE:
            if not identity.may_request_object_delete_iam:
                raise AuthorizationDenied(
                    f"role {role.value} cannot obtain object-delete IAM; only "
                    "independently authorized deletion by maintainer/catalog "
                    "owner receives separate scoped object-delete IAM"
                )
            if not approve_object_delete_iam:
                raise AuthorizationDenied(
                    "delete authorization requires explicit object-delete IAM approval"
                )
            object_delete_iam_approved = True

        auth_id = f"auth-{uuid.uuid4().hex}"
        now = float(self._clock())
        decision = MappingProxyType(
            {
                "schema": DUCKLAKE_SECURITY_SCHEMA,
                "authorized": True,
                "authorization_id": auth_id,
                "authorized_by": "trusted_owner_broker",
                "broker_id": self.broker_id,
                "catalog_id": self.catalog_id,
                "endpoint_id": self.endpoint_id,
                "owner_generation": gen,
                "operation": op.value,
                "operation_id": op_id,
                "caller_id": caller,
                "caller_role": role.value,
                "process_birth": dict(process_birth.as_mapping()),
                "resource": resource_text,
                "nonce": secrets.token_hex(16),
                "expires_at_unix": now + float(_DEFAULT_CAPABILITY_TTL_SECONDS),
                "ducklake_native_role_layer": False,
                "quack_token_sufficient": False,
                "object_delete_iam_approved": object_delete_iam_approved,
                "tenant_schema": dict(self.tenant_schema.as_mapping()),
                "encryption_policy": dict(self.encryption.as_mapping()),
                "issued_at_unix": now,
            }
        )
        scrubbed = scrub_sensitive_projection(dict(decision))
        with self._lock:
            self._authorizations[auth_id] = MappingProxyType(scrubbed)
            self._record_audit_locked(
                event_type="privileged_authorize",
                operation_id=op_id,
                caller_id=caller,
                decision="allow",
                resource=resource_text,
                details={
                    "operation": op.value,
                    "caller_role": role.value,
                    "authorization_id": auth_id,
                },
            )
        return MappingProxyType(scrubbed)

    def deny_with_quack_token_only(
        self,
        *,
        operation: PrivilegedOperation | str,
        quack_token: QuackTransportToken | str | None,
    ) -> None:
        """Explicit acceptance helper: Quack token alone always denies."""

        assert_quack_token_cannot_authorize(quack_token, operation=operation)

    def assert_remote_worker_denied(
        self,
        action: str,
        *,
        target: str = "authority_catalog",
    ) -> None:
        assert_remote_authority_action_denied(action, target=target)

    def audit_events(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(self._audit_log)

    def _assert_role_may_perform(
        self,
        role: LakeIdentityRole,
        identity: IdentityEndpointCapabilities,
        op: PrivilegedOperation,
    ) -> None:
        if not identity.endpoint_access and op is not PrivilegedOperation.ATTACH:
            raise AuthorizationDenied(f"role {role.value} lacks endpoint access")
        if op is PrivilegedOperation.READ:
            if not identity.object_read and role is not LakeIdentityRole.CATALOG_OWNER:
                raise AuthorizationDenied(f"role {role.value} cannot read")
            return
        if op is PrivilegedOperation.WRITE:
            if role is LakeIdentityRole.READER:
                raise AuthorizationDenied("reader cannot write")
            if not identity.object_write and role is not LakeIdentityRole.CATALOG_OWNER:
                raise AuthorizationDenied(f"role {role.value} cannot write")
            return
        if op in {
            PrivilegedOperation.MAINTAIN,
            PrivilegedOperation.EXPIRE,
            PrivilegedOperation.COMPACT,
            PrivilegedOperation.ORPHAN_CLEANUP,
        }:
            if role not in {
                LakeIdentityRole.MAINTAINER,
                LakeIdentityRole.CATALOG_OWNER,
            }:
                raise AuthorizationDenied(
                    f"maintenance requires maintainer or catalog_owner; got {role.value}"
                )
            return
        if op is PrivilegedOperation.DELETE:
            if role not in {
                LakeIdentityRole.MAINTAINER,
                LakeIdentityRole.CATALOG_OWNER,
            }:
                raise AuthorizationDenied(
                    "delete requires maintainer or catalog_owner identity"
                )
            return
        if op is PrivilegedOperation.ATTACH:
            if not identity.is_catalog_owner_process:
                raise AuthorizationDenied(
                    "only the catalog owner process may attach the authority catalog"
                )
            return
        if op in {
            PrivilegedOperation.MIGRATE,
            PrivilegedOperation.BOOTSTRAP,
        }:
            if role is not LakeIdentityRole.CATALOG_OWNER:
                raise AuthorizationDenied(
                    f"{op.value} requires catalog_owner identity"
                )
            return
        if op is PrivilegedOperation.SNAPSHOT:
            return

    def _record_audit_locked(
        self,
        *,
        event_type: str,
        operation_id: str,
        caller_id: str,
        decision: str,
        resource: str,
        details: Mapping[str, Any],
    ) -> None:
        event = AuditEvent(
            event_id=f"aud-{uuid.uuid4().hex}",
            event_type=event_type,
            endpoint_id=self.endpoint_id,
            owner_generation=self.owner_generation,
            operation_id=operation_id,
            caller_id=caller_id,
            decision=decision,
            resource=resource,
            timestamp_unix=float(self._clock()),
            details=details,
        )
        self._audit_log.append(event)


# ---------------------------------------------------------------------------
# Boundary facade
# ---------------------------------------------------------------------------


class DuckLakeSecurityBoundary:
    """Composite boundary: broker + distinct credential issuer + policies."""

    def __init__(
        self,
        *,
        broker_id: str = "owner-broker-1",
        issuer_id: str = "credential-issuer-1",
        catalog_id: str = "catalog-a",
        endpoint_id: str = "quack-endpoint-a",
        owner_generation: int = 1,
        tenant_id: str = "default",
        schema_prefix: str = "lake",
        clock: Callable[[], float] | None = None,
    ) -> None:
        if broker_id == issuer_id:
            raise SecurityError(
                "trusted owner broker and credential issuer must be distinct"
            )
        self.broker = TrustedOwnerBroker(
            broker_id=broker_id,
            catalog_id=catalog_id,
            endpoint_id=endpoint_id,
            owner_generation=owner_generation,
            tenant_schema=TenantSchemaPrefix(
                tenant_id=tenant_id, schema_prefix=schema_prefix
            ),
            clock=clock,
        )
        self.issuer = CredentialIssuer(
            issuer_id=issuer_id,
            broker_id=broker_id,
            clock=clock,
        )
        self.catalog_id = catalog_id
        self.endpoint_id = endpoint_id

    def authorize_and_issue(
        self,
        *,
        operation: PrivilegedOperation | str,
        operation_id: str,
        caller_id: str,
        caller_role: LakeIdentityRole | str,
        process_birth: ProcessBirth,
        resource: str,
        capability_kind: CapabilityKind | str = CapabilityKind.QUACK_TRANSPORT,
        quack_token: QuackTransportToken | str | None = None,
        approve_object_delete_iam: bool = False,
        delete_scope_prefix: str | None = None,
        ttl_seconds: int = _DEFAULT_CAPABILITY_TTL_SECONDS,
    ) -> Mapping[str, Any]:
        """Authorize via broker, then issue capability via distinct issuer."""

        auth = self.broker.authorize(
            operation=operation,
            operation_id=operation_id,
            caller_id=caller_id,
            caller_role=caller_role,
            process_birth=process_birth,
            resource=resource,
            quack_token=quack_token,
            approve_object_delete_iam=approve_object_delete_iam,
        )
        cap = self.issuer.issue_capability(
            authorization=auth,
            kind=capability_kind,
            process_birth=process_birth,
            ttl_seconds=ttl_seconds,
        )
        result: dict[str, Any] = {
            "authorization": dict(auth),
            "capability": dict(cap.as_mapping()),
        }
        if approve_object_delete_iam:
            grant = self.issuer.issue_object_delete_iam(
                authorization=auth,
                process_birth=process_birth,
                scope_prefix=delete_scope_prefix
                or f"{self.catalog_id}/owned/",
                ttl_seconds=min(ttl_seconds, _DEFAULT_DELETE_IAM_TTL_SECONDS),
            )
            result["object_delete_iam"] = dict(grant.as_mapping())
        return MappingProxyType(scrub_sensitive_projection(result))

    def proof_summary(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": DUCKLAKE_SECURITY_SCHEMA,
                "implementation_generation": _IMPLEMENTATION_GENERATION,
                "ducklake_native_role_layer": DUCKLAKE_HAS_NATIVE_ROLE_LAYER,
                "quack_token_is_transport_only": QUACK_TOKEN_IS_TRANSPORT_ONLY,
                "broker_id": self.broker.broker_id,
                "issuer_id": self.issuer.issuer_id,
                "broker_distinct_from_issuer": (
                    self.broker.broker_id != self.issuer.issuer_id
                ),
                "identities": {
                    role.value: dict(cap.as_mapping())
                    for role, cap in self.broker.identities.items()
                },
                "tenant_schema": dict(self.broker.tenant_schema.as_mapping()),
                "encryption_policy": dict(self.broker.encryption.as_mapping()),
            }
        )


# ---------------------------------------------------------------------------
# Sensitive surface scrubbing
# ---------------------------------------------------------------------------


def is_sensitive_key(key: str) -> bool:
    text = str(key or "").strip().lower()
    if not text:
        return False
    if text in SENSITIVE_LOG_KEYS:
        return True
    for marker in (
        "token",
        "secret",
        "password",
        "credential",
        "encryption_key",
        "private_key",
        "api_key",
        "signing_key",
        "file_key",
    ):
        if marker in text:
            return True
    return False


def is_sensitive_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    upper = text.upper()
    if "BEGIN PRIVATE KEY" in upper or "BEGIN RSA PRIVATE KEY" in upper:
        return True
    if "BEGIN SECRET" in upper:
        return True
    # High-entropy hex/base64 blobs that look like keys/tokens.
    if len(text) >= 32 and re.fullmatch(r"[0-9a-fA-F]+", text):
        return True
    if len(text) >= 40 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", text):
        return True
    return False


def scrub_sensitive_projection(
    projection: Any,
    *,
    _path: str = "$",
) -> Any:
    """Recursively redact credentials and encryption keys from projections."""

    if isinstance(projection, Mapping):
        out: dict[str, Any] = {}
        for key, value in projection.items():
            key_text = str(key)
            child = f"{_path}.{key_text}"
            if is_sensitive_key(key_text):
                # Preserve non-secret flag/counter values on sensitive-looking
                # key names (e.g. quack_token_sufficient=False).
                if isinstance(value, bool) or value is None:
                    out[key_text] = value
                elif isinstance(value, (int, float)) and not isinstance(value, bool):
                    out[key_text] = value
                elif value in ("", {}, [], (), REDACTION_MARKER, "***"):
                    out[key_text] = value if value != "" else REDACTION_MARKER
                elif isinstance(value, Mapping) and set(value.keys()) <= {
                    "ref_id",
                    "purpose",
                    "provider",
                    "version",
                    "key_ref_id",
                }:
                    out[key_text] = scrub_sensitive_projection(value, _path=child)
                else:
                    out[key_text] = REDACTION_MARKER
                continue
            out[key_text] = scrub_sensitive_projection(value, _path=child)
        return out
    if isinstance(projection, list):
        return [
            scrub_sensitive_projection(item, _path=f"{_path}[{idx}]")
            for idx, item in enumerate(projection)
        ]
    if isinstance(projection, tuple):
        return tuple(
            scrub_sensitive_projection(item, _path=f"{_path}[{idx}]")
            for idx, item in enumerate(projection)
        )
    if isinstance(projection, str) and is_sensitive_value(projection):
        # Only scrub free-floating secrets; digests and ids stay.
        if projection.startswith("sha256:"):
            return projection
        if _SAFE_TOKEN.match(projection) and len(projection) < 80:
            # Short identifiers are fine.
            return projection
        return REDACTION_MARKER
    return projection


def redact_for_log(payload: Any) -> Any:
    return scrub_sensitive_projection(payload)


def redact_for_export(payload: Any) -> Any:
    return scrub_sensitive_projection(payload)


def redact_for_receipt(payload: Any) -> Any:
    return scrub_sensitive_projection(payload)


def redact_for_agent_quack_response(payload: Any) -> Any:
    """Agent-visible Quack responses must never carry keys or credentials."""

    return scrub_sensitive_projection(payload)


def _assert_no_sensitive_material(payload: Any, *, surface: str) -> None:
    """Raise if residual secret-looking material remains after scrubbing."""

    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if is_sensitive_key(str(key)) and value not in {
                None,
                "",
                REDACTION_MARKER,
                "***",
                "[redacted]",
                "REDACTED",
            }:
                if isinstance(value, Mapping) and set(value.keys()) <= {
                    "ref_id",
                    "purpose",
                    "provider",
                    "version",
                    "key_ref_id",
                }:
                    _assert_no_sensitive_material(value, surface=surface)
                    continue
                if value is False or value is True:
                    continue
                raise CredentialLeakError(
                    f"{surface} must not expose sensitive key {key!r}"
                )
            _assert_no_sensitive_material(value, surface=surface)
        return
    if isinstance(payload, (list, tuple)):
        for item in payload:
            _assert_no_sensitive_material(item, surface=surface)
        return
    if isinstance(payload, str):
        upper = payload.upper()
        if "BEGIN PRIVATE KEY" in upper or "BEGIN SECRET" in upper:
            raise CredentialLeakError(
                f"{surface} embeds PEM/secret material"
            )
