#!/usr/bin/env python3
"""Isolated, paired-source entry point for the detached multi-supervisor."""

import os
import stat
import subprocess
import sys
import types
from pathlib import Path, PurePosixPath

if not (
    sys.flags.isolated == 1
    and sys.flags.ignore_environment == 1
    and sys.flags.no_site == 1
    and sys.flags.no_user_site == 1
    and sys.flags.safe_path
    and sys.dont_write_bytecode
):
    raise RuntimeError("multi-supervisor entry requires Python -I -S -B")
_PYTHON = Path(sys.executable).resolve(strict=True)
_PYTHON_STAT = _PYTHON.stat()
if (
    _PYTHON != Path("/usr/bin/python3.12")
    or _PYTHON_STAT.st_uid != 0
    or _PYTHON_STAT.st_mode & 0o022
):
    raise RuntimeError("multi-supervisor entry requires trusted system Python")

_ENTRY_PATH = Path(__file__).resolve()
REPO_ROOT = _ENTRY_PATH.parents[3]
_GIT = Path("/usr/bin/git").resolve(strict=True)
_GIT_STAT = _GIT.stat()
if (
    _GIT != Path("/usr/bin/git")
    or not stat.S_ISREG(_GIT_STAT.st_mode)
    or _GIT_STAT.st_uid != 0
    or _GIT_STAT.st_mode & 0o022
):
    raise RuntimeError("multi-supervisor entry requires trusted system Git")


def _git_bytes(*arguments: str) -> bytes:
    try:
        result = subprocess.run(
            [
                str(_GIT),
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.untrackedCache=false",
                "-c",
                "core.attributesFile=/dev/null",
                "-c",
                "core.excludesFile=/dev/null",
                *arguments,
            ],
            cwd=REPO_ROOT,
            env={
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "HOME": "/nonexistent",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PATH": "/usr/bin:/bin",
            },
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("control source Git inspection failed") from exc
    if result.returncode != 0:
        raise RuntimeError("control source Git inspection failed")
    return result.stdout


def _attest_tracked_source(path: Path) -> bytes:
    try:
        relative = path.relative_to(REPO_ROOT).as_posix()
        top = Path(
            _git_bytes("rev-parse", "--show-toplevel").decode("utf-8").strip()
        ).resolve()
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("control source is outside the exact Git worktree") from exc
    if top != REPO_ROOT:
        raise RuntimeError("control source is outside the exact Git worktree")
    index_record = _git_bytes("ls-files", "-v", "-z", "--", relative)
    if index_record != b"H " + os.fsencode(relative) + b"\0":
        raise RuntimeError("control source has non-default index flags or is untracked")
    if _git_bytes("status", "--porcelain=v1", "--untracked-files=all", "--", relative):
        raise RuntimeError("control source is not clean")
    try:
        path_stat = path.lstat()
        if not stat.S_ISREG(path_stat.st_mode):
            raise OSError("control source is not a regular file")
        source = path.read_bytes()
    except OSError as exc:
        raise RuntimeError("control source is unreadable") from exc
    if source != _git_bytes("show", f"HEAD:{relative}"):
        raise RuntimeError("control source does not match the exact HEAD blob")

    target = PurePosixPath(relative)
    for arguments in (
        (
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            target.parent.as_posix(),
        ),
        (
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "-z",
            "--",
            target.parent.as_posix(),
        ),
    ):
        for raw_candidate in _git_bytes(*arguments).rstrip(b"\0").split(b"\0"):
            if not raw_candidate:
                continue
            candidate = PurePosixPath(os.fsdecode(raw_candidate))
            same_basename = candidate.name.startswith(f"{target.stem}.")
            direct_shadow = (
                candidate.parent == target.parent
                and candidate.name.endswith((".pyc", ".so", ".pyd"))
            )
            cache_shadow = (
                candidate.parent == target.parent / "__pycache__"
                and candidate.name.endswith(".pyc")
            )
            if same_basename and (direct_shadow or cache_shadow):
                raise RuntimeError(
                    "control source has an ignored or untracked import shadow"
                )
    return source


_ENTRY_SOURCE = _attest_tracked_source(_ENTRY_PATH)
_BOOTSTRAP_PATH = _ENTRY_PATH.parent / "paired_accelerator_bootstrap.py"
_BOOTSTRAP_SOURCE = _attest_tracked_source(_BOOTSTRAP_PATH)
_BOOTSTRAP_MODULE = types.ModuleType("_paired_accelerator_bootstrap_source")
_BOOTSTRAP_MODULE.__file__ = str(_BOOTSTRAP_PATH)
_BOOTSTRAP_MODULE.__package__ = ""
sys.modules[_BOOTSTRAP_MODULE.__name__] = _BOOTSTRAP_MODULE
# Execute only the exact helper bytes already compared with the current HEAD blob.
exec(  # noqa: S102
    compile(
        _BOOTSTRAP_SOURCE,
        str(_BOOTSTRAP_PATH),
        "exec",
        dont_inherit=True,
    ),
    _BOOTSTRAP_MODULE.__dict__,
)
attest_imported_module = _BOOTSTRAP_MODULE.attest_imported_module
bootstrap_from_environment = _BOOTSTRAP_MODULE.bootstrap_from_environment

_PAIRED_BINDING = bootstrap_from_environment(REPO_ROOT)
if _PAIRED_BINDING is None:
    raise RuntimeError("multi-supervisor entry requires a paired binding")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(1, str(REPO_ROOT))

from ipfs_accelerate_py.agent_supervisor.runtime import (
    multi_supervisor_runner as _multi_supervisor,
)

attest_imported_module(
    _PAIRED_BINDING,
    _multi_supervisor.__file__,
    expected_relative=(
        "ipfs_accelerate_py/agent_supervisor/runtime/multi_supervisor_runner.py"
    ),
)


if __name__ == "__main__":
    raise SystemExit(_multi_supervisor.main(sys.argv[1:]))
