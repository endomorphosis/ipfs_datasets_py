"""Private transaction ownership for Hyper installer entry points.

The facade's outer lease is separate. Nested Hyper calls share this transaction
only in the same process and thread, and retain backups until publication passes.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import os
from pathlib import Path
import shutil
import stat
import tempfile
import threading
import time

_ACTIVE: ContextVar[tuple | None] = ContextVar("hyper_install_transaction", default=None)
_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _checkpoint() -> float:
    from .install_control import installation_checkpoint
    return installation_checkpoint("Hyper installation transaction")


def _remove(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink(missing_ok=True)
    else:
        shutil.rmtree(path)


class InstallTransaction:
    def __init__(self) -> None:
        self.replacements: list[tuple[Path, Path | None]] = []
        self.failed = False

    def replace_tree(self, source: Path, destination: Path) -> None:
        _checkpoint()
        destination.parent.mkdir(parents=True, exist_ok=True)
        backup = None
        if destination.is_symlink():
            raise ValueError("Hyper install destination must not be a symlink")
        if destination.exists():
            if not destination.is_dir():
                raise ValueError("Hyper install destination must be a directory")
            backup = Path(tempfile.mkdtemp(prefix=f".{destination.name}-backup-", dir=destination.parent))
            backup.rmdir()
            destination.replace(backup)
        try:
            source.replace(destination)
        except BaseException:
            if backup is not None:
                backup.replace(destination)
            raise
        self.replacements.append((destination, backup))

    def replace_file(self, source: Path, destination: Path) -> None:
        """Keep the live regular launcher intact until one atomic replacement."""
        _checkpoint()
        backup = None
        try:
            details = destination.lstat()
        except FileNotFoundError:
            details = None
        if details is not None:
            if not stat.S_ISREG(details.st_mode):
                raise ValueError("Hyper launcher must be a regular file, not a symlink")
            descriptor, name = tempfile.mkstemp(prefix=f".{destination.name}-backup-", dir=destination.parent)
            os.close(descriptor)
            backup = Path(name)
            backup.unlink()
            # Hard-link the existing inode without reading or following it.
            os.link(destination, backup, follow_symlinks=False)
            if not stat.S_ISREG(backup.lstat().st_mode):
                backup.unlink()
                raise ValueError("Hyper launcher changed while preparing publication")
        try:
            os.replace(source, destination)
        except BaseException:
            if backup is not None:
                backup.unlink(missing_ok=True)
            raise
        self.replacements.append((destination, backup))

    def rollback(self) -> None:
        errors = []
        for destination, backup in reversed(self.replacements):
            try:
                if backup is not None and backup.is_file():
                    os.replace(backup, destination)
                else:
                    _remove(destination)
                    if backup is not None:
                        backup.replace(destination)
            except OSError as exc:
                errors.append(exc)
        if errors:
            raise OSError("Hyper install rollback failed; backups retained") from errors[0]

    def commit(self) -> None:
        _checkpoint()
        # Publication and its identity audit have succeeded. Backup cleanup is
        # best-effort: a cleanup error cannot roll back an already removed copy.
        for _, backup in self.replacements:
            if backup is not None:
                try:
                    _remove(backup)
                except OSError:
                    pass


def current_transaction() -> InstallTransaction | None:
    active = _ACTIVE.get()
    if active is None or active[:2] != (os.getpid(), threading.get_ident()):
        return None
    return active[3]


@contextmanager
def installation_transaction(root: Path, tool_id: str):
    key = (str(root), tool_id)
    active = _ACTIVE.get()
    if active is not None and active[:3] == (os.getpid(), threading.get_ident(), key):
        yield active[3]
        return
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(key, threading.Lock())
    while True:
        remaining = _checkpoint()
        if lock.acquire(timeout=min(.05, max(0.0, remaining))):
            break
    descriptor = None
    acquired = False
    try:
        _checkpoint()
        if root.resolve() != root:
            raise ValueError("Hyper installer root must not contain symlink components")
        directory = root / ".install-locks"
        if directory.is_symlink() or directory.resolve() != directory:
            raise ValueError("Hyper installer lock directory must not be symlinked")
        directory.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(directory / f"hyper-{tool_id}.lock", flags, 0o600)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("Hyper installer lock must be a regular file")
        if os.name != "posix":
            raise ValueError("Hyper vendor installation requires POSIX file locking")
        import fcntl
        while True:
            remaining = _checkpoint()
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                time.sleep(min(.05, max(0.0, remaining)))
        transaction = InstallTransaction()
        token = _ACTIVE.set((os.getpid(), threading.get_ident(), key, transaction))
        rollback_started = False
        try:
            yield transaction
            if transaction.failed:
                rollback_started = True
                transaction.rollback()
            else:
                transaction.commit()
        except BaseException:
            if not rollback_started:
                transaction.rollback()
            raise
        finally:
            _ACTIVE.reset(token)
    finally:
        if descriptor is not None:
            try:
                if acquired:
                    import fcntl
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
        lock.release()
