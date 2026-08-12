"""Deterministic, captured-byte repository snapshots.

This is the authority boundary for repository inputs.  In particular, a
snapshot describes both what was observed and the exact bytes that may be
analysed in this process; a deserialised snapshot is only a manifest claim.
"""
from __future__ import annotations

import fcntl
import os
import posixpath
import stat
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes, cid_for_structured, validate_cid

SNAPSHOT_SCHEMA: Final[str] = "ipfs-datasets.software-contracts.semantic-repository-snapshot@4"
SNAPSHOT_ENTRY_SCHEMA: Final[str] = "ipfs-datasets.software-contracts.semantic-snapshot-entry@3"
REPOSITORY_ID_SCHEMA: Final[str] = "ipfs-datasets.software-contracts.semantic-repository-identity@3"
DEFAULT_MAX_FILE_BYTES: Final[int] = 8 * 1024 * 1024
DEFAULT_MAX_ENTRIES: Final[int] = 100_000
GIT_COMMAND_TIMEOUT_SECONDS: Final[float] = 10.0
_UNBORN_ID_FILE: Final[str] = ".ipfs-datasets-semantic-index-unborn-id"
_UNBORN_ID_BYTES: Final[int] = 32
_UNBORN_TOKEN_HEX_LEN: Final[int] = _UNBORN_ID_BYTES * 2
_UNBORN_CLEANUP_BOUND: Final[int] = 256
_IGNORED_DIRECTORIES: Final[frozenset[str]] = frozenset({".git", ".hg", ".svn", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox", ".venv", "venv", "env", "build", "dist", ".eggs", "htmlcov", "coverage", "node_modules", "vendor", "third_party", "third-party", "external", "site-packages", ".semantic-index", "semantic-index-state", ".semantic_index"})
_LOCK_NAMES = frozenset({"poetry.lock", "pdm.lock", "uv.lock", "requirements.txt", "requirements-dev.txt", "pipfile.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"})
_PYTEST_CONFIG_NAMES = frozenset({"pytest.ini", "tox.ini", "setup.cfg", "conftest.py"})
_SCHEMA_SUFFIXES = (".json", ".yaml", ".yml", ".toml", ".proto", ".schema")
# Kept for compatibility with prior manifests.  It is not an identity domain:
# raw_path_hex remains the non-forgeable key, so a real path with this spelling
# cannot collide with an unsafe byte name downstream.
_UNSAFE_PREFIX = "@malformed-path/"
_O_NOFOLLOW: Final[int] = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY: Final[int] = getattr(os, "O_DIRECTORY", 0)
_O_NONBLOCK: Final[int] = getattr(os, "O_NONBLOCK", 0)

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

def _safe_raw_path(raw: bytes) -> str | None:
    try: return _path(raw.decode("utf-8", "strict"))
    except (UnicodeDecodeError, SnapshotError): return None

def _raw_display(raw: bytes) -> str:
    return _safe_raw_path(raw) or (_UNSAFE_PREFIX + raw.hex())

def _malformed_raw(raw: bytes) -> bool: return _safe_raw_path(raw) is None
def _raw_hex(path: str) -> str: return os.fsencode(path).hex()

def _exclusion_raw(exclusions: Iterable[str] | None) -> tuple[bytes, ...]:
    values = set(_IGNORED_DIRECTORIES)
    if exclusions is not None:
        for item in exclusions:
            item = _path(_text(item, "exclusion"))
            values.add(item)
    return tuple(sorted(os.fsencode(value) for value in values))

def _ignored_raw(raw: bytes, exclusions: Sequence[bytes]) -> bool:
    # Exclusions may name either one directory component (the built-in
    # exclusions) or a repository-relative subtree supplied by a caller.
    # All comparisons stay in the raw-byte domain: an invalid UTF-8 lookalike
    # must not disappear due to a decoded-string comparison.
    components = raw.split(b"/")
    return any(
        excluded in components
        or raw == excluded
        or raw.startswith(excluded + b"/")
        for excluded in exclusions
    )

def _git_oid(value: str | None, name: str) -> str | None:
    if value is None: return None
    if len(value) not in {40, 64} or any(c not in "0123456789abcdef" for c in value): raise SnapshotError(f"{name} must be a Git object id")
    return value

def _oid_map(value: Mapping[str, str] | Sequence[tuple[str, str]] | None) -> tuple[tuple[str, str], ...]:
    if value is None: return ()
    try: pairs = value.items() if isinstance(value, Mapping) else value
    except AttributeError as exc: raise SnapshotError("index_blob_oids must be a mapping") from exc
    try: result = tuple(sorted((str(key), _git_oid(item, "index blob oid") or "") for key, item in pairs))
    except (TypeError, ValueError) as exc: raise SnapshotError("index_blob_oids must be a mapping") from exc
    if any(key not in {"1", "2", "3"} or not oid for key, oid in result) or len({key for key, _ in result}) != len(result): raise SnapshotError("index_blob_oids must contain stages 1, 2, or 3")
    return result

@dataclass(frozen=True, slots=True)
class SnapshotEntry:
    path: str; kind: str; size_bytes: int | None; source_cid: str | None = None; opaque_reason: str | None = None; raw_path_hex: str | None = None
    git_blob_oid: str | None = None; acquisition: str = "captured"; disposition: str = "working"
    head_blob_oid: str | None = None; index_blob_oids: Mapping[str, str] | None = None
    captured_bytes: bytes | None = field(default=None, compare=False, repr=False)
    witness: tuple[int, int, int, int, int] | None = field(default=None, compare=False, repr=False)
    def __post_init__(self) -> None:
        raw = self.raw_path_hex or _raw_hex(self.path)
        try: raw_bytes = bytes.fromhex(raw)
        except ValueError as exc: raise SnapshotError("raw_path_hex must be hexadecimal") from exc
        if raw_bytes.hex() != raw: raise SnapshotError("raw_path_hex must be canonical hexadecimal")
        safe = _safe_raw_path(raw_bytes)
        expected = safe if safe is not None else _UNSAFE_PREFIX + raw
        if self.path != expected: raise SnapshotError("path must bind exactly to raw_path_hex")
        object.__setattr__(self, "path", _path(self.path)); object.__setattr__(self, "raw_path_hex", raw)
        object.__setattr__(self, "kind", _text(self.kind, "kind")); object.__setattr__(self, "git_blob_oid", _git_oid(self.git_blob_oid, "git_blob_oid")); object.__setattr__(self, "head_blob_oid", _git_oid(self.head_blob_oid, "head_blob_oid"))
        object.__setattr__(self, "index_blob_oids", _oid_map(self.index_blob_oids))
        if self.size_bytes is not None and (type(self.size_bytes) is not int or self.size_bytes < 0): raise SnapshotError("size_bytes must be nonnegative or None")
        if self.source_cid is not None:
            try: validate_cid(self.source_cid)
            except Exception as exc: raise SnapshotError("source_cid must be valid") from exc
        if self.opaque_reason is not None:
            object.__setattr__(self, "opaque_reason", _text(self.opaque_reason, "opaque_reason"))
            if self.kind != "opaque": raise SnapshotError("opaque entries must have kind opaque")
        elif self.source_cid is None: raise SnapshotError("non-opaque entries require source_cid")
        if self.acquisition not in {"captured", "git-object", "working-captured", "opaque"}: raise SnapshotError("unsupported acquisition")
        if self.disposition not in {"clean", "working", "tracked_modified", "staged_added", "staged_modified", "staged_deleted", "unstaged_deleted", "untracked", "conflicted", "unborn", "filesystem", "opaque"}: raise SnapshotError("unsupported disposition")
        if self.captured_bytes is not None and (type(self.captured_bytes) is not bytes or self.source_cid != cid_for_bytes(self.captured_bytes)): raise SnapshotError("captured bytes do not verify source_cid")
    @property
    def is_opaque(self) -> bool: return self.opaque_reason is not None
    @property
    def source_key(self) -> str: return "raw:" + (self.raw_path_hex or "")
    def identity_payload(self) -> dict[str, Any]:
        return {"schema": SNAPSHOT_ENTRY_SCHEMA, "path": self.path, "raw_path_hex": self.raw_path_hex, "kind": self.kind, "size_bytes": self.size_bytes, "source_cid": self.source_cid, "opaque_reason": self.opaque_reason, "git_blob_oid": self.git_blob_oid, "acquisition": self.acquisition, "disposition": self.disposition, "head_blob_oid": self.head_blob_oid, "index_blob_oids": dict(self.index_blob_oids or ())}
    @property
    def entry_cid(self) -> str: return cid_for_structured(self.identity_payload())
    def to_dict(self) -> dict[str, Any]: return {**self.identity_payload(), "entry_cid": self.entry_cid}
    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SnapshotEntry":
        fields = set(cls("x", "artifact", 0, cid_for_bytes(b"")).identity_payload()) | {"entry_cid"}
        if set(value) != fields or value.get("schema") != SNAPSHOT_ENTRY_SCHEMA: raise SnapshotError("unsupported SnapshotEntry schema")
        result = cls(**{key: value[key] for key in fields - {"schema", "entry_cid"}})
        if value["entry_cid"] != result.entry_cid: raise SnapshotError("SnapshotEntry entry_cid does not verify")
        return result

@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    repository_id: str; entries: Sequence[SnapshotEntry]; mode: str; max_file_bytes: int = DEFAULT_MAX_FILE_BYTES; max_entries: int = DEFAULT_MAX_ENTRIES; git_tree: str | None = None; git_commit: str | None = None; exclusions: Sequence[str] = ()
    def __post_init__(self) -> None:
        object.__setattr__(self, "repository_id", _text(self.repository_id, "repository_id"))
        if self.mode not in {"git-clean", "git-working", "git-unborn", "filesystem"}: raise SnapshotError("unsupported snapshot mode")
        object.__setattr__(self, "git_tree", _git_oid(self.git_tree, "git_tree")); object.__setattr__(self, "git_commit", _git_oid(self.git_commit, "git_commit"))
        if self.mode in {"git-clean", "git-working"} and (self.git_tree is None or self.git_commit is None): raise SnapshotError("committed Git snapshots require commit and tree")
        if type(self.max_file_bytes) is not int or self.max_file_bytes < 1 or type(self.max_entries) is not int or self.max_entries < 1: raise SnapshotError("invalid limits")
        if any(not isinstance(e, SnapshotEntry) for e in self.entries): raise SnapshotError("entries must be SnapshotEntry records")
        entries = tuple(sorted(self.entries, key=lambda e: e.raw_path_hex or ""))
        if len(entries) > self.max_entries or len({e.raw_path_hex for e in entries}) != len(entries): raise SnapshotError("invalid selected entries")
        object.__setattr__(self, "entries", entries); object.__setattr__(self, "exclusions", tuple(sorted(_text(x, "exclusion") for x in self.exclusions)))
    def identity_payload(self) -> dict[str, Any]:
        return {"schema": SNAPSHOT_SCHEMA, "repository_id": self.repository_id, "entries": [e.to_dict() for e in self.entries], "mode": self.mode, "max_file_bytes": self.max_file_bytes, "max_entries": self.max_entries, "git_tree": self.git_tree, "git_commit": self.git_commit, "exclusions": list(self.exclusions)}
    @property
    def snapshot_cid(self) -> str: return cid_for_structured(self.identity_payload())
    def to_dict(self) -> dict[str, Any]: return {**self.identity_payload(), "snapshot_cid": self.snapshot_cid}
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
    except OSError as exc: raise GitSnapshotError("git execution failed") from exc
def _not_git(result: subprocess.CompletedProcess[bytes]) -> bool: return b"not a git repository" in result.stderr.lower()
def _require_git(root: Path, args: Sequence[str], what: str) -> bytes:
    result = _git(root, args)
    if result.returncode or result.stderr: raise GitSnapshotError(f"git {what} failed or warned")
    return result.stdout
def _ascii_oid(raw: bytes, what: str) -> str:
    try: value = raw.decode("ascii", "strict").strip()
    except UnicodeDecodeError as exc: raise GitSnapshotError(f"git {what} was not ASCII") from exc
    try: return _git_oid(value, what) or ""
    except SnapshotError as exc: raise GitSnapshotError(f"git {what} was malformed") from exc
def _git_root(root: Path) -> Path | None:
    result = _git(root, ("rev-parse", "--show-toplevel"))
    if result.returncode:
        # A broken .git marker is not permission to silently downgrade to a
        # filesystem snapshot.  It claims Git authority but cannot establish
        # it, so surface a typed acquisition failure instead.
        if _not_git(result) and not os.path.lexists(root / ".git"): return None
        raise GitSnapshotError("git repository discovery failed")
    if result.stderr: raise GitSnapshotError("git repository discovery warned")
    try: text = result.stdout.decode("utf-8", "strict").strip()
    except UnicodeDecodeError as exc: raise GitSnapshotError("git root was not UTF-8") from exc
    if not text: raise GitSnapshotError("git root was empty")
    return Path(text).resolve()

def _unborn_head_ref(root: Path) -> str:
    """Return a validated symbolic HEAD, rejecting a contradictory born HEAD."""
    symbolic = _git(root, ("symbolic-ref", "-q", "HEAD"))
    if symbolic.returncode or symbolic.stderr or not symbolic.stdout.strip():
        raise GitSnapshotError("git HEAD discovery failed")
    try:
        head_ref = symbolic.stdout.decode("ascii", "strict").strip()
    except UnicodeDecodeError as exc:
        raise GitSnapshotError("git symbolic HEAD was not ASCII") from exc
    if not head_ref:
        raise GitSnapshotError("git symbolic HEAD was empty")
    # A successful history lookup means the preceding quiet HEAD lookup was
    # inconsistent, not that this is an unborn repository.
    history = _git(root, ("rev-list", "--max-count=1", "HEAD"))
    if history.returncode == 0:
        raise GitSnapshotError("git HEAD discovery was inconsistent")
    if history.returncode not in {0, 128}:
        raise GitSnapshotError("git unborn HEAD verification failed")
    return head_ref

def _captured_head(root: Path) -> tuple[str | None, str | None]:
    """Capture one HEAD generation, returning ``(commit, unborn_ref)``.

    Git has no single command that gives both the unborn state and the
    symbolic ref.  Re-checking the quiet lookup after the symbolic/history
    proof makes that compound observation fail closed if a first commit lands
    in between.  Callers which subsequently acquire an unborn inventory must
    fence with this helper again before returning it.
    """
    head = _git(root, ("rev-parse", "--verify", "--quiet", "HEAD"))
    if not head.returncode:
        if head.stderr:
            raise GitSnapshotError("git HEAD discovery warned")
        return _ascii_oid(head.stdout, "HEAD"), None
    if head.returncode != 1 or head.stderr:
        raise GitSnapshotError("git HEAD discovery failed")
    head_ref = _unborn_head_ref(root)
    fence = _git(root, ("rev-parse", "--verify", "--quiet", "HEAD"))
    if not fence.returncode or fence.returncode != 1 or fence.stderr:
        raise GitSnapshotError("git HEAD generation changed during capture")
    return None, head_ref

def _git_dir(root: Path) -> Path:
    """Resolve Git's metadata directory, including linked worktrees."""
    raw = _require_git(root, ("rev-parse", "--git-dir"), "git-dir")
    try:
        rendered = raw.decode("utf-8", "strict").strip()
    except UnicodeDecodeError as exc:
        raise GitSnapshotError("git directory was not UTF-8") from exc
    if not rendered:
        raise GitSnapshotError("git directory was empty")
    candidate = Path(rendered)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise GitSnapshotError("git directory was unavailable") from exc
    if not resolved.is_dir():
        raise GitSnapshotError("git directory was not a directory")
    return resolved

def _unborn_temp_prefix(marker_name: str) -> str:
    return f".{marker_name}.tmp-"


def _raise_git_snapshot(message: str, *failures: BaseException) -> None:
    """Raise ``GitSnapshotError``, retaining every linked diagnostic."""
    retained = [item for item in failures if isinstance(item, BaseException)]
    if not retained:
        raise GitSnapshotError(message)
    if len(retained) == 1:
        raise GitSnapshotError(message) from retained[0]
    raise GitSnapshotError(message) from ExceptionGroup(message, retained)


def _close_descriptor(descriptor: int) -> None:
    os.close(descriptor)


def _sync_metadata_directory(directory: Path) -> None:
    """Make directory entry mutations durable via an explicit directory fsync."""
    try:
        descriptor = os.open(directory, os.O_RDONLY | _O_DIRECTORY)
    except OSError as exc:
        _raise_git_snapshot("unborn repository identity directory could not be synchronized", exc)
        return
    sync_error: BaseException | None = None
    try:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            sync_error = exc
    finally:
        try:
            _close_descriptor(descriptor)
        except OSError as exc:
            if sync_error is not None:
                _raise_git_snapshot(
                    "unborn repository identity directory could not be synchronized",
                    sync_error,
                    exc,
                )
            _raise_git_snapshot(
                "unborn repository identity directory could not be synchronized",
                exc,
            )
    if sync_error is not None:
        _raise_git_snapshot("unborn repository identity directory could not be synchronized", sync_error)


def _token_from_bytes(value: bytes) -> str:
    try:
        token = value.decode("ascii", "strict")
    except UnicodeDecodeError as exc:
        raise GitSnapshotError("unborn repository identity was malformed") from exc
    if len(token) != _UNBORN_TOKEN_HEX_LEN or any(char not in "0123456789abcdef" for char in token):
        raise GitSnapshotError("unborn repository identity was malformed")
    return token


def _validate_private_regular(descriptor: int) -> None:
    try:
        info = os.fstat(descriptor)
    except OSError as exc:
        raise GitSnapshotError("unborn repository identity was unreadable") from exc
    if not stat.S_ISREG(info.st_mode):
        raise GitSnapshotError("unborn repository identity was not a private regular file")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise GitSnapshotError("unborn repository identity was not a private regular file")


def _read_token_from_descriptor(descriptor: int) -> str:
    _validate_private_regular(descriptor)
    try:
        value = os.read(descriptor, _UNBORN_TOKEN_HEX_LEN + 1)
    except OSError as exc:
        raise GitSnapshotError("unborn repository identity was unreadable") from exc
    return _token_from_bytes(value)


def _open_unborn_path(path: Path, flags: int, mode: int = 0o600) -> int:
    """Open a final or temporary marker without following or blocking."""
    open_flags = flags | _O_NOFOLLOW | _O_NONBLOCK
    try:
        if flags & os.O_CREAT:
            return os.open(path, open_flags, mode)
        return os.open(path, open_flags)
    except FileExistsError:
        raise
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise GitSnapshotError("unborn repository identity was unreadable") from exc


def _read_final_unborn_token(metadata: Path) -> str | None:
    """Return a validated final token, or ``None`` when the final path is absent."""
    try:
        descriptor = _open_unborn_path(metadata, os.O_RDONLY)
    except FileNotFoundError:
        return None
    except GitSnapshotError:
        raise
    try:
        return _read_token_from_descriptor(descriptor)
    finally:
        try:
            _close_descriptor(descriptor)
        except OSError as exc:
            raise GitSnapshotError("unborn repository identity was unreadable") from exc


def _try_lock_exclusive(descriptor: int) -> bool:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    except OSError as exc:
        raise GitSnapshotError("unborn repository identity cleanup failed") from exc
    return True


def _unlink_path(path: Path) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise GitSnapshotError("unborn repository identity cleanup failed") from exc


def _inspect_and_reap_candidate(path: Path) -> str:
    """Inspect one marker-derived temporary.

    Returns ``"reaped"``, ``"live"``, or ``"absent"``. A non-blocking exclusive
    lock distinguishes a cooperating live publisher (lock held) from crash
    residue (lock available). Unsafe residue fails typed rather than skipped.
    """
    try:
        descriptor = _open_unborn_path(path, os.O_RDWR)
    except FileNotFoundError:
        return "absent"
    close_error: BaseException | None = None
    try:
        _validate_private_regular(descriptor)
        try:
            # Consume evidence through the descriptor; content validity does not
            # change reaping once the exclusive lock is available.
            os.read(descriptor, _UNBORN_TOKEN_HEX_LEN + 1)
        except OSError as exc:
            raise GitSnapshotError("unborn repository identity was unreadable") from exc
        if not _try_lock_exclusive(descriptor):
            return "live"
    finally:
        try:
            _close_descriptor(descriptor)
        except OSError as exc:
            close_error = exc
    if close_error is not None:
        raise GitSnapshotError("unborn repository identity cleanup failed") from close_error
    _unlink_path(path)
    return "reaped"


def _cleanup_unborn_candidates(directory: Path, marker_name: str) -> None:
    """Boundedly discover and clean marker-derived temporaries.

    Discovery/inspection and marker-derived mutation are each capped at
    ``_UNBORN_CLEANUP_BOUND`` per public call. Unsafe, nonprivate, or unreadable
    residue fails typed. Every successful unlink batch is followed by a
    metadata-directory sync before return or typed failure.
    """
    prefix = _unborn_temp_prefix(marker_name)
    inspected = 0
    mutations = 0
    reaped_any = False
    hit_bound = False
    fatal: BaseException | None = None
    try:
        with os.scandir(directory) as entries:
            iterator = iter(entries)
            while True:
                # Do not request another entry once the discovery budget is spent;
                # a for-loop would otherwise materialize entry 257 before the check.
                if inspected >= _UNBORN_CLEANUP_BOUND:
                    hit_bound = True
                    break
                if mutations >= _UNBORN_CLEANUP_BOUND:
                    hit_bound = True
                    break
                try:
                    entry = next(iterator)
                except StopIteration:
                    break
                inspected += 1
                if not entry.name.startswith(prefix):
                    continue
                outcome = _inspect_and_reap_candidate(Path(entry.path))
                if outcome == "reaped":
                    mutations += 1
                    reaped_any = True
    except GitSnapshotError as exc:
        fatal = exc
    except OSError as exc:
        fatal = GitSnapshotError("unborn repository identity cleanup failed")
        fatal.__cause__ = exc
    if reaped_any:
        try:
            _sync_metadata_directory(directory)
        except GitSnapshotError as exc:
            if fatal is None:
                fatal = exc
            else:
                _raise_git_snapshot("unborn repository identity cleanup failed", fatal, exc)
    if fatal is not None:
        if isinstance(fatal, GitSnapshotError):
            raise fatal
        raise GitSnapshotError("unborn repository identity cleanup failed") from fatal
    if hit_bound:
        raise GitSnapshotError("unborn repository identity cleanup made only bounded progress")


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        try:
            written = os.write(descriptor, view)
        except OSError as exc:
            raise GitSnapshotError("unborn repository identity could not be stored") from exc
        if written <= 0:
            raise GitSnapshotError("unborn repository identity could not be stored")
        view = view[written:]


def _cleanup_failed_candidate(
    directory: Path,
    candidate: Path,
    failures: list[BaseException],
    message: str,
) -> None:
    """Unlink a prepublication candidate, sync the directory, then raise if needed."""
    try:
        _unlink_path(candidate)
    except GitSnapshotError as exc:
        failures.append(exc)
        _raise_git_snapshot(message, *failures)
    try:
        _sync_metadata_directory(directory)
    except GitSnapshotError as exc:
        failures.append(exc)
        _raise_git_snapshot(message, *failures)
    if failures:
        _raise_git_snapshot(message, *failures)


def _publish_unborn_candidate(directory: Path, metadata: Path, token: str) -> bool:
    """Write a private candidate and no-replace publish it.

    Returns True when this caller installed the final marker, False when another
    durable winner already won the race. Own candidate residue is always cleaned
    with a following metadata-directory sync, or a typed cleanup failure is raised.
    """
    payload = token.encode("ascii")
    failures: list[BaseException] = []
    candidate: Path | None = None
    descriptor: int | None = None
    published = False

    for _attempt in range(8):
        suffix = os.urandom(8).hex()
        path = directory / f"{_unborn_temp_prefix(metadata.name)}{suffix}"
        try:
            descriptor = _open_unborn_path(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            candidate = path
            break
        except FileExistsError:
            continue
        except GitSnapshotError as exc:
            failures.append(exc)
            break
    if descriptor is None or candidate is None:
        if failures:
            _raise_git_snapshot("unborn repository identity could not be created", *failures)
        raise GitSnapshotError("unborn repository identity could not be created")

    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError as exc:
            failures.append(exc)
            raise
        try:
            _write_all(descriptor, payload)
        except GitSnapshotError as exc:
            failures.append(exc.__cause__ or exc)
            raise
        try:
            os.fsync(descriptor)
        except OSError as exc:
            failures.append(exc)
            raise
        try:
            os.link(candidate, metadata)
            published = True
        except FileExistsError:
            published = False
        except OSError as exc:
            failures.append(exc)
            raise
    except (GitSnapshotError, OSError, Exception):
        # Close before cleanup so flock is released; retain close diagnostics.
        close_error: BaseException | None = None
        try:
            _close_descriptor(descriptor)
        except OSError as exc:
            close_error = exc
        descriptor = None
        if close_error is not None:
            failures.append(close_error)
        assert candidate is not None
        _cleanup_failed_candidate(
            directory,
            candidate,
            failures,
            "unborn repository identity could not be stored",
        )
        return False
    else:
        close_error = None
        try:
            _close_descriptor(descriptor)
        except OSError as exc:
            close_error = exc
        descriptor = None
        if close_error is not None:
            failures.append(close_error)
            assert candidate is not None
            if published:
                try:
                    _sync_metadata_directory(directory)
                    _unlink_path(candidate)
                    _sync_metadata_directory(directory)
                except GitSnapshotError as exc:
                    failures.append(exc)
                _raise_git_snapshot(
                    "unborn repository identity could not be stored",
                    *failures,
                )
            _cleanup_failed_candidate(
                directory,
                candidate,
                failures,
                "unborn repository identity could not be stored",
            )
            return False

    assert candidate is not None
    if not published:
        _cleanup_failed_candidate(
            directory,
            candidate,
            failures,
            "unborn repository identity could not be stored",
        )
        return False

    # Winner: durable publication, then candidate unlink, then post-cleanup sync.
    _sync_metadata_directory(directory)
    _unlink_path(candidate)
    _sync_metadata_directory(directory)
    return True


def _unborn_bootstrap_token(root: Path) -> str:
    """Return a move-stable, locally generated identity seed for an unborn Git repo.

    Publication is candidate-then-no-replace-link: the final path is never
    visible with partial or unflushed bytes. Concurrent losers reread the
    durable winner; crash residue is cleaned with bounded discovery/mutation
    and live cooperating candidates are not reaped.
    """
    directory = _git_dir(root)
    metadata = directory / _UNBORN_ID_FILE

    existing = _read_final_unborn_token(metadata)
    if existing is not None:
        # Final visibility is not durability: re-establish directory durability
        # before returning, then clean stale candidates with pre/post sync order.
        _sync_metadata_directory(directory)
        _cleanup_unborn_candidates(directory, metadata.name)
        confirmed = _read_final_unborn_token(metadata)
        if confirmed is None:
            raise GitSnapshotError("unborn repository identity was unreadable")
        return confirmed

    # Remove crash residue; flock keeps cooperating live candidates alive.
    _cleanup_unborn_candidates(directory, metadata.name)

    try:
        token = os.urandom(_UNBORN_ID_BYTES).hex()
    except OSError as exc:
        raise GitSnapshotError("unborn repository identity could not be created") from exc

    _publish_unborn_candidate(directory, metadata, token)

    winner = _read_final_unborn_token(metadata)
    if winner is None:
        raise GitSnapshotError("unborn repository identity was unreadable")
    # Losers re-establish durability before return; winners already synced.
    _sync_metadata_directory(directory)
    _cleanup_unborn_candidates(directory, metadata.name)
    confirmed = _read_final_unborn_token(metadata)
    if confirmed is None:
        raise GitSnapshotError("unborn repository identity was unreadable")
    return confirmed

def _identity_for_captured_head(root: Path, commit: str | None, unborn_ref: str | None) -> str:
    if commit is None:
        if unborn_ref is None:
            raise GitSnapshotError("git HEAD capture was incomplete")
        return cid_for_structured({
            "schema": REPOSITORY_ID_SCHEMA,
            "kind": "git-unborn",
            "head_ref": unborn_ref,
            "bootstrap": _unborn_bootstrap_token(root),
        })
    roots = _require_git(root, ("rev-list", "--max-parents=0", "--reverse", commit), "root-history").splitlines()
    if not roots:
        raise GitSnapshotError("git root history was empty")
    try:
        object_format = _require_git(root, ("rev-parse", "--show-object-format"), "object-format").decode("ascii", "strict").strip()
    except UnicodeDecodeError as exc:
        raise GitSnapshotError("git object format was not ASCII") from exc
    if object_format not in {"sha1", "sha256"}:
        raise GitSnapshotError("git object format was malformed")
    return cid_for_structured({"schema": REPOSITORY_ID_SCHEMA, "kind": "git", "root_commits": sorted(_ascii_oid(item, "root commit") for item in roots), "object_format": object_format})

def repository_identity(repository: str | os.PathLike[str], *, repository_id: str | None = None) -> str:
    if repository_id is not None: return _text(repository_id, "repository_id")
    root = Path(repository).resolve(); git_root = _git_root(root)
    if git_root is None: return cid_for_structured({"schema": REPOSITORY_ID_SCHEMA, "kind": "filesystem", "path": str(root)})
    commit, unborn_ref = _captured_head(git_root)
    return _identity_for_captured_head(git_root, commit, unborn_ref)

def _kind(path: str) -> str:
    name = posixpath.basename(path).lower(); suffix = posixpath.splitext(name)[1]
    if suffix in {".py", ".pyi"}: return "python"
    if name in _PYTEST_CONFIG_NAMES or name == "pyproject.toml": return "pytest-config"
    if name in _LOCK_NAMES: return "dependency-lock"
    if suffix in _SCHEMA_SUFFIXES: return "schema"
    return "artifact"
def _opaque(path: str, reason: str, size: int | None = None, source_cid: str | None = None, *, raw: bytes | None = None, oid: str | None = None, disposition: str = "opaque", head_oid: str | None = None, index_oids: Mapping[str, str] | None = None) -> SnapshotEntry:
    return SnapshotEntry(path, "opaque", size, source_cid, reason, (raw or os.fsencode(path)).hex(), oid, "opaque", disposition, head_oid, index_oids)
def _entry(path: str, raw: bytes, data: bytes, max_file_bytes: int, oid: str | None = None, witness: tuple[int, int, int, int, int] | None = None, disposition: str = "working", head_oid: str | None = None, index_oids: Mapping[str, str] | None = None, acquisition: str = "working-captured") -> SnapshotEntry:
    if len(data) > max_file_bytes: return _opaque(path, "oversized", len(data), raw=raw, oid=oid, disposition=disposition, head_oid=head_oid, index_oids=index_oids)
    try: data.decode("utf-8", "strict")
    except UnicodeDecodeError: return _opaque(path, "undecodable", len(data), cid_for_bytes(data), raw=raw, oid=oid, disposition=disposition, head_oid=head_oid, index_oids=index_oids)
    return SnapshotEntry(path, _kind(path), len(data), cid_for_bytes(data), None, raw.hex(), oid, acquisition, disposition, head_oid, index_oids, data, witness)
def _working_entry(root: Path, raw: bytes, max_file_bytes: int, **evidence: Any) -> SnapshotEntry:
    path = _raw_display(raw)
    if _malformed_raw(raw): return _opaque(path, "malformed_path", raw=raw, **evidence)
    candidate = root / os.fsdecode(raw)
    try:
        before = candidate.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode): return _opaque(path, "symlink_or_nonregular", before.st_size, raw=raw, **evidence)
        if before.st_size > max_file_bytes: return _opaque(path, "oversized", before.st_size, raw=raw, **evidence)
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None: return _opaque(path, "symlink_or_nonregular", before.st_size, raw=raw, **evidence)
        fd = os.open(candidate, os.O_RDONLY | nofollow)
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode): return _opaque(path, "symlink_or_nonregular", before.st_size, raw=raw, **evidence)
            data = handle.read(max_file_bytes + 1)
        after = candidate.stat(follow_symlinks=False)
    except FileNotFoundError: return _opaque(path, "missing", raw=raw, **evidence)
    except OSError: return _opaque(path, "unreadable", raw=raw, **evidence)
    witness = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    if witness != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns): return _opaque(path, "raced", after.st_size, raw=raw, **evidence)
    return _entry(path, raw, data, max_file_bytes, witness=witness, **evidence)

def _tree_oids(root: Path, tree: str, exclusions: Sequence[bytes]) -> dict[bytes, str]:
    result: dict[bytes, str] = {}
    for record in _require_git(root, ("ls-tree", "-r", "-z", tree), "ls-tree").split(b"\0"):
        if not record: continue
        try: meta, raw = record.split(b"\t", 1); mode, typ, oid = meta.decode("ascii").split()
        except ValueError as exc: raise GitSnapshotError("git tree record was malformed") from exc
        if not _ignored_raw(raw, exclusions) and typ == "blob": result[raw] = _git_oid(oid, "tree blob") or ""
    return result
def _clean_entries(root: Path, tree: str, max_file_bytes: int, max_entries: int, exclusions: Sequence[bytes]) -> Iterable[SnapshotEntry]:
    selected: list[tuple[str, str, str, bytes]] = []
    for record in _require_git(root, ("ls-tree", "-r", "-z", tree), "ls-tree").split(b"\0"):
        if not record: continue
        try: meta, raw = record.split(b"\t", 1); mode, typ, oid = meta.decode("ascii").split()
        except ValueError as exc: raise GitSnapshotError("git tree record was malformed") from exc
        if not _ignored_raw(raw, exclusions): selected.append((mode, typ, _git_oid(oid, "tree blob") or "", raw))
    if len(selected) > max_entries: raise SnapshotError("selected entries exceed max_entries")
    for mode, typ, oid, raw in sorted(selected, key=lambda item: item[3]):
        path = _raw_display(raw)
        if _malformed_raw(raw): yield _opaque(path, "malformed_path", raw=raw, oid=oid, disposition="clean", head_oid=oid); continue
        if mode == "120000" or typ != "blob": yield _opaque(path, "symlink_or_nonregular", raw=raw, oid=oid, disposition="clean", head_oid=oid); continue
        size_text = _require_git(root, ("cat-file", "-s", oid), "blob size")
        try: size = int(size_text.strip())
        except ValueError as exc: raise GitSnapshotError("git blob size was malformed") from exc
        if size > max_file_bytes: yield _opaque(path, "oversized", size, raw=raw, oid=oid, disposition="clean", head_oid=oid); continue
        data = _require_git(root, ("cat-file", "blob", oid), "blob")
        yield _entry(path, raw, data, max_file_bytes, oid, disposition="clean", head_oid=oid, acquisition="git-object")
def _working_paths(root: Path, exclusions: Sequence[bytes]) -> set[bytes]:
    return {p for p in _require_git(root, ("ls-files", "-z", "--cached", "--others", "--exclude-standard"), "ls-files").split(b"\0") if p and not _ignored_raw(p, exclusions)}
def _index_oids(root: Path, exclusions: Sequence[bytes]) -> dict[bytes, dict[str, str]]:
    result: dict[bytes, dict[str, str]] = {}
    for record in _require_git(root, ("ls-files", "--stage", "-z"), "index").split(b"\0"):
        if not record: continue
        try: meta, raw = record.split(b"\t", 1); _mode, oid, stage = meta.decode("ascii").split()
        except ValueError as exc: raise GitSnapshotError("git index record was malformed") from exc
        if not _ignored_raw(raw, exclusions): result.setdefault(raw, {})[stage] = _git_oid(oid, "index blob") or ""
    return result
def _status(root: Path) -> dict[bytes, bytes]:
    records = [r for r in _require_git(root, ("status", "--porcelain", "-z", "--untracked-files=all"), "status").split(b"\0") if r]
    result: dict[bytes, bytes] = {}; index = 0
    while index < len(records):
        record = records[index]; index += 1
        if len(record) < 4: raise GitSnapshotError("git status record was malformed")
        code, raw = record[:2], record[3:]; result[raw] = code
        if code[:1] in {b"R", b"C"}:
            if index >= len(records): raise GitSnapshotError("git status rename record was incomplete")
            result[records[index]] = code; index += 1
    return result
def _disposition(code: bytes | None, in_index: bool, head_oid: str | None, stages: Mapping[str, str]) -> str:
    if stages and set(stages) != {"0"}: return "conflicted"
    if code is None: return "working" if in_index else "untracked"
    x, y = code[:1], code[1:2]
    if x == b"D": return "staged_deleted"
    if y == b"D": return "unstaged_deleted"
    if x == b"A": return "staged_added"
    if x in {b"M", b"R", b"C"}: return "staged_modified"
    if y in {b"M", b"R", b"C"}: return "tracked_modified"
    return "working" if in_index else "untracked"

def _unborn_entry_evidence(item: SnapshotEntry, index: Mapping[bytes, Mapping[str, str]], status: Mapping[bytes, bytes]) -> SnapshotEntry:
    raw = bytes.fromhex(item.raw_path_hex or "")
    stages = index.get(raw, {})
    disposition = _disposition(status.get(raw), raw in index, None, stages)
    # A wholly empty index is a bootstrap inventory.  Once staged content
    # exists, retain the meaningful untracked distinction for other paths.
    if disposition == "untracked" and not index:
        disposition = "unborn"
    return replace(item, git_blob_oid=stages.get("0"), index_blob_oids={key: value for key, value in stages.items() if key in {"1", "2", "3"}}, disposition=disposition if not item.is_opaque else item.disposition)

def _filesystem_entries(root: Path, max_file_bytes: int, max_entries: int, exclusions: Sequence[bytes]) -> list[SnapshotEntry]:
    result: list[SnapshotEntry] = []; stack = [root]
    while stack:
        directory = stack.pop()
        try: children = sorted(list(os.scandir(directory)), key=lambda x: os.fsencode(x.name))
        except OSError:
            if directory != root:
                raw = os.fsencode(str(directory.relative_to(root))); result.append(_opaque(_raw_display(raw), "unreadable_directory", raw=raw, disposition="filesystem"))
            continue
        for child in children:
            raw = os.fsencode(str(Path(child.path).relative_to(root)))
            if _ignored_raw(raw, exclusions): continue
            try:
                if child.is_dir(follow_symlinks=False): stack.append(Path(child.path))
                else: result.append(_working_entry(root, raw, max_file_bytes, disposition="filesystem"))
            except OSError: result.append(_opaque(_raw_display(raw), "unreadable", raw=raw, disposition="filesystem"))
            if len(result) > max_entries: raise SnapshotError("selected entries exceed max_entries")
    return result

def snapshot_repository(repository: str | os.PathLike[str], *, repository_id: str | None = None, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES, max_entries: int = DEFAULT_MAX_ENTRIES, exclusions: Iterable[str] | None = None) -> RepositorySnapshot:
    if type(max_file_bytes) is not int or max_file_bytes < 1 or type(max_entries) is not int or max_entries < 1: raise SnapshotError("invalid limits")
    root = Path(repository).resolve()
    if not root.is_dir(): raise SnapshotError("repository must be an existing directory")
    raw_exclusions = _exclusion_raw(exclusions); rendered_exclusions = tuple(item.decode("utf-8", "strict") for item in raw_exclusions)
    git_root = _git_root(root)
    if git_root is None:
        identity = _text(repository_id, "repository_id") if repository_id is not None else cid_for_structured({"schema": REPOSITORY_ID_SCHEMA, "kind": "filesystem", "path": str(root)})
        return RepositorySnapshot(identity, _filesystem_entries(root, max_file_bytes, max_entries, raw_exclusions), "filesystem", max_file_bytes, max_entries, exclusions=rendered_exclusions)
    commit, unborn_ref = _captured_head(git_root)
    identity = _text(repository_id, "repository_id") if repository_id is not None else _identity_for_captured_head(git_root, commit, unborn_ref)
    if commit is None:
        entries = _filesystem_entries(git_root, max_file_bytes, max_entries, raw_exclusions)
        index = _index_oids(git_root, raw_exclusions)
        status = _status(git_root)
        fence_commit, fence_ref = _captured_head(git_root)
        if fence_commit is not None or fence_ref != unborn_ref:
            raise GitSnapshotError("git generation changed during snapshot")
        entries = tuple(_unborn_entry_evidence(item, index, status) for item in entries)
        return RepositorySnapshot(identity, entries, "git-unborn", max_file_bytes, max_entries, exclusions=rendered_exclusions)
    tree = _ascii_oid(_require_git(git_root, ("rev-parse", f"{commit}^{{tree}}"), "commit tree"), "commit tree")
    status = _status(git_root); index = _index_oids(git_root, raw_exclusions); head_oids = _tree_oids(git_root, tree, raw_exclusions)
    selected_status = {raw: code for raw, code in status.items() if not _ignored_raw(raw, raw_exclusions)}
    if not selected_status:
        entries = tuple(_clean_entries(git_root, tree, max_file_bytes, max_entries, raw_exclusions)); mode = "git-clean"
    else:
        paths = _working_paths(git_root, raw_exclusions) | set(index) | set(head_oids) | set(selected_status)
        if len(paths) > max_entries: raise SnapshotError("selected entries exceed max_entries")
        entries_list: list[SnapshotEntry] = []
        for raw in sorted(paths):
            stages = index.get(raw, {}); code = selected_status.get(raw); disposition = _disposition(code, raw in index, head_oids.get(raw), stages)
            evidence = {"oid": stages.get("0"), "disposition": disposition, "head_oid": head_oids.get(raw), "index_oids": {key: value for key, value in stages.items() if key in {"1", "2", "3"}}}
            if disposition in {"staged_deleted", "unstaged_deleted", "conflicted"}:
                entries_list.append(_opaque(_raw_display(raw), disposition, raw=raw, **evidence))
            else: entries_list.append(_working_entry(git_root, raw, max_file_bytes, **evidence))
        entries = tuple(entries_list); mode = "git-working"
    # Fence status/index/blob acquisition against a moving HEAD.  The selected
    # commit remains tied to its own tree even when this reports a race.
    # The commit alone is insufficient: status and index can change while
    # HEAD remains fixed.  Re-observe both raw records to close that race.
    if _status(git_root) != status or _index_oids(git_root, raw_exclusions) != index:
        raise GitSnapshotError("git working generation changed during snapshot")
    if _ascii_oid(_require_git(git_root, ("rev-parse", "--verify", "HEAD"), "HEAD fence"), "HEAD fence") != commit: raise GitSnapshotError("git generation changed during snapshot")
    return RepositorySnapshot(identity, entries, mode, max_file_bytes, max_entries, tree, commit, rendered_exclusions)

__all__ = ["DEFAULT_MAX_ENTRIES", "DEFAULT_MAX_FILE_BYTES", "GIT_COMMAND_TIMEOUT_SECONDS", "GitCommandTimeout", "GitSnapshotError", "GitUnbornRepository", "RepositorySnapshot", "SNAPSHOT_ENTRY_SCHEMA", "SNAPSHOT_SCHEMA", "SnapshotEntry", "SnapshotError", "repository_identity", "snapshot_repository"]
