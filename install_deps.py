#!/usr/bin/env python3
"""Compatibility wrapper for the canonical ``scripts/setup/install_deps.py``."""

from __future__ import annotations

from pathlib import Path
import runpy


_CANONICAL_SCRIPT = Path(__file__).resolve().parent / "scripts" / "setup" / "install_deps.py"


def _validate_canonical_script() -> Path:
    if not _CANONICAL_SCRIPT.is_file():
        raise FileNotFoundError(
            f"Canonical install helper not found: {_CANONICAL_SCRIPT}"
        )
    return _CANONICAL_SCRIPT

if __name__ == "__main__":
    runpy.run_path(str(_validate_canonical_script()), run_name="__main__")
else:
    _namespace = runpy.run_path(str(_validate_canonical_script()))
    install_profile = _namespace.get("install_profile")
    if install_profile is None:
        raise RuntimeError(
            f"'install_profile' is missing from canonical install helper: {_CANONICAL_SCRIPT}"
        )

    __all__ = ["install_profile"]
