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


def test_production_storage_cap_is_two_hundred_fifty_gb_without_admission(tmp_path):
    root = tmp_path / "outputs"
    root.mkdir()
    ledger = tmp_path / "disk.json"
    reservation = resources.DaemonResourceReservation(
        ledger, roots=[root], storage_bytes=7, memory_mb=1)
    assert resources.MAX_STORAGE_BYTES == 250_000_000_000
    assert resources.MAX_INVENTORY_ENTRIES == 4_000_000
    assert reservation._read() == {
        "schema": resources.SCHEMA, "roots": reservation.root_identities,
        "limit_bytes": 250_000_000_000, "reservations": {},
    }
    assert reservation.to_dict()["storage_limit_bytes"] == 250_000_000_000
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
    monkeypatch.setattr(resources.shutil, "disk_usage", lambda root: SimpleNamespace(free=180_000_000_000))
    headroom = 118_331_851_778
    usage = reservation._account(ledger, additional=headroom)
    assert usage["outstanding_full_reservations_bytes"] == 31_465_000_000
    assert usage["charged_bytes"] == usage["limit_bytes"] == 250_000_000_000
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


@pytest.fixture(params=[50_000_000_000, 60_000_000_000, 62_000_000_000, 75_000_000_000, 80_000_000_000, 85_000_000_000, 87_000_000_000, 90_000_000_000, 145_000_000_000, 160_000_000_000, 200_000_000_000, 220_000_000_000],
                ids=["fifty-gb", "sixty-gb", "sixty-two-gb", "seventy-five-gb", "eighty-gb", "eighty-five-gb", "eighty-seven-gb", "ninety-gb", "one-hundred-forty-five-gb", "one-hundred-sixty-gb", "two-hundred-gb", "two-hundred-twenty-gb"])
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
    new_prefix = b'{"limit_bytes":250000000000,'
    assert raw.startswith(old_prefix)
    # Model the explicit one-time edit on a tiny, test-owned fixture. This
    # neither introduces an implicit migration API nor acquires a reservation.
    migrated = new_prefix + raw[len(old_prefix):]
    backup = ledger.with_name("historical-disk.json")
    backup.write_bytes(raw)
    with reservation._locked():
        assert ledger.read_bytes() == raw
        reservation._write({**historical, "limit_bytes": 250_000_000_000})
    current = reservation._read()
    assert current == {**historical, "limit_bytes": 250_000_000_000}
    assert current["reservations"] == historical["reservations"]
    assert migrated[len(new_prefix):] == raw[len(old_prefix):]
    usage = reservation._account(current, additional=13)
    assert usage["limit_bytes"] == 250_000_000_000
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
    ("timeout_seconds",-1),("timeout_seconds",True),("timeout_seconds",float("nan")),
    ("ledger_lock_timeout_seconds",-1),("ledger_lock_timeout_seconds",True),
    ("ledger_lock_timeout_seconds",float("nan")),("ledger_lock_timeout_seconds",float("inf")),
    ("ledger_lock_timeout_seconds",600.001),("ledger_lock_timeout_seconds","180")])
def test_invalid_requests_fail_before_ledger_mutation(setup, field, value):
    factory, _, ledger, _ = setup
    with pytest.raises(resources.DaemonResourceError):
        factory(**{field:value})
    assert not ledger.exists()


def test_overlapping_missing_and_symlink_roots_rejected(setup, tmp_path):
    _, roots, ledger, _ = setup
    nested=roots[0]/"nested"; nested.mkdir()
    alias=tmp_path/"alias"
    try:
        alias.symlink_to(roots[0],target_is_directory=True)
        for selected in ([roots[0],roots[0]], [roots[0],nested], [alias], [tmp_path/"missing"]):
            with pytest.raises(resources.DaemonResourceError):
                resources.DaemonResourceReservation(ledger,roots=selected,storage_bytes=1,memory_mb=1)
    finally:
        alias.unlink(missing_ok=True)  # This fixture owns the alias, not its target.


@pytest.mark.parametrize("kind", ["symlink","fifo","hardlink"])
def test_ledger_aliases_and_special_files_rejected_without_opening_fifo(setup, tmp_path, kind):
    factory, _, ledger, _ = setup
    try:
        if kind=="fifo": os.mkfifo(ledger)
        elif kind=="symlink": ledger.symlink_to(tmp_path/"other")
        else:
            other=tmp_path/"other"; other.write_text("{}")
            os.link(other,ledger)
        with pytest.raises(resources.DaemonResourceError):
            factory().__enter__()
    finally:
        try:
            ledger.unlink(missing_ok=True)
        finally:
            if kind=="hardlink":
                (tmp_path/"other").unlink(missing_ok=True)  # Both fixture-owned links.


def test_shared_inventory_counts_symlinks_and_special_files_without_following(setup, tmp_path):
    factory, roots, _, _ = setup
    outside=tmp_path/"large-unowned";outside.write_bytes(b"x"*150_000)
    link=roots[1]/"cache-link"
    try:
        link.symlink_to(outside)
        os.mkfifo(roots[1]/"unowned-fifo")
        expected=link.lstat().st_size+(roots[1]/"unowned-fifo").lstat().st_size
        with factory() as reservation:
            usage=reservation.check_usage(roots[0])
            assert usage["observed_apparent_bytes"]==expected
            assert usage["inventory"]["symlink_count"]==1
            assert usage["inventory"]["special_file_count"]==1
            reservation.release(artifacts_durable=True)
    finally:
        try:
            link.unlink(missing_ok=True)  # Never unlink the target.
        finally:
            (roots[1]/"unowned-fifo").unlink(missing_ok=True)


@pytest.mark.parametrize("kind",["symlink","fifo"])
def test_bound_attempt_rejects_unsafe_output_entries(setup,kind):
    factory,roots,_,_=setup
    attempt=roots[0]/"attempt";attempt.mkdir()
    unsafe=attempt/"unsafe"
    try:
        if kind=="symlink":unsafe.symlink_to(roots[1])
        else:os.mkfifo(unsafe)
        with factory() as reservation:
            with pytest.raises(resources.DaemonResourceError,match="attempt"):
                reservation.check_usage(attempt)
            unsafe.unlink()  # Test-owned entry only; production never removes data.
            reservation.release(artifacts_durable=True)
    finally:
        unsafe.unlink(missing_ok=True)  # Also covers admission/assertion failure.


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



# These controls use private filesystem state only. Injected leases below are
# explicitly fictional unit controls and establish no actual native custody.
class _AdmissionDeadlineClock:
    def __init__(self, actual, now=100.0):
        self.actual = actual
        self.now = now
    def monotonic(self):
        return self.now
    def __getattr__(self, name):
        return getattr(self.actual, name)


class _AdmissionDeadlineProxy:
    def __init__(self, actual, **overrides):
        self.actual = actual
        self.overrides = overrides
    def __getattr__(self, name):
        return self.overrides.get(name, getattr(self.actual, name))


def _host_admission_clock(monkeypatch):
    clock = _AdmissionDeadlineClock(resources.time)
    # Replace module references, never the process-wide time.monotonic function.
    monkeypatch.setattr(resources, "time", clock)
    monkeypatch.setattr(resources.native_deadlines, "time", clock)
    return clock


@pytest.mark.parametrize("mode", ["ordinary", "strict", "owned_strict"])
@pytest.mark.parametrize("slow_operation", ["scandir", "entry_stat"])
def test_admission_inventory_checks_deadline_after_real_io(tmp_path, monkeypatch, mode, slow_operation):
    root = tmp_path / "inventory"
    root.mkdir()
    (root / "payload").write_bytes(b"actual private contents")
    (root / "payload2").write_bytes(b"second actual entry proves closure")
    clock = _host_admission_clock(monkeypatch)
    actual_os = resources.os
    seen = []
    opened = []
    class Scandir(_OwnedLiveScandirProxy):
        def __exit__(self, *args):
            result = super().__exit__(*args)
            self.closed_by_context = True
            return result
    class Entry:
        def __init__(self, actual):
            self.actual = actual
        def __getattr__(self, name):
            return getattr(self.actual, name)
        def stat(self, **kwargs):
            value = self.actual.stat(**kwargs)
            seen.append("entry_stat")
            if slow_operation == "entry_stat":
                clock.now = 111.0
            return value
    def scandir(path):
        result = actual_os.scandir(path)
        seen.append("scandir")
        if slow_operation == "scandir":
            clock.now = 111.0
        proxy = Scandir(result, transform=Entry)
        proxy.closed_by_context = False
        opened.append(proxy)
        return proxy
    monkeypatch.setattr(resources, "os", _AdmissionDeadlineProxy(actual_os, scandir=scandir))
    with resources.native_deadlines.resource_admission_deadline(
            work_deadline_monotonic=110.0, native_deadline_monotonic=120.0):
        with pytest.raises(resources.native_deadlines.ResourceAdmissionDeadlineError):
            resources._inventory([root], strict=mode != "ordinary",
                                 report_owned_disappearance=mode == "owned_strict")
    assert slow_operation in seen
    assert opened and all(item.closed_by_context for item in opened)
    for item in opened:
        assert next(item.actual, None) is None
    assert resources.native_deadlines.resource_operation_deadline() is None


def test_admission_account_checks_deadline_after_disk_usage(setup, monkeypatch):
    factory, roots, ledger_path, scheduler = setup
    owner = factory()
    ledger = owner._read()
    clock = _host_admission_clock(monkeypatch)
    original = resources.shutil
    calls = []
    def disk_usage(root):
        value = original.disk_usage(root)
        calls.append(str(root))
        clock.now = 111.0
        return value
    monkeypatch.setattr(resources, "shutil", _AdmissionDeadlineProxy(original, disk_usage=disk_usage))
    with resources.native_deadlines.resource_admission_deadline(
            work_deadline_monotonic=110.0, native_deadline_monotonic=120.0):
        with pytest.raises(resources.native_deadlines.ResourceAdmissionDeadlineError):
            owner._account(ledger, additional=owner.storage_bytes)
    assert calls == [str(roots[0])]
    assert not ledger_path.exists() and owner._record is None and owner._lease is None


@pytest.mark.parametrize("parent_scope", [False, True])
@pytest.mark.parametrize("failure_stage", ["before_record", "native_acquire"])
def test_admission_failure_before_native_grant_keeps_exact_custody(setup, monkeypatch, parent_scope, failure_stage):
    from contextlib import contextmanager, nullcontext
    factory, roots, ledger_path, scheduler = setup
    owner = factory()
    clock = _host_admission_clock(monkeypatch)
    native_calls = []
    @contextmanager
    def admission_scope():
        with resources.native_deadlines.resource_admission_deadline(
                work_deadline_monotonic=110.0, native_deadline_monotonic=150.0):
            yield
    monkeypatch.setattr(owner, "_admission_scope", admission_scope)
    primary = resources.native_deadlines.ResourceAdmissionDeadlineError("fictional injected native refusal")
    def acquire(*args):
        native_calls.append("acquire")
        clock.now = 111.0
        raise primary
    monkeypatch.setattr(owner, "_acquire_native_lease", acquire)
    if failure_stage == "before_record":
        def account(*args, **kwargs):
            clock.now = 111.0
            raise primary
        monkeypatch.setattr(owner, "_account", account)
    outer = resources.native_deadlines.resource_admission_deadline(
        work_deadline_monotonic=110.0, native_deadline_monotonic=150.0) if parent_scope else nullcontext()
    with outer:
        previous = resources.native_deadlines.resource_operation_deadline()
        with pytest.raises(resources.native_deadlines.ResourceAdmissionDeadlineError) as raised:
            owner.__enter__()
        assert raised.value is primary
        assert resources.native_deadlines.resource_operation_deadline() is previous
    assert owner._lease is None and owner._cleanup_error is None
    if failure_stage == "before_record":
        assert native_calls == [] and owner._record is None and not ledger_path.exists()
    else:
        assert native_calls == ["acquire"]
        assert owner._record["status"] == "retained"
        assert json.loads(ledger_path.read_text())["reservations"][owner.reservation_id]["status"] == "retained"
    assert scheduler.snapshot()["allocated"]["cpu_slots"] == 0


@pytest.mark.parametrize("parent_scope", [False, True])
@pytest.mark.parametrize("cleanup_failure", ["none", "retain", "release", "both"])
def test_admission_expiry_unwinds_before_independent_cleanup_attempts(setup, monkeypatch, parent_scope, cleanup_failure):
    from contextlib import contextmanager, nullcontext
    factory, roots, ledger_path, scheduler = setup
    owner = factory()
    clock = _host_admission_clock(monkeypatch)
    events = []
    primary = resources.native_deadlines.ResourceAdmissionDeadlineError("fictional post-grant expiry")
    class FictionalLease:
        def release(self):
            operation = resources.native_deadlines.resource_operation_deadline()
            events.append(("release", operation))
            if cleanup_failure in {"release", "both"}:
                raise RuntimeError("fictional release failed; no release assertion")
    lease = FictionalLease()
    @contextmanager
    def admission_scope():
        with resources.native_deadlines.resource_admission_deadline(
                work_deadline_monotonic=110.0, native_deadline_monotonic=150.0):
            yield
    monkeypatch.setattr(owner, "_admission_scope", admission_scope)
    monkeypatch.setattr(owner, "_acquire_native_lease", lambda *args: lease)
    original_update = owner._update
    def update(**changes):
        if changes.get("status") == "active":
            clock.now = 111.0
            raise primary
        return original_update(**changes)
    monkeypatch.setattr(owner, "_update", update)
    original_retain = owner._retain
    def retain(reason):
        operation = resources.native_deadlines.resource_operation_deadline()
        events.append(("retain", operation))
        if cleanup_failure in {"retain", "both"}:
            raise OSError("fictional retention I/O failure")
        return original_retain(reason)
    monkeypatch.setattr(owner, "_retain", retain)
    outer = resources.native_deadlines.resource_admission_deadline(
        work_deadline_monotonic=110.0, native_deadline_monotonic=150.0) if parent_scope else nullcontext()
    with outer:
        previous = resources.native_deadlines.resource_operation_deadline()
        with pytest.raises(resources.native_deadlines.ResourceAdmissionDeadlineError) as raised:
            owner.__enter__()
        assert raised.value is primary
        assert resources.native_deadlines.resource_operation_deadline() is previous
    assert [name for name, _ in events] == ["retain", "release"]
    for name, operation in events:
        if parent_scope:
            assert operation.cleanup_only and operation.native_deadline_monotonic == 150.0
        else:
            assert operation is None
    expected = {"none": None, "retain": "OSError", "release": "RuntimeError", "both": "OSError+RuntimeError"}
    assert owner._cleanup_error == expected[cleanup_failure]
    expected_status = "reserved" if cleanup_failure in {"retain", "both"} else "retained"
    assert owner._record["status"] == expected_status
    assert json.loads(ledger_path.read_text())["reservations"][owner.reservation_id]["status"] == expected_status
    # The injected lease is fictional. The actual private scheduler never grants.
    assert scheduler.snapshot()["allocated"]["cpu_slots"] == 0



def test_admission_expired_original_native_end_keeps_cleanup_unknown(setup, monkeypatch):
    from contextlib import contextmanager
    factory, roots, ledger_path, scheduler = setup
    owner = factory()
    clock = _host_admission_clock(monkeypatch)
    events = []
    primary = resources.native_deadlines.ResourceAdmissionDeadlineError("fictional post-grant native-end expiry")
    class FictionalLease:
        def release(self):
            events.append("release")
    lease = FictionalLease()
    @contextmanager
    def admission_scope():
        with resources.native_deadlines.resource_admission_deadline(
                work_deadline_monotonic=110.0, native_deadline_monotonic=120.0):
            yield
    monkeypatch.setattr(owner, "_admission_scope", admission_scope)
    monkeypatch.setattr(owner, "_acquire_native_lease", lambda *args: lease)
    original_update = owner._update
    def update(**changes):
        if changes.get("status") == "active":
            clock.now = 121.0
            raise primary
        return original_update(**changes)
    monkeypatch.setattr(owner, "_update", update)
    def retain(reason):
        events.append("retain")
        pytest.fail("expired original native end must not be renewed")
    monkeypatch.setattr(owner, "_retain", retain)
    with resources.native_deadlines.resource_admission_deadline(
            work_deadline_monotonic=110.0, native_deadline_monotonic=120.0):
        previous = resources.native_deadlines.resource_operation_deadline()
        with pytest.raises(resources.native_deadlines.ResourceAdmissionDeadlineError) as raised:
            owner.__enter__()
        assert raised.value is primary
        assert resources.native_deadlines.resource_operation_deadline() is previous
        assert previous.native_deadline_monotonic == 120.0
    assert events == []
    assert owner._lease is lease and owner._record["status"] == "reserved"
    assert owner._cleanup_error == "ResourceAdmissionDeadlineError"
    assert json.loads(ledger_path.read_text())["reservations"][owner.reservation_id]["status"] == "reserved"
    # No successful release is asserted; the injected lease is a unit fiction.
    assert scheduler.snapshot()["allocated"]["cpu_slots"] == 0


# Failure diagnostics preserve typed facts without exporting exception messages.
def test_retention_real_lock_timeout_keeps_full_claim_and_typed_observation(setup):
    import fcntl
    factory, _, ledger_path, scheduler = setup
    owner = factory(ledger_lock_timeout_seconds=0.01)
    owner.__enter__()
    before = ledger_path.read_bytes()
    descriptor = os.open(owner.lock_path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        primary = RuntimeError('original check failed')
        assert owner.__exit__(RuntimeError, primary, None) is False
    finally:
        os.close(descriptor)
    assert ledger_path.read_bytes() == before
    value = owner.to_dict()
    assert value['status'] == 'active' and value['record']['storage_bytes'] == owner.storage_bytes
    assert value['resource_lease']['released'] is True
    assert scheduler.snapshot()['allocated']['cpu_slots'] == 0
    assert value['cleanup_error'] == 'DaemonResourceError'
    observation, = value['cleanup_failure_observations']
    assert observation['stage'] == 'failure_retention'
    assert observation['error_kind'] == 'daemon_resource_error'
    assert observation['reason_code'] == 'ledger_lock_unavailable'
    assert observation['lock_observation_status'] == 'accepted'
    actual = observation['lock_observation']
    assert actual['lock_path'] == str(owner.lock_path)
    assert actual['lock_acquired'] is actual['holder_identity_established'] is False
    assert actual['started_monotonic'] <= actual['deadline_monotonic'] <= actual['observed_monotonic']
    assert value['cleanup_failure_observation_overflow'] is False


@pytest.mark.parametrize('error_class', [resources.DaemonResourceError, OSError, RuntimeError])
def test_retention_diagnostics_never_export_arbitrary_exception_message(setup, monkeypatch, error_class):
    factory, _, ledger_path, scheduler = setup
    owner = factory();owner.__enter__()
    secret = 'SECRET-error-message-must-not-escape-' + 'x' * 5000
    def fail(reason): raise error_class(secret)
    monkeypatch.setattr(owner, '_retain', fail)
    before = ledger_path.read_bytes()
    assert owner.__exit__(RuntimeError, RuntimeError('primary'), None) is False
    value = owner.to_dict()
    assert ledger_path.read_bytes() == before and value['status'] == 'active'
    assert value['resource_lease']['released'] is True
    assert scheduler.snapshot()['allocated']['cpu_slots'] == 0
    assert secret not in json.dumps(value['cleanup_failure_observations'])
    observation, = value['cleanup_failure_observations']
    assert observation['stage'] == 'failure_retention'
    assert observation['reason_code'] == 'unclassified' and observation['lock_observation'] is None


@pytest.mark.parametrize('bad', ['extra', 'foreign_path', 'nonfinite', 'untyped_identity',
    'schema_object', 'stage_object', 'schema_subclass', 'stage_subclass',
    'missing_origin', 'wrong_origin', 'changed_valid_inode', 'changed_valid_time'])
def test_retention_diagnostics_refuse_unbound_lock_observation_data(setup, monkeypatch, bad):
    import fcntl
    factory, _, ledger_path, _ = setup
    owner = factory(ledger_lock_timeout_seconds=0.01);owner.__enter__()
    descriptor = os.open(owner.lock_path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(resources.DaemonResourceError) as caught:
            with owner._locked(): pytest.fail('private lock unexpectedly acquired')
    finally: os.close(descriptor)
    class EqualSecret:
        def __eq__(self, other): return True
        def __deepcopy__(self, memo): return 'SECRET-unsafe-deepcopy'
    class SecretStr(str):
        def __deepcopy__(self, memo): return 'SECRET-unsafe-deepcopy'
    offered = caught.value._lock_observation
    if bad == 'extra': offered['arbitrary'] = 'SECRET'
    elif bad == 'foreign_path': offered['lock_path'] = '/SECRET/foreign.lock'
    elif bad == 'nonfinite': offered['observed_monotonic'] = float('nan')
    elif bad == 'untyped_identity': offered['opened_lock_identity']['st_ino'] = True
    elif bad == 'schema_object': offered['schema'] = EqualSecret()
    elif bad == 'stage_object': offered['stage'] = EqualSecret()
    elif bad == 'schema_subclass': offered['schema'] = SecretStr(offered['schema'])
    elif bad == 'stage_subclass': offered['stage'] = SecretStr(offered['stage'])
    elif bad == 'missing_origin': del caught.value._lock_observation_binding
    elif bad == 'wrong_origin': caught.value._lock_observation_binding = (object(), caught.value._lock_observation_binding[1])
    elif bad == 'changed_valid_inode': offered['opened_lock_identity']['st_ino'] += 1
    else: offered['observed_monotonic'] += 1
    def fail(reason): raise caught.value
    monkeypatch.setattr(owner, '_retain', fail)
    before = ledger_path.read_bytes()
    assert owner.__exit__(RuntimeError, RuntimeError('primary'), None) is False
    assert ledger_path.read_bytes() == before and owner._lease.to_dict()['released'] is True
    observation, = owner.to_dict()['cleanup_failure_observations']
    assert observation['stage'] == 'failure_retention'
    assert observation['lock_observation_status'] == 'rejected'
    assert observation['lock_observation'] is None and observation['reason_code'] == 'unclassified'
    assert 'SECRET' not in json.dumps(observation)


def test_retention_and_native_release_errors_keep_distinct_stages(setup, monkeypatch):
    factory, _, ledger_path, scheduler = setup
    owner = factory();owner.__enter__()
    release = owner._lease.release
    def fail_retention(reason): raise resources.DaemonResourceError('SECRET-retention')
    def fail_release(): raise RuntimeError('SECRET-release')
    monkeypatch.setattr(owner, '_retain', fail_retention)
    monkeypatch.setattr(owner._lease, 'release', fail_release)
    before = ledger_path.read_bytes()
    try:
        assert owner.__exit__(RuntimeError, RuntimeError('primary'), None) is False
        value = owner.to_dict()
        assert ledger_path.read_bytes() == before and value['status'] == 'active'
        assert [o['stage'] for o in value['cleanup_failure_observations']] == ['failure_retention','native_release']
        assert 'SECRET' not in json.dumps(value['cleanup_failure_observations'])
        assert value['resource_lease']['released'] is False
    finally:
        release()
    assert scheduler.snapshot()['allocated']['cpu_slots'] == 0


def test_normal_retention_keeps_legacy_receipt_without_diagnostic_extension(setup):
    factory, _, ledger_path, scheduler = setup
    with factory() as owner:
        pass
    value = owner.to_dict()
    assert value['cleanup_error'] is None and value['status'] == 'retained'
    assert 'cleanup_failure_observations' not in value
    assert 'cleanup_failure_observation_overflow' not in value
    assert value['record'] == json.loads(ledger_path.read_bytes())['reservations'][owner.reservation_id]
    assert scheduler.snapshot()['allocated']['cpu_slots'] == 0


def test_cleanup_diagnostic_bound_and_detached_receipt(setup):
    factory, _, _, scheduler = setup
    owner = factory();owner.__enter__()
    try:
        for _ in range(6):
            owner._remember_cleanup_failure('failure_retention', RuntimeError('SECRET'))
        first = owner.to_dict()
        assert len(first['cleanup_failure_observations']) == 4
        assert first['cleanup_failure_observation_overflow'] is True
        assert 'SECRET' not in json.dumps(first['cleanup_failure_observations'])
        first['cleanup_failure_observations'][0]['stage'] = 'SECRET-mutated-receipt'
        assert owner.to_dict()['cleanup_failure_observations'][0]['stage'] == 'failure_retention'
    finally:
        owner.__exit__(RuntimeError, RuntimeError('primary'), None)
    assert scheduler.snapshot()['allocated']['cpu_slots'] == 0


@pytest.mark.parametrize('lock_timeout', [30, 60, 180, 600])
def test_cleanup_diagnostics_recognize_bounded_selected_ledger_lock_timeout(setup, monkeypatch, lock_timeout):
    # Controlled clock: no claim that these wall-clock durations elapsed.
    # Real _locked emits its own owner-bound timeout for every supported bound.
    from types import SimpleNamespace
    import fcntl
    factory, _, _, scheduler = setup
    owner = factory(ledger_lock_timeout_seconds=lock_timeout);owner.__enter__()
    descriptor = os.open(owner.lock_path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        clock = iter((100.0, 101.0 + lock_timeout))
        with monkeypatch.context() as patch:
            patch.setattr(resources, 'time', SimpleNamespace(monotonic=lambda: next(clock)))
            with pytest.raises(resources.DaemonResourceError) as caught:
                with owner._locked(): pytest.fail('private held lock unexpectedly acquired')
        owner._remember_cleanup_failure('failure_retention', caught.value)
        observation, = owner.to_dict()['cleanup_failure_observations']
        assert observation['reason_code'] == 'ledger_lock_unavailable'
        assert observation['lock_observation_status'] == 'accepted'
        assert observation['lock_observation']['configured_lock_timeout_seconds'] == lock_timeout
    finally:
        os.close(descriptor)
        owner.__exit__(RuntimeError, RuntimeError('primary'), None)
    assert scheduler.snapshot()['allocated']['cpu_slots'] == 0





def test_default_usage_inventory_hook_keeps_strict_unaliased_inventory(tmp_path, monkeypatch):
    reservation = object.__new__(resources.DaemonResourceReservation)
    original = resources._inventory
    calls = []
    def observed(paths, **kwargs):
        calls.append((tuple(paths), kwargs))
        return original(paths, **kwargs)
    monkeypatch.setattr(resources, "_inventory", observed)
    (tmp_path / "regular").write_bytes(b"x")
    result = reservation._usage_inventory(tmp_path)
    assert calls == [((tmp_path,), {"strict": True})]
    assert result["apparent_bytes"] == 1
    (tmp_path / "alias").symlink_to(tmp_path / "regular")
    with pytest.raises(resources.DaemonResourceError):
        reservation._usage_inventory(tmp_path)
    assert "_usage_inventory" not in reservation.__dict__



def test_ledger_wait_headroom_preserves_selected_thirty_and_inherited_timeout(setup):
    factory, _, ledger, scheduler = setup
    default = factory()
    inherited = factory(timeout_seconds=30)
    explicit = factory(timeout_seconds=0, ledger_lock_timeout_seconds=30)
    assert default.timeout_seconds == default.ledger_lock_timeout_seconds == 0
    assert inherited.timeout_seconds == inherited.ledger_lock_timeout_seconds == 30
    assert explicit.timeout_seconds == 0 and explicit.ledger_lock_timeout_seconds == 30
    assert resources.MAX_LEDGER_LOCK_TIMEOUT_SECONDS == 600
    assert not ledger.exists()
    assert scheduler.snapshot()['allocated']['cpu_slots'] == 0


def test_selected_ledger_headroom_acquires_real_lock_after_old_sixty_second_boundary(setup, monkeypatch):
    from types import SimpleNamespace
    import fcntl
    factory, _, ledger, scheduler = setup
    owner = factory(ledger_lock_timeout_seconds=180)
    descriptor = os.open(owner.lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    now = [100.0]
    sleeps = []
    def release_after_old_bound(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 1:
            # Keep the real lock held for another failed flock AFTER the old
            # sixty-second boundary; only the second sleep releases it.
            now[0] = 161.0
        else:
            assert len(sleeps) == 2
            now[0] = 162.0
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with monkeypatch.context() as patch:
            patch.setattr(resources, 'time', SimpleNamespace(
                monotonic=lambda: now[0], sleep=release_after_old_bound))
            with owner._locked():
                assert now[0] == 162.0
        assert len(sleeps) == 2 and all(0 < value <= 0.05 for value in sleeps)
    finally:
        os.close(descriptor)
    assert not ledger.exists() and owner._record is None and owner._lease is None
    assert scheduler.snapshot()['allocated']['cpu_slots'] == 0


def test_selected_ledger_headroom_never_extends_original_operation_deadline(setup, monkeypatch):
    import fcntl
    factory, _, ledger, scheduler = setup
    owner = factory(ledger_lock_timeout_seconds=180)
    descriptor = os.open(owner.lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    clock = _host_admission_clock(monkeypatch)
    def cross_original_work_deadline(seconds):
        assert 0 < seconds <= 0.05
        clock.now = 111.0
    monkeypatch.setattr(clock, 'sleep', cross_original_work_deadline)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with resources.native_deadlines.resource_admission_deadline(
                work_deadline_monotonic=110.0, native_deadline_monotonic=120.0):
            with pytest.raises(resources.native_deadlines.ResourceAdmissionDeadlineError):
                with owner._locked():
                    pytest.fail('held lock must not pass the original operation deadline')
        assert clock.now == 111.0
    finally:
        os.close(descriptor)
    assert resources.native_deadlines.resource_operation_deadline() is None
    assert not ledger.exists() and owner._record is None and owner._lease is None
    assert scheduler.snapshot()['allocated']['cpu_slots'] == 0


def test_initial_usage_lock_timeout_can_retry_same_owner_without_dropping_full_claim(setup, monkeypatch):
    from types import SimpleNamespace
    import fcntl
    factory, roots, ledger, scheduler = setup
    attempt = roots[0] / 'attempt'
    attempt.mkdir()
    with factory(ledger_lock_timeout_seconds=180) as owner:
        reservation_id = owner.reservation_id
        lease_id = owner._lease.lease_id
        before = ledger.read_bytes()
        descriptor = os.open(owner.lock_path, os.O_RDWR | os.O_NOFOLLOW)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            clock = iter((100.0, 281.0))
            with monkeypatch.context() as patch:
                patch.setattr(resources, 'time', SimpleNamespace(monotonic=lambda: next(clock)))
                with pytest.raises(resources.DaemonResourceError) as caught:
                    owner.check_usage(attempt, child_pid=None)
            assert caught.value.lock_observation['configured_lock_timeout_seconds'] == 180
            assert caught.value._lock_observation_binding[0] is owner
            assert ledger.read_bytes() == before
        finally:
            os.close(descriptor)
        usage = owner.check_usage(attempt, child_pid=None)
        ledger_value = json.loads(ledger.read_bytes())
        assert set(ledger_value['reservations']) == {reservation_id}
        assert owner.reservation_id == reservation_id and owner._lease.lease_id == lease_id
        assert owner._child is None and owner._child_history == []
        assert usage['outstanding_full_reservations_bytes'] == owner.storage_bytes
        assert ledger_value['reservations'][reservation_id]['status'] == 'active'
        assert scheduler.snapshot()['allocated']['cpu_slots'] == 1
        owner.finalize(attempt, artifacts_durable=True)
    assert scheduler.snapshot()['allocated']['cpu_slots'] == 0


# Explicit capacity and migration tests use only their temporary ledger/roots.
@pytest.mark.parametrize("capacity", [1, 250_000_000_000, 280_000_000_000])
def test_configured_storage_capacity_is_explicit_and_has_no_admission_side_effects(tmp_path, capacity):
    root = tmp_path / "outputs"
    root.mkdir()
    ledger = tmp_path / "disk.json"
    owner = resources.DaemonResourceReservation(
        ledger, roots=[root], storage_bytes=1, memory_mb=1, storage_limit_bytes=capacity)
    assert owner._read()["limit_bytes"] == capacity
    assert owner.to_dict()["storage_limit_bytes"] == capacity
    assert owner.to_dict()["resource_lease"] is None
    assert resources.MAX_STORAGE_BYTES == 250_000_000_000
    assert not ledger.exists() and not owner.lock_path.exists()


@pytest.mark.parametrize("capacity", [0, -1, True, False, 1.5, "280000000000", float("nan"), float("inf"), 1 << 63])
def test_invalid_configured_capacity_refuses_before_ledger_or_lock_creation(tmp_path, capacity):
    root = tmp_path / "outputs"
    root.mkdir()
    ledger = tmp_path / "disk.json"
    with pytest.raises(resources.DaemonResourceError, match="storage_limit_bytes"):
        resources.DaemonResourceReservation(
            ledger, roots=[root], storage_bytes=1, memory_mb=1, storage_limit_bytes=capacity)
    assert not ledger.exists() and not ledger.with_name("disk.json.lock").exists()


def _configured_capacity_ledger(tmp_path):
    root = tmp_path / "outputs"
    root.mkdir()
    (root / "retained").write_bytes(b"abc")
    ledger_path = tmp_path / "disk.json"
    owner = resources.DaemonResourceReservation(ledger_path, roots=[root], storage_bytes=1, memory_mb=1)
    # A real absence check, not a host-process kill or monkeypatch of capacity.
    dead_pid = (1 << 31) - 1
    assert resources._process(dead_pid) is None
    records = {}
    for index, status in enumerate(["reserved", "active", "retained", "released"], 1):
        records[status] = {"reservation_id": status, "owner_pid": dead_pid,
            "storage_bytes": index * 1000, "status": status, "child": None,
            "external_charges": {"journal": 2}, "created_at": index + 0.25,
            "last_usage": {"limit_bytes": 250_000_000_000, "charged_bytes": index * 1000 + 3},
            "prior_children": [{"pid": 17, "birth": "historical", "group_observed_dead_at": 1.0}],
            "retention_reason": "preserve-exact-history", "artifacts_durable_asserted": status == "released"}
    ledger = {"schema": resources.SCHEMA, "roots": owner.root_identities,
              "limit_bytes": 250_000_000_000, "reservations": records}
    raw = (json.dumps(ledger, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ledger_path.write_bytes(raw)
    return root, ledger_path, ledger, raw


def test_locked_configured_capacity_migration_preserves_all_records_and_exact_old_history(tmp_path, monkeypatch):
    import hashlib
    root, ledger_path, old, raw = _configured_capacity_ledger(tmp_path)
    records_raw = json.dumps(old["reservations"], sort_keys=True, separators=(",", ":")).encode()
    def no_lease(*args, **kwargs):
        raise AssertionError("migration must never acquire native resources")
    monkeypatch.setattr(resources.DaemonResourceReservation, "_acquire_native_lease", no_lease)
    receipt = resources.DaemonResourceReservation.migrate_storage_limit(
        ledger_path, roots=[root], expected_limit_bytes=250_000_000_000,
        storage_limit_bytes=280_000_000_000)
    current = json.loads(ledger_path.read_bytes())
    assert current == {**old, "limit_bytes": 280_000_000_000}
    assert json.dumps(current["reservations"], sort_keys=True, separators=(",", ":")).encode() == records_raw
    assert receipt["reservation_records_sha256"] == hashlib.sha256(records_raw).hexdigest()
    assert receipt["accounting"]["outstanding_full_reservations_bytes"] == 6000
    assert receipt["accounting"]["observed_apparent_bytes"] == 3
    assert receipt["accounting"]["charged_bytes"] == 6003
    assert receipt["reservation_or_scheduler_lease_acquired"] is False
    assert receipt["roots"] == old["roots"]
    assert ledger_path.read_bytes() != raw
    reopened = resources.DaemonResourceReservation(
        ledger_path, roots=[root], storage_bytes=1, memory_mb=1, storage_limit_bytes=280_000_000_000)
    assert reopened._read() == current
    with pytest.raises(resources.DaemonResourceError, match="storage scope differs"):
        resources.DaemonResourceReservation(ledger_path, roots=[root], storage_bytes=1, memory_mb=1)._read()
    after = ledger_path.read_bytes()
    with pytest.raises(resources.DaemonResourceError, match="storage scope differs"):
        resources.DaemonResourceReservation.migrate_storage_limit(
            ledger_path, roots=[root], expected_limit_bytes=250_000_000_000,
            storage_limit_bytes=280_000_000_000)
    assert ledger_path.read_bytes() == after


@pytest.mark.parametrize("status", ["reserved", "active", "retained"])
def test_capacity_migration_refuses_legacy_live_owners_without_dropping_claims(tmp_path, status):
    root, ledger_path, old, _ = _configured_capacity_ledger(tmp_path)
    old["reservations"][status]["owner_pid"] = os.getpid()
    raw = json.dumps(old, sort_keys=True).encode()
    ledger_path.write_bytes(raw)
    with pytest.raises(resources.DaemonResourceError, match="live disk ledger owner"):
        resources.DaemonResourceReservation.migrate_storage_limit(
            ledger_path, roots=[root], expected_limit_bytes=250_000_000_000,
            storage_limit_bytes=280_000_000_000)
    assert ledger_path.read_bytes() == raw


def test_capacity_migration_refuses_live_orphan_child_and_does_not_kill_it(tmp_path):
    root, ledger_path, old, _ = _configured_capacity_ledger(tmp_path)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        identity = resources._process(child.pid)
        assert identity is not None
        old["reservations"]["retained"]["child"] = {"pid": child.pid, "birth": identity["birth"]}
        raw = json.dumps(old, sort_keys=True).encode()
        ledger_path.write_bytes(raw)
        with pytest.raises(resources.DaemonResourceError, match="live disk ledger child"):
            resources.DaemonResourceReservation.migrate_storage_limit(
                ledger_path, roots=[root], expected_limit_bytes=250_000_000_000,
                storage_limit_bytes=280_000_000_000)
        assert ledger_path.read_bytes() == raw and child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=5)


@pytest.mark.parametrize("expected,target", [(0, 280_000_000_000), (True, 280_000_000_000),
    (250_000_000_000, 0), (250_000_000_000, True), (250_000_000_000, float("inf")),
    (250_000_000_000, 250_000_000_000), (250_000_000_000, 220_000_000_000),
    (250_000_000_000, 1 << 63)])
def test_invalid_capacity_migration_is_atomic_and_does_not_create_lock(tmp_path, expected, target):
    root, ledger_path, _, raw = _configured_capacity_ledger(tmp_path)
    with pytest.raises(resources.DaemonResourceError):
        resources.DaemonResourceReservation.migrate_storage_limit(
            ledger_path, roots=[root], expected_limit_bytes=expected, storage_limit_bytes=target)
    assert ledger_path.read_bytes() == raw
    assert not ledger_path.with_name(ledger_path.name + ".lock").exists()


def test_capacity_migration_requires_existing_ledger_and_real_exclusive_lock(tmp_path):
    import fcntl
    root, ledger_path, _, raw = _configured_capacity_ledger(tmp_path)
    lock = ledger_path.with_name(ledger_path.name + ".lock")
    with lock.open("wb") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(resources.DaemonResourceError, match="disk ledger lock unavailable"):
            resources.DaemonResourceReservation.migrate_storage_limit(
                ledger_path, roots=[root], expected_limit_bytes=250_000_000_000,
                storage_limit_bytes=280_000_000_000, ledger_lock_timeout_seconds=0)
        assert ledger_path.read_bytes() == raw
    ledger_path.unlink()
    with pytest.raises(resources.DaemonResourceError, match="disk ledger disappeared"):
        resources.DaemonResourceReservation.migrate_storage_limit(
            ledger_path, roots=[root], expected_limit_bytes=250_000_000_000,
            storage_limit_bytes=280_000_000_000)
    assert not ledger_path.exists()


def test_capacity_migration_write_failure_preserves_exact_original_ledger(tmp_path, monkeypatch):
    root, ledger_path, _, raw = _configured_capacity_ledger(tmp_path)
    def fail_replace(*args):
        raise OSError("injected replace failure")
    monkeypatch.setattr(resources.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected replace failure"):
        resources.DaemonResourceReservation.migrate_storage_limit(
            ledger_path, roots=[root], expected_limit_bytes=250_000_000_000,
            storage_limit_bytes=280_000_000_000)
    assert ledger_path.read_bytes() == raw
    assert not list(tmp_path.glob(".daemon-reservation-*"))


def test_capacity_migration_keeps_full_claim_and_filesystem_free_space_constraints(tmp_path, monkeypatch):
    from types import SimpleNamespace
    root, ledger_path, old, raw = _configured_capacity_ledger(tmp_path)
    monkeypatch.setattr(resources.shutil, "disk_usage", lambda root: SimpleNamespace(free=5999))
    with pytest.raises(resources.DaemonResourceError, match="capacity"):
        resources.DaemonResourceReservation.migrate_storage_limit(
            ledger_path, roots=[root], expected_limit_bytes=250_000_000_000,
            storage_limit_bytes=280_000_000_000)
    assert ledger_path.read_bytes() == raw
    old["reservations"]["active"]["storage_bytes"] = 140_000_000_000
    old["reservations"]["retained"]["storage_bytes"] = 140_000_000_000
    raw = json.dumps(old, sort_keys=True).encode()
    ledger_path.write_bytes(raw)
    monkeypatch.setattr(resources.shutil, "disk_usage", lambda root: SimpleNamespace(free=1_000_000_000_000))
    with pytest.raises(resources.DaemonResourceError, match="capacity"):
        resources.DaemonResourceReservation.migrate_storage_limit(
            ledger_path, roots=[root], expected_limit_bytes=250_000_000_000,
            storage_limit_bytes=280_000_000_000)
    assert ledger_path.read_bytes() == raw


def test_capacity_migration_can_repair_over_old_cap_without_reducing_any_claim(tmp_path, monkeypatch):
    from types import SimpleNamespace
    root, ledger_path, old, _ = _configured_capacity_ledger(tmp_path)
    old["reservations"]["active"]["storage_bytes"] = 200_000_000_000
    old["reservations"]["retained"]["storage_bytes"] = 51_000_000_000
    raw = json.dumps(old, sort_keys=True).encode()
    ledger_path.write_bytes(raw)
    monkeypatch.setattr(resources.shutil, "disk_usage", lambda root: SimpleNamespace(free=1_000_000_000_000))
    receipt = resources.DaemonResourceReservation.migrate_storage_limit(
        ledger_path, roots=[root], expected_limit_bytes=250_000_000_000,
        storage_limit_bytes=280_000_000_000)
    assert receipt["accounting"]["charged_bytes"] == 251_000_001_003
    assert json.loads(ledger_path.read_bytes()) == {**old, "limit_bytes": 280_000_000_000}


def test_configured_capacity_validates_large_named_charge_without_changing_legacy_default(tmp_path):
    root = tmp_path / "outputs"
    root.mkdir()
    ledger = tmp_path / "disk.json"
    owner = resources.DaemonResourceReservation(
        ledger, roots=[root], storage_bytes=270_000_000_000, memory_mb=1,
        storage_limit_bytes=280_000_000_000)
    value = owner._read()
    value["reservations"]["declared"] = {"reservation_id": "declared", "owner_pid": os.getpid(),
        "status": "retained", "storage_bytes": 270_000_000_000,
        "external_charges": {"large": 260_000_000_000}}
    ledger.write_text(json.dumps(value))
    assert owner._read() == value
    with pytest.raises(resources.DaemonResourceError, match="storage_bytes"):
        resources.DaemonResourceReservation(ledger, roots=[root], storage_bytes=270_000_000_000, memory_mb=1)
    assert resources.MAX_STORAGE_BYTES == 250_000_000_000


def _lowering_capacity_ledger(tmp_path):
    root, ledger_path, old, _ = _configured_capacity_ledger(tmp_path)
    old["limit_bytes"] = 280_000_000_000
    raw = (json.dumps(old, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ledger_path.write_bytes(raw)
    return root, ledger_path, old, raw


def test_storage_limit_lowering_preserves_every_record_and_full_charges(tmp_path, monkeypatch):
    import hashlib
    root, ledger_path, old, raw = _lowering_capacity_ledger(tmp_path)
    def no_lease(*args, **kwargs):
        raise AssertionError("lowering must never acquire native resources")
    monkeypatch.setattr(resources.DaemonResourceReservation, "_acquire_native_lease", no_lease)
    receipt = resources.DaemonResourceReservation.lower_storage_limit(
        ledger_path, roots=[root], expected_limit_bytes=280_000_000_000,
        storage_limit_bytes=250_000_000_000)
    current = json.loads(ledger_path.read_bytes())
    assert current == {**old, "limit_bytes": 250_000_000_000}
    records_raw = json.dumps(old["reservations"], sort_keys=True, separators=(",", ":")).encode()
    assert receipt["reservation_records_sha256"] == hashlib.sha256(records_raw).hexdigest()
    assert receipt["accounting"]["charged_bytes"] == 6003
    assert receipt["accounting"]["outstanding_full_reservations_bytes"] == 6000
    assert receipt["accounting"]["observed_apparent_bytes"] == 3
    assert receipt["records_roots_history_and_charges_preserved"] is True
    assert receipt["reservation_or_scheduler_lease_acquired"] is False
    assert receipt["roots"] == old["roots"]
    assert resources.MAX_STORAGE_BYTES == 250_000_000_000
    assert ledger_path.read_bytes() != raw
    reopened = resources.DaemonResourceReservation(
        ledger_path, roots=[root], storage_bytes=1, memory_mb=1)
    assert reopened._read() == current
    assert reopened.to_dict()["resource_lease"] is None


def test_storage_limit_lowering_exact_commitment_boundary_and_released_history(tmp_path):
    root, ledger_path, old, _ = _lowering_capacity_ledger(tmp_path)
    old["reservations"]["released"]["owner_pid"] = os.getpid()
    ledger_path.write_text(json.dumps(old))
    receipt = resources.DaemonResourceReservation.lower_storage_limit(
        ledger_path, roots=[root], expected_limit_bytes=280_000_000_000,
        storage_limit_bytes=6003)
    assert receipt["accounting"]["charged_bytes"] == 6003
    assert json.loads(ledger_path.read_bytes()) == {**old, "limit_bytes": 6003}


def test_storage_limit_lowering_refuses_one_byte_below_full_commitment(tmp_path):
    root, ledger_path, _, raw = _lowering_capacity_ledger(tmp_path)
    with pytest.raises(resources.DaemonResourceError, match="capacity"):
        resources.DaemonResourceReservation.lower_storage_limit(
            ledger_path, roots=[root], expected_limit_bytes=280_000_000_000,
            storage_limit_bytes=6002)
    assert ledger_path.read_bytes() == raw


@pytest.mark.parametrize("status", ["reserved", "active", "retained"])
def test_storage_limit_lowering_refuses_live_owner_without_releasing_claim(tmp_path, status):
    root, ledger_path, old, _ = _lowering_capacity_ledger(tmp_path)
    old["reservations"][status]["owner_pid"] = os.getpid()
    raw = json.dumps(old, sort_keys=True).encode()
    ledger_path.write_bytes(raw)
    with pytest.raises(resources.DaemonResourceError, match="live disk ledger owner"):
        resources.DaemonResourceReservation.lower_storage_limit(
            ledger_path, roots=[root], expected_limit_bytes=280_000_000_000,
            storage_limit_bytes=250_000_000_000)
    assert ledger_path.read_bytes() == raw


def test_storage_limit_lowering_refuses_live_orphan_child_without_killing_it(tmp_path):
    root, ledger_path, old, _ = _lowering_capacity_ledger(tmp_path)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        identity = resources._process(child.pid)
        assert identity is not None
        old["reservations"]["retained"]["child"] = {"pid": child.pid, "birth": identity["birth"]}
        raw = json.dumps(old, sort_keys=True).encode()
        ledger_path.write_bytes(raw)
        with pytest.raises(resources.DaemonResourceError, match="live disk ledger child"):
            resources.DaemonResourceReservation.lower_storage_limit(
                ledger_path, roots=[root], expected_limit_bytes=280_000_000_000,
                storage_limit_bytes=250_000_000_000)
        assert ledger_path.read_bytes() == raw and child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=5)


@pytest.mark.parametrize("expected,target", [
    (True, 250_000_000_000), ("280000000000", 250_000_000_000),
    (0, 250_000_000_000), (-1, 250_000_000_000),
    (1 << 63, 250_000_000_000), (280_000_000_000, True),
    (280_000_000_000, "250000000000"), (280_000_000_000, 1.5),
    (280_000_000_000, 0), (280_000_000_000, -1),
    (280_000_000_000, 1 << 63), (280_000_000_000, 280_000_000_000),
    (280_000_000_000, 281_000_000_000),
])
def test_storage_limit_lowering_invalid_transition_has_no_write_or_lock(tmp_path, expected, target):
    root, ledger_path, _, raw = _lowering_capacity_ledger(tmp_path)
    with pytest.raises(resources.DaemonResourceError):
        resources.DaemonResourceReservation.lower_storage_limit(
            ledger_path, roots=[root], expected_limit_bytes=expected,
            storage_limit_bytes=target)
    assert ledger_path.read_bytes() == raw
    assert not ledger_path.with_name(ledger_path.name + ".lock").exists()


def test_storage_limit_lowering_refuses_stale_expected_cap_and_wrong_roots(tmp_path):
    root, ledger_path, _, raw = _lowering_capacity_ledger(tmp_path)
    with pytest.raises(resources.DaemonResourceError, match="storage scope differs"):
        resources.DaemonResourceReservation.lower_storage_limit(
            ledger_path, roots=[root], expected_limit_bytes=270_000_000_000,
            storage_limit_bytes=250_000_000_000)
    other = tmp_path / "unrelated"
    other.mkdir()
    with pytest.raises(resources.DaemonResourceError, match="storage scope differs"):
        resources.DaemonResourceReservation.lower_storage_limit(
            ledger_path, roots=[other], expected_limit_bytes=280_000_000_000,
            storage_limit_bytes=250_000_000_000)
    assert ledger_path.read_bytes() == raw


def test_storage_limit_lowering_requires_existing_ledger_and_real_lock(tmp_path):
    import fcntl
    root, ledger_path, _, raw = _lowering_capacity_ledger(tmp_path)
    lock = ledger_path.with_name(ledger_path.name + ".lock")
    with lock.open("wb") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(resources.DaemonResourceError, match="disk ledger lock unavailable"):
            resources.DaemonResourceReservation.lower_storage_limit(
                ledger_path, roots=[root], expected_limit_bytes=280_000_000_000,
                storage_limit_bytes=250_000_000_000, ledger_lock_timeout_seconds=0)
        assert ledger_path.read_bytes() == raw
    ledger_path.unlink()
    with pytest.raises(resources.DaemonResourceError, match="disk ledger disappeared"):
        resources.DaemonResourceReservation.lower_storage_limit(
            ledger_path, roots=[root], expected_limit_bytes=280_000_000_000,
            storage_limit_bytes=250_000_000_000)
    assert not ledger_path.exists()


def test_storage_limit_lowering_replace_failure_preserves_bytes_and_removes_temp(tmp_path, monkeypatch):
    root, ledger_path, _, raw = _lowering_capacity_ledger(tmp_path)
    def fail_replace(*args):
        raise OSError("injected lowering replace failure")
    monkeypatch.setattr(resources.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected lowering replace failure"):
        resources.DaemonResourceReservation.lower_storage_limit(
            ledger_path, roots=[root], expected_limit_bytes=280_000_000_000,
            storage_limit_bytes=250_000_000_000)
    assert ledger_path.read_bytes() == raw
    assert not list(tmp_path.glob(".daemon-reservation-*"))


def test_storage_limit_lowering_keeps_filesystem_free_constraint(tmp_path, monkeypatch):
    from types import SimpleNamespace
    root, ledger_path, _, raw = _lowering_capacity_ledger(tmp_path)
    monkeypatch.setattr(resources.shutil, "disk_usage", lambda root: SimpleNamespace(free=5999))
    with pytest.raises(resources.DaemonResourceError, match="capacity"):
        resources.DaemonResourceReservation.lower_storage_limit(
            ledger_path, roots=[root], expected_limit_bytes=280_000_000_000,
            storage_limit_bytes=250_000_000_000)
    assert ledger_path.read_bytes() == raw


@pytest.mark.parametrize("field", ["reservation", "external_charge"])
def test_storage_limit_lowering_cannot_make_retained_history_unreadable(tmp_path, field):
    root, ledger_path, old, _ = _lowering_capacity_ledger(tmp_path)
    if field == "reservation":
        old["reservations"]["released"]["storage_bytes"] = 260_000_000_000
    else:
        old["reservations"]["released"]["external_charges"] = {"journal": 260_000_000_000}
    raw = json.dumps(old, sort_keys=True).encode()
    ledger_path.write_bytes(raw)
    with pytest.raises(resources.DaemonResourceError):
        resources.DaemonResourceReservation.lower_storage_limit(
            ledger_path, roots=[root], expected_limit_bytes=280_000_000_000,
            storage_limit_bytes=250_000_000_000)
    assert ledger_path.read_bytes() == raw


@pytest.mark.parametrize("fits", [True, False])
def test_storage_limit_lowering_external_overage_is_retained_in_commitment(tmp_path, fits):
    root, ledger_path, old, _ = _lowering_capacity_ledger(tmp_path)
    old["reservations"]["reserved"]["external_charges"] = {"journal": 5000}
    raw = json.dumps(old, sort_keys=True).encode()
    ledger_path.write_bytes(raw)
    kwargs = dict(roots=[root], expected_limit_bytes=280_000_000_000,
                  storage_limit_bytes=10003 if fits else 10002)
    if fits:
        receipt = resources.DaemonResourceReservation.lower_storage_limit(ledger_path, **kwargs)
        assert receipt["retained_external_overage_bytes"] == 4000
        assert receipt["accounting"]["charged_bytes"] == 10003
        assert json.loads(ledger_path.read_bytes()) == {**old, "limit_bytes": 10003}
    else:
        with pytest.raises(resources.DaemonResourceError, match="capacity"):
            resources.DaemonResourceReservation.lower_storage_limit(ledger_path, **kwargs)
        assert ledger_path.read_bytes() == raw
