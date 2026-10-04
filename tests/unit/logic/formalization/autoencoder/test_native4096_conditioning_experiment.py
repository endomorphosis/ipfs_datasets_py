"""Synthetic optimizer controls, not native embeddings or qualifications."""
from copy import deepcopy
import time

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import native4096_conditioning_experiment as subject
from ipfs_datasets_py.logic.formalization.autoencoder import native4096_formula_sidecar_experiment as pilot
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical


@pytest.fixture(autouse=True)
def one_cpu():
    before = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(before)


def codec():
    return dict(schema="synthetic-control/v1", target_vocabulary=["<pad>", "<bos>", "<eos>"]
                + ["token"+str(i) for i in range(29)])


def donor():
    return numerical._model({"dimension": 384}, codec(),
        dict(seed=7, hidden_size=8, token_embedding_dim=8, projection_width=2))


def rows(dense=False):
    if dense:
        values = [[(-1. if (i+j) % 2 else 1.)/64 for i in range(4096)] for j in range(2)]
    else:
        values = [[1., 0.]+[0.]*4094, [0., 1.]+[0.]*4094]
    return [dict(id=name, source_text="Synthetic "+name, input=value, target_ids=[1, index, 2])
            for name, value, index in zip(("a", "b"), values, (3, 4))]


def fit(arm, steps=20, dense=False):
    model = pilot._new_body(donor(), vocabulary_size=32)
    receipt = subject._fit_arm(model, rows(dense), arm=arm, steps=steps, deadline=time.monotonic()+60)
    return model, receipt


def test_source_rate_geometry_uses_training_vectors_only():
    original = rows(True)
    changed = deepcopy(original)
    for row in changed:
        row["target_ids"] = [1, 12, 13, 14, 2]
    x, _, metadata = subject._prepare(original)
    x2, _, metadata2 = subject._prepare(changed)
    assert torch.equal(x, x2) and metadata == metadata2
    assert metadata["source_l1_bound"] == 64.
    model = pilot._new_body(donor(), vocabulary_size=32)
    groups = subject._groups(model, "joint_source_scaled", metadata["source_l1_bound"])
    rates = {group["name"]: group["lr"] for group in groups}
    assert rates == {"source_weights": .001/64, "source_bias": .001, "copied_prior": .001}
    actual = [id(parameter) for group in groups for parameter in group["params"]]
    assert len(actual) == len(set(actual)) == len(list(model.parameters()))


def test_unscaled_arm_replays_original_optimizer_exactly():
    parent = donor()
    old = pilot._new_body(parent, vocabulary_size=32)
    new = pilot._new_body(parent, vocabulary_size=32)
    expected = pilot._fit(old, rows(True), steps=20, learning_rate=.001, deadline=time.monotonic()+60)
    observed = subject._fit_arm(new, rows(True), arm="joint_unscaled", steps=20, deadline=time.monotonic()+60)
    assert observed["initial_tensor_sha256"] == expected["initial_tensor_sha256"]
    assert observed["final_tensor_sha256"] == expected["final_tensor_sha256"]
    assert observed["observations"][-1]["conditioned"]["cross_entropy"] == expected["final"]["cross_entropy"]
    assert observed["observations"][-1]["zero_source"]["cross_entropy"] == expected["final"]["zero_source_cross_entropy"]
    assert observed["observations"][-1]["rotated_source"]["cross_entropy"] == expected["final"]["rotated_source_cross_entropy"]


def test_frozen_prior_is_byte_identical_then_joint_phase_updates_it():
    _, frozen = fit("staged_source_scaled_plateau", steps=40)
    assert frozen["frozen_phase_copied_prior_sha256"] == frozen["initial_copied_prior_sha256"]
    assert all(row["copied_prior_frozen"] for row in frozen["updates"])
    model, joint = fit("staged_source_scaled_plateau", steps=41)
    assert joint["frozen_phase_copied_prior_sha256"] == joint["initial_copied_prior_sha256"]
    assert not joint["updates"][-1]["copied_prior_frozen"]
    assert all(parameter.requires_grad for parameter in model.parameters())
    assert any(subject.core.tensor_digest(getattr(model, name)) != digest
               for name, digest in joint["initial_copied_prior_sha256"].items())


@pytest.mark.parametrize("arm", subject.ARMS)
def test_all_arms_have_source_gradients_and_closed_control_panels(arm):
    _, receipt = fit(arm, steps=60)
    assert receipt["optimizer_steps"] == 60
    assert receipt["row_presentations"] == 120
    assert receipt["target_token_presentations"] == 240
    assert [row["step"] for row in receipt["observations"]] == [0, 20, 40, 60]
    assert receipt["observations"][-1]["conditioned"]["cross_entropy"] < receipt["observations"][0]["conditioned"]["cross_entropy"]
    for name in subject.SOURCE_WEIGHTS:
        assert any(update["source_gradient_norms_after_clip"][name] > 0 for update in receipt["updates"])
    for observation in receipt["observations"]:
        for control in ("conditioned", "zero_source", "rotated_source"):
            assert len(observation[control]["predictions"]) == 2
            assert all(set(row) == {"id", "token_ids", "status"} for row in observation[control]["predictions"])


def test_first_adam_step_activation_change_is_bounded_by_source_scaling():
    old_model, _ = fit("joint_unscaled", steps=1, dense=True)
    scaled_model, _ = fit("joint_source_scaled", steps=1, dense=True)
    x, _, _ = subject._prepare(rows(True))
    with torch.inference_mode():
        old_delta = old_model.source_to_embedding(x).abs().max().item()
        scaled_delta = scaled_model.source_to_embedding(x).abs().max().item()
    assert old_delta > 50*scaled_delta
    assert scaled_delta <= .001000001


def test_expired_deadline_cannot_modify_model():
    model = pilot._new_body(donor(), vocabulary_size=32)
    digest = subject.core.tensor_digest(model)
    with pytest.raises(ValueError, match="deadline"):
        subject._fit_arm(model, rows(), arm="joint_unscaled", deadline=time.monotonic()-1)
    assert subject.core.tensor_digest(model) == digest


@pytest.mark.parametrize("steps", [True, 0, 201, 1.5])
def test_bounded_step_recipe(steps):
    model = pilot._new_body(donor(), vocabulary_size=32)
    with pytest.raises(ValueError, match="steps"):
        subject._fit_arm(model, rows(), arm="joint_unscaled", steps=steps, deadline=time.monotonic()+10)


def test_serialized_native_receipt_never_authorizes_comparison():
    with pytest.raises((TypeError, ValueError)):
        subject.train_native_comparison({"verified": True, "rows": rows()},
            donor=donor(), codec=codec(), training_labels=[])


def test_arm_inventory_is_fixed_and_has_no_projection_or_context_relaxation():
    assert subject.ARMS == ("joint_unscaled", "joint_source_scaled", "staged_source_scaled_plateau")
    assert subject.STEPS == 200 and subject.BASE_LR == .001
    assert all(value is False for value in subject.FALSE.values())
