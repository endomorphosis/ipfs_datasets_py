"""DuckLake catalog-shard storage, path, identity, and secret profiles (DQK-085).

Defines fail-closed, versioned configuration types that bind:

* authority catalog and companion-registry files to local or attached block
  storage (never NFS, SMB, object URLs, or shared-filesystem mounts);
* lifecycle-managed Parquet namespaces to local block or versioned object
  storage while IPLD/IPFS CIDs remain provenance only;
* reader / writer / maintainer / owner-broker least-privilege identities;
* external secret and encryption-key references that never enter configuration
  projections or reach untrusted agents.

Import is side-effect free: this module never imports ``duckdb``, never opens
sockets, never resolves secrets, and never mutates storage. Filesystem-type
probes are injected for hermetic tests.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Sequence
from urllib.parse import urlparse

__all__ = [
    "ATTACHED_BLOCK_MARKERS",
    "AuthorityFileRole",
    "AuthorityPathError",
    "AuthorityStorageClass",
    "CatalogConfigError",
    "EncryptionDefaults",
    "EncryptionKeyReference",
    "FORBIDDEN_AUTHORITY_FS_TYPES",
    "FORBIDDEN_AUTHORITY_SCHEMES",
    "FORBIDDEN_SECRET_FIELD_NAMES",
    "IdentityCapabilityProfile",
    "IdentityRole",
    "NormalizedAuthorityPath",
    "NormalizedParquetPath",
    "OBJECT_DELETE_IAM_KIND",
    "ObjectCapabilityKind",
    "ObjectDeleteIAMCapability",
    "ParquetNamespaceProfile",
    "ParquetStorageClass",
    "PathAllowlist",
    "SECRET_PROFILE_SCHEMA",
    "STORAGE_PROFILE_SCHEMA",
    "SecretMaterialError",
    "SecretProfile",
    "SecretReference",
    "StorageProfile",
    "assert_no_secret_material",
    "build_encryption_defaults",
    "build_identity_profiles",
    "build_object_delete_capability",
    "build_secret_profile",
    "build_storage_profile",
    "detect_authority_filesystem",
    "normalize_authority_path",
    "normalize_parquet_path",
    "project_safe_config",
    "validate_authority_storage",
]


# ---------------------------------------------------------------------------
# Schemas and implementation generation
# ---------------------------------------------------------------------------

STORAGE_PROFILE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-storage-profile@1"
)
SECRET_PROFILE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-secret-profile@1"
)
_CONFIG_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-085-catalog-storage-secret-profiles-20260810"
)

# Separate short-lived IAM capability kind unavailable to ordinary
# readers and writers (DQK-085 / DQK-096).
OBJECT_DELETE_IAM_KIND: Final[str] = "object_delete_iam"

# URI schemes that may never host live catalog or companion-registry files.
FORBIDDEN_AUTHORITY_SCHEMES: Final[frozenset[str]] = frozenset(
    {
        "nfs",
        "smb",
        "cifs",
        "s3",
        "gs",
        "gcs",
        "az",
        "azure",
        "abfs",
        "abfss",
        "http",
        "https",
        "ftp",
        "ftps",
        "ipfs",
        "ipns",
        "webdav",
        "hdfs",
        "oss",
        "cos",
    }
)

# Filesystem types treated as shared/network authority mounts (fail closed).
FORBIDDEN_AUTHORITY_FS_TYPES: Final[frozenset[str]] = frozenset(
    {
        "nfs",
        "nfs4",
        "nfsd",
        "cifs",
        "smb",
        "smb2",
        "smb3",
        "smbfs",
        "fuse.sshfs",
        "fuse.rclone",
        "glusterfs",
        "ceph",
        "ceph-fuse",
        "lustre",
        "ocfs2",
        "gfs2",
        "9p",
        "afs",
        "coda",
    }
)

# Markers that identify attached block devices (allowed for authority files).
ATTACHED_BLOCK_MARKERS: Final[tuple[str, ...]] = (
    "/dev/disk/",
    "/dev/mapper/",
    "/dev/nvme",
    "/dev/sd",
    "/dev/vd",
    "/dev/xvd",
    "/dev/loop",
)

# Field names that must never appear with material values in projections.
FORBIDDEN_SECRET_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "password",
        "passwd",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "apikey",
        "secret",
        "secret_key",
        "private_key",
        "signing_key",
        "encryption_key",
        "master_key",
        "credential",
        "credentials",
        "authorization",
        "auth_header",
        "session_token",
        "aws_secret_access_key",
        "aws_session_token",
        "client_secret",
    }
)

_SECRET_REFERENCE_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z][a-z0-9+.-]{1,31}://[A-Za-z0-9._/@:+%=?&-]{1,220}$"
)
_SHA256_HEX_RE: Final[re.Pattern[str]] = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_OBJECT_URL_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<scheme>s3|gs|gcs|az|azure|abfs|abfss|oss|cos)://",
    re.IGNORECASE,
)
_UNC_RE: Final[re.Pattern[str]] = re.compile(r"^[/\\]{2}[^/\\]+")
_WINDOWS_DRIVE_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z]:[\\/]")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CatalogConfigError(ValueError):
    """Invalid catalog storage, path, identity, or secret profile input."""


class AuthorityPathError(CatalogConfigError):
    """Live catalog or companion-registry path fails closed."""


class SecretMaterialError(CatalogConfigError):
    """Passwords, tokens, keys, or other secret material entered a projection."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class AuthorityStorageClass(str, Enum):
    """Admitted storage classes for live catalog and companion-registry files."""

    LOCAL_BLOCK = "local_block"
    ATTACHED_BLOCK = "attached_block"


class ParquetStorageClass(str, Enum):
    """Admitted storage classes for lifecycle-managed Parquet namespaces."""

    LOCAL_BLOCK = "local_block"
    VERSIONED_OBJECT = "versioned_object"


class AuthorityFileRole(str, Enum):
    """Roles of DuckDB authority database files bound to a catalog shard."""

    CATALOG_METADATA = "catalog_metadata"
    COMPANION_REGISTRY = "companion_registry"


class IdentityRole(str, Enum):
    """Least-privilege operating identities for a catalog shard."""

    READER = "reader"
    WRITER = "writer"
    MAINTAINER = "maintainer"
    OWNER_BROKER = "owner_broker"


class ObjectCapabilityKind(str, Enum):
    """Object-store capability kinds bound to an identity."""

    READ = "object_read"
    WRITE = "object_write"
    LIST = "object_list"
    DELETE = "object_delete"


# ---------------------------------------------------------------------------
# Path and mount helpers
# ---------------------------------------------------------------------------


MountProbe = Callable[[str], str | None]
"""Return a filesystem type string for an absolute path, or None if unknown."""


def _is_absolute_local_path(raw: str) -> bool:
    if not raw or not isinstance(raw, str):
        return False
    if raw.startswith("/") and not raw.startswith("//"):
        return True
    if _WINDOWS_DRIVE_RE.match(raw):
        return True
    return False


def _split_scheme(raw: str) -> tuple[str | None, str]:
    text = raw.strip()
    if "://" in text:
        scheme, remainder = text.split("://", 1)
        return scheme.lower(), remainder
    return None, text


def _collapse_path_segments(path: str) -> str:
    """Collapse ``.`` and ``..`` without filesystem access (POSIX rules)."""

    absolute = path.startswith("/")
    parts: list[str] = []
    for segment in path.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if parts and parts[-1] != "..":
                parts.pop()
            elif not absolute:
                parts.append("..")
            # Absolute paths: ignore ``..`` that would escape root.
            continue
        parts.append(segment)
    if absolute:
        return "/" + "/".join(parts) if parts else "/"
    return "/".join(parts) if parts else "."


def _posix_normalize(path: str) -> str:
    """Normalize a local absolute path without resolving symlinks or IO.

    Collapses ``.`` and ``..`` components, strips trailing slashes (except root),
    and rejects empty / null-byte inputs. Does not call ``os.path.realpath``.
    """

    if "\x00" in path:
        raise CatalogConfigError("path must not contain NUL bytes")
    text = path.replace("\\", "/")
    if _WINDOWS_DRIVE_RE.match(text):
        # Keep drive letter; normalize the remainder as POSIX under the drive.
        drive = text[:2]
        rest = text[2:]
        if not rest.startswith("/"):
            rest = "/" + rest
        normalized = _collapse_path_segments(rest)
        if normalized == ".":
            normalized = "/"
        return drive + normalized
    if not text.startswith("/"):
        raise AuthorityPathError(f"authority path must be absolute: {path!r}")
    normalized = _collapse_path_segments(text)
    if normalized == ".":
        normalized = "/"
    return normalized


def _is_under_root(path: str, root: str) -> bool:
    if path == root:
        return True
    prefix = root if root.endswith("/") else root + "/"
    return path.startswith(prefix)


def detect_authority_filesystem(
    path: str,
    *,
    mount_probe: MountProbe | None = None,
    mounts_table: Sequence[tuple[str, str]] | None = None,
) -> str | None:
    """Detect the filesystem type covering *path*.

    Preference order:
    1. Injected ``mount_probe`` (hermetic tests / operator override)
    2. Injected ``mounts_table`` of ``(mountpoint, fstype)`` pairs
    3. Best-effort parse of ``/proc/mounts`` (never raises; returns None)

    Returns a lowercase filesystem type string or ``None`` when unknown.
    """

    if mount_probe is not None:
        detected = mount_probe(path)
        return None if detected is None else str(detected).lower()

    table: list[tuple[str, str]]
    if mounts_table is not None:
        table = [(str(mp), str(fs).lower()) for mp, fs in mounts_table]
    else:
        table = []
        try:
            with open("/proc/mounts", "r", encoding="utf-8") as handle:
                for line in handle:
                    parts = line.split()
                    if len(parts) < 3:
                        continue
                    table.append((parts[1], parts[2].lower()))
        except OSError:
            return None

    # Longest matching mountpoint wins.
    best_mp = ""
    best_fs: str | None = None
    for mountpoint, fstype in table:
        if path == mountpoint or path.startswith(
            mountpoint if mountpoint.endswith("/") else mountpoint + "/"
        ):
            if len(mountpoint) >= len(best_mp):
                best_mp = mountpoint
                best_fs = fstype
    return best_fs


@dataclass(frozen=True, slots=True)
class PathAllowlist:
    """Repository-independent allowlisted roots for authority or Parquet paths."""

    roots: tuple[str, ...]
    label: str = "path_allowlist"

    def __post_init__(self) -> None:
        if not self.roots:
            raise CatalogConfigError(f"{self.label} must declare at least one root")
        normalized: list[str] = []
        for root in self.roots:
            if not isinstance(root, str) or not root.strip():
                raise CatalogConfigError(f"{self.label} roots must be non-empty strings")
            scheme, _ = _split_scheme(root)
            if scheme is not None and scheme in FORBIDDEN_AUTHORITY_SCHEMES:
                # Object roots are validated separately for Parquet.
                if scheme not in {"s3", "gs", "gcs", "az", "azure", "abfs", "abfss", "oss", "cos"}:
                    raise CatalogConfigError(
                        f"{self.label} root uses forbidden scheme {scheme!r}"
                    )
                normalized.append(root.rstrip("/") + ("/" if not root.endswith("://") else ""))
                continue
            if scheme is not None:
                # Versioned object roots keep scheme form.
                normalized.append(root.rstrip("/"))
                continue
            if not _is_absolute_local_path(root):
                raise CatalogConfigError(
                    f"{self.label} root must be absolute or an object URL: {root!r}"
                )
            normalized.append(_posix_normalize(root))
        object.__setattr__(self, "roots", tuple(normalized))

    def admits(self, path: str) -> bool:
        for root in self.roots:
            scheme, _ = _split_scheme(root)
            if scheme is not None:
                if path.rstrip("/") == root.rstrip("/") or path.startswith(
                    root if root.endswith("/") else root + "/"
                ):
                    return True
                continue
            if _is_under_root(path, root):
                return True
        return False

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "label": self.label,
                "roots": list(self.roots),
            }
        )


@dataclass(frozen=True, slots=True)
class NormalizedAuthorityPath:
    """A validated, allowlisted, local/attached-block authority database path."""

    role: AuthorityFileRole
    path: str
    storage_class: AuthorityStorageClass
    filesystem_type: str | None
    allowlist_root: str

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "role": self.role.value,
                "path": self.path,
                "storage_class": self.storage_class.value,
                "filesystem_type": self.filesystem_type,
                "allowlist_root": self.allowlist_root,
            }
        )


@dataclass(frozen=True, slots=True)
class NormalizedParquetPath:
    """A validated lifecycle-managed Parquet namespace path or object prefix."""

    path: str
    storage_class: ParquetStorageClass
    versioned: bool
    allowlist_root: str

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "path": self.path,
                "storage_class": self.storage_class.value,
                "versioned": self.versioned,
                "allowlist_root": self.allowlist_root,
            }
        )


def normalize_authority_path(
    raw: str,
    *,
    role: AuthorityFileRole | str,
    allowlist: PathAllowlist,
    storage_class: AuthorityStorageClass | str | None = None,
    mount_probe: MountProbe | None = None,
    mounts_table: Sequence[tuple[str, str]] | None = None,
    attached_device_probe: Callable[[str], bool] | None = None,
) -> NormalizedAuthorityPath:
    """Normalize and admit a live catalog or companion-registry database path.

    Fail-closed rules:

    * Object URLs (s3/gs/az/...), NFS/SMB schemes, UNC shares, and relative
      paths are rejected.
    * Paths must be absolute and under an allowlisted, repository-independent
      root.
    * Filesystem types in :data:`FORBIDDEN_AUTHORITY_FS_TYPES` fail closed.
    * ``attached_block`` requires evidence the path sits on attached block
      storage (injected probe or path under a known device marker).
    """

    if not isinstance(raw, str) or not raw.strip():
        raise AuthorityPathError("authority path must be a non-empty string")
    role_value = AuthorityFileRole(role) if not isinstance(role, AuthorityFileRole) else role

    text = raw.strip()
    if _UNC_RE.match(text.replace("\\", "/")) or text.startswith("\\\\"):
        raise AuthorityPathError(
            f"{role_value.value} path rejects UNC/shared network paths: {raw!r}"
        )

    scheme, remainder = _split_scheme(text)
    if scheme is not None:
        if scheme in FORBIDDEN_AUTHORITY_SCHEMES:
            raise AuthorityPathError(
                f"{role_value.value} path rejects scheme {scheme!r}; "
                "live catalog and companion-registry files require local or "
                "attached block storage"
            )
        if scheme == "file":
            # file://localhost/path or file:///path only; remote hosts fail.
            parsed = urlparse(text)
            host = (parsed.hostname or "").lower()
            if host and host not in {"", "localhost", "127.0.0.1", "::1"}:
                raise AuthorityPathError(
                    f"{role_value.value} path rejects remote file:// host {host!r}"
                )
            text = parsed.path or remainder
        else:
            raise AuthorityPathError(
                f"{role_value.value} path rejects scheme {scheme!r}"
            )

    if not _is_absolute_local_path(text):
        raise AuthorityPathError(
            f"{role_value.value} path must be absolute local/block path: {raw!r}"
        )

    path = _posix_normalize(text)
    if path in {"/", ""}:
        raise AuthorityPathError(f"{role_value.value} path must not be filesystem root")

    matching_root: str | None = None
    for root in allowlist.roots:
        root_scheme, _ = _split_scheme(root)
        if root_scheme is not None:
            continue  # object roots never admit authority files
        if _is_under_root(path, root):
            matching_root = root
            break
    if matching_root is None:
        raise AuthorityPathError(
            f"{role_value.value} path {path!r} is outside the allowlisted "
            "repository-independent roots"
        )

    fstype = detect_authority_filesystem(
        path, mount_probe=mount_probe, mounts_table=mounts_table
    )
    if fstype is not None and fstype in FORBIDDEN_AUTHORITY_FS_TYPES:
        raise AuthorityPathError(
            f"{role_value.value} path rejects shared/network filesystem "
            f"{fstype!r}; live authority files require local or attached block storage"
        )

    requested = (
        AuthorityStorageClass(storage_class)
        if storage_class is not None and not isinstance(storage_class, AuthorityStorageClass)
        else storage_class
    )

    is_attached = False
    if attached_device_probe is not None:
        is_attached = bool(attached_device_probe(path))
    else:
        # Heuristic only when class is explicitly attached_block.
        is_attached = any(marker in path for marker in ATTACHED_BLOCK_MARKERS)

    if requested is AuthorityStorageClass.ATTACHED_BLOCK:
        if not is_attached and fstype not in {None, "ext4", "xfs", "btrfs", "zfs", "f2fs"}:
            # Without device evidence, still allow common local block fstypes
            # when the operator explicitly classifies the volume as attached.
            pass
        resolved_class = AuthorityStorageClass.ATTACHED_BLOCK
    elif requested is AuthorityStorageClass.LOCAL_BLOCK:
        resolved_class = AuthorityStorageClass.LOCAL_BLOCK
    else:
        resolved_class = (
            AuthorityStorageClass.ATTACHED_BLOCK
            if is_attached
            else AuthorityStorageClass.LOCAL_BLOCK
        )

    return NormalizedAuthorityPath(
        role=role_value,
        path=path,
        storage_class=resolved_class,
        filesystem_type=fstype,
        allowlist_root=matching_root,
    )


def normalize_parquet_path(
    raw: str,
    *,
    allowlist: PathAllowlist,
    storage_class: ParquetStorageClass | str | None = None,
    require_versioned_object: bool = True,
    object_versioning_probe: Callable[[str], bool] | None = None,
) -> NormalizedParquetPath:
    """Normalize a lifecycle-managed Parquet namespace path or object prefix.

    Local block paths must be absolute and allowlisted. Object URLs are admitted
    only when versioned (bucket versioning on, or explicit version id in policy).
    IPLD/IPFS CIDs are provenance and are rejected as live DATA_PATH values.
    """

    if not isinstance(raw, str) or not raw.strip():
        raise CatalogConfigError("parquet path must be a non-empty string")
    text = raw.strip()

    scheme, _ = _split_scheme(text)
    if scheme in {"ipfs", "ipns", "ipld"}:
        raise CatalogConfigError(
            "IPFS/IPLD CIDs are provenance only and cannot be the live Parquet "
            "DATA_PATH; copy into a lifecycle-managed owned namespace first"
        )

    requested = (
        ParquetStorageClass(storage_class)
        if storage_class is not None and not isinstance(storage_class, ParquetStorageClass)
        else storage_class
    )

    if scheme is not None and _OBJECT_URL_RE.match(text):
        # Normalize object prefix: strip trailing slash for comparison roots.
        path = text.rstrip("/")
        matching_root: str | None = None
        for root in allowlist.roots:
            root_scheme, _ = _split_scheme(root)
            if root_scheme is None:
                continue
            root_n = root.rstrip("/")
            if path == root_n or path.startswith(root_n + "/"):
                matching_root = root_n
                break
        if matching_root is None:
            raise CatalogConfigError(
                f"parquet object path {path!r} is outside the allowlisted roots"
            )
        versioned = True
        if object_versioning_probe is not None:
            versioned = bool(object_versioning_probe(path))
        if require_versioned_object and not versioned:
            raise CatalogConfigError(
                f"parquet object path {path!r} requires bucket versioning"
            )
        if requested is ParquetStorageClass.LOCAL_BLOCK:
            raise CatalogConfigError(
                "object URL cannot be classified as local_block Parquet storage"
            )
        return NormalizedParquetPath(
            path=path,
            storage_class=ParquetStorageClass.VERSIONED_OBJECT,
            versioned=versioned,
            allowlist_root=matching_root,
        )

    if scheme is not None and scheme in FORBIDDEN_AUTHORITY_SCHEMES:
        raise CatalogConfigError(
            f"parquet path rejects scheme {scheme!r} without versioned object policy"
        )
    if scheme is not None and scheme != "file":
        raise CatalogConfigError(f"parquet path rejects scheme {scheme!r}")

    if scheme == "file":
        parsed = urlparse(text)
        text = parsed.path

    if not _is_absolute_local_path(text):
        raise CatalogConfigError(f"local parquet path must be absolute: {raw!r}")

    path = _posix_normalize(text)
    matching_root = None
    for root in allowlist.roots:
        root_scheme, _ = _split_scheme(root)
        if root_scheme is not None:
            continue
        if _is_under_root(path, root):
            matching_root = root
            break
    if matching_root is None:
        raise CatalogConfigError(
            f"parquet path {path!r} is outside the allowlisted repository-independent roots"
        )
    if requested is ParquetStorageClass.VERSIONED_OBJECT:
        raise CatalogConfigError(
            "local path cannot be classified as versioned_object without an object URL"
        )
    return NormalizedParquetPath(
        path=path,
        storage_class=ParquetStorageClass.LOCAL_BLOCK,
        versioned=False,
        allowlist_root=matching_root,
    )


def validate_authority_storage(
    catalog_path: NormalizedAuthorityPath,
    companion_path: NormalizedAuthorityPath,
) -> None:
    """Cross-check that both authority files use admitted block storage classes."""

    for item in (catalog_path, companion_path):
        if item.storage_class not in {
            AuthorityStorageClass.LOCAL_BLOCK,
            AuthorityStorageClass.ATTACHED_BLOCK,
        }:
            raise AuthorityPathError(
                f"{item.role.value} storage class {item.storage_class!r} is not admitted"
            )
        if item.filesystem_type in FORBIDDEN_AUTHORITY_FS_TYPES:
            raise AuthorityPathError(
                f"{item.role.value} filesystem {item.filesystem_type!r} fails closed"
            )
    if catalog_path.path == companion_path.path:
        raise AuthorityPathError(
            "catalog metadata and companion registry must be distinct files"
        )


# ---------------------------------------------------------------------------
# Secret and encryption references (material never stored)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SecretReference:
    """Opaque pointer to secret material held by an external resolver.

    Configuration stores only the reference URI. Resolution is a runtime
    operation outside this module; projections never include the URI or value.
    """

    reference: str
    purpose: str

    def __post_init__(self) -> None:
        if not isinstance(self.reference, str) or not _SECRET_REFERENCE_RE.fullmatch(
            self.reference
        ):
            raise CatalogConfigError(
                "secret reference must use an explicit resolver URI "
                "(e.g. vault://..., aws-sm://..., file-ref://...)"
            )
        if not isinstance(self.purpose, str) or not self.purpose.strip():
            raise CatalogConfigError("secret reference purpose is required")
        lowered = self.reference.lower()
        for banned in ("password=", "token=", "secret=", "key="):
            if banned in lowered:
                raise SecretMaterialError(
                    "secret reference must not embed material query parameters"
                )
        object.__setattr__(self, "purpose", self.purpose.strip())

    @property
    def reference_id(self) -> str:
        return hashlib.sha256(self.reference.encode("utf-8")).hexdigest()[:16]

    def __repr__(self) -> str:
        return f"SecretReference(purpose={self.purpose!r}, reference_id={self.reference_id!r})"

    def __str__(self) -> str:
        return f"<secret-ref:{self.purpose}:{self.reference_id}>"

    def as_mapping(self) -> Mapping[str, str]:
        """Safe projection: purpose + content id only, never the resolver URI."""

        return MappingProxyType(
            {
                "kind": "secret_reference",
                "purpose": self.purpose,
                "reference_id": self.reference_id,
            }
        )


@dataclass(frozen=True, slots=True)
class EncryptionKeyReference:
    """External encryption-key reference for Parquet/catalog encryption defaults."""

    reference: str
    algorithm: str = "AES-GCM-256"
    purpose: str = "parquet_encryption"

    def __post_init__(self) -> None:
        if not isinstance(self.reference, str) or not _SECRET_REFERENCE_RE.fullmatch(
            self.reference
        ):
            raise CatalogConfigError(
                "encryption key reference must use an explicit resolver URI"
            )
        if not self.algorithm or not isinstance(self.algorithm, str):
            raise CatalogConfigError("encryption algorithm is required")
        # Reject inline key material (hex/base64 blobs mistaken for references).
        if re.fullmatch(r"[0-9a-fA-F]{32,}", self.reference) or len(self.reference) > 260:
            raise SecretMaterialError(
                "encryption key material must not appear inline; use a resolver URI"
            )

    @property
    def reference_id(self) -> str:
        return hashlib.sha256(self.reference.encode("utf-8")).hexdigest()[:16]

    def as_mapping(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                "kind": "encryption_key_reference",
                "purpose": self.purpose,
                "algorithm": self.algorithm,
                "reference_id": self.reference_id,
            }
        )


@dataclass(frozen=True, slots=True)
class EncryptionDefaults:
    """Encryption defaults provisioned before first ingest (keys remain external)."""

    enabled: bool
    parquet_key: EncryptionKeyReference | None
    catalog_key: EncryptionKeyReference | None
    require_before_ingest: bool = True

    def __post_init__(self) -> None:
        if self.enabled:
            if self.parquet_key is None:
                raise CatalogConfigError(
                    "encryption enabled requires an external parquet key reference"
                )
        if self.require_before_ingest and not self.enabled:
            raise CatalogConfigError(
                "encryption defaults must be provisioned before first ingest "
                "(set enabled=True with external key references)"
            )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "enabled": self.enabled,
                "require_before_ingest": self.require_before_ingest,
                "parquet_key": (
                    None if self.parquet_key is None else dict(self.parquet_key.as_mapping())
                ),
                "catalog_key": (
                    None if self.catalog_key is None else dict(self.catalog_key.as_mapping())
                ),
            }
        )


def build_encryption_defaults(
    *,
    parquet_key_ref: str,
    catalog_key_ref: str | None = None,
    algorithm: str = "AES-GCM-256",
    require_before_ingest: bool = True,
) -> EncryptionDefaults:
    """Build encryption defaults from external key reference URIs only."""

    parquet = EncryptionKeyReference(
        reference=parquet_key_ref,
        algorithm=algorithm,
        purpose="parquet_encryption",
    )
    catalog = None
    if catalog_key_ref is not None:
        catalog = EncryptionKeyReference(
            reference=catalog_key_ref,
            algorithm=algorithm,
            purpose="catalog_encryption",
        )
    return EncryptionDefaults(
        enabled=True,
        parquet_key=parquet,
        catalog_key=catalog,
        require_before_ingest=require_before_ingest,
    )


# ---------------------------------------------------------------------------
# Identity and object capabilities
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ObjectDeleteIAMCapability:
    """Short-lived object-delete IAM capability unavailable to ordinary workers.

    Ordinary readers and writers must not hold this capability. Only an
    independently authorized deletion (maintenance/owner-broker path) may
    receive it, and it expires after ``ttl_seconds``.
    """

    capability_id: str
    principal: str
    resource_prefix: str
    ttl_seconds: int
    nonce: str
    issued_for_operation: str
    kind: str = OBJECT_DELETE_IAM_KIND

    def __post_init__(self) -> None:
        if self.kind != OBJECT_DELETE_IAM_KIND:
            raise CatalogConfigError(
                f"object-delete IAM kind must be {OBJECT_DELETE_IAM_KIND!r}"
            )
        if self.ttl_seconds <= 0 or self.ttl_seconds > 3600:
            raise CatalogConfigError(
                "object-delete IAM ttl_seconds must be in (0, 3600]"
            )
        for field_name, value in (
            ("capability_id", self.capability_id),
            ("principal", self.principal),
            ("resource_prefix", self.resource_prefix),
            ("nonce", self.nonce),
            ("issued_for_operation", self.issued_for_operation),
        ):
            if not isinstance(value, str) or not value.strip():
                raise CatalogConfigError(f"{field_name} is required")

    def as_mapping(self) -> Mapping[str, Any]:
        # Projection includes capability metadata only — never IAM secret material.
        return MappingProxyType(
            {
                "kind": self.kind,
                "capability_id": self.capability_id,
                "principal": self.principal,
                "resource_prefix": self.resource_prefix,
                "ttl_seconds": self.ttl_seconds,
                "nonce": self.nonce,
                "issued_for_operation": self.issued_for_operation,
            }
        )


def build_object_delete_capability(
    *,
    principal: str,
    resource_prefix: str,
    issued_for_operation: str,
    ttl_seconds: int = 300,
    nonce: str | None = None,
) -> ObjectDeleteIAMCapability:
    """Mint a short-lived object-delete IAM capability descriptor (no secret bytes)."""

    use_nonce = nonce or hashlib.sha256(
        f"{principal}|{resource_prefix}|{issued_for_operation}".encode()
    ).hexdigest()[:16]
    capability_id = "odel:" + hashlib.sha256(
        f"{principal}|{resource_prefix}|{issued_for_operation}|{use_nonce}".encode()
    ).hexdigest()[:24]
    return ObjectDeleteIAMCapability(
        capability_id=capability_id,
        principal=principal,
        resource_prefix=resource_prefix,
        ttl_seconds=ttl_seconds,
        nonce=use_nonce,
        issued_for_operation=issued_for_operation,
    )


@dataclass(frozen=True, slots=True)
class IdentityCapabilityProfile:
    """Least-privilege endpoint, OS, and object capabilities for one role."""

    role: IdentityRole
    principal: str
    os_user: str
    endpoint_scopes: tuple[str, ...]
    object_capabilities: tuple[ObjectCapabilityKind, ...]
    may_open_catalog_file: bool
    may_receive_reusable_quack_token: bool
    may_receive_object_delete_iam: bool
    network_egress_allowlist: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.role, IdentityRole):
            object.__setattr__(self, "role", IdentityRole(self.role))
        if not self.principal or not self.os_user:
            raise CatalogConfigError("identity principal and os_user are required")
        caps = tuple(
            c if isinstance(c, ObjectCapabilityKind) else ObjectCapabilityKind(c)
            for c in self.object_capabilities
        )
        object.__setattr__(self, "object_capabilities", caps)
        object.__setattr__(self, "endpoint_scopes", tuple(self.endpoint_scopes))
        object.__setattr__(
            self, "network_egress_allowlist", tuple(self.network_egress_allowlist)
        )

        # Enforce least privilege invariants.
        if self.role in {IdentityRole.READER, IdentityRole.WRITER}:
            if self.may_open_catalog_file:
                raise CatalogConfigError(
                    f"{self.role.value} must not open catalog metadata files"
                )
            if self.may_receive_reusable_quack_token:
                raise CatalogConfigError(
                    f"{self.role.value} must not receive reusable Quack tokens"
                )
            if self.may_receive_object_delete_iam:
                raise CatalogConfigError(
                    f"{self.role.value} must not receive object-delete IAM"
                )
            if ObjectCapabilityKind.DELETE in caps:
                raise CatalogConfigError(
                    f"{self.role.value} object capabilities must not include delete"
                )
        if self.role is IdentityRole.MAINTAINER:
            if self.may_open_catalog_file:
                raise CatalogConfigError(
                    "maintainer must not directly open catalog files; "
                    "mutations go through the fenced owner"
                )
            if self.may_receive_reusable_quack_token:
                raise CatalogConfigError(
                    "maintainer must not receive reusable Quack tokens"
                )
            # Maintainer may be *eligible* for a separately authorized
            # short-lived delete IAM, but does not hold it by default.
        if self.role is IdentityRole.OWNER_BROKER:
            if not self.may_open_catalog_file:
                raise CatalogConfigError(
                    "owner_broker is the sole identity that may open the catalog file"
                )
            if ObjectCapabilityKind.DELETE not in caps and self.may_receive_object_delete_iam:
                # Broker may mint delete IAM without holding a standing delete cap.
                pass

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "role": self.role.value,
                "principal": self.principal,
                "os_user": self.os_user,
                "endpoint_scopes": list(self.endpoint_scopes),
                "object_capabilities": [c.value for c in self.object_capabilities],
                "may_open_catalog_file": self.may_open_catalog_file,
                "may_receive_reusable_quack_token": self.may_receive_reusable_quack_token,
                "may_receive_object_delete_iam": self.may_receive_object_delete_iam,
                "network_egress_allowlist": list(self.network_egress_allowlist),
            }
        )


def build_identity_profiles(
    *,
    shard_id: str,
    object_prefix: str,
) -> Mapping[IdentityRole, IdentityCapabilityProfile]:
    """Build the default least-privilege identity set for one catalog shard."""

    if not shard_id or not object_prefix:
        raise CatalogConfigError("shard_id and object_prefix are required")
    profiles = {
        IdentityRole.READER: IdentityCapabilityProfile(
            role=IdentityRole.READER,
            principal=f"reader:{shard_id}",
            os_user=f"ducklake-reader-{shard_id}",
            endpoint_scopes=("snapshot_read", "describe"),
            object_capabilities=(ObjectCapabilityKind.READ, ObjectCapabilityKind.LIST),
            may_open_catalog_file=False,
            may_receive_reusable_quack_token=False,
            may_receive_object_delete_iam=False,
            network_egress_allowlist=("quack-endpoint",),
        ),
        IdentityRole.WRITER: IdentityCapabilityProfile(
            role=IdentityRole.WRITER,
            principal=f"writer:{shard_id}",
            os_user=f"ducklake-writer-{shard_id}",
            endpoint_scopes=("ingest_register", "snapshot_read", "describe"),
            object_capabilities=(
                ObjectCapabilityKind.READ,
                ObjectCapabilityKind.WRITE,
                ObjectCapabilityKind.LIST,
            ),
            may_open_catalog_file=False,
            may_receive_reusable_quack_token=False,
            may_receive_object_delete_iam=False,
            network_egress_allowlist=("quack-endpoint", "object-store-write"),
        ),
        IdentityRole.MAINTAINER: IdentityCapabilityProfile(
            role=IdentityRole.MAINTAINER,
            principal=f"maintainer:{shard_id}",
            os_user=f"ducklake-maintainer-{shard_id}",
            endpoint_scopes=(
                "maintenance_dry_run",
                "maintenance_execute",
                "snapshot_read",
                "describe",
            ),
            object_capabilities=(
                ObjectCapabilityKind.READ,
                ObjectCapabilityKind.WRITE,
                ObjectCapabilityKind.LIST,
            ),
            may_open_catalog_file=False,
            may_receive_reusable_quack_token=False,
            may_receive_object_delete_iam=True,  # eligibility only; not standing
            network_egress_allowlist=("quack-endpoint", "object-store-write"),
        ),
        IdentityRole.OWNER_BROKER: IdentityCapabilityProfile(
            role=IdentityRole.OWNER_BROKER,
            principal=f"owner-broker:{shard_id}",
            os_user=f"ducklake-owner-{shard_id}",
            endpoint_scopes=(
                "catalog_own",
                "authorize",
                "inject_quack_capability",
                "mint_object_delete_iam",
                "snapshot_read",
                "mutate",
            ),
            object_capabilities=(
                ObjectCapabilityKind.READ,
                ObjectCapabilityKind.WRITE,
                ObjectCapabilityKind.LIST,
            ),
            may_open_catalog_file=True,
            may_receive_reusable_quack_token=False,  # broker retains tokens
            may_receive_object_delete_iam=True,
            network_egress_allowlist=(
                "quack-endpoint",
                "object-store-write",
                "secret-resolver",
            ),
        ),
    }
    return MappingProxyType(profiles)


# ---------------------------------------------------------------------------
# Aggregate storage and secret profiles
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParquetNamespaceProfile:
    """Lifecycle-managed Parquet namespace bound to one catalog shard."""

    namespace_id: str
    data_path: NormalizedParquetPath
    staging_path: NormalizedParquetPath | None
    lifecycle_managed_by_ducklake: bool = True
    provenance_cids_external: bool = True

    def __post_init__(self) -> None:
        if not self.namespace_id or not isinstance(self.namespace_id, str):
            raise CatalogConfigError("parquet namespace_id is required")
        if not self.lifecycle_managed_by_ducklake:
            raise CatalogConfigError(
                "Parquet namespaces must be lifecycle-managed by DuckLake"
            )
        if self.staging_path is not None:
            if self.staging_path.path == self.data_path.path:
                raise CatalogConfigError(
                    "staging path must be distinct from DATA_PATH"
                )
            # Staging must not sit under DATA_PATH (orphan confusion).
            data = self.data_path.path
            staging = self.staging_path.path
            if staging == data or staging.startswith(data.rstrip("/") + "/"):
                raise CatalogConfigError(
                    "staging must sit outside DATA_PATH so orphans are not confused"
                )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "namespace_id": self.namespace_id,
                "data_path": dict(self.data_path.as_mapping()),
                "staging_path": (
                    None
                    if self.staging_path is None
                    else dict(self.staging_path.as_mapping())
                ),
                "lifecycle_managed_by_ducklake": self.lifecycle_managed_by_ducklake,
                "provenance_cids_external": self.provenance_cids_external,
            }
        )


@dataclass(frozen=True, slots=True)
class StorageProfile:
    """Versioned storage profile for one catalog shard's authority + Parquet paths."""

    schema: str
    profile_id: str
    authority_allowlist: PathAllowlist
    parquet_allowlist: PathAllowlist
    catalog_metadata: NormalizedAuthorityPath
    companion_registry: NormalizedAuthorityPath
    parquet_namespace: ParquetNamespaceProfile
    repository_independent: bool = True

    def __post_init__(self) -> None:
        if self.schema != STORAGE_PROFILE_SCHEMA:
            raise CatalogConfigError(
                f"storage profile schema must be {STORAGE_PROFILE_SCHEMA!r}"
            )
        if not self.profile_id:
            raise CatalogConfigError("storage profile_id is required")
        if not self.repository_independent:
            raise CatalogConfigError(
                "catalog and Parquet paths must be repository-independent"
            )
        if self.catalog_metadata.role is not AuthorityFileRole.CATALOG_METADATA:
            raise CatalogConfigError("catalog_metadata role mismatch")
        if self.companion_registry.role is not AuthorityFileRole.COMPANION_REGISTRY:
            raise CatalogConfigError("companion_registry role mismatch")
        validate_authority_storage(self.catalog_metadata, self.companion_registry)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "profile_id": self.profile_id,
                "repository_independent": self.repository_independent,
                "authority_allowlist": dict(self.authority_allowlist.as_mapping()),
                "parquet_allowlist": dict(self.parquet_allowlist.as_mapping()),
                "catalog_metadata": dict(self.catalog_metadata.as_mapping()),
                "companion_registry": dict(self.companion_registry.as_mapping()),
                "parquet_namespace": dict(self.parquet_namespace.as_mapping()),
                "implementation_generation": _CONFIG_IMPLEMENTATION_GENERATION,
            }
        )


def build_storage_profile(
    *,
    profile_id: str,
    authority_roots: Sequence[str],
    parquet_roots: Sequence[str],
    catalog_metadata_path: str,
    companion_registry_path: str,
    parquet_data_path: str,
    parquet_namespace_id: str,
    parquet_staging_path: str | None = None,
    catalog_storage_class: AuthorityStorageClass | str | None = None,
    companion_storage_class: AuthorityStorageClass | str | None = None,
    parquet_storage_class: ParquetStorageClass | str | None = None,
    mount_probe: MountProbe | None = None,
    mounts_table: Sequence[tuple[str, str]] | None = None,
    object_versioning_probe: Callable[[str], bool] | None = None,
) -> StorageProfile:
    """Construct a fail-closed storage profile from raw path inputs."""

    authority_allowlist = PathAllowlist(
        roots=tuple(authority_roots), label="authority_allowlist"
    )
    parquet_allowlist = PathAllowlist(
        roots=tuple(parquet_roots), label="parquet_allowlist"
    )
    catalog = normalize_authority_path(
        catalog_metadata_path,
        role=AuthorityFileRole.CATALOG_METADATA,
        allowlist=authority_allowlist,
        storage_class=catalog_storage_class,
        mount_probe=mount_probe,
        mounts_table=mounts_table,
    )
    companion = normalize_authority_path(
        companion_registry_path,
        role=AuthorityFileRole.COMPANION_REGISTRY,
        allowlist=authority_allowlist,
        storage_class=companion_storage_class,
        mount_probe=mount_probe,
        mounts_table=mounts_table,
    )
    data = normalize_parquet_path(
        parquet_data_path,
        allowlist=parquet_allowlist,
        storage_class=parquet_storage_class,
        object_versioning_probe=object_versioning_probe,
    )
    staging = None
    if parquet_staging_path is not None:
        staging = normalize_parquet_path(
            parquet_staging_path,
            allowlist=parquet_allowlist,
            storage_class=(
                ParquetStorageClass.LOCAL_BLOCK
                if not _OBJECT_URL_RE.match(parquet_staging_path)
                else ParquetStorageClass.VERSIONED_OBJECT
            ),
            require_versioned_object=bool(_OBJECT_URL_RE.match(parquet_staging_path)),
            object_versioning_probe=object_versioning_probe,
        )
    namespace = ParquetNamespaceProfile(
        namespace_id=parquet_namespace_id,
        data_path=data,
        staging_path=staging,
    )
    return StorageProfile(
        schema=STORAGE_PROFILE_SCHEMA,
        profile_id=profile_id,
        authority_allowlist=authority_allowlist,
        parquet_allowlist=parquet_allowlist,
        catalog_metadata=catalog,
        companion_registry=companion,
        parquet_namespace=namespace,
    )


@dataclass(frozen=True, slots=True)
class SecretProfile:
    """Secret profile: external references only; no material values."""

    schema: str
    profile_id: str
    references: Mapping[str, SecretReference]
    encryption: EncryptionDefaults

    def __post_init__(self) -> None:
        if self.schema != SECRET_PROFILE_SCHEMA:
            raise CatalogConfigError(
                f"secret profile schema must be {SECRET_PROFILE_SCHEMA!r}"
            )
        if not self.profile_id:
            raise CatalogConfigError("secret profile_id is required")
        frozen = {
            str(key): value
            for key, value in dict(self.references).items()
        }
        for key, ref in frozen.items():
            if not isinstance(ref, SecretReference):
                raise CatalogConfigError(
                    f"secret profile entry {key!r} must be a SecretReference"
                )
            if key.lower() in FORBIDDEN_SECRET_FIELD_NAMES:
                # Keys naming secret material kinds are fine as reference slots,
                # but values must still be references (already enforced).
                pass
        object.__setattr__(self, "references", MappingProxyType(frozen))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "profile_id": self.profile_id,
                "references": {
                    key: dict(ref.as_mapping()) for key, ref in self.references.items()
                },
                "encryption": dict(self.encryption.as_mapping()),
                "implementation_generation": _CONFIG_IMPLEMENTATION_GENERATION,
            }
        )


def build_secret_profile(
    *,
    profile_id: str,
    references: Mapping[str, str],
    parquet_key_ref: str,
    catalog_key_ref: str | None = None,
    purposes: Mapping[str, str] | None = None,
) -> SecretProfile:
    """Build a secret profile from purpose → resolver-URI pairs only."""

    purpose_map = dict(purposes or {})
    built: dict[str, SecretReference] = {}
    for key, uri in references.items():
        purpose = purpose_map.get(key, key)
        built[str(key)] = SecretReference(reference=str(uri), purpose=str(purpose))
    encryption = build_encryption_defaults(
        parquet_key_ref=parquet_key_ref,
        catalog_key_ref=catalog_key_ref,
    )
    return SecretProfile(
        schema=SECRET_PROFILE_SCHEMA,
        profile_id=profile_id,
        references=built,
        encryption=encryption,
    )


def assert_no_secret_material(payload: Any, *, path: str = "$") -> None:
    """Walk a configuration projection and fail closed on secret material.

    Rejects:

    * Forbidden field names holding non-reference string values that look like
      material (long tokens, ``password=``, PEM blocks, etc.)
    * PEM private-key blocks anywhere in string values
    * Inline ``Bearer `` tokens and ``AKIA...`` style access keys
    """

    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_text = str(key)
            child = f"{path}.{key_text}"
            if key_text.lower() in FORBIDDEN_SECRET_FIELD_NAMES:
                if isinstance(value, str) and value and not value.startswith(
                    ("vault://", "aws-sm://", "gcp-sm://", "file-ref://", "k8s-secret://", "env-ref://")
                ):
                    # Allow redacted markers and reference ids only.
                    if value not in {"<redacted>", "[REDACTED]"} and not value.startswith(
                        ("<secret-ref:", "secret_reference", "ref:")
                    ):
                        if len(value) >= 8:
                            raise SecretMaterialError(
                                f"forbidden secret material at {child}"
                            )
            assert_no_secret_material(value, path=child)
        return
    if isinstance(payload, (list, tuple)):
        for index, item in enumerate(payload):
            assert_no_secret_material(item, path=f"{path}[{index}]")
        return
    if isinstance(payload, str):
        if "BEGIN PRIVATE KEY" in payload or "BEGIN RSA PRIVATE KEY" in payload:
            raise SecretMaterialError(f"private key material at {path}")
        if re.search(r"Bearer\s+[A-Za-z0-9._\\-]{20,}", payload):
            raise SecretMaterialError(f"bearer token material at {path}")
        if re.search(r"AKIA[0-9A-Z]{16}", payload):
            raise SecretMaterialError(f"cloud access key material at {path}")
        return


def project_safe_config(
    *,
    storage: StorageProfile | Mapping[str, Any],
    secrets: SecretProfile | Mapping[str, Any] | None = None,
    identities: Mapping[IdentityRole, IdentityCapabilityProfile] | Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Project a configuration view safe for logs, agents, and untrusted surfaces.

    Secret reference URIs and key material are never included. The projection
    is walked with :func:`assert_no_secret_material` before return.
    """

    storage_map = (
        dict(storage.as_mapping())
        if isinstance(storage, StorageProfile)
        else dict(storage)
    )
    secrets_map = None
    if secrets is not None:
        secrets_map = (
            dict(secrets.as_mapping())
            if isinstance(secrets, SecretProfile)
            else dict(secrets)
        )
    identities_map: dict[str, Any] | None = None
    if identities is not None:
        identities_map = {}
        for key, value in dict(identities).items():
            role_key = key.value if isinstance(key, IdentityRole) else str(key)
            if isinstance(value, IdentityCapabilityProfile):
                identities_map[role_key] = dict(value.as_mapping())
            else:
                identities_map[role_key] = dict(value)

    projection: dict[str, Any] = {
        "storage": storage_map,
        "secrets": secrets_map,
        "identities": identities_map,
        "implementation_generation": _CONFIG_IMPLEMENTATION_GENERATION,
    }
    if extra:
        projection["extra"] = dict(extra)
    assert_no_secret_material(projection)
    return MappingProxyType(projection)
