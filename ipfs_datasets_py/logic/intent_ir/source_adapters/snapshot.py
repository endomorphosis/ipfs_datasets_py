"""Pinned SkillCenter snapshot manifests and a verified offline cache.

The cache separates a logical source alias (dataset, immutable revision, and
repository file) from its content-addressed local artifact.  Both aliases and
artifact bytes are validated on every cache hit.  Fetchers are explicitly
injected, write only to a temporary path, and cannot promote bytes until the
declared size and SHA-256 digest have been verified.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any, Iterator, Protocol, runtime_checkable

from ...ir_core.artifacts import Artifact, ArtifactRole
from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import cid_v1_from_digest
from .skillcenter import DEFAULT_SKILLCENTER_DATASET_ID, SkillCenterBundleReader


SKILLCENTER_SNAPSHOT_SCHEMA_VERSION = "skillcenter-snapshot/v1"
SKILLCENTER_CACHE_ALIAS_SCHEMA_VERSION = "skillcenter-cache-alias/v1"

# This is the immutable Hub revision inspected while preparing the bounded
# SkillCenter pilot.  Network access is deliberately not needed to use it or
# to test the snapshot/cache contract.
INSPECTED_SKILLCENTER_PILOT_REVISION = (
    "f9dd4fec3c86d85ebf116c7408ac5ce602c418a1"
)
DEFAULT_SKILLCENTER_DOWNLOAD_PRODUCER = "producer:huggingface-hub-download"

_MUTABLE_REVISION_NAMES = frozenset(
    {
        "head",
        "latest",
        "main",
        "master",
        "refs/heads/main",
        "refs/heads/master",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PARTIAL_SUFFIXES = (".part", ".partial", ".tmp")
_MAX_ALIAS_BYTES = 1024 * 1024


class SkillCenterSnapshotError(ValueError):
    """Base class for invalid snapshots and cache failures."""


class SkillCenterSnapshotValidationError(SkillCenterSnapshotError):
    """Raised when a snapshot manifest is not safe or fully pinned."""


class SkillCenterSnapshotIntegrityError(SkillCenterSnapshotError):
    """Raised when local bytes disagree with their snapshot manifest."""


class SkillCenterSnapshotCacheMiss(SkillCenterSnapshotError):
    """Raised when an offline cache has no complete matching artifact."""


class SkillCenterStaleCacheAliasError(SkillCenterSnapshotIntegrityError):
    """Raised when a logical cache alias names another or missing snapshot."""


class SkillCenterSnapshotFetchError(SkillCenterSnapshotError):
    """Raised when an injected fetcher cannot produce a complete artifact."""


@runtime_checkable
class SkillCenterSnapshotFetcher(Protocol):
    """Materialize one snapshot at the supplied temporary destination.

    Implementations may write ``destination`` and return ``None``, return
    bytes, or return a path to existing local bytes.  The cache owns final-path
    promotion and performs all integrity checks.
    """

    def __call__(
        self,
        snapshot: "SkillCenterSnapshot",
        destination: Path,
    ) -> None | str | os.PathLike[str] | bytes | bytearray | memoryview:
        ...


def _relative_posix_path(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SkillCenterSnapshotValidationError(f"{label} must not be empty")
    if value.strip() != value or "\\" in value or "\x00" in value:
        raise SkillCenterSnapshotValidationError(
            f"{label} must be a normalized root-relative POSIX path"
        )
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise SkillCenterSnapshotValidationError(
            f"{label} must be root-relative and contain no '.'/'..' segments"
        )
    normalized = path.as_posix()
    if normalized != value:
        raise SkillCenterSnapshotValidationError(
            f"{label} must be normalized POSIX text"
        )
    return normalized


def _require_text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise SkillCenterSnapshotValidationError(
            f"{label} must be non-empty and have no surrounding whitespace"
        )
    if "\x00" in value:
        raise SkillCenterSnapshotValidationError(f"{label} must not contain NUL")
    return value


@dataclass(frozen=True, slots=True)
class SkillCenterSnapshot:
    """Immutable expected identity for one SkillCenter repository artifact."""

    dataset_revision: str
    repository_file: str
    expected_sha256: str
    expected_size_bytes: int
    dataset_id: str = DEFAULT_SKILLCENTER_DATASET_ID
    content_cid: str = ""
    cache_path: str = ""
    download_producer: str = DEFAULT_SKILLCENTER_DOWNLOAD_PRODUCER
    schema_version: str = SKILLCENTER_SNAPSHOT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        dataset_id = _require_text(self.dataset_id, label="dataset_id")
        revision = _require_text(self.dataset_revision, label="dataset_revision")
        repository_file = _relative_posix_path(
            self.repository_file, label="repository_file"
        )
        folded_revision = revision.casefold()
        if (
            folded_revision in _MUTABLE_REVISION_NAMES
            or folded_revision.startswith("refs/heads/")
        ):
            raise SkillCenterSnapshotValidationError(
                "dataset_revision must be an immutable revision, not a mutable ref"
            )
        if "\\" in dataset_id:
            raise SkillCenterSnapshotValidationError(
                "dataset_id must use normalized POSIX separators"
            )
        dataset_path = PurePosixPath(dataset_id)
        if dataset_path.is_absolute() or any(
            part in {"", ".", ".."} for part in dataset_path.parts
        ) or dataset_path.as_posix() != dataset_id:
            raise SkillCenterSnapshotValidationError(
                "dataset_id must be normalized and contain no path traversal"
            )
        if not isinstance(self.expected_sha256, str) or not _SHA256_RE.fullmatch(
            self.expected_sha256
        ):
            raise SkillCenterSnapshotValidationError(
                "expected_sha256 must be 64 lowercase hexadecimal characters"
            )
        if (
            isinstance(self.expected_size_bytes, bool)
            or not isinstance(self.expected_size_bytes, int)
            or self.expected_size_bytes < 1
        ):
            raise SkillCenterSnapshotValidationError(
                "expected_size_bytes must be a positive integer"
            )
        producer = _require_text(
            self.download_producer, label="download_producer"
        )
        if self.schema_version != SKILLCENTER_SNAPSHOT_SCHEMA_VERSION:
            raise SkillCenterSnapshotValidationError(
                "unsupported SkillCenter snapshot schema_version"
            )

        cache_path = self.cache_path or (
            f"objects/sha256/{self.expected_sha256[:2]}/"
            f"{self.expected_sha256}"
        )
        cache_path = _relative_posix_path(cache_path, label="cache_path")
        if cache_path.casefold().endswith(_PARTIAL_SUFFIXES):
            raise SkillCenterSnapshotValidationError(
                "cache_path must identify a complete artifact, not a partial file"
            )
        if PurePosixPath(cache_path).parts[0].casefold() in {"aliases", "locks"}:
            raise SkillCenterSnapshotValidationError(
                "cache_path must not use a reserved cache metadata directory"
            )
        expected_content_cid = cid_v1_from_digest(
            bytes.fromhex(self.expected_sha256)
        )
        content_cid = self.content_cid or expected_content_cid
        _require_text(content_cid, label="content_cid")
        if content_cid != expected_content_cid:
            raise SkillCenterSnapshotValidationError(
                "content_cid must be the fixed-profile CID for expected_sha256"
            )

        object.__setattr__(self, "dataset_id", dataset_id)
        object.__setattr__(self, "dataset_revision", revision)
        object.__setattr__(self, "repository_file", repository_file)
        object.__setattr__(self, "cache_path", cache_path)
        object.__setattr__(self, "content_cid", content_cid)
        object.__setattr__(self, "download_producer", producer)

    @property
    def sha256(self) -> str:
        """Compatibility spelling for the expected SHA-256 value."""

        return self.expected_sha256

    @property
    def size_bytes(self) -> int:
        """Compatibility spelling for the expected byte length."""

        return self.expected_size_bytes

    @property
    def revision(self) -> str:
        """Compatibility spelling for the pinned dataset revision."""

        return self.dataset_revision

    @property
    def logical_source(self) -> str:
        return (
            f"hf://datasets/{self.dataset_id}@{self.dataset_revision}/"
            f"{self.repository_file}"
        )

    @property
    def snapshot_id(self) -> str:
        digest = hashlib.sha256(self.canonical_bytes()).hexdigest()
        return f"skillcenter-snapshot:sha256:{digest}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache_path": self.cache_path,
            "content_cid": self.content_cid,
            "dataset_id": self.dataset_id,
            "dataset_revision": self.dataset_revision,
            "download_producer": self.download_producer,
            "expected_sha256": self.expected_sha256,
            "expected_size_bytes": self.expected_size_bytes,
            "repository_file": self.repository_file,
            "schema_version": self.schema_version,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SkillCenterSnapshot":
        if not isinstance(value, Mapping):
            raise SkillCenterSnapshotValidationError(
                "snapshot manifest must be a mapping"
            )
        allowed = {
            "cache_path",
            "content_cid",
            "dataset_id",
            "dataset_revision",
            "download_producer",
            "expected_sha256",
            "expected_size_bytes",
            "repository_file",
            "schema_version",
        }
        if any(not isinstance(key, str) for key in value):
            raise SkillCenterSnapshotValidationError(
                "snapshot manifest field names must be strings"
            )
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise SkillCenterSnapshotValidationError(
                f"snapshot manifest contains unknown field(s): {', '.join(unknown)}"
            )
        for field in allowed - {"expected_size_bytes"}:
            if field in value and not isinstance(value[field], str):
                raise SkillCenterSnapshotValidationError(
                    f"{field} must be a string"
                )
        try:
            expected_size = value["expected_size_bytes"]
        except KeyError as exc:
            raise SkillCenterSnapshotValidationError(
                "snapshot manifest is missing expected_size_bytes"
            ) from exc
        if isinstance(expected_size, bool) or not isinstance(expected_size, int):
            raise SkillCenterSnapshotValidationError(
                "expected_size_bytes must be an integer"
            )
        try:
            return cls(
                dataset_id=str(
                    value.get("dataset_id") or DEFAULT_SKILLCENTER_DATASET_ID
                ),
                dataset_revision=str(value.get("dataset_revision") or ""),
                repository_file=str(value.get("repository_file") or ""),
                expected_sha256=str(value.get("expected_sha256") or ""),
                expected_size_bytes=expected_size,
                content_cid=str(value.get("content_cid") or ""),
                cache_path=str(value.get("cache_path") or ""),
                download_producer=str(
                    value.get("download_producer")
                    or DEFAULT_SKILLCENTER_DOWNLOAD_PRODUCER
                ),
                schema_version=str(
                    value.get("schema_version")
                    or SKILLCENTER_SNAPSHOT_SCHEMA_VERSION
                ),
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, SkillCenterSnapshotValidationError):
                raise
            raise SkillCenterSnapshotValidationError(str(exc)) from exc

    @classmethod
    def from_json(
        cls, value: str | bytes | bytearray
    ) -> "SkillCenterSnapshot":
        if isinstance(value, (bytes, bytearray)):
            try:
                value = bytes(value).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise SkillCenterSnapshotValidationError(
                    "snapshot JSON must be UTF-8"
                ) from exc
        if not isinstance(value, str):
            raise TypeError("snapshot JSON must be str or bytes")
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise SkillCenterSnapshotValidationError(
                f"invalid snapshot JSON: {exc}"
            ) from exc
        if not isinstance(decoded, Mapping):
            raise SkillCenterSnapshotValidationError(
                "snapshot JSON must contain an object"
            )
        return cls.from_dict(decoded)

    def to_artifact(self, *, artifact_id: str | None = None) -> Artifact:
        """Project this snapshot into the shared immutable artifact contract."""

        return Artifact(
            artifact_id=artifact_id
            or f"artifact:skillcenter:{self.expected_sha256}",
            role=ArtifactRole.INPUT,
            content_sha256=self.expected_sha256,
            size=self.expected_size_bytes,
            path=self.cache_path,
            content_cid=self.content_cid,
            producer_id=self.download_producer,
            metadata={
                "dataset_id": self.dataset_id,
                "dataset_revision": self.dataset_revision,
                "repository_file": self.repository_file,
                "snapshot_id": self.snapshot_id,
            },
        )


class HuggingFaceSkillCenterFetcher:
    """Explicit fetcher for a pinned Hugging Face dataset artifact.

    Merely importing this module or constructing a cache never accesses the
    network.  Callers opt in by injecting this fetcher.
    """

    producer_id = DEFAULT_SKILLCENTER_DOWNLOAD_PRODUCER

    def __init__(self, *, local_files_only: bool = False) -> None:
        self.local_files_only = bool(local_files_only)

    def __call__(
        self,
        snapshot: SkillCenterSnapshot,
        destination: Path,
    ) -> Path:
        try:
            from huggingface_hub import hf_hub_download
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise SkillCenterSnapshotFetchError(
                "huggingface_hub is required for network snapshot fetching"
            ) from exc
        try:
            downloaded = hf_hub_download(
                repo_id=snapshot.dataset_id,
                filename=snapshot.repository_file,
                revision=snapshot.dataset_revision,
                repo_type="dataset",
                local_files_only=self.local_files_only,
            )
        except Exception as exc:  # pragma: no cover - backend/network dependent
            raise SkillCenterSnapshotFetchError(
                f"failed to fetch {snapshot.logical_source}: {exc}"
            ) from exc
        # ``hf_hub_download`` normally returns a symlink into the Hub's
        # content-addressed blob cache.  The snapshot cache intentionally
        # rejects fetchers that return symlinks, so materialize those bytes at
        # the caller-owned temporary destination.  The cache independently
        # verifies the declared byte length and SHA-256 before promotion.
        try:
            shutil.copyfile(Path(downloaded), destination)
        except OSError as exc:
            raise SkillCenterSnapshotFetchError(
                f"failed to stage {snapshot.logical_source}: {exc}"
            ) from exc
        return destination


@dataclass(frozen=True, slots=True)
class _CacheAlias:
    snapshot_id: str
    snapshot: SkillCenterSnapshot
    schema_version: str = SKILLCENTER_CACHE_ALIAS_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "snapshot": self.snapshot.to_dict(),
            "snapshot_id": self.snapshot_id,
        }


class SkillCenterSnapshotCache:
    """Content-verified cache for immutable SkillCenter snapshots."""

    def __init__(
        self,
        root: str | Path,
        *,
        fetcher: SkillCenterSnapshotFetcher | Any | None = None,
    ) -> None:
        root_path = Path(root).expanduser()
        try:
            root_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SkillCenterSnapshotValidationError(
                "cache root must be a real directory"
            ) from exc
        if root_path.is_symlink() or not root_path.is_dir():
            raise SkillCenterSnapshotValidationError(
                "cache root must be a real directory"
            )
        self.root = root_path.resolve()
        self.fetcher = fetcher
        self._ensure_directory(self.root / "aliases")
        self._ensure_directory(self.root / "locks")

    def cache_path(self, snapshot: SkillCenterSnapshot) -> Path:
        self._require_snapshot(snapshot)
        return self._safe_cache_path(snapshot.cache_path)

    def alias_path(self, snapshot: SkillCenterSnapshot) -> Path:
        self._require_snapshot(snapshot)
        self._ensure_directory(self.root / "aliases")
        logical_key = canonical_json_bytes(
            {
                "dataset_id": snapshot.dataset_id,
                "dataset_revision": snapshot.dataset_revision,
                "repository_file": snapshot.repository_file,
            }
        )
        key = hashlib.sha256(logical_key).hexdigest()
        return self.root / "aliases" / f"{key}.json"

    def materialize(self, snapshot: SkillCenterSnapshot) -> Path:
        """Return verified local bytes, fetching and promoting on a cache miss."""

        self._require_snapshot(snapshot)
        with self._snapshot_lock(snapshot):
            destination = self.cache_path(snapshot)
            alias_path = self.alias_path(snapshot)
            alias = (
                self._read_alias(alias_path)
                if alias_path.exists() or alias_path.is_symlink()
                else None
            )
            if alias is not None and alias.snapshot != snapshot:
                raise SkillCenterStaleCacheAliasError(
                    "stale cache alias does not match the requested snapshot"
                )
            if alias is not None and alias.snapshot_id != snapshot.snapshot_id:
                raise SkillCenterStaleCacheAliasError(
                    "stale cache alias has an invalid snapshot identity"
                )
            if alias is not None and not destination.exists():
                raise SkillCenterStaleCacheAliasError(
                    "stale cache alias points to a missing artifact"
                )

            if destination.exists():
                self.verify(snapshot, destination)
                if alias is None:
                    self._write_alias_atomic(alias_path, snapshot)
                return destination

            if self.fetcher is None:
                raise SkillCenterSnapshotCacheMiss(
                    f"offline cache miss for {snapshot.logical_source}"
                )
            self._ensure_directory(destination.parent)
            file_descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.",
                suffix=".partial",
                dir=destination.parent,
            )
            os.close(file_descriptor)
            temporary_path = Path(temporary_name)
            try:
                self._invoke_fetcher(snapshot, temporary_path)
                self.verify(snapshot, temporary_path)
                _fsync_file(temporary_path)
                if destination.exists():
                    # A cooperating writer may have won after the initial
                    # cache check.  Its bytes must independently verify.
                    self.verify(snapshot, destination)
                    temporary_path.unlink()
                else:
                    os.replace(temporary_path, destination)
                    _fsync_directory(destination.parent)
                self._write_alias_atomic(alias_path, snapshot)
                return destination
            except SkillCenterSnapshotError:
                if temporary_path.exists():
                    temporary_path.unlink()
                raise
            except Exception as exc:
                if temporary_path.exists():
                    temporary_path.unlink()
                raise SkillCenterSnapshotFetchError(
                    f"fetcher failed for {snapshot.logical_source}: {exc}"
                ) from exc

    def verify(
        self,
        snapshot: SkillCenterSnapshot,
        path: str | Path | None = None,
    ) -> Path:
        """Validate a complete regular file against its declared size and hash."""

        self._require_snapshot(snapshot)
        candidate = self.cache_path(snapshot) if path is None else Path(path)
        if candidate.is_symlink() or not candidate.is_file():
            raise SkillCenterSnapshotIntegrityError(
                f"snapshot artifact is missing or not a regular file: {candidate}"
            )
        actual_size = candidate.stat().st_size
        if actual_size != snapshot.expected_size_bytes:
            raise SkillCenterSnapshotIntegrityError(
                "snapshot size mismatch: "
                f"expected {snapshot.expected_size_bytes}, got {actual_size}"
            )
        actual_sha256 = _file_sha256(candidate)
        if actual_sha256 != snapshot.expected_sha256:
            raise SkillCenterSnapshotIntegrityError(
                "snapshot sha256 mismatch: "
                f"expected {snapshot.expected_sha256}, got {actual_sha256}"
            )
        return candidate

    def open_reader(
        self,
        snapshot: SkillCenterSnapshot,
        **reader_options: Any,
    ) -> SkillCenterBundleReader:
        """Materialize a snapshot and bind it to the read-only SQLite adapter."""

        path = self.materialize(snapshot)
        return SkillCenterBundleReader(
            path,
            dataset_id=snapshot.dataset_id,
            dataset_revision=snapshot.dataset_revision,
            repository_file=snapshot.repository_file,
            **reader_options,
        )

    @staticmethod
    def _require_snapshot(snapshot: SkillCenterSnapshot) -> None:
        if not isinstance(snapshot, SkillCenterSnapshot):
            raise TypeError("snapshot must be a SkillCenterSnapshot")

    def _safe_cache_path(self, relative_path: str) -> Path:
        normalized = _relative_posix_path(relative_path, label="cache_path")
        candidate = self.root.joinpath(*PurePosixPath(normalized).parts)
        if (
            candidate.is_symlink()
            or not candidate.absolute().is_relative_to(self.root)
            or not candidate.resolve(strict=False).is_relative_to(self.root)
        ):
            raise SkillCenterSnapshotValidationError(
                "cache_path escapes the cache root through path traversal or a symlink"
            )
        return candidate

    def _ensure_directory(self, directory: Path) -> None:
        """Create an in-root directory without accepting symlinked parents."""

        try:
            relative = directory.absolute().relative_to(self.root)
        except ValueError as exc:
            raise SkillCenterSnapshotValidationError(
                "cache directory escapes the cache root"
            ) from exc
        current = self.root
        for part in relative.parts:
            current = current / part
            try:
                current.mkdir(exist_ok=True)
            except OSError as exc:
                raise SkillCenterSnapshotValidationError(
                    "cache directories must be real directories"
                ) from exc
            if current.is_symlink() or not current.is_dir():
                raise SkillCenterSnapshotValidationError(
                    "cache directories must not be symlinks"
                )
            if not current.resolve().is_relative_to(self.root):
                raise SkillCenterSnapshotValidationError(
                    "cache directory escapes the cache root through a symlink"
                )

    def _read_alias(self, path: Path) -> _CacheAlias:
        if path.is_symlink() or not path.is_file():
            raise SkillCenterStaleCacheAliasError(
                "cache alias is not a regular file"
            )
        if path.stat().st_size > _MAX_ALIAS_BYTES:
            raise SkillCenterStaleCacheAliasError("cache alias is oversized")
        try:
            decoded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SkillCenterStaleCacheAliasError(
                f"cache alias is malformed: {exc}"
            ) from exc
        if not isinstance(decoded, Mapping):
            raise SkillCenterStaleCacheAliasError(
                "cache alias must contain a JSON object"
            )
        if set(decoded) != {"schema_version", "snapshot", "snapshot_id"}:
            raise SkillCenterStaleCacheAliasError(
                "cache alias has unknown or missing fields"
            )
        if decoded.get("schema_version") != SKILLCENTER_CACHE_ALIAS_SCHEMA_VERSION:
            raise SkillCenterStaleCacheAliasError(
                "cache alias has an unsupported schema version"
            )
        try:
            snapshot = SkillCenterSnapshot.from_dict(decoded["snapshot"])
        except (KeyError, TypeError, SkillCenterSnapshotValidationError) as exc:
            raise SkillCenterStaleCacheAliasError(
                f"cache alias snapshot is invalid: {exc}"
            ) from exc
        snapshot_id = decoded.get("snapshot_id")
        if not isinstance(snapshot_id, str) or snapshot_id != snapshot.snapshot_id:
            raise SkillCenterStaleCacheAliasError(
                "cache alias snapshot_id does not match its manifest"
            )
        return _CacheAlias(snapshot_id=snapshot_id, snapshot=snapshot)

    def _write_alias_atomic(
        self,
        path: Path,
        snapshot: SkillCenterSnapshot,
    ) -> None:
        alias = _CacheAlias(
            snapshot_id=snapshot.snapshot_id,
            snapshot=snapshot,
        )
        payload = canonical_json_bytes(alias.to_dict()) + b"\n"
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".partial",
            dir=path.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(file_descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
            _fsync_directory(path.parent)
        except Exception:
            if temporary_path.exists():
                temporary_path.unlink()
            raise

    def _invoke_fetcher(
        self,
        snapshot: SkillCenterSnapshot,
        destination: Path,
    ) -> None:
        fetch = getattr(self.fetcher, "fetch", None)
        if not callable(fetch):
            fetch = self.fetcher
        if not callable(fetch):
            raise SkillCenterSnapshotFetchError(
                "fetcher must be callable or provide fetch(snapshot, destination)"
            )
        result = fetch(snapshot, destination)
        if isinstance(result, (bytes, bytearray, memoryview)):
            destination.write_bytes(bytes(result))
        elif isinstance(result, int) and not isinstance(result, bool):
            # Path.write_bytes()/write_text() return the count written.  Small
            # fixture fetchers commonly return this value implicitly.
            pass
        elif result is not None:
            source = Path(result)
            if source.is_symlink() or not source.is_file():
                raise SkillCenterSnapshotFetchError(
                    "fetcher returned a path that is not a regular file"
                )
            if source.resolve() != destination.resolve():
                shutil.copyfile(source, destination)
        if destination.is_symlink() or not destination.is_file():
            raise SkillCenterSnapshotFetchError(
                "fetcher did not produce a regular temporary file"
            )

    @contextmanager
    def _snapshot_lock(
        self, snapshot: SkillCenterSnapshot
    ) -> Iterator[None]:
        self._ensure_directory(self.root / "locks")
        key = hashlib.sha256(snapshot.logical_source.encode("utf-8")).hexdigest()
        path = self.root / "locks" / f"{key}.lock"
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise SkillCenterSnapshotValidationError(
                "cache lock must be a regular file"
            )
        with path.open("a+b") as handle:
            try:
                import fcntl
            except ImportError:  # pragma: no cover - non-POSIX fallback
                yield
                return
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _file_sha256(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:  # pragma: no cover - platform/filesystem dependent
        return
    try:
        os.fsync(descriptor)
    except OSError:  # pragma: no cover - platform/filesystem dependent
        pass
    finally:
        os.close(descriptor)


__all__ = [
    "DEFAULT_SKILLCENTER_DOWNLOAD_PRODUCER",
    "HuggingFaceSkillCenterFetcher",
    "INSPECTED_SKILLCENTER_PILOT_REVISION",
    "SKILLCENTER_CACHE_ALIAS_SCHEMA_VERSION",
    "SKILLCENTER_SNAPSHOT_SCHEMA_VERSION",
    "SkillCenterSnapshot",
    "SkillCenterSnapshotCache",
    "SkillCenterSnapshotCacheMiss",
    "SkillCenterSnapshotError",
    "SkillCenterSnapshotFetchError",
    "SkillCenterSnapshotFetcher",
    "SkillCenterSnapshotIntegrityError",
    "SkillCenterSnapshotValidationError",
    "SkillCenterStaleCacheAliasError",
]
