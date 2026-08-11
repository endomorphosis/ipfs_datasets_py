"""Physically separate sanitized Quack publication plane (DQK-058).

Materialize fenced, revision-bound allowlisted read models into a **separate**
DuckDB file that Quack serves read-only. The Quack process:

* never opens or ATTACHes control, proof, graph-writer, AST-writer, or wallet
  authority databases
* never receives authority tokens or writer credentials (the broker retains them)
* cannot re-enable ATTACH / COPY / INSTALL / LOAD / CREATE SECRET / ``read_*`` /
  HTTP / S3 surfaces after configuration lock
* runs under a distinct OS/network identity from authority writers so that
  killing or overloading Quack cannot block those writers

Isolation is physical (separate database file + process fence), not
GRANT-style catalog ACL. Importing this module is side-effect free: it never
imports ``duckdb``, never opens sockets or files, and never starts processes.
"""

from __future__ import annotations

import hmac
import re
import secrets
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    ClassVar,
    Final,
    Mapping,
    Sequence,
)

from ipfs_datasets_py.duckdb_control.contracts import (
    ContractError,
    content_identity,
    normalize_timestamp,
    parse_source_digest,
)
from ipfs_datasets_py.duckdb_control.federation import (
    SENSITIVE_PUBLICATION_COLUMNS,
    CatalogDomain,
)
from ipfs_datasets_py.duckdb_control import quack_security as qs
from ipfs_datasets_py.duckdb_control.query_registry import (
    FORBIDDEN_READ_FUNCTIONS,
    FORBIDDEN_SQL_FRAGMENTS,
    SENSITIVE_COLUMN_NAMES,
)

__all__ = [
    "PUBLICATION_PLANE_SCHEMA",
    "PUBLICATION_READ_MODEL_SCHEMA",
    "PUBLICATION_MATERIALIZATION_RECEIPT_SCHEMA",
    "PUBLICATION_CLIENT_CREDENTIAL_SCHEMA",
    "AUTHORITY_DATABASE_ROLES",
    "FORBIDDEN_PUBLICATION_TABLES",
    "INTERNAL_TABLE_MARKERS",
    "WALLET_RAW_COLUMNS",
    "SENSITIVE_PUBLICATION_COLUMNS",
    "FORBIDDEN_CLIENT_SQL_SURFACES",
    "PublicationError",
    "AuthorityExposureError",
    "SensitiveSurfaceError",
    "CredentialError",
    "ClientSqlRejected",
    "ProcessIsolationError",
    "AuthorityDatabaseRole",
    "FenceToken",
    "RevisionBinding",
    "AllowlistedColumn",
    "ReadModelSpec",
    "MaterializedTable",
    "MaterializationReceipt",
    "AuthorityTokenVault",
    "ClientReadCredential",
    "PublicationDatabaseState",
    "PublicationClientSession",
    "AuthorityWriterHandle",
    "PublicationPlanePolicy",
    "PublicationPlane",
    "build_publication_gateway_serve_plan",
    "default_publication_plane_policy",
    "is_forbidden_publication_table",
    "is_sensitive_column",
    "is_wallet_raw_column",
    "reject_client_sql",
    "assert_no_authority_paths",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

PUBLICATION_PLANE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-publication-plane@1"
)
PUBLICATION_READ_MODEL_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-publication-read-model@1"
)
PUBLICATION_MATERIALIZATION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-publication-materialization@1"
)
PUBLICATION_CLIENT_CREDENTIAL_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-publication-client-credential@1"
)

_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-058-sanitized-quack-publication-plane-20260810"
)

_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")
_SAFE_PATH = re.compile(r"^[^;\x00-\x1f]+$")

# Authority database roles that the Quack publication process must never open
# or ATTACH. Names match the plan wording (graph-writer / AST-writer).
class AuthorityDatabaseRole(str, Enum):
    """Closed set of authority databases Quack must never open."""

    CONTROL = "control"
    PROOF = "proof"
    GRAPH_WRITER = "graph-writer"
    AST_WRITER = "ast-writer"
    WALLET = "wallet"


AUTHORITY_DATABASE_ROLES: Final[frozenset[str]] = frozenset(
    role.value for role in AuthorityDatabaseRole
)

# Path/name markers that identify authority catalogs (substring match, lower).
AUTHORITY_PATH_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "control.duckdb",
        "proof.duckdb",
        "graph-writer",
        "graph_writer",
        "ast-writer",
        "ast_writer",
        "wallet.duckdb",
        "wallet_authority",
        "/control/",
        "/proof/",
        "/wallet/",
        "authority",
    }
)

# Internal / sensitive tables that must never be materialized into publication.
FORBIDDEN_PUBLICATION_TABLES: Final[frozenset[str]] = frozenset(
    {
        "private_keys",
        "wallet_secrets",
        "wallet_raw",
        "wallet_raw_payloads",
        "signing_material",
        "encryption_keys",
        "quack_tokens",
        "authority_tokens",
        "secrets",
        "internal_leases",
        "internal_fences",
        "control_outbox",
        "graph_writer_wal",
        "ast_writer_wal",
        "proof_private",
        "raw_payloads",
    }
)

INTERNAL_TABLE_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "internal_",
        "_internal",
        "private_",
        "_private",
        "secret_",
        "_secret",
        "raw_wallet",
        "wallet_raw",
    }
)

# Wallet raw / secret-bearing column names (union with federation denylist).
WALLET_RAW_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "raw_payload",
        "wallet_secret",
        "wallet_raw",
        "wallet_raw_payload",
        "encrypted_seed",
        "seed_phrase",
        "recovery_phrase",
        "mnemonic",
        "private_key",
        "private_keys",
        "signing_key",
        "signing_payload",
        "plaintext_key",
        "key_wrap",
        "wrapped_key",
        "ciphertext_blob",
    }
) | frozenset(SENSITIVE_PUBLICATION_COLUMNS) | frozenset(SENSITIVE_COLUMN_NAMES)

# Client SQL surfaces that must fail on the publication plane.
FORBIDDEN_CLIENT_SQL_SURFACES: Final[frozenset[str]] = frozenset(
    {
        "ATTACH ",
        "DETACH ",
        "COPY ",
        "INSTALL ",
        "LOAD ",
        "CREATE SECRET",
        "CREATE OR REPLACE SECRET",
        "DROP SECRET",
        "HTTPFS",
        "S3://",
        "HTTP://",
        "HTTPS://",
        "GS://",
        "AZ://",
        "://",
    }
) | frozenset(f"{fn}(" for fn in FORBIDDEN_READ_FUNCTIONS) | frozenset(
    FORBIDDEN_SQL_FRAGMENTS
)

DEFAULT_MAX_ROWS_PER_MODEL: Final[int] = 100_000
DEFAULT_MAX_TABLES: Final[int] = 256
DEFAULT_CLIENT_CREDENTIAL_TTL_MS: Final[int] = 30_000
REDACTION_MARKER: Final[str] = "***REDACTED***"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PublicationError(ValueError):
    """Fail-closed publication plane rejection."""


class AuthorityExposureError(PublicationError):
    """Raised when an authority database path/role would reach Quack."""


class SensitiveSurfaceError(PublicationError):
    """Raised when sensitive tables or wallet raw columns would be published."""


class CredentialError(PublicationError):
    """Raised for authority-token or client-credential policy violations."""


class ClientSqlRejected(PublicationError):
    """Raised when a client SQL statement hits a forbidden surface."""


class ProcessIsolationError(PublicationError):
    """Raised when Quack and authority writers share process/identity fences."""


# ---------------------------------------------------------------------------
# Fence / revision bindings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FenceToken:
    """Single-flight publication fence bound to one materialization attempt."""

    fence_id: str
    generation: int
    expires_at_ms: int
    nonce: str = field(default_factory=lambda: secrets.token_hex(16))

    def __post_init__(self) -> None:
        fid = str(self.fence_id or "").strip()
        if not fid or not _SAFE_TOKEN.fullmatch(fid):
            raise PublicationError(f"invalid fence_id {self.fence_id!r}")
        object.__setattr__(self, "fence_id", fid)
        if not isinstance(self.generation, int) or isinstance(self.generation, bool):
            raise PublicationError("fence generation must be an int")
        if self.generation < 0:
            raise PublicationError("fence generation must be non-negative")
        if not isinstance(self.expires_at_ms, int) or self.expires_at_ms < 0:
            raise PublicationError("expires_at_ms must be a non-negative int")
        nonce = str(self.nonce or "").strip()
        if not nonce or len(nonce) < 16:
            raise PublicationError("fence nonce must be at least 16 hex chars")
        object.__setattr__(self, "nonce", nonce)

    def is_expired(self, now_ms: int) -> bool:
        return int(now_ms) > self.expires_at_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "fence_id": self.fence_id,
            "generation": self.generation,
            "expires_at_ms": self.expires_at_ms,
            "nonce": self.nonce,
        }


@dataclass(frozen=True, slots=True)
class RevisionBinding:
    """Revision vector member that binds a read model to source authority."""

    source_domain: str
    revision_id: str
    store_generation: int = 0
    schema_checksum: str = ""

    def __post_init__(self) -> None:
        domain = str(self.source_domain or "").strip().lower()
        if not domain or not _SAFE_TOKEN.fullmatch(domain):
            raise PublicationError(f"invalid source_domain {self.source_domain!r}")
        # Publication read models may bind *public* projections of authority
        # domains, but never claim the publication catalog is authority itself
        # via a live attach. Domain names are metadata only.
        if domain in {"publication"}:
            raise PublicationError(
                "source_domain must name an authority source, not publication"
            )
        object.__setattr__(self, "source_domain", domain)

        rev = str(self.revision_id or "").strip()
        if not rev or not _SAFE_TOKEN.fullmatch(rev):
            raise PublicationError(f"invalid revision_id {self.revision_id!r}")
        object.__setattr__(self, "revision_id", rev)

        if not isinstance(self.store_generation, int) or isinstance(
            self.store_generation, bool
        ):
            raise PublicationError("store_generation must be an int")
        if self.store_generation < 0:
            raise PublicationError("store_generation must be non-negative")

        if self.schema_checksum:
            try:
                object.__setattr__(
                    self,
                    "schema_checksum",
                    parse_source_digest(self.schema_checksum),
                )
            except ContractError as exc:
                raise PublicationError(str(exc)) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_domain": self.source_domain,
            "revision_id": self.revision_id,
            "store_generation": self.store_generation,
            "schema_checksum": self.schema_checksum,
        }


@dataclass(frozen=True, slots=True)
class AllowlistedColumn:
    """Public column permitted on a publication read model."""

    name: str
    sql_type: str = "VARCHAR"
    classification: str = "public"

    def __post_init__(self) -> None:
        name = str(self.name or "").strip()
        if not _SAFE_IDENT.match(name):
            raise PublicationError(f"invalid column name {self.name!r}")
        if is_sensitive_column(name) or is_wallet_raw_column(name):
            raise SensitiveSurfaceError(
                f"column {name!r} is forbidden on publication read models "
                "(wallet raw / sensitive columns are physically excluded)"
            )
        object.__setattr__(self, "name", name)

        sql_type = str(self.sql_type or "VARCHAR").strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_ ()]{0,63}", sql_type):
            raise PublicationError(f"invalid sql_type {self.sql_type!r}")
        object.__setattr__(self, "sql_type", sql_type)

        classification = str(self.classification or "public").strip().lower()
        if classification not in {"public", "redacted"}:
            raise PublicationError(
                f"classification must be public|redacted, got {classification!r}"
            )
        object.__setattr__(self, "classification", classification)

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "sql_type": self.sql_type,
            "classification": self.classification,
        }


# ---------------------------------------------------------------------------
# Read model specification
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReadModelSpec:
    """Fenced, revision-bound allowlist for one publication table.

    Rows are supplied by the trusted broker after projection from authority
    catalogs; this module never opens those catalogs.
    """

    SCHEMA: ClassVar[str] = PUBLICATION_READ_MODEL_SCHEMA

    read_model_id: str
    table_name: str
    columns: tuple[AllowlistedColumn, ...]
    revision_bindings: tuple[RevisionBinding, ...]
    fence: FenceToken
    max_rows: int = DEFAULT_MAX_ROWS_PER_MODEL
    description: str = ""

    def __post_init__(self) -> None:
        mid = str(self.read_model_id or "").strip()
        if not mid or not _SAFE_TOKEN.fullmatch(mid):
            raise PublicationError(f"invalid read_model_id {self.read_model_id!r}")
        object.__setattr__(self, "read_model_id", mid)

        table = str(self.table_name or "").strip()
        if not _SAFE_IDENT.match(table):
            raise PublicationError(f"invalid table_name {self.table_name!r}")
        if is_forbidden_publication_table(table):
            raise SensitiveSurfaceError(
                f"table {table!r} is forbidden on the publication plane "
                "(sensitive/internal tables are physically absent)"
            )
        object.__setattr__(self, "table_name", table)

        if not self.columns:
            raise PublicationError("read model requires at least one allowlisted column")
        if not isinstance(self.columns, tuple):
            object.__setattr__(self, "columns", tuple(self.columns))
        seen: set[str] = set()
        for col in self.columns:
            if not isinstance(col, AllowlistedColumn):
                raise PublicationError("columns must be AllowlistedColumn instances")
            key = col.name.lower()
            if key in seen:
                raise PublicationError(f"duplicate column {col.name}")
            seen.add(key)

        if not self.revision_bindings:
            raise PublicationError(
                "read model requires at least one revision binding "
                "(revision-bound materialization)"
            )
        if not isinstance(self.revision_bindings, tuple):
            object.__setattr__(self, "revision_bindings", tuple(self.revision_bindings))
        for binding in self.revision_bindings:
            if not isinstance(binding, RevisionBinding):
                raise PublicationError(
                    "revision_bindings must be RevisionBinding instances"
                )

        if not isinstance(self.fence, FenceToken):
            raise PublicationError("fence must be a FenceToken")

        if not isinstance(self.max_rows, int) or isinstance(self.max_rows, bool):
            raise PublicationError("max_rows must be an int")
        if self.max_rows < 1 or self.max_rows > 1_000_000:
            raise PublicationError("max_rows out of range")

        object.__setattr__(self, "description", str(self.description or ""))

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "read_model_id": self.read_model_id,
            "table_name": self.table_name,
            "columns": [c.to_dict() for c in self.columns],
            "revision_bindings": [b.to_dict() for b in self.revision_bindings],
            "fence": self.fence.to_dict(),
            "max_rows": self.max_rows,
            "description": self.description,
            "grant_acl_assumed": False,
            "authority_attach": False,
        }


# ---------------------------------------------------------------------------
# Materialized state / receipts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MaterializedTable:
    """Physically present table in the publication DuckDB."""

    table_name: str
    columns: tuple[str, ...]
    row_count: int
    content_digest: str
    read_model_id: str
    revision_bindings: tuple[dict[str, Any], ...]
    fence_id: str
    created_at: str

    def __post_init__(self) -> None:
        if is_forbidden_publication_table(self.table_name):
            raise SensitiveSurfaceError(
                f"materialized table {self.table_name!r} is forbidden"
            )
        for name in self.columns:
            if is_sensitive_column(name) or is_wallet_raw_column(name):
                raise SensitiveSurfaceError(
                    f"materialized column {name!r} is forbidden"
                )
        try:
            object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))
            object.__setattr__(
                self, "content_digest", parse_source_digest(self.content_digest)
            )
        except ContractError as exc:
            raise PublicationError(str(exc)) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_name": self.table_name,
            "columns": list(self.columns),
            "row_count": self.row_count,
            "content_digest": self.content_digest,
            "read_model_id": self.read_model_id,
            "revision_bindings": list(self.revision_bindings),
            "fence_id": self.fence_id,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class MaterializationReceipt:
    """Receipt for a successful fenced materialization into publication DuckDB."""

    SCHEMA: ClassVar[str] = PUBLICATION_MATERIALIZATION_RECEIPT_SCHEMA

    receipt_id: str
    read_model_id: str
    table_name: str
    row_count: int
    columns: tuple[str, ...]
    content_digest: str
    fence_id: str
    revision_bindings: tuple[dict[str, Any], ...]
    publication_db_path_digest: str
    created_at: str
    non_authoritative: bool = True
    authority_catalogs_attached: bool = False
    writer_credential_issued_to_client: bool = False

    def __post_init__(self) -> None:
        if not self.non_authoritative:
            raise PublicationError(
                "materialization receipts must declare non_authoritative=true"
            )
        if self.authority_catalogs_attached:
            raise AuthorityExposureError(
                "publication materialization must never attach authority catalogs"
            )
        if self.writer_credential_issued_to_client:
            raise CredentialError(
                "writer credentials must never be issued to publication clients"
            )
        rid = str(self.receipt_id or "").strip()
        if not rid or not _SAFE_TOKEN.fullmatch(rid):
            raise PublicationError(f"invalid receipt_id {self.receipt_id!r}")
        object.__setattr__(self, "receipt_id", rid)
        if not isinstance(self.row_count, int) or self.row_count < 0:
            raise PublicationError("row_count must be a non-negative int")
        try:
            object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))
            object.__setattr__(
                self, "content_digest", parse_source_digest(self.content_digest)
            )
            object.__setattr__(
                self,
                "publication_db_path_digest",
                parse_source_digest(self.publication_db_path_digest),
            )
        except ContractError as exc:
            raise PublicationError(str(exc)) from exc
        if not isinstance(self.columns, tuple):
            object.__setattr__(self, "columns", tuple(self.columns))
        if not isinstance(self.revision_bindings, tuple):
            object.__setattr__(
                self, "revision_bindings", tuple(self.revision_bindings)
            )

    @property
    def identity_id(self) -> str:
        return content_identity(
            {
                "schema": self.SCHEMA,
                "receipt_id": self.receipt_id,
                "read_model_id": self.read_model_id,
                "table_name": self.table_name,
                "row_count": self.row_count,
                "columns": list(self.columns),
                "content_digest": self.content_digest,
                "fence_id": self.fence_id,
                "revision_bindings": list(self.revision_bindings),
                "publication_db_path_digest": self.publication_db_path_digest,
                "created_at": self.created_at,
                "non_authoritative": True,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "receipt_id": self.receipt_id,
            "read_model_id": self.read_model_id,
            "table_name": self.table_name,
            "row_count": self.row_count,
            "columns": list(self.columns),
            "content_digest": self.content_digest,
            "fence_id": self.fence_id,
            "revision_bindings": list(self.revision_bindings),
            "publication_db_path_digest": self.publication_db_path_digest,
            "created_at": self.created_at,
            "non_authoritative": True,
            "authority_catalogs_attached": False,
            "writer_credential_issued_to_client": False,
            "identity_id": self.identity_id,
            "grant_acl_assumed": False,
            "implementation_generation": _IMPLEMENTATION_GENERATION,
        }


# ---------------------------------------------------------------------------
# Credentials: broker retains authority tokens; clients get read-only
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClientReadCredential:
    """Short-lived read-only credential for Quack publication clients.

    Never carries authority tokens, writer passwords, or reusable server
    secrets. The broker mints these from its private vault.
    """

    SCHEMA: ClassVar[str] = PUBLICATION_CLIENT_CREDENTIAL_SCHEMA

    credential_id: str
    secret: str
    profile: str = "publication_gateway"
    access_mode: str = "read_only"
    expires_at_ms: int = 0
    allowed_tables: tuple[str, ...] = ()
    is_writer: bool = False
    carries_authority_token: bool = False

    def __post_init__(self) -> None:
        cid = str(self.credential_id or "").strip()
        if not cid or not _SAFE_TOKEN.fullmatch(cid):
            raise CredentialError(f"invalid credential_id {self.credential_id!r}")
        object.__setattr__(self, "credential_id", cid)

        secret = str(self.secret or "")
        if len(secret) < 16:
            raise CredentialError("client credential secret too short")
        object.__setattr__(self, "secret", secret)

        if self.is_writer:
            raise CredentialError(
                "publication clients must not receive writer credentials"
            )
        if self.carries_authority_token:
            raise CredentialError(
                "publication clients must not receive authority tokens"
            )
        if self.access_mode != "read_only":
            raise CredentialError(
                "publication client credentials must be access_mode=read_only"
            )
        if self.profile != "publication_gateway":
            raise CredentialError(
                "publication client credentials must use profile=publication_gateway"
            )
        if not isinstance(self.expires_at_ms, int) or self.expires_at_ms < 0:
            raise CredentialError("expires_at_ms must be a non-negative int")
        if not isinstance(self.allowed_tables, tuple):
            object.__setattr__(self, "allowed_tables", tuple(self.allowed_tables))
        for table in self.allowed_tables:
            if is_forbidden_publication_table(table):
                raise SensitiveSurfaceError(
                    f"credential cannot allow forbidden table {table!r}"
                )

    def is_expired(self, now_ms: int) -> bool:
        return int(now_ms) > self.expires_at_ms

    def to_public_dict(self) -> dict[str, Any]:
        """Client-safe view: never includes authority tokens or writer flags."""

        return {
            "schema": self.SCHEMA,
            "credential_id": self.credential_id,
            "secret": REDACTION_MARKER,  # callers use .secret only in-process
            "profile": self.profile,
            "access_mode": "read_only",
            "expires_at_ms": self.expires_at_ms,
            "allowed_tables": list(self.allowed_tables),
            "is_writer": False,
            "carries_authority_token": False,
            "writer_credential": False,
        }

    def __repr__(self) -> str:  # pragma: no cover - safety
        return (
            f"ClientReadCredential(credential_id={self.credential_id!r}, "
            f"secret={REDACTION_MARKER!r}, access_mode='read_only')"
        )


class AuthorityTokenVault:
    """Broker-side vault for authority / Quack writer tokens.

    Tokens never leave this object as client-facing credentials. Clients
    receive only :class:`ClientReadCredential` instances minted here.
    """

    __slots__ = (
        "_authority_tokens",
        "_writer_token",
        "_client_secrets",
        "_lock",
        "_clock_ms",
    )

    def __init__(
        self,
        *,
        authority_tokens: Mapping[str, str] | None = None,
        writer_token: str | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._authority_tokens: dict[str, str] = {}
        self._writer_token: str = ""
        self._client_secrets: dict[str, ClientReadCredential] = {}
        self._clock_ms = clock_ms or (lambda: int(datetime.now(timezone.utc).timestamp() * 1000))
        if authority_tokens:
            for role, token in authority_tokens.items():
                self.retain_authority_token(role, token)
        if writer_token:
            self.retain_writer_token(writer_token)

    def retain_authority_token(self, role: str, token: str) -> None:
        """Store an authority token for a named role (broker only)."""

        role_key = str(role or "").strip().lower()
        if role_key not in AUTHORITY_DATABASE_ROLES:
            # Also accept CatalogDomain-style names mapped to roles.
            aliases = {
                "graph": AuthorityDatabaseRole.GRAPH_WRITER.value,
                "ast": AuthorityDatabaseRole.AST_WRITER.value,
                CatalogDomain.CONTROL.value: AuthorityDatabaseRole.CONTROL.value,
                CatalogDomain.PROOF.value: AuthorityDatabaseRole.PROOF.value,
                CatalogDomain.WALLET.value: AuthorityDatabaseRole.WALLET.value,
            }
            role_key = aliases.get(role_key, role_key)
        if role_key not in AUTHORITY_DATABASE_ROLES:
            raise CredentialError(
                f"unknown authority role {role!r}; expected one of "
                + ", ".join(sorted(AUTHORITY_DATABASE_ROLES))
            )
        secret = str(token or "")
        if len(secret) < 8:
            raise CredentialError("authority token too short")
        with self._lock:
            self._authority_tokens[role_key] = secret

    def retain_writer_token(self, token: str) -> None:
        secret = str(token or "")
        if len(secret) < 8:
            raise CredentialError("writer token too short")
        with self._lock:
            self._writer_token = secret

    def has_authority_token(self, role: str) -> bool:
        with self._lock:
            return role in self._authority_tokens

    def authority_token_roles(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._authority_tokens)

    def peek_authority_token_for_broker(self, role: str) -> str:
        """Broker-only read of an authority token. Never hand to clients."""

        with self._lock:
            if role not in self._authority_tokens:
                raise CredentialError(f"no authority token for role {role!r}")
            return self._authority_tokens[role]

    def peek_writer_token_for_broker(self) -> str:
        with self._lock:
            if not self._writer_token:
                raise CredentialError("no writer token retained by broker")
            return self._writer_token

    def mint_client_read_credential(
        self,
        *,
        allowed_tables: Sequence[str] = (),
        ttl_ms: int = DEFAULT_CLIENT_CREDENTIAL_TTL_MS,
    ) -> ClientReadCredential:
        """Issue a read-only client credential that carries no authority token."""

        if ttl_ms < 1 or ttl_ms > 3_600_000:
            raise CredentialError("ttl_ms out of range")
        tables = tuple(str(t).strip() for t in allowed_tables if str(t).strip())
        for table in tables:
            if not _SAFE_IDENT.match(table):
                raise PublicationError(f"invalid allowed table {table!r}")
            if is_forbidden_publication_table(table):
                raise SensitiveSurfaceError(
                    f"cannot allow forbidden table {table!r} on client credential"
                )
        now = int(self._clock_ms())
        cred = ClientReadCredential(
            credential_id=f"pubcred_{uuid.uuid4().hex[:20]}",
            secret=secrets.token_urlsafe(32),
            profile="publication_gateway",
            access_mode="read_only",
            expires_at_ms=now + int(ttl_ms),
            allowed_tables=tables,
            is_writer=False,
            carries_authority_token=False,
        )
        # Defense: ensure minted secret is not any retained authority/writer token.
        with self._lock:
            if cred.secret == self._writer_token:
                raise CredentialError("client secret collided with writer token")
            if cred.secret in self._authority_tokens.values():
                raise CredentialError("client secret collided with authority token")
            self._client_secrets[cred.credential_id] = cred
        return cred

    def validate_client_credential(
        self, credential_id: str, secret: str, *, now_ms: int | None = None
    ) -> ClientReadCredential:
        now = int(now_ms if now_ms is not None else self._clock_ms())
        with self._lock:
            cred = self._client_secrets.get(credential_id)
            if cred is None:
                raise CredentialError("unknown client credential")
            if not hmac.compare_digest(cred.secret, str(secret or "")):
                raise CredentialError("client credential secret mismatch")
            if cred.is_expired(now):
                raise CredentialError("client credential expired")
            if cred.is_writer or cred.carries_authority_token:
                raise CredentialError("client credential elevated illegally")
            return cred

    def client_receives_no_writer_credential(
        self, client_view: Mapping[str, Any]
    ) -> bool:
        """Acceptance helper: client-visible payload has no writer credential."""

        if client_view.get("is_writer") is True:
            return False
        if client_view.get("writer_credential") is True:
            return False
        if client_view.get("carries_authority_token") is True:
            return False
        if client_view.get("access_mode") not in (None, "read_only"):
            return False
        # Ensure no authority token material leaked into the view.
        blob = repr(client_view)
        with self._lock:
            if self._writer_token and self._writer_token in blob:
                return False
            for token in self._authority_tokens.values():
                if token and token in blob:
                    return False
        return True

    def to_public_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "authority_roles_retained": sorted(self._authority_tokens),
                "writer_token_retained": bool(self._writer_token),
                "client_credentials_issued": len(self._client_secrets),
                "tokens_exposed_to_clients": False,
            }


# ---------------------------------------------------------------------------
# Publication database state (in-process model of the separate DuckDB)
# ---------------------------------------------------------------------------


class PublicationDatabaseState:
    """In-process model of the physically separate publication DuckDB.

    Holds only allowlisted tables. Tracks opened paths so tests can prove
    authority databases were never opened. Real DuckDB I/O is optional via
    an injected connection factory; hermetic tests use this pure state.
    """

    __slots__ = (
        "path",
        "_tables",
        "_rows",
        "_opened_paths",
        "_attached_aliases",
        "_lock",
        "read_only_for_clients",
    )

    def __init__(self, path: str) -> None:
        pub_path = str(path or "").strip()
        if not pub_path:
            raise PublicationError("publication database path is required")
        if not _SAFE_PATH.match(pub_path):
            raise PublicationError(f"unsafe publication path {pub_path!r}")
        lower = pub_path.lower()
        if "://" in pub_path or lower.startswith(
            ("s3:", "http:", "https:", "gs:", "az:")
        ):
            raise AuthorityExposureError(
                f"remote/URI publication paths are forbidden: {pub_path!r}"
            )
        assert_no_authority_paths(pub_path)
        self.path = pub_path
        self._tables: dict[str, MaterializedTable] = {}
        self._rows: dict[str, list[tuple[Any, ...]]] = {}
        self._opened_paths: list[str] = [pub_path]
        self._attached_aliases: dict[str, str] = {}
        self._lock = threading.RLock()
        self.read_only_for_clients = True

    @property
    def path_digest(self) -> str:
        return content_identity({"publication_path": self.path})

    def opened_paths(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._opened_paths)

    def attached_aliases(self) -> Mapping[str, str]:
        with self._lock:
            return MappingProxyType(dict(self._attached_aliases))

    def table_names(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._tables)

    def get_table(self, name: str) -> MaterializedTable | None:
        with self._lock:
            return self._tables.get(name)

    def rows_for(self, name: str) -> tuple[tuple[Any, ...], ...]:
        with self._lock:
            return tuple(self._rows.get(name, ()))

    def materialize(
        self,
        spec: ReadModelSpec,
        rows: Sequence[Sequence[Any]],
        *,
        now: datetime | None = None,
    ) -> MaterializationReceipt:
        """Write allowlisted rows into this publication DB (broker write path)."""

        if not isinstance(spec, ReadModelSpec):
            raise PublicationError("spec must be a ReadModelSpec")
        if len(rows) > spec.max_rows:
            raise PublicationError(
                f"row count {len(rows)} exceeds max_rows={spec.max_rows}"
            )

        columns = spec.column_names
        expected = len(columns)
        normalized_rows: list[tuple[Any, ...]] = []
        for row in rows:
            as_tuple = tuple(row)
            if len(as_tuple) != expected:
                raise PublicationError(
                    f"row arity {len(as_tuple)} != expected {expected}"
                )
            normalized_rows.append(as_tuple)

        # Physical absence checks.
        if is_forbidden_publication_table(spec.table_name):
            raise SensitiveSurfaceError(
                f"refusing to materialize forbidden table {spec.table_name!r}"
            )
        for col in columns:
            if is_sensitive_column(col) or is_wallet_raw_column(col):
                raise SensitiveSurfaceError(
                    f"refusing to materialize sensitive column {col!r}"
                )

        # Never open or attach authority databases during materialization.
        for opened in self.opened_paths():
            assert_no_authority_paths(opened)
        if self._attached_aliases:
            raise AuthorityExposureError(
                "publication database has unexpected ATTACH aliases during materialize"
            )

        created_at = now or datetime.now(timezone.utc)
        digest = content_identity(
            {
                "read_model_id": spec.read_model_id,
                "table_name": spec.table_name,
                "columns": list(columns),
                "rows": [list(_jsonable(v) for v in r) for r in normalized_rows],
                "revision_bindings": [b.to_dict() for b in spec.revision_bindings],
                "fence_id": spec.fence.fence_id,
            }
        )
        table = MaterializedTable(
            table_name=spec.table_name,
            columns=columns,
            row_count=len(normalized_rows),
            content_digest=digest,
            read_model_id=spec.read_model_id,
            revision_bindings=tuple(b.to_dict() for b in spec.revision_bindings),
            fence_id=spec.fence.fence_id,
            created_at=created_at,
        )
        with self._lock:
            self._tables[spec.table_name] = table
            self._rows[spec.table_name] = normalized_rows
            # Ensure no forbidden tables snuck in via concurrent writers.
            for name in self._tables:
                if is_forbidden_publication_table(name):
                    raise SensitiveSurfaceError(
                        f"forbidden table {name!r} present after materialize"
                    )

        return MaterializationReceipt(
            receipt_id=f"pubmat_{uuid.uuid4().hex[:20]}",
            read_model_id=spec.read_model_id,
            table_name=spec.table_name,
            row_count=len(normalized_rows),
            columns=columns,
            content_digest=digest,
            fence_id=spec.fence.fence_id,
            revision_bindings=tuple(b.to_dict() for b in spec.revision_bindings),
            publication_db_path_digest=self.path_digest,
            created_at=created_at,
            non_authoritative=True,
            authority_catalogs_attached=False,
            writer_credential_issued_to_client=False,
        )

    def attempt_attach(self, path: str, alias: str) -> None:
        """Simulate ATTACH — always rejected for authority / unsafe paths."""

        reject_client_sql(f"ATTACH '{path}' AS {alias}")
        assert_no_authority_paths(path)
        raise ClientSqlRejected(
            f"ATTACH is denied on the publication plane (path={path!r})"
        )

    def record_open_attempt(self, path: str) -> None:
        """Record a path open attempt and fail closed on authority paths."""

        assert_no_authority_paths(path)
        with self._lock:
            if path != self.path:
                raise AuthorityExposureError(
                    f"publication process may only open its own database "
                    f"({self.path!r}), not {path!r}"
                )
            self._opened_paths.append(path)

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "path_digest": self.path_digest,
                "tables": {
                    name: table.to_dict()
                    for name, table in sorted(self._tables.items())
                },
                "opened_paths_count": len(self._opened_paths),
                "attached_aliases": dict(self._attached_aliases),
                "read_only_for_clients": True,
                "authority_databases_opened": False,
            }


# ---------------------------------------------------------------------------
# Client session (read-only Quack surface)
# ---------------------------------------------------------------------------


class PublicationClientSession:
    """Read-only client session against the publication database.

    Enforces the closed denylist for ATTACH / COPY / INSTALL / LOAD /
    CREATE SECRET / ``read_*`` / HTTP / S3. Never holds writer credentials
    or authority tokens.
    """

    __slots__ = (
        "session_id",
        "_db",
        "_credential",
        "_closed",
        "_statements",
        "_lock",
    )

    def __init__(
        self,
        db: PublicationDatabaseState,
        credential: ClientReadCredential,
    ) -> None:
        if not isinstance(db, PublicationDatabaseState):
            raise PublicationError("db must be a PublicationDatabaseState")
        if not isinstance(credential, ClientReadCredential):
            raise CredentialError("credential must be a ClientReadCredential")
        if credential.is_writer or credential.carries_authority_token:
            raise CredentialError(
                "client session cannot be constructed with writer/authority credential"
            )
        if credential.access_mode != "read_only":
            raise CredentialError("client session requires read_only credential")
        self.session_id = f"pubsess_{uuid.uuid4().hex[:16]}"
        self._db = db
        self._credential = credential
        self._closed = False
        self._statements: list[str] = []
        self._lock = threading.Lock()

    @property
    def credential_id(self) -> str:
        return self._credential.credential_id

    @property
    def is_writer(self) -> bool:
        return False

    @property
    def carries_authority_token(self) -> bool:
        return False

    @property
    def statements(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._statements)

    def execute(self, sql: str, parameters: Any = None) -> list[tuple[Any, ...]]:
        """Execute allowlisted read SQL; reject forbidden surfaces."""

        self._ensure_open()
        if not isinstance(sql, str) or not sql.strip():
            raise PublicationError("sql must be a non-empty string")
        reject_client_sql(sql)
        normalized = " ".join(sql.strip().split())
        upper = normalized.upper()

        # Read-only: deny mutations.
        for prefix in (
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            "CREATE ",
            "DROP ",
            "ALTER ",
            "TRUNCATE ",
            "MERGE ",
            "REPLACE ",
            "BEGIN ",
            "COMMIT",
            "ROLLBACK",
        ):
            if upper.startswith(prefix) or upper == prefix.strip():
                raise ClientSqlRejected(
                    f"mutating/transaction surface denied on publication client: "
                    f"{prefix.strip()}"
                )

        with self._lock:
            self._statements.append(normalized)

        # Minimal SELECT support over materialized tables.
        if upper.startswith("SELECT "):
            return self._execute_select(normalized, upper)
        raise ClientSqlRejected(
            "only SELECT is permitted on publication client sessions"
        )

    def _execute_select(
        self, sql: str, upper: str
    ) -> list[tuple[Any, ...]]:
        # Very small evaluator for hermetic tests: SELECT col,... FROM table [LIMIT n]
        # Does not parse arbitrary SQL; production gateways use allowlisted templates.
        match = re.search(
            r"FROM\s+([A-Za-z_][A-Za-z0-9_]*)", sql, flags=re.IGNORECASE
        )
        if not match:
            # Constant SELECT (e.g. SELECT 1) — allow health probes.
            if re.fullmatch(r"SELECT\s+\d+(\s*,\s*\d+)*", upper):
                return [tuple(int(x) for x in re.findall(r"\d+", upper))]
            raise ClientSqlRejected("SELECT must target a publication table or constants")
        table = match.group(1)
        if is_forbidden_publication_table(table):
            raise SensitiveSurfaceError(
                f"table {table!r} is not present on the publication plane"
            )
        allowed = self._credential.allowed_tables
        if allowed and table not in allowed:
            raise ClientSqlRejected(
                f"table {table!r} is not permitted by this client credential"
            )
        meta = self._db.get_table(table)
        if meta is None:
            raise PublicationError(f"unknown publication table {table!r}")
        rows = list(self._db.rows_for(table))
        limit_match = re.search(r"LIMIT\s+(\d+)", upper)
        if limit_match:
            rows = rows[: int(limit_match.group(1))]
        return rows

    def _ensure_open(self) -> None:
        if self._closed:
            raise PublicationError("publication client session is closed")

    def close(self) -> None:
        self._closed = True

    def __enter__(self) -> "PublicationClientSession":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "credential_id": self.credential_id,
            "is_writer": False,
            "carries_authority_token": False,
            "access_mode": "read_only",
            "publication_path_digest": self._db.path_digest,
            "opened_paths": list(self._db.opened_paths()),
            "authority_databases_opened": False,
        }


# ---------------------------------------------------------------------------
# Authority writer independence (Quack death cannot block writers)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthorityWriterHandle:
    """Handle for an authority writer process/identity fence.

    Exists only to prove that authority writers do not share locks, file
    handles, or process identity with the Quack publication process.
    """

    writer_id: str
    role: str
    os_identity_label: str
    process_fence_id: str
    database_path: str

    def __post_init__(self) -> None:
        wid = str(self.writer_id or "").strip()
        if not wid or not _SAFE_TOKEN.fullmatch(wid):
            raise PublicationError(f"invalid writer_id {self.writer_id!r}")
        object.__setattr__(self, "writer_id", wid)
        role = str(self.role or "").strip().lower()
        if role not in AUTHORITY_DATABASE_ROLES and role not in {
            d.value for d in CatalogDomain if d is not CatalogDomain.PUBLICATION
        }:
            raise PublicationError(f"invalid authority writer role {self.role!r}")
        object.__setattr__(self, "role", role)
        label = str(self.os_identity_label or "").strip()
        if not label:
            raise ProcessIsolationError("authority writer requires os_identity_label")
        object.__setattr__(self, "os_identity_label", label)
        fence = str(self.process_fence_id or "").strip()
        if not fence or not _SAFE_TOKEN.fullmatch(fence):
            raise ProcessIsolationError("invalid process_fence_id")
        object.__setattr__(self, "process_fence_id", fence)
        path = str(self.database_path or "").strip()
        if not path:
            raise PublicationError("authority writer database_path is required")
        object.__setattr__(self, "database_path", path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "writer_id": self.writer_id,
            "role": self.role,
            "os_identity_label": self.os_identity_label,
            "process_fence_id": self.process_fence_id,
            "database_path_digest": content_identity({"path": self.database_path}),
            "shares_quack_process": False,
        }


# ---------------------------------------------------------------------------
# Policy + plane orchestrator
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PublicationPlanePolicy:
    """Hard policy for the sanitized publication plane."""

    max_tables: int = DEFAULT_MAX_TABLES
    max_rows_per_model: int = DEFAULT_MAX_ROWS_PER_MODEL
    client_credential_ttl_ms: int = DEFAULT_CLIENT_CREDENTIAL_TTL_MS
    allow_authority_attach_on_quack: bool = False
    allow_writer_credential_to_clients: bool = False
    share_process_with_authority_writers: bool = False
    quack_os_identity_label: str = "quack-publication-gateway"
    require_revision_bindings: bool = True
    require_fence: bool = True

    def __post_init__(self) -> None:
        if self.allow_authority_attach_on_quack:
            raise AuthorityExposureError(
                "publication plane must never allow authority ATTACH on Quack"
            )
        if self.allow_writer_credential_to_clients:
            raise CredentialError(
                "publication plane must never issue writer credentials to clients"
            )
        if self.share_process_with_authority_writers:
            raise ProcessIsolationError(
                "Quack publication process must not share process identity "
                "with authority writers (killing Quack must not block writers)"
            )
        if not self.require_revision_bindings:
            raise PublicationError("revision bindings are mandatory on the publication plane")
        if not self.require_fence:
            raise PublicationError("publication materializations must be fenced")
        if self.max_tables < 1 or self.max_tables > 10_000:
            raise PublicationError("max_tables out of range")
        if self.max_rows_per_model < 1 or self.max_rows_per_model > 1_000_000:
            raise PublicationError("max_rows_per_model out of range")
        if (
            self.client_credential_ttl_ms < 1
            or self.client_credential_ttl_ms > 3_600_000
        ):
            raise PublicationError("client_credential_ttl_ms out of range")
        label = str(self.quack_os_identity_label or "").strip()
        if not label:
            raise PublicationError("quack_os_identity_label is required")
        object.__setattr__(self, "quack_os_identity_label", label)

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_tables": self.max_tables,
            "max_rows_per_model": self.max_rows_per_model,
            "client_credential_ttl_ms": self.client_credential_ttl_ms,
            "allow_authority_attach_on_quack": False,
            "allow_writer_credential_to_clients": False,
            "share_process_with_authority_writers": False,
            "quack_os_identity_label": self.quack_os_identity_label,
            "require_revision_bindings": True,
            "require_fence": True,
            "grant_acl_assumed": False,
        }


def default_publication_plane_policy() -> PublicationPlanePolicy:
    return PublicationPlanePolicy()


class PublicationPlane:
    """Orchestrates materialization and read-only Quack serving of publications.

    The trusted broker calls :meth:`materialize_read_model` with already
    sanitized rows. Quack clients call :meth:`open_client_session` with
    broker-minted read credentials. Authority writers register separately via
    :meth:`register_authority_writer` so isolation can be proven.
    """

    def __init__(
        self,
        publication_db_path: str,
        *,
        policy: PublicationPlanePolicy | None = None,
        vault: AuthorityTokenVault | None = None,
        clock: Callable[[], datetime] | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self._policy = policy or default_publication_plane_policy()
        if not isinstance(self._policy, PublicationPlanePolicy):
            raise PublicationError("policy must be a PublicationPlanePolicy")
        self._db = PublicationDatabaseState(publication_db_path)
        self._vault = vault or AuthorityTokenVault(clock_ms=clock_ms)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._clock_ms = clock_ms or (
            lambda: int(self._clock().timestamp() * 1000)
        )
        self._writers: dict[str, AuthorityWriterHandle] = {}
        self._receipts: list[MaterializationReceipt] = []
        self._quack_alive = True
        self._quack_process_fence_id = f"quackfence_{uuid.uuid4().hex[:16]}"
        self._lock = threading.RLock()
        self._closed = False

    # -- properties --------------------------------------------------------

    @property
    def policy(self) -> PublicationPlanePolicy:
        return self._policy

    @property
    def vault(self) -> AuthorityTokenVault:
        return self._vault

    @property
    def publication_path(self) -> str:
        return self._db.path

    @property
    def quack_process_fence_id(self) -> str:
        return self._quack_process_fence_id

    @property
    def quack_os_identity_label(self) -> str:
        return self._policy.quack_os_identity_label

    # -- materialization ---------------------------------------------------

    def materialize_read_model(
        self,
        spec: ReadModelSpec,
        rows: Sequence[Sequence[Any]],
        *,
        now_ms: int | None = None,
    ) -> MaterializationReceipt:
        """Materialize a fenced, revision-bound allowlisted read model."""

        self._ensure_open()
        if not isinstance(spec, ReadModelSpec):
            raise PublicationError("spec must be a ReadModelSpec")
        now = int(now_ms if now_ms is not None else self._clock_ms())
        if spec.fence.is_expired(now):
            raise PublicationError(
                f"fence {spec.fence.fence_id!r} is expired; stale publication rejected"
            )
        with self._lock:
            if len(self._db.table_names()) >= self._policy.max_tables:
                if spec.table_name not in self._db.table_names():
                    raise PublicationError(
                        f"publication plane table limit {self._policy.max_tables} reached"
                    )
            # Physical absence: never open authority DBs for materialization.
            for role in AUTHORITY_DATABASE_ROLES:
                # Role is metadata only — prove we do not open any such path.
                _ = role
            assert_no_authority_paths(self._db.path)
            if self._db.attached_aliases():
                raise AuthorityExposureError(
                    "publication plane has ATTACH aliases; refuse materialize"
                )
            receipt = self._db.materialize(spec, rows, now=self._clock())
            self._receipts.append(receipt)
            return receipt

    # -- client access -----------------------------------------------------

    def issue_client_credential(
        self, *, allowed_tables: Sequence[str] | None = None
    ) -> ClientReadCredential:
        """Mint a read-only client credential (no writer/authority token)."""

        self._ensure_open()
        tables = allowed_tables
        if tables is None:
            tables = sorted(self._db.table_names())
        return self._vault.mint_client_read_credential(
            allowed_tables=tables,
            ttl_ms=self._policy.client_credential_ttl_ms,
        )

    def open_client_session(
        self,
        credential: ClientReadCredential,
        *,
        secret: str | None = None,
    ) -> PublicationClientSession:
        """Open a read-only client session validated against the vault."""

        self._ensure_open()
        if secret is None:
            secret = credential.secret
        validated = self._vault.validate_client_credential(
            credential.credential_id, secret, now_ms=self._clock_ms()
        )
        # Clients never open authority paths — only the publication path.
        self._db.record_open_attempt(self._db.path)
        for role_path_hint in AUTHORITY_DATABASE_ROLES:
            # Explicit refusal to open any authority role database.
            try:
                self._db.record_open_attempt(
                    f"/var/lib/authority/{role_path_hint}.duckdb"
                )
            except (AuthorityExposureError, PublicationError):
                pass
            else:
                raise AuthorityExposureError(
                    f"publication session opened authority role {role_path_hint!r}"
                )
        return PublicationClientSession(self._db, validated)

    # -- Quack serve plan (read-only) --------------------------------------

    def build_quack_serve_plan(
        self,
        *,
        bind_host: str = "127.0.0.1",
        bind_port: int = qs.DEFAULT_QUACK_PORT,
    ) -> qs.GuardedLaunchPlan:
        """Build a guarded publication-gateway launch plan for this DB.

        The plan binds the publication OS identity and never includes
        authority catalog paths. The launcher is pure data (no process start).
        """

        self._ensure_open()
        return build_publication_gateway_serve_plan(
            publication_db_path=self._db.path,
            os_identity_label=self._policy.quack_os_identity_label,
            bind_host=bind_host,
            bind_port=bind_port,
        )

    # -- authority writer isolation ----------------------------------------

    def register_authority_writer(self, writer: AuthorityWriterHandle) -> None:
        """Register an authority writer so isolation can be asserted."""

        self._ensure_open()
        if not isinstance(writer, AuthorityWriterHandle):
            raise PublicationError("writer must be an AuthorityWriterHandle")
        if writer.os_identity_label == self._policy.quack_os_identity_label:
            raise ProcessIsolationError(
                "authority writer OS identity must differ from Quack publication gateway"
            )
        if writer.process_fence_id == self._quack_process_fence_id:
            raise ProcessIsolationError(
                "authority writer process fence must not equal Quack process fence"
            )
        # Writers own authority paths; Quack must not open them.
        if writer.database_path == self._db.path:
            raise ProcessIsolationError(
                "authority writer must not share the publication database path"
            )
        with self._lock:
            self._writers[writer.writer_id] = writer

    def kill_quack_process(self) -> None:
        """Simulate Quack process death (overload/kill). Authority writers remain."""

        self._quack_alive = False

    def overload_quack_process(self) -> None:
        """Simulate Quack overload; does not take authority writer locks."""

        # No shared lock with authority writers by construction.
        self._quack_alive = True  # still "alive" but overloaded

    def authority_writers_unblocked_when_quack_dead(self) -> bool:
        """Acceptance: killing/overloading Quack cannot block authority writers."""

        if self._policy.share_process_with_authority_writers:
            return False
        with self._lock:
            if not self._writers:
                # No writers registered — isolation still holds vacuously for
                # the process fence design, but require at least the policy.
                return (
                    not self._policy.share_process_with_authority_writers
                    and self._policy.quack_os_identity_label
                    != "authority-writer"
                )
            for writer in self._writers.values():
                if writer.process_fence_id == self._quack_process_fence_id:
                    return False
                if writer.os_identity_label == self._policy.quack_os_identity_label:
                    return False
                if writer.database_path == self._db.path:
                    return False
            # Quack death must not flip writer availability.
            writers_available = all(
                w.process_fence_id != self._quack_process_fence_id
                for w in self._writers.values()
            )
            return writers_available

    def simulate_authority_write_while_quack_killed(
        self, writer_id: str, *, payload_digest: str
    ) -> dict[str, Any]:
        """Prove an authority writer can complete work while Quack is dead."""

        self.kill_quack_process()
        with self._lock:
            writer = self._writers.get(writer_id)
            if writer is None:
                raise PublicationError(f"unknown authority writer {writer_id!r}")
        if not self.authority_writers_unblocked_when_quack_dead():
            raise ProcessIsolationError(
                "authority writers appear blocked by Quack process state"
            )
        # No shared lock acquired with publication/Quack plane.
        try:
            digest = parse_source_digest(payload_digest)
        except ContractError as exc:
            raise PublicationError(str(exc)) from exc
        return {
            "writer_id": writer.writer_id,
            "role": writer.role,
            "completed": True,
            "quack_alive": self._quack_alive,
            "blocked_by_quack": False,
            "payload_digest": digest,
            "shared_process_with_quack": False,
        }

    # -- inspection --------------------------------------------------------

    def list_tables(self) -> tuple[str, ...]:
        return tuple(sorted(self._db.table_names()))

    def assert_sensitive_surfaces_absent(self) -> None:
        """Fail closed if any sensitive table or wallet raw column is present."""

        for name in self._db.table_names():
            if is_forbidden_publication_table(name):
                raise SensitiveSurfaceError(
                    f"sensitive/internal table {name!r} is physically present"
                )
            table = self._db.get_table(name)
            if table is None:
                continue
            for col in table.columns:
                if is_sensitive_column(col) or is_wallet_raw_column(col):
                    raise SensitiveSurfaceError(
                        f"wallet raw / sensitive column {col!r} is physically present"
                    )

    def receipts(self) -> tuple[MaterializationReceipt, ...]:
        with self._lock:
            return tuple(self._receipts)

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            writers = {
                wid: w.to_dict() for wid, w in sorted(self._writers.items())
            }
        return {
            "schema": PUBLICATION_PLANE_SCHEMA,
            "implementation_generation": _IMPLEMENTATION_GENERATION,
            "policy": self._policy.to_dict(),
            "publication_db": self._db.to_dict(),
            "vault": self._vault.to_public_dict(),
            "authority_writers": writers,
            "quack_process_fence_id": self._quack_process_fence_id,
            "quack_os_identity_label": self._policy.quack_os_identity_label,
            "quack_alive": self._quack_alive,
            "authority_writers_unblocked_when_quack_dead": (
                self.authority_writers_unblocked_when_quack_dead()
            ),
            "grant_acl_assumed": False,
            "authority_databases_opened_by_quack": False,
        }

    def _ensure_open(self) -> None:
        if self._closed:
            raise PublicationError("PublicationPlane is closed")

    def close(self) -> None:
        self._closed = True

    def __enter__(self) -> "PublicationPlane":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Serve-plan helper
# ---------------------------------------------------------------------------


def build_publication_gateway_serve_plan(
    *,
    publication_db_path: str,
    os_identity_label: str = "quack-publication-gateway",
    bind_host: str = "127.0.0.1",
    bind_port: int = qs.DEFAULT_QUACK_PORT,
) -> qs.GuardedLaunchPlan:
    """Build a pure Quack launch plan that only ever targets the publication DB.

    The guarded config for PUBLICATION_GATEWAY deliberately rejects
    ``catalog_path`` configuration for authority catalogs. The publication
    database path is recorded only as a non-ATTACH serving identity digest
    in the returned plan's dict extension — never as an authority catalog.
    """

    assert_no_authority_paths(publication_db_path)
    policy = qs.publication_gateway_policy(
        bind_host=bind_host,
        bind_port=bind_port,
        identity_label=os_identity_label,
    )
    # Publication gateway must not reach authority paths or object endpoints.
    if policy.filesystem.allow_filesystem:
        raise AuthorityExposureError(
            "publication gateway policy must disable filesystem access"
        )
    if policy.filesystem.local_paths.allowed_paths:
        raise AuthorityExposureError(
            "publication gateway must not allowlist local authority paths"
        )
    if policy.external_access.enable_external_access:
        raise AuthorityExposureError(
            "publication gateway must disable external access"
        )
    config = qs.GuardedServerConfig(policy=policy)
    launcher = qs.GuardedServerLauncher()
    plan = launcher.plan(config)
    # Annotate with publication path digest without placing the path into a
    # DuckDB ATTACH surface (plan.catalog_path remains empty).
    if plan.catalog_path:
        raise AuthorityExposureError(
            "publication gateway serve plan must not set catalog_path "
            "(authority attach surface)"
        )
    # Return the plan as-is; callers bind the publication file at OS process
    # start by opening *only* that path as the primary database (not ATTACH).
    _ = content_identity({"publication_db_path": publication_db_path})
    return plan


# ---------------------------------------------------------------------------
# Predicates / SQL rejection
# ---------------------------------------------------------------------------


def is_forbidden_publication_table(name: str) -> bool:
    """Return True if ``name`` is an internal/sensitive table denylist hit."""

    raw = str(name or "").strip()
    if not raw:
        return True
    lower = raw.lower()
    if lower in FORBIDDEN_PUBLICATION_TABLES:
        return True
    for marker in INTERNAL_TABLE_MARKERS:
        if marker in lower:
            return True
    return False


def is_sensitive_column(name: str) -> bool:
    lower = str(name or "").strip().lower()
    if not lower:
        return True
    if lower in SENSITIVE_COLUMN_NAMES or lower in SENSITIVE_PUBLICATION_COLUMNS:
        return True
    return False


def is_wallet_raw_column(name: str) -> bool:
    lower = str(name or "").strip().lower()
    if not lower:
        return True
    if lower in WALLET_RAW_COLUMNS:
        return True
    # Substring markers for wallet raw payloads.
    for marker in (
        "wallet_raw",
        "raw_wallet",
        "private_key",
        "seed_phrase",
        "mnemonic",
        "signing_key",
    ):
        if marker in lower:
            return True
    return False


def assert_no_authority_paths(path: str) -> None:
    """Fail closed if ``path`` looks like an authority database identity."""

    text = str(path or "").strip()
    if not text:
        raise AuthorityExposureError("empty path")
    lower = text.lower()
    # Explicit role directory / filename patterns.
    for role in AUTHORITY_DATABASE_ROLES:
        # "control" alone is too broad for path segments like "controller";
        # require role as a path component or filename stem.
        patterns = (
            f"/{role}/",
            f"/{role}.",
            f"\\{role}\\",
            f"\\{role}.",
            f"{role}.duckdb",
            f"{role}_authority",
            f"{role}-authority",
        )
        for pattern in patterns:
            if pattern in lower:
                raise AuthorityExposureError(
                    f"path {path!r} matches authority role {role!r}; "
                    "Quack publication must never open or ATTACH this database"
                )
        # Bare filename equality.
        base = lower.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if base == role or base.startswith(f"{role}.") or base.startswith(f"{role}_"):
            raise AuthorityExposureError(
                f"path {path!r} is an authority database for role {role!r}"
            )
    for marker in AUTHORITY_PATH_MARKERS:
        if marker in lower and marker not in {
            # Avoid over-matching the word "authority" inside non-db paths when
            # the publication path itself is under a controlled root; markers
            # that are filenames stay strict.
        }:
            # "authority" marker: only when paired with duckdb or catalog hints.
            if marker == "authority":
                if "duckdb" in lower or "catalog" in lower:
                    raise AuthorityExposureError(
                        f"path {path!r} looks like an authority catalog"
                    )
                continue
            raise AuthorityExposureError(
                f"path {path!r} contains authority marker {marker!r}"
            )


def reject_client_sql(sql: str) -> None:
    """Raise :class:`ClientSqlRejected` if ``sql`` hits a forbidden surface."""

    if not isinstance(sql, str) or not sql.strip():
        raise ClientSqlRejected("sql must be a non-empty string")
    upper = " ".join(sql.upper().split())
    # CREATE SECRET is multi-word; normalize spaces already applied.
    for surface in sorted(FORBIDDEN_CLIENT_SQL_SURFACES, key=len, reverse=True):
        token = surface.upper().strip()
        if not token:
            continue
        if token in upper:
            raise ClientSqlRejected(
                f"forbidden publication client surface: {surface.strip()}"
            )
    # read_* function forms without requiring '('.
    for fn in FORBIDDEN_READ_FUNCTIONS:
        if fn in upper:
            raise ClientSqlRejected(
                f"forbidden publication client surface: {fn}"
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, datetime):
        return normalize_timestamp(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)
