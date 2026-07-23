"""Regression coverage for packet-001552 frame-family ambiguity policy pairs."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_AMBIGUITY_PACKET_001552_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
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
        resolved_runner_up_family = runner_up_family or ModalLogicFamily.TEMPORAL.value
        if resolved_runner_up_family == predicted_family:
            resolved_runner_up_family = ModalLogicFamily.DEONTIC.value
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
                "family": resolved_runner_up_family,
                "count": 0,
                "logit": 1.1,
                "share_raw": runner_up_share,
                "share": runner_up_share,
                "source": "logit_softmax_fallback",
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


def test_modal_registry_packet_001552_frame_pairs_are_supported() -> None:
    assert COMPILER_AMBIGUITY_PACKET_001552_FAMILY_PAIRS == (
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.FRAME.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.TEMPORAL.value),
    )
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_001552_FAMILY_PAIRS:
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


def test_compiler_emits_packet_001552_explicit_frame_ambiguities() -> None:
    cases = (
        {
            "sample_id": "us-code-42-242v.-de00ffae4beb85a1",
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.561671253006,
            "expected_type": "adaptive_frame_temporal_outvoted_margin_low",
            "severity": "requires_rule",
        },
        {
            "sample_id": "us-code-25-1300m-5-d20902998bd3a240",
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.437252289298,
            "expected_type": "adaptive_frame_temporal_outvoted_margin_low",
            "severity": "requires_rule",
        },
        {
            "sample_id": "us-code-50-2314.-10608b0d81711c3f",
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.640036243215,
            "expected_type": "adaptive_frame_deontic_outvoted_margin_low",
            "severity": "requires_rule",
        },
        {
            "sample_id": "us-code-33-875-4e6e30c8be32481e",
            "target_family": ModalLogicFamily.FRAME.value,
            "runner_up_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": 0.146894141292,
            "expected_type": "adaptive_frame_frame_contested_margin_low",
            "severity": "review",
        },
        {
            "sample_id": "us-code-25-334-d8e5c7979b3deb36",
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.963250725626,
            "expected_type": "adaptive_frame_deontic_outvoted_margin_low",
            "severity": "requires_rule",
        },
    )
    predicted_family = ModalLogicFamily.FRAME.value
    for case in cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        target_family = str(case["target_family"])
        family_margin = float(case["family_margin"])
        ranking = _adaptive_ranking_for_margin(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
            runner_up_family=(
                str(case["runner_up_family"])
                if case.get("runner_up_family") is not None
                else None
            ),
        )
        compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
            lambda _encoding, _ranking=ranking: list(_ranking)
        )

        result = compiler.compile(
            (
                "This chapter applies to the response program. The Secretary "
                "shall maintain reports not later than 60 days after enactment."
            ),
            document_id=f"compiler-ambiguity-packet-001552-{case['sample_id']}",
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
        assert ambiguity.severity == case["severity"]
        assert ambiguity.metadata.get("adaptive_policy_pair") == (
            f"{predicted_family}->{target_family}"
        )
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("is_compiler_required_policy_pair") is True
        assert ambiguity.metadata.get("is_priority_policy_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert (
            abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - family_margin)
            <= 1e-12
        )
