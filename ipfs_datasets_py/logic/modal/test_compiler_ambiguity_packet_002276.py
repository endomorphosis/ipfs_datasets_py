"""Regression coverage for packet-002276 compiler ambiguity policy pairs."""

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


def test_compiler_preserves_packet_002276_explicit_ambiguity_policy_pairs() -> None:
    evidence_cases: Tuple[Tuple[str, str, str, float, float], ...] = (
        (
            "us-code-36-150413-db57e08761618757",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
            -0.329729946821,
            0.479729946821,
        ),
        (
            "us-code-16-778c-5421521c1e89d29f",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
            -0.107959072818,
            0.257959072818,
        ),
        (
            "us-code-42-18655.-2d1b476395702606",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
            -0.785061730195,
            0.935061730195,
        ),
        (
            "us-code-29-466-047aa7c42624011c",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.FRAME.value,
            -0.534017928252,
            0.684017928252,
        ),
    )

    for sample_id, predicted_family, target_family, expected_margin, expected_priority in evidence_cases:
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
        assert ambiguity.severity == "requires_rule"
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
