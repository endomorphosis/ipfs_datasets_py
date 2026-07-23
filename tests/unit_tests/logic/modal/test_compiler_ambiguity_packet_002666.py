"""Regression coverage for packet-002666 modal ambiguity policy."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple

import ipfs_datasets_py.logic.modal.compiler as modal_compiler_module
from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_REFINED_PACKET_002666_FAMILY_PAIRS,
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
    if predicted_family == target_family:
        predicted_share = (1.0 + family_margin) / 2.0
        runner_up_share = predicted_share - family_margin
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
                "family": ModalLogicFamily.TEMPORAL.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": runner_up_share,
                "share": runner_up_share,
                "source": "logit_softmax_fallback",
            },
        ]

    predicted_share = min(0.99, abs(float(family_margin)) + 0.05)
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
    family_margin: float,
) -> ModalCompilationAmbiguity | None:
    for ambiguity in ambiguities:
        metadata: Mapping[str, Any] = ambiguity.metadata
        if not ambiguity.ambiguity_type.startswith("adaptive_"):
            continue
        if ambiguity.ambiguity_type == "adaptive_family_margin_low":
            continue
        if metadata.get("adaptive_predicted_family_source") != "adaptive_logits_fallback":
            continue
        if metadata.get("predicted_family") != predicted_family:
            continue
        if metadata.get("target_family") != target_family:
            continue
        if abs(float(metadata.get("family_margin_raw", 0.0)) - family_margin) > 1e-12:
            continue
        return ambiguity
    return None


def test_packet_002666_pairs_are_registered_across_ambiguity_policies() -> None:
    expected_pairs = (
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.EPISTEMIC.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.TEMPORAL.value),
    )

    assert COMPILER_REFINED_PACKET_002666_FAMILY_PAIRS == expected_pairs
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
            >= 0.0015
        )


def test_compiler_exposes_packet_002666_explicit_adaptive_ambiguities(
    monkeypatch,
) -> None:
    evidence_cases: Tuple[Tuple[str, str, str, float, str, str, float], ...] = (
        (
            "us-code-6-1505-a38a0f1bb37bb6b2",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
            0.145990952589,
            "adaptive_deontic_deontic_contested_margin_low",
            "review",
            0.004009047411,
        ),
        (
            "us-code-16-482n-1-d224d4c3b20604b2",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.972162205276,
            "adaptive_frame_temporal_outvoted_margin_low",
            "requires_rule",
            1.122162205276,
        ),
        (
            "us-code-6-1402-e4f4e4514225aa0f",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.EPISTEMIC.value,
            -0.437083884709,
            "adaptive_frame_epistemic_outvoted_margin_low",
            "requires_rule",
            0.587083884709,
        ),
    )

    monkeypatch.setattr(modal_compiler_module, "ranked_modal_families", lambda _: [])
    monkeypatch.setattr(modal_compiler_module, "modal_ambiguity_signals", lambda _: {})

    for (
        sample_id,
        predicted_family,
        target_family,
        family_margin,
        expected_type,
        expected_severity,
        expected_priority,
    ) in evidence_cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="regex")
        )
        ranking = _mock_adaptive_ranking(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
        )
        compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
            lambda _encoding, ranking=ranking: list(ranking)
        )

        result = compiler.compile(
            "The Secretary shall establish a program subject to this section.",
            document_id=f"compiler-ambiguity-packet-002666-{sample_id}",
        )
        ambiguity = _matching_explicit_ambiguity(
            ambiguities=result.ambiguities,
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
        assert ambiguity.metadata.get("explicit_ambiguity_type") == expected_type
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert (
            abs(float(ambiguity.metadata.get("priority", 0.0)) - expected_priority)
            <= 1e-12
        )
