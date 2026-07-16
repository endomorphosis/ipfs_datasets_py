"""Tests for spaCy-based modal encoder / IR / decoder workflows."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.modal.decompiler import (
    decode_modal_ir_document,
    decoded_modal_phrase_slot_text_map,
)
from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_modal_parser import LegalModalParser
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
    ModalIROperator,
    ModalIRPredicate,
    ModalIRProvenance,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_AMBIGUITY_PACKET_001029_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_000224_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_000486_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_007373_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_000697_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_000935_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_001316_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_001117_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_000122_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_000205_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_004348_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_004071_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_004558_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_000124_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_000176_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_000222_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_002414_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_004762_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_005718_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_000399_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_001615_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_005786_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_001002_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_003559_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_003166_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_005666_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_003762_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_006897_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_006902_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_002296_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_000814_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_004828_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_001944_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_002837_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_000368_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_003002_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_003436_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_007144_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_000936_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_000279_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_000373_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_003976_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_001287_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_003763_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_001592_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_001621_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_001775_FAMILY_PAIRS,
    compiler_ambiguity_policy_targets,
    ModalLogicFamily,
    compiler_refined_modal_family_cue_margin_buffer,
    compiler_weak_typed_self_family_cue_margin_buffer,
    is_compiler_required_adaptive_ambiguity_pair,
    compiler_required_adaptive_ambiguity_targets,
    is_compiler_ambiguity_policy_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_signal_free_adaptive_ambiguity_pair,
    priority_signal_free_adaptive_ambiguity_targets,
    signal_free_adaptive_ambiguity_targets,
    supports_signal_free_adaptive_ambiguity_pair,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_todo_daemon import ModalTodoSupervisor
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (
    _apply_competing_scope_backfill,
    _apply_directional_modal_family_pair_backfill,
    _debias_frame_bonus_for_generic_cues,
    _apply_dynamic_competing_scope_soft_cap,
    _apply_frame_competing_scope_soft_cap,
    _apply_refined_modal_family_cue_pair_balance,
    _apply_temporal_competing_scope_soft_cap,
    _weighted_modal_family_counts,
    _frame_logit_bonus,
    _scope_signal_family_logit_boosts,
    SpaCyLegalEncoder,
    SpaCyLegalEncoding,
    SpaCyModalCueFeature,
    SpaCyModalCodec,
    SpaCyModalDecoder,
    SpaCyModalIRCompiler,
    modal_ambiguity_signals,
    ranked_modal_families,
)

pytest.importorskip("spacy")


def test_packet_003763_registry_exposes_compiler_ambiguity_policy() -> None:
    expected_pairs = {
        ("deontic", "deontic"),
        ("frame", "temporal"),
        ("temporal", "deontic"),
    }

    assert set(COMPILER_AMBIGUITY_PACKET_003763_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_003763_FAMILY_PAIRS:
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_packet_001592_registry_exposes_explicit_ambiguity_policy() -> None:
    expected_pairs = {
        ("deontic", "temporal"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "frame"),
    }

    assert set(COMPILER_AMBIGUITY_PACKET_001592_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_001592_FAMILY_PAIRS:
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


def test_modal_compiler_surfaces_packet_001775_ambiguity_policy() -> None:
    expected_pairs = {
        ("deontic", "conditional_normative"),
        ("frame", "deontic"),
    }
    assert set(COMPILER_AMBIGUITY_PACKET_001775_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_001775_FAMILY_PAIRS:
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

    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            modal_adaptive_family_margin=0.15,
        )
    )
    scenarios = (
        ("us-code-42-16461.-46987980df49dcae", "frame", "deontic", -0.225158633771),
        (
            "us-code-18-3-b0b510916e84020a",
            "deontic",
            "conditional_normative",
            -0.048256867213,
        ),
        ("us-code-46-58102.-3d6641b7c6e1036c", "frame", "deontic", -0.999967112319),
    )
    family_operator = {
        "deontic": ("D", "O", "obligation"),
        "frame": ("FRAME_BM25", "Frame", "frame"),
    }
    for sample_id, predicted_family, target_family, family_margin in scenarios:
        predicted_system, predicted_symbol, predicted_label = family_operator[
            predicted_family
        ]
        predicted_share = min(0.95, abs(family_margin) + 0.02)
        target_share = predicted_share + family_margin
        text = f"Packet 001775 {predicted_family} to {target_family} ambiguity."
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-001775-{sample_id}",
            text=text,
            normalized_text=text.lower(),
            tokens=[],
            sentences=[],
            cues=[],
            citation="packet-001775",
            source="unit_test",
        )
        modal_ir = ModalIRDocument(
            document_id=encoding.document_id,
            source="unit_test",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"packet-001775-{sample_id}-f0",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=predicted_system,
                        symbol=predicted_symbol,
                        label=predicted_label,
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role=predicted_label,
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="packet-001775",
                    ),
                )
            ],
        )
        ranking = [
            {
                "family": predicted_family,
                "count": 0,
                "share_raw": predicted_share,
                "share": round(predicted_share, 6),
            },
            {
                "family": target_family,
                "count": 0,
                "share_raw": target_share,
                "share": round(target_share, 6),
            },
        ]
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="packet_001775_test",
        )
        policy_pair = f"{predicted_family}->{target_family}"
        explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert base_ambiguity.candidate_ids == [predicted_family, target_family]
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["is_compiler_required_policy_pair"] is True
        assert base_ambiguity.metadata["is_priority_policy_pair"] is True
        assert base_ambiguity.metadata["adaptive_margin_direction"] == "outvoted"
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == explicit_type
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert base_ambiguity.severity == "requires_rule"
        assert any(
            ambiguity.ambiguity_type == explicit_type
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_packet_001621_registry_exposes_compiler_ambiguity_policy() -> None:
    expected_pairs = {
        ("deontic", "dynamic"),
        ("deontic", "deontic"),
        ("frame", "deontic"),
        ("frame", "temporal"),
        ("temporal", "frame"),
    }

    assert set(COMPILER_AMBIGUITY_PACKET_001621_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_001621_FAMILY_PAIRS:
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


def test_packet_002837_registry_refines_modal_family_cue_policy() -> None:
    expected_pairs = {
        ("deontic", "temporal"),
        ("deontic", "deontic"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "temporal"),
    }

    assert set(COMPILER_REFINED_PACKET_002837_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in COMPILER_REFINED_PACKET_002837_FAMILY_PAIRS:
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
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            >= 0.12
        )


def test_packet_000368_registry_refines_frame_family_cue_policy() -> None:
    expected_pairs = {
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "temporal"),
    }

    assert set(COMPILER_REFINED_PACKET_000368_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in COMPILER_REFINED_PACKET_000368_FAMILY_PAIRS:
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
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            >= 0.12
        )


def test_packet_001287_registry_refines_frame_to_typed_family_cue_policy() -> None:
    expected_pairs = {
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "temporal"),
    }

    assert set(COMPILER_REFINED_PACKET_001287_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in COMPILER_REFINED_PACKET_001287_FAMILY_PAIRS:
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

    assert (
        compiler_refined_modal_family_cue_margin_buffer(
            "frame",
            "conditional_normative",
        )
        >= 1.0
    )


def test_modal_compiler_surfaces_packet_001287_frame_family_outvotes(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    scenarios = (
        (
            "us-code-26-7424-3e7375b4e701621e",
            "conditional_normative",
            -0.999989204393,
        ),
        ("us-code-14-2531-98785d94b487049a", "temporal", -0.346305973707),
        ("us-code-30-957-b93b8d521578db6d", "deontic", -0.265080048331),
    )
    family_operator = {
        "conditional_normative": ("D", "CN", "conditional_normative"),
        "deontic": ("D", "O", "obligation"),
        "frame": ("FRAME_BM25", "Frame", "frame"),
        "temporal": ("LTL", "G", "temporal"),
    }

    for index, (sample_id, target_family, family_margin) in enumerate(
        scenarios,
        start=1,
    ):
        predicted_family = "frame"
        predicted_system, predicted_symbol, predicted_label = family_operator[
            predicted_family
        ]
        predicted_share = 1.0
        target_share = predicted_share + family_margin
        ranking = [
            {
                "family": predicted_family,
                "count": 0,
                "share_raw": predicted_share,
                "share": round(predicted_share, 6),
            },
            {
                "family": target_family,
                "count": 0,
                "share_raw": target_share,
                "share": round(target_share, 6),
            },
        ]
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-001287-adaptive-evidence-{index}",
            text=f"Synthetic packet 001287 frame->{target_family} evidence.",
            normalized_text=(
                f"Synthetic packet 001287 frame->{target_family} evidence."
            ),
            tokens=[],
            sentences=[],
            cues=[],
        )
        modal_ir = ModalIRDocument(
            document_id=encoding.document_id,
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-packet-001287-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=predicted_system,
                        symbol=predicted_symbol,
                        label=predicted_label,
                    ),
                    predicate=ModalIRPredicate(
                        name="frame_predicate",
                        arguments=["actor:agency"],
                        role=predicted_label,
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="packet-001287",
                    ),
                ),
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        policy_pair = f"{predicted_family}->{target_family}"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert base_ambiguity.severity == "requires_rule"
        assert base_ambiguity.metadata["adaptive_margin_direction"] == "outvoted"
        assert base_ambiguity.metadata["is_compiler_required_policy_pair"] is True
        assert base_ambiguity.metadata["is_priority_policy_pair"] is True
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            float(base_ambiguity.metadata["adaptive_effective_family_margin_threshold"])
            > abs(family_margin)
        )
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_packet_003002_registry_refines_modal_family_cue_policy() -> None:
    expected_pairs = {
        ("deontic", "conditional_normative"),
        ("frame", "conditional_normative"),
        ("frame", "epistemic"),
    }

    assert set(COMPILER_REFINED_PACKET_003002_FAMILY_PAIRS) == expected_pairs
    margin_floors = {
        ("deontic", "conditional_normative"): 0.12,
        ("frame", "conditional_normative"): 0.14,
        ("frame", "epistemic"): 0.34,
    }
    for predicted_family, target_family in COMPILER_REFINED_PACKET_003002_FAMILY_PAIRS:
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
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            >= margin_floors[(predicted_family, target_family)]
        )


def test_packet_007144_registry_refines_modal_family_cue_policy() -> None:
    expected_pairs = {
        ("deontic", "frame"),
        ("deontic", "temporal"),
        ("frame", "deontic"),
        ("frame", "temporal"),
    }

    assert set(COMPILER_REFINED_PACKET_007144_FAMILY_PAIRS) == expected_pairs
    margin_floors = {
        ("deontic", "frame"): 0.22,
        ("deontic", "temporal"): 0.36,
        ("frame", "deontic"): 0.54,
        ("frame", "temporal"): 0.68,
    }
    for predicted_family, target_family in COMPILER_REFINED_PACKET_007144_FAMILY_PAIRS:
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
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            >= margin_floors[(predicted_family, target_family)]
        )


def test_packet_000936_registry_refines_modal_family_cue_policy() -> None:
    expected_pairs = {
        ("deontic", "conditional_normative"),
        ("frame", "deontic"),
    }

    assert set(COMPILER_REFINED_PACKET_000936_FAMILY_PAIRS) == expected_pairs
    margin_floors = {
        ("deontic", "conditional_normative"): 0.5,
        ("frame", "deontic"): 1.02,
    }
    for predicted_family, target_family in COMPILER_REFINED_PACKET_000936_FAMILY_PAIRS:
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
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            >= margin_floors[(predicted_family, target_family)]
        )


def test_packet_000279_registry_refines_modal_family_cue_policy() -> None:
    expected_pairs = {
        ("deontic", "conditional_normative"),
        ("deontic", "frame"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
    }

    assert set(COMPILER_REFINED_PACKET_000279_FAMILY_PAIRS) == expected_pairs
    margin_floors = {
        ("deontic", "conditional_normative"): 0.45,
        ("deontic", "frame"): 0.38,
        ("frame", "conditional_normative"): 0.82,
        ("frame", "deontic"): 0.54,
    }
    for predicted_family, target_family in COMPILER_REFINED_PACKET_000279_FAMILY_PAIRS:
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
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            >= margin_floors[(predicted_family, target_family)]
        )


def test_packet_000373_registry_refines_modal_family_cue_policy() -> None:
    expected_pairs = {
        ("conditional_normative", "conditional_normative"),
        ("deontic", "conditional_normative"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "epistemic"),
    }

    assert set(COMPILER_REFINED_PACKET_000373_FAMILY_PAIRS) == expected_pairs
    margin_floors = {
        ("conditional_normative", "conditional_normative"): 0.075,
        ("deontic", "conditional_normative"): 0.45,
        ("frame", "conditional_normative"): 0.84,
        ("frame", "deontic"): 0.68,
        ("frame", "epistemic"): 0.34,
    }
    for predicted_family, target_family in COMPILER_REFINED_PACKET_000373_FAMILY_PAIRS:
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
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            >= margin_floors[(predicted_family, target_family)]
        )

    encoding = SpaCyLegalEncoder().encode(
        (
            "The Secretary may, whenever the Secretary shall deem it necessary, "
            "cause townsites to be surveyed."
        ),
        document_id="packet-000373-townsites-epistemic-cue",
    )
    assert any(
        cue.family == "epistemic"
        and cue.cue.lower() == "shall deem it necessary"
        for cue in encoding.cues
    )


def test_packet_003436_registry_refines_deontic_family_cue_policy() -> None:
    expected_pairs = {
        ("conditional_normative", "deontic"),
        ("frame", "deontic"),
    }

    assert set(COMPILER_REFINED_PACKET_003436_FAMILY_PAIRS) == expected_pairs
    margin_floors = {
        ("conditional_normative", "deontic"): 0.16,
        ("frame", "deontic"): 0.89,
    }
    for predicted_family, target_family in COMPILER_REFINED_PACKET_003436_FAMILY_PAIRS:
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
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            >= margin_floors[(predicted_family, target_family)]
        )


def test_packet_003762_registry_exposes_modal_ambiguity_policy() -> None:
    expected_pairs = {
        ("conditional_normative", "deontic"),
        ("frame", "deontic"),
    }
    margin_floors = {
        ("conditional_normative", "deontic"): 0.16,
        ("frame", "deontic"): 0.89,
    }

    assert set(COMPILER_AMBIGUITY_PACKET_003762_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_003762_FAMILY_PAIRS:
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
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            >= margin_floors[(predicted_family, target_family)]
        )


def test_packet_006902_registry_exposes_modal_ambiguity_policy() -> None:
    expected_pairs = {
        ("conditional_normative", "deontic"),
        ("frame", "conditional_normative"),
        ("frame", "temporal"),
    }

    assert set(COMPILER_AMBIGUITY_PACKET_006902_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_006902_FAMILY_PAIRS:
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


def test_modal_compiler_surfaces_packet_005666_adaptive_ambiguity_policy(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    scenarios = (
        (
            "us-code-16-430s-a4964b683637c7ef",
            "deontic",
            "temporal",
            -0.384196080636,
        ),
        (
            "us-code-22-9125-a2d95827b1007d2d",
            "frame",
            "conditional_normative",
            -0.855568138172,
        ),
        (
            "us-code-12-3-c5c8d666f911d349",
            "frame",
            "deontic",
            -0.446735090214,
        ),
    )
    expected_pairs = {
        ("deontic", "temporal"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
    }
    assert set(COMPILER_AMBIGUITY_PACKET_005666_FAMILY_PAIRS) == expected_pairs

    family_operator = {
        "deontic": ("D", "O", "obligation"),
        "frame": ("FRAME_BM25", "Frame", "frame"),
    }
    for index, (
        sample_id,
        predicted_family,
        target_family,
        family_margin,
    ) in enumerate(scenarios, start=1):
        predicted_system, predicted_symbol, predicted_label = family_operator[
            predicted_family
        ]
        predicted_share = min(0.95, abs(family_margin) + 0.02)
        target_share = predicted_share + family_margin
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
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-005666-adaptive-evidence-{index}",
            text=f"Synthetic packet 005666 {predicted_family} ambiguity evidence.",
            normalized_text=(
                f"Synthetic packet 005666 {predicted_family} ambiguity evidence."
            ),
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=predicted_system,
                    symbol=predicted_symbol,
                    label=predicted_label,
                    cue=predicted_family,
                    start_char=0,
                    end_char=len(predicted_family),
                    token_indices=[],
                ),
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=encoding.document_id,
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-packet-005666-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=predicted_system,
                        symbol=predicted_symbol,
                        label=predicted_label,
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role=predicted_label,
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="packet-005666",
                    ),
                ),
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        policy_pair = f"{predicted_family}->{target_family}"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
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
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["is_compiler_required_policy_pair"] is True
        assert base_ambiguity.metadata["is_priority_policy_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["adaptive_margin_direction"] == "outvoted"
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert base_ambiguity.severity == "requires_rule"
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


@pytest.mark.parametrize(
    ("predicted_family", "target_family", "runner_up_family", "expected_direction"),
    [
        ("deontic", "deontic", "frame", "contested"),
        ("deontic", "frame", "frame", "outvoted"),
        ("frame", "conditional_normative", "deontic", "outvoted"),
        ("frame", "deontic", "deontic", "outvoted"),
        ("frame", "epistemic", "deontic", "outvoted"),
        ("frame", "temporal", "deontic", "outvoted"),
    ],
)
def test_modal_compiler_surfaces_packet_000486_adaptive_ambiguity_policy(
    predicted_family: str,
    target_family: str,
    runner_up_family: str,
    expected_direction: str,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            modal_adaptive_family_margin=0.15,
        )
    )
    text = "Packet 000486 synthetic low-margin family evidence."
    encoding = SpaCyLegalEncoding(
        document_id=f"packet-000486-{predicted_family}-{target_family}",
        text=text,
        normalized_text=text.lower(),
        tokens=[],
        sentences=[],
        cues=[],
        citation="packet-000486",
        source="unit_test",
    )
    modal_ir = ModalIRDocument(
        document_id=encoding.document_id,
        source="unit_test",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="packet-000486-f0",
                operator=ModalIROperator(
                    family=predicted_family,
                    system="D" if predicted_family == "deontic" else "FRAME_BM25",
                    symbol="O" if predicted_family == "deontic" else "Frame",
                    label=predicted_family,
                ),
                predicate=ModalIRPredicate(
                    name=f"{predicted_family}_predicate",
                    arguments=["actor:agency"],
                    role=predicted_family,
                ),
                provenance=ModalIRProvenance(
                    source_id=encoding.document_id,
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="packet-000486",
                ),
            )
        ],
    )
    ranking = [
        {"family": predicted_family, "share_raw": 0.54, "share": 0.54},
        {"family": runner_up_family, "share_raw": 0.46, "share": 0.46},
    ]
    family_shares = {
        str(candidate["family"]): float(candidate["share_raw"])
        for candidate in ranking
    }

    policy_pair = f"{predicted_family}->{target_family}"
    explicit_type = (
        f"adaptive_{predicted_family}_{target_family}_{expected_direction}_margin_low"
    )
    assert (predicted_family, target_family) in set(
        COMPILER_AMBIGUITY_PACKET_000486_FAMILY_PAIRS
    )
    assert target_family in compiler_required_adaptive_ambiguity_targets(
        predicted_family
    )
    assert target_family in priority_signal_free_adaptive_ambiguity_targets(
        predicted_family
    )
    assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
    assert supports_signal_free_adaptive_ambiguity_pair(
        predicted_family,
        target_family,
    )

    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=ranking,
        family_shares=family_shares,
        predicted_family_source="packet_000486_test",
    )
    base_ambiguity = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
    )
    assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert base_ambiguity.metadata["is_compiler_required_policy_pair"] is True
    assert base_ambiguity.metadata["is_priority_policy_pair"] is True
    assert base_ambiguity.metadata["adaptive_margin_direction"] == expected_direction
    assert base_ambiguity.metadata["explicit_ambiguity_type"] == explicit_type
    assert any(
        ambiguity.ambiguity_type == explicit_type
        and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        and ambiguity.metadata["adaptive_base_ambiguity_type"]
        == "adaptive_family_margin_low"
        for ambiguity in ambiguities
    )


def test_modal_compiler_surfaces_packet_001944_deontic_compiler_ambiguity_policy() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            modal_adaptive_family_margin=0.15,
        )
    )
    scenarios = (
        ("deontic", "dynamic", -0.560068462368),
        ("deontic", "frame", -0.245881999218),
    )

    assert COMPILER_AMBIGUITY_PACKET_001944_FAMILY_PAIRS == (
        ("deontic", "dynamic"),
        ("deontic", "frame"),
    )
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_001944_FAMILY_PAIRS:
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

    for predicted_family, target_family, family_margin in scenarios:
        predicted_share = min(0.95, abs(family_margin) + 0.02)
        target_share = predicted_share + family_margin
        text = f"Packet 001944 {predicted_family} to {target_family} ambiguity."
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-001944-{predicted_family}-{target_family}",
            text=text,
            normalized_text=text.lower(),
            tokens=[],
            sentences=[],
            cues=[],
            citation="packet-001944",
            source="unit_test",
        )
        modal_ir = ModalIRDocument(
            document_id=encoding.document_id,
            source="unit_test",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"packet-001944-{target_family}-f0",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system="D",
                        symbol="P",
                        label="permission",
                    ),
                    predicate=ModalIRPredicate(
                        name="deontic_permission_predicate",
                        arguments=["actor:agency"],
                        role="permission",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=encoding.document_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="packet-001944",
                    ),
                )
            ],
        )
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
                "share": round(target_share, 6),
            },
        ]
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        policy_pair = f"{predicted_family}->{target_family}"
        explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="packet_001944_test",
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )

        assert base_ambiguity.candidate_ids == [predicted_family, target_family]
        assert base_ambiguity.severity == "requires_rule"
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["is_compiler_required_policy_pair"] is True
        assert base_ambiguity.metadata["is_priority_policy_pair"] is True
        assert base_ambiguity.metadata["adaptive_margin_direction"] == "outvoted"
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == explicit_type
        assert abs(
            float(base_ambiguity.metadata["family_margin_raw"]) - family_margin
        ) < 1e-12
        assert any(
            ambiguity.ambiguity_type == explicit_type
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["is_explicit_adaptive_ambiguity"] is True
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_002296_adaptive_ambiguity_policy() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            modal_adaptive_family_margin=0.15,
        )
    )
    scenarios = (
        ("conditional_normative", "deontic", -0.163344133887),
        ("frame", "deontic", -0.773399856727),
    )

    assert COMPILER_AMBIGUITY_PACKET_002296_FAMILY_PAIRS == (
        ("conditional_normative", "deontic"),
        ("frame", "deontic"),
    )
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_002296_FAMILY_PAIRS:
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

    for predicted_family, target_family, family_margin in scenarios:
        predicted_share = 0.5
        target_share = predicted_share + family_margin
        text = f"Packet 002296 {predicted_family} to {target_family} ambiguity."
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-002296-{predicted_family}-{target_family}",
            text=text,
            normalized_text=text.lower(),
            tokens=[],
            sentences=[],
            cues=[],
            citation="packet-002296",
            source="unit_test",
        )
        modal_ir = ModalIRDocument(
            document_id=encoding.document_id,
            source="unit_test",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"packet-002296-{predicted_family}-f0",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=(
                            "KD"
                            if predicted_family == "conditional_normative"
                            else "FRAME_BM25"
                        ),
                        symbol=(
                            "O|"
                            if predicted_family == "conditional_normative"
                            else "Frame"
                        ),
                        label=predicted_family,
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role=predicted_family,
                    ),
                    provenance=ModalIRProvenance(
                        source_id=encoding.document_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="packet-002296",
                    ),
                )
            ],
        )
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
                "share": round(target_share, 6),
            },
        ]
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        policy_pair = f"{predicted_family}->{target_family}"
        explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="packet_002296_test",
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )

        assert base_ambiguity.candidate_ids == [predicted_family, target_family]
        assert base_ambiguity.severity == "requires_rule"
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["is_compiler_required_policy_pair"] is True
        assert base_ambiguity.metadata["is_priority_policy_pair"] is True
        assert base_ambiguity.metadata["adaptive_margin_direction"] == "outvoted"
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == explicit_type
        assert abs(
            float(base_ambiguity.metadata["family_margin_raw"]) - family_margin
        ) < 1e-12
        assert any(
            ambiguity.ambiguity_type == explicit_type
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["is_explicit_adaptive_ambiguity"] is True
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_000814_adaptive_ambiguity_policy() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            modal_adaptive_family_margin=0.15,
        )
    )
    scenarios = (
        ("deontic", "conditional_normative", -0.238402902887),
        ("frame", "deontic", -0.058085568842),
    )

    assert COMPILER_AMBIGUITY_PACKET_000814_FAMILY_PAIRS == (
        ("deontic", "conditional_normative"),
        ("frame", "deontic"),
    )
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_000814_FAMILY_PAIRS:
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

    for predicted_family, target_family, family_margin in scenarios:
        predicted_share = 0.5
        target_share = predicted_share + family_margin
        text = f"Packet 000814 {predicted_family} to {target_family} ambiguity."
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-000814-{predicted_family}-{target_family}",
            text=text,
            normalized_text=text.lower(),
            tokens=[],
            sentences=[],
            cues=[],
            citation="packet-000814",
            source="unit_test",
        )
        modal_ir = ModalIRDocument(
            document_id=encoding.document_id,
            source="unit_test",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"packet-000814-{predicted_family}-f0",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=(
                            "D"
                            if predicted_family == "deontic"
                            else "FRAME_BM25"
                        ),
                        symbol=(
                            "O"
                            if predicted_family == "deontic"
                            else "Frame"
                        ),
                        label=predicted_family,
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role=predicted_family,
                    ),
                    provenance=ModalIRProvenance(
                        source_id=encoding.document_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="packet-000814",
                    ),
                )
            ],
        )
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
                "share": round(target_share, 6),
            },
        ]
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        policy_pair = f"{predicted_family}->{target_family}"
        explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="packet_000814_test",
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )

        assert base_ambiguity.candidate_ids == [predicted_family, target_family]
        assert base_ambiguity.severity == "requires_rule"
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["is_compiler_required_policy_pair"] is True
        assert base_ambiguity.metadata["is_priority_policy_pair"] is True
        assert base_ambiguity.metadata["adaptive_margin_direction"] == "outvoted"
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == explicit_type
        assert abs(
            float(base_ambiguity.metadata["family_margin_raw"]) - family_margin
        ) < 1e-12
        assert any(
            ambiguity.ambiguity_type == explicit_type
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["is_explicit_adaptive_ambiguity"] is True
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )

_USCODE_25_422_HEADING_ONLY_TEXT = "Housing voucher benefits and utility allowances."
_USCODE_48_1572_HEADING_ONLY_TEXT = "Administrative notice and hearing."
_USCODE_42_6323_HEADING_ONLY_TEXT = "Notice and hearing requirements."
_USCODE_42_18791_TODO_TEXT = "Sec. 18791 - Administrative provisions. Additional provisions."
_USCODE_7_473A_SEC_HEADING_TEXT = "Sec. 473a - Cotton classification services."
_USCODE_20_1067J_SEC_HEADING_TEXT = "Sec. 1067j - Administrative provisions."
_USCODE_15_2501_SEC_HEADING_TEXT = "Sec. 2501 - Congressional findings and policy."
_USCODE_7_431_TODO_TEXT = "Sec. 431 - Declaration of policy."
_USCODE_6_257_TODO_TEXT = "Sec. 257 - National planning scenarios and preparedness targets."
_USCODE_45_81_TO_92_TODO_TEXT = "Secs. 81 to 92. Repealed."
_USCODE_46_55318_TODO_TEXT = (
    "§55318. Effect on other law This subchapter does not affect chapter 5 of title 5. "
    "(Pub. L. 109–304, §8(c), Oct. 6, 2006, 120 Stat. 1648.) Historical and Revision "
    "Notes Revised Section Source (U.S. Code) Source (Statutes at Large) 55318 46 "
    "App.:1241p. Pub. L. 99–198, title XI, §1143, Dec. 23, 1985, 99 Stat. 1496. The "
    "words \"section 1707a(b)(8) of title 7\" are omitted because the provision referred "
    "to has been repealed."
)
_USCODE_SAVINGS_EFFECT_RESIDUAL_TEXT = (
    "Sec. 18726 - Savings provision. Nothing in this part affects any other "
    "provision of law of a Federal department or agency."
)
_USCODE_8_606_TODO_TEXT = (
    "U.S.C. Title 8 - ALIENS AND NATIONALITY 8 U.S.C. United States Code, 2024 Edition "
    "Title 8 - ALIENS AND NATIONALITY CHAPTER 11 - NATIONALITY SUBCHAPTER II - NATIONALITY "
    "AT BIRTH Sec. 606 - Transferred From the U.S. Government Publishing Office, www.gpo.gov "
    "§606. Transferred Editorial Notes Codification Section transferred to section 1421l of "
    "Title 48, Territories and Insular Possessions. That section was later repealed. See "
    "section 1407 of this title."
)
_USCODE_46_115_TODO_TEXT = (
    "§115. Vessel In this title, the term \"vessel\" has the meaning given that term in "
    "section 3 of title 1. (Pub. L. 109–304, §4, Oct. 6, 2006, 120 Stat. 1487.) Historical "
    "and Revision Notes Revised Section Source (U.S. Code) Source (Statutes at Large) 115 "
    "46:2101(45)."
)
_USCODE_36_110105_TODO_TEXT = (
    "U.S.C. Title 36 - PATRIOTIC AND NATIONAL OBSERVANCES, CEREMONIES, AND ORGANIZATIONS 36 U.S.C. United States Co"
    "de, 2024 Edition Title 36 - PATRIOTIC AND NATIONAL OBSERVANCES, CEREMONIES, AND ORGANIZATIONS Subtitle II - Pa"
    "triotic and National Organizations Part B - Organizations CHAPTER 1101 - JEWISH WAR VETERANS OF THE UNITED STA"
    "TES OF AMERICA, INCORPORATED Sec. 110105 - Governing body From the U.S. Government Publishing Office, www.gpo."
    "gov §110105. Governing body (a) Board of Directors .—The board of directors and the responsibilities of the bo"
    "ard are as provided in the articles of incorporation. (b) Officers .—The officers and the election of officers"
    " are as provided in the articles of incorporation. (Pub. L. 105–225, Aug. 12, 1998, 112 Stat. 1367.) Historica"
    "l and Revision Notes Revised Section Source (U.S. Code) Source (Statutes at Large) 110105(a) 36:2706. Aug. 21,"
    " 1984, Pub. L. 98–391, §§6, 7, 98 Stat. 1359. 110105(b) 36:2707."
)
_USCODE_25_450_TODO_TEXT = (
    "U.S.C. Title 25 - INDIANS 25 U.S.C. United States Code, 2024 Edition Title 25 - INDIANS CHAPTER 14 - MISCELLAN"
    "EOUS SUBCHAPTER II - INDIAN SELF-DETERMINATION AND EDUCATION ASSISTANCE Sec. 450 - Transferred From the U.S. G"
    "overnment Publishing Office, www.gpo.gov §450. Transferred Editorial Notes Codification Section 450 was editor"
    "ially reclassified as section 5301 of this title."
)
_USCODE_50_2523B_RESIDUAL_SPAN_TEXT = (
    "Sec. 2523b - Transfer authority and procedures. Administrative notice and hearing "
    "procedures are established for this section. Editorial Notes Codification Section "
    "2523b was editorially reclassified as section 3373b of this title."
)
_USCODE_10_3101_ADMINISTRATIVE_RESIDUAL_SPAN_TEXT = (
    "Sec. 3101 - General provisions. Administrative notice and hearing procedures "
    "for eligibility review and petition records."
)
_USCODE_ADMINISTRATIVE_PROCEEDING_RESIDUAL_SPAN_TEXT = (
    "Sec. 1116 - Administrative record. Notice of proceeding and hearing records "
    "for investigation testimony."
)
_USCODE_44_3558_REPORTS_RESIDUAL_SPAN_TEXT = (
    "Sec. 3558 - Major incident reporting. Congressional notification and reports."
)
_USCODE_25_5396_TODO_TEXT = (
    "U.S.C. Title 25 - INDIANS 25 U.S.C. United States Code, 2024 Edition Title 25 - INDIANS CHAPTER 46 - INDIAN SE"
    "LF-DETERMINATION AND EDUCATION ASSISTANCE SUBCHAPTER V - TRIBAL SELF-GOVERNANCE-INDIAN HEALTH SERVICE Sec. 539"
    "6 - Application of other sections of this chapter From the U.S. Government Publishing Office, www.gpo.gov §539"
    "6. Application of other sections of this chapter (a) Mandatory application All provisions of sections 5305(b),"
    " 5306, 5307, 5321(c) and (d), 5323, 5324(k) and (l), 5325(a) through (k), and 5332 of this title and section 3"
    "14 of Public Law 101–512 (coverage under chapter 171 of title 28, commonly known as the \"Federal Tort Claims A"
    "ct\"), to the extent not in conflict with this subchapter, shall apply to compacts and funding agreements autho"
    "rized by this subchapter. (b) Discretionary application At the request of a participating Indian tribe, any ot"
    "her provision of subchapter I of this chapter, to the extent such provision is not in conflict with this subch"
    "apter, shall be made a part of a funding agreement or compact entered into under this subchapter. The Secretar"
    "y is obligated to include such provision at the option of the participating Indian tribe or tribes. If such pr"
    "ovision is incorporated it shall have the same force and effect as if it were set out in full in this subchapt"
    "er. In the event an Indian tribe requests such incorporation at the negotiation stage of a compact or funding "
    "agreement, such incorporation shall be deemed effective immediately and shall control the negotiation and resu"
    "lting compact and funding agreement. (Pub. L. 93–638, title V, §516, as added Pub. L. 106–260, §4, Aug. 18, 20"
    "00, 114 Stat. 729.) Editorial Notes References in Text Section 314 of Pub. L. 101–512, referred to in subsec. "
    "(a), is section 314 of Pub. L. 101–512, which is set out as a note under section 5321 of this title. Subchapte"
    "r I of this chapter, referred to in subsec. (b), was in the original \"title I\", meaning title I of Pub. L. 93–"
    "638, known as the Indian Self-Determination Act, which is classified principally to subchapter I (§5321 et seq"
    ".) of this chapter. For complete classification of title I to the Code, see Short Title note set out under sec"
    "tion 5301 of this title and Tables. Codification Section was formerly classified to section 458aaa–15 of this "
    "title prior to editorial reclassification and renumbering as this section."
)
_USCODE_25_507_PACKET_519_TEXT = (
    "U.S.C. Title 25 - INDIANS 25 U.S.C. United States Code, 2024 Edition "
    "Title 25 - INDIANS CHAPTER 14 - MISCELLANEOUS SUBCHAPTER VIII - INDIANS "
    "IN OKLAHOMA: PROMOTION OF WELFARE Sec. 507 - Transferred From the U.S. "
    "Government Publishing Office, www.gpo.gov §507. Transferred Editorial "
    "Notes Codification Section 507 was editorially reclassified as section "
    "5207 of this title."
)
_USCODE_10_167_PACKET_519_TEXT = (
    "U.S.C. Title 10 - ARMED FORCES 10 U.S.C. United States Code, 2024 Edition "
    "Title 10 - ARMED FORCES PART I - ORGANIZATION AND GENERAL MILITARY POWERS "
    "CHAPTER 6 - COMBATANT COMMANDS Sec. 167 - Unified combatant command for "
    "special operations forces From the U.S. Government Publishing Office, "
    "www.gpo.gov §167. Unified combatant command for special operations forces "
    "(a) Establishment. With the advice and assistance of the Chairman of the "
    "Joint Chiefs of Staff, the President, through the Secretary of Defense, "
    "shall establish under section 161 of this title a unified combatant "
    "command for special operations forces. (b) Assignment of Forces. Unless "
    "otherwise directed by the Secretary of Defense, all active and reserve "
    "special operations forces of the armed forces stationed in the United "
    "States shall be assigned to the special operations command. (c) Grade of "
    "Commander. The commander of the special operations command shall hold the "
    "grade of general or admiral while serving in that position. (d) Command "
    "of Activity or Mission. Unless otherwise directed by the President or the "
    "Secretary of Defense, a special operations activity or mission shall be "
    "conducted under the command of the commander of the unified combatant "
    "command in whose geographic area the activity or mission is to be "
    "conducted."
)
_USCODE_38_8112_PACKET_519_TEXT = (
    "U.S.C. Title 38 - VETERANS' BENEFITS 38 U.S.C. United States Code, 2024 "
    "Edition Title 38 - VETERANS' BENEFITS PART VI - ACQUISITION AND "
    "DISPOSITION OF PROPERTY CHAPTER 81 - ACQUISITION AND OPERATION OF "
    "HOSPITAL AND DOMICILIARY FACILITIES; PROCUREMENT AND SUPPLY; ENHANCED-USE "
    "LEASES OF REAL PROPERTY SUBCHAPTER I - ACQUISITION AND OPERATION OF "
    "MEDICAL FACILITIES Sec. 8112 - Partial relinquishment of legislative "
    "jurisdiction From the U.S. Government Publishing Office, www.gpo.gov "
    "§8112. Partial relinquishment of legislative jurisdiction The Secretary, "
    "on behalf of the United States, may relinquish to the State in which any "
    "lands or interests under the supervision or control of the Secretary are "
    "situated, such measure of legislative jurisdiction over such lands or "
    "interests as is necessary to establish concurrent jurisdiction between the "
    "Federal Government and the State concerned. Such partial relinquishment "
    "of legislative jurisdiction shall be initiated by filing a notice with the "
    "Governor of the State concerned and shall take effect upon acceptance by "
    "such State. Editorial Notes Prior Provisions Provisions similar to those "
    "comprising this section were contained in former section 5007 of this "
    "title prior to the general revision of this subchapter by Pub. L. 96-22."
)
_USCODE_36_170307_TODO_TEXT = (
    "Administrative notice and hearing procedures are established for this subchapter."
)
_USCODE_36_21110_TODO_TEXT = (
    "Sec. 21110 - Administrative notice and hearing activities. "
    "Historical and Revision Notes."
)
_USCODE_10_1095C_TODO_TEXT = (
    "Administrative review procedures are established for health care collection actions."
)
_USCODE_19_2113_TODO_TEXT = (
    "Administrative notice and hearing procedures are established for import petitions."
)
_USCODE_25_57_RESIDUAL_SPAN_TODO_TEXT = (
    "U.S.C. Title 25 - INDIANS 25 U.S.C. United States Code, 2024 Edition "
    "Title 25 - INDIANS CHAPTER 2 - OFFICERS OF INDIAN AFFAIRS Sec. 57 - "
    "Omitted From the U.S. Government Publishing Office, www.gpo.gov §57. "
    "Omitted Editorial Notes Codification Section, act Mar. 3, 1925, ch. 462, "
    "43 Stat. 1147, which authorized the Secretary of the Interior to allow "
    "employees in the Indian Service heat and light for quarters without "
    "charge, was not repeated in subsequent appropriation acts."
)
_USCODE_15_1212_TRANSFER_FUNCTIONS_TODO_TEXT = (
    "U.S.C. Title 15 - COMMERCE AND TRADE 15 U.S.C. United States Code, 2024 "
    "Edition Title 15 - COMMERCE AND TRADE CHAPTER 26 - HOUSEHOLD "
    "REFRIGERATORS Sec. 1212 - Violations; misdemeanor; penalties From the "
    "U.S. Government Publishing Office, www.gpo.gov §1212. Violations; "
    "misdemeanor; penalties Any person who violates section 1211 of this title "
    "shall be guilty of a misdemeanor and shall, upon conviction thereof, be "
    "subject to imprisonment for not more than one year, or a fine of not more "
    "than $1,000, or both. (Aug. 2, 1956, ch. 890, §2, 70 Stat. 953.) "
    "Statutory Notes and Related Subsidiaries Transfer of Functions Functions "
    "of Secretary of Commerce and Federal Trade Commission under this chapter "
    "transferred to Consumer Product Safety Commission, see section 2079 of "
    "this title."
)
_USCODE_2_5602_SYMBOLIC_VALIDITY_TODO_TEXT = (
    "U.S.C. Title 2 - THE CONGRESS 2 U.S.C. United States Code, 2024 Edition "
    "Title 2 - THE CONGRESS CHAPTER 55 - HOUSE OF REPRESENTATIVES OFFICERS AND "
    "ADMINISTRATION SUBCHAPTER VIII - SERGEANT AT ARMS Sec. 5602 - Tenure of "
    "office of Sergeant at Arms From the U.S. Government Publishing Office, "
    "www.gpo.gov §5602. Tenure of office of Sergeant at Arms Any person duly "
    "elected and qualified as Sergeant at Arms of the House of Representatives "
    "shall continue in said office until his successor is chosen and qualified, "
    "subject however, to removal by the House of Representatives. (Oct. 1, "
    "1890, ch. 1256, §6, 26 Stat. 646.) Editorial Notes Codification Section "
    "was formerly classified to section 83 of this title prior to editorial "
    "reclassification and renumbering as this section."
)
_USCODE_5_5348_SYMBOLIC_VALIDITY_TODO_TEXT = (
    "U.S.C. Title 5 - GOVERNMENT ORGANIZATION AND EMPLOYEES 5 U.S.C. United "
    "States Code, 2024 Edition Title 5 - GOVERNMENT ORGANIZATION AND EMPLOYEES "
    "PART III - EMPLOYEES Subpart D - Pay and Allowances CHAPTER 53 - PAY RATES "
    "AND SYSTEMS SUBCHAPTER IV - PREVAILING RATE SYSTEMS Sec. 5348 - Crews of "
    "vessels From the U.S. Government Publishing Office, www.gpo.gov §5348. "
    "Crews of vessels (a) Except as provided by subsection (b) of this section, "
    "the pay of officers and members of crews of vessels excepted from chapter "
    "51 of this title by section 5102(c)(8) of this title shall be fixed and "
    "adjusted from time to time as nearly as is consistent with the public "
    "interest in accordance with prevailing rates and practices in the maritime "
    "industry. (b) Vessel employees in an area where inadequate maritime "
    "industry practice exists and vessel employees of the Corps of Engineers "
    "shall have their pay fixed and adjusted under the provisions of this "
    "subchapter other than this section, as appropriate. Statutory Notes and "
    "Related Subsidiaries Effective Date of 1972 Amendment Amendment by Pub. L. "
    "92–392 effective on first day of first applicable pay period beginning on "
    "or after 90th day after Aug. 19, 1972, see section 15(a) of Pub. L. "
    "92–392, set out as an Effective Date note under section 5341 of this "
    "title."
)
_USCODE_42_15251_SYMBOLIC_VALIDITY_TODO_TEXT = (
    "§15251. Transferred Editorial Notes Codification Section 15251 was "
    "editorially reclassified as section 50321 of Title 34, Crime Control and "
    "Law Enforcement."
)
_USCODE_2_88B_5_TODO_TEXT = "The administrative notice and hearing procedures."
_USCODE_42_18431_SYMBOLIC_VALIDITY_TODO_TEXT = (
    "The notice and hearing requirements for administrative review."
)
_USCODE_42_12313_SYMBOLIC_VALIDITY_TODO_TEXT = (
    "The administrative notice and hearing procedures for certification."
)
_USCODE_43_2430_PACKET_143_TODO_TEXT = (
    "The administrative notice and hearing procedures for offshore mineral leasing "
    "adjustments and adjudications."
)
_USCODE_16_431_PACKET_2400_TEXT = (
    "U.S.C. Title 16 - CONSERVATION 16 U.S.C. United States Code, 2024 Edition "
    "Title 16 - CONSERVATION CHAPTER 1 - NATIONAL PARKS, MILITARY PARKS, "
    "MONUMENTS, AND SEASHORES SUBCHAPTER LXI - NATIONAL AND INTERNATIONAL "
    "MONUMENTS AND MEMORIALS Sec. 431 - Repealed. Pub. L. 113-287, §7, "
    "Dec. 19, 2014, 128 Stat. 3272 From the U.S. Government Publishing Office, "
    "www.gpo.gov §431. Repealed. Pub. L. 113–287, §7, Dec. 19, 2014, "
    "128 Stat. 3272 Section, act June 8, 1906, ch. 3060, §2, 34 Stat. 225, "
    "authorized declaration of national monuments. See section 320301(a) to "
    "(c) of Title 54, National Park Service and Related Programs."
)
_USCODE_16_590R_PACKET_2400_TEXT = (
    "U.S.C. Title 16 - CONSERVATION 16 U.S.C. United States Code, 2024 Edition "
    "Title 16 - CONSERVATION CHAPTER 3C - WATER CONSERVATION SUBCHAPTER I - "
    "FACILITIES FOR WATER STORAGE AND UTILIZATION Secs. 590r to 590x-4 - "
    "Repealed. Pub. L. 87-128, title III, §341(a), Aug. 8, 1961, 75 Stat. 318 "
    "From the U.S. Government Publishing Office, www.gpo.gov §§590r to 590x–4. "
    "Repealed. Pub. L. 87–128, title III, §341(a), Aug. 8, 1961, 75 Stat. 318 "
    "Section 590r, acts Aug. 28, 1937, ch. 870, §1, 50 Stat. 869, related to "
    "Congressional declaration of policy. Section 590x, act Aug. 28, 1937, "
    "ch. 870, §7, 50 Stat. 870, authorized appropriations."
)
_USCODE_2_453_PACKET_39_TEXT = "The oath of office."
_USCODE_9_6_PACKET_39_TEXT = "The application heard as motion."
_USCODE_43_1656_PACKET_39_TEXT = "The withdrawal and reservation of lands."


def test_modal_compiler_surfaces_packet_000224_family_cue_policy(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    scenarios = (
        (
            "us-code-42-2415 to 2421.-e3358d996b11fe81",
            "frame",
            "temporal",
            -0.98507144513,
        ),
        (
            "us-code-30-501-3c448e13ffc98255",
            "deontic",
            "conditional_normative",
            -0.111004827483,
        ),
        (
            "us-code-20-80q-6-6170dcb4977ae241",
            "frame",
            "deontic",
            -0.911811584575,
        ),
        (
            "us-code-42-7195.-122e167c4369367c",
            "frame",
            "epistemic",
            -0.298684341762,
        ),
    )
    assert set(COMPILER_AMBIGUITY_PACKET_000224_FAMILY_PAIRS) == {
        ("deontic", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "epistemic"),
        ("frame", "temporal"),
    }

    family_operator = {
        "deontic": ("D", "O", "obligation"),
        "frame": ("FRAME_BM25", "Frame", "frame"),
    }
    for index, (
        sample_id,
        predicted_family,
        target_family,
        family_margin,
    ) in enumerate(scenarios, start=1):
        predicted_system, predicted_symbol, predicted_label = family_operator[
            predicted_family
        ]
        predicted_share = min(0.999, max(0.2, abs(family_margin) + 0.001))
        target_share = predicted_share + family_margin
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
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-000224-adaptive-evidence-{index}",
            text=f"Synthetic packet 000224 {predicted_family} ambiguity evidence.",
            normalized_text=(
                f"Synthetic packet 000224 {predicted_family} ambiguity evidence."
            ),
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=predicted_system,
                    symbol=predicted_symbol,
                    label=predicted_label,
                    cue=predicted_family,
                    start_char=0,
                    end_char=len(predicted_family),
                    token_indices=[],
                ),
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=encoding.document_id,
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-packet-000224-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=predicted_system,
                        symbol=predicted_symbol,
                        label=predicted_label,
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role=predicted_label,
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="packet-000224",
                    ),
                ),
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        policy_pair = f"{predicted_family}->{target_family}"
        explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in priority_signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert base_ambiguity.severity == "requires_rule"
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["is_compiler_required_policy_pair"] is True
        assert base_ambiguity.metadata["is_priority_policy_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["adaptive_margin_direction"] == "outvoted"
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == explicit_type
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert any(
            ambiguity.ambiguity_type == explicit_type
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_001029_ambiguity_policy(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    expected_pairs = {
        ("deontic", "temporal"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "temporal"),
    }
    assert set(COMPILER_AMBIGUITY_PACKET_001029_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in expected_pairs:
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

    family_operator = {
        "deontic": ("D", "O", "obligation"),
        "frame": ("FRAME_BM25", "Frame", "frame"),
    }
    scenarios = (
        (
            "us-code-7-4207-7841fcb215fbf21c",
            "frame",
            "temporal",
            -0.381161941551,
        ),
        (
            "us-code-40-11703-b6f57de28c340894",
            "frame",
            "deontic",
            -0.482417937439,
        ),
        (
            "us-code-11-781-567abfcaee308b66",
            "frame",
            "conditional_normative",
            -0.961080824965,
        ),
        (
            "us-code-42-300jj-f338d43f4efd49a3",
            "frame",
            "conditional_normative",
            -0.56442733376,
        ),
        (
            "us-code-10-2216-fd634bec8b2ae0f5",
            "frame",
            "temporal",
            -0.692747437275,
        ),
        (
            "us-code-42-141 to 148.-b4619e2a4060b8f9",
            "deontic",
            "temporal",
            -0.294339101504,
        ),
    )
    for index, (
        sample_id,
        predicted_family,
        target_family,
        family_margin,
    ) in enumerate(scenarios, start=1):
        predicted_system, predicted_symbol, predicted_label = family_operator[
            predicted_family
        ]
        predicted_share = min(0.999, max(0.2, abs(family_margin) + 0.001))
        target_share = predicted_share + family_margin
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
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-001029-adaptive-evidence-{index}",
            text=f"Synthetic packet 001029 {predicted_family} ambiguity evidence.",
            normalized_text=(
                f"Synthetic packet 001029 {predicted_family} ambiguity evidence."
            ),
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=predicted_system,
                    symbol=predicted_symbol,
                    label=predicted_label,
                    cue=predicted_family,
                    start_char=0,
                    end_char=len(predicted_family),
                    token_indices=[],
                ),
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=encoding.document_id,
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-packet-001029-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=predicted_system,
                        symbol=predicted_symbol,
                        label=predicted_label,
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role=predicted_label,
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="packet-001029",
                    ),
                ),
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        policy_pair = f"{predicted_family}->{target_family}"
        explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert base_ambiguity.severity == "requires_rule"
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["is_compiler_required_policy_pair"] is True
        assert base_ambiguity.metadata["is_priority_policy_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["adaptive_margin_direction"] == "outvoted"
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == explicit_type
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert any(
            ambiguity.ambiguity_type == explicit_type
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_006897_adaptive_ambiguity_policy(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    expected_pairs = {
        ("conditional_normative", "conditional_normative"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
    }
    assert set(COMPILER_AMBIGUITY_PACKET_006897_FAMILY_PAIRS) == expected_pairs
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

    family_operator = {
        "conditional_normative": ("CEC", "COND_O", "conditional_obligation"),
        "frame": ("FRAME_BM25", "Frame", "frame"),
    }
    scenarios = (
        (
            "us-code-16-410aaa-47-99f343e934f1f686",
            "frame",
            "conditional_normative",
            -0.063183777235,
        ),
        (
            "us-code-34-10755-434d0dad64749892",
            "conditional_normative",
            "conditional_normative",
            0.140121910946,
        ),
        (
            "us-code-10-1135-d14a425b22f99235",
            "frame",
            "deontic",
            -0.448124968012,
        ),
    )
    for index, (
        sample_id,
        predicted_family,
        target_family,
        family_margin,
    ) in enumerate(scenarios, start=1):
        predicted_system, predicted_symbol, predicted_label = family_operator[
            predicted_family
        ]
        if predicted_family == target_family:
            runner_up_family = "deontic"
            predicted_share = 0.5
            runner_up_share = predicted_share - family_margin
            ranking = [
                {
                    "family": predicted_family,
                    "count": 0,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": runner_up_family,
                    "count": 0,
                    "share_raw": runner_up_share,
                    "share": runner_up_share,
                },
            ]
            expected_direction = "contested"
            expected_candidate_ids = [predicted_family]
        else:
            predicted_share = min(0.999, max(0.2, abs(family_margin) + 0.001))
            target_share = predicted_share + family_margin
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
            expected_direction = "outvoted"
            expected_candidate_ids = [predicted_family, target_family]
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-006897-adaptive-evidence-{index}",
            text=f"Synthetic packet 006897 {predicted_family} ambiguity evidence.",
            normalized_text=(
                f"Synthetic packet 006897 {predicted_family} ambiguity evidence."
            ),
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=predicted_system,
                    symbol=predicted_symbol,
                    label=predicted_label,
                    cue=predicted_family,
                    start_char=0,
                    end_char=len(predicted_family),
                    token_indices=[],
                ),
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=encoding.document_id,
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-packet-006897-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=predicted_system,
                        symbol=predicted_symbol,
                        label=predicted_label,
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role=predicted_label,
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="packet-006897",
                    ),
                ),
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        policy_pair = f"{predicted_family}->{target_family}"
        explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_"
            f"{expected_direction}_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["is_compiler_required_policy_pair"] is True
        assert base_ambiguity.metadata["is_priority_policy_pair"] is True
        assert base_ambiguity.metadata["adaptive_margin_direction"] == expected_direction
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == explicit_type
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert any(
            ambiguity.ambiguity_type == explicit_type
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["is_explicit_adaptive_ambiguity"] is True
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_001316_deontic_ambiguity_policy(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    assert set(COMPILER_AMBIGUITY_PACKET_001316_FAMILY_PAIRS) == {
        ("deontic", "deontic"),
        ("deontic", "temporal"),
    }

    scenarios = (
        (
            "us-code-42-9126.-ae799f62909a6b9e",
            "deontic",
            0.58,
            "temporal",
            0.58 - 0.03374331246,
            "deontic",
            0.03374331246,
            "contested",
            ["deontic"],
        ),
        (
            "us-code-50-3369c.-3175f8ba39d9c91d",
            "deontic",
            0.61,
            "temporal",
            0.61 - 0.268693966018,
            "temporal",
            -0.268693966018,
            "outvoted",
            ["deontic", "temporal"],
        ),
    )
    for index, (
        sample_id,
        predicted_family,
        predicted_share,
        runner_up_family,
        runner_up_share,
        target_family,
        family_margin,
        margin_direction,
        candidate_ids,
    ) in enumerate(scenarios, start=1):
        ranking = [
            {
                "family": predicted_family,
                "count": 0,
                "share_raw": predicted_share,
                "share": predicted_share,
            },
            {
                "family": runner_up_family,
                "count": 0,
                "share_raw": runner_up_share,
                "share": runner_up_share,
            },
        ]
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-001316-adaptive-evidence-{index}",
            text="Synthetic packet 001316 deontic ambiguity evidence.",
            normalized_text="Synthetic packet 001316 deontic ambiguity evidence.",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                    cue="shall",
                    start_char=0,
                    end_char=5,
                    token_indices=[],
                ),
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=encoding.document_id,
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-packet-001316-{index}",
                    operator=ModalIROperator(
                        family="deontic",
                        system="D",
                        symbol="O",
                        label="obligation",
                    ),
                    predicate=ModalIRPredicate(
                        name="deontic_predicate",
                        arguments=["actor:agency"],
                        role="obligation",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="packet-001316",
                    ),
                ),
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        policy_pair = f"{predicted_family}->{target_family}"
        explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_"
            f"{margin_direction}_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in priority_signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["is_compiler_required_policy_pair"] is True
        assert base_ambiguity.metadata["is_priority_policy_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["adaptive_margin_direction"] == margin_direction
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == explicit_type
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert any(
            ambiguity.ambiguity_type == explicit_type
            and ambiguity.candidate_ids == candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_000935_adaptive_ambiguity_policy(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    scenarios = (
        (
            "us-code-11-781-567abfcaee308b66",
            "frame",
            "conditional_normative",
            -0.959614180332,
        ),
        (
            "us-code-42-300jj-f338d43f4efd49a3",
            "frame",
            "conditional_normative",
            -0.553315447242,
        ),
        (
            "us-code-40-11703-b6f57de28c340894",
            "frame",
            "deontic",
            -0.493490397595,
        ),
        (
            "us-code-7-4207-7841fcb215fbf21c",
            "frame",
            "temporal",
            -0.370624321296,
        ),
        (
            "us-code-42-141 to 148.-b4619e2a4060b8f9",
            "deontic",
            "temporal",
            -0.309802392535,
        ),
        (
            "us-code-10-2216-fd634bec8b2ae0f5",
            "frame",
            "temporal",
            -0.710609697904,
        ),
    )
    expected_pairs = {
        ("deontic", "temporal"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "temporal"),
    }
    assert set(COMPILER_AMBIGUITY_PACKET_000935_FAMILY_PAIRS) == expected_pairs

    family_operator = {
        "deontic": ("D", "O", "obligation"),
        "frame": ("FRAME_BM25", "Frame", "frame"),
    }
    for index, (
        sample_id,
        predicted_family,
        target_family,
        family_margin,
    ) in enumerate(scenarios, start=1):
        predicted_system, predicted_symbol, predicted_label = family_operator[
            predicted_family
        ]
        predicted_share = min(0.999, max(0.2, abs(family_margin) + 0.001))
        target_share = predicted_share + family_margin
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
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-000935-adaptive-evidence-{index}",
            text=f"Synthetic packet 000935 {predicted_family} ambiguity evidence.",
            normalized_text=(
                f"Synthetic packet 000935 {predicted_family} ambiguity evidence."
            ),
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=predicted_system,
                    symbol=predicted_symbol,
                    label=predicted_label,
                    cue=predicted_family,
                    start_char=0,
                    end_char=len(predicted_family),
                    token_indices=[],
                ),
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=encoding.document_id,
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-packet-000935-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=predicted_system,
                        symbol=predicted_symbol,
                        label=predicted_label,
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role=predicted_label,
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="packet-000935",
                    ),
                ),
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        policy_pair = f"{predicted_family}->{target_family}"
        explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in priority_signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert base_ambiguity.severity == "requires_rule"
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["is_compiler_required_policy_pair"] is True
        assert base_ambiguity.metadata["is_priority_policy_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["adaptive_margin_direction"] == "outvoted"
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == explicit_type
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert any(
            ambiguity.ambiguity_type == explicit_type
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_registry_packet_000124_refines_family_cue_policy_pairs() -> None:
    expected_pairs = {
        ("deontic", "conditional_normative"),
        ("deontic", "frame"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "epistemic"),
        ("temporal", "deontic"),
    }

    assert set(COMPILER_REFINED_PACKET_000124_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)


def test_modal_registry_packet_000222_refines_family_cue_policy_pairs() -> None:
    expected_pairs = {
        ("deontic", "deontic"),
        ("deontic", "frame"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "doxastic"),
        ("frame", "epistemic"),
        ("frame", "frame"),
        ("frame", "temporal"),
    }

    assert set(COMPILER_REFINED_PACKET_000222_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)

    assert (
        compiler_weak_typed_self_family_cue_margin_buffer("deontic", "deontic")
        >= 0.155
    )
    for target_family in (
        "conditional_normative",
        "deontic",
        "doxastic",
        "epistemic",
        "frame",
        "temporal",
    ):
        assert (
            compiler_refined_modal_family_cue_margin_buffer("frame", target_family)
            >= 0.015
        )
    assert (
        compiler_weak_typed_self_family_cue_margin_buffer("frame", "frame")
        >= 0.19
    )


def test_modal_registry_packet_000176_refines_frame_normative_temporal_pairs() -> None:
    expected_pairs = {
        ("deontic", "frame"),
        ("deontic", "temporal"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "temporal"),
    }

    assert set(COMPILER_REFINED_PACKET_000176_FAMILY_PAIRS) == expected_pairs
def test_packet_002414_registry_exposes_adaptive_family_ambiguity_policy() -> None:
    expected_pairs = {
        ("conditional_normative", "conditional_normative"),
        ("deontic", "deontic"),
        ("deontic", "temporal"),
        ("frame", "conditional_normative"),
        ("frame", "epistemic"),
    }

    assert set(COMPILER_AMBIGUITY_PACKET_002414_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            > 0.0
        )


def test_packet_002414_adaptive_low_margins_emit_explicit_ambiguities() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(spacy_model_name="blank")
    )
    scenarios = (
        (
            "us-code-10-931a-f50abc457484ada6",
            "frame",
            0.843606,
            "conditional_normative",
            0.156394,
            "conditional_normative",
            -0.687212,
            "outvoted",
            ["frame", "conditional_normative"],
        ),
        (
            "us-code-22-8808-387e8cde9e6ad300",
            "deontic",
            0.639709,
            "temporal",
            0.360291,
            "temporal",
            -0.279418,
            "outvoted",
            ["deontic", "temporal"],
        ),
        (
            "us-code-43-364f.-f76294ee50dd54b8",
            "deontic",
            0.510048,
            "temporal",
            0.489952,
            "deontic",
            0.020096,
            "contested",
            ["deontic"],
        ),
        (
            "us-code-18-647-dff85016d0ab1ea6",
            "frame",
            0.805782,
            "epistemic",
            0.194218,
            "epistemic",
            -0.611564,
            "outvoted",
            ["frame", "epistemic"],
        ),
        (
            "us-code-31-735-5e38334daee34d4d",
            "conditional_normative",
            0.508316,
            "frame",
            0.491684,
            "conditional_normative",
            0.016632,
            "contested",
            ["conditional_normative"],
        ),
    )

    for (
        sample_id,
        predicted_family,
        predicted_share,
        runner_up_family,
        runner_up_share,
        target_family,
        family_margin,
        margin_direction,
        candidate_ids,
    ) in scenarios:
        ranking = [
            {
                "family": predicted_family,
                "count": 0,
                "share_raw": predicted_share,
                "share": predicted_share,
            },
            {
                "family": runner_up_family,
                "count": 0,
                "share_raw": runner_up_share,
                "share": runner_up_share,
            },
        ]
        encoding = SpaCyLegalEncoding(
            document_id=sample_id,
            text="Synthetic packet 002414 adaptive family ambiguity evidence.",
            normalized_text="Synthetic packet 002414 adaptive family ambiguity evidence.",
            tokens=[],
            sentences=[],
            cues=[],
        )
        modal_ir = ModalIRDocument(
            document_id=encoding.document_id,
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{sample_id}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system="packet-002414",
                        symbol=predicted_family,
                        label="packet_002414",
                    ),
                    predicate=ModalIRPredicate(
                        name="packet_002414_predicate",
                        arguments=["actor:agency"],
                        role="packet_002414",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="packet-002414",
                    ),
                ),
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares={
                str(candidate["family"]): float(candidate["share_raw"])
                for candidate in ranking
            },
            predicted_family_source="adaptive_logits",
        )
        policy_pair = f"{predicted_family}->{target_family}"
        explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_"
            f"{margin_direction}_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )

        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["adaptive_margin_direction"] == margin_direction
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == explicit_type
        assert base_ambiguity.metadata["family_margin"] == family_margin
        assert any(
            ambiguity.ambiguity_type == explicit_type
            and ambiguity.candidate_ids == candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["is_explicit_adaptive_ambiguity"] is True
            for ambiguity in ambiguities
        )


def test_refined_pair_balance_promotes_typed_scope_over_generic_frame() -> None:
    counts = {
        "frame": 2.0,
        "conditional_normative": 0.7,
        "temporal": 0.8,
        "epistemic": 0.9,
    }
    signals = {
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_statutory_scope_reference": True,
        "has_condition_or_exception_scope": True,
        "has_conditional_scope_phrase": True,
        "has_temporal_scope": True,
        "has_temporal_status_scope": True,
        "has_epistemic_scope": True,
        "has_epistemic_scope_phrase": True,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["conditional_normative"] > counts["frame"]
    assert counts["temporal"] > counts["frame"]
    assert counts["epistemic"] > counts["frame"]


def test_refined_pair_balance_promotes_definition_conditional_over_frame() -> None:
    counts = {
        "frame": 2.0,
        "conditional_normative": 0.6,
    }
    signals = {
        "has_definition_scope": True,
        "has_condition_or_exception_scope": True,
        "has_conditional_scope_phrase": True,
        "has_purpose_scope_phrase": True,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["conditional_normative"] > counts["frame"]


def test_modal_registry_packet_001117_refines_frame_target_family_pairs() -> None:
    expected_pairs = {
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "temporal"),
    }

    assert set(COMPILER_REFINED_PACKET_001117_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
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


def test_modal_registry_packet_000697_refines_family_cue_policy_pairs() -> None:
    expected_pairs = {
        ("deontic", "doxastic"),
        ("frame", "deontic"),
        ("frame", "epistemic"),
    }

    assert set(COMPILER_AMBIGUITY_PACKET_000697_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_modal_registry_packet_007373_exposes_normative_frame_ambiguity_pairs() -> None:
    expected_pairs = {
        ("conditional_normative", "deontic"),
        ("frame", "conditional_normative"),
    }

    assert set(COMPILER_AMBIGUITY_PACKET_007373_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in priority_signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_refined_pair_balance_promotes_study_report_duty_over_deadline() -> None:
    counts = {
        "deontic": 1.2,
        "temporal": 1.6,
        "frame": 0.3,
    }
    signals = {
        "has_deontic_study_report_duty_scope_phrase": True,
        "has_deontic_cue": True,
        "has_temporal_deadline_cue": True,
        "has_temporal_scope": True,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["deontic"] > counts["temporal"]


def test_refined_pair_balance_promotes_false_claim_intent_over_deontic() -> None:
    counts = {
        "deontic": 2.4,
        "doxastic": 0.8,
        "frame": 0.2,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_cue": True,
        "has_doxastic_scope": True,
        "has_doxastic_cue": True,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["doxastic"] > counts["deontic"]


def test_refined_pair_balance_promotes_implementation_budget_conditions() -> None:
    counts = {
        "conditional_normative": 0.8,
        "deontic": 1.3,
        "frame": 0.7,
    }
    signals = {
        "has_deontic_implementation_budget_scope_phrase": True,
        "has_condition_or_exception_scope": True,
        "has_conditional_scope_phrase": True,
        "has_statutory_scope_reference": True,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["conditional_normative"] > counts["deontic"]


def test_refined_pair_balance_promotes_opinion_findings_over_frame() -> None:
    counts = {
        "epistemic": 0.65,
        "frame": 1.1,
    }
    signals = {
        "has_epistemic_scope": True,
        "has_epistemic_scope_phrase": True,
        "has_frame_context": True,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["epistemic"] > counts["frame"]


def _coarse_uscode_heading_noise_text(section: str, heading: str) -> str:
    noise_tokens = " ".join(chr(ord("a") + (index % 26)) for index in range(160))
    return (
        "U S C title archive register digest taxonomy index chapter crosswalk "
        f"sec {section} {heading} "
        f"{noise_tokens}"
    )


def test_spacy_encoder_compiles_modal_ir_without_downloaded_model() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The agency must make records promptly available to any person.",
        document_id="sample-5-552",
        citation="5 U.S.C. 552",
        source="us_code",
    )

    modal_ir = SpaCyModalIRCompiler().compile(encoding)

    assert encoding.used_fallback_model is True
    assert encoding.tokens
    assert encoding.cues[0].family == "deontic"
    assert modal_ir.metadata["llm_call_count"] == 0
    assert modal_ir.formulas[0].operator.family == "deontic"
    assert "records" in modal_ir.formulas[0].predicate.name


def test_spacy_compiler_extracts_condition_and_exception_slots() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "If the application is complete, the agency must issue written notice unless waived.",
        document_id="sample-condition-exception",
    )

    modal_ir = SpaCyModalIRCompiler().compile(encoding)
    deontic_formula = next(
        formula for formula in modal_ir.formulas if formula.operator.family == "deontic"
    )

    assert "if the application is complete" in deontic_formula.conditions
    assert "unless waived" in deontic_formula.exceptions


def test_spacy_encoder_ignores_calendar_month_may_as_permission_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The Secretary shall make the payment after May 13, 2002, and a producer may request review.",
        document_id="sample-may-date-literal",
    )

    may_cues = [cue for cue in encoding.cues if cue.cue.lower() == "may"]

    assert may_cues
    assert len(may_cues) == 1
    assert may_cues[0].family == "deontic"
    assert any(cue.family == "temporal" and cue.cue.lower() == "after" for cue in encoding.cues)


def test_spacy_encoder_prefers_negated_permission_over_embedded_may() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The civil penalty may not exceed $100 per day.",
        document_id="sample-negated-permission",
    )

    deontic_cues = {
        (cue.symbol, cue.cue.lower()) for cue in encoding.cues if cue.family == "deontic"
    }

    assert ("F", "may not") in deontic_cues
    assert ("P", "may") not in deontic_cues


def test_spacy_encoder_refines_packet_000317_registry_family_cues() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")

    prohibition = encoder.encode(
        "No member of the armed forces may be placed in confinement.",
        document_id="packet-000317-prohibition",
    )
    assert any(
        cue.family == "deontic" and cue.symbol == "F" and cue.cue.lower() == "no member"
        for cue in prohibition.cues
    )

    appropriations = encoder.encode(
        "Amounts available for obligation shall remain available without fiscal year limitation "
        "when determined by the Secretary.",
        document_id="packet-000317-appropriations",
    )
    assert any(
        cue.family == "temporal"
        and cue.cue.lower() == "available without fiscal year limitation"
        for cue in appropriations.cues
    )
    assert any(
        cue.family == "epistemic" and cue.cue.lower() == "determined"
        for cue in appropriations.cues
    )


def test_spacy_encoder_treats_non_deadline_by_as_non_temporal_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The Secretary shall provide notice by the Comptroller.",
        document_id="sample-by-non-temporal",
    )

    assert any(cue.family == "deontic" and cue.cue.lower() == "shall" for cue in encoding.cues)
    assert not any(
        cue.family == "temporal" and cue.cue.lower() == "by"
        for cue in encoding.cues
    )


def test_spacy_encoder_treats_statutory_cross_reference_by_as_non_temporal_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The Secretary shall provide notice by section 8005 of this title.",
        document_id="sample-by-statutory-cross-reference",
    )

    assert any(cue.family == "deontic" and cue.cue.lower() == "shall" for cue in encoding.cues)
    assert not any(
        cue.family == "temporal" and cue.cue.lower() == "by"
        for cue in encoding.cues
    )


def test_spacy_encoder_treats_deadline_by_as_temporal_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The Secretary shall provide notice by January 1, 2030.",
        document_id="sample-by-deadline",
    )

    assert any(
        cue.family == "temporal" and cue.cue.lower() == "by"
        for cue in encoding.cues
    )


def test_spacy_encoder_treats_deadline_by_with_dotted_month_as_temporal_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The Secretary shall provide notice by Oct. 6, 2006.",
        document_id="sample-by-deadline-dotted-month",
    )

    assert any(
        cue.family == "temporal" and cue.cue.lower() == "by"
        for cue in encoding.cues
    )


def test_spacy_encoder_treats_within_department_as_non_temporal_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The Secretary shall designate a team within the Department of Agriculture.",
        document_id="sample-within-department-non-temporal",
    )

    assert any(cue.family == "deontic" and cue.cue.lower() == "shall" for cue in encoding.cues)
    assert not any(
        cue.family == "temporal" and cue.cue.lower() == "within"
        for cue in encoding.cues
    )
    signals = modal_ambiguity_signals(encoding)
    assert signals["has_temporal_within_scope"] is False
    assert signals["has_temporal_scope"] is False


def test_spacy_encoder_treats_within_days_as_temporal_cue_and_scope() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The Secretary shall provide notice within 30 days after review.",
        document_id="sample-within-days-temporal",
    )

    assert any(
        cue.family == "temporal" and cue.cue.lower() == "within"
        for cue in encoding.cues
    )
    signals = modal_ambiguity_signals(encoding)
    assert signals["has_temporal_within_scope"] is True
    assert signals["has_temporal_scope"] is True


def test_spacy_encoder_treats_prior_to_as_temporal_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The filing applies only to records created prior to January 1, 2030.",
        document_id="sample-prior-to-temporal",
    )

    assert any(
        cue.family == "temporal" and cue.cue.lower() == "prior to"
        for cue in encoding.cues
    )


def test_spacy_encoder_detects_editorial_frame_scope_signals() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "Editorial Notes Codification Section 5602 was formerly classified to "
            "section 83 of this title prior to editorial reclassification and "
            "renumbering as this section."
        ),
        document_id="sample-editorial-frame-scope",
    )

    signals = modal_ambiguity_signals(encoding)
    assert signals["has_frame_context"] is True
    assert signals["has_frame_scope_phrase"] is True
    assert signals["has_frame_editorial_scope_phrase"] is True


def test_spacy_encoder_detects_procedural_frame_scope_signals() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "Administrative notice and hearing procedures are established under this section.",
        document_id="sample-procedural-frame-scope",
    )

    signals = modal_ambiguity_signals(encoding)
    assert signals["has_frame_procedural_scope_phrase"] is True
    assert signals["has_frame_context"] is True
    assert signals["has_frame_scope_phrase"] is False


def test_spacy_encoder_detects_of_this_title_as_statutory_scope_reference() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "Section 430f-12 of this title shall apply.",
        document_id="sample-statutory-of-this-title-reference",
    )

    signals = modal_ambiguity_signals(encoding)
    assert signals["has_statutory_scope_reference"] is True
    assert signals["has_deontic_scope"] is True


def test_spacy_encoder_detects_structural_authority_frame_scope_for_jurisdiction_and_executive_authority() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    jurisdiction_encoding = encoder.encode(
        (
            "The United States Court of Federal Claims shall have jurisdiction to "
            "render judgment under this section."
        ),
        document_id="sample-structural-authority-jurisdiction",
    )
    authority_encoding = encoder.encode(
        (
            "Authority of Executive Agencies under this section shall be exercised "
            "in accordance with this title."
        ),
        document_id="sample-structural-authority-executive",
    )

    jurisdiction_signals = modal_ambiguity_signals(jurisdiction_encoding)
    authority_signals = modal_ambiguity_signals(authority_encoding)

    assert jurisdiction_signals["has_frame_structural_authority_scope_phrase"] is True
    assert authority_signals["has_frame_structural_authority_scope_phrase"] is True


def test_spacy_encoder_extracts_rescued_packet_001981_deontic_cues() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "The plan shall conduct research and provide for services. "
            "There are authorized to be appropriated such sums as are necessary. "
            "The Administrator may guarantee bonds and may carry out this section."
        ),
        document_id="packet-001981-rescued-deontic-cues",
    )

    deontic_cues = {
        cue.cue.lower()
        for cue in encoding.cues
        if cue.family == "deontic"
    }

    assert {
        "shall conduct",
        "provide for",
        "there are authorized to be appropriated",
        "may guarantee",
        "may carry out",
    }.issubset(deontic_cues)


def test_spacy_encoder_extracts_packet_000004_statutory_family_cues() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "Sections 5102 and 5124 of this title shall apply to all Indian "
            "tribes. The Secretary shall develop a system and shall consult "
            "with the advisory committee. Members may collect charges and may "
            "present a voucher under such regulations as the Secretary may "
            "prescribe."
        ),
        document_id="packet-000004-family-cues",
    )

    cues_by_family = {}
    for cue in encoding.cues:
        cues_by_family.setdefault(cue.family, set()).add(cue.cue.lower())

    assert {
        "shall apply",
        "shall develop",
        "shall consult",
        "may collect",
        "may present",
    }.issubset(cues_by_family["deontic"])
    assert "under such regulations" in cues_by_family["conditional_normative"]


def test_refined_pair_balance_boosts_frame_for_structural_authority_statutory_scope() -> None:
    counts = {
        "deontic": 2.0,
        "temporal": 1.35,
        "conditional_normative": 1.35,
        "frame": 0.62,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_cue": True,
        "has_temporal_scope": True,
        "has_temporal_status_scope": True,
        "has_calendar_date_scope": True,
        "has_condition_or_exception_scope": True,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_frame_editorial_scope_phrase": True,
        "has_frame_structural_authority_scope_phrase": True,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["frame"] > 0.62


def test_refined_pair_balance_boosts_temporal_runner_up_in_statutory_status_context() -> None:
    counts = {
        "deontic": 1.75,
        "temporal": 1.35,
        "conditional_normative": 0.6,
        "frame": 0.35,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_cue": True,
        "has_deontic_scope_phrase": False,
        "has_temporal_scope": True,
        "has_temporal_status_scope": True,
        "has_calendar_date_scope": True,
        "has_statutory_scope_reference": True,
        "has_condition_or_exception_scope": True,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": False,
        "has_conditional_scope_token": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["temporal"] > 1.35


def test_refined_pair_balance_promotes_conditional_scope_over_generic_frame() -> None:
    counts = {
        "frame": 2.2,
        "conditional_normative": 1.4,
        "deontic": 0.8,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_conditional_scope_phrase": True,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_cue": True,
        "has_frame_editorial_scope_phrase": False,
        "has_definition_scope": False,
        "has_frame_structural_authority_scope_phrase": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["conditional_normative"] > counts["frame"]


def test_refined_pair_balance_promotes_epistemic_scope_over_generic_frame() -> None:
    counts = {
        "frame": 2.2,
        "epistemic": 1.15,
        "conditional_normative": 0.4,
        "deontic": 0.35,
    }
    signals = {
        "has_epistemic_scope": True,
        "has_epistemic_cue": True,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_cue": True,
        "has_frame_editorial_scope_phrase": False,
        "has_definition_scope": False,
        "has_frame_structural_authority_scope_phrase": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["epistemic"] > 1.15
    assert counts["frame"] - counts["epistemic"] <= 0.62


def test_refined_pair_balance_promotes_strong_epistemic_over_statutory_frame() -> None:
    counts = {
        "frame": 2.2,
        "epistemic": 0.45,
        "conditional_normative": 0.4,
        "deontic": 0.35,
    }
    signals = {
        "has_epistemic_scope": True,
        "has_epistemic_cue": True,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_cue": True,
        "has_frame_editorial_scope_phrase": False,
        "has_definition_scope": False,
        "has_frame_structural_authority_scope_phrase": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["epistemic"] > counts["frame"]


def test_refined_pair_balance_promotes_explicit_deontic_scope_over_statutory_frame() -> None:
    counts = {
        "frame": 2.2,
        "deontic": 0.78,
        "conditional_normative": 0.45,
        "temporal": 0.35,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_cue": True,
        "has_deontic_scope_phrase": True,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_cue": True,
        "has_frame_editorial_scope_phrase": False,
        "has_definition_scope": False,
        "has_frame_structural_authority_scope_phrase": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["deontic"] > counts["frame"]


def test_refined_pair_balance_promotes_typed_temporal_status_over_deontic_cues() -> None:
    counts = {
        "deontic": 2.1,
        "temporal": 1.45,
        "frame": 0.7,
        "conditional_normative": 0.35,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_cue": True,
        "has_temporal_scope": True,
        "has_temporal_status_scope": True,
        "has_calendar_date_scope": True,
        "has_temporal_scope_token": True,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_editorial_scope_phrase": False,
        "has_deontic_authorization_scope_phrase": False,
        "has_deontic_report_duty_scope_phrase": False,
        "has_deontic_corporate_powers_scope_phrase": False,
        "has_deontic_citation_authority_scope_phrase": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["temporal"] > counts["deontic"]


def test_refined_pair_balance_promotes_explicit_conditional_over_frame_cues() -> None:
    counts = {
        "frame": 2.35,
        "conditional_normative": 1.05,
        "deontic": 0.8,
        "temporal": 0.4,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_conditional_scope_phrase": False,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_deontic_scope": True,
        "has_definition_scope": False,
        "has_frame_structural_authority_scope_phrase": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["conditional_normative"] > counts["frame"]


def test_refined_pair_balance_promotes_statutory_conditional_over_generic_frame() -> None:
    counts = {
        "frame": 2.45,
        "conditional_normative": 0.72,
        "deontic": 0.65,
        "temporal": 0.4,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_conditional_scope_phrase": False,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_editorial_scope_phrase": False,
        "has_definition_scope": False,
        "has_frame_structural_authority_scope_phrase": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["conditional_normative"] > counts["frame"]


def test_spacy_encoder_promotes_failure_heading_as_conditional_normative_scope() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "26 U.S.C. 4980G - Failure of employer to make comparable Archer "
            "MSAs available. This chapter applies to qualified pension plans "
            "under this title."
        ),
        document_id="packet-002481-failure-heading-conditional-scope",
    )

    signals = modal_ambiguity_signals(encoding)
    counts = _weighted_modal_family_counts(encoding, signals=signals)

    assert signals["has_conditional_scope_phrase"] is True
    assert any(
        cue.family == "conditional_normative"
        and cue.cue.lower() == "failure of"
        for cue in encoding.cues
    )
    assert counts["conditional_normative"] > counts["frame"]


def test_packet_005718_registry_refines_frame_doxastic_temporal_cues() -> None:
    assert tuple(COMPILER_REFINED_PACKET_005718_FAMILY_PAIRS) == (
        ("frame", "doxastic"),
        ("frame", "temporal"),
    )
    for predicted_family, target_family in COMPILER_REFINED_PACKET_005718_FAMILY_PAIRS:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            > 0.0
        )

    extracted_cues = {
        (cue.family, cue.cue.lower())
        for cue in SpaCyLegalEncoder().encode(
            (
                "A return must be filed at such time and in the time and "
                "manner prescribed. A person who knowingly and willfully "
                "makes a false statement has the required intent."
            )
        ).cues
    }
    assert ("temporal", "at such time") in extracted_cues
    assert ("temporal", "time and manner") in extracted_cues
    assert ("doxastic", "knowingly and willfully") in extracted_cues
    assert ("doxastic", "false statement") in extracted_cues


def test_spacy_encoder_treats_bare_knowingly_as_doxastic_mens_rea() -> None:
    encoding = SpaCyLegalEncoder(model_name="definitely_missing_legal_model").encode(
        (
            "Whoever knowingly receives money from an officer of a court "
            "is guilty of embezzlement and shall be fined."
        ),
        document_id="bare-knowingly-mens-rea",
    )
    cues_by_family = {
        (cue.family, cue.cue.lower())
        for cue in encoding.cues
    }
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)
    share_by_family = {
        str(item["family"]): float(item["share_raw"])
        for item in ranking
    }

    assert ("doxastic", "knowingly") in cues_by_family
    assert signals["has_doxastic_cue"] is True
    assert share_by_family["doxastic"] > 0.0


def test_packet_005786_registry_refines_family_cue_policy_pairs() -> None:
    assert tuple(COMPILER_REFINED_PACKET_005786_FAMILY_PAIRS) == (
        ("deontic", "temporal"),
        ("frame", "deontic"),
        ("frame", "frame"),
    )
    for predicted_family, target_family in COMPILER_REFINED_PACKET_005786_FAMILY_PAIRS:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            > 0.0
        )


def test_packet_001002_registry_exposes_frame_deontic_doxastic_ambiguity_policy() -> None:
    expected_pairs = (
        ("frame", "deontic"),
        ("frame", "doxastic"),
    )

    assert COMPILER_AMBIGUITY_PACKET_001002_FAMILY_PAIRS == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in priority_signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_packet_004762_registry_refines_modal_family_cue_pairs() -> None:
    assert tuple(COMPILER_REFINED_PACKET_004762_FAMILY_PAIRS) == (
        ("deontic", "doxastic"),
        ("deontic", "temporal"),
        ("frame", "deontic"),
        ("frame", "temporal"),
    )
    for predicted_family, target_family in COMPILER_REFINED_PACKET_004762_FAMILY_PAIRS:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            >= 0.006
        )


def test_packet_001615_registry_refines_frame_to_typed_family_cues() -> None:
    assert tuple(COMPILER_REFINED_PACKET_001615_FAMILY_PAIRS) == (
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "epistemic"),
    )
    for predicted_family, target_family in COMPILER_REFINED_PACKET_001615_FAMILY_PAIRS:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            >= 0.095
        )


def test_refined_pair_balance_promotes_statutory_deontic_over_generic_frame() -> None:
    counts = {
        "frame": 2.2,
        "deontic": 0.78,
        "conditional_normative": 0.45,
        "temporal": 0.35,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_cue": True,
        "has_deontic_scope_phrase": True,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_editorial_scope_phrase": False,
        "has_definition_scope": False,
        "has_frame_structural_authority_scope_phrase": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["deontic"] > counts["frame"]


def test_refined_pair_balance_promotes_explicit_deontic_over_frame_scaffold() -> None:
    counts = {
        "frame": 2.6,
        "deontic": 1.1,
        "conditional_normative": 0.35,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_cue": True,
        "has_deontic_scope_phrase": False,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_cue": True,
        "has_frame_editorial_scope_phrase": False,
        "has_definition_scope": False,
        "has_frame_structural_authority_scope_phrase": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["deontic"] > counts["frame"]


def test_packet_005575_refined_balance_promotes_doxastic_intent_over_frame() -> None:
    counts = {
        "frame": 2.2,
        "doxastic": 0.4,
        "deontic": 0.8,
        "conditional_normative": 0.35,
    }
    signals = {
        "has_doxastic_scope": True,
        "has_doxastic_cue": True,
        "has_deontic_scope": True,
        "has_deontic_cue": True,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_cue": True,
        "has_frame_editorial_scope_phrase": False,
        "has_definition_scope": False,
        "has_frame_structural_authority_scope_phrase": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["doxastic"] > counts["frame"]


def test_packet_005575_refined_balance_promotes_temporal_status_over_frame() -> None:
    counts = {
        "frame": 2.4,
        "temporal": 0.6,
        "deontic": 0.35,
        "conditional_normative": 0.25,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_cue": True,
        "has_temporal_status_scope": True,
        "has_calendar_date_scope": True,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_cue": True,
        "has_frame_editorial_scope_phrase": False,
        "has_definition_scope": False,
        "has_frame_structural_authority_scope_phrase": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["temporal"] > counts["frame"]


def test_packet_005575_refined_balance_promotes_deontic_over_conditional_scaffold() -> None:
    counts = {
        "conditional_normative": 2.1,
        "deontic": 1.0,
        "frame": 0.6,
        "temporal": 0.35,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_cue": True,
        "has_deontic_scope_phrase": True,
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_editorial_scope_phrase": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["deontic"] > counts["conditional_normative"]


def test_packet_004071_registry_refines_frame_deontic_and_dynamic_self_buffers() -> None:
    assert set(COMPILER_REFINED_PACKET_004071_FAMILY_PAIRS) == {
        ("dynamic", "dynamic"),
        ("frame", "deontic"),
    }
    assert is_compiler_ambiguity_policy_pair("frame", "deontic")
    assert compiler_refined_modal_family_cue_margin_buffer("frame", "deontic") >= 0.0015
    assert compiler_refined_modal_family_cue_margin_buffer("dynamic", "dynamic") >= 0.02
    assert (
        compiler_weak_typed_self_family_cue_margin_buffer("dynamic", "dynamic")
        > compiler_weak_typed_self_family_cue_margin_buffer("deontic", "deontic")
    )


def test_packet_004348_registry_refines_modal_family_cue_pairs() -> None:
    assert set(COMPILER_REFINED_PACKET_004348_FAMILY_PAIRS) == {
        ("deontic", "temporal"),
        ("frame", "deontic"),
        ("frame", "temporal"),
        ("temporal", "deontic"),
    }
    for predicted_family, target_family in COMPILER_REFINED_PACKET_004348_FAMILY_PAIRS:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            > 0.0
        )


def test_packet_000399_registry_refines_modal_family_cue_pairs() -> None:
    expected_pairs = {
        ("deontic", "conditional_normative"),
        ("deontic", "epistemic"),
        ("frame", "deontic"),
        ("frame", "temporal"),
    }

    assert set(COMPILER_REFINED_PACKET_000399_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            > 0.0
        )


def test_packet_000122_registry_refines_current_family_cue_pairs() -> None:
    expected_pairs = {
        ("deontic", "conditional_normative"),
        ("deontic", "deontic"),
        ("deontic", "temporal"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "temporal"),
        ("temporal", "deontic"),
        ("temporal", "frame"),
    }

    assert expected_pairs.issubset(set(COMPILER_REFINED_PACKET_000122_FAMILY_PAIRS))
    for predicted_family, target_family in expected_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            > 0.0
        )
def test_packet_000205_registry_exposes_compiler_ambiguity_pairs() -> None:
    assert ("frame", "temporal") in COMPILER_AMBIGUITY_PACKET_000205_FAMILY_PAIRS
    assert ("temporal", "deontic") in COMPILER_AMBIGUITY_PACKET_000205_FAMILY_PAIRS
    assert is_compiler_ambiguity_policy_pair("frame", "temporal")
    assert is_compiler_ambiguity_policy_pair("temporal", "deontic")


def test_temporal_deontic_ambiguity_marks_packet_000205_policy_bundle() -> None:
    encoder = SpaCyLegalEncoder(model_name="blank")
    encoding = encoder.encode(
        "The Secretary shall act within 30 days.",
        document_id="packet-000205-temporal-deontic-policy",
    )
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
    ambiguity = compiler._temporal_deontic_scope_family_ambiguities(
        encoding,
        ranking=[
            {"family": "temporal", "share": 0.62, "share_raw": 0.62},
            {"family": "deontic", "share": 0.38, "share_raw": 0.38},
        ],
        family_shares={"temporal": 0.62, "deontic": 0.38},
    )

    assert len(ambiguity) == 1
    assert isinstance(ambiguity[0], ModalCompilationAmbiguity)
    assert ambiguity[0].metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert ambiguity[0].metadata["compiler_ambiguity_policy_pair"] == "temporal->deontic"
    assert ambiguity[0].metadata["is_compiler_ambiguity_bundle_pair"] is True
def test_packet_004828_registry_exposes_modal_ambiguity_pairs() -> None:
    assert set(COMPILER_AMBIGUITY_PACKET_004828_FAMILY_PAIRS) == {
        ("deontic", "temporal"),
        ("dynamic", "dynamic"),
        ("frame", "deontic"),
    }
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_004828_FAMILY_PAIRS:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)


def test_refined_pair_balance_promotes_temporal_for_dated_status_history_tail() -> None:
    counts = {
        "frame": 1.2,
        "temporal": 1.0,
        "deontic": 0.0,
        "conditional_normative": 0.0,
    }
    signals = {
        "has_calendar_date_scope": True,
        "has_dated_status_legislative_history_scope": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_temporal_scope": True,
        "has_temporal_status_scope": True,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["temporal"] > counts["frame"]


def test_spacy_encoder_promotes_temporal_for_dated_repealed_history_tail() -> None:
    encoder = SpaCyLegalEncoder(model_name="blank")
    encoding = encoder.encode(
        (
            "§833. Repealed. Pub. L. 104-201, div. A, title XVI, "
            "§1633(b)(2), Sept. 23, 1996, 110 Stat. 2751 Section, "
            "act Sept. 23, 1950, ch. 1024, title III, §303, as added "
            "Mar. 26, 1964, Pub. L. 88-290, 78 Stat. 169; amended "
            "Oct. 27, 1972, Pub. L. 92-544, 86 Stat. 1115."
        ),
        document_id="packet-004348-dated-repealed-history-tail",
    )

    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert signals["has_dated_status_legislative_history_scope"] is True
    assert signals["has_temporal_status_scope"] is True
    assert ranking[0]["family"] == "temporal"


def test_refined_pair_balance_promotes_deontic_over_temporal_status_scaffold() -> None:
    counts = {
        "temporal": 2.4,
        "deontic": 1.2,
        "conditional_normative": 0.5,
        "frame": 0.35,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_cue": True,
        "has_deontic_scope_phrase": True,
        "has_temporal_scope": True,
        "has_temporal_status_scope": True,
        "has_statutory_scope_reference": True,
        "has_frame_editorial_scope_phrase": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["deontic"] > counts["temporal"]


def test_spacy_encoder_promotes_deontic_over_temporal_period_scaffold() -> None:
    encoder = SpaCyLegalEncoder(model_name="blank")
    encoding = encoder.encode(
        (
            "Temporary increase. The amount payable under this section for a "
            "period beginning on the date of enactment and ending on September "
            "30, 2025, shall be increased."
        ),
        document_id="packet-003061-temporal-deontic-period-scaffold",
    )

    ranking = ranked_modal_families(encoding)
    signals = modal_ambiguity_signals(encoding)

    assert any(
        cue.family == "deontic" and cue.cue.lower() == "shall"
        for cue in encoding.cues
    )
    assert signals["has_temporal_scope"] is True
    assert signals["has_deontic_cue"] is True
    assert ranking[0]["family"] == "deontic"


def test_refined_pair_balance_preserves_alethic_scope_under_temporal_dominance() -> None:
    counts = {
        "temporal": 2.25,
        "alethic": 0.0,
        "deontic": 1.0,
        "frame": 0.35,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_status_scope": True,
        "has_alethic_scope": True,
        "has_alethic_scope_phrase": True,
        "has_deontic_scope": True,
        "has_deontic_cue": True,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["alethic"] >= 1.0


def test_spacy_decoder_promotes_frame_logits_over_hybrid_for_editorial_scope_text() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="2",
        section="5602",
        text=(
            "Editorial Notes Codification Section 5602 was formerly classified to "
            "section 83 of this title prior to editorial reclassification and "
            "renumbering as this section."
        ),
    )

    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("frame", "hybrid", "temporal"),
    )

    assert logits["frame"] > logits["hybrid"]


def test_spacy_decoder_promotes_frame_logits_over_temporal_for_editorial_scope_text() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="2",
        section="5602",
        text=(
            "Editorial Notes Codification Section 5602 was formerly classified to "
            "section 83 of this title after editorial reclassification and "
            "renumbering as this section."
        ),
    )

    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("frame", "hybrid", "temporal"),
    )

    assert logits["frame"] > logits["temporal"]


def test_spacy_decoder_debiases_editorial_frame_logits_when_deontic_scope_competes_without_frame_cues() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="8",
        section="606",
        text="Section transferred to section 1421l of this title shall apply.",
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)

    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("frame", "deontic", "temporal"),
    )

    assert not any(cue.family == "frame" for cue in encoding.cues)
    assert signals["has_frame_editorial_scope_phrase"] is True
    assert signals["has_statutory_scope_reference"] is True
    assert signals["has_deontic_cue"] is True
    assert logits["deontic"] > logits["frame"]


def test_spacy_decoder_debiases_editorial_frame_logits_when_temporal_scope_competes_without_frame_cues() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="42",
        section="603a",
        text=(
            "Section transferred to section 1421l of this title applies "
            "beginning on January 1, 2030."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)

    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("frame", "temporal", "deontic"),
    )

    assert not any(cue.family == "frame" for cue in encoding.cues)
    assert signals["has_frame_editorial_scope_phrase"] is True
    assert signals["has_statutory_scope_reference"] is True
    assert signals["has_temporal_scope"] is True
    assert logits["temporal"] > logits["frame"]


def test_spacy_encoder_treats_repealed_status_as_temporal_scope_signal() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline_sample = build_us_code_sample(
        title="45",
        section="44 to 46",
        text="Secs. 44 to 46.",
    )
    repealed_sample = build_us_code_sample(
        title="45",
        section="44 to 46",
        text="Secs. 44 to 46. Repealed.",
    )

    baseline_encoding = codec.encode_sample(baseline_sample)
    repealed_encoding = codec.encode_sample(repealed_sample)
    baseline_signals = modal_ambiguity_signals(baseline_encoding)
    repealed_signals = modal_ambiguity_signals(repealed_encoding)
    baseline_logits = codec.family_logits_for_sample(
        baseline_sample,
        modal_families=("frame", "temporal"),
    )
    repealed_logits = codec.family_logits_for_sample(
        repealed_sample,
        modal_families=("frame", "temporal"),
    )

    assert baseline_signals["has_temporal_scope"] is False
    assert baseline_signals["has_temporal_status_scope"] is False
    assert repealed_signals["has_temporal_scope"] is True
    assert repealed_signals["has_temporal_status_scope"] is True
    assert repealed_signals["has_frame_scope_phrase"] is True
    assert repealed_signals["has_statutory_status_frame_scope"] is True
    assert repealed_logits["temporal"] > baseline_logits["temporal"]


def test_spacy_encoder_marks_repealed_statutory_sections_as_status_frame_scope() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="43",
        section="356.",
        text=(
            "Sec. 356. Repealed. Pub. L. 94-579, title VII, Sec. 703(a), "
            "Oct. 21, 1976, 90 Stat. 2789 Section, act Sept. 22, 1922, "
            "extended time for development of underground water supplies with "
            "reclamation grants."
        ),
    )

    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)

    assert signals["has_temporal_status_scope"] is True
    assert signals["has_frame_context"] is True
    assert signals["has_statutory_status_frame_scope"] is True


def test_spacy_encoder_extracts_packet_000004_registry_authority_cues() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    repealed_encoding = encoder.encode(
        (
            "Sec. 763a-2 - Repealed. Pub. L. 117-263, div. K, "
            "title CXVIII, Sec. 11808(a)(14), Dec. 23, 2022."
        ),
        document_id="packet-000004-repealed-status",
    )
    authority_encoding = encoder.encode(
        (
            "Transfer of title; power development. The Secretary may, in his "
            "discretion, when repayments shall have been made, transfer the "
            "title to said canal and appurtenant structures to districts "
            "having a beneficial interest. The districts shall have the "
            "privilege at any time of using such power possibilities as may "
            "exist, until they shall have paid the required costs."
        ),
        document_id="packet-000004-title-transfer-authority",
    )

    repealed_ranking = ranked_modal_families(repealed_encoding)
    authority_ranking = ranked_modal_families(authority_encoding)
    authority_rank_by_family = {
        item["family"]: item["share_raw"] for item in authority_ranking
    }

    assert not repealed_encoding.cues
    assert repealed_ranking[0]["family"] == "frame"
    assert any(
        cue.family == "frame" and cue.cue.lower() == "transfer of title"
        for cue in authority_encoding.cues
    )
    assert any(
        cue.family == "frame" and cue.cue.lower() == "power development"
        for cue in authority_encoding.cues
    )
    assert authority_rank_by_family["frame"] > 0.0
    assert authority_rank_by_family["deontic"] > authority_rank_by_family["frame"]


def test_spacy_encoder_marks_vacant_sections_as_frame_status_scope() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="38",
        section="3475",
        text=(
            "Sec. 3475 - Vacant From the U.S. Government Publishing Office. "
            "[§3475. Vacant] Editorial Notes Codification Prior section was repealed."
        ),
    )

    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert signals["has_vacant_section_scope"] is True
    assert signals["has_frame_context"] is True
    assert signals["has_statutory_status_frame_scope"] is True
    assert ranking[0]["family"] == "frame"


def test_spacy_encoder_keeps_editorial_effective_date_status_temporal() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="25",
        section="1300m-5",
        text=(
            "Sec. 1300m-5 - Omitted From the U.S. Government Publishing Office. "
            "Editorial Notes Codification Section omitted effective date of repeal "
            "after enactment."
        ),
    )

    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)
    rank_by_family = {item["family"]: item["share_raw"] for item in ranking}

    assert signals["has_frame_editorial_scope_phrase"] is True
    assert signals["has_temporal_status_scope"] is True
    assert ranking[0]["family"] == "temporal"
    assert rank_by_family["temporal"] > rank_by_family["frame"]


def test_spacy_encoder_treats_editorial_required_as_non_deontic_scope() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="22",
        section="277d-39",
        text=(
            "Section was required and later repealed. Editorial Notes Codification "
            "Section was formerly classified to section 83 of this title prior to "
            "editorial reclassification and renumbering."
        ),
    )

    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)

    assert not any(
        cue.family == "deontic" and cue.cue.lower() == "required"
        for cue in encoding.cues
    )
    assert signals["has_frame_editorial_scope_phrase"] is True
    assert signals["has_temporal_status_scope"] is True
    assert signals["has_deontic_scope"] is False


def test_spacy_encoder_treats_repealed_required_submission_as_history_scope() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="42",
        section="1411d.",
        text=(
            "§1411d. Repealed. Pub. L. 93-383, title II, §204, Aug. 22, "
            "1974, 88 Stat. 668 Section, act Aug. 2, 1954, ch. 649, title "
            "VIII, §815, 68 Stat. 647, required submission of specifications "
            "by applicants prior to award of any contract for construction of "
            "a project."
        ),
    )

    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(
        cue.family == "deontic" and cue.cue.lower() == "required"
        for cue in encoding.cues
    )
    assert signals["has_statutory_status_frame_scope"] is True
    assert signals["has_deontic_scope"] is False
    assert ranking[0]["family"] in {"frame", "temporal"}


def test_directional_backfill_treats_temporal_status_scope_as_strong_temporal_signal() -> None:
    counts = {
        "deontic": 1.0,
        "temporal": 0.0,
        "frame": 0.0,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_status_scope": True,
        "has_frame_context": True,
    }

    _apply_directional_modal_family_pair_backfill(counts, signals)
    assert counts["temporal"] >= 0.18


def test_spacy_encoder_treats_extended_over_status_as_temporal_scope_signal() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline_sample = build_us_code_sample(
        title="43",
        section="647",
        text="The provisions of this title shall apply to these lands.",
    )
    extended_sample = build_us_code_sample(
        title="43",
        section="647",
        text=(
            "The provisions of this title are extended over these lands and "
            "shall apply."
        ),
    )

    baseline_encoding = codec.encode_sample(baseline_sample)
    extended_encoding = codec.encode_sample(extended_sample)
    baseline_signals = modal_ambiguity_signals(baseline_encoding)
    extended_signals = modal_ambiguity_signals(extended_encoding)
    baseline_logits = codec.family_logits_for_sample(
        baseline_sample,
        modal_families=("deontic", "temporal", "frame"),
    )
    extended_logits = codec.family_logits_for_sample(
        extended_sample,
        modal_families=("deontic", "temporal", "frame"),
    )

    assert baseline_signals["has_temporal_scope"] is False
    assert baseline_signals["has_temporal_status_scope"] is False
    assert extended_signals["has_temporal_scope"] is True
    assert extended_signals["has_temporal_scope_phrase"] is True
    assert extended_signals["has_temporal_status_scope"] is True
    assert extended_logits["temporal"] > baseline_logits["temporal"]


def test_spacy_codec_debiases_generic_frame_share_for_repealed_statutory_scope() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="42",
        section="2308",
        text="Authority and jurisdiction under this section are repealed.",
    )

    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert signals["has_statutory_scope_reference"] is True
    assert signals["has_temporal_scope"] is True
    assert signals["has_temporal_status_scope"] is True
    assert any(item["family"] == "temporal" for item in ranking)
    temporal_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "temporal"
    )
    frame_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "frame"
    )
    assert temporal_share > 0.3
    assert (frame_share - temporal_share) <= 0.05


def test_spacy_codec_debiases_generic_frame_cues_when_deontic_force_is_present() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="42",
        section="247b",
        text=(
            "Authority under this section and jurisdiction under this chapter "
            "shall apply."
        ),
    )

    ranking = ranked_modal_families(codec.encode_sample(sample))

    assert ranking[0]["family"] == "deontic"
    assert any(item["family"] == "frame" and item["count"] >= 1 for item in ranking)
    deontic_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "deontic"
    )
    frame_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "frame"
    )
    assert deontic_share > frame_share


def test_spacy_codec_reinforces_statutory_structural_frame_cues_without_erasing_deontic_force() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The corporation may not issue stock. A director or officer may not "
        "receive a dividend."
    )

    ranking = ranked_modal_families(encoding)

    assert any(cue.cue == "corporation" and cue.family == "frame" for cue in encoding.cues)
    assert any(
        cue.cue == "director or officer" and cue.family == "frame"
        for cue in encoding.cues
    )
    assert ranking[0]["family"] == "deontic"
    frame_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "frame"
    )
    assert frame_share > 0.3


def test_spacy_decoder_debiases_generic_frame_logits_when_deontic_force_is_present() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="42",
        section="1395w",
        text=(
            "Authority under this section and jurisdiction under this chapter "
            "shall apply."
        ),
    )

    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("deontic", "frame", "temporal"),
    )

    assert logits["deontic"] > logits["frame"]


def test_spacy_decoder_debiases_generic_frame_logits_when_conditional_scope_is_present() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="43",
        section="1656",
        text="Authority under this chapter applies pursuant to subsection (b).",
    )

    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("frame", "conditional_normative", "deontic"),
    )

    assert logits["conditional_normative"] > logits["frame"]


def test_spacy_decoder_debiases_generic_frame_logits_when_temporal_scope_is_present() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="42",
        section="321d",
        text=(
            "Authority under this chapter applies for the period beginning on "
            "January 1, 2030 and ending on December 31, 2030."
        ),
    )

    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("frame", "temporal", "deontic"),
    )

    assert logits["temporal"] > logits["frame"]


def test_spacy_decoder_strengthens_conditional_scope_boost_for_statutory_frame_context() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="43",
        section="1656a",
        text="As provided in subsection (b), liability applies.",
    )
    competing = build_us_code_sample(
        title="43",
        section="1656b",
        text="Authority under this section applies as provided in subsection (b).",
    )

    baseline_logits = codec.family_logits_for_sample(
        baseline,
        modal_families=("conditional_normative", "frame", "deontic"),
    )
    competing_logits = codec.family_logits_for_sample(
        competing,
        modal_families=("conditional_normative", "frame", "deontic"),
    )

    assert competing_logits["conditional_normative"] > baseline_logits["conditional_normative"]


def test_spacy_decoder_prefers_conditional_over_frame_for_statutory_deontic_scope_without_frame_cues() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="20",
        section="9151a",
        text="The agency shall issue notice as provided in subsection (b).",
    )

    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("conditional_normative", "frame", "deontic"),
    )

    assert logits["conditional_normative"] > logits["frame"]


def test_spacy_decoder_strengthens_deontic_scope_boost_for_statutory_frame_context() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="16",
        section="403h-10a",
        text="Liability for noncompliance applies.",
    )
    competing = build_us_code_sample(
        title="16",
        section="403h-10b",
        text="Authority under this section imposes liability for noncompliance.",
    )

    baseline_logits = codec.family_logits_for_sample(
        baseline,
        modal_families=("deontic", "frame", "temporal"),
    )
    competing_logits = codec.family_logits_for_sample(
        competing,
        modal_families=("deontic", "frame", "temporal"),
    )

    assert competing_logits["deontic"] > baseline_logits["deontic"]


def test_spacy_decoder_strengthens_deontic_scope_boost_for_temporal_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="29",
        section="2861a",
        text="Liability for noncompliance applies.",
    )
    competing = build_us_code_sample(
        title="29",
        section="2861b",
        text="Not later than January 1, 2030, liability for noncompliance applies.",
    )

    baseline_logits = codec.family_logits_for_sample(
        baseline,
        modal_families=("deontic", "temporal", "frame"),
    )
    competing_logits = codec.family_logits_for_sample(
        competing,
        modal_families=("deontic", "temporal", "frame"),
    )

    assert competing_logits["deontic"] > baseline_logits["deontic"]


def test_spacy_decoder_strengthens_temporal_logits_for_strong_temporal_scope_with_deontic_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="29",
        section="2861c",
        text="Within 90 days, liability for noncompliance applies.",
    )
    competing = build_us_code_sample(
        title="29",
        section="2861d",
        text=(
            "No later than January 1, 2030, liability for noncompliance applies "
            "within 90 days."
        ),
    )

    baseline_logits = codec.family_logits_for_sample(
        baseline,
        modal_families=("deontic", "temporal", "frame"),
    )
    competing_logits = codec.family_logits_for_sample(
        competing,
        modal_families=("deontic", "temporal", "frame"),
    )

    assert competing_logits["temporal"] > baseline_logits["temporal"]


def test_spacy_decoder_strengthens_deontic_scope_boost_for_alethic_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="28",
        section="1a",
        text="Liability for noncompliance applies.",
    )
    competing = build_us_code_sample(
        title="28",
        section="1b",
        text="It is possible that liability for noncompliance applies.",
    )

    baseline_logits = codec.family_logits_for_sample(
        baseline,
        modal_families=("deontic", "alethic", "frame"),
    )
    competing_logits = codec.family_logits_for_sample(
        competing,
        modal_families=("deontic", "alethic", "frame"),
    )

    assert competing_logits["deontic"] > baseline_logits["deontic"]


def test_spacy_decoder_strengthens_deontic_scope_boost_for_alethic_competition_with_deontic_phrase() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="28",
        section="1aa",
        text="It is possible and necessary that the filing proceeds.",
    )
    competing = build_us_code_sample(
        title="28",
        section="1ab",
        text=(
            "It is possible and necessary that the agency is under an obligation "
            "to file notice."
        ),
    )

    baseline_logits = codec.family_logits_for_sample(
        baseline,
        modal_families=("deontic", "alethic", "frame"),
    )
    competing_logits = codec.family_logits_for_sample(
        competing,
        modal_families=("deontic", "alethic", "frame"),
    )

    assert competing_logits["deontic"] > baseline_logits["deontic"]


def test_spacy_decoder_soft_caps_repeated_alethic_logits_for_deontic_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="28",
        section="1c",
        text=(
            "It is possible and necessary and impossible that the filing proceeds."
        ),
    )
    competing = build_us_code_sample(
        title="28",
        section="1d",
        text=(
            "It is possible and necessary and impossible that the agency is under "
            "an obligation to file notice."
        ),
    )

    baseline_logits = codec.family_logits_for_sample(
        baseline,
        modal_families=("deontic", "alethic", "frame"),
    )
    competing_logits = codec.family_logits_for_sample(
        competing,
        modal_families=("deontic", "alethic", "frame"),
    )

    assert competing_logits["alethic"] < baseline_logits["alethic"]
    assert competing_logits["deontic"] > baseline_logits["deontic"]


def test_spacy_decoder_soft_caps_repeated_alethic_logits_for_epistemic_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="28",
        section="1e",
        text=(
            "It is possible and necessary and impossible that the filing proceeds."
        ),
    )
    competing = build_us_code_sample(
        title="28",
        section="1f",
        text=(
            "It is possible and necessary and impossible that the agency has reason "
            "to believe the filing proceeds."
        ),
    )

    baseline_logits = codec.family_logits_for_sample(
        baseline,
        modal_families=("epistemic", "alethic", "frame"),
    )
    competing_logits = codec.family_logits_for_sample(
        competing,
        modal_families=("epistemic", "alethic", "frame"),
    )

    assert competing_logits["alethic"] < baseline_logits["alethic"]
    assert competing_logits["epistemic"] > baseline_logits["epistemic"]


def test_spacy_codec_backfills_conditional_and_epistemic_shares_for_alethic_scope_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="28",
        section="1g",
        text=(
            "It is possible and necessary and impossible that the filing proceeds."
        ),
    )
    conditional_competing = build_us_code_sample(
        title="28",
        section="1h",
        text=(
            "When designated, it is possible and necessary and impossible that the "
            "filing proceeds."
        ),
    )
    epistemic_competing = build_us_code_sample(
        title="28",
        section="1i",
        text=(
            "It is possible and necessary and impossible that a finding that the "
            "filing proceeds is recorded."
        ),
    )

    baseline_ranking = ranked_modal_families(codec.encode_sample(baseline))
    conditional_ranking = ranked_modal_families(codec.encode_sample(conditional_competing))
    epistemic_ranking = ranked_modal_families(codec.encode_sample(epistemic_competing))

    def _share(ranking: list[dict[str, float]], family: str) -> float:
        for item in ranking:
            if item["family"] == family:
                return float(item["share"])
        return 0.0

    baseline_conditional_share = _share(baseline_ranking, "conditional_normative")
    competing_conditional_share = _share(conditional_ranking, "conditional_normative")
    baseline_epistemic_share = _share(baseline_ranking, "epistemic")
    competing_epistemic_share = _share(epistemic_ranking, "epistemic")

    assert competing_conditional_share > baseline_conditional_share
    assert competing_conditional_share > 0.0
    assert competing_epistemic_share > baseline_epistemic_share
    assert competing_epistemic_share > 0.0


def test_spacy_codec_backfills_deontic_share_for_alethic_scope_with_deontic_phrase() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="28",
        section="1j",
        text=(
            "It is possible and necessary and impossible that the filing proceeds."
        ),
    )
    competing = build_us_code_sample(
        title="28",
        section="1k",
        text=(
            "It is possible and necessary and impossible that the agency is under "
            "an obligation to provide notice."
        ),
    )

    baseline_ranking = ranked_modal_families(codec.encode_sample(baseline))
    competing_encoding = codec.encode_sample(competing)
    competing_ranking = ranked_modal_families(competing_encoding)
    competing_signals = modal_ambiguity_signals(competing_encoding)

    def _share(ranking: list[dict[str, float]], family: str) -> float:
        for item in ranking:
            if item["family"] == family:
                return float(item["share"])
        return 0.0

    baseline_deontic_share = _share(baseline_ranking, "deontic")
    competing_deontic_share = _share(competing_ranking, "deontic")

    assert competing_signals["has_deontic_scope"] is True
    assert competing_signals["has_deontic_scope_phrase"] is True
    assert competing_deontic_share > baseline_deontic_share
    assert competing_deontic_share > 0.0


def test_spacy_codec_backfills_temporal_share_for_generic_frame_only_scope() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="43",
        section="2451",
        text="The authority applies before each annual review deadline.",
    )

    ranking = ranked_modal_families(codec.encode_sample(sample))

    assert ranking[0]["family"] == "frame"
    temporal_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "temporal"
    )
    frame_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "frame"
    )
    assert temporal_share > 0.0
    assert frame_share > temporal_share


def test_spacy_codec_backfills_strong_temporal_share_for_generic_frame_scope_with_calendar_date() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="43",
        section="2451a",
        text="The authority takes effect on January 1, 2030.",
    )

    ranking = ranked_modal_families(codec.encode_sample(sample))
    frame_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "frame"
    )
    temporal_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "temporal"
    )

    assert ranking[0]["family"] == "temporal"
    assert temporal_share > frame_share


def test_spacy_codec_backfills_conditional_share_for_generic_frame_only_scope() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="25",
        section="5601",
        text="This authority applies as provided in subsection (b).",
    )

    ranking = ranked_modal_families(codec.encode_sample(sample))

    assert ranking[0]["family"] == "conditional_normative"
    conditional_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "conditional_normative"
    )
    frame_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "frame"
    )
    assert conditional_share > 0.0
    assert conditional_share > frame_share


def test_spacy_codec_backfills_deontic_share_for_generic_frame_only_scope() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="18",
        section="336",
        text="This authority states a prohibition on denial of access.",
    )

    ranking = ranked_modal_families(codec.encode_sample(sample))

    assert ranking[0]["family"] == "frame"
    deontic_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "deontic"
    )
    frame_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "frame"
    )
    assert deontic_share > 0.0
    assert frame_share > deontic_share


def test_spacy_codec_prioritizes_deontic_share_for_generic_frame_statutory_scope_with_strong_deontic_phrase() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="18",
        section="336a",
        text="Authority under this section imposes liability for noncompliance.",
    )

    ranking = ranked_modal_families(codec.encode_sample(sample))

    assert ranking[0]["family"] == "deontic"
    deontic_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "deontic"
    )
    frame_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "frame"
    )
    assert deontic_share > frame_share


def test_spacy_codec_prioritizes_deontic_share_for_compensation_and_privilege_sections() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    cases = (
        build_us_code_sample(
            title="29",
            section="2634",
            text=(
                "Sec. 2634 - Compensation. Members shall be entitled to "
                "compensation and travel reimbursement under this section."
            ),
        ),
        build_us_code_sample(
            title="26",
            section="1501",
            text=(
                "Sec. 1501 - Privilege to file consolidated returns. "
                "Authority under this section provides that an affiliated "
                "group shall have the privilege of filing a consolidated "
                "return under regulations prescribed by the Secretary."
            ),
        ),
    )

    for sample in cases:
        ranking = ranked_modal_families(codec.encode_sample(sample))

        assert ranking[0]["family"] == "deontic"
        shares = {str(item["family"]): float(item["share"]) for item in ranking}
        assert shares["deontic"] > shares.get("frame", 0.0)


def test_spacy_codec_prioritizes_temporal_share_for_generic_frame_statutory_scope_with_strong_temporal_scope_phrase() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="43",
        section="2451b",
        text=(
            "Authority under this section applies for the period beginning on "
            "January 1, 2030."
        ),
    )
    encoding = codec.encode_sample(sample)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "temporal" for cue in encoding.cues)
    assert ranking[0]["family"] == "temporal"
    temporal_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "temporal"
    )
    frame_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "frame"
    )
    assert temporal_share > frame_share


def test_spacy_decoder_debiases_generic_frame_logits_for_subject_only_to_scope() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="25",
        section="967b",
        text="Authority over the lands is subject only to subsection (b).",
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)

    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("frame", "conditional_normative", "temporal"),
    )

    assert signals["has_condition_or_exception_scope"] is True
    assert logits["conditional_normative"] > logits["frame"]


def test_spacy_decoder_debiases_generic_frame_logits_for_while_pending_scope() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="43",
        section="156",
        text="Authority over the lands remains in force while pending adjudication.",
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)

    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("frame", "temporal", "conditional_normative"),
    )

    assert signals["has_temporal_scope"] is True
    assert logits["temporal"] > logits["frame"]


def test_spacy_decoder_debiases_generic_frame_logits_when_deontic_scope_phrase_is_present() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="18",
        section="930",
        text="Authority is under an obligation to provide notice.",
    )

    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("frame", "deontic", "temporal"),
    )

    assert logits["deontic"] > logits["frame"]


def test_spacy_decoder_debiases_generic_frame_logits_in_editorial_scope_with_deontic_cue() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="12",
        section="1822b",
        text="Authority and jurisdiction in this former section apply.",
    )
    competing = build_us_code_sample(
        title="12",
        section="1822c",
        text="Authority and jurisdiction in this former section shall apply.",
    )

    baseline_logits = codec.family_logits_for_sample(
        baseline,
        modal_families=("frame", "deontic", "temporal"),
    )
    competing_logits = codec.family_logits_for_sample(
        competing,
        modal_families=("frame", "deontic", "temporal"),
    )

    assert competing_logits["frame"] < baseline_logits["frame"]
    assert competing_logits["deontic"] > baseline_logits["deontic"]


def test_spacy_codec_debiases_relational_frame_cues_when_deontic_force_is_present() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="5",
        section="702",
        text=(
            "The program is administered by the Secretary under this section "
            "and shall provide notice."
        ),
    )

    ranking = ranked_modal_families(codec.encode_sample(sample))
    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("deontic", "frame", "temporal"),
    )

    assert ranking[0]["family"] == "deontic"
    assert logits["deontic"] > logits["frame"]


def test_spacy_decoder_debiases_relational_frame_cues_when_temporal_scope_is_present() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="42",
        section="5121",
        text=(
            "The program is administered by the Secretary for the period beginning on "
            "January 1, 2030 and ending on December 31, 2030."
        ),
    )

    ranking = ranked_modal_families(codec.encode_sample(sample))
    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("frame", "temporal", "deontic"),
    )

    assert ranking[0]["family"] == "temporal"
    assert logits["temporal"] > logits["frame"]


def test_spacy_decoder_debiases_generic_frame_logits_when_epistemic_cues_are_present() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="20",
        section="80e",
        text=(
            "Authority under this chapter finds that the report is false."
        ),
    )

    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("frame", "epistemic", "deontic"),
    )

    assert logits["epistemic"] > logits["frame"]


def test_spacy_decoder_debiases_generic_frame_logits_when_epistemic_scope_is_present_without_epistemic_cues() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="20",
        section="80f",
        text=(
            "Authority under this section follows a formal finding that the applicant "
            "concealed material facts."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)

    assert not any(cue.family == "epistemic" for cue in encoding.cues)
    assert signals["has_epistemic_scope"] is True
    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("frame", "epistemic", "deontic"),
    )

    assert logits["epistemic"] > logits["frame"]


def test_spacy_decoder_boosts_temporal_logits_from_scope_without_temporal_cues() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="47",
        section="219",
        text="The agency shall provide written notice before each annual review deadline.",
    )
    encoding = codec.encode_sample(sample)

    assert not any(cue.family == "temporal" for cue in encoding.cues)
    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("deontic", "temporal", "frame"),
    )

    assert logits["deontic"] > logits["temporal"]
    assert logits["temporal"] > -0.25


def test_spacy_decoder_boosts_dynamic_logits_from_scope_without_dynamic_cues() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="5",
        section="6339",
        text="The agency shall file the report.",
    )
    encoding = codec.encode_sample(sample)

    assert not any(cue.family == "dynamic" for cue in encoding.cues)
    signals = modal_ambiguity_signals(encoding)
    assert signals["has_dynamic_scope"] is True
    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("deontic", "dynamic", "frame"),
    )

    assert logits["dynamic"] > -0.25


def test_spacy_decoder_soft_caps_repeated_deontic_logits_for_temporal_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="47",
        section="220",
        text="Vendor shall and must and shall and must submit reports.",
    )
    competing = build_us_code_sample(
        title="47",
        section="221",
        text=(
            "Vendor shall and must and shall and must submit reports "
            "before each annual review deadline."
        ),
    )

    baseline_logits = codec.family_logits_for_sample(
        baseline,
        modal_families=("deontic", "temporal", "frame"),
    )
    competing_logits = codec.family_logits_for_sample(
        competing,
        modal_families=("deontic", "temporal", "frame"),
    )

    assert competing_logits["deontic"] < baseline_logits["deontic"]
    assert competing_logits["temporal"] > -0.25


def test_spacy_decoder_soft_caps_repeated_deontic_logits_for_frame_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="10",
        section="1029",
        text="Vendor shall and must and shall and must submit reports.",
    )
    competing = build_us_code_sample(
        title="10",
        section="1030",
        text=(
            "Vendor shall and must and shall and must submit reports "
            "under this section."
        ),
    )

    baseline_logits = codec.family_logits_for_sample(
        baseline,
        modal_families=("deontic", "frame", "temporal"),
    )
    competing_logits = codec.family_logits_for_sample(
        competing,
        modal_families=("deontic", "frame", "temporal"),
    )

    assert competing_logits["deontic"] < baseline_logits["deontic"]
    assert competing_logits["frame"] > -0.25


def test_spacy_decoder_soft_caps_repeated_deontic_logits_for_conditional_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="18",
        section="924",
        text="The vendor shall and must and shall and must issue notice.",
    )
    competing = build_us_code_sample(
        title="18",
        section="924",
        text=(
            "The vendor shall and must and shall and must issue notice "
            "as provided in subsection (b)."
        ),
    )

    baseline_logits = codec.family_logits_for_sample(
        baseline,
        modal_families=("deontic", "conditional_normative", "frame"),
    )
    competing_logits = codec.family_logits_for_sample(
        competing,
        modal_families=("deontic", "conditional_normative", "frame"),
    )

    assert competing_logits["deontic"] < baseline_logits["deontic"]
    assert competing_logits["conditional_normative"] > -0.25


def test_spacy_decoder_soft_caps_repeated_deontic_logits_for_epistemic_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="18",
        section="1031",
        text="Vendor shall and must and shall and must submit reports.",
    )
    competing = build_us_code_sample(
        title="18",
        section="1032",
        text=(
            "Vendor shall and must and shall and must submit reports, "
            "and inspector determines compliance."
        ),
    )

    baseline_logits = codec.family_logits_for_sample(
        baseline,
        modal_families=("deontic", "epistemic", "frame"),
    )
    competing_logits = codec.family_logits_for_sample(
        competing,
        modal_families=("deontic", "epistemic", "frame"),
    )

    assert competing_logits["deontic"] < baseline_logits["deontic"]
    assert competing_logits["epistemic"] > baseline_logits["epistemic"]


def test_spacy_decoder_soft_caps_repeated_deontic_logits_for_dynamic_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="18",
        section="1033",
        text="Vendor shall and must and shall and must submit reports.",
    )
    competing = build_us_code_sample(
        title="18",
        section="1034",
        text=(
            "Vendor shall and must and shall and must file and serve reports."
        ),
    )

    baseline_logits = codec.family_logits_for_sample(
        baseline,
        modal_families=("deontic", "dynamic", "frame"),
    )
    competing_logits = codec.family_logits_for_sample(
        competing,
        modal_families=("deontic", "dynamic", "frame"),
    )

    assert competing_logits["deontic"] < baseline_logits["deontic"]
    assert competing_logits["dynamic"] > baseline_logits["dynamic"]


def test_spacy_decoder_strengthens_dynamic_logits_for_dense_deontic_scope_with_dynamic_phrase() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="18",
        section="1034a",
        text="Vendor shall and must and shall and must provide reports.",
    )
    competing = build_us_code_sample(
        title="18",
        section="1034b",
        text=(
            "Vendor shall and must and shall and must provide reports upon transfer."
        ),
    )

    baseline_logits = codec.family_logits_for_sample(
        baseline,
        modal_families=("deontic", "dynamic", "frame"),
    )
    competing_logits = codec.family_logits_for_sample(
        competing,
        modal_families=("deontic", "dynamic", "frame"),
    )

    assert competing_logits["deontic"] < baseline_logits["deontic"]
    assert competing_logits["dynamic"] > baseline_logits["dynamic"]


def test_spacy_decoder_strengthens_temporal_logits_for_dense_deontic_scope_with_temporal_phrase() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="47",
        section="221a",
        text="Vendor shall and must and shall and must submit reports.",
    )
    competing = build_us_code_sample(
        title="47",
        section="221b",
        text=(
            "Vendor shall and must and shall and must submit reports while pending review."
        ),
    )

    baseline_logits = codec.family_logits_for_sample(
        baseline,
        modal_families=("deontic", "temporal", "frame"),
    )
    competing_logits = codec.family_logits_for_sample(
        competing,
        modal_families=("deontic", "temporal", "frame"),
    )

    assert competing_logits["deontic"] < baseline_logits["deontic"]
    assert competing_logits["temporal"] > baseline_logits["temporal"]


def test_spacy_decoder_soft_caps_repeated_temporal_logits_for_deontic_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="6",
        section="609a",
        text=(
            "Within 30 days and by January 1, 2030, and no later than the fiscal "
            "year deadline, submission occurs."
        ),
    )
    competing = build_us_code_sample(
        title="6",
        section="609b",
        text=(
            "Within 30 days and by January 1, 2030, and no later than the fiscal "
            "year deadline, the agency is required to submit notice."
        ),
    )

    baseline_logits = codec.family_logits_for_sample(
        baseline,
        modal_families=("temporal", "deontic", "frame"),
    )
    competing_logits = codec.family_logits_for_sample(
        competing,
        modal_families=("temporal", "deontic", "frame"),
    )

    assert competing_logits["temporal"] < baseline_logits["temporal"]
    assert competing_logits["deontic"] > baseline_logits["deontic"]


def test_spacy_decoder_soft_caps_repeated_temporal_logits_for_conditional_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="6",
        section="609c",
        text=(
            "Within 30 days and by January 1, 2030, and no later than the fiscal "
            "year deadline, submission occurs."
        ),
    )
    competing = build_us_code_sample(
        title="6",
        section="609d",
        text=(
            "Within 30 days and by January 1, 2030, and no later than the fiscal "
            "year deadline, if designated under subsection (b), submission occurs."
        ),
    )

    baseline_logits = codec.family_logits_for_sample(
        baseline,
        modal_families=("temporal", "conditional_normative", "deontic"),
    )
    competing_logits = codec.family_logits_for_sample(
        competing,
        modal_families=("temporal", "conditional_normative", "deontic"),
    )

    assert competing_logits["temporal"] < baseline_logits["temporal"]
    assert (
        competing_logits["conditional_normative"]
        > baseline_logits["conditional_normative"]
    )


def test_spacy_decoder_soft_caps_repeated_frame_logits_for_temporal_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="43",
        section="1700",
        text=(
            "Authority and jurisdiction and authority and jurisdiction "
            "apply."
        ),
    )
    competing = build_us_code_sample(
        title="43",
        section="1701",
        text=(
            "Authority and jurisdiction and authority and jurisdiction "
            "apply before each annual review deadline."
        ),
    )

    baseline_logits = codec.family_logits_for_sample(
        baseline,
        modal_families=("frame", "temporal", "deontic"),
    )
    competing_logits = codec.family_logits_for_sample(
        competing,
        modal_families=("frame", "temporal", "deontic"),
    )

    assert competing_logits["frame"] < baseline_logits["frame"]
    assert competing_logits["temporal"] > -0.25


def test_spacy_decoder_soft_caps_repeated_frame_logits_for_deontic_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="43",
        section="1702",
        text=(
            "Authority and jurisdiction and authority and jurisdiction "
            "apply."
        ),
    )
    competing = build_us_code_sample(
        title="43",
        section="1703",
        text=(
            "Authority and jurisdiction and authority and jurisdiction "
            "apply, and the agency is required to provide notice."
        ),
    )

    baseline_logits = codec.family_logits_for_sample(
        baseline,
        modal_families=("frame", "deontic", "temporal"),
    )
    competing_logits = codec.family_logits_for_sample(
        competing,
        modal_families=("frame", "deontic", "temporal"),
    )

    assert competing_logits["frame"] < baseline_logits["frame"]
    assert competing_logits["deontic"] > baseline_logits["deontic"]


def test_spacy_decoder_soft_caps_repeated_frame_logits_for_conditional_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="43",
        section="1704",
        text=(
            "Authority and jurisdiction and authority and jurisdiction "
            "apply."
        ),
    )
    competing = build_us_code_sample(
        title="43",
        section="1705",
        text=(
            "Authority and jurisdiction and authority and jurisdiction "
            "apply if designated under subsection (b)."
        ),
    )

    baseline_logits = codec.family_logits_for_sample(
        baseline,
        modal_families=("frame", "conditional_normative", "temporal"),
    )
    competing_logits = codec.family_logits_for_sample(
        competing,
        modal_families=("frame", "conditional_normative", "temporal"),
    )

    assert competing_logits["frame"] < baseline_logits["frame"]
    assert (
        competing_logits["conditional_normative"]
        > baseline_logits["conditional_normative"]
    )


def test_spacy_frame_soft_cap_treats_strong_epistemic_scope_as_competing_signal() -> None:
    counts = {
        "frame": 4.0,
        "epistemic": 0.0,
    }
    signals = {
        "has_epistemic_scope": True,
        "has_epistemic_scope_phrase": True,
    }

    _apply_frame_competing_scope_soft_cap(counts, signals)

    assert counts["frame"] < 4.0


def test_spacy_frame_soft_cap_treats_strong_dynamic_scope_as_competing_signal() -> None:
    counts = {
        "frame": 4.0,
        "dynamic": 0.12,
    }
    signals = {
        "has_dynamic_scope": True,
        "has_dynamic_scope_phrase": True,
    }

    _apply_frame_competing_scope_soft_cap(counts, signals)

    assert counts["frame"] < 4.0


def test_spacy_frame_backfill_strengthens_existing_low_epistemic_weight() -> None:
    counts = {
        "frame": 0.6,
        "epistemic": 0.12,
    }
    signals = {
        "has_epistemic_scope": True,
    }

    _apply_competing_scope_backfill(counts, signals)

    assert counts["epistemic"] > 0.12


def test_spacy_backfill_strengthens_existing_low_deontic_weight_for_conditional_scope() -> None:
    counts = {
        "conditional_normative": 2.4,
        "deontic": 0.12,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_deontic_cue": False,
        "has_statutory_scope_reference": True,
    }

    _apply_competing_scope_backfill(counts, signals)

    assert counts["deontic"] > 0.12


def test_spacy_backfill_strengthens_existing_low_conditional_weight_for_temporal_scope() -> None:
    counts = {
        "temporal": 3.6,
        "conditional_normative": 0.12,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
    }

    _apply_competing_scope_backfill(counts, signals)

    assert counts["conditional_normative"] > 0.12


def test_spacy_backfill_reinforces_existing_deontic_weight_for_frame_competition() -> None:
    counts = {
        "frame": 1.8,
        "deontic": 0.6,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": True,
        "has_statutory_scope_reference": True,
    }

    _apply_competing_scope_backfill(counts, signals)

    assert counts["deontic"] > 0.6


def test_spacy_backfill_reinforces_existing_temporal_weight_for_frame_competition() -> None:
    counts = {
        "frame": 1.6,
        "temporal": 0.8,
    }
    signals = {
        "has_temporal_scope": True,
        "has_calendar_date_scope": True,
        "has_temporal_scope_phrase": False,
        "has_temporal_within_scope": False,
    }

    _apply_competing_scope_backfill(counts, signals)

    assert counts["temporal"] > 0.8


def test_spacy_backfill_reinforces_existing_conditional_weight_for_frame_competition() -> None:
    counts = {
        "frame": 1.9,
        "conditional_normative": 0.8,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
    }

    _apply_competing_scope_backfill(counts, signals)

    assert counts["conditional_normative"] > 0.8


def test_spacy_backfill_reinforces_existing_deontic_weight_for_temporal_competition() -> None:
    counts = {
        "temporal": 3.2,
        "deontic": 0.8,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_deontic_cue": False,
        "has_statutory_scope_reference": False,
    }

    _apply_competing_scope_backfill(counts, signals)

    assert counts["deontic"] > 0.8


def test_spacy_backfill_reinforces_existing_conditional_weight_for_temporal_competition() -> None:
    counts = {
        "temporal": 3.2,
        "conditional_normative": 0.9,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
    }

    _apply_competing_scope_backfill(counts, signals)

    assert counts["conditional_normative"] > 0.9


def test_spacy_backfill_reinforces_temporal_to_conditional_statutory_scope_below_trigger() -> None:
    baseline_counts = {
        "temporal": 1.6,
        "conditional_normative": 0.08,
    }
    competing_counts = dict(baseline_counts)
    baseline_signals = {
        "has_temporal_scope": True,
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": False,
        "has_deontic_scope": False,
        "has_deontic_cue": False,
    }
    competing_signals = {
        **baseline_signals,
        "has_statutory_scope_reference": True,
    }

    _apply_competing_scope_backfill(baseline_counts, baseline_signals)
    _apply_competing_scope_backfill(competing_counts, competing_signals)

    assert competing_counts["conditional_normative"] > baseline_counts["conditional_normative"]


def test_spacy_backfill_reinforces_existing_epistemic_weight_for_temporal_competition() -> None:
    counts = {
        "temporal": 2.4,
        "epistemic": 0.9,
    }
    signals = {
        "has_epistemic_scope": True,
        "has_epistemic_scope_phrase": False,
        "has_epistemic_cue": True,
    }

    _apply_competing_scope_backfill(counts, signals)

    assert counts["epistemic"] > 0.9


def test_spacy_directional_backfill_adds_frame_support_for_conditional_statutory_scope() -> None:
    counts = {
        "conditional_normative": 2.0,
        "frame": 0.0,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": False,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": False,
    }

    _apply_directional_modal_family_pair_backfill(counts, signals)

    assert counts["frame"] > 0.3


def test_spacy_directional_backfill_adds_epistemic_support_for_conditional_scope() -> None:
    counts = {
        "conditional_normative": 2.6,
        "epistemic": 0.02,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_epistemic_scope": True,
        "has_epistemic_scope_phrase": True,
        "has_epistemic_cue": True,
        "has_statutory_scope_reference": False,
        "has_frame_context": False,
        "has_frame_scope_phrase": False,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": False,
    }

    _apply_directional_modal_family_pair_backfill(counts, signals)

    assert counts["epistemic"] > 0.2


def test_spacy_directional_backfill_adds_temporal_support_for_strong_conditional_scope_without_frame_context() -> None:
    counts = {
        "conditional_normative": 2.4,
        "temporal": 0.05,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_scope_token": False,
        "has_temporal_within_scope": False,
        "has_calendar_date_scope": False,
        "has_temporal_cue": False,
        "has_statutory_scope_reference": False,
        "has_frame_context": False,
        "has_frame_scope_phrase": False,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": False,
    }

    _apply_directional_modal_family_pair_backfill(counts, signals)

    assert counts["temporal"] > 0.2


def test_spacy_directional_backfill_adds_structural_deontic_support_for_temporal_scope() -> None:
    counts = {
        "temporal": 0.8,
        "deontic": 0.05,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_token": True,
        "has_temporal_scope_phrase": False,
        "has_temporal_within_scope": False,
        "has_calendar_date_scope": False,
        "has_temporal_cue": False,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": False,
        "has_statutory_scope_reference": True,
        "has_frame_context": False,
        "has_frame_scope_phrase": False,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": False,
    }

    _apply_directional_modal_family_pair_backfill(counts, signals)

    assert counts["deontic"] > 0.17


def test_spacy_directional_backfill_reinforces_frame_to_deontic_with_explicit_scope() -> None:
    counts = {
        "frame": 2.0,
        "deontic": 0.2,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_deontic_cue": False,
        "has_frame_context": True,
        "has_frame_scope_phrase": False,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": True,
        "has_statutory_scope_reference": True,
    }

    _apply_directional_modal_family_pair_backfill(counts, signals)

    assert counts["deontic"] > 0.85


def test_spacy_directional_backfill_reinforces_frame_to_conditional_for_deontic_statutory_scope() -> None:
    baseline_counts = {
        "frame": 2.2,
        "conditional_normative": 0.18,
    }
    competing_counts = dict(baseline_counts)
    baseline_signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_deontic_scope": False,
        "has_deontic_cue": False,
        "has_frame_context": True,
        "has_frame_scope_phrase": False,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": True,
        "has_statutory_scope_reference": True,
    }
    competing_signals = {
        **baseline_signals,
        "has_deontic_scope": True,
    }

    _apply_directional_modal_family_pair_backfill(baseline_counts, baseline_signals)
    _apply_directional_modal_family_pair_backfill(competing_counts, competing_signals)

    assert competing_counts["conditional_normative"] > baseline_counts["conditional_normative"]


def test_spacy_directional_backfill_adds_conditional_support_for_deontic_scope() -> None:
    counts = {
        "deontic": 0.9,
        "conditional_normative": 0.05,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_deontic_cue": False,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": False,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": False,
    }

    _apply_directional_modal_family_pair_backfill(counts, signals)

    assert counts["conditional_normative"] > 0.2


def test_spacy_directional_backfill_adds_deontic_support_for_conditional_statutory_scope() -> None:
    counts = {
        "conditional_normative": 2.3,
        "deontic": 0.08,
        "frame": 0.05,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_deontic_cue": False,
        "has_statutory_scope_reference": True,
        "has_frame_context": False,
        "has_frame_scope_phrase": False,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": False,
    }

    _apply_directional_modal_family_pair_backfill(counts, signals)

    assert counts["deontic"] > 0.7


def test_spacy_directional_backfill_reinforces_deontic_to_temporal_for_strong_statutory_scope() -> None:
    counts = {
        "deontic": 2.8,
        "temporal": 0.06,
        "frame": 0.0,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_deontic_cue": False,
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_scope_token": True,
        "has_temporal_within_scope": False,
        "has_temporal_cue": True,
        "has_calendar_date_scope": True,
        "has_statutory_scope_reference": True,
        "has_frame_context": False,
        "has_frame_scope_phrase": False,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": False,
    }

    _apply_directional_modal_family_pair_backfill(counts, signals)

    assert counts["temporal"] > 0.7


def test_spacy_directional_backfill_reinforces_deontic_to_frame_without_frame_lexemes() -> None:
    counts = {
        "deontic": 2.0,
        "frame": 0.0,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_deontic_cue": False,
        "has_statutory_scope_reference": True,
        "has_frame_context": False,
        "has_frame_scope_phrase": False,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": False,
    }

    _apply_directional_modal_family_pair_backfill(counts, signals)

    assert counts["frame"] >= 0.78


def test_spacy_directional_backfill_adds_temporal_support_for_weak_statutory_frame_deontic_scope() -> None:
    baseline_counts = {
        "frame": 2.0,
        "temporal": 0.04,
    }
    competing_counts = dict(baseline_counts)
    baseline_signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": False,
        "has_temporal_scope_token": False,
        "has_temporal_within_scope": False,
        "has_calendar_date_scope": False,
        "has_temporal_cue": False,
        "has_deontic_scope": False,
        "has_deontic_cue": False,
        "has_frame_context": True,
        "has_frame_scope_phrase": False,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": True,
        "has_statutory_scope_reference": True,
    }
    competing_signals = {
        **baseline_signals,
        "has_deontic_scope": True,
    }

    _apply_directional_modal_family_pair_backfill(baseline_counts, baseline_signals)
    _apply_directional_modal_family_pair_backfill(competing_counts, competing_signals)

    assert competing_counts["temporal"] > baseline_counts["temporal"]


def test_spacy_directional_backfill_adds_frame_support_for_temporal_scope_with_editorial_frame_signals() -> None:
    counts = {
        "temporal": 0.9,
        "frame": 0.1,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_scope_token": False,
        "has_temporal_within_scope": False,
        "has_calendar_date_scope": False,
        "has_temporal_cue": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": False,
        "has_frame_editorial_scope_phrase": True,
        "has_frame_cue": False,
        "has_statutory_scope_reference": False,
    }

    _apply_directional_modal_family_pair_backfill(counts, signals)

    assert counts["frame"] > 0.3


def test_spacy_directional_backfill_reinforces_temporal_to_deontic_for_strong_statutory_scope() -> None:
    counts = {
        "temporal": 3.4,
        "deontic": 0.1,
        "frame": 0.1,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_scope_token": True,
        "has_temporal_within_scope": False,
        "has_calendar_date_scope": True,
        "has_temporal_cue": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_deontic_cue": False,
        "has_frame_context": True,
        "has_frame_scope_phrase": False,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": False,
        "has_statutory_scope_reference": True,
    }

    _apply_directional_modal_family_pair_backfill(counts, signals)

    assert counts["deontic"] >= 1.0


def test_spacy_directional_backfill_reinforces_temporal_to_frame_for_editorial_statutory_scope() -> None:
    counts = {
        "temporal": 3.2,
        "deontic": 0.2,
        "frame": 0.05,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_scope_token": True,
        "has_temporal_within_scope": False,
        "has_calendar_date_scope": True,
        "has_temporal_cue": True,
        "has_deontic_scope": False,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": False,
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_frame_editorial_scope_phrase": True,
        "has_frame_cue": False,
        "has_statutory_scope_reference": True,
    }

    _apply_directional_modal_family_pair_backfill(counts, signals)

    assert counts["frame"] >= 0.62


def test_spacy_directional_backfill_reinforces_temporal_to_frame_for_statutory_context_without_editorial_phrase() -> None:
    counts = {
        "temporal": 3.0,
        "frame": 0.05,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_scope_token": True,
        "has_temporal_within_scope": False,
        "has_calendar_date_scope": True,
        "has_temporal_cue": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": False,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": False,
        "has_statutory_scope_reference": True,
    }

    _apply_directional_modal_family_pair_backfill(counts, signals)

    assert counts["frame"] >= 0.6


def test_spacy_directional_backfill_reinforces_conditional_to_deontic_for_explicit_scope() -> None:
    counts = {
        "conditional_normative": 2.2,
        "deontic": 0.05,
        "frame": 0.0,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_deontic_cue": False,
        "has_frame_context": True,
        "has_frame_scope_phrase": False,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": False,
        "has_statutory_scope_reference": True,
    }

    _apply_directional_modal_family_pair_backfill(counts, signals)

    assert counts["deontic"] >= 0.4


def test_spacy_directional_backfill_reinforces_deontic_to_temporal_for_strong_temporal_scope() -> None:
    counts = {
        "deontic": 2.8,
        "temporal": 0.04,
        "frame": 0.0,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_scope_token": True,
        "has_temporal_within_scope": False,
        "has_calendar_date_scope": True,
        "has_temporal_cue": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": False,
        "has_frame_context": False,
        "has_frame_scope_phrase": False,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": False,
        "has_statutory_scope_reference": True,
    }

    _apply_directional_modal_family_pair_backfill(counts, signals)

    assert counts["temporal"] >= 0.7


def test_spacy_refined_pair_balance_reinforces_temporal_and_conditional_for_deontic_temporal_conditional_competition() -> None:
    counts = {
        "deontic": 2.8,
        "temporal": 0.04,
        "conditional_normative": 0.05,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": True,
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_scope_token": True,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": False,
        "has_calendar_date_scope": True,
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["temporal"] >= 0.7
    assert counts["conditional_normative"] >= 0.6


def test_spacy_refined_pair_balance_reinforces_deontic_for_temporal_status_scope_competition() -> None:
    counts = {
        "temporal": 2.0,
        "deontic": 0.05,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": False,
        "has_temporal_scope_token": False,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": True,
        "has_calendar_date_scope": False,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": True,
        "has_condition_or_exception_scope": False,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": False,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["deontic"] >= 0.44


def test_spacy_refined_pair_balance_reinforces_deontic_for_statutory_repeal_status_scope() -> None:
    counts = {
        "temporal": 3.35,
        "deontic": 1.35,
        "conditional_normative": 1.35,
        "frame": 0.75,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": True,
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_scope_token": True,
        "has_temporal_status_scope": True,
        "has_temporal_cue": True,
        "has_temporal_deadline_cue": False,
        "has_calendar_date_scope": True,
        "has_condition_or_exception_scope": True,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": False,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["deontic"] >= 2.15
    assert counts["deontic"] > counts["conditional_normative"]


def test_spacy_refined_pair_balance_softens_deontic_overflow_for_statutory_conditional_editorial_scope() -> None:
    counts = {
        "deontic": 3.369256,
        "conditional_normative": 3.0,
        "temporal": 1.35,
        "frame": 0.35,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": True,
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": False,
        "has_temporal_scope_token": True,
        "has_temporal_status_scope": False,
        "has_temporal_cue": True,
        "has_temporal_deadline_cue": True,
        "has_calendar_date_scope": True,
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": True,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_frame_editorial_scope_phrase": True,
        "has_frame_cue": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["deontic"] < 3.369256
    assert counts["conditional_normative"] > 3.0
    assert (counts["deontic"] - counts["conditional_normative"]) <= 0.13


def test_spacy_refined_pair_balance_reinforces_temporal_to_conditional_and_deontic_for_statutory_status_scope() -> None:
    counts = {
        "temporal": 2.6,
        "deontic": 0.05,
        "conditional_normative": 0.04,
        "frame": 0.95,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": False,
        "has_temporal_scope_token": False,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": True,
        "has_temporal_deadline_cue": False,
        "has_calendar_date_scope": False,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_deontic_cue": True,
        "has_condition_or_exception_scope": True,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["deontic"] >= 0.67
    assert counts["conditional_normative"] >= 0.57


def test_spacy_refined_pair_balance_reinforces_frame_to_deontic_for_non_editorial_statutory_status_scope() -> None:
    counts = {
        "frame": 2.2,
        "deontic": 0.05,
        "temporal": 0.8,
        "conditional_normative": 0.0,
    }
    signals = {
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": False,
        "has_statutory_scope_reference": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_deontic_cue": True,
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": False,
        "has_temporal_scope_token": False,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": True,
        "has_temporal_deadline_cue": False,
        "has_calendar_date_scope": False,
        "has_condition_or_exception_scope": False,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": False,
        "has_conditional_scope_token": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["deontic"] >= 0.55


def test_spacy_refined_pair_balance_preserves_deontic_for_generic_statutory_frame_scope() -> None:
    counts = {
        "frame": 2.4,
        "deontic": 0.08,
        "temporal": 0.2,
        "conditional_normative": 0.1,
    }
    signals = {
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": True,
        "has_frame_structural_authority_scope_phrase": True,
        "has_statutory_scope_reference": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_deontic_cue": True,
        "has_temporal_scope": False,
        "has_temporal_scope_phrase": False,
        "has_temporal_scope_token": False,
        "has_temporal_status_scope": False,
        "has_calendar_date_scope": False,
        "has_condition_or_exception_scope": False,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": False,
        "has_conditional_scope_token": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["deontic"] >= 0.7


def test_spacy_refined_pair_balance_preserves_temporal_for_generic_statutory_frame_scope() -> None:
    counts = {
        "frame": 2.6,
        "temporal": 0.05,
        "deontic": 0.2,
        "conditional_normative": 0.1,
    }
    signals = {
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_frame_editorial_scope_phrase": True,
        "has_frame_cue": True,
        "has_frame_structural_authority_scope_phrase": False,
        "has_statutory_scope_reference": True,
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_scope_token": True,
        "has_temporal_status_scope": True,
        "has_temporal_within_scope": False,
        "has_calendar_date_scope": True,
        "has_temporal_deadline_cue": False,
        "has_deontic_scope": False,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": False,
        "has_condition_or_exception_scope": False,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": False,
        "has_conditional_scope_token": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["temporal"] >= 0.75


def test_spacy_refined_pair_balance_preserves_conditional_and_deontic_for_temporal_statutory_scope() -> None:
    counts = {
        "temporal": 2.8,
        "conditional_normative": 0.06,
        "deontic": 0.08,
        "frame": 0.5,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_scope_token": True,
        "has_temporal_status_scope": True,
        "has_temporal_within_scope": False,
        "has_calendar_date_scope": True,
        "has_temporal_deadline_cue": False,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_deontic_cue": True,
        "has_condition_or_exception_scope": True,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_purpose_scope_phrase": True,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_frame_editorial_scope_phrase": True,
        "has_frame_structural_authority_scope_phrase": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["conditional_normative"] >= 0.84
    assert counts["deontic"] >= 0.84


def test_spacy_refined_pair_balance_reinforces_frame_for_statutory_conditional_status_scope() -> None:
    counts = {
        "deontic": 3.369256,
        "conditional_normative": 3.0,
        "temporal": 2.18,
        "frame": 0.5,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": True,
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": False,
        "has_temporal_scope_token": True,
        "has_temporal_status_scope": True,
        "has_temporal_cue": True,
        "has_temporal_deadline_cue": True,
        "has_calendar_date_scope": True,
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": False,
        "has_conditional_scope_token": True,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": True,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["frame"] >= 1.2


def test_spacy_refined_pair_balance_reinforces_deontic_and_temporal_for_structural_conditional_scope() -> None:
    counts = {
        "conditional_normative": 2.2,
        "deontic": 0.05,
        "temporal": 0.03,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": False,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": True,
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_scope_token": True,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": False,
        "has_calendar_date_scope": True,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["deontic"] >= 0.52
    assert counts["temporal"] >= 0.52


def test_spacy_refined_pair_balance_reinforces_frame_for_phrase_only_structural_conditional_scope() -> None:
    counts = {
        "conditional_normative": 2.2,
        "frame": 0.0,
        "deontic": 0.0,
        "temporal": 0.0,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": False,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": False,
        "has_deontic_scope": False,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": False,
        "has_temporal_scope": False,
        "has_temporal_scope_phrase": False,
        "has_temporal_scope_token": False,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": False,
        "has_calendar_date_scope": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["frame"] >= 0.52
    assert counts["conditional_normative"] < 2.2


def test_spacy_refined_pair_balance_reinforces_conditional_for_phrase_only_statutory_deontic_scope() -> None:
    counts = {
        "deontic": 2.0,
        "conditional_normative": 0.04,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_deontic_cue": True,
        "has_temporal_scope": False,
        "has_temporal_scope_phrase": False,
        "has_temporal_scope_token": False,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": False,
        "has_calendar_date_scope": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["conditional_normative"] >= 0.4


def test_spacy_refined_pair_balance_reinforces_conditional_for_structural_statutory_deontic_scope() -> None:
    counts = {
        "deontic": 2.4,
        "conditional_normative": 0.05,
        "temporal": 0.45,
        "frame": 0.35,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": False,
        "has_conditional_scope_token": False,
        "has_purpose_scope_phrase": False,
        "has_statutory_scope_reference": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": True,
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": False,
        "has_temporal_scope_token": True,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": False,
        "has_temporal_deadline_cue": False,
        "has_calendar_date_scope": False,
        "has_frame_context": True,
        "has_frame_scope_phrase": False,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["conditional_normative"] >= 0.45


def test_spacy_refined_pair_balance_reinforces_deontic_for_conditional_scope_phrase_with_explicit_deontic_force() -> None:
    counts = {
        "conditional_normative": 1.0,
        "deontic": 1.0,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_purpose_scope_phrase": True,
        "has_statutory_scope_reference": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_deontic_cue": True,
        "has_temporal_scope": False,
        "has_temporal_scope_phrase": False,
        "has_temporal_scope_token": False,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": False,
        "has_temporal_deadline_cue": False,
        "has_calendar_date_scope": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["deontic"] > 1.0


def test_spacy_refined_pair_balance_reinforces_deontic_for_clause_only_if_scope_with_explicit_deontic_force() -> None:
    counts = {
        "conditional_normative": 2.3,
        "deontic": 0.2,
        "temporal": 0.0,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": False,
        "has_conditional_scope_token": False,
        "has_purpose_scope_phrase": False,
        "has_statutory_scope_reference": False,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_deontic_cue": True,
        "has_temporal_scope": False,
        "has_temporal_scope_phrase": False,
        "has_temporal_scope_token": False,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": False,
        "has_temporal_deadline_cue": False,
        "has_calendar_date_scope": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["deontic"] > 0.2


def test_spacy_refined_pair_balance_promotes_epistemic_over_generic_frame_scaffold() -> None:
    counts = {
        "frame": 2.4,
        "epistemic": 0.35,
        "deontic": 0.1,
    }
    signals = {
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_structural_authority_scope_phrase": False,
        "has_statutory_scope_reference": True,
        "has_definition_scope": False,
        "has_epistemic_scope": True,
        "has_epistemic_cue": True,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["epistemic"] > counts["frame"]


def test_spacy_refined_pair_balance_promotes_temporal_status_over_editorial_frame_scaffold() -> None:
    counts = {
        "frame": 2.5,
        "temporal": 0.45,
        "deontic": 0.0,
        "conditional_normative": 0.0,
    }
    signals = {
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_frame_editorial_scope_phrase": True,
        "has_statutory_scope_reference": True,
        "has_definition_scope": False,
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_status_scope": True,
        "has_calendar_date_scope": True,
        "has_deontic_cue": False,
        "has_condition_or_exception_scope": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["temporal"] > counts["frame"]


def test_spacy_refined_pair_balance_promotes_conditional_over_frame_status_scaffold() -> None:
    counts = {
        "frame": 2.1,
        "conditional_normative": 0.4,
        "temporal": 0.8,
    }
    signals = {
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_frame_editorial_scope_phrase": True,
        "has_frame_structural_authority_scope_phrase": False,
        "has_statutory_scope_reference": True,
        "has_definition_scope": False,
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_temporal_status_scope": True,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["conditional_normative"] > counts["frame"]


def test_spacy_refined_pair_balance_promotes_deontic_study_report_over_deadline_scope() -> None:
    counts = {
        "temporal": 2.15,
        "deontic": 0.7,
        "conditional_normative": 0.2,
        "frame": 0.35,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_cue": True,
        "has_deontic_report_duty_scope_phrase": True,
        "has_deontic_study_report_duty_scope_phrase": True,
        "has_temporal_scope": True,
        "has_temporal_deadline_cue": True,
        "has_temporal_within_scope": True,
        "has_frame_editorial_scope_phrase": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["deontic"] > counts["temporal"]


def test_spacy_refined_pair_balance_promotes_structural_authority_frame_over_generic_deontic() -> None:
    counts = {
        "deontic": 2.0,
        "frame": 0.6,
        "temporal": 0.2,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_cue": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_frame_structural_authority_scope_phrase": True,
        "has_deontic_authorization_scope_phrase": False,
        "has_deontic_report_duty_scope_phrase": False,
        "has_deontic_corporate_powers_scope_phrase": False,
        "has_deontic_benefit_entitlement_scope_phrase": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["frame"] > counts["deontic"]


def test_spacy_encoder_marks_study_and_report_as_deontic_report_duty_scope() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The Commission shall conduct a study and report not later than 180 days.",
        document_id="packet-000117-study-report-duty",
    )

    signals = modal_ambiguity_signals(encoding)

    assert signals["has_deontic_study_report_duty_scope_phrase"] is True


def test_spacy_encoder_treats_to_the_extent_possible_as_deontic_qualifier_not_alethic_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The agency shall, to the extent possible, provide written notice.",
        document_id="deontic-qualified-possible-doc",
    )

    possible_cues = [cue for cue in encoding.cues if cue.cue.lower() == "possible"]
    assert all(cue.family != "alethic" for cue in possible_cues)
    signals = modal_ambiguity_signals(encoding)
    assert signals["has_deontic_cue"] is True
    assert signals["has_alethic_cue"] is False


def test_spacy_refined_pair_balance_reinforces_deontic_for_phrase_only_structural_temporal_scope() -> None:
    counts = {
        "temporal": 2.0,
        "deontic": 0.1,
        "conditional_normative": 0.3,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": False,
        "has_temporal_scope_token": True,
        "has_temporal_within_scope": True,
        "has_temporal_status_scope": False,
        "has_calendar_date_scope": False,
        "has_temporal_deadline_cue": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": True,
        "has_condition_or_exception_scope": True,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["deontic"] >= 0.48


def test_spacy_refined_pair_balance_reinforces_deontic_for_temporal_appropriations_authorization_scope() -> None:
    counts = {
        "temporal": 2.2,
        "deontic": 0.08,
        "conditional_normative": 0.2,
        "frame": 0.15,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_scope_token": True,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": False,
        "has_calendar_date_scope": False,
        "has_temporal_deadline_cue": False,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_deontic_appropriations_scope_phrase": True,
        "has_deontic_cue": False,
        "has_condition_or_exception_scope": False,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": False,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": False,
        "has_frame_context": False,
        "has_frame_scope_phrase": False,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["deontic"] >= 0.61
    assert counts["temporal"] < 2.2


def test_spacy_refined_pair_balance_reinforces_frame_for_temporal_deontic_statutory_scope() -> None:
    counts = {
        "temporal": 2.4,
        "deontic": 1.4,
        "frame": 0.05,
        "conditional_normative": 0.2,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": False,
        "has_temporal_scope_token": True,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": False,
        "has_calendar_date_scope": False,
        "has_temporal_deadline_cue": False,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": True,
        "has_condition_or_exception_scope": True,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": False,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": True,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["frame"] >= 0.57


def test_spacy_refined_pair_balance_skips_purpose_only_conditional_reinforcement_for_explicit_deontic_scope() -> None:
    counts = {
        "deontic": 2.0,
        "conditional_normative": 0.04,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_purpose_scope_phrase": True,
        "has_statutory_scope_reference": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_deontic_cue": True,
        "has_temporal_scope": False,
        "has_temporal_scope_phrase": False,
        "has_temporal_scope_token": False,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": False,
        "has_calendar_date_scope": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["conditional_normative"] == pytest.approx(0.04)


def test_spacy_refined_pair_balance_caps_non_deadline_temporal_pressure_against_explicit_deontic_scope() -> None:
    counts = {
        "temporal": 2.0,
        "deontic": 0.5,
        "conditional_normative": 0.0,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_scope_token": True,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": False,
        "has_calendar_date_scope": False,
        "has_temporal_deadline_cue": False,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_deontic_cue": False,
        "has_condition_or_exception_scope": False,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": False,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["temporal"] < 2.0
    assert counts["temporal"] < 1.0
    assert counts["deontic"] == 0.5


def test_spacy_refined_pair_balance_caps_generic_deontic_overflow_for_structural_temporal_frame_scope() -> None:
    counts = {
        "deontic": 3.2,
        "temporal": 2.0,
        "conditional_normative": 2.0,
        "frame": 1.0,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": True,
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_scope_token": True,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": True,
        "has_temporal_deadline_cue": False,
        "has_calendar_date_scope": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_frame_editorial_scope_phrase": True,
        "has_frame_cue": True,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["deontic"] < 3.2
    assert counts["deontic"] > counts["temporal"]


def test_spacy_refined_pair_balance_caps_editorial_deontic_overflow_with_temporal_status_scope() -> None:
    counts = {
        "deontic": 5.6,
        "temporal": 1.35,
        "conditional_normative": 3.0,
        "frame": 1.0,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_deontic_cue": True,
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": False,
        "has_temporal_scope_token": True,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": True,
        "has_temporal_deadline_cue": False,
        "has_calendar_date_scope": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_frame_editorial_scope_phrase": True,
        "has_frame_cue": True,
    }
    baseline_deontic = counts["deontic"]

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["deontic"] < baseline_deontic
    assert counts["deontic"] > counts["temporal"]


def test_spacy_refined_pair_balance_reinforces_deontic_when_explicit_statutory_conditional_scope_dominates() -> None:
    counts = {
        "conditional_normative": 4.6,
        "deontic": 3.4,
        "temporal": 3.0,
        "frame": 0.75,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_exception_clause": True,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": True,
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_scope_token": True,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": True,
        "has_temporal_deadline_cue": True,
        "has_calendar_date_scope": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_frame_editorial_scope_phrase": True,
        "has_frame_cue": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["deontic"] > 3.4


def test_spacy_refined_pair_balance_reinforces_temporal_for_structural_statutory_conditional_scope_with_temporal_cue() -> None:
    counts = {
        "conditional_normative": 0.62,
        "deontic": 1.0,
        "temporal": 1.0,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": False,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": True,
        "has_temporal_scope": True,
        "has_temporal_cue": True,
        "has_temporal_scope_phrase": False,
        "has_temporal_scope_token": False,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": False,
        "has_temporal_deadline_cue": False,
        "has_calendar_date_scope": False,
        "has_frame_editorial_scope_phrase": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["temporal"] > 1.25


def test_spacy_refined_pair_balance_reinforces_temporal_for_deadline_condition_clause_competition() -> None:
    counts = {
        "conditional_normative": 1.0,
        "deontic": 1.0,
        "temporal": 1.0,
    }
    signals = {
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": False,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_deontic_cue": True,
        "has_temporal_scope": True,
        "has_temporal_cue": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_scope_token": True,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": False,
        "has_temporal_deadline_cue": True,
        "has_calendar_date_scope": True,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["temporal"] > 1.0


def test_spacy_refined_pair_balance_caps_editorial_temporal_status_pressure_for_statutory_deontic_scope() -> None:
    counts = {
        "temporal": 3.26160091167848,
        "deontic": 1.35,
        "conditional_normative": 1.35,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_scope_token": False,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": True,
        "has_calendar_date_scope": True,
        "has_temporal_deadline_cue": True,
        "has_temporal_cue": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": True,
        "has_condition_or_exception_scope": True,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": False,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
        "has_frame_editorial_scope_phrase": True,
    }
    baseline_temporal = counts["temporal"]

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["temporal"] < baseline_temporal
    assert counts["temporal"] < 2.0
    assert counts["deontic"] == pytest.approx(1.35)


def test_spacy_refined_pair_balance_reinforces_frame_for_purpose_scoped_deontic_statutory_scope() -> None:
    counts = {
        "deontic": 2.5,
        "conditional_normative": 1.2,
        "frame": 0.2,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": True,
        "has_condition_or_exception_scope": True,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_purpose_scope_phrase": True,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_frame_editorial_scope_phrase": True,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["frame"] >= 0.6


def test_spacy_refined_pair_balance_reinforces_temporal_for_purpose_scoped_strong_statutory_temporal_context() -> None:
    counts = {
        "deontic": 2.6,
        "temporal": 0.72,
        "conditional_normative": 1.1,
        "frame": 0.3,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_deontic_cue": True,
        "has_condition_or_exception_scope": True,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_purpose_scope_phrase": True,
        "has_statutory_scope_reference": True,
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_scope_token": True,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": True,
        "has_temporal_deadline_cue": False,
        "has_calendar_date_scope": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_frame_editorial_scope_phrase": True,
        "has_frame_cue": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["temporal"] > 0.9


def test_spacy_refined_pair_balance_reinforces_temporal_for_fiscal_until_expended_scope() -> None:
    counts = {
        "deontic": 5.0,
        "conditional_normative": 2.5,
        "temporal": 1.0,
        "frame": 0.4,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": True,
        "has_condition_or_exception_scope": True,
        "has_condition_clause": True,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
        "has_temporal_scope": True,
        "has_temporal_cue": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_fiscal_scope_phrase": True,
        "has_temporal_expended_scope_phrase": True,
        "has_temporal_scope_token": True,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": False,
        "has_temporal_deadline_cue": False,
        "has_calendar_date_scope": False,
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_frame_editorial_scope_phrase": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["temporal"] >= 1.3


def test_spacy_refined_pair_balance_reinforces_epistemic_for_temporal_statutory_competition() -> None:
    counts = {
        "temporal": 2.4,
        "deontic": 1.2,
        "epistemic": 0.05,
        "frame": 0.2,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_scope_token": True,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": False,
        "has_temporal_deadline_cue": True,
        "has_calendar_date_scope": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": True,
        "has_epistemic_scope": True,
        "has_epistemic_scope_phrase": True,
        "has_epistemic_cue": False,
        "has_condition_or_exception_scope": True,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": True,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": False,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_cue": False,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["epistemic"] >= 0.35
    assert counts["epistemic"] > 0.05


def test_spacy_refined_pair_balance_reinforces_alethic_for_temporal_definition_heading_scope() -> None:
    counts = {
        "temporal": 2.1,
        "alethic": 0.02,
        "frame": 0.0,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": False,
        "has_temporal_scope_token": False,
        "has_temporal_within_scope": False,
        "has_temporal_status_scope": False,
        "has_temporal_deadline_cue": False,
        "has_calendar_date_scope": False,
        "has_deontic_scope": False,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": False,
        "has_definition_scope": True,
    }

    _apply_refined_modal_family_cue_pair_balance(counts, signals)

    assert counts["alethic"] >= 0.35


def test_modal_ambiguity_signals_mark_section_defined_heading_as_definition_scope() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "Sec. 12 - United States Postal Service defined.",
        document_id="section-defined-heading-doc",
    )

    signals = modal_ambiguity_signals(encoding)

    assert signals["has_definition_scope"] is True
    assert signals["has_alethic_scope"] is True
    assert signals["has_alethic_scope_phrase"] is False


def test_spacy_temporal_scope_boost_is_stronger_with_deontic_cue_competition() -> None:
    base_signals = {
        "has_temporal_scope": True,
        "has_calendar_date_scope": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": False,
    }
    cue_competing_signals = {
        **base_signals,
        "has_deontic_cue": True,
    }

    base_boosts = _scope_signal_family_logit_boosts(base_signals)
    cue_competing_boosts = _scope_signal_family_logit_boosts(cue_competing_signals)

    assert (
        cue_competing_boosts["temporal"]
        > base_boosts["temporal"]
    )


def test_spacy_temporal_scope_boost_is_weaker_for_weak_temporal_scope_with_deontic_competition() -> None:
    base_signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": False,
        "has_temporal_scope_token": False,
        "has_temporal_within_scope": False,
        "has_statutory_scope_reference": True,
    }
    competing_signals = {
        **base_signals,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
    }

    base_boosts = _scope_signal_family_logit_boosts(base_signals)
    competing_boosts = _scope_signal_family_logit_boosts(competing_signals)

    assert competing_boosts["temporal"] < base_boosts["temporal"]
    assert competing_boosts["deontic"] > 0.0


def test_spacy_temporal_scope_boost_damps_editorial_calendar_noise_without_temporal_cues() -> None:
    noise_signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": False,
        "has_temporal_scope_token": True,
        "has_temporal_within_scope": False,
        "has_temporal_deadline_cue": False,
        "has_temporal_cue": False,
        "has_calendar_date_scope": True,
        "has_temporal_status_scope": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": False,
        "has_deontic_cue": True,
        "has_frame_context": True,
        "has_frame_editorial_scope_phrase": True,
        "has_statutory_scope_reference": True,
    }
    explicit_temporal_signals = {
        **noise_signals,
        "has_temporal_cue": True,
    }

    noise_boosts = _scope_signal_family_logit_boosts(noise_signals)
    explicit_temporal_boosts = _scope_signal_family_logit_boosts(
        explicit_temporal_signals
    )

    assert noise_boosts["temporal"] < explicit_temporal_boosts["temporal"]
    assert noise_boosts["deontic"] > 0.0


def test_spacy_temporal_scope_boost_damps_status_only_temporal_noise_in_non_statutory_frame_scope() -> None:
    baseline_signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": False,
        "has_temporal_scope_token": False,
        "has_temporal_within_scope": False,
        "has_temporal_deadline_cue": False,
        "has_temporal_cue": False,
        "has_temporal_status_scope": True,
        "has_calendar_date_scope": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_statutory_scope_reference": False,
    }
    statutory_reference_signals = {
        **baseline_signals,
        "has_statutory_scope_reference": True,
    }

    baseline_boosts = _scope_signal_family_logit_boosts(baseline_signals)
    statutory_boosts = _scope_signal_family_logit_boosts(
        statutory_reference_signals
    )

    assert baseline_boosts["temporal"] < statutory_boosts["temporal"]


def test_spacy_frame_bonus_preserves_more_statutory_weight_for_weak_temporal_scope() -> None:
    weak_temporal_signals = {
        "has_frame_context": True,
        "has_statutory_scope_reference": True,
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": False,
        "has_temporal_scope_token": False,
        "has_temporal_within_scope": False,
    }
    strong_temporal_signals = {
        **weak_temporal_signals,
        "has_temporal_scope_phrase": True,
    }

    weak_temporal_bonus = _frame_logit_bonus(weak_temporal_signals)
    strong_temporal_bonus = _frame_logit_bonus(strong_temporal_signals)

    assert weak_temporal_bonus > strong_temporal_bonus
    assert weak_temporal_bonus > 0.5


def test_spacy_frame_bonus_recognizes_procedural_frame_scope_signal() -> None:
    baseline_signals = {
        "has_frame_context": True,
        "has_statutory_scope_reference": True,
        "has_deontic_scope": True,
    }
    procedural_signals = {
        **baseline_signals,
        "has_frame_procedural_scope_phrase": True,
    }

    assert _frame_logit_bonus(procedural_signals) > _frame_logit_bonus(baseline_signals)


def test_spacy_frame_bonus_reinforces_deontic_conditional_statutory_frame_competition() -> None:
    baseline_signals = {
        "has_deontic_scope": True,
        "has_condition_or_exception_scope": True,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": False,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_frame_editorial_scope_phrase": True,
        "has_frame_cue": True,
        "has_temporal_scope": True,
    }
    competing_signals = {
        **baseline_signals,
        "has_condition_clause": True,
        "has_conditional_scope_phrase": True,
    }

    assert _frame_logit_bonus(competing_signals) > _frame_logit_bonus(baseline_signals) + 2.0


def test_spacy_generic_frame_debias_bonus_reinforces_deontic_conditional_statutory_competition() -> None:
    baseline_signals = {
        "has_deontic_scope": True,
        "has_condition_or_exception_scope": True,
        "has_condition_clause": False,
        "has_exception_clause": False,
        "has_conditional_scope_phrase": False,
        "has_conditional_scope_token": False,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_frame_editorial_scope_phrase": True,
        "has_frame_cue": True,
        "has_temporal_scope": True,
    }
    competing_signals = {
        **baseline_signals,
        "has_condition_clause": True,
        "has_conditional_scope_phrase": True,
    }

    assert _debias_frame_bonus_for_generic_cues(competing_signals) > _debias_frame_bonus_for_generic_cues(
        baseline_signals
    ) + 1.0


def test_spacy_deontic_boost_reinforces_explicit_deontic_scope_in_procedural_frame_context() -> None:
    baseline_signals = {
        "has_deontic_scope": True,
        "has_deontic_cue": True,
        "has_frame_context": True,
        "has_statutory_scope_reference": True,
    }
    procedural_signals = {
        **baseline_signals,
        "has_frame_procedural_scope_phrase": True,
    }

    baseline_boost = _scope_signal_family_logit_boosts(baseline_signals)["deontic"]
    procedural_boost = _scope_signal_family_logit_boosts(procedural_signals)["deontic"]

    assert procedural_boost > baseline_boost


def test_spacy_temporal_soft_cap_treats_strong_frame_scope_as_competing_signal() -> None:
    counts = {
        "temporal": 4.0,
        "frame": 1.0,
    }
    signals = {
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
    }

    _apply_temporal_competing_scope_soft_cap(counts, signals)

    assert counts["temporal"] < 4.0


def test_spacy_temporal_soft_cap_strengthens_with_multiple_strong_competing_scopes() -> None:
    frame_only_counts = {
        "temporal": 4.0,
        "frame": 1.0,
    }
    frame_only_signals = {
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
    }
    frame_and_deontic_counts = {
        "temporal": 4.0,
        "frame": 1.0,
        "deontic": 1.0,
    }
    frame_and_deontic_signals = {
        "has_frame_context": True,
        "has_frame_scope_phrase": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
    }

    _apply_temporal_competing_scope_soft_cap(frame_only_counts, frame_only_signals)
    _apply_temporal_competing_scope_soft_cap(
        frame_and_deontic_counts,
        frame_and_deontic_signals,
    )

    assert frame_and_deontic_counts["temporal"] < frame_only_counts["temporal"]


def test_spacy_dynamic_soft_cap_treats_strong_temporal_scope_as_competing_signal() -> None:
    counts = {
        "dynamic": 4.0,
        "temporal": 0.12,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
    }

    _apply_dynamic_competing_scope_soft_cap(counts, signals)

    assert counts["dynamic"] < 4.0


def test_spacy_backfill_strengthens_temporal_weight_for_dynamic_scope() -> None:
    counts = {
        "dynamic": 2.6,
        "temporal": 0.0,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
    }

    _apply_competing_scope_backfill(counts, signals)

    assert counts["temporal"] > 0.0


def test_spacy_scope_boost_strengthens_deontic_and_epistemic_in_frame_context() -> None:
    deontic_base_signals = {
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
    }
    deontic_frame_signals = {
        **deontic_base_signals,
        "has_frame_context": True,
        "has_frame_cue": True,
    }
    epistemic_base_signals = {
        "has_epistemic_scope": True,
        "has_epistemic_scope_phrase": True,
    }
    epistemic_frame_signals = {
        **epistemic_base_signals,
        "has_frame_context": True,
        "has_frame_cue": True,
    }

    deontic_base_boosts = _scope_signal_family_logit_boosts(deontic_base_signals)
    deontic_frame_boosts = _scope_signal_family_logit_boosts(deontic_frame_signals)
    epistemic_base_boosts = _scope_signal_family_logit_boosts(epistemic_base_signals)
    epistemic_frame_boosts = _scope_signal_family_logit_boosts(epistemic_frame_signals)

    assert deontic_frame_boosts["deontic"] > deontic_base_boosts["deontic"]
    assert epistemic_frame_boosts["epistemic"] > epistemic_base_boosts["epistemic"]


def test_spacy_decoder_soft_caps_repeated_conditional_logits_for_deontic_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="15",
        section="4701",
        text=(
            "If designated and unless waived and except as otherwise provided "
            "and provided that the filing is complete, this provision applies."
        ),
    )
    competing = build_us_code_sample(
        title="15",
        section="4702",
        text=(
            "If designated and unless waived and except as otherwise provided "
            "and provided that the filing is complete, this provision imposes "
            "mandatory compliance."
        ),
    )

    baseline_logits = codec.family_logits_for_sample(
        baseline,
        modal_families=("conditional_normative", "deontic", "temporal"),
    )
    competing_logits = codec.family_logits_for_sample(
        competing,
        modal_families=("conditional_normative", "deontic", "temporal"),
    )

    assert competing_logits["conditional_normative"] < baseline_logits["conditional_normative"]
    assert competing_logits["deontic"] > baseline_logits["deontic"]


def test_spacy_codec_backfills_deontic_share_for_conditional_scope_with_deontic_phrase() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="20",
        section="1415",
        text=(
            "If designated and subject to subsection (b), liability for "
            "noncompliance applies."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "deontic" for cue in encoding.cues)
    assert signals["has_deontic_scope"] is True
    assert signals["has_deontic_scope_phrase"] is True
    assert signals["has_statutory_scope_reference"] is False
    deontic_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "deontic"
    )
    assert deontic_share > 0.05


def test_spacy_codec_strengthens_conditional_share_for_dense_deontic_scope_with_condition_clause() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="18",
        section="1038",
        text=(
            "When the application is complete, the agency shall and must and shall "
            "and must issue notice."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "conditional_normative" for cue in encoding.cues)
    assert signals["has_condition_clause"] is True
    conditional_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "conditional_normative"
    )
    assert conditional_share > 0.05


def test_spacy_codec_backfills_temporal_share_for_conditional_scope_with_temporal_scope_phrase() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="30",
        section="1352",
        text=(
            "If designated and subject to subsection (b), this authority "
            "applies while pending review."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "temporal" for cue in encoding.cues)
    assert signals["has_temporal_scope"] is True
    assert signals["has_temporal_scope_phrase"] is True
    temporal_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "temporal"
    )
    assert temporal_share > 0.0


def test_spacy_codec_backfills_frame_share_for_conditional_scope_with_statutory_reference() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="7",
        section="8321",
        text=(
            "If designated and except as otherwise provided, as provided in "
            "subsection (b), this provision applies."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "frame" for cue in encoding.cues)
    assert signals["has_statutory_scope_reference"] is True
    frame_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "frame"
    )
    assert frame_share > 0.0


def test_spacy_codec_backfills_deontic_share_for_conditional_scope_with_deontic_tokens() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="12",
        section="1819",
        text=(
            "If designated and except as otherwise provided, mandatory reporting "
            "applies."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "deontic" for cue in encoding.cues)
    assert signals["has_deontic_scope"] is True
    assert signals["has_deontic_scope_phrase"] is False
    assert signals["has_statutory_scope_reference"] is False
    deontic_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "deontic"
    )
    assert deontic_share > 0.0


def test_spacy_codec_backfills_temporal_share_for_conditional_scope_with_temporal_tokens() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="12",
        section="1820",
        text=(
            "If designated and except as otherwise provided, annual review "
            "applies."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "temporal" for cue in encoding.cues)
    assert signals["has_temporal_scope"] is True
    assert signals["has_temporal_scope_phrase"] is False
    assert signals["has_statutory_scope_reference"] is False
    temporal_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "temporal"
    )
    assert temporal_share > 0.0


def test_spacy_codec_backfills_conditional_share_for_frame_scope_with_statutory_condition_reference() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="12",
        section="1821",
        text=(
            "Authority and jurisdiction in this former section apply as provided in "
            "subsection (b)."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "conditional_normative" for cue in encoding.cues)
    assert signals["has_frame_scope_phrase"] is True
    assert signals["has_condition_or_exception_scope"] is True
    conditional_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "conditional_normative"
    )
    assert conditional_share > 0.0


def test_spacy_codec_backfills_deontic_share_for_frame_scope_with_conditional_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="28",
        section="2345",
        text=(
            "Authority and jurisdiction apply if designated under subsection (b), "
            "and liability for noncompliance applies."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "deontic" for cue in encoding.cues)
    assert signals["has_deontic_scope"] is True
    assert signals["has_condition_or_exception_scope"] is True
    deontic_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "deontic"
    )
    assert deontic_share > 0.0


def test_spacy_codec_backfills_temporal_share_for_frame_scope_with_conditional_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="46",
        section="60104",
        text=(
            "Authority and jurisdiction apply if designated under subsection (b) "
            "while pending review."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "temporal" for cue in encoding.cues)
    assert signals["has_temporal_scope"] is True
    assert signals["has_condition_or_exception_scope"] is True
    temporal_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "temporal"
    )
    assert temporal_share > 0.0


def test_spacy_codec_backfills_temporal_share_for_single_frame_cue_with_deontic_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="31",
        section="710",
        text="The authority shall remain while pending review.",
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert signals["has_frame_cue"] is True
    assert signals["has_deontic_cue"] is True
    assert signals["has_temporal_scope"] is True
    temporal_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "temporal"
    )
    assert temporal_share > 0.0


def test_spacy_codec_backfills_deontic_share_for_single_frame_cue_with_temporal_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="31",
        section="711",
        text="The authority applies within 30 days, and liability for noncompliance remains.",
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert signals["has_frame_cue"] is True
    assert signals["has_temporal_scope"] is True
    assert signals["has_deontic_scope"] is True
    deontic_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "deontic"
    )
    assert deontic_share > 0.0


def test_spacy_codec_balances_corporate_powers_permission_against_frame_cues() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="36",
        section="130305",
        text=(
            "Powers The corporation may adopt bylaws and carry out the purposes "
            "of the corporation under this section. The corporation and authority apply."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)
    shares = {item["family"]: float(item["share"]) for item in ranking}

    assert signals["has_deontic_corporate_powers_scope_phrase"] is True
    assert shares["deontic"] >= shares["frame"]
    assert ranking[0]["family"] == "deontic"


def test_spacy_codec_preserves_annual_report_duty_over_fiscal_temporal_scope() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="36",
        section="140411",
        text=(
            "Annual report The corporation shall submit to Congress an annual "
            "report during the preceding fiscal year under this section."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)
    shares = {item["family"]: float(item["share"]) for item in ranking}

    assert signals["has_deontic_report_duty_scope_phrase"] is True
    assert signals["has_temporal_fiscal_scope_phrase"] is True
    assert shares["deontic"] > shares["temporal"]


def test_spacy_codec_preserves_calendar_report_duty_over_temporal_notes() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="15",
        section="183",
        text=(
            "Report of statistics The Secretary of Commerce shall make a report "
            "to Congress on the first Monday of January in each year, containing "
            "the information collected during the preceding year. Historical and "
            "Revision Notes Based on title 15, U.S.C., 1940 ed., January 1, 1940."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)
    shares = {item["family"]: float(item["share"]) for item in ranking}

    assert signals["has_deontic_report_duty_scope_phrase"] is True
    assert signals["has_calendar_date_scope"] is True
    assert shares["deontic"] > shares["temporal"]
    assert ranking[0]["family"] == "deontic"


def test_spacy_codec_preserves_court_venue_duty_over_historical_dates() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="28",
        section="111",
        text=(
            "New Mexico constitutes one judicial district. Court shall be held "
            "at Albuquerque, Las Cruces, Santa Fe, and Silver City. Historical "
            "and Revision Notes Based on title 28, U.S.C., 1940 ed., June 20, "
            "1910, and June 25, 1948."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)
    shares = {item["family"]: float(item["share"]) for item in ranking}

    assert signals["has_deontic_court_venue_duty_scope_phrase"] is True
    assert signals["has_calendar_date_scope"] is True
    assert shares["deontic"] > shares["temporal"]
    assert ranking[0]["family"] == "deontic"


def test_spacy_codec_keeps_deadline_submit_clause_temporal() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="14",
        section="5113",
        text=(
            "Not later than 60 days after the date on which the President submits "
            "a budget, the Commandant shall submit the report."
        ),
    )
    ranking = ranked_modal_families(codec.encode_sample(sample))
    shares = {item["family"]: float(item["share"]) for item in ranking}

    assert shares["temporal"] > shares["deontic"]
    assert ranking[0]["family"] == "temporal"


def test_spacy_codec_reinforces_deontic_share_for_moderate_temporal_scope_with_explicit_cue() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="31",
        section="711a",
        text="Within 30 days after receipt, the agency issues a determination.",
    )
    competing = build_us_code_sample(
        title="31",
        section="711b",
        text="Within 30 days after receipt, the agency shall issue a determination.",
    )
    baseline_ranking = ranked_modal_families(codec.encode_sample(baseline))
    competing_ranking = ranked_modal_families(codec.encode_sample(competing))

    baseline_deontic_share = next(
        (
            float(item["share"])
            for item in baseline_ranking
            if item["family"] == "deontic"
        ),
        0.0,
    )
    competing_deontic_share = next(
        (
            float(item["share"])
            for item in competing_ranking
            if item["family"] == "deontic"
        ),
        0.0,
    )

    assert competing_deontic_share > baseline_deontic_share
    assert competing_deontic_share > 0.35


def test_spacy_codec_backfills_temporal_share_for_deontic_competition_with_calendar_scope() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="20",
        section="9150",
        text="The agency shall issue notice on January 1, 2030.",
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "temporal" for cue in encoding.cues)
    assert signals["has_deontic_cue"] is True
    assert signals["has_calendar_date_scope"] is True
    temporal_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "temporal"
    )
    assert temporal_share > 0.0


def test_spacy_codec_backfills_temporal_share_for_deontic_competition_with_dotted_month_calendar_scope() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="20",
        section="9150A",
        text="The agency shall issue notice on Oct. 6, 2006.",
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "temporal" for cue in encoding.cues)
    assert signals["has_deontic_cue"] is True
    assert signals["has_calendar_date_scope"] is True
    temporal_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "temporal"
    )
    assert temporal_share > 0.0


def test_spacy_codec_backfills_conditional_share_for_deontic_competition_with_statutory_scope() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="20",
        section="9151",
        text="The agency shall issue notice as provided in subsection (b).",
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "conditional_normative" for cue in encoding.cues)
    assert signals["has_deontic_cue"] is True
    assert signals["has_statutory_scope_reference"] is True
    conditional_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "conditional_normative"
    )
    assert conditional_share > 0.0


def test_spacy_codec_balances_frame_heavy_statutory_scope_with_normative_cues() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="25",
        section="310",
        text=(
            "The institute has authority, jurisdiction, articles of incorporation, "
            "and purposes of the corporation under this chapter. Subject to this "
            "section, the Secretary shall award grants."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)
    share_by_family = {
        str(item["family"]): float(item["share_raw"])
        for item in ranking
    }

    assert signals["has_frame_context"] is True
    assert signals["has_statutory_scope_reference"] is True
    assert signals["has_condition_or_exception_scope"] is True
    assert signals["has_deontic_cue"] is True
    assert share_by_family["deontic"] >= 0.30
    assert share_by_family["conditional_normative"] >= 0.28
    assert (
        share_by_family["frame"]
        - max(share_by_family["deontic"], share_by_family["conditional_normative"])
    ) < 0.1


def test_spacy_codec_backfills_conditional_share_for_single_frame_cue_with_statutory_scope() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="31",
        section="712",
        text="The authority shall apply as provided in subsection (b).",
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert signals["has_frame_cue"] is True
    assert signals["has_deontic_cue"] is True
    assert signals["has_statutory_scope_reference"] is True
    conditional_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "conditional_normative"
    )
    assert conditional_share > 0.0


def test_spacy_codec_prefers_conditional_share_for_frame_statutory_scope_with_explicit_conditional_phrase() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="31",
        section="712a",
        text=(
            "Authority and jurisdiction under this section, as provided in "
            "subsection (b), apply."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "conditional_normative" for cue in encoding.cues)
    assert signals["has_frame_cue"] is True
    assert signals["has_statutory_scope_reference"] is True
    assert signals["has_conditional_scope_phrase"] is True

    frame_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "frame"
    )
    conditional_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "conditional_normative"
    )
    assert conditional_share > frame_share


def test_spacy_codec_prefers_conditional_override_for_relationship_to_other_law() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="31",
        section="735",
        text=(
            "Relationship to other laws. Except as provided in this section, "
            "this subchapter does not affect any other provision of law. "
            "Except as specifically provided in this subchapter, those "
            "provisions do not change the application of a law applicable "
            "to officers and employees. Historical and Revision Notes."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)
    share_by_family = {
        str(item["family"]): float(item["share_raw"])
        for item in ranking
    }

    assert signals["has_frame_context"] is True
    assert signals["has_exception_clause"] is True
    assert signals["has_conditional_scope_phrase"] is True
    assert ranking[0]["family"] == "conditional_normative"
    assert share_by_family["conditional_normative"] > share_by_family["frame"]


def test_spacy_codec_avoids_conditional_backfill_for_bare_statutory_frame_scope() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="31",
        section="712b",
        text="Authority and jurisdiction under this section apply.",
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert signals["has_frame_cue"] is True
    assert signals["has_statutory_scope_reference"] is True
    assert signals["has_condition_clause"] is False
    assert signals["has_exception_clause"] is False
    assert signals["has_conditional_scope_phrase"] is False
    assert signals["has_conditional_scope_token"] is False

    frame_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "frame"
    )
    conditional_share = next(
        (
            float(item["share"])
            for item in ranking
            if item["family"] == "conditional_normative"
        ),
        0.0,
    )
    assert ranking[0]["family"] == "frame"
    assert frame_share > 0.9
    assert conditional_share == 0.0


def test_spacy_codec_backfills_epistemic_share_for_single_frame_cue_with_scope_phrase() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="31",
        section="713",
        text="The authority shall apply upon a formal finding that the applicant concealed facts.",
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert signals["has_frame_cue"] is True
    assert signals["has_deontic_cue"] is True
    assert signals["has_epistemic_scope"] is True
    epistemic_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "epistemic"
    )
    assert epistemic_share > 0.0


def test_spacy_codec_backfills_frame_share_for_statutory_reference_deontic_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="22",
        section="1642e",
        text="The Secretary shall administer this authority.",
    )
    competing = build_us_code_sample(
        title="22",
        section="1642e",
        text=(
            "The Secretary shall administer this authority under section 1642e "
            "of this title."
        ),
    )
    baseline_encoding = codec.encode_sample(baseline)
    competing_encoding = codec.encode_sample(competing)
    baseline_ranking = ranked_modal_families(baseline_encoding)
    competing_ranking = ranked_modal_families(competing_encoding)
    competing_signals = modal_ambiguity_signals(competing_encoding)

    baseline_frame_share = next(
        float(item["share"])
        for item in baseline_ranking
        if item["family"] == "frame"
    )
    competing_frame_share = next(
        float(item["share"])
        for item in competing_ranking
        if item["family"] == "frame"
    )
    assert competing_signals["has_statutory_scope_reference"] is True
    assert competing_signals["has_deontic_scope_phrase"] is False
    assert competing_ranking[0]["family"] == "deontic"
    assert competing_frame_share > baseline_frame_share


def test_spacy_codec_backfills_frame_share_for_statutory_deontic_scope_without_frame_lexemes() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="22",
        section="8005",
        text="Any person shall pay the fee under section 8005 of this title.",
    )
    encoding = codec.encode_sample(sample)
    ranking = ranked_modal_families(encoding)
    signals = modal_ambiguity_signals(encoding)

    shares = {str(item["family"]): float(item["share"]) for item in ranking}
    assert signals["has_statutory_scope_reference"] is True
    assert signals["has_deontic_scope"] is True
    assert signals["has_frame_context"] is False
    assert signals["has_frame_cue"] is False
    assert shares["frame"] > 0.0
    assert shares["deontic"] > shares["frame"]


def test_spacy_codec_keeps_deontic_dominant_for_statutory_reference_with_dense_frame_cues() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="22",
        section="1642f",
        text=(
            "Authority and jurisdiction and authority and jurisdiction under section "
            "1642f of this title shall apply."
        ),
    )
    ranking = ranked_modal_families(codec.encode_sample(sample))
    shares = {str(item["family"]): float(item["share"]) for item in ranking}

    assert ranking[0]["family"] == "deontic"
    assert shares["deontic"] > shares["frame"]


def test_spacy_codec_backfills_frame_share_for_statutory_reference_conditional_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="22",
        section="1642e",
        text="Authority under this chapter applies pursuant to subsection (b).",
    )
    encoding = codec.encode_sample(sample)
    ranking = ranked_modal_families(encoding)
    signals = modal_ambiguity_signals(encoding)

    frame_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "frame"
    )
    conditional_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "conditional_normative"
    )
    assert signals["has_statutory_scope_reference"] is True
    assert signals["has_condition_clause"] is False
    assert signals["has_exception_clause"] is False
    assert frame_share > 0.2
    assert conditional_share > frame_share


def test_spacy_codec_limits_statutory_frame_backfill_with_explicit_conditional_scope() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="22",
        section="1642g",
        text=(
            "Authority and jurisdiction under this section, as provided in subsection "
            "(b), impose liability for noncompliance."
        ),
    )
    encoding = codec.encode_sample(sample)
    ranking = ranked_modal_families(encoding)
    signals = modal_ambiguity_signals(encoding)

    frame_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "frame"
    )
    conditional_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "conditional_normative"
    )
    deontic_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "deontic"
    )

    assert signals["has_statutory_scope_reference"] is True
    assert signals["has_condition_or_exception_scope"] is True
    assert conditional_share > 0.3
    assert frame_share - conditional_share < 0.1
    assert deontic_share > 0.0


def test_spacy_codec_backfills_frame_share_for_dense_deontic_scope_with_frame_scope_phrase() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="22",
        section="1642e-1",
        text=(
            "The Secretary shall and must and shall provide notice in this former section."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "frame" for cue in encoding.cues)
    assert signals["has_frame_scope_phrase"] is True
    frame_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "frame"
    )
    assert frame_share > 0.0


def test_spacy_codec_backfills_deontic_share_for_frame_scope_with_deontic_tokens() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="12",
        section="1822",
        text=(
            "Authority and jurisdiction in this former section are mandatory for "
            "reporting."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "deontic" for cue in encoding.cues)
    assert signals["has_frame_scope_phrase"] is True
    assert signals["has_deontic_scope"] is True
    assert signals["has_statutory_scope_reference"] is False
    deontic_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "deontic"
    )
    assert deontic_share > 0.0


def test_spacy_codec_soft_caps_repeated_frame_share_for_deontic_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="12",
        section="1822a",
        text=(
            "Authority and jurisdiction and authority and jurisdiction and "
            "authority apply."
        ),
    )
    competing = build_us_code_sample(
        title="12",
        section="1822b",
        text=(
            "Authority and jurisdiction and authority and jurisdiction and "
            "authority shall apply."
        ),
    )
    baseline_ranking = ranked_modal_families(codec.encode_sample(baseline))
    competing_ranking = ranked_modal_families(codec.encode_sample(competing))

    baseline_frame_share = next(
        float(item["share"])
        for item in baseline_ranking
        if item["family"] == "frame"
    )
    competing_frame_share = next(
        float(item["share"])
        for item in competing_ranking
        if item["family"] == "frame"
    )
    competing_deontic_share = next(
        float(item["share"])
        for item in competing_ranking
        if item["family"] == "deontic"
    )

    assert competing_frame_share < baseline_frame_share
    assert competing_deontic_share > 0.15


def test_spacy_codec_strengthens_deontic_share_for_generic_frame_scope_with_penalty_terms() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="18",
        section="1792a",
        text="Authority and jurisdiction under this section apply.",
    )
    competing = build_us_code_sample(
        title="18",
        section="1792b",
        text=(
            "Authority and jurisdiction under this section apply, and violations are "
            "subject to criminal penalties."
        ),
    )
    baseline_ranking = ranked_modal_families(codec.encode_sample(baseline))
    competing_ranking = ranked_modal_families(codec.encode_sample(competing))

    baseline_deontic_share = next(
        (
            float(item["share"])
            for item in baseline_ranking
            if item["family"] == "deontic"
        ),
        0.0,
    )
    competing_deontic_share = next(
        (
            float(item["share"])
            for item in competing_ranking
            if item["family"] == "deontic"
        ),
        0.0,
    )
    assert competing_deontic_share > baseline_deontic_share
    assert competing_deontic_share > 0.0


def test_spacy_codec_preserves_conditional_penalty_scope_over_frame_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "If a vessel to which this chapter applies is operated in violation "
            "of this chapter, the owner is liable to the United States "
            "Government for a civil penalty."
        ),
        document_id="packet-000178-conditional-penalty-scope",
    )

    shares = {
        item["family"]: float(item["share"])
        for item in ranked_modal_families(encoding)
    }
    assert shares["conditional_normative"] > shares["frame"]
    assert shares["conditional_normative"] >= shares["deontic"]


def test_spacy_encoder_marks_direct_civil_penalty_liability_as_deontic() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The owner is liable for a civil penalty under this section.",
        document_id="packet-000178-direct-civil-penalty-liability",
    )

    assert any(
        cue.family == "deontic"
        and cue.cue.lower() == "liable for a civil penalty"
        for cue in encoding.cues
    )


def test_spacy_encoder_marks_public_interest_opinion_as_epistemic() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "The Secretary may, if in the opinion of the Secretary public "
            "interests require it, survey the lands and report to Congress."
        ),
        document_id="packet-000178-public-interest-opinion",
    )

    shares = {
        item["family"]: float(item["share"])
        for item in ranked_modal_families(encoding)
    }
    assert shares["epistemic"] > shares["deontic"]
    assert shares["epistemic"] > shares["conditional_normative"]


def test_spacy_encoder_marks_in_lieu_substitution_as_conditional_normative() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "Section provided that this chapter be in lieu of different "
            "provisions and shall not affect rights under applicable law."
        ),
        document_id="packet-000178-in-lieu-substitution",
    )

    assert any(
        cue.family == "conditional_normative"
        and cue.cue.lower() == "be in lieu of"
        for cue in encoding.cues
    )
    shares = {
        item["family"]: float(item["share"])
        for item in ranked_modal_families(encoding)
    }
    assert shares["conditional_normative"] > shares["deontic"]


def test_spacy_codec_limits_temporal_share_for_after_notice_procedural_scope() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="7",
        section="2009bb-13",
        text=(
            "The Secretary shall be subject to civil penalties not later than 30 days "
            "after notice and hearing under this section."
        ),
    )
    encoding = codec.encode_sample(sample)
    ranking = ranked_modal_families(encoding)

    shares = {str(item["family"]): float(item["share"]) for item in ranking}
    assert shares["temporal"] <= shares["deontic"] + 0.03
    assert shares["temporal"] <= shares["conditional_normative"] + 0.03


def test_spacy_codec_soft_caps_repeated_alethic_share_for_temporal_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="17",
        section="803",
        text=(
            "It is possible and necessary and impossible and possible and cannot comply."
        ),
    )
    competing = build_us_code_sample(
        title="17",
        section="803a",
        text=(
            "It is possible and necessary and impossible and possible and cannot "
            "comply after review."
        ),
    )
    baseline_ranking = ranked_modal_families(codec.encode_sample(baseline))
    competing_ranking = ranked_modal_families(codec.encode_sample(competing))

    baseline_alethic_share = next(
        float(item["share"])
        for item in baseline_ranking
        if item["family"] == "alethic"
    )
    competing_alethic_share = next(
        float(item["share"])
        for item in competing_ranking
        if item["family"] == "alethic"
    )
    competing_temporal_share = next(
        float(item["share"])
        for item in competing_ranking
        if item["family"] == "temporal"
    )

    assert competing_alethic_share < baseline_alethic_share
    assert competing_temporal_share > 0.2


def test_spacy_codec_backfills_temporal_share_for_frame_scope_with_temporal_tokens() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="12",
        section="1823",
        text=(
            "Authority and jurisdiction in this former section apply before annual "
            "review."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "temporal" for cue in encoding.cues)
    assert signals["has_frame_scope_phrase"] is True
    assert signals["has_temporal_scope"] is True
    assert signals["has_statutory_scope_reference"] is False
    temporal_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "temporal"
    )
    assert temporal_share > 0.0


def test_spacy_codec_backfills_alethic_share_for_frame_scope_with_alethic_tokens() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="12",
        section="1823a",
        text=(
            "Authority and jurisdiction in this former section apply while the "
            "agency is unable to comply."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "alethic" for cue in encoding.cues)
    assert signals["has_frame_scope_phrase"] is True
    assert signals["has_alethic_scope"] is True
    alethic_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "alethic"
    )
    assert alethic_share > 0.0


def test_spacy_codec_backfills_dynamic_share_for_frame_scope_with_dynamic_phrase() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="12",
        section="1823b",
        text=(
            "Authority and jurisdiction in this former section apply upon service."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "dynamic" for cue in encoding.cues)
    assert signals["has_frame_scope_phrase"] is True
    assert signals["has_dynamic_scope"] is True
    dynamic_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "dynamic"
    )
    assert dynamic_share > 0.0


def test_spacy_codec_backfills_temporal_share_for_dense_deontic_scope_with_temporal_scope_phrase() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="12",
        section="4405",
        text=(
            "The Secretary shall and must and shall and must issue notice "
            "while pending review."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "temporal" for cue in encoding.cues)
    assert signals["has_temporal_scope"] is True
    temporal_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "temporal"
    )
    assert temporal_share > 0.0


def test_spacy_codec_treats_during_as_temporal_scope_for_deontic_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="12",
        section="4405a",
        text=(
            "The Secretary shall and must and shall provide notice during review."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "temporal" for cue in encoding.cues)
    assert signals["has_temporal_scope"] is True
    temporal_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "temporal"
    )
    assert temporal_share > 0.0


def test_spacy_codec_backfills_dynamic_share_for_conditional_scope_with_dynamic_scope_phrase() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="14",
        section="905",
        text=(
            "If designated and except as otherwise provided, authority applies "
            "upon transfer."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "dynamic" for cue in encoding.cues)
    assert signals["has_dynamic_scope"] is True
    assert signals["has_condition_or_exception_scope"] is True
    dynamic_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "dynamic"
    )
    assert dynamic_share > 0.0


def test_spacy_codec_backfills_dynamic_share_for_single_conditional_scope_with_dynamic_phrase() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="14",
        section="905a",
        text="If designated, the notice applies upon service.",
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "dynamic" for cue in encoding.cues)
    assert signals["has_condition_or_exception_scope"] is True
    assert signals["has_dynamic_scope_phrase"] is True
    dynamic_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "dynamic"
    )
    assert dynamic_share > 0.0


def test_spacy_codec_backfills_dynamic_share_for_dense_deontic_scope_with_dynamic_scope_phrase() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="16",
        section="743",
        text=(
            "The Secretary shall and must and shall and must provide notice "
            "upon transfer."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "dynamic" for cue in encoding.cues)
    assert signals["has_dynamic_scope"] is True
    dynamic_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "dynamic"
    )
    assert dynamic_share > 0.0


def test_spacy_codec_backfills_conditional_share_for_dense_temporal_scope_with_condition_clause() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="21",
        section="404",
        text=(
            "When the application is complete, the notice is effective on first day "
            "and no later than January 1, 2030 after review."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "conditional_normative" for cue in encoding.cues)
    assert signals["has_condition_clause"] is True
    assert signals["has_temporal_scope"] is True
    conditional_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "conditional_normative"
    )
    assert conditional_share > 0.0


def test_spacy_codec_treats_as_provided_in_as_explicit_conditional_scope_phrase() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="21",
        section="404c",
        text=(
            "Within 30 days and no later than January 1, 2030, the effective date "
            "applies as provided in subsection (b)."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "conditional_normative" for cue in encoding.cues)
    assert signals["has_temporal_scope"] is True
    assert signals["has_statutory_scope_reference"] is True
    assert signals["has_conditional_scope_phrase"] is True
    conditional_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "conditional_normative"
    )
    assert conditional_share > 0.0


def test_spacy_codec_treats_provided_comma_that_as_explicit_conditional_scope_phrase() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="43",
        section="988",
        text=(
            "The grant shall not include lands: Provided , That the Secretary may "
            "issue notice under this section."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)

    conditional_cues = [
        cue.cue.lower()
        for cue in encoding.cues
        if cue.family == "conditional_normative"
    ]
    assert "provided , that" in conditional_cues
    assert signals["has_conditional_scope_phrase"] is True
    assert signals["has_condition_or_exception_scope"] is True


def test_spacy_codec_backfills_epistemic_share_for_dense_temporal_scope_with_epistemic_tokens() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="21",
        section="404a",
        text=(
            "Within 30 days and no later than January 1, 2030, the effective date "
            "is on or after review, and knowledge exists that filing is complete."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "epistemic" for cue in encoding.cues)
    assert signals["has_temporal_scope"] is True
    assert signals["has_epistemic_scope"] is True
    epistemic_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "epistemic"
    )
    assert epistemic_share > 0.0


def test_spacy_codec_backfills_temporal_share_for_dense_epistemic_scope_with_temporal_tokens() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="21",
        section="404b",
        text=(
            "Knowledge of the filing exists, and annual reports are due "
            "each year upon review."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "temporal" for cue in encoding.cues)
    assert signals["has_epistemic_scope"] is True
    assert signals["has_temporal_scope"] is True
    assert signals["has_temporal_scope_token"] is True
    temporal_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "temporal"
    )
    assert temporal_share > 0.0


def test_spacy_codec_backfills_frame_share_for_dense_temporal_scope_with_frame_context() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="12",
        section="1824",
        text=(
            "Within 30 days and no later than January 1, 2030, this former section "
            "is effective date."
        ),
    )
    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "frame" for cue in encoding.cues)
    assert signals["has_temporal_scope"] is True
    assert signals["has_frame_scope_phrase"] is True
    frame_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "frame"
    )
    assert frame_share > 0.15


def test_spacy_codec_strengthens_frame_share_for_sparse_frame_cues_in_dense_temporal_scope() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="12",
        section="1824a",
        text=(
            "Within 30 days and no later than January 1, 2030, this authority "
            "remains effective."
        ),
    )
    competing = build_us_code_sample(
        title="12",
        section="1824b",
        text=(
            "Within 30 days and no later than January 1, 2030, this authority "
            "remains effective under this section."
        ),
    )
    baseline_encoding = codec.encode_sample(baseline)
    competing_encoding = codec.encode_sample(competing)
    baseline_signals = modal_ambiguity_signals(baseline_encoding)
    competing_signals = modal_ambiguity_signals(competing_encoding)
    baseline_ranking = ranked_modal_families(baseline_encoding)
    competing_ranking = ranked_modal_families(competing_encoding)

    baseline_frame_share = next(
        float(item["share"])
        for item in baseline_ranking
        if item["family"] == "frame"
    )
    competing_frame_share = next(
        float(item["share"])
        for item in competing_ranking
        if item["family"] == "frame"
    )
    assert baseline_signals["has_temporal_scope"] is True
    assert competing_signals["has_temporal_scope"] is True
    assert baseline_signals["has_statutory_scope_reference"] is False
    assert competing_signals["has_statutory_scope_reference"] is True
    assert baseline_ranking[0]["family"] == "temporal"
    assert competing_ranking[0]["family"] == "temporal"
    assert competing_frame_share > baseline_frame_share


def test_spacy_encoder_extracts_conditional_terms_and_conditions_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The Secretary shall and must act under such terms and conditions as the Secretary prescribes.",
        document_id="sample-terms-and-conditions-conditional",
    )

    assert any(
        cue.family == "conditional_normative"
        and cue.cue.lower() == "under such terms and conditions"
        for cue in encoding.cues
    )


def test_spacy_encoder_extracts_conditional_subject_to_terms_and_conditions_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "The Secretary shall act subject to such terms and conditions as the "
            "Secretary determines."
        ),
        document_id="sample-subject-to-terms-and-conditions-conditional",
    )

    assert any(
        cue.family == "conditional_normative"
        and cue.cue.lower() == "subject to such terms and conditions"
        for cue in encoding.cues
    )


def test_spacy_modal_signals_treat_subject_to_subsection_as_conditional_scope_phrase() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "The agency shall issue notice subject to subsection (b) under this section."
        ),
        document_id="sample-subject-to-subsection-conditional-scope",
    )
    signals = modal_ambiguity_signals(encoding)

    assert any(
        cue.family == "conditional_normative"
        and cue.cue.lower() == "subject to subsection"
        for cue in encoding.cues
    )
    assert signals["has_conditional_scope_phrase"] is True
    assert signals["has_condition_or_exception_scope"] is True


def test_spacy_encoder_extracts_conditional_scope_cues_from_statutory_phrases() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "Notwithstanding subsection (b), for purposes of this section the agency "
            "shall act."
        ),
        document_id="sample-conditional-statutory-phrases",
    )

    assert any(
        cue.family == "conditional_normative"
        and cue.cue.lower() == "notwithstanding"
        for cue in encoding.cues
    )
    assert any(
        cue.family == "conditional_normative"
        and cue.cue.lower() == "for purposes of"
        for cue in encoding.cues
    )
    signals = modal_ambiguity_signals(encoding)
    assert signals["has_purpose_scope_phrase"] is True


def test_spacy_encoder_extracts_dynamic_transfer_and_vesting_cues() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "There are transferred to and vested in the Secretary all functions "
            "relating to administration."
        ),
        document_id="sample-dynamic-transfer-vesting",
    )

    assert any(
        cue.family == "dynamic"
        and cue.cue.lower() == "transferred to and vested in"
        for cue in encoding.cues
    )


def test_spacy_encoder_extracts_temporal_scope_cues_from_deadline_phrases() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "Authority under this section applies not later than 30 days after the "
            "effective date."
        ),
        document_id="sample-temporal-deadline-phrases",
    )

    assert any(
        cue.family == "temporal"
        and cue.cue.lower() == "not later than"
        for cue in encoding.cues
    )
    assert any(
        cue.family == "temporal"
        and cue.cue.lower() == "effective date"
        for cue in encoding.cues
    )


def test_spacy_encoder_extracts_temporal_cues_from_succeeding_fiscal_year_phrases() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "Authority under this section applies for each succeeding fiscal year "
            "thereafter."
        ),
        document_id="sample-temporal-succeeding-fiscal-year-phrases",
    )

    assert any(
        cue.family == "temporal"
        and cue.cue.lower() == "for each succeeding fiscal year"
        for cue in encoding.cues
    )


def test_spacy_codec_strengthens_temporal_share_for_frame_context_with_succeeding_fiscal_year_phrase() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    baseline = build_us_code_sample(
        title="31",
        section="7200a",
        text="Authority and jurisdiction under this section apply.",
    )
    competing = build_us_code_sample(
        title="31",
        section="7200b",
        text=(
            "Authority and jurisdiction under this section apply for each succeeding "
            "fiscal year thereafter."
        ),
    )

    baseline_ranking = ranked_modal_families(codec.encode_sample(baseline))
    competing_ranking = ranked_modal_families(codec.encode_sample(competing))
    baseline_temporal_share = next(
        (
            float(item["share"])
            for item in baseline_ranking
            if item["family"] == "temporal"
        ),
        0.0,
    )
    competing_temporal_share = next(
        float(item["share"])
        for item in competing_ranking
        if item["family"] == "temporal"
    )

    assert competing_temporal_share > baseline_temporal_share


def test_spacy_encoder_extracts_deontic_obligation_phrase_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The agency is under an obligation to provide notice.",
        document_id="sample-deontic-obligation-phrase",
    )

    assert any(
        cue.family == "deontic"
        and cue.cue.lower() == "under an obligation to"
        for cue in encoding.cues
    )


def test_spacy_encoder_avoids_alethic_may_be_cue_in_permission_context() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The Secretary may be authorized to issue the permit if review is complete.",
        document_id="sample-may-be-permission-context",
    )

    assert any(
        cue.family == "deontic" and cue.cue.lower() == "may"
        for cue in encoding.cues
    )
    assert not any(
        cue.family == "alethic" and cue.cue.lower() == "may be"
        for cue in encoding.cues
    )


def test_spacy_signals_mark_authorized_and_empowered_as_structural_frame_scope() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "The Secretary is authorized and empowered, in his discretion, "
            "to conduct the survey."
        ),
        document_id="sample-authorized-empowered-structural-frame-scope",
    )

    signals = modal_ambiguity_signals(encoding)
    assert signals["has_deontic_cue"] is True
    assert signals["has_frame_context"] is True
    assert signals["has_frame_structural_authority_scope_phrase"] is True


def test_directional_backfill_reinforces_deontic_to_frame_for_structural_authority_scope() -> None:
    counts = {
        "deontic": 1.0,
        "frame": 0.0,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_cue": True,
        "has_frame_context": True,
        "has_frame_scope_phrase": False,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_structural_authority_scope_phrase": True,
        "has_statutory_scope_reference": False,
    }

    _apply_directional_modal_family_pair_backfill(counts, signals)
    assert counts["frame"] == pytest.approx(0.2)


def test_spacy_encoder_treats_the_following_as_non_temporal_list_intro() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The following shall apply: (1) recordkeeping requirements; (2) audit procedures.",
        document_id="sample-following-list-intro",
    )

    assert not any(
        cue.family == "temporal" and cue.cue.lower() == "following"
        for cue in encoding.cues
    )


def test_spacy_encoder_treats_following_section_reference_as_non_temporal_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The requirements in the following section shall apply to the agency.",
        document_id="sample-following-section-reference",
    )

    assert not any(
        cue.family == "temporal" and cue.cue.lower() == "following"
        for cue in encoding.cues
    )


def test_spacy_encoder_treats_editorial_after_reference_as_non_temporal_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "Section 83 of this title after editorial reclassification shall apply.",
        document_id="sample-after-editorial-reference",
    )

    assert not any(
        cue.family == "temporal" and cue.cue.lower() == "after"
        for cue in encoding.cues
    )


def test_spacy_encoder_treats_after_notice_scope_as_non_temporal_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "A civil penalty shall apply after notice and hearing under this section.",
        document_id="sample-after-notice-hearing-reference",
    )

    assert not any(
        cue.family == "temporal" and cue.cue.lower() == "after"
        for cue in encoding.cues
    )


def test_spacy_encoder_treats_by_secretary_may_as_non_temporal_deadline_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "The regulatory authority with approval by the Secretary may authorize "
            "departures in individual cases."
        ),
        document_id="sample-by-secretary-may-non-temporal",
    )

    assert not any(
        cue.family == "temporal" and cue.cue.lower() == "by"
        for cue in encoding.cues
    )
    assert any(
        cue.family == "deontic" and cue.cue.lower() == "may"
        for cue in encoding.cues
    )


def test_spacy_encoder_treats_by_promulgated_standards_with_citation_date_as_non_temporal_deadline_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "The public health protection provided by promulgated standards shall apply. "
            "(Pub. L. 95-87, title VII, sec. 711, Aug. 3, 1977, 91 Stat. 523.)"
        ),
        document_id="sample-by-promulgated-standards-non-temporal",
    )

    assert not any(
        cue.family == "temporal" and cue.cue.lower() == "by"
        for cue in encoding.cues
    )


def test_spacy_encoder_extracts_conditional_cue_except_as_provided_in() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "Except as provided in subsection (b), the Secretary shall issue a determination.",
        document_id="sample-except-as-provided-in",
    )

    assert any(
        cue.family == "conditional_normative"
        and cue.cue.lower() == "except as provided in"
        for cue in encoding.cues
    )


def test_spacy_encoder_extracts_conditional_cue_except_as_provided_by() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "Except as provided by subsection (b), the Secretary shall issue a determination.",
        document_id="sample-except-as-provided-by",
    )

    assert any(
        cue.family == "conditional_normative"
        and cue.cue.lower() == "except as provided by"
        for cue in encoding.cues
    )


def test_spacy_encoder_extracts_conditional_cue_does_not_affect() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "This subchapter does not affect chapter 5 of title 5.",
        document_id="sample-does-not-affect-conditional",
    )

    assert any(
        cue.family == "conditional_normative"
        and cue.cue.lower() == "does not affect"
        for cue in encoding.cues
    )


def test_spacy_codec_collapses_nested_conditional_cues_in_weighted_family_ranking() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "Except as provided by subsection (b), this authority applies not later "
            "than 30 days after enactment."
        ),
        document_id="sample-nested-conditional-cues",
    )

    conditional_cues = [
        cue for cue in encoding.cues if cue.family == "conditional_normative"
    ]
    ranking = ranked_modal_families(encoding)
    shares = {str(item["family"]): float(item["share"]) for item in ranking}

    assert len(conditional_cues) >= 3
    assert ranking[0]["family"] == "temporal"
    assert shares["temporal"] > shares["conditional_normative"]


def test_spacy_codec_collapses_nested_same_family_cues_for_weighted_logits() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="5",
        section="500",
        text="The agency must not provide notice by January 1, 2030.",
    )
    encoding = codec.encode_sample(sample)
    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("deontic", "temporal"),
    )

    assert any(
        cue.family == "deontic" and cue.cue.lower() == "must not"
        for cue in encoding.cues
    )
    assert any(
        cue.family == "deontic" and cue.cue.lower() == "must"
        for cue in encoding.cues
    )
    assert logits["deontic"] == logits["temporal"]


def test_spacy_encoder_extracts_temporal_cues_from_recurring_effective_date_phrases() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "The amendment shall apply from time to time and take effect on first day "
            "of each applicable pay period beginning on or after January 1, 2030."
        ),
        document_id="sample-temporal-recurring-effective-date-phrases",
    )

    assert any(
        cue.family == "temporal"
        and cue.cue.lower() == "from time to time"
        for cue in encoding.cues
    )
    assert any(
        cue.family == "temporal"
        and cue.cue.lower() in {"on or after", "beginning on or after"}
        for cue in encoding.cues
    )


def test_spacy_decoder_reinforces_deontic_scope_for_office_tenure_successor_clauses() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="2",
        section="5602",
        text=(
            "Any person duly elected and qualified as Sergeant at Arms of the House of "
            "Representatives shall continue in said office until his successor is chosen "
            "and qualified, subject however, to removal by the House of Representatives."
        ),
    )

    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("deontic", "temporal"),
    )

    assert signals["has_deontic_scope_phrase"] is True
    assert logits["deontic"] > logits["temporal"]


def test_spacy_decoder_treats_until_expended_as_strong_temporal_scope_phrase() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="25",
        section="123b",
        text="Amounts appropriated under this section shall remain available until expended.",
    )

    encoding = codec.encode_sample(sample)
    signals = modal_ambiguity_signals(encoding)
    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("deontic", "temporal"),
    )

    assert signals["has_temporal_scope_phrase"] is True
    assert signals["has_temporal_expended_scope_phrase"] is True
    assert logits["temporal"] > logits["deontic"]


def test_spacy_encoder_extracts_epistemic_cues_for_knowledge_and_belief() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "A person with knowledge of the violation has reason to believe the report is false.",
        document_id="sample-knowledge-belief",
    )

    assert any(
        cue.family == "epistemic"
        and cue.cue.lower() in {"knowledge of", "has reason to believe"}
        for cue in encoding.cues
    )


def test_spacy_compiler_replays_uscode_editorial_status_zero_formula_cases() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-2-117j-0f405de004ab24ed",
            "2 U.S.C. 117j",
            "\u00a7117j. Omitted.",
        ),
        (
            "us-code-7-450-759794f8a1f6176f",
            "7 U.S.C. 450",
            "\u00a7450. Omitted.",
        ),
        (
            "us-code-8-71-ba23a2579e9f7282",
            "8 U.S.C. 71",
            "\u00a771. Omitted.",
        ),
    ]

    for document_id, citation, text in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_editorial_status_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_editorial_status_heading_v1"
        assert fallback.metadata["status_keyword"] == "omitted"
        assert fallback.provenance.citation == citation


def test_spacy_compiler_ignores_historical_authorized_cue_in_repealed_section_notes() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    text = (
        "§§9881 to 9887. Repealed. Pub. L. 103-252, title I, "
        "§§112(b)(1), (2)(B), May 18, 1994, 108 Stat. 640, 641 "
        "Section 9881, Pub. L. 97-35, title VI, §670N, as added "
        "Pub. L. 100-297, title II, §2503, Apr. 28, 1988, "
        "102 Stat. 326, authorized Community Services Block Grant "
        "program coordination."
    )

    modal_ir = compiler.compile(
        encoder.encode(
            text,
            document_id="us-code-42-9881-to-9887-packet-000124",
            citation="42 U.S.C. 9881 to 9887.",
            source="us_code",
        )
    )

    assert not any(
        formula.operator.family == "deontic"
        and str(formula.metadata.get("cue", "")).lower() == "authorized"
        for formula in modal_ir.formulas
    )
    fallback_rules = {
        str(formula.metadata.get("fallback_rule"))
        for formula in modal_ir.formulas
    }
    assert "uscode_editorial_status_heading_v1" in fallback_rules
    assert "uscode_residual_span_coverage_v1" in fallback_rules


def test_spacy_and_regex_compilers_treat_repealed_required_history_as_frame() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    regex_parser = LegalModalParser()
    text = (
        "§1411d. Repealed. Pub. L. 93–383, title II, §204, Aug. 22, "
        "1974, 88 Stat. 668 Section, act Aug. 2, 1954, ch. 649, title "
        "VIII, §815, 68 Stat. 647, required submission of specifications "
        "by applicants prior to award of any contract for construction of "
        "a project and submission of data with respect to acquisition of "
        "land prior to authorization to purchase such land."
    )

    spacy_ir = compiler.compile(
        encoder.encode(
            text,
            document_id="us-code-42-1411d-packet-000441",
            citation="42 U.S.C. 1411d.",
            source="us_code",
        )
    )
    regex_ir = regex_parser.parse(
        text,
        document_id="us-code-42-1411d-packet-000441",
        citation="42 U.S.C. 1411d.",
        source="us_code",
    )

    for modal_ir in (spacy_ir, regex_ir):
        assert not any(
            formula.operator.family in {"conditional_normative", "deontic", "temporal"}
            for formula in modal_ir.formulas
        )
        assert any(
            formula.metadata.get("fallback_rule")
            == "uscode_editorial_status_heading_v1"
            for formula in modal_ir.formulas
        )
        assert any(
            formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
            and "required submission of specifications"
            in modal_ir.normalized_text[
                formula.provenance.start_char : formula.provenance.end_char
            ]
            for formula in modal_ir.formulas
        )


def test_spacy_compiler_replays_sec_prefixed_transferred_heading_zero_formula_cases() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-2-123b-a41bd4aaf77abbf3",
            "2 U.S.C. 123b",
            "Sec. 123b - Transferred.",
        ),
        (
            "us-code-25-478-ebbb6cefef299fc2",
            "25 U.S.C. 478",
            "Sec. 478 - Transferred.",
        ),
    ]

    for document_id, citation, text in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_codification_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_transferred_heading_v1"
        assert fallback.provenance.citation == citation


def test_spacy_and_regex_parsers_ignore_editorial_history_authorized_cues() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    regex_parser = LegalModalParser()
    cases = [
        (
            _USCODE_16_431_PACKET_2400_TEXT,
            "us-code-16-431-715f8a7a6ba4bc2b",
            "16 U.S.C. 431",
        ),
        (
            _USCODE_16_590R_PACKET_2400_TEXT,
            "us-code-16-590r-e49058a68f67bb60",
            "16 U.S.C. 590r",
        ),
    ]

    for text, document_id, citation in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        assert not any(
            cue.family == "deontic" and cue.cue.lower() == "authorized"
            for cue in encoding.cues
        )

        spacy_ir = compiler.compile(encoding)
        regex_ir = regex_parser.parse(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )

        for modal_ir in (spacy_ir, regex_ir):
            assert not any(
                formula.operator.family == "deontic"
                and formula.metadata.get("cue") == "authorized"
                for formula in modal_ir.formulas
            )
            assert any(
                formula.operator.family == "frame"
                and formula.metadata.get("fallback_rule")
                == "uscode_editorial_status_heading_v1"
                for formula in modal_ir.formulas
            )


def test_spacy_compiler_adds_residual_span_coverage_before_codification_fallback_for_50_2523b_style_text() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    encoding = encoder.encode(
        _USCODE_50_2523B_RESIDUAL_SPAN_TEXT,
        document_id="us-code-50-2523b.-9372ed91908bfe9a",
        citation="50 U.S.C. 2523b.",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    assert modal_ir.formulas
    assert len({formula.formula_id for formula in modal_ir.formulas}) == len(modal_ir.formulas)
    fallback = modal_ir.formulas[-1]
    assert fallback.operator.family == "frame"
    assert fallback.metadata["cue"] == "__uscode_codification_fallback__"
    residual_formulas = [
        formula
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    ]
    assert residual_formulas
    assert all(
        formula.provenance.citation == "50 U.S.C. 2523b."
        for formula in modal_ir.formulas
    )


def test_spacy_compiler_adds_administrative_notice_hearing_residual_span_coverage() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    encoding = encoder.encode(
        _USCODE_10_3101_ADMINISTRATIVE_RESIDUAL_SPAN_TEXT,
        document_id="us-code-10-3101-000d4c508496a464",
        citation="10 U.S.C. 3101",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    assert modal_ir.formulas
    residual_formulas = [
        formula
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    ]
    assert residual_formulas
    residual_text_spans = {
        modal_ir.normalized_text[
            int(formula.provenance.start_char) : int(formula.provenance.end_char)
        ].strip()
        for formula in residual_formulas
    }
    assert (
        "Administrative notice and hearing procedures for eligibility review and petition records."
        in residual_text_spans
    )
    assert all(
        formula.provenance.citation == "10 U.S.C. 3101"
        for formula in modal_ir.formulas
    )


def test_spacy_compiler_adds_administrative_proceeding_record_residual_span_coverage() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    encoding = encoder.encode(
        _USCODE_ADMINISTRATIVE_PROCEEDING_RESIDUAL_SPAN_TEXT,
        document_id="us-code-45-1116.-5646808ce5a8b0a2",
        citation="45 U.S.C. 1116.",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    residual_formulas = [
        formula
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    ]
    assert residual_formulas
    residual_text_spans = {
        modal_ir.normalized_text[
            int(formula.provenance.start_char) : int(formula.provenance.end_char)
        ].strip()
        for formula in residual_formulas
    }
    assert (
        "Notice of proceeding and hearing records for investigation testimony."
        in residual_text_spans
    )


def test_spacy_compiler_adds_public_review_recommendation_residual_span_coverage() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    text = (
        "Sec. 433a - Recommendations and reports. "
        "Environmental impact recommendations and reports for public review."
    )
    encoding = encoder.encode(
        text,
        document_id="us-code-43-433a-public-review-residual",
        citation="43 U.S.C. 433a.",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    residual_text_spans = {
        modal_ir.normalized_text[
            int(formula.provenance.start_char) : int(formula.provenance.end_char)
        ].strip()
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    }

    assert (
        "Environmental impact recommendations and reports for public review."
        in residual_text_spans
    )


def test_spacy_compiler_adds_administrative_approval_residual_span_coverage_for_packet_005219_shape() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    text = (
        "The Secretary shall prescribe procedures. "
        "Peer review records. "
        "Secretarial approval records."
    )
    encoding = encoder.encode(
        text,
        document_id="us-code-42-6395-packet-005219-spacy",
        citation="42 U.S.C. 6395.",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    residual_text_spans = {
        modal_ir.normalized_text[
            formula.provenance.start_char : formula.provenance.end_char
        ].strip()
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    }

    assert "Secretarial approval records." in residual_text_spans


def test_spacy_compiler_adds_report_heading_residual_span_coverage() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    encoding = encoder.encode(
        _USCODE_44_3558_REPORTS_RESIDUAL_SPAN_TEXT,
        document_id="us-code-44-3558.-9af6ffad8db763d4",
        citation="44 U.S.C. 3558.",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    residual_formulas = [
        formula
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    ]
    residual_text_spans = {
        modal_ir.normalized_text[
            int(formula.provenance.start_char) : int(formula.provenance.end_char)
        ].strip()
        for formula in residual_formulas
    }
    assert "Congressional notification and reports." in residual_text_spans


def test_spacy_compiler_adds_savings_effect_residual_span_coverage() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    encoding = encoder.encode(
        _USCODE_SAVINGS_EFFECT_RESIDUAL_TEXT,
        document_id="us-code-42-18726-savings-effect-residual",
        citation="42 U.S.C. 18726",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    residual_text_spans = {
        modal_ir.normalized_text[
            int(formula.provenance.start_char) : int(formula.provenance.end_char)
        ].strip()
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    }

    assert (
        "Nothing in this part affects any other provision of law of "
        "a Federal department or agency."
    ) in residual_text_spans


def test_spacy_compiler_adds_cost_analysis_residual_span_coverage() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    text = (
        "Sec. 1544 - Annual cost analysis by Fish and Wildlife Service. "
        "Cost analysis."
    )
    encoding = encoder.encode(
        text,
        document_id="us-code-16-1544-cost-analysis-residual",
        citation="16 U.S.C. 1544",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    residual_text_spans = {
        modal_ir.normalized_text[
            int(formula.provenance.start_char) : int(formula.provenance.end_char)
        ].strip()
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    }

    assert "Cost analysis." in residual_text_spans


def test_spacy_compiler_preserves_coalesced_semicolon_uscode_catchline_coverage() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    text = (
        "U.S.C. Title 30 - MINERAL LANDS AND MINING 30 U.S.C. "
        "United States Code, 2024 Edition Title 30 - MINERAL LANDS AND "
        "MINING CHAPTER 13 - CONTROL OF COAL-MINE FIRES Sec. 553 - "
        "Duties of Secretary; surveys, research, etc.; projects From "
        "the U.S. Government Publishing Office, www.gpo.gov §553. "
        "Duties of Secretary; surveys, research, etc.; projects The "
        "Secretary of the Interior is hereby authorized to conduct surveys."
    )
    encoding = encoder.encode(
        text,
        document_id="us-code-30-553-semicolon-catchline",
        citation="30 U.S.C. 553",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    catchline_spans = {
        modal_ir.normalized_text[
            int(formula.provenance.start_char) : int(formula.provenance.end_char)
        ].strip()
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule")
        == "uscode_section_catchline_coverage_v1"
    }
    residual_spans = {
        modal_ir.normalized_text[
            int(formula.provenance.start_char) : int(formula.provenance.end_char)
        ].strip()
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    }

    assert "Duties of Secretary; surveys, research, etc.; projects" in catchline_spans
    assert any("surveys, research, etc.; projects" in span for span in residual_spans)


def test_spacy_compiler_covers_packet_000161_subsection_heading_spans() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    text = (
        "10 U.S.C. 2263: Sec. 2263 - United States contributions to the "
        "North Atlantic Treaty Organization common-funded budgets §2263. "
        "United States contributions to the North Atlantic Treaty Organization "
        "common-funded budgets (a) In General .-The total amount contributed "
        "by the Secretary of Defense in any fiscal year for the common-funded "
        "budgets of NATO may be an amount in excess of the maximum amount "
        "that would otherwise be applicable to those contributions in such "
        "fiscal year under the fiscal year 1998 baseline limitation."
    )
    encoding = encoder.encode(
        text,
        document_id="us-code-10-2263-571407a5044f94b2",
        citation="10 U.S.C. 2263",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    subsection_heading_spans = {
        modal_ir.normalized_text[
            int(formula.provenance.start_char) : int(formula.provenance.end_char)
        ].strip()
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule")
        == "uscode_subsection_heading_coverage_v1"
    }

    assert "(a) In General ." in subsection_heading_spans


def test_spacy_compiler_covers_packet_000162_section_marker_spans() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    text = (
        "10 U.S.C. 2263: Sec. 2263 - United States contributions to the "
        "North Atlantic Treaty Organization common-funded budgets §2263. "
        "United States contributions to the North Atlantic Treaty Organization "
        "common-funded budgets (a) In General .-The total amount contributed "
        "by the Secretary of Defense in any fiscal year for the common-funded "
        "budgets of NATO may be an amount in excess of the maximum amount "
        "that would otherwise be applicable to those contributions in such "
        "fiscal year under the fiscal year 1998 baseline limitation."
    )
    encoding = encoder.encode(
        text,
        document_id="us-code-10-2263-571407a5044f94b2",
        citation="10 U.S.C. 2263",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    marker_spans = {
        modal_ir.normalized_text[
            int(formula.provenance.start_char) : int(formula.provenance.end_char)
        ].strip()
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule")
        == "uscode_section_marker_coverage_v1"
    }

    assert "Sec. 2263 -" in marker_spans
    assert "§2263." in marker_spans


def test_spacy_compiler_adds_packet_000004_short_structural_heading_spans() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    text = (
        "§52. Dissemination of false advertisements "
        "(a) Unlawfulness It shall be unlawful to disseminate false advertisements. "
        '"(2) Requirements . The Commission shall include consumer information. '
        '"(b) Database . The Commission shall establish a national database. '
        "(c) Definition of Political Appointee . In this section, the term "
        '"political appointee" means an employee appointed by the Secretary.'
    )
    encoding = encoder.encode(
        text,
        document_id="us-code-packet-000004-structural-headings",
        citation="15 U.S.C. 52",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    residual_text_spans = {
        modal_ir.normalized_text[
            int(formula.provenance.start_char) : int(formula.provenance.end_char)
        ].strip()
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    }

    assert "2) Requirements ." in residual_text_spans
    assert "b) Database ." in residual_text_spans
    assert "c) Definition of Political Appointee ." in residual_text_spans


def test_spacy_compiler_adds_compact_administration_heading_span_coverage() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    text = (
        "Administration. "
        "The Secretary shall issue regulations for the park area."
    )
    encoding = encoder.encode(
        text,
        document_id="us-code-16-450dd-1-compact-administration",
        citation="16 U.S.C. 450dd-1",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    frame_coverage_text_spans = {
        modal_ir.normalized_text[
            int(formula.provenance.start_char) : int(formula.provenance.end_char)
        ].strip()
        for formula in modal_ir.formulas
        if formula.operator.family == "frame"
        and formula.metadata.get("fallback_rule")
        in {
            "uscode_modal_heading_prefix_coverage_v1",
            "uscode_residual_span_coverage_v1",
        }
    }

    assert "Administration." in frame_coverage_text_spans


def test_spacy_compiler_adds_criminal_penalty_enforcement_residual_span_coverage() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    text = (
        "Civil enforcement. "
        "The Secretary shall maintain records for criminal penalties."
    )
    encoding = encoder.encode(
        text,
        document_id="us-code-50-2205.-44bac97fa2b482ea",
        citation="50 U.S.C. 2205.",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    frame_coverage_text_spans = {
        modal_ir.normalized_text[
            int(formula.provenance.start_char) : int(formula.provenance.end_char)
        ].strip()
        for formula in modal_ir.formulas
        if formula.operator.family == "frame"
        and formula.metadata.get("fallback_rule")
        in {
            "uscode_modal_heading_prefix_coverage_v1",
            "uscode_residual_span_coverage_v1",
        }
    }

    assert "Civil enforcement." in frame_coverage_text_spans


def test_spacy_compiler_adds_modal_heading_prefix_coverage_for_penalty_heading() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    text = (
        "§542. Unauthorized aids to maritime navigation; penalty "
        "No person shall establish an aid without authority."
    )
    encoding = encoder.encode(
        text,
        document_id="us-code-14-542-heading-prefix",
        citation="14 U.S.C. 542",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    prefix_formulas = [
        formula
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule")
        == "uscode_modal_heading_prefix_coverage_v1"
    ]
    assert prefix_formulas
    prefix_spans = {
        modal_ir.normalized_text[
            int(formula.provenance.start_char) : int(formula.provenance.end_char)
        ].strip()
        for formula in prefix_formulas
    }
    assert "Unauthorized aids to maritime navigation;" in prefix_spans


def test_spacy_compiler_adds_modal_heading_prefix_coverage_for_security_evaluations() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    text = (
        "§2210d. Security evaluations (a) Security response evaluations "
        "Not less often than once every 3 years, the Commission shall "
        "conduct security evaluations."
    )
    encoding = encoder.encode(
        text,
        document_id="us-code-42-2210d-heading-prefix",
        citation="42 U.S.C. 2210d.",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    prefix_formulas = [
        formula
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule")
        == "uscode_modal_heading_prefix_coverage_v1"
    ]
    assert prefix_formulas
    prefix_spans = {
        modal_ir.normalized_text[
            int(formula.provenance.start_char) : int(formula.provenance.end_char)
        ].strip()
        for formula in prefix_formulas
    }
    assert "Security response evaluations" in prefix_spans


def test_spacy_compiler_replays_sec_prefixed_heading_zero_formula_sample_for_15_1693l() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    encoding = encoder.encode(
        "Sec. 1693l - Waiver of rights.",
        document_id="us-code-15-1693l-62b207bc138a3216",
        citation="15 U.S.C. 1693l",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    assert modal_ir.formulas
    fallback = modal_ir.formulas[-1]
    assert fallback.operator.family == "frame"
    assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
    assert fallback.metadata["fallback_rule"] == "uscode_section_heading_v1"
    assert fallback.provenance.citation == "15 U.S.C. 1693l"


def test_spacy_compiler_replays_packet_todo_samples_for_7_431_6_257_and_45_81_to_92() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-7-431-b2d3ec880a4d889f",
            "7 U.S.C. 431",
            _USCODE_7_431_TODO_TEXT,
            "__uscode_section_heading_fallback__",
            "uscode_section_heading_v1",
            "",
        ),
        (
            "us-code-6-257-73184bd2fbf238f5",
            "6 U.S.C. 257",
            _USCODE_6_257_TODO_TEXT,
            "__uscode_section_heading_fallback__",
            "uscode_section_heading_v1",
            "",
        ),
        (
            "us-code-45-81 to 92.-1562d5d82d7f6c80",
            "45 U.S.C. §§ 81 to 92.",
            _USCODE_45_81_TO_92_TODO_TEXT,
            "__uscode_editorial_status_fallback__",
            "uscode_editorial_status_heading_v1",
            "repealed",
        ),
    ]

    for document_id, citation, text, cue, fallback_rule, status_keyword in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == cue
        assert fallback.metadata["fallback_rule"] == fallback_rule
        if status_keyword:
            assert fallback.metadata["status_keyword"] == status_keyword
        assert fallback.provenance.citation == citation


def test_spacy_compiler_replays_packet_todo_samples_for_46_55318_8_606_and_46_115() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-46-55318.-a7002ab697067d67",
            "46 U.S.C. 55318.",
            _USCODE_46_55318_TODO_TEXT,
            "__uscode_section_heading_fallback__",
            "uscode_section_heading_v1",
        ),
        (
            "us-code-8-606-f7dcbbfb006072f7",
            "8 U.S.C. 606",
            _USCODE_8_606_TODO_TEXT,
            "__uscode_codification_fallback__",
            "uscode_transferred_heading_v1",
        ),
        (
            "us-code-46-115.-286a747a33fe04bb",
            "46 U.S.C. 115.",
            _USCODE_46_115_TODO_TEXT,
            "__uscode_section_heading_fallback__",
            "uscode_section_heading_v1",
        ),
    ]

    for document_id, citation, text, cue, fallback_rule in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == cue
        assert fallback.metadata["fallback_rule"] == fallback_rule
        assert fallback.provenance.citation == citation


def test_spacy_compiler_replays_packet_todo_samples_for_36_110105_and_25_450() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-36-110105-c16a1da4a57f02ec",
            "36 U.S.C. 110105",
            _USCODE_36_110105_TODO_TEXT,
            "__uscode_section_heading_fallback__",
            "uscode_section_heading_v1",
        ),
        (
            "us-code-25-450-c265a65e885d4655",
            "25 U.S.C. 450",
            _USCODE_25_450_TODO_TEXT,
            "__uscode_codification_fallback__",
            "uscode_transferred_heading_v1",
        ),
    ]

    for document_id, citation, text, cue, fallback_rule in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == cue
        assert fallback.metadata["fallback_rule"] == fallback_rule
        assert fallback.provenance.citation == citation


def test_spacy_compiler_replays_packet_todo_symbolic_validity_sample_for_25_5396() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    encoding = encoder.encode(
        _USCODE_25_5396_TODO_TEXT,
        document_id="us-code-25-5396-17291bf2fa3ae3f6",
        citation="25 U.S.C. 5396",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    assert modal_ir.formulas
    assert any(formula.operator.family == "deontic" for formula in modal_ir.formulas)
    assert all(
        formula.provenance.citation == "25 U.S.C. 5396"
        for formula in modal_ir.formulas
    )


def test_spacy_compiler_replays_packet_todo_samples_for_25_507_10_167_and_38_8112() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-25-507-e22029a3cea8b735",
            "25 U.S.C. 507",
            _USCODE_25_507_PACKET_519_TEXT,
            True,
        ),
        (
            "us-code-10-167-c04be565137bd57c",
            "10 U.S.C. 167",
            _USCODE_10_167_PACKET_519_TEXT,
            False,
        ),
        (
            "us-code-38-8112-c323ef8fcde15329",
            "38 U.S.C. 8112",
            _USCODE_38_8112_PACKET_519_TEXT,
            False,
        ),
    ]

    for document_id, citation, text, expects_codification_fallback in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.document_id == document_id
        assert modal_ir.formulas
        assert all(formula.provenance.citation == citation for formula in modal_ir.formulas)
        if expects_codification_fallback:
            fallback = modal_ir.formulas[-1]
            assert fallback.operator.family == "frame"
            assert fallback.metadata["cue"] == "__uscode_codification_fallback__"
            assert fallback.metadata["fallback_rule"] == "uscode_transferred_heading_v1"
        else:
            assert any(formula.operator.family == "deontic" for formula in modal_ir.formulas)


def test_spacy_compiler_replays_packet_todo_samples_for_36_170307_10_1095c_and_19_2113() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-36-170307-8767653c3220e539",
            "36 U.S.C. 170307",
            _USCODE_36_170307_TODO_TEXT,
            "notice",
        ),
        (
            "us-code-10-1095c-95cb9940fa4690f6",
            "10 U.S.C. 1095c",
            _USCODE_10_1095C_TODO_TEXT,
            "review",
        ),
        (
            "us-code-19-2113-bb39dec0898628d3",
            "19 U.S.C. 2113",
            _USCODE_19_2113_TODO_TEXT,
            "notice",
        ),
    ]

    for document_id, citation, text, procedural_keyword in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.document_id == document_id
        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_procedural_clause_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_procedural_clause_v1"
        assert fallback.metadata["procedural_keyword"] == procedural_keyword
        assert fallback.provenance.citation == citation


def test_spacy_compiler_adds_short_residual_heading_span_coverage_for_36_21110_todo_shape() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    encoding = encoder.encode(
        _USCODE_36_21110_TODO_TEXT,
        document_id="us-code-36-21110-e10464bdc5e2ba17",
        citation="36 U.S.C. 21110",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    assert modal_ir.document_id == "us-code-36-21110-e10464bdc5e2ba17"
    assert modal_ir.formulas
    fallback = modal_ir.formulas[-1]
    assert fallback.operator.family == "frame"
    assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
    assert fallback.metadata["fallback_rule"] == "uscode_section_heading_v1"
    residual_formulas = [
        formula
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    ]
    assert residual_formulas
    residual_text_spans = {
        modal_ir.normalized_text[
            int(formula.provenance.start_char) : int(formula.provenance.end_char)
        ].strip()
        for formula in residual_formulas
    }
    assert "Historical and Revision Notes." in residual_text_spans


def test_spacy_compiler_adds_short_residual_heading_span_coverage_for_42_18791_todo_shape() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    encoding = encoder.encode(
        _USCODE_42_18791_TODO_TEXT,
        document_id="us-code-42-18791.-fa3f6f298b46c6e4",
        citation="42 U.S.C. 18791.",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    assert modal_ir.document_id == "us-code-42-18791.-fa3f6f298b46c6e4"
    assert modal_ir.formulas
    fallback = modal_ir.formulas[-1]
    assert fallback.operator.family == "frame"
    assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
    assert fallback.metadata["fallback_rule"] == "uscode_section_heading_v1"
    residual_formulas = [
        formula
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    ]
    assert residual_formulas
    residual_text_spans = {
        modal_ir.normalized_text[
            int(formula.provenance.start_char) : int(formula.provenance.end_char)
        ].strip()
        for formula in residual_formulas
    }
    assert "Additional provisions." in residual_text_spans


def test_spacy_compiler_adds_residual_span_coverage_for_25_57_todo_shape() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    encoding = encoder.encode(
        _USCODE_25_57_RESIDUAL_SPAN_TODO_TEXT,
        document_id="us-code-25-57-884a228276a417f6",
        citation="25 U.S.C. 57",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    assert modal_ir.document_id == "us-code-25-57-884a228276a417f6"
    assert modal_ir.formulas
    residual_formulas = [
        formula
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    ]
    assert residual_formulas
    residual_text_spans = {
        modal_ir.normalized_text[
            int(formula.provenance.start_char) : int(formula.provenance.end_char)
        ].strip()
        for formula in residual_formulas
    }
    assert any(
        "U.S.C. Title 25 - INDIANS 25 U.S.C." in span for span in residual_text_spans
    )
    assert any("43 Stat." in span for span in residual_text_spans)


def test_spacy_compiler_adds_transfer_functions_residual_span_coverage_for_15_1212() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    encoding = encoder.encode(
        _USCODE_15_1212_TRANSFER_FUNCTIONS_TODO_TEXT,
        document_id="us-code-15-1212-80d23ee30f50aa42",
        citation="15 U.S.C. 1212",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    residual_text_spans = {
        modal_ir.normalized_text[
            int(formula.provenance.start_char) : int(formula.provenance.end_char)
        ].strip()
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    }

    assert any(
        "Transfer of Functions Functions of Secretary of Commerce" in span
        and "Consumer Product Safety Commission" in span
        for span in residual_text_spans
    )


def test_spacy_compiler_expands_split_omitted_codification_fallback_span() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    text = (
        "U.S.C. Title 25 - INDIANS 25 U.S.C. United States Code, 2024 Edition "
        "Title 25 - INDIANS CHAPTER 19 - INDIAN LAND CLAIMS SETTLEMENTS "
        "SUBCHAPTER XII - TORRES-MARTINEZ DESERT CAHUILLA INDIANS CLAIMS "
        "SETTLEMENT Sec. 1778b - Omitted From the U.S. Government Publishing "
        "Office, www.gpo.gov \u00a71778b. Omitted Editorial Notes Codification "
        "Section, Pub. L. 106-568, title VI, \u00a7604, Dec. 27, 2000, 114 Stat. "
        "2908, which ratified the Settlement Agreement, was omitted from the "
        "Code as being of special and not general application."
    )
    encoding = encoder.encode(
        text,
        document_id="us-code-25-1778b-dc9d5bd7a948724f",
        citation="25 U.S.C. 1778b",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    fallback = modal_ir.formulas[-1]
    fallback_span = modal_ir.normalized_text[
        int(fallback.provenance.start_char) : int(fallback.provenance.end_char)
    ]

    assert fallback.metadata["fallback_rule"] == "uscode_codification_transfer_heading_v1"
    assert fallback_span.startswith("Omitted Editorial Notes Codification Section")
    assert "was omitted from the Code as being of special and not general application" in fallback_span


def test_spacy_compiler_supports_usc_and_section_symbol_citation_variants_for_sec_headings() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-7-473a-02a85f2b18cfe8ee",
            "7 U.S.C. §473a",
            _USCODE_7_473A_SEC_HEADING_TEXT,
        ),
        (
            "us-code-7-473a-02a85f2b18cfe8ee",
            "7 USC 473a",
            _USCODE_7_473A_SEC_HEADING_TEXT,
        ),
        (
            "us-code-20-1067j-13aeda303003f5af",
            "20 U.S.C. §1067j",
            _USCODE_20_1067J_SEC_HEADING_TEXT,
        ),
        (
            "us-code-20-1067j-13aeda303003f5af",
            "20 USC 1067j",
            _USCODE_20_1067J_SEC_HEADING_TEXT,
        ),
        (
            "us-code-15-2501-eb4a7816e81bb710",
            "15 U.S.C. §2501",
            _USCODE_15_2501_SEC_HEADING_TEXT,
        ),
        (
            "us-code-15-2501-eb4a7816e81bb710",
            "15 USC 2501",
            _USCODE_15_2501_SEC_HEADING_TEXT,
        ),
    ]

    for index, (document_id, citation, text) in enumerate(cases, start=1):
        encoding = encoder.encode(
            text,
            document_id=f"{document_id}:citation-variant-{index}",
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_section_heading_v1"
        assert fallback.provenance.citation == citation


def test_spacy_compiler_replays_embedded_sec_heading_zero_formula_cases() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-10-2672-8dd80f359cdc8c51",
            "10 U.S.C. 2672",
            "Title 10 Armed Forces chapter heading Sec. 2672\u2014 Housing voucher benefits and utility allowances.",
        ),
        (
            "us-code-26-45N-50d302a360db7728",
            "26 U.S.C. 45N",
            "Title 26 Internal Revenue Code chapter heading Sec. 45N\u2014 Clean fuel production credit.",
        ),
        (
            "us-code-12-548-2c44bdc47b86c5f0",
            "12 U.S.C. 548",
            "Title 12 Banks and Banking chapter heading Sec. 548\u2014 State taxation of national banking associations.",
        ),
    ]

    for document_id, citation, text in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_section_heading_v1"
        assert fallback.provenance.citation == citation


def test_spacy_compiler_replays_symbolic_validity_todo_samples_with_coarse_section_heading_fallback() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-7-3125-7e90453fbb54b8b5",
            "7 U.S.C. 3125",
            "3125",
            "administrative notice hearing procedures",
        ),
        (
            "us-code-15-828-103d21b6b8cb41ed",
            "15 U.S.C. 828",
            "828",
            "administrative notice hearing records",
        ),
        (
            "us-code-22-2878-e0e935df7cbf1b94",
            "22 U.S.C. 2878",
            "2878",
            "administrative notice hearing review",
        ),
    ]

    for document_id, citation, section, heading in cases:
        encoding = encoder.encode(
            _coarse_uscode_heading_noise_text(section, heading),
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_section_heading_coarse_v1"
        assert fallback.provenance.citation == citation


def test_spacy_compiler_replays_symbolic_validity_todo_samples_for_2_5602_5_5348_and_42_15251() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-2-5602-ed23b79794b2e0a4",
            "2 U.S.C. 5602",
            _USCODE_2_5602_SYMBOLIC_VALIDITY_TODO_TEXT,
        ),
        (
            "us-code-5-5348-f0250f870668e53f",
            "5 U.S.C. 5348",
            _USCODE_5_5348_SYMBOLIC_VALIDITY_TODO_TEXT,
        ),
        (
            "us-code-42-15251.-c8bc40200627c975",
            "42 U.S.C. 15251.",
            _USCODE_42_15251_SYMBOLIC_VALIDITY_TODO_TEXT,
        ),
    ]

    for document_id, citation, text in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.document_id == document_id
        assert modal_ir.formulas
        assert all(formula.provenance.citation == citation for formula in modal_ir.formulas)
        if citation == "42 U.S.C. 15251.":
            fallback = modal_ir.formulas[-1]
            assert fallback.operator.family == "frame"
            assert fallback.metadata["cue"] == "__uscode_codification_fallback__"
            assert fallback.metadata["fallback_rule"] == "uscode_codification_transfer_heading_v1"


def test_spacy_compiler_replays_packet_todo_samples_for_2_88b_5_42_18431_and_42_12313() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-2-88b-5-94883a45ddc4a6db",
            "2 U.S.C. 88b-5",
            _USCODE_2_88B_5_TODO_TEXT,
        ),
        (
            "us-code-42-18431.-b72b735d11b81b90",
            "42 U.S.C. 18431.",
            _USCODE_42_18431_SYMBOLIC_VALIDITY_TODO_TEXT,
        ),
        (
            "us-code-42-12313.-c1053dbe1a049f60",
            "42 U.S.C. 12313.",
            _USCODE_42_12313_SYMBOLIC_VALIDITY_TODO_TEXT,
        ),
    ]

    for document_id, citation, text in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.document_id == document_id
        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_heading_without_section_reference_v1"
        assert fallback.provenance.citation == citation


def test_spacy_compiler_replays_packet_todo_long_heading_sample_for_43_2430() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    encoding = encoder.encode(
        _USCODE_43_2430_PACKET_143_TODO_TEXT,
        document_id="us-code-43-2430.-7bfbe56b01b9ee78",
        citation="43 U.S.C. 2430.",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    assert modal_ir.document_id == "us-code-43-2430.-7bfbe56b01b9ee78"
    assert modal_ir.formulas
    fallback = modal_ir.formulas[-1]
    assert fallback.operator.family == "frame"
    assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
    assert fallback.metadata["fallback_rule"] == "uscode_heading_without_section_reference_v1"
    assert fallback.provenance.citation == "43 U.S.C. 2430."


def test_spacy_compiler_replays_packet_todo_article_prefixed_heading_samples_for_2_453_9_6_and_43_1656() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-2-453-868ad5bf81742f35",
            "2 U.S.C. 453",
            _USCODE_2_453_PACKET_39_TEXT,
        ),
        (
            "us-code-9-6-725aa2302c64ab87",
            "9 U.S.C. 6",
            _USCODE_9_6_PACKET_39_TEXT,
        ),
        (
            "us-code-43-1656.-ee86a662b13291c8",
            "43 U.S.C. 1656.",
            _USCODE_43_1656_PACKET_39_TEXT,
        ),
    ]

    for document_id, citation, text in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.document_id == document_id
        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_heading_without_section_reference_v1"
        assert fallback.provenance.citation == citation


def test_spacy_compiler_replays_uscode_declarative_statement_zero_formula_cases() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-22-2688-83d45528085ab9e0",
            "22 U.S.C. 2688",
            (
                "U.S.C. Title 22 - FOREIGN RELATIONS AND INTERCOURSE 22 U.S.C. "
                "United States Code, 2024 Edition Title 22 - FOREIGN RELATIONS "
                "AND INTERCOURSE CHAPTER 38 - DEPARTMENT OF STATE Sec. 2688 - "
                "Ambassadors; criteria regarding selection and confirmation From the "
                "U.S. Government Publishing Office, www.gpo.gov \u00a72688. Ambassadors; "
                "criteria regarding selection and confirmation It is the sense of "
                "the Congress that the position of United States ambassador to a "
                "foreign country should be accorded to men and women possessing "
                "clearly demonstrated competence to perform ambassadorial duties. "
                "No individual should be accorded the position of United States "
                "ambassador to a foreign country primarily because of financial "
                "contributions to political campaigns. (Aug. 1, 1956, ch. 841, "
                "title I, \u00a718, as added Pub. L. 94\u2013141, title I, \u00a7104, Nov. 29, "
                "1975, 89 Stat. 757; renumbered title I, Pub. L. 97\u2013241, title II, "
                "\u00a7202(a), Aug. 24, 1982, 96 Stat. 282.)"
            ),
            "sense_of_congress",
        ),
        (
            "us-code-7-7311-017c4d8b52982ca1",
            "7 U.S.C. 7311",
            (
                "U.S.C. Title 7 - AGRICULTURE 7 U.S.C. United States Code, 2024 "
                "Edition Title 7 - AGRICULTURE CHAPTER 100 - AGRICULTURAL MARKET "
                "TRANSITION SUBCHAPTER VII - COMMISSION ON 21st CENTURY PRODUCTION "
                "AGRICULTURE Sec. 7311 - Establishment From the U.S. Government "
                "Publishing Office, www.gpo.gov \u00a77311. Establishment There is "
                "established a commission to be known as the \"Commission on 21st "
                "Century Production Agriculture\" (in this subchapter referred to as "
                "the \"Commission\"). (Pub. L. 104\u2013127, title I, \u00a7181, Apr. 4, "
                "1996, 110 Stat. 938.)"
            ),
            "establishment_clause",
        ),
        (
            "us-code-15-2402-7e27f5e59f9ba39e",
            "15 U.S.C. 2402",
            (
                "U.S.C. Title 15 - COMMERCE AND TRADE 15 U.S.C. United States "
                "Code, 2024 Edition Title 15 - COMMERCE AND TRADE CHAPTER 51 - "
                "NATIONAL PRODUCTIVITY AND QUALITY OF WORKING LIFE SUBCHAPTER I - "
                "FINDINGS, PURPOSE, AND POLICY; DEFINITIONS Sec. 2402 - "
                "Congressional statement of purpose From the U.S. Government "
                "Publishing Office, www.gpo.gov \u00a72402. Congressional statement of "
                "purpose It is the purpose of this chapter\u2014 (1) to establish a "
                "national policy which will encourage productivity growth "
                "consistent with needs of the economy, the natural environment, "
                "and the needs, rights, and best interests of management, the "
                "work force, and consumers; and (2) to establish as an independent "
                "establishment of the executive branch a National Center for "
                "Productivity and Quality of Working Life to focus, coordinate, "
                "and promote efforts to improve the rate of productivity growth. "
                "(Pub. L. 94\u2013136, title I, \u00a7102, Nov. 28, 1975, 89 Stat. 734.)"
            ),
            "purpose_clause",
        ),
    ]

    for document_id, citation, text, statement_hint in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_declarative_statement_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_declarative_statement_v1"
        assert fallback.metadata["statement_hint"] == statement_hint
        assert fallback.provenance.citation == citation


def test_spacy_compiler_replays_heading_only_zero_formula_cases_for_25_422_48_1572_and_42_6323() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-25-422-f3f166961e45b585",
            "25 U.S.C. 422",
            _USCODE_25_422_HEADING_ONLY_TEXT,
        ),
        (
            "us-code-48-1572.-8711c64e2d6b256c",
            "48 U.S.C. 1572.",
            _USCODE_48_1572_HEADING_ONLY_TEXT,
        ),
        (
            "us-code-42-6323.-1c7e7d2f53c36e15",
            "42 U.S.C. 6323.",
            _USCODE_42_6323_HEADING_ONLY_TEXT,
        ),
    ]

    for document_id, citation, text in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_heading_without_section_reference_v1"
        assert fallback.provenance.citation == citation


def test_spacy_compiler_adds_residual_heading_fallback_when_modal_cues_cover_other_segments() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    encoding = encoder.encode(
        (
            "Sec. 124 - Administrative notice and hearing procedures. "
            "The Secretary shall issue a decision within 30 days."
        ),
        document_id="us-code-25-124-d6ef602ae0d2e2b8",
        citation="25 U.S.C. 124",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    assert modal_ir.formulas
    assert any(formula.operator.family == "deontic" for formula in modal_ir.formulas)
    fallback = modal_ir.formulas[-1]
    assert fallback.operator.family == "frame"
    assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
    assert fallback.metadata["fallback_rule"] == "uscode_section_heading_v1"
    assert fallback.provenance.citation == "25 U.S.C. 124"


def test_spacy_compiler_adds_long_heading_residual_span_coverage_after_section_heading_fallback() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    encoding = encoder.encode(
        (
            "Sec. 124 - Administrative hearing notice and review procedures. "
            "Definitions and application requirements for appeals and petitions. "
            "The Secretary shall issue a decision within 30 days."
        ),
        document_id="us-code-25-124-long-heading-residual",
        citation="25 U.S.C. 124",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    residual_formulas = [
        formula
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    ]
    assert residual_formulas
    assert any(formula.operator.family == "deontic" for formula in modal_ir.formulas)
    fallback = modal_ir.formulas[-1]
    assert fallback.operator.family == "frame"
    assert fallback.metadata["fallback_rule"] == "uscode_section_heading_v1"


def test_spacy_compiler_adds_purpose_clause_residual_span_coverage_for_institute_sample() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    text = (
        "\u00a7285 l . Purpose of Institute The general purpose of the National "
        "Institute of Environmental Health Sciences (in this subpart referred "
        "to as the \"Institute\") is the conduct and support of research, "
        "training, health information dissemination, and other programs with "
        "respect to factors in the environment that affect human health."
    )

    encoding = encoder.encode(
        text,
        document_id="us-code-42-285-purpose-residual",
        citation="42 U.S.C. 285",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    assert not any(cue.cue.lower() == "with respect to" for cue in encoding.cues)
    residual_text_spans = {
        modal_ir.normalized_text[
            int(formula.provenance.start_char) : int(formula.provenance.end_char)
        ].strip()
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    }
    assert any(
        span.startswith("Purpose of Institute The general purpose")
        for span in residual_text_spans
    )


def test_spacy_compiler_adds_compact_frame_heading_residual_span_coverage_for_packet_000037_samples() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-42-4906.-49752be6630435d0",
            "42 U.S.C. 4906.",
            "Sec. 4906 - Availability of assistance. Environmental program benefits.",
            "Environmental program benefits.",
        ),
        (
            "us-code-26-676-062ec0a8a033a9fa",
            "26 U.S.C. 676",
            "Sec. 676 - Employee payments. Compensation and reimbursement expenses.",
            "Compensation and reimbursement expenses.",
        ),
        (
            "us-code-5-8173-653bf9ab88ca9151",
            "5 U.S.C. 8173",
            "Sec. 8173 - Administrative proceedings. Employee benefit determinations.",
            "Employee benefit determinations.",
        ),
        (
            "us-code-2-5103-2723bab002d6ffe8",
            "2 U.S.C. 5103",
            "Sec. 5103 - Program administration. Payment authorization.",
            "Payment authorization.",
        ),
        (
            "us-code-43-316b.-afdb72a9cdfde1d3",
            "43 U.S.C. 316b.",
            "Sec. 316b - Withdrawal and reservation of lands. Land settlement expenses.",
            "Land settlement expenses.",
        ),
    ]

    for document_id, citation, text, expected_span in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        residual_text_spans = {
            modal_ir.normalized_text[
                int(formula.provenance.start_char) : int(formula.provenance.end_char)
            ].strip()
            for formula in modal_ir.formulas
            if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
        }
        assert expected_span in residual_text_spans


def test_spacy_decompiler_preserves_uscode_source_surface_when_typed_slots_overlap() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-50-1231 to 1238.-54ddc50447da3288",
            "50 U.S.C. 1231 to 1238.",
            (
                "50 U.S.C. 1231 to 1238.: §§1231 to 1238. Repealed. "
                "Pub. L. 85-861, §36A, Sept. 2, 1958, 72 Stat. 1569 "
                "Section 1231, act Sept. 3, 1954, ch. 1257, title III, "
                "§308, 68 Stat. 1155, provided for promotion to first "
                "lieutenant. See section 14301 et seq. of Title 10, "
                "Armed Forces."
            ),
            "Repealed",
        ),
        (
            "us-code-54-102503.-8cd28d6d56630d35",
            "54 U.S.C. 102503.",
            (
                "54 U.S.C. 102503.: §102503. Authority of Secretary "
                "(a) In General .-Notwithstanding other provisions or "
                "limitations of law, the Secretary may perform the functions "
                "described in this section in the manner that the Secretary "
                "considers to be in the public interest."
            ),
            "Secretary may perform the functions",
        ),
    ]

    for document_id, citation, text, expected_fragment in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        decoded = decode_modal_ir_document(compiler.compile(encoding))

        assert decoded.reconstruction_similarity == 1.0
        assert decoded.text.startswith(citation)
        assert expected_fragment in decoded.text


def test_spacy_decompiler_exports_frame_residual_deontic_and_conditional_cues() -> None:
    text = (
        "30 U.S.C. 1512. Loan size limitation. The Secretary may make loans "
        "subject to amounts made available under this section."
    )
    span_start = text.index("The Secretary")
    modal_ir = ModalIRDocument(
        document_id="us-code-30-1512-frame-residual-cue-slots",
        source="us_code",
        normalized_text=text,
        formulas=[
            ModalIRFormula(
                formula_id="f1",
                operator=ModalIROperator(
                    family="frame",
                    system="FLogic",
                    symbol="Frame",
                    label="framed as",
                ),
                predicate=ModalIRPredicate(
                    name="loan_size_limitation",
                    arguments=["argument_subject:Secretary"],
                ),
                provenance=ModalIRProvenance(
                    source_id="us-code-30-1512-frame-residual-cue-slots",
                    start_char=span_start,
                    end_char=len(text),
                    citation="30 U.S.C. 1512",
                ),
                metadata={
                    "cue": "__uscode_residual_span_fallback__",
                    "fallback_rule": "uscode_residual_span_coverage_v1",
                },
            )
        ],
        metadata={"citation": "30 U.S.C. 1512"},
    )

    decoded = decode_modal_ir_document(modal_ir)
    slot_map = decoded_modal_phrase_slot_text_map(
        decoded,
        include_fixed=False,
        include_provenance_only=True,
    )

    assert "frame->deontic:may" in slot_map["typed_decompiler_family_pair_cue"]
    assert (
        "frame->conditional_normative:subject_to"
        in slot_map["typed_decompiler_family_pair_cue"]
    )
    assert (
        "frame->deontic:may"
        in slot_map["typed-decompiler-target-reconstruction-cue"]
    )


def test_spacy_decoder_vector_and_family_logits_are_deterministic() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must make records promptly available.",
    )

    first = codec.decode_sample_embedding(sample, dimensions=6)
    second = codec.decode_sample_embedding(sample, dimensions=6)
    logits = codec.family_logits_for_sample(sample, modal_families=("deontic", "temporal", "hybrid"))

    assert first == second
    assert len(first) == 6
    assert any(value != 0.0 for value in first)
    assert logits["deontic"] > logits["temporal"]


def test_spacy_codec_exposes_text_features_without_sample_ids() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must make records promptly available.",
    )

    features = codec.feature_keys_for_sample(sample)

    assert features
    assert any(feature.startswith("cue:deontic") for feature in features)
    assert all(sample.sample_id not in feature for feature in features)


def test_spacy_codec_ranks_modal_families_from_cues() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall provide notice within 30 days.",
    )

    ranking = ranked_modal_families(codec.encode_sample(sample))

    assert ranking
    assert ranking[0]["family"] in {"deontic", "temporal"}
    assert ranking[0]["count"] >= 1
    assert abs(sum(item["share"] for item in ranking) - 1.0) <= 1e-6


def test_spacy_codec_lowers_initial_family_cross_entropy() -> None:
    sample = build_us_code_sample(
        title="42",
        section="1983",
        text="A person may bring an action when rights are deprived under color of law.",
    )
    plain = AdaptiveModalAutoencoder()
    spacy = AdaptiveModalAutoencoder(
        feature_codec=SpaCyModalCodec(
            encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
        )
    )

    plain_eval = plain.evaluate([sample])
    spacy_eval = spacy.evaluate([sample])

    assert spacy_eval.cross_entropy_loss < plain_eval.cross_entropy_loss


def test_spacy_codec_strengthens_deontic_share_for_statutory_generic_frame_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="42",
        section="1396u",
        text=(
            "Authority and jurisdiction and authority and jurisdiction under this section "
            "impose liability for violations."
        ),
    )
    encoding = codec.encode_sample(sample)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "deontic" for cue in encoding.cues)
    deontic_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "deontic"
    )
    frame_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "frame"
    )
    assert deontic_share > 0.3
    assert frame_share > deontic_share


def test_spacy_codec_strengthens_temporal_share_for_statutory_generic_frame_competition() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="50",
        section="3305",
        text=(
            "Authority and jurisdiction and authority and jurisdiction under this section "
            "apply before each annual review deadline."
        ),
    )
    encoding = codec.encode_sample(sample)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "temporal" for cue in encoding.cues)
    temporal_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "temporal"
    )
    frame_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "frame"
    )
    assert temporal_share > 0.3
    assert frame_share > temporal_share


def test_spacy_codec_marks_us_code_enforcement_and_duration_cues() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "Sec. 5009 - Unlawful activities. It is unlawful for any person "
            "to transport the resource, and the Secretary may discontinue a "
            "lease for a period of not less than ten years."
        ),
        document_id="packet-005384-enforcement-duration-cues",
    )
    cues = {(cue.family, cue.cue.lower()) for cue in encoding.cues}
    ranking = ranked_modal_families(encoding)
    shares = {str(item["family"]): float(item["share_raw"]) for item in ranking}

    assert ("deontic", "it is unlawful") in cues
    assert ("deontic", "may discontinue") in cues
    assert ("temporal", "period of not less than") in cues
    assert shares["deontic"] > shares["frame"]
    assert shares["temporal"] > 0.2


def test_spacy_codec_strengthens_conditional_share_for_dense_temporal_scope_statutory_conflict() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="43",
        section="326",
        text=(
            "Within 30 days and by January 1, 2030 and no later than the fiscal year "
            "deadline, as provided in subsection (b), the agency publishes the report."
        ),
    )
    encoding = codec.encode_sample(sample)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "conditional_normative" for cue in encoding.cues)
    conditional_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "conditional_normative"
    )
    assert conditional_share > 0.12


def test_spacy_codec_strengthens_temporal_share_for_dense_deontic_scope_statutory_conflict() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="2",
        section="5303",
        text=(
            "The agency shall and must and shall and must provide notice before each "
            "annual review deadline under this section."
        ),
    )
    encoding = codec.encode_sample(sample)
    ranking = ranked_modal_families(encoding)

    assert not any(cue.family == "temporal" for cue in encoding.cues)
    temporal_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "temporal"
    )
    assert temporal_share > 0.12


def test_spacy_signals_mark_authorized_appropriation_fiscal_scope() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "There is authorized to be appropriated $25,000,000 for each of the fiscal "
            "years 1978 and 1979, and $20,000,000 for fiscal year 1980."
        ),
        document_id="authorized-appropriation-fiscal-scope-signals",
    )

    signals = modal_ambiguity_signals(encoding)

    assert signals["has_deontic_authorization_scope_phrase"] is True
    assert signals["has_temporal_fiscal_scope_phrase"] is True
    assert signals["has_temporal_deadline_cue"] is False


def test_spacy_codec_boosts_deontic_share_for_authorized_appropriation_fiscal_scope() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    with_phrase = build_us_code_sample(
        title="42",
        section="6931",
        text=(
            "There is authorized to be appropriated $25,000,000 for each of the fiscal "
            "years 1978 and 1979, and $20,000,000 for fiscal year 1980."
        ),
    )
    without_phrase = build_us_code_sample(
        title="42",
        section="6931",
        text=(
            "The program is authorized for each of the fiscal years 1978 and 1979, and "
            "for fiscal year 1980."
        ),
    )

    with_phrase_ranking = ranked_modal_families(codec.encode_sample(with_phrase))
    without_phrase_ranking = ranked_modal_families(codec.encode_sample(without_phrase))

    with_phrase_deontic_share = next(
        float(item["share"])
        for item in with_phrase_ranking
        if item["family"] == "deontic"
    )
    without_phrase_deontic_share = next(
        float(item["share"])
        for item in without_phrase_ranking
        if item["family"] == "deontic"
    )
    with_phrase_temporal_share = next(
        float(item["share"])
        for item in with_phrase_ranking
        if item["family"] == "temporal"
    )
    without_phrase_temporal_share = next(
        float(item["share"])
        for item in without_phrase_ranking
        if item["family"] == "temporal"
    )

    assert with_phrase_deontic_share > without_phrase_deontic_share
    assert with_phrase_temporal_share < without_phrase_temporal_share


def test_spacy_codec_refines_packet_000709_notification_deadline_family_evidence() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "Notification of an active measures campaign. The Director shall notify "
            "the appropriate congressional committees not later than 48 hours after "
            "determining that there is credible information of an active measures campaign."
        ),
        document_id="packet-000709-notification-deadline",
    )

    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)
    shares = {str(item["family"]): float(item["share_raw"]) for item in ranking}

    assert signals["has_temporal_notification_deadline_scope_phrase"] is True
    assert signals["has_temporal_deadline_cue"] is True
    assert shares["temporal"] > shares["deontic"]


def test_spacy_codec_refines_packet_002839_frame_temporal_deadline_evidence() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="42",
        section="242v",
        text=(
            "Authority and jurisdiction under this section. The Secretary shall "
            "review each foreign talent recruitment program and issue guidance "
            "not later than 60 days after December 29, 2022, under this section."
        ),
    )
    encoding = codec.encode_sample(sample)

    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)
    shares = {str(item["family"]): float(item["share_raw"]) for item in ranking}

    assert signals["has_statutory_scope_reference"] is True
    assert signals["has_temporal_deadline_cue"] is True
    assert signals["has_calendar_date_scope"] is True
    assert shares["temporal"] > shares["frame"]


def test_spacy_codec_refines_active_measures_after_notification_timing() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "The congressional committees shall receive notification of an "
            "active measures campaign after the Director determines that such "
            "campaign is occurring."
        ),
        document_id="packet-000603-active-measures-after-notification",
    )

    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)
    shares = {str(item["family"]): float(item["share_raw"]) for item in ranking}

    assert signals["has_temporal_notification_deadline_scope_phrase"] is True
    assert shares["temporal"] > shares["deontic"]
    assert ranking[0]["family"] == "temporal"


def test_spacy_codec_refines_packet_000709_exempt_operations_remain_deontic() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "Exempt operations. Test platforms. The provisions of this subchapter "
            "shall not apply to any test platform which will not operate as an ocean "
            "thermal energy conversion facility or plantship after conclusion of the "
            "testing period."
        ),
        document_id="packet-000709-exempt-operations",
    )

    ranking = ranked_modal_families(encoding)
    shares = {str(item["family"]): float(item["share_raw"]) for item in ranking}

    assert shares["deontic"] > shares["temporal"]


def test_spacy_codec_refines_packet_001882_authorized_appropriation_conditional_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "For the purposes of this part, there is authorized to be appropriated "
            "to the Secretary not to exceed $98,000,000 for the period beginning "
            "October 1, 1978, and ending September 30, 1981."
        ),
        document_id="packet-001882-authorized-appropriation-conditional",
    )
    ranking = ranked_modal_families(encoding)
    shares = {str(item["family"]): float(item["share_raw"]) for item in ranking}

    assert any(
        cue.family == "conditional_normative"
        and cue.cue.lower() == "there is authorized to be appropriated"
        for cue in encoding.cues
    )
    assert shares["conditional_normative"] > shares["temporal"]
    assert shares["conditional_normative"] > 0.34


def test_spacy_codec_refines_packet_002939_mixed_scope_family_evidence() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    samples = {
        "removal_frame": (
            "Sec. 1450 - Attachment or sequestration; securities. Whenever any "
            "action is removed from a State court to a district court of the "
            "United States, any attachment or sequestration shall remain valid "
            "until dissolved or modified by the district court. Historical and "
            "Revision Notes changes were made in phraseology."
        ),
        "approval_deontic": (
            "Sec. 6395 - Secretarial approval; peer review. The Secretary shall "
            "approve each State application that meets the requirements of this "
            "part and may review such application. Editorial Notes Effective "
            "Date of 2015 Amendment effective Dec. 10, 2015, see section 6301 "
            "of this title."
        ),
        "repeal_deontic": (
            "Sec. 3342 - Repealed. Section related to Federal participants and "
            "prohibited details of employees except for temporary duty provided "
            "for by law. Effective Date of Repeal effective Oct. 1, 1991, see "
            "section 6303 of this title."
        ),
        "membership_conditional": (
            "Sec. 286w - Denial of membership or other status. It is the policy "
            "that the organization should not be given membership or observer "
            "status. In the event that the Fund provides membership, such action "
            "would result in a serious diminution of support. Upon review, the "
            "President would be required to report recommendations to Congress."
        ),
    }

    shares_by_sample = {}
    for sample_id, text in samples.items():
        ranking = ranked_modal_families(encoder.encode(text, document_id=sample_id))
        shares_by_sample[sample_id] = {
            str(item["family"]): float(item["share_raw"])
            for item in ranking
        }

    assert shares_by_sample["removal_frame"]["frame"] > 0.14
    assert shares_by_sample["approval_deontic"]["deontic"] > 0.34
    assert shares_by_sample["repeal_deontic"]["deontic"] > 0.28
    assert shares_by_sample["membership_conditional"]["conditional_normative"] > 0.4


def test_supervisor_with_spacy_codec_improves_loss_and_cosine() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must make records promptly available to any person.",
        embedding_vector=[0.1, 0.2, 0.3, 0.4],
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_codec=SpaCyModalCodec(
            encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
        )
    )
    supervisor = ModalTodoSupervisor()
    before = autoencoder.evaluate([sample])

    run = supervisor.optimize(
        [sample],
        autoencoder=autoencoder,
        max_iterations=2,
        max_items=4,
        learning_rate=0.5,
    )

    assert run.final_evaluation.cross_entropy_loss < before.cross_entropy_loss
    assert run.final_evaluation.reconstruction_loss < before.reconstruction_loss
    assert run.final_evaluation.embedding_cosine_similarity > before.embedding_cosine_similarity
    assert supervisor.queue.status_counts()["completed"] >= 2


def test_packet_002219_dense_frame_headings_do_not_outvote_explicit_deontic_cues() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    text = (
        "33 U.S.C. Title 33 - NAVIGATION AND NAVIGABLE WATERS CHAPTER 12 - "
        "RIVER AND HARBOR IMPROVEMENTS GENERALLY SUBCHAPTER I - GENERAL "
        "PROVISIONS Sec. 558b-1 - Canals and appurtenant structures; "
        "transfer of title; power development. The Secretary shall establish "
        "authority under this section and may transfer title in accordance "
        "with this chapter."
    )
    encoding = encoder.encode(
        text,
        document_id="packet-002219-frame-deontic-cue-balance",
        citation="33 U.S.C. 558b-1",
        source="us_code",
    )
    ranking = ranked_modal_families(encoding)
    shares = {str(item["family"]): float(item["share_raw"]) for item in ranking}

    assert ranking[0]["family"] == "deontic"
    assert shares["deontic"] > shares["frame"]
    assert shares["frame"] > 0.0
    assert shares["conditional_normative"] > 0.0


def test_packet_003559_frame_policy_exposes_explicit_adaptive_ambiguity() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    scenarios = (
        ("us-code-6-1402-e4f4e4514225aa0f", "epistemic", -0.532464262103),
        ("us-code-16-482n-1-d224d4c3b20604b2", "temporal", -0.956936053292),
    )

    assert COMPILER_AMBIGUITY_PACKET_003559_FAMILY_PAIRS == (
        ("frame", "epistemic"),
        ("frame", "temporal"),
    )
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_003559_FAMILY_PAIRS:
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in priority_signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )

    for sample_id, target_family, family_margin in scenarios:
        predicted_family = "frame"
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
            predicted_family_source=f"packet_003559:{sample_id}",
        )
        explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        policy_pair = f"{predicted_family}->{target_family}"
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        )

        assert base_ambiguity.candidate_ids == [predicted_family, target_family]
        assert base_ambiguity.severity == "requires_rule"
        assert base_ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["is_compiler_required_policy_pair"] is True
        assert base_ambiguity.metadata["is_priority_policy_pair"] is True
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
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            for ambiguity in ambiguities
        )


def test_packet_003976_registry_refines_weak_frame_family_cues() -> None:
    expected_pairs = (
        ("frame", "deontic"),
        ("frame", "temporal"),
    )

    assert COMPILER_REFINED_PACKET_003976_FAMILY_PAIRS == expected_pairs
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

    assert compiler_refined_modal_family_cue_margin_buffer("frame", "deontic") >= 0.94
    assert compiler_refined_modal_family_cue_margin_buffer("frame", "temporal") >= 0.76


def test_packet_003166_compiler_policy_exposes_explicit_adaptive_ambiguity() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    scenarios = (
        ("us-code-43-364f.-f76294ee50dd54b8", "deontic", "deontic", 0.027210909929),
        ("us-code-22-8808-387e8cde9e6ad300", "deontic", "temporal", -0.305611079378),
        (
            "us-code-10-931a-f50abc457484ada6",
            "frame",
            "conditional_normative",
            -0.675306020683,
        ),
    )

    assert COMPILER_AMBIGUITY_PACKET_003166_FAMILY_PAIRS == (
        ("deontic", "deontic"),
        ("deontic", "temporal"),
        ("frame", "conditional_normative"),
    )
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_003166_FAMILY_PAIRS:
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

    for sample_id, predicted_family, target_family, family_margin in scenarios:
        is_self_pair = predicted_family == target_family
        predicted_share = 0.3 if is_self_pair else 0.1
        competing_share = predicted_share - family_margin
        runner_up_family = (
            "temporal"
            if is_self_pair and predicted_family == "deontic"
            else target_family
        )
        ranking = [
            {
                "family": predicted_family,
                "count": 0,
                "share_raw": predicted_share,
                "share": predicted_share,
            },
            {
                "family": runner_up_family,
                "count": 0,
                "share_raw": competing_share,
                "share": competing_share,
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
            predicted_family_source=f"packet_003166:{sample_id}",
        )
        expected_direction = "outvoted" if family_margin <= 0.0 else "contested"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_"
            f"{expected_direction}_margin_low"
        )
        policy_pair = f"{predicted_family}->{target_family}"
        expected_candidate_ids = (
            [predicted_family]
            if is_self_pair
            else [predicted_family, target_family]
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        )

        assert base_ambiguity.candidate_ids == expected_candidate_ids
        assert base_ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["is_compiler_required_policy_pair"] is True
        assert base_ambiguity.metadata["is_priority_policy_pair"] is True
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert base_ambiguity.metadata["adaptive_margin_direction"] == expected_direction
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["is_explicit_adaptive_ambiguity"] is True
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            for ambiguity in ambiguities
        )


def test_packet_004558_exchange_classification_rule_prefers_conditional_family() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "26 U.S.C. 1241. Cancellation of lease or distributor agreements. "
            "Amounts received by a lessee for cancellation of a lease or by a "
            "distributor of goods for the cancellation of a distributor agreement "
            "shall be considered as amounts received in exchange for such lease "
            "or agreement."
        ),
        document_id="packet-004558-us-code-26-1241",
    )
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)
    shares = {str(item["family"]): float(item["share_raw"]) for item in ranking}

    assert (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ) in COMPILER_REFINED_PACKET_004558_FAMILY_PAIRS
    assert signals["has_conditional_exchange_classification_scope_phrase"] is True
    assert any(
        cue.family == "conditional_normative"
        and cue.cue.lower() == "shall be considered as amounts received in exchange"
        for cue in encoding.cues
    )
    assert ranking[0]["family"] == "conditional_normative"
    assert shares["conditional_normative"] > shares["deontic"]


def test_packet_004558_personnel_action_rule_remains_deontic() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "5 U.S.C. 7513. An agency may take an action under this section "
            "only for such cause as will promote the efficiency of the service. "
            "The employee is entitled to written notice and may appeal."
        ),
        document_id="packet-004558-us-code-5-7513",
    )
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)
    shares = {str(item["family"]): float(item["share_raw"]) for item in ranking}

    assert (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ) in COMPILER_REFINED_PACKET_004558_FAMILY_PAIRS
    assert signals["has_conditional_exchange_classification_scope_phrase"] is False
    assert ranking[0]["family"] == "deontic"
    assert shares["deontic"] > shares["conditional_normative"]


def test_spacy_compiler_covers_uscode_effect_of_act_catchline_for_701e() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    text = (
        "33 U.S.C. 701e. Effect of act June 22, 1936, on provisions for "
        "Mississippi River and other projects. Nothing in this Act shall be "
        "construed as repealing or amending any provision of sections 702a "
        "through 704 of this title."
    )
    encoding = encoder.encode(
        text,
        document_id="us-code-33-701e-19ea9c3021f51521",
        citation="33 U.S.C. 701e",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    residual_spans = {
        modal_ir.normalized_text[
            formula.provenance.start_char : formula.provenance.end_char
        ].strip()
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    }

    assert (
        "Effect of act June 22, 1936, on provisions for Mississippi River "
        "and other projects."
    ) in residual_spans


def test_spacy_compiler_bounds_packet_catchlines_before_body_starters() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-16-666e-packet-catchline",
            "16 U.S.C. 666e",
            "U.S.C. Title 16 - CONSERVATION 16 U.S.C. United States Code, "
            "2024 Edition Title 16 - CONSERVATION Sec. 666e - "
            "Administration of acquired lands From the U.S. Government "
            "Publishing Office, www.gpo.gov §666e. Administration of "
            "acquired lands Any lands acquired by the Secretary shall become "
            "a part of such refuge.",
            "Administration of acquired lands",
        ),
        (
            "us-code-10-7592-packet-catchline",
            "10 U.S.C. 7592",
            "U.S.C. Title 10 - ARMED FORCES 10 U.S.C. United States Code, "
            "2024 Edition Title 10 - ARMED FORCES Sec. 7592 - Radiograms "
            "and telegrams: forwarding charges due connecting commercial "
            "facilities From the U.S. Government Publishing Office, "
            "www.gpo.gov §7592. Radiograms and telegrams: forwarding "
            "charges due connecting commercial facilities In the operation "
            "of telegraph lines, members of the Signal Corps may collect "
            "forwarding charges.",
            "Radiograms and telegrams: forwarding charges due connecting "
            "commercial facilities",
        ),
    ]

    for document_id, citation, text, expected_catchline in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)
        catchline_spans = {
            modal_ir.normalized_text[
                int(formula.provenance.start_char) : int(formula.provenance.end_char)
            ].strip()
            for formula in modal_ir.formulas
            if formula.metadata.get("fallback_rule")
            == "uscode_section_catchline_coverage_v1"
        }

        assert expected_catchline in catchline_spans
