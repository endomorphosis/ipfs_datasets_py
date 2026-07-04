"""Regression coverage for packet-002094 frame-family cue policy pairs."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_AMBIGUITY_PACKET_002094_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    compiler_refined_modal_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


def _adaptive_ranking_for_margin(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
    runner_up_family: str | None = None,
) -> List[Dict[str, Any]]:
    if predicted_family == target_family:
        resolved_runner_up_family = runner_up_family or ModalLogicFamily.DEONTIC.value
        predicted_share = (1.0 + family_margin) / 2.0
        runner_up_share = predicted_share - family_margin
        return [
            {
                "family": predicted_family,
                "count": 0,
                "logit": 1.2,
                "share_raw": predicted_share,
                "share": predicted_share,
                "source": "adaptive_logits",
            },
            {
                "family": resolved_runner_up_family,
                "count": 0,
                "logit": 1.1,
                "share_raw": runner_up_share,
                "share": runner_up_share,
                "source": "adaptive_logits",
            },
        ]

    predicted_share = max(0.7, abs(float(family_margin)) + 0.1)
    target_share = predicted_share + family_margin
    return [
        {
            "family": predicted_family,
            "count": 0,
            "logit": 1.2,
            "share_raw": predicted_share,
            "share": predicted_share,
            "source": "adaptive_logits",
        },
        {
            "family": target_family,
            "count": 0,
            "logit": 1.1,
            "share_raw": target_share,
            "share": target_share,
            "source": "adaptive_logits",
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
        if (
            abs(float(metadata.get("family_margin_raw", 0.0)) - expected_margin)
            > 1e-12
        ):
            continue
        return ambiguity
    return None


def test_modal_registry_packet_002094_frame_pairs_are_supported() -> None:
    assert COMPILER_AMBIGUITY_PACKET_002094_FAMILY_PAIRS == (
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.CONDITIONAL_NORMATIVE.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.EPISTEMIC.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.FRAME.value),
    )
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_002094_FAMILY_PAIRS:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        buffer = compiler_refined_modal_family_cue_margin_buffer(
            predicted_family,
            target_family,
        )
        if target_family in {
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.EPISTEMIC.value,
        }:
            assert buffer >= 0.02
        else:
            assert buffer > 0.0


def test_compiler_emits_packet_002094_explicit_frame_ambiguities() -> None:
    cases = (
        (
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.731000343211,
            None,
            "adaptive_frame_conditional_normative_outvoted_margin_low",
            "requires_rule",
        ),
        (
            ModalLogicFamily.DEONTIC.value,
            -0.754853387446,
            None,
            "adaptive_frame_deontic_outvoted_margin_low",
            "requires_rule",
        ),
        (
            ModalLogicFamily.EPISTEMIC.value,
            -0.992081761525,
            None,
            "adaptive_frame_epistemic_outvoted_margin_low",
            "requires_rule",
        ),
        (
            ModalLogicFamily.FRAME.value,
            0.064262763356,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "adaptive_frame_frame_contested_margin_low",
            "review",
        ),
    )
    predicted_family = ModalLogicFamily.FRAME.value
    text = (
        "Applicability and jurisdiction. Except as provided in this section, "
        "the Secretary shall have jurisdiction over notices and findings, "
        "and shall determine whether the requirements apply to each entity."
    )

    for target_family, family_margin, runner_up_family, expected_type, severity in cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        ranking = _adaptive_ranking_for_margin(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
            runner_up_family=runner_up_family,
        )
        compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
            lambda _encoding, _ranking=ranking: list(_ranking)
        )

        result = compiler.compile(
            text,
            document_id=f"compiler-ambiguity-packet-002094-{target_family}",
        )
        ambiguity = _matching_explicit_ambiguity(
            result.ambiguities,
            predicted_family=predicted_family,
            target_family=target_family,
            expected_margin=family_margin,
        )

        assert ambiguity is not None, [item.to_dict() for item in result.ambiguities]
        assert ambiguity.ambiguity_type == expected_type
        assert ambiguity.severity == severity
        assert ambiguity.metadata.get("adaptive_policy_pair") == (
            f"{predicted_family}->{target_family}"
        )
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("is_priority_policy_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
