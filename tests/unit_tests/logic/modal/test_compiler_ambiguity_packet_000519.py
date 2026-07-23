"""Regression coverage for packet-000519 refined frame-family cue rules."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_modal_parser import (
    LegalModalParser,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_REFINED_PACKET_000519_FAMILY_PAIRS,
    DEFAULT_MODAL_REGISTRY,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    compiler_refined_modal_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


def _profile_cues(family: ModalLogicFamily) -> set[str]:
    profile = DEFAULT_MODAL_REGISTRY.get_profile(family)
    return {
        cue
        for operator in profile.operators
        for cue in operator.cue_terms
    }


def test_packet_000519_refined_frame_family_pairs_are_registered() -> None:
    expected_pairs = (
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
            ModalLogicFamily.TEMPORAL.value,
        ),
    )

    assert COMPILER_REFINED_PACKET_000519_FAMILY_PAIRS == expected_pairs
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
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            >= 0.08
        )


def test_packet_000519_statutory_cues_are_typed_to_target_families() -> None:
    assert {
        "for purposes of this subchapter",
        "the following definitions shall apply",
        "to the extent consistent with",
        "as a condition to",
    } <= _profile_cues(ModalLogicFamily.CONDITIONAL_NORMATIVE)
    assert {
        "shall ensure",
        "shall keep",
        "shall have the right",
        "is authorized to conduct",
    } <= _profile_cues(ModalLogicFamily.DEONTIC)
    assert {
        "on january 1",
        "beginning of each subsequent calendar year",
        "on the date before",
        "regular and periodic",
    } <= _profile_cues(ModalLogicFamily.TEMPORAL)


def test_packet_000519_parser_extracts_refined_target_family_cues() -> None:
    parser = LegalModalParser()
    text = (
        "For purposes of this subchapter, the following definitions shall apply. "
        "To the extent consistent with section 300jj-11, duties shall be "
        "transferred as of February 17, 2009. On January 1, 1987, and at the "
        "beginning of each subsequent calendar year, the Council shall ensure "
        "regular and periodic audits."
    )
    families = {cue.family for cue in parser.extract_cues(text)}

    assert ModalLogicFamily.CONDITIONAL_NORMATIVE in families
    assert ModalLogicFamily.DEONTIC in families
    assert ModalLogicFamily.TEMPORAL in families
