"""Qualification wrapper preserves shared configuration and foreign work."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "benchmarks"))
import bench_codebase_restart_safety as harness


def configuration(tmp_path):
    return schedulers.ResourceSchedulerConfig(
        state_path=tmp_path / "pool.json", total_cpu_slots=4, total_memory_mb=9830,
        total_child_process_slots=4, lane_reservations={}, proof_safety_enabled=True,
        proof_memory_headroom_mb=2458, auto_renew_leases=False)


@pytest.mark.parametrize("operation", ["snapshot", "active_leases", "acquire"])
def test_guard_refuses_idle_external_config_drift_without_rewriting(operation, tmp_path):
    original = configuration(tmp_path)
    schedulers.GlobalResourceScheduler(original)
    guarded = harness.guarded_owner(original)
    changed = schedulers.GlobalResourceScheduler(replace(original, total_cpu_slots=3))
    before = changed.state_path.read_bytes()
    with pytest.raises(schedulers.ResourceConfigurationError, match="refuses shared pool drift"):
        if operation == "acquire":
            guarded.acquire("validation", cpu_slots=1, memory_mb=64, child_process_slots=1, timeout=0)
        else:
            getattr(guarded, operation)()
    assert changed.state_path.read_bytes() == before
    assert json.loads(before)["config"] == changed.config.persisted_dict()


def test_guard_refuses_recreating_deleted_shared_pool(tmp_path):
    config = configuration(tmp_path)
    owner = schedulers.GlobalResourceScheduler(config)
    guarded = harness.guarded_owner(config)
    owner.state_path.unlink()
    with pytest.raises(schedulers.ResourceConfigurationError, match="recreation"):
        guarded.snapshot()
    assert not owner.state_path.exists()


def test_saved_owner_coexists_with_real_foreign_lease_without_releasing_it(tmp_path, monkeypatch):
    config = configuration(tmp_path)
    owner = schedulers.GlobalResourceScheduler(config)
    pin = tmp_path / "config.json"
    harness.write_json(pin, {"schema": harness.PIN_SCHEMA, "state_path": str(owner.state_path),
        "config": config.persisted_dict(), "allow_foreign_work": True})
    script = """
import json,sys
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import ResourceSchedulerConfig,GlobalResourceScheduler
value=json.loads(sys.argv[1])
owner=GlobalResourceScheduler(ResourceSchedulerConfig(state_path=sys.argv[2],**value))
with owner.acquire('validation',cpu_slots=1,memory_mb=64,child_process_slots=1,timeout=5):
 print('ready',flush=True)
 sys.stdin.read()
"""
    child = subprocess.Popen([sys.executable, "-c", script, json.dumps(config.persisted_dict()),
                              str(owner.state_path)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    monkeypatch.setattr(schedulers, "_GLOBAL_SCHEDULERS", {})
    monkeypatch.setattr(schedulers, "default_resource_scheduler_config", lambda: config)
    try:
        # The fixture emits one readiness line after actual native admission.
        import select
        assert select.select([child.stdout], [], [], 10)[0], "foreign fixture failed to become ready"
        assert child.stdout.readline().strip() == "ready"
        guarded, _ = harness.install_saved_owner(pin)
        assert schedulers.get_global_resource_scheduler() is guarded
        assert harness.base.own_leases(guarded) == []
        assert [row["owner_pid"] for row in guarded.active_leases()] == [child.pid]
        with guarded.acquire("validation", cpu_slots=1, memory_mb=64, child_process_slots=1, timeout=2):
            assert len(guarded.active_leases()) == 2
        after = harness.state_summary(owner.state_path)
        assert after["active_leases"] == 1 and after["owned_active_leases"] == 0
        assert after["config"] == config.persisted_dict()
        assert child.poll() is None
    finally:
        try:
            child.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.communicate(timeout=5)
    assert child.returncode == 0
    assert owner.active_leases() == []


def test_install_refuses_changed_config_before_registering_default(tmp_path, monkeypatch):
    config = configuration(tmp_path)
    owner = schedulers.GlobalResourceScheduler(config)
    pin = tmp_path / "config.json"
    harness.write_json(pin, {"schema": harness.PIN_SCHEMA, "state_path": str(owner.state_path),
        "config": replace(config, total_cpu_slots=3).persisted_dict(), "allow_foreign_work": True})
    monkeypatch.setattr(schedulers, "_GLOBAL_SCHEDULERS", {})
    before = owner.state_path.read_bytes()
    with pytest.raises(AssertionError, match="changed since pinning"):
        harness.install_saved_owner(pin)
    assert owner.state_path.read_bytes() == before
    assert schedulers._GLOBAL_SCHEDULERS == {}


def test_fresh_cli_prioritizes_workspace_matcher_over_nested_accelerate(tmp_path):
    # Deliberately supply datasets first, where a nested accelerate checkout
    # shadows the workspace package if the wrapper fails to prioritize it.
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join((str(harness.base.ROOT),
                                                            str(harness.base.ACCELERATE))))
    result = subprocess.run([sys.executable, str(Path(harness.__file__).resolve()),
        "--replay", str(tmp_path / "missing-replay.json"),
        "--pinned-config", str(tmp_path / "missing-pinned-config.json")],
        capture_output=True, text=True, timeout=15, env=environment, cwd=harness.base.ROOT)
    assert result.returncode == 1
    # Reaching the bounded config reader requires the real entrypoint's exact
    # imported matcher path assertion to pass first. No shared owner is opened.
    report = json.loads(result.stdout.splitlines()[-1])
    assert report["error"]["type"] == "FileNotFoundError"
    assert "missing-pinned-config.json" in report["error"]["message"]
