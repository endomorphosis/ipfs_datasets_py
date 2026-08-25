#!/usr/bin/env python3
"""Source-checkout entry with refill policy mapping for configured boards."""

import os
import stat
import subprocess
import sys
import types
from pathlib import Path, PurePosixPath

_ENTRY_PATH = Path(__file__).resolve()
REPO_ROOT = _ENTRY_PATH.parents[3]
_PAIRED_CONFIGS = {
    (
        REPO_ROOT / "config/agent_supervisor_legal_corpora_reindex_scheduler.json"
    ).resolve(),
    (
        REPO_ROOT / "config/agent_supervisor_open_us_law_reindex_scheduler.json"
    ).resolve(),
}


def _selects_paired_legal_config(argv: list[str]) -> bool:
    for index, value in enumerate(argv):
        option, separator, inline_value = value.partition("=")
        if option == "--config" or (
            option.startswith("--") and "--config".startswith(option)
        ):
            config_value = inline_value if separator else None
            if config_value is None and index + 1 < len(argv):
                config_value = argv[index + 1]
            if config_value:
                config_path = Path(config_value)
                if not config_path.is_absolute():
                    config_path = REPO_ROOT / config_path
                if config_path.resolve() in _PAIRED_CONFIGS:
                    return True
    return False


_PAIRED_MODE = _selects_paired_legal_config(sys.argv[1:])
_GIT = Path("/usr/bin/git")
if _PAIRED_MODE:
    if not (
        sys.flags.isolated == 1
        and sys.flags.ignore_environment == 1
        and sys.flags.no_site == 1
        and sys.flags.no_user_site == 1
        and sys.flags.safe_path
        and sys.dont_write_bytecode
    ):
        raise RuntimeError("configured board scheduler requires Python -I -S -B")
    _PYTHON = Path(sys.executable).resolve(strict=True)
    _PYTHON_STAT = _PYTHON.stat()
    if (
        _PYTHON != Path("/usr/bin/python3.12")
        or _PYTHON_STAT.st_uid != 0
        or _PYTHON_STAT.st_mode & 0o022
    ):
        raise RuntimeError("configured board scheduler requires trusted system Python")

    _GIT = _GIT.resolve(strict=True)
    _GIT_STAT = _GIT.stat()
    if (
        _GIT != Path("/usr/bin/git")
        or not stat.S_ISREG(_GIT_STAT.st_mode)
        or _GIT_STAT.st_uid != 0
        or _GIT_STAT.st_mode & 0o022
    ):
        raise RuntimeError("configured board scheduler requires trusted system Git")


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


_PAIRED_BINDING = None
if _PAIRED_MODE:
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
    bootstrap_from_config_argv = _BOOTSTRAP_MODULE.bootstrap_from_config_argv
    _PAIRED_BINDING = bootstrap_from_config_argv(REPO_ROOT, sys.argv[1:])
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(1 if _PAIRED_BINDING is not None else 0, str(REPO_ROOT))

from ipfs_accelerate_py.agent_supervisor.runtime import (
    configured_board_scheduler as _scheduler,
)

if _PAIRED_MODE:
    attest_imported_module(
        _PAIRED_BINDING,
        _scheduler.__file__,
        expected_relative=(
            "ipfs_accelerate_py/agent_supervisor/runtime/configured_board_scheduler.py"
        ),
    )


_upstream_common_args = _scheduler.configured_board_common_args


def _configured_board_common_args(board, *, implement):
    """Map the bounded refill fields omitted by the pinned generic adapter."""

    args = list(_upstream_common_args(board, implement=implement))
    policy = board.payload.get("refill_policy", {})

    for enabled_key, negative_flag in (
        ("objective_task_janitor_enabled", "--no-objective-task-janitor"),
        (
            "objective_goal_completion_reconcile_enabled",
            "--no-objective-goal-completion-reconcile",
        ),
        ("objective_goal_migration_enabled", "--no-objective-goal-migration"),
    ):
        if policy.get(enabled_key) is True and negative_flag in args:
            args.remove(negative_flag)

    mappings = (
        ("--objective-scan-min-open-tasks", "minimum_open_tasks"),
        ("--objective-scan-max-findings", "maximum_findings_per_scan"),
        ("--objective-scan-cooldown-seconds", "cooldown_seconds"),
        ("--objective-refill-timeout-seconds", "scan_timeout_seconds"),
        ("--codebase-scan-min-open-tasks", "minimum_open_tasks"),
        ("--codebase-scan-max-findings", "maximum_findings_per_scan"),
        ("--codebase-scan-cooldown-seconds", "cooldown_seconds"),
        ("--codebase-refill-timeout-seconds", "scan_timeout_seconds"),
    )
    for flag, key in mappings:
        value = policy.get(key)
        if value is not None:
            args.extend((flag, str(value)))
    return tuple(args)


_scheduler.configured_board_common_args = _configured_board_common_args
main = _scheduler.main


if __name__ == "__main__":
    raise SystemExit(main())
