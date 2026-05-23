"""Regression coverage for packet-000663 compiler ambiguity policy pairs."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    ModalLogicFamily,
)


def _mock_adaptive_ranking(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> List[Dict[str, Any]]:
    predicted_share = max(0.70, abs(float(family_margin)) + 0.10)
    target_share = predicted_share + float(family_margin)
    fallback_family = (
        ModalLogicFamily.ALETHIC.value
        if ModalLogicFamily.ALETHIC.value not in {predicted_family, target_family}
        else ModalLogicFamily.EPISTEMIC.value
    )
    fallback_share = max(0.0, min(predicted_share, target_share) / 2.0)
    return [
        {
            "family": predicted_family,
            "count": 0,
            "logit": 1.30,
            "share_raw": predicted_share,
            "share": predicted_share,
            "source": "logit_softmax_fallback",
        },
        {
            "family": target_family,
            "count": 0,
            "logit": 1.10,
            "share_raw": target_share,
            "share": target_share,
            "source": "logit_softmax_fallback",
        },
        {
            "family": fallback_family,
            "count": 0,
            "logit": 0.90,
            "share_raw": fallback_share,
            "share": fallback_share,
            "source": "logit_softmax_fallback",
        },
    ]


def _matching_explicit_ambiguity(
    *,
    ambiguities: List[ModalCompilationAmbiguity],
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> Optional[ModalCompilationAmbiguity]:
    for ambiguity in ambiguities:
        if not ambiguity.ambiguity_type.startswith("adaptive_"):
            continue
        if ambiguity.ambiguity_type == "adaptive_family_margin_low":
            continue
        metadata: Mapping[str, Any] = ambiguity.metadata
        if metadata.get("adaptive_predicted_family_source") != "adaptive_logits":
            continue
        if metadata.get("predicted_family") != predicted_family:
            continue
        if metadata.get("target_family") != target_family:
            continue
        margin_raw = float(metadata.get("family_margin_raw", 0.0))
        if abs(margin_raw - float(family_margin)) > 1e-12:
            continue
        return ambiguity
    return None


def test_compiler_preserves_packet_000663_explicit_ambiguity_policy_pairs() -> None:
    cases: Tuple[Tuple[str, str, str, float, float, str], ...] = (
        (
            "us-code-42-1395w-e0282eae03e99c45",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.DEONTIC.value,
            -0.2701617219,
            0.4201617219,
            "adaptive_conditional_normative_deontic_outvoted_margin_low",
        ),
        (
            "us-code-40-8106-7f3b19011fb863f2",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
            -0.068509777116,
            0.218509777116,
            "adaptive_temporal_deontic_outvoted_margin_low",
        ),
        (
            "us-code-25-1777b-a42bc17c85af6fa0",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.FRAME.value,
            -0.081139848584,
            0.231139848584,
            "adaptive_temporal_frame_outvoted_margin_low",
        ),
    )

    for (
        sample_id,
        predicted_family,
        target_family,
        expected_margin,
        expected_priority,
        expected_type,
    ) in cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        ranking = _mock_adaptive_ranking(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=expected_margin,
        )
        compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
            lambda _encoding, _ranking=ranking: _ranking
        )

        result = compiler.compile(
            "Within 30 days the Secretary shall submit the report as provided by statute.",
            document_id=f"compiler-ambiguity-packet-000663-{sample_id}",
        )

        ambiguity = _matching_explicit_ambiguity(
            ambiguities=result.ambiguities,
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=expected_margin,
        )
        assert ambiguity is not None, (
            sample_id,
            [item.to_dict() for item in result.ambiguities],
        )
        assert ambiguity.ambiguity_type == expected_type
        assert ambiguity.severity == "requires_rule"
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert (
            abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - expected_margin)
            <= 1e-12
        )
        assert (
            abs(float(ambiguity.metadata.get("priority", 0.0)) - expected_priority)
            <= 1e-12
        )
        assert (
            abs(
                float(ambiguity.metadata.get("adaptive_priority", 0.0))
                - expected_priority
            )
            <= 1e-12
        )
