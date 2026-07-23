"""Regression coverage for packet-001271 compiler ambiguity policy pairs."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_AMBIGUITY_PACKET_001271_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


def _mock_ranking(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> List[Dict[str, Any]]:
    predicted_share = max(0.75, abs(family_margin) + 0.1)
    target_share = predicted_share + family_margin
    return [
        {
            "family": predicted_family,
            "count": 0,
            "logit": 1.3,
            "share_raw": predicted_share,
            "share": predicted_share,
            "source": "logit_softmax_fallback",
        },
        {
            "family": target_family,
            "count": 0,
            "logit": 1.2,
            "share_raw": target_share,
            "share": target_share,
            "source": "logit_softmax_fallback",
        },
    ]


def _matching_explicit_ambiguity(
    *,
    ambiguities: Sequence[ModalCompilationAmbiguity],
    predicted_family: str,
    target_family: str,
    expected_margin: float,
) -> ModalCompilationAmbiguity | None:
    for ambiguity in ambiguities:
        if not ambiguity.ambiguity_type.startswith("adaptive_"):
            continue
        if ambiguity.ambiguity_type == "adaptive_family_margin_low":
            continue
        metadata = ambiguity.metadata
        if metadata.get("adaptive_predicted_family_source") != "adaptive_logits":
            continue
        if metadata.get("predicted_family") != predicted_family:
            continue
        if metadata.get("target_family") != target_family:
            continue
        margin_raw = float(metadata.get("family_margin_raw", 0.0))
        if abs(margin_raw - expected_margin) > 1e-12:
            continue
        return ambiguity
    return None


def test_modal_registry_packet_001271_family_pairs_are_supported() -> None:
    expected_pairs = {
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
        ),
        (
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
        ),
        (
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.FRAME.value,
        ),
    }
    assert set(COMPILER_AMBIGUITY_PACKET_001271_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_compiler_preserves_packet_001271_explicit_ambiguity_margins() -> None:
    evidence_cases: Tuple[Tuple[str, str, str, float], ...] = (
        (
            "us-code-43-881.-9d139afe9396d027",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
            -0.166941999918,
        ),
        (
            "us-code-48-2174.-d4d269a7a590ffe9",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
            0.046931887403,
        ),
        (
            "us-code-7-323-5f06bf8223062016",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
            0.102335090317,
        ),
        (
            "us-code-10-12319-f76009e4befd7d13",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
            0.038394073705,
        ),
        (
            "us-code-16-8f-014e413d63268075",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.FRAME.value,
            -0.066016703465,
        ),
        (
            "us-code-36-150909-8f67861533db9040",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
            0.098302834997,
        ),
    )

    threshold = 0.15
    for sample_id, predicted_family, target_family, expected_margin in evidence_cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        ranking = _mock_ranking(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=expected_margin,
        )
        compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
            lambda _encoding, _ranking=ranking: _ranking
        )

        result = compiler.compile(
            "The Secretary shall confirm the plan before conveyance if required.",
            document_id=f"compiler-ambiguity-packet-001271-{sample_id}",
        )
        ambiguity = _matching_explicit_ambiguity(
            ambiguities=result.ambiguities,
            predicted_family=predicted_family,
            target_family=target_family,
            expected_margin=expected_margin,
        )
        assert ambiguity is not None, (
            sample_id,
            [item.to_dict() for item in result.ambiguities],
        )

        margin_direction = "outvoted" if expected_margin <= 0.0 else "contested"
        expected_priority = (
            abs(expected_margin) + threshold
            if margin_direction == "outvoted"
            else max(0.0, threshold - expected_margin)
        )
        assert ambiguity.ambiguity_type == (
            f"adaptive_{predicted_family}_{target_family}_{margin_direction}_margin_low"
        )
        assert ambiguity.severity == (
            "requires_rule" if margin_direction == "outvoted" else "review"
        )
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_compiler_required_policy_pair") is True
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert ambiguity.metadata.get("adaptive_margin_direction") == margin_direction
        assert (
            abs(
                float(ambiguity.metadata.get("family_margin_raw", 0.0))
                - expected_margin
            )
            <= 1e-12
        )
        assert (
            abs(float(ambiguity.metadata.get("priority", 0.0)) - expected_priority)
            <= 1e-12
        )
