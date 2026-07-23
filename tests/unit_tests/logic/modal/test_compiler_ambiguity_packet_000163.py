"""Regression coverage for packet-000163 compiler ambiguity policy pairs."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple

from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_AMBIGUITY_PACKET_000163_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
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
        if not ambiguity.ambiguity_type.startswith("adaptive_"):
            continue
        if ambiguity.ambiguity_type == "adaptive_family_margin_low":
            continue
        metadata: Mapping[str, Any] = ambiguity.metadata
        if metadata.get("adaptive_predicted_family_source") != "adaptive_logits":
            continue
        if metadata.get("predicted_family") != predicted_family:
            continue
        if metadata.get("target_family") != target_family:
            continue
        margin_raw = float(metadata.get("family_margin_raw", 0.0))
        if abs(margin_raw - family_margin) > 1e-12:
            continue
        return ambiguity
    return None


def test_packet_000163_pairs_are_registered_across_ambiguity_policies() -> None:
    expected_pairs = (
        (
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.DEONTIC.value,
        ),
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
        ),
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.FRAME.value,
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.EPISTEMIC.value,
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.TEMPORAL.value,
        ),
        (
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
        ),
    )

    assert COMPILER_AMBIGUITY_PACKET_000163_FAMILY_PAIRS == expected_pairs
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


def test_compiler_exposes_packet_000163_explicit_adaptive_ambiguities() -> None:
    evidence_cases: Tuple[Tuple[str, str, str, float], ...] = (
        (
            "us-code-20-9577-32c8a949b26ca467",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
            -0.595494409297,
        ),
        (
            "us-code-16-758e-1-9082a10ae8699682",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
            -0.682455435193,
        ),
        (
            "us-code-42-18815.-4abce690c25dbe96",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
            -0.348382317877,
        ),
        (
            "us-code-20-7231c-74bfbb64db1c3f13",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.612527381139,
        ),
        (
            "us-code-20-1067l-3ec9016aef729a55",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.999990329314,
        ),
        (
            "us-code-42-247b-4945fa92fa1c6173",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
            0.14732877557,
        ),
        (
            "us-code-50-514.-bdaced095d73d36a",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
            -0.150631329184,
        ),
        (
            "us-code-46-10310.-4748e5ab4483791a",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
            -0.159252540061,
        ),
        (
            "us-code-46-4106.-e1ccfe4a030a9cde",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.813995374593,
        ),
    )

    threshold = 0.15
    for sample_id, predicted_family, target_family, family_margin in evidence_cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        ranking = _mock_adaptive_ranking(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
        )
        compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
            lambda _encoding, _ranking=ranking: _ranking
        )

        result = compiler.compile(
            "The Secretary shall transfer functions subject to this section.",
            document_id=f"compiler-ambiguity-packet-000163-{sample_id}",
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

        expected_priority = (
            threshold - family_margin
            if family_margin > 0.0
            else abs(family_margin) + threshold
        )
        assert (
            ambiguity.metadata.get("effective_is_compiler_ambiguity_bundle_pair")
            is True
        )
        assert (
            ambiguity.metadata.get("effective_ambiguity_policy_bundle")
            == "compiler_ambiguity"
        )
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert ambiguity.metadata.get("explicit_ambiguity_type") == ambiguity.ambiguity_type
        assert (
            abs(float(ambiguity.metadata.get("priority", 0.0)) - expected_priority)
            <= 1e-12
        )
