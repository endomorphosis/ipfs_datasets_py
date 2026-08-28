"""SPAR-004 contract vectors for initialization and public compatibility."""

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
    AUTHORITY,
    AUTHORITY_OWNER,
    COMPATIBILITY_CAN_AUTHORIZE_COMPLETION,
    COMPATIBILITY_CAN_AUTHORIZE_TRANSITION,
    COMPATIBILITY_CONTRACTS_SCHEMA,
    CliPluginObligation,
    CompatibilityContractError,
    CompatibilityDisposition,
    CompatibilityKind,
    CompatibilityTerminal,
    CompatibilityTerminalKind,
    DecoratorObligation,
    DUCKLAKE_IS_AUTHORITY,
    EvidenceClass,
    FIRST_CLASS_OBLIGATION_KINDS,
    IDENTITY_EXCLUDED_FIELDS,
    INITIALIZATION_BLOCK_INTERFACE,
    ImportEffect,
    InitializationBlock,
    IntrospectionObligation,
    KIND_FAMILY,
    MARKDOWN_IS_NOT_COMPLETION,
    MODEL_OUTPUT_IS_PROPOSAL_ONLY,
    PUBLIC_COMPATIBILITY_KINDS,
    PUBLIC_COMPATIBILITY_OBLIGATION_INTERFACE,
    PatchTargetObligation,
    PublicCompatibilityObligation,
    RegistryObligation,
    ResourceObligation,
    SerializationObligation,
    SupportStatus,
    TASK_ID,
    TEST_PASS_IS_NOT_COMPLETION,
    VECTOR_SIMILARITY_IS_AUTHORITY,
    WORKER_SELF_APPROVAL,
    evaluate_compatibility,
    evaluate_initialization_block,
    evaluate_public_compatibility,
    family_for_kind,
)


ROOT = Path(__file__).resolve().parents[4]
MODULE_PATH = (
    ROOT
    / "ipfs_datasets_py"
    / "ipfs_datasets_py"
    / "semantic_refactoring"
    / "compatibility.py"
)
TEST_PATH = Path(__file__).resolve()
INVENTORY = (
    ROOT
    / "docs"
    / "architecture"
    / "semantic_preserving_autonomous_remodularization_inventory"
)
WRITE_SCOPE = (
    "ipfs_datasets_py/ipfs_datasets_py/semantic_refactoring/compatibility.py",
    "ipfs_datasets_py/tests/unit/semantic_refactoring/test_compatibility_contracts.py",
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


def _block(**overrides: Any) -> InitializationBlock:
    fields = {
        "block_id": "block:pkg.mod:toplevel:0",
        "module_path": "ipfs_datasets_py/semantic_refactoring/compatibility.py",
        "source_cid": _cid("source"),
        "start_line": 1,
        "end_line": 12,
        "order_index": 0,
        "eagerness": "eager",
        "import_effects": (_import_effect(),),
        "registries": (_registry(),),
        "decorators": (_decorator(),),
        "resources": (_resource(),),
        "happens_before": (),
    }
    fields.update(overrides)
    return InitializationBlock(**fields)


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


def test_owned_paths_and_task_identity_are_exact() -> None:
    assert TASK_ID == "SPAR-004"
    assert INITIALIZATION_BLOCK_INTERFACE == "InitializationBlock@1"
    assert PUBLIC_COMPATIBILITY_OBLIGATION_INTERFACE == "PublicCompatibilityObligation@1"
    assert COMPATIBILITY_CONTRACTS_SCHEMA.endswith("@1")
    assert MODULE_PATH.is_file()
    assert TEST_PATH.is_file()
    for relative in WRITE_SCOPE:
        assert (ROOT / relative).is_file()


def test_authority_flags_cannot_self_authorize() -> None:
    assert AUTHORITY == "formal semantic authority"
    assert AUTHORITY_OWNER == "ipfs_datasets_py"
    assert COMPATIBILITY_CAN_AUTHORIZE_COMPLETION is False
    assert COMPATIBILITY_CAN_AUTHORIZE_TRANSITION is False
    assert VECTOR_SIMILARITY_IS_AUTHORITY is False
    assert MODEL_OUTPUT_IS_PROPOSAL_ONLY is True
    assert TEST_PASS_IS_NOT_COMPLETION is True
    assert MARKDOWN_IS_NOT_COMPLETION is True
    assert WORKER_SELF_APPROVAL is False
    assert DUCKLAKE_IS_AUTHORITY is False


def test_closed_vocabularies_cover_plan_surfaces() -> None:
    required = {
        "import_path",
        "import_effect",
        "import_eagerness",
        "import_order",
        "star_export",
        "module_attribute",
        "signature",
        "annotation",
        "default",
        "decorator",
        "exception",
        "cli",
        "plugin",
        "registry",
        "module_name",
        "qualname",
        "pickle",
        "serialization",
        "introspection",
        "traceback",
        "documentation",
        "configuration",
        "patch_target",
        "resource",
        "resource_lifetime",
    }
    assert PUBLIC_COMPATIBILITY_KINDS == required
    assert FIRST_CLASS_OBLIGATION_KINDS == {
        "import_effect",
        "registry",
        "decorator",
        "resource",
        "serialization",
        "introspection",
        "cli",
        "plugin",
        "patch_target",
    }
    assert set(KIND_FAMILY) == set(CompatibilityKind)


def test_module_defines_predicted_symbols_not_capsule_family() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    assert "InitializationBlock" in names
    assert "PublicCompatibilityObligation" in names
    assert "CompatibilityTerminal" in names
    for capsule in CAPSULE_TYPES:
        assert capsule not in names


@pytest.mark.parametrize("kind", list(CompatibilityKind))
def test_every_public_kind_is_first_class_and_round_trips(
    kind: CompatibilityKind,
) -> None:
    obligation = _obligation(kind)
    restored = PublicCompatibilityObligation.from_dict(obligation.to_dict())
    assert restored == obligation
    assert restored.obligation_cid == obligation.obligation_cid
    assert restored.obligation_cid == cid_for_structured(obligation.identity_payload())
    payload_field = {
        "import": "import_effect",
        "registry": "registry",
        "decorator": "decorator",
        "resource": "resource",
        "serialization": "serialization",
        "introspection": "introspection",
        "cli_plugin": "cli_plugin",
        "patch_target": "patch_target",
    }[family_for_kind(kind).value]
    assert restored.to_dict()[payload_field] is not None
    payload = restored.nested_payload()
    assert payload.support_status == SupportStatus.SUPPORTED.value


def test_initialization_block_is_first_class_for_import_registry_decorator_resource() -> None:
    block = _block(happens_before=("block:pkg.mod:prelude",))
    assert block.interface == "InitializationBlock@1"
    assert len(block.import_effects) == 1
    assert len(block.registries) == 1
    assert len(block.decorators) == 1
    assert len(block.resources) == 1
    restored = InitializationBlock.from_dict(block.to_dict())
    assert restored == block
    assert restored.block_cid == cid_for_structured(block.identity_payload())
    assert restored.happens_before == ("block:pkg.mod:prelude",)


def test_nested_records_round_trip_independently() -> None:
    records = (
        _import_effect(),
        _registry(),
        _decorator(),
        _resource(),
        _serialization(),
        _introspection(),
        _cli_plugin(),
        _patch_target(),
    )
    for record in records:
        restored = type(record).from_dict(record.to_dict())
        assert restored == record
        assert restored.record_cid == cid_for_structured(record.identity_payload())


def test_unknown_and_missing_fields_are_rejected() -> None:
    block = _block()
    payload = block.to_dict()
    payload["timestamp"] = "now"
    with pytest.raises(CompatibilityContractError, match="observational"):
        InitializationBlock.from_dict(payload)
    payload = block.to_dict()
    payload["extra"] = "nope"
    with pytest.raises(CompatibilityContractError, match="unknown"):
        InitializationBlock.from_dict(payload)
    payload = block.to_dict()
    payload.pop("module_path")
    with pytest.raises(CompatibilityContractError, match="missing"):
        InitializationBlock.from_dict(payload)


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
    obligation = _obligation()
    payload = obligation.to_dict()
    payload["model_output"] = "guess"
    with pytest.raises(CompatibilityContractError, match="observational"):
        PublicCompatibilityObligation.from_dict(payload)


def test_absolute_and_parent_paths_are_rejected() -> None:
    with pytest.raises(CompatibilityContractError, match="repository-relative"):
        _block(module_path="/tmp/mod.py")
    with pytest.raises(CompatibilityContractError, match="POSIX"):
        _block(module_path="../outside.py")
    with pytest.raises(CompatibilityContractError, match="dotted"):
        _patch_target(dotted_path=".relative.path")


def test_forged_cids_and_schema_versions_fail_closed() -> None:
    block = _block()
    payload = block.to_dict()
    payload["block_cid"] = _cid("forged")
    with pytest.raises(CompatibilityContractError, match="does not verify"):
        InitializationBlock.from_dict(payload)
    payload = block.to_dict()
    payload["schema"] = "ipfs-datasets.semantic-refactoring.initialization-block@0"
    with pytest.raises(CompatibilityContractError, match="unsupported"):
        InitializationBlock.from_dict(payload)
    obligation = _obligation()
    payload = obligation.to_dict()
    payload["interface"] = "PublicCompatibilityObligation@0"
    with pytest.raises(CompatibilityContractError, match="unsupported"):
        PublicCompatibilityObligation.from_dict(payload)


def test_kind_requires_matching_first_class_payload() -> None:
    with pytest.raises(CompatibilityContractError, match="import_effect is required"):
        PublicCompatibilityObligation(
            obligation_id="obl:missing",
            kind=CompatibilityKind.IMPORT_EFFECT,
            subject_id="symbol:x",
            subject_module="pkg.mod",
            subject_qualname="pkg.mod.fn",
            required=True,
            support_status=SupportStatus.SUPPORTED,
            disposition=CompatibilityDisposition.PRESERVE,
            consumer_id="pkg.cli",
            patch_target=_patch_target(),
        )
    with pytest.raises(CompatibilityContractError, match="admits only"):
        _obligation(
            CompatibilityKind.REGISTRY,
            registry=_registry(),
            decorator=_decorator(),
        )


def test_happens_before_cannot_include_self_and_order_is_unique() -> None:
    with pytest.raises(CompatibilityContractError, match="cannot include self"):
        _block(happens_before=("block:pkg.mod:toplevel:0",))
    with pytest.raises(CompatibilityContractError, match="unique"):
        _block(
            import_effects=(
                _import_effect(order_index=0),
                _import_effect(
                    module_name="pkg.other",
                    imported_names=("x",),
                    order_index=0,
                ),
            )
        )
    with pytest.raises(CompatibilityContractError, match="nondecreasing"):
        _block(
            import_effects=(
                _import_effect(order_index=2, module_name="pkg.late"),
                _import_effect(order_index=1, module_name="pkg.early", imported_names=("y",)),
            )
        )


def test_supported_initialization_and_obligations_admit_without_completion_authority() -> None:
    prelude = _block(
        block_id="block:pkg.mod:prelude",
        start_line=1,
        end_line=4,
        order_index=0,
        import_effects=(_import_effect(),),
        registries=(),
        decorators=(),
        resources=(),
    )
    body = _block(
        block_id="block:pkg.mod:body",
        start_line=5,
        end_line=20,
        order_index=1,
        happens_before=("block:pkg.mod:prelude",),
    )
    obligation = _obligation(CompatibilityKind.CLI)
    terminal = evaluate_compatibility(blocks=(prelude, body), obligations=(obligation,))
    assert terminal.kind == CompatibilityTerminalKind.ADMITTED.value
    assert terminal.success is True
    assert terminal.authorizes_completion is False
    assert COMPATIBILITY_CAN_AUTHORIZE_COMPLETION is False
    restored = CompatibilityTerminal.from_dict(terminal.to_dict())
    assert restored == terminal
    assert restored.authorizes_completion is False


def test_unsupported_required_behavior_is_typed_terminal_never_success() -> None:
    block = _block(support_status=SupportStatus.UNSUPPORTED)
    terminal = evaluate_initialization_block(block)
    assert terminal.kind == CompatibilityTerminalKind.UNSUPPORTED_REQUIRED.value
    assert terminal.success is False
    assert terminal.required is True
    assert terminal.authorizes_completion is False

    obligation = _obligation(
        CompatibilityKind.SERIALIZATION,
        support_status=SupportStatus.UNSUPPORTED,
        disposition=CompatibilityDisposition.UNSUPPORTED,
        serialization=_serialization(support_status=SupportStatus.UNSUPPORTED),
    )
    public = evaluate_public_compatibility(obligation)
    assert public.kind == CompatibilityTerminalKind.UNSUPPORTED_REQUIRED.value
    assert public.success is False
    merged = evaluate_compatibility(blocks=(block,), obligations=(obligation,))
    assert merged.kind == CompatibilityTerminalKind.UNSUPPORTED_REQUIRED.value
    assert merged.success is False


def test_unknown_required_and_undispositioned_consumers_are_typed_terminals() -> None:
    unknown = _obligation(
        CompatibilityKind.INTROSPECTION,
        support_status=SupportStatus.UNKNOWN,
        disposition=CompatibilityDisposition.UNDISPOSITIONED,
        introspection=_introspection(support_status=SupportStatus.UNKNOWN),
    )
    terminal = evaluate_public_compatibility(unknown)
    assert terminal.kind == CompatibilityTerminalKind.UNKNOWN_REQUIRED.value
    assert terminal.success is False

    missing_consumer = _obligation(
        CompatibilityKind.PLUGIN,
        consumer_id=None,
        disposition=CompatibilityDisposition.UNDISPOSITIONED,
        cli_plugin=_cli_plugin(channel="plugin"),
    )
    incomplete = evaluate_public_compatibility(missing_consumer)
    assert incomplete.kind == CompatibilityTerminalKind.INCOMPLETE_CONTRACT.value
    assert incomplete.success is False


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
    terminal = evaluate_public_compatibility(obligation)
    assert terminal.kind == CompatibilityTerminalKind.UNSUPPORTED_OPTIONAL.value
    assert terminal.success is False
    assert terminal.required is False


def test_nested_required_unsupported_inside_supported_block_is_still_terminal() -> None:
    block = _block(
        resources=(
            _resource(support_status=SupportStatus.UNSUPPORTED, required=True),
        )
    )
    terminal = evaluate_initialization_block(block)
    assert terminal.kind == CompatibilityTerminalKind.UNSUPPORTED_REQUIRED.value
    assert terminal.success is False


def test_missing_happens_before_predecessor_is_incomplete_not_success() -> None:
    block = _block(happens_before=("block:missing",))
    terminal = evaluate_compatibility(blocks=(block,))
    assert terminal.kind == CompatibilityTerminalKind.INCOMPLETE_CONTRACT.value
    assert terminal.success is False


def test_duplicate_ids_fail_closed() -> None:
    block = _block()
    with pytest.raises(CompatibilityContractError, match="unique block_id"):
        evaluate_compatibility(blocks=(block, block))
    obligation = _obligation()
    with pytest.raises(CompatibilityContractError, match="unique obligation_id"):
        evaluate_compatibility(obligations=(obligation, obligation))


def test_explicit_incompatibility_is_classified_not_hidden() -> None:
    obligation = _obligation(
        CompatibilityKind.QUALNAME,
        disposition=CompatibilityDisposition.EXPLICIT_INCOMPATIBILITY,
        introspection=_introspection(surface="qualname"),
    )
    terminal = evaluate_public_compatibility(obligation)
    assert terminal.kind == CompatibilityTerminalKind.ADMITTED.value
    assert obligation.disposition == "explicit_incompatibility"
    with pytest.raises(CompatibilityContractError, match="unsupported disposition"):
        _obligation(
            CompatibilityKind.QUALNAME,
            support_status=SupportStatus.SUPPORTED,
            disposition=CompatibilityDisposition.UNSUPPORTED,
            introspection=_introspection(surface="qualname"),
        )


def test_canonical_encoding_is_byte_identical_across_construction() -> None:
    first = _obligation(CompatibilityKind.PICKLE)
    second = PublicCompatibilityObligation.from_dict(json.loads(json.dumps(first.to_dict())))
    assert first.to_dict() == second.to_dict()
    assert first.obligation_cid == second.obligation_cid
    assert cid_for_structured(first.identity_payload()) == first.obligation_cid


def test_admitted_terminal_cannot_be_forged_into_completion_authority() -> None:
    terminal = evaluate_public_compatibility(_obligation())
    payload = terminal.to_dict()
    payload["authorizes_completion"] = True
    with pytest.raises(CompatibilityContractError, match="cannot authorize completion"):
        CompatibilityTerminal.from_dict(payload)
    payload = terminal.to_dict()
    payload["success"] = False
    with pytest.raises(CompatibilityContractError, match="success does not match"):
        CompatibilityTerminal.from_dict(payload)


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
