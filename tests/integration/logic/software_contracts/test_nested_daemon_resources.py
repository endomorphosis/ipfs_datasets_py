"""Actual shared native parent joined to the existing durable disk/RSS owner."""
from dataclasses import replace
import json
import os
import signal
import subprocess
import sys
import time

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import (
    DaemonResourceReservation, DaemonResourceError,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    ResourceLane, ResourceLeaseToken, get_global_resource_scheduler, ResourceUnavailableError, ResourceConfigurationError,
)


@pytest.fixture
def parent():
    scheduler = get_global_resource_scheduler()
    with scheduler.acquire(ResourceLane.ORCHESTRATION, cpu_slots=2, memory_mb=512,
            child_process_slots=2, timeout=60, request_id="nested-durable-resource-qualification") as lease:
        yield scheduler, lease


def reservation(tmp_path, parent, **changes):
    output = tmp_path / "outputs"
    output.mkdir(exist_ok=True)
    values = dict(roots=[output], storage_bytes=16384, memory_mb=128,
        cpu_slots=1, child_process_slots=1, timeout_seconds=0, parent_lease=parent)
    values.update(changes)
    return DaemonResourceReservation(tmp_path / "disk.json", **values)


@pytest.mark.parametrize("token", [False, True])
def test_durable_disk_children_share_parent_without_duplicate_host_allocation(tmp_path, parent, token):
    scheduler, lease = parent
    def owned_roots():
        return [(row["lease_id"], row["cpu_slots"], row["memory_mb"])
                for row in scheduler.active_leases()
                if row["owner_pid"] == os.getpid() and not row.get("parent_lease_id")]
    capacity = owned_roots()
    reference = lease.token if token else lease
    with reservation(tmp_path, reference) as first, reservation(tmp_path, reference) as second:
        # Unrelated host jobs can start/stop between observations. Compare only
        # this process's root charges, while checking both real child linkages.
        assert owned_roots() == capacity == [(lease.lease_id, 2, 512)]
        records = [first.to_dict(), second.to_dict()]
        assert all(r["resource_lease"]["parent_lease_id"] == lease.lease_id for r in records)
        assert all(r["record"]["parent_lease_id"] == lease.lease_id for r in records)
        ledger = json.loads((tmp_path / "disk.json").read_text())
        assert sum(v["storage_bytes"] for v in ledger["reservations"].values()) == 32768
        assert "lease_key" not in json.dumps(records) and lease.lease_key not in json.dumps(ledger)
        first.release(artifacts_durable=True)
        assert not lease.released and not second._lease.released
    assert second.to_dict()["status"] == "retained"
    assert second._lease.released and not lease.released
    second.release(artifacts_durable=True)
    assert all(r["lease_id"] == lease.lease_id for r in scheduler.active_leases()
               if r["owner_pid"] == os.getpid())


def test_over_parent_demand_refuses_and_retains_disk_claim(tmp_path, parent):
    _, lease = parent
    request = reservation(tmp_path, lease, memory_mb=513)
    with pytest.raises(ResourceUnavailableError, match="exceeds parent"):
        with request:
            pytest.fail("over-parent demand admitted")
    assert request.to_dict()["status"] == "retained" and not lease.released
    assert request.to_dict()["resource_lease"] is None
    request.release(artifacts_durable=True)


def test_foreign_scheduler_token_never_creates_a_new_root(tmp_path, parent):
    _, lease = parent
    foreign = replace(lease.token, state_path=str(tmp_path / "foreign.json"))
    request = reservation(tmp_path, foreign)
    with pytest.raises(ResourceConfigurationError):
        with request:
            pytest.fail("foreign host authority admitted")
    assert request.to_dict()["status"] == "retained"
    assert request.to_dict()["resource_lease"] is None and not (tmp_path / "foreign.json").exists()
    request.release(artifacts_durable=True)


@pytest.mark.parametrize("revoke", ["cancel", "release"])
def test_parent_cancellation_reaches_durable_child_without_releasing_disk_early(tmp_path, parent, revoke):
    _, lease = parent
    with reservation(tmp_path, lease) as child:
        child.check_usage(tmp_path / "outputs")
        child.account_external_bytes("before", 16)
        getattr(lease, revoke)()
        assert child._lease.cancelled
        with pytest.raises(DaemonResourceError, match="no longer active"):
            child.check_usage(tmp_path / "outputs")
        with pytest.raises(DaemonResourceError, match="no longer active"):
            child.account_external_bytes("after", 16)
        assert child.to_dict()["record"]["external_charges"] == {"before": 16}
    assert child.to_dict()["status"] == "retained"
    assert child._lease.released and lease.released == (revoke == "release")
    child.release(artifacts_durable=True)


def test_revocation_during_child_launch_still_tracks_child_until_reaped(tmp_path, parent):
    _, lease = parent
    with reservation(tmp_path, lease) as child:
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"],
                                   start_new_session=True)
        try:
            lease.cancel()
            with pytest.raises(DaemonResourceError, match="no longer active"):
                child.check_usage(tmp_path / "outputs", child_pid=process.pid)
            assert child.to_dict()["record"]["child"]["pid"] == process.pid
            with pytest.raises(DaemonResourceError, match="still alive"):
                child.release(artifacts_durable=True)
        finally:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        child.release(artifacts_durable=True)


def test_untyped_parent_refuses_before_any_durable_reservation(tmp_path):
    with pytest.raises(DaemonResourceError, match="exact native parent"):
        reservation(tmp_path, "invented-lease")
    assert not (tmp_path / "disk.json").exists()


def test_dead_parent_is_recovered_before_usage_or_new_charges(tmp_path):
    private = tmp_path / "parent-capability.json"
    script = '''
from dataclasses import asdict
import json, os, sys, time
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import get_global_resource_scheduler, ResourceLane
with get_global_resource_scheduler().acquire(ResourceLane.ORCHESTRATION,
        cpu_slots=1, memory_mb=256, child_process_slots=1, timeout=60) as parent:
    fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(asdict(parent.token), stream); stream.flush(); os.fsync(stream.fileno())
    time.sleep(120)
'''
    process = subprocess.Popen([sys.executable, "-B", "-c", script, str(private)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
    try:
        deadline = time.monotonic() + 65
        token = None
        while process.poll() is None and time.monotonic() < deadline:
            if private.exists():
                try:
                    token = ResourceLeaseToken(**json.loads(private.read_text()))
                    break
                except json.JSONDecodeError:
                    pass
            time.sleep(.02)
        assert token is not None, "native subprocess parent was not admitted"
        with reservation(tmp_path, token) as child:
            child.check_usage(tmp_path / "outputs")
            process.kill(); process.wait(timeout=5)
            with pytest.raises(DaemonResourceError, match="no longer active"):
                child.check_usage(tmp_path / "outputs")
            with pytest.raises(DaemonResourceError, match="no longer active"):
                child.account_external_bytes("after-death", 1)
            assert child.to_dict()["record"]["external_charges"] == {}
        assert child.to_dict()["status"] == "retained"
        child.release(artifacts_durable=True)
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=5)
        private.unlink(missing_ok=True)
