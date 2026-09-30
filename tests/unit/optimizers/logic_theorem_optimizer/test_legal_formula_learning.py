"""Actual source-only sequence learning, integrity, and numerical resume tests."""
import copy
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

torch = pytest.importorskip("torch")
PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if os.environ.get("LEGAL_FORMULA_STAGING"):
    directory = Path(os.environ["LEGAL_FORMULA_STAGING"])
    codec = _load(directory / "legal_formula_codec.py", PREFIX + ".legal_formula_codec")
    learning = _load(directory / "legal_formula_learning.py", PREFIX + ".legal_formula_learning")
else:
    codec = importlib.import_module(PREFIX + ".legal_formula_codec")
    learning = importlib.import_module(PREFIX + ".legal_formula_learning")


def _row(identifier, text, modality="O", actor="agency", action="disclose", obj="records"):
    return {"id": identifier, "source_text": text, "canonical_ir": {"rules": [{
        "modality": modality, "actor": actor, "action": action, "object": obj,
        "conditions": [], "exceptions": [], "temporal": []}]}}


def _examples():
    return [_row("obligation", "The agency shall disclose records."),
            _row("prohibition", "The agency shall not disclose records.", "F")]


SETTINGS = {"max_seconds": 60, "learning_rate": 0.02, "batch_size": 2,
            "seed": 1729, "hidden_size": 16, "embedding_dim": 8}


@pytest.fixture(scope="module")
def trained():
    return learning.train_decoder(_examples(), [], epochs=100, **SETTINGS)


def test_token_loss_backprop_updates_output_head_and_reconstructs_source_minimal_pair(trained):
    report = trained["report"]
    assert report["training_after"]["token_cross_entropy"] < report["training_before"]["token_cross_entropy"] / 10
    assert report["output_head_gradient_norm_max"] > 0
    assert report["initial_output_head_sha256"] != report["final_output_head_sha256"]
    result = learning.LearnedLegalFormulaDecoder(trained["checkpoint"]).decode_formal_logic(
        [row["source_text"] for row in _examples()])
    assert [row["canonical_ir"] for row in result["rows"]] == [row["canonical_ir"] for row in _examples()]
    assert all(row["formula_text"] for row in result["rows"])
    assert not result["target_access"] and not result["training_executed"]
    assert all(result[key] is False for key in learning.FALSE)


def test_inference_never_calls_source_compiler_target_encoder_or_training(trained, monkeypatch):
    def prohibited(*args, **kwargs):
        raise AssertionError("inference accessed training/target codec")
    decoder = learning.LearnedLegalFormulaDecoder(trained["checkpoint"])
    before = copy.deepcopy(decoder.model.state_dict())
    monkeypatch.setattr(codec, "encode_target", prohibited)
    monkeypatch.setattr(learning, "train_decoder", prohibited)
    for _ in range(2):
        result = decoder.decode_formal_logic([_examples()[0]["source_text"]])
        assert result["status"] == "decoded"
    assert all(torch.equal(value, before[name]) for name, value in decoder.model.state_dict().items())


def test_zero_output_head_and_unknown_source_abstain_without_target_fallback(trained):
    zero = copy.deepcopy(trained["checkpoint"])
    for name in ("output.weight", "output.bias"):
        zero["model_state"][name] = torch.zeros_like(torch.tensor(zero["model_state"][name])).tolist()
    result = learning.decode_formula(zero, _examples()[0]["source_text"])
    assert result["status"] == "abstained" and result["reason"] == "zero_output_head"
    assert result["canonical_ir"] is None and result["formal_outputs"] == []
    missing = learning.decode_formula(trained["checkpoint"], "A spacecraft shall orbit Mars.")
    assert missing["status"] == "abstained" and "out-of-vocabulary" in missing["detail"]


def test_checkpoint_roundtrip_hash_binding_and_exclusive_write(trained, tmp_path):
    checkpoint = trained["checkpoint"]
    path = tmp_path / "weights.json"
    descriptor = learning.save_checkpoint(checkpoint, path)
    assert descriptor["sha256"] == learning.checkpoint_digest(checkpoint)
    assert learning.load_checkpoint(path, expected_sha256=descriptor["sha256"]) == checkpoint
    with pytest.raises(FileExistsError):
        learning.save_checkpoint(checkpoint, path)
    with pytest.raises(ValueError, match="hash differs"):
        learning.load_checkpoint(path, expected_sha256="0" * 64)
    assert "source_text" not in json.dumps(checkpoint)


def test_adam_moments_and_weights_resume_exactly_at_epoch_boundary():
    whole = learning.train_decoder(_examples(), [], epochs=4, **SETTINGS)["checkpoint"]
    first = learning.train_decoder(_examples(), [], epochs=2, **SETTINGS)["checkpoint"]
    original = copy.deepcopy(first)
    second = learning.train_decoder(_examples(), [], epochs=2, checkpoint=first, **SETTINGS)["checkpoint"]
    assert first == original
    assert second["parent_checkpoint_sha256"] == learning.checkpoint_digest(first)
    for field in ("model_state", "optimizer_state", "progress"):
        assert second[field] == whole[field]


def test_batch_boundary_deadline_and_partial_epoch_resume_are_exact(monkeypatch):
    examples = _examples() + [_row("officer", "The officer shall disclose records.", actor="officer")]
    original_loss = learning._loss
    clock = {"value": 0.0}
    def timed_loss(torch_module, model, records):
        result = original_loss(torch_module, model, records)
        if model.training:
            clock["value"] = 2.0
        return result
    with monkeypatch.context() as patch:
        patch.setattr(learning.time, "monotonic", lambda: clock["value"])
        patch.setattr(learning, "_loss", timed_loss)
        limited = learning.train_decoder(examples, [], epochs=2, **{**SETTINGS, "max_seconds": 1})
    assert limited["report"]["stopped_reason"] == "deadline_before_batch"
    assert limited["checkpoint"]["progress"] == {"epochs_completed": 0, "row_cursor": 2, "optimizer_steps": 1}
    resumed = learning.train_decoder(examples, [], epochs=2, checkpoint=limited["checkpoint"], **SETTINGS)["checkpoint"]
    whole = learning.train_decoder(examples, [], epochs=2, **SETTINGS)["checkpoint"]
    for field in ("model_state", "optimizer_state", "progress"):
        assert resumed[field] == whole[field]


def test_zero_budget_returns_valid_untrained_checkpoint_and_no_optimizer_step():
    result = learning.train_decoder(_examples(), [], epochs=1, **{**SETTINGS, "max_seconds": 0})
    learning.validate_checkpoint(result["checkpoint"])
    assert result["report"]["optimizer_steps"] == 0
    assert not result["report"]["training_executed"]
    assert result["checkpoint"]["optimizer_state"]["parameters"] == {}


def test_checkpoint_tamper_and_changed_resume_manifests_fail_closed(trained):
    checkpoint = trained["checkpoint"]
    tampered = copy.deepcopy(checkpoint)
    tampered["model_state"]["output.bias"][0] = float("nan")
    with pytest.raises(ValueError):
        learning.validate_checkpoint(tampered)
    wrong = copy.deepcopy(checkpoint)
    wrong["implementation"]["files"]["legal_formula_learning.py"] = "0" * 64
    with pytest.raises(ValueError, match="source drift"):
        learning.validate_checkpoint(wrong)
    different = _examples()
    different[0]["id"] = "changed-id"
    with pytest.raises(ValueError, match="manifests differ"):
        learning.train_decoder(different, [], epochs=1, checkpoint=checkpoint, **SETTINGS)
    negative = copy.deepcopy(checkpoint)
    negative["optimizer_state"]["parameters"]["output.bias"]["exp_avg_sq"][0] = -1
    with pytest.raises(ValueError, match="finite"):
        learning.validate_checkpoint(negative)


def test_training_tuning_split_rejects_token_identity_overlap():
    tuning = copy.deepcopy(_examples()[0])
    tuning["id"] = "new-id"
    tuning["source_text"] = "  THE agency SHALL disclose records. "
    with pytest.raises(ValueError, match="tokenized sources overlap"):
        learning.train_decoder(_examples(), [tuning], epochs=1, **SETTINGS)


def test_tied_nonzero_output_head_abstains(trained):
    checkpoint = copy.deepcopy(trained["checkpoint"])
    for name in ("output.weight", "output.bias"):
        checkpoint["model_state"][name] = torch.ones_like(torch.tensor(checkpoint["model_state"][name])).tolist()
    result = learning.decode_formula(checkpoint, _examples()[0]["source_text"])
    assert result["status"] == "abstained" and result["reason"] == "ambiguous_decoder_scores"


def test_runtime_source_drift_and_wrong_codec_tree_rejected(trained, monkeypatch):
    decoder = learning.LearnedLegalFormulaDecoder(trained["checkpoint"])
    changed = copy.deepcopy(learning._IMPLEMENTATION_AT_IMPORT)
    changed["files"]["legal_ir_grammar_decoder.py"] = "0" * 64
    with monkeypatch.context() as patch:
        patch.setattr(learning, "_capture_implementation", lambda: changed)
        with pytest.raises(ValueError, match="changed since decoder import"):
            decoder.decode_formal_logic([_examples()[0]["source_text"]])
    with monkeypatch.context() as patch:
        patch.setattr(codec, "__file__", "/tmp/drifted-tree/legal_formula_codec.py")
        with pytest.raises(ValueError, match="different runtime tree"):
            decoder.decode_formal_logic([_examples()[0]["source_text"]])


def test_unrepresentable_tuning_target_does_not_claim_complete_measurement():
    tuning = _row("new-source", "The agency shall disclose records records.", action="retire")
    result = learning.train_decoder(_examples(), [tuning], epochs=1, **SETTINGS)
    assert not result["report"]["tuning"]["complete"]
    assert result["report"]["tuning"]["rejected_rows"]
