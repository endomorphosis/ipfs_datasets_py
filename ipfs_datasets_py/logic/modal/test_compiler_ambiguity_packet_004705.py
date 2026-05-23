"""Regression coverage for packet-004705 compiler-registry ambiguity pairs."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    ModalLogicFamily,
)


def _mock_ranking(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> List[Dict[str, Any]]:
    if predicted_family == target_family:
        predicted_share = max(0.7, float(family_margin) + 0.25)
        runner_up_share = predicted_share - float(family_margin)
        runner_up_family = {
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value: ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value: ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.TEMPORAL.value: ModalLogicFamily.DEONTIC.value,
        }.get(predicted_family, ModalLogicFamily.ALETHIC.value)
        tertiary_share = max(0.0, min(predicted_share, runner_up_share) / 2.0)
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
                "family": runner_up_family,
                "count": 0,
                "logit": 1.0,
                "share_raw": runner_up_share,
                "share": runner_up_share,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.ALETHIC.value,
                "count": 0,
                "logit": 0.8,
                "share_raw": tertiary_share,
                "share": tertiary_share,
                "source": "logit_softmax_fallback",
            },
        ]

    predicted_share = max(0.7, abs(float(family_margin)) + 0.1)
    target_share = predicted_share + float(family_margin)
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
            "logit": 1.0,
            "share_raw": target_share,
            "share": target_share,
            "source": "logit_softmax_fallback",
        },
        {
            "family": ModalLogicFamily.ALETHIC.value,
            "count": 0,
            "logit": 0.8,
            "share_raw": max(0.0, min(target_share, predicted_share) / 2.0),
            "share": max(0.0, min(target_share, predicted_share) / 2.0),
            "source": "logit_softmax_fallback",
        },
    ]


def _matching_explicit_ambiguities(
    *,
    ambiguities: Sequence[ModalCompilationAmbiguity],
    predicted_family: str,
    target_family: str,
    expected_margin: float,
) -> List[ModalCompilationAmbiguity]:
    matches: List[ModalCompilationAmbiguity] = []
    for ambiguity in ambiguities:
        if not ambiguity.ambiguity_type.startswith("adaptive_"):
            continue
        if ambiguity.ambiguity_type == "adaptive_family_margin_low":
            continue
        metadata = ambiguity.metadata
        if metadata.get("predicted_family") != predicted_family:
            continue
        if metadata.get("target_family") != target_family:
            continue
        margin_raw = float(metadata.get("family_margin_raw", 0.0))
        if abs(margin_raw - expected_margin) > 1e-12:
            continue
        matches.append(ambiguity)
    return matches


def test_compiler_preserves_packet_004705_refined_registry_pairs() -> None:
    evidence_cases: Tuple[Tuple[str, str, str, float, str, str], ...] = (
        (
            "us-code-18-3509-f15c6d57c863b26f",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.429651825778,
            "outvoted",
            "requires_rule",
        ),
        (
            "us-code-49-11704.-32dbdeb82ec0dcda",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.42130150729,
            "outvoted",
            "requires_rule",
        ),
        (
            "us-code-25-1616f-f47e81f5699d536d",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
            0.097079518142,
            "contested",
            "review",
        ),
        (
            "us-code-26-3131-ac6b744db1d972d3",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            0.003581739814,
            "contested",
            "review",
        ),
        (
            "us-code-7-3508-cdda5e8da016da61",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.327803207468,
            "outvoted",
            "requires_rule",
        ),
        (
            "us-code-2-61k-8d8f1f15dc7f1291",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
            -0.214706242679,
            "outvoted",
            "requires_rule",
        ),
    )

    for (
        sample_id,
        predicted_family,
        target_family,
        expected_margin,
        expected_direction,
        expected_severity,
    ) in evidence_cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        ranking = _mock_ranking(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=expected_margin,
        )
        compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
            lambda _encoding, _ranking=ranking: _ranking
        )

        result = compiler.compile(
            (
                "Within 30 days the Secretary shall submit the report, "
                "if required, as provided by statute."
            ),
            document_id=sample_id,
        )
        matches = _matching_explicit_ambiguities(
            ambiguities=result.ambiguities,
            predicted_family=predicted_family,
            target_family=target_family,
            expected_margin=expected_margin,
        )
        assert matches, (sample_id, [ambiguity.to_dict() for ambiguity in result.ambiguities])
        ambiguity = matches[0]
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert ambiguity.metadata.get("adaptive_margin_direction") == expected_direction
        assert ambiguity.severity == expected_severity
        assert (
            abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - expected_margin)
            <= 1e-12
        )
