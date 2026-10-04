"""Actual neural recovery, explicit ablation and bounded document accounting."""
import json
from pathlib import Path

import pytest

from .test_rich_intent_decoder import published_child
from ipfs_datasets_py.logic.intent_ir.formalize.rich_document import prepare_rich_intent_document


@pytest.mark.parametrize("options", [
    {"beam_width": True}, {"beam_width": -1}, {"beam_width": 17},
    {"composition_recovery": "yes"},
])
def test_invalid_recovery_options_refused_before_checkpoint_load(options):
    with pytest.raises(ValueError):
        prepare_rich_intent_document("agent must inspect cache.",
            {"schema": "intent-rich-copy-checkpoint/v1"}, **options)


@pytest.mark.parametrize("instruction", [
    "Then inspect cache.", "if it is ready, agent must inspect cache.",
    "agent must inspect it then agent must save cache.",
    "agent must inspect next file then agent must save cache.",
    "next agent must inspect cache then agent must save cache.",
    "agent must next cache then agent must save cache.",
])
def test_sequence_admission_does_not_admit_unresolved_antecedents(instruction):
    result = prepare_rich_intent_document(instruction,
        {"schema": "intent-rich-copy-checkpoint/v1"})
    assert result["counts"]["inference_attempts"] == 0
    assert not result["candidates"]


@pytest.mark.parametrize("identifier", [
    "authored-rich:validation:then:0", "authored-rich:test:if:0",
])
def test_actual_compound_recovery_can_be_ablated_without_changing_source(published_child, identifier):
    corpus = json.loads((Path(published_child["path"]).parent / "corpus.json").read_text())
    # Fixed before model execution; no search for successful examples.
    row = next(row for row in corpus["samples"] if row["id"] == identifier)
    direct = prepare_rich_intent_document(row["instruction"], published_child,
        composition_recovery=False)
    recovered = prepare_rich_intent_document(row["instruction"], published_child)
    assert not direct["candidates"]
    assert direct["counts"]["composition_attempts"] == 0
    assert len(recovered["candidates"]) == 1
    assert recovered["candidates"][0]["rich_ir"]["ast"] == row["ast"]
    assert recovered["counts"]["composition_attempts"] == 1
    assert recovered["counts"]["composed_accepted_clauses"] == 1
    assert recovered["counts"]["direct_accepted_clauses"] == 0
    unit = next(unit for unit in recovered["units"] if unit["accepted"])
    inference = unit["inference"]
    assert unit["decoding_method"] == "grammar_composition_with_neural_leaves"
    assert inference["cached_direct_stage_reused"]
    assert not inference["whole_AST_generated_by_neural_encoder"]
    assert inference["learned"]["encoder"] is None
    for key in ("encoder_executions", "decoder_executions"):
        assert recovered["counts"][key] == inference["counts"][key]
        assert inference["counts"][key] == (direct["counts"][key] +
            inference["phase_counts"]["neural_leaves"][key])
    assert all(leaf["inference"]["learned"]["encoder"] and
        leaf["inference"]["learned"]["decoder"] for leaf in inference["neural_leaves"])
    assert "".join(unit["text"] for unit in recovered["units"]) == row["instruction"]
    assert unit["atomic_family_projection"] is None
    assert unit["selected_native_targets"] == []
