"""Compatibility schema re-exports for legacy vector store imports.

This shim deliberately loads ``ml/embeddings/schema.py`` by file path to avoid
executing ``ml/embeddings/__init__.py`` side effects (for example optional
heavy dependencies like torch) during vector-store-only workflows.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "ml" / "embeddings" / "schema.py"
_SPEC = importlib.util.spec_from_file_location("ipfs_datasets_py.ml.embeddings.schema_compat", _SCHEMA_PATH)
if _SPEC is None or _SPEC.loader is None:
	raise ImportError(f"Unable to load schema module at {_SCHEMA_PATH}")

_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

for _name in dir(_MODULE):
	if _name.startswith("_"):
		continue
	globals()[_name] = getattr(_MODULE, _name)

__all__ = [name for name in globals() if not name.startswith("_")]
