"""Hybrid structure ownership and real neural-leaf generalization controls."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from .test_rich_intent_decoder import published_child
from ipfs_datasets_py.logic.intent_ir.formalize import compositional_decoder as composed
from ipfs_datasets_py.logic.intent_ir.formalize import rich_decoder as direct
from ipfs_datasets_py.logic.intent_ir.formalize import rich_grammar as grammar

# Chosen before running recovery. These are implementation qualification cases,
# not a claim of blind held-out accuracy after the previous decoder evaluation.
CONTROL_IDS = ("authored-rich:validation:and:0", "authored-rich:test:or:0",
               "authored-rich:validation:then:0", "authored-rich:test:if:0")


@pytest.fixture(scope="module")
def fixed_controls(published_child):
    corpus = json.loads((Path(published_child["path"]).parent / "corpus.json").read_text())
    rows = {row["id"]: row for row in corpus["samples"]}
    return {key: {"sample": rows[key], "report": composed.prepare_composed_rich_intent(
        rows[key]["instruction"], published_child, beam_width=16)} for key in CONTROL_IDS}


@pytest.mark.parametrize("control_id", [CONTROL_IDS[0], CONTROL_IDS[2], CONTROL_IDS[3]])
def test_fixed_heldout_constructor_recovers_only_with_actual_neural_leaves(fixed_controls, control_id):
    sample, report = (fixed_controls[control_id][key] for key in ("sample", "report"))
    assert report["status"] == "source_supported_grammar_composed_candidate", (
        control_id, report["status"], report.get("reason"),
        [row["inference"]["status"] for row in report.get("neural_leaves", [])])
    assert report["schema"] == composed.SCHEMA
    assert report["decoding_method"] == composed.METHOD
    assert report["rich_ir"]["ast"] == sample["ast"]
    assert report["direct_report"]["rich_ir"] is None
    assert report["learned"]["encoder"] is report["learned"]["decoder"] is None
    assert report["whole_AST_generated_by_neural_encoder"] is False
    assert report["whole_inverse_generated_by_neural_decoder"] is False
    assert report["composition"]["constructor_origin"] == "explicit_source_grammar"
    parts = report["composition"]["source_parts"]
    assert "".join(part["text"] for part in parts) == sample["instruction"]
    for part in parts:
        assert sample["instruction"][part["start_char"]:part["end_char"]] == part["text"]
        assert sample["instruction"].encode()[part["start_byte"]:part["end_byte"]].decode() == part["text"]
    for row in report["neural_leaves"]:
        inference = row["inference"]
        assert inference["status"] == "source_supported_rich_candidate"
        assert inference["rich_ir"]["ast"]["kind"] == "atom"
        assert inference["instruction_sha256"] == direct.sha(row["source_span"]["text"].encode())
        assert inference["learned"]["encoder"]["checkpoint_weights_sha256"]
        assert inference["learned"]["decoder"]["checkpoint_weights_sha256"]
        assert inference["counts"]["encoder_executions"] >= 1
        assert inference["counts"]["decoder_executions"] >= 1
        assert inference["project"] is False and inference["context"] is None
    assert grammar.parse_instruction(report["learned"]["normalized_text"], normalized_inverse=True) == sample["ast"]
    if sample["ast"]["kind"] == "if":
        assert report["composition"]["guard_origin"] == "explicit_source_grammar"
        assert report["logic"]["formula"]["op"] == "implies"
        assert report["logic"]["native_intent_ir"] is None
    elif sample["ast"]["kind"] == "then":
        assert report["logic"]["lean_fixture"] is None
        assert report["logic"]["native_intent_ir_scope"] == "ordered_action_workflow"


def test_fixed_or_control_retains_honest_neural_leaf_refusal(fixed_controls):
    report = fixed_controls[CONTROL_IDS[1]]["report"]
    assert report["schema"] == composed.SCHEMA and report["beam_width"] == 16
    assert report["status"] == "fail_open_composed_leaf_rejected"
    assert report["rich_ir"] is None and report["source_agreement"] is False
    assert report["learned"]["ast"] is None
    leaf = report["neural_leaves"][0]
    assert leaf["source_span"]["text"] == "maintainer should use reserved0"
    assert leaf["inference"]["status"] == "fail_open_no_source_agreed_roundtrip"
    assert leaf["inference"]["counts"]["encoder_executions"] > 0
    assert report["composition"]["constructor"] == "or"
    assert report["composition"]["neural_structure_prediction_claimed"] is False


def test_only_raw_source_leaf_slices_reach_neural_encoder(fixed_controls, published_child, monkeypatch):
    selected = fixed_controls[CONTROL_IDS[0]]
    source, original = selected["sample"]["instruction"], selected["report"]
    actual_prepare = direct.prepare_rich_intent_instruction
    calls = []
    def traced(instruction, checkpoint, **kwargs):
        calls.append((instruction, kwargs))
        return actual_prepare(instruction, checkpoint, **kwargs)
    monkeypatch.setattr(direct, "prepare_rich_intent_instruction", traced)
    report = composed.prepare_composed_rich_intent(source, published_child, base_report=original["direct_report"])
    assert report["source_agreement"]
    assert [text for text, _ in calls] == [row["source_span"]["text"] for row in report["neural_leaves"]]
    assert all(options["project"] is False and options["context"] is None for _, options in calls)
    assert calls[0][0] == source[:source.index(" and ")]
    assert not calls[0][0].endswith(".")  # No artificial source period added.
    assert report["executed_here_counts"] == report["phase_counts"]["neural_leaves"]
    for key in report["counts"]:
        assert report["counts"][key] == report["phase_counts"]["direct"][key] + report["phase_counts"]["neural_leaves"][key]
    assert composed.validate_composed_rich_intent(report, instruction=source, checkpoint=published_child) == report


def test_rejected_neural_leaf_cannot_be_replaced_by_parser_ast(fixed_controls, published_child, monkeypatch):
    selected = fixed_controls[CONTROL_IDS[0]]
    original = direct.prepare_rich_intent_instruction
    def fail_leaf(instruction, checkpoint, **kwargs):
        if kwargs.get("project") is False:
            return original(instruction, None, **kwargs)
        return original(instruction, checkpoint, **kwargs)
    monkeypatch.setattr(direct, "prepare_rich_intent_instruction", fail_leaf)
    report = composed.prepare_composed_rich_intent(selected["sample"]["instruction"], published_child,
                                                  base_report=selected["report"]["direct_report"])
    assert report["rich_ir"] is None and report["learned"]["ast"] is None
    assert report["source_agreement"] is False
    assert report["status"] == "fail_open_composed_leaf_rejected"
    assert report["neural_leaves"][0]["inference"]["status"] == "fail_open_no_checkpoint"


def test_zero_output_head_applies_to_every_atomic_leaf(published_child):
    source = "if cache is ready, agent must inspect cache."
    report = composed.prepare_composed_rich_intent(source, published_child,
                                                  weight_ablation="zero_output_head", beam_width=0)
    assert report["schema"] == composed.SCHEMA
    assert report["rich_ir"] is None and report["source_agreement"] is False
    assert report["neural_leaves"]
    assert all(row["inference"]["weight_ablation"] == "zero_output_head" for row in report["neural_leaves"])


def test_missing_checkpoint_has_no_symbolic_action_fallback():
    report = composed.prepare_composed_rich_intent("if cache is ready, agent must inspect cache.")
    assert report["rich_ir"] is None and report["learned"]["ast"] is None
    assert report["counts"] == {"encoder_executions": 0, "decoder_executions": 0}
    assert report["continue_planning"] and report["raw_instruction_preserved"]


@pytest.mark.parametrize("source", [
    "Do not upload secrets and log outputs.",
    "if cache is ready, inspect cache and update registry.",
    "inspect cache and update registry or delete logs.",
])
def test_unsupported_whole_source_cannot_be_repaired_by_composition(source):
    report = composed.prepare_composed_rich_intent(source)
    assert report["schema"] == direct.SCHEMA
    assert report["status"] == "fail_open_input_out_of_scope" and report["rich_ir"] is None


def test_atoms_keep_genuine_direct_report_without_composition(published_child):
    source = "agent must inspect cache."
    baseline = direct.prepare_rich_intent_instruction(source, published_child)
    report = composed.prepare_composed_rich_intent(source, published_child, base_report=baseline)
    assert report == baseline and report["schema"] == direct.SCHEMA
    assert report["status"] == "source_supported_rich_candidate"


@pytest.mark.parametrize("field", ["guard", "source_slice", "neural_atom", "counts"])
def test_resigned_composed_claims_require_actual_neural_replay(fixed_controls, published_child, field):
    selected = fixed_controls[CONTROL_IDS[-1]]
    report = deepcopy(selected["report"])
    if field == "guard": report["rich_ir"]["ast"]["guard"]["negated"] = False
    elif field == "source_slice": report["neural_leaves"][0]["source_span"]["text"] = "different text"
    elif field == "neural_atom": report["rich_ir"]["ast"]["body"]["actor"] = "different"
    else: report["counts"]["encoder_executions"] += 1
    report["report_sha256"] = direct.sha(direct.wire({k: v for k, v in report.items() if k != "report_sha256"}))
    with pytest.raises(ValueError, match="neural replay"):
        composed.validate_composed_rich_intent(report, instruction=selected["sample"]["instruction"], checkpoint=published_child)


def test_cached_direct_report_requires_exact_source_and_checkpoint(fixed_controls, published_child):
    selected = fixed_controls[CONTROL_IDS[0]]
    with pytest.raises(ValueError, match="binding"):
        composed.prepare_composed_rich_intent(selected["sample"]["instruction"] + " ", published_child,
                                             base_report=selected["report"]["direct_report"])


def test_forged_cached_direct_counts_cannot_survive_full_neural_replay(fixed_controls, published_child):
    selected = fixed_controls[CONTROL_IDS[2]]
    forged = deepcopy(selected["report"]["direct_report"])
    forged["counts"]["encoder_executions"] += 1
    forged["report_sha256"] = direct.sha(direct.wire({k: v for k, v in forged.items() if k != "report_sha256"}))
    report = composed.prepare_composed_rich_intent(selected["sample"]["instruction"], published_child,
                                                 base_report=forged)
    # Independently executed leaves remain genuine, but a hash is not evidence
    # for caller-supplied performance numbers. Full replay rejects those numbers.
    assert report["source_agreement"]
    assert report["cached_direct_stage_is_numerically_replayed_here"] is False
    with pytest.raises(ValueError, match="neural replay"):
        composed.validate_composed_rich_intent(report, instruction=selected["sample"]["instruction"],
                                              checkpoint=published_child)
