"""Read-only inventory tests; authored files never establish model qualification."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
MODULE = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/alignment_inventory.py"
spec = importlib.util.spec_from_file_location("alignment_inventory_test_subject", MODULE)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def fixture_tree(tmp_path):
    repository, workspace = tmp_path / "repository", tmp_path / "workspace"
    repository.mkdir()
    workspace.mkdir()
    checkpoint = workspace / "checkpoints/current.json"
    checkpoint_hash = write_json(checkpoint, {
        "schema": "shared-source-384-autoencoder/v2", "dimension": 384,
        "domain_id": "legal_ir", "qualified": True,
        "model_state": {"fixture_only": [0.1, 0.2]},
        "config": {"hidden_size": 32, "projection_width": 16},
    })
    plan = {"schema": "gte-parallel-lineage-plan/v1", "workspace_root": str(workspace),
            "lanes": [
                {"lane_id": "legacy_8d", "dimension": 8, "runtime_id": "legal_ir:legacy_v1",
                 "checkpoint": {"path": "checkpoints/missing.json", "sha256": "a" * 64}},
                {"lane_id": "source_384d", "dimension": 384,
                 "runtime_id": "legal_ir:source_training_v2", "representation_id": "fixture:g384",
                 "checkpoint": {"path": "checkpoints/current.json", "sha256": checkpoint_hash}},
                {"lane_id": "multilingual_768d", "dimension": 768,
                 "runtime_id": "legal_ir:gte_multilingual_768_v1", "checkpoint": None},
            ]}
    plan_path = repository / "configs/autoencoders/gte_parallel_lineages_v1.json"
    write_json(plan_path, plan)
    return {"repository": repository, "workspace": workspace, "plan": plan,
            "plan_path": plan_path, "checkpoint": checkpoint, "checkpoint_hash": checkpoint_hash}


def inventory(tree, **options):
    return subject.describe_alignment_assets(tree["repository"], **options)


def lane(report, lane_id):
    return next(row for row in report["lanes"] if row["lane_id"] == lane_id)


def test_binds_exact_small_bytes_and_separates_declared_qualification(fixture_tree):
    before = fixture_tree["checkpoint"].read_bytes()
    report = inventory(fixture_tree)
    current = lane(report, "source_384d")
    assert report == inventory(fixture_tree)
    assert json.loads(json.dumps(report)) == report
    assert current["configured"] is True and current["metadata_inspected"] is True
    assert current["checkpoint"]["observed_sha256"] == fixture_tree["checkpoint_hash"]
    assert current["checkpoint"]["expected_sha256_match"] is True
    assert current["checkpoint"]["declared_metadata"]["qualified"] is True
    assert "model_state" not in current["checkpoint"]["declared_metadata"]
    assert current["qualified"] is False and report["qualified"] is False
    assert current["numerically_evaluated"] is False
    assert current["alignment_training_readiness"] == "not_evaluated"
    assert report["source_identity_scope"] == "listed_files_only_not_complete_dependency_closure"
    assert fixture_tree["checkpoint"].read_bytes() == before


def test_missing_and_unconfigured_assets_are_distinct_without_mutation(fixture_tree):
    report = inventory(fixture_tree)
    legacy = lane(report, "legacy_8d")
    target = lane(report, "multilingual_768d")
    assert legacy["configured"] is True and legacy["inventory_status"] == "missing"
    assert legacy["path_exists"] is False
    assert target["configured"] is True and target["inventory_status"] == "checkpoint_unconfigured"
    assert target["path_exists"] is None
    assert not (fixture_tree["workspace"] / "checkpoints/missing.json").exists()
    assert report["model_loaded"] is False
    assert report["download_executed"] is False and report["training_executed"] is False


def test_empty_repository_reports_all_lanes_without_creating_directories(tmp_path):
    missing = tmp_path / "does-not-exist"
    report = subject.describe_alignment_assets(missing)
    assert all(row["configured"] is False for row in report["lanes"])
    assert all(row["inventory_status"] == "unconfigured" for row in report["lanes"])
    assert all(row["status"] == "missing" for row in report["configurations"])
    assert not missing.exists()


def test_workspace_override_controls_relative_paths(fixture_tree, tmp_path):
    override = tmp_path / "other-workspace"
    report = inventory(fixture_tree, workspace_root=override)
    current = lane(report, "source_384d")
    assert current["checkpoint"]["path"] == str(override / "checkpoints/current.json")
    assert current["inventory_status"] == "missing"


def test_hash_mismatch_remains_visible_and_is_not_metadata_readiness(fixture_tree):
    fixture_tree["checkpoint"].write_bytes(b'{"dimension":384}')
    current = lane(inventory(fixture_tree), "source_384d")
    assert current["checkpoint"]["expected_sha256_match"] is False
    assert "expected_sha256_mismatch" in current["checkpoint"]["reasons"]
    assert current["inventory_status"] == "invalid"
    assert current["qualified"] is False


@pytest.mark.parametrize("raw", [
    b'{"schema":"gte-parallel-lineage-plan/v1","schema":"duplicate"}',
    b'{"schema":"gte-parallel-lineage-plan/v1","bad":NaN}',
    b'{"schema":"gte-parallel-lineage-plan/v1","bad":1e999}',
    b'[]', b'not-json', b'\xff',
])
def test_malformed_config_yields_stable_invalid_record(fixture_tree, raw):
    fixture_tree["plan_path"].write_bytes(raw)
    report = inventory(fixture_tree)
    plan = next(row for row in report["configurations"] if row["config_id"] == "gte_parallel_lineages_v1.json")
    assert plan["status"] == "invalid"
    assert plan["observed_sha256"] == hashlib.sha256(raw).hexdigest()
    assert plan["reasons"] == ["malformed_metadata_json"]
    assert all(row["configured"] is False for row in report["lanes"])


def test_unknown_config_schema_is_not_identified_by_lane_dimensions(fixture_tree):
    fixture_tree["plan"]["schema"] = "unrecognized/v1"
    write_json(fixture_tree["plan_path"], fixture_tree["plan"])
    report = inventory(fixture_tree)
    assert all(row["configured"] is False for row in report["lanes"])
    assert "unexpected_config_schema" in report["configurations"][1]["reasons"]


@pytest.mark.parametrize("location", ["config", "checkpoint", "ancestor"])
def test_symlinks_are_never_read(fixture_tree, location):
    if location == "ancestor":
        original = fixture_tree["checkpoint"].parent
        moved = original.with_name("real-checkpoints")
        original.rename(moved)
        original.symlink_to(moved, target_is_directory=True)
    else:
        original = fixture_tree["plan_path"] if location == "config" else fixture_tree["checkpoint"]
        moved = original.with_name("real-" + original.name)
        original.rename(moved)
        original.symlink_to(moved)
    report = inventory(fixture_tree)
    record = report["configurations"][1] if location == "config" else lane(report, "source_384d")["checkpoint"]
    assert record["observed_sha256"] is None
    assert record["content_read"] is False
    assert record["reasons"] == ["symlink_or_nonregular_path"]


def test_large_checkpoint_is_stat_only_even_with_a_declared_digest(fixture_tree):
    fixture_tree["checkpoint"].write_bytes(b"x" * (subject.DEFAULT_MAX_METADATA_BYTES + 1))
    current = lane(inventory(fixture_tree), "source_384d")
    assert current["inventory_status"] == "presence_only"
    assert current["checkpoint"]["expected_sha256"] == fixture_tree["checkpoint_hash"]
    assert current["checkpoint"]["observed_sha256"] is None
    assert current["checkpoint"]["expected_sha256_match"] is None
    assert current["checkpoint"]["content_read"] is False
    assert current["checkpoint"]["reasons"] == ["metadata_size_limit"]


def test_explicit_source_and_manifest_references_are_bounded_and_pin_checked(fixture_tree):
    source = fixture_tree["workspace"] / "source.py"
    source.write_text("raise AssertionError('must never execute')\n")
    donor = fixture_tree["workspace"] / "donor-pins.json"
    donor_hash = write_json(donor, {"schema": "authored-donor/v1", "teacher_qualified": True})
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    write_json(fixture_tree["repository"] / "configs/autoencoders/gte_migration_preparation_v1.json", {
        "schema": "gte-migration-preparation-config/v1",
        "source_files": [{"path": "source.py", "sha256": source_hash}],
    })
    write_json(fixture_tree["repository"] / "configs/autoencoders/gte_decoder_transfer_preparation_v1.json", {
        "schema": "gte-decoder-transfer-preparation-config/v1",
        "donor_pins": {"path": "donor-pins.json", "sha256": donor_hash},
        "primary_training_archive": {"path": "source.py", "sha256": source_hash},
    })
    report = inventory(fixture_tree)
    observed = next(row for row in report["artifacts"] if row["field"] == "source_files/0")
    assert observed["kind"] == "source" and observed["observed_sha256"] == source_hash
    donor_record = next(row for row in report["artifacts"] if row["field"] == "donor_pins")
    assert donor_record["kind"] == "manifest" and donor_record["expected_sha256_match"] is True
    archive = next(row for row in report["artifacts"] if row["field"] == "primary_training_archive")
    assert archive["kind"] == "dataset" and archive["content_read"] is False
    assert report["qualified"] is False


def test_dataset_bodies_are_excluded_and_relative_traversal_is_reported(fixture_tree):
    dataset = fixture_tree["workspace"] / "validation.json"
    dataset.write_bytes(b"not json: sealed content must not be parsed")
    write_json(fixture_tree["repository"] / "configs/autoencoders/gte_migration_preparation_v1.json", {
        "schema": "gte-migration-preparation-config/v1",
        "datasets": [{"path": "validation.json", "sha256": "a" * 64}],
        "source_files": [{"path": "../escape.py", "sha256": "b" * 64}],
    })
    report = inventory(fixture_tree)
    record = next(row for row in report["artifacts"] if row["field"] == "datasets/0")
    assert record["status"] == "presence_only" and record["observed_sha256"] is None
    assert record["content_read"] is False
    assert any(row["reason"] == "path_traversal" for row in report["issues"])


def test_explicit_encoder_metadata_is_hashed_but_binary_weights_are_never_read(fixture_tree):
    encoder = fixture_tree["workspace"] / "encoder"
    encoder.mkdir()
    metadata_hash = write_json(encoder / "config.json", {"hidden_size": 768})
    weight = encoder / "model.safetensors"
    weight.write_bytes(b"tiny authored tensor placeholder")
    assets = [
        {"relative_to": "model", "path": "config.json", "sha256": metadata_hash,
         "bytes": (encoder / "config.json").stat().st_size},
        {"relative_to": "model", "path": "model.safetensors", "sha256": "a" * 64,
         "bytes": weight.stat().st_size},
    ]
    write_json(fixture_tree["repository"] / "configs/autoencoders/gte_multilingual_local_assets_v1.json", {
        "schema": "gte-multilingual-local-assets/v1", "files": assets,
    })
    fixture_tree["plan"]["lanes"][2]["producer"] = {"model_directory": "encoder"}
    write_json(fixture_tree["plan_path"], fixture_tree["plan"])
    report = inventory(fixture_tree)
    target = next(row for row in report["encoders"] if row["lane_id"] == "multilingual_768d")
    config, binary = target["assets"]
    assert config["observed_sha256"] == metadata_hash and config["expected_sha256_match"] is True
    assert binary["path_exists"] is True and binary["expected_bytes_match"] is True
    assert binary["observed_sha256"] is None and binary["expected_sha256_match"] is None
    assert binary["content_read"] is False and target["numerically_evaluated"] is False


@pytest.mark.parametrize("maximum", [True, 0, -1, 1.5, subject.MAX_METADATA_BYTES + 1])
def test_invalid_metadata_bounds_fail_before_inspection(fixture_tree, maximum):
    with pytest.raises(ValueError, match="max_metadata_bytes"):
        inventory(fixture_tree, max_metadata_bytes=maximum)


def test_lineage_catalog_retains_unselected_declared_checkpoint_pins(fixture_tree):
    expected = "a" * 64
    write_json(fixture_tree["repository"] / "configs/autoencoders/legal_autoencoder_lineages.json", {
        "schema": "legal-autoencoder-lineages/v1", "lineages": {
            "legacy_hub_v1": {"runtime_dimension": 8, "role": "immutable_distillation_teacher",
                              "checkpoint_policy": {"mode": "fixed_sha256", "sha256": expected}},
            "current_legal_v2": {"runtime_dimension": 384, "role": "evolving_legal_feature_student",
                                 "checkpoint_policy": {"mode": "explicit_sha256"}},
        },
    })
    report = inventory(fixture_tree)
    assert report["lineages"][0]["declared_checkpoint_policy"]["sha256"] == expected
    assert report["lineages"][0]["catalog_entry_is_selected_checkpoint"] is False
    assert report["lineages"][0]["qualified"] is False
    assert report["implementation_source"]["observed_sha256"] == hashlib.sha256(MODULE.read_bytes()).hexdigest()


def test_bad_config_workspace_and_lane_dimensions_are_explicit_diagnostics(fixture_tree):
    fixture_tree["plan"]["workspace_root"] = True
    fixture_tree["plan"]["lanes"][1]["dimension"] = 8
    write_json(fixture_tree["plan_path"], fixture_tree["plan"])
    report = inventory(fixture_tree)
    assert report["workspace_root"] == str(fixture_tree["repository"])
    assert lane(report, "source_384d")["configured"] is False
    assert {row["reason"] for row in report["issues"]} >= {
        "invalid_configured_workspace_root", "lane_dimension_mismatch"}


def test_explicit_alternate_encoder_manifest_is_honored(fixture_tree):
    fixture_tree["plan"]["lanes"][2]["producer"] = {
        "asset_manifest": "configs/autoencoders/private-assets.json",
        "model_directory": "private-encoder",
    }
    write_json(fixture_tree["plan_path"], fixture_tree["plan"])
    encoder = fixture_tree["workspace"] / "private-encoder/config.json"
    expected = write_json(encoder, {"hidden_size": 768})
    write_json(fixture_tree["repository"] / "configs/autoencoders/private-assets.json", {
        "schema": "gte-multilingual-local-assets/v1", "files": [
            {"relative_to": "model", "path": "config.json", "sha256": expected,
             "bytes": encoder.stat().st_size}],
    })
    target = next(row for row in inventory(fixture_tree)["encoders"] if row["lane_id"] == "multilingual_768d")
    assert target["assets"][0]["observed_sha256"] == expected
    assert target["asset_manifest"]["metadata_inspected"] is True
