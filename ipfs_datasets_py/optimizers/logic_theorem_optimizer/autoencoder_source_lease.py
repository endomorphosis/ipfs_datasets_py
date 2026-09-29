"""Cooperative source readers and serialized canonical-checkout writers.

Readers hold a shared lease for the complete operation, including draining
children. Writers hold the exclusive lease while applying and validating a
merge. The admission lock prevents new readers passing a waiting writer once
that writer reaches the turnstile. Both waits share one bounded deadline.

These are kernel file locks, not expiring ownership records: closing the last
descriptor (including process death) releases a lease. Never unlink lock files.
Direct editors can bypass this cooperative protocol; the existing complete
source/provenance checks remain necessary and unchanged. Do not nest leases:
an outer orchestration lease must cover its children's entire lifetime.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import fcntl
import math
import os
from pathlib import Path
import stat
import subprocess
import time


DEFAULT_TIMEOUT_SECONDS = 300.0
CONTROL_DIRECTORY = Path("workspace/control-plane/source-leases")


class SourceLeaseError(RuntimeError):
    """The canonical repository or lock identity cannot be verified."""


class SourceLeaseTimeout(TimeoutError):
    """The bounded source-lease admission deadline expired."""


def _absolute(value):
    return Path(os.path.abspath(os.fspath(value)))


@contextmanager
def _directory(path, *, create_under=None):
    """Walk using no-follow directory descriptors, including every ancestor."""
    path = _absolute(path)
    boundary = _absolute(create_under) if create_under is not None else None
    if boundary is not None and boundary not in path.parents:
        raise SourceLeaseError("source lease directory creation escaped its repository")
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        try:
            for index, name in enumerate(path.parts[1:], start=1):
                if boundary is not None and index >= len(boundary.parts):
                    try:
                        os.mkdir(name, mode=0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                                os.O_CLOEXEC, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
        except OSError as exc:
            raise SourceLeaseError(f"source lease directory is missing, aliased, or unsafe: {path}") from exc
        yield descriptor
    finally:
        os.close(descriptor)


def _git(root, *arguments):
    environment = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"):
        environment.pop(key, None)
    result = subprocess.run(["git", "-C", str(root), *arguments],
                            capture_output=True, text=True, timeout=5,
                            env=environment, check=False)
    if result.returncode:
        raise SourceLeaseError("cannot verify canonical source repository: " +
                               (result.stderr.strip() or "git command failed"))
    return result.stdout.strip()


def canonical_source_root(repo_root=None):
    """Map linked worktrees and submodules to their shared primary checkout."""
    selected = _absolute(repo_root if repo_root is not None else Path(__file__).parents[3])
    with _directory(selected):
        common = _absolute(_git(selected, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        if _git(selected, "rev-parse", "--is-bare-repository") != "false":
            raise SourceLeaseError("source lease requires a non-bare repository")
        # --get may legitimately return 1 when core.worktree is absent. Read
        # the full config value through --default instead; submodules use a
        # path relative to their common git directory, not the current lane.
        configured = _git(selected, "config", "--local", "--default", "", "--get", "core.worktree")
        worktree_config = _git(selected, "config", "--local", "--type=bool", "--default",
                               "false", "--get", "extensions.worktreeConfig") == "true"
        if worktree_config:
            # A linked lane's effective config.worktree can name the lane
            # itself. Read only the PRIMARY worktree configuration, located
            # beside the common config, to preserve one shared lock authority.
            primary_config = common / "config.worktree"
            try:
                observed = primary_config.lstat()
            except FileNotFoundError:
                observed = None
            if observed is not None:
                if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
                    raise SourceLeaseError("primary worktree configuration is aliased or not regular")
                override = _git(selected, "config", "--file", str(primary_config),
                                "--default", "", "--get", "core.worktree")
                if override:
                    configured = override
        if configured:
            candidate = Path(configured)
            root = _absolute(candidate if candidate.is_absolute() else common / candidate)
        elif common.name == ".git":
            root = common.parent
        else:
            raise SourceLeaseError("repository has no verifiable primary checkout")
        with _directory(root):
            observed = _absolute(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
            if observed != common or _absolute(_git(root, "rev-parse", "--show-toplevel")) != root:
                raise SourceLeaseError("canonical source repository identity mismatch")
        return root


def _lock_file(directory_fd, name):
    try:
        descriptor = os.open(name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW |
                             os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=directory_fd)
    except OSError as exc:
        raise SourceLeaseError("source lease lock cannot be opened safely") from exc
    try:
        _verify_lock(directory_fd, name, descriptor)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _verify_lock(directory_fd, name, descriptor):
    info = os.fstat(descriptor)
    observed = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1
            or (info.st_dev, info.st_ino) != (observed.st_dev, observed.st_ino)):
        raise SourceLeaseError("source lease lock must remain an unaliased regular file")


def _acquire(descriptor, operation, deadline, label):
    while True:
        try:
            fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
            return
        except BlockingIOError as exc:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SourceLeaseTimeout(f"timed out waiting for {label} source lease") from exc
            time.sleep(min(0.025, remaining))


@dataclass(frozen=True)
class SourceLease:
    canonical_root: str
    mode: str
    lock_path: str
    waited_seconds: float
    schema_version: str = "autoencoder-source-lease/v1"
    cooperative: bool = True

    def to_dict(self):
        return asdict(self)


@contextmanager
def source_lease(repo_root=None, *, mode="read", timeout_seconds=DEFAULT_TIMEOUT_SECONDS):
    """Hold the shared training/read or exclusive merge/write source lease.

    ``repo_root`` identifies a repository, never a caller-selected lock path.
    Linked worktrees resolve to the same primary-checkout control directory.
    Timeout bounds lock waiting; repository identity checks have separate five
    second Git-command bounds. A zero timeout performs nonblocking admission.
    """
    if mode not in {"read", "write"}:
        raise SourceLeaseError("source lease mode must be read or write")
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or timeout_seconds < 0):
        raise SourceLeaseError("source lease timeout must be finite and nonnegative")
    root = canonical_source_root(repo_root)
    directory = root / CONTROL_DIRECTORY
    with _directory(directory, create_under=root) as directory_fd:
        initial = os.fstat(directory_fd)
        admission = _lock_file(directory_fd, "admission.lock")
        source = None
        try:
            source = _lock_file(directory_fd, "source.lock")
            started = time.monotonic()
            deadline = started + float(timeout_seconds)
            _acquire(admission, fcntl.LOCK_EX, deadline, "admission")
            _verify_lock(directory_fd, "admission.lock", admission)
            _acquire(source, fcntl.LOCK_SH if mode == "read" else fcntl.LOCK_EX,
                     deadline, mode)
            _verify_lock(directory_fd, "source.lock", source)
            with _directory(directory) as fresh:
                current = os.fstat(fresh)
                if (current.st_dev, current.st_ino) != (initial.st_dev, initial.st_ino):
                    raise SourceLeaseError("source lease directory identity changed")
            fcntl.flock(admission, fcntl.LOCK_UN)
            try:
                yield SourceLease(str(root), mode, str(directory / "source.lock"),
                                  time.monotonic() - started)
            finally:
                # Detect cooperative lock-path replacement too; do not delete
                # any path or adopt a replacement descriptor during recovery.
                _verify_lock(directory_fd, "source.lock", source)
                _verify_lock(directory_fd, "admission.lock", admission)
                with _directory(directory) as fresh:
                    current = os.fstat(fresh)
                    if (current.st_dev, current.st_ino) != (initial.st_dev, initial.st_ino):
                        raise SourceLeaseError("source lease directory identity changed")
        finally:
            if source is not None:
                os.close(source)
            os.close(admission)


__all__ = ["SourceLease", "SourceLeaseError", "SourceLeaseTimeout",
           "canonical_source_root", "source_lease"]
