"""Compatibility wrapper for the canonical ``scripts/setup/ipfs_auto_install_config.py``."""

from __future__ import annotations

from pathlib import Path
import runpy


_CANONICAL_SCRIPT = (
    Path(__file__).resolve().parent / "scripts" / "setup" / "ipfs_auto_install_config.py"
)
globals().update(runpy.run_path(str(_CANONICAL_SCRIPT)))
