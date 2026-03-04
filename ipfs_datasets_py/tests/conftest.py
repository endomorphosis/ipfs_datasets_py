"""Parent conftest for ipfs_datasets_py/tests/.

Injects the legal_data path into sys.path early so that
`from reasoner.X import ...` resolves to processors/legal_data/reasoner/
rather than the test-package directory.  This conftest lives in a directory
without __init__.py, so pytest discovers it BEFORE importing any sub-package
test module.
"""
from __future__ import annotations

import sys
from pathlib import Path

_LEGAL_DATA_DIR = Path(__file__).parent.parent / "processors" / "legal_data"
_LEGAL_DATA_STR = str(_LEGAL_DATA_DIR.resolve())
if _LEGAL_DATA_STR not in sys.path:
    sys.path.insert(0, _LEGAL_DATA_STR)

# Clear any stale 'reasoner' cache to ensure the legal_data package wins.
for _key in list(sys.modules.keys()):
    if _key == "reasoner" or _key.startswith("reasoner."):
        del sys.modules[_key]
