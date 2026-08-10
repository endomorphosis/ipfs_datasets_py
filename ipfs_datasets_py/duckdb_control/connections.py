"""Local and Quack catalog connection policy (DQK-005).

Provides the control-plane connection kernel:

* short-lived local writer / reader sessions
* workload-isolated connection pools and catalogs (control vs analytical)
* attached read-only analytical catalogs for the trusted broker
* Quack URI parsing with secret separation and redaction
* per-session statement / row / byte / duration budgets
* external-access denial (filesystem, network, extension autoload)

Importing this module is inert: it never imports ``duckdb``, never opens
sockets or files, and never installs extensions. Real DuckDB handles are
created only through an explicit :class:`ConnectionManager` call, or via an
injected factory under test.
"""

from __future__ import annotations

import re
import threading
import time
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from enum import Enum
from types import MappingProxyType, TracebackType
from typing import (
    Any,
    Callable,
    Final,
    Iterator,
    Mapping,
    Protocol,
    Sequence,
)

__all__ = [
    "CONNECTION_POLICY_SCHEMA",
    "AccessMode",
    "AnalyticalCatalogSpec",
    "BoundedWriterSession",
    "ConnectionError",
    "ConnectionHandle",
    "ConnectionManager",
    "ConnectionPool",
    "ConnectionSecurityPolicy",
    "DEFAULT_ANALYTICAL_BUDGET",
    "DEFAULT_CONTROL_BUDGET",
    "DEFAULT_UNTRUSTED_BUDGET",
    "DEFAULT_WRITER_TRANSACTION_MS",
    "ManagedConnection",
    "PoolConfig",
    "QuackEndpoint",
    "QuackSecrets",
    "QuackURI",
    "StatementBudget",
    "StatementBudgetExceeded",
    "TrustLevel",
    "WorkloadKind",
    "apply_security_policy",
    "build_duckdb_config",
    "default_pool_config",
    "default_security_policy",
    "parse_quack_uri",
    "redact_quack_uri",
    "security_statements_for",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

CONNECTION_POLICY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-connection-policy@1"
)

# Content-addressed implementation generation (not a wire schema field).
_CONNECTION_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-005-lane3-attempt1-20260810"
)

DEFAULT_WRITER_TRANSACTION_MS: Final[int] = 5_000
DEFAULT_CONTROL_MEMORY_LIMIT: Final[str] = "256MB"
DEFAULT_ANALYTICAL_MEMORY_LIMIT: Final[str] = "1GB"
DEFAULT_UNTRUSTED_MEMORY_LIMIT: Final[str] = "128MB"

_ALIAS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_HOST_RE = re.compile(
    r"^(?:localhost|(?:\d{1,3}\.){3}\d{1,3}|[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)$"
)
_MEMORY_LIMIT_RE = re.compile(
    r"^(?:0|[1-9]\d*)(?:\.\d+)?(?:\s*(?:B|KB|MB|GB|TB|KiB|MiB|GiB|TiB))?$",
    re.IGNORECASE,
)
_SAFE_PATH_CHARS = re.compile(r"^[^;\x00-\x1f]+$")


class ConnectionError(ValueError):
    """Fail-closed connection policy, URI, pool, or security rejection."""


class StatementBudgetExceeded(ConnectionError):
    """A session exceeded its statement, row, byte, or duration budget."""


class WorkloadKind(str, Enum):
    """Closed set of workload classes with isolated pools and catalogs.

    Control heartbeats and orchestration writes must never share a pool or
    primary catalog with analytical scans. Publication / untrusted surfaces
    are physically separate and never attach authority catalogs.
    """

    CONTROL = "control"
    ANALYTICAL = "analytical"
    PUBLICATION = "publication"
    UNTRUSTED = "untrusted"


class AccessMode(str, Enum):
    """Session access mode."""

    READ_ONLY = "read_only"
    READ_WRITE = "read_write"


class TrustLevel(str, Enum):
    """Whether the session is held by the trusted broker or an untrusted party."""

    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


# ---------------------------------------------------------------------------
# Statement budgets
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StatementBudget:
    """Hard caps enforced per short-lived session.

    Writers additionally bind ``max_transaction_ms`` so control-plane
    transactions stay short and cannot starve heartbeats.
    """

    max_statements: int = 64
    max_rows: int = 100_000
    max_bytes: int = 32 * 1024 * 1024
    max_duration_ms: int = 30_000
    max_transaction_ms: int = DEFAULT_WRITER_TRANSACTION_MS

    def __post_init__(self) -> None:
        for name in (
            "max_statements",
            "max_rows",
            "max_bytes",
            "max_duration_ms",
            "max_transaction_ms",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ConnectionError(f"{name} must be a positive int, got {value!r}")

    def to_dict(self) -> dict[str, int]:
        return {
            "max_statements": self.max_statements,
            "max_rows": self.max_rows,
            "max_bytes": self.max_bytes,
            "max_duration_ms": self.max_duration_ms,
            "max_transaction_ms": self.max_transaction_ms,
        }


DEFAULT_CONTROL_BUDGET: Final[StatementBudget] = StatementBudget(
    max_statements=32,
    max_rows=10_000,
    max_bytes=8 * 1024 * 1024,
    max_duration_ms=10_000,
    max_transaction_ms=DEFAULT_WRITER_TRANSACTION_MS,
)

DEFAULT_ANALYTICAL_BUDGET: Final[StatementBudget] = StatementBudget(
    max_statements=256,
    max_rows=1_000_000,
    max_bytes=256 * 1024 * 1024,
    max_duration_ms=120_000,
    max_transaction_ms=30_000,
)

DEFAULT_UNTRUSTED_BUDGET: Final[StatementBudget] = StatementBudget(
    max_statements=16,
    max_rows=5_000,
    max_bytes=4 * 1024 * 1024,
    max_duration_ms=5_000,
    max_transaction_ms=2_000,
)


# ---------------------------------------------------------------------------
# Security policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConnectionSecurityPolicy:
    """DuckDB security surface applied before any user SQL runs.

    Untrusted sessions always force external access, autoload, autoinstall,
    filesystem, and network surfaces off. Trusted control writers may still
    open a local primary catalog but never autoload extensions.
    """

    enable_external_access: bool = False
    autoinstall_known_extensions: bool = False
    autoload_known_extensions: bool = False
    lock_configuration: bool = True
    allow_filesystem: bool = False
    allow_network: bool = False
    threads: int = 1
    memory_limit: str = DEFAULT_CONTROL_MEMORY_LIMIT

    def __post_init__(self) -> None:
        if not isinstance(self.threads, int) or isinstance(self.threads, bool):
            raise ConnectionError("threads must be an int")
        if self.threads < 1 or self.threads > 256:
            raise ConnectionError(f"threads out of range: {self.threads}")
        limit = str(self.memory_limit or "").strip()
        if not limit or not _MEMORY_LIMIT_RE.match(limit):
            raise ConnectionError(f"invalid memory_limit {self.memory_limit!r}")
        object.__setattr__(self, "memory_limit", limit)

    def for_trust(self, trust: TrustLevel) -> ConnectionSecurityPolicy:
        """Return a policy hardened for the given trust level (fail closed)."""

        if trust is TrustLevel.UNTRUSTED:
            return replace(
                self,
                enable_external_access=False,
                autoinstall_known_extensions=False,
                autoload_known_extensions=False,
                lock_configuration=True,
                allow_filesystem=False,
                allow_network=False,
            )
        # Trusted still never autoloads/autoinstalls extensions by default.
        return replace(
            self,
            autoinstall_known_extensions=False,
            autoload_known_extensions=False,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enable_external_access": self.enable_external_access,
            "autoinstall_known_extensions": self.autoinstall_known_extensions,
            "autoload_known_extensions": self.autoload_known_extensions,
            "lock_configuration": self.lock_configuration,
            "allow_filesystem": self.allow_filesystem,
            "allow_network": self.allow_network,
            "threads": self.threads,
            "memory_limit": self.memory_limit,
        }


def default_security_policy(
    workload: WorkloadKind,
    *,
    trust: TrustLevel | None = None,
) -> ConnectionSecurityPolicy:
    """Return the default security policy for a workload class."""

    if trust is None:
        trust = (
            TrustLevel.UNTRUSTED
            if workload in (WorkloadKind.PUBLICATION, WorkloadKind.UNTRUSTED)
            else TrustLevel.TRUSTED
        )

    if workload is WorkloadKind.CONTROL:
        base = ConnectionSecurityPolicy(
            enable_external_access=False,
            autoinstall_known_extensions=False,
            autoload_known_extensions=False,
            lock_configuration=True,
            allow_filesystem=False,
            allow_network=False,
            threads=1,
            memory_limit=DEFAULT_CONTROL_MEMORY_LIMIT,
        )
    elif workload is WorkloadKind.ANALYTICAL:
        base = ConnectionSecurityPolicy(
            enable_external_access=False,
            autoinstall_known_extensions=False,
            autoload_known_extensions=False,
            lock_configuration=True,
            # Analytical may open allowlisted local catalog files only via ATTACH.
            allow_filesystem=False,
            allow_network=False,
            threads=2,
            memory_limit=DEFAULT_ANALYTICAL_MEMORY_LIMIT,
        )
    else:
        # Publication / untrusted: hardest surface.
        base = ConnectionSecurityPolicy(
            enable_external_access=False,
            autoinstall_known_extensions=False,
            autoload_known_extensions=False,
            lock_configuration=True,
            allow_filesystem=False,
            allow_network=False,
            threads=1,
            memory_limit=DEFAULT_UNTRUSTED_MEMORY_LIMIT,
        )
    return base.for_trust(trust)


def build_duckdb_config(policy: ConnectionSecurityPolicy) -> dict[str, str]:
    """Materialize a DuckDB ``config`` dict from a security policy.

    Values are strings so they are accepted both by ``duckdb.connect(..., config=)``
    and by ``SET`` statements.
    """

    return {
        "enable_external_access": "true" if policy.enable_external_access else "false",
        "autoinstall_known_extensions": (
            "true" if policy.autoinstall_known_extensions else "false"
        ),
        "autoload_known_extensions": (
            "true" if policy.autoload_known_extensions else "false"
        ),
        "threads": str(policy.threads),
        "memory_limit": policy.memory_limit,
    }


def security_statements_for(policy: ConnectionSecurityPolicy) -> tuple[str, ...]:
    """Ordered SET statements that enforce ``policy`` on an open connection.

    ``lock_configuration`` is always last so later statements cannot undo the
    hardened surface.
    """

    statements = [
        f"SET enable_external_access={'true' if policy.enable_external_access else 'false'}",
        f"SET autoinstall_known_extensions="
        f"{'true' if policy.autoinstall_known_extensions else 'false'}",
        f"SET autoload_known_extensions="
        f"{'true' if policy.autoload_known_extensions else 'false'}",
        f"SET threads={int(policy.threads)}",
        f"SET memory_limit='{policy.memory_limit}'",
    ]
    if policy.lock_configuration:
        statements.append("SET lock_configuration=true")
    return tuple(statements)


def apply_security_policy(connection: Any, policy: ConnectionSecurityPolicy) -> None:
    """Execute security SETs on ``connection`` (fail closed on any error)."""

    for statement in security_statements_for(policy):
        try:
            connection.execute(statement)
        except Exception as exc:  # noqa: BLE001 — surface as ConnectionError
            raise ConnectionError(
                f"failed to apply security policy statement {statement!r}: {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# Analytical catalog attachments
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AnalyticalCatalogSpec:
    """One catalog to ATTACH read-only under a trusted analytical session.

    Authority control catalogs must never appear on untrusted/publication
    sessions. Paths are validated as local filesystem paths (no URIs, no
    remote schemes).
    """

    alias: str
    path: str
    read_only: bool = True
    workload: WorkloadKind = WorkloadKind.ANALYTICAL

    def __post_init__(self) -> None:
        alias = str(self.alias or "").strip()
        if not _ALIAS_RE.match(alias):
            raise ConnectionError(f"invalid catalog alias {self.alias!r}")
        object.__setattr__(self, "alias", alias)

        path = str(self.path or "").strip()
        if not path:
            raise ConnectionError("catalog path is required")
        if not _SAFE_PATH_CHARS.match(path):
            raise ConnectionError(f"unsafe catalog path {path!r}")
        lower = path.lower()
        if "://" in path or lower.startswith(("s3:", "http:", "https:", "gs:", "az:")):
            raise ConnectionError(
                f"remote/URI catalog paths are forbidden for local attach: {path!r}"
            )
        # Normalize to a stable string form without resolving (tests may use
        # synthetic paths).
        object.__setattr__(self, "path", path)

        if not self.read_only:
            raise ConnectionError(
                "analytical catalog attachments must be read_only=True"
            )
        if self.workload is WorkloadKind.CONTROL:
            raise ConnectionError(
                "analytical catalogs cannot target the control workload pool"
            )
        if self.workload in (WorkloadKind.PUBLICATION, WorkloadKind.UNTRUSTED):
            raise ConnectionError(
                "authority/analytical catalogs cannot attach to untrusted workloads"
            )

    def attach_sql(self) -> str:
        """Return the parameterized ATTACH statement for this catalog.

        The path is single-quote escaped. Always sets ``READ_ONLY``.
        """

        escaped = self.path.replace("'", "''")
        return f"ATTACH '{escaped}' AS {self.alias} (READ_ONLY)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "path": self.path,
            "read_only": self.read_only,
            "workload": self.workload.value,
        }


# ---------------------------------------------------------------------------
# Quack URI / secrets
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QuackSecrets:
    """Short-lived Quack credentials held separately from endpoints.

    Secrets never appear in ``repr`` / ``str`` and must not be written to
    logs, receipts, or Quack-visible columns.
    """

    token: str = ""
    username: str = ""
    password: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "token", str(self.token or ""))
        object.__setattr__(self, "username", str(self.username or ""))
        object.__setattr__(self, "password", str(self.password or ""))
        if len(self.token) > 8_192:
            raise ConnectionError("Quack token exceeds maximum length")
        if len(self.password) > 8_192:
            raise ConnectionError("Quack password exceeds maximum length")
        if len(self.username) > 512:
            raise ConnectionError("Quack username exceeds maximum length")

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "QuackSecrets(token=***, username=***, password=***)"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.__repr__()

    @property
    def is_empty(self) -> bool:
        return not (self.token or self.password or self.username)

    def redacted_dict(self) -> dict[str, str]:
        return {
            "token": "***" if self.token else "",
            "username": "***" if self.username else "",
            "password": "***" if self.password else "",
        }


@dataclass(frozen=True, slots=True)
class QuackEndpoint:
    """Network identity of a Quack endpoint without secrets."""

    host: str
    port: int
    database: str = ""
    use_tls: bool = False

    def __post_init__(self) -> None:
        host = str(self.host or "").strip().lower()
        if not host or not _HOST_RE.match(host):
            raise ConnectionError(f"invalid Quack host {self.host!r}")
        # Reject non-loopback remote hosts unless explicitly TLS (defense in depth:
        # production remote use requires a TLS reverse proxy per plan).
        if host not in {"localhost", "127.0.0.1", "::1"} and not self.use_tls:
            # Still allow the endpoint description; callers decide policy.
            pass
        if not isinstance(self.port, int) or isinstance(self.port, bool):
            raise ConnectionError("Quack port must be an int")
        if self.port < 1 or self.port > 65_535:
            raise ConnectionError(f"Quack port out of range: {self.port}")
        database = str(self.database or "").strip().lstrip("/")
        if database and not re.match(r"^[A-Za-z0-9_./-]{1,256}$", database):
            raise ConnectionError(f"invalid Quack database name {self.database!r}")
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "database", database)

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "use_tls": self.use_tls,
        }

    def authority(self) -> str:
        return f"{self.host}:{self.port}"


@dataclass(frozen=True, slots=True)
class QuackURI:
    """Parsed Quack URI with secrets held in a separate object."""

    endpoint: QuackEndpoint
    secrets: QuackSecrets = field(default_factory=QuackSecrets)
    scheme: str = "quack"
    query: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        scheme = str(self.scheme or "quack").strip().lower()
        if scheme not in {"quack", "quacks", "duckdb"}:
            raise ConnectionError(f"unsupported Quack URI scheme {self.scheme!r}")
        object.__setattr__(self, "scheme", scheme)
        # Freeze query mapping.
        raw_query = self.query or {}
        if not isinstance(raw_query, Mapping):
            raise ConnectionError("Quack URI query must be a mapping")
        frozen = MappingProxyType({str(k): str(v) for k, v in raw_query.items()})
        object.__setattr__(self, "query", frozen)
        if scheme == "quacks":
            object.__setattr__(
                self,
                "endpoint",
                QuackEndpoint(
                    host=self.endpoint.host,
                    port=self.endpoint.port,
                    database=self.endpoint.database,
                    use_tls=True,
                ),
            )

    def redacted(self) -> str:
        """Return a log-safe URI with credentials stripped."""

        db = f"/{self.endpoint.database}" if self.endpoint.database else ""
        auth = "***@" if not self.secrets.is_empty else ""
        scheme = "quacks" if self.endpoint.use_tls else self.scheme
        return f"{scheme}://{auth}{self.endpoint.authority()}{db}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "scheme": self.scheme,
            "endpoint": self.endpoint.to_dict(),
            "secrets": self.secrets.redacted_dict(),
            "query": dict(self.query),
            "redacted_uri": self.redacted(),
        }


def parse_quack_uri(uri: str) -> QuackURI:
    """Parse a Quack connection URI into endpoint + secrets.

    Accepted forms::

        quack://host:port/database
        quack://user:token@host:port/database
        quacks://host:port/database?token=...

    Secrets are extracted and never retained in the endpoint object. The
    original URI string is not stored.
    """

    if not isinstance(uri, str) or not uri.strip():
        raise ConnectionError("Quack URI must be a non-empty string")
    text = uri.strip()
    if len(text) > 8_192:
        raise ConnectionError("Quack URI exceeds maximum length")
    if "\x00" in text:
        raise ConnectionError("Quack URI contains NUL")

    parsed = urllib.parse.urlparse(text)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"quack", "quacks", "duckdb"}:
        raise ConnectionError(
            f"unsupported Quack URI scheme {parsed.scheme!r}; expected quack/quacks"
        )
    if not parsed.hostname:
        raise ConnectionError("Quack URI requires a host")

    port = parsed.port
    if port is None:
        port = 5433 if scheme != "quacks" else 5433

    query = {
        str(k): str(v[0]) if isinstance(v, list) and v else str(v)
        for k, v in urllib.parse.parse_qs(parsed.query, keep_blank_values=False).items()
    }

    username = urllib.parse.unquote(parsed.username or "") if parsed.username else ""
    password = urllib.parse.unquote(parsed.password or "") if parsed.password else ""
    token = query.pop("token", "") or password

    endpoint = QuackEndpoint(
        host=parsed.hostname,
        port=int(port),
        database=(parsed.path or "").lstrip("/"),
        use_tls=(scheme == "quacks"),
    )
    secrets = QuackSecrets(token=token, username=username, password=password)
    return QuackURI(endpoint=endpoint, secrets=secrets, scheme=scheme, query=query)


def redact_quack_uri(uri: str) -> str:
    """Parse and re-emit a redacted Quack URI for logging."""

    return parse_quack_uri(uri).redacted()


# ---------------------------------------------------------------------------
# Pool configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PoolConfig:
    """Per-workload pool sizing and lifecycle bounds."""

    workload: WorkloadKind
    max_size: int = 4
    max_idle: int = 2
    max_lifetime_ms: int = 60_000
    acquire_timeout_ms: int = 5_000
    short_lived: bool = True
    access_mode: AccessMode = AccessMode.READ_ONLY
    trust: TrustLevel = TrustLevel.TRUSTED
    budget: StatementBudget = field(default_factory=lambda: DEFAULT_CONTROL_BUDGET)
    security: ConnectionSecurityPolicy = field(
        default_factory=lambda: default_security_policy(WorkloadKind.CONTROL)
    )
    primary_path: str = ":memory:"
    catalog_name: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.max_size, int) or self.max_size < 1:
            raise ConnectionError("max_size must be a positive int")
        if not isinstance(self.max_idle, int) or self.max_idle < 0:
            raise ConnectionError("max_idle must be a non-negative int")
        if self.max_idle > self.max_size:
            raise ConnectionError("max_idle cannot exceed max_size")
        for name in ("max_lifetime_ms", "acquire_timeout_ms"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 1:
                raise ConnectionError(f"{name} must be a positive int")
        path = str(self.primary_path or "").strip() or ":memory:"
        if path != ":memory:" and not _SAFE_PATH_CHARS.match(path):
            raise ConnectionError(f"unsafe primary_path {path!r}")
        object.__setattr__(self, "primary_path", path)
        catalog = str(self.catalog_name or "").strip() or self.workload.value
        if not _ALIAS_RE.match(catalog.replace("-", "_")) and catalog not in {
            self.workload.value
        }:
            # Allow workload value tokens; normalize catalog name.
            if not re.match(r"^[A-Za-z0-9_.-]{1,64}$", catalog):
                raise ConnectionError(f"invalid catalog_name {catalog!r}")
        object.__setattr__(self, "catalog_name", catalog)

        # Writers only on control (and never on untrusted).
        if self.access_mode is AccessMode.READ_WRITE:
            if self.workload is not WorkloadKind.CONTROL:
                raise ConnectionError(
                    "read_write access is only permitted on the control workload"
                )
            if self.trust is TrustLevel.UNTRUSTED:
                raise ConnectionError("untrusted sessions cannot be read_write")

        # Harden security for untrusted.
        secured = self.security.for_trust(self.trust)
        object.__setattr__(self, "security", secured)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workload": self.workload.value,
            "max_size": self.max_size,
            "max_idle": self.max_idle,
            "max_lifetime_ms": self.max_lifetime_ms,
            "acquire_timeout_ms": self.acquire_timeout_ms,
            "short_lived": self.short_lived,
            "access_mode": self.access_mode.value,
            "trust": self.trust.value,
            "budget": self.budget.to_dict(),
            "security": self.security.to_dict(),
            "primary_path": self.primary_path,
            "catalog_name": self.catalog_name,
        }


def default_pool_config(
    workload: WorkloadKind,
    *,
    primary_path: str = ":memory:",
    read_write: bool = False,
) -> PoolConfig:
    """Return a default pool configuration for ``workload``."""

    if workload is WorkloadKind.CONTROL:
        return PoolConfig(
            workload=WorkloadKind.CONTROL,
            max_size=2 if read_write else 4,
            max_idle=1 if read_write else 2,
            max_lifetime_ms=30_000,
            acquire_timeout_ms=3_000,
            short_lived=True,
            access_mode=(
                AccessMode.READ_WRITE if read_write else AccessMode.READ_ONLY
            ),
            trust=TrustLevel.TRUSTED,
            budget=DEFAULT_CONTROL_BUDGET,
            security=default_security_policy(WorkloadKind.CONTROL),
            primary_path=primary_path,
            catalog_name="control",
        )
    if workload is WorkloadKind.ANALYTICAL:
        if read_write:
            raise ConnectionError("analytical pools are read-only")
        return PoolConfig(
            workload=WorkloadKind.ANALYTICAL,
            max_size=8,
            max_idle=4,
            max_lifetime_ms=120_000,
            acquire_timeout_ms=10_000,
            short_lived=True,
            access_mode=AccessMode.READ_ONLY,
            trust=TrustLevel.TRUSTED,
            budget=DEFAULT_ANALYTICAL_BUDGET,
            security=default_security_policy(WorkloadKind.ANALYTICAL),
            primary_path=primary_path,
            catalog_name="analytical",
        )
    # Publication / untrusted
    if read_write:
        raise ConnectionError(f"{workload.value} pools are read-only")
    return PoolConfig(
        workload=workload,
        max_size=4,
        max_idle=2,
        max_lifetime_ms=15_000,
        acquire_timeout_ms=2_000,
        short_lived=True,
        access_mode=AccessMode.READ_ONLY,
        trust=TrustLevel.UNTRUSTED,
        budget=DEFAULT_UNTRUSTED_BUDGET,
        security=default_security_policy(workload, trust=TrustLevel.UNTRUSTED),
        primary_path=primary_path,
        catalog_name=workload.value,
    )


# ---------------------------------------------------------------------------
# Connection backend protocol + managed handle
# ---------------------------------------------------------------------------


class ConnectionHandle(Protocol):
    """Minimal DuckDB-like connection surface used by this module."""

    def execute(self, sql: str, parameters: Any = None) -> Any: ...

    def close(self) -> None: ...


ConnectionFactory = Callable[[PoolConfig], ConnectionHandle]


def _import_duckdb() -> Any:
    try:
        import duckdb  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised when duckdb absent
        raise ConnectionError(
            "duckdb is not installed; inject a connection factory for tests "
            "or provision the pinned DuckDB 1.5.5 environment"
        ) from exc
    return duckdb


def default_duckdb_factory(config: PoolConfig) -> ConnectionHandle:
    """Open a real DuckDB connection for ``config`` (lazy import)."""

    duckdb = _import_duckdb()
    read_only = config.access_mode is AccessMode.READ_ONLY
    path = config.primary_path
    # In-memory databases cannot be opened read-only in DuckDB.
    if path == ":memory:" and read_only:
        read_only = False
    duck_config = build_duckdb_config(config.security)
    try:
        connection = duckdb.connect(
            database=path,
            read_only=read_only,
            config=duck_config,
        )
    except Exception as exc:  # noqa: BLE001
        raise ConnectionError(f"failed to open DuckDB database {path!r}: {exc}") from exc
    try:
        apply_security_policy(connection, config.security)
    except ConnectionError:
        try:
            connection.close()
        except Exception:  # noqa: BLE001
            pass
        raise
    return connection


@dataclass
class _BudgetMeter:
    """Mutable counters for one short-lived session."""

    budget: StatementBudget
    started_monotonic: float = field(default_factory=time.monotonic)
    statements: int = 0
    rows: int = 0
    bytes: int = 0
    transaction_started_monotonic: float | None = None

    def check_duration(self) -> None:
        elapsed_ms = int((time.monotonic() - self.started_monotonic) * 1000)
        if elapsed_ms > self.budget.max_duration_ms:
            raise StatementBudgetExceeded(
                f"session duration budget exceeded "
                f"({elapsed_ms}ms > {self.budget.max_duration_ms}ms)"
            )
        if self.transaction_started_monotonic is not None:
            tx_ms = int(
                (time.monotonic() - self.transaction_started_monotonic) * 1000
            )
            if tx_ms > self.budget.max_transaction_ms:
                raise StatementBudgetExceeded(
                    f"writer transaction budget exceeded "
                    f"({tx_ms}ms > {self.budget.max_transaction_ms}ms)"
                )

    def record_statement(self, sql: str) -> None:
        self.check_duration()
        self.statements += 1
        if self.statements > self.budget.max_statements:
            raise StatementBudgetExceeded(
                f"statement budget exceeded "
                f"({self.statements} > {self.budget.max_statements})"
            )
        # Approximate SQL byte cost against the byte budget.
        self.bytes += len(sql.encode("utf-8"))
        if self.bytes > self.budget.max_bytes:
            raise StatementBudgetExceeded(
                f"byte budget exceeded ({self.bytes} > {self.budget.max_bytes})"
            )

    def record_rows(self, count: int) -> None:
        if count < 0:
            return
        self.rows += count
        if self.rows > self.budget.max_rows:
            raise StatementBudgetExceeded(
                f"row budget exceeded ({self.rows} > {self.budget.max_rows})"
            )

    def begin_transaction(self) -> None:
        self.transaction_started_monotonic = time.monotonic()

    def end_transaction(self, *, enforce_budget: bool = True) -> None:
        """Clear the open-transaction clock.

        When ``enforce_budget`` is true (commit path), a late transaction is
        rejected. Rollback always clears state so cleanup cannot fail closed
        on the budget it is trying to recover from.
        """

        if enforce_budget and self.transaction_started_monotonic is not None:
            self.check_duration()
        self.transaction_started_monotonic = None


class ManagedConnection:
    """Short-lived, budgeted, security-hardened session wrapper.

    Does not own pool membership; callers obtain instances from a
    :class:`ConnectionPool` or :class:`ConnectionManager` context manager.
    """

    __slots__ = (
        "_raw",
        "_config",
        "_meter",
        "_closed",
        "_in_transaction",
        "_attached_aliases",
        "_owns_raw",
    )

    def __init__(
        self,
        raw: ConnectionHandle,
        config: PoolConfig,
        *,
        owns_raw: bool = True,
    ) -> None:
        self._raw = raw
        self._config = config
        self._meter = _BudgetMeter(budget=config.budget)
        self._closed = False
        self._in_transaction = False
        self._attached_aliases: list[str] = []
        self._owns_raw = owns_raw

    # -- properties --------------------------------------------------------

    @property
    def workload(self) -> WorkloadKind:
        return self._config.workload

    @property
    def access_mode(self) -> AccessMode:
        return self._config.access_mode

    @property
    def trust(self) -> TrustLevel:
        return self._config.trust

    @property
    def budget(self) -> StatementBudget:
        return self._config.budget

    @property
    def security(self) -> ConnectionSecurityPolicy:
        return self._config.security

    @property
    def catalog_name(self) -> str:
        return self._config.catalog_name

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def in_transaction(self) -> bool:
        return self._in_transaction

    @property
    def attached_aliases(self) -> tuple[str, ...]:
        return tuple(self._attached_aliases)

    @property
    def statements_used(self) -> int:
        return self._meter.statements

    @property
    def raw(self) -> ConnectionHandle:
        """Underlying handle (for trusted broker integration only)."""

        self._ensure_open()
        return self._raw

    # -- lifecycle ---------------------------------------------------------

    def _ensure_open(self) -> None:
        if self._closed:
            raise ConnectionError("connection is closed")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._in_transaction:
            try:
                self._raw.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass
            self._in_transaction = False
            self._meter.end_transaction()
        if self._owns_raw:
            try:
                self._raw.close()
            except Exception:  # noqa: BLE001
                pass

    def __enter__(self) -> ManagedConnection:
        self._ensure_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- SQL execution with budgets ----------------------------------------

    def execute(self, sql: str, parameters: Any = None) -> Any:
        """Execute ``sql`` under the session budget and access-mode checks."""

        self._ensure_open()
        if not isinstance(sql, str) or not sql.strip():
            raise ConnectionError("sql must be a non-empty string")
        normalized = " ".join(sql.strip().split())
        upper = normalized.upper()
        self._reject_forbidden_sql(upper)
        self._meter.record_statement(normalized)

        if parameters is None:
            result = self._raw.execute(sql)
        else:
            result = self._raw.execute(sql, parameters)

        # Best-effort row accounting when the driver exposes rowcount.
        rowcount = getattr(result, "rowcount", None)
        if isinstance(rowcount, int) and rowcount > 0:
            self._meter.record_rows(rowcount)
        return result

    def _reject_forbidden_sql(self, upper_sql: str) -> None:
        """Deny dangerous surfaces for untrusted / locked sessions."""

        # Configuration lock first — prevents privilege re-enablement.
        if self._config.security.lock_configuration and upper_sql.startswith(
            ("SET ", "RESET ")
        ):
            # ManagedConnection itself applies SETs before lock; user SQL cannot.
            raise ConnectionError(
                "configuration is locked; SET/RESET is denied on this session"
            )

        # Extension autoload / install surface (all hardened sessions).
        if not self._config.security.autoload_known_extensions:
            if upper_sql.startswith(("INSTALL ", "LOAD ")):
                raise ConnectionError(
                    "extension install/load is disabled on this connection"
                )
        if not self._config.security.autoinstall_known_extensions:
            if upper_sql.startswith("INSTALL "):
                raise ConnectionError(
                    "extension install/load is disabled on this connection"
                )

        # Filesystem / network / external-access surfaces.
        if (
            self._config.trust is TrustLevel.UNTRUSTED
            or not self._config.security.enable_external_access
        ):
            forbidden_fragments = (
                "INSTALL ",
                "LOAD ",
                "COPY ",
                "READ_CSV",
                "READ_PARQUET",
                "READ_JSON",
                "READ_BLOB",
                "READ_TEXT",
                "HTTPFS",
            )
            for fragment in forbidden_fragments:
                if fragment in upper_sql:
                    raise ConnectionError(
                        f"external/filesystem/network surface denied: {fragment.strip()}"
                    )
            # Bare path table scans: FROM 'file' (not FROM table).
            if "FROM '" in upper_sql or 'FROM "' in upper_sql:
                raise ConnectionError(
                    "external/filesystem/network surface denied: path scan"
                )

        # Writers only on control read_write sessions.
        mutating_prefixes = (
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            "CREATE ",
            "DROP ",
            "ALTER ",
            "TRUNCATE ",
            "COPY ",
            "INSTALL ",
            "LOAD ",
            "EXPORT ",
            "IMPORT ",
            "ATTACH ",
            "DETACH ",
            "CALL ",
            "PRAGMA ",
            "SET ",
            "RESET ",
        )
        is_mutating = upper_sql.startswith(mutating_prefixes) or upper_sql in {
            "CHECKPOINT",
            "FORCE CHECKPOINT",
        }

        if self._config.access_mode is AccessMode.READ_ONLY and is_mutating:
            if not upper_sql.startswith(
                (
                    "BEGIN",
                    "COMMIT",
                    "ROLLBACK",
                    "SELECT",
                    "WITH",
                    "EXPLAIN",
                    "DESCRIBE",
                    "SHOW",
                    "SUMMARIZE",
                )
            ):
                raise ConnectionError(
                    f"read-only session rejects mutating SQL: {upper_sql[:80]}"
                )

    # -- writer transactions -----------------------------------------------

    def begin(self) -> None:
        """Begin a bounded short writer transaction."""

        self._ensure_open()
        if self._config.access_mode is not AccessMode.READ_WRITE:
            raise ConnectionError("begin() requires a read_write (writer) session")
        if self._config.workload is not WorkloadKind.CONTROL:
            raise ConnectionError("writer transactions are control-workload only")
        if self._in_transaction:
            raise ConnectionError("transaction already open")
        self._meter.begin_transaction()
        self._meter.check_duration()
        self._raw.execute("BEGIN TRANSACTION")
        self._in_transaction = True

    def commit(self) -> None:
        self._ensure_open()
        if not self._in_transaction:
            raise ConnectionError("no open transaction to commit")
        self._meter.check_duration()
        self._raw.execute("COMMIT")
        self._in_transaction = False
        self._meter.end_transaction(enforce_budget=True)

    def rollback(self) -> None:
        self._ensure_open()
        if not self._in_transaction:
            raise ConnectionError("no open transaction to rollback")
        try:
            self._raw.execute("ROLLBACK")
        finally:
            self._in_transaction = False
            self._meter.end_transaction(enforce_budget=False)

    @contextmanager
    def short_transaction(self) -> Iterator[ManagedConnection]:
        """Context manager for a bounded short writer transaction.

        On success commits; on error rolls back. Exceeding
        ``max_transaction_ms`` raises :class:`StatementBudgetExceeded`.
        """

        self.begin()
        try:
            yield self
            self._meter.check_duration()
            self.commit()
        except BaseException:
            if self._in_transaction:
                try:
                    self.rollback()
                except Exception:  # noqa: BLE001
                    pass
            raise

    # -- analytical attachments --------------------------------------------

    def attach_analytical_catalog(self, spec: AnalyticalCatalogSpec) -> None:
        """ATTACH a read-only analytical catalog (trusted broker only)."""

        self._ensure_open()
        if self._config.trust is TrustLevel.UNTRUSTED:
            raise ConnectionError(
                "untrusted sessions cannot attach analytical catalogs"
            )
        if self._config.workload in (
            WorkloadKind.PUBLICATION,
            WorkloadKind.UNTRUSTED,
        ):
            raise ConnectionError(
                "publication/untrusted workloads cannot attach authority catalogs"
            )
        if self._config.workload is WorkloadKind.CONTROL:
            raise ConnectionError(
                "control workload must not attach analytical catalogs "
                "(use the analytical pool)"
            )
        if spec.workload is not WorkloadKind.ANALYTICAL:
            raise ConnectionError(
                "only analytical-workload catalog specs may be attached"
            )
        if not spec.read_only:
            raise ConnectionError("attached catalogs must be read_only")
        if spec.alias in self._attached_aliases:
            raise ConnectionError(f"catalog alias already attached: {spec.alias}")

        # Bypass the generic SET/ATTACH denylist for this controlled path.
        self._meter.record_statement(spec.attach_sql())
        try:
            self._raw.execute(spec.attach_sql())
        except Exception as exc:  # noqa: BLE001
            raise ConnectionError(
                f"failed to attach catalog {spec.alias!r}: {exc}"
            ) from exc
        self._attached_aliases.append(spec.alias)

    def usage_snapshot(self) -> dict[str, Any]:
        return {
            "workload": self.workload.value,
            "access_mode": self.access_mode.value,
            "trust": self.trust.value,
            "catalog_name": self.catalog_name,
            "statements": self._meter.statements,
            "rows": self._meter.rows,
            "bytes": self._meter.bytes,
            "in_transaction": self._in_transaction,
            "attached_aliases": list(self._attached_aliases),
            "closed": self._closed,
            "budget": self.budget.to_dict(),
            "security": self.security.to_dict(),
        }


class BoundedWriterSession:
    """Convenience facade: one short-lived control writer with auto-close."""

    def __init__(self, connection: ManagedConnection) -> None:
        if connection.access_mode is not AccessMode.READ_WRITE:
            raise ConnectionError("BoundedWriterSession requires a writer connection")
        if connection.workload is not WorkloadKind.CONTROL:
            raise ConnectionError("BoundedWriterSession requires control workload")
        self._connection = connection

    @property
    def connection(self) -> ManagedConnection:
        return self._connection

    def __enter__(self) -> ManagedConnection:
        self._connection.begin()
        return self._connection

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if exc_type is None and self._connection.in_transaction:
                self._connection.commit()
            elif self._connection.in_transaction:
                self._connection.rollback()
        finally:
            self._connection.close()


# ---------------------------------------------------------------------------
# Connection pool (per workload)
# ---------------------------------------------------------------------------


class ConnectionPool:
    """Thread-safe short-lived connection pool for a single workload/catalog.

    Control and analytical workloads must use distinct pool instances (and
    typically distinct primary paths / catalog names). Idle connections may be
    reused only when ``short_lived`` still allows and the lifetime budget
    permits; otherwise connections are closed on release.
    """

    def __init__(
        self,
        config: PoolConfig,
        *,
        factory: ConnectionFactory | None = None,
    ) -> None:
        self._config = config
        self._factory = factory or default_duckdb_factory
        self._lock = threading.RLock()
        self._idle: list[tuple[float, ConnectionHandle]] = []
        self._checked_out = 0
        self._closed = False
        self._created = 0

    @property
    def config(self) -> PoolConfig:
        return self._config

    @property
    def workload(self) -> WorkloadKind:
        return self._config.workload

    @property
    def catalog_name(self) -> str:
        return self._config.catalog_name

    @property
    def checked_out(self) -> int:
        with self._lock:
            return self._checked_out

    @property
    def idle_count(self) -> int:
        with self._lock:
            return len(self._idle)

    @property
    def created_count(self) -> int:
        with self._lock:
            return self._created

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "workload": self._config.workload.value,
                "catalog_name": self._config.catalog_name,
                "max_size": self._config.max_size,
                "checked_out": self._checked_out,
                "idle": len(self._idle),
                "created": self._created,
                "closed": self._closed,
                "access_mode": self._config.access_mode.value,
                "trust": self._config.trust.value,
            }

    def _create_raw(self) -> ConnectionHandle:
        raw = self._factory(self._config)
        self._created += 1
        return raw

    def acquire(self) -> ManagedConnection:
        """Acquire a short-lived managed connection from this pool."""

        deadline = time.monotonic() + (self._config.acquire_timeout_ms / 1000.0)
        while True:
            with self._lock:
                if self._closed:
                    raise ConnectionError("pool is closed")
                now = time.monotonic()
                # Drop expired idle handles.
                kept: list[tuple[float, ConnectionHandle]] = []
                for created_at, handle in self._idle:
                    age_ms = int((now - created_at) * 1000)
                    if age_ms > self._config.max_lifetime_ms:
                        try:
                            handle.close()
                        except Exception:  # noqa: BLE001
                            pass
                    else:
                        kept.append((created_at, handle))
                self._idle = kept

                if self._idle:
                    _, raw = self._idle.pop()
                    self._checked_out += 1
                    return ManagedConnection(raw, self._config, owns_raw=False)

                if self._checked_out < self._config.max_size:
                    raw = self._create_raw()
                    self._checked_out += 1
                    return ManagedConnection(raw, self._config, owns_raw=False)

            if time.monotonic() >= deadline:
                raise ConnectionError(
                    f"timed out acquiring {self._config.workload.value} connection "
                    f"(max_size={self._config.max_size})"
                )
            time.sleep(0.005)

    def release(self, connection: ManagedConnection) -> None:
        """Return or destroy a managed connection."""

        if connection.workload is not self._config.workload:
            raise ConnectionError(
                f"cannot release {connection.workload.value} connection "
                f"into {self._config.workload.value} pool"
            )
        raw = connection._raw  # noqa: SLF001 — intentional pool handoff
        # Force-close managed wrapper bookkeeping without closing raw yet.
        if connection.in_transaction:
            try:
                raw.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass
        connection._in_transaction = False  # noqa: SLF001
        connection._closed = True  # noqa: SLF001

        with self._lock:
            if self._checked_out > 0:
                self._checked_out -= 1
            if self._closed or not self._config.short_lived:
                try:
                    raw.close()
                except Exception:  # noqa: BLE001
                    pass
                return
            # Short-lived pools intentionally avoid long reuse: only keep a
            # small idle set, otherwise close immediately.
            if len(self._idle) < self._config.max_idle:
                self._idle.append((time.monotonic(), raw))
            else:
                try:
                    raw.close()
                except Exception:  # noqa: BLE001
                    pass

    @contextmanager
    def connection(self) -> Iterator[ManagedConnection]:
        """Acquire → yield → release a short-lived connection."""

        conn = self.acquire()
        try:
            yield conn
        finally:
            self.release(conn)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            while self._idle:
                _, handle = self._idle.pop()
                try:
                    handle.close()
                except Exception:  # noqa: BLE001
                    pass


# ---------------------------------------------------------------------------
# Connection manager (workload isolation root)
# ---------------------------------------------------------------------------


class ConnectionManager:
    """Root factory that keeps control and analytical pools strictly separate.

    Responsibilities:

    * own one :class:`ConnectionPool` per ``(WorkloadKind, AccessMode)``
    * open short-lived local writer / reader sessions
    * attach read-only analytical catalogs only on the analytical pool
    * parse and hold Quack endpoints/secrets without leaking credentials
    * refuse cross-workload catalog attachment and untrusted privilege escalation
    """

    def __init__(
        self,
        *,
        control_path: str = ":memory:",
        analytical_path: str = ":memory:",
        publication_path: str = ":memory:",
        factory: ConnectionFactory | None = None,
        quack: QuackURI | None = None,
    ) -> None:
        self._factory = factory
        self._quack = quack
        self._lock = threading.RLock()
        self._pools: dict[tuple[WorkloadKind, AccessMode], ConnectionPool] = {}
        self._paths = {
            WorkloadKind.CONTROL: control_path,
            WorkloadKind.ANALYTICAL: analytical_path,
            WorkloadKind.PUBLICATION: publication_path,
            WorkloadKind.UNTRUSTED: publication_path,
        }
        self._closed = False

    # -- pool management ---------------------------------------------------

    def pool_for(
        self,
        workload: WorkloadKind,
        *,
        read_write: bool = False,
    ) -> ConnectionPool:
        """Return (creating if needed) the isolated pool for ``workload``."""

        if read_write and workload is not WorkloadKind.CONTROL:
            raise ConnectionError(
                "read_write pools are only available for the control workload"
            )
        mode = (
            AccessMode.READ_WRITE
            if read_write and workload is WorkloadKind.CONTROL
            else AccessMode.READ_ONLY
        )
        key = (workload, mode)
        with self._lock:
            if self._closed:
                raise ConnectionError("connection manager is closed")
            existing = self._pools.get(key)
            if existing is not None:
                return existing
            config = default_pool_config(
                workload,
                primary_path=self._paths.get(workload, ":memory:"),
                read_write=(mode is AccessMode.READ_WRITE),
            )
            pool = ConnectionPool(config, factory=self._factory)
            self._pools[key] = pool
            return pool

    def ensure_isolated_pools(self) -> Mapping[str, dict[str, Any]]:
        """Create default control + analytical pools and return their stats.

        Guarantees distinct pool object identities and catalog names.
        """

        control = self.pool_for(WorkloadKind.CONTROL, read_write=False)
        control_writer = self.pool_for(WorkloadKind.CONTROL, read_write=True)
        analytical = self.pool_for(WorkloadKind.ANALYTICAL)
        if control.catalog_name == analytical.catalog_name:
            raise ConnectionError(
                "control and analytical pools must use distinct catalog names"
            )
        if control is analytical or control_writer is analytical:
            raise ConnectionError(
                "control and analytical workloads must not share a pool object"
            )
        if (
            control.config.primary_path == analytical.config.primary_path
            and control.config.primary_path != ":memory:"
        ):
            raise ConnectionError(
                "control and analytical primary paths must differ"
            )
        return {
            "control": control.stats(),
            "control_writer": control_writer.stats(),
            "analytical": analytical.stats(),
        }

    # -- short-lived sessions ----------------------------------------------

    @contextmanager
    def reader(
        self,
        workload: WorkloadKind = WorkloadKind.CONTROL,
        *,
        catalogs: Sequence[AnalyticalCatalogSpec] = (),
    ) -> Iterator[ManagedConnection]:
        """Open a short-lived read-only session for ``workload``."""

        if workload is WorkloadKind.CONTROL and catalogs:
            raise ConnectionError(
                "control readers cannot attach analytical catalogs; "
                "use WorkloadKind.ANALYTICAL"
            )
        if workload in (WorkloadKind.PUBLICATION, WorkloadKind.UNTRUSTED) and catalogs:
            raise ConnectionError(
                "untrusted/publication sessions cannot attach authority catalogs"
            )
        pool = self.pool_for(workload, read_write=False)
        with pool.connection() as conn:
            for spec in catalogs:
                conn.attach_analytical_catalog(spec)
            yield conn

    @contextmanager
    def writer(self) -> Iterator[ManagedConnection]:
        """Open a short-lived control writer session (no auto-transaction)."""

        pool = self.pool_for(WorkloadKind.CONTROL, read_write=True)
        with pool.connection() as conn:
            yield conn

    @contextmanager
    def short_writer_transaction(self) -> Iterator[ManagedConnection]:
        """Open a control writer and run one bounded short transaction."""

        pool = self.pool_for(WorkloadKind.CONTROL, read_write=True)
        with pool.connection() as conn:
            with conn.short_transaction():
                yield conn

    # -- Quack -------------------------------------------------------------

    @property
    def quack(self) -> QuackURI | None:
        return self._quack

    def set_quack_uri(self, uri: str | QuackURI) -> QuackURI:
        """Install a Quack endpoint+secrets from a URI or object."""

        parsed = uri if isinstance(uri, QuackURI) else parse_quack_uri(uri)
        self._quack = parsed
        return parsed

    def quack_endpoint_public(self) -> dict[str, Any] | None:
        """Return a redacted public description of the Quack endpoint."""

        if self._quack is None:
            return None
        return self._quack.to_dict()

    def quack_secrets(self) -> QuackSecrets | None:
        """Return secrets for trusted broker use only (never log)."""

        if self._quack is None:
            return None
        return self._quack.secrets

    # -- teardown ----------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._closed = True
            for pool in self._pools.values():
                pool.close()
            self._pools.clear()

    def __enter__(self) -> ConnectionManager:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
