#!/usr/bin/env python3
"""Compatibility wrapper for the canonical ``scripts/setup/install_deps.py``."""

from __future__ import annotations

from pathlib import Path
import runpy


_CANONICAL_SCRIPT = Path(__file__).resolve().parent / "scripts" / "setup" / "install_deps.py"

if __name__ == "__main__":
    runpy.run_path(str(_CANONICAL_SCRIPT), run_name="__main__")
else:
    _namespace = runpy.run_path(str(_CANONICAL_SCRIPT))
    install_profile = _namespace["install_profile"]

    __all__ = ["install_profile"]
