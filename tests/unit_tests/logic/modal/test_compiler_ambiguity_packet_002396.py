"""Regression coverage for packet-002396 compiler ambiguity policy pairs."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple

import ipfs_datasets_py.logic.modal.compiler as modal_compiler
from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_AMBIGUITY_PACKET_002396_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


_PACKET_002396_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)


def _mock_adaptive_ranking(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> List[Dict[str, Any]]:
    predicted_share = 0.5
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
        if ambiguity.ambiguity_type == "adaptive_family_margin_low":
            continue
        metadata: Mapping[str, Any] = ambiguity.metadata
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


def test_packet_002396_pairs_are_registered_across_ambiguity_policies() -> None:
    assert COMPILER_AMBIGUITY_PACKET_002396_FAMILY_PAIRS == _PACKET_002396_FAMILY_PAIRS
    for predicted_family, target_family in _PACKET_002396_FAMILY_PAIRS:
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


def test_compiler_exposes_packet_002396_explicit_adaptive_ambiguities(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        modal_compiler,
        "modal_ambiguity_signals",
        lambda _encoding: {},
    )
    evidence_cases: Tuple[Tuple[str, str, float, str], ...] = (
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.252341126968,
            "adaptive_frame_conditional_normative_outvoted_margin_low",
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
            -0.380872542557,
            "adaptive_frame_deontic_outvoted_margin_low",
        ),
        (
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.FRAME.value,
            -0.163811618837,
            "adaptive_temporal_frame_outvoted_margin_low",
        ),
    )
    modal_ir = ModalIRDocument(
        document_id="compiler-ambiguity-packet-002396",
        source="unit_test",
        normalized_text="",
    )
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    for predicted_family, target_family, family_margin, expected_type in evidence_cases:
        ranking = _mock_adaptive_ranking(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
        )
        ambiguities = compiler._adaptive_family_margin_ambiguities(
            object(),  # type: ignore[arg-type]
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares={
                str(candidate["family"]): compiler._ranking_share(candidate)
                for candidate in ranking
            },
            predicted_family_source="adaptive_logits",
        )
        ambiguity = _matching_explicit_ambiguity(
            ambiguities=ambiguities,
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
        )

        assert ambiguity is not None, [item.to_dict() for item in ambiguities]
        assert ambiguity.ambiguity_type == expected_type
        assert ambiguity.severity == "requires_rule"
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("adaptive_margin_direction") == "outvoted"
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert ambiguity.metadata.get("explicit_ambiguity_type") == ambiguity.ambiguity_type
