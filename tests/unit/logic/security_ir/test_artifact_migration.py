from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.security_ir import artifact_migration as migration
from tools.security_ir import inventory_artifacts


REPO_ROOT = Path(__file__).resolve().parents[4]
INVENTORY_PATH = (
    REPO_ROOT / "docs/security_verification/security_ir_artifact_inventory.json"
)
MANIFEST_PATH = REPO_ROOT / migration.DEFAULT_MANIFEST_PATH


def _inventory() -> dict:
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _inventory_digest(records: list[dict]) -> str:
    encoded = json.dumps(
        records,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_checked_in_manifest_is_complete_and_deterministic() -> None:
    inventory = _inventory()
    first = migration.build_migration_manifest(inventory)
    second = migration.build_migration_manifest(deepcopy(inventory))

    assert first == second == _manifest()
    assert migration.render_migration_manifest(first) == MANIFEST_PATH.read_text(
        encoding="utf-8"
    )
    assert first["schema_version"] == "SecurityArtifactMigration@1"
    deterministic = first["deterministic_fields"]
    assert deterministic["artifact_count"] == inventory["artifact_count"] == 269
    assert deterministic["source_inventory"]["inventory_sha256"] == (
        inventory["inventory_sha256"]
    )
    assert deterministic["authority_decisions_made"] == 0
    assert deterministic["class_counts"] == {
        "archive": 24,
        "golden": 9,
        "promoted": 9,
        "run": 135,
        "source": 92,
    }
    assert deterministic["legacy_id_count"] == 731

    paths = [record["legacy"]["path"] for record in deterministic["records"]]
    assert paths == sorted(paths, key=lambda value: value.encode("utf-8"))
    assert len(paths) == len(set(paths))
    assert len(
        {record["record_id"] for record in deterministic["records"]}
    ) == len(paths)
    assert migration.DEFAULT_MANIFEST_PATH not in paths


def test_migration_metadata_cannot_recursively_enter_legacy_inventory(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "security_ir_artifacts"
    migrations = artifact_root / "migrations"
    migrations.mkdir(parents=True)
    (artifact_root / "legacy.json").write_text("{}\n", encoding="utf-8")
    (migrations / "manifest.json").write_text("{}\n", encoding="utf-8")

    paths = inventory_artifacts.filesystem_artifact_paths(tmp_path)
    assert [path.as_posix() for path in paths] == [
        "security_ir_artifacts/legacy.json"
    ]


def test_every_legacy_hash_id_and_inventory_record_is_preserved() -> None:
    inventory = _inventory()
    manifest = _manifest()
    migration.validate_migration_manifest(manifest)

    restored = migration.restore_inventory_records(manifest)
    assert restored == inventory["artifacts"]
    assert [record["sha256"] for record in restored] == [
        record["sha256"] for record in inventory["artifacts"]
    ]
    assert [record["legacy_ids"] for record in restored] == [
        record["legacy_ids"] for record in inventory["artifacts"]
    ]
    assert sum(len(record["legacy_ids"]) for record in restored) == 731

    receipt = migration.verify_migration_integrity(
        manifest,
        REPO_ROOT,
        inventory=inventory,
    )
    assert receipt.valid
    assert receipt.checked_artifact_count == 269
    assert receipt.legacy_id_count == 731
    assert receipt.issues == ()


def test_classes_and_safety_flags_do_not_select_ambiguous_authority() -> None:
    records = {
        item["legacy"]["path"]: item
        for item in _manifest()["deterministic_fields"]["records"]
    }
    expected = {
        "security_ir_artifacts/assurance-baseline.md": "golden",
        "security_ir_artifacts/corpora/xaman-app/security-model-ir.json": "source",
        "security_ir_artifacts/environment/lean-lane-report.json": "run",
        "security_ir_artifacts/production/evidence-bundle-report.json": "promoted",
        "security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.vo": "archive",
    }
    for path, artifact_class in expected.items():
        record = records[path]
        assert record["target"]["artifact_class"] == artifact_class
        assert record["target"]["authority_selected"] is False

    ambiguous = records[
        "security_ir_artifacts/corpora/xaman-app/native-boundary-coverage-new.json"
    ]
    assert ambiguous["flags"] == {
        "ambiguous": True,
        "transient": False,
        "unknown": False,
    }
    assert ambiguous["target"]["artifact_class"] == "archive"
    assert ambiguous["target"]["disposition"] == "retain_pending_review"
    assert ambiguous["target"]["authority_selected"] is False

    transient = records[
        "security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.vo"
    ]
    assert transient["flags"]["transient"] is True
    assert transient["target"]["disposition"] == "retain_regenerable_output"


def test_unknown_and_transient_fixture_records_are_archived_and_flagged() -> None:
    inventory = _inventory()
    fixture = deepcopy(inventory)
    fixture["artifacts"] = deepcopy(inventory["artifacts"][:2])
    fixture["artifacts"][0]["classification"] = "unknown"
    fixture["artifacts"][0]["is_temporary"] = False
    fixture["artifacts"][1]["classification"] = "transient compiler output"
    fixture["artifacts"][1]["is_temporary"] = True
    fixture["artifact_count"] = len(fixture["artifacts"])
    fixture["inventory_sha256"] = _inventory_digest(fixture["artifacts"])

    manifest = migration.build_migration_manifest(fixture)
    records = manifest["deterministic_fields"]["records"]
    unknown = next(item for item in records if item["flags"]["unknown"])
    transient = next(item for item in records if item["flags"]["transient"])
    assert unknown["target"]["artifact_class"] == "archive"
    assert unknown["target"]["disposition"] == "retain_pending_classification"
    assert transient["target"]["artifact_class"] == "archive"
    assert transient["target"]["disposition"] == "retain_regenerable_output"
    assert all(item["target"]["authority_selected"] is False for item in records)


def test_deterministic_and_observational_fields_are_separate() -> None:
    manifest = _manifest()
    changed_observation = deepcopy(manifest)
    annotations = changed_observation["observational_fields"]["inventory_annotations"]
    annotations[0]["recommendations"] = ["review guidance changed"]

    migration.validate_migration_manifest(changed_observation)
    assert changed_observation["manifest_id"] == manifest["manifest_id"]
    assert changed_observation["manifest_sha256"] == manifest["manifest_sha256"]

    changed_deterministic = deepcopy(manifest)
    changed_deterministic["deterministic_fields"]["records"][0]["legacy"][
        "size_bytes"
    ] += 1
    with pytest.raises(migration.ArtifactMigrationError, match="manifest_sha256"):
        migration.validate_migration_manifest(changed_deterministic)


def test_reference_migration_is_idempotent_and_reversible() -> None:
    manifest = _manifest()
    legacy = manifest["deterministic_fields"]["records"][0]["legacy"]

    migrated = migration.migrate_legacy_reference(
        manifest,
        {"path": legacy["path"], "sha256": legacy["sha256"]},
    )
    assert migration.migrate_legacy_reference(manifest, migrated) == migrated
    assert migration.reverse_migration(manifest, migrated) == {
        "legacy_ids": legacy["legacy_ids"],
        "path": legacy["path"],
        "sha256": legacy["sha256"],
    }
    assert migration.reverse_migration(manifest, migrated["record_id"]) == (
        migration.reverse_migration(manifest, migrated)
    )

    tampered = deepcopy(migrated)
    tampered["artifact_class"] = "promoted"
    with pytest.raises(migration.ArtifactMigrationError, match="not bound"):
        migration.reverse_migration(manifest, tampered)

    with pytest.raises(migration.ArtifactMigrationIntegrityError) as exc_info:
        migration.migrate_legacy_reference(
            manifest,
            {"path": legacy["path"], "sha256": "0" * 64},
        )
    assert not exc_info.value.receipt.valid


def test_integrity_audit_detects_missing_changed_and_inventory_drift(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "security_ir_artifacts"
    artifact_root.mkdir()
    path = artifact_root / "source.json"
    path.write_bytes(b'{"id":"legacy"}\n')
    record = {
        "ambiguity_reasons": [],
        "authority_selected": False,
        "classification": "source",
        "detected_format": "json",
        "file_type": "regular-file",
        "is_mutable_alias": False,
        "is_new_variant": False,
        "is_temporary": False,
        "legacy_ids": [{"field": "id", "value": "legacy"}],
        "likely_producers": ["fixture"],
        "path": "security_ir_artifacts/source.json",
        "recommendations": ["preserve"],
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": len(path.read_bytes()),
        "variant_kinds": [],
        "variant_of": None,
    }
    inventory = {
        "artifact_count": 1,
        "artifact_root": "security_ir_artifacts",
        "artifacts": [record],
        "inventory_sha256": _inventory_digest([record]),
        "schema_version": "SecurityArtifactInventory@1",
        "scope": "filesystem files",
    }
    manifest = migration.build_migration_manifest(inventory)
    assert migration.audit_migration_integrity(
        manifest, tmp_path, inventory=inventory
    ).valid

    path.write_bytes(b"tampered")
    changed = migration.audit_migration_integrity(manifest, tmp_path)
    assert not changed.valid
    assert any("SHA-256 changed" in issue for issue in changed.issues)
    with pytest.raises(migration.ArtifactMigrationIntegrityError):
        migration.verify_migration_integrity(manifest, tmp_path)

    path.unlink()
    missing = migration.audit_migration_integrity(manifest, tmp_path)
    assert not missing.valid
    assert any("missing or unreadable" in issue for issue in missing.issues)

    drifted_inventory = deepcopy(inventory)
    drifted_inventory["artifacts"][0]["recommendations"] = ["different"]
    drifted = migration.audit_migration_integrity(
        manifest, tmp_path, inventory=drifted_inventory
    )
    assert not drifted.valid
    assert any("source inventory" in issue or "reversed" in issue for issue in drifted.issues)
