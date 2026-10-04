"""V4 owner admission and archive boundaries; no actual native tool executes."""
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import resumable_native_validation as previous
from ipfs_datasets_py.logic.formalization.autoencoder import resumable_native_validation_v2 as api
from ipfs_datasets_py.logic.formalization.autoencoder import parallel_projection_checks_v2 as v2
from ipfs_datasets_py.logic.formalization.autoencoder import parallel_projection_checks_v3 as v3
from ipfs_datasets_py.logic.formalization.autoencoder import parallel_projection_checks_v4 as checks
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


@pytest.mark.parametrize("module", (v2, v3, checks))
def test_exact_reviewed_native_owners_remain_explicit(module):
    owner = api.NativeValidationOwner.from_module(module)
    assert api._resolve_owner(owner) is module
    assert owner.native_schema == module.native.SCHEMA
    assert owner.validation_schema == module.validation.SCHEMA
    assert owner.producer_sha256 == tuple(sorted(module._PINS.items()))


def test_old_resumer_does_not_implicitly_acquire_new_execution_owner():
    with pytest.raises(ValueError, match="versioned native parallel owner"):
        previous.NativeValidationOwner.from_module(checks)
    owner = previous.NativeValidationOwner.from_module(v3)
    with pytest.raises(ValueError, match="typed immutable"):
        api._resolve_owner(owner)
    assert api.SCHEMA != previous.SCHEMA


@pytest.mark.parametrize("fake", (SimpleNamespace(), ModuleType(checks.__name__), ModuleType("unreviewed")))
def test_arbitrary_or_impersonated_callback_namespaces_rejected(fake):
    with pytest.raises(ValueError):
        api.NativeValidationOwner.from_module(fake)


@pytest.mark.parametrize("field", ("source_sha256", "policy_sha256", "schema", "native_schema", "validation_schema"))
def test_modified_descriptor_cannot_restore_authority(field):
    owner = api.NativeValidationOwner.from_module(checks)
    with pytest.raises(ValueError, match="owner or fixed policy drift"):
        api._resolve_owner(replace(owner, **{field: "unrelated"}))
    with pytest.raises(ValueError, match="typed immutable"):
        api._resolve_owner(dict(owner.__dict__))


def test_lease_only_retry_rejects_granted_or_saved_success(tmp_path):
    events = [{"job_id": "a", "phase": "lease_wait_started"},
        {"job_id": "a", "phase": "lease_wait_timeout", "exact_scheduler_timeout_type": True,
         "lease_granted": False}]
    failed = {"job_id": "a", "status": "failed", "error_type": "LeaseTimeoutError"}
    assert api._retryable("a", failed, events, tmp_path)
    assert not api._retryable("a", {**failed, "native": {}}, events, tmp_path)
    assert not api._retryable("a", {**failed, "status": "completed"}, events, tmp_path)
    assert not api._retryable("a", failed,
        [*events, {"job_id": "a", "phase": "lease_granted", "lease_granted": True}], tmp_path)
    (tmp_path / "a").mkdir()
    assert not api._retryable("a", failed, events, tmp_path)


def test_saved_completion_is_archive_only_on_resume(monkeypatch, tmp_path):
    # Explicit scheduler orchestration double: never a Lake command or proof.
    owner = api.NativeValidationOwner.from_module(checks)
    calls = []
    def execute(jobs, *, output_directory, **kwargs):
        calls.append([job.job_id for job in jobs])
        Path(output_directory).mkdir()
        return {"jobs": [{"job_id": job.job_id, "receipt": {"job_id": job.job_id,
            "status": "completed", "test_scope": "orchestration_double_no_native_execution",
            "native": {"backend_executed": False}, **api.FALSE},
            "native_execution": object(), "observation": object()} for job in jobs]}
    harness = SimpleNamespace(NativeProjectionJob=checks.NativeProjectionJob,
        _identifier=checks._identifier, _seconds=checks._seconds,
        MAX_ITEM_BYTES=checks.MAX_ITEM_BYTES, MAX_BATCH_BYTES=checks.MAX_BATCH_BYTES,
        run_parallel_projection_checks=execute)
    monkeypatch.setattr(api, "_resolve_owner", lambda supplied: harness)
    scheduler = api.resources.GlobalResourceScheduler(api.resources.ResourceSchedulerConfig(
        total_cpu_slots=2, total_memory_mb=2048, total_child_process_slots=2,
        state_path=tmp_path / "scheduler.json", lane_reservations={}, proof_safety_enabled=True,
        proof_resource_sampler=lambda: ProofHostResources(2, 2048, 2048), proof_backoff_seconds=0))
    jobs = [checks.NativeProjectionJob("a", {"domain_id": "ui_ux_ir", "source_digest": "0" * 64},
        {"source_text": "unit declaration only", "candidate": {}})]
    kwargs = dict(owner=owner, output_directory=tmp_path / "run", scheduler=scheduler,
        lake_executable="not-executed", max_admission_seconds=5, retry_backoff_seconds=0)
    first = api.run_resumable_native_validation(jobs, **kwargs)
    assert len(first["live_jobs"]) == 1
    restored = api.run_resumable_native_validation(jobs, resume=True, **kwargs)
    assert calls == [["a"]]
    assert restored["live_jobs"] == [] and len(restored["archived_jobs"]) == 1
    assert "native_execution" not in restored["archived_jobs"][0]
    assert not restored["receipt"]["live_validation_complete"]
    assert not restored["receipt"]["archived_receipts_are_live_authority"]
    assert all(restored["receipt"][key] is False for key in api.FALSE)
