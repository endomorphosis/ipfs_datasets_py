"""Offline protocol qualification on isolated ledgers; no Docker or native jobs.

The genuine test owner supplies the native outer resource grant. Docker and
public scheduler observations below are authored doubles; files, durability,
selected-record hashing and atomic ledger preservation use the actual SDK.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_resource_recovery as base

MODULE_PATH = Path(base.__file__).with_name("autoencoder_orphan_resource_recovery.py")
MODULE_NAME = "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_orphan_resource_recovery"
SPEC = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
orphan = importlib.util.module_from_spec(SPEC)
sys.modules[MODULE_NAME] = orphan
SPEC.loader.exec_module(orphan)


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


def pin(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


@pytest.fixture
def case(tmp_path, monkeypatch):
    roots = [tmp_path / str(index) for index in range(4)]
    for root in roots:
        root.mkdir()
    attempt = roots[0] / "failed-attempt"; attempt.mkdir()
    repo = roots[1] / "repo"; repo.mkdir()
    provider = roots[3] / "provider"; provider.mkdir()
    (repo / "source.py").write_bytes(b"# inert source metadata\n")
    (repo / "alias").symlink_to("source.py")
    reservation_id, root_id, phase_id, native_id = (character * 32 for character in "abcd")
    owner_pid, child_pid, master_pid, watchdog_pid = (99_999_991 + index for index in range(4))
    request_path = tmp_path / "original-request.json"
    terminal_path = repo / "native-terminal.json"
    request = {"schema": "legal-ir-native-orchestration-request@1", "purpose": "supervisor_launch",
        "attempt_directory": str(attempt), "cwd": str(repo), "storage_bytes": 200_000,
        "external_charges": [{"path": str(repo), "bytes": 20_000}, {"path": str(provider), "bytes": 10_000}],
        "board_namespace": "authored-ordinary-bootstrap", "native_terminal_receipt": str(terminal_path),
        "supervised_provider_temporary_root": str(provider)}
    write(request_path, request)
    terminal = {"schema": orphan.TERMINAL_SCHEMA, "master_pid": master_pid,
        "run_started_at_epoch_nanoseconds": 100, "label": request["board_namespace"],
        "active_binding_cid": "b-authored-active", "all_trees_fenced": True}
    terminal["terminal_receipt_cid"] = orphan._cid(terminal)
    write(terminal_path, terminal)
    receipt = {"schema": "legal-ir-native-orchestration-receipt@1", "purpose": "supervisor_launch",
        "owner_pid": owner_pid, "request_sha256": pin(request_path)["sha256"],
        "disk_reservation_id": reservation_id, "root_lease_id": root_id, "phase_lease_id": phase_id,
        "child_pid": child_pid, "child_pgid": child_pid, "native_stop_verified": True,
        "owned_group_quiescent": True, "status": "resource_held_ordinary_provider_cleanup_unresolved",
        "failure_type": "ProcessLookupError", "native_fence_proof": {
            key: terminal[key] for key in ("master_pid", "run_started_at_epoch_nanoseconds",
                "active_binding_cid", "terminal_receipt_cid", "all_trees_fenced")}}
    receipt["native_fence_proof"]["master_start_time_ticks"] = 1
    receipt_path = attempt / "receipt.json"; write(receipt_path, receipt)
    allocation = {"schema": "legal-ir-ordinary-provider-daemon-allocation@1", "endpoint": orphan.ENDPOINT,
        "temporary_root": str(provider), "daemon_id": "12345678-1234-1234-1234-123456789abc"}
    allocation_path = attempt / "provider-docker-allocation.json"; write(allocation_path, allocation)
    name = "ipfs-accelerate-grok-" + str(child_pid) + "-" + "f" * 32
    binding = {"provider": "grok", "container_name": name,
        "lease_root": str(provider / "asref-grok-container-authored"), "watchdog_pid": watchdog_pid,
        "watchdog_start_time_ticks": 2, "creator_pid": child_pid, "endpoint": orphan.ENDPOINT,
        "daemon_id": allocation["daemon_id"]}
    observations = {"schema": "legal-ir-owned-ordinary-provider-cleanup-observations@1",
        "observation_only": True, "bindings": [binding], "unresolved": "ProcessLookupError"}
    observations_path = attempt / "provider-docker-observations.json"; write(observations_path, observations)
    charges = {hashlib.sha256(value["path"].encode()).hexdigest(): value["bytes"] for value in request["external_charges"]}
    record = {"reservation_id": reservation_id, "status": "active", "owner_pid": owner_pid,
        "storage_bytes": request["storage_bytes"], "cpu_slots": 1, "memory_mb": 128,
        "child_process_slots": 2, "scheduler_lane": "orchestration", "workload": "canonical_parented_phase",
        "attempt_directory": orphan.resources._root_identity(attempt), "external_charges": charges,
        "child": {"pid": child_pid, "birth": "1"}, "prior_children": [],
        "native_lease_id": native_id, "parent_lease_id": phase_id, "created_at": 1,
        "artifacts_durable_asserted": False,
        "scheduler_state_path": str(tmp_path / "not-opened-authoritative-double.json"),
        "scheduler_policy_sha256": "1" * 64}
    foreign_id = "e" * 32
    foreign_attempt = roots[2] / "foreign-attempt"; foreign_attempt.mkdir()
    (foreign_attempt / "failure.json").write_bytes(b'{"retained":"foreign evidence"}\n')
    foreign = copy.deepcopy(record)
    foreign.update(reservation_id=foreign_id, status="retained", owner_pid=99_999_999,
        storage_bytes=100_000, external_charges={}, retention_reason="foreign evidence",
        attempt_directory=orphan.resources._root_identity(foreign_attempt), child=None, prior_children=[],
        native_lease_id="f" * 32, parent_lease_id="0" * 32)
    ledger = tmp_path / "disk.json"
    write(ledger, {"schema": orphan.resources.SCHEMA, "roots": [orphan.resources._root_identity(root) for root in roots],
        "limit_bytes": orphan.resources.MAX_STORAGE_BYTES, "reservations": {reservation_id: record, foreign_id: foreign}})
    class Facade:
        active = []
        def active_leases(self):
            return copy.deepcopy(self.active)
    facade = Facade()
    monkeypatch.setattr(orphan, "open_existing_scheduler", lambda *args: facade)
    probes = []
    def probe(*arguments):
        probes.append(arguments)
        return allocation["daemon_id"] if arguments[0] == "info" else None
    monkeypatch.setattr(orphan, "_docker_probe", probe)
    args = {"roots": roots, "reservation_id": reservation_id, "expected_owner_pid": owner_pid,
        "expected_record_sha256": base._digest(record), "attempt_directory": attempt,
        "scheduler_state_path": tmp_path / "not-opened-authoritative-double.json",
        "expected_scheduler_policy_sha256": "1" * 64, "artifacts_durable": True,
        "runtime_proof": {"inert_residual_lease_directories": []}}
    def refresh():
        args["original_request_pin"] = pin(request_path)
        args["original_owner_receipt_pin"] = pin(receipt_path)
        args["runtime_proof"].update(native_terminal_pin=pin(terminal_path),
            provider_allocation_pin=pin(allocation_path), provider_observations_pin=pin(observations_path))
        args["expected_artifacts"] = base._durable_inventory(attempt)
        args["external_dispositions"] = [orphan.snapshot_named_root_external_directory(path, roots=roots)
                                           for path in (repo, provider)]
    refresh()
    return locals()


def test_selected_inspection_exposes_only_owned_dead_active_claim(case):
    before = case["ledger"].read_bytes()
    value = orphan.inspect_selected_orphan_reservation(case["ledger"], roots=case["roots"],
        reservation_id=case["reservation_id"], expected_owner_pid=case["owner_pid"], attempt_directory=case["attempt"])
    assert value["original_status"] == "active"
    assert value["record_sha256"] == case["args"]["expected_record_sha256"]
    assert value["expected_artifacts"] == case["args"]["expected_artifacts"]
    assert case["foreign_id"] not in json.dumps(value)
    assert case["ledger"].read_bytes() == before


def test_dead_active_closeout_preserves_failure_foreign_claim_cap_and_outputs(case):
    before = json.loads(case["ledger"].read_bytes())
    failed_receipt = case["receipt_path"].read_bytes()
    result = orphan.reconcile_dead_active_external_reservation(case["ledger"], **case["args"])
    after = json.loads(case["ledger"].read_bytes())
    selected = after["reservations"][case["reservation_id"]]
    assert selected["status"] == "released"
    assert selected["external_charges"] == case["charges"]
    assert result["original_status"] == "active" and result["historical_retained_transition_synthesized"] is False
    assert result["runtime_fences"]["historical_observer_unresolved"] == "ProcessLookupError"
    assert result["runtime_fences"]["historical_observer_error_cleared"] is False
    assert after["reservations"][case["foreign_id"]] == before["reservations"][case["foreign_id"]]
    assert after["roots"] == before["roots"] and after["limit_bytes"] == before["limit_bytes"]
    assert case["receipt_path"].read_bytes() == failed_receipt
    assert base._durable_inventory(case["attempt"]) == case["args"]["expected_artifacts"]
    assert (case["repo"] / "alias").is_symlink()
    assert result["fresh_global_inventory_count"] == 2 and result["atomic_ledger_write_count"] == 1
    assert all(result[field] is False for field in ("new_reservation_created", "new_resource_lease_acquired",
               "cap_changed", "outputs_deleted", "admitted", "productive_custody_transferred"))
    assert len(case["probes"]) >= 6


@pytest.mark.parametrize("fault", ["live_owner", "wrong_record_hash", "wrong_charge", "missing_fence",
                                    "active_native_lease", "container_exists", "live_watchdog", "wrong_request_pin"])
def test_unsafe_or_unbound_closeout_refuses_without_any_ledger_write(case, monkeypatch, fault):
    args = case["args"]
    if fault == "live_owner":
        ledger = json.loads(case["ledger"].read_bytes())
        row = ledger["reservations"][case["reservation_id"]]; row["owner_pid"] = os.getpid()
        write(case["ledger"], ledger)
        args.update(expected_owner_pid=os.getpid(), expected_record_sha256=base._digest(row))
    elif fault == "wrong_record_hash":
        args["expected_record_sha256"] = "0" * 64
    elif fault == "wrong_charge":
        case["request"]["external_charges"][0]["bytes"] += 1
        write(case["request_path"], case["request"])
        case["receipt"]["request_sha256"] = pin(case["request_path"])["sha256"]
        write(case["receipt_path"], case["receipt"]); case["refresh"]()
    elif fault == "missing_fence":
        del args["runtime_proof"]["native_terminal_pin"]
    elif fault == "active_native_lease":
        case["facade"].active = [{"lease_id": case["native_id"]}]
    elif fault == "container_exists":
        monkeypatch.setattr(orphan, "_docker_probe", lambda *a: case["allocation"]["daemon_id"] if a[0] == "info" else "container-exists")
    elif fault == "live_watchdog":
        case["binding"].update(watchdog_pid=os.getpid(), watchdog_start_time_ticks=int(orphan.resources._process(os.getpid())["birth"]))
        write(case["observations_path"], case["observations"]); case["refresh"]()
    else:
        args["original_request_pin"]["sha256"] = "0" * 64
    before = case["ledger"].read_bytes()
    with pytest.raises(orphan.resources.DaemonResourceError):
        orphan.reconcile_dead_active_external_reservation(case["ledger"], **args)
    assert case["ledger"].read_bytes() == before


@pytest.mark.parametrize("census_number", [1, 2])
@pytest.mark.parametrize("fault", ["external_changed", "foreign_changed", "packet_changed", "owner_reappears"])
def test_census_boundary_mutations_refuse_before_atomic_write(case, monkeypatch, census_number, fault):
    original = base._administrative_census
    calls = [0]
    def census(helper, ledger):
        value = original(helper, ledger)
        calls[0] += 1
        if calls[0] == census_number:
            if fault == "external_changed":
                (case["repo"] / "source.py").write_bytes(b"changed external source\n")
            elif fault == "foreign_changed":
                ledger["reservations"][case["foreign_id"]]["retention_reason"] = "changed foreign claim"
            elif fault == "packet_changed":
                case["args"]["runtime_proof"]["inert_residual_lease_directories"].append({"substituted": True})
            else:
                previous = orphan.resources._process
                monkeypatch.setattr(orphan.resources, "_process", lambda pid:
                    {"pid": pid, "birth": "changed", "state": "S"} if pid == case["owner_pid"] else previous(pid))
        return value
    monkeypatch.setattr(base, "_administrative_census", census)
    before = case["ledger"].read_bytes()
    with pytest.raises(orphan.resources.DaemonResourceError):
        orphan.reconcile_dead_active_external_reservation(case["ledger"], **case["args"])
    assert case["ledger"].read_bytes() == before


def test_inert_readonly_launcher_residue_can_be_preserved_but_capability_files_refuse(case):
    root = Path(case["binding"]["lease_root"]); (root / "task-launchers").mkdir(parents=True)
    root.chmod(0o700); (root / "task-launchers").chmod(0o700)
    for name in ("provider-command-env", "task-bootstrap.py"):
        path = root / "task-launchers" / name; path.write_bytes(b"# authored inert launcher\n"); path.chmod(0o500)
    residue = orphan.snapshot_inert_launcher_residue(root, roots=case["roots"])
    case["args"]["runtime_proof"]["inert_residual_lease_directories"] = [residue]
    case["refresh"]()
    result = orphan.reconcile_dead_active_external_reservation(case["ledger"], **case["args"])
    assert result["runtime_fences"]["inert_residual_directory_count"] == 1
    assert root.is_dir() and len(list((root / "task-launchers").iterdir())) == 2


def test_residual_capability_file_is_not_reclassified_as_inert(case):
    root = Path(case["binding"]["lease_root"]); root.mkdir(mode=0o700)
    (root / "container.cid").write_bytes(b"authored possible live capability")
    case["args"]["runtime_proof"]["inert_residual_lease_directories"] = [{
        "path": str(root), "directory_identity": orphan._directory_identity(root), "artifacts": base._durable_inventory(root)}]
    case["refresh"]()
    before = case["ledger"].read_bytes()
    with pytest.raises(orphan.resources.DaemonResourceError, match="unsupported capability"):
        orphan.reconcile_dead_active_external_reservation(case["ledger"], **case["args"])
    assert case["ledger"].read_bytes() == before and (root / "container.cid").is_file()


@pytest.mark.parametrize("surprise", ["auth.json", "config.json", "provider-payload.bin"])
def test_unexpected_residual_body_is_refused_before_any_body_reader(case, monkeypatch, surprise):
    root = Path(case["binding"]["lease_root"]); root.mkdir(mode=0o700)
    (root / "task-launchers").mkdir(mode=0o700)
    for name in ("provider-command-env", "task-bootstrap.py"):
        path = root / "task-launchers" / name; path.write_bytes(b"# inert authored launcher\n"); path.chmod(0o500)
    (root / surprise).write_bytes(b"do not open this authored surprise body")
    opened = []
    previous_path_open, previous_os_open = Path.open, orphan.os.open
    def no_path_body(path, *args, **kwargs):
        if root in path.parents:
            opened.append(str(path)); raise AssertionError("unexpected residual body reader reached")
        return previous_path_open(path, *args, **kwargs)
    def no_descriptor_body(path, flags, *args, **kwargs):
        if not flags & os.O_DIRECTORY:
            opened.append(str(path)); raise AssertionError("body descriptor opened before shape validation")
        return previous_os_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(Path, "open", no_path_body)
    monkeypatch.setattr(orphan.os, "open", no_descriptor_body)
    with pytest.raises(orphan.resources.DaemonResourceError, match="unsupported capability"):
        orphan.snapshot_inert_launcher_residue(root, roots=case["roots"])
    assert opened == []


@pytest.mark.parametrize("fault", ["bad_cid", "unfenced", "different_generation"])
def test_native_terminal_is_revalidated_not_accepted_as_a_boolean(case, fault):
    terminal = case["terminal"]
    if fault == "bad_cid":
        terminal["terminal_receipt_cid"] = "b-invalid-authored-cid"
    else:
        terminal["all_trees_fenced" if fault == "unfenced" else "run_started_at_epoch_nanoseconds"] = False if fault == "unfenced" else 101
        body = {key: value for key, value in terminal.items() if key != "terminal_receipt_cid"}
        terminal["terminal_receipt_cid"] = orphan._cid(body)
    write(case["terminal_path"], terminal); case["refresh"]()
    before = case["ledger"].read_bytes()
    with pytest.raises(orphan.resources.DaemonResourceError, match="native"):
        orphan.reconcile_dead_active_external_reservation(case["ledger"], **case["args"])
    assert case["ledger"].read_bytes() == before


def test_external_snapshot_never_opens_file_bodies_or_follows_links(case, monkeypatch):
    original_open = Path.open
    def deny_body_open(path, *args, **kwargs):
        if path == case["repo"] or case["repo"] in path.parents:
            raise AssertionError("external file bodies must not be opened")
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", deny_body_open)
    snapshot = orphan.snapshot_named_root_external_directory(case["repo"], roots=case["roots"])
    assert snapshot == case["args"]["external_dispositions"][0]
    assert snapshot["kind_counts"]["symlink"] == 1
    assert "entries" not in snapshot and len(snapshot["entries_sha256"]) == 64


def verify_postwrite(case, result):
    return orphan.verify_selected_orphan_closeout(case["ledger"], roots=case["roots"],
        reservation_id=case["reservation_id"], attempt_directory=case["attempt"],
        expected_reconciliation=result, scheduler_state_path=case["args"]["scheduler_state_path"],
        expected_scheduler_policy_sha256=case["args"]["expected_scheduler_policy_sha256"])


def test_public_postwrite_verification_censuses_actual_released_state(case):
    result = orphan.reconcile_dead_active_external_reservation(case["ledger"], **case["args"])
    before = case["ledger"].read_bytes()
    actual = verify_postwrite(case, result)
    assert actual["selected_status"] == "released"
    assert actual["actual_postwrite_census_complete"] is True
    assert actual["accounting_is_prewrite_projection"] is False
    assert actual["actual_accounting"]["outstanding_full_reservations_bytes"] == case["foreign"]["storage_bytes"]
    assert actual["matches_closeout_foreign_snapshot"] is True
    assert actual["original_artifacts_preserved"] is True
    assert actual["ledger_written"] is actual["new_resource_lease_acquired"] is actual["admitted"] is False
    assert case["ledger"].read_bytes() == before


@pytest.mark.parametrize("fault", ["wrong_public_result", "selected_record_changed", "untouched_field_changed", "artifacts_changed", "native_lease_active"])
def test_public_postwrite_verification_refuses_tampering_or_live_custody(case, fault):
    result = orphan.reconcile_dead_active_external_reservation(case["ledger"], **case["args"])
    if fault == "wrong_public_result":
        result["previous_record_sha256"] = "0" * 64
    elif fault in {"selected_record_changed", "untouched_field_changed"}:
        ledger = json.loads(case["ledger"].read_bytes())
        field, value = ("status", "active") if fault == "selected_record_changed" else ("cpu_slots", 99)
        ledger["reservations"][case["reservation_id"]][field] = value
        write(case["ledger"], ledger)
    elif fault == "artifacts_changed":
        (case["attempt"] / "new-unsupported-output.json").write_bytes(b"{}")
    else:
        case["facade"].active = [{"lease_id": case["native_id"]}]
    before = case["ledger"].read_bytes()
    with pytest.raises(orphan.resources.DaemonResourceError):
        verify_postwrite(case, result)
    assert case["ledger"].read_bytes() == before


def test_public_postwrite_observation_reports_concurrent_foreign_progress(case):
    result = orphan.reconcile_dead_active_external_reservation(case["ledger"], **case["args"])
    ledger = json.loads(case["ledger"].read_bytes())
    ledger["reservations"][case["foreign_id"]]["retention_reason"] = "legitimate later foreign progress"
    write(case["ledger"], ledger)
    before = case["ledger"].read_bytes()
    actual = verify_postwrite(case, result)
    assert actual["matches_closeout_foreign_snapshot"] is False
    assert actual["actual_postwrite_census_complete"] is True
    assert case["ledger"].read_bytes() == before
