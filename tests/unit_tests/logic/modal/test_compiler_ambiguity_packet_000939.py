"""Regression coverage for packet-000939 refined modal family cue policy."""

from __future__ import annotations

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
    COMPILER_REFINED_PACKET_000939_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    compiler_refined_modal_family_cue_margin_buffer,
    compiler_required_adaptive_ambiguity_targets,
    compiler_weak_typed_self_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_signal_free_adaptive_ambiguity_pair,
    priority_signal_free_adaptive_ambiguity_targets,
    supports_signal_free_adaptive_ambiguity_pair,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (
    SpaCyLegalEncoding,
    SpaCyModalCueFeature,
)


def test_packet_000939_family_cue_pairs_are_registered() -> None:
    expected_pairs = (
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
        ),
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.EPISTEMIC.value,
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
        ),
    )

    assert COMPILER_REFINED_PACKET_000939_FAMILY_PAIRS == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert target_family in compiler_required_adaptive_ambiguity_targets(
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
            >= 0.0015
        )

    assert (
        compiler_weak_typed_self_family_cue_margin_buffer(
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
        )
        >= 0.135
    )


@pytest.mark.parametrize(
    ("sample_id", "predicted_family", "target_family", "family_margin"),
    (
        (
            "us-code-15-505-30cb40b784afc2dd",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.EPISTEMIC.value,
            -0.024961551256,
        ),
        (
            "us-code-16-746-e2076d8bc1b1188c",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
            -0.083034371202,
        ),
        (
            "us-code-20-7355a-33823e075ccdb9d5",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
            -0.115638346936,
        ),
        (
            "us-code-34-41107-f82a1f879ef9084c",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
            0.170663600516,
        ),
    ),
)
def test_modal_compiler_surfaces_packet_000939_adaptive_ambiguity_policy(
    monkeypatch,
    sample_id: str,
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )

    predicted_share = 0.5 if predicted_family == target_family else min(
        0.99,
        abs(family_margin) + 0.05,
    )
    target_share = (
        predicted_share - family_margin
        if predicted_family == target_family
        else predicted_share + family_margin
    )
    ranking = [
        {
            "family": predicted_family,
            "count": 0,
            "share_raw": predicted_share,
            "share": predicted_share,
        },
        {
            "family": (
                target_family
                if target_family != predicted_family
                else ModalLogicFamily.FRAME.value
            ),
            "count": 0,
            "share_raw": target_share,
            "share": target_share,
        },
    ]
    family_shares = {
        str(candidate["family"]): float(candidate["share_raw"])
        for candidate in ranking
    }
    text = f"Synthetic packet 000939 {predicted_family} ambiguity evidence."
    predicted_system = "FRAME_BM25" if predicted_family == "frame" else "D"
    predicted_symbol = "Frame" if predicted_family == "frame" else "O"
    predicted_label = "frame" if predicted_family == "frame" else "obligation"
    encoding = SpaCyLegalEncoding(
        document_id=f"packet-000939-{sample_id}",
        text=text,
        normalized_text=text,
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
                formula_id=f"f-packet-000939-{sample_id}",
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
                    end_char=len(text),
                    citation="packet-000939",
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

    expected_candidate_ids = (
        [predicted_family]
        if predicted_family == target_family
        else [predicted_family, target_family]
    )
    expected_direction = "outvoted" if family_margin < 0.0 else "contested"
    expected_type = (
        f"adaptive_{predicted_family}_{target_family}_{expected_direction}_margin_low"
    )
    policy_pair = f"{predicted_family}->{target_family}"
    base_ambiguity = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == expected_candidate_ids
        and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
    )

    assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert base_ambiguity.metadata["is_compiler_required_policy_pair"] is True
    assert base_ambiguity.metadata["is_priority_policy_pair"] is True
    assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert base_ambiguity.metadata["adaptive_margin_direction"] == expected_direction
    assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_type
    assert (
        abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
        < 1e-12
    )
