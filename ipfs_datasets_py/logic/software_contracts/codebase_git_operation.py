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

from .codebase_path_boundary import PathBoundary, PathBoundaryError


class GitOperationError(ValueError):
    """A scan Git context or bounded native result is outside its profile."""


_ACTIVE = ContextVar("codebase_git_operation", default=None)
MAX_METADATA_BYTES = 512 * 1024
MAX_NATIVE_MEMORY_BYTES = 256 * 1024 * 1024
_SAFE_CONFIG = ("--no-pager", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
                "-c", "gc.auto=0", "-c", "maintenance.auto=false",
                "-c", "protocol.allow=never")
_REDIRECTS = {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
              "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
              "GIT_NAMESPACE", "GIT_EXEC_PATH", "GIT_SSH", "GIT_SSH_COMMAND",
              "GIT_PROXY_COMMAND", "GIT_EXTERNAL_DIFF", "GIT_CONFIG"}
_CONFIG_QUERY = ("config", "--null", "--includes", "--show-origin", "--show-scope", "--list")


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
        _CONFIG_QUERY,
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
        _require(not any(key.startswith(("LD_", "DYLD_", "GIT_TRACE")) or key in _REDIRECTS
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
        environment.update(GIT_ALLOW_PROTOCOL="", GIT_NO_LAZY_FETCH="1",
                           GIT_TRACE2="0", GIT_TRACE2_PERF="0", GIT_TRACE2_EVENT="0")
        self.environment = MappingProxyType(environment)
        self._temporary = None
        self._token = None
        self._root_boundary = None
        self._config_bytes = None

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
            try:
                self._root_boundary = PathBoundary(self.root, directory=True).__enter__()
            except (OSError, PathBoundaryError) as exc:
                raise GitOperationError("repository root ancestors are unsafe") from exc
            self._token = _ACTIVE.set(self)
            self._config_bytes = self._read_configuration()
        except BaseException:
            self._config_bytes = None
            if self._token is not None:
                _ACTIVE.reset(self._token)
                self._token = None
            try:
                if self._root_boundary is not None:
                    self._root_boundary.close()
                    self._root_boundary = None
            finally:
                self._temporary = None
                temporary.cleanup()
            raise
        return self

    def __exit__(self, exception_type, *_):
        try:
            if exception_type is None:
                self.verify_configuration()
        finally:
            self._config_bytes = None
            try:
                _ACTIVE.reset(self._token)
                self._token = None
                boundary, self._root_boundary = self._root_boundary, None
                boundary.close()
            finally:
                temporary, self._temporary = self._temporary, None
                temporary.cleanup()

    def remaining(self):
        seconds = self.checkpoint()
        _require(type(seconds) in (int, float) and math.isfinite(seconds) and seconds > 0,
                 "finite positive remaining Git deadline required")
        _require(_configuration(os.environ) == self.configuration,
                 "Git configuration environment changed during scan")
        if self._root_boundary is not None:
            try:
                self._root_boundary.verify()
            except PathBoundaryError as exc:
                raise GitOperationError("repository root ancestor binding changed") from exc
        return seconds

    def _execute(self, args, output_bytes):
        from ..backends.process import ProcessInvocation, SubprocessExecutor, ToolRunLimits, ToolRuntime
        _require(_ACTIVE.get() is self and self._root_boundary is not None
                 and self._temporary is not None, "active admitted Git context required")
        timeout = min(10.0, self.remaining())
        limits = ToolRunLimits(timeout_seconds=timeout, cpu_seconds=timeout,
            memory_bytes=self.native_memory_bytes, resident_memory_bytes=self.native_memory_bytes,
            max_input_bytes=1, max_output_bytes=output_bytes, max_workspace_bytes=65536)
        invocation = ProcessInvocation(
            argv=(self.executable, "-C", str(self.root), *_SAFE_CONFIG, *args),
            runtime=ToolRuntime.NATIVE, cwd=self.root, environment=self.environment,
            stdin=None, limits=limits)
        raw = SubprocessExecutor().execute(invocation, cancellation=self.cancellation)
        self.remaining()
        _require(type(raw.returncode) is int and type(raw.stdout) is bytes and type(raw.stderr) is bytes
                 and not any((raw.error, raw.timed_out, raw.cancelled, raw.output_truncated,
                              raw.resource_exhausted, raw.process_tree_terminated)),
                 "Git query failed or exceeded its bounded process profile")
        return subprocess.CompletedProcess(invocation.argv, raw.returncode, raw.stdout, raw.stderr)

    def _read_configuration(self):
        result = self._execute(_CONFIG_QUERY, MAX_METADATA_BYTES)
        _require(result.returncode == 0 and result.stderr == b"", "Git configuration preflight failed")
        records = result.stdout.split(b"\0")
        _require(records[-1] == b"" and (len(records) - 1) % 3 == 0,
                 "ordered Git configuration records are malformed")
        for offset in range(0, len(records) - 1, 3):
            scope, origin, entry = records[offset:offset + 3]
            key = entry.partition(b"\n")[0].lower()
            _require(scope in {b"system", b"global", b"local", b"worktree", b"command"}
                     and origin and key, "Git configuration origin or scope is malformed")
            _require(not (key.startswith((b"filter.", b"trace2."))
                          or key in {b"extensions.partialclone", b"core.alternaterefscommand"}
                          or (key.startswith(b"remote.") and key.endswith(b".promisor"))),
                     "executable filter, trace, alternate-ref or promisor configuration is outside scan profile")
        return result.stdout

    def verify_configuration(self):
        _require(_ACTIVE.get() is self and self._root_boundary is not None,
                 "active admitted Git context required")
        _require(self._config_bytes is not None, "admitted Git configuration witness required")
        _require(self._read_configuration() == self._config_bytes,
                 "Git configuration records changed during scan")

    def run(self, root, arguments, *, max_output_bytes=None):
        _require(_ACTIVE.get() is self and Path(root).resolve() == self.root,
                 "Git query must use its active exact repository root")
        args = _arguments(arguments)
        output_bytes = (self.max_file_bytes + 1 if args[:2] == ("cat-file", "blob")
                        else MAX_METADATA_BYTES) if max_output_bytes is None else max_output_bytes
        _require(type(output_bytes) is int and 0 < output_bytes <= MAX_METADATA_BYTES,
                 "finite Git output cap required")
        self.verify_configuration()
        if args == ("status", "--porcelain", "-z", "--untracked-files=all"):
            args = (*args, "--ignore-submodules=all")
        result = self._execute(args, output_bytes)
        self.verify_configuration()
        return result


__all__ = ["GitOperationError", "GitScanOperation", "current_git_operation"]
