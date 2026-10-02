"""Reusable checkout mutation lock helpers for autonomous agent supervisors."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import errno
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
import stat as stat_module
from typing import Any, Callable, Final, Iterator, Literal, Mapping, Sequence

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised only on non-POSIX hosts
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt
except ImportError:  # pragma: no cover - exercised only on non-Windows hosts
    msvcrt = None  # type: ignore[assignment]

from ..proof.formal_verification_contracts import content_identity


DEFAULT_CHECKOUT_MUTATION_LOCK_NAME = "implementation-main-merge.lock"
PROTECTED_PATH_MAINTENANCE_LOCK_NAME = (
    "implementation-protected-path-maintenance.lock"
)
CRASH_FENCE_RECONCILIATION_LOCK_NAME = (
    "implementation-protected-path-crash-fence-recon.lock"
)
# Exclusive crash-fence mutations must finish quickly: expensive path/objective
# scans stay outside this critical section, and only revalidation + fence
# writes run while the lease is held.
DEFAULT_CHECKOUT_MAINTENANCE_MAX_HOLD_SECONDS = 2.0
DEFAULT_MERGE_TRAIN_DIRECTORY_NAME = "agent-merge-trains"
DEFAULT_OBJECTIVE_ADMISSION_LOCK_DIRECTORY_NAME = "agent-objective-admission-locks"
BACKLOG_REFINERY_AUTHOR_EMAIL = "accelerator-backlog-refinery@example.invalid"
GENERATED_PROTECTED_BOARD_COMMIT_MARKER = "[agent-supervisor:generated-protected-board]"


def generated_protected_board_commit_subject(subject: str) -> str:
    """Tag a supervisor-generated protected-board commit for fence validation."""

    normalized = str(subject or "").strip()
    if normalized.endswith(GENERATED_PROTECTED_BOARD_COMMIT_MARKER):
        return normalized
    return f"{normalized} {GENERATED_PROTECTED_BOARD_COMMIT_MARKER}".strip()


def crash_fence_reconciliation_lock_path(repo_root: Path) -> Path:
    """Return the short exclusive lock used for crash-fence mutations."""

    return checkout_mutation_lock_path(
        repo_root,
        lock_name=CRASH_FENCE_RECONCILIATION_LOCK_NAME,
    )


def durable_input_generation(path: Path) -> dict[str, Any]:
    """Capture an immutable-input identity used to revalidate before mutation.

    Callers scan expensive state outside the exclusive lease, then re-read this
    generation under the critical section. Any mismatch aborts the mutation so
    concurrent maintenance or a peer reconciler cannot produce a false clear or
    false incident from a stale plan.
    """

    try:
        if not path.exists():
            return {
                "path": str(path),
                "state": "missing",
            }
    except OSError as exc:
        return {
            "path": str(path),
            "state": "error",
            "error_type": type(exc).__name__,
            "error": str(exc)[-500:],
        }
    try:
        stat_result = path.lstat()
    except FileNotFoundError:
        return {
            "path": str(path),
            "state": "missing",
        }
    except OSError as exc:
        return {
            "path": str(path),
            "state": "error",
            "error_type": type(exc).__name__,
            "error": str(exc)[-500:],
        }
    digest = ""
    size = int(getattr(stat_result, "st_size", 0) or 0)
    if stat_module_is_regular_file(stat_result) and size <= 1_048_576:
        try:
            payload = path.read_bytes()
        except OSError as exc:
            return {
                "path": str(path),
                "state": "error",
                "error_type": type(exc).__name__,
                "error": str(exc)[-500:],
            }
        digest = hashlib.sha256(payload).hexdigest()
    return {
        "path": str(path),
        "state": "present",
        "device": int(getattr(stat_result, "st_dev", 0) or 0),
        "inode": int(getattr(stat_result, "st_ino", 0) or 0),
        "size": size,
        "mtime_ns": int(getattr(stat_result, "st_mtime_ns", 0) or 0),
        "sha256": digest,
    }


def stat_module_is_regular_file(stat_result: os.stat_result) -> bool:
    """Return whether a stat result describes a regular file."""

    import stat as stat_module

    return stat_module.S_ISREG(int(stat_result.st_mode))


def generations_match(
    expected: Mapping[str, Any] | None,
    observed: Mapping[str, Any] | None,
) -> bool:
    """Return whether two durable-input generations are identical."""

    if not isinstance(expected, Mapping) or not isinstance(observed, Mapping):
        return False
    return dict(expected) == dict(observed)


@dataclass
class CheckoutMaintenanceLease:
    """Bounded exclusive lease for short checkout-mutation critical sections.

    Repository-global maintenance and crash-fence reconciliation both need
    mutual exclusion, but expensive scans must not keep the exclusive section
    open. Callers scan immutable inputs first, then enter
    :meth:`exclusive_section` only for revalidation and fenced mutation.
    """

    lock_path: Path
    metadata: dict[str, Any]
    max_hold_seconds: float = DEFAULT_CHECKOUT_MAINTENANCE_MAX_HOLD_SECONDS
    _acquired_at_monotonic: float | None = field(default=None, init=False, repr=False)
    _hold_seconds: float | None = field(default=None, init=False, repr=False)
    _lease_id: str = field(default="", init=False, repr=False)

    def __post_init__(self) -> None:
        self.lock_path = Path(self.lock_path)
        self.metadata = dict(self.metadata)
        self.max_hold_seconds = float(self.max_hold_seconds)
        if self.max_hold_seconds <= 0:
            raise ValueError("max_hold_seconds must be positive")
        lease_id = str(self.metadata.get("lease_id") or "").strip()
        if not lease_id:
            seed = (
                f"{os.getpid()}:{time.time_ns()}:{self.lock_path}:"
                f"{self.metadata.get('kind') or 'checkout-maintenance'}"
            )
            lease_id = hashlib.sha1(seed.encode("utf-8")).hexdigest()
            self.metadata["lease_id"] = lease_id
        self._lease_id = lease_id
        self.metadata.setdefault("kind", "checkout-maintenance")
        self.metadata.setdefault("pid", os.getpid())
        if "expires_at" not in self.metadata:
            self.metadata["expires_at"] = time.time() + self.max_hold_seconds
        self.metadata.setdefault("owner_script", Path(sys.argv[0]).name)

    @property
    def lease_id(self) -> str:
        return self._lease_id

    @property
    def hold_seconds(self) -> float | None:
        if self._hold_seconds is not None:
            return self._hold_seconds
        if self._acquired_at_monotonic is None:
            return None
        return max(0.0, time.monotonic() - self._acquired_at_monotonic)

    def is_held(self) -> bool:
        return self._acquired_at_monotonic is not None and self._hold_seconds is None

    def ensure_within_hold_bound(self) -> float:
        """Return current hold seconds or raise when the exclusive bound is exceeded."""

        held = self.hold_seconds
        if held is None:
            raise RuntimeError("checkout maintenance lease is not held")
        if held > self.max_hold_seconds:
            raise RuntimeError(
                "checkout maintenance lease hold exceeded bound: "
                f"{held:.6f}s > {self.max_hold_seconds:.6f}s"
            )
        return held

    def _publish_lease(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.lock_path.with_name(
            f".{self.lock_path.name}.{self._lease_id}.tmp"
        )
        data = (
            json.dumps(self.metadata, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        fd: int | None = None
        try:
            fd = os.open(
                temporary_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            with os.fdopen(fd, "wb") as stream:
                fd = None
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary_path, self.lock_path)
            except FileExistsError:
                return False
            return True
        finally:
            if fd is not None:
                os.close(fd)
            temporary_path.unlink(missing_ok=True)

    def _load_existing(self) -> dict[str, Any] | None:
        try:
            if not self.lock_path.exists():
                return None
        except OSError:
            return None
        try:
            payload = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {"kind": "malformed", "path": str(self.lock_path)}
        if not isinstance(payload, dict):
            return {"kind": "malformed", "path": str(self.lock_path)}
        return payload

    def try_acquire(
        self,
        *,
        owner_is_active: Any | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        """Attempt a non-blocking exclusive acquire with bounded metadata."""

        if self.is_held():
            return True, {
                "blocked": False,
                "reason": "checkout_maintenance_lease_already_held",
                "lease_id": self._lease_id,
                "lock_path": str(self.lock_path),
            }
        with serialized_lock_update(self.lock_path):
            for _ in range(2):
                if self._publish_lease():
                    self._acquired_at_monotonic = time.monotonic()
                    self._hold_seconds = None
                    return True, {
                        "blocked": False,
                        "reason": "checkout_maintenance_lease_acquired",
                        "lease_id": self._lease_id,
                        "lock_path": str(self.lock_path),
                        "max_hold_seconds": self.max_hold_seconds,
                    }
                existing = self._load_existing()
                if existing is None:
                    try:
                        self.lock_path.unlink()
                    except FileNotFoundError:
                        continue
                    except OSError as exc:
                        return False, {
                            "blocked": True,
                            "reason": "checkout_maintenance_lease_cleanup_failed",
                            "lock_path": str(self.lock_path),
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    continue
                if str(existing.get("kind") or "") == "malformed":
                    # Atomic publication cannot create a partial owned lease.
                    # Treat malformed state as unknown ownership and require
                    # explicit recovery instead of deleting a potentially live
                    # coordination record.
                    return False, {
                        "blocked": True,
                        "reason": "checkout_maintenance_lease_malformed",
                        "lock_path": str(self.lock_path),
                    }
                try:
                    expires_at = float(existing.get("expires_at") or 0.0)
                except (TypeError, ValueError):
                    expires_at = 0.0
                if expires_at > 0 and expires_at <= time.time():
                    try:
                        self.lock_path.unlink()
                    except FileNotFoundError:
                        continue
                    except OSError as exc:
                        return False, {
                            "blocked": True,
                            "reason": "checkout_maintenance_lease_cleanup_failed",
                            "lock_path": str(self.lock_path),
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    continue
                active = True
                if owner_is_active is not None:
                    try:
                        active = bool(owner_is_active(existing))
                    except Exception:
                        active = True
                if active:
                    return False, {
                        "blocked": True,
                        "reason": "checkout_maintenance_lease_active",
                        "lock_path": str(self.lock_path),
                        "lock_owner_pid": int(existing.get("pid") or 0),
                        "lock_owner_lease_id": str(
                            existing.get("lease_id") or ""
                        ),
                    }
                try:
                    self.lock_path.unlink()
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    return False, {
                        "blocked": True,
                        "reason": "checkout_maintenance_lease_cleanup_failed",
                        "lock_path": str(self.lock_path),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
        return False, {
            "blocked": True,
            "reason": "checkout_maintenance_lease_unavailable",
            "lock_path": str(self.lock_path),
        }

    def release(self) -> dict[str, Any]:
        """Release this exclusive lease when still owned by ``lease_id``."""

        hold = self.hold_seconds
        if self._acquired_at_monotonic is not None and self._hold_seconds is None:
            self._hold_seconds = max(
                0.0, time.monotonic() - self._acquired_at_monotonic
            )
            hold = self._hold_seconds
        self._acquired_at_monotonic = None
        try:
            with serialized_lock_update(self.lock_path):
                existing = self._load_existing()
                if existing is None:
                    return {
                        "released": True,
                        "reason": "checkout_maintenance_lease_absent",
                        "hold_seconds": hold,
                        "max_hold_seconds": self.max_hold_seconds,
                    }
                if str(existing.get("lease_id") or "") != self._lease_id:
                    return {
                        "released": False,
                        "reason": "checkout_maintenance_lease_replaced",
                        "hold_seconds": hold,
                        "max_hold_seconds": self.max_hold_seconds,
                    }
                self.lock_path.unlink(missing_ok=True)
        except (OSError, RuntimeError) as exc:
            return {
                "released": False,
                "reason": "checkout_maintenance_lease_release_failed",
                "error": f"{type(exc).__name__}: {exc}",
                "hold_seconds": hold,
                "max_hold_seconds": self.max_hold_seconds,
            }
        return {
            "released": True,
            "reason": "checkout_maintenance_lease_released",
            "hold_seconds": hold,
            "max_hold_seconds": self.max_hold_seconds,
            "within_bound": (
                hold is not None and hold <= self.max_hold_seconds
            ),
        }

    @contextmanager
    def exclusive_section(
        self,
        *,
        owner_is_active: Any | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Hold the exclusive lease only for the critical section body.

        The yielded timing dict is updated in ``finally`` so callers that keep a
        reference observe final hold seconds even when the body returns early.
        """

        acquired, guard = self.try_acquire(owner_is_active=owner_is_active)
        if not acquired:
            raise RuntimeError(
                str(guard.get("reason") or "checkout_maintenance_lease_unavailable")
            )
        timing: dict[str, Any] = {
            "lease_id": self._lease_id,
            "lock_path": str(self.lock_path),
            "max_hold_seconds": self.max_hold_seconds,
            "hold_seconds": None,
            "within_bound": None,
        }
        body_error: BaseException | None = None
        try:
            yield timing
        except BaseException as exc:
            body_error = exc
            raise
        finally:
            release_info = self.release()
            hold = release_info.get("hold_seconds")
            timing["hold_seconds"] = hold
            within_bound = (
                hold is not None and float(hold) <= self.max_hold_seconds
            )
            timing["within_bound"] = within_bound
            timing["release"] = release_info
            if body_error is None and hold is not None and not within_bound:
                # Surface bound violations after a clean body so callers cannot
                # miss an over-long exclusive section.
                raise RuntimeError(
                    "checkout maintenance lease hold exceeded bound: "
                    f"{float(hold):.6f}s > {self.max_hold_seconds:.6f}s"
                )

@contextmanager
def serialized_lock_update(
    lock_path: Path,
    *,
    timeout_seconds: float | None = None,
    poll_seconds: float = 0.05,
) -> Iterator[None]:
    """Serialize create/inspect/replace operations for one durable lock path.

    The durable JSON lock remains the long-lived ownership record.  This
    adjacent advisory guard is held only while that record is inspected or
    replaced, closing the stale-owner check/unlink race between the supervisor
    and its managed implementation daemon.
    """

    from .workspace_quarantine import claim_update
    with claim_update(lock_path):
        if fcntl is None and msvcrt is None:
            raise RuntimeError("durable lock replacement requires an advisory file-lock backend")
        guard_path = lock_path.with_name(f".{lock_path.name}.update.lock")
        guard_path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_RDWR
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(guard_path, flags, 0o600)
        locked = False
        deadline = (
            None if timeout_seconds is None else time.monotonic() + max(0.0, float(timeout_seconds))
        )
        try:
            if fcntl is not None:
                if deadline is None:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                else:
                    while True:
                        try:
                            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            break
                        except BlockingIOError:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise TimeoutError("timed out serializing durable lock update")
                            time.sleep(min(max(0.001, float(poll_seconds)), remaining))
            else:
                assert msvcrt is not None
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"\0")
                while True:
                    os.lseek(fd, 0, os.SEEK_SET)
                    try:
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                        break
                    except OSError as exc:
                        if exc.errno not in {
                            errno.EACCES,
                            errno.EAGAIN,
                            errno.EDEADLK,
                        }:
                            raise
                        if deadline is not None and deadline - time.monotonic() <= 0:
                            raise TimeoutError("timed out serializing durable lock update")
                        sleep_seconds = max(0.001, float(poll_seconds))
                        if deadline is not None:
                            sleep_seconds = min(
                                sleep_seconds,
                                max(0.0, deadline - time.monotonic()),
                            )
                        if sleep_seconds <= 0:
                            raise TimeoutError("timed out serializing durable lock update")
                        time.sleep(sleep_seconds)
            locked = True
            yield
        finally:
            try:
                if locked:
                    if fcntl is not None:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                    else:
                        assert msvcrt is not None
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            finally:
                os.close(fd)


def git_common_dir(repo_root: Path) -> Path:
    """Return the repository common git directory for a checkout."""

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return repo_root / ".git"
    stdout = result.stdout or ""
    if result.returncode != 0 or not stdout.strip():
        return repo_root / ".git"
    path = Path(stdout.strip())
    return path if path.is_absolute() else repo_root / path


def checkout_mutation_lock_path(
    repo_root: Path,
    *,
    lock_name: str = DEFAULT_CHECKOUT_MUTATION_LOCK_NAME,
) -> Path:
    """Return a repo-wide lock path for parent checkout mutations."""

    return git_common_dir(repo_root) / lock_name


def board_scoped_checkout_mutation_lock_path(
    repo_root: Path,
    board_namespace: str,
) -> Path:
    """Return the merge lock used by one task-board namespace.

    Distinct boards sharing a Git common directory no longer contend on
    ``implementation-main-merge.lock``. Two supervisors with the same
    namespace still serialize on the same inode.
    """

    from ..task_sources.board_control_plane import board_merge_lock_name

    return checkout_mutation_lock_path(
        repo_root,
        lock_name=board_merge_lock_name(board_namespace),
    )


def board_scoped_protected_path_maintenance_lock_path(
    repo_root: Path,
    board_namespace: str,
) -> Path:
    """Return the protected-path maintenance lock for one board namespace."""

    from ..task_sources.board_control_plane import board_protected_path_lock_name

    return checkout_mutation_lock_path(
        repo_root,
        lock_name=board_protected_path_lock_name(board_namespace),
    )


def objective_admission_lock_path(objective_path: Path) -> Path:
    """Return a durable lock outside a Git worktree when one is available.

    Objective admission locks must survive for the lifetime of cooperating
    processes: unlinking an advisory lock after use creates an inode race.
    Keeping that persistent coordination file beside a tracked objective,
    however, makes an otherwise clean integration checkout permanently dirty.
    A repository's common Git directory is shared by the processes operating
    on that checkout while remaining outside its status surface.

    Git-less callers retain the historical adjacent-lock fallback.
    """

    objective = Path(objective_path).resolve()
    cwd = objective.parent
    while not cwd.exists() and cwd.parent != cwd:
        cwd = cwd.parent
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel", "--git-common-dir"],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        result = None
    lines = (
        [line.strip() for line in (result.stdout or "").splitlines()]
        if result is not None and result.returncode == 0
        else []
    )
    if len(lines) >= 2:
        top = Path(lines[0]).resolve()
        try:
            objective.relative_to(top)
        except ValueError:
            pass
        else:
            common_dir = Path(lines[1])
            if not common_dir.is_absolute():
                common_dir = (cwd / common_dir).resolve()
            safe_name = (
                "".join(
                    character if character.isalnum() or character in "-._" else "-"
                    for character in objective.name
                ).strip("-")
                or "objective"
            )
            binding = f"{top}\0{objective}".encode("utf-8")
            digest = hashlib.sha256(binding).hexdigest()[:20]
            return (
                common_dir
                / DEFAULT_OBJECTIVE_ADMISSION_LOCK_DIRECTORY_NAME
                / f"{safe_name[:64]}-{digest}.lock"
            )
    return objective.with_name(f".{objective.name}.admission.lock")


def checkout_repository_id(repo_root: Path) -> str:
    """Return a stable local identity shared by all worktrees of one Git repo."""

    common_dir = git_common_dir(repo_root)
    try:
        identity_source = str(common_dir.resolve())
    except (OSError, RuntimeError):
        identity_source = str(common_dir)
    return "repository:" + content_identity(
        {
            "kind": "local-git-common-directory",
            "path": identity_source,
        }
    )


def _verified_checkout_repository_id(repo_root: Path) -> str | None:
    """Return a repository identity only when Git proves the common directory.

    ``checkout_repository_id`` intentionally retains its historical Git-less
    fallback for callers that need a stable local namespace.  Lease ownership
    is a stricter safety boundary: treating that fallback as proof could make
    two sibling worktrees appear unrelated when Git is unavailable and allow
    one process to steal the other's live common-directory lease.
    """

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
    except (OSError, ValueError):
        return None
    stdout = result.stdout or ""
    if result.returncode != 0 or not stdout.strip():
        return None
    common_dir = Path(stdout.strip())
    if not common_dir.is_absolute():
        common_dir = repo_root / common_dir
    try:
        identity_source = str(common_dir.resolve(strict=True))
    except (OSError, RuntimeError):
        return None
    return (
        "repository:"
        + content_identity(
            {
                "kind": "local-git-common-directory",
                "path": identity_source,
            }
        )
    )


def checkout_lock_repository_matches(
    metadata: Mapping[str, Any],
    expected_repo_root: Path,
) -> bool | None:
    """Compare lock authority by physical Git repository.

    ``True`` and ``False`` are conclusive matches and mismatches. ``None``
    means Git could not prove the relationship.  Lease liveness callers must
    treat that uncertainty as active so they fail closed instead of clearing
    an incumbent lock.

    New records carry ``repository_id``.  Legacy records fall back to proving
    the common Git identity of their exact checkout path, allowing a live
    record written by one linked worktree to remain valid in every sibling.
    """

    expected_repository_id = _verified_checkout_repository_id(expected_repo_root)
    repository_id = str(metadata.get("repository_id") or "")
    if expected_repository_id is not None and repository_id:
        return repository_id == expected_repository_id
    legacy_root = str(
        metadata.get("worktree_root")
        or metadata.get("repo_root")
        or ""
    ).strip()
    if not legacy_root:
        return None
    try:
        if Path(legacy_root).resolve() == expected_repo_root.resolve():
            # Exact-checkout metadata remains safe for Git-less test repos and
            # legacy single-worktree deployments. Different paths are not a
            # mismatch unless Git can prove they are different repositories:
            # they may be siblings observed during a transient Git failure.
            return True
    except (OSError, RuntimeError):
        return None
    if expected_repository_id is None:
        return None
    observed_repository_id = _verified_checkout_repository_id(
        Path(legacy_root)
    )
    if observed_repository_id is None:
        return None
    return observed_repository_id == expected_repository_id


def merge_target_queue_dir(
    repo_root: Path,
    target_branch: str,
) -> Path:
    """Return the queue namespace for one physical repository and target ref.

    Older supervisors used one queue directly under ``agent-merge-train``
    inside the Git common directory. The catalog now lives under the account
    home in ``.ipfs_accelerate/agent_supervisor`` (``/home/<user>`` on Linux,
    ``/Users/<user>`` on macOS, ``C:\\Users\\<user>`` on Windows), unless
    ``IPFS_ACCELERATE_AGENT_ORCHESTRATION_DIR`` or
    ``IPFS_ACCELERATE_AGENT_HOME`` is set. Every worktree of the repository
    shares that directory. Target-scoped
    directories still keep upgraded producers invisible to old repo-wide
    consumers. ``.git`` is not a database directory.
    """

    branch = str(target_branch or "").strip()
    if not branch:
        raise ValueError("merge target branch must not be empty")
    repository_id = checkout_repository_id(repo_root)
    binding = f"{repository_id}\0{branch}".encode("utf-8")
    digest = hashlib.sha256(binding).hexdigest()[:20]
    safe_branch = (
        "".join(
            character if character.isalnum() or character in "-._" else "-" for character in branch
        ).strip("-")
        or "target"
    )
    from ..task_sources.board_control_plane import (
        adopt_legacy_catalog,
        orchestration_database,
        orchestration_scope_dir,
    )

    legacy_root = git_common_dir(repo_root) / DEFAULT_MERGE_TRAIN_DIRECTORY_NAME
    destination_root = orchestration_scope_dir(repo_root) / DEFAULT_MERGE_TRAIN_DIRECTORY_NAME
    if legacy_root.is_dir() and not legacy_root.is_symlink():
        for child in list(legacy_root.iterdir()):
            if child.is_symlink():
                continue
            adopt_legacy_catalog(child, destination_root / child.name)
        try:
            legacy_root.rmdir()
        except OSError:
            pass
    return orchestration_database(
        repo_root,
        DEFAULT_MERGE_TRAIN_DIRECTORY_NAME,
        f"{safe_branch[:48]}-{digest}",
    )


def checkout_lock_metadata(
    *,
    kind: str,
    repo_root: Path,
    task_id: str = "",
    branch: str = "",
    attempt: int = 0,
    owner_script: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build JSON-serializable metadata for a checkout mutation lock."""

    worktree_root = str(repo_root.resolve())
    # Do not persist the Git-less namespace fallback as repository authority.
    # A blank identity makes upgraded liveness checks fail closed until Git
    # can prove the relationship from ``worktree_root``.
    repository_id = _verified_checkout_repository_id(repo_root) or ""
    payload: dict[str, Any] = {
        "kind": kind,
        "pid": os.getpid(),
        "owner_script": owner_script if owner_script is not None else Path(sys.argv[0]).name,
        # Keep the historical field empty during the rolling migration.
        # Older daemons compare a nonempty repo_root by exact path and would
        # otherwise steal a live lease written from a sibling worktree.
        "repo_root": "",
        "worktree_root": worktree_root,
        "repository_id": repository_id,
        "task_id": task_id,
        "attempt": int(attempt or 0),
        "branch": branch,
    }
    if extra:
        payload.update(extra)
    # Repository authority is derived from the actual checkout and must not
    # be replaceable through caller-provided supplemental metadata.
    payload["repo_root"] = ""
    payload["worktree_root"] = worktree_root
    payload["repository_id"] = repository_id
    if not str(payload.get("lease_id") or ""):
        payload["lease_id"] = content_identity(
            {
                "kind": "checkout-mutation-lease",
                "pid": os.getpid(),
                "thread_id": threading.get_ident(),
                "repository_id": repository_id,
                "worktree_root": worktree_root,
                "task_id": task_id,
                "attempt": int(attempt or 0),
                "branch": branch,
                "operation": str(payload.get("operation") or ""),
                "issued_ns": time.time_ns(),
            }
        )
    return payload


@dataclass(frozen=True)
class CheckoutMutationLease:
    """A fully published checkout lock bound to one filesystem identity."""

    lock_path: Path
    metadata: Mapping[str, Any]
    device: int
    inode: int

    @property
    def lease_id(self) -> str:
        return str(self.metadata.get("lease_id") or "")


CheckoutMutationLeaseState = Literal[
    "current",
    "absent",
    "replaced",
    "inconclusive",
]


def _read_checkout_lock(
    lock_path: Path,
) -> tuple[dict[str, Any] | None, tuple[int, int] | None]:
    """Read one lock with a stable inode identity or return inconclusive."""

    try:
        before = lock_path.stat(follow_symlinks=False)
        raw = lock_path.read_text(encoding="utf-8")
        after = lock_path.stat(follow_symlinks=False)
    except (OSError, UnicodeError):
        return None, None
    before_identity = (int(before.st_dev), int(before.st_ino))
    if before_identity != (int(after.st_dev), int(after.st_ino)):
        return None, None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None, before_identity
    if not isinstance(payload, dict):
        return None, before_identity
    return payload, before_identity


def read_checkout_mutation_lease(
    lock_path: Path,
) -> CheckoutMutationLease | None:
    """Return a stable, fully published checkout lease when one exists."""

    metadata, identity = _read_checkout_lock(lock_path)
    if metadata is None or identity is None or not str(metadata.get("lease_id") or ""):
        return None
    return CheckoutMutationLease(
        lock_path=lock_path,
        metadata=metadata,
        device=identity[0],
        inode=identity[1],
    )


def _checkout_mutation_lease_state_unlocked(
    lease: CheckoutMutationLease,
) -> CheckoutMutationLeaseState:
    """Classify a lease while the durable lock update guard is held."""

    current, identity = _read_checkout_lock(lease.lock_path)
    if current is None or identity is None:
        # A failed read is not proof of absence: malformed JSON, an inode
        # replacement during the read, and an I/O failure all collapse to an
        # inconclusive result. Confirm absence with a separate stat while the
        # serialized update guard is still held.
        try:
            lease.lock_path.stat(follow_symlinks=False)
        except FileNotFoundError:
            return "absent"
        except OSError:
            return "inconclusive"
        return "inconclusive"
    if (
        identity == (lease.device, lease.inode)
        and str(current.get("lease_id") or "") == lease.lease_id
    ):
        return "current"
    return "replaced"


def checkout_mutation_lease_state(
    lease: CheckoutMutationLease,
    *,
    timeout_seconds: float = 1.0,
) -> CheckoutMutationLeaseState:
    """Safely classify whether a durable lease is current, gone, or replaced."""

    try:
        with serialized_lock_update(
            lease.lock_path,
            timeout_seconds=timeout_seconds,
        ):
            return _checkout_mutation_lease_state_unlocked(lease)
    except (FileNotFoundError, TimeoutError):
        return "inconclusive"


def _atomic_replace_checkout_mutation_lease(
    lease: CheckoutMutationLease,
    metadata: Mapping[str, Any],
) -> CheckoutMutationLease | None:
    """Replace an exact lease with complete metadata and a new inode binding."""

    normalized = dict(metadata)
    lease_id = str(normalized.get("lease_id") or "")
    if not lease_id:
        raise ValueError("checkout mutation lock metadata requires lease_id")
    current, identity = _read_checkout_lock(lease.lock_path)
    if (
        current is None
        or identity != (lease.device, lease.inode)
        or str(current.get("lease_id") or "") != lease.lease_id
    ):
        return None

    temp_fd, temp_name = tempfile.mkstemp(
        prefix=f".{lease.lock_path.name}.",
        suffix=".replacement",
        dir=lease.lock_path.parent,
    )
    temp_path = Path(temp_name)
    try:
        fchmod = getattr(os, "fchmod", None)
        if fchmod is not None:
            fchmod(temp_fd, 0o600)
        data = json.dumps(
            normalized,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        offset = 0
        while offset < len(data):
            written = os.write(temp_fd, data[offset:])
            if written <= 0:
                raise OSError("short write while replacing checkout mutation lease")
            offset += written
        os.fsync(temp_fd)
        replacement_stat = os.fstat(temp_fd)
        replacement_identity = (
            int(replacement_stat.st_dev),
            int(replacement_stat.st_ino),
        )
        os.replace(temp_path, lease.lock_path)
        destination_stat = lease.lock_path.stat(follow_symlinks=False)
        if (
            int(destination_stat.st_dev),
            int(destination_stat.st_ino),
        ) != replacement_identity:
            return None
        published, published_identity = _read_checkout_lock(lease.lock_path)
        if published != normalized or published_identity != replacement_identity:
            return None
        return CheckoutMutationLease(
            lock_path=lease.lock_path,
            metadata=normalized,
            device=replacement_identity[0],
            inode=replacement_identity[1],
        )
    finally:
        if temp_fd >= 0:
            os.close(temp_fd)
        temp_path.unlink(missing_ok=True)


def update_checkout_mutation_lease(
    lease: CheckoutMutationLease,
    metadata: Mapping[str, Any],
    *,
    timeout_seconds: float = 1.0,
) -> CheckoutMutationLease | None:
    """CAS-replace one exact lease with atomically published metadata."""

    try:
        with serialized_lock_update(
            lease.lock_path,
            timeout_seconds=timeout_seconds,
        ):
            return _atomic_replace_checkout_mutation_lease(lease, metadata)
    except (FileNotFoundError, TimeoutError):
        return None


def adopt_inactive_checkout_mutation_lease(
    lease: CheckoutMutationLease,
    metadata: Mapping[str, Any],
    *,
    owner_active: Callable[[dict[str, Any]], bool],
    timeout_seconds: float = 1.0,
) -> CheckoutMutationLease | None:
    """CAS-adopt an exact dead-owner lease using a newly fenced identity."""

    normalized = dict(metadata)
    if str(normalized.get("lease_id") or "") == lease.lease_id:
        raise ValueError("adopted checkout mutation lease must rotate lease_id")
    try:
        with serialized_lock_update(
            lease.lock_path,
            timeout_seconds=timeout_seconds,
        ):
            current, identity = _read_checkout_lock(lease.lock_path)
            if (
                current is None
                or identity != (lease.device, lease.inode)
                or str(current.get("lease_id") or "") != lease.lease_id
            ):
                return None
            try:
                if owner_active(current):
                    return None
            except Exception:
                return None
            confirmed, confirmed_identity = _read_checkout_lock(lease.lock_path)
            if confirmed != current or confirmed_identity != identity:
                return None
            return _atomic_replace_checkout_mutation_lease(
                lease,
                normalized,
            )
    except (FileNotFoundError, TimeoutError):
        return None


def _try_publish_checkout_mutation_lease(
    lock_path: Path,
    metadata: Mapping[str, Any],
) -> tuple[
    CheckoutMutationLease | None,
    str,
    dict[str, Any] | None,
]:
    """Atomically publish complete lock metadata without an empty-file window."""

    normalized = dict(metadata)
    lease_id = str(normalized.get("lease_id") or "")
    if not lease_id:
        raise ValueError("checkout mutation lock metadata requires lease_id")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_name = tempfile.mkstemp(
        prefix=f".{lock_path.name}.",
        suffix=".pending",
        dir=lock_path.parent,
    )
    temp_path = Path(temp_name)
    try:
        fchmod = getattr(os, "fchmod", None)
        if fchmod is not None:
            fchmod(temp_fd, 0o600)
        data = json.dumps(
            normalized,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        offset = 0
        while offset < len(data):
            written = os.write(temp_fd, data[offset:])
            if written <= 0:
                raise OSError("short write while publishing checkout mutation lease")
            offset += written
        os.fsync(temp_fd)
        # Capture the identity from the file descriptor we exclusively own.
        # Looking up the destination after publication could instead bind the
        # lease to a replacement installed by another process.
        published_stat = os.fstat(temp_fd)
        published_identity = (
            int(published_stat.st_dev),
            int(published_stat.st_ino),
        )
        try:
            os.link(temp_path, lock_path)
        except FileExistsError:
            existing, _identity = _read_checkout_lock(lock_path)
            return None, "lock_exists", existing
        except OSError:
            return None, "lock_publication_failed", None
        try:
            destination_stat = lock_path.stat(follow_symlinks=False)
        except OSError:
            return None, "lock_publication_lost", None
        if (
            int(destination_stat.st_dev),
            int(destination_stat.st_ino),
        ) != published_identity:
            return None, "lock_publication_lost", None
        return (
            CheckoutMutationLease(
                lock_path=lock_path,
                metadata=normalized,
                device=published_identity[0],
                inode=published_identity[1],
            ),
            "acquired",
            None,
        )
    finally:
        if temp_fd >= 0:
            os.close(temp_fd)
        temp_path.unlink(missing_ok=True)


def acquire_checkout_mutation_lease(
    lock_path: Path,
    metadata: Mapping[str, Any],
    *,
    owner_active: Callable[[dict[str, Any]], bool],
    timeout_seconds: float = 0.0,
    poll_seconds: float = 0.05,
) -> tuple[
    CheckoutMutationLease | None,
    str,
    dict[str, Any] | None,
    float,
]:
    """Acquire an atomic lease, waiting boundedly and clearing valid stale owners."""

    started = time.monotonic()
    deadline = started + max(0.0, float(timeout_seconds))
    last_reason = "lock_unavailable"
    last_owner: dict[str, Any] | None = None
    cleared_owner: dict[str, Any] | None = None
    while True:
        lease, reason, existing = _try_publish_checkout_mutation_lease(
            lock_path,
            metadata,
        )
        if lease is not None:
            return (
                lease,
                "acquired",
                cleared_owner,
                max(0.0, time.monotonic() - started),
            )
        last_reason = reason
        last_owner = existing
        if (
            reason == "lock_exists"
            and existing
            and remove_inactive_checkout_mutation_lock(
                lock_path,
                expected_metadata=existing,
                owner_active=owner_active,
                timeout_seconds=min(
                    1.0,
                    max(0.0, deadline - time.monotonic()),
                ),
            )
        ):
            cleared_owner = dict(existing)
            continue
        remaining = deadline - time.monotonic()
        if reason != "lock_exists" or remaining <= 0:
            return (
                None,
                last_reason,
                last_owner,
                max(0.0, time.monotonic() - started),
            )
        time.sleep(
            min(
                max(0.001, float(poll_seconds)),
                remaining,
            )
        )


def remove_inactive_checkout_mutation_lock(
    lock_path: Path,
    *,
    expected_metadata: Mapping[str, Any],
    owner_active: Callable[[dict[str, Any]], bool],
    timeout_seconds: float = 1.0,
) -> bool:
    """Remove only the same fully published lock after rechecking its owner."""

    expected = dict(expected_metadata)
    expected_lease_id = str(expected.get("lease_id") or "")
    if not expected:
        # An empty or malformed record can be an in-flight pre-lease publisher.
        # Valid, nonempty legacy JSON remains reclaimable for upgrade safety.
        return False
    try:
        with serialized_lock_update(
            lock_path,
            timeout_seconds=timeout_seconds,
        ):
            current, identity = _read_checkout_lock(lock_path)
            if (
                current is None
                or identity is None
                or current != expected
                or (expected_lease_id and str(current.get("lease_id") or "") != expected_lease_id)
            ):
                return False
            try:
                if owner_active(current):
                    return False
            except Exception:
                # Owner validation is a safety boundary.  An inconclusive
                # liveness probe must preserve the incumbent record.
                return False
            confirmed, confirmed_identity = _read_checkout_lock(lock_path)
            if confirmed != current or confirmed_identity != identity:
                return False
            lock_path.unlink()
            return True
    except (FileNotFoundError, TimeoutError):
        return False


def release_checkout_mutation_lease(
    lease: CheckoutMutationLease,
    *,
    timeout_seconds: float = 1.0,
    require_exact_metadata: bool = False,
) -> bool:
    """Idempotently release only the exact lease acquired by the caller.

    A missing lock is already released.  Treating that state as failure leaves
    a daemon's in-memory ``release_pending`` context permanently wedged after
    another fenced transaction has legitimately reclaimed and removed the
    durable record.  Existing replacement or malformed records still fail
    closed and are never removed by this caller. Source-maintenance callers
    can also require the complete metadata to match at the unlink boundary.
    """

    try:
        with serialized_lock_update(
            lease.lock_path,
            timeout_seconds=timeout_seconds,
        ):
            current, identity = _read_checkout_lock(lease.lock_path)
            if current is None and not lease.lock_path.exists():
                return True
            if (
                current is None
                or identity != (lease.device, lease.inode)
                or str(current.get("lease_id") or "") != lease.lease_id
                or (require_exact_metadata and current != dict(lease.metadata))
            ):
                return False
            lease.lock_path.unlink()
            return True
    except (FileNotFoundError, TimeoutError):
        return False


def checkout_lock_owner_is_active(
    metadata: dict[str, Any],
    *,
    expected_kind: str,
    expected_repo_root: Path | None = None,
    process_command_line: Any,
    process_is_running: Any,
) -> bool:
    """Return whether lock metadata still belongs to a live compatible process."""

    kind = str(metadata.get("kind") or "")
    if kind and kind != expected_kind:
        return False
    if expected_repo_root is not None:
        repository_match = checkout_lock_repository_matches(
            metadata,
            expected_repo_root,
        )
        if repository_match is False:
            return False
        if repository_match is None:
            # Repository identity is part of lease ownership. An inability to
            # prove it must preserve the incumbent record, even when its PID
            # is unavailable, so uncertainty cannot become lock theft.
            return True
    # A protected mutation recovery record is an intentionally retained
    # durable fence, not an ordinary process lease.  Its owning daemon may
    # have exited after changing a generated board.  Preserve it so the next
    # compatible daemon can CAS-adopt and repair it instead of treating it as
    # stale process metadata.
    if metadata.get("protected_recovery_required") is True:
        return True
    try:
        pid = int(metadata.get("pid") or 0)
    except (TypeError, ValueError):
        return False
    if not process_is_running(pid):
        return False
    owner_script = str(metadata.get("owner_script") or "")
    command_line = process_command_line(pid)
    if owner_script and command_line and owner_script not in command_line:
        # Module launches (``python -m package.worker``) expose the module
        # name, not the source filename, in argv.
        owner_module_stem = Path(owner_script).stem
        if not owner_module_stem or owner_module_stem not in command_line:
            return False
    return True


UNHELD_GIT_CONTROL_LOCK_NAMES: Final = ("index.lock", "HEAD.lock")


def git_lock_inode_is_open(
    lock_path: Path,
    *,
    proc_root: Path = Path("/proc"),
) -> bool | None:
    """Return whether any process still holds ``lock_path`` open.

    Git's lock files are empty even while a live ``update-ref`` /
    ``update-index`` child owns them. After SIGTERM or reboot those fds
    vanish and leftover 0-byte files brick exclusive-owner admission.
    ``None`` means ``/proc`` could not prove the answer; callers fail closed.
    """

    try:
        identity = lock_path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return None
    if not stat_module.S_ISREG(identity.st_mode) or stat_module.S_ISLNK(
        identity.st_mode
    ):
        return None
    if not proc_root.exists():
        return None
    target = (int(identity.st_dev), int(identity.st_ino))
    try:
        entries = tuple(proc_root.iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.name.isdigit():
            continue
        fd_dir = entry / "fd"
        try:
            descriptors = tuple(fd_dir.iterdir())
        except OSError:
            continue
        for descriptor in descriptors:
            try:
                observed = os.stat(descriptor, follow_symlinks=True)
            except OSError:
                continue
            if (int(observed.st_dev), int(observed.st_ino)) == target:
                return True
    return False


def reclaim_unheld_empty_git_lock_files(
    lock_paths: Sequence[Path],
    *,
    proc_root: Path = Path("/proc"),
) -> dict[str, Any]:
    """Unlink leftover empty Git control locks with no live file holder.

    Non-empty lock files are left in place so a foreign/malformed lock still
    fails closed. Empty unheld locks are the post-reboot / post-SIGTERM
    git-guard leftover that otherwise raises ``candidate Git guard is
    contended`` after a 10s wait.
    """

    removed: list[str] = []
    skipped: list[dict[str, Any]] = []
    for raw in lock_paths:
        path = Path(raw)
        try:
            identity = path.lstat()
        except FileNotFoundError:
            skipped.append({"path": str(path), "reason": "absent"})
            continue
        except OSError as exc:
            skipped.append(
                {
                    "path": str(path),
                    "reason": "stat_failed",
                    "error_type": type(exc).__name__,
                }
            )
            continue
        if (
            not stat_module.S_ISREG(identity.st_mode)
            or stat_module.S_ISLNK(identity.st_mode)
            or identity.st_uid != os.geteuid()
            or identity.st_nlink != 1
        ):
            skipped.append({"path": str(path), "reason": "unsafe_identity"})
            continue
        if int(identity.st_size) != 0:
            skipped.append({"path": str(path), "reason": "nonempty"})
            continue
        holder = git_lock_inode_is_open(path, proc_root=proc_root)
        if holder is None:
            skipped.append({"path": str(path), "reason": "holder_unknown"})
            continue
        if holder is True:
            skipped.append({"path": str(path), "reason": "held"})
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            skipped.append({"path": str(path), "reason": "absent"})
            continue
        except OSError as exc:
            skipped.append(
                {
                    "path": str(path),
                    "reason": "unlink_failed",
                    "error_type": type(exc).__name__,
                }
            )
            continue
        removed.append(str(path))
    return {"removed": removed, "skipped": skipped}
