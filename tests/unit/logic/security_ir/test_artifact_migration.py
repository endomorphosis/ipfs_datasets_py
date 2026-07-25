"""Contracts for complete, reversible Security artifact migration metadata."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath

import pytest

from ipfs_datasets_py.logic.security_ir.artifact_migration import (
    ArtifactMigrationError,
    ArtifactMigrationIntegrityError,
    DEFAULT_MANIFEST_PATH,
    SECURITY_ARTIFACT_MIGRATION_SCHEMA_VERSION,
    SecurityArtifactMigration,
    audit_migration_integrity,
    build_migration_manifest,
    load_migration_manifest,
    migrate_artifact_path,
    render_migration_manifest,
    reverse_artifact_path,
    validate_migration_manifest,
    verify_migration_integrity,
    write_migration_manifest,
)
from tools.security_ir import inventory_artifacts


REPO_ROOT = Path(__file__).resolve().parents[4]
INVENTORY_PATH = (
    REPO_ROOT / "docs/security_verification/security_ir_artifact_inventory.json"
)
MANIFEST_PATH = REPO_ROOT / DEFAULT_MANIFEST_PATH


def _inventory() -> dict:
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _records_by_legacy_path(manifest: dict) -> dict[str, dict]:
    return {
        item["legacy_path"]: item
        for item in manifest["deterministic"]["records"]
    }


def test_checked_in_manifest_is_complete_deterministic_and_idempotent() -> None:
    inventory = _inventory()
    first = build_migration_manifest(inventory)
    second = build_migration_manifest(deepcopy(inventory))

    assert first == second
    assert first == _manifest()
    assert render_migration_manifest(first) == MANIFEST_PATH.read_text(
        encoding="utf-8"
    )
    assert first["schema_version"] == SECURITY_ARTIFACT_MIGRATION_SCHEMA_VERSION
    assert first["deterministic"]["legacy_artifact_count"] == inventory[
        "artifact_count"
    ]
    assert len(first["deterministic"]["records"]) == inventory["artifact_count"]
    assert set(first["deterministic"]["record_counts_by_class"]) == {
        "source",
        "golden",
        "run",
        "promoted",
        "archive",
    }
    assert sum(first["deterministic"]["record_counts_by_class"].values()) == 269
    assert PurePosixPath(DEFAULT_MANIFEST_PATH) not in (
        inventory_artifacts.filesystem_artifact_paths(REPO_ROOT)
    )
    validate_migration_manifest(first)
    assert load_migration_manifest(MANIFEST_PATH) == first


def test_every_legacy_hash_id_and_path_is_preserved_exactly() -> None:
    inventory = _inventory()
    manifest = _manifest()
    migrated = _records_by_legacy_path(manifest)

    assert set(migrated) == {item["path"] for item in inventory["artifacts"]}
    for source in inventory["artifacts"]:
        target = migrated[source["path"]]
        assert target["legacy_path"] == source["path"]
        assert target["legacy_sha256"] == source["sha256"]
        assert target["v1_content_sha256"] == source["sha256"]
        assert target["v1_artifact_id"] == f"sha256:{source['sha256']}"
        assert target["legacy_ids"] == source["legacy_ids"]
        assert target["size_bytes"] == source["size_bytes"]
        assert migrate_artifact_path(manifest, source["path"]) == target["v1_path"]
        assert reverse_artifact_path(manifest, target["v1_path"]) == source["path"]
        # Re-applying either direction is a no-op.
        assert migrate_artifact_path(manifest, target["v1_path"]) == target["v1_path"]
        assert reverse_artifact_path(manifest, source["path"]) == source["path"]

    facade = SecurityArtifactMigration.from_dict(manifest)
    sample = manifest["deterministic"]["records"][0]
    assert facade.migrate_path(sample["legacy_path"]) == sample["v1_path"]
    assert facade.reverse_path(sample["v1_path"]) == sample["legacy_path"]
    assert SecurityArtifactMigration.from_dict(facade.to_dict()).migration_id == (
        facade.migration_id
    )


def test_transient_unknown_and_ambiguous_records_fail_closed_to_archive() -> None:
    manifest = _manifest()
    records = manifest["deterministic"]["records"]

    transient = [
        item
        for item in records
        if item["source_classification"] == "transient compiler output"
    ]
    ambiguous = [
        item for item in records if item["source_classification"] == "ambiguous"
    ]
    unknown = [
        item for item in records if item["source_classification"] == "unknown"
    ]
    assert len(transient) == 20
    assert all(item["artifact_class"] == "archive" for item in transient)
    assert all("transient" in item["flags"] for item in transient)
    assert len(ambiguous) == 4
    assert all(item["artifact_class"] == "archive" for item in ambiguous)
    assert all("ambiguous" in item["flags"] for item in ambiguous)
    observations = {
        item["record_id"]: item for item in manifest["observational"]["records"]
    }
    assert all(
        observations[item["record_id"]]["authority_selected"] is False
        for item in ambiguous
    )
    assert unknown == []
    assert manifest["deterministic"]["record_counts_by_flag"]["unknown"] == 0

    fixture = {
        "schema_version": "SecurityArtifactInventory@1",
        "artifact_root": "security_ir_artifacts",
        "scope": "fixture",
        "artifact_count": 1,
        "inventory_sha256": "0" * 64,
        "classification_counts": {"unknown": 1},
        "format_counts": {"binary": 1},
        "authority_decisions_made": 0,
        "legacy_id_extraction": "fixture",
        "variant_groups": [],
        "artifacts": [
            {
                "path": "security_ir_artifacts/unclassified.bin",
                "sha256": "a" * 64,
                "size_bytes": 7,
                "detected_format": "binary",
                "classification": "unknown",
                "legacy_ids": [],
                "is_temporary": False,
                "is_new_variant": False,
                "is_mutable_alias": False,
                "variant_kinds": [],
                "variant_of": None,
                "ambiguity_reasons": ["no classifier"],
                "likely_producers": ["unknown"],
                "recommendations": ["manual review"],
                "authority_selected": False,
            }
        ],
    }
    unknown_manifest = build_migration_manifest(fixture)
    unknown_record = unknown_manifest["deterministic"]["records"][0]
    assert unknown_record["artifact_class"] == "archive"
    assert unknown_record["flags"] == ["unknown"]


def test_deterministic_and_observational_fields_are_separate() -> None:
    manifest = _manifest()
    partition = manifest["deterministic"]["field_partition"]
    assert set(partition["deterministic_record_fields"]).isdisjoint(
        partition["observational_record_fields"]
    )
    record = manifest["deterministic"]["records"][0]
    observed_record = manifest["observational"]["records"][0]
    assert set(record) == set(partition["deterministic_record_fields"])
    assert set(observed_record) - {"record_id"} == set(
        partition["observational_record_fields"]
    )

    changed_observation = deepcopy(manifest)
    changed_observation["observational"]["notes"].append("operator note")
    changed_observation["observational"]["records"][0][
        "likely_producers"
    ].append("another observation")
    validate_migration_manifest(changed_observation)
    assert changed_observation["migration_id"] == manifest["migration_id"]

    changed_identity = deepcopy(manifest)
    changed_identity["deterministic"]["records"][0]["legacy_sha256"] = "f" * 64
    with pytest.raises(ArtifactMigrationError):
        validate_migration_manifest(changed_identity)


def test_ambiguous_authority_and_non_reversible_edits_are_rejected() -> None:
    manifest = _manifest()
    ambiguous_index = next(
        index
        for index, item in enumerate(manifest["deterministic"]["records"])
        if "ambiguous" in item["flags"]
    )

    selected = deepcopy(manifest)
    selected["observational"]["records"][ambiguous_index][
        "authority_selected"
    ] = True
    with pytest.raises(ArtifactMigrationError, match="cannot select authority"):
        validate_migration_manifest(selected)

    collision = deepcopy(manifest)
    collision["deterministic"]["records"][1]["v1_path"] = (
        collision["deterministic"]["records"][0]["v1_path"]
    )
    with pytest.raises(ArtifactMigrationError, match="not reversible|duplicate"):
        validate_migration_manifest(collision)

    with pytest.raises(KeyError):
        migrate_artifact_path(manifest, "security_ir_artifacts/not-in-manifest.json")


def test_integrity_receipt_covers_every_legacy_file_without_writes(
    tmp_path: Path,
) -> None:
    fixture_root = tmp_path / "security_ir_artifacts"
    fixture_root.mkdir()
    legacy = fixture_root / "source.json"
    content = b'{"model_id":"legacy"}\n'
    legacy.write_bytes(content)
    inventory = {
        "schema_version": "SecurityArtifactInventory@1",
        "artifact_root": "security_ir_artifacts",
        "scope": "fixture",
        "artifact_count": 1,
        "inventory_sha256": "b" * 64,
        "classification_counts": {"source": 1},
        "format_counts": {"json": 1},
        "authority_decisions_made": 0,
        "legacy_id_extraction": "fixture",
        "variant_groups": [],
        "artifacts": [
            {
                "path": "security_ir_artifacts/source.json",
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
                "detected_format": "json",
                "classification": "source",
                "legacy_ids": [{"field": "model_id", "value": "legacy"}],
                "is_temporary": False,
                "is_new_variant": False,
                "is_mutable_alias": False,
                "variant_kinds": [],
                "variant_of": None,
                "ambiguity_reasons": [],
                "likely_producers": ["fixture"],
                "recommendations": ["preserve"],
                "authority_selected": False,
            }
        ],
    }
    manifest = build_migration_manifest(inventory)
    before = legacy.read_bytes()

    receipt = verify_migration_integrity(manifest, tmp_path)
    assert receipt.valid
    assert receipt.checked_artifact_count == 1
    assert receipt.checked_legacy_sha256 == (hashlib.sha256(content).hexdigest(),)
    assert legacy.read_bytes() == before

    legacy.write_bytes(b"changed")
    failure = audit_migration_integrity(manifest, tmp_path)
    assert not failure.valid
    assert any(issue.startswith("digest_changed:") for issue in failure.issues)
    with pytest.raises(ArtifactMigrationIntegrityError):
        verify_migration_integrity(manifest, tmp_path)


def test_writer_is_atomic_scoped_and_idempotent(tmp_path: Path) -> None:
    source_root = tmp_path / "security_ir_artifacts"
    source_root.mkdir()
    content = b"x"
    inventory = {
        "schema_version": "SecurityArtifactInventory@1",
        "artifact_root": "security_ir_artifacts",
        "scope": "fixture",
        "artifact_count": 1,
        "inventory_sha256": "c" * 64,
        "classification_counts": {"source": 1},
        "format_counts": {"binary": 1},
        "authority_decisions_made": 0,
        "legacy_id_extraction": "fixture",
        "variant_groups": [],
        "artifacts": [
            {
                "path": "security_ir_artifacts/input.bin",
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": 1,
                "detected_format": "binary",
                "classification": "source",
                "legacy_ids": [],
                "is_temporary": False,
                "is_new_variant": False,
                "is_mutable_alias": False,
                "variant_kinds": [],
                "variant_of": None,
                "ambiguity_reasons": [],
                "likely_producers": ["fixture"],
                "recommendations": ["preserve"],
                "authority_selected": False,
            }
        ],
    }
    manifest = build_migration_manifest(inventory)

    assert write_migration_manifest(
        manifest, DEFAULT_MANIFEST_PATH, repo_root=tmp_path
    )
    output = tmp_path / DEFAULT_MANIFEST_PATH
    before = output.stat().st_mtime_ns
    assert not write_migration_manifest(
        manifest, DEFAULT_MANIFEST_PATH, repo_root=tmp_path
    )
    assert output.stat().st_mtime_ns == before
    assert load_migration_manifest(output) == manifest

    with pytest.raises(ArtifactMigrationError, match="exactly"):
        write_migration_manifest(
            manifest,
            "security_ir_artifacts/source.json",
            repo_root=tmp_path,
        )
