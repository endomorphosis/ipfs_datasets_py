"""Unit tests for the US Code sparse GraphRAG package API (USCIR-029)."""

from __future__ import annotations

import importlib
import warnings

import pytest

from ipfs_datasets_py.processors.legal_data import uscode_sparse_graphrag as api


def test_import_is_optional_dependency_safe() -> None:
    receipt = api.import_is_optional_dependency_safe()
    assert receipt["optional_dependency_safe"] is True
    assert receipt["stdlib_only_at_import"] is True
    assert receipt["heavy_backends_imported"] is False


def test_reimport_is_side_effect_free() -> None:
    # Re-import must not raise and must stay lazy.
    module = importlib.reload(api)
    assert module.TASK_ID == "USCIR-029"
    assert module.PRIMARY_KEY_V2 == "entry_cid"


def test_open_api_package_identity() -> None:
    facade = api.open_api()
    identity = facade.package_identity()
    assert identity["task_id"] == "USCIR-029"
    assert identity["primary_key"] == "entry_cid"
    assert identity["default_config"] == "publicus-ir-graphrag/v2"
    assert identity["corpus_id"] == "uscode"
    assert identity["dataset_repo_id"] == "justicedao/ipfs_uscode"


def test_compatibility_configs_include_explicit_legacy() -> None:
    configs = {item["name"]: item for item in api.list_compatibility_configs()}
    assert "publicus-ir-graphrag/v2" in configs
    assert configs["publicus-ir-graphrag/v2"]["is_default"] is True
    assert "legacy-uscode-parquet/v1" in configs
    assert configs["legacy-uscode-parquet/v1"]["is_legacy"] is True
    assert configs["legacy-uscode-parquet/v1"]["is_default"] is False


def test_legacy_path_requires_explicit_opt_in() -> None:
    default = api.default_compatibility_config()
    assert default.name == "publicus-ir-graphrag/v2"
    legacy = api.legacy_compatibility_config()
    assert legacy.is_legacy is True
    facade = api.open_api().use_legacy_compatibility()
    assert facade.compatibility_config_name == "legacy-uscode-parquet/v1"


def test_unknown_compatibility_config_fails() -> None:
    with pytest.raises(api.CompatibilityConfigError):
        api.get_compatibility_config("not-a-real-config")


def test_registry_path_cid_reconciliation() -> None:
    receipt = api.reconcile_registry_path_cid()
    payload = receipt.to_dict() if hasattr(receipt, "to_dict") else dict(receipt)
    assert payload["reconciled"] is True
    assert payload["v2_primary_key"] == "entry_cid"
    assert "ipfs_cid" in payload["accepted_cid_fields"]
    assert "cid" in payload["accepted_cid_fields"]
    assert any("laws.parquet" in p for p in payload["accepted_parquet_paths"])


def test_resolve_legacy_cid_field_aliases() -> None:
    assert api.resolve_legacy_cid_field({"ipfs_cid": "abc"}) == "abc"
    assert api.resolve_legacy_cid_field({"cid": "xyz"}) == "xyz"
    assert api.resolve_legacy_cid_field({"entry_cid": "e1"}) == "e1"
    assert api.resolve_legacy_cid_field({"other": "nope"}) is None


def test_adapter_roots_reconcile() -> None:
    corpus_cid = api.content_cid({"family": "corpus", "n": 1})
    bm25_cid = api.build_family_root_cid(
        "bm25", {"docs": 3}, parent_root_cid=corpus_cid
    )
    roots = api.AdapterRootSet(
        corpus_root_cid=corpus_cid,
        bm25_root_cid=bm25_cid,
        vector_root_cid=None,
        graph_root_cid=None,
    )
    receipt = api.reconcile_adapter_roots(roots)
    assert receipt["reconciled"] is True
    assert receipt["corpus_root_cid"] == corpus_cid
    assert "bm25" in receipt["families_present"]


def test_release_gate_capability_descriptor() -> None:
    capability = api.open_api().release_gate_capability()
    assert capability["corpus_id"] == "uscode"
    assert capability["release_gate_capable"] is True
    assert capability["differential_capable"] is True
    families = capability["required_artifact_families"]
    assert isinstance(families, list) and families


def test_warn_legacy_default_config() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        api.warn_legacy_default_config()
    assert any(issubclass(item.category, DeprecationWarning) for item in caught)


def test_lazy_export_resolution_for_query_client_symbol() -> None:
    # Resolving the symbol name must not import heavy optional stacks beyond
    # the already-present legal_data modules in this environment.
    name = "UscodeQueryClient"
    assert name in api.available_lazy_exports()
    resolved = api.resolve_export(name)
    assert resolved is not None
    assert getattr(resolved, "__name__", "") == "UscodeQueryClient"
