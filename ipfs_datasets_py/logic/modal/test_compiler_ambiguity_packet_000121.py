"""Regression coverage for packet-000121 compiler ambiguity policy pairs."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import ModalIRDocument
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (
    SpaCyLegalEncoding,
)


def _mock_ranking(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> List[Dict[str, Any]]:
    if predicted_family == target_family:
        predicted_share = (1.0 + family_margin) / 2.0
        runner_up_family = ModalLogicFamily.TEMPORAL.value
        if predicted_family == runner_up_family:
            runner_up_family = ModalLogicFamily.DEONTIC.value
        return [
            {
                "family": predicted_family,
                "count": 0,
                "share_raw": predicted_share,
                "share": predicted_share,
                "source": "packet_000121_mock",
            },
            {
                "family": runner_up_family,
                "count": 0,
                "share_raw": predicted_share - family_margin,
                "share": predicted_share - family_margin,
                "source": "packet_000121_mock",
            },
        ]

    predicted_share = 0.9
    target_share = predicted_share + family_margin
    if target_share < 0.0:
        predicted_share = min(0.99, abs(float(family_margin)) + 0.05)
        target_share = predicted_share + family_margin
    return [
        {
            "family": predicted_family,
            "count": 0,
            "share_raw": predicted_share,
            "share": predicted_share,
            "source": "packet_000121_mock",
        },
        {
            "family": target_family,
            "count": 0,
            "share_raw": target_share,
            "share": target_share,
            "source": "packet_000121_mock",
        },
    ]


def _empty_encoding(sample_id: str) -> SpaCyLegalEncoding:
    return SpaCyLegalEncoding(
        document_id=sample_id,
        text=f"Synthetic packet 000121 ambiguity evidence for {sample_id}.",
        normalized_text=f"synthetic packet 000121 ambiguity evidence for {sample_id}.",
        tokens=[],
        sentences=[],
        cues=[],
    )


def _empty_ir(sample_id: str) -> ModalIRDocument:
    return ModalIRDocument(
        document_id=sample_id,
        source="packet_000121_test",
        normalized_text=f"synthetic packet 000121 ambiguity evidence for {sample_id}.",
    )


def _matching_explicit_ambiguity(
    ambiguities: Sequence[ModalCompilationAmbiguity],
    *,
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
        if metadata.get("predicted_family") != predicted_family:
            continue
        if metadata.get("target_family") != target_family:
            continue
        if abs(float(metadata.get("family_margin_raw", 0.0)) - expected_margin) > 1e-12:
            continue
        return ambiguity
    return None


def test_compiler_surfaces_packet_000121_explicit_ambiguity_policy_pairs() -> None:
    evidence_cases: Tuple[Tuple[str, str, str, float], ...] = (
        (
            "us-code-10-2263-571407a5044f94b2",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.FRAME.value,
            -0.602279629693,
        ),
        (
            "us-code-2-5541-462165e82b6b68ce",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.067313528485,
        ),
        (
            "us-code-38-1731-7736f9e2e50472ec",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
            -0.020584353576,
        ),
        (
            "us-code-33-3803-ac8f8e7ef6c14117",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.152757189911,
        ),
        (
            "us-code-33-851a-648cc9f03e4a8120",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.FRAME.value,
            0.115152118965,
        ),
        (
            "us-code-16-758e-1-9082a10ae8699682",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
            -0.422815952469,
        ),
        (
            "us-code-22-290k-5-2914184e2690e597",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
            -0.242904446931,
        ),
        (
            "us-code-10-2515-cb1304b3980adf2a",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.070978301003,
        ),
        (
            "us-code-10-233a-8bed7fafbdc4039d",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.032555206446,
        ),
    )

    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )
    threshold = float(compiler.config.modal_adaptive_family_margin)

    for sample_id, predicted_family, target_family, family_margin in evidence_cases:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )

        ranking = _mock_ranking(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
        )
        ambiguities = compiler._adaptive_family_margin_ambiguities(
            _empty_encoding(sample_id),
            modal_ir=_empty_ir(sample_id),
            ranking=ranking,
            family_shares={
                str(candidate["family"]): float(candidate["share_raw"])
                for candidate in ranking
            },
            predicted_family_source="packet_000121_regression",
        )
        ambiguity = _matching_explicit_ambiguity(
            ambiguities,
            predicted_family=predicted_family,
            target_family=target_family,
            expected_margin=family_margin,
        )
        assert ambiguity is not None, (
            sample_id,
            [item.to_dict() for item in ambiguities],
        )
        expected_direction = "contested" if family_margin > 0.0 else "outvoted"
        expected_priority = (
            threshold - family_margin
            if family_margin > 0.0
            else abs(family_margin) + threshold
        )
        assert ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert ambiguity.metadata["is_compiler_required_policy_pair"] is True
        assert ambiguity.metadata["is_priority_policy_pair"] is True
        assert ambiguity.metadata["adaptive_margin_direction"] == expected_direction
        assert ambiguity.metadata["explicit_ambiguity_type"] == ambiguity.ambiguity_type
        assert ambiguity.metadata["is_explicit_adaptive_ambiguity"] is True
        assert (
            abs(float(ambiguity.metadata["family_margin_raw"]) - family_margin)
            <= 1e-12
        )
        assert (
            abs(float(ambiguity.metadata["adaptive_priority"]) - expected_priority)
            <= 1e-12
        )
        assert ambiguity.severity == (
            "requires_rule" if expected_direction == "outvoted" else "review"
        )
