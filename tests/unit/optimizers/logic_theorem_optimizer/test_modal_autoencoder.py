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
    introspection = autoencoder.introspect_sample(sample).to_dict()
    assert introspection["legal_ir_losses"]["legal_ir_multiview_total_loss"] > 0.0


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
    autoencoder = AdaptiveModalAutoencoder(feature_codec=NoisyFeatureCodec())

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
        max_token_features=0,
        feature_activity_reference=64,
        feature_logit_clip=3.0,
    )
    for feature in autoencoder._feature_keys_for(sample):
        autoencoder.state.feature_family_logits[feature] = {"deontic": 10.0}

    logits = autoencoder._logits_for(sample, use_sample_memory=False)

    assert logits["deontic"] == pytest.approx(3.0)


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
