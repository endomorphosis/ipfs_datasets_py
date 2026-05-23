"""Tests for modal autoencoder baseline metrics."""

from __future__ import annotations

import math
from dataclasses import replace

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
    cross_entropy_distribution_loss,
    cross_entropy_loss,
    evaluate_modal_prover_compilation,
    frame_ranking_loss,
    mse_loss,
    symbolic_validity_penalty,
    _evaluation_improved_for_training,
    _legal_ir_target_cache_key,
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
        text="The agency must provide notice.",
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
    assert evaluation.legal_ir_losses["legal_ir_multiview_total_loss"] > 0.0
    assert evaluation.legal_ir_losses["legal_ir_multiview_view_coverage_loss"] == 0.0
    assert evaluation.legal_ir_losses["legal_ir_view_cross_entropy_loss"] > 0.0
    assert evaluation.legal_ir_target_hashes[sample.sample_id] == target.document.canonical_hash()
    assert evaluation.legal_ir_view_distribution
    assert evaluation.legal_ir_predicted_view_distribution
    payload = evaluation.to_dict()
    assert payload["legal_ir_losses"]["legal_ir_multiview_total_loss"] > 0.0
    assert payload["legal_ir_predicted_view_distribution"]


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
    autoencoder = AdaptiveModalAutoencoder(feature_family_logit_scale=1.0)
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
