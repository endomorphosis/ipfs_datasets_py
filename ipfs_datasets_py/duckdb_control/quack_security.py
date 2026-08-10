"""Quack threat model and guarded server launcher (DQK-049).

Two explicit, non-inheriting server profiles:

* **Publication gateway** — sanitized, loopback-bound surface for agent traffic.
  Per-operation credentials, restricted OS identity, external access off,
  query authorization, audit, and a supported TLS reverse proxy for remote use.
  Cannot reach authority catalog files, object endpoints, or secret material.

* **Catalog owner** — internal DuckLake catalog manager. Deny-by-default.
  Pre-loads only pinned DuckLake / Quack / object-store extensions, restricts
  local paths and filesystems to the exact catalog file, permits egress only
  to the shard's exact object endpoint or TLS proxy, and installs non-default
  fresh-connection authentication plus exact full-SQL authorization callbacks.

Neither profile inherits ambient filesystem, extension, secret, or network
reachability. Default authentication and authorization are never permissive
for agent traffic. Tokens and full SQL text are treated as sensitive.

Importing this module is inert: it never imports ``duckdb``, never opens
sockets or files, and never installs extensions. Real process launch is only
materialized through an explicit :class:`GuardedQuackServerLauncher` call
(or injected runner under test).
"""

from __future__ import annotations

import hashlib
import re
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Final,
    Iterable,
    Mapping,
    Protocol,
    Sequence,
)

from ipfs_datasets_py.duckdb_control.capabilities import (
    PINNED_QUACK_EXTENSION_BUILD,
    PINNED_QUACK_EXTENSION_NAME,
    REQUIRED_DUCKDB_VERSION_TEXT,
)
from ipfs_datasets_py.duckdb_control.contracts import (
    canonical_json_bytes,
    content_identity,
)

__all__ = [
    "QUACK_SECURITY_SCHEMA",
    "QUACK_THREAT_MODEL_SCHEMA",
    "QUACK_SERVER_LAUNCH_SCHEMA",
    "PINNED_DUCKLAKE_EXTENSION_NAME",
    "PINNED_DUCKLAKE_EXTENSION_BUILD",
    "PINNED_OBJECT_ADAPTER_EXTENSION_NAME",
    "PINNED_OBJECT_ADAPTER_EXTENSION_BUILD",
    "CATALOG_OWNER_PINNED_EXTENSIONS",
    "PUBLICATION_GATEWAY_PINNED_EXTENSIONS",
    "LOOPBACK_HOSTS",
    "DEFAULT_QUACK_PORT",
    "DEFAULT_CAPABILITY_TTL_MS",
    "SENSITIVE_FIELD_NAMES",
    "AuthenticationMode",
    "AuthorizationMode",
    "EgressTargetKind",
    "QuackServerProfile",
    "QuackSecurityError",
    "AuthenticationDenied",
    "AuthorizationDenied",
    "PlaintextExposureRejected",
    "PolicyViolation",
    "CapabilityExpired",
    "CapabilityAlreadyConsumed",
    "CapabilityNotFound",
    "ThreatActor",
    "ThreatAsset",
    "ThreatControl",
    "ThreatModelEntry",
    "QuackThreatModel",
    "OsIdentityPolicy",
    "BindPolicy",
    "TlsProxyPolicy",
    "ExtensionPolicy",
    "LocalPathPolicy",
    "FilesystemPolicy",
    "EgressEndpoint",
    "EgressPolicy",
    "ExternalAccessPolicy",
    "AuditPolicy",
    "SensitiveSurfacePolicy",
    "QuackSecurityProfileConfig",
    "OperationCapability",
    "OneUseCapabilityStore",
    "AuthenticatedSession",
    "FreshConnectionAuthenticator",
    "ExactFullSqlAuthorizer",
    "DefaultDenyAuthenticator",
    "DefaultDenyAuthorizer",
    "GuardedServerPlan",
    "GuardedQuackServerLauncher",
    "default_threat_model",
    "publication_gateway_profile",
    "catalog_owner_profile",
    "build_security_profile",
    "assert_remote_not_plaintext",
    "is_loopback_host",
    "profiles_are_isolated",
    "redact_sensitive",
    "redact_sql",
    "redact_token",
    "sql_identity",
    "capability_fingerprint",
]


# ---------------------------------------------------------------------------
# Schema pins / constants
# ---------------------------------------------------------------------------

QUACK_SECURITY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-quack-security@1"
)
QUACK_THREAT_MODEL_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-quack-threat-model@1"
)
QUACK_SERVER_LAUNCH_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-quack-server-launch@1"
)

_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-049-lane3-attempt1-20260810"
)

# Pinned catalog-owner extension identities (must be explicit-load only).
PINNED_DUCKLAKE_EXTENSION_NAME: Final[str] = "ducklake"
PINNED_DUCKLAKE_EXTENSION_BUILD: Final[str] = "ducklake@1.0.0+pinned"
PINNED_OBJECT_ADAPTER_EXTENSION_NAME: Final[str] = "httpfs"
PINNED_OBJECT_ADAPTER_EXTENSION_BUILD: Final[str] = "httpfs@1.5.5+core"

CATALOG_OWNER_PINNED_EXTENSIONS: Final[tuple[str, ...]] = (
    PINNED_DUCKLAKE_EXTENSION_NAME,
    PINNED_QUACK_EXTENSION_NAME,
    PINNED_OBJECT_ADAPTER_EXTENSION_NAME,
)
PUBLICATION_GATEWAY_PINNED_EXTENSIONS: Final[tuple[str, ...]] = ()

LOOPBACK_HOSTS: Final[frozenset[str]] = frozenset(
    {"localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1"}
)
DEFAULT_QUACK_PORT: Final[int] = 5433
DEFAULT_CAPABILITY_TTL_MS: Final[int] = 30_000
MAX_SQL_BYTES: Final[int] = 256 * 1024
MAX_TOKEN_BYTES: Final[int] = 8_192
MAX_CAPABILITY_STORE: Final[int] = 100_000

SENSITIVE_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "token",
        "tokens",
        "quack_token",
        "password",
        "passwords",
        "secret",
        "secrets",
        "api_key",
        "authorization",
        "capability",
        "capability_token",
        "operation_capability",
        "sql",
        "full_sql",
        "query_text",
        "statement",
        "raw_sql",
        "encryption_key",
        "private_key",
    }
)

_HOST_RE = re.compile(
    r"^(?:localhost|(?:\d{1,3}\.){3}\d{1,3}|[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)$"
)
_SAFE_PATH_RE = re.compile(r"^[^;\x00-\x1f]+$")
_EXT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")
_OP_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class QuackSecurityError(ValueError):
    """Fail-closed rejection of a Quack security policy, capability, or launch."""

    reason_code: str = "quack_security.error"

    def __init__(self, message: str, *, reason_code: str | None = None) -> None:
        super().__init__(message)
        if reason_code is not None:
            self.reason_code = reason_code


class AuthenticationDenied(QuackSecurityError):
    """Fresh-connection authentication rejected the presented credential."""

    reason_code = "quack_security.authentication_denied"


class AuthorizationDenied(QuackSecurityError):
    """Exact full-SQL / connection authorization denied the statement."""

    reason_code = "quack_security.authorization_denied"


class PlaintextExposureRejected(QuackSecurityError):
    """Remote plaintext Quack bind or advertise was rejected."""

    reason_code = "quack_security.plaintext_exposure"


class PolicyViolation(QuackSecurityError):
    """A path, extension, filesystem, or egress policy was violated."""

    reason_code = "quack_security.policy_violation"


class CapabilityExpired(QuackSecurityError):
    """One-use operation capability has expired."""

    reason_code = "quack_security.capability_expired"


class CapabilityAlreadyConsumed(QuackSecurityError):
    """One-use operation capability was already consumed."""

    reason_code = "quack_security.capability_already_consumed"


class CapabilityNotFound(QuackSecurityError):
    """Presented capability token is unknown."""

    reason_code = "quack_security.capability_not_found"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class QuackServerProfile(str, Enum):
    """Closed set of guarded Quack server profiles."""

    PUBLICATION_GATEWAY = "publication_gateway"
    CATALOG_OWNER = "catalog_owner"


class AuthenticationMode(str, Enum):
    """How fresh connections authenticate.

    ``PERMISSIVE`` is never admitted for agent or production traffic.
    ``DEFAULT_DENY`` rejects every connection (safe idle default).
    ``ONE_USE_CAPABILITY`` requires a non-default fresh-connection callback
    that atomically consumes a broker-issued one-use operation capability.
    ``AUTHENTICATING_PROXY`` requires a TLS-terminating authenticating proxy
    that injects a verified one-use capability on the trusted loopback hop.
    """

    DEFAULT_DENY = "default_deny"
    ONE_USE_CAPABILITY = "one_use_capability"
    AUTHENTICATING_PROXY = "authenticating_proxy"
    # Explicitly named so misuse is detectable; never selected by builders.
    PERMISSIVE = "permissive"


class AuthorizationMode(str, Enum):
    """How statements are authorized after authentication.

    ``EXACT_FULL_SQL`` is the only production-admitted mode: the callback
    exact-matches the broker's versioned canonical SQL template and the
    authenticated connection/operation identities. Prefix/regex matching is
    forbidden. ``DEFAULT_DENY`` rejects every statement.
    ``PERMISSIVE`` is never admitted.
    """

    DEFAULT_DENY = "default_deny"
    EXACT_FULL_SQL = "exact_full_sql"
    PERMISSIVE = "permissive"


class EgressTargetKind(str, Enum):
    """Kind of allowed egress target for a catalog-owner shard."""

    OBJECT_ENDPOINT = "object_endpoint"
    TLS_PROXY = "tls_proxy"


# ---------------------------------------------------------------------------
# Sensitive handling
# ---------------------------------------------------------------------------


def redact_token(token: str | None) -> str:
    """Return a log-safe fingerprint or empty marker for a token."""

    if not token:
        return ""
    digest = hashlib.sha256(str(token).encode("utf-8")).hexdigest()[:12]
    return f"token:sha256:{digest}"


def redact_sql(sql: str | None, *, max_preview: int = 0) -> str:
    """Redact full SQL text for logs and receipts.

    By default only a content digest is retained. A zero-length preview is the
    production default so full SQL never appears in agent-visible surfaces.
    """

    if not sql:
        return ""
    text = str(sql)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if max_preview > 0:
        preview = text[:max_preview].replace("\n", " ")
        return f"sql:sha256:{digest}:preview={preview!r}"
    return f"sql:sha256:{digest}"


def sql_identity(sql: str) -> str:
    """Return a deterministic identity over exact full SQL bytes."""

    if not isinstance(sql, str):
        raise QuackSecurityError("sql must be a string")
    if len(sql.encode("utf-8")) > MAX_SQL_BYTES:
        raise QuackSecurityError("sql exceeds maximum byte length")
    return content_identity({"sql": sql, "schema": "exact_full_sql@1"})


def capability_fingerprint(token: str) -> str:
    """Return a non-reversible fingerprint of a capability token."""

    if not token:
        raise QuackSecurityError("capability token is required for fingerprint")
    return "sha256:" + hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def redact_sensitive(
    payload: Mapping[str, Any] | Sequence[Any] | Any,
    *,
    extra_fields: Iterable[str] = (),
) -> Any:
    """Recursively redact sensitive fields (tokens, SQL, secrets) from a payload."""

    sensitive = SENSITIVE_FIELD_NAMES | {str(f).lower() for f in extra_fields}

    def visit(value: Any, key_hint: str | None = None) -> Any:
        if key_hint is not None and key_hint.lower() in sensitive:
            if key_hint.lower() in {"sql", "full_sql", "query_text", "statement", "raw_sql"}:
                return redact_sql(str(value) if value is not None else None)
            return redact_token(str(value) if value is not None else None)
        if isinstance(value, Mapping):
            return {str(k): visit(v, str(k)) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [visit(item, None) for item in value]
        return value

    return visit(payload, None)


# ---------------------------------------------------------------------------
# Threat model
# ---------------------------------------------------------------------------


class ThreatActor(str, Enum):
    """Adversaries considered by the Quack threat model."""

    UNTRUSTED_AGENT = "untrusted_agent"
    COMPROMISED_WORKER = "compromised_worker"
    NETWORK_EAVESDROPPER = "network_eavesdropper"
    NETWORK_ACTIVE_ATTACKER = "network_active_attacker"
    MALICIOUS_REMOTE_CLIENT = "malicious_remote_client"
    INSIDER_WITH_HOST_ACCESS = "insider_with_host_access"
    STALE_OWNER_PROCESS = "stale_owner_process"


class ThreatAsset(str, Enum):
    """Assets protected by the Quack security boundary."""

    AUTHORITY_CATALOG_FILE = "authority_catalog_file"
    COMPANION_REGISTRY = "companion_registry"
    DUCKLAKE_ENCRYPTION_KEYS = "ducklake_encryption_keys"
    QUACK_REUSABLE_TOKEN = "quack_reusable_token"
    ONE_USE_OPERATION_CAPABILITY = "one_use_operation_capability"
    FULL_SQL_TEXT = "full_sql_text"
    OBJECT_STORE_CREDENTIALS = "object_store_credentials"
    SNAPSHOT_BOUND_PUBLICATION_DATA = "snapshot_bound_publication_data"
    CONTROL_PLANE_RECEIPTS = "control_plane_receipts"


class ThreatControl(str, Enum):
    """Controls enforced by the guarded launcher and profiles."""

    LOOPBACK_BIND = "loopback_bind"
    TLS_REVERSE_PROXY = "tls_reverse_proxy"
    ONE_USE_CAPABILITY_AUTH = "one_use_capability_auth"
    EXACT_FULL_SQL_AUTHZ = "exact_full_sql_authz"
    DEFAULT_DENY_AUTH = "default_deny_auth"
    DISABLED_EXTERNAL_ACCESS = "disabled_external_access"
    PINNED_EXPLICIT_EXTENSIONS = "pinned_explicit_extensions"
    LOCAL_PATH_ALLOWLIST = "local_path_allowlist"
    EGRESS_ALLOWLIST = "egress_allowlist"
    RESTRICTED_OS_IDENTITY = "restricted_os_identity"
    AUDIT_EVENTS = "audit_events"
    SENSITIVE_REDACTION = "sensitive_redaction"
    PROFILE_ISOLATION = "profile_isolation"
    NO_AMBIENT_REACHABILITY = "no_ambient_reachability"


@dataclass(frozen=True, slots=True)
class ThreatModelEntry:
    """One threat/asset/control mapping in the Quack threat model."""

    threat_id: str
    actor: ThreatActor
    asset: ThreatAsset
    description: str
    controls: tuple[ThreatControl, ...]
    residual_risk: str = "accepted_with_controls"

    def __post_init__(self) -> None:
        tid = str(self.threat_id or "").strip()
        if not re.match(r"^T[0-9]{2,3}$", tid):
            raise QuackSecurityError(f"invalid threat_id {self.threat_id!r}")
        object.__setattr__(self, "threat_id", tid)
        desc = str(self.description or "").strip()
        if not desc:
            raise QuackSecurityError("threat description is required")
        object.__setattr__(self, "description", desc)
        if not self.controls:
            raise QuackSecurityError("threat entry requires at least one control")
        object.__setattr__(self, "controls", tuple(self.controls))

    def to_dict(self) -> dict[str, Any]:
        return {
            "threat_id": self.threat_id,
            "actor": self.actor.value,
            "asset": self.asset.value,
            "description": self.description,
            "controls": [c.value for c in self.controls],
            "residual_risk": self.residual_risk,
        }


@dataclass(frozen=True, slots=True)
class QuackThreatModel:
    """Structured Quack threat model for both server profiles."""

    schema: str = QUACK_THREAT_MODEL_SCHEMA
    version: str = "1"
    entries: tuple[ThreatModelEntry, ...] = ()
    assumptions: tuple[str, ...] = ()
    non_goals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(self.entries))
        object.__setattr__(self, "assumptions", tuple(str(a) for a in self.assumptions))
        object.__setattr__(self, "non_goals", tuple(str(n) for n in self.non_goals))
        ids = [e.threat_id for e in self.entries]
        if len(ids) != len(set(ids)):
            raise QuackSecurityError("threat model entry ids must be unique")

    def identity_id(self) -> str:
        return content_identity(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "version": self.version,
            "entries": [e.to_dict() for e in self.entries],
            "assumptions": list(self.assumptions),
            "non_goals": list(self.non_goals),
        }


def default_threat_model() -> QuackThreatModel:
    """Return the authoritative Quack threat model for DQK-049 profiles."""

    entries = (
        ThreatModelEntry(
            threat_id="T01",
            actor=ThreatActor.UNTRUSTED_AGENT,
            asset=ThreatAsset.AUTHORITY_CATALOG_FILE,
            description=(
                "Untrusted agents attempt to open, ATTACH, or query the "
                "authority DuckLake catalog through a Quack endpoint."
            ),
            controls=(
                ThreatControl.PROFILE_ISOLATION,
                ThreatControl.DEFAULT_DENY_AUTH,
                ThreatControl.DISABLED_EXTERNAL_ACCESS,
                ThreatControl.LOCAL_PATH_ALLOWLIST,
            ),
        ),
        ThreatModelEntry(
            threat_id="T02",
            actor=ThreatActor.UNTRUSTED_AGENT,
            asset=ThreatAsset.FULL_SQL_TEXT,
            description=(
                "Agents attempt to submit arbitrary SQL or observe full SQL "
                "text of broker-authorized operations."
            ),
            controls=(
                ThreatControl.EXACT_FULL_SQL_AUTHZ,
                ThreatControl.SENSITIVE_REDACTION,
                ThreatControl.AUDIT_EVENTS,
            ),
        ),
        ThreatModelEntry(
            threat_id="T03",
            actor=ThreatActor.MALICIOUS_REMOTE_CLIENT,
            asset=ThreatAsset.QUACK_REUSABLE_TOKEN,
            description=(
                "A remote client reuses a long-lived Quack token as if it were "
                "per-operation authority."
            ),
            controls=(
                ThreatControl.ONE_USE_CAPABILITY_AUTH,
                ThreatControl.DEFAULT_DENY_AUTH,
            ),
        ),
        ThreatModelEntry(
            threat_id="T04",
            actor=ThreatActor.NETWORK_EAVESDROPPER,
            asset=ThreatAsset.ONE_USE_OPERATION_CAPABILITY,
            description=(
                "Network observers capture plaintext Quack credentials or SQL "
                "on non-loopback paths."
            ),
            controls=(
                ThreatControl.LOOPBACK_BIND,
                ThreatControl.TLS_REVERSE_PROXY,
                ThreatControl.SENSITIVE_REDACTION,
            ),
        ),
        ThreatModelEntry(
            threat_id="T05",
            actor=ThreatActor.NETWORK_ACTIVE_ATTACKER,
            asset=ThreatAsset.OBJECT_STORE_CREDENTIALS,
            description=(
                "Active attackers redirect catalog-owner egress to attacker "
                "object storage or inject ambient network reachability."
            ),
            controls=(
                ThreatControl.EGRESS_ALLOWLIST,
                ThreatControl.NO_AMBIENT_REACHABILITY,
                ThreatControl.RESTRICTED_OS_IDENTITY,
            ),
        ),
        ThreatModelEntry(
            threat_id="T06",
            actor=ThreatActor.COMPROMISED_WORKER,
            asset=ThreatAsset.COMPANION_REGISTRY,
            description=(
                "A compromised worker attempts INSTALL/LOAD of extensions or "
                "filesystem escape from the publication gateway."
            ),
            controls=(
                ThreatControl.PINNED_EXPLICIT_EXTENSIONS,
                ThreatControl.DISABLED_EXTERNAL_ACCESS,
                ThreatControl.RESTRICTED_OS_IDENTITY,
            ),
        ),
        ThreatModelEntry(
            threat_id="T07",
            actor=ThreatActor.STALE_OWNER_PROCESS,
            asset=ThreatAsset.AUTHORITY_CATALOG_FILE,
            description=(
                "A stale catalog-owner process continues serving after lease "
                "loss or uses permissive default authentication."
            ),
            controls=(
                ThreatControl.ONE_USE_CAPABILITY_AUTH,
                ThreatControl.DEFAULT_DENY_AUTH,
                ThreatControl.AUDIT_EVENTS,
            ),
        ),
        ThreatModelEntry(
            threat_id="T08",
            actor=ThreatActor.INSIDER_WITH_HOST_ACCESS,
            asset=ThreatAsset.DUCKLAKE_ENCRYPTION_KEYS,
            description=(
                "Host-local actors scrape logs, receipts, or agent responses "
                "for tokens, encryption keys, or full SQL."
            ),
            controls=(
                ThreatControl.SENSITIVE_REDACTION,
                ThreatControl.AUDIT_EVENTS,
            ),
        ),
        ThreatModelEntry(
            threat_id="T09",
            actor=ThreatActor.UNTRUSTED_AGENT,
            asset=ThreatAsset.SNAPSHOT_BOUND_PUBLICATION_DATA,
            description=(
                "Agents attempt to escalate from sanitized publication data to "
                "authority catalogs, object storage, or secret endpoints."
            ),
            controls=(
                ThreatControl.PROFILE_ISOLATION,
                ThreatControl.NO_AMBIENT_REACHABILITY,
                ThreatControl.DISABLED_EXTERNAL_ACCESS,
            ),
        ),
        ThreatModelEntry(
            threat_id="T10",
            actor=ThreatActor.MALICIOUS_REMOTE_CLIENT,
            asset=ThreatAsset.CONTROL_PLANE_RECEIPTS,
            description=(
                "Remote clients attempt to bind on non-loopback plaintext or "
                "bypass the supported TLS reverse proxy."
            ),
            controls=(
                ThreatControl.LOOPBACK_BIND,
                ThreatControl.TLS_REVERSE_PROXY,
            ),
        ),
    )
    return QuackThreatModel(
        entries=entries,
        assumptions=(
            "The trusted broker retains reusable Quack endpoint secrets and "
            "never issues them to untrusted agents.",
            "OS-level process isolation and least-privilege identities are "
            "enforced by the process supervisor outside this module.",
            "DuckLake itself is not a security boundary and provides no role "
            "or authorization layer.",
            "Publication gateways and catalog owners run as distinct OS and "
            "network identities.",
        ),
        non_goals=(
            "Quack does not provide replication, failover, or multi-owner "
            "catalog semantics.",
            "This module does not start production catalog endpoints or "
            "perform DuckLake mutations.",
            "GRANT-style catalog ACLs are not assumed or implemented.",
        ),
    )


# ---------------------------------------------------------------------------
# Policy surfaces
# ---------------------------------------------------------------------------


def is_loopback_host(host: str) -> bool:
    """Return True if ``host`` is a loopback address identity."""

    return str(host or "").strip().lower() in LOOPBACK_HOSTS


def assert_remote_not_plaintext(
    *,
    host: str,
    use_tls: bool,
    behind_tls_proxy: bool = False,
) -> None:
    """Reject remote plaintext exposure of a Quack endpoint.

    Loopback binds may be plaintext (credentials still per-operation). Any
    non-loopback bind or advertise requires TLS on the Quack endpoint itself
    or a supported TLS reverse proxy in front of a loopback origin.
    """

    host_norm = str(host or "").strip().lower()
    if not host_norm or not _HOST_RE.match(host_norm):
        raise QuackSecurityError(f"invalid bind/advertise host {host!r}")
    if is_loopback_host(host_norm):
        return
    if use_tls or behind_tls_proxy:
        return
    raise PlaintextExposureRejected(
        f"remote plaintext Quack exposure rejected for host {host_norm!r}; "
        "require TLS or a supported TLS reverse proxy"
    )


@dataclass(frozen=True, slots=True)
class OsIdentityPolicy:
    """Restricted OS identity for a Quack server process."""

    identity_name: str
    uid: int | None = None
    gid: int | None = None
    allow_root: bool = False
    drop_capabilities: bool = True
    no_new_privileges: bool = True

    def __post_init__(self) -> None:
        name = str(self.identity_name or "").strip()
        if not name or not _IDENTITY_RE.match(name):
            raise QuackSecurityError(f"invalid OS identity name {self.identity_name!r}")
        object.__setattr__(self, "identity_name", name)
        if self.allow_root:
            raise QuackSecurityError("root OS identity is forbidden for Quack profiles")
        if self.uid is not None and (not isinstance(self.uid, int) or self.uid < 1):
            raise QuackSecurityError("uid must be a positive int when set")
        if self.gid is not None and (not isinstance(self.gid, int) or self.gid < 1):
            raise QuackSecurityError("gid must be a positive int when set")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_name": self.identity_name,
            "uid": self.uid,
            "gid": self.gid,
            "allow_root": self.allow_root,
            "drop_capabilities": self.drop_capabilities,
            "no_new_privileges": self.no_new_privileges,
        }


@dataclass(frozen=True, slots=True)
class BindPolicy:
    """Network bind policy for a guarded Quack server."""

    host: str = "127.0.0.1"
    port: int = DEFAULT_QUACK_PORT
    use_tls: bool = False
    allow_remote_plaintext: bool = False

    def __post_init__(self) -> None:
        host = str(self.host or "").strip().lower()
        if not host or not _HOST_RE.match(host):
            raise QuackSecurityError(f"invalid bind host {self.host!r}")
        object.__setattr__(self, "host", host)
        if not isinstance(self.port, int) or isinstance(self.port, bool):
            raise QuackSecurityError("bind port must be an int")
        if self.port < 1 or self.port > 65_535:
            raise QuackSecurityError(f"bind port out of range: {self.port}")
        if self.allow_remote_plaintext:
            raise QuackSecurityError(
                "allow_remote_plaintext=True is forbidden; remote plaintext "
                "exposure is always rejected"
            )
        # Fail closed for non-loopback plaintext at construction time.
        assert_remote_not_plaintext(
            host=host,
            use_tls=self.use_tls,
            behind_tls_proxy=False,
        )

    @property
    def is_loopback(self) -> bool:
        return is_loopback_host(self.host)

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "use_tls": self.use_tls,
            "is_loopback": self.is_loopback,
            "allow_remote_plaintext": self.allow_remote_plaintext,
        }


@dataclass(frozen=True, slots=True)
class TlsProxyPolicy:
    """Supported TLS reverse proxy in front of a loopback Quack origin."""

    enabled: bool = False
    public_host: str = ""
    public_port: int = 443
    require_client_auth: bool = True
    terminate_tls: bool = True
    origin_must_be_loopback: bool = True

    def __post_init__(self) -> None:
        if not self.enabled:
            object.__setattr__(self, "public_host", "")
            return
        host = str(self.public_host or "").strip().lower()
        if not host or not _HOST_RE.match(host):
            raise QuackSecurityError(
                f"TLS proxy public_host required when enabled, got {self.public_host!r}"
            )
        object.__setattr__(self, "public_host", host)
        if not isinstance(self.public_port, int) or self.public_port < 1:
            raise QuackSecurityError("TLS proxy public_port must be a positive int")
        if not self.terminate_tls:
            raise QuackSecurityError(
                "supported TLS reverse proxy must terminate TLS"
            )
        if not self.origin_must_be_loopback:
            raise QuackSecurityError(
                "TLS proxy origin must be loopback-only for Quack profiles"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "public_host": self.public_host,
            "public_port": self.public_port,
            "require_client_auth": self.require_client_auth,
            "terminate_tls": self.terminate_tls,
            "origin_must_be_loopback": self.origin_must_be_loopback,
        }


@dataclass(frozen=True, slots=True)
class ExtensionPolicy:
    """Explicit-load extension policy (no ambient autoload/autoinstall)."""

    allowed_extensions: tuple[str, ...] = ()
    pinned_builds: Mapping[str, str] = field(default_factory=dict)
    autoinstall_known_extensions: bool = False
    autoload_known_extensions: bool = False
    allow_install: bool = False
    allow_load_unpinned: bool = False

    def __post_init__(self) -> None:
        if self.autoinstall_known_extensions or self.autoload_known_extensions:
            raise QuackSecurityError(
                "automatic extension install/load is forbidden for Quack profiles"
            )
        if self.allow_install:
            raise QuackSecurityError(
                "INSTALL is forbidden after provisioning; only explicit LOAD "
                "of pinned extensions is admitted"
            )
        if self.allow_load_unpinned:
            raise QuackSecurityError("unpinned extension LOAD is forbidden")
        names: list[str] = []
        for name in self.allowed_extensions:
            n = str(name or "").strip().lower()
            if not _EXT_NAME_RE.match(n):
                raise QuackSecurityError(f"invalid extension name {name!r}")
            names.append(n)
        if len(names) != len(set(names)):
            raise QuackSecurityError("allowed_extensions must be unique")
        object.__setattr__(self, "allowed_extensions", tuple(names))
        builds = {
            str(k).strip().lower(): str(v).strip()
            for k, v in dict(self.pinned_builds or {}).items()
        }
        for name in names:
            if name not in builds or not builds[name]:
                raise QuackSecurityError(
                    f"pinned build required for allowed extension {name!r}"
                )
        object.__setattr__(self, "pinned_builds", MappingProxyType(builds))

    def permits_load(self, extension_name: str) -> bool:
        name = str(extension_name or "").strip().lower()
        return name in self.allowed_extensions

    def assert_load_allowed(self, extension_name: str) -> None:
        if not self.permits_load(extension_name):
            raise PolicyViolation(
                f"extension LOAD denied for {extension_name!r}; not on pinned allowlist"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_extensions": list(self.allowed_extensions),
            "pinned_builds": dict(self.pinned_builds),
            "autoinstall_known_extensions": self.autoinstall_known_extensions,
            "autoload_known_extensions": self.autoload_known_extensions,
            "allow_install": self.allow_install,
            "allow_load_unpinned": self.allow_load_unpinned,
        }


@dataclass(frozen=True, slots=True)
class LocalPathPolicy:
    """Exact local path allowlist (no ambient filesystem inheritance)."""

    allowed_paths: tuple[str, ...] = ()
    allow_ambient: bool = False

    def __post_init__(self) -> None:
        if self.allow_ambient:
            raise QuackSecurityError(
                "ambient local-path reachability is forbidden for Quack profiles"
            )
        paths: list[str] = []
        for path in self.allowed_paths:
            p = str(path or "").strip()
            if not p:
                raise QuackSecurityError("empty local path is forbidden")
            if not _SAFE_PATH_RE.match(p):
                raise QuackSecurityError(f"unsafe local path {path!r}")
            lower = p.lower()
            if "://" in p or lower.startswith(
                ("s3:", "http:", "https:", "gs:", "az:", "nfs:", "smb:")
            ):
                raise QuackSecurityError(
                    f"remote/URI paths forbidden in local path policy: {path!r}"
                )
            paths.append(p)
        if len(paths) != len(set(paths)):
            raise QuackSecurityError("allowed_paths must be unique")
        object.__setattr__(self, "allowed_paths", tuple(paths))

    def permits(self, path: str) -> bool:
        """Exact path match only (no prefix inheritance)."""

        candidate = str(path or "").strip()
        return candidate in self.allowed_paths

    def assert_permitted(self, path: str) -> None:
        if not self.permits(path):
            raise PolicyViolation(
                f"local path denied: {path!r} is not the exact allowlisted path"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_paths": list(self.allowed_paths),
            "allow_ambient": self.allow_ambient,
        }


@dataclass(frozen=True, slots=True)
class FilesystemPolicy:
    """Filesystem surface for a Quack profile."""

    allow_filesystem: bool = False
    allow_copy: bool = False
    allow_read_functions: bool = False
    allow_attach_foreign: bool = False

    def __post_init__(self) -> None:
        # When filesystem is disabled, every derived surface must stay off.
        if not self.allow_filesystem:
            if self.allow_copy or self.allow_read_functions or self.allow_attach_foreign:
                raise QuackSecurityError(
                    "filesystem-derived surfaces require allow_filesystem=True"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_filesystem": self.allow_filesystem,
            "allow_copy": self.allow_copy,
            "allow_read_functions": self.allow_read_functions,
            "allow_attach_foreign": self.allow_attach_foreign,
        }


@dataclass(frozen=True, slots=True)
class EgressEndpoint:
    """One exact egress target (object endpoint or TLS proxy)."""

    kind: EgressTargetKind
    host: str
    port: int
    use_tls: bool = True
    path_prefix: str = ""

    def __post_init__(self) -> None:
        host = str(self.host or "").strip().lower()
        if not host or not _HOST_RE.match(host):
            raise QuackSecurityError(f"invalid egress host {self.host!r}")
        object.__setattr__(self, "host", host)
        if not isinstance(self.port, int) or isinstance(self.port, bool):
            raise QuackSecurityError("egress port must be an int")
        if self.port < 1 or self.port > 65_535:
            raise QuackSecurityError(f"egress port out of range: {self.port}")
        prefix = str(self.path_prefix or "").strip()
        if prefix and not prefix.startswith("/"):
            raise QuackSecurityError("egress path_prefix must start with '/' when set")
        object.__setattr__(self, "path_prefix", prefix)
        # Object endpoints and TLS proxies for remote storage must use TLS.
        if not self.use_tls and not is_loopback_host(host):
            raise PlaintextExposureRejected(
                f"non-loopback egress target must use TLS: {host}:{self.port}"
            )

    def authority(self) -> str:
        return f"{self.host}:{self.port}"

    def identity_key(self) -> str:
        return f"{self.kind.value}|{self.host}|{self.port}|{int(self.use_tls)}|{self.path_prefix}"

    def matches(
        self,
        *,
        host: str,
        port: int,
        use_tls: bool | None = None,
        path: str = "",
    ) -> bool:
        if str(host or "").strip().lower() != self.host:
            return False
        if int(port) != self.port:
            return False
        if use_tls is not None and bool(use_tls) != self.use_tls:
            return False
        if self.path_prefix:
            p = str(path or "")
            if p != self.path_prefix and not p.startswith(self.path_prefix.rstrip("/") + "/"):
                # Exact prefix allow: path must equal prefix or be under it.
                if not p.startswith(self.path_prefix):
                    return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "host": self.host,
            "port": self.port,
            "use_tls": self.use_tls,
            "path_prefix": self.path_prefix,
        }


@dataclass(frozen=True, slots=True)
class EgressPolicy:
    """Exact egress allowlist (no ambient network reachability)."""

    allowed_endpoints: tuple[EgressEndpoint, ...] = ()
    allow_ambient_network: bool = False
    allow_dns_except_allowlist: bool = False

    def __post_init__(self) -> None:
        if self.allow_ambient_network:
            raise QuackSecurityError(
                "ambient network reachability is forbidden for Quack profiles"
            )
        if self.allow_dns_except_allowlist:
            raise QuackSecurityError(
                "unrestricted DNS is forbidden; only exact allowlisted endpoints"
            )
        endpoints = tuple(self.allowed_endpoints)
        keys = [e.identity_key() for e in endpoints]
        if len(keys) != len(set(keys)):
            raise QuackSecurityError("egress endpoints must be unique")
        object.__setattr__(self, "allowed_endpoints", endpoints)

    def permits(
        self,
        *,
        host: str,
        port: int,
        use_tls: bool | None = None,
        path: str = "",
    ) -> bool:
        return any(
            ep.matches(host=host, port=port, use_tls=use_tls, path=path)
            for ep in self.allowed_endpoints
        )

    def assert_permitted(
        self,
        *,
        host: str,
        port: int,
        use_tls: bool | None = None,
        path: str = "",
    ) -> None:
        if not self.permits(host=host, port=port, use_tls=use_tls, path=path):
            raise PolicyViolation(
                f"egress denied to {host}:{port} (path={path!r}); not on exact allowlist"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_endpoints": [e.to_dict() for e in self.allowed_endpoints],
            "allow_ambient_network": self.allow_ambient_network,
            "allow_dns_except_allowlist": self.allow_dns_except_allowlist,
        }


@dataclass(frozen=True, slots=True)
class ExternalAccessPolicy:
    """DuckDB external-access surface (disabled for publication; owner-scoped)."""

    enable_external_access: bool = False
    lock_configuration: bool = True

    def __post_init__(self) -> None:
        if not self.lock_configuration:
            raise QuackSecurityError(
                "lock_configuration must remain true for Quack profiles"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enable_external_access": self.enable_external_access,
            "lock_configuration": self.lock_configuration,
        }


@dataclass(frozen=True, slots=True)
class AuditPolicy:
    """Audit emission policy for Quack connections and statements."""

    enabled: bool = True
    record_authentication: bool = True
    record_authorization: bool = True
    record_policy_violations: bool = True
    redact_tokens: bool = True
    redact_full_sql: bool = True

    def __post_init__(self) -> None:
        if not self.enabled:
            raise QuackSecurityError("audit cannot be disabled for Quack profiles")
        if not self.redact_tokens or not self.redact_full_sql:
            raise QuackSecurityError(
                "tokens and full SQL must remain redacted in audit output"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "record_authentication": self.record_authentication,
            "record_authorization": self.record_authorization,
            "record_policy_violations": self.record_policy_violations,
            "redact_tokens": self.redact_tokens,
            "redact_full_sql": self.redact_full_sql,
        }


@dataclass(frozen=True, slots=True)
class SensitiveSurfacePolicy:
    """Policy declaring tokens and full SQL as sensitive."""

    tokens_sensitive: bool = True
    full_sql_sensitive: bool = True
    scrub_logs: bool = True
    scrub_receipts: bool = True
    scrub_agent_responses: bool = True

    def __post_init__(self) -> None:
        if not self.tokens_sensitive or not self.full_sql_sensitive:
            raise QuackSecurityError(
                "tokens and full SQL text must be handled as sensitive"
            )
        if not (self.scrub_logs and self.scrub_receipts and self.scrub_agent_responses):
            raise QuackSecurityError(
                "sensitive scrubbing must cover logs, receipts, and agent responses"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tokens_sensitive": self.tokens_sensitive,
            "full_sql_sensitive": self.full_sql_sensitive,
            "scrub_logs": self.scrub_logs,
            "scrub_receipts": self.scrub_receipts,
            "scrub_agent_responses": self.scrub_agent_responses,
        }


# ---------------------------------------------------------------------------
# Profile configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QuackSecurityProfileConfig:
    """Complete security configuration for one Quack server profile.

    Profiles never inherit ambient filesystem, extension, secret, or network
    reachability from the host process environment.
    """

    profile: QuackServerProfile
    os_identity: OsIdentityPolicy
    bind: BindPolicy
    tls_proxy: TlsProxyPolicy
    extensions: ExtensionPolicy
    local_paths: LocalPathPolicy
    filesystem: FilesystemPolicy
    egress: EgressPolicy
    external_access: ExternalAccessPolicy
    authentication_mode: AuthenticationMode
    authorization_mode: AuthorizationMode
    audit: AuditPolicy = field(default_factory=AuditPolicy)
    sensitive: SensitiveSurfacePolicy = field(default_factory=SensitiveSurfacePolicy)
    per_operation_credentials: bool = True
    inherit_ambient_filesystem: bool = False
    inherit_ambient_extensions: bool = False
    inherit_ambient_secrets: bool = False
    inherit_ambient_network: bool = False
    duckdb_version: str = REQUIRED_DUCKDB_VERSION_TEXT
    quack_extension_build: str = PINNED_QUACK_EXTENSION_BUILD

    def __post_init__(self) -> None:
        # Never admit ambient inheritance.
        for flag_name in (
            "inherit_ambient_filesystem",
            "inherit_ambient_extensions",
            "inherit_ambient_secrets",
            "inherit_ambient_network",
        ):
            if getattr(self, flag_name):
                raise QuackSecurityError(
                    f"{flag_name}=True is forbidden; profiles must not inherit "
                    "ambient reachability"
                )
        if not self.per_operation_credentials:
            raise QuackSecurityError(
                "per-operation credentials are required for both Quack profiles"
            )
        # Never admit permissive auth/authz.
        if self.authentication_mode is AuthenticationMode.PERMISSIVE:
            raise QuackSecurityError(
                "PERMISSIVE authentication is never admitted for Quack traffic"
            )
        if self.authorization_mode is AuthorizationMode.PERMISSIVE:
            raise QuackSecurityError(
                "PERMISSIVE authorization is never admitted for Quack traffic"
            )

        if self.profile is QuackServerProfile.PUBLICATION_GATEWAY:
            self._validate_publication_gateway()
        elif self.profile is QuackServerProfile.CATALOG_OWNER:
            self._validate_catalog_owner()
        else:  # pragma: no cover - closed enum
            raise QuackSecurityError(f"unknown profile {self.profile!r}")

        # TLS proxy origin must match loopback bind when enabled.
        if self.tls_proxy.enabled and not self.bind.is_loopback:
            raise QuackSecurityError(
                "TLS reverse proxy requires a loopback Quack origin bind"
            )

    def _validate_publication_gateway(self) -> None:
        if self.external_access.enable_external_access:
            raise QuackSecurityError(
                "publication gateway must disable external access"
            )
        if self.filesystem.allow_filesystem:
            raise QuackSecurityError(
                "publication gateway must deny filesystem access"
            )
        if self.local_paths.allowed_paths:
            raise QuackSecurityError(
                "publication gateway must not allow local catalog paths"
            )
        if self.egress.allowed_endpoints:
            raise QuackSecurityError(
                "publication gateway must not allow object endpoint/TLS proxy egress"
            )
        if self.extensions.allowed_extensions:
            raise QuackSecurityError(
                "publication gateway must not pre-load ducklake/quack/httpfs "
                "or any catalog-owner extensions"
            )
        if not self.bind.is_loopback:
            # Remote publish only via TLS proxy in front of loopback origin.
            if not self.tls_proxy.enabled:
                raise QuackSecurityError(
                    "publication gateway non-loopback bind requires TLS reverse proxy"
                )
        # Publication still authorizes queries; default-deny auth is allowed
        # as a hard closed surface, or one-use for trusted broker injection.
        if self.authentication_mode is AuthenticationMode.PERMISSIVE:
            raise QuackSecurityError("publication auth cannot be permissive")
        if self.authorization_mode is AuthorizationMode.PERMISSIVE:
            raise QuackSecurityError("publication authz cannot be permissive")

    def _validate_catalog_owner(self) -> None:
        # Catalog owner must use non-default fresh-connection authentication.
        if self.authentication_mode not in {
            AuthenticationMode.ONE_USE_CAPABILITY,
            AuthenticationMode.AUTHENTICATING_PROXY,
        }:
            raise QuackSecurityError(
                "catalog owner requires one-use capability authentication via "
                "a non-default authentication callback or authenticating proxy"
            )
        if self.authorization_mode is not AuthorizationMode.EXACT_FULL_SQL:
            raise QuackSecurityError(
                "catalog owner requires exact full-SQL authorization callbacks"
            )
        # Must pre-load only pinned ducklake/quack/object extensions.
        allowed = set(self.extensions.allowed_extensions)
        required = set(CATALOG_OWNER_PINNED_EXTENSIONS)
        if allowed != required:
            raise QuackSecurityError(
                "catalog owner must allow exactly pinned ducklake, quack, and "
                f"object-adapter extensions; got {sorted(allowed)}"
            )
        # Exact local catalog path required (single path).
        if len(self.local_paths.allowed_paths) != 1:
            raise QuackSecurityError(
                "catalog owner must allow exactly one local catalog path"
            )
        # Filesystem only for that exact catalog path (no free-form FS).
        if not self.filesystem.allow_filesystem:
            raise QuackSecurityError(
                "catalog owner requires scoped filesystem access for its catalog path"
            )
        if self.filesystem.allow_copy or self.filesystem.allow_read_functions:
            raise QuackSecurityError(
                "catalog owner must not enable COPY or read_* filesystem surfaces"
            )
        if self.filesystem.allow_attach_foreign:
            raise QuackSecurityError(
                "catalog owner must not allow foreign ATTACH"
            )
        # Egress only to exact object endpoint and/or TLS proxy.
        if not self.egress.allowed_endpoints:
            raise QuackSecurityError(
                "catalog owner requires at least one exact object endpoint or TLS proxy"
            )
        kinds = {ep.kind for ep in self.egress.allowed_endpoints}
        if not kinds.issubset(
            {EgressTargetKind.OBJECT_ENDPOINT, EgressTargetKind.TLS_PROXY}
        ):
            raise QuackSecurityError("catalog owner egress kinds are restricted")
        # External access may be enabled only to support the exact object egress;
        # configuration remains locked after setup.
        if not self.external_access.lock_configuration:
            raise QuackSecurityError("catalog owner must lock configuration")

    def permits_local_path(self, path: str) -> bool:
        return self.local_paths.permits(path)

    def permits_egress(
        self,
        *,
        host: str,
        port: int,
        use_tls: bool | None = None,
        path: str = "",
    ) -> bool:
        return self.egress.permits(
            host=host, port=port, use_tls=use_tls, path=path
        )

    def identity_id(self) -> str:
        return content_identity(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": QUACK_SECURITY_SCHEMA,
            "profile": self.profile.value,
            "os_identity": self.os_identity.to_dict(),
            "bind": self.bind.to_dict(),
            "tls_proxy": self.tls_proxy.to_dict(),
            "extensions": self.extensions.to_dict(),
            "local_paths": self.local_paths.to_dict(),
            "filesystem": self.filesystem.to_dict(),
            "egress": self.egress.to_dict(),
            "external_access": self.external_access.to_dict(),
            "authentication_mode": self.authentication_mode.value,
            "authorization_mode": self.authorization_mode.value,
            "audit": self.audit.to_dict(),
            "sensitive": self.sensitive.to_dict(),
            "per_operation_credentials": self.per_operation_credentials,
            "inherit_ambient_filesystem": self.inherit_ambient_filesystem,
            "inherit_ambient_extensions": self.inherit_ambient_extensions,
            "inherit_ambient_secrets": self.inherit_ambient_secrets,
            "inherit_ambient_network": self.inherit_ambient_network,
            "duckdb_version": self.duckdb_version,
            "quack_extension_build": self.quack_extension_build,
            "implementation_generation": _IMPLEMENTATION_GENERATION,
        }


def publication_gateway_profile(
    *,
    identity_name: str = "quack-publication-gateway",
    bind_host: str = "127.0.0.1",
    bind_port: int = DEFAULT_QUACK_PORT,
    tls_proxy: TlsProxyPolicy | None = None,
    authentication_mode: AuthenticationMode = AuthenticationMode.ONE_USE_CAPABILITY,
    authorization_mode: AuthorizationMode = AuthorizationMode.EXACT_FULL_SQL,
) -> QuackSecurityProfileConfig:
    """Build the sanitized publication-gateway security profile."""

    # Agent traffic never gets permissive defaults.
    if authentication_mode is AuthenticationMode.PERMISSIVE:
        raise QuackSecurityError(
            "default authentication is never permissive for agent traffic"
        )
    if authorization_mode is AuthorizationMode.PERMISSIVE:
        raise QuackSecurityError(
            "default authorization is never permissive for agent traffic"
        )
    # Exact full-SQL authorization requires a non-default one-use authenticator.
    # A fully closed surface may pair DEFAULT_DENY auth with DEFAULT_DENY authz.
    if authentication_mode is AuthenticationMode.DEFAULT_DENY:
        if authorization_mode is AuthorizationMode.EXACT_FULL_SQL:
            raise QuackSecurityError(
                "publication DEFAULT_DENY authentication cannot pair with "
                "EXACT_FULL_SQL authorization; use ONE_USE_CAPABILITY or "
                "DEFAULT_DENY authorization"
            )
    if authorization_mode is AuthorizationMode.DEFAULT_DENY:
        if authentication_mode in {
            AuthenticationMode.ONE_USE_CAPABILITY,
            AuthenticationMode.AUTHENTICATING_PROXY,
        }:
            # Still valid: authenticate then deny all statements (closed).
            pass

    proxy = tls_proxy or TlsProxyPolicy(enabled=False)
    return QuackSecurityProfileConfig(
        profile=QuackServerProfile.PUBLICATION_GATEWAY,
        os_identity=OsIdentityPolicy(identity_name=identity_name),
        bind=BindPolicy(host=bind_host, port=bind_port, use_tls=False),
        tls_proxy=proxy,
        extensions=ExtensionPolicy(
            allowed_extensions=PUBLICATION_GATEWAY_PINNED_EXTENSIONS,
            pinned_builds={},
        ),
        local_paths=LocalPathPolicy(allowed_paths=()),
        filesystem=FilesystemPolicy(allow_filesystem=False),
        egress=EgressPolicy(allowed_endpoints=()),
        external_access=ExternalAccessPolicy(
            enable_external_access=False,
            lock_configuration=True,
        ),
        authentication_mode=authentication_mode,
        authorization_mode=authorization_mode,
    )


def catalog_owner_profile(
    *,
    catalog_path: str,
    object_endpoint: EgressEndpoint,
    tls_proxy_egress: EgressEndpoint | None = None,
    identity_name: str = "quack-catalog-owner",
    bind_host: str = "127.0.0.1",
    bind_port: int = DEFAULT_QUACK_PORT,
    authentication_mode: AuthenticationMode = AuthenticationMode.ONE_USE_CAPABILITY,
    public_tls_proxy: TlsProxyPolicy | None = None,
) -> QuackSecurityProfileConfig:
    """Build the internal DuckLake catalog-owner security profile."""

    if authentication_mode not in {
        AuthenticationMode.ONE_USE_CAPABILITY,
        AuthenticationMode.AUTHENTICATING_PROXY,
    }:
        raise QuackSecurityError(
            "catalog owner requires non-default one-use authentication "
            f"(callback or authenticating proxy); got {authentication_mode!r}"
        )

    endpoints: list[EgressEndpoint] = [object_endpoint]
    if tls_proxy_egress is not None:
        endpoints.append(tls_proxy_egress)

    pinned_builds = {
        PINNED_DUCKLAKE_EXTENSION_NAME: PINNED_DUCKLAKE_EXTENSION_BUILD,
        PINNED_QUACK_EXTENSION_NAME: PINNED_QUACK_EXTENSION_BUILD,
        PINNED_OBJECT_ADAPTER_EXTENSION_NAME: PINNED_OBJECT_ADAPTER_EXTENSION_BUILD,
    }

    return QuackSecurityProfileConfig(
        profile=QuackServerProfile.CATALOG_OWNER,
        os_identity=OsIdentityPolicy(identity_name=identity_name),
        bind=BindPolicy(host=bind_host, port=bind_port, use_tls=False),
        tls_proxy=public_tls_proxy or TlsProxyPolicy(enabled=False),
        extensions=ExtensionPolicy(
            allowed_extensions=CATALOG_OWNER_PINNED_EXTENSIONS,
            pinned_builds=pinned_builds,
        ),
        local_paths=LocalPathPolicy(allowed_paths=(catalog_path,)),
        filesystem=FilesystemPolicy(
            allow_filesystem=True,
            allow_copy=False,
            allow_read_functions=False,
            allow_attach_foreign=False,
        ),
        egress=EgressPolicy(allowed_endpoints=tuple(endpoints)),
        external_access=ExternalAccessPolicy(
            # Scoped external access only for the allowlisted object egress.
            enable_external_access=True,
            lock_configuration=True,
        ),
        authentication_mode=authentication_mode,
        authorization_mode=AuthorizationMode.EXACT_FULL_SQL,
    )


def build_security_profile(
    profile: QuackServerProfile | str,
    **kwargs: Any,
) -> QuackSecurityProfileConfig:
    """Dispatch helper to build a named security profile."""

    if isinstance(profile, str):
        profile = QuackServerProfile(profile)
    if profile is QuackServerProfile.PUBLICATION_GATEWAY:
        return publication_gateway_profile(**kwargs)
    if profile is QuackServerProfile.CATALOG_OWNER:
        return catalog_owner_profile(**kwargs)
    raise QuackSecurityError(f"unknown profile {profile!r}")


# ---------------------------------------------------------------------------
# One-use operation capabilities
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OperationCapability:
    """Broker-issued, one-use, expiring operation capability.

    The raw token is sensitive and never appears in ``repr`` / ``str``.
    """

    operation_id: str
    profile: QuackServerProfile
    caller_identity: str
    issued_at_ms: int
    expires_at_ms: int
    token: str = field(repr=False)
    sql_template_identity: str = ""
    resource: str = ""
    nonce: str = field(default_factory=lambda: secrets.token_hex(16), repr=False)
    consumed: bool = False

    def __post_init__(self) -> None:
        op = str(self.operation_id or "").strip()
        if not op or not _OP_ID_RE.match(op):
            raise QuackSecurityError(f"invalid operation_id {self.operation_id!r}")
        object.__setattr__(self, "operation_id", op)
        caller = str(self.caller_identity or "").strip()
        if not caller or not _IDENTITY_RE.match(caller):
            raise QuackSecurityError(f"invalid caller_identity {self.caller_identity!r}")
        object.__setattr__(self, "caller_identity", caller)
        token = str(self.token or "")
        if not token or len(token.encode("utf-8")) > MAX_TOKEN_BYTES:
            raise QuackSecurityError("capability token missing or too large")
        object.__setattr__(self, "token", token)
        if self.expires_at_ms <= self.issued_at_ms:
            raise QuackSecurityError("capability expiry must be after issuance")
        if self.profile not in (
            QuackServerProfile.PUBLICATION_GATEWAY,
            QuackServerProfile.CATALOG_OWNER,
        ):
            raise QuackSecurityError(f"invalid capability profile {self.profile!r}")

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"OperationCapability(operation_id={self.operation_id!r}, "
            f"profile={self.profile.value!r}, token={redact_token(self.token)}, "
            f"consumed={self.consumed})"
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.__repr__()

    @property
    def fingerprint(self) -> str:
        return capability_fingerprint(self.token)

    def is_expired(self, now_ms: int | None = None) -> bool:
        clock = int(time.time() * 1000) if now_ms is None else int(now_ms)
        return clock >= self.expires_at_ms

    def redacted_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "profile": self.profile.value,
            "caller_identity": self.caller_identity,
            "issued_at_ms": self.issued_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "token": redact_token(self.token),
            "sql_template_identity": self.sql_template_identity,
            "resource": self.resource,
            "nonce": redact_token(self.nonce),
            "consumed": self.consumed,
            "fingerprint": self.fingerprint,
        }

    def with_consumed(self) -> OperationCapability:
        return replace(self, consumed=True)


class OneUseCapabilityStore:
    """Thread-safe store that issues and atomically consumes one-use capabilities."""

    def __init__(self, *, max_entries: int = MAX_CAPABILITY_STORE) -> None:
        if max_entries < 1:
            raise QuackSecurityError("max_entries must be positive")
        self._max = max_entries
        self._lock = threading.RLock()
        self._by_token: dict[str, OperationCapability] = {}

    def issue(
        self,
        *,
        operation_id: str,
        profile: QuackServerProfile,
        caller_identity: str,
        ttl_ms: int = DEFAULT_CAPABILITY_TTL_MS,
        sql_template_identity: str = "",
        resource: str = "",
        token: str | None = None,
        now_ms: int | None = None,
    ) -> OperationCapability:
        if ttl_ms < 1:
            raise QuackSecurityError("ttl_ms must be positive")
        clock = int(time.time() * 1000) if now_ms is None else int(now_ms)
        raw = token if token is not None else secrets.token_urlsafe(32)
        cap = OperationCapability(
            operation_id=operation_id,
            profile=profile,
            caller_identity=caller_identity,
            issued_at_ms=clock,
            expires_at_ms=clock + int(ttl_ms),
            token=raw,
            sql_template_identity=sql_template_identity,
            resource=resource,
        )
        with self._lock:
            self._purge_locked(clock)
            if len(self._by_token) >= self._max:
                raise QuackSecurityError("capability store capacity exceeded")
            if cap.token in self._by_token:
                raise QuackSecurityError("capability token collision")
            self._by_token[cap.token] = cap
        return cap

    def consume(
        self,
        token: str,
        *,
        expected_profile: QuackServerProfile | None = None,
        expected_operation_id: str | None = None,
        now_ms: int | None = None,
    ) -> OperationCapability:
        """Atomically consume a one-use capability (fail closed)."""

        if not token:
            raise AuthenticationDenied("missing operation capability token")
        clock = int(time.time() * 1000) if now_ms is None else int(now_ms)
        with self._lock:
            cap = self._by_token.get(token)
            if cap is None:
                raise CapabilityNotFound("unknown operation capability")
            if cap.consumed:
                raise CapabilityAlreadyConsumed(
                    f"capability for operation {cap.operation_id!r} already consumed"
                )
            if cap.is_expired(clock):
                # Remove and reject.
                self._by_token.pop(token, None)
                raise CapabilityExpired(
                    f"capability for operation {cap.operation_id!r} expired"
                )
            if expected_profile is not None and cap.profile is not expected_profile:
                raise AuthenticationDenied(
                    f"capability profile mismatch: expected {expected_profile.value}, "
                    f"got {cap.profile.value}"
                )
            if (
                expected_operation_id is not None
                and cap.operation_id != expected_operation_id
            ):
                raise AuthenticationDenied(
                    f"capability operation_id mismatch: expected "
                    f"{expected_operation_id!r}, got {cap.operation_id!r}"
                )
            consumed = cap.with_consumed()
            # One-use: remove after consume so replay fails as not found.
            del self._by_token[token]
            return consumed

    def peek(self, token: str) -> OperationCapability | None:
        with self._lock:
            return self._by_token.get(token)

    def __len__(self) -> int:
        with self._lock:
            return len(self._by_token)

    def _purge_locked(self, now_ms: int) -> None:
        expired = [
            tok
            for tok, cap in self._by_token.items()
            if cap.consumed or cap.is_expired(now_ms)
        ]
        for tok in expired:
            self._by_token.pop(tok, None)


# ---------------------------------------------------------------------------
# Authentication / authorization callbacks
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """Session established by a non-default fresh-connection authenticator."""

    session_id: str
    profile: QuackServerProfile
    caller_identity: str
    operation_id: str
    capability_fingerprint: str
    sql_template_identity: str = ""
    authenticated_at_ms: int = 0
    authentication_mode: AuthenticationMode = AuthenticationMode.ONE_USE_CAPABILITY

    def __post_init__(self) -> None:
        sid = str(self.session_id or "").strip()
        if not sid:
            raise QuackSecurityError("session_id is required")
        object.__setattr__(self, "session_id", sid)
        if not self.caller_identity:
            raise QuackSecurityError("caller_identity is required")
        if not self.operation_id:
            raise QuackSecurityError("operation_id is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "profile": self.profile.value,
            "caller_identity": self.caller_identity,
            "operation_id": self.operation_id,
            "capability_fingerprint": self.capability_fingerprint,
            "sql_template_identity": self.sql_template_identity,
            "authenticated_at_ms": self.authenticated_at_ms,
            "authentication_mode": self.authentication_mode.value,
        }


class FreshConnectionAuthenticator:
    """Non-default fresh-connection authentication callback.

    Atomically consumes a one-use operation capability and binds the resulting
    session identity for subsequent exact full-SQL authorization. This is the
    production catalog-owner (and publication) authentication path — never a
    permissive default.
    """

    def __init__(
        self,
        store: OneUseCapabilityStore,
        *,
        profile: QuackServerProfile,
        mode: AuthenticationMode = AuthenticationMode.ONE_USE_CAPABILITY,
        audit_sink: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        if mode is AuthenticationMode.PERMISSIVE:
            raise QuackSecurityError(
                "FreshConnectionAuthenticator cannot be configured as PERMISSIVE"
            )
        if mode is AuthenticationMode.DEFAULT_DENY:
            raise QuackSecurityError(
                "use DefaultDenyAuthenticator for default-deny mode"
            )
        if mode not in {
            AuthenticationMode.ONE_USE_CAPABILITY,
            AuthenticationMode.AUTHENTICATING_PROXY,
        }:
            raise QuackSecurityError(f"unsupported authentication mode {mode!r}")
        self._store = store
        self._profile = profile
        self._mode = mode
        self._audit = audit_sink
        self._sessions: dict[str, AuthenticatedSession] = {}
        self._lock = threading.RLock()

    @property
    def is_default(self) -> bool:
        """Always False — this is an explicitly installed non-default callback."""

        return False

    @property
    def mode(self) -> AuthenticationMode:
        return self._mode

    @property
    def profile(self) -> QuackServerProfile:
        return self._profile

    def authenticate(
        self,
        token: str,
        *,
        expected_operation_id: str | None = None,
        now_ms: int | None = None,
    ) -> AuthenticatedSession:
        """Authenticate a fresh connection by consuming a one-use capability."""

        clock = int(time.time() * 1000) if now_ms is None else int(now_ms)
        try:
            cap = self._store.consume(
                token,
                expected_profile=self._profile,
                expected_operation_id=expected_operation_id,
                now_ms=clock,
            )
        except QuackSecurityError as exc:
            self._emit_audit(
                {
                    "event": "authentication_denied",
                    "profile": self._profile.value,
                    "token": redact_token(token),
                    "reason": str(exc),
                    "reason_code": getattr(exc, "reason_code", "unknown"),
                }
            )
            raise AuthenticationDenied(str(exc)) from exc

        session = AuthenticatedSession(
            session_id=str(uuid.uuid4()),
            profile=self._profile,
            caller_identity=cap.caller_identity,
            operation_id=cap.operation_id,
            capability_fingerprint=cap.fingerprint,
            sql_template_identity=cap.sql_template_identity,
            authenticated_at_ms=clock,
            authentication_mode=self._mode,
        )
        with self._lock:
            self._sessions[session.session_id] = session
        self._emit_audit(
            {
                "event": "authentication_ok",
                "profile": self._profile.value,
                "session_id": session.session_id,
                "operation_id": session.operation_id,
                "caller_identity": session.caller_identity,
                "token": redact_token(token),
                "capability_fingerprint": session.capability_fingerprint,
            }
        )
        return session

    def get_session(self, session_id: str) -> AuthenticatedSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def revoke_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def _emit_audit(self, event: Mapping[str, Any]) -> None:
        if self._audit is not None:
            self._audit(redact_sensitive(dict(event)))


class DefaultDenyAuthenticator:
    """Default authentication callback: never permissive, always denies."""

    def __init__(self, *, profile: QuackServerProfile | None = None) -> None:
        self._profile = profile

    @property
    def is_default(self) -> bool:
        return True

    @property
    def mode(self) -> AuthenticationMode:
        return AuthenticationMode.DEFAULT_DENY

    def authenticate(self, token: str, **_: Any) -> AuthenticatedSession:
        raise AuthenticationDenied(
            "default authentication is deny-all; install a non-default "
            "FreshConnectionAuthenticator or authenticating proxy"
        )


class ExactFullSqlAuthorizer:
    """Exact full-SQL authorization callback (defense in depth).

    Authorizes only when:

    * the connection session is authenticated, and
    * the presented SQL is an exact byte-for-byte match of the broker's
      versioned canonical template bound to that session's operation.

    Prefix and regex approximations are forbidden. Missing session, missing
    template binding, or any mismatch fails closed.
    """

    def __init__(
        self,
        *,
        profile: QuackServerProfile,
        authenticator: FreshConnectionAuthenticator,
        audit_sink: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        self._profile = profile
        self._authenticator = authenticator
        self._audit = audit_sink
        # operation_id -> exact SQL text (sensitive; never logged raw)
        self._templates: dict[str, str] = {}
        self._lock = threading.RLock()

    @property
    def is_default(self) -> bool:
        return False

    @property
    def mode(self) -> AuthorizationMode:
        return AuthorizationMode.EXACT_FULL_SQL

    def register_exact_sql(self, operation_id: str, sql: str) -> str:
        """Register the exact full SQL allowed for ``operation_id``.

        Returns the SQL identity digest. The raw SQL is retained only for
        exact comparison and is never exposed via ``to_dict`` or audit.
        """

        op = str(operation_id or "").strip()
        if not op or not _OP_ID_RE.match(op):
            raise QuackSecurityError(f"invalid operation_id {operation_id!r}")
        if not isinstance(sql, str) or not sql:
            raise QuackSecurityError("exact SQL template must be non-empty text")
        if len(sql.encode("utf-8")) > MAX_SQL_BYTES:
            raise QuackSecurityError("exact SQL template exceeds maximum size")
        # Multi-statement escape: reject semicolons that would allow chaining.
        # Allow a single trailing semicolon only.
        body = sql.strip()
        if ";" in body.rstrip(";"):
            raise QuackSecurityError(
                "exact SQL template must be a single statement (no multi-statement)"
            )
        identity = sql_identity(sql)
        with self._lock:
            self._templates[op] = sql
        return identity

    def authorize(
        self,
        *,
        session_id: str,
        sql: str,
    ) -> Mapping[str, Any]:
        """Authorize ``sql`` for an authenticated session (exact match only)."""

        session = self._authenticator.get_session(session_id)
        if session is None:
            self._emit(
                {
                    "event": "authorization_denied",
                    "reason": "unknown_session",
                    "session_id": session_id,
                    "sql": redact_sql(sql),
                }
            )
            raise AuthorizationDenied("unknown or unauthenticated session")

        if session.profile is not self._profile:
            raise AuthorizationDenied("session profile mismatch")

        with self._lock:
            expected = self._templates.get(session.operation_id)

        if expected is None:
            self._emit(
                {
                    "event": "authorization_denied",
                    "reason": "no_template",
                    "session_id": session_id,
                    "operation_id": session.operation_id,
                    "sql": redact_sql(sql),
                }
            )
            raise AuthorizationDenied(
                f"no exact SQL template registered for operation "
                f"{session.operation_id!r}"
            )

        # Exact full-SQL match — no prefix, no regex, no normalize-beyond-identity.
        if sql != expected:
            # Also allow exact match against identity if session carries one and
            # the presented SQL hashes to it *and* equals the registered text.
            # (Equality already failed; reject.)
            self._emit(
                {
                    "event": "authorization_denied",
                    "reason": "sql_mismatch",
                    "session_id": session_id,
                    "operation_id": session.operation_id,
                    "sql": redact_sql(sql),
                    "expected_sql": redact_sql(expected),
                }
            )
            raise AuthorizationDenied(
                "exact full-SQL authorization failed: statement does not match "
                "the broker-authorized canonical template"
            )

        # If the capability bound a template identity, verify it too.
        if session.sql_template_identity:
            presented_id = sql_identity(sql)
            if presented_id != session.sql_template_identity:
                raise AuthorizationDenied(
                    "SQL template identity mismatch for authenticated operation"
                )

        result = {
            "authorized": True,
            "session_id": session.session_id,
            "operation_id": session.operation_id,
            "caller_identity": session.caller_identity,
            "sql": redact_sql(sql),
            "sql_identity": sql_identity(sql),
            "authorization_mode": self.mode.value,
        }
        self._emit(
            {
                "event": "authorization_ok",
                **result,
            }
        )
        return MappingProxyType(result)

    def _emit(self, event: Mapping[str, Any]) -> None:
        if self._audit is not None:
            self._audit(redact_sensitive(dict(event)))


class DefaultDenyAuthorizer:
    """Default authorization callback: never permissive, always denies."""

    @property
    def is_default(self) -> bool:
        return True

    @property
    def mode(self) -> AuthorizationMode:
        return AuthorizationMode.DEFAULT_DENY

    def authorize(self, *, session_id: str, sql: str) -> Mapping[str, Any]:
        raise AuthorizationDenied(
            "default authorization is deny-all; install ExactFullSqlAuthorizer"
        )


# ---------------------------------------------------------------------------
# Guarded server launcher
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GuardedServerPlan:
    """Materialized, launchable plan for a guarded Quack server.

    The plan is side-effect free. Tokens and full SQL never appear in
    ``to_dict`` / public surfaces.
    """

    profile_config: QuackSecurityProfileConfig
    threat_model_identity: str
    authentication_callback: str
    authorization_callback: str
    pre_load_extensions: tuple[str, ...]
    duckdb_config: Mapping[str, str]
    audit_enabled: bool
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "pre_load_extensions", tuple(self.pre_load_extensions)
        )
        object.__setattr__(
            self, "duckdb_config", MappingProxyType(dict(self.duckdb_config))
        )
        # Fail closed: authentication callback name must not be the permissive default.
        if self.authentication_callback in {"", "default", "permissive", "allow_all"}:
            raise QuackSecurityError(
                "authentication callback must be a non-default installed function"
            )
        if self.authorization_callback in {"", "default", "permissive", "allow_all"}:
            raise QuackSecurityError(
                "authorization callback must be a non-default installed function"
            )
        if self.profile_config.profile is QuackServerProfile.CATALOG_OWNER:
            if self.authentication_callback == "default_deny":
                raise QuackSecurityError(
                    "catalog owner cannot launch with default-deny authentication; "
                    "fresh connections require one-use capability callback"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": QUACK_SERVER_LAUNCH_SCHEMA,
            "plan_id": self.plan_id,
            "profile": self.profile_config.to_dict(),
            "threat_model_identity": self.threat_model_identity,
            "authentication_callback": self.authentication_callback,
            "authorization_callback": self.authorization_callback,
            "pre_load_extensions": list(self.pre_load_extensions),
            "duckdb_config": dict(self.duckdb_config),
            "audit_enabled": self.audit_enabled,
        }

    def identity_id(self) -> str:
        return content_identity(self.to_dict())


class ProcessRunner(Protocol):
    """Optional process runner injected for tests."""

    def __call__(self, plan: GuardedServerPlan) -> Mapping[str, Any]:
        ...


class GuardedQuackServerLauncher:
    """Build and (optionally) materialize a guarded Quack server for one profile.

    Construction validates the profile and threat model. Launch is fail-closed
    and never starts a production endpoint unless an explicit runner is provided.
    Without a runner, :meth:`launch` returns a dry-run receipt of the validated
    plan (suitable for tests and control-plane planning).
    """

    AUTH_CALLBACK_NAME: Final[str] = "quack_authentication_function"
    AUTHZ_CALLBACK_NAME: Final[str] = "quack_authorization_function"

    def __init__(
        self,
        profile_config: QuackSecurityProfileConfig,
        *,
        threat_model: QuackThreatModel | None = None,
        capability_store: OneUseCapabilityStore | None = None,
        runner: ProcessRunner | None = None,
        audit_sink: Callable[[Mapping[str, Any]], None] | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self._config = profile_config
        self._threat_model = threat_model or default_threat_model()
        self._store = capability_store or OneUseCapabilityStore()
        self._runner = runner
        self._audit_events: list[dict[str, Any]] = []
        self._audit_sink = audit_sink
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._authenticator: FreshConnectionAuthenticator | DefaultDenyAuthenticator
        self._authorizer: ExactFullSqlAuthorizer | DefaultDenyAuthorizer
        self._install_callbacks()
        self._plan = self._build_plan()

    def _audit(self, event: Mapping[str, Any]) -> None:
        redacted = redact_sensitive(dict(event))
        if not isinstance(redacted, dict):
            redacted = {"event": "malformed_audit"}
        self._audit_events.append(redacted)
        if self._audit_sink is not None:
            self._audit_sink(redacted)

    def _install_callbacks(self) -> None:
        cfg = self._config
        if cfg.authentication_mode in {
            AuthenticationMode.ONE_USE_CAPABILITY,
            AuthenticationMode.AUTHENTICATING_PROXY,
        }:
            self._authenticator = FreshConnectionAuthenticator(
                self._store,
                profile=cfg.profile,
                mode=cfg.authentication_mode,
                audit_sink=self._audit,
            )
        else:
            # Publication may use default-deny as a hard-closed surface.
            self._authenticator = DefaultDenyAuthenticator(profile=cfg.profile)

        if cfg.authorization_mode is AuthorizationMode.EXACT_FULL_SQL:
            if not isinstance(self._authenticator, FreshConnectionAuthenticator):
                # Exact SQL authz requires sessions from a non-default authenticator.
                # Install a one-use authenticator even if mode was default-deny? No —
                # fail closed: EXACT_FULL_SQL without one-use auth is inconsistent
                # for production; for publication with default-deny auth, use deny authz.
                raise QuackSecurityError(
                    "exact full-SQL authorization requires a non-default "
                    "one-use capability authenticator"
                )
            self._authorizer = ExactFullSqlAuthorizer(
                profile=cfg.profile,
                authenticator=self._authenticator,
                audit_sink=self._audit,
            )
        else:
            self._authorizer = DefaultDenyAuthorizer()

    def _build_plan(self) -> GuardedServerPlan:
        cfg = self._config
        # Re-validate remote plaintext against bind + proxy.
        assert_remote_not_plaintext(
            host=cfg.bind.host,
            use_tls=cfg.bind.use_tls,
            behind_tls_proxy=cfg.tls_proxy.enabled and cfg.bind.is_loopback,
        )
        if not cfg.bind.is_loopback and not cfg.bind.use_tls and not cfg.tls_proxy.enabled:
            raise PlaintextExposureRejected(
                "guarded launcher rejects remote plaintext Quack exposure"
            )

        duckdb_config = {
            "enable_external_access": (
                "true" if cfg.external_access.enable_external_access else "false"
            ),
            "autoinstall_known_extensions": "false",
            "autoload_known_extensions": "false",
            "lock_configuration": (
                "true" if cfg.external_access.lock_configuration else "false"
            ),
        }

        if isinstance(self._authenticator, FreshConnectionAuthenticator):
            auth_cb = self.AUTH_CALLBACK_NAME
        else:
            auth_cb = "default_deny_authentication"
        if isinstance(self._authorizer, ExactFullSqlAuthorizer):
            authz_cb = self.AUTHZ_CALLBACK_NAME
        else:
            authz_cb = "default_deny_authorization"

        pre_load = tuple(cfg.extensions.allowed_extensions)

        plan = GuardedServerPlan(
            profile_config=cfg,
            threat_model_identity=self._threat_model.identity_id(),
            authentication_callback=auth_cb,
            authorization_callback=authz_cb,
            pre_load_extensions=pre_load,
            duckdb_config=duckdb_config,
            audit_enabled=cfg.audit.enabled,
        )
        return plan

    @property
    def plan(self) -> GuardedServerPlan:
        return self._plan

    @property
    def config(self) -> QuackSecurityProfileConfig:
        return self._config

    @property
    def threat_model(self) -> QuackThreatModel:
        return self._threat_model

    @property
    def authenticator(self) -> FreshConnectionAuthenticator | DefaultDenyAuthenticator:
        return self._authenticator

    @property
    def authorizer(self) -> ExactFullSqlAuthorizer | DefaultDenyAuthorizer:
        return self._authorizer

    @property
    def capability_store(self) -> OneUseCapabilityStore:
        return self._store

    @property
    def audit_events(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._audit_events)

    def issue_operation_capability(
        self,
        *,
        operation_id: str,
        caller_identity: str,
        sql: str | None = None,
        resource: str = "",
        ttl_ms: int = DEFAULT_CAPABILITY_TTL_MS,
    ) -> OperationCapability:
        """Broker-side helper: issue a one-use capability for this profile."""

        sql_id = ""
        if sql is not None:
            if not isinstance(self._authorizer, ExactFullSqlAuthorizer):
                raise QuackSecurityError(
                    "cannot bind SQL to capability without ExactFullSqlAuthorizer"
                )
            sql_id = self._authorizer.register_exact_sql(operation_id, sql)
        return self._store.issue(
            operation_id=operation_id,
            profile=self._config.profile,
            caller_identity=caller_identity,
            ttl_ms=ttl_ms,
            sql_template_identity=sql_id,
            resource=resource,
            now_ms=self._clock_ms(),
        )

    def authenticate_fresh_connection(
        self,
        token: str,
        *,
        expected_operation_id: str | None = None,
    ) -> AuthenticatedSession:
        """Invoke the installed non-default (or default-deny) auth callback."""

        return self._authenticator.authenticate(
            token,
            expected_operation_id=expected_operation_id,
            now_ms=self._clock_ms(),
        )

    def authorize_sql(self, *, session_id: str, sql: str) -> Mapping[str, Any]:
        """Invoke the installed authorization callback for exact full SQL."""

        return self._authorizer.authorize(session_id=session_id, sql=sql)

    def assert_path_policy(self, path: str) -> None:
        self._config.local_paths.assert_permitted(path)

    def assert_egress_policy(
        self,
        *,
        host: str,
        port: int,
        use_tls: bool | None = None,
        path: str = "",
    ) -> None:
        self._config.egress.assert_permitted(
            host=host, port=port, use_tls=use_tls, path=path
        )

    def assert_extension_load(self, extension_name: str) -> None:
        self._config.extensions.assert_load_allowed(extension_name)

    def launch(self) -> Mapping[str, Any]:
        """Validate and materialize the guarded server plan.

        Without an injected runner this is a dry-run that returns a receipt.
        Catalog-owner plans always require non-default authentication.
        """

        plan = self._plan
        cfg = plan.profile_config

        # Final launch gates.
        if cfg.profile is QuackServerProfile.CATALOG_OWNER:
            if not isinstance(self._authenticator, FreshConnectionAuthenticator):
                raise QuackSecurityError(
                    "catalog owner launch requires non-default one-use "
                    "authentication callback"
                )
            if self._authenticator.is_default:
                raise QuackSecurityError(
                    "catalog owner authentication callback must not be default"
                )
            if not isinstance(self._authorizer, ExactFullSqlAuthorizer):
                raise QuackSecurityError(
                    "catalog owner launch requires exact full-SQL authorization"
                )
            # Pre-load only pinned extensions.
            for ext in CATALOG_OWNER_PINNED_EXTENSIONS:
                self.assert_extension_load(ext)

        if cfg.profile is QuackServerProfile.PUBLICATION_GATEWAY:
            # Publication reaches neither catalog paths nor object egress.
            if cfg.local_paths.allowed_paths:
                raise PolicyViolation(
                    "publication gateway must not reach local catalog paths"
                )
            if cfg.egress.allowed_endpoints:
                raise PolicyViolation(
                    "publication gateway must not reach object endpoints or TLS proxies"
                )
            for ext in CATALOG_OWNER_PINNED_EXTENSIONS:
                if cfg.extensions.permits_load(ext):
                    raise PolicyViolation(
                        f"publication gateway must not load catalog-owner extension {ext!r}"
                    )

        # Reject remote plaintext one more time at launch.
        assert_remote_not_plaintext(
            host=cfg.bind.host,
            use_tls=cfg.bind.use_tls,
            behind_tls_proxy=cfg.tls_proxy.enabled and cfg.bind.is_loopback,
        )

        receipt: dict[str, Any] = {
            "schema": QUACK_SERVER_LAUNCH_SCHEMA,
            "status": "planned",
            "plan": plan.to_dict(),
            "plan_identity": plan.identity_id(),
            "threat_model_identity": self._threat_model.identity_id(),
            "launched_at_ms": self._clock_ms(),
            "authentication_is_default": (
                self._authenticator.is_default
                if hasattr(self._authenticator, "is_default")
                else True
            ),
            "authorization_is_default": (
                self._authorizer.is_default
                if hasattr(self._authorizer, "is_default")
                else True
            ),
        }

        if self._runner is not None:
            result = self._runner(plan)
            receipt["status"] = "launched"
            receipt["runner_result"] = redact_sensitive(
                dict(result) if isinstance(result, Mapping) else {"result": result}
            )

        self._audit({"event": "server_launch", **receipt})
        return MappingProxyType(receipt)


def profiles_are_isolated(
    publication: QuackSecurityProfileConfig,
    catalog_owner: QuackSecurityProfileConfig,
) -> bool:
    """Return True if the two profiles have distinct policy surfaces."""

    if publication.profile is not QuackServerProfile.PUBLICATION_GATEWAY:
        return False
    if catalog_owner.profile is not QuackServerProfile.CATALOG_OWNER:
        return False
    # Distinct external access.
    if (
        publication.external_access.enable_external_access
        == catalog_owner.external_access.enable_external_access
        and publication.external_access.enable_external_access is True
    ):
        # Both enabled is not isolation for this pair; publication must be off.
        return False
    if publication.external_access.enable_external_access:
        return False
    # Distinct extensions.
    if set(publication.extensions.allowed_extensions) & set(
        catalog_owner.extensions.allowed_extensions
    ):
        return False
    # Distinct local paths: publication empty; owner has catalog path.
    if publication.local_paths.allowed_paths:
        return False
    if not catalog_owner.local_paths.allowed_paths:
        return False
    # Distinct filesystem.
    if publication.filesystem.allow_filesystem:
        return False
    if not catalog_owner.filesystem.allow_filesystem:
        return False
    # Distinct egress: publication empty; owner has endpoints.
    if publication.egress.allowed_endpoints:
        return False
    if not catalog_owner.egress.allowed_endpoints:
        return False
    # Distinct OS identities.
    if publication.os_identity.identity_name == catalog_owner.os_identity.identity_name:
        return False
    return True
