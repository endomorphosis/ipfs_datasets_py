from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from ipfs_datasets_py.logic.ir_core.schema_registry import (
    CompatibilityDeclaration,
    CompatibilityStatus,
    DuplicateRegistrationError,
    IRSchemaRegistry,
    InvalidSchemaIDError,
    MigrationCycleError,
    MigrationExecutionError,
    MigrationLoss,
    MigrationOutcome,
    MigrationPathError,
    MigrationSpec,
    NondeterministicMigrationError,
    SchemaSpec,
    UnknownSchemaError,
    payload_digest,
)


V1 = "urn:example:widget/v1"
V2 = "urn:example:widget/v2"
V2_ALT = "urn:example:widget/v2-alt"
V3 = "urn:example:widget/v3"
OTHER = "urn:example:other/v1"


def _schemas(*schema_ids: str) -> tuple[SchemaSpec, ...]:
    return tuple(SchemaSpec(schema_id) for schema_id in schema_ids)


def _rename_name(payload):
    migrated = dict(payload)
    migrated["label"] = migrated.pop("name")
    return migrated


def _add_enabled(payload):
    migrated = dict(payload)
    migrated.setdefault("enabled", True)
    return migrated


def _registry() -> IRSchemaRegistry:
    return IRSchemaRegistry(
        schemas=_schemas(V1, V2, V3, OTHER),
        compatibility=(
            CompatibilityDeclaration(
                source_schema_id=V2,
                reader_schema_id=V3,
                compatible=True,
                rationale="v3 readers default the new optional field",
            ),
            CompatibilityDeclaration(
                source_schema_id=OTHER,
                reader_schema_id=V3,
                compatible=False,
                rationale="the schemas represent different domains",
            ),
        ),
        migrations=(
            MigrationSpec("widget-v1-v2", V1, V2, _rename_name),
            MigrationSpec("widget-v2-v3", V2, V3, _add_enabled),
        ),
    )


def test_schema_ids_are_opaque_exact_and_duplicates_are_rejected() -> None:
    registry = IRSchemaRegistry(_schemas(V1, V2))

    assert registry[V1].schema_id == V1
    with pytest.raises(UnknownSchemaError):
        registry[V1.upper()]
    with pytest.raises(InvalidSchemaIDError):
        SchemaSpec(f" {V1}")
    with pytest.raises(InvalidSchemaIDError):
        SchemaSpec("urn:example:bad id/v1")
    with pytest.raises(DuplicateRegistrationError):
        registry.register_schema(SchemaSpec(V1))


def test_unknown_schema_versions_fail_closed_in_every_public_operation() -> None:
    registry = _registry()

    with pytest.raises(UnknownSchemaError):
        registry.negotiate("urn:example:widget/v999", V3)
    with pytest.raises(UnknownSchemaError):
        registry.resolve_migration_path(V1, "urn:example:widget/v999")
    with pytest.raises(UnknownSchemaError):
        registry.migrate(
            {"name": "one"},
            source_schema_id="urn:example:widget/v999",
            destination_schema_id=V3,
        )


def test_compatibility_is_directional_explicit_and_not_inferred_from_names() -> None:
    registry = _registry()

    exact = registry.negotiate(V1, V1)
    assert exact.status is CompatibilityStatus.EXACT
    assert exact.compatible

    declared = registry.negotiate(V2, V3)
    assert declared.status is CompatibilityStatus.COMPATIBLE
    assert declared.declared

    denied = registry.negotiate(OTHER, V3)
    assert denied.status is CompatibilityStatus.INCOMPATIBLE
    assert denied.declared

    undeclared = registry.negotiate(V3, V2)
    assert undeclared.status is CompatibilityStatus.INCOMPATIBLE
    assert not undeclared.declared

    migratable = registry.negotiate(V1, V3)
    assert migratable.status is CompatibilityStatus.MIGRATION_REQUIRED
    assert migratable.schema_path == (V1, V2, V3)
    assert migratable.migration_ids == ("widget-v1-v2", "widget-v2-v3")


def test_incompatible_direct_read_can_still_require_an_explicit_migration() -> None:
    registry = IRSchemaRegistry(
        _schemas(V1, V2),
        compatibility=(
            CompatibilityDeclaration(
                V1,
                V2,
                compatible=False,
                rationale="v2 cannot directly decode the legacy name field",
            ),
        ),
        migrations=(MigrationSpec("v1-v2", V1, V2, _rename_name),),
    )

    decision = registry.negotiate(V1, V2)
    assert decision.status is CompatibilityStatus.MIGRATION_REQUIRED
    assert decision.declared
    assert decision.migration_ids == ("v1-v2",)


def test_migration_path_is_shortest_and_stable_across_registration_order() -> None:
    edges = (
        MigrationSpec("via-z-first", V1, V2_ALT, lambda value: dict(value)),
        MigrationSpec("via-a-first", V1, V2, lambda value: dict(value)),
        MigrationSpec("via-z-last", V2_ALT, V3, lambda value: dict(value)),
        MigrationSpec("via-a-last", V2, V3, lambda value: dict(value)),
    )
    first = IRSchemaRegistry(_schemas(V1, V2, V2_ALT, V3), migrations=edges)
    second = IRSchemaRegistry(
        _schemas(V3, V2_ALT, V2, V1), migrations=tuple(reversed(edges))
    )

    first_path = first.resolve_migration_path(V1, V3)
    second_path = second.resolve_migration_path(V1, V3)
    assert tuple(item.migration_id for item in first_path) == (
        "via-a-first",
        "via-a-last",
    )
    assert tuple(item.migration_id for item in first_path) == tuple(
        item.migration_id for item in second_path
    )

    direct = MigrationSpec("direct", V1, V3, lambda value: dict(value))
    first.register_migration(direct)
    assert tuple(
        item.migration_id for item in first.resolve_migration_path(V1, V3)
    ) == ("direct",)


def test_missing_path_and_migration_cycles_are_rejected_atomically() -> None:
    registry = IRSchemaRegistry(
        _schemas(V1, V2, V3),
        migrations=(
            MigrationSpec("v1-v2", V1, V2, lambda value: dict(value)),
            MigrationSpec("v2-v3", V2, V3, lambda value: dict(value)),
        ),
    )

    with pytest.raises(MigrationPathError):
        registry.resolve_migration_path(V3, V1)
    with pytest.raises(MigrationCycleError, match="cycle"):
        registry.register_migration(
            MigrationSpec("v3-v1", V3, V1, lambda value: dict(value))
        )
    assert (V3, V1) not in registry.migrations

    with pytest.raises(MigrationCycleError):
        MigrationSpec("self", V1, V1, lambda value: dict(value))


def test_migration_is_non_mutating_and_receipt_binds_both_payload_digests() -> None:
    registry = _registry()
    source = {"name": "one", "nested": {"values": [1, 2]}}
    original = {"name": "one", "nested": {"values": [1, 2]}}

    result = registry.migrate(
        source, source_schema_id=V1, destination_schema_id=V3
    )

    assert source == original
    assert result.payload == {
        "label": "one",
        "enabled": True,
        "nested": {"values": (1, 2)},
    }
    assert result.receipt.source_digest == payload_digest(source)
    assert result.receipt.destination_digest == payload_digest(result.payload)
    assert result.receipt.schema_path == (V1, V2, V3)
    assert result.receipt.migration_ids == ("widget-v1-v2", "widget-v2-v3")
    assert not result.receipt.loss_report.lossy
    assert result.receipt.verifies(source, result.payload)
    assert not result.receipt.verifies(
        {**source, "name": "tampered"}, result.payload
    )
    assert result.receipt.receipt_digest.startswith("sha256:")
    with pytest.raises(MigrationExecutionError, match="schema_id"):
        replace(result.receipt, schema_id="ir-core-migration-receipt/v999")
    with pytest.raises(TypeError):
        result.payload["label"] = "changed"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        result.receipt.source_digest = "sha256:" + "0" * 64  # type: ignore[misc]


def test_lossy_migration_requires_and_aggregates_structured_loss_reports() -> None:
    def discard_legacy(payload):
        migrated = dict(payload)
        migrated.pop("legacy_note", None)
        return MigrationOutcome(
            migrated,
            (
                MigrationLoss(
                    code="legacy-field-discarded",
                    field_path="legacy_note",
                    message="v2 cannot represent the legacy note",
                ),
            ),
        )

    registry = IRSchemaRegistry(
        _schemas(V1, V2),
        migrations=(
            MigrationSpec(
                "discard-note",
                V1,
                V2,
                discard_legacy,
                lossy=True,
            ),
        ),
    )
    result = registry.migrate(
        {"name": "one", "legacy_note": "old"},
        source_schema_id=V1,
        destination_schema_id=V2,
    )

    report = result.receipt.loss_report
    assert report.lossy
    assert report.losses[0].migration_id == "discard-note"
    assert report.to_dict()["losses"][0]["field_path"] == "legacy_note"
    assert result.receipt.to_dict()["loss_report"] == report.to_dict()


@pytest.mark.parametrize(
    "migration",
    [
        MigrationSpec(
            "declared-lossy-without-report",
            V1,
            V2,
            lambda value: dict(value),
            lossy=True,
        ),
        MigrationSpec(
            "declared-lossless-with-report",
            V1,
            V2,
            lambda value: MigrationOutcome(
                dict(value),
                (MigrationLoss("unexpected-loss", "something was lost"),),
            ),
            lossy=False,
        ),
    ],
)
def test_loss_declaration_must_match_transform_report(
    migration: MigrationSpec,
) -> None:
    registry = IRSchemaRegistry(_schemas(V1, V2), migrations=(migration,))

    with pytest.raises(MigrationExecutionError):
        registry.migrate(
            {"name": "one"},
            source_schema_id=V1,
            destination_schema_id=V2,
        )


def test_nondeterministic_transform_is_rejected() -> None:
    calls = iter((1, 2))

    def nondeterministic(payload):
        return {**payload, "sequence": next(calls)}

    registry = IRSchemaRegistry(
        _schemas(V1, V2),
        migrations=(
            MigrationSpec("unstable", V1, V2, nondeterministic),
        ),
    )

    with pytest.raises(NondeterministicMigrationError):
        registry.migrate(
            {"name": "one"},
            source_schema_id=V1,
            destination_schema_id=V2,
        )


def test_manifest_is_deterministic_and_excludes_transform_objects() -> None:
    registry = _registry()
    manifest = registry.manifest()

    assert manifest == registry.manifest()
    assert manifest["registry_digest"].startswith("sha256:")
    assert manifest["migrations"][0]["migration_id"] == "widget-v1-v2"
    assert "transform" not in manifest["migrations"][0]


def test_same_schema_migration_produces_a_zero_step_bound_receipt() -> None:
    registry = IRSchemaRegistry(_schemas(V1))
    source = {"name": "unchanged"}

    result = registry.migrate(
        source, source_schema_id=V1, destination_schema_id=V1
    )

    assert result.payload == source
    assert result.receipt.schema_path == (V1,)
    assert result.receipt.migration_ids == ()
    assert result.receipt.source_digest == result.receipt.destination_digest
