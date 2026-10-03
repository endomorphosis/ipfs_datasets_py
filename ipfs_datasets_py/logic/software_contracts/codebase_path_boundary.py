"""Ephemeral descriptor-relative path witnesses for bounded source reads.

These witnesses never enter content identities. Native Git still consumes
pathname configuration and cwd; this helper governs Python acquisition only.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat

MAX_COMPONENTS = 128
MAX_PATH_BYTES = 65536


class PathBoundaryError(ValueError):
    """A path component cannot be acquired without following or racing."""


class PathCleanupError(RuntimeError):
    """Descriptor lifecycle failure; never downgrade this to opaque input."""


def _identity(info):
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


class PathBoundary:
    """Hold and reobserve each directory binding from the filesystem root."""

    def __init__(self, path, *, directory=False, allow_missing=False):
        path = Path(path)
        raw = os.fsencode(path)
        if (not path.is_absolute() or b"\0" in raw or len(raw) > MAX_PATH_BYTES
                or ".." in path.parts or len(path.parts) > MAX_COMPONENTS):
            raise PathBoundaryError("bounded absolute path without parent traversal required")
        if not all(hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")):
            raise PathBoundaryError("descriptor-relative no-follow acquisition unavailable")
        self.path = path
        self.directory = directory
        self.allow_missing = allow_missing
        components = tuple(os.fsencode(part) for part in path.parts[1:])
        self.components = components if directory else components[:-1]
        self.leaf = None if directory else (components[-1] if components else None)
        if not directory and self.leaf is None:
            raise PathBoundaryError("regular leaf path required")
        self._fds = []
        self._bindings = []
        self._missing = None

    @property
    def missing(self):
        return self._missing is not None

    @property
    def signature(self):
        return tuple((name.hex(), *_identity(os.fstat(fd))) for _, name, fd in self._bindings)

    def __enter__(self):
        if self._fds:
            raise PathBoundaryError("path witness cannot be reentered")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            self._fds.append(os.open(b"/", flags))
            for name in self.components:
                parent = self._fds[-1]
                try:
                    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    if not self.allow_missing:
                        raise
                    self._missing = (parent, name)
                    break
                if not stat.S_ISDIR(before.st_mode):
                    raise PathBoundaryError("unsafe path ancestor is not a directory")
                fd = os.open(name, flags, dir_fd=parent)
                self._fds.append(fd)
                if _identity(before) != _identity(os.fstat(fd)):
                    raise PathBoundaryError("path ancestor changed during acquisition")
                self._bindings.append((parent, name, fd))
            self.verify()
            return self
        except OSError as exc:
            self.close()
            if isinstance(exc, FileNotFoundError):
                raise
            raise PathBoundaryError("path ancestor could not be opened without following") from exc
        except BaseException:
            self.close()
            raise

    def verify(self):
        if not self._fds:
            raise PathBoundaryError("active path witness required")
        try:
            for parent, name, fd in self._bindings:
                current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if _identity(current) != _identity(os.fstat(fd)) or not stat.S_ISDIR(current.st_mode):
                    raise PathBoundaryError("path ancestor binding changed")
            if self._missing is not None:
                parent, name = self._missing
                try:
                    os.stat(name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise PathBoundaryError("missing path ancestor appeared during acquisition")
        except OSError as exc:
            raise PathBoundaryError("path ancestor binding became unavailable") from exc

    def stat_leaf(self):
        self.verify()
        if self.missing:
            raise FileNotFoundError(str(self.path))
        return os.stat(self.leaf, dir_fd=self._fds[-1], follow_symlinks=False)

    def open_leaf(self):
        self.verify()
        if self.missing:
            raise FileNotFoundError(str(self.path))
        return os.open(self.leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                       dir_fd=self._fds[-1])

    def close(self):
        failures = []
        while self._fds:
            try:
                os.close(self._fds.pop())
            except OSError as exc:
                failures.append(exc)
        self._bindings.clear()
        self._missing = None
        if failures:
            raise PathCleanupError("path descriptor cleanup failed") from failures[0]

    def __exit__(self, exception_type, *_):
        try:
            if exception_type is None:
                self.verify()
        finally:
            self.close()


__all__ = ["PathBoundary", "PathBoundaryError", "PathCleanupError"]
