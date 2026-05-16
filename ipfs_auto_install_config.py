"""Compatibility wrapper for the canonical ``scripts/setup/ipfs_auto_install_config.py``."""

from __future__ import annotations

from pathlib import Path
import runpy


_CANONICAL_SCRIPT = (
    Path(__file__).resolve().parent / "scripts" / "setup" / "ipfs_auto_install_config.py"
)
if not _CANONICAL_SCRIPT.is_file():
    raise FileNotFoundError(
        f"Canonical auto-install configuration not found: {_CANONICAL_SCRIPT}"
    )

runpy.run_path(str(_CANONICAL_SCRIPT))
