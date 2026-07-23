from __future__ import annotations

from ipfs_datasets_py.logic.modal import compiler as compiler_module
from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
    ModalIROperator,
    ModalIRPredicate,
    ModalIRProvenance,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_AMBIGUITY_PACKET_001357_FAMILY_PAIRS,
    compiler_ambiguity_policy_targets,
    compiler_refined_modal_family_cue_margin_buffer,
    compiler_weak_typed_self_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


def _compiler_without_pipeline() -> DeterministicModalCompiler:
    compiler = object.__new__(DeterministicModalCompiler)
    compiler.config = ModalCompilerConfig()
    return compiler


def _deontic_modal_ir() -> ModalIRDocument:
    return ModalIRDocument(
        document_id="packet-001357",
        source="us_code",
        normalized_text="The officer shall file notice.",
        formulas=[
            ModalIRFormula(
                formula_id="packet-001357:f0001",
                operator=ModalIROperator(
                    family="deontic",
                    system="deterministic",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(name="FileNotice", arguments=["officer"]),
                provenance=ModalIRProvenance(
                    source_id="packet-001357",
                    start_char=0,
                    end_char=30,
                    citation="packet-001357",
                ),
            )
        ],
    )


def test_packet_001357_pairs_are_explicit_signal_free_policy_pairs() -> None:
    expected_pairs = (
        ("deontic", "deontic"),
        ("frame", "deontic"),
    )

    assert COMPILER_AMBIGUITY_PACKET_001357_FAMILY_PAIRS == expected_pairs
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


def test_packet_001357_frame_to_deontic_emits_without_lexical_signal(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        compiler_module,
        "modal_ambiguity_signals",
        lambda _encoding: {"has_deontic_scope": False, "has_deontic_cue": False},
    )
    compiler = _compiler_without_pipeline()

    ambiguities = compiler._deontic_scope_target_family_ambiguities(
        object(),
        ranking=[{"family": "frame", "share_raw": 1.0, "share": 1.0}],
        family_shares={},
    )

    assert len(ambiguities) == 1
    ambiguity = ambiguities[0]
    assert ambiguity.ambiguity_type == "deontic_scope_family_outvoted"
    assert ambiguity.metadata.get("compiler_ambiguity_policy_pair") == (
        "frame->deontic"
    )
    assert ambiguity.metadata.get("signal_free_pair_policy_applied") is True
    assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"


def test_packet_001357_deontic_self_pair_emits_on_small_adaptive_margin(
    monkeypatch,
) -> None:
    monkeypatch.setattr(compiler_module, "modal_ambiguity_signals", lambda _encoding: {})
    compiler = _compiler_without_pipeline()

    ambiguities = compiler._adaptive_family_margin_ambiguities(
        object(),
        modal_ir=_deontic_modal_ir(),
        ranking=[
            {"family": "deontic", "share_raw": 0.49, "share": 0.49},
            {"family": "frame", "share_raw": 0.454, "share": 0.454},
        ],
        family_shares={"deontic": 0.49, "frame": 0.454},
    )

    explicit = [
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type
        == "adaptive_deontic_deontic_contested_margin_low"
    ]
    assert explicit
    ambiguity = explicit[0]
    assert ambiguity.metadata.get("effective_ambiguity_policy_bundle") == (
        "compiler_ambiguity"
    )
    assert ambiguity.metadata.get("adaptive_policy_pair") == "deontic->deontic"
    assert ambiguity.metadata.get("predicted_margin_to_runner_up") == 0.036
    assert compiler_refined_modal_family_cue_margin_buffer("deontic", "deontic") > 0
    assert compiler_weak_typed_self_family_cue_margin_buffer("deontic", "deontic") > 0
