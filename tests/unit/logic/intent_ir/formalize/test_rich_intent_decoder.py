"""Independent rich grammar checks and actual frozen-child inference controls."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import rich_grammar as grammar
from ipfs_datasets_py.logic.intent_ir.formalize import rich_decoder as decoder
from ipfs_datasets_py.logic.intent_ir.formalize import rich_document as document
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_paired_copy_continuation as backend


@pytest.mark.parametrize("instruction,kind", [
    ("Find restaurants by name.", "atom"),
    ("Fetch the activation package.", "atom"),
    ("Do not reuse the full system report template.", "atom"),
    ("Alice must inspect `Config.YAML`.", "atom"),
    ("Inspect src/Config.py.", "atom"),
    ("inspect cache and update registry.", "and"),
    ("agent must inspect cache and user may update registry.", "and"),
    ("agent must inspect cache or user must update registry.", "or"),
    ("agent must inspect cache then user must update registry.", "then"),
    ("If cache is ready, agent must inspect cache.", "if"),
    ("if cache is not ready, user must not update registry.", "if"),
])
def test_declared_grammar_roundtrip_preserves_full_ast(instruction, kind):
    ast = grammar.parse_instruction(instruction)
    assert ast["kind"] == kind
    assert grammar.sequence_to_ast(grammar.ast_to_sequence(ast)) == ast
    assert grammar.parse_instruction(grammar.ast_to_text(ast), normalized_inverse=True) == ast


def test_case_sensitive_source_leaves_are_not_normalized_away():
    ast = grammar.parse_instruction("Alice must inspect `Config.YAML`.")
    assert ast["actor"] == "Alice" and ast["object"] == "`Config.YAML`"
    assert ast != grammar.parse_instruction("alice must inspect `Config.YAML`.")
    assert ast != grammar.parse_instruction("Alice must inspect `config.yaml`.")
    assert grammar.sequence_to_ast("<actor> Alice <action> inspect <object> ` Config . YAML ` <modality> required") == ast


def test_model_input_preserves_explicit_actor_and_identifier_case():
    assert grammar.model_input("Inspect `Config.YAML`.") == "inspect `Config.YAML`."
    assert grammar.model_input("Inspect must check `Config.YAML`.") == "Inspect must check `Config.YAML`."
    assert grammar.model_input("Alice must inspect `Config.YAML`.") == "Alice must inspect `Config.YAML`."


@pytest.mark.parametrize("instruction", [
    "agent must inspect cache and update registry.",
    "Do not upload secrets and log outputs.",
    "Must inspect cache and delete logs.",
    "Never upload secrets or delete logs.",
    "if cache is ready, inspect cache and update registry.",
    "inspect cache and update registry or delete logs.",
    "if cache is ready, if registry is ready, inspect cache.",
    "if cache exists, inspect cache.",
    "unless cache is ready, inspect cache.",
    "inspect every file.",
    "inspect cache without changing logs.",
    "inspect it.",
    "Group activity trends analyzed with monthly breakdowns",
    "Search results come from public search engines",
    "Benchmark suite for model comparison.",
    "Search or select the service.",
    "inspect cache\nupdate registry.",
])
def test_ambiguous_unsupported_or_nested_scope_is_not_flattened(instruction):
    with pytest.raises(ValueError):
        grammar.parse_instruction(instruction)


def test_conditional_and_modal_position_are_distinct_structures():
    ast = grammar.parse_instruction("if cache is not ready, agent must not update registry.")
    assert ast["guard"] == {"subject":"cache", "property":"ready", "negated":True}
    assert ast["body"]["modality"] == "prohibited"
    assert ast != ast["body"]
    changed = deepcopy(ast)
    changed["guard"]["negated"] = False
    assert grammar.ast_to_sequence(changed) != grammar.ast_to_sequence(ast)


@pytest.mark.parametrize("source", [
    "## Examples\n\nagent must inspect cache.\n",
    "```text\nagent must inspect cache.\n```\n",
    "## Prohibited\n\ninspect cache.\n",
    "The following actions are prohibited:\n\ninspect cache.\n",
    "1. Do not perform these actions:\n   - inspect cache.\n",
    "```text\vagent must inspect cache.\v```",
])
def test_document_context_prevents_inference_for_examples_fences_and_shared_scope(source, monkeypatch):
    monkeypatch.setattr(document, "prepare_rich_intent_instruction",
                        lambda *a, **k: pytest.fail("unsupported source reached neural inference"))
    report = document.prepare_rich_intent_document(source, {"schema":decoder.CHECKPOINT_SCHEMA})
    assert report["counts"]["inference_attempts"] == report["counts"]["accepted_clauses"] == 0
    assert "".join(row["text"] for row in report["units"]) == source


def test_document_partial_selection_retains_source_without_creating_command(monkeypatch):
    source = "agent must inspect cache."
    monkeypatch.setattr(document, "prepare_rich_intent_instruction",
                        lambda *a, **k: pytest.fail("partial source reached neural inference"))
    result = document.prepare_rich_intent_document(source, {"schema":decoder.CHECKPOINT_SCHEMA},
                                                  start_char=11, end_char=24)
    assert result["counts"]["inference_attempts"] == 0
    assert "".join(row["text"] for row in result["units"]) == source[11:24]
    assert all(row["reason"] == "selection_splits_source_unit" for row in result["units"])


@pytest.mark.parametrize("families", [["smt"], ["tla_plus"], ["higher_order", "higher_order"], []])
def test_document_family_selection_is_canonical_and_unique(families):
    with pytest.raises(ValueError, match="canonical"):
        document.prepare_rich_intent_document("Inspect cache.", {"schema":decoder.CHECKPOINT_SCHEMA},
                                              requested_families=families)


def test_no_checkpoint_remains_fail_open_without_teacher_candidate():
    report = decoder.prepare_rich_intent_instruction("if cache is ready, agent must inspect cache.")
    assert report["status"] == "fail_open_no_checkpoint"
    assert report["rich_ir"] is None and report["learned"]["ast"] is None
    assert report["counts"] == {"encoder_executions":0, "decoder_executions":0}
    assert report["raw_instruction_preserved"] and report["continue_planning"]


@pytest.fixture(scope="module")
def published_child():
    import torch
    torch.set_num_threads(1)
    default = Path(__file__).resolve().parents[7] / "artifacts/intent-rich-decoder-20261002/inference-01/descriptor.json"
    selected = Path(os.environ.get("INTENT_RICH_TEST_CHECKPOINT", str(default)))
    if not selected.exists():
        pytest.skip("frozen rich child descriptor is not installed; set INTENT_RICH_TEST_CHECKPOINT")
    value = json.loads(selected.read_text())
    decoder.load_rich_intent_checkpoint(value)
    return value


@pytest.fixture(scope="module")
def actual_candidate(published_child):
    instruction = "agent must inspect cache."
    report = decoder.prepare_rich_intent_instruction(instruction, published_child)
    assert report["status"] == "source_supported_rich_candidate", report
    assert report["counts"]["encoder_executions"] >= 1
    assert report["counts"]["decoder_executions"] >= 1
    return instruction, report


def test_actual_child_inference_is_source_bound_and_replayable(actual_candidate, published_child):
    instruction, report = actual_candidate
    loaded = decoder.load_rich_intent_checkpoint(published_child)
    assert report["learned"]["encoder"]["checkpoint_weights_sha256"] == loaded["backend"]["training"]["final_state_sha256"]
    assert report["learned"]["decoder"]["checkpoint_weights_sha256"] == loaded["backend"]["training"]["final_state_sha256"]
    assert report["learned"]["ast"] == grammar.parse_instruction(instruction)
    assert decoder.validate_rich_intent_report(report, instruction=instruction, checkpoint_descriptor=published_child) == report
    assert report["training_steps"] == report["llm_calls"] == 0
    assert not report["source_semantics_verified"] and not report["proof_authority"]


@pytest.mark.parametrize("kind", ["and", "or", "then", "if"])
def test_actual_learned_rich_constructor_reaches_scoped_logic(published_child, kind):
    # Predeclared training controls qualify the implementation, not held-out
    # model accuracy. Never select a control by whether inference accepted it.
    corpus = json.loads((Path(published_child["path"]).parent / "corpus.json").read_text())
    examples = {row["id"]:row for row in corpus["samples"]}
    example = examples["authored-rich:train:" + kind + ":0"]
    instruction = example["instruction"]
    report = decoder.prepare_rich_intent_instruction(instruction, published_child)
    assert report["status"] == "source_supported_rich_candidate", report
    assert report["learned"]["ast"]["kind"] == kind
    assert report["learned"]["ast"] == grammar.parse_instruction(instruction)
    assert report["counts"]["encoder_executions"] >= 1 and report["counts"]["decoder_executions"] >= 1
    logic = report["logic"]
    if kind == "then":
        assert logic["native_intent_ir_scope"] == "ordered_action_workflow"
        assert logic["lean_fixture"] is None
    elif kind == "if":
        assert logic["formula"]["op"] == "implies"
        antecedent = logic["formula"]["left"]
        if example["ast"]["guard"]["negated"]:
            assert antecedent["op"] == "not"
            antecedent = antecedent["body"]
        assert antecedent["predicate"] == "property:" + example["ast"]["guard"]["property"]
        assert logic["native_intent_ir"] is None
    else:
        assert logic["formula"]["op"] == kind and logic["native_intent_ir"] is None


@pytest.mark.parametrize("changed", [
    "agent must not inspect cache.", "user must inspect cache.", "agent must inspect Cache.",
    "if cache is ready, agent must inspect cache.",
])
def test_post_inference_guard_rejects_changed_scope_actor_or_case(actual_candidate, published_child, monkeypatch, changed):
    _instruction, original = actual_candidate
    # Fault injection presents an actually generated old atom for a different
    # source. The parser may reject it but may never replace it with a teacher.
    calls = []
    def wrong_prediction(descriptor, source, direction, **kwargs):
        calls.append(direction)
        assert direction == "encode", "source disagreement reached inverse inference"
        return deepcopy(original["learned"]["encoder"])
    monkeypatch.setattr(backend, "infer_paired_copy_continuation", wrong_prediction)
    result = decoder.prepare_rich_intent_instruction(changed, published_child, beam_width=0)
    assert result["rich_ir"] is None and result["source_agreement"] is False
    assert result["status"] == "fail_open_no_source_agreed_roundtrip"
    assert calls == ["encode"]


def test_rehashed_ast_tampering_cannot_bypass_learned_replay(actual_candidate, published_child):
    instruction, original = actual_candidate
    report = deepcopy(original)
    report["rich_ir"]["ast"]["actor"] = "different"
    report["report_sha256"] = decoder.sha(decoder.wire({k:v for k,v in report.items() if k != "report_sha256"}))
    with pytest.raises(ValueError, match="learned replay"):
        decoder.validate_rich_intent_report(report, instruction=instruction, checkpoint_descriptor=published_child)


def test_same_meaning_different_source_bytes_do_not_replay_old_receipt(actual_candidate, published_child):
    instruction, report = actual_candidate
    with pytest.raises(ValueError, match="learned replay"):
        decoder.validate_rich_intent_report(report, instruction=instruction + " ", checkpoint_descriptor=published_child)


def test_stale_checkpoint_digest_fails_open_without_parser_fallback(published_child):
    descriptor = {**published_child, "sha256":"0" * 64}
    report = decoder.prepare_rich_intent_instruction("agent must inspect cache.", descriptor)
    assert report["status"] == "fail_open_checkpoint_or_inference_error"
    assert report["rich_ir"] is None and report["learned"]["ast"] is None
    assert report["counts"] == {"encoder_executions":0, "decoder_executions":0}
    assert report["continue_planning"] and report["raw_instruction_preserved"]


def test_actual_output_ablation_does_not_invent_teacher_fallback(actual_candidate, published_child):
    instruction, original = actual_candidate
    report = decoder.prepare_rich_intent_instruction(instruction, published_child,
                                                   weight_ablation="zero_output_head", beam_width=0)
    assert report["rich_ir"] is None and report["source_agreement"] is False
    assert report["learned"]["encoder"]["tokens"] != original["learned"]["encoder"]["tokens"]


@pytest.mark.parametrize("change", ["source", "checkpoint", "clause", "unit"])
def test_document_rejects_stale_exact_context_binding(published_child, change):
    source = "agent must inspect cache."
    report = document.prepare_rich_intent_document(source, published_child)
    assert report["counts"]["accepted_clauses"] == 1
    unit = next(row for row in report["units"] if row["accepted"])
    context = {"schema":document.CONTEXT_SCHEMA, "source_sha256":decoder.sha(source.encode()),
        "checkpoint_sha256":decoder.sha(decoder.wire(published_child)),
        "units":[{"unit_id":unit["unit_id"], "clause_sha256":unit["inference"]["instruction_sha256"], "slot_context":None}]}
    if change == "source": context["source_sha256"] = "0" * 64
    elif change == "checkpoint": context["checkpoint_sha256"] = "0" * 64
    elif change == "clause": context["units"][0]["clause_sha256"] = "0" * 64
    else: context["units"][0]["unit_id"] = "wrong"
    with pytest.raises(ValueError):
        document.prepare_rich_intent_document(source, published_child, context=context)
