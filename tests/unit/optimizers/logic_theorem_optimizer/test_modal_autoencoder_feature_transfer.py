from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    MODAL_AUTOENCODER_ARCHITECTURE_VERSION,
    MODAL_AUTOENCODER_LEGACY_ARCHITECTURE_VERSION,
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_feature_transfer import (
    LegacyFeatureTransferConfig,
    transfer_legacy_autoencoder_features,
)


def test_transfer_preserves_target_and_fills_legacy_only_rows() -> None:
    source = ModalAutoencoderTrainingState(
        architecture_version=MODAL_AUTOENCODER_LEGACY_ARCHITECTURE_VERSION,
        decoded_embeddings={"leaked-sample": [9.0]},
        family_logits={"leaked-sample": {"deontic": 9.0}},
        feature_embedding_weights={
            "legacy-high": [4.0, 0.0],
            "legacy-low": [1.0, 0.0],
            "shared": [8.0, 8.0],
        },
        feature_family_logits={
            "legacy-high": {"deontic": 4.0},
            "legacy-low": {"deontic": 1.0},
            "shared": {"deontic": 8.0},
        },
    )
    target = ModalAutoencoderTrainingState(
        feature_embedding_weights={
            "current": [3.0, 0.0],
            "shared": [0.25, 0.5],
        },
        feature_family_logits={
            "current": {"temporal": 3.0},
            "shared": {"temporal": 0.75},
        },
    )

    result = transfer_legacy_autoencoder_features(
        source,
        target,
        config=LegacyFeatureTransferConfig(
            max_entries_per_group=3,
            minimum_source_signal_coverage=0.0,
            transfer_source_embedding_weights=True,
        ),
        source_architecture_version=MODAL_AUTOENCODER_LEGACY_ARCHITECTURE_VERSION,
    )

    assert result.accepted is True
    assert result.state.architecture_version == MODAL_AUTOENCODER_ARCHITECTURE_VERSION
    assert result.state.feature_embedding_weights["shared"] == [0.25, 0.5]
    assert result.state.feature_family_logits["shared"] == {"temporal": 0.75}
    assert set(result.state.feature_embedding_weights) == {
        "current",
        "legacy-high",
        "shared",
    }
    assert "legacy-low" not in result.state.feature_embedding_weights
    assert result.state.decoded_embeddings == {}
    assert result.state.family_logits == {}
    assert result.report["target_preserved"] is True
    assert result.report["imported_source_field_entries"] == 2


def test_transfer_defers_legacy_only_embeddings_by_default() -> None:
    source = ModalAutoencoderTrainingState(
        feature_embedding_weights={"legacy": [4.0, 2.0]},
        feature_family_logits={"legacy": {"deontic": 3.0}},
    )
    target = ModalAutoencoderTrainingState()

    result = transfer_legacy_autoencoder_features(
        source,
        target,
        config=LegacyFeatureTransferConfig(
            max_entries_per_group=4,
            minimum_source_signal_coverage=0.0,
        ),
    )

    assert result.state.feature_embedding_weights == {}
    assert result.state.feature_family_logits == {
        "legacy": {"deontic": 3.0}
    }
    assert result.report["source_embedding_transfer_enabled"] is False
    assert "behavior distillation" in result.report["deferred_components"][
        "legacy_only_embedding_weights"
    ]


def test_transfer_fails_when_target_cannot_fit_without_eviction() -> None:
    source = ModalAutoencoderTrainingState(
        feature_family_logits={"legacy": {"deontic": 1.0}},
    )
    target = ModalAutoencoderTrainingState(
        feature_family_logits={
            "one": {"deontic": 1.0},
            "two": {"deontic": 1.0},
        },
    )

    with pytest.raises(ValueError, match="exceeding transfer capacity"):
        transfer_legacy_autoencoder_features(
            source,
            target,
            config=LegacyFeatureTransferConfig(max_entries_per_group=1),
        )


def test_transfer_never_synthesizes_legacy_proof_heads() -> None:
    source = ModalAutoencoderTrainingState(
        architecture_version=MODAL_AUTOENCODER_LEGACY_ARCHITECTURE_VERSION,
        proof_auxiliary_head_logits={
            "trusted_outcome": {
                "__global__": {"proved": 12.0},
            }
        },
        proof_feedback_version_fingerprint="legacy-untrusted",
        applied_proof_feedback_ids=["legacy-record"],
    )
    target = ModalAutoencoderTrainingState(
        proof_auxiliary_head_logits={
            "trusted_outcome": {
                "__global__": {"failed": 2.0},
            }
        },
        proof_feedback_version_fingerprint="current-trusted",
        applied_proof_feedback_ids=["current-record"],
    )

    result = transfer_legacy_autoencoder_features(
        source,
        target,
        config=LegacyFeatureTransferConfig(
            max_entries_per_group=4,
            minimum_source_signal_coverage=0.0,
        ),
        source_architecture_version=MODAL_AUTOENCODER_LEGACY_ARCHITECTURE_VERSION,
    )

    assert result.state.proof_feedback_version_fingerprint == "current-trusted"
    assert result.state.proof_auxiliary_head_logits == {
        "trusted_outcome": {
            "__global__": {"failed": 2.0},
        }
    }
    assert result.state.applied_proof_feedback_ids == ["current-record"]
    assert "versioned Hammer proof labels" in result.report[
        "deferred_components"
    ]["proof_auxiliary_head_logits"]


def test_transfer_is_deterministic() -> None:
    source = ModalAutoencoderTrainingState(
        feature_family_logits={
            "b": {"deontic": 2.0},
            "a": {"deontic": 2.0},
        },
    )
    target = ModalAutoencoderTrainingState()
    config = LegacyFeatureTransferConfig(
        max_entries_per_group=1,
        minimum_source_signal_coverage=0.0,
    )

    first = transfer_legacy_autoencoder_features(source, target, config=config)
    second = transfer_legacy_autoencoder_features(source, target, config=config)

    assert first.state.to_dict() == second.state.to_dict()
    assert first.report == second.report
    assert set(first.state.feature_family_logits) == {"a"}


def test_transfer_can_allowlist_source_fields() -> None:
    source = ModalAutoencoderTrainingState(
        feature_family_logits={"feature": {"deontic": 2.0}},
        feature_legal_ir_view_logits={"feature": {"deontic.ir": 3.0}},
    )
    target = ModalAutoencoderTrainingState()

    result = transfer_legacy_autoencoder_features(
        source,
        target,
        config=LegacyFeatureTransferConfig(
            max_entries_per_group=4,
            minimum_source_signal_coverage=0.0,
            source_field_allowlist=("feature_family_logits",),
        ),
    )

    assert result.state.feature_family_logits == {
        "feature": {"deontic": 2.0}
    }
    assert result.state.feature_legal_ir_view_logits == {}
    assert result.report["source_field_allowlist"] == [
        "feature_family_logits"
    ]


def test_transfer_rejects_unknown_allowlist_field() -> None:
    with pytest.raises(ValueError, match="unknown source transfer fields"):
        LegacyFeatureTransferConfig(
            source_field_allowlist=("not_a_real_head",)
        )
