"""Regression coverage for packet-002055 modal ambiguity policy."""

from __future__ import annotations

from ipfs_datasets_py.logic.modal.compiler import DeterministicModalCompiler
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_AMBIGUITY_PACKET_002055_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


def test_packet_002055_family_pairs_are_explicit_policy_pairs() -> None:
    expected_pairs = (
        (
            ModalLogicFamily.DOXASTIC.value,
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

    assert set(expected_pairs) <= set(COMPILER_AMBIGUITY_PACKET_002055_FAMILY_PAIRS)
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


def test_packet_002055_doxastic_conditions_feed_conditional_target_signal() -> None:
    compiler = DeterministicModalCompiler()

    target_signals = compiler._adaptive_target_signal_by_family(
        ModalLogicFamily.DOXASTIC.value,
        signals={"has_condition_or_exception_scope": True},
        has_frame_scope=False,
    )

    assert target_signals[ModalLogicFamily.CONDITIONAL_NORMATIVE.value] is True
