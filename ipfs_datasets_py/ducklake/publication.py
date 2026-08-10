"""Fenced DuckLake → Quack publication sanitizer (DQK-097).

Copy-publishes approved snapshot-bound aggregates into a **physically
separate** Quack publication DuckDB without attaching the authority DuckLake
catalog. The sanitized publication Quack process:

* runs under a distinct OS/network identity from the DQK-104 catalog owner
* cannot reach authority catalog files, companion registries, object storage,
  or secret endpoints
* cannot INSTALL/LOAD ducklake, quack, or httpfs
* cannot open or ATTACH the DuckLake authority catalog

Only the distinct broker-owned DQK-104 catalog owner holds a narrowly scoped
authority attachment. Publication rows bind sanitizer policy, source snapshot
vector, schema, and digest.

Import is side-effect free: no ``duckdb``, sockets, extension LOAD, or secret
resolution occurs at import time.
"""

from __future__ import annotations

import hashlib
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

from ipfs_datasets_py.ducklake import security as sec

__all__ = [
    "LAKE_PUBLICATION_SCHEMA",
    "SANITIZER_POLICY_SCHEMA",
    "PUBLICATION_ROW_SCHEMA",
    "PUBLICATION_RECEIPT_SCHEMA",
    "FORBIDDEN_PUBLICATION_EXTENSIONS",
    "FORBIDDEN_PUBLICATION_SQL_SURFACES",
    "AUTHORITY_REACHABILITY_TARGETS",
    "PublicationError",
    "AuthorityAttachDenied",
    "PublicationIdentityError",
    "SanitizerPolicyError",
    "ExtensionDenied",
    "PublicationReachabilityError",
    "SanitizerPolicy",
    "SnapshotVectorBinding",
    "PublicationIdentity",
    "CatalogOwnerAttachment",
    "PublicationRow",
    "PublicationReceipt",
    "LakePublicationPlane",
    "default_sanitizer_policy",
    "default_publication_identity",
    "assert_publication_cannot_attach_authority",
    "assert_publication_extensions_denied",
    "assert_publication_reachability_denied",
    "reject_publication_sql",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

LAKE_PUBLICATION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-publication-plane@1"
)
SANITIZER_POLICY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-publication-sanitizer-policy@1"
)
PUBLICATION_ROW_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-publication-row@1"
)
PUBLICATION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-publication-receipt@1"
)

_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-097-ducklake-publication-sanitizer-20260810"
)

FORBIDDEN_PUBLICATION_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        "ducklake",
        "quack",
        "httpfs",
        "aws",
        "azure",
        "gcp",
        "sqlite_scanner",
        "postgres_scanner",
    }
)

FORBIDDEN_PUBLICATION_SQL_SURFACES: Final[frozenset[str]] = frozenset(
    {
        "ATTACH ",
        "DETACH ",
        "INSTALL ",
        "LOAD ",
        "CREATE SECRET",
        "CREATE OR REPLACE SECRET",
        "DROP SECRET",
        "COPY ",
        "S3://",
        "GS://",
        "AZ://",
        "HTTP://",
        "HTTPS://",
        "READ_PARQUET(",
        "READ_CSV(",
        "READ_JSON(",
        "DUCKLAKE:",
    }
)

AUTHORITY_REACHABILITY_TARGETS: Final[frozenset[str]] = frozenset(
    {
        "authority_catalog",
        "companion_registry",
        "object_storage",
        "secret_endpoint",
        "catalog_file",
        "registry_file",
        "s3_endpoint",
        "vault_endpoint",
    }
)

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{0,255}$")
_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")

DEFAULT_MAX_ROWS: Final[int] = 100_000
REDACTION_MARKER: Final[str] = sec.REDACTION_MARKER


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PublicationError(ValueError):
    """Fail-closed DuckLake publication sanitizer rejection."""


class AuthorityAttachDenied(PublicationError):
    """Publication process attempted to open/ATTACH the authority catalog."""


class PublicationIdentityError(PublicationError):
    """Publication OS/network identity violated isolation invariants."""


class SanitizerPolicyError(PublicationError):
    """Sanitizer policy binding or evaluation failed."""


class ExtensionDenied(PublicationError):
    """INSTALL/LOAD of a forbidden extension was rejected."""


class PublicationReachabilityError(PublicationError):
    """Publication identity attempted to reach a forbidden network/file target."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_nonempty(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PublicationError(f"{field_name} is required")
    return text


def _require_safe_token(value: Any, *, field_name: str) -> str:
    text = _require_nonempty(value, field_name=field_name)
    if not _SAFE_TOKEN.match(text):
        raise PublicationError(f"invalid {field_name} {value!r}")
    return text


def _require_safe_ident(value: Any, *, field_name: str) -> str:
    text = _require_nonempty(value, field_name=field_name)
    if not _SAFE_IDENT.match(text):
        raise PublicationError(f"invalid {field_name} {value!r}")
    return text


def _normalize_digest(value: str, *, field_name: str = "digest") -> str:
    text = str(value or "").strip().lower()
    if not _SHA256_RE.match(text):
        raise PublicationError(f"{field_name} must be a sha256 digest")
    if not text.startswith("sha256:"):
        text = f"sha256:{text}"
    return text


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Public assertions
# ---------------------------------------------------------------------------


def assert_publication_cannot_attach_authority(
    *,
    publication_identity: "PublicationIdentity",
    authority_catalog_path: str,
) -> None:
    """Fail closed: publication process cannot open or ATTACH authority."""

    if publication_identity.may_attach_authority_catalog:
        raise AuthorityAttachDenied(
            "publication identity must never may_attach_authority_catalog"
        )
    if publication_identity.may_open_authority_catalog:
        raise AuthorityAttachDenied(
            "publication identity must never may_open_authority_catalog"
        )
    path = str(authority_catalog_path or "").strip()
    if not path:
        raise AuthorityAttachDenied("authority_catalog_path is required for denial")
    raise AuthorityAttachDenied(
        "sanitized publication Quack process cannot open or ATTACH the "
        f"DuckLake authority catalog at {path!r}; only the distinct "
        "broker-owned DQK-104 catalog owner has a narrowly scoped attachment"
    )


def assert_publication_extensions_denied(extension: str) -> None:
    """Fail closed for INSTALL/LOAD of ducklake, quack, or httpfs."""

    name = str(extension or "").strip().lower()
    if not name:
        raise ExtensionDenied("extension name is required")
    # Strip version suffixes like ducklake@1.5.5+core
    base = name.split("@", 1)[0].split(" ", 1)[0]
    if base in FORBIDDEN_PUBLICATION_EXTENSIONS or name in FORBIDDEN_PUBLICATION_EXTENSIONS:
        raise ExtensionDenied(
            f"sanitized publication Quack cannot INSTALL/LOAD {base!r}"
        )
    raise ExtensionDenied(
        f"sanitized publication Quack refuses extension {name!r}"
    )


def assert_publication_reachability_denied(
    target: str,
    *,
    publication_identity: "PublicationIdentity | None" = None,
) -> None:
    """Fail closed when publication identity reaches forbidden targets."""

    normalized = str(target or "").strip().lower().replace("-", "_").replace(" ", "_")
    if publication_identity is not None:
        if not publication_identity.isolated_from_authority:
            raise PublicationReachabilityError(
                "publication identity must be isolated from authority surfaces"
            )
    if normalized in AUTHORITY_REACHABILITY_TARGETS or any(
        marker in normalized for marker in AUTHORITY_REACHABILITY_TARGETS
    ):
        raise PublicationReachabilityError(
            f"sanitized publication Quack OS/network identity cannot reach "
            f"{normalized!r}"
        )
    # Paths that look like authority catalogs / registries / secrets.
    lowered = normalized
    markers = (
        "catalog.duckdb",
        "companion",
        "registry.duckdb",
        "s3://",
        "gs://",
        "secret",
        "vault",
        "/authority/",
        "ducklake:",
    )
    if any(m in lowered for m in markers):
        raise PublicationReachabilityError(
            f"sanitized publication Quack OS/network identity cannot reach "
            f"{target!r}"
        )
    raise PublicationReachabilityError(
        f"publication reachability denied for target {target!r}"
    )


def reject_publication_sql(sql: str) -> None:
    """Reject forbidden SQL surfaces on the publication plane."""

    text = str(sql or "")
    if not text.strip():
        raise PublicationError("empty SQL rejected")
    upper = text.upper()
    # ATTACH/DETACH are authority-boundary violations (not generic SQL noise).
    if re.search(r"(?i)\bATTACH\b", text):
        raise AuthorityAttachDenied(
            "publication process cannot ATTACH; authority catalogs are never "
            "attached on the publication plane"
        )
    if re.search(r"(?i)\bDETACH\b", text):
        raise AuthorityAttachDenied(
            "publication process cannot DETACH authority catalogs"
        )
    # Extension names as INSTALL/LOAD targets.
    for ext in FORBIDDEN_PUBLICATION_EXTENSIONS:
        if re.search(rf"(?i)\b(?:INSTALL|LOAD)\s+{re.escape(ext)}\b", text):
            raise ExtensionDenied(
                f"sanitized publication Quack cannot INSTALL/LOAD {ext!r}"
            )
    for surface in FORBIDDEN_PUBLICATION_SQL_SURFACES:
        if surface in upper:
            raise PublicationError(
                f"publication plane rejects SQL surface {surface.strip()!r}"
            )


# ---------------------------------------------------------------------------
# Policies / bindings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SanitizerPolicy:
    """Policy that governs which aggregates may be copy-published."""

    policy_id: str
    allowlisted_tables: frozenset[str]
    allowlisted_columns: frozenset[str]
    max_rows: int = DEFAULT_MAX_ROWS
    redact_sensitive: bool = True
    forbid_authority_attach: bool = True
    forbid_extensions: frozenset[str] = field(
        default_factory=lambda: frozenset(FORBIDDEN_PUBLICATION_EXTENSIONS)
    )
    require_snapshot_binding: bool = True
    require_schema_digest: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "policy_id",
            _require_safe_token(self.policy_id, field_name="policy_id"),
        )
        tables = frozenset(
            _require_safe_ident(t, field_name="allowlisted_tables")
            for t in self.allowlisted_tables
        )
        if not tables:
            raise SanitizerPolicyError("allowlisted_tables must be non-empty")
        object.__setattr__(self, "allowlisted_tables", tables)
        columns = frozenset(
            _require_safe_ident(c, field_name="allowlisted_columns")
            for c in self.allowlisted_columns
        )
        if not columns:
            raise SanitizerPolicyError("allowlisted_columns must be non-empty")
        # Sensitive columns never allowlisted.
        for col in columns:
            if sec.is_sensitive_key(col):
                raise SanitizerPolicyError(
                    f"column {col!r} is sensitive and cannot be published"
                )
        object.__setattr__(self, "allowlisted_columns", columns)
        if (
            not isinstance(self.max_rows, int)
            or isinstance(self.max_rows, bool)
            or self.max_rows < 1
            or self.max_rows > 1_000_000
        ):
            raise SanitizerPolicyError("max_rows out of range")
        if not self.forbid_authority_attach:
            raise SanitizerPolicyError(
                "sanitizer policy must forbid authority catalog attach"
            )
        if not self.redact_sensitive:
            raise SanitizerPolicyError(
                "sanitizer policy must redact sensitive material"
            )
        forb = frozenset(str(x).strip().lower() for x in self.forbid_extensions)
        for required in ("ducklake", "quack", "httpfs"):
            if required not in forb:
                raise SanitizerPolicyError(
                    f"sanitizer policy must forbid extension {required!r}"
                )
        object.__setattr__(self, "forbid_extensions", forb)
        if not self.require_snapshot_binding:
            raise SanitizerPolicyError(
                "sanitizer policy must require source snapshot vector binding"
            )
        if not self.require_schema_digest:
            raise SanitizerPolicyError(
                "sanitizer policy must require schema digest binding"
            )

    def permits_table(self, table: str) -> bool:
        return str(table or "").strip() in self.allowlisted_tables

    def permits_column(self, column: str) -> bool:
        return str(column or "").strip() in self.allowlisted_columns

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": SANITIZER_POLICY_SCHEMA,
                "policy_id": self.policy_id,
                "allowlisted_tables": sorted(self.allowlisted_tables),
                "allowlisted_columns": sorted(self.allowlisted_columns),
                "max_rows": self.max_rows,
                "redact_sensitive": self.redact_sensitive,
                "forbid_authority_attach": self.forbid_authority_attach,
                "forbid_extensions": sorted(self.forbid_extensions),
                "require_snapshot_binding": self.require_snapshot_binding,
                "require_schema_digest": self.require_schema_digest,
            }
        )


def default_sanitizer_policy(
    *,
    policy_id: str = "sanitizer-default",
    tables: Sequence[str] = ("public_aggregates", "public_datasets"),
    columns: Sequence[str] = (
        "dataset_id",
        "catalog_id",
        "row_count",
        "snapshot_id",
        "content_digest",
    ),
    max_rows: int = DEFAULT_MAX_ROWS,
) -> SanitizerPolicy:
    return SanitizerPolicy(
        policy_id=policy_id,
        allowlisted_tables=frozenset(tables),
        allowlisted_columns=frozenset(columns),
        max_rows=max_rows,
    )


@dataclass(frozen=True, slots=True)
class SnapshotVectorBinding:
    """Source snapshot vector identity bound into every publication row."""

    vector_id: str
    vector_digest: str
    members: tuple[Mapping[str, Any], ...]
    schema_version: str
    schema_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "vector_id",
            _require_safe_token(self.vector_id, field_name="vector_id"),
        )
        object.__setattr__(
            self,
            "vector_digest",
            _normalize_digest(self.vector_digest, field_name="vector_digest"),
        )
        members = tuple(dict(m) for m in (self.members or ()))
        if not members:
            raise PublicationError(
                "snapshot vector binding requires at least one member"
            )
        # Scrub any accidental secrets from member projections.
        clean_members = tuple(
            sec.scrub_sensitive_projection(m) for m in members
        )
        object.__setattr__(self, "members", clean_members)
        object.__setattr__(
            self,
            "schema_version",
            _require_nonempty(self.schema_version, field_name="schema_version"),
        )
        object.__setattr__(
            self,
            "schema_digest",
            _normalize_digest(self.schema_digest, field_name="schema_digest"),
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "vector_id": self.vector_id,
                "vector_digest": self.vector_digest,
                "members": [dict(m) for m in self.members],
                "schema_version": self.schema_version,
                "schema_digest": self.schema_digest,
            }
        )


@dataclass(frozen=True, slots=True)
class PublicationIdentity:
    """OS/network identity of the sanitized publication Quack process."""

    os_identity: str
    network_identity: str
    publication_db_path: str
    may_open_authority_catalog: bool = False
    may_attach_authority_catalog: bool = False
    may_reach_companion_registry: bool = False
    may_reach_object_storage: bool = False
    may_reach_secret_endpoints: bool = False
    may_install_extensions: bool = False
    may_load_extensions: bool = False
    distinct_from_catalog_owner: bool = True

    def __post_init__(self) -> None:
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
        path = _require_nonempty(
            self.publication_db_path, field_name="publication_db_path"
        )
        # Publication path must not look like an authority catalog.
        lowered = path.lower()
        for marker in (
            "authority",
            "catalog.duckdb",
            "companion",
            "registry.duckdb",
            "control.duckdb",
        ):
            if marker in lowered and "publication" not in lowered:
                raise PublicationIdentityError(
                    f"publication_db_path must not reference authority path "
                    f"markers; got {path!r}"
                )
        object.__setattr__(self, "publication_db_path", path)
        if self.may_open_authority_catalog or self.may_attach_authority_catalog:
            raise PublicationIdentityError(
                "publication identity cannot open or ATTACH authority catalogs"
            )
        if self.may_reach_companion_registry:
            raise PublicationIdentityError(
                "publication identity cannot reach companion registries"
            )
        if self.may_reach_object_storage:
            raise PublicationIdentityError(
                "publication identity cannot reach object storage"
            )
        if self.may_reach_secret_endpoints:
            raise PublicationIdentityError(
                "publication identity cannot reach secret endpoints"
            )
        if self.may_install_extensions or self.may_load_extensions:
            raise PublicationIdentityError(
                "publication identity cannot INSTALL/LOAD extensions "
                "(including ducklake, quack, httpfs)"
            )
        if not self.distinct_from_catalog_owner:
            raise PublicationIdentityError(
                "publication identity must be distinct from the DQK-104 "
                "catalog owner"
            )

    @property
    def isolated_from_authority(self) -> bool:
        return (
            not self.may_open_authority_catalog
            and not self.may_attach_authority_catalog
            and not self.may_reach_companion_registry
            and not self.may_reach_object_storage
            and not self.may_reach_secret_endpoints
            and self.distinct_from_catalog_owner
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "os_identity": self.os_identity,
                "network_identity": self.network_identity,
                "publication_db_path": self.publication_db_path,
                "may_open_authority_catalog": False,
                "may_attach_authority_catalog": False,
                "may_reach_companion_registry": False,
                "may_reach_object_storage": False,
                "may_reach_secret_endpoints": False,
                "may_install_extensions": False,
                "may_load_extensions": False,
                "distinct_from_catalog_owner": True,
                "isolated_from_authority": True,
            }
        )


def default_publication_identity(
    *,
    publication_db_path: str = "/var/lib/publication/ducklake_public.duckdb",
    catalog_id: str = "catalog-a",
) -> PublicationIdentity:
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", catalog_id).strip("_").lower() or "catalog"
    return PublicationIdentity(
        os_identity=f"ducklake_{safe}_publication",
        network_identity=f"net_{safe}_publication",
        publication_db_path=publication_db_path,
    )


@dataclass(frozen=True, slots=True)
class CatalogOwnerAttachment:
    """Narrowly scoped authority attachment held only by DQK-104 owner."""

    owner_process_id: str
    catalog_id: str
    catalog_path: str
    endpoint_id: str
    owner_generation: int
    broker_owned: bool = True
    attach_mode: str = "safe"
    create_if_not_exists: bool = False
    override_data_path: bool = False
    automatic_migration: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "owner_process_id",
            _require_safe_token(self.owner_process_id, field_name="owner_process_id"),
        )
        object.__setattr__(
            self,
            "catalog_id",
            _require_safe_token(self.catalog_id, field_name="catalog_id"),
        )
        object.__setattr__(
            self,
            "catalog_path",
            _require_nonempty(self.catalog_path, field_name="catalog_path"),
        )
        object.__setattr__(
            self,
            "endpoint_id",
            _require_safe_token(self.endpoint_id, field_name="endpoint_id"),
        )
        if (
            not isinstance(self.owner_generation, int)
            or isinstance(self.owner_generation, bool)
            or self.owner_generation < 1
        ):
            raise PublicationError("owner_generation must be a positive int")
        if not self.broker_owned:
            raise PublicationError(
                "DQK-104 catalog owner attachment must be broker-owned"
            )
        mode = str(self.attach_mode or "").strip().lower()
        if mode != "safe":
            raise PublicationError(
                "publication-adjacent owner attachment must use safe attach mode"
            )
        object.__setattr__(self, "attach_mode", mode)
        if (
            self.create_if_not_exists
            or self.override_data_path
            or self.automatic_migration
        ):
            raise PublicationError(
                "narrow owner attachment requires CREATE_IF_NOT_EXISTS=false, "
                "OVERRIDE_DATA_PATH=false, AUTOMATIC_MIGRATION=false"
            )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "owner_process_id": self.owner_process_id,
                "catalog_id": self.catalog_id,
                "catalog_path": self.catalog_path,
                "endpoint_id": self.endpoint_id,
                "owner_generation": self.owner_generation,
                "broker_owned": True,
                "attach_mode": self.attach_mode,
                "CREATE_IF_NOT_EXISTS": False,
                "OVERRIDE_DATA_PATH": False,
                "AUTOMATIC_MIGRATION": False,
                "dqk104_catalog_owner": True,
            }
        )


# ---------------------------------------------------------------------------
# Publication rows / receipts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PublicationRow:
    """One published aggregate row bound to policy, vector, schema, digest."""

    row_id: str
    table_name: str
    payload: Mapping[str, Any]
    sanitizer_policy_id: str
    snapshot_vector: SnapshotVectorBinding
    schema_version: str
    schema_digest: str
    content_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "row_id", _require_safe_token(self.row_id, field_name="row_id")
        )
        object.__setattr__(
            self,
            "table_name",
            _require_safe_ident(self.table_name, field_name="table_name"),
        )
        if not isinstance(self.snapshot_vector, SnapshotVectorBinding):
            raise PublicationError("snapshot_vector binding is required")
        object.__setattr__(
            self,
            "sanitizer_policy_id",
            _require_safe_token(
                self.sanitizer_policy_id, field_name="sanitizer_policy_id"
            ),
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_nonempty(self.schema_version, field_name="schema_version"),
        )
        object.__setattr__(
            self,
            "schema_digest",
            _normalize_digest(self.schema_digest, field_name="schema_digest"),
        )
        # Schema binding must match the snapshot vector schema.
        if self.schema_version != self.snapshot_vector.schema_version:
            raise PublicationError(
                "publication row schema_version must match snapshot vector"
            )
        if self.schema_digest != self.snapshot_vector.schema_digest:
            raise PublicationError(
                "publication row schema_digest must match snapshot vector"
            )
        payload = sec.scrub_sensitive_projection(dict(self.payload or {}))
        if not payload:
            raise PublicationError("publication row payload must be non-empty")
        for key in payload:
            if sec.is_sensitive_key(str(key)):
                raise PublicationError(
                    f"publication row cannot include sensitive column {key!r}"
                )
        object.__setattr__(self, "payload", MappingProxyType(payload))
        # Content digest: provided or computed from bound fields.
        digest = str(self.content_digest or "").strip()
        if digest:
            object.__setattr__(
                self,
                "content_digest",
                _normalize_digest(digest, field_name="content_digest"),
            )
        else:
            body = {
                "row_id": self.row_id,
                "table_name": self.table_name,
                "payload": payload,
                "sanitizer_policy_id": self.sanitizer_policy_id,
                "snapshot_vector": dict(self.snapshot_vector.as_mapping()),
                "schema_version": self.schema_version,
                "schema_digest": self.schema_digest,
            }
            object.__setattr__(self, "content_digest", _sha256_text(_canonical_json(body)))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": PUBLICATION_ROW_SCHEMA,
                "row_id": self.row_id,
                "table_name": self.table_name,
                "payload": dict(self.payload),
                "sanitizer_policy_id": self.sanitizer_policy_id,
                "snapshot_vector": dict(self.snapshot_vector.as_mapping()),
                "schema_version": self.schema_version,
                "schema_digest": self.schema_digest,
                "content_digest": self.content_digest,
                "authority_catalog_attached": False,
            }
        )


@dataclass(frozen=True, slots=True)
class PublicationReceipt:
    """Receipt for a fenced copy-publish into the publication DuckDB."""

    receipt_id: str
    publication_id: str
    table_name: str
    row_count: int
    content_digest: str
    sanitizer_policy_id: str
    snapshot_vector_id: str
    snapshot_vector_digest: str
    schema_version: str
    schema_digest: str
    publication_db_path_digest: str
    created_at_unix: float
    authority_catalog_attached: bool = False
    extensions_loaded: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "receipt_id",
            _require_safe_token(self.receipt_id, field_name="receipt_id"),
        )
        object.__setattr__(
            self,
            "publication_id",
            _require_safe_token(self.publication_id, field_name="publication_id"),
        )
        object.__setattr__(
            self,
            "table_name",
            _require_safe_ident(self.table_name, field_name="table_name"),
        )
        if (
            not isinstance(self.row_count, int)
            or isinstance(self.row_count, bool)
            or self.row_count < 0
        ):
            raise PublicationError("row_count must be a non-negative int")
        object.__setattr__(
            self,
            "content_digest",
            _normalize_digest(self.content_digest, field_name="content_digest"),
        )
        object.__setattr__(
            self,
            "sanitizer_policy_id",
            _require_safe_token(
                self.sanitizer_policy_id, field_name="sanitizer_policy_id"
            ),
        )
        object.__setattr__(
            self,
            "snapshot_vector_id",
            _require_safe_token(
                self.snapshot_vector_id, field_name="snapshot_vector_id"
            ),
        )
        object.__setattr__(
            self,
            "snapshot_vector_digest",
            _normalize_digest(
                self.snapshot_vector_digest, field_name="snapshot_vector_digest"
            ),
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_nonempty(self.schema_version, field_name="schema_version"),
        )
        object.__setattr__(
            self,
            "schema_digest",
            _normalize_digest(self.schema_digest, field_name="schema_digest"),
        )
        object.__setattr__(
            self,
            "publication_db_path_digest",
            _normalize_digest(
                self.publication_db_path_digest,
                field_name="publication_db_path_digest",
            ),
        )
        if self.authority_catalog_attached:
            raise AuthorityAttachDenied(
                "publication receipt must never record authority catalog attach"
            )
        if self.extensions_loaded:
            raise ExtensionDenied(
                "publication receipt must not record loaded extensions; "
                "publication process cannot INSTALL/LOAD ducklake/quack/httpfs"
            )
        object.__setattr__(self, "extensions_loaded", ())

    def as_mapping(self) -> Mapping[str, Any]:
        payload = {
            "schema": PUBLICATION_RECEIPT_SCHEMA,
            "receipt_id": self.receipt_id,
            "publication_id": self.publication_id,
            "table_name": self.table_name,
            "row_count": self.row_count,
            "content_digest": self.content_digest,
            "sanitizer_policy_id": self.sanitizer_policy_id,
            "snapshot_vector_id": self.snapshot_vector_id,
            "snapshot_vector_digest": self.snapshot_vector_digest,
            "schema_version": self.schema_version,
            "schema_digest": self.schema_digest,
            "publication_db_path_digest": self.publication_db_path_digest,
            "created_at_unix": self.created_at_unix,
            "authority_catalog_attached": False,
            "extensions_loaded": [],
            "copy_publish": True,
            "implementation_generation": _IMPLEMENTATION_GENERATION,
        }
        return MappingProxyType(sec.scrub_sensitive_projection(payload))


# ---------------------------------------------------------------------------
# Publication plane
# ---------------------------------------------------------------------------


class LakePublicationPlane:
    """In-memory fenced sanitizer that copy-publishes snapshot-bound rows.

    Never attaches the authority lake catalog. The broker supplies already-
    sanitized row payloads; this plane only validates policy bindings and
    stores them in a separate publication database projection.
    """

    def __init__(
        self,
        *,
        identity: PublicationIdentity | None = None,
        policy: SanitizerPolicy | None = None,
        catalog_owner: CatalogOwnerAttachment | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.identity = identity or default_publication_identity()
        self.policy = policy or default_sanitizer_policy()
        self.catalog_owner = catalog_owner
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._tables: dict[str, list[PublicationRow]] = {}
        self._receipts: list[PublicationReceipt] = []
        self._authority_attached = False
        self._loaded_extensions: set[str] = set()
        # Enforce isolation at construction.
        if not self.identity.isolated_from_authority:
            raise PublicationIdentityError(
                "publication plane requires isolated publication identity"
            )
        if self.catalog_owner is not None:
            if (
                self.catalog_owner.owner_process_id
                == self.identity.os_identity
            ):
                raise PublicationIdentityError(
                    "publication OS identity must differ from DQK-104 catalog "
                    "owner process"
                )

    @property
    def authority_catalog_attached(self) -> bool:
        return self._authority_attached

    def list_tables(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._tables))

    def row_count(self, table_name: str) -> int:
        with self._lock:
            return len(self._tables.get(table_name, ()))

    def receipts(self) -> tuple[PublicationReceipt, ...]:
        with self._lock:
            return tuple(self._receipts)

    def attempt_attach_authority(self, catalog_path: str) -> None:
        """Always fails: publication cannot ATTACH authority catalogs."""

        assert_publication_cannot_attach_authority(
            publication_identity=self.identity,
            authority_catalog_path=catalog_path,
        )

    def attempt_install_extension(self, extension: str) -> None:
        assert_publication_extensions_denied(extension)

    def attempt_load_extension(self, extension: str) -> None:
        assert_publication_extensions_denied(extension)

    def attempt_reach(self, target: str) -> None:
        assert_publication_reachability_denied(
            target, publication_identity=self.identity
        )

    def execute_client_sql(self, sql: str) -> None:
        reject_publication_sql(sql)

    def copy_publish(
        self,
        *,
        table_name: str,
        rows: Sequence[Mapping[str, Any]],
        snapshot_vector: SnapshotVectorBinding,
        publication_id: str | None = None,
    ) -> PublicationReceipt:
        """Copy-publish allowlisted rows without attaching the authority lake."""

        table = _require_safe_ident(table_name, field_name="table_name")
        if not self.policy.permits_table(table):
            raise SanitizerPolicyError(
                f"table {table!r} is not allowlisted by sanitizer policy "
                f"{self.policy.policy_id!r}"
            )
        if self._authority_attached:
            raise AuthorityAttachDenied(
                "publication plane is corrupted: authority catalog attached"
            )
        if self._loaded_extensions:
            raise ExtensionDenied(
                "publication plane is corrupted: extensions were loaded"
            )

        pub_id = publication_id or f"pub-{uuid.uuid4().hex}"
        materialised: list[PublicationRow] = []
        for index, raw in enumerate(rows):
            if not isinstance(raw, Mapping):
                raise PublicationError(f"row {index} must be a mapping")
            scrubbed = sec.scrub_sensitive_projection(dict(raw))
            # Drop columns not in the allowlist.
            filtered = {
                str(k): v
                for k, v in scrubbed.items()
                if self.policy.permits_column(str(k))
            }
            if not filtered:
                raise SanitizerPolicyError(
                    f"row {index} has no allowlisted columns after sanitization"
                )
            for key in filtered:
                if not self.policy.permits_column(key):
                    raise SanitizerPolicyError(
                        f"column {key!r} is not allowlisted"
                    )
            row = PublicationRow(
                row_id=f"row-{uuid.uuid4().hex}",
                table_name=table,
                payload=filtered,
                sanitizer_policy_id=self.policy.policy_id,
                snapshot_vector=snapshot_vector,
                schema_version=snapshot_vector.schema_version,
                schema_digest=snapshot_vector.schema_digest,
                content_digest="",
            )
            materialised.append(row)

        if len(materialised) > self.policy.max_rows:
            raise SanitizerPolicyError(
                f"row count {len(materialised)} exceeds policy max_rows "
                f"{self.policy.max_rows}"
            )

        content_digest = _sha256_text(
            _canonical_json(
                {
                    "table_name": table,
                    "rows": [dict(r.as_mapping()) for r in materialised],
                    "snapshot_vector_id": snapshot_vector.vector_id,
                    "policy_id": self.policy.policy_id,
                }
            )
        )
        path_digest = _sha256_text(self.identity.publication_db_path)
        receipt = PublicationReceipt(
            receipt_id=f"preceipt-{uuid.uuid4().hex}",
            publication_id=pub_id,
            table_name=table,
            row_count=len(materialised),
            content_digest=content_digest,
            sanitizer_policy_id=self.policy.policy_id,
            snapshot_vector_id=snapshot_vector.vector_id,
            snapshot_vector_digest=snapshot_vector.vector_digest,
            schema_version=snapshot_vector.schema_version,
            schema_digest=snapshot_vector.schema_digest,
            publication_db_path_digest=path_digest,
            created_at_unix=float(self._clock()),
            authority_catalog_attached=False,
            extensions_loaded=(),
        )

        with self._lock:
            bucket = self._tables.setdefault(table, [])
            bucket.extend(materialised)
            self._receipts.append(receipt)

        # Public surface must scrub credentials/keys.
        _ = sec.redact_for_agent_quack_response(dict(receipt.as_mapping()))
        return receipt

    def agent_visible_projection(self) -> Mapping[str, Any]:
        """Projection safe for agent-visible Quack responses."""

        with self._lock:
            tables = {
                name: [dict(r.as_mapping()) for r in rows]
                for name, rows in self._tables.items()
            }
            payload = {
                "schema": LAKE_PUBLICATION_SCHEMA,
                "identity": dict(self.identity.as_mapping()),
                "policy": dict(self.policy.as_mapping()),
                "tables": tables,
                "receipts": [dict(r.as_mapping()) for r in self._receipts],
                "authority_catalog_attached": False,
                "catalog_owner_attachment": (
                    None
                    if self.catalog_owner is None
                    else dict(self.catalog_owner.as_mapping())
                ),
                "extensions_loaded": [],
            }
        return MappingProxyType(sec.redact_for_agent_quack_response(payload))

    def close(self) -> None:
        with self._lock:
            self._tables.clear()
            self._receipts.clear()
            self._authority_attached = False
            self._loaded_extensions.clear()
