"""Synthetic numerical controls, never native4096 training evidence."""
from copy import deepcopy
import time

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import native4096_formula_sidecar_experiment as subject
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from ipfs_datasets_py.logic.formalization.autoencoder import dimension_native_decoder_experiment as old
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


def native_rows():
    return [dict(id="a", source_text="Control A.", embedding=[1., 0.]+[0.]*4094),
            dict(id="b", source_text="Control B.", embedding=[0., 1.]+[0.]*4094)]


def labels():
    return [dict(id="a", source_text="Control A.", target_ids=[1, 3, 2]),
            dict(id="b", source_text="Control B.", target_ids=[1, 4, 2])]


def test_constructor_preserves_donor_and_random_generator():
    parent = donor()
    parent.eval()
    parent.decoder.train()
    for parameter in parent.parameters():
        parameter.grad = torch.ones_like(parameter)
    before = core.tensor_digest(parent)
    modes = {key: m.training for key, m in parent.named_modules()}
    rng = torch.get_rng_state().clone()
    model = subject._new_body(parent, vocabulary_size=32)
    assert core.tensor_digest(parent) == before
    assert torch.equal(torch.get_rng_state(), rng)
    assert modes == {key: m.training for key, m in parent.named_modules()}
    assert all(torch.equal(p.grad, torch.ones_like(p)) for p in parent.parameters())
    assert all(p.grad is None for p in model.parameters())
    for name in ("target_embedding", "decoder", "output"):
        assert core.tensor_digest(getattr(model, name)) == core.tensor_digest(getattr(parent, name))
        assert next(getattr(model, name).parameters()).data_ptr() != next(getattr(parent, name).parameters()).data_ptr()
    assert model.dimension == 4096 and model.condition.in_features == 4096
    assert torch.count_nonzero(model.source_to_embedding.weight) == 0
    assert torch.count_nonzero(model.condition.weight) == 0


def test_real_gradient_paths_reduce_synthetic_ce_and_use_source():
    parent = donor()
    before = core.tensor_digest(parent)
    model = subject._new_body(parent, vocabulary_size=32)
    rows = subject._training_rows(native_rows(), labels(), codec())
    result = subject._fit(model, rows, steps=60, learning_rate=.01, deadline=time.monotonic()+20)
    assert result["final"]["cross_entropy"] < result["initial"]["cross_entropy"]
    assert result["final"]["cross_entropy"] < result["final"]["rotated_source_cross_entropy"]
    assert result["optimizer_steps"] == 60 and result["row_presentations"] == 120
    assert result["target_token_presentations"] == 240
    assert result["final_tensor_sha256"] != result["initial_tensor_sha256"]
    assert all(any(step["source_gradient_norms"][name] > 0 for step in result["updates"])
               for name in ("condition.weight", "source_to_embedding.weight"))
    assert core.tensor_digest(parent) == before


def test_full_prefix_matches_causal_recurrence():
    model = subject._new_body(donor(), vocabulary_size=32)
    with torch.no_grad():
        model.source_to_embedding.weight.fill_(.01)
    source = torch.tensor([r["embedding"] for r in native_rows()])
    prefix = torch.tensor([[1, 3], [1, 4]])
    full, _ = model.next_logits(prefix, model.start(source))
    state = model.start(source)
    parts = []
    for i in range(2):
        logits, state = model.next_logits(prefix[:, i:i+1], state)
        parts.append(logits)
    assert torch.allclose(full, torch.cat(parts, 1), atol=1e-7, rtol=1e-6)
    assert state[1] is source
    assert torch.equal(model.project(source), source)


@pytest.mark.parametrize("change", ["source", "width", "nan", "norm", "duplicate", "partial", "extra", "unknown"])
def test_row_validation_is_closed_and_rejects_mismatches(change):
    native, targets = native_rows(), labels()
    if change == "source":
        targets[0]["source_text"] = "Different source."
    elif change == "width":
        native[0]["embedding"].pop()
    elif change == "nan":
        native[0]["embedding"][0] = float("nan")
    elif change == "norm":
        native[0]["embedding"][0] = .1
    elif change == "duplicate":
        targets[1] = deepcopy(targets[0])
    elif change == "partial":
        targets[0]["target_ids"][-1] = 4
    elif change == "extra":
        targets[0]["verified"] = True
    else:
        targets[0]["id"] = "unknown"
    with pytest.raises(ValueError):
        subject._training_rows(native, targets, codec())


def test_expired_deadline_cannot_update_weights():
    model = subject._new_body(donor(), vocabulary_size=32)
    before = core.tensor_digest(model)
    rows = subject._training_rows(native_rows(), labels(), codec())
    with pytest.raises(ValueError, match="deadline"):
        subject._fit(model, rows, steps=20, learning_rate=.001, deadline=time.monotonic()-1)
    assert core.tensor_digest(model) == before


@pytest.mark.parametrize("steps", [True, 0, 201, 1.5])
def test_bounded_update_budget(steps):
    model = subject._new_body(donor(), vocabulary_size=32)
    rows = subject._training_rows(native_rows(), labels(), codec())
    with pytest.raises(ValueError, match="steps"):
        subject._fit(model, rows, steps=steps, learning_rate=.001, deadline=time.monotonic()+5)


def test_old_three_width_factory_stays_closed_for4096():
    with pytest.raises(ValueError, match="dimension"):
        old.bind_dimension_native_body(donor(), dimension=4096)


def test_serialized_receipt_cannot_authorize_training():
    pytest.importorskip("ipfs_datasets_py.logic.formalization.autoencoder.source_embeddings_4096_full_owner")
    with pytest.raises((TypeError, ValueError)):
        subject.train_native_pilot(dict(rows=native_rows(), verified=True),
            donor=donor(), codec=codec(), training_labels=labels())
