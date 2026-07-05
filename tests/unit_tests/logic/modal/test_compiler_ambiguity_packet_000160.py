"""Regression coverage for packet-000160 compiler ambiguity policy."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

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
    ModalLogicFamily,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (
    SpaCyLegalEncoding,
    SpaCyModalCueFeature,
)


def _ranking_for_margin(
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


@pytest.mark.parametrize(
    ("sample_id", "predicted_family", "target_family", "family_margin"),
    (
        (
            "us-code-22-290k-5-2914184e2690e597",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
            -0.517628420281,
        ),
        (
            "us-code-10-2515-cb1304b3980adf2a",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.56870308291,
        ),
        (
            "us-code-10-233a-8bed7fafbdc4039d",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.236742208251,
        ),
    ),
)
def test_compiler_surfaces_packet_000160_explicit_adaptive_ambiguity(
    monkeypatch,
    sample_id: str,
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(parser_backend="regex", modal_adaptive_family_margin=0.15)
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    ranking = _ranking_for_margin(
        predicted_family=predicted_family,
        target_family=target_family,
        family_margin=family_margin,
    )
    family_shares = {
        str(candidate["family"]): float(candidate["share_raw"])
        for candidate in ranking
    }
    text = f"Synthetic packet 000160 {predicted_family} ambiguity evidence."
    encoding = SpaCyLegalEncoding(
        document_id=f"packet-000160-{sample_id}",
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
    modal_ir = ModalIRDocument(
        document_id=encoding.document_id,
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id=f"f-packet-000160-{sample_id}",
                operator=ModalIROperator(
                    family=predicted_family,
                    system="FRAME_BM25" if predicted_family == "frame" else "D",
                    symbol="Frame" if predicted_family == "frame" else "O",
                    label="frame" if predicted_family == "frame" else "obligation",
                ),
                predicate=ModalIRPredicate(
                    name=f"{predicted_family}_predicate",
                    arguments=["actor:agency"],
                    role="frame" if predicted_family == "frame" else "obligation",
                ),
                provenance=ModalIRProvenance(
                    source_id=sample_id,
                    start_char=0,
                    end_char=len(text),
                    citation="packet-000160",
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
    expected_type = (
        f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
    )
    explicit_ambiguity = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == expected_type
        and ambiguity.candidate_ids == [predicted_family, target_family]
    )

    assert explicit_ambiguity.metadata["adaptive_policy_pair"] == policy_pair
    assert explicit_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert explicit_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert explicit_ambiguity.metadata["is_compiler_required_policy_pair"] is True
    assert explicit_ambiguity.metadata["is_priority_policy_pair"] is True
    assert explicit_ambiguity.metadata["has_target_signal_evidence"] is True
    assert explicit_ambiguity.metadata["signal_free_pair_policy_applied"] is False
    assert explicit_ambiguity.metadata["is_explicit_adaptive_ambiguity"] is True
    assert (
        abs(float(explicit_ambiguity.metadata["family_margin_raw"]) - family_margin)
        < 1e-12
    )
