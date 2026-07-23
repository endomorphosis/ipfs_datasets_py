"""Regression coverage for packet-001252 refined modal-family cue rules."""

from __future__ import annotations

from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_REFINED_PACKET_001252_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    compiler_refined_modal_family_cue_margin_buffer,
    compiler_required_adaptive_ambiguity_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_signal_free_adaptive_ambiguity_pair,
    priority_signal_free_adaptive_ambiguity_targets,
    signal_free_adaptive_ambiguity_targets,
    supports_signal_free_adaptive_ambiguity_pair,
)


def test_packet_001252_refined_family_pairs_are_registered() -> None:
    expected_pairs = (
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.TEMPORAL.value),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.FRAME.value),
    )

    assert COMPILER_REFINED_PACKET_001252_FAMILY_PAIRS == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in priority_signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
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

    assert compiler_refined_modal_family_cue_margin_buffer(
        "deontic",
        "temporal",
    ) >= 0.40
    assert compiler_refined_modal_family_cue_margin_buffer(
        "frame",
        "conditional_normative",
    ) >= 1.17
    assert compiler_refined_modal_family_cue_margin_buffer("frame", "deontic") >= 1.12
    assert compiler_refined_modal_family_cue_margin_buffer("temporal", "frame") >= 0.61


def test_packet_001252_compiler_emits_explicit_refined_ambiguities() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    scenarios = (
        (
            "us-code-29-179-954141dce6060d9b",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.040472637134,
        ),
        (
            "us-code-40-3143-c585aa4fb8b065cc",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.544717868757,
        ),
        (
            "us-code-42-4101d.-bb2fe2653c6a7c3e",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
            -0.88930792264,
        ),
        (
            "us-code-16-408j-32fdacd850bbb58d",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.FRAME.value,
            -0.005654672066,
        ),
    )

    for sample_id, predicted_family, target_family, family_margin in scenarios:
        predicted_share = 0.1
        target_share = predicted_share - family_margin
        ranking = [
            {
                "family": predicted_family,
                "count": 0,
                "share_raw": predicted_share,
                "share": predicted_share,
            },
            {
                "family": target_family,
                "count": 0,
                "share_raw": target_share,
                "share": target_share,
            },
        ]
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        ambiguities = compiler._compiled_primary_family_adaptive_pair_ambiguities(
            compiled_primary_family=predicted_family,
            competing_family=target_family,
            ranking=ranking,
            family_shares=family_shares,
            threshold=compiler.config.modal_adaptive_family_margin,
            signals={},
            has_frame_scope=False,
            has_frame_bm25_support=False,
            compiled_modal_families=[predicted_family],
            predicted_family_source=f"packet_001252:{sample_id}",
        )
        explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        )

        assert base_ambiguity.severity == "requires_rule"
        assert base_ambiguity.candidate_ids == [predicted_family, target_family]
        assert base_ambiguity.metadata["adaptive_policy_pair"] == (
            f"{predicted_family}->{target_family}"
        )
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["is_compiler_required_policy_pair"] is True
        assert base_ambiguity.metadata["is_priority_policy_pair"] is True
        assert base_ambiguity.metadata["signal_free_pair_policy_applied"] is False
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == explicit_type
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert any(
            ambiguity.ambiguity_type == explicit_type
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["is_explicit_adaptive_ambiguity"] is True
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )
