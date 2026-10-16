"""Bounded native unit fixtures; no actual campaign state or subprocesses.

Run only in an admitted native validation after installing the proposal in the
native package. These fixtures use four temporary storage roots and absent PIDs;
they do not monkeypatch ledger/census/process checks or acquire resource leases.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_resource_recovery as base
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_prelaunch_resource_recovery as recovery


def _save(path, value):
    path.write_text(json.dumps(value, sort_keys=True))
    path.chmod(0o600)


def _pin(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


@pytest.fixture
def case(tmp_path):
    roots = [tmp_path / f"named-{n}" for n in range(4)]
    for root in roots:
        root.mkdir()
    attempt = roots[0] / "failed-attempt"
    attempt.mkdir()
    controller = roots[1] / "controller"
    controller.mkdir()
    catalog = roots[0] / "catalog"
    catalog.mkdir()
    (catalog / "quack-owner").mkdir()
    (catalog / "control.duckdb").write_bytes(b"preserved fixture database; never opened")
    source = tmp_path / "source"
    source.mkdir()
    owner = source / "run_native_owner.py"
    entry = source / "start_grok_supervisor.py"
    launcher = source / "launch_retained_master.py"
    quack = source / "retained_catalog_owner.py"
    owner.write_text("# reviewed original explicit orchestration owner fixture\n")
    entry.write_text("# reviewed original controller entry fixture\n")
    launcher.write_text("def run_retained_supervisor():\n    with helper.retained_quack_owner() as live:\n        subprocess.Popen([])\n")
    quack.write_text("def retained_quack_owner():\n    identity = server.start()\n    yield identity\n")
    sources = [owner, entry, launcher, quack]
    for path in sources:
        path.chmod(0o600)
    request_path = source / "original-request.json"
    request = {"schema": "legal-ir-native-orchestration-request@1", "purpose": "supervisor_launch",
        "attempt_directory": str(attempt), "storage_bytes": 4 * 1024 * 1024,
        "command": ["/usr/bin/python3", "-B", str(entry)],
        "native_terminal_receipt": str(controller / "workspace/native-run/state/master.pid.terminal.json"),
        "source_sha256": {str(path): _pin(path)["sha256"] for path in sources},
        "external_charges": [{"path": str(controller), "bytes": 1024 * 1024},
                             {"path": str(catalog), "bytes": 1024 * 1024}]}
    _save(request_path, request)
    child = {"pid": 2147483646, "birth": "1"}
    record = {"reservation_id": "fixture-failed-pre-master", "owner_pid": 2147483647,
        "storage_bytes": request["storage_bytes"], "status": "active", "memory_mb": 4096,
        "cpu_slots": 3, "child_process_slots": 4,
        "attempt_directory": base.resources._root_identity(attempt), "child": child,
        "prior_children": [], "parent_lease_id": "fixture-original-phase", "native_lease_id": "fixture-native-lease",
        "external_charges": {hashlib.sha256(row["path"].encode()).hexdigest(): row["bytes"]
                             for row in request["external_charges"]}}
    receipt = {"schema": "legal-ir-native-orchestration-receipt@1", "purpose": "supervisor_launch",
        "request_sha256": _pin(request_path)["sha256"], "owner_pid": record["owner_pid"],
        "disk_reservation_id": record["reservation_id"], "phase_lease_id": record["parent_lease_id"],
        "child_pid": child["pid"], "child_pgid": child["pid"],
        "status": "resource_held_pending_native_fence", "native_stop_verified": False}
    _save(attempt / "receipt.json", receipt)
    _save(attempt / "launch-operations.json", [{"operation": "original_quack_capability",
          "body": {"catalog_opened": False, "worker_dispatched": False}}])
    (attempt / "child.sanitized.log").write_text(
        "Traceback (most recent call last):\n"
        + str(entry) + "\n" + str(launcher) + " run_retained_supervisor\n"
        + str(quack) + " retained_quack_owner\nidentity = server.start()\n"
        "_bind_configured_database_status\n_resolve_database_status_scope\n"
        "TypedStateOwnerAuthorizationError: [REDACTED] status source binding changed\n")
    (attempt / "child.sanitized.log").chmod(0o600)
    other = copy.deepcopy(record)
    other.update(reservation_id="unrelated-reservation", status="retained", storage_bytes=4096)
    ledger = roots[0] / "disk-reservations.json"
    _save(ledger, {"schema": base.resources.SCHEMA, "roots": [base.resources._root_identity(root) for root in roots],
                  "limit_bytes": base.resources.MAX_STORAGE_BYTES,
                  "reservations": {record["reservation_id"]: record, other["reservation_id"]: other}})
    proof = {"schema": recovery.PROOF_SCHEMA, "original_request_pin": _pin(request_path),
        "source_roles": {"orchestration_owner": str(owner), "controller_entry": str(entry),
                         "master_launcher": str(launcher), "quack_owner": str(quack)},
        "source_pins": [_pin(path) for path in sources], "receipt_pin": _pin(attempt / "receipt.json"),
        "failure_log_pin": _pin(attempt / "child.sanitized.log"),
        "operations_pin": _pin(attempt / "launch-operations.json"),
        "owner_identity": {"pid": record["owner_pid"], "birth": "1"}, "child_identity": child,
        "native_generation_directory": str(controller / "workspace/native-run"),
        "quack_state_directory": str(catalog / "quack-owner")}
    disposition = [{"key": hashlib.sha256(str(path).encode()).hexdigest(), "path": str(path),
                    "bytes": 1024 * 1024, "directory_identity": base.resources._root_identity(path),
                    "expected_artifacts": recovery.durable_external_inventory(path)} for path in (controller, catalog)]
    kwargs = {"roots": roots, "reservation_id": record["reservation_id"],
        "expected_record_sha256": base._digest(record), "attempt_directory": str(attempt),
        "expected_artifacts": base._durable_inventory(attempt), "proof": proof,
        "external_dispositions": disposition, "artifacts_durable": True}
    return {"ledger": ledger, "kwargs": kwargs, "record": record, "other": other,
            "attempt": attempt, "catalog": catalog, "controller": controller, "source": sources}


def _run(case):
    return recovery.reconcile_failed_prelaunch_reservation(case["ledger"], **case["kwargs"])


def _reject_without_write(case):
    before = case["ledger"].read_bytes()
    with pytest.raises(base.resources.DaemonResourceError):
        _run(case)
    assert case["ledger"].read_bytes() == before


def test_dead_active_prelaunch_preserves_other_claim_and_external_charge(case):
    receipt = _run(case)
    current = json.loads(case["ledger"].read_text())
    selected = current["reservations"][case["record"]["reservation_id"]]
    assert selected["status"] == "released"
    assert current["reservations"][case["other"]["reservation_id"]] == case["other"]
    assert selected["external_charges"] == case["record"]["external_charges"]
    assert receipt["native_fence_synthesized"] is False and receipt["native_stop_verified"] is False
    assert receipt["admitted"] is False and receipt["new_resource_lease_acquired"] is False
    assert receipt["fresh_global_inventory_count"] == 2 and receipt["atomic_ledger_write_count"] == 1
    assert receipt["full_claim_accounting"]["outstanding_full_reservations_bytes"] - receipt["final_accounting"]["outstanding_full_reservations_bytes"] == case["record"]["storage_bytes"]
    assert receipt["actual_postwrite_census_required"] is True
    assert (case["catalog"] / "control.duckdb").read_bytes() == b"preserved fixture database; never opened"
    assert not Path(case["kwargs"]["proof"]["native_generation_directory"]).exists()


@pytest.mark.parametrize("mutation", ["live_owner", "live_child", "wrong_record", "wrong_request",
    "changed_source", "source_incomplete", "source_launch_order", "native_generation",
    "populated_quack", "wrong_charge", "missing_charge", "wrong_directory_identity",
    "changed_external_payload", "changed_attempt", "native_stop_claim", "later_launch_operation",
    "wrong_failure_trace", "proof_symlink", "external_symlink_changed", "external_special_file", "no_durability"])
def test_refuses_unsafe_or_changed_closeout_without_ledger_write(case, mutation):
    kwargs = case["kwargs"]
    proof = kwargs["proof"]
    def edit_receipt(change):
        path = case["attempt"] / "receipt.json"
        value = json.loads(path.read_text()); value.update(change); _save(path, value)
        proof["receipt_pin"] = _pin(path)
        kwargs["expected_artifacts"] = base._durable_inventory(case["attempt"])
    if mutation == "live_owner":
        current = json.loads(case["ledger"].read_text())
        current["reservations"][case["record"]["reservation_id"]]["owner_pid"] = os.getpid()
        _save(case["ledger"], current)
        kwargs["expected_record_sha256"] = base._digest(current["reservations"][case["record"]["reservation_id"]])
        proof["owner_identity"]["pid"] = os.getpid(); edit_receipt({"owner_pid": os.getpid()})
    elif mutation == "live_child":
        # Current process is its group's member; no child is started or killed.
        leader = os.getpgrp(); observed = base.resources._process(leader)
        child = {"pid": leader, "birth": observed["birth"]}
        current = json.loads(case["ledger"].read_text())
        selected = current["reservations"][case["record"]["reservation_id"]]
        selected["child"] = child; _save(case["ledger"], current)
        kwargs["expected_record_sha256"] = base._digest(selected)
        proof["child_identity"] = child; edit_receipt({"child_pid": leader, "child_pgid": leader})
    elif mutation == "wrong_record": kwargs["expected_record_sha256"] = "0" * 64
    elif mutation == "wrong_request": proof["original_request_pin"]["sha256"] = "0" * 64
    elif mutation == "changed_source": case["source"][0].write_text("changed original source")
    elif mutation == "source_incomplete": proof["source_pins"].pop()
    elif mutation == "source_launch_order":
        path = case["source"][2]; path.write_text("def run_retained_supervisor():\n    subprocess.Popen([])\n    with helper.retained_quack_owner():\n        pass\n")
        source_pins = [_pin(p) for p in case["source"]]; proof["source_pins"] = source_pins
        request_path = Path(proof["original_request_pin"]["path"])
        request = json.loads(request_path.read_text()); request["source_sha256"] = {p["path"]: p["sha256"] for p in source_pins}
        _save(request_path, request); proof["original_request_pin"] = _pin(request_path)
        edit_receipt({"request_sha256": proof["original_request_pin"]["sha256"]})
    elif mutation == "native_generation": Path(proof["native_generation_directory"]).mkdir(parents=True)
    elif mutation == "populated_quack": (case["catalog"] / "quack-owner/status.json").write_text("{}")
    elif mutation == "wrong_charge": kwargs["external_dispositions"][0]["bytes"] += 1
    elif mutation == "missing_charge": kwargs["external_dispositions"].pop()
    elif mutation == "wrong_directory_identity": kwargs["external_dispositions"][0]["directory_identity"]["inode"] += 1
    elif mutation == "changed_external_payload": (case["catalog"] / "control.duckdb").write_bytes(b"changed")
    elif mutation == "changed_attempt": (case["attempt"] / "late-output.json").write_text("{}")
    elif mutation == "native_stop_claim": edit_receipt({"native_stop_verified": True})
    elif mutation == "later_launch_operation":
        path = case["attempt"] / "launch-operations.json"; _save(path, [{"operation": "native_master_lifecycle"}])
        proof["operations_pin"] = _pin(path); kwargs["expected_artifacts"] = base._durable_inventory(case["attempt"])
    elif mutation == "wrong_failure_trace":
        path = case["attempt"] / "child.sanitized.log"; path.write_text("different late failure\n")
        proof["failure_log_pin"] = _pin(path); kwargs["expected_artifacts"] = base._durable_inventory(case["attempt"])
    elif mutation == "proof_symlink":
        original = Path(proof["original_request_pin"]["path"])
        linked = original.parent / "symlink-request.json"; linked.symlink_to(original)
        proof["original_request_pin"]["path"] = str(linked)
    elif mutation == "external_symlink_changed":
        link = case["controller"] / "legacy-link.py"
        link.symlink_to("/never-follow-this-original-target")
        kwargs["external_dispositions"][0]["expected_artifacts"] = recovery.durable_external_inventory(case["controller"])
        link.unlink(); link.symlink_to("/never-follow-this-changed-target")
    elif mutation == "external_special_file": os.mkfifo(case["controller"] / "unexpected-pipe")
    elif mutation == "no_durability": kwargs["artifacts_durable"] = False
    _reject_without_write(case)


def test_retained_failed_prelaunch_is_supported_with_exact_frozen_record(case):
    current = json.loads(case["ledger"].read_text())
    selected = current["reservations"][case["record"]["reservation_id"]]
    selected["status"] = "retained"
    _save(case["ledger"], current)
    case["kwargs"]["expected_record_sha256"] = base._digest(selected)
    assert _run(case)["original_status"] == "retained"


def test_second_closeout_refuses_existing_released_claim(case):
    _run(case)
    _reject_without_write(case)


def test_preserves_legacy_lexical_symlink_without_reading_target(case):
    link = case["controller"] / "existing-legacy-link.py"
    target = "/outside-owned-roots/target-does-not-exist.py"
    link.symlink_to(target)
    inventory = recovery.durable_external_inventory(case["controller"])
    assert inventory == [{"path": link.name, "kind": "symlink", "bytes": len(target.encode()),
                          "sha256": hashlib.sha256(target.encode()).hexdigest()}]
    case["kwargs"]["external_dispositions"][0]["expected_artifacts"] = inventory
    receipt = _run(case)
    assert link.is_symlink() and os.readlink(link) == target
    assert receipt["outputs_deleted"] is False
