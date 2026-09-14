"""SPAR-011 inventory vectors for public compatibility obligations and consumers."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "0")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS", "0")
os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.logic.software_contracts.content import (  # noqa: E402
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.semantic_refactoring.compatibility import (  # noqa: E402
    CliPluginObligation,
    CompatibilityDisposition,
    CompatibilityKind,
    CompatibilityTerminal,
    CompatibilityTerminalKind,
    DecoratorObligation,
    FIRST_CLASS_OBLIGATION_KINDS,
    ImportEffect,
    IntrospectionObligation,
    KIND_FAMILY,
    PUBLIC_COMPATIBILITY_KINDS,
    PatchTargetObligation,
    PublicCompatibilityObligation,
    RegistryObligation,
    ResourceObligation,
    SerializationObligation,
    SupportStatus,
    family_for_kind,
)
from ipfs_datasets_py.semantic_refactoring.public_compatibility import (  # noqa: E402
    AUTHORITY,
    AUTHORITY_OWNER,
    DECLARED_CONSUMER_SURFACES,
    DISPOSITIONED,
    DUCKLAKE_IS_AUTHORITY,
    IDENTITY_EXCLUDED_FIELDS,
    INVENTORY_CAN_AUTHORIZE_COMPLETION,
    INVENTORY_CAN_AUTHORIZE_TRANSITION,
    INVENTORY_CAN_CREATE_AUTHORITY,
    INVENTORY_CAN_RETIRE_FACADE,
    KIND_SURFACE,
    MARKDOWN_IS_NOT_COMPLETION,
    MODEL_OUTPUT_IS_PROPOSAL_ONLY,
    PUBLIC_COMPATIBILITY_INVENTORY_INTERFACE,
    PUBLIC_COMPATIBILITY_INVENTORY_SCHEMA,
    TASK_ID,
    TEST_PASS_IS_NOT_COMPLETION,
    VECTOR_SIMILARITY_IS_AUTHORITY,
    WORKER_SELF_APPROVAL,
    CompatibilityConsumer,
    CompatibilityGraphEdge,
    CompatibilityInventoryError,
    ConsumerRole,
    ConsumerSurface,
    PublicCompatibilityInventory,
    SubjectFacadeRecord,
    inventory_public_compatibility,
    surface_for_kind,
    synthesize_consumers,
)


ROOT = Path(__file__).resolve().parents[4]
MODULE_PATH = (
    ROOT
    / "ipfs_datasets_py"
    / "ipfs_datasets_py"
    / "semantic_refactoring"
    / "public_compatibility.py"
)
TEST_PATH = Path(__file__).resolve()
INVENTORY = (
    ROOT
    / "docs"
    / "architecture"
    / "semantic_preserving_autonomous_remodularization_inventory"
)
WRITE_SCOPE = (
    "ipfs_datasets_py/ipfs_datasets_py/semantic_refactoring/public_compatibility.py",
    "ipfs_datasets_py/tests/unit/semantic_refactoring/test_public_compatibility.py",
)
PROTECTED_PATHS = (
    ".gitignore",
    "benchmarks/agent_supervisor/semantic_refactoring/preregistration.json",
    "config/agent_supervisor_semantic_preserving_remodularization_scheduler.json",
    "config/semantic_preserving_autonomous_remodularization_dependencies.seal.json",
    "docs/architecture/SEMANTIC_PRESERVING_AUTONOMOUS_REMODULARIZATION_PLAN.md",
    "docs/architecture/semantic_preserving_autonomous_remodularization.objectives.md",
    "docs/architecture/semantic_preserving_autonomous_remodularization.todo.md",
    "docs/architecture/semantic_preserving_autonomous_remodularization_inventory/authority_matrix.json",
    "docs/architecture/semantic_preserving_autonomous_remodularization_inventory/benchmark_preregistration.json",
    "docs/architecture/semantic_preserving_autonomous_remodularization_inventory/dynamic_python_risk_inventory.json",
    "docs/architecture/semantic_preserving_autonomous_remodularization_inventory/identity_inventory.json",
    "docs/architecture/semantic_preserving_autonomous_remodularization_inventory/interface_inventory.json",
    "docs/architecture/semantic_preserving_autonomous_remodularization_inventory/overlap_gap_matrix.json",
    "docs/architecture/semantic_preserving_autonomous_remodularization_inventory/repository_baseline.json",
    "docs/architecture/semantic_preserving_autonomous_remodularization_inventory/rollout_baseline.json",
    "scripts/materialize_semantic_preserving_remodularization_program.py",
    "scripts/ops/agent_supervisor/semantic_preserving_remodularization.py",
    "scripts/validate_semantic_preserving_remodularization_board.py",
    "scripts/validate_semantic_preserving_remodularization_dependencies.py",
    "test/api/semantic_refactoring/test_bootstrap_controls.py",
)
CAPSULE_TYPES = (
    "FunctionSemanticCapsule",
    "MethodSemanticCapsule",
    "ClassSemanticCapsule",
    "TopLevelBlockCapsule",
    "ModuleSemanticCapsule",
    "PackageSemanticCapsule",
    "CallsiteSemanticCapsule",
    "StateOwnerCapsule",
    "RegistrationCapsule",
    "ResourceLifecycleCapsule",
)
TREE_ID = "fbc6fa1ddefb2f9ecb7b5c718d618e3b60aa3051"
TASK_SURFACES = {
    "import",
    "api",
    "binding",
    "serialization",
    "introspection",
    "cli",
    "plugin",
    "registration",
    "documentation",
    "patch",
}


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _import_effect(**overrides: Any) -> ImportEffect:
    fields = {
        "module_name": "pkg.deps",
        "imported_names": ("loads",),
        "eagerness": "eager",
        "order_index": 0,
        "relative": False,
        "side_effects": ("import",),
    }
    fields.update(overrides)
    return ImportEffect(**fields)


def _registry(**overrides: Any) -> RegistryObligation:
    fields = {
        "registry_id": "pkg.commands",
        "key": "build",
        "value_binding": "pkg.cli.build",
        "order_index": 0,
    }
    fields.update(overrides)
    return RegistryObligation(**fields)


def _decorator(**overrides: Any) -> DecoratorObligation:
    fields = {
        "decorator_name": "click.command",
        "target_qualname": "pkg.cli.build",
        "order_index": 0,
        "side_effects": ("decorator", "cli_registration"),
    }
    fields.update(overrides)
    return DecoratorObligation(**fields)


def _resource(**overrides: Any) -> ResourceObligation:
    fields = {
        "resource_id": "pkg.connection",
        "phase": "acquire",
        "owner_id": "pkg.mod",
        "lifetime": "import_module",
        "order_index": 0,
    }
    fields.update(overrides)
    return ResourceObligation(**fields)


def _serialization(**overrides: Any) -> SerializationObligation:
    fields = {
        "format": "pickle",
        "type_qualname": "pkg.mod.Record",
        "protocol": "__reduce__",
    }
    fields.update(overrides)
    return SerializationObligation(**fields)


def _introspection(**overrides: Any) -> IntrospectionObligation:
    fields = {
        "surface": "qualname",
        "expected_value": "pkg.mod.Record",
    }
    fields.update(overrides)
    return IntrospectionObligation(**fields)


def _cli_plugin(**overrides: Any) -> CliPluginObligation:
    fields = {
        "channel": "cli",
        "group": "console_scripts",
        "name": "pkg-build",
        "target_qualname": "pkg.cli:main",
    }
    fields.update(overrides)
    return CliPluginObligation(**fields)


def _patch_target(**overrides: Any) -> PatchTargetObligation:
    fields = {
        "dotted_path": "pkg.mod.Record.save",
        "consumer_id": "tests.unit.test_record",
    }
    fields.update(overrides)
    return PatchTargetObligation(**fields)


def _payload_for_kind(kind: CompatibilityKind) -> dict[str, Any]:
    family = family_for_kind(kind)
    return {
        "import": {"import_effect": _import_effect()},
        "registry": {"registry": _registry()},
        "decorator": {"decorator": _decorator()},
        "resource": {"resource": _resource()},
        "serialization": {"serialization": _serialization()},
        "introspection": {"introspection": _introspection()},
        "cli_plugin": {"cli_plugin": _cli_plugin()},
        "patch_target": {"patch_target": _patch_target()},
    }[family.value]


def _obligation(
    kind: CompatibilityKind = CompatibilityKind.PATCH_TARGET,
    **overrides: Any,
) -> PublicCompatibilityObligation:
    fields = {
        "obligation_id": f"obl:{kind.value}:record",
        "kind": kind,
        "subject_id": "symbol:pkg.mod.Record",
        "subject_module": "pkg.mod",
        "subject_qualname": "pkg.mod.Record",
        "required": True,
        "support_status": SupportStatus.SUPPORTED,
        "disposition": CompatibilityDisposition.PRESERVE,
        "consumer_id": "pkg.cli",
    }
    fields.update(_payload_for_kind(CompatibilityKind(fields["kind"])))
    fields.update(overrides)
    return PublicCompatibilityObligation(**fields)


def _inventory(
    obligations: tuple[PublicCompatibilityObligation, ...] | None = None,
    **overrides: Any,
) -> PublicCompatibilityInventory:
    if obligations is None:
        obligations = tuple(_obligation(kind) for kind in CompatibilityKind)
    fields = {
        "tree_id": TREE_ID,
        "source_cid": _cid("source"),
        "obligations": obligations,
    }
    fields.update(overrides)
    if "consumers" not in fields:
        return inventory_public_compatibility(**fields)
    return PublicCompatibilityInventory(**fields)


def test_owned_paths_and_task_identity_are_exact() -> None:
    assert TASK_ID == "SPAR-011"
    assert PUBLIC_COMPATIBILITY_INVENTORY_INTERFACE == "PublicCompatibilityInventory@1"
    assert PUBLIC_COMPATIBILITY_INVENTORY_SCHEMA.endswith("@1")
    assert MODULE_PATH.is_file()
    assert TEST_PATH.is_file()
    for relative in WRITE_SCOPE:
        assert (ROOT / relative).is_file()


def test_authority_flags_cannot_self_authorize() -> None:
    assert AUTHORITY == "formal semantic authority"
    assert AUTHORITY_OWNER == "ipfs_datasets_py"
    assert INVENTORY_CAN_AUTHORIZE_COMPLETION is False
    assert INVENTORY_CAN_AUTHORIZE_TRANSITION is False
    assert INVENTORY_CAN_CREATE_AUTHORITY is False
    assert INVENTORY_CAN_RETIRE_FACADE is False
    assert VECTOR_SIMILARITY_IS_AUTHORITY is False
    assert MODEL_OUTPUT_IS_PROPOSAL_ONLY is True
    assert TEST_PASS_IS_NOT_COMPLETION is True
    assert MARKDOWN_IS_NOT_COMPLETION is True
    assert WORKER_SELF_APPROVAL is False
    assert DUCKLAKE_IS_AUTHORITY is False


def test_closed_vocabularies_cover_plan_surfaces() -> None:
    assert PUBLIC_COMPATIBILITY_KINDS == {kind.value for kind in CompatibilityKind}
    assert set(KIND_FAMILY) == set(CompatibilityKind)
    assert set(KIND_SURFACE) == set(CompatibilityKind)
    assert DECLARED_CONSUMER_SURFACES == TASK_SURFACES
    assert {surface.value for surface in KIND_SURFACE.values()} == TASK_SURFACES
    assert FIRST_CLASS_OBLIGATION_KINDS <= PUBLIC_COMPATIBILITY_KINDS
    assert DISPOSITIONED == {
        "preserve",
        "migrate",
        "facade",
        "explicit_incompatibility",
        "unsupported",
    }


def test_module_defines_predicted_symbols_not_capsule_family() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    assert "PublicCompatibilityInventory" in names
    assert "CompatibilityConsumer" in names
    assert "CompatibilityGraphEdge" in names
    assert "SubjectFacadeRecord" in names
    for capsule in CAPSULE_TYPES:
        assert capsule not in names
    assert "InitializationBlock" not in names
    assert "PublicCompatibilityObligation" not in names


@pytest.mark.parametrize("kind", list(CompatibilityKind))
def test_every_declared_kind_is_inventoried_and_dispositioned(
    kind: CompatibilityKind,
) -> None:
    obligation = _obligation(kind)
    inventory = _inventory((obligation,))
    restored = PublicCompatibilityInventory.from_dict(inventory.to_dict())
    assert restored == inventory
    assert restored.inventory_cid == inventory.inventory_cid
    assert restored.inventory_cid == cid_for_structured(inventory.identity_payload())
    assert restored.covered_kinds == (kind.value,)
    assert restored.covered_surfaces == (surface_for_kind(kind).value,)
    assert restored.facade_required is False
    terminal = restored.evaluate()
    assert terminal.kind == CompatibilityTerminalKind.ADMITTED.value
    assert terminal.success is True
    assert terminal.authorizes_completion is False
    assert inventory.authorizes_completion is False
    assert inventory.authorizes_facade_retirement is False
    assert len(restored.edges) == 1
    assert restored.edges[0].kind == kind.value
    assert restored.edges[0].disposition == "preserve"
    assert restored.edges[0].dispositioned is True


def test_complete_inventory_covers_every_kind_and_task_surface() -> None:
    inventory = _inventory()
    assert set(inventory.covered_kinds) == PUBLIC_COMPATIBILITY_KINDS
    assert set(inventory.covered_surfaces) == TASK_SURFACES
    assert len(inventory.obligations) == len(CompatibilityKind)
    assert len(inventory.consumers) == 1
    assert inventory.consumers[0].consumer_id == "pkg.cli"
    assert inventory.facade_required is False
    terminal = inventory.evaluate()
    assert terminal.kind == CompatibilityTerminalKind.ADMITTED.value
    assert terminal.success is True
    restored = PublicCompatibilityInventory.from_dict(
        json.loads(json.dumps(inventory.to_dict()))
    )
    assert restored.to_dict() == inventory.to_dict()
    assert restored.inventory_cid == inventory.inventory_cid


def test_consumers_are_first_class_and_round_trip() -> None:
    consumer = CompatibilityConsumer(
        consumer_id="tests.unit.test_record",
        module_name="tests.unit.test_record",
        role=ConsumerRole.TEST,
        required=True,
    )
    obligation = _obligation(
        CompatibilityKind.PATCH_TARGET,
        consumer_id="tests.unit.test_record",
        patch_target=_patch_target(),
    )
    inventory = inventory_public_compatibility(
        (obligation,),
        tree_id=TREE_ID,
        source_cid=_cid("source"),
        consumers=(consumer,),
    )
    restored = CompatibilityConsumer.from_dict(consumer.to_dict())
    assert restored == consumer
    assert restored.consumer_cid == cid_for_structured(consumer.identity_payload())
    assert inventory.consumers[0].role == ConsumerRole.TEST.value
    assert inventory.obligations_for_consumer("tests.unit.test_record") == (obligation,)
    assert inventory.consumers_for_subject("symbol:pkg.mod.Record") == (consumer,)


def test_synthesized_consumers_keep_tests_and_proofs_explicit() -> None:
    test_obl = _obligation(
        CompatibilityKind.PATCH_TARGET,
        consumer_id="tests.unit.test_record",
    )
    proof_obl = _obligation(
        CompatibilityKind.SIGNATURE,
        obligation_id="obl:signature:proof",
        consumer_id="proofs.boundary.record",
        introspection=_introspection(surface="signature", expected_value="save"),
    )
    consumers = synthesize_consumers((test_obl, proof_obl))
    roles = {item.consumer_id: item.role for item in consumers}
    assert roles["tests.unit.test_record"] == ConsumerRole.TEST.value
    assert roles["proofs.boundary.record"] == ConsumerRole.PROOF.value


def test_facade_required_until_every_consumer_is_dispositioned() -> None:
    preserved = _obligation(CompatibilityKind.IMPORT_PATH)
    pending = _obligation(
        CompatibilityKind.QUALNAME,
        obligation_id="obl:qualname:pending",
        consumer_id="pkg.legacy",
        disposition=CompatibilityDisposition.UNDISPOSITIONED,
        introspection=_introspection(surface="qualname"),
    )
    inventory = _inventory((preserved, pending))
    assert inventory.facade_required is True
    assert inventory.facades[0].facade_required is True
    assert inventory.facades[0].undispositioned_consumer_ids == ("pkg.legacy",)
    terminal = inventory.evaluate()
    assert terminal.kind == CompatibilityTerminalKind.INCOMPLETE_CONTRACT.value
    assert terminal.success is False
    assert terminal.authorizes_completion is False
    assert "undispositioned" in terminal.reason or "façade" in terminal.reason


def test_dispositioned_consumers_release_blocking_facade_requirement() -> None:
    migrated = _obligation(
        CompatibilityKind.IMPORT_PATH,
        disposition=CompatibilityDisposition.MIGRATE,
    )
    facade = _obligation(
        CompatibilityKind.QUALNAME,
        obligation_id="obl:qualname:facade",
        consumer_id="pkg.legacy",
        disposition=CompatibilityDisposition.FACADE,
        introspection=_introspection(surface="qualname"),
    )
    inventory = _inventory((migrated, facade))
    assert inventory.facade_required is False
    assert set(inventory.facades[0].dispositions) == {"facade", "migrate"}
    terminal = inventory.evaluate()
    assert terminal.kind == CompatibilityTerminalKind.ADMITTED.value
    assert terminal.success is True
    assert inventory.authorizes_facade_retirement is False


def test_graph_edges_match_declared_obligations() -> None:
    import_obl = _obligation(CompatibilityKind.IMPORT_EFFECT)
    patch_obl = _obligation(
        CompatibilityKind.PATCH_TARGET,
        obligation_id="obl:patch:tests",
        consumer_id="tests.unit.test_record",
    )
    inventory = _inventory((import_obl, patch_obl))
    assert len(inventory.edges) == 2
    by_obligation = {item.obligation_id: item for item in inventory.edges}
    assert by_obligation[import_obl.obligation_id].surface == "import"
    assert by_obligation[patch_obl.obligation_id].surface == "patch"
    assert by_obligation[patch_obl.obligation_id].consumer_id == "tests.unit.test_record"
    restored = CompatibilityGraphEdge.from_dict(inventory.edges[0].to_dict())
    assert restored == inventory.edges[0]
    assert restored.edge_cid == cid_for_structured(inventory.edges[0].identity_payload())


def test_nested_records_round_trip_independently() -> None:
    records = (
        CompatibilityConsumer(consumer_id="pkg.cli", module_name="pkg.cli"),
        CompatibilityGraphEdge.from_obligation(_obligation()),
        SubjectFacadeRecord(
            subject_id="symbol:pkg.mod.Record",
            subject_module="pkg.mod",
            facade_required=False,
            consumer_ids=("pkg.cli",),
            undispositioned_consumer_ids=(),
            dispositions=("preserve",),
        ),
    )
    for record in records:
        restored = type(record).from_dict(record.to_dict())
        assert restored == record


def test_unknown_and_missing_fields_are_rejected() -> None:
    inventory = _inventory((_obligation(),))
    payload = inventory.to_dict()
    payload["timestamp"] = "now"
    with pytest.raises(CompatibilityInventoryError, match="observational"):
        PublicCompatibilityInventory.from_dict(payload)
    payload = inventory.to_dict()
    payload["extra"] = "nope"
    with pytest.raises(CompatibilityInventoryError, match="unknown"):
        PublicCompatibilityInventory.from_dict(payload)
    payload = inventory.to_dict()
    payload.pop("tree_id")
    with pytest.raises(CompatibilityInventoryError, match="missing"):
        PublicCompatibilityInventory.from_dict(payload)


def test_identity_excludes_observational_metadata() -> None:
    assert {
        "timestamp",
        "process_id",
        "pid",
        "local_path",
        "model_output",
        "provider",
        "prompt",
    } <= IDENTITY_EXCLUDED_FIELDS
    consumer = CompatibilityConsumer(consumer_id="pkg.cli", module_name="pkg.cli")
    payload = consumer.to_dict()
    payload["model_output"] = "guess"
    with pytest.raises(CompatibilityInventoryError, match="observational"):
        CompatibilityConsumer.from_dict(payload)


def test_tree_id_and_source_cid_are_exact() -> None:
    with pytest.raises(CompatibilityInventoryError, match="lowercase hex"):
        _inventory((_obligation(),), tree_id="NOT-A-TREE")
    with pytest.raises(CompatibilityInventoryError, match="valid CID"):
        _inventory((_obligation(),), source_cid="not-a-cid")


def test_forged_cids_and_schema_versions_fail_closed() -> None:
    inventory = _inventory((_obligation(),))
    payload = inventory.to_dict()
    payload["inventory_cid"] = _cid("forged")
    with pytest.raises(CompatibilityInventoryError, match="does not verify"):
        PublicCompatibilityInventory.from_dict(payload)
    payload = inventory.to_dict()
    payload["schema"] = (
        "ipfs-datasets.semantic-refactoring.public-compatibility-inventory@0"
    )
    with pytest.raises(CompatibilityInventoryError, match="unsupported"):
        PublicCompatibilityInventory.from_dict(payload)
    payload = inventory.to_dict()
    payload["interface"] = "PublicCompatibilityInventory@0"
    with pytest.raises(CompatibilityInventoryError, match="unsupported"):
        PublicCompatibilityInventory.from_dict(payload)


def test_forged_derived_graph_and_facade_fields_fail_closed() -> None:
    inventory = _inventory((_obligation(),))
    payload = inventory.to_dict()
    payload["facade_required"] = True
    with pytest.raises(CompatibilityInventoryError, match="facade_required"):
        PublicCompatibilityInventory.from_dict(payload)
    payload = inventory.to_dict()
    payload["covered_kinds"] = ["cli"]
    with pytest.raises(CompatibilityInventoryError, match="covered_kinds"):
        PublicCompatibilityInventory.from_dict(payload)
    payload = inventory.to_dict()
    payload["edges"] = []
    with pytest.raises(CompatibilityInventoryError, match="edges"):
        PublicCompatibilityInventory.from_dict(payload)


def test_duplicate_ids_and_orphan_consumers_fail_closed() -> None:
    obligation = _obligation()
    with pytest.raises(CompatibilityInventoryError, match="unique obligation_id"):
        _inventory((obligation, obligation))
    extra = CompatibilityConsumer(consumer_id="pkg.orphan", module_name="pkg.orphan")
    with pytest.raises(CompatibilityInventoryError, match="orphan"):
        inventory_public_compatibility(
            (obligation,),
            tree_id=TREE_ID,
            source_cid=_cid("source"),
            consumers=(
                CompatibilityConsumer(consumer_id="pkg.cli", module_name="pkg.cli"),
                extra,
            ),
        )
    with pytest.raises(CompatibilityInventoryError, match="missing consumers"):
        PublicCompatibilityInventory(
            tree_id=TREE_ID,
            source_cid=_cid("source"),
            obligations=(obligation,),
            consumers=(),
        )


def test_conflicting_dispositions_are_typed_failures() -> None:
    first = _obligation(CompatibilityKind.QUALNAME)
    second = _obligation(
        CompatibilityKind.QUALNAME,
        obligation_id="obl:qualname:conflict",
        disposition=CompatibilityDisposition.MIGRATE,
        introspection=_introspection(surface="qualname"),
    )
    with pytest.raises(CompatibilityInventoryError, match="conflicting dispositions"):
        _inventory((first, second))


def test_duplicate_coverage_fails_closed() -> None:
    first = _obligation(CompatibilityKind.CLI)
    second = _obligation(
        CompatibilityKind.CLI,
        obligation_id="obl:cli:duplicate",
        cli_plugin=_cli_plugin(name="pkg-other"),
    )
    with pytest.raises(CompatibilityInventoryError, match="duplicate"):
        _inventory((first, second))


def test_unsupported_required_behavior_is_typed_terminal_never_success() -> None:
    obligation = _obligation(
        CompatibilityKind.SERIALIZATION,
        support_status=SupportStatus.UNSUPPORTED,
        disposition=CompatibilityDisposition.UNSUPPORTED,
        serialization=_serialization(support_status=SupportStatus.UNSUPPORTED),
    )
    inventory = _inventory((obligation,))
    terminal = inventory.evaluate()
    assert terminal.kind == CompatibilityTerminalKind.UNSUPPORTED_REQUIRED.value
    assert terminal.success is False
    assert terminal.required is True
    assert terminal.authorizes_completion is False


def test_unknown_required_and_undispositioned_consumers_are_typed_terminals() -> None:
    unknown = _obligation(
        CompatibilityKind.INTROSPECTION,
        support_status=SupportStatus.UNKNOWN,
        disposition=CompatibilityDisposition.UNDISPOSITIONED,
        introspection=_introspection(support_status=SupportStatus.UNKNOWN),
    )
    inventory = _inventory((unknown,))
    terminal = inventory.evaluate()
    assert terminal.kind == CompatibilityTerminalKind.UNKNOWN_REQUIRED.value
    assert terminal.success is False
    assert inventory.facade_required is True

    missing_consumer = _obligation(
        CompatibilityKind.PLUGIN,
        consumer_id=None,
        disposition=CompatibilityDisposition.UNDISPOSITIONED,
        cli_plugin=_cli_plugin(channel="plugin"),
    )
    incomplete = _inventory((missing_consumer,))
    assert incomplete.consumers == ()
    assert incomplete.edges == ()
    assert incomplete.facade_required is True
    public = incomplete.evaluate()
    assert public.kind == CompatibilityTerminalKind.INCOMPLETE_CONTRACT.value
    assert public.success is False


def test_optional_unsupported_is_explicit_and_not_success() -> None:
    obligation = _obligation(
        CompatibilityKind.DOCUMENTATION,
        required=False,
        support_status=SupportStatus.UNSUPPORTED,
        disposition=CompatibilityDisposition.UNSUPPORTED,
        introspection=_introspection(
            surface="documentation",
            support_status=SupportStatus.UNSUPPORTED,
            required=False,
        ),
    )
    inventory = _inventory((obligation,))
    terminal = inventory.evaluate()
    assert terminal.kind == CompatibilityTerminalKind.UNSUPPORTED_OPTIONAL.value
    assert terminal.success is False
    assert terminal.required is False


def test_explicit_incompatibility_is_classified_not_hidden() -> None:
    obligation = _obligation(
        CompatibilityKind.QUALNAME,
        disposition=CompatibilityDisposition.EXPLICIT_INCOMPATIBILITY,
        introspection=_introspection(surface="qualname"),
    )
    inventory = _inventory((obligation,))
    terminal = inventory.evaluate()
    assert terminal.kind == CompatibilityTerminalKind.ADMITTED.value
    assert obligation.disposition == "explicit_incompatibility"
    assert inventory.facades[0].dispositions == ("explicit_incompatibility",)
    assert inventory.facade_required is False


def test_empty_inventory_is_incomplete_not_success() -> None:
    inventory = PublicCompatibilityInventory(
        tree_id=TREE_ID,
        source_cid=_cid("source"),
        obligations=(),
        consumers=(),
    )
    terminal = inventory.evaluate()
    assert terminal.kind == CompatibilityTerminalKind.INCOMPLETE_CONTRACT.value
    assert terminal.success is False
    assert terminal.reason == "inventory requires declared obligations"


def test_canonical_encoding_is_byte_identical_across_construction() -> None:
    first = _inventory((_obligation(CompatibilityKind.PICKLE),))
    second = PublicCompatibilityInventory.from_dict(
        json.loads(json.dumps(first.to_dict()))
    )
    assert first.to_dict() == second.to_dict()
    assert first.inventory_cid == second.inventory_cid
    assert cid_for_structured(first.identity_payload()) == first.inventory_cid


def test_location_sensitive_inventory_changes_when_subject_module_moves() -> None:
    original = _obligation(CompatibilityKind.MODULE_NAME)
    moved = _obligation(
        CompatibilityKind.MODULE_NAME,
        subject_module="pkg.extracted.mod",
        introspection=_introspection(
            surface="module_name", expected_value="pkg.extracted.mod"
        ),
    )
    left = _inventory((original,))
    right = _inventory((moved,))
    assert left.inventory_cid != right.inventory_cid
    assert left.obligations[0].obligation_cid != right.obligations[0].obligation_cid


def test_admitted_inventory_cannot_be_forged_into_completion_or_retirement() -> None:
    inventory = _inventory((_obligation(),))
    payload = inventory.to_dict()
    payload["authorizes_completion"] = True
    with pytest.raises(CompatibilityInventoryError, match="cannot authorize completion"):
        PublicCompatibilityInventory.from_dict(payload)
    payload = inventory.to_dict()
    payload["authorizes_transition"] = True
    with pytest.raises(CompatibilityInventoryError, match="cannot authorize transition"):
        PublicCompatibilityInventory.from_dict(payload)
    payload = inventory.to_dict()
    payload["authorizes_facade_retirement"] = True
    with pytest.raises(CompatibilityInventoryError, match="cannot retire"):
        PublicCompatibilityInventory.from_dict(payload)
    terminal = inventory.evaluate()
    payload = terminal.to_dict()
    payload["authorizes_completion"] = True
    with pytest.raises(Exception, match="cannot authorize completion"):
        CompatibilityTerminal.from_dict(payload)


def test_surface_mapping_is_closed_and_fail_closed() -> None:
    assert surface_for_kind(CompatibilityKind.IMPORT_PATH) is ConsumerSurface.IMPORT
    assert surface_for_kind(CompatibilityKind.SIGNATURE) is ConsumerSurface.API
    assert surface_for_kind(CompatibilityKind.QUALNAME) is ConsumerSurface.BINDING
    assert surface_for_kind(CompatibilityKind.PICKLE) is ConsumerSurface.SERIALIZATION
    assert surface_for_kind(CompatibilityKind.TRACEBACK) is ConsumerSurface.INTROSPECTION
    assert surface_for_kind(CompatibilityKind.CLI) is ConsumerSurface.CLI
    assert surface_for_kind(CompatibilityKind.PLUGIN) is ConsumerSurface.PLUGIN
    assert surface_for_kind(CompatibilityKind.REGISTRY) is ConsumerSurface.REGISTRATION
    assert surface_for_kind(CompatibilityKind.DOCUMENTATION) is ConsumerSurface.DOCUMENTATION
    assert surface_for_kind(CompatibilityKind.PATCH_TARGET) is ConsumerSurface.PATCH
    assert surface_for_kind(CompatibilityKind.RESOURCE) is ConsumerSurface.REGISTRATION
    with pytest.raises(ValueError):
        surface_for_kind("not-a-kind")


def test_protected_controls_are_outside_write_scope_and_remain() -> None:
    protected = set(PROTECTED_PATHS)
    assert protected.isdisjoint(WRITE_SCOPE)
    for relative in PROTECTED_PATHS:
        path = ROOT / relative
        assert path.exists(), relative
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))


def test_authority_matrix_and_safety_floors_do_not_regress() -> None:
    authority = json.loads((INVENTORY / "authority_matrix.json").read_text(encoding="utf-8"))
    owners = {row["authority"]: row["owner"] for row in authority["rules"]}
    assert owners["formal semantic authority"] == "ipfs_datasets_py"
    assert owners["storage and retrieval authority"] == "ipfs_kit_py"
    assert owners["operational refactoring authority"] == "ipfs_accelerate_py"
    preregistration = json.loads(
        (INVENTORY / "benchmark_preregistration.json").read_text(encoding="utf-8")
    )
    floors = preregistration["zero_safety_floors"]
    assert floors and all(value == 0 for value in floors.values())
    assert floors["unaccepted_public_api_break"] == 0
    assert floors["test_or_proof_weakening"] == 0
    identity = json.loads((INVENTORY / "identity_inventory.json").read_text(encoding="utf-8"))
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    for capsule in identity["capsule_types"]:
        assert capsule.split("@", 1)[0] not in names


def test_import_is_provider_free() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
    assert "openai" not in imported
    assert "ipfs_kit_py" not in imported
    assert "ipfs_accelerate_py" not in imported
    assert "software_contracts" in source
    assert "cid_for_structured" in source
    assert "PublicCompatibilityObligation" in source
    assert "evaluate_compatibility" in source
