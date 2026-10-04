"""Compatibility shim for legal citation stack modules.

Canonical implementation now lives under:
ipfs_datasets_py/processors/legal_data/

This shim executes the canonical module source into this module namespace so
legacy monkeypatching/tests that target module-level globals keep working.
"""

from __future__ import annotations

from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "legal_data" / Path(__file__).name
if not _MODULE_PATH.is_file():  # pragma: no cover
    raise ImportError(f"Unable to load canonical implementation from {_MODULE_PATH}")

_code = compile(_MODULE_PATH.read_text(encoding="utf-8"), str(_MODULE_PATH), "exec")
exec(_code, globals(), globals())
