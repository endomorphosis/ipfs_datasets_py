"""Regression coverage for packet-000407 refined modal family cue policy."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple

from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_REFINED_PACKET_000407_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    compiler_refined_modal_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


def _mock_adaptive_ranking(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> List[Dict[str, Any]]:
    predicted_share = min(0.99, abs(float(family_margin)) + 0.05)
    target_share = max(0.0, predicted_share + family_margin)
    return [
        {
            "family": predicted_family,
            "count": 0,
            "logit": 1.4,
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


def _matching_explicit_ambiguity(
    *,
    ambiguities: Sequence[ModalCompilationAmbiguity],
    target_family: str,
    family_margin: float,
) -> ModalCompilationAmbiguity | None:
    for ambiguity in ambiguities:
        if ambiguity.ambiguity_type == "adaptive_family_margin_low":
            continue
        metadata: Mapping[str, Any] = ambiguity.metadata
        if not ambiguity.ambiguity_type.startswith("adaptive_"):
            continue
        if metadata.get("predicted_family") != ModalLogicFamily.FRAME.value:
            continue
        if metadata.get("target_family") != target_family:
            continue
        if metadata.get("adaptive_predicted_family_source") != "adaptive_logits":
            continue
        if abs(float(metadata.get("family_margin_raw", 0.0)) - family_margin) > 1e-12:
            continue
        return ambiguity
    return None


def test_packet_000407_frame_outvote_pairs_are_registered() -> None:
    expected_pairs = (
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.TEMPORAL.value),
    )

    assert COMPILER_REFINED_PACKET_000407_FAMILY_PAIRS == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            > 0.0
        )


def test_packet_000407_frame_outvotes_emit_explicit_adaptive_ambiguities() -> None:
    evidence_cases: Tuple[Tuple[str, str, float], ...] = (
        (
            "us-code-11-781-567abfcaee308b66",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.985462663153,
        ),
        (
            "us-code-42-300jj-f338d43f4efd49a3",
            ModalLogicFamily.DEONTIC.value,
            -0.647822248368,
        ),
        (
            "us-code-7-4207-7841fcb215fbf21c",
            ModalLogicFamily.TEMPORAL.value,
            -0.322088888639,
        ),
    )

    threshold = 0.15
    for sample_id, target_family, family_margin in evidence_cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        ranking = _mock_adaptive_ranking(
            predicted_family=ModalLogicFamily.FRAME.value,
            target_family=target_family,
            family_margin=family_margin,
        )
        compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
            lambda _encoding, _ranking=ranking: _ranking
        )

        result = compiler.compile(
            "The section states authority under this chapter subject to this title.",
            document_id=f"compiler-ambiguity-packet-000407-{sample_id}",
        )
        ambiguity = _matching_explicit_ambiguity(
            ambiguities=result.ambiguities,
            target_family=target_family,
            family_margin=family_margin,
        )

        assert ambiguity is not None, (
            sample_id,
            [item.to_dict() for item in result.ambiguities],
        )
        assert ambiguity.severity == "requires_rule"
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("adaptive_margin_direction") == "outvoted"
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert ambiguity.metadata.get("has_target_signal_evidence") is True
        assert (
            abs(
                float(ambiguity.metadata.get("priority", 0.0))
                - (abs(family_margin) + threshold)
            )
            <= 1e-12
        )
