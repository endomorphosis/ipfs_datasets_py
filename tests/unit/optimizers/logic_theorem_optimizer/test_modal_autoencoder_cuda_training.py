"""True packed CUDA training tests for the modal autoencoder."""

from __future__ import annotations

import math
from unittest.mock import patch

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_cuda import (
    CUDA_TRAINING_SCHEMA_VERSION,
    apply_cpu_reference_projection_update,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.projection_profiler import (
    ProjectionProfiler,
)


torch = pytest.importorskip("torch")


def _samples():
    return [
        build_us_code_sample(
            title="5",
            section="552-cuda-training",
            text="The agency shall provide notice before the permit takes effect.",
        ),
        build_us_code_sample(
            title="12",
            section="1841-cuda-training",
            text="The applicant may appeal unless the board denies jurisdiction.",
        ),
    ]


def _autoencoder(device: str) -> AdaptiveModalAutoencoder:
    # Keep the fixture intentionally small while exercising every loss family:
    # family embeddings drive MSE/cosine, compiler-quality rows drive modal CE,
    # and the global LegalIR row drives auxiliary LegalIR CE.
    return AdaptiveModalAutoencoder(
        compute_device=device,
        compiler_quality_embedding_weight_scale=0.0,
        logic_signature_embedding_weight_scale=0.0,
        round_trip_signal_embedding_weight_scale=0.0,
        decompiler_plan_embedding_weight_scale=0.0,
        predicate_argument_embedding_weight_scale=0.0,
        feature_embedding_weight_scale=0.0,
        family_embedding_weight_scale=1.0,
        family_semantic_slot_embedding_weight_scale=0.0,
        family_semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        family_legal_ir_view_embedding_weight_scale=0.0,
        semantic_slot_embedding_weight_scale=0.0,
        semantic_slot_legal_ir_view_embedding_weight_scale=0.0,
        legal_ir_view_embedding_weight_scale=0.0,
        compiler_quality_family_logit_scale=1.0,
        logic_signature_family_logit_scale=0.0,
        round_trip_signal_family_logit_scale=0.0,
        decompiler_plan_family_logit_scale=0.0,
        predicate_argument_family_logit_scale=0.0,
        feature_family_logit_scale=0.0,
        semantic_slot_family_logit_scale=0.0,
        legal_ir_view_family_logit_scale=0.0,
        semantic_slot_legal_ir_view_family_logit_scale=0.0,
        logic_signature_legal_ir_view_logit_scale=0.0,
        round_trip_signal_legal_ir_view_logit_scale=0.0,
        decompiler_plan_legal_ir_view_logit_scale=0.0,
        predicate_argument_legal_ir_view_logit_scale=0.0,
        semantic_slot_legal_ir_view_logit_scale=0.0,
        family_semantic_slot_legal_ir_view_logit_scale=0.0,
    )


def _packed_update(autoencoder, samples, *, backend="cuda_resident"):
    transaction = autoencoder.state.transaction(label=f"test-{backend}").begin()
    try:
        if backend == "cuda_resident":
            result = autoencoder._apply_projection_update_batch_in_transaction(
                samples,
                update_targets=(
                    "family_logits",
                    "decoded_embedding",
                    "legal_ir_view_logits",
                ),
                learning_rate=0.025,
                l2_regularization=0.0,
                update_backend=backend,
            )
            report = result["backend_report"]
        else:
            report = apply_cpu_reference_projection_update(
                autoencoder,
                samples,
                update_targets=(
                    "family_logits",
                    "decoded_embedding",
                    "legal_ir_view_logits",
                ),
                learning_rate=0.025,
            ).to_dict()
        transaction.commit()
        return report, transaction
    except BaseException:
        if transaction.active:
            transaction.rollback()
        raise


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is unavailable")
def test_cuda_training_never_invokes_legacy_apply_and_reports_real_work(monkeypatch) -> None:
    monkeypatch.setenv("IPFS_DATASETS_MODAL_AUTOENCODER_CUDA_GRADIENT_ACCUMULATION_STEPS", "2")
    monkeypatch.setenv("IPFS_DATASETS_MODAL_AUTOENCODER_CUDA_MAX_GRAD_NORM", "0.01")
    autoencoder = _autoencoder("cuda")
    samples = _samples()
    profiler = ProjectionProfiler(enabled=True)
    transaction = autoencoder.state.transaction(label="forbid-legacy").begin()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("legacy Python apply path was invoked")

    with (
        patch.object(autoencoder, "_nudge_family_logits", side_effect=forbidden),
        patch.object(autoencoder, "_nudge_decoded_embedding", side_effect=forbidden),
        patch.object(autoencoder, "_nudge_legal_ir_view_logits", side_effect=forbidden),
    ):
        result = autoencoder._apply_projection_update_batch_in_transaction(
            samples,
            update_targets=(
                "family_logits",
                "decoded_embedding",
                "legal_ir_view_logits",
            ),
            learning_rate=0.025,
            l2_regularization=0.0,
            profiler=profiler,
            update_backend="cuda_resident",
        )
    transaction.commit()

    report = result["backend_report"]
    assert report["admitted"] is True
    assert report["applied"] is True
    assert report["training_schema_version"] == CUDA_TRAINING_SCHEMA_VERSION
    assert report["gradient_accumulation_steps"] == 2
    assert report["gradient_norm"] > 0.0
    assert report["clipped_gradient_norm"] <= 0.010001
    assert report["kernel_launch_count"] > 10
    assert report["transfer_count"] >= 3
    assert report["transfer_bytes"] > 0
    assert report["synchronization_count"] > 0
    assert report["optimizer_state_resident"] is True
    assert report["parameter_count"] > 0
    assert report["loss_dtype"] == str(torch.float32)
    assert report["losses"]["cross_entropy"] > 0.0
    assert report["losses"]["legal_ir_cross_entropy"] > 0.0
    assert report["losses"]["reconstruction"] > 0.0
    assert report["losses"]["cosine"] >= 0.0
    assert math.isfinite(report["losses"]["guarded_auxiliary"])
    assert transaction.touched_row_count > 0
    resident = autoencoder._cuda_resident_projection_state
    assert resident.packed_parameter_tensors
    assert all(
        tensor.is_cuda and tensor.is_contiguous()
        for tensor in resident.packed_parameter_tensors.values()
    )
    assert resident.optimizer_state_tensors
    assert all(tensor.is_cuda for tensor in resident.optimizer_state_tensors)
    counters = profiler.summarize()["counters"]
    assert counters["cuda_resident_optimizer_step_count"] == 1
    assert counters["cuda_resident_gradient_accumulation_step_count"] == 2


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is unavailable")
def test_cuda_matches_fixed_cpu_packed_reference(monkeypatch) -> None:
    monkeypatch.setenv("IPFS_DATASETS_MODAL_AUTOENCODER_CUDA_MIXED_PRECISION", "0")
    monkeypatch.setenv("IPFS_DATASETS_MODAL_AUTOENCODER_CUDA_MAX_GRAD_NORM", "10")
    samples = _samples()
    cuda_autoencoder = _autoencoder("cuda")
    cpu_autoencoder = _autoencoder("python")

    cuda_report, _ = _packed_update(cuda_autoencoder, samples)
    cpu_report, _ = _packed_update(cpu_autoencoder, samples, backend="cpu")

    assert cuda_report["applied"] is True
    assert cpu_report["applied"] is True
    assert cuda_report["losses"]["total"] == pytest.approx(
        cpu_report["losses"]["total"], abs=5.0e-6
    )
    for component in (
        "family_embedding_weights",
        "compiler_quality_family_logits",
        "legal_ir_view_logits",
    ):
        cuda_values = getattr(cuda_autoencoder.state, component)
        cpu_values = getattr(cpu_autoencoder.state, component)
        assert set(cuda_values) == set(cpu_values)
        for key, cuda_value in cuda_values.items():
            cpu_value = cpu_values[key]
            if isinstance(cuda_value, dict):
                assert dict(cuda_value) == pytest.approx(dict(cpu_value), abs=5.0e-6)
            elif isinstance(cuda_value, list):
                assert list(cuda_value) == pytest.approx(list(cpu_value), abs=5.0e-6)
            else:
                assert float(cuda_value) == pytest.approx(float(cpu_value), abs=5.0e-6)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is unavailable")
def test_optimizer_state_and_parameters_remain_resident_across_batches(monkeypatch) -> None:
    monkeypatch.setenv("IPFS_DATASETS_MODAL_AUTOENCODER_CUDA_MIXED_PRECISION", "0")
    autoencoder = _autoencoder("cuda")
    samples = _samples()

    first, _ = _packed_update(autoencoder, samples)
    resident = autoencoder._cuda_resident_projection_state
    session_ids = {
        signature: (id(session), id(session.step_tensor))
        for signature, session in resident.training_sessions.items()
    }
    second, _ = _packed_update(autoencoder, samples)

    assert first["optimizer_step"] == 1
    assert second["optimizer_step"] == 2
    assert second["resident_cache_hit"] is True
    assert autoencoder._cuda_resident_projection_state is resident
    assert session_ids == {
        signature: (id(session), id(session.step_tensor))
        for signature, session in resident.training_sessions.items()
    }


@pytest.mark.skipif(
    not torch.cuda.is_available() or not torch.cuda.is_bf16_supported(),
    reason="CUDA BF16 is unavailable",
)
def test_bf16_activations_are_guarded_while_loss_reductions_remain_fp32(monkeypatch) -> None:
    monkeypatch.setenv("IPFS_DATASETS_MODAL_AUTOENCODER_CUDA_MIXED_PRECISION", "1")
    monkeypatch.setenv(
        "IPFS_DATASETS_MODAL_AUTOENCODER_CUDA_MIXED_PRECISION_TOLERANCE",
        "0.02",
    )
    report, _ = _packed_update(_autoencoder("cuda"), _samples())

    assert report["mixed_precision_checked"] is True
    assert report["mixed_precision_safe"] is True
    assert report["activation_dtype"] == str(torch.bfloat16)
    assert report["parameter_dtype"] == str(torch.float32)
    assert report["loss_dtype"] == str(torch.float32)
