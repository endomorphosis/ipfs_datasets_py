"""Quack threat model and guarded server launcher (DQK-049).

Two explicit, non-inheriting process profiles:

* **Publication gateway** — sanitized snapshot projections for untrusted
  agents. Loopback bind by default, per-operation credentials, restricted OS
  identity, external access disabled, query authorization, audit, and a
  supported TLS reverse proxy for remote use. Reaches neither catalog files
  nor object-store endpoints.
* **Catalog owner** — internal DuckLake shard owner. Deny-by-default surface
  that pre-loads only pinned DuckLake/Quack/object extensions, restricts the
  local filesystem to the exact catalog path, permits egress only to the
  shard's exact object endpoint or TLS proxy, and installs non-default
  fresh-connection authentication plus exact full-SQL authorization callbacks.

Neither profile inherits ambient filesystem, extension, secret, or network
reachability. Default authentication and authorization are never permissive
for agent traffic. Tokens and full SQL text are treated as sensitive and are
never retained in log-safe views.

Importing this module is side-effect free: it never imports ``duckdb``, never
starts sockets or processes, never LOADs extensions, and never installs
packages. Launch plans are pure data; optional runtime hooks are injected.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Mapping, Sequence
from urllib.parse import urlparse

__all__ = [
    "QUACK_SECURITY_SCHEMA",
    "PINNED_CATALOG_OWNER_EXTENSIONS",
    "PINNED_PUBLICATION_EXTENSIONS",
    "DEFAULT_LOOPBACK_HOSTS",
    "DEFAULT_QUACK_PORT",
    "REDACTION_MARKER",
    "QuackSecurityError",
    "AuthenticationError",
    "AuthorizationError",
    "ExposureError",
    "CapabilityError",
    "ProfileMismatchError",
    "ServerProfile",
    "AuthenticationMode",
    "AuthorizationMode",
    "BindMode",
    "SensitiveClass",
    "ThreatId",
    "ThreatControl",
    "ThreatEntry",
    "QuackThreatModel",
    "QUACK_THREAT_MODEL",
    "ExternalAccessPolicy",
    "ExtensionPolicy",
    "LocalPathPolicy",
    "FilesystemPolicy",
    "EgressEndpoint",
    "EgressPolicy",
    "NetworkExposurePolicy",
    "AuthenticationPolicy",
    "AuthorizationPolicy",
    "OSIdentityPolicy",
    "AuditPolicy",
    "SensitiveDataPolicy",
    "ProfileSecurityPolicy",
    "OperationCapability",
    "OperationCapabilityStore",
    "AuthenticatedSession",
    "AuthenticationCallback",
    "AuthorizationCallback",
    "GuardedServerConfig",
    "GuardedLaunchPlan",
    "GuardedServerLauncher",
    "publication_gateway_policy",
    "catalog_owner_policy",
    "build_guarded_config",
    "assert_profiles_distinct",
    "reject_remote_plaintext",
    "is_loopback_host",
    "redact_token",
    "redact_sql",
    "classify_sensitive",
    "sensitive_log_view",
    "default_auth_is_permissive_for_agents",
    "default_authz_is_permissive_for_agents",
    "mint_operation_capability",
    "threat_model_summary",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

QUACK_SECURITY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-quack-security@1"
)

_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-049-quack-threat-model-guarded-launcher-20260810"
)

# Pinned extension sets (builds match DQK-002 / DQK-084 control-plane pins).
PINNED_CATALOG_OWNER_EXTENSIONS: Final[tuple[str, ...]] = (
    "quack@1.5.5+core",
    "ducklake@1.5.5+core",
    "httpfs@1.5.5+core",
)
PINNED_PUBLICATION_EXTENSIONS: Final[tuple[str, ...]] = (
    "quack@1.5.5+core",
)

DEFAULT_LOOPBACK_HOSTS: Final[frozenset[str]] = frozenset(
    {"127.0.0.1", "localhost", "::1"}
)
DEFAULT_QUACK_PORT: Final[int] = 5433
DEFAULT_CAPABILITY_TTL_MS: Final[int] = 30_000
DEFAULT_CAPABILITY_MAX_BYTES: Final[int] = 8_192
REDACTION_MARKER: Final[str] = "***REDACTED***"

# Quack SET keys for non-default auth/authz hooks (defense-in-depth surface).
QUACK_AUTHENTICATION_FUNCTION: Final[str] = "quack_authentication_function"
QUACK_AUTHORIZATION_FUNCTION: Final[str] = "quack_authorization_function"

# Callback identity tokens that must never equal Quack's default/permissive hooks.
NON_DEFAULT_AUTH_CALLBACK_NAME: Final[str] = (
    "ipfs_datasets_quack_one_use_capability_auth"
)
NON_DEFAULT_AUTHZ_CALLBACK_NAME: Final[str] = (
    "ipfs_datasets_quack_exact_sql_authz"
)
DEFAULT_PERMISSIVE_AUTH_HOOKS: Final[frozenset[str]] = frozenset(
    {"", "default", "none", "allow", "allow_all", "true", "1"}
)
DEFAULT_PERMISSIVE_AUTHZ_HOOKS: Final[frozenset[str]] = frozenset(
    {"", "default", "none", "allow", "allow_all", "true", "1", "prefix", "regex"}
)

_SAFE_PATH_RE = re.compile(r"^[^;\x00-\x1f]+$")
_HOST_RE = re.compile(
    r"^(?:localhost|(?:\d{1,3}\.){3}\d{1,3}|::1|"
    r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)$"
)
_TOKEN_INLINE_RE = re.compile(
    r"(?i)(\b(?:password|passwd|pwd|secret|token|api[_-]?key|authorization|"
    r"bearer|credential)\b\s*[=:]\s*)(['\"]?)([^'\"\s,;)]+)(\2)"
)
_SQL_LITERAL_TOKEN_RE = re.compile(
    r"(?i)(\b(?:password|token|secret|api_key)\b\s*=\s*)'[^']*'"
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class QuackSecurityError(ValueError):
    """Fail-closed Quack security policy rejection."""


class AuthenticationError(QuackSecurityError):
    """Fresh-connection authentication failed or capability was invalid."""


class AuthorizationError(QuackSecurityError):
    """Exact full-SQL authorization rejected the statement."""


class ExposureError(QuackSecurityError):
    """Remote plaintext or otherwise unsafe network exposure was rejected."""


class CapabilityError(QuackSecurityError):
    """One-use operation capability mint/consume failure."""


class ProfileMismatchError(QuackSecurityError):
    """A policy field is illegal for the selected server profile."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ServerProfile(str, Enum):
    """Closed set of Quack process profiles."""

    PUBLICATION_GATEWAY = "publication_gateway"
    CATALOG_OWNER = "catalog_owner"


class AuthenticationMode(str, Enum):
    """How a fresh Quack connection is authenticated.

    Default/permissive modes are never admitted for agent traffic.
    Catalog owners require a one-use capability callback or authenticating
    proxy; publication gateways use per-operation credentials under the same
    non-default callback surface.
    """

    DENY = "deny"
    ONE_USE_CAPABILITY_CALLBACK = "one_use_capability_callback"
    AUTHENTICATING_PROXY = "authenticating_proxy"


class AuthorizationMode(str, Enum):
    """How statements are authorized after authentication.

    Prefix and regex approximations are forbidden. Exact full-SQL matching
    against a broker-issued canonical template is the only allow path.
    """

    DENY_ALL = "deny_all"
    EXACT_FULL_SQL = "exact_full_sql"


class BindMode(str, Enum):
    """How the Quack listen address may be exposed."""

    LOOPBACK_ONLY = "loopback_only"
    TLS_REVERSE_PROXY = "tls_reverse_proxy"


class SensitiveClass(str, Enum):
    """Classification for tokens, SQL text, and related material."""

    PUBLIC = "public"
    SENSITIVE = "sensitive"
    SECRET = "secret"


class ThreatId(str, Enum):
    """Stable identifiers for the Quack threat catalog."""

    T1_PERMISSIVE_DEFAULT_AUTH = "T1_permissive_default_auth"
    T2_REUSABLE_TOKEN_AS_AUTHORITY = "T2_reusable_token_as_authority"
    T3_AGENT_CATALOG_REACH = "T3_agent_catalog_reach"
    T4_AMBIENT_EGRESS = "T4_ambient_egress"
    T5_REMOTE_PLAINTEXT = "T5_remote_plaintext"
    T6_TOKEN_SQL_LOG_LEAK = "T6_token_sql_log_leak"
    T7_EXTENSION_SMUGGLING = "T7_extension_smuggling"
    T8_PREFIX_AUTHZ_BYPASS = "T8_prefix_authz_bypass"


# ---------------------------------------------------------------------------
# Threat model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ThreatControl:
    """A concrete control that mitigates a threat."""

    control_id: str
    description: str
    profiles: tuple[ServerProfile, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "control_id": self.control_id,
            "description": self.description,
            "profiles": [p.value for p in self.profiles],
        }


@dataclass(frozen=True, slots=True)
class ThreatEntry:
    """One threat in the Quack threat catalog."""

    threat_id: ThreatId
    title: str
    description: str
    assets: tuple[str, ...]
    controls: tuple[ThreatControl, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "threat_id": self.threat_id.value,
            "title": self.title,
            "description": self.description,
            "assets": list(self.assets),
            "controls": [c.to_dict() for c in self.controls],
        }


@dataclass(frozen=True, slots=True)
class QuackThreatModel:
    """Structured threat model for Quack publication and catalog-owner surfaces."""

    schema: str
    assets: tuple[str, ...]
    trust_boundaries: tuple[str, ...]
    threats: tuple[ThreatEntry, ...]
    non_goals: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "assets": list(self.assets),
            "trust_boundaries": list(self.trust_boundaries),
            "threats": [t.to_dict() for t in self.threats],
            "non_goals": list(self.non_goals),
        }


def _build_threat_model() -> QuackThreatModel:
    both = (ServerProfile.PUBLICATION_GATEWAY, ServerProfile.CATALOG_OWNER)
    pub = (ServerProfile.PUBLICATION_GATEWAY,)
    owner = (ServerProfile.CATALOG_OWNER,)
    return QuackThreatModel(
        schema=QUACK_SECURITY_SCHEMA,
        assets=(
            "Reusable Quack endpoint token (broker-only)",
            "One-use operation capability",
            "Full SQL text of authorized operations",
            "DuckLake catalog metadata file and encrypted-file keys",
            "Object-store IAM credentials / short-lived storage capability",
            "Sanitized publication snapshot projections",
            "OS identity and network reachability of each profile",
        ),
        trust_boundaries=(
            "Trusted broker retains reusable tokens and mints one-use capabilities",
            "Identity-bound trusted worker receives only a one-use capability",
            "Untrusted agents reach only the sanitized publication gateway",
            "Catalog owner process is OS/network-isolated from the publication gateway",
            "TLS reverse proxy terminates remote clients; Quack itself stays loopback",
            "DuckLake is not the security boundary; broker + Quack callbacks are",
        ),
        threats=(
            ThreatEntry(
                threat_id=ThreatId.T1_PERMISSIVE_DEFAULT_AUTH,
                title="Permissive default authentication/authorization for agents",
                description=(
                    "Default Quack hooks or missing callbacks allow untrusted agent "
                    "traffic without per-operation credentials."
                ),
                assets=("One-use operation capability", "Full SQL text"),
                controls=(
                    ThreatControl(
                        "C1_default_deny",
                        "Default authentication and authorization modes are DENY; "
                        "agent traffic never inherits a permissive default.",
                        both,
                    ),
                    ThreatControl(
                        "C1_non_default_hooks",
                        "Profiles install non-default authentication and "
                        "authorization callback identities before admission.",
                        both,
                    ),
                ),
            ),
            ThreatEntry(
                threat_id=ThreatId.T2_REUSABLE_TOKEN_AS_AUTHORITY,
                title="Reusable server token used as per-operation authority",
                description=(
                    "Workers reuse the default server token across operations, "
                    "bypassing one-use capability consumption."
                ),
                assets=(
                    "Reusable Quack endpoint token (broker-only)",
                    "One-use operation capability",
                ),
                controls=(
                    ThreatControl(
                        "C2_one_use_capability",
                        "Fresh catalog-owner connections require atomic consumption "
                        "of a one-use operation capability via a non-default "
                        "authentication callback or authenticating proxy.",
                        owner,
                    ),
                    ThreatControl(
                        "C2_broker_retains_token",
                        "Reusable endpoint secrets remain inside the trusted broker; "
                        "workers receive only short-lived one-use capabilities.",
                        owner,
                    ),
                ),
            ),
            ThreatEntry(
                threat_id=ThreatId.T3_AGENT_CATALOG_REACH,
                title="Agent or publication gateway reaches live catalog files",
                description=(
                    "Publication processes open, mount, or read the DuckLake catalog "
                    "metadata file or companion registry."
                ),
                assets=("DuckLake catalog metadata file and encrypted-file keys",),
                controls=(
                    ThreatControl(
                        "C3_publication_no_catalog_path",
                        "Publication gateway local-path and filesystem policies are "
                        "empty; they reach neither the catalog path nor object storage.",
                        pub,
                    ),
                    ThreatControl(
                        "C3_owner_exact_catalog_path",
                        "Catalog owner filesystem access is restricted to the exact "
                        "local catalog path only.",
                        owner,
                    ),
                ),
            ),
            ThreatEntry(
                threat_id=ThreatId.T4_AMBIENT_EGRESS,
                title="Ambient filesystem, extension, or network reachability",
                description=(
                    "A profile inherits ambient directories, extension autoload, "
                    "or unrestricted network egress."
                ),
                assets=(
                    "Object-store IAM credentials / short-lived storage capability",
                    "OS identity and network reachability of each profile",
                ),
                controls=(
                    ThreatControl(
                        "C4_distinct_policies",
                        "Publication and catalog-owner profiles have distinct "
                        "external-access, extension, local-path, filesystem, and "
                        "egress policies; neither inherits ambient reachability.",
                        both,
                    ),
                    ThreatControl(
                        "C4_owner_exact_egress",
                        "Catalog owner egress is limited to the shard's exact object "
                        "endpoint or TLS proxy.",
                        owner,
                    ),
                ),
            ),
            ThreatEntry(
                threat_id=ThreatId.T5_REMOTE_PLAINTEXT,
                title="Remote plaintext Quack exposure",
                description=(
                    "Quack binds a non-loopback address without TLS or a supported "
                    "TLS reverse proxy."
                ),
                assets=("Reusable Quack endpoint token (broker-only)", "Full SQL text"),
                controls=(
                    ThreatControl(
                        "C5_reject_remote_plaintext",
                        "Remote plaintext exposure is rejected; remote clients must "
                        "terminate at a TLS reverse proxy while Quack stays loopback.",
                        both,
                    ),
                ),
            ),
            ThreatEntry(
                threat_id=ThreatId.T6_TOKEN_SQL_LOG_LEAK,
                title="Tokens or full SQL text leak into logs and receipts",
                description=(
                    "Tokens, credentials, or full SQL appear in DuckDB/Quack logs, "
                    "audit payloads, or exception text."
                ),
                assets=("One-use operation capability", "Full SQL text"),
                controls=(
                    ThreatControl(
                        "C6_sensitive_handling",
                        "Tokens and full SQL text are classified as sensitive/secret "
                        "and redacted from log-safe views and repr surfaces.",
                        both,
                    ),
                ),
            ),
            ThreatEntry(
                threat_id=ThreatId.T7_EXTENSION_SMUGGLING,
                title="Unpinned or automatic extension load",
                description=(
                    "Automatic install/load introduces unpinned extensions that "
                    "expand the attack surface."
                ),
                assets=("DuckLake catalog metadata file and encrypted-file keys",),
                controls=(
                    ThreatControl(
                        "C7_pinned_preload",
                        "Catalog owners pre-load only pinned DuckLake/Quack/object "
                        "extensions before locking configuration; publication loads "
                        "only pinned Quack.",
                        both,
                    ),
                ),
            ),
            ThreatEntry(
                threat_id=ThreatId.T8_PREFIX_AUTHZ_BYPASS,
                title="Prefix/regex authorization bypass",
                description=(
                    "Authorization uses prefix or regex matching instead of exact "
                    "full-SQL identity, allowing statement smuggling."
                ),
                assets=("Full SQL text of authorized operations",),
                controls=(
                    ThreatControl(
                        "C8_exact_full_sql",
                        "Authorization callback exact-allows only the broker's "
                        "canonical full SQL / template identity; prefix and regex "
                        "are forbidden.",
                        both,
                    ),
                ),
            ),
        ),
        non_goals=(
            "DuckLake role/GRANT ACL boundary (DuckLake is not the security boundary)",
            "High availability, replication, or multi-owner catalog semantics",
            "Production catalog mutation activation (held behind later promotion gates)",
            "Serving control, proof, or wallet authority catalogs over Quack",
        ),
    )


QUACK_THREAT_MODEL: Final[QuackThreatModel] = _build_threat_model()


def threat_model_summary() -> dict[str, Any]:
    """Return a serializable summary of the Quack threat model."""

    return QUACK_THREAT_MODEL.to_dict()


# ---------------------------------------------------------------------------
# Policy components
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExternalAccessPolicy:
    """DuckDB external-access and autoinstall/autoload surface."""

    enable_external_access: bool = False
    autoinstall_known_extensions: bool = False
    autoload_known_extensions: bool = False
    allow_unsigned_extensions: bool = False
    lock_configuration: bool = True

    def __post_init__(self) -> None:
        # Fail closed: agent/publication traffic never gets external access.
        if self.enable_external_access and not self.lock_configuration:
            raise QuackSecurityError(
                "enable_external_access requires lock_configuration=True"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enable_external_access": self.enable_external_access,
            "autoinstall_known_extensions": self.autoinstall_known_extensions,
            "autoload_known_extensions": self.autoload_known_extensions,
            "allow_unsigned_extensions": self.allow_unsigned_extensions,
            "lock_configuration": self.lock_configuration,
        }


@dataclass(frozen=True, slots=True)
class ExtensionPolicy:
    """Pinned extensions that may be pre-loaded; ambient load is denied."""

    pinned_builds: tuple[str, ...] = ()
    allow_automatic_install: bool = False
    allow_automatic_load: bool = False
    allow_ambient_extensions: bool = False
    load_before_configuration_lock: bool = True

    def __post_init__(self) -> None:
        if self.allow_automatic_install or self.allow_automatic_load:
            raise QuackSecurityError(
                "automatic extension install/load is forbidden for Quack profiles"
            )
        if self.allow_ambient_extensions:
            raise QuackSecurityError(
                "ambient extension inheritance is forbidden for Quack profiles"
            )
        builds = tuple(str(b).strip() for b in self.pinned_builds if str(b).strip())
        object.__setattr__(self, "pinned_builds", builds)

    def contains(self, build: str) -> bool:
        return str(build).strip() in self.pinned_builds

    def to_dict(self) -> dict[str, Any]:
        return {
            "pinned_builds": list(self.pinned_builds),
            "allow_automatic_install": self.allow_automatic_install,
            "allow_automatic_load": self.allow_automatic_load,
            "allow_ambient_extensions": self.allow_ambient_extensions,
            "load_before_configuration_lock": self.load_before_configuration_lock,
        }


@dataclass(frozen=True, slots=True)
class LocalPathPolicy:
    """Exact local filesystem paths the process may open."""

    allowed_paths: tuple[str, ...] = ()
    allow_ambient_paths: bool = False
    reject_network_filesystems: bool = True

    def __post_init__(self) -> None:
        if self.allow_ambient_paths:
            raise QuackSecurityError(
                "ambient filesystem path inheritance is forbidden"
            )
        paths: list[str] = []
        for raw in self.allowed_paths:
            path = str(raw or "").strip()
            if not path:
                continue
            if not _SAFE_PATH_RE.match(path):
                raise QuackSecurityError(f"unsafe local path {path!r}")
            lower = path.lower()
            if "://" in path or lower.startswith(
                ("s3:", "http:", "https:", "gs:", "az:", "nfs:", "smb:")
            ):
                raise QuackSecurityError(
                    f"remote/URI catalog paths are forbidden: {path!r}"
                )
            if self.reject_network_filesystems and any(
                token in lower
                for token in ("/nfs/", "\\nfs\\", "/smb/", "\\smb\\", "//")
            ):
                # Conservative reject for shared-mount style paths.
                if path.startswith("//") or path.startswith("\\\\"):
                    raise QuackSecurityError(
                        f"shared/network filesystem path rejected: {path!r}"
                    )
            paths.append(path)
        object.__setattr__(self, "allowed_paths", tuple(paths))

    def allows(self, path: str) -> bool:
        """Exact path match only (no prefix inheritance)."""

        candidate = str(path or "").strip()
        return candidate in self.allowed_paths

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_paths": list(self.allowed_paths),
            "allow_ambient_paths": self.allow_ambient_paths,
            "reject_network_filesystems": self.reject_network_filesystems,
        }


@dataclass(frozen=True, slots=True)
class FilesystemPolicy:
    """Whether general filesystem access is enabled and which paths apply."""

    allow_filesystem: bool = False
    local_paths: LocalPathPolicy = field(default_factory=LocalPathPolicy)
    allow_attach_arbitrary: bool = False
    allow_copy: bool = False
    allow_read_star: bool = False

    def __post_init__(self) -> None:
        if self.allow_attach_arbitrary or self.allow_copy or self.allow_read_star:
            raise QuackSecurityError(
                "arbitrary ATTACH/COPY/read_* surfaces are forbidden"
            )
        if self.allow_filesystem and not self.local_paths.allowed_paths:
            raise QuackSecurityError(
                "filesystem access requires at least one exact allowed path"
            )
        if not self.allow_filesystem and self.local_paths.allowed_paths:
            raise QuackSecurityError(
                "local paths require allow_filesystem=True"
            )

    def allows_path(self, path: str) -> bool:
        if not self.allow_filesystem:
            return False
        return self.local_paths.allows(path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_filesystem": self.allow_filesystem,
            "local_paths": self.local_paths.to_dict(),
            "allow_attach_arbitrary": self.allow_attach_arbitrary,
            "allow_copy": self.allow_copy,
            "allow_read_star": self.allow_read_star,
        }


@dataclass(frozen=True, slots=True)
class EgressEndpoint:
    """Exact host:port (and optional scheme) that may be contacted."""

    host: str
    port: int
    scheme: str = "https"
    role: str = "object_endpoint"  # object_endpoint | tls_proxy

    def __post_init__(self) -> None:
        host = str(self.host or "").strip().lower()
        if not host or not _HOST_RE.match(host):
            raise QuackSecurityError(f"invalid egress host {self.host!r}")
        if not isinstance(self.port, int) or isinstance(self.port, bool):
            raise QuackSecurityError("egress port must be an int")
        if self.port < 1 or self.port > 65_535:
            raise QuackSecurityError(f"egress port out of range: {self.port}")
        scheme = str(self.scheme or "https").strip().lower()
        if scheme not in {"https", "http", "s3", "tls"}:
            raise QuackSecurityError(f"unsupported egress scheme {scheme!r}")
        role = str(self.role or "object_endpoint").strip().lower()
        if role not in {"object_endpoint", "tls_proxy"}:
            raise QuackSecurityError(f"unsupported egress role {role!r}")
        # Object endpoints and TLS proxies must not be ambient open internet
        # without an explicit host; empty already rejected above.
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "scheme", scheme)
        object.__setattr__(self, "role", role)

    def authority(self) -> str:
        return f"{self.host}:{self.port}"

    def matches(self, host: str, port: int | None = None) -> bool:
        h = str(host or "").strip().lower()
        if h != self.host:
            return False
        if port is None:
            return True
        return int(port) == self.port

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "scheme": self.scheme,
            "role": self.role,
            "authority": self.authority(),
        }


@dataclass(frozen=True, slots=True)
class EgressPolicy:
    """Exact allowlist of network egress targets; ambient egress is denied."""

    allowed_endpoints: tuple[EgressEndpoint, ...] = ()
    allow_ambient_network: bool = False
    allow_dns_beyond_allowlist: bool = False

    def __post_init__(self) -> None:
        if self.allow_ambient_network:
            raise QuackSecurityError("ambient network egress is forbidden")
        if self.allow_dns_beyond_allowlist and self.allowed_endpoints:
            # Even with endpoints, broader DNS is not ambient reachability.
            pass
        if self.allow_dns_beyond_allowlist and not self.allowed_endpoints:
            raise QuackSecurityError(
                "DNS beyond allowlist requires at least one allowed endpoint"
            )
        endpoints = tuple(self.allowed_endpoints)
        for ep in endpoints:
            if not isinstance(ep, EgressEndpoint):
                raise QuackSecurityError("egress endpoints must be EgressEndpoint")
        object.__setattr__(self, "allowed_endpoints", endpoints)

    def allows(self, host: str, port: int | None = None) -> bool:
        return any(ep.matches(host, port) for ep in self.allowed_endpoints)

    def allows_url(self, url: str) -> bool:
        parsed = urlparse(str(url or "").strip())
        if not parsed.hostname:
            return False
        port = parsed.port
        if port is None:
            if parsed.scheme in {"https", "tls"}:
                port = 443
            elif parsed.scheme in {"http", "s3"}:
                port = 80
        return self.allows(parsed.hostname, port)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_endpoints": [e.to_dict() for e in self.allowed_endpoints],
            "allow_ambient_network": self.allow_ambient_network,
            "allow_dns_beyond_allowlist": self.allow_dns_beyond_allowlist,
        }


@dataclass(frozen=True, slots=True)
class NetworkExposurePolicy:
    """Listen-address and TLS reverse-proxy constraints."""

    bind_mode: BindMode = BindMode.LOOPBACK_ONLY
    bind_host: str = "127.0.0.1"
    bind_port: int = DEFAULT_QUACK_PORT
    require_tls_for_remote: bool = True
    tls_reverse_proxy_required_for_remote: bool = True
    allow_remote_plaintext: bool = False

    def __post_init__(self) -> None:
        host = str(self.bind_host or "").strip().lower()
        if not host or not _HOST_RE.match(host):
            raise QuackSecurityError(f"invalid bind host {self.bind_host!r}")
        if not isinstance(self.bind_port, int) or isinstance(self.bind_port, bool):
            raise QuackSecurityError("bind_port must be an int")
        if self.bind_port < 1 or self.bind_port > 65_535:
            raise QuackSecurityError(f"bind_port out of range: {self.bind_port}")
        if self.allow_remote_plaintext:
            raise QuackSecurityError("remote plaintext exposure is never allowed")
        object.__setattr__(self, "bind_host", host)
        if self.bind_mode is BindMode.LOOPBACK_ONLY:
            if not is_loopback_host(host):
                raise ExposureError(
                    f"loopback_only bind requires a loopback host, got {host!r}"
                )
        elif self.bind_mode is BindMode.TLS_REVERSE_PROXY:
            # Quack process itself still binds loopback; remote clients hit TLS proxy.
            if not is_loopback_host(host):
                raise ExposureError(
                    "TLS reverse-proxy mode still requires the Quack process "
                    f"to bind loopback, got {host!r}"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bind_mode": self.bind_mode.value,
            "bind_host": self.bind_host,
            "bind_port": self.bind_port,
            "require_tls_for_remote": self.require_tls_for_remote,
            "tls_reverse_proxy_required_for_remote": (
                self.tls_reverse_proxy_required_for_remote
            ),
            "allow_remote_plaintext": self.allow_remote_plaintext,
        }


@dataclass(frozen=True, slots=True)
class AuthenticationPolicy:
    """Fresh-connection authentication surface."""

    mode: AuthenticationMode = AuthenticationMode.DENY
    callback_name: str = ""
    per_operation_credentials: bool = True
    reusable_token_is_authority: bool = False
    require_non_default_callback: bool = True
    allow_agent_default_auth: bool = False

    def __post_init__(self) -> None:
        if self.allow_agent_default_auth:
            raise QuackSecurityError(
                "default authentication must never be permissive for agent traffic"
            )
        if self.reusable_token_is_authority:
            raise QuackSecurityError(
                "reusable server token must not be a per-operation authority"
            )
        if self.mode is AuthenticationMode.DENY:
            # Deny is always safe.
            return
        if self.mode in (
            AuthenticationMode.ONE_USE_CAPABILITY_CALLBACK,
            AuthenticationMode.AUTHENTICATING_PROXY,
        ):
            if not self.per_operation_credentials:
                raise QuackSecurityError(
                    "catalog/publication auth requires per-operation credentials"
                )
            name = str(self.callback_name or "").strip()
            if self.require_non_default_callback:
                if not name or name.lower() in DEFAULT_PERMISSIVE_AUTH_HOOKS:
                    raise QuackSecurityError(
                        "authentication requires a non-default callback name"
                    )
            object.__setattr__(self, "callback_name", name)

    def is_permissive_for_agents(self) -> bool:
        return False  # construction fails closed if permissive flags are set

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "callback_name": self.callback_name,
            "per_operation_credentials": self.per_operation_credentials,
            "reusable_token_is_authority": self.reusable_token_is_authority,
            "require_non_default_callback": self.require_non_default_callback,
            "allow_agent_default_auth": self.allow_agent_default_auth,
        }


@dataclass(frozen=True, slots=True)
class AuthorizationPolicy:
    """Statement authorization surface (exact full-SQL only)."""

    mode: AuthorizationMode = AuthorizationMode.DENY_ALL
    callback_name: str = ""
    allow_prefix_match: bool = False
    allow_regex_match: bool = False
    allow_agent_default_authz: bool = False
    require_non_default_callback: bool = True

    def __post_init__(self) -> None:
        if self.allow_agent_default_authz:
            raise QuackSecurityError(
                "default authorization must never be permissive for agent traffic"
            )
        if self.allow_prefix_match or self.allow_regex_match:
            raise QuackSecurityError(
                "prefix/regex authorization is forbidden; exact full-SQL only"
            )
        if self.mode is AuthorizationMode.DENY_ALL:
            return
        if self.mode is AuthorizationMode.EXACT_FULL_SQL:
            name = str(self.callback_name or "").strip()
            if self.require_non_default_callback:
                if not name or name.lower() in DEFAULT_PERMISSIVE_AUTHZ_HOOKS:
                    raise QuackSecurityError(
                        "authorization requires a non-default callback name"
                    )
            object.__setattr__(self, "callback_name", name)

    def is_permissive_for_agents(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "callback_name": self.callback_name,
            "allow_prefix_match": self.allow_prefix_match,
            "allow_regex_match": self.allow_regex_match,
            "allow_agent_default_authz": self.allow_agent_default_authz,
            "require_non_default_callback": self.require_non_default_callback,
        }


@dataclass(frozen=True, slots=True)
class OSIdentityPolicy:
    """Restricted OS identity expectations for the process."""

    restricted: bool = True
    dedicated_user: bool = True
    allow_root: bool = False
    drop_ambient_capabilities: bool = True
    identity_label: str = ""

    def __post_init__(self) -> None:
        if self.allow_root:
            raise QuackSecurityError("Quack profiles must not run as root")
        if not self.restricted:
            raise QuackSecurityError("OS identity must be restricted")
        label = str(self.identity_label or "").strip()
        object.__setattr__(self, "identity_label", label)

    def to_dict(self) -> dict[str, Any]:
        return {
            "restricted": self.restricted,
            "dedicated_user": self.dedicated_user,
            "allow_root": self.allow_root,
            "drop_ambient_capabilities": self.drop_ambient_capabilities,
            "identity_label": self.identity_label,
        }


@dataclass(frozen=True, slots=True)
class AuditPolicy:
    """Audit requirements for authentication and authorization decisions."""

    enabled: bool = True
    record_auth_events: bool = True
    record_authz_events: bool = True
    scrub_tokens: bool = True
    scrub_full_sql: bool = True

    def __post_init__(self) -> None:
        if not self.enabled:
            raise QuackSecurityError("audit must remain enabled for Quack profiles")
        if not self.scrub_tokens or not self.scrub_full_sql:
            raise QuackSecurityError(
                "audit records must scrub tokens and full SQL text"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "record_auth_events": self.record_auth_events,
            "record_authz_events": self.record_authz_events,
            "scrub_tokens": self.scrub_tokens,
            "scrub_full_sql": self.scrub_full_sql,
        }


@dataclass(frozen=True, slots=True)
class SensitiveDataPolicy:
    """How tokens and full SQL text are classified and redacted."""

    tokens_are_sensitive: bool = True
    full_sql_is_sensitive: bool = True
    redaction_marker: str = REDACTION_MARKER
    retain_full_sql_in_logs: bool = False
    retain_tokens_in_logs: bool = False

    def __post_init__(self) -> None:
        if not self.tokens_are_sensitive or not self.full_sql_is_sensitive:
            raise QuackSecurityError(
                "tokens and full SQL text must be handled as sensitive"
            )
        if self.retain_full_sql_in_logs or self.retain_tokens_in_logs:
            raise QuackSecurityError(
                "tokens and full SQL must not be retained in logs"
            )
        marker = str(self.redaction_marker or REDACTION_MARKER)
        object.__setattr__(self, "redaction_marker", marker)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tokens_are_sensitive": self.tokens_are_sensitive,
            "full_sql_is_sensitive": self.full_sql_is_sensitive,
            "redaction_marker": self.redaction_marker,
            "retain_full_sql_in_logs": self.retain_full_sql_in_logs,
            "retain_tokens_in_logs": self.retain_tokens_in_logs,
        }


@dataclass(frozen=True, slots=True)
class ProfileSecurityPolicy:
    """Complete security surface for one Quack server profile."""

    profile: ServerProfile
    external_access: ExternalAccessPolicy
    extensions: ExtensionPolicy
    filesystem: FilesystemPolicy
    egress: EgressPolicy
    network: NetworkExposurePolicy
    authentication: AuthenticationPolicy
    authorization: AuthorizationPolicy
    os_identity: OSIdentityPolicy
    audit: AuditPolicy
    sensitive: SensitiveDataPolicy

    def __post_init__(self) -> None:
        if self.profile is ServerProfile.PUBLICATION_GATEWAY:
            if self.external_access.enable_external_access:
                raise ProfileMismatchError(
                    "publication gateway must disable external access"
                )
            if self.filesystem.allow_filesystem or self.filesystem.local_paths.allowed_paths:
                raise ProfileMismatchError(
                    "publication gateway must not reach local catalog paths"
                )
            if self.egress.allowed_endpoints:
                raise ProfileMismatchError(
                    "publication gateway must not reach object endpoints or TLS proxies"
                )
            # Publication may only pin Quack, never DuckLake/object adapters.
            for build in self.extensions.pinned_builds:
                if "ducklake" in build or "httpfs" in build:
                    raise ProfileMismatchError(
                        "publication gateway must not pin DuckLake/object extensions"
                    )
        elif self.profile is ServerProfile.CATALOG_OWNER:
            if not self.external_access.enable_external_access:
                # Distinct from publication: owner may use exact allowlisted
                # external surfaces (path + object/TLS egress) only.
                raise ProfileMismatchError(
                    "catalog owner external access must be allowlisted-enabled "
                    "(never ambient); publication disables it entirely"
                )
            if not self.filesystem.allow_filesystem:
                raise ProfileMismatchError(
                    "catalog owner must allow its exact local catalog path"
                )
            if len(self.filesystem.local_paths.allowed_paths) != 1:
                raise ProfileMismatchError(
                    "catalog owner must allow exactly one local catalog path"
                )
            # Extensions must include the pinned owner set.
            pinned = set(self.extensions.pinned_builds)
            required = set(PINNED_CATALOG_OWNER_EXTENSIONS)
            if not required.issubset(pinned):
                raise ProfileMismatchError(
                    "catalog owner must pre-load pinned DuckLake/Quack/object extensions"
                )
            if self.authentication.mode not in (
                AuthenticationMode.ONE_USE_CAPABILITY_CALLBACK,
                AuthenticationMode.AUTHENTICATING_PROXY,
            ):
                raise ProfileMismatchError(
                    "catalog owner requires one-use capability authentication "
                    "via non-default callback or authenticating proxy"
                )
            if self.authorization.mode is not AuthorizationMode.EXACT_FULL_SQL:
                raise ProfileMismatchError(
                    "catalog owner requires exact full-SQL authorization"
                )
        else:  # pragma: no cover - enum exhaustive
            raise ProfileMismatchError(f"unknown profile {self.profile!r}")

        # Shared: defaults never permissive for agents.
        if self.authentication.is_permissive_for_agents():
            raise QuackSecurityError("authentication is permissive for agents")
        if self.authorization.is_permissive_for_agents():
            raise QuackSecurityError("authorization is permissive for agents")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": QUACK_SECURITY_SCHEMA,
            "profile": self.profile.value,
            "external_access": self.external_access.to_dict(),
            "extensions": self.extensions.to_dict(),
            "filesystem": self.filesystem.to_dict(),
            "egress": self.egress.to_dict(),
            "network": self.network.to_dict(),
            "authentication": self.authentication.to_dict(),
            "authorization": self.authorization.to_dict(),
            "os_identity": self.os_identity.to_dict(),
            "audit": self.audit.to_dict(),
            "sensitive": self.sensitive.to_dict(),
        }


# ---------------------------------------------------------------------------
# Profile factories
# ---------------------------------------------------------------------------


def publication_gateway_policy(
    *,
    bind_host: str = "127.0.0.1",
    bind_port: int = DEFAULT_QUACK_PORT,
    bind_mode: BindMode = BindMode.LOOPBACK_ONLY,
    identity_label: str = "quack-publication-gateway",
) -> ProfileSecurityPolicy:
    """Build the sanitized publication-gateway profile (deny external reach)."""

    return ProfileSecurityPolicy(
        profile=ServerProfile.PUBLICATION_GATEWAY,
        external_access=ExternalAccessPolicy(
            enable_external_access=False,
            autoinstall_known_extensions=False,
            autoload_known_extensions=False,
            allow_unsigned_extensions=False,
            lock_configuration=True,
        ),
        extensions=ExtensionPolicy(
            pinned_builds=PINNED_PUBLICATION_EXTENSIONS,
            allow_automatic_install=False,
            allow_automatic_load=False,
            allow_ambient_extensions=False,
            load_before_configuration_lock=True,
        ),
        filesystem=FilesystemPolicy(
            allow_filesystem=False,
            local_paths=LocalPathPolicy(allowed_paths=()),
            allow_attach_arbitrary=False,
            allow_copy=False,
            allow_read_star=False,
        ),
        egress=EgressPolicy(allowed_endpoints=()),
        network=NetworkExposurePolicy(
            bind_mode=bind_mode,
            bind_host=bind_host,
            bind_port=bind_port,
            require_tls_for_remote=True,
            tls_reverse_proxy_required_for_remote=True,
            allow_remote_plaintext=False,
        ),
        authentication=AuthenticationPolicy(
            mode=AuthenticationMode.ONE_USE_CAPABILITY_CALLBACK,
            callback_name=NON_DEFAULT_AUTH_CALLBACK_NAME,
            per_operation_credentials=True,
            reusable_token_is_authority=False,
            require_non_default_callback=True,
            allow_agent_default_auth=False,
        ),
        authorization=AuthorizationPolicy(
            mode=AuthorizationMode.EXACT_FULL_SQL,
            callback_name=NON_DEFAULT_AUTHZ_CALLBACK_NAME,
            allow_prefix_match=False,
            allow_regex_match=False,
            allow_agent_default_authz=False,
            require_non_default_callback=True,
        ),
        os_identity=OSIdentityPolicy(
            restricted=True,
            dedicated_user=True,
            allow_root=False,
            drop_ambient_capabilities=True,
            identity_label=identity_label,
        ),
        audit=AuditPolicy(
            enabled=True,
            record_auth_events=True,
            record_authz_events=True,
            scrub_tokens=True,
            scrub_full_sql=True,
        ),
        sensitive=SensitiveDataPolicy(
            tokens_are_sensitive=True,
            full_sql_is_sensitive=True,
            retain_full_sql_in_logs=False,
            retain_tokens_in_logs=False,
        ),
    )


def catalog_owner_policy(
    *,
    catalog_path: str,
    object_endpoint: EgressEndpoint | None = None,
    tls_proxy: EgressEndpoint | None = None,
    bind_host: str = "127.0.0.1",
    bind_port: int = DEFAULT_QUACK_PORT,
    bind_mode: BindMode = BindMode.LOOPBACK_ONLY,
    authentication_mode: AuthenticationMode = (
        AuthenticationMode.ONE_USE_CAPABILITY_CALLBACK
    ),
    identity_label: str = "quack-catalog-owner",
) -> ProfileSecurityPolicy:
    """Build the internal DuckLake catalog-owner profile (deny by default)."""

    path = str(catalog_path or "").strip()
    if not path:
        raise QuackSecurityError("catalog_path is required for catalog owner")

    endpoints: list[EgressEndpoint] = []
    if object_endpoint is not None:
        endpoints.append(object_endpoint)
    if tls_proxy is not None:
        endpoints.append(tls_proxy)
    if not endpoints:
        raise QuackSecurityError(
            "catalog owner requires at least one object endpoint or TLS proxy"
        )

    if authentication_mode not in (
        AuthenticationMode.ONE_USE_CAPABILITY_CALLBACK,
        AuthenticationMode.AUTHENTICATING_PROXY,
    ):
        raise QuackSecurityError(
            "catalog owner authentication must be one-use callback or proxy"
        )

    return ProfileSecurityPolicy(
        profile=ServerProfile.CATALOG_OWNER,
        external_access=ExternalAccessPolicy(
            # Catalog owner opens only exact path + egress allowlists (never
            # ambient). Publication keeps external access fully disabled, so
            # the external-access policy dimension remains distinct.
            enable_external_access=True,
            autoinstall_known_extensions=False,
            autoload_known_extensions=False,
            allow_unsigned_extensions=False,
            lock_configuration=True,
        ),
        extensions=ExtensionPolicy(
            pinned_builds=PINNED_CATALOG_OWNER_EXTENSIONS,
            allow_automatic_install=False,
            allow_automatic_load=False,
            allow_ambient_extensions=False,
            load_before_configuration_lock=True,
        ),
        filesystem=FilesystemPolicy(
            allow_filesystem=True,
            local_paths=LocalPathPolicy(allowed_paths=(path,)),
            allow_attach_arbitrary=False,
            allow_copy=False,
            allow_read_star=False,
        ),
        egress=EgressPolicy(allowed_endpoints=tuple(endpoints)),
        network=NetworkExposurePolicy(
            bind_mode=bind_mode,
            bind_host=bind_host,
            bind_port=bind_port,
            require_tls_for_remote=True,
            tls_reverse_proxy_required_for_remote=True,
            allow_remote_plaintext=False,
        ),
        authentication=AuthenticationPolicy(
            mode=authentication_mode,
            callback_name=NON_DEFAULT_AUTH_CALLBACK_NAME,
            per_operation_credentials=True,
            reusable_token_is_authority=False,
            require_non_default_callback=True,
            allow_agent_default_auth=False,
        ),
        authorization=AuthorizationPolicy(
            mode=AuthorizationMode.EXACT_FULL_SQL,
            callback_name=NON_DEFAULT_AUTHZ_CALLBACK_NAME,
            allow_prefix_match=False,
            allow_regex_match=False,
            allow_agent_default_authz=False,
            require_non_default_callback=True,
        ),
        os_identity=OSIdentityPolicy(
            restricted=True,
            dedicated_user=True,
            allow_root=False,
            drop_ambient_capabilities=True,
            identity_label=identity_label,
        ),
        audit=AuditPolicy(
            enabled=True,
            record_auth_events=True,
            record_authz_events=True,
            scrub_tokens=True,
            scrub_full_sql=True,
        ),
        sensitive=SensitiveDataPolicy(
            tokens_are_sensitive=True,
            full_sql_is_sensitive=True,
            retain_full_sql_in_logs=False,
            retain_tokens_in_logs=False,
        ),
    )


def assert_profiles_distinct(
    publication: ProfileSecurityPolicy,
    owner: ProfileSecurityPolicy,
) -> None:
    """Fail closed if publication and catalog-owner policies are not distinct."""

    if publication.profile is not ServerProfile.PUBLICATION_GATEWAY:
        raise ProfileMismatchError("first policy must be publication_gateway")
    if owner.profile is not ServerProfile.CATALOG_OWNER:
        raise ProfileMismatchError("second policy must be catalog_owner")

    dims = (
        ("external_access", publication.external_access.to_dict(), owner.external_access.to_dict()),
        ("extensions", publication.extensions.to_dict(), owner.extensions.to_dict()),
        ("local_path", publication.filesystem.local_paths.to_dict(), owner.filesystem.local_paths.to_dict()),
        ("filesystem", publication.filesystem.to_dict(), owner.filesystem.to_dict()),
        ("egress", publication.egress.to_dict(), owner.egress.to_dict()),
    )
    for name, left, right in dims:
        if left == right:
            raise ProfileMismatchError(
                f"publication and catalog-owner {name} policies must be distinct"
            )

    # Reachability guarantees.
    catalog_path = owner.filesystem.local_paths.allowed_paths[0]
    if publication.filesystem.allows_path(catalog_path):
        raise ProfileMismatchError(
            "publication gateway must not reach the catalog owner path"
        )
    for ep in owner.egress.allowed_endpoints:
        if publication.egress.allows(ep.host, ep.port):
            raise ProfileMismatchError(
                "publication gateway must not reach owner object endpoint/TLS proxy"
            )


# ---------------------------------------------------------------------------
# Host / exposure helpers
# ---------------------------------------------------------------------------


def is_loopback_host(host: str) -> bool:
    """Return True if ``host`` is a loopback identity."""

    h = str(host or "").strip().lower()
    if h in DEFAULT_LOOPBACK_HOSTS:
        return True
    if h.startswith("127."):
        return True
    return False


def reject_remote_plaintext(
    *,
    bind_host: str,
    use_tls: bool = False,
    behind_tls_reverse_proxy: bool = False,
) -> None:
    """Reject remote plaintext Quack exposure (fail closed).

    Loopback binds are always allowed. Non-loopback exposure requires TLS or
    a supported TLS reverse proxy in front of a loopback Quack process.
    """

    host = str(bind_host or "").strip().lower()
    if not host:
        raise ExposureError("bind host is required")
    if is_loopback_host(host):
        return
    if use_tls or behind_tls_reverse_proxy:
        # Direct non-loopback Quack without proxy is still unsafe for this
        # control plane: Quack must remain loopback and remote clients must
        # terminate at the TLS reverse proxy.
        raise ExposureError(
            "remote Quack process bind is rejected; bind loopback and terminate "
            "remote clients at a supported TLS reverse proxy"
        )
    raise ExposureError(
        f"remote plaintext Quack exposure rejected for host {host!r}"
    )


# ---------------------------------------------------------------------------
# Sensitive data handling
# ---------------------------------------------------------------------------


def redact_token(token: str | None, marker: str = REDACTION_MARKER) -> str:
    """Return a log-safe stand-in for a token or secret."""

    if not token:
        return ""
    return marker


def redact_sql(sql: str | None, marker: str = REDACTION_MARKER) -> str:
    """Redact full SQL text for logs while preserving a short fingerprint.

    Full SQL is sensitive: logs keep only a length and sha256 prefix, never
    the statement body.
    """

    if sql is None:
        return ""
    text = str(sql)
    if not text:
        return ""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"{marker}:sql_sha256={digest}:len={len(text)}"


def classify_sensitive(kind: str) -> SensitiveClass:
    """Classify a data kind as public, sensitive, or secret."""

    key = str(kind or "").strip().lower()
    if key in {
        "token",
        "password",
        "secret",
        "credential",
        "operation_capability",
        "bearer",
        "api_key",
    }:
        return SensitiveClass.SECRET
    if key in {"sql", "full_sql", "query", "statement", "authorization_template"}:
        return SensitiveClass.SENSITIVE
    return SensitiveClass.PUBLIC


def sensitive_log_view(
    *,
    token: str | None = None,
    sql: str | None = None,
    extra: Mapping[str, Any] | None = None,
    marker: str = REDACTION_MARKER,
) -> dict[str, Any]:
    """Build a log-safe mapping with tokens and full SQL redacted."""

    view: dict[str, Any] = {
        "token": redact_token(token, marker=marker) if token else "",
        "sql": redact_sql(sql, marker=marker) if sql else "",
        "token_class": classify_sensitive("token").value,
        "sql_class": classify_sensitive("full_sql").value,
    }
    if extra:
        for key, value in extra.items():
            k = str(key)
            cls = classify_sensitive(k)
            if cls is SensitiveClass.SECRET:
                view[k] = marker if value else ""
            elif cls is SensitiveClass.SENSITIVE:
                view[k] = redact_sql(str(value), marker=marker) if value else ""
            else:
                view[k] = value
    return view


def default_auth_is_permissive_for_agents() -> bool:
    """Default authentication is never permissive for agent traffic."""

    # The construction of default AuthenticationPolicy(mode=DENY) is the source of truth.
    return AuthenticationPolicy().is_permissive_for_agents()


def default_authz_is_permissive_for_agents() -> bool:
    """Default authorization is never permissive for agent traffic."""

    return AuthorizationPolicy().is_permissive_for_agents()


# ---------------------------------------------------------------------------
# One-use operation capabilities
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OperationCapability:
    """One-use, expiring capability injected into a trusted worker.

    The secret material is never included in ``repr`` / ``str``. The reusable
    server token is intentionally absent: this capability is the only fresh-
    connection authority for catalog-owner (and publication) sessions.
    """

    capability_id: str
    operation_id: str
    profile: ServerProfile
    secret: str
    expires_at_ms: int
    canonical_sql: str = ""
    session_binding: str = ""
    consumed: bool = False

    def __post_init__(self) -> None:
        cap_id = str(self.capability_id or "").strip()
        op_id = str(self.operation_id or "").strip()
        secret = str(self.secret or "")
        if not cap_id or not op_id:
            raise CapabilityError("capability_id and operation_id are required")
        if not secret or len(secret) < 16:
            raise CapabilityError("capability secret must be at least 16 characters")
        if len(secret) > DEFAULT_CAPABILITY_MAX_BYTES:
            raise CapabilityError("capability secret exceeds maximum length")
        if not isinstance(self.expires_at_ms, int) or self.expires_at_ms < 1:
            raise CapabilityError("expires_at_ms must be a positive int")
        object.__setattr__(self, "capability_id", cap_id)
        object.__setattr__(self, "operation_id", op_id)
        object.__setattr__(self, "secret", secret)
        object.__setattr__(self, "canonical_sql", str(self.canonical_sql or ""))
        object.__setattr__(self, "session_binding", str(self.session_binding or ""))

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"OperationCapability(capability_id={self.capability_id!r}, "
            f"operation_id={self.operation_id!r}, profile={self.profile.value!r}, "
            f"secret={REDACTION_MARKER}, expires_at_ms={self.expires_at_ms}, "
            f"canonical_sql={REDACTION_MARKER}, consumed={self.consumed})"
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.__repr__()

    def is_expired(self, now_ms: int | None = None) -> bool:
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        return now >= self.expires_at_ms

    def secret_fingerprint(self) -> str:
        return hashlib.sha256(self.secret.encode("utf-8")).hexdigest()[:16]

    def redacted_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "operation_id": self.operation_id,
            "profile": self.profile.value,
            "secret": REDACTION_MARKER,
            "expires_at_ms": self.expires_at_ms,
            "canonical_sql": redact_sql(self.canonical_sql) if self.canonical_sql else "",
            "session_binding": self.session_binding,
            "consumed": self.consumed,
            "secret_fingerprint": self.secret_fingerprint(),
        }


def mint_operation_capability(
    *,
    operation_id: str,
    profile: ServerProfile,
    canonical_sql: str = "",
    ttl_ms: int = DEFAULT_CAPABILITY_TTL_MS,
    now_ms: int | None = None,
    secret: str | None = None,
) -> OperationCapability:
    """Mint a fresh one-use operation capability (broker-side helper)."""

    if ttl_ms < 1:
        raise CapabilityError("ttl_ms must be positive")
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    return OperationCapability(
        capability_id=f"cap_{uuid.uuid4().hex}",
        operation_id=str(operation_id).strip(),
        profile=profile,
        secret=secret or secrets.token_urlsafe(32),
        expires_at_ms=now + int(ttl_ms),
        canonical_sql=str(canonical_sql or ""),
        session_binding="",
        consumed=False,
    )


class OperationCapabilityStore:
    """Thread-safe store that atomically consumes one-use capabilities."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_id: dict[str, OperationCapability] = {}
        # secret fingerprint -> capability_id for constant-ish lookup
        self._by_secret: dict[str, str] = {}

    def insert(self, capability: OperationCapability) -> None:
        if not isinstance(capability, OperationCapability):
            raise CapabilityError("expected OperationCapability")
        if capability.consumed:
            raise CapabilityError("cannot insert an already-consumed capability")
        with self._lock:
            if capability.capability_id in self._by_id:
                raise CapabilityError(
                    f"duplicate capability_id {capability.capability_id!r}"
                )
            fp = capability.secret_fingerprint()
            if fp in self._by_secret:
                raise CapabilityError("duplicate capability secret fingerprint")
            self._by_id[capability.capability_id] = capability
            self._by_secret[fp] = capability.capability_id

    def get(self, capability_id: str) -> OperationCapability | None:
        with self._lock:
            return self._by_id.get(str(capability_id))

    def consume(
        self,
        *,
        secret: str,
        profile: ServerProfile | None = None,
        now_ms: int | None = None,
        session_id: str | None = None,
    ) -> OperationCapability:
        """Atomically consume a capability by secret. Fail closed on reuse/expiry."""

        presented = str(secret or "")
        if not presented:
            raise AuthenticationError("missing operation capability")
        fp = hashlib.sha256(presented.encode("utf-8")).hexdigest()[:16]
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        with self._lock:
            cap_id = self._by_secret.get(fp)
            if cap_id is None:
                raise AuthenticationError("unknown or already-consumed capability")
            cap = self._by_id.get(cap_id)
            if cap is None:
                raise AuthenticationError("unknown or already-consumed capability")
            if cap.consumed:
                raise AuthenticationError("capability already consumed")
            if not hmac.compare_digest(cap.secret, presented):
                raise AuthenticationError("capability secret mismatch")
            if cap.is_expired(now):
                # Expire and remove.
                self._drop_locked(cap)
                raise AuthenticationError("capability expired")
            if profile is not None and cap.profile is not profile:
                raise AuthenticationError(
                    f"capability profile mismatch: {cap.profile.value} != {profile.value}"
                )
            session = str(session_id or f"sess_{uuid.uuid4().hex}")
            consumed = replace(
                cap,
                consumed=True,
                session_binding=session,
            )
            self._by_id[cap_id] = consumed
            # Remove secret index so the same secret cannot be presented again.
            self._by_secret.pop(fp, None)
            return consumed

    def _drop_locked(self, cap: OperationCapability) -> None:
        self._by_id.pop(cap.capability_id, None)
        self._by_secret.pop(cap.secret_fingerprint(), None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._by_id)


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """Session established after non-default fresh-connection authentication."""

    session_id: str
    operation_id: str
    capability_id: str
    profile: ServerProfile
    canonical_sql: str
    authenticated_at_ms: int

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"AuthenticatedSession(session_id={self.session_id!r}, "
            f"operation_id={self.operation_id!r}, "
            f"capability_id={self.capability_id!r}, "
            f"profile={self.profile.value!r}, "
            f"canonical_sql={REDACTION_MARKER}, "
            f"authenticated_at_ms={self.authenticated_at_ms})"
        )

    def redacted_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "operation_id": self.operation_id,
            "capability_id": self.capability_id,
            "profile": self.profile.value,
            "canonical_sql": redact_sql(self.canonical_sql),
            "authenticated_at_ms": self.authenticated_at_ms,
        }


class AuthenticationCallback:
    """Non-default quack_authentication_function implementation.

    Atomically consumes a one-use operation capability on each fresh
    connection and binds the authenticated session ID for subsequent
    authorization. Missing, reused, expired, or default-hook credentials fail
    closed.
    """

    def __init__(
        self,
        store: OperationCapabilityStore,
        *,
        profile: ServerProfile,
        policy: AuthenticationPolicy,
        name: str = NON_DEFAULT_AUTH_CALLBACK_NAME,
    ) -> None:
        if not isinstance(store, OperationCapabilityStore):
            raise QuackSecurityError("store must be OperationCapabilityStore")
        if policy.mode not in (
            AuthenticationMode.ONE_USE_CAPABILITY_CALLBACK,
            AuthenticationMode.AUTHENTICATING_PROXY,
        ):
            raise QuackSecurityError(
                "authentication callback requires one-use or proxy mode"
            )
        callback_name = str(name or policy.callback_name or "").strip()
        if not callback_name or callback_name.lower() in DEFAULT_PERMISSIVE_AUTH_HOOKS:
            raise QuackSecurityError("authentication callback name must be non-default")
        self._store = store
        self._profile = profile
        self._policy = policy
        self.name = callback_name
        self._sessions: dict[str, AuthenticatedSession] = {}
        self._lock = threading.RLock()
        self._audit: list[dict[str, Any]] = []

    @property
    def is_default(self) -> bool:
        return self.name.lower() in DEFAULT_PERMISSIVE_AUTH_HOOKS

    def authenticate(
        self,
        *,
        capability_secret: str,
        now_ms: int | None = None,
    ) -> AuthenticatedSession:
        if self.is_default:
            raise AuthenticationError("default authentication callback is forbidden")
        consumed = self._store.consume(
            secret=capability_secret,
            profile=self._profile,
            now_ms=now_ms,
        )
        session = AuthenticatedSession(
            session_id=consumed.session_binding,
            operation_id=consumed.operation_id,
            capability_id=consumed.capability_id,
            profile=consumed.profile,
            canonical_sql=consumed.canonical_sql,
            authenticated_at_ms=int(time.time() * 1000) if now_ms is None else int(now_ms),
        )
        with self._lock:
            self._sessions[session.session_id] = session
            self._audit.append(
                sensitive_log_view(
                    token=capability_secret,
                    sql=session.canonical_sql,
                    extra={
                        "event": "authenticate",
                        "session_id": session.session_id,
                        "operation_id": session.operation_id,
                        "capability_id": session.capability_id,
                        "result": "allow",
                    },
                )
            )
        return session

    def get_session(self, session_id: str) -> AuthenticatedSession | None:
        with self._lock:
            return self._sessions.get(str(session_id))

    def audit_events(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(self._audit)


class AuthorizationCallback:
    """Non-default quack_authorization_function (exact full-SQL only).

    Sees connection identity and full SQL text. Exact-allows only the
    broker-bound canonical SQL for the authenticated session; prefix and
    regex approximations are rejected by construction.
    """

    def __init__(
        self,
        auth: AuthenticationCallback,
        *,
        policy: AuthorizationPolicy,
        name: str = NON_DEFAULT_AUTHZ_CALLBACK_NAME,
    ) -> None:
        if policy.mode is not AuthorizationMode.EXACT_FULL_SQL:
            raise QuackSecurityError("authorization callback requires EXACT_FULL_SQL")
        if policy.allow_prefix_match or policy.allow_regex_match:
            raise QuackSecurityError("prefix/regex authorization is forbidden")
        callback_name = str(name or policy.callback_name or "").strip()
        if not callback_name or callback_name.lower() in DEFAULT_PERMISSIVE_AUTHZ_HOOKS:
            raise QuackSecurityError("authorization callback name must be non-default")
        self._auth = auth
        self._policy = policy
        self.name = callback_name
        self._lock = threading.RLock()
        self._audit: list[dict[str, Any]] = []

    @property
    def is_default(self) -> bool:
        return self.name.lower() in DEFAULT_PERMISSIVE_AUTHZ_HOOKS

    def authorize(
        self,
        *,
        session_id: str,
        sql: str,
    ) -> bool:
        if self.is_default:
            raise AuthorizationError("default authorization callback is forbidden")
        session = self._auth.get_session(session_id)
        if session is None:
            self._record(session_id, sql, allow=False, reason="unknown_session")
            raise AuthorizationError("unknown or unauthenticated session")
        presented = str(sql or "")
        expected = session.canonical_sql
        if not expected:
            self._record(session_id, sql, allow=False, reason="no_canonical_sql")
            raise AuthorizationError("session has no canonical SQL binding")
        # Exact full-SQL match only (no strip beyond trailing whitespace normalization
        # of complete statement identity — still not a prefix match).
        if presented != expected:
            # Also reject if caller attempts prefix smuggling.
            if expected.startswith(presented) or presented.startswith(expected):
                self._record(session_id, sql, allow=False, reason="prefix_rejected")
                raise AuthorizationError(
                    "authorization requires exact full-SQL identity; prefix denied"
                )
            self._record(session_id, sql, allow=False, reason="sql_mismatch")
            raise AuthorizationError("SQL does not match authorized template")
        self._record(session_id, sql, allow=True, reason="exact_match")
        return True

    def _record(
        self,
        session_id: str,
        sql: str,
        *,
        allow: bool,
        reason: str,
    ) -> None:
        with self._lock:
            self._audit.append(
                sensitive_log_view(
                    sql=sql,
                    extra={
                        "event": "authorize",
                        "session_id": session_id,
                        "result": "allow" if allow else "deny",
                        "reason": reason,
                    },
                )
            )

    def audit_events(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(self._audit)


# ---------------------------------------------------------------------------
# Guarded server launcher
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GuardedServerConfig:
    """Inputs required to build a guarded Quack launch plan."""

    policy: ProfileSecurityPolicy
    catalog_path: str = ""
    object_endpoint: EgressEndpoint | None = None
    tls_proxy: EgressEndpoint | None = None

    def __post_init__(self) -> None:
        if self.policy.profile is ServerProfile.CATALOG_OWNER:
            path = str(self.catalog_path or "").strip()
            if not path:
                # Fall back to the single allowed path on the policy.
                paths = self.policy.filesystem.local_paths.allowed_paths
                if len(paths) != 1:
                    raise QuackSecurityError(
                        "catalog owner config requires catalog_path"
                    )
                object.__setattr__(self, "catalog_path", paths[0])
            else:
                if not self.policy.filesystem.allows_path(path):
                    raise QuackSecurityError(
                        "catalog_path is not the policy's exact allowed path"
                    )
                object.__setattr__(self, "catalog_path", path)
        else:
            if self.catalog_path:
                raise QuackSecurityError(
                    "publication gateway must not configure a catalog_path"
                )
            if self.object_endpoint is not None or self.tls_proxy is not None:
                raise QuackSecurityError(
                    "publication gateway must not configure object endpoint/TLS proxy"
                )


@dataclass(frozen=True, slots=True)
class GuardedLaunchPlan:
    """Pure launch plan for a guarded Quack process (no side effects)."""

    schema: str
    profile: ServerProfile
    policy: ProfileSecurityPolicy
    bind_host: str
    bind_port: int
    duckdb_settings: Mapping[str, str]
    extension_load_order: tuple[str, ...]
    authentication_callback: str
    authorization_callback: str
    catalog_path: str
    allowed_egress: tuple[dict[str, Any], ...]
    os_identity_label: str
    threat_model_schema: str
    implementation_generation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "profile": self.profile.value,
            "policy": self.policy.to_dict(),
            "bind_host": self.bind_host,
            "bind_port": self.bind_port,
            "duckdb_settings": dict(self.duckdb_settings),
            "extension_load_order": list(self.extension_load_order),
            "authentication_callback": self.authentication_callback,
            "authorization_callback": self.authorization_callback,
            "catalog_path": self.catalog_path,
            "allowed_egress": list(self.allowed_egress),
            "os_identity_label": self.os_identity_label,
            "threat_model_schema": self.threat_model_schema,
            "implementation_generation": self.implementation_generation,
        }

    def security_statements(self) -> tuple[str, ...]:
        """Ordered SET statements that materialize the hardened surface."""

        stmts: list[str] = []
        for key, value in self.duckdb_settings.items():
            if key in {
                QUACK_AUTHENTICATION_FUNCTION,
                QUACK_AUTHORIZATION_FUNCTION,
            }:
                stmts.append(f"SET {key}='{value}'")
            else:
                stmts.append(f"SET {key}={value}")
        if self.policy.external_access.lock_configuration:
            stmts.append("SET lock_configuration=true")
        return tuple(stmts)


def build_guarded_config(
    profile: ServerProfile,
    *,
    catalog_path: str = "",
    object_host: str = "",
    object_port: int = 443,
    tls_proxy_host: str = "",
    tls_proxy_port: int = 443,
    bind_host: str = "127.0.0.1",
    bind_port: int = DEFAULT_QUACK_PORT,
    authentication_mode: AuthenticationMode = (
        AuthenticationMode.ONE_USE_CAPABILITY_CALLBACK
    ),
) -> GuardedServerConfig:
    """Factory for a validated guarded-server configuration."""

    if profile is ServerProfile.PUBLICATION_GATEWAY:
        policy = publication_gateway_policy(
            bind_host=bind_host,
            bind_port=bind_port,
        )
        return GuardedServerConfig(policy=policy)

    object_ep: EgressEndpoint | None = None
    tls_ep: EgressEndpoint | None = None
    if object_host:
        object_ep = EgressEndpoint(
            host=object_host,
            port=object_port,
            scheme="https",
            role="object_endpoint",
        )
    if tls_proxy_host:
        tls_ep = EgressEndpoint(
            host=tls_proxy_host,
            port=tls_proxy_port,
            scheme="tls",
            role="tls_proxy",
        )
    policy = catalog_owner_policy(
        catalog_path=catalog_path,
        object_endpoint=object_ep,
        tls_proxy=tls_ep,
        bind_host=bind_host,
        bind_port=bind_port,
        authentication_mode=authentication_mode,
    )
    return GuardedServerConfig(
        policy=policy,
        catalog_path=catalog_path,
        object_endpoint=object_ep,
        tls_proxy=tls_ep,
    )


class GuardedServerLauncher:
    """Builds and attests guarded Quack launch plans for either profile.

    Does not start processes or open sockets. Callers supply optional
    runtime hooks when they later apply a plan to a real DuckDB handle.
    """

    def __init__(
        self,
        *,
        capability_store: OperationCapabilityStore | None = None,
    ) -> None:
        self.capability_store = capability_store or OperationCapabilityStore()
        self._auth_callbacks: dict[str, AuthenticationCallback] = {}
        self._authz_callbacks: dict[str, AuthorizationCallback] = {}
        self._lock = threading.RLock()

    def plan(self, config: GuardedServerConfig) -> GuardedLaunchPlan:
        """Validate exposure and materialize a pure launch plan."""

        policy = config.policy
        reject_remote_plaintext(
            bind_host=policy.network.bind_host,
            use_tls=False,
            behind_tls_reverse_proxy=(
                policy.network.bind_mode is BindMode.TLS_REVERSE_PROXY
            ),
        )

        settings: dict[str, str] = {
            "enable_external_access": (
                "true" if policy.external_access.enable_external_access else "false"
            ),
            "autoinstall_known_extensions": (
                "true"
                if policy.external_access.autoinstall_known_extensions
                else "false"
            ),
            "autoload_known_extensions": (
                "true"
                if policy.external_access.autoload_known_extensions
                else "false"
            ),
            "allow_unsigned_extensions": (
                "true"
                if policy.external_access.allow_unsigned_extensions
                else "false"
            ),
            QUACK_AUTHENTICATION_FUNCTION: policy.authentication.callback_name,
            QUACK_AUTHORIZATION_FUNCTION: policy.authorization.callback_name,
        }

        # Extension load order: names without build suffix, in pin order.
        load_order = tuple(
            build.split("@", 1)[0] for build in policy.extensions.pinned_builds
        )

        return GuardedLaunchPlan(
            schema=QUACK_SECURITY_SCHEMA,
            profile=policy.profile,
            policy=policy,
            bind_host=policy.network.bind_host,
            bind_port=policy.network.bind_port,
            duckdb_settings=MappingProxyType(settings),
            extension_load_order=load_order,
            authentication_callback=policy.authentication.callback_name,
            authorization_callback=policy.authorization.callback_name,
            catalog_path=config.catalog_path if policy.profile is ServerProfile.CATALOG_OWNER else "",
            allowed_egress=tuple(ep.to_dict() for ep in policy.egress.allowed_endpoints),
            os_identity_label=policy.os_identity.identity_label,
            threat_model_schema=QUACK_THREAT_MODEL.schema,
            implementation_generation=_IMPLEMENTATION_GENERATION,
        )

    def install_callbacks(
        self,
        plan: GuardedLaunchPlan,
    ) -> tuple[AuthenticationCallback, AuthorizationCallback]:
        """Install non-default auth/authz callbacks for ``plan.profile``."""

        if plan.authentication_callback.lower() in DEFAULT_PERMISSIVE_AUTH_HOOKS:
            raise AuthenticationError("refusing to install default auth callback")
        if plan.authorization_callback.lower() in DEFAULT_PERMISSIVE_AUTHZ_HOOKS:
            raise AuthorizationError("refusing to install default authz callback")

        auth = AuthenticationCallback(
            self.capability_store,
            profile=plan.profile,
            policy=plan.policy.authentication,
            name=plan.authentication_callback,
        )
        authz = AuthorizationCallback(
            auth,
            policy=plan.policy.authorization,
            name=plan.authorization_callback,
        )
        key = plan.profile.value
        with self._lock:
            self._auth_callbacks[key] = auth
            self._authz_callbacks[key] = authz
        return auth, authz

    def authenticate_fresh_connection(
        self,
        profile: ServerProfile,
        *,
        capability_secret: str,
        now_ms: int | None = None,
    ) -> AuthenticatedSession:
        """Authenticate a fresh connection via the installed non-default callback."""

        with self._lock:
            auth = self._auth_callbacks.get(profile.value)
        if auth is None:
            raise AuthenticationError(
                f"no authentication callback installed for {profile.value}"
            )
        return auth.authenticate(
            capability_secret=capability_secret,
            now_ms=now_ms,
        )

    def authorize_sql(
        self,
        profile: ServerProfile,
        *,
        session_id: str,
        sql: str,
    ) -> bool:
        """Authorize full SQL via the installed exact-match callback."""

        with self._lock:
            authz = self._authz_callbacks.get(profile.value)
        if authz is None:
            raise AuthorizationError(
                f"no authorization callback installed for {profile.value}"
            )
        return authz.authorize(session_id=session_id, sql=sql)

    def mint_and_register(
        self,
        *,
        operation_id: str,
        profile: ServerProfile,
        canonical_sql: str,
        ttl_ms: int = DEFAULT_CAPABILITY_TTL_MS,
        now_ms: int | None = None,
    ) -> OperationCapability:
        """Broker helper: mint a capability and insert it into the store."""

        cap = mint_operation_capability(
            operation_id=operation_id,
            profile=profile,
            canonical_sql=canonical_sql,
            ttl_ms=ttl_ms,
            now_ms=now_ms,
        )
        self.capability_store.insert(cap)
        return cap
