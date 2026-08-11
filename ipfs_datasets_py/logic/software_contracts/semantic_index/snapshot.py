"""Deterministic, captured-byte repository snapshots.

The snapshot is the acquisition boundary: the scanner consumes the bytes kept
here and never asks Git (or the worktree) for a second copy of their content.
"""
from __future__ import annotations

import os
import posixpath
import stat
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes, cid_for_structured, validate_cid

SNAPSHOT_SCHEMA: Final[str] = "ipfs-datasets.software-contracts.semantic-repository-snapshot@3"
SNAPSHOT_ENTRY_SCHEMA: Final[str] = "ipfs-datasets.software-contracts.semantic-snapshot-entry@2"
REPOSITORY_ID_SCHEMA: Final[str] = "ipfs-datasets.software-contracts.semantic-repository-identity@2"
DEFAULT_MAX_FILE_BYTES: Final[int] = 8 * 1024 * 1024
DEFAULT_MAX_ENTRIES: Final[int] = 100_000
GIT_COMMAND_TIMEOUT_SECONDS: Final[float] = 10.0
_IGNORED_DIRECTORIES: Final[frozenset[str]] = frozenset({".git", ".hg", ".svn", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox", ".venv", "venv", "env", "build", "dist", ".eggs", "htmlcov", "coverage", "node_modules", "vendor", "third_party", "third-party", "external", "site-packages", ".semantic-index", "semantic-index-state", ".semantic_index"})
_LOCK_NAMES = frozenset({"poetry.lock", "pdm.lock", "uv.lock", "requirements.txt", "requirements-dev.txt", "pipfile.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"})
_PYTEST_CONFIG_NAMES = frozenset({"pytest.ini", "tox.ini", "setup.cfg", "conftest.py"})
_SCHEMA_SUFFIXES = (".json", ".yaml", ".yml", ".toml", ".proto", ".schema")

class SnapshotError(ValueError): pass
class GitCommandTimeout(SnapshotError): pass
class GitSnapshotError(SnapshotError): pass
class GitUnbornRepository(SnapshotError): pass

def _text(value: str, name: str) -> str:
    if type(value) is not str or not value or value != value.strip(): raise SnapshotError(f"{name} must be nonempty trimmed text")
    return value

def _path(value: str) -> str:
    _text(value, "path")
    if value.startswith("/") or value in {".", ".."} or any(part in {"", ".", ".."} for part in value.split("/")) or any(ord(c) < 32 for c in value):
        raise SnapshotError("path must be a raw repository-relative path")
    return value

def _raw_display(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8", "strict")
        return _path(text)
    except (UnicodeDecodeError, SnapshotError):
        return "@malformed-path/" + raw.hex()

def _malformed_raw(raw: bytes) -> bool:
    try:
        _path(raw.decode("utf-8", "strict"))
    except (UnicodeDecodeError, SnapshotError):
        return True
    return False

def _raw_hex(path: str) -> str: return os.fsencode(path).hex()
def _ignored_raw(raw: bytes) -> bool:
    # Compare bytes, so invalid names and Unicode normalization cannot evade policy.
    return any(part.decode("ascii", "ignore") in _IGNORED_DIRECTORIES for part in raw.split(b"/"))
def _git_oid(value: str | None, name: str) -> str | None:
    if value is None: return None
    if len(value) not in {40, 64} or any(c not in "0123456789abcdef" for c in value): raise SnapshotError(f"{name} must be a Git object id")
    return value

@dataclass(frozen=True, slots=True)
class SnapshotEntry:
    path: str
    kind: str
    size_bytes: int | None
    source_cid: str | None = None
    opaque_reason: str | None = None
    raw_path_hex: str | None = None
    git_blob_oid: str | None = None
    acquisition: str = "captured"
    # Deliberately not serialized: it is immutable process-local handoff data.
    captured_bytes: bytes | None = field(default=None, compare=False, repr=False)
    witness: tuple[int, int, int, int] | None = field(default=None, compare=False, repr=False)
    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _path(self.path)); object.__setattr__(self, "kind", _text(self.kind, "kind"))
        raw = self.raw_path_hex or _raw_hex(self.path)
        try: bytes.fromhex(raw)
        except ValueError as exc: raise SnapshotError("raw_path_hex must be hexadecimal") from exc
        object.__setattr__(self, "raw_path_hex", raw)
        if self.size_bytes is not None and (type(self.size_bytes) is not int or self.size_bytes < 0): raise SnapshotError("size_bytes must be nonnegative or None")
        if self.source_cid is not None:
            try: validate_cid(self.source_cid)
            except Exception as exc: raise SnapshotError("source_cid must be valid") from exc
        if self.opaque_reason is not None:
            object.__setattr__(self, "opaque_reason", _text(self.opaque_reason, "opaque_reason"))
            if self.kind != "opaque": raise SnapshotError("opaque entries must have kind opaque")
        elif self.source_cid is None: raise SnapshotError("non-opaque entries require source_cid")
        object.__setattr__(self, "git_blob_oid", _git_oid(self.git_blob_oid, "git_blob_oid"))
        if self.acquisition not in {"captured", "opaque"}: raise SnapshotError("unsupported acquisition")
        if self.captured_bytes is not None:
            if type(self.captured_bytes) is not bytes or self.source_cid != cid_for_bytes(self.captured_bytes): raise SnapshotError("captured bytes do not verify source_cid")
    @property
    def is_opaque(self) -> bool: return self.opaque_reason is not None
    def identity_payload(self) -> dict[str, Any]:
        return {"schema": SNAPSHOT_ENTRY_SCHEMA, "path": self.path, "raw_path_hex": self.raw_path_hex, "kind": self.kind, "size_bytes": self.size_bytes, "source_cid": self.source_cid, "opaque_reason": self.opaque_reason, "git_blob_oid": self.git_blob_oid, "acquisition": self.acquisition}
    @property
    def entry_cid(self) -> str: return cid_for_structured(self.identity_payload())
    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_payload(), "entry_cid": self.entry_cid}
    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SnapshotEntry":
        fields = {"schema", "path", "raw_path_hex", "kind", "size_bytes", "source_cid", "opaque_reason", "git_blob_oid", "acquisition", "entry_cid"}
        if set(value) != fields or value.get("schema") != SNAPSHOT_ENTRY_SCHEMA: raise SnapshotError("unsupported SnapshotEntry schema")
        claimed = value["entry_cid"]
        result = cls(**{key: value[key] for key in fields - {"schema", "entry_cid"}})
        if claimed != result.entry_cid: raise SnapshotError("SnapshotEntry entry_cid does not verify")
        return result

@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    repository_id: str; entries: Sequence[SnapshotEntry]; mode: str; max_file_bytes: int = DEFAULT_MAX_FILE_BYTES; max_entries: int = DEFAULT_MAX_ENTRIES; git_tree: str | None = None; git_commit: str | None = None; exclusions: Sequence[str] = ()
    def __post_init__(self) -> None:
        object.__setattr__(self, "repository_id", _text(self.repository_id, "repository_id"))
        if self.mode not in {"git-clean", "git-working", "git-unborn", "filesystem"}: raise SnapshotError("unsupported snapshot mode")
        object.__setattr__(self, "git_tree", _git_oid(self.git_tree, "git_tree")); object.__setattr__(self, "git_commit", _git_oid(self.git_commit, "git_commit"))
        if self.mode in {"git-clean", "git-working"} and (self.git_tree is None or self.git_commit is None): raise SnapshotError("committed Git snapshots require commit and tree")
        if self.mode == "git-clean" and any(entry.git_blob_oid is None and not entry.is_opaque for entry in self.entries): raise SnapshotError("clean Git entries require blob ids")
        if type(self.max_file_bytes) is not int or self.max_file_bytes < 1 or type(self.max_entries) is not int or self.max_entries < 1: raise SnapshotError("invalid limits")
        if any(not isinstance(e, SnapshotEntry) for e in self.entries): raise SnapshotError("entries must be SnapshotEntry records")
        entries = tuple(sorted(self.entries, key=lambda e: (e.raw_path_hex or "", e.path)))
        if len(entries) > self.max_entries or len({e.raw_path_hex for e in entries}) != len(entries): raise SnapshotError("invalid selected entries")
        object.__setattr__(self, "entries", entries); object.__setattr__(self, "exclusions", tuple(sorted(_text(x, "exclusion") for x in self.exclusions)))
    def identity_payload(self) -> dict[str, Any]: return {"schema": SNAPSHOT_SCHEMA, "repository_id": self.repository_id, "entries": [e.to_dict() for e in self.entries], "max_file_bytes": self.max_file_bytes, "max_entries": self.max_entries, "git_tree": self.git_tree, "git_commit": self.git_commit, "exclusions": list(self.exclusions)}
    @property
    def snapshot_cid(self) -> str: return cid_for_structured(self.identity_payload())
    def to_dict(self) -> dict[str, Any]: return {**self.identity_payload(), "mode": self.mode, "snapshot_cid": self.snapshot_cid}
    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RepositorySnapshot":
        fields = {"schema", "repository_id", "entries", "mode", "max_file_bytes", "max_entries", "git_tree", "git_commit", "exclusions", "snapshot_cid"}
        if set(value) != fields or value.get("schema") != SNAPSHOT_SCHEMA: raise SnapshotError("unsupported RepositorySnapshot schema")
        result = cls(value["repository_id"], tuple(SnapshotEntry.from_dict(e) for e in value["entries"]), value["mode"], value["max_file_bytes"], value["max_entries"], value["git_tree"], value["git_commit"], value["exclusions"])
        if value["snapshot_cid"] != result.snapshot_cid: raise SnapshotError("RepositorySnapshot snapshot_cid does not verify")
        return result

def _git(root: Path, args: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
    try: return subprocess.run(["git", *args], cwd=str(root), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=GIT_COMMAND_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc: raise GitCommandTimeout("git command timed out") from exc
def _not_git(result: subprocess.CompletedProcess[bytes]) -> bool: return b"not a git repository" in result.stderr.lower()
def _require_git(root: Path, args: Sequence[str], what: str) -> bytes:
    result = _git(root, args)
    if result.returncode or result.stderr: raise GitSnapshotError(f"git {what} failed or warned")
    return result.stdout
def _git_root(root: Path) -> Path | None:
    result = _git(root, ("rev-parse", "--show-toplevel"))
    if result.returncode:
        if _not_git(result): return None
        raise GitSnapshotError("git repository discovery failed")
    if result.stderr: raise GitSnapshotError("git repository discovery warned")
    try: return Path(result.stdout.decode("utf-8", "strict").strip()).resolve()
    except UnicodeDecodeError as exc: raise GitSnapshotError("git root was not UTF-8") from exc

def repository_identity(repository: str | os.PathLike[str], *, repository_id: str | None = None) -> str:
    if repository_id is not None: return _text(repository_id, "repository_id")
    root = Path(repository).resolve(); git_root = _git_root(root); label = (git_root or root).name
    if git_root is None: return cid_for_structured({"schema": REPOSITORY_ID_SCHEMA, "kind": "filesystem", "label": label, "path": str(root)})
    remote_result = _git(git_root, ("config", "--get", "remote.origin.url")); remote = "" if remote_result.returncode else remote_result.stdout.decode("utf-8", "strict").strip()
    head = _git(git_root, ("rev-parse", "--verify", "--quiet", "HEAD"))
    if head.returncode:
        if head.returncode != 1 or head.stderr: raise GitSnapshotError("git HEAD discovery failed")
        # Git has no durable intrinsic identifier before its first commit.
        common = _require_git(git_root, ("rev-parse", "--git-common-dir"), "common-dir").decode("utf-8", "strict").strip()
        return cid_for_structured({"schema": REPOSITORY_ID_SCHEMA, "kind": "git-unborn", "label": label, "common_dir": str((git_root / common).resolve()), "origin": remote})
    roots = _require_git(git_root, ("rev-list", "--max-parents=0", "--reverse", "HEAD"), "root-history").decode("ascii", "strict").splitlines()
    return cid_for_structured({"schema": REPOSITORY_ID_SCHEMA, "kind": "git", "origin": remote, "root_commit": roots[0], "object_format": _require_git(git_root, ("rev-parse", "--show-object-format"), "object-format").decode("ascii", "strict").strip()})

def _kind(path: str) -> str:
    name = posixpath.basename(path).lower(); suffix = posixpath.splitext(name)[1]
    if suffix in {".py", ".pyi"}: return "python"
    if name in _PYTEST_CONFIG_NAMES or name == "pyproject.toml": return "pytest-config"
    if name in _LOCK_NAMES: return "dependency-lock"
    if suffix in _SCHEMA_SUFFIXES: return "schema"
    return "artifact"
def _opaque(path: str, reason: str, size: int | None = None, source_cid: str | None = None, *, raw: bytes | None = None, oid: str | None = None) -> SnapshotEntry: return SnapshotEntry(path, "opaque", size, source_cid, reason, (raw or os.fsencode(path)).hex(), oid, "opaque")
def _entry(path: str, raw: bytes, data: bytes, max_file_bytes: int, oid: str | None = None, witness: tuple[int, int, int, int] | None = None) -> SnapshotEntry:
    if len(data) > max_file_bytes: return _opaque(path, "oversized", len(data), raw=raw, oid=oid)
    try: data.decode("utf-8", "strict")
    except UnicodeDecodeError: return _opaque(path, "undecodable", len(data), cid_for_bytes(data), raw=raw, oid=oid)
    return SnapshotEntry(path, _kind(path), len(data), cid_for_bytes(data), None, raw.hex(), oid, "captured", data, witness)
def _working_entry(root: Path, raw: bytes, max_file_bytes: int) -> SnapshotEntry:
    path = _raw_display(raw); candidate = root / os.fsdecode(raw)
    if _malformed_raw(raw): return _opaque(path, "malformed_path", raw=raw)
    try:
        before = candidate.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode): return _opaque(path, "symlink_or_nonregular", before.st_size, raw=raw)
        if before.st_size > max_file_bytes: return _opaque(path, "oversized", before.st_size, raw=raw)
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None: return _opaque(path, "symlink_or_nonregular", before.st_size, raw=raw)
        fd = os.open(candidate, os.O_RDONLY | nofollow)
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode): return _opaque(path, "symlink_or_nonregular", before.st_size, raw=raw)
            data = handle.read(max_file_bytes + 1)
        after = candidate.stat(follow_symlinks=False)
    except FileNotFoundError: return _opaque(path, "missing", raw=raw)
    except OSError: return _opaque(path, "unreadable", raw=raw)
    witness = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    if witness != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns): return _opaque(path, "raced", after.st_size, raw=raw)
    return _entry(path, raw, data, max_file_bytes, witness=witness)
def _clean_entries(root: Path, tree: str, max_file_bytes: int, max_entries: int) -> Iterable[SnapshotEntry]:
    records = [r for r in _require_git(root, ("ls-tree", "-r", "-z", tree), "ls-tree").split(b"\0") if r]
    selected = []
    for record in records:
        try: meta, raw = record.split(b"\t", 1); mode, typ, oid = meta.decode("ascii").split()
        except ValueError: yield _opaque(_raw_display(record), "malformed_path", raw=record); continue
        if _ignored_raw(raw): continue
        selected.append((mode, typ, oid, raw))
    if len(selected) > max_entries: raise SnapshotError("selected entries exceed max_entries")
    for mode, typ, oid, raw in selected:
        path = _raw_display(raw)
        if _malformed_raw(raw): yield _opaque(path, "malformed_path", raw=raw, oid=oid); continue
        if mode == "120000" or typ != "blob": yield _opaque(path, "symlink_or_nonregular", raw=raw, oid=oid); continue
        try: size = int(_require_git(root, ("cat-file", "-s", oid), "blob size").strip())
        except ValueError as exc: raise GitSnapshotError("git blob size was malformed") from exc
        if size > max_file_bytes: yield _opaque(path, "oversized", size, raw=raw, oid=oid); continue
        data = _require_git(root, ("cat-file", "blob", oid), "blob")
        yield _entry(path, raw, data, max_file_bytes, oid)
def _working_paths(root: Path, max_entries: int) -> list[bytes]:
    raw_paths = [p for p in _require_git(root, ("ls-files", "-z", "--cached", "--others", "--exclude-standard"), "ls-files").split(b"\0") if p and not _ignored_raw(p)]
    result = sorted(set(raw_paths))
    if len(result) > max_entries: raise SnapshotError("selected entries exceed max_entries")
    return result
def _tracked_blob_oids(root: Path) -> dict[bytes, str]:
    """Index blob evidence is authoritative even when worktree bytes are dirty."""
    result: dict[bytes, str] = {}
    for record in _require_git(root, ("ls-files", "--stage", "-z"), "index").split(b"\0"):
        if not record: continue
        try:
            meta, raw = record.split(b"\t", 1)
            _mode, oid, stage = meta.decode("ascii").split()
        except ValueError as exc:
            raise GitSnapshotError("git index record was malformed") from exc
        if stage == "0": result[raw] = oid
    return result
def _has_selected_status(status: bytes) -> bool:
    """Ignore changes entirely under policy control roots before mode choice."""
    records = [r for r in status.split(b"\0") if r]
    index = 0
    while index < len(records):
        record = records[index]; index += 1
        if len(record) < 4: raise GitSnapshotError("git status record was malformed")
        code, raw = record[:2], record[3:]
        if not _ignored_raw(raw): return True
        # In -z porcelain rename/copy's source path is the following record.
        if code[:1] in {b"R", b"C"}:
            if index >= len(records): raise GitSnapshotError("git status rename record was incomplete")
            if not _ignored_raw(records[index]): return True
            index += 1
    return False
def _filesystem_entries(root: Path, max_file_bytes: int, max_entries: int) -> list[SnapshotEntry]:
    result: list[SnapshotEntry] = []; stack = [root]
    while stack:
        directory = stack.pop()
        try: children = sorted(list(os.scandir(directory)), key=lambda x: os.fsencode(x.name))
        except OSError:
            if directory != root:
                raw = os.fsencode(str(directory.relative_to(root)))
                result.append(_opaque(_raw_display(raw), "unreadable_directory", raw=raw))
            continue
        for child in children:
            raw = os.fsencode(str(Path(child.path).relative_to(root)))
            if _ignored_raw(raw): continue
            try:
                if child.is_dir(follow_symlinks=False): stack.append(Path(child.path))
                else: result.append(_working_entry(root, raw, max_file_bytes))
            except OSError: result.append(_opaque(_raw_display(raw), "unreadable", raw=raw))
            if len(result) > max_entries: raise SnapshotError("selected entries exceed max_entries")
    return result
def snapshot_repository(repository: str | os.PathLike[str], *, repository_id: str | None = None, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES, max_entries: int = DEFAULT_MAX_ENTRIES) -> RepositorySnapshot:
    if type(max_file_bytes) is not int or max_file_bytes < 1 or type(max_entries) is not int or max_entries < 1: raise SnapshotError("invalid limits")
    root = Path(repository).resolve()
    if not root.is_dir(): raise SnapshotError("repository must be an existing directory")
    git_root = _git_root(root); identity = repository_identity(root, repository_id=repository_id); exclusions = tuple(sorted(_IGNORED_DIRECTORIES))
    if git_root is None: return RepositorySnapshot(identity, _filesystem_entries(root, max_file_bytes, max_entries), "filesystem", max_file_bytes, max_entries, exclusions=exclusions)
    head = _git(git_root, ("rev-parse", "--verify", "--quiet", "HEAD"))
    if head.returncode:
        if head.returncode != 1 or head.stderr: raise GitSnapshotError("git HEAD discovery failed")
        return RepositorySnapshot(identity, tuple(), "git-unborn", max_file_bytes, max_entries, exclusions=exclusions)
    commit = head.stdout.decode("ascii", "strict").strip(); tree = _require_git(git_root, ("rev-parse", "HEAD^{tree}"), "HEAD tree").decode("ascii", "strict").strip()
    status = _require_git(git_root, ("status", "--porcelain", "-z", "--untracked-files=all"), "status")
    if not _has_selected_status(status): return RepositorySnapshot(identity, tuple(_clean_entries(git_root, tree, max_file_bytes, max_entries)), "git-clean", max_file_bytes, max_entries, tree, commit, exclusions)
    paths = _working_paths(git_root, max_entries); index_oids = _tracked_blob_oids(git_root)
    entries = tuple(replace(_working_entry(git_root, raw, max_file_bytes), git_blob_oid=index_oids.get(raw)) for raw in paths)
    return RepositorySnapshot(identity, entries, "git-working", max_file_bytes, max_entries, tree, commit, exclusions)

__all__ = ["DEFAULT_MAX_ENTRIES", "DEFAULT_MAX_FILE_BYTES", "GIT_COMMAND_TIMEOUT_SECONDS", "GitCommandTimeout", "GitSnapshotError", "GitUnbornRepository", "RepositorySnapshot", "SNAPSHOT_ENTRY_SCHEMA", "SNAPSHOT_SCHEMA", "SnapshotEntry", "SnapshotError", "repository_identity", "snapshot_repository"]
