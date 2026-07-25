"""Integrity and policy tests for the legacy Security artifact migration."""

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
    MigrationFlag,
    MigrationIssueKind,
    MigrationObservations,
    SECURITY_ARTIFACT_MIGRATION_INTERFACE,
    SECURITY_ARTIFACT_MIGRATION_SCHEMA_VERSION,
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


def _inventory() -> dict:
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def _manifest() -> SecurityArtifactMigration:
    return load_migration_manifest(MANIFEST_PATH)


def _inventory_record(
    path: str,
    content: bytes,
    classification: str,
    *,
    legacy_ids: list[dict[str, str]] | None = None,
    is_temporary: bool = False,
    is_new_variant: bool = False,
    is_mutable_alias: bool = False,
    ambiguity_reasons: list[str] | None = None,
    variant_of: str | None = None,
    file_type: str = "regular-file",
) -> dict:
    return {
        "ambiguity_reasons": ambiguity_reasons or [],
        "authority_selected": False,
        "classification": classification,
        "detected_format": "json",
        "file_type": file_type,
        "is_mutable_alias": is_mutable_alias,
        "is_new_variant": is_new_variant,
        "is_temporary": is_temporary,
        "legacy_ids": legacy_ids or [],
        "likely_producers": ["fixture producer"],
        "path": path,
        "recommendations": ["retain exact fixture bytes"],
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
        "variant_kinds": [],
        "variant_of": variant_of,
    }


def _fixture_inventory(records: list[dict]) -> dict:
    preimage = json.dumps(
        records,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {
        "artifact_count": len(records),
        "artifact_root": "security_ir_artifacts",
        "artifacts": records,
        "inventory_sha256": hashlib.sha256(preimage).hexdigest(),
        "schema_version": "SecurityArtifactInventory@1",
        "total_size_bytes": sum(item["size_bytes"] for item in records),
    }


def test_checked_in_manifest_preserves_every_legacy_path_hash_and_id() -> None:
    inventory = _inventory()
    manifest = _manifest()
    rebuilt = build_migration_manifest(
        inventory,
        inventory_content_sha256=hashlib.sha256(
            INVENTORY_PATH.read_bytes()
        ).hexdigest(),
        repository_revision="commit:bca22890ea668092421314608587daa5c2900326",
        deterministic_metadata={
            "authority_decisions_made": 0,
            "migration_task_id": "IRF-025",
            "source_inventory_scope": "git-tracked legacy files",
        },
    )
    records = {
        item["path"]: item for item in inventory["artifacts"]
    }
    migrations = {
        item.legacy_path: item for item in manifest.artifacts
    }

    assert manifest.schema_version == SECURITY_ARTIFACT_MIGRATION_SCHEMA_VERSION
    assert manifest.interface == SECURITY_ARTIFACT_MIGRATION_INTERFACE
    assert rebuilt == manifest
    assert manifest.to_json(pretty=True) == MANIFEST_PATH.read_text(
        encoding="utf-8"
    )
    assert manifest.inventory.inventory_sha256 == inventory["inventory_sha256"]
    assert manifest.inventory.content_sha256 == hashlib.sha256(
        INVENTORY_PATH.read_bytes()
    ).hexdigest()
    assert manifest.artifact_count == inventory["artifact_count"] == 269
    assert manifest.total_size_bytes == inventory["total_size_bytes"]
    assert set(migrations) == set(records)

    for path, record in records.items():
        migration = migrations[path]
        assert migration.legacy_sha256 == record["sha256"]
        assert migration.legacy_size_bytes == record["size_bytes"]
        assert [item.to_dict() for item in migration.legacy_ids] == record[
            "legacy_ids"
        ]
        assert migration.authority_selected is False

    inventory_ids = [
        (record["path"], legacy_id["field"], legacy_id["value"])
        for record in inventory["artifacts"]
        for legacy_id in record["legacy_ids"]
    ]
    manifest_ids = [
        (migration.legacy_path, legacy_id.field, legacy_id.value)
        for migration in manifest.artifacts
        for legacy_id in migration.legacy_ids
    ]
    assert manifest_ids == inventory_ids
    assert len(manifest_ids) == 731


def test_classes_and_destination_layout_are_explicit_and_collision_free() -> None:
    manifest = _manifest()

    assert dict(manifest.class_counts) == {
        "source": 92,
        "golden": 9,
        "run": 119,
        "promoted": 9,
        "archive": 40,
    }
    prefixes = {
        ArtifactClass.SOURCE: "security_ir_artifacts/inputs/",
        ArtifactClass.GOLDEN: "security_ir_artifacts/golden/",
        ArtifactClass.RUN: "security_ir_artifacts/runs/legacy-import/",
        ArtifactClass.PROMOTED: "security_ir_artifacts/promoted/",
        ArtifactClass.ARCHIVE: "security_ir_artifacts/archive/",
    }
    for migration in manifest.artifacts:
        assert migration.target_path.startswith(prefixes[migration.artifact_class])

    assert len(manifest.forward_mapping()) == manifest.artifact_count
    assert len(manifest.reverse_mapping()) == manifest.artifact_count
    assert set(manifest.forward_mapping().values()) == set(
        manifest.reverse_mapping()
    )


def test_transient_unknown_environment_and_ambiguous_records_are_archived() -> None:
    contents = {
        "transient": b"temporary",
        "unknown": b"opaque",
        "environment": b"host observation",
        "ambiguous": b"candidate",
    }
    records = [
        _inventory_record(
            "security_ir_artifacts/compiler/output.aux",
            contents["transient"],
            "transient compiler output",
            is_temporary=True,
        ),
        _inventory_record(
            "security_ir_artifacts/mystery.bin",
            contents["unknown"],
            "unknown",
        ),
        _inventory_record(
            "security_ir_artifacts/environment/host.json",
            contents["environment"],
            "environment record",
        ),
        _inventory_record(
            "security_ir_artifacts/report-new.json",
            contents["ambiguous"],
            "ambiguous",
            is_new_variant=True,
            ambiguity_reasons=["filename does not establish authority"],
            variant_of="security_ir_artifacts/report.json",
        ),
    ]
    manifest = build_migration_manifest(_fixture_inventory(records))
    by_path = {item.legacy_path: item for item in manifest.artifacts}

    transient = by_path["security_ir_artifacts/compiler/output.aux"]
    assert transient.artifact_class is ArtifactClass.ARCHIVE
    assert MigrationFlag.TRANSIENT in transient.flags

    unknown = by_path["security_ir_artifacts/mystery.bin"]
    assert unknown.artifact_class is ArtifactClass.ARCHIVE
    assert MigrationFlag.UNKNOWN in unknown.flags

    environment = by_path["security_ir_artifacts/environment/host.json"]
    assert environment.artifact_class is ArtifactClass.ARCHIVE
    assert MigrationFlag.OBSERVATIONAL in environment.flags

    ambiguous = by_path["security_ir_artifacts/report-new.json"]
    assert ambiguous.artifact_class is ArtifactClass.ARCHIVE
    assert MigrationFlag.AMBIGUOUS in ambiguous.flags
    assert MigrationFlag.NEW_VARIANT in ambiguous.flags
    assert ambiguous.authority_selected is False


def test_filename_variants_remain_distinct_without_authority_selection() -> None:
    manifest = _manifest()
    paths = {
        item.legacy_path: item for item in manifest.artifacts
    }
    variant_pairs = (
        (
            "security_ir_artifacts/corpora/xaman-app/native-boundary-coverage-new.json",
            "security_ir_artifacts/corpora/xaman-app/native-boundary-coverage.json",
        ),
        (
            "security_ir_artifacts/corpora/xaman-app/public-source-assessment-new.json",
            "security_ir_artifacts/corpora/xaman-app/public-source-assessment.json",
        ),
        (
            "security_ir_artifacts/corpora/xaman-app/source-claim-map-new.json",
            "security_ir_artifacts/corpora/xaman-app/source-claim-map.json",
        ),
    )
    for variant_path, base_path in variant_pairs:
        variant = paths[variant_path]
        base = paths[base_path]
        assert variant.variant_of == base_path
        assert variant.target_path != base.target_path
        assert variant.artifact_class is ArtifactClass.ARCHIVE
        assert MigrationFlag.AMBIGUOUS in variant.flags
        assert not variant.authority_selected
        assert not base.authority_selected


def test_manifest_is_deterministic_idempotent_and_observations_are_separate(
    tmp_path: Path,
) -> None:
    inventory = _inventory()
    kwargs = {
        "inventory_content_sha256": hashlib.sha256(
            INVENTORY_PATH.read_bytes()
        ).hexdigest(),
        "repository_revision": "commit:test",
        "deterministic_metadata": {"migration_task_id": "IRF-025"},
    }
    forward = build_migration_manifest(inventory, **kwargs)
    reverse_input = dict(inventory)
    reverse_input["artifacts"] = list(reversed(inventory["artifacts"]))
    reverse_input["inventory_sha256"] = hashlib.sha256(
        json.dumps(
            reverse_input["artifacts"],
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    reverse = build_migration_manifest(reverse_input, **kwargs)

    # Inventory order is not semantically relevant; mappings sort by legacy path.
    assert forward.artifacts == reverse.artifacts
    assert forward.manifest_id != reverse.manifest_id
    # The inventory hash is itself preserved, so two source inventories remain
    # distinguishable even when their normalized migration maps are identical.
    repeated = build_migration_manifest(inventory, **kwargs)
    assert repeated == forward
    assert repeated.deterministic_bytes() == forward.deterministic_bytes()

    observed = forward.with_observations(
        MigrationObservations(
            generated_at="2099-01-01T00:00:00Z",
            environment={"hostname": "different-runner"},
            metadata={"duration_ms": 123},
        )
    )
    assert observed.manifest_id == forward.manifest_id
    assert observed.deterministic_bytes() == forward.deterministic_bytes()
    assert observed.to_json() != forward.to_json()

    output = tmp_path / "manifest.json"
    assert write_migration_manifest(forward, output) is True
    before = output.read_bytes()
    assert write_migration_manifest(forward, output) is False
    assert output.read_bytes() == before
    with pytest.raises(
        ArtifactMigrationValidationError, match="refusing to overwrite"
    ):
        write_migration_manifest(observed, output)

    record = forward.artifacts[0]
    for mapped_path in (record.legacy_path, record.target_path):
        with pytest.raises(
            ArtifactMigrationValidationError, match="mapped artifact path"
        ):
            write_migration_manifest(forward, tmp_path / mapped_path)


def test_mapping_is_exactly_reversible_and_round_trips_json() -> None:
    manifest = _manifest()
    restored = SecurityArtifactMigration.from_json(
        manifest.to_json(pretty=True)
    )

    assert restored == manifest
    assert restored.manifest_id == manifest.manifest_id
    for legacy_path, target_path in manifest.forward_mapping().items():
        assert manifest.target_for(legacy_path) == target_path
        assert manifest.legacy_for(target_path) == legacy_path


def test_integrity_receipt_covers_all_legacy_bytes_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    root = tmp_path / "security_ir_artifacts"
    root.mkdir()
    content = b'{"model_id":"legacy"}\n'
    artifact = root / "source.json"
    artifact.write_bytes(content)
    record = _inventory_record(
        "security_ir_artifacts/source.json",
        content,
        "source",
        legacy_ids=[{"field": "model_id", "value": "legacy"}],
    )
    fixture_inventory = _fixture_inventory([record])
    inventory_file = tmp_path / "inventory.json"
    inventory_file.write_text(
        json.dumps(
            fixture_inventory, ensure_ascii=True, indent=2, sort_keys=True
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = build_migration_manifest(
        fixture_inventory, inventory_path="inventory.json"
    )

    report = manifest.verify_integrity(
        tmp_path, reject_unmapped=True, verify_inventory=True
    )
    assert report.valid
    assert report.checked_legacy_paths == (
        "security_ir_artifacts/source.json",
    )
    assert report.manifest_id == manifest.manifest_id

    inventory_file.write_text("{}\n", encoding="utf-8")
    inventory_changed = manifest.audit_integrity(
        tmp_path, verify_inventory=True
    )
    assert MigrationIssueKind.CHANGED in {
        issue.kind for issue in inventory_changed.issues
    }

    artifact.write_bytes(b"changed")
    report = manifest.audit_integrity(tmp_path)
    assert not report.valid
    assert MigrationIssueKind.CHANGED in {
        issue.kind for issue in report.issues
    }
    with pytest.raises(ArtifactMigrationIntegrityError) as captured:
        manifest.verify_integrity(tmp_path)
    assert captured.value.report == report

    artifact.unlink()
    missing = manifest.audit_integrity(tmp_path)
    assert MigrationIssueKind.MISSING in {
        issue.kind for issue in missing.issues
    }


def test_symbolic_link_identity_is_preserved_without_following_it(
    tmp_path: Path,
) -> None:
    root = tmp_path / "security_ir_artifacts"
    root.mkdir()
    link = root / "legacy-link.json"
    link.symlink_to("outside.json")
    link_bytes = b"outside.json"
    record = _inventory_record(
        "security_ir_artifacts/legacy-link.json",
        link_bytes,
        "unknown",
        file_type="symbolic-link",
    )
    manifest = build_migration_manifest(_fixture_inventory([record]))

    assert manifest.verify_integrity(tmp_path).valid
    assert manifest.artifacts[0].legacy_file_type == "symbolic-link"

    link.unlink()
    link.write_bytes(link_bytes)
    report = manifest.audit_integrity(tmp_path)
    assert not report.valid
    assert MigrationIssueKind.CHANGED in {
        issue.kind for issue in report.issues
    }


def test_checked_in_integrity_receipt_is_complete_and_manifest_is_not_legacy() -> None:
    manifest = _manifest()
    report = manifest.verify_integrity(
        REPO_ROOT, reject_unmapped=True, verify_inventory=True
    )

    assert report.valid
    assert len(report.checked_legacy_paths) == 269
    assert (
        "security_ir_artifacts/migrations/manifest.json"
        not in report.checked_legacy_paths
    )


def test_migration_metadata_cannot_reenter_the_legacy_inventory(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "security_ir_artifacts"
    migrations = artifact_root / "migrations"
    migrations.mkdir(parents=True)
    (artifact_root / "source.json").write_text("{}", encoding="utf-8")
    (migrations / "manifest.json").write_text("{}", encoding="utf-8")

    paths = inventory_artifacts.filesystem_artifact_paths(tmp_path)

    assert [path.as_posix() for path in paths] == [
        "security_ir_artifacts/source.json"
    ]


def test_manifest_rejects_inventory_or_identity_tampering_and_field_leakage() -> None:
    inventory = _inventory()
    inventory["artifacts"][0]["sha256"] = "0" * 64
    with pytest.raises(
        ArtifactMigrationValidationError, match="inventory_sha256"
    ):
        build_migration_manifest(inventory)

    payload = _manifest().to_dict()
    payload["manifest_id"] = "bafkreibad"
    with pytest.raises(
        ArtifactMigrationValidationError, match="manifest_id"
    ):
        SecurityArtifactMigration.from_dict(payload)

    manifest = _manifest()
    with pytest.raises(
        ArtifactMigrationValidationError, match="observational"
    ):
        replace(
            manifest,
            deterministic_metadata={"environment": {"hostname": "leak"}},
            manifest_id="",
        )
