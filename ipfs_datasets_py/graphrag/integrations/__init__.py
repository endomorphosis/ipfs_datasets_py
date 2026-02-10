"""GraphRAG integration modules (canonical namespace).

This package is the canonical location for GraphRAG integration glue.

Legacy import path:
- `ipfs_datasets_py.logic.integrations.*`

Notes:
- Keep this initializer lightweight; integrations may depend on optional/heavy
  dependencies.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict


_EXPORTS: Dict[str, str] = {
    # Modules
    "graphrag_integration": "ipfs_datasets_py.graphrag.integrations.graphrag_integration",
    "enhanced_graphrag_integration": "ipfs_datasets_py.graphrag.integrations.enhanced_graphrag_integration",
    "phase7_complete_integration": "ipfs_datasets_py.graphrag.integrations.phase7_complete_integration",
    "unixfs_integration": "ipfs_datasets_py.graphrag.integrations.unixfs_integration",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_name)
    globals()[name] = module
    return module


__all__ = list(_EXPORTS.keys())
