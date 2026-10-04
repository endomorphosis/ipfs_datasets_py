"""Actual bidirectional weights, native semantics, and fail-open advice checks."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import roundtrip as sut
from ipfs_datasets_py.logic.intent_ir.formalize import roundtrip_training as training
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_paired_text as paired


def frame(modality="required", **kwargs):
    return {"actor": "agent", "action": "inspect", "object": "cache", "modality": modality, **kwargs}


def sample(index, semantic, split="train", instruction=None):
    canonical = sut.canonical_frame_text(semantic)
    return {"id": f"authored:{index}", "split": split, "group_id": f"family:{index}",
            "instruction": instruction or canonical, "frame": semantic,
            "canonical_text": canonical, "provenance": {"kind": "authored_development_control"}}


@pytest.fixture(scope="module")
def checkpoint(tmp_path_factory):
    import torch
    torch.set_num_threads(1)
    rows = [sample(index, frame(modality)) for index, modality in enumerate(sut.MODALS)]
    rows.append(sample("validation", frame(actor="operator"), "validation"))
    rows.append(sample("unused-test", frame(object="quasarprobe"), "test"))
    corpus = {"samples": rows}
    root = tmp_path_factory.mktemp("intent-roundtrip")
    receipt = training.train_intent_roundtrip(corpus, root / "package", epochs=140,
        max_seconds=40, hidden_size=48, embedding_dim=24)
    return receipt["checkpoint"], receipt, rows


@pytest.mark.parametrize("modality", tuple(sut.MODALS))
def test_modalities_and_negation_survive_all_native_codec_directions(modality):
    original = frame(modality)
    sequence = sut.frame_to_sequence(original)
    assert sut.sequence_to_frame(sequence) == original
    text = sut.canonical_frame_text(original)
    assert sut.normalized_text_to_frame(text) == original
    document = sut.frame_to_intent_ir(original, instruction=f"source declaration for {modality}")
    assert sut.intent_ir_to_frame(document) == original
    assert sut.intent_ir_to_frame(document.to_dict()) == original
    statement = document.statements[0]
    assert statement.grounding.value == document.actions[0].grounding.value == "inferred"
    assert statement.review_status.value == "machine_extracted" and statement.confidence == 0
    assert statement.modality.value == modality
    if modality == "prohibited":
        assert text == "agent must not inspect cache."


def test_native_source_binding_and_compiler_projections_do_not_promote_authority():
    from ipfs_datasets_py.logic.formalization.autoencoder.domain_targets import prepare_intent_targets
    instruction = "Please do not inspect the cache."
    document = sut.frame_to_intent_ir(frame("prohibited"), instruction=instruction)
    source = document.sources[0]
    assert source.content_sha256 == hashlib.sha256(instruction.encode()).hexdigest()
    assert source.span.start_char == 0 and source.span.end_char == len(instruction)
    targets = prepare_intent_targets(document).to_dict()
    assert targets["projections"]
    assert not targets["qualified"] and not targets["admitted"]
    assert any(p["native_formulas"] for p in targets["projections"])
    assert any("source_meaning_not_verified" == gap for gap in targets["qualification_gaps"])


@pytest.mark.parametrize("extra", ["tool_refs", "input_refs", "output_refs"])
def test_inverse_refuses_action_constraints_that_the_codec_would_drop(extra):
    document = sut.frame_to_intent_ir(frame(), instruction="agent must inspect cache.")
    action = replace(document.actions[0], **{extra: ("extra-binding",)})
    with pytest.raises(ValueError, match="unsupported action constraints"):
        sut.intent_ir_to_frame(replace(document, actions=(action,)))


def test_inverse_refuses_additional_statements_workflows_or_conflicting_fields():
    from ipfs_datasets_py.logic.intent_ir.schema import StatementKind, NodeGrounding
    document = sut.frame_to_intent_ir(frame(), instruction="agent must inspect cache.")
    extra = replace(document.statements[0], statement_id="invariant", kind=StatementKind.INVARIANT)
    with pytest.raises(ValueError, match="outside the learned"):
        sut.intent_ir_to_frame(replace(document, statements=(*document.statements, extra)))
    with pytest.raises(ValueError, match="semantic fields disagree"):
        sut.intent_ir_to_frame(replace(document, actions=(replace(document.actions[0], verb="delete"),)))
    with pytest.raises(ValueError, match="grounding"):
        sut.intent_ir_to_frame(replace(document, actions=(replace(document.actions[0], grounding=NodeGrounding.GROUNDED),)))


@pytest.mark.parametrize("bad", [
    "<actor> agent <action> inspect <object> cache <modality> required <proof> proven",
    "<actor> agent <action> inspect and delete <object> cache <modality> required",
    "<actor> agent <action> inspect <object> cache <modality> authorized",
    "<actor> Agent <action> inspect <object> cache <modality> required",
])
def test_neural_sequence_grammar_rejects_extra_slots_and_unsupported_values(bad):
    with pytest.raises(ValueError):
        sut.sequence_to_frame(bad)


def test_actual_shared_training_has_two_directions_and_excludes_test_vocabulary(checkpoint):
    descriptor, receipt, _ = checkpoint
    loaded = sut.load_intent_roundtrip_checkpoint(descriptor)
    backend = loaded["backend"]
    assert receipt["training_pair_count"] == 10
    assert receipt["test_used_for_training_or_tuning"] is False
    assert receipt["shared_training"]["optimizer_steps"] == 140
    assert receipt["shared_training"]["native_kernel_calls"] > 0
    assert "quasarprobe" not in backend["config"]["vocabulary"]
    assert receipt["shared_training"]["initial_state_sha256"] != receipt["shared_training"]["final_state_sha256"]


def test_real_neural_roundtrip_and_inverse_only_receive_typed_ir(checkpoint, monkeypatch):
    descriptor, _, _ = checkpoint
    before = Path(descriptor["path"]).read_bytes()
    calls, original = [], paired.infer_paired_text
    def traced(selected, source, direction, *args, **kwargs):
        calls.append((source, direction))
        return original(selected, source, direction, *args, **kwargs)
    monkeypatch.setattr(paired, "infer_paired_text", traced)
    instruction = "agent must not inspect cache."
    report = sut.prepare_roundtrip_intent_instruction(instruction, descriptor)
    assert report["status"] == "semantic_candidate_advice"
    assert report["learned"]["frame"] == frame("prohibited")
    assert report["learned"]["normalized_text"] == instruction
    assert calls == [(instruction, "encode"), (sut.frame_to_sequence(frame("prohibited")), "decode")]
    assert report["provider_calls"] == report["download_calls"] == report["training_steps"] == 0
    assert all(report[key] is False for key in ("proof_authority", "execution_authority", "completion_authority"))
    assert Path(descriptor["path"]).read_bytes() == before
    other_source = sut.frame_to_intent_ir(frame("prohibited"), instruction="Different original source bytes.")
    direct = sut.decode_intent_text(descriptor, other_source)
    assert calls[-1] == (sut.frame_to_sequence(frame("prohibited")), "decode")
    assert direct["generated_text"] == report["learned"]["decoder"]["generated_text"]
    assert direct["target_access"] is False and direct["training_executed"] is False


def test_zeroed_real_output_head_changes_inference_without_mutating_checkpoint(checkpoint):
    descriptor, _, _ = checkpoint
    loaded = sut.load_intent_roundtrip_checkpoint(descriptor)
    model_file = Path(loaded["backend_descriptor"]["path"])
    before = model_file.read_bytes()
    document = sut.frame_to_intent_ir(frame(), instruction="agent must inspect cache.")
    normal = sut.decode_intent_text(descriptor, document)
    zeroed = sut.decode_intent_text(descriptor, document, weight_ablation="zero_output_head")
    assert normal["status"] == "generated"
    assert zeroed["status"] == "invalid_or_incomplete_output"
    assert zeroed["tokens"] != normal["tokens"]
    assert model_file.read_bytes() == before


def test_fail_open_paths_preserve_planning_without_candidates(checkpoint):
    descriptor, _, _ = checkpoint
    cases = [
        ("agent must inspect cache.", None, "fail_open_no_checkpoint"),
        ("agent must inspect quasarprobe.", descriptor, "fail_open_encoder_generation"),
        ("", descriptor, "fail_open_input_out_of_scope"),
        ("word " * 49, descriptor, "fail_open_input_out_of_scope"),
        ("agent must inspect cache.", {**descriptor, "sha256": "0" * 64}, "fail_open_checkpoint_or_decode_error"),
    ]
    for instruction, selected, expected in cases:
        result = sut.prepare_roundtrip_intent_instruction(instruction, selected)
        assert result["status"] == expected
        assert result["continue_planning"] is result["raw_instruction_preserved"] is True
        assert result["candidate_intent_ir"] is result["projections"] is None
        assert result["instruction_sha256"] == hashlib.sha256(instruction.encode()).hexdigest()


def test_replay_rejects_forged_source_scores_and_authority(checkpoint):
    descriptor, _, _ = checkpoint
    instruction = "agent must inspect cache."
    report = sut.prepare_roundtrip_intent_instruction(instruction, descriptor)
    assert report["status"] == "semantic_candidate_advice"
    sut.validate_roundtrip_intent_report(report, instruction=instruction, checkpoint_descriptor=descriptor)
    for key, replacement in (("proof_authority", True), ("instruction_sha256", "f" * 64),
                             ("status", "proved_semantics")):
        forged = deepcopy(report)
        forged[key] = replacement
        forged.pop("report_sha256")
        sut._finish(forged)
        with pytest.raises(ValueError, match="numerical/source replay"):
            sut.validate_roundtrip_intent_report(forged, instruction=instruction, checkpoint_descriptor=descriptor)
    with pytest.raises(ValueError, match="numerical/source replay"):
        sut.validate_roundtrip_intent_report(report, instruction="agent must not inspect cache.", checkpoint_descriptor=descriptor)


def test_inverse_frame_labels_and_source_family_leakage_rejected_before_training(tmp_path):
    first = sample("first", frame())
    second = sample("validation", frame(actor="operator"), "validation")
    corpus = {"samples": [first, second]}
    training._validated_samples(corpus)
    invalid = deepcopy(corpus)
    invalid["samples"][1]["frame"] = frame()
    invalid["samples"][1]["canonical_text"] = first["canonical_text"]
    with pytest.raises(ValueError, match="split leakage"):
        training.train_intent_roundtrip(invalid, tmp_path / "not-created", epochs=1)
    assert not (tmp_path / "not-created").exists()
    invalid = deepcopy(corpus)
    invalid["samples"][0]["canonical_text"] = "agent must not inspect cache."
    with pytest.raises(ValueError, match="canonical inverse label"):
        training._validated_samples(invalid)


def test_evaluation_keeps_invalid_and_oov_predictions_in_denominator(checkpoint):
    descriptor, _, rows = checkpoint
    report = training.evaluate_intent_roundtrip(descriptor, [rows[0], rows[-1]])
    assert report["metrics"]["count"] == 2
    assert report["teacher_forcing"] is report["inference_target_access"] is False
    assert report["rows"][1]["encoder_oov"] is True
    assert report["rows"][1]["encode_exact"] is False
    assert report["metrics"]["encode_exact_rate"] <= 0.5
    zeroed = training.evaluate_intent_roundtrip(descriptor, [rows[0]], weight_ablation="zero_output_head")
    assert zeroed["metrics"]["count"] == 1
    assert zeroed["metrics"]["encode_valid_rate"] == zeroed["metrics"]["composed_exact_rate"] == 0


def test_evaluation_survives_collapsed_predictions_and_excludes_oov_from_deployable(monkeypatch):
    observations = []
    def evaluate(descriptor, pairs, **kwargs):
        observations.append(deepcopy(pairs))
        targets = {}
        for row in pairs:
            key = row["direction"], row["source"]
            assert key not in targets or targets[key] == row["target"]
            targets[key] = row["target"]
        return {"rows": [{"id": row["id"], "status": "generated",
            "generated_text": sut.frame_to_sequence(frame()) if row["direction"] == "encode" else sut.canonical_frame_text(frame()),
            "input_oov_tokens": ["unrecognized"] if row["id"] == "authored:one" and row["direction"] == "encode" else []}
            for row in pairs]}
    monkeypatch.setattr(training, "load_intent_roundtrip_checkpoint", lambda _: {"backend_descriptor": {}})
    monkeypatch.setattr(paired, "evaluate_paired_text", evaluate)
    report = training.evaluate_intent_roundtrip({}, [sample("one", frame()), sample("two", frame(object="report"))])
    assert len(observations) == 4
    assert observations[2][0]["source"] == observations[2][1]["source"]
    assert observations[2][0]["target"] == observations[2][1]["target"]
    assert report["rows"][0]["encode_exact"] is True
    assert report["rows"][0]["deployable_candidate"] is False
    assert report["rows"][1]["cycle_consistent"] is True
    assert report["rows"][1]["composed_exact"] is False
    assert report["metrics"]["composed_exact_rate"] == 0.5
    assert report["metrics"]["deployable_exact_rate"] == 0


def test_tokenized_internal_hyphen_reconstructs_the_supported_literal():
    original = frame(object="common anti-patterns")
    tokenized = sut.frame_to_sequence(original).replace("anti-patterns", "anti - patterns")
    assert sut.sequence_to_frame(tokenized) == original
    assert sut.normalized_text_to_frame("agent must inspect common anti - patterns .") == original


def test_normalized_input_split_collision_rejected_before_output():
    original = sample("one", frame())
    changed = sample("two", frame(object="report"), "validation", instruction="agent  must\tinspect cache.")
    with pytest.raises(ValueError, match="split leakage"):
        training._validated_samples({"samples": [original, changed]})


def test_native_projection_failure_cannot_be_marked_deployable(checkpoint, monkeypatch):
    descriptor, _, rows = checkpoint
    def unsupported(*args, **kwargs):
        raise ValueError("native representation unavailable")
    monkeypatch.setattr(training, "frame_to_intent_ir", unsupported)
    report = training.evaluate_intent_roundtrip(descriptor, [rows[0]])
    assert report["rows"][0]["encode_exact"] is True
    assert report["rows"][0]["native_ir_valid"] is False
    assert report["rows"][0]["deployable_candidate"] is False
    assert report["rows"][0]["deployable_exact"] is False
