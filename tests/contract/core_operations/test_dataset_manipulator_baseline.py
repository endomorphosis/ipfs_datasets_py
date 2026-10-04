"""DSCON-G300 / DSCON-005 dataset manipulator compatibility and failure baseline.

Characterization-only contract tests. Mock-success paths and missing modules are
frozen as expected failures, not compatibility promises. Assertions observe
filesystem side effects and fabricated identities — not dictionary shape alone.
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

# workspace/.../ipfs_datasets_py/tests/contract/core_operations/this_file
_TEST_FILE = Path(__file__).resolve()
PACKAGE_ROOT = _TEST_FILE.parents[3]  # ipfs_datasets_py package checkout
REPO_ROOT = _TEST_FILE.parents[4]  # 211-AI workspace root

FIXTURES = PACKAGE_ROOT / "tests" / "fixtures" / "dataset_manipulator"
BASELINE = REPO_ROOT / "data" / "datasets_contract_analysis" / "audit" / "dataset-contract-baseline.json"
DRIFT = REPO_ROOT / "data" / "datasets_contract_analysis" / "audit" / "datasets-manipulator-drift.json"

REQUIRED_FIXTURE_FILES = {
    "README.md",
    "manifest.json",
    "sample_dataset.json",
    "expected_behaviors.json",
    "safe_vectors.json",
    "surface_inventory.json",
    "digests.json",
}

ACCEPTANCE_TERMS = {
    "pass-no-op-transformation",
    "fabricated-counts",
    "random-hash-id-identity",
    "no-write-save",
    "no-conversion-convert",
    "fallback-sample-dataset",
    "duplicate-shadowed-monolith",
    "missing-import",
    "kit-integration-failure",
    "weak-wrapper",
    "safe-vectors-preserved",
    "vulnerabilities-not-compatibility-promises",
}

DIGEST_TARGETS = [
    "manifest.json",
    "sample_dataset.json",
    "expected_behaviors.json",
    "safe_vectors.json",
    "surface_inventory.json",
    "README.md",
]


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_on_path() -> None:
    for root in (str(REPO_ROOT), str(PACKAGE_ROOT)):
        if root not in sys.path:
            sys.path.insert(0, root)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def sample_dataset() -> dict[str, Any]:
    return _load_json(FIXTURES / "sample_dataset.json")


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return _load_json(FIXTURES / "manifest.json")


@pytest.fixture(scope="module")
def expected_behaviors() -> dict[str, Any]:
    return _load_json(FIXTURES / "expected_behaviors.json")


@pytest.fixture(scope="module")
def safe_vectors() -> dict[str, Any]:
    return _load_json(FIXTURES / "safe_vectors.json")


@pytest.fixture(scope="module")
def surface_inventory() -> dict[str, Any]:
    return _load_json(FIXTURES / "surface_inventory.json")


@pytest.fixture(scope="module")
def baseline() -> dict[str, Any]:
    return _load_json(BASELINE)


# ---------------------------------------------------------------------------
# Evidence presence
# ---------------------------------------------------------------------------


def test_fixture_directory_contains_required_files() -> None:
    assert FIXTURES.is_dir(), f"missing fixtures dir: {FIXTURES}"
    present = {path.name for path in FIXTURES.iterdir() if path.is_file()}
    missing = REQUIRED_FIXTURE_FILES - present
    assert not missing, f"fixtures missing files: {sorted(missing)}"


def test_audit_baseline_exists_and_binds_goal_packet(baseline: dict[str, Any]) -> None:
    assert BASELINE.is_file(), f"missing baseline: {BASELINE}"
    assert baseline["schema"] == "datasets_contract_analysis/dataset-contract-baseline@1"
    assert baseline["goal_id"] == "DSCON-G300"
    assert baseline["task_id"] == "DSCON-005"
    assert baseline["goal_packet"] == "goal_packet/datasets_pilot/ipfs_datasets_py/c2f31d882e73"
    assert set(baseline["goal_packet_goals"]) == {"DSCON-G300", "DSCON-G310", "DSCON-G320"}
    assert baseline["characterization_only"] is True
    assert baseline["production_code_changed"] is False
    assert baseline["vulnerabilities_are_expected_failures"] is True
    assert baseline["compatibility_promises"] is False


def test_manifest_covers_acceptance_terms(manifest: dict[str, Any]) -> None:
    assert manifest["goal_id"] == "DSCON-G300"
    assert manifest["classification"]["security_vulnerabilities_frozen_as_ok"] is False
    assert manifest["classification"]["mock_success_is_defect"] is True
    assert manifest["classification"]["observe_side_effects"] is True
    terms = set(manifest["acceptance_terms"])
    missing = ACCEPTANCE_TERMS - terms
    assert not missing, f"manifest missing acceptance terms: {sorted(missing)}"
    for relative in manifest["files"]:
        assert (FIXTURES / relative).is_file(), relative


def test_expected_behaviors_cover_all_acceptance_categories(
    expected_behaviors: dict[str, Any],
) -> None:
    categories = {item["category"] for item in expected_behaviors["behaviors"]}
    required = set(expected_behaviors["acceptance_categories"])
    missing = required - categories
    assert not missing, f"behavior categories missing: {sorted(missing)}"
    assert required >= {
        "pass-no-op-transformation",
        "fabricated-counts",
        "random-hash-id-identity",
        "no-write-save",
        "no-conversion-convert",
        "fallback-sample-dataset",
        "duplicate-shadowed-monolith",
        "missing-import",
        "kit-integration-failure",
        "weak-wrapper",
    }


def test_fixture_digests_match_payloads() -> None:
    digests = _load_json(FIXTURES / "digests.json")
    assert digests["algorithm"] == "sha256"
    recorded = digests["files"]
    for name in DIGEST_TARGETS:
        path = FIXTURES / name
        assert path.is_file(), name
        actual = _sha256_file(path)
        assert recorded[name] == actual, f"digest mismatch for {name}"


def test_surface_inventory_lists_required_channels(surface_inventory: dict[str, Any]) -> None:
    channel_ids = {item["channel_id"] for item in surface_inventory["channels"]}
    for required in surface_inventory["required_channels"]:
        assert required in channel_ids, required
    kinds = {item["kind"] for item in surface_inventory["channels"]}
    for kind in ("direct_python", "mcp_tool", "mcp_client", "http_service", "swissknife", "ipfs_kit"):
        assert kind in kinds, kind


# ---------------------------------------------------------------------------
# Live side-effect characterization (expected failures)
# ---------------------------------------------------------------------------


def test_process_transform_is_noop_success(sample_dataset: dict[str, Any]) -> None:
    _repo_on_path()
    from ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset import (
        process_dataset,
    )

    result = _run(
        process_dataset(
            {"data": list(sample_dataset["data"])},
            operations=[{"type": "transform", "params": {}}],
        )
    )
    assert result["status"] == "success"
    assert result["num_records"] == sample_dataset["record_count"]
    assert result["operations_summary"] == ["transform"]
    # No real transform receipt / row payload — success is mock characterization.
    assert "rows" not in result
    assert "transformed_data" not in result


def test_process_filter_fabricates_count_without_predicate(
    sample_dataset: dict[str, Any],
) -> None:
    _repo_on_path()
    from ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset import (
        process_dataset,
    )

    source = {"data": list(sample_dataset["data"])}
    result = _run(
        process_dataset(
            source,
            operations=[{"type": "filter", "field": "id", "op": "eq", "value": 999}],
        )
    )
    assert result["status"] == "success"
    # Predicate would yield 0 rows; mock uses max(1, int(n * 0.9)).
    expected = max(1, int(sample_dataset["record_count"] * 0.9))
    assert result["num_records"] == expected
    assert result["num_records"] != 0


def test_process_identity_uses_process_salted_hash(sample_dataset: dict[str, Any]) -> None:
    _repo_on_path()
    from ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset import (
        process_dataset,
    )

    source = {"data": list(sample_dataset["data"])}
    result = _run(process_dataset(source, operations=[{"type": "normalize"}]))
    assert result["status"] == "success"
    dataset_id = result["dataset_id"]
    assert dataset_id.startswith("processed_")
    suffix = dataset_id.removeprefix("processed_")
    assert suffix.isdigit()
    # Matches implementation: hash(str(dataset_source)) % 100000
    assert int(suffix) == hash(str(source)) % 100000


def test_save_dataset_dict_path_is_no_write(
    sample_dataset: dict[str, Any],
    tmp_path: Path,
) -> None:
    _repo_on_path()
    from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset

    dest = tmp_path / "saved.json"
    result = _run(
        save_dataset(
            dataset_data={"data": list(sample_dataset["data"])},
            destination=str(dest),
            format="json",
        )
    )
    assert result["status"] == "success"
    assert result["destination"] == str(dest)
    assert result["location"] == str(dest)
    assert result["dataset_id"].startswith("mock_dataset_")
    # Side effect: no artifact on disk despite success.
    assert not dest.exists(), "mock save must not create destination (expected failure freeze)"
    assert list(tmp_path.iterdir()) == []


def test_managed_dataset_save_is_no_write(tmp_path: Path) -> None:
    _repo_on_path()
    from ipfs_datasets_py.dataset_manager import DatasetManager

    manager = DatasetManager(use_accelerate=False)
    managed = manager.get_dataset("definitely-missing-dscon-g300")
    dest = tmp_path / "mgr.json"
    sync_result = managed.save(str(dest), format="json")
    async_result = _run(managed.save_async(str(tmp_path / "mgr_async.json"), format="json"))
    assert sync_result["location"] == str(dest)
    assert "size" in sync_result and "format" in sync_result
    assert async_result["location"].endswith("mgr_async.json")
    assert not dest.exists()
    assert not (tmp_path / "mgr_async.json").exists()


def test_dataset_manager_fallback_sample_not_fail_closed() -> None:
    _repo_on_path()
    from ipfs_datasets_py.dataset_manager import DatasetManager, ManagedDataset

    manager = DatasetManager(use_accelerate=False)
    managed = manager.get_dataset("missing-authority-dataset-xyz")
    assert isinstance(managed, ManagedDataset)
    assert managed.dataset_id == "missing-authority-dataset-xyz"
    # Fallback sample payload shape (dict or HF Dataset-like).
    payload = managed.dataset
    if isinstance(payload, dict):
        assert "text" in payload and "label" in payload
    else:
        # HF Dataset path still represents the mock sample.
        assert payload is not None


def test_convert_dataset_format_is_mock_no_conversion(tmp_path: Path) -> None:
    _repo_on_path()
    from ipfs_datasets_py.mcp_server.tools.dataset_tools.convert_dataset_format import (
        convert_dataset_format,
    )

    out = tmp_path / "converted.parquet"
    result = _run(
        convert_dataset_format(
            dataset_id="sample_ds",
            target_format="parquet",
            output_path=str(out),
        )
    )
    assert result["status"] == "success"
    assert result.get("conversion_method") == "mock"
    assert result.get("num_records") == 100
    assert result["dataset_id"] == "converted_sample_ds_parquet"
    assert not out.exists(), "mock convert must not write output artifact"


def test_core_saver_and_converter_placeholders_are_no_ops(tmp_path: Path) -> None:
    _repo_on_path()
    from ipfs_datasets_py.core_operations.dataset_converter import DatasetConverter
    from ipfs_datasets_py.core_operations.dataset_saver import DatasetSaver

    dest = tmp_path / "core_save.json"
    save_result = _run(DatasetSaver().save({"data": [1]}, str(dest), format="json"))
    convert_result = _run(DatasetConverter().convert("source", "csv"))
    assert save_result["status"] == "success"
    assert "successfully" in save_result.get("message", "").lower()
    assert not dest.exists()
    assert convert_result["status"] == "success"
    assert "successfully" in convert_result.get("message", "").lower()
    assert "output_path" not in convert_result or not Path(
        convert_result.get("output_path") or ""
    ).exists()


def test_dataset_manipulator_and_contracts_missing() -> None:
    _repo_on_path()
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("ipfs_datasets_py.core_operations.dataset_manipulator")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("ipfs_datasets_py.core_operations.dataset_contracts")
    # Present core surfaces remain importable.
    from ipfs_datasets_py.core_operations import (
        DataProcessor,
        DatasetConverter,
        DatasetLoader,
        DatasetSaver,
    )

    assert DatasetLoader and DatasetSaver and DatasetConverter and DataProcessor
    manip_path = (
        PACKAGE_ROOT / "ipfs_datasets_py" / "core_operations" / "dataset_manipulator.py"
    )
    contracts_path = (
        PACKAGE_ROOT / "ipfs_datasets_py" / "core_operations" / "dataset_contracts.py"
    )
    assert not manip_path.exists()
    assert not contracts_path.exists()


def test_duplicate_dataset_manager_shadow_definitions() -> None:
    paths = [
        REPO_ROOT / "ipfs_datasets_py" / "ipfs_datasets_py" / "dataset_manager.py",
        REPO_ROOT / "ipfs_kit_py" / "ipfs_kit_py" / "ai_ml_integration.py",
        REPO_ROOT / "ipfs_kit_py" / "ipfs_kit_py" / "mcp" / "ai" / "dataset_manager.py",
        REPO_ROOT
        / "ipfs_kit_py"
        / "ipfs_kit_py"
        / "mcp"
        / "ai"
        / "dataset_management"
        / "manager.py",
    ]
    for path in paths:
        assert path.is_file(), f"missing shadow surface: {path}"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        class_names = {
            node.name for node in tree.body if isinstance(node, ast.ClassDef)
        }
        assert "DatasetManager" in class_names, f"DatasetManager missing in {path}"


def test_kit_integration_lacks_top_level_load_dataset_export() -> None:
    _repo_on_path()
    integration_path = (
        REPO_ROOT / "ipfs_kit_py" / "ipfs_kit_py" / "ipfs_datasets_integration.py"
    )
    assert integration_path.is_file()
    source = integration_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(integration_path))
    top_level_funcs = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    assert "load_dataset" not in top_level_funcs
    # Class method exists on DatasetIPFSBackend (adapter), not package export.
    assert "class DatasetIPFSBackend" in source
    assert "def load_dataset" in source


def test_weak_wrapper_unit_tests_do_not_assert_side_effects() -> None:
    weak_test = (
        PACKAGE_ROOT / "tests" / "mcp" / "unit" / "test_dataset_tools.py"
    )
    assert weak_test.is_file()
    text = weak_test.read_text(encoding="utf-8")
    assert "isinstance(result, dict)" in text
    # Characterization: these tests do not freeze persistence or mock detection.
    assert "exists()" not in text
    assert "conversion_method" not in text
    assert "mock_dataset_" not in text


# ---------------------------------------------------------------------------
# Safe vectors preserved
# ---------------------------------------------------------------------------


def test_safe_vectors_reject_dangerous_ops_and_executable_destinations(
    safe_vectors: dict[str, Any],
    sample_dataset: dict[str, Any],
) -> None:
    _repo_on_path()
    from ipfs_datasets_py.core_operations.dataset_loader import DatasetLoader
    from ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset import (
        process_dataset,
    )
    from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset

    assert len(safe_vectors["vectors"]) >= 4

    eval_result = _run(
        process_dataset(
            {"data": list(sample_dataset["data"])},
            operations=[{"type": "eval"}],
        )
    )
    assert eval_result["status"] == "error"
    assert eval_result.get("error_type") == "validation"
    assert "not allowed" in eval_result.get("message", "").lower()

    exec_result = _run(
        process_dataset(
            {"data": list(sample_dataset["data"])},
            operations=[{"type": "exec"}],
        )
    )
    assert exec_result["status"] == "error"

    empty_ops = _run(
        process_dataset({"data": list(sample_dataset["data"])}, operations=[])
    )
    assert empty_ops["status"] == "error"

    exe_dest = _run(
        save_dataset(
            dataset_data={"data": list(sample_dataset["data"])},
            destination="/tmp/evil.py",
            format="json",
        )
    )
    assert exe_dest["status"] == "error"
    assert "executable" in exe_dest.get("message", "").lower()

    py_source = _run(DatasetLoader().load("payload.py"))
    assert py_source["status"] == "error"
    assert "python" in py_source.get("message", "").lower()


# ---------------------------------------------------------------------------
# Baseline / drift coherence
# ---------------------------------------------------------------------------


def test_baseline_acceptance_coverage_all_true(baseline: dict[str, Any]) -> None:
    coverage = baseline["acceptance_coverage"]
    assert coverage, "acceptance_coverage missing"
    for key, value in coverage.items():
        assert value is True, f"acceptance coverage false: {key}"


def test_baseline_links_drift_findings(baseline: dict[str, Any]) -> None:
    assert DRIFT.is_file(), f"missing drift inventory: {DRIFT}"
    drift = _load_json(DRIFT)
    drift_ids = {item["finding_id"] for item in drift["findings"]}
    for finding_id in baseline["linked_drift_findings"]:
        assert finding_id in drift_ids, finding_id
    # Required categories from G010 remain represented.
    for category in (
        "mock-success",
        "nondeterministic-identity",
        "duplicate-definition",
        "missing-import",
        "weak-test",
    ):
        assert category in drift["finding_categories"]


def test_baseline_declares_missing_core_symbols(baseline: dict[str, Any]) -> None:
    missing = set(baseline["missing_core_symbols"])
    assert "DatasetManipulator" in missing
    present = set(baseline["present_core_symbols"])
    assert {"DatasetLoader", "DatasetSaver", "DatasetConverter", "DataProcessor"} <= present


def test_baseline_observed_side_effects_include_no_write_and_mock_convert(
    baseline: dict[str, Any],
) -> None:
    effects = {item["id"]: item for item in baseline["observed_side_effects"]}
    assert effects["OBS-SAVE-MCP-NO-WRITE"]["filesystem_write"] is False
    assert effects["OBS-CONVERT-MCP-MOCK"]["conversion_method"] == "mock"
    assert effects["OBS-CONVERT-MCP-MOCK"]["fabricated_num_records"] == 100
    assert effects["OBS-MISSING-MANIPULATOR"]["importable"] is False
    for item in baseline["observed_side_effects"]:
        assert item["classification"] == "expected_failure"


def test_process_source_contains_mock_markers() -> None:
    path = (
        PACKAGE_ROOT
        / "ipfs_datasets_py"
        / "mcp_server"
        / "tools"
        / "dataset_tools"
        / "process_dataset.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "Process operations (mock implementation for now)" in text
    assert "return 100  # Default mock count" in text
    assert "processed_records * 0.9" in text


def test_save_and_convert_source_contain_mock_markers() -> None:
    save_path = (
        PACKAGE_ROOT
        / "ipfs_datasets_py"
        / "mcp_server"
        / "tools"
        / "dataset_tools"
        / "save_dataset.py"
    )
    convert_path = (
        PACKAGE_ROOT
        / "ipfs_datasets_py"
        / "mcp_server"
        / "tools"
        / "dataset_tools"
        / "convert_dataset_format.py"
    )
    manager_path = PACKAGE_ROOT / "ipfs_datasets_py" / "dataset_manager.py"
    assert 'mock_dataset_{hash(str(dataset_data))}' in save_path.read_text(encoding="utf-8")
    convert_text = convert_path.read_text(encoding="utf-8")
    assert "Using mock conversion response" in convert_text
    assert '"conversion_method": "mock"' in convert_text or "conversion_method\": \"mock\"" in convert_text
    assert "Mock successful save" in manager_path.read_text(encoding="utf-8")
