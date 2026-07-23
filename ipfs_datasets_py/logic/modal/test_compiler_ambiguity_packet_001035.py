"""Regression coverage for packet-001035 compiler ambiguity policy pairs."""

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
        predicted_share = (1.0 + family_margin) / 2.0
        runner_up_family = (
            ModalLogicFamily.TEMPORAL.value
            if predicted_family != ModalLogicFamily.TEMPORAL.value
            else ModalLogicFamily.DEONTIC.value
        )
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
                "family": runner_up_family,
                "count": 0,
                "logit": 1.2,
                "share_raw": runner_up_share,
                "share": runner_up_share,
                "source": "logit_softmax_fallback",
            },
        ]

    predicted_share = 0.9
    target_share = predicted_share + family_margin
    if target_share < 0.0:
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


def test_compiler_preserves_packet_001035_explicit_ambiguity_policy_pairs() -> None:
    evidence_cases: Tuple[Tuple[str, str, str, float], ...] = (
        (
            "us-code-42-3614a.-a7289f307e4ba874",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.641138644022,
        ),
        (
            "us-code-45-53.-2240635c0da53f61",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
            -0.750359119735,
        ),
        (
            "us-code-18-1039-ebfbfc90e48233c0",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.EPISTEMIC.value,
            -0.649356134943,
        ),
        (
            "us-code-31-1553-aa1024c9ebd50ac7",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.13504789627,
        ),
        (
            "us-code-2-1110-d6ea0d44184c1ca4",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.FRAME.value,
            -0.307646698128,
        ),
        (
            "us-code-26-2041-f1193a6120fbab7a",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.DEONTIC.value,
            -0.325925769635,
        ),
        (
            "us-code-44-305.-4825fb4cfba20bbc",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
            0.147031500434,
        ),
        (
            "us-code-18-1966-88802ff0ce21894d",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.025328530453,
        ),
        (
            "us-code-22-7430-b9611ae2e9bc4714",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
            0.120018816332,
        ),
        (
            "us-code-19-2401b-055a62a25be14950",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.090399968631,
        ),
        (
            "us-code-42-7111.-b555f05d070a4358",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.EPISTEMIC.value,
            -0.322779896452,
        ),
        (
            "us-code-43-1715.-e56278513592e5be",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.FRAME.value,
            -0.656222245954,
        ),
        (
            "us-code-14-3742-5702ee3e7094817e",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.FRAME.value,
            -0.616012203181,
        ),
        (
            "us-code-42-12211.-b1e2aeacdf5b8e16",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.032137318252,
        ),
    )

    threshold = 0.15
    for sample_id, predicted_family, target_family, expected_margin in evidence_cases:
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
            "Within 30 days the Secretary shall submit the report as provided by statute.",
            document_id=sample_id,
        )
        matches = _matching_explicit_ambiguities(
            ambiguities=result.ambiguities,
            predicted_family=predicted_family,
            target_family=target_family,
            expected_margin=expected_margin,
        )
        assert matches, (
            sample_id,
            [ambiguity.to_dict() for ambiguity in result.ambiguities],
        )
        ambiguity = matches[0]
        expected_margin_direction = (
            "contested" if expected_margin > 0.0 else "outvoted"
        )
        expected_priority = (
            threshold - expected_margin
            if expected_margin > 0.0
            else abs(expected_margin) + threshold
        )

        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("adaptive_margin_direction") == expected_margin_direction
        assert (
            ambiguity.metadata.get("explicit_ambiguity_type")
            == ambiguity.ambiguity_type
        )
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert (
            abs(
                float(ambiguity.metadata.get("family_margin_raw", 0.0))
                - expected_margin
            )
            <= 1e-12
        )
        assert (
            abs(float(ambiguity.metadata.get("priority", 0.0)) - expected_priority)
            <= 1e-12
        )
        assert (
            abs(
                float(ambiguity.metadata.get("adaptive_priority", 0.0))
                - expected_priority
            )
            <= 1e-12
        )
        if expected_margin_direction == "outvoted":
            assert ambiguity.severity == "requires_rule"
        else:
            assert ambiguity.severity == "review"
