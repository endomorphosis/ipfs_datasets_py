"""Retry state-machine tests: real scheduler, explicitly fake native owner.

No test double is reported as actual Lake execution or live proof authority.
Owner-contract tests exercise the real versioned owner separately.
"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import resumable_native_validation as api
from ipfs_datasets_py.logic.formalization.autoencoder import parallel_projection_checks_v2 as checks
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


def job(identity):
    return checks.NativeProjectionJob(identity,
        {"domain_id": "intent_ir", "source_digest": identity * 64, "fixture": "scheduler-unit-not-native-target"},
        {"source_text": "Unit source " + identity}, ())


@pytest.fixture
def scheduler(tmp_path):
    return api.resources.GlobalResourceScheduler(api.resources.ResourceSchedulerConfig(
        total_cpu_slots=2, total_memory_mb=2048, total_child_process_slots=2,
        state_path=tmp_path / "scheduler.json", lane_reservations={}, proof_safety_enabled=True,
        proof_resource_sampler=lambda: ProofHostResources(2, 2048, 2048), proof_backoff_seconds=0))


@pytest.fixture
def fake_owner(monkeypatch):
    actual_contract = api.NativeValidationOwner.from_module(checks)
    state = {"calls": [], "native_calls": [], "before": None, "after": None, "failure": None}

    def run(jobs, *, scheduler, output_directory, **options):
        state["calls"].append([row.job_id for row in jobs])
        output = Path(output_directory)
        output.mkdir()
        rows = []
        for item in jobs:
            identity = item.job_id
            try:
                if state["before"] is not None:
                    state["before"](identity, output)
                with scheduler.acquire(api.resources.ResourceLane.VALIDATION,
                        cpu_slots=options["native_cpu_slots"], memory_mb=options["native_memory_mb"],
                        child_process_slots=options["native_child_process_slots"],
                        timeout=options["lease_wait_timeout_seconds"], request_id="native:" + identity):
                    state["native_calls"].append(identity)
                    if state["failure"] is not None:
                        state["failure"](identity)
                    destination = output / identity
                    destination.mkdir()
                    receipt = {"job_id": identity, "status": "completed", "native_status": "partial",
                        "test_scope": "fake-native-owner-no-Lake", "native": {"backend_executed": False}, **api.FALSE}
                    (destination / "receipt.json").write_text(json.dumps(receipt))
                    rows.append({"job_id": identity, "receipt": receipt,
                        "native_execution": object(), "observation": object()})
            except Exception as error:
                rows.append({"job_id": identity, "receipt": {"job_id": identity, "status": "failed",
                    "error_type": type(error).__name__, "reason": str(error), **api.FALSE}})
        (output / "receipt.json").write_text(json.dumps({"jobs": [row["receipt"] for row in rows]}))
        if state["after"] is not None:
            state["after"](state)
        return {"jobs": rows}

    # Explicit owner adapter double isolates retry orchestration. Public owner
    # construction and strict type rejection are tested without this patch.
    harness = SimpleNamespace(NativeProjectionJob=checks.NativeProjectionJob,
        _identifier=checks._identifier, _seconds=checks._seconds,
        MAX_ITEM_BYTES=checks.MAX_ITEM_BYTES, MAX_BATCH_BYTES=checks.MAX_BATCH_BYTES,
        run_parallel_projection_checks=run)
    monkeypatch.setattr(api, "_resolve_owner", lambda owner: harness)
    state["contract"] = actual_contract
    return state


def run(tmp_path, scheduler, fake_owner, jobs=None, **options):
    return api.run_resumable_native_validation(jobs or [job("a")], owner=fake_owner["contract"],
        output_directory=tmp_path / "campaign", scheduler=scheduler, lake_executable="unit-not-executed",
        native_cpu_slots=1, native_memory_mb=128, native_child_process_slots=1,
        lease_wait_timeout_seconds=.01, retry_backoff_seconds=0, max_admission_seconds=5, **options)


def hold(scheduler):
    return scheduler.acquire(api.resources.ResourceLane.TRAINER,
        cpu_slots=2, memory_mb=128, child_process_slots=2, timeout=.1)


def test_real_owner_contract_rejects_namespaces_and_detects_changed_descriptor():
    with pytest.raises(ValueError, match="versioned native parallel owner"):
        api.NativeValidationOwner.from_module(SimpleNamespace())
    contract = api.NativeValidationOwner.from_module(checks)
    assert api._resolve_owner(contract) is checks
    fields = dict(contract.__dict__, source_sha256="0" * 64)
    with pytest.raises(ValueError, match="owner or fixed policy drift"):
        api._resolve_owner(api.NativeValidationOwner(**fields))
    with pytest.raises(ValueError, match="typed immutable"):
        api._resolve_owner(dict(contract.__dict__))


def test_actual_scheduler_timeout_then_recovery_preserves_both_attempts(tmp_path, scheduler, fake_owner):
    lease = hold(scheduler)
    fake_owner["after"] = lambda state: lease.release()
    result = run(tmp_path, scheduler, fake_owner)
    assert fake_owner["calls"] == [["a"], ["a"]] and fake_owner["native_calls"] == ["a"]
    assert result["receipt"]["status"] == "completed" and len(result["live_jobs"]) == 1
    first = api._read(tmp_path / "campaign/round-0000/result.json")
    assert first["jobs"][0]["retryable_lease_timeout"]
    assert [row["phase"] for row in first["lease_events"]] == ["lease_wait_started", "lease_wait_timeout"]
    assert first["lease_events"][-1]["exact_scheduler_timeout_type"] is True
    assert first["lease_events"][-1]["telemetry"]["scheduler"]["active_root_lease_count"] == 1
    assert scheduler.snapshot()["active_lease_count"] == 0
    assert all(result["receipt"][key] is False for key in api.FALSE)


def test_only_failed_subset_retries_and_successful_native_work_is_not_repeated(tmp_path, scheduler, fake_owner):
    leases = []

    def before(identity, output):
        if identity == "b" and len(fake_owner["calls"]) == 1:
            leases.append(hold(scheduler))

    fake_owner["before"] = before
    fake_owner["after"] = lambda state: [lease.release() for lease in leases]
    result = run(tmp_path, scheduler, fake_owner, [job("a"), job("b")])
    assert fake_owner["calls"] == [["a", "b"], ["b"]]
    assert fake_owner["native_calls"] == ["a", "b"]
    assert [row["job_id"] for row in result["live_jobs"]] == ["a", "b"]


def test_identically_worded_arbitrary_admission_error_is_not_retryable(tmp_path, scheduler, fake_owner, monkeypatch):
    def reject(*args, **kwargs):
        raise RuntimeError("timed out waiting for a resource lease")

    monkeypatch.setattr(scheduler, "acquire", reject)
    result = run(tmp_path, scheduler, fake_owner)
    assert fake_owner["calls"] == [["a"]] and not fake_owner["native_calls"]
    assert not result["archived_jobs"][0]["retryable_lease_timeout"]
    assert result["receipt"]["status"] == "incomplete"
    first = api._read(tmp_path / "campaign/round-0000/result.json")
    assert first["lease_events"][-1]["phase"] == "lease_admission_failed"


@pytest.mark.parametrize("error", [api.resources.LeaseTimeoutError("timed out waiting for a resource lease"),
    ValueError("native parser rejected formula"), RuntimeError("Lake failed")])
def test_after_grant_failure_never_retries_even_with_timeout_type(tmp_path, scheduler, fake_owner, error):
    def fail(identity):
        raise error

    fake_owner["failure"] = fail
    result = run(tmp_path, scheduler, fake_owner)
    assert fake_owner["calls"] == [["a"]] and fake_owner["native_calls"] == ["a"]
    assert not result["archived_jobs"][0]["retryable_lease_timeout"]
    assert scheduler.snapshot()["active_lease_count"] == 0


def test_artifact_before_timeout_disqualifies_retry(tmp_path, scheduler, fake_owner):
    lease = hold(scheduler)
    fake_owner["before"] = lambda identity, output: (output / identity).mkdir()
    try:
        result = run(tmp_path, scheduler, fake_owner)
    finally:
        lease.release()
    assert fake_owner["calls"] == [["a"]] and not result["archived_jobs"][0]["retryable_lease_timeout"]


def test_resume_completed_campaign_returns_archived_evidence_without_live_handles(tmp_path, scheduler, fake_owner):
    first = run(tmp_path, scheduler, fake_owner)
    assert first["live_jobs"]
    second = run(tmp_path, scheduler, fake_owner, resume=True)
    assert fake_owner["calls"] == [["a"]]
    assert second["live_jobs"] == [] and len(second["archived_jobs"]) == 1
    assert not second["receipt"]["live_validation_complete"]
    assert not second["receipt"]["archived_receipts_are_live_authority"]
    assert "native_execution" not in second["archived_jobs"][0]
    assert second["receipt"] == api._read(tmp_path / "campaign/manifest.json")
    for result in (first, second):
        receipt = result["receipt"]
        assert receipt["manifest_sha256"] == api._digest({k:v for k,v in receipt.items() if k != "manifest_sha256"})


def test_resume_only_sealed_lease_failure_retains_prior_success_as_archive(tmp_path, scheduler, fake_owner, monkeypatch):
    leases = []

    def before(identity, output):
        if identity == "b" and len(fake_owner["calls"]) == 1:
            leases.append(hold(scheduler))

    def after(state):
        for lease in leases:
            lease.release()

    def interrupt_backoff(seconds):
        raise KeyboardInterrupt("unit interruption after sealed first round")

    fake_owner.update(before=before, after=after)
    original_time = api.time
    monkeypatch.setattr(api, "time", SimpleNamespace(monotonic=original_time.monotonic, sleep=interrupt_backoff))
    options = dict(owner=fake_owner["contract"], output_directory=tmp_path / "campaign", scheduler=scheduler,
        lake_executable="unit-not-executed", native_cpu_slots=1, native_memory_mb=128, native_child_process_slots=1,
        lease_wait_timeout_seconds=.01, retry_backoff_seconds=.001, max_admission_seconds=5)
    with pytest.raises(KeyboardInterrupt):
        api.run_resumable_native_validation([job("a"), job("b")], **options)
    assert api._read(tmp_path / "campaign/manifest.json")["inflight"] is None
    monkeypatch.setattr(api, "time", original_time)
    result = api.run_resumable_native_validation([job("a"), job("b")], resume=True, **options)
    assert fake_owner["calls"] == [["a", "b"], ["b"]]
    assert [row["job_id"] for row in result["live_jobs"]] == ["b"]
    assert [row["job_id"] for row in result["archived_jobs"]] == ["a"]
    assert not result["receipt"]["live_validation_complete"]


def test_interrupted_inflight_is_unknown_and_cannot_replay(tmp_path, scheduler, fake_owner):
    def interrupt(identity):
        raise KeyboardInterrupt("native stage outcome unknown")

    fake_owner["failure"] = interrupt
    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, scheduler, fake_owner)
    first = api._read(tmp_path / "campaign/manifest.json")
    assert first["inflight"] is not None
    result = run(tmp_path, scheduler, fake_owner, resume=True)
    assert fake_owner["calls"] == [["a"]]
    assert result["receipt"]["stopped_reason"] == "interrupted_inflight_execution_unknown"
    assert result["receipt"]["status"] == "incomplete" and not result["live_jobs"]
    assert (tmp_path / "campaign/round-0000/lease-events.jsonl").exists()


@pytest.mark.parametrize("changed", ("source", "report", "review", "receipt", "manifest"))
def test_resume_refuses_source_or_evidence_drift(tmp_path, scheduler, fake_owner, changed):
    rows = [job("a")]
    run(tmp_path, scheduler, fake_owner, rows)
    if changed == "source":
        rows[0].source_inputs["source_text"] += " changed"
    elif changed == "report":
        rows[0].report["fixture"] = "changed"
    elif changed == "review":
        rows = [checks.NativeProjectionJob("a", rows[0].report, rows[0].source_inputs, ({"changed": True},))]
    elif changed == "receipt":
        (tmp_path / "campaign/round-0000/batch/a/receipt.json").write_text("{}")
    else:
        manifest = api._read(tmp_path / "campaign/manifest.json")
        manifest["consumed_admission_seconds"] = -100
        (tmp_path / "campaign/manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        run(tmp_path, scheduler, fake_owner, rows, resume=True)
    assert fake_owner["calls"] == [["a"]]


def test_attempt_budget_retains_all_resource_failures(tmp_path, scheduler, fake_owner):
    lease = hold(scheduler)
    try:
        result = run(tmp_path, scheduler, fake_owner, max_attempts_per_job=2)
    finally:
        lease.release()
    assert fake_owner["calls"] == [["a"], ["a"]] and not fake_owner["native_calls"]
    assert result["receipt"]["stopped_reason"] == "attempt_budget_exhausted"
    assert result["receipt"]["status"] == "incomplete" and len(result["receipt"]["rounds"]) == 2


def test_changed_scheduler_policy_refuses_resume(tmp_path, scheduler, fake_owner):
    run(tmp_path, scheduler, fake_owner)
    scheduler.config.proof_memory_headroom_mb += 1
    with pytest.raises(ValueError, match="scheduler policy drift"):
        run(tmp_path, scheduler, fake_owner, resume=True)


def test_proof_safety_cannot_be_disabled(tmp_path, scheduler, fake_owner):
    scheduler.config.proof_safety_enabled = False
    with pytest.raises(ValueError, match="proof safety"):
        run(tmp_path, scheduler, fake_owner)
    assert not (tmp_path / "campaign").exists()


def test_original_job_and_full_typed_inputs_are_unchanged(tmp_path, scheduler, fake_owner):
    rows = [job("a")]
    before = deepcopy(rows)
    run(tmp_path, scheduler, fake_owner, rows)
    assert rows == before


@pytest.mark.parametrize("setting,value", (("max_attempts_per_job", True), ("max_attempts_per_job", 9),
    ("max_admission_seconds", float("nan")), ("retry_backoff_seconds", 61)))
def test_invalid_retry_settings_fail_before_artifact_creation(tmp_path, scheduler, fake_owner, setting, value):
    options = dict(owner=fake_owner["contract"], output_directory=tmp_path / "campaign", scheduler=scheduler,
        lake_executable="unit-not-executed", **{setting: value})
    with pytest.raises(ValueError):
        api.run_resumable_native_validation([job("a")], **options)
    assert not (tmp_path / "campaign").exists()


def test_expired_before_acquire_is_pending_without_extending_cumulative_budget(tmp_path, scheduler, fake_owner, monkeypatch):
    logical_time = [0.0]
    monkeypatch.setattr(api, "time", SimpleNamespace(monotonic=lambda: logical_time[0],
        sleep=lambda seconds: logical_time.__setitem__(0, logical_time[0] + seconds)))
    fake_owner["before"] = lambda *args: logical_time.__setitem__(0, 6.0)
    result = run(tmp_path, scheduler, fake_owner)
    assert result["receipt"]["stopped_reason"] == "admission_budget_exhausted"
    assert result["archived_jobs"][0]["deferred_before_admission"]
    assert not result["archived_jobs"][0]["retryable_lease_timeout"]
    assert not fake_owner["native_calls"]
    assert scheduler.snapshot()["counters"]["acquisitions_total"] == 0
    resumed = run(tmp_path, scheduler, fake_owner, resume=True)
    assert fake_owner["calls"] == [["a"]]
    assert resumed["receipt"]["stopped_reason"] == "admission_budget_exhausted"
    assert not resumed["live_jobs"]


@pytest.mark.parametrize("usage", (-1, True))
def test_rehashed_invalid_consumed_budget_cannot_extend_resume(tmp_path, scheduler, fake_owner, usage):
    run(tmp_path, scheduler, fake_owner)
    root = tmp_path / "campaign"
    manifest = api._read(root / "manifest.json")
    manifest["consumed_admission_seconds"] = usage
    api._save_manifest(root, manifest)
    with pytest.raises(ValueError, match="finite and nonnegative"):
        run(tmp_path, scheduler, fake_owner, resume=True)


def test_unversioned_owner_is_not_an_implicit_resume_upgrade():
    from ipfs_datasets_py.logic.formalization.autoencoder import parallel_projection_checks as old
    with pytest.raises(ValueError, match="versioned native parallel owner"):
        api.NativeValidationOwner.from_module(old)
