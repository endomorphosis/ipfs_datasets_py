from __future__ import annotations

import importlib
import sys
import warnings


def _fresh_import(module_name: str):
    root = module_name.split(".", 1)[0]
    for name in list(sys.modules.keys()):
        if name == root or name.startswith(root + "."):
            sys.modules.pop(name, None)
    importlib.invalidate_caches()
    return importlib.import_module(module_name)


def _ipfs_origin_warnings(recorded: list[warnings.WarningMessage]) -> list[warnings.WarningMessage]:
    return [w for w in recorded if "ipfs_datasets_py" in (getattr(w, "filename", "") or "")]


def test_logic_api_import_is_quiet_and_lightweight(monkeypatch):
    monkeypatch.delenv("IPFS_DATASETS_PY_WARN_OPTIONAL_IMPORTS", raising=False)

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        api = _fresh_import("ipfs_datasets_py.logic.api")

    ipfs_warnings = _ipfs_origin_warnings(recorded)
    assert ipfs_warnings == [], [str(w.message) for w in ipfs_warnings]

    expected_exports = {
        "FOLConverter",
        "DeonticConverter",
        "ConversionResult",
        "ConversionStatus",
        "ProofResult",
        "ProofStatus",
    }

    exported = set(getattr(api, "__all__", []))
    missing_from_all = sorted(expected_exports - exported)
    assert missing_from_all == [], missing_from_all

    # The blessed API surface should not import the heavy integration namespace.
    assert "ipfs_datasets_py.logic.integration" not in sys.modules
