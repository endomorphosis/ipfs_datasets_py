"""Shape, gradient, and serialization tests for PGIR-030 experiment arms."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_grammar_decoder import (
    COMPATIBLE_ARCHITECTURE_ARMS,
    COMPATIBLE_ARCHITECTURE_INIT_CHECKPOINT_SCHEMA,
    CompatibleLearnedArchitecture,
    IncompatibleLegacyWarmStartError,
    MODEL_LEGACY_1_IDENTITY,
    SHARED_ENCODER_TYPED_HEAD_ARCHITECTURE_ARM,
    SHARED_LATENT_ARCHITECTURE_ARM,
    build_compatible_learned_architecture,
    compatible_architecture_suite,
    evaluate_legacy_warm_start,
    require_legacy_warm_start,
)


def _pgir030_deontic_ir() -> dict:
    return {
        "family": "deontic",
        "rules": [
            {
                "modality": "obligation",
                "subject": "agency",
                "action": "provide_notice",
            }
        ],
    }


@pytest.mark.parametrize("arm", COMPATIBLE_ARCHITECTURE_ARMS)
def test_compatible_architecture_arms_are_runnable_with_explicit_heads(arm: str) -> None:
    architecture = build_compatible_learned_architecture(arm, seed=7)
    result = architecture.forward(
        _pgir030_deontic_ir(),
        family="deontic",
        source_text="The agency shall provide notice.",
        target_family="deontic",
        proof_label="unchecked",
    )

    assert result["arm"] == arm
    assert result["winner"] is False
    assert result["latent_normalized"] is True
    assert result["shapes"]["latent"] == [architecture.dim]
    assert result["shapes"]["token_ids"] == [architecture.config.max_seq_len]
    assert result["shapes"]["family_logits"] == [len(architecture.families)]
    assert len(result["latent"]) == architecture.dim
    assert pytest.approx(math.sqrt(sum(value * value for value in result["latent"]))) == 1.0
    assert set(result["heads"]) == {"family", "view", "reconstruction", "uncertainty"}
    assert result["conditioning"]["proof_label_differentiable"] is False
    assert result["conditioning"]["source_surface_separated"] is True
    assert "aleatoric_uncertainty" in result
    assert "epistemic_uncertainty" in result
    assert result["token_class_counts"]["family"] >= 1
    assert result["tokenizer_vocabulary_cid"] == architecture.tokenizer.vocabulary_cid


@pytest.mark.parametrize("arm", COMPATIBLE_ARCHITECTURE_ARMS)
def test_compatible_architecture_gradients_and_serialization(arm: str) -> None:
    architecture = build_compatible_learned_architecture(arm, seed=3)
    payload = architecture.forward(
        _pgir030_deontic_ir(),
        family="deontic",
        target_family="deontic",
    )
    gradients = architecture.backward(payload)
    restored = CompatibleLearnedArchitecture.from_dict(architecture.to_dict())
    restored_forward = restored.forward(
        _pgir030_deontic_ir(),
        family="deontic",
        target_family="deontic",
    )
    checkpoint = architecture.initialization_checkpoint()
    estimate = architecture.parameter_resource_estimate()

    assert gradients["gradient_norm"] > 0.0
    assert gradients["proof_in_gradient_path"] is False
    assert restored_forward["latent"] == payload["latent"]
    assert restored_forward["family_logits"] == payload["family_logits"]
    assert checkpoint["schema"] == COMPATIBLE_ARCHITECTURE_INIT_CHECKPOINT_SCHEMA
    assert checkpoint["winner"] is False
    assert checkpoint["legacy_promoted"] is False
    assert estimate["parameter_count"] == architecture.parameter_count()
    assert estimate["gpu_required"] is False
    assert estimate["bytes_fp32"] == architecture.parameter_count() * 4

    finite_index = 0
    if arm == SHARED_ENCODER_TYPED_HEAD_ARCHITECTURE_ARM:
        original = architecture.parameters["typed_heads"]["deontic"]["bias"][finite_index]
        architecture.parameters["typed_heads"]["deontic"]["bias"][finite_index] = original + 1.0e-4
        plus = architecture.forward(
            _pgir030_deontic_ir(),
            family="deontic",
            target_family="deontic",
        )["loss"]
        architecture.parameters["typed_heads"]["deontic"]["bias"][finite_index] = original - 1.0e-4
        minus = architecture.forward(
            _pgir030_deontic_ir(),
            family="deontic",
            target_family="deontic",
        )["loss"]
        architecture.parameters["typed_heads"]["deontic"]["bias"][finite_index] = original
    else:
        original = architecture.parameters["family_bias"][finite_index]
        architecture.parameters["family_bias"][finite_index] = original + 1.0e-4
        plus = architecture.forward(
            _pgir030_deontic_ir(),
            family="deontic",
            target_family="deontic",
        )["loss"]
        architecture.parameters["family_bias"][finite_index] = original - 1.0e-4
        minus = architecture.forward(
            _pgir030_deontic_ir(),
            family="deontic",
            target_family="deontic",
        )["loss"]
        architecture.parameters["family_bias"][finite_index] = original
    numeric = (plus - minus) / 2.0e-4
    assert numeric == pytest.approx(gradients["d_family_bias"][finite_index], rel=1.0e-2, abs=1.0e-3)


def test_both_compatible_arms_exist_without_choosing_a_winner() -> None:
    suite = compatible_architecture_suite(seed=0)
    shared = suite["instances"][SHARED_LATENT_ARCHITECTURE_ARM].forward(
        _pgir030_deontic_ir(),
        family="deontic",
        target_family="deontic",
    )
    typed = suite["instances"][SHARED_ENCODER_TYPED_HEAD_ARCHITECTURE_ARM].forward(
        _pgir030_deontic_ir(),
        family="deontic",
        target_family="deontic",
    )
    checkpoint = suite["instances"][SHARED_LATENT_ARCHITECTURE_ARM].initialization_checkpoint()

    assert suite["winner"] is False
    assert suite["legacy_promoted"] is False
    assert set(suite["arms"]) == set(COMPATIBLE_ARCHITECTURE_ARMS)
    assert shared["arm"] == SHARED_LATENT_ARCHITECTURE_ARM
    assert typed["arm"] == SHARED_ENCODER_TYPED_HEAD_ARCHITECTURE_ARM
    assert shared["heads"]["family"]["shared"] is True
    assert typed["heads"]["family"]["shared"] is False
    assert checkpoint["tokenizer_vocabulary_cid"] == suite["tokenizer_vocabulary_cid"]
    assert suite["instances"][SHARED_LATENT_ARCHITECTURE_ARM].tokenizer.frozen is True


def test_legacy_warm_start_requires_compatibility_and_quarantine() -> None:
    denied = evaluate_legacy_warm_start(
        compatibility_passed=True,
        quarantine_passed=False,
    )
    assert denied["allowed"] is False
    assert denied["promoted"] is False
    assert denied["authority"] is False
    assert denied["identity"] == MODEL_LEGACY_1_IDENTITY
    with pytest.raises(IncompatibleLegacyWarmStartError):
        require_legacy_warm_start(compatibility_passed=True, quarantine_passed=False)
    admitted = require_legacy_warm_start(
        compatibility_passed=True,
        quarantine_passed=True,
        architecture_version="proof_aware_auxiliary_heads_v2",
    )
    assert admitted["allowed"] is True
    assert admitted["promoted"] is False
    assert admitted["authority"] is False


def test_import_and_construction_are_side_effect_free(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_grammar_decoder as module

    tokenizer = module.LegalIRFrozenTokenizer.canonical()
    suite = module.compatible_architecture_suite(tokenizer=tokenizer, seed=1)
    assert tokenizer.frozen is True
    assert suite["winner"] is False
    assert list(tmp_path.iterdir()) == []
