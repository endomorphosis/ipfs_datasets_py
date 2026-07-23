"""Lean/Elan runtime resolution and supervisor-owned execution.

All Lean and Lake invocations should enter through :func:`run_lean_process`
or the generic Hammer lifecycle runner.  Resolution also avoids repeatedly
entering the Elan proxy and conservatively clears only old lock files on
which no process currently holds an advisory lock.
"""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
import shutil
from typing import Mapping, Optional, Sequence

from ipfs_datasets_py.logic.hammers.process_lifecycle import (
    ProcessExecutionResult,
    ProcessKind,
    ProcessLimits,
    get_process_supervisor,
    recover_stale_elan_locks,
    supervised_temporary_directory,
)


def resolve_lean_executable(explicit: Optional[str] = None) -> str:
    """Return an installed Lean binary, bypassing the Elan proxy if possible."""

    if explicit:
        return str(explicit)
    return _resolve_default_lean_executable()


@lru_cache(maxsize=1)
def _resolve_default_lean_executable() -> str:
    candidate = shutil.which("lean") or ""
    if not candidate:
        return ""

    elan = shutil.which("elan") or ""
    if elan and Path(elan).parent == Path(candidate).parent:
        elan_home = Path(os.getenv("ELAN_HOME", "~/.elan")).expanduser()
        # Removal requires both age and a successful nonblocking advisory
        # lock, so this cannot interfere with an active Elan operation.
        recover_stale_elan_locks(elan_home, stale_after_seconds=300.0)
        result = get_process_supervisor().run(
            [elan, "which", "lean"],
            kind=ProcessKind.TOOLCHAIN,
            limits=ProcessLimits(
                wall_time_seconds=2.0,
                graceful_shutdown_seconds=0.25,
                forced_cleanup_seconds=0.5,
            ),
        )
        resolved = (result.stdout or "").strip()
        if result.returncode == 0 and _is_executable(resolved):
            return resolved

        # A rolling channel can block on an update check when the network is
        # unavailable.  Prefer an already-installed toolchain to invoking the
        # proxy for every proof.
        installed = [
            path
            for path in (elan_home / "toolchains").glob("*/bin/lean")
            if _is_executable(str(path))
        ]
        if installed:
            return str(max(installed, key=lambda path: path.stat().st_mtime_ns))

    return candidate


def run_lean_process(
    command: Sequence[str],
    *,
    timeout: float,
    cwd: Optional[str | Path] = None,
    input_text: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    cancel_event=None,
    lease=None,
    cpu_seconds: Optional[float] = None,
    memory_mb: Optional[int] = None,
) -> ProcessExecutionResult:
    """Run a literal Lean/Lake argv under the shared lifecycle supervisor."""

    executable_name = Path(command[0]).name.lower() if command else ""
    kind = ProcessKind.LAKE if executable_name == "lake" else ProcessKind.LEAN
    return get_process_supervisor().run(
        command,
        kind=kind,
        limits=ProcessLimits(
            wall_time_seconds=max(0.001, float(timeout)),
            cpu_seconds=cpu_seconds,
            memory_mb=memory_mb,
        ),
        cwd=cwd,
        input_text=input_text,
        env=env,
        cancel_event=cancel_event,
        lease=lease,
    )


def _is_executable(path: str) -> bool:
    return bool(path) and Path(path).is_file() and os.access(path, os.X_OK)


__all__ = [
    "resolve_lean_executable",
    "run_lean_process",
    "recover_stale_elan_locks",
    "supervised_temporary_directory",
]
