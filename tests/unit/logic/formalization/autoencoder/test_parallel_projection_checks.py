"""Scheduling/accounting tests; actual Lake/solver execution belongs to smoke."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import parallel_projection_checks as checks
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


class Wire:
    def __init__(self, value):
        self.value = value

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
    # Real native formula evidence records the AST of its canonical reparse.
    replay = checks.modal.parse_modal(parsed.printed, checks.modal.profile_k())
    report = {"domain_id": "legal_ir", "source_digest": "a" * 64, "source_sha256": "b" * 64,
        "projections": [{"projection_id": "legal_ir/native_formula/propositional/v3", "logic_family": "propositional",
            "target_sha256": "c" * 64, "payload": {"ast_format": "shared_logic", "printed": parsed.printed,
                "native_ast": replay.root.to_dict()}}]}
    return checks.NativeProjectionJob("first", report, {"source_text": "explicit test source"})


@pytest.fixture
def stub_native(monkeypatch):
    monkeypatch.setattr(checks, "_guard", lambda: None)
    monkeypatch.setattr(checks.native.v2, "_source_bytes", lambda domain, inputs: (inputs["source_text"].encode(), None, None))
    monkeypatch.setattr(checks.native, "prepare_native_family_lean", lambda *a, **kw: {})
    monkeypatch.setattr(checks.native, "build_native_family_lake", lambda *a, **kw: Wire({"status": "partial"}))
    monkeypatch.setattr(checks.validation, "validate_projection_report", lambda *a, **kw: Wire({"qualified": False}))


def run(tmp_path, scheduler, jobs, **kwargs):
    return checks.run_parallel_projection_checks(jobs, scheduler=scheduler,
        lake_executable="unexecuted-test-only-lake", output_directory=tmp_path / "out", **kwargs)


def diagnostic(job, **kwargs):
    return checks.PortfolioDiagnosticJob("solver", job.job_id, job.report["projections"][0]["projection_id"], **kwargs)


def test_parallel_native_jobs_use_shared_leases_and_preserve_order(tmp_path, scheduler, job, stub_native, monkeypatch):
    barrier, active = Barrier(2), []

    def build(*a, **kw):
        barrier.wait(timeout=3)
        active.append(scheduler.snapshot()["active_root_lease_count"])
        barrier.wait(timeout=3)
        return Wire({"status": "partial"})

    monkeypatch.setattr(checks.native, "build_native_family_lake", build)
    result = run(tmp_path, scheduler, [job, replace(job, job_id="second")])
    assert active == [2, 2]
    assert [r["job_id"] for r in result["jobs"]] == ["first", "second"]
    assert all(r["receipt"]["lease"]["memory_mb"] == 1024 for r in result["jobs"])
    assert scheduler.snapshot()["active_lease_count"] == 0
    assert result["receipt"]["all_jobs_completed"]
    assert not result["receipt"]["qualified"]
    assert all(r["receipt"]["native_status"] == "partial" for r in result["jobs"])


def test_missing_or_failed_native_is_not_replaced(tmp_path, scheduler, job, stub_native, monkeypatch):
    def fail(*a, **kw):
        raise ValueError("native rejected exact source")

    monkeypatch.setattr(checks.native, "build_native_family_lake", fail)
    result = run(tmp_path, scheduler, [job])
    assert result["jobs"][0]["receipt"]["status"] == "failed"
    assert "observation" not in result["jobs"][0]
    assert not result["receipt"]["all_jobs_completed"]
    assert scheduler.snapshot()["active_lease_count"] == 0


def test_hardware_capacity_caps_worker_count(tmp_path, scheduler, job, stub_native):
    result = run(tmp_path, scheduler, [job, replace(job, job_id="second"), replace(job, job_id="third")], max_workers=10)
    assert result["receipt"]["effective_workers"] == 2


def test_existing_lease_reduces_initial_concurrency(tmp_path, scheduler, job, stub_native):
    with scheduler.acquire(checks.resources.ResourceLane.TRAINER, cpu_slots=2, memory_mb=1024, child_process_slots=2):
        result = run(tmp_path, scheduler, [job, replace(job, job_id="second")])
    assert result["receipt"]["effective_workers"] == 1


@pytest.mark.parametrize("kwargs", [{"max_workers": True}, {"native_memory_mb": 0},
    {"native_cpu_slots": 0}, {"native_child_process_slots": 0}, {"native_step_timeout_seconds": 61},
    {"lease_wait_timeout_seconds": float("nan")}, {"solver_timeout_seconds": 0}])
def test_bad_budgets_fail_before_work(tmp_path, scheduler, job, stub_native, kwargs):
    with pytest.raises(ValueError):
        run(tmp_path, scheduler, [job], **kwargs)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("identity", ["../other", "", "a/b", "a" * 97])
def test_output_identifiers_fail_closed(tmp_path, scheduler, job, stub_native, identity):
    with pytest.raises(ValueError):
        run(tmp_path, scheduler, [replace(job, job_id=identity)])


def test_duplicate_jobs_rejected(tmp_path, scheduler, job, stub_native):
    with pytest.raises(ValueError, match="duplicate"):
        run(tmp_path, scheduler, [job, job])


def test_aggregate_bytes_refuse_before_any_native_launch(tmp_path, scheduler, job, stub_native, monkeypatch):
    monkeypatch.setattr(checks, "MAX_BATCH_BYTES", 1)
    with pytest.raises(ValueError, match="aggregate byte"):
        run(tmp_path, scheduler, [job])
    assert not (tmp_path / "out").exists()
    assert scheduler.snapshot()["counters"]["acquisitions_total"] == 0


def test_per_item_bytes_refuse_before_work(tmp_path, scheduler, job, stub_native, monkeypatch):
    monkeypatch.setattr(checks, "MAX_ITEM_BYTES", 1)
    with pytest.raises(ValueError, match="item byte"):
        run(tmp_path, scheduler, [job])


def test_native_worker_must_fit_resource_envelope(tmp_path, scheduler, job, stub_native):
    with pytest.raises(ValueError, match="does not fit"):
        run(tmp_path, scheduler, [job], native_memory_mb=4097)


def test_proof_safety_cannot_be_disabled(tmp_path, scheduler, job, stub_native):
    scheduler.config.proof_safety_enabled = False
    with pytest.raises(ValueError, match="proof safety"):
        run(tmp_path, scheduler, [job])


def test_diagnostic_uses_real_parser_and_translator_with_exact_binding(job):
    attempts, policy, binding = checks._diagnostic(diagnostic(job), job, 10, 256, 2)
    assert len(attempts) == 2
    assert policy.cancel_on_first_conclusive is False
    assert binding["report_sha256"] == checks._digest(job.report)
    assert binding["payload_sha256"] == checks._digest(job.report["projections"][0]["payload"])
    assert binding["relation"] == "exact_propositional_native_ast_translation"
    assert all("(assert (=> p q))" in attempt.translation.translated_text for attempt in attempts)
    assert not binding["source_meaning_relation_verified"]
    assert all(row["source_logic_family"] == "propositional"
               and row["operation"] == "check_satisfiability"
               and row["input_semantics"] == "assert_formula"
               for row in binding["semantic_routing"]["routes"])


@pytest.mark.parametrize("family", ["first_order", "deontic", "modal", "temporal", "tdfol",
    "dcec", "cec", "frame_logic", "transition_system", "tla_plus"])
def test_unsupported_family_never_launches_or_acquires_solver_resources(
        tmp_path, scheduler, job, stub_native, monkeypatch, family):
    modified = deepcopy(job.report)
    modified["projections"][0]["logic_family"] = family
    target = replace(job, report=modified)
    monkeypatch.setattr(checks.native, "build_native_family_lake", lambda *a, **k: pytest.fail("native launched before route gate"))
    monkeypatch.setattr(checks.portfolio, "SolverPortfolio", lambda *a, **k: pytest.fail("unsupported solver launched"))
    with pytest.raises(ValueError, match="propositional targets only"):
        run(tmp_path, scheduler, [target], portfolio_jobs=[diagnostic(target)])
    assert scheduler.snapshot()["counters"]["acquisitions_total"] == 0
    assert not (tmp_path / "out").exists()


def test_atp_and_smt_keep_distinct_operations_without_winner_cancellation(job):
    attempts, policy, binding = checks._diagnostic(
        diagnostic(job, solver_names=("z3", "vampire")), job, 10, 256, 2)
    routes = binding["semantic_routing"]["routes"]
    assert routes[0]["verdict_semantics"] == "formula_satisfiability"
    assert routes[1]["verdict_semantics"] == "formula_validity_candidate"
    assert "(assert" in attempts[0].translation.translated_text
    assert "conjecture" in attempts[1].translation.translated_text
    assert policy.cancel_on_first_conclusive is False
    assert binding["semantic_routing"]["cross_operation_vote_permitted"] is False


def test_diagnostic_target_ast_must_equal_reparse(job):
    modified = deepcopy(job.report)
    modified["projections"][0]["payload"]["native_ast"]["symbol"] = "fabricated"
    with pytest.raises(ValueError, match="AST differs"):
        checks._diagnostic(diagnostic(job), replace(job, report=modified), 10, 256, 2)


@pytest.mark.parametrize("kind", ["forall", "exists", "extension", "equality"])
def test_diagnostic_never_erases_unsupported_operators(kind):
    with pytest.raises(ValueError, match="unsupported"):
        checks._propositional_term({"kind": kind, "arguments": [], "binders": []})


@pytest.mark.parametrize("mutation", ["wrong_family", "wrong_projection", "duplicate_solver", "extra_override"])
def test_diagnostic_contract_mismatches_fail(job, mutation):
    d = diagnostic(job)
    if mutation == "wrong_family":
        job = replace(job, report=deepcopy(job.report))
        job.report["projections"][0]["logic_family"] = "tdfol"
    elif mutation == "wrong_projection":
        d = replace(d, projection_id="missing")
    elif mutation == "duplicate_solver":
        d = replace(d, solver_names=("z3", "z3"))
    else:
        d = replace(d, executable_overrides={"vampire": "/nowhere"})
    with pytest.raises(ValueError):
        checks._diagnostic(d, job, 10, 256, 2)


def test_portfolio_receives_same_scheduler_and_denials_remain_explicit(tmp_path, scheduler, job, stub_native, monkeypatch):
    constructed = []

    class FakePortfolio:
        def __init__(self, policy, **kwargs):
            constructed.append(kwargs)

        def run(self, request, attempts):
            return Wire({"attempts": [], "denied": [{"solver_name": "z3", "reason": "test missing binary"}]})

    monkeypatch.setattr(checks.portfolio, "SolverPortfolio", FakePortfolio)
    result = run(tmp_path, scheduler, [job], portfolio_jobs=[diagnostic(job, solver_names=("z3",))])
    assert constructed[0]["resource_scheduler"] is scheduler
    assert constructed[0]["resource_lane"] == checks.resources.ResourceLane.HAMMER_LEAN.value
    assert result["portfolio_jobs"][0]["receipt"]["portfolio"]["denied"]
    assert not result["portfolio_jobs"][0]["receipt"]["admitted"]
    assert len(result["jobs"]) == 1


def test_fresh_output_required(tmp_path, scheduler, job, stub_native):
    (tmp_path / "out").mkdir()
    with pytest.raises(FileExistsError):
        run(tmp_path, scheduler, [job])


def test_native_and_portfolio_submissions_are_interleaved(tmp_path, scheduler, job, stub_native, monkeypatch):
    started, barrier = [], Barrier(2)

    def build(*a, **kw):
        key = kw["output_directory"].name
        started.append(key)
        if key == "first":
            barrier.wait(timeout=3)
        return Wire({"status": "partial"})

    class FakePortfolio:
        def __init__(self, *a, **kw):
            pass

        def run(self, request, attempts):
            started.append(request)
            barrier.wait(timeout=3)
            return Wire({"attempts": [], "denied": []})

    monkeypatch.setattr(checks.native, "build_native_family_lake", build)
    monkeypatch.setattr(checks.portfolio, "SolverPortfolio", FakePortfolio)
    result = run(tmp_path, scheduler, [job, replace(job, job_id="second")],
        portfolio_jobs=[diagnostic(job, solver_names=("z3",))])
    assert set(started[:2]) == {"first", "solver"}
    assert started[-1] == "second"
    assert [item["job_id"] for item in result["jobs"]] == ["first", "second"]
    assert [item["job_id"] for item in result["portfolio_jobs"]] == ["solver"]
    assert result["receipt"]["all_jobs_completed"]


def test_producer_guard_detects_drift(tmp_path, monkeypatch):
    path = tmp_path / "source.py"
    path.write_text("original")
    monkeypatch.setattr(checks.native, "_guard", lambda: None)
    monkeypatch.setattr(checks, "_PINS", {str(path): "0" * 64})
    with pytest.raises(ValueError, match="producer changed"):
        checks._guard()
