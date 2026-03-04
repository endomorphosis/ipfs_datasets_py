"""Reasoner test package.

When pytest's --import-mode=importlib loads this directory as a package it
names it ``reasoner``.  That clashes with the real implementation package at
``processors/legal_data/reasoner/``.  We fix the collision by injecting a
lightweight stub whose __path__ points at the real source tree, so that
``from reasoner.hybrid_v2_blueprint import ...`` in test files resolves to
the implementation, not this stub directory.
"""
from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

_LEGAL_DATA_DIR = (Path(__file__).parent.parent.parent / "processors" / "legal_data").resolve()
_REAL_REASONER_DIR = _LEGAL_DATA_DIR / "reasoner"
_LEGAL_DATA_STR = str(_LEGAL_DATA_DIR)

if _LEGAL_DATA_STR not in sys.path:
    sys.path.insert(0, _LEGAL_DATA_STR)

# Create a lightweight stub module whose __path__ points to the real reasoner
# directory.  This lets Python find and import any reasoner.X submodule while
# avoiding the heavyweight reasoner/__init__.py that imports engine.py.
_stub = types.ModuleType("reasoner")
_stub.__package__ = "reasoner"
_stub.__path__ = [str(_REAL_REASONER_DIR)]
_stub.__file__ = str(_REAL_REASONER_DIR / "__init__.py")
_stub.__spec__ = importlib.util.spec_from_file_location(
    "reasoner",
    str(_REAL_REASONER_DIR / "__init__.py"),
    submodule_search_locations=[str(_REAL_REASONER_DIR)],
)
sys.modules["reasoner"] = _stub
