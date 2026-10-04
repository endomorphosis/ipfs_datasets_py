"""Qualify the actual packed autograd executor on CPU, using synthetic inputs."""
from copy import deepcopy
from dataclasses import replace
import importlib.util
import math
from pathlib import Path
from unittest.mock import patch

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_cuda as native

_spec = importlib.util.spec_from_file_location(
    "native_cuda_training_fixture", Path(__file__).with_name("test_modal_autoencoder_cuda_training.py"))
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)
TARGETS = ("family_logits", "decoded_embedding", "legal_ir_view_logits")


def model():
    return _fixture._autoencoder("python")


def update(value, samples=None, *, targets=TARGETS, rate=0.025, l2=0.0):
    samples = _fixture._samples() if samples is None else samples
    tx = value.state.transaction(label="native-packed-cpu-test").begin()
    try:
        report = native.apply_cpu_reference_projection_update(
            value, samples, update_targets=targets, learning_rate=rate, l2_regularization=l2)
        touched = tx.touched_row_count
        if report.applied:
            tx.commit()
        else:
            tx.rollback()
        return report, touched
    except BaseException:
        if tx.active:
            tx.rollback()
        raise


def test_same_native_step_has_gradients_sgd_and_shared_changes(monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_MODAL_AUTOENCODER_CUDA_MAX_GRAD_NORM", "0.01")
    value = model()
    before = deepcopy(value.state.to_dict())
    captured = []
    scatter = native._scatter_blocks

    def inspect_then_scatter(autoencoder, session):
        for block in session.blocks.values():
            parameter = block.parameter
            assert parameter.grad is not None and torch.isfinite(parameter.grad).all()
            assert torch.allclose(parameter, block.initial - 0.025 * parameter.grad, atol=1e-7, rtol=1e-6)
            captured.append((float(parameter.grad.square().sum()), bool(torch.any(parameter != block.initial))))
        return scatter(autoencoder, session)

    def forbidden(*args, **kwargs):
        raise AssertionError("historical nudge path must not execute")

    with patch.object(native, "_scatter_blocks", side_effect=inspect_then_scatter), \
         patch.object(value, "_nudge_family_logits", side_effect=forbidden), \
         patch.object(value, "_nudge_decoded_embedding", side_effect=forbidden), \
         patch.object(value, "_nudge_legal_ir_view_logits", side_effect=forbidden):
        report, touched = update(value)
    assert report.admitted and report.applied and report.optimizer_step == 1
    assert report.gradient_norm > 0 and 0 < report.clipped_gradient_norm <= 0.010001
    assert sum(g for g, _ in captured) > 0 and any(changed for _, changed in captured)
    assert touched > 0
    after = value.state.to_dict()
    assert before["family_embedding_weights"] != after["family_embedding_weights"]
    assert before["compiler_quality_family_logits"] != after["compiler_quality_family_logits"]


@pytest.mark.parametrize("l2", [0.0, 2.0])
@pytest.mark.parametrize("sample_count", [2, 3])
def test_global_microbatch_normalization_including_l2(monkeypatch, l2, sample_count):
    # Use nonzero canonical weights so an accidentally repeated L2 term matters.
    seed = model()
    first, _ = update(seed)
    assert first.applied
    left, right = model(), model()
    left.state = type(seed.state).from_dict(seed.state.to_dict())
    right.state = type(seed.state).from_dict(seed.state.to_dict())
    monkeypatch.setenv("IPFS_DATASETS_MODAL_AUTOENCODER_CUDA_MAX_GRAD_NORM", "100")
    monkeypatch.setenv("IPFS_DATASETS_MODAL_AUTOENCODER_CUDA_GRADIENT_ACCUMULATION_STEPS", "1")
    samples = (_fixture._samples() * 2)[:sample_count]
    a, _ = update(left, samples, l2=l2)
    monkeypatch.setenv("IPFS_DATASETS_MODAL_AUTOENCODER_CUDA_GRADIENT_ACCUMULATION_STEPS", "2")
    b, _ = update(right, samples, l2=l2)
    assert a.applied and b.applied
    assert a.gradient_accumulation_steps == 1 and b.gradient_accumulation_steps == 2
    assert a.losses["l2"] == pytest.approx(b.losses["l2"], abs=1e-12, rel=1e-5)
    assert a.losses == pytest.approx(b.losses, abs=1e-6, rel=1e-5)
    assert a.gradient_norm == pytest.approx(b.gradient_norm, abs=1e-6, rel=1e-5)
    for name in ("family_embedding_weights", "compiler_quality_family_logits", "legal_ir_view_logits"):
        one, two = getattr(left.state, name), getattr(right.state, name)
        assert set(one) == set(two)
        for key in one:
            assert one[key] == pytest.approx(two[key], abs=1e-6, rel=1e-5)


@pytest.mark.parametrize("enabled", [True, False])
def test_fully_masked_legal_objective_is_finite_explicit_noop(enabled):
    value = model()
    value.legal_ir_view_logit_scale = 1.0 if enabled else 0.0
    # Keep candidate columns present even though every target is masked.
    value.state.legal_ir_view_logits["TDFOL.prover"] = 0.0
    value.state.legal_ir_view_logits["CEC.native"] = 0.0
    before = deepcopy(value.state.to_dict())
    with patch.object(value, "_legal_ir_view_target_distribution_for_sample", return_value={}):
        report, touched = update(value, targets=("legal_ir_view_global_logits",))
    assert report.applied and report.admitted
    assert math.isfinite(report.losses["total"]) and report.losses["total"] == 0.0
    assert report.gradient_norm == 0.0
    assert value.state.to_dict() == before
    assert touched == 0


def test_zero_norm_embeddings_do_not_create_nonfinite_update():
    value = model()
    samples = [replace(s, embedding_vector=[0.0] * len(s.embedding_vector)) for s in _fixture._samples()]
    report, _ = update(value, samples)
    assert report.applied and all(math.isfinite(v) for v in report.losses.values())
    assert math.isfinite(report.gradient_norm) and math.isfinite(report.clipped_gradient_norm)


def test_nonfinite_loss_rejects_without_canonical_mutation():
    value = model()
    before = deepcopy(value.state.to_dict())
    samples = [replace(s, embedding_vector=[float("nan")] * len(s.embedding_vector)) for s in _fixture._samples()]
    report, _ = update(value, samples)
    assert not report.applied and not report.admitted
    assert "FloatingPointError" in report.fallback_reason
    assert value.state.to_dict() == before


def test_zero_rate_does_not_scatter_unchanged_or_insert_zero_rows():
    value = model()
    before = deepcopy(value.state.to_dict())
    report, touched = update(value, rate=0.0)
    assert report.applied and report.gradient_norm > 0
    assert value.state.to_dict() == before
    assert touched == 0


def test_real_packed_update_rolls_back_exactly():
    value = model()
    before = deepcopy(value.state.to_dict())
    tx = value.state.transaction(label="actual-packed-rollback").begin()
    report = native.apply_cpu_reference_projection_update(
        value, _fixture._samples(), update_targets=TARGETS, learning_rate=0.025)
    assert report.applied and report.gradient_norm > 0 and tx.touched_row_count > 0
    assert value.state.to_dict() != before
    tx.rollback()
    assert value.state.to_dict() == before


def test_nonfinite_autograd_gradient_rejects_before_scatter():
    value = model()
    before = deepcopy(value.state.to_dict())
    original = native._ResidentTrainingSession.create.__func__

    def poisoned_gradient(cls, *args, **kwargs):
        session = original(cls, *args, **kwargs)
        # Fault injection at a real autograd boundary; forward loss stays finite.
        session.parameters[0].register_hook(lambda grad: grad * float("inf"))
        return session

    with patch.object(native._ResidentTrainingSession, "create", classmethod(poisoned_gradient)):
        report, touched = update(value)
    assert not report.applied and not report.admitted
    assert "FloatingPointError" in report.fallback_reason
    assert touched == 0 and value.state.to_dict() == before


def test_actual_packed_checkpoint_reload_then_second_update():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import (
        serialize_checkpoint, deserialize_checkpoint)
    value = model()
    first, _ = update(value)
    assert first.applied and first.gradient_norm > 0
    loaded = deserialize_checkpoint(serialize_checkpoint(value.state))
    assert loaded.state.to_dict() == value.state.to_dict()
    reloaded = model()
    reloaded.state = loaded.state
    a, _ = update(value)
    b, _ = update(reloaded)
    assert a.applied and b.applied and a.gradient_norm > 0 and b.gradient_norm > 0
    assert a.losses == b.losses
    assert reloaded.state.to_dict() == value.state.to_dict()


def test_outer_trainer_explicit_packed_cpu_runs_real_update_without_nudges():
    value = model()
    samples = _fixture._samples()
    before = deepcopy(value.state.to_dict())
    calls = []
    executor = native.apply_cpu_reference_projection_update

    def witness(*args, **kwargs):
        old = deepcopy(value.state.to_dict())
        result = executor(*args, **kwargs)
        calls.append((result.gradient_norm, value.state.to_dict() != old))
        return result

    def forbidden(*args, **kwargs):
        raise AssertionError("historical nudge fallback is forbidden")

    with patch.object(native, "apply_cpu_reference_projection_update", side_effect=witness), \
         patch.object(value, "_nudge_family_logits", side_effect=forbidden), \
         patch.object(value, "_nudge_decoded_embedding", side_effect=forbidden), \
         patch.object(value, "_nudge_legal_ir_view_logits", side_effect=forbidden):
        result = value.train_generalizable_projection(
            samples, validation_samples=samples, epochs=1, learning_rate=0.025,
            projection_update_backend="packed_cpu",
            max_line_search_attempts=1, legal_ir_evaluate_provers=False)
    assert result["projection_update_backend"] == "packed_cpu"
    assert result["projection_packed_cpu"]["enabled"]
    assert not result["projection_cuda_residency"]["enabled"]
    assert calls and any(norm > 0 and changed for norm, changed in calls)
    assert result["accepted_epochs"] == 1
    assert value.state.to_dict() != before
    assert value.state.family_logits == before["family_logits"]
    assert value.state.decoded_embeddings == before["decoded_embeddings"]


def test_outer_packed_cpu_rejection_rolls_back_without_legacy_fallback():
    value = model()
    before = deepcopy(value.state.to_dict())
    failure = native.CudaResidencyReport(admitted=False, applied=False,
                                         fallback_reason="torch_unavailable")
    with patch.object(native, "apply_cpu_reference_projection_update", return_value=failure):
        with pytest.raises(RuntimeError, match="packed CPU update rejected: torch_unavailable"):
            value.train_generalizable_projection(
                _fixture._samples(), epochs=1, projection_update_backend="packed_cpu",
                projection_max_update_families=1, max_line_search_attempts=1,
                legal_ir_evaluate_provers=False)
    assert value.state.to_dict() == before
    assert value.state._active_state_transaction is None
