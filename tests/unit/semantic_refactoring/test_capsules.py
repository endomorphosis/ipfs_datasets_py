"""Independent contract tests for SPAR-002 closed capsule records."""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    PROFILE_ID,
    STRUCTURED_CODEC,
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
)
from ipfs_datasets_py.semantic_refactoring.capsules import (
    CAPSULE_SCHEMA_REGISTRY,
    CAPSULE_TYPES,
    FORBIDDEN_OBSERVATIONAL_FIELDS,
    FUNCTION_SEMANTIC_CAPSULE_INTERFACE,
    FUNCTION_SEMANTIC_CAPSULE_SCHEMA,
    IDENTITY_DIMENSIONS,
    BlockKind,
    CallsiteSemanticCapsule,
    CapsuleContractError,
    CapsuleFreshness,
    CapsuleKind,
    ClassSemanticCapsule,
    DispatchKind,
    EvidenceClass,
    FunctionSemanticCapsule,
    MethodKind,
    MethodSemanticCapsule,
    ModuleSemanticCapsule,
    PackageSemanticCapsule,
    RegistrationCapsule,
    RegistrationKind,
    ResourceKind,
    ResourceLifecycleCapsule,
    StateOwnerCapsule,
    StateOwnerKind,
    StateUniqueness,
    TopLevelBlockCapsule,
    TypedUncertainty,
    capsule_cid_profile,
    capsule_from_dict,
    capsule_from_identity_payload,
    decode_canonical_capsule,
    encode_canonical_capsule,
    provider_free_exports,
)


CAPSULES_PATH = (
    Path(__file__).resolve().parents[3]
    / "ipfs_datasets_py"
    / "semantic_refactoring"
    / "capsules.py"
)
INVENTORY_PATH = (
    Path(__file__).resolve().parents[4]
    / "docs"
    / "architecture"
    / "semantic_preserving_autonomous_remodularization_inventory"
    / "identity_inventory.json"
)

_CAPSULE_CLASSES = (
    FunctionSemanticCapsule,
    MethodSemanticCapsule,
    ClassSemanticCapsule,
    TopLevelBlockCapsule,
    ModuleSemanticCapsule,
    PackageSemanticCapsule,
    CallsiteSemanticCapsule,
    StateOwnerCapsule,
    RegistrationCapsule,
    ResourceLifecycleCapsule,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _uncertainty(
    *,
    confidence: str = AnalysisConfidence.EXACT.value,
    unresolved: tuple[str, ...] = (),
    evidence: str = EvidenceClass.EXACT_STATIC_FACT.value,
) -> TypedUncertainty:
    return TypedUncertainty(
        confidence=confidence,
        unresolved_identity_fields=list(unresolved),
        evidence_class=evidence,
    )


def _identities() -> dict[str, str]:
    return {name: _cid(f"id:{name}") for name in IDENTITY_DIMENSIONS}


def _core() -> dict[str, Any]:
    return {
        **_identities(),
        "freshness": CapsuleFreshness.FRESH.value,
        "typed_uncertainty": _uncertainty(),
    }


def _function(**overrides: Any) -> FunctionSemanticCapsule:
    fields = {
        **_core(),
        "logical_qualname": "pkg.mod.answer",
        "owner_module_id": _cid("module:pkg.mod"),
        "is_async": False,
        "is_generator": False,
        "positional_arity": 1,
    }
    fields.update(overrides)
    return FunctionSemanticCapsule(**fields)


def _method(**overrides: Any) -> MethodSemanticCapsule:
    fields = {
        **_core(),
        "logical_qualname": "pkg.mod.Box.answer",
        "owner_class_id": _cid("class:pkg.mod.Box"),
        "owner_module_id": _cid("module:pkg.mod"),
        "method_kind": MethodKind.INSTANCE.value,
        "is_async": False,
        "is_generator": False,
        "positional_arity": 2,
    }
    fields.update(overrides)
    return MethodSemanticCapsule(**fields)


def _class(**overrides: Any) -> ClassSemanticCapsule:
    fields = {
        **_core(),
        "logical_qualname": "pkg.mod.Box",
        "owner_module_id": _cid("module:pkg.mod"),
        "base_class_ids": (_cid("class:object"),),
        "member_ids": (_cid("method:answer"),),
        "has_metaclass": False,
    }
    fields.update(overrides)
    return ClassSemanticCapsule(**fields)


def _block(**overrides: Any) -> TopLevelBlockCapsule:
    fields = {
        **_core(),
        "owner_module_id": _cid("module:pkg.mod"),
        "block_kind": BlockKind.IMPORT_STMT.value,
        "predecessor_ids": (),
        "effect_ids": (_cid("effect:import"),),
    }
    fields.update(overrides)
    return TopLevelBlockCapsule(**fields)


def _module(**overrides: Any) -> ModuleSemanticCapsule:
    fields = {
        **_core(),
        "logical_module_name": "pkg.mod",
        "owner_package_id": _cid("package:pkg"),
        "member_ids": (_cid("fn:answer"),),
        "top_level_block_ids": (_cid("block:import"),),
        "import_target_ids": (_cid("mod:json"),),
    }
    fields.update(overrides)
    return ModuleSemanticCapsule(**fields)


def _package(**overrides: Any) -> PackageSemanticCapsule:
    fields = {
        **_core(),
        "logical_package_name": "pkg",
        "parent_package_id": None,
        "module_ids": (_cid("module:pkg.mod"),),
        "child_package_ids": (),
    }
    fields.update(overrides)
    return PackageSemanticCapsule(**fields)


def _callsite(**overrides: Any) -> CallsiteSemanticCapsule:
    fields = {
        **_core(),
        "caller_id": _cid("fn:caller"),
        "callee_id": _cid("fn:callee"),
        "enclosing_module_id": _cid("module:pkg.mod"),
        "argument_count": 2,
        "dispatch_kind": DispatchKind.DIRECT.value,
    }
    fields.update(overrides)
    return CallsiteSemanticCapsule(**fields)


def _state_owner(**overrides: Any) -> StateOwnerCapsule:
    fields = {
        **_core(),
        "owner_kind": StateOwnerKind.MODULE_GLOBAL.value,
        "owning_symbol_id": _cid("fn:owner"),
        "uniqueness": StateUniqueness.UNIQUE.value,
        "alias_ids": (),
    }
    fields.update(overrides)
    return StateOwnerCapsule(**fields)


def _registration(**overrides: Any) -> RegistrationCapsule:
    fields = {
        **_core(),
        "registry_id": _cid("registry:cli"),
        "registered_symbol_id": _cid("fn:main"),
        "registration_kind": RegistrationKind.CLI_COMMAND.value,
        "order_index": 0,
    }
    fields.update(overrides)
    return RegistrationCapsule(**fields)


def _resource(**overrides: Any) -> ResourceLifecycleCapsule:
    fields = {
        **_core(),
        "resource_kind": ResourceKind.LOCK.value,
        "acquire_site_id": _cid("site:acquire"),
        "owner_id": _cid("fn:owner"),
        "release_site_id": _cid("site:release"),
    }
    fields.update(overrides)
    return ResourceLifecycleCapsule(**fields)


def _all_records() -> tuple[Any, ...]:
    return (
        _function(),
        _method(),
        _class(),
        _block(),
        _module(),
        _package(),
        _callsite(),
        _state_owner(),
        _registration(),
        _resource(),
    )


def test_landed_types_match_identity_inventory_and_ast_class_defs() -> None:
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    assert tuple(inventory["capsule_types"]) == CAPSULE_TYPES
    assert list(IDENTITY_DIMENSIONS) == [
        item for item in inventory["identity_fields"] if item != "function_capsule_cid"
    ]
    tree = ast.parse(CAPSULES_PATH.read_text(encoding="utf-8"))
    class_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    expected = {
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
        "TypedUncertainty",
    }
    assert expected <= class_names
    assert all(item.endswith("@1") for item in CAPSULE_TYPES)
    assert FUNCTION_SEMANTIC_CAPSULE_INTERFACE == "FunctionSemanticCapsule@1"
    assert FUNCTION_SEMANTIC_CAPSULE_SCHEMA.endswith("@1")


def test_every_capsule_round_trips_and_reverifies_independent_cid() -> None:
    for record in _all_records():
        restored = type(record).from_dict(record.to_dict())
        assert restored == record
        payload = record.identity_payload()
        assert cid_for_structured(payload) == record.capsule_cid
        assert payload.get(type(record).AGGREGATE_FIELD) is None
        exported = record.to_dict()
        assert exported[type(record).AGGREGATE_FIELD] == record.capsule_cid
        assert set(exported) == set(type(record)._FIELDS)
        dispatched = capsule_from_dict(exported)
        assert type(dispatched) is type(record)
        assert dispatched.capsule_cid == record.capsule_cid
        identity_restored = capsule_from_identity_payload(payload)
        assert identity_restored.capsule_cid == record.capsule_cid


def test_canonical_encoding_is_strict_and_byte_stable() -> None:
    record = _function()
    encoded = encode_canonical_capsule(record)
    assert encoded == record.canonical_bytes()
    assert encoded == canonical_dag_json_bytes(record.identity_payload())
    decoded = decode_canonical_capsule(encoded)
    assert decoded == record
    assert decode_canonical_capsule(encoded).canonical_bytes() == encoded
    pretty = json.dumps(record.identity_payload(), indent=2).encode("utf-8")
    with pytest.raises(CapsuleContractError, match="canonical"):
        decode_canonical_capsule(pretty)
    unsorted = json.dumps(record.identity_payload(), sort_keys=False).encode("utf-8")
    if unsorted != encoded:
        with pytest.raises(CapsuleContractError, match="canonical"):
            decode_canonical_capsule(unsorted)


def test_nested_values_are_immutable_and_records_are_frozen() -> None:
    record = _class(
        member_ids=[_cid("b"), _cid("a")],
        base_class_ids=[_cid("z"), _cid("y")],
    )
    assert record.member_ids == tuple(sorted({_cid("a"), _cid("b")}))
    assert record.base_class_ids == tuple(sorted({_cid("y"), _cid("z")}))
    with pytest.raises(TypeError):
        record.member_ids[0] = _cid("mutated")  # type: ignore[index]
    with pytest.raises(Exception):
        record.logical_qualname = "pkg.mod.Other"  # type: ignore[misc]
    uncertainty = record.typed_uncertainty
    with pytest.raises(Exception):
        uncertainty.confidence = AnalysisConfidence.OPAQUE.value  # type: ignore[misc]
    assert isinstance(uncertainty.unresolved_identity_fields, tuple)
    with pytest.raises(AttributeError):
        uncertainty.unresolved_identity_fields.append("source_cid")  # type: ignore[attr-defined]


def test_from_dict_does_not_rewrite_accepted_payloads_in_place() -> None:
    record = _function()
    payload = record.to_dict()
    original = copy.deepcopy(payload)
    frozen = MappingProxyType(payload)
    restored = FunctionSemanticCapsule.from_dict(frozen)
    assert restored == record
    assert payload == original
    forged = record.to_dict()
    forged[FunctionSemanticCapsule.AGGREGATE_FIELD] = _cid("forged-aggregate")
    with pytest.raises(CapsuleContractError, match="does not verify"):
        FunctionSemanticCapsule.from_dict(forged)
    assert FunctionSemanticCapsule.from_dict(record.to_dict()).to_dict() == record.to_dict()


def test_closed_records_reject_unknown_and_observational_fields() -> None:
    record = _function()
    extra = record.to_dict()
    extra["timestamp"] = "2026-08-28T00:00:00Z"
    with pytest.raises(CapsuleContractError, match="observational|exactly"):
        FunctionSemanticCapsule.from_dict(extra)
    missing = record.to_dict()
    missing.pop("logical_qualname")
    with pytest.raises(CapsuleContractError, match="exactly"):
        FunctionSemanticCapsule.from_dict(missing)
    for field_name in sorted(FORBIDDEN_OBSERVATIONAL_FIELDS):
        payload = record.to_dict()
        payload[field_name] = "observational"
        with pytest.raises(CapsuleContractError):
            FunctionSemanticCapsule.from_dict(payload)
    with pytest.raises(CapsuleContractError, match="unsupported"):
        FunctionSemanticCapsule.from_dict(
            {**record.to_dict(), "schema": FUNCTION_SEMANTIC_CAPSULE_SCHEMA.replace("@1", "@2")}
        )


def test_move_preserves_implementation_and_contract_identity() -> None:
    original = _function()
    moved = _function(
        symbol_binding_cid=_cid("binding:moved"),
        public_compatibility_cid=_cid("compat:moved"),
        logical_qualname="pkg.other.answer",
        owner_module_id=_cid("module:pkg.other"),
    )
    assert moved.implementation_ir_cid == original.implementation_ir_cid
    assert moved.interface_contract_cid == original.interface_contract_cid
    assert moved.symbol_binding_cid != original.symbol_binding_cid
    assert moved.public_compatibility_cid != original.public_compatibility_cid
    assert moved.function_capsule_cid != original.function_capsule_cid
    assert moved.stable_symbol_id == original.stable_symbol_id


def test_local_paths_floats_and_invalid_cids_are_rejected() -> None:
    with pytest.raises(CapsuleContractError, match="filesystem path"):
        _function(logical_qualname="/home/barberb/pkg/mod.py")
    with pytest.raises(CapsuleContractError, match="filesystem path"):
        _module(logical_module_name="C:\\Users\\pkg\\mod.py")
    with pytest.raises(CapsuleContractError, match="filesystem path"):
        _package(logical_package_name="~/src/pkg")
    with pytest.raises(CapsuleContractError, match="CID"):
        _function(source_cid="not-a-cid")
    planted = _function()
    object.__setattr__(planted, "logical_qualname", 1.5)
    with pytest.raises(CapsuleContractError, match="DAG-JSON"):
        planted.identity_payload()
    object.__setattr__(planted, "logical_qualname", b"bytes")
    with pytest.raises(CapsuleContractError, match="DAG-JSON"):
        planted.identity_payload()


def test_typed_uncertainty_fail_closed_invariants() -> None:
    with pytest.raises(CapsuleContractError, match="forbids unresolved"):
        TypedUncertainty(
            confidence=AnalysisConfidence.EXACT.value,
            unresolved_identity_fields=["cst_cid"],
            evidence_class=EvidenceClass.EXACT_STATIC_FACT.value,
        )
    with pytest.raises(CapsuleContractError, match="requires unresolved"):
        TypedUncertainty(
            confidence=AnalysisConfidence.OPAQUE.value,
            unresolved_identity_fields=(),
            evidence_class=EvidenceClass.UNKNOWN.value,
        )
    with pytest.raises(CapsuleContractError, match="incompatible evidence"):
        TypedUncertainty(
            confidence=AnalysisConfidence.CONSERVATIVE.value,
            unresolved_identity_fields=["cst_cid"],
            evidence_class=EvidenceClass.MODEL_HYPOTHESIS.value,
        )
    opaque = TypedUncertainty(
        confidence=AnalysisConfidence.OPAQUE.value,
        unresolved_identity_fields=["cst_cid", "ast_cid"],
        evidence_class=EvidenceClass.UNKNOWN.value,
    )
    assert opaque.unresolved_identity_fields == ("ast_cid", "cst_cid")
    restored = TypedUncertainty.from_dict(opaque.to_dict())
    assert restored == opaque


def test_unresolved_dispatch_and_unknown_uniqueness_cannot_be_exact() -> None:
    opaque = _uncertainty(
        confidence=AnalysisConfidence.OPAQUE.value,
        unresolved=["symbol_binding_cid"],
        evidence=EvidenceClass.UNKNOWN.value,
    )
    with pytest.raises(CapsuleContractError, match="exact confidence"):
        _callsite(dispatch_kind=DispatchKind.UNRESOLVED.value)
    unresolved = _callsite(dispatch_kind=DispatchKind.UNRESOLVED.value, typed_uncertainty=opaque)
    assert unresolved.dispatch_kind == DispatchKind.UNRESOLVED.value
    with pytest.raises(CapsuleContractError, match="exact confidence"):
        _state_owner(uniqueness=StateUniqueness.UNKNOWN.value)
    with pytest.raises(CapsuleContractError, match="exact confidence"):
        _block(block_kind=BlockKind.UNKNOWN.value)
    with pytest.raises(CapsuleContractError, match="exact confidence"):
        _registration(registration_kind=RegistrationKind.UNKNOWN.value)
    with pytest.raises(CapsuleContractError, match="exact confidence"):
        _resource(resource_kind=ResourceKind.UNKNOWN.value)


def test_kind_specific_optional_fields_and_enums() -> None:
    root_pkg = _package(parent_package_id=None)
    assert root_pkg.parent_package_id is None
    child = _package(parent_package_id=_cid("package:root"), logical_package_name="pkg.child")
    assert child.parent_package_id == _cid("package:root")
    open_resource = _resource(release_site_id=None)
    assert open_resource.release_site_id is None
    assert open_resource.resource_lifecycle_capsule_cid != _resource().resource_lifecycle_capsule_cid
    method = _method(method_kind=MethodKind.CLASSMETHOD.value, is_async=True)
    assert method.method_kind == MethodKind.CLASSMETHOD.value
    assert method.is_async is True
    with pytest.raises(CapsuleContractError, match="unsupported"):
        _method(method_kind="dunder")
    with pytest.raises(CapsuleContractError, match="boolean"):
        _function(is_async=1)  # type: ignore[arg-type]
    with pytest.raises(CapsuleContractError, match="nonnegative"):
        _function(positional_arity=-1)
    with pytest.raises(CapsuleContractError, match="duplicates"):
        _class(member_ids=[_cid("same"), _cid("same")])


def test_provider_free_exports_and_no_provider_imports() -> None:
    exports = provider_free_exports()
    assert exports == tuple(sorted(exports))
    forbidden_export_names = {
        "openai",
        "anthropic",
        "torch",
        "transformers",
        "model_output",
        "SemanticCapsuleCompiler",
        "compile_semantic_capsule",
    }
    assert forbidden_export_names.isdisjoint(set(exports))
    tree = ast.parse(CAPSULES_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "openai" not in imported
    assert "anthropic" not in imported
    assert "transformers" not in imported
    assert "torch" not in imported
    text = CAPSULES_PATH.read_text(encoding="utf-8")
    assert "class SemanticCapsuleCompiler" not in text
    assert "does not replace" in text or "does not" in text
    profile = capsule_cid_profile()
    assert profile["profile_id"] == PROFILE_ID
    assert profile["codec"] == STRUCTURED_CODEC
    assert FunctionSemanticCapsule in _CAPSULE_CLASSES
    assert set(CAPSULE_SCHEMA_REGISTRY) == {cls.SCHEMA for cls in _CAPSULE_CLASSES}
    assert "FunctionSemanticCapsule" in exports


def test_duplicate_construction_is_deterministic_across_mapping_order() -> None:
    first = _function()
    second = _function()
    assert first.function_capsule_cid == second.function_capsule_cid
    assert encode_canonical_capsule(first) == encode_canonical_capsule(second)
    shuffled_members = _class(member_ids=[_cid("m2"), _cid("m1")])
    ordered_members = _class(member_ids=[_cid("m1"), _cid("m2")])
    assert shuffled_members.class_capsule_cid == ordered_members.class_capsule_cid
    changed_root = _function(semantic_state_root_cid=_cid("root:other"))
    assert changed_root.function_capsule_cid != first.function_capsule_cid


def test_unsupported_schema_dispatch_and_encode_type_checks() -> None:
    with pytest.raises(CapsuleContractError, match="unsupported capsule schema"):
        capsule_from_dict({"schema": "not-a-capsule@1"})
    with pytest.raises(CapsuleContractError, match="mapping"):
        capsule_from_dict(["not", "a", "mapping"])  # type: ignore[arg-type]
    with pytest.raises(CapsuleContractError, match="exact bytes"):
        decode_canonical_capsule("[]")  # type: ignore[arg-type]
    with pytest.raises(CapsuleContractError, match="encode requires"):
        encode_canonical_capsule(object())  # type: ignore[arg-type]
    payload = _function().to_dict()
    payload["kind"] = CapsuleKind.METHOD.value
    with pytest.raises(CapsuleContractError, match="kind must be"):
        FunctionSemanticCapsule.from_dict(payload)


def test_freshness_and_identity_dimensions_are_first_class() -> None:
    fresh = _function()
    stale = _function(freshness=CapsuleFreshness.STALE.value)
    unknown = _function(freshness=CapsuleFreshness.UNKNOWN.value)
    assert fresh.freshness == CapsuleFreshness.FRESH.value
    assert stale.function_capsule_cid != fresh.function_capsule_cid
    assert unknown.function_capsule_cid != stale.function_capsule_cid
    for name in IDENTITY_DIMENSIONS:
        assert getattr(fresh, name) == _cid(f"id:{name}")
    assert fresh.provenance_cid
    assert fresh.semantic_state_root_cid
    with pytest.raises(CapsuleContractError, match="unsupported"):
        _function(freshness="yesterday")


def test_module_import_is_provider_free_and_side_effect_free() -> None:
    import ipfs_datasets_py.semantic_refactoring.capsules as capsules

    assert capsules.FunctionSemanticCapsule is FunctionSemanticCapsule
    assert capsules.__all__
    assert "compile_semantic_capsule" not in capsules.__all__
    assert "openai" not in capsules.__all__
    assert "llm" not in {name.lower() for name in capsules.__all__}
