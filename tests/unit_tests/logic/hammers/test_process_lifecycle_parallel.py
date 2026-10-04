"""Native Linux portfolio launches and metadata probes retain process bounds."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from ipfs_datasets_py.logic.hammers import models, policy, portfolio, process_lifecycle as lifecycle
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="native Linux prlimit qualification")

LIMIT_SCRIPT = """import json, resource, time
print(json.dumps({name: list(resource.getrlimit(getattr(resource, 'RLIMIT_' + name)))
                  for name in ('CORE', 'CPU', 'AS')}), flush=True)
time.sleep(.15)
"""


def limits(**kwargs):
    return lifecycle.ProcessLimits(wall_time_seconds=3, cpu_seconds=1.2, memory_mb=128,
        graceful_shutdown_seconds=.1, forced_cleanup_seconds=.5, **kwargs)


def test_concurrent_native_launches_overlap_without_python_preexec_and_inherit_limits(tmp_path, monkeypatch):
    popen, observed, overlaps = subprocess.Popen, [], []
    lock = threading.Lock()
    def launch(argv, **kwargs):
        assert kwargs["preexec_fn"] is None and kwargs["shell"] is False
        assert kwargs["start_new_session"] is True
        assert argv[0] == lifecycle._linux_prlimit_path()
        process = popen(argv, **kwargs)
        with lock:
            observed.append(process)
            overlaps.append(sum(row.poll() is None for row in observed))
        return process
    monkeypatch.setattr(lifecycle.subprocess, "Popen", launch)
    monkeypatch.setattr(lifecycle, "_resource_preexec", lambda *_: pytest.fail("Python preexec selected on Linux"))
    command = [sys.executable, "-c", LIMIT_SCRIPT]
    with lifecycle.ProcessSupervisor(state_directory=tmp_path, recover=False) as supervisor:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: supervisor.run(command, kind="smt", limits=limits()), range(8)))
        assert supervisor.active_process_count == 0
        assert not list(supervisor.manifest_directory.glob("*.json"))
    assert 2 <= max(overlaps) <= 4
    assert all(process.poll() is not None for process in observed)
    for result in results:
        assert result.command == command and result.returncode == 0 and result.process_group_reaped
        assert json.loads(result.stdout) == {"CORE": [0, 0], "CPU": [2, 2], "AS": [128 * 1024**2] * 2}


def test_native_memory_limit_refuses_oversized_allocation(tmp_path):
    code = """try:
    allocation = bytearray(512 * 1024 * 1024)
except MemoryError:
    print('bounded-allocation-refused', flush=True)
else:
    raise AssertionError('allocation exceeded declared address-space limit')
"""
    with lifecycle.ProcessSupervisor(state_directory=tmp_path, recover=False) as supervisor:
        result = supervisor.run([sys.executable, "-c", code], limits=limits())
    assert result.returncode == 0 and result.stdout.strip() == "bounded-allocation-refused"
    assert result.process_group_reaped


def test_missing_native_helper_fails_closed_before_spawn(tmp_path, monkeypatch):
    def missing():
        raise OSError("trusted prlimit unavailable")
    monkeypatch.setattr(lifecycle, "_linux_prlimit_path", missing)
    monkeypatch.setattr(lifecycle.subprocess, "Popen", lambda *a, **k: pytest.fail("unbounded process launched"))
    with lifecycle.ProcessSupervisor(state_directory=tmp_path, recover=False) as supervisor:
        result = supervisor.run([sys.executable, "-c", "print(1)"], limits=limits())
        assert supervisor.active_process_count == 0
        assert not list(supervisor.manifest_directory.glob("*.json"))
    assert result.pid is None and "trusted prlimit unavailable" in result.error
    assert result.termination_reason == "spawn_error" and result.process_group_reaped


@pytest.fixture
def owned_portfolio(tmp_path, monkeypatch):
    owner = resources.GlobalResourceScheduler(resources.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "admission.json", proof_resource_sampler=lambda: ProofHostResources(8, 8192, 8192),
        lane_reservations={}, auto_renew_leases=False, proof_backoff_seconds=.02, poll_interval_seconds=.005))
    with lifecycle.ProcessSupervisor(state_directory=tmp_path / "processes", recover=False,
                                    heartbeat_interval_seconds=.02) as supervisor:
        monkeypatch.setattr(portfolio, "get_process_supervisor", lambda: supervisor)
        with owner.acquire("orchestration", cpu_slots=1, memory_mb=256, child_process_slots=1, timeout=0) as parent:
            yield owner, parent, supervisor
            assert owner.snapshot()["active_lease_count"] == 1
            assert owner.snapshot()["waiting_request_count"] == 0
        assert supervisor.active_process_count == 0
        assert owner.snapshot()["active_lease_count"] == 0


def executable(tmp_path, version_code):
    path = tmp_path / "z3-probe-fixture"
    path.write_text(f"#!{sys.executable}\nimport json, resource, sys, time\n"
                    "if '--version' in sys.argv:\n" + "\n".join("    " + line for line in version_code.splitlines())
                    + "\nelse:\n    print('unsat', flush=True)\n")
    path.chmod(0o700)
    return str(path)


def runner(path, owner, **kwargs):
    settings = policy.PortfolioPolicy(
        hammer_policy=models.HammerPolicy(allowed_solvers=["z3"], timeout_seconds=3),
        executable_overrides={"z3": path},
        solver_budgets={"z3": policy.SolverBudget(timeout_seconds=3, cpu_seconds=1.2, memory_mb=128)},
        max_parallel_processes=1, cancel_on_first_conclusive=False)
    return portfolio.SolverPortfolio(settings, resource_scheduler=owner, resource_wait_timeout_seconds=.5, **kwargs)


def attempts():
    translated = models.TranslationRecord(translation_id="bounded-fixture", request_id="probe-fixture",
        target=models.TranslationTarget.SMTLIB, status=models.TranslationStatus.SUPPORTED,
        source_construct="fixture", translated_text="(assert false)")
    return [portfolio.PortfolioAttemptSpec(translated, "z3")]


def test_native_version_probe_inherits_solver_memory_and_cpu_bounds(tmp_path, owned_portfolio):
    owner, parent, _ = owned_portfolio
    path = executable(tmp_path, "print(json.dumps({name:list(resource.getrlimit(getattr(resource,'RLIMIT_'+name))) for name in ('CORE','CPU','AS')}), flush=True)")
    result = runner(path, owner).run("probe-fixture", attempts(), parent_lease=parent)
    assert result.attempts[0].verdict is models.SolverVerdict.UNSAT
    assert json.loads(result.attempts[0].solver_version) == {
        "CORE": [0, 0], "CPU": [2, 2], "AS": [128 * 1024**2] * 2}


def test_cancellation_during_native_version_probe_reaps_process_and_skips_solver(tmp_path, owned_portfolio):
    owner, parent, supervisor = owned_portfolio
    marker = tmp_path / "version-started"
    path = executable(tmp_path, f"open({str(marker)!r}, 'w').write('started')\ntime.sleep(30)")
    event = threading.Event()
    def forbidden(*args, **kwargs):
        pytest.fail("cancelled version discovery still launched the solver")
    transport = runner(path, owner, process_runner=forbidden)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(transport.run, "probe-fixture", attempts(), parent_lease=parent, cancel_event=event)
        deadline = time.monotonic() + 2
        while not marker.exists() and time.monotonic() < deadline:
            event.wait(.005)
        assert marker.exists()
        assert supervisor.active_process_count == 1
        event.set()
        result = future.result(timeout=3)
    assert result.attempts[0].verdict is models.SolverVerdict.UNKNOWN
    assert len(result.cancelled_attempt_ids) == 1
    assert result.attempts[0].solver_version is None
    assert supervisor.active_process_count == 0
    assert not list(supervisor.manifest_directory.glob("*.json"))


def test_legacy_two_argument_version_probe_still_observes_cancellation(tmp_path, owned_portfolio):
    owner, parent, _ = owned_portfolio
    event, calls = threading.Event(), []
    path = executable(tmp_path, "print('unused')")
    def probe(executable_path, spec):
        calls.append((executable_path, spec.name))
        event.set()
        return "fixture-version"
    def forbidden(*args, **kwargs):
        pytest.fail("injected version cancellation was ignored")
    result = runner(path, owner, version_prober=probe, process_runner=forbidden).run(
        "probe-fixture", attempts(), parent_lease=parent, cancel_event=event)
    assert calls == [(path, "z3")]
    assert len(result.cancelled_attempt_ids) == 1


def test_version_probe_time_is_subtracted_from_solver_wall_budget(tmp_path, owned_portfolio):
    owner, parent, _ = owned_portfolio
    path = executable(tmp_path, "print('unused')")
    def probe(path, spec):
        time.sleep(.04)
        return "fixture-version"
    observed = []
    def process(command, *, budget, cancel_event):
        observed.append(budget.timeout_seconds)
        return portfolio.SolverProcessOutcome(command, returncode=0, stdout="unsat", wall_time_seconds=.01)
    result = runner(path, owner, version_prober=probe, process_runner=process).run(
        "probe-fixture", attempts(), parent_lease=parent)
    assert len(observed) == 1 and 0 < observed[0] < 2.98
    assert result.attempts[0].wall_time_seconds >= .05
