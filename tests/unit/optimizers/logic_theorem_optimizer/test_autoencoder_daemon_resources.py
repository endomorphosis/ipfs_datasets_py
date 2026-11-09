"""Real scheduler/filesystem checks; small test-only capacities, no native jobs."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, ResourceLane, ResourceSchedulerConfig, ResourceUnavailableError, LeaseTimeoutError,
)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    roots = [tmp_path / "outputs", tmp_path / "cache"]
    for root in roots:
        root.mkdir()
    scheduler = GlobalResourceScheduler(ResourceSchedulerConfig(
        total_cpu_slots=4, total_memory_mb=4096, total_child_process_slots=4,
        lane_reservations={}, state_path=tmp_path / "scheduler.json", auto_renew_leases=False))
    # Test-local real scheduler: never alter host-global resource state.
    monkeypatch.setattr(resources, "get_global_resource_scheduler", lambda: scheduler)
    monkeypatch.setattr(resources, "MAX_STORAGE_BYTES", 100_000)
    ledger = tmp_path / "disk.json"
    def factory(**kwargs):
        return resources.DaemonResourceReservation(ledger, roots=roots, storage_bytes=kwargs.pop("storage_bytes", 10_000),
                                                    memory_mb=kwargs.pop("memory_mb", 128), **kwargs)
    return factory, roots, ledger, scheduler


def test_production_storage_cap_is_two_hundred_twenty_gb_without_admission(tmp_path):
    root = tmp_path / "outputs"
    root.mkdir()
    ledger = tmp_path / "disk.json"
    reservation = resources.DaemonResourceReservation(
        ledger, roots=[root], storage_bytes=7, memory_mb=1)
    assert resources.MAX_STORAGE_BYTES == 220_000_000_000
    assert resources.MAX_INVENTORY_ENTRIES == 4_000_000
    assert reservation._read() == {
        "schema": resources.SCHEMA, "roots": reservation.root_identities,
        "limit_bytes": 220_000_000_000, "reservations": {},
    }
    assert reservation.to_dict()["storage_limit_bytes"] == 220_000_000_000
    assert reservation.to_dict()["status"] == "not_entered"
    assert reservation.to_dict()["resource_lease"] is None
    assert not ledger.exists()
    assert not reservation.lock_path.exists()


def test_campaign_cap_does_not_raise_fifty_gb_per_worker_policy():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_training_request as request

    policy = {"ledger_path": "/owned/disk.json", "roots": ["/owned/outputs"],
              "storage_bytes": 50_000_000_000, "memory_mb": 128, "cpu_slots": 1}
    assert request.MAX_STORAGE_BYTES == 50_000_000_000
    request._resource_policy(policy)
    with pytest.raises(request.CampaignTrainingRequestError, match="per-worker storage bytes"):
        request._resource_policy({**policy, "storage_bytes": 50_000_000_001})


def test_raised_campaign_boundary_still_counts_all_nonreleased_claims(tmp_path, monkeypatch):
    from types import SimpleNamespace

    root = tmp_path / "outputs"
    root.mkdir()
    ledger_path = tmp_path / "disk.json"
    reservation = resources.DaemonResourceReservation(
        ledger_path, roots=[root], storage_bytes=7, memory_mb=1)
    ledger = reservation._read()
    ledger["reservations"] = {
        "retained": {"status": "retained", "storage_bytes": 30_000_000_000},
        "active": {"status": "active", "storage_bytes": 1_000_000_000},
        "reserved": {"status": "reserved", "storage_bytes": 465_000_000},
        "released": {"status": "released", "storage_bytes": 50_000_000_000},
    }
    before = json.dumps(ledger, sort_keys=True)
    monkeypatch.setattr(resources, "_inventory", lambda roots: {
        "apparent_bytes": 100_203_148_222, "entry_count": 1_359_805,
        "symlink_count": 4_557, "special_file_count": 28})
    monkeypatch.setattr(resources.shutil, "disk_usage", lambda root: SimpleNamespace(free=120_000_000_000))
    headroom = 88_331_851_778
    usage = reservation._account(ledger, additional=headroom)
    assert usage["outstanding_full_reservations_bytes"] == 31_465_000_000
    assert usage["charged_bytes"] == usage["limit_bytes"] == 220_000_000_000
    with pytest.raises(resources.DaemonResourceError, match="capacity"):
        reservation._account(ledger, additional=headroom + 1)
    # Accounting headroom never substitutes for physically free storage.
    monkeypatch.setattr(resources.shutil, "disk_usage", lambda root: SimpleNamespace(free=31_714_999_999))
    with pytest.raises(resources.DaemonResourceError, match="capacity"):
        reservation._account(ledger, additional=250_000_000)
    assert json.dumps(ledger, sort_keys=True) == before
    assert not ledger_path.exists()
    assert reservation.to_dict()["resource_lease"] is None


@pytest.mark.parametrize("strict", [False, True])
def test_inventory_entry_limit_remains_inclusive_and_fail_closed(tmp_path, monkeypatch, strict):
    root = tmp_path / "outputs"
    root.mkdir()
    for index in range(3):
        (root / str(index)).write_bytes(b"abc")
    # Exercise the real scanner at a small finite limit, not millions of files.
    monkeypatch.setattr(resources, "MAX_INVENTORY_ENTRIES", 3)
    assert resources._inventory([root], strict=strict) == {
        "apparent_bytes": 9, "entry_count": 3, "symlink_count": 0, "special_file_count": 0}
    (root / "overflow").write_bytes(b"retained")
    with pytest.raises(resources.DaemonResourceError, match="inventory entry bound exceeded"):
        resources._inventory([root], strict=strict)
    assert (root / "overflow").read_bytes() == b"retained"


def test_declared_process_envelope_is_reserved_and_recorded(setup):
    factory, roots, ledger, scheduler = setup
    with factory(child_process_slots=3) as reservation:
        assert scheduler.snapshot()["allocated_child_process_slots"] == 3
        assert reservation.to_dict()["resource_lease"]["child_process_slots"] == 3
        record = json.loads(ledger.read_bytes())["reservations"][reservation.reservation_id]
        assert record["child_process_slots"] == 3
        usage = reservation.check_usage(roots[0])
        assert usage["reserved_child_process_slots"] == 3
        assert usage["process_slot_estimate_exceeded"] is False
        with factory() as other:
            assert scheduler.snapshot()["allocated_child_process_slots"] == 4
            assert other.to_dict()["resource_lease"]["child_process_slots"] == 1
            other.release(artifacts_durable=True)
        reservation.release(artifacts_durable=True)
    assert scheduler.snapshot()["allocated_child_process_slots"] == 0


def test_process_envelope_cannot_exceed_authoritative_scheduler_slots(setup):
    factory, roots, ledger, scheduler = setup
    with factory(child_process_slots=4) as active:
        with pytest.raises(LeaseTimeoutError):
            factory(child_process_slots=1).__enter__()
        assert scheduler.snapshot()["allocated_child_process_slots"] == 4
        active.release(artifacts_durable=True)


@pytest.fixture(params=[50_000_000_000, 60_000_000_000, 62_000_000_000, 75_000_000_000, 80_000_000_000, 85_000_000_000, 87_000_000_000, 90_000_000_000, 145_000_000_000, 160_000_000_000, 200_000_000_000],
                ids=["fifty-gb", "sixty-gb", "sixty-two-gb", "seventy-five-gb", "eighty-gb", "eighty-five-gb", "eighty-seven-gb", "ninety-gb", "one-hundred-forty-five-gb", "one-hundred-sixty-gb", "two-hundred-gb"])
def historical_storage_ledger(tmp_path, request):
    previous_limit = request.param
    root = tmp_path / "outputs"
    root.mkdir()
    (root / "preserved-output").write_bytes(b"abc")
    ledger = tmp_path / "disk.json"
    reservation = resources.DaemonResourceReservation(
        ledger, roots=[root], storage_bytes=7, memory_mb=1)
    records = {
        "retained": {
            "reservation_id": "retained", "status": "retained",
            "owner_pid": os.getpid(), "storage_bytes": 4_000,
            "external_charges": {"journal": 2},
            "retention_reason": "context_failed", "artifacts_durable_asserted": False,
            "last_usage": {"limit_bytes": previous_limit, "charged_bytes": 4_003},
            "prior_children": [{"pid": 17, "birth": "historical", "group_observed_dead_at": 1.0}],
        },
        "released": {
            "reservation_id": "released", "status": "released",
            "owner_pid": os.getpid(), "storage_bytes": 9_000,
            "external_charges": {}, "artifacts_durable_asserted": True,
            "final_accounting": {"limit_bytes": previous_limit},
        },
    }
    historical = {"schema": resources.SCHEMA, "roots": reservation.root_identities,
                  "limit_bytes": previous_limit, "reservations": records}
    raw = (json.dumps(historical, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ledger.write_bytes(raw)
    return reservation, ledger, historical, raw


def test_historical_ledger_fails_closed_without_implicit_migration(historical_storage_ledger):
    reservation, ledger, historical, raw = historical_storage_ledger
    with pytest.raises(resources.DaemonResourceError, match="storage scope differs"):
        reservation._read()
    assert ledger.read_bytes() == raw
    assert json.loads(raw)["reservations"] == historical["reservations"]
    assert reservation.to_dict()["status"] == "not_entered"
    assert not reservation.lock_path.exists()


def test_explicit_top_level_cap_migration_preserves_history_and_full_accounting(historical_storage_ledger):
    reservation, ledger, historical, raw = historical_storage_ledger
    old_prefix = ('{"limit_bytes":' + str(historical["limit_bytes"]) + ',').encode()
    new_prefix = b'{"limit_bytes":220000000000,'
    assert raw.startswith(old_prefix)
    # Model the explicit one-time edit on a tiny, test-owned fixture. This
    # neither introduces an implicit migration API nor acquires a reservation.
    migrated = new_prefix + raw[len(old_prefix):]
    backup = ledger.with_name("historical-disk.json")
    backup.write_bytes(raw)
    with reservation._locked():
        assert ledger.read_bytes() == raw
        reservation._write({**historical, "limit_bytes": 220_000_000_000})
    current = reservation._read()
    assert current == {**historical, "limit_bytes": 220_000_000_000}
    assert current["reservations"] == historical["reservations"]
    assert migrated[len(new_prefix):] == raw[len(old_prefix):]
    usage = reservation._account(current, additional=13)
    assert usage["limit_bytes"] == 220_000_000_000
    assert usage["observed_apparent_bytes"] == 3
    assert usage["outstanding_full_reservations_bytes"] == 4_000
    assert usage["additional_requested_bytes"] == 13
    assert usage["charged_bytes"] == 4_016
    assert ledger.read_bytes() == migrated
    assert backup.read_bytes() == raw
    assert reservation.to_dict()["status"] == "not_entered"
    assert reservation.to_dict()["resource_lease"] is None
    assert reservation.lock_path.is_file()


def test_canonical_trainer_uses_existing_default_reserved_lane(tmp_path, monkeypatch):
    # Keep the production five-lane defaults. Only state paths/capacities for
    # this deterministic filesystem test are local; never touch shared state.
    config = ResourceSchedulerConfig(total_cpu_slots=20, total_memory_mb=4096,
        state_path=tmp_path / "scheduler.json", auto_renew_leases=False)
    original = config.persisted_dict()
    assert original["lane_reservations"] == {
        "hammer_lean": {"cpu_slots": 8, "memory_mb": 0},
        "codex": {"cpu_slots": 4, "memory_mb": 0},
        "validation": {"cpu_slots": 4, "memory_mb": 0},
        "orchestration": {"cpu_slots": 2, "memory_mb": 0},
        "reserve": {"cpu_slots": 2, "memory_mb": 0},
    }
    scheduler = GlobalResourceScheduler(config)
    with pytest.raises(ResourceUnavailableError, match="reservation lane"):
        scheduler.acquire(ResourceLane.TRAINER, cpu_slots=1, memory_mb=128, timeout=0)
    monkeypatch.setattr(resources, "get_global_resource_scheduler", lambda: scheduler)
    root = tmp_path / "outputs"
    root.mkdir()
    ledger = tmp_path / "disk.json"
    with resources.DaemonResourceReservation(ledger, roots=[root], storage_bytes=10_000,
            memory_mb=128, cpu_slots=1) as reservation:
        receipt = reservation.to_dict()
        assert receipt["scheduler_lane"] == receipt["record"]["scheduler_lane"] == "hammer_lean"
        assert receipt["workload"] == receipt["record"]["workload"] == "canonical_trainer"
        assert receipt["resource_lease"]["lane"] == "hammer_lean"
        snapshot = scheduler.snapshot()
        assert snapshot["allocated"]["cpu_slots"] == 1
        assert snapshot["lanes"]["hammer_lean"]["allocated"]["cpu_slots"] == 1
        assert snapshot["lanes"]["validation"]["allocated"]["cpu_slots"] == 0
        reservation.release(artifacts_durable=True)
    assert config.persisted_dict() == original
    assert scheduler.snapshot()["allocated"]["cpu_slots"] == 0
    saved = json.loads(ledger.read_text())["reservations"][reservation.reservation_id]
    assert saved["scheduler_lane"] == "hammer_lean" and saved["workload"] == "canonical_trainer"


def test_durable_release_preserves_outputs_and_detached_receipt(setup):
    factory, roots, ledger, scheduler = setup
    attempt = roots[0] / "attempt"
    attempt.mkdir()
    (attempt / "output").write_bytes(b"exact output")
    with factory() as reservation:
        usage = reservation.check_usage(attempt)
        assert usage["attempt_bytes"] == 12
        assert usage["outstanding_full_reservations_bytes"] == 10_000
        result = reservation.release(artifacts_durable=True)
        assert result["status"] == "released"
        assert result["resource_lease"]["released"] is True
        assert result["record"]["final_attempt_bytes"] == 12
        result["record"]["status"] = "tampered copy"
        assert reservation.to_dict()["status"] == "released"
        assert reservation.close(artifacts_durable=True)["status"] == "released"
    assert (attempt / "output").read_bytes() == b"exact output"
    saved = json.loads(ledger.read_text())
    assert saved["reservations"][reservation.reservation_id]["status"] == "released"
    assert saved["roots"] == reservation.root_identities


def test_context_exit_retains_disk_but_releases_cpu(setup):
    factory, roots, ledger, _ = setup
    with factory() as reservation:
        pass
    result = reservation.to_dict()
    assert result["status"] == "retained"
    assert result["resource_lease"]["released"] is True
    with factory() as other:
        usage = other.check_usage(roots[0])
        assert usage["outstanding_full_reservations_bytes"] == 20_000
        other.release(artifacts_durable=True)
    reservation.release(artifacts_durable=True)


@pytest.mark.parametrize("failure", [ValueError("failure"), KeyboardInterrupt("interrupted")])
def test_exception_is_preserved_and_failed_claim_retained(setup, failure):
    factory, _, ledger, _ = setup
    with pytest.raises(type(failure)) as caught:
        with factory() as reservation:
            raise failure
    assert caught.value is failure
    row = json.loads(ledger.read_text())["reservations"][reservation.reservation_id]
    assert row["status"] == "retained"
    assert row["retention_reason"] == "context_failed"
    reservation.release(artifacts_durable=True)


def test_cleanup_error_does_not_mask_primary_exception(setup, monkeypatch):
    factory, _, _, _ = setup
    reservation = factory()
    reservation.__enter__()
    failure = KeyboardInterrupt("original")
    def cleanup(*args):
        raise RuntimeError("ledger unavailable")
    monkeypatch.setattr(reservation, "_retain", cleanup)
    assert reservation.__exit__(type(failure), failure, None) is False
    assert reservation.to_dict()["cleanup_error"] == "RuntimeError"
    reservation.release(artifacts_durable=True)


def test_observed_plus_all_full_reserves_are_charged(setup):
    factory, roots, _, _ = setup
    (roots[1] / "retained").write_bytes(b"x" * 75_000)
    with factory(storage_bytes=20_000) as first:
        with pytest.raises(resources.DaemonResourceError, match="capacity"):
            factory(storage_bytes=6_000).__enter__()
        assert first.check_usage(roots[0])["charged_bytes"] == 95_000
        first.release(artifacts_durable=True)
    # Released reservations become observed artifacts, never deleted files.
    with factory(storage_bytes=24_000) as second:
        second.release(artifacts_durable=True)
    assert (roots[1] / "retained").stat().st_size == 75_000


def test_attempt_growth_limit_retained_then_explicit_safe_release(setup):
    factory, roots, _, _ = setup
    attempt = roots[0] / "attempt"; attempt.mkdir()
    with factory(storage_bytes=50) as reservation:
        reservation.check_usage(attempt)
        (attempt / "grown").write_bytes(b"x" * 51)
        with pytest.raises(resources.DaemonResourceError, match="attempt storage"):
            reservation.check_usage(attempt)
        result = reservation.release(artifacts_durable=True)
        assert result["record"]["attempt_exceeded_reservation"] is True
    assert (attempt / "grown").stat().st_size == 51


def test_external_growth_rechecked_during_poll(setup):
    factory, roots, _, _ = setup
    with factory() as reservation:
        reservation.check_usage(roots[0])
        (roots[1] / "other-owner").write_bytes(b"x" * 95_000)
        with pytest.raises(resources.DaemonResourceError, match="capacity"):
            reservation.check_usage(roots[0])
        # Final accounting drops only this reservation; observed bytes remain.
        reservation.release(artifacts_durable=True)


def test_ledger_scope_is_ordered_and_immutable(setup):
    factory, roots, ledger, _ = setup
    with factory() as reservation:
        with pytest.raises(resources.DaemonResourceError, match="scope differs"):
            resources.DaemonResourceReservation(ledger, roots=list(reversed(roots)), storage_bytes=1, memory_mb=1).__enter__()
        reservation.release(artifacts_durable=True)


@pytest.mark.parametrize("field,value", [("storage_bytes",0),("storage_bytes",True),("storage_bytes",100_001),
    ("memory_mb",0),("memory_mb",True),("cpu_slots",0),("cpu_slots",False),
    ("child_process_slots",0),("child_process_slots",False),("child_process_slots",1.5),
    ("timeout_seconds",-1),("timeout_seconds",True),("timeout_seconds",float("nan"))])
def test_invalid_requests_fail_before_ledger_mutation(setup, field, value):
    factory, _, ledger, _ = setup
    with pytest.raises(resources.DaemonResourceError):
        factory(**{field:value})
    assert not ledger.exists()


def test_overlapping_missing_and_symlink_roots_rejected(setup, tmp_path):
    _, roots, ledger, _ = setup
    nested=roots[0]/"nested"; nested.mkdir()
    alias=tmp_path/"alias"; alias.symlink_to(roots[0],target_is_directory=True)
    for selected in ([roots[0],roots[0]], [roots[0],nested], [alias], [tmp_path/"missing"]):
        with pytest.raises(resources.DaemonResourceError):
            resources.DaemonResourceReservation(ledger,roots=selected,storage_bytes=1,memory_mb=1)


@pytest.mark.parametrize("kind", ["symlink","fifo","hardlink"])
def test_ledger_aliases_and_special_files_rejected_without_opening_fifo(setup, tmp_path, kind):
    factory, _, ledger, _ = setup
    if kind=="fifo": os.mkfifo(ledger)
    elif kind=="symlink": ledger.symlink_to(tmp_path/"other")
    else:
        other=tmp_path/"other"; other.write_text("{}")
        os.link(other,ledger)
    with pytest.raises(resources.DaemonResourceError):
        factory().__enter__()


def test_shared_inventory_counts_symlinks_and_special_files_without_following(setup, tmp_path):
    factory, roots, _, _ = setup
    outside=tmp_path/"large-unowned";outside.write_bytes(b"x"*150_000)
    link=roots[1]/"cache-link";link.symlink_to(outside)
    os.mkfifo(roots[1]/"unowned-fifo")
    expected=link.lstat().st_size+(roots[1]/"unowned-fifo").lstat().st_size
    with factory() as reservation:
        usage=reservation.check_usage(roots[0])
        assert usage["observed_apparent_bytes"]==expected
        assert usage["inventory"]["symlink_count"]==1
        assert usage["inventory"]["special_file_count"]==1
        reservation.release(artifacts_durable=True)


@pytest.mark.parametrize("kind",["symlink","fifo"])
def test_bound_attempt_rejects_unsafe_output_entries(setup,kind):
    factory,roots,_,_=setup
    attempt=roots[0]/"attempt";attempt.mkdir()
    unsafe=attempt/"unsafe"
    if kind=="symlink":unsafe.symlink_to(roots[1])
    else:os.mkfifo(unsafe)
    with factory() as reservation:
        with pytest.raises(resources.DaemonResourceError,match="attempt"):
            reservation.check_usage(attempt)
        unsafe.unlink()  # Test-owned entry only; production never removes data.
        reservation.release(artifacts_durable=True)


def test_attempt_outside_root_or_replaced_directory_fails(setup,tmp_path):
    factory,roots,_,_=setup
    attempt=roots[0]/"attempt";attempt.mkdir()
    with factory() as reservation:
        with pytest.raises(resources.DaemonResourceError,match="outside"):
            reservation.check_usage(tmp_path)
        reservation.check_usage(attempt)
        attempt.rename(roots[0]/"old");attempt.mkdir()
        with pytest.raises(resources.DaemonResourceError,match="identity changed"):
            reservation.check_usage(attempt)
    assert reservation.to_dict()["status"]=="retained"


def test_scheduler_failure_retains_claim_and_original_error(setup,monkeypatch):
    factory,_,ledger,scheduler=setup
    failure=RuntimeError("scheduler busy")
    def reject(*args,**kwargs):raise failure
    monkeypatch.setattr(scheduler,"acquire",reject)
    reservation=factory()
    with pytest.raises(RuntimeError) as caught:reservation.__enter__()
    assert caught.value is failure
    assert json.loads(ledger.read_text())["reservations"][reservation.reservation_id]["status"]=="retained"
    reservation.release(artifacts_durable=True)


def test_explicit_durability_and_no_child_identity_switch(setup):
    factory,roots,_,_=setup
    with factory() as reservation:
        with pytest.raises(resources.DaemonResourceError,match="durability"):
            reservation.release()
        with pytest.raises(resources.DaemonResourceError,match="owned isolated"):
            reservation.check_usage(roots[0],child_pid=os.getpid())
        reservation.release(artifacts_durable=True)


@pytest.mark.skipif(sys.platform!="linux",reason="Linux process-group accounting")
def test_real_child_group_rss_and_release_after_exit(setup):
    factory,roots,_,_=setup
    with factory() as reservation:
        child=subprocess.Popen([sys.executable,"-c","import sys; print('ready',flush=True);sys.stdin.buffer.read(1)"],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,start_new_session=True)
        try:
            assert child.stdout.readline()==b"ready\n"
            usage=reservation.check_usage(roots[0],child_pid=child.pid)
            assert usage["group_rss"]["live_processes"]==1
            assert usage["group_rss"]["rss_bytes"]>0
            with pytest.raises(resources.DaemonResourceError,match="still alive"):
                reservation.release(artifacts_durable=True)
        finally:
            child.communicate(b"x",timeout=5)
        assert child.returncode==0
        reservation.release(artifacts_durable=True)


def test_group_rss_limit_is_polled_and_never_kills_unowned_process(setup,monkeypatch):
    factory,roots,_,_=setup
    with factory(memory_mb=1) as reservation:
        monkeypatch.setattr(resources,"_group_usage",lambda child:{"available":True,"live_processes":1,"rss_bytes":2*1024*1024})
        with pytest.raises(resources.DaemonResourceError,match="RSS"):
            reservation.check_usage(roots[0])
        assert reservation.to_dict()["record"]["last_usage"]["group_rss"]["rss_bytes"]==2*1024*1024
        monkeypatch.setattr(resources,"_group_usage",lambda child:{"available":True,"live_processes":0,"rss_bytes":0})
        reservation.release(artifacts_durable=True)


def test_ledger_deleted_or_duplicate_json_fails_closed(setup):
    factory,roots,ledger,_=setup
    with factory() as reservation:
        raw=ledger.read_bytes();ledger.unlink()
        with pytest.raises(resources.DaemonResourceError,match="disappeared"):
            reservation.check_usage(roots[0])
        ledger.write_text('{"schema":1,"schema":2}')
        with pytest.raises(resources.DaemonResourceError,match="duplicate"):
            reservation.check_usage(roots[0])
        ledger.write_bytes(raw)
        reservation.release(artifacts_durable=True)


def test_crashed_owner_disk_claim_survives_scheduler_recovery(setup):
    factory, roots, ledger, scheduler = setup
    script = """
import os, sys
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as r
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import GlobalResourceScheduler, ResourceSchedulerConfig
r.MAX_STORAGE_BYTES=100000
s=GlobalResourceScheduler(ResourceSchedulerConfig(total_cpu_slots=4,total_memory_mb=4096,total_child_process_slots=4,lane_reservations={},state_path=sys.argv[1],auto_renew_leases=False))
r.get_global_resource_scheduler=lambda:s
v=r.DaemonResourceReservation(sys.argv[2],roots=sys.argv[3:],storage_bytes=10000,memory_mb=128)
v.__enter__()
v.account_external_bytes('journal',2000)
print(v.reservation_id,flush=True)
os._exit(17)
"""
    child = subprocess.run([sys.executable,"-c",script,str(scheduler.state_path),str(ledger),
                            *(str(root) for root in roots)],capture_output=True,text=True,timeout=15,
                           env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1"})
    assert child.returncode == 17, child.stderr
    abandoned = child.stdout.strip()
    assert json.loads(ledger.read_text())["reservations"][abandoned]["status"] == "active"
    assert json.loads(ledger.read_text())["reservations"][abandoned]["external_charges"] == {"journal":2000}
    with factory() as reservation:
        usage=reservation.check_usage(roots[0])
        assert usage["outstanding_full_reservations_bytes"] == 20_000
        reservation.release(artifacts_durable=True)
    # The scheduler can recover CPU slots; disk authority never infers release.
    assert json.loads(ledger.read_text())["reservations"][abandoned]["status"] == "active"


def test_sequential_child_reattachment_requires_previous_group_dead(setup, monkeypatch):
    factory, roots, _, _ = setup
    processes = {
        111: {"pid":111,"parent_pid":os.getpid(),"group_pid":111,"birth":"one"},
        222: {"pid":222,"parent_pid":os.getpid(),"group_pid":222,"birth":"two"},
    }
    alive = {111: True, 222: True}
    monkeypatch.setattr(resources, "_process", lambda pid: processes.get(pid))
    monkeypatch.setattr(resources, "_group_usage", lambda child:{"available":True,"rss_bytes":0,
        "live_processes":int(child is not None and alive[child["pid"]])})
    with factory() as reservation:
        reservation.check_usage(roots[0], child_pid=111)
        with pytest.raises(resources.DaemonResourceError, match="previous child.*alive"):
            reservation.check_usage(roots[0], child_pid=222)
        assert reservation.to_dict()["record"]["child"]["pid"] == 111
        alive[111] = False
        reservation.check_usage(roots[0], child_pid=222)
        row = reservation.to_dict()["record"]
        assert row["child"] == {"pid":222,"birth":"two"}
        assert row["prior_children"][0]["pid"] == 111
        assert row["prior_children"][0]["birth"] == "one"
        alive[222] = False
        reservation.release(artifacts_durable=True)


def test_external_and_private_bytes_share_attempt_cap(setup):
    factory,roots,ledger,_=setup
    attempt=roots[0]/"attempt";attempt.mkdir()
    private=attempt/"candidate";private.write_bytes(b"x"*20)
    with factory(storage_bytes=100) as reservation:
        reservation.check_usage(attempt)
        charged=reservation.account_external_bytes("a"*64,60)
        assert charged["usage"]["total_attempt_charged_bytes"]==80
        # The physical CAS copy counts once in the global inventory; the
        # immutable named amount is also attributed to this attempt's quota.
        (roots[1]/"cas").write_bytes(b"x"*60)
        usage=reservation.check_usage(attempt)
        assert usage["observed_apparent_bytes"]==80
        assert usage["outstanding_full_reservations_bytes"]==100
        assert usage["charged_bytes"]==180
        assert usage["total_attempt_charged_bytes"]==80
        private.write_bytes(b"x"*45)
        with pytest.raises(resources.DaemonResourceError,match="attempt storage"):
            reservation.check_usage(attempt)
        result=reservation.release(artifacts_durable=True)
        assert result["record"]["final_attempt_bytes"]==45
        assert result["record"]["final_external_charged_bytes"]==60
        assert result["record"]["final_total_charged_bytes"]==105
        assert result["record"]["attempt_exceeded_reservation"] is True
        assert result["record"]["final_accounting"]["observed_apparent_bytes"]==105
    assert private.read_bytes()==b"x"*45
    assert json.loads(ledger.read_text())["reservations"][reservation.reservation_id]["external_charges"]=={"a"*64:60}


def test_external_charge_idempotence_and_immutable_amount(setup):
    factory,roots,ledger,_=setup
    with factory() as reservation:
        first=reservation.account_external_bytes("journal",800)
        second=reservation.account_external_bytes("journal",800)
        assert first["already_charged"] is False and second["already_charged"] is True
        assert second["usage"]["external_charged_bytes"]==800
        with pytest.raises(resources.DaemonResourceError,match="amount changed"):
            reservation.account_external_bytes("journal",801)
        usage=reservation.check_usage(roots[0])
        assert usage["external_charged_bytes"]==800
        assert usage["total_attempt_charged_bytes"]==800
        assert json.loads(ledger.read_text())["reservations"][reservation.reservation_id]["external_charges"]=={"journal":800}
        reservation.release(artifacts_durable=True)
        with pytest.raises(resources.DaemonResourceError,match="not outstanding"):
            reservation.account_external_bytes("later",1)


def test_external_charge_rejected_before_staging_does_not_change_inventory(setup):
    factory,roots,_,_=setup
    with factory(storage_bytes=100) as reservation:
        reservation.check_usage(roots[0])
        reservation.account_external_bytes("journal",30)
        (roots[0]/"private").write_bytes(b"x"*40)
        with pytest.raises(resources.DaemonResourceError,match="combined"):
            reservation.account_external_bytes("candidate",31)
        assert reservation.to_dict()["record"]["external_charges"]=={"journal":30}
        reservation.account_external_bytes("candidate",30)
        assert reservation.check_usage(roots[0])["total_attempt_charged_bytes"]==100
        reservation.release(artifacts_durable=True)


@pytest.mark.parametrize("key,value", [("",1),("../escape",1),("a"*129,1),(True,1),
    ("number",True),("negative",-1),("float",1.0),("large",100_001)])
def test_external_charge_exact_bounds(setup,key,value):
    factory,_,_,_=setup
    with factory() as reservation:
        with pytest.raises(resources.DaemonResourceError):reservation.account_external_bytes(key,value)
        assert reservation.to_dict()["record"]["external_charges"]=={}
        reservation.release(artifacts_durable=True)


def test_external_charge_inventory_bound_and_repeated_last_key(setup):
    factory,_,ledger,_=setup
    with factory() as reservation:
        for index in range(128):reservation.account_external_bytes(f"artifact-{index}",1)
        assert reservation.account_external_bytes("artifact-127",1)["already_charged"] is True
        with pytest.raises(resources.DaemonResourceError,match="inventory bound"):
            reservation.account_external_bytes("artifact-128",1)
        assert len(json.loads(ledger.read_text())["reservations"][reservation.reservation_id]["external_charges"])==128
        reservation.release(artifacts_durable=True)


def test_failed_context_keeps_named_charges_durable(setup):
    factory,_,ledger,_=setup
    with pytest.raises(RuntimeError,match="copy failed"):
        with factory() as reservation:
            reservation.account_external_bytes("cas-sha256",500)
            raise RuntimeError("copy failed")
    row=json.loads(ledger.read_text())["reservations"][reservation.reservation_id]
    assert row["status"]=="retained" and row["external_charges"]=={"cas-sha256":500}
    released=reservation.release(artifacts_durable=True)
    assert released["record"]["final_total_charged_bytes"]==500


def test_corrupt_named_ledger_charge_is_not_ignored(setup):
    factory,roots,ledger,_=setup
    with factory() as reservation:
        reservation.account_external_bytes("journal",100)
        raw=ledger.read_bytes();value=json.loads(raw)
        value["reservations"][reservation.reservation_id]["external_charges"]["journal"]=True
        ledger.write_text(json.dumps(value))
        with pytest.raises(resources.DaemonResourceError,match="external charge bytes"):
            reservation.check_usage(roots[0])
        ledger.write_bytes(raw)
        reservation.release(artifacts_durable=True)


def test_finalization_checks_current_full_claim_once_and_preserves_other_claims(setup, monkeypatch):
    import fcntl
    factory, roots, ledger, scheduler = setup
    with factory() as retained:
        pass
    historical = json.loads(ledger.read_bytes())["reservations"][retained.reservation_id]
    attempt = roots[0] / "attempt"
    attempt.mkdir()
    (attempt / "output").write_bytes(b"exact output")
    with factory() as reservation:
        reservation.check_usage(attempt)
        original_inventory = resources._inventory
        scans = []
        def observed_inventory(paths, **kwargs):
            scans.append((tuple(paths), kwargs.get("strict", False)))
            # Each observation belongs to the one held ledger lock, including
            # the strict attempt scan; another descriptor cannot acquire it.
            with reservation.lock_path.open("rb") as other:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return original_inventory(paths, **kwargs)
        monkeypatch.setattr(resources, "_inventory", observed_inventory)
        result = reservation.finalize(attempt, artifacts_durable=True)
        monkeypatch.setattr(resources, "_inventory", original_inventory)
        assert scans == [((attempt,), True), (tuple(roots), False)]
        row = result["record"]
        assert row["last_usage"]["outstanding_full_reservations_bytes"] == 20_000
        assert row["last_usage"]["charged_bytes"] == 20_012
        assert row["final_accounting"]["outstanding_full_reservations_bytes"] == 10_000
        assert row["final_accounting"]["charged_bytes"] == 10_012
        assert row["last_usage"]["inventory"] == row["final_accounting"]["inventory"]
        assert row["final_attempt_bytes"] == row["final_total_charged_bytes"] == 12
        assert row["attempt_exceeded_reservation"] is False
        assert row["finalization_profile"]["global_inventory_count"] == 1
        assert result["resource_lease"]["released"] is True
        assert scheduler.snapshot()["allocated_child_process_slots"] == 0
        assert reservation.finalize(attempt, artifacts_durable=True) == result
    assert json.loads(ledger.read_bytes())["reservations"][retained.reservation_id] == historical
    assert (attempt / "output").read_bytes() == b"exact output"


def test_finalization_requires_durability_and_prior_binding(setup):
    factory, roots, _, _ = setup
    with factory() as reservation:
        with pytest.raises(resources.DaemonResourceError, match="durability"):
            reservation.finalize(roots[0])
        with pytest.raises(resources.DaemonResourceError, match="previously bound"):
            reservation.finalize(roots[0], artifacts_durable=True)
        reservation.check_usage(roots[0])
        reservation.finalize(roots[0], artifacts_durable=True)


@pytest.mark.parametrize("external", [False, True])
def test_finalization_records_attempt_overage_and_retains_claim(setup, external):
    factory, roots, ledger, _ = setup
    attempt = roots[0] / "attempt"
    attempt.mkdir()
    with pytest.raises(resources.DaemonResourceError, match="attempt storage"):
        with factory(storage_bytes=50) as reservation:
            reservation.check_usage(attempt)
            if external:
                reservation.account_external_bytes("existing-cas-output", 40)
            (attempt / "grown").write_bytes(b"x" * (11 if external else 51))
            reservation.finalize(attempt, artifacts_durable=True)
    row = json.loads(ledger.read_bytes())["reservations"][reservation.reservation_id]
    assert row["status"] == "retained"
    assert row["last_usage"]["total_attempt_charged_bytes"] == 51
    assert row["artifacts_durable_asserted"] is False
    assert "released_at" not in row and "final_accounting" not in row
    # Explicit audited recovery keeps its original behavior and preserves data.
    legacy = reservation.release(artifacts_durable=True)
    assert legacy["record"]["attempt_exceeded_reservation"] is True


def test_finalization_does_not_drop_claim_to_make_global_capacity_fit(setup):
    factory, roots, ledger, _ = setup
    with pytest.raises(resources.DaemonResourceError, match="capacity"):
        with factory() as reservation:
            reservation.check_usage(roots[0])
            before = reservation.to_dict()["record"]["last_usage"]
            (roots[1] / "other-owner-growth").write_bytes(b"x" * 95_000)
            reservation.finalize(roots[0], artifacts_durable=True)
    row = json.loads(ledger.read_bytes())["reservations"][reservation.reservation_id]
    assert row["status"] == "retained" and row["last_usage"] == before
    assert "released_at" not in row
    # Legacy explicit release can still reconcile stopped outputs after failure.
    assert reservation.release(artifacts_durable=True)["record"]["final_accounting"]["charged_bytes"] == 95_000


def test_finalization_rechecks_attempt_identity_after_global_inventory(setup, monkeypatch):
    factory, roots, ledger, _ = setup
    attempt = roots[0] / "attempt"
    attempt.mkdir()
    original_inventory = resources._inventory
    def replaced_after_scan(paths, **kwargs):
        observed = original_inventory(paths, **kwargs)
        if tuple(paths) == tuple(roots):
            attempt.rename(roots[0] / "old-attempt")
            attempt.mkdir()
        return observed
    with pytest.raises(resources.DaemonResourceError, match="identity changed"):
        with factory() as reservation:
            reservation.check_usage(attempt)
            monkeypatch.setattr(resources, "_inventory", replaced_after_scan)
            reservation.finalize(attempt, artifacts_durable=True)
    row = json.loads(ledger.read_bytes())["reservations"][reservation.reservation_id]
    assert row["status"] == "retained" and "released_at" not in row


@pytest.mark.skipif(sys.platform != "linux", reason="Linux process-group accounting")
def test_finalization_requires_real_child_group_dead_and_records_live_observation(setup):
    factory, roots, ledger, _ = setup
    with factory() as reservation:
        child = subprocess.Popen([sys.executable, "-c", "import sys; print('ready',flush=True);sys.stdin.buffer.read(1)"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, start_new_session=True)
        try:
            assert child.stdout.readline() == b"ready\n"
            reservation.check_usage(roots[0], child_pid=child.pid)
            with pytest.raises(resources.DaemonResourceError, match="still alive"):
                reservation.finalize(roots[0], artifacts_durable=True)
            row = json.loads(ledger.read_bytes())["reservations"][reservation.reservation_id]
            assert row["status"] == "active"
            assert row["last_usage"]["group_rss"]["live_processes"] == 1
            assert "released_at" not in row
        finally:
            child.communicate(b"x", timeout=5)
        assert reservation.finalize(roots[0], artifacts_durable=True)["status"] == "released"


def test_finalization_preserves_rss_failure_usage(setup, monkeypatch):
    factory, roots, ledger, _ = setup
    with factory(memory_mb=1) as reservation:
        reservation.check_usage(roots[0])
        monkeypatch.setattr(resources, "_group_usage", lambda child: {"available": True, "live_processes": 1, "rss_bytes": 2 * 1024 * 1024})
        with pytest.raises(resources.DaemonResourceError, match="RSS"):
            reservation.finalize(roots[0], artifacts_durable=True)
        row = json.loads(ledger.read_bytes())["reservations"][reservation.reservation_id]
        assert row["last_usage"]["group_rss"]["rss_bytes"] == 2 * 1024 * 1024
        assert row["status"] == "active" and "released_at" not in row
        monkeypatch.setattr(resources, "_group_usage", lambda child: {"available": True, "live_processes": 0, "rss_bytes": 0})
        reservation.finalize(roots[0], artifacts_durable=True)


# Opt-in owned live census controls. These fixtures coordinate real filesystem
# publication at exact scanner boundaries; they do not model the scanner.


class _OwnedLiveScandirProxy:
    """Keep the real immediate-open scandir iterator and context protocol."""
    def __init__(self, actual, *, transform=None, after_complete=None, prefetched=()):
        self.actual = actual
        self.transform = transform
        self.after_complete = after_complete
        self.prefetched = list(prefetched)
    def __iter__(self):
        return self
    def __next__(self):
        entry = self.prefetched.pop(0) if self.prefetched else next(self.actual)
        return self.transform(entry) if self.transform is not None else entry
    def __enter__(self):
        self.actual.__enter__()
        return self
    def close(self):
        self.actual.close()
    def __exit__(self, exc_type, exc, traceback):
        result = self.actual.__exit__(exc_type, exc, traceback)
        if exc_type is None and self.after_complete is not None:
            self.after_complete()
        return result


def _atomic_census_publication(monkeypatch, module, directory, boundary, *,
                               before_publish=None, publications=1):
    directory = Path(directory)
    staging, published = directory / ".capsule-staging", directory / "published"
    (staging / "nested").mkdir(parents=True)
    payload = b"formal source payload\n" * 5
    metadata = b'{"schema":"fixture"}\n'
    (staging / "nested" / "payload.txt").write_bytes(payload)
    (staging / "metadata.json").write_bytes(metadata)
    state = {"current": staging, "other": published, "publications": 0,
             "payload_bytes": len(payload) + len(metadata)}
    actual_scandir = module.os.scandir

    def publish():
        if state["publications"] >= publications:
            return
        if before_publish is not None:
            before_publish()
        os.rename(state["current"], state["other"])
        state["current"], state["other"] = state["other"], state["current"]
        state["publications"] += 1

    class Entry:
        def __init__(self, entry, target):
            self.path = entry.path
            self._entry, self._target = entry, target
        def __getattr__(self, name):
            return getattr(self._entry, name)
        def stat(self, *, follow_symlinks):
            assert follow_symlinks is False
            if Path(self.path) == self._target:
                publish()
            return self._entry.stat(follow_symlinks=False)

    def scan(path):
        named = Path(path)
        if boundary == "scandir" and named == state["current"]:
            publish()
        # Open at the os.scandir call boundary, not delayed __enter__ time.
        actual = actual_scandir(path)
        target = state["current"] / "nested" / "payload.txt"
        transform = (lambda entry: Entry(entry, target)) if boundary == "entry-stat" else None
        after = publish if boundary == "pending" and named == directory else None
        return _OwnedLiveScandirProxy(actual, transform=transform, after_complete=after)

    monkeypatch.setattr(module.os, "scandir", scan)
    return state



@pytest.mark.parametrize("boundary", ["pending", "scandir"])
def test_owned_live_census_reports_real_atomic_publication(setup, monkeypatch, boundary):
    _, roots, _, _ = setup
    root = roots[0]
    frozen = resources._root_identity(root)
    state = _atomic_census_publication(monkeypatch, resources, root, boundary)
    with pytest.raises(resources.OwnedInventoryDisappearance) as caught:
        resources._inventory([root], strict=True, report_owned_disappearance=True)
    event = caught.value
    assert type(event) is resources.OwnedInventoryDisappearance
    assert event.frozen_root == frozen
    assert root in Path(event.vanished_path).parents
    partial = event.partial_inventory
    assert set(partial) == {"apparent_bytes", "entry_count", "symlink_count", "special_file_count"}
    assert partial["entry_count"] > 0
    assert partial["symlink_count"] == partial["special_file_count"] == 0
    assert state["publications"] == 1
    # Detached metadata cannot be rewritten by a consumer.
    event.frozen_root["path"] = "/foreign"
    event.partial_inventory["apparent_bytes"] = 999_999
    assert event.frozen_root == frozen and event.partial_inventory == partial
    with pytest.raises(AttributeError):
        event.vanished_path = "/foreign"
    completed = resources._inventory([root], strict=True)
    assert completed == {"apparent_bytes": state["payload_bytes"], "entry_count": 4,
                         "symlink_count": 0, "special_file_count": 0}
    assert (state["current"] / "nested/payload.txt").read_bytes() == b"formal source payload\n" * 5


@pytest.mark.parametrize("flag", [None, 0, 1, "yes"], ids=["none", "zero", "one", "text"])
def test_owned_live_census_flag_requires_exact_boolean(tmp_path, flag):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(resources.DaemonResourceError, match="boolean"):
        resources._inventory([root], strict=True, report_owned_disappearance=flag)


def test_owned_live_census_reporting_requires_strict_true(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(resources.DaemonResourceError, match="strict=True"):
        resources._inventory([root], strict=False, report_owned_disappearance=True)


def test_owned_live_census_default_does_not_reclassify_strict_failure(setup, monkeypatch):
    _, roots, _, _ = setup
    _atomic_census_publication(monkeypatch, resources, roots[0], "entry-stat")
    with pytest.raises((FileNotFoundError, resources.DaemonResourceError)) as caught:
        resources._inventory([roots[0]], strict=True)
    assert not isinstance(caught.value, resources.OwnedInventoryDisappearance)


def test_owned_live_census_false_missing_file_is_not_a_typed_disappearance(setup, monkeypatch):
    _, roots, _, _ = setup
    root = roots[0]
    target = root / "present"
    target.write_bytes(b"must remain accounted")
    actual = resources.os.scandir
    failure = FileNotFoundError(2, "injected stale stat", str(target))
    class Entry:
        def __init__(self, entry):
            self.path, self._entry = entry.path, entry
        def stat(self, *, follow_symlinks):
            assert follow_symlinks is False
            if Path(self.path) == target:
                raise failure
            return self._entry.stat(follow_symlinks=False)
    def scan(path):
        return _OwnedLiveScandirProxy(actual(path), transform=Entry)
    monkeypatch.setattr(resources.os, "scandir", scan)
    with pytest.raises(FileNotFoundError) as caught:
        resources._inventory([root], strict=True, report_owned_disappearance=True)
    assert caught.value is failure and target.read_bytes() == b"must remain accounted"


@pytest.mark.parametrize("replacement", ["root", "ancestor"])
def test_owned_live_census_root_or_ancestor_replacement_never_becomes_retry(tmp_path, monkeypatch, replacement):
    parent = tmp_path / "ancestor"
    root = parent / "owned"
    root.mkdir(parents=True)
    queued = root / "queued"
    queued.mkdir()
    (queued / "kept").write_bytes(b"retained")
    actual = resources.os.scandir
    changed = []
    def scan(path):
        actual_entries = actual(path)
        def after_complete():
            if Path(path) == root and not changed:
                selected = root if replacement == "root" else parent
                backup = selected.with_name(selected.name + "-retained")
                selected.rename(backup)
                selected.mkdir()
                changed.append(backup)
        return _OwnedLiveScandirProxy(actual_entries, after_complete=after_complete)
    monkeypatch.setattr(resources.os, "scandir", scan)
    with pytest.raises(resources.DaemonResourceError) as caught:
        resources._inventory([root], strict=True, report_owned_disappearance=True)
    assert not isinstance(caught.value, resources.OwnedInventoryDisappearance)
    kept = changed[0] / ("queued/kept" if replacement == "root" else "owned/queued/kept")
    assert kept.read_bytes() == b"retained"



def _owned_live_fail_entry_stat(monkeypatch, target):
    actual = resources.os.scandir
    failure = FileNotFoundError(2, "injected leaf stat disappearance", str(target))
    class Entry:
        def __init__(self, entry):
            self.path, self._entry = entry.path, entry
        def stat(self, *, follow_symlinks):
            assert follow_symlinks is False
            if Path(self.path) == target:
                raise failure
            return self._entry.stat(follow_symlinks=False)
    def scan(path):
        return _OwnedLiveScandirProxy(actual(path), transform=Entry)
    monkeypatch.setattr(resources.os, "scandir", scan)


def test_owned_live_census_rechecks_internal_ancestor_before_typing_loss(setup, monkeypatch):
    _, roots, _, _ = setup
    root, branch = roots[0], roots[0] / "branch"
    target = branch / "queued"
    target.mkdir(parents=True)
    (target / "payload").write_bytes(b"retained original")
    original_lstat = Path.lstat
    replacements = []
    def lstat(path):
        # This is reached only after the real queued DIR stat observed its
        # UID/kind/inode; replace its already checked surviving ancestor.
        if path == target and not replacements:
            backup = root / "branch-retained"
            branch.rename(backup)
            branch.mkdir()
            replacements.append(backup)
            raise FileNotFoundError(2, "lost queued directory after checked ancestor", str(path))
        return original_lstat(path)
    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(resources.DaemonResourceError) as caught:
        resources._inventory([root], strict=True, report_owned_disappearance=True)
    assert not isinstance(caught.value, resources.OwnedInventoryDisappearance)
    assert (replacements[0] / "queued/payload").read_bytes() == b"retained original"


def test_owned_live_census_missing_then_present_leaf_is_not_retry_authority(setup, monkeypatch):
    _, roots, _, _ = setup
    root, target = roots[0], roots[0] / "queued"
    target.mkdir()
    (target / "payload").write_bytes(b"retained original")
    retained = root / "retained-queued"
    actual_scandir, actual_lstat = resources.os.scandir, Path.lstat
    moved, republished = [], []
    def scan(path):
        def after_complete():
            if Path(path) == root and not moved:
                target.rename(retained)
                moved.append(True)
        return _OwnedLiveScandirProxy(actual_scandir(path), after_complete=after_complete)
    def lstat(path):
        if path == target and moved and not republished:
            try:
                actual_lstat(path)
            except FileNotFoundError as missing:
                target.mkdir()
                (target / "new-payload").write_bytes(b"new directory must not become retry authority")
                republished.append(True)
                raise missing
        return actual_lstat(path)
    monkeypatch.setattr(resources.os, "scandir", scan)
    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(resources.DaemonResourceError, match="reappeared") as caught:
        resources._inventory([root], strict=True, report_owned_disappearance=True)
    assert not isinstance(caught.value, resources.OwnedInventoryDisappearance)
    assert moved == republished == [True]
    assert (retained / "payload").read_bytes() == b"retained original"



@pytest.mark.parametrize("kind", ["symlink-file", "symlink-directory", "fifo"])
def test_owned_live_census_rejects_declared_unsafe_leaf(tmp_path, monkeypatch, kind):
    root = tmp_path / "scan"
    root.mkdir(mode=0o700)
    leaf = root / "unsafe-leaf"
    payload = b"retained ordinary payload\n"
    if kind == "symlink-directory":
        target = root / "retained-target-directory"
        target.mkdir(mode=0o700)
        retained = target / "payload.txt"
    else:
        target = root / ("retained-target-file" if kind == "symlink-file" else "retained-payload.txt")
        retained = target
    retained.write_bytes(payload)
    assert not os.path.lexists(leaf)
    actual_inventory = resources._inventory
    calls, partials = [], []
    def inventory(roots, **kwargs):
        calls.append({"roots": list(roots), **kwargs})
        try:
            return actual_inventory(roots, **kwargs)
        except resources.OwnedInventoryDisappearance as event:
            partials.append(event.partial_inventory)
            raise
    monkeypatch.setattr(resources, "_inventory", inventory)
    try:
        if kind == "fifo":
            os.mkfifo(leaf, 0o600)
        else:
            leaf.symlink_to(target.absolute(), target_is_directory=kind == "symlink-directory")
        with pytest.raises(resources.DaemonResourceError, match="symlink|nonregular") as caught:
            resources._inventory([root], strict=True, report_owned_disappearance=True)
        assert not isinstance(caught.value, resources.OwnedInventoryDisappearance)
        assert calls == [{"roots": [root], "strict": True, "report_owned_disappearance": True}]
        assert partials == []
        assert retained.read_bytes() == payload
    finally:
        leaf.unlink(missing_ok=True)
    assert not os.path.lexists(leaf) and retained.read_bytes() == payload


# Refinement of the historical prototype: only a previously owned queued DIR
# may supply typed retry authority. These controls add no new alias permission.
def _owned_live_unobserved_leaf_disappearance(monkeypatch, module, root):
    target = Path(root) / "first-stat-unknown-leaf"
    target.write_bytes(b"the scanner has not observed this leaf UID or kind")
    actual, removed = module.os.scandir, []
    class Entry:
        def __init__(self, entry):
            self.path, self._entry = entry.path, entry
        def __getattr__(self, name):
            return getattr(self._entry, name)
        def stat(self, *, follow_symlinks):
            assert follow_symlinks is False
            if Path(self.path) == target and not removed:
                target.unlink()
                removed.append(True)
            return self._entry.stat(follow_symlinks=False)
    def scan(path):
        return _OwnedLiveScandirProxy(actual(path), transform=Entry)
    monkeypatch.setattr(module.os, "scandir", scan)
    return target, removed


def test_owned_live_census_first_stat_unknown_leaf_disappearance_is_fatal(setup, monkeypatch):
    _, roots, _, _ = setup
    target, removed = _owned_live_unobserved_leaf_disappearance(monkeypatch, resources, roots[0])
    with pytest.raises(FileNotFoundError) as caught:
        resources._inventory([roots[0]], strict=True, report_owned_disappearance=True)
    assert not isinstance(caught.value, resources.OwnedInventoryDisappearance)
    assert removed == [True] and not target.exists()


def test_owned_live_census_missing_ancestor_of_known_queued_directory_is_fatal(setup, monkeypatch):
    _, roots, _, _ = setup
    root = roots[0]
    branch, retained = root / "branch", root / "retained-branch"
    target = branch / "queued"
    target.mkdir(parents=True)
    (target / "payload").write_bytes(b"retain ancestor evidence")
    actual, moved = resources.os.scandir, []
    def scan(path):
        def after_complete():
            if Path(path) == branch and not moved:
                branch.rename(retained)
                moved.append(True)
        return _OwnedLiveScandirProxy(actual(path), after_complete=after_complete)
    monkeypatch.setattr(resources.os, "scandir", scan)
    with pytest.raises(FileNotFoundError) as caught:
        resources._inventory([root], strict=True, report_owned_disappearance=True)
    assert not isinstance(caught.value, resources.OwnedInventoryDisappearance)
    assert moved == [True] and (retained / "queued/payload").read_bytes() == b"retain ancestor evidence"


@pytest.mark.parametrize("observation", ["permission", "symlink", "fifo", "file", "uid"])
def test_owned_live_census_known_queued_directory_nonmissing_faults_never_become_retry(setup, monkeypatch, observation):
    import stat
    _, roots, _, _ = setup
    root, target = roots[0], roots[0] / "queued"
    target.mkdir()
    (target / "payload").write_bytes(b"unchanged ordinary fixture")
    actual_lstat, seen = Path.lstat, []
    def lstat(path):
        current = actual_lstat(path)
        if path == target and not seen:
            seen.append(True)
            if observation == "permission":
                raise PermissionError(13, "synthetic queued-leaf permission refusal", str(path))
            # Deliberately synthetic stat observations. Real static alias/FIFO
            # fixtures remain in the separate original physical6 profile.
            fields = list(current)
            if observation == "uid":
                fields[4] = os.geteuid() + 1
            else:
                fields[0] = {"symlink": stat.S_IFLNK, "fifo": stat.S_IFIFO, "file": stat.S_IFREG}[observation] | 0o600
            return os.stat_result(fields)
        return current
    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises((PermissionError, resources.DaemonResourceError)) as caught:
        resources._inventory([root], strict=True, report_owned_disappearance=True)
    assert not isinstance(caught.value, resources.OwnedInventoryDisappearance)
    assert seen == [True] and (target / "payload").read_bytes() == b"unchanged ordinary fixture"
