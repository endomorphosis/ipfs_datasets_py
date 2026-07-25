"""Contract tests for the domain-neutral schema and migration registry."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

import pytest

from ipfs_datasets_py.logic.ir_core.schema_registry import (
    IR_MIGRATION_RECEIPT_SCHEMA_ID,
    IR_SCHEMA_REGISTRY_PROTOCOL_ID,
    CompatibilityDeclaration,
    CompatibilityKind,
    IRSchemaRegistry,
    IncompatibleSchemaError,
    LossEntry,
    LossReport,
    Migration,
    MigrationCycleError,
    MigrationExecutionError,
    ReceiptVerificationError,
    SchemaDeclaration,
    SchemaRegistryError,
    UnknownSchemaError,
    canonical_digest,
)


V1 = "example.intent/v1"
V2 = "example.intent/v2"
V2_READER = "example.intent/v2-reader"
V3 = "example.intent/v3"
V4 = "example.intent/v4"


def _upgrade_v1_v2(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    result = dict(payload)
    result["schema_id"] = V2
    result["tags"] = []
    return result


def _upgrade_v2_v3(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    result = dict(payload)
    result["schema_id"] = V3
    result["name"] = result.pop("title")
    return result


def _drop_tags_v3_v4(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    result = dict(payload)
    result["schema_id"] = V4
    result.pop("tags", None)
    return result


def _schemas() -> tuple[SchemaDeclaration, ...]:
    return (
        SchemaDeclaration(V1),
        SchemaDeclaration(V2),
        SchemaDeclaration(
            V2_READER,
            compatibility=(CompatibilityDeclaration(V2),),
        ),
        SchemaDeclaration(V3),
        SchemaDeclaration(V4),
    )


def _migrations() -> tuple[Migration, ...]:
    return (
        Migration(
            "example.intent.v1-to-v2",
            V1,
            V2,
            _upgrade_v1_v2,
            LossReport.lossless(),
        ),
        Migration(
            "example.intent.v2-to-v3",
            V2,
            V3,
            _upgrade_v2_v3,
            LossReport.lossless(),
        ),
        Migration(
            "example.intent.v3-to-v4",
            V3,
            V4,
            _drop_tags_v3_v4,
            LossReport(
                (
                    LossEntry(
                        "example.intent.tags-dropped",
                        "v4 no longer represents free-form tags.",
                        ("tags",),
                    ),
                )
            ),
        ),
    )


def _registry() -> IRSchemaRegistry:
    return IRSchemaRegistry(_schemas(), _migrations())


def test_exact_schema_ids_and_compatibility_are_explicit() -> None:
    registry = _registry()

    exact = registry.negotiate(V2, V2)
    declared = registry.negotiate(V2, V2_READER)
    migration = registry.negotiate(V1, V3)
    incompatible = registry.negotiate(V4, V1)

    assert registry.protocol_id == IR_SCHEMA_REGISTRY_PROTOCOL_ID
    assert exact.kind is CompatibilityKind.EXACT
    assert declared.kind is CompatibilityKind.DECLARED
    assert migration.kind is CompatibilityKind.MIGRATION_REQUIRED
    assert migration.migration_ids == (
        "example.intent.v1-to-v2",
        "example.intent.v2-to-v3",
    )
    assert migration.schema_path == (V1, V2, V3)
    assert incompatible.kind is CompatibilityKind.INCOMPATIBLE
    assert not incompatible.compatible


@pytest.mark.parametrize(
    "unknown",
    (
        "example.intent/v999",
        "example.intent/v*",
        "example.intent/>=v2",
    ),
)
def test_unknown_versions_and_non_exact_identifiers_are_rejected(
    unknown: str,
) -> None:
    registry = _registry()

    with pytest.raises((UnknownSchemaError, SchemaRegistryError)):
        registry.require_schema(unknown)
    with pytest.raises((UnknownSchemaError, SchemaRegistryError)):
        registry.negotiate(V1, unknown)


def test_compatibility_declarations_must_reference_registered_exact_ids() -> None:
    with pytest.raises(UnknownSchemaError, match="unknown compatible source"):
        IRSchemaRegistry(
            (
                SchemaDeclaration(V1),
                SchemaDeclaration(
                    V2,
                    compatibility=(
                        CompatibilityDeclaration("example.intent/v999"),
                    ),
                ),
            )
        )


def test_migration_path_is_shortest_and_lexically_deterministic() -> None:
    direct = Migration(
        "z-direct",
        V1,
        V4,
        lambda payload: {**payload, "schema_id": V4},
        LossReport.lossless(),
    )
    registry = IRSchemaRegistry(_schemas(), (*_migrations(), direct))

    assert tuple(item.migration_id for item in registry.migration_path(V1, V4)) == (
        "z-direct",
    )

    # Both paths have two edges.  Sorted destinations make the V2 path win
    # regardless of caller registration order.
    left = "example.intent/v2-left"
    right = "example.intent/v2-right"
    schemas = (
        SchemaDeclaration(V1),
        SchemaDeclaration(left),
        SchemaDeclaration(right),
        SchemaDeclaration(V4),
    )

    def edge(mid: str, source: str, destination: str) -> Migration:
        return Migration(
            mid,
            source,
            destination,
            lambda payload, destination=destination: {
                **payload,
                "schema_id": destination,
            },
            LossReport.lossless(),
        )

    edges = (
        edge("right-in", V1, right),
        edge("right-out", right, V4),
        edge("left-in", V1, left),
        edge("left-out", left, V4),
    )
    tie_registry = IRSchemaRegistry(schemas, edges)
    assert tuple(
        item.migration_id for item in tie_registry.migration_path(V1, V4)
    ) == ("left-in", "left-out")


def test_cycles_and_duplicate_edges_are_rejected_at_construction() -> None:
    reverse = Migration(
        "example.intent.v3-to-v1",
        V3,
        V1,
        lambda payload: {**payload, "schema_id": V1},
        LossReport.lossless(),
    )
    with pytest.raises(MigrationCycleError, match=f"{V1} -> {V2} -> {V3} -> {V1}"):
        IRSchemaRegistry(_schemas(), (*_migrations(), reverse))

    duplicate_edge = Migration(
        "another-v1-to-v2",
        V1,
        V2,
        _upgrade_v1_v2,
        LossReport.lossless(),
    )
    with pytest.raises(SchemaRegistryError, match="only one migration"):
        IRSchemaRegistry(_schemas(), (*_migrations(), duplicate_edge))


def test_migration_emits_loss_reports_and_digest_bound_receipt() -> None:
    registry = _registry()
    source = {"schema_id": V1, "title": "Ship safely"}

    result = registry.migrate(source, V1, V4)
    migrated = dict(result.payload)
    receipt = result.receipt

    assert migrated == {"schema_id": V4, "name": "Ship safely"}
    assert receipt.schema_id == IR_MIGRATION_RECEIPT_SCHEMA_ID
    assert receipt.registry_protocol_id == IR_SCHEMA_REGISTRY_PROTOCOL_ID
    assert receipt.source_schema_id == V1
    assert receipt.destination_schema_id == V4
    assert receipt.source_digest == canonical_digest(source)
    assert receipt.destination_digest == canonical_digest(migrated)
    assert not receipt.is_lossless
    assert receipt.steps[0].loss_report.is_lossless
    assert receipt.steps[-1].loss_report.entries[0].field_paths == ("tags",)
    assert receipt.steps[0].source_digest == receipt.source_digest
    assert all(
        left.destination_digest == right.source_digest
        for left, right in zip(receipt.steps, receipt.steps[1:])
    )
    assert receipt.steps[-1].destination_digest == receipt.destination_digest
    assert receipt.receipt_digest == result.receipt.receipt_digest
    registry.verify_receipt(receipt, source, migrated)

    repeated = registry.migrate(source, V1, V4)
    assert repeated.receipt.to_dict() == receipt.to_dict()
    assert repeated.receipt.receipt_digest == receipt.receipt_digest


def test_receipt_verification_detects_source_destination_and_path_tampering() -> None:
    registry = _registry()
    source = {"schema_id": V1, "title": "Ship safely"}
    result = registry.migrate(source, V1, V3)

    with pytest.raises(ReceiptVerificationError, match="source digest"):
        registry.verify_receipt(
            result.receipt,
            {**source, "title": "tampered"},
            result.payload,
        )
    with pytest.raises(ReceiptVerificationError, match="destination digest"):
        registry.verify_receipt(
            result.receipt,
            source,
            {**dict(result.payload), "name": "tampered"},
        )
    with pytest.raises(ReceiptVerificationError, match="path mismatch"):
        registry.verify_receipt(
            replace(result.receipt, steps=tuple(reversed(result.receipt.steps))),
            source,
            result.payload,
        )

    forged_digest = "sha256:" + ("0" * 64)
    forged_steps = (
        replace(result.receipt.steps[0], destination_digest=forged_digest),
        replace(result.receipt.steps[1], source_digest=forged_digest),
    )
    with pytest.raises(ReceiptVerificationError, match="re-execution"):
        registry.verify_receipt(
            replace(result.receipt, steps=forged_steps),
            source,
            result.payload,
        )


def test_transforms_receive_immutable_input_and_must_emit_exact_target_schema() -> None:
    def mutating_transform(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        payload["schema_id"] = V2  # type: ignore[index]
        return payload

    registry = IRSchemaRegistry(
        (SchemaDeclaration(V1), SchemaDeclaration(V2)),
        (
            Migration(
                "mutating",
                V1,
                V2,
                mutating_transform,
                LossReport.lossless(),
            ),
        ),
    )
    source = {"schema_id": V1, "nested": {"items": [1]}}
    with pytest.raises(MigrationExecutionError, match="failed"):
        registry.migrate(source, V1, V2)
    assert source == {"schema_id": V1, "nested": {"items": [1]}}

    wrong_schema = IRSchemaRegistry(
        (SchemaDeclaration(V1), SchemaDeclaration(V2)),
        (
            Migration(
                "wrong-target",
                V1,
                V2,
                lambda payload: dict(payload),
                LossReport.lossless(),
            ),
        ),
    )
    with pytest.raises(MigrationExecutionError, match="must equal exact schema ID"):
        wrong_schema.migrate(source, V1, V2)


def test_manifest_is_stable_and_contains_compatibility_and_loss_declarations() -> None:
    first = _registry().manifest()
    second = IRSchemaRegistry(
        tuple(reversed(_schemas())), tuple(reversed(_migrations()))
    ).manifest()

    assert first == second
    assert canonical_digest(first) == canonical_digest(second)
    assert first["protocol_id"] == IR_SCHEMA_REGISTRY_PROTOCOL_ID
    compatible = next(
        schema for schema in first["schemas"] if schema["schema_id"] == V2_READER
    )
    assert compatible["compatibility"] == [{"source_schema_id": V2}]
    lossy = next(
        migration
        for migration in first["migrations"]
        if migration["migration_id"] == "example.intent.v3-to-v4"
    )
    assert not lossy["loss_report"]["is_lossless"]


def test_unreachable_migration_is_rejected() -> None:
    registry = _registry()
    with pytest.raises(IncompatibleSchemaError, match="no migration path"):
        registry.migration_path(V4, V1)
