"""Regression coverage for packet-001265 compiler ambiguity policy pairs."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_AMBIGUITY_PACKET_001265_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    compiler_required_adaptive_ambiguity_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    signal_free_adaptive_ambiguity_targets,
    supports_signal_free_adaptive_ambiguity_pair,
)


def _adaptive_ranking_for_margin(
    *,
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
            "logit": 1.1,
            "share_raw": target_share,
            "share": target_share,
            "source": "logit_softmax_fallback",
        },
    ]


def _matching_explicit_ambiguity(
    ambiguities: Sequence[ModalCompilationAmbiguity],
    *,
    predicted_family: str,
    target_family: str,
    expected_margin: float,
) -> ModalCompilationAmbiguity | None:
    for ambiguity in ambiguities:
        if ambiguity.ambiguity_type == "adaptive_family_margin_low":
            continue
        if not ambiguity.ambiguity_type.startswith("adaptive_"):
            continue
        metadata = ambiguity.metadata
        if metadata.get("adaptive_predicted_family_source") != "adaptive_logits":
            continue
        if metadata.get("predicted_family") != predicted_family:
            continue
        if metadata.get("target_family") != target_family:
            continue
        if abs(float(metadata.get("family_margin_raw", 0.0)) - expected_margin) > 1e-12:
            continue
        return ambiguity
    return None


def test_modal_registry_packet_001265_family_pairs_are_supported() -> None:
    assert COMPILER_AMBIGUITY_PACKET_001265_FAMILY_PAIRS == (
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.DOXASTIC.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.EPISTEMIC.value),
    )
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_001265_FAMILY_PAIRS:
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
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in signal_free_adaptive_ambiguity_targets(predicted_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_compiler_preserves_packet_001265_explicit_ambiguity_margins() -> None:
    evidence_cases = (
        {
            "sample_id": "us-code-16-407d-ffe85671d5c04484",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.156703124547,
            "expected_type": "adaptive_frame_deontic_outvoted_margin_low",
            "text": (
                "The Secretary has authority under this chapter and shall "
                "prescribe rules and regulations for the lease program."
            ),
        },
        {
            "sample_id": "us-code-47-1430.-4922d100440a3155",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.EPISTEMIC.value,
            "family_margin": -0.567405864004,
            "expected_type": "adaptive_frame_epistemic_outvoted_margin_low",
            "text": (
                "The annual report to Congress shall include findings, "
                "assessments, and determinations about the authority."
            ),
        },
        {
            "sample_id": "us-code-43-617u.-ccc23533fe0bd328",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.999997641809,
            "expected_type": "adaptive_frame_deontic_outvoted_margin_low",
            "text": (
                "Reserved lands in Boulder City are subject to rules and "
                "regulations the Secretary may prescribe for rental rates."
            ),
        },
        {
            "sample_id": "us-code-18-287-285c98993acf7426",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.DOXASTIC.value,
            "family_margin": -0.253701748308,
            "expected_type": "adaptive_deontic_doxastic_outvoted_margin_low",
            "text": (
                "A person knowingly and willfully makes a false statement "
                "with intent to defraud while subject to a statutory duty."
            ),
        },
    )

    for case in evidence_cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        predicted_family = str(case["predicted_family"])
        target_family = str(case["target_family"])
        family_margin = float(case["family_margin"])
        ranking = _adaptive_ranking_for_margin(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
        )
        compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
            lambda _encoding, _ranking=ranking: list(_ranking)
        )

        result = compiler.compile(
            str(case["text"]),
            document_id=f"compiler-ambiguity-packet-001265-{case['sample_id']}",
        )
        ambiguity = _matching_explicit_ambiguity(
            result.ambiguities,
            predicted_family=predicted_family,
            target_family=target_family,
            expected_margin=family_margin,
        )

        assert ambiguity is not None, (
            case["sample_id"],
            [item.to_dict() for item in result.ambiguities],
        )
        assert ambiguity.ambiguity_type == case["expected_type"]
        assert ambiguity.severity == "requires_rule"
        assert ambiguity.metadata.get("adaptive_policy_pair") == (
            f"{predicted_family}->{target_family}"
        )
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("is_compiler_required_policy_pair") is True
        assert ambiguity.metadata.get("is_priority_policy_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert abs(
            float(ambiguity.metadata.get("family_margin_raw", 0.0)) - family_margin
        ) <= 1e-12
