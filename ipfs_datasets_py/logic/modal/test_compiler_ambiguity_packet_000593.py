"""Regression coverage for packet-000593 compiler ambiguity policy pairs."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_AMBIGUITY_PACKET_000593_FAMILY_PAIRS,
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


def test_modal_registry_packet_000593_family_pairs_are_supported() -> None:
    assert COMPILER_AMBIGUITY_PACKET_000593_FAMILY_PAIRS == (
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ),
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.TEMPORAL.value),
    )
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_000593_FAMILY_PAIRS:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_compiler_preserves_packet_000593_explicit_ambiguity_margins() -> None:
    evidence_cases = (
        {
            "sample_id": "us-code-25-1495-7267c4106dc9cd01",
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.147421837176,
            "priority": 0.297421837176,
            "expected_type": (
                "adaptive_deontic_conditional_normative_outvoted_margin_low"
            ),
            "text": (
                "The Secretary may guarantee loans subject to the terms and "
                "conditions prescribed under this section."
            ),
        },
        {
            "sample_id": "us-code-43-397.-330e4d6b9f7b5229",
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.220594780628,
            "priority": 0.370594780628,
            "expected_type": "adaptive_deontic_temporal_outvoted_margin_low",
            "text": (
                "To enable the Secretary to complete projects begun prior to "
                "June 25, 1910, advances may be made."
            ),
        },
        {
            "sample_id": "us-code-42-2297g-148f9d508df316cf",
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.027536969942,
            "priority": 0.177536969942,
            "expected_type": "adaptive_deontic_temporal_outvoted_margin_low",
            "text": (
                "The corporation shall submit reports during each fiscal year "
                "under this section."
            ),
        },
    )

    for case in evidence_cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        predicted_family = ModalLogicFamily.DEONTIC.value
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
            document_id=f"compiler-ambiguity-packet-000593-{case['sample_id']}",
        )
        ambiguity = _explicit_adaptive_ambiguity(
            result.ambiguities,
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
        )

        assert ambiguity is not None, (
            case["sample_id"],
            [item.to_dict() for item in result.ambiguities],
        )
        assert ambiguity.ambiguity_type == case["expected_type"]
        assert ambiguity.severity == "requires_rule"
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert ambiguity.metadata.get("adaptive_margin_direction") == "outvoted"
        assert (
            abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - family_margin)
            <= 1e-12
        )
        assert (
            abs(float(ambiguity.metadata.get("priority", 0.0)) - float(case["priority"]))
            <= 1e-12
        )
