"""Source-copy IntentIR package boundaries and actual numerical integration."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import copy_roundtrip as sut
from ipfs_datasets_py.logic.intent_ir.formalize import copy_training as training
from ipfs_datasets_py.logic.intent_ir.formalize import roundtrip


def frame(modality="required", **kwargs):
    return {"actor": "agent", "action": "inspect", "object": "cache", "modality": modality, **kwargs}


def sample(index, semantic, split="train"):
    text = roundtrip.canonical_frame_text(semantic)
    return {"id": f"authored:{index}", "split": split, "group_id": f"copy-family:{index}",
            "instruction": text, "frame": semantic, "canonical_text": text,
            "provenance": {"kind": "authored_copy_contract_control"}}


@pytest.fixture(scope="module")
def checkpoint(tmp_path_factory):
    import torch
    torch.set_num_threads(1)
    rows = [sample(i, frame(modal)) for i, modal in enumerate(roundtrip.MODALS)]
    rows += [sample("validation", frame(actor="operator"), "validation"),
             sample("heldout", frame(object="nebularwidget"), "test")]
    receipt = training.train_intent_copy({"samples": rows}, tmp_path_factory.mktemp("intent-copy") / "model",
        epochs=180, max_seconds=45, hidden_size=48, embedding_dim=24)
    return receipt["checkpoint"], receipt, rows


@pytest.mark.parametrize("replacement", [
    {"input_coverage_complete": False}, {"uncovered_input_tokens": ["newword"]},
    {"tokens": ["<unk>"]}, {"ended": False}, {"status": "invalid_or_incomplete_output"},
])
def test_unknown_input_requires_complete_copy_addressability(replacement):
    report = {"status": "generated", "ended": True, "tokens": ["newword"],
              "input_oov_tokens": ["newword"], "input_coverage_complete": True,
              "uncovered_input_tokens": []}
    assert sut.generation_usable(report)
    assert not sut.generation_usable({**report, **replacement})


def test_old_codec_still_rejects_unknown_input():
    report = {"status": "generated", "ended": True, "tokens": ["newword"],
              "input_oov_tokens": ["newword"], "input_coverage_complete": True,
              "uncovered_input_tokens": []}
    assert not roundtrip._generation_usable(report)


@pytest.mark.parametrize("instruction", ["", "word " * 49, "x" * 4097])
def test_input_scope_keeps_original_source_binding(instruction):
    report = sut.prepare_copy_intent_instruction(instruction)
    assert report["status"] == "fail_open_input_out_of_scope"
    assert report["instruction_sha256"] == sut._sha(instruction.encode())
    assert report["raw_instruction_preserved"] and report["continue_planning"]
    assert report["candidate_intent_ir"] is None


def test_real_training_keeps_test_vocabulary_out_and_records_weights(checkpoint):
    descriptor, receipt, _ = checkpoint
    loaded = sut.load_intent_copy_checkpoint(descriptor)
    assert "nebularwidget" not in loaded["backend"]["config"]["vocabulary"]
    assert receipt["test_used_for_training_or_tuning"] is False
    evidence = receipt["shared_training"]
    assert evidence["optimizer_steps"] > 0 and evidence["native_kernel_calls"] > 0
    assert evidence["initial_state_sha256"] != evidence["final_state_sha256"]


def test_inverse_receives_only_predicted_native_frame(checkpoint, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_paired_copy as backend
    descriptor, _, rows = checkpoint
    calls, original = [], backend.infer_paired_copy
    def traced(selected, source, direction, *args, **kwargs):
        calls.append((source, direction))
        return original(selected, source, direction, *args, **kwargs)
    monkeypatch.setattr(backend, "infer_paired_copy", traced)
    instruction = rows[0]["instruction"]
    report = sut.prepare_copy_intent_instruction(instruction, descriptor)
    assert report["status"] == "semantic_candidate_advice"
    assert calls == [(instruction, "encode"),
                     (roundtrip.frame_to_sequence(report["learned"]["frame"]), "decode")]
    assert report["learned"]["frame"] == rows[0]["frame"]
    assert report["extended_projections"] is not None
    assert report["provider_calls"] == report["download_calls"] == report["training_steps"] == 0
    assert all(report[k] is False for k in ("proof_authority", "execution_authority", "completion_authority"))
    sut.validate_copy_intent_report(report, instruction=instruction, checkpoint_descriptor=descriptor)


@pytest.mark.parametrize("mutation", ["authority", "frame", "input", "schema"])
def test_resigned_report_tampering_does_not_pass_numerical_replay(checkpoint, mutation):
    descriptor, _, rows = checkpoint
    instruction = rows[0]["instruction"]
    report = deepcopy(sut.prepare_copy_intent_instruction(instruction, descriptor))
    if mutation == "authority": report["proof_authority"] = True
    elif mutation == "frame": report["learned"]["frame"]["action"] = "delete"
    elif mutation == "input": report["instruction_sha256"] = "0" * 64
    else: report["schema"] = roundtrip.SCHEMA
    report.pop("report_sha256")
    sut._finish(report)
    with pytest.raises(ValueError):
        sut.validate_copy_intent_report(report, instruction=instruction, checkpoint_descriptor=descriptor)


def test_optional_projector_failure_retains_replayable_base(checkpoint, monkeypatch):
    from ipfs_datasets_py.logic.intent_ir.formalize import extended_projections
    descriptor, _, rows = checkpoint
    original = extended_projections.project_intent_families
    def fail(*args, **kwargs): raise RuntimeError("transient authored fixture")
    monkeypatch.setattr(extended_projections, "project_intent_families", fail)
    report = sut.prepare_copy_intent_instruction(rows[0]["instruction"], descriptor)
    assert report["status"] == "semantic_candidate_advice"
    assert report["extension_status"] == "fail_open_projection_error"
    monkeypatch.setattr(extended_projections, "project_intent_families", original)
    sut.validate_copy_intent_report(report, instruction=rows[0]["instruction"], checkpoint_descriptor=descriptor)


@pytest.mark.parametrize("value", ["../candidate.json", "/tmp/model.json", "model/../candidate.json", ""])
def test_manifest_cannot_escape_package(checkpoint, tmp_path, value):
    descriptor, _, _ = checkpoint
    manifest = json.loads(Path(descriptor["path"]).read_bytes())
    manifest["backend"]["file"] = value
    path = tmp_path / "manifest.json"
    path.write_bytes(sut._raw(manifest))
    with pytest.raises(ValueError):
        sut.load_intent_copy_checkpoint({"schema": sut.CHECKPOINT_SCHEMA, "path": str(path),
                                        "sha256": sut._sha(path.read_bytes())})


def test_bad_checkpoint_fails_open_and_old_loader_rejects_new_schema(checkpoint):
    descriptor, _, rows = checkpoint
    with pytest.raises(ValueError): roundtrip.load_intent_roundtrip_checkpoint(descriptor)
    report = sut.prepare_copy_intent_instruction(rows[0]["instruction"], {**descriptor, "sha256": "0" * 64})
    assert report["status"] == "fail_open_checkpoint_or_decode_error"
    assert report["candidate_intent_ir"] is report["projections"] is None
    assert report["continue_planning"] and report["raw_instruction_preserved"]
