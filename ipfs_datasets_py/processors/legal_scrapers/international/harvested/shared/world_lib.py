"""Compatibility shim for the shared legal-collector helper ``world_lib``.

The one maintained implementation is
``ipfs_datasets_py/processors/legal_scrapers/national_collectors/world_lib.py``.
Harvested collectors import this helper as a top-level module (``import world_lib``)
from this directory, and tests load it by file path, so instead of shipping a
second fork this file executes the canonical source in its own namespace.
However it is loaded, the resulting module object is the canonical module, so
attribute reads and monkeypatches behave exactly as before. ``__file__`` points
at the canonical file (its sibling lookups use it) and ``sys.path`` is restored
afterwards so harvested import order does not change.
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
        raise ImportError(f"canonical helper {filename} not found")
    return _ipfs_shim_Path(list(spec.submodule_search_locations)[0]) / filename


_ipfs_shim_path = _ipfs_shim_canonical_path("world_lib.py")
_ipfs_shim_saved_sys_path = list(_ipfs_shim_sys.path)
__file__ = str(_ipfs_shim_path)
try:
    exec(compile(_ipfs_shim_path.read_bytes(), __file__, "exec"), globals())
finally:
    _ipfs_shim_sys.path[:] = _ipfs_shim_saved_sys_path
