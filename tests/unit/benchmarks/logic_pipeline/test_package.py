"""Foundation contract for the isolated logic-pipeline benchmark package."""

from __future__ import annotations

import builtins
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import benchmarks.logic_pipeline as logic_pipeline


OPTIONAL_OR_PRODUCTION_ROOTS = {
    "hammer",
    "leanstral",
    "spacy",
    "symai",
    "symbolicai",
    "ipfs_datasets_py",
}


def test_package_import_does_not_load_optional_or_production_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The package remains importable in a minimal benchmark environment."""

    real_import = builtins.__import__

    def guarded_import(name: str, *args: object, **kwargs: object) -> object:
        if name.partition(".")[0] in OPTIONAL_OR_PRODUCTION_ROOTS:
            raise AssertionError(f"benchmark package imported forbidden component {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    reloaded = importlib.reload(logic_pipeline)

    assert (
        reloaded.HSSLEV0009A31()
        == "isolated benchmark package and execution skeleton"
    )
    assert (
        reloaded.HSSLEV2007A42()
        == "label-blind CID-bound semantic projection protocol with "
        "non-vacuous producer validation and fail-closed calibration contracts"
    )
    assert (
        reloaded.HSSLEV2343B16()
        == "source-recomputed full-runtime paired efficacy, reliability, "
        "and routing validators"
    )
    assert (
        reloaded.HSSLEV2367D38()
        == "CID-addressed independently reviewed non-holdout controls with "
        "exact full-runtime joins and fatal terminal native-kernel authority"
    )
    assert (
        reloaded.HSSLEV2350C27()
        == "CID-native G201 source replay with label-blind producer/cache "
        "proofs and per-arm non-vacuous absolute semantic quality"
    )
    assert (
        reloaded.HSSLEV2374E49()
        == "CID-native independent resource receipts, exact missing-aware A0 "
        "pairs, replayed statistics, and safety-feasible Pareto evidence"
    )
    assert (
        reloaded.HSSLEV2381F50()
        == "CID-native all-success and deterministic failure-sample replay "
        "with fresh detached worktree, run, process, state, and cache "
        "isolation"
    )
    assert (
        reloaded.HSSLEV2405D72()
        == "fail-closed source-bound runtime namespaces, confined execution, "
        "and detached replay"
    )
    assert (
        reloaded.HSSLEV2312F74()
        == "source-recomputed positive gate bundle with complete live-source "
        "and detached-replay joins"
    )
    assert set(reloaded.__all__) >= {
        "HSSLEV0217E25",
        "HSSLEV0224A96",
        "HSSLEV2007A42",
        "HSSLEV2343B16",
        "HSSLEV2350C27",
        "HSSLEV2367D38",
        "HSSLEV2374E49",
        "HSSLEV2381F50",
        "HSSLEV2405D72",
        "HSSLEV2312F74",
        "ExecutionDefaults",
        "G210RuntimeReceiptMatrixV2",
        "G230_RECEIPT_REPLAY_ASSESSMENT_SCHEMA",
        "G234_GATE_IDS",
        "G234_PAIRED_EFFICACY_COMPARISON_SCHEMA",
        "G234_PAIRED_EFFICACY_PAIR_SCHEMA",
        "G234_RUNTIME_GATE_RECEIPT_SCHEMA",
        "G236_REQUIRED_CACHE_MODES",
        "G236_REQUIRED_VARIANT_IDS",
        "REVIEWED_CONTROL_ATTESTATION_SCHEMA_V2",
        "REVIEWED_CONTROL_CLASSIFICATION_SCHEMA_V2",
        "REVIEWED_CONTROL_ENTRY_SCHEMA_V2",
        "REVIEWED_CONTROL_INDEX_SCHEMA_V2",
        "REVIEWED_CONTROL_POLICY_V2_CID",
        "REVIEWED_CONTROL_REVIEW_PROTOCOL_V2_CID",
        "REVIEWED_CONTROL_SAFETY_GATE_SCHEMA_V2",
        "ReviewedControlAttestationV2",
        "ReviewedControlEntryV2",
        "ReviewedControlIndexV2",
        "ReviewedControlSafetyError",
        "RunPaths",
        "build_g210_runtime_receipt_matrix_v2",
        "build_g230_receipt_replay_assessment_v2",
        "build_g234_efficacy_gate_v2",
        "build_g234_reliability_gate_v2",
        "build_g234_routing_gate_v2",
        "build_g238_detached_replay_gate_v2",
        "build_resource_statistics_gate_v2",
        "build_reviewed_control_index_v2",
        "build_reviewed_control_safety_gate_v2",
        "build_smoke_manifest",
        "gate_candidate",
        "load_control_suite",
        "load_fixture_imports",
        "manifest_sha256",
        "reviewed_control_policy_v2",
        "reviewed_control_review_protocol_v2",
        "SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID",
        "SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID",
        "SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID",
        "validate_g234_efficacy_gate_v2",
        "validate_g234_reliability_gate_v2",
        "validate_g234_routing_gate_v2",
        "validate_g238_detached_replay_gate_v2",
        "validate_resource_statistics_gate_v2",
        "validate_reviewed_control_safety_gate_v2",
    }
    assert set(reloaded.__all__).isdisjoint(
        {
            "build_g230_efficacy_gate_v2",
            "build_g230_reliability_gate_v2",
            "build_g230_routing_gate_v2",
            "validate_g230_efficacy_gate_v2",
            "validate_g230_reliability_gate_v2",
            "validate_g230_routing_gate_v2",
        }
    )


def test_g236_package_exports_match_the_reviewed_control_module() -> None:
    reviewed_control = importlib.import_module(
        "benchmarks.logic_pipeline.reviewed_control"
    )
    public = {
        "G236_REQUIRED_CACHE_MODES",
        "G236_REQUIRED_VARIANT_IDS",
        "HSSLEV2367D38",
        "REVIEWED_CONTROL_ATTESTATION_SCHEMA_V2",
        "REVIEWED_CONTROL_CLASSIFICATION_SCHEMA_V2",
        "REVIEWED_CONTROL_ENTRY_SCHEMA_V2",
        "REVIEWED_CONTROL_INDEX_SCHEMA_V2",
        "REVIEWED_CONTROL_POLICY_V2_CID",
        "REVIEWED_CONTROL_REVIEW_PROTOCOL_V2_CID",
        "REVIEWED_CONTROL_SAFETY_GATE_SCHEMA_V2",
        "ReviewedControlAttestationV2",
        "ReviewedControlEntryV2",
        "ReviewedControlIndexV2",
        "ReviewedControlSafetyError",
        "build_reviewed_control_index_v2",
        "build_reviewed_control_safety_gate_v2",
        "reviewed_control_policy_v2",
        "reviewed_control_review_protocol_v2",
        "validate_reviewed_control_safety_gate_v2",
    }

    assert public <= set(logic_pipeline.__all__)
    assert public == set(reviewed_control.__all__)
    for name in public:
        assert getattr(logic_pipeline, name) is getattr(
            reviewed_control,
            name,
        )


@pytest.mark.parametrize(
    "module_name",
    (
        "semantic_quality",
        "resource_statistics",
        "replay_gate",
    ),
)
def test_revision_2_gate_package_exports_match_source_module(
    module_name: str,
) -> None:
    module = importlib.import_module(
        f"benchmarks.logic_pipeline.{module_name}"
    )
    public = set(module.__all__)

    assert public <= set(logic_pipeline.__all__)
    for name in public:
        assert getattr(logic_pipeline, name) is getattr(module, name)


def test_import_has_no_filesystem_or_routing_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    production_modules_before = {
        name for name in sys.modules if name.startswith("ipfs_datasets_py.")
    }

    importlib.reload(logic_pipeline)

    assert list(tmp_path.iterdir()) == []
    assert {
        name for name in sys.modules if name.startswith("ipfs_datasets_py.")
    } == production_modules_before


def test_fresh_import_does_not_enable_application_auto_installers() -> None:
    """The CID bridge must not pull in the application package bootstrap."""

    repository_root = Path(__file__).resolve().parents[4]
    environment = dict(os.environ)
    for name in (
        "IPFS_DATASETS_AUTO_INSTALL",
        "IPFS_KIT_AUTO_INSTALL_DEPS",
        "IPFS_DATASETS_PY_BENCHMARK",
        "IPFS_DATASETS_PY_MINIMAL_IMPORTS",
    ):
        environment.pop(name, None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, os, sys; "
                "import benchmarks.logic_pipeline; "
                "print(json.dumps({"
                "'datasets': os.environ.get('IPFS_DATASETS_AUTO_INSTALL'),"
                "'kit': os.environ.get('IPFS_KIT_AUTO_INSTALL_DEPS'),"
                "'package_loaded': 'ipfs_datasets_py' in sys.modules"
                "}, sort_keys=True))"
            ),
        ],
        cwd=repository_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "datasets": None,
        "kit": None,
        "package_loaded": False,
    }


def test_all_mutable_defaults_are_scoped_below_the_run_root(tmp_path: Path) -> None:
    first = logic_pipeline.ExecutionDefaults(
        "smoke-001",
        benchmark_root=tmp_path / "benchmark",
    )
    second = logic_pipeline.ExecutionDefaults(
        "smoke-002",
        benchmark_root=tmp_path / "benchmark",
    )

    assert first.paths.run_root == tmp_path / "benchmark" / "smoke-001"
    assert set(first.paths.as_dict()) == {
        "run_root",
        *logic_pipeline.RUN_DIRECTORY_NAMES,
    }
    assert all(
        path == first.paths.run_root or path.is_relative_to(first.paths.run_root)
        for path in first.paths.directories()
    )
    assert set(first.paths.directories()).isdisjoint(second.paths.directories())
    assert first.cache_namespace != second.cache_namespace
    assert not first.paths.run_root.exists()


def test_materialization_only_creates_run_scoped_directories(tmp_path: Path) -> None:
    defaults = logic_pipeline.ExecutionDefaults(
        "materialize-001",
        benchmark_root=tmp_path / "benchmark",
    )

    defaults.paths.materialize()

    assert all(path.is_dir() for path in defaults.paths.directories())
    assert {path.name for path in defaults.paths.run_root.iterdir()} == set(
        logic_pipeline.RUN_DIRECTORY_NAMES
    )


@pytest.mark.parametrize(
    "run_id",
    ["", ".", "..", "../escape", "/absolute", "space id", "slash/id", "a" * 129],
)
def test_unsafe_run_ids_are_rejected(run_id: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="run_id"):
        logic_pipeline.RunPaths.for_run(run_id, benchmark_root=tmp_path)


def test_empty_benchmark_root_and_duplicate_variants_are_rejected() -> None:
    with pytest.raises(ValueError, match="benchmark_root"):
        logic_pipeline.ExecutionDefaults("smoke-001", benchmark_root="")

    with pytest.raises(ValueError, match="duplicate"):
        logic_pipeline.ExecutionDefaults("smoke-001", variants=("A0", "A0"))


def test_smoke_manifest_is_deterministic_and_canonical(tmp_path: Path) -> None:
    root = tmp_path / "benchmark"

    first = logic_pipeline.build_smoke_manifest("repeatable-001", benchmark_root=root)
    second = logic_pipeline.build_smoke_manifest("repeatable-001", benchmark_root=root)
    canonical = logic_pipeline.canonical_manifest_json(first)

    assert first == second
    assert logic_pipeline.manifest_sha256(first) == logic_pipeline.manifest_sha256(
        second
    )
    assert json.loads(canonical) == first
    assert canonical == json.dumps(
        first,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def test_default_smoke_manifest_has_a_frozen_content_digest() -> None:
    manifest = logic_pipeline.build_smoke_manifest("smoke-contract-v1")

    assert (
        logic_pipeline.manifest_sha256(manifest)
        == "33accd31da8ba1bfdeb1a395bf84e0ff1a2b0d8ec55d4a9fa4dbf3ad127a93a4"
    )


def test_smoke_defaults_are_offline_shadow_only_and_non_promoting() -> None:
    defaults = logic_pipeline.ExecutionDefaults("safe-defaults-001")
    manifest = defaults.smoke_manifest()

    assert defaults.variants == ("A0", "A1", "A7", "A8")
    assert defaults.shadow_only is True
    assert defaults.network_enabled is False
    assert defaults.model_calls_enabled is False
    assert defaults.auto_merge is False
    assert defaults.production_routing_changes is False
    assert manifest["mode"] == "shadow"
    assert manifest["execution"] == {
        "network_enabled": False,
        "model_calls_enabled": False,
        "auto_merge": False,
        "production_routing_changes": False,
    }


def test_g240_public_api_excludes_forgeable_builders_and_synthetic_factory() -> None:
    forbidden = {
        "build_g240_source_orchestration_receipt_v2",
        "build_g240_replay_orchestration_receipt_v2",
        "G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2",
        "G240_SYNTHETIC_ADAPTER_FACTORY_SCHEMA_V2",
        "build_g240_synthetic_adapter_configuration_v2",
    }

    assert forbidden.isdisjoint(logic_pipeline.__all__)
    assert all(
        not hasattr(logic_pipeline, name)
        for name in forbidden
    )
    assert callable(
        logic_pipeline.validate_g240_production_execution_request_v2
    )


def test_g241_custody_access_api_is_exported_exactly_once() -> None:
    expected = {
        "G241_GIT_EXECUTABLE_IDENTITY_SCHEMA_V1",
        "G241_LEDGER_FILE_IDENTITY_SCHEMA_V1",
        "G241_RELEASE_CONSUMPTION_TOMBSTONE_SCHEMA_V1",
        "G241_RELEASE_LEDGER_AUTHORITY_SCHEMA_V1",
        "G241CustodyAccessTransactionV1",
        "G241ReleaseConsumptionTombstoneV1",
        "consume_g241_release_for_access_v1",
        "g241_git_executable_cid_v1",
        "g241_release_ledger_authority_cid_v1",
        "load_and_validate_g241_release_receipt_v1",
    }

    assert expected <= set(logic_pipeline.__all__)
    assert all(
        logic_pipeline.__all__.count(name) == 1
        and hasattr(logic_pipeline, name)
        for name in expected
    )
