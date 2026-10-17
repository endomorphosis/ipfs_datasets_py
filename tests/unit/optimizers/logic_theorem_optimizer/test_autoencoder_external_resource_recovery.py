"""Administrative batch controls using only test-local scheduler/files/ledger."""
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_external_resource_recovery as external
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_daemon_resources import setup


def pin(path):
    raw = path.read_bytes()
    return {"path":str(path),"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}


def prepare(setup, *, mode="same_declared_inputs", retained_directory=False):
    factory, roots, ledger, _ = setup
    if len(roots) == 2:
        for name in ("third", "fourth"):
            root = roots[0].parent / name
            root.mkdir(); roots.append(root)
    attempt = roots[0] / ("attempt-" + str(len(list(roots[0].iterdir())))); attempt.mkdir()
    fixture = roots[1] / ("fixtures-" + attempt.name)
    if retained_directory:
        fixture.mkdir(); (fixture / "kept.bin").write_bytes(b"retained fixture bytes")
    cohort = [{"path":"/authored/test_source.py","bytes":7,"sha256":"1" * 64}]
    audit = {"schema":"authored-audit/v1","external_fixture_charge":{"key":"pytest-fixtures","bytes":6000},
             "test_artifacts":cohort}
    tests = {"schema":"authored-tests/v1","fixture_directory":str(fixture),
             "fixtures_outside_strict_attempt":True,"test_artifacts":cohort}
    if mode == "same_receipt":
        audit["fixture_directory"] = str(fixture)
    audit_path = attempt / "audit.json"; audit_path.write_text(json.dumps(audit))
    tests_path = attempt / "tests.json"; tests_path.write_text(json.dumps(tests))
    if mode == "direct_receipt_pin":
        audit["tests_receipt"] = pin(tests_path); audit_path.write_text(json.dumps(audit))
    with factory() as owner:
        owner.check_usage(attempt)
        owner.account_external_bytes("pytest-fixtures", 6000)
    data = json.loads(ledger.read_bytes()); row = data["reservations"][owner.reservation_id]
    row["owner_pid"] = 99999999
    ledger.write_text(json.dumps(data))
    source_pin = pin(audit_path) if mode == "same_receipt" else pin(tests_path)
    association = ({"mode":mode,"charge_json_pointer":None,"path_json_pointer":None}
        if mode == "same_receipt" else {"mode":mode,"charge_json_pointer":"/tests_receipt","path_json_pointer":None}
        if mode == "direct_receipt_pin" else
        {"mode":mode,"charge_json_pointer":"/test_artifacts","path_json_pointer":"/test_artifacts"})
    entry = {"key":"pytest-fixtures","bytes":6000,"charge_evidence_pin":pin(audit_path),
        "charge_json_pointer":"/external_fixture_charge","path_evidence_pin":source_pin,
        "path_json_pointer":"/fixture_directory","outside_attempt_json_pointer":None if mode == "same_receipt" else "/fixtures_outside_strict_attempt",
        "association":association,"path":str(fixture),
        "disposition":"retained_directory" if retained_directory else "absent_leaf",
        "parent_identity":external._directory_identity(fixture.parent),
        "directory_identity":external._directory_identity(fixture) if retained_directory else None,
        "expected_artifacts":external.base._durable_inventory(fixture) if retained_directory else []}
    disposition = {"schema":external.DISPOSITION_SCHEMA,
        "external_charges_sha256":external.base._digest(row["external_charges"]),"bindings":[entry]}
    claim = {"reservation_id":owner.reservation_id,"expected_record_sha256":external.base._digest(row),
        "attempt_directory":str(attempt),"expected_artifacts":external.base._durable_inventory(attempt),
        "allow_empty_failed_admission":False,"conservative_named_roots_external_disposition":disposition}
    return ledger, roots, claim, fixture, data


@pytest.mark.parametrize("mode", ["same_declared_inputs", "same_receipt", "direct_receipt_pin"])
@pytest.mark.parametrize("retained_directory", [False, True])
def test_explicit_association_closes_only_claim_and_preserves_charge_history(setup, mode, retained_directory):
    ledger, roots, claim, fixture, before = prepare(setup, mode=mode, retained_directory=retained_directory)
    old = before["reservations"][claim["reservation_id"]]
    receipt = external.reconcile_retained_reservations_batch(ledger, roots=roots, claims=[claim], artifacts_durable=True)
    row = json.loads(ledger.read_bytes())["reservations"][claim["reservation_id"]]
    assert row["status"] == "released"
    assert row["external_charges"] == old["external_charges"]
    assert row["last_usage"] == old["last_usage"]
    assert row["final_external_charged_bytes"] == 6000
    assert row["final_total_charged_bytes"] == row["final_attempt_bytes"] + 6000
    assert receipt["claim_count"] == 1 and receipt["fresh_global_inventory_count"] == 2
    assert receipt["actual_postwrite_census_required"] is True
    assert receipt["historical_external_payloads_authenticated"] is False
    assert receipt["cap_changed"] is receipt["admitted"] is receipt["outputs_deleted"] is False
    assert external.base._durable_inventory(Path(claim["attempt_directory"])) == claim["expected_artifacts"]
    assert fixture.exists() is retained_directory


def test_batch_uses_two_censuses_one_atomic_write_and_no_native_admission(setup, monkeypatch):
    ledger, roots, first, _, _ = prepare(setup)
    _, _, second, _, _ = prepare(setup, mode="same_receipt")
    factory, _, _, scheduler = setup
    with factory() as foreign:
        pass
    original = json.loads(ledger.read_bytes()); foreign_body = original["reservations"][foreign.reservation_id]
    census = external.base._administrative_census; write = external.resources.DaemonResourceReservation._write
    counts = {"census":0,"write":0}
    def observe(*args):
        counts["census"] += 1; return census(*args)
    def persist(*args):
        counts["write"] += 1; return write(*args)
    def forbidden(*args, **kwargs):
        raise AssertionError("administrative closeout must acquire no lease")
    monkeypatch.setattr(external.base, "_administrative_census", observe)
    monkeypatch.setattr(external.resources.DaemonResourceReservation, "_write", persist)
    monkeypatch.setattr(scheduler, "acquire", forbidden)
    monkeypatch.setattr(external.resources.DaemonResourceReservation, "__enter__", forbidden)
    receipt = external.reconcile_retained_reservations_batch(ledger, roots=roots, claims=[first,second], artifacts_durable=True)
    after = json.loads(ledger.read_bytes())
    assert counts == {"census":2,"write":1}
    assert receipt["released_promise_bytes"] == 20_000
    assert after["reservations"][foreign.reservation_id] == foreign_body
    assert after["roots"] == original["roots"] and after["limit_bytes"] == original["limit_bytes"]


@pytest.mark.parametrize("fault", ["record", "owner", "group", "attempt", "charge_amount", "unbound_key",
    "receipt", "cohort", "network_guard", "absent_leaf", "parent", "outside_roots", "no_assertion"])
def test_later_bad_claim_refuses_complete_batch_without_any_write(setup, monkeypatch, fault):
    ledger, roots, first, _, _ = prepare(setup)
    _, _, second, fixture, data = prepare(setup)
    row = data["reservations"][second["reservation_id"]]
    binding = second["conservative_named_roots_external_disposition"]["bindings"][0]
    if fault == "record": second["expected_record_sha256"] = "0" * 64
    elif fault == "owner": row["owner_pid"] = os.getpid()
    elif fault == "group":
        row["child"] = {"pid":99999998,"birth":"authored"}
        monkeypatch.setattr(external.resources, "_group_usage", lambda value: {"live_processes":int(value is not None)})
    elif fault == "attempt": (Path(second["attempt_directory"]) / "extra").write_bytes(b"changed")
    elif fault == "charge_amount": binding["bytes"] += 1
    elif fault == "unbound_key": row["external_charges"]["unbound"] = 1
    elif fault == "receipt": binding["path_evidence_pin"]["sha256"] = "0" * 64
    elif fault == "cohort": binding["association"]["path_json_pointer"] = "/missing"
    elif fault == "network_guard":
        binding["association"]["charge_json_pointer"] = "/network_guard"
        binding["association"]["path_json_pointer"] = "/network_guard"
    elif fault == "absent_leaf": fixture.mkdir()
    elif fault == "parent": binding["parent_identity"]["inode"] += 1
    elif fault == "outside_roots": binding["path"] = "/not-a-selected-root/fixture"
    if fault != "record": second["expected_record_sha256"] = external.base._digest(row)
    ledger.write_text(json.dumps(data)); before = ledger.read_bytes()
    with pytest.raises(external.resources.DaemonResourceError):
        external.reconcile_retained_reservations_batch(ledger, roots=roots, claims=[first,second],
            artifacts_durable=fault != "no_assertion")
    assert ledger.read_bytes() == before


@pytest.mark.parametrize("number", [1,2])
@pytest.mark.parametrize("fault", ["external_appears", "selected", "foreign", "request"])
def test_census_callbacks_cannot_change_any_bound_claim_or_external_disposition(setup, monkeypatch, number, fault):
    ledger, roots, claim, fixture, _ = prepare(setup)
    factory, _, _, _ = setup
    with factory() as foreign:
        pass
    census = external.base._administrative_census; count = 0; before = ledger.read_bytes()
    claims = [claim]
    def mutate(helper, state):
        nonlocal count
        result = census(helper, state); count += 1
        if count == number:
            if fault == "external_appears": fixture.mkdir()
            elif fault == "selected": state["reservations"][claim["reservation_id"]]["storage_bytes"] += 1
            elif fault == "foreign": state["reservations"][foreign.reservation_id]["retention_reason"] = "changed"
            else: claims[0]["expected_record_sha256"] = "0" * 64
        return result
    monkeypatch.setattr(external.base, "_administrative_census", mutate)
    with pytest.raises(external.resources.DaemonResourceError):
        external.reconcile_retained_reservations_batch(ledger, roots=roots, claims=claims, artifacts_durable=True)
    assert ledger.read_bytes() == before


def test_old_strict_recovery_still_refuses_the_same_external_charge(setup):
    ledger, roots, claim, _, _ = prepare(setup); before = ledger.read_bytes()
    with pytest.raises(external.resources.DaemonResourceError, match="external charges"):
        external.base.reconcile_retained_reservation(ledger, roots=roots,
            reservation_id=claim["reservation_id"],expected_record_sha256=claim["expected_record_sha256"],
            attempt_directory=claim["attempt_directory"],expected_artifacts=claim["expected_artifacts"],
            artifacts_durable=True,capacity_policy="administrative_closeout")
    assert ledger.read_bytes() == before


@pytest.mark.parametrize("empty", [False, True])
def test_mixed_batch_preserves_original_plain_and_empty_failed_admission_contracts(setup, empty):
    ledger, roots, charged, _, _ = prepare(setup)
    factory, _, _, _ = setup
    attempt = roots[0] / "plain"; attempt.mkdir()
    if not empty:
        (attempt / "failure.json").write_bytes(b'{"failed":true}')
    with factory() as owner:
        owner.check_usage(attempt)
    data = json.loads(ledger.read_bytes()); row = data["reservations"][owner.reservation_id]
    row["owner_pid"] = 99999998
    if empty:
        # Authored administrative fixture of the original closed failed-open
        # record. No claim that a real validation process failed here.
        row.update(retention_reason="scheduler_admission_failed", scheduler_lane="validation",
                   workload="canonical_validation")
    ledger.write_text(json.dumps(data))
    plain = {"reservation_id":owner.reservation_id,"expected_record_sha256":external.base._digest(row),
        "attempt_directory":str(attempt),"expected_artifacts":external.base._durable_inventory(attempt),
        "allow_empty_failed_admission":empty,"conservative_named_roots_external_disposition":None}
    receipt = external.reconcile_retained_reservations_batch(ledger, roots=roots,
        claims=[charged,plain],artifacts_durable=True)
    assert receipt["claim_count"] == 2 and receipt["released_promise_bytes"] == 20000
    current = json.loads(ledger.read_bytes())["reservations"][owner.reservation_id]
    assert current["status"] == "released" and current["final_external_charged_bytes"] == 0
    assert current["external_charges"] == row["external_charges"] == {}


@pytest.mark.parametrize("write_completed", [False, True])
def test_atomic_batch_write_failure_is_never_retried_or_represented_as_rollback(setup, monkeypatch, write_completed):
    ledger, roots, first, _, _ = prepare(setup)
    _, _, second, _, _ = prepare(setup, mode="same_receipt")
    original = external.resources.DaemonResourceReservation._write
    calls = 0; before = ledger.read_bytes()
    def fail(helper, state):
        nonlocal calls
        calls += 1
        if write_completed:
            original(helper, state)
        raise OSError("retained primary atomic write failure")
    monkeypatch.setattr(external.resources.DaemonResourceReservation,"_write",fail)
    with pytest.raises(OSError,match="primary atomic write failure"):
        external.reconcile_retained_reservations_batch(ledger, roots=roots,
            claims=[first,second],artifacts_durable=True)
    assert calls == 1
    if write_completed:
        rows = json.loads(ledger.read_bytes())["reservations"]
        assert rows[first["reservation_id"]]["status"] == rows[second["reservation_id"]]["status"] == "released"
    else:
        assert ledger.read_bytes() == before


@pytest.mark.parametrize("kind", ["symlink", "file"])
def test_absence_proof_refuses_new_alias_or_file_without_touching_outputs(setup, kind):
    ledger, roots, claim, fixture, _ = prepare(setup)
    if kind == "symlink":
        fixture.symlink_to(roots[2],target_is_directory=True)
    else:
        fixture.write_bytes(b"new foreign file")
    before = ledger.read_bytes()
    with pytest.raises(external.resources.DaemonResourceError):
        external.reconcile_retained_reservations_batch(ledger,roots=roots,claims=[claim],artifacts_durable=True)
    assert ledger.read_bytes() == before
    assert fixture.is_symlink() if kind == "symlink" else fixture.read_bytes() == b"new foreign file"
