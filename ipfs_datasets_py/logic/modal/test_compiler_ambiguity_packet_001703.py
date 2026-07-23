"""Regression coverage for packet-001703 compiler ambiguity policy pairs."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_AMBIGUITY_PACKET_001703_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    is_compiler_ambiguity_policy_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


def _adaptive_ranking_for_margin(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> List[Dict[str, Any]]:
    if predicted_family == target_family:
        runner_up_family = ModalLogicFamily.TEMPORAL.value
        if runner_up_family == predicted_family:
            runner_up_family = ModalLogicFamily.DEONTIC.value
        predicted_share = (1.0 + family_margin) / 2.0
        runner_up_share = predicted_share - family_margin
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
                "family": runner_up_family,
                "count": 0,
                "logit": 1.1,
                "share_raw": runner_up_share,
                "share": runner_up_share,
                "source": "logit_softmax_fallback",
            },
        ]

    target_share = max(0.0001, 0.7 + family_margin)
    predicted_share = target_share - family_margin
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
            "logit": 1.1,
            "share_raw": target_share,
            "share": target_share,
            "source": "logit_softmax_fallback",
        },
    ]


def _explicit_adaptive_ambiguity(
    ambiguities: Sequence[ModalCompilationAmbiguity],
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
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
        if abs(float(metadata.get("family_margin_raw", 0.0)) - family_margin) > 1e-12:
            continue
        return ambiguity
    return None


def test_modal_registry_packet_001703_family_pairs_are_supported() -> None:
    assert COMPILER_AMBIGUITY_PACKET_001703_FAMILY_PAIRS == (
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.TEMPORAL.value),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.TEMPORAL.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.FRAME.value),
    )
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_001703_FAMILY_PAIRS:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_compiler_preserves_packet_001703_explicit_ambiguity_margins() -> None:
    evidence_cases = (
        (
            "us-code-44-731.-0e92fb9cf6b137c3",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.04169404804,
            "adaptive_deontic_temporal_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-5-8959-dca4c75fe51f4e0b",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.561084815133,
            "adaptive_frame_conditional_normative_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-7-3154-e489bb9fa533fd0e",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.999811409652,
            "adaptive_frame_temporal_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-25-334-d8e5c7979b3deb36",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
            -0.961302524974,
            "adaptive_frame_deontic_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-33-875-4e6e30c8be32481e",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.FRAME.value,
            0.123286051148,
            "adaptive_frame_frame_contested_margin_low",
            "review",
        ),
    )

    for (
        sample_id,
        predicted_family,
        target_family,
        family_margin,
        expected_type,
        expected_severity,
    ) in evidence_cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        ranking = _adaptive_ranking_for_margin(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
        )
        compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
            lambda _encoding, _ranking=ranking: list(_ranking)
        )

        result = compiler.compile(
            (
                "The Secretary shall maintain the program subject to this section "
                "and after notice may prescribe terms and conditions."
            ),
            document_id=f"compiler-ambiguity-packet-001703-{sample_id}",
        )
        ambiguity = _explicit_adaptive_ambiguity(
            result.ambiguities,
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
        )

        assert ambiguity is not None, (
            sample_id,
            [item.to_dict() for item in result.ambiguities],
        )
        assert ambiguity.ambiguity_type == expected_type
        assert ambiguity.severity == expected_severity
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert (
            abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - family_margin)
            <= 1e-12
        )
