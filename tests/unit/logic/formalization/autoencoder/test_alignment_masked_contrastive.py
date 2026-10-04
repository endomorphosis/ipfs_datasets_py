"""Synthetic mask arithmetic and gradient boundaries, never semantic labels."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
MODULE = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/alignment_masked_contrastive.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


subject = load(MODULE, "isolated_masked_loss")
legacy = load(MODULE.with_name("alignment_projection.py"), "isolated_legacy_loss")


@pytest.fixture
def torch():
    return pytest.importorskip("torch")


def pair(torch, dtype=None):
    dtype = torch.float64 if dtype is None else dtype
    source = torch.tensor([[0.4, -0.2], [-0.1, 0.3]], dtype=dtype, requires_grad=True)
    formal = torch.tensor([[0.1, 0.2], [-0.3, 0.4], [0.2, -0.1]], dtype=dtype, requires_grad=True)
    positive = torch.tensor([[True, True, False], [False, False, True]], dtype=torch.bool)
    negative = torch.tensor([[False, False, True], [True, False, False]], dtype=torch.bool)
    return source, formal, positive, negative


def run(values, **kwargs):
    source, formal, positive, negative = values
    return subject.masked_multi_positive_contrastive_loss(source, formal, positive_mask=positive,
        permitted_negative_mask=negative, **kwargs)


def test_module_import_does_not_import_torch():
    code = """
import importlib.abc,importlib.util,sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self,name,path=None,target=None):
        if name=='torch' or name.startswith('torch.'):
            raise AssertionError('torch imported at module import')
sys.meta_path.insert(0,Guard())
spec=importlib.util.spec_from_file_location('inert_subject',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert 'torch' not in sys.modules
"""
    result = subprocess.run([sys.executable, "-I", "-c", code, str(MODULE)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("dtype_name", ["float32", "float64"])
@pytest.mark.parametrize("weighted", [False, True])
def test_exact_legacy_parity_when_all_nonpositives_are_permitted(torch, dtype_name, weighted):
    dtype = getattr(torch, dtype_name)
    source = torch.tensor([[0.4, -0.2], [-0.1, 0.3], [0.2, 0.5], [-0.4, 0.1]], dtype=dtype, requires_grad=True)
    formal = torch.tensor([[0.2, 0.3], [-0.4, 0.1], [0.1, 0.5], [-0.3, -0.1]], dtype=dtype, requires_grad=True)
    identifiers = ["synthetic_same", "synthetic_same", "synthetic_other", "synthetic_last"]
    positive = torch.tensor([[left == right for right in identifiers] for left in identifiers], dtype=torch.bool)
    negative = ~positive
    weights = torch.arange(1, 17, dtype=dtype).reshape(4, 4) if weighted else None
    old = legacy.multi_positive_contrastive_loss(source, formal, identifiers, temperature=0.2, hard_negative_weights=weights)
    new = subject.masked_multi_positive_contrastive_loss(source, formal, positive_mask=positive,
        permitted_negative_mask=negative, temperature=0.2, negative_weights=weights)
    assert torch.equal(old, new)
    old_grads = torch.autograd.grad(old, (source, formal), retain_graph=True)
    new_grads = torch.autograd.grad(new, (source, formal))
    assert all(torch.equal(left, right) for left, right in zip(old_grads, new_grads, strict=True))


def test_rectangular_weighted_mass_and_ignored_nonfinite_weights(torch):
    values = pair(torch)
    source, formal, positive, negative = values
    weights = torch.tensor([[float("nan"), -float("inf"), 2.0], [3.0, float("nan"), float("inf")]], dtype=torch.float64)
    logits = source @ formal.T / 0.3
    numerator = logits.masked_fill(~positive, -torch.inf)
    safe = torch.where(negative, weights, torch.ones_like(weights))
    denominator = (logits + safe.log()).masked_fill(~(positive | negative), -torch.inf)
    expected = ((torch.logsumexp(denominator, 1) - torch.logsumexp(numerator, 1)).mean()
                + (torch.logsumexp(denominator, 0) - torch.logsumexp(numerator, 0)).mean()) / 2
    loss = run(values, temperature=0.3, negative_weights=weights)
    assert torch.equal(loss, expected)
    gradients = torch.autograd.grad(loss, (source, formal))
    assert all(bool(torch.isfinite(gradient).all()) and bool((gradient != 0).any()) for gradient in gradients)


def test_transposed_rectangular_loss_and_gradients_are_symmetric(torch):
    source, formal, positive, negative = pair(torch)
    first = run((source, formal, positive, negative), temperature=0.3)
    second = run((formal, source, positive.T, negative.T), temperature=0.3)
    assert torch.equal(first, second)
    one = torch.autograd.grad(first, (source, formal), retain_graph=True)
    two = torch.autograd.grad(second, (source, formal))
    assert all(torch.equal(left, right) for left, right in zip(one, two, strict=True))


def test_unknown_coordinate_perturbation_and_pair_logit_gradient_isolation(torch):
    source = torch.eye(3, dtype=torch.float64)
    formal = torch.tensor([[0.5, -0.1, 0.3], [-0.2, 0.4, 0.1], [0.2, 0.6, -0.3]], dtype=torch.float64, requires_grad=True)
    positive = torch.eye(3, dtype=torch.bool)
    negative = torch.tensor([[False, True, False], [True, False, False], [False, True, False]])
    unknown = ~(positive | negative)
    old_logits = source @ formal.T
    changed = formal.detach().clone()
    changed[2, 0] += 900.0  # Only source0/formal2, an unknown pair, changes.
    assert torch.equal(old_logits[~unknown], (source @ changed.T)[~unknown])
    loss = run((source, formal, positive, negative), temperature=1.0)
    assert torch.equal(loss, run((source, changed, positive, negative), temperature=1.0))
    pair_gradient = torch.autograd.grad(loss, formal)[0].T
    assert torch.equal(pair_gradient[unknown], torch.zeros_like(pair_gradient[unknown]))
    assert bool((pair_gradient[~unknown] != 0).any())


def test_unknown_logits_still_must_be_finite(torch):
    source = torch.eye(3, dtype=torch.float64)
    formal = torch.eye(3, dtype=torch.float64)
    formal[2, 0] = 1e308
    positive = torch.eye(3, dtype=torch.bool)
    with pytest.raises(ValueError, match="including unknown"):
        run((source, formal, positive, torch.zeros_like(positive)), temperature=0.07)


def test_no_negatives_connected_exact_zero_without_overflowing_sum(torch):
    source = (torch.eye(2, dtype=torch.float64) * 1e154).requires_grad_()
    formal = (torch.ones((2, 2), dtype=torch.float64) * 1e154).requires_grad_()
    positive = torch.eye(2, dtype=torch.bool)
    negative = torch.zeros((2, 2), dtype=torch.bool)
    loss = run((source, formal, positive, negative), temperature=1.0)
    assert loss.requires_grad and loss.item() == 0.0
    for gradient in torch.autograd.grad(loss, (source, formal)):
        assert torch.equal(gradient, torch.zeros_like(gradient))
    descriptor = subject.describe_masked_contrastive_relations(positive, negative)
    assert descriptor["global_no_separation_signal"] is True
    assert descriptor["rows_without_permitted_negatives"] == descriptor["columns_without_permitted_negatives"] == [0, 1]


def test_directional_no_negative_anchors_are_not_dropped_from_means(torch):
    source = torch.eye(2, dtype=torch.float64)
    formal = torch.tensor([[0.1, 0.2], [0.3, 0.4]], dtype=torch.float64)
    positive = torch.tensor([[True, True], [False, True]])
    negative = torch.tensor([[False, False], [True, False]])
    logits = source @ formal.T
    expected = ((torch.logsumexp(logits[1], 0) - logits[1, 1]) / 2
                + (torch.logsumexp(logits[:, 0], 0) - logits[0, 0]) / 2) / 2
    assert torch.equal(run((source, formal, positive, negative), temperature=1.0), expected)
    descriptor = subject.describe_masked_contrastive_relations(positive, negative)
    assert descriptor["rows_without_permitted_negatives"] == [0]
    assert descriptor["columns_without_permitted_negatives"] == [1]


def test_float64_gradcheck_with_ignored_nonfinite_weights(torch):
    source, formal, positive, negative = pair(torch)
    weights = torch.tensor([[float("nan"), float("inf"), 2.0], [3.0, -float("inf"), float("nan")]], dtype=torch.float64)
    assert torch.autograd.gradcheck(lambda left, right: subject.masked_multi_positive_contrastive_loss(left, right,
        positive_mask=positive, permitted_negative_mask=negative, temperature=0.3, negative_weights=weights),
        (source, formal), eps=1e-6, atol=1e-5, rtol=1e-3)


def test_descriptor_is_detached_sealed_and_has_no_semantic_authority(torch):
    _, _, positive, negative = pair(torch)
    before = positive.clone(), negative.clone()
    descriptor = subject.describe_masked_contrastive_relations(positive, negative)
    assert (descriptor["pair_count"], descriptor["positive_pair_count"], descriptor["permitted_negative_pair_count"], descriptor["unknown_pair_count"]) == (6, 3, 2, 1)
    assert descriptor["row_counts"][1] == {"index": 1, "positive_count": 1, "permitted_negative_count": 1, "unknown_count": 1}
    expected_sha = hashlib.sha256(json.dumps(positive.tolist(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert descriptor["positive_mask_sha256"] == expected_sha
    assert descriptor["masks"] == dict.fromkeys(subject.MASKS, 0)
    assert all(descriptor[name] is False for name in subject.FALSE)
    assert descriptor["content_sha256"] == subject._digest({key: value for key, value in descriptor.items() if key != "content_sha256"})
    descriptor["row_counts"][0]["positive_count"] = 999
    assert torch.equal(positive, before[0]) and torch.equal(negative, before[1])
    assert subject.describe_masked_contrastive_relations(positive, negative)["row_counts"][0]["positive_count"] == 2


def test_inputs_rng_and_existing_gradient_fields_are_unchanged(torch):
    values = pair(torch)
    original = [value.detach().clone() for value in values]
    rng = torch.get_rng_state().clone()
    assert bool(torch.isfinite(run(values, temperature=0.3)))
    subject.describe_masked_contrastive_relations(values[2], values[3])
    assert all(torch.equal(value, prior) for value, prior in zip(values, original, strict=True))
    assert values[0].grad is values[1].grad is None
    assert torch.equal(torch.get_rng_state(), rng)


@pytest.mark.parametrize("temperature", [True, False, 0, -1, float("nan"), float("inf"), 10**1000, "0.07"])
def test_temperature_is_exact_finite_positive_numeric(torch, temperature):
    with pytest.raises(ValueError, match="temperature"):
        run(pair(torch), temperature=temperature)


@pytest.mark.parametrize("kind", ["integer", "floating", "overlap", "missing_row", "missing_column", "shape", "meta", "empty", "too_many"])
def test_masks_are_cpu_bool_and_require_bidirectional_positives(torch, kind):
    source, formal, positive, negative = pair(torch)
    if kind == "integer":
        positive = positive.to(torch.int64)
    elif kind == "floating":
        negative = negative.to(torch.float64)
    elif kind == "overlap":
        negative[0, 0] = True
    elif kind == "missing_row":
        positive[0] = False
    elif kind == "missing_column":
        positive[:, 2] = False
    elif kind == "shape":
        negative = torch.zeros((3, 2), dtype=torch.bool)
    elif kind == "meta":
        positive = torch.empty((2, 3), dtype=torch.bool, device="meta")
    elif kind == "empty":
        positive = negative = torch.empty((0, 3), dtype=torch.bool)
    else:
        positive = torch.ones((129, 1), dtype=torch.bool)
        negative = torch.zeros_like(positive)
    with pytest.raises(ValueError):
        run((source, formal, positive, negative))
    with pytest.raises(ValueError):
        subject.describe_masked_contrastive_relations(positive, negative)


@pytest.mark.parametrize("kind", ["dtype", "integer", "nan", "infinite", "width", "rank", "meta", "empty", "rows", "wide"])
def test_representation_domain_is_bounded_finite_cpu_matching_float(torch, kind):
    source, formal, positive, negative = pair(torch)
    if kind == "dtype":
        source = source.to(torch.float32)
    elif kind == "integer":
        source = formal = torch.ones((2, 2), dtype=torch.int64)
    elif kind == "nan":
        source = source.detach().clone()
        source[0, 0] = float("nan")
    elif kind == "infinite":
        formal = formal.detach().clone()
        formal[0, 0] = float("inf")
    elif kind == "width":
        formal = torch.zeros((3, 3), dtype=torch.float64)
    elif kind == "rank":
        source = source.unsqueeze(0)
    elif kind == "meta":
        source = torch.empty((2, 2), dtype=torch.float64, device="meta")
    elif kind == "empty":
        source = torch.empty((0, 2), dtype=torch.float64)
    elif kind == "rows":
        source = torch.zeros((129, 2), dtype=torch.float64)
    else:
        source = torch.zeros((2, 8193), dtype=torch.float64)
        formal = torch.zeros((3, 8193), dtype=torch.float64)
    with pytest.raises(ValueError):
        run((source, formal, positive, negative))


@pytest.mark.parametrize("kind", ["less_than_one", "nan_negative", "inf_negative", "requires_grad", "dtype", "integer", "shape", "meta"])
def test_only_fixed_matching_valid_negative_weights_are_accepted(torch, kind):
    weights = torch.ones((2, 3), dtype=torch.float64)
    if kind == "less_than_one":
        weights[0, 2] = 0.99
    elif kind == "nan_negative":
        weights[0, 2] = float("nan")
    elif kind == "inf_negative":
        weights[1, 0] = float("inf")
    elif kind == "requires_grad":
        weights.requires_grad_()
    elif kind == "dtype":
        weights = weights.to(torch.float32)
    elif kind == "integer":
        weights = weights.to(torch.int64)
    elif kind == "shape":
        weights = torch.ones((3, 2), dtype=torch.float64)
    else:
        weights = torch.empty((2, 3), dtype=torch.float64, device="meta")
    with pytest.raises(ValueError):
        run(pair(torch), negative_weights=weights)


@pytest.mark.parametrize("dtype_name", ["float32", "float64"])
def test_ambient_cpu_autocast_preserves_explicit_dtype_and_state(torch, dtype_name):
    values = pair(torch, getattr(torch, dtype_name))
    ordinary = run(values, temperature=0.3)
    with torch.autocast(device_type="cpu", dtype=torch.bfloat16):
        under_autocast = run(values, temperature=0.3)
        assert torch.is_autocast_enabled("cpu")
    assert under_autocast.dtype == ordinary.dtype == getattr(torch, dtype_name)
    assert torch.equal(ordinary, under_autocast)


def test_finite_forward_domain_does_not_imply_universal_finite_backward(torch):
    positive = torch.eye(2, dtype=torch.bool)
    source = torch.zeros((2, 1), dtype=torch.float32, requires_grad=True)
    formal = torch.tensor([[1.0], [-1.0]], requires_grad=True)
    loss = run((source, formal, positive, ~positive), temperature=1e-40)
    assert bool(torch.isfinite(loss))
    assert not bool(torch.isfinite(torch.autograd.grad(loss, (source, formal))[0]).all())


def test_noncontiguous_dense_inputs_are_supported_and_sparse_inputs_rejected(torch):
    source, formal, positive, negative = pair(torch)
    dense = (source.T.contiguous().T, formal.T.contiguous().T, positive.T.contiguous().T, negative.T.contiguous().T)
    assert not dense[0].is_contiguous()
    assert torch.equal(run(dense), run((source, formal, positive, negative)))
    with pytest.raises(ValueError):
        run((source.to_sparse(), formal, positive, negative))
    with pytest.raises(ValueError):
        subject.describe_masked_contrastive_relations(positive.to_sparse(), negative)
    with pytest.raises(ValueError):
        run((source, formal, positive, negative), negative_weights=torch.ones((2, 3), dtype=torch.float64).to_sparse())
