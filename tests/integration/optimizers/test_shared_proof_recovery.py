"""Actual process/lock/restart controls with explicitly injected pressure.

No external host pressure or GPU qualification is implied by these tests.
"""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as mod
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


WORKER = r'''
import json,sys,time
from pathlib import Path
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as mod
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
p=json.loads(sys.argv[1]); mod.time.time=lambda:p['clock']
def sample():
 if p.get('missing'): raise OSError('injected telemetry loss')
 return ProofHostResources(8,8192,8192,memory_stall_percent=p.get('pressure',0))
if p.get('default_owner'):
 mod.collect_proof_host_resources=sample
 s=mod.get_global_resource_scheduler()
else:
 c=mod.ResourceSchedulerConfig(**p['config'],state_path=p['state'],proof_resource_sampler=sample,
  auto_renew_leases=False,poll_interval_seconds=.005)
 s=mod.GlobalResourceScheduler(c)
Path(p['ready']).write_text('ready')
deadline=time.monotonic()+15
while not Path(p['go']).exists():
 if time.monotonic()>=deadline: raise TimeoutError('test barrier')
 time.sleep(.01)
lease=s.try_acquire('hammer',memory_mb=64)
row=dict(pid=__import__('os').getpid(),admitted=lease is not None,
 lease_id=None if lease is None else lease.lease_id,recovery=s.snapshot()['proof_recovery'])
Path(p['result']).write_text(json.dumps(row))
try:
 if lease is not None and p.get('hold'): time.sleep(15)
finally:
 if lease is not None: lease.release()
'''


def wait_for(predicate):
    deadline = time.monotonic() + 15
    while not predicate():
        if time.monotonic() >= deadline:
            raise TimeoutError("bounded worker test barrier")
        time.sleep(.01)


def arm(tmp_path, monkeypatch):
    clock, observed = [1000.0], [ProofHostResources(8, 8192, 8192)]
    monkeypatch.setattr(mod.time, "time", lambda: clock[0])
    cfg = mod.ResourceSchedulerConfig(state_path=tmp_path / "shared.json",
        total_cpu_slots=8, total_memory_mb=8192, total_child_process_slots=8,
        lane_reservations={"validation": 1}, proof_safety_enabled=True,
        proof_resource_sampler=lambda: observed[0], proof_backoff_seconds=2,
        proof_recovery_enabled=True, proof_recovery_samples=2,
        proof_recovery_interval_seconds=1, proof_recovery_grants=4,
        auto_renew_leases=False, poll_interval_seconds=.005)
    owner = mod.GlobalResourceScheduler(cfg)
    observed[0] = replace(observed[0], memory_stall_percent=90)
    assert owner.try_acquire("hammer", memory_mb=64) is None
    observed[0] = replace(observed[0], memory_stall_percent=0)
    clock[0] = 1002.0
    assert owner.try_acquire("hammer", memory_mb=64) is None
    clock[0] = 1003.0
    with owner.acquire("validation", memory_mb=64, timeout=0):
        pass
    return owner, clock


def spawn(owner, tmp_path, name, clock, **options):
    files = {key: str(tmp_path / (name + "." + key)) for key in ("ready", "go", "result")}
    payload = dict(files, clock=clock, config=owner.config.persisted_dict(),
                   state=str(owner.state_path), **options)
    process = subprocess.Popen([sys.executable, "-c", WORKER, json.dumps(payload)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=dict(os.environ))
    return process, {key: Path(value) for key, value in files.items()}


def finish(process):
    stdout, stderr = process.communicate(timeout=20)
    assert process.returncode == 0, (stdout, stderr)


def stop_all(processes):
    for process, _ in processes:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def save(name, value):
    directory = os.environ.get("RPI_PRESSURE_RECOVERY_EVIDENCE")
    if directory:
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        (root / (name + ".json")).write_text(json.dumps(dict(
            pressure="injected", clock="injected", processes="actual", result=value), indent=2) + "\n")


def test_simultaneous_processes_share_one_credit_and_cold_reopen_cannot_bypass(tmp_path, monkeypatch):
    owner, clock = arm(tmp_path, monkeypatch)
    processes = [spawn(owner, tmp_path, "peer" + str(i), clock[0]) for i in range(3)]
    try:
        wait_for(lambda: all(files["ready"].exists() for _, files in processes))
        for _, files in processes:
            files["go"].touch()
        for process, _ in processes:
            finish(process)
        rows = [json.loads(files["result"].read_text()) for _, files in processes]
        assert len({row["pid"] for row in rows}) == 3
        assert sum(row["admitted"] for row in rows) == 1
        assert owner.snapshot()["proof_recovery"]["grants_remaining"] == 3
        cold = spawn(owner, tmp_path, "cold", clock[0])
        processes.append(cold)
        cold[1]["go"].touch()
        finish(cold[0])
        assert not json.loads(cold[1]["result"].read_text())["admitted"]
        later = spawn(owner, tmp_path, "later", clock[0] + 1)
        processes.append(later)
        later[1]["go"].touch()
        finish(later[0])
        assert json.loads(later[1]["result"].read_text())["admitted"]
        assert owner.snapshot()["proof_recovery"]["grants_remaining"] == 2
        assert owner.snapshot()["active_lease_count"] == owner.snapshot()["waiting_request_count"] == 0
        save("shared-credit", dict(simultaneous=rows, cold=json.loads(cold[1]["result"].read_text()),
            later=json.loads(later[1]["result"].read_text()), snapshot=owner.snapshot()))
    finally:
        stop_all(processes)


def test_killed_lease_owner_does_not_refund_shared_recovery_credit(tmp_path, monkeypatch):
    owner, clock = arm(tmp_path, monkeypatch)
    child = spawn(owner, tmp_path, "killed", clock[0], hold=True)
    try:
        child[1]["go"].touch()
        wait_for(child[1]["result"].exists)
        row = json.loads(child[1]["result"].read_text())
        assert row["admitted"]
        child[0].kill()
        child[0].communicate(timeout=10)
        recovered = owner.recover_stale_leases()
        assert row["lease_id"] in recovered
        assert owner.snapshot()["active_lease_count"] == 0
        assert owner.snapshot()["proof_recovery"]["grants_remaining"] == 3
        assert owner.try_acquire("hammer", memory_mb=64) is None
        clock[0] += 1
        with owner.acquire("hammer", memory_mb=64, timeout=0):
            pass
        save("killed-owner", dict(worker=row, reaped=recovered, snapshot=owner.snapshot()))
    finally:
        stop_all([child])


def test_missing_telemetry_in_fresh_process_rearms_every_owner(tmp_path, monkeypatch):
    owner, clock = arm(tmp_path, monkeypatch)
    child = spawn(owner, tmp_path, "missing", clock[0], missing=True)
    try:
        child[1]["go"].touch()
        finish(child[0])
        row = json.loads(child[1]["result"].read_text())
        assert not row["admitted"]
        snapshot = owner.snapshot()
        assert snapshot["proof_backoff"]["reason"] == "proof_resource_telemetry_unknown"
        assert snapshot["proof_recovery"]["healthy_samples"] == 0
        assert owner.try_acquire("validation", memory_mb=64) is None
        clock[0] += 2
        assert owner.try_acquire("hammer", memory_mb=64) is None
        assert owner.snapshot()["proof_recovery"]["healthy_samples"] == 1
        save("missing-telemetry", dict(worker=row, refusal=snapshot, after=owner.snapshot()))
    finally:
        stop_all([child])


def test_environment_selected_default_owner_reopens_same_recovery_in_fresh_process(tmp_path, monkeypatch):
    clock = [1000.0]
    healthy = ProofHostResources(8, 8192, 8192)
    observed = [healthy]
    monkeypatch.setattr(mod.time, "time", lambda: clock[0])
    monkeypatch.setattr(mod, "collect_proof_host_resources", lambda: observed[0])
    monkeypatch.setenv(mod.DEFAULT_STATE_ENV, str(tmp_path / "default-shared.json"))
    monkeypatch.setenv(mod.DEFAULT_PROOF_RECOVERY_ENV, "1")
    monkeypatch.delenv("IPFS_DATASETS_PROOF_RESOURCE_SAFETY", raising=False)
    owner = mod.get_global_resource_scheduler()
    observed[0] = replace(healthy, memory_stall_percent=90)
    assert owner.try_acquire("hammer", memory_mb=64) is None
    observed[0] = healthy
    clock[0] += owner.config.proof_backoff_seconds
    assert owner.try_acquire("hammer", memory_mb=64) is None
    # Fresh default owner must inherit the first spaced sample, not reset it.
    child = spawn(owner, tmp_path, "environment", clock[0], default_owner=True)
    try:
        child[1]["go"].touch()
        finish(child[0])
        row = json.loads(child[1]["result"].read_text())
        assert not row["admitted"]
        assert row["recovery"]["healthy_samples"] == 1
        assert row["recovery"] == owner.snapshot()["proof_recovery"]
        assert owner.snapshot()["active_lease_count"] == 0
        save("environment-owner", dict(worker=row, snapshot=owner.snapshot()))
    finally:
        stop_all([child])
