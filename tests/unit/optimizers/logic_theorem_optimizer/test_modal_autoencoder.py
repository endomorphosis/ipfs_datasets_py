"""Tests for modal autoencoder baseline metrics."""

from __future__ import annotations

import math
from dataclasses import replace
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    AutoencoderEvaluation,
    CodexCallCache,
    CodexCallGateConfig,
    ModalAutoencoderBaseline,
    ModalAutoencoderTrainingState,
    ProverCompilationSignal,
    cosine_loss,
    cosine_similarity,
    cross_entropy_excess_distribution_loss,
    cross_entropy_distribution_loss,
    cross_entropy_loss,
    distribution_entropy_loss,
    evaluate_modal_prover_compilation,
    frame_ranking_loss,
    mse_loss,
    symbolic_validity_penalty,
    _evaluation_improved_for_training,
    _legal_ir_target_cache_key,
    _source_decompiled_text_losses_from_targets,
)


def _vector_norm(values: list[float]) -> float:
    return math.sqrt(sum(float(value) * float(value) for value in values))


def _max_abs(values: dict[str, float]) -> float:
    return max(abs(float(value)) for value in values.values())


def test_embedding_loss_helpers() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_loss([1.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)
    assert mse_loss([1.0, 2.0], [1.0, 4.0]) == pytest.approx(2.0)
    assert cross_entropy_loss({"deontic": 0.25}, "deontic") == pytest.approx(-math.log(0.25))
    assert cross_entropy_distribution_loss(
        {"deontic": 0.25, "temporal": 0.75},
        {"deontic": 0.5, "temporal": 0.5},
    ) == pytest.approx(0.5 * -math.log(0.25) + 0.5 * -math.log(0.75))
    assert distribution_entropy_loss({"deontic": 0.5, "temporal": 0.5}) == pytest.approx(
        math.log(2.0)
    )
    assert cross_entropy_excess_distribution_loss(
        {"deontic": 0.5, "temporal": 0.5},
        {"deontic": 0.5, "temporal": 0.5},
    ) == pytest.approx(0.0)


def test_loss_helpers_reject_vector_length_mismatch() -> None:
    with pytest.raises(ValueError, match="same length"):
        cosine_similarity([1.0], [1.0, 2.0])


def test_source_decompiled_loss_normalization_prefers_same_space_cosine() -> None:
    losses = _source_decompiled_text_losses_from_targets(
        {
            "cosine_similarity": 0.82,
            "raw_source_embedding_cosine_similarity": -0.35,
            "structural_text_reconstruction_loss": 0.27,
        }
    )

    assert losses["source_decompiled_text_embedding_cosine_loss"] == pytest.approx(
        0.18
    )
    assert losses["source_decompiled_text_token_loss"] == pytest.approx(0.27)

    explicit_losses = _source_decompiled_text_losses_from_targets(
        {
            "source_decompiled_text_embedding_cosine_loss": 0.11,
            "cosine_similarity": 0.82,
            "raw_source_embedding_cosine_similarity": -0.35,
        }
    )

    assert explicit_losses["source_decompiled_text_embedding_cosine_loss"] == (
        pytest.approx(0.11)
    )


def test_modal_autoencoder_baseline_reports_fixture_losses() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice.",
    )
    baseline = ModalAutoencoderBaseline()

    evaluation = baseline.evaluate([sample])

    assert evaluation.sample_count == 1
    assert evaluation.embedding_cosine_similarity == pytest.approx(1.0)
    assert evaluation.cosine_loss == pytest.approx(0.0)
    assert evaluation.reconstruction_loss == pytest.approx(0.0)
    assert evaluation.cross_entropy_loss >= 0.0
    assert evaluation.cross_entropy_entropy_loss >= 0.0
    assert evaluation.cross_entropy_excess_loss >= 0.0
    assert evaluation.frame_ranking_loss == pytest.approx(0.0)
    assert evaluation.symbolic_validity_penalty == pytest.approx(0.0)
    assert sample.sample_id in evaluation.decoded_embeddings
    assert evaluation.to_dict()["sample_count"] == 1


def test_autoencoder_evaluation_carries_legal_ir_training_target_losses() -> None:
    from ipfs_datasets_py.logic.bridge import evaluate_legal_ir_multiview

    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )
    target = evaluate_legal_ir_multiview(
        sample.text,
        bridge_names=("deontic_norms", "fol_tdfol"),
        document_id=sample.sample_id,
        citation=sample.citation,
        source=sample.source,
        source_embedding=sample.embedding_vector,
    ).training_target()
    autoencoder = AdaptiveModalAutoencoder()

    evaluation = autoencoder.evaluate(
        [sample],
        legal_ir_targets={sample.sample_id: target},
    )

    assert evaluation.legal_ir_target_count == 1
    assert "legal_ir_multiview_total_loss" in evaluation.legal_ir_losses
    assert evaluation.legal_ir_losses["legal_ir_multiview_total_loss"] >= 0.0
    assert evaluation.legal_ir_losses["legal_ir_multiview_view_coverage_loss"] == 0.0
    assert evaluation.legal_ir_losses["legal_ir_view_cross_entropy_loss"] > 0.0
    assert evaluation.legal_ir_losses["legal_ir_view_entropy_loss"] >= 0.0
    assert evaluation.legal_ir_losses["legal_ir_view_cross_entropy_excess_loss"] >= 0.0
    assert evaluation.legal_ir_target_hashes[sample.sample_id] == target.document.canonical_hash()
    assert evaluation.legal_ir_view_distribution
    assert evaluation.legal_ir_predicted_view_distribution
    payload = evaluation.to_dict()
    assert payload["legal_ir_losses"]["legal_ir_multiview_total_loss"] >= 0.0
    assert payload["legal_ir_losses"]["legal_ir_view_cross_entropy_loss"] > 0.0
    assert payload["cross_entropy_excess_loss"] >= 0.0
    assert payload["legal_ir_predicted_view_distribution"]
    introspection = autoencoder.introspect_sample(sample).to_dict()
    assert introspection["legal_ir_losses"]["legal_ir_multiview_total_loss"] >= 0.0
    assert introspection["legal_ir_view_cross_entropy_loss"] > 0.0
    assert introspection["legal_ir_view_entropy_loss"] >= 0.0
    assert introspection["legal_ir_view_cross_entropy_excess_loss"] >= 0.0


def test_adaptive_autoencoder_reports_legal_ir_view_family_losses() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "The agency may not disclose protected records except as authorized "
            "before the permit hearing."
        ),
    )
    target = SimpleNamespace(
        losses={},
        view_distribution={
            "deontic.ir": 0.20,
            "modal.frame_logic": 0.15,
            "TDFOL.prover": 0.20,
            "knowledge_graphs.neo4j_compat": 0.15,
            "CEC.native": 0.15,
            "external_provers.router": 0.15,
        },
        document=SimpleNamespace(canonical_hash=lambda: "family-target-hash"),
    )
    autoencoder = AdaptiveModalAutoencoder()

    evaluation = autoencoder.evaluate(
        [sample],
        legal_ir_targets={sample.sample_id: target},
    )

    losses = evaluation.legal_ir_losses
    assert losses["legal_ir_view_family_cross_entropy_loss"] > 0.0
    assert losses["legal_ir_view_family_cross_entropy_excess_loss"] >= 0.0
    assert 0.0 <= losses["legal_ir_view_family_cosine_gap_loss"] <= 1.0
    for family in ("deontic", "frame_logic", "tdfol", "kg", "cec", "prover"):
        assert f"legal_ir_view_family_{family}_cross_entropy_loss" in losses
        assert f"legal_ir_view_family_{family}_cross_entropy_excess_loss" in losses
        assert f"legal_ir_view_family_{family}_cosine_gap_loss" in losses
    introspection = autoencoder.introspect_sample(sample).to_dict()
    assert (
        introspection["legal_ir_losses"]["legal_ir_view_family_deontic_cosine_gap_loss"]
        >= 0.0
    )


def test_legal_ir_target_cache_key_uses_source_text_not_citation_identity() -> None:
    text = "The agency shall publish notice before the permit takes effect."
    first = build_us_code_sample(title="5", section="552", text=text)
    second = build_us_code_sample(title="12", section="1841", text=text)
    third = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may publish notice before the permit takes effect.",
    )

    first_key = _legal_ir_target_cache_key(
        first,
        bridge_names=("deontic_norms", "fol_tdfol"),
        evaluate_provers=False,
    )
    second_key = _legal_ir_target_cache_key(
        second,
        bridge_names=("deontic_norms", "fol_tdfol"),
        evaluate_provers=False,
    )
    third_key = _legal_ir_target_cache_key(
        third,
        bridge_names=("deontic_norms", "fol_tdfol"),
        evaluate_provers=False,
    )

    assert first.sample_id != second.sample_id
    assert first_key == second_key
    assert first_key != third_key


def test_adaptive_autoencoder_sgd_lowers_legal_ir_view_cross_entropy() -> None:
    from ipfs_datasets_py.logic.bridge import evaluate_legal_ir_multiview

    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )
    target = evaluate_legal_ir_multiview(
        sample.text,
        bridge_names=("deontic_norms", "fol_tdfol"),
        document_id=sample.sample_id,
        citation=sample.citation,
        source=sample.source,
        source_embedding=sample.embedding_vector,
    ).training_target()
    autoencoder = AdaptiveModalAutoencoder()
    before = autoencoder.evaluate(
        [sample],
        legal_ir_targets={sample.sample_id: target},
    )
    todo = type(
        "Todo",
        (),
        {
            "action": "improve_legal_ir_view_distribution",
            "loss_name": "legal_ir_view_cross_entropy_loss",
            "sample_ids": [sample.sample_id],
            "todo_id": "legal-ir-view-ce",
        },
    )()

    report = autoencoder.apply_todo(
        todo,
        {sample.sample_id: sample},
        learning_rate=0.5,
    )
    after = autoencoder.evaluate(
        [sample],
        legal_ir_targets={sample.sample_id: target},
    )
    introspection = autoencoder.introspect_sample(sample)

    assert report["changed"] == ["legal_ir_view_logits"]
    assert (
        after.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
        < before.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
    )
    assert "repair_multiview_legal_ir_loss" in introspection.synthesis_focus
    assert introspection.legal_ir_view_distribution


def test_generalizable_projection_lowers_legal_ir_view_ce_on_holdout() -> None:
    from ipfs_datasets_py.logic.bridge import evaluate_legal_ir_multiview

    train_sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )
    validation_sample = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall publish notice before a rule takes effect.",
    )
    targets = {}
    for sample in (train_sample, validation_sample):
        targets[sample.sample_id] = evaluate_legal_ir_multiview(
            sample.text,
            bridge_names=("deontic_norms", "fol_tdfol"),
            document_id=sample.sample_id,
            citation=sample.citation,
            source=sample.source,
            source_embedding=sample.embedding_vector,
        ).training_target()
    autoencoder = AdaptiveModalAutoencoder()
    before = autoencoder.evaluate(
        [validation_sample],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    report = autoencoder.train_generalizable_projection(
        [train_sample],
        validation_samples=[validation_sample],
        legal_ir_targets=targets,
        epochs=5,
        learning_rate=0.5,
    )
    after = autoencoder.evaluate(
        [validation_sample],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    assert report["accepted_epochs"] >= 1
    assert report["epoch_reports"][0]["selected_update"] == "legal_ir_view_logits"
    assert any(
        candidate["update"] == "combined"
        and candidate["pareto_regressions"]
        for candidate in report["epoch_reports"][0]["candidate_reports"]
    )
    assert (
        after.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
        < before.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
    )
    assert autoencoder.state.family_logits == {}
    assert autoencoder.state.feature_legal_ir_view_logits


def test_generalizable_projection_reports_progress_and_attempt_cap() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )
    autoencoder = AdaptiveModalAutoencoder()
    progress: list[dict[str, object]] = []

    report = autoencoder.train_generalizable_projection(
        [sample],
        epochs=1,
        learning_rate=0.1,
        max_line_search_attempts=1,
        progress_callback=progress.append,
    )

    stages = [item.get("stage") for item in progress]
    assert report["effective_max_line_search_attempts"] == 1
    assert report["elapsed_seconds"] >= 0.0
    assert report["state_entry_count"] >= 0
    assert "before_holdout_evaluation" in stages
    assert "line_search_attempt" in stages
    assert stages[-1] == "finished"


def test_legal_ir_view_global_projection_isolates_core_heads() -> None:
    from ipfs_datasets_py.logic.bridge import evaluate_legal_ir_multiview

    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )
    targets = {
        sample.sample_id: evaluate_legal_ir_multiview(
            sample.text,
            bridge_names=("deontic_norms", "fol_tdfol"),
            document_id=sample.sample_id,
            citation=sample.citation,
            source=sample.source,
            source_embedding=sample.embedding_vector,
        ).training_target()
    }
    autoencoder = AdaptiveModalAutoencoder()
    before = autoencoder.evaluate(
        [sample],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    changed = autoencoder._nudge_legal_ir_view_global_logits(
        sample,
        learning_rate=0.5,
    )
    after = autoencoder.evaluate(
        [sample],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    assert changed is True
    assert (
        after.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
        < before.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
    )
    assert autoencoder.state.legal_ir_view_logits
    assert autoencoder.state.family_logits == {}
    assert autoencoder.state.feature_family_logits == {}
    assert autoencoder.state.feature_legal_ir_view_logits == {}
    assert autoencoder.state.feature_embedding_weights == {}


def test_modal_autoencoder_empty_dataset_returns_zero_metrics() -> None:
    evaluation = ModalAutoencoderBaseline().evaluate([])

    assert evaluation.sample_count == 0
    assert evaluation.decoded_embeddings == {}


def test_adaptive_autoencoder_todo_updates_lower_ce_and_increase_cosine() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice.",
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


def test_adaptive_autoencoder_generalizable_projection_uses_holdout_without_sample_memory() -> None:
    train_sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice within 30 days.",
    )
    validation_sample = build_us_code_sample(
        title="5",
        section="553",
        text="The agency must provide notice before adopting a rule.",
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_embedding_weight_scale=1.0,
        feature_family_logit_scale=1.0,
    )
    before = autoencoder.evaluate([validation_sample], use_sample_memory=False)

    report = autoencoder.train_generalizable_projection(
        [train_sample],
        validation_samples=[validation_sample],
        epochs=3,
        learning_rate=0.5,
    )
    after = autoencoder.evaluate([validation_sample], use_sample_memory=False)

    assert report["accepted_epochs"] >= 1
    assert report["sample_memory_used"] is False
    assert after.cross_entropy_loss < before.cross_entropy_loss
    assert after.embedding_cosine_similarity > before.embedding_cosine_similarity
    assert autoencoder.state.family_logits == {}
    assert autoencoder.state.decoded_embeddings == {}
    assert autoencoder.state.feature_family_logits
    assert autoencoder.state.feature_embedding_weights


def test_generalizable_projection_supports_objective_weights_and_hard_example_fraction() -> None:
    train_a = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice within 30 days.",
    )
    train_b = build_us_code_sample(
        title="5",
        section="553",
        text="The agency may provide notice before adopting a rule.",
    )
    validation = build_us_code_sample(
        title="5",
        section="554",
        text="The agency must provide notice before final action.",
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_embedding_weight_scale=1.0,
        feature_family_logit_scale=1.0,
    )

    report = autoencoder.train_generalizable_projection(
        [train_a, train_b],
        validation_samples=[validation],
        epochs=1,
        learning_rate=0.5,
        objective_cross_entropy_weight=2.0,
        objective_reconstruction_weight=0.5,
        objective_cosine_gap_weight=0.25,
        objective_legal_ir_weight=1.5,
        hard_example_fraction=0.5,
    )

    assert report["objective_weights"]["cross_entropy"] == pytest.approx(2.0)
    assert report["objective_weights"]["reconstruction"] == pytest.approx(0.5)
    assert report["objective_weights"]["cosine_gap"] == pytest.approx(0.25)
    assert report["objective_weights"]["legal_ir"] == pytest.approx(1.5)
    assert report["epoch_reports"][0]["hard_example_count"] == 1
    assert report["epoch_reports"][0]["hard_example_fraction"] == pytest.approx(0.5)
    assert report["rejection_summary"]["attempted_count"] >= 1
    assert "refinement_attempt_count" in report["rejection_summary"]
    first_candidate = report["epoch_reports"][0]["candidate_reports"][0]
    assert first_candidate["line_search_attempt_count"] >= 6
    assert "line_search_refinement_attempt_count" in first_candidate
    assert first_candidate["attempt_reports"]
    assert first_candidate["effective_learning_rate"] <= 0.5


def test_projection_acceptance_uses_objective_weights() -> None:
    before = AutoencoderEvaluation(
        sample_count=1,
        embedding_cosine_similarity=0.9,
        cosine_loss=0.1,
        reconstruction_loss=0.1,
        cross_entropy_loss=1.0,
        frame_ranking_loss=0.0,
        symbolic_validity_penalty=0.0,
        decoded_embeddings={},
    )
    after = AutoencoderEvaluation(
        sample_count=1,
        embedding_cosine_similarity=0.99,
        cosine_loss=0.01,
        reconstruction_loss=0.01,
        cross_entropy_loss=2.0,
        frame_ranking_loss=0.0,
        symbolic_validity_penalty=0.0,
        decoded_embeddings={},
    )

    assert (
        _evaluation_improved_for_training(
            before,
            after,
            max_cross_entropy_regression=2.0,
        )
        is False
    )
    assert (
        _evaluation_improved_for_training(
            before,
            after,
            max_cross_entropy_regression=2.0,
            cross_entropy=0.0,
            reconstruction=1.0,
            cosine_gap=1.0,
            legal_ir=0.0,
        )
        is True
    )


def test_generalizable_projection_acceptance_rejects_cosine_regression() -> None:
    before = AutoencoderEvaluation(
        sample_count=1,
        embedding_cosine_similarity=0.5,
        cosine_loss=0.5,
        reconstruction_loss=0.2,
        cross_entropy_loss=2.0,
        frame_ranking_loss=0.0,
        symbolic_validity_penalty=0.0,
        decoded_embeddings={},
    )
    after_ce_only = AutoencoderEvaluation(
        sample_count=1,
        embedding_cosine_similarity=0.1,
        cosine_loss=0.9,
        reconstruction_loss=0.2,
        cross_entropy_loss=1.0,
        frame_ranking_loss=0.0,
        symbolic_validity_penalty=0.0,
        decoded_embeddings={},
    )
    after_pareto = AutoencoderEvaluation(
        sample_count=1,
        embedding_cosine_similarity=0.55,
        cosine_loss=0.45,
        reconstruction_loss=0.19,
        cross_entropy_loss=1.5,
        frame_ranking_loss=0.0,
        symbolic_validity_penalty=0.0,
        decoded_embeddings={},
    )

    assert _evaluation_improved_for_training(before, after_ce_only) is False
    assert _evaluation_improved_for_training(before, after_pareto) is True


def test_legal_ir_component_gap_focus_routes_only_underrepresented_views() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall make final opinions available to the public.",
    )
    autoencoder = AdaptiveModalAutoencoder()
    focus = autoencoder._synthesis_focus_for(
        sample,
        target_family="deontic",
        predicted_family="deontic",
        target_probability=0.9,
        reconstruction_loss=0.0,
        legal_ir_view_cross_entropy_loss=1.0,
        legal_ir_view_distribution={
            "CEC.native": 0.15,
            "external_provers.router": 0.05,
            "knowledge_graphs.neo4j_compat": 0.18,
            "zkp.circuits": 0.05,
        },
        legal_ir_predicted_view_distribution={
            "CEC.native": 0.06,
            "external_provers.router": 0.08,
            "knowledge_graphs.neo4j_compat": 0.07,
            "zkp.circuits": 0.08,
        },
    )

    assert "repair_multiview_legal_ir_loss" in focus
    assert "repair_cec_dcec_bridge" in focus
    assert "repair_multiview_legal_ir_graph_projection" in focus
    assert "repair_external_prover_router" not in focus
    assert "repair_zkp_attestation_bridge" not in focus


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


def test_hard_example_objective_uses_mixed_family_cross_entropy_targets() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice within 30 days.",
    )
    first_formula = sample.modal_ir.formulas[0]
    temporal_formula = replace(
        first_formula,
        formula_id=f"{first_formula.formula_id}-temporal-hard-example",
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
        feature_family_logit_scale=1.0,
        state=ModalAutoencoderTrainingState(
            feature_family_logits={
                "modal-family:deontic": {
                    "deontic": 4.0,
                    "temporal": -4.0,
                }
            }
        )
    )
    distribution = autoencoder._family_distribution(
        mixed_sample,
        use_sample_memory=False,
    )

    objective = autoencoder._sample_training_objective(
        mixed_sample,
        objective_weights={
            "cross_entropy": 1.0,
            "reconstruction": 0.0,
            "cosine_gap": 0.0,
            "legal_ir": 0.0,
        },
    )

    assert objective == pytest.approx(
        cross_entropy_excess_distribution_loss(
            distribution,
            {"deontic": 0.5, "temporal": 0.5},
        )
    )
    assert objective + distribution_entropy_loss(
        {"deontic": 0.5, "temporal": 0.5}
    ) == pytest.approx(
        cross_entropy_distribution_loss(
            distribution,
            {"deontic": 0.5, "temporal": 0.5},
        )
    )
    assert objective > cross_entropy_loss(distribution, "deontic")


def test_family_logit_updates_follow_mixed_family_distribution() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice within 30 days.",
    )
    first_formula = sample.modal_ir.formulas[0]
    temporal_formula = replace(
        first_formula,
        formula_id=f"{first_formula.formula_id}-temporal-update",
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
    autoencoder = AdaptiveModalAutoencoder(feature_family_logit_scale=1.0)
    before = autoencoder.evaluate([mixed_sample])

    todo = type(
        "Todo",
        (),
        {
            "action": "improve_modal_family_classifier",
            "loss_name": "cross_entropy_loss",
            "sample_ids": [mixed_sample.sample_id],
            "todo_id": "mixed-ce-update",
        },
    )()
    autoencoder.apply_todo(
        todo,
        {mixed_sample.sample_id: mixed_sample},
        learning_rate=0.5,
    )
    after = autoencoder.evaluate([mixed_sample])

    sample_logits = autoencoder.state.family_logits[mixed_sample.sample_id]
    assert after.cross_entropy_loss < before.cross_entropy_loss
    assert sample_logits["deontic"] > 0.0
    assert sample_logits["temporal"] > 0.0
    assert sample_logits["alethic"] < 0.0


def test_compiler_latent_profile_features_bridge_source_and_ir_shape() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552(a)",
        text=(
            "If the applicant files notice, the agency must approve the permit "
            "except when records are incomplete."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(max_compiler_latent_profile_features=96)

    profile_features = autoencoder._compiler_latent_profile_feature_keys_for(sample)
    fallback_features = autoencoder._fallback_feature_keys_for(sample)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(sample)

    assert autoencoder._source_role_anchors_for(sample)["action"] == "approve"
    assert autoencoder._source_role_anchors_for(sample)["object"] == "permit"
    assert any(
        feature.startswith("compiler-profile:source-cue-family:deontic:")
        for feature in profile_features
    )
    assert "compiler-profile:source-role:action:approve" in profile_features
    assert "compiler-profile:source-role:object:permit" in profile_features
    assert any(
        feature.startswith("compiler-profile:source-action-family:approve:")
        for feature in profile_features
    )
    assert any(
        feature.startswith("compiler-profile:source-object-family:permit:")
        for feature in profile_features
    )
    assert any(
        feature.startswith("compiler-profile:role-shape:")
        for feature in profile_features
    )
    assert any(feature.startswith("compiler-profile:frame-family:") for feature in fallback_features)
    assert any(
        feature.startswith("legal-ir:compiler-profile:source-cue-family:deontic:")
        for feature in legal_ir_features
    )
    assert "legal-ir:compiler-profile:source-role:action:approve" in legal_ir_features


def test_compiler_latent_profile_feature_head_lowers_holdout_ce() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall provide notice before final action.",
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_profile_features = set(
        autoencoder._compiler_latent_profile_feature_keys_for(train)
    ).intersection(
        autoencoder._compiler_latent_profile_feature_keys_for(validation)
    )
    before = autoencoder.evaluate([validation], use_sample_memory=False)

    autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate([validation], use_sample_memory=False)

    assert any(feature.startswith("compiler-profile:family:") for feature in shared_profile_features)
    assert any(
        feature.startswith("compiler-profile:")
        for feature in autoencoder.state.feature_family_logits
    )
    assert any(feature in autoencoder.state.feature_family_logits for feature in shared_profile_features)
    assert after.cross_entropy_loss < before.cross_entropy_loss


def test_compiler_latent_profile_feature_head_transfers_cosine_to_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall provide notice before final action.",
        embedding_vector=[1.0, 0.0],
    )
    autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before = autoencoder.evaluate([validation], use_sample_memory=False)

    autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate([validation], use_sample_memory=False)

    assert any(
        feature.startswith("compiler-profile:")
        for feature in autoencoder.state.feature_embedding_weights
    )
    assert after.embedding_cosine_similarity > before.embedding_cosine_similarity


def test_decompiler_plan_and_predicate_heads_align_source_roles_to_ir_shape() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552(a)",
        text=(
            "If the applicant files notice, the agency must approve the permit "
            "except when records are incomplete."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder()

    decompiler_plan = autoencoder._decompiler_plan_distribution_for(sample)
    predicate_arguments = autoencoder._predicate_argument_distribution_for(sample)

    assert "decompiler-plan:source-action-family:approve:deontic" in decompiler_plan
    assert "decompiler-plan:source-object-predicate:permit:approve" in decompiler_plan
    assert "decompiler-plan:source-subject-role:agency:condition" in decompiler_plan
    assert "predicate-argument:source-action-family:approve:deontic" in predicate_arguments
    assert "predicate-argument:source-action-predicate:approve:approve" in predicate_arguments
    assert "predicate-argument:source-object-predicate:permit:approve" in predicate_arguments


def test_round_trip_bridge_features_encode_source_ir_equivalence() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552(a)",
        text=(
            "If the applicant files notice, the agency must approve the permit "
            "except when records are incomplete."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(max_round_trip_bridge_features=128)

    bridge_features = autoencoder._round_trip_bridge_feature_keys_for(sample)
    fallback_features = autoencoder._fallback_feature_keys_for(sample)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(sample)

    assert "round-trip-bridge:surface-action-to-family:approve:deontic" in bridge_features
    assert "round-trip-bridge:surface-action-to-predicate:approve:approve" in bridge_features
    assert "round-trip-bridge:surface-object-to-predicate:permit:approve" in bridge_features
    assert any(
        feature.startswith("round-trip-bridge:compile-path:approve->permit:")
        for feature in bridge_features
    )
    assert any(feature.startswith("round-trip-bridge:ir-role-shape:") for feature in bridge_features)
    assert "round-trip-bridge:surface-action-to-family:approve:deontic" in fallback_features
    assert (
        "legal-ir:round-trip-bridge:surface-action-to-family:approve:deontic"
        in legal_ir_features
    )


def test_round_trip_bridge_feature_head_transfers_ce_and_cosine_to_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must approve the permit before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall approve the permit before final action.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=128,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_bridge_features = set(
        family_autoencoder._round_trip_bridge_feature_keys_for(train)
    ).intersection(
        family_autoencoder._round_trip_bridge_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert "round-trip-bridge:surface-action-to-family:approve:deontic" in shared_bridge_features
    assert any(
        feature.startswith("round-trip-bridge:")
        for feature in family_autoencoder.state.feature_family_logits
    )
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=128,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    assert any(
        feature.startswith("round-trip-bridge:")
        for feature in embedding_autoencoder.state.feature_embedding_weights
    )
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_clause_topology_features_capture_abstract_source_ir_graph() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552(a)",
        text=(
            "If the applicant files notice, the agency must approve the permit "
            "except when records are incomplete."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(max_clause_topology_features=128)

    topology_features = autoencoder._clause_topology_feature_keys_for(sample)
    fallback_features = autoencoder._fallback_feature_keys_for(sample)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(sample)

    assert (
        "clause-topology:surface-role-set:condition+subject+action+object+exception"
        in topology_features
    )
    assert "clause-topology:surface-scope:conditional+exception+normative" in topology_features
    assert "clause-topology:surface-role-edge:condition->action" in topology_features
    assert "clause-topology:surface-role-edge:exception->action" in topology_features
    assert (
        "clause-topology:ir-scope:deontic:condition:yes:exception:yes"
        in topology_features
    )
    assert (
        "clause-topology:surface-scope-to-family:conditional+exception+normative:deontic"
        in topology_features
    )
    assert (
        "clause-topology:surface-topology-to-ir:"
        "conditional+exception+normative:"
        "condition+subject+action+object+exception:deontic:condition"
        in topology_features
    )
    assert "clause-topology:surface-scope:conditional+exception+normative" in fallback_features
    assert (
        "legal-ir:clause-topology:surface-scope:conditional+exception+normative"
        in legal_ir_features
    )


def test_clause_topology_feature_head_transfers_across_lexical_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "If the applicant files notice, the agency must approve the permit "
            "except when records are incomplete."
        ),
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text=(
            "If the owner submits proof, the board shall issue the license "
            "except when fees are unpaid."
        ),
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=128,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_topology_features = set(
        family_autoencoder._clause_topology_feature_keys_for(train)
    ).intersection(
        family_autoencoder._clause_topology_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert (
        "clause-topology:surface-scope-to-family:conditional+exception+normative:deontic"
        in shared_topology_features
    )
    assert any(
        feature.startswith("clause-topology:")
        for feature in family_autoencoder.state.feature_family_logits
    )
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=128,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    assert any(
        feature.startswith("clause-topology:")
        for feature in embedding_autoencoder.state.feature_embedding_weights
    )
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_legal_semantic_frame_features_canonicalize_legal_roles() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must approve the permit before final action.",
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="The board shall issue the license before final action.",
    )
    autoencoder = AdaptiveModalAutoencoder(max_legal_semantic_frame_features=128)

    sample_features = autoencoder._legal_semantic_frame_feature_keys_for(sample)
    validation_features = autoencoder._legal_semantic_frame_feature_keys_for(validation)
    fallback_features = autoencoder._fallback_feature_keys_for(sample)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(sample)
    shared_features = set(sample_features).intersection(validation_features)

    assert "legal-semantic-frame:source-action-class:grant_authorization" in sample_features
    assert (
        "legal-semantic-frame:source-object-class:authorization_instrument"
        in sample_features
    )
    assert "legal-semantic-frame:source-subject-class:government_actor" in sample_features
    assert (
        "legal-semantic-frame:source-frame:"
        "government_actor:grant_authorization:authorization_instrument"
        in shared_features
    )
    assert (
        "legal-semantic-frame:source-action-class-family:grant_authorization:deontic"
        in shared_features
    )
    assert (
        "legal-semantic-frame:source-object-class-family:"
        "authorization_instrument:deontic"
        in shared_features
    )
    assert (
        "legal-semantic-frame:source-action-class:grant_authorization"
        in fallback_features
    )
    assert (
        "legal-ir:legal-semantic-frame:source-action-class:grant_authorization"
        in legal_ir_features
    )


def test_legal_semantic_frame_feature_head_transfers_across_paraphrase() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must approve the permit before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="The board shall issue the license before final action.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=128,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_semantic_features = set(
        family_autoencoder._legal_semantic_frame_feature_keys_for(train)
    ).intersection(
        family_autoencoder._legal_semantic_frame_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert (
        "legal-semantic-frame:source-frame:"
        "government_actor:grant_authorization:authorization_instrument"
        in shared_semantic_features
    )
    assert any(
        feature.startswith("legal-semantic-frame:")
        for feature in family_autoencoder.state.feature_family_logits
    )
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=128,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    assert any(
        feature.startswith("legal-semantic-frame:")
        for feature in embedding_autoencoder.state.feature_embedding_weights
    )
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_normative_polarity_features_encode_force_and_negated_scope() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
    )
    negated = build_us_code_sample(
        title="5",
        section="553",
        text="The agency must not issue the license unless fees are paid.",
    )
    autoencoder = AdaptiveModalAutoencoder(max_normative_polarity_features=128)

    polarity_features = autoencoder._normative_polarity_feature_keys_for(sample)
    negated_features = autoencoder._normative_polarity_feature_keys_for(negated)
    fallback_features = autoencoder._fallback_feature_keys_for(sample)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(sample)

    assert "normative-polarity:force:permission" in polarity_features
    assert "normative-polarity:polarity:enabling" in polarity_features
    assert (
        "normative-polarity:deontic-frame:"
        "government_actor:grant_authorization:authorization_instrument:permission"
        in polarity_features
    )
    assert "normative-polarity:force-family:permission:deontic" in polarity_features
    assert autoencoder._source_role_anchors_for(negated)["action"] == "issue"
    assert "normative-polarity:polarity:negative_scope" in negated_features
    assert "normative-polarity:polarity:enabling" not in negated_features
    assert (
        "normative-polarity:force-polarity:obligation:negative_scope"
        in negated_features
    )
    assert (
        "normative-polarity:action-class-polarity:"
        "grant_authorization:negative_scope"
        in negated_features
    )
    assert "normative-polarity:force:permission" in fallback_features
    assert "legal-ir:normative-polarity:force:permission" in legal_ir_features


def test_normative_polarity_feature_head_transfers_permission_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="The board may grant the permit before final action.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=128,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_polarity_features = set(
        family_autoencoder._normative_polarity_feature_keys_for(train)
    ).intersection(
        family_autoencoder._normative_polarity_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert (
        "normative-polarity:deontic-frame:"
        "government_actor:grant_authorization:authorization_instrument:permission"
        in shared_polarity_features
    )
    assert any(
        feature.startswith("normative-polarity:")
        for feature in family_autoencoder.state.feature_family_logits
    )
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=128,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    assert any(
        feature.startswith("normative-polarity:")
        for feature in embedding_autoencoder.state.feature_embedding_weights
    )
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_compiler_contract_features_compose_source_and_ir_contract() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
    )
    negated = build_us_code_sample(
        title="5",
        section="553",
        text="The agency must not issue the license unless fees are paid.",
    )
    autoencoder = AdaptiveModalAutoencoder(max_compiler_contract_features=128)

    contract_features = autoencoder._compiler_contract_feature_keys_for(sample)
    negated_contract_features = autoencoder._compiler_contract_feature_keys_for(negated)
    fallback_features = autoencoder._fallback_feature_keys_for(sample)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(sample)

    assert (
        "compiler-contract:source-contract:"
        "government_actor:grant_authorization:authorization_instrument:"
        "permission:enabling:conditioned+temporal"
        in contract_features
    )
    assert "compiler-contract:ir-contract:deontic:d:p:clause:a0:cno:eno" in contract_features
    assert (
        "compiler-contract:source-ir-contract:"
        "grant_authorization:permission:enabling:deontic:p:clause"
        in contract_features
    )
    assert (
        "compiler-contract:frame-ir-contract:"
        "government_actor:grant_authorization:authorization_instrument:deontic:p"
        in contract_features
    )
    assert (
        "compiler-contract:source-contract:"
        "government_actor:grant_authorization:authorization_instrument:"
        "obligation:negative_scope:conditioned"
        in negated_contract_features
    )
    assert (
        "compiler-contract:source-ir-contract:"
        "grant_authorization:obligation:negative_scope:deontic:o:clause"
        in negated_contract_features
    )
    assert "compiler-contract:force-polarity:obligation:enabling" not in negated_contract_features
    assert "compiler-contract:ir-contract:deontic:d:p:clause:a0:cno:eno" in fallback_features
    assert (
        "legal-ir:compiler-contract:ir-contract:deontic:d:p:clause:a0:cno:eno"
        in legal_ir_features
    )


def test_compiler_guidance_exports_learned_contract_representations() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=2.0,
        max_compiler_contract_features=128,
        max_decompiler_surface_template_features=128,
        max_cycle_consistency_features=128,
        max_logic_view_contract_features=128,
    )
    autoencoder._nudge_family_logits(
        sample,
        learning_rate=0.25,
        update_sample_memory=False,
    )

    guidance = autoencoder.compiler_guidance_for_sample(sample, top_k=12)

    assert guidance["sample_id"] == sample.sample_id
    assert guidance["sample_memory_used"] is False
    assert guidance["family_distribution"]
    assert guidance["decoded_embedding"]
    assert guidance["feature_groups"]["compiler_contract"]
    assert guidance["feature_groups"]["decompiler_surface_template"]
    assert guidance["feature_groups"]["cycle_consistency"]
    assert guidance["feature_groups"]["logic_view_contract"]
    assert "cross_entropy_excess_loss" in guidance["legal_ir_view_metrics"]
    assert guidance["ranked_guidance_features"]
    assert any(
        feature.startswith("compiler-contract:")
        for feature in guidance["feature_groups"]["compiler_contract"]
    )
    assert any(
        feature.startswith("decompiler-surface:")
        for feature in guidance["feature_groups"]["decompiler_surface_template"]
    )


def test_compiler_guidance_flows_into_deterministic_codec_ir() -> None:
    from ipfs_datasets_py.logic.modal import (
        DeterministicModalLogicCodec,
        ModalLogicCodecConfig,
        decoded_modal_phrase_slot_text_map,
    )

    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=2.0,
        max_compiler_contract_features=128,
        max_decompiler_surface_template_features=128,
        max_cycle_consistency_features=128,
        max_logic_view_contract_features=128,
    )
    autoencoder.evaluate(
        [sample],
        legal_ir_targets={
            sample.sample_id: SimpleNamespace(
                losses={"legal_ir_multiview_total_loss": 0.25},
                view_distribution={
                    "deontic.norms": 0.1,
                    "modal.frame_logic": 0.9,
                },
            )
        },
    )
    autoencoder._nudge_family_logits(
        sample,
        learning_rate=0.25,
        update_sample_memory=False,
    )
    guidance = autoencoder.compiler_guidance_for_sample(sample, top_k=12)
    assert guidance["legal_ir_view_gap_distribution"]
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(spacy_model_name="definitely_missing_legal_model")
    )

    result = codec.encode(
        sample.text,
        document_id=sample.sample_id,
        citation=sample.citation,
        source=sample.source,
        source_embedding=sample.embedding_vector,
        compiler_guidance=guidance,
    )

    assert result.metadata["compiler_guidance_applied"] is True
    assert result.metadata["compiler_guidance_feature_count"] > 0
    assert result.metadata["compiler_guidance_legal_ir_view_gap_distribution"]
    assert result.modal_ir.metadata["compiler_guidance_feature_groups"]
    assert result.modal_ir.metadata["compiler_guidance_legal_ir_view_gap_distribution"]
    assert result.modal_ir.metadata["compiler_guidance_ranked_features"]
    assert result.modal_ir.metadata["frame_selector"] == "bm25_v1+autoencoder_guidance_v1"
    assert result.modal_ir.frame_logic.metadata["compiler_guidance_applied"] is True
    slot_texts = decoded_modal_phrase_slot_text_map(result.decoded_modal_text)
    assert slot_texts["compiler_guidance_applied"] == ["true"]
    assert slot_texts["compiler_guidance_family"]
    assert slot_texts["compiler_guidance_feature_group"]
    assert slot_texts["compiler_guidance_feature"]
    assert slot_texts["compiler_guidance_decompiler_surface_template_feature"]
    assert slot_texts["compiler_guidance_legal_ir_view_gap"]
    assert slot_texts["compiler_guidance_legal_ir_view_gap_direction"]
    assert "cross_entropy_excess_loss" in result.losses
    assert "guidance_family_cross_entropy_excess_loss" in result.losses
    assert "source_copy_reward_hack_penalty" in result.losses


def test_compiler_guidance_surfaces_underrepresented_legal_ir_views() -> None:
    from ipfs_datasets_py.logic.modal import (
        DeterministicModalLogicCodec,
        ModalLogicCodecConfig,
        decoded_modal_phrase_slot_text_map,
    )

    sample = build_us_code_sample(
        title="19",
        section="1521",
        text="Administrative notice and hearing procedures are established.",
    )
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(spacy_model_name="definitely_missing_legal_model")
    )
    guidance = {
        "sample_id": sample.sample_id,
        "sample_memory_used": False,
        "family_distribution": {"frame": 0.8, "deontic": 0.2},
        "decoded_embedding": [0.1, 0.2, 0.3],
        "feature_groups": {"logic_view_contract": ["legal-ir-view:CEC.native"]},
        "legal_ir_predicted_view_distribution": {"deontic.ir": 0.9, "CEC.native": 0.1},
        "legal_ir_target_view_distribution": {"deontic.ir": 0.6, "CEC.native": 0.4},
        "legal_ir_view_gap_distribution": {"deontic.ir": -0.3, "CEC.native": 0.3},
        "legal_ir_view_metrics": {"cross_entropy_excess_loss": 0.1},
        "ranked_guidance_features": [{"feature": "legal-ir-view:CEC.native", "weight": 0.3}],
    }

    result = codec.encode(
        sample.text,
        document_id=sample.sample_id,
        citation=sample.citation,
        source=sample.source,
        source_embedding=sample.embedding_vector,
        compiler_guidance=guidance,
    )

    slot_texts = decoded_modal_phrase_slot_text_map(result.decoded_modal_text)
    assert slot_texts["compiler_guidance_legal_ir_underrepresented_view"] == ["cec_native"]
    assert (
        slot_texts["compiler_guidance_legal_ir_underrepresented_view_ranked"]
        == ["1:cec_native"]
    )


def test_compiler_contract_feature_head_transfers_permission_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="The board may grant the permit before final action.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=128,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_contract_features = set(
        family_autoencoder._compiler_contract_feature_keys_for(train)
    ).intersection(
        family_autoencoder._compiler_contract_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert (
        "compiler-contract:source-ir-contract:"
        "grant_authorization:permission:enabling:deontic:p:clause"
        in shared_contract_features
    )
    assert any(
        feature.startswith("compiler-contract:")
        for feature in family_autoencoder.state.feature_family_logits
    )
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=128,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    assert any(
        feature.startswith("compiler-contract:")
        for feature in embedding_autoencoder.state.feature_embedding_weights
    )
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_decompiler_surface_template_features_encode_ir_to_text_plan() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
    )
    negated = build_us_code_sample(
        title="5",
        section="553",
        text="The agency must not issue the license unless fees are paid.",
    )
    autoencoder = AdaptiveModalAutoencoder(
        max_decompiler_surface_template_features=128,
    )

    surface_features = autoencoder._decompiler_surface_template_feature_keys_for(sample)
    negated_surface_features = autoencoder._decompiler_surface_template_feature_keys_for(
        negated
    )
    fallback_features = autoencoder._fallback_feature_keys_for(sample)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(sample)

    assert (
        "decompiler-surface:slot-order:"
        "subject>force>polarity>action>object>temporal"
        in surface_features
    )
    assert "decompiler-surface:force-lexeme:permission:may" in surface_features
    assert (
        "decompiler-surface:template:"
        "government_actor:permission:enabling:"
        "grant_authorization:authorization_instrument:conditioned+temporal"
        in surface_features
    )
    assert (
        "decompiler-surface:ir-realization:"
        "deontic:d:p:permission:enabling:conditioned+temporal"
        in surface_features
    )
    assert (
        "decompiler-surface:surface-ir-template:"
        "government_actor:grant_authorization:authorization_instrument:deontic:p"
        in surface_features
    )
    assert "decompiler-surface:negation-placement:pre-action" in negated_surface_features
    assert (
        "decompiler-surface:template:"
        "government_actor:obligation:negative_scope:"
        "grant_authorization:authorization_instrument:conditioned"
        in negated_surface_features
    )
    assert not any(
        feature.startswith("decompiler-surface:template:")
        and ":enabling:" in feature
        for feature in negated_surface_features
    )
    assert "decompiler-surface:force-lexeme:permission:may" in fallback_features
    assert (
        "legal-ir:decompiler-surface:force-lexeme:permission:may"
        in legal_ir_features
    )


def test_decompiler_surface_template_feature_head_transfers_permission_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="The board may grant the permit before final action.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=128,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_surface_features = set(
        family_autoencoder._decompiler_surface_template_feature_keys_for(train)
    ).intersection(
        family_autoencoder._decompiler_surface_template_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert (
        "decompiler-surface:ir-realization:"
        "deontic:d:p:permission:enabling:conditioned+temporal"
        in shared_surface_features
    )
    assert any(
        feature.startswith("decompiler-surface:")
        for feature in family_autoencoder.state.feature_family_logits
    )
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=128,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    assert any(
        feature.startswith("decompiler-surface:")
        for feature in embedding_autoencoder.state.feature_embedding_weights
    )
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_canonical_ir_graph_features_normalize_surface_paraphrases() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
    )
    paraphrase = build_us_code_sample(
        title="12",
        section="1841",
        text="The board may grant the permit before final action.",
    )
    conditional = build_us_code_sample(
        title="5",
        section="553",
        text=(
            "If the applicant files notice, the agency must approve the permit "
            "except when records are incomplete."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(
        max_canonical_ir_graph_features=128,
    )

    graph_features = autoencoder._canonical_ir_graph_feature_keys_for(sample)
    paraphrase_features = autoencoder._canonical_ir_graph_feature_keys_for(paraphrase)
    conditional_features = autoencoder._canonical_ir_graph_feature_keys_for(conditional)
    fallback_features = autoencoder._fallback_feature_keys_for(sample)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(sample)

    assert (
        "canonical-ir:canonical-formula:"
        "deontic:p:clause:grant_authorization:authorization_instrument:"
        "permission:enabling:conditioned+temporal"
        in graph_features
    )
    assert (
        "canonical-ir:semantic-node:"
        "grant_authorization:authorization_instrument:deontic:p:clause"
        in graph_features
    )
    assert "canonical-ir:ir-node:deontic:d:p:clause:a0:c0:e0" in graph_features
    assert (
        "canonical-ir:canonical-formula:"
        "deontic:p:clause:grant_authorization:authorization_instrument:"
        "permission:enabling:conditioned+temporal"
        in paraphrase_features
    )
    assert (
        "canonical-ir:condition-edge:"
        "eligibility_condition->conditional_normative:o:condition"
        in conditional_features
    )
    assert (
        "canonical-ir:exception-edge:record_exception->deontic:o:condition"
        in conditional_features
    )
    assert "canonical-ir:ir-node:deontic:d:p:clause:a0:c0:e0" in fallback_features
    assert (
        "legal-ir:canonical-ir:ir-node:deontic:d:p:clause:a0:c0:e0"
        in legal_ir_features
    )


def test_canonical_ir_graph_feature_head_transfers_permission_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="The board may grant the permit before final action.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=128,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_graph_features = set(
        family_autoencoder._canonical_ir_graph_feature_keys_for(train)
    ).intersection(
        family_autoencoder._canonical_ir_graph_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert (
        "canonical-ir:canonical-formula:"
        "deontic:p:clause:grant_authorization:authorization_instrument:"
        "permission:enabling:conditioned+temporal"
        in shared_graph_features
    )
    assert any(
        feature.startswith("canonical-ir:")
        for feature in family_autoencoder.state.feature_family_logits
    )
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=128,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    assert any(
        feature.startswith("canonical-ir:")
        for feature in embedding_autoencoder.state.feature_embedding_weights
    )
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_cycle_consistency_features_bind_source_ir_and_decompiler_scope() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
    )
    conditional = build_us_code_sample(
        title="5",
        section="553",
        text=(
            "If the applicant files notice, the agency must approve the permit "
            "except when records are incomplete."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(
        max_cycle_consistency_features=128,
    )

    cycle_features = autoencoder._cycle_consistency_feature_keys_for(sample)
    conditional_cycle_features = autoencoder._cycle_consistency_feature_keys_for(
        conditional
    )
    fallback_features = autoencoder._fallback_feature_keys_for(sample)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(sample)

    assert (
        "cycle-consistency:source-ir-cycle:"
        "government_actor:grant_authorization:authorization_instrument:"
        "permission:enabling:deontic:p:clause:conditioned+temporal:cno:eno"
        in cycle_features
    )
    assert (
        "cycle-consistency:condition-cycle:source-no:ir-no:deontic:clause"
        in cycle_features
    )
    assert (
        "cycle-consistency:scope-cycle:"
        "deontic:clause:conditioned+temporal->temporal"
        in cycle_features
    )
    assert (
        "cycle-consistency:condition-cycle:"
        "source-yes:ir-yes:conditional_normative:condition"
        in conditional_cycle_features
    )
    assert (
        "cycle-consistency:exception-cycle:source-yes:ir-yes:deontic:condition"
        in conditional_cycle_features
    )
    assert (
        "cycle-consistency:source-ir-cycle:"
        "government_actor:grant_authorization:authorization_instrument:"
        "permission:enabling:deontic:p:clause:conditioned+temporal:cno:eno"
        in fallback_features
    )
    assert (
        "legal-ir:cycle-consistency:condition-cycle:"
        "source-no:ir-no:deontic:clause"
        in legal_ir_features
    )


def test_cycle_consistency_feature_head_transfers_permission_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="The board may grant the permit before final action.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=128,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_cycle_features = set(
        family_autoencoder._cycle_consistency_feature_keys_for(train)
    ).intersection(
        family_autoencoder._cycle_consistency_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert (
        "cycle-consistency:source-ir-cycle:"
        "government_actor:grant_authorization:authorization_instrument:"
        "permission:enabling:deontic:p:clause:conditioned+temporal:cno:eno"
        in shared_cycle_features
    )
    assert any(
        feature.startswith("cycle-consistency:")
        for feature in family_autoencoder.state.feature_family_logits
    )
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=128,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    assert any(
        feature.startswith("cycle-consistency:")
        for feature in embedding_autoencoder.state.feature_embedding_weights
    )
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_equivalence_prototype_features_share_logical_paraphrase_class() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
    )
    paraphrase = build_us_code_sample(
        title="12",
        section="1841",
        text="The board may grant the permit before final action.",
    )
    conditional = build_us_code_sample(
        title="5",
        section="553",
        text=(
            "If the applicant files notice, the agency must approve the permit "
            "except when records are incomplete."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(
        max_equivalence_prototype_features=128,
    )

    prototype_features = autoencoder._equivalence_prototype_feature_keys_for(sample)
    paraphrase_features = autoencoder._equivalence_prototype_feature_keys_for(
        paraphrase
    )
    conditional_features = autoencoder._equivalence_prototype_feature_keys_for(
        conditional
    )
    shared_equivalence_classes = {
        feature
        for feature in prototype_features
        if feature.startswith("equivalence-prototype:equivalence-class:")
    }.intersection(paraphrase_features)
    fallback_features = autoencoder._fallback_feature_keys_for(sample)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(sample)

    assert shared_equivalence_classes
    assert (
        "equivalence-prototype:round-trip-prototype:"
        "government_actor:grant_authorization:authorization_instrument:"
        "permission:enabling:deontic:p:clause:conditioned+temporal:"
        "unconditioned:unexcepted"
        in prototype_features
    )
    assert (
        "equivalence-prototype:role-prototype:"
        "government_actor:grant_authorization:authorization_instrument:"
        "eligibility_condition:record_exception:atemporal"
        in conditional_features
    )
    assert (
        "equivalence-prototype:operator-prototype:"
        "deontic:d:p:clause:a0:unconditioned:unexcepted"
        in fallback_features
    )
    assert (
        "legal-ir:equivalence-prototype:operator-prototype:"
        "deontic:d:p:clause:a0:unconditioned:unexcepted"
        in legal_ir_features
    )


def test_equivalence_prototype_feature_head_transfers_permission_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="The board may grant the permit before final action.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=128,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_prototype_features = set(
        family_autoencoder._equivalence_prototype_feature_keys_for(train)
    ).intersection(
        family_autoencoder._equivalence_prototype_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert any(
        feature.startswith("equivalence-prototype:equivalence-class:")
        for feature in shared_prototype_features
    )
    assert (
        "equivalence-prototype:round-trip-prototype:"
        "government_actor:grant_authorization:authorization_instrument:"
        "permission:enabling:deontic:p:clause:conditioned+temporal:"
        "unconditioned:unexcepted"
        in shared_prototype_features
    )
    assert any(
        feature.startswith("equivalence-prototype:")
        for feature in family_autoencoder.state.feature_family_logits
    )
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=128,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    assert any(
        feature.startswith("equivalence-prototype:")
        for feature in embedding_autoencoder.state.feature_embedding_weights
    )
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_contrastive_ir_boundary_features_separate_minimal_pairs() -> None:
    permission = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
    )
    obligation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency must issue the license before final action.",
    )
    negated = build_us_code_sample(
        title="5",
        section="554",
        text="The agency must not issue the license unless fees are paid.",
    )
    autoencoder = AdaptiveModalAutoencoder(
        max_contrastive_ir_boundary_features=128,
    )

    permission_features = autoencoder._contrastive_ir_boundary_feature_keys_for(
        permission
    )
    obligation_features = autoencoder._contrastive_ir_boundary_feature_keys_for(
        obligation
    )
    negated_features = autoencoder._contrastive_ir_boundary_feature_keys_for(negated)
    fallback_features = autoencoder._fallback_feature_keys_for(permission)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(permission)

    assert (
        "contrastive-ir:force-axis:"
        "permission:vs-obligation+prohibition+definition+enforcement+assertive"
        in permission_features
    )
    assert (
        "contrastive-ir:force-axis:"
        "obligation:vs-permission+prohibition+definition+enforcement+assertive"
        in obligation_features
    )
    assert "contrastive-ir:operator-axis:deontic:d:p:clause:a0:cno:eno:tyes" in (
        permission_features
    )
    assert "contrastive-ir:operator-axis:deontic:d:o:clause:a0:cno:eno:tyes" in (
        obligation_features
    )
    assert (
        "contrastive-ir:minimal-pair-boundary:"
        "government_actor:grant_authorization:authorization_instrument:"
        "permission:enabling:cyes:eno:tyes"
        in permission_features
    )
    assert (
        "contrastive-ir:negation-boundary:negated:conditioned"
        in negated_features
    )
    assert (
        "contrastive-ir:operator-axis:deontic:d:p:clause:a0:cno:eno:tyes"
        not in obligation_features
    )
    assert (
        "contrastive-ir:force-axis:"
        "permission:vs-obligation+prohibition+definition+enforcement+assertive"
        in fallback_features
    )
    assert (
        "legal-ir:contrastive-ir:force-axis:"
        "permission:vs-obligation+prohibition+definition+enforcement+assertive"
        in legal_ir_features
    )


def test_contrastive_ir_boundary_feature_head_transfers_permission_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="The board may grant the permit before final action.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=128,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_boundary_features = set(
        family_autoencoder._contrastive_ir_boundary_feature_keys_for(train)
    ).intersection(
        family_autoencoder._contrastive_ir_boundary_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert (
        "contrastive-ir:semantic-operator-boundary:"
        "government_actor:grant_authorization:authorization_instrument:"
        "deontic:p:permission:enabling:cyes:eno:tyes"
        in shared_boundary_features
    )
    assert any(
        feature.startswith("contrastive-ir:")
        for feature in family_autoencoder.state.feature_family_logits
    )
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=128,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    assert any(
        feature.startswith("contrastive-ir:")
        for feature in embedding_autoencoder.state.feature_embedding_weights
    )
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_repair_plan_features_encode_todo_repair_axes() -> None:
    permission = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
    )
    negated = build_us_code_sample(
        title="5",
        section="554",
        text="The agency must not issue the license unless fees are paid.",
    )
    conditional = build_us_code_sample(
        title="5",
        section="553",
        text=(
            "If the applicant files notice, the agency must approve the permit "
            "except when records are incomplete."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(max_repair_plan_features=160)

    permission_features = autoencoder._repair_plan_feature_keys_for(permission)
    negated_features = autoencoder._repair_plan_feature_keys_for(negated)
    conditional_features = autoencoder._repair_plan_feature_keys_for(conditional)
    fallback_features = autoencoder._fallback_feature_keys_for(permission)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(permission)

    assert (
        "repair-plan:source-ir-rule:"
        "government_actor:grant_authorization:authorization_instrument:"
        "deontic:p:clause"
        in permission_features
    )
    assert (
        "repair-plan:force-operator:"
        "permission:enabling:deontic:p:clause"
        in permission_features
    )
    assert (
        "repair-plan:surface-template:"
        "permission:enabling:conditioned+temporal:deontic:p"
        in permission_features
    )
    assert (
        "repair-plan:lexeme-operator:may:deontic:p:permission"
        in permission_features
    )
    assert (
        "repair-plan:preserve-force-boundary:"
        "grant_authorization:authorization_instrument:"
        "permission:enabling:deontic:p"
        in permission_features
    )
    assert (
        "repair-plan:add-condition-extractor:deontic:clause"
        in permission_features
    )
    assert (
        "repair-plan:preserve-negation-boundary:negated:deontic:o"
        in negated_features
    )
    assert (
        "repair-plan:condition-state:"
        "source-yes:ir-yes:conditional_normative:condition"
        in conditional_features
    )
    assert (
        "repair-plan:exception-state:"
        "source-yes:ir-yes:deontic:condition"
        in conditional_features
    )
    assert "repair-plan:kg-build-needed:t0:r0" in permission_features
    assert (
        "repair-plan:source-ir-rule:"
        "government_actor:grant_authorization:authorization_instrument:"
        "deontic:p:clause"
        in fallback_features
    )
    assert (
        "legal-ir:repair-plan:source-ir-rule:"
        "government_actor:grant_authorization:authorization_instrument:"
        "deontic:p:clause"
        in legal_ir_features
    )


def test_repair_plan_feature_head_transfers_permission_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="The board may grant the permit before final action.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=160,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_repair_features = set(
        family_autoencoder._repair_plan_feature_keys_for(train)
    ).intersection(family_autoencoder._repair_plan_feature_keys_for(validation))
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert (
        "repair-plan:source-ir-rule:"
        "government_actor:grant_authorization:authorization_instrument:"
        "deontic:p:clause"
        in shared_repair_features
    )
    assert (
        "repair-plan:surface-template:"
        "permission:enabling:conditioned+temporal:deontic:p"
        in shared_repair_features
    )
    assert any(
        feature.startswith("repair-plan:")
        for feature in family_autoencoder.state.feature_family_logits
    )
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=160,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    assert any(
        feature.startswith("repair-plan:")
        for feature in embedding_autoencoder.state.feature_embedding_weights
    )
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_logic_view_contract_features_bind_multiview_bridge_slots() -> None:
    permission = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
    )
    conditional = build_us_code_sample(
        title="5",
        section="553",
        text=(
            "If the applicant files notice, the agency must approve the permit "
            "except when records are incomplete."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(
        max_logic_view_contract_features=180,
    )

    permission_features = autoencoder._logic_view_contract_feature_keys_for(permission)
    conditional_features = autoencoder._logic_view_contract_feature_keys_for(
        conditional
    )
    fallback_features = autoencoder._fallback_feature_keys_for(permission)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(permission)

    assert "logic-view-contract:expected-view:deontic_norms" in permission_features
    assert "logic-view-contract:expected-view:fol_tdfol" in permission_features
    assert "logic-view-contract:expected-view:cec_native" in permission_features
    assert (
        "logic-view-contract:expected-view:knowledge_graphs_neo4j_compat"
        in permission_features
    )
    assert (
        "logic-view-contract:todo-route:"
        "refine_typed_ir_or_decompiler_slots:"
        "modal_ir+external_provers_router+deontic_norms+fol_tdfol+"
        "cec_native+knowledge_graphs_neo4j_compat+modal_frame_logic"
        in permission_features
    )
    assert (
        "logic-view-contract:deontic-slot:"
        "permission:enabling:government_actor:grant_authorization:"
        "authorization_instrument:deontic:p"
        in permission_features
    )
    assert (
        "logic-view-contract:cec-slot:"
        "temporal:grant_authorization:deontic:p:clause"
        in permission_features
    )
    assert (
        "logic-view-contract:kg-slot:"
        "government_actor:grant_authorization:authorization_instrument:t0:r0"
        in permission_features
    )
    assert (
        "logic-view-contract:tdfol-slot:"
        "grant_authorization:cyes:eyes:a0:deontic:o"
        in conditional_features
    )
    assert (
        "logic-view-contract:scope-slot:"
        "conditional_normative:o:source-cyes:eyes:tno:ir-cyes:eyes"
        in conditional_features
    )
    assert "logic-view-contract:expected-view:deontic_norms" in fallback_features
    assert (
        "legal-ir:logic-view-contract:expected-view:deontic_norms"
        in legal_ir_features
    )


def test_logic_view_contract_feature_head_transfers_permission_holdout() -> None:
    class DummyDocument:
        def __init__(self, value: str) -> None:
            self._value = value

        def canonical_hash(self):
            return self._value

    class DummyTarget:
        def __init__(self, value: str) -> None:
            self.document = DummyDocument(value)
            self.losses = {"legal_ir_multiview_total_loss": 0.1}
            self.view_distribution = {
                "deontic_norms": 0.4,
                "CEC.native": 0.3,
                "knowledge_graphs.neo4j_compat": 0.3,
            }

    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="The board may grant the permit before final action.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=180,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_contract_features = set(
        family_autoencoder._logic_view_contract_feature_keys_for(train)
    ).intersection(
        family_autoencoder._logic_view_contract_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert (
        "logic-view-contract:deontic-slot:"
        "permission:enabling:government_actor:grant_authorization:"
        "authorization_instrument:deontic:p"
        in shared_contract_features
    )
    assert (
        "logic-view-contract:cec-slot:"
        "temporal:grant_authorization:deontic:p:clause"
        in shared_contract_features
    )
    assert any(
        feature.startswith("logic-view-contract:")
        for feature in family_autoencoder.state.feature_family_logits
    )
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=180,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate([validation], use_sample_memory=False)

    assert any(
        feature.startswith("logic-view-contract:")
        for feature in embedding_autoencoder.state.feature_embedding_weights
    )
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity

    targets = {
        train.sample_id: DummyTarget("logic-view-contract-train-target"),
        validation.sample_id: DummyTarget("logic-view-contract-validation-target"),
    }
    view_autoencoder = AdaptiveModalAutoencoder(
        legal_ir_view_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=180,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        max_legal_ir_token_features=0,
        max_legal_ir_token_bigram_features=0,
        max_legal_ir_token_trigram_features=0,
    )
    before_view = view_autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    view_autoencoder.evaluate(
        [train],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )
    view_autoencoder._nudge_legal_ir_view_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_view = view_autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    assert any(
        feature.startswith("logic-view-contract:")
        for feature in view_autoencoder.state.feature_legal_ir_view_logits
    )
    assert (
        after_view.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
        < before_view.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
    )


def test_objective_residual_features_bind_loss_profile_to_todo_routes() -> None:
    class DummyDocument:
        def canonical_hash(self):
            return "objective-residual-target"

    class DummyTarget:
        document = DummyDocument()
        losses = {
            "legal_ir_multiview_total_loss": 0.42,
            "legal_ir_multiview_cross_entropy_loss": 0.31,
            "legal_ir_multiview_cosine_loss": 0.22,
            "legal_ir_multiview_graph_failure_penalty": 0.5,
            "cec_dcec_validation_failure_ratio": 0.4,
            "source_copy_reward_hack_penalty": 0.3,
            "source_decompiled_text_embedding_cosine_loss": 0.45,
            "source_decompiled_text_token_loss": 0.35,
        }
        view_distribution = {
            "deontic_norms": 0.4,
            "CEC.native": 0.3,
            "knowledge_graphs.neo4j_compat": 0.3,
        }

    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
    )
    targets = {sample.sample_id: DummyTarget()}
    autoencoder = AdaptiveModalAutoencoder(
        max_objective_residual_features=180,
    )

    assert autoencoder._objective_residual_feature_keys_for(sample) == []

    autoencoder.evaluate(
        [sample],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )
    objective_features = autoencoder._objective_residual_feature_keys_for(sample)
    fallback_features = autoencoder._fallback_feature_keys_for(sample)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(sample)

    assert (
        "objective-residual:loss-route:"
        "repair_multiview_legal_ir_graph_projection:"
        "legal_ir_multiview_graph_failure_penalty:large"
        in objective_features
    )
    assert (
        "objective-residual:loss-route:"
        "repair_cec_dcec_bridge:cec_dcec_validation_failure_ratio:large"
        in objective_features
    )
    assert (
        "objective-residual:loss-route:"
        "refine_typed_ir_or_decompiler_slots:"
        "legal_ir_multiview_cosine_loss:large"
        in objective_features
    )
    assert (
        "objective-residual:loss-route:"
        "refine_semantic_decompiler_reconstruction:"
        "source_copy_reward_hack_penalty:large"
        in objective_features
    )
    assert (
        "objective-residual:loss-route:"
        "refine_semantic_decompiler_reconstruction:"
        "source_decompiled_text_embedding_cosine_loss:large"
        in objective_features
    )
    assert (
        "objective-residual:view-route:"
        "repair_deontic_bridge_quality_gate:deontic_norms:high"
        in objective_features
    )
    assert (
        "objective-residual:force-objective:"
        "permission:enabling:repair_cec_dcec_bridge:"
        "conditioned+temporal:government_actor:grant_authorization:"
        "authorization_instrument"
        in objective_features
    )
    assert (
        "objective-residual:operator-view-objective:"
        "deontic:p:knowledge_graphs_neo4j_compat:large"
        in objective_features
    )
    assert (
        "objective-residual:view-route:"
        "repair_deontic_bridge_quality_gate:deontic_norms:high"
        in fallback_features
    )
    assert (
        "legal-ir:objective-residual:view-route:"
        "repair_deontic_bridge_quality_gate:deontic_norms:high"
        in legal_ir_features
    )


def test_objective_residual_feature_head_transfers_loss_profile_holdout() -> None:
    class DummyDocument:
        def __init__(self, value: str) -> None:
            self._value = value

        def canonical_hash(self):
            return self._value

    class DummyTarget:
        def __init__(self, value: str) -> None:
            self.document = DummyDocument(value)
            self.losses = {
                "legal_ir_multiview_total_loss": 0.42,
                "legal_ir_multiview_cross_entropy_loss": 0.31,
                "legal_ir_multiview_cosine_loss": 0.22,
                "legal_ir_multiview_graph_failure_penalty": 0.5,
                "cec_dcec_validation_failure_ratio": 0.4,
            }
            self.view_distribution = {
                "deontic_norms": 0.4,
                "CEC.native": 0.3,
                "knowledge_graphs.neo4j_compat": 0.3,
            }

    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="The board may grant the permit before final action.",
        embedding_vector=[1.0, 0.0],
    )
    targets = {
        train.sample_id: DummyTarget("objective-residual-train-target"),
        validation.sample_id: DummyTarget("objective-residual-validation-target"),
    }
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=180,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    before_ce = family_autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )
    family_autoencoder.evaluate(
        [train],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )
    shared_objective_features = set(
        family_autoencoder._objective_residual_feature_keys_for(train)
    ).intersection(
        family_autoencoder._objective_residual_feature_keys_for(validation)
    )

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    assert (
        "objective-residual:loss-route:"
        "repair_cec_dcec_bridge:cec_dcec_validation_failure_ratio:large"
        in shared_objective_features
    )
    assert any(
        feature.startswith("objective-residual:")
        for feature in family_autoencoder.state.feature_family_logits
    )
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=180,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )
    embedding_autoencoder.evaluate(
        [train],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    assert any(
        feature.startswith("objective-residual:")
        for feature in embedding_autoencoder.state.feature_embedding_weights
    )
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity

    view_autoencoder = AdaptiveModalAutoencoder(
        legal_ir_view_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=180,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        max_legal_ir_token_features=0,
        max_legal_ir_token_bigram_features=0,
        max_legal_ir_token_trigram_features=0,
    )
    before_view = view_autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )
    view_autoencoder.evaluate(
        [train],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    view_autoencoder._nudge_legal_ir_view_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_view = view_autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    assert any(
        feature.startswith("objective-residual:")
        for feature in view_autoencoder.state.feature_legal_ir_view_logits
    )
    assert (
        after_view.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
        < before_view.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
    )


def test_provenance_alignment_features_encode_span_and_cue_contracts() -> None:
    permission = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
    )
    conditional = build_us_code_sample(
        title="5",
        section="553",
        text=(
            "If the applicant files notice, the agency must approve the permit "
            "except when records are incomplete."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(
        max_provenance_alignment_features=180,
    )

    permission_features = autoencoder._provenance_alignment_feature_keys_for(
        permission
    )
    conditional_features = autoencoder._provenance_alignment_feature_keys_for(
        conditional
    )
    fallback_features = autoencoder._fallback_feature_keys_for(permission)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(permission)

    assert (
        "provenance-alignment:operator-span:"
        "deontic:p:clause:start-0:len-very-high"
        in permission_features
    )
    assert "provenance-alignment:cue-span:may:deontic:p:inside" in (
        permission_features
    )
    assert (
        "provenance-alignment:span-role-contract:"
        "subject-action-object-temporal:deontic:p:clause:conditioned+temporal"
        in permission_features
    )
    assert (
        "provenance-alignment:decompiler-span-contract:"
        "government_actor:grant_authorization:authorization_instrument:"
        "conditioned+temporal:coverage-very-high"
        in permission_features
    )
    assert "provenance-alignment:coverage:very-high" in permission_features
    assert "provenance-alignment:span-order:monotonic" in permission_features
    assert (
        "provenance-alignment:span-role-contract:"
        "subject-action-object-condition-exception:"
        "conditional_normative:o:condition:conditioned+excepted"
        in conditional_features
    )
    assert "provenance-alignment:span-order:overlap" in conditional_features
    assert (
        "provenance-alignment:operator-span:"
        "deontic:p:clause:start-0:len-very-high"
        in fallback_features
    )
    assert (
        "legal-ir:provenance-alignment:operator-span:"
        "deontic:p:clause:start-0:len-very-high"
        in legal_ir_features
    )


def test_provenance_alignment_feature_head_transfers_permission_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="The board may grant the permit before final action.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=180,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_provenance_features = set(
        family_autoencoder._provenance_alignment_feature_keys_for(train)
    ).intersection(
        family_autoencoder._provenance_alignment_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert (
        "provenance-alignment:decompiler-span-contract:"
        "government_actor:grant_authorization:authorization_instrument:"
        "conditioned+temporal:coverage-very-high"
        in shared_provenance_features
    )
    assert any(
        feature.startswith("provenance-alignment:")
        for feature in family_autoencoder.state.feature_family_logits
    )
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=180,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert any(
        feature.startswith("provenance-alignment:")
        for feature in embedding_autoencoder.state.feature_embedding_weights
    )
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_discourse_flow_features_encode_clause_order_and_decompiler_routes() -> None:
    permission = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
    )
    conditional = build_us_code_sample(
        title="5",
        section="553",
        text=(
            "If the applicant files notice, the agency must approve the permit "
            "except when records are incomplete."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(max_discourse_flow_features=180)

    permission_features = autoencoder._discourse_flow_feature_keys_for(permission)
    conditional_features = autoencoder._discourse_flow_feature_keys_for(conditional)
    fallback_features = autoencoder._fallback_feature_keys_for(permission)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(permission)

    assert "discourse-flow:phase-sequence:permission->temporal" in permission_features
    assert (
        "discourse-flow:role-flow:"
        "government_actor:grant_authorization:authorization_instrument:"
        "subject->action->object->temporal:conditioned+temporal"
        in permission_features
    )
    assert (
        "discourse-flow:decompiler-order:"
        "permission->temporal:subject->action->object->temporal:"
        "conditioned+temporal"
        in permission_features
    )
    assert (
        "discourse-flow:cue-operator-flow:"
        "before:deontic:p:temporal:clause"
        in permission_features
    )
    assert (
        "discourse-flow:todo-route:"
        "refine_semantic_decompiler_reconstruction:"
        "permission->temporal:subject->action->object->temporal"
        in permission_features
    )
    assert (
        "discourse-flow:phase-sequence:"
        "condition->event->obligation->exception->condition"
        in conditional_features
    )
    assert (
        "discourse-flow:phase-transition:"
        "obligation->exception:conditioned+excepted"
        in conditional_features
    )
    assert (
        "discourse-flow:scope-order:condition:before-action:conditioned+excepted"
        in conditional_features
    )
    assert (
        "discourse-flow:scope-order:exception:after-action:conditioned+excepted"
        in conditional_features
    )
    assert (
        "discourse-flow:cue-operator-flow:"
        "files:dynamic:a:event:condition"
        in conditional_features
    )
    assert "discourse-flow:phase-sequence:permission->temporal" in fallback_features
    assert (
        "legal-ir:discourse-flow:phase-sequence:permission->temporal"
        in legal_ir_features
    )


def test_discourse_flow_feature_head_transfers_permission_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="The board may grant the permit before final action.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=180,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_discourse_features = set(
        family_autoencoder._discourse_flow_feature_keys_for(train)
    ).intersection(
        family_autoencoder._discourse_flow_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert (
        "discourse-flow:decompiler-order:"
        "permission->temporal:subject->action->object->temporal:"
        "conditioned+temporal"
        in shared_discourse_features
    )
    assert any(
        feature.startswith("discourse-flow:")
        for feature in family_autoencoder.state.feature_family_logits
    )
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=180,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert any(
        feature.startswith("discourse-flow:")
        for feature in embedding_autoencoder.state.feature_embedding_weights
    )
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_proof_obligation_features_encode_bridge_and_prover_routes() -> None:
    permission = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
    )
    conditional = build_us_code_sample(
        title="5",
        section="553",
        text=(
            "If the applicant files notice, the agency must approve the permit "
            "except when records are incomplete."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(max_proof_obligation_features=220)

    permission_features = autoencoder._proof_obligation_feature_keys_for(permission)
    conditional_features = autoencoder._proof_obligation_feature_keys_for(conditional)
    fallback_features = autoencoder._fallback_feature_keys_for(permission)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(permission)

    assert (
        "proof-obligation:formula-proof:"
        "prove-permission:deontic:p:clause:cno:eno:a0"
        in permission_features
    )
    assert (
        "proof-obligation:proof-route:"
        "deontic_norms:prove-permission:deontic:p:"
        "grant_authorization:conditioned+temporal"
        in permission_features
    )
    assert (
        "proof-obligation:proof-route:"
        "zkp_attestation:prove-permission:deontic:p:"
        "grant_authorization:conditioned+temporal"
        in permission_features
    )
    assert (
        "proof-obligation:compiler-proof-plan:"
        "prove-permission:"
        "modal_frame_logic+deontic_norms+fol_tdfol+cec_dcec+"
        "external_prover_router+zkp_attestation:"
        "government_actor:grant_authorization:authorization_instrument:"
        "none:none:none:conditioned+temporal"
        in permission_features
    )
    assert (
        "proof-obligation:formula-proof:"
        "prove-event-transition:dynamic:a:condition:cyes:eyes:a0"
        in conditional_features
    )
    assert (
        "proof-obligation:proof-route:"
        "cec_dcec:prove-event-transition:dynamic:a:"
        "disclose_or_notify:conditioned+excepted"
        in conditional_features
    )
    assert (
        "proof-obligation:guarded-proof:"
        "prove-guarded-duty:source-cyes:source-eyes:ir-cyes:ir-eyes:"
        "modal_frame_logic+deontic_norms+fol_tdfol+"
        "external_prover_router+zkp_attestation"
        in conditional_features
    )
    assert (
        "proof-obligation:todo-route:"
        "repair_zkp_attestation_bridge:zkp_attestation:"
        "prove-guarded-duty:conditioned+excepted"
        in conditional_features
    )
    assert (
        "proof-obligation:proof-route:"
        "deontic_norms:prove-permission:deontic:p:"
        "grant_authorization:conditioned+temporal"
        in fallback_features
    )
    assert (
        "legal-ir:proof-obligation:proof-route:"
        "deontic_norms:prove-permission:deontic:p:"
        "grant_authorization:conditioned+temporal"
        in legal_ir_features
    )


def test_proof_obligation_feature_head_transfers_permission_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="The board may grant the permit before final action.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=220,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_proof_features = set(
        family_autoencoder._proof_obligation_feature_keys_for(train)
    ).intersection(
        family_autoencoder._proof_obligation_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert (
        "proof-obligation:compiler-proof-plan:"
        "prove-permission:"
        "modal_frame_logic+deontic_norms+fol_tdfol+cec_dcec+"
        "external_prover_router+zkp_attestation:"
        "government_actor:grant_authorization:authorization_instrument:"
        "none:none:none:conditioned+temporal"
        in shared_proof_features
    )
    assert any(
        feature.startswith("proof-obligation:")
        for feature in family_autoencoder.state.feature_family_logits
    )
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=220,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert any(
        feature.startswith("proof-obligation:")
        for feature in embedding_autoencoder.state.feature_embedding_weights
    )
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_entity_binding_features_encode_role_variable_graph() -> None:
    permission = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
    )
    conditional = build_us_code_sample(
        title="5",
        section="553",
        text=(
            "If the applicant files notice, the agency must approve the permit "
            "except when records are incomplete."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(max_entity_binding_features=220)

    permission_features = autoencoder._entity_binding_feature_keys_for(permission)
    conditional_features = autoencoder._entity_binding_feature_keys_for(conditional)
    fallback_features = autoencoder._fallback_feature_keys_for(permission)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(permission)

    assert (
        "entity-binding:source-binding:"
        "government_actor:grant_authorization:authorization_instrument:"
        "none:none:none:conditioned+temporal"
        in permission_features
    )
    assert (
        "entity-binding:binding-edge:"
        "subject->action:government_actor->grant_authorization"
        in permission_features
    )
    assert (
        "entity-binding:quantifier-binding:"
        "guarded-permission-exists:deontic:p:"
        "government_actor:grant_authorization:authorization_instrument:"
        "none:none:none:conditioned+temporal"
        in permission_features
    )
    assert (
        "entity-binding:decompiler-binding-plan:"
        "guarded-permission-exists:subject->action->object->temporal:"
        "government_actor:grant_authorization:authorization_instrument:"
        "none:none:none:deontic:p"
        in permission_features
    )
    assert (
        "entity-binding:binding-edge:"
        "condition->action:eligibility_condition->grant_authorization"
        in conditional_features
    )
    assert (
        "entity-binding:binding-edge:"
        "exception->action:record_exception->grant_authorization"
        in conditional_features
    )
    assert (
        "entity-binding:formula-binding:"
        "dynamic:a:condition:disclose_or_notify:a0:cyes:eyes:"
        "government_actor:grant_authorization:authorization_instrument:"
        "eligibility_condition:record_exception:none"
        in conditional_features
    )
    assert (
        "entity-binding:quantifier-path:"
        "guarded-duty-forall->guarded-event-exists:conditioned+excepted"
        in conditional_features
    )
    assert (
        "entity-binding:todo-route:"
        "refine_predicate_argument_binding:"
        "government_actor:grant_authorization:authorization_instrument:"
        "none:none:none:deontic:p:conditioned+temporal"
        in fallback_features
    )
    assert (
        "legal-ir:entity-binding:todo-route:"
        "refine_predicate_argument_binding:"
        "government_actor:grant_authorization:authorization_instrument:"
        "none:none:none:deontic:p:conditioned+temporal"
        in legal_ir_features
    )


def test_entity_binding_feature_head_transfers_permission_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="The board may grant the permit before final action.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=220,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_entity_features = set(
        family_autoencoder._entity_binding_feature_keys_for(train)
    ).intersection(
        family_autoencoder._entity_binding_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert (
        "entity-binding:decompiler-binding-plan:"
        "guarded-permission-exists:subject->action->object->temporal:"
        "government_actor:grant_authorization:authorization_instrument:"
        "none:none:none:deontic:p"
        in shared_entity_features
    )
    assert any(
        feature.startswith("entity-binding:")
        for feature in family_autoencoder.state.feature_family_logits
    )
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=220,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert any(
        feature.startswith("entity-binding:")
        for feature in embedding_autoencoder.state.feature_embedding_weights
    )
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_defeasible_priority_features_encode_exception_and_override_scope() -> None:
    permission = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
    )
    conditional = build_us_code_sample(
        title="5",
        section="553",
        text=(
            "If the applicant files notice, the agency must approve the permit "
            "except when records are incomplete."
        ),
    )
    override = build_us_code_sample(
        title="5",
        section="554",
        text=(
            "Notwithstanding any other provision, the agency must approve the "
            "permit unless records are incomplete."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(max_defeasible_priority_features=240)

    permission_features = autoencoder._defeasible_priority_feature_keys_for(permission)
    conditional_features = autoencoder._defeasible_priority_feature_keys_for(conditional)
    override_features = autoencoder._defeasible_priority_feature_keys_for(override)
    fallback_features = autoencoder._fallback_feature_keys_for(permission)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(permission)

    assert (
        "defeasible-priority:rule-priority:"
        "temporal-guard:deontic:p:clause:grant_authorization:"
        "cno:eno:conditioned+temporal"
        in permission_features
    )
    assert (
        "defeasible-priority:decompiler-priority-plan:"
        "temporal-guard:deontic:p:"
        "government_actor:grant_authorization:authorization_instrument:"
        "none:none:none:conditioned+temporal"
        in permission_features
    )
    assert (
        "defeasible-priority:source-priority-marker:"
        "except:exception-overrides:conditioned+excepted"
        in conditional_features
    )
    assert (
        "defeasible-priority:rule-priority:"
        "exception-overrides:deontic:o:condition:grant_authorization:"
        "cyes:eyes:conditioned+excepted"
        in conditional_features
    )
    assert (
        "defeasible-priority:exception-contract:"
        "exception-overrides:record_exception:"
        "government_actor:grant_authorization:authorization_instrument:"
        "eligibility_condition:record_exception:none"
        in conditional_features
    )
    assert (
        "defeasible-priority:source-priority-marker:"
        "notwithstanding:express-override:conditioned+excepted"
        in override_features
    )
    assert (
        "defeasible-priority:priority-sequence:"
        "express-override:conditioned+excepted"
        in override_features
    )
    assert (
        "defeasible-priority:todo-route:"
        "refine_defeasible_priority_scope:temporal-guard:"
        "government_actor:grant_authorization:authorization_instrument:"
        "none:none:none:conditioned+temporal"
        in fallback_features
    )
    assert (
        "legal-ir:defeasible-priority:todo-route:"
        "refine_defeasible_priority_scope:temporal-guard:"
        "government_actor:grant_authorization:authorization_instrument:"
        "none:none:none:conditioned+temporal"
        in legal_ir_features
    )


def test_defeasible_priority_feature_head_transfers_permission_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may issue the license before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="The board may grant the permit before final action.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_priority_features = set(
        family_autoencoder._defeasible_priority_feature_keys_for(train)
    ).intersection(
        family_autoencoder._defeasible_priority_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert (
        "defeasible-priority:decompiler-priority-plan:"
        "temporal-guard:deontic:p:"
        "government_actor:grant_authorization:authorization_instrument:"
        "none:none:none:conditioned+temporal"
        in shared_priority_features
    )
    assert any(
        feature.startswith("defeasible-priority:")
        for feature in family_autoencoder.state.feature_family_logits
    )
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert any(
        feature.startswith("defeasible-priority:")
        for feature in embedding_autoencoder.state.feature_embedding_weights
    )
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_constraint_grounding_features_encode_deadlines_thresholds_and_crossrefs() -> None:
    deadline = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice within 30 days under subsection (b).",
    )
    percent = build_us_code_sample(
        title="5",
        section="553",
        text=(
            "The board may approve the permit if at least 60 percent of "
            "members vote under paragraph (1)."
        ),
    )
    money = build_us_code_sample(
        title="5",
        section="554",
        text="The person must pay $5,000 not later than 30 days after notice.",
    )
    autoencoder = AdaptiveModalAutoencoder(max_constraint_grounding_features=240)

    deadline_features = autoencoder._constraint_grounding_feature_keys_for(deadline)
    percent_features = autoencoder._constraint_grounding_feature_keys_for(percent)
    money_features = autoencoder._constraint_grounding_feature_keys_for(money)
    fallback_features = autoencoder._fallback_feature_keys_for(deadline)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(deadline)

    assert (
        "constraint-grounding:constraint-signature:"
        "temporal-deadline:within:16-31:day+"
        "statutory-crossref:under:b:subsection"
        in deadline_features
    )
    assert (
        "constraint-grounding:constraint-exact:"
        "temporal-deadline:within:30:day"
        in deadline_features
    )
    assert (
        "constraint-grounding:cross-reference-grounding:"
        "under:subsection:b:temporal"
        in deadline_features
    )
    assert (
        "constraint-grounding:todo-route:"
        "refine_quantitative_crossref_grounding:"
        "temporal-deadline:within:16-31:day+"
        "statutory-crossref:under:b:subsection:"
        "government_actor:disclose_or_notify:notice_or_record:"
        "none:none:deadline_temporal"
        in fallback_features
    )
    assert (
        "legal-ir:constraint-grounding:todo-route:"
        "refine_quantitative_crossref_grounding:"
        "temporal-deadline:within:16-31:day+"
        "statutory-crossref:under:b:subsection:"
        "government_actor:disclose_or_notify:notice_or_record:"
        "none:none:deadline_temporal"
        in legal_ir_features
    )
    assert (
        "constraint-grounding:constraint-signature:"
        "percentage-threshold:at_least:32-90:percent+"
        "statutory-crossref:under:1:paragraph"
        in percent_features
    )
    assert (
        "constraint-grounding:constraint-exact:"
        "percentage-threshold:at_least:60:percent"
        in percent_features
    )
    assert (
        "constraint-grounding:threshold-constraint:"
        "percentage-threshold:at_least:32-90:percent:"
        "authorization_instrument"
        in percent_features
    )
    assert (
        "constraint-grounding:constraint-signature:"
        "monetary-threshold:exact:1k_10k:usd+"
        "temporal-deadline:not_later_than:16-31:day"
        in money_features
    )
    assert (
        "constraint-grounding:constraint-exact:"
        "monetary-threshold:exact:5000:usd"
        in money_features
    )
    assert (
        "constraint-grounding:constraint-exact:"
        "temporal-deadline:not_later_than:30:day"
        in money_features
    )


def test_constraint_grounding_feature_head_transfers_deadline_holdout() -> None:
    shared_plan_feature = (
        "constraint-grounding:decompiler-constraint-plan:"
        "temporal-deadline:within:16-31:day+"
        "statutory-crossref:under:b:subsection:"
        "government_actor:disclose_or_notify:notice_or_record:"
        "none:none:deadline_temporal:deontic:o->temporal:f"
    )
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice within 30 days under subsection (b).",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="The board shall publish notice within 30 days under subsection (b).",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_constraint_features = set(
        family_autoencoder._constraint_grounding_feature_keys_for(train)
    ).intersection(
        family_autoencoder._constraint_grounding_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert shared_plan_feature in shared_constraint_features
    assert shared_plan_feature in family_autoencoder.state.feature_family_logits
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert shared_plan_feature in embedding_autoencoder.state.feature_embedding_weights
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_quantitative_formula_features_encode_arithmetic_ir_nodes() -> None:
    greater = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "The penalty shall be the greater of $500 or 10 percent of the "
            "payment."
        ),
    )
    lesser = build_us_code_sample(
        title="5",
        section="553",
        text="The fee shall be the lesser of $500 and actual damages.",
    )
    cap = build_us_code_sample(
        title="5",
        section="554",
        text="The civil penalty may not exceed $100 per day.",
    )
    multiplier = build_us_code_sample(
        title="5",
        section="555",
        text="The refund must equal twice the amount paid.",
    )
    summation = build_us_code_sample(
        title="5",
        section="556",
        text="The total payment shall be the sum of $100 and costs.",
    )
    autoencoder = AdaptiveModalAutoencoder(max_quantitative_formula_features=240)

    greater_features = autoencoder._quantitative_formula_feature_keys_for(greater)
    lesser_features = autoencoder._quantitative_formula_feature_keys_for(lesser)
    cap_features = autoencoder._quantitative_formula_feature_keys_for(cap)
    multiplier_features = autoencoder._quantitative_formula_feature_keys_for(
        multiplier
    )
    sum_features = autoencoder._quantitative_formula_feature_keys_for(summation)
    fallback_features = autoencoder._fallback_feature_keys_for(greater)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(greater)

    greater_signature = (
        "greater_of_formula:monetary_amount+percentage_amount->"
        "penalty_amount:obligation:computed_amount:lump_sum"
    )
    assert (
        f"quantitative-formula:formula-signature:{greater_signature}"
        in greater_features
    )
    assert (
        "quantitative-formula:compiler-arithmetic-node:"
        "greater_of_formula:monetary_amount+percentage_amount:"
        "penalty_amount:obligation"
        in greater_features
    )
    assert (
        "quantitative-formula:frame-logic-arithmetic-slot:"
        "greater_of_formula:penalty_amount:monetary_amount:"
        "percentage_amount:lump_sum"
        in greater_features
    )
    assert (
        f"quantitative-formula:decompiler-formula-plan:{greater_signature}"
        in fallback_features
    )
    assert (
        f"legal-ir:quantitative-formula:decompiler-formula-plan:"
        f"{greater_signature}"
        in legal_ir_features
    )

    assert (
        "quantitative-formula:formula-signature:"
        "lesser_of_formula:monetary_amount+damages_amount->"
        "fee_amount:obligation:upper_bound:lump_sum"
        in lesser_features
    )
    assert (
        "quantitative-formula:formula-signature:"
        "cap_formula:monetary_amount+period_amount->"
        "penalty_amount:prohibition:upper_bound:per_day"
        in cap_features
    )
    assert (
        "quantitative-formula:formula-signature:"
        "multiplier_formula:multiplier_amount+payment_amount->"
        "refund_amount:obligation:computed_amount:lump_sum"
        in multiplier_features
    )
    assert (
        "quantitative-formula:formula-signature:"
        "sum_formula:monetary_amount+cost_amount->"
        "payment_amount:obligation:computed_amount:lump_sum"
        in sum_features
    )


def test_quantitative_formula_feature_head_transfers_arithmetic_holdout() -> None:
    shared_plan_feature = (
        "quantitative-formula:decompiler-formula-plan:"
        "greater_of_formula:monetary_amount+percentage_amount->"
        "penalty_amount:obligation:computed_amount:lump_sum"
    )
    train = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "The penalty shall be the greater of $500 or 10 percent of the "
            "payment."
        ),
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text=(
            "The civil fine must equal the greater of $500 or 10 percent of "
            "the payment."
        ),
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_quantitative_formula_features=240,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_temporal_validity_features=0,
        max_evidentiary_burden_features=0,
        max_legal_relation_features=0,
        max_status_transition_features=0,
        max_condition_consequence_features=0,
        max_applicability_scope_features=0,
        max_coreference_binding_features=0,
        max_logical_connective_features=0,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_formula_features = set(
        family_autoencoder._quantitative_formula_feature_keys_for(train)
    ).intersection(
        family_autoencoder._quantitative_formula_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert shared_plan_feature in shared_formula_features
    assert shared_plan_feature in family_autoencoder.state.feature_family_logits
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_quantitative_formula_features=240,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_temporal_validity_features=0,
        max_evidentiary_burden_features=0,
        max_legal_relation_features=0,
        max_status_transition_features=0,
        max_condition_consequence_features=0,
        max_applicability_scope_features=0,
        max_coreference_binding_features=0,
        max_logical_connective_features=0,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert shared_plan_feature in embedding_autoencoder.state.feature_embedding_weights
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_definition_grounding_features_encode_terms_inclusions_and_exclusions() -> None:
    means = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "As used in this section, the term record means any information "
            "maintained by an agency."
        ),
    )
    includes = build_us_code_sample(
        title="5",
        section="553",
        text=(
            "The term license includes any permit or certification issued by "
            "the board."
        ),
    )
    excludes = build_us_code_sample(
        title="5",
        section="554",
        text=(
            "The term permit does not include a temporary waiver issued under "
            "this section."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(max_definition_grounding_features=240)

    means_features = autoencoder._definition_grounding_feature_keys_for(means)
    includes_features = autoencoder._definition_grounding_feature_keys_for(includes)
    excludes_features = autoencoder._definition_grounding_feature_keys_for(excludes)
    fallback_features = autoencoder._fallback_feature_keys_for(means)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(means)

    assert (
        "definition-grounding:definition-signature:"
        "means:record_term:notice_or_record:this_section:event_anchored"
        in means_features
    )
    assert (
        "definition-grounding:kg-definition-edge:"
        "record_term:means:notice_or_record"
        in means_features
    )
    assert (
        "definition-grounding:operator-definition:"
        "temporal:f:definition:means:record_term:notice_or_record:this_section"
        in means_features
    )
    assert (
        "definition-grounding:todo-route:"
        "refine_definition_grounding:"
        "means:record_term:notice_or_record:this_section:event_anchored:"
        "none:none:notice_or_record:none:none:none"
        in fallback_features
    )
    assert (
        "legal-ir:definition-grounding:todo-route:"
        "refine_definition_grounding:"
        "means:record_term:notice_or_record:this_section:event_anchored:"
        "none:none:notice_or_record:none:none:none"
        in legal_ir_features
    )
    assert (
        "definition-grounding:definition-signature:"
        "includes:authorization_term:authorization_instrument:"
        "unspecified_scope:enumerated+event_anchored"
        in includes_features
    )
    assert (
        "definition-grounding:subclass-expansion:"
        "authorization_term:authorization_instrument:enumerated+event_anchored"
        in includes_features
    )
    assert (
        "definition-grounding:definition-signature:"
        "excludes:authorization_term:authorization_instrument:this_section:"
        "negative_boundary+cross_reference+event_anchored"
        in excludes_features
    )
    assert (
        "definition-grounding:exclusion-boundary:"
        "authorization_term:authorization_instrument:this_section"
        in excludes_features
    )


def test_definition_grounding_feature_head_transfers_definition_holdout() -> None:
    shared_plan_feature = (
        "definition-grounding:decompiler-definition-plan:"
        "means:record_term:notice_or_record:this_section:event_anchored:"
        "none:none:notice_or_record:none:none:none:temporal:f"
    )
    train = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "As used in this section, the term record means any information "
            "maintained by an agency."
        ),
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text=(
            "As used in this section, the term document means any data "
            "maintained by a department."
        ),
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_definition_features = set(
        family_autoencoder._definition_grounding_feature_keys_for(train)
    ).intersection(
        family_autoencoder._definition_grounding_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert shared_plan_feature in shared_definition_features
    assert shared_plan_feature in family_autoencoder.state.feature_family_logits
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert shared_plan_feature in embedding_autoencoder.state.feature_embedding_weights
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_quantifier_scope_features_encode_universal_negative_and_existential_scope() -> None:
    universal = build_us_code_sample(
        title="5",
        section="552",
        text="Each agency must provide notice to every applicant before final action.",
    )
    negative = build_us_code_sample(
        title="5",
        section="553",
        text="No person may deny any permit unless the application is incomplete.",
    )
    existential = build_us_code_sample(
        title="5",
        section="554",
        text="One or more applicants may file an application only if the fee is paid.",
    )
    autoencoder = AdaptiveModalAutoencoder(max_quantifier_scope_features=240)

    universal_features = autoencoder._quantifier_scope_feature_keys_for(universal)
    negative_features = autoencoder._quantifier_scope_feature_keys_for(negative)
    existential_features = autoencoder._quantifier_scope_feature_keys_for(existential)
    fallback_features = autoencoder._fallback_feature_keys_for(universal)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(universal)

    assert (
        "quantifier-scope:quantifier-signature:"
        "universal:government_actor:subject:conditioned+temporal+"
        "universal:private_party:object:conditioned+temporal"
        in universal_features
    )
    assert (
        "quantifier-scope:fol-quantifier:forall:government_actor:subject"
        in universal_features
    )
    assert (
        "quantifier-scope:operator-quantifier:"
        "deontic:o:clause:universal:private_party:object:conditioned+temporal"
        in universal_features
    )
    assert (
        "quantifier-scope:todo-route:"
        "refine_quantifier_scope:"
        "universal:government_actor:subject:conditioned+temporal+"
        "universal:private_party:object:conditioned+temporal:"
        "government_actor:disclose_or_notify:notice_or_record:none:none:none"
        in fallback_features
    )
    assert (
        "legal-ir:quantifier-scope:todo-route:"
        "refine_quantifier_scope:"
        "universal:government_actor:subject:conditioned+temporal+"
        "universal:private_party:object:conditioned+temporal:"
        "government_actor:disclose_or_notify:notice_or_record:none:none:none"
        in legal_ir_features
    )
    assert (
        "quantifier-scope:quantifier-signature:"
        "negative_universal:private_party:subject:conditioned+"
        "universal:authorization_instrument:object:conditioned"
        in negative_features
    )
    assert (
        "quantifier-scope:fol-quantifier:forall_not:private_party:subject"
        in negative_features
    )
    assert (
        "quantifier-scope:negative-scope-binder:"
        "private_party:subject:conditioned"
        in negative_features
    )
    assert (
        "quantifier-scope:quantifier-signature:"
        "existential_min_one:private_party:subject:conditioned+"
        "existential:application_or_proof:object:conditioned+"
        "conditional_restriction:payment_or_fee:condition:conditioned"
        in existential_features
    )
    assert (
        "quantifier-scope:existential-witness:"
        "existential_min_one:private_party:subject:conditioned"
        in existential_features
    )
    assert (
        "quantifier-scope:guarded-quantifier:payment_or_fee:condition:conditioned"
        in existential_features
    )


def test_quantifier_scope_feature_head_transfers_universal_holdout() -> None:
    shared_plan_feature = (
        "quantifier-scope:decompiler-quantifier-plan:"
        "universal:government_actor:subject:conditioned+temporal+"
        "universal:private_party:object:conditioned+temporal:"
        "government_actor:disclose_or_notify:notice_or_record:"
        "none:none:none:deontic:o"
    )
    train = build_us_code_sample(
        title="5",
        section="552",
        text="Each agency must provide notice to every applicant before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="Every department shall publish notice to each applicant before final action.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_quantifier_features = set(
        family_autoencoder._quantifier_scope_feature_keys_for(train)
    ).intersection(
        family_autoencoder._quantifier_scope_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert shared_plan_feature in shared_quantifier_features
    assert shared_plan_feature in family_autoencoder.state.feature_family_logits
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert shared_plan_feature in embedding_autoencoder.state.feature_embedding_weights
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_procedural_lifecycle_features_encode_ordered_event_stages() -> None:
    procedure = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "After the applicant files an application, the agency shall provide "
            "notice, hold a hearing, and issue an order before the permit "
            "becomes effective."
        ),
    )
    review = build_us_code_sample(
        title="5",
        section="553",
        text=(
            "A person may appeal the order and seek judicial review after the "
            "agency issues a final decision."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(max_procedural_lifecycle_features=240)

    procedure_features = autoencoder._procedural_lifecycle_feature_keys_for(procedure)
    review_features = autoencoder._procedural_lifecycle_feature_keys_for(review)
    fallback_features = autoencoder._fallback_feature_keys_for(procedure)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(procedure)

    assert (
        "procedural-lifecycle:stage-sequence:"
        "initiate_filing->notice->hearing->decision->effectiveness"
        in procedure_features
    )
    assert (
        "procedural-lifecycle:stage-class-signature:"
        "initiate_filing:application_or_proof+"
        "notice:notice_or_record+hearing:proceeding_or_order+"
        "decision:proceeding_or_order+effectiveness:authorization_instrument"
        in procedure_features
    )
    assert (
        "procedural-lifecycle:event-calculus-transition:"
        "hearing->decision:filing_to_decision"
        in procedure_features
    )
    assert (
        "procedural-lifecycle:decompiler-lifecycle-plan:"
        "initiate_filing->notice->hearing->decision->effectiveness:"
        "filing_to_decision:none:none:none:none:none:none"
        in fallback_features
    )
    assert (
        "legal-ir:procedural-lifecycle:decompiler-lifecycle-plan:"
        "initiate_filing->notice->hearing->decision->effectiveness:"
        "filing_to_decision:none:none:none:none:none:none"
        in legal_ir_features
    )
    assert (
        "procedural-lifecycle:stage-sequence:appeal_review"
        in review_features
    )
    assert (
        "procedural-lifecycle:event-calculus-review:"
        "private_party:proceeding_or_order:conditioned+temporal"
        in review_features
    )


def test_procedural_lifecycle_feature_head_transfers_process_holdout() -> None:
    shared_plan_feature = (
        "procedural-lifecycle:decompiler-lifecycle-plan:"
        "initiate_filing->notice->hearing->decision->effectiveness:"
        "filing_to_decision:none:none:none:none:none:none"
    )
    train = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "After the applicant files an application, the agency shall provide "
            "notice, hold a hearing, and issue an order before the permit "
            "becomes effective."
        ),
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text=(
            "After the owner submits a claim, the department must publish "
            "notice, conduct a hearing, and grant approval before the license "
            "becomes effective."
        ),
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_lifecycle_features = set(
        family_autoencoder._procedural_lifecycle_feature_keys_for(train)
    ).intersection(
        family_autoencoder._procedural_lifecycle_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert shared_plan_feature in shared_lifecycle_features
    assert shared_plan_feature in family_autoencoder.state.feature_family_logits
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert shared_plan_feature in embedding_autoencoder.state.feature_embedding_weights
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_enforcement_remedy_features_encode_violations_and_remedies() -> None:
    liability = build_us_code_sample(
        title="15",
        section="77x",
        text=(
            "A person who violates this section shall be liable for a civil "
            "penalty."
        ),
    )
    agency_sanction = build_us_code_sample(
        title="7",
        section="13a",
        text=(
            "The agency may impose a sanction for each violation of this "
            "chapter."
        ),
    )
    court_injunction = build_us_code_sample(
        title="28",
        section="1651",
        text=(
            "The court may enjoin a person who fails to comply with the "
            "order."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(max_enforcement_remedy_features=240)

    liability_features = autoencoder._enforcement_remedy_feature_keys_for(liability)
    agency_features = autoencoder._enforcement_remedy_feature_keys_for(
        agency_sanction
    )
    court_features = autoencoder._enforcement_remedy_feature_keys_for(
        court_injunction
    )
    fallback_features = autoencoder._fallback_feature_keys_for(liability)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(liability)

    liability_signature = (
        "statutory_violation:this_section->civil_penalty:"
        "payment_or_fee:none:strict_or_unspecified:private_party"
    )
    assert (
        f"enforcement-remedy:enforcement-signature:{liability_signature}"
        in liability_features
    )
    assert (
        "enforcement-remedy:event-calculus-enforcement:"
        "statutory_violation->civil_penalty:this_section"
        in liability_features
    )
    assert (
        "enforcement-remedy:operator-enforcement:"
        "deontic:o:remedy:civil_penalty:payment_or_fee:"
        "private_party:strict_or_unspecified"
        in liability_features
    )
    assert (
        f"enforcement-remedy:decompiler-enforcement-plan:{liability_signature}"
        in fallback_features
    )
    assert (
        f"legal-ir:enforcement-remedy:decompiler-enforcement-plan:"
        f"{liability_signature}"
        in legal_ir_features
    )
    assert (
        "enforcement-remedy:todo-route:refine_enforcement_remedy:"
        f"{liability_signature}"
        in liability_features
    )

    assert (
        "enforcement-remedy:remedy:administrative_sanction:"
        "administrative_sanction:government_actor:none:"
        "strict_or_unspecified"
        in agency_features
    )
    assert (
        "enforcement-remedy:enforcement-actor:"
        "government_actor:impose:administrative_sanction"
        in agency_features
    )
    assert (
        "enforcement-remedy:violation-trigger:"
        "noncompliance:the_order:private_party"
        in court_features
    )
    assert (
        "enforcement-remedy:remedy:injunction:private_party:"
        "judicial_actor:private_party:strict_or_unspecified"
        in court_features
    )
    assert (
        "enforcement-remedy:event-calculus-enforcement:"
        "noncompliance->injunction:the_order"
        in court_features
    )


def test_enforcement_remedy_feature_head_transfers_liability_holdout() -> None:
    shared_plan_feature = (
        "enforcement-remedy:decompiler-enforcement-plan:"
        "statutory_violation:this_section->civil_penalty:"
        "payment_or_fee:none:strict_or_unspecified:private_party"
    )
    train = build_us_code_sample(
        title="15",
        section="77x",
        text=(
            "A person who violates this section shall be liable for a civil "
            "penalty."
        ),
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="42",
        section="1320a-7a",
        text=(
            "Any owner that violates this section shall be subject to a civil "
            "fine."
        ),
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_enforcement_features = set(
        family_autoencoder._enforcement_remedy_feature_keys_for(train)
    ).intersection(
        family_autoencoder._enforcement_remedy_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert shared_plan_feature in shared_enforcement_features
    assert shared_plan_feature in family_autoencoder.state.feature_family_logits
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert shared_plan_feature in embedding_autoencoder.state.feature_embedding_weights
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_mental_state_features_encode_culpability_and_knowledge_gates() -> None:
    knowing = build_us_code_sample(
        title="15",
        section="77x",
        text=(
            "A person who knowingly violates this section shall be liable "
            "for a civil penalty."
        ),
    )
    reason_to_know = build_us_code_sample(
        title="15",
        section="78u",
        text="A person has reason to know the statement is false.",
    )
    negligent = build_us_code_sample(
        title="7",
        section="13a",
        text="A licensee negligently fails to comply with the order.",
    )
    lack_of_intent = build_us_code_sample(
        title="5",
        section="552",
        text="A person may correct the record without intent to deceive.",
    )
    autoencoder = AdaptiveModalAutoencoder(max_mental_state_features=240)

    knowing_features = autoencoder._mental_state_feature_keys_for(knowing)
    reason_features = autoencoder._mental_state_feature_keys_for(reason_to_know)
    negligent_features = autoencoder._mental_state_feature_keys_for(negligent)
    lack_features = autoencoder._mental_state_feature_keys_for(lack_of_intent)
    fallback_features = autoencoder._fallback_feature_keys_for(knowing)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(knowing)

    knowing_signature = (
        "knowing:private_party:statutory_violation:obligation:"
        "affirmative_mental_state:liability_scope"
    )
    assert (
        f"mental-state:mental-state-signature:{knowing_signature}"
        in knowing_features
    )
    assert (
        "mental-state:compiler-mental-state-gate:"
        "knowing:private_party:statutory_violation:liability_scope"
        in knowing_features
    )
    assert (
        "mental-state:frame-logic-mental-slot:"
        "private_party:knowing:statutory_violation:liability_scope"
        in knowing_features
    )
    assert (
        f"mental-state:decompiler-mental-state-plan:{knowing_signature}"
        in fallback_features
    )
    assert (
        f"legal-ir:mental-state:decompiler-mental-state-plan:"
        f"{knowing_signature}"
        in legal_ir_features
    )

    assert (
        "mental-state:mental-state-signature:"
        "reason_to_know:private_party:material_fact:assertive:"
        "affirmative_mental_state:general_scope"
        in reason_features
    )
    assert (
        "mental-state:culpability-edge:"
        "negligent:private_party:noncompliance:assertive:"
        "affirmative_mental_state"
        in negligent_features
    )
    assert (
        "mental-state:mental-state-signature:"
        "lack_of_intent:private_party:legal_conduct:permission:"
        "negated_mental_state:disclosure_scope"
        in lack_features
    )


def test_mental_state_feature_head_transfers_culpability_holdout() -> None:
    shared_plan_feature = (
        "mental-state:decompiler-mental-state-plan:"
        "knowing:private_party:statutory_violation:obligation:"
        "affirmative_mental_state:liability_scope"
    )
    train = build_us_code_sample(
        title="15",
        section="77x",
        text=(
            "A person who knowingly violates this section shall be liable "
            "for a civil penalty."
        ),
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="42",
        section="1320a-7a",
        text=(
            "Any owner that knowingly violates this section shall be subject "
            "to a civil fine."
        ),
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_quantitative_formula_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_mental_state_features=240,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_discretion_standard_features=0,
        max_temporal_validity_features=0,
        max_evidentiary_burden_features=0,
        max_legal_relation_features=0,
        max_status_transition_features=0,
        max_condition_consequence_features=0,
        max_applicability_scope_features=0,
        max_coreference_binding_features=0,
        max_logical_connective_features=0,
        max_enumeration_hierarchy_features=0,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_mental_features = set(
        family_autoencoder._mental_state_feature_keys_for(train)
    ).intersection(
        family_autoencoder._mental_state_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert shared_plan_feature in shared_mental_features
    assert shared_plan_feature in family_autoencoder.state.feature_family_logits
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_quantitative_formula_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_mental_state_features=240,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_discretion_standard_features=0,
        max_temporal_validity_features=0,
        max_evidentiary_burden_features=0,
        max_legal_relation_features=0,
        max_status_transition_features=0,
        max_condition_consequence_features=0,
        max_applicability_scope_features=0,
        max_coreference_binding_features=0,
        max_logical_connective_features=0,
        max_enumeration_hierarchy_features=0,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert shared_plan_feature in embedding_autoencoder.state.feature_embedding_weights
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_reference_dependency_features_encode_imports_and_applicability() -> None:
    exception_import = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "Except as provided in subsection (b), the agency shall approve "
            "the application."
        ),
    )
    authority_import = build_us_code_sample(
        title="5",
        section="553",
        text="The person shall file a report under section 552.",
    )
    applicability = build_us_code_sample(
        title="42",
        section="1320a",
        text="The requirements of this section shall apply to each licensee.",
    )
    exclusion = build_us_code_sample(
        title="42",
        section="1320b",
        text="This subsection does not apply to a small business.",
    )
    autoencoder = AdaptiveModalAutoencoder(max_reference_dependency_features=240)

    exception_features = autoencoder._reference_dependency_feature_keys_for(
        exception_import
    )
    authority_features = autoencoder._reference_dependency_feature_keys_for(
        authority_import
    )
    applicability_features = autoencoder._reference_dependency_feature_keys_for(
        applicability
    )
    exclusion_features = autoencoder._reference_dependency_feature_keys_for(
        exclusion
    )
    fallback_features = autoencoder._fallback_feature_keys_for(exception_import)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(
        exception_import
    )

    exception_signature = "exception_import:local_subdivision:conditioned+excepted"
    assert (
        f"reference-dependency:reference-signature:{exception_signature}"
        in exception_features
    )
    assert (
        "reference-dependency:reference-exact:"
        "exception_import:subsection:b:except_as_provided_in"
        in exception_features
    )
    assert (
        "reference-dependency:defeasible-reference:"
        "exception:local_subdivision:conditioned+excepted"
        in exception_features
    )
    assert (
        "reference-dependency:operator-reference:"
        "conditional_normative:o:condition:"
        "exception_import:local_subdivision"
        in exception_features
    )
    assert (
        f"reference-dependency:decompiler-reference-plan:{exception_signature}"
        in fallback_features
    )
    assert (
        f"legal-ir:reference-dependency:decompiler-reference-plan:"
        f"{exception_signature}"
        in legal_ir_features
    )

    assert (
        "reference-dependency:reference-exact:"
        "authority_import:section:552:under"
        in authority_features
    )
    assert (
        "reference-dependency:compiler-import-edge:"
        "authority_import:statutory_section:unscoped"
        in authority_features
    )
    assert (
        "reference-dependency:applicability-reference:"
        "applicability_scope:current_section:positive"
        in applicability_features
    )
    assert (
        "reference-dependency:applicability-reference:"
        "applicability_exclusion:current_subdivision:exceptional"
        in exclusion_features
    )
    assert (
        "reference-dependency:decompiler-reference-plan:"
        "applicability_exclusion:current_subdivision:unscoped"
        in exclusion_features
    )


def test_reference_dependency_feature_head_transfers_citation_holdout() -> None:
    shared_plan_feature = (
        "reference-dependency:decompiler-reference-plan:"
        "exception_import:local_subdivision:conditioned+excepted"
    )
    train = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "Except as provided in subsection (b), the agency shall approve "
            "the application."
        ),
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text=(
            "Except as provided in paragraph (2), the department must grant "
            "the license."
        ),
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_reference_features = set(
        family_autoencoder._reference_dependency_feature_keys_for(train)
    ).intersection(
        family_autoencoder._reference_dependency_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert shared_plan_feature in shared_reference_features
    assert shared_plan_feature in family_autoencoder.state.feature_family_logits
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert shared_plan_feature in embedding_autoencoder.state.feature_embedding_weights
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def _amendment_operation_only_feature_kwargs() -> dict[str, int]:
    return {
        "max_compiler_latent_profile_features": 0,
        "max_round_trip_bridge_features": 0,
        "max_clause_topology_features": 0,
        "max_legal_semantic_frame_features": 0,
        "max_normative_polarity_features": 0,
        "max_compiler_contract_features": 0,
        "max_decompiler_surface_template_features": 0,
        "max_canonical_ir_graph_features": 0,
        "max_cycle_consistency_features": 0,
        "max_equivalence_prototype_features": 0,
        "max_contrastive_ir_boundary_features": 0,
        "max_repair_plan_features": 0,
        "max_logic_view_contract_features": 0,
        "max_objective_residual_features": 0,
        "max_provenance_alignment_features": 0,
        "max_discourse_flow_features": 0,
        "max_proof_obligation_features": 0,
        "max_entity_binding_features": 0,
        "max_defeasible_priority_features": 0,
        "max_constraint_grounding_features": 0,
        "max_quantitative_formula_features": 0,
        "max_definition_grounding_features": 0,
        "max_quantifier_scope_features": 0,
        "max_procedural_lifecycle_features": 0,
        "max_enforcement_remedy_features": 0,
        "max_mental_state_features": 0,
        "max_reference_dependency_features": 0,
        "max_amendment_operation_features": 240,
        "max_authority_jurisdiction_features": 0,
        "max_discretion_standard_features": 0,
        "max_temporal_validity_features": 0,
        "max_evidentiary_burden_features": 0,
        "max_legal_relation_features": 0,
        "max_status_transition_features": 0,
        "max_condition_consequence_features": 0,
        "max_applicability_scope_features": 0,
        "max_coreference_binding_features": 0,
        "max_logical_connective_features": 0,
        "max_enumeration_hierarchy_features": 0,
        "max_token_features": 0,
        "max_token_bigram_features": 0,
        "max_token_trigram_features": 0,
    }


def test_amendment_operation_features_encode_text_and_structural_edits() -> None:
    replacement = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "Section 552 shall be amended by striking old text and "
            "inserting new text."
        ),
    )
    addition = build_us_code_sample(
        title="5",
        section="553",
        text="Subsection (a) is amended by adding at the end the following text.",
    )
    redesignation = build_us_code_sample(
        title="5",
        section="554",
        text="Section 554 is amended by redesignating paragraph (1) as paragraph (2).",
    )
    repeal = build_us_code_sample(
        title="5",
        section="555",
        text="Section 555 is repealed.",
    )
    autoencoder = AdaptiveModalAutoencoder(max_amendment_operation_features=240)

    replacement_features = autoencoder._amendment_operation_feature_keys_for(
        replacement
    )
    addition_features = autoencoder._amendment_operation_feature_keys_for(addition)
    redesignation_features = autoencoder._amendment_operation_feature_keys_for(
        redesignation
    )
    repeal_features = autoencoder._amendment_operation_feature_keys_for(repeal)
    fallback_features = autoencoder._fallback_feature_keys_for(replacement)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(replacement)

    replacement_signature = (
        "replace_text:statutory_section:text_fragment->text_fragment:"
        "positive_amendment:textual_scope"
    )
    assert (
        f"amendment-operation:amendment-signature:{replacement_signature}"
        in replacement_features
    )
    assert (
        "amendment-operation:compiler-amendment-node:"
        "replace_text:statutory_section:text_fragment->text_fragment:textual_scope"
        in replacement_features
    )
    assert (
        "amendment-operation:operator-amendment:"
        "deontic:o:clause:replace_text:statutory_section:positive_amendment"
        in replacement_features
    )
    assert (
        f"amendment-operation:decompiler-amendment-plan:{replacement_signature}"
        in fallback_features
    )
    assert (
        f"legal-ir:amendment-operation:decompiler-amendment-plan:"
        f"{replacement_signature}"
        in legal_ir_features
    )

    assert (
        "amendment-operation:operation:"
        "add_text:local_subdivision:none->introduced_text:textual_scope"
        in addition_features
    )
    assert (
        "amendment-operation:structural-redesignation:"
        "statutory_section:paragraph_reference->paragraph_reference"
        in redesignation_features
    )
    assert (
        "amendment-operation:structural-repeal:"
        "statutory_section:negative_amendment:structural_scope"
        in repeal_features
    )


def test_amendment_operation_feature_head_transfers_edit_holdout() -> None:
    shared_plan_feature = (
        "amendment-operation:decompiler-amendment-plan:"
        "replace_text:statutory_section:text_fragment->text_fragment:"
        "positive_amendment:textual_scope"
    )
    train = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "Section 552 shall be amended by striking old text and "
            "inserting new text."
        ),
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text=(
            "Section 1841 shall be amended by striking obsolete language and "
            "inserting revised language."
        ),
        embedding_vector=[1.0, 0.0],
    )
    feature_kwargs = _amendment_operation_only_feature_kwargs()
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        **feature_kwargs,
    )
    shared_amendment_features = set(
        family_autoencoder._amendment_operation_feature_keys_for(train)
    ).intersection(
        family_autoencoder._amendment_operation_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert shared_plan_feature in shared_amendment_features
    assert shared_plan_feature in family_autoencoder.state.feature_family_logits
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        cosine_reconstruction_weight=0.0,
        **feature_kwargs,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert shared_plan_feature in embedding_autoencoder.state.feature_embedding_weights
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_authority_jurisdiction_features_encode_power_scope_and_preemption() -> None:
    rulemaking = build_us_code_sample(
        title="5",
        section="552",
        text="The Secretary may prescribe regulations to carry out this section.",
    )
    waiver = build_us_code_sample(
        title="5",
        section="553",
        text=(
            "The agency is authorized to grant a waiver under this "
            "subsection."
        ),
    )
    preemption = build_us_code_sample(
        title="49",
        section="14501",
        text=(
            "No State may establish or enforce any requirement relating to "
            "this subject."
        ),
    )
    jurisdiction = build_us_code_sample(
        title="28",
        section="1331",
        text="The court has jurisdiction over any action under this chapter.",
    )
    autoencoder = AdaptiveModalAutoencoder(
        max_authority_jurisdiction_features=240
    )

    rulemaking_features = autoencoder._authority_jurisdiction_feature_keys_for(
        rulemaking
    )
    waiver_features = autoencoder._authority_jurisdiction_feature_keys_for(waiver)
    preemption_features = autoencoder._authority_jurisdiction_feature_keys_for(
        preemption
    )
    jurisdiction_features = autoencoder._authority_jurisdiction_feature_keys_for(
        jurisdiction
    )
    fallback_features = autoencoder._fallback_feature_keys_for(rulemaking)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(rulemaking)

    rulemaking_signature = (
        "rulemaking_authority:government_actor:rulemaking_instrument:"
        "local_statutory_scope:positive"
    )
    assert (
        f"authority-jurisdiction:authority-signature:{rulemaking_signature}"
        in rulemaking_features
    )
    assert (
        "authority-jurisdiction:rulemaking-power:"
        "government_actor:rulemaking_instrument:"
        "local_statutory_scope:positive"
        in rulemaking_features
    )
    assert (
        "authority-jurisdiction:operator-authority:"
        "deontic:p:clause:rulemaking_authority:"
        "government_actor:rulemaking_instrument:positive"
        in rulemaking_features
    )
    assert (
        f"authority-jurisdiction:decompiler-authority-plan:"
        f"{rulemaking_signature}"
        in fallback_features
    )
    assert (
        f"legal-ir:authority-jurisdiction:decompiler-authority-plan:"
        f"{rulemaking_signature}"
        in legal_ir_features
    )

    assert (
        "authority-jurisdiction:authority-grant:"
        "waiver_authority:government_actor:waiver_instrument:"
        "local_statutory_scope:positive"
        in waiver_features
    )
    assert (
        "authority-jurisdiction:preemption-edge:"
        "state_actor:legal_requirement:state_law_scope:preemptive"
        in preemption_features
    )
    assert (
        "authority-jurisdiction:decompiler-authority-plan:"
        "preemption_limit:state_actor:legal_requirement:"
        "state_law_scope:preemptive"
        in preemption_features
    )
    assert (
        "authority-jurisdiction:forum-authority:"
        "judicial_actor:adjudicatory_instrument:"
        "local_statutory_scope:positive"
        in jurisdiction_features
    )


def test_authority_jurisdiction_feature_head_transfers_rulemaking_holdout() -> None:
    shared_plan_feature = (
        "authority-jurisdiction:decompiler-authority-plan:"
        "rulemaking_authority:government_actor:rulemaking_instrument:"
        "local_statutory_scope:positive"
    )
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The Secretary may prescribe regulations to carry out this section.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="The Commission may issue rules to implement this chapter.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_authority_features = set(
        family_autoencoder._authority_jurisdiction_feature_keys_for(train)
    ).intersection(
        family_autoencoder._authority_jurisdiction_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert shared_plan_feature in shared_authority_features
    assert shared_plan_feature in family_autoencoder.state.feature_family_logits
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert shared_plan_feature in embedding_autoencoder.state.feature_embedding_weights
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_discretion_standard_features_encode_evaluative_gates() -> None:
    necessity = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "The Secretary may grant a waiver if the Secretary determines "
            "that the waiver is necessary."
        ),
    )
    reasonable = build_us_code_sample(
        title="28",
        section="1920",
        text="The court may award fees as the court determines reasonable.",
    )
    good_cause = build_us_code_sample(
        title="5",
        section="553",
        text="The agency may extend the deadline for good cause shown.",
    )
    public_interest = build_us_code_sample(
        title="15",
        section="78w",
        text=(
            "The Commission may issue rules when the Commission finds that "
            "the rule is in the public interest."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(
        max_discretion_standard_features=240
    )

    necessity_features = autoencoder._discretion_standard_feature_keys_for(
        necessity
    )
    reasonable_features = autoencoder._discretion_standard_feature_keys_for(
        reasonable
    )
    good_cause_features = autoencoder._discretion_standard_feature_keys_for(
        good_cause
    )
    public_interest_features = autoencoder._discretion_standard_feature_keys_for(
        public_interest
    )
    fallback_features = autoencoder._fallback_feature_keys_for(necessity)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(necessity)

    necessity_signature = (
        "discretionary_determination:government_actor:necessity_standard:"
        "authorization_instrument:permission:epistemic_gate:instrument_scope"
    )
    assert (
        f"discretion-standard:standard-signature:{necessity_signature}"
        in necessity_features
    )
    assert (
        "discretion-standard:compiler-discretion-gate:"
        "discretionary_determination:government_actor:"
        "authorization_instrument:necessity_standard:epistemic_gate"
        in necessity_features
    )
    assert (
        "discretion-standard:frame-logic-standard-slot:"
        "government_actor:necessity_standard:"
        "authorization_instrument:instrument_scope"
        in necessity_features
    )
    assert (
        f"discretion-standard:decompiler-standard-plan:{necessity_signature}"
        in fallback_features
    )
    assert (
        f"legal-ir:discretion-standard:decompiler-standard-plan:"
        f"{necessity_signature}"
        in legal_ir_features
    )

    assert (
        "discretion-standard:standard-signature:"
        "judicial_finding:judicial_actor:reasonableness_standard:"
        "payment_or_fee:permission:evaluative_gate:payment_scope"
        in reasonable_features
    )
    assert (
        "discretion-standard:standard-edge:"
        "good_cause_finding:government_actor:good_cause_standard:"
        "deadline_condition:permission"
        in good_cause_features
    )
    assert (
        "discretion-standard:standard-signature:"
        "public_interest_determination:government_actor:"
        "public_interest_standard:rulemaking_instrument:"
        "permission:epistemic_gate:rulemaking_scope"
        in public_interest_features
    )


def test_discretion_standard_feature_head_transfers_determination_holdout() -> None:
    shared_plan_feature = (
        "discretion-standard:decompiler-standard-plan:"
        "discretionary_determination:government_actor:necessity_standard:"
        "authorization_instrument:permission:epistemic_gate:instrument_scope"
    )
    train = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "The Secretary may grant a waiver if the Secretary determines "
            "that the waiver is necessary."
        ),
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text=(
            "The Administrator may issue an exemption if the Administrator "
            "finds that the exemption is necessary."
        ),
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_quantitative_formula_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_discretion_standard_features=240,
        max_temporal_validity_features=0,
        max_evidentiary_burden_features=0,
        max_legal_relation_features=0,
        max_status_transition_features=0,
        max_condition_consequence_features=0,
        max_applicability_scope_features=0,
        max_coreference_binding_features=0,
        max_logical_connective_features=0,
        max_enumeration_hierarchy_features=0,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_standard_features = set(
        family_autoencoder._discretion_standard_feature_keys_for(train)
    ).intersection(
        family_autoencoder._discretion_standard_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert shared_plan_feature in shared_standard_features
    assert shared_plan_feature in family_autoencoder.state.feature_family_logits
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_quantitative_formula_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_discretion_standard_features=240,
        max_temporal_validity_features=0,
        max_evidentiary_burden_features=0,
        max_legal_relation_features=0,
        max_status_transition_features=0,
        max_condition_consequence_features=0,
        max_applicability_scope_features=0,
        max_coreference_binding_features=0,
        max_logical_connective_features=0,
        max_enumeration_hierarchy_features=0,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert shared_plan_feature in embedding_autoencoder.state.feature_embedding_weights
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_temporal_validity_features_encode_effective_sunset_and_retroactivity() -> None:
    effective = build_us_code_sample(
        title="5",
        section="552",
        text="This section shall take effect on January 1, 2027.",
    )
    sunset = build_us_code_sample(
        title="5",
        section="553",
        text="This section expires 5 years after the date of enactment.",
    )
    retroactive = build_us_code_sample(
        title="26",
        section="7805",
        text=(
            "This amendment applies retroactively to claims filed before "
            "January 1, 2020."
        ),
    )
    applicability = build_us_code_sample(
        title="42",
        section="1320a",
        text="The rule applies to applications submitted after July 1, 2026.",
    )
    transition = build_us_code_sample(
        title="42",
        section="1320b",
        text=(
            "The transition rule shall apply during the 2-year period after "
            "enactment."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(max_temporal_validity_features=240)

    effective_features = autoencoder._temporal_validity_feature_keys_for(effective)
    sunset_features = autoencoder._temporal_validity_feature_keys_for(sunset)
    retroactive_features = autoencoder._temporal_validity_feature_keys_for(
        retroactive
    )
    applicability_features = autoencoder._temporal_validity_feature_keys_for(
        applicability
    )
    transition_features = autoencoder._temporal_validity_feature_keys_for(transition)
    fallback_features = autoencoder._fallback_feature_keys_for(effective)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(effective)

    effective_signature = (
        "effective_start:norm_unit:calendar_date:"
        "prospective:local_statutory_scope"
    )
    assert (
        f"temporal-validity:validity-signature:{effective_signature}"
        in effective_features
    )
    assert (
        "temporal-validity:validity-exact:"
        "effective_start:take_effect:january_1_2027:calendar_date"
        in effective_features
    )
    assert (
        "temporal-validity:effective-date:"
        "norm_unit:calendar_date:local_statutory_scope:prospective"
        in effective_features
    )
    assert (
        f"temporal-validity:decompiler-validity-plan:{effective_signature}"
        in fallback_features
    )
    assert (
        f"legal-ir:temporal-validity:decompiler-validity-plan:"
        f"{effective_signature}"
        in legal_ir_features
    )

    assert (
        "temporal-validity:sunset-expiration:"
        "norm_unit:relative_duration:local_statutory_scope:expiring"
        in sunset_features
    )
    assert (
        "temporal-validity:validity-exact:"
        "validity_end:expires:5_years_after_the_date_of_enactment:4-7_year"
        in sunset_features
    )
    assert (
        "temporal-validity:retroactivity:"
        "case_or_claim:before:calendar_date:case_or_claim_scope"
        in retroactive_features
    )
    assert (
        "temporal-validity:applicability-date:"
        "application_or_authorization:after:calendar_date:application_scope"
        in applicability_features
    )
    assert (
        "temporal-validity:transition-window:"
        "rule_unit:relative_duration:enactment_scope:transition"
        in transition_features
    )


def test_temporal_validity_feature_head_transfers_effective_date_holdout() -> None:
    shared_plan_feature = (
        "temporal-validity:decompiler-validity-plan:"
        "effective_start:norm_unit:calendar_date:"
        "prospective:local_statutory_scope"
    )
    train = build_us_code_sample(
        title="5",
        section="552",
        text="This section shall take effect on January 1, 2027.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="This Act shall take effect on July 1, 2027.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_temporal_validity_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_validity_features = set(
        family_autoencoder._temporal_validity_feature_keys_for(train)
    ).intersection(
        family_autoencoder._temporal_validity_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert shared_plan_feature in shared_validity_features
    assert shared_plan_feature in family_autoencoder.state.feature_family_logits
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_temporal_validity_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert shared_plan_feature in embedding_autoencoder.state.feature_embedding_weights
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_evidentiary_burden_features_encode_standards_and_presumptions() -> None:
    burden = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "The applicant bears the burden of proof to establish eligibility "
            "by a preponderance of the evidence."
        ),
    )
    presumption = build_us_code_sample(
        title="5",
        section="553",
        text=(
            "A record is presumed valid unless rebutted by clear and "
            "convincing evidence."
        ),
    )
    prima_facie = build_us_code_sample(
        title="5",
        section="554",
        text="The certificate is prima facie evidence of compliance.",
    )
    government_proof = build_us_code_sample(
        title="15",
        section="78u",
        text="The agency must prove a violation by substantial evidence.",
    )
    exception_burden = build_us_code_sample(
        title="15",
        section="78v",
        text="The party asserting an exception bears the burden of proof.",
    )
    autoencoder = AdaptiveModalAutoencoder(max_evidentiary_burden_features=240)

    burden_features = autoencoder._evidentiary_burden_feature_keys_for(burden)
    presumption_features = autoencoder._evidentiary_burden_feature_keys_for(
        presumption
    )
    prima_facie_features = autoencoder._evidentiary_burden_feature_keys_for(
        prima_facie
    )
    government_features = autoencoder._evidentiary_burden_feature_keys_for(
        government_proof
    )
    exception_features = autoencoder._evidentiary_burden_feature_keys_for(
        exception_burden
    )
    fallback_features = autoencoder._fallback_feature_keys_for(burden)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(burden)

    burden_signature = (
        "burden_of_proof:private_party:eligibility_issue:"
        "preponderance:persuasion_burden"
    )
    assert (
        f"evidentiary-burden:burden-signature:{burden_signature}"
        in burden_features
    )
    assert (
        "evidentiary-burden:proof-burden:"
        "private_party:eligibility_issue:preponderance:persuasion_burden"
        in burden_features
    )
    assert (
        "evidentiary-burden:standard-of-proof:"
        "preponderance:burden_of_proof:private_party:eligibility_issue"
        in burden_features
    )
    assert (
        f"evidentiary-burden:decompiler-burden-plan:{burden_signature}"
        in fallback_features
    )
    assert (
        f"legal-ir:evidentiary-burden:decompiler-burden-plan:"
        f"{burden_signature}"
        in legal_ir_features
    )

    assert (
        "evidentiary-burden:presumption:"
        "rebuttable_presumption:record_issue:"
        "clear_and_convincing:rebuttal_burden"
        in presumption_features
    )
    assert (
        "evidentiary-burden:evidence-rule:"
        "prima_facie_evidence:compliance_issue:"
        "prima_facie:production_burden"
        in prima_facie_features
    )
    assert (
        "evidentiary-burden:proof-burden:"
        "government_actor:violation_issue:"
        "substantial_evidence:persuasion_burden"
        in government_features
    )
    assert (
        "evidentiary-burden:proof-burden:"
        "private_party:exception_issue:"
        "unspecified_standard:persuasion_burden"
        in exception_features
    )


def test_evidentiary_burden_feature_head_transfers_burden_holdout() -> None:
    shared_plan_feature = (
        "evidentiary-burden:decompiler-burden-plan:"
        "burden_of_proof:private_party:eligibility_issue:"
        "preponderance:persuasion_burden"
    )
    train = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "The applicant bears the burden of proof to establish eligibility "
            "by a preponderance of the evidence."
        ),
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text=(
            "An owner has the burden to prove eligibility by a preponderance "
            "of the evidence."
        ),
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_temporal_validity_features=0,
        max_evidentiary_burden_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_burden_features = set(
        family_autoencoder._evidentiary_burden_feature_keys_for(train)
    ).intersection(
        family_autoencoder._evidentiary_burden_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert shared_plan_feature in shared_burden_features
    assert shared_plan_feature in family_autoencoder.state.feature_family_logits
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_temporal_validity_features=0,
        max_evidentiary_burden_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert shared_plan_feature in embedding_autoencoder.state.feature_embedding_weights
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_legal_relation_features_encode_hohfeld_correlatives() -> None:
    right = build_us_code_sample(
        title="5",
        section="552",
        text="The applicant has a right to inspect records from the agency.",
    )
    duty = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall provide notice to the applicant.",
    )
    privilege = build_us_code_sample(
        title="5",
        section="554",
        text="A person may file an appeal.",
    )
    power = build_us_code_sample(
        title="7",
        section="13",
        text="The Secretary may revoke a license.",
    )
    liability = build_us_code_sample(
        title="7",
        section="14",
        text="The licensee is subject to revocation.",
    )
    immunity = build_us_code_sample(
        title="28",
        section="2679",
        text="The officer is immune from liability.",
    )
    disability = build_us_code_sample(
        title="42",
        section="1983",
        text="The agency may not revoke a license.",
    )
    autoencoder = AdaptiveModalAutoencoder(max_legal_relation_features=240)

    right_features = autoencoder._legal_relation_feature_keys_for(right)
    duty_features = autoencoder._legal_relation_feature_keys_for(duty)
    privilege_features = autoencoder._legal_relation_feature_keys_for(privilege)
    power_features = autoencoder._legal_relation_feature_keys_for(power)
    liability_features = autoencoder._legal_relation_feature_keys_for(liability)
    immunity_features = autoencoder._legal_relation_feature_keys_for(immunity)
    disability_features = autoencoder._legal_relation_feature_keys_for(disability)
    fallback_features = autoencoder._fallback_feature_keys_for(right)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(right)

    right_signature = (
        "right_duty:private_party:government_actor:notice_or_record:"
        "investigate_or_enforce:positive:general_scope"
    )
    assert (
        f"legal-relation:relation-signature:{right_signature}"
        in right_features
    )
    assert (
        "legal-relation:hohfeld-relation:"
        "right_duty:private_party:government_actor:"
        "notice_or_record:investigate_or_enforce:positive"
        in right_features
    )
    assert (
        "legal-relation:correlative:right->duty:"
        "private_party->government_actor:"
        "notice_or_record:investigate_or_enforce"
        in right_features
    )
    assert (
        "legal-relation:claim-right:"
        "private_party:government_actor:"
        "notice_or_record:investigate_or_enforce"
        in right_features
    )
    assert (
        f"legal-relation:decompiler-relation-plan:{right_signature}"
        in fallback_features
    )
    assert (
        f"legal-ir:legal-relation:decompiler-relation-plan:{right_signature}"
        in legal_ir_features
    )

    assert (
        "legal-relation:legal-duty:government_actor:private_party:"
        "notice_or_record:disclose_or_notify"
        in duty_features
    )
    assert (
        "legal-relation:privilege-liberty:"
        "private_party:proceeding_or_order:submit_or_file:positive"
        in privilege_features
    )
    assert (
        "legal-relation:legal-power:government_actor:private_party:"
        "authorization_instrument:deny_or_revoke"
        in power_features
    )
    assert (
        "legal-relation:legal-liability:private_party:government_actor:"
        "authorization_instrument:deny_or_revoke"
        in liability_features
    )
    assert (
        "legal-relation:legal-immunity:government_actor:private_party:"
        "liability_or_penalty:enforcement_liability"
        in immunity_features
    )
    assert (
        "legal-relation:legal-disability:government_actor:private_party:"
        "authorization_instrument:deny_or_revoke"
        in disability_features
    )


def test_legal_relation_feature_head_transfers_privilege_holdout() -> None:
    shared_plan_feature = (
        "legal-relation:decompiler-relation-plan:"
        "privilege_no_right:private_party:government_actor:"
        "proceeding_or_order:submit_or_file:positive:general_scope"
    )
    train = build_us_code_sample(
        title="5",
        section="552",
        text="A person may file an appeal.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="An owner may submit an appeal.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_temporal_validity_features=0,
        max_evidentiary_burden_features=0,
        max_legal_relation_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_relation_features = set(
        family_autoencoder._legal_relation_feature_keys_for(train)
    ).intersection(
        family_autoencoder._legal_relation_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert shared_plan_feature in shared_relation_features
    assert shared_plan_feature in family_autoencoder.state.feature_family_logits
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_temporal_validity_features=0,
        max_evidentiary_burden_features=0,
        max_legal_relation_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert shared_plan_feature in embedding_autoencoder.state.feature_embedding_weights
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_status_transition_features_encode_legal_state_machines() -> None:
    revoke = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may revoke a license.",
    )
    issue = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall issue a license.",
    )
    effective = build_us_code_sample(
        title="5",
        section="554",
        text="The permit becomes effective.",
    )
    expiration = build_us_code_sample(
        title="5",
        section="555",
        text="The certificate expires after five years.",
    )
    eligible = build_us_code_sample(
        title="42",
        section="1437f",
        text="The applicant is eligible for the benefit.",
    )
    ineligible = build_us_code_sample(
        title="42",
        section="1437g",
        text="The owner is ineligible for the license.",
    )
    suspend = build_us_code_sample(
        title="7",
        section="13",
        text="The commission may suspend a registration.",
    )
    autoencoder = AdaptiveModalAutoencoder(max_status_transition_features=240)

    revoke_features = autoencoder._status_transition_feature_keys_for(revoke)
    issue_features = autoencoder._status_transition_feature_keys_for(issue)
    effective_features = autoencoder._status_transition_feature_keys_for(effective)
    expiration_features = autoencoder._status_transition_feature_keys_for(expiration)
    eligible_features = autoencoder._status_transition_feature_keys_for(eligible)
    ineligible_features = autoencoder._status_transition_feature_keys_for(ineligible)
    suspend_features = autoencoder._status_transition_feature_keys_for(suspend)
    fallback_features = autoencoder._fallback_feature_keys_for(revoke)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(revoke)

    revoke_signature = (
        "authorization_status:government_actor:authorization_instrument:"
        "active_authorization->terminated_authorization:"
        "authorization_termination:permission:affirmed:instrument_scope"
    )
    assert (
        f"status-transition:transition-signature:{revoke_signature}"
        in revoke_features
    )
    assert (
        "status-transition:status-state:authorization_status:"
        "authorization_instrument:active_authorization->"
        "terminated_authorization:authorization_termination:affirmed"
        in revoke_features
    )
    assert (
        "status-transition:event-calculus-terminates-status:"
        "active_authorization:government_actor:authorization_instrument"
        in revoke_features
    )
    assert (
        f"status-transition:decompiler-status-plan:{revoke_signature}"
        in fallback_features
    )
    assert (
        f"legal-ir:status-transition:decompiler-status-plan:{revoke_signature}"
        in legal_ir_features
    )

    assert (
        "status-transition:event-calculus-initiates-status:"
        "active_authorization:government_actor:authorization_instrument"
        in issue_features
    )
    assert (
        "status-transition:status-state:authorization_status:"
        "authorization_instrument:pending_authorization->"
        "active_authorization:effectiveness_activation:affirmed"
        in effective_features
    )
    assert (
        "status-transition:event-calculus-terminates-status:"
        "active_authorization:status_actor:authorization_instrument"
        in expiration_features
    )
    assert (
        "status-transition:event-calculus-initiates-status:"
        "eligible_status:private_party:eligibility_status"
        in eligible_features
    )
    assert (
        "status-transition:event-calculus-terminates-status:"
        "eligible_status:private_party:eligibility_status"
        in ineligible_features
    )
    assert (
        "status-transition:status-state:authorization_status:"
        "authorization_instrument:active_authorization->"
        "suspended_authorization:authorization_suspension:affirmed"
        in suspend_features
    )


def test_status_transition_feature_head_transfers_termination_holdout() -> None:
    shared_plan_feature = (
        "status-transition:decompiler-status-plan:"
        "authorization_status:government_actor:authorization_instrument:"
        "active_authorization->terminated_authorization:"
        "authorization_termination:permission:affirmed:instrument_scope"
    )
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may revoke a license.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="The board may terminate a permit.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_temporal_validity_features=0,
        max_evidentiary_burden_features=0,
        max_legal_relation_features=0,
        max_status_transition_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_status_features = set(
        family_autoencoder._status_transition_feature_keys_for(train)
    ).intersection(
        family_autoencoder._status_transition_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert shared_plan_feature in shared_status_features
    assert shared_plan_feature in family_autoencoder.state.feature_family_logits
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_temporal_validity_features=0,
        max_evidentiary_burden_features=0,
        max_legal_relation_features=0,
        max_status_transition_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert shared_plan_feature in embedding_autoencoder.state.feature_embedding_weights
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_condition_consequence_features_encode_guarded_rule_edges() -> None:
    sufficient = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "If the applicant files an application, the agency shall approve "
            "the permit."
        ),
    )
    exception = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall not issue the license unless the fee is paid.",
    )
    necessary = build_us_code_sample(
        title="5",
        section="554",
        text="A person may file an appeal only if the notice is timely.",
    )
    proviso = build_us_code_sample(
        title="5",
        section="555",
        text=(
            "The agency may grant a waiver provided that the application is "
            "complete."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(
        max_condition_consequence_features=240
    )

    sufficient_features = autoencoder._condition_consequence_feature_keys_for(
        sufficient
    )
    exception_features = autoencoder._condition_consequence_feature_keys_for(
        exception
    )
    necessary_features = autoencoder._condition_consequence_feature_keys_for(
        necessary
    )
    proviso_features = autoencoder._condition_consequence_feature_keys_for(proviso)
    fallback_features = autoencoder._fallback_feature_keys_for(sufficient)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(sufficient)

    sufficient_signature = (
        "sufficient_condition:application_or_proof->grant_authorization:"
        "government_actor:authorization_instrument:obligation:"
        "positive_consequence:instrument_scope"
    )
    assert (
        f"condition-consequence:guard-signature:{sufficient_signature}"
        in sufficient_features
    )
    assert (
        "condition-consequence:event-calculus-precondition:"
        "application_or_proof->grant_authorization:authorization_instrument"
        in sufficient_features
    )
    assert (
        "condition-consequence:operator-guard:"
        "deontic:o:condition:sufficient_condition:"
        "application_or_proof->grant_authorization"
        in sufficient_features
    )
    assert (
        f"condition-consequence:decompiler-guard-plan:{sufficient_signature}"
        in fallback_features
    )
    assert (
        f"legal-ir:condition-consequence:decompiler-guard-plan:"
        f"{sufficient_signature}"
        in legal_ir_features
    )

    assert (
        "condition-consequence:guard-signature:"
        "exception_guard:payment_or_fee->grant_authorization:"
        "government_actor:authorization_instrument:obligation:"
        "exception_consequence:instrument_scope"
        in exception_features
    )
    assert (
        "condition-consequence:guard-signature:"
        "necessary_condition:notice_or_record->submit_or_file:"
        "private_party:proceeding_or_order:permission:"
        "positive_consequence:procedure_scope"
        in necessary_features
    )
    assert (
        "condition-consequence:guard-signature:"
        "proviso_guard:application_or_proof->grant_authorization:"
        "government_actor:authorization_instrument:permission:"
        "positive_consequence:instrument_scope"
        in proviso_features
    )


def test_condition_consequence_feature_head_transfers_guard_holdout() -> None:
    shared_plan_feature = (
        "condition-consequence:decompiler-guard-plan:"
        "necessary_condition:notice_or_record->submit_or_file:"
        "private_party:proceeding_or_order:permission:"
        "positive_consequence:procedure_scope"
    )
    train = build_us_code_sample(
        title="5",
        section="552",
        text="A person may file an appeal only if the notice is timely.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="An owner may submit an appeal only if the record is timely.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_temporal_validity_features=0,
        max_evidentiary_burden_features=0,
        max_legal_relation_features=0,
        max_status_transition_features=0,
        max_condition_consequence_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_guard_features = set(
        family_autoencoder._condition_consequence_feature_keys_for(train)
    ).intersection(
        family_autoencoder._condition_consequence_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert shared_plan_feature in shared_guard_features
    assert shared_plan_feature in family_autoencoder.state.feature_family_logits
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_temporal_validity_features=0,
        max_evidentiary_burden_features=0,
        max_legal_relation_features=0,
        max_status_transition_features=0,
        max_condition_consequence_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert shared_plan_feature in embedding_autoencoder.state.feature_embedding_weights
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_applicability_scope_features_encode_domain_and_exception_edges() -> None:
    inclusion = build_us_code_sample(
        title="5",
        section="552",
        text="This section applies to each covered entity.",
    )
    exclusion = build_us_code_sample(
        title="5",
        section="553",
        text="This subsection does not apply to an employee of the agency.",
    )
    respect = build_us_code_sample(
        title="5",
        section="554",
        text=(
            "This section applies with respect to any record maintained by "
            "the agency."
        ),
    )
    purpose = build_us_code_sample(
        title="5",
        section="555",
        text=(
            "For purposes of this section, a covered entity includes any "
            "recipient."
        ),
    )
    case_scope = build_us_code_sample(
        title="5",
        section="556",
        text=(
            "In the case of a licensee, this subsection applies to the "
            "renewal."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(max_applicability_scope_features=240)

    inclusion_features = autoencoder._applicability_scope_feature_keys_for(
        inclusion
    )
    exclusion_features = autoencoder._applicability_scope_feature_keys_for(
        exclusion
    )
    respect_features = autoencoder._applicability_scope_feature_keys_for(
        respect
    )
    purpose_features = autoencoder._applicability_scope_feature_keys_for(
        purpose
    )
    case_features = autoencoder._applicability_scope_feature_keys_for(case_scope)
    fallback_features = autoencoder._fallback_feature_keys_for(inclusion)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(inclusion)

    inclusion_signature = (
        "inclusion_scope:positive_applicability:"
        "current_section->regulated_entity:entity_scope"
    )
    assert (
        f"applicability-scope:applicability-signature:{inclusion_signature}"
        in inclusion_features
    )
    assert (
        "applicability-scope:frame-logic-domain-slot:"
        "inclusion_scope:regulated_entity:entity_scope:current_section"
        in inclusion_features
    )
    assert (
        "applicability-scope:kg-applicability-edge:"
        "current_section:inclusion_scope:regulated_entity:positive_applicability"
        in inclusion_features
    )
    assert (
        f"applicability-scope:decompiler-applicability-plan:"
        f"{inclusion_signature}"
        in fallback_features
    )
    assert (
        f"legal-ir:applicability-scope:decompiler-applicability-plan:"
        f"{inclusion_signature}"
        in legal_ir_features
    )

    assert (
        "applicability-scope:applicability-signature:"
        "exclusion_scope:negative_applicability:"
        "current_subsection->affiliated_person:entity_scope"
        in exclusion_features
    )
    assert (
        "applicability-scope:defeasible-applicability-exception:"
        "current_subsection->affiliated_person:entity_scope"
        in exclusion_features
    )
    assert (
        "applicability-scope:applicability-signature:"
        "respect_scope:scoped_applicability:"
        "current_section->notice_or_record:record_scope"
        in respect_features
    )
    assert (
        "applicability-scope:applicability-signature:"
        "purpose_scope:scoped_applicability:"
        "current_section->regulated_entity:entity_scope"
        in purpose_features
    )
    assert (
        "applicability-scope:applicability-signature:"
        "case_scope:scoped_applicability:"
        "current_subsection->benefit_participant:entity_scope"
        in case_features
    )


def test_applicability_scope_feature_head_transfers_domain_holdout() -> None:
    shared_plan_feature = (
        "applicability-scope:decompiler-applicability-plan:"
        "inclusion_scope:positive_applicability:"
        "current_section->regulated_entity:entity_scope"
    )
    train = build_us_code_sample(
        title="5",
        section="552",
        text="This section shall apply to each covered entity.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text=(
            "The requirements of this section shall apply to every regulated "
            "entity."
        ),
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_temporal_validity_features=0,
        max_evidentiary_burden_features=0,
        max_legal_relation_features=0,
        max_status_transition_features=0,
        max_condition_consequence_features=0,
        max_applicability_scope_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_scope_features = set(
        family_autoencoder._applicability_scope_feature_keys_for(train)
    ).intersection(
        family_autoencoder._applicability_scope_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert shared_plan_feature in shared_scope_features
    assert shared_plan_feature in family_autoencoder.state.feature_family_logits
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_temporal_validity_features=0,
        max_evidentiary_burden_features=0,
        max_legal_relation_features=0,
        max_status_transition_features=0,
        max_condition_consequence_features=0,
        max_applicability_scope_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert shared_plan_feature in embedding_autoencoder.state.feature_embedding_weights
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_coreference_binding_features_encode_deictic_reference_edges() -> None:
    such_person = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "A person may request a permit. Such person shall file the "
            "application."
        ),
    )
    that_license = build_us_code_sample(
        title="5",
        section="553",
        text=(
            "The agency shall issue a license. That license expires after "
            "one year."
        ),
    )
    therein_record = build_us_code_sample(
        title="5",
        section="554",
        text=(
            "The applicant shall file a record. Data contained therein shall "
            "be protected."
        ),
    )
    that_subsection = build_us_code_sample(
        title="5",
        section="555",
        text=(
            "Subsection (b) applies to the claim. An appeal under that "
            "subsection may be filed."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(max_coreference_binding_features=240)

    person_features = autoencoder._coreference_binding_feature_keys_for(
        such_person
    )
    license_features = autoencoder._coreference_binding_feature_keys_for(
        that_license
    )
    record_features = autoencoder._coreference_binding_feature_keys_for(
        therein_record
    )
    subsection_features = autoencoder._coreference_binding_feature_keys_for(
        that_subsection
    )
    fallback_features = autoencoder._fallback_feature_keys_for(such_person)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(such_person)

    person_signature = (
        "such_reference:private_party->private_party:"
        "cross_sentence:class_preserving"
    )
    assert (
        f"coreference-binding:coreference-signature:{person_signature}"
        in person_features
    )
    assert (
        "coreference-binding:compiler-variable-binding:"
        "private_party->private_party:such_reference:cross_sentence"
        in person_features
    )
    assert (
        "coreference-binding:frame-logic-same-as:"
        "private_party:private_party:such_reference:class_preserving"
        in person_features
    )
    assert (
        f"coreference-binding:decompiler-coreference-plan:{person_signature}"
        in fallback_features
    )
    assert (
        f"legal-ir:coreference-binding:decompiler-coreference-plan:"
        f"{person_signature}"
        in legal_ir_features
    )

    assert (
        "coreference-binding:coreference-signature:"
        "that_reference:authorization_instrument->authorization_instrument:"
        "cross_sentence:class_preserving"
        in license_features
    )
    assert (
        "coreference-binding:coreference-signature:"
        "therein_reference:notice_or_record->notice_or_record:"
        "cross_sentence:class_preserving"
        in record_features
    )
    assert (
        "coreference-binding:coreference-signature:"
        "under_that_reference:statutory_reference->statutory_reference:"
        "cross_sentence:class_preserving"
        in subsection_features
    )


def test_coreference_binding_feature_head_transfers_deictic_holdout() -> None:
    shared_plan_feature = (
        "coreference-binding:decompiler-coreference-plan:"
        "such_reference:private_party->private_party:"
        "cross_sentence:class_preserving"
    )
    train = build_us_code_sample(
        title="5",
        section="552",
        text="A person shall file an application. Such person shall keep records.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text=(
            "An individual must submit a claim. Such individual must maintain "
            "records."
        ),
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_temporal_validity_features=0,
        max_evidentiary_burden_features=0,
        max_legal_relation_features=0,
        max_status_transition_features=0,
        max_condition_consequence_features=0,
        max_applicability_scope_features=0,
        max_coreference_binding_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_coreference_features = set(
        family_autoencoder._coreference_binding_feature_keys_for(train)
    ).intersection(
        family_autoencoder._coreference_binding_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert shared_plan_feature in shared_coreference_features
    assert shared_plan_feature in family_autoencoder.state.feature_family_logits
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_temporal_validity_features=0,
        max_evidentiary_burden_features=0,
        max_legal_relation_features=0,
        max_status_transition_features=0,
        max_condition_consequence_features=0,
        max_applicability_scope_features=0,
        max_coreference_binding_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert shared_plan_feature in embedding_autoencoder.state.feature_embedding_weights
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_logical_connective_features_encode_boolean_ir_edges() -> None:
    conjunction = build_us_code_sample(
        title="5",
        section="552",
        text="The person shall file an application and pay the fee.",
    )
    disjunction = build_us_code_sample(
        title="5",
        section="553",
        text="The applicant may request a hearing or submit a written statement.",
    )
    negative = build_us_code_sample(
        title="5",
        section="554",
        text="The agency shall neither disclose the record nor publish the notice.",
    )
    cumulative = build_us_code_sample(
        title="5",
        section="555",
        text="The licensee shall both maintain records and submit reports.",
    )
    enumerated = build_us_code_sample(
        title="5",
        section="556",
        text="The applicant shall provide any of the following: a record; a notice.",
    )
    autoencoder = AdaptiveModalAutoencoder(max_logical_connective_features=240)

    conjunction_features = autoencoder._logical_connective_feature_keys_for(
        conjunction
    )
    disjunction_features = autoencoder._logical_connective_feature_keys_for(
        disjunction
    )
    negative_features = autoencoder._logical_connective_feature_keys_for(negative)
    cumulative_features = autoencoder._logical_connective_feature_keys_for(
        cumulative
    )
    enumerated_features = autoencoder._logical_connective_feature_keys_for(
        enumerated
    )
    fallback_features = autoencoder._fallback_feature_keys_for(conjunction)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(conjunction)

    conjunction_signature = (
        "conjunction:application_or_proof+payment_or_fee:"
        "obligation:positive_connective:modal_scope:2-3"
    )
    assert (
        f"logical-connective:connective-signature:{conjunction_signature}"
        in conjunction_features
    )
    assert (
        "logical-connective:compiler-boolean-node:"
        "conjunction:application_or_proof+payment_or_fee:modal_scope:2-3"
        in conjunction_features
    )
    assert (
        "logical-connective:frame-logic-connective-slot:"
        "conjunction:application_or_proof:payment_or_fee:modal_scope"
        in conjunction_features
    )
    assert (
        f"logical-connective:decompiler-connective-plan:"
        f"{conjunction_signature}"
        in fallback_features
    )
    assert (
        f"legal-ir:logical-connective:decompiler-connective-plan:"
        f"{conjunction_signature}"
        in legal_ir_features
    )

    assert (
        "logical-connective:connective-signature:"
        "inclusive_disjunction:proceeding_or_order+application_or_proof:"
        "permission:positive_connective:modal_scope:2-3"
        in disjunction_features
    )
    assert (
        "logical-connective:connective-signature:"
        "negative_conjunction:notice_or_record+notice_or_record:"
        "prohibition:negative_connective:same_role_scope:2-3"
        in negative_features
    )
    assert (
        "logical-connective:connective-signature:"
        "cumulative_conjunction:notice_or_record+application_or_proof:"
        "obligation:positive_connective:mixed_role_scope:2-3"
        in cumulative_features
    )
    assert (
        "logical-connective:connective-signature:"
        "enumerated_disjunction:notice_or_record+notice_or_record:"
        "obligation:positive_connective:enumeration_scope:2-3"
        in enumerated_features
    )


def test_logical_connective_feature_head_transfers_boolean_holdout() -> None:
    shared_plan_feature = (
        "logical-connective:decompiler-connective-plan:"
        "conjunction:application_or_proof+payment_or_fee:"
        "obligation:positive_connective:modal_scope:2-3"
    )
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The person shall file an application and pay the fee.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text="The individual must submit a claim and pay the payment.",
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_temporal_validity_features=0,
        max_evidentiary_burden_features=0,
        max_legal_relation_features=0,
        max_status_transition_features=0,
        max_condition_consequence_features=0,
        max_applicability_scope_features=0,
        max_coreference_binding_features=0,
        max_logical_connective_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_connective_features = set(
        family_autoencoder._logical_connective_feature_keys_for(train)
    ).intersection(
        family_autoencoder._logical_connective_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert shared_plan_feature in shared_connective_features
    assert shared_plan_feature in family_autoencoder.state.feature_family_logits
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_temporal_validity_features=0,
        max_evidentiary_burden_features=0,
        max_legal_relation_features=0,
        max_status_transition_features=0,
        max_condition_consequence_features=0,
        max_applicability_scope_features=0,
        max_coreference_binding_features=0,
        max_logical_connective_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert shared_plan_feature in embedding_autoencoder.state.feature_embedding_weights
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_enumeration_hierarchy_features_encode_numbered_list_scope() -> None:
    numbered = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "The person shall do any of the following: "
            "(1) file an application; (2) pay the fee."
        ),
    )
    nested = build_us_code_sample(
        title="5",
        section="553",
        text=(
            "The application must include: "
            "(1) filing instructions; (A) records; (B) notices."
        ),
    )
    crossref = build_us_code_sample(
        title="5",
        section="554",
        text=(
            "The requirements of paragraphs (1) and (2) shall apply to "
            "clauses (i) and (ii)."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(max_enumeration_hierarchy_features=240)

    numbered_features = autoencoder._enumeration_hierarchy_feature_keys_for(numbered)
    nested_features = autoencoder._enumeration_hierarchy_feature_keys_for(nested)
    crossref_features = autoencoder._enumeration_hierarchy_feature_keys_for(crossref)
    fallback_features = autoencoder._fallback_feature_keys_for(numbered)
    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(numbered)

    numbered_signature = (
        "numbered_list:paragraph_level:application_or_proof+payment_or_fee:"
        "any:2-3:positive_enumeration:list_scope"
    )
    assert (
        f"enumeration-hierarchy:enumeration-signature:{numbered_signature}"
        in numbered_features
    )
    assert (
        "enumeration-hierarchy:compiler-enumeration-node:"
        "numbered_list:paragraph_level:application_or_proof+payment_or_fee:"
        "any:2-3"
        in numbered_features
    )
    assert (
        "enumeration-hierarchy:frame-logic-enumeration-slot:"
        "paragraph_level:application_or_proof+payment_or_fee:list_scope"
        in numbered_features
    )
    assert (
        f"enumeration-hierarchy:decompiler-enumeration-plan:{numbered_signature}"
        in fallback_features
    )
    assert (
        f"legal-ir:enumeration-hierarchy:decompiler-enumeration-plan:"
        f"{numbered_signature}"
        in legal_ir_features
    )

    assert (
        "enumeration-hierarchy:enumeration-signature:"
        "numbered_list:paragraph_level->subparagraph_level:"
        "application_or_proof+notice_or_record:"
        "unspecified:2-3:positive_enumeration:inline_scope"
        in nested_features
    )
    assert (
        "enumeration-hierarchy:reference-target:"
        "paragraph_reference:paragraph_level:2-3"
        in crossref_features
    )
    assert (
        "enumeration-hierarchy:reference-target:"
        "clause_reference:clause_level:2-3"
        in crossref_features
    )


def test_enumeration_hierarchy_feature_head_transfers_numbered_holdout() -> None:
    shared_plan_feature = (
        "enumeration-hierarchy:decompiler-enumeration-plan:"
        "numbered_list:paragraph_level:application_or_proof+payment_or_fee:"
        "any:2-3:positive_enumeration:list_scope"
    )
    train = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "The person shall do any of the following: "
            "(1) file an application; (2) pay the fee."
        ),
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="12",
        section="1841",
        text=(
            "The individual must perform any of the following: "
            "(1) submit a claim; (2) pay the payment."
        ),
        embedding_vector=[1.0, 0.0],
    )
    family_autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_quantitative_formula_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_temporal_validity_features=0,
        max_evidentiary_burden_features=0,
        max_legal_relation_features=0,
        max_status_transition_features=0,
        max_condition_consequence_features=0,
        max_applicability_scope_features=0,
        max_coreference_binding_features=0,
        max_logical_connective_features=0,
        max_enumeration_hierarchy_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
    )
    shared_enumeration_features = set(
        family_autoencoder._enumeration_hierarchy_feature_keys_for(train)
    ).intersection(
        family_autoencoder._enumeration_hierarchy_feature_keys_for(validation)
    )
    before_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    family_autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_ce = family_autoencoder.evaluate([validation], use_sample_memory=False)

    assert shared_plan_feature in shared_enumeration_features
    assert shared_plan_feature in family_autoencoder.state.feature_family_logits
    assert after_ce.cross_entropy_loss < before_ce.cross_entropy_loss

    embedding_autoencoder = AdaptiveModalAutoencoder(
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=4.0,
        max_compiler_latent_profile_features=0,
        max_round_trip_bridge_features=0,
        max_clause_topology_features=0,
        max_legal_semantic_frame_features=0,
        max_normative_polarity_features=0,
        max_compiler_contract_features=0,
        max_decompiler_surface_template_features=0,
        max_canonical_ir_graph_features=0,
        max_cycle_consistency_features=0,
        max_equivalence_prototype_features=0,
        max_contrastive_ir_boundary_features=0,
        max_repair_plan_features=0,
        max_logic_view_contract_features=0,
        max_objective_residual_features=0,
        max_provenance_alignment_features=0,
        max_discourse_flow_features=0,
        max_proof_obligation_features=0,
        max_entity_binding_features=0,
        max_defeasible_priority_features=0,
        max_constraint_grounding_features=0,
        max_quantitative_formula_features=0,
        max_definition_grounding_features=0,
        max_quantifier_scope_features=0,
        max_procedural_lifecycle_features=0,
        max_enforcement_remedy_features=0,
        max_reference_dependency_features=0,
        max_authority_jurisdiction_features=0,
        max_temporal_validity_features=0,
        max_evidentiary_burden_features=0,
        max_legal_relation_features=0,
        max_status_transition_features=0,
        max_condition_consequence_features=0,
        max_applicability_scope_features=0,
        max_coreference_binding_features=0,
        max_logical_connective_features=0,
        max_enumeration_hierarchy_features=240,
        max_token_features=0,
        max_token_bigram_features=0,
        max_token_trigram_features=0,
        cosine_reconstruction_weight=0.0,
    )
    before_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    embedding_autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after_cosine = embedding_autoencoder.evaluate(
        [validation],
        use_sample_memory=False,
    )

    assert shared_plan_feature in embedding_autoencoder.state.feature_embedding_weights
    assert after_cosine.embedding_cosine_similarity > before_cosine.embedding_cosine_similarity


def test_family_embedding_prototype_head_transfers_cosine_to_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency must publish notice.",
        embedding_vector=[1.0, 0.0],
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        family_embedding_weight_scale=4.0,
        feature_family_logit_scale=1.0,
        cosine_reconstruction_weight=0.0,
    )
    before = autoencoder.evaluate([validation], use_sample_memory=False)

    autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate([validation], use_sample_memory=False)

    assert autoencoder.state.family_embedding_weights["deontic"]
    assert after.embedding_cosine_similarity > before.embedding_cosine_similarity
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type == "family_embedding_weight"
        for contribution in introspection.top_embedding_contributions
    )


def test_semantic_slot_family_head_lowers_cross_entropy_on_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall publish notice before final action.",
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=0.0,
        semantic_slot_family_logit_scale=8.0,
    )
    before = autoencoder.evaluate([validation], use_sample_memory=False)

    autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate([validation], use_sample_memory=False)

    assert autoencoder.state.semantic_slot_family_logits
    assert autoencoder.state.family_logits == {}
    assert after.cross_entropy_loss < before.cross_entropy_loss
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type == "semantic_slot_family_logit"
        for contribution in introspection.top_family_contributions
    )


def test_semantic_slot_embedding_head_transfers_cosine_to_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall publish notice before final action.",
        embedding_vector=[1.0, 0.0],
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=6.0,
        cosine_reconstruction_weight=0.0,
    )
    before = autoencoder.evaluate([validation], use_sample_memory=False)

    autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate([validation], use_sample_memory=False)

    assert autoencoder.state.semantic_slot_embedding_weights
    assert after.embedding_cosine_similarity > before.embedding_cosine_similarity
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type == "semantic_slot_embedding_weight"
        for contribution in introspection.top_embedding_contributions
    )


def test_semantic_slot_interactions_capture_compositional_ir() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "If the applicant files notice, the agency must approve the permit "
            "except when records are incomplete."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(
        semantic_slot_interaction_weight=0.5,
        max_semantic_slot_interactions=3,
    )

    distribution = autoencoder._semantic_slot_distribution_for(sample)
    pair_slots = [
        slot for slot in distribution if slot.startswith("slot-pair:")
    ]

    assert len(pair_slots) == 3
    assert any("condition-present" in slot for slot in pair_slots)
    assert any("exception-present" in slot for slot in pair_slots)

    disabled = AdaptiveModalAutoencoder(
        semantic_slot_interaction_weight=0.0,
        max_semantic_slot_interactions=3,
    )
    assert not any(
        slot.startswith("slot-pair:")
        for slot in disabled._semantic_slot_distribution_for(sample)
    )


def test_semantic_slots_surface_typed_family_pair_reconstruction_contracts() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "The agency determines eligibility after the board is authorized "
            "to carry out the transfer."
        ),
    )
    base_formula = sample.modal_ir.formulas[0]
    formulas = [
        replace(
            base_formula,
            formula_id="packet-000851-deontic",
            operator=replace(
                base_formula.operator,
                family="deontic",
                system="D",
                symbol="O",
                label="obligation",
            ),
            metadata={"cue": "determines"},
        ),
        replace(
            base_formula,
            formula_id="packet-000851-frame",
            operator=replace(
                base_formula.operator,
                family="frame",
                system="Frame",
                symbol="frame",
                label="frame",
            ),
            metadata={"cue": "authorized"},
        ),
        replace(
            base_formula,
            formula_id="packet-000851-temporal",
            operator=replace(
                base_formula.operator,
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
            ),
            metadata={"cue": "after"},
        ),
    ]
    mixed_sample = replace(sample, modal_ir=replace(sample.modal_ir, formulas=formulas))

    distribution = AdaptiveModalAutoencoder()._semantic_slot_distribution_for(
        mixed_sample
    )

    for family_pair in (
        "deontic->epistemic",
        "frame->deontic",
        "frame->frame",
        "temporal->epistemic",
    ):
        assert f"slot:typed-decompiler-family-pair:{family_pair}" in distribution

    assert (
        "slot:typed-decompiler-family-pair-cue:deontic->epistemic:determines"
        in distribution
    )
    assert (
        "slot:typed-decompiler-family-pair-cue:temporal->epistemic:after"
        in distribution
    )


def test_semantic_slot_pair_logits_can_drive_compositional_family_ce() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="If the applicant files notice, the agency must approve the permit.",
    )
    probe = AdaptiveModalAutoencoder(
        semantic_slot_interaction_weight=0.5,
        max_semantic_slot_interactions=8,
    )
    pair_slot = next(
        slot
        for slot in probe._semantic_slot_distribution_for(sample)
        if slot.startswith("slot-pair:")
        and "condition-present" in slot
        and "modal-operator:conditional_normative" in slot
    )
    autoencoder = AdaptiveModalAutoencoder(
        semantic_slot_family_logit_scale=8.0,
        semantic_slot_interaction_weight=0.5,
        max_semantic_slot_interactions=8,
        state=ModalAutoencoderTrainingState(
            semantic_slot_family_logits={
                pair_slot: {"conditional_normative": 2.0}
            }
        ),
    )

    before = AdaptiveModalAutoencoder().evaluate([sample], use_sample_memory=False)
    after = autoencoder.evaluate([sample], use_sample_memory=False)

    assert after.cross_entropy_loss < before.cross_entropy_loss


def test_semantic_slot_legal_ir_view_head_lowers_holdout_ce() -> None:
    class DummyDocument:
        def canonical_hash(self):
            return "dummy-semantic-slot-view-target"

    class DummyTarget:
        document = DummyDocument()
        losses = {"legal_ir_multiview_total_loss": 0.1}
        view_distribution = {
            "CEC.native": 0.2,
            "knowledge_graphs.neo4j_compat": 0.8,
        }

    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall publish notice before final action.",
    )
    targets = {
        train.sample_id: DummyTarget(),
        validation.sample_id: DummyTarget(),
    }
    autoencoder = AdaptiveModalAutoencoder(
        legal_ir_view_logit_scale=0.0,
        semantic_slot_legal_ir_view_logit_scale=8.0,
    )
    before = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    autoencoder.evaluate([train], legal_ir_targets=targets, use_sample_memory=False)
    autoencoder._nudge_legal_ir_view_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    assert autoencoder.state.semantic_slot_legal_ir_view_logits
    assert (
        after.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
        < before.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
    )


def test_legal_ir_view_family_head_lowers_holdout_family_ce() -> None:
    class DummyDocument:
        def canonical_hash(self):
            return "dummy-view-family-target"

    class DummyTarget:
        document = DummyDocument()
        losses = {"legal_ir_multiview_total_loss": 0.1}
        view_distribution = {"knowledge_graphs.neo4j_compat": 1.0}

    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall publish notice before final action.",
    )
    targets = {
        train.sample_id: DummyTarget(),
        validation.sample_id: DummyTarget(),
    }
    autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=0.0,
        semantic_slot_family_logit_scale=0.0,
        legal_ir_view_family_logit_scale=8.0,
        legal_ir_view_logit_scale=0.0,
    )
    before = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    autoencoder.evaluate([train], legal_ir_targets=targets, use_sample_memory=False)
    autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    assert autoencoder.state.legal_ir_view_family_logits
    assert after.cross_entropy_loss < before.cross_entropy_loss
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type == "legal_ir_view_family_logit"
        for contribution in introspection.top_family_contributions
    )


def test_semantic_slot_legal_ir_view_family_head_lowers_holdout_family_ce() -> None:
    class DummyDocument:
        def canonical_hash(self):
            return "dummy-slot-view-family-target"

    class DummyTarget:
        document = DummyDocument()
        losses = {"legal_ir_multiview_total_loss": 0.1}
        view_distribution = {"knowledge_graphs.neo4j_compat": 1.0}

    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall publish notice before final action.",
    )
    targets = {
        train.sample_id: DummyTarget(),
        validation.sample_id: DummyTarget(),
    }
    autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=0.0,
        semantic_slot_family_logit_scale=0.0,
        legal_ir_view_family_logit_scale=0.0,
        semantic_slot_legal_ir_view_family_logit_scale=8.0,
        legal_ir_view_logit_scale=0.0,
    )
    before = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    autoencoder.evaluate([train], legal_ir_targets=targets, use_sample_memory=False)
    autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    assert autoencoder.state.semantic_slot_legal_ir_view_family_logits
    assert after.cross_entropy_loss < before.cross_entropy_loss
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type == "semantic_slot_legal_ir_view_family_logit"
        for contribution in introspection.top_family_contributions
    )


def test_family_semantic_slot_legal_ir_view_head_lowers_holdout_view_ce() -> None:
    class DummyDocument:
        def canonical_hash(self):
            return "dummy-family-slot-view-target"

    class DummyTarget:
        document = DummyDocument()
        losses = {"legal_ir_multiview_total_loss": 0.1}
        view_distribution = {
            "CEC.native": 0.2,
            "knowledge_graphs.neo4j_compat": 0.8,
        }

    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall publish notice before final action.",
    )
    targets = {
        train.sample_id: DummyTarget(),
        validation.sample_id: DummyTarget(),
    }
    autoencoder = AdaptiveModalAutoencoder(
        legal_ir_view_logit_scale=0.0,
        semantic_slot_legal_ir_view_logit_scale=0.0,
        family_semantic_slot_legal_ir_view_logit_scale=8.0,
    )
    before = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    autoencoder.evaluate([train], legal_ir_targets=targets, use_sample_memory=False)
    autoencoder._nudge_legal_ir_view_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    assert autoencoder.state.family_semantic_slot_legal_ir_view_logits
    assert (
        after.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
        < before.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
    )


def test_legal_ir_view_embedding_prototype_head_transfers_cosine_to_holdout() -> None:
    class DummyDocument:
        def canonical_hash(self):
            return "dummy-legal-ir-target"

    class DummyTarget:
        document = DummyDocument()
        losses = {"legal_ir_multiview_total_loss": 0.1}
        view_distribution = {"knowledge_graphs.neo4j_compat": 1.0}

    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice.",
        embedding_vector=[0.0, 1.0],
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall publish notice.",
        embedding_vector=[0.0, 1.0],
    )
    targets = {
        train.sample_id: DummyTarget(),
        validation.sample_id: DummyTarget(),
    }
    autoencoder = AdaptiveModalAutoencoder(
        feature_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=4.0,
        cosine_reconstruction_weight=0.0,
    )
    before = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    autoencoder.evaluate([train], legal_ir_targets=targets, use_sample_memory=False)
    autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    assert autoencoder.state.legal_ir_view_embedding_weights[
        "knowledge_graphs.neo4j_compat"
    ]
    assert after.embedding_cosine_similarity > before.embedding_cosine_similarity
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type == "legal_ir_view_embedding_weight"
        for contribution in introspection.top_embedding_contributions
    )


def test_semantic_slot_legal_ir_view_embedding_head_transfers_cosine_to_holdout() -> None:
    class DummyDocument:
        def canonical_hash(self):
            return "dummy-slot-view-embedding-target"

    class DummyTarget:
        document = DummyDocument()
        losses = {"legal_ir_multiview_total_loss": 0.1}
        view_distribution = {"knowledge_graphs.neo4j_compat": 1.0}

    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
        embedding_vector=[0.0, 1.0],
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall publish notice before final action.",
        embedding_vector=[0.0, 1.0],
    )
    targets = {
        train.sample_id: DummyTarget(),
        validation.sample_id: DummyTarget(),
    }
    autoencoder = AdaptiveModalAutoencoder(
        feature_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=8.0,
        cosine_reconstruction_weight=0.0,
    )
    before = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    autoencoder.evaluate([train], legal_ir_targets=targets, use_sample_memory=False)
    autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    assert autoencoder.state.semantic_slot_legal_ir_view_embedding_weights
    assert after.embedding_cosine_similarity > before.embedding_cosine_similarity
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type == "semantic_slot_legal_ir_view_embedding_weight"
        for contribution in introspection.top_embedding_contributions
    )


def test_family_semantic_slot_legal_ir_view_embedding_head_transfers_cosine_to_holdout() -> None:
    class DummyDocument:
        def canonical_hash(self):
            return "dummy-family-slot-view-embedding-target"

    class DummyTarget:
        document = DummyDocument()
        losses = {"legal_ir_multiview_total_loss": 0.1}
        view_distribution = {"knowledge_graphs.neo4j_compat": 1.0}

    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall publish notice before final action.",
        embedding_vector=[1.0, 0.0],
    )
    targets = {
        train.sample_id: DummyTarget(),
        validation.sample_id: DummyTarget(),
    }
    autoencoder = AdaptiveModalAutoencoder(
        feature_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=8.0,
        cosine_reconstruction_weight=0.0,
    )
    before = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    autoencoder.evaluate([train], legal_ir_targets=targets, use_sample_memory=False)
    autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    assert autoencoder.state.family_semantic_slot_legal_ir_view_embedding_weights
    assert after.embedding_cosine_similarity > before.embedding_cosine_similarity
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type
        == "family_semantic_slot_legal_ir_view_embedding_weight"
        for contribution in introspection.top_embedding_contributions
    )


def test_compiler_quality_family_head_lowers_missing_formula_holdout_ce() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency publishes records.",
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency keeps records.",
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=0.0,
        semantic_slot_family_logit_scale=0.0,
        legal_ir_view_family_logit_scale=0.0,
        semantic_slot_legal_ir_view_family_logit_scale=0.0,
        compiler_quality_family_logit_scale=8.0,
    )
    before = autoencoder.evaluate([validation], use_sample_memory=False)

    autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate([validation], use_sample_memory=False)

    assert train.modal_ir.formulas == []
    assert validation.modal_ir.formulas == []
    assert autoencoder.state.compiler_quality_family_logits
    assert after.cross_entropy_loss < before.cross_entropy_loss
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type == "compiler_quality_family_logit"
        for contribution in introspection.top_family_contributions
    )


def test_compiler_quality_embedding_head_transfers_cosine_to_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency publishes records.",
        embedding_vector=[0.0, 1.0],
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency keeps records.",
        embedding_vector=[0.0, 1.0],
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        compiler_quality_embedding_weight_scale=8.0,
        logic_signature_embedding_weight_scale=0.0,
        cosine_reconstruction_weight=0.0,
    )
    before = autoencoder.evaluate([validation], use_sample_memory=False)

    autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate([validation], use_sample_memory=False)

    assert autoencoder.state.compiler_quality_embedding_weights
    assert after.embedding_cosine_similarity > before.embedding_cosine_similarity
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type == "compiler_quality_embedding_weight"
        for contribution in introspection.top_embedding_contributions
    )


def test_logic_signature_family_head_lowers_holdout_ce() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall publish notice before final action.",
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=0.0,
        semantic_slot_family_logit_scale=0.0,
        legal_ir_view_family_logit_scale=0.0,
        semantic_slot_legal_ir_view_family_logit_scale=0.0,
        compiler_quality_family_logit_scale=0.0,
        logic_signature_family_logit_scale=8.0,
    )
    before = autoencoder.evaluate([validation], use_sample_memory=False)

    autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate([validation], use_sample_memory=False)

    assert autoencoder.state.logic_signature_family_logits
    assert after.cross_entropy_loss < before.cross_entropy_loss
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type == "logic_signature_family_logit"
        for contribution in introspection.top_family_contributions
    )


def test_logic_signature_embedding_head_transfers_cosine_to_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
        embedding_vector=[0.0, 1.0],
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall publish notice before final action.",
        embedding_vector=[0.0, 1.0],
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=8.0,
        cosine_reconstruction_weight=0.0,
    )
    before = autoencoder.evaluate([validation], use_sample_memory=False)

    autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate([validation], use_sample_memory=False)

    assert autoencoder.state.logic_signature_embedding_weights
    assert after.embedding_cosine_similarity > before.embedding_cosine_similarity
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type == "logic_signature_embedding_weight"
        for contribution in introspection.top_embedding_contributions
    )


def test_logic_signature_legal_ir_view_head_lowers_holdout_view_ce() -> None:
    class DummyDocument:
        def canonical_hash(self):
            return "dummy-logic-signature-view-target"

    class DummyTarget:
        document = DummyDocument()
        losses = {"legal_ir_multiview_total_loss": 0.1}
        view_distribution = {
            "CEC.native": 0.2,
            "knowledge_graphs.neo4j_compat": 0.8,
        }

    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall publish notice before final action.",
    )
    targets = {
        train.sample_id: DummyTarget(),
        validation.sample_id: DummyTarget(),
    }
    autoencoder = AdaptiveModalAutoencoder(
        legal_ir_view_logit_scale=0.0,
        semantic_slot_legal_ir_view_logit_scale=0.0,
        family_semantic_slot_legal_ir_view_logit_scale=0.0,
        logic_signature_legal_ir_view_logit_scale=8.0,
    )
    before = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    autoencoder.evaluate([train], legal_ir_targets=targets, use_sample_memory=False)
    autoencoder._nudge_legal_ir_view_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    assert autoencoder.state.logic_signature_legal_ir_view_logits
    assert (
        after.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
        < before.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
    )


def test_round_trip_signal_family_head_lowers_holdout_ce() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency publishes records.",
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency keeps records.",
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=0.0,
        semantic_slot_family_logit_scale=0.0,
        legal_ir_view_family_logit_scale=0.0,
        semantic_slot_legal_ir_view_family_logit_scale=0.0,
        compiler_quality_family_logit_scale=0.0,
        logic_signature_family_logit_scale=0.0,
        round_trip_signal_family_logit_scale=8.0,
    )
    before = autoencoder.evaluate([validation], use_sample_memory=False)

    autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate([validation], use_sample_memory=False)

    assert train.modal_ir.formulas == []
    assert validation.modal_ir.formulas == []
    assert autoencoder.state.round_trip_signal_family_logits
    assert after.cross_entropy_loss < before.cross_entropy_loss
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type == "round_trip_signal_family_logit"
        for contribution in introspection.top_family_contributions
    )


def test_round_trip_signal_embedding_head_transfers_cosine_to_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency publishes records.",
        embedding_vector=[0.0, 1.0],
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency keeps records.",
        embedding_vector=[0.0, 1.0],
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=8.0,
        cosine_reconstruction_weight=0.0,
    )
    before = autoencoder.evaluate([validation], use_sample_memory=False)

    autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate([validation], use_sample_memory=False)

    assert autoencoder.state.round_trip_signal_embedding_weights
    assert after.embedding_cosine_similarity > before.embedding_cosine_similarity
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type == "round_trip_signal_embedding_weight"
        for contribution in introspection.top_embedding_contributions
    )


def test_round_trip_signal_legal_ir_view_head_lowers_holdout_view_ce() -> None:
    class DummyDocument:
        def canonical_hash(self):
            return "dummy-round-trip-view-target"

    class DummyTarget:
        document = DummyDocument()
        losses = {"legal_ir_multiview_total_loss": 0.1}
        view_distribution = {
            "CEC.native": 0.2,
            "knowledge_graphs.neo4j_compat": 0.8,
        }

    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency publishes records.",
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency keeps records.",
    )
    targets = {
        train.sample_id: DummyTarget(),
        validation.sample_id: DummyTarget(),
    }
    autoencoder = AdaptiveModalAutoencoder(
        legal_ir_view_logit_scale=0.0,
        semantic_slot_legal_ir_view_logit_scale=0.0,
        family_semantic_slot_legal_ir_view_logit_scale=0.0,
        logic_signature_legal_ir_view_logit_scale=0.0,
        round_trip_signal_legal_ir_view_logit_scale=8.0,
    )
    before = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    autoencoder.evaluate([train], legal_ir_targets=targets, use_sample_memory=False)
    autoencoder._nudge_legal_ir_view_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    assert autoencoder.state.round_trip_signal_legal_ir_view_logits
    assert (
        after.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
        < before.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
    )
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type == "round_trip_signal_legal_ir_view_logit"
        for contribution in introspection.top_family_contributions
    )


def test_decompiler_plan_family_head_lowers_holdout_ce() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall provide notice before final action.",
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=0.0,
        semantic_slot_family_logit_scale=0.0,
        legal_ir_view_family_logit_scale=0.0,
        semantic_slot_legal_ir_view_family_logit_scale=0.0,
        compiler_quality_family_logit_scale=0.0,
        logic_signature_family_logit_scale=0.0,
        round_trip_signal_family_logit_scale=0.0,
        decompiler_plan_family_logit_scale=8.0,
    )
    before = autoencoder.evaluate([validation], use_sample_memory=False)

    autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate([validation], use_sample_memory=False)

    assert autoencoder.state.decompiler_plan_family_logits
    assert after.cross_entropy_loss < before.cross_entropy_loss
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type == "decompiler_plan_family_logit"
        for contribution in introspection.top_family_contributions
    )


def test_decompiler_plan_embedding_head_transfers_cosine_to_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall provide notice before final action.",
        embedding_vector=[1.0, 0.0],
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=8.0,
        cosine_reconstruction_weight=0.0,
    )
    before = autoencoder.evaluate([validation], use_sample_memory=False)

    autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate([validation], use_sample_memory=False)

    assert autoencoder.state.decompiler_plan_embedding_weights
    assert after.embedding_cosine_similarity > before.embedding_cosine_similarity
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type == "decompiler_plan_embedding_weight"
        for contribution in introspection.top_embedding_contributions
    )


def test_decompiler_plan_legal_ir_view_head_lowers_holdout_view_ce() -> None:
    class DummyDocument:
        def canonical_hash(self):
            return "dummy-decompiler-plan-view-target"

    class DummyTarget:
        document = DummyDocument()
        losses = {"legal_ir_multiview_total_loss": 0.1}
        view_distribution = {
            "CEC.native": 0.2,
            "knowledge_graphs.neo4j_compat": 0.8,
        }

    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall provide notice before final action.",
    )
    targets = {
        train.sample_id: DummyTarget(),
        validation.sample_id: DummyTarget(),
    }
    autoencoder = AdaptiveModalAutoencoder(
        legal_ir_view_logit_scale=0.0,
        semantic_slot_legal_ir_view_logit_scale=0.0,
        family_semantic_slot_legal_ir_view_logit_scale=0.0,
        logic_signature_legal_ir_view_logit_scale=0.0,
        round_trip_signal_legal_ir_view_logit_scale=0.0,
        decompiler_plan_legal_ir_view_logit_scale=8.0,
    )
    before = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    autoencoder.evaluate([train], legal_ir_targets=targets, use_sample_memory=False)
    autoencoder._nudge_legal_ir_view_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    assert autoencoder.state.decompiler_plan_legal_ir_view_logits
    assert (
        after.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
        < before.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
    )
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type == "decompiler_plan_legal_ir_view_logit"
        for contribution in introspection.top_family_contributions
    )


def test_predicate_argument_family_head_lowers_holdout_ce() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall provide notice before final action.",
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_family_logit_scale=0.0,
        semantic_slot_family_logit_scale=0.0,
        legal_ir_view_family_logit_scale=0.0,
        semantic_slot_legal_ir_view_family_logit_scale=0.0,
        compiler_quality_family_logit_scale=0.0,
        logic_signature_family_logit_scale=0.0,
        round_trip_signal_family_logit_scale=0.0,
        decompiler_plan_family_logit_scale=0.0,
        predicate_argument_family_logit_scale=8.0,
    )
    before = autoencoder.evaluate([validation], use_sample_memory=False)

    autoencoder._nudge_family_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate([validation], use_sample_memory=False)

    assert autoencoder.state.predicate_argument_family_logits
    assert after.cross_entropy_loss < before.cross_entropy_loss
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type == "predicate_argument_family_logit"
        for contribution in introspection.top_family_contributions
    )


def test_predicate_argument_embedding_head_transfers_cosine_to_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall provide notice before final action.",
        embedding_vector=[1.0, 0.0],
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=8.0,
        cosine_reconstruction_weight=0.0,
    )
    before = autoencoder.evaluate([validation], use_sample_memory=False)

    autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate([validation], use_sample_memory=False)

    assert autoencoder.state.predicate_argument_embedding_weights
    assert after.embedding_cosine_similarity > before.embedding_cosine_similarity
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type == "predicate_argument_embedding_weight"
        for contribution in introspection.top_embedding_contributions
    )


def test_predicate_argument_legal_ir_view_head_lowers_holdout_view_ce() -> None:
    class DummyDocument:
        def canonical_hash(self):
            return "dummy-predicate-argument-view-target"

    class DummyTarget:
        document = DummyDocument()
        losses = {"legal_ir_multiview_total_loss": 0.1}
        view_distribution = {
            "CEC.native": 0.2,
            "knowledge_graphs.neo4j_compat": 0.8,
        }

    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall provide notice before final action.",
    )
    targets = {
        train.sample_id: DummyTarget(),
        validation.sample_id: DummyTarget(),
    }
    autoencoder = AdaptiveModalAutoencoder(
        legal_ir_view_logit_scale=0.0,
        semantic_slot_legal_ir_view_logit_scale=0.0,
        family_semantic_slot_legal_ir_view_logit_scale=0.0,
        logic_signature_legal_ir_view_logit_scale=0.0,
        round_trip_signal_legal_ir_view_logit_scale=0.0,
        decompiler_plan_legal_ir_view_logit_scale=0.0,
        predicate_argument_legal_ir_view_logit_scale=8.0,
    )
    before = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    autoencoder.evaluate([train], legal_ir_targets=targets, use_sample_memory=False)
    autoencoder._nudge_legal_ir_view_logits(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    assert autoencoder.state.predicate_argument_legal_ir_view_logits
    assert (
        after.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
        < before.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
    )
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type == "predicate_argument_legal_ir_view_logit"
        for contribution in introspection.top_family_contributions
    )


def test_embedding_head_update_normalization_shares_multi_head_step_budget() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
        embedding_vector=[1.0, 0.0],
    )
    unnormalized = AdaptiveModalAutoencoder(
        embedding_head_update_normalization=0.0,
        cosine_reconstruction_weight=0.0,
    )
    normalized = AdaptiveModalAutoencoder(
        embedding_head_update_normalization=1.0,
        cosine_reconstruction_weight=0.0,
    )

    unnormalized._nudge_decoded_embedding(
        sample,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    normalized._nudge_decoded_embedding(
        sample,
        learning_rate=0.5,
        update_sample_memory=False,
    )

    unnormalized_norm = _vector_norm(
        unnormalized.state.compiler_quality_embedding_weights["quality:bias"]
    )
    normalized_norm = _vector_norm(
        normalized.state.compiler_quality_embedding_weights["quality:bias"]
    )

    assert normalized._active_embedding_update_head_count(sample) > 1
    assert 0.0 < normalized_norm < unnormalized_norm


def test_family_logit_head_update_normalization_shares_multi_head_step_budget() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
    )
    head_scales = {
        "compiler_quality_family_logit_scale": 1.0,
        "logic_signature_family_logit_scale": 1.0,
        "round_trip_signal_family_logit_scale": 1.0,
        "decompiler_plan_family_logit_scale": 1.0,
        "predicate_argument_family_logit_scale": 1.0,
        "feature_family_logit_scale": 1.0,
        "semantic_slot_family_logit_scale": 1.0,
    }
    unnormalized = AdaptiveModalAutoencoder(
        family_logit_head_update_normalization=0.0,
        **head_scales,
    )
    normalized = AdaptiveModalAutoencoder(
        family_logit_head_update_normalization=1.0,
        **head_scales,
    )

    unnormalized._nudge_family_logits(
        sample,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    normalized._nudge_family_logits(
        sample,
        learning_rate=0.5,
        update_sample_memory=False,
    )

    unnormalized_step = _max_abs(
        unnormalized.state.compiler_quality_family_logits["quality:bias"]
    )
    normalized_step = _max_abs(
        normalized.state.compiler_quality_family_logits["quality:bias"]
    )

    assert normalized._active_family_logit_update_head_count(sample) > 1
    assert 0.0 < normalized_step < unnormalized_step


def test_legal_ir_view_head_update_normalization_shares_multi_head_step_budget() -> None:
    class DummyDocument:
        def canonical_hash(self):
            return "dummy-normalized-legal-ir-view-target"

    class DummyTarget:
        document = DummyDocument()
        losses = {"legal_ir_multiview_total_loss": 0.1}
        view_distribution = {
            "CEC.native": 0.2,
            "knowledge_graphs.neo4j_compat": 0.8,
        }

    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
    )
    targets = {sample.sample_id: DummyTarget()}
    unnormalized = AdaptiveModalAutoencoder(
        legal_ir_view_head_update_normalization=0.0,
    )
    normalized = AdaptiveModalAutoencoder(
        legal_ir_view_head_update_normalization=1.0,
    )

    unnormalized.evaluate([sample], legal_ir_targets=targets, use_sample_memory=False)
    normalized.evaluate([sample], legal_ir_targets=targets, use_sample_memory=False)
    unnormalized._nudge_legal_ir_view_logits(
        sample,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    normalized._nudge_legal_ir_view_logits(
        sample,
        learning_rate=0.5,
        update_sample_memory=False,
    )

    unnormalized_step = unnormalized.state.legal_ir_view_logits[
        "knowledge_graphs.neo4j_compat"
    ]
    normalized_step = normalized.state.legal_ir_view_logits[
        "knowledge_graphs.neo4j_compat"
    ]

    assert normalized._active_legal_ir_view_logit_update_head_count(sample) > 1
    assert 0.0 < normalized_step < unnormalized_step


def test_family_legal_ir_view_joint_embedding_head_transfers_cosine_to_holdout() -> None:
    class DummyDocument:
        def canonical_hash(self):
            return "dummy-family-view-target"

    class DummyTarget:
        document = DummyDocument()
        losses = {"legal_ir_multiview_total_loss": 0.1}
        view_distribution = {"knowledge_graphs.neo4j_compat": 1.0}

    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice.",
        embedding_vector=[1.0, 0.0],
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall publish notice.",
        embedding_vector=[1.0, 0.0],
    )
    targets = {
        train.sample_id: DummyTarget(),
        validation.sample_id: DummyTarget(),
    }
    autoencoder = AdaptiveModalAutoencoder(
        feature_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=4.0,
        cosine_reconstruction_weight=0.0,
    )
    before = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    autoencoder.evaluate([train], legal_ir_targets=targets, use_sample_memory=False)
    autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate(
        [validation],
        legal_ir_targets=targets,
        use_sample_memory=False,
    )

    assert autoencoder.state.family_legal_ir_view_embedding_weights
    assert after.embedding_cosine_similarity > before.embedding_cosine_similarity
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type == "family_legal_ir_view_embedding_weight"
        for contribution in introspection.top_embedding_contributions
    )


def test_family_semantic_slot_embedding_head_transfers_cosine_to_holdout() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
        embedding_vector=[0.0, 1.0],
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency shall publish notice before final action.",
        embedding_vector=[0.0, 1.0],
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_embedding_weight_scale=0.0,
        family_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_semantic_slot_embedding_weight_scale=8.0,
        cosine_reconstruction_weight=0.0,
    )
    before = autoencoder.evaluate([validation], use_sample_memory=False)

    autoencoder._nudge_decoded_embedding(
        train,
        learning_rate=0.5,
        update_sample_memory=False,
    )
    after = autoencoder.evaluate([validation], use_sample_memory=False)

    assert autoencoder.state.family_semantic_slot_embedding_weights
    assert after.embedding_cosine_similarity > before.embedding_cosine_similarity
    introspection = autoencoder.introspect_sample(validation)
    assert any(
        contribution.contribution_type == "family_semantic_slot_embedding_weight"
        for contribution in introspection.top_embedding_contributions
    )


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

    class DummyDocument:
        def canonical_hash(self):
            return "source-decompiled-introspection-target"

    class DummyTarget:
        document = DummyDocument()
        losses = {
            "source_decompiled_text_embedding_cosine_loss": 0.72,
            "source_decompiled_text_token_loss": 0.61,
            "structural_text_reconstruction_loss": 0.61,
        }
        view_distribution = {}

    autoencoder.evaluate(
        [sample],
        legal_ir_targets={sample.sample_id: DummyTarget()},
        use_sample_memory=False,
    )

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
    assert introspection.cosine_loss == pytest.approx(
        max(0.0, 1.0 - introspection.cosine_similarity)
    )
    assert data["pipeline_stage_diagnostics"]["autoencoder_embedding_cosine_gap"] == (
        pytest.approx(introspection.cosine_loss)
    )
    assert data["source_decompiled_text_embedding_cosine_loss"] == pytest.approx(0.72)
    assert data["source_decompiled_text_token_loss"] == pytest.approx(0.61)
    assert data["pipeline_stage_diagnostics"][
        "source_decompiled_text_embedding_cosine_loss"
    ] == pytest.approx(0.72)
    assert data["pipeline_stage_diagnostics"]["source_decompiled_text_token_loss"] == (
        pytest.approx(0.61)
    )
    assert "semantic_decompiler" in introspection.pipeline_stage_focus
    assert "refine_semantic_decompiler_reconstruction" in introspection.synthesis_focus
    assert data["cosine_loss"] == pytest.approx(introspection.cosine_loss)
    if introspection.cosine_loss > 0.20:
        assert "autoencoder_embedding_head" in introspection.pipeline_stage_focus
        assert "improve_encoder_decoder_reconstruction" in introspection.synthesis_focus
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


def test_feature_codec_keys_are_augmented_with_fallback_modal_features() -> None:
    class SparseFeatureCodec:
        def feature_keys_for_sample(self, sample):
            return [f"codec-only:{sample.sample_id}"]

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
    autoencoder = AdaptiveModalAutoencoder(
        feature_codec=SparseFeatureCodec(),
        feature_family_logit_scale=1.0,
        max_codec_feature_keys=8,
    )
    before = autoencoder.evaluate([validation])
    todo = type(
        "Todo",
        (),
        {
            "action": "improve_modal_family_classifier",
            "loss_name": "cross_entropy_loss",
            "sample_ids": [train.sample_id],
            "todo_id": "ce-feature-codec-augmented",
        },
    )()

    autoencoder.apply_todos([todo], {train.sample_id: train}, learning_rate=0.5)
    after = autoencoder.evaluate([validation])
    validation_features = autoencoder._feature_keys_for(validation)

    assert f"codec-only:{validation.sample_id}" in validation_features
    assert "modal-family:deontic" in validation_features
    assert "token:agency" in validation_features
    assert after.cross_entropy_loss < before.cross_entropy_loss


def test_sparse_codec_noise_does_not_drown_fallback_family_updates() -> None:
    class NoisyFeatureCodec:
        def feature_keys_for_sample(self, sample):
            return [
                f"codec-noise:{sample.sample_id}:{index}"
                for index in range(100)
            ]

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
    autoencoder = AdaptiveModalAutoencoder(
        feature_codec=NoisyFeatureCodec(),
        feature_family_logit_scale=1.0,
        max_codec_feature_keys=100,
    )
    before = autoencoder.evaluate([validation])
    todo = type(
        "Todo",
        (),
        {
            "action": "improve_modal_family_classifier",
            "loss_name": "cross_entropy_loss",
            "sample_ids": [train.sample_id],
            "todo_id": "ce-feature-noisy-codec",
        },
    )()

    autoencoder.apply_todos([todo], {train.sample_id: train}, learning_rate=0.5)
    after = autoencoder.evaluate([validation])
    fallback_logit = autoencoder.state.feature_family_logits["modal-family:deontic"][
        "deontic"
    ]
    noisy_logit = autoencoder.state.feature_family_logits[
        f"codec-noise:{train.sample_id}:0"
    ]["deontic"]

    assert fallback_logit > noisy_logit
    assert after.cross_entropy_loss < before.cross_entropy_loss


def test_fallback_features_include_structural_and_ngram_signals() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552(a)",
        text=(
            "If the applicant files notice, the agency must approve the permit "
            "except when records are incomplete."
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(
        max_token_features=8,
        max_token_bigram_features=8,
        max_token_trigram_features=4,
    )

    features = autoencoder._fallback_feature_keys_for(sample)

    assert "title:5" in features
    assert "section-prefix:552" in features
    assert "cue:deontic" in features
    assert "token:agency" in features
    assert "token2:agency_must" in features
    assert any(feature.startswith("modal-family:") for feature in features)
    assert any(feature.startswith("frame-family:") for feature in features)
    assert any(feature.startswith("predicate:") for feature in features)
    assert "condition-count-bin:2-3" in features
    assert "exception-count-bin:1" in features
    assert "frame-logic-ontology:modal_flogic_ir" in features
    assert any(feature.startswith("semantic-slot:modal-operator:") for feature in features)
    assert any(feature.startswith("semantic-slot:slot-pair:") for feature in features)

    legal_ir_features = autoencoder._legal_ir_view_core_feature_keys_for(sample)
    assert any(
        feature.startswith("legal-ir:predicate:")
        for feature in legal_ir_features
    )
    assert "legal-ir:condition-count-bin:2-3" in legal_ir_features
    assert "legal-ir:exception-count-bin:1" in legal_ir_features
    assert any(
        feature.startswith("legal-ir:semantic-slot:modal-operator:")
        for feature in legal_ir_features
    )
    assert any(
        feature.startswith("legal-ir:semantic-slot:slot-pair:")
        for feature in legal_ir_features
    )


def test_feature_update_groups_prioritize_structural_fallback_over_noisy_codec_keys() -> None:
    class NoisyFeatureCodec:
        def feature_keys_for_sample(self, sample):
            return [f"codec-noise:{index}" for index in range(100)]

    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_codec=NoisyFeatureCodec(),
        max_codec_feature_keys=100,
    )

    groups = autoencoder._feature_update_groups_for(sample, step=1.0)
    per_feature_step = {
        feature: feature_step
        for keys, feature_step in groups
        for feature in keys
    }

    assert per_feature_step["modal-family:deontic"] > per_feature_step["token:agency"]
    assert per_feature_step["token:agency"] > per_feature_step["codec-noise:0"]


def test_feature_logit_clip_bounds_large_feature_aggregates() -> None:
    class DenseFeatureCodec:
        def feature_keys_for_sample(self, sample):
            return [f"dense:{index}" for index in range(400)]

    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_codec=DenseFeatureCodec(),
        feature_family_logit_scale=1.0,
        max_codec_feature_keys=400,
        max_token_features=0,
        feature_activity_reference=64,
        feature_logit_clip=3.0,
    )
    for feature in autoencoder._feature_keys_for(sample):
        autoencoder.state.feature_family_logits[feature] = {"deontic": 10.0}

    logits = autoencoder._logits_for(sample, use_sample_memory=False)

    assert logits["deontic"] == pytest.approx(3.0)


def test_feature_codec_keys_are_disabled_by_default_for_fast_fallback_features() -> None:
    class ExpensiveFeatureCodec:
        def feature_keys_for_sample(self, sample):
            raise AssertionError("codec feature keys should be opt-in")

    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before final action.",
    )
    autoencoder = AdaptiveModalAutoencoder(feature_codec=ExpensiveFeatureCodec())

    features = autoencoder._feature_keys_for(sample)

    assert "modal-family:deontic" in features
    assert "token:agency" in features


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


def test_codex_gate_skips_call_when_local_losses_and_prover_are_good() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice within 30 days.",
    )
    autoencoder = AdaptiveModalAutoencoder()
    config = CodexCallGateConfig(
        min_cosine_similarity=0.0,
        max_cross_entropy_loss=10.0,
        max_reconstruction_loss=10.0,
        codex_call_cost=0.0,
    )
    signal = ProverCompilationSignal(
        attempted_count=1,
        valid_count=1,
        verified_by=["modal:tdfol_modal_tableaux"],
    )

    decision = autoencoder.codex_call_decision(
        sample,
        config=config,
        prover_signal=signal,
    )

    assert decision.should_call_codex is False
    assert decision.reasons == []
    assert decision.prover_signal.compiles is True
    assert decision.feature_signature_hash


def test_codex_gate_calls_once_per_feature_signature() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice within 30 days.",
    )
    autoencoder = AdaptiveModalAutoencoder()
    cache = CodexCallCache()
    config = CodexCallGateConfig(
        require_prover_compilation=False,
        min_cosine_similarity=0.99,
        max_cross_entropy_loss=0.01,
        codex_call_cost=0.0,
    )

    first = autoencoder.codex_call_decision(sample, config=config, cache=cache)
    cache.record_codex_call(first)
    second = autoencoder.codex_call_decision(sample, config=config, cache=cache)

    assert first.should_call_codex is True
    assert "low_embedding_cosine_similarity" in first.reasons
    assert "high_cross_entropy_loss" in first.reasons
    assert second.should_call_codex is False
    assert "duplicate_feature_signature" in second.suppressed_reasons
    assert cache.codex_call_count == 1


def test_codex_gate_escalates_missing_formula_before_api_cache() -> None:
    sample = build_us_code_sample(
        title="5",
        section="555",
        text="The agency publishes records.",
    )
    autoencoder = AdaptiveModalAutoencoder()
    config = CodexCallGateConfig(
        min_cosine_similarity=0.0,
        max_cross_entropy_loss=10.0,
        max_reconstruction_loss=10.0,
        codex_call_cost=0.0,
    )

    decision = autoencoder.codex_call_decision(sample, config=config)

    assert decision.should_call_codex is True
    assert "missing_or_invalid_symbolic_ir" in decision.reasons
    assert "no_modal_formula_for_prover" in decision.reasons
    assert decision.prover_signal.attempted_count == 0


def test_modal_prover_compilation_signal_uses_local_router() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice.",
    )

    signal = evaluate_modal_prover_compilation(sample)

    assert signal.compiles is True
    assert signal.valid_count == 1
    assert signal.unavailable_count == 0
    assert signal.details[0]["statuses"] == ["valid"]
    assert signal.verified_by == ["modal:tdfol_modal_tableaux"]


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
        compiler_quality_embedding_weights={
            "quality:symbolic:missing-formula": [0.21, 0.22]
        },
        compiler_quality_family_logits={
            "quality:symbolic:missing-formula": {"hybrid": 0.31}
        },
        logic_signature_embedding_weights={
            "signature:role-schema:deontic:clause:arity:0": [0.23, 0.24]
        },
        logic_signature_family_logits={
            "signature:role-schema:deontic:clause:arity:0": {"deontic": 0.33}
        },
        logic_signature_legal_ir_view_logits={
            "signature:role-schema:deontic:clause:arity:0": {
                "knowledge_graphs.neo4j_compat": 0.35
            }
        },
        round_trip_signal_embedding_weights={
            "round-trip:modal-family-ambiguous": [0.25, 0.26]
        },
        round_trip_signal_family_logits={
            "round-trip:modal-family-ambiguous": {"hybrid": 0.37}
        },
        round_trip_signal_legal_ir_view_logits={
            "round-trip:modal-family-ambiguous": {
                "knowledge_graphs.neo4j_compat": 0.39
            }
        },
        decompiler_plan_embedding_weights={
            "decompiler-plan:cue:deontic": [0.27, 0.28]
        },
        decompiler_plan_family_logits={
            "decompiler-plan:cue:deontic": {"deontic": 0.41}
        },
        decompiler_plan_legal_ir_view_logits={
            "decompiler-plan:cue:deontic": {
                "knowledge_graphs.neo4j_compat": 0.43
            }
        },
        predicate_argument_embedding_weights={
            "predicate-argument:role-arity:deontic:clause:0": [0.29, 0.3]
        },
        predicate_argument_family_logits={
            "predicate-argument:role-arity:deontic:clause:0": {"deontic": 0.45}
        },
        predicate_argument_legal_ir_view_logits={
            "predicate-argument:role-arity:deontic:clause:0": {
                "knowledge_graphs.neo4j_compat": 0.47
            }
        },
        feature_embedding_weights={"token:agency": [0.01, -0.01]},
        family_embedding_weights={"deontic": [0.03, 0.04]},
        family_semantic_slot_embedding_weights={
            "deontic||slot:condition-present": [0.11, 0.12]
        },
        family_semantic_slot_legal_ir_view_embedding_weights={
            "deontic||slot:condition-present||knowledge_graphs.neo4j_compat": [
                0.15,
                0.16,
            ]
        },
        family_legal_ir_view_embedding_weights={
            "deontic||knowledge_graphs.neo4j_compat": [0.09, 0.1]
        },
        semantic_slot_embedding_weights={"slot:modal-operator:deontic:d:o": [0.07, 0.08]},
        feature_family_logits={"modal-family:deontic": {"deontic": 0.2}},
        semantic_slot_family_logits={"slot:modal-operator:deontic:d:o": {"deontic": 0.5}},
        family_semantic_slot_legal_ir_view_logits={
            "deontic||slot:condition-present": {"knowledge_graphs.neo4j_compat": 0.95}
        },
        legal_ir_view_logits={"deontic.ir": 0.3},
        legal_ir_view_embedding_weights={"knowledge_graphs.neo4j_compat": [0.05, 0.06]},
        legal_ir_view_family_logits={
            "knowledge_graphs.neo4j_compat": {"deontic": 0.8}
        },
        feature_legal_ir_view_logits={"legal-ir:cue:deontic": {"deontic.ir": 0.4}},
        semantic_slot_legal_ir_view_embedding_weights={
            "slot:condition-present||knowledge_graphs.neo4j_compat": [0.13, 0.14]
        },
        semantic_slot_legal_ir_view_family_logits={
            "slot:condition-present||knowledge_graphs.neo4j_compat": {"deontic": 0.9}
        },
        semantic_slot_legal_ir_view_logits={
            "slot:modal-operator:deontic:d:o": {"knowledge_graphs.neo4j_compat": 0.7}
        },
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
        compiler_quality_embedding_weights={
            "quality:symbolic:missing-formula": [0.21, 0.22]
        },
        compiler_quality_family_logits={
            "quality:symbolic:missing-formula": {"hybrid": 0.31}
        },
        logic_signature_embedding_weights={
            "signature:role-schema:deontic:clause:arity:0": [0.23, 0.24]
        },
        logic_signature_family_logits={
            "signature:role-schema:deontic:clause:arity:0": {"deontic": 0.33}
        },
        logic_signature_legal_ir_view_logits={
            "signature:role-schema:deontic:clause:arity:0": {
                "knowledge_graphs.neo4j_compat": 0.35
            }
        },
        round_trip_signal_embedding_weights={
            "round-trip:modal-family-ambiguous": [0.25, 0.26]
        },
        round_trip_signal_family_logits={
            "round-trip:modal-family-ambiguous": {"hybrid": 0.37}
        },
        round_trip_signal_legal_ir_view_logits={
            "round-trip:modal-family-ambiguous": {
                "knowledge_graphs.neo4j_compat": 0.39
            }
        },
        decompiler_plan_embedding_weights={
            "decompiler-plan:cue:deontic": [0.27, 0.28]
        },
        decompiler_plan_family_logits={
            "decompiler-plan:cue:deontic": {"deontic": 0.41}
        },
        decompiler_plan_legal_ir_view_logits={
            "decompiler-plan:cue:deontic": {
                "knowledge_graphs.neo4j_compat": 0.43
            }
        },
        predicate_argument_embedding_weights={
            "predicate-argument:role-arity:deontic:clause:0": [0.29, 0.3]
        },
        predicate_argument_family_logits={
            "predicate-argument:role-arity:deontic:clause:0": {"deontic": 0.45}
        },
        predicate_argument_legal_ir_view_logits={
            "predicate-argument:role-arity:deontic:clause:0": {
                "knowledge_graphs.neo4j_compat": 0.47
            }
        },
        feature_embedding_weights={"token:agency": [0.01, -0.01]},
        family_embedding_weights={"deontic": [0.03, 0.04]},
        family_semantic_slot_embedding_weights={
            "deontic||slot:condition-present": [0.11, 0.12]
        },
        family_semantic_slot_legal_ir_view_embedding_weights={
            "deontic||slot:condition-present||knowledge_graphs.neo4j_compat": [
                0.15,
                0.16,
            ]
        },
        family_legal_ir_view_embedding_weights={
            "deontic||knowledge_graphs.neo4j_compat": [0.09, 0.1]
        },
        semantic_slot_embedding_weights={"slot:modal-operator:deontic:d:o": [0.07, 0.08]},
        feature_family_logits={"modal-family:deontic": {"deontic": 0.2}},
        semantic_slot_family_logits={"slot:modal-operator:deontic:d:o": {"deontic": 0.5}},
        family_semantic_slot_legal_ir_view_logits={
            "deontic||slot:condition-present": {"knowledge_graphs.neo4j_compat": 0.95}
        },
        legal_ir_view_logits={"deontic.ir": 0.3},
        legal_ir_view_embedding_weights={"knowledge_graphs.neo4j_compat": [0.05, 0.06]},
        legal_ir_view_family_logits={
            "knowledge_graphs.neo4j_compat": {"deontic": 0.8}
        },
        feature_legal_ir_view_logits={"legal-ir:cue:deontic": {"deontic.ir": 0.4}},
        semantic_slot_legal_ir_view_embedding_weights={
            "slot:condition-present||knowledge_graphs.neo4j_compat": [0.13, 0.14]
        },
        semantic_slot_legal_ir_view_family_logits={
            "slot:condition-present||knowledge_graphs.neo4j_compat": {"deontic": 0.9}
        },
        semantic_slot_legal_ir_view_logits={
            "slot:modal-operator:deontic:d:o": {"knowledge_graphs.neo4j_compat": 0.7}
        },
        applied_todo_ids=["todo-1"],
    )

    generalizable = state.generalizable_copy()

    assert generalizable.decoded_embeddings == {}
    assert generalizable.family_logits == {}
    assert generalizable.applied_todo_ids == []
    assert (
        generalizable.compiler_quality_embedding_weights
        == state.compiler_quality_embedding_weights
    )
    assert (
        generalizable.compiler_quality_family_logits
        == state.compiler_quality_family_logits
    )
    assert (
        generalizable.logic_signature_embedding_weights
        == state.logic_signature_embedding_weights
    )
    assert (
        generalizable.logic_signature_family_logits
        == state.logic_signature_family_logits
    )
    assert (
        generalizable.logic_signature_legal_ir_view_logits
        == state.logic_signature_legal_ir_view_logits
    )
    assert (
        generalizable.round_trip_signal_embedding_weights
        == state.round_trip_signal_embedding_weights
    )
    assert (
        generalizable.round_trip_signal_family_logits
        == state.round_trip_signal_family_logits
    )
    assert (
        generalizable.round_trip_signal_legal_ir_view_logits
        == state.round_trip_signal_legal_ir_view_logits
    )
    assert (
        generalizable.decompiler_plan_embedding_weights
        == state.decompiler_plan_embedding_weights
    )
    assert (
        generalizable.decompiler_plan_family_logits
        == state.decompiler_plan_family_logits
    )
    assert (
        generalizable.decompiler_plan_legal_ir_view_logits
        == state.decompiler_plan_legal_ir_view_logits
    )
    assert (
        generalizable.predicate_argument_embedding_weights
        == state.predicate_argument_embedding_weights
    )
    assert (
        generalizable.predicate_argument_family_logits
        == state.predicate_argument_family_logits
    )
    assert (
        generalizable.predicate_argument_legal_ir_view_logits
        == state.predicate_argument_legal_ir_view_logits
    )
    assert generalizable.feature_embedding_weights == state.feature_embedding_weights
    assert generalizable.family_embedding_weights == state.family_embedding_weights
    assert (
        generalizable.family_semantic_slot_embedding_weights
        == state.family_semantic_slot_embedding_weights
    )
    assert (
        generalizable.family_semantic_slot_legal_ir_view_embedding_weights
        == state.family_semantic_slot_legal_ir_view_embedding_weights
    )
    assert (
        generalizable.family_legal_ir_view_embedding_weights
        == state.family_legal_ir_view_embedding_weights
    )
    assert generalizable.feature_family_logits == state.feature_family_logits
    assert generalizable.legal_ir_view_logits == state.legal_ir_view_logits
    assert (
        generalizable.legal_ir_view_embedding_weights
        == state.legal_ir_view_embedding_weights
    )
    assert (
        generalizable.legal_ir_view_family_logits
        == state.legal_ir_view_family_logits
    )
    assert (
        generalizable.semantic_slot_embedding_weights
        == state.semantic_slot_embedding_weights
    )
    assert generalizable.semantic_slot_family_logits == state.semantic_slot_family_logits
    assert (
        generalizable.family_semantic_slot_legal_ir_view_logits
        == state.family_semantic_slot_legal_ir_view_logits
    )
    assert (
        generalizable.semantic_slot_legal_ir_view_embedding_weights
        == state.semantic_slot_legal_ir_view_embedding_weights
    )
    assert (
        generalizable.semantic_slot_legal_ir_view_family_logits
        == state.semantic_slot_legal_ir_view_family_logits
    )
    assert (
        generalizable.semantic_slot_legal_ir_view_logits
        == state.semantic_slot_legal_ir_view_logits
    )
    assert (
        generalizable.feature_legal_ir_view_logits
        == state.feature_legal_ir_view_logits
    )


def test_training_state_copy_avoids_sorted_serialization(monkeypatch) -> None:
    state = ModalAutoencoderTrainingState(
        decoded_embeddings={"sample": [0.1, 0.2]},
        family_logits={"sample": {"deontic": 1.0}},
        feature_embedding_weights={"token:agency": [0.3, -0.1]},
        feature_family_logits={"modal-family:deontic": {"deontic": 0.2}},
        applied_todo_ids=["todo-1"],
    )

    def fail_to_dict(self: ModalAutoencoderTrainingState) -> dict[str, object]:
        raise AssertionError("copy() must not use sorted JSON serialization")

    monkeypatch.setattr(ModalAutoencoderTrainingState, "to_dict", fail_to_dict)

    copied = state.copy()
    copied.decoded_embeddings["sample"][0] = 9.0
    copied.feature_embedding_weights["token:agency"][0] = 8.0
    copied.family_logits["sample"]["deontic"] = 7.0
    copied.applied_todo_ids.append("todo-2")

    assert state.decoded_embeddings["sample"] == [0.1, 0.2]
    assert state.feature_embedding_weights["token:agency"] == [0.3, -0.1]
    assert state.family_logits["sample"]["deontic"] == 1.0
    assert state.applied_todo_ids == ["todo-1"]


def test_average_generalizable_state_reuses_prior_feature_learning() -> None:
    first = ModalAutoencoderTrainingState(
        decoded_embeddings={"sample-a": [1.0, 1.0]},
        family_logits={"sample-a": {"deontic": 4.0}},
        compiler_quality_embedding_weights={
            "quality:symbolic:missing-formula": [0.2, 0.6]
        },
        compiler_quality_family_logits={
            "quality:symbolic:missing-formula": {"hybrid": 0.8}
        },
        logic_signature_embedding_weights={
            "signature:role-schema:deontic:clause:arity:0": [0.6, 1.0]
        },
        logic_signature_family_logits={
            "signature:role-schema:deontic:clause:arity:0": {"deontic": 1.0}
        },
        logic_signature_legal_ir_view_logits={
            "signature:role-schema:deontic:clause:arity:0": {
                "knowledge_graphs.neo4j_compat": 1.2
            }
        },
        round_trip_signal_embedding_weights={
            "round-trip:modal-family-ambiguous": [0.2, 0.6]
        },
        round_trip_signal_family_logits={
            "round-trip:modal-family-ambiguous": {"hybrid": 0.8}
        },
        round_trip_signal_legal_ir_view_logits={
            "round-trip:modal-family-ambiguous": {
                "knowledge_graphs.neo4j_compat": 1.2
            }
        },
        decompiler_plan_embedding_weights={
            "decompiler-plan:cue:deontic": [0.4, 0.8]
        },
        decompiler_plan_family_logits={
            "decompiler-plan:cue:deontic": {"deontic": 1.0}
        },
        decompiler_plan_legal_ir_view_logits={
            "decompiler-plan:cue:deontic": {
                "knowledge_graphs.neo4j_compat": 1.2
            }
        },
        predicate_argument_embedding_weights={
            "predicate-argument:role-arity:deontic:clause:0": [0.6, 1.0]
        },
        predicate_argument_family_logits={
            "predicate-argument:role-arity:deontic:clause:0": {"deontic": 1.0}
        },
        predicate_argument_legal_ir_view_logits={
            "predicate-argument:role-arity:deontic:clause:0": {
                "knowledge_graphs.neo4j_compat": 1.2
            }
        },
        feature_embedding_weights={"token:agency": [0.2, -0.2]},
        family_embedding_weights={"deontic": [0.2, 0.4]},
        family_semantic_slot_embedding_weights={
            "deontic||slot:condition-present": [0.4, 0.8]
        },
        family_semantic_slot_legal_ir_view_embedding_weights={
            "deontic||slot:condition-present||knowledge_graphs.neo4j_compat": [
                0.8,
                1.2,
            ]
        },
        family_legal_ir_view_embedding_weights={
            "deontic||knowledge_graphs.neo4j_compat": [0.2, 0.8]
        },
        semantic_slot_embedding_weights={"slot:modal-operator:deontic:d:o": [0.1, 0.3]},
        feature_family_logits={"modal-family:deontic": {"deontic": 0.6}},
        semantic_slot_family_logits={"slot:modal-operator:deontic:d:o": {"deontic": 0.9}},
        family_semantic_slot_legal_ir_view_logits={
            "deontic||slot:condition-present": {"knowledge_graphs.neo4j_compat": 1.2}
        },
        legal_ir_view_logits={"deontic.ir": 0.6},
        legal_ir_view_embedding_weights={"knowledge_graphs.neo4j_compat": [0.2, 0.6]},
        legal_ir_view_family_logits={
            "knowledge_graphs.neo4j_compat": {"deontic": 0.6}
        },
        feature_legal_ir_view_logits={"legal-ir:cue:deontic": {"deontic.ir": 0.8}},
        semantic_slot_legal_ir_view_embedding_weights={
            "slot:condition-present||knowledge_graphs.neo4j_compat": [0.6, 1.0]
        },
        semantic_slot_legal_ir_view_family_logits={
            "slot:condition-present||knowledge_graphs.neo4j_compat": {"deontic": 1.0}
        },
        semantic_slot_legal_ir_view_logits={
            "slot:modal-operator:deontic:d:o": {"knowledge_graphs.neo4j_compat": 0.9}
        },
    )
    second = ModalAutoencoderTrainingState(
        decoded_embeddings={"sample-b": [2.0, 2.0]},
        family_logits={"sample-b": {"temporal": 4.0}},
        compiler_quality_embedding_weights={
            "quality:symbolic:missing-formula": [0.4, 1.0]
        },
        compiler_quality_family_logits={
            "quality:symbolic:missing-formula": {"hybrid": 0.4}
        },
        logic_signature_embedding_weights={
            "signature:role-schema:deontic:clause:arity:0": [0.2, 0.4]
        },
        logic_signature_family_logits={
            "signature:role-schema:deontic:clause:arity:0": {"deontic": 0.4}
        },
        logic_signature_legal_ir_view_logits={
            "signature:role-schema:deontic:clause:arity:0": {
                "knowledge_graphs.neo4j_compat": 0.8
            }
        },
        round_trip_signal_embedding_weights={
            "round-trip:modal-family-ambiguous": [0.4, 1.0]
        },
        round_trip_signal_family_logits={
            "round-trip:modal-family-ambiguous": {"hybrid": 0.4}
        },
        round_trip_signal_legal_ir_view_logits={
            "round-trip:modal-family-ambiguous": {
                "knowledge_graphs.neo4j_compat": 0.8
            }
        },
        decompiler_plan_embedding_weights={
            "decompiler-plan:cue:deontic": [0.2, 0.6]
        },
        decompiler_plan_family_logits={
            "decompiler-plan:cue:deontic": {"deontic": 0.4}
        },
        decompiler_plan_legal_ir_view_logits={
            "decompiler-plan:cue:deontic": {
                "knowledge_graphs.neo4j_compat": 0.8
            }
        },
        predicate_argument_embedding_weights={
            "predicate-argument:role-arity:deontic:clause:0": [0.2, 0.4]
        },
        predicate_argument_family_logits={
            "predicate-argument:role-arity:deontic:clause:0": {"deontic": 0.4}
        },
        predicate_argument_legal_ir_view_logits={
            "predicate-argument:role-arity:deontic:clause:0": {
                "knowledge_graphs.neo4j_compat": 0.8
            }
        },
        feature_embedding_weights={"token:agency": [0.4, -0.4]},
        family_embedding_weights={"deontic": [0.4, 0.8]},
        family_semantic_slot_embedding_weights={
            "deontic||slot:condition-present": [0.8, 1.2]
        },
        family_semantic_slot_legal_ir_view_embedding_weights={
            "deontic||slot:condition-present||knowledge_graphs.neo4j_compat": [
                0.4,
                0.8,
            ]
        },
        family_legal_ir_view_embedding_weights={
            "deontic||knowledge_graphs.neo4j_compat": [0.4, 1.2]
        },
        semantic_slot_embedding_weights={"slot:modal-operator:deontic:d:o": [0.3, 0.7]},
        feature_family_logits={"modal-family:deontic": {"deontic": 0.2}},
        semantic_slot_family_logits={"slot:modal-operator:deontic:d:o": {"deontic": 0.3}},
        family_semantic_slot_legal_ir_view_logits={
            "deontic||slot:condition-present": {"knowledge_graphs.neo4j_compat": 0.8}
        },
        legal_ir_view_logits={"deontic.ir": 0.2},
        legal_ir_view_embedding_weights={"knowledge_graphs.neo4j_compat": [0.4, 1.0]},
        legal_ir_view_family_logits={
            "knowledge_graphs.neo4j_compat": {"deontic": 0.2}
        },
        feature_legal_ir_view_logits={"legal-ir:cue:deontic": {"deontic.ir": 0.4}},
        semantic_slot_legal_ir_view_embedding_weights={
            "slot:condition-present||knowledge_graphs.neo4j_compat": [0.2, 0.4]
        },
        semantic_slot_legal_ir_view_family_logits={
            "slot:condition-present||knowledge_graphs.neo4j_compat": {"deontic": 0.4}
        },
        semantic_slot_legal_ir_view_logits={
            "slot:modal-operator:deontic:d:o": {"knowledge_graphs.neo4j_compat": 0.5}
        },
    )

    averaged = ModalAutoencoderTrainingState.average_generalizable([first, second])

    assert averaged.decoded_embeddings == {}
    assert averaged.family_logits == {}
    assert averaged.compiler_quality_embedding_weights[
        "quality:symbolic:missing-formula"
    ] == pytest.approx([0.3, 0.8])
    assert averaged.compiler_quality_family_logits[
        "quality:symbolic:missing-formula"
    ]["hybrid"] == pytest.approx(0.6)
    assert averaged.logic_signature_embedding_weights[
        "signature:role-schema:deontic:clause:arity:0"
    ] == pytest.approx([0.4, 0.7])
    assert averaged.logic_signature_family_logits[
        "signature:role-schema:deontic:clause:arity:0"
    ]["deontic"] == pytest.approx(0.7)
    assert averaged.logic_signature_legal_ir_view_logits[
        "signature:role-schema:deontic:clause:arity:0"
    ]["knowledge_graphs.neo4j_compat"] == pytest.approx(1.0)
    assert averaged.round_trip_signal_embedding_weights[
        "round-trip:modal-family-ambiguous"
    ] == pytest.approx([0.3, 0.8])
    assert averaged.round_trip_signal_family_logits[
        "round-trip:modal-family-ambiguous"
    ]["hybrid"] == pytest.approx(0.6)
    assert averaged.round_trip_signal_legal_ir_view_logits[
        "round-trip:modal-family-ambiguous"
    ]["knowledge_graphs.neo4j_compat"] == pytest.approx(1.0)
    assert averaged.decompiler_plan_embedding_weights[
        "decompiler-plan:cue:deontic"
    ] == pytest.approx([0.3, 0.7])
    assert averaged.decompiler_plan_family_logits[
        "decompiler-plan:cue:deontic"
    ]["deontic"] == pytest.approx(0.7)
    assert averaged.decompiler_plan_legal_ir_view_logits[
        "decompiler-plan:cue:deontic"
    ]["knowledge_graphs.neo4j_compat"] == pytest.approx(1.0)
    assert averaged.predicate_argument_embedding_weights[
        "predicate-argument:role-arity:deontic:clause:0"
    ] == pytest.approx([0.4, 0.7])
    assert averaged.predicate_argument_family_logits[
        "predicate-argument:role-arity:deontic:clause:0"
    ]["deontic"] == pytest.approx(0.7)
    assert averaged.predicate_argument_legal_ir_view_logits[
        "predicate-argument:role-arity:deontic:clause:0"
    ]["knowledge_graphs.neo4j_compat"] == pytest.approx(1.0)
    assert averaged.feature_embedding_weights["token:agency"] == pytest.approx([0.3, -0.3])
    assert averaged.family_embedding_weights["deontic"] == pytest.approx([0.3, 0.6])
    assert averaged.family_semantic_slot_embedding_weights[
        "deontic||slot:condition-present"
    ] == pytest.approx([0.6, 1.0])
    assert averaged.family_semantic_slot_legal_ir_view_embedding_weights[
        "deontic||slot:condition-present||knowledge_graphs.neo4j_compat"
    ] == pytest.approx([0.6, 1.0])
    assert averaged.family_legal_ir_view_embedding_weights[
        "deontic||knowledge_graphs.neo4j_compat"
    ] == pytest.approx([0.3, 1.0])
    assert averaged.legal_ir_view_embedding_weights[
        "knowledge_graphs.neo4j_compat"
    ] == pytest.approx([0.3, 0.8])
    assert averaged.legal_ir_view_family_logits[
        "knowledge_graphs.neo4j_compat"
    ]["deontic"] == pytest.approx(0.4)
    assert averaged.semantic_slot_embedding_weights[
        "slot:modal-operator:deontic:d:o"
    ] == pytest.approx([0.2, 0.5])
    assert averaged.feature_family_logits["modal-family:deontic"]["deontic"] == pytest.approx(0.4)
    assert averaged.semantic_slot_family_logits[
        "slot:modal-operator:deontic:d:o"
    ]["deontic"] == pytest.approx(0.6)
    assert averaged.family_semantic_slot_legal_ir_view_logits[
        "deontic||slot:condition-present"
    ]["knowledge_graphs.neo4j_compat"] == pytest.approx(1.0)
    assert averaged.semantic_slot_legal_ir_view_embedding_weights[
        "slot:condition-present||knowledge_graphs.neo4j_compat"
    ] == pytest.approx([0.4, 0.7])
    assert averaged.semantic_slot_legal_ir_view_family_logits[
        "slot:condition-present||knowledge_graphs.neo4j_compat"
    ]["deontic"] == pytest.approx(0.7)
    assert averaged.semantic_slot_legal_ir_view_logits[
        "slot:modal-operator:deontic:d:o"
    ]["knowledge_graphs.neo4j_compat"] == pytest.approx(0.7)
    assert averaged.legal_ir_view_logits["deontic.ir"] == pytest.approx(0.4)
    assert (
        averaged.feature_legal_ir_view_logits["legal-ir:cue:deontic"]["deontic.ir"]
        == pytest.approx(0.6)
    )


def test_frame_and_symbolic_penalties_for_valid_sample() -> None:
    sample = build_us_code_sample(
        title="42",
        section="1437f",
        text="The tenant may request a housing voucher accommodation.",
    )

    assert frame_ranking_loss(sample) == pytest.approx(0.0)
    assert symbolic_validity_penalty(sample) == pytest.approx(0.0)
