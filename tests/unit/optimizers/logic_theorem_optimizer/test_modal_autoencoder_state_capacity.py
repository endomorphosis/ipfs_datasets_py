"""Tests for deterministic global capacity control of reusable sparse state."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    MODAL_AUTOENCODER_GENERALIZABLE_CAPACITY_SCHEMA_VERSION,
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import (
    deserialize_checkpoint,
    serialize_checkpoint,
)


def test_capacity_compaction_keeps_coupled_heads_aligned_and_sample_memory() -> None:
    state = ModalAutoencoderTrainingState(
        decoded_embeddings={"sample": [0.25, 0.75]},
        family_logits={"sample": {"deontic": 1.0}},
        feature_embedding_weights={
            "feature:bias": [0.0],
            "high": [4.0],
            "low": [1.0],
            "middle": [3.0],
        },
        feature_family_logits={
            "feature:bias": {"deontic": 0.0},
            "high": {"deontic": 4.0},
            "low": {"deontic": 1.0},
            "middle": {"deontic": 3.0},
        },
        feature_legal_ir_view_logits={
            "feature:bias": {"deontic.ir": 0.0},
            "high": {"deontic.ir": 4.0},
            "low": {"deontic.ir": 1.0},
            "middle": {"deontic.ir": 3.0},
        },
    )

    assert state.generalizable_capacity_exceeded(3) is True
    report = state.compact_generalizable_capacity(3)

    expected = {"feature:bias", "high", "middle"}
    assert set(state.feature_embedding_weights) == expected
    assert set(state.feature_family_logits) == expected
    assert set(state.feature_legal_ir_view_logits) == expected
    assert state.decoded_embeddings == {"sample": [0.25, 0.75]}
    assert state.family_logits == {"sample": {"deontic": 1.0}}
    assert report["schema_version"] == (
        MODAL_AUTOENCODER_GENERALIZABLE_CAPACITY_SCHEMA_VERSION
    )
    assert report["compacted"] is True
    assert report["groups"]["feature"]["unique_keys_dropped"] == 1
    assert report["groups"]["feature"]["protected_keys_after"] == 1
    assert 0.0 < report["retained_signal_ratio"] <= 1.0
    assert state.generalizable_capacity_exceeded(3) is False


def test_capacity_compaction_aggregates_signal_and_breaks_ties_lexically() -> None:
    state = ModalAutoencoderTrainingState(
        decompiler_plan_embedding_weights={
            "alpha": [1.0],
            "bravo": [1.0],
            "charlie": [1.0],
        },
        decompiler_plan_family_logits={
            "alpha": {"deontic": 1.0},
            "bravo": {"deontic": 1.0},
            "charlie": {"deontic": 1.0},
        },
        decompiler_plan_legal_ir_view_logits={
            "alpha": {"decompiler": 1.0},
            "bravo": {"decompiler": 1.0},
            "charlie": {"decompiler": 1.0},
        },
    )

    state.compact_generalizable_capacity(2)

    assert set(state.decompiler_plan_embedding_weights) == {"alpha", "bravo"}
    assert set(state.decompiler_plan_family_logits) == {"alpha", "bravo"}
    assert set(state.decompiler_plan_legal_ir_view_logits) == {"alpha", "bravo"}


def test_capacity_compaction_is_idempotent_when_state_is_within_limit() -> None:
    state = ModalAutoencoderTrainingState(
        logic_signature_embedding_weights={"signature": [1.0, -2.0]},
        logic_signature_family_logits={"signature": {"deontic": 0.5}},
    )
    revision = state.state_revision

    first = state.compact_generalizable_capacity(2)
    second = state.compact_generalizable_capacity(2)

    assert first["compacted"] is False
    assert second["compacted"] is False
    assert state.state_revision == revision
    assert first["retained_signal_ratio"] == pytest.approx(1.0)


def test_capacity_compacted_state_round_trips_through_compact_checkpoint() -> None:
    state = ModalAutoencoderTrainingState(
        semantic_slot_embedding_weights={
            f"slot-{index}": [float(index)] for index in range(6)
        },
        semantic_slot_family_logits={
            f"slot-{index}": {"deontic": float(index)} for index in range(6)
        },
    )
    state.compact_generalizable_capacity(3)

    restored = deserialize_checkpoint(serialize_checkpoint(state)).state

    assert restored.to_dict() == state.to_dict()
    assert restored.generalizable_capacity_exceeded(3) is False


def test_capacity_control_rejects_nonpositive_limit() -> None:
    state = ModalAutoencoderTrainingState()

    with pytest.raises(ValueError, match="positive"):
        state.generalizable_capacity_exceeded(0)
    with pytest.raises(ValueError, match="positive"):
        state.compact_generalizable_capacity(0)
