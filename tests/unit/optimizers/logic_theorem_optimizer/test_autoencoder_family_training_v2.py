"""Training-only calibration, independent family selection and native inference."""
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training as old
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_v2 as api
from ipfs_datasets_py.logic.formalization.autoencoder.family_training import prepare_family_training_targets
from ipfs_datasets_py.logic.intent_ir.formalize.rich_grammar import parse_instruction


def target(text):
    return prepare_family_training_targets("intent_ir", document=parse_instruction(text), source_text=text,
        requested_families=["deontic", "dcec", "tdfol", "frame_logic"])


@pytest.fixture
def corpus():
    return ([target(f"The agent must save the {name} record.") for name in ("amber", "cobalt", "ivory")],
            [target("The agent must save the validationunique report.")])


def test_exact_family_does_not_veto_independent_decoder_improvement():
    import torch
    # Both native projections start at constant predictions: a is wrong, b is exact.
    initial = [torch.zeros((2, 1), dtype=torch.float64), torch.zeros(1, dtype=torch.float64),
               torch.zeros((1, 2), dtype=torch.float64), torch.tensor([2., 1.], dtype=torch.float64)]
    proposal = [p.clone() for p in initial]
    proposal[3] = torch.tensor([1., 3.], dtype=torch.float64)
    data = torch.ones((2, 2), dtype=torch.float64)
    mask = torch.ones((2, 2), dtype=torch.bool)
    descriptors = {"a": {"logic_family": "deontic"}, "b": {"logic_family": "temporal"}}
    selected, loss, _, receipt = api._select_decoder_families(torch, initial, proposal, data, mask,
        {"a": (0, 1), "b": (1, 2)}, descriptors)
    assert receipt["selected_families"] == ["deontic"]
    assert torch.equal(selected[3], torch.ones(2, dtype=torch.float64))
    assert loss == pytest.approx(0.)
    assert all(torch.equal(initial[i], selected[i]) for i in (0, 1, 2))


def test_family_selection_rejects_changed_shared_encoder():
    import torch
    initial = [torch.zeros((1, 1)), torch.zeros(1), torch.zeros((1, 1)), torch.zeros(1)]
    candidate = [p.clone() for p in initial]
    candidate[0][0, 0] = 1
    with pytest.raises(ValueError, match="identical shared encoder"):
        api._select_decoder_families(torch, initial, candidate, None, None, None, None)


def test_calibration_uses_only_observed_training_projection_rows():
    import torch
    parameters = [torch.tensor([[.2], [.3]], dtype=torch.float64), torch.zeros(1, dtype=torch.float64),
                  torch.zeros((1, 2), dtype=torch.float64), torch.zeros(2, dtype=torch.float64)]
    data = torch.tensor([[1., 0.], [0., 1.]], dtype=torch.float64)
    mask = torch.tensor([[True, False], [False, True]])
    result, observations = api._calibrate_decoder(torch, parameters, data, mask,
        {"a": (0, 1), "b": (1, 2)}, .001)
    assert all(row["training_rows"] == 1 and row["train_mse_after"] < row["train_mse_before"]
               for row in observations)
    assert all(torch.equal(result[index], parameters[index]) for index in (0, 1))
    assert not torch.equal(result[2], parameters[2])


def test_real_targets_calibration_refinement_and_saved_weight_inference(tmp_path, corpus):
    training, validation = corpus
    result = api.train_family_projection_autoencoder_v2(training, validation,
        output_dir=tmp_path / "model", epochs=3, latent_width=2)
    report = result["report"]
    assert report["training_executed"] and report["optimizer_steps"] == 3
    assert report["decoder_calibration"]["status"] == "executed"
    assert report["after"]["objective"] <= report["before"]["objective"]
    assert all(loss <= report["before"]["families"][name] + api.EPS
               for name, loss in report["after"]["families"].items())
    inference = api.infer_family_projection_autoencoder_v2(result["descriptor"], validation)
    assert inference["objective"] == pytest.approx(report["after"]["objective"])
    assert inference["formulas_generated"] is False
    saved, _ = api._read(result["descriptor"])
    assert not any("validationunique" in token for _, token in saved["space"]["columns"])


def test_validation_changes_never_change_fitted_calibration_proposal(tmp_path, corpus):
    training, validation = corpus
    first = api.train_family_projection_autoencoder_v2(training, validation,
        output_dir=tmp_path / "first", epochs=1, latent_width=2)
    second = api.train_family_projection_autoencoder_v2(training,
        [target("The reviewer may view the unseen report.")], output_dir=tmp_path / "second", epochs=1, latent_width=2)
    assert first["report"]["decoder_calibration"]["proposal_parameters_sha256"] == \
        second["report"]["decoder_calibration"]["proposal_parameters_sha256"]


def test_complete_v1_and_v2_parent_transfer_preserves_original_bytes(tmp_path, corpus):
    training, validation = corpus
    original = old.train_family_projection_autoencoder(training, validation,
        output_dir=tmp_path / "old", epochs=1, latent_width=2)
    parent_raw = Path(original["descriptor"]["path"]).read_bytes()
    saved, _ = old._read(original["descriptor"])
    child = api.train_family_projection_autoencoder_v2(training, validation,
        output_dir=tmp_path / "child", parent_descriptor=original["descriptor"], epochs=1, latent_width=2)
    assert child["report"]["initial_parameters_sha256"] == api._digest(saved["parameters"])
    assert Path(original["descriptor"]["path"]).read_bytes() == parent_raw
    child_raw = Path(child["descriptor"]["path"]).read_bytes()
    next_ = api.train_family_projection_autoencoder_v2(training, validation,
        output_dir=tmp_path / "next", parent_descriptor=child["descriptor"], epochs=1, latent_width=2)
    assert next_["report"]["initial_parameters_sha256"] == child["report"]["selected_parameters_sha256"]
    assert Path(child["descriptor"]["path"]).read_bytes() == child_raw
    with pytest.raises(ValueError, match="original validation panel"):
        api.train_family_projection_autoencoder_v2(training, [target("The reviewer must view another report.")],
            output_dir=tmp_path / "wrong", parent_descriptor=child["descriptor"], epochs=1, latent_width=2)


def test_source_overlap_and_stale_producers_stop_before_output(tmp_path, corpus, monkeypatch):
    training, validation = corpus
    with pytest.raises(ValueError, match="source leakage"):
        api.train_family_projection_autoencoder_v2(training, training, output_dir=tmp_path / "bad")
    assert not (tmp_path / "bad").exists()
    result = api.train_family_projection_autoencoder_v2(training, validation,
        output_dir=tmp_path / "good", epochs=1, latent_width=2)
    from ipfs_datasets_py.logic.intent_ir.formalize import extended_projections
    path = Path(extended_projections.__file__)
    reader = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda p: reader(p) + b"# drift" if p == path else reader(p))
    with pytest.raises(ValueError, match="native target producer changed"):
        api._read(result["descriptor"])


def test_effective_panel_reports_collapsed_heldout_features(tmp_path, corpus):
    training, _ = corpus
    validation = [target(f"The agent must save the {word} record.") for word in ("novelalpha", "novelbeta")]
    result = api.train_family_projection_autoencoder_v2(training, validation,
        output_dir=tmp_path / "model", epochs=1, latent_width=2)
    panel = result["report"]["effective_feature_panels"]["validation"]
    assert panel["rows"] == 2
    assert panel["distinct_retained_feature_vectors"] == 1
    assert panel["colliding_row_groups"] == [[0, 1]]


def test_expired_calibration_reports_work_but_retains_initializer(tmp_path, corpus, monkeypatch):
    training, validation = corpus
    clock = [0.]
    calibrate = api._calibrate_decoder

    def expire_after_calibration(*args, **kwargs):
        result = calibrate(*args, **kwargs)
        clock[0] = 121.
        return result

    monkeypatch.setattr(api.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(api, "_calibrate_decoder", expire_after_calibration)
    result = api.train_family_projection_autoencoder_v2(training, validation,
        output_dir=tmp_path / "model", epochs=1, latent_width=2, max_seconds=120)
    report = result["report"]
    assert report["decoder_calibration"]["status"] == "discarded_due_deadline"
    assert report["training_executed"] and report["optimizer_steps"] == 0
    assert report["initial_parameters_sha256"] == report["selected_parameters_sha256"]
    assert report["decoder_calibration"]["selected_families"] == []
    assert report["stopping"] == "deadline"
