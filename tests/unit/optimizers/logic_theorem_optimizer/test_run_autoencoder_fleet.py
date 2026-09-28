"""Fleet orchestration tests use injected owners and short local fixture children.

No model training, Hub access, owner construction, source repairs or legal admits.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location("fleet_cli", ROOT / "scripts/ops/legal_ir/run_autoencoder_fleet.py")
fleet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fleet)


def setup(tmp_path, count=3, **changes):
    connections = []
    for i in range(count):
        token = tmp_path / f"worker-{i}.token"
        token.write_text("secret-fixture-token-" + str(i)); token.chmod(0o600)
        connection = tmp_path / f"worker-{i}.json"
        connection.write_text(json.dumps({"worker_id": f"worker-{i}", "campaign_id": "fixture-campaign",
            "token_file": str(token), "endpoint": "http://127.0.0.1:1"}))
        connections.append(connection)
    argv = ["--state-directory", str(tmp_path / "fleet"), "--resource-ledger", str(tmp_path / "ledger.json")]
    for connection in connections:
        argv += ["--connection-file", str(connection)]
    args = fleet.parser().parse_args(argv)
    args.wave_interval = 0
    for key, value in changes.items():
        setattr(args, key, value)
    return args, fleet.connections(connections, args.state_directory)


def campaign(row):
    return {"campaign_id": row["campaign_id"], "known_workers": [row["worker_id"]],
            "binding_sha256": "a" * 64, "policy": {"worker_storage_bytes": 750_000_000},
            "weights": {"generation": 3}}


def planned(args, rows, **changes):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_capacity
    probe = {"hardware_cpu_count": 32, "affinity_cpu_count": 32,
             "cgroup_cpu_count": None, "available_memory_mb": 128000,
             "cgroup_memory_remaining_mb": None}
    capacity = lambda **kwargs: autoencoder_capacity.capacity_plan(**kwargs, probe=probe)
    settings = {"campaign_reader": campaign, "capacity": capacity,
                "storage_reader": lambda *_: {"headroom_bytes": 12_000_000_000},
                "scheduler_reader": lambda: {"available": {"cpu_slots": 20, "memory_mb": 128000,
                                                            "child_process_slots": 32}, "lanes": {}}}
    settings.update(changes)
    return fleet.plan_wave(args, rows, **settings)


def test_readonly_plan_has_no_fleet_files_reservations_or_processes(tmp_path):
    args, rows = setup(tmp_path, plan=True)
    before = {str(p): p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    result = fleet.run(args, planner=planned,
        wave_runner=lambda *a: pytest.fail("plan launched a child"))
    assert result["plan_only"] is True
    assert result["capacity"]["workers"] == 3
    assert result["per_worker"] == {"memory_mb": 9216, "cpu_slots": 2, "child_process_slots": 6, "storage_bytes": 1_500_000_000}
    assert result["reservation_acquired"] is False
    assert not args.state_directory.exists()
    assert before == {str(p): p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    assert "secret-fixture-token" not in json.dumps(result)


def test_capacity_respects_shared_storage_process_slots_and_explicit_pending(tmp_path):
    args, rows = setup(tmp_path, count=5)
    assert planned(args, rows, storage_reader=lambda *_: {"headroom_bytes": 3_000_000_000})["capacity"]["workers"] == 2
    assert planned(args, rows, scheduler_reader=lambda: {"available": {"cpu_slots": 20,
        "memory_mb": 128000, "child_process_slots": 3}, "lanes": {}})["capacity"]["workers"] == 0
    assert planned(args, rows, scheduler_reader=lambda: {"available": {"cpu_slots": 20,
        "memory_mb": 128000, "child_process_slots": 12}, "lanes": {}})["capacity"]["workers"] == 2
    args.pending_jobs = 0
    assert planned(args, rows)["capacity"]["workers"] == 0
    args.pending_jobs, args.max_workers = 20, 1
    assert planned(args, rows)["capacity"]["workers"] == 1


def test_sync_only_budgets_no_training_and_owner_policy_cannot_be_understated(tmp_path):
    args, rows = setup(tmp_path)
    larger = lambda row: {**campaign(row), "policy": {"worker_storage_bytes": 900_000_000}}
    with pytest.raises(fleet.FleetError, match="understates"):
        planned(args, rows, campaign_reader=larger)
    args.sync_only, args.pending_jobs = True, 0
    result = planned(args, rows, campaign_reader=larger)
    assert result["intent"] == "synchronize_weights"
    assert result["per_worker"] == {"memory_mb": 1024, "cpu_slots": 1, "child_process_slots": 1, "storage_bytes": 750_000_000}
    assert result["capacity"]["workers"] == 3


def test_storage_observer_counts_retained_claims_without_ledger_mutation(tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
    root = tmp_path / "root"; root.mkdir()
    ledger = tmp_path / "ledger.json"
    observer = resources.DaemonResourceReservation(ledger, roots=[root], storage_bytes=1, memory_mb=1)
    value = observer._read()
    value["reservations"]["retained"] = {"reservation_id": "retained", "status": "retained",
        "owner_pid": 999999, "storage_bytes": 700_000_000}
    ledger.write_text(json.dumps(value))
    before = ledger.read_bytes()
    (root / "artifact").write_bytes(b"x" * 100)
    result = fleet.storage_capacity(ledger, root / "fleet")
    assert result["outstanding_reservations_bytes"] == 700_000_000
    assert result["observed_apparent_bytes"] == 100
    assert result["headroom_bytes"] <= resources.MAX_STORAGE_BYTES - 700_000_100
    assert ledger.read_bytes() == before
    assert not ledger.with_name("ledger.json.lock").exists()
    assert not (root / "fleet").exists()


def test_waves_recompute_capacity_round_robin_and_resume_topology(tmp_path):
    args, rows = setup(tmp_path, cycles=2)
    selections, calls = [], []
    def plan(args, rows):
        calls.append(1)
        value = planned(args, rows); value["capacity"]["workers"] = 2
        return value
    def wave(args, selected, directory, stop):
        selections.append([row["worker_id"] for row in selected])
        return {"workers": [{"worker_id": row["worker_id"], "status": "completed"} for row in selected]}
    result = fleet.run(args, planner=plan, wave_runner=wave)
    assert selections == [["worker-0", "worker-1"], ["worker-2", "worker-0"]]
    assert len(calls) == 2 and result["waves_this_invocation"] == 2
    args.cycles = 1
    fleet.run(args, planner=plan, wave_runner=wave)
    assert selections[-1] == ["worker-1", "worker-2"]
    assert json.loads((args.state_directory / "fleet.json").read_text())["next_wave"] == 3
    changed = lambda a, r: {**plan(a, r), "campaign_binding_sha256": "b" * 64}
    with pytest.raises(fleet.FleetError, match="topology"):
        fleet.run(args, planner=changed, wave_runner=wave)
    assert len(selections) == 3


def test_no_capacity_rechecks_and_failure_stops_further_waves(tmp_path):
    args, rows = setup(tmp_path, cycles=3)
    calls = []
    def plan(a, r):
        value = planned(a, r); value["capacity"]["workers"] = 0 if not calls else 1
        calls.append(1); return value
    def wave(*unused):
        return {"workers": [{"worker_id": "worker-0", "status": "failed", "returncode": 7}]}
    result = fleet.run(args, planner=plan, wave_runner=wave)
    assert result["waves_this_invocation"] == 2 and result["failed_workers"] == 1


def test_prior_wave_with_live_pid_birth_blocks_resume_without_signaling(tmp_path, monkeypatch):
    args, rows = setup(tmp_path)
    args.state_directory.mkdir()
    prior = args.state_directory / "waves" / "prior"
    fleet._write(prior / "wave.json", {"workers": [{"owned_processes": {"123": "original-birth"}}]})
    fleet._write(args.state_directory / "fleet.json", {"schema": fleet.SCHEMA, "next_wave": 1,
        "next_worker": 0, "active_wave_directory": str(prior)})
    monkeypatch.setattr(fleet, "process_snapshot", lambda: {123: {"birth": "original-birth", "state": "R", "parent_pid": 1}})
    monkeypatch.setattr(fleet.os, "kill", lambda *a: pytest.fail("resume signaled an existing process"))
    with pytest.raises(fleet.FleetError, match="prior owned wave"):
        fleet.run(args, planner=planned)


def test_pid_reuse_does_not_expand_ownership():
    known = {123: "old"}
    snapshot = {123: {"birth": "new", "parent_pid": 1, "state": "R"},
                456: {"birth": "child", "parent_pid": 123, "state": "R"}}
    assert fleet.collect_owned(known, snapshot) == {}
    assert known == {123: "old"}


def test_real_fixture_child_uses_exact_worker_boundary_and_private_logs(tmp_path):
    args, rows = setup(tmp_path, count=1)
    recorded = []
    def spawn(command, **kwargs):
        recorded.append((command, kwargs.copy()))
        state = Path(rows[0]["state_directory"]); state.mkdir(parents=True)
        source = "import json,time;from pathlib import Path;print('fixture-only');time.sleep(.15);Path(" + repr(str(state / "worker-status.json")) + ").write_text(json.dumps({'processed_jobs_this_invocation':0}))"
        return subprocess.Popen([sys.executable, "-c", source], **kwargs)
    result = fleet.run_wave(args, rows, tmp_path / "wave", [False], popen=spawn)
    entry = result["workers"][0]
    assert entry["status"] == "completed" and entry["returncode"] == 0
    assert entry["worker_status_observed_this_invocation"] is True
    command, options = recorded[0]
    assert command[:3] == [sys.executable, str(fleet.RUNNER), "worker"]
    assert command[command.index("--polls") + 1] == command[command.index("--max-jobs") + 1] == "1"
    assert options["shell"] is False and options["start_new_session"] is True
    assert len(options["pass_fds"]) == 1
    assert "secret-fixture-token" not in " ".join(command)
    log = Path(entry["log_path"])
    assert log.stat().st_mode & 0o077 == 0 and "fixture-only" in log.read_text()
    assert not fleet.collect_owned({int(k): v for k, v in entry["owned_processes"].items()}, fleet.process_snapshot())


def test_timeout_stops_owned_detached_descendant_and_reaps_parent(tmp_path):
    args, rows = setup(tmp_path, count=1, wave_timeout=0.35)
    child_file = tmp_path / "descendant.pid"
    source = "import subprocess,sys,time;from pathlib import Path;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],start_new_session=True);Path(" + repr(str(child_file)) + ").write_text(str(p.pid));time.sleep(30)"
    def spawn(command, **kwargs):
        return subprocess.Popen([sys.executable, "-c", source], **kwargs)
    result = fleet.run_wave(args, rows, tmp_path / "wave", [False], popen=spawn)
    entry = result["workers"][0]
    assert entry["status"] == "timeout" and entry["returncode"] != 0
    descendant = int(child_file.read_text())
    assert descendant in entry["owned_processes"]
    assert not (Path("/proc") / str(descendant)).exists()


def test_identity_lock_survives_launcher_descriptor_close(tmp_path):
    path = tmp_path / "identity.lock"
    with fleet.exclusive(path) as descriptor:
        process = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], pass_fds=(descriptor,))
    try:
        with pytest.raises(BlockingIOError):
            with fleet.exclusive(path):
                pass
    finally:
        process.terminate(); process.wait(timeout=5)
    with fleet.exclusive(path):
        pass


def test_busy_identity_is_not_launched(tmp_path):
    args, rows = setup(tmp_path, count=1)
    key = hashlib.sha256((rows[0]["campaign_id"] + ":" + rows[0]["worker_id"]).encode()).hexdigest()
    with fleet.exclusive(args.resource_ledger.parent / "fleet-identity-locks" / (key + ".lock")):
        result = fleet.run_wave(args, rows, tmp_path / "wave", [False],
            popen=lambda *a, **k: pytest.fail("overlapped existing identity"))
    assert result["workers"] == [{"worker_id": "worker-0", "status": "identity_busy"}]


def test_spawn_failure_cleans_every_owned_worker_even_if_one_cleanup_reports_error(tmp_path, monkeypatch):
    args, rows = setup(tmp_path, count=3)
    children, stopped = [], []
    original = fleet.stop_owned
    def spawn(command, **kwargs):
        if len(children) == 2:
            raise OSError("injected spawn failure")
        child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], **kwargs)
        children.append(child)
        return child
    def stop(process, known):
        original(process, known)
        stopped.append(process.pid)
        if len(stopped) == 1:
            raise RuntimeError("injected post-reap cleanup error")
    monkeypatch.setattr(fleet, "stop_owned", stop)
    with pytest.raises(fleet.FleetError, match="cleanup failed"):
        fleet.run_wave(args, rows, tmp_path / "wave", [False], popen=spawn)
    assert len(stopped) == 2 and all(child.returncode is not None for child in children)


def test_sigterm_during_readonly_planning_does_not_launch_a_worker(tmp_path):
    args, rows = setup(tmp_path)
    previous = signal.getsignal(signal.SIGTERM)
    def planning(args, rows):
        os.kill(os.getpid(), signal.SIGTERM)
        return planned(args, rows)
    result = fleet.run(args, planner=planning, wave_runner=lambda *a: pytest.fail("launched after SIGTERM"))
    assert result["interrupted"] is True and result["waves_this_invocation"] == 0
    assert signal.getsignal(signal.SIGTERM) == previous


@pytest.mark.parametrize("flags", [["--cycles", "-1"], ["--max-workers", "33"],
    ["--wave-timeout", "nan"], ["--wave-interval", "inf"], ["--worker-storage-bytes", "0"],
    ["--memory-budget-mb", "-1"], ["--pending-jobs", "-1"], ["--lease-seconds", "119"]])
def test_invalid_cli_bounds_fail_before_owner_access(tmp_path, flags):
    with pytest.raises(SystemExit) as exc:
        fleet.main(["--state-directory", str(tmp_path / "unused"), "--connection-file", "missing.json", *flags])
    assert exc.value.code == 2
    assert not (tmp_path / "unused").exists()


def test_identity_and_token_file_validation(tmp_path):
    args, rows = setup(tmp_path, count=1)
    with pytest.raises(fleet.FleetError, match="duplicate"):
        fleet.connections(args.connection_file * 2, args.state_directory)
    token = tmp_path / "worker-0.token"; token.chmod(0o644)
    with pytest.raises(fleet.FleetError, match="private"):
        fleet.connections(args.connection_file, args.state_directory)
