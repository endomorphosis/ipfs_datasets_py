"""Lean executable resolution without repeated elan update checks."""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
import shutil
import subprocess
from typing import Optional


def resolve_lean_executable(explicit: Optional[str] = None) -> str:
    """Return an installed Lean binary, bypassing the elan proxy when possible."""

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
        try:
            result = subprocess.run(
                [elan, "which", "lean"],
                capture_output=True,
                check=False,
                text=True,
                timeout=2.0,
            )
            resolved = (result.stdout or "").strip()
            if result.returncode == 0 and _is_executable(resolved):
                return resolved
        except (OSError, subprocess.TimeoutExpired):
            pass

        # A rolling elan channel can block on an update check when the network
        # is unavailable. Prefer the newest already-installed toolchain rather
        # than invoking that proxy for every proof.
        elan_home = Path(os.getenv("ELAN_HOME", "~/.elan")).expanduser()
        installed = [
            path
            for path in (elan_home / "toolchains").glob("*/bin/lean")
            if _is_executable(str(path))
        ]
        if installed:
            return str(max(installed, key=lambda path: path.stat().st_mtime_ns))

    return candidate


def _is_executable(path: str) -> bool:
    return bool(path) and Path(path).is_file() and os.access(path, os.X_OK)

