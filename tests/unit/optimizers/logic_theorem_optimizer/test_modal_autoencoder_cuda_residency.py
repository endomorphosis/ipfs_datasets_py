"""CUDA residency and deterministic fallback tests for modal autoencoder updates."""

from __future__ import annotations

import json
from types import SimpleNamespace

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_cuda import (
    CUDA_RESIDENCY_SCHEMA_VERSION,
    CudaResidentBatchState,
    CudaResidencyReport,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.projection_profiler import (
    ProjectionProfiler,
)


def _samples():
    return [
        build_us_code_sample(
            title="5",
            section="552-cuda-resident",
            text="The agency shall provide notice before the permit takes effect.",
        ),
        build_us_code_sample(
            title="12",
            section="1841-cuda-resident",
            text="The applicant may appeal unless the board denies jurisdiction.",
        ),
    ]


def _stable_training_payload(report):
    return {
        "accepted_epochs": report["accepted_epochs"],
        "after": report["after"],
        "before": report["before"],
        "candidate_update_order": report["candidate_update_order"],
        "sample_memory_used": report["sample_memory_used"],
    }


def test_cuda_resident_backend_falls_back_deterministically_without_cuda() -> None:
    samples = _samples()
    validation = list(samples)
    native = AdaptiveModalAutoencoder(compute_device="python")
    resident = AdaptiveModalAutoencoder(compute_device="python")
    profiler = ProjectionProfiler(enabled=True)

    native_report = native.train_generalizable_projection(
        samples,
        validation_samples=validation,
        epochs=1,
        learning_rate=0.2,
        max_line_search_attempts=2,
        projection_update_backend="native",
    )
    resident_report = resident.train_generalizable_projection(
        samples,
        validation_samples=validation,
        epochs=1,
        learning_rate=0.2,
        max_line_search_attempts=2,
        projection_profiler=profiler,
        projection_update_backend="cuda_resident",
    )

    assert json.dumps(
        _stable_training_payload(resident_report),
        sort_keys=True,
    ) == json.dumps(
        _stable_training_payload(native_report),
        sort_keys=True,
    )
    assert resident_report["projection_update_backend"] == "cuda_resident"
    residency = resident_report["projection_cuda_residency"]
    assert residency["schema_version"] == CUDA_RESIDENCY_SCHEMA_VERSION
    assert residency["enabled"] is True
    assert residency["reports"]
    assert any(not report["admitted"] for report in residency["reports"])
    assert (
        resident_report["projection_profile"]["counters"][
            "cuda_resident_deterministic_fallback_count"
        ]
        >= 1
    )


def test_cuda_admission_reports_unavailable_backend_without_state_mutation() -> None:
    class _FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return False

    fake_torch = SimpleNamespace(cuda=_FakeCuda())
    autoencoder = AdaptiveModalAutoencoder(compute_device="python")
    autoencoder.compute_backend = "torch_cuda"
    autoencoder.compute_device = "cuda"
    autoencoder._torch = fake_torch
    before = autoencoder.state.to_dict()
    profiler = ProjectionProfiler(enabled=True)

    state, report = CudaResidentBatchState.admit(
        autoencoder,
        _samples(),
        update_targets=("family_logits", "legal_ir_view_logits"),
        profiler=profiler,
    )

    assert state is None
    assert report.admitted is False
    assert report.applied is False
    assert report.fallback_reason == "cuda_unavailable"
    assert autoencoder.state.to_dict() == before
    assert profiler.summarize()["counters"]["cuda_resident_fallback_count"] == 1


def test_cuda_residency_report_serializes_transfer_and_sync_counters() -> None:
    report = CudaResidencyReport(
        admitted=True,
        applied=True,
        mixed_precision_checked=True,
        mixed_precision_safe=True,
        resident_cache_hit=True,
        transfer_count=1,
        transfer_bytes=256,
        synchronization_count=0,
        kernel_launch_count=2,
        update_targets=["family_logits", "semantic_slots", "proof_auxiliary_heads"],
    )

    payload = report.to_dict()

    assert payload["schema_version"] == CUDA_RESIDENCY_SCHEMA_VERSION
    assert payload["mixed_precision_checked"] is True
    assert payload["mixed_precision_safe"] is True
    assert payload["transfer_count"] == 1
    assert payload["synchronization_count"] == 0
    assert payload["kernel_launch_count"] == 2
    assert "proof_auxiliary_heads" in payload["update_targets"]
