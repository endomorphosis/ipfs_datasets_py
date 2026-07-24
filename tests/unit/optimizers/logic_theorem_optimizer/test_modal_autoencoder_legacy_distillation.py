"""Contracts for bounded legacy-only embedding-tail distillation."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    ModalAutoencoderTrainingState,
    mse_loss,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_legacy_distillation import (
    DirectBulkEmbeddingTransferError,
    LegacyDistillationConfig,
    LegacyDistillationPromotionConfig,
    LegacyDistillationPromotionError,
    LegacyEmbeddingAdapterBundle,
    distill_legacy_embedding_tails,
    evaluate_legacy_distillation_promotion,
    forbid_direct_bulk_embedding_replacement,
    require_legacy_distillation_promotion,
)


def _teacher() -> ModalAutoencoderTrainingState:
    return ModalAutoencoderTrainingState(
        decoded_embeddings={"source-sample-must-not-transfer": [99.0, 99.0]},
        family_logits={
            "source-sample-must-not-transfer": {"deontic": 99.0}
        },
        feature_embedding_weights={
            "legacy-alpha": [3.0, 0.0, 0.0],
            "legacy-bravo": [0.0, 2.0, 0.0],
            "legacy-charlie": [0.0, 0.0, 1.0],
            "shared": [9.0, 9.0, 9.0],
        },
        family_embedding_weights={
            "legacy-family": [0.5, -0.5, 0.25],
        },
    )


def _student() -> ModalAutoencoderTrainingState:
    return ModalAutoencoderTrainingState(
        decoded_embeddings={"current-sample": [0.1, 0.2, 0.3]},
        feature_embedding_weights={"shared": [0.1, 0.2, 0.3]},
    )


def test_distillation_is_bounded_low_rank_and_never_mutates_states() -> None:
    teacher = _teacher()
    student = _student()
    teacher_before = teacher.to_dict()
    student_before = student.to_dict()

    result = distill_legacy_embedding_tails(
        teacher,
        student,
        config=LegacyDistillationConfig(
            rank=1,
            max_rows_per_adapter=2,
            influence=0.0,
            seed=17,
        ),
        split_id="heldout-2026q3",
    )

    assert result.accepted is True
    assert teacher.to_dict() == teacher_before
    assert student.to_dict() == student_before
    assert set(result.bundle.adapters) == {
        "family_embedding_weights",
        "feature_embedding_weights",
    }
    feature = result.bundle.adapters["feature_embedding_weights"]
    assert feature.rank == 1
    assert feature.row_count == 2
    assert feature.coefficients.shape == (2, 1)
    assert feature.basis.shape == (1, 3)
    assert "shared" not in feature.keys
    assert result.report["excluded_shared_student_row_count"] == 1
    assert result.report["sample_memory_included"] is False
    assert result.report["sample_memory_fields_excluded"] == [
        "decoded_embeddings",
        "family_logits",
    ]
    assert result.report["lineage"]["seed"] == 17
    assert result.report["lineage"]["split_id"] == "heldout-2026q3"
    assert result.report["lineage"]["teacher_checkpoint_sha256"]
    assert result.report["lineage"]["student_checkpoint_sha256"]


def test_default_zero_influence_is_exact_and_shadow_is_counterfactual() -> None:
    result = distill_legacy_embedding_tails(
        _teacher(),
        _student(),
        config=LegacyDistillationConfig(rank=3, max_rows_per_adapter=3),
    )
    adapter = result.bundle.adapters["feature_embedding_weights"]

    assert result.bundle.zero_influence is True
    assert adapter.adjustment(
        {"legacy-alpha": 1.0},
        dimensions=3,
    ) == [0.0, 0.0, 0.0]
    assert adapter.shadow_adjustment(
        {"legacy-alpha": 1.0},
        dimensions=3,
    ) == pytest.approx([1.0, 0.0, 0.0])
    assert adapter.influence == 0.0

    autoencoder = AdaptiveModalAutoencoder(
        state=_student(),
        compute_device="cpu",
        legacy_embedding_adapters=result.bundle,
    )
    report = autoencoder.legacy_embedding_adapter_report()
    assert report["attached"] is True
    assert report["zero_influence"] is True
    assert autoencoder.state.feature_embedding_weights == {
        "shared": [0.1, 0.2, 0.3]
    }
    assert autoencoder.detach_legacy_embedding_adapters() is result.bundle
    assert autoencoder.legacy_embedding_adapter_report()["adapter_count"] == 0


def test_shadow_counterfactual_does_not_mutate_runtime_influence() -> None:
    result = distill_legacy_embedding_tails(
        _teacher(),
        _student(),
        config=LegacyDistillationConfig(rank=3, max_rows_per_adapter=3),
    )
    adapter = result.bundle.adapters["feature_embedding_weights"]

    before = adapter.to_dict()
    shadow = adapter.shadow_adjustment(
        {"legacy-alpha": 1.0},
        dimensions=3,
    )

    assert shadow == pytest.approx([1.0, 0.0, 0.0])
    assert adapter.to_dict() == before


def test_promoted_adapter_influences_decode_without_hydrating_student_rows() -> None:
    student = ModalAutoencoderTrainingState()
    sample = build_us_code_sample(
        title="5",
        section="121",
        text="The agency shall publish the final rule.",
        embedding_vector=[1.0, -0.5, 0.25],
    )
    autoencoder = AdaptiveModalAutoencoder(
        state=student,
        compute_device="cpu",
    )
    baseline = autoencoder.decode(
        autoencoder.encode(sample, use_sample_memory=False)
    )
    feature = autoencoder._feature_keys_for(sample)[0]
    scale = autoencoder.feature_embedding_weight_scale
    teacher_vector = [
        (target - current) / scale
        for target, current in zip(sample.embedding_vector, baseline)
    ]
    result = distill_legacy_embedding_tails(
        ModalAutoencoderTrainingState(
            feature_embedding_weights={feature: teacher_vector}
        ),
        student,
        config=LegacyDistillationConfig(
            rank=3,
            influence=0.0,
            max_adjustment_norm=10.0,
        ),
    )

    with pytest.raises(LegacyDistillationPromotionError):
        result.bundle.set_influence(1.0)
    promotion = evaluate_legacy_distillation_promotion(
        [
            _promotion_packet(seed, lineage_id=result.bundle.lineage.lineage_id)
            for seed in (7, 11, 19)
        ],
        lineage_id=result.bundle.lineage.lineage_id,
    )
    result.bundle.promote(promotion, influence=1.0)
    autoencoder.attach_legacy_embedding_adapters(result.bundle)
    adapted = autoencoder.decode(
        autoencoder.encode(sample, use_sample_memory=False)
    )

    assert adapted != pytest.approx(baseline)
    assert mse_loss(sample.embedding_vector, adapted) < mse_loss(
        sample.embedding_vector,
        baseline,
    )
    assert student.feature_embedding_weights == {}


def test_confidence_gate_and_capacity_are_deterministic() -> None:
    config = LegacyDistillationConfig(
        rank=2,
        max_rows_per_adapter=2,
        minimum_confidence=0.5,
        influence=1.0,
    )
    confidences = {
        "feature_embedding_weights": {
            "legacy-alpha": 0.8,
            "legacy-bravo": 0.9,
            "legacy-charlie": 0.4,
        }
    }

    first = distill_legacy_embedding_tails(
        _teacher(),
        _student(),
        config=config,
        confidence_by_adapter=confidences,
        seed=91,
    )
    second = distill_legacy_embedding_tails(
        _teacher(),
        _student(),
        config=config,
        confidence_by_adapter=confidences,
        seed=91,
    )

    adapter = first.bundle.adapters["feature_embedding_weights"]
    assert adapter.keys == ("legacy-bravo", "legacy-alpha")
    assert adapter.adjustment({"legacy-charlie": 1.0}, dimensions=3) == [
        0.0,
        0.0,
        0.0,
    ]
    assert first.report == second.report
    assert first.bundle.to_dict() == second.bundle.to_dict()
    assert first.report["excluded_low_confidence_row_count"] == 1


def test_source_or_decoded_text_memory_keys_are_not_distilled_or_reported() -> None:
    teacher = ModalAutoencoderTrainingState(
        feature_embedding_weights={
            "semantic-safe": [1.0, 0.0],
            "raw source text that must stay private": [9.0, 9.0],
            "decoded_text:private": [8.0, 8.0],
        }
    )

    result = distill_legacy_embedding_tails(
        teacher,
        ModalAutoencoderTrainingState(),
        config=LegacyDistillationConfig(rank=2),
    )

    assert result.bundle.adapters["feature_embedding_weights"].keys == (
        "semantic-safe",
    )
    assert (
        result.report["excluded_incompatible_or_text_memory_row_count"] == 2
    )
    serialized_report = json.dumps(result.report, sort_keys=True)
    assert "private" not in serialized_report
    assert "raw source text" not in serialized_report


def test_direct_bulk_embedding_transfer_is_unconditionally_forbidden() -> None:
    with pytest.raises(
        DirectBulkEmbeddingTransferError,
        match="regressed autoencoder cosine",
    ):
        LegacyDistillationConfig(direct_bulk_embedding_replacement=True)
    with pytest.raises(DirectBulkEmbeddingTransferError, match="forbidden"):
        forbid_direct_bulk_embedding_replacement(_teacher(), _student())


def test_adapter_gradients_and_optimizer_moments_are_isolated() -> None:
    result = distill_legacy_embedding_tails(
        _teacher(),
        _student(),
        config=LegacyDistillationConfig(
            rank=1,
            max_rows_per_adapter=3,
            influence=0.0,
        ),
    )
    bundle = result.bundle
    sibling = bundle.adapters["family_embedding_weights"]
    sibling_before = (sibling.adapter_id, sibling.optimizer_state_id)

    report = bundle.train_adapter(
        "feature_embedding_weights",
        {"legacy-alpha": [0.0, 1.0, 0.0]},
        learning_rate=0.01,
    )

    assert report["trained_row_count"] == 1
    assert report["sibling_optimizer_state_unchanged"] is True
    assert (sibling.adapter_id, sibling.optimizer_state_id) == sibling_before
    assert (
        bundle.adapters["feature_embedding_weights"].optimizer_state_dict()[
            "step"
        ]
        == 1
    )
    assert sibling.optimizer_state_dict()["step"] == 0
    # Adapter optimization never becomes a student optimizer update.
    assert _student().feature_embedding_weights == {
        "shared": [0.1, 0.2, 0.3]
    }


def test_adapter_checkpoint_round_trip_binds_lineage_and_optimizer_state(
    tmp_path,
) -> None:
    result = distill_legacy_embedding_tails(
        _teacher(),
        _student(),
        config=LegacyDistillationConfig(rank=2, influence=0.25),
        split_id="heldout-fixed",
        seed=23,
    )
    result.bundle.train_adapter(
        "feature_embedding_weights",
        {"legacy-alpha": [1.0, 1.0, 0.0]},
    )
    payload = result.bundle.to_dict()
    restored = LegacyEmbeddingAdapterBundle.from_dict(
        json.loads(json.dumps(payload, sort_keys=True))
    )
    path = tmp_path / "legacy-adapters.json"
    result.bundle.save_json(path)
    loaded = LegacyEmbeddingAdapterBundle.load_json(path)

    assert restored.to_dict() == payload
    assert loaded.to_dict() == payload
    assert restored.lineage.lineage_id == result.bundle.lineage.lineage_id
    assert restored.adapters[
        "feature_embedding_weights"
    ].optimizer_state_dict()["step"] == 1
    assert payload["sample_memory_included"] is False
    assert "source-sample-must-not-transfer" not in json.dumps(payload)
    assert not list(tmp_path.glob(".legacy-adapters.json.tmp-*"))


def _promotion_packet(
    seed: int,
    *,
    regress: str = "",
    lineage_id: str = "lineage-1",
) -> dict:
    baseline = {
        "autoencoder_cross_entropy_loss": 1.0,
        "autoencoder_cosine_similarity": 0.70,
        "ir_cross_entropy_loss": 0.8,
        "ir_cosine_similarity": 0.75,
        "semantic_equivalence_score": 0.90,
        "hammer_proof_success_rate": 0.80,
        "reconstruction_loss": 0.20,
        "round_trip_reconstruction_success_rate": 0.85,
        "provenance_alignment_success_rate": 0.90,
        "uncertainty_calibration_error": 0.10,
        "holdout_loss": 0.40,
        "source_copy_reward_hack_penalty": 0.05,
    }
    candidate = {
        **baseline,
        "autoencoder_cross_entropy_loss": 0.9,
        "autoencoder_cosine_similarity": 0.72,
    }
    if regress:
        if regress.endswith("loss") or "penalty" in regress or "error" in regress:
            candidate[regress] = baseline[regress] + 0.01
        else:
            candidate[regress] = baseline[regress] - 0.01
    return {
        "baseline": baseline,
        "candidate": candidate,
        "lineage_id": lineage_id,
        "per_family": {
            "deontic": {
                "baseline": {
                    "semantic_equivalence_score": 0.9,
                    "proof_success_rate": 0.8,
                    "reconstruction_loss": 0.2,
                },
                "candidate": {
                    "semantic_equivalence_score": 0.9,
                    "proof_success_rate": 0.8,
                    "reconstruction_loss": 0.2,
                },
            }
        },
        "seed": seed,
        "split_id": "heldout-fixed",
    }


def test_multi_seed_promotion_requires_improvement_and_every_guardrail() -> None:
    packets = [_promotion_packet(seed) for seed in (7, 11, 19)]

    report = evaluate_legacy_distillation_promotion(
        packets,
        lineage_id="lineage-1",
    )

    assert report["promotion_allowed"] is True
    assert report["seed_count"] == 3
    assert report["aggregate_autoencoder_ce_improvement"] == pytest.approx(0.1)
    assert report["aggregate_autoencoder_cosine_improvement"] == pytest.approx(
        0.02
    )
    assert all(row["objective_passed"] for row in report["seed_reports"])


def test_promotion_fails_closed_on_regression_missing_seed_or_family() -> None:
    packets = [
        _promotion_packet(7),
        _promotion_packet(11, regress="hammer_proof_success_rate"),
    ]
    report = evaluate_legacy_distillation_promotion(
        packets,
        config=LegacyDistillationPromotionConfig(
            minimum_seeds=3,
            required_families=("deontic", "frame_logic"),
        ),
        lineage_id="lineage-1",
    )

    assert report["promotion_allowed"] is False
    assert "seed_11:proof_regression" in report["reasons"]
    assert "insufficient_unique_seeds" in report["reasons"]
    assert "missing_required_families" in report["reasons"]
    with pytest.raises(LegacyDistillationPromotionError):
        require_legacy_distillation_promotion(
            packets,
            config=LegacyDistillationPromotionConfig(minimum_seeds=3),
            lineage_id="lineage-1",
        )


def test_promotion_requires_one_fixed_split_and_each_required_family() -> None:
    packets = [_promotion_packet(seed) for seed in (7, 11, 19)]
    packets[1]["split_id"] = "heldout-other"
    packets[2]["per_family"] = {
        "frame_logic": packets[2]["per_family"]["deontic"]
    }

    report = evaluate_legacy_distillation_promotion(
        packets,
        config=LegacyDistillationPromotionConfig(
            required_families=("deontic", "frame_logic"),
        ),
        lineage_id="lineage-1",
    )

    assert report["promotion_allowed"] is False
    assert "inconsistent_held_out_splits" in report["reasons"]
    assert "seed_7:missing_required_families" in report["reasons"]
    assert "seed_19:missing_required_families" in report["reasons"]


def test_promotion_requires_semantic_evidence_for_every_family() -> None:
    packets = [_promotion_packet(seed) for seed in (7, 11, 19)]
    for packet in packets:
        packet["per_family"]["deontic"] = {
            "baseline": {"proof_success_rate": 0.8},
            "candidate": {"proof_success_rate": 0.8},
        }

    report = evaluate_legacy_distillation_promotion(
        packets,
        lineage_id="lineage-1",
    )

    assert report["promotion_allowed"] is False
    assert (
        "seed_7:family_deontic_missing_semantic_guardrail"
        in report["reasons"]
    )
