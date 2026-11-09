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


def _nested_path_order_fixture(fixture):
    """Real private producer evidence with differing Path and string order."""
    _, _, args, attempt, external = fixture
    for tree in (attempt, external):
        nested = tree / "native" / "grok"
        nested.mkdir(parents=True)
        (nested / "report.json").write_bytes(b'{"private":true}')
        (tree / "native-parse-refusal-predicate-fixtures.json").write_bytes(b'[]')
    args["expected_artifacts"] = old._durable_inventory(attempt)
    args["external_evidence"]["expected_artifacts"] = old._durable_inventory(external)
    for artifacts in (args["expected_artifacts"], args["external_evidence"]["expected_artifacts"]):
        paths = [row["path"] for row in artifacts]
        assert paths.index("native/grok/report.json") < paths.index("native-parse-refusal-predicate-fixtures.json")
        assert paths != sorted(paths)
    return fixture


def test_real_nested_durable_producer_order_releases_only_selected_private_claim(fixture):
    helper, ledger, args, attempt, external = _nested_path_order_fixture(fixture)
    expected_attempt = deepcopy(args["expected_artifacts"])
    expected_external = deepcopy(args["external_evidence"]["expected_artifacts"])
    report = api.reconcile_retained_external_reservation(helper.ledger_path,
        **args, capacity_policy="administrative_closeout")
    actual = helper._read()
    selected = actual["reservations"]["inert-selected"]
    assert selected["status"] == "released" and selected["external_charges"] == {"inert-external": 128}
    assert actual["reservations"]["inert-other"] == ledger["reservations"]["inert-other"]
    assert report["artifacts"] == args["expected_artifacts"] == expected_attempt
    assert report["external_artifacts"] == args["external_evidence"]["expected_artifacts"] == expected_external
    assert old._durable_inventory(attempt) == expected_attempt
    assert old._durable_inventory(external) == expected_external
    assert report["final_nonpersisted_census_verified"] is True
    assert report["full_claim_accounting"]["outstanding_full_reservations_bytes"] \
        - report["final_nonpersisted_accounting"]["outstanding_full_reservations_bytes"] == 4096
    assert report["admitted"] is report["outputs_deleted"] is report["cap_changed"] is False


def test_reverse_shuffled_and_string_sorted_nested_evidence_refuse_without_private_ledger_write(fixture):
    helper, _, args, *_ = _nested_path_order_fixture(fixture)
    before = helper.ledger_path.read_bytes()
    for which in ("attempt", "external"):
        original = args["expected_artifacts"] if which == "attempt" else args["external_evidence"]["expected_artifacts"]
        variants = (list(reversed(original)), original[1:] + original[:1],
                    sorted(original, key=lambda row: row["path"]))
        for artifacts in variants:
            assert artifacts != original
            changed = deepcopy(args)
            if which == "attempt":
                changed["expected_artifacts"] = artifacts
            else:
                changed["external_evidence"]["expected_artifacts"] = artifacts
            with pytest.raises(r.DaemonResourceError, match="artifact paths repeat or are unsorted"):
                api.reconcile_retained_external_reservation(helper.ledger_path,
                    **changed, capacity_policy="administrative_closeout")
            assert helper.ledger_path.read_bytes() == before


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


# New opt-in proof fixtures are inert metadata and real ordinary filesystem
# state. They neither reconstruct an original execution request nor allocate
# native resources. The legacy fixture/function AST prefix remains unchanged.
def _write_parented_proof(fixture, documents):
    helper, _, args, attempt, _ = fixture
    directory=helper.ledger_path.parent/'original-captured-parented-records'
    directory.mkdir(exist_ok=True)
    request_path=directory/'request.json';terminal_path=directory/'owner-stdout.json';reap_path=directory/'root-genuine-reap.json'
    request_path.write_text(json.dumps(documents['request'],sort_keys=True))
    documents['terminal']['request_sha256']=pin(request_path)['sha256']
    terminal_path.write_text(json.dumps(documents['terminal'],sort_keys=True))
    documents['root_reap'].update(request=pin(request_path),terminal=pin(terminal_path))
    reap_path.write_text(json.dumps(documents['root_reap'],sort_keys=True))
    args['external_evidence']['execution_request_pin']=pin(request_path)
    proof={'schema':'original-parented-external-collection-failure-proof/v1',
        'request':pin(request_path),'terminal':pin(terminal_path),'root_reap':pin(reap_path)}
    args['original_parented_owner_proof']=proof
    return proof


def _parented_collection_fixture(fixture, *, stdio=False):
    helper, ledger, args, attempt, external = fixture
    (attempt/'execution-request.json').unlink()  # Inert legacy fixture only.
    (external/'fixture-data.txt').unlink()
    if stdio:
        (external/'.stdio-sinks').mkdir()
        for name in ('stdin','stdout','stderr'):(external/'.stdio-sinks'/name).write_bytes(b'')
    else:
        (external/'empty'/'ordinary'/'directories').mkdir(parents=True)
    row=ledger['reservations']['inert-selected']
    row.update(workload='canonical_parented_phase',scheduler_lane='validation',
        cpu_slots=1,memory_mb=1536,child_process_slots=8,native_lease_id='inert-closed-native')
    helper._write(ledger);args['expected_record_sha256']=old._digest(row)
    args['expected_artifacts']=inventory(attempt);args['external_evidence']['expected_artifacts']=inventory(external)
    physical={'root':str(external),'apparent_bytes':0,'entry_count':4 if stdio else 3,'targets_followed':False,
        'symlinks':0,'fifos':0,'hardlinked_regular_paths':0}
    documents={
        'request':{'schema':'legal-ir-original-parented-private-git-validation/v1','purpose':'private_git_validation',
            'attempt_directory':str(attempt),'fixture_directory':str(external),'fixture_max_bytes':128,
            'resource_ledger':str(helper.ledger_path),'storage_bytes':4096,'memory_mb':1536,'cpu_slots':1,'child_process_slots':8},
        'terminal':{'schema':'legal-ir-original-parented-focused-validation-terminal/v1',
            'completed':False,'child_reaped':True,'child_returncode':1,'cleanup_errors':[],'received_signals':[],
            'source_READ_closed':True,'original_native_compute_closed':True,'storage_status':'retained',
            'task_completion_authority_granted_by_resource_owner':False,'owner_pid':row['owner_pid'],'owner_birth':'inert-original-birth',
            'external_precharge':{'key':'inert-external','bytes':128,'already_charged':False},
            'external_before':deepcopy(physical),'external_after':deepcopy(physical),
            'reservation':{'status':'retained','reservation_id':'inert-selected','cleanup_error':None,
                'ledger_path':str(helper.ledger_path),'record':deepcopy(row),
                'resource_lease':{'released':True,'lease_id':'inert-closed-native'}}},
        'root_reap':{'schema':'native-metadata-qualification-ROOT-genuine-collection-failure-reap/v1',
            'outer_exec_genuinely_reaped':True,'outer_exec_exit_code':1,'reservation_id':'inert-selected',
            'source_READ_closed':True,'original_native_compute_closed':True,'storage_status':'retained',
            'no_actual_native_task_or_provider_or_model_effects':True,'case_count':0,'passed_cases':0,
            'phase_count':0,'private_SQL_connections':0,'full_storage_claim_bytes':4096,
            'external_charges':{'inert-external':128}}}
    _write_parented_proof(fixture,documents)
    return fixture,documents


def test_parented_empty_collection_failure_uses_shared_recovery_without_reconstructed_request(fixture):
    fixture,documents=_parented_collection_fixture(fixture);helper,ledger,args,attempt,external=fixture
    before_other=deepcopy(ledger['reservations']['inert-other']);proof=deepcopy(args['original_parented_owner_proof'])
    report=api.reconcile_retained_parented_external_reservation_v1(helper.ledger_path,**args)
    row=helper._read()['reservations']['inert-selected']
    assert row['status']=='released' and row['external_charges']=={'inert-external':128}
    assert row['final_external_charged_bytes']==128 and report['external_actual_bytes']==0
    assert report['empty_external_collection_failure_only'] is True
    assert report['original_execution_request_reconstructed'] is False
    assert report['original_parented_owner_proof']==proof
    assert report['final_nonpersisted_census_verified'] is True
    assert helper._read()['reservations']['inert-other']==before_other
    assert not (attempt/'execution-request.json').exists() and inventory(external)==[]
    assert all(pin(Path(value['path']))==value for key,value in proof.items()if key!='schema')


@pytest.mark.parametrize('fault',[
    'root_not_reaped','root_code_bool','root_cases','root_SQL','root_record',
    'child_unknown','cleanup','cleanup_missing','native_live','source_open',
    'charge','request_external_root','current_record','external_nonempty','missing_proof','extra_proof_field'])
def test_parented_collection_failure_refuses_incomplete_or_changed_original_evidence(fixture,fault):
    fixture,documents=_parented_collection_fixture(fixture);helper,_,args,_,external=fixture
    if fault=='root_not_reaped':documents['root_reap']['outer_exec_genuinely_reaped']=False
    elif fault=='root_code_bool':documents['root_reap']['outer_exec_exit_code']=True
    elif fault=='root_cases':documents['root_reap']['case_count']=1
    elif fault=='root_SQL':documents['root_reap']['private_SQL_connections']=1
    elif fault=='root_record':documents['root_reap']['reservation_id']='foreign'
    elif fault=='child_unknown':documents['terminal']['child_reaped']=False
    elif fault=='cleanup':documents['terminal']['reservation']['cleanup_error']='unknown'
    elif fault=='cleanup_missing':documents['terminal']['reservation'].pop('cleanup_error')
    elif fault=='native_live':documents['terminal']['reservation']['resource_lease']['released']=False
    elif fault=='source_open':documents['terminal']['source_READ_closed']=False
    elif fault=='charge':documents['terminal']['external_precharge']['bytes']+=1
    elif fault=='request_external_root':documents['request']['fixture_directory']=str(external.parent/'foreign')
    elif fault=='current_record':documents['terminal']['reservation']['record']['retention_reason']='different'
    elif fault=='external_nonempty':
        (external/'foreign.txt').write_text('no historical payload claim');args['external_evidence']['expected_artifacts']=inventory(external)
    _write_parented_proof(fixture,documents)
    if fault=='missing_proof':args['original_parented_owner_proof']=None
    elif fault=='extra_proof_field':args['original_parented_owner_proof']['unprovided_authority']=True
    before=helper.ledger_path.read_bytes()
    with pytest.raises(r.DaemonResourceError):api.reconcile_retained_parented_external_reservation_v1(helper.ledger_path,**args)
    assert helper.ledger_path.read_bytes()==before


def test_legacy_execution_request_protocol_stays_strict_for_parented_original_captures(fixture):
    fixture,_=_parented_collection_fixture(fixture);helper,_,args,attempt,_=fixture
    original={key:value for key,value in args.items()if key!='original_parented_owner_proof'}
    before=helper.ledger_path.read_bytes()
    with pytest.raises(r.DaemonResourceError):api.reconcile_retained_external_reservation(helper.ledger_path,**original)
    assert helper.ledger_path.read_bytes()==before and not (attempt/'execution-request.json').exists()


@pytest.mark.parametrize('which',['request','terminal','root_reap'])
def test_parented_original_proof_bytes_are_rechecked_after_actual_census(fixture,monkeypatch,which):
    fixture,_=_parented_collection_fixture(fixture);helper,_,args,_,_=fixture
    original=r.DaemonResourceReservation._account;target=Path(args['original_parented_owner_proof'][which]['path'])
    changed=[]
    def census_then_actual_drift(owner,ledger,*extra,**kwargs):
        result=original(owner,ledger,*extra,**kwargs)
        if not changed:target.write_bytes(target.read_bytes()+b'\n');changed.append(True)
        return result
    monkeypatch.setattr(r.DaemonResourceReservation,'_account',census_then_actual_drift)
    before=helper.ledger_path.read_bytes()
    with pytest.raises(r.DaemonResourceError):api.reconcile_retained_parented_external_reservation_v1(helper.ledger_path,**args)
    assert changed==[True] and helper.ledger_path.read_bytes()==before


@pytest.mark.parametrize('write_number',[1,2])
def test_parented_actual_postwrite_proof_drift_preserves_explicit_pending_disposition(fixture,monkeypatch,write_number):
    fixture,_=_parented_collection_fixture(fixture);helper,ledger,args,_,_=fixture
    parent=helper.ledger_path.parent;identity=(parent.stat().st_dev,parent.stat().st_ino)
    original=os.fsync;writes=[];target=Path(args['original_parented_owner_proof']['root_reap']['path'])
    def persist_then_change_original_proof(fd):
        result=original(fd);info=os.fstat(fd)
        if stat.S_ISDIR(info.st_mode)and (info.st_dev,info.st_ino)==identity:
            writes.append(True)
            if len(writes)==write_number:target.write_bytes(target.read_bytes()+b'\n')
        return result
    monkeypatch.setattr(os,'fsync',persist_then_change_original_proof)
    with pytest.raises(api.ExternalRecoveryPostwritePending)as caught:
        api.reconcile_retained_parented_external_reservation_v1(helper.ledger_path,**args)
    error=caught.value;assert len(writes)==write_number
    assert error.claim_released is True and error.automatic_retry_permitted is False and error.rollback_claimed is False
    assert error.observed_disposition==('released_pending_observed'if write_number==1 else'released_receipt_observed')
    assert error.postwrite_verification_pending is True
    assert helper._read()['reservations']['inert-other']==ledger['reservations']['inert-other']


def test_parented_original_three_zero_byte_stdio_files_are_preserved_and_released(fixture):
    fixture,_=_parented_collection_fixture(fixture,stdio=True)
    helper,ledger,args,attempt,external=fixture
    expected=deepcopy(args['external_evidence']['expected_artifacts'])
    assert [row['path']for row in expected]==['.stdio-sinks/stderr','.stdio-sinks/stdin','.stdio-sinks/stdout']
    assert len(expected)==3 and all(row['bytes']==0 for row in expected)
    report=api.reconcile_retained_parented_external_reservation_v1(helper.ledger_path,**args)
    assert report['external_actual_bytes']==0 and report['external_artifacts']==expected
    assert report['final_nonpersisted_census_verified']is True
    assert inventory(external)==expected and not(attempt/'execution-request.json').exists()
    assert helper._read()['reservations']['inert-selected']['external_charges']=={'inert-external':128}
    assert helper._read()['reservations']['inert-other']==ledger['reservations']['inert-other']


# Explicit indexed receipts preserve the full evidence in a separate durable
# private document; they do not relax the original recovery protocol.
def indexed_evidence(fixture):
    helper, _, args, attempt, _ = fixture
    path = helper.ledger_path.parent / "artifact-index.json"
    body = {"schema": "external-reservation-artifact-index/v1",
        "reservation_id": args["reservation_id"],
        "previous_record_sha256": args["expected_record_sha256"],
        "attempt_directory": str(attempt),
        "expected_artifacts": deepcopy(args["expected_artifacts"]),
        "external_evidence": deepcopy(args["external_evidence"])}
    path.write_text(json.dumps(body, sort_keys=True))
    with path.open("rb") as stream:
        os.fsync(stream.fileno())
    return path, body


def test_indexed_recovery_preserves_complete_evidence_outputs_and_bounded_ledger(fixture):
    helper, ledger, args, attempt, external = fixture
    index, _ = indexed_evidence(fixture)
    before = index.read_bytes(), inventory(attempt), inventory(external)
    report = api.reconcile_retained_external_reservation_indexed_v1(
        helper.ledger_path, **args, artifact_index_pin=pin(index))
    actual = helper._read()
    marker = actual["reservations"]["inert-selected"]["explicit_external_reconciliation"]
    assert marker["schema"].endswith("/indexed-v1")
    assert marker["artifact_index_pin"] == pin(index)
    assert "artifacts" not in marker and "external_artifacts" not in marker
    for key, rows in (("artifacts", args["expected_artifacts"]),
                      ("external_artifacts", args["external_evidence"]["expected_artifacts"])):
        assert marker[key + "_summary"] == {"count": len(rows),
            "bytes": sum(row["bytes"] for row in rows), "sha256": old._digest(rows)}
    assert before == (index.read_bytes(), inventory(attempt), inventory(external))
    assert actual["reservations"]["inert-other"] == ledger["reservations"]["inert-other"]
    assert report["final_nonpersisted_census_verified"] is True
    assert actual["reservations"]["inert-selected"]["external_charges"] == {"inert-external": 128}


@pytest.mark.parametrize("field", ["schema", "reservation_id", "previous_record_sha256",
    "attempt_directory", "expected_artifacts", "external_evidence", "extra_field"])
def test_indexed_recovery_refuses_incomplete_or_different_full_manifest(fixture, field):
    helper, _, args, *_ = fixture
    index, body = indexed_evidence(fixture)
    body[field] = "different original evidence"
    index.write_text(json.dumps(body))
    before = helper.ledger_path.read_bytes()
    with pytest.raises(r.DaemonResourceError, match="artifact index"):
        api.reconcile_retained_external_reservation_indexed_v1(
            helper.ledger_path, **args, artifact_index_pin=pin(index))
    assert helper.ledger_path.read_bytes() == before


def test_indexed_recovery_still_requires_original_execution_request(fixture):
    helper, _, args, attempt, _ = fixture
    request = attempt / "execution-request.json"
    request.write_text(json.dumps({"disk_reservation_id": "unrelated",
        "external_precharge": {"root": args["external_evidence"]["root_identity"]["path"], "bytes": 128}}))
    args["expected_artifacts"] = inventory(attempt)
    args["external_evidence"]["execution_request_pin"] = pin(request)
    index, _ = indexed_evidence(fixture)
    before = helper.ledger_path.read_bytes()
    with pytest.raises(r.DaemonResourceError, match="original execution request"):
        api.reconcile_retained_external_reservation_indexed_v1(
            helper.ledger_path, **args, artifact_index_pin=pin(index))
    assert helper.ledger_path.read_bytes() == before


def test_indexed_recovery_refuses_stale_manifest_before_ledger_write(fixture, monkeypatch):
    helper, _, args, *_ = fixture
    index, _ = indexed_evidence(fixture)
    expected_pin = pin(index)
    before = helper.ledger_path.read_bytes()
    original = r.DaemonResourceReservation._account
    def change_index(self, *values, **options):
        report = original(self, *values, **options)
        index.write_text('{"changed":true}')
        return report
    monkeypatch.setattr(r.DaemonResourceReservation, "_account", change_index)
    with pytest.raises(r.DaemonResourceError):
        api.reconcile_retained_external_reservation_indexed_v1(
            helper.ledger_path, **args, artifact_index_pin=expected_pin)
    assert helper.ledger_path.read_bytes() == before


def test_indexed_recovery_refuses_manifest_outside_named_roots(fixture, tmp_path):
    helper, _, args, *_ = fixture
    # The declared root is narrowed to both inventories; the index stays in
    # their original parent, outside the new exact named roots.
    index, _ = indexed_evidence(fixture)
    before = helper.ledger_path.read_bytes()
    with pytest.raises(r.DaemonResourceError, match="outside named storage roots"):
        api.reconcile_retained_external_reservation_indexed_v1(helper.ledger_path,
            **{**args, "roots": [args["attempt_directory"], args["external_evidence"]["root_identity"]["path"]]},
            artifact_index_pin=pin(index))
    assert helper.ledger_path.read_bytes() == before


def test_indexed_recovery_closes_real_private_ledger_byte_pressure_without_raising_cap(fixture, monkeypatch):
    helper, ledger, args, attempt, external = fixture
    for n in range(200):
        (external / ("entry-%04d.txt" % n)).write_bytes(b"x")
    # This is an expressly inert private reservation, never a real allocation.
    ledger["reservations"]["inert-selected"].update(storage_bytes=16384,
        external_charges={"inert-external": 4096})
    helper._write(ledger)
    args["expected_record_sha256"] = old._digest(ledger["reservations"]["inert-selected"])
    request = attempt / "execution-request.json"
    request.write_text(json.dumps({"disk_reservation_id": "inert-selected",
        "external_precharge": {"root": str(external), "bytes": 4096}}))
    args["expected_artifacts"] = inventory(attempt)
    args["external_evidence"].update(charged_bytes=4096,
        execution_request_pin=pin(request), expected_artifacts=inventory(external))
    index, _ = indexed_evidence(fixture)
    # Lower only the synthetic child's private byte ceiling, then exercise
    # the original real serialization/write path at an actual boundary.
    monkeypatch.setattr(r, "MAX_LEDGER_BYTES", 16384)
    before = helper.ledger_path.read_bytes()
    with pytest.raises(api.ExternalRecoveryWriteIncomplete) as caught:
        api.reconcile_retained_external_reservation(helper.ledger_path, **args)
    assert caught.value.stage == "initial_release_write"
    assert caught.value.observed_disposition == "retained_preimage_observed"
    assert helper.ledger_path.read_bytes() == before
    report = api.reconcile_retained_external_reservation_indexed_v1(
        helper.ledger_path, **args, artifact_index_pin=pin(index))
    assert report["final_nonpersisted_census_verified"] is True
    assert helper._read()["reservations"]["inert-selected"]["status"] == "released"
    assert helper.ledger_path.stat().st_size <= 16384 == r.MAX_LEDGER_BYTES
    assert len(inventory(external)) == 201



def test_indexed_recovery_freezes_caller_descriptor_before_callbacks(fixture, monkeypatch):
    helper, _, args, *_ = fixture
    index, _ = indexed_evidence(fixture)
    original_pin = pin(index)
    caller_pin = deepcopy(original_pin)
    replacement = index.with_name("another-identical-index.json")
    replacement.write_bytes(index.read_bytes())
    original = r.DaemonResourceReservation._account
    def change_reference(self, *values, **options):
        caller_pin.update(pin(replacement))
        return original(self, *values, **options)
    monkeypatch.setattr(r.DaemonResourceReservation, "_account", change_reference)
    report = api.reconcile_retained_external_reservation_indexed_v1(
        helper.ledger_path, **args, artifact_index_pin=caller_pin)
    assert caller_pin != original_pin
    assert report["artifact_index_pin"] == original_pin
    assert helper._read()["reservations"]["inert-selected"]["explicit_external_reconciliation"]["artifact_index_pin"] == original_pin


@pytest.mark.parametrize("fault", ["float_charge", "boolean_durability"])
def test_indexed_recovery_refuses_equal_python_values_with_different_json_types(fixture, fault):
    helper, _, args, *_ = fixture
    index, body = indexed_evidence(fixture)
    if fault == "float_charge":
        body["external_evidence"]["charged_bytes"] = float(body["external_evidence"]["charged_bytes"])
    else:
        body["external_evidence"]["artifacts_durable"] = 1
    index.write_text(json.dumps(body))
    before = helper.ledger_path.read_bytes()
    with pytest.raises(r.DaemonResourceError, match="artifact index does not bind"):
        api.reconcile_retained_external_reservation_indexed_v1(
            helper.ledger_path, **args, artifact_index_pin=pin(index))
    assert helper.ledger_path.read_bytes() == before


@pytest.mark.parametrize("target", ["file", "directory"])
def test_indexed_recovery_refuses_undurable_index_before_release(fixture, monkeypatch, target):
    helper, _, args, *_ = fixture
    index, _ = indexed_evidence(fixture)
    info = (index if target == "file" else index.parent).stat()
    identity = info.st_dev, info.st_ino
    original = os.fsync
    def fail_selected(descriptor):
        current = os.fstat(descriptor)
        if (current.st_dev, current.st_ino) == identity:
            raise OSError("private indexed evidence durability failure")
        return original(descriptor)
    monkeypatch.setattr(os, "fsync", fail_selected)
    before = helper.ledger_path.read_bytes()
    with pytest.raises(OSError, match="durability failure"):
        api.reconcile_retained_external_reservation_indexed_v1(
            helper.ledger_path, **args, artifact_index_pin=pin(index))
    assert helper.ledger_path.read_bytes() == before
