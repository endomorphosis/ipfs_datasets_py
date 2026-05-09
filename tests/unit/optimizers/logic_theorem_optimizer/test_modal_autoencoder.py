"""Tests for modal autoencoder baseline metrics."""

from __future__ import annotations

import math

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    ModalAutoencoderBaseline,
    ModalAutoencoderTrainingState,
    cosine_loss,
    cosine_similarity,
    cross_entropy_loss,
    frame_ranking_loss,
    mse_loss,
    symbolic_validity_penalty,
)


def test_embedding_loss_helpers() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_loss([1.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)
    assert mse_loss([1.0, 2.0], [1.0, 4.0]) == pytest.approx(2.0)
    assert cross_entropy_loss({"deontic": 0.25}, "deontic") == pytest.approx(-math.log(0.25))


def test_loss_helpers_reject_vector_length_mismatch() -> None:
    with pytest.raises(ValueError, match="same length"):
        cosine_similarity([1.0], [1.0, 2.0])


def test_modal_autoencoder_baseline_reports_fixture_losses() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice within 30 days.",
    )
    baseline = ModalAutoencoderBaseline()

    evaluation = baseline.evaluate([sample])

    assert evaluation.sample_count == 1
    assert evaluation.embedding_cosine_similarity == pytest.approx(1.0)
    assert evaluation.cosine_loss == pytest.approx(0.0)
    assert evaluation.reconstruction_loss == pytest.approx(0.0)
    assert evaluation.cross_entropy_loss >= 0.0
    assert evaluation.frame_ranking_loss == pytest.approx(0.0)
    assert evaluation.symbolic_validity_penalty == pytest.approx(0.0)
    assert sample.sample_id in evaluation.decoded_embeddings
    assert evaluation.to_dict()["sample_count"] == 1


def test_modal_autoencoder_empty_dataset_returns_zero_metrics() -> None:
    evaluation = ModalAutoencoderBaseline().evaluate([])

    assert evaluation.sample_count == 0
    assert evaluation.decoded_embeddings == {}


def test_adaptive_autoencoder_todo_updates_lower_ce_and_increase_cosine() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice within 30 days.",
    )
    autoencoder = AdaptiveModalAutoencoder()
    before = autoencoder.evaluate([sample])
    todo = type(
        "Todo",
        (),
        {
            "action": "improve_modal_family_classifier",
            "loss_name": "cross_entropy_loss",
            "sample_ids": [sample.sample_id],
            "todo_id": "ce-1",
        },
    )()
    reconstruction_todo = type(
        "Todo",
        (),
        {
            "action": "improve_encoder_decoder_reconstruction",
            "loss_name": "cosine_loss",
            "sample_ids": [sample.sample_id],
            "todo_id": "cos-1",
        },
    )()

    autoencoder.apply_todos(
        [todo, reconstruction_todo],
        {sample.sample_id: sample},
        learning_rate=0.5,
    )
    after = autoencoder.evaluate([sample])

    assert after.cross_entropy_loss < before.cross_entropy_loss
    assert after.embedding_cosine_similarity > before.embedding_cosine_similarity
    assert autoencoder.state.applied_todo_ids == ["ce-1", "cos-1"]


def test_feature_family_updates_generalize_without_sample_id_leakage() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must make records promptly available.",
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency must make notices promptly available.",
    )
    autoencoder = AdaptiveModalAutoencoder()
    before = autoencoder.evaluate([validation])
    todo = type(
        "Todo",
        (),
        {
            "action": "improve_modal_family_classifier",
            "loss_name": "cross_entropy_loss",
            "sample_ids": [train.sample_id],
            "todo_id": "ce-feature-1",
        },
    )()

    autoencoder.apply_todos([todo], {train.sample_id: train}, learning_rate=0.5)
    after = autoencoder.evaluate([validation])

    assert validation.sample_id not in autoencoder.state.family_logits
    assert autoencoder.state.feature_family_logits
    assert after.cross_entropy_loss < before.cross_entropy_loss


def test_adaptive_autoencoder_state_roundtrip(tmp_path) -> None:
    state = ModalAutoencoderTrainingState(
        decoded_embeddings={"sample": [0.1, 0.2]},
        family_logits={"sample": {"deontic": 1.0}},
        feature_embedding_weights={"token:agency": [0.01, -0.01]},
        feature_family_logits={"modal-family:deontic": {"deontic": 0.2}},
        applied_todo_ids=["todo-1"],
    )
    path = tmp_path / "state.json"
    state.save_json(path)

    loaded = ModalAutoencoderTrainingState.from_dict(state.to_dict())
    loaded_from_file = ModalAutoencoderTrainingState.load_json(path)

    assert loaded.to_dict() == state.to_dict()
    assert loaded_from_file.to_dict() == state.to_dict()


def test_frame_and_symbolic_penalties_for_valid_sample() -> None:
    sample = build_us_code_sample(
        title="42",
        section="1437f",
        text="The tenant may request a housing voucher accommodation.",
    )

    assert frame_ranking_loss(sample) == pytest.approx(0.0)
    assert symbolic_validity_penalty(sample) == pytest.approx(0.0)
