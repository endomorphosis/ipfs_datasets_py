from __future__ import annotations

from ipfs_datasets_py.logic.modal import compiler as compiler_module
from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_AMBIGUITY_PACKET_002323_FAMILY_PAIRS,
    compiler_ambiguity_policy_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


def _compiler_without_pipeline() -> DeterministicModalCompiler:
    compiler = object.__new__(DeterministicModalCompiler)
    compiler.config = ModalCompilerConfig()
    return compiler


def test_packet_002323_pairs_are_explicit_signal_free_policy_pairs() -> None:
    expected_pairs = (
        ("deontic", "conditional_normative"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "temporal"),
    )

    assert COMPILER_AMBIGUITY_PACKET_002323_FAMILY_PAIRS == expected_pairs
    for predicted_family, target_family in expected_pairs:
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
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_packet_002323_deontic_to_conditional_emits_without_lexical_signal(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        compiler_module,
        "modal_ambiguity_signals",
        lambda _encoding: {"has_condition_or_exception_scope": False},
    )
    compiler = _compiler_without_pipeline()

    ambiguities = compiler._conditional_scope_target_family_ambiguities(
        object(),
        ranking=[{"family": "deontic", "share_raw": 1.0, "share": 1.0}],
        family_shares={},
    )

    assert len(ambiguities) == 1
    ambiguity = ambiguities[0]
    assert ambiguity.ambiguity_type == "conditional_scope_family_outvoted"
    assert ambiguity.metadata.get("compiler_ambiguity_policy_pair") == (
        "deontic->conditional_normative"
    )
    assert ambiguity.metadata.get("signal_free_pair_policy_applied") is True
    assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"

