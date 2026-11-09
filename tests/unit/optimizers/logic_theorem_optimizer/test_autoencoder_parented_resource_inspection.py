"""Private, ordinary-file fixtures for active parented inspection.

The original native inspection fixture supplies a real typed private broker and
real kernel birth/boot observations.  Only private rows are authored.  No host
pressure, host ledger, admission, provider, model, alias or special file is used.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_parented_resource_inspection as api
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as sdk
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
from tests.unit.optimizers.logic_theorem_optimizer.test_resource_lease_inspection import private


RID, ROOT, PHASE, OWNED = (c * 32 for c in "a123")


def pin(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def identity(path):
    value = path.stat()
    return {"path": str(path), "device": value.st_dev, "inode": value.st_ino}


@pytest.fixture
def active(private, tmp_path):
    owner = {"pid": os.getppid(), "birth": sdk._owner_birth_marker(os.getppid())}
    child = {"pid": os.getpid(), "birth": sdk._owner_birth_marker(os.getpid())}
    assert owner["birth"] and child["birth"] and sdk._owner_boot_id()
    roots = [tmp_path / "outputs", tmp_path / "cache"]
    for root in roots:
        root.mkdir()
    attempt, fixture = roots[0] / "attempt", roots[1] / "fixtures"
    attempt.mkdir(); fixture.mkdir()
    output = fixture / "result.json"
    output.write_text("{}")
    ledger = tmp_path / "ledger.json"
    ledger.with_name(ledger.name + ".lock").write_bytes(b"")
    policy = existing.policy_sha256(private.state["config"])
    request_path = tmp_path / "request.json"
    request = {"schema": "legal-ir-original-parented-private-git-validation/v1",
        "request_id": "active-parented-test", "attempt_directory": str(attempt),
        "resource_ledger": str(ledger), "scheduler_state_path": str(private.scheduler.state_path),
        "expected_scheduler_policy_sha256": policy, "cpu_slots": 1, "memory_mb": 1,
        "child_process_slots": 2, "storage_bytes": 4096,
        "fixture_directory": str(fixture), "fixture_max_bytes": 2048}
    key = "physical-" + hashlib.sha256(str(fixture).encode()).hexdigest()
    row = {"reservation_id": RID, "status": "active", "owner_pid": owner["pid"],
        "attempt_directory": identity(attempt), "workload": "canonical_parented_phase",
        "scheduler_lane": "validation", "storage_bytes": 4096, "memory_mb": 1,
        "cpu_slots": 1, "child_process_slots": 2, "created_at": time.time(),
        "external_charges": {key: 2048}, "child": child, "prior_children": [],
        "artifacts_durable_asserted": False, "native_lease_id": OWNED,
        "parent_lease_id": PHASE, "scheduler_state_path": str(private.scheduler.state_path),
        "scheduler_policy_sha256": policy, "private_extra": "own-private-secret"}
    data = {"schema": api.resources.SCHEMA, "roots": [identity(root) for root in roots],
        "limit_bytes": api.resources.MAX_STORAGE_BYTES, "reservations": {RID: row}}
    original = deepcopy(private.state["leases"]["owned"])
    for identifier, parent, name in ((ROOT, None, "active-parented-test:root"),
            (PHASE, ROOT, "active-parented-test:phase"), (OWNED, PHASE, "daemon:" + RID)):
        value = deepcopy(original)
        value.update(lease_id=identifier, parent_lease_id=parent, request_id=name,
            lease_key="secret-" + identifier, owner_pid=owner["pid"],
            owner_birth_marker=owner["birth"], owner_boot_id=sdk._owner_boot_id(),
            child_process_slots=2, requires_gpu=False, lane="validation")
        private.state["leases"][identifier] = value
    c = SimpleNamespace(private=private, owner=owner, child=child, roots=roots,
        attempt=attempt, fixture=fixture, output=output, ledger=ledger,
        request=request, request_path=request_path, row=row, data=data)
    def write():
        request_path.write_text(json.dumps(request, sort_keys=True))
        execution = {"schema": "native-metadata-qualification-execution-request/v1",
            "request": pin(request_path), "request_sha256": pin(request_path)["sha256"],
            "disk_reservation_id": RID, "owner_pid": owner["pid"], "owner_birth": owner["birth"],
            "external_precharge": {"root": str(fixture), "bytes": 2048},
            "external_charge_key": next(iter(row["external_charges"])), "child_not_started": True}
        if request["schema"] == "legal-ir-original-native-control-request/v1":
            execution = {"schema": "native-metadata-resource-owner-execution-request/v1",
                "request": pin(request_path), "disk_reservation_id": RID,
                "provider_authority": False, "completion_authority": False,
                "external_precharge": {"key": next(iter(row["external_charges"])),
                    "bytes": 2048, "files": request["external_files"]}}
        (attempt / "execution-request.json").write_text(json.dumps(execution, sort_keys=True))
        ledger.write_text(json.dumps(data, sort_keys=True))
        private.scheduler.state_path.write_text(json.dumps(private.state, sort_keys=True))
        c.args = dict(roots=roots, reservation_id=RID,
            execution_request_pin=pin(attempt / "execution-request.json"),
            expected_request_sha256=pin(request_path)["sha256"], owner_identity=owner.copy(),
            child_identity=child.copy(), native_lease_token=sdk.ResourceLeaseToken(
                OWNED, "secret-" + OWNED, str(private.scheduler.state_path)),
            expected_phase_lease_id=PHASE, expected_scheduler_policy_sha256=policy,
            demand={"cpu_slots": 1, "memory_mb": 1, "child_process_slots": 1, "storage_bytes": 512},
            writable_paths=[output], sealed_work_deadline_monotonic=time.monotonic() + 30,
            expected_boot_id=sdk._owner_boot_id(), lock_timeout_seconds=1)
    c.write = write
    write()
    return c


def observe(c):
    return api.inspect_active_parented_reservation(c.ledger, **c.args)


@pytest.mark.parametrize("dialect", ["qualification", "actual"])
def test_live_funded_binding_keeps_broker_ledger_and_credentials_private(active, monkeypatch, dialect):
    c = active
    if dialect == "actual":
        files = [{"path": str(c.output), "max_bytes": 2048}]
        key = "control-" + hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        c.request.update(schema="legal-ir-original-native-control-request/v1", external_files=files)
        c.row.update(scheduler_lane="orchestration", external_charges={key: 2048})
        for name in (ROOT, PHASE, OWNED):
            c.private.state["leases"][name]["lane"] = "orchestration"
        c.write()
    def forbidden(*args, **kwargs):
        pytest.fail("read-only parent inspection must not admit, persist, census or sample")
    for name in ("acquire", "release", "cancel", "renew", "recover_stale_leases"):
        monkeypatch.setattr(sdk.GlobalResourceScheduler, name, forbidden)
    monkeypatch.setattr(api.resources.DaemonResourceReservation, "_account", forbidden)
    monkeypatch.setattr(api.resources, "_inventory", forbidden)
    before = c.ledger.read_bytes(), c.private.scheduler.state_path.read_bytes()
    result = observe(c)
    assert result["binding_verified"] is result["native_capability_authenticated"] is True
    assert result["allocated_envelope"]["storage_bytes"] == 4096
    assert result["native_lease_id"] == OWNED and result["phase_lease_id"] == PHASE
    assert result["root_lease_id"] == ROOT and result["demand"] == c.args["demand"]
    assert all(result[k] is False for k in ("compute_suballocation_reserved", "admitted",
        "state_written", "new_host_reservation", "recovery_performed", "credential_exported"))
    assert "secret-" not in json.dumps(result) and "own-private-secret" not in json.dumps(result)
    assert "lease_key" not in json.dumps(result)
    assert (c.ledger.read_bytes(), c.private.scheduler.state_path.read_bytes()) == before


@pytest.mark.parametrize("fault", ["retained", "released", "wrong_child_birth", "wrong_owner_birth",
    "wrong_native", "wrong_phase", "wrong_charge", "wrong_token", "dictionary_token",
    "wrong_request", "missing_child", "prior_child", "memory_excess", "storage_excess",
    "boolean_demand", "unfunded_path", "bad_boot", "expired_deadline", "cancelled_owned",
    "cancelled_phase", "expired_root", "reused_native_owner", "native_envelope_mismatch"])
def test_each_ambiguous_or_unfunded_binding_refuses_without_writes(active, fault):
    c = active
    if fault in {"retained", "released"}: c.row["status"] = fault
    elif fault == "wrong_child_birth": c.row["child"] = {**c.child, "birth": "0"}
    elif fault == "wrong_owner_birth": c.private.state["leases"][OWNED]["owner_birth_marker"] = "0"
    elif fault == "wrong_native": c.row["native_lease_id"] = "f" * 32
    elif fault == "wrong_phase": c.row["parent_lease_id"] = "f" * 32
    elif fault == "wrong_charge": c.row["external_charges"] = {"unbound": 2048}
    elif fault == "missing_child": c.row["child"] = None
    elif fault == "prior_child": c.row["prior_children"] = [c.child]
    elif fault == "cancelled_owned": c.private.state["leases"][OWNED]["cancelled"] = True
    elif fault == "cancelled_phase": c.private.state["leases"][PHASE]["cancelled"] = True
    elif fault == "expired_root": c.private.state["leases"][ROOT]["expires_at"] = 1
    elif fault == "reused_native_owner": c.private.state["leases"][ROOT]["owner_birth_marker"] = "0"
    elif fault == "native_envelope_mismatch": c.private.state["leases"][OWNED]["memory_mb"] = 2
    c.write()
    if fault == "wrong_token": c.args["native_lease_token"] = sdk.ResourceLeaseToken(OWNED, "wrong", str(c.private.scheduler.state_path))
    elif fault == "dictionary_token": c.args["native_lease_token"] = {"lease_id": OWNED, "lease_key": "secret-" + OWNED}
    elif fault == "wrong_request": c.args["expected_request_sha256"] = "0" * 64
    elif fault == "memory_excess": c.args["demand"]["memory_mb"] = 2
    elif fault == "storage_excess": c.args["demand"]["storage_bytes"] = 4097
    elif fault == "boolean_demand": c.args["demand"]["cpu_slots"] = True
    elif fault == "unfunded_path": c.args["writable_paths"] = [c.roots[0] / "outside.json"]
    elif fault == "bad_boot": c.args["expected_boot_id"] = "not-this-boot"
    elif fault == "expired_deadline": c.args["sealed_work_deadline_monotonic"] = 1
    before = c.ledger.read_bytes(), c.private.scheduler.state_path.read_bytes()
    with pytest.raises((api.resources.DaemonResourceError, sdk.ResourceSchedulerError)):
        observe(c)
    assert (c.ledger.read_bytes(), c.private.scheduler.state_path.read_bytes()) == before


@pytest.mark.parametrize("fault", ["symlink", "hardlink"])
def test_output_alias_metadata_is_refused_without_creating_aliases(active, monkeypatch, fault):
    c = active
    if fault == "symlink":
        original = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda p: p == c.output or original(p))
    else:
        original = Path.lstat
        def aliased(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            if path == c.output:
                fields = list(value); fields[3] = 2
                return os.stat_result(fields)
            return value
        monkeypatch.setattr(Path, "lstat", aliased)
    before = c.ledger.read_bytes(), c.private.scheduler.state_path.read_bytes()
    with pytest.raises(api.resources.DaemonResourceError): observe(c)
    assert (c.ledger.read_bytes(), c.private.scheduler.state_path.read_bytes()) == before


def test_changed_execution_request_is_detected_after_native_observation(active, monkeypatch):
    c = active
    original = sdk.GlobalResourceScheduler.inspect_lease
    calls = []
    def mutate(scheduler, *args, **kwargs):
        result = original(scheduler, *args, **kwargs)
        calls.append(1)
        if len(calls) == 1:
            path = c.attempt / "execution-request.json"
            value = json.loads(path.read_text()); value["disk_reservation_id"] = "f" * 32
            path.write_text(json.dumps(value))
        return result
    monkeypatch.setattr(sdk.GlobalResourceScheduler, "inspect_lease", mutate)
    before = c.ledger.read_bytes(), c.private.scheduler.state_path.read_bytes()
    with pytest.raises(api.resources.DaemonResourceError): observe(c)
    assert (c.ledger.read_bytes(), c.private.scheduler.state_path.read_bytes()) == before


def test_effective_deadline_never_exceeds_authenticated_outer_deadline(active):
    c = active
    result = observe(c)
    assert time.monotonic() < result["effective_work_deadline_monotonic"] <= c.args["sealed_work_deadline_monotonic"]
