"""Regression coverage for packet-003357 refined modal family cue policy."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple

from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
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
    COMPILER_REFINED_PACKET_003357_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    compiler_refined_modal_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (
    SpaCyLegalEncoding,
    SpaCyModalCueFeature,
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
            "source": "packet_003357_fixture",
        },
        {
            "family": target_family,
            "count": 0,
            "logit": 1.2,
            "share_raw": target_share,
            "share": target_share,
            "source": "packet_003357_fixture",
        },
    ]


def _modal_ir_for_family(
    *,
    document_id: str,
    predicted_family: str,
) -> ModalIRDocument:
    predicted_system = "FRAME_BM25" if predicted_family == "frame" else "D"
    predicted_symbol = "Frame" if predicted_family == "frame" else "O"
    predicted_label = "frame" if predicted_family == "frame" else "obligation"
    return ModalIRDocument(
        document_id=document_id,
        source="us_code",
        normalized_text=f"Synthetic packet 003357 {predicted_family} evidence.",
        formulas=[
            ModalIRFormula(
                formula_id=f"f-{document_id}",
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
                    source_id=document_id,
                    start_char=0,
                    end_char=len(document_id),
                    citation="packet-003357",
                ),
            ),
        ],
    )


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
        if metadata.get("predicted_family") != predicted_family:
            continue
        if metadata.get("target_family") != target_family:
            continue
        if abs(float(metadata.get("family_margin_raw", 0.0)) - family_margin) > 1e-12:
            continue
        return ambiguity
    return None


def test_packet_003357_family_cue_pairs_are_registered() -> None:
    expected_pairs = (
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ),
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.TEMPORAL.value,
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
        ),
    )

    assert COMPILER_REFINED_PACKET_003357_FAMILY_PAIRS == expected_pairs
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
            >= 0.0015
        )


def test_compiler_exposes_packet_003357_explicit_adaptive_ambiguities() -> None:
    evidence_cases: Tuple[Tuple[str, str, str, float], ...] = (
        (
            "us-code-40-605-2530cb7b5d81da59",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
            -0.869755874639,
        ),
        (
            "us-code-42-4155.-2d59f04d0d395c60",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.313893999892,
        ),
        (
            "us-code-2-1438-117bb6da4d01e8c1",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.142010098179,
        ),
    )

    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            modal_adaptive_family_margin=0.15,
        )
    )
    threshold = 0.15
    for sample_id, predicted_family, target_family, family_margin in evidence_cases:
        document_id = f"compiler-ambiguity-packet-003357-{sample_id}"
        text = f"Synthetic packet 003357 {predicted_family} ambiguity evidence."
        encoding = SpaCyLegalEncoding(
            document_id=document_id,
            text=text,
            normalized_text=text,
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system="FRAME_BM25" if predicted_family == "frame" else "D",
                    symbol="Frame" if predicted_family == "frame" else "O",
                    label="frame" if predicted_family == "frame" else "obligation",
                    cue=predicted_family,
                    start_char=0,
                    end_char=len(predicted_family),
                    token_indices=[],
                ),
            ],
        )
        ranking = _mock_adaptive_ranking(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
        )
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=_modal_ir_for_family(
                document_id=document_id,
                predicted_family=predicted_family,
            ),
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        ambiguity = _matching_explicit_ambiguity(
            ambiguities=ambiguities,
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
        )

        assert ambiguity is not None, (
            sample_id,
            [item.to_dict() for item in ambiguities],
        )
        assert ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert ambiguity.metadata["is_compiler_required_policy_pair"] is True
        assert ambiguity.metadata["is_priority_policy_pair"] is True
        assert ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert ambiguity.metadata["adaptive_margin_direction"] == "outvoted"
        assert ambiguity.metadata["is_explicit_adaptive_ambiguity"] is True
        assert (
            abs(float(ambiguity.metadata["priority"]) - (abs(family_margin) + threshold))
            <= 1e-12
        )
