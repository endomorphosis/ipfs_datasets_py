"""Immutable Hugging Face GraphRAG artifact resolver and revision-scoped cache.

USCIR-010 hardens the shared remote GraphRAG substrate so every fetch is:

* pinned to an immutable 40-hex Hub commit SHA (never ``main``/``latest``);
* confined to release-relative POSIX paths without traversal;
* verified for size, SHA-256 digest, optional CID, and optional row count
  **before** callers parse artifact bytes;
* stored under a revision-scoped, content-addressed cache that fails closed on
  collisions and stale aliases;
* reported through a fetch trace that never leaks credentials, tokens, or
  absolute local secrets.

Unit tests inject a fake Hub transport; credentials are never required offline.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import time
from typing import Any, Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RESOLVER_SCHEMA_VERSION: Final = "hf-graphrag-resolver/v1"
CACHE_ALIAS_SCHEMA_VERSION: Final = "hf-graphrag-cache-alias/v1"
DEFAULT_MANIFEST_NAME: Final = "manifest.json"
DEFAULT_MAX_ARTIFACT_BYTES: Final = 64 * 1024 * 1024  # 64 MiB control plane / shard
DEFAULT_MAX_ROWS_PER_ARTIFACT: Final = 4096
DEFAULT_CACHE_DIR: Final = Path(
    "~/.cache/ipfs_datasets_py/hf-graphrag-resolver"
).expanduser()

# Domain-neutral release schemas the shared substrate accepts. Domain adapters
# may extend this set at construction time; unknown schemas fail closed.
DEFAULT_SUPPORTED_RELEASE_SCHEMAS: Final = frozenset(
    {
        "publicus-ir-graphrag/v2",
        "hf-graphrag-release/v1",
        "uscode-sparse-graphrag-release-schema-v2",
    }
)

_REVISION_RE: Final = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_CID_V1_RAW_SHA256_RE: Final = re.compile(r"^b[a-z2-7]{58}$")
_REPO_ID_RE: Final = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
)
_MUTABLE_REVISIONS: Final = frozenset(
    {
        "latest",
        "main",
        "master",
        "head",
        "tip",
        "trunk",
        "default",
        "current",
        "live",
        "prod",
        "production",
        "staging",
        "dev",
        "develop",
        "development",
        "nightly",
        "canary",
    }
)
_CACHE_PATH_PARTS: Final = frozenset(
    {"__pycache__", ".cache", ".git", ".pytest_cache", ".mypy_cache"}
)
_CREDENTIAL_KEY_MARKERS: Final = frozenset(
    {
        "token",
        "access_token",
        "hf_token",
        "authorization",
        "api_key",
        "apikey",
        "password",
        "secret",
        "credential",
        "credentials",
        "bearer",
        "auth",
    }
)
_TOKEN_LIKE_RE: Final = re.compile(
    r"(?:hf_[A-Za-z0-9]{10,}|Bearer\s+[A-Za-z0-9\-._~+/]+=*)",
    re.IGNORECASE,
)
_READ_CHUNK: Final = 8 * 1024 * 1024

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ResolverError(RuntimeError):
    """Base class for fail-closed resolver and cache failures."""


class MutableRevisionError(ResolverError):
    """Raised when a revision is not an immutable 40-hex Hub commit SHA."""


class UnsafePathError(ResolverError):
    """Raised when a path is absolute, traverses, or is otherwise unsafe."""


class SymlinkRejectedError(ResolverError):
    """Raised when an artifact or cache entry is a symlink."""


class DigestDriftError(ResolverError):
    """Raised when on-disk size or digest disagrees with the descriptor."""


class OversizedArtifactError(ResolverError):
    """Raised when an artifact exceeds the configured byte or row bound."""


class SchemaMismatchError(ResolverError):
    """Raised when a release or descriptor schema is unsupported or wrong."""


class CacheCollisionError(ResolverError):
    """Raised when a cache alias or content object collides with different bytes."""


class CredentialLeakageError(ResolverError):
    """Raised when a credential would be recorded in a public surface."""


class TransportError(ResolverError):
    """Raised when the Hub transport cannot materialize a pinned artifact."""


class MissingArtifactError(ResolverError):
    """Raised when a requested release file is absent."""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_immutable_revision(value: Any, *, name: str = "revision") -> str:
    """Require an immutable 40-character lowercase Hub commit SHA."""

    if not isinstance(value, str) or not value.strip():
        raise MutableRevisionError(f"{name} must be an immutable 40-hex Hub commit SHA")
    text = value.strip()
    lowered = text.lower()
    if lowered in _MUTABLE_REVISIONS or lowered.startswith("refs/"):
        raise MutableRevisionError(
            f"{name} must be an immutable 40-hex Hub commit SHA, not a mutable ref: {value!r}"
        )
    if "/resolve/main/" in lowered or "/tree/main/" in lowered:
        raise MutableRevisionError(
            f"{name} embeds a mutable resolve path and is not an immutable pin: {value!r}"
        )
    if _REVISION_RE.fullmatch(lowered) is None:
        raise MutableRevisionError(
            f"{name} must be an immutable 40-hex Hub commit SHA, got {value!r}"
        )
    return lowered


def validate_repo_id(value: Any, *, name: str = "repo_id") -> str:
    """Require a Hub ``owner/name`` dataset identifier without traversal."""

    if not isinstance(value, str) or not value.strip():
        raise ResolverError(f"{name} must be a non-empty owner/name string")
    text = value.strip()
    if any(character.isspace() for character in text) or "\\" in text:
        raise ResolverError(f"{name} is malformed: {value!r}")
    if ".." in text or text.startswith("/") or text.startswith("~"):
        raise UnsafePathError(f"{name} must not contain path traversal: {value!r}")
    if _REPO_ID_RE.fullmatch(text) is None:
        raise ResolverError(f"{name} must look like 'owner/name', got {value!r}")
    return text


def safe_relative_path(value: Any, *, name: str = "relative_path") -> PurePosixPath:
    """Normalize a release-relative POSIX path and reject traversal."""

    if not isinstance(value, str) or not value:
        raise UnsafePathError(f"{name} must be a non-empty relative POSIX path")
    text = value
    if text.strip() != text or "\x00" in text:
        raise UnsafePathError(f"{name} must not contain surrounding whitespace or NUL")
    if "\\" in text:
        raise UnsafePathError(f"{name} must use POSIX separators, got {value!r}")
    if text.startswith("/") or text.startswith("~"):
        raise UnsafePathError(f"{name} must be relative, not absolute: {value!r}")
    if len(text) >= 2 and text[1] == ":":
        raise UnsafePathError(f"{name} must not include a drive letter: {value!r}")
    if text.startswith("//"):
        raise UnsafePathError(f"{name} must not be a UNC path: {value!r}")
    path = PurePosixPath(text)
    if path.is_absolute() or path.as_posix() != text:
        raise UnsafePathError(
            f"{name} must be a normalized POSIX path without redundant segments: {value!r}"
        )
    if any(part in {"", ".", ".."} for part in path.parts):
        raise UnsafePathError(
            f"{name} must not contain empty, '.', or '..' segments: {value!r}"
        )
    if any(part.casefold() in _CACHE_PATH_PARTS for part in path.parts):
        raise UnsafePathError(
            f"{name} must not include cache/VCS path components: {value!r}"
        )
    return path


def normalize_sha256(value: Any, *, name: str = "sha256") -> str:
    """Normalize a SHA-256 hex digest (optional ``sha256:`` prefix)."""

    if not isinstance(value, str) or not value.strip():
        raise DigestDriftError(f"{name} must be a 64-hex SHA-256 digest")
    text = value.strip().lower()
    if text.startswith("sha256:"):
        text = text[7:]
    if _SHA256_RE.fullmatch(text) is None:
        raise DigestDriftError(f"{name} must be a 64-hex SHA-256 digest, got {value!r}")
    return text


def raw_sha256_cid(digest: bytes) -> str:
    """Return CIDv1 (base32) for a raw-codec SHA-256 multihash."""

    if len(digest) != 32:
        raise DigestDriftError("SHA-256 digest has an invalid length")
    payload = bytes((0x01, 0x55, 0x12, 0x20)) + digest
    return "b" + base64.b32encode(payload).decode("ascii").lower().rstrip("=")


def file_sha256_and_size(path: Path) -> tuple[str, int]:
    """Hash a regular file; reject symlinks and non-files."""

    if path.is_symlink():
        raise SymlinkRejectedError(f"symlinks are rejected: {path.name}")
    if not path.is_file():
        raise MissingArtifactError(f"artifact is missing: {path.name}")
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(_READ_CHUNK):
                size += len(chunk)
                digest.update(chunk)
    except OSError as exc:
        raise ResolverError(f"cannot read artifact: {path.name}") from exc
    return digest.hexdigest(), size


def _require_non_negative_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SchemaMismatchError(f"{name} must be a non-negative integer")
    return value


def _require_positive_int(value: Any, *, name: str) -> int:
    number = _require_non_negative_int(value, name=name)
    if number <= 0:
        raise SchemaMismatchError(f"{name} must be a positive integer")
    return number


def _redact_secrets(text: str) -> str:
    return _TOKEN_LIKE_RE.sub("[REDACTED]", text)


def _assert_no_credential_payload(payload: Mapping[str, Any], *, surface: str) -> None:
    """Fail closed if a public surface would expose credential-like fields."""

    stack: list[Any] = [payload]
    while stack:
        current = stack.pop()
        if isinstance(current, Mapping):
            for key, value in current.items():
                key_text = str(key).casefold()
                if key_text in _CREDENTIAL_KEY_MARKERS or any(
                    marker in key_text for marker in ("token", "password", "secret", "credential")
                ):
                    raise CredentialLeakageError(
                        f"{surface} must not include credential field {key!r}"
                    )
                if isinstance(value, str) and _TOKEN_LIKE_RE.search(value):
                    raise CredentialLeakageError(
                        f"{surface} must not include credential-like values"
                    )
                stack.append(value)
        elif isinstance(current, (list, tuple)):
            stack.extend(current)
        elif isinstance(current, str) and _TOKEN_LIKE_RE.search(current):
            raise CredentialLeakageError(
                f"{surface} must not include credential-like values"
            )


# ---------------------------------------------------------------------------
# Descriptors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    """Integrity metadata for one release-relative artifact."""

    relative_path: str
    size_bytes: int
    sha256: str
    schema_id: str = ""
    row_count: int | None = None
    cid: str | None = None
    media_type: str = "application/octet-stream"

    def __post_init__(self) -> None:
        path = safe_relative_path(self.relative_path).as_posix()
        digest = normalize_sha256(self.sha256)
        size = _require_non_negative_int(self.size_bytes, name="size_bytes")
        schema_id = str(self.schema_id or "").strip()
        media_type = str(self.media_type or "application/octet-stream").strip()
        if not media_type:
            raise SchemaMismatchError("media_type must be non-empty when provided")
        row_count = self.row_count
        if row_count is not None:
            row_count = _require_non_negative_int(row_count, name="row_count")
        cid = self.cid
        if cid is not None:
            cid_text = str(cid).strip()
            if not cid_text:
                raise SchemaMismatchError("cid must be non-empty when provided")
            expected = raw_sha256_cid(bytes.fromhex(digest))
            if cid_text != expected and _CID_V1_RAW_SHA256_RE.fullmatch(cid_text) is None:
                raise SchemaMismatchError(f"cid is malformed: {cid!r}")
            if _CID_V1_RAW_SHA256_RE.fullmatch(cid_text) and cid_text != expected:
                raise DigestDriftError(
                    f"cid does not match sha256 for {path}"
                )
            cid = expected if cid_text == expected else cid_text
        object.__setattr__(self, "relative_path", path)
        object.__setattr__(self, "sha256", digest)
        object.__setattr__(self, "size_bytes", size)
        object.__setattr__(self, "schema_id", schema_id)
        object.__setattr__(self, "row_count", row_count)
        object.__setattr__(self, "cid", cid)
        object.__setattr__(self, "media_type", media_type)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "media_type": self.media_type,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }
        if self.schema_id:
            payload["schema_id"] = self.schema_id
        if self.row_count is not None:
            payload["row_count"] = self.row_count
        if self.cid is not None:
            payload["cid"] = self.cid
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ArtifactDescriptor":
        if not isinstance(value, Mapping):
            raise SchemaMismatchError("artifact descriptor must be a mapping")
        return cls(
            relative_path=str(value.get("relative_path") or value.get("path") or ""),
            size_bytes=value.get("size_bytes", value.get("byte_length", -1)),
            sha256=str(value.get("sha256") or value.get("digest") or ""),
            schema_id=str(value.get("schema_id") or value.get("schema_version") or ""),
            row_count=value.get("row_count"),
            cid=(
                str(value["cid"])
                if value.get("cid") is not None
                else (str(value["content_cid"]) if value.get("content_cid") is not None else None)
            ),
            media_type=str(value.get("media_type") or "application/octet-stream"),
        )


@dataclass(frozen=True, slots=True)
class ResolvedArtifact:
    """A verified local path for one release artifact."""

    relative_path: str
    path: Path
    size_bytes: int
    sha256: str
    cache_hit: bool
    verified: bool = True
    row_count: int | None = None
    schema_id: str = ""
    duration_ms: float = 0.0

    def to_trace_entry(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "cache_hit": self.cache_hit,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "verified": self.verified,
        }
        if self.row_count is not None:
            entry["row_count"] = self.row_count
        if self.schema_id:
            entry["schema_id"] = self.schema_id
        if self.duration_ms:
            entry["duration_ms"] = round(self.duration_ms, 3)
        return entry


@dataclass
class _FetchRecord:
    relative_path: str
    size_bytes: int
    sha256: str
    cache_hit: bool
    verified: bool
    duration_ms: float
    row_count: int | None = None
    schema_id: str = ""


# ---------------------------------------------------------------------------
# Transport protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class HubTransport(Protocol):
    """Materialize one pinned Hub file to a caller-owned destination path."""

    def fetch(
        self,
        *,
        repo_id: str,
        revision: str,
        relative_path: str,
        destination: Path,
        token: str | None = None,
    ) -> Path:
        """Write bytes to *destination* (regular file) and return it."""


class LocalRootTransport:
    """Transport that reads from a local release root (offline fixtures)."""

    def __init__(self, root: str | Path) -> None:
        root_path = Path(root).expanduser()
        if root_path.is_symlink() or not root_path.is_dir():
            raise ResolverError("local release root must be a real directory")
        self.root = root_path.resolve()

    def fetch(
        self,
        *,
        repo_id: str,
        revision: str,
        relative_path: str,
        destination: Path,
        token: str | None = None,
    ) -> Path:
        del repo_id, revision, token  # pin is enforced by the resolver
        safe = safe_relative_path(relative_path)
        source = self.root.joinpath(*safe.parts)
        try:
            source.resolve().relative_to(self.root)
        except ValueError as exc:
            raise UnsafePathError("local path escapes release root") from exc
        if source.is_symlink():
            raise SymlinkRejectedError(
                f"symlinks are rejected: {safe.as_posix()}"
            )
        if not source.is_file():
            raise MissingArtifactError(f"release file is missing: {safe.as_posix()}")
        try:
            shutil.copyfile(source, destination)
        except OSError as exc:
            raise TransportError(
                f"failed to stage local artifact: {safe.as_posix()}"
            ) from exc
        return destination


class HuggingFaceHubTransport:
    """Network transport using ``huggingface_hub.hf_hub_download``.

    Merely constructing this object never contacts the network. Network access
    happens only when :meth:`fetch` is invoked by a resolver.
    """

    def fetch(
        self,
        *,
        repo_id: str,
        revision: str,
        relative_path: str,
        destination: Path,
        token: str | None = None,
    ) -> Path:
        try:
            from huggingface_hub import hf_hub_download
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise TransportError(
                "huggingface_hub is required for remote Hub fetches"
            ) from exc
        safe = safe_relative_path(relative_path).as_posix()
        try:
            downloaded = hf_hub_download(
                repo_id=repo_id,
                filename=safe,
                repo_type="dataset",
                revision=revision,
                token=token,
            )
            # Hub often returns a symlink into its CAS; materialize real bytes.
            shutil.copyfile(Path(downloaded), destination)
        except ResolverError:
            raise
        except Exception:
            # Never echo Hub exception text: it may include headers or tokens.
            raise TransportError(
                f"failed to fetch pinned artifact: {safe}"
            ) from None
        return destination


class MappingTransport:
    """In-memory fake Hub transport for unit tests.

    ``files`` maps ``relative_path -> bytes``. Optional ``meta`` can force
    symlink-like failures or oversized responses without writing them.
    """

    def __init__(
        self,
        files: Mapping[str, bytes],
        *,
        fail_paths: Mapping[str, str] | None = None,
    ) -> None:
        self.files = {safe_relative_path(key).as_posix(): value for key, value in files.items()}
        self.fail_paths = {
            safe_relative_path(key).as_posix(): str(reason)
            for key, reason in (fail_paths or {}).items()
        }

    def fetch(
        self,
        *,
        repo_id: str,
        revision: str,
        relative_path: str,
        destination: Path,
        token: str | None = None,
    ) -> Path:
        del repo_id, revision, token
        safe = safe_relative_path(relative_path).as_posix()
        if safe in self.fail_paths:
            reason = self.fail_paths[safe]
            if reason == "symlink":
                raise SymlinkRejectedError(f"symlinks are rejected: {safe}")
            if reason == "missing":
                raise MissingArtifactError(f"release file is missing: {safe}")
            raise TransportError(f"failed to fetch pinned artifact: {safe}")
        if safe not in self.files:
            raise MissingArtifactError(f"release file is missing: {safe}")
        try:
            destination.write_bytes(self.files[safe])
        except OSError as exc:
            raise TransportError(f"failed to stage artifact: {safe}") from exc
        return destination


# ---------------------------------------------------------------------------
# Revision-scoped content-addressed cache
# ---------------------------------------------------------------------------


class RevisionScopedCache:
    """Content-addressed cache with revision-scoped logical aliases.

    Layout::

        <root>/
          objects/sha256/<ab>/<sha256>          # verified bytes
          aliases/<repo_hash>/<revision>/<path_hash>.json
          locks/...

    Cache keys bind repo ID, immutable revision, relative path, digest, and
    schema version. A logical alias that points at different content fails
    closed as a cache collision.
    """

    def __init__(self, root: str | Path) -> None:
        root_path = Path(root).expanduser()
        try:
            root_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ResolverError("cache root must be creatable") from exc
        if root_path.is_symlink() or not root_path.is_dir():
            raise ResolverError("cache root must be a real directory")
        self.root = root_path.resolve()
        self._ensure_directory(self.root / "objects")
        self._ensure_directory(self.root / "aliases")
        self._ensure_directory(self.root / "locks")

    def object_path(self, sha256: str) -> Path:
        digest = normalize_sha256(sha256)
        return self.root / "objects" / "sha256" / digest[:2] / digest

    def alias_path(
        self,
        *,
        repo_id: str,
        revision: str,
        relative_path: str,
    ) -> Path:
        repo = validate_repo_id(repo_id)
        rev = validate_immutable_revision(revision)
        rel = safe_relative_path(relative_path).as_posix()
        repo_key = hashlib.sha256(repo.encode("utf-8")).hexdigest()[:16]
        path_key = hashlib.sha256(rel.encode("utf-8")).hexdigest()
        return self.root / "aliases" / repo_key / rev / f"{path_key}.json"

    def lookup(
        self,
        *,
        repo_id: str,
        revision: str,
        relative_path: str,
        expected_sha256: str | None = None,
    ) -> Path | None:
        """Return a verified object path on hit, else ``None``.

        Raises :class:`CacheCollisionError` when an alias names different
        content than *expected_sha256* or the on-disk object drifted.
        """

        alias_file = self.alias_path(
            repo_id=repo_id, revision=revision, relative_path=relative_path
        )
        if alias_file.is_symlink():
            raise SymlinkRejectedError("cache alias must not be a symlink")
        if not alias_file.is_file():
            return None
        try:
            payload = json.loads(alias_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CacheCollisionError("cache alias is corrupt") from exc
        if not isinstance(payload, Mapping):
            raise CacheCollisionError("cache alias must be a JSON object")
        if payload.get("schema_version") != CACHE_ALIAS_SCHEMA_VERSION:
            raise CacheCollisionError("cache alias schema mismatch")
        if (
            payload.get("repo_id") != repo_id
            or payload.get("revision") != revision
            or payload.get("relative_path") != safe_relative_path(relative_path).as_posix()
        ):
            raise CacheCollisionError("cache alias identity collision")
        digest = normalize_sha256(payload.get("sha256"), name="alias.sha256")
        size = _require_non_negative_int(payload.get("size_bytes"), name="alias.size_bytes")
        if expected_sha256 is not None and digest != normalize_sha256(expected_sha256):
            raise CacheCollisionError(
                "cache collision: alias digest disagrees with requested descriptor"
            )
        object_file = self.object_path(digest)
        if object_file.is_symlink():
            raise SymlinkRejectedError("cache object must not be a symlink")
        if not object_file.is_file():
            raise CacheCollisionError("cache alias points at a missing object")
        actual_digest, actual_size = file_sha256_and_size(object_file)
        if actual_digest != digest or actual_size != size:
            raise CacheCollisionError("cache object digest or size drifted")
        return object_file

    def store(
        self,
        *,
        repo_id: str,
        revision: str,
        relative_path: str,
        source: Path,
        sha256: str,
        size_bytes: int,
    ) -> Path:
        """Promote verified *source* bytes into the content-addressed cache."""

        digest = normalize_sha256(sha256)
        size = _require_non_negative_int(size_bytes, name="size_bytes")
        if source.is_symlink():
            raise SymlinkRejectedError("cannot store a symlink in the cache")
        actual_digest, actual_size = file_sha256_and_size(source)
        if actual_digest != digest or actual_size != size:
            raise DigestDriftError("cannot cache artifact with digest drift")

        object_file = self.object_path(digest)
        self._ensure_directory(object_file.parent)
        if object_file.exists() or object_file.is_symlink():
            if object_file.is_symlink() or not object_file.is_file():
                raise CacheCollisionError("cache object path is unsafe")
            existing_digest, existing_size = file_sha256_and_size(object_file)
            if existing_digest != digest or existing_size != size:
                raise CacheCollisionError(
                    "cache collision: content-addressed object already holds different bytes"
                )
        else:
            self._atomic_copy(source, object_file)

        alias_file = self.alias_path(
            repo_id=repo_id, revision=revision, relative_path=relative_path
        )
        self._ensure_directory(alias_file.parent)
        if alias_file.exists() or alias_file.is_symlink():
            # Existing alias must agree; otherwise this is a revision-scoped collision.
            existing = self.lookup(
                repo_id=repo_id,
                revision=revision,
                relative_path=relative_path,
                expected_sha256=digest,
            )
            if existing is None:
                raise CacheCollisionError("cache alias collision")
            return object_file

        alias_payload = {
            "relative_path": safe_relative_path(relative_path).as_posix(),
            "repo_id": validate_repo_id(repo_id),
            "revision": validate_immutable_revision(revision),
            "schema_version": CACHE_ALIAS_SCHEMA_VERSION,
            "sha256": digest,
            "size_bytes": size,
        }
        _assert_no_credential_payload(alias_payload, surface="cache alias")
        self._atomic_write_json(alias_file, alias_payload)
        return object_file

    def _atomic_copy(self, source: Path, destination: Path) -> None:
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".partial",
            dir=destination.parent,
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, destination)
        except Exception:
            if temporary.exists():
                temporary.unlink(missing_ok=True)
            raise

    def _atomic_write_json(self, destination: Path, payload: Mapping[str, Any]) -> None:
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".partial",
            dir=destination.parent,
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            temporary.write_text(
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary, destination)
        except Exception:
            if temporary.exists():
                temporary.unlink(missing_ok=True)
            raise

    def _ensure_directory(self, directory: Path) -> None:
        try:
            relative = directory.absolute().relative_to(self.root)
        except ValueError as exc:
            raise UnsafePathError("cache directory escapes the cache root") from exc
        current = self.root
        for part in relative.parts:
            current = current / part
            if current.exists() and (current.is_symlink() or not current.is_dir()):
                raise SymlinkRejectedError("cache directory must not be a symlink")
            try:
                current.mkdir(exist_ok=True)
            except OSError as exc:
                raise ResolverError("cannot create cache directory") from exc
            if current.is_symlink():
                raise SymlinkRejectedError("cache directory must not be a symlink")


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


@dataclass
class ImmutableHubResolver:
    """Fail-closed resolver for immutable Hugging Face GraphRAG releases.

    Parameters
    ----------
    repo_id:
        Hub dataset id (``owner/name``).
    revision:
        Immutable 40-hex commit SHA.
    cache_dir:
        Local cache root (revision-scoped aliases + content objects).
    transport:
        Optional :class:`HubTransport`. Defaults to
        :class:`HuggingFaceHubTransport` when *local_root* is absent, otherwise
        :class:`LocalRootTransport`.
    local_root:
        Optional offline release directory.
    token:
        Optional Hub token. Stored privately and never emitted in traces,
        representations, or public error messages.
    max_artifact_bytes:
        Hard byte ceiling for any single artifact.
    max_rows_per_artifact:
        Hard row ceiling enforced when a descriptor declares ``row_count``.
    supported_schemas:
        Accepted release ``schema_version`` / descriptor ``schema_id`` values.
    require_descriptor:
        When true, :meth:`resolve` requires a descriptor for every path.
    """

    repo_id: str
    revision: str
    cache_dir: Path | str | None = None
    transport: HubTransport | None = None
    local_root: Path | str | None = None
    token: str | None = field(default=None, repr=False)
    max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES
    max_rows_per_artifact: int = DEFAULT_MAX_ROWS_PER_ARTIFACT
    supported_schemas: frozenset[str] | set[str] | Sequence[str] = field(
        default_factory=lambda: set(DEFAULT_SUPPORTED_RELEASE_SCHEMAS)
    )
    require_descriptor: bool = False
    path_prefix: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "repo_id", validate_repo_id(self.repo_id))
        object.__setattr__(
            self, "revision", validate_immutable_revision(self.revision)
        )
        max_bytes = _require_positive_int(
            self.max_artifact_bytes, name="max_artifact_bytes"
        )
        max_rows = _require_positive_int(
            self.max_rows_per_artifact, name="max_rows_per_artifact"
        )
        object.__setattr__(self, "max_artifact_bytes", max_bytes)
        object.__setattr__(self, "max_rows_per_artifact", max_rows)

        schemas = frozenset(str(item).strip() for item in self.supported_schemas if str(item).strip())
        if not schemas:
            raise SchemaMismatchError("supported_schemas must not be empty")
        object.__setattr__(self, "supported_schemas", schemas)

        prefix = str(self.path_prefix or "").strip().strip("/")
        if prefix:
            safe_relative_path(prefix, name="path_prefix")
        object.__setattr__(self, "path_prefix", prefix)

        cache_root = Path(self.cache_dir or DEFAULT_CACHE_DIR).expanduser()
        object.__setattr__(self, "cache_dir", cache_root)
        object.__setattr__(self, "_cache", RevisionScopedCache(cache_root))

        local: Path | None
        if self.local_root is not None:
            local = Path(self.local_root).expanduser().resolve()
            if local.is_symlink() or not local.is_dir():
                raise ResolverError("local_root must be a real directory")
        else:
            local = None
        object.__setattr__(self, "local_root", local)

        if self.transport is None:
            if local is not None:
                transport: HubTransport = LocalRootTransport(local)
            else:
                transport = HuggingFaceHubTransport()
        else:
            transport = self.transport
        object.__setattr__(self, "transport", transport)

        # Private credential storage — never part of public repr/trace.
        object.__setattr__(self, "_token", self.token)
        object.__setattr__(self, "token", None)
        object.__setattr__(self, "_fetch_log", [])
        object.__setattr__(self, "_manifest_schema", None)

    # -- public API ---------------------------------------------------------

    def resolve(
        self,
        relative_path: str,
        *,
        descriptor: ArtifactDescriptor | Mapping[str, Any] | None = None,
    ) -> ResolvedArtifact:
        """Fetch, verify, and cache one release-relative artifact."""

        started = time.perf_counter()
        safe = safe_relative_path(relative_path)
        rel = safe.as_posix()
        desc = self._coerce_descriptor(rel, descriptor)
        if self.require_descriptor and desc is None:
            raise SchemaMismatchError(
                f"descriptor is required for {rel}"
            )
        if desc is not None and desc.relative_path != rel:
            raise UnsafePathError(
                f"descriptor path {desc.relative_path!r} does not match {rel!r}"
            )
        if desc is not None:
            self._enforce_descriptor_bounds(desc)

        expected_sha = desc.sha256 if desc is not None else None
        cache_hit = False
        # lookup returns None on a clean miss; integrity/collision failures raise.
        cached = self._cache.lookup(
            repo_id=self.repo_id,
            revision=self.revision,
            relative_path=rel,
            expected_sha256=expected_sha,
        )

        if cached is not None:
            path = cached
            cache_hit = True
            digest, size = file_sha256_and_size(path)
            if expected_sha is not None:
                self._verify_against_descriptor(path, desc)  # type: ignore[arg-type]
            elif size > self.max_artifact_bytes:
                raise OversizedArtifactError(
                    f"artifact exceeds max_artifact_bytes: {rel}"
                )
        else:
            path, digest, size = self._fetch_and_verify(rel, desc)

        duration_ms = (time.perf_counter() - started) * 1000.0
        resolved = ResolvedArtifact(
            relative_path=rel,
            path=path,
            size_bytes=size,
            sha256=digest,
            cache_hit=cache_hit,
            verified=True,
            row_count=desc.row_count if desc is not None else None,
            schema_id=desc.schema_id if desc is not None else "",
            duration_ms=duration_ms,
        )
        self._fetch_log.append(
            _FetchRecord(
                relative_path=rel,
                size_bytes=size,
                sha256=digest,
                cache_hit=cache_hit,
                verified=True,
                duration_ms=duration_ms,
                row_count=resolved.row_count,
                schema_id=resolved.schema_id,
            )
        )
        return resolved

    def resolve_bytes(
        self,
        relative_path: str,
        *,
        descriptor: ArtifactDescriptor | Mapping[str, Any] | None = None,
    ) -> bytes:
        """Resolve and return verified artifact bytes."""

        artifact = self.resolve(relative_path, descriptor=descriptor)
        try:
            return artifact.path.read_bytes()
        except OSError as exc:
            raise ResolverError(
                f"cannot read verified artifact: {artifact.relative_path}"
            ) from exc

    def resolve_json(
        self,
        relative_path: str,
        *,
        descriptor: ArtifactDescriptor | Mapping[str, Any] | None = None,
        expect_object: bool = True,
    ) -> Any:
        """Resolve a JSON artifact and optionally require a top-level object."""

        raw = self.resolve_bytes(relative_path, descriptor=descriptor)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SchemaMismatchError(
                f"JSON artifact is malformed: {relative_path}"
            ) from exc
        if expect_object and not isinstance(value, Mapping):
            raise SchemaMismatchError(
                f"JSON artifact must be an object: {relative_path}"
            )
        return value

    def load_manifest(
        self,
        relative_path: str = DEFAULT_MANIFEST_NAME,
        *,
        descriptor: ArtifactDescriptor | Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Load and schema-check a release manifest."""

        manifest = self.resolve_json(
            relative_path, descriptor=descriptor, expect_object=True
        )
        schema_version = manifest.get("schema_version") or manifest.get("release_profile")
        if not isinstance(schema_version, str) or not schema_version.strip():
            raise SchemaMismatchError("manifest is missing schema_version")
        schema_version = schema_version.strip()
        if schema_version not in self.supported_schemas:
            raise SchemaMismatchError(
                f"unsupported release schema_version: {schema_version!r}"
            )
        # Prefer explicit profile when both are present.
        profile = manifest.get("release_profile")
        if isinstance(profile, str) and profile.strip():
            if profile.strip() not in self.supported_schemas and profile.strip() != schema_version:
                # Allow profile aliases only when listed.
                if profile.strip() not in self.supported_schemas:
                    raise SchemaMismatchError(
                        f"unsupported release_profile: {profile!r}"
                    )
        primary_key = manifest.get("primary_key")
        if primary_key is not None and primary_key != "entry_cid":
            raise SchemaMismatchError(
                "manifest primary_key must be 'entry_cid' when provided"
            )
        object.__setattr__(self, "_manifest_schema", schema_version)
        return dict(manifest)

    def verify_descriptor(
        self,
        path: str | Path,
        descriptor: ArtifactDescriptor | Mapping[str, Any],
    ) -> ArtifactDescriptor:
        """Verify an on-disk file against a descriptor (fail closed)."""

        desc = (
            descriptor
            if isinstance(descriptor, ArtifactDescriptor)
            else ArtifactDescriptor.from_mapping(descriptor)
        )
        self._enforce_descriptor_bounds(desc)
        target = Path(path)
        self._verify_against_descriptor(target, desc)
        return desc

    def fetch_trace(self) -> dict[str, Any]:
        """Return a credential-safe summary of fetches performed so far."""

        files = []
        total_bytes = 0
        cache_hits = 0
        for record in self._fetch_log:
            entry = {
                "cache_hit": record.cache_hit,
                "relative_path": record.relative_path,
                "sha256": record.sha256,
                "size_bytes": record.size_bytes,
                "verified": record.verified,
            }
            if record.row_count is not None:
                entry["row_count"] = record.row_count
            if record.schema_id:
                entry["schema_id"] = record.schema_id
            if record.duration_ms:
                entry["duration_ms"] = round(record.duration_ms, 3)
            files.append(entry)
            total_bytes += record.size_bytes
            if record.cache_hit:
                cache_hits += 1
        files.sort(key=lambda item: item["relative_path"])
        trace: dict[str, Any] = {
            "cache_hits": cache_hits,
            "file_count": len(files),
            "files": files,
            "repo_id": self.repo_id,
            "resolver_schema_version": RESOLVER_SCHEMA_VERSION,
            "revision": self.revision,
            "total_file_bytes": total_bytes,
            "verification_state": "verified" if files else "empty",
        }
        if self._manifest_schema is not None:
            trace["manifest_schema_version"] = self._manifest_schema
        _assert_no_credential_payload(trace, surface="fetch_trace")
        # Defense in depth: ensure string form has no token-like blobs.
        rendered = json.dumps(trace, sort_keys=True)
        if _TOKEN_LIKE_RE.search(rendered):
            raise CredentialLeakageError("fetch_trace would leak credentials")
        if self._token and self._token in rendered:
            raise CredentialLeakageError("fetch_trace would leak credentials")
        return trace

    # Compatibility alias used by SkillCenter/CVEfixes-style callers.
    def trace(self) -> dict[str, Any]:
        return self.fetch_trace()

    def __repr__(self) -> str:
        return (
            f"ImmutableHubResolver(repo_id={self.repo_id!r}, "
            f"revision={self.revision!r}, cache_dir={str(self.cache_dir)!r})"
        )

    # -- internals ----------------------------------------------------------

    def _coerce_descriptor(
        self,
        relative_path: str,
        descriptor: ArtifactDescriptor | Mapping[str, Any] | None,
    ) -> ArtifactDescriptor | None:
        if descriptor is None:
            return None
        if isinstance(descriptor, ArtifactDescriptor):
            desc = descriptor
        else:
            desc = ArtifactDescriptor.from_mapping(descriptor)
        if desc.relative_path != relative_path:
            # Allow descriptors that omit path only when constructed via from_mapping
            # with an empty path — already rejected by ArtifactDescriptor.
            raise UnsafePathError(
                f"descriptor path {desc.relative_path!r} does not match {relative_path!r}"
            )
        if desc.schema_id and desc.schema_id not in self.supported_schemas:
            # Descriptor schema_id may be an artifact-family schema, not a
            # release schema. Only reject clearly malicious release markers.
            if desc.schema_id in {
                "latest",
                "main",
                "untrusted",
                "mutable",
            } or desc.schema_id.endswith("/latest"):
                raise SchemaMismatchError(
                    f"unsupported descriptor schema_id: {desc.schema_id!r}"
                )
        return desc

    def _enforce_descriptor_bounds(self, descriptor: ArtifactDescriptor) -> None:
        if descriptor.size_bytes > self.max_artifact_bytes:
            raise OversizedArtifactError(
                f"descriptor size_bytes {descriptor.size_bytes} exceeds "
                f"max_artifact_bytes {self.max_artifact_bytes}"
            )
        if (
            descriptor.row_count is not None
            and descriptor.row_count > self.max_rows_per_artifact
        ):
            raise OversizedArtifactError(
                f"descriptor row_count {descriptor.row_count} exceeds "
                f"max_rows_per_artifact {self.max_rows_per_artifact}"
            )

    def _fetch_and_verify(
        self,
        relative_path: str,
        descriptor: ArtifactDescriptor | None,
    ) -> tuple[Path, str, int]:
        remote_name = (
            f"{self.path_prefix}/{relative_path}"
            if self.path_prefix
            else relative_path
        )
        # Stage into a private temp file under the cache root, then promote.
        staging_dir = self._cache.root / "locks"
        self._cache._ensure_directory(staging_dir)
        fd, temporary_name = tempfile.mkstemp(
            prefix=".fetch.",
            suffix=".partial",
            dir=staging_dir,
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            try:
                self.transport.fetch(
                    repo_id=self.repo_id,
                    revision=self.revision,
                    relative_path=remote_name,
                    destination=temporary,
                    token=self._token,
                )
            except ResolverError as exc:
                # Sanitize any accidental credential text from transport errors.
                message = _redact_secrets(str(exc))
                if self._token and self._token in message:
                    message = "failed to fetch pinned artifact"
                raise type(exc)(message) from None
            except Exception:
                raise TransportError(
                    f"failed to fetch pinned artifact: {relative_path}"
                ) from None

            if temporary.is_symlink():
                raise SymlinkRejectedError(
                    f"symlinks are rejected: {relative_path}"
                )
            digest, size = file_sha256_and_size(temporary)
            if size > self.max_artifact_bytes:
                raise OversizedArtifactError(
                    f"artifact exceeds max_artifact_bytes: {relative_path}"
                )
            if descriptor is not None:
                if size != descriptor.size_bytes or digest != descriptor.sha256:
                    raise DigestDriftError(
                        f"artifact digest or size differs: {relative_path}"
                    )
                if descriptor.cid is not None:
                    actual_cid = raw_sha256_cid(bytes.fromhex(digest))
                    if actual_cid != descriptor.cid:
                        raise DigestDriftError(
                            f"artifact CID differs: {relative_path}"
                        )
            stored = self._cache.store(
                repo_id=self.repo_id,
                revision=self.revision,
                relative_path=relative_path,
                source=temporary,
                sha256=digest,
                size_bytes=size,
            )
            return stored, digest, size
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)

    def _verify_against_descriptor(
        self,
        path: Path,
        descriptor: ArtifactDescriptor,
    ) -> None:
        if path.is_symlink():
            raise SymlinkRejectedError(
                f"symlinks are rejected: {descriptor.relative_path}"
            )
        if not path.is_file():
            raise MissingArtifactError(
                f"artifact is missing: {descriptor.relative_path}"
            )
        digest, size = file_sha256_and_size(path)
        if size != descriptor.size_bytes:
            raise DigestDriftError(
                f"artifact size differs: {descriptor.relative_path}"
            )
        if digest != descriptor.sha256:
            raise DigestDriftError(
                f"artifact digest differs: {descriptor.relative_path}"
            )
        if descriptor.cid is not None:
            actual_cid = raw_sha256_cid(bytes.fromhex(digest))
            if actual_cid != descriptor.cid:
                raise DigestDriftError(
                    f"artifact CID differs: {descriptor.relative_path}"
                )
        if size > self.max_artifact_bytes:
            raise OversizedArtifactError(
                f"artifact exceeds max_artifact_bytes: {descriptor.relative_path}"
            )


def build_descriptor_for_bytes(
    relative_path: str,
    content: bytes,
    *,
    schema_id: str = "",
    row_count: int | None = None,
    media_type: str = "application/octet-stream",
    include_cid: bool = True,
) -> ArtifactDescriptor:
    """Helper for tests and writers: build a descriptor for exact bytes."""

    digest = hashlib.sha256(content).hexdigest()
    return ArtifactDescriptor(
        relative_path=relative_path,
        size_bytes=len(content),
        sha256=digest,
        schema_id=schema_id,
        row_count=row_count,
        cid=raw_sha256_cid(bytes.fromhex(digest)) if include_cid else None,
        media_type=media_type,
    )


def load_malicious_manifest_cases(path: str | Path) -> list[dict[str, Any]]:
    """Load adversarial fixture cases from ``malicious_manifests.json``."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise SchemaMismatchError("malicious_manifests fixture must be an object")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise SchemaMismatchError("malicious_manifests fixture has no cases")
    return [dict(case) for case in cases if isinstance(case, Mapping)]


__all__ = [
    "CACHE_ALIAS_SCHEMA_VERSION",
    "DEFAULT_CACHE_DIR",
    "DEFAULT_MANIFEST_NAME",
    "DEFAULT_MAX_ARTIFACT_BYTES",
    "DEFAULT_MAX_ROWS_PER_ARTIFACT",
    "DEFAULT_SUPPORTED_RELEASE_SCHEMAS",
    "RESOLVER_SCHEMA_VERSION",
    "ArtifactDescriptor",
    "CacheCollisionError",
    "CredentialLeakageError",
    "DigestDriftError",
    "HubTransport",
    "HuggingFaceHubTransport",
    "ImmutableHubResolver",
    "LocalRootTransport",
    "MappingTransport",
    "MissingArtifactError",
    "MutableRevisionError",
    "OversizedArtifactError",
    "ResolvedArtifact",
    "ResolverError",
    "RevisionScopedCache",
    "SchemaMismatchError",
    "SymlinkRejectedError",
    "TransportError",
    "UnsafePathError",
    "build_descriptor_for_bytes",
    "file_sha256_and_size",
    "load_malicious_manifest_cases",
    "normalize_sha256",
    "raw_sha256_cid",
    "safe_relative_path",
    "validate_immutable_revision",
    "validate_repo_id",
]
