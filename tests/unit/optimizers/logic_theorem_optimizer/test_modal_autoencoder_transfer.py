"""Transfer-boundary regressions used by legacy adapter validation."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_feature_transfer import (
    LegacyFeatureTransferConfig,
    transfer_legacy_autoencoder_features,
)


def test_safe_transfer_defers_embedding_tail_to_distillation() -> None:
    teacher = ModalAutoencoderTrainingState(
        decoded_embeddings={"legacy-sample": [9.0]},
        feature_embedding_weights={"legacy-only": [1.0, 2.0]},
        feature_family_logits={"legacy-only": {"deontic": 1.0}},
    )
    student = ModalAutoencoderTrainingState()

    result = transfer_legacy_autoencoder_features(
        teacher,
        student,
        config=LegacyFeatureTransferConfig(
            max_entries_per_group=4,
            minimum_source_signal_coverage=0.0,
        ),
    )

    assert result.state.feature_embedding_weights == {}
    assert result.state.feature_family_logits == {
        "legacy-only": {"deontic": 1.0}
    }
    assert result.state.decoded_embeddings == {}
    assert result.report["source_embedding_transfer_enabled"] is False


def test_transfer_preserves_current_student_rows() -> None:
    teacher = ModalAutoencoderTrainingState(
        feature_family_logits={"shared": {"deontic": 10.0}},
    )
    student = ModalAutoencoderTrainingState(
        feature_family_logits={"shared": {"temporal": 0.25}},
    )

    result = transfer_legacy_autoencoder_features(
        teacher,
        student,
        config=LegacyFeatureTransferConfig(
            max_entries_per_group=4,
            minimum_source_signal_coverage=0.0,
        ),
    )

    assert result.state.feature_family_logits["shared"] == {"temporal": 0.25}
    assert result.report["target_preserved"] is True
