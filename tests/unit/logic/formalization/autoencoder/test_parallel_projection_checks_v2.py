"""V2 scheduler handoff tests with explicitly fake native execution.

These tests exercise accounting and error boundaries, never claim actual Lake
results, and keep real propositional routing for solver-exclusion checks.
"""
from copy import deepcopy
from dataclasses import replace
from threading import Barrier

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import parallel_projection_checks_v2 as checks
from ipfs_datasets_py.logic.formalization.autoencoder import parallel_projection_checks as old
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v6 as native
from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract_v6 as validation
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


class FakeWire:
    def __init__(self, value):
        self.value = {"test_scope": "scheduler_unit_double_not_Lake_evidence", **value}

    def to_dict(self):
        return deepcopy(self.value)


@pytest.fixture
def scheduler(tmp_path):
    return checks.resources.GlobalResourceScheduler(checks.resources.ResourceSchedulerConfig(
        total_cpu_slots=4, total_memory_mb=4096, total_child_process_slots=4,
        state_path=tmp_path / "scheduler.json", lane_reservations={}, proof_safety_enabled=True,
        proof_resource_sampler=lambda: ProofHostResources(4, 4096, 4096), proof_backoff_seconds=0))


@pytest.fixture
def job():
    parsed = checks.modal.parse_modal("p -> q", checks.modal.profile_k())
    replay = checks.modal.parse_modal(parsed.printed, checks.modal.profile_k())
    report = {"domain_id": "legal_ir", "source_digest": "a" * 64, "source_sha256": "b" * 64,
        "projections": [{"projection_id": "legal_ir/native_formula/propositional/v3", "logic_family": "propositional",
            "target_sha256": "c" * 64, "payload": {"ast_format": "shared_logic", "printed": parsed.printed,
                "native_ast": replay.root.to_dict()}}]}
    return checks.NativeProjectionJob("one", report, {"source_text": "explicit scheduler unit fixture"})


@pytest.fixture
def fake_native(monkeypatch):
    monkeypatch.setattr(checks, "_guard", lambda: None)
    monkeypatch.setattr(checks.native.v2, "_source_bytes", lambda domain, inputs: (inputs["source_text"].encode(), None, None))
    monkeypatch.setattr(checks.native, "prepare_native_family_lean", lambda *a, **k: {})
    monkeypatch.setattr(checks.native, "build_native_family_lake", lambda *a, **k: FakeWire({"status": "partial"}))
    monkeypatch.setattr(checks.validation, "validate_projection_report", lambda *a, **k: FakeWire({"qualified": False}))


def run(tmp_path, scheduler, jobs, **options):
    return checks.run_parallel_projection_checks(jobs, scheduler=scheduler,
        lake_executable="unit-never-executed", output_directory=tmp_path / "out", **options)


def test_new_owners_and_old_interface_remain_separate():
    assert checks.native is native and checks.validation is validation
    assert checks.native is not old.native and checks.validation is not old.validation
    assert checks.SCHEMA != old.SCHEMA
    assert checks.NativeProjectionJob is not old.NativeProjectionJob


def test_parallel_leases_preserve_order_and_live_object_identity(tmp_path, scheduler, job, fake_native, monkeypatch):
    barrier = Barrier(2)
    issued, observed, active = [], [], []

    def build(report, **options):
        barrier.wait(timeout=3)
        active.append(scheduler.snapshot()["active_root_lease_count"])
        handle = FakeWire({"status": "partial"})
        issued.append(handle)
        barrier.wait(timeout=3)
        return handle

    def validate(report, *, lake_execution, applicability_review):
        assert any(lake_execution is handle for handle in issued)
        observed.append(lake_execution)
        return FakeWire({"qualified": False})

    monkeypatch.setattr(checks.native, "build_native_family_lake", build)
    monkeypatch.setattr(checks.validation, "validate_projection_report", validate)
    original = deepcopy(job.report)
    result = run(tmp_path, scheduler, [job, replace(job, job_id="two")])
    assert active == [2, 2] and job.report == original
    assert [row["job_id"] for row in result["jobs"]] == ["one", "two"]
    assert all(any(row["native_execution"] is handle for handle in observed) for row in result["jobs"])
    assert result["receipt"]["effective_workers"] == 2
    assert scheduler.snapshot()["active_lease_count"] == 0
    assert all(row["receipt"]["native_status"] == "partial" for row in result["jobs"])
    assert all(result["receipt"][key] is False for key in checks.FALSE)


def test_failed_native_job_is_retained_and_sibling_completes(tmp_path, scheduler, job, fake_native, monkeypatch):
    def build(report, *, output_directory, **options):
        if output_directory.name == "one":
            raise ValueError("strict native parser rejected this projection")
        return FakeWire({"status": "partial"})

    monkeypatch.setattr(checks.native, "build_native_family_lake", build)
    result = run(tmp_path, scheduler, [job, replace(job, job_id="two")])
    assert [row["receipt"]["status"] for row in result["jobs"]] == ["failed", "completed"]
    assert "observation" not in result["jobs"][0]
    assert not result["receipt"]["all_jobs_completed"]
    assert scheduler.snapshot()["active_lease_count"] == 0


def test_preflight_parser_error_stops_before_resources_or_backend(tmp_path, scheduler, job, fake_native, monkeypatch):
    def reject(*args, **kwargs):
        raise ValueError("complete formula malformed")

    monkeypatch.setattr(checks.native, "prepare_native_family_lean", reject)
    monkeypatch.setattr(checks.native, "build_native_family_lake", lambda *a, **k: pytest.fail("backend called after parser failure"))
    with pytest.raises(ValueError, match="complete formula malformed"):
        run(tmp_path, scheduler, [job])
    assert scheduler.snapshot()["counters"]["acquisitions_total"] == 0 and not (tmp_path / "out").exists()


@pytest.mark.parametrize("family", ("dcec", "cec", "deontic", "tdfol", "first_order", "temporal", "frame_logic", "transition_system"))
def test_nonpropositional_families_never_enter_solver_portfolio(tmp_path, scheduler, job, fake_native, monkeypatch, family):
    modified = deepcopy(job.report)
    modified["projections"][0]["logic_family"] = family
    target = replace(job, report=modified)
    diagnostic = checks.PortfolioDiagnosticJob("solver", target.job_id, modified["projections"][0]["projection_id"])
    monkeypatch.setattr(checks.native, "build_native_family_lake", lambda *a, **k: pytest.fail("native started before route preflight"))
    monkeypatch.setattr(checks.portfolio, "SolverPortfolio", lambda *a, **k: pytest.fail("unsupported solver started"))
    with pytest.raises(ValueError, match="propositional targets only"):
        run(tmp_path, scheduler, [target], portfolio_jobs=[diagnostic])
    assert scheduler.snapshot()["counters"]["acquisitions_total"] == 0 and not (tmp_path / "out").exists()


def test_existing_load_caps_concurrency_and_releases_new_leases(tmp_path, scheduler, job, fake_native):
    with scheduler.acquire(checks.resources.ResourceLane.TRAINER, cpu_slots=2, memory_mb=1024, child_process_slots=2):
        result = run(tmp_path, scheduler, [job, replace(job, job_id="two")], max_workers=8)
        assert result["receipt"]["effective_workers"] == 1
    assert scheduler.snapshot()["active_lease_count"] == 0


@pytest.mark.parametrize("options", ({"max_workers": True}, {"native_memory_mb": 0}, {"native_step_timeout_seconds": 61}))
def test_invalid_resource_settings_fail_before_work(tmp_path, scheduler, job, fake_native, options):
    with pytest.raises(ValueError):
        run(tmp_path, scheduler, [job], **options)
    assert not (tmp_path / "out").exists()


def test_old_typed_jobs_are_not_implicitly_upgraded(tmp_path, scheduler, job, fake_native):
    previous = old.NativeProjectionJob(job.job_id, job.report, job.source_inputs)
    with pytest.raises(ValueError, match="typed NativeProjectionJob"):
        run(tmp_path, scheduler, [previous])
