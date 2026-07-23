"""Tests for typed constrained LegalIR grammar decoding."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_grammar_decoder import (
    LEGAL_IR_GRAMMAR_FAMILIES,
    LegalIRGrammarDecoder,
    constrained_legal_ir_decode,
    validate_legal_ir_candidate,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    _evaluation_objective_for_training,
)


def _valid_candidate(family: str) -> dict:
    candidates = {
        "deontic": {
            "family": "deontic",
            "rules": [
                {
                    "modality": "obligation",
                    "subject": "agency",
                    "action": "provide_notice",
                }
            ],
        },
        "frame_logic": {
            "family": "frame_logic",
            "triples": [
                {
                    "subject": "agency",
                    "relation": "must_provide",
                    "object": "notice",
                }
            ],
        },
        "tdfol": {
            "family": "tdfol",
            "formulas": [
                {
                    "quantifier": "forall",
                    "predicate": "ProvideNotice",
                    "arguments": ["agency", "notice"],
                }
            ],
        },
        "knowledge_graphs": {
            "family": "knowledge_graphs",
            "nodes": [
                {"id": "agency", "label": "Agency"},
                {"id": "notice", "label": "Notice"},
            ],
            "edges": [
                {
                    "source": "agency",
                    "target": "notice",
                    "label": "must_provide",
                }
            ],
        },
        "cec": {
            "family": "cec",
            "events": [{"id": "e1", "type": "omission"}],
            "counterexamples": [{"violates": "notice_obligation"}],
        },
        "external_provers": {
            "family": "external_provers",
            "backend": "z3",
            "obligations": [{"id": "po1", "goal": "ProvideNotice(agency)"}],
        },
        "temporal": {
            "family": "temporal",
            "intervals": [{"id": "i1", "duration": "30 days"}],
            "relations": [{"before": "final_action", "after": "notice"}],
        },
        "provenance": {
            "family": "provenance",
            "source_refs": [{"citation": "5 U.S.C. 552", "span_hash": "abc"}],
            "evidence": [{"receipt_id": "r1", "source_hash": "def"}],
        },
        "decompiler": {
            "family": "decompiler",
            "target_view": "deontic.ir",
            "source_copy_policy": "hash_only",
            "steps": [{"op": "emit_rule", "slot": "obligation"}],
        },
    }
    return candidates[family]


@pytest.mark.parametrize("family", LEGAL_IR_GRAMMAR_FAMILIES)
def test_typed_grammar_accepts_valid_family_candidates(family: str) -> None:
    result = validate_legal_ir_candidate(_valid_candidate(family), family=family)

    assert result.accepted is True
    assert result.family == family
    assert result.rejection_reasons == ()
    assert result.metrics()["legal_ir_grammar_syntactic_validity_success_rate"] == 1.0


def test_typed_grammar_records_family_specific_rejection_reasons() -> None:
    result = validate_legal_ir_candidate(
        {
            "family": "tdfol",
            "formulas": [{"predicate": "not a predicate", "arguments": []}],
        },
        family="tdfol",
    )

    assert result.accepted is False
    names = result.rejection_reason_names
    assert "invalid_tdfol_predicate" in names
    assert "missing_tdfol_arguments" in names
    assert result.metrics()["legal_ir_grammar_invalid_production_penalty"] == 1.0
    assert (
        result.metrics()[
            "legal_ir_grammar_rejection_reason_invalid_tdfol_predicate"
        ]
        == 1.0
    )


def test_decoder_masks_invalid_high_score_production_before_selection() -> None:
    valid = _valid_candidate("deontic")
    invalid = {
        "family": "deontic",
        "rules": [
            {
                "modality": "maybe",
                "subject": "agency",
                "action": "provide_notice",
            }
        ],
    }

    result = constrained_legal_ir_decode(
        [
            {
                "production": "invalid_high_score",
                "family": "deontic",
                "score": 99.0,
                "output": invalid,
            },
            {
                "production": "valid_low_score",
                "family": "deontic",
                "score": 0.1,
                "output": valid,
            },
        ]
    )

    assert result.accepted is True
    assert result.selected_production == "valid_low_score"
    assert result.decoded_ir == valid
    assert "invalid_high_score" in result.masked_scores
    assert "valid_low_score" in result.valid_scores


def test_source_copy_placeholders_are_rejected_with_specific_reason() -> None:
    source_text = (
        "The agency shall provide notice before the hearing and preserve the "
        "record for review."
    )
    result = validate_legal_ir_candidate(
        {
            "family": "decompiler",
            "target_view": "deontic.ir",
            "source_copy_policy": "hash_only",
            "steps": [{"op": "emit_text", "surface": source_text}],
        },
        family="decompiler",
        source_text=source_text,
    )

    assert result.accepted is False
    assert "source_copy_placeholder" in result.rejection_reason_names
    assert result.metrics()["legal_ir_grammar_source_copy_placeholder_penalty"] == 1.0


def test_autoencoder_penalizes_invalid_decoded_ir_before_objective_reward() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552-grammar-guard",
        text="The agency shall provide notice before the hearing.",
    )
    target_distribution = {
        "deontic.ir": 0.8,
        "TDFOL.prover": 0.2,
    }
    valid_target = SimpleNamespace(
        losses={"legal_ir_multiview_total_loss": 0.01},
        view_distribution=target_distribution,
        decoded_ir=_valid_candidate("deontic"),
        document=SimpleNamespace(canonical_hash=lambda: "valid-grammar-target"),
    )
    invalid_target = SimpleNamespace(
        losses={"legal_ir_multiview_total_loss": 0.0},
        view_distribution=target_distribution,
        decoded_ir={
            "family": "deontic",
            "rules": [
                {
                    "modality": "placeholder",
                    "subject": "SOURCE_TEXT",
                    "action": "TODO",
                }
            ],
        },
        document=SimpleNamespace(canonical_hash=lambda: "invalid-grammar-target"),
    )
    autoencoder = AdaptiveModalAutoencoder(compute_device="python")

    valid_eval = autoencoder.evaluate(
        [sample],
        legal_ir_targets={sample.sample_id: valid_target},
    )
    invalid_eval = autoencoder.evaluate(
        [sample],
        legal_ir_targets={sample.sample_id: invalid_target},
    )

    assert "legal_ir_grammar_rejection_reasons" in invalid_eval.to_dict()
    assert invalid_eval.legal_ir_losses[
        "legal_ir_grammar_invalid_production_penalty"
    ] == pytest.approx(1.0)
    assert invalid_eval.legal_ir_losses[
        "legal_ir_grammar_source_copy_placeholder_penalty"
    ] == pytest.approx(1.0)
    assert invalid_eval.legal_ir_grammar_rejection_reasons[sample.sample_id]
    assert _evaluation_objective_for_training(invalid_eval, legal_ir=1.0) > (
        _evaluation_objective_for_training(valid_eval, legal_ir=1.0)
    )
