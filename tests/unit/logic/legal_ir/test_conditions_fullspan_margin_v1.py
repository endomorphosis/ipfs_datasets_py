"""Synthetic scalar and supplied-logit controls; no model or optimizer is opened."""
import copy
import importlib.util
import math
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[4] / "ipfs_datasets_py/logic/legal_ir/conditions_fullspan_margin_v1.py"
spec = importlib.util.spec_from_file_location("conditions_fullspan_margin_controls", SOURCE)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def target(count=3, present=True, span=(1, 2)):
    return {"token_count": count, "present": present, "span": span if present else (-100, -100)}


def test_full_domain_includes_wrong_spans_outside_gold_start_and_ignores_padding():
    starts, ends, labels = [[4., 1., 0., 100.]], [[0., 0., 2., 100.]], [target()]
    before = copy.deepcopy((starts, ends, labels))
    result = subject.conditions_fullspan_margin_reference(starts, ends, labels)
    row = result["row_diagnostics"][0]
    assert row["wrong_span"] == [0, 2] and row["wrong_domain_count"] == 5
    assert row["gold_score"] == 3 and row["wrong_score"] == 6
    assert result["loss"] == 4 and result["weighted_loss"] == 1
    assert (starts, ends, labels) == before
    assert not any(result[k] for k in ("qualified", "semantic_gold", "proof_authority", "training_executed", "model_execution_performed"))


def test_exact_ties_choose_earliest_wrong_row_major_pair():
    row = subject.conditions_fullspan_margin_reference([[0., 0., 0.]], [[0., 0., 0.]], [target(span=(0, 0))])["row_diagnostics"][0]
    assert row["wrong_span"] == [0, 1] and row["max_tie_count"] == 5


def test_reversed_pair_cannot_win():
    row = subject.conditions_fullspan_margin_reference([[0., 0., 10.]], [[10., 0., 0.]], [target(span=(0, 2))])["row_diagnostics"][0]
    assert row["wrong_span"] == [0, 0] and row["wrong_score"] == 10


def test_full_batch_denominator_includes_absent_rows_and_duplicate_invariance():
    starts, ends = [[4., 1., 0.], [9., 9., 9.]], [[0., 0., 2.], [9., 9., 9.]]
    labels = [target(), target(present=False)]
    value = subject.conditions_fullspan_margin_reference(starts, ends, labels)
    assert value["loss"] == 2 and value["weighted_loss"] == .5
    assert value["row_diagnostics"][1]["wrong_span"] is None
    doubled = subject.conditions_fullspan_margin_reference(starts * 2, ends * 2, labels * 2)
    assert doubled["loss"] == value["loss"]


def test_absent_and_empty_wrong_domain_zero_without_overflowing_input_sum():
    result = subject.conditions_fullspan_margin_reference([[3e38], [3e38]], [[3e38], [3e38]],
        [target(1, span=(0, 0)), target(1, present=False)])
    assert result["loss"] == 0 and all(row["wrong_domain_count"] == 0 for row in result["row_diagnostics"])


def test_zero_control_skips_pair_arithmetic():
    result = subject.conditions_fullspan_margin_reference([[3e38, 3e38]], [[3e38, 3e38]], [target(2, span=(0, 0))], weight=0)
    assert result["loss"] == result["weighted_loss"] == 0
    assert result["margin_computed"] is False and result["row_diagnostics"] == []


@pytest.mark.parametrize("weight", [True, None, -1, .1, 1, float("nan"), float("inf")])
def test_only_fixed_matched_weights_are_accepted_before_backend_access(weight):
    with pytest.raises(ValueError, match="weight"):
        subject.conditions_fullspan_margin_from_logits(object(), None, None, [], weight=weight)


@pytest.mark.parametrize("labels", [[], [target(0)], [target(257)], [target(present=1)], [target(span=(2, 1))],
    [{**target(), "teacher": True}], [{**target(present=False), "span": (0, 0)}], [target()] * 33])
def test_bad_targets_refuse_before_backend_access(labels):
    with pytest.raises(ValueError):
        subject.conditions_fullspan_margin_from_logits(object(), None, None, labels)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 4e38, 10**1000, True])
def test_scalar_scores_must_be_finite_float32_including_padding(value):
    with pytest.raises(ValueError):
        subject.conditions_fullspan_margin_reference([[0., 0., 0., value]], [[0., 0., 0., 0.]], [target()])


def test_valid_pair_overflow_refuses_without_silently_changing_precision():
    with pytest.raises(ValueError, match="overflow"):
        subject.conditions_fullspan_margin_reference([[3e38, 3e38]], [[3e38, 3e38]], [target(2, span=(0, 0))])


def test_scalar_negative_hinge_overflow_is_rejected():
    with pytest.raises(ValueError, match="overflow"):
        subject.conditions_fullspan_margin_reference([[0., 0.]], [[3e38, -3e38]], [target(2, span=(0, 0))])


def test_negative_hinge_overflow_is_not_hidden_by_tensor_relu():
    import torch
    with pytest.raises(ValueError, match="hinge overflow"):
        subject.conditions_fullspan_margin_from_logits(torch, torch.tensor([[0., 0.]], dtype=torch.float32),
            torch.tensor([[3e38, -3e38]], dtype=torch.float32), [target(2, span=(0, 0))])


def test_hinge_preserves_declared_float32_association():
    # (1 + wrong) - gold rounds differently from (wrong - gold) + 1 here.
    value = subject.conditions_fullspan_margin_reference([[16777216., 0.]], [[0., 0.]], [target(2, span=(0, 0))])
    assert value["row_diagnostics"][0]["wrong_score"] == 16777216.
    assert value["loss"] == 0.


@pytest.mark.parametrize("end_values, expected_loss, end_gradient", [
    ([0., 0., 2., 100.], .5, [0., 0., 0., 0.]),
    ([5., 0., 2., 100.], .875, [.125, 0., -.125, 0.]),
])
def test_supplied_logits_autograd_and_matched_zero_control(end_values, expected_loss, end_gradient):
    import torch
    labels = [target(), target(present=False)]
    rng_before, grad_mode_before = torch.get_rng_state().clone(), torch.is_grad_enabled()
    start = torch.tensor([[4., 1., 0., 100.], [3e38, 3e38, 3e38, 100.]], dtype=torch.float32, requires_grad=True)
    end = torch.tensor([end_values, [3e38, 3e38, 3e38, 100.]], dtype=torch.float32, requires_grad=True)
    start_before, end_before, labels_before = start.detach().clone(), end.detach().clone(), copy.deepcopy(labels)
    result = subject.conditions_fullspan_margin_from_logits(torch, start, end, labels)
    reference = subject.conditions_fullspan_margin_reference(start.detach().tolist(), end.detach().tolist(), labels)
    assert result["row_diagnostics"] == reference["row_diagnostics"]
    assert float(result["weighted_loss"].detach()) == expected_loss
    result["weighted_loss"].backward()
    assert torch.equal(start.grad, torch.tensor([[.125, -.125, 0., 0.], [0., 0., 0., 0.]]))
    assert torch.equal(end.grad, torch.tensor([end_gradient, [0., 0., 0., 0.]], dtype=torch.float32))
    assert torch.equal(start.detach(), start_before) and torch.equal(end.detach(), end_before) and labels == labels_before
    zero = subject.conditions_fullspan_margin_from_logits(torch, start, end, labels, weight=0)
    assert zero["margin_computed"] is False and zero["row_diagnostics"] == []
    before_start, before_end = start.grad.clone(), end.grad.clone()
    zero["weighted_loss"].backward()
    assert torch.equal(start.grad, before_start) and torch.equal(end.grad, before_end)
    assert torch.is_grad_enabled() == grad_mode_before and torch.equal(torch.get_rng_state(), rng_before)


@pytest.mark.parametrize("starts, ends, label, wrong, end_gradient", [
    ([0., 0., 0.], [0., 0., 0.], target(span=(0, 0)), [0, 1], [-.25, .25, 0.]),
    ([-0., 0., 0.], [0., -0., 0.], target(span=(0, 0)), [0, 1], [-.25, .25, 0.]),
    ([3e38, -3e38], [3e38, -3e38], target(1, span=(0, 0)), None, [0., 0.]),
    ([16777216., 0.], [0., 0.], target(2, span=(0, 0)), [0, 1], [0., 0.]),
])
def test_tensor_ties_singleton_and_float32_association_match_scalar(starts, ends, label, wrong, end_gradient):
    import torch
    start = torch.tensor([starts], dtype=torch.float32, requires_grad=True)
    end = torch.tensor([ends], dtype=torch.float32, requires_grad=True)
    result = subject.conditions_fullspan_margin_from_logits(torch, start, end, [label])
    reference = subject.conditions_fullspan_margin_reference([starts], [ends], [label])
    assert result["row_diagnostics"] == reference["row_diagnostics"]
    assert result["row_diagnostics"][0]["wrong_span"] == wrong
    assert float(result["weighted_loss"].detach()) == reference["weighted_loss"]
    result["weighted_loss"].backward()
    assert torch.equal(start.grad, torch.zeros_like(start))
    assert torch.equal(end.grad, torch.tensor([end_gradient], dtype=torch.float32))
