"""Regression coverage for packet-000560 refined modal family cue rules."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    COMPILER_AMBIGUITY_PACKET_000560_FAMILY_PAIRS,
    COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS,
    DEFAULT_MODAL_REGISTRY,
    ModalLogicFamily,
    compiler_refined_modal_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (  # noqa: E402
    SpaCyLegalEncoder,
    ranked_modal_families,
)


_PACKET_000560_FAMILY_PAIRS = (
    ("deontic", "conditional_normative"),
    ("frame", "deontic"),
)


def test_packet_000560_pairs_are_pinned_in_packet_pair_table() -> None:
    assert (
        tuple(COMPILER_AMBIGUITY_PACKET_000560_FAMILY_PAIRS)
        == _PACKET_000560_FAMILY_PAIRS
    )


def test_packet_000560_pairs_are_supported_across_compiler_ambiguity_policies() -> None:
    refined_pairs = set(COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS)
    for predicted_family, target_family in _PACKET_000560_FAMILY_PAIRS:
        assert (predicted_family, target_family) in refined_pairs
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_compiler_ambiguity_policy_pair(
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
            >= 0.0015
        )


def test_deontic_profile_covers_program_establishment_and_guideline_duties() -> None:
    profile = DEFAULT_MODAL_REGISTRY.get_profile(ModalLogicFamily.DEONTIC)
    cue_terms = {
        cue
        for operator in profile.operators
        for cue in operator.cue_terms
    }

    assert "shall establish" in cue_terms
    assert "shall establish a program" in cue_terms
    assert "shall issue guidelines" in cue_terms


def test_program_establishment_text_ranks_deontic_over_frame_context() -> None:
    encoder = SpaCyLegalEncoder(model_name="blank")
    encoding = encoder.encode(
        (
            "The Secretary shall establish a program to facilitate and "
            "encourage the transfer of technology to small businesses and "
            "shall issue guidelines relating to the program not later than "
            "May 1, 1993."
        ),
        document_id="packet-000560-program-establishment",
    )

    ranking = ranked_modal_families(encoding)

    assert ranking[0]["family"] == ModalLogicFamily.DEONTIC.value
    assert any(
        cue.family == ModalLogicFamily.DEONTIC.value
        and cue.cue.lower() == "shall establish"
        for cue in encoding.cues
    )
    assert any(
        cue.family == ModalLogicFamily.DEONTIC.value
        and cue.cue.lower() == "shall issue guidelines"
        for cue in encoding.cues
    )
