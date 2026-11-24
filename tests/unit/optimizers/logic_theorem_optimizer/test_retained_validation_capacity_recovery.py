"""Synthetic stopped-claim guards through the original recovery/scheduler owners."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from scripts.ops.legal_ir import run_autoformal_supervisor as cli
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_resource_recovery as recovery
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_source_lease as lease
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as native


def pin(path):
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
    path.chmod(0o600)
    return pin(path)


@pytest.fixture
def stopped(tmp_path, monkeypatch):
    root = tmp_path / "owned";root.mkdir()
    attempt = root / "attempt";(attempt / "logs").mkdir(parents=True)
    state = root / "cleanup-state";state.mkdir(mode=0o700)
    scheduler_path = root / "native.json"
    config = native.ResourceSchedulerConfig(state_path=scheduler_path,
        total_cpu_slots=4, total_memory_mb=2048, total_gpu_memory_mb=None,
        total_unified_memory_mb=None, total_child_process_slots=4,
        lane_reservations={"validation": 1, "orchestration": 1},
        proof_safety_enabled=True, auto_renew_leases=False)
    scheduler = native.GlobalResourceScheduler(config)
    monkeypatch.setattr(cli, "CAPACITY_RECOVERY_LEDGER", root / "disk.json")
    monkeypatch.setattr(cli, "CAPACITY_RECOVERY_ROOTS", (root,))
    monkeypatch.setattr(cli, "CAPACITY_RECOVERY_SCHEDULER_STATE", scheduler_path)
    monkeypatch.setattr(cli, "CAPACITY_RECOVERY_POLICY_SHA256", existing.policy_sha256(config.persisted_dict()))
    rid = "a" * 32;native_id = "b" * 32;request_sha = "c" * 64
    owner_pid = int(Path("/proc/sys/kernel/pid_max").read_text()) + 1
    row = dict(reservation_id=rid, status="retained", owner_pid=owner_pid, owner_birth="1",
        storage_bytes=8192, memory_mb=1, cpu_slots=1, child_process_slots=1,
        scheduler_lane="validation", workload="canonical_validation", created_at=1.0,
        attempt_directory=resources._root_identity(attempt), child=None, prior_children=[],
        external_charges={}, last_usage={}, artifacts_durable_asserted=False,
        retention_reason="context_failed", validation_request_sha256=request_sha,
        native_lease_id=native_id, scheduler_state_path=str(scheduler_path),
        scheduler_policy_sha256=existing.policy_sha256(config.persisted_dict()),
        process_scope="isolated_process_group_only")
    failure = dict(schema="owned-validation-result/v1", completed=False, returncode=1,
        admitted=False, Lean_admitted=False, authority_granted=False, model_weights_downloaded=False,
        request_sha256=request_sha, received_signals=[], watchdog_errors=[])
    failure_ref = save(attempt / "logs/failure.json", failure)
    (attempt / "retained.txt").write_text("Preserve failed evidence.\n")
    save(cli.CAPACITY_RECOVERY_LEDGER, dict(schema=resources.SCHEMA,
        roots=[resources._root_identity(root)], limit_bytes=resources.MAX_STORAGE_BYTES,
        reservations={rid: row}))
    manifest_ref = save(root / "inventory.json", dict(schema="retained-artifact-inventory/v1",
        attempt_directory=row["attempt_directory"], artifacts=recovery._durable_inventory(attempt)))
    manifest = json.loads(Path(manifest_ref["path"]).read_text())
    controller_ref = save(root / "controller.json", {"historical_controller": "synthetic fixture"})
    pre = dict(schema="legal-ir-unblock-a612-retained-claim-prepare/v1", accepted=True, completed=True,
        source_READ_closed=True, capacity_policy="require_capacity", recovery_API_calls=0,
        reservation_id=rid, selected_record=row, selected_record_sha256=recovery._digest(row),
        controller=controller_ref, roots=[str(root)], source_api=pin(Path(recovery.__file__)),
        source_resources=pin(Path(resources.__file__)), source_scheduler=pin(Path(native.__file__)),
        original_failure=failure_ref, inventory_manifest=manifest_ref,
        artifact_count=len(manifest["artifacts"]), artifact_bytes=sum(x["bytes"] for x in manifest["artifacts"]),
        full_storage_claim_bytes=row["storage_bytes"])
    pre_ref = save(root / "preflight.json", pre)
    review = dict(accepted=True, source_READ_closed=True, preflight=pre_ref, controller=controller_ref)
    candidate = dict(preflight=pre_ref, review=save(root / "review.json", review))
    request_ref = save(root / "refused-request.json", dict(schema="legal-ir-original-native-control-request/v1",
        purpose="native_control_metadata", storage_bytes=201326592, resource_ledger=str(cli.CAPACITY_RECOVERY_LEDGER)))
    outstanding = 300000000;free = outstanding + 201326592 - 4096;observed = 1000
    terminal = dict(schema="legal-ir-original-native-control-terminal/v1", completed=False,
        control_effects="not_started", child_launch_attempted=False, original_native_compute_closed=True,
        source_READ_closed=True, absolute_resource_operation_deadline_closed=True, cleanup_errors=[],
        request_sha256=request_ref["sha256"], reservation=dict(record=None, resource_lease=None, status="not_entered"),
        resource_capacity_observation=dict(schema="daemon-resource-capacity-observation/v1",
            observed_apparent_bytes=observed, outstanding_full_reservations_bytes=outstanding,
            additional_requested_bytes=201326592, charged_bytes=observed + outstanding + 201326592,
            limit_bytes=resources.MAX_STORAGE_BYTES, minimum_filesystem_free_bytes=free,
            storage_capacity_deficit_bytes=0, filesystem_free_deficit_bytes=4096,
            storage_capacity_exceeded=False, filesystem_free_insufficient=True,
            scope="named_roots_only_apparent_bytes"))
    terminal_ref = save(root / "refused-terminal.json", terminal)
    wait = dict(schema="legal-ir-native0101-amendment-ROOT-actual-wait/v1",
        actual_wait_completed=True, exit_code=1, request=request_ref, stdout=terminal_ref)
    trigger = save(root / "root-wait.json", wait)
    def refresh():
        candidate["preflight"] = save(root / "preflight.json", pre)
        review["preflight"] = candidate["preflight"]
        candidate["review"] = save(root / "review.json", review)
    def run(**kwargs):
        with native.resource_cleanup_deadline(native_deadline_monotonic=time.monotonic() + 5):
            return cli._recover_retained_validation_capacity(trigger, [candidate], state, **kwargs)
    return dict(root=root, attempt=attempt, state=state, row=row, rid=rid, pre=pre, candidate=candidate,
        review=review, refresh=refresh, run=run, trigger=trigger, terminal=terminal, wait=wait,
        scheduler=scheduler, scheduler_path=scheduler_path, manifest_ref=manifest_ref)


def ledger():
    return json.loads(cli.CAPACITY_RECOVERY_LEDGER.read_text())


def deny_census(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("no original global inventory/census is allowed on this path")
    monkeypatch.setattr(resources, "_inventory", unexpected)


def test_one_original_reconciliation_preserves_files_and_second_tick_has_no_call(stopped, monkeypatch):
    before = recovery._durable_inventory(stopped["attempt"])
    native_before = stopped["scheduler_path"].read_bytes()
    result = stopped["run"]()
    assert result["status"] == "one_reviewed_claim_reconciled" and result["recovery_API_calls"] == 1
    row = ledger()["reservations"][stopped["rid"]]
    assert row["status"] == "released" and row["final_attempt_bytes"] == stopped["pre"]["artifact_bytes"]
    assert recovery._durable_inventory(stopped["attempt"]) == before
    assert stopped["scheduler_path"].read_bytes() == native_before
    assert result["actor_or_provider_or_task_calls"] == 0 and result["retry_authorized"] is False
    deny_census(monkeypatch)
    repeated = stopped["run"]()
    assert repeated["status"] == "trigger_already_started" and repeated["recovery_API_calls"] == 0


def test_manual_closeout_consumes_trigger_without_census_on_first_or_idle_tick(stopped, monkeypatch):
    pre = stopped["pre"]
    receipt = recovery.reconcile_retained_reservation(cli.CAPACITY_RECOVERY_LEDGER,
        roots=cli.CAPACITY_RECOVERY_ROOTS, reservation_id=stopped["rid"],
        expected_record_sha256=pre["selected_record_sha256"], attempt_directory=stopped["attempt"],
        expected_artifacts=json.loads(Path(pre["inventory_manifest"]["path"]).read_text())["artifacts"],
        artifacts_durable=True, capacity_policy="require_capacity", artifact_inventory_manifest=pre["inventory_manifest"])
    close = dict(accepted=True, completed=True, source_READ_closed=True, storage_claim_released=True,
        recovery_API_calls=1, capacity_policy="require_capacity", selected_record_sha256=pre["selected_record_sha256"],
        selected_record_after=ledger()["reservations"][stopped["rid"]], inventory_manifest=pre["inventory_manifest"],
        original_reconciliation=save(stopped["root"] / "manual-reconciliation.json", receipt),
        trigger_ROOT_failed_0101_reap=stopped["trigger"])
    close_ref = save(stopped["root"] / "manual-closeout.json", close)
    reap_ref = save(stopped["root"] / "manual-genuine-reap.json", dict(completed=True, source_READ_closed=True,
        outer_exec_genuinely_reaped=True, outer_exec_exit_code=0, closeout=close_ref))
    deny_census(monkeypatch)
    result = stopped["run"](resolved=[dict(closeout=close_ref, genuine_reap=reap_ref)])
    assert result["status"] == "authenticated_trigger_already_resolved" and result["recovery_API_calls"] == 0
    marker = next(stopped["state"].glob("*.resolved-trigger-v01.json"));before = marker.stat().st_mtime_ns
    assert stopped["run"]()["status"] == "authenticated_trigger_already_resolved"
    assert marker.stat().st_mtime_ns == before


@pytest.mark.parametrize("kind", ["noncapacity", "arithmetic", "actor_started", "launch_attempted", "unknown_source", "no_reap"])
def test_noneligible_trigger_refuses_before_recovery(stopped, monkeypatch, kind):
    terminal = stopped["terminal"];wait = stopped["wait"]
    if kind == "noncapacity":terminal.pop("resource_capacity_observation")
    elif kind == "arithmetic":terminal["resource_capacity_observation"]["charged_bytes"] += 1
    elif kind == "actor_started":terminal["control_effects"] = "started_reconcile_on_failure"
    elif kind == "launch_attempted":terminal["child_launch_attempted"] = True
    elif kind == "unknown_source":terminal["source_READ_closed"] = False
    else:wait["actual_wait_completed"] = False
    wait["stdout"] = save(stopped["root"] / "refused-terminal.json", terminal)
    stopped["trigger"].update(save(stopped["root"] / "root-wait.json", wait))
    deny_census(monkeypatch)
    with pytest.raises(ValueError):stopped["run"]()
    assert ledger()["reservations"][stopped["rid"]]["status"] == "retained"


@pytest.mark.parametrize("kind", ["no_review", "row_changed", "external_charge", "unknown_process_scope", "controller_changed"])
def test_unreviewed_or_drifted_candidate_refuses_without_mutation(stopped, monkeypatch, kind):
    row = stopped["row"];pre = stopped["pre"];review = stopped["review"]
    if kind == "no_review":review["accepted"] = False
    elif kind == "row_changed":
        current = ledger();current["reservations"][stopped["rid"]]["memory_mb"] += 1;save(cli.CAPACITY_RECOVERY_LEDGER, current)
    elif kind == "external_charge":
        row["external_charges"] = {"outside": 1};pre["selected_record_sha256"] = recovery._digest(row)
        current = ledger();current["reservations"][stopped["rid"]] = row;save(cli.CAPACITY_RECOVERY_LEDGER, current)
    elif kind == "unknown_process_scope":
        row["process_scope"] = "unknown";pre["selected_record_sha256"] = recovery._digest(row)
        current = ledger();current["reservations"][stopped["rid"]] = row;save(cli.CAPACITY_RECOVERY_LEDGER, current)
    else:review["controller"] = {"path": "wrong", "bytes": 1, "sha256": "0" * 64}
    stopped["refresh"]();deny_census(monkeypatch)
    with pytest.raises((ValueError, resources.DaemonResourceError)):stopped["run"]()
    assert ledger()["reservations"][stopped["rid"]]["status"] == "retained"


@pytest.mark.parametrize("kind", ["owner_live", "native_live"])
def test_live_owner_and_native_custody_block_original_api(stopped, monkeypatch, kind):
    row = stopped["row"]; live_lease = None
    try:
        if kind == "owner_live":
            row["owner_pid"] = os.getpid()
        else:
            # Use the real original private broker, never fabricate a native
            # live-owner record. A live lease owned by this process cannot
            # authenticate the retained dead owner's recorded custody.
            live_lease = stopped["scheduler"].acquire(native.ResourceLane.VALIDATION,
                cpu_slots=1, memory_mb=1, child_process_slots=1, timeout=1,
                request_id="validation:" + stopped["rid"])
            row["native_lease_id"] = live_lease.lease_id
            observation = stopped["scheduler"].inspect_lease(live_lease.lease_id,
                expected_request_id="validation:" + stopped["rid"], expected_lane="validation",
                expected_owner_pid=os.getpid(), bounded_lock_timeout=1)
            assert observation["binding_verified"] is True and observation["lease"]["owner_alive"] is True
        stopped["pre"]["selected_record_sha256"] = recovery._digest(row)
        current = ledger(); current["reservations"][stopped["rid"]] = row
        save(cli.CAPACITY_RECOVERY_LEDGER, current); stopped["refresh"](); deny_census(monkeypatch)
        with pytest.raises((ValueError, native.ResourceSchedulerError)):
            stopped["run"]()
        assert ledger()["reservations"][stopped["rid"]]["status"] == "retained"
        if live_lease is not None:
            observation = stopped["scheduler"].inspect_lease(live_lease.lease_id,
                expected_request_id="validation:" + stopped["rid"], expected_lane="validation",
                expected_owner_pid=os.getpid(), bounded_lock_timeout=1)
            assert observation["binding_verified"] is True and observation["lease"]["owner_alive"] is True
    finally:
        if live_lease is not None:
            live_lease.release()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "manifest_changed"])
def test_inventory_alias_or_change_keeps_claim(stopped, kind):
    if kind == "symlink":_legacy_unit_alias_metadata_slot_v1("symlink", stopped["attempt"] / "alias", stopped["attempt"] / "retained.txt")
    elif kind == "hardlink":_legacy_unit_alias_metadata_slot_v1("hardlink", stopped["attempt"] / "alias", stopped["attempt"] / "retained.txt")
    else:(stopped["attempt"] / "retained.txt").write_text("changed")
    try:
        with pytest.raises((ValueError, resources.DaemonResourceError)):stopped["run"]()
        assert ledger()["reservations"][stopped["rid"]]["status"] == "retained"
    finally:
        # Keep the genuine refusal case while restoring ordinary final custody.
        if kind in {"symlink", "hardlink"}:
            (stopped["attempt"] / "alias").unlink()


def test_empty_retained_attempt_is_not_automatically_reconciled(stopped):
    # The failure stays outside the synthetic empty directory; never fabricate an artifact.
    empty = stopped["root"] / "empty";empty.mkdir()
    row = stopped["row"];row["attempt_directory"] = resources._root_identity(empty)
    current = ledger();current["reservations"][stopped["rid"]] = row;save(cli.CAPACITY_RECOVERY_LEDGER, current)
    stopped["pre"]["selected_record_sha256"] = recovery._digest(row);stopped["refresh"]()
    with pytest.raises(ValueError):stopped["run"]()
    assert list(empty.iterdir()) == [] and ledger()["reservations"][stopped["rid"]]["status"] == "retained"


@pytest.mark.parametrize("kind", ["started", "lock_held"])
def test_duplicate_start_marker_and_other_instance_cannot_reconcile(stopped, monkeypatch, kind):
    import fcntl
    if kind == "started":
        key = hashlib.sha256(json.dumps(stopped["trigger"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        save(stopped["state"] / (key + ".operation-started-v01.json"), {"uncertain_original_start": True})
        deny_census(monkeypatch)
        assert stopped["run"]()["status"] == "trigger_already_started"
    else:
        with (stopped["state"] / ".capacity-recovery.lock").open("w") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB);deny_census(monkeypatch)
            assert stopped["run"]()["status"] == "another_cleanup_instance_running"
    assert ledger()["reservations"][stopped["rid"]]["status"] == "retained"


def test_existing_capacity_pressure_is_recorded_without_admission_or_API_retry(stopped, monkeypatch):
    current = ledger(); foreign = deepcopy(stopped["row"])
    foreign.update(reservation_id="d" * 32, storage_bytes=resources.MAX_STORAGE_BYTES)
    current["reservations"][foreign["reservation_id"]] = foreign
    save(cli.CAPACITY_RECOVERY_LEDGER, current)
    before = recovery._durable_inventory(stopped["attempt"])
    native_before = stopped["scheduler_path"].read_bytes()
    result = stopped["run"]()
    assert result["recovery_API_calls"] == 1 and result["recovery_API_returned"] is True
    assert result["postwrite_verification_pending"] is False and result["actual_postwrite_census_verified"] is True
    proof = json.loads(Path(result["postwrite_observation"]["path"]).read_text())
    assert proof["actual_postwrite_accounting"]["capacity_satisfied"] is False
    assert proof["actual_postwrite_accounting"]["over_limit_bytes"] > 0
    assert proof["actual_postwrite_accounting"]["outstanding_full_reservations_bytes"] == foreign["storage_bytes"]
    assert ledger()["reservations"][foreign["reservation_id"]] == foreign
    assert ledger()["reservations"][stopped["rid"]]["status"] == "released"
    assert result["admitted"] is False and result["retry_authorized"] is False
    assert result["fresh_operation_admission_still_required"] is True
    assert recovery._durable_inventory(stopped["attempt"]) == before
    assert stopped["scheduler_path"].read_bytes() == native_before
    deny_census(monkeypatch)
    assert stopped["run"]()["recovery_API_calls"] == 0


@pytest.mark.parametrize("kind", ["api_pin", "roots", "attempt_identity"])
def test_qualified_source_or_physical_scope_drift_refuses(stopped, monkeypatch, kind):
    pre = stopped["pre"]
    if kind == "api_pin":pre["source_api"]["sha256"] = "0" * 64
    elif kind == "roots":pre["roots"] = [str(stopped["root"] / "elsewhere")]
    else:
        row = stopped["row"];row["attempt_directory"]["inode"] += 1
        pre["selected_record_sha256"] = recovery._digest(row)
        current = ledger();current["reservations"][stopped["rid"]] = row
        save(cli.CAPACITY_RECOVERY_LEDGER, current)
    stopped["refresh"]();deny_census(monkeypatch)
    with pytest.raises((ValueError, resources.DaemonResourceError)):stopped["run"]()
    assert ledger()["reservations"][stopped["rid"]]["status"] == "retained"


def test_original_record_CAS_race_is_not_retried(stopped, monkeypatch):
    original = recovery.reconcile_retained_reservation;calls = []
    def concurrent_change(*args, **kwargs):
        calls.append(True)
        current = ledger();current["reservations"][stopped["rid"]]["retention_reason"] = "concurrent_change"
        save(cli.CAPACITY_RECOVERY_LEDGER, current)
        return original(*args, **kwargs)
    monkeypatch.setattr(recovery, "reconcile_retained_reservation", concurrent_change)
    with pytest.raises(resources.DaemonResourceError, match="identity changed"):
        stopped["run"]()
    assert calls == [True] and ledger()["reservations"][stopped["rid"]]["status"] == "retained"
    deny_census(monkeypatch)
    assert stopped["run"]()["status"] == "trigger_already_started" and calls == [True]


def test_cli_rejects_changed_own_source_before_any_source_lease_or_recovery(stopped):
    before = list(stopped["state"].iterdir())
    with pytest.raises(ValueError, match="bytes changed or differ"):
        cli.main(["recover-retained-validation-capacity", "--trigger", json.dumps(stopped["trigger"]),
            "--candidate", json.dumps(stopped["candidate"]), "--state-directory", str(stopped["state"]),
            "--expected-cli-sha256", "0" * 64])
    assert list(stopped["state"].iterdir()) == before


def test_cli_help_is_available_without_native_database_flags(capsys):
    with pytest.raises(SystemExit) as result:
        cli.main(["recover-retained-validation-capacity", "--help"])
    assert result.value.code == 0 and "--resolved-trigger" in capsys.readouterr().out


@pytest.mark.parametrize("failure_point", ["receipt_write", "post_receipt", "API_raise_after_ledger_write"])
def test_post_reconciliation_failure_records_the_actual_attempt_and_blocks_retry(stopped, monkeypatch, failure_point):
    original_api = recovery.reconcile_retained_reservation
    original_put = cli._capacity_recovery_put
    calls = []
    def counted_api(*args, **kwargs):
        calls.append(True)
        receipt = original_api(*args, **kwargs)
        if failure_point == "API_raise_after_ledger_write":
            raise OSError("injected after original ledger reconciliation")
        return receipt
    def failed_receipt(path, value):
        if path.name.endswith(".original-reconciliation-v01.json"):
            if failure_point == "post_receipt":
                original_put(path, value)
            raise OSError("injected original receipt durability/readback failure")
        return original_put(path, value)
    monkeypatch.setattr(recovery, "reconcile_retained_reservation", counted_api)
    if failure_point != "API_raise_after_ledger_write":
        monkeypatch.setattr(cli, "_capacity_recovery_put", failed_receipt)
    before = recovery._durable_inventory(stopped["attempt"])
    with pytest.raises(OSError, match="injected"):
        stopped["run"]()
    assert calls == [True] and ledger()["reservations"][stopped["rid"]]["status"] == "released"
    assert recovery._durable_inventory(stopped["attempt"]) == before
    failure = json.loads(next(stopped["state"].glob("*.operation-failure-v01.json")).read_text())
    returned = failure_point != "API_raise_after_ledger_write"
    assert failure["recovery_API_calls"] == 1 and failure["recovery_API_attempted"] is True
    assert failure["recovery_API_returned"] is returned
    assert failure["recovery_outcome"] == ("returned_unverified" if returned else "call_outcome_uncertain")
    assert failure["automatic_retry_allowed"] is False and failure["manual_outcome_reconciliation_required"] is True
    deny_census(monkeypatch)
    repeated = stopped["run"]()
    assert repeated["status"] == "trigger_already_started" and repeated["recovery_API_calls"] == 0
    assert calls == [True]


# This is a byte copy of the real qualified original owner, never an imported
# replacement, executable fake backend, task action or authority assertion.
_ORIGINAL_WATCH_ACTOR_LOCATOR_DATA_V1 = None
ORIGINAL_WATCH_OWNER = Path("/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/supervisor-programme-v01/current-plan-refresh-v01/native-handoff-acceptance-20261028-v01/asset-inventory-0101-v01/source-preparation-v01/original_native0101_owner_v02.py")


@pytest.fixture
def watched(stopped):
    root = stopped["root"];inbox = root / "frontier";inbox.mkdir(mode=0o700)
    owner = root / "original-qualified-owner.py";owner.write_bytes(ORIGINAL_WATCH_OWNER.read_bytes())
    owner_pin = pin(owner)
    assert owner_pin["sha256"] == "9bb22d26e9ff2160b6171e8cfac0b445bff0585f5051d43fa7d5783b7099b23e"
    owner5 = root / "original-qualified-owner5.py";owner5.write_bytes(ORIGINAL_WATCH_OWNER.with_name("original_native0101_owner_v05.py").read_bytes())
    owner5_pin = pin(owner5)
    assert owner5_pin["sha256"] == "d272357589581a08d875d9d9b0d275fba5776fb06edb6d03791c591073c8508c"
    # Root and independent868 attest the same original owner AST except this
    # ACTOR_PATH literal. Derive exact metadata bytes; never execute its body.
    original = owner.read_bytes()
    old_actor = ("ACTOR_PATH = Path("+repr(_ORIGINAL_WATCH_ACTOR_LOCATOR_DATA_V1)+")").encode()
    new_actor = old_actor.replace(b"native0101_amend_actor_v01.py",b"native0101_completion_actor_v01.py")
    assert original.count(old_actor) == 1
    completion_bytes = original.replace(old_actor,new_actor,1)
    assert hashlib.sha256(completion_bytes).hexdigest() == "82235104f05fe468a789532c59afea779e270594fdc8c5b1e821bb1e79eb72f4"
    completion_owner = root / "original-qualified-completion-owner.py";completion_owner.write_bytes(completion_bytes)
    completion_owner_pin = pin(completion_owner)
    config = dict(schema="legal-ir-retained-capacity-watch-config/v1",
        watched_operations=[dict(root=resources._root_identity(inbox),
            generation_prefixes=["native-amendment-plan-v", "native-documentary-amendment-plan-v", "native-completion-plan-v"],request_filename="request-v01.json")],
        owner_source_pins=[owner_pin,owner5_pin,completion_owner_pin],state_directory=str(stopped["state"]),
        candidates=[stopped["candidate"]],resolved=[])
    config_path = root / "watch-config.json"
    def publish(index=1, kind="capacity", namespace="native"):
        prefix = "native-completion-plan-v" if namespace == "completion" else "native-documentary-amendment-plan-v" if namespace == "documentary" else "native-amendment-plan-v"
        selected_owner = completion_owner_pin if namespace == "completion" else owner5_pin if namespace == "documentary" else owner_pin
        generation = inbox / (prefix + str(index).zfill(2));generation.mkdir(mode=0o700)
        request = json.loads(Path(stopped["wait"]["request"]["path"]).read_text())
        request.update(cwd=str(cli.ROOT),source_sha256={selected_owner["path"]:selected_owner["sha256"]},request_id="fixture-operation-"+str(index))
        if kind == "unknown_owner":request["source_sha256"][selected_owner["path"]] = "0" * 64
        request_pin = save(generation / "request-v01.json", request)
        terminal = deepcopy(stopped["terminal"])
        terminal.update(request_sha256=request_pin["sha256"],owner_pid=stopped["row"]["owner_pid"],
            owner_birth=stopped["row"]["owner_birth"],received_signals=[])
        if kind == "positive":terminal.update(completed=True,control_effects="returned",child_launch_attempted=True)
        elif kind == "noncapacity":terminal.pop("resource_capacity_observation")
        elif kind == "owner_live":terminal["owner_pid"] = os.getpid()
        stdout_pin = save(generation / "root-owner-stdout-v01.log", terminal)
        wait = dict(schema="legal-ir-native0101-documentary-completion-ROOT-actual-wait/v1" if namespace == "completion" else "legal-ir-native0101-documentary-rebind-ROOT-actual-wait/v1" if namespace == "documentary" else "legal-ir-native0101-amendment-ROOT-actual-wait/v1",actual_wait_completed=True,
            exit_code=0 if kind == "positive" else 1,child_pid=terminal["owner_pid"],request=request_pin,stdout=stdout_pin)
        if kind == "owner_pid_mismatch":wait["child_pid"] += 1
        wait_path = generation / "root-actual-wait-v01.json";save(wait_path,wait)
        if kind == "partial":wait_path.write_text('{"actual_wait_completed":')
        return dict(generation=generation,wait=wait,wait_path=wait_path)
    def run():
        config_pin = save(config_path,config)
        with native.resource_cleanup_deadline(native_deadline_monotonic=time.monotonic()+5):
            return cli._watch_retained_validation_capacity(config_pin)
    return dict(stopped=stopped,inbox=inbox,config=config,publish=publish,run=run)


@pytest.mark.parametrize("namespace", ["native", "documentary", "completion"])
def test_watch_observes_a_new_closed_generation_after_idle_and_reconciles_once(watched, monkeypatch, namespace):
    # The same immutable policy discovers a newly published operation; no timer
    # argument or service-file edit is necessary.
    with monkeypatch.context() as temporary:
        deny_census(temporary)
        def forbidden(*args, **kwargs):raise AssertionError("idle watch must not open a disk ledger")
        temporary.setattr(resources.DaemonResourceReservation,"_read",forbidden)
        for _ in range(2):assert watched["run"]()["recovery_API_calls"] == 0
    published = watched["publish"](namespace=namespace)
    before = recovery._durable_inventory(watched["stopped"]["attempt"])
    result = watched["run"]()
    assert result["status"] == "one_reviewed_claim_reconciled" and result["recovery_API_calls"] == 1
    assert ledger()["reservations"][watched["stopped"]["rid"]]["status"] == "released"
    assert recovery._durable_inventory(watched["stopped"]["attempt"]) == before
    assert result["actor_or_provider_or_task_calls"] == 0 and result["retry_authorized"] is False
    deny_census(monkeypatch)
    assert watched["run"]()["recovery_API_calls"] == 0
    assert published["wait_path"].exists()


@pytest.mark.parametrize("kind", ["owner_live", "owner_pid_mismatch", "unknown_owner", "noncapacity", "positive", "partial"])
def test_watch_rejects_unclosed_provenance_or_noncapacity_operations(watched, monkeypatch, kind):
    watched["publish"](kind=kind);deny_census(monkeypatch)
    result = watched["run"]()
    assert result["recovery_API_calls"] == 0 and result["observations"]
    assert ledger()["reservations"][watched["stopped"]["rid"]]["status"] == "retained"
    assert not list(watched["stopped"]["state"].glob("*.operation-started-v01.json"))


@pytest.mark.parametrize("kind", ["root_identity", "wait_outside", "slot_rewrite"])
def test_watch_refuses_root_or_operation_identity_drift(watched, monkeypatch, kind):
    if kind == "root_identity":
        watched["config"]["watched_operations"][0]["root"]["inode"] += 1
    else:
        published = watched["publish"](kind="positive")
        if kind == "wait_outside":published["wait"]["request"] = watched["stopped"]["wait"]["request"]
        else:
            assert watched["run"]()["recovery_API_calls"] == 0
            published["wait"]["recorded_at_utc"] = "rewritten closed operation"
        save(published["wait_path"],published["wait"])
    deny_census(monkeypatch)
    if kind == "root_identity":
        with pytest.raises(ValueError,match="watched root identity"):watched["run"]()
    else:
        result = watched["run"]();assert result["recovery_API_calls"] == 0 and result["observations"]
    assert ledger()["reservations"][watched["stopped"]["rid"]]["status"] == "retained"


def test_watch_immediate_generation_population_is_bounded(watched, monkeypatch):
    for index in range(65):(watched["inbox"] / ("native-amendment-plan-v"+str(index).zfill(2))).mkdir(mode=0o700)
    deny_census(monkeypatch)
    with pytest.raises(ValueError,match="watched generation bound exceeded"):watched["run"]()
    assert ledger()["reservations"][watched["stopped"]["rid"]]["status"] == "retained"


def test_watch_two_closed_operations_can_make_at_most_one_original_API_call_per_tick(watched):
    watched["publish"](1);watched["publish"](2)
    result = watched["run"]()
    assert result["recovery_API_calls"] == 1 and len(result["observations"]) == 1
    assert len(list(watched["stopped"]["state"].glob("*.operation-started-v01.json"))) == 1


def test_watch_refuses_an_aliased_generation_without_census(watched, monkeypatch):
    target = watched["inbox"] / "real-generation";target.mkdir(mode=0o700)
    alias = watched["inbox"] / "native-amendment-plan-v01";_legacy_unit_alias_metadata_slot_v1("symlink", alias, target, directory=True)
    deny_census(monkeypatch)
    try:
        with pytest.raises(resources.DaemonResourceError,match="symlink resource path"):watched["run"]()
        assert ledger()["reservations"][watched["stopped"]["rid"]]["status"] == "retained"
    finally:alias.rmdir()



def test_watch_consumes_authentic_old_manual_resolution_without_any_further_census(watched, monkeypatch):
    stopped = watched["stopped"];published = watched["publish"]();pre = stopped["pre"]
    receipt = recovery.reconcile_retained_reservation(cli.CAPACITY_RECOVERY_LEDGER,
        roots=cli.CAPACITY_RECOVERY_ROOTS,reservation_id=stopped["rid"],
        expected_record_sha256=pre["selected_record_sha256"],attempt_directory=stopped["attempt"],
        expected_artifacts=json.loads(Path(pre["inventory_manifest"]["path"]).read_text())["artifacts"],
        artifacts_durable=True,capacity_policy="require_capacity",artifact_inventory_manifest=pre["inventory_manifest"])
    close = dict(accepted=True,completed=True,source_READ_closed=True,storage_claim_released=True,
        recovery_API_calls=1,capacity_policy="require_capacity",selected_record_sha256=pre["selected_record_sha256"],
        selected_record_after=ledger()["reservations"][stopped["rid"]],inventory_manifest=pre["inventory_manifest"],
        original_reconciliation=save(stopped["root"] / "watched-manual-original.json",receipt),
        trigger_ROOT_failed_0101_reap=pin(published["wait_path"]))
    close_pin = save(stopped["root"] / "watched-manual-closeout.json",close)
    reap_pin = save(stopped["root"] / "watched-manual-genuine-reap.json",dict(completed=True,source_READ_closed=True,
        outer_exec_genuinely_reaped=True,outer_exec_exit_code=0,closeout=close_pin))
    watched["config"]["resolved"] = [dict(closeout=close_pin,genuine_reap=reap_pin)]
    deny_census(monkeypatch)
    result = watched["run"]()
    assert result["recovery_API_calls"] == 0
    assert result["observations"][0]["result"]["status"] == "authenticated_trigger_already_resolved"
    # A second ordinary successful generation is still observed after the old
    # consumed failure; old history cannot stall later frontier inspection.
    watched["publish"](2,kind="positive")
    result = watched["run"]()
    assert result["recovery_API_calls"] == 0 and len(result["observations"]) == 2
    assert result["observations"][1]["status"] == "closed_success_needs_no_capacity_repair"



def test_original_decorated_source_lease_guard_returns_original_without_entering():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_source_lease as module
    path = Path(module.__file__).resolve()
    original = module.source_lease
    assert cli._capacity_recovery_source_lease_v1(module, path) is original
    assert original.__wrapped__.__globals__ is module.__dict__


def test_original_decorated_source_lease_guard_rejects_foreign_body(monkeypatch):
    import contextlib
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_source_lease as module
    entered = []
    @contextlib.contextmanager
    def foreign():
        entered.append(True)
        yield
    monkeypatch.setattr(module, "source_lease", foreign)
    with pytest.raises(ValueError, match="original decorated source lease"):
        cli._capacity_recovery_source_lease_v1(module, Path(module.__file__).resolve())
    assert entered == []


def test_original_decorated_source_lease_guard_rejects_forged_wrapper(monkeypatch):
    import contextlib
    import functools
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_source_lease as module
    original = module.source_lease
    called = []
    @contextlib.contextmanager
    def foreign_delegate(*args, **kwargs):
        called.append(True)
        yield
    forged = foreign_delegate
    functools.update_wrapper(forged, original.__wrapped__)
    assert forged.__wrapped__ is original.__wrapped__
    assert forged.__code__ is original.__code__ and forged.__globals__ is contextlib.__dict__
    assert forged.__closure__[0].cell_contents is not original.__wrapped__
    monkeypatch.setattr(module, "source_lease", forged)
    with pytest.raises(ValueError, match="original decorated source lease"):
        cli._capacity_recovery_source_lease_v1(module, Path(module.__file__).resolve())
    assert called == []



ORIGINAL_METADATA_EXECUTION_OWNER = Path("/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/comprehensive-plan-review-v01/supervisor-dispatch-integration-v01/unblock-work-v01/native-metadata-executor-v01/parent-resource-handoff-candidate-v01/revision-v04/controls/original_native0102_execution_owner_v11.py")


@pytest.fixture
def metadata_watched(watched, monkeypatch):
    root = watched["stopped"]["root"]
    inbox = root / "metadata-frontier";inbox.mkdir(mode=0o700)
    monkeypatch.setattr(cli, "CAPACITY_RECOVERY_METADATA_WATCH_ROOT", inbox)
    owner = root / "original-metadata-execution-owner.py"
    owner.write_bytes(ORIGINAL_METADATA_EXECUTION_OWNER.read_bytes());owner_pin = pin(owner)
    assert owner_pin["sha256"] == cli.CAPACITY_RECOVERY_METADATA_OWNER_SHA256
    driver_pin = pin(cli.CAPACITY_RECOVERY_METADATA_DRIVER)
    assert driver_pin["sha256"] == cli.CAPACITY_RECOVERY_METADATA_DRIVER_SHA256
    watched["config"]["owner_source_pins"].append(owner_pin)
    watched["config"]["watched_operations"].append(dict(root=resources._root_identity(inbox),
        generation_prefixes=["actual-native-execution-v"],request_filename="request-v01.json"))
    def publish(index=1, kind="capacity", deficit=4096):
        namespace = "native-amendment-plan-v" if kind == "wrong_namespace" else "actual-native-execution-v"
        if kind == "wrong_namespace":watched["config"]["watched_operations"][-1]["generation_prefixes"] = [namespace]
        generation = inbox / (namespace+str(index).zfill(2));generation.mkdir(mode=0o700)
        task_cid = cli.CAPACITY_RECOVERY_METADATA_TASK_CID
        cli_argv = ["/home/barberb/lift_coding/.venv/bin/python","-B","-m",
            "ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon",
            "--once","--implement","--task-source-kind","duckdb","--authority-mode","embedded_exclusive",
            "--max-task-attempts","1","--execution-slice-task-id","LIR-0102","--execution-slice-task-cid",task_cid,
            "--native-metadata-execution-task-cid",task_cid,"--native-metadata-execution-task-revision","4"]
        plan = dict(operation="native_metadata_signed_execution_0102_v1",task_cid=task_cid,
            expected_ready_revision=4,source_owner=owner_pin,driver=driver_pin,
            native_metadata_cli=dict(schema="native-metadata-cold-cli/v1",task_cid=task_cid,task_id="LIR-0102",
                expected_revision=4,runtime_root=str(cli.CAPACITY_RECOVERY_METADATA_RUNTIME_ROOT),
                cwd=str(cli.ROOT),cli_argv=cli_argv))
        if kind == "wrong_cid":plan["task_cid"] = "task:unapproved"
        if kind == "wrong_purpose":plan["operation"] = "provider_execution"
        plan_pin = save(generation / "operation-plan.json",plan)
        request = json.loads(Path(watched["stopped"]["wait"]["request"]["path"]).read_text())
        request.update(cwd=str(cli.ROOT),cpu_slots=1,memory_mb=1536,child_process_slots=8,
            storage_bytes=384*1024**2,timeout_seconds=300,
            source_roots=[str(cli.CAPACITY_RECOVERY_METADATA_A_ROOT)],
            source_sha256={owner_pin["path"]:owner_pin["sha256"],driver_pin["path"]:driver_pin["sha256"],plan_pin["path"]:plan_pin["sha256"]},
            argv=["/home/barberb/lift_coding/.venv/bin/python","-B",driver_pin["path"],"--plan",plan_pin["path"],"--plan-sha256",plan_pin["sha256"]])
        if kind == "wrong_driver":request["source_sha256"][driver_pin["path"]] = "0"*64
        if kind == "malformed_argv":request["argv"][4] = None
        if kind == "null_sources":request["source_sha256"] = None
        if kind == "list_sources":request["source_sha256"] = []
        if kind == "wrong_budget":request["storage_bytes"] -= 1
        if kind == "wrong_source_roots":request["source_roots"] = [str(cli.ROOT)]
        request_pin = save(generation / "request-v01.json",request)
        terminal = deepcopy(watched["stopped"]["terminal"])
        terminal.update(request_sha256=request_pin["sha256"],owner_pid=watched["stopped"]["row"]["owner_pid"],
            owner_birth=watched["stopped"]["row"]["owner_birth"],received_signals=[])
        observed = terminal["resource_capacity_observation"]
        observed.update(additional_requested_bytes=request["storage_bytes"],
            charged_bytes=observed["observed_apparent_bytes"]+observed["outstanding_full_reservations_bytes"]+request["storage_bytes"],
            minimum_filesystem_free_bytes=observed["outstanding_full_reservations_bytes"]+request["storage_bytes"]-deficit,
            filesystem_free_deficit_bytes=deficit)
        if kind == "owner_live":terminal["owner_pid"] = os.getpid()
        if kind == "entered":terminal["reservation"].update(record={"status":"retained"},status="retained")
        if kind == "null_reservation":terminal["reservation"] = None
        if kind == "list_reservation":terminal["reservation"] = []
        stdout_pin = save(generation / "root-owner-stdout-v01.log",terminal)
        wait = dict(schema=cli.CAPACITY_RECOVERY_METADATA_WAIT_SCHEMA,actual_wait_completed=True,exit_code=1,
            child_pid=terminal["owner_pid"],request=request_pin,stdout=stdout_pin)
        if kind == "partial":wait["actual_wait_completed"] = False
        if kind == "malformed_schema":wait["schema"] = {"untrusted":"not_a_schema_string"}
        if kind == "null_request_pin":wait["request"] = None
        if kind == "list_stdout_pin":wait["stdout"] = []
        wait_path = generation / "root-actual-wait-v01.json";save(wait_path,wait)
        return dict(generation=generation,request=request,terminal=terminal,wait=wait,wait_path=wait_path)
    return dict(watched=watched,publish=publish,run=watched["run"],owner_pin=owner_pin)


def test_metadata_watch_discovers_current_owner_and_reconciles_once(metadata_watched, monkeypatch):
    watched = metadata_watched["watched"]
    with monkeypatch.context() as idle:
        deny_census(idle)
        idle.setattr(resources.DaemonResourceReservation,"_read",lambda *_:pytest.fail("idle tick opened ledger"))
        assert metadata_watched["run"]()["recovery_API_calls"] == 0
    metadata_watched["publish"]()
    before = recovery._durable_inventory(watched["stopped"]["attempt"])
    result = metadata_watched["run"]()
    assert result["recovery_API_calls"] == 1 and result["actor_or_provider_or_task_calls"] == 0
    assert result["retry_authorized"] is False
    assert ledger()["reservations"][watched["stopped"]["rid"]]["status"] == "released"
    assert recovery._durable_inventory(watched["stopped"]["attempt"]) == before
    deny_census(monkeypatch)
    assert metadata_watched["run"]()["recovery_API_calls"] == 0


def test_metadata_watch_rejects_uncorrected_owner_v04(metadata_watched, monkeypatch):
    watched = metadata_watched["watched"]
    deny_census(monkeypatch)
    for retired in ("6eff67e11a2a5520b1daf164187d4f3de7de513ab46aafc975cf128658b28e58",
                    "bbf996ed9ffc21324284152eaae7c4df7e11fb445bd87d6e3bb91cdf5780a0df"):
        watched["config"]["owner_source_pins"][-1] = dict(metadata_watched["owner_pin"],sha256=retired)
        with pytest.raises(ValueError,match="explicitly qualified original generation"):
            metadata_watched["run"]()
    assert ledger()["reservations"][watched["stopped"]["rid"]]["status"] == "retained"


def test_metadata_watch_rejects_wrong_driver(metadata_watched, monkeypatch):
    deny_census(monkeypatch)
    for index,kind in enumerate(("wrong_driver","malformed_argv","malformed_schema","null_sources","list_sources","null_reservation","list_reservation","null_request_pin","list_stdout_pin"),1):
        metadata_watched["publish"](index,kind=kind)
        result = metadata_watched["run"]()
        assert result["recovery_API_calls"] == 0 and result["observations"]
    assert ledger()["reservations"][metadata_watched["watched"]["stopped"]["rid"]]["status"] == "retained"


def test_metadata_watch_rejects_other_CID_or_purpose(metadata_watched, monkeypatch):
    deny_census(monkeypatch)
    for index,kind in enumerate(("wrong_cid","wrong_purpose"),1):
        metadata_watched["publish"](index,kind=kind)
        result = metadata_watched["run"]()
        assert result["recovery_API_calls"] == 0 and result["observations"]
    assert not list(metadata_watched["watched"]["stopped"]["state"].glob("*.operation-started-v01.json"))


def test_metadata_watch_rejects_wrong_budget_or_source_roots(metadata_watched, monkeypatch):
    deny_census(monkeypatch)
    for index,kind in enumerate(("wrong_budget","wrong_source_roots"),1):
        metadata_watched["publish"](index,kind=kind)
        assert metadata_watched["run"]()["recovery_API_calls"] == 0
    assert not list(metadata_watched["watched"]["stopped"]["state"].glob("*.operation-started-v01.json"))


def test_metadata_watch_rejects_cross_namespace_or_request_locator(metadata_watched, monkeypatch):
    deny_census(monkeypatch)
    first = metadata_watched["publish"](kind="wrong_namespace")
    assert metadata_watched["run"]()["recovery_API_calls"] == 0
    watched = metadata_watched["watched"]
    watched["config"]["watched_operations"][-1]["generation_prefixes"] = ["actual-native-execution-v"]
    second = metadata_watched["publish"](2)
    second["wait"]["request"] = pin(first["generation"] / "request-v01.json")
    save(second["wait_path"],second["wait"])
    assert metadata_watched["run"]()["recovery_API_calls"] == 0


def test_metadata_watch_preserves_live_partial_and_postgrant_unknown(metadata_watched, monkeypatch):
    deny_census(monkeypatch)
    for index,kind in enumerate(("owner_live","partial","entered"),1):
        metadata_watched["publish"](index,kind=kind)
        assert metadata_watched["run"]()["recovery_API_calls"] == 0
    stopped = metadata_watched["watched"]["stopped"]
    assert ledger()["reservations"][stopped["rid"]]["status"] == "retained"
    assert not list(stopped["state"].glob("*.operation-started-v01.json"))


def test_metadata_watch_consumes_manual_resolution_and_preserves_old_family(metadata_watched, monkeypatch):
    watched = metadata_watched["watched"];stopped = watched["stopped"];published = metadata_watched["publish"]();pre = stopped["pre"]
    receipt = recovery.reconcile_retained_reservation(cli.CAPACITY_RECOVERY_LEDGER,
        roots=cli.CAPACITY_RECOVERY_ROOTS,reservation_id=stopped["rid"],
        expected_record_sha256=pre["selected_record_sha256"],attempt_directory=stopped["attempt"],
        expected_artifacts=json.loads(Path(pre["inventory_manifest"]["path"]).read_text())["artifacts"],
        artifacts_durable=True,capacity_policy="require_capacity",artifact_inventory_manifest=pre["inventory_manifest"])
    close = dict(accepted=True,completed=True,source_READ_closed=True,storage_claim_released=True,
        recovery_API_calls=1,capacity_policy="require_capacity",selected_record_sha256=pre["selected_record_sha256"],
        selected_record_after=ledger()["reservations"][stopped["rid"]],inventory_manifest=pre["inventory_manifest"],
        original_reconciliation=save(stopped["root"] / "metadata-manual-original.json",receipt),
        trigger_ROOT_failed_0101_reap=pin(published["wait_path"]))
    close_pin = save(stopped["root"] / "metadata-manual-closeout.json",close)
    reap_pin = save(stopped["root"] / "metadata-manual-genuine-reap.json",dict(completed=True,source_READ_closed=True,
        outer_exec_genuinely_reaped=True,outer_exec_exit_code=0,closeout=close_pin))
    watched["config"]["resolved"] = [dict(closeout=close_pin,genuine_reap=reap_pin)]
    deny_census(monkeypatch)
    result = metadata_watched["run"]()
    assert result["recovery_API_calls"] == 0
    assert result["observations"][0]["result"]["status"] == "authenticated_trigger_already_resolved"
    watched["publish"](2,kind="positive")
    result = metadata_watched["run"]()
    assert result["recovery_API_calls"] == 0
    assert any(row.get("status")=="closed_success_needs_no_capacity_repair" for row in result["observations"])


def test_metadata_watch_cannot_sweep_or_combine_an_insufficient_pool(metadata_watched, monkeypatch):
    stopped = metadata_watched["watched"]["stopped"]
    metadata_watched["publish"](deficit=stopped["row"]["storage_bytes"]+1)
    deny_census(monkeypatch)
    result = metadata_watched["run"]()
    assert result["recovery_API_calls"] == 0
    assert result["observations"][0]["result"]["status"] == "no_sufficient_eligible_reviewed_claim"
    assert ledger()["reservations"][stopped["rid"]]["status"] == "retained"
    assert not list(stopped["state"].glob("*.operation-started-v01.json"))


def metadata_pressure(metadata_watched, monkeypatch):
    """Real private ledger overage; host free-space telemetry remains original."""
    stopped = metadata_watched["watched"]["stopped"]
    row = stopped["row"]; row["storage_bytes"] = 512 * 1024**2
    stopped["pre"].update(selected_record_sha256=recovery._digest(row),
        full_storage_claim_bytes=row["storage_bytes"])
    private_ledger = ledger(); private_ledger["reservations"][stopped["rid"]] = row
    save(cli.CAPACITY_RECOVERY_LEDGER, private_ledger); stopped["refresh"]()
    published = metadata_watched["publish"]()
    observed = resources._inventory(cli.CAPACITY_RECOVERY_ROOTS)["apparent_bytes"]
    # This lower limit exists only in the isolated fixture. No deployed cap,
    # scheduler policy, host disk reading, or admitted reservation is changed.
    monkeypatch.setattr(resources, "MAX_STORAGE_BYTES", row["storage_bytes"] + observed // 2)
    private_ledger["limit_bytes"] = resources.MAX_STORAGE_BYTES
    save(cli.CAPACITY_RECOVERY_LEDGER, private_ledger)
    helper = resources.DaemonResourceReservation(cli.CAPACITY_RECOVERY_LEDGER,
        roots=cli.CAPACITY_RECOVERY_ROOTS, storage_bytes=1, memory_mb=1,
        require_existing_ledger=True, ledger_lock_timeout_seconds=2)
    with pytest.raises(resources.DaemonResourceError, match="storage reservation capacity exceeded") as refused:
        helper._account(ledger(), additional=published["request"]["storage_bytes"])
    published["terminal"]["resource_capacity_observation"] = refused.value._capacity_observation
    published["wait"]["stdout"] = save(published["generation"] / "root-owner-stdout-v01.log", published["terminal"])
    save(published["wait_path"], published["wait"])
    before = recovery._durable_inventory(stopped["attempt"])
    native_before = stopped["scheduler_path"].read_bytes()
    pre = stopped["pre"]
    # The old admission policy refuses even cleanup at an existing overage.
    with native.resource_cleanup_deadline(native_deadline_monotonic=time.monotonic()+5):
        with pytest.raises(resources.DaemonResourceError, match="storage reservation capacity exceeded"):
            recovery.reconcile_retained_reservation(cli.CAPACITY_RECOVERY_LEDGER,
                roots=cli.CAPACITY_RECOVERY_ROOTS, reservation_id=stopped["rid"],
                expected_record_sha256=pre["selected_record_sha256"], attempt_directory=stopped["attempt"],
                expected_artifacts=before, artifacts_durable=True, capacity_policy="require_capacity",
                artifact_inventory_manifest=pre["inventory_manifest"])
    assert ledger()["reservations"][stopped["rid"]] == row
    return stopped, before, native_before


def test_metadata_watch_administrative_closeout_under_real_private_pressure(metadata_watched, monkeypatch):
    stopped, before, native_before = metadata_pressure(metadata_watched, monkeypatch)
    result = metadata_watched["run"]()
    observed = next(row["result"] for row in result["observations"] if row.get("result", {}).get("recovery_API_calls"))
    assert result["recovery_API_calls"] == 1 and observed["recovery_API_returned"] is True
    assert observed["postwrite_verification_pending"] is False and observed["actual_postwrite_census_verified"] is True
    assert observed["fresh_operation_admission_still_required"] is True
    proof = json.loads(Path(observed["postwrite_observation"]["path"]).read_text())
    assert pin(Path(observed["postwrite_observation"]["path"])) == observed["postwrite_observation"]
    assert proof["actual_postwrite_census_verified"] is True and proof["postwrite_verification_pending"] is False
    assert proof["actual_postwrite_accounting"]["outstanding_full_reservations_bytes"] == 0
    assert proof["capacity_policy"] == "administrative_closeout" and proof["limits_changed"] is False
    assert ledger()["reservations"][stopped["rid"]]["status"] == "released"
    assert recovery._durable_inventory(stopped["attempt"]) == before
    assert stopped["scheduler_path"].read_bytes() == native_before
    assert result["actor_or_provider_or_task_calls"] == 0 and result["retry_authorized"] is False
    deny_census(monkeypatch)
    assert metadata_watched["run"]()["recovery_API_calls"] == 0


@pytest.mark.parametrize("refusal", ["census", "attempt_replacement"])
def test_metadata_watch_postwrite_census_refusal_keeps_uncertain_once_state(metadata_watched, monkeypatch, refusal):
    stopped, before, native_before = metadata_pressure(metadata_watched, monkeypatch)
    original = recovery._administrative_census
    calls = []
    def refuse_actual_postwrite(helper, value):
        disk_released = ledger()["reservations"][stopped["rid"]]["status"] == "released"
        calls.append(disk_released)
        if disk_released:
            if refusal == "census":
                raise resources.DaemonResourceError("private actual postwrite census refusal")
            attempt = stopped["attempt"]; prior = stopped["root"] / "original-attempt"
            attempt.rename(prior); attempt.mkdir()
            for artifact in before:
                target = attempt / artifact["path"]; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((prior / artifact["path"]).read_bytes())
            assert recovery._durable_inventory(attempt) == before
            assert resources._root_identity(attempt) != stopped["pre"]["selected_record"]["attempt_directory"]
        return original(helper, value)
    monkeypatch.setattr(recovery, "_administrative_census", refuse_actual_postwrite)
    error_type = resources.DaemonResourceError if refusal == "census" else ValueError
    message = "private actual postwrite census refusal" if refusal == "census" else "attempt identity changed after census"
    with pytest.raises(error_type, match=message):
        metadata_watched["run"]()
    assert calls == [False, False, True]
    failure = json.loads(next(stopped["state"].glob("*.operation-failure-v01.json")).read_text())
    assert failure["recovery_API_calls"] == 1 and failure["recovery_API_returned"] is True
    assert failure["postwrite_verification_pending"] is True
    assert failure["automatic_retry_allowed"] is False and failure["manual_outcome_reconciliation_required"] is True
    assert not list(stopped["state"].glob("*.postwrite-capacity-v01.json"))
    assert ledger()["reservations"][stopped["rid"]]["status"] == "released"
    assert recovery._durable_inventory(stopped["attempt"]) == before
    assert stopped["scheduler_path"].read_bytes() == native_before
    if refusal == "attempt_replacement":
        deny_census(monkeypatch)
        assert metadata_watched["run"]()["recovery_API_calls"] == 0
        assert calls == [False, False, True]
    else:
        with pytest.raises(resources.DaemonResourceError, match="private actual postwrite census refusal"):
            metadata_watched["run"]()
        retry_failure = json.loads(next(stopped["state"].glob("*.postwrite-verification-01-failure-v01.json")).read_text())
        assert retry_failure["recovery_API_calls"] == 0 and retry_failure["postwrite_verification_pending"] is True
        assert calls == [False, False, True, True]


def postwrite_failure_scope(metadata_watched, monkeypatch, *, fail_once=False):
    stopped, before, native_before = metadata_pressure(metadata_watched, monkeypatch)
    original_census = recovery._administrative_census
    original_api = recovery.reconcile_retained_reservation
    census_calls = []; api_calls = []
    def count_api(*args, **kwargs):
        api_calls.append(kwargs["capacity_policy"])
        return original_api(*args, **kwargs)
    def census(helper, value):
        released = ledger()["reservations"][stopped["rid"]]["status"] == "released"
        census_calls.append(released)
        if released and (not fail_once or census_calls.count(True) == 1):
            raise resources.DaemonResourceError("private transient postwrite census refusal")
        return original_census(helper, value)
    monkeypatch.setattr(recovery, "reconcile_retained_reservation", count_api)
    monkeypatch.setattr(recovery, "_administrative_census", census)
    with pytest.raises(resources.DaemonResourceError, match="private transient postwrite census refusal"):
        metadata_watched["run"]()
    assert api_calls == ["administrative_closeout"] and census_calls == [False, False, True]
    return stopped, before, native_before, api_calls, census_calls


def test_metadata_watch_finishes_known_returned_census_once_without_API_replay(metadata_watched, monkeypatch):
    stopped, before, native_before, api_calls, census_calls = postwrite_failure_scope(metadata_watched, monkeypatch, fail_once=True)
    original_failure = next(stopped["state"].glob("*.operation-failure-v01.json")); old_failure = original_failure.read_bytes()
    result = metadata_watched["run"]()
    observed = next(row["result"] for row in result["observations"] if row.get("result", {}).get("postwrite_verification_attempted"))
    assert result["recovery_API_calls"] == observed["recovery_API_calls"] == 0
    assert observed["read_only_postwrite_verification"] is True and observed["verification_attempt"] == 1
    assert observed["actual_postwrite_census_verified"] is True and observed["postwrite_verification_pending"] is False
    assert observed["fresh_operation_admission_still_required"] is True
    assert api_calls == ["administrative_closeout"] and census_calls == [False, False, True, True]
    assert original_failure.read_bytes() == old_failure
    assert recovery._durable_inventory(stopped["attempt"]) == before
    assert stopped["scheduler_path"].read_bytes() == native_before
    deny_census(monkeypatch)
    assert metadata_watched["run"]()["recovery_API_calls"] == 0
    assert api_calls == ["administrative_closeout"] and census_calls == [False, False, True, True]


@pytest.mark.parametrize("kind", ["exhaustion", "interruption"])
def test_metadata_watch_known_returned_verification_budget_stays_finite(metadata_watched, monkeypatch, kind):
    stopped, before, native_before, api_calls, census_calls = postwrite_failure_scope(metadata_watched, monkeypatch)
    if kind == "exhaustion":
        for number in range(1, 4):
            with pytest.raises(resources.DaemonResourceError, match="private transient postwrite census refusal"):
                metadata_watched["run"]()
            failure = json.loads(next(stopped["state"].glob("*.postwrite-verification-"+str(number).zfill(2)+"-failure-v01.json")).read_text())
            assert failure["recovery_API_calls"] == 0 and failure["verification_attempt"] == number
        expected_status = "postwrite_verification_attempts_exhausted"
        assert census_calls == [False, False, True, True, True, True]
    else:
        original_put = cli._capacity_recovery_put
        def interrupt_after_start(path, value):
            result = original_put(path, value)
            if path.name.endswith(".postwrite-verification-01-started-v01.json"):
                raise RuntimeError("private interruption after durable verification intent")
            return result
        with monkeypatch.context() as interrupted:
            interrupted.setattr(cli, "_capacity_recovery_put", interrupt_after_start)
            with pytest.raises(RuntimeError, match="private interruption after durable verification intent"):
                metadata_watched["run"]()
        assert not list(stopped["state"].glob("*.postwrite-verification-01-failure-v01.json"))
        expected_status = "postwrite_verification_interrupted_manual_repair_required"
        assert census_calls == [False, False, True]
    with monkeypatch.context() as no_census:
        deny_census(no_census)
        for _ in range(2):
            result = metadata_watched["run"]()
            observed = next(row["result"] for row in result["observations"] if row.get("result", {}).get("status") == expected_status)
            assert result["recovery_API_calls"] == observed["recovery_API_calls"] == 0
            assert observed["postwrite_verification_pending"] is True and observed["repair_reason"]
    assert api_calls == ["administrative_closeout"]
    assert len(list(stopped["state"].glob("*.postwrite-verification-*-started-v01.json"))) == (3 if kind == "exhaustion" else 1)
    assert recovery._durable_inventory(stopped["attempt"]) == before
    assert stopped["scheduler_path"].read_bytes() == native_before


def test_metadata_watch_invalid_existing_postwrite_proof_stays_pending(metadata_watched, monkeypatch):
    stopped, before, native_before, api_calls, census_calls = postwrite_failure_scope(metadata_watched, monkeypatch)
    started = next(stopped["state"].glob("*.operation-started-v01.json"))
    closed = next(stopped["state"].glob("*.original-reconciliation-v01.json"))
    failed = next(stopped["state"].glob("*.operation-failure-v01.json"))
    immutable = {p: p.read_bytes() for p in (started, closed, failed)}
    proof = started.with_name(started.name.replace(".operation-started-v01.json", ".postwrite-capacity-v01.json"))
    with monkeypatch.context() as no_census:
        deny_census(no_census)
        for invalid in (b"", b"{", b'{"schema":"legal-ir-retained-capacity-actual-postwrite-observation/v1","actual_postwrite_census_verified":true}\n'):
            proof.write_bytes(invalid); proof.chmod(0o600)
            result = metadata_watched["run"]()
            observed = next(row["result"] for row in result["observations"] if row.get("result", {}).get("postwrite_verification_pending"))
            assert result["recovery_API_calls"] == observed["recovery_API_calls"] == 0
            assert "invalid or incomplete postwrite proof" in observed["repair_reason"]
            assert observed["postwrite_verification_pending"] is True
    assert all(p.read_bytes() == value for p, value in immutable.items())
    assert not list(stopped["state"].glob("*.postwrite-verification-*-started-v01.json"))
    assert api_calls == ["administrative_closeout"] and census_calls == [False, False, True]
    assert recovery._durable_inventory(stopped["attempt"]) == before
    assert stopped["scheduler_path"].read_bytes() == native_before


# Focused current-contract regressions: no resource admission or recovery API call.
def test_recovery_command_dispatch_does_not_require_unrelated_native_global_flags(monkeypatch):
    calls = []
    def selected(argv):
        calls.append(argv)
        return 23
    monkeypatch.setattr(cli, "recover_retained_validation_capacity_main_v1", selected)
    monkeypatch.setattr(cli, "parser", lambda: pytest.fail("unrelated native parser reached"))
    argv = ["--watch-config", "{}", "--expected-cli-sha256", "0" * 64]
    assert cli.main(["recover-retained-validation-capacity", *argv]) == 23
    assert calls == [argv]


def test_recovery_stale_cli_pin_refuses_before_source_or_API_without_native_fixture(monkeypatch):
    monkeypatch.setattr(cli, "_capacity_recovery_source_lease_v1",
        lambda *args, **kwargs: pytest.fail("Source lease reached after stale CLI pin"))
    monkeypatch.setattr(cli, "_capacity_recovery_require_api_contract_v1",
        lambda *args, **kwargs: pytest.fail("API preflight reached after stale CLI pin"))
    with pytest.raises(ValueError, match="bytes changed or differ"):
        cli.main(["recover-retained-validation-capacity", "--watch-config", "{}",
            "--expected-cli-sha256", "0" * 64])


def test_current_generic_API_contract_refuses_before_trigger_or_once_marker(tmp_path, monkeypatch):
    import inspect
    signature = inspect.signature(recovery.reconcile_retained_reservation)
    assert "artifact_inventory_manifest" not in signature.parameters
    assert not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values())
    monkeypatch.setattr(cli, "_capacity_recovery_trigger",
        lambda *args, **kwargs: pytest.fail("trigger accessed before API compatibility refusal"))
    monkeypatch.setattr(cli, "_capacity_recovery_put",
        lambda *args, **kwargs: pytest.fail("once-only marker created before API compatibility refusal"))
    with pytest.raises(ValueError, match="API contract unavailable.*artifact_inventory_manifest"):
        cli._recover_retained_validation_capacity({}, [{"preflight": {}, "review": {}}], tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_recovery_CLI_reports_current_API_unavailable_without_repair(monkeypatch, capsys):
    from contextlib import contextmanager
    phases = []
    @contextmanager
    def unit_source_lease(*args, **kwargs):
        # Error-formatting fixture only: this grants no real Source authority.
        phases.append("enter")
        try:
            yield None
        finally:
            phases.append("exit")
    monkeypatch.setattr(cli, "_capacity_recovery_source_lease_v1", lambda *args: unit_source_lease)
    monkeypatch.setattr(cli, "_watch_retained_validation_capacity",
        lambda *args: pytest.fail("watch path reached with unsupported current API"))
    monkeypatch.setattr(cli, "_capacity_recovery_put",
        lambda *args, **kwargs: pytest.fail("repair bookkeeping created on unavailable route"))
    current_sha = hashlib.sha256(Path(cli.__file__).read_bytes()).hexdigest()
    assert cli.main(["recover-retained-validation-capacity", "--watch-config", "{}",
        "--expected-cli-sha256", current_sha]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "capacity_recovery_unavailable"
    assert result["reason_code"] == "recovery_API_contract_unavailable"
    assert result["recovery_API_source"] == pin(Path(recovery.__file__))
    assert result["recovery_API_calls"] == 0
    assert result["operation_started_marker_created"] is False
    assert result["current_policy_or_source_compatibility_verified"] is False
    assert result["new_profile_or_repair_authority"] is False
    assert result["retry_authorized"] is result["admitted"] is result["formalized"] is False
    assert phases == ["enter", "exit"]


@pytest.mark.parametrize("change", ["unknown_profile", "extra_field", "wrong_CLI", "wrong_policy", "empty_candidates"])
def test_current_profile_binding_refuses_before_source_capture_or_any_operation(monkeypatch, change):
    cfg = {"schema": "legal-ir-retained-capacity-watch-config/v2", "profile": cli.CAPACITY_CURRENT_PROFILE,
        "expected_cli_sha256": "a" * 64, "expected_policy_sha256": cli.CAPACITY_CURRENT_POLICY_SHA256,
        "source_capture_ref": {"unused": True}, "state_directory": str(cli.CAPACITY_CURRENT_STATE),
        "root_identities": [], "triggers": [{}], "candidates": [{}]}
    if change == "unknown_profile": cfg["profile"] = "unreviewed-current-profile"
    elif change == "extra_field": cfg["allow_unknown_release"] = True
    elif change == "wrong_CLI": cfg["expected_cli_sha256"] = "b" * 64
    elif change == "wrong_policy": cfg["expected_policy_sha256"] = "b" * 64
    else: cfg["candidates"] = []
    reads = []
    def document(pin):
        reads.append(pin)
        assert len(reads) == 1, "source/candidate data reached after incompatible config"
        return cfg
    monkeypatch.setattr(cli, "_capacity_recovery_json", document)
    monkeypatch.setattr(cli, "_capacity_recovery_put", lambda *args: pytest.fail("operation marker created"))
    with pytest.raises(ValueError):
        cli._capacity_current_config_v1({"declared_unit_config": True}, {"sha256": "a" * 64})
    assert len(reads) == 1


def test_current_typed_API_signature_preflight_accepts_current_shape_without_call(monkeypatch):
    # Signature inspection only; this is not fictional original custody or a recovery.
    import inspect
    calls = []
    original = inspect.signature
    def signatures(function):
        calls.append(function.__name__)
        return original(function)
    monkeypatch.setattr(cli.inspect, "signature", signatures)
    assert cli._capacity_current_api_contract_v1(recovery) is None
    assert calls == ["inspect_sampled_validation_recovery_v1", "reconcile_sampled_validation_reservation_v1",
                     "inspect_validation_disposition"]


@pytest.mark.parametrize("row", [None, {}, {"status": "released"}, {"process_scope": "isolated_process_group_only"}])
def test_current_sampled_candidate_never_promotes_a_no_row_or_legacy_identifier(row):
    # In particular, a pregrant-minted identifier with record=None is no claim.
    with pytest.raises(ValueError, match="explicit retained sampled row required"):
        cli._capacity_current_record_v1(row, "7" * 32, recovery)


def test_current_profile_unknown_once_marker_authorizes_no_second_mutation(tmp_path, monkeypatch):
    started = tmp_path / "started.json";returned = tmp_path / "returned.json"
    trigger = {"declared_unit_journal_key_only": True}
    save(started, {"profile": cli.CAPACITY_CURRENT_PROFILE, "trigger": trigger,
                   "no_automatic_mutation_retry": True})
    before = started.read_bytes()
    monkeypatch.setattr(recovery, "reconcile_sampled_validation_reservation_v1",
        lambda *args, **kwargs: pytest.fail("unknown outcome replayed a mutation"))
    result = cli._capacity_current_unknown_once_state_v1(started, returned, trigger)
    assert result["status"] == "original_outcome_unknown_no_mutation_replay"
    assert result["reconciliation_API_calls"] == 0
    assert result["no_additional_release_authorized"] is True
    assert result["current_ledger_disposition_not_inferred"] is True
    assert result["automatic_mutation_retry"] is result["qualification"] is False
    assert started.read_bytes() == before and not returned.exists()


def test_current_profile_is_explicit_and_keeps_default_historical_route(monkeypatch):
    monkeypatch.setattr(cli, "_capacity_recovery_source_lease_v1",
        lambda *args: pytest.fail("Source reached without required finite watch config"))
    with pytest.raises(ValueError, match="explicit finite v2 watch config"):
        cli.main(["recover-retained-validation-capacity", "--profile", cli.CAPACITY_CURRENT_PROFILE,
            "--trigger", "{}", "--candidate", "{}", "--state-directory", "/unused",
            "--expected-cli-sha256", "0" * 64])


def test_current_profile_unknown_name_refuses_in_its_own_parser(capsys):
    with pytest.raises(SystemExit) as observed:
        cli.main(["recover-retained-validation-capacity", "--profile", "arbitrary-ledger-sweep",
            "--watch-config", "{}", "--expected-cli-sha256", "0" * 64])
    assert observed.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


@pytest.mark.parametrize("case", ["expired", "foreign_boot", "missing_epoch", "raised_budget"])
def test_current_profile_readonly_continuation_cannot_replace_original_clock(case):
    marker = {"original_started_monotonic": 100.0, "original_deadline_monotonic": 340.0,
        "original_boot_id": "unit-boot", "phase": "one_mutation_and_actual_postwrite_verification/v1"}
    now = 350.0 if case == "expired" else 200.0
    if case == "foreign_boot": marker["original_boot_id"] = "other-unit-boot"
    elif case == "missing_epoch": marker.pop("original_deadline_monotonic")
    elif case == "raised_budget": marker["original_deadline_monotonic"] = 341.0
    with pytest.raises(ValueError):
        cli._capacity_current_original_deadline_v1(marker, 600.0, "unit-boot", now)


def test_current_profile_readonly_continuation_uses_remaining_original_epoch_only():
    marker = {"original_started_monotonic": 100.0, "original_deadline_monotonic": 340.0,
        "original_boot_id": "unit-boot", "phase": "one_mutation_and_actual_postwrite_verification/v1"}
    assert cli._capacity_current_original_deadline_v1(marker, 600.0, "unit-boot", 200.0) == 340.0
    assert cli._capacity_current_original_deadline_v1(marker, 300.0, "unit-boot", 200.0) == 300.0



def _declared_unit_pressure_shape_only():
    # This is synthetic PRESSURE DATA with an unqualified producer SHA, not a
    # genuine-custody proof. It is never passed to the evidence wrapper or API.
    request_sha = "a" * 64;producer_sha = "3" * 64;pid = 12345678;birth = 12345
    roots = [str(p) for p in cli.CAPACITY_RECOVERY_ROOTS]
    producer_path = str(cli.ROOT / "scripts/ops/legal_ir/run_owned_validation.py")
    ledger = str(cli.CAPACITY_RECOVERY_LEDGER)
    request = dict(schema="owned-validation-request/v4", cwd=str(cli.ROOT), roots=roots,
        scheduler_state_path=str(cli.CAPACITY_RECOVERY_SCHEDULER_STATE),
        expected_scheduler_policy_sha256=cli.CAPACITY_CURRENT_POLICY_SHA256,
        live_inventory_profile={"schema": "owned-validation-live-census/v1", "max_complete_resamples": 1},
        process_scope="sampled_birth_bound_descendants", declared_external_writable_paths=[],
        storage_bytes=67108864, cpu_slots=1, memory_mb=1536, child_process_slots=2,
        timeout_seconds=120, source_sha256={producer_path: producer_sha})
    cap = dict(schema="daemon-resource-capacity-observation/v1", limit_bytes=220000000000,
        observed_apparent_bytes=220000000000, outstanding_full_reservations_bytes=0,
        additional_requested_bytes=67108864, charged_bytes=220067108864,
        storage_capacity_deficit_bytes=67108864, storage_capacity_exceeded=True)
    life = dict(schema="owned-validation-pre-grant-capacity-refusal/v1",
        stage="owner_open_capacity_refused_before_record", request_sha256=request_sha, ledger_path=ledger,
        native_grant={"status": "not_requested_capacity_refusal"},
        storage={"release_authorized": False, "status": "not_entered"},
        events=dict(barrier_release_attempted=False, barrier_released=False, child_created=False,
            child_launch_attempted=False, owner_open_attempted=True, owner_open_returned=False),
        owner_state=dict(child_attached=False, entered=False, native_lease_created=False, opened=False, record_created=False),
        owner={"pid": pid, "birth": str(birth)},
        source_guards=dict(errors=[], owner_identity_unchanged=True, request_unchanged=True, source_pins_unchanged=True),
        producer={"path": producer_path, "sha256": producer_sha}, capacity_observation=cap)
    terminal = dict(schema="owned-validation-failure-terminal/v1", request_sha256=request_sha,
        completed=False, admitted=False, Lean_admitted=False, process_cleanup_error=None, owner_exit_error=None,
        failure=dict(schema="owned-validation-result/v1", request_sha256=request_sha, error_type="DaemonResourceError",
            error="storage reservation capacity exceeded", returncode=None, executed_checks=[], completed=False,
            admitted=False, Lean_admitted=False, authority_granted=False, model_weights_downloaded=False,
            received_signals=[], watchdog_errors=[]),
        reservation=dict(schema="daemon-resource-reservations-v1", status="not_entered", record=None,
            resource_lease=None, process_observation=None, ledger_path=ledger, scheduler_lane="validation",
            workload="canonical_validation", storage_limit_bytes=220000000000,
            roots=[{"path": p, "device": 1, "inode": i + 1} for i, p in enumerate(roots)]),
        source_custody_lifecycle=life)
    parent = dict(schema="legal-phase8-reviewed-producer-pytest-actual-owner-closeout/v1",
        owner_pid=pid, owner_birth=birth, returncode=1, genuine_wait_completed=True, completed=False,
        source_custody_closed=True, source_READ_closed=True, source_pins_unchanged=True,
        productive_child_never_created=True, tests_executed=False,
        original_native_request_status="not_requested_capacity_refusal",
        actual_preentry_terminal_schema="owned-validation-pre-grant-capacity-refusal/v1",
        original_native_compute_closed=False, native_cleanup_proven=False,
        actual_a0b_terminal_cleanup_verified=False, storage_release_authorized=False,
        actual_preentry_no_native_source_verdict=dict(source_custody_closed=True,
            storage_release_authorized=False, verdict="proven_original_no_child_no_native_grant"))
    return parent, request, terminal, request_sha, producer_sha


def test_declared_unit_pressure_shape_is_only_a_gate_not_candidate_custody():
    parent, request, terminal, request_sha, producer_sha = _declared_unit_pressure_shape_only()
    assert producer_sha not in cli.CAPACITY_CURRENT_PRODUCERS
    assert cli._capacity_current_pregrant_data_gate_v1(parent, request, terminal, request_sha, producer_sha) == 67108864
    assert terminal["reservation"]["record"] is None
    with pytest.raises(ValueError):
        cli._capacity_current_record_v1(None, "7" * 32, recovery)


@pytest.mark.parametrize("case", ["terminal_success", "terminal_admitted", "lease_present", "missing_record",
    "executed_checks", "wrong_failure", "child_created", "integer_event", "wrong_roots", "wrong_ledger",
    "boolean_birth", "boolean_resample", "owner_birth_mismatch", "wrong_policy", "reservation_root", "wrong_arithmetic"])
def test_current_pressure_gate_rejects_contradictory_no_grant_data(case):
    parent, request, terminal, request_sha, producer_sha = _declared_unit_pressure_shape_only()
    life = terminal["source_custody_lifecycle"]
    if case == "terminal_success": terminal["completed"] = True
    elif case == "terminal_admitted": terminal["admitted"] = True
    elif case == "lease_present": terminal["reservation"]["resource_lease"] = {"lease_id": "not-a-no-grant"}
    elif case == "missing_record": terminal["reservation"].pop("record")
    elif case == "executed_checks": terminal["failure"]["executed_checks"] = ["unexpected executed child"]
    elif case == "wrong_failure": terminal["failure"]["error"] = "some unrelated failure"
    elif case == "child_created": life["events"]["child_created"] = True
    elif case == "integer_event": life["events"]["child_created"] = 0
    elif case == "wrong_roots": request["roots"] = ["/unrelated-root"]
    elif case == "wrong_ledger": life["ledger_path"] = "/unrelated-ledger"
    elif case == "boolean_birth": parent["owner_birth"] = True
    elif case == "boolean_resample": request["live_inventory_profile"]["max_complete_resamples"] = True
    elif case == "owner_birth_mismatch": life["owner"]["birth"] = "67890"
    elif case == "wrong_policy": request["expected_scheduler_policy_sha256"] = "b" * 64
    elif case == "reservation_root": terminal["reservation"]["roots"][0]["path"] = "/other-root"
    else: life["capacity_observation"]["charged_bytes"] += 1
    with pytest.raises(ValueError):
        cli._capacity_current_pregrant_data_gate_v1(parent, request, terminal, request_sha, producer_sha)



def _declared_unit_administrative_accounting(charged, outstanding, free=90000000000):
    # Pure accounting fixture only, not a ledger, proof, API or custody premise.
    return dict(observed_apparent_bytes=charged-outstanding,
        outstanding_full_reservations_bytes=outstanding, charged_bytes=charged,
        additional_requested_bytes=0, limit_bytes=220000000000,
        minimum_filesystem_free_bytes=free)


def test_current_partial_recovery_counts_one_full_promise_without_claiming_admission():
    before = cli._capacity_current_pressure_v1(
        _declared_unit_administrative_accounting(220337754068,44774561472),67108864)
    after = cli._capacity_current_pressure_v1(
        _declared_unit_administrative_accounting(220270645204,44707452608),67108864)
    assert before['storage_capacity_deficit_bytes'] == 404862932
    assert after['storage_capacity_deficit_bytes'] == 337754068
    assert before['storage_capacity_deficit_bytes']-after['storage_capacity_deficit_bytes'] == 67108864
    assert before['capacity_satisfied'] is after['capacity_satisfied'] is False
    assert before['admitted'] is after['admitted'] is False
    assert after['cap_changed'] is False and after['fresh_operation_admission_still_required'] is True


def test_current_pressure_observes_idle_without_releasing_a_claim():
    result = cli._capacity_current_pressure_v1(
        _declared_unit_administrative_accounting(219000000000,0),67108864)
    assert result['capacity_satisfied'] is True
    assert result['storage_capacity_deficit_bytes'] == result['filesystem_free_shortfall_bytes'] == 0
    assert result['admitted'] is False


def test_current_pressure_keeps_filesystem_shortfall_even_when_storage_is_under_cap():
    result = cli._capacity_current_pressure_v1(
        _declared_unit_administrative_accounting(219000000000,100000000,free=120000000),67108864)
    assert result['storage_capacity_deficit_bytes'] == 0
    assert result['filesystem_free_shortfall_bytes'] == 47108864
    assert result['capacity_satisfied'] is False


@pytest.mark.parametrize('case',['boolean_request','negative_request','raised_request','boolean_census',
    'nonadministrative_census','raised_cap','contradictory_census'])
def test_current_pressure_refuses_budget_and_census_contradictions(case):
    accounting = _declared_unit_administrative_accounting(220337754068,44774561472)
    request = 67108864
    if case == 'boolean_request': request=True
    elif case == 'negative_request': request=-1
    elif case == 'raised_request': request=67108865
    elif case == 'boolean_census': accounting['minimum_filesystem_free_bytes']=True
    elif case == 'nonadministrative_census': accounting['additional_requested_bytes']=67108864
    elif case == 'raised_cap': accounting['limit_bytes']+=1
    else: accounting['charged_bytes']+=1
    with pytest.raises(ValueError): cli._capacity_current_pressure_v1(accounting,request)


def test_current_claim_once_key_is_stable_independent_of_trigger_config_generation():
    rid='9'*32
    expected=hashlib.sha256(json.dumps({'profile':cli.CAPACITY_CURRENT_PROFILE,'reservation_id':rid},
        sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    assert cli._capacity_current_claim_key_v1(rid) == expected
    assert cli._capacity_current_claim_key_v1('8'*32) != expected


@pytest.mark.parametrize('rid',[None,True,'9'*31,'G'*32])
def test_current_claim_once_key_refuses_nonidentifiers(rid):
    with pytest.raises(ValueError): cli._capacity_current_claim_key_v1(rid)



# Versioned, isolated historical unit inputs. These owners are never imported by
# public product code. Current typed recovery is not qualified by these tests.
_LEGACY_SOURCE_FIXTURE_CASES_V1 = frozenset(['test_duplicate_start_marker_and_other_instance_cannot_reconcile[lock_held]', 'test_duplicate_start_marker_and_other_instance_cannot_reconcile[started]', 'test_existing_capacity_pressure_is_recorded_without_admission_or_API_retry', 'test_inventory_alias_or_change_keeps_claim[hardlink]', 'test_inventory_alias_or_change_keeps_claim[symlink]', 'test_manual_closeout_consumes_trigger_without_census_on_first_or_idle_tick', 'test_metadata_watch_administrative_closeout_under_real_private_pressure', 'test_metadata_watch_cannot_sweep_or_combine_an_insufficient_pool', 'test_metadata_watch_consumes_manual_resolution_and_preserves_old_family', 'test_metadata_watch_discovers_current_owner_and_reconciles_once', 'test_metadata_watch_finishes_known_returned_census_once_without_API_replay', 'test_metadata_watch_invalid_existing_postwrite_proof_stays_pending', 'test_metadata_watch_known_returned_verification_budget_stays_finite[exhaustion]', 'test_metadata_watch_known_returned_verification_budget_stays_finite[interruption]', 'test_metadata_watch_postwrite_census_refusal_keeps_uncertain_once_state[attempt_replacement]', 'test_metadata_watch_postwrite_census_refusal_keeps_uncertain_once_state[census]', 'test_metadata_watch_preserves_live_partial_and_postgrant_unknown', 'test_metadata_watch_rejects_cross_namespace_or_request_locator', 'test_metadata_watch_rejects_other_CID_or_purpose', 'test_metadata_watch_rejects_uncorrected_owner_v04', 'test_metadata_watch_rejects_wrong_budget_or_source_roots', 'test_metadata_watch_rejects_wrong_driver', 'test_one_original_reconciliation_preserves_files_and_second_tick_has_no_call', 'test_original_record_CAS_race_is_not_retried', 'test_post_reconciliation_failure_records_the_actual_attempt_and_blocks_retry[API_raise_after_ledger_write]', 'test_post_reconciliation_failure_records_the_actual_attempt_and_blocks_retry[post_receipt]', 'test_post_reconciliation_failure_records_the_actual_attempt_and_blocks_retry[receipt_write]', 'test_watch_consumes_authentic_old_manual_resolution_without_any_further_census', 'test_watch_observes_a_new_closed_generation_after_idle_and_reconciles_once[completion]', 'test_watch_observes_a_new_closed_generation_after_idle_and_reconciles_once[documentary]', 'test_watch_observes_a_new_closed_generation_after_idle_and_reconciles_once[native]', 'test_watch_refuses_an_aliased_generation_without_census', 'test_watch_two_closed_operations_can_make_at_most_one_original_API_call_per_tick'])
_LEGACY_SOURCE_BUNDLE_SHA256_V1 = 'a96c63426ca4c81c552289e56744e9c5e9f5d3526dc8e08c0cfc88efa87c7e79'
_LEGACY_SOURCE_ROLE_HASHES_V1 = {'legacy_host_4c35': '4c351874ac6725bfdaf43b9e16b1ceba70d283044e9d59a4588c35f83f1142c0', 'legacy_metadata_owner_d710': 'd710d6662795dd6ab5c98fe5d01c3b9f71d29f67d30463ab7ebbf0a4014226d1', 'legacy_recovery_e132': 'e132d4db0cd5cfce0c8f9fb0e047decd45c7370e98d4a77a0a2635014e5bb84e', 'measured_driver_b386_data_only': 'b38692b994349fa478a386a581779110565df3684715f9da4b00fc9e2a7367c2', 'watch_owner_v02_data_only': '9bb22d26e9ff2160b6171e8cfac0b445bff0585f5051d43fa7d5783b7099b23e', 'watch_owner_v05_data_only': 'd272357589581a08d875d9d9b0d275fba5776fb06edb6d03791c591073c8508c'}
_LEGACY_ALIAS_METADATA_CONTEXT_V1 = None


def _load_exact_legacy_unit_source_v1(declaration, name, monkeypatch):
    import importlib.util
    import importlib.machinery
    import sys
    path = Path(declaration['path']);assert pin(path) == declaration
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and isinstance(spec.loader, importlib.machinery.SourceFileLoader)
    module = importlib.util.module_from_spec(spec)
    # Resolve only genuine canonical sibling dependencies through the already
    # loaded package. This private fixture name never replaces sys.modules[D].
    module.__package__ = 'ipfs_datasets_py.optimizers.logic_theorem_optimizer'
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    assert module.__file__ == str(path) and module.__spec__.origin == str(path)
    assert module.__spec__.loader.path == str(path) and pin(path) == declaration
    return module


def _portable_legacy_source_rows_v1(tmp_path):
    bundle_path = Path(__file__).resolve().parents[3] / 'fixtures/retained_capacity_historical_sources_v1.json'
    raw = bundle_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == _LEGACY_SOURCE_BUNDLE_SHA256_V1
    bundle = json.loads(raw)
    assert set(bundle) == {'schema', 'scope', 'sources'}
    assert bundle['schema'] == 'retained-capacity-historical-unit-source-fixtures/v1'
    assert set(bundle['sources']) == set(_LEGACY_SOURCE_ROLE_HASHES_V1)
    folder = tmp_path / 'historical-capacity-unit-inputs';folder.mkdir(mode=0o700)
    rows = {}
    for role, expected in _LEGACY_SOURCE_ROLE_HASHES_V1.items():
        row = bundle['sources'][role]
        assert set(row) == {'bytes','sha256','source_utf8','provenance','data_only',
            'historical_execution_allowed_in_explicit_unit_fixture'}
        body = row['source_utf8'].encode('utf-8')
        assert type(row['bytes']) is int and len(body) == row['bytes']
        assert hashlib.sha256(body).hexdigest() == row['sha256'] == expected
        executable = role in {'legacy_host_4c35','legacy_recovery_e132'}
        assert row['data_only'] is not executable
        assert row['historical_execution_allowed_in_explicit_unit_fixture'] is executable
        assert set(row['provenance']) == {'path','bytes','sha256'}
        assert row['provenance']['bytes'] == row['bytes'] and row['provenance']['sha256'] == expected
        # Provenance locators are retained DATA. Never open workspace history.
        output = folder / (role + '.py')
        with output.open('xb') as stream: stream.write(body)
        output.chmod(0o400)
        rows[role] = pin(output)
    return rows, bundle


@pytest.fixture(autouse=True)
def _versioned_historical_source_for_failed_legacy_cases_v1(request, monkeypatch, tmp_path):
    historical = request.node.name in _LEGACY_SOURCE_FIXTURE_CASES_V1
    watched_data = 'watched' in request.fixturenames
    if not historical and not watched_data:
        yield
        return
    import sys
    import ipfs_datasets_py.optimizers.logic_theorem_optimizer as package
    test_module = sys.modules[__name__]
    rows, bundle = _portable_legacy_source_rows_v1(tmp_path)
    original_host = sys.modules[package.__name__ + '.autoencoder_daemon_resources']
    original_api = sys.modules[package.__name__ + '.autoencoder_resource_recovery']
    canonical_host, canonical_api = pin(Path(original_host.__file__)), pin(Path(original_api.__file__))
    with monkeypatch.context() as scoped:
        if watched_data:
            # Keep the exact DATA bytes and all original assertions for current
            # previously-passing cases; do not change their API/source owner.
            folder = Path(rows['watch_owner_v02_data_only']['path']).parent
            for role, filename in [('watch_owner_v02_data_only','original_native0101_owner_v02.py'),
                ('watch_owner_v05_data_only','original_native0101_owner_v05.py')]:
                target = folder / filename
                target.write_bytes(Path(rows[role]['path']).read_bytes());target.chmod(0o400)
            scoped.setattr(test_module, 'ORIGINAL_WATCH_OWNER', folder/'original_native0101_owner_v02.py')
            actor_locator = str(Path(bundle['sources']['watch_owner_v02_data_only']['provenance']['path'])
                .with_name('native0101_amend_actor_v01.py'))
            scoped.setattr(test_module, '_ORIGINAL_WATCH_ACTOR_LOCATOR_DATA_V1', actor_locator)
            request.node.user_properties.append(('watch_owner_data_scope','portable_exact_v02_v05_DATA_ONLY'))
        alias_metadata = None
        if historical:
            historical_host = _load_exact_legacy_unit_source_v1(rows['legacy_host_4c35'],
                '_legal_ir_capacity_historical_host_fixture_v1', scoped)
            scoped.setattr(package, 'autoencoder_daemon_resources', historical_host)
            historical_api = _load_exact_legacy_unit_source_v1(rows['legacy_recovery_e132'],
                '_legal_ir_capacity_historical_api_fixture_v1', scoped)
            assert historical_api.resources is historical_host
            scoped.setattr(package, 'autoencoder_resource_recovery', historical_api)
            scoped.setattr(test_module, 'resources', historical_host)
            scoped.setattr(test_module, 'recovery', historical_api)
            alias_metadata = dict(monkeypatch=scoped, request=request, observed=0, used=False)
            scoped.setattr(test_module, '_LEGACY_ALIAS_METADATA_CONTEXT_V1', alias_metadata)
            if request.node.name.startswith('test_metadata_watch_'):
                scoped.setattr(test_module, 'ORIGINAL_METADATA_EXECUTION_OWNER',
                    Path(rows['legacy_metadata_owner_d710']['path']))
                # Measuredb386 bytes are only a declared DATA fixture authority;
                # never loaded/executed or represented as missing historical0e897.
                scoped.setattr(cli, 'CAPACITY_RECOVERY_METADATA_DRIVER',
                    Path(rows['measured_driver_b386_data_only']['path']))
                scoped.setattr(cli, 'CAPACITY_RECOVERY_METADATA_DRIVER_SHA256',
                    rows['measured_driver_b386_data_only']['sha256'])
                request.node.user_properties.append(('metadata_driver_fixture_scope',
                    'declared_measured_b386_DATA_ONLY_NOT_ORIGINAL_0e897_OR_EXECUTION'))
            request.node.user_properties.extend([
                ('legacy_source_fixture_profile','exact_e132_4c35_private_unit_only/v1'),
                ('legacy_positive_assertions_exercised',True),
                ('current_typed_or_genuine_custody_coverage',False)])
        try:
            yield
        finally:
            if alias_metadata is not None and alias_metadata['used']:
                assert alias_metadata['observed'] > 0, 'modeled alias metadata never reached a real product guard'
    assert package.autoencoder_daemon_resources is original_host
    assert package.autoencoder_resource_recovery is original_api
    assert sys.modules[package.__name__ + '.autoencoder_daemon_resources'] is original_host
    assert sys.modules[package.__name__ + '.autoencoder_resource_recovery'] is original_api
    assert pin(Path(original_host.__file__)) == canonical_host and pin(Path(original_api.__file__)) == canonical_api


def _legacy_unit_alias_metadata_slot_v1(kind, path, target, *, directory=False):
    """Model only alias metadata; exercise the actual product rejection guard.

    No symlink, hardlink or special file is created. Real-physical-alias
    qualification belongs to its separately admitted owner/cohort.
    """
    import stat
    context = _LEGACY_ALIAS_METADATA_CONTEXT_V1
    assert context is not None and context['request'].node.name in _LEGACY_SOURCE_FIXTURE_CASES_V1
    assert kind in {'symlink', 'hardlink'} and not context['used']
    context['used'] = True
    path = Path(path);target = Path(target)
    if directory: path.mkdir(mode=0o700)
    else: path.write_bytes(target.read_bytes())
    actual = path.stat();original_lstat = Path.lstat;original_fstat = os.fstat
    if kind == 'symlink':
        def declared_lstat(self, *args, **kwargs):
            info = original_lstat(self, *args, **kwargs)
            if self == path:
                context['observed'] += 1;values = list(info)
                values[0] = stat.S_IFLNK | (info.st_mode & 0o7777)
                return os.stat_result(values)
            return info
        context['monkeypatch'].setattr(Path, 'lstat', declared_lstat)
    else:
        def declared_fstat(descriptor):
            info = original_fstat(descriptor)
            if (info.st_dev, info.st_ino) == (actual.st_dev, actual.st_ino):
                context['observed'] += 1;values = list(info);values[3] = 2
                return os.stat_result(values)
            return info
        context['monkeypatch'].setattr(os, 'fstat', declared_fstat)
    context['request'].node.user_properties.extend([
        ('alias_fixture_scope', kind + '_METADATA_MODEL_REAL_PRODUCT_REFUSAL'),
        ('physical_alias_created_or_qualified', False)])

"""Append-only snippets for the existing owning test module; never a runtime.

These test copied request DATA only. The unit sentinel deliberately stops before
the pregrant gate can accept any pressure/custody premise. No genuine-positive
parent, native absence, recovery eligibility or API result is fabricated.
Existing imports, pin/save helpers and cli/resources/recovery bindings are used.
"""


class _StoredRequestUnitReadReached(Exception):
    pass


@pytest.fixture
def stored_request_unit_data(tmp_path, monkeypatch):
    original_directory = tmp_path / "original-operation"
    original_directory.mkdir()
    state = tmp_path / "state"
    bundle = state / "input-bundles/unit-generation"
    bundle.mkdir(parents=True)
    payload = {"fixture": "request-data-only-no-custody-or-pressure-authority"}
    original = tmp_path / "ephemeral-original-request.json"
    original_ref = save(original, payload)
    stored = bundle / "request.json"
    stored.write_bytes(original.read_bytes())
    stored_ref = pin(stored)
    terminal = {"fixture": "terminal-data-only-never-accepted-by-real-pressure-gate"}
    stdout_ref = save(original_directory / "owner.stdout", terminal)
    parent = {"request": original_ref, "original_terminal": terminal}
    parent_ref = save(original_directory / "actual-owner-closeout.json", parent)
    producer = bundle / "unit-producer.txt"
    producer.write_text("unit producer bytes, never compiled or executed\n")
    producer_ref = pin(producer)
    monkeypatch.setattr(cli, "CAPACITY_CURRENT_STATE", state)
    monkeypatch.setattr(cli, "CAPACITY_RECOVERY_ROOTS", (tmp_path,))
    monkeypatch.setattr(cli, "CAPACITY_CURRENT_PRODUCERS", frozenset((producer_ref["sha256"],)))
    reads = []
    actual_reader = cli._checked_job_packet_bytes_v1

    def observed_reader(descriptor):
        reads.append(descriptor["path"])
        return actual_reader(descriptor)

    monkeypatch.setattr(cli, "_checked_job_packet_bytes_v1", observed_reader)

    def no_process_observation(*args, **kwargs):
        raise AssertionError("unit copied-data test must not observe process custody")

    def no_recovery_API(*args, **kwargs):
        raise AssertionError("unit copied-data test must not call a recovery API")

    monkeypatch.setattr(resources, "_process", no_process_observation)
    monkeypatch.setattr(recovery, "inspect_sampled_validation_recovery_v1", no_recovery_API)
    monkeypatch.setattr(recovery, "reconcile_sampled_validation_reservation_v1", no_recovery_API)

    def stop_before_pressure_acceptance(actual_parent, request, actual_terminal,
                                        request_sha256, producer_sha256):
        assert actual_parent == parent
        assert request == payload and actual_terminal == terminal
        assert request_sha256 == original_ref["sha256"]
        assert producer_sha256 == producer_ref["sha256"]
        raise _StoredRequestUnitReadReached("copied bytes read; no pressure or custody accepted")

    monkeypatch.setattr(cli, "_capacity_current_pregrant_data_gate_v1", stop_before_pressure_acceptance)
    declaration = dict(directory=resources._root_identity(original_directory),
        parent_ref=parent_ref, request_ref=original_ref, stdout_ref=stdout_ref,
        producer_ref=producer_ref, stored_request_ref=stored_ref)
    return dict(declaration=declaration, original=original, stored=stored,
        parent=parent, parent_path=original_directory / "actual-owner-closeout.json",
        payload=payload, reads=reads, state=state, tmp_path=tmp_path)


def test_current_stored_request_reads_copy_without_original_or_custody_credit(stored_request_unit_data):
    unit = stored_request_unit_data
    unit["original"].unlink()
    with pytest.raises(_StoredRequestUnitReadReached, match="no pressure or custody accepted"):
        cli._capacity_current_trigger_v1(unit["declaration"], resources, recovery)
    assert str(unit["stored"]) in unit["reads"]
    assert str(unit["original"]) not in unit["reads"]
    assert unit["declaration"]["request_ref"] == unit["parent"]["request"]
    assert not list(unit["state"].glob("*.current-sampled-*-v01.json"))


def test_current_stored_request_five_field_form_keeps_original_reader(stored_request_unit_data):
    unit = stored_request_unit_data
    declaration = dict(unit["declaration"])
    declaration.pop("stored_request_ref")
    with pytest.raises(_StoredRequestUnitReadReached):
        cli._capacity_current_trigger_v1(declaration, resources, recovery)
    assert str(unit["original"]) in unit["reads"]
    assert str(unit["stored"]) not in unit["reads"]


@pytest.mark.parametrize("case", ["extra_trigger_field", "extra_stored_field", "wrong_stored_SHA",
    "wrong_stored_length", "changed_copy_bytes", "outside_input_bundles", "missing_copy",
    "boolean_original_length", "NUL_original_path", "nonabsolute_original_path"])
def test_current_stored_request_refuses_mapping_or_bytes_contradictions(stored_request_unit_data, case):
    unit = stored_request_unit_data
    declaration = deepcopy(unit["declaration"])
    if case == "extra_trigger_field":
        declaration["arbitrary_mapping"] = {}
    elif case == "extra_stored_field":
        declaration["stored_request_ref"]["authority"] = True
    elif case == "wrong_stored_SHA":
        declaration["stored_request_ref"]["sha256"] = "0" * 64
    elif case == "wrong_stored_length":
        declaration["stored_request_ref"]["bytes"] += 1
    elif case == "changed_copy_bytes":
        unit["stored"].write_bytes(b"different copied data\n")
    elif case == "outside_input_bundles":
        outside = unit["tmp_path"] / "outside-input-bundles.json"
        outside.write_bytes(unit["stored"].read_bytes())
        declaration["stored_request_ref"] = pin(outside)
    elif case == "missing_copy":
        unit["stored"].unlink()
    elif case == "boolean_original_length":
        declaration["request_ref"]["bytes"] = True
    elif case == "NUL_original_path":
        declaration["request_ref"]["path"] += "\x00"
    else:
        declaration["request_ref"]["path"] = "relative-original-request.json"
    with pytest.raises((ValueError, OSError)):
        cli._capacity_current_trigger_v1(declaration, resources, recovery)
    assert not list(unit["state"].glob("*.current-sampled-*-v01.json"))


def test_current_stored_request_never_relocates_original_parent_descriptor(stored_request_unit_data):
    unit = stored_request_unit_data
    declaration = deepcopy(unit["declaration"])
    # Payload hash/length are still equal, but historical locator identity differs.
    declaration["request_ref"]["path"] = str(unit["tmp_path"] / "other-original-request.json")
    assert declaration["request_ref"]["sha256"] == unit["parent"]["request"]["sha256"]
    with pytest.raises(ValueError, match="original Root request/stdout byte bindings differ"):
        cli._capacity_current_trigger_v1(declaration, resources, recovery)


# PRIVATE PROPOSAL / UNRUN. Append to the existing capacity-recovery test owner.
# These cases exercise stage routing with private metadata and injected guards.
# They establish no actual Source/Native authority, original producer custody,
# recovery eligibility, storage release, task retry, or admission.


@pytest.fixture
def initial_current_census_scope_v1(tmp_path, monkeypatch):
    import fcntl
    from contextlib import contextmanager
    from types import SimpleNamespace

    root = tmp_path / "initial-current-census-unit"; root.mkdir(mode=0o700)
    state = root / "state"; state.mkdir(mode=0o700)
    ledger_path = root / "ledger.json"
    save(ledger_path, {"reservations": {}})
    lock_path = root / "ledger.json.lock"
    lock_path.write_bytes(b""); lock_path.chmod(0o600)
    preserved = root / "retained-evidence.txt"
    preserved.write_bytes(b"Preserve ordinary outputs and prior operation evidence.\n")
    calls = []; puts = []
    rid = "7" * 32
    entry = {"reservation_id": rid}
    config = {"state_directory": str(state),
        "root_identities": [resources._root_identity(root)],
        "triggers": [{"unit_pressure_metadata_only": True}], "candidates": [entry]}
    deadline = time.monotonic() + 240.0

    def read():
        calls.append("ledger_read")
        return json.loads(ledger_path.read_bytes())

    helper = SimpleNamespace(ledger_path=ledger_path, lock_path=lock_path, ledger_lock_timeout_seconds=0.0,
        roots=(root,), root_identities=[resources._root_identity(root)], _owner_pid=os.getpid(),
        _verify_owner_roots=lambda: calls.append("verify_unit_roots"), _read=read)
    monkeypatch.setattr(cli, "CAPACITY_RECOVERY_LEDGER", root / "ledger.json")
    monkeypatch.setattr(cli, "CAPACITY_RECOVERY_ROOTS", (root,))
    monkeypatch.setattr(cli, "_capacity_current_config_v1", lambda *args: (config, {}))
    monkeypatch.setattr(cli, "_capacity_current_api_contract_v1", lambda *args: None)
    monkeypatch.setattr(cli, "_capacity_current_source_guard_v1", lambda *args: None)
    monkeypatch.setattr(cli, "_capacity_current_trigger_v1", lambda *args: None)
    monkeypatch.setattr(resources, "DaemonResourceReservation", lambda *args, **kwargs: helper)
    monkeypatch.setattr(resources.native_deadlines, "_check_resource_operation_deadline", lambda: None)
    monkeypatch.setattr(resources.native_deadlines, "resource_operation_deadline", lambda: None)

    def census(*args):
        calls.append("administrative_census")
        # Declared arithmetic only. No real global resource census is performed.
        return _declared_unit_administrative_accounting(220000000000, 0)

    monkeypatch.setattr(recovery, "_administrative_census", census)

    def denied_api(name):
        def denied(*args, **kwargs):
            calls.append(name)
            pytest.fail("stage-routing fixture reached a real recovery/readiness/disposition API: " + name)
        return denied

    for name in ("inspect_sampled_validation_recovery_v1",
            "reconcile_sampled_validation_reservation_v1", "inspect_validation_disposition"):
        monkeypatch.setattr(recovery, name, denied_api(name))

    def denied_put(path, value):
        puts.append(path)
        pytest.fail("stage-routing case attempted operation bookkeeping: " + str(path))

    monkeypatch.setattr(cli, "_capacity_recovery_put", denied_put)

    @contextmanager
    def real_private_lock_contention():
        # Independent open descriptions genuinely contend under flock. No
        # process, Native lease, Source lease or canonical ledger is involved.
        descriptor = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(descriptor)

    source_phases = []

    @contextmanager
    def declared_unit_source_scope(*args, **kwargs):
        source_phases.append("enter")
        try:
            yield None
        finally:
            source_phases.append("exit")

    @contextmanager
    def declared_unit_cleanup_scope(*args, **kwargs):
        yield None

    # Error-formatting fixtures only. These never acquire real authority.
    monkeypatch.setattr(cli, "_checked_job_packet_bytes_v1", lambda *args: b"unit-scope-only")
    monkeypatch.setattr(cli, "_capacity_recovery_source_lease_v1",
        lambda *args: declared_unit_source_scope)
    monkeypatch.setattr(native, "resource_cleanup_deadline", declared_unit_cleanup_scope)
    for name in ("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "IPFS_DATASETS_AUTO_INSTALL",
            "IPFS_AUTO_INSTALL", "PYTHONDONTWRITEBYTECODE"):
        monkeypatch.setenv(name, os.environ.get(name, ""))

    def run_watch():
        return cli._watch_current_sampled_validation_capacity_v1(
            {"declared_unit_config_only": True}, {"declared_unit_pin_only": True}, deadline)

    def run_main():
        return cli.main(["recover-retained-validation-capacity", "--profile", cli.CAPACITY_CURRENT_PROFILE,
            "--watch-config", "{}", "--expected-cli-sha256", "0" * 64])

    def journals():
        return {path.name: path.read_bytes() for path in state.glob("*.current-sampled-*.json")}

    def seed_journal(phase):
        key = cli._capacity_current_claim_key_v1(rid)
        started = state / (key + ".current-sampled-started-v01.json")
        returned = state / (key + ".current-sampled-returned-v01.json")
        verified = state / (key + ".current-sampled-verified-v01.json")
        # Journal-shape DATA only; none of these bytes prove an actual mutation.
        save(started, {"profile": cli.CAPACITY_CURRENT_PROFILE, "candidate": entry,
            "trigger": config["triggers"][0], "unit_journal_shape_only": True})
        if phase == "verified":
            save(returned, {"profile": cli.CAPACITY_CURRENT_PROFILE, "candidate": entry,
                "trigger": config["triggers"][0], "mutation_API_calls": 1,
                "unit_journal_shape_only": True})
            save(verified, {"unit_postwrite_proof_shape_only": True})
        return {"started": started, "returned": returned, "verified": verified}[phase]

    return dict(root=root, state=state, helper=helper, config=config, calls=calls, puts=puts,
        preserved=preserved, preserved_before=preserved.read_bytes(), run=run_watch, main=run_main,
        contend=real_private_lock_contention, journals=journals, seed_journal=seed_journal,
        source_phases=source_phases)


def _assert_initial_current_census_deferred_v1(result, scope):
    assert result["status"] == "current_cycle_observation_deferred"
    assert result["reason_code"] == "initial_current_census_lock_unavailable"
    assert result["current_capacity_status"] == "UNKNOWN"
    assert result["readiness_API_calls"] == result["reconciliation_API_calls"] == result["disposition_API_calls"] == 0
    assert result["observations"] == []
    assert result["automatic_mutation_retry"] is False
    assert result["current_operation_journal_must_be_inspected"] is True
    assert result["fresh_operation_admission_still_required"] is True
    assert all(result[key] is False for key in ("admitted", "retry_authorized", "outputs_deleted",
        "native_release_performed", "qualification"))
    assert not {"actual_current_accounting", "actual_current_ledger_metadata",
                "current_pressure_for_blocked_request", "remaining_pressure"} & result.keys()
    # A local zero-call counter cannot establish the absence of earlier markers.
    assert "operation_started_marker_created" not in result
    assert "ledger_read" not in scope["calls"] and "administrative_census" not in scope["calls"]
    assert scope["puts"] == []
    assert scope["preserved"].read_bytes() == scope["preserved_before"]


@pytest.mark.parametrize("prior_unknown_marker", [False, True])
def test_current_initial_census_real_lock_contention_defers_without_claims(
        initial_current_census_scope_v1, prior_unknown_marker):
    scope = initial_current_census_scope_v1
    if prior_unknown_marker:
        scope["seed_journal"]("started")
    before = scope["journals"]()
    with scope["contend"]():
        result = scope["run"]()
    _assert_initial_current_census_deferred_v1(result, scope)
    assert result["source_READ_closed"] is False
    assert scope["journals"]() == before


def test_current_initial_census_real_contention_CLI_returns_deferred_after_Source_exit(
        initial_current_census_scope_v1, capsys):
    scope = initial_current_census_scope_v1
    with scope["contend"]():
        code = scope["main"]()
    result = json.loads(capsys.readouterr().out)
    assert code == 0
    _assert_initial_current_census_deferred_v1(result, scope)
    assert result["source_READ_closed"] is True
    assert scope["source_phases"] == ["enter", "exit"]
    assert scope["journals"]() == {}


@pytest.mark.parametrize("phase", ["ledger_read", "administrative_census"])
def test_current_initial_census_body_same_error_text_remains_unknown(
        initial_current_census_scope_v1, monkeypatch, capsys, phase):
    scope = initial_current_census_scope_v1

    def fail_after_lock_acquired(*args):
        scope["calls"].append("body_failure_" + phase)
        raise resources.DaemonResourceError("inspection ledger lock unavailable")

    if phase == "ledger_read":
        monkeypatch.setattr(scope["helper"], "_read", fail_after_lock_acquired)
    else:
        monkeypatch.setattr(recovery, "_administrative_census", fail_after_lock_acquired)
    assert scope["main"]() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "current_profile_refused_or_original_outcome_unresolved"
    assert result["reconciliation_API_calls"] is None
    assert result["current_operation_journal_must_be_inspected"] is True
    assert result["automatic_mutation_retry"] is result["admitted"] is result["retry_authorized"] is False
    assert result["reason"] == "inspection ledger lock unavailable"
    assert "body_failure_" + phase in scope["calls"]
    assert scope["puts"] == [] and scope["journals"]() == {}
    assert scope["source_phases"] == ["enter", "exit"] and result["source_READ_closed"] is True


def test_current_candidate_same_error_text_stays_unresolved_and_charged(
        initial_current_census_scope_v1, monkeypatch):
    scope = initial_current_census_scope_v1
    entry = scope["config"]["candidates"][0]
    entry.update({name: {} for name in ("record_ref", "proof_ref", "pins_ref", "inventory_ref",
        "parent_ref", "request_ref", "stdout_ref", "producer_ref")})

    def unavailable_candidate_document(*args):
        scope["calls"].append("candidate_document_failure")
        raise resources.DaemonResourceError("inspection ledger lock unavailable")

    monkeypatch.setattr(cli, "_capacity_recovery_json", unavailable_candidate_document)
    result = scope["run"]()
    assert result["status"] == "no_eligible_reviewed_claim_pressure_remains"
    assert result["observations"] == [{"reservation_id": entry["reservation_id"],
        "status": "candidate_unresolved_kept_charged", "reason": "inspection ledger lock unavailable"}]
    assert result["readiness_API_calls"] == result["reconciliation_API_calls"] == result["disposition_API_calls"] == 0
    assert result["admitted"] is result["retry_authorized"] is result["native_release_performed"] is False
    assert "candidate_document_failure" in scope["calls"]
    assert scope["puts"] == [] and scope["journals"]() == {}


@pytest.mark.parametrize("phase", ["started", "verified"])
def test_current_existing_operation_or_postwrite_journal_error_never_becomes_initial_deferral(
        initial_current_census_scope_v1, monkeypatch, capsys, phase):
    scope = initial_current_census_scope_v1
    failing_path = scope["seed_journal"](phase)
    before = scope["journals"]()
    original_read = cli._capacity_recovery_current_json

    def failed_journal_read(path):
        if path == failing_path:
            scope["calls"].append("journal_failure_" + phase)
            raise resources.DaemonResourceError("inspection ledger lock unavailable")
        return original_read(path)

    monkeypatch.setattr(cli, "_capacity_recovery_current_json", failed_journal_read)
    assert scope["main"]() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "current_profile_refused_or_original_outcome_unresolved"
    assert result["reconciliation_API_calls"] is None
    assert result["current_operation_journal_must_be_inspected"] is True
    assert result["automatic_mutation_retry"] is result["admitted"] is result["retry_authorized"] is False
    assert "journal_failure_" + phase in scope["calls"]
    assert scope["puts"] == [] and scope["journals"]() == before
    assert scope["preserved"].read_bytes() == scope["preserved_before"]
    assert scope["source_phases"] == ["enter", "exit"] and result["source_READ_closed"] is True



def test_current_initial_census_modeled_invalid_nlink_refuses_instead_of_deferring(
        initial_current_census_scope_v1, monkeypatch, capsys):
    from types import SimpleNamespace
    scope = initial_current_census_scope_v1
    # MODELED descriptor metadata only, not physical hardlink qualification.
    # Keep the ordinary worker's existing os.link/os.symlink audit denials.
    # The real inspection helper opens the real private lock; alter only its
    # observed nlink for descriptors naming this exact device/inode.
    lock_info = scope["helper"].lock_path.stat()
    assert lock_info.st_nlink == 1
    original_fstat = os.fstat
    faults = []

    def modeled_invalid_nlink(descriptor):
        info = original_fstat(descriptor)
        if (info.st_dev, info.st_ino) != (lock_info.st_dev, lock_info.st_ino):
            return info
        fields = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
        fields["st_nlink"] = 2
        faults.append(descriptor)
        return SimpleNamespace(**fields)

    monkeypatch.setattr(recovery.os, "fstat", modeled_invalid_nlink)
    assert scope["main"]() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "current_profile_refused_or_original_outcome_unresolved"
    assert result["reason"] == "inspection lock must be an unaliased regular file"
    assert len(faults) == 1
    assert scope["helper"].lock_path.stat().st_nlink == 1
    assert result["reconciliation_API_calls"] is None
    assert result["current_operation_journal_must_be_inspected"] is True
    assert result["automatic_mutation_retry"] is result["admitted"] is result["retry_authorized"] is False
    assert "ledger_read" not in scope["calls"] and "administrative_census" not in scope["calls"]
    assert scope["puts"] == [] and scope["journals"]() == {}
    assert scope["preserved"].read_bytes() == scope["preserved_before"]
    assert scope["source_phases"] == ["enter", "exit"] and result["source_READ_closed"] is True


@pytest.fixture
def current_source_read_watchdog_v1(tmp_path, monkeypatch):
    checkout = tmp_path / 'source-lock-repository'
    subprocess.run(['git', 'init', '-q', str(checkout)], check=True, capture_output=True)
    state = tmp_path / 'state'
    state.mkdir()
    journal = state / 'prior.current-sampled-started-v01.json'
    previous_journal = b'{"prior_original_outcome_unknown": true}\n'
    journal.write_bytes(previous_journal)
    monkeypatch.setattr(cli, 'CAPACITY_CURRENT_STATE', state)
    calls = []
    pin_read = cli._checked_job_packet_bytes_v1
    lease_binding = cli._capacity_recovery_source_lease_v1

    def record_pin(descriptor):
        calls.append(('pin', Path(descriptor['path']).name))
        return pin_read(descriptor)

    def private_binding(module, path):
        bound = lease_binding(module, path)

        def open_lease(root, *, mode, timeout_seconds):
            assert root == cli.ROOT and bound is lease.source_lease
            calls.append(('lease', mode, timeout_seconds))
            return bound(checkout, mode=mode, timeout_seconds=timeout_seconds)

        return open_lease

    def observe(config, own_pin, deadline):
        calls.append(('observe', config))
        assert deadline > time.monotonic()
        return {'status': 'idle_current_capacity_satisfied'}

    monkeypatch.setattr(cli, '_checked_job_packet_bytes_v1', record_pin)
    monkeypatch.setattr(cli, '_capacity_recovery_source_lease_v1', private_binding)
    monkeypatch.setattr(cli, '_watch_current_sampled_validation_capacity_v1', observe)
    for name in ('IPFS_DATASETS_PY_MINIMAL_IMPORTS', 'IPFS_DATASETS_AUTO_INSTALL',
                 'IPFS_AUTO_INSTALL', 'PYTHONDONTWRITEBYTECODE'):
        monkeypatch.setenv(name, '1' if name in ('IPFS_DATASETS_PY_MINIMAL_IMPORTS', 'PYTHONDONTWRITEBYTECODE') else '0')

    def run(profile=cli.CAPACITY_CURRENT_PROFILE, config='{}'):
        return cli.main(['recover-retained-validation-capacity', '--profile', profile,
            '--watch-config', config, '--expected-cli-sha256', hashlib.sha256(Path(cli.__file__).read_bytes()).hexdigest()])

    return SimpleNamespace(checkout=checkout, calls=calls, run=run, pin_read=record_pin,
        binding=private_binding, journal=journal, previous_journal=previous_journal)


def _accelerate_source_read_wait_v1(monkeypatch):
    watchdog_thread = threading.get_ident()
    advance = 0

    def monotonic():
        nonlocal advance
        now = time.monotonic()
        if threading.get_ident() == watchdog_thread:
            advance += 31
            return now + advance
        return now

    monkeypatch.setattr(lease, 'time', SimpleNamespace(monotonic=monotonic, sleep=time.sleep))


def _assert_source_read_deferred_v1(result, current_source_read_watchdog_v1):
    assert result['schema'] == 'legal-ir-current-sampled-capacity-watch/v1'
    assert result['profile'] == cli.CAPACITY_CURRENT_PROFILE
    assert result['status'] == 'current_cycle_observation_deferred'
    assert result['reason_code'] == 'initial_source_read_lease_timeout'
    assert result['current_capacity_status'] == 'UNKNOWN'
    assert result['source_READ_acquired'] is result['source_READ_closed'] is False
    assert result['readiness_API_calls'] == result['reconciliation_API_calls'] == result['disposition_API_calls'] == 0
    assert result['observations'] == []
    assert result['current_operation_journal_must_be_inspected'] is True
    assert result['fresh_operation_admission_still_required'] is True
    assert all(result[key] is False for key in ('automatic_mutation_retry', 'admitted',
        'retry_authorized', 'outputs_deleted', 'native_release_performed', 'qualification'))
    assert not {'config_ref', 'operation_started_marker_created', 'actual_current_accounting',
        'current_pressure_for_blocked_request', 'remaining_pressure'} & result.keys()
    assert current_source_read_watchdog_v1.calls == [('pin', 'run_autoformal_supervisor.py'), ('pin', 'autoencoder_source_lease.py'),
        ('lease', 'read', 30)]
    assert current_source_read_watchdog_v1.journal.read_bytes() == current_source_read_watchdog_v1.previous_journal


def test_current_watchdog_defers_behind_real_queued_writer_and_existing_reader(current_source_read_watchdog_v1, monkeypatch, capsys):
    writer_at_source_lock = threading.Event()
    acquire = lease._acquire

    def observe_writer(descriptor, operation, deadline, label):
        if label == 'write':
            writer_at_source_lock.set()
        return acquire(descriptor, operation, deadline, label)

    monkeypatch.setattr(lease, '_acquire', observe_writer)

    def write():
        with lease.source_lease(current_source_read_watchdog_v1.checkout, mode='write', timeout_seconds=5):
            return 'writer acquired after the original reader left'

    with ThreadPoolExecutor(max_workers=1) as pool:
        with lease.source_lease(current_source_read_watchdog_v1.checkout, mode='read', timeout_seconds=0):
            queued_writer = pool.submit(write)
            assert writer_at_source_lock.wait(2)
            with monkeypatch.context() as scoped:
                _accelerate_source_read_wait_v1(scoped)
                assert current_source_read_watchdog_v1.run(config='unparsed-before-source') == 0
            assert not queued_writer.done()
        assert queued_writer.result(timeout=3) == 'writer acquired after the original reader left'
    result = json.loads(capsys.readouterr().out)
    _assert_source_read_deferred_v1(result, current_source_read_watchdog_v1)
    assert result['reason'] == 'timed out waiting for admission source lease'


def test_current_watchdog_defers_when_real_source_write_lease_is_already_held(current_source_read_watchdog_v1, monkeypatch, capsys):
    with lease.source_lease(current_source_read_watchdog_v1.checkout, mode='write', timeout_seconds=0):
        with monkeypatch.context() as scoped:
            _accelerate_source_read_wait_v1(scoped)
            assert current_source_read_watchdog_v1.run() == 0
    result = json.loads(capsys.readouterr().out)
    _assert_source_read_deferred_v1(result, current_source_read_watchdog_v1)
    assert result['reason'] == 'timed out waiting for read source lease'


def test_historical_watchdog_keeps_initial_source_timeout(current_source_read_watchdog_v1, monkeypatch, capsys):
    with lease.source_lease(current_source_read_watchdog_v1.checkout, mode='write', timeout_seconds=0):
        with monkeypatch.context() as scoped:
            _accelerate_source_read_wait_v1(scoped)
            with pytest.raises(lease.SourceLeaseTimeout, match='waiting for read source lease'):
                current_source_read_watchdog_v1.run(profile='historical-metadata-v1')
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('error_type', [TimeoutError, lease.SourceLeaseError])
def test_current_watchdog_keeps_other_initial_errors(current_source_read_watchdog_v1, monkeypatch, capsys, error_type):
    @contextmanager
    def failed_enter(*args, **kwargs):
        raise error_type('timed out waiting for admission source lease')
        yield

    monkeypatch.setattr(cli, '_capacity_recovery_source_lease_v1', lambda *args: failed_enter)
    with pytest.raises(error_type, match='waiting for admission source lease') as caught:
        current_source_read_watchdog_v1.run()
    assert type(caught.value) is error_type
    assert capsys.readouterr().out == ''


def test_current_watchdog_keeps_same_typed_factory_failure(current_source_read_watchdog_v1, monkeypatch, capsys):
    def failed_factory(*args, **kwargs):
        raise lease.SourceLeaseTimeout('modeled factory failure before context entry')

    monkeypatch.setattr(cli, '_capacity_recovery_source_lease_v1', lambda *args: failed_factory)
    with pytest.raises(lease.SourceLeaseTimeout, match='modeled factory failure'):
        current_source_read_watchdog_v1.run()
    assert capsys.readouterr().out == ''


def test_current_watchdog_keeps_same_typed_post_acquisition_pin_failure(current_source_read_watchdog_v1, monkeypatch, capsys):
    def fail_recheck(descriptor):
        if current_source_read_watchdog_v1.calls and current_source_read_watchdog_v1.calls[-1][0] == 'lease':
            raise lease.SourceLeaseTimeout('modeled post-acquisition pin failure')
        return current_source_read_watchdog_v1.pin_read(descriptor)

    monkeypatch.setattr(cli, '_checked_job_packet_bytes_v1', fail_recheck)
    with pytest.raises(lease.SourceLeaseTimeout, match='modeled post-acquisition pin failure'):
        current_source_read_watchdog_v1.run()
    assert capsys.readouterr().out == ''
    with lease.source_lease(current_source_read_watchdog_v1.checkout, mode='write', timeout_seconds=0):
        pass


def test_current_watchdog_keeps_same_typed_body_error_unresolved(current_source_read_watchdog_v1, monkeypatch, capsys):
    def failed_observation(*args):
        raise lease.SourceLeaseTimeout('modeled body failure after Source acquisition')

    monkeypatch.setattr(cli, '_watch_current_sampled_validation_capacity_v1', failed_observation)
    assert current_source_read_watchdog_v1.run() == 2
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'current_profile_refused_or_original_outcome_unresolved'
    assert result['reason'] == 'modeled body failure after Source acquisition'
    assert result['error_type'] == 'SourceLeaseTimeout'
    assert result['reconciliation_API_calls'] is None
    assert result['source_READ_closed'] is True
    assert result['current_operation_journal_must_be_inspected'] is True
    assert result['automatic_mutation_retry'] is False
    assert current_source_read_watchdog_v1.journal.read_bytes() == current_source_read_watchdog_v1.previous_journal


def test_current_watchdog_keeps_same_typed_exit_failure(current_source_read_watchdog_v1, monkeypatch, capsys):
    def closing_binding(module, path):
        open_lease = current_source_read_watchdog_v1.binding(module, path)

        @contextmanager
        def failed_exit(*args, **kwargs):
            with open_lease(*args, **kwargs):
                yield
            raise lease.SourceLeaseTimeout('modeled post-acquisition Source exit failure')

        return failed_exit

    monkeypatch.setattr(cli, '_capacity_recovery_source_lease_v1', closing_binding)
    with pytest.raises(lease.SourceLeaseTimeout, match='Source exit failure'):
        current_source_read_watchdog_v1.run()
    assert ('observe', {}) in current_source_read_watchdog_v1.calls
    assert capsys.readouterr().out == ''


def test_current_watchdog_keeps_normal_read_scope_and_completion(current_source_read_watchdog_v1, capsys):
    assert current_source_read_watchdog_v1.run() == 0
    assert json.loads(capsys.readouterr().out) == {
        'status': 'idle_current_capacity_satisfied', 'source_READ_closed': True,
    }
    assert current_source_read_watchdog_v1.calls == [('pin', 'run_autoformal_supervisor.py'), ('pin', 'autoencoder_source_lease.py'),
        ('lease', 'read', 30), ('pin', 'run_autoformal_supervisor.py'), ('pin', 'autoencoder_source_lease.py'),
        ('observe', {})]
    with lease.source_lease(current_source_read_watchdog_v1.checkout, mode='write', timeout_seconds=0):
        pass


@pytest.mark.parametrize("layout", ["compact", "pretty"])
def test_current_watch_reports_physical_ledger_headroom_during_disk_satisfied_idle(
        initial_current_census_scope_v1, monkeypatch, layout):
    scope = initial_current_census_scope_v1
    path = scope["helper"].ledger_path
    value = {"reservations": {"1" * 32: {"status": "retained"},
                              "2" * 32: {"status": "released"}}}
    raw = (json.dumps(value, sort_keys=True, indent=2 if layout == "pretty" else None)
           + "\n  ").encode()
    path.write_bytes(raw)
    path.chmod(0o660)
    monkeypatch.setattr(resources, "MAX_LEDGER_BYTES", len(raw) + 767)
    monkeypatch.setattr(resources, "MAX_RESERVATIONS", 2)
    monkeypatch.setattr(recovery, "_administrative_census",
        lambda *args: _declared_unit_administrative_accounting(219000000000, 0))
    before = scope["journals"]()
    lock_before = scope["helper"].lock_path.read_bytes()
    result = scope["run"]()
    assert result["status"] == "idle_current_capacity_satisfied"
    assert result["current_pressure_for_blocked_request"]["capacity_satisfied"] is True
    assert path.read_bytes() == raw
    assert scope["journals"]() == before and scope["puts"] == []
    assert result["readiness_API_calls"] == result["reconciliation_API_calls"] == result["disposition_API_calls"] == 0
    metadata = result["actual_current_ledger_metadata"]
    assert metadata == {
        "schema": "current-resource-ledger-metadata-observation/v1",
        "ledger_bytes": len(raw), "ledger_limit_bytes": len(raw) + 767,
        "ledger_headroom_bytes": 767, "reservation_count": 2,
        "reservation_limit": 2, "reservation_headroom": 0,
        "fresh_operation_admission_still_required": True,
    }
    assert scope["helper"].lock_path.read_bytes() == lock_before
    assert all(result[key] is False for key in ("admitted", "retry_authorized",
        "native_release_performed", "qualification"))


def test_current_watch_ledger_mutation_during_census_remains_unresolved(
        initial_current_census_scope_v1, monkeypatch, capsys):
    scope = initial_current_census_scope_v1
    path = scope["helper"].ledger_path
    before = path.read_bytes()

    def changed(*args):
        path.write_bytes(before + b"\n")
        return _declared_unit_administrative_accounting(219000000000, 0)

    monkeypatch.setattr(recovery, "_administrative_census", changed)
    assert scope["main"]() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "current_profile_refused_or_original_outcome_unresolved"
    assert result["reason"] == "current sampled capacity profile: current ledger metadata changed during census"
    assert "actual_current_ledger_metadata" not in result
    assert result["automatic_mutation_retry"] is False
    assert scope["source_phases"] == ["enter", "exit"]
    assert scope["journals"]() == {} and scope["puts"] == []


# Initial observation alone may run its census outside the ledger lock. Every
# admission/recovery/finalization path keeps the original locked owner.
_CENSUS_ORIGINAL_WRITER_CLASS_V1 = resources.DaemonResourceReservation


@pytest.fixture
def detached_initial_census_scope_v1(initial_current_census_scope_v1):
    scope = initial_current_census_scope_v1
    helper = scope["helper"]
    writer = _CENSUS_ORIGINAL_WRITER_CLASS_V1(helper.ledger_path,
        roots=[scope["root"]], storage_bytes=1, memory_mb=1,
        require_existing_ledger=True, ledger_lock_timeout_seconds=0)
    foreign = "8" * 32
    value = dict(schema=resources.SCHEMA, roots=writer.root_identities,
        limit_bytes=resources.MAX_STORAGE_BYTES, reservations={foreign: dict(
            reservation_id=foreign, status="released", owner_pid=1, storage_bytes=1)})
    save(helper.ledger_path, value)
    scope["seed_journal"]("started")
    scope.update(writer=writer, foreign=foreign, initial_ledger=value,
        before_journals=scope["journals"](), before_ordinary=scope["preserved"].read_bytes())
    return scope


def _assert_detached_current_unknown_v1(result, scope, reason):
    assert result["status"] == "current_cycle_observation_deferred"
    assert result["reason_code"] == reason
    assert result["current_capacity_status"] == "UNKNOWN"
    assert result["automatic_mutation_retry"] is False
    assert result["current_operation_journal_must_be_inspected"] is True
    assert result["fresh_operation_admission_still_required"] is True
    assert result["readiness_API_calls"] == result["reconciliation_API_calls"] == result["disposition_API_calls"] == 0
    assert result["observations"] == []
    assert not {"actual_current_accounting", "actual_current_ledger_metadata",
                "current_pressure_for_blocked_request", "remaining_pressure"} & result.keys()
    assert all(result[key] is False for key in ("admitted", "retry_authorized", "outputs_deleted",
        "native_release_performed", "qualification"))
    assert scope["puts"] == [] and scope["journals"]() == scope["before_journals"]
    assert scope["preserved"].read_bytes() == scope["before_ordinary"]
    assert scope["writer"]._entered is False and scope["writer"]._lease is None
    assert scope["writer"]._record is None


def test_current_detached_census_real_original_writer_progress_invalidates_observation(
        detached_initial_census_scope_v1, monkeypatch):
    scope = detached_initial_census_scope_v1
    entered, resume = threading.Event(), threading.Event()
    original = recovery._administrative_census
    phases = []

    def write(phase):
        before = scope["helper"].ledger_path.stat()
        with scope["writer"]._locked():
            current = scope["writer"]._read()
            scope["writer"]._write(current)
        after = scope["helper"].ledger_path.stat()
        assert before.st_ino != after.st_ino
        phases.append(phase)

    write("before_watch")

    def paused(owner, ledger):
        entered.set()
        assert resume.wait(5), "finite census fixture was not resumed"
        return original(owner, ledger)

    monkeypatch.setattr(recovery, "_administrative_census", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        watch = pool.submit(scope["run"])
        try:
            assert entered.wait(5)
            write("while_census_paused")
        finally:
            resume.set()
        result = watch.result(timeout=5)
    write("after_watch")
    assert phases == ["before_watch", "while_census_paused", "after_watch"]
    _assert_detached_current_unknown_v1(result, scope, "current_census_snapshot_changed")


@pytest.mark.parametrize("layout", ["compact", "pretty"])
def test_current_detached_census_unchanged_snapshot_preserves_observation_and_unknown(
        detached_initial_census_scope_v1, monkeypatch, layout):
    scope = detached_initial_census_scope_v1
    helper = scope["helper"]
    raw = (json.dumps(scope["initial_ledger"], sort_keys=True,
        indent=2 if layout == "pretty" else None) + "\n  ").encode()
    helper.ledger_path.write_bytes(raw)
    before = helper.ledger_path.stat()
    result = scope["run"]()
    after = helper.ledger_path.stat()
    assert result["status"] == "no_eligible_reviewed_claim_pressure_remains"
    assert result["actual_current_ledger_metadata"]["ledger_bytes"] == len(raw)
    assert result["actual_current_ledger_metadata"]["reservation_count"] == 1
    assert result["current_pressure_for_blocked_request"]["capacity_satisfied"] is False
    assert result["actual_current_accounting"]["charged_bytes"] == 220000000000
    assert result["observations"] == [dict(reservation_id="7" * 32,
        status="original_outcome_unknown_no_mutation_replay",
        current_ledger_disposition_not_inferred=True, automatic_mutation_retry=False)]
    assert result["readiness_API_calls"] == result["reconciliation_API_calls"] == result["disposition_API_calls"] == 0
    assert helper.ledger_path.read_bytes() == raw
    assert before.st_ino == after.st_ino and before.st_mtime_ns == after.st_mtime_ns
    assert scope["journals"]() == scope["before_journals"] and scope["puts"] == []


@pytest.mark.parametrize("change", ["foreign-row", "same-size", "format-only", "same-content-inode"])
def test_current_detached_census_atomic_writer_generation_change_discards_metrics(
        detached_initial_census_scope_v1, monkeypatch, change):
    scope = detached_initial_census_scope_v1
    path = scope["helper"].ledger_path
    if change == "same-size":
        with scope["writer"]._locked():
            scope["writer"]._write(scope["writer"]._read())
    raw = path.read_bytes()
    original = recovery._administrative_census

    def changed(owner, ledger):
        with scope["writer"]._locked():
            current = scope["writer"]._read()
            if change in {"foreign-row", "same-size"}:
                current["reservations"][scope["foreign"]]["owner_pid"] = 2
            scope["writer"]._write(current)
        if change == "same-size":
            assert len(path.read_bytes()) == len(raw) and path.read_bytes() != raw
        elif change == "format-only":
            assert json.loads(path.read_bytes()) == json.loads(raw) and path.read_bytes() != raw
        elif change == "same-content-inode":
            # The first writer normalizes formatting; a second original write
            # preserves those normalized bytes while still replacing the inode.
            normalized = path.read_bytes()
            inode = path.stat().st_ino
            with scope["writer"]._locked():
                scope["writer"]._write(scope["writer"]._read())
            assert path.read_bytes() == normalized and path.stat().st_ino != inode
        return original(owner, ledger)

    monkeypatch.setattr(recovery, "_administrative_census", changed)
    result = scope["run"]()
    _assert_detached_current_unknown_v1(result, scope, "current_census_snapshot_changed")


def test_current_detached_census_mutated_detached_input_discards_metrics(
        detached_initial_census_scope_v1, monkeypatch):
    scope = detached_initial_census_scope_v1
    raw = scope["helper"].ledger_path.read_bytes()
    original = recovery._administrative_census

    def changed(owner, ledger):
        ledger["reservations"][scope["foreign"]]["storage_bytes"] = 2
        return original(owner, ledger)

    monkeypatch.setattr(recovery, "_administrative_census", changed)
    result = scope["run"]()
    assert scope["helper"].ledger_path.read_bytes() == raw
    _assert_detached_current_unknown_v1(result, scope, "current_census_snapshot_changed")


def test_current_detached_census_real_final_lock_contention_discards_metrics(
        detached_initial_census_scope_v1, monkeypatch):
    scope = detached_initial_census_scope_v1
    original = recovery._administrative_census
    held = []

    def final_writer(owner, ledger):
        context = scope["writer"]._locked()
        context.__enter__()
        held.append(context)
        return original(owner, ledger)

    monkeypatch.setattr(recovery, "_administrative_census", final_writer)
    try:
        result = scope["run"]()
    finally:
        for context in held:
            context.__exit__(None, None, None)
    assert len(held) == 1
    _assert_detached_current_unknown_v1(result, scope, "final_current_census_lock_unavailable")


def test_current_detached_census_original_absolute_deadline_is_not_refreshed(
        detached_initial_census_scope_v1, monkeypatch):
    scope = detached_initial_census_scope_v1
    original = recovery._administrative_census
    deadline = time.monotonic() + .025

    def exhausted(owner, ledger):
        threading.Event().wait(.05)
        return original(owner, ledger)

    monkeypatch.setattr(recovery, "_administrative_census", exhausted)
    with pytest.raises(ValueError, match="original absolute240 cleanup deadline exhausted"):
        cli._watch_current_sampled_validation_capacity_v1(
            {"declared_unit_config_only": True}, {"declared_unit_pin_only": True}, deadline)
    assert scope["puts"] == [] and scope["journals"]() == scope["before_journals"]


@pytest.mark.parametrize("body_phase", ["census", "final-ledger-read"])
def test_current_detached_census_same_text_body_timeout_remains_unresolved(
        detached_initial_census_scope_v1, monkeypatch, capsys, body_phase):
    scope = detached_initial_census_scope_v1

    def fail(*args):
        raise recovery._ValidationInspectionLockTimeout("inspection ledger lock unavailable")

    if body_phase == "census":
        monkeypatch.setattr(recovery, "_administrative_census", fail)
    else:
        original = scope["helper"]._read
        reads = []

        def fail_second_read():
            reads.append(True)
            if len(reads) == 2:
                fail()
            return original()

        monkeypatch.setattr(scope["helper"], "_read", fail_second_read)
    assert scope["main"]() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "current_profile_refused_or_original_outcome_unresolved"
    assert "actual_current_accounting" not in result and "actual_current_ledger_metadata" not in result
    assert result["automatic_mutation_retry"] is False
    assert scope["puts"] == [] and scope["journals"]() == scope["before_journals"]


@pytest.mark.parametrize("replacement", ["root", "lock"])
def test_current_detached_census_root_or_original_lock_replacement_discards_metrics(
        detached_initial_census_scope_v1, monkeypatch, replacement):
    import shutil
    scope = detached_initial_census_scope_v1
    original = recovery._administrative_census
    backup = scope["root"].with_name(scope["root"].name + "-original")
    saved_lock = scope["helper"].lock_path.with_name("saved-original-ledger.lock")

    def replaced(owner, ledger):
        if replacement == "root":
            scope["root"].rename(backup)
            shutil.copytree(backup, scope["root"])
        else:
            scope["helper"].lock_path.rename(saved_lock)
            scope["helper"].lock_path.write_bytes(b"")
            scope["helper"].lock_path.chmod(0o600)
        return original(owner, ledger)

    monkeypatch.setattr(recovery, "_administrative_census", replaced)
    try:
        result = scope["run"]()
    finally:
        if backup.exists():
            shutil.rmtree(scope["root"])
            backup.rename(scope["root"])
        if saved_lock.exists():
            scope["helper"].lock_path.unlink()
            saved_lock.rename(scope["helper"].lock_path)
    _assert_detached_current_unknown_v1(result, scope, "current_census_snapshot_changed")


@pytest.mark.parametrize("outcome", ["success", "changed", "final-lock", "deadline"])
def test_current_detached_census_restores_entry_lock_timeout_on_every_exit(
        detached_initial_census_scope_v1, monkeypatch, outcome):
    scope = detached_initial_census_scope_v1
    helper = scope["helper"]
    entry_timeout = .5
    helper.ledger_lock_timeout_seconds = entry_timeout
    original = recovery._administrative_census
    held = []

    def control(owner, ledger):
        if outcome == "changed":
            with scope["writer"]._locked():
                scope["writer"]._write(scope["writer"]._read())
        elif outcome == "final-lock":
            context = scope["writer"]._locked()
            context.__enter__()
            held.append(context)
        elif outcome == "deadline":
            threading.Event().wait(.05)
        return original(owner, ledger)

    monkeypatch.setattr(recovery, "_administrative_census", control)
    original_deadline = time.monotonic() + .025
    try:
        if outcome == "deadline":
            with pytest.raises(ValueError, match="original absolute240 cleanup deadline exhausted"):
                cli._watch_current_sampled_validation_capacity_v1(
                    {"declared_unit_config_only": True}, {"declared_unit_pin_only": True}, original_deadline)
        else:
            result = cli._watch_current_sampled_validation_capacity_v1(
                {"declared_unit_config_only": True}, {"declared_unit_pin_only": True}, original_deadline)
            if outcome == "success":
                assert result["status"] == "no_eligible_reviewed_claim_pressure_remains"
            else:
                _assert_detached_current_unknown_v1(result, scope,
                    "final_current_census_lock_unavailable" if outcome == "final-lock"
                    else "current_census_snapshot_changed")
    finally:
        for context in held:
            context.__exit__(None, None, None)
    assert helper.ledger_lock_timeout_seconds == entry_timeout
    assert scope["puts"] == [] and scope["journals"]() == scope["before_journals"]


# Exact private API-pin successor controls. These are Source29-shaped unit DATA
# declarations only; they neither acquire Source nor establish current custody.
@pytest.fixture
def current_API_pin_Source29_unit_data_v1(tmp_path, monkeypatch):
    root = cli.ROOT
    module_names = (
        "__init__.py", "optimizers/__init__.py",
        "optimizers/logic_theorem_optimizer/__init__.py", "router_deps.py",
        "optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py",
        "optimizers/logic_theorem_optimizer/autoencoder_resource_recovery.py",
        "optimizers/logic_theorem_optimizer/autoencoder_source_lease.py",
        "optimizers/logic_theorem_optimizer/existing_resource_scheduler.py",
        "optimizers/logic_theorem_optimizer/proof_resource_safety.py",
        "optimizers/logic_theorem_optimizer/resource_scheduler.py",
        "optimizers/logic_theorem_optimizer/runtime_telemetry.py",
    )
    instruction_directories = (Path("/"), Path("/home"), Path("/home/barberb"),
        root.parent.parent, root.parent, root, root / "ipfs_datasets_py",
        root / "ipfs_datasets_py/logic", root / "ipfs_datasets_py/logic/autoformal",
        root / "ipfs_datasets_py/optimizers",
        root / "ipfs_datasets_py/optimizers/logic_theorem_optimizer",
        root / "scripts", root / "scripts/ops", root / "scripts/ops/legal_ir",
        root / "tests", root / "tests/unit", root / "tests/unit/optimizers",
        root / "tests/unit/optimizers/logic_theorem_optimizer")
    files = [dict(kind="file", path=str(root / "ipfs_datasets_py" / name),
                  source_ref=pin(root / "ipfs_datasets_py" / name))
             for name in module_names]
    capture = dict(schema="legacy-ec90-current-Source29-capture/v1",
        completed=True, Source_closed=True, Source_absolute3s_satisfied=True,
        Source_window_renewed=False, all_pre_post_full9_bytes_modes_stable=True,
        errors=[], Source_seconds=0.01, files=files,
        absences=[dict(kind="absent", path=str(folder / "AGENTS.md"))
                  for folder in instruction_directories])
    capture_path = tmp_path / "declared-Source29-DATA.json"
    config_path = tmp_path / "declared-watch-config-DATA.json"
    capture_ref = save(capture_path, capture)
    own_pin = pin(Path(cli.__file__))
    config = dict(schema="legal-ir-retained-capacity-watch-config/v2",
        profile=cli.CAPACITY_CURRENT_PROFILE, expected_cli_sha256=own_pin["sha256"],
        expected_policy_sha256=cli.CAPACITY_CURRENT_POLICY_SHA256,
        source_capture_ref=capture_ref, state_directory=str(cli.CAPACITY_CURRENT_STATE),
        root_identities=[], triggers=[dict(unit_DATA_only=True)],
        candidates=[dict(unit_DATA_only=True)])
    api_path = str(root / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_resource_recovery.py")
    assert len(files) == 11 and len(capture["absences"]) == 18

    def forbidden(*args, **kwargs):
        pytest.fail("Source29 API-pin DATA test reached Source/runtime owner/API/journal")

    monkeypatch.setattr(cli, "_capacity_current_source_guard_v1", forbidden)
    monkeypatch.setattr(cli, "_capacity_recovery_source_lease_v1", forbidden)
    monkeypatch.setattr(cli, "_capacity_recovery_put", forbidden)
    monkeypatch.setattr(resources, "DaemonResourceReservation", forbidden)
    monkeypatch.setattr(recovery, "inspect_sampled_validation_recovery_v1", forbidden)
    monkeypatch.setattr(recovery, "reconcile_sampled_validation_reservation_v1", forbidden)
    return dict(capture=capture, capture_path=capture_path, config=config,
        config_path=config_path, own_pin=own_pin, api_path=api_path)


@pytest.mark.parametrize("pin_generation", ["current_product", "previous_a5fc", "unknown"])
def test_current_API_pin_Source29_parser_binds_selected_recovery_generation(
        current_API_pin_Source29_unit_data_v1, pin_generation):
    unit = current_API_pin_Source29_unit_data_v1
    api = next(row for row in unit["capture"]["files"] if row["path"] == unit["api_path"])
    if pin_generation == "previous_a5fc":
        api["source_ref"]["sha256"] = "a5fcf80c976095350fbd07ed820da5161230a25063662d2b15ea8756c016313a"
    elif pin_generation == "unknown":
        api["source_ref"]["sha256"] = "f" * 64
    unit["config"]["source_capture_ref"] = save(unit["capture_path"], unit["capture"])
    config_ref = save(unit["config_path"], unit["config"])
    before = {path.name: path.read_bytes() for path in unit["config_path"].parent.iterdir()
              if path.is_file()}
    if pin_generation == "current_product":
        actual, guards = cli._capacity_current_config_v1(config_ref, unit["own_pin"])
        assert actual == unit["config"]
        assert len(guards) == 29
        assert next(row for row in guards if row["path"] == unit["api_path"]) == api
    else:
        with pytest.raises(ValueError, match="current typed API source generation differs"):
            cli._capacity_current_config_v1(config_ref, unit["own_pin"])
    assert {path.name: path.read_bytes() for path in unit["config_path"].parent.iterdir()
            if path.is_file()} == before


# Explicit automatic-completed routing UNIT_DATA. Captured producers are DATA
# only; all scheduler/ledger/process observations below stay in test-local roots.
@pytest.fixture(scope='session')
def auto_completed_captured_producers_v1(tmp_path_factory):
    folder = tmp_path_factory.mktemp('auto-completed-captured-producer-DATA', numbered=False)
    captured = {}
    def retain(raw):
        digest = hashlib.sha256(raw).hexdigest()
        if digest not in captured:
            path = folder / (digest + '.pydata')
            with path.open('xb') as stream:
                stream.write(raw)
            path.chmod(0o600)
            captured[digest] = pin(path)
        assert Path(captured[digest]['path']).read_bytes() == raw
        return dict(captured[digest])
    return retain


@pytest.fixture(autouse=True)
def _auto_completed_closed_unit_proof_storage_v1(request):
    if not request.node.name.startswith('test_auto_completed_'):
        yield
        return
    scratch = request.getfixturevalue('tmp_path')
    try:
        yield
    finally:
        from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_resource_recovery as unit
        unit._completed_watchdog_archive_closed_proof_data(scratch, request.node.nodeid)


@pytest.fixture
def auto_completed_setup_v1(tmp_path, monkeypatch):
    from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_daemon_resources as unit
    # The original fixture owns a real local scheduler. Invoke its undecorated
    # fixture body directly; no host scheduler or Native resource is requested.
    return unit.setup.__wrapped__(tmp_path, monkeypatch)


def _auto_completed_case_v1(setup, monkeypatch, captured, *, pair='280-11e', large=False):
    from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_resource_recovery as unit
    case = unit._completed_watchdog_unit_case(setup, monkeypatch, large_population=large,
        owner_pair=pair, subject_pair='269-4df' if pair == '280-11e' else '280-11e')
    canonical, _ = case['manual_unit_roots']
    suffix = 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py'
    case['request']['source_sha256'][str(canonical / suffix)] = '3d11147bbaa9bba35dadda391baa074fefd2ad9c851fff3a5fe2ed9542a072e3'
    case['terminal']['reservation']['storage_limit_bytes'] = 220_000_000_000
    monkeypatch.setattr(resources, 'MAX_STORAGE_BYTES', 250_000_000_000)
    data = json.loads(case['ledger'].read_bytes())
    claims = unit._sampled_copy(data['reservations'])
    data['limit_bytes'] = 250_000_000_000
    case['ledger'].write_text(json.dumps(data))
    assert json.loads(case['ledger'].read_bytes())['reservations'] == claims
    unit._completed_watchdog_reseal_unit_data(case)
    monkeypatch.setattr(cli, 'CAPACITY_RECOVERY_ROOTS', tuple(case['args']['roots']))
    monkeypatch.setattr(cli, 'CAPACITY_RECOVERY_LEDGER', case['ledger'])
    monkeypatch.setattr(cli, 'CAPACITY_CURRENT_POLICY_SHA256', case['request']['expected_scheduler_policy_sha256'])
    case['auto_unit'] = unit
    case['auto_captured'] = captured
    return case


def _auto_completed_entry_v1(case):
    unit = case['auto_unit']
    folder = case['args']['roots'][1] / 'automatic-completed-original-DATA'
    folder.mkdir(exist_ok=True)
    def raw(name, body):
        path = folder / name
        path.write_bytes(body)
        path.chmod(0o600)
        return pin(path)
    args, proof = case['completed_args'], case['proof']
    pins = {key: args[key] for key in ('expected_record_sha256', 'expected_producer_sha256',
        'expected_request_sha256', 'expected_parent_closeout_sha256', 'expected_stdout_sha256',
        'expected_terminal_sha256')}
    pins.update(proof_sha256=args['expected_proof_sha256'], historical_evidence_selected_by_caller=True,
        cryptographic_execution_attestation=False, reconstructed_Popen_handle=False)
    return dict(reservation_id=args['reservation_id'],
        recovery_profile=cli.CAPACITY_COMPLETED_RECOVERY_PROFILE,
        record_ref=save(folder / 'record.json', case['row']),
        proof_ref=dict(args['evidence_archive']), inventory_ref=dict(args['artifact_inventory_manifest']),
        pins_ref=save(folder / 'pins.json', pins),
        parent_ref=raw('parent-closeout.json', proof['parent_closeout_raw_utf8'].encode()),
        request_ref=raw('request.json', proof['request_raw_utf8'].encode()),
        stdout_ref=raw('owner.stdout', proof['stdout_raw_utf8'].encode()),
        producer_ref=case['auto_captured'](proof['producer_source_utf8'].encode()))


def _auto_completed_call_v1(case, function, **kwargs):
    native = resources.native_deadlines
    deadline = native.resource_operation_deadline()
    if deadline is not None and deadline.cleanup_only:
        return function(case['ledger'], **kwargs)
    cutoff = time.monotonic() + 240.0
    with native.resource_cleanup_deadline(native_deadline_monotonic=cutoff):
        return function(case['ledger'], **kwargs)


def _auto_completed_route_entry_v1():
    return dict(reservation_id='a' * 32, record_ref={}, proof_ref={}, pins_ref={}, inventory_ref={},
        parent_ref={}, request_ref={}, stdout_ref={}, producer_ref={})


def test_auto_completed_route_is_explicit_and_legacy_default_is_exact():
    entry = _auto_completed_route_entry_v1()
    legacy = cli._capacity_current_candidate_route_v1(entry, recovery)
    assert legacy['name'] is None
    assert legacy['inspect'] is recovery.inspect_sampled_validation_recovery_v1
    assert legacy['reconcile'] is recovery.reconcile_sampled_validation_reservation_v1
    assert legacy['receipt_schema'] == 'explicit-sampled-validation-reservation-reconciliation/v1'
    assert legacy['readiness_schema'] is None
    entry['recovery_profile'] = cli.CAPACITY_COMPLETED_RECOVERY_PROFILE
    selected = cli._capacity_current_candidate_route_v1(entry, recovery)
    assert selected['name'] == 'source-held-V5-completed-command-watchdog-finalization/v1'
    assert selected['inspect'] is recovery.inspect_completed_watchdog_validation_recovery_v1
    assert selected['reconcile'] is recovery.reconcile_completed_watchdog_validation_reservation_v1
    assert selected['receipt_schema'] == 'explicit-completed-watchdog-validation-reconciliation/v1'
    assert selected['readiness_schema'] == 'completed-watchdog-validation-recovery-readiness/v1'


@pytest.mark.parametrize('profile', [None, True, 'manual-private-snapshot-source-held-V5-retained-command-failure/v1', 'unknown/v1'])
def test_auto_completed_unknown_optin_refuses_before_file_owner_or_API(monkeypatch, profile):
    entry = _auto_completed_route_entry_v1()
    entry['recovery_profile'] = profile
    def forbidden(*args, **kwargs):
        pytest.fail('unknown candidate opt-in reached DATA/owner/API')
    monkeypatch.setattr(cli, '_capacity_recovery_json', forbidden)
    monkeypatch.setattr(recovery, 'inspect_completed_watchdog_validation_recovery_v1', forbidden)
    with pytest.raises(ValueError, match='explicit completed-watchdog candidate'):
        cli._capacity_current_candidate_route_v1(entry, recovery)


@pytest.mark.parametrize('damage', ['extra', 'missing-inventory', 'missing-proof'])
def test_auto_completed_optin_has_closed_descriptor_field_set(damage):
    entry = _auto_completed_route_entry_v1()
    entry['recovery_profile'] = cli.CAPACITY_COMPLETED_RECOVERY_PROFILE
    if damage == 'extra': entry['allow_automatic_retry'] = True
    elif damage == 'missing-inventory': entry.pop('inventory_ref')
    else: entry.pop('proof_ref')
    with pytest.raises(ValueError):
        cli._capacity_current_candidate_profile_v1(entry)


@pytest.mark.parametrize('budget', [1, 16 * 1024**2, 64 * 1024**2])
def test_auto_completed_record_keeps_original_positive_budget_within_existing_maximum(budget):
    record = dict(reservation_id='a' * 32, status='retained', process_scope='sampled_birth_bound_descendants',
        scheduler_lane='validation', workload='canonical_validation', external_charges={},
        storage_bytes=budget, scheduler_policy_sha256=cli.CAPACITY_CURRENT_POLICY_SHA256)
    assert cli._capacity_current_completed_record_v1(record, 'a' * 32, recovery) == recovery._digest(record)
    if budget != 64 * 1024**2:
        with pytest.raises(ValueError):
            cli._capacity_current_record_v1(record, 'a' * 32, recovery)


@pytest.mark.parametrize('damage', ['zero', 'boolean', 'too-large', 'string', 'released',
    'process-scope', 'policy', 'foreign-charge', 'wrong-id'])
def test_auto_completed_record_refuses_budget_or_custody_scope_upgrade(damage):
    row = dict(reservation_id='a' * 32, status='retained', process_scope='sampled_birth_bound_descendants',
        scheduler_lane='validation', workload='canonical_validation', external_charges={},
        storage_bytes=1_000_000, scheduler_policy_sha256=cli.CAPACITY_CURRENT_POLICY_SHA256)
    if damage == 'zero': row['storage_bytes'] = 0
    elif damage == 'boolean': row['storage_bytes'] = True
    elif damage == 'too-large': row['storage_bytes'] = 64 * 1024**2 + 1
    elif damage == 'string': row['storage_bytes'] = '1000000'
    elif damage == 'released': row['status'] = 'released'
    elif damage == 'process-scope': row['process_scope'] = 'unknown'
    elif damage == 'policy': row['scheduler_policy_sha256'] = 'f' * 64
    elif damage == 'foreign-charge': row['external_charges'] = {'unit': 1}
    else: row['reservation_id'] = 'b' * 32
    with pytest.raises(ValueError):
        cli._capacity_current_completed_record_v1(row, 'a' * 32, recovery)


@pytest.mark.parametrize('pair', ['280-11e', '269-4df'])
def test_auto_completed_bridge_reuses_exact_descriptors_and_real_typed_readiness(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, pair):
    case = _auto_completed_case_v1(auto_completed_setup_v1, monkeypatch,
        auto_completed_captured_producers_v1, pair=pair)
    entry = _auto_completed_entry_v1(case)
    before = case['ledger'].read_bytes()
    # Bridge validates DATA only. Actual fsync/inventory belongs to e42 readiness.
    def forbidden(*args, **kwargs):
        pytest.fail('DATA bridge performed a pre-API fsync inventory')
    with monkeypatch.context() as data_only:
        data_only.setattr(recovery, '_durable_inventory', forbidden)
        record, kwargs = cli._capacity_current_completed_candidate_data_v1(entry, recovery, lambda: 5.0)
    assert record == case['row']
    assert kwargs['artifact_inventory_manifest'] == entry['inventory_ref']
    assert kwargs['evidence_archive'] == entry['proof_ref']
    assert kwargs['proof_raw'] == case['args']['proof_raw']
    assert kwargs['expected_artifacts'] == case['args']['expected_artifacts']
    ready = _auto_completed_call_v1(case, recovery.inspect_completed_watchdog_validation_recovery_v1, **kwargs)
    assert ready['ready'] is True and ready['recovery_performed'] is ready['state_written'] is False
    assert ready['original_storage_limit_bytes'] == 220_000_000_000
    assert ready['current_storage_limit_bytes'] == 250_000_000_000
    assert case['ledger'].read_bytes() == before


@pytest.mark.parametrize('damage', ['parent-raw', 'request-raw', 'stdout-raw', 'unknown-producer',
    'row-pin', 'proof-pin', 'inventory-identity', 'inventory-count', 'inventory-over-budget'])
def test_auto_completed_bridge_refuses_contradictory_configured_original_DATA(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, damage):
    case = _auto_completed_case_v1(auto_completed_setup_v1, monkeypatch,
        auto_completed_captured_producers_v1)
    entry = _auto_completed_entry_v1(case)
    if damage in ('parent-raw', 'request-raw', 'stdout-raw'):
        field = {'parent-raw': 'parent_ref', 'request-raw': 'request_ref', 'stdout-raw': 'stdout_ref'}[damage]
        entry[field] = save(Path(entry[field]['path']), {'unit': 'different original DATA'})
    elif damage == 'unknown-producer':
        path = case['args']['roots'][1] / 'unreviewed-producer.pydata'
        path.write_bytes(b'# unit unknown producer DATA only\n');path.chmod(0o600)
        entry['producer_ref'] = pin(path)
    elif damage in ('row-pin', 'proof-pin'):
        values = json.loads(Path(entry['pins_ref']['path']).read_bytes())
        values['expected_record_sha256' if damage == 'row-pin' else 'proof_sha256'] = 'f' * 64
        entry['pins_ref'] = save(Path(entry['pins_ref']['path']), values)
    else:
        values = json.loads(Path(entry['inventory_ref']['path']).read_bytes())
        if damage == 'inventory-identity': values['attempt_directory']['inode'] += 1
        elif damage == 'inventory-count': values['artifacts'] = []
        else: values['artifacts'][0]['bytes'] = case['row']['storage_bytes'] + 1
        entry['inventory_ref'] = save(Path(entry['inventory_ref']['path']), values)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        pytest.fail('contradictory configured DATA reached a current owner/API')
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    monkeypatch.setattr(resources, 'DaemonResourceReservation', forbidden)
    with pytest.raises(ValueError):
        cli._capacity_current_completed_candidate_data_v1(entry, recovery, lambda: 5.0)
    assert case['ledger'].read_bytes() == before


@pytest.mark.parametrize('damage', ['owner-sdk', 'subject-sdk', 'native-closure', 'Source-closure',
    'Source-root', 'private-root', 'nonzero-body', 'live-owner', 'native-live'])
def test_auto_completed_bridge_leaves_full_custody_rejection_to_actual_e42_owner(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, damage):
    case = _auto_completed_case_v1(auto_completed_setup_v1, monkeypatch,
        auto_completed_captured_producers_v1)
    canonical, private = case['manual_unit_roots']
    sdk = 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py'
    if damage == 'owner-sdk': case['request']['source_sha256'][str(canonical / sdk)] = 'f' * 64
    elif damage == 'subject-sdk': case['request']['source_sha256'][str(private / sdk)] = 'f' * 64
    elif damage == 'native-closure': case['parent']['original_owner_custody']['original_native_compute_closed'] = False
    elif damage == 'Source-closure': case['parent']['original_owner_custody']['original_source_exit_lifecycle_closed'] = False
    elif damage == 'Source-root': case['parent']['original_source_READs'][0]['canonical_root'] = str(canonical / 'different')
    elif damage == 'private-root': case['request']['cwd'] = str(canonical)
    elif damage == 'nonzero-body':
        case['terminal']['failure'].update(returncode=1, error='validation command failed with returncode 1')
    elif damage == 'live-owner': case['process_table'][case['row']['owner_pid']] = {'unit': 'live'}
    else: case['scheduler_state']['leases'][case['row']['native_lease_id']] = {}
    case['auto_unit']._completed_watchdog_reseal_unit_data(case)
    entry = _auto_completed_entry_v1(case)
    _, kwargs = cli._capacity_current_completed_candidate_data_v1(entry, recovery, lambda: 5.0)
    before = case['ledger'].read_bytes()
    with pytest.raises(resources.DaemonResourceError):
        _auto_completed_call_v1(case, recovery.inspect_completed_watchdog_validation_recovery_v1, **kwargs)
    assert case['ledger'].read_bytes() == before


@pytest.mark.parametrize('damage', ['schema', 'count', 'bytes', 'manifest-ref', 'proof-ref', 'row',
    'failure-preserved', 'native-release', 'inline-artifacts', 'failure-profile', 'boolean-count',
    'both-missing-row', 'both-boolean-row', 'both-malformed-row', 'both-wrong-row',
    'swapped-attempt', 'request-budget', 'admitted'])
def test_auto_completed_receipt_binds_actual_inventory_and_explicit_profile(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, damage):
    case = _auto_completed_case_v1(auto_completed_setup_v1, monkeypatch,
        auto_completed_captured_producers_v1)
    entry = _auto_completed_entry_v1(case)
    receipt = case['auto_unit']._completed_watchdog_call(case, 'reconcile')
    assert cli._capacity_current_completed_receipt_v1(entry, receipt, case['args']['expected_record_sha256']) is None
    changed = deepcopy(receipt)
    if damage == 'schema': changed['schema'] = 'explicit-sampled-validation-reservation-reconciliation/v1'
    elif damage == 'count': changed['artifact_count'] += 1
    elif damage == 'bytes': changed['artifact_bytes'] += 1
    elif damage == 'manifest-ref': changed['artifact_inventory_manifest']['sha256'] = 'f' * 64
    elif damage == 'proof-ref': changed['evidence_archive']['sha256'] = 'f' * 64
    elif damage == 'row': changed['previous_record_sha256'] = 'f' * 64
    elif damage == 'failure-preserved': changed['original_failure_preserved'] = False
    elif damage == 'native-release': changed['native_release_performed'] = True
    elif damage == 'inline-artifacts': changed['artifacts'] = case['args']['expected_artifacts']
    elif damage == 'failure-profile': changed['sampled_custody_proof']['original_failure_profile'] = 'unknown/v1'
    elif damage == 'boolean-count': changed['artifact_count'] = True
    elif damage in ('both-missing-row', 'both-boolean-row', 'both-malformed-row', 'both-wrong-row'):
        pins = json.loads(Path(entry['pins_ref']['path']).read_bytes())
        if damage == 'both-missing-row':
            changed.pop('previous_record_sha256');pins.pop('expected_record_sha256')
        else:
            wrong = True if damage == 'both-boolean-row' else ('x' * 64 if damage == 'both-malformed-row' else 'f' * 64)
            changed['previous_record_sha256'] = pins['expected_record_sha256'] = wrong
        entry['pins_ref'] = save(Path(entry['pins_ref']['path']), pins)
    elif damage == 'swapped-attempt':
        inventory = json.loads(Path(entry['inventory_ref']['path']).read_bytes())
        inventory['attempt_directory']['inode'] += 1
        entry['inventory_ref'] = save(Path(entry['inventory_ref']['path']), inventory)
        changed['artifact_inventory_manifest'] = dict(entry['inventory_ref'])
    elif damage == 'request-budget': changed['request_budget_changed'] = True
    else: changed['admitted'] = True
    before = case['ledger'].read_bytes()
    with pytest.raises(ValueError):
        cli._capacity_current_completed_receipt_v1(entry, changed)
    assert case['ledger'].read_bytes() == before


def _auto_completed_watch_unit_v1(case, monkeypatch):
    entry = _auto_completed_entry_v1(case)
    state = case['args']['roots'][1] / 'automatic-completed-watch-state'
    state.mkdir(mode=0o700)
    monkeypatch.setattr(cli, 'CAPACITY_CURRENT_STATE', state)
    config = dict(state_directory=str(state), root_identities=[resources._root_identity(r) for r in cli.CAPACITY_RECOVERY_ROOTS],
        triggers=[dict(unit_pressure_context_DATA=True)], candidates=[entry])
    monkeypatch.setattr(cli, '_capacity_current_config_v1', lambda *args: (config, {}))
    monkeypatch.setattr(cli, '_capacity_current_source_guard_v1', lambda *args: None)
    monkeypatch.setattr(cli, '_capacity_current_trigger_v1', lambda *args: 1)
    original = recovery._administrative_census
    initial = [True]
    def census(owner, ledger):
        observed = original(owner, ledger)
        if initial[0]:
            initial[0] = False
            # One explicitly modeled initial pressure observation. The actual
            # original e42 mutation and postwrite census use real local roots.
            observed['observed_apparent_bytes'] = resources.MAX_STORAGE_BYTES - observed['outstanding_full_reservations_bytes'] - 32 * 1024**2
            observed['charged_bytes'] = resources.MAX_STORAGE_BYTES - 32 * 1024**2
        return observed
    monkeypatch.setattr(recovery, '_administrative_census', census)
    def run(*, deadline=None, config_ref=None):
        initial[0] = True
        deadline = time.monotonic() + 240.0 if deadline is None else deadline
        with resources.native_deadlines.resource_cleanup_deadline(native_deadline_monotonic=deadline):
            return cli._watch_current_sampled_validation_capacity_v1(
                {'unit_config_DATA': True} if config_ref is None else config_ref,
                {'unit_source_pin_DATA': True}, deadline)
    key = cli._capacity_current_claim_key_v1(entry['reservation_id'])
    paths = {name: state / (key + '.current-sampled-' + name + '-v01.json')
        for name in ('started', 'returned', 'verified', 'failure')}
    return dict(entry=entry, state=state, config=config, run=run, paths=paths)


def test_auto_completed_body_zero_without_optin_keeps_default_denial(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1):
    case = _auto_completed_case_v1(auto_completed_setup_v1, monkeypatch,
        auto_completed_captured_producers_v1)
    watched = _auto_completed_watch_unit_v1(case, monkeypatch)
    legacy = dict(watched['entry']);legacy.pop('recovery_profile')
    watched['config']['candidates'] = [legacy]
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        pytest.fail('completed body silently upgraded the legacy candidate route')
    monkeypatch.setattr(cli, '_capacity_current_completed_candidate_data_v1', forbidden)
    monkeypatch.setattr(recovery, 'inspect_completed_watchdog_validation_recovery_v1', forbidden)
    monkeypatch.setattr(recovery, 'reconcile_completed_watchdog_validation_reservation_v1', forbidden)
    result = watched['run']()
    assert result['readiness_API_calls'] == result['reconciliation_API_calls'] == 0
    assert any(row['status'] == 'candidate_unresolved_kept_charged' for row in result['observations'])
    assert not any(path.exists() for path in watched['paths'].values())
    assert case['ledger'].read_bytes() == before


def test_auto_completed_wrong_readiness_schema_cannot_start_a_mutation(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1):
    case = _auto_completed_case_v1(auto_completed_setup_v1, monkeypatch,
        auto_completed_captured_producers_v1)
    watched = _auto_completed_watch_unit_v1(case, monkeypatch)
    original = recovery.inspect_completed_watchdog_validation_recovery_v1
    def wrong_schema(*args, **kwargs):
        observed = original(*args, **kwargs)
        observed['schema'] = 'sampled-validation-recovery-readiness/v1'
        return observed
    monkeypatch.setattr(recovery, 'inspect_completed_watchdog_validation_recovery_v1', wrong_schema)
    before = case['ledger'].read_bytes()
    result = watched['run']()
    assert result['readiness_API_calls'] == 1 and result['reconciliation_API_calls'] == 0
    assert any(row['status'] == 'candidate_unresolved_kept_charged' for row in result['observations'])
    assert not any(path.exists() for path in watched['paths'].values())
    assert case['ledger'].read_bytes() == before


@pytest.mark.parametrize('large', [False, True])
def test_auto_completed_watch_performs_one_real_local_closeout_with_compact_full_inventory(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, large):
    case = _auto_completed_case_v1(auto_completed_setup_v1, monkeypatch,
        auto_completed_captured_producers_v1, large=large)
    watched = _auto_completed_watch_unit_v1(case, monkeypatch)
    before = json.loads(case['ledger'].read_bytes())
    result = watched['run']()
    assert result['readiness_API_calls'] == result['reconciliation_API_calls'] == result['disposition_API_calls'] == 1
    assert result['status'] == 'capacity_for_blocked_request_recovered'
    assert result['source_READ_closed'] is False  # Unit calls the inner watcher, no Source lease.
    returned = json.loads(watched['paths']['returned'].read_bytes())
    receipt = returned['actual_receipt']
    assert returned['mutation_API_calls'] == 1
    assert receipt['schema'] == 'explicit-completed-watchdog-validation-reconciliation/v1'
    assert receipt['artifact_count'] == (4097 if large else len(case['args']['expected_artifacts']))
    assert 'artifacts' not in receipt
    assert receipt['artifact_inventory_manifest'] == watched['entry']['inventory_ref']
    assert receipt['evidence_archive'] == watched['entry']['proof_ref']
    after = json.loads(case['ledger'].read_bytes())
    selected = after['reservations'][case['args']['reservation_id']]
    assert selected['status'] == 'released'
    assert selected['storage_bytes'] == case['row']['storage_bytes']
    assert after['reservations'][case['prior_id']] == before['reservations'][case['prior_id']]
    assert after['limit_bytes'] == before['limit_bytes'] == 250_000_000_000
    assert watched['paths']['verified'].exists() and not watched['paths']['failure'].exists()
    def forbidden(*args, **kwargs):
        pytest.fail('second tick replayed completed-profile mutation')
    monkeypatch.setattr(recovery, 'reconcile_completed_watchdog_validation_reservation_v1', forbidden)
    second = watched['run']()
    assert second['reconciliation_API_calls'] == 0
    assert any(row['status'] == 'historical_actual_postwrite_verified' for row in second['observations'])


@pytest.mark.parametrize('history', ['unknown', 'manual-returned', 'manual-verified'])
def test_auto_completed_existing_manual_lineage_and_UNKNOWN_never_mutate_again(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, history):
    case = _auto_completed_case_v1(auto_completed_setup_v1, monkeypatch,
        auto_completed_captured_producers_v1)
    watched = _auto_completed_watch_unit_v1(case, monkeypatch)
    manual = dict(reservation_id=case['args']['reservation_id'], unit_manual_lineage_DATA=True)
    trigger = {'unit_original_manual_trigger_DATA': True}
    save(watched['paths']['started'], dict(profile=cli.CAPACITY_CURRENT_PROFILE, candidate=manual, trigger=trigger))
    if history != 'unknown':
        save(watched['paths']['returned'], dict(profile=cli.CAPACITY_CURRENT_PROFILE,
            candidate=manual, trigger=trigger, mutation_API_calls=1,
            actual_receipt={'unit_uninterpreted_manual_receipt_DATA': True}))
    if history == 'manual-verified':
        save(watched['paths']['verified'], {'unit_uninterpreted_manual_verified_DATA': True})
    original = {p.name: p.read_bytes() for p in watched['state'].glob('*.current-sampled-*.json')}
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        pytest.fail('existing per-claim history reached readiness or a mutation')
    monkeypatch.setattr(cli, '_capacity_current_completed_candidate_data_v1', forbidden)
    monkeypatch.setattr(recovery, 'inspect_completed_watchdog_validation_recovery_v1', forbidden)
    monkeypatch.setattr(recovery, 'reconcile_completed_watchdog_validation_reservation_v1', forbidden)
    result = watched['run']()
    assert result['readiness_API_calls'] == result['reconciliation_API_calls'] == result['disposition_API_calls'] == 0
    expected = ('original_outcome_unknown_no_mutation_replay' if history == 'unknown'
        else 'existing_claim_lineage_differs_no_mutation_replay')
    assert any(row['status'] == expected for row in result['observations'])
    assert {p.name: p.read_bytes() for p in watched['state'].glob('*.current-sampled-*.json')} == original
    assert not watched['paths']['failure'].exists()
    assert case['ledger'].read_bytes() == before


@pytest.mark.parametrize('change', ['same-lineage', 'changed-config-same-candidate', 'changed-candidate', 'expired-clock',
    'wrong-receipt-schema', 'boolean-return-counter'])
def test_auto_completed_known_returned_recovery_is_readonly_and_keeps_original_clock(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, change):
    case = _auto_completed_case_v1(auto_completed_setup_v1, monkeypatch,
        auto_completed_captured_producers_v1)
    watched = _auto_completed_watch_unit_v1(case, monkeypatch)
    watched['run']()
    started = json.loads(watched['paths']['started'].read_bytes())
    saved_deadline = started['original_deadline_monotonic']
    original_verified = watched['paths']['verified'].with_name('retained-initial-verified-UNIT_DATA.json')
    watched['paths']['verified'].rename(original_verified)
    if change == 'changed-candidate':
        watched['config']['candidates'] = [dict(watched['entry'], proof_ref=dict(watched['entry']['proof_ref'], sha256='f' * 64))]
    elif change == 'expired-clock':
        started['original_deadline_monotonic'] = time.monotonic() - 1
        started['original_started_monotonic'] = started['original_deadline_monotonic'] - 240.0
        save(watched['paths']['started'], started)
    elif change in ('wrong-receipt-schema', 'boolean-return-counter'):
        returned = json.loads(watched['paths']['returned'].read_bytes())
        if change == 'wrong-receipt-schema':
            returned['actual_receipt']['schema'] = 'explicit-sampled-validation-reservation-reconciliation/v1'
        else:
            returned['mutation_API_calls'] = True
        save(watched['paths']['returned'], returned)
    def forbidden(*args, **kwargs):
        pytest.fail('known-returned completion replayed a mutation')
    monkeypatch.setattr(recovery, 'reconcile_completed_watchdog_validation_reservation_v1', forbidden)
    before = case['ledger'].read_bytes()
    if change in ('wrong-receipt-schema', 'boolean-return-counter'):
        with pytest.raises(ValueError):
            watched['run'](deadline=time.monotonic() + 600.0)
    else:
        result = watched['run'](deadline=time.monotonic() + 600.0,
            config_ref={'unit_new_config_generation_DATA': True} if change == 'changed-config-same-candidate' else None)
        assert result['reconciliation_API_calls'] == 0
        if change in ('same-lineage', 'changed-config-same-candidate'):
            assert result['status'] == 'known_returned_typed_API_postwrite_completed_readonly'
            assert watched['paths']['verified'].exists()
            assert json.loads(watched['paths']['started'].read_bytes())['original_deadline_monotonic'] == saved_deadline
        else:
            expected = ('existing_claim_lineage_differs_no_mutation_replay' if change == 'changed-candidate'
                else 'original_readonly_clock_unavailable_no_replay')
            assert any(row['status'] == expected for row in result['observations'])
            assert not watched['paths']['verified'].exists()
    assert original_verified.exists()
    assert case['ledger'].read_bytes() == before


def test_auto_completed_postwrite_failure_keeps_actual_return_and_finishes_readonly(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1):
    case = _auto_completed_case_v1(auto_completed_setup_v1, monkeypatch,
        auto_completed_captured_producers_v1)
    watched = _auto_completed_watch_unit_v1(case, monkeypatch)
    original = recovery.inspect_validation_disposition
    def fail_once(*args, **kwargs):
        raise OSError('authored postwrite inspection interruption')
    monkeypatch.setattr(recovery, 'inspect_validation_disposition', fail_once)
    with pytest.raises(OSError, match='authored postwrite'):
        watched['run']()
    assert watched['paths']['started'].exists() and watched['paths']['returned'].exists()
    assert watched['paths']['failure'].exists() and not watched['paths']['verified'].exists()
    returned = json.loads(watched['paths']['returned'].read_bytes())
    assert returned['mutation_API_calls'] == 1
    assert returned['actual_receipt']['schema'] == 'explicit-completed-watchdog-validation-reconciliation/v1'
    retained_history = {name: watched['paths'][name].read_bytes() for name in ('started', 'returned', 'failure')}
    before = case['ledger'].read_bytes()
    monkeypatch.setattr(recovery, 'inspect_validation_disposition', original)
    def forbidden(*args, **kwargs):
        pytest.fail('postwrite completion replayed the original mutation')
    monkeypatch.setattr(recovery, 'reconcile_completed_watchdog_validation_reservation_v1', forbidden)
    result = watched['run'](deadline=time.monotonic() + 600.0)
    assert result['status'] == 'known_returned_typed_API_postwrite_completed_readonly'
    assert result['reconciliation_API_calls'] == 0 and watched['paths']['verified'].exists()
    assert all(watched['paths'][name].read_bytes() == body for name, body in retained_history.items())
    assert case['ledger'].read_bytes() == before


def test_auto_completed_86c8_bridge_reuses_real_typed_readiness(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1):
    test_auto_completed_bridge_reuses_exact_descriptors_and_real_typed_readiness(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, '86c8-4df')


@pytest.mark.parametrize('damage', ['parent-raw', 'request-raw', 'stdout-raw', 'unknown-producer',
    'row-pin', 'proof-pin', 'inventory-identity', 'inventory-count', 'inventory-over-budget'])
def test_auto_completed_86c8_bridge_refuses_contradictory_original_DATA(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, damage):
    original = _auto_completed_case_v1
    def selected(*args, **kwargs):
        kwargs.setdefault('pair', '86c8-4df')
        return original(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setitem(globals(), '_auto_completed_case_v1', selected)
        test_auto_completed_bridge_refuses_contradictory_configured_original_DATA(
            auto_completed_setup_v1, patch, auto_completed_captured_producers_v1, damage)


@pytest.mark.parametrize('damage', ['owner-sdk', 'subject-sdk', 'native-closure', 'Source-closure',
    'Source-root', 'private-root', 'nonzero-body', 'live-owner', 'native-live'])
def test_auto_completed_86c8_bridge_keeps_full_current_custody_rejection(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, damage):
    original = _auto_completed_case_v1
    def selected(*args, **kwargs):
        kwargs.setdefault('pair', '86c8-4df')
        return original(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setitem(globals(), '_auto_completed_case_v1', selected)
        test_auto_completed_bridge_leaves_full_custody_rejection_to_actual_e42_owner(
            auto_completed_setup_v1, patch, auto_completed_captured_producers_v1, damage)


def test_auto_completed_86c8_API_binding_refuses_previous_e42_generation_before_operation(
        current_API_pin_Source29_unit_data_v1):
    unit = current_API_pin_Source29_unit_data_v1
    api = next(row for row in unit['capture']['files'] if row['path'] == unit['api_path'])
    api['source_ref']['sha256'] = 'e42f8175e03c29a4212f49b036bd2e0b82fb41a396e50781870ca875ab146f79'
    unit['config']['source_capture_ref'] = save(unit['capture_path'], unit['capture'])
    config_ref = save(unit['config_path'], unit['config'])
    before = {path.name: path.read_bytes() for path in unit['config_path'].parent.iterdir() if path.is_file()}
    with pytest.raises(ValueError, match='current typed API source generation differs'):
        cli._capacity_current_config_v1(config_ref, unit['own_pin'])
    assert {path.name: path.read_bytes() for path in unit['config_path'].parent.iterdir() if path.is_file()} == before


# Existing watcher caller, fictional completed-ledger DATA, real local owners.
def _auto_ledger_case_v1(setup, monkeypatch, captured):
    from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_resource_recovery as unit
    case = unit._completed_ledger_unit_case(setup, monkeypatch)
    # Adapt only this fictional fixture to the existing watcher production context.
    # The reused watcher models a32MiB pressure gap, incompatible with setup's100k cap.
    # The ledger-finalization profile requires the same ORIGINAL/current cap.
    data = json.loads(case['ledger'].read_bytes())
    original_claims = deepcopy(data['reservations'])
    assert data['limit_bytes'] == resources.MAX_STORAGE_BYTES == 100_000
    monkeypatch.setattr(resources, 'MAX_STORAGE_BYTES', 250_000_000_000)
    data['limit_bytes'] = 250_000_000_000
    case['ledger'].write_text(json.dumps(data))
    case['terminal']['reservation']['storage_limit_bytes'] = 250_000_000_000
    unit._completed_ledger_reseal_unit_data(case)
    assert json.loads(case['ledger'].read_bytes())['reservations'] == original_claims
    assert case['terminal']['reservation']['storage_limit_bytes'] == resources.MAX_STORAGE_BYTES
    monkeypatch.setattr(cli, 'CAPACITY_RECOVERY_ROOTS', tuple(case['args']['roots']))
    monkeypatch.setattr(cli, 'CAPACITY_RECOVERY_LEDGER', case['ledger'])
    monkeypatch.setattr(cli, 'CAPACITY_CURRENT_POLICY_SHA256', case['request']['expected_scheduler_policy_sha256'])
    case['auto_unit'] = unit
    case['auto_captured'] = captured
    return case


def _auto_ledger_entry_v1(case):
    folder = case['args']['roots'][1] / 'automatic-ledger-original-DATA'
    folder.mkdir(exist_ok=True)
    def raw(name, body):
        path = folder / name
        path.write_bytes(body);path.chmod(0o600)
        return pin(path)
    args, proof = case['ledger_args'], case['proof']
    pins = {key: args[key] for key in ('expected_record_sha256', 'expected_producer_sha256',
        'expected_request_sha256', 'expected_parent_closeout_sha256', 'expected_stdout_sha256',
        'expected_terminal_sha256')}
    pins.update(proof_sha256=args['expected_proof_sha256'], historical_evidence_selected_by_caller=True,
        cryptographic_execution_attestation=False, reconstructed_Popen_handle=False)
    return dict(reservation_id=args['reservation_id'],
        recovery_profile=cli.CAPACITY_COMPLETED_LEDGER_RECOVERY_PROFILE,
        record_ref=save(folder / 'record.json', case['row']),
        proof_ref=raw('proof.json', args['proof_raw']),
        inventory_ref=save(folder / 'inventory.json', dict(schema='retained-artifact-inventory/v1',
            attempt_directory=case['row']['attempt_directory'], artifacts=args['expected_artifacts'])),
        pins_ref=save(folder / 'pins.json', pins),
        parent_ref=raw('parent-closeout.json', proof['parent_closeout_raw_utf8'].encode()),
        request_ref=raw('request.json', proof['request_raw_utf8'].encode()),
        stdout_ref=raw('owner.stdout', proof['stdout_raw_utf8'].encode()),
        producer_ref=case['auto_captured'](proof['producer_source_utf8'].encode()),
        sealed_artifacts=deepcopy(case['sealed_artifacts']))


def _auto_ledger_watch_v1(case, monkeypatch):
    entry = _auto_ledger_entry_v1(case)
    # Reuse the existing finite watcher fixture and original deadline/once keys.
    monkeypatch.setitem(globals(), '_auto_completed_entry_v1', lambda _: entry)
    return _auto_completed_watch_unit_v1(case, monkeypatch)


def test_auto_ledger_route_selects_existing_typed_API_without_relabeling():
    entry = _auto_completed_route_entry_v1()
    entry.update(recovery_profile='source-held-V5-completed-command-ledger-finalization/v1',
        sealed_artifacts={})
    selected = cli._capacity_current_candidate_route_v1(entry, recovery)
    assert selected['inspect'] is recovery.inspect_completed_ledger_finalization_validation_recovery_v1
    assert selected['reconcile'] is recovery.reconcile_completed_ledger_finalization_validation_reservation_v1
    assert selected['name'] == 'source-held-V5-completed-command-ledger-finalization/v1'
    assert selected['readiness_schema'] == 'sampled-validation-recovery-readiness/v1'
    assert selected['receipt_schema'] == 'explicit-sampled-validation-reservation-reconciliation/v1'
    entry.pop('recovery_profile');entry.pop('sealed_artifacts')
    assert cli._capacity_current_candidate_route_v1(entry, recovery)['name'] is None


@pytest.mark.parametrize('damage', ['extra-grant', 'missing-sealed', 'missing-inventory'])
def test_auto_ledger_explicit_enrollment_requires_closed_fields_before_DATA(monkeypatch, damage):
    entry = _auto_completed_route_entry_v1()
    entry.update(recovery_profile=cli.CAPACITY_COMPLETED_LEDGER_RECOVERY_PROFILE, sealed_artifacts={})
    if damage == 'extra-grant': entry['automatic_productive_retry'] = True
    elif damage == 'missing-sealed': entry.pop('sealed_artifacts')
    else: entry.pop('inventory_ref')
    def forbidden(*args, **kwargs): pytest.fail('malformed enrollment reached DATA/owner')
    monkeypatch.setattr(cli, '_capacity_recovery_json', forbidden)
    with pytest.raises(ValueError, match='explicit completed-ledger candidate'):
        cli._capacity_current_candidate_route_v1(entry, recovery)


def test_auto_ledger_bridge_uses_real_readiness_and_original_three_seals(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1):
    case = _auto_ledger_case_v1(auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    entry = _auto_ledger_entry_v1(case)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs): pytest.fail('DATA bridge fsynced before typed owner')
    with monkeypatch.context() as data_only:
        data_only.setattr(recovery, '_durable_inventory', forbidden)
        row, kwargs = cli._capacity_current_completed_candidate_data_v1(entry, recovery, lambda: 5.0)
    assert row == case['row'] and kwargs['sealed_artifacts'] == case['sealed_artifacts']
    assert kwargs['sealed_artifacts'] is not entry['sealed_artifacts']
    assert 'artifact_inventory_manifest' not in kwargs and 'evidence_archive' not in kwargs
    ready = _auto_completed_call_v1(case,
        recovery.inspect_completed_ledger_finalization_validation_recovery_v1, **kwargs)
    assert ready['ready'] is True and ready['state_written'] is ready['recovery_performed'] is False
    assert ready['proof']['original_command_returncode'] == 0
    assert ready['proof']['original_cli_returncode'] == 1
    assert ready['proof']['sealed_completed_artifacts'] == entry['sealed_artifacts']
    assert case['ledger'].read_bytes() == before


@pytest.mark.parametrize('damage', ['sealed-extra', 'sealed-missing', 'sealed-path', 'sealed-size-bool',
    'sealed-sha', 'producer-generation', 'inventory-overflow'])
def test_auto_ledger_bridge_refuses_incomplete_or_foreign_DATA_before_API(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, damage):
    case = _auto_ledger_case_v1(auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    entry = _auto_ledger_entry_v1(case)
    if damage == 'sealed-extra': entry['sealed_artifacts']['approval'] = {}
    elif damage == 'sealed-missing': entry['sealed_artifacts'].pop('execution')
    elif damage == 'sealed-path': entry['sealed_artifacts']['result']['path'] += '.other'
    elif damage == 'sealed-size-bool': entry['sealed_artifacts']['result']['bytes'] = True
    elif damage == 'sealed-sha': entry['sealed_artifacts']['result']['sha256'] = 'invalid'
    elif damage == 'producer-generation': entry['producer_ref']['sha256'] = '280bf5bcb4d1cdc42ba91d5e1d71d6c867fb6e575833957eca7fc79d5e3228a4'
    else:
        inventory = json.loads(Path(entry['inventory_ref']['path']).read_bytes())
        inventory['artifacts'] = [dict(inventory['artifacts'][0])] * 4097
        entry['inventory_ref'] = save(Path(entry['inventory_ref']['path']), inventory)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs): pytest.fail('bad DATA reached scheduler/owner')
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    # One selected case covers both bool rejection and the exact API4MiB descriptor bound.
    sizes = (True, 4 * 1024**2 + 1) if damage == 'sealed-size-bool' else (None,)
    for size in sizes:
        if damage == 'sealed-size-bool': entry['sealed_artifacts']['result']['bytes'] = size
        with pytest.raises(ValueError):
            cli._capacity_current_completed_candidate_data_v1(entry, recovery, lambda: 5.0)
    assert case['ledger'].read_bytes() == before


def test_auto_ledger_watch_performs_one_real_accounting_closeout_and_keeps_failed_outer_owner(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1):
    case = _auto_ledger_case_v1(auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    watched = _auto_ledger_watch_v1(case, monkeypatch)
    ledger_before = json.loads(case['ledger'].read_bytes())
    frames = deepcopy((case['request'], case['terminal'], case['parent']))
    artifacts = recovery._durable_inventory(case['args']['attempt_directory'])
    native_before = deepcopy(case['scheduler_state'])
    original_inspect = recovery.inspect_completed_ledger_finalization_validation_recovery_v1
    busy = [True]
    def inspect_after_one_busy_observation(*args, **kwargs):
        assert 0 < kwargs['ledger_lock_timeout_seconds'] <= 5.0
        if busy[0]:
            busy[0] = False
            raise recovery._ValidationInspectionLockTimeout('unit readonly inspection busy')
        return original_inspect(*args, **kwargs)
    monkeypatch.setattr(recovery, 'inspect_completed_ledger_finalization_validation_recovery_v1',
        inspect_after_one_busy_observation)
    deferred = watched['run']()
    assert deferred['readiness_API_calls'] == 1 and deferred['reconciliation_API_calls'] == 0
    assert any(row['status'] == 'candidate_readonly_ledger_busy_deferred'
        and row['mutation_API_calls'] == 0 and row['once_started'] is False
        for row in deferred['observations'])
    assert not any(path.exists() for path in watched['paths'].values())
    assert json.loads(case['ledger'].read_bytes()) == ledger_before
    assert case['scheduler_state'] == native_before
    original_reconcile = recovery.reconcile_completed_ledger_finalization_validation_reservation_v1
    def bounded_reconcile(*args, **kwargs):
        assert 0 < kwargs['ledger_lock_timeout_seconds'] <= 5.0
        return original_reconcile(*args, **kwargs)
    monkeypatch.setattr(recovery, 'reconcile_completed_ledger_finalization_validation_reservation_v1',
        bounded_reconcile)
    original_disposition = recovery.inspect_validation_disposition
    def bounded_disposition(*args, **kwargs):
        assert 0 < kwargs['ledger_lock_timeout_seconds'] <= 5.0
        return original_disposition(*args, **kwargs)
    monkeypatch.setattr(recovery, 'inspect_validation_disposition', bounded_disposition)
    result = watched['run']()
    assert result['readiness_API_calls'] == result['reconciliation_API_calls'] == result['disposition_API_calls'] == 1
    returned = json.loads(watched['paths']['returned'].read_bytes())
    receipt = returned['actual_receipt']
    assert receipt['schema'] == 'explicit-sampled-validation-reservation-reconciliation/v1'
    assert receipt['sampled_custody_proof']['original_cli_returncode'] == 1
    assert receipt['sampled_custody_proof']['test_or_task_acceptance_asserted'] is False
    assert returned['mutation_API_calls'] == 1 and watched['paths']['verified'].exists()
    after = json.loads(case['ledger'].read_bytes())
    assert after['reservations'][case['args']['reservation_id']]['status'] == 'released'
    assert after['reservations'][case['prior_id']] == ledger_before['reservations'][case['prior_id']]
    assert after['limit_bytes'] == ledger_before['limit_bytes']
    assert (case['request'], case['terminal'], case['parent']) == frames
    assert case['parent']['owner_returncode'] == 1 and case['terminal']['failure']['completed'] is False
    assert recovery._durable_inventory(case['args']['attempt_directory']) == artifacts
    assert case['scheduler_state'] == native_before
    def forbidden(*args, **kwargs): pytest.fail('second tick replayed accounting mutation')
    monkeypatch.setattr(recovery, 'reconcile_completed_ledger_finalization_validation_reservation_v1', forbidden)
    repeated = watched['run']()
    assert repeated['reconciliation_API_calls'] == 0
    assert any(row['status'] == 'historical_actual_postwrite_verified' for row in repeated['observations'])


@pytest.mark.parametrize('enrolled', [False, True])
def test_auto_ledger_administrative_closeout_does_not_require_pressure_or_upgrade_default_idle(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, enrolled):
    case = _auto_ledger_case_v1(auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    watched = _auto_ledger_watch_v1(case, monkeypatch)
    if not enrolled:
        watched['entry'].pop('recovery_profile');watched['entry'].pop('sealed_artifacts')
    original = cli._capacity_current_pressure_v1
    def satisfied(accounting, requested):
        value = original(accounting, requested)
        value['capacity_satisfied'] = True
        return value
    monkeypatch.setattr(cli, '_capacity_current_pressure_v1', satisfied)
    before = case['ledger'].read_bytes()
    result = watched['run']()
    if enrolled:
        assert result['reconciliation_API_calls'] == 1 and watched['paths']['verified'].exists()
    else:
        assert result['status'] == 'idle_current_capacity_satisfied'
        assert result['readiness_API_calls'] == result['reconciliation_API_calls'] == 0
        assert case['ledger'].read_bytes() == before
        assert not any(p.exists() for p in watched['paths'].values())


@pytest.mark.parametrize('damage', ['legal-review', 'policy-wait', 'nonzero-command', 'missing-seal', 'changed-seal'])
def test_auto_ledger_watch_keeps_unrelated_waits_and_incomplete_command_evidence_charged(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, damage):
    case = _auto_ledger_case_v1(auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    if damage in ('legal-review', 'policy-wait'):
        case['terminal']['failure'].update(error_type='LegalReviewRequired' if damage == 'legal-review' else 'PolicyWait',
            error='intentional legal review pending' if damage == 'legal-review' else 'policy decision pending')
        case['auto_unit']._completed_ledger_reseal_unit_data(case)
    elif damage == 'nonzero-command':
        case['terminal']['failure']['returncode'] = 1
        case['auto_unit']._completed_ledger_reseal_unit_data(case)
    elif damage == 'missing-seal':
        case['ledger_sealed_paths']['result'].unlink()
    else:
        case['ledger_sealed_paths']['execution'].write_bytes(b'changed after original completed-body seal\n')
    watched = _auto_ledger_watch_v1(case, monkeypatch)
    before = case['ledger'].read_bytes()
    result = watched['run']()
    assert result['reconciliation_API_calls'] == 0
    assert any(row['status'] == 'candidate_unresolved_kept_charged' for row in result['observations'])
    assert not any(p.exists() for p in watched['paths'].values())
    assert case['ledger'].read_bytes() == before


@pytest.mark.parametrize('history', ['unknown', 'foreign-candidate'])
def test_auto_ledger_unknown_and_foreign_once_lineage_never_replay(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, history):
    case = _auto_ledger_case_v1(auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    watched = _auto_ledger_watch_v1(case, monkeypatch)
    candidate = watched['entry'] if history == 'unknown' else dict(reservation_id=case['args']['reservation_id'])
    save(watched['paths']['started'], dict(profile=cli.CAPACITY_CURRENT_PROFILE,
        candidate=candidate, trigger={'unit_original_unknown_DATA': True}))
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs): pytest.fail('UNKNOWN lineage reached a recovery API')
    monkeypatch.setattr(recovery, 'inspect_completed_ledger_finalization_validation_recovery_v1', forbidden)
    monkeypatch.setattr(recovery, 'reconcile_completed_ledger_finalization_validation_reservation_v1', forbidden)
    result = watched['run']()
    assert result['reconciliation_API_calls'] == 0
    assert any(row['status'] == 'original_outcome_unknown_no_mutation_replay' for row in result['observations'])
    assert case['ledger'].read_bytes() == before


@pytest.mark.parametrize('damage', ['outer-success', 'task-accepted', 'productive-grant', 'wrong-profile',
    'wrong-row', 'wrong-seal', 'missing-pin', 'inline-inventory'])
def test_auto_ledger_receipt_keeps_original_failure_and_exact_typed_binding(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, damage):
    case = _auto_ledger_case_v1(auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    entry = _auto_ledger_entry_v1(case)
    receipt = case['auto_unit']._completed_ledger_call(case, 'reconcile')
    assert cli._capacity_current_completed_receipt_v1(entry, receipt) is None
    altered = deepcopy(receipt)
    if damage == 'outer-success': altered['sampled_custody_proof']['original_cli_returncode'] = 0
    elif damage == 'task-accepted': altered['sampled_custody_proof']['test_or_task_acceptance_asserted'] = True
    elif damage == 'productive-grant': altered['sampled_custody_proof']['new_productive_authority_granted'] = True
    elif damage == 'wrong-profile': altered['sampled_custody_proof']['original_failure_profile'] = cli.CAPACITY_COMPLETED_RECOVERY_PROFILE
    elif damage == 'wrong-row': altered['previous_record_sha256'] = 'f' * 64
    elif damage == 'wrong-seal': altered['sampled_custody_proof']['sealed_completed_artifacts']['result']['sha256'] = 'f' * 64
    elif damage == 'missing-pin':
        pins = json.loads(Path(entry['pins_ref']['path']).read_bytes());pins.pop('expected_request_sha256')
        entry['pins_ref'] = save(Path(entry['pins_ref']['path']), pins)
    else: altered['artifacts'] = []
    before = case['ledger'].read_bytes()
    with pytest.raises(ValueError): cli._capacity_current_completed_receipt_v1(entry, altered)
    assert case['ledger'].read_bytes() == before


def test_auto_ledger_short_original_clock_defers_before_once_without_renewal(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1):
    case = _auto_ledger_case_v1(auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    watched = _auto_ledger_watch_v1(case, monkeypatch)
    before = case['ledger'].read_bytes()
    cutoff = time.monotonic() + 189.0
    def forbidden(*args, **kwargs): pytest.fail('short original clock entered mutation')
    monkeypatch.setattr(recovery, 'reconcile_completed_ledger_finalization_validation_reservation_v1', forbidden)
    result = watched['run'](deadline=cutoff)
    assert result['status'] == 'current_cycle_readonly_clock_shortfall_deferred'
    assert result['readiness_API_calls'] == 1 and result['reconciliation_API_calls'] == 0
    assert result['original_deadline_renewed'] is False
    assert any(row['status'] == 'candidate_readonly_clock_shortfall_deferred'
        and row['required_original_remaining_seconds'] == 190.0
        and 0 < row['original_remaining_seconds'] < 190.0
        and row['once_started'] is False and row['mutation_API_calls'] == 0
        for row in result['observations'])
    assert not any(path.exists() for path in watched['paths'].values())
    assert case['ledger'].read_bytes() == before


# Prospective private-ledger watcher integration. These authored UNIT_DATA
# frames reuse the RCE owning helpers; no actual failed-owner history or legal
# meaning is manufactured. Their future execution qualification is separate.
def _auto_private_ledger_case_v1(setup, monkeypatch, captured, *, population=None):
    from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_resource_recovery as unit
    case = unit._private_completed_ledger_unit_case(setup, monkeypatch, population=population)
    # As in the existing ledger watcher fixture, adapt only authored frames to
    # its32MiB pressure model. Preserve every original claim and promise.
    data = json.loads(case['ledger'].read_bytes()); claims = deepcopy(data['reservations'])
    assert data['limit_bytes'] == resources.MAX_STORAGE_BYTES == 4_000_000
    monkeypatch.setattr(resources, 'MAX_STORAGE_BYTES', 250_000_000_000)
    data['limit_bytes'] = 250_000_000_000
    case['ledger'].write_text(json.dumps(data))
    case['terminal']['reservation']['storage_limit_bytes'] = 250_000_000_000
    unit._private_completed_ledger_reseal_unit_data(case)
    assert json.loads(case['ledger'].read_bytes())['reservations'] == claims
    assert case['row']['storage_bytes'] == 2_000_000
    monkeypatch.setattr(cli, 'CAPACITY_RECOVERY_ROOTS', tuple(case['args']['roots']))
    monkeypatch.setattr(cli, 'CAPACITY_RECOVERY_LEDGER', case['ledger'])
    monkeypatch.setattr(cli, 'CAPACITY_CURRENT_POLICY_SHA256', case['request']['expected_scheduler_policy_sha256'])
    case['auto_unit'] = unit;case['auto_captured'] = captured
    return case


def _auto_private_ledger_entry_v1(case):
    # Reuse the exact two detached descriptors already produced by the owning
    # fixture; do not make a second inventory/proof archive for this route.
    args, proof = case['private_ledger_args'], case['proof']
    folder = case['args']['roots'][1] / 'automatic-private-ledger-original-DATA';folder.mkdir(exist_ok=True)
    def raw(name, body):
        path = folder / name;path.write_bytes(body);path.chmod(0o600);return pin(path)
    pins = {key: args[key] for key in ('expected_record_sha256', 'expected_producer_sha256',
        'expected_request_sha256', 'expected_parent_closeout_sha256', 'expected_stdout_sha256',
        'expected_terminal_sha256')}
    pins.update(proof_sha256=args['expected_proof_sha256'], historical_evidence_selected_by_caller=True,
        cryptographic_execution_attestation=False, reconstructed_Popen_handle=False)
    return dict(reservation_id=args['reservation_id'],
        recovery_profile=cli.CAPACITY_PRIVATE_COMPLETED_LEDGER_RECOVERY_PROFILE,
        record_ref=save(folder / 'record.json', case['row']),
        proof_ref=deepcopy(args['evidence_archive']), inventory_ref=deepcopy(args['artifact_inventory_manifest']),
        pins_ref=save(folder / 'pins.json', pins),
        parent_ref=raw('parent-closeout.json', proof['parent_closeout_raw_utf8'].encode()),
        request_ref=raw('request.json', proof['request_raw_utf8'].encode()),
        stdout_ref=raw('owner.stdout', proof['stdout_raw_utf8'].encode()),
        producer_ref=case['auto_captured'](proof['producer_source_utf8'].encode()),
        sealed_artifacts=deepcopy(case['sealed_artifacts']))


def _auto_private_ledger_watch_v1(case, monkeypatch):
    entry = _auto_private_ledger_entry_v1(case)
    monkeypatch.setitem(globals(), '_auto_completed_entry_v1', lambda _: entry)
    return _auto_completed_watch_unit_v1(case, monkeypatch)


def test_auto_private_ledger_route_is_separate_and_does_not_change_old_discriminators():
    entry = _auto_completed_route_entry_v1()
    entry.update(recovery_profile='private-snapshot-source-held-V5-completed-command-ledger-finalization/v1', sealed_artifacts={})
    route = cli._capacity_current_candidate_route_v1(entry, recovery)
    assert route['inspect'] is recovery.inspect_private_snapshot_completed_ledger_finalization_validation_recovery_v1
    assert route['reconcile'] is recovery.reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1
    assert route['readiness_schema'] == 'private-snapshot-completed-ledger-validation-recovery-readiness/v1'
    assert route['receipt_schema'] == 'explicit-private-snapshot-completed-ledger-validation-reconciliation/v1'
    entry['recovery_profile'] = cli.CAPACITY_COMPLETED_LEDGER_RECOVERY_PROFILE
    assert cli._capacity_current_candidate_route_v1(entry, recovery)['inspect'] is recovery.inspect_completed_ledger_finalization_validation_recovery_v1
    entry.pop('recovery_profile');entry.pop('sealed_artifacts')
    assert cli._capacity_current_candidate_route_v1(entry, recovery)['inspect'] is recovery.inspect_sampled_validation_recovery_v1


@pytest.mark.parametrize('damage', ['extra-grant', 'missing-sealed', 'missing-inventory'])
def test_auto_private_ledger_closed_enrollment_precedes_DATA(monkeypatch, damage):
    entry = _auto_completed_route_entry_v1()
    entry.update(recovery_profile=cli.CAPACITY_PRIVATE_COMPLETED_LEDGER_RECOVERY_PROFILE, sealed_artifacts={})
    if damage == 'extra-grant': entry['productive_retry'] = True
    elif damage == 'missing-sealed': entry.pop('sealed_artifacts')
    else: entry.pop('inventory_ref')
    monkeypatch.setattr(cli, '_capacity_recovery_json', lambda *args: pytest.fail('bad enrollment reached DATA'))
    with pytest.raises(ValueError): cli._capacity_current_candidate_route_v1(entry, recovery)


def test_auto_private_ledger_API_contract_requires_both_detached_refs():
    class Incomplete:
        @staticmethod
        def inspect_private_snapshot_completed_ledger_finalization_validation_recovery_v1(ledger_path, *, sealed_artifacts): pass
        reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1 = inspect_private_snapshot_completed_ledger_finalization_validation_recovery_v1
    with pytest.raises(ValueError, match='private completed-ledger recovery API contract'):
        cli._capacity_current_private_completed_ledger_api_contract_v1(Incomplete)


@pytest.mark.parametrize('population', [None, 4097])
def test_auto_private_ledger_bridge_preserves_original_archives_and_real_readonly_API(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, population):
    case = _auto_private_ledger_case_v1(auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, population=population)
    entry = _auto_private_ledger_entry_v1(case);before = case['ledger'].read_bytes()
    with monkeypatch.context() as data_only:
        data_only.setattr(recovery, '_durable_inventory', lambda *args: pytest.fail('DATA bridge fsynced before typed owner'))
        row, kwargs = cli._capacity_current_completed_candidate_data_v1(entry, recovery, lambda: 29.0)
    assert row == case['row'] and 0 < kwargs['ledger_lock_timeout_seconds'] <= 5.0
    assert kwargs['sealed_artifacts'] == case['sealed_artifacts'] and kwargs['sealed_artifacts'] is not entry['sealed_artifacts']
    assert kwargs['artifact_inventory_manifest'] == entry['inventory_ref'] == case['private_ledger_args']['artifact_inventory_manifest']
    assert kwargs['evidence_archive'] == entry['proof_ref'] == case['private_ledger_args']['evidence_archive']
    ready = _auto_completed_call_v1(case, recovery.inspect_private_snapshot_completed_ledger_finalization_validation_recovery_v1, **kwargs)
    assert cli._capacity_current_private_completed_ledger_readiness_v1(entry, ready) is None
    assert ready['proof']['original_command_returncode'] == 0 and ready['proof']['original_cli_returncode'] == 1
    if population is not None: assert ready['artifact_count'] == 4097 and 'artifacts' not in ready
    assert case['ledger'].read_bytes() == before


def test_auto_private_ledger_busy_then_one_real_closeout_and_repeated_tick(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1):
    case = _auto_private_ledger_case_v1(auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    watched = _auto_private_ledger_watch_v1(case, monkeypatch)
    before = json.loads(case['ledger'].read_bytes());frames = deepcopy((case['request'], case['terminal'], case['parent']))
    native_before = deepcopy(case['scheduler_state']);artifacts = recovery._durable_inventory(case['args']['attempt_directory'])
    original = recovery.inspect_private_snapshot_completed_ledger_finalization_validation_recovery_v1
    busy = [True]
    def inspect_after_busy(*args, **kwargs):
        assert 0 < kwargs['ledger_lock_timeout_seconds'] <= 5.0
        if busy[0]: busy[0] = False;raise recovery._ValidationInspectionLockTimeout('authored readonly busy')
        return original(*args, **kwargs)
    monkeypatch.setattr(recovery, 'inspect_private_snapshot_completed_ledger_finalization_validation_recovery_v1', inspect_after_busy)
    deferred = watched['run']()
    assert deferred['readiness_API_calls'] == 1 and deferred['reconciliation_API_calls'] == 0
    assert any(row['status'] == 'candidate_readonly_ledger_busy_deferred' and row['once_started'] is False for row in deferred['observations'])
    assert not any(path.exists() for path in watched['paths'].values())
    assert json.loads(case['ledger'].read_bytes()) == before
    reconcile = recovery.reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1
    disposition = recovery.inspect_validation_disposition
    def bounded_reconcile(*args, **kwargs):
        assert 0 < kwargs['ledger_lock_timeout_seconds'] <= 5.0
        assert kwargs['capacity_policy'] == 'administrative_closeout'
        return reconcile(*args, **kwargs)
    def bounded_disposition(*args, **kwargs):
        assert 0 < kwargs['ledger_lock_timeout_seconds'] <= 5.0
        return disposition(*args, **kwargs)
    monkeypatch.setattr(recovery, 'reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1', bounded_reconcile)
    monkeypatch.setattr(recovery, 'inspect_validation_disposition', bounded_disposition)
    result = watched['run']()
    assert result['readiness_API_calls'] == result['reconciliation_API_calls'] == result['disposition_API_calls'] == 1
    returned = json.loads(watched['paths']['returned'].read_bytes());receipt = returned['actual_receipt']
    assert receipt['schema'] == 'explicit-private-snapshot-completed-ledger-validation-reconciliation/v1'
    assert receipt['sampled_custody_proof']['original_cli_returncode'] == 1
    assert receipt['sampled_custody_proof']['test_or_task_acceptance_asserted'] is False
    verified = json.loads(watched['paths']['verified'].read_bytes())
    assert verified['disposition']['release_evidence']['schema'] == receipt['schema']
    after = json.loads(case['ledger'].read_bytes())
    assert after['reservations'][case['args']['reservation_id']]['status'] == 'released'
    assert after['reservations'][case['prior_id']] == before['reservations'][case['prior_id']]
    assert after['limit_bytes'] == before['limit_bytes']
    assert (case['request'], case['terminal'], case['parent']) == frames
    assert case['parent']['owner_returncode'] == 1 and case['terminal']['failure']['completed'] is False
    assert recovery._durable_inventory(case['args']['attempt_directory']) == artifacts and case['scheduler_state'] == native_before
    monkeypatch.setattr(recovery, 'reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1', lambda *args, **kwargs: pytest.fail('second tick replayed accounting mutation'))
    repeated = watched['run']()
    assert repeated['reconciliation_API_calls'] == 0
    assert any(row['status'] == 'historical_actual_postwrite_verified' for row in repeated['observations'])


@pytest.mark.parametrize('enrolled', [False, True])
def test_auto_private_ledger_explicit_admin_closeout_keeps_default_idle(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, enrolled):
    case = _auto_private_ledger_case_v1(auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    watched = _auto_private_ledger_watch_v1(case, monkeypatch)
    if not enrolled: watched['entry'].pop('recovery_profile');watched['entry'].pop('sealed_artifacts')
    original = cli._capacity_current_pressure_v1
    def satisfied(*args): value = original(*args);value['capacity_satisfied'] = True;return value
    monkeypatch.setattr(cli, '_capacity_current_pressure_v1', satisfied)
    before = case['ledger'].read_bytes();result = watched['run']()
    if enrolled: assert result['reconciliation_API_calls'] == 1 and watched['paths']['verified'].exists()
    else:
        assert result['status'] == 'idle_current_capacity_satisfied'
        assert result['readiness_API_calls'] == result['reconciliation_API_calls'] == 0
        assert case['ledger'].read_bytes() == before and not any(path.exists() for path in watched['paths'].values())


@pytest.mark.parametrize('history', ['unknown', 'foreign-candidate'])
def test_auto_private_ledger_unknown_original_marker_never_replays(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, history):
    case = _auto_private_ledger_case_v1(auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    watched = _auto_private_ledger_watch_v1(case, monkeypatch)
    candidate = watched['entry'] if history == 'unknown' else dict(reservation_id=case['args']['reservation_id'])
    save(watched['paths']['started'], dict(profile=cli.CAPACITY_CURRENT_PROFILE, candidate=candidate, trigger={}))
    def forbidden(*args, **kwargs): pytest.fail('UNKNOWN marker reached a recovery API')
    monkeypatch.setattr(recovery, 'inspect_private_snapshot_completed_ledger_finalization_validation_recovery_v1', forbidden)
    monkeypatch.setattr(recovery, 'reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1', forbidden)
    before = case['ledger'].read_bytes();result = watched['run']()
    assert result['reconciliation_API_calls'] == 0 and case['ledger'].read_bytes() == before
    assert any(row['status'] == 'original_outcome_unknown_no_mutation_replay' for row in result['observations'])


def test_auto_private_ledger_lost_API_return_remains_UNKNOWN_after_real_release(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1):
    case = _auto_private_ledger_case_v1(auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    watched = _auto_private_ledger_watch_v1(case, monkeypatch)
    original = recovery.reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1
    def release_then_lost_return(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('authored lost original API return; no inference of completion')
    monkeypatch.setattr(recovery, 'reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1', release_then_lost_return)
    with pytest.raises(RuntimeError, match='lost original API return'): watched['run']()
    assert watched['paths']['started'].exists() and not watched['paths']['returned'].exists()
    assert json.loads(case['ledger'].read_bytes())['reservations'][case['args']['reservation_id']]['status'] == 'released'
    before = case['ledger'].read_bytes()
    monkeypatch.setattr(recovery, 'reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1', lambda *args, **kwargs: pytest.fail('lost return replayed API'))
    result = watched['run']()
    assert result['reconciliation_API_calls'] == 0 and case['ledger'].read_bytes() == before
    assert any(row['status'] == 'original_outcome_unknown_no_mutation_replay' for row in result['observations'])


@pytest.mark.parametrize('damage', ['schema', 'profile', 'outer-success', 'missing-private-optin', 'seal', 'archive', 'scope', 'body-nonzero'])
def test_auto_private_ledger_readiness_requires_distinct_compact_failed_owner_evidence(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, damage):
    case = _auto_private_ledger_case_v1(auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    entry = _auto_private_ledger_entry_v1(case)
    ready = case['auto_unit']._private_completed_ledger_call(case)
    assert cli._capacity_current_private_completed_ledger_readiness_v1(entry, ready) is None
    changed = deepcopy(ready)
    if damage == 'schema': changed['schema'] = 'sampled-validation-recovery-readiness/v1'
    elif damage == 'profile': changed['proof']['original_failure_profile'] = cli.CAPACITY_COMPLETED_LEDGER_RECOVERY_PROFILE
    elif damage == 'outer-success': changed['proof']['original_cli_returncode'] = 0
    elif damage == 'missing-private-optin': changed['proof'].pop('completed_body_ledger_private_snapshot_optin')
    elif damage == 'seal': changed['proof']['sealed_completed_artifacts']['result']['sha256'] = 'f' * 64
    elif damage == 'archive': changed['evidence_archive']['sha256'] = 'f' * 64
    elif damage == 'scope': changed['proof']['private_subject_pin_scope'] = 'execution-attestation'
    else: changed['proof']['original_command_returncode'] = 1
    before = case['ledger'].read_bytes()
    with pytest.raises(ValueError): cli._capacity_current_private_completed_ledger_readiness_v1(entry, changed)
    assert case['ledger'].read_bytes() == before


@pytest.mark.parametrize('damage', ['schema', 'profile', 'body-nonzero', 'outer-success', 'wrong-row', 'seal', 'archive',
    'artifact-count', 'inline-artifacts', 'accepted', 'grant', 'global-inventory-count', 'cap-change', 'source-pair'])
def test_auto_private_ledger_compact_receipt_refuses_foreign_or_acceptance_fields(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, damage):
    case = _auto_private_ledger_case_v1(auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    entry = _auto_private_ledger_entry_v1(case)
    receipt = case['auto_unit']._private_completed_ledger_call(case, 'reconcile')
    assert cli._capacity_current_completed_receipt_v1(entry, receipt) is None
    changed = deepcopy(receipt)
    if damage == 'schema': changed['schema'] = 'explicit-sampled-validation-reservation-reconciliation/v1'
    elif damage == 'profile': changed['sampled_custody_proof']['original_failure_profile'] = cli.CAPACITY_COMPLETED_RECOVERY_PROFILE
    elif damage == 'body-nonzero': changed['sampled_custody_proof']['original_command_returncode'] = 1
    elif damage == 'outer-success': changed['sampled_custody_proof']['original_cli_returncode'] = 0
    elif damage == 'wrong-row': changed['previous_record_sha256'] = 'f' * 64
    elif damage == 'seal': changed['sampled_custody_proof']['sealed_completed_artifacts']['execution']['sha256'] = 'f' * 64
    elif damage == 'archive': changed['artifact_inventory_manifest']['sha256'] = 'f' * 64
    elif damage == 'artifact-count': changed['artifact_count'] = True
    elif damage == 'inline-artifacts': changed['artifacts'] = []
    elif damage == 'accepted': changed['test_or_task_acceptance_asserted'] = True
    elif damage == 'grant': changed['sampled_custody_proof']['new_productive_authority_granted'] = True
    elif damage == 'global-inventory-count': changed['fresh_global_inventory_count'] = 1
    elif damage == 'cap-change': changed['cap_changed'] = True
    else: changed['sampled_custody_proof']['private_subject_sdk_sha256'] = 'f' * 64
    before = case['ledger'].read_bytes()
    with pytest.raises(ValueError): cli._capacity_current_completed_receipt_v1(entry, changed)
    assert case['ledger'].read_bytes() == before


@pytest.mark.parametrize('damage', ['legal-review', 'policy-wait', 'nonzero-command', 'missing-seal', 'changed-seal'])
def test_auto_private_ledger_other_waits_and_unsealed_history_stay_charged(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, damage):
    case = _auto_private_ledger_case_v1(auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    if damage in ('legal-review', 'policy-wait'):
        case['terminal']['failure'].update(error_type='LegalReviewRequired' if damage == 'legal-review' else 'PolicyWait',
            error='intentional meaning review pending' if damage == 'legal-review' else 'policy decision pending')
        case['auto_unit']._private_completed_ledger_reseal_unit_data(case)
    elif damage == 'nonzero-command':
        case['terminal']['failure']['returncode'] = 1
        case['auto_unit']._private_completed_ledger_reseal_unit_data(case)
    elif damage == 'missing-seal': case['ledger_sealed_paths']['result'].unlink()
    else: case['ledger_sealed_paths']['execution'].write_bytes(b'authored damage after original completed seal\n')
    watched = _auto_private_ledger_watch_v1(case, monkeypatch)
    before = case['ledger'].read_bytes();result = watched['run']()
    assert result['reconciliation_API_calls'] == 0 and case['ledger'].read_bytes() == before
    assert any(row['status'] == 'candidate_unresolved_kept_charged' for row in result['observations'])
    assert not any(path.exists() for path in watched['paths'].values())


def test_auto_private_ledger_short_original_clock_defers_before_once(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1):
    case = _auto_private_ledger_case_v1(auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    watched = _auto_private_ledger_watch_v1(case, monkeypatch)
    before = case['ledger'].read_bytes()
    monkeypatch.setattr(recovery, 'reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1', lambda *args, **kwargs: pytest.fail('short clock entered accounting mutation'))
    result = watched['run'](deadline=time.monotonic() + 189.0)
    assert result['status'] == 'current_cycle_readonly_clock_shortfall_deferred'
    assert result['readiness_API_calls'] == 1 and result['reconciliation_API_calls'] == 0
    assert result['original_deadline_renewed'] is False
    assert not any(path.exists() for path in watched['paths'].values()) and case['ledger'].read_bytes() == before


@pytest.mark.parametrize('which', ['proof', 'receipt'])
@pytest.mark.parametrize('damage', ['missing-pin', 'both-missing', 'boolean-pin', 'malformed-pin'])
def test_auto_private_ledger_compact_evidence_requires_exact_hash_declarations(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, which, damage):
    case = _auto_private_ledger_case_v1(auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    entry = _auto_private_ledger_entry_v1(case)
    if which == 'proof':
        result = case['auto_unit']._private_completed_ledger_call(case);key = 'proof'
    else:
        result = case['auto_unit']._private_completed_ledger_call(case, 'reconcile');key = 'sampled_custody_proof'
    pins = json.loads(Path(entry['pins_ref']['path']).read_bytes())
    if damage in ('missing-pin', 'both-missing'):
        pins.pop('expected_request_sha256')
        if damage == 'both-missing': result[key].pop('request_sha256')
    else:
        pins['expected_request_sha256'] = True if damage == 'boolean-pin' else 'invalid'
        result[key]['request_sha256'] = pins['expected_request_sha256']
    entry['pins_ref'] = save(Path(entry['pins_ref']['path']), pins)
    before = case['ledger'].read_bytes()
    with pytest.raises(ValueError, match='complete exact private completed-ledger SHA256'):
        cli._capacity_current_private_completed_ledger_evidence_v1(entry, result, key)
    assert case['ledger'].read_bytes() == before


# Closed-parent candidate preparation UNIT_DATA only. Existing RCE owning
# helpers supply every fictional original frame; no historical failure is
# reauthored and this additive helper remains unwired to any live config.
def _auto_completed_candidate_prepare_case_v1(setup, monkeypatch, captured):
    case = _auto_private_ledger_case_v1(setup, monkeypatch, captured)
    old_entry = _auto_private_ledger_entry_v1(case)
    state = case['args']['roots'][1] / 'closed-original-candidate-state'
    state.mkdir(mode=0o700)
    monkeypatch.setattr(cli, 'CAPACITY_CURRENT_STATE', state)
    refs = {name: deepcopy(old_entry[name]) for name in (
        'recovery_profile', 'parent_ref', 'request_ref', 'stdout_ref', 'producer_ref')}
    key = cli._capacity_current_claim_key_v1(case['args']['reservation_id'])
    output = state / 'input-bundles' / ('completed-ledger-' + key)
    def run(*, selected=None, registered=None):
        deadline = time.monotonic() + 240.0
        with resources.native_deadlines.resource_cleanup_deadline(native_deadline_monotonic=deadline):
            return cli._capacity_current_prepare_closed_ledger_candidate_v1(
                refs if selected is None else selected,
                refs['request_ref'] if registered is None else registered,
                output, recovery, lambda: max(0.001, deadline - time.monotonic()))
    return case, refs, state, output, key, run


def test_auto_completed_candidate_builder_derives_complete_DATA_before_real_typed_readiness(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1):
    case, refs, state, output, key, run = _auto_completed_candidate_prepare_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    import stat
    before = case['ledger'].read_bytes()
    original = recovery._durable_inventory(case['args']['attempt_directory'])
    result = run();entry = result['entry']
    assert result['status'] == 'closed_original_candidate_prepared_not_enrolled'
    assert result['claim_key'] == key and result['detached_evidence_archives'] == 2
    assert result['readiness_API_calls'] == result['reconciliation_API_calls'] == result['disposition_API_calls'] == 0
    assert result['config_changed'] is result['once_started'] is result['retry_authorized'] is result['admitted'] is False
    assert set(entry) == {'reservation_id', 'record_ref', 'proof_ref', 'pins_ref', 'inventory_ref',
        'parent_ref', 'request_ref', 'stdout_ref', 'producer_ref', 'recovery_profile', 'sealed_artifacts'}
    assert json.loads(Path(entry['inventory_ref']['path']).read_bytes())['artifacts'] == original
    assert entry['parent_ref'] == refs['parent_ref'] and entry['request_ref'] == refs['request_ref']
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in output.iterdir())
    record, kwargs = cli._capacity_current_completed_candidate_data_v1(entry, recovery, lambda: 5.0)
    assert record == case['row']
    ready = case['auto_unit']._private_completed_ledger_call(case, **kwargs)
    assert ready['ready'] is True and ready['state_written'] is ready['recovery_performed'] is False
    assert case['ledger'].read_bytes() == before
    assert recovery._durable_inventory(case['args']['attempt_directory']) == original
    assert not any(state.glob('*.current-sampled-*-v01.json'))


def test_auto_completed_candidate_builder_repeat_reuses_exact_archives_without_fork(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1):
    case, refs, state, output, key, run = _auto_completed_candidate_prepare_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    first = run();images = {p.name: (p.read_bytes(), p.stat().st_ino) for p in output.iterdir()}
    second = run()
    assert second == first
    assert {p.name: (p.read_bytes(), p.stat().st_ino) for p in output.iterdir()} == images


@pytest.mark.parametrize('damage', ['wait', 'Source', 'Native', 'owner', 'child', 'source-drift', 'parent-return'])
def test_auto_completed_candidate_builder_refuses_pending_or_unknown_parent_before_publication(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, damage):
    case, refs, state, output, key, run = _auto_completed_candidate_prepare_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    parent = json.loads(Path(refs['parent_ref']['path']).read_bytes())
    if damage == 'Source': parent['source_closed'] = False
    elif damage == 'source-drift': parent['source_drift'] = ['authored-unit-change']
    elif damage == 'parent-return': parent['owner_returncode'] = True
    else:
        field = {'wait': 'genuine_wait_completed', 'Native': 'original_native_compute_closed',
            'owner': 'owner_identity_gone', 'child': 'child_reaped'}[damage]
        parent['original_owner_custody'][field] = False
    refs['parent_ref'] = save(Path(refs['parent_ref']['path']), parent)
    before = case['ledger'].read_bytes()
    with pytest.raises((ValueError, resources.DaemonResourceError)): run()
    assert not output.exists() and case['ledger'].read_bytes() == before


@pytest.mark.parametrize('damage', ['unregistered', 'profile', 'API-pin'])
def test_auto_completed_candidate_builder_requires_registered_request_and_current_proof_owner(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, damage):
    case, refs, state, output, key, run = _auto_completed_candidate_prepare_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    registered = deepcopy(refs['request_ref'])
    if damage == 'unregistered': registered['sha256'] = 'f' * 64
    elif damage == 'profile': refs['recovery_profile'] = cli.CAPACITY_COMPLETED_RECOVERY_PROFILE
    else: monkeypatch.setattr(cli, 'CAPACITY_CURRENT_API_SHA256', 'f' * 64)
    before = case['ledger'].read_bytes()
    with pytest.raises((ValueError, resources.DaemonResourceError)): run(registered=registered)
    assert not output.exists() and case['ledger'].read_bytes() == before


@pytest.mark.parametrize('which', ['result', 'execution', 'durability', 'unsealed-extra'])
def test_auto_completed_candidate_builder_never_publishes_partial_or_changed_sealed_history(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, which):
    case, refs, state, output, key, run = _auto_completed_candidate_prepare_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    if which == 'unsealed-extra':
        (case['args']['attempt_directory'] / 'exports/after-seal-extra.txt').write_bytes(b'authored unsealed DATA\n')
    else: Path(case['sealed_artifacts'][which]['path']).unlink()
    before = case['ledger'].read_bytes()
    with pytest.raises((ValueError, OSError, resources.DaemonResourceError)): run()
    assert not output.exists() and case['ledger'].read_bytes() == before


@pytest.mark.parametrize('damage', ['missing', 'released', 'changed-retained'])
def test_auto_completed_candidate_builder_requires_the_original_current_retained_row(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, damage):
    case, refs, state, output, key, run = _auto_completed_candidate_prepare_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    data = json.loads(case['ledger'].read_bytes());rid = case['args']['reservation_id']
    if damage == 'missing': data['reservations'].pop(rid)
    elif damage == 'released': data['reservations'][rid]['status'] = 'released'
    else: data['reservations'][rid]['retention_reason'] = 'authored-different-retained-frame'
    case['ledger'].write_text(json.dumps(data));before = case['ledger'].read_bytes()
    with pytest.raises((ValueError, resources.DaemonResourceError)): run()
    assert not output.exists() and case['ledger'].read_bytes() == before


@pytest.mark.parametrize('phase', ['started', 'returned', 'verified', 'failure'])
def test_auto_completed_candidate_builder_cannot_reset_manual_or_watcher_once_state(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, phase):
    case, refs, state, output, key, run = _auto_completed_candidate_prepare_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    marker = state / (key + '.current-sampled-' + phase + '-v01.json')
    marker.write_bytes(b'preserved authored once-state; no replay\n');before = case['ledger'].read_bytes()
    result = run()
    assert result['status'] == 'existing_claim_once_state_preserved_no_enrollment'
    assert result['candidate_ref'] is None and not output.exists()
    assert marker.read_bytes() == b'preserved authored once-state; no replay\n'
    assert case['ledger'].read_bytes() == before


def test_auto_completed_candidate_builder_preserves_partial_conflicting_DATA_without_candidate(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1):
    case, refs, state, output, key, run = _auto_completed_candidate_prepare_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    output.mkdir(mode=0o700, parents=True)
    old = output / 'original-proof.json';old.write_bytes(b'preserved partial authored archive\n');old.chmod(0o600)
    before = case['ledger'].read_bytes()
    with pytest.raises(ValueError, match='partial or changed'): run()
    assert old.read_bytes() == b'preserved partial authored archive\n'
    assert not (output / 'candidate.json').exists() and case['ledger'].read_bytes() == before


def test_auto_completed_candidate_builder_does_not_create_a_new_cleanup_clock(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1):
    case, refs, state, output, key, run = _auto_completed_candidate_prepare_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    assert resources.native_deadlines.resource_operation_deadline() is None
    with pytest.raises(resources.DaemonResourceError, match='existing absolute cleanup deadline'):
        cli._capacity_current_prepare_closed_ledger_candidate_v1(
            refs, refs['request_ref'], output, recovery, lambda: 240.0)
    assert not output.exists()


@pytest.mark.parametrize('which', ['owner', 'child'])
def test_auto_completed_candidate_builder_rechecks_current_original_process_absence(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, which):
    case, refs, state, output, key, run = _auto_completed_candidate_prepare_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    target = case['row']['owner_pid'] if which == 'owner' else case['row']['child']['pid']
    old = resources._process
    monkeypatch.setattr(resources, '_process', lambda pid: {'pid': target} if pid == target else old(pid))
    before = case['ledger'].read_bytes()
    with pytest.raises(resources.DaemonResourceError, match='PID still exists'): run()
    assert not output.exists() and case['ledger'].read_bytes() == before


def test_auto_completed_candidate_builder_refuses_an_unregistered_detached_output_root(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1):
    case, refs, state, output, key, run = _auto_completed_candidate_prepare_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    deadline = time.monotonic() + 240.0
    with resources.native_deadlines.resource_cleanup_deadline(native_deadline_monotonic=deadline):
        with pytest.raises(ValueError, match='fixed claim-bound'):
            cli._capacity_current_prepare_closed_ledger_candidate_v1(
                refs, refs['request_ref'], state / 'foreign-output', recovery, lambda: 5.0)
    assert not output.exists() and not (state / 'foreign-output').exists()


# Root completion registration is fictional UNIT_DATA in these controls. The
# admitted config descriptor, actual one-shot chain contract and existing RCE
# proof owner are exercised; no test claims a genuine historical Root job.
def _auto_completed_registered_watch_case_v1(setup, monkeypatch, captured, *, closed=True):
    case = _auto_private_ledger_case_v1(setup, monkeypatch, captured)
    watched = _auto_private_ledger_watch_v1(case, monkeypatch)
    entry = watched['entry'];packet = Path(entry['request_ref']['path']).parent
    driver = save(packet / 'fictional-completion-driver.pydata', {'fictional': 'never executed source DATA'})
    parent = save(packet / 'run-original-source-held-owner-v02-acquired-v5.py', {'fictional': 'never executed parent DATA'})
    selection = dict(schema='Root-owned-original-parent-completion-selection/v1', driver=driver,
        expected_original_parent_returncode=0, expected_scope={'cases': 1, 'functions': 1},
        lock_policy=driver, observer_module=driver, packet_directory=str(packet), parent=parent,
        plan=driver, profile='UNIT-explicitly-admitted-original', ready=driver,
        ready_entry_label='UNIT-closed-original', request=entry['request_ref'],
        selection_nonce='a' * 32, source_full9={})
    selection_ref = save(packet / 'fictional-pre-execution-selection.json', selection)
    # Registration identifies the actual original producer path, while the
    # older manual fixture's .pydata descriptor is only its captured byte copy.
    producer_path = Path(case['terminal']['source_custody_lifecycle']['producer']['path'])
    assert producer_path.read_bytes() == case['proof']['producer_source_utf8'].encode('utf-8')
    declaration = dict(selection_ref=selection_ref, expected_driver_ref=driver,
        expected_profile=selection['profile'], producer_ref=pin(producer_path))
    watched['config'].update(schema='legal-ir-retained-capacity-watch-config/v3',
        candidates=[], registered_originals=[declaration])
    stem = 'Root-original-completion-' + entry['request_ref']['sha256']
    intent = dict(schema='Root-owned-one-shot-completion-intent/v1', completion_source=driver,
        selection=selection_ref, request_sha256=entry['request_ref']['sha256'], parent_sha256=parent['sha256'],
        ready_sha256=driver['sha256'], profile=selection['profile'], maximum_parent_invocations=1,
        automatic_retry=False, original_parent_seconds=420,
        original_productive_seconds=case['request']['timeout_seconds'],
        original_storage_bytes=case['row']['storage_bytes'], Source_or_Native_calls_by_selector=0)
    intent_ref = save(packet / (stem + '-intent.json'), intent)
    save(packet / (stem + '-run-claimed.json'), dict(pid=1900000001, birth='101', intent_sha256=intent_ref['sha256'],
        selection=selection_ref, maximum_invocations=1))
    save(packet / (stem + '-invoking.json'), dict(argv=['/usr/bin/python3', '-I', '-B', parent['path']],
        maximum_invocations=1, parent_sha256=parent['sha256'], request_sha256=entry['request_ref']['sha256'],
        selection=selection_ref))
    save(packet / (stem + '-parent-started.json'), dict(pid=1900000002, birth='102',
        parent_sha256=parent['sha256'], request_sha256=entry['request_ref']['sha256']))
    save(packet / 'started.json', dict(pid=case['row']['owner_pid'], birth=case['row']['owner_birth'],
        request_sha256=entry['request_ref']['sha256'], time=1.0))
    outcome = dict(schema='Root-owned-original-parent-completion/v1', selection=selection_ref,
        profile=selection['profile'], request_sha256=entry['request_ref']['sha256'], parent_sha256=parent['sha256'],
        original_parent_invocations=1, maximum_parent_invocations=1, original_parent_genuine_wait_completed=True,
        automatic_retry=False, status='same_original_parent_waited', parent_returncode=1,
        completion_pid=1900000001, completion_birth='101', original_parent_pid=1900000002, original_parent_birth='102')
    outcome_path = packet / (stem + '-outcome.json')
    if closed: save(outcome_path, outcome)
    return case, watched, declaration, outcome_path, outcome


def test_auto_completed_registered_wiring_prepares_API0_then_existing_single_closeout_next_cycle(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1):
    case, watched, declaration, outcome_path, outcome = _auto_completed_registered_watch_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    before = case['ledger'].read_bytes();first = watched['run']()
    assert first['status'] == 'registered_original_candidate_prepared_API0'
    assert first['readiness_API_calls'] == first['reconciliation_API_calls'] == first['disposition_API_calls'] == 0
    assert case['ledger'].read_bytes() == before and not any(p.exists() for p in watched['paths'].values())
    candidate = first['prepared_candidate_ref'];raw = Path(candidate['path']).read_bytes()
    second = watched['run']()
    assert second['readiness_API_calls'] == second['reconciliation_API_calls'] == second['disposition_API_calls'] == 1
    assert watched['paths']['returned'].exists() and watched['paths']['verified'].exists()
    assert Path(candidate['path']).read_bytes() == raw
    images = {k: p.read_bytes() for k, p in watched['paths'].items() if p.exists()}
    third = watched['run']()
    assert third['reconciliation_API_calls'] == 0
    assert {k: p.read_bytes() for k, p in watched['paths'].items() if p.exists()} == images
    assert json.loads(case['ledger'].read_bytes())['reservations'][case['row']['reservation_id']]['status'] == 'released'


@pytest.mark.parametrize('damage', ['pending', 'not-waited', 'wrong-selection', 'wrong-parent', 'wrong-driver', 'CLI-birth'])
def test_auto_completed_registered_wiring_never_enrolls_pending_or_forked_parent_chain(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, damage):
    case, watched, declaration, outcome_path, outcome = _auto_completed_registered_watch_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, closed=damage != 'pending')
    if damage == 'not-waited': outcome['original_parent_genuine_wait_completed'] = False;save(outcome_path, outcome)
    elif damage == 'wrong-selection': outcome['selection'] = dict(outcome['selection'], sha256='f' * 64);save(outcome_path, outcome)
    elif damage == 'wrong-parent': outcome['original_parent_birth'] = '999';save(outcome_path, outcome)
    elif damage == 'wrong-driver': declaration['expected_driver_ref'] = dict(declaration['expected_driver_ref'], sha256='f' * 64)
    elif damage == 'CLI-birth':
        path = outcome_path.parent / 'started.json';value = json.loads(path.read_bytes());value['birth'] = '999';save(path, value)
    before = case['ledger'].read_bytes();result = watched['run']()
    assert result['reconciliation_API_calls'] == result['readiness_API_calls'] == 0
    assert case['ledger'].read_bytes() == before and not any(p.exists() for p in watched['paths'].values())
    assert not any(watched['state'].rglob('candidate.json'))


def test_auto_completed_registered_wiring_deduplicates_and_restarts_from_exact_prepared_entry(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1):
    case, watched, declaration, outcome_path, outcome = _auto_completed_registered_watch_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    watched['config']['registered_originals'].append(deepcopy(declaration))
    first = watched['run']();pin_before = first['prepared_candidate_ref']
    assert len(list(watched['state'].rglob('candidate.json'))) == 1
    second = watched['run']()
    assert second['reconciliation_API_calls'] == 1
    assert any(row['status'] == 'identical_registration_deduplicated' for row in second['observations'])
    assert pin(Path(pin_before['path'])) == pin_before


@pytest.mark.parametrize('phase', ['started', 'returned', 'verified', 'failure'])
def test_auto_completed_registered_wiring_preserves_every_preexisting_manual_once_state(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, phase):
    case, watched, declaration, outcome_path, outcome = _auto_completed_registered_watch_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    marker = watched['paths'][phase];marker.write_bytes(b'authored manual once state; never replay\n')
    before = case['ledger'].read_bytes();result = watched['run']()
    assert result['reconciliation_API_calls'] == result['readiness_API_calls'] == 0
    assert marker.read_bytes() == b'authored manual once state; never replay\n'
    assert case['ledger'].read_bytes() == before and not any(watched['state'].rglob('candidate.json'))


def test_auto_completed_registered_wiring_full_frontier_keeps_originals_unpublished_and_charged(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1):
    case, watched, declaration, outcome_path, outcome = _auto_completed_registered_watch_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    watched['config']['candidates'] = [dict(watched['entry'], reservation_id=f'{number+1:032x}') for number in range(16)]
    before = case['ledger'].read_bytes();result = watched['run']()
    assert any(row['status'] == 'registered_frontier_full_no_preparation' for row in result['observations'])
    assert result['reconciliation_API_calls'] == 0 and case['ledger'].read_bytes() == before
    assert not any(watched['state'].rglob('candidate.json'))


@pytest.mark.parametrize('damage', ['extra', 'no-registrations', 'too-many-registrations', 'too-many-candidates'])
def test_auto_completed_registered_config_is_explicit_finite_and_keeps_v2_unchanged(monkeypatch, damage):
    config = dict(schema='legal-ir-retained-capacity-watch-config/v3', profile=cli.CAPACITY_CURRENT_PROFILE,
        expected_cli_sha256='a' * 64, expected_policy_sha256=cli.CAPACITY_CURRENT_POLICY_SHA256,
        source_capture_ref={'unit': 'existing source guard tested separately'}, state_directory=str(cli.CAPACITY_CURRENT_STATE),
        root_identities=[], triggers=[{}], candidates=[], registered_originals=[dict(selection_ref={},
            expected_driver_ref={}, expected_profile='UNIT-registered-original', producer_ref={})])
    if damage == 'extra': config['renew_budget'] = True
    elif damage == 'no-registrations': config['registered_originals'] = []
    elif damage == 'too-many-registrations': config['registered_originals'] *= 17
    else: config['candidates'] = [{}] * 17
    monkeypatch.setattr(cli, '_capacity_current_config_sources_v1', lambda *args: pytest.fail('invalid v3 reached common Source capture guard'))
    with pytest.raises(ValueError): cli._capacity_current_registered_config_v1(config, {'sha256': 'a' * 64})


@pytest.mark.parametrize('which', ['completion', 'parent'])
def test_auto_completed_registered_wiring_foreign_PID_generation_does_not_stall_original_closeout(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, which):
    case, watched, declaration, outcome_path, outcome = _auto_completed_registered_watch_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    target = outcome['completion_pid'] if which == 'completion' else outcome['original_parent_pid']
    original_process = resources._process
    monkeypatch.setattr(resources, '_process', lambda pid: {'pid': target, 'birth': '999'}
        if pid == target else original_process(pid))
    first = watched['run']()
    assert first['status'] == 'registered_original_candidate_prepared_API0'
    assert first['reconciliation_API_calls'] == 0
    # The foreign observer/wrapper generation is never signaled or treated as
    # the original CLI/Native owner. Real full1508 readiness/reconcile remain.
    second = watched['run']()
    assert second['readiness_API_calls'] == second['reconciliation_API_calls'] == second['disposition_API_calls'] == 1
    assert watched['paths']['verified'].exists()


@pytest.mark.parametrize('which', ['completion', 'parent'])
def test_auto_completed_registered_wiring_same_birth_stays_pending_without_publication(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, which):
    case, watched, declaration, outcome_path, outcome = _auto_completed_registered_watch_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    target = outcome['completion_pid'] if which == 'completion' else outcome['original_parent_pid']
    birth = outcome['completion_birth'] if which == 'completion' else outcome['original_parent_birth']
    original_process = resources._process
    monkeypatch.setattr(resources, '_process', lambda pid: {'pid': target, 'birth': birth}
        if pid == target else original_process(pid))
    before = case['ledger'].read_bytes();result = watched['run']()
    assert result['status'] == 'registered_frontier_pending_no_candidate'
    assert result['readiness_API_calls'] == result['reconciliation_API_calls'] == 0
    assert case['ledger'].read_bytes() == before and not any(watched['state'].rglob('candidate.json'))


def test_auto_completed_registered_wiring_known_return_restart_finishes_readonly_under_saved_end(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1):
    case, watched, declaration, outcome_path, outcome = _auto_completed_registered_watch_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    assert watched['run']()['status'] == 'registered_original_candidate_prepared_API0'
    original_disposition = recovery.inspect_validation_disposition
    def interrupted(*args, **kwargs):
        raise OSError('authored registered postwrite interruption')
    monkeypatch.setattr(recovery, 'inspect_validation_disposition', interrupted)
    with pytest.raises(OSError, match='authored registered postwrite'):
        watched['run']()
    assert watched['paths']['returned'].exists() and not watched['paths']['verified'].exists()
    saved = json.loads(watched['paths']['started'].read_bytes())['original_deadline_monotonic']
    history = {name: watched['paths'][name].read_bytes() for name in ('started', 'returned', 'failure')}
    before = case['ledger'].read_bytes();observed_ends = []
    original_end = cli._capacity_current_original_deadline_v1
    def observe_end(*args):
        end = original_end(*args);observed_ends.append(end);return end
    monkeypatch.setattr(cli, '_capacity_current_original_deadline_v1', observe_end)
    monkeypatch.setattr(recovery, 'inspect_validation_disposition', original_disposition)
    monkeypatch.setattr(recovery, 'reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1',
        lambda *args, **kwargs: pytest.fail('registered restart replayed returned accounting mutation'))
    result = watched['run'](deadline=time.monotonic() + 600.0)
    assert result['status'] == 'known_returned_typed_API_postwrite_completed_readonly'
    assert result['reconciliation_API_calls'] == 0 and watched['paths']['verified'].exists()
    assert observed_ends and all(end <= saved for end in observed_ends)
    assert all(watched['paths'][name].read_bytes() == body for name, body in history.items())
    assert case['ledger'].read_bytes() == before


def test_auto_completed_registered_wiring_cached_UNKNOWN_reaches_existing_no_replay_owner(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1):
    case, watched, declaration, outcome_path, outcome = _auto_completed_registered_watch_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    first = watched['run']();candidate = json.loads(Path(first['prepared_candidate_ref']['path']).read_bytes())
    save(watched['paths']['started'], dict(profile=cli.CAPACITY_CURRENT_PROFILE, candidate=candidate))
    before = case['ledger'].read_bytes();history = watched['paths']['started'].read_bytes()
    monkeypatch.setattr(recovery, 'reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1',
        lambda *args, **kwargs: pytest.fail('registered UNKNOWN replayed mutation'))
    result = watched['run']()
    assert any(row['status'] == 'original_outcome_unknown_no_mutation_replay' for row in result['observations'])
    assert result['reconciliation_API_calls'] == result['readiness_API_calls'] == 0
    assert watched['paths']['started'].read_bytes() == history and not watched['paths']['returned'].exists()
    assert case['ledger'].read_bytes() == before


@pytest.mark.parametrize('history', ['verified', 'UNKNOWN'])
def test_auto_completed_registered_wiring_finished_or_unknown_history_cannot_starve_second_registration(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, history):
    case, watched, first_declaration, outcome_path, outcome = _auto_completed_registered_watch_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    first = watched['run']();candidate = json.loads(Path(first['prepared_candidate_ref']['path']).read_bytes())
    if history == 'verified':
        assert watched['run']()['reconciliation_API_calls'] == 1
        assert json.loads(case['ledger'].read_bytes())['reservations'][case['row']['reservation_id']]['status'] == 'released'
        assert watched['paths']['verified'].exists()
    else:
        save(watched['paths']['started'], dict(profile=cli.CAPACITY_CURRENT_PROFILE, candidate=candidate))
    old_markers = {name: path.read_bytes() for name, path in watched['paths'].items() if path.exists()}
    old_files = {p: p.read_bytes() for p in case['args']['attempt_directory'].rglob('*') if p.is_file()}
    before = case['ledger'].read_bytes()
    # SECOND-only routing double: no second custody proof, eligibility or
    # candidate publication is claimed. First original uses the real adapter,
    # preparation helper and1508; a sentinel proves another claim is reached.
    folder = watched['state'] / 'SECOND-routing-UNIT-DATA';folder.mkdir()
    second_id = 'e' * 32
    assert second_id != case['row']['reservation_id']
    second_parent = save(folder / 'parent.json', dict(source_closed=True, source_drift=[]))
    second_stdout = save(folder / 'terminal.json', dict(reservation={'record': {'reservation_id': second_id}}))
    second = dict(first_declaration, selection_ref=dict(first_declaration['selection_ref'], sha256='e' * 64))
    watched['config']['registered_originals'].append(second)
    real_adapter = cli._capacity_current_registered_original_v1
    def adapter(declaration, owner):
        if declaration == second:
            return dict(status='SECOND-routing-UNIT-DATA-only', original_refs=dict(
                recovery_profile=cli.CAPACITY_PRIVATE_COMPLETED_LEDGER_RECOVERY_PROFILE,
                parent_ref=second_parent, stdout_ref=second_stdout, request_ref=second['selection_ref'],
                producer_ref=second['producer_ref']))
        return real_adapter(declaration, owner)
    reached = []
    class SecondPreparationReached(AssertionError):
        pass
    real_prepare = cli._capacity_current_prepare_closed_ledger_candidate_v1
    def prepare(refs, *args):
        if refs['stdout_ref'] == second_stdout:
            reached.append(second_id);raise SecondPreparationReached('second preparation reached without API')
        return real_prepare(refs, *args)
    monkeypatch.setattr(cli, '_capacity_current_registered_original_v1', adapter)
    monkeypatch.setattr(cli, '_capacity_current_prepare_closed_ledger_candidate_v1', prepare)
    monkeypatch.setattr(recovery, 'reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1',
        lambda *args, **kwargs: pytest.fail('history or SECOND routing control entered mutation'))
    with pytest.raises(SecondPreparationReached): watched['run']()
    assert reached == [second_id]
    assert {name: watched['paths'][name].read_bytes() for name in old_markers} == old_markers
    assert {p: p.read_bytes() for p in old_files} == old_files and case['ledger'].read_bytes() == before
    assert len(list(watched['state'].rglob('candidate.json'))) == 1


# Fictional engineering clocks below exercise the actual existing API1508
# reconciliation/inventory/once owners. They are not historical Root execution.
def _registered_adaptive_clock_case_v1(setup, monkeypatch, captured):
    case, watched, declaration, outcome_path, outcome = _auto_completed_registered_watch_case_v1(
        setup, monkeypatch, captured)
    clock = [1000.0]
    monkeypatch.setattr(time, 'monotonic', lambda: clock[0])
    assert watched['run']()['status'] == 'registered_original_candidate_prepared_API0'
    return case, watched, clock


@pytest.mark.parametrize('original,inherited,now', [
    (1240.0, 1240.0, 1051.6439106520265),
    (1300.0, 1240.0, 1051.6439106520265),
    (True, 1240.0, 1051.0),
    (1240.0, float('inf'), 1051.0),
])
def test_registered_adaptive_window_borrows_original_parent_and_rejects_invalid_clocks(
        original, inherited, now):
    if type(original) is bool or inherited == float('inf'):
        with pytest.raises(ValueError, match='finite original'):
            cli._capacity_current_registered_cleanup_window_v1(original, inherited, now)
        return
    window = cli._capacity_current_registered_cleanup_window_v1(original, inherited, now)
    assert window['enough_original_time'] is True
    assert window['original_deadline_monotonic'] == min(original, inherited) == 1240.0
    assert window['mutation_deadline_monotonic'] == 1165.0
    assert window['mutation_seconds'] == pytest.approx(113.3560893479735)
    assert window['postwrite_and_Source_close_forecast_seconds'] == 75.0
    assert window['scheduling_forecast_not_IO_guarantee'] is True
    assert window['original_deadline_renewed'] is False


@pytest.mark.parametrize('delay_phase', ['initial-census', 'readiness'])
def test_registered_adaptive_slow_readiness_runs_real_two_census_closeout_with_same_parent(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, delay_phase):
    case, watched, clock = _registered_adaptive_clock_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    original_inventory = recovery._durable_inventory(case['args']['attempt_directory'])
    original_frames = deepcopy((case['request'], case['terminal'], case['parent']))
    native_before = deepcopy(case['scheduler_state'])
    census = recovery._administrative_census;inspect = recovery.inspect_private_snapshot_completed_ledger_finalization_validation_recovery_v1
    reconcile = recovery.reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1
    put = cli._capacity_recovery_put;inspection = recovery._validation_inspection_lock
    phases = [];parents = [];mutation_contexts = [];returned_contexts = [];tail_locks = []
    def timed_census(owner, ledger):
        phases.append('census')
        result = census(owner, ledger)
        if len(phases) == 1:
            if delay_phase == 'initial-census': clock[0] += 51.64391065202653
        else:
            clock[0] += 49.0
        return result
    def timed_readiness(*args, **kwargs):
        parents.append(native.resource_operation_deadline())
        result = inspect(*args, **kwargs)
        if delay_phase == 'readiness': clock[0] += 51.64391065202653
        return result
    def bounded_mutation(*args, **kwargs):
        current = native.resource_operation_deadline();mutation_contexts.append(current)
        assert current.cleanup_only is True and current.native_deadline_monotonic == 1165.0
        assert 0 < kwargs['ledger_lock_timeout_seconds'] <= 5.0
        return reconcile(*args, **kwargs)
    def observe_return(path, value):
        if Path(path) == watched['paths']['returned']:
            returned_contexts.append(native.resource_operation_deadline())
            assert returned_contexts[-1] is parents[-1]
        return put(path, value)
    @contextmanager
    def bounded_inspection(owner):
        if watched['paths']['returned'].exists():
            tail_locks.append(owner.ledger_lock_timeout_seconds)
            assert 0 < owner.ledger_lock_timeout_seconds <= 5.0
        with inspection(owner): yield
    monkeypatch.setattr(recovery, '_administrative_census', timed_census)
    monkeypatch.setattr(recovery, 'inspect_private_snapshot_completed_ledger_finalization_validation_recovery_v1', timed_readiness)
    monkeypatch.setattr(recovery, 'reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1', bounded_mutation)
    monkeypatch.setattr(recovery, '_validation_inspection_lock', bounded_inspection)
    monkeypatch.setattr(cli, '_capacity_recovery_put', observe_return)
    with native.resource_cleanup_deadline(native_deadline_monotonic=1240.0):
        parent = native.resource_operation_deadline()
        result = watched['run'](deadline=1240.0)
        assert native.resource_operation_deadline() is parent
    assert native.resource_operation_deadline() is None
    assert result['readiness_API_calls'] == result['reconciliation_API_calls'] == result['disposition_API_calls'] == 1
    assert len(phases) == 4 and len(mutation_contexts) == len(returned_contexts) == 1 and tail_locks
    started = json.loads(watched['paths']['started'].read_bytes())
    assert started['original_started_monotonic'] == 1000.0 and started['original_deadline_monotonic'] == 1240.0
    assert started['mutation_window']['mutation_deadline_monotonic'] == 1165.0
    returned = json.loads(watched['paths']['returned'].read_bytes())
    assert returned['actual_receipt']['fresh_global_inventory_count'] == 2
    assert watched['paths']['verified'].exists() and not watched['paths']['failure'].exists()
    assert json.loads(case['ledger'].read_bytes())['reservations'][case['row']['reservation_id']]['status'] == 'released'
    assert recovery._durable_inventory(case['args']['attempt_directory']) == original_inventory
    assert (case['request'], case['terminal'], case['parent']) == original_frames
    assert case['scheduler_state'] == native_before and clock[0] < 1240.0


@pytest.mark.parametrize('remaining', [184.999, 100.0])
def test_registered_adaptive_insufficient_forecast_keeps_real_readiness_but_no_once(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, remaining):
    case, watched, clock = _registered_adaptive_clock_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    before = case['ledger'].read_bytes();inspect = recovery.inspect_private_snapshot_completed_ledger_finalization_validation_recovery_v1
    def delayed_readiness(*args, **kwargs):
        result = inspect(*args, **kwargs);clock[0] = 1240.0 - remaining;return result
    monkeypatch.setattr(recovery, 'inspect_private_snapshot_completed_ledger_finalization_validation_recovery_v1', delayed_readiness)
    monkeypatch.setattr(recovery, 'reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1',
        lambda *args, **kwargs: pytest.fail('insufficient original phase budget reached mutation'))
    result = watched['run'](deadline=1240.0)
    assert result['status'] == 'current_cycle_readonly_clock_shortfall_deferred'
    assert result['readiness_API_calls'] == 1 and result['reconciliation_API_calls'] == result['disposition_API_calls'] == 0
    assert result['original_deadline_renewed'] is False
    observation = next(row for row in result['observations'] if row['status'] == 'candidate_readonly_clock_shortfall_deferred')
    assert observation['original_remaining_seconds'] == pytest.approx(remaining)
    assert observation['mutation_window']['minimum_mutation_forecast_seconds'] == 110.0
    assert observation['mutation_window']['postwrite_and_Source_close_forecast_seconds'] == 75.0
    assert not any(path.exists() for path in watched['paths'].values()) and case['ledger'].read_bytes() == before


@pytest.mark.parametrize('expire_census', [2, 3])
def test_registered_adaptive_each_prewrite_census_expiry_keeps_row_and_UNKNOWN_no_replay(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, expire_census):
    case, watched, clock = _registered_adaptive_clock_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    census = recovery._administrative_census;inspect = recovery.inspect_private_snapshot_completed_ledger_finalization_validation_recovery_v1
    reconcile = recovery.reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1
    before = case['ledger'].read_bytes();count = [0];mutations = []
    def slow_readiness(*args, **kwargs):
        result = inspect(*args, **kwargs);clock[0] += 51.64391065202653;return result
    def expiry_census(owner, ledger):
        count[0] += 1;result = census(owner, ledger)
        if count[0] == expire_census:
            current = native.resource_operation_deadline()
            assert current.native_deadline_monotonic == 1165.0
            clock[0] = current.native_deadline_monotonic
        return result
    def mutation(*args, **kwargs):
        mutations.append(1);return reconcile(*args, **kwargs)
    monkeypatch.setattr(recovery, '_administrative_census', expiry_census)
    monkeypatch.setattr(recovery, 'inspect_private_snapshot_completed_ledger_finalization_validation_recovery_v1', slow_readiness)
    monkeypatch.setattr(recovery, 'reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1', mutation)
    with native.resource_cleanup_deadline(native_deadline_monotonic=1240.0):
        parent = native.resource_operation_deadline()
        with pytest.raises(native.ResourceAdmissionDeadlineError, match='original absolute'):
            watched['run'](deadline=1240.0)
        assert native.resource_operation_deadline() is parent
    assert native.resource_operation_deadline() is None
    assert len(mutations) == 1 and case['ledger'].read_bytes() == before
    assert watched['paths']['started'].exists() and watched['paths']['failure'].exists()
    assert not watched['paths']['returned'].exists() and not watched['paths']['verified'].exists()
    history = {name:path.read_bytes()for name,path in watched['paths'].items()if path.exists()}
    monkeypatch.setattr(recovery, 'reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1',
        lambda *args, **kwargs: pytest.fail('UNKNOWN mutation outcome replayed'))
    result = watched['run'](deadline=clock[0] + 240.0)
    assert result['reconciliation_API_calls'] == 0 and len(mutations) == 1
    assert {name:path.read_bytes()for name,path in watched['paths'].items()if path.exists()} == history
    assert case['ledger'].read_bytes() == before


@pytest.mark.parametrize('expired_original', [False, True])
def test_registered_adaptive_genuine_return_precedes_tail_error_and_same_end_readonly_restart(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, expired_original):
    case, watched, clock = _registered_adaptive_clock_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    census = recovery._administrative_census;inspect = recovery.inspect_private_snapshot_completed_ledger_finalization_validation_recovery_v1
    reconcile = recovery.reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1
    disposition = recovery.inspect_validation_disposition;put = cli._capacity_recovery_put
    calls = [0];mutations = [];parents = [];returned_contexts = []
    def timed_census(owner, ledger):
        calls[0] += 1;result = census(owner, ledger)
        if calls[0] > 1: clock[0] += 20.0
        return result
    def slow_readiness(*args, **kwargs):
        parents.append(native.resource_operation_deadline());result = inspect(*args, **kwargs)
        clock[0] += 51.64391065202653;return result
    def mutation(*args, **kwargs):
        mutations.append(1);return reconcile(*args, **kwargs)
    def observe_return(path, value):
        if Path(path) == watched['paths']['returned']:
            returned_contexts.append(native.resource_operation_deadline())
            assert returned_contexts[-1] is parents[-1]
        return put(path, value)
    def failed_tail(*args, **kwargs):raise OSError('authored adaptive postwrite interruption')
    monkeypatch.setattr(recovery, '_administrative_census', timed_census)
    monkeypatch.setattr(recovery, 'inspect_private_snapshot_completed_ledger_finalization_validation_recovery_v1', slow_readiness)
    monkeypatch.setattr(recovery, 'reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1', mutation)
    monkeypatch.setattr(recovery, 'inspect_validation_disposition', failed_tail)
    monkeypatch.setattr(cli, '_capacity_recovery_put', observe_return)
    with pytest.raises(OSError, match='authored adaptive postwrite'):
        watched['run'](deadline=1240.0)
    assert native.resource_operation_deadline() is None
    assert len(mutations) == len(returned_contexts) == 1
    assert watched['paths']['returned'].exists() and not watched['paths']['verified'].exists()
    row = json.loads(case['ledger'].read_bytes())['reservations'][case['row']['reservation_id']]
    assert row['status'] == 'released'
    history = {name:watched['paths'][name].read_bytes()for name in ['started','returned','failure']}
    saved = json.loads(history['started'])['original_deadline_monotonic'];ends = []
    original_end = cli._capacity_current_original_deadline_v1
    def observe_end(*args):
        result = original_end(*args);ends.append(result);return result
    monkeypatch.setattr(cli, '_capacity_current_original_deadline_v1', observe_end)
    monkeypatch.setattr(recovery, 'inspect_validation_disposition', disposition)
    monkeypatch.setattr(recovery, 'reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1',
        lambda *args, **kwargs: pytest.fail('returned adaptive mutation replayed'))
    if expired_original: clock[0] = saved + 1.0
    before = case['ledger'].read_bytes();result = watched['run'](deadline=clock[0] + 600.0)
    assert result['reconciliation_API_calls'] == 0 and len(mutations) == 1
    if expired_original:
        assert not watched['paths']['verified'].exists() and not ends
        assert any(row['status'] == 'original_readonly_clock_unavailable_no_replay'
            for row in result['observations'])
    else:
        assert result['status'] == 'known_returned_typed_API_postwrite_completed_readonly'
        assert watched['paths']['verified'].exists()
        assert ends and all(end <= saved == 1240.0 for end in ends)
    assert case['ledger'].read_bytes() == before
    assert all(watched['paths'][name].read_bytes() == value for name,value in history.items())
    assert native.resource_operation_deadline() is None



def _auto_completed_current_v5_select_fixture(monkeypatch):
    from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_resource_recovery as unit
    unit._current_v5_pair_select_completed_fixture(monkeypatch)


def test_auto_completed_current_V5_pair_registration_runs_existing_API0_then_single_closeout(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1):
    _auto_completed_current_v5_select_fixture(monkeypatch)
    test_auto_completed_registered_wiring_prepares_API0_then_existing_single_closeout_next_cycle(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)


@pytest.mark.parametrize('damage', ['cross-sdk', 'missing-sdk', 'V6-schema', 'V6-field', 'unqualified-parent'])
def test_auto_completed_current_V5_registration_refuses_unqualified_input_before_candidate(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, damage):
    _auto_completed_current_v5_select_fixture(monkeypatch)
    case, watched, declaration, outcome_path, outcome = _auto_completed_registered_watch_case_v1(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    selection = json.loads(Path(declaration['selection_ref']['path']).read_bytes())
    request_path = Path(selection['request']['path'])
    request = json.loads(request_path.read_bytes())
    sdk = str(Path(declaration['producer_ref']['path']).parents[3] /
        'ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py')
    if damage == 'cross-sdk': request['source_sha256'][sdk] = '4df3f7f2c6d2952550dd78153b579f4e928e9f119e697bded8a7dc001021f8d2'
    elif damage == 'missing-sdk': request['source_sha256'].pop(sdk)
    elif damage == 'V6-schema': request['schema'] = 'owned-validation-request/v6'
    elif damage == 'V6-field': request['startup_clock_profile'] = {'schema': 'unqualified'}
    else:
        old_parent = Path(selection['parent']['path'])
        wrong_parent = request_path.parent / 'A-parent-source-closeout@2.py'
        wrong_parent.write_bytes(old_parent.read_bytes())
        wrong_parent.chmod(0o600)
        selection['parent'] = pin(wrong_parent)
    selection['request'] = save(request_path, request)
    declaration['selection_ref'] = save(Path(declaration['selection_ref']['path']), selection)
    before = case['ledger'].read_bytes()
    with pytest.raises(ValueError):
        cli._capacity_current_registered_original_v1(declaration, recovery)
    assert case['ledger'].read_bytes() == before
    assert not any(watched['paths'][name].exists() for name in watched['paths'])


@pytest.mark.parametrize('damage', ['owner-sdk', 'subject-sdk', 'subject-producer'])
def test_auto_completed_current_V5_compact_summary_rejects_mixed_source_tuple(
        auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1, damage):
    _auto_completed_current_v5_select_fixture(monkeypatch)
    case = _auto_private_ledger_case_v1(auto_completed_setup_v1, monkeypatch, auto_completed_captured_producers_v1)
    entry = _auto_private_ledger_entry_v1(case)
    record, kwargs = cli._capacity_current_completed_candidate_data_v1(entry, recovery, lambda: 5.0)
    ready = case['auto_unit']._private_completed_ledger_call(case, **kwargs)
    proof = ready['proof']
    key = {'owner-sdk': 'owner_sdk_sha256', 'subject-sdk': 'private_subject_sdk_sha256',
           'subject-producer': 'private_subject_producer_sha256'}[damage]
    proof[key] = '86c8c151e559e4f4e665c475348e3a81665f008ba69298b3829d474b4873035f' if damage == 'subject-producer' else '4df3f7f2c6d2952550dd78153b579f4e928e9f119e697bded8a7dc001021f8d2'
    before = case['ledger'].read_bytes()
    with pytest.raises(ValueError):
        cli._capacity_current_private_completed_ledger_evidence_v1(entry, ready, 'proof')
    assert case['ledger'].read_bytes() == before


# Explicit existing-header binding for the original sampled-v1 recovery path.
# These fixtures are entirely fictional and confer no host-ledger eligibility.
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_daemon_resources import setup as sampled_header_setup
from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_resource_recovery as sampled_header_unit

_SAMPLED_HEADER_OMITTED = object()


def _sampled_header_case(sampled_header_setup, monkeypatch, header=280_000_000_000):
    monkeypatch.setattr(recovery.resources, "MAX_STORAGE_BYTES", 250_000_000_000)
    case = sampled_header_unit._sampled_validation_fixture(sampled_header_setup, monkeypatch)
    data = json.loads(case["ledger"].read_bytes())
    data["limit_bytes"] = header
    case["ledger"].write_bytes(sampled_header_unit._sampled_wire(data))
    case["terminal"]["reservation"]["storage_limit_bytes"] = header
    case["parent"]["original_owner_custody"]["original_terminal"] = deepcopy(case["terminal"])
    sampled_header_unit._sampled_seal(case)
    return case


def _sampled_header_call(case, operation, expected=_SAMPLED_HEADER_OMITTED, policy="administrative_closeout"):
    if expected is _SAMPLED_HEADER_OMITTED:
        case["args"].pop("expected_ledger_limit_bytes", None)
    else:
        case["args"]["expected_ledger_limit_bytes"] = expected
    if operation == "inspect":
        return sampled_header_unit._sampled_inspect(case)
    return sampled_header_unit._sampled_reconcile(case, policy)


def _sampled_header_unchanged(case, before):
    assert case["ledger"].read_bytes() == before
    assert recovery._durable_inventory(case["args"]["attempt_directory"]) == case["args"]["expected_artifacts"]
    assert recovery.resources.MAX_STORAGE_BYTES == 250_000_000_000


def test_sampled_v1_header_omitted_legacy_inspection(sampled_header_setup, monkeypatch):
    case = _sampled_header_case(sampled_header_setup, monkeypatch, 250_000_000_000)
    before = case["ledger"].read_bytes()
    report = _sampled_header_call(case, "inspect")
    assert report["ready"] is True
    assert report["state_written"] is report["recovery_performed"] is report["admitted"] is False
    _sampled_header_unchanged(case, before)


def test_sampled_v1_header_none_keeps_inspection_constructor_shape(sampled_header_setup, monkeypatch):
    case = _sampled_header_case(sampled_header_setup, monkeypatch, 250_000_000_000)
    calls = []
    original = recovery.resources.DaemonResourceReservation.__init__
    def spy(owner, *args, **kwargs):
        calls.append(dict(kwargs))
        return original(owner, *args, **kwargs)
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, "__init__", spy)
    before = case["ledger"].read_bytes()
    assert _sampled_header_call(case, "inspect", None)["ready"] is True
    assert calls and all("storage_limit_bytes" not in row for row in calls)
    _sampled_header_unchanged(case, before)


def test_sampled_v1_header_omitted_legacy_closeout(sampled_header_setup, monkeypatch):
    case = _sampled_header_case(sampled_header_setup, monkeypatch, 250_000_000_000)
    report = _sampled_header_call(case, "reconcile")
    after = json.loads(case["ledger"].read_bytes())
    assert after["limit_bytes"] == recovery.resources.MAX_STORAGE_BYTES == 250_000_000_000
    assert after["reservations"][case["args"]["reservation_id"]]["status"] == "released"
    assert after["reservations"][case["prior_id"]] == case["prior"]
    assert report["cap_changed"] is report["admitted"] is report["outputs_deleted"] is False


def test_sampled_v1_header_none_keeps_closeout_constructor_shape(sampled_header_setup, monkeypatch):
    case = _sampled_header_case(sampled_header_setup, monkeypatch, 250_000_000_000)
    calls = []
    original = recovery.resources.DaemonResourceReservation.__init__
    def spy(owner, *args, **kwargs):
        calls.append(dict(kwargs))
        return original(owner, *args, **kwargs)
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, "__init__", spy)
    report = _sampled_header_call(case, "reconcile", None)
    assert calls and all("storage_limit_bytes" not in row for row in calls)
    assert report["cap_changed"] is report["admitted"] is False


def test_sampled_v1_header_explicit_inspection_is_read_only(sampled_header_setup, monkeypatch):
    case = _sampled_header_case(sampled_header_setup, monkeypatch)
    before = case["ledger"].read_bytes()
    report = _sampled_header_call(case, "inspect", 280_000_000_000)
    assert report["ready"] is True and report["capacity_not_assessed"] is True
    for key in ("state_written", "recovery_performed", "admitted", "native_release_performed", "historical_release_invented"):
        assert report[key] is False
    _sampled_header_unchanged(case, before)


def test_sampled_v1_header_explicit_closeout_preserves_cap_artifacts_and_foreign_row(sampled_header_setup, monkeypatch):
    case = _sampled_header_case(sampled_header_setup, monkeypatch)
    inventory = recovery._durable_inventory(case["args"]["attempt_directory"])
    report = _sampled_header_call(case, "reconcile", 280_000_000_000)
    after = json.loads(case["ledger"].read_bytes())
    assert after["limit_bytes"] == 280_000_000_000
    assert recovery.resources.MAX_STORAGE_BYTES == 250_000_000_000
    assert after["reservations"][case["args"]["reservation_id"]]["status"] == "released"
    assert after["reservations"][case["prior_id"]] == case["prior"]
    assert recovery._durable_inventory(case["args"]["attempt_directory"]) == inventory
    assert report["capacity_policy"] == "administrative_closeout"
    assert report["cap_changed"] is report["admitted"] is report["outputs_deleted"] is False


def test_sampled_v1_header_no_optin_retains_actual_header_refusal(sampled_header_setup, monkeypatch):
    case = _sampled_header_case(sampled_header_setup, monkeypatch)
    before = case["ledger"].read_bytes()
    for operation in ("inspect", "reconcile"):
        for value in (_SAMPLED_HEADER_OMITTED, None):
            with pytest.raises(recovery.resources.DaemonResourceError, match="disk ledger storage scope differs"):
                _sampled_header_call(case, operation, value)
            _sampled_header_unchanged(case, before)


def test_sampled_v1_header_wrong_explicit_value_cannot_rebind_header(sampled_header_setup, monkeypatch):
    case = _sampled_header_case(sampled_header_setup, monkeypatch)
    before = case["ledger"].read_bytes()
    for operation in ("inspect", "reconcile"):
        with pytest.raises(recovery.resources.DaemonResourceError, match="disk ledger storage scope differs"):
            _sampled_header_call(case, operation, 279_000_000_000)
        _sampled_header_unchanged(case, before)


def test_sampled_v1_header_rejects_nonpositive_nonint_and_overflow(sampled_header_setup, monkeypatch):
    case = _sampled_header_case(sampled_header_setup, monkeypatch)
    before = case["ledger"].read_bytes()
    for value in (True, False, 0, -1, 280_000_000_000.0, "280000000000", [], {}, 1 << 63):
        for operation in ("inspect", "reconcile"):
            with pytest.raises(recovery.resources.DaemonResourceError, match="invalid expected ledger limit"):
                _sampled_header_call(case, operation, value)
            _sampled_header_unchanged(case, before)
    assert case["scheduler_calls"] == []


def test_sampled_v1_header_explicit_requires_administrative_policy_before_scheduler(sampled_header_setup, monkeypatch):
    case = _sampled_header_case(sampled_header_setup, monkeypatch)
    before = case["ledger"].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match="explicit ledger limit requires administrative_closeout"):
        _sampled_header_call(case, "reconcile", 280_000_000_000, "require_capacity")
    assert case["scheduler_calls"] == []
    _sampled_header_unchanged(case, before)


def test_sampled_v1_header_signed63_upper_bound_inspection(sampled_header_setup, monkeypatch):
    case = _sampled_header_case(sampled_header_setup, monkeypatch, (1 << 63) - 1)
    before = case["ledger"].read_bytes()
    assert _sampled_header_call(case, "inspect", (1 << 63) - 1)["ready"] is True
    _sampled_header_unchanged(case, before)


def test_sampled_v1_header_does_not_bypass_missing_child_profile(sampled_header_setup, monkeypatch):
    case = _sampled_header_case(sampled_header_setup, monkeypatch)
    case["row"]["child"] = None
    data = json.loads(case["ledger"].read_bytes())
    data["reservations"][case["args"]["reservation_id"]] = case["row"]
    case["ledger"].write_bytes(sampled_header_unit._sampled_wire(data))
    case["terminal"]["reservation"]["record"] = deepcopy(case["row"])
    case["parent"]["original_owner_custody"]["original_terminal"] = deepcopy(case["terminal"])
    sampled_header_unit._sampled_seal(case)
    before = case["ledger"].read_bytes()
    for operation in ("inspect", "reconcile"):
        with pytest.raises(recovery.resources.DaemonResourceError):
            _sampled_header_call(case, operation, 280_000_000_000)
        _sampled_header_unchanged(case, before)


def test_sampled_v1_header_does_not_bypass_original_custody(sampled_header_setup, monkeypatch):
    case = _sampled_header_case(sampled_header_setup, monkeypatch)
    case["parent"]["original_owner_custody"]["original_native_compute_closed"] = False
    sampled_header_unit._sampled_seal(case)
    before = case["ledger"].read_bytes()
    for operation in ("inspect", "reconcile"):
        with pytest.raises(recovery.resources.DaemonResourceError):
            _sampled_header_call(case, operation, 280_000_000_000)
        _sampled_header_unchanged(case, before)


def test_sampled_v1_header_does_not_bypass_live_owner(sampled_header_setup, monkeypatch):
    case = _sampled_header_case(sampled_header_setup, monkeypatch)
    case["process_table"][99999999] = dict(pid=99999999, birth="456", state="S",
        parent_pid=1, group_pid=99999999, rss_bytes=4096)
    before = case["ledger"].read_bytes()
    for operation in ("inspect", "reconcile"):
        with pytest.raises(recovery.resources.DaemonResourceError):
            _sampled_header_call(case, operation, 280_000_000_000)
        _sampled_header_unchanged(case, before)


def test_sampled_v1_header_does_not_bypass_native_lease(sampled_header_setup, monkeypatch):
    case = _sampled_header_case(sampled_header_setup, monkeypatch)
    lease_id = case["row"]["native_lease_id"]
    case["scheduler_state"]["leases"][lease_id] = dict(
        lease_id=lease_id, request_id="validation:" + case["args"]["reservation_id"])
    before = case["ledger"].read_bytes()
    for operation in ("inspect", "reconcile"):
        with pytest.raises(recovery.resources.DaemonResourceError):
            _sampled_header_call(case, operation, 280_000_000_000)
        _sampled_header_unchanged(case, before)


def test_sampled_v1_header_does_not_bypass_proof_pin(sampled_header_setup, monkeypatch):
    case = _sampled_header_case(sampled_header_setup, monkeypatch)
    case["args"]["expected_proof_sha256"] = "0" * 64
    before = case["ledger"].read_bytes()
    for operation in ("inspect", "reconcile"):
        with pytest.raises(recovery.resources.DaemonResourceError):
            _sampled_header_call(case, operation, 280_000_000_000)
        _sampled_header_unchanged(case, before)
