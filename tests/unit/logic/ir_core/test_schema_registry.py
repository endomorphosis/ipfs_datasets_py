"""Contract tests for the domain-neutral IR schema registry."""

from __future__ import annotations

from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.ir_core.schema_registry import (
    CompatibilityDeclaration,
    CompatibilityKind,
    DuplicateMigrationError,
    DuplicateSchemaError,
    IR_SCHEMA_REGISTRY_PROTOCOL_ID,
    IRSchemaRegistry,
    MigrationCycleError,
    MigrationExecutionError,
    MigrationLoss,
    MigrationPathError,
    MigrationResult,
    ReceiptVerificationError,
    SchemaMigration,
    SchemaRegistration,
    SchemaValidationError,
    UnknownSchemaError,
    canonical_payload_digest,
    verify_migration_receipt,
)


V1 = "example.ir/document@1"
V2 = "example.ir/document@2"
V3 = "example.ir/document@3"
V4 = "example.ir/document@4"


def _schemas() -> tuple[SchemaRegistration, ...]:
    return tuple(SchemaRegistration(schema_id) for schema_id in (V1, V2, V3, V4))


def _v1_to_v2(payload):
    migrated = dict(payload)
    migrated["items"] = [migrated.pop("item")]
    return migrated


def _v2_to_v3(payload):
    migrated = dict(payload)
    migrated["entries"] = migrated.pop("items")
    return migrated


def _registry() -> IRSchemaRegistry:
    return IRSchemaRegistry(
        schemas=_schemas(),
        migrations=(
            SchemaMigration("example-v1-v2", V1, V2, _v1_to_v2),
            SchemaMigration("example-v2-v3", V2, V3, _v2_to_v3),
        ),
    )


def test_exact_schema_ids_and_compatibility_declarations_are_required() -> None:
    registry = IRSchemaRegistry(schemas=_schemas())

    assert registry.compatibility(V1, V1).kind is CompatibilityKind.EXACT
    assert registry.compatibility(V1, V2).kind is CompatibilityKind.INCOMPATIBLE

    declaration = registry.declare_compatibility(
        CompatibilityDeclaration(V1, V2, "The v2 reader accepts v1 unchanged.")
    )
    result = registry.compatibility(V1, V2)
    assert declaration.source_schema_id == V1
    assert result.kind is CompatibilityKind.DECLARED
    assert result.compatible

    # Similar-looking IDs are not guessed or coerced.
    with pytest.raises(UnknownSchemaError):
        registry.compatibility("example.ir/document@1.0", V2)
    with pytest.raises(ValueError):
        registry.register_schema(" example.ir/document@5")


def test_unknown_versions_duplicates_and_missing_payload_ids_are_rejected() -> None:
    registry = IRSchemaRegistry(schemas=_schemas())

    with pytest.raises(DuplicateSchemaError):
        registry.register_schema(V1)
    with pytest.raises(UnknownSchemaError):
        registry.declare_compatibility(
            source_schema_id="example.ir/document@999",
            destination_schema_id=V2,
        )
    with pytest.raises(UnknownSchemaError):
        registry.register_migration(
            migration_id="unknown-v2",
            source_schema_id="example.ir/document@999",
            destination_schema_id=V2,
            transform=dict,
        )
    with pytest.raises(SchemaValidationError):
        registry.migrate({"item": "alpha"}, V2)
    with pytest.raises(UnknownSchemaError):
        registry.migrate({"schema_id": "example.ir/document@999"}, V2)


def test_migration_paths_are_shortest_and_deterministically_tie_broken() -> None:
    registry = IRSchemaRegistry(schemas=_schemas())
    # Register the lexically later path first to prove insertion order is irrelevant.
    registry.register_migration(
        SchemaMigration("via-v3-first", V1, V3, lambda payload: dict(payload))
    )
    registry.register_migration(
        SchemaMigration("v3-v4", V3, V4, lambda payload: dict(payload))
    )
    registry.register_migration(
        SchemaMigration("via-v2-second", V1, V2, lambda payload: dict(payload))
    )
    registry.register_migration(
        SchemaMigration("v2-v4", V2, V4, lambda payload: dict(payload))
    )

    path = registry.find_migration_path(V1, V4)
    assert tuple(step.migration_id for step in path) == (
        "via-v2-second",
        "v2-v4",
    )
    result = registry.compatibility(V1, V4)
    assert result.kind is CompatibilityKind.MIGRATION_REQUIRED
    assert result.migration_path == ("via-v2-second", "v2-v4")

    with pytest.raises(MigrationPathError):
        registry.find_migration_path(V4, V1)


def test_duplicate_edges_and_migration_cycles_are_rejected_atomically() -> None:
    registry = _registry()

    with pytest.raises(DuplicateMigrationError):
        registry.register_migration(
            SchemaMigration("another-v1-v2", V1, V2, lambda payload: dict(payload))
        )
    with pytest.raises(DuplicateMigrationError):
        registry.register_migration(
            SchemaMigration("example-v1-v2", V3, V4, lambda payload: dict(payload))
        )
    with pytest.raises(MigrationCycleError):
        registry.register_migration(
            SchemaMigration("example-v3-v1", V3, V1, lambda payload: dict(payload))
        )

    assert (V3, V1) not in registry.migrations
    assert tuple(step.migration_id for step in registry.find_migration_path(V1, V3)) == (
        "example-v1-v2",
        "example-v2-v3",
    )


def test_migration_reports_declared_and_runtime_losses() -> None:
    declared = MigrationLoss(
        "field-renamed",
        "The legacy item field was replaced.",
        ("item", "items"),
    )
    runtime = MigrationLoss(
        "precision-reduced",
        "Subsecond precision was removed.",
        ("timestamp",),
    )

    def migrate(payload):
        value = dict(payload)
        value["items"] = [value.pop("item")]
        value["timestamp"] = int(value["timestamp"])
        return MigrationResult(value, (runtime,))

    registry = IRSchemaRegistry(
        schemas=(V1, V2),
        migrations=(
            SchemaMigration(
                "lossy-v1-v2",
                V1,
                V2,
                migrate,
                declared_losses=(declared,),
            ),
        ),
    )
    outcome = registry.migrate(
        {"schema_id": V1, "item": "alpha", "timestamp": 1.25}, V2
    )

    assert outcome.payload["schema_id"] == V2
    assert outcome.receipt.loss_report.lossy
    assert tuple(loss.code for loss in outcome.receipt.loss_report.losses) == (
        "field-renamed",
        "precision-reduced",
    )
    assert outcome.receipt.steps[0].loss_report == outcome.receipt.loss_report


def test_receipt_binds_canonical_source_destination_and_registry() -> None:
    registry = _registry()
    source = {"schema_id": V1, "item": "alpha", "metadata": {"b": 2, "a": 1}}

    outcome = registry.migrate(source, V3)
    receipt = outcome.receipt

    assert receipt.protocol_id == IR_SCHEMA_REGISTRY_PROTOCOL_ID
    assert receipt.source_digest == canonical_payload_digest(source)
    assert receipt.destination_digest == canonical_payload_digest(outcome.payload)
    assert receipt.registry_digest == registry.registry_digest()
    assert receipt.schema_path == (V1, V2, V3)
    assert verify_migration_receipt(receipt, source, outcome.payload)
    assert receipt.steps[0].destination_digest == receipt.steps[1].source_digest

    with pytest.raises(ReceiptVerificationError):
        receipt.verify({**source, "item": "tampered"}, outcome.payload)
    with pytest.raises(ReceiptVerificationError):
        receipt.verify(source, {**outcome.payload, "entries": ["tampered"]})
    with pytest.raises(ReceiptVerificationError):
        replace(
            receipt,
            registry_digest="sha256:" + ("0" * 64),
        ).verify(source, outcome.payload)


def test_exact_noop_migration_has_a_bound_empty_path_receipt() -> None:
    registry = IRSchemaRegistry(schemas=(V1,))
    source = {"schema_id": V1, "item": "alpha"}

    outcome = registry.migrate(source, V1)

    assert dict(outcome.payload) == source
    assert outcome.receipt.schema_path == (V1,)
    assert outcome.receipt.steps == ()
    assert not outcome.receipt.loss_report.lossy
    assert outcome.receipt.source_digest == outcome.receipt.destination_digest
    assert outcome.receipt.verify(source, outcome.payload)


def test_nondeterministic_transforms_are_rejected() -> None:
    calls = 0

    def nondeterministic(payload):
        nonlocal calls
        calls += 1
        return {**payload, "call": calls}

    registry = IRSchemaRegistry(
        schemas=(V1, V2),
        migrations=(SchemaMigration("unstable", V1, V2, nondeterministic),),
    )

    with pytest.raises(MigrationExecutionError, match="nondeterministic"):
        registry.migrate({"schema_id": V1}, V2)


def test_source_is_not_mutated_and_destination_schema_is_validated() -> None:
    def v2_validator(payload):
        return payload.get("items") == ["alpha"]

    source = {"schema_id": V1, "item": "alpha", "nested": {"values": [1]}}
    registry = IRSchemaRegistry(
        schemas=(SchemaRegistration(V1), SchemaRegistration(V2, validator=v2_validator)),
        migrations=(SchemaMigration("v1-v2", V1, V2, _v1_to_v2),),
    )

    outcome = registry.migrate(source, V2)
    assert source == {
        "schema_id": V1,
        "item": "alpha",
        "nested": {"values": [1]},
    }
    assert outcome.payload["schema_id"] == V2
    with pytest.raises(TypeError):
        outcome.payload["new"] = "not mutable"

    rejecting_registry = IRSchemaRegistry(
        schemas=(SchemaRegistration(V1), SchemaRegistration(V2, validator=lambda _: False)),
        migrations=(SchemaMigration("v1-v2", V1, V2, _v1_to_v2),),
    )
    with pytest.raises(SchemaValidationError, match="failed validator"):
        rejecting_registry.migrate(source, V2)


def test_manifest_and_digest_do_not_depend_on_registration_order() -> None:
    first = IRSchemaRegistry(
        schemas=(V2, V1),
        migrations=(SchemaMigration("v1-v2", V1, V2, _v1_to_v2),),
    )
    second = IRSchemaRegistry(
        schemas=(V1, V2),
        migrations=(SchemaMigration("v1-v2", V1, V2, _v1_to_v2),),
    )

    assert first.manifest() == second.manifest()
    assert first.registry_digest() == second.registry_digest()
