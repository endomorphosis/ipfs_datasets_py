"""Private native control metadata; no production jobs, models or databases.

Only private host-pressure observations are injected for deterministic native
admission. Actual native locks, state, lease lifecycle and disk ledger persist.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import threading

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as native
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


@pytest.fixture
def private(tmp_path, monkeypatch):
    path = tmp_path / "native.json"
    scheduler = native.GlobalResourceScheduler(native.ResourceSchedulerConfig(
        state_path=path, total_cpu_slots=4, total_memory_mb=4096,
        total_child_process_slots=8, lane_reservations={}, proof_safety_enabled=True,
        auto_renew_leases=False))
    policy = deepcopy(json.loads(path.read_bytes())["config"])
    expected = existing.policy_sha256(policy)
    factory = existing.open_existing_scheduler

    def private_factory(*args):
        facade = factory(*args)
        # Private fixture observations/settings only, not a production API.
        facade.config.proof_resource_sampler = lambda: ProofHostResources(8, 8192, 8192,
            pid_task_limit=500, available_pid_tasks=400)
        facade.config.auto_renew_leases = False
        return facade

    monkeypatch.setattr(existing, "open_existing_scheduler", private_factory)
    root = tmp_path / "artifacts"
    root.mkdir()
    ledger = tmp_path / "disk.json"
    template = resources.DaemonResourceReservation(ledger, roots=[root], storage_bytes=10_000, memory_mb=64)
    template._write(template._read())
    return path, policy, expected, root, ledger, scheduler


def reservation(private, **changes):
    path, _, expected, root, ledger, _ = private
    arguments = dict(roots=[root], storage_bytes=10_000, memory_mb=64, child_process_slots=5,
        scheduler_state_path=path, expected_scheduler_policy_sha256=expected, require_existing_ledger=True)
    arguments.update(changes)
    return resources.DaemonResourceReservation(ledger, **arguments)


def test_factory_preserves_exact_native_state_policy_without_global_cache_or_lease(private):
    path, policy, expected, _, _, _ = private
    before = path.read_bytes()
    global_before = dict(native._GLOBAL_SCHEDULERS)
    facade = existing.open_existing_scheduler(path, expected)
    assert isinstance(facade, native.GlobalResourceScheduler)
    assert facade.config.persisted_dict() == policy
    assert facade.active_leases() == []
    assert path.read_bytes() == before
    assert native._GLOBAL_SCHEDULERS == global_before


def test_opening_preserves_existing_noncanonical_json_bytes_without_normalizing(private):
    path, _, expected, _, _, _ = private
    before = json.dumps(json.loads(path.read_bytes()), indent=2).encode()+b"\n"
    path.write_bytes(before)
    existing.open_existing_scheduler(path, expected)
    assert path.read_bytes() == before


def test_current_native_producer_rejects_smaller_legacy_policy_without_migrating(private):
    path, _, _, _, _, _ = private
    state = json.loads(path.read_bytes())
    newer = {"proof_resource_profile", "proof_recovery_enabled", "proof_recovery_samples",
             "proof_recovery_interval_seconds", "proof_recovery_grants"}
    # Omit fields from the selected producer's actual closed inventory. The
    # pinned P scheduler predates recovery fields; its own earlier inventory
    # still must not be normalized into the current schema.
    omitted = newer.intersection(state["config"]) or {"total_child_process_slots"}
    for key in omitted:
        state["config"].pop(key)
    path.write_text(json.dumps(state))
    before = path.read_bytes()
    with pytest.raises(existing.ExistingResourceSchedulerError, match="cannot be normalized"):
        existing.open_existing_scheduler(path, existing.policy_sha256(state["config"]))
    assert path.read_bytes() == before


@pytest.mark.parametrize("legacy_inventory", [False, True])
def test_closed_inventory_is_defined_by_exact_selected_typed_producer_boundary(private, monkeypatch, legacy_inventory):
    """Schema boundary fixture only; no facade, lease or P-native claim."""
    path, _, _, _, _, _ = private
    state = json.loads(path.read_bytes())
    dropped = {"proof_resource_profile", "proof_recovery_enabled", "proof_recovery_samples",
               "proof_recovery_interval_seconds", "proof_recovery_grants"}
    if legacy_inventory:
        state["config"] = {key: value for key, value in state["config"].items() if key not in dropped}
    path.write_text(json.dumps(state))
    original_config = native.ResourceSchedulerConfig
    class SchemaBoundaryConfig(original_config):
        def persisted_dict(self):
            policy = super().persisted_dict()
            return {key: value for key, value in policy.items() if key not in dropped} if legacy_inventory else policy
    monkeypatch.setattr(native, "ResourceSchedulerConfig", SchemaBoundaryConfig)
    observed = []
    def fixture_boundary(config, policy, digest, parents):
        from types import SimpleNamespace
        observed.append(config.persisted_dict())
        return SimpleNamespace(config=config, scope="unqualified typed schema boundary fixture")
    monkeypatch.setattr(existing, "_PinnedGlobalResourceScheduler", fixture_boundary)
    result = existing.open_existing_scheduler(path, existing.policy_sha256(state["config"]))
    assert result.scope == "unqualified typed schema boundary fixture"
    assert observed == [state["config"]]


@pytest.mark.parametrize("locked", [False, True])
@pytest.mark.parametrize("stage", ["before_fstat", "after_read"])
def test_atomic_native_filename_replacement_allows_advisory_snapshot_but_refuses_locked_race(private, monkeypatch, locked, stage):
    path, _, expected, _, _, _ = private
    old = path.read_bytes()
    newer = json.loads(old)
    newer["metrics"]["acquisitions_total"] += 1
    replacement = path.with_name("private-native-replacement.json")
    replacement.write_text(json.dumps(newer))
    real_fdopen = existing.os.fdopen
    replaced = []
    def replace_once():
        if not replaced:
            existing.os.replace(replacement, path)
            replaced.append(True)
    class SnapshotStream:
        def __init__(self, stream): self.stream = stream
        def __getattr__(self, key): return getattr(self.stream, key)
        def __enter__(self):
            self.stream.__enter__()
            if stage == "before_fstat": replace_once()
            return self
        def __exit__(self, *args): return self.stream.__exit__(*args)
        def read(self, size):
            raw = self.stream.read(size)
            if stage == "after_read": replace_once()
            return raw
    monkeypatch.setattr(existing.os, "fdopen", lambda *args, **kwargs: SnapshotStream(real_fdopen(*args, **kwargs)))
    if locked:
        with pytest.raises(existing.ExistingResourceSchedulerError, match="changed while reading|replaced while reading|unaliased existing"):
            existing._read(path, require_current=True)
    else:
        _, observed = existing._read(path, require_current=False)
        assert observed["metrics"]["acquisitions_total"] == 0
        facade = existing.open_existing_scheduler(path, expected)
        assert facade.active_leases() == []
    assert json.loads(path.read_bytes())["metrics"]["acquisitions_total"] == 1


@pytest.mark.parametrize("failure", ["missing", "empty", "corrupt", "duplicate", "nonfinite", "overflow_float", "symlink", "hardlink", "oversized", "policy", "safety", "partial", "control_shape", "negative_envelope"])
def test_factory_refuses_bad_existing_metadata_without_initializing_or_rewriting(private, tmp_path, failure):
    path, policy, expected, _, _, _ = private
    selected = path
    if failure == "missing":
        selected = tmp_path / "never-created" / "native.json"
    elif failure == "empty": path.write_bytes(b"")
    elif failure == "corrupt": path.write_bytes(b"{broken")
    elif failure == "duplicate":
        path.write_bytes(b'{"config":{},"config":' + json.dumps(policy).encode() + b'}')
    elif failure == "nonfinite": path.write_bytes(b'{"config":{},"value":NaN}')
    elif failure == "overflow_float": path.write_bytes(b'{"config":{},"value":1e999}')
    elif failure == "symlink":
        selected = tmp_path / "alias.json"
        selected.symlink_to(path)
    elif failure == "hardlink":
        selected = tmp_path / "linked.json"
        os.link(path, selected)
    elif failure == "oversized": path.write_bytes(b" " * (existing.MAX_STATE_BYTES + 1))
    else:
        state = json.loads(path.read_bytes())
        if failure == "policy": state["config"]["total_cpu_slots"] += 1
        if failure == "safety": state["config"]["proof_safety_enabled"] = False
        if failure == "partial": state["config"].pop("proof_memory_headroom_mb")
        if failure == "control_shape": state["leases"] = []
        if failure == "negative_envelope":
            state["leases"] = {"private-corrupt-record": {"owner_pid": os.getpid(), "lane": "hammer_lean",
                "cpu_slots": -1, "memory_mb": 64}}
        path.write_text(json.dumps(state))
        if failure in {"safety", "partial"}: expected = existing.policy_sha256(state["config"])
    before = path.read_bytes()
    with pytest.raises((existing.ExistingResourceSchedulerError, OSError)):
        existing.open_existing_scheduler(selected, expected)
    assert path.read_bytes() == before
    assert not (tmp_path / "never-created").exists()


def test_factory_refuses_symlinked_parent_directory(private, tmp_path):
    path, _, expected, _, _, _ = private
    alias = tmp_path / "alias-directory"
    alias.symlink_to(path.parent, target_is_directory=True)
    with pytest.raises(existing.ExistingResourceSchedulerError, match="directory"):
        existing.open_existing_scheduler(alias / path.name, expected)


@pytest.mark.parametrize("argument", ["", "A"*64, "a"*63, None, True])
def test_factory_requires_exact_explicit_policy_sha256(private, argument):
    path, _, _, _, _, _ = private
    with pytest.raises(existing.ExistingResourceSchedulerError):
        existing.open_existing_scheduler(path, argument)


def test_policy_change_between_initial_read_and_native_lock_refuses_even_when_idle(private, monkeypatch):
    path, _, expected, _, _, _ = private
    before_constructor = existing._PinnedGlobalResourceScheduler.__init__
    def racing(self, config, policy, digest, parents):
        state = json.loads(path.read_bytes())
        state["config"]["total_cpu_slots"] += 1
        path.write_text(json.dumps(state))
        return before_constructor(self, config, policy, digest, parents)
    monkeypatch.setattr(existing._PinnedGlobalResourceScheduler, "__init__", racing)
    with pytest.raises(existing.ExistingResourceSchedulerError, match="policy changed"):
        existing.open_existing_scheduler(path, expected)
    assert json.loads(path.read_bytes())["config"]["total_cpu_slots"] == 5


def test_missing_parent_race_never_recreates_state_directory(tmp_path, monkeypatch):
    directory = tmp_path / "disappearing"
    directory.mkdir()
    path = directory / "native.json"
    native.GlobalResourceScheduler(native.ResourceSchedulerConfig(state_path=path,
        total_cpu_slots=2, total_memory_mb=256, total_child_process_slots=2,
        lane_reservations={}, proof_safety_enabled=True, auto_renew_leases=False))
    expected = existing.policy_sha256(json.loads(path.read_bytes())["config"])
    before_constructor = existing._PinnedGlobalResourceScheduler.__init__
    def racing(self, config, policy, digest, parents):
        for entry in directory.iterdir(): entry.unlink()
        directory.rmdir()
        return before_constructor(self, config, policy, digest, parents)
    monkeypatch.setattr(existing._PinnedGlobalResourceScheduler, "__init__", racing)
    with pytest.raises(OSError):
        existing.open_existing_scheduler(path, expected)
    assert not directory.exists()


@pytest.mark.parametrize("failure", ["missing", "duplicate", "policy", "source"])
def test_opened_facade_rechecks_every_native_operation_under_same_lock(private, tmp_path, failure):
    path, _, expected, _, _, _ = private
    facade = existing.open_existing_scheduler(path, expected)
    if failure == "missing": path.unlink()
    elif failure == "duplicate": path.write_text('{"config":{},"config":{}}')
    elif failure == "policy":
        state = json.loads(path.read_bytes())
        state["config"]["total_cpu_slots"] += 1
        path.write_text(json.dumps(state))
    else:
        watched = tmp_path / "private-producer-fixture.py"
        watched.write_bytes(b"before")
        facade._sources[watched] = hashlib.sha256(watched.read_bytes()).hexdigest()
        watched.write_bytes(b"changed")
    before = path.read_bytes() if path.exists() else None
    with pytest.raises((existing.ExistingResourceSchedulerError, OSError)):
        facade.active_leases()
    assert (path.read_bytes() if path.exists() else None) == before


def test_outside_lock_policy_edit_during_native_transaction_is_not_overwritten(private):
    path, _, expected, _, _, _ = private
    facade = existing.open_existing_scheduler(path, expected)
    with pytest.raises(existing.ExistingResourceSchedulerError, match="outside its sibling lock"):
        with facade._locked_state() as state:
            external = json.loads(path.read_bytes())
            external["config"]["total_cpu_slots"] += 1
            path.write_text(json.dumps(external))
            state["metrics"]["acquisitions_total"] += 1
    assert json.loads(path.read_bytes())["config"]["total_cpu_slots"] == 5


def test_native_and_pinned_facades_share_one_lock_domain_and_preserve_each_others_work(private):
    path, _, expected, _, _, original = private
    facade = existing.open_existing_scheduler(path, expected)
    assert facade._thread_lock is original._thread_lock
    started, acquired = threading.Event(), threading.Event()
    failures = []
    def native_writer():
        try:
            started.set()
            with original._locked_state() as state:
                acquired.set()
                assert state["metrics"]["acquisitions_total"] == 1
                state["metrics"]["releases_total"] += 1
        except BaseException as error:
            failures.append(error)
    thread = threading.Thread(target=native_writer)
    try:
        with facade._locked_state() as state:
            thread.start()
            assert started.wait(1)
            assert not acquired.wait(0.05)
            state["metrics"]["acquisitions_total"] += 1
        thread.join(2)
        assert not thread.is_alive() and acquired.is_set() and failures == []
        state = json.loads(path.read_bytes())
        assert state["metrics"]["acquisitions_total"] == state["metrics"]["releases_total"] == 1
    finally:
        thread.join(2)


def test_source_change_during_native_transaction_refuses_atomic_persistence(private, tmp_path):
    path, _, expected, _, _, _ = private
    facade = existing.open_existing_scheduler(path, expected)
    watched = tmp_path / "private-producer-fixture.py"
    watched.write_bytes(b"before")
    facade._sources[watched] = hashlib.sha256(watched.read_bytes()).hexdigest()
    before = path.read_bytes()
    with pytest.raises(existing.ExistingResourceSchedulerError, match="producer source changed"):
        with facade._locked_state() as state:
            state["metrics"]["acquisitions_total"] += 1
            watched.write_bytes(b"after")
    assert path.read_bytes() == before


def test_strict_reservation_uses_native_hammer_lease_and_durable_finalize(private, monkeypatch):
    path, policy, expected, root, ledger, _ = private
    monkeypatch.setattr(resources, "get_global_resource_scheduler", lambda: pytest.fail("strict path used global defaults"))
    owned = reservation(private)
    assert owned.cancelled and owned.heartbeat() is False
    with owned:
        snapshot = owned.to_dict()
        assert snapshot["resource_lease"]["lane"] == native.ResourceLane.HAMMER_LEAN.value
        assert snapshot["resource_lease"]["child_process_slots"] == 5
        assert "lease_key" not in snapshot["resource_lease"]
        assert owned.heartbeat() is True and owned.cancelled is False
        (root / "retained-evidence").write_bytes(b"authored metadata only")
        owned.check_usage(root)
        assert json.loads(path.read_bytes())["config"] == policy
        owned.finalize(root, artifacts_durable=True)
    assert owned.cancelled and owned.heartbeat() is False
    row = json.loads(ledger.read_bytes())["reservations"][owned.reservation_id]
    assert row["status"] == "released" and row["artifacts_durable_asserted"] is True
    assert existing.open_existing_scheduler(path, expected).active_leases() == []


def test_strict_metadata_refusal_precedes_disk_reservation(private):
    path, _, _, _, ledger, _ = private
    before = ledger.read_bytes()
    path.unlink()
    owned = reservation(private)
    with pytest.raises(OSError): owned.__enter__()
    assert ledger.read_bytes() == before and owned.to_dict()["status"] == "not_entered"


def test_strict_admission_failure_retains_existing_disk_claim(private):
    _, policy, _, _, ledger, _ = private
    owned = reservation(private, cpu_slots=policy["total_cpu_slots"]+1)
    with pytest.raises(native.ResourceUnavailableError): owned.__enter__()
    row = json.loads(ledger.read_bytes())["reservations"][owned.reservation_id]
    assert row["status"] == "retained" and row["retention_reason"] == "scheduler_admission_failed"
    assert owned.to_dict()["resource_lease"] is None


def test_existing_disk_requirement_does_not_create_missing_ledger(private):
    _, _, _, _, ledger, _ = private
    ledger.unlink()
    with pytest.raises(resources.DaemonResourceError, match="ledger disappeared"):
        reservation(private).__enter__()
    assert not ledger.exists()


def test_context_failure_retains_disk_charge_after_releasing_stopped_native_work(private):
    path, _, expected, root, ledger, _ = private
    owned = reservation(private)
    with pytest.raises(RuntimeError, match="authored metadata failure"):
        with owned:
            owned.check_usage(root)
            raise RuntimeError("authored metadata failure")
    row = json.loads(ledger.read_bytes())["reservations"][owned.reservation_id]
    assert row["status"] == "retained" and row["artifacts_durable_asserted"] is False
    assert existing.open_existing_scheduler(path, expected).active_leases() == []


def test_strict_process_overflow_is_recorded_then_refused_legacy_remains_annotation(private, monkeypatch):
    _, _, _, root, ledger, legacy = private
    monkeypatch.setattr(resources, "_group_usage", lambda child: {"available": True, "live_processes": 6, "rss_bytes": 0})
    owned = reservation(private)
    with owned:
        with pytest.raises(resources.DaemonResourceError, match="process-slot"):
            owned.check_usage(root)
        row = json.loads(ledger.read_bytes())["reservations"][owned.reservation_id]
        assert row["last_usage"]["process_slot_estimate_exceeded"] is True
        monkeypatch.setattr(resources, "_group_usage", lambda child: {"available": True, "live_processes": 0, "rss_bytes": 0})
        owned.finalize(root, artifacts_durable=True)
    monkeypatch.setattr(resources, "get_global_resource_scheduler", lambda: legacy)
    monkeypatch.setattr(resources, "_group_usage", lambda child: {"available": True, "live_processes": 6, "rss_bytes": 0})
    # Native fixture's own constructor safety sampler is controlled privately.
    legacy.config.proof_resource_sampler = lambda: ProofHostResources(8, 8192, 8192,
        pid_task_limit=500, available_pid_tasks=400)
    unqualified = resources.DaemonResourceReservation(ledger, roots=[root], storage_bytes=10_000,
        memory_mb=64, child_process_slots=5)
    with unqualified:
        assert unqualified.check_usage(root)["process_slot_estimate_exceeded"] is True
        monkeypatch.setattr(resources, "_group_usage", lambda child: {"available": True, "live_processes": 0, "rss_bytes": 0})
        unqualified.finalize(root, artifacts_durable=True)


@pytest.mark.parametrize("changes", [
    {"scheduler_state_path": None}, {"expected_scheduler_policy_sha256": None},
    {"expected_scheduler_policy_sha256": "bad"}, {"require_existing_ledger": 1},
])
def test_reservation_refuses_partial_or_untyped_strict_options_before_mutation(private, changes):
    ledger = private[4]
    before = ledger.read_bytes()
    with pytest.raises(resources.DaemonResourceError): reservation(private, **changes)
    assert ledger.read_bytes() == before


def test_pinned_persistence_keeps_native_lock_and_atomic_fsync_protocol(private, monkeypatch):
    path, _, expected, _, _, _ = private
    facade = existing.open_existing_scheduler(path, expected)
    events = []
    real_fsync, real_replace = existing.os.fsync, existing.os.replace
    def fsync(descriptor):
        events.append("fsync")
        return real_fsync(descriptor)
    def replace(source, target):
        assert Path(target) == path and Path(source).parent == path.parent
        events.append("replace")
        return real_replace(source, target)
    monkeypatch.setattr(existing.os, "fsync", fsync)
    monkeypatch.setattr(existing.os, "replace", replace)
    with facade._locked_state() as state:
        state["metrics"]["acquisitions_total"] += 1
    assert events == ["fsync", "replace", "fsync"]
    assert facade.lock_path == path.with_name(path.name+".lock")
    assert list(path.parent.glob("."+path.name+".*.tmp")) == []
