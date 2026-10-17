"""Real private file/ledger fixtures; no native admission or original resources.

All records and small byte allowances are expressly inert test data. Actual
local PID observations test refusal; no process is spawned or signalled.
Scoped filesystem failure injection checks actual pre/post-replace readback
and final receipt-byte capacity boundaries. No project source is replaced.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_external_artifact_recovery as api
r, old = api.resources, api.legacy


def pin(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def inventory(path):
    return [{"path": str(item.relative_to(path)), "bytes": item.stat().st_size,
             "sha256": hashlib.sha256(item.read_bytes()).hexdigest()}
            for item in sorted(path.rglob("*")) if item.is_file()]


@pytest.fixture
def fixture(tmp_path):
    attempt, external = tmp_path / "attempt", tmp_path / "external"
    attempt.mkdir(); external.mkdir()
    (attempt / "result.json").write_text('{"fixture_only":true}')
    (external / "fixture-data.txt").write_bytes(b"retained private fixture bytes")
    request = attempt / "execution-request.json"
    request.write_text(json.dumps({"disk_reservation_id": "inert-selected",
        "external_precharge": {"root": str(external), "bytes": 128}}))
    helper = r.DaemonResourceReservation(tmp_path / "ledger.json", roots=[tmp_path],
        storage_bytes=1, memory_mb=1)
    dead_pid = int(Path("/proc/sys/kernel/pid_max").read_text()) + 1
    assert r._process(dead_pid) is None
    row = {"reservation_id": "inert-selected", "status": "retained", "owner_pid": dead_pid,
        "storage_bytes": 4096, "child": None, "prior_children": [],
        "attempt_directory": r._root_identity(attempt), "external_charges": {"inert-external": 128},
        "artifacts_durable_asserted": False, "retention_reason": "explicit_release_required"}
    other = {"reservation_id": "inert-other", "status": "retained", "owner_pid": dead_pid,
        "storage_bytes": 512, "external_charges": {}}
    ledger = {"schema": r.SCHEMA, "roots": helper.root_identities, "limit_bytes": r.MAX_STORAGE_BYTES,
              "reservations": {"inert-selected": row, "inert-other": other}}
    helper._write(ledger)
    args = {"roots": [tmp_path], "reservation_id": "inert-selected",
        "expected_record_sha256": old._digest(row), "attempt_directory": attempt,
        "expected_artifacts": inventory(attempt), "artifacts_durable": True,
        "external_evidence": {"charge_key": "inert-external", "charged_bytes": 128,
            "root_identity": r._root_identity(external), "execution_request_pin": pin(request),
            "expected_artifacts": inventory(external), "artifacts_durable": True}}
    return helper, ledger, args, attempt, external


def rewrite(fixture, mutate):
    helper, ledger, args, *_ = fixture
    mutate(ledger["reservations"]["inert-selected"])
    helper._write(ledger)
    args["expected_record_sha256"] = old._digest(ledger["reservations"]["inert-selected"])


def refuse_without_ledger_change(fixture, **overrides):
    helper, _, args, *_ = fixture
    before = helper.ledger_path.read_bytes()
    with pytest.raises(r.DaemonResourceError):
        api.reconcile_retained_external_reservation(helper.ledger_path, **{**args, **overrides})
    assert helper.ledger_path.read_bytes() == before


def test_release_keeps_outputs_charge_history_and_other_records_with_actual_readback(fixture):
    helper, ledger, args, attempt, external = fixture
    artifacts_before = (inventory(attempt), inventory(external))
    report = api.reconcile_retained_external_reservation(helper.ledger_path, **args)
    actual = helper._read()
    row = actual["reservations"]["inert-selected"]
    assert row["status"] == "released" and row["artifacts_durable_asserted"] is True
    assert row["external_charges"] == {"inert-external": 128}
    assert row["final_external_charged_bytes"] == 128
    assert actual["reservations"]["inert-other"] == ledger["reservations"]["inert-other"]
    assert (inventory(attempt), inventory(external)) == artifacts_before
    assert report["actual_postwrite_census_verified"] is True
    assert report["postwrite_verification_pending"] is False
    assert report["full_claim_accounting"]["outstanding_full_reservations_bytes"] == 4608
    assert report["actual_postwrite_accounting"]["outstanding_full_reservations_bytes"] == 512
    assert report["final_nonpersisted_census_verified"] is True
    assert report["final_nonpersisted_accounting"]["outstanding_full_reservations_bytes"] == 512
    assert report["final_nonpersisted_selected_record_sha256"] == old._digest(row)
    assert report["final_nonpersisted_evidence_in_ledger"] is False
    assert "final_nonpersisted_census_verified" not in row["explicit_external_reconciliation"]
    assert report["outputs_deleted"] is report["admitted"] is report["cap_changed"] is False


def test_legacy_api_still_refuses_external_charges(fixture):
    helper, _, args, *_ = fixture
    before = helper.ledger_path.read_bytes()
    with pytest.raises(r.DaemonResourceError, match="external charges require separate recovery"):
        old.reconcile_retained_reservation(helper.ledger_path,
            **{key: value for key, value in args.items() if key != "external_evidence"})
    assert helper.ledger_path.read_bytes() == before


def test_stale_selected_record_refuses(fixture):
    refuse_without_ledger_change(fixture, expected_record_sha256="0" * 64)


@pytest.mark.parametrize("old_birth", [None, "an-explicitly-stale-owner-birth"])
def test_current_or_reused_owner_pid_refuses_using_real_process_observation(fixture, old_birth):
    def mutate(row):
        row["owner_pid"] = os.getpid()
        if old_birth is not None:
            row["owner_birth"] = old_birth
    rewrite(fixture, mutate)
    refuse_without_ledger_change(fixture)


@pytest.mark.parametrize("prior", [False, True])
def test_live_recorded_child_group_refuses_without_spawning_any_process(fixture, prior):
    leader = r._process(os.getpgrp())
    assert leader is not None
    child = {"pid": leader["pid"], "birth": leader["birth"]}
    rewrite(fixture, lambda row: row.update(prior_children=[child]) if prior else row.update(child=child))
    refuse_without_ledger_change(fixture)


def test_reused_child_pid_birth_refuses(fixture):
    rewrite(fixture, lambda row: row.update(child={"pid": os.getpid(), "birth": "wrong-birth"}))
    refuse_without_ledger_change(fixture)


@pytest.mark.parametrize("which", ["attempt", "external"])
def test_changed_same_size_file_contents_refuse(fixture, which):
    _, _, _, attempt, external = fixture
    path = attempt / "result.json" if which == "attempt" else external / "fixture-data.txt"
    path.write_bytes(b"x" * path.stat().st_size)
    refuse_without_ledger_change(fixture)


@pytest.mark.parametrize("which,kind", [(a, b) for a in ("attempt", "external") for b in ("symlink", "hardlink")])
def test_unaliased_regular_file_inventory_is_required(fixture, which, kind):
    _, _, _, attempt, external = fixture
    tree = attempt if which == "attempt" else external
    target = tree / ("result.json" if which == "attempt" else "fixture-data.txt")
    if kind == "symlink":
        (tree / "unexpected-link").symlink_to(target)
    else:
        os.link(target, tree / "unexpected-link")
    refuse_without_ledger_change(fixture)


@pytest.mark.parametrize("field,value", [("charge_key", "another-charge"), ("charged_bytes", 127),
    ("artifacts_durable", False), ("unexpected", "field")])
def test_external_closed_evidence_drift_refuses(fixture, field, value):
    evidence = deepcopy(fixture[2]["external_evidence"])
    evidence[field] = value
    refuse_without_ledger_change(fixture, external_evidence=evidence)


def test_extra_recorded_external_charge_refuses(fixture):
    rewrite(fixture, lambda row: row["external_charges"].update({"unexplained-charge": 1}))
    refuse_without_ledger_change(fixture)


def test_external_root_identity_drift_refuses(fixture):
    evidence = deepcopy(fixture[2]["external_evidence"])
    evidence["root_identity"]["inode"] += 1
    refuse_without_ledger_change(fixture, external_evidence=evidence)


def test_execution_request_selector_drift_refuses(fixture):
    _, _, args, attempt, _ = fixture
    request = attempt / "execution-request.json"
    value = json.loads(request.read_text()); value["disk_reservation_id"] = "another-claim"
    request.write_text(json.dumps(value))
    evidence = deepcopy(args["external_evidence"]); evidence["execution_request_pin"] = pin(request)
    refuse_without_ledger_change(fixture, external_evidence=evidence,
                                expected_artifacts=inventory(attempt))


def test_external_actual_bytes_over_allowance_refuse(fixture):
    _, _, args, _, external = fixture
    (external / "fixture-data.txt").write_bytes(b"x" * 129)
    evidence = deepcopy(args["external_evidence"]); evidence["expected_artifacts"] = inventory(external)
    refuse_without_ledger_change(fixture, external_evidence=evidence)


def test_attempt_plus_external_allowance_must_fit_original_reservation(fixture):
    rewrite(fixture, lambda row: row.update(storage_bytes=128))
    refuse_without_ledger_change(fixture)


def test_attempt_durability_is_explicit(fixture):
    refuse_without_ledger_change(fixture, artifacts_durable=False)


def test_postwrite_census_failure_keeps_a_durable_pending_release(fixture, monkeypatch):
    helper, ledger, args, *_ = fixture
    original = old._administrative_census
    def fail_after_release(helper_arg, value):
        selected = value["reservations"]["inert-selected"]
        if selected.get("explicit_external_reconciliation") is not None:
            raise r.DaemonResourceError("injected postwrite census failure")
        return original(helper_arg, value)
    monkeypatch.setattr(old, "_administrative_census", fail_after_release)
    with pytest.raises(api.ExternalRecoveryPostwritePending) as raised:
        api.reconcile_retained_external_reservation(helper.ledger_path, **args)
    assert raised.value.claim_released is True
    actual = helper._read()
    selected = actual["reservations"]["inert-selected"]
    assert selected["status"] == "released"
    assert selected["external_charges"] == {"inert-external": 128}
    assert selected["explicit_external_reconciliation"]["postwrite_verification_pending"] is True
    assert selected["explicit_external_reconciliation"]["actual_postwrite_census_verified"] is False
    assert actual["reservations"]["inert-other"] == ledger["reservations"]["inert-other"]


@pytest.mark.parametrize("policy", ["require_capacity", "administrative_closeout"])
def test_real_fixture_ledger_overage_is_refused_or_explicitly_recorded(fixture, policy):
    helper, ledger, args, *_ = fixture
    # This is an inert local fixture record, never an allocation or native grant.
    ledger["reservations"]["inert-other"]["storage_bytes"] = r.MAX_STORAGE_BYTES
    helper._write(ledger)
    if policy == "require_capacity":
        refuse_without_ledger_change(fixture, capacity_policy=policy)
    else:
        report = api.reconcile_retained_external_reservation(helper.ledger_path,
            **args, capacity_policy=policy)
        assert report["full_claim_accounting"]["over_limit_bytes"] > 0
        assert report["actual_postwrite_accounting"]["capacity_satisfied"] is False
        assert report["actual_postwrite_census_verified"] is True
        assert report["admitted"] is report["cap_changed"] is False
        actual = helper._read()
        assert actual["limit_bytes"] == r.MAX_STORAGE_BYTES
        assert actual["reservations"]["inert-other"] == ledger["reservations"]["inert-other"]


@pytest.mark.parametrize("which", ["overlap", "outside_roots"])
def test_external_tree_cannot_overlap_attempt_or_escape_named_roots(fixture, tmp_path_factory, which):
    _, _, args, attempt, _ = fixture
    path = attempt if which == "overlap" else tmp_path_factory.mktemp("inert-outside-recovery-root")
    evidence = deepcopy(args["external_evidence"])
    evidence["root_identity"] = r._root_identity(path)
    refuse_without_ledger_change(fixture, external_evidence=evidence)


@pytest.mark.parametrize("write_number", [1, 2])
@pytest.mark.parametrize("fault", ["before_replace", "after_replace", "unreadable_after_replace"])
def test_actual_scoped_filesystem_write_failure_has_explicit_readback_disposition(
        fixture, monkeypatch, write_number, fault):
    helper, ledger, args, *_ = fixture
    before = helper.ledger_path.read_bytes()
    parent = helper.ledger_path.parent
    parent_identity = (parent.stat().st_dev, parent.stat().st_ino)
    saved_fsync = os.fsync
    seen = {"temp": 0, "directory": 0, "injected": False}
    backup = parent / "inert-ledger-retained-backup.json"

    def scoped_fault(descriptor):
        info = os.fstat(descriptor)
        is_parent = stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == parent_identity
        is_temporary = False
        if stat.S_ISREG(info.st_mode):
            target = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
            is_temporary = target.parent == parent and target.name.startswith(".daemon-reservation-")
        kind = "directory" if is_parent else "temp" if is_temporary else None
        if kind is not None:
            seen[kind] += 1
        inject = (not seen["injected"] and
            ((fault == "before_replace" and is_temporary and seen["temp"] == write_number)
             or (fault != "before_replace" and is_parent and seen["directory"] == write_number)))
        if inject:
            seen["injected"] = True
            if fault == "unreadable_after_replace":
                # Preserve every written byte under a private backup pathname;
                # missing original readback must not imply either disposition.
                os.rename(helper.ledger_path, backup)
            raise OSError(5, "inert private fixture fsync fault")
        return saved_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", scoped_fault)
    error_class = api.ExternalRecoveryWriteIncomplete if write_number == 1 else api.ExternalRecoveryPostwritePending
    with pytest.raises(error_class) as caught:
        api.reconcile_retained_external_reservation(helper.ledger_path, **args)
    error = caught.value
    assert seen["injected"] is True
    assert error.stage == ("initial_release_write" if write_number == 1 else "receipt_write")
    assert error.initial_release_write_completed is (write_number == 2)
    assert error.receipt_write_completed is False
    assert error.postwrite_verification_pending is True
    assert error.automatic_retry_permitted is error.rollback_claimed is False
    if fault == "unreadable_after_replace":
        assert error.observed_disposition == "unknown" and error.claim_released is None
        assert error.observation["readback_succeeded"] is False
        assert error.observed_record_durability_verified is False
        assert not helper.ledger_path.exists() and backup.is_file()
        visible = json.loads(backup.read_bytes())
        assert visible["reservations"]["inert-selected"]["status"] == "released"
    elif write_number == 1 and fault == "before_replace":
        assert error.observed_disposition == "retained_preimage_observed"
        assert error.claim_released is error.observed_record_durability_verified is False
        assert helper.ledger_path.read_bytes() == before
        visible = helper._read()
    else:
        pending = write_number == 1 or fault == "before_replace"
        assert error.observed_disposition == ("released_pending_observed" if pending else "released_receipt_observed")
        assert error.claim_released is True
        assert error.ledger_postwrite_verification_pending is pending
        assert error.ledger_actual_postwrite_census_verified is (not pending)
        assert error.observed_record_durability_verified is (write_number == 2 and pending)
        visible = helper._read()
        assert visible["reservations"]["inert-selected"]["status"] == "released"
    assert visible["reservations"]["inert-other"] == ledger["reservations"]["inert-other"]


def test_final_nonpersisted_census_refuses_actual_growth_after_receipt_persistence(fixture, monkeypatch):
    helper, ledger, args, *_ = fixture
    # Only inert byte claims change: no allocation, global quota edit or large
    # files. The original full claim fits before writing the recovery receipt.
    rewrite(fixture, lambda row: row.update(storage_bytes=32768))
    ledger["reservations"]["inert-other"]["storage_bytes"] = r.MAX_STORAGE_BYTES - 65536
    helper._write(ledger)
    parent = helper.ledger_path.parent
    parent_identity = (parent.stat().st_dev, parent.stat().st_ino)
    saved_fsync = os.fsync
    writes = []
    growth = parent / "inert-post-receipt-growth.bin"

    def add_after_receipt(descriptor):
        result = saved_fsync(descriptor)
        info = os.fstat(descriptor)
        if stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == parent_identity:
            writes.append(True)
            if len(writes) == 2:
                growth.write_bytes(b"x" * 81920)
        return result

    monkeypatch.setattr(os, "fsync", add_after_receipt)
    with pytest.raises(api.ExternalRecoveryPostwritePending) as caught:
        api.reconcile_retained_external_reservation(helper.ledger_path, **args)
    error = caught.value
    assert len(writes) == 2 and growth.stat().st_size == 81920
    assert error.stage == "final_nonpersisted_census_readback"
    assert error.claim_released is True and error.observed_disposition == "released_receipt_observed"
    assert error.receipt_write_completed is error.observed_record_durability_verified is True
    assert error.postwrite_verification_pending is True
    assert error.ledger_postwrite_verification_pending is False
    actual = helper._read()
    marker = actual["reservations"]["inert-selected"]["explicit_external_reconciliation"]
    assert marker["actual_postwrite_accounting"]["capacity_satisfied"] is True
    assert old._administrative_census(helper, actual)["capacity_satisfied"] is False
    assert actual["reservations"]["inert-other"] == ledger["reservations"]["inert-other"]
