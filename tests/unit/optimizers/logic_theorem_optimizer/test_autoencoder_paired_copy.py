"""Actual shared CPU learning, ephemeral copying, and closed artifact checks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_paired_copy as copy


def examples():
    rows = []
    for actor in ("agent", "user"):
        for action in ("inspect", "update"):
            for obj in ("cache", "registry"):
                key = actor + action + obj
                instruction = f"{actor} must {action} {obj} ."
                wire = f"<actor> {actor} <action> {action} <object> {obj} <modality> required"
                rows.extend(({"id": "e:" + key, "source": instruction, "target": wire, "direction": "encode"},
                             {"id": "d:" + key, "source": wire, "target": instruction, "direction": "decode"}))
    tune = [{"id": "tune", "source": "agent inspect cache .", "target": rows[0]["target"], "direction": "encode"}]
    return rows, tune


@pytest.fixture(scope="module")
def checkpoint(tmp_path_factory):
    import torch
    torch.set_num_threads(1)
    root = tmp_path_factory.mktemp("copy-model")
    initializer = root / "initializer.json"
    initializer.write_text(json.dumps({"keys": ["token:agent", "token:cache", "token:inspect", "token:update", "token:user"],
        "weights": [[0.02 * (index + 1), 0.03] for index in range(5)], "embedding_width": 2,
        "source_checkpoint_sha256": "a" * 64}))
    before = initializer.read_bytes()
    train, tune = examples()
    descriptor = copy.train_paired_copy(train, tune, output_dir=root / "model", lexical_initializer_path=initializer,
        epochs=100, max_seconds=45, hidden_size=32, embedding_dim=24)
    assert initializer.read_bytes() == before
    return descriptor


def test_real_copy_training_uses_both_directions_and_shared_kernel(checkpoint):
    loaded = copy.load_paired_copy(checkpoint)
    training = loaded["training"]
    assert training["optimizer_steps"] == 100
    assert training["native_kernel_calls"] == 300
    assert training["initial_state_sha256"] != training["final_state_sha256"]
    assert training["training_loss"][-1] < training["training_loss"][0]
    assert all(count > 0 for count in training["copy_masked_types_by_direction"].values())
    assert training["copy_dropout_scope"] == "training_only"
    assert training["lexical_lineage"]["matched_tokens"] == 5
    assert loaded["config"]["copy_dropout"] == 0.20
    assert training["tuning_used_for_fit_or_selection"] is False
    train, _ = examples()
    result = copy.evaluate_paired_copy(checkpoint, train)
    assert result["exact_token_rate"] == 1.0


@pytest.mark.parametrize("nonce", ["quasarwidget", "nebulaflux"])
def test_actual_unseen_source_copied_in_both_directions(checkpoint, nonce):
    loaded = copy.load_paired_copy(checkpoint)
    assert nonce not in loaded["config"]["vocabulary"]
    instruction = f"agent must inspect {nonce} ."
    wire = f"<actor> agent <action> inspect <object> {nonce} <modality> required"
    for source, target, direction in ((instruction, wire, "encode"), (wire, instruction, "decode")):
        result = copy.infer_paired_copy(checkpoint, source, direction)
        assert result["status"] == "generated"
        assert result["generated_text"] == target
        assert result["input_oov_tokens"] == [nonce]
        assert result["uncovered_input_tokens"] == [] and result["input_coverage_complete"] is True
        trace = [row for row in result["copy_trace"] if row["token"] == nonce]
        assert len(trace) == 1 and trace[0]["extended_copy_token"] is True
        assert trace[0]["generator_probability"] == 0 and trace[0]["copy_probability"] > 0
        assert [copy.tokenize(source)[i] for i in trace[0]["copy_source_positions"]] == [nonce]
        assert result["teacher_forcing"] is result["target_access"] is result["training_executed"] is False
        assert result["download_calls"] == result["provider_calls"] == 0


def test_additive_beam_search_consumes_same_weights_and_source_local_copy(checkpoint):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_paired_search import infer_paired_copy_beam
    before = Path(checkpoint["path"]).read_bytes()
    source = "agent must inspect unseenasteroid ."
    result = infer_paired_copy_beam(checkpoint, source, "encode", beam_width=4)
    greedy = copy.infer_paired_copy(checkpoint, source, "encode")
    assert result["rows"][0]["generated_text"] == greedy["generated_text"]
    assert result["checkpoint_weights_sha256"] == greedy["checkpoint_weights_sha256"]
    assert result["native_decoder_calls"] > 0
    scores = [row["log_probability"] for row in result["rows"]]
    assert scores == sorted(scores, reverse=True)
    first = result["rows"][0]
    assert first["input_oov_tokens"] == ["unseenasteroid"]
    assert any(t["token"] == "unseenasteroid" and t["extended_copy_token"] and t["copy_probability"] > 0
               for t in first["copy_trace"])
    assert not result["target_access"] and not result["teacher_forcing"]
    assert not result["training_executed"]
    assert Path(checkpoint["path"]).read_bytes() == before
    assert infer_paired_copy_beam(checkpoint, source, "encode", beam_width=4) == result


def test_beam_search_ablation_changes_learned_output_without_modifying_package(checkpoint):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_paired_search import infer_paired_copy_beam
    before = Path(checkpoint["path"]).read_bytes()
    source = "agent must inspect unseenasteroid ."
    ordinary = infer_paired_copy_beam(checkpoint, source, "encode", beam_width=2)
    ablated = infer_paired_copy_beam(checkpoint, source, "encode", beam_width=2,
                                    weight_ablation="disable_copy")
    assert ordinary["rows"]
    assert [r["generated_text"] for r in ordinary["rows"]] != [r["generated_text"] for r in ablated["rows"]]
    assert all("unseenasteroid" not in r["tokens"] for r in ablated["rows"])
    assert all(r["input_coverage_complete"] is False for r in ablated["rows"])
    assert Path(checkpoint["path"]).read_bytes() == before


@pytest.mark.parametrize("beam_width", [0, 17, True, 1.5])
def test_beam_bounds_are_checked_before_checkpoint_loading(beam_width):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_paired_search import infer_paired_copy_beam
    with pytest.raises(ValueError, match="beam width"):
        infer_paired_copy_beam({}, "agent must inspect cache", "encode", beam_width=beam_width)


def test_ablations_change_copies_and_generator_without_mutating_checkpoint(checkpoint):
    before = Path(checkpoint["path"]).read_bytes()
    source = "agent must inspect quasarwidget ."
    normal = copy.infer_paired_copy(checkpoint, source, "encode")
    disabled = copy.infer_paired_copy(checkpoint, source, "encode", weight_ablation="disable_copy")
    zeroed = copy.infer_paired_copy(checkpoint, source, "encode", weight_ablation="zero_output_head")
    assert normal["tokens"] != disabled["tokens"] and "quasarwidget" not in disabled["tokens"]
    assert disabled["uncovered_input_tokens"] == ["quasarwidget"]
    assert disabled["input_coverage_complete"] is False
    assert all(row["copy_probability"] == 0 for row in disabled["copy_trace"])
    assert normal["tokens"] != zeroed["tokens"]
    assert Path(checkpoint["path"]).read_bytes() == before


def test_expected_only_unknown_tokens_are_unreachable(checkpoint):
    row = {"id": "target-only", "source": "agent must inspect cache .", "target": "untouchedasteroid", "direction": "encode"}
    result = copy.evaluate_paired_copy(checkpoint, [row])["rows"][0]
    assert result["uncovered_target_tokens"] == ["untouchedasteroid"]
    assert "untouchedasteroid" not in result["tokens"]
    assert result["exact_tokens"] is False


def test_copy_scatter_sums_repeated_tokens_and_masks_direction(checkpoint):
    import torch
    loaded = copy.load_paired_copy(checkpoint)
    config, model = loaded["config"], loaded["model"]
    tokens = copy.tokenize("quasarwidget quasarwidget")
    source, copied, extended, _ = copy._source_ids(tokens, config["vocabulary"], "encode")
    assert extended == ["quasarwidget"] and copied[1] == copied[2]
    ids = torch.tensor([source]); copy_ids = torch.tensor([copied]); mask = torch.tensor([[False, True, True]])
    encoded, hidden = model.encode(ids, torch.tensor([len(source)]))
    probabilities, _, generated, pointer, attention, gate = model.decode(
        torch.tensor([[1]]), hidden, encoded, mask, copy_ids, len(config["vocabulary"]) + 1)
    assert torch.allclose(probabilities.sum(-1), torch.ones_like(gate.squeeze(-1)))
    assert float(attention[0, 0, 0]) == 0
    assert float(pointer[0, 0, 0]) == 0
    assert torch.allclose(pointer[0, 0, copied[1]], (1 - gate[0, 0, 0]))
    assert float(generated[0, 0, copied[1]]) == 0


def test_pointer_and_generator_have_actual_gradients_with_frozen_lexical(checkpoint):
    import torch
    loaded = copy.load_paired_copy(checkpoint)
    model = loaded["model"]
    train, _ = examples()
    batch = copy._batch(torch, copy.legacy._pairs(train), loaded["config"]["vocabulary"],
                        generator=torch.Generator().manual_seed(33), dropout=0.75)
    loss, calls, count = copy._loss(torch, model, batch)
    loss.backward()
    assert calls == 3 and count > 0 and bool(torch.isfinite(loss))
    for parameter in (model.output.weight, model.copy_gate.weight, model.encoder.weight_ih_l0):
        assert parameter.grad is not None
        assert bool(torch.isfinite(parameter.grad).all()) and float(parameter.grad.abs().sum()) > 0
    assert model.lexical.requires_grad is False and model.lexical.grad is None


@pytest.mark.parametrize("source", ["", "   ", "<pad>", "<bos>", "<eos>", "<unk>", "<encode>", "<decode>", "a " * 192])
def test_empty_reserved_and_out_of_bounds_input_rejected(checkpoint, source):
    with pytest.raises(ValueError):
        copy.infer_paired_copy(checkpoint, source, "encode")


@pytest.mark.parametrize("maximum", [0, 193, True, 1.5])
def test_output_bounds_rejected(checkpoint, maximum):
    with pytest.raises(ValueError, match="bounded decoder"):
        copy.infer_paired_copy(checkpoint, "agent inspect cache", "encode", maximum)


def test_output_bound_and_input_local_vocabulary(checkpoint):
    source = " ".join("nonceword" + str(i) for i in range(180))
    result = copy.infer_paired_copy(checkpoint, source, "encode", max_new_tokens=2)
    assert len(result["tokens"]) <= 2 and len(result["copy_trace"]) == len(result["tokens"])
    assert len(result["input_oov_tokens"]) == 180
    loaded = copy.load_paired_copy(checkpoint)
    assert not set(result["input_oov_tokens"]) & set(loaded["config"]["vocabulary"])
    assert result["input_coverage_complete"] is True


def _changed(checkpoint, tmp_path, mutation):
    package = json.loads(Path(checkpoint["path"]).read_bytes())
    mutation(package)
    path = tmp_path / "changed.json"
    path.write_bytes(copy._raw(package))
    return {**checkpoint, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.mark.parametrize("mutation", [
    lambda p: p["config"]["implementation"].update(copy_backend_sha256="b" * 64),
    lambda p: p["config"].update(copy_dropout=True),
    lambda p: p["config"].update(copy_vocabulary_scope="training_memory"),
    lambda p: p["weights"]["copy_gate.bias"].__setitem__(0, True),
    lambda p: p["weights"]["copy_gate.bias"].append(0),
    lambda p: p["training"].update(tuning_used_for_fit_or_selection=True),
    lambda p: p["training"].update(copy_dropout_scope="all_splits"),
    lambda p: p["training"].update(copy_masked_types_by_direction={"encode": -1, "decode": 5}),
    lambda p: p.update(proof_authority=True),
])
def test_rehashed_contract_and_tensor_tampering_rejected(checkpoint, tmp_path, mutation):
    changed = _changed(checkpoint, tmp_path, mutation)
    with pytest.raises(ValueError):
        copy.load_paired_copy(changed)


def test_nonfinite_json_rejected(checkpoint, tmp_path):
    package = json.loads(Path(checkpoint["path"]).read_bytes())
    package["weights"]["copy_gate.bias"][0] = float("nan")
    path = tmp_path / "nonfinite.json"
    path.write_text(json.dumps(package))
    with pytest.raises(ValueError, match="nonfinite"):
        copy.load_paired_copy({**checkpoint, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})


def test_hash_unknown_fields_symlinks_and_ablation_rejected(checkpoint, tmp_path):
    with pytest.raises(ValueError, match="hash differs"):
        copy.load_paired_copy({**checkpoint, "sha256": "a" * 64})
    with pytest.raises(ValueError, match="closed"):
        copy.load_paired_copy({**checkpoint, "authority": True})
    link = tmp_path / "linked.json"
    link.symlink_to(checkpoint["path"])
    with pytest.raises(ValueError, match="canonical"):
        copy.load_paired_copy({**checkpoint, "path": str(link)})
    with pytest.raises(ValueError, match="unknown"):
        copy.infer_paired_copy(checkpoint, "agent inspect cache", "encode", weight_ablation="lookup")


@pytest.mark.parametrize("setting,value", [("copy_dropout", True), ("copy_dropout", -0.1),
                                          ("copy_dropout", 0.76), ("copy_dropout", float("nan")),
                                          ("epochs", True), ("hidden_size", 7)])
def test_invalid_training_configuration_has_no_output(tmp_path, setting, value):
    train, tune = examples()
    with pytest.raises(ValueError):
        copy.train_paired_copy(train, tune, output_dir=tmp_path / "model", **{setting: value})
    assert not (tmp_path / "model").exists()


def test_training_overlap_conflicts_and_identity_aliases_rejected(tmp_path):
    train, tune = examples()
    tune = [{**train[0], "id": "fresh", "source": train[0]["source"].replace(" .", ".")}]
    with pytest.raises(ValueError, match="source overlap"):
        copy.train_paired_copy(train, tune, output_dir=tmp_path / "model", epochs=1)
    train, tune = examples()
    train.append({**train[0], "id": "conflict", "target": "a contradictory target"})
    with pytest.raises(ValueError, match="conflicting"):
        copy.train_paired_copy(train, tune, output_dir=tmp_path / "model", epochs=1)
    assert not (tmp_path / "model").exists()


def test_tokenizer_punctuation_aliases_and_source_strings_are_exact():
    tokens = copy.tokenize("case-sensitive case-sensitive.")
    vocabulary = list(copy.SPECIAL) + ["."]
    source, copied, extra, _ = copy._source_ids(tokens, vocabulary, "encode")
    assert tokens == ["case", "-", "sensitive", "case", "-", "sensitive", "."]
    assert extra == ["case", "-", "sensitive"]
    assert copied[1:4] == copied[4:7]
    assert copy.tokenize("case - sensitive .") == copy.tokenize("case-sensitive.")
    assert source[1:7] == [3] * 6
