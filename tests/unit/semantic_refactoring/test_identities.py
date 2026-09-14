"""Independent contract tests for SPAR-003 identity sets and golden move vectors."""

from __future__ import annotations

import ast
import copy
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any

os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "0")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS", "0")
os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    PROFILE_ID,
    STRUCTURED_CODEC,
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.semantic_refactoring.identities import (
    AGGREGATE_IDENTITY_FIELDS,
    AUTHORITY,
    AUTHORITY_OWNER,
    BINDING_AND_COMPATIBILITY_IDENTITY_FIELDS,
    EXISTING_AT1_IDENTITY_DIMENSIONS,
    FORBIDDEN_OBSERVATIONAL_FIELDS,
    GOLDEN_MOVE_VECTORS,
    IDENTITIES_CAN_AUTHORIZE_COMPLETION,
    IDENTITIES_CAN_AUTHORIZE_TRANSITION,
    IDENTITY_CID_CODEC,
    IDENTITY_CID_PROFILE,
    IDENTITY_FIELDS,
    IDENTITY_FIELD_SPECS,
    IDENTITY_MOVE_VECTOR_INTERFACE,
    IMPLEMENTATION_AND_CONTRACT_IDENTITY_FIELDS,
    IMPLEMENTATION_IDENTITY_FIELDS,
    LOCATION_INDEPENDENT_IDENTITY_FIELDS,
    LOCATION_SENSITIVE_IDENTITY_FIELDS,
    PRIMARY_IDENTITY_FAMILIES,
    SEMANTIC_ARTIFACT_IDENTITY_SET_INTERFACE,
    SEMANTIC_ARTIFACT_IDENTITY_SET_SCHEMA,
    TASK_ID,
    VECTOR_SIMILARITY_IS_AUTHORITY,
    IdentityContractError,
    IdentityDelta,
    IdentityFamily,
    IdentityMoveKind,
    IdentityMoveVector,
    IdentitySensitivity,
    SemanticArtifactIdentitySet,
    build_golden_move_vectors,
    classify_identity_field,
    compare_identity_sets,
    decode_canonical_identity_set,
    decode_canonical_move_vector,
    encode_canonical_identity_set,
    encode_canonical_move_vector,
    extract_existing_at1_identity_fields,
    fields_for_family,
    identity_cid_profile,
    is_forbidden_observational_field,
    present_existing_at1_identity_fields,
    provider_free_exports,
    require_semantic_preserving_relocation,
)


IDENTITIES_PATH = (
    Path(__file__).resolve().parents[3]
    / "ipfs_datasets_py"
    / "semantic_refactoring"
    / "identities.py"
)
INVENTORY_PATH = (
    Path(__file__).resolve().parents[4]
    / "docs"
    / "architecture"
    / "semantic_preserving_autonomous_remodularization_inventory"
    / "identity_inventory.json"
)

EXISTING_AT1_FUNCTION_SCHEMA = (
    "ipfs-datasets.semantic-refactoring.function-semantic-capsule@1"
)
EXISTING_SEMANTIC_CAPSULE_SCHEMA = (
    "ipfs-datasets.software-contracts.semantic-capsule@1"
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _identity_cids(*, prefix: str = "id") -> dict[str, str]:
    return {name: _cid(f"{prefix}:{name}") for name in IDENTITY_FIELDS}


def _identities(**overrides: str) -> SemanticArtifactIdentitySet:
    fields = _identity_cids()
    fields.update(overrides)
    return SemanticArtifactIdentitySet(**fields)


def _existing_at1_envelope(**overrides: Any) -> dict[str, Any]:
    """Closed-looking existing @1 function-capsule envelope as a plain mapping.

    SPAR-003 must read existing @1 identity fields without importing SPAR-002
    capsule types or rewriting the source mapping.
    """

    payload: dict[str, Any] = {
        "schema": EXISTING_AT1_FUNCTION_SCHEMA,
        "kind": "function",
        **{name: _cid(f"id:{name}") for name in EXISTING_AT1_IDENTITY_DIMENSIONS},
        "freshness": "fresh",
        "typed_uncertainty": {
            "schema": "ipfs-datasets.semantic-refactoring.typed-uncertainty@1",
            "confidence": "exact",
            "unresolved_identity_fields": [],
            "evidence_class": "exact_static_fact",
        },
        "logical_qualname": "pkg.mod.answer",
        "owner_module_id": _cid("module:pkg.mod"),
        "is_async": False,
        "is_generator": False,
        "positional_arity": 1,
        "function_capsule_cid": _cid("id:function_capsule_cid"),
    }
    payload.update(overrides)
    return payload


def test_predicted_symbols_and_task_identity() -> None:
    assert TASK_ID == "SPAR-003"
    assert (
        SemanticArtifactIdentitySet.INTERFACE
        == SEMANTIC_ARTIFACT_IDENTITY_SET_INTERFACE
        == "SemanticArtifactIdentitySet@1"
    )
    assert (
        IdentityMoveVector.INTERFACE
        == IDENTITY_MOVE_VECTOR_INTERFACE
        == "IdentityMoveVector@1"
    )
    assert SEMANTIC_ARTIFACT_IDENTITY_SET_SCHEMA.endswith("@1")
    tree = ast.parse(IDENTITIES_PATH.read_text(encoding="utf-8"))
    class_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }
    assert "SemanticArtifactIdentitySet" in class_names
    assert "IdentityMoveVector" in class_names
    assert "FunctionSemanticCapsule" not in class_names
    assert "SemanticCapsule" not in class_names
    assert "SemanticCapsuleCompiler" not in class_names


def test_identity_fields_match_inventory_and_existing_at1_dimensions() -> None:
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    assert tuple(inventory["identity_fields"]) == IDENTITY_FIELDS
    assert list(EXISTING_AT1_IDENTITY_DIMENSIONS) == [
        item for item in inventory["identity_fields"] if item != "function_capsule_cid"
    ]
    assert set(LOCATION_INDEPENDENT_IDENTITY_FIELDS).isdisjoint(
        LOCATION_SENSITIVE_IDENTITY_FIELDS
    )
    assert (
        set(LOCATION_INDEPENDENT_IDENTITY_FIELDS)
        | set(LOCATION_SENSITIVE_IDENTITY_FIELDS)
        | set(AGGREGATE_IDENTITY_FIELDS)
        == set(IDENTITY_FIELDS)
    )
    assert tuple(spec.name for spec in IDENTITY_FIELD_SPECS) == IDENTITY_FIELDS
    assert PRIMARY_IDENTITY_FAMILIES == (
        "implementation",
        "binding",
        "contract",
        "effect",
        "state",
        "dependency",
        "behavior",
        "validation",
    )
    assert tuple(inventory["rules"]) == (
        "CID identifies exact canonical bytes under declared codec/profile, not universal meaning",
        "move may preserve implementation/contract identity while changing binding/compatibility identity",
        "timestamps, process IDs, local paths, and model output are excluded from semantic identity",
        "accepted @1 payloads are not rewritten in place",
    )


def test_field_catalog_separates_implementation_from_binding_and_compat() -> None:
    implementation = classify_identity_field("implementation_ir_cid")
    binding = classify_identity_field("symbol_binding_cid")
    contract = classify_identity_field("interface_contract_cid")
    compatibility = classify_identity_field("public_compatibility_cid")
    assert implementation.family == IdentityFamily.IMPLEMENTATION.value
    assert implementation.sensitivity == IdentitySensitivity.LOCATION_INDEPENDENT.value
    assert binding.family == IdentityFamily.BINDING.value
    assert binding.sensitivity == IdentitySensitivity.LOCATION_SENSITIVE.value
    assert contract.sensitivity == IdentitySensitivity.LOCATION_INDEPENDENT.value
    assert compatibility.family == IdentityFamily.COMPATIBILITY.value
    assert compatibility.sensitivity == IdentitySensitivity.LOCATION_SENSITIVE.value
    assert fields_for_family(IdentityFamily.IMPLEMENTATION) == IMPLEMENTATION_IDENTITY_FIELDS
    assert IMPLEMENTATION_AND_CONTRACT_IDENTITY_FIELDS == (
        "implementation_ir_cid",
        "interface_contract_cid",
    )
    assert BINDING_AND_COMPATIBILITY_IDENTITY_FIELDS == (
        "symbol_binding_cid",
        "public_compatibility_cid",
    )
    with pytest.raises(IdentityContractError, match="observational|unknown identity field"):
        classify_identity_field("timestamp")
    with pytest.raises(IdentityContractError, match="unknown identity field"):
        classify_identity_field("not_an_identity_field")


def test_authority_flags_cannot_self_authorize() -> None:
    assert AUTHORITY == "formal semantic authority"
    assert AUTHORITY_OWNER == "ipfs_datasets_py"
    assert IDENTITIES_CAN_AUTHORIZE_COMPLETION is False
    assert IDENTITIES_CAN_AUTHORIZE_TRANSITION is False
    assert VECTOR_SIMILARITY_IS_AUTHORITY is False
    profile = identity_cid_profile()
    assert profile["profile_id"] == PROFILE_ID == IDENTITY_CID_PROFILE
    assert profile["codec"] == STRUCTURED_CODEC == IDENTITY_CID_CODEC
    assert "not universal meaning" in profile["rule"]


def test_identity_set_round_trips_and_reverifies_independent_cid() -> None:
    record = _identities()
    restored = SemanticArtifactIdentitySet.from_dict(record.to_dict())
    assert restored == record
    payload = record.identity_payload()
    assert cid_for_structured(payload) == record.identity_set_cid
    assert payload.get("identity_set_cid") is None
    exported = record.to_dict()
    assert exported["identity_set_cid"] == record.identity_set_cid
    assert set(exported) == set(SemanticArtifactIdentitySet._FIELDS)
    identity_restored = SemanticArtifactIdentitySet.from_identity_payload(payload)
    assert identity_restored.identity_set_cid == record.identity_set_cid
    grouped = record.family_identities()
    assert grouped["implementation"] == {"implementation_ir_cid": record.implementation_ir_cid}
    assert grouped["binding"] == {"symbol_binding_cid": record.symbol_binding_cid}
    assert grouped["compatibility"] == {
        "public_compatibility_cid": record.public_compatibility_cid
    }
    assert record.implementation_and_contract_identity() == {
        "implementation_ir_cid": record.implementation_ir_cid,
        "interface_contract_cid": record.interface_contract_cid,
    }
    assert record.binding_and_compatibility_identity() == {
        "symbol_binding_cid": record.symbol_binding_cid,
        "public_compatibility_cid": record.public_compatibility_cid,
    }


def test_canonical_encoding_is_strict_and_byte_stable() -> None:
    record = _identities()
    encoded = encode_canonical_identity_set(record)
    assert encoded == record.canonical_bytes()
    assert encoded == canonical_dag_json_bytes(record.identity_payload())
    decoded = decode_canonical_identity_set(encoded)
    assert decoded == record
    pretty = json.dumps(record.identity_payload(), indent=2).encode("utf-8")
    with pytest.raises(IdentityContractError, match="canonical"):
        decode_canonical_identity_set(pretty)
    with pytest.raises(IdentityContractError, match="exact bytes"):
        decode_canonical_identity_set("[]")  # type: ignore[arg-type]
    with pytest.raises(IdentityContractError, match="encode requires"):
        encode_canonical_identity_set(object())  # type: ignore[arg-type]


def test_from_dict_does_not_rewrite_accepted_payloads_in_place() -> None:
    record = _identities()
    payload = record.to_dict()
    original = copy.deepcopy(payload)
    frozen = MappingProxyType(payload)
    restored = SemanticArtifactIdentitySet.from_dict(frozen)
    assert restored == record
    assert payload == original
    forged = record.to_dict()
    forged["identity_set_cid"] = _cid("forged-aggregate")
    with pytest.raises(IdentityContractError, match="does not verify"):
        SemanticArtifactIdentitySet.from_dict(forged)
    assert (
        SemanticArtifactIdentitySet.from_dict(record.to_dict()).to_dict()
        == record.to_dict()
    )


def test_closed_records_reject_unknown_and_observational_fields() -> None:
    record = _identities()
    extra = record.to_dict()
    extra["timestamp"] = "2026-08-28T00:00:00Z"
    with pytest.raises(IdentityContractError, match="observational|exactly"):
        SemanticArtifactIdentitySet.from_dict(extra)
    missing = record.to_dict()
    missing.pop("implementation_ir_cid")
    with pytest.raises(IdentityContractError, match="exactly"):
        SemanticArtifactIdentitySet.from_dict(missing)
    for field_name in sorted(FORBIDDEN_OBSERVATIONAL_FIELDS):
        payload = record.to_dict()
        payload[field_name] = "observational"
        with pytest.raises(IdentityContractError):
            SemanticArtifactIdentitySet.from_dict(payload)
    with pytest.raises(IdentityContractError, match="unsupported"):
        SemanticArtifactIdentitySet.from_dict(
            {
                **record.to_dict(),
                "schema": SEMANTIC_ARTIFACT_IDENTITY_SET_SCHEMA.replace("@1", "@2"),
            }
        )
    assert is_forbidden_observational_field("timestamp") is True
    assert is_forbidden_observational_field("process_id") is True
    assert is_forbidden_observational_field("local_path") is True
    assert is_forbidden_observational_field("model_output") is True
    assert is_forbidden_observational_field("implementation_ir_cid") is False


def test_invalid_cids_floats_and_local_paths_are_rejected() -> None:
    with pytest.raises(IdentityContractError, match="CID"):
        _identities(source_cid="not-a-cid")
    with pytest.raises(IdentityContractError, match="CID"):
        _identities(implementation_ir_cid="/home/barberb/pkg/mod.py")
    planted = _identities()
    object.__setattr__(planted, "implementation_ir_cid", 1.5)
    with pytest.raises(IdentityContractError, match="DAG-JSON"):
        planted.identity_payload()
    object.__setattr__(planted, "implementation_ir_cid", b"bytes")
    with pytest.raises(IdentityContractError, match="DAG-JSON"):
        planted.identity_payload()
    with pytest.raises(IdentityContractError, match="filesystem path"):
        IdentityMoveVector(
            name="/tmp/move",
            kind=IdentityMoveKind.IMPLEMENTATION_EDIT,
            before=_identities(),
            after=_identities(
                implementation_ir_cid=_cid("impl:other"),
                function_capsule_cid=_cid("agg:other"),
            ),
        )


def test_relocation_preserves_implementation_and_contract_identity() -> None:
    original = _identities()
    moved = original.relocated(
        symbol_binding_cid=_cid("binding:moved"),
        public_compatibility_cid=_cid("compat:moved"),
        function_capsule_cid=_cid("capsule:moved"),
    )
    assert moved.implementation_ir_cid == original.implementation_ir_cid
    assert moved.interface_contract_cid == original.interface_contract_cid
    assert moved.effect_summary_cid == original.effect_summary_cid
    assert moved.state_footprint_cid == original.state_footprint_cid
    assert moved.dependency_slice_cid == original.dependency_slice_cid
    assert moved.behavior_summary_cid == original.behavior_summary_cid
    assert moved.validation_profile_cid == original.validation_profile_cid
    assert moved.initialization_dependency_cid == original.initialization_dependency_cid
    assert moved.symbol_binding_cid != original.symbol_binding_cid
    assert moved.public_compatibility_cid != original.public_compatibility_cid
    assert moved.function_capsule_cid != original.function_capsule_cid
    assert moved.identity_set_cid != original.identity_set_cid
    assert (
        moved.location_independent_identities()
        == original.location_independent_identities()
    )
    assert (
        moved.implementation_and_contract_identity()
        == original.implementation_and_contract_identity()
    )
    assert (
        moved.binding_and_compatibility_identity()
        != original.binding_and_compatibility_identity()
    )
    delta = require_semantic_preserving_relocation(original, moved)
    assert delta.is_semantic_preserving_relocation()
    assert set(delta.changed_fields) == {
        "symbol_binding_cid",
        "public_compatibility_cid",
        "function_capsule_cid",
    }
    with pytest.raises(IdentityContractError, match="must change symbol_binding_cid"):
        original.relocated(
            symbol_binding_cid=original.symbol_binding_cid,
            public_compatibility_cid=_cid("compat:moved"),
            function_capsule_cid=_cid("capsule:moved"),
        )


def test_implementation_edit_does_not_change_binding_or_compatibility() -> None:
    original = _identities()
    edited = original.replace(
        implementation_ir_cid=_cid("impl:edited"),
        function_capsule_cid=_cid("capsule:edited"),
    )
    delta = compare_identity_sets(original, edited)
    assert "implementation_ir_cid" in delta.changed_fields
    assert "symbol_binding_cid" in delta.preserved_fields
    assert "public_compatibility_cid" in delta.preserved_fields
    assert edited.binding_and_compatibility_identity() == (
        original.binding_and_compatibility_identity()
    )
    with pytest.raises(IdentityContractError, match="not a semantic-preserving"):
        require_semantic_preserving_relocation(original, edited)


def test_existing_at1_capsule_readers_are_preserved_without_rewrite() -> None:
    envelope = _existing_at1_envelope()
    original = copy.deepcopy(envelope)
    frozen = MappingProxyType(envelope)
    projected = SemanticArtifactIdentitySet.from_existing_at1(frozen)
    assert envelope == original
    assert projected.implementation_ir_cid == envelope["implementation_ir_cid"]
    assert projected.symbol_binding_cid == envelope["symbol_binding_cid"]
    assert projected.public_compatibility_cid == envelope["public_compatibility_cid"]
    assert projected.function_capsule_cid == envelope["function_capsule_cid"]
    identity_payload = {
        name: envelope[name] for name in EXISTING_AT1_IDENTITY_DIMENSIONS
    }
    identity_payload["schema"] = envelope["schema"]
    identity_payload["kind"] = envelope["kind"]
    identity_payload["freshness"] = envelope["freshness"]
    identity_original = copy.deepcopy(identity_payload)
    from_identity = SemanticArtifactIdentitySet.from_existing_at1(
        identity_payload,
        function_capsule_cid=envelope["function_capsule_cid"],
    )
    assert identity_payload == identity_original
    assert from_identity.function_capsule_cid == envelope["function_capsule_cid"]
    assert SemanticArtifactIdentitySet.from_dict(projected.to_dict()) == projected
    with pytest.raises(IdentityContractError, match="unsupported|exactly"):
        SemanticArtifactIdentitySet.from_dict(envelope)
    present = present_existing_at1_identity_fields(identity_payload)
    assert "function_capsule_cid" not in present
    assert present["implementation_ir_cid"] == envelope["implementation_ir_cid"]


def test_existing_semantic_capsule_at1_overlap_is_read_without_rewrite() -> None:
    payload = {
        "schema": EXISTING_SEMANTIC_CAPSULE_SCHEMA,
        "stable_symbol_id": _cid("stable"),
        "version_cid": _cid("version"),
        "source_cid": _cid("source"),
        "source_slice_path": "pkg/mod.py",
        "capsule_schema": EXISTING_SEMANTIC_CAPSULE_SCHEMA,
        "confidence": "exact",
    }
    original = copy.deepcopy(payload)
    frozen = MappingProxyType(payload)
    present = present_existing_at1_identity_fields(frozen)
    assert payload == original
    assert present["stable_symbol_id"] == payload["stable_symbol_id"]
    assert present["source_cid"] == payload["source_cid"]
    assert "source_slice_path" not in present
    assert "version_cid" not in present
    assert "function_capsule_cid" not in present


def test_existing_at1_reader_rejects_observational_metadata() -> None:
    envelope = _existing_at1_envelope()
    payload = dict(envelope)
    payload["model_output"] = "hypothesis"
    with pytest.raises(IdentityContractError, match="observational"):
        extract_existing_at1_identity_fields(payload)
    with pytest.raises(IdentityContractError, match="observational"):
        present_existing_at1_identity_fields(
            {"timestamp": "now", "source_cid": _cid("s")}
        )
    incomplete = {name: _cid(name) for name in EXISTING_AT1_IDENTITY_DIMENSIONS[:3]}
    with pytest.raises(IdentityContractError, match="missing identity fields"):
        extract_existing_at1_identity_fields(incomplete)


def test_golden_move_vectors_are_closed_deterministic_and_self_verifying() -> None:
    vectors = GOLDEN_MOVE_VECTORS
    assert vectors == build_golden_move_vectors()
    names = tuple(item.name for item in vectors)
    assert names[0] == "semantic_preserving_relocation"
    assert set(names) == {
        "semantic_preserving_relocation",
        "implementation_edit",
        "contract_edit",
        "effect_edit",
        "state_edit",
        "dependency_edit",
        "behavior_edit",
        "validation_edit",
    }
    kinds = {item.kind for item in vectors}
    assert kinds == {kind.value for kind in IdentityMoveKind}
    relocation = vectors[0]
    assert relocation.delta.is_semantic_preserving_relocation()
    assert (
        relocation.before.implementation_identity()
        == relocation.after.implementation_identity()
    )
    assert (
        relocation.before.contract_identity() == relocation.after.contract_identity()
    )
    assert (
        relocation.before.implementation_and_contract_identity()
        == relocation.after.implementation_and_contract_identity()
    )
    assert relocation.before.binding_identity() != relocation.after.binding_identity()
    assert (
        relocation.before.compatibility_identity()
        != relocation.after.compatibility_identity()
    )
    for vector in vectors:
        restored = IdentityMoveVector.from_dict(vector.to_dict())
        assert restored == vector
        assert restored.move_vector_cid == cid_for_structured(vector.identity_payload())
        encoded = encode_canonical_move_vector(vector)
        assert decode_canonical_move_vector(encoded) == vector
        assert vector.after.function_capsule_cid != vector.before.function_capsule_cid


def test_golden_family_edits_preserve_binding_and_compatibility() -> None:
    by_name = {item.name: item for item in GOLDEN_MOVE_VECTORS}
    for name in (
        "implementation_edit",
        "contract_edit",
        "effect_edit",
        "state_edit",
        "dependency_edit",
        "behavior_edit",
        "validation_edit",
    ):
        vector = by_name[name]
        assert vector.before.symbol_binding_cid == vector.after.symbol_binding_cid
        assert (
            vector.before.public_compatibility_cid
            == vector.after.public_compatibility_cid
        )
        family = name.removesuffix("_edit")
        assert family in vector.delta.changed_families
        assert "binding" not in vector.delta.changed_families
        assert "compatibility" not in vector.delta.changed_families


def test_move_vector_rejects_mismatched_kind_and_forged_cid() -> None:
    original = _identities()
    relocated = original.relocated(
        symbol_binding_cid=_cid("binding:moved"),
        public_compatibility_cid=_cid("compat:moved"),
        function_capsule_cid=_cid("capsule:moved"),
    )
    with pytest.raises(IdentityContractError, match="must change families"):
        IdentityMoveVector(
            name="not-an-implementation-edit",
            kind=IdentityMoveKind.IMPLEMENTATION_EDIT,
            before=original,
            after=relocated,
        )
    vector = IdentityMoveVector(
        name="semantic_preserving_relocation",
        kind=IdentityMoveKind.SEMANTIC_PRESERVING_RELOCATION,
        before=original,
        after=relocated,
    )
    forged = vector.to_dict()
    forged["move_vector_cid"] = _cid("forged-move")
    with pytest.raises(IdentityContractError, match="does not verify"):
        IdentityMoveVector.from_dict(forged)
    mutated = vector.to_dict()
    mutated["preserved_fields"] = list(IDENTITY_FIELDS)
    mutated["changed_fields"] = []
    with pytest.raises(IdentityContractError):
        IdentityMoveVector.from_dict(mutated)


def test_identity_delta_is_closed_and_partitioned() -> None:
    original = _identities()
    moved = original.relocated(
        symbol_binding_cid=_cid("binding:moved"),
        public_compatibility_cid=_cid("compat:moved"),
        function_capsule_cid=_cid("capsule:moved"),
    )
    delta = compare_identity_sets(original, moved)
    restored = IdentityDelta.from_dict(delta.to_dict())
    assert restored == delta
    with pytest.raises(IdentityContractError, match="partitioned"):
        IdentityDelta(
            preserved_fields=IDENTITY_FIELDS,
            changed_fields=("implementation_ir_cid",),
        )
    with pytest.raises(IdentityContractError, match="cover every"):
        IdentityDelta(preserved_fields=("source_cid",), changed_fields=("cst_cid",))
    forged = delta.to_dict()
    forged["delta_cid"] = _cid("forged-delta")
    with pytest.raises(IdentityContractError, match="does not verify"):
        IdentityDelta.from_dict(forged)


def test_records_are_frozen_and_duplicate_construction_is_deterministic() -> None:
    first = _identities()
    second = _identities()
    assert first.identity_set_cid == second.identity_set_cid
    assert encode_canonical_identity_set(first) == encode_canonical_identity_set(second)
    with pytest.raises(Exception):
        first.implementation_ir_cid = _cid("mutated")  # type: ignore[misc]
    with pytest.raises(Exception):
        GOLDEN_MOVE_VECTORS[0].name = "mutated"  # type: ignore[misc]
    changed = first.replace(semantic_state_root_cid=_cid("root:other"))
    assert changed.identity_set_cid != first.identity_set_cid
    assert changed.implementation_ir_cid == first.implementation_ir_cid
    with pytest.raises(IdentityContractError, match="observational"):
        first.replace(timestamp="now")  # type: ignore[arg-type]


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
        "FunctionSemanticCapsule",
    }
    assert forbidden_export_names.isdisjoint(set(exports))
    tree = ast.parse(IDENTITIES_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
            imported_modules.add(node.module)
    assert "openai" not in imported
    assert "anthropic" not in imported
    assert "transformers" not in imported
    assert "torch" not in imported
    assert "ipfs_datasets_py.semantic_refactoring.capsules" not in imported_modules
    assert "ipfs_datasets_py.logic.software_contracts.semantic_state" not in (
        imported_modules
    )
    assert "SemanticArtifactIdentitySet" in exports
    assert "GOLDEN_MOVE_VECTORS" in exports
    assert "is_forbidden_observational_field" in exports
    text = IDENTITIES_PATH.read_text(encoding="utf-8")
    assert "does not replace" in text
    assert "accepted" in text.lower() and "rewritten" in text.lower()


def test_module_import_is_provider_free_and_side_effect_free() -> None:
    import ipfs_datasets_py.semantic_refactoring.identities as identities

    assert identities.SemanticArtifactIdentitySet is SemanticArtifactIdentitySet
    assert identities.__all__
    assert "compile_semantic_capsule" not in identities.__all__
    assert "openai" not in identities.__all__
    assert "llm" not in {name.lower() for name in identities.__all__}
    assert identities.GOLDEN_MOVE_VECTORS[0].kind == (
        IdentityMoveKind.SEMANTIC_PRESERVING_RELOCATION.value
    )
    assert identities.IDENTITIES_CAN_AUTHORIZE_COMPLETION is False
    assert identities.VECTOR_SIMILARITY_IS_AUTHORITY is False
