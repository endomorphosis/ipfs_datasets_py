"""Typed DuckDB + Quack catalog-shard, storage, and secret profiles (DQK-085).

Binds each logical catalog shard to:

* exactly one DuckDB metadata file on local or attached block storage
* one private companion-registry DuckDB path (same storage class)
* one canonical Quack endpoint (secrets held only as external references)
* one active owner lease / process-birth / fencing epoch
* one lifecycle-managed Parquet namespace in local or versioned object storage

Source IPLD/IPFS CIDs remain provenance only. Passwords, tokens, signing
material, and encryption keys never enter configuration projections.

Import is side-effect free: this module never imports ``duckdb``, never opens
catalog files, never contacts object stores, and never resolves secret values.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.ducklake.capabilities import ATTACH_SAFE_OPTIONS

__all__ = [
    "ATTACH_MODE_SAFE_OPTIONS",
    "ATTACH_PRIVILEGED_OPTIONS_DEFAULT",
    "AuthorityDatabasePath",
    "AuthorityStorageKind",
    "AttachMode",
    "AttachOptions",
    "CATALOG_PROFILE_SCHEMA",
    "CatalogIdentityRole",
    "CatalogProfileError",
    "CatalogShardProfile",
    "CompanionRegistryPath",
    "DEFAULT_ENCRYPTION_PROFILE",
    "EncryptionDefaults",
    "ExternalSecretReference",
    "FORBIDDEN_AUTHORITY_SCHEMES",
    "FORBIDDEN_SECRET_PROJECTION_KEYS",
    "IdentityCapabilityProfile",
    "ObjectDeleteIamCapability",
    "ObjectStoreNamespace",
    "OwnerLeaseBinding",
    "ParquetNamespace",
    "ParquetStorageKind",
    "PathPolicyError",
    "ProcessBirthBinding",
    "QuackEndpointProfile",
    "SecretProfile",
    "SecretProfileError",
    "StorageClassError",
    "assert_authority_path_admitted",
    "assert_no_secrets_in_projection",
    "build_attach_options",
    "default_identity_capabilities",
    "normalize_authority_path",
    "normalize_parquet_data_path",
    "project_catalog_profile",
    "project_secret_profile",
    "validate_path_under_allowlist",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

CATALOG_PROFILE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-catalog-shard-profile@1"
)

_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-085-catalog-shard-profiles-20260810"
)

# Safe non-bootstrap / non-migration ATTACH options (authoritative).
ATTACH_MODE_SAFE_OPTIONS: Final[Mapping[str, bool]] = MappingProxyType(
    dict(ATTACH_SAFE_OPTIONS)
)

# Bootstrap / migration may flip individual flags only under separate
# authorization; defaults remain fail-closed until an authorized mode is set.
ATTACH_PRIVILEGED_OPTIONS_DEFAULT: Final[Mapping[str, bool]] = MappingProxyType(
    {
        "CREATE_IF_NOT_EXISTS": False,
        "OVERRIDE_DATA_PATH": False,
        "AUTOMATIC_MIGRATION": False,
    }
)

FORBIDDEN_AUTHORITY_SCHEMES: Final[frozenset[str]] = frozenset(
    {
        "nfs",
        "smb",
        "cifs",
        "s3",
        "s3a",
        "s3n",
        "gs",
        "gcs",
        "az",
        "abfs",
        "abfss",
        "wasb",
        "wasbs",
        "http",
        "https",
        "ftp",
        "ftps",
        "ipfs",
        "ipns",
        "ipld",
        "file+nfs",
        "file+smb",
        "file+cifs",
        "afp",
        "webdav",
        "dav",
        "davs",
    }
)

# Keys that must never appear with non-empty secret material in projections.
FORBIDDEN_SECRET_PROJECTION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "password",
        "passwd",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "apikey",
        "secret",
        "secrets",
        "private_key",
        "privatekey",
        "signing_key",
        "signing_material",
        "encryption_key",
        "encryption_keys",
        "master_key",
        "session_token",
        "aws_secret_access_key",
        "secret_access_key",
        "client_secret",
        "quack_token",
        "capability_token",
        "raw_key",
        "pem",
        "credential",
        "credentials",
    }
)

_HOST_RE = re.compile(
    r"^(?:localhost|(?:\d{1,3}\.){3}\d{1,3}|\[?[A-Fa-f0-9:]+\]?|"
    r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)$"
)
_CATALOG_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_LEASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,255}$")
_SECRET_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./:@+%=-]{2,512}$")
_SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")
_OS_IDENTITY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
_NAMESPACE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

# Shared / network filesystem type names that fail closed for authority files.
_FORBIDDEN_FS_TYPES: Final[frozenset[str]] = frozenset(
    {
        "nfs",
        "nfs4",
        "nfsd",
        "smb",
        "smb2",
        "smb3",
        "cifs",
        "fuse.sshfs",
        "fuse.s3fs",
        "fuse.rclone",
        "fuse.gcsfuse",
        "fuse.s3",
        "afs",
        "glusterfs",
        "ceph",
        "lustre",
        "9p",
        "overlay",  # not a network FS but often multi-writer; reject when reported as shared authority
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CatalogProfileError(ValueError):
    """Fail-closed catalog-shard profile, storage, or secret rejection."""


class PathPolicyError(CatalogProfileError):
    """Authority or data path rejected by the storage class policy."""


class StorageClassError(CatalogProfileError):
    """Storage class is not admitted for the requested role."""


class SecretProfileError(CatalogProfileError):
    """Secret material leaked into a projection or invalid secret reference."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class AuthorityStorageKind(str, Enum):
    """Admitted storage classes for live catalog / companion-registry files."""

    LOCAL_BLOCK = "local_block"
    ATTACHED_BLOCK = "attached_block"


class ParquetStorageKind(str, Enum):
    """Admitted storage classes for lifecycle-managed Parquet namespaces."""

    LOCAL = "local"
    VERSIONED_OBJECT = "versioned_object"


class CatalogIdentityRole(str, Enum):
    """Least-privilege OS / endpoint / object identity roles for a shard."""

    READER = "reader"
    WRITER = "writer"
    MAINTAINER = "maintainer"
    OWNER_BROKER = "owner_broker"


class AttachMode(str, Enum):
    """ATTACH authorization mode.

    Only :attr:`SAFE` (runtime non-bootstrap / non-migration) is the default.
    :attr:`BOOTSTRAP` and :attr:`MIGRATION` require a separate authorization
    receipt and may enable privileged ATTACH options.
    """

    SAFE = "safe"
    BOOTSTRAP = "bootstrap"
    MIGRATION = "migration"


# ---------------------------------------------------------------------------
# Path policy (authority files fail closed on network / object / shared FS)
# ---------------------------------------------------------------------------


def _coerce_enum(enum_cls: type[Any], value: Any, *, field_name: str) -> Any:
    """Coerce ``value`` to ``enum_cls``, tolerating cross-reload enum members."""

    if isinstance(value, enum_cls):
        return value
    # str(Enum) on Python 3.11+ may yield "ClassName.MEMBER"; prefer .value.
    if isinstance(value, Enum):
        raw = getattr(value, "value", None)
        if raw is not None:
            try:
                return enum_cls(raw)
            except (TypeError, ValueError):
                pass
        name = getattr(value, "name", None)
        if isinstance(name, str) and name in enum_cls.__members__:
            return enum_cls[name]
    try:
        return enum_cls(value)
    except (TypeError, ValueError):
        pass
    text = str(value or "").strip()
    if "." in text:
        # Accept "ParquetStorageKind.LOCAL" after module reload.
        maybe_name = text.rsplit(".", 1)[-1]
        if maybe_name in enum_cls.__members__:
            return enum_cls[maybe_name]
    if text in enum_cls.__members__:
        return enum_cls[text]
    try:
        return enum_cls(text)
    except (TypeError, ValueError) as exc:
        raise CatalogProfileError(
            f"invalid {field_name} {value!r}; expected one of "
            f"{sorted(m.value for m in enum_cls)}"
        ) from exc


def _split_scheme(raw: str) -> tuple[str | None, str]:
    text = raw.strip()
    if not text:
        return None, text
    # UNC / Windows share paths are shared-filesystem authority.
    if text.startswith("\\\\") or text.startswith("//"):
        return "smb", text
    if "://" in text:
        scheme, rest = text.split("://", 1)
        return scheme.strip().lower() or None, rest
    # Bare scheme-like prefixes without // (e.g. s3:bucket/key).
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]{0,31}:[^/\\]", text):
        scheme, rest = text.split(":", 1)
        return scheme.strip().lower(), rest
    return None, text


def _is_windows_drive_path(path: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", path))


def normalize_authority_path(
    path: str,
    *,
    field_name: str = "authority_path",
) -> str:
    """Normalize a live catalog or companion-registry path (fail closed).

    Rules:
    * absolute local path only (POSIX ``/…`` or Windows drive path)
    * no NFS/SMB/object/URL schemes
    * no UNC / shared network paths
    * no ``..`` escape after normalization
    * no NULs or control characters
    * repository-relative paths are rejected
    """

    if not isinstance(path, str) or not path.strip():
        raise PathPolicyError(f"{field_name} must be a non-empty string")
    raw = path.strip()
    if len(raw) > 4_096:
        raise PathPolicyError(f"{field_name} exceeds maximum length")
    if any(ord(ch) < 32 for ch in raw):
        raise PathPolicyError(f"{field_name} contains control characters")

    scheme, remainder = _split_scheme(raw)
    if scheme is not None:
        if scheme in FORBIDDEN_AUTHORITY_SCHEMES or scheme.startswith("file+"):
            raise PathPolicyError(
                f"{field_name} rejects scheme {scheme!r}; live catalog and "
                "companion-registry files require local or attached block storage "
                "(NFS, SMB, object URLs, and shared filesystem mounts fail closed)"
            )
        if scheme != "file":
            raise PathPolicyError(
                f"{field_name} rejects scheme {scheme!r}; only local file paths "
                "are admitted for authority database files"
            )
        raw = remainder

    # After scheme strip, still reject UNC.
    if raw.startswith("\\\\") or raw.startswith("//"):
        raise PathPolicyError(
            f"{field_name} rejects UNC/shared network paths for authority files"
        )

    if _is_windows_drive_path(raw):
        pure = PureWindowsPath(raw)
        # Collapse . and .. without touching the filesystem.
        parts: list[str] = []
        for part in pure.parts:
            if part in (".",):
                continue
            if part == "..":
                if len(parts) <= 1:
                    raise PathPolicyError(
                        f"{field_name} escapes drive root after normalization"
                    )
                parts.pop()
                continue
            parts.append(part)
        normalized = str(PureWindowsPath(*parts)) if parts else str(pure)
        if ".." in PureWindowsPath(normalized).parts:
            raise PathPolicyError(f"{field_name} retains parent references")
        return normalized

    if not raw.startswith("/"):
        raise PathPolicyError(
            f"{field_name} must be an absolute path (repository-relative and "
            "cwd-relative paths are rejected for authority files)"
        )

    pure = PurePosixPath(raw)
    parts = []
    for part in pure.parts:
        if part in (".",):
            continue
        if part == "..":
            if len(parts) <= 1:
                raise PathPolicyError(
                    f"{field_name} escapes filesystem root after normalization"
                )
            parts.pop()
            continue
        parts.append(part)
    normalized = str(PurePosixPath(*parts)) if parts else "/"
    if normalized == "/":
        raise PathPolicyError(f"{field_name} must name a file, not filesystem root")
    if ".." in PurePosixPath(normalized).parts:
        raise PathPolicyError(f"{field_name} retains parent references")
    return normalized


def validate_path_under_allowlist(
    path: str,
    allowlist: Sequence[str],
    *,
    field_name: str = "path",
) -> str:
    """Ensure ``path`` is under one of the absolute allowlisted roots."""

    normalized = normalize_authority_path(path, field_name=field_name)
    if not allowlist:
        raise PathPolicyError(f"{field_name} allowlist must not be empty")
    roots = [
        normalize_authority_path(root, field_name=f"{field_name}_allowlist")
        for root in allowlist
    ]
    # For directory roots, ensure trailing-boundary match.
    for root in roots:
        if normalized == root:
            return normalized
        prefix = root if root.endswith(("/", "\\")) else root + (
            "\\" if "\\" in root and "/" not in root else "/"
        )
        if normalized.startswith(prefix):
            return normalized
    raise PathPolicyError(
        f"{field_name} {normalized!r} is outside the allowlisted roots "
        f"{sorted(set(roots))!r}"
    )


def assert_authority_path_admitted(
    path: str,
    *,
    field_name: str = "authority_path",
    allowlist: Sequence[str] | None = None,
    filesystem_type_probe: Callable[[str], str | None] | None = None,
) -> str:
    """Normalize and admit an authority path; optionally probe FS type.

    ``filesystem_type_probe`` is injected under test or by the owner process
    (e.g. reading ``statfs`` / mount table). When it returns a forbidden
    shared/network filesystem type, admission fails closed.
    """

    if allowlist:
        normalized = validate_path_under_allowlist(
            path, allowlist, field_name=field_name
        )
    else:
        normalized = normalize_authority_path(path, field_name=field_name)

    if filesystem_type_probe is not None:
        fs_type = filesystem_type_probe(normalized)
        if fs_type is not None:
            kind = str(fs_type).strip().lower()
            if kind in _FORBIDDEN_FS_TYPES or kind.startswith("fuse."):
                raise PathPolicyError(
                    f"{field_name} rejects filesystem type {fs_type!r}; live "
                    "catalog and companion-registry files require local or "
                    "attached block storage (NFS, SMB, object URLs, and shared "
                    "filesystem mounts fail closed)"
                )
    return normalized


def normalize_parquet_data_path(
    path: str,
    *,
    storage_kind: ParquetStorageKind | str,
    field_name: str = "data_path",
    allowlist: Sequence[str] | None = None,
) -> str:
    """Normalize a DuckLake DATA_PATH / Parquet namespace location.

    Local paths follow the same absolute-path rules as authority files but
    may live on local block storage. Versioned object storage admits
    ``s3://``, ``gs://``, ``gcs://``, ``az://``, ``abfs://``, ``abfss://``
    URIs with a non-empty bucket/container and key prefix. IPFS/IPLD CIDs are
    not valid live DATA_PATH values (provenance only).
    """

    kind = _coerce_enum(
        ParquetStorageKind, storage_kind, field_name="storage_kind"
    )
    if not isinstance(path, str) or not path.strip():
        raise PathPolicyError(f"{field_name} must be a non-empty string")
    raw = path.strip()
    if len(raw) > 4_096:
        raise PathPolicyError(f"{field_name} exceeds maximum length")
    if any(ord(ch) < 32 for ch in raw):
        raise PathPolicyError(f"{field_name} contains control characters")

    if kind is ParquetStorageKind.LOCAL:
        if allowlist:
            return validate_path_under_allowlist(
                raw, allowlist, field_name=field_name
            )
        return normalize_authority_path(raw, field_name=field_name)

    # versioned object storage
    scheme, remainder = _split_scheme(raw)
    admitted_object = {"s3", "s3a", "gs", "gcs", "az", "abfs", "abfss"}
    if scheme is None or scheme not in admitted_object:
        raise PathPolicyError(
            f"{field_name} for versioned object storage requires an admitted "
            f"object URI scheme {sorted(admitted_object)!r}; got {raw!r}"
        )
    if scheme in {"ipfs", "ipns", "ipld"}:
        raise PathPolicyError(
            f"{field_name} rejects IPFS/IPLD as live DATA_PATH; CIDs remain "
            "provenance only"
        )
    body = remainder.lstrip("/")
    if not body or "/" not in body and not body:
        raise PathPolicyError(f"{field_name} object URI requires bucket and prefix")
    # Normalize double slashes in key, keep scheme lowercase.
    parts = [p for p in body.split("/") if p not in ("", ".")]
    if ".." in parts:
        raise PathPolicyError(f"{field_name} object key must not contain '..'")
    if not parts:
        raise PathPolicyError(f"{field_name} object URI is empty after normalization")
    return f"{scheme}://{'/'.join(parts)}"


# ---------------------------------------------------------------------------
# Secret references (external only; values never embedded)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExternalSecretReference:
    """Reference to secret material held outside configuration projections.

    The reference identifies a secret-store handle, IAM role, or sealed vault
    path. It must never contain the secret value itself.
    """

    ref_id: str
    purpose: str
    provider: str = "external"
    version: str | None = None

    def __post_init__(self) -> None:
        ref_id = str(self.ref_id or "").strip()
        if not ref_id or not _SECRET_REF_RE.match(ref_id):
            raise SecretProfileError(f"invalid secret reference id {self.ref_id!r}")
        # Reject values that look like embedded PEM / high-entropy blobs.
        if "BEGIN " in ref_id.upper() or "\n" in ref_id:
            raise SecretProfileError(
                "secret reference must not embed PEM or multi-line secret material"
            )
        if len(ref_id) > 256 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", ref_id):
            # Long base64-like strings are likely embedded tokens.
            raise SecretProfileError(
                "secret reference looks like embedded token material; store "
                "secrets externally and pass only a short handle"
            )
        purpose = str(self.purpose or "").strip().lower()
        if not purpose or not re.match(r"^[a-z][a-z0-9_.-]{0,63}$", purpose):
            raise SecretProfileError(f"invalid secret purpose {self.purpose!r}")
        provider = str(self.provider or "external").strip().lower()
        if not provider or not re.match(r"^[a-z][a-z0-9_.-]{0,63}$", provider):
            raise SecretProfileError(f"invalid secret provider {self.provider!r}")
        version = self.version
        if version is not None:
            version = str(version).strip() or None
            if version is not None and len(version) > 128:
                raise SecretProfileError("secret version exceeds maximum length")
        object.__setattr__(self, "ref_id", ref_id)
        object.__setattr__(self, "purpose", purpose)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "version", version)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "ref_id": self.ref_id,
                "purpose": self.purpose,
                "provider": self.provider,
                "version": self.version,
            }
        )

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"ExternalSecretReference(ref_id={self.ref_id!r}, "
            f"purpose={self.purpose!r}, provider={self.provider!r})"
        )


@dataclass(frozen=True, slots=True)
class SecretProfile:
    """External secret references for a catalog shard (no secret values)."""

    quack_capability_ref: ExternalSecretReference | None = None
    object_read_ref: ExternalSecretReference | None = None
    object_write_ref: ExternalSecretReference | None = None
    object_delete_ref: ExternalSecretReference | None = None
    catalog_encryption_key_ref: ExternalSecretReference | None = None
    signing_key_ref: ExternalSecretReference | None = None
    extra_refs: Mapping[str, ExternalSecretReference] = field(default_factory=dict)

    def __post_init__(self) -> None:
        extras: dict[str, ExternalSecretReference] = {}
        for key, value in dict(self.extra_refs or {}).items():
            name = str(key).strip().lower()
            if not name or name in FORBIDDEN_SECRET_PROJECTION_KEYS:
                raise SecretProfileError(
                    f"extra secret ref key {key!r} is forbidden or empty"
                )
            if isinstance(value, ExternalSecretReference):
                extras[name] = value
            elif isinstance(value, Mapping):
                extras[name] = ExternalSecretReference(**dict(value))
            else:
                raise SecretProfileError(
                    f"extra secret ref {key!r} must be ExternalSecretReference "
                    "or a mapping"
                )
        object.__setattr__(self, "extra_refs", MappingProxyType(extras))
        for attr in (
            "quack_capability_ref",
            "object_read_ref",
            "object_write_ref",
            "object_delete_ref",
            "catalog_encryption_key_ref",
            "signing_key_ref",
        ):
            value = getattr(self, attr)
            if value is None:
                continue
            if isinstance(value, Mapping):
                object.__setattr__(self, attr, ExternalSecretReference(**dict(value)))
            elif not isinstance(value, ExternalSecretReference):
                raise SecretProfileError(
                    f"{attr} must be ExternalSecretReference, mapping, or None"
                )

    def all_refs(self) -> Mapping[str, ExternalSecretReference]:
        items: dict[str, ExternalSecretReference] = {}
        for attr in (
            "quack_capability_ref",
            "object_read_ref",
            "object_write_ref",
            "object_delete_ref",
            "catalog_encryption_key_ref",
            "signing_key_ref",
        ):
            value = getattr(self, attr)
            if value is not None:
                items[attr] = value
        items.update(dict(self.extra_refs))
        return MappingProxyType(items)

    def as_mapping(self) -> Mapping[str, Any]:
        payload: dict[str, Any] = {}
        for attr in (
            "quack_capability_ref",
            "object_read_ref",
            "object_write_ref",
            "object_delete_ref",
            "catalog_encryption_key_ref",
            "signing_key_ref",
        ):
            value = getattr(self, attr)
            payload[attr] = None if value is None else dict(value.as_mapping())
        payload["extra_refs"] = {
            key: dict(ref.as_mapping()) for key, ref in self.extra_refs.items()
        }
        return MappingProxyType(payload)


def project_secret_profile(profile: SecretProfile) -> Mapping[str, Any]:
    """Return a configuration projection that never embeds secret values."""

    projected = dict(profile.as_mapping())
    assert_no_secrets_in_projection(projected)
    return MappingProxyType(projected)


def assert_no_secrets_in_projection(
    projection: Mapping[str, Any] | Sequence[Any] | Any,
    *,
    _path: str = "$",
) -> None:
    """Walk a configuration projection and reject embedded secret material."""

    if isinstance(projection, Mapping):
        for key, value in projection.items():
            key_text = str(key).strip().lower()
            child = f"{_path}.{key_text}"
            if key_text in FORBIDDEN_SECRET_PROJECTION_KEYS:
                if value in (None, "", {}, [], ()):
                    continue
                # Allow redacted markers and external ref structures.
                if isinstance(value, str) and value in {"***", "[redacted]", "REDACTED"}:
                    continue
                if isinstance(value, Mapping) and set(value.keys()) <= {
                    "ref_id",
                    "purpose",
                    "provider",
                    "version",
                }:
                    assert_no_secrets_in_projection(value, _path=child)
                    continue
                raise SecretProfileError(
                    f"configuration projection must not embed secret material "
                    f"at {child}"
                )
            assert_no_secrets_in_projection(value, _path=child)
        return
    if isinstance(projection, (list, tuple)):
        for index, item in enumerate(projection):
            assert_no_secrets_in_projection(item, _path=f"{_path}[{index}]")
        return
    if isinstance(projection, str):
        upper = projection.upper()
        if "BEGIN PRIVATE KEY" in upper or "BEGIN RSA PRIVATE KEY" in upper:
            raise SecretProfileError(
                f"configuration projection embeds PEM key material at {_path}"
            )
        if "BEGIN SECRET" in upper:
            raise SecretProfileError(
                f"configuration projection embeds secret material at {_path}"
            )


# ---------------------------------------------------------------------------
# Identity, encryption, object store, owner lease
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ObjectDeleteIamCapability:
    """Short-lived object-delete IAM capability (separate from read/write).

    Ordinary readers and writers must not hold this capability. Maintainers
    and owner-broker identities may request it only for authorized destructive
    maintenance under a separate short-lived grant.
    """

    capability_ref: ExternalSecretReference
    max_ttl_seconds: int = 300
    allowed_roles: frozenset[CatalogIdentityRole] = field(
        default_factory=lambda: frozenset(
            {CatalogIdentityRole.MAINTAINER, CatalogIdentityRole.OWNER_BROKER}
        )
    )

    def __post_init__(self) -> None:
        if isinstance(self.capability_ref, Mapping):
            object.__setattr__(
                self,
                "capability_ref",
                ExternalSecretReference(**dict(self.capability_ref)),
            )
        elif not isinstance(self.capability_ref, ExternalSecretReference):
            raise CatalogProfileError(
                "object-delete capability_ref must be ExternalSecretReference"
            )
        if self.capability_ref.purpose not in {
            "object_delete",
            "object-delete",
            "object_delete_iam",
        }:
            # Normalize purpose to the canonical name.
            object.__setattr__(
                self,
                "capability_ref",
                ExternalSecretReference(
                    ref_id=self.capability_ref.ref_id,
                    purpose="object_delete",
                    provider=self.capability_ref.provider,
                    version=self.capability_ref.version,
                ),
            )
        if not isinstance(self.max_ttl_seconds, int) or isinstance(
            self.max_ttl_seconds, bool
        ):
            raise CatalogProfileError("max_ttl_seconds must be an int")
        if self.max_ttl_seconds < 1 or self.max_ttl_seconds > 3_600:
            raise CatalogProfileError(
                f"object-delete max_ttl_seconds out of range: {self.max_ttl_seconds}"
            )
        roles = frozenset(
            _coerce_enum(CatalogIdentityRole, r, field_name="allowed_roles")
            for r in self.allowed_roles
        )
        if CatalogIdentityRole.READER in roles or CatalogIdentityRole.WRITER in roles:
            raise CatalogProfileError(
                "object-delete IAM capability must be unavailable to ordinary "
                "readers and writers"
            )
        if not roles:
            raise CatalogProfileError("object-delete allowed_roles must not be empty")
        object.__setattr__(self, "allowed_roles", roles)

    def permits(self, role: CatalogIdentityRole | str) -> bool:
        resolved = _coerce_enum(CatalogIdentityRole, role, field_name="role")
        return resolved in self.allowed_roles

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "capability_ref": dict(self.capability_ref.as_mapping()),
                "max_ttl_seconds": self.max_ttl_seconds,
                "allowed_roles": sorted(role.value for role in self.allowed_roles),
            }
        )


@dataclass(frozen=True, slots=True)
class IdentityCapabilityProfile:
    """Least-privilege endpoint / OS / object capabilities for one role."""

    role: CatalogIdentityRole
    os_identity: str
    endpoint_access: bool
    object_read: bool
    object_write: bool
    object_delete: bool = False
    open_catalog_file: bool = False
    broker_authorize: bool = False
    inject_quack_capability: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "role",
            _coerce_enum(CatalogIdentityRole, self.role, field_name="role"),
        )
        os_id = str(self.os_identity or "").strip()
        if not os_id or not _OS_IDENTITY_RE.match(os_id):
            raise CatalogProfileError(f"invalid os_identity {self.os_identity!r}")
        object.__setattr__(self, "os_identity", os_id)

        role = self.role
        # Least-privilege invariants (use == so reload-safe enum members match).
        if role == CatalogIdentityRole.READER:
            if self.object_write or self.object_delete or self.open_catalog_file:
                raise CatalogProfileError(
                    "reader identity must not write/delete objects or open the "
                    "catalog file"
                )
            if self.broker_authorize or self.inject_quack_capability:
                raise CatalogProfileError(
                    "reader identity must not authorize or inject Quack capabilities"
                )
        if role == CatalogIdentityRole.WRITER:
            if self.object_delete or self.open_catalog_file:
                raise CatalogProfileError(
                    "writer identity must not delete objects or open the catalog file"
                )
            if self.broker_authorize or self.inject_quack_capability:
                raise CatalogProfileError(
                    "writer identity must not authorize or inject Quack capabilities"
                )
        if role == CatalogIdentityRole.MAINTAINER:
            if self.open_catalog_file:
                raise CatalogProfileError(
                    "maintainer must not open the live catalog file; only the "
                    "identity-bound owner process may open it"
                )
            if self.inject_quack_capability:
                raise CatalogProfileError(
                    "only the owner-broker may inject one-use Quack capabilities"
                )
        if role == CatalogIdentityRole.OWNER_BROKER:
            if not self.broker_authorize:
                raise CatalogProfileError(
                    "owner-broker must independently authorize privileged calls"
                )
            if not self.inject_quack_capability:
                raise CatalogProfileError(
                    "owner-broker must be able to inject one-use Quack capabilities "
                    "into identity-bound trusted workers"
                )
            # The owner process (not remote broker clients) opens the file;
            # the broker identity itself does not open remote catalog files.
            if self.open_catalog_file:
                raise CatalogProfileError(
                    "owner-broker network identity must not open the catalog file; "
                    "only the fenced owner process does"
                )
        if self.object_delete and role in {
            CatalogIdentityRole.READER,
            CatalogIdentityRole.WRITER,
        }:
            raise CatalogProfileError(
                "object deletion requires a separate short-lived IAM capability "
                "unavailable to ordinary readers and writers"
            )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "role": self.role.value,
                "os_identity": self.os_identity,
                "endpoint_access": self.endpoint_access,
                "object_read": self.object_read,
                "object_write": self.object_write,
                "object_delete": self.object_delete,
                "open_catalog_file": self.open_catalog_file,
                "broker_authorize": self.broker_authorize,
                "inject_quack_capability": self.inject_quack_capability,
            }
        )


def default_identity_capabilities(
    *,
    catalog_id: str,
) -> Mapping[CatalogIdentityRole, IdentityCapabilityProfile]:
    """Return least-privilege default identities for a catalog shard."""

    safe = re.sub(r"[^A-Za-z0-9_]+", "_", catalog_id).strip("_").lower() or "catalog"
    return MappingProxyType(
        {
            CatalogIdentityRole.READER: IdentityCapabilityProfile(
                role=CatalogIdentityRole.READER,
                os_identity=f"ducklake_{safe}_reader",
                endpoint_access=True,
                object_read=True,
                object_write=False,
                object_delete=False,
                open_catalog_file=False,
                broker_authorize=False,
                inject_quack_capability=False,
            ),
            CatalogIdentityRole.WRITER: IdentityCapabilityProfile(
                role=CatalogIdentityRole.WRITER,
                os_identity=f"ducklake_{safe}_writer",
                endpoint_access=True,
                object_read=True,
                object_write=True,
                object_delete=False,
                open_catalog_file=False,
                broker_authorize=False,
                inject_quack_capability=False,
            ),
            CatalogIdentityRole.MAINTAINER: IdentityCapabilityProfile(
                role=CatalogIdentityRole.MAINTAINER,
                os_identity=f"ducklake_{safe}_maintainer",
                endpoint_access=True,
                object_read=True,
                object_write=True,
                object_delete=False,  # delete only via separate short-lived IAM
                open_catalog_file=False,
                broker_authorize=False,
                inject_quack_capability=False,
            ),
            CatalogIdentityRole.OWNER_BROKER: IdentityCapabilityProfile(
                role=CatalogIdentityRole.OWNER_BROKER,
                os_identity=f"ducklake_{safe}_owner_broker",
                endpoint_access=True,
                object_read=True,
                object_write=True,
                object_delete=False,  # still requires separate short-lived IAM
                open_catalog_file=False,
                broker_authorize=True,
                inject_quack_capability=True,
            ),
        }
    )


@dataclass(frozen=True, slots=True)
class EncryptionDefaults:
    """Encryption defaults applied before first ingest (keys stay external)."""

    catalog_at_rest: bool = True
    object_at_rest: bool = True
    transit_tls_required: bool = True
    algorithm: str = "aes-256-gcm"
    key_ref: ExternalSecretReference | None = None

    def __post_init__(self) -> None:
        algo = str(self.algorithm or "").strip().lower()
        if algo not in {"aes-256-gcm", "aes-256-cbc", "chacha20-poly1305"}:
            raise CatalogProfileError(f"unsupported encryption algorithm {self.algorithm!r}")
        object.__setattr__(self, "algorithm", algo)
        if self.key_ref is not None and isinstance(self.key_ref, Mapping):
            object.__setattr__(
                self, "key_ref", ExternalSecretReference(**dict(self.key_ref))
            )
        if self.catalog_at_rest and self.key_ref is None:
            # Key may be provisioned later, but defaults require a reference slot
            # before first ingest is authorized by higher layers. We allow None
            # here so profiles can be assembled before key minting; catalog.py
            # enforces presence before open for ingest.
            pass

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "catalog_at_rest": self.catalog_at_rest,
                "object_at_rest": self.object_at_rest,
                "transit_tls_required": self.transit_tls_required,
                "algorithm": self.algorithm,
                "key_ref": None if self.key_ref is None else dict(self.key_ref.as_mapping()),
            }
        )


DEFAULT_ENCRYPTION_PROFILE: Final[EncryptionDefaults] = EncryptionDefaults()


@dataclass(frozen=True, slots=True)
class ProcessBirthBinding:
    """Process-birth identity bound to a catalog-owner lease (no live probe)."""

    pid: int
    boot_id: str
    start_ticks: int
    cmdline_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.pid, int) or isinstance(self.pid, bool) or self.pid < 1:
            raise CatalogProfileError("process birth pid must be a positive int")
        boot = str(self.boot_id or "").strip()
        if not boot or len(boot) > 128:
            raise CatalogProfileError("invalid process birth boot_id")
        if not isinstance(self.start_ticks, int) or isinstance(self.start_ticks, bool):
            raise CatalogProfileError("start_ticks must be an int")
        if self.start_ticks < 0:
            raise CatalogProfileError("start_ticks must be non-negative")
        digest = str(self.cmdline_sha256 or "").strip().lower()
        if not _SHA256_RE.match(digest):
            raise CatalogProfileError("cmdline_sha256 must be a sha256 hex digest")
        if not digest.startswith("sha256:"):
            digest = f"sha256:{digest}"
        object.__setattr__(self, "boot_id", boot)
        object.__setattr__(self, "cmdline_sha256", digest)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "pid": self.pid,
                "boot_id": self.boot_id,
                "start_ticks": self.start_ticks,
                "cmdline_sha256": self.cmdline_sha256,
            }
        )


@dataclass(frozen=True, slots=True)
class OwnerLeaseBinding:
    """Active owner lease / process birth / fencing epoch for one shard."""

    lease_id: str
    owner_generation: int
    fencing_epoch: int
    process_birth: ProcessBirthBinding
    endpoint_identity: str
    os_identity: str

    def __post_init__(self) -> None:
        lease = str(self.lease_id or "").strip()
        if not lease or not _LEASE_ID_RE.match(lease):
            raise CatalogProfileError(f"invalid owner lease_id {self.lease_id!r}")
        if (
            not isinstance(self.owner_generation, int)
            or isinstance(self.owner_generation, bool)
            or self.owner_generation < 1
        ):
            raise CatalogProfileError("owner_generation must be a positive int")
        if (
            not isinstance(self.fencing_epoch, int)
            or isinstance(self.fencing_epoch, bool)
            or self.fencing_epoch < 1
        ):
            raise CatalogProfileError("fencing_epoch must be a positive int")
        if isinstance(self.process_birth, Mapping):
            object.__setattr__(
                self, "process_birth", ProcessBirthBinding(**dict(self.process_birth))
            )
        elif not isinstance(self.process_birth, ProcessBirthBinding):
            raise CatalogProfileError(
                "process_birth must be ProcessBirthBinding or a mapping"
            )
        endpoint = str(self.endpoint_identity or "").strip()
        if not endpoint or len(endpoint) > 256:
            raise CatalogProfileError("invalid endpoint_identity")
        os_id = str(self.os_identity or "").strip()
        if not os_id or not _OS_IDENTITY_RE.match(os_id):
            raise CatalogProfileError(f"invalid owner os_identity {self.os_identity!r}")
        object.__setattr__(self, "lease_id", lease)
        object.__setattr__(self, "endpoint_identity", endpoint)
        object.__setattr__(self, "os_identity", os_id)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "lease_id": self.lease_id,
                "owner_generation": self.owner_generation,
                "fencing_epoch": self.fencing_epoch,
                "process_birth": dict(self.process_birth.as_mapping()),
                "endpoint_identity": self.endpoint_identity,
                "os_identity": self.os_identity,
            }
        )


@dataclass(frozen=True, slots=True)
class QuackEndpointProfile:
    """Canonical Quack endpoint identity without credentials."""

    host: str
    port: int
    database: str = ""
    use_tls: bool = True
    endpoint_id: str = ""

    def __post_init__(self) -> None:
        host = str(self.host or "").strip().lower()
        if not host or not _HOST_RE.match(host):
            raise CatalogProfileError(f"invalid Quack host {self.host!r}")
        if not isinstance(self.port, int) or isinstance(self.port, bool):
            raise CatalogProfileError("Quack port must be an int")
        if self.port < 1 or self.port > 65_535:
            raise CatalogProfileError(f"Quack port out of range: {self.port}")
        database = str(self.database or "").strip().lstrip("/")
        if database and not re.match(r"^[A-Za-z0-9_./-]{1,256}$", database):
            raise CatalogProfileError(f"invalid Quack database name {self.database!r}")
        endpoint_id = str(self.endpoint_id or "").strip()
        if not endpoint_id:
            scheme = "quacks" if self.use_tls else "quack"
            db = f"/{database}" if database else ""
            endpoint_id = f"{scheme}://{host}:{self.port}{db}"
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "database", database)
        object.__setattr__(self, "endpoint_id", endpoint_id)

    def authority(self) -> str:
        return f"{self.host}:{self.port}"

    def redacted_uri(self) -> str:
        scheme = "quacks" if self.use_tls else "quack"
        db = f"/{self.database}" if self.database else ""
        return f"{scheme}://{self.authority()}{db}"

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "host": self.host,
                "port": self.port,
                "database": self.database,
                "use_tls": self.use_tls,
                "endpoint_id": self.endpoint_id,
                "redacted_uri": self.redacted_uri(),
            }
        )


@dataclass(frozen=True, slots=True)
class AuthorityDatabasePath:
    """Validated path for a live catalog or companion-registry DuckDB file."""

    path: str
    storage_kind: AuthorityStorageKind
    role: str = "catalog"
    allowlist: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "storage_kind",
            _coerce_enum(
                AuthorityStorageKind, self.storage_kind, field_name="storage_kind"
            ),
        )
        role = str(self.role or "catalog").strip().lower()
        if role not in {"catalog", "companion_registry"}:
            raise CatalogProfileError(
                f"authority path role must be catalog or companion_registry, got {role!r}"
            )
        roots = tuple(str(item) for item in (self.allowlist or ()))
        object.__setattr__(self, "allowlist", roots)
        normalized = assert_authority_path_admitted(
            self.path,
            field_name=f"{role}_path",
            allowlist=roots or None,
        )
        object.__setattr__(self, "path", normalized)
        object.__setattr__(self, "role", role)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "path": self.path,
                "storage_kind": self.storage_kind.value,
                "role": self.role,
                "allowlist": list(self.allowlist),
            }
        )


# Back-compat alias name used in docs.
CompanionRegistryPath = AuthorityDatabasePath


@dataclass(frozen=True, slots=True)
class ObjectStoreNamespace:
    """Object-store binding for a lifecycle-managed Parquet namespace."""

    endpoint: str | None
    region: str | None
    bucket_or_root: str
    versioning_required: bool = True
    delete_iam: ObjectDeleteIamCapability | None = None

    def __post_init__(self) -> None:
        root = str(self.bucket_or_root or "").strip()
        if not root:
            raise CatalogProfileError("object store bucket_or_root is required")
        object.__setattr__(self, "bucket_or_root", root)
        endpoint = None if self.endpoint is None else str(self.endpoint).strip() or None
        if endpoint is not None and any(ord(ch) < 32 for ch in endpoint):
            raise CatalogProfileError("object store endpoint contains control characters")
        object.__setattr__(self, "endpoint", endpoint)
        region = None if self.region is None else str(self.region).strip() or None
        object.__setattr__(self, "region", region)
        if self.delete_iam is not None and isinstance(self.delete_iam, Mapping):
            object.__setattr__(
                self, "delete_iam", ObjectDeleteIamCapability(**dict(self.delete_iam))
            )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "endpoint": self.endpoint,
                "region": self.region,
                "bucket_or_root": self.bucket_or_root,
                "versioning_required": self.versioning_required,
                "delete_iam": (
                    None if self.delete_iam is None else dict(self.delete_iam.as_mapping())
                ),
            }
        )


@dataclass(frozen=True, slots=True)
class ParquetNamespace:
    """Lifecycle-managed Parquet namespace owned by DuckLake for one shard."""

    data_path: str
    storage_kind: ParquetStorageKind
    namespace_id: str
    staging_path: str | None = None
    object_store: ObjectStoreNamespace | None = None
    allowlist: tuple[str, ...] = ()
    provenance_cid_roots: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "storage_kind",
            _coerce_enum(
                ParquetStorageKind, self.storage_kind, field_name="storage_kind"
            ),
        )
        ns = str(self.namespace_id or "").strip()
        if not ns or not _NAMESPACE_SEGMENT_RE.match(ns):
            raise CatalogProfileError(f"invalid parquet namespace_id {self.namespace_id!r}")
        object.__setattr__(self, "namespace_id", ns)
        roots = tuple(str(item) for item in (self.allowlist or ()))
        object.__setattr__(self, "allowlist", roots)
        normalized = normalize_parquet_data_path(
            self.data_path,
            storage_kind=self.storage_kind,
            field_name="data_path",
            allowlist=roots or None,
        )
        object.__setattr__(self, "data_path", normalized)

        staging = self.staging_path
        if staging is not None:
            staging_norm = normalize_parquet_data_path(
                staging,
                storage_kind=(
                    ParquetStorageKind.LOCAL
                    if self.storage_kind is ParquetStorageKind.LOCAL
                    else self.storage_kind
                ),
                field_name="staging_path",
                allowlist=roots or None,
            )
            # Staging must not be inside DATA_PATH for local paths.
            if self.storage_kind is ParquetStorageKind.LOCAL:
                data_prefix = normalized.rstrip("/") + "/"
                if staging_norm == normalized or staging_norm.startswith(data_prefix):
                    raise CatalogProfileError(
                        "staging_path must be outside DATA_PATH so staging files "
                        "cannot be mistaken for orphans under DATA_PATH"
                    )
            object.__setattr__(self, "staging_path", staging_norm)

        if self.storage_kind is ParquetStorageKind.VERSIONED_OBJECT:
            if self.object_store is None:
                raise CatalogProfileError(
                    "versioned object Parquet namespaces require object_store binding"
                )
            if isinstance(self.object_store, Mapping):
                object.__setattr__(
                    self, "object_store", ObjectStoreNamespace(**dict(self.object_store))
                )
            if self.object_store is not None and not self.object_store.versioning_required:
                raise CatalogProfileError(
                    "versioned object Parquet namespaces require versioning_required=True"
                )
        elif self.object_store is not None and isinstance(self.object_store, Mapping):
            object.__setattr__(
                self, "object_store", ObjectStoreNamespace(**dict(self.object_store))
            )

        cids: list[str] = []
        for item in self.provenance_cid_roots or ():
            text = str(item).strip()
            if not text:
                continue
            # CIDs are provenance only; never treat as DATA_PATH.
            if text.startswith(("s3://", "gs://", "https://", "http://")):
                raise CatalogProfileError(
                    "provenance_cid_roots must be IPLD/IPFS CIDs, not object URLs"
                )
            cids.append(text)
        object.__setattr__(self, "provenance_cid_roots", tuple(cids))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "data_path": self.data_path,
                "storage_kind": self.storage_kind.value,
                "namespace_id": self.namespace_id,
                "staging_path": self.staging_path,
                "object_store": (
                    None
                    if self.object_store is None
                    else dict(self.object_store.as_mapping())
                ),
                "allowlist": list(self.allowlist),
                "provenance_cid_roots": list(self.provenance_cid_roots),
                "lifecycle_managed_by": "ducklake",
            }
        )


# ---------------------------------------------------------------------------
# ATTACH options
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AttachOptions:
    """Typed DuckLake ATTACH options with mode-gated privileges."""

    mode: AttachMode
    create_if_not_exists: bool
    override_data_path: bool
    automatic_migration: bool
    authorization_receipt_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "mode",
            _coerce_enum(AttachMode, self.mode, field_name="mode"),
        )
        if self.mode is AttachMode.SAFE:
            if (
                self.create_if_not_exists
                or self.override_data_path
                or self.automatic_migration
            ):
                raise CatalogProfileError(
                    "SAFE ATTACH requires CREATE_IF_NOT_EXISTS=false, "
                    "OVERRIDE_DATA_PATH=false, and AUTOMATIC_MIGRATION=false"
                )
            if self.authorization_receipt_id is not None:
                # Safe mode does not need a privileged receipt.
                object.__setattr__(self, "authorization_receipt_id", None)
        else:
            receipt = (
                None
                if self.authorization_receipt_id is None
                else str(self.authorization_receipt_id).strip() or None
            )
            if not receipt:
                raise CatalogProfileError(
                    f"{self.mode.value} ATTACH requires a separate authorization "
                    "receipt id; only SAFE mode may omit it"
                )
            object.__setattr__(self, "authorization_receipt_id", receipt)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "mode": self.mode.value,
                "CREATE_IF_NOT_EXISTS": self.create_if_not_exists,
                "OVERRIDE_DATA_PATH": self.override_data_path,
                "AUTOMATIC_MIGRATION": self.automatic_migration,
                "authorization_receipt_id": self.authorization_receipt_id,
            }
        )

    def ducklake_options(self) -> Mapping[str, bool]:
        return MappingProxyType(
            {
                "CREATE_IF_NOT_EXISTS": bool(self.create_if_not_exists),
                "OVERRIDE_DATA_PATH": bool(self.override_data_path),
                "AUTOMATIC_MIGRATION": bool(self.automatic_migration),
            }
        )


def build_attach_options(
    mode: AttachMode | str = AttachMode.SAFE,
    *,
    create_if_not_exists: bool | None = None,
    override_data_path: bool | None = None,
    automatic_migration: bool | None = None,
    authorization_receipt_id: str | None = None,
) -> AttachOptions:
    """Build ATTACH options; non-bootstrap defaults force all safe flags false.

    Only a separately authorized bootstrap or migration operation may set
    privileged values; callers must supply ``authorization_receipt_id``.
    """

    resolved = _coerce_enum(AttachMode, mode, field_name="attach_mode")
    if resolved is AttachMode.SAFE:
        # Force safe defaults regardless of caller overrides.
        if (
            create_if_not_exists is True
            or override_data_path is True
            or automatic_migration is True
        ):
            raise CatalogProfileError(
                "SAFE (non-bootstrap / non-migration) ATTACH forbids "
                "CREATE_IF_NOT_EXISTS=true, OVERRIDE_DATA_PATH=true, or "
                "AUTOMATIC_MIGRATION=true; only a separately authorized "
                "bootstrap or migration operation may use other values"
            )
        return AttachOptions(
            mode=AttachMode.SAFE,
            create_if_not_exists=False,
            override_data_path=False,
            automatic_migration=False,
            authorization_receipt_id=None,
        )

    return AttachOptions(
        mode=resolved,
        create_if_not_exists=bool(
            ATTACH_PRIVILEGED_OPTIONS_DEFAULT["CREATE_IF_NOT_EXISTS"]
            if create_if_not_exists is None
            else create_if_not_exists
        ),
        override_data_path=bool(
            ATTACH_PRIVILEGED_OPTIONS_DEFAULT["OVERRIDE_DATA_PATH"]
            if override_data_path is None
            else override_data_path
        ),
        automatic_migration=bool(
            ATTACH_PRIVILEGED_OPTIONS_DEFAULT["AUTOMATIC_MIGRATION"]
            if automatic_migration is None
            else automatic_migration
        ),
        authorization_receipt_id=authorization_receipt_id,
    )


# ---------------------------------------------------------------------------
# Catalog shard profile (top-level typed binding)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CatalogShardProfile:
    """Typed DuckDB + Quack catalog-shard profile (one logical catalog).

    Invariants:
    * one DuckDB metadata file + one companion-registry file on block storage
    * one canonical Quack endpoint
    * one active owner lease / process birth / fencing epoch
    * one lifecycle-managed Parquet namespace
    * secrets are external references only
    * DuckLake supplies no role or authorization layer (broker is external)
    """

    catalog_id: str
    catalog_metadata: AuthorityDatabasePath
    companion_registry: AuthorityDatabasePath
    quack_endpoint: QuackEndpointProfile
    owner_lease: OwnerLeaseBinding
    parquet_namespace: ParquetNamespace
    secret_profile: SecretProfile = field(default_factory=SecretProfile)
    identities: Mapping[CatalogIdentityRole, IdentityCapabilityProfile] = field(
        default_factory=dict
    )
    encryption: EncryptionDefaults = field(default_factory=lambda: DEFAULT_ENCRYPTION_PROFILE)
    ducklake_supplies_authorization: bool = False
    remote_clients_may_open_catalog_file: bool = False
    same_shard_serialization: bool = True
    independent_shard_concurrency: bool = True
    schema: str = CATALOG_PROFILE_SCHEMA

    def __post_init__(self) -> None:
        catalog_id = str(self.catalog_id or "").strip()
        if not catalog_id or not _CATALOG_ID_RE.match(catalog_id):
            raise CatalogProfileError(f"invalid catalog_id {self.catalog_id!r}")
        object.__setattr__(self, "catalog_id", catalog_id)

        if isinstance(self.catalog_metadata, Mapping):
            object.__setattr__(
                self,
                "catalog_metadata",
                AuthorityDatabasePath(**dict(self.catalog_metadata)),
            )
        elif not isinstance(self.catalog_metadata, AuthorityDatabasePath):
            raise CatalogProfileError(
                "catalog_metadata must be AuthorityDatabasePath or a mapping"
            )
        if self.catalog_metadata.role != "catalog":
            object.__setattr__(
                self,
                "catalog_metadata",
                AuthorityDatabasePath(
                    path=self.catalog_metadata.path,
                    storage_kind=self.catalog_metadata.storage_kind,
                    role="catalog",
                    allowlist=self.catalog_metadata.allowlist,
                ),
            )

        if isinstance(self.companion_registry, Mapping):
            object.__setattr__(
                self,
                "companion_registry",
                AuthorityDatabasePath(**dict(self.companion_registry)),
            )
        elif not isinstance(self.companion_registry, AuthorityDatabasePath):
            raise CatalogProfileError(
                "companion_registry must be AuthorityDatabasePath or a mapping"
            )
        if self.companion_registry.role != "companion_registry":
            object.__setattr__(
                self,
                "companion_registry",
                AuthorityDatabasePath(
                    path=self.companion_registry.path,
                    storage_kind=self.companion_registry.storage_kind,
                    role="companion_registry",
                    allowlist=self.companion_registry.allowlist,
                ),
            )

        if self.catalog_metadata.path == self.companion_registry.path:
            raise CatalogProfileError(
                "catalog metadata and companion-registry paths must be distinct"
            )

        if isinstance(self.quack_endpoint, Mapping):
            object.__setattr__(
                self, "quack_endpoint", QuackEndpointProfile(**dict(self.quack_endpoint))
            )
        elif not isinstance(self.quack_endpoint, QuackEndpointProfile):
            raise CatalogProfileError(
                "quack_endpoint must be QuackEndpointProfile or a mapping"
            )

        if isinstance(self.owner_lease, Mapping):
            object.__setattr__(
                self, "owner_lease", OwnerLeaseBinding(**dict(self.owner_lease))
            )
        elif not isinstance(self.owner_lease, OwnerLeaseBinding):
            raise CatalogProfileError(
                "owner_lease must be OwnerLeaseBinding or a mapping"
            )

        if isinstance(self.parquet_namespace, Mapping):
            object.__setattr__(
                self,
                "parquet_namespace",
                ParquetNamespace(**dict(self.parquet_namespace)),
            )
        elif not isinstance(self.parquet_namespace, ParquetNamespace):
            raise CatalogProfileError(
                "parquet_namespace must be ParquetNamespace or a mapping"
            )

        if isinstance(self.secret_profile, Mapping):
            object.__setattr__(
                self, "secret_profile", SecretProfile(**dict(self.secret_profile))
            )
        elif not isinstance(self.secret_profile, SecretProfile):
            raise CatalogProfileError(
                "secret_profile must be SecretProfile or a mapping"
            )

        if isinstance(self.encryption, Mapping):
            object.__setattr__(
                self, "encryption", EncryptionDefaults(**dict(self.encryption))
            )
        elif not isinstance(self.encryption, EncryptionDefaults):
            raise CatalogProfileError(
                "encryption must be EncryptionDefaults or a mapping"
            )

        if self.ducklake_supplies_authorization:
            raise CatalogProfileError(
                "DuckLake supplies no role or authorization layer; the trusted "
                "broker independently authorizes every privileged call"
            )
        if self.remote_clients_may_open_catalog_file:
            raise CatalogProfileError(
                "remote clients cannot directly open, mount, or mutate the "
                "catalog file; all access is through the fenced owner"
            )
        if not self.same_shard_serialization:
            raise CatalogProfileError(
                "same-shard requests must be serialized through the fenced owner"
            )
        if not self.independent_shard_concurrency:
            raise CatalogProfileError(
                "independent catalog shards must be allowed to run concurrently"
            )

        identities = dict(self.identities or {})
        if not identities:
            identities = dict(default_identity_capabilities(catalog_id=catalog_id))
        normalized: dict[CatalogIdentityRole, IdentityCapabilityProfile] = {}
        for key, value in identities.items():
            role = _coerce_enum(CatalogIdentityRole, key, field_name="identity_role")
            if isinstance(value, IdentityCapabilityProfile):
                value_role = _coerce_enum(
                    CatalogIdentityRole, value.role, field_name="identity_role"
                )
                if value_role is not role:
                    raise CatalogProfileError(
                        f"identity map key {role.value} does not match profile "
                        f"role {value_role.value}"
                    )
                if value.role is not value_role:
                    # Rebuild after enum reload so role identity matches map key.
                    value = IdentityCapabilityProfile(
                        role=value_role,
                        os_identity=value.os_identity,
                        endpoint_access=value.endpoint_access,
                        object_read=value.object_read,
                        object_write=value.object_write,
                        object_delete=value.object_delete,
                        open_catalog_file=value.open_catalog_file,
                        broker_authorize=value.broker_authorize,
                        inject_quack_capability=value.inject_quack_capability,
                    )
                normalized[role] = value
            elif isinstance(value, Mapping):
                payload = dict(value)
                payload["role"] = role
                normalized[role] = IdentityCapabilityProfile(**payload)
            else:
                raise CatalogProfileError(
                    f"identity for {role.value} must be IdentityCapabilityProfile "
                    "or a mapping"
                )
        required = set(CatalogIdentityRole)
        missing = required - set(normalized)
        if missing:
            raise CatalogProfileError(
                "identities missing roles: "
                + ", ".join(sorted(role.value for role in missing))
            )
        object.__setattr__(self, "identities", MappingProxyType(normalized))

        schema = str(self.schema or CATALOG_PROFILE_SCHEMA).strip()
        if schema != CATALOG_PROFILE_SCHEMA:
            raise CatalogProfileError(
                f"unsupported catalog profile schema {self.schema!r}; "
                f"expected {CATALOG_PROFILE_SCHEMA!r}"
            )
        object.__setattr__(self, "schema", schema)

    def identity(self, role: CatalogIdentityRole | str) -> IdentityCapabilityProfile:
        resolved = _coerce_enum(CatalogIdentityRole, role, field_name="role")
        return self.identities[resolved]

    def safe_attach_options(self) -> AttachOptions:
        return build_attach_options(AttachMode.SAFE)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "implementation_generation": _IMPLEMENTATION_GENERATION,
                "catalog_id": self.catalog_id,
                "catalog_metadata": dict(self.catalog_metadata.as_mapping()),
                "companion_registry": dict(self.companion_registry.as_mapping()),
                "quack_endpoint": dict(self.quack_endpoint.as_mapping()),
                "owner_lease": dict(self.owner_lease.as_mapping()),
                "parquet_namespace": dict(self.parquet_namespace.as_mapping()),
                "secret_profile": dict(self.secret_profile.as_mapping()),
                "identities": {
                    role.value: dict(profile.as_mapping())
                    for role, profile in self.identities.items()
                },
                "encryption": dict(self.encryption.as_mapping()),
                "ducklake_supplies_authorization": False,
                "remote_clients_may_open_catalog_file": False,
                "same_shard_serialization": True,
                "independent_shard_concurrency": True,
                "attach_safe_options": dict(ATTACH_MODE_SAFE_OPTIONS),
                "single_owner_process": True,
                "owner_opens_catalog_file": True,
            }
        )


def project_catalog_profile(profile: CatalogShardProfile) -> Mapping[str, Any]:
    """Return a sanitized configuration projection with no secret material."""

    projected = dict(profile.as_mapping())
    assert_no_secrets_in_projection(projected)
    return MappingProxyType(projected)
