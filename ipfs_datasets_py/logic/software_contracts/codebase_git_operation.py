"""One source-bound, byte-preserving Git context for a structural scan.

This adapter owns input validation around the shared raw process executor. It
does not change generic tool-runner HOME isolation or standalone snapshotting.
Admission, the deadline and cancellation are supplied by the scan owner.
"""
from __future__ import annotations

from contextvars import ContextVar
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import MappingProxyType


class GitOperationError(ValueError):
    """A scan Git context or bounded native result is outside its profile."""


_ACTIVE = ContextVar("codebase_git_operation", default=None)
MAX_METADATA_BYTES = 512 * 1024
MAX_NATIVE_MEMORY_BYTES = 256 * 1024 * 1024
_SAFE_CONFIG = ("-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
                "-c", "gc.auto=0", "-c", "maintenance.auto=false",
                "-c", "protocol.allow=never")
_REDIRECTS = {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
              "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
              "GIT_NAMESPACE", "GIT_EXEC_PATH", "GIT_SSH", "GIT_SSH_COMMAND",
              "GIT_PROXY_COMMAND", "GIT_EXTERNAL_DIFF", "GIT_CONFIG"}


def _require(condition, message):
    if not condition:
        raise GitOperationError(message)


def _configuration(environment):
    return {key: value for key, value in environment.items()
            if key in {"HOME", "XDG_CONFIG_HOME", "PATH", "LANG", "LC_ALL", "LC_CTYPE"}
            or key.startswith(("GIT_", "LD_", "DYLD_"))}


def _arguments(arguments):
    _require(type(arguments) in (tuple, list) and 0 < len(arguments) <= 128
             and all(type(item) is str and item and "\0" not in item for item in arguments)
             and sum(len(os.fsencode(item)) + 1 for item in arguments) <= 65536,
             "bounded Git argument sequence required")
    args = tuple(arguments)
    fixed = {
        ("rev-parse", "--show-toplevel"), ("rev-parse", "--show-object-format"),
        ("rev-parse", "--git-dir"), ("rev-parse", "--verify", "--quiet", "HEAD"),
        ("rev-parse", "--verify", "HEAD"),
        ("symbolic-ref", "-q", "HEAD"), ("rev-list", "--max-count=1", "HEAD"),
        ("status", "--porcelain", "-z", "--untracked-files=all"),
        ("ls-files", "--stage", "-z"),
        ("ls-files", "-z", "--cached", "--others", "--exclude-standard"),
        ("config", "--path", "--null", "--get", "core.excludesfile"),
        ("rev-parse", "--git-path", "info/exclude"),
        ("ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", ".gitignore", "**/.gitignore"),
        ("ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--", ".gitignore", "**/.gitignore"),
    }
    if args in fixed:
        return args
    oid = None
    if len(args) == 2 and args[0] == "rev-parse" and args[1].endswith("^{tree}"):
        oid = args[1][:-7]
    elif len(args) == 4 and args[:3] in (("ls-tree", "-r", "-z"), ("rev-list", "--max-parents=0", "--reverse")):
        oid = args[3]
    elif len(args) == 3 and args[:2] in (("cat-file", "-s"), ("cat-file", "blob")):
        oid = args[2]
    _require(oid is not None and len(oid) in (40, 64)
             and all(character in "0123456789abcdef" for character in oid),
             "Git command is outside the read-only structural profile")
    return args


def current_git_operation():
    return _ACTIVE.get()


class GitScanOperation:
    """Freeze native configuration and scope it to one admitted exact root."""

    def __init__(self, root, *, checkpoint, cancellation, max_file_bytes, memory_mb):
        _require(callable(checkpoint) and callable(getattr(cancellation, "is_set", None)),
                 "admitted Git checkpoint and cancellation required")
        _require(type(max_file_bytes) is int and 0 < max_file_bytes <= 65536,
                 "bounded structural source size required")
        _require(type(memory_mb) is int and memory_mb > 0, "positive native reservation required")
        self.root = Path(root).resolve()
        self.checkpoint = checkpoint
        self.cancellation = cancellation
        self.max_file_bytes = max_file_bytes
        self.native_memory_bytes = min(MAX_NATIVE_MEMORY_BYTES, memory_mb * 1024 * 1024)
        environment = dict(os.environ)
        _require(all(type(key) is str and type(value) is str and key
                     and "\0" not in key + value and "=" not in key
                     for key, value in environment.items()), "native Git environment is malformed")
        _require(not any(key.startswith(("LD_", "DYLD_")) or key in _REDIRECTS
                         for key in environment), "native loader or Git redirect is outside scan profile")
        _require(sum(len(os.fsencode(key)) + len(os.fsencode(value)) + 2
                     for key, value in environment.items()) <= 131072,
                 "native Git environment exceeds its byte bound")
        executable = shutil.which("git", path=environment.get("PATH"))
        _require(executable is not None, "Git scan inspection is unavailable")
        self.executable = str(Path(executable).resolve(strict=True))
        _require(Path(self.executable).is_file() and os.access(self.executable, os.X_OK),
                 "regular executable Git target required")
        self.configuration = _configuration(environment)
        # Status may otherwise refresh the source index as an optional write.
        environment["GIT_OPTIONAL_LOCKS"] = "0"
        self.environment = MappingProxyType(environment)
        self._temporary = None
        self._token = None

    def __enter__(self):
        _require(self._token is None and self._temporary is None, "Git scan context cannot be reentered")
        self.remaining()
        temporary = tempfile.TemporaryDirectory(prefix="codebase-git-")
        try:
            environment = dict(self.environment)
            environment.update(TMPDIR=temporary.name, TMP=temporary.name, TEMP=temporary.name)
            _require(sum(len(os.fsencode(key)) + len(os.fsencode(value)) + 2
                         for key, value in environment.items()) <= 131072,
                     "private Git environment exceeds its byte bound")
            self.environment = MappingProxyType(environment)
            self._temporary = temporary
            self._token = _ACTIVE.set(self)
        except BaseException:
            temporary.cleanup()
            raise
        return self

    def __exit__(self, *_):
        try:
            _ACTIVE.reset(self._token)
        finally:
            self._token = None
            temporary, self._temporary = self._temporary, None
            temporary.cleanup()

    def remaining(self):
        seconds = self.checkpoint()
        _require(type(seconds) in (int, float) and math.isfinite(seconds) and seconds > 0,
                 "finite positive remaining Git deadline required")
        _require(_configuration(os.environ) == self.configuration,
                 "Git configuration environment changed during scan")
        return seconds

    def run(self, root, arguments, *, max_output_bytes=None):
        from ..backends.process import ProcessInvocation, SubprocessExecutor, ToolRunLimits, ToolRuntime
        _require(_ACTIVE.get() is self and Path(root).resolve() == self.root,
                 "Git query must use its active exact repository root")
        args = _arguments(arguments)
        output_bytes = (self.max_file_bytes + 1 if args[:2] == ("cat-file", "blob")
                        else MAX_METADATA_BYTES) if max_output_bytes is None else max_output_bytes
        _require(type(output_bytes) is int and 0 < output_bytes <= MAX_METADATA_BYTES,
                 "finite Git output cap required")
        timeout = min(10.0, self.remaining())
        limits = ToolRunLimits(timeout_seconds=timeout, cpu_seconds=timeout,
            memory_bytes=self.native_memory_bytes, resident_memory_bytes=self.native_memory_bytes,
            max_input_bytes=1, max_output_bytes=output_bytes, max_workspace_bytes=65536)
        invocation = ProcessInvocation(
            argv=(self.executable, "-C", str(self.root), *_SAFE_CONFIG, *args),
            runtime=ToolRuntime.NATIVE, cwd=self.root, environment=self.environment,
            stdin=None, limits=limits)
        raw = SubprocessExecutor().execute(invocation, cancellation=self.cancellation)
        self.remaining()  # Native cleanup must finish before checking current success.
        _require(type(raw.returncode) is int and type(raw.stdout) is bytes and type(raw.stderr) is bytes
                 and not any((raw.error, raw.timed_out, raw.cancelled, raw.output_truncated,
                              raw.resource_exhausted, raw.process_tree_terminated)),
                 "Git query failed or exceeded its bounded process profile")
        return subprocess.CompletedProcess(invocation.argv, raw.returncode, raw.stdout, raw.stderr)


__all__ = ["GitOperationError", "GitScanOperation", "current_git_operation"]
