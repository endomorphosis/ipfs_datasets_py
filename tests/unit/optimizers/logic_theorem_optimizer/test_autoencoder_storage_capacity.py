"""Disposable administrative metadata; never production migration authority.

All schedulers, ledgers, retained rows and files are test-authored below
tmp_path. No workload is launched or acquired. The actual selected backend
must already declare220GB: these tests never monkeypatch a capacity/policy cap.
"""
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest


PACKAGE = os.environ.get("IPFS_RECOVERY_TEST_PACKAGE",
    "ipfs_datasets_py.optimizers.logic_theorem_optimizer")
capacity = importlib.import_module(PACKAGE + ".autoencoder_storage_capacity")
resources = importlib.import_module(PACKAGE + ".autoencoder_daemon_resources")
existing = importlib.import_module(PACKAGE + ".existing_resource_scheduler")
native = importlib.import_module(PACKAGE + ".resource_scheduler")
proof = importlib.import_module(PACKAGE + ".proof_resource_safety")
telemetry = importlib.import_module(PACKAGE + ".runtime_telemetry")


def save(path, value):
    path.write_bytes(json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n")
    path.chmod(0o600)  # Only this disposable fixture; independent of host umask.


def pin(path):
    raw = Path(path).read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


@pytest.fixture
def case(tmp_path):
    assert resources.MAX_STORAGE_BYTES == 220_000_000_000, "qualify the real target backend first"
    roots = [tmp_path / "synthetic-a", tmp_path / "synthetic-b"]
    for root, data in zip(roots, (b"first", b"second!")):
        root.mkdir()
        (root / "ordinary.txt").write_bytes(data)
    config = native.ResourceSchedulerConfig(state_path=tmp_path / "scheduler.json",
        total_cpu_slots=16, total_memory_mb=32_768, total_child_process_slots=16,
        lane_reservations={}, proof_safety_enabled=True, proof_recovery_enabled=True,
        proof_cpu_stall_percent=65.0, auto_renew_leases=False)
    scheduler = native.GlobalResourceScheduler(config)
    ledger = tmp_path / "ledger.json"
    rows = {}
    for index, (status, amount) in enumerate((
            ("retained", 700), ("released", 200_000_000_000), ("reserved", 200), ("active", 300))):
        key = str(index + 1) * 32
        rows[key] = {"reservation_id": key, "status": status,
            "owner_pid": 99_999_999 - index, "storage_bytes": amount,
            "child_process_slots": 4, "child": None, "prior_children": [],
            "external_charges": {"unchanged-foreign-promise": 500} if index == 0 else {},
            "artifacts_durable_asserted": False, "historical_opaque_fields": {"text": "preserve me"}}
    data = {"schema": resources.SCHEMA, "roots": [resources._root_identity(root) for root in roots],
            "limit_bytes": 200_000_000_000, "reservations": rows}
    save(ledger, data)
    ledger.with_name(ledger.name + ".lock").touch(mode=0o600)
    sources = [pin(Path(module.__file__))
               for module in (capacity, resources, existing, native, proof, telemetry)]
    args = dict(roots=roots, expected_ledger_sha256=pin(ledger)["sha256"],
        previous_limit_bytes=200_000_000_000, new_limit_bytes=220_000_000_000,
        scheduler_state_path=config.state_path,
        expected_scheduler_policy_sha256=existing.policy_sha256(config.persisted_dict()),
        expected_source_pins=sources)
    return dict(root=tmp_path, roots=roots, ledger=ledger, data=data, scheduler=scheduler,
        backup=tmp_path / "exact-old-ledger.backup.json", args=args,
        backend_cap=resources.MAX_STORAGE_BYTES, scheduler_bytes=Path(config.state_path).read_bytes())


def call(case, **changes):
    args = dict(case["args"])
    args.update(changes)
    return capacity.expand_storage_capacity(case["ledger"], **args)


def reseal(case):
    save(case["ledger"], case["data"])
    case["args"]["expected_ledger_sha256"] = pin(case["ledger"])["sha256"]


def no_authority(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("storage administration must not construct an owner or acquire/recover native authority")
    monkeypatch.setattr(resources.DaemonResourceReservation, "__init__", forbidden)
    monkeypatch.setattr(native.GlobalResourceScheduler, "__init__", forbidden)
    monkeypatch.setattr(native.GlobalResourceScheduler, "acquire", forbidden)
    monkeypatch.setattr(native.GlobalResourceScheduler, "recover_stale_leases", forbidden)


def test_default_plan_is_readonly_and_counts_full_promises_once(case, monkeypatch):
    before = case["ledger"].read_bytes()
    no_authority(monkeypatch)
    result = call(case)
    assert result["applied"] is False and result["status"] == "ready_explicit_apply"
    assert case["ledger"].read_bytes() == before
    assert not case["backup"].exists()
    assert case["scheduler"].state_path.read_bytes() == case["scheduler_bytes"]
    assert result["initial_accounting"]["observed_apparent_bytes"] == 12
    assert result["initial_accounting"]["outstanding_full_reservations_bytes"] == 1200
    assert result["initial_accounting"]["charged_bytes"] == 1212
    assert result["fresh_global_inventory_count"] == 2
    assert result["admitted"] is result["new_resource_lease_acquired"] is False
    assert result["new_reservation_created"] is result["reservation_records_changed"] is False
    assert result["scheduler_state_changed"] is result["outputs_deleted"] is False
    assert result["atomic_global_snapshot"] is result["continuous_custody_proved"] is False
    assert resources.MAX_STORAGE_BYTES == case["backend_cap"] == 220_000_000_000


def test_apply_changes_only_global_limit_and_fsyncs_exact_old_backup(case, monkeypatch):
    before = case["ledger"].read_bytes()
    no_authority(monkeypatch)
    result = call(case, apply=True, backup_path=case["backup"])
    after = json.loads(case["ledger"].read_bytes())
    expected = copy.deepcopy(case["data"])
    expected["limit_bytes"] = 220_000_000_000
    assert after == expected
    assert after["reservations"] == case["data"]["reservations"]
    assert case["backup"].read_bytes() == before
    assert stat.S_IMODE(case["backup"].stat().st_mode) == 0o600
    assert result["backup_pin"] == pin(case["backup"])
    assert result["previous_ledger_sha256"] == hashlib.sha256(before).hexdigest()
    assert result["successor_ledger_sha256"] == pin(case["ledger"])["sha256"]
    assert result["applied"] is result["actual_postwrite_capacity_census_required"] is True
    assert case["scheduler"].state_path.read_bytes() == case["scheduler_bytes"]
    assert [path.read_bytes() for root in case["roots"] for path in root.iterdir()] == [b"first", b"second!"]
    assert resources.MAX_STORAGE_BYTES == case["backend_cap"]


def test_normal_native_reader_refuses_old_limit_then_accepts_explicit_successor(case):
    helper = resources.DaemonResourceReservation(case["ledger"], roots=case["roots"],
        storage_bytes=1, memory_mb=1, require_existing_ledger=True)
    with pytest.raises(resources.DaemonResourceError, match="storage scope differs"):
        helper._read()
    call(case, apply=True, backup_path=case["backup"])
    assert helper._read()["limit_bytes"] == 220_000_000_000
    assert not helper._entered


def test_genuine_native_prior_child_metadata_is_preserved_and_group_checked(case, monkeypatch):
    historical = {"pid": 99_999_990, "birth": "123", "group_observed_dead_at": 1234.5}
    case["data"]["reservations"]["1" * 32]["prior_children"] = [historical]
    reseal(case)
    checked = []
    def group(child):
        checked.append(copy.deepcopy(child))
        assert child == {"pid": historical["pid"], "birth": historical["birth"]}
        return {"available": True, "live_processes": 0, "rss_bytes": 0}
    monkeypatch.setattr(resources, "_group_usage", group)
    call(case, apply=True, backup_path=case["backup"])
    assert len(checked) >= 2
    assert json.loads(case["ledger"].read_bytes())["reservations"]["1" * 32]["prior_children"] == [historical]


@pytest.mark.parametrize("timestamp", [True, -1, "1234"])
def test_invalid_historical_child_observation_refuses(case, timestamp):
    case["data"]["reservations"]["2" * 32]["prior_children"] = [
        {"pid": 99_999_990, "birth": "123", "group_observed_dead_at": timestamp}]
    reseal(case)
    with pytest.raises(capacity.StorageCapacityExpansionError, match="historical_child_observation"):
        call(case, apply=True, backup_path=case["backup"])
    assert not case["backup"].exists()


def test_same_owner_group_native_scheduler_lock_is_accepted_without_chmod(case):
    lock = case["scheduler"].lock_path
    lock.chmod(0o664)
    before = lock.stat()
    call(case)
    after = lock.stat()
    assert stat.S_IMODE(after.st_mode) == 0o664
    assert (after.st_dev, after.st_ino, after.st_uid, after.st_gid) == (
        before.st_dev, before.st_ino, before.st_uid, before.st_gid)


def test_other_writable_scheduler_lock_refuses_without_chmod(case):
    lock = case["scheduler"].lock_path
    lock.chmod(0o666)
    with pytest.raises(capacity.StorageCapacityExpansionError, match="existing_scheduler_lock"):
        call(case)
    assert stat.S_IMODE(lock.stat().st_mode) == 0o666


@pytest.mark.parametrize("changes", [
    {"previous_limit_bytes": 160_000_000_000}, {"previous_limit_bytes": True},
    {"new_limit_bytes": 221_000_000_000}, {"new_limit_bytes": 220_000_000_000.0},
    {"new_limit_bytes": "220000000000"}, {"apply": 1}, {"apply": None},
])
def test_nonreviewed_transition_and_nonbool_apply_refuse(case, changes):
    before = case["ledger"].read_bytes()
    with pytest.raises(capacity.StorageCapacityExpansionError):
        call(case, **changes)
    assert case["ledger"].read_bytes() == before


def test_apply_requires_explicit_unused_sibling_backup(case):
    with pytest.raises(capacity.StorageCapacityExpansionError, match="explicit_backup"):
        call(case, apply=True)
    outside = case["roots"][0] / "not-a-sibling.json"
    with pytest.raises(capacity.StorageCapacityExpansionError, match="sibling_backup"):
        call(case, apply=True, backup_path=outside)
    case["backup"].write_bytes(b"preexisting unrelated file")
    with pytest.raises(FileExistsError):
        call(case, apply=True, backup_path=case["backup"])
    assert case["backup"].read_bytes() == b"preexisting unrelated file"
    assert case["ledger"].read_bytes() == json.dumps(case["data"], sort_keys=True, indent=2).encode() + b"\n"


@pytest.mark.parametrize("fault", ["missing", "duplicate", "wrong_digest", "bool_bytes"])
def test_source_pin_closure_is_exact_and_checked_before_backup(case, fault):
    pins = copy.deepcopy(case["args"]["expected_source_pins"])
    if fault == "missing":
        pins.pop()
    elif fault == "duplicate":
        pins[-1] = copy.deepcopy(pins[0])
    elif fault == "wrong_digest":
        pins[0]["sha256"] = "0" * 64
    else:
        pins[0]["bytes"] = True
    with pytest.raises(capacity.StorageCapacityExpansionError):
        call(case, expected_source_pins=pins, apply=True, backup_path=case["backup"])
    assert not case["backup"].exists()


def test_stale_ledger_sha_refuses_before_backup(case):
    before = case["ledger"].read_bytes()
    with pytest.raises(capacity.StorageCapacityExpansionError, match="preimage_changed"):
        call(case, expected_ledger_sha256="0" * 64, apply=True, backup_path=case["backup"])
    assert case["ledger"].read_bytes() == before and not case["backup"].exists()


@pytest.mark.parametrize("kind", ["leases", "waiters", "recovery"])
def test_native_activity_blocks_plan_and_apply_without_recovery(case, kind):
    path = case["scheduler"].state_path
    state = json.loads(path.read_bytes())
    if kind == "recovery":
        state["proof_recovery"] = dict(phase="settling", healthy_samples=0,
            next_sample_at=0, next_grant_at=0, grants_remaining=case["scheduler"].config.proof_recovery_grants)
    else:
        state[kind]["synthetic-live-metadata"] = dict(owner_pid=os.getpid(), lane="orchestration",
            cpu_slots=1, memory_mb=1, child_process_slots=1)
    save(path, state)
    before = path.read_bytes()
    for apply in (False, True):
        with pytest.raises(capacity.StorageCapacityExpansionError, match="idle_scheduler"):
            call(case, apply=apply, backup_path=case["backup"] if apply else None)
    assert path.read_bytes() == before and not case["backup"].exists()


def test_active_backoff_blocks_and_expired_backoff_history_is_preserved(case):
    path = case["scheduler"].state_path
    state = json.loads(path.read_bytes())
    state["proof_backoff"] = {"until": 10**12, "reason": "synthetic"}
    save(path, state)
    with pytest.raises(capacity.StorageCapacityExpansionError, match="active_backoff"):
        call(case)
    state["proof_backoff"]["until"] = 0
    save(path, state)
    before = path.read_bytes()
    call(case, apply=True, backup_path=case["backup"])
    assert path.read_bytes() == before


def test_any_present_original_owner_including_reused_pid_blocks(case, monkeypatch):
    owner = case["data"]["reservations"]["1" * 32]["owner_pid"]
    monkeypatch.setattr(resources, "_process", lambda pid: {"pid": pid, "birth": "different"} if pid == owner else None)
    with pytest.raises(capacity.StorageCapacityExpansionError, match="original_owner_present"):
        call(case, apply=True, backup_path=case["backup"])
    assert not case["backup"].exists()


@pytest.mark.parametrize("reused", [False, True])
def test_live_or_reused_recorded_child_group_refuses(case, monkeypatch, reused):
    child = {"pid": 99_999_990, "birth": "123"}
    case["data"]["reservations"]["1" * 32]["child"] = child
    reseal(case)
    def group(value):
        assert value == child
        if reused:
            raise resources.DaemonResourceError("child PID was reused")
        return {"available": True, "live_processes": 1, "rss_bytes": 0}
    monkeypatch.setattr(resources, "_group_usage", group)
    with pytest.raises(resources.DaemonResourceError):
        call(case, apply=True, backup_path=case["backup"])
    assert not case["backup"].exists()


@pytest.mark.parametrize("changes", [
    {"status": "unknown"}, {"storage_bytes": True}, {"owner_pid": False},
    {"storage_bytes": 200_000_000_001}, {"external_charges": {"x": True}},
    {"child_process_slots": 0}, {"child": {"pid": 12, "birth": "not-ticks"}},
])
def test_every_record_is_validated_without_mutating_it(case, changes):
    case["data"]["reservations"]["2" * 32].update(changes)  # Even released rows must validate.
    reseal(case)
    before = case["ledger"].read_bytes()
    with pytest.raises(capacity.StorageCapacityExpansionError):
        call(case, apply=True, backup_path=case["backup"])
    assert case["ledger"].read_bytes() == before and not case["backup"].exists()


@pytest.mark.parametrize("raw", [b'{"schema":1,"schema":2}',
    b'{"x":NaN}', b'{"x":1e9999}'])
def test_duplicate_or_nonfinite_json_refuses(case, raw):
    case["ledger"].write_bytes(raw)
    case["args"]["expected_ledger_sha256"] = pin(case["ledger"])["sha256"]
    with pytest.raises(capacity.StorageCapacityExpansionError):
        call(case)
    assert case["ledger"].read_bytes() == raw


@pytest.mark.parametrize("kind", ["order", "inode", "extra_schema"])
def test_exact_original_scope_and_schema_required(case, kind):
    if kind == "order":
        case["data"]["roots"].reverse()
    elif kind == "inode":
        case["data"]["roots"][0]["inode"] += 1
    else:
        case["data"]["migration"] = "not-native"
    reseal(case)
    with pytest.raises(capacity.StorageCapacityExpansionError, match="ledger_scope"):
        call(case)


@pytest.mark.parametrize("kind", ["same", "disk_at_scheduler_lock", "scheduler_at_disk_lock"])
def test_all_four_control_paths_must_be_distinct(case, kind):
    ledger = case["ledger"]
    scheduler = case["scheduler"].state_path
    if kind == "same":
        changes = {"scheduler_state_path": ledger}
    elif kind == "disk_at_scheduler_lock":
        ledger = scheduler.with_name(scheduler.name + ".lock")
        changes = {}
    else:
        changes = {"scheduler_state_path": ledger.with_name(ledger.name + ".lock")}
    args = dict(case["args"], **changes)
    with pytest.raises(capacity.StorageCapacityExpansionError, match="distinct_control_paths"):
        capacity.expand_storage_capacity(ledger, **args)


@pytest.mark.parametrize("which", ["disk", "scheduler"])
def test_missing_existing_lock_is_not_created(case, which):
    base = case["ledger"] if which == "disk" else case["scheduler"].state_path
    path = base.with_name(base.name + ".lock")
    path.unlink()
    with pytest.raises(FileNotFoundError):
        call(case)
    assert not path.exists()


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_ledger_alias_refuses(case, kind):
    path = case["ledger"]
    if kind == "symlink":
        target = path.with_name("other-ledger.json")
        path.rename(target)
        path.symlink_to(target.name)
    else:
        os.link(path, path.with_name("alias.json"))
    with pytest.raises(capacity.StorageCapacityExpansionError):
        call(case)


def test_full_claim_overage_refuses_without_any_huge_files_or_cap_patch(case):
    for row in case["data"]["reservations"].values():
        if row["status"] != "released":
            row["storage_bytes"] = 200_000_000_000
    reseal(case)
    with pytest.raises(capacity.StorageCapacityExpansionError, match="target_insufficient"):
        call(case, apply=True, backup_path=case["backup"])
    assert resources.MAX_STORAGE_BYTES == case["backend_cap"]
    assert not case["backup"].exists()


def test_filesystem_free_must_cover_all_outstanding_promises(case, monkeypatch):
    monkeypatch.setattr(resources.shutil, "disk_usage", lambda path: SimpleNamespace(free=1199))
    with pytest.raises(capacity.StorageCapacityExpansionError, match="filesystem_free_insufficient"):
        call(case, apply=True, backup_path=case["backup"])
    assert not case["backup"].exists()


def test_second_actual_census_detects_growth_before_replacement(case, monkeypatch):
    original = resources._inventory
    calls = []
    def inventory(roots):
        result = original(roots)
        calls.append(result)
        if len(calls) == 2:
            result["apparent_bytes"] = 220_000_000_000
        return result
    monkeypatch.setattr(resources, "_inventory", inventory)
    before = case["ledger"].read_bytes()
    with pytest.raises(capacity.StorageCapacityExpansionError, match="target_insufficient"):
        call(case, apply=True, backup_path=case["backup"])
    assert len(calls) == 2 and case["ledger"].read_bytes() == before
    assert case["backup"].read_bytes() == before


def test_partial_backup_fsync_failure_never_replaces_original(case, monkeypatch):
    original = os.fsync
    def fsync(fd):
        if case["backup"].exists() and os.fstat(fd).st_ino == case["backup"].stat().st_ino:
            raise OSError("synthetic backup durability failure")
        return original(fd)
    monkeypatch.setattr(os, "fsync", fsync)
    before = case["ledger"].read_bytes()
    with pytest.raises(OSError):
        call(case, apply=True, backup_path=case["backup"])
    assert case["ledger"].read_bytes() == before


def test_outside_lock_ledger_change_during_census_refuses_without_overwriting(case, monkeypatch):
    original = resources._inventory
    changed = copy.deepcopy(case["data"])
    changed["reservations"]["1" * 32]["historical_opaque_fields"]["new"] = "outside-lock change"
    def inventory(roots):
        result = original(roots)
        save(case["ledger"], changed)
        return result
    monkeypatch.setattr(resources, "_inventory", inventory)
    with pytest.raises(capacity.StorageCapacityExpansionError, match="ledger_changed_outside_lock"):
        call(case, apply=True, backup_path=case["backup"])
    assert json.loads(case["ledger"].read_bytes()) == changed
    assert not case["backup"].exists()


def test_owner_appearing_after_final_census_blocks_write(case, monkeypatch):
    original = resources._inventory
    count = [0]
    def inventory(roots):
        result = original(roots)
        count[0] += 1
        return result
    monkeypatch.setattr(resources, "_inventory", inventory)
    monkeypatch.setattr(resources, "_process", lambda pid: None if count[0] < 2 else {"pid": pid})
    before = case["ledger"].read_bytes()
    with pytest.raises(capacity.StorageCapacityExpansionError, match="original_owner_present"):
        call(case, apply=True, backup_path=case["backup"])
    assert count[0] == 2 and case["ledger"].read_bytes() == before


def test_replacement_response_loss_is_unknown_without_rollback_or_retry(case, monkeypatch):
    original = os.replace
    old = case["ledger"].read_bytes()
    def replace(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("synthetic loss after genuine atomic replacement")
    monkeypatch.setattr(os, "replace", replace)
    with pytest.raises(capacity.StorageCapacityWriteOutcomeUnknown) as caught:
        call(case, apply=True, backup_path=case["backup"])
    assert caught.value.may_have_applied is True
    assert caught.value.previous_ledger_sha256 == hashlib.sha256(old).hexdigest()
    assert caught.value.successor_ledger_sha256 == pin(case["ledger"])["sha256"]
    assert json.loads(case["ledger"].read_bytes())["limit_bytes"] == 220_000_000_000
    assert case["backup"].read_bytes() == old
    with pytest.raises(capacity.StorageCapacityExpansionError, match="preimage_changed"):
        call(case, apply=True, backup_path=case["root"] / "do-not-retry.backup")
    assert not list(case["root"].glob(".storage-capacity-*.tmp"))


def test_late_lock_domain_change_after_replacement_is_reported_unknown(case, monkeypatch):
    original = capacity._replace
    def replace(*args, **kwargs):
        original(*args, **kwargs)
        lock = case["ledger"].with_name(case["ledger"].name + ".lock")
        replacement = lock.with_name("new-test-lock")
        replacement.touch(mode=0o600)
        os.replace(replacement, lock)
    monkeypatch.setattr(capacity, "_replace", replace)
    with pytest.raises(capacity.StorageCapacityWriteOutcomeUnknown):
        call(case, apply=True, backup_path=case["backup"])
    assert json.loads(case["ledger"].read_bytes())["limit_bytes"] == 220_000_000_000
    assert case["backup"].exists()
