"""Tests for modal autoencoder baseline metrics."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    ModalAutoencoderBaseline,
    ModalAutoencoderTrainingState,
    cosine_loss,
    cosine_similarity,
    cross_entropy_distribution_loss,
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
    assert cross_entropy_distribution_loss(
        {"deontic": 0.25, "temporal": 0.75},
        {"deontic": 0.5, "temporal": 0.5},
    ) == pytest.approx(0.5 * -math.log(0.25) + 0.5 * -math.log(0.75))


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


def test_adaptive_autoencoder_cross_entropy_uses_mixed_family_targets() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice within 30 days.",
    )
    first_formula = sample.modal_ir.formulas[0]
    temporal_formula = replace(
        first_formula,
        formula_id=f"{first_formula.formula_id}-temporal",
        operator=replace(
            first_formula.operator,
            family="temporal",
            system="LTL",
            symbol="G",
            label="always",
        ),
    )
    mixed_sample = replace(
        sample,
        modal_ir=replace(sample.modal_ir, formulas=[first_formula, temporal_formula]),
    )
    autoencoder = AdaptiveModalAutoencoder(
        state=ModalAutoencoderTrainingState(
            family_logits={
                mixed_sample.sample_id: {
                    "deontic": 4.0,
                    "temporal": -4.0,
                }
            }
        )
    )

    evaluation = autoencoder.evaluate([mixed_sample])
    predicted = autoencoder._family_distribution(mixed_sample)

    assert evaluation.cross_entropy_loss == pytest.approx(
        cross_entropy_distribution_loss(
            predicted,
            {"deontic": 0.5, "temporal": 0.5},
        )
    )
    assert evaluation.cross_entropy_loss > cross_entropy_loss(predicted, "deontic")


def test_adaptive_autoencoder_introspection_explains_feature_level_decisions() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice within 30 days.",
    )
    autoencoder = AdaptiveModalAutoencoder()
    todos = [
        type(
            "Todo",
            (),
            {
                "action": "improve_modal_family_classifier",
                "loss_name": "cross_entropy_loss",
                "sample_ids": [sample.sample_id],
                "todo_id": "ce-introspection",
            },
        )(),
        type(
            "Todo",
            (),
            {
                "action": "improve_encoder_decoder_reconstruction",
                "loss_name": "cosine_loss",
                "sample_ids": [sample.sample_id],
                "todo_id": "cos-introspection",
            },
        )(),
    ]
    autoencoder.apply_todos(todos, {sample.sample_id: sample}, learning_rate=0.5)

    introspection = autoencoder.introspect_sample(sample)
    data = introspection.to_dict()

    assert introspection.sample_id == sample.sample_id
    assert introspection.sample_memory_used is False
    assert introspection.target_family == "deontic"
    assert introspection.top_family_contributions
    assert introspection.top_embedding_contributions
    assert all(
        contribution.contribution_type != "sample_family_logit"
        for contribution in introspection.top_family_contributions
    )
    assert "refine_typed_ir_or_decompiler_slots" in introspection.synthesis_focus
    assert data["top_family_contributions"][0]["feature"]


def test_feature_family_updates_are_stored_without_sample_id_leakage() -> None:
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
    assert after.cross_entropy_loss == pytest.approx(before.cross_entropy_loss)


def test_feature_family_updates_can_be_opted_into_for_experiments() -> None:
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
    autoencoder = AdaptiveModalAutoencoder(feature_family_logit_scale=1.0)
    before = autoencoder.evaluate([validation])
    todo = type(
        "Todo",
        (),
        {
            "action": "improve_modal_family_classifier",
            "loss_name": "cross_entropy_loss",
            "sample_ids": [train.sample_id],
            "todo_id": "ce-feature-opt-in",
        },
    )()

    autoencoder.apply_todos([todo], {train.sample_id: train}, learning_rate=0.5)
    after = autoencoder.evaluate([validation])

    assert validation.sample_id not in autoencoder.state.family_logits
    assert autoencoder.state.feature_family_logits
    assert after.cross_entropy_loss < before.cross_entropy_loss


def test_adaptive_autoencoder_skips_program_synthesis_todos() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice within 30 days.",
    )
    autoencoder = AdaptiveModalAutoencoder()
    state_before = autoencoder.state.to_dict()
    todo = type(
        "Todo",
        (),
        {
            "action": "add_deterministic_parser_rule",
            "loss_name": "parser_formula_count",
            "sample_ids": [sample.sample_id],
            "todo_id": "program-1",
        },
    )()

    report = autoencoder.apply_todo(
        todo,
        {sample.sample_id: sample},
        learning_rate=0.5,
    )

    assert report["skipped"] is True
    assert report["changed"] == []
    assert autoencoder.state.to_dict() == state_before


def test_clean_evaluation_ignores_sample_specific_memory() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice within 30 days.",
    )
    autoencoder = AdaptiveModalAutoencoder()
    memory_before = autoencoder.evaluate([sample], use_sample_memory=False)
    autoencoder.state.decoded_embeddings[sample.sample_id] = list(sample.embedding_vector)
    memorized = autoencoder.evaluate([sample])
    clean = autoencoder.evaluate([sample], use_sample_memory=False)

    assert sample.sample_id in autoencoder.state.decoded_embeddings
    assert memorized.embedding_cosine_similarity > memory_before.embedding_cosine_similarity
    assert clean.embedding_cosine_similarity == pytest.approx(
        memory_before.embedding_cosine_similarity
    )


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


def test_generalizable_state_copy_drops_sample_specific_memory() -> None:
    state = ModalAutoencoderTrainingState(
        decoded_embeddings={"sample": [0.1, 0.2]},
        family_logits={"sample": {"deontic": 1.0}},
        feature_embedding_weights={"token:agency": [0.01, -0.01]},
        feature_family_logits={"modal-family:deontic": {"deontic": 0.2}},
        applied_todo_ids=["todo-1"],
    )

    generalizable = state.generalizable_copy()

    assert generalizable.decoded_embeddings == {}
    assert generalizable.family_logits == {}
    assert generalizable.applied_todo_ids == []
    assert generalizable.feature_embedding_weights == state.feature_embedding_weights
    assert generalizable.feature_family_logits == state.feature_family_logits


def test_average_generalizable_state_reuses_prior_feature_learning() -> None:
    first = ModalAutoencoderTrainingState(
        decoded_embeddings={"sample-a": [1.0, 1.0]},
        family_logits={"sample-a": {"deontic": 4.0}},
        feature_embedding_weights={"token:agency": [0.2, -0.2]},
        feature_family_logits={"modal-family:deontic": {"deontic": 0.6}},
    )
    second = ModalAutoencoderTrainingState(
        decoded_embeddings={"sample-b": [2.0, 2.0]},
        family_logits={"sample-b": {"temporal": 4.0}},
        feature_embedding_weights={"token:agency": [0.4, -0.4]},
        feature_family_logits={"modal-family:deontic": {"deontic": 0.2}},
    )

    averaged = ModalAutoencoderTrainingState.average_generalizable([first, second])

    assert averaged.decoded_embeddings == {}
    assert averaged.family_logits == {}
    assert averaged.feature_embedding_weights["token:agency"] == pytest.approx([0.3, -0.3])
    assert averaged.feature_family_logits["modal-family:deontic"]["deontic"] == pytest.approx(0.4)


def test_frame_and_symbolic_penalties_for_valid_sample() -> None:
    sample = build_us_code_sample(
        title="42",
        section="1437f",
        text="The tenant may request a housing voucher accommodation.",
    )

    assert frame_ranking_loss(sample) == pytest.approx(0.0)
    assert symbolic_validity_penalty(sample) == pytest.approx(0.0)
