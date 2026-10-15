"""Real private native grants, files, SQLite sidecars and cooperative processes.

These checks never initialize, replace or allocate from the shared host state.
The outer validation launcher owns the actual host grant.  Each test exercises
the production owner against a separate real file-backed scheduler and ledger.
Process custody covers an isolated process group; this is not a kernel quota
or containment of arbitrary descendants which create their own sessions.
"""
from __future__ import annotations

from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import stat
import subprocess
import sys
import time

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as native_disk
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as native
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import validation_run_resources as validation


CHILD_SOURCE = r'''
import json
import os
from pathlib import Path
import sys
import time

mode, attempt_text, request_digest, checks_json = sys.argv[1:]
attempt = Path(attempt_text)
assert sys.stdin.readline().strip() == "attached"
if request_digest == "REQUEST_DIGEST_FROM_STDIN":
    request_digest = sys.stdin.readline().strip()
assert sum((1, 2, 3)) == 6
if mode in {"descendant", "two_processes"}:
    child = os.fork()
    if child:
        (attempt / "logs" / "descendant.pid").write_text(str(child))
        if mode == "two_processes":
            time.sleep(20)
        sys.exit(0)
    time.sleep(20)
    os._exit(0)
if mode == "waiting":
    (attempt / "logs" / "started").write_text("actual isolated child")
    time.sleep(20)
    sys.exit(0)
output = attempt / "exports" / "checked.json"
output.write_text(json.dumps({"sum": 6, "pid": os.getpid()}))
result = {
    "schema": "owned-validation-result/v1",
    "request_sha256": request_digest,
    "executed_checks": json.loads(checks_json),
    "returncode": 0,
    "completed": True,
    "evidence_paths": [str(output)],
}
(attempt / "logs" / "result.json").write_text(json.dumps(result))
'''


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json(path):
    return json.loads(Path(path).read_bytes())


def _write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def _wait_for(predicate, message, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError(message)


def _stop_group(process):
    """Reap only the test's direct child and its original cooperative group."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            stream.close()


@pytest.fixture
def private_control(tmp_path):
    """Native state is created only in pytest's private, owned test fixture."""
    root = tmp_path / "outputs"
    root.mkdir()
    source = tmp_path / "actual_validation_child.py"
    source.write_text(CHILD_SOURCE)
    scheduler = native.GlobalResourceScheduler(native.ResourceSchedulerConfig(
        total_cpu_slots=4,
        total_memory_mb=4096,
        total_child_process_slots=8,
        total_gpu_memory_mb=None,
        total_unified_memory_mb=None,
        lane_reservations={"validation": {"cpu_slots": 1, "memory_mb": 0}},
        state_path=tmp_path / "native-state.json",
        proof_safety_enabled=True,
        proof_memory_stall_percent=100.0,
        proof_cpu_stall_percent=100.0,
        proof_io_stall_percent=100.0,
        auto_renew_leases=False,
    ))
    policy = deepcopy(_json(scheduler.state_path)["config"])
    policy_digest = existing.policy_sha256(policy)
    ledger = tmp_path / "disk.json"
    foreign = {
        "reservation_id": "foreign-retained",
        "status": "retained",
        "owner_pid": os.getpid(),
        "storage_bytes": 1234,
        "reason": "unrelated retained evidence is not ours to clear",
        "external_charges": {},
    }
    _write_json(ledger, {
        "schema": native_disk.SCHEMA,
        "roots": [native_disk._root_identity(root)],
        "limit_bytes": 145_000_000_000,
        "reservations": {"foreign-retained": foreign},
    })

    def prepare(*, storage_bytes=1_000_000, memory_mb=2048, cpu_slots=1,
                child_process_slots=3, timeout_seconds=20, mode="success", mutate=None):
        attempt = root / ("attempt-" + str(len(tuple(root.iterdir()))))
        attempt.mkdir(mode=0o700)
        request_path = tmp_path / (attempt.name + "-request.json")
        # argv deliberately records the actual child executable/source/mode.
        # The request digest is supplied over stdin after native attachment,
        # avoiding a self-referential request hash in argv.
        argv = [sys.executable, "-B", str(source), mode, str(attempt),
                "REQUEST_DIGEST_FROM_STDIN", json.dumps(["actual arithmetic check"])]
        request = {
            "schema": "owned-validation-request/v1",
            "roots": [str(root)],
            "argv": argv,
            "cwd": str(attempt),
            "selected_checks": ["actual arithmetic check"],
            "source_sha256": {str(source): _sha(source)},
            "timeout_seconds": timeout_seconds,
            "storage_bytes": storage_bytes,
            "memory_mb": memory_mb,
            "cpu_slots": cpu_slots,
            "child_process_slots": child_process_slots,
            "attempt_directory": str(attempt),
            "outputs": {name: str(attempt / name) for name in
                        ("pytest", "tmp", "cache", "db", "exports", "logs")},
            "declared_external_writable_paths": [],
            "process_scope": "isolated_process_group",
            "scheduler_state_path": str(scheduler.state_path),
            "expected_scheduler_policy_sha256": policy_digest,
        }
        if mutate:
            mutate(request)
        _write_json(request_path, request)
        kwargs = dict(
            roots=[root], attempt_directory=attempt,
            storage_bytes=storage_bytes, memory_mb=memory_mb,
            cpu_slots=cpu_slots, child_process_slots=child_process_slots,
            scheduler_state_path=scheduler.state_path,
            expected_scheduler_policy_sha256=policy_digest,
            validation_manifest_path=request_path,
            frozen_validation_manifest_sha256=_sha(request_path),
            timeout_seconds=timeout_seconds,
        )
        return attempt, request_path, request, kwargs

    yield dict(root=root, source=source, scheduler=scheduler, ledger=ledger,
               policy=policy, policy_digest=policy_digest, foreign=foreign, prepare=prepare,
               original_state=scheduler.state_path.read_bytes())
    # Production owners must have released actual compute on normal exit or
    # on failures after the supported group has been stopped. Retained disk
    # claims deliberately remain and are not administratively reconciled here.
    assert scheduler.snapshot()["allocated"]["cpu_slots"] == 0
    assert _json(scheduler.state_path)["config"] == policy
    assert _json(ledger)["limit_bytes"] == 145_000_000_000
    assert _json(ledger)["reservations"]["foreign-retained"] == foreign


def _owner(control, kwargs):
    return validation.ValidationResourceReservation(control["ledger"], **kwargs)


def _start_attached(owner, request, request_path):
    process = subprocess.Popen(
        request["argv"], cwd=request["cwd"], env=owner.environment(os.environ),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,
    )
    try:
        owner.attach_child(process.pid)
        assert process.poll() is None
        process.stdin.write("attached\n" + _sha(request_path) + "\n")
        process.stdin.flush()
        return process
    except BaseException:
        _stop_group(process)
        raise


def _complete(owner, request, request_path):
    process = _start_attached(owner, request, request_path)
    try:
        process.wait(timeout=5)
        assert process.returncode == 0, process.stderr.read()
    finally:
        _stop_group(process)
    return Path(request["attempt_directory"]) / "logs" / "result.json"


def test_exactly_one_real_validation_root_and_foreign_native_lease_preserved(private_control):
    c = private_control
    attempt, manifest, request, kwargs = c["prepare"](cpu_slots=2, child_process_slots=3)
    foreign_lease = c["scheduler"].acquire(
        native.ResourceLane.CODEX, cpu_slots=1, memory_mb=128,
        child_process_slots=1, timeout=0, request_id="unrelated-test-owner")
    try:
        foreign_before = deepcopy(_json(c["scheduler"].state_path)["leases"][foreign_lease.lease_id])
        with _owner(c, kwargs) as owned:
            receipt = owned.to_dict()
            lease = receipt["resource_lease"]
            assert receipt["scheduler_lane"] == lease["lane"] == "validation"
            assert receipt["workload"] == "canonical_validation"
            assert lease["cpu_slots"] == 2 and lease["memory_mb"] == 2048
            assert lease["child_process_slots"] == 3
            live = _json(c["scheduler"].state_path)["leases"]
            ours = [row for key, row in live.items() if key != foreign_lease.lease_id]
            assert len(ours) == 1 and not ours[0].get("parent_lease_id")
            assert ours[0]["lane"] == "validation"
            assert c["scheduler"].snapshot()["allocated"]["cpu_slots"] == 3
            assert _json(c["scheduler"].state_path)["config"] == c["policy"]
            assert _json(c["scheduler"].state_path)["leases"][foreign_lease.lease_id] == foreign_before
            result = _complete(owned, request, manifest)
            checked = _json(attempt / "exports" / "checked.json")
            assert checked["sum"] == 6 and checked["pid"] != os.getpid()
            owned.seal_results(result)
            released = owned.finalize(artifacts_durable=True)
            assert released["status"] == "released"
            assert released["resource_lease"]["released"] is True
            row = _json(c["ledger"])["reservations"][receipt["reservation_id"]]
            assert row["artifacts_durable_asserted"] is True
            assert row["finalization_profile"]["global_inventory_count"] == 1
            assert row["external_charges"] == {}
            assert owned.finalize(artifacts_durable=True)["status"] == "released"
        assert c["scheduler"].snapshot()["allocated"]["cpu_slots"] == 1
        assert _json(c["scheduler"].state_path)["leases"][foreign_lease.lease_id] == foreign_before
        assert result.is_file() and (attempt / "logs" / "validation-durability.json").is_file()
    finally:
        foreign_lease.release()


def test_outputs_and_python_temporary_environment_are_owned(private_control):
    c = private_control
    attempt, _, _, kwargs = c["prepare"]()
    with _owner(c, kwargs) as owned:
        assert {entry.name for entry in attempt.iterdir()} == {
            "pytest", "tmp", "cache", "db", "exports", "logs"}
        environment = owned.environment({"PRESERVED_READ_ONLY_SETTING": "yes"})
        assert environment["PRESERVED_READ_ONLY_SETTING"] == "yes"
        assert all(environment[name] == str(attempt / "tmp") for name in ("TMPDIR", "TMP", "TEMP"))
        assert environment["XDG_CACHE_HOME"] == str(attempt / "cache")
        assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
        local = owned.check_limits()
        assert local["full_ledger_check"] is False
        assert owned.check_limits(full=True)["full_ledger_check"] is True
        key = owned.to_dict()["reservation_id"]
    row = _json(c["ledger"])["reservations"][key]
    assert row["status"] == "retained" and row["storage_bytes"] == kwargs["storage_bytes"]
    assert row["artifacts_durable_asserted"] is False


@pytest.mark.parametrize("bad_field", [
    "empty_checks", "empty_argv", "no_source", "external_output", "wrong_output",
    "wrong_scope", "wrong_budget", "wrong_policy", "wrong_cwd",
])
def test_nonproductive_or_out_of_scope_request_refused_before_admission(private_control, bad_field):
    c = private_control
    def mutate(request):
        if bad_field == "empty_checks": request["selected_checks"] = []
        elif bad_field == "empty_argv": request["argv"] = []
        elif bad_field == "no_source": request["source_sha256"] = {}
        elif bad_field == "external_output": request["declared_external_writable_paths"] = [str(c["root"].parent / "foreign")]
        elif bad_field == "wrong_output": request["outputs"]["db"] = str(c["root"].parent / "foreign.sqlite")
        elif bad_field == "wrong_scope": request["process_scope"] = "arbitrary_process_tree"
        elif bad_field == "wrong_budget": request["storage_bytes"] += 1
        elif bad_field == "wrong_policy": request["expected_scheduler_policy_sha256"] = "0" * 64
        elif bad_field == "wrong_cwd": request["cwd"] = "relative/unowned"
    attempt, _, _, kwargs = c["prepare"](mutate=mutate)
    before = c["ledger"].read_bytes()
    with pytest.raises((validation.ValidationResourceError, native_disk.DaemonResourceError)):
        with _owner(c, kwargs):
            pytest.fail("invalid request reached productive admission")
    assert c["ledger"].read_bytes() == before
    assert not tuple(attempt.iterdir())
    assert not _json(c["scheduler"].state_path)["leases"]


@pytest.mark.parametrize("fault", ["missing_state", "empty_state", "changed_policy", "missing_ledger"])
def test_existing_control_metadata_is_never_initialized_or_reconfigured(private_control, fault):
    c = private_control
    _, _, _, kwargs = c["prepare"]()
    state_path = c["scheduler"].state_path
    if fault == "missing_state": state_path.unlink()
    elif fault == "empty_state": state_path.write_bytes(b"")
    elif fault == "changed_policy":
        state = _json(state_path)
        state["config"]["total_child_process_slots"] += 1
        _write_json(state_path, state)
    else: c["ledger"].unlink()
    state_before = state_path.read_bytes() if state_path.exists() else None
    ledger_before = c["ledger"].read_bytes() if c["ledger"].exists() else None
    try:
        with pytest.raises((validation.ValidationResourceError, native_disk.DaemonResourceError,
                            existing.ExistingResourceSchedulerError, FileNotFoundError)):
            with _owner(c, kwargs):
                pytest.fail("untrusted metadata granted validation")
        assert (state_path.read_bytes() if state_path.exists() else None) == state_before
        assert (c["ledger"].read_bytes() if c["ledger"].exists() else None) == ledger_before
    finally:
        # Restore only these test-owned deliberately damaged fixture files so
        # the fixture can inspect final policy. No production recovery occurs.
        if fault in {"missing_state", "empty_state", "changed_policy"}:
            state_path.write_bytes(c["original_state"])
        if fault == "missing_ledger":
            _write_json(c["ledger"], {"schema": native_disk.SCHEMA,
                "roots": [native_disk._root_identity(c["root"])],
                "limit_bytes": 145_000_000_000,
                "reservations": {"foreign-retained": c["foreign"]}})


def test_full_retained_claims_refuse_new_capacity_without_changing_cap_or_rows(private_control):
    c = private_control
    _, _, _, kwargs = c["prepare"]()
    before = _json(c["ledger"])
    extra = {"reservation_id": "other-full-claim", "status": "retained", "owner_pid": os.getpid(),
             "storage_bytes": 145_000_000_000, "external_charges": {}}
    before["reservations"]["other-full-claim"] = extra
    _write_json(c["ledger"], before)
    raw = c["ledger"].read_bytes()
    with pytest.raises(native_disk.DaemonResourceError, match="capacity"):
        with _owner(c, kwargs):
            pytest.fail("full conservative reservations must remain charged")
    assert c["ledger"].read_bytes() == raw
    assert not _json(c["scheduler"].state_path)["leases"]


def test_many_small_files_exceed_one_aggregate_allowance_and_retain_exact_claim(private_control):
    c = private_control
    attempt, _, _, kwargs = c["prepare"](storage_bytes=4096)
    with _owner(c, kwargs) as owned:
        key = owned.to_dict()["reservation_id"]
        for number in range(50):
            target = attempt / ("cache" if number % 2 else "pytest") / str(number)
            target.write_bytes(b"x" * 100)
        assert max(path.stat().st_size for path in attempt.rglob("*") if path.is_file()) == 100
        with pytest.raises((validation.ValidationResourceError, native_disk.DaemonResourceError), match="storage"):
            owned.check_limits(full=True)
    row = _json(c["ledger"])["reservations"][key]
    assert row["status"] == "retained" and row["storage_bytes"] == 4096
    assert sum(path.stat().st_size for path in attempt.rglob("*") if path.is_file()) == 5000


def test_local_watchdog_does_not_wait_for_the_real_private_ledger_lock(private_control):
    c = private_control
    _, _, _, kwargs = c["prepare"]()
    kwargs["ledger_lock_timeout_seconds"] = 0.25
    with _owner(c, kwargs) as owned:
        # A real separately opened flock describes the serialization domain a
        # slow census owns. The independent local guard must not enter it.
        with owned.lock_path.open("r+b") as locked:
            fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                report = owned.check_limits(full=False)
                assert report["full_ledger_check"] is False
            finally:
                fcntl.flock(locked, fcntl.LOCK_UN)


def test_existing_bound_claim_refuses_a_second_owner_of_the_same_empty_attempt(private_control):
    c = private_control
    attempt, _, _, kwargs = c["prepare"]()
    ledger = _json(c["ledger"])
    already_owned = {"reservation_id": "other-bound-owner", "status": "active",
        "owner_pid": os.getpid(), "storage_bytes": 1000, "external_charges": {},
        "attempt_directory": native_disk._root_identity(attempt)}
    ledger["reservations"]["other-bound-owner"] = already_owned
    _write_json(c["ledger"], ledger)
    before = c["ledger"].read_bytes()
    with pytest.raises(validation.ValidationResourceError, match="overlap|claim"):
        with _owner(c, kwargs):
            pytest.fail("a second owner must not bind the existing attempt")
    assert c["ledger"].read_bytes() == before
    assert not tuple(attempt.iterdir())
    assert not _json(c["scheduler"].state_path)["leases"]


def test_real_sqlite_wal_shm_and_simultaneous_exports_are_aggregate_bytes(private_control):
    c = private_control
    attempt, _, _, kwargs = c["prepare"](storage_bytes=250_000)
    connection = None
    try:
        with _owner(c, kwargs) as owned:
            key = owned.to_dict()["reservation_id"]
            database = attempt / "db" / "private.sqlite"
            connection = sqlite3.connect(database)
            assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
            connection.execute("PRAGMA wal_autocheckpoint=0")
            connection.execute("CREATE TABLE evidence(payload BLOB NOT NULL)")
            connection.execute("INSERT INTO evidence VALUES (?)", (b"e" * 65536,))
            connection.commit()
            assert Path(str(database) + "-wal").is_file()
            assert Path(str(database) + "-shm").is_file()
            owned.check_limits()
            export = attempt / "exports" / "snapshot.sqlite"
            with sqlite3.connect(export) as destination:
                connection.backup(destination)
            pending = attempt / "exports" / "atomic-snapshot.tmp"
            pending.write_bytes(export.read_bytes())
            files = [path for path in attempt.rglob("*") if path.is_file()]
            assert max(path.stat().st_size for path in files) < kwargs["storage_bytes"]
            assert sum(path.stat().st_size for path in files) > kwargs["storage_bytes"]
            with pytest.raises((validation.ValidationResourceError, native_disk.DaemonResourceError), match="storage"):
                owned.check_limits(full=True)
        row = _json(c["ledger"])["reservations"][key]
        assert row["status"] == "retained" and row["storage_bytes"] == 250_000
        assert export.is_file() and pending.is_file()
    finally:
        if connection is not None:
            connection.close()


def test_attachment_records_real_pid_start_birth_and_refuses_foreign_process(private_control):
    c = private_control
    _, manifest, request, kwargs = c["prepare"](mode="waiting")
    with _owner(c, kwargs) as owned:
        with pytest.raises((validation.ValidationResourceError, native_disk.DaemonResourceError), match="child|owned|group"):
            owned.attach_child(os.getpid())
        process = _start_attached(owned, request, manifest)
        try:
            _wait_for(lambda: (Path(request["attempt_directory"]) / "logs" / "started").exists(), "child did not start")
            row = owned.to_dict()["record"]
            actual = native_disk._process(process.pid)
            assert row["child"] == {"pid": process.pid, "birth": actual["birth"]}
            assert actual["parent_pid"] == os.getpid() and actual["group_pid"] == process.pid
            with pytest.raises((validation.ValidationResourceError, native_disk.DaemonResourceError), match="alive|stopped|sealed|result"):
                owned.finalize(artifacts_durable=True)
        finally:
            _stop_group(process)


def test_leader_exit_is_not_group_quiescence(private_control):
    c = private_control
    attempt, manifest, request, kwargs = c["prepare"](mode="descendant")
    with _owner(c, kwargs) as owned:
        process = _start_attached(owned, request, manifest)
        try:
            process.wait(timeout=5)
            assert process.returncode == 0
            child = owned.to_dict()["record"]["child"]
            _wait_for(lambda: native_disk._group_usage(child)["live_processes"] > 0,
                      "cooperative descendant was not observed")
            assert (attempt / "logs" / "descendant.pid").is_file()
            with pytest.raises((validation.ValidationResourceError, native_disk.DaemonResourceError), match="alive|stopped|sealed|result"):
                owned.finalize(artifacts_durable=True)
        finally:
            _stop_group(process)


def test_source_drift_after_attachment_retains_evidence_and_claim(private_control):
    c = private_control
    attempt, manifest, request, kwargs = c["prepare"](mode="waiting")
    with _owner(c, kwargs) as owned:
        key = owned.to_dict()["reservation_id"]
        process = _start_attached(owned, request, manifest)
        try:
            _wait_for(lambda: (attempt / "logs" / "started").exists(), "child did not reach actual work")
            c["source"].write_text(CHILD_SOURCE + "\n# deliberate private fixture drift\n")
            with pytest.raises(validation.ValidationResourceError, match="source|changed|drift"):
                owned.check_limits()
        finally:
            _stop_group(process)
    row = _json(c["ledger"])["reservations"][key]
    assert row["status"] == "retained" and row["storage_bytes"] == kwargs["storage_bytes"]
    assert (attempt / "logs" / "started").is_file()


def test_actual_same_group_process_overflow_retains_full_claim(private_control):
    c = private_control
    attempt, manifest, request, kwargs = c["prepare"](mode="two_processes", child_process_slots=1)
    with _owner(c, kwargs) as owned:
        key = owned.to_dict()["reservation_id"]
        process = _start_attached(owned, request, manifest)
        try:
            _wait_for(lambda: (attempt / "logs" / "descendant.pid").is_file(), "actual second process did not start")
            child = owned.to_dict()["record"]["child"]
            assert native_disk._group_usage(child)["live_processes"] == 2
            with pytest.raises(validation.ValidationResourceError, match="process limit"):
                owned.check_limits()
        finally:
            _stop_group(process)
    row = _json(c["ledger"])["reservations"][key]
    assert row["status"] == "retained" and row["child_process_slots"] == 1


def test_productive_deadline_is_not_extended_by_checks_or_native_renewal(private_control):
    c = private_control
    attempt, manifest, request, kwargs = c["prepare"](mode="waiting", timeout_seconds=1)
    with _owner(c, kwargs) as owned:
        key = owned.to_dict()["reservation_id"]
        process = _start_attached(owned, request, manifest)
        try:
            _wait_for(lambda: (attempt / "logs" / "started").is_file(), "actual check did not start")
            assert owned.heartbeat()
            time.sleep(1.05)
            with pytest.raises(validation.ValidationResourceError, match="deadline"):
                owned.check_limits()
        finally:
            _stop_group(process)
    row = _json(c["ledger"])["reservations"][key]
    assert row["status"] == "retained" and row["storage_bytes"] == kwargs["storage_bytes"]


def test_cancelled_actual_native_lease_prevents_further_work(private_control):
    c = private_control
    _, _, _, kwargs = c["prepare"]()
    with _owner(c, kwargs) as owned:
        receipt = owned.to_dict()
        # Administrative cancellation goes through the real native scheduler;
        # no fake lease or injected cancellation object can establish custody.
        assert c["scheduler"].cancel(receipt["resource_lease"]["lease_id"])
        with pytest.raises(validation.ValidationResourceError, match="cancel|lease|custody"):
            owned.check_limits(full=True)
    assert _json(c["ledger"])["reservations"][receipt["reservation_id"]]["status"] == "retained"


@pytest.mark.parametrize("fault", ["cpu_budget", "child_birth", "request_binding", "status"])
def test_changed_own_ledger_custody_is_not_repaired_or_released(private_control, fault):
    """Corrupt a real owned row; this does not claim to force kernel PID reuse."""
    c = private_control
    attempt, manifest, request, kwargs = c["prepare"](mode="waiting")
    owned = _owner(c, kwargs)
    owned.open()
    process = None
    try:
        process = _start_attached(owned, request, manifest)
        _wait_for(lambda: (attempt / "logs" / "started").is_file(), "actual check did not start")
        key = owned.to_dict()["reservation_id"]
        state = _json(c["ledger"])
        row = state["reservations"][key]
        if fault == "cpu_budget": row["cpu_slots"] += 1
        elif fault == "child_birth": row["child"]["birth"] = "0"
        elif fault == "request_binding": row["validation_request_sha256"] = "0" * 64
        else: row["status"] = "reserved"
        _write_json(c["ledger"], state)
        tampered = c["ledger"].read_bytes()
        with pytest.raises(native_disk.DaemonResourceError, match="owned|record|changed|differ|custody"):
            owned.check_limits(full=True)
        assert c["ledger"].read_bytes() == tampered
    finally:
        if process is not None:
            _stop_group(process)
        owned.__exit__(RuntimeError, RuntimeError("test-owned durable custody changed"), None)
    assert owned.to_dict()["cleanup_error"] is not None
    assert c["ledger"].read_bytes() == tampered
    persisted = _json(c["ledger"])["reservations"][key]
    assert persisted["status"] != "released"
    assert persisted["storage_bytes"] == kwargs["storage_bytes"]
    assert (attempt / "logs" / "started").is_file()
    # The supported group has stopped, so native compute can be released even
    # though unknown durable disk custody cannot authorize a claim rewrite.
    assert c["scheduler"].snapshot()["allocated"]["cpu_slots"] == 0


def test_manifest_mutation_and_attempt_substitution_are_not_new_authority(private_control):
    c = private_control
    attempt, manifest, _, kwargs = c["prepare"]()
    with _owner(c, kwargs) as owned:
        original = manifest.read_bytes()
        manifest.write_bytes(original + b" ")
        with pytest.raises(validation.ValidationResourceError, match="request|manifest|changed"):
            owned.check_limits()
        manifest.write_bytes(original)
        preserved = attempt.with_name(attempt.name + "-retained")
        attempt.rename(preserved)
        attempt.mkdir(mode=0o700)
        with pytest.raises((validation.ValidationResourceError, native_disk.DaemonResourceError), match="identity|directory|changed"):
            owned.check_limits()
        assert preserved.is_dir()


def test_no_child_or_unsealed_return_code_cannot_finalize(private_control):
    c = private_control
    _, manifest, request, kwargs = c["prepare"]()
    with _owner(c, kwargs) as owned:
        with pytest.raises(validation.ValidationResourceError, match="child|attached|sealed|result"):
            owned.finalize(artifacts_durable=True)
        result = _complete(owned, request, manifest)
        assert _json(result)["completed"] is True
        with pytest.raises(validation.ValidationResourceError, match="sealed|result|durab"):
            owned.finalize(artifacts_durable=True)
        owned.seal_results(result)
        with pytest.raises((validation.ValidationResourceError, native_disk.DaemonResourceError), match="durab"):
            owned.finalize(artifacts_durable=False)


@pytest.mark.parametrize("fault", ["wrong_request", "wrong_checks", "false_complete", "failed_returncode", "outside_evidence"])
def test_sealed_result_requires_exact_request_checks_and_owned_evidence(private_control, fault):
    c = private_control
    _, manifest, request, kwargs = c["prepare"]()
    with _owner(c, kwargs) as owned:
        result_path = _complete(owned, request, manifest)
        result = _json(result_path)
        if fault == "wrong_request": result["request_sha256"] = "0" * 64
        elif fault == "wrong_checks": result["executed_checks"] = ["unrequested easy check"]
        elif fault == "false_complete": result["completed"] = False
        elif fault == "failed_returncode": result["returncode"] = 1
        else: result["evidence_paths"] = [str(c["source"])]
        _write_json(result_path, result)
        with pytest.raises(validation.ValidationResourceError):
            owned.seal_results(result_path)


def test_mutation_after_sealing_keeps_original_full_claim(private_control):
    c = private_control
    attempt, manifest, request, kwargs = c["prepare"]()
    with _owner(c, kwargs) as owned:
        key = owned.to_dict()["reservation_id"]
        result = _complete(owned, request, manifest)
        owned.seal_results(result)
        (attempt / "exports" / "checked.json").write_text('{"sum": 0}\n')
        with pytest.raises(validation.ValidationResourceError, match="changed|inventory|durab"):
            owned.finalize(artifacts_durable=True)
    row = _json(c["ledger"])["reservations"][key]
    assert row["status"] == "retained" and row["storage_bytes"] == kwargs["storage_bytes"]
    assert row["artifacts_durable_asserted"] is False


@pytest.mark.parametrize("command_succeeds", [True, False], ids=["successful-check", "failed-check"])
def test_actual_cli_executes_checks_with_one_native_owner_and_preserves_failed_evidence(
        private_control, command_succeeds):
    """Use the canonical CLI in a fresh process, not an injected test facade."""
    c = private_control
    attempt, manifest, request, kwargs = c["prepare"](timeout_seconds=30)
    package_root = Path(validation.__file__).resolve().parents[3]
    launcher = package_root / "scripts" / "ops" / "legal_ir" / "run_owned_validation.py"
    check_source = c["source"].with_name("cli_actual_check.py")
    check_source.write_text(
        "import json, os\n"
        "from pathlib import Path\n"
        "assert 6 * 7 == 42\n"
        "temporary = Path(os.environ['TMPDIR']) / 'actual-check.json'\n"
        "temporary.write_text(json.dumps({'answer': 42, 'pid': os.getpid()}))\n"
        "print('actual-check answer=42 tmp='+str(temporary), flush=True)\n"
        + ("raise SystemExit(0)\n" if command_succeeds else "raise SystemExit(7)\n"))
    request["argv"] = [sys.executable, "-B", str(check_source)]
    request["selected_checks"] = ["actual-check arithmetic and owned temporary output"]
    pinned = [launcher, check_source, Path(validation.__file__), Path(native_disk.__file__),
              Path(native.__file__), Path(existing.__file__),
              Path(native.__file__).with_name("proof_resource_safety.py")]
    request["source_sha256"] = {str(path.resolve()): _sha(path) for path in pinned}
    _write_json(manifest, request)
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
        IPFS_DATASETS_PY_MINIMAL_IMPORTS="1", IPFS_DATASETS_AUTO_INSTALL="0",
        IPFS_AUTO_INSTALL="false", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1")
    process = subprocess.run(
        [sys.executable, "-B", str(launcher), "--request", str(manifest),
         "--expected-request-sha256", _sha(manifest), "--resource-ledger", str(c["ledger"])],
        cwd=package_root, env=environment, text=True, capture_output=True, timeout=45,
    )
    rows = _json(c["ledger"])["reservations"]
    ours = [row for key, row in rows.items() if key != "foreign-retained"]
    assert len(ours) == 1, process.stderr
    row = ours[0]
    assert row["scheduler_lane"] == "validation" and row["workload"] == "canonical_validation"
    assert row["storage_bytes"] == kwargs["storage_bytes"]
    assert row["owner_pid"] != os.getpid()
    assert row["child"]["pid"] != row["owner_pid"]
    child_identity = native_disk._process(row["child"]["pid"])
    assert child_identity is None or child_identity["birth"] != row["child"]["birth"] or child_identity["state"] == "Z"
    assert not native_disk._group_usage(row["child"])["live_processes"]
    state = _json(c["scheduler"].state_path)
    assert state["metrics"]["acquisitions_total"] == 1
    assert state["metrics"]["lanes"]["validation"]["acquisitions_total"] == 1
    assert all(metrics["acquisitions_total"] == 0 for lane, metrics in state["metrics"]["lanes"].items()
               if lane != "validation")
    assert state["leases"] == {}
    proof = _json(attempt / "tmp" / "actual-check.json")
    assert proof["answer"] == 42 and proof["pid"] == row["child"]["pid"]
    assert "actual-check answer=42" in (attempt / "logs" / "stdout.log").read_text()
    if command_succeeds:
        assert process.returncode == 0, process.stderr
        result = _json(attempt / "logs" / "result.json")
        assert result["executed_checks"] == request["selected_checks"]
        assert result["returncode"] == 0 and result["completed"] is True
        assert row["status"] == "released" and row["artifacts_durable_asserted"] is True
        assert (attempt / "logs" / "validation-durability.json").is_file()
    else:
        assert process.returncode != 0
        assert row["status"] == "retained" and row["artifacts_durable_asserted"] is False
        assert (attempt / "logs" / "failure.json").is_file()
        assert not (attempt / "logs" / "validation-durability.json").exists()


@pytest.mark.parametrize("node_label", ["plain", "../../a slash and spaces", "unicode-\u00e9<>[]"])
def test_opt_in_pytest_profile_retains_unique_private_directories_without_aliases(tmp_path, node_label):
    """Run actual opt-in fixtures; ordinary outer pytest remains supported."""
    package_root = Path(validation.__file__).resolve().parents[3]
    plugin = "ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_pytest"
    plugin_source = Path(validation.__file__).resolve().with_name("validation_pytest.py")
    base = tmp_path / "inner-owned-basetemp"
    inner_test = tmp_path / "test_actual_tmp_profile.py"
    inner_test.write_text(
        "from pathlib import Path\n"
        "import json, stat\n"
        "import pytest\n"
        "retained = []\n"
        + "@pytest.mark.parametrize('number', [0, 1], ids="
        + repr([node_label + "-first", node_label + "-second"]) + ")\n"
        "def test_private_directory(tmp_path, request, number):\n"
        + "    plugin = request.config.pluginmanager.getplugin(" + repr(plugin) + ")\n"
        "    assert plugin is not None\n"
        + "    assert Path(plugin.__file__).resolve() == Path(" + repr(str(plugin_source)) + ")\n"
        + "    base = Path(" + repr(str(base)) + ")\n"
        "    assert tmp_path.parent == base\n"
        "    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700\n"
        "    assert all(not path.is_symlink() for path in (tmp_path, *tmp_path.parents))\n"
        "    assert all(not path.is_symlink() for path in base.iterdir())\n"
        "    assert all(old.is_file() and old.parent != tmp_path for old in retained)\n"
        "    evidence = tmp_path / 'actual-check.json'\n"
        "    evidence.write_text(json.dumps({'number': number, 'sum': sum((1, 2, 3))}))\n"
        "    assert json.loads(evidence.read_text())['sum'] == 6\n"
        "    retained.append(evidence)\n")
    environment = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1",
        IPFS_DATASETS_PY_MINIMAL_IMPORTS="1", IPFS_DATASETS_AUTO_INSTALL="0", IPFS_AUTO_INSTALL="false",
        PYTHONPATH=os.pathsep.join([str(package_root), os.environ.get("PYTHONPATH", "")]))
    result = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-q", "-c", "/dev/null", "--noconftest",
         "-p", plugin, "-p", "no:cacheprovider", "--basetemp", str(base), str(inner_test)],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout
    directories = tuple(base.iterdir())
    assert len(directories) == 2
    assert all(path.is_dir() and not path.is_symlink() for path in directories)
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o700 for path in directories)
    assert all((path / "actual-check.json").is_file() for path in directories)

