"""Full tensor inheritance, train-only vocabulary growth and real inference."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_paired_copy as base
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_paired_copy_continuation as child


def _examples():
    rows = []
    for actor in ("agent", "user"):
        for action in ("inspect", "update"):
            for obj in ("cache", "registry"):
                key = actor + action + obj
                instruction = f"{actor} must {action} {obj} ."
                wire = f"<actor> {actor} <action> {action} <object> {obj} <modality> required"
                rows.extend(({"id": "e:" + key, "source": instruction, "target": wire, "direction": "encode"},
                             {"id": "d:" + key, "source": wire, "target": instruction, "direction": "decode"}))
    tune = [{"id": "tune", "source": "agent inspect unseencomet .",
             "target": "unseentargetplanet", "direction": "encode"}]
    return rows, tune


@pytest.fixture(scope="module")
def parent(tmp_path_factory):
    import torch
    torch.set_num_threads(1)
    root = tmp_path_factory.mktemp("continuation-parent")
    train, tuning = _examples()
    return base.train_paired_copy(train, tuning, output_dir=root / "parent", epochs=100,
        max_seconds=45, hidden_size=32, embedding_dim=24)


@pytest.fixture(scope="module")
def checkpoint(parent, tmp_path_factory):
    root = tmp_path_factory.mktemp("continuation-child")
    train, tuning = _examples()
    before = Path(parent["path"]).read_bytes()
    descriptor = child.train_paired_copy_continuation(train, tuning, parent_descriptor=parent,
        output_dir=root / "child", epochs=5, max_seconds=30, copy_dropout=0.20)
    assert Path(parent["path"]).read_bytes() == before
    return descriptor


def test_real_full_weight_continuation_initial_state_matches_parent(parent, checkpoint):
    prior, current = base.load_paired_copy(parent), child.load_paired_copy_continuation(checkpoint)
    training = current["training"]
    assert training["initial_state_sha256"] == prior["training"]["final_state_sha256"]
    assert training["final_state_sha256"] != training["initial_state_sha256"]
    assert training["parent"]["artifact_sha256"] == parent["sha256"]
    assert training["optimizer_steps"] == 5 and training["native_kernel_calls"] == 15
    assert training["changed_tensors"] == training["trainable_parameters"]
    assert all(name in training["changed_tensors"] for name in
               ("encoder.weight_ih_l0", "decoder.weight_hh_l0", "copy_gate.weight", "embedding.weight", "output.weight"))
    assert training["lexical_lineage"] == prior["training"]["lexical_lineage"]
    assert current["model"].lexical.tolist() == prior["model"].lexical.tolist()
    assert training["tuning_used_for_fit_or_selection"] is False
    assert training["added_vocabulary"] == []
    assert "unseencomet" not in current["config"]["vocabulary"]
    assert "unseentargetplanet" not in current["config"]["vocabulary"]


def test_transfer_reindexes_every_parent_row_and_initializes_new_rows_from_unk(parent):
    import torch
    prior = base.load_paired_copy(parent)
    config = copy.deepcopy(prior["config"])
    config["vocabulary"] = list(base.SPECIAL) + sorted(config["vocabulary"][6:] + ["<if>", "CapitalLeaf"])
    model, state = child._transfer(torch, prior, config)
    old_positions = {token: i for i, token in enumerate(prior["config"]["vocabulary"])}
    for name, tensor in prior["model"].state_dict().items():
        if name in child._ROW_TENSORS:
            for i, token in enumerate(config["vocabulary"]):
                assert torch.equal(state[name][i], tensor[old_positions.get(token, 3)])
        else:
            assert torch.equal(state[name], tensor)
        assert torch.equal(model.state_dict()[name], state[name])


def test_training_grows_vocabulary_from_train_only_and_excludes_tuning_targets(parent, tmp_path):
    train, tuning = _examples()
    expanded = [{**row, "source": row["source"].replace("cache", "repository"),
                 "target": row["target"].replace("cache", "repository")} for row in train]
    descriptor = child.train_paired_copy_continuation(expanded, tuning, parent_descriptor=parent,
        output_dir=tmp_path / "expanded", epochs=1, max_seconds=10)
    result = child.load_paired_copy_continuation(descriptor)
    assert result["training"]["added_vocabulary"] == ["repository"]
    assert "cache" in result["config"]["vocabulary"]
    assert not {"unseencomet", "unseentargetplanet"} & set(result["config"]["vocabulary"])
    assert result["training"]["parent"]["weights_sha256"] == base.load_paired_copy(parent)["training"]["final_state_sha256"]


def test_tuning_target_changes_cannot_change_weights(parent, tmp_path):
    train, tuning = _examples()
    first = child.train_paired_copy_continuation(train, tuning, parent_descriptor=parent,
        output_dir=tmp_path / "first", epochs=2, max_seconds=10)
    other_tuning = [{**tuning[0], "target": "entirelydifferent forbiddenheldoutlabel"}]
    second = child.train_paired_copy_continuation(train, other_tuning, parent_descriptor=parent,
        output_dir=tmp_path / "second", epochs=2, max_seconds=10)
    a, b = child.load_paired_copy_continuation(first), child.load_paired_copy_continuation(second)
    assert a["training"]["final_state_sha256"] == b["training"]["final_state_sha256"]
    assert a["config"] == b["config"]


def test_child_loads_standalone_after_parent_removed(parent, tmp_path):
    copied_parent = tmp_path / "parent.json"
    copied_parent.write_bytes(Path(parent["path"]).read_bytes())
    train, tuning = _examples()
    descriptor = child.train_paired_copy_continuation(train, tuning,
        parent_descriptor={**parent, "path": str(copied_parent)}, output_dir=tmp_path / "child", epochs=1)
    copied_parent.unlink()
    assert child.load_paired_copy_continuation(descriptor)["training"]["parent"]["artifact_sha256"] == parent["sha256"]
    assert child.infer_paired_copy_continuation(descriptor, "agent must inspect cache .", "encode")["status"] == "generated"


def test_child_can_be_parent_without_losing_original_lexical_lineage(checkpoint, tmp_path):
    train, tuning = _examples()
    descriptor = child.train_paired_copy_continuation(train, tuning, parent_descriptor=checkpoint,
        output_dir=tmp_path / "grandchild", epochs=1)
    result = child.load_paired_copy_continuation(descriptor)
    prior = child.load_paired_copy_continuation(checkpoint)
    assert result["training"]["initial_state_sha256"] == prior["training"]["final_state_sha256"]
    assert result["training"]["lexical_lineage"] == prior["training"]["lexical_lineage"]


def test_real_inference_and_beam_use_weights_and_ephemeral_source_copy(checkpoint):
    source = "agent must inspect ephemeralasteroid ."
    target = "<actor> agent <action> inspect <object> ephemeralasteroid <modality> required"
    result = child.infer_paired_copy_continuation(checkpoint, source, "encode")
    assert result["generated_text"] == target
    assert result["input_oov_tokens"] == ["ephemeralasteroid"]
    assert not result["target_access"] and not result["teacher_forcing"] and not result["training_executed"]
    beam = child.infer_paired_copy_continuation_beam(checkpoint, source, "encode", beam_width=3)
    assert beam["rows"][0]["generated_text"] == target
    assert beam["native_decoder_calls"] > 0
    assert beam == child.infer_paired_copy_continuation_beam(checkpoint, source, "encode", beam_width=3)
    assert [row["log_probability"] for row in beam["rows"]] == sorted(
        [row["log_probability"] for row in beam["rows"]], reverse=True)
    copied = [row for row in result["copy_trace"] if row["token"] == "ephemeralasteroid"]
    assert copied[0]["extended_copy_token"] and copied[0]["copy_probability"] > 0
    assert copied[0]["generator_probability"] == 0


@pytest.mark.parametrize("ablation", ["zero_output_head", "disable_copy"])
def test_ablations_change_inference_without_writing_checkpoint(checkpoint, ablation):
    before = Path(checkpoint["path"]).read_bytes()
    source = "agent must inspect ephemeralasteroid ."
    ordinary = child.infer_paired_copy_continuation(checkpoint, source, "encode")
    changed = child.infer_paired_copy_continuation(checkpoint, source, "encode", weight_ablation=ablation)
    assert ordinary["tokens"] != changed["tokens"]
    beam = child.infer_paired_copy_continuation_beam(checkpoint, source, "encode", beam_width=2, weight_ablation=ablation)
    assert beam["weight_ablation"] == ablation
    if ablation == "disable_copy":
        assert all("ephemeralasteroid" not in row["tokens"] for row in beam["rows"])
    assert Path(checkpoint["path"]).read_bytes() == before


@pytest.mark.parametrize("change", [
    lambda p: p["config"]["implementation"].update(continuation_backend_sha256="b" * 64),
    lambda p: p["training"].update(parent_modified=True),
    lambda p: p["training"].update(initial_state_sha256="a" * 64),
    lambda p: p["training"].update(added_vocabulary=["nottrained"]),
    lambda p: p["training"].update(tuning_used_for_fit_or_selection=True),
    lambda p: p["training"].update(new_parameters_initialization="random"),
    lambda p: p["training"].update(trainable_parameters=["output.weight"]),
    lambda p: p["training"]["parent"].update(artifact_sha256="bad"),
    lambda p: p["weights"]["copy_gate.bias"].append(0),
    lambda p: p.update(proof_authority=True),
])
def test_rehashed_contract_tampering_is_rejected(checkpoint, tmp_path, change):
    package = base._json(Path(checkpoint["path"]).read_bytes())
    change(package)
    raw = base._raw(package)
    destination = tmp_path / "changed.json"
    destination.write_bytes(raw)
    with pytest.raises(ValueError):
        child.load_paired_copy_continuation({**checkpoint, "path": str(destination), "sha256": base._sha(raw)})


@pytest.mark.parametrize("setting,value", [("epochs", True), ("epochs", 0), ("copy_dropout", True),
    ("copy_dropout", -0.1), ("max_seconds", float("nan")), ("learning_rate", 0), ("learning_rate", True)])
def test_invalid_settings_reject_before_creating_output(parent, tmp_path, setting, value):
    train, tuning = _examples()
    with pytest.raises(ValueError):
        child.train_paired_copy_continuation(train, tuning, parent_descriptor=parent,
            output_dir=tmp_path / "child", **{setting: value})
    assert not (tmp_path / "child").exists()


def test_existing_output_overlap_and_wrong_parent_are_rejected(parent, tmp_path):
    train, tuning = _examples()
    for kwargs in ({"output_dir": tmp_path},
                   {"parent_descriptor": {"schema": "not-a-shared-checkpoint"}}):
        with pytest.raises(ValueError):
            child.train_paired_copy_continuation(train, tuning,
                **{**{"parent_descriptor": parent, "output_dir": tmp_path / "child"}, **kwargs}, epochs=1)
    with pytest.raises(ValueError, match="source overlap"):
        child.train_paired_copy_continuation(train, [{**train[0], "id": "different"}],
            parent_descriptor=parent, output_dir=tmp_path / "child", epochs=1)


@pytest.mark.parametrize("beam_width", [0, 17, True])
def test_beam_bound_rejects_before_loading(beam_width):
    with pytest.raises(ValueError, match="beam width"):
        child.infer_paired_copy_continuation_beam({}, "input", "encode", beam_width=beam_width)
