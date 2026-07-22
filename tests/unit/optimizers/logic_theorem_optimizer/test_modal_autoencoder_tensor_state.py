"""Contracts for deterministic packed modal-autoencoder tensor state."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import (
    deserialize_checkpoint,
    serialize_checkpoint,
    write_checkpoint_atomic,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_state_migration import (
    load_and_pack_modal_autoencoder_checkpoint,
    pack_modal_autoencoder_state,
    unpack_modal_autoencoder_state,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_tensor_state import (
    ModalAutoencoderTensorState,
    SparseOverflowFullError,
    StableKeyRegistry,
    TensorKeyKind,
    TypedParameterKey,
    UnsafeParameterKeyError,
)


def _state() -> ModalAutoencoderTrainingState:
    state = ModalAutoencoderTrainingState(
        decoded_embeddings={"sample-17": [0.1, 0.2]},
        family_logits={"sample-17": {"deontic": 0.8}},
        feature_embedding_weights={
            "unless": [-0.5, 0.25, 0.75],
            "shall": [1.0, 0.5, -0.25],
        },
        family_embedding_weights={"deontic": [0.1, 0.9, 0.0]},
        semantic_slot_embedding_weights={"actor": [0.4, 0.3, 0.2]},
        family_semantic_slot_embedding_weights={
            "deontic||actor": [0.7, -0.1, 0.2]
        },
        family_semantic_slot_legal_ir_view_embedding_weights={
            "deontic||actor||deontic": [0.6, -0.2, 0.1]
        },
        legal_ir_view_embedding_weights={"deontic": [0.2, 0.3, 0.4]},
        feature_family_logits={
            "shall": {"deontic": 1.25, "kg": -0.25},
            "unless": {"cec": 0.5},
        },
        semantic_slot_legal_ir_view_logits={
            "actor": {"deontic": 0.875}
        },
        legal_ir_view_logits={"deontic": 0.625, "kg": -0.125},
        proof_auxiliary_head_logits={
            "obligation_family": {
                "__global__": {"mandatory": 0.75, "permission": -0.25}
            }
        },
        proof_feedback_version_fingerprint="hammer-v1",
        applied_proof_feedback_ids=["proof-1"],
    )
    state.legal_ir_view_logits["tdfol"] = 0.375
    return state


def test_stable_typed_ids_are_namespace_separated_and_order_independent() -> None:
    keys = [
        TypedParameterKey.feature("shall"),
        TypedParameterKey.family("shall"),
        TypedParameterKey.semantic_slot("actor"),
        TypedParameterKey.legal_ir_view("deontic"),
        TypedParameterKey.target("mandatory"),
        TypedParameterKey.interaction(
            "deontic||actor",
            TypedParameterKey.family("deontic"),
            TypedParameterKey.semantic_slot("actor"),
        ),
    ]
    left = StableKeyRegistry(keys)
    right = StableKeyRegistry(list(reversed(keys)))

    assert len({key.stable_id for key in keys}) == len(keys)
    assert left.to_dict() == right.to_dict()
    assert left.version_identity == right.version_identity
    assert all(left.key_for(key.stable_id) == key for key in keys)


def test_all_trainable_parameters_are_contiguous_and_sample_memory_is_not_keyed() -> None:
    packed = pack_modal_autoencoder_state(_state())

    assert packed.tables
    assert all(table.is_contiguous for table in packed.tables.values())
    assert all(tensor.flags.c_contiguous for tensor in packed.parameter_tensors.values())
    assert all(tensor.dtype == np.float64 for tensor in packed.parameter_tensors.values())
    assert "decoded_embeddings" not in packed.tables
    assert "family_logits" not in packed.tables
    assert all(
        key.value != "sample-17" for key in packed.registry.keys()
    )
    assert packed.non_parameter_state["decoded_embeddings"] == {
        "sample-17": [0.1, 0.2]
    }


def test_map_and_json_migration_are_deterministic_and_reversible(tmp_path: Path) -> None:
    state = _state()
    original = state.to_dict()
    reversed_mapping = {
        key: value for key, value in reversed(list(original.items()))
    }
    # Also reverse representative inner maps: stable IDs and tensor row order
    # must depend on key content, never Python insertion order.
    reversed_mapping["feature_embedding_weights"] = dict(
        reversed(list(original["feature_embedding_weights"].items()))
    )
    reversed_mapping["feature_family_logits"] = dict(
        reversed(list(original["feature_family_logits"].items()))
    )

    first = pack_modal_autoencoder_state(state)
    second = pack_modal_autoencoder_state(reversed_mapping)
    assert first.version_identity == second.version_identity
    assert first.registry.to_dict() == second.registry.to_dict()
    assert first.to_legacy_dict() == original
    assert second.to_legacy_dict() == original

    packed_json = ModalAutoencoderTensorState.from_json(first.to_json())
    assert packed_json.version_identity == first.version_identity
    assert packed_json.to_legacy_dict() == original
    restored = unpack_modal_autoencoder_state(packed_json)
    assert restored.to_dict() == original
    assert restored.state_revision == state.state_revision

    legacy_path = tmp_path / "legacy.json"
    state.save_json(legacy_path)
    from_path = load_and_pack_modal_autoencoder_checkpoint(legacy_path)
    assert from_path.to_legacy_dict() == original

    packed_path = tmp_path / "packed.json"
    first.save_json(packed_path)
    assert ModalAutoencoderTrainingState.load_json(packed_path).to_dict() == original
    assert ModalAutoencoderTensorState.load_json(packed_path).to_legacy_dict() == original
    assert state.to_tensor_state().to_legacy_dict() == original


def test_unknown_cpu_keys_use_bounded_overflow_without_changing_layout() -> None:
    packed = pack_modal_autoencoder_state(_state(), overflow_capacity=1)
    identity = packed.version_identity
    registry_version = packed.registry.version_identity
    revision = packed.state_revision

    packed.feature_embedding_weights["prohibition"] = [0.4, 0.5, 0.6]

    assert list(packed.feature_embedding_weights["prohibition"]) == [0.4, 0.5, 0.6]
    assert packed.feature_embedding_weights["shall"][1] == 0.5
    packed.feature_embedding_weights["shall"][1] = 0.875
    feature_table = packed.table("feature_embedding_weights")
    shall_row = feature_table._row_index[TypedParameterKey.feature("shall").stable_id]
    assert feature_table.tensor[shall_row, 1] == 0.875
    assert packed.version_identity == identity
    assert packed.registry.version_identity == registry_version
    assert packed.state_revision == revision + 2
    assert packed.table("feature_embedding_weights").overflow_size == 1

    with pytest.raises(SparseOverflowFullError):
        packed.feature_embedding_weights["permission"] = [0.1, 0.2, 0.3]
    assert packed.version_identity == identity
    assert packed.state_revision == revision + 2


def test_nested_cpu_accessor_mutates_dense_and_sparse_cells() -> None:
    packed = pack_modal_autoencoder_state(_state(), overflow_capacity=2)
    logits = packed.feature_family_logits

    logits["shall"]["deontic"] = 1.5
    logits["shall"]["tdfol"] = 0.125
    logits["permission"] = {"deontic": 0.25}

    assert logits["shall"]["deontic"] == 1.5
    assert dict(logits["shall"])["tdfol"] == 0.125
    assert dict(logits["permission"]) == {"deontic": 0.25}
    legacy = packed.to_legacy_dict()
    assert legacy["feature_family_logits"]["permission"] == {"deontic": 0.25}


def test_empty_nested_rows_remain_reversible_in_dense_and_overflow_storage() -> None:
    state = _state()
    state.feature_family_logits["empty-base"] = {}
    packed = pack_modal_autoencoder_state(state, overflow_capacity=2)

    assert dict(packed.feature_family_logits["empty-base"]) == {}
    packed.feature_family_logits["empty-late"] = {}
    assert dict(packed.feature_family_logits["empty-late"]) == {}
    assert packed.to_legacy_dict()["feature_family_logits"]["empty-base"] == {}
    assert packed.to_legacy_dict()["feature_family_logits"]["empty-late"] == {}
    assert ModalAutoencoderTensorState.from_json(packed.to_json()).to_legacy_dict() == (
        packed.to_legacy_dict()
    )


def test_proof_auxiliary_three_level_map_round_trips_as_typed_tensor() -> None:
    state = _state()
    packed = pack_modal_autoencoder_state(state)
    table = packed.table("proof_auxiliary_head_logits")

    assert table.layout == "matrix"
    assert table.row_kind is TensorKeyKind.INTERACTION
    assert table.column_kind is TensorKeyKind.TARGET
    assert packed.proof_auxiliary_head_logits["obligation_family"]["__global__"][
        "mandatory"
    ] == 0.75
    packed.proof_auxiliary_head_logits["obligation_family"]["__global__"][
        "mandatory"
    ] = 0.875
    assert packed.proof_auxiliary_head_logits["obligation_family"]["__global__"][
        "mandatory"
    ] == 0.875
    state.proof_auxiliary_head_logits["obligation_family"]["__global__"][
        "mandatory"
    ] = 0.875
    assert packed.to_legacy_dict()["proof_auxiliary_head_logits"] == (
        state.to_dict()["proof_auxiliary_head_logits"]
    )


def test_source_prose_and_sample_ids_fail_before_registry_insertion() -> None:
    state = _state()
    state.feature_embedding_weights[
        "The agency shall provide every applicant a complete written determination."
    ] = [0.1, 0.2]
    with pytest.raises(UnsafeParameterKeyError, match="source prose"):
        pack_modal_autoencoder_state(state)

    packed = pack_modal_autoencoder_state(_state())
    count = len(packed.registry)
    with pytest.raises(UnsafeParameterKeyError, match="sample/source"):
        packed.feature_embedding_weights["sample-999"] = [0.1, 0.2, 0.3]
    assert len(packed.registry) == count


def test_current_compact_checkpoint_dual_reads_into_tensor_state(tmp_path: Path) -> None:
    state = _state()
    path = tmp_path / "state.checkpoint"
    write_checkpoint_atomic(path, state)

    packed = load_and_pack_modal_autoencoder_checkpoint(path)

    assert packed.to_legacy_dict() == state.to_dict()
    assert unpack_modal_autoencoder_state(packed).state_revision == state.state_revision


def test_packed_state_compact_writes_for_old_and_tensor_readers() -> None:
    source = _state()
    packed = pack_modal_autoencoder_state(source)
    payload = serialize_checkpoint(packed)

    legacy = deserialize_checkpoint(payload)
    tensor = deserialize_checkpoint(payload, state_factory=ModalAutoencoderTensorState)

    assert legacy.state.to_dict() == source.to_dict()
    assert legacy.state.state_revision == source.state_revision
    assert tensor.state.to_legacy_dict() == source.to_dict()
    assert tensor.state.state_revision == source.state_revision


def test_packed_serialization_rejects_layout_tampering() -> None:
    packed = pack_modal_autoencoder_state(_state())
    payload = json.loads(packed.to_json())
    payload["tables"]["legal_ir_view_logits"]["row_ids"].reverse()

    with pytest.raises(ValueError, match="layout identity"):
        ModalAutoencoderTensorState.from_dict(payload)
