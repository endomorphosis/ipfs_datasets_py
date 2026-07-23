"""Regression coverage for packet-000662 compiler ambiguity policy."""

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
    COMPILER_AMBIGUITY_PACKET_000662_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    compiler_required_adaptive_ambiguity_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (
    SpaCyLegalEncoding,
    SpaCyModalCueFeature,
)


_PACKET_000662_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.DEONTIC.value),
    (ModalLogicFamily.FRAME.value, ModalLogicFamily.DEONTIC.value),
)


def _mock_ranking(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> List[Dict[str, Any]]:
    predicted_share = 0.5
    if predicted_family == target_family:
        competing_family = ModalLogicFamily.FRAME.value
        competing_share = predicted_share - family_margin
    else:
        competing_family = target_family
        competing_share = predicted_share + family_margin
    return [
        {
            "family": predicted_family,
            "count": 1,
            "share_raw": predicted_share,
            "share": predicted_share,
        },
        {
            "family": competing_family,
            "count": 1,
            "share_raw": competing_share,
            "share": competing_share,
        },
    ]


def _encoding_for_family(*, predicted_family: str, document_id: str) -> SpaCyLegalEncoding:
    system, symbol, label = (
        ("FRAME_BM25", "Frame", "frame")
        if predicted_family == ModalLogicFamily.FRAME.value
        else ("D", "O", "obligation")
    )
    text = f"Synthetic packet 000662 {predicted_family} ambiguity evidence."
    return SpaCyLegalEncoding(
        document_id=document_id,
        text=text,
        normalized_text=text,
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family=predicted_family,
                system=system,
                symbol=symbol,
                label=label,
                cue=predicted_family,
                start_char=0,
                end_char=len(predicted_family),
                token_indices=[],
            ),
        ],
    )


def _modal_ir_for_encoding(
    *,
    encoding: SpaCyLegalEncoding,
    predicted_family: str,
    sample_id: str,
) -> ModalIRDocument:
    system, symbol, label = (
        ("FRAME_BM25", "Frame", "frame")
        if predicted_family == ModalLogicFamily.FRAME.value
        else ("D", "O", "obligation")
    )
    return ModalIRDocument(
        document_id=encoding.document_id,
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id=f"f-packet-000662-{predicted_family}",
                operator=ModalIROperator(
                    family=predicted_family,
                    system=system,
                    symbol=symbol,
                    label=label,
                ),
                predicate=ModalIRPredicate(
                    name=f"{predicted_family}_predicate",
                    arguments=["actor:agency"],
                    role=label,
                ),
                provenance=ModalIRProvenance(
                    source_id=sample_id,
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="packet-000662",
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
    expected_type = (
        f"adaptive_{predicted_family}_{target_family}_"
        f"{'outvoted' if family_margin < 0.0 else 'contested'}_margin_low"
    )
    for ambiguity in ambiguities:
        if ambiguity.ambiguity_type != expected_type:
            continue
        metadata: Mapping[str, Any] = ambiguity.metadata
        if metadata.get("adaptive_policy_pair") != f"{predicted_family}->{target_family}":
            continue
        if abs(float(metadata.get("family_margin_raw", 0.0)) - family_margin) > 1e-12:
            continue
        return ambiguity
    return None


def test_packet_000662_pairs_are_registered_across_ambiguity_policies() -> None:
    assert COMPILER_AMBIGUITY_PACKET_000662_FAMILY_PAIRS == _PACKET_000662_FAMILY_PAIRS
    for predicted_family, target_family in _PACKET_000662_FAMILY_PAIRS:
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
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


def test_compiler_exposes_packet_000662_explicit_adaptive_ambiguities() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    scenarios = (
        (
            "us-code-42-300bb-025873c840b5036f",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
            0.112472615285,
            "review",
        ),
        (
            "us-code-42-12203.-ce045304b5a196f5",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
            -0.653934328509,
            "requires_rule",
        ),
    )
    for sample_id, predicted_family, target_family, family_margin, severity in scenarios:
        ranking = _mock_ranking(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
        )
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        encoding = _encoding_for_family(
            predicted_family=predicted_family,
            document_id=f"packet-000662-{predicted_family}-{target_family}",
        )
        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=_modal_ir_for_encoding(
                encoding=encoding,
                predicted_family=predicted_family,
                sample_id=sample_id,
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

        assert ambiguity is not None, [item.to_dict() for item in ambiguities]
        assert ambiguity.severity == severity
        assert ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert ambiguity.metadata["is_compiler_required_policy_pair"] is True
        assert ambiguity.metadata["is_priority_policy_pair"] is True
        assert ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert ambiguity.metadata["is_explicit_adaptive_ambiguity"] is True
