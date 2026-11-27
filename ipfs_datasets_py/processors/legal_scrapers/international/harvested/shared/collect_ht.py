"""Compatibility shim for the harvested collector ``collect_ht``.

The one maintained implementation is
``ipfs_datasets_py/processors/legal_scrapers/national_collectors/collect_ht.py``.
The harvested runtime, ``python collect_ht.py`` and load-by-path callers keep using this
path, so instead of shipping a second copy this file executes the canonical
source in its own namespace (``__name__`` is kept, so ``__main__`` runs still
run ``main()``). ``__file__`` points at the canonical file so its sibling helper
imports resolve there, and ``sys.path`` is restored afterwards.
"""

import importlib.util as _ipfs_shim_ilu
import sys as _ipfs_shim_sys
from pathlib import Path as _ipfs_shim_Path


def _ipfs_shim_canonical_path(filename):
    for parent in _ipfs_shim_Path(__file__).resolve().parents:
        candidate = parent / "national_collectors" / filename
        if parent.name == "legal_scrapers" and candidate.is_file():
            return candidate
    spec = _ipfs_shim_ilu.find_spec("ipfs_datasets_py.processors.legal_scrapers.national_collectors")
    if spec is None or not spec.submodule_search_locations:
        raise ImportError(f"canonical collector {filename} not found")
    return _ipfs_shim_Path(list(spec.submodule_search_locations)[0]) / filename


_ipfs_shim_path = _ipfs_shim_canonical_path("collect_ht.py")
_ipfs_shim_saved_sys_path = list(_ipfs_shim_sys.path)
__file__ = str(_ipfs_shim_path)
try:
    exec(compile(_ipfs_shim_path.read_bytes(), __file__, "exec"), globals())
finally:
    _ipfs_shim_sys.path[:] = _ipfs_shim_saved_sys_path
