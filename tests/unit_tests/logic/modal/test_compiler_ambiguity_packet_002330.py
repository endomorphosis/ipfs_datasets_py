"""Regression coverage for packet-002330 frame-to-temporal ambiguity policy."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple

from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_AMBIGUITY_PACKET_002330_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


_PACKET_002330_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (ModalLogicFamily.FRAME.value, ModalLogicFamily.TEMPORAL.value),
)


def _mock_adaptive_ranking(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> List[Dict[str, Any]]:
    predicted_share = 0.7
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
    family_margin: float,
) -> ModalCompilationAmbiguity | None:
    for ambiguity in ambiguities:
        metadata: Mapping[str, Any] = ambiguity.metadata
        if ambiguity.ambiguity_type != "adaptive_frame_temporal_outvoted_margin_low":
            continue
        if metadata.get("adaptive_predicted_family_source") != "adaptive_logits":
            continue
        if metadata.get("predicted_family") != ModalLogicFamily.FRAME.value:
            continue
        if metadata.get("target_family") != ModalLogicFamily.TEMPORAL.value:
            continue
        if abs(float(metadata.get("family_margin_raw", 0.0)) - family_margin) > 1e-12:
            continue
        return ambiguity
    return None


def test_packet_002330_pair_is_registered_across_ambiguity_policies() -> None:
    assert COMPILER_AMBIGUITY_PACKET_002330_FAMILY_PAIRS == _PACKET_002330_FAMILY_PAIRS
    for predicted_family, target_family in _PACKET_002330_FAMILY_PAIRS:
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


def test_compiler_exposes_packet_002330_explicit_frame_temporal_ambiguities() -> None:
    evidence_cases: Tuple[Tuple[str, float], ...] = (
        ("us-code-25-1300m-5-d20902998bd3a240", -0.613669708924),
        ("us-code-42-242v.-de00ffae4beb85a1", -0.533664524261),
    )

    threshold = 0.15
    for sample_id, family_margin in evidence_cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        ranking = _mock_adaptive_ranking(
            predicted_family=ModalLogicFamily.FRAME.value,
            target_family=ModalLogicFamily.TEMPORAL.value,
            family_margin=family_margin,
        )
        compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
            lambda _encoding, _ranking=ranking: _ranking
        )

        result = compiler.compile(
            "Not later than 60 days after enactment, the Secretary shall report.",
            document_id=f"compiler-ambiguity-packet-002330-{sample_id}",
        )
        ambiguity = _matching_explicit_ambiguity(
            ambiguities=result.ambiguities,
            family_margin=family_margin,
        )

        assert ambiguity is not None, (
            sample_id,
            [item.to_dict() for item in result.ambiguities],
        )
        assert ambiguity.severity == "requires_rule"
        assert ambiguity.candidate_ids == [
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.TEMPORAL.value,
        ]
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("compiler_ambiguity_policy_pair") is None
        assert ambiguity.metadata.get("effective_compiler_ambiguity_policy_pair") == (
            "frame->temporal"
        )
        assert ambiguity.metadata.get("adaptive_margin_direction") == "outvoted"
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert ambiguity.metadata.get("explicit_ambiguity_type") == ambiguity.ambiguity_type
        assert (
            abs(float(ambiguity.metadata.get("priority", 0.0)) - (abs(family_margin) + threshold))
            <= 1e-12
        )
