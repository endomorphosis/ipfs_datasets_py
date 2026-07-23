"""Regression coverage for packet-000225 refined modal-family cue rules."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_REFINED_PACKET_000225_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    compiler_refined_modal_family_cue_margin_buffer,
    compiler_weak_typed_self_family_cue_margin_buffer,
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


def test_modal_registry_packet_000225_family_pairs_are_supported() -> None:
    assert COMPILER_REFINED_PACKET_000225_FAMILY_PAIRS == (
        (
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ),
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.CONDITIONAL_NORMATIVE.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.TEMPORAL.value),
    )
    for predicted_family, target_family in COMPILER_REFINED_PACKET_000225_FAMILY_PAIRS:
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
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            > 0.0
        )

    assert (
        compiler_weak_typed_self_family_cue_margin_buffer(
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        )
        > 0.0
    )


def test_compiler_emits_packet_000225_explicit_family_ambiguities() -> None:
    cases = (
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.63482775917,
            None,
            "adaptive_frame_temporal_outvoted_margin_low",
            "requires_rule",
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
            -0.437184894038,
            None,
            "adaptive_frame_deontic_outvoted_margin_low",
            "requires_rule",
        ),
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.109407384733,
            None,
            "adaptive_deontic_conditional_normative_outvoted_margin_low",
            "requires_rule",
        ),
        (
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            0.130942336453,
            ModalLogicFamily.DEONTIC.value,
            "adaptive_conditional_normative_conditional_normative_contested_margin_low",
            "review",
        ),
    )
    text = (
        "Except as provided in this section, the Secretary shall determine "
        "whether the requirement applies after notice and hearing."
    )

    for (
        predicted_family,
        target_family,
        family_margin,
        runner_up_family,
        expected_type,
        severity,
    ) in cases:
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
            document_id=f"compiler-ambiguity-packet-000225-{target_family}",
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
