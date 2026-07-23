"""Regression coverage for packet-000132 frame-family ambiguity policy pairs."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_AMBIGUITY_PACKET_000132_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    compiler_required_adaptive_ambiguity_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


def _adaptive_ranking_for_outvote(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> List[Dict[str, Any]]:
    target_share = max(0.001, min(0.2, (1.0 + family_margin) / 2.0))
    predicted_share = target_share - family_margin
    return [
        {
            "family": predicted_family,
            "count": 0,
            "logit": 1.4,
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


def test_modal_registry_packet_000132_frame_pairs_are_explicit_policy_pairs() -> None:
    assert COMPILER_AMBIGUITY_PACKET_000132_FAMILY_PAIRS == (
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.TEMPORAL.value),
    )
    for (
        predicted_family,
        target_family,
    ) in COMPILER_AMBIGUITY_PACKET_000132_FAMILY_PAIRS:
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
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_compiler_emits_packet_000132_explicit_frame_ambiguities() -> None:
    cases = (
        (
            "us-code-42-300a-e57ccd658257dc26",
            ModalLogicFamily.TEMPORAL.value,
            -0.996745588404,
        ),
        (
            "us-code-16-799-ed4b744b4bed77ee",
            ModalLogicFamily.DEONTIC.value,
            -0.471786209431,
        ),
    )
    predicted_family = ModalLogicFamily.FRAME.value
    threshold = 0.15
    for sample_id, target_family, family_margin in cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        ranking = _adaptive_ranking_for_outvote(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
        )
        compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
            lambda _encoding, _ranking=ranking: list(_ranking)
        )

        result = compiler.compile(
            (
                "This chapter applies to the power project. The Commission "
                "shall issue regulations within 30 days after enactment."
            ),
            document_id=f"compiler-ambiguity-packet-000132-{sample_id}",
        )
        ambiguity = _matching_explicit_ambiguity(
            result.ambiguities,
            predicted_family=predicted_family,
            target_family=target_family,
            expected_margin=family_margin,
        )

        assert ambiguity is not None, (
            sample_id,
            [item.to_dict() for item in result.ambiguities],
        )
        assert (
            ambiguity.ambiguity_type
            == f"adaptive_frame_{target_family}_outvoted_margin_low"
        )
        assert ambiguity.severity == "requires_rule"
        assert ambiguity.metadata.get("adaptive_policy_pair") == (
            f"{predicted_family}->{target_family}"
        )
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("is_compiler_required_policy_pair") is True
        assert ambiguity.metadata.get("is_priority_policy_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert (
            abs(
                float(ambiguity.metadata.get("priority", 0.0))
                - (abs(family_margin) + threshold)
            )
            <= 1e-12
        )
