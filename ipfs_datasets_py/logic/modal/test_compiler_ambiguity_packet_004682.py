"""Regression coverage for packet-004682 compiler ambiguity policy pairs."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    ModalLogicFamily,
)


def _mock_ranking(
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> List[Dict[str, Any]]:
    predicted_share = max(0.7, abs(float(family_margin)) + 0.1)
    target_share = predicted_share + family_margin
    return [
        {
            "family": predicted_family,
            "count": 0,
            "logit": 1.2,
            "share_raw": predicted_share,
            "share": predicted_share,
            "source": "logit_softmax_fallback",
        },
        {
            "family": target_family,
            "count": 0,
            "logit": 1.0,
            "share_raw": target_share,
            "share": target_share,
            "source": "logit_softmax_fallback",
        },
        {
            "family": ModalLogicFamily.ALETHIC.value,
            "count": 0,
            "logit": 0.8,
            "share_raw": max(0.0, min(target_share, predicted_share) / 2.0),
            "share": max(0.0, min(target_share, predicted_share) / 2.0),
            "source": "logit_softmax_fallback",
        },
    ]


def _matching_explicit_ambiguities(
    *,
    ambiguities: Sequence[ModalCompilationAmbiguity],
    predicted_family: str,
    target_family: str,
    expected_margin: float,
) -> List[ModalCompilationAmbiguity]:
    matches: List[ModalCompilationAmbiguity] = []
    for ambiguity in ambiguities:
        if not ambiguity.ambiguity_type.startswith("adaptive_"):
            continue
        if ambiguity.ambiguity_type == "adaptive_family_margin_low":
            continue
        metadata = ambiguity.metadata
        if metadata.get("predicted_family") != predicted_family:
            continue
        if metadata.get("target_family") != target_family:
            continue
        margin_raw = float(metadata.get("family_margin_raw", 0.0))
        if abs(margin_raw - expected_margin) > 1e-12:
            continue
        matches.append(ambiguity)
    return matches


def test_compiler_preserves_packet_004682_explicit_ambiguity_policy_pairs() -> None:
    evidence_cases: Tuple[Tuple[str, str, str, float, float], ...] = (
        (
            "us-code-42-1395a.-dc254d6ab03fdda9",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.257771928136,
            0.407771928136,
        ),
        (
            "us-code-42-6102.-f54c98d7f11dc95c",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.281916617228,
            0.431916617228,
        ),
        (
            "us-code-46-53111.-d55f3d8fd634aec0",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
            -0.87786416845,
            1.02786416845,
        ),
    )

    for sample_id, predicted_family, target_family, expected_margin, expected_priority in evidence_cases:
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
            "Within 30 days the Secretary shall submit the report as provided by statute.",
            document_id=sample_id,
        )
        matches = _matching_explicit_ambiguities(
            ambiguities=result.ambiguities,
            predicted_family=predicted_family,
            target_family=target_family,
            expected_margin=expected_margin,
        )
        assert matches, (sample_id, [ambiguity.to_dict() for ambiguity in result.ambiguities])
        ambiguity = matches[0]
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert ambiguity.severity == "requires_rule"
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
        assert (
            abs(float(ambiguity.metadata.get("adaptive_priority", 0.0)) - expected_priority)
            <= 1e-12
        )
