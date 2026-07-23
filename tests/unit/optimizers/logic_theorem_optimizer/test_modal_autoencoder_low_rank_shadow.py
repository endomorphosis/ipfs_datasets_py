"""Focused regression contracts for the existing low-rank shadow sidecar."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    ModalAutoencoderTrainingState,
)


def test_low_rank_shadow_is_non_mutating_and_excludes_sample_memory() -> None:
    state = ModalAutoencoderTrainingState(
        decoded_embeddings={"sample-memory": [9.0, 9.0]},
        family_logits={"sample-memory": {"deontic": 9.0}},
        feature_embedding_weights={
            "semantic-a": [1.0, 0.0],
            "semantic-b": [0.0, 1.0],
        },
    )
    before = state.to_dict()

    payload = state.materialize_low_rank_shadow_state(rank=2)

    assert state.to_dict() == before
    assert set(payload["embedding_maps"]) == {"feature_embedding_weights"}
    assert "sample-memory" not in str(payload)
    assert payload["shadow_mode"] is True
    assert payload["complete"] is True


def test_low_rank_shadow_round_trip_preserves_full_rank_vectors() -> None:
    state = ModalAutoencoderTrainingState(
        feature_embedding_weights={"semantic": [1.0, -2.0, 3.0]},
    )

    payload = state.materialize_low_rank_shadow_state(rank=3)
    reconstructed = state.reconstruct_low_rank_embedding_maps(payload)

    assert reconstructed["feature_embedding_weights"]["semantic"] == pytest.approx(
        [1.0, -2.0, 3.0]
    )
