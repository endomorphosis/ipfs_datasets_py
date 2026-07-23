"""Regression coverage for packet-000545 deontic/frame cue policy."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_AMBIGUITY_PACKET_000545_FAMILY_PAIRS,
    DEFAULT_MODAL_REGISTRY,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    compiler_refined_modal_family_cue_margin_buffer,
    compiler_weak_typed_self_family_cue_margin_buffer,
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
        resolved_runner_up_family = runner_up_family or ModalLogicFamily.FRAME.value
        if resolved_runner_up_family == predicted_family:
            resolved_runner_up_family = ModalLogicFamily.TEMPORAL.value
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


def test_modal_registry_packet_000545_pairs_and_buffers_are_supported() -> None:
    assert COMPILER_AMBIGUITY_PACKET_000545_FAMILY_PAIRS == (
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.FRAME.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.DEONTIC.value),
    )
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_000545_FAMILY_PAIRS:
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

    assert (
        compiler_weak_typed_self_family_cue_margin_buffer(
            ModalLogicFamily.DEONTIC,
            ModalLogicFamily.DEONTIC,
        )
        == 0.135
    )
    assert (
        compiler_refined_modal_family_cue_margin_buffer(
            ModalLogicFamily.DEONTIC,
            ModalLogicFamily.DEONTIC,
        )
        == 0.076
    )
    assert (
        compiler_refined_modal_family_cue_margin_buffer(
            ModalLogicFamily.DEONTIC,
            ModalLogicFamily.FRAME,
        )
        == 0.0015
    )
    assert (
        compiler_refined_modal_family_cue_margin_buffer(
            ModalLogicFamily.FRAME,
            ModalLogicFamily.DEONTIC,
        )
        == 0.0015
    )


def test_modal_registry_packet_000545_legal_cues_are_registered() -> None:
    deontic_terms = {
        term
        for operator in DEFAULT_MODAL_REGISTRY.get_profile(
            ModalLogicFamily.DEONTIC
        ).operators
        for term in operator.cue_terms
    }
    frame_terms = {
        term
        for operator in DEFAULT_MODAL_REGISTRY.get_profile(ModalLogicFamily.FRAME).operators
        for term in operator.cue_terms
    }

    assert {"may take", "may use"} <= deontic_terms
    assert {
        "civil actions",
        "courts in civil actions",
        "jurisdiction of",
        "jurisdiction of state courts",
        "state courts",
    } <= frame_terms


def test_compiler_emits_packet_000545_explicit_ambiguities() -> None:
    cases = (
        {
            "sample_id": "us-code-34-10512-f1eb1d96fb4b565b",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.011929012174,
            "expected_type": "adaptive_frame_deontic_outvoted_margin_low",
            "severity": "requires_rule",
        },
        {
            "sample_id": "us-code-16-477-1e795a196584fe10",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.798999262592,
            "expected_type": "adaptive_frame_deontic_outvoted_margin_low",
            "severity": "requires_rule",
        },
        {
            "sample_id": "us-code-7-2322-8a47b18df0989404",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "runner_up_family": ModalLogicFamily.FRAME.value,
            "family_margin": 0.032692359451,
            "expected_type": "adaptive_deontic_deontic_contested_margin_low",
            "severity": "review",
        },
        {
            "sample_id": "us-code-25-233-da029ae8d3664392",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": -0.712105419749,
            "expected_type": "adaptive_deontic_frame_outvoted_margin_low",
            "severity": "requires_rule",
        },
    )
    for case in cases:
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
                "The Secretary may take and may use timber. Jurisdiction of "
                "State courts in civil actions applies under this section."
            ),
            document_id=f"compiler-ambiguity-packet-000545-{case['sample_id']}",
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
