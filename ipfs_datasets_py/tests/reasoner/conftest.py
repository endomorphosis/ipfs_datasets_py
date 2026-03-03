"""Pytest configuration for reasoner tests.

Sets up the import path so that reasoner modules can be imported
without triggering the heavyweight processors/__init__.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add the legal_data directory to sys.path so `import reasoner` works,
# and `from reasoner.hybrid_v2_blueprint import ...` works with relative imports.
_LEGAL_DATA_DIR = Path(__file__).parent.parent.parent / "processors" / "legal_data"
_LEGAL_DATA_STR = str(_LEGAL_DATA_DIR)
if _LEGAL_DATA_STR not in sys.path:
    sys.path.insert(0, _LEGAL_DATA_STR)

# Clear any cached 'reasoner' entry that pytest's importlib mode may have set to the
# test directory package, so subsequent imports resolve from processors/legal_data/.
for _key in list(sys.modules.keys()):
    if _key == "reasoner" or _key.startswith("reasoner."):
        del sys.modules[_key]

# Also add the repo root so tests can be discovered normally.
_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_REPO_ROOT_STR = str(_REPO_ROOT)
if _REPO_ROOT_STR not in sys.path:
    sys.path.insert(0, _REPO_ROOT_STR)
