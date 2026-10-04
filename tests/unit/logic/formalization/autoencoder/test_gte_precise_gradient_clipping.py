"""Safety-bound and runtime restoration checks for the explicit numerical adapter."""
import importlib
import math

import pytest
import torch

adapter = importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder.gte_precise_gradient_clipping")


def parameter(gradient):
    value = torch.nn.Parameter(torch.zeros_like(gradient))
    value.grad = gradient.clone()
    return value


@pytest.mark.parametrize("scale", [0.0, .5, 1.0, 1.0000001192092896, 12.0])
def test_clipping_near_bound_zero_and_large_keeps_exact_bound(scale):
    p = parameter(torch.tensor([scale, 0.], dtype=torch.float32))
    before = p.grad.clone()
    records = []
    result = adapter.clip_grad_norm_([p], 1.0, records=records, error_if_nonfinite=True, foreach=False)
    assert float(result) == float(before.double().norm())
    assert p.grad.dtype == torch.float32
    assert float(p.grad.double().norm()) <= 1.0
    if scale <= 1:
        assert torch.equal(p.grad, before)
    assert records[0]["norm_after"] <= records[0]["max_norm"]


def test_large_vector_clips_using_double_precision_total_norm():
    generator = torch.Generator().manual_seed(1729)
    parameters = [parameter(torch.randn(295680, generator=generator)), parameter(torch.ones(384))]
    before = torch.linalg.vector_norm(torch.stack([p.grad.double().norm() for p in parameters]))
    result = adapter.clip_grad_norm_(parameters, 1.0)
    after = torch.linalg.vector_norm(torch.stack([p.grad.double().norm() for p in parameters]))
    assert torch.equal(before, result)
    assert .99999 < float(after) <= 1.0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_fails_closed_before_mutating_any_gradient(value):
    first = parameter(torch.tensor([2.]))
    second = parameter(torch.tensor([value]))
    with pytest.raises(ValueError, match="finite dense"):
        adapter.clip_grad_norm_([first, second], 1.)
    assert first.grad.item() == 2.


def test_unsupported_dtype_and_bound_fail_closed():
    with pytest.raises(ValueError, match="CPU float32"):
        adapter.clip_grad_norm_([parameter(torch.ones(1, dtype=torch.float64))], 1.)
    for bound in (0., -1., math.inf, math.nan):
        with pytest.raises(ValueError, match="finite positive"):
            adapter.clip_grad_norm_([parameter(torch.ones(1))], bound)


def test_temporary_runtime_adapter_restores_original_on_failure():
    original = torch.nn.utils.clip_grad_norm_
    records = []
    with pytest.raises(RuntimeError, match="test exit"):
        with adapter.installed_clipper(records):
            assert torch.nn.utils.clip_grad_norm_ is not original
            torch.nn.utils.clip_grad_norm_([parameter(torch.tensor([2.]))], 1.)
            raise RuntimeError("test exit")
    assert torch.nn.utils.clip_grad_norm_ is original
    assert len(records) == 1
