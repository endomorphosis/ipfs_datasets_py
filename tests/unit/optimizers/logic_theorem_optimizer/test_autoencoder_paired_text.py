"""Real CPU training, weight consumption and closed checkpoint regressions."""
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_paired_text as paired


def examples():
    rows = []
    for index, (actor, action) in enumerate((("agent", "inspect"), ("agent", "update"),
                                            ("user", "inspect"), ("user", "update"))):
        source = f"{actor} must {action} cache ."
        target = f"<actor> {actor} <action> {action} <object> cache <modality> required"
        rows.extend(({"id": f"e{index}", "source": source, "target": target, "direction": "encode"},
                     {"id": f"d{index}", "source": target, "target": source, "direction": "decode"}))
    tuning = [{"id": "tune", "source": "agent inspect cache .", "target": rows[0]["target"], "direction": "encode"}]
    return rows, tuning


@pytest.fixture(scope="module")
def checkpoint(tmp_path_factory):
    import torch
    torch.set_num_threads(1)
    root = tmp_path_factory.mktemp("paired-model")
    source = root / "initializer.json"
    source.write_text(json.dumps({"keys": ["token:agent", "token:cache", "token:inspect", "token:update", "token:user"],
        "weights": [[0.02 * (index + 1), 0.03] for index in range(5)], "embedding_width": 2,
        "source_checkpoint_sha256": "a" * 64}))
    before = source.read_bytes()
    train, tuning = examples()
    descriptor = paired.train_paired_text(train, tuning, output_dir=root / "model",
        lexical_initializer_path=source, epochs=100, max_seconds=30, hidden_size=24, embedding_dim=16)
    assert source.read_bytes() == before
    return descriptor


def test_real_bidirectional_training_and_frozen_lexical_inference(checkpoint):
    loaded = paired.load_paired_text(checkpoint)
    training = loaded["training"]
    assert training["optimizer_steps"] > 0
    assert training["native_kernel_calls"] >= 3 * training["optimizer_steps"]
    assert training["initial_state_sha256"] != training["final_state_sha256"]
    assert training["training_loss"][-1] < training["training_loss"][0]
    assert training["lexical_lineage"]["matched_tokens"] == 5
    assert training["lexical_lineage"]["frozen"] is True
    train, _ = examples()
    report = paired.evaluate_paired_text(checkpoint, train)
    assert report["exact_token_rate"] == 1
    assert report["teacher_forcing"] is False
    assert report["semantic_correctness_verified"] is False


def test_actual_heads_change_free_running_output(checkpoint):
    train, _ = examples()
    before = Path(checkpoint["path"]).read_bytes()
    normal = paired.infer_paired_text(checkpoint, train[0]["source"], "encode")
    ablated = paired.infer_paired_text(checkpoint, train[0]["source"], "encode", weight_ablation="zero_output_head")
    assert normal["status"] == "generated"
    assert normal["tokens"] != ablated["tokens"]
    assert ablated["status"] == "invalid_or_incomplete_output"
    assert normal["target_access"] is False
    assert normal["training_executed"] is False
    assert Path(checkpoint["path"]).read_bytes() == before


def test_oov_is_visible_and_no_external_calls(checkpoint):
    result = paired.infer_paired_text(checkpoint, "agent must inspect supernovax .", "encode")
    assert result["input_oov_tokens"] == ["supernovax"]
    assert result["download_calls"] == result["provider_calls"] == 0


def test_tampered_checkpoint_rejected(checkpoint, tmp_path):
    copy = tmp_path / "copy.json"
    copy.write_bytes(Path(checkpoint["path"]).read_bytes() + b" ")
    selected = {**checkpoint, "path": str(copy)}
    with pytest.raises(ValueError, match="hash differs"):
        paired.load_paired_text(selected)


@pytest.mark.parametrize("field,value", [("direction", "bogus"), ("source", "<encode> agent"),
                                        ("target", ""), ("id", "")])
def test_invalid_pairs_rejected_before_output(tmp_path, field, value):
    train, tuning = examples()
    train[0][field] = value
    with pytest.raises(ValueError):
        paired.train_paired_text(train, tuning, output_dir=tmp_path / "model", epochs=1)
    assert not (tmp_path / "model").exists()


def test_split_overlap_and_duplicate_ids_rejected(tmp_path):
    train, tuning = examples()
    tuning[0] = {**train[0], "id": "disjoint-id"}
    with pytest.raises(ValueError, match="source overlap"):
        paired.train_paired_text(train, tuning, output_dir=tmp_path / "model", epochs=1)
    train, tuning = examples()
    train[1]["id"] = train[0]["id"]
    with pytest.raises(ValueError, match="unique"):
        paired.train_paired_text(train, tuning, output_dir=tmp_path / "model", epochs=1)


def test_vocabulary_uses_training_only(checkpoint):
    config = paired.load_paired_text(checkpoint)["config"]
    assert config["vocabulary"][:6] == list(paired.SPECIAL)
    assert "supernovax" not in config["vocabulary"]


def test_conflicting_source_labels_rejected(tmp_path):
    train, tuning = examples()
    train.append({**train[0], "id": "conflict", "target": "different meaning"})
    with pytest.raises(ValueError, match="conflicting"):
        paired.train_paired_text(train, tuning, output_dir=tmp_path / "model", epochs=1)


def test_repinned_producer_and_tensor_tampering_rejected(checkpoint, tmp_path):
    package = json.loads(Path(checkpoint["path"]).read_bytes())
    package["config"]["implementation"]["backend_sha256"] = "b" * 64
    candidate = tmp_path / "changed.json"
    candidate.write_bytes(paired._raw(package))
    changed = {**checkpoint, "path": str(candidate), "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest()}
    with pytest.raises(ValueError, match="implementation"):
        paired.load_paired_text(changed)
    package = json.loads(Path(checkpoint["path"]).read_bytes())
    package["weights"]["output.bias"][0] = True
    candidate.write_bytes(paired._raw(package))
    changed["sha256"] = hashlib.sha256(candidate.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="nonfinite"):
        paired.load_paired_text(changed)


def test_authority_and_length_bounds(checkpoint):
    with pytest.raises(ValueError, match="closed"):
        paired.load_paired_text({**checkpoint, "proof_authority": True})
    with pytest.raises(ValueError, match="bounded decoder"):
        paired.infer_paired_text(checkpoint, "agent inspect cache", "encode", max_new_tokens=True)
    with pytest.raises(ValueError, match="unknown paired weight"):
        paired.infer_paired_text(checkpoint, "agent inspect cache", "encode", weight_ablation="train")
