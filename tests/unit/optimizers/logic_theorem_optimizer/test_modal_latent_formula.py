"""Real latent-to-formula learning, isolation, exact resume and fail-closed state."""
import copy
import hashlib
import json

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as learning


@pytest.fixture(autouse=True)
def allocated_cpu():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def binding(dimension=8):
    return {"domain": "legal_ir", "lineage_id": "legacy_hub_v1" if dimension == 8 else "current_legal_v2",
            "dimension": dimension, "runtime_profile": "test_authored_raw_core/v1", "core_sha256": "a" * 64}


def row(identifier, sign=1., dimension=8, *, source=None):
    latent = [sign] + [0.] * (dimension - 1)
    return {"id": identifier, "source_text": source or identifier + " authored source.", "latent": latent,
        "embedding": [.6 * item for item in latent], "canonical_ir": {"rules": [{
            "modality": "O" if sign > 0 else "F", "actor": "agency", "action": "disclose", "object": "records",
            "conditions": [], "exceptions": [], "temporal": []}]}}


OPTIONS = {"learning_rate": .03, "batch_size": 2, "seed": 1729, "hidden_size": 16,
           "token_embedding_dim": 8, "projection_width": 4}


def train_rows(dimension=8):
    return [row("obligation", dimension=dimension), row("prohibition", -1., dimension)]


def inference(rows):
    return [{key: row[key] for key in ("id", "source_text", "latent")} for row in rows]


@pytest.fixture(scope="module")
def trained():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    samples = train_rows()
    checkpoint = learning.build_checkpoint(binding(), samples, [], **OPTIONS)
    result = learning.train(checkpoint, samples, [], epochs=100, max_seconds=60)
    torch.set_num_threads(previous)
    return result


def test_joint_loss_reaches_projection_and_decoder_and_generates_actual_formulas(trained):
    report = trained["report"]
    assert report["training_after"]["token_cross_entropy"] < report["training_before"]["token_cross_entropy"] / 10
    assert report["training_after"]["reconstruction_mse"] < report["training_before"]["reconstruction_mse"]
    assert report["formula_projection_gradient_norm_max"] > 0
    for name in ("projection", "decoder"):
        evidence = report["parameter_evidence"][name]
        assert evidence["gradient_norm_max"] > 0 and evidence["parameter_update_l2"] > 0
        assert evidence["initial_parameters_sha256"] != evidence["final_parameters_sha256"]
    result = learning.infer(trained["checkpoint"], inference(train_rows()))
    assert [item["canonical_ir"] for item in result["rows"]] == [item["canonical_ir"] for item in train_rows()]
    assert all(item["formula_text"] for item in result["rows"])
    assert result["target_access"] is False and result["training_executed"] is False
    assert all(result[key] is False and report[key] is False for key in learning.FALSE)
    assert report["core_sparse_weights_frozen_for_formula_gradient"] is True


def test_inference_uses_latent_not_text_and_does_not_read_targets_or_train(trained, monkeypatch):
    decoder = learning.LatentFormulaDecoder(trained["checkpoint"], expected_binding=binding())
    before = {name: value.clone() for name, value in decoder.model.state_dict().items()}
    def forbidden(*args, **kwargs):
        raise AssertionError("inference attempted training or target access")
    monkeypatch.setattr(learning, "train", forbidden)
    monkeypatch.setattr(learning.codec_module, "encode_target", forbidden)
    monkeypatch.setattr(learning.codec_module, "encode_source", forbidden)
    inputs = inference(train_rows())
    result = decoder.infer(inputs)
    inputs[0]["source_text"] = "Unseen text does not enter the neural network."
    changed_text = decoder.infer(inputs)
    assert changed_text["rows"][0]["canonical_ir"] == result["rows"][0]["canonical_ir"]
    inputs[0]["latent"] = list(inputs[1]["latent"])
    changed_latent = decoder.infer(inputs)
    assert changed_latent["rows"][0]["canonical_ir"] == result["rows"][1]["canonical_ir"]
    assert all(torch.equal(value, before[name]) for name, value in decoder.model.state_dict().items())


@pytest.mark.parametrize("dimension", [8, 384])
def test_both_dimensions_have_separate_projection_and_real_formula_updates(dimension):
    samples = train_rows(dimension)
    checkpoint = learning.build_checkpoint(binding(dimension), samples, [], **OPTIONS)
    original = copy.deepcopy(checkpoint)
    result = learning.train(checkpoint, samples, [], epochs=2, max_seconds=60)
    assert checkpoint == original
    assert result["report"]["parameter_evidence"]["projection"]["parameter_update_l2"] > 0
    assert result["report"]["parameter_evidence"]["decoder"]["parameter_update_l2"] > 0
    assert result["report"]["formula_projection_gradient_norm_max"] > 0
    values = learning.project(result["checkpoint"], [samples[0]["latent"]], expected_binding=binding(dimension))
    assert len(values[0]) == dimension
    other = binding(384 if dimension == 8 else 8)
    with pytest.raises(ValueError, match="binding differs"):
        learning.validate_checkpoint(result["checkpoint"], expected_binding=other)


def test_epoch_and_partial_batch_resume_are_exact():
    samples = train_rows() + [row("third")]
    checkpoint = learning.build_checkpoint(binding(), samples, [], **OPTIONS)
    whole = learning.train(checkpoint, samples, [], epochs=4, max_seconds=60)["checkpoint"]
    first = learning.train(checkpoint, samples, [], epochs=2, max_seconds=60)["checkpoint"]
    resumed = learning.train(first, samples, [], epochs=2, max_seconds=60)["checkpoint"]
    for name in ("model_state", "optimizer_state", "progress"):
        assert resumed[name] == whole[name]
    partial = learning.train(checkpoint, samples, [], epochs=4, max_seconds=60, max_optimizer_steps=1)
    assert partial["checkpoint"]["progress"] == {"epochs_completed": 0, "row_cursor": 2, "optimizer_steps": 1}
    continued = learning.train(partial["checkpoint"], samples, [], epochs=4, max_seconds=60)["checkpoint"]
    for name in ("model_state", "optimizer_state", "progress"):
        assert continued[name] == whole[name]


def test_zero_budget_retains_state_and_untrained_decoder_abstains():
    samples = train_rows()
    checkpoint = learning.build_checkpoint(binding(), samples, [], **OPTIONS)
    result = learning.train(checkpoint, samples, [], epochs=1, max_seconds=0)
    assert result["report"]["optimizer_steps"] == 0 and result["report"]["training_executed"] is False
    assert result["checkpoint"]["model_state"] == checkpoint["model_state"]
    output = learning.infer(checkpoint, inference(samples))
    assert output["status"] == "abstained"
    assert all(item["reason"] == "untrained_formula_head" for item in output["rows"])


def test_zero_and_tied_output_head_abstain_without_fallback(trained):
    for value, reason in ((0., "zero_output_head"), (1., "ambiguous_decoder_scores")):
        checkpoint = copy.deepcopy(trained["checkpoint"])
        for name in ("output.weight", "output.bias"):
            checkpoint["model_state"][name] = torch.full_like(torch.tensor(checkpoint["model_state"][name]), value).tolist()
        result = learning.infer(checkpoint, inference(train_rows()))
        assert all(item["reason"] == reason and item["canonical_ir"] is None for item in result["rows"])


def test_unsupported_family_is_explicit_and_not_deontic_alias(trained):
    output = learning.infer(trained["checkpoint"], inference(train_rows()), projection_id="dcec")
    assert output["status"] == "abstained"
    assert all(item["reason"] == "unsupported_formula_projection" and item["formal_outputs"] == [] for item in output["rows"])


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(admitted=True),
    lambda value: value.update(unexpected=1),
    lambda value: value["binding"].update(dimension=384),
    lambda value: value["binding"].update(domain="security_ir"),
    lambda value: value["config"].update(temperature=1),
    lambda value: value["config"].update(max_target_tokens=128),
    lambda value: value["model_state"]["output.bias"].__setitem__(0, float("nan")),
    lambda value: value["model_state"]["output.bias"].__setitem__(0, True),
    lambda value: value["model_state"].update(extra=[]),
    lambda value: value["progress"].update(optimizer_steps=0),
    lambda value: value["progress"].update(row_cursor=True),
    lambda value: value["optimizer_state"]["parameters"]["output.bias"]["exp_avg_sq"].__setitem__(0, -1.),
    lambda value: value["implementation"]["files"].update(modal_latent_formula="0" * 64),
    lambda value: value["codec"]["source_vocabulary"].append("source"),
])
def test_checkpoint_tampering_fails_closed(trained, mutation):
    value = copy.deepcopy(trained["checkpoint"])
    mutation(value)
    with pytest.raises((ValueError, TypeError)):
        learning.validate_checkpoint(value)


@pytest.mark.parametrize("extra", [{"canonical_ir": {}}, {"embedding": [0.] * 8}, {"target": "O(x)"}])
def test_inference_rejects_targets_and_extra_fields(trained, extra):
    rows = inference(train_rows())
    rows[0].update(extra)
    with pytest.raises(ValueError, match="closed latent row"):
        learning.infer(trained["checkpoint"], rows)


def test_resume_requires_same_core_codec_data_and_disjoint_sources(trained):
    samples = train_rows()
    samples[0]["latent"][0] += .1
    with pytest.raises(ValueError, match="manifests differ"):
        learning.train(trained["checkpoint"], samples, [], epochs=1)
    wrong = binding()
    wrong["core_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="binding differs"):
        learning.LatentFormulaDecoder(trained["checkpoint"], expected_binding=wrong)
    tuning = row("distinct-id", source="  OBLIGATION AUTHORED SOURCE. ")
    with pytest.raises(ValueError, match="sources overlap"):
        learning.build_checkpoint(binding(), train_rows(), [tuning], **OPTIONS)


def test_tuning_is_observation_only_and_does_not_change_learning():
    samples = train_rows()
    tuning = [row("held-separate-source")]
    a = learning.build_checkpoint(binding(), samples, [], **OPTIONS)
    b = learning.build_checkpoint(binding(), samples, tuning, **OPTIONS)
    left = learning.train(a, samples, [], epochs=2)
    right = learning.train(b, samples, tuning, epochs=2)
    assert left["checkpoint"]["model_state"] == right["checkpoint"]["model_state"]
    assert right["report"]["tuning"]["complete"]
    assert right["report"]["tuning"]["used_for_fit_or_selection"] is False


def test_checkpoint_roundtrip_hash_and_exclusive_write(trained, tmp_path):
    checkpoint = trained["checkpoint"]
    output = tmp_path / "weights.json"
    receipt = learning.save_checkpoint(checkpoint, output)
    assert receipt["sha256"] == learning.checkpoint_digest(checkpoint)
    assert learning.load_checkpoint(output, expected_sha256=receipt["sha256"], expected_binding=binding()) == checkpoint
    assert "authored source" not in output.read_text()
    assert '"canonical_ir"' not in output.read_text()
    with pytest.raises(FileExistsError):
        learning.save_checkpoint(checkpoint, output)
    with pytest.raises(ValueError, match="hash differs"):
        learning.load_checkpoint(output, expected_sha256="0" * 64)
    duplicate = tmp_path / "duplicate.json"
    data = output.read_bytes().replace(b'{"admitted":false,', b'{"admitted":false,"admitted":false,', 1)
    assert data != output.read_bytes()
    duplicate.write_bytes(data)
    with pytest.raises(ValueError, match="duplicate JSON"):
        learning.load_checkpoint(duplicate, expected_sha256=hashlib.sha256(data).hexdigest())


def test_runtime_provenance_drift_and_thread_overcommit_fail(trained, monkeypatch):
    original = learning._pins()
    original["files"]["modal_latent_formula.py"] = "0" * 64
    monkeypatch.setattr(learning, "_pins", lambda: original)
    with pytest.raises(ValueError, match="changed since import"):
        learning.validate_checkpoint(trained["checkpoint"])
    monkeypatch.undo()
    torch.set_num_threads(2)
    with pytest.raises(ValueError, match="reserve CPU"):
        learning.validate_checkpoint(trained["checkpoint"])


def test_invalid_target_atoms_cannot_be_copied_into_codec():
    samples = train_rows()
    samples[0]["canonical_ir"]["rules"][0]["unsupported"] = "ignored?"
    with pytest.raises(ValueError, match="seven canonical facets"):
        learning.build_checkpoint(binding(), samples, [], **OPTIONS)


def test_checkpoint_has_no_training_sources_and_no_source_model(trained):
    checkpoint = trained["checkpoint"]
    assert checkpoint["codec"]["source_vocabulary"] == ["<pad>", "<unk>", "latent"]
    assert not any("source" in key or "encoder" in key for key in checkpoint["model_state"])
    assert "source_text" not in json.dumps(checkpoint)
