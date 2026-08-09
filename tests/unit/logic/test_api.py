"""Unit tests for the stable ``logic.api`` public surface (LFP-051 companions).

Covers additive VerificationAPI@2 / CanonicalLogicDiscovery@1 lazy exports
without mutating the frozen exact_exports contract, and keeps the simple
``explain_counterexample`` model projection green under sealed validation.
"""

from __future__ import annotations

import importlib
import sys
import warnings

import pytest


def _fresh_import(module_name: str):
    root = module_name.split(".", 1)[0]
    for name in list(sys.modules.keys()):
        if name == root or name.startswith(root + "."):
            sys.modules.pop(name, None)
    importlib.invalidate_caches()
    return importlib.import_module(module_name)


def test_logic_api_import_is_quiet() -> None:
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        module = _fresh_import("ipfs_datasets_py.logic.api")

    ipfs_warnings = [
        item
        for item in recorded
        if "ipfs_datasets_py" in (getattr(item, "filename", "") or "")
    ]
    assert ipfs_warnings == []
    assert hasattr(module, "__all__")
    assert "FOLConverter" in module.__all__


def test_logic_api_lazy_verification_and_migration_exports() -> None:
    import ipfs_datasets_py.logic.api as api

    # Additive surface via __getattr__; must not appear in frozen exact_exports.
    assert "LogicVerificationAPI" not in api.__all__
    assert "CanonicalLogicDiscovery" not in api.__all__
    assert api.LogicVerificationAPI.__name__ == "LogicVerificationAPI"
    assert api.CANONICAL_LOGIC_DISCOVERY_INTERFACE == "CanonicalLogicDiscovery@1"
    assert api.VERIFICATION_API_V2_INTERFACE == "VerificationAPI@2"
    assert callable(api.get_verification_api)
    assert callable(api.get_canonical_discovery)
    assert callable(api.dual_read_label)
    assert callable(api.migrate_artifact)
    assert callable(api.explain_counterexample)

    families = api.list_logic_families()
    assert families.status.value == "declarative"
    assert families.result["count"] >= 1

    dual = api.dual_read_label("family", "fol")
    assert dual.result["canonical"] == "first_order"

    migrated = api.migrate_artifact({"family_id": "fol", "provider_id": "z3"})
    assert migrated.status.value == "succeeded"
    assert migrated.result["artifact"]["family_id"] == "first_order"
    assert migrated.result["artifact"]["provider_id"] == "z3"


def test_logic_api_explain_counterexample_model_projection() -> None:
    import ipfs_datasets_py.logic.api as api

    explained = api.explain_counterexample(
        {"kind": "model", "model": {"x": "1"}, "summary": "x assigned 1"}
    )
    assert explained.status.value == "succeeded"
    assert explained.authority.value == "bounded"
    assert explained.result["model"] == {"x": "1"}
    assert explained.witnesses


def test_logic_api_exact_exports_remain_frozen() -> None:
    """exact_exports must not gain verification/migration symbols."""

    import json
    from pathlib import Path

    import ipfs_datasets_py.logic.api as api

    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "logic"
        / "api_v1"
        / "manifest.json"
    )
    if not manifest_path.is_file():
        pytest.skip("api_v1 compatibility manifest not present")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    exact = list(manifest["python_api"]["exact_exports"])
    assert list(api.__all__) == exact
    for forbidden in (
        "LogicVerificationAPI",
        "CanonicalLogicDiscovery",
        "get_verification_api",
        "explain_counterexample",
        "dual_read_label",
        "migrate_artifact",
    ):
        assert forbidden not in exact
