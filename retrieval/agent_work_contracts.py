"""Merge-admission alias for EAAEF-060 federated retrieval contracts.

The canonical module lives in the installable package
``ipfs_datasets_py.retrieval.agent_work_contracts``.  This path exists so
owned-file admission against ``ipfs_datasets_py/retrieval/agent_work_contracts.py``
and kit pytest against the nested package both observe the same @1 API.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_CANONICAL = (
    Path(__file__).resolve().parent.parent
    / "ipfs_datasets_py"
    / "retrieval"
    / "agent_work_contracts.py"
)


def _load_canonical():
    existing = sys.modules.get("ipfs_datasets_py.retrieval.agent_work_contracts")
    if existing is not None and getattr(existing, "__file__", None):
        try:
            if Path(existing.__file__).resolve() == _CANONICAL:
                return existing
        except OSError:
            pass
    spec = importlib.util.spec_from_file_location(
        "ipfs_datasets_py.retrieval.agent_work_contracts",
        _CANONICAL,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"canonical EAAEF-060 contracts missing: {_CANONICAL}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("ipfs_datasets_py.retrieval.agent_work_contracts", module)
    spec.loader.exec_module(module)
    return module


_module = _load_canonical()
globals().update({name: getattr(_module, name) for name in _module.__all__})
__all__ = list(_module.__all__)
