"""Regression coverage for packet-000523 compiler ambiguity policy pairs."""

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
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> List[Dict[str, Any]]:
    predicted_share = max(0.7, abs(float(family_margin)) + 0.1)
    if predicted_family == target_family:
        runner_up_family = (
            ModalLogicFamily.TEMPORAL.value
            if predicted_family != ModalLogicFamily.TEMPORAL.value
            else ModalLogicFamily.DEONTIC.value
        )
        runner_up_share = max(0.0, predicted_share - float(family_margin))
        third_share = max(0.0, min(predicted_share, runner_up_share) / 2.0)
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
                "share_raw": third_share,
                "share": third_share,
                "source": "logit_softmax_fallback",
            },
        ]

    target_share = predicted_share + float(family_margin)
    third_share = max(0.0, min(target_share, predicted_share) / 2.0)
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
            "share_raw": third_share,
            "share": third_share,
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


def test_compiler_preserves_packet_000523_explicit_ambiguity_policy_pairs() -> None:
    evidence_cases: Tuple[Tuple[str, str, str, float, float, str], ...] = (
        (
            "us-code-49-5332.-a6b1e95959cb7569",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.FRAME.value,
            -0.488278483317,
            0.638278483317,
            "requires_rule",
        ),
        (
            "us-code-49-31112.-ec9f0de1c0a46548",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.FRAME.value,
            -0.63203460184,
            0.78203460184,
            "requires_rule",
        ),
        (
            "us-code-20-7934-c5662c45e90210c4",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.DEONTIC.value,
            -0.67583491362,
            0.82583491362,
            "requires_rule",
        ),
        (
            "us-code-22-7702-42361c5e6f2d1c76",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            0.119235471514,
            0.030764528486,
            "review",
        ),
        (
            "us-code-33-2304-9bffad5853fcc776",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.327803207468,
            0.477803207468,
            "requires_rule",
        ),
        (
            "us-code-42-280c.-d7c48ac098d6bee2",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.DEONTIC.value,
            -0.353960369862,
            0.503960369862,
            "requires_rule",
        ),
        (
            "us-code-42-16796.-d469fb7ecc34b3c5",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
            0.13151054905,
            0.01848945095,
            "review",
        ),
    )

    for (
        sample_id,
        predicted_family,
        target_family,
        expected_margin,
        expected_priority,
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
            "Within 30 days the Secretary shall submit the report as provided by statute.",
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
        assert ambiguity.severity == expected_severity
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
            abs(float(ambiguity.metadata.get("adaptive_priority", 0.0)) - expected_priority)
            <= 1e-12
        )


def test_compiler_uses_duplicate_self_family_entries_to_compute_self_pair_margin() -> None:
    compiler = DeterministicModalCompiler(config=ModalCompilerConfig(parser_backend="spacy"))
    ranking = [
        {
            "family": ModalLogicFamily.DEONTIC.value,
            "count": 0,
            "logit": 1.2,
            "share_raw": 0.7,
            "share": 0.7,
            "source": "logit_softmax_fallback",
        },
        {
            "family": ModalLogicFamily.DEONTIC.value,
            "count": 0,
            "logit": 1.0,
            "share_raw": 0.83151054905,
            "share": 0.83151054905,
            "source": "logit_softmax_fallback",
        },
        {
            "family": ModalLogicFamily.FRAME.value,
            "count": 0,
            "logit": 0.8,
            "share_raw": 0.2,
            "share": 0.2,
            "source": "logit_softmax_fallback",
        },
    ]
    compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
        lambda _encoding, _ranking=ranking: _ranking
    )

    result = compiler.compile(
        "The agency shall issue notice under this section.",
        document_id="duplicate-self-margin-doc",
    )

    explicit = next(
        ambiguity
        for ambiguity in result.ambiguities
        if ambiguity.ambiguity_type
        == "adaptive_deontic_deontic_contested_margin_low"
        and ambiguity.metadata.get("predicted_family") == ModalLogicFamily.DEONTIC.value
        and ambiguity.metadata.get("target_family") == ModalLogicFamily.DEONTIC.value
    )
    assert abs(float(explicit.metadata.get("family_margin_raw", 0.0)) - 0.13151054905) <= 1e-12
    assert explicit.severity == "review"
