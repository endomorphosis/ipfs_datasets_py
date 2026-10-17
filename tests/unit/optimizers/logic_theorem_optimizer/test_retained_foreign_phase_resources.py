"""Real isolated native scheduler/ledger controls for bounded foreign custody."""
import copy
from contextlib import contextmanager
import json
import os

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as host
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.existing_resource_scheduler import policy_sha256
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.retained_foreign_phase_resources import (
    RetainedForeignPhaseResourceReservation, SCOPE_SCHEMA,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, ResourceLane, ResourceSchedulerConfig,
)


@pytest.fixture
def native(tmp_path, monkeypatch):
    roots = [tmp_path / name for name in ("outputs", "worktrees", "evidence", "pytest")]
    for root in roots:
        root.mkdir()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    database = foreign / "coordination.duckdb"
    database.write_bytes(b"native retained coordination bytes")
    for suffix in (".lock", ".serialized-coordinator.lock"):
        (foreign / ("." + database.name + suffix)).write_bytes(b"")
    ledger = tmp_path / "disk.json"
    scheduler = GlobalResourceScheduler(ResourceSchedulerConfig(
        total_cpu_slots=4, total_memory_mb=2048, total_child_process_slots=8,
        lane_reservations={}, state_path=tmp_path / "scheduler.json", auto_renew_leases=False,
        proof_safety_enabled=True))
    monkeypatch.setattr(host, "get_global_resource_scheduler", lambda: scheduler)
    monkeypatch.setattr(host, "MAX_STORAGE_BYTES", 100_000)
    # Create the isolated ledger through the unchanged genuine v1 producer.
    with host.DaemonResourceReservation(ledger, roots=roots, storage_bytes=1000, memory_mb=64) as initial:
        initial.release(artifacts_durable=True)
    policy = policy_sha256(json.loads(scheduler.state_path.read_bytes())["config"])
    scope = {"schema": SCOPE_SCHEMA, "database_path": str(database),
             "parent_identity": host._root_identity(foreign), "retained_bytes": 4000}
    sequence = 0

    @contextmanager
    def phase():
        with scheduler.acquire(ResourceLane.ORCHESTRATION, cpu_slots=2, memory_mb=512,
                               child_process_slots=4) as root:
            with root.acquire_child(lane=ResourceLane.ORCHESTRATION, cpu_slots=2,
                                    memory_mb=512, child_process_slots=4) as parent:
                yield parent

    def factory(parent, **options):
        nonlocal sequence
        sequence += 1
        attempt = roots[0] / str(sequence)
        attempt.mkdir()
        return RetainedForeignPhaseResourceReservation(
            ledger, roots=roots, attempt_directory=attempt, parent_lease=parent,
            foreign_scope=options.pop("foreign_scope", copy.deepcopy(scope)),
            storage_bytes=options.pop("storage_bytes", 10_000), memory_mb=128,
            scheduler_state_path=scheduler.state_path,
            expected_scheduler_policy_sha256=policy, timeout_seconds=30, **options)

    def legacy():
        return host.DaemonResourceReservation(ledger, roots=roots, storage_bytes=1000, memory_mb=64)
    return phase, factory, legacy, roots, ledger, database, scope, scheduler


def test_stopped_foreign_custody_remains_charged_to_unchanged_v1_producer(native):
    phase, factory, legacy, roots, ledger, database, scope, scheduler = native
    with phase() as parent:
        with factory(parent) as owner:
            original = json.loads(ledger.read_bytes())
            assert original["schema"] == host.SCHEMA
            assert original["roots"] == [host._root_identity(root) for root in roots]
            with pytest.raises(host.DaemonResourceError, match="foreign artifacts persist"):
                owner.release(artifacts_durable=True)
            result = owner.finalize(owner.directory, artifacts_durable=True)
            assert result["status"] == "retained"
            assert result["resource_lease"]["released"] is True
            assert result["record"]["foreign_scope"]["native_child_released_after_stop"] is True
        # Ordinary context exit cannot rewrite/drop finalized retained custody.
        row = json.loads(ledger.read_bytes())["reservations"][owner.reservation_id]
        assert row == result["record"]
        assert row["storage_bytes"] == scope["retained_bytes"]
        assert database.exists()
        observation = legacy()._account(legacy()._read())
        assert observation["outstanding_full_reservations_bytes"] == scope["retained_bytes"]
        assert observation["charged_bytes"] >= scope["retained_bytes"] >= database.stat().st_size
    assert scheduler.snapshot()["allocated"]["cpu_slots"] == 0


def test_genuine_successor_transfers_custody_without_dropping_coverage(native, monkeypatch):
    phase, factory, legacy, roots, ledger, database, scope, scheduler = native
    with phase() as parent:
        with factory(parent) as first:
            first.finalize(first.directory, artifacts_durable=True)
    old_row = copy.deepcopy(json.loads(ledger.read_bytes())["reservations"][first.reservation_id])
    writes = []
    original_write = host.DaemonResourceReservation._write
    def observe_write(self, value):
        writes.append(sum(row["storage_bytes"] for row in value["reservations"].values()
                          if row["status"] != "released"))
        return original_write(self, value)
    monkeypatch.setattr(host.DaemonResourceReservation, "_write", observe_write)
    with phase() as parent:
        with factory(parent) as second:
            rows = json.loads(ledger.read_bytes())["reservations"]
            assert rows[first.reservation_id]["status"] == "released"
            assert rows[first.reservation_id]["owner_pid"] == old_row["owner_pid"]
            assert rows[first.reservation_id]["native_lease_id"] == old_row["native_lease_id"]
            assert rows[first.reservation_id]["foreign_scope"]["custody_state"] == "transferred"
            assert rows[first.reservation_id]["foreign_scope"]["successor_reservation_id"] == second.reservation_id
            assert second.to_dict()["record"]["foreign_scope"]["predecessor_reservation_id"] == first.reservation_id
            second.finalize(second.directory, artifacts_durable=True)
    assert writes and min(writes) >= scope["retained_bytes"]
    assert legacy()._account(legacy()._read())["outstanding_full_reservations_bytes"] == scope["retained_bytes"]


def test_failure_retains_full_original_job_and_refuses_custody_reuse(native):
    phase, factory, legacy, roots, ledger, database, scope, scheduler = native
    with phase() as parent:
        with pytest.raises(RuntimeError, match="interrupted"):
            with factory(parent) as first:
                raise RuntimeError("interrupted")
    row = legacy()._read()["reservations"][first.reservation_id]
    assert row["status"] == "retained" and row["storage_bytes"] == 10_000
    assert row["foreign_scope"]["custody_state"] == "active"
    with phase() as parent:
        with pytest.raises(host.DaemonResourceError, match="interrupted owner"):
            factory(parent).__enter__()
    assert legacy()._account(legacy()._read())["outstanding_full_reservations_bytes"] == 10_000


@pytest.mark.parametrize("mutation", ["parent", "extra_path", "symlink", "hardlink", "companion", "growth"])
def test_foreign_scope_refuses_redirected_unrelated_or_unbounded_files(native, mutation):
    phase, factory, legacy, roots, ledger, database, scope, scheduler = native
    changed = copy.deepcopy(scope)
    if mutation == "parent":
        changed["parent_identity"]["inode"] += 1
    elif mutation == "extra_path":
        changed["files"] = [str(database.parent / "unrelated")]
    elif mutation == "symlink":
        database.rename(database.with_name("original"))
        database.symlink_to("original")
    elif mutation == "hardlink":
        os.link(database, database.parent / "alias")
    elif mutation == "companion":
        database.with_name(database.name + ".tmp").mkdir()
    else:
        database.write_bytes(b"x" * (scope["retained_bytes"] + 1))
    original = ledger.read_bytes()
    with phase() as parent:
        with pytest.raises(host.DaemonResourceError):
            factory(parent, foreign_scope=changed)
    assert ledger.read_bytes() == original


def test_active_foreign_custodian_cannot_be_adopted(native):
    phase, factory, legacy, roots, ledger, database, scope, scheduler = native
    with phase() as parent:
        with factory(parent) as first:
            with pytest.raises(host.DaemonResourceError, match="outstanding or interrupted"):
                factory(parent).__enter__()
            first.finalize(first.directory, artifacts_durable=True)


def test_actual_foreign_growth_refuses_and_retains_the_full_job_promise(native):
    phase, factory, legacy, roots, ledger, database, scope, scheduler = native
    with phase() as parent:
        with pytest.raises(host.DaemonResourceError, match="foreign retained byte limit"):
            with factory(parent) as owner:
                database.write_bytes(b"x" * (scope["retained_bytes"] + 1))
                owner.check_usage(owner.directory)
    row = legacy()._read()["reservations"][owner.reservation_id]
    assert row["status"] == "retained" and row["storage_bytes"] == 10_000
    assert row["foreign_scope"]["custody_state"] == "active"


def test_transfer_refuses_unconfirmed_native_release_receipt(native):
    phase, factory, legacy, roots, ledger, database, scope, scheduler = native
    with phase() as parent:
        with factory(parent) as owner:
            owner.finalize(owner.directory, artifacts_durable=True)
    # Corrupt only this isolated ledger's attestation, never a host record.
    value = legacy()._read()
    value["reservations"][owner.reservation_id]["foreign_scope"]["native_child_released_after_stop"] = False
    ledger.write_text(json.dumps(value))
    original = ledger.read_bytes()
    with phase() as parent:
        with pytest.raises(host.DaemonResourceError, match="outstanding or interrupted"):
            factory(parent).__enter__()
    assert ledger.read_bytes() == original


def test_empty_foreign_scope_can_retire_only_in_a_fresh_native_phase(native):
    phase, factory, legacy, roots, ledger, database, scope, scheduler = native
    with phase() as parent:
        with factory(parent) as first:
            first.finalize(first.directory, artifacts_durable=True)
    database.unlink()
    for suffix in (".lock", ".serialized-coordinator.lock"):
        database.with_name("." + database.name + suffix).unlink()
    with phase() as parent:
        with factory(parent) as second:
            result = second.release(artifacts_durable=True)
            assert result["status"] == "released"
            assert result["record"]["foreign_scope"]["custody_state"] == "released_empty"
    assert legacy()._account(legacy()._read())["outstanding_full_reservations_bytes"] == 0
