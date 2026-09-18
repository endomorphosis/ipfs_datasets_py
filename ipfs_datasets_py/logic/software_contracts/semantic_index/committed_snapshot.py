"""Explicit complete committed populations with bounded metadata preflight.

Unlike ordinary filtered snapshots, these APIs include every committed path.
They never traverse the working filesystem to discover input files. Preflight
reads Git metadata only; acquisition retains the existing in-memory snapshot
representation and therefore refuses unqualified per-file/aggregate budgets.
Neither a population digest nor a snapshot grants semantic acceptance authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time
from typing import Any

from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
from .snapshot import (
    DEFAULT_MAX_ENTRIES, DEFAULT_MAX_FILE_BYTES, GIT_COMMAND_TIMEOUT_SECONDS,
    GitCommandTimeout, GitSnapshotError, RepositorySnapshot, SnapshotError,
    _entry, _git_oid, _malformed_raw, _opaque, _raw_display, _text,
)

DEFAULT_MAX_TOTAL_BYTES = 128 * 1024 * 1024
DEFAULT_MAX_METADATA_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class CommittedPopulationEntry:
    raw_path_hex: str
    git_mode: str
    object_type: str
    git_object_oid: str
    size_bytes: int | None

    @property
    def path(self) -> str:
        return _raw_display(bytes.fromhex(self.raw_path_hex))

    def to_dict(self) -> dict[str, Any]:
        return dict(raw_path_hex=self.raw_path_hex, git_mode=self.git_mode,
                    object_type=self.object_type, git_object_oid=self.git_object_oid,
                    size_bytes=self.size_bytes)


@dataclass(frozen=True)
class CommittedPopulationPlan:
    repository_id: str
    commit: str
    tree: str
    entries: tuple[CommittedPopulationEntry, ...]
    max_entries: int
    max_file_bytes: int
    max_total_bytes: int
    max_metadata_bytes: int

    @property
    def blob_count(self) -> int:
        return sum(entry.object_type == "blob" for entry in self.entries)

    @property
    def total_blob_bytes(self) -> int:
        # Count bytes per committed path, including repeated blob OIDs.
        return sum(entry.size_bytes or 0 for entry in self.entries)

    @property
    def maximum_blob_bytes(self) -> int:
        return max((entry.size_bytes or 0 for entry in self.entries), default=0)

    @property
    def budget_violations(self) -> tuple[str, ...]:
        return tuple(name for name, failed in (
            ("max_entries", len(self.entries) > self.max_entries),
            ("max_file_bytes", self.maximum_blob_bytes > self.max_file_bytes),
            ("max_total_bytes", self.total_blob_bytes > self.max_total_bytes),
        ) if failed)

    def population_payload(self) -> dict[str, Any]:
        return {"schema": "ipfs-datasets.complete-committed-population@1",
                "repository_id": self.repository_id, "commit": self.commit, "tree": self.tree,
                "scope": "complete-committed", "exclusions": [],
                "entries": [entry.to_dict() for entry in self.entries]}

    @property
    def population_cid(self) -> str:
        return cid_for_structured(self.population_payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.population_payload(), "population_cid": self.population_cid,
                "entry_count": len(self.entries), "blob_count": self.blob_count,
                "total_blob_bytes": self.total_blob_bytes, "maximum_blob_bytes": self.maximum_blob_bytes,
                "limits": {name: getattr(self, name) for name in (
                    "max_entries", "max_file_bytes", "max_total_bytes", "max_metadata_bytes")},
                "budget_violations": list(self.budget_violations),
                "blob_bytes_acquired": 0, "acceptance_authority": False}


class CommittedPopulationBudgetError(SnapshotError):
    def __init__(self, plan: CommittedPopulationPlan):
        super().__init__("committed population exceeds " + ", ".join(plan.budget_violations))
        self.plan = plan


def _run_git(root: Path, args: tuple[str, ...], maximum_bytes: int) -> bytes:
    """Bound both Git output streams before retaining them in memory."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    argv = ["git", "--no-optional-locks", "--no-replace-objects", "-c", "core.fsmonitor=false",
            "-c", "core.hooksPath=/dev/null", "-C", str(root), *args]
    try:
        child = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    except OSError as exc:
        raise GitSnapshotError("committed Git observation unavailable") from exc
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + GIT_COMMAND_TIMEOUT_SECONDS
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ, "stdout")
            selector.register(child.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise GitCommandTimeout("committed Git observation timed out")
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    buffer = buffers[key.data]
                    limit = maximum_bytes if key.data == "stdout" else 65536
                    if len(buffer) + len(chunk) > limit:
                        raise GitSnapshotError("committed Git output exceeds acquisition budget")
                    buffer.extend(chunk)
        try:
            child.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise GitCommandTimeout("committed Git observation timed out") from exc
        if child.returncode or buffers["stderr"]:
            raise GitSnapshotError("committed Git observation failed or warned")
        return bytes(buffers["stdout"])
    except BaseException:
        # Retain the unreaped leader until its own process group is fenced.
        if child.returncode is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=5)
        raise
    finally:
        child.stdout.close()
        child.stderr.close()


def _fence(root: Path, commit: str, tree: str, limit: int) -> str:
    observed_root = _run_git(root, ("rev-parse", "--show-toplevel"), limit).decode().strip()
    if Path(observed_root).resolve() != root:
        raise GitSnapshotError("committed request must name the exact repository root")
    if _run_git(root, ("rev-parse", "--verify", "HEAD"), limit).decode().strip() != commit:
        raise GitSnapshotError("HEAD differs from requested committed population")
    if _run_git(root, ("cat-file", "-t", commit), limit).strip() != b"commit":
        raise GitSnapshotError("requested object is not a commit")
    if _run_git(root, ("rev-parse", "--verify", commit + "^{tree}"), limit).decode().strip() != tree:
        raise GitSnapshotError("tree differs from requested committed population")
    if _run_git(root, ("status", "--porcelain=v1", "-z", "--untracked-files=all"), limit):
        raise GitSnapshotError("complete committed acquisition requires a clean checkout")
    flags = _run_git(root, ("ls-files", "-v", "-z"), limit)
    if any(row and (chr(row[0]).islower() or row[:1] == b"S") for row in flags.split(b"\0")):
        raise GitSnapshotError("source index hides tracked bytes")
    index = _run_git(root, ("ls-files", "--stage", "-z"), limit)
    return hashlib.sha256(flags + b"\0" + index).hexdigest()


def preflight_committed_repository(
    repository: str | os.PathLike[str], *, expected_commit: str, expected_tree: str,
    repository_id: str, max_entries: int = DEFAULT_MAX_ENTRIES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES, max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_metadata_bytes: int = DEFAULT_MAX_METADATA_BYTES,
) -> CommittedPopulationPlan:
    """Inventory every committed entry without acquiring or parsing blob bytes.

    Per-file/aggregate deficiencies are returned in the complete plan. Metadata
    output itself is bounded and fails closed instead of yielding partial scope.
    Gitlinks are retained as references; this API does not acquire their forests.
    """
    commit, tree = _git_oid(expected_commit, "commit"), _git_oid(expected_tree, "tree")
    if not commit or not tree:
        raise GitSnapshotError("full commit and tree object ids are required")
    identity = _text(repository_id, "repository_id")
    if any(type(value) is not int or value < 1 for value in (
            max_entries, max_file_bytes, max_total_bytes, max_metadata_bytes)):
        raise SnapshotError("committed acquisition limits must be positive integers")
    root = Path(repository).resolve(strict=True)
    before = _fence(root, commit, tree, max_metadata_bytes)
    raw = _run_git(root, ("ls-tree", "-r", "-l", "-z", "--full-tree", tree), max_metadata_bytes)
    entries = []
    paths = set()
    for row in raw.split(b"\0"):
        if not row:
            continue
        try:
            metadata, path = row.split(b"\t", 1)
            mode, kind, oid, size = metadata.decode("ascii").split()
            _git_oid(oid, "committed object")
            if (mode, kind) not in {("100644", "blob"), ("100755", "blob"),
                                    ("120000", "blob"), ("160000", "commit")}:
                raise ValueError("invalid committed object kind")
            if kind == "blob":
                if not size.isascii() or not size.isdecimal():
                    raise ValueError("unavailable committed blob size")
                measured = int(size)
            else:
                if size != "-":
                    raise ValueError("invalid gitlink size")
                measured = None
            if not path or path in paths:
                raise ValueError("missing or duplicate committed path")
            paths.add(path)
            entries.append(CommittedPopulationEntry(path.hex(), mode, kind, oid, measured))
        except (ValueError, SnapshotError) as exc:
            raise GitSnapshotError("invalid committed population inventory") from exc
    if _fence(root, commit, tree, max_metadata_bytes) != before:
        raise GitSnapshotError("source index changed during committed preflight")
    return CommittedPopulationPlan(identity, commit, tree, tuple(sorted(entries, key=lambda e: e.raw_path_hex)),
                                   max_entries, max_file_bytes, max_total_bytes, max_metadata_bytes)


def snapshot_committed_repository(
    repository: str | os.PathLike[str], *, expected_commit: str, expected_tree: str,
    repository_id: str, max_entries: int = DEFAULT_MAX_ENTRIES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES, max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_metadata_bytes: int = DEFAULT_MAX_METADATA_BYTES, expected_population_cid: str | None = None,
) -> RepositorySnapshot:
    """Acquire a complete committed population only after its budget is admitted.

    Calling this separate API explicitly selects complete committed scope.
    Ordinary snapshot_repository exclusions and identities remain unchanged.
    The caller must bind the plan/limits and producer revision to any subsequent
    independent verification request; this function is not an acceptance issuer.
    """
    plan = preflight_committed_repository(
        repository, expected_commit=expected_commit, expected_tree=expected_tree,
        repository_id=repository_id, max_entries=max_entries, max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes, max_metadata_bytes=max_metadata_bytes)
    if expected_population_cid is not None and expected_population_cid != plan.population_cid:
        raise GitSnapshotError("committed population differs from requested preflight")
    if plan.budget_violations:
        raise CommittedPopulationBudgetError(plan)
    root = Path(repository).resolve(strict=True)
    before = _fence(root, plan.commit, plan.tree, max_metadata_bytes)
    entries = []
    for item in plan.entries:
        raw, oid = bytes.fromhex(item.raw_path_hex), item.git_object_oid
        if _malformed_raw(raw) or item.git_mode == "120000" or item.object_type != "blob":
            reason = "malformed_path" if _malformed_raw(raw) else "symlink_or_nonregular"
            entries.append(_opaque(item.path, reason, item.size_bytes, raw=raw, oid=oid,
                                   disposition="clean", head_oid=oid))
            continue
        data = _run_git(root, ("cat-file", "blob", oid), item.size_bytes + 1)
        header = b"blob " + str(len(data)).encode("ascii") + b"\0"
        algorithm = hashlib.sha1 if len(oid) == 40 else hashlib.sha256
        if len(data) != item.size_bytes or algorithm(header + data).hexdigest() != oid:
            raise GitSnapshotError("captured blob differs from committed object identity")
        entries.append(_entry(item.path, raw, data, max_file_bytes, oid,
                              disposition="clean", head_oid=oid, acquisition="git-object"))
    if _fence(root, plan.commit, plan.tree, max_metadata_bytes) != before:
        raise GitSnapshotError("source index changed during complete committed acquisition")
    result = RepositorySnapshot(plan.repository_id, tuple(entries), "git-clean",
                                max_file_bytes, max_entries, plan.tree, plan.commit, ())
    if tuple(entry.raw_path_hex for entry in result.entries) != tuple(entry.raw_path_hex for entry in plan.entries):
        raise GitSnapshotError("complete committed acquisition changed population")
    return result


__all__ = ["CommittedPopulationEntry", "CommittedPopulationPlan", "CommittedPopulationBudgetError",
           "preflight_committed_repository", "snapshot_committed_repository"]
