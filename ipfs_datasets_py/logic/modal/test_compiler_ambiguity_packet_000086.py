"""Regression coverage for packet-000086 compiler ambiguity policy pairs."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_AMBIGUITY_PACKET_000086_FAMILY_PAIRS,
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
    runner_up_family: str | None = None,
) -> List[Dict[str, Any]]:
    if predicted_family == target_family:
        resolved_runner_up_family = runner_up_family or ModalLogicFamily.TEMPORAL.value
        if resolved_runner_up_family == predicted_family:
            resolved_runner_up_family = ModalLogicFamily.FRAME.value
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

    predicted_share = 0.7
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


def test_modal_registry_packet_000086_family_pairs_are_supported() -> None:
    assert COMPILER_AMBIGUITY_PACKET_000086_FAMILY_PAIRS == (
        (
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ),
        (
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.DEONTIC.value,
        ),
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.FRAME.value,
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.TEMPORAL.value,
        ),
    )
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_000086_FAMILY_PAIRS:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_compiler_preserves_packet_000086_explicit_ambiguity_margins() -> None:
    evidence_cases = (
        {
            "sample_id": "us-code-43-433a.-f13d8a3ff4f56a04",
            "predicted_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.247537462115,
            "priority": 0.397537462115,
            "severity": "requires_rule",
            "expected_type": (
                "adaptive_conditional_normative_deontic_outvoted_margin_low"
            ),
            "text": (
                "It is declared to be the policy of the Congress that preference "
                "shall be given to needy families in opening public lands."
            ),
        },
        {
            "sample_id": "us-code-42-2751.-d7af5ae7f6f1c93a",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.068775319494,
            "priority": 0.218775319494,
            "severity": "requires_rule",
            "expected_type": "adaptive_frame_temporal_outvoted_margin_low",
            "text": (
                "This section establishes the program frame after notice and "
                "sets the effective date for administration."
            ),
        },
        {
            "sample_id": "us-code-36-150903-b0591f45ce9a3faf",
            "predicted_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": 0.051221530715,
            "priority": 0.098778469285,
            "severity": "review",
            "expected_type": (
                "adaptive_conditional_normative_conditional_normative_"
                "contested_margin_low"
            ),
            "runner_up_family": ModalLogicFamily.DEONTIC.value,
            "text": (
                "If the corporation acts under this section, the following "
                "conditions and exclusions shall apply."
            ),
        },
        {
            "sample_id": "us-code-42-6244.-3e0d2b124eabe490",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": -0.329037489063,
            "priority": 0.479037489063,
            "severity": "requires_rule",
            "expected_type": "adaptive_deontic_frame_outvoted_margin_low",
            "text": (
                "The section is repealed, but prior authority and amendments "
                "shall remain listed for statutory status."
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
            str(case["text"]),
            document_id=f"compiler-ambiguity-packet-000086-{case['sample_id']}",
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
        assert ambiguity.severity == case["severity"]
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert (
            abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - family_margin)
            <= 1e-12
        )
        assert (
            abs(float(ambiguity.metadata.get("priority", 0.0)) - float(case["priority"]))
            <= 1e-12
        )
