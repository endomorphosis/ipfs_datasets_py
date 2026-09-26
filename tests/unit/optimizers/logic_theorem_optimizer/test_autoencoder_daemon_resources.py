"""Real scheduler/filesystem checks; small test-only capacities, no native jobs."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, ResourceLane, ResourceSchedulerConfig, ResourceUnavailableError,
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


def test_production_storage_cap_is_sixty_gb_without_admission(tmp_path):
    root = tmp_path / "outputs"
    root.mkdir()
    ledger = tmp_path / "disk.json"
    reservation = resources.DaemonResourceReservation(
        ledger, roots=[root], storage_bytes=7, memory_mb=1)
    assert resources.MAX_STORAGE_BYTES == 60_000_000_000
    assert reservation._read() == {
        "schema": resources.SCHEMA, "roots": reservation.root_identities,
        "limit_bytes": 60_000_000_000, "reservations": {},
    }
    assert reservation.to_dict()["storage_limit_bytes"] == 60_000_000_000
    assert reservation.to_dict()["status"] == "not_entered"
    assert reservation.to_dict()["resource_lease"] is None
    assert not ledger.exists()
    assert not reservation.lock_path.exists()


@pytest.fixture
def historical_fifty_gb_ledger(tmp_path):
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
            "last_usage": {"limit_bytes": 50_000_000_000, "charged_bytes": 4_003},
            "prior_children": [{"pid": 17, "birth": "historical", "group_observed_dead_at": 1.0}],
        },
        "released": {
            "reservation_id": "released", "status": "released",
            "owner_pid": os.getpid(), "storage_bytes": 9_000,
            "external_charges": {}, "artifacts_durable_asserted": True,
            "final_accounting": {"limit_bytes": 50_000_000_000},
        },
    }
    historical = {"schema": resources.SCHEMA, "roots": reservation.root_identities,
                  "limit_bytes": 50_000_000_000, "reservations": records}
    raw = (json.dumps(historical, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ledger.write_bytes(raw)
    return reservation, ledger, historical, raw


def test_historical_fifty_gb_ledger_fails_closed_without_implicit_migration(historical_fifty_gb_ledger):
    reservation, ledger, historical, raw = historical_fifty_gb_ledger
    with pytest.raises(resources.DaemonResourceError, match="storage scope differs"):
        reservation._read()
    assert ledger.read_bytes() == raw
    assert json.loads(raw)["reservations"] == historical["reservations"]
    assert reservation.to_dict()["status"] == "not_entered"
    assert not reservation.lock_path.exists()


def test_explicit_top_level_cap_migration_preserves_history_and_full_accounting(historical_fifty_gb_ledger):
    reservation, ledger, historical, raw = historical_fifty_gb_ledger
    old_prefix = b'{"limit_bytes":50000000000,'
    new_prefix = b'{"limit_bytes":60000000000,'
    assert raw.startswith(old_prefix)
    # Model the explicit one-time edit on a tiny, test-owned fixture. This
    # neither introduces an implicit migration API nor acquires a reservation.
    migrated = new_prefix + raw[len(old_prefix):]
    backup = ledger.with_name("historical-disk.json")
    backup.write_bytes(raw)
    ledger.write_bytes(migrated)
    current = reservation._read()
    assert current == {**historical, "limit_bytes": 60_000_000_000}
    assert current["reservations"] == historical["reservations"]
    assert migrated[len(new_prefix):] == raw[len(old_prefix):]
    usage = reservation._account(current, additional=13)
    assert usage["limit_bytes"] == 60_000_000_000
    assert usage["observed_apparent_bytes"] == 3
    assert usage["outstanding_full_reservations_bytes"] == 4_000
    assert usage["additional_requested_bytes"] == 13
    assert usage["charged_bytes"] == 4_016
    assert ledger.read_bytes() == migrated
    assert backup.read_bytes() == raw
    assert reservation.to_dict()["status"] == "not_entered"
    assert reservation.to_dict()["resource_lease"] is None
    assert not reservation.lock_path.exists()


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
