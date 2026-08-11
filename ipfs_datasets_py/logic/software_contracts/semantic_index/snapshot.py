"""Deterministic, non-executing repository input snapshots.

Snapshots are deliberately smaller than a repository manifest: they describe
the bytes that a semantic scanner may consume.  A clean Git checkout is read
from Git objects; a dirty checkout is read from the working tree.  Neither
mode imports, compiles, or otherwise executes repository code.
"""

from __future__ import annotations

import os
import posixpath
import stat
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
    validate_cid,
)


SNAPSHOT_SCHEMA: Final[str] = "ipfs-datasets.software-contracts.semantic-repository-snapshot@2"
SNAPSHOT_ENTRY_SCHEMA: Final[str] = "ipfs-datasets.software-contracts.semantic-snapshot-entry@1"
REPOSITORY_ID_SCHEMA: Final[str] = "ipfs-datasets.software-contracts.semantic-repository-identity@1"
DEFAULT_MAX_FILE_BYTES: Final[int] = 8 * 1024 * 1024
DEFAULT_MAX_ENTRIES: Final[int] = 100_000
GIT_COMMAND_TIMEOUT_SECONDS: Final[float] = 10.0

# These are policy exclusions, not Git ignores.  They make the non-Git path
# hermetic and ensure a scanner never accidentally treats its own state or a
# virtual environment as target source.
_IGNORED_DIRECTORIES: Final[frozenset[str]] = frozenset({
    ".git", ".hg", ".svn", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", ".nox", ".venv", "venv", "env", "build", "dist",
    ".eggs", "htmlcov", "coverage", "node_modules", "vendor", "third_party",
    "third-party", "external", "site-packages", ".semantic-index",
    "semantic-index-state", ".semantic_index",
})
_LOCK_NAMES: Final[frozenset[str]] = frozenset({
    "poetry.lock", "pdm.lock", "uv.lock", "requirements.txt", "requirements-dev.txt",
    "pipfile.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
})
_PYTEST_CONFIG_NAMES: Final[frozenset[str]] = frozenset({
    "pytest.ini", "tox.ini", "setup.cfg", "conftest.py",
})
_SCHEMA_SUFFIXES: Final[tuple[str, ...]] = (".json", ".yaml", ".yml", ".toml", ".proto", ".schema")


class SnapshotError(ValueError):
    """Raised when a snapshot record or request is invalid."""


class GitCommandTimeout(SnapshotError):
    """Raised when Git cannot provide a bounded snapshot input in time."""


def _path(value: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise SnapshotError("path must be nonempty trimmed text")
    value = unicodedata.normalize("NFC", value).replace("\\", "/")
    normalized = posixpath.normpath(value)
    if value != normalized or value in {".", ".."} or value.startswith("../") or value.startswith("/") or any(ord(char) < 32 for char in value):
        raise SnapshotError("path must be repository-relative")
    return value


def _malformed_path(encoded_path: bytes) -> str:
    """Return a collision-resistant, serializable witness for an invalid name."""
    return "@malformed-path/" + encoded_path.hex()


def _ignored_path(path: str) -> bool:
    return any(component in _IGNORED_DIRECTORIES for component in path.split("/"))


def _text(value: str, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise SnapshotError(f"{name} must be nonempty trimmed NFC text")
    return value


@dataclass(frozen=True, slots=True)
class SnapshotEntry:
    """One selected input, including deliberately opaque inputs.

    ``source_cid`` is present only when source bytes were safely read.  An
    opaque entry remains in the manifest, so omissions cannot be mistaken for
    a successful scan.
    """

    path: str
    kind: str
    size_bytes: int | None
    source_cid: str | None = None
    opaque_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _path(self.path))
        object.__setattr__(self, "kind", _text(self.kind, "kind"))
        if self.size_bytes is not None and (type(self.size_bytes) is not int or self.size_bytes < 0):
            raise SnapshotError("size_bytes must be a nonnegative integer or None")
        if self.source_cid is not None:
            try:
                validate_cid(self.source_cid)
            except Exception as exc:
                raise SnapshotError("source_cid must be a valid CID") from exc
        if self.opaque_reason is not None:
            object.__setattr__(self, "opaque_reason", _text(self.opaque_reason, "opaque_reason"))
        if self.opaque_reason is None and self.source_cid is None:
            raise SnapshotError("non-opaque entries require source_cid")
        if self.opaque_reason is not None and self.kind != "opaque":
            raise SnapshotError("opaque entries must have kind 'opaque'")

    @property
    def is_opaque(self) -> bool:
        return self.opaque_reason is not None

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SNAPSHOT_ENTRY_SCHEMA, "path": self.path, "kind": self.kind,
                "size_bytes": self.size_bytes, "source_cid": self.source_cid,
                "opaque_reason": self.opaque_reason}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SnapshotEntry":
        expected = {"schema", "path", "kind", "size_bytes", "source_cid", "opaque_reason"}
        if set(value) != expected or value.get("schema") != SNAPSHOT_ENTRY_SCHEMA:
            raise SnapshotError("unsupported SnapshotEntry schema")
        return cls(**{key: value[key] for key in expected - {"schema"}})


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    repository_id: str
    entries: Sequence[SnapshotEntry]
    mode: str
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_entries: int = DEFAULT_MAX_ENTRIES
    git_tree: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository_id", _text(self.repository_id, "repository_id"))
        if self.mode not in {"git-clean", "git-working", "filesystem"}:
            raise SnapshotError("unsupported snapshot mode")
        if self.git_tree is not None:
            if self.mode != "git-clean" or len(self.git_tree) not in {40, 64} or any(char not in "0123456789abcdef" for char in self.git_tree):
                raise SnapshotError("git_tree must be a Git object-format tree identifier for git-clean snapshots")
        elif self.mode == "git-clean":
            raise SnapshotError("git-clean snapshots require git_tree")
        if type(self.max_file_bytes) is not int or self.max_file_bytes < 1:
            raise SnapshotError("max_file_bytes must be a positive integer")
        if type(self.max_entries) is not int or self.max_entries < 1:
            raise SnapshotError("max_entries must be a positive integer")
        if any(not isinstance(entry, SnapshotEntry) for entry in self.entries):
            raise SnapshotError("entries must be SnapshotEntry records")
        entries = tuple(sorted(self.entries, key=lambda entry: entry.path))
        if len(entries) > self.max_entries:
            raise SnapshotError("entries exceed max_entries")
        if len({entry.path for entry in entries}) != len(entries):
            raise SnapshotError("entries must not have duplicate paths")
        object.__setattr__(self, "entries", entries)

    def identity_payload(self) -> dict[str, Any]:
        # The acquisition mode intentionally does not affect identity: equal
        # input manifests from a clean and a working scan are interchangeable.
        return {"schema": SNAPSHOT_SCHEMA, "repository_id": self.repository_id,
                "entries": [entry.to_dict() for entry in self.entries],
                "max_file_bytes": self.max_file_bytes, "max_entries": self.max_entries,
                "git_tree": self.git_tree}

    @property
    def snapshot_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["mode"] = self.mode
        value["snapshot_cid"] = self.snapshot_cid
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RepositorySnapshot":
        expected = {"schema", "repository_id", "entries", "mode", "max_file_bytes", "max_entries", "git_tree", "snapshot_cid"}
        if set(value) != expected or value.get("schema") != SNAPSHOT_SCHEMA:
            raise SnapshotError("unsupported RepositorySnapshot schema")
        result = cls(repository_id=value["repository_id"], entries=tuple(SnapshotEntry.from_dict(item) for item in value["entries"]), mode=value["mode"], max_file_bytes=value["max_file_bytes"], max_entries=value["max_entries"], git_tree=value["git_tree"])
        if value["snapshot_cid"] != result.snapshot_cid:
            raise SnapshotError("RepositorySnapshot snapshot_cid does not verify")
        return result


def _git(root: Path, args: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(["git", *args], cwd=str(root), stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                              timeout=GIT_COMMAND_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise GitCommandTimeout("git command timed out") from exc


def _git_root(root: Path) -> Path | None:
    result = _git(root, ("rev-parse", "--show-toplevel"))
    if result.returncode:
        return None
    try:
        return Path(result.stdout.decode("utf-8", "strict").strip()).resolve()
    except UnicodeDecodeError:
        return None


def repository_identity(repository: str | os.PathLike[str], *, repository_id: str | None = None) -> str:
    """Return a stable repository identity without putting an absolute path in it."""
    if repository_id is not None:
        return _text(repository_id, "repository_id")
    root = Path(repository).resolve()
    git_root = _git_root(root)
    label = (git_root or root).name
    remote = ""
    head = ""
    if git_root is not None:
        result = _git(git_root, ("config", "--get", "remote.origin.url"))
        if not result.returncode:
            remote = result.stdout.decode("utf-8", "replace").strip()
        # A repository without an origin has no portable external identity.
        # Its immutable HEAD is a conservative identity anchor: unrelated
        # same-basename repositories therefore cannot collide by label alone.
        if not remote:
            result = _git(git_root, ("rev-parse", "HEAD"))
            if not result.returncode:
                head = result.stdout.decode("ascii", "strict").strip()
    return cid_for_structured({"schema": REPOSITORY_ID_SCHEMA, "kind": "git" if git_root else "filesystem", "label": label, "origin": remote, "head": head})


def _kind(path: str) -> str:
    name = posixpath.basename(path).lower()
    suffix = posixpath.splitext(name)[1]
    if suffix in {".py", ".pyi"}:
        return "python"
    if name in _PYTEST_CONFIG_NAMES or name == "pyproject.toml":
        return "pytest-config"
    if name in _LOCK_NAMES:
        return "dependency-lock"
    if suffix in _SCHEMA_SUFFIXES:
        return "schema"
    return "artifact"


def _opaque(path: str, reason: str, size: int | None = None, source_cid: str | None = None) -> SnapshotEntry:
    return SnapshotEntry(path=path, kind="opaque", size_bytes=size, source_cid=source_cid, opaque_reason=reason)


def _entry_from_bytes(path: str, data: bytes, *, max_file_bytes: int) -> SnapshotEntry:
    if len(data) > max_file_bytes:
        return _opaque(path, "oversized", len(data))
    try:
        data.decode("utf-8", "strict")
    except UnicodeDecodeError:
        return _opaque(path, "undecodable", len(data), cid_for_bytes(data))
    return SnapshotEntry(path=path, kind=_kind(path), size_bytes=len(data), source_cid=cid_for_bytes(data))


def _working_entry(root: Path, path: str, *, max_file_bytes: int) -> SnapshotEntry:
    candidate = root / path
    try:
        before = candidate.stat(follow_symlinks=False)
    except FileNotFoundError:
        return _opaque(path, "missing")
    except OSError:
        return _opaque(path, "unreadable")
    if not stat.S_ISREG(before.st_mode):
        return _opaque(path, "symlink_or_nonregular", before.st_size)
    if before.st_size > max_file_bytes:
        return _opaque(path, "oversized", before.st_size)
    try:
        # O_NOFOLLOW closes the check/open race: a repository file replaced by
        # a symlink is opaque rather than an opportunity to read outside root.
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            return _opaque(path, "symlink_or_nonregular", before.st_size)
        descriptor = os.open(candidate, os.O_RDONLY | nofollow)
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode):
                return _opaque(path, "symlink_or_nonregular", before.st_size)
            data = handle.read(max_file_bytes + 1)
        after = candidate.stat(follow_symlinks=False)
    except FileNotFoundError:
        return _opaque(path, "missing")
    except OSError:
        return _opaque(path, "unreadable", before.st_size)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        return _opaque(path, "raced", after.st_size)
    return _entry_from_bytes(path, data, max_file_bytes=max_file_bytes)


def _clean_git_entries(root: Path, tree: str, *, max_file_bytes: int, max_entries: int) -> Iterable[SnapshotEntry]:
    listed = _git(root, ("ls-tree", "-r", "-z", tree))
    if listed.returncode:
        raise SnapshotError("git ls-tree failed")
    records = [item for item in listed.stdout.split(b"\0") if item]
    if len(records) > max_entries:
        raise SnapshotError("selected entries exceed max_entries")
    for record in records:
        try:
            metadata, encoded_path = record.split(b"\t", 1)
            mode, object_type, oid = metadata.decode("ascii").split()
            path = _path(encoded_path.decode("utf-8", "strict"))
        except (ValueError, UnicodeDecodeError, SnapshotError):
            yield _opaque(_malformed_path(encoded_path), "malformed_path")
            continue
        if _ignored_path(path):
            continue
        if mode == "120000" or object_type != "blob":
            yield _opaque(path, "symlink_or_nonregular")
            continue
        size_result = _git(root, ("cat-file", "-s", oid))
        try:
            size = int(size_result.stdout.strip()) if not size_result.returncode else None
        except ValueError:
            size = None
        if size is None:
            yield _opaque(path, "missing")
        elif size > max_file_bytes:
            yield _opaque(path, "oversized", size)
        else:
            content = _git(root, ("cat-file", "blob", oid))
            if content.returncode:
                yield _opaque(path, "missing", size)
            else:
                yield _entry_from_bytes(path, content.stdout, max_file_bytes=max_file_bytes)


def _working_paths(root: Path, *, max_entries: int) -> list[str]:
    listed = _git(root, ("ls-files", "-z", "--cached", "--others", "--exclude-standard"))
    if listed.returncode:
        raise SnapshotError("git ls-files failed")
    paths: set[str] = set()
    for item in listed.stdout.split(b"\0"):
        if not item:
            continue
        try:
            path = _path(item.decode("utf-8", "strict"))
        except (UnicodeDecodeError, SnapshotError):
            paths.add(_malformed_path(item))
            continue
        if not _ignored_path(path):
            paths.add(path)
    result = sorted(paths)
    if len(result) > max_entries:
        raise SnapshotError("selected entries exceed max_entries")
    return result


def _filesystem_paths(root: Path, *, max_entries: int) -> list[str]:
    paths: list[str] = []
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError:
            continue
        for child in children:
            relative = child.relative_to(root).as_posix()
            try:
                if child.is_dir() and not child.is_symlink():
                    if not _ignored_path(relative):
                        stack.append(child)
                elif not _ignored_path(relative):
                    paths.append(_path(relative))
            except OSError:
                paths.append(_path(relative))
            if len(paths) > max_entries:
                raise SnapshotError("selected entries exceed max_entries")
    return sorted(paths)


def snapshot_repository(repository: str | os.PathLike[str], *, repository_id: str | None = None,
                        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
                        max_entries: int = DEFAULT_MAX_ENTRIES) -> RepositorySnapshot:
    """Create a sorted input manifest without importing or executing target code."""
    if type(max_file_bytes) is not int or max_file_bytes < 1:
        raise SnapshotError("max_file_bytes must be a positive integer")
    if type(max_entries) is not int or max_entries < 1:
        raise SnapshotError("max_entries must be a positive integer")
    root = Path(repository).resolve()
    if not root.is_dir():
        raise SnapshotError("repository must be an existing directory")
    git_root = _git_root(root)
    identity = repository_identity(root, repository_id=repository_id)
    if git_root is not None:
        status = _git(git_root, ("status", "--porcelain", "--untracked-files=all"))
        if not status.returncode and not status.stdout:
            tree_result = _git(git_root, ("rev-parse", "HEAD^{tree}"))
            if tree_result.returncode:
                raise SnapshotError("git HEAD tree is unavailable")
            tree = tree_result.stdout.decode("ascii", "strict").strip()
            entries = tuple(_clean_git_entries(git_root, tree, max_file_bytes=max_file_bytes, max_entries=max_entries))
            return RepositorySnapshot(identity, entries, "git-clean", max_file_bytes, max_entries, tree)
        paths = _working_paths(git_root, max_entries=max_entries)
        entries = tuple(
            _opaque(path, "malformed_path") if path.startswith("@malformed-path/")
            else _working_entry(git_root, path, max_file_bytes=max_file_bytes)
            for path in paths
        )
        return RepositorySnapshot(identity, entries, "git-working", max_file_bytes, max_entries)
    paths = _filesystem_paths(root, max_entries=max_entries)
    entries = tuple(_working_entry(root, path, max_file_bytes=max_file_bytes) for path in paths)
    return RepositorySnapshot(identity, entries, "filesystem", max_file_bytes, max_entries)


__all__ = ["DEFAULT_MAX_ENTRIES", "DEFAULT_MAX_FILE_BYTES", "GIT_COMMAND_TIMEOUT_SECONDS", "GitCommandTimeout", "RepositorySnapshot", "SNAPSHOT_ENTRY_SCHEMA", "SNAPSHOT_SCHEMA", "SnapshotEntry", "SnapshotError", "repository_identity", "snapshot_repository"]
