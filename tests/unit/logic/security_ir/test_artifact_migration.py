"""Integrity contracts for the Security IR legacy-artifact migration map."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.security_ir.artifact_migration import (
    ArtifactClass,
    ArtifactMigrationIntegrityError,
    ArtifactMigrationValidationError,
    MigrationIssueKind,
    SecurityArtifactMigration,
    build_migration_manifest,
    load_migration_manifest,
    write_migration_manifest,
)
from tools.security_ir import inventory_artifacts


REPO_ROOT = Path(__file__).resolve().parents[4]
INVENTORY_PATH = (
    REPO_ROOT / "docs/security_verification/security_ir_artifact_inventory.json"
)
MANIFEST_PATH = REPO_ROOT / "security_ir_artifacts/migrations/manifest.json"
EXPECTED_REPOSITORY_COMMIT = "9f537204e735530161d1e9fe1919953f7c246d2d"


def _inventory() -> dict:
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def _manifest() -> SecurityArtifactMigration:
    return load_migration_manifest(MANIFEST_PATH)


def _by_legacy_path(manifest: SecurityArtifactMigration) -> dict:
    return {record.legacy_path: record for record in manifest.artifacts}


def _bind_inventory_digest(inventory: dict) -> dict:
    encoded = json.dumps(
        inventory["artifacts"],
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    inventory["inventory_sha256"] = hashlib.sha256(encoded).hexdigest()
    return inventory


def test_checked_in_manifest_is_complete_deterministic_and_inventory_bound() -> None:
    inventory = _inventory()
    checked_in = _manifest()
    rebuilt = build_migration_manifest(
        inventory,
        repository_commit=EXPECTED_REPOSITORY_COMMIT,
    )

    assert checked_in == rebuilt
    assert checked_in.to_json(pretty=True) == MANIFEST_PATH.read_text(
        encoding="utf-8"
    )
    assert checked_in.artifact_count == inventory["artifact_count"] == 269
    assert checked_in.source_inventory.inventory_sha256 == (
        inventory["inventory_sha256"]
    )
    assert checked_in.repository_commit == EXPECTED_REPOSITORY_COMMIT
    assert checked_in.manifest_id.startswith("bafkrei")
    assert checked_in.class_counts == {
        "source": 92,
        "golden": 9,
        "run": 135,
        "promoted": 9,
        "archive": 24,
    }
    assert [record.legacy_path for record in checked_in.artifacts] == sorted(
        record["path"] for record in inventory["artifacts"]
    )


def test_every_hash_id_and_legacy_path_is_preserved_verbatim() -> None:
    inventory = _inventory()
    manifest = _manifest()
    records = _by_legacy_path(manifest)

    assert set(records) == {item["path"] for item in inventory["artifacts"]}
    for legacy in inventory["artifacts"]:
        migrated = records[legacy["path"]]
        assert migrated.legacy_sha256 == legacy["sha256"]
        assert migrated.legacy_size_bytes == legacy["size_bytes"]
        assert [item.to_dict() for item in migrated.legacy_ids] == (
            legacy["legacy_ids"]
        )
        assert migrated.legacy_classification == legacy["classification"]
        assert migrated.authority_selected is False

    expected_ids = [
        (record["path"], identity["field"], identity["value"])
        for record in inventory["artifacts"]
        for identity in record["legacy_ids"]
    ]
    actual_ids = [
        (record.legacy_path, identity.field, identity.value)
        for record in manifest.artifacts
        for identity in record.legacy_ids
    ]
    assert actual_ids == expected_ids
    assert len(actual_ids) == 731


def test_classes_and_quarantine_flags_are_explicit_without_authority_choice() -> None:
    manifest = _manifest()
    records = _by_legacy_path(manifest)

    examples = {
        "security_ir_artifacts/corpora/xaman-app/security-model-ir.json":
            ArtifactClass.SOURCE,
        "security_ir_artifacts/proof-baseline.json": ArtifactClass.GOLDEN,
        "security_ir_artifacts/corpora/xaman-app/runtime-trace-report.json":
            ArtifactClass.RUN,
        "security_ir_artifacts/policies/security-decision-policy.json":
            ArtifactClass.PROMOTED,
        "security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.vo":
            ArtifactClass.ARCHIVE,
    }
    for path, expected_class in examples.items():
        assert records[path].target_class is expected_class

    transient = records[
        "security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.vo"
    ]
    assert transient.is_transient
    assert transient.requires_review
    assert transient.target_path.startswith(
        "security_ir_artifacts/archive/legacy/"
    )

    for path in (
        "security_ir_artifacts/corpora/xaman-app/"
        "native-boundary-coverage-new.json",
        "security_ir_artifacts/recovery/taskboard-preflight-latest.json",
    ):
        variant = records[path]
        assert variant.target_class is ArtifactClass.ARCHIVE
        assert variant.requires_review
        assert variant.authority_selected is False

    assert manifest.flag_counts["transient"] == 20
    assert manifest.flag_counts["unknown"] == 0


def test_unknown_fixture_is_flagged_and_archived() -> None:
    content = b"\x00opaque"
    inventory = _bind_inventory_digest({
        "schema_version": "SecurityArtifactInventory@1",
        "scope": "filesystem files",
        "artifact_count": 1,
        "inventory_sha256": "",
        "artifacts": [
            {
                "ambiguity_reasons": ["format has no reviewed producer"],
                "authority_selected": False,
                "classification": "unknown",
                "detected_format": "binary",
                "file_type": "regular-file",
                "is_mutable_alias": False,
                "is_new_variant": False,
                "is_temporary": False,
                "legacy_ids": [{"field": "id", "value": "opaque-legacy-id"}],
                "likely_producers": ["unknown"],
                "path": "security_ir_artifacts/opaque.bin",
                "recommendations": ["retain for review"],
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
                "variant_kinds": [],
                "variant_of": None,
            }
        ],
    })

    record = build_migration_manifest(inventory).artifacts[0]

    assert record.is_unknown
    assert record.requires_review
    assert record.target_class is ArtifactClass.ARCHIVE
    assert record.legacy_ids[0].value == "opaque-legacy-id"


def test_path_migration_is_idempotent_and_exactly_reversible() -> None:
    manifest = _manifest()
    inventory_records = {
        record["path"]: record for record in _inventory()["artifacts"]
    }

    for record in manifest.artifacts:
        migrated = manifest.migrate_path(record.legacy_path)
        assert migrated == record.target_path
        assert manifest.migrate_path(migrated) == migrated
        assert manifest.restore_path(migrated) == record.legacy_path
        assert manifest.restore_path(record.legacy_path) == record.legacy_path
        assert manifest.restore_record(migrated) == (
            inventory_records[record.legacy_path]
        )

    with pytest.raises(KeyError, match="not bound"):
        manifest.migrate_path("security_ir_artifacts/not-in-inventory.json")


def test_legacy_id_lookup_preserves_ambiguity_instead_of_selecting() -> None:
    manifest = _manifest()
    matches = manifest.records_for_legacy_id("model_id", "minimal-btc-exchange")

    assert len(matches) > 1
    assert [record.legacy_path for record in matches] == sorted(
        record.legacy_path for record in matches
    )
    assert all(record.authority_selected is False for record in matches)


def test_observations_round_trip_but_do_not_change_deterministic_identity() -> None:
    original = _manifest()
    observed = replace(
        original,
        observations={
            "generated_at": "2099-01-01T00:00:00Z",
            "environment": {"host": "different-runner"},
            "duration_ms": 999,
        },
    )

    assert observed.manifest_id == original.manifest_id
    assert observed.deterministic_bytes() == original.deterministic_bytes()
    assert observed.canonical_bytes() != original.canonical_bytes()
    assert SecurityArtifactMigration.from_json(observed.to_json()) == observed
    payload = observed.to_dict()
    assert set(payload) == {
        "deterministic",
        "manifest_id",
        "observations",
        "schema_version",
    }
    assert "observations" not in payload["deterministic"]


def test_integrity_receipt_checks_inventory_and_all_legacy_bytes() -> None:
    manifest = _manifest()
    report = manifest.verify_integrity(REPO_ROOT, inventory=_inventory())

    assert report.valid
    assert report.checked_artifact_count == manifest.artifact_count
    assert report.inventory_sha256 == manifest.source_inventory.inventory_sha256
    assert report.manifest_id == manifest.manifest_id


def test_integrity_detects_changed_bytes_and_inventory_ids(tmp_path: Path) -> None:
    root = tmp_path
    artifact_root = root / "security_ir_artifacts"
    artifact_root.mkdir()
    legacy_bytes = b'{"model_id":"original"}\n'
    legacy_path = artifact_root / "model.json"
    legacy_path.write_bytes(legacy_bytes)
    inventory = _bind_inventory_digest({
        "schema_version": "SecurityArtifactInventory@1",
        "scope": "filesystem files",
        "artifact_count": 1,
        "inventory_sha256": "",
        "artifacts": [
            {
                "ambiguity_reasons": [],
                "authority_selected": False,
                "classification": "source",
                "detected_format": "json",
                "file_type": "regular-file",
                "is_mutable_alias": False,
                "is_new_variant": False,
                "is_temporary": False,
                "legacy_ids": [{"field": "model_id", "value": "original"}],
                "likely_producers": ["fixture"],
                "path": "security_ir_artifacts/model.json",
                "recommendations": ["preserve"],
                "sha256": hashlib.sha256(legacy_bytes).hexdigest(),
                "size_bytes": len(legacy_bytes),
                "variant_kinds": [],
                "variant_of": None,
            }
        ],
    })
    manifest = build_migration_manifest(inventory)

    legacy_path.write_bytes(b"tampered")
    changed = manifest.audit_integrity(root, inventory=inventory)
    assert MigrationIssueKind.CHANGED in changed.issue_kinds
    with pytest.raises(ArtifactMigrationIntegrityError):
        manifest.verify_integrity(root, inventory=inventory)

    legacy_path.write_bytes(legacy_bytes)
    mutated_inventory = json.loads(json.dumps(inventory))
    mutated_inventory["artifacts"][0]["legacy_ids"][0]["value"] = "rewritten"
    inventory_changed = manifest.audit_integrity(
        root, inventory=mutated_inventory
    )
    assert MigrationIssueKind.INVALID in inventory_changed.issue_kinds


def test_manifest_rejects_tampered_identity_and_non_reversible_target() -> None:
    payload = _manifest().to_dict()
    payload["deterministic"]["artifacts"][0]["legacy_sha256"] = "0" * 64
    with pytest.raises(
        ArtifactMigrationValidationError, match="artifact_id does not match"
    ):
        SecurityArtifactMigration.from_dict(payload)

    payload = _manifest().to_dict()
    payload["deterministic"]["artifacts"][0]["target_path"] = (
        "security_ir_artifacts/promoted/not-reversible.json"
    )
    with pytest.raises(ArtifactMigrationValidationError, match="reversible"):
        SecurityArtifactMigration.from_dict(payload)


def test_writer_never_overwrites_legacy_or_proposed_artifacts(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    record = manifest.artifacts[0]

    with pytest.raises(ArtifactMigrationValidationError, match="overwrite"):
        write_migration_manifest(manifest, tmp_path / record.legacy_path)
    with pytest.raises(ArtifactMigrationValidationError, match="overwrite"):
        write_migration_manifest(manifest, tmp_path / record.target_path)


def test_legacy_inventory_excludes_migration_metadata_to_avoid_a_cycle(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "security_ir_artifacts"
    artifact_root.mkdir()
    (artifact_root / "source.json").write_text("{}\n", encoding="utf-8")
    migrations = artifact_root / "migrations"
    migrations.mkdir()
    (migrations / "manifest.json").write_text("{}\n", encoding="utf-8")

    inventory = inventory_artifacts.build_inventory(
        tmp_path, tracked_only=False
    )

    assert [record["path"] for record in inventory["artifacts"]] == [
        "security_ir_artifacts/source.json"
    ]
