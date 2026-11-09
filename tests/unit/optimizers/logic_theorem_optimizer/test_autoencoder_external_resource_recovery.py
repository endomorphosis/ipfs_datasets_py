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

# These tests preserve synthetic special entries long enough to prove the
# disposition, then remove ONLY their own fixtures in finally. Qualification
# must use the original registered physical-fixture boundary for these cases.
# Immutable nonsecret canonical policy TEST DATA, authenticated by its exact
# original persisted-policy SHA. Only this private broker's capacity/layout
# fields change below; safety/headroom/stall thresholds and real sampler stay.
_FAILED_FILESYSTEM_QUALIFIED_PROOF_POLICY = {'lane_reservations': {'validation': {'cpu_slots': 2, 'memory_mb': 0}}, 'max_gpu_memory_percent': None, 'max_memory_percent': None, 'max_swap_percent': None, 'max_waiting_requests': 256, 'proof_backoff_seconds': 2.0, 'proof_cpu_stall_percent': 65.0, 'proof_io_stall_percent': 10.0, 'proof_memory_headroom_mb': 24922, 'proof_memory_stall_percent': 2.0, 'proof_recovery_enabled': False, 'proof_recovery_grants': 4, 'proof_recovery_interval_seconds': 0.25, 'proof_recovery_samples': 2, 'proof_resource_profile': None, 'proof_safety_enabled': True, 'require_known_gpu_for_gpu_work': True, 'reserved_gpu_memory_mb': 0, 'reserved_memory_mb': 0, 'total_child_process_slots': 20, 'total_cpu_slots': 16, 'total_gpu_memory_mb': None, 'total_memory_mb': 99688, 'total_unified_memory_mb': None}


def prepare_failed_filesystem(setup):
    factory, roots, ledger, scheduler = setup
    if len(roots) == 2:
        for name in ("third", "fourth"):
            root = roots[0].parent / name
            root.mkdir(); roots.append(root)
    attempt = roots[0] / ("failed-" + str(len(list(roots[0].iterdir())))); attempt.mkdir()
    (attempt / "failure.json").write_bytes(b'{"failed":true,"test_acceptance":false}')
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
        GlobalResourceScheduler, ResourceSchedulerConfig)
    # A fresh genuinely proof-enabled private broker, not a migration or a
    # relaxed inspection guard. The old35 fixtures/defaults remain untouched.
    assert external.base._digest(_FAILED_FILESYSTEM_QUALIFIED_PROOF_POLICY) ==         "4662bd8fe6caf6f2c048e3d7cff7abb4d80e5c875b21e02e204b1b89371b8286"
    private_config = copy.deepcopy(_FAILED_FILESYSTEM_QUALIFIED_PROOF_POLICY)
    private_config.update(total_cpu_slots=4, total_memory_mb=4096,
                          total_child_process_slots=4, lane_reservations={})
    private_scheduler = GlobalResourceScheduler(ResourceSchedulerConfig(
        **private_config, state_path=roots[3] / (attempt.name + ".native.json"),
        auto_renew_leases=False))
    private_policy = external.base._digest(private_scheduler.config.persisted_dict())
    with pytest.raises(RuntimeError, match="synthetic owned failure"):
        with factory(scheduler_state_path=private_scheduler.state_path,
                     expected_scheduler_policy_sha256=private_policy) as owner:
            owner.check_usage(attempt)
            closed_native = owner.to_dict()["resource_lease"]
            raise RuntimeError("synthetic owned failure")
    state = json.loads(ledger.read_bytes()); row = state["reservations"][owner.reservation_id]
    # Explicit historical test projection: original real native lease is closed,
    # original disk claim retained. No claim that this authored PID was a job.
    row.update(owner_pid=99999997, workload="canonical_validation",
        native_lease_id=closed_native["lease_id"], scheduler_state_path=str(private_scheduler.state_path),
        scheduler_policy_sha256="0" * 64)
    ledger.write_text(json.dumps(state))
    claim = {"reservation_id":owner.reservation_id,"expected_record_sha256":external.base._digest(row),
        "attempt_directory":str(attempt),"expected_artifacts":[],"allow_empty_failed_admission":False,
        "conservative_named_roots_external_disposition":None,"failed_filesystem_manifest":None,
        "native_inspection":{"state_path":str(private_scheduler.state_path),
            "policy_sha256":private_policy,
            "request_id":"daemon:" + owner.reservation_id}}
    return ledger, roots, claim, attempt, state


def freeze_failed_filesystem(roots, claim):
    manifest = external.failed_filesystem_manifest(claim["attempt_directory"])
    path = roots[3] / (claim["reservation_id"] + ".manifest.json")
    path.write_bytes(external._wire(manifest))
    claim["failed_filesystem_manifest"] = pin(path)
    return manifest, path


def close_failed_filesystem(ledger, roots, claims):
    return external.reconcile_retained_failed_filesystem_reservations_batch(
        ledger, roots=roots, claims=claims, failed_filesystem_disposition=True)


@pytest.mark.parametrize("kind", ["absolute_symlink", "relative_symlink", "dangling_symlink", "fifo"])
def test_failed_filesystem_preserves_specials_without_opening_payloads(setup, monkeypatch, kind):
    ledger, roots, claim, attempt, before = prepare_failed_filesystem(setup)
    target = roots[2] / "target-must-never-open"; target.write_bytes(b"unrelated bytes")
    special = attempt / "special"
    if kind == "fifo": os.mkfifo(special)
    else: special.symlink_to(str(target) if kind == "absolute_symlink" else
        "../unresolved/../not-a-target" if kind == "relative_symlink" else "/absent/never-follow")
    original_open = external.os.open; original_readlink = external.os.readlink
    target_before = target.read_bytes(); special_before = special.lstat()
    text = os.readlink(special) if kind != "fifo" else None
    def checked_open(path, flags, *args, **kwargs):
        assert os.fspath(path) not in {str(target), str(special), "special"}, "special/target payload opened"
        return original_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(external.os, "open", checked_open)
    try:
        document, manifest_path = freeze_failed_filesystem(roots, claim)
        receipt = close_failed_filesystem(ledger, roots, [claim])
        current = json.loads(ledger.read_bytes())["reservations"][claim["reservation_id"]]
        assert current["status"] == "released" and current["artifacts_durable_asserted"] is False
        assert current["last_usage"] == before["reservations"][claim["reservation_id"]]["last_usage"]
        assert special.lstat().st_ino == special_before.st_ino
        if text is not None: assert original_readlink(special) == text
        assert target.lstat().st_size == len(target_before)
        assert document["targets_followed"] is document["special_payloads_opened"] is False
        assert document["typed_counts"]["fifo" if kind == "fifo" else "symlink"] == 1
        selected = current["explicit_reconciliation"]["selected_claim"]
        assert "artifacts" not in selected and "entries" not in selected
        assert selected["failed_filesystem_disposition"]["manifest"] == pin(manifest_path)
        assert selected["native_absence"]["historical_release_established"] is False
        assert receipt["ordinary_artifact_durability_asserted"] is False
        assert receipt["test_or_task_acceptance_asserted"] is False
        assert receipt["actual_ledger_write_readback_verified"] is True
        assert receipt["actual_postwrite_census_required"] is True
        assert receipt["admitted"] is receipt["cap_changed"] is receipt["outputs_deleted"] is False
    finally:
        special.unlink(missing_ok=True)


def test_failed_filesystem_pressure_closes_only_unused_promise_and_never_admits(setup, monkeypatch):
    from types import SimpleNamespace
    ledger, roots, claim, attempt, before = prepare_failed_filesystem(setup)
    freeze_failed_filesystem(roots, claim)
    old_scheduler = Path(claim["native_inspection"]["state_path"]).read_bytes()
    monkeypatch.setattr(external.resources.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    helper = external.resources.DaemonResourceReservation(ledger, roots=roots,
        storage_bytes=1, memory_mb=1, require_existing_ledger=True)
    with pytest.raises(external.resources.DaemonResourceError, match="capacity"):
        helper._account(before, additional=1)
    receipt = close_failed_filesystem(ledger, roots, [claim])
    assert receipt["capacity_policy"] == "administrative_closeout"
    assert receipt["full_claim_accounting"]["capacity_satisfied"] is False
    assert receipt["full_claim_accounting"]["filesystem_free_shortfall_bytes"] > 0
    assert receipt["final_accounting"]["outstanding_full_reservations_bytes"] == 0
    assert receipt["released_promise_bytes"] == before["reservations"][claim["reservation_id"]]["storage_bytes"]
    assert Path(claim["native_inspection"]["state_path"]).read_bytes() == old_scheduler
    assert receipt["new_resource_lease_acquired"] is receipt["new_reservation_created"] is False


@pytest.mark.parametrize("kind", ["hardlink", "fifo", "symlink"])
def test_original_ordinary_api_still_rejects_special_failed_tree(setup, monkeypatch, kind):
    ledger, roots, claim, attempt, _ = prepare_failed_filesystem(setup)
    special = attempt / "special"
    if kind == "hardlink": os.link(attempt / "failure.json", special)
    elif kind == "fifo": os.mkfifo(special)
    else: special.symlink_to("failure.json")
    old = ledger.read_bytes()
    ordinary = {key:value for key,value in claim.items() if key not in {"native_inspection", "failed_filesystem_manifest"}}
    ordinary_pin = pin(attempt / "failure.json")
    ordinary["expected_artifacts"] = [{"path":"failure.json", "bytes":ordinary_pin["bytes"], "sha256":ordinary_pin["sha256"]}]
    if kind != "fifo":
        ordinary["expected_artifacts"].append({"path":"special", "bytes":ordinary_pin["bytes"], "sha256":ordinary_pin["sha256"]})
    else:
        import io
        original_io_open = io.open; original_os_open = external.os.open
        def safe_io_open(path, *args, **kwargs):
            assert not isinstance(path,(str,bytes,Path)) or os.fsdecode(path) != str(special), "FIFO payload opened"
            return original_io_open(path,*args,**kwargs)
        def safe_os_open(path, *args, **kwargs):
            assert not isinstance(path,(str,bytes,Path)) or os.fsdecode(path) != str(special), "FIFO payload opened"
            return original_os_open(path,*args,**kwargs)
        monkeypatch.setattr(io,"open",safe_io_open); monkeypatch.setattr(external.os,"open",safe_os_open)
    expected_error = {"hardlink":"unaliased regular file", "symlink":"symlink in attempt inventory", "fifo":"nonregular attempt entry"}[kind]
    try:
        with pytest.raises(external.resources.DaemonResourceError, match=expected_error):
            external.reconcile_retained_reservations_batch(ledger, roots=roots, claims=[ordinary], artifacts_durable=True)
        assert ledger.read_bytes() == old
    finally:
        special.unlink(missing_ok=True)


@pytest.mark.parametrize("fault", ["hardlink", "foreign_uid", "device", "socket", "entry_bound", "depth_bound", "manifest_bound"])
def test_failed_filesystem_collector_rejects_unsupported_metadata_before_payload_open(tmp_path, monkeypatch, fault):
    import stat
    attempt = tmp_path / "attempt"; attempt.mkdir(); payload = attempt / "payload"
    payload.write_bytes(b"ordinary")
    alias = attempt / "alias"
    if fault == "hardlink": os.link(payload, alias)
    if fault in {"foreign_uid", "device", "socket"}:
        original_stat = external.os.stat
        def altered(path, *args, **kwargs):
            info = original_stat(path, *args, **kwargs)
            if os.fspath(path) == "payload" and kwargs.get("follow_symlinks") is False:
                fields = list(info)
                if fault == "foreign_uid": fields[4] = os.getuid() + 1
                else: fields[0] = (stat.S_IFCHR if fault == "device" else stat.S_IFSOCK) | 0o600
                return os.stat_result(fields)
            return info
        monkeypatch.setattr(external.os, "stat", altered)
    elif fault == "entry_bound": monkeypatch.setattr(external, "MAX_FAILED_FILESYSTEM_ENTRIES", 0)
    elif fault == "depth_bound":
        (attempt / "sub").mkdir(); monkeypatch.setattr(external, "MAX_FAILED_FILESYSTEM_DEPTH", 0)
    elif fault == "manifest_bound": monkeypatch.setattr(external, "MAX_FAILED_FILESYSTEM_MANIFEST_BYTES", 1)
    try:
        with pytest.raises(external.resources.DaemonResourceError):
            external.failed_filesystem_manifest(attempt)
    finally:
        alias.unlink(missing_ok=True)


@pytest.mark.parametrize("race", ["regular_to_fifo", "symlink_text", "regular_contents", "directory_replace", "root_replace"])
def test_failed_filesystem_anchored_scan_rejects_substitution_without_opening_special_payload(tmp_path, monkeypatch, race):
    attempt = tmp_path / "attempt"; attempt.mkdir(); payload = attempt / "payload"
    payload.write_bytes(b"original")
    special = attempt / "special"
    original_open = external.os.open; original_read = external.os.read; original_readlink = external.os.readlink
    fired = False
    if race == "regular_to_fifo":
        def swapped(path, flags, *args, **kwargs):
            nonlocal fired
            if os.fspath(path) == "payload" and flags & os.O_PATH and not fired:
                fired = True; payload.unlink(); os.mkfifo(payload)
            if os.fspath(path).startswith("/proc/self/fd/"):
                assert stat_is_regular(os.fstat(int(os.fspath(path).rsplit("/", 1)[1])).st_mode)
            return original_open(path, flags, *args, **kwargs)
        monkeypatch.setattr(external.os, "open", swapped)
    elif race == "symlink_text":
        special.symlink_to("first")
        def swapped(path, *args, **kwargs):
            nonlocal fired
            result = original_readlink(path, *args, **kwargs)
            if os.fspath(path) == "special" and not fired:
                fired = True; special.unlink(); special.symlink_to("second")
            return result
        monkeypatch.setattr(external.os, "readlink", swapped)
    elif race == "regular_contents":
        def changed(descriptor, count):
            nonlocal fired
            result = original_read(descriptor, count)
            if result and not fired:
                fired = True; payload.write_bytes(b"mutated!")
            return result
        monkeypatch.setattr(external.os, "read", changed)
    elif race == "directory_replace":
        special.mkdir(); replacement = attempt / "replacement"; replacement.mkdir()
        def swapped(path, flags, *args, **kwargs):
            nonlocal fired
            if os.fspath(path) == "special" and flags & os.O_DIRECTORY and not fired:
                fired = True; special.rename(attempt / "old-special"); replacement.rename(special)
            return original_open(path, flags, *args, **kwargs)
        monkeypatch.setattr(external.os, "open", swapped)
    else:
        replacement = tmp_path / "replacement-root"; replacement.mkdir()
        (replacement / "payload").write_bytes(b"must never read")
        def swapped(path, flags, *args, **kwargs):
            nonlocal fired
            if os.fspath(path) == str(attempt) and flags & os.O_DIRECTORY and not fired:
                fired = True; attempt.rename(tmp_path / "old-attempt"); replacement.rename(attempt)
            assert not (fired and os.fspath(path) == "payload"), "substituted root child was opened"
            return original_open(path, flags, *args, **kwargs)
        monkeypatch.setattr(external.os, "open", swapped)
    try:
        with pytest.raises(external.resources.DaemonResourceError):
            external.failed_filesystem_manifest(attempt)
        assert fired
    finally:
        if payload.exists() and not payload.is_file(): payload.unlink()
        if special.is_symlink(): special.unlink()


def stat_is_regular(mode):
    import stat
    return stat.S_ISREG(mode)


@pytest.mark.parametrize("fault", ["missing_row", "count", "typed_float", "typed_bool", "target_flag", "duplicate", "pin", "inside_attempt", "manifest_hardlink", "external", "empty", "empty_parented", "assertion", "successful", "artifact_assertion"])
def test_failed_filesystem_exact_manifest_and_profile_fail_closed_without_write(setup, monkeypatch, fault):
    ledger, roots, claim, attempt, state = prepare_failed_filesystem(setup)
    document, path = freeze_failed_filesystem(roots, claim)
    alias = roots[3] / "manifest-alias"
    if fault == "missing_row": document["entries"] = []
    elif fault == "count": document["entry_count"] += 1
    elif fault == "typed_float": document["entry_count"] = float(document["entry_count"])
    elif fault == "typed_bool": document["entry_count"] = True
    elif fault == "target_flag": document["targets_followed"] = True
    elif fault == "duplicate":
        path.write_bytes(b'{"schema":"wrong","schema":"duplicate"}')
    elif fault == "pin": claim["failed_filesystem_manifest"]["sha256"] = "0" * 64
    elif fault == "inside_attempt":
        path = attempt / "manifest.json"; path.write_bytes(external._wire(document))
    elif fault == "manifest_hardlink": os.link(path, alias)
    elif fault == "external": state["reservations"][claim["reservation_id"]]["external_charges"] = {"unreviewed":1}
    elif fault == "empty": (attempt / "failure.json").unlink()
    elif fault == "empty_parented": claim["allow_empty_failed_admission"] = True
    elif fault == "successful": state["reservations"][claim["reservation_id"]]["retention_reason"] = "explicit_release_required"
    elif fault == "artifact_assertion": state["reservations"][claim["reservation_id"]]["artifacts_durable_asserted"] = True
    if fault in {"missing_row", "count", "typed_float", "typed_bool", "target_flag"}: path.write_bytes(external._wire(document))
    if fault not in {"pin"}: claim["failed_filesystem_manifest"] = pin(path)
    claim["expected_record_sha256"] = external.base._digest(state["reservations"][claim["reservation_id"]])
    ledger.write_text(json.dumps(state)); before = ledger.read_bytes()
    try:
        with pytest.raises(external.resources.DaemonResourceError):
            external.reconcile_retained_failed_filesystem_reservations_batch(ledger, roots=roots, claims=[claim],
                failed_filesystem_disposition=fault != "assertion")
        assert ledger.read_bytes() == before
        if fault == "inside_attempt":
            # The second subassertion exercises detached-parent replacement
            # after file validation but during fsync, preserving this case's
            # exact selection/count and the first inside-attempt denial.
            parent = roots[3] / "detached-parent"; parent.mkdir()
            detached = parent / "manifest.json"
            detached.write_bytes(external._wire(external.failed_filesystem_manifest(attempt)))
            reference = pin(detached); parent_inode = parent.stat().st_ino
            original_fsync = external.os.fsync; fired = False
            def swap_parent(descriptor):
                nonlocal fired
                if os.fstat(descriptor).st_ino == parent_inode and not fired:
                    fired = True; parent.rename(roots[3] / "original-detached-parent")
                    parent.mkdir(); (parent / "manifest.json").write_bytes(
                        (roots[3] / "original-detached-parent" / "manifest.json").read_bytes())
                return original_fsync(descriptor)
            monkeypatch.setattr(external.os, "fsync", swap_parent)
            with pytest.raises(external.resources.DaemonResourceError, match="parent changed"):
                external._failed_manifest(reference, attempt, roots)
            assert fired and ledger.read_bytes() == before
    finally:
        alias.unlink(missing_ok=True)


@pytest.mark.parametrize("fault", ["owner_alive", "group_alive", "group_unknown", "native_policy", "native_path", "native_present", "native_descendant"])
def test_failed_filesystem_retains_all_process_and_current_native_absence_guards(setup, monkeypatch, fault):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler
    ledger, roots, claim, attempt, state = prepare_failed_filesystem(setup)
    freeze_failed_filesystem(roots, claim)
    row = state["reservations"][claim["reservation_id"]]
    if fault == "owner_alive": row["owner_pid"] = os.getpid()
    elif fault in {"group_alive", "group_unknown"}:
        monkeypatch.setattr(external.resources, "_group_usage", lambda _: {
            "available":fault != "group_unknown", "live_processes":int(fault == "group_alive")})
    elif fault == "native_policy": claim["native_inspection"]["policy_sha256"] = "0" * 64
    elif fault == "native_path": claim["native_inspection"]["state_path"] += ".foreign"
    else:
        original = existing_resource_scheduler._PinnedGlobalResourceScheduler.inspect_lease
        def present(*args, **kwargs):
            result = original(*args, **kwargs)
            if fault == "native_present": result.update(status="present", lease={"status":"present"})
            else: result["descendant_count"] = 1
            return result
        monkeypatch.setattr(existing_resource_scheduler._PinnedGlobalResourceScheduler, "inspect_lease", present)
    claim["expected_record_sha256"] = external.base._digest(row)
    ledger.write_text(json.dumps(state)); before = ledger.read_bytes()
    with pytest.raises((external.resources.DaemonResourceError, existing_resource_scheduler.ExistingResourceSchedulerError)):
        close_failed_filesystem(ledger, roots, [claim])
    assert ledger.read_bytes() == before


@pytest.mark.parametrize("number", [1,2])
@pytest.mark.parametrize("fault", ["manifest", "payload", "request", "selected", "foreign", "attempt_identity"])
def test_failed_filesystem_repeats_all_manifest_and_claim_proofs_across_censuses(setup, monkeypatch, number, fault):
    ledger, roots, claim, attempt, state = prepare_failed_filesystem(setup)
    _, manifest = freeze_failed_filesystem(roots, claim)
    factory, _, _, _ = setup
    with factory() as foreign: pass
    original = external.base._administrative_census; count = 0; before = ledger.read_bytes()
    claims = [claim]
    moved = attempt.with_name(attempt.name + "-original")
    def changed(helper, document):
        nonlocal count
        result = original(helper, document); count += 1
        if count == number:
            if fault == "manifest": manifest.write_bytes(b"substituted")
            elif fault == "payload": (attempt / "failure.json").write_bytes(b"changed")
            elif fault == "request": claims[0]["native_inspection"]["request_id"] = "other"
            elif fault == "selected": document["reservations"][claim["reservation_id"]]["storage_bytes"] += 1
            elif fault == "foreign": document["reservations"][foreign.reservation_id]["retention_reason"] = "changed"
            else:
                attempt.rename(moved); attempt.mkdir(); (attempt / "failure.json").write_bytes((moved / "failure.json").read_bytes())
        return result
    monkeypatch.setattr(external.base, "_administrative_census", changed)
    with pytest.raises(external.resources.DaemonResourceError):
        close_failed_filesystem(ledger, roots, claims)
    assert ledger.read_bytes() == before


@pytest.mark.parametrize("stage", ["before_write", "after_write", "readback"])
def test_failed_filesystem_write_uncertainty_preserves_actual_disposition_and_forbids_replay(setup, monkeypatch, stage):
    ledger, roots, claim, attempt, _ = prepare_failed_filesystem(setup)
    freeze_failed_filesystem(roots, claim)
    original_write = external.resources.DaemonResourceReservation._write
    original_read = external.resources.DaemonResourceReservation._read
    before = ledger.read_bytes(); writes = 0; committed = False
    def failing_write(helper, state):
        nonlocal writes, committed
        writes += 1
        if stage == "before_write": raise OSError("synthetic prewrite failure")
        result = original_write(helper, state); committed = True
        if stage == "after_write": raise OSError("synthetic postwrite failure")
        return result
    def failing_read(helper):
        if stage == "readback" and committed: raise OSError("synthetic readback failure")
        return original_read(helper)
    monkeypatch.setattr(external.resources.DaemonResourceReservation, "_write", failing_write)
    monkeypatch.setattr(external.resources.DaemonResourceReservation, "_read", failing_read)
    with pytest.raises(external.FailedFilesystemDispositionWriteIncomplete) as caught:
        close_failed_filesystem(ledger, roots, [claim])
    assert writes == 1
    observation = caught.value.observation
    assert observation["automatic_replay_permitted"] is observation["rollback_asserted"] is False
    assert observation["ledger_write_attempted"] is True
    assert observation["ledger_write_returned"] is (stage == "readback")
    assert observation["write_completed"] is (True if stage == "readback" else None)
    assert observation["observed_write_disposition"] == {
        "before_write":"exact_selected_preimages", "after_write":"exact_expected_postimage", "readback":"unknown"}[stage]
    if stage == "before_write": assert ledger.read_bytes() == before
    else: assert json.loads(ledger.read_bytes())["reservations"][claim["reservation_id"]]["status"] == "released"
    # A caller must inspect, not replay; the API still rejects the released CAS.
    if stage != "before_write":
        monkeypatch.setattr(external.resources.DaemonResourceReservation, "_read", original_read)
        with pytest.raises(external.resources.DaemonResourceError, match="identity changed"):
            close_failed_filesystem(ledger, roots, [claim])
        assert writes == 1


def test_failed_filesystem_batch_one_later_invalid_claim_prevents_every_write(setup, monkeypatch):
    ledger, roots, first, _, _ = prepare_failed_filesystem(setup); freeze_failed_filesystem(roots, first)
    _, _, second, _, _ = prepare_failed_filesystem(setup); freeze_failed_filesystem(roots, second)
    second["expected_record_sha256"] = "0" * 64
    before = ledger.read_bytes(); writes = []
    monkeypatch.setattr(external.resources.DaemonResourceReservation, "_write", lambda *args: writes.append(args))
    with pytest.raises(external.resources.DaemonResourceError): close_failed_filesystem(ledger, roots, [first,second])
    assert not writes and ledger.read_bytes() == before
