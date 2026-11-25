"""Real private native grants, files, SQLite sidecars and cooperative processes.

These checks never initialize, replace or allocate from the shared host state.
The outer validation launcher owns the actual host grant.  Each test exercises
the production owner against a separate real file-backed scheduler and ledger.
The legacy profile covers an isolated process group. The explicit tracked
profile additionally tests observed new-session descendants; neither profile
claims kernel containment of unobserved escaping processes.
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
    fixture_storage_limit_bytes = native_disk.MAX_STORAGE_BYTES
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
        "limit_bytes": fixture_storage_limit_bytes,
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
    assert _json(ledger)["limit_bytes"] == fixture_storage_limit_bytes
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
                "limit_bytes": 220_000_000_000,
                "reservations": {"foreign-retained": c["foreign"]}})


def test_full_retained_claims_refuse_new_capacity_without_changing_cap_or_rows(private_control):
    c = private_control
    _, _, _, kwargs = c["prepare"]()
    before = _json(c["ledger"])
    extra = {"reservation_id": "other-full-claim", "status": "retained", "owner_pid": os.getpid(),
             "storage_bytes": 220_000_000_000, "external_charges": {}}
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



# These are harmless real Python fixtures. Their explicit setsid child ignores
# SIGTERM so the shared retained-identity drain must reach its bounded SIGKILL.
TRACKED_CHILD_SOURCE = r"""
import json, os, signal, subprocess, sys, time
from pathlib import Path
mode, attempt_text, request_digest, checks_json = sys.argv[1:]
attempt = Path(attempt_text)
assert sys.stdin.readline().strip() == 'attached'
assert sys.stdin.readline().strip()
nested_body = ("import signal,sys,time\n"
               "from pathlib import Path\n"
               "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
               "Path(sys.argv[1]).write_text('ready')\n"
               "time.sleep(20)\n")
nested = subprocess.Popen([sys.executable, '-B', '-c', nested_body,
                           str(attempt/'logs'/'nested-ready')],
                          stdin=subprocess.DEVNULL, start_new_session=True)
(attempt/'logs'/'nested.pid').write_text(str(nested.pid))
if mode == 'tracked_parent_exit':
    while not (attempt/'tmp'/'allow-parent-exit').exists():
        time.sleep(.01)
    raise SystemExit(0)
time.sleep(20)
"""


def _tracked_fixture(control, **kwargs):
    control['source'].write_text(TRACKED_CHILD_SOURCE)
    return control['prepare'](mode='tracked_waiting', **kwargs,
        mutate=lambda request: request.update(process_scope=validation.TRACKED_SCOPE))


def _nested_ready(owner, attempt):
    _wait_for(lambda: (attempt/'logs'/'nested-ready').is_file(), 'new-session child did not become ready')
    pid = int((attempt/'logs'/'nested.pid').read_text())
    observed = owner.observe_processes()
    identity = native_disk._process(pid)
    assert identity is not None and identity['state'] != 'Z'
    assert identity['group_pid'] == pid and pid != owner.to_dict()['record']['child']['pid']
    assert any(row['pid'] == pid and str(row['birth_ticks']) == identity['birth']
               for row in observed['observed_identities'])
    return pid, identity['birth'], observed


def _finish_tracked(owner, process):
    _stop_group(process)
    owner.drain_tracked_descendants(.05)


def test_tracked_scope_retains_before_barrier_and_counts_group_union_once(private_control):
    c = private_control
    attempt, manifest, request, kwargs = _tracked_fixture(c, child_process_slots=2)
    with _owner(c, kwargs) as owned:
        process = _start_attached(owned, request, manifest)
        try:
            child = owned.to_dict()['record']['child']
            assert owned._descendants.records[child['pid']][0] == int(child['birth'])
            pid, birth, observed = _nested_ready(owned, attempt)
            assert observed['scope'] == validation.TRACKED_SCOPE
            assert observed['group_rss']['live_processes'] == 1
            assert observed['live_processes'] == 2
            assert observed['rss_bytes'] == (observed['group_rss']['rss_bytes'] +
                sum(row['rss_bytes'] for row in observed['out_of_group_live_identities']))
            assert [(row['pid'], row['birth']) for row in observed['out_of_group_live_identities']] == [(pid, birth)]
            actual = owned.check_limits()['process_observation']
            assert actual['live_processes'] == 2 and not actual['tracking_error']
            assert len(set(request)) == 17
        finally:
            _finish_tracked(owned, process)


def test_tracked_new_session_process_limit_retains_full_original_claim(private_control):
    c = private_control
    attempt, manifest, request, kwargs = _tracked_fixture(c, child_process_slots=1)
    with _owner(c, kwargs) as owned:
        key = owned.reservation_id
        process = _start_attached(owned, request, manifest)
        try:
            _nested_ready(owned, attempt)
            assert native_disk._group_usage(owned._child)['live_processes'] == 1
            with pytest.raises(validation.ValidationResourceError, match='process limit'):
                owned.check_limits()
        finally:
            _finish_tracked(owned, process)
    row = _json(c['ledger'])['reservations'][key]
    assert row['status'] == 'retained' and row['storage_bytes'] == kwargs['storage_bytes']
    assert row['process_scope'] == validation.TRACKED_SCOPE


def test_parent_exit_preserves_retained_new_session_and_blocks_sealing(private_control):
    c = private_control
    c['source'].write_text(TRACKED_CHILD_SOURCE)
    attempt, manifest, request, kwargs = c['prepare'](mode='tracked_parent_exit',
        mutate=lambda value: value.update(process_scope=validation.TRACKED_SCOPE))
    with _owner(c, kwargs) as owned:
        process = _start_attached(owned, request, manifest)
        try:
            pid, birth, _ = _nested_ready(owned, attempt)
            (attempt/'tmp'/'allow-parent-exit').write_text('explicit fixture handshake')
            process.wait(timeout=5)
            assert process.returncode == 0
            observed = owned.observe_processes()
            assert observed['group_rss']['live_processes'] == 0
            assert observed['live_processes'] == 1
            assert any(row['pid'] == pid and row['birth'] == birth
                       for row in observed['out_of_group_live_identities'])
            with pytest.raises(validation.ValidationResourceError, match='tracked descendants.*alive'):
                owned.seal_results(attempt/'logs'/'not-a-result.json')
        finally:
            _finish_tracked(owned, process)
        closed = owned.observe_processes()
        assert closed['live_processes'] == 0
        assert any(row['pid'] == pid for row in closed['observed_identities'])


def test_live_retained_session_prevents_weaker_failure_exit_releasing_native_lease(private_control):
    c = private_control
    attempt, manifest, request, kwargs = _tracked_fixture(c)
    owned = _owner(c, kwargs).open()
    process = _start_attached(owned, request, manifest)
    try:
        pid, birth, _ = _nested_ready(owned, attempt)
        # A changed decoded request must refuse productive work, and must not
        # downgrade the cleanup scope frozen from the authenticated manifest.
        owned.request['process_scope'] = validation.GROUP_SCOPE
        assert owned.tracks_descendants
        with pytest.raises(validation.ValidationResourceError, match='in-memory.*changed'):
            owned.check_limits()
        _stop_group(process)
        assert native_disk._group_usage(owned._child)['live_processes'] == 0
        assert owned.__exit__(RuntimeError, RuntimeError('fixture cancellation'), None) is False
        row = _json(c['ledger'])['reservations'][owned.reservation_id]
        assert row['status'] == 'retained'
        assert row['retention_reason'] == 'tracked_descendant_cleanup_unresolved'
        lease = owned.to_dict()['resource_lease']['lease_id']
        assert lease in _json(c['scheduler'].state_path)['leases']
        assert native_disk._process(pid)['birth'] == birth
        assert owned._opened and owned.to_dict()['cleanup_error']
    finally:
        owned.request['process_scope'] = validation.TRACKED_SCOPE
        _finish_tracked(owned, process)
        owned.__exit__(RuntimeError, RuntimeError('drained fixture failure'), None)
    assert owned.to_dict()['resource_lease']['lease_id'] not in _json(c['scheduler'].state_path)['leases']


def test_observation_error_retains_failure_custody_even_when_original_group_is_dead(private_control, monkeypatch):
    c = private_control
    attempt, manifest, request, kwargs = _tracked_fixture(c)
    owned = _owner(c, kwargs).open()
    process = _start_attached(owned, request, manifest)
    try:
        _nested_ready(owned, attempt)
        _stop_group(process)
        with monkeypatch.context() as fault:
            fault.setattr(owned._descendants, 'error', 'deliberate bounded observation fault')
            with pytest.raises(validation.ValidationResourceError, match='observation failed'):
                owned.drain_tracked_descendants(.05)
            assert owned.__exit__(RuntimeError, RuntimeError('original refusal'), None) is False
            assert owned._opened
            assert owned.to_dict()['process_observation']['tracking_error']
            lease = owned.to_dict()['resource_lease']['lease_id']
            assert lease in _json(c['scheduler'].state_path)['leases']
            assert _json(c['ledger'])['reservations'][owned.reservation_id]['retention_reason'] == 'tracked_descendant_cleanup_unresolved'
    finally:
        _finish_tracked(owned, process)
        owned.__exit__(RuntimeError, RuntimeError('drained fixture failure'), None)


def test_tracking_cleanup_refuses_changed_owner_birth_before_signalling(private_control, monkeypatch):
    c = private_control
    attempt, manifest, request, kwargs = _tracked_fixture(c)
    with _owner(c, kwargs) as owned:
        process = _start_attached(owned, request, manifest)
        try:
            pid, birth, _ = _nested_ready(owned, attempt)
            original = native_disk._process
            def changed_owner(candidate):
                value = original(candidate)
                if candidate == os.getpid() and value is not None:
                    value = dict(value, birth=str(int(value['birth']) + 1))
                return value
            with monkeypatch.context() as fault:
                fault.setattr(native_disk, '_process', changed_owner)
                with pytest.raises(validation.ValidationResourceError, match='another owner'):
                    owned.drain_tracked_descendants(.05)
            assert native_disk._process(pid)['birth'] == birth
            assert native_disk._process(pid)['state'] != 'Z'
        finally:
            _finish_tracked(owned, process)


def _tracked_cli(control, *, succeeds):
    attempt, manifest, request, kwargs = control['prepare'](timeout_seconds=30,
        child_process_slots=2, mutate=lambda value: value.update(process_scope=validation.TRACKED_SCOPE))
    package_root = Path(validation.__file__).resolve().parents[3]
    launcher = package_root/'scripts'/'ops'/'legal_ir'/'run_owned_validation.py'
    source = control['source']
    # The child announces its real setsid helper before waiting. On failures the
    # launcher takes a final ancestry sample before terminating the parent.
    source.write_text("import os,subprocess,sys,time\nfrom pathlib import Path\n"
        "root=Path(sys.argv[1])\n"
        "body=\"import signal,sys,time; from pathlib import Path; signal.signal(signal.SIGTERM,signal.SIG_IGN); Path(sys.argv[1]).write_text('ready'); time.sleep(20)\"\n"
        "child=subprocess.Popen([sys.executable,'-B','-c',body,str(root/'logs'/'nested-ready')],stdin=subprocess.DEVNULL,start_new_session=True)\n"
        "(root/'logs'/'nested.pid').write_text(str(child.pid))\n"
        + ("time.sleep(.5)\nchild.kill()\nchild.wait(timeout=5)\nassert 6*7==42\nprint('actual-tracked-check=42',flush=True)\n"
           if succeeds else "time.sleep(20)\n"))
    request['argv'] = [sys.executable, '-B', str(source), str(attempt)]
    request['selected_checks'] = ['actual tracked Python fixture']
    shared = package_root/'ipfs_datasets_py'/'logic'/'backends'/'process.py'
    paths = [launcher, source, Path(validation.__file__), Path(native_disk.__file__),
             Path(native.__file__), Path(existing.__file__),
             Path(native.__file__).with_name('proof_resource_safety.py'), shared]
    request['source_sha256'] = {str(path.resolve()): _sha(path) for path in paths}
    _write_json(manifest, request)
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
        IPFS_DATASETS_PY_MINIMAL_IMPORTS='1', IPFS_DATASETS_AUTO_INSTALL='0',
        IPFS_AUTO_INSTALL='false', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
        OPENBLAS_NUM_THREADS='1')
    cli = subprocess.Popen([sys.executable, '-B', str(launcher), '--request', str(manifest),
        '--expected-request-sha256', _sha(manifest), '--resource-ledger', str(control['ledger'])],
        cwd=package_root, env=environment, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, start_new_session=True)
    return cli, attempt, source, request


@pytest.mark.parametrize('refusal', ['cancel', 'source_drift'])
def test_actual_cli_drains_real_new_session_on_cancel_or_source_watchdog(private_control, refusal):
    c = private_control
    cli, attempt, source, request = _tracked_cli(c, succeeds=False)
    nested = None
    try:
        _wait_for(lambda: (attempt/'logs'/'nested-ready').is_file(), 'tracked CLI child did not become ready', timeout=15)
        nested = native_disk._process(int((attempt/'logs'/'nested.pid').read_text()))
        assert nested is not None and nested['group_pid'] == nested['pid']
        if refusal == 'cancel':
            cli.send_signal(signal.SIGTERM)
        else:
            source.write_text(source.read_text()+'\n# deliberate private source watchdog mutation\n')
        stdout, stderr = cli.communicate(timeout=15)
        assert cli.returncode != 0, (stdout, stderr)
        current = native_disk._process(nested['pid'])
        assert current is None or current['birth'] != nested['birth'] or current['state'] == 'Z'
        failure = _json(attempt/'logs'/'failure.json')
        assert failure['completed'] is False and not failure['Lean_admitted']
        assert failure['process_observation']['scope'] == validation.TRACKED_SCOPE
        assert failure['process_observation']['live_processes'] == 0
        assert failure['process_cleanup_error'] is None
        terminal = json.loads(stdout)
        assert terminal['schema'] == 'owned-validation-failure-terminal/v1'
        assert terminal['completed'] is False and terminal['admitted'] is False
        assert terminal['Lean_admitted'] is False
        assert terminal['failure'] == failure
        assert terminal['request_sha256'] == failure['request_sha256']
        assert terminal['process_cleanup_error'] is None and terminal['owner_exit_error'] is None
        original_owner = terminal['reservation']
        assert original_owner['status'] == 'retained'
        assert original_owner['record']['status'] == 'retained'
        assert original_owner['record']['storage_bytes'] == request['storage_bytes']
        assert original_owner['resource_lease']['released'] is True
        assert original_owner['cleanup_error'] is None
        after_exit = original_owner['process_observation']
        assert after_exit['scope'] == validation.TRACKED_SCOPE
        assert after_exit['live_processes'] == 0
        assert after_exit['group_rss']['live_processes'] == 0
        assert after_exit['tracking_error'] == ''
        assert after_exit['out_of_group_live_identities'] == []
        assert any(row['pid'] == nested['pid'] and str(row['birth_ticks']) == nested['birth']
                   for row in failure['process_observation']['observed_identities'])
        rows = [row for key, row in _json(c['ledger'])['reservations'].items() if key != 'foreign-retained']
        assert len(rows) == 1 and rows[0]['status'] == 'retained'
        assert rows[0]['process_scope'] == validation.TRACKED_SCOPE
        assert rows[0]['storage_bytes'] == request['storage_bytes']
        assert not _json(c['scheduler'].state_path)['leases']
        assert not (attempt/'logs'/'result.json').exists()
        assert not (attempt/'logs'/'validation-durability.json').exists()
    finally:
        if cli.poll() is None:
            cli.send_signal(signal.SIGTERM)
            cli.wait(timeout=15)
        _stop_group(cli)
        if nested is not None:
            current = native_disk._process(nested['pid'])
            if current is not None and current['birth'] == nested['birth'] and current['state'] != 'Z':
                os.kill(nested['pid'], signal.SIGKILL)


def test_actual_cli_saves_completed_explicit_tracked_scope_before_release(private_control):
    c = private_control
    cli, attempt, _, request = _tracked_cli(c, succeeds=True)
    try:
        stdout, stderr = cli.communicate(timeout=20)
        assert cli.returncode == 0, (stdout, stderr)
    finally:
        _stop_group(cli)
    execution = _json(attempt/'logs'/'execution.json')
    assert execution['completed'] and execution['returncode'] == 0
    assert execution['resource_scope'] == 'cooperative_sampled_birth_bound_descendants_and_owned_attempt'
    assert execution['process_observation']['scope'] == validation.TRACKED_SCOPE
    assert execution['process_observation']['live_processes'] == 0
    assert execution['process_observation']['tracking_error'] == ''
    terminal = json.loads(stdout)
    assert terminal['reservation']['status'] == 'released'
    assert terminal['reservation']['process_observation']['live_processes'] == 0
    assert terminal['reservation']['resource_lease']['lease_id'] not in _json(c['scheduler'].state_path)['leases']
    assert (attempt/'logs'/'validation-durability.json').is_file()
    assert not execution['Lean_admitted']
    assert len(request) == 17


def test_legacy_scope_receipt_does_not_claim_tracked_descendant_observation(private_control):
    c = private_control
    _, manifest, request, kwargs = c['prepare']()
    with _owner(c, kwargs) as owned:
        assert not owned.tracks_descendants and owned._descendants is None
        result = _complete(owned, request, manifest)
        owned.seal_results(result)
        terminal = owned.finalize(artifacts_durable=True)
    assert terminal['status'] == 'released'
    assert terminal['record']['process_scope'] == 'isolated_process_group_only'
    assert 'process_observation' not in terminal
    assert request['process_scope'] == 'isolated_process_group'
    assert len(request) == 17


def test_tracked_attachment_update_failure_retains_tracker_for_cleanup(private_control, monkeypatch):
    """A real blocked child remains owned when its ledger attachment fails."""
    c = private_control
    attempt, manifest, request, kwargs = _tracked_fixture(c, child_process_slots=1)
    owned = _owner(c, kwargs).open()
    lease_id = owned.to_dict()['resource_lease']['lease_id']
    attachment_error = native_disk.DaemonResourceError('injected attachment ledger update unavailable')
    process, rejected_updates = None, []
    try:
        process = subprocess.Popen(
            request['argv'], cwd=request['cwd'], env=owned.environment(os.environ),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
        actual = _wait_for(lambda: native_disk._process(process.pid), 'blocked child identity unavailable')
        expected_child = {'pid': process.pid, 'birth': actual['birth']}
        assert actual['parent_pid'] == os.getpid() and actual['group_pid'] == process.pid
        original_update = owned._update
        def fail_child_update(**fields):
            if fields.get('child') is not None:
                assert fields['child'] == expected_child
                rejected_updates.append(deepcopy(fields))
                raise attachment_error
            return original_update(**fields)
        with monkeypatch.context() as fault:
            fault.setattr(owned, '_update', fail_child_update)
            with pytest.raises(native_disk.DaemonResourceError, match='injected attachment ledger update') as caught:
                owned.attach_child(process.pid)
            assert caught.value is attachment_error
        assert len(rejected_updates) == 1
        assert owned._child == expected_child
        assert owned.to_dict()['record']['child'] is None
        assert _json(c['ledger'])['reservations'][owned.reservation_id]['child'] is None
        tracker = owned._descendants
        assert tracker is not None and tracker.enabled and tracker.error == ''
        assert tracker.records[process.pid][0] == int(expected_child['birth'])
        assert (process.pid, int(expected_child['birth'])) in tracker.history
        observed = owned.observe_processes()
        assert observed['scope'] == validation.TRACKED_SCOPE and observed['tracking_error'] == ''
        assert observed['live_processes'] == observed['group_rss']['live_processes'] == 1
        assert observed['out_of_group_live_identities'] == []
        assert any(row['pid'] == process.pid and str(row['birth_ticks']) == expected_child['birth']
                   for row in observed['observed_identities'])
        # No handshake is written. The genuine child cannot reach the nested
        # process or productive work after its two explicit stdin barriers.
        assert process.poll() is None and process.stdin is not None and not process.stdin.closed
        assert not (attempt / 'logs/nested.pid').exists()
        assert not (attempt / 'logs/nested-ready').exists()
        assert not (attempt / 'exports/checked.json').exists()
        assert lease_id in _json(c['scheduler'].state_path)['leases']
    finally:
        try:
            if process is not None:
                _finish_tracked(owned, process)
        finally:
            owned.__exit__(RuntimeError, attachment_error, None)
    assert process.returncode is not None
    assert lease_id not in _json(c['scheduler'].state_path)['leases']
    assert owned.to_dict()['resource_lease']['released'] is True
    assert owned.to_dict()['cleanup_error'] is None and not owned._opened
    row = _json(c['ledger'])['reservations'][owned.reservation_id]
    assert row['status'] == 'retained' and row['storage_bytes'] == kwargs['storage_bytes']
    assert row['child'] is None and row['process_scope'] == validation.TRACKED_SCOPE
    assert _json(c['ledger'])['reservations']['foreign-retained'] == c['foreign']
    assert _json(c['scheduler'].state_path)['config'] == c['policy']


@pytest.mark.parametrize('rejection_point', ['before_sampling', 'after_sampling'])
def test_tracked_attachment_rejected_initial_identity_is_never_drained(private_control, monkeypatch, rejection_point):
    """Rejected initial samples cannot become a scope that cleanup may signal."""
    from ipfs_datasets_py.logic.backends import process as process_backend
    c = private_control
    attempt, manifest, request, kwargs = _tracked_fixture(c, child_process_slots=1)
    owned = _owner(c, kwargs).open()
    lease_id = owned.to_dict()['resource_lease']['lease_id']
    attachment_error = native_disk.DaemonResourceError('injected attachment ledger update unavailable')
    process = None
    sampled, closed, drained, signalled, child_queries = [], [], [], [], []
    try:
        process = subprocess.Popen(
            request['argv'], cwd=request['cwd'], env=owned.environment(os.environ),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
        actual = _wait_for(lambda: native_disk._process(process.pid), 'blocked child identity unavailable')
        expected_child = {'pid': process.pid, 'birth': actual['birth']}
        original_update, original_process = owned._update, native_disk._process
        tracker_type = process_backend._LinuxDescendantTracker
        original_refresh, original_close = tracker_type.refresh, tracker_type.close
        original_drain, original_signal = tracker_type.drain, tracker_type.signal_descendants
        reject_query = 2 if rejection_point == 'before_sampling' else 3
        def fail_child_update(**fields):
            if fields.get('child') is not None:
                assert fields['child'] == expected_child
                raise attachment_error
            return original_update(**fields)
        def selected_identity(pid):
            value = original_process(pid)
            if pid == process.pid:
                child_queries.append(value)
                if len(child_queries) == reject_query:
                    assert value is not None and value['birth'] == expected_child['birth']
                    return dict(value, birth=str(int(value['birth']) + 1))
            return value
        def sample(tracker):
            original_refresh(tracker)
            if tracker.leader_pid == process.pid:
                sampled.append(tracker)
                assert tracker.records[process.pid][0] == int(expected_child['birth'])
        def close_sample(tracker):
            descriptors = [descriptor for _, descriptor in tracker.records.values() if descriptor is not None]
            original_close(tracker)
            if tracker.leader_pid == process.pid:
                assert tracker.records == {}
                for descriptor in descriptors:
                    with pytest.raises(OSError):
                        os.fstat(descriptor)
                closed.append(tracker)
        def forbid_drain(tracker, *args, **kwargs):
            if tracker.leader_pid == process.pid:
                drained.append(tracker)
                raise AssertionError('rejected initial tracker must not drain')
            return original_drain(tracker, *args, **kwargs)
        def forbid_signal(tracker, *args, **kwargs):
            if tracker.leader_pid == process.pid:
                signalled.append(tracker)
                raise AssertionError('rejected initial tracker must not signal')
            return original_signal(tracker, *args, **kwargs)
        with monkeypatch.context() as fault:
            fault.setattr(owned, '_update', fail_child_update)
            fault.setattr(native_disk, '_process', selected_identity)
            fault.setattr(tracker_type, 'refresh', sample)
            fault.setattr(tracker_type, 'close', close_sample)
            fault.setattr(tracker_type, 'drain', forbid_drain)
            fault.setattr(tracker_type, 'signal_descendants', forbid_signal)
            with pytest.raises(native_disk.DaemonResourceError, match='injected attachment ledger update') as caught:
                owned.attach_child(process.pid)
            assert caught.value is attachment_error
            assert len(child_queries) == reject_query
            assert any('birth differs ' + rejection_point.replace('_', ' ') in note
                       for note in caught.value.__notes__)
            assert owned._child == expected_child and owned._descendants is None
            assert owned.to_dict()['record']['child'] is None
            assert _json(c['ledger'])['reservations'][owned.reservation_id]['child'] is None
            assert owned.drain_tracked_descendants(.05) is None
            with pytest.raises(validation.ValidationResourceError, match='no retained descendant owner'):
                owned.observe_processes()
            assert drained == signalled == []
            if rejection_point == 'before_sampling':
                assert sampled == closed == []
            else:
                assert len(sampled) == len(closed) == 1 and sampled[0] is closed[0]
                assert sampled[0].records == {}
            assert process.poll() is None and process.stdin is not None and not process.stdin.closed
            assert not (attempt / 'logs/nested.pid').exists()
            assert not (attempt / 'logs/nested-ready').exists()
            assert not (attempt / 'exports/checked.json').exists()
            assert lease_id in _json(c['scheduler'].state_path)['leases']
    finally:
        try:
            if process is not None:
                # Only after the selected fault is removed, retain the actual
                # still-blocked original birth through the genuine owner.
                try:
                    owned._retain_attached_descendants()
                finally:
                    _finish_tracked(owned, process)
        finally:
            owned.__exit__(RuntimeError, attachment_error, None)
    assert process.returncode is not None
    assert lease_id not in _json(c['scheduler'].state_path)['leases']
    assert owned.to_dict()['resource_lease']['released'] is True
    assert owned.to_dict()['cleanup_error'] is None and not owned._opened
    row = _json(c['ledger'])['reservations'][owned.reservation_id]
    assert row['status'] == 'retained' and row['storage_bytes'] == kwargs['storage_bytes']
    assert row['child'] is None and row['process_scope'] == validation.TRACKED_SCOPE
    assert _json(c['ledger'])['reservations']['foreign-retained'] == c['foreign']
    assert _json(c['scheduler'].state_path)['config'] == c['policy']


# The lifecycle extension is exercised under real private native admission. The
# outer owned test run retains the actual host resource and writable scope.
def _lifecycle_launcher_module():
    import importlib.util
    launcher = Path(validation.__file__).resolve().parents[3]/'scripts/ops/legal_ir/run_owned_validation.py'
    spec = importlib.util.spec_from_file_location('canonical_validation_lifecycle_under_test', launcher)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, launcher


def _prepare_no_child_lifecycle(control):
    module, launcher = _lifecycle_launcher_module()
    attempt, manifest, request, kwargs = control['prepare'](memory_mb=4096,
        mutate=lambda value: value.update(process_scope=validation.TRACKED_SCOPE))
    request['argv'] = [sys.executable, '-B', str(control['source'])]
    paths = [launcher, control['source'], Path(validation.__file__), Path(native_disk.__file__),
        Path(native.__file__), Path(existing.__file__), Path(native.__file__).with_name('proof_resource_safety.py')]
    request['source_sha256'] = {str(path.resolve()): _sha(path) for path in paths}
    _write_json(manifest, request)
    kwargs['frozen_validation_manifest_sha256'] = _sha(manifest)
    return module, launcher, attempt, manifest, request, kwargs


def _actual_no_child_cli(control):
    module, launcher, attempt, manifest, request, kwargs = _prepare_no_child_lifecycle(control)
    blocker = control['scheduler'].acquire(native.ResourceLane.VALIDATION,
        cpu_slots=1, memory_mb=1, child_process_slots=0, timeout=0,
        request_id='private-no-child-admission-blocker')
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
        IPFS_DATASETS_PY_MINIMAL_IMPORTS='1', IPFS_DATASETS_AUTO_INSTALL='0',
        IPFS_AUTO_INSTALL='false', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    cli = None
    try:
        cli = subprocess.Popen([sys.executable, '-B', str(launcher), '--request', str(manifest),
            '--expected-request-sha256', _sha(manifest), '--resource-ledger', str(control['ledger'])],
            cwd=launcher.parents[3], env=environment, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        identity = native_disk._process(cli.pid)
        assert identity is not None
        stdout, stderr = cli.communicate(timeout=30)
        assert cli.returncode != 0, (stdout, stderr)
        terminal = json.loads(stdout)
        assert terminal['failure']['error_type'] == 'LeaseTimeoutError', (stdout, stderr)
        caller = dict(expected_request_sha256=_sha(manifest), owner_pid=cli.pid,
            owner_birth=identity['birth'], returncode=cli.returncode,
            expected_resource_ledger=str(control['ledger']))
        return module, terminal, manifest.read_bytes(), caller, attempt
    finally:
        if cli is not None:
            if cli.poll() is None:
                cli.terminate()
                cli.wait(timeout=10)
            _stop_group(cli)
        blocker.release()


def test_actual_cli_native_timeout_proves_no_child_source_custody_and_retains_storage(private_control):
    module, terminal, request_raw, caller, attempt = _actual_no_child_cli(private_control)
    verdict = module.classify_owned_validation_source_custody(terminal, request_raw, **caller)
    assert verdict == {'verdict': 'proven_original_no_child_no_native_grant',
        'source_custody_closed': True, 'storage_release_authorized': False}
    original = terminal['reservation']
    assert original['resource_lease'] is None and original['process_observation'] is None
    assert original['record']['child'] is None and original['record']['prior_children'] == []
    assert original['status'] == original['record']['status'] == 'retained'
    assert original['record']['retention_reason'] == 'scheduler_admission_failed'
    assert original['record']['artifacts_durable_asserted'] is False
    assert not tuple(attempt.iterdir())
    witness = terminal['source_custody_lifecycle']
    assert witness['events'] == dict(owner_open_attempted=True, owner_open_returned=False,
        child_launch_attempted=False, child_created=False, barrier_release_attempted=False,
        barrier_released=False, owner_exit_handling_completed=True)
    assert witness['native_grant']['exact_native_timeout'] is True
    assert witness['native_grant']['timeout_decision']['request_id'] == 'validation:' + original['reservation_id']
    assert witness['owner'] == {'pid': caller['owner_pid'], 'birth': caller['owner_birth']}
    # Authored metadata perturbation proves storage cleanup is a separate claim;
    # this is not evidence that the real fixture encountered a storage failure.
    retained_failure = deepcopy(terminal)
    retained_failure['reservation']['cleanup_error'] = 'DaemonResourceError'
    retained_failure['source_custody_lifecycle']['storage']['cleanup_error'] = 'DaemonResourceError'
    assert module.classify_owned_validation_source_custody(retained_failure, request_raw, **caller) == verdict


def test_original_no_child_classifier_refuses_spoofed_mismatched_or_started_evidence(private_control):
    module, terminal, request_raw, caller, _ = _actual_no_child_cli(private_control)
    assert module.classify_owned_validation_source_custody(terminal, request_raw, **caller)['source_custody_closed'] is True
    for damage in ('missing', 'schema', 'request', 'owner_pid', 'owner_birth', 'producer', 'policy',
            'ledger', 'reservation', 'launch_attempt', 'child_created', 'barrier_attempt', 'barrier_released',
            'open_returned', 'exit_incomplete', 'acquired', 'subclass', 'timeout_request', 'timeout_integer',
            'grant_integer', 'cancelled', 'source_guard', 'budget_bool', 'attached_child', 'process_observation',
            'process_cleanup', 'exit_error', 'admitted_outcome', 'storage_release'):
        changed = deepcopy(terminal)
        witness = changed['source_custody_lifecycle']
        decision = witness['native_grant']['timeout_decision']
        if damage == 'missing': changed.pop('source_custody_lifecycle')
        elif damage == 'schema': witness['schema'] = 'owned-validation-source-custody-lifecycle/v0'
        elif damage == 'request': witness['request_sha256'] = '0'*64
        elif damage == 'owner_pid': witness['owner']['pid'] += 1
        elif damage == 'owner_birth': witness['owner']['birth'] += '1'
        elif damage == 'producer': witness['producer']['sha256'] = '0'*64
        elif damage == 'policy': witness['scheduler']['policy_sha256'] = '0'*64
        elif damage == 'ledger': witness['ledger_path'] += '.foreign'
        elif damage == 'reservation': witness['reservation_id'] += '-foreign'
        elif damage in ('launch_attempt', 'child_created', 'barrier_attempt', 'barrier_released', 'open_returned'):
            key = {'launch_attempt': 'child_launch_attempted', 'child_created': 'child_created',
                'barrier_attempt': 'barrier_release_attempted', 'barrier_released': 'barrier_released',
                'open_returned': 'owner_open_returned'}[damage]
            witness['events'][key] = True
        elif damage == 'exit_incomplete': witness['events']['owner_exit_handling_completed'] = False
        elif damage == 'acquired': witness['native_grant']['status'] = 'acquired'
        elif damage == 'subclass':
            changed['failure']['error_type'] = 'ResourceAdmissionDeadlineError'
            witness['native_grant']['exact_native_timeout'] = False
        elif damage == 'timeout_request': decision['request_id'] += '-foreign'
        elif damage == 'timeout_integer': decision['timed_out'] = 1
        elif damage == 'grant_integer': decision['can_grant_now'] = 0
        elif damage == 'cancelled': decision['externally_cancelled'] = True
        elif damage == 'source_guard': witness['source_guards']['source_pins_unchanged'] = False
        elif damage == 'budget_bool': witness['budgets']['cpu_slots'] = True
        elif damage == 'attached_child': witness['owner_child_attached'] = True
        elif damage == 'process_observation': changed['reservation']['process_observation'] = {'live_processes': 1}
        elif damage == 'process_cleanup': changed['process_cleanup_error'] = 'unresolved'
        elif damage == 'exit_error': changed['owner_exit_error'] = 'unresolved'
        elif damage == 'admitted_outcome': changed['failure']['admitted'] = True
        else: witness['storage']['release_authorized'] = True
        result = module.classify_owned_validation_source_custody(changed, request_raw, **caller)
        assert result == {'verdict': 'requires_original_native_cleanup',
            'source_custody_closed': False, 'storage_release_authorized': False}, damage
    for key, value in (('owner_pid', True), ('returncode', 0), ('returncode', False),
            ('expected_request_sha256', '0'*64), ('expected_resource_ledger', str(private_control['ledger'])+'.foreign')):
        assert module.classify_owned_validation_source_custody(terminal, request_raw,
            **{**caller, key: value})['source_custody_closed'] is False, key
    for filename in module._LIFECYCLE_OWNER_NAMES:
        sparse_request = json.loads(request_raw)
        path = str(module.ROOT/'ipfs_datasets_py/optimizers/logic_theorem_optimizer'/filename)
        sparse_request['source_sha256'].pop(path)
        sparse_raw = json.dumps(sparse_request, sort_keys=True, separators=(',', ':')).encode()
        sparse_pin = hashlib.sha256(sparse_raw).hexdigest()
        sparse_terminal = deepcopy(terminal)
        sparse_terminal['request_sha256'] = sparse_pin
        sparse_terminal['failure']['request_sha256'] = sparse_pin
        sparse_terminal['source_custody_lifecycle']['request_sha256'] = sparse_pin
        assert module.classify_owned_validation_source_custody(sparse_terminal, sparse_raw,
            **{**caller, 'expected_request_sha256': sparse_pin})['source_custody_closed'] is False, filename
        with pytest.raises(ValueError, match='original lifecycle owner source pins'):
            module._lifecycle_source_guard(sparse_request)
    source = private_control['source']
    original = source.read_bytes()
    try:
        source.write_bytes(original + b'\n# authored post-exit pinned source drift\n')
        assert module.classify_owned_validation_source_custody(terminal, request_raw, **caller)['source_custody_closed'] is False
    finally:
        source.write_bytes(original)
    assert module.classify_owned_validation_source_custody(terminal, request_raw, **caller)['source_custody_closed'] is True


def test_lifecycle_builder_never_promotes_subclass_spoof_or_legacy_timeout(private_control):
    control = private_control
    module, _, _, manifest, request, kwargs = _prepare_no_child_lifecycle(control)
    blocker = control['scheduler'].acquire(native.ResourceLane.VALIDATION,
        cpu_slots=1, memory_mb=1, child_process_slots=0, timeout=0,
        request_id='private-builder-admission-blocker')
    owner = _owner(control, kwargs)
    try:
        with pytest.raises(native.LeaseTimeoutError) as caught:
            owner.open()
        genuine = caught.value
        assert type(genuine) is native.LeaseTimeoutError
        owner.__exit__(type(genuine), genuine, None)
        reservation = owner.to_dict()
        events = dict(owner_open_attempted=True, owner_open_returned=False,
            child_launch_attempted=False, child_created=False,
            barrier_release_attempted=False, barrier_released=False)
        def witness(error):
            return module._source_custody_witness(owner, reservation, request,
                manifest.read_bytes(), manifest, _sha(manifest), events, error,
                exit_handling_completed=True)
        assert witness(genuine)['native_grant']['status'] == 'not_acquired_terminal_timeout'
        spoof = type('LeaseTimeoutError', (RuntimeError,), {})('authored spoof')
        spoof.timeout_decision = deepcopy(genuine.timeout_decision)
        legacy = native.LeaseTimeoutError('legacy message without decision')
        subclass = native.ResourceAdmissionDeadlineError('deadline subclass',
            timeout_decision=genuine.timeout_decision)
        mismatch = native.LeaseTimeoutError('wrong request',
            timeout_decision={**genuine.timeout_decision, 'request_id': 'foreign'})
        for error in (spoof, legacy, subclass, mismatch):
            observed = witness(error)
            assert observed['native_grant']['status'] == 'unknown'
            assert observed['storage']['release_authorized'] is False
    finally:
        blocker.release()


# These source-only controls call the existing launcher file helpers directly.
# They create private fixture files and do not invoke main(), native admission,
# storage reservation, a worker, or a validation subprocess.
_EMPTY_SOURCE_SHA256 = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'


def test_source_snapshot_empty_regular_source_accepts_only_its_exact_pin(tmp_path):
    module, _ = _lifecycle_launcher_module()
    source = tmp_path / '__init__.py'
    source.write_bytes(b'')
    assert module.snapshot(source, allow_empty=True) == b''
    assert module.source_guard({'source_sha256': {str(source): _EMPTY_SOURCE_SHA256}}) is None
    with pytest.raises(ValueError, match='validation source changed'):
        module.source_guard({'source_sha256': {str(source): hashlib.sha256(b'changed').hexdigest()}})


def test_source_snapshot_default_and_request_still_refuse_empty_files(tmp_path):
    module, _ = _lifecycle_launcher_module()
    path = tmp_path / 'request.json'
    path.write_bytes(b'')
    with pytest.raises(ValueError, match='bounded unaliased regular input'):
        module.snapshot(path)
    with pytest.raises(ValueError, match='bounded unaliased regular input'):
        module.request(path, _EMPTY_SOURCE_SHA256)


def test_source_snapshot_nonempty_sources_and_requests_keep_exact_bytes_and_hashes(tmp_path):
    module, _ = _lifecycle_launcher_module()
    source = tmp_path / 'source.py'
    raw = b'pass\n'
    source.write_bytes(raw)
    assert module.snapshot(source) == module.snapshot(source, allow_empty=True) == raw
    assert module.source_guard({'source_sha256': {str(source): hashlib.sha256(raw).hexdigest()}}) is None
    with pytest.raises(ValueError, match='validation source changed'):
        module.source_guard({'source_sha256': {str(source): _EMPTY_SOURCE_SHA256}})
    request = tmp_path / 'request.json'
    request_raw = b'{"schema":"owned-validation-request/v1"}'
    request.write_bytes(request_raw)
    assert module.request(request, hashlib.sha256(request_raw).hexdigest()) == (
        {'schema': 'owned-validation-request/v1'}, request_raw)


@pytest.mark.parametrize('allow_empty', [None, 0, 1, '', 'true', [], {}])
def test_source_snapshot_empty_opt_in_requires_exact_bool(tmp_path, allow_empty):
    module, _ = _lifecycle_launcher_module()
    source = tmp_path / '__init__.py'
    source.write_bytes(b'')
    with pytest.raises(ValueError, match='exact bool'):
        module.snapshot(source, allow_empty=allow_empty)


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'fifo', 'directory', 'parent_symlink', 'missing'])
def test_source_snapshot_empty_opt_in_keeps_unsafe_file_refusals(tmp_path, kind):
    module, _ = _lifecycle_launcher_module()
    source = tmp_path / 'candidate.py'
    original = tmp_path / 'original.py'
    original.write_bytes(b'')
    try:
        if kind == 'symlink': source.symlink_to(original)
        elif kind == 'hardlink': os.link(original, source)
        elif kind == 'fifo': os.mkfifo(source)
        elif kind == 'directory': source.mkdir()
        elif kind == 'parent_symlink':
            directory = tmp_path / 'real-parent'
            directory.mkdir()
            (directory / 'candidate.py').write_bytes(b'')
            alias = tmp_path / 'aliased-parent'
            alias.symlink_to(directory, target_is_directory=True)
            source = alias / 'candidate.py'
        with pytest.raises((ValueError, OSError)):
            module.source_guard({'source_sha256': {str(source): _EMPTY_SOURCE_SHA256}})
    finally:
        if kind == 'parent_symlink':
            (tmp_path / 'aliased-parent').unlink(missing_ok=True)  # Never its target.
        elif kind == 'directory':
            if source.exists(): source.rmdir()  # Only the empty fixture-owned directory.
        else:
            source.unlink(missing_ok=True)  # Original hardlink target remains single-link.


def test_source_snapshot_empty_opt_in_preserves_existing_size_limits(tmp_path):
    module, _ = _lifecycle_launcher_module()
    source = tmp_path / 'source.py'
    source.write_bytes(b'1234')
    assert module.snapshot(source, maximum=4, allow_empty=True) == b'1234'
    source.write_bytes(b'12345')
    with pytest.raises(ValueError, match='bounded unaliased regular input'):
        module.snapshot(source, maximum=4, allow_empty=True)
    # A private sparse fixture crosses the unchanged4MiB source limit without
    # reading or allocating a real source population.
    with source.open('wb') as stream:
        stream.seek(4 * 1024 * 1024)
        stream.write(b'x')
    with pytest.raises(ValueError, match='bounded unaliased regular input'):
        module.source_guard({'source_sha256': {str(source): _EMPTY_SOURCE_SHA256}})


# Closed finite F18 trainer-controller controls. These cases use no model,
# native grant, real subprocess, or production task/claim fixture.
def _trainer_controller_request_case(tmp_path, *, paired=False):
    module, launcher = _lifecycle_launcher_module()
    root = tmp_path / "trainer-outputs"
    root.mkdir()
    attempt = root / "attempt"
    attempt.mkdir(mode=0o700)
    directory = module.ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer"
    names = ("autoencoder_daemon_resources.py", "autoencoder_daemon_operation_journal.py",
             "autoencoder_daemon_invocation_contracts.py", "resource_scheduler.py",
             "existing_resource_scheduler.py", "proof_resource_safety.py",
             "autoencoder_campaign_process_worker.py", "autoencoder_daemon_invocation_worker.py")
    pins = {str(path): _sha(path) for path in (launcher, *(directory / name for name in names))}
    value = {
        "schema": "owned-f18-conditions-training-request/v1",
        "mode": "paired_fit" if paired else "native_probe",
        "cwd": str(module.ROOT), "attempt_directory": str(attempt),
        "outputs": {name: str(attempt / name) for name in
                    ("logs", "exports", "tmp", "cache", "pytest", "db")},
        "roots": [str(root)], "source_sha256": pins,
        "cpu_slots": 1, "memory_mb": 2048, "storage_bytes": 128 * 1024 * 1024,
        "child_process_slots": 1, "timeout_seconds": 300,
        "scheduler_state_path": str(tmp_path / "existing-scheduler.json"),
        "expected_scheduler_policy_sha256": "a" * 64,
        "process_scope": "isolated_process_group", "compute": None,
    }
    if paired:
        value["compute"] = {
            name: {"path": str(tmp_path / (name + ".json")), "bytes": 17, "sha256": "b" * 64}
            for name in ("input_descriptors", "initial_parity", "runtime_contract", "population_manifest")
        }
        value["compute"].update(max_steps_per_arm=32, max_seconds_per_arm=32)
    path = tmp_path / "trainer-request.json"
    _write_json(path, value)
    return module, path, value


def _trainer_forbid_reference_bodies(monkeypatch, value):
    """Sentinel for content access, not a claim about physical-file custody."""
    import builtins
    refs = value["compute"] or {}
    forbidden = {Path(ref["path"]) for ref in refs.values() if type(ref) is dict and "path" in ref}
    attempts = []
    for owner, name in ((builtins, "open"), (os, "open"), (Path, "open")):
        genuine = getattr(owner, name)
        def guarded(path, *args, _genuine=genuine, **kwargs):
            if isinstance(path, (str, bytes, os.PathLike)) and Path(os.fsdecode(path)) in forbidden:
                attempts.append(str(path))
                raise AssertionError("trainer metadata/payload opened before RUN")
            return _genuine(path, *args, **kwargs)
        monkeypatch.setattr(owner, name, guarded)
    return attempts


def test_closed_trainer_probe_parser_is_detached_and_has_no_generic_command(tmp_path):
    module, path, offered = _trainer_controller_request_case(tmp_path)
    before = path.read_bytes()
    parsed, raw = module.trainer_request(path, _sha(path))
    assert raw == before and parsed == offered and parsed is not offered
    assert parsed["compute"] is None and set(parsed) == {
        "schema", "mode", "cwd", "attempt_directory", "outputs", "roots", "source_sha256",
        "cpu_slots", "memory_mb", "storage_bytes", "child_process_slots", "timeout_seconds",
        "scheduler_state_path", "expected_scheduler_policy_sha256", "process_scope", "compute"}
    assert "argv" not in parsed and "selected_checks" not in parsed
    offered["outputs"]["logs"] = "/foreign"
    assert parsed["outputs"]["logs"] != "/foreign"
    assert path.read_bytes() == before
    assert not Path(parsed["scheduler_state_path"]).exists()
    assert tuple(Path(parsed["attempt_directory"]).iterdir()) == ()


@pytest.mark.parametrize("damage", [
    "generic_argv", "validation_checks", "extra_field", "foreign_mode", "foreign_scope",
    "foreign_cwd", "attempt_outside_roots", "overlapping_roots", "output_escape",
    "boolean_cpu", "zero_children", "storage_over_bound", "deadline_over_bound", "probe_compute",
])
def test_closed_trainer_probe_rejects_unbounded_or_borrowed_scope_before_admission(tmp_path, damage):
    module, _, value = _trainer_controller_request_case(tmp_path)
    if damage == "generic_argv": value["argv"] = [sys.executable, "-c", "raise SystemExit(0)"]
    elif damage == "validation_checks": value["selected_checks"] = ["borrowed validation"]
    elif damage == "extra_field": value["admitted"] = True
    elif damage == "foreign_mode": value["mode"] = "arbitrary_worker"
    elif damage == "foreign_scope": value["process_scope"] = "sampled_birth_bound_descendants"
    elif damage == "foreign_cwd": value["cwd"] = str(tmp_path)
    elif damage == "attempt_outside_roots": value["roots"] = [str(tmp_path / "different")]
    elif damage == "overlapping_roots": value["roots"].append(str(Path(value["roots"][0]) / "nested"))
    elif damage == "output_escape": value["outputs"]["exports"] = str(tmp_path / "exports")
    elif damage == "boolean_cpu": value["cpu_slots"] = True
    elif damage == "zero_children": value["child_process_slots"] = 0
    elif damage == "storage_over_bound": value["storage_bytes"] = 50_000_000_001
    elif damage == "deadline_over_bound": value["timeout_seconds"] = 301
    else: value["compute"] = {}
    with pytest.raises(ValueError):
        module._validate_trainer_request(value)
    assert not Path(value["scheduler_state_path"]).exists()
    assert tuple(Path(value["attempt_directory"]).iterdir()) == ()


def test_closed_trainer_pair_reference_validation_opens_no_reference_body(tmp_path, monkeypatch):
    module, path, value = _trainer_controller_request_case(tmp_path, paired=True)
    attempts = _trainer_forbid_reference_bodies(monkeypatch, value)
    parsed, raw = module.trainer_request(path, _sha(path))
    module._trainer_source_guard(parsed)
    assert raw and parsed == value and parsed["compute"] is not value["compute"]
    assert set(parsed["compute"]) == {"input_descriptors", "initial_parity", "runtime_contract",
                                      "population_manifest", "max_steps_per_arm", "max_seconds_per_arm"}
    assert parsed["compute"]["max_steps_per_arm"] == parsed["compute"]["max_seconds_per_arm"] == 32
    assert attempts == [] and tuple(Path(value["attempt_directory"]).iterdir()) == ()


@pytest.mark.parametrize("damage", [
    "unknown_reference_field", "boolean_reference_bytes", "reference_over_bound", "missing_reference",
    "extra_steps", "boolean_steps", "extra_seconds", "boolean_seconds", "float_seconds",
])
def test_closed_trainer_pair_bounds_are_refused_without_reference_reads(tmp_path, monkeypatch, damage):
    module, _, value = _trainer_controller_request_case(tmp_path, paired=True)
    attempts = _trainer_forbid_reference_bodies(monkeypatch, value)
    compute = value["compute"]
    if damage == "unknown_reference_field": compute["initial_parity"]["gold"] = "forbidden"
    elif damage == "boolean_reference_bytes": compute["input_descriptors"]["bytes"] = True
    elif damage == "reference_over_bound": compute["runtime_contract"]["bytes"] = 131073
    elif damage == "missing_reference": compute.pop("population_manifest")
    elif damage == "extra_steps": compute["max_steps_per_arm"] = 33
    elif damage == "boolean_steps": compute["max_steps_per_arm"] = True
    elif damage == "extra_seconds": compute["max_seconds_per_arm"] = 33
    elif damage == "boolean_seconds": compute["max_seconds_per_arm"] = True
    else: compute["max_seconds_per_arm"] = 32.0
    with pytest.raises(ValueError):
        module._validate_trainer_request(value)
    assert attempts == [] and tuple(Path(value["attempt_directory"]).iterdir()) == ()


@pytest.mark.parametrize("damage", ["hash", "duplicate_JSON", "nonfinite_JSON", "empty"])
def test_closed_trainer_request_wire_refuses_ambiguity_and_hash_drift(tmp_path, damage):
    module, path, value = _trainer_controller_request_case(tmp_path)
    raw = path.read_bytes()
    expected = _sha(path)
    if damage == "hash": expected = "0" * 64
    elif damage == "duplicate_JSON":
        text = json.dumps(value)
        assert text.count('"mode": "native_probe"') == 1
        raw = text.replace('"mode": "native_probe"',
                           '"mode": "paired_fit", "mode": "native_probe"', 1).encode()
        path.write_bytes(raw)
        expected = _sha(path)
    elif damage == "nonfinite_JSON":
        value["timeout_seconds"] = float("nan")
        path.write_text(json.dumps(value))
        expected = _sha(path)
    else:
        path.write_bytes(b"")
        expected = _sha(path)
    with pytest.raises(ValueError):
        module.trainer_request(path, expected)
    assert tuple(Path(value["attempt_directory"]).iterdir()) == ()


def test_trainer_request_does_not_broaden_original_validation_parser(tmp_path):
    module, path, trainer = _trainer_controller_request_case(tmp_path)
    original = {"schema": "owned-validation-request/v1", "argv": ["unchanged-validation-command"]}
    for schema in ("owned-validation-request/v1", "owned-validation-request/v2",
                   "owned-validation-request/v4"):
        ordinary = {**original, "schema": schema}
        _write_json(path, ordinary)
        assert module.request(path, _sha(path))[0] == ordinary
    for schema in (module.TRAINER_REQUEST_SCHEMA, module.TRAINER_V2_REQUEST_SCHEMA):
        _write_json(path, {**trainer, "schema": schema})
        with pytest.raises(ValueError, match="unsupported validation request"):
            module.request(path, _sha(path))
    with pytest.raises(ValueError):
        module._validate_trainer_request({"schema": "owned-validation-request/v1"})


def test_trainer_source_guard_requires_public_owner_and_rechecks_owned_source(tmp_path):
    module, _, value = _trainer_controller_request_case(tmp_path)
    module._trainer_source_guard(value)
    owner_source = str(module.ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py")
    assert value["source_sha256"][owner_source] == "c99d78004e6ce6b8a861f15e2c0b7009bbb6f45a37a89daabc8894ac440b282d"
    missing = deepcopy(value)
    missing["source_sha256"].pop(owner_source)
    with pytest.raises(ValueError):
        module._trainer_source_guard(missing)
    borrowed = deepcopy(value)
    borrowed["source_sha256"][owner_source] = "0a2ee6f66c0b7613dc4b44966c9b991fbda9faf1fbc7eb3aa00c3ac5be9c8238"
    with pytest.raises(ValueError, match="different original public trainer backend"):
        module._trainer_source_guard(borrowed)
    source = tmp_path / "owned_source_marker.py"
    source.write_text("value = 1\n")
    value["source_sha256"][str(source)] = _sha(source)
    module._trainer_source_guard(value)
    source.write_text("value = 2\n")
    with pytest.raises(ValueError, match="source changed"):
        module._trainer_source_guard(value)


def _trainer_ready_case(module):
    identity = {"pid": 20123, "group_pid": 20123, "birth": "90123"}
    owner_pid, request_pin = 20122, "c" * 64
    payload = {"schema": "owned-f18-conditions-training-ready/v1", "identity": deepcopy(identity),
               "owner_pid": owner_pid, "request_sha256": request_pin, "canonical_root": str(module.ROOT),
               "network_guard": {"mechanism": "linux_seccomp", "denied_syscalls": [
                   "socket", "connect", "sendto", "sendmsg", "sendmmsg"], "socket_denial_verified": True}}
    return payload, dict(identity=identity, owner_pid=owner_pid, request_pin=request_pin)


def test_trainer_READY_accepts_only_exact_owner_birth_request_and_bootstrap_evidence():
    module, _ = _lifecycle_launcher_module()
    payload, expected = _trainer_ready_case(module)
    assert module._trainer_ready(payload, **expected) == payload


@pytest.mark.parametrize("damage", ["owner_boolean", "group", "birth", "request", "network", "network_boolean"])
def test_trainer_READY_refuses_foreign_or_malformed_evidence(damage):
    module, _ = _lifecycle_launcher_module()
    payload, expected = _trainer_ready_case(module)
    if damage == "schema": payload["schema"] = "autoencoder-campaign-process-ready-v1"
    elif damage == "owner_boolean": payload["owner_pid"] = True
    elif damage == "group": payload["identity"]["group_pid"] += 1
    elif damage == "birth": payload["identity"]["birth"] += "1"
    elif damage == "request": payload["request_sha256"] = "0" * 64
    elif damage == "canonical_root": payload["canonical_root"] = "/different-tree"
    elif damage == "network": payload["network_guard"] = {}
    elif damage == "network_boolean": payload["network_guard"]["socket_denial_verified"] = 1
    elif damage == "extra": payload["admitted"] = True
    else: payload["identity"]["parent_pid"] = expected["owner_pid"]
    with pytest.raises(ValueError):
        module._trainer_ready(payload, **expected)


def test_trainer_start_is_once_only_and_durable_journal_detaches_payload(tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_operation_journal import DurableDaemonOperationJournal
    module, _ = _lifecycle_launcher_module()
    path = tmp_path / "controller-journal.json"
    binding = {"schema": "trainer-controller-unit-journal/v1", "request_sha256": "d" * 64}
    payload = {"request_sha256": "d" * 64, "mode": "native_probe", "owner": {"pid": 101, "birth": "201"}}
    with DurableDaemonOperationJournal(path, binding) as journal:
        module._trainer_record_start(journal, payload)
        saved = journal.get_metadata("start")
        payload["owner"]["birth"] = "mutated"
        assert journal.get_metadata("start") == saved and saved["owner"]["birth"] == "201"
        before = path.read_bytes()
        with pytest.raises(ValueError, match="recovery|retry"):
            module._trainer_record_start(journal, saved)
        assert path.read_bytes() == before
    with DurableDaemonOperationJournal(path, binding, create=False) as journal:
        assert journal.get_metadata("start") == saved
        with pytest.raises(ValueError, match="recovery|retry"):
            module._trainer_record_start(journal, saved)


@pytest.mark.parametrize("prior", ["start", "child", "release_intent", "released", "terminal"])
def test_trainer_prior_lifecycle_fact_never_authorizes_a_new_start(tmp_path, prior):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_operation_journal import DurableDaemonOperationJournal
    module, _ = _lifecycle_launcher_module()
    path = tmp_path / "controller-journal.json"
    binding = {"schema": "trainer-controller-unit-journal/v1", "request_sha256": "d" * 64}
    with DurableDaemonOperationJournal(path, binding) as journal:
        journal.set_metadata(prior, {"original_fact": True})
        before = path.read_bytes()
        with pytest.raises(ValueError, match="recovery|retry|lifecycle"):
            module._trainer_record_start(journal, {"new_fact": True})
        assert path.read_bytes() == before and journal.get_metadata(prior) == {"original_fact": True}


def test_trainer_journal_request_binding_conflict_keeps_original_bytes(tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_operation_journal import DurableDaemonOperationJournal, DaemonOperationJournalError
    path = tmp_path / "controller-journal.json"
    binding = {"schema": "trainer-controller-unit-journal/v1", "request_sha256": "d" * 64}
    with DurableDaemonOperationJournal(path, binding):
        pass
    before = path.read_bytes()
    with pytest.raises(DaemonOperationJournalError, match="binding differs"):
        with DurableDaemonOperationJournal(path, {**binding, "request_sha256": "e" * 64}, create=False):
            raise AssertionError("foreign journal was opened")
    assert path.read_bytes() == before


class _TrainerVirtualPipes:
    """In-memory FD contract for PURE tests; never opens a kernel pipe."""
    def __init__(self):
        self.next_fd = 9000
        self.handles = {}
        self.run_writes = []

    def _handle(self, channel, kind):
        self.next_fd += 1
        self.handles[self.next_fd] = (channel, kind)
        channel[kind] += 1
        return self.next_fd

    def pipe(self):
        channel = {"data": bytearray(), "read": 0, "write": 0}
        return self._handle(channel, "read"), self._handle(channel, "write")

    def duplicate(self, fd):
        channel, kind = self.handles[fd]
        return self._handle(channel, kind)

    def read(self, fd, size):
        channel, kind = self.handles[fd]
        assert kind == "read"
        if channel["data"]:
            raw = bytes(channel["data"][:size])
            del channel["data"][:size]
            return raw
        if channel["write"] == 0:
            return b""
        raise BlockingIOError()

    def write(self, fd, raw):
        channel, kind = self.handles[fd]
        assert kind == "write" and channel["read"] > 0
        channel["data"].extend(raw)
        if raw == b"RUN\n": self.run_writes.append(fd)
        return len(raw)

    def close(self, fd):
        channel, kind = self.handles.pop(fd)
        channel[kind] -= 1


@pytest.fixture
def trainer_supervisor_fake(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_operation_journal import DurableDaemonOperationJournal
    module, path, value = _trainer_controller_request_case(tmp_path)
    for directory in value["outputs"].values(): Path(directory).mkdir(mode=0o700)
    marker = tmp_path / "owned-controller-source.py"
    marker.write_text("unchanged = True\n")
    value["source_sha256"][str(marker)] = _sha(marker)
    _write_json(path, value)
    raw, pin = path.read_bytes(), _sha(path)
    journal = DurableDaemonOperationJournal(Path(value["outputs"]["logs"])/"controller-journal.json",
        {"schema": "trainer-controller-unit/v1", "request_sha256": pin})
    state = SimpleNamespace(module=module, path=path, value=value, raw=raw, pin=pin,
        journal=journal, pipes=_TrainerVirtualPipes(), events=[], clock=100.0, child=None,
        fail_heartbeat=None, heartbeat_count=0, usage_count=0, timeout_at_usage=False,
        mutate_at=None, journal_failure=None, bad_ready=None, cleanup_failure=False,
        residual_group=False, group_available=True, post_release_polls=1, sleep_step=.1,
        source_marker=marker)
    class Event:
        def __init__(self): self.flag = False; self.wait_count = 0
        def set(self): self.flag = True
        def is_set(self): return self.flag
        def wait(self, _seconds):
            self.wait_count += 1
            return self.flag or self.wait_count > 1
    class Thread:
        def __init__(self, *, target, **_kwargs): self.target=target; self.ident=None
        def start(self): self.ident=1; self.target()
        def join(self, timeout): assert timeout > 0
        def is_alive(self): return False
    owner_pid = os.getpid()
    owner_identity = {"pid": owner_pid, "birth": "1001", "parent_pid": os.getppid(), "group_pid": os.getpgrp()}
    class Owner:
        reservation_id = "1" * 32
        cancelled = False
        def heartbeat(self):
            state.heartbeat_count += 1
            return state.heartbeat_count != state.fail_heartbeat
        def check_usage(self, attempt, child_pid=None):
            assert attempt == Path(value["attempt_directory"]) and child_pid == 20123
            assert state.pipes.run_writes == [], "RUN preceded original attachment/census"
            state.usage_count += 1
            state.events.append("usage")
            if state.timeout_at_usage: state.clock += value["timeout_seconds"] + 1
    class Process:
        pid = 20123
        returncode = None
        live = True
        def __init__(self, argv, options):
            self.argv, self.options = argv, options
            assert journal.get_metadata("start") is not None
            assert journal.get_metadata("child") is None
            assert options["start_new_session"] is True and argv[1:4] == ["-I", "-S", "-B"]
            self.release = state.pipes.duplicate(int(argv[argv.index("--release-fd")+1]))
            self.channel = state.pipes.handles[self.release][0]
            ready_fd = int(argv[argv.index("--ready-fd")+1])
            payload = {"schema": "owned-f18-conditions-training-ready/v1",
                "identity": {"pid": self.pid, "group_pid": self.pid, "birth": "20124"},
                "owner_pid": owner_pid, "request_sha256": pin, "canonical_root": str(module.ROOT),
                "network_guard": {"mechanism": "linux_seccomp", "denied_syscalls": [
                    "socket", "connect", "sendto", "sendmsg", "sendmmsg"], "socket_denial_verified": True}}
            if state.bad_ready == "request": payload["request_sha256"] = "0" * 64
            state.pipes.write(ready_fd, json.dumps(payload).encode()+b"\n")
            state.events.append("spawn")
            self.released = False
        def poll(self):
            if not self.live: return self.returncode
            if not self.released:
                try: token=state.pipes.read(self.release, 4)
                except BlockingIOError: return None
                if not token: self.live=False; self.returncode=125; return self.returncode
                assert token == b"RUN\n"
                assert journal.get_metadata("release_intent") is not None
                self.released=True
                state.events.append("after_RUN")
            if state.post_release_polls:
                state.post_release_polls -= 1
                return None
            self.live=False; self.returncode=0
            return 0
        def wait(self, timeout):
            assert timeout > 0
            if self.returncode is None:
                self.poll()
            assert self.returncode is not None
            return self.returncode
    original_close, original_read, original_write, original_blocking = os.close, os.read, os.write, os.set_blocking
    monkeypatch.setattr(os, "pipe", state.pipes.pipe)
    monkeypatch.setattr(os, "close", lambda fd: state.pipes.close(fd) if fd in state.pipes.handles else original_close(fd))
    monkeypatch.setattr(os, "read", lambda fd,n: state.pipes.read(fd,n) if fd in state.pipes.handles else original_read(fd,n))
    monkeypatch.setattr(os, "write", lambda fd,b: state.pipes.write(fd,b) if fd in state.pipes.handles else original_write(fd,b))
    monkeypatch.setattr(os, "set_blocking", lambda fd,v: None if fd in state.pipes.handles else original_blocking(fd,v))
    def popen(argv, **options):
        state.child=Process(argv, options)
        return state.child
    def observed(pid):
        if pid == owner_pid: return dict(owner_identity)
        if state.child is not None and pid == state.child.pid and state.child.live:
            return {"pid":pid,"group_pid":pid,"birth":"20124","parent_pid":owner_pid}
        return None
    def group(identity):
        live = bool(identity and state.child is not None and (state.child.live or state.residual_group))
        return {"available":state.group_available,"live_processes":int(live),"rss_bytes":128 if live else 0}
    def stop(child, birth, owner=None):
        if child is None: return
        assert birth == "20124"
        assert child.channel["write"] > 0, "owner FD closed before original cleanup"
        state.events.append("cleanup")
        if state.cleanup_failure: raise RuntimeError("unconfirmed owned group")
        child.live=False
        if child.returncode is None: child.returncode=-15
        child.wait(timeout=1)
        if child.release in state.pipes.handles: state.pipes.close(child.release)
    original_set = journal.set_metadata
    def record(key, payload):
        if state.journal_failure == key: raise OSError("controlled journal failure")
        original_set(key,payload)
        state.events.append("journal:"+key)
        if state.mutate_at == key:
            if state.mutation == "request": path.write_bytes(raw+b" ")
            else: marker.write_text("unchanged = False\n")
    monkeypatch.setattr(journal, "set_metadata", record)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda:state.clock,
        sleep=lambda _seconds:setattr(state,"clock",state.clock+state.sleep_step)))
    import threading
    monkeypatch.setattr(module, "threading", SimpleNamespace(Event=Event,Thread=Thread,Lock=threading.Lock))
    monkeypatch.setattr(module, "subprocess", SimpleNamespace(Popen=popen,DEVNULL=subprocess.DEVNULL))
    monkeypatch.setattr(module, "stop_and_reap", stop)
    state.owner=Owner()
    state.host=SimpleNamespace(_process=observed,_group_usage=group)
    state.run=lambda: module._trainer_supervise(state.owner,journal,value,raw,
        request_path=path,request_pin=pin,host=state.host)
    yield state
    journal.close()
    state.pipes.handles.clear()


def test_trainer_supervision_journals_before_RUN_and_retains_owner_FD_through_reap(trainer_supervisor_fake):
    case=trainer_supervisor_fake
    result=case.run()
    assert result["completed"] is True and result["returncode"] == 0
    assert all(result["events"].values()) and result["process_cleanup_error"] is None
    assert result["group_observation"]["live_processes"] == 0
    assert case.events.index("journal:start") < case.events.index("spawn")
    assert case.events.index("journal:child") < case.events.index("journal:release_intent") < case.events.index("after_RUN")
    assert case.events.index("journal:released") < case.events.index("cleanup")
    assert len(case.pipes.run_writes) == 1 and case.pipes.handles == {}
    assert result["resource_scope"] == "isolated_process_group"
    assert all(result[key] is False for key in ("admitted","formalized","promoted"))


@pytest.mark.parametrize("mutation", ["request","source"])
def test_trainer_supervision_drift_at_child_journal_never_releases_RUN(trainer_supervisor_fake, mutation):
    case=trainer_supervisor_fake;case.mutate_at="child";case.mutation=mutation
    result=case.run()
    assert result["completed"] is False and result["events"]["ready_verified"] is True
    assert result["events"]["barrier_released"] is False and case.pipes.run_writes == []
    assert case.journal.get_metadata("released") is None
    assert result["group_observation"]["live_processes"] == 0


@pytest.mark.parametrize("boundary", ["start","child","release_intent","released"])
def test_trainer_supervision_journal_failure_never_becomes_a_retry(trainer_supervisor_fake, boundary):
    case=trainer_supervisor_fake;case.journal_failure=boundary
    result=case.run()
    assert result["completed"] is False and "journal" in result["error"]["error"]
    assert result["events"]["barrier_released"] is (boundary == "released")
    if boundary != "start":
        with pytest.raises(ValueError,match="recovery|retry"):
            case.module._trainer_record_start(case.journal,{"replacement":True})
    else:
        assert case.child is None and case.pipes.run_writes == []


def test_trainer_supervision_rechecks_deadline_after_gated_resource_census(trainer_supervisor_fake):
    case=trainer_supervisor_fake;case.timeout_at_usage=True
    result=case.run()
    assert result["completed"] is False and "deadline" in result["error"]["error"]
    assert not result["events"]["barrier_released"] and case.pipes.run_writes == []


@pytest.mark.parametrize("failure_at", [1,2])
def test_trainer_supervision_lost_native_heartbeat_never_releases_RUN(trainer_supervisor_fake,failure_at):
    case=trainer_supervisor_fake;case.fail_heartbeat=failure_at
    result=case.run()
    assert result["completed"] is False and "lease lost" in result["error"]["error"]
    assert case.pipes.run_writes == []


def test_trainer_supervision_bad_READY_never_reaches_productive_boundary(trainer_supervisor_fake):
    case=trainer_supervisor_fake;case.bad_ready="request"
    result=case.run()
    assert result["completed"] is False and not result["events"]["ready_verified"]
    assert case.pipes.run_writes == [] and "after_RUN" not in case.events


@pytest.mark.parametrize("uncertainty", ["cleanup","live_group","unavailable"])
def test_trainer_supervision_unknown_cleanup_is_not_success(trainer_supervisor_fake,uncertainty):
    case=trainer_supervisor_fake
    if uncertainty == "cleanup": case.cleanup_failure=True
    elif uncertainty == "live_group": case.residual_group=True
    else: case.group_available=False
    result=case.run()
    assert result["completed"] is False and result["process_cleanup_error"] is not None


def _trainer_terminal_case(tmp_path):
    module,path,value=_trainer_controller_request_case(tmp_path)
    raw=path.read_bytes();pin=_sha(path);pid=os.getpid();birth="123456"
    ledger=tmp_path/"ledger.json";ledger.write_text("{}\n")
    identity={"pid":20123,"group_pid":20123,"birth":"20124"}
    record={"reservation_id":"1"*32,"status":"released","owner_pid":pid,
        "scheduler_lane":"hammer_lean","workload":"canonical_trainer",
        "attempt_directory":{"path":value["attempt_directory"]},
        "child":{"pid":20123,"birth":"20124"},"prior_children":[],
        **{k:value[k] for k in ("cpu_slots","memory_mb","storage_bytes","child_process_slots")}}
    reservation={"reservation_id":record["reservation_id"],"record":record,
        "resource_lease":{"released":True,"lane":"hammer_lean","owner_pid":pid,"lease_id":"2"*32,"parent_lease_id":None,
                          **{k:value[k] for k in ("cpu_slots","memory_mb","child_process_slots")}},
        "scheduler_lane":"hammer_lean","workload":"canonical_trainer","ledger_path":str(ledger),"status":"released"}
    terminal={"schema":"owned-f18-conditions-training-terminal/v1","request_sha256":pin,
        "mode":"native_probe","completed":True,"resource_scope":"isolated_process_group",
        "resource_request_id":"daemon:"+record["reservation_id"],"owner":{"pid":pid,"birth":birth},
        "owner_open_returned":True,"owner_exit_handling_completed":True,"child_identity":identity,
        "group_observation":{"available":True,"live_processes":0,"rss_bytes":0},
        "events":{"child_launch_attempted":True,"child_created":True,"ready_verified":True,
                  "barrier_release_attempted":True,"barrier_released":True},
        "process_cleanup_error":None,"owner_exit_error":None,
        "source_guards":{"request_unchanged":True,"sources_unchanged":True},
        "scheduler":{"state_path":value["scheduler_state_path"],"policy_sha256":value["expected_scheduler_policy_sha256"],
                     "lane":"hammer_lean","workload":"canonical_trainer"},
        "reservation":reservation,"admitted":False,"Lean_admitted":False,"formalized":False,"promoted":False}
    caller=dict(expected_request_sha256=pin,owner_pid=pid,owner_birth=birth,returncode=0,expected_resource_ledger=str(ledger))
    return module,terminal,raw,caller


def test_trainer_typed_custody_closes_source_without_authorizing_storage_release(tmp_path):
    module,terminal,raw,caller=_trainer_terminal_case(tmp_path)
    expected={"verdict":"proven_original_trainer_native_and_source_closed","source_custody_closed":True,"storage_release_authorized":False}
    assert module.classify_owned_trainer_source_custody(terminal,raw,**caller) == expected
    terminal["completed"]=False;terminal["reservation"]["status"]="retained";terminal["reservation"]["record"]["status"]="retained"
    assert module.classify_owned_trainer_source_custody(terminal,raw,**{**caller,"returncode":1}) == expected


@pytest.mark.parametrize("damage", ['validation_purpose', 'borrowed_native_parent', 'native_not_released', 'live_group', 'cleanup', 'prior_child', 'unreported_child', 'missing_native', 'native_budget', 'native_boolean', 'boolean_child'])
def test_trainer_typed_custody_refuses_borrowed_malformed_or_unclosed_evidence(tmp_path,damage):
    module,t,raw,caller=_trainer_terminal_case(tmp_path);r=t["reservation"];record=r["record"];lease=r["resource_lease"]
    if damage == "validation_purpose": r["workload"]=record["workload"]="canonical_validation"
    elif damage == "borrowed_native_parent": lease["parent_lease_id"]="3"*32
    elif damage == "native_not_released": lease["released"]=False
    elif damage == "boolean_budget": record["cpu_slots"]=True
    elif damage == "request": t["request_sha256"]="0"*64
    elif damage == "owner_birth": t["owner"]["birth"]+="1"
    elif damage == "source_boolean": t["source_guards"]["sources_unchanged"]=1
    elif damage == "live_group": t["group_observation"]["live_processes"]=1
    elif damage == "RSS_boolean": t["group_observation"]["rss_bytes"]=False
    elif damage == "cleanup": t["process_cleanup_error"]="unconfirmed"
    elif damage == "owner_exit": t["owner_exit_error"]="unconfirmed"
    elif damage == "authority": t["admitted"]=True
    elif damage == "prior_child": record["prior_children"]=[{"pid":40123,"birth":"40124"}]
    elif damage == "unreported_child": t["child_identity"]=None;record["child"]=None
    elif damage == "missing_native": r["resource_lease"]=None
    elif damage == "completed_mismatch": t["completed"]=False
    elif damage == "native_budget": lease["memory_mb"] += 1
    elif damage == "native_boolean": lease["cpu_slots"] = True
    else: t["child_identity"]["pid"] = True; t["child_identity"]["group_pid"] = True; record["child"]["pid"] = True
    assert module.classify_owned_trainer_source_custody(t,raw,**caller) == {
        "verdict":"requires_original_trainer_cleanup","source_custody_closed":False,"storage_release_authorized":False}


def _trainer_child_fake_bootstrap_case(tmp_path, monkeypatch, *, stop_at_RUN):
    from types import SimpleNamespace
    module,path,value=_trainer_controller_request_case(tmp_path,paired=stop_at_RUN)
    for directory in value["outputs"].values(): Path(directory).mkdir(mode=0o700)
    events=[]
    guard={"mechanism":"linux_seccomp","denied_syscalls":["socket","connect","sendto","sendmsg","sendmmsg"],"socket_denial_verified":True}
    class BeforeRUN(BaseException): pass
    def wait(fd, *, timeout_seconds, owner_pid):
        assert fd == 7002 and 0 < timeout_seconds <= value["timeout_seconds"]
        events.append("wait_RUN")
        if stop_at_RUN: raise BeforeRUN()
    bootstrap=SimpleNamespace(_network_denial=lambda pin:events.append("network") or guard,
        _identity=lambda:{"pid":20123,"group_pid":20123,"birth":"20124"},
        _send_ready=lambda fd,payload:events.append("ready"),_await_release=wait,
        _watch_owner=lambda **kwargs:None,
        _configure_dependency_paths=lambda:(_ for _ in ()).throw(AssertionError("probe imported compute dependencies")))
    monkeypatch.setattr(module,"_trainer_bootstrap",lambda offered:bootstrap)
    monkeypatch.setattr(module,"sys",SimpleNamespace(flags=SimpleNamespace(isolated=True,no_site=True,dont_write_bytecode=True),modules={}))
    monkeypatch.setattr(module,"threading",SimpleNamespace(Thread=lambda **kwargs:SimpleNamespace(start=lambda:events.append("watch"))))
    genuine_close=os.close
    monkeypatch.setattr(os,"close",lambda fd:events.append("close_READY") if fd == 7001 else genuine_close(fd))
    monkeypatch.chdir(module.ROOT)
    return module,path,value,events,BeforeRUN


def test_trainer_child_waits_for_original_RUN_before_reference_access_or_dispatch(tmp_path,monkeypatch):
    module,path,value,events,BeforeRUN=_trainer_child_fake_bootstrap_case(tmp_path,monkeypatch,stop_at_RUN=True)
    attempted=_trainer_forbid_reference_bodies(monkeypatch,value)
    def premature_access(*_args, **_kwargs):
        raise AssertionError("bytecode-enabled child reached request or bootstrap access")
    with monkeypatch.context() as guard:
        guard.setattr(module.sys.flags,"dont_write_bytecode",False)
        guard.setenv("PYTHONDONTWRITEBYTECODE","1")
        guard.setattr(module,"trainer_request",premature_access)
        guard.setattr(module,"_trainer_bootstrap",premature_access)
        with pytest.raises(ValueError,match="bytecode-disabled"):
            module._trainer_child_main(path,_sha(path),ready_fd=7001,release_fd=7002,owner_pid=os.getppid())
    assert events == [] and attempted == []
    assert tuple(Path(value["outputs"]["exports"]).iterdir()) == ()
    with pytest.raises(BeforeRUN):
        module._trainer_child_main(path,_sha(path),ready_fd=7001,release_fd=7002,owner_pid=os.getppid())
    assert events == ["network","ready","close_READY","wait_RUN"]
    assert attempted == [] and tuple(Path(value["outputs"]["exports"]).iterdir()) == ()


def test_trainer_child_native_probe_after_RUN_has_exact_zero_compute_authority(tmp_path,monkeypatch):
    module,path,value,events,_=_trainer_child_fake_bootstrap_case(tmp_path,monkeypatch,stop_at_RUN=False)
    assert module._trainer_child_main(path,_sha(path),ready_fd=7001,release_fd=7002,owner_pid=os.getppid()) == 0
    report=_json(Path(value["outputs"]["exports"])/"trainer-result.json")
    assert events == ["network","ready","close_READY","wait_RUN","watch"]
    assert report["mode"] == "native_probe" and report["completed"] is True
    assert all(report[key] == 0 for key in ("model_constructions","checkpoint_payloads_opened","model_forwards","gradient_calls","optimizer_updates"))
    assert all(report[key] is False for key in ("admitted","formalized","promoted"))


# Separate controlled-OS cohort: never include test_trainer_native_* in PURE.
_TRAINER_NATIVE_HELPER_CHILD = r'''
import hashlib,importlib.util,json,os,stat,sys,threading,time
from pathlib import Path
bootstrap_path,bootstrap_sha,network_sha,ready_text,release_text,owner_text,marker_text,timeout_text=sys.argv[1:]
path=Path(bootstrap_path)
raw=path.read_bytes()
assert hashlib.sha256(raw).hexdigest()==bootstrap_sha
spec=importlib.util.spec_from_file_location("original_trainer_helper_under_OS_test",path)
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
assert Path(helper.__file__).resolve()==path
assert all(Path(getattr(helper,name).__code__.co_filename).resolve()==path for name in ("_send_ready","_await_release","_watch_owner","_identity"))
guard=helper._network_denial(network_sha)
identity=helper._identity();owner=int(owner_text);ready=int(ready_text);release=int(release_text)
assert identity["pid"]==identity["group_pid"] and os.getppid()==owner
helper._send_ready(ready,{"schema":"owned-f18-conditions-training-ready/v1","identity":identity,"owner_pid":owner,"request_sha256":bootstrap_sha,"canonical_root":str(helper.ROOT),"network_guard":guard})
os.close(ready)
try:
    helper._await_release(release,timeout_seconds=float(timeout_text),owner_pid=owner)
except BaseException as error:
    print(json.dumps({"productive_marker":False,"refusal":str(error)}),flush=True)
    raise SystemExit(2)
threading.Thread(target=helper._watch_owner,kwargs={"fd":release,"owner_pid":owner,"group_pid":identity["group_pid"]},daemon=True).start()
Path(marker_text).write_text("after original RUN\n")
while True: time.sleep(.05)
'''


def _trainer_native_start(tmp_path):
    import select
    module,_=_lifecycle_launcher_module()
    bootstrap=module.ROOT/"ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_campaign_process_worker.py"
    network=module.ROOT/"ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_invocation_worker.py"
    ready_read,ready_write=os.pipe();release_read,release_write=os.pipe()
    marker=tmp_path/"productive-marker"
    child=None;identity=None
    try:
        child=subprocess.Popen([sys.executable,"-I","-S","-c",_TRAINER_NATIVE_HELPER_CHILD,
            str(bootstrap),_sha(bootstrap),_sha(network),str(ready_write),str(release_read),str(os.getpid()),str(marker),".35"],
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            start_new_session=True,close_fds=True,pass_fds=(ready_write,release_read))
        observed=native_disk._process(child.pid)
        assert observed is not None and observed["parent_pid"]==os.getpid() and observed["group_pid"]==child.pid
        identity={"pid":child.pid,"birth":observed["birth"]}
        os.close(ready_write);ready_write=None
        os.close(release_read);release_read=None
        raw=b"";deadline=time.monotonic()+.8
        while b"\n" not in raw:
            remaining=deadline-time.monotonic()
            assert remaining>0,"original helper did not become READY within declared bound"
            readable,_,_=select.select([ready_read],[],[],remaining)
            assert readable
            piece=os.read(ready_read,8193-len(raw));assert piece
            raw+=piece;assert len(raw)<=8192
        assert raw.count(b"\n")==1 and raw.endswith(b"\n")
        payload=json.loads(raw)
        module._trainer_ready(payload,identity={"pid":child.pid,"group_pid":child.pid,"birth":identity["birth"]},
            owner_pid=os.getpid(),request_pin=_sha(bootstrap))
        assert not marker.exists() and child.poll() is None
        return dict(child=child,identity=identity,ready_read=ready_read,release_write=release_write,marker=marker)
    except BaseException:
        for fd in (ready_read,ready_write,release_read,release_write):
            if fd is not None:
                try: os.close(fd)
                except OSError: pass
        if child is not None:
            if identity is not None and native_disk._group_usage(identity)["live_processes"]:
                os.killpg(child.pid,signal.SIGKILL)
            child.wait(timeout=.8)
        raise


def _trainer_native_cleanup(case):
    for field in ("ready_read","release_write"):
        fd=case.get(field)
        if fd is not None:
            os.close(fd);case[field]=None
    child,identity=case["child"],case["identity"]
    usage=native_disk._group_usage(identity)
    if usage["live_processes"]:
        # Original helper checks the recorded birth before this owned-group signal.
        again=native_disk._group_usage(identity)
        if again["live_processes"]: os.killpg(identity["pid"],signal.SIGKILL)
    child.communicate(timeout=.8)
    assert native_disk._group_usage(identity)["live_processes"] == 0


def test_trainer_native_RUN_gate_and_retained_EOF_stop_only_owned_group(tmp_path):
    case=_trainer_native_start(tmp_path)
    try:
        assert not case["marker"].exists()
        os.write(case["release_write"],b"RUN\n")
        _wait_for(case["marker"].exists,"no productive marker after original RUN",timeout=.8)
        os.close(case["release_write"]);case["release_write"]=None
        assert case["child"].wait(timeout=.8) != 0
        assert native_disk._group_usage(case["identity"])["live_processes"] == 0
    finally:
        _trainer_native_cleanup(case)




def test_trainer_native_bad_RUN_token_refuses_all_work(tmp_path):
    case=_trainer_native_start(tmp_path)
    try:
        os.write(case["release_write"],b"BAD\n")
        stdout,_=case["child"].communicate(timeout=.8)
        assert case["child"].returncode==2 and b"invalid compute release token" in stdout
        assert not case["marker"].exists()
    finally:
        _trainer_native_cleanup(case)


def test_trainer_native_release_deadline_refuses_work_without_rearm(tmp_path):
    case=_trainer_native_start(tmp_path)
    try:
        stdout,_=case["child"].communicate(timeout=.8)
        assert case["child"].returncode==2 and b"compute release deadline expired" in stdout
        assert not case["marker"].exists()
    finally:
        _trainer_native_cleanup(case)


def test_trainer_supervision_cancelled_owner_never_spawns_or_releases_RUN(trainer_supervisor_fake):
    case=trainer_supervisor_fake;case.owner.cancelled=True
    result=case.run()
    assert result["completed"] is False and "cancelled" in result["error"]["error"]
    assert case.child is None and case.pipes.run_writes == []
    assert case.journal.get_metadata("start") is None


# Explicit v2 controller controls are lexical/fake only; no retained TRAIN work.
def _v2_trainer_controller_case(tmp_path):
    module, path, value = _trainer_controller_request_case(tmp_path, paired=True)
    value["schema"] = "owned-f18-conditions-training-request/v2"
    value["compute"]["learning_rate"] = 0.003  # authored metadata, no experiment selection
    directory = module.ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer"
    for name in ("legal_span_conditions_fullspan_training_v2.py",
                 "legal_span_conditions_fullspan_optimizer_recipe_v1.py"):
        value["source_sha256"][str(directory / name)] = _sha(directory / name)
    _write_json(path, value)
    return module, path, value


def test_v2_trainer_request_is_explicit_lexical_and_detached(tmp_path, monkeypatch):
    module, path, value = _v2_trainer_controller_case(tmp_path)
    attempts = _trainer_forbid_reference_bodies(monkeypatch, value)
    parsed, raw = module.trainer_request(path, _sha(path))
    module._trainer_source_guard(parsed)
    assert parsed == value and parsed is not value and raw
    parsed["compute"]["learning_rate"] = 0.007
    assert value["compute"]["learning_rate"] == 0.003
    assert attempts == [] and not Path(value["scheduler_state_path"]).exists()
    assert tuple(Path(value["attempt_directory"]).iterdir()) == ()


@pytest.mark.parametrize("damage", ["missing_rate", "boolean_rate", "false_rate", "zero_rate",
    "negative_rate", "nan_rate", "positive_inf", "negative_inf", "string_rate", "null_rate",
    "huge_integer", "unknown_field", "v1_with_rate", "foreign_schema"])
def test_v2_trainer_request_refuses_invalid_rate_or_version_without_payload_access(tmp_path, monkeypatch, damage):
    module, _, value = _v2_trainer_controller_case(tmp_path)
    attempts = _trainer_forbid_reference_bodies(monkeypatch, value)
    rates = {"boolean_rate": True, "false_rate": False, "zero_rate": 0.0, "negative_rate": -0.001,
        "nan_rate": float("nan"), "positive_inf": float("inf"), "negative_inf": -float("inf"),
        "string_rate": "0.003", "null_rate": None, "huge_integer": 10 ** 400}
    if damage == "missing_rate": value["compute"].pop("learning_rate")
    elif damage in rates: value["compute"]["learning_rate"] = rates[damage]
    elif damage == "unknown_field": value["compute"]["admitted"] = True
    elif damage == "v1_with_rate": value["schema"] = "owned-f18-conditions-training-request/v1"
    else: value["schema"] = "owned-f18-conditions-training-request/v3"
    with pytest.raises(ValueError):
        module._validate_trainer_request(value)
    assert attempts == [] and tuple(Path(value["attempt_directory"]).iterdir()) == ()


@pytest.mark.parametrize("missing", ["legal_span_conditions_fullspan_training_v2.py",
                                   "legal_span_conditions_fullspan_optimizer_recipe_v1.py"])
def test_v2_trainer_source_guard_requires_each_explicit_numerical_owner(tmp_path, missing):
    module, _, value = _v2_trainer_controller_case(tmp_path)
    directory = module.ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer"
    value["source_sha256"].pop(str(directory / missing))
    with pytest.raises(ValueError, match="explicit v2 numerical and recipe"):
        module._trainer_source_guard(value)
    assert tuple(Path(value["attempt_directory"]).iterdir()) == ()


def test_v2_native_probe_keeps_compute_empty_and_validation_schema_unchanged(tmp_path):
    module, _, value = _v2_trainer_controller_case(tmp_path)
    value.update(mode="native_probe", compute=None)
    parsed = module._validate_trainer_request(value)
    assert parsed["compute"] is None
    value["compute"] = {"learning_rate": 0.003}
    with pytest.raises(ValueError, match="native probe permits no payload"):
        module._validate_trainer_request(value)
    with pytest.raises(ValueError):
        module._validate_trainer_request({"schema": "owned-validation-request/v2"})



def test_v2_trainer_child_preserves_original_RUN_barrier_before_all_reference_access(tmp_path, monkeypatch):
    module, path, value, events, BeforeRUN = _trainer_child_fake_bootstrap_case(
        tmp_path, monkeypatch, stop_at_RUN=True)
    module.sys.float_info = sys.float_info
    value["schema"] = "owned-f18-conditions-training-request/v2"
    value["compute"]["learning_rate"] = 0.003
    directory = module.ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer"
    for name in ("legal_span_conditions_fullspan_training_v2.py",
                 "legal_span_conditions_fullspan_optimizer_recipe_v1.py"):
        value["source_sha256"][str(directory / name)] = _sha(directory / name)
    _write_json(path, value)
    attempts = _trainer_forbid_reference_bodies(monkeypatch, value)
    with pytest.raises(BeforeRUN):
        module._trainer_child_main(path, _sha(path), ready_fd=7001, release_fd=7002, owner_pid=os.getppid())
    assert events == ["network", "ready", "close_READY", "wait_RUN"] and attempts == []
    assert tuple(Path(value["outputs"]["exports"]).iterdir()) == ()


def test_v2_probe_after_RUN_keeps_original_zero_compute_result_and_lifecycle(tmp_path, monkeypatch):
    module, path, value, events, _ = _trainer_child_fake_bootstrap_case(
        tmp_path, monkeypatch, stop_at_RUN=False)
    value["schema"] = "owned-f18-conditions-training-request/v2"
    _write_json(path, value)
    assert module._trainer_child_main(path, _sha(path), ready_fd=7001, release_fd=7002, owner_pid=os.getppid()) == 0
    report = _json(Path(value["outputs"]["exports"]) / "trainer-result.json")
    assert events == ["network", "ready", "close_READY", "wait_RUN", "watch"]
    assert report["schema"] == "f18-native-trainer-probe-result/v1"
    assert module.TRAINER_READY_SCHEMA.endswith("/v1") and module.TRAINER_TERMINAL_SCHEMA.endswith("/v1")
    assert all(report[key] == 0 for key in (
        "model_constructions", "checkpoint_payloads_opened", "model_forwards", "gradient_calls", "optimizer_updates"))
    assert all(report[key] is False for key in ("admitted", "formalized", "promoted"))



def _trainer_preentry_inventory_refusal_case(tmp_path):
    """Authored source-close evidence only; no native reservation is created."""
    module, terminal, raw, caller = _trainer_terminal_case(tmp_path)
    value = json.loads(raw)
    reservation = terminal["reservation"]
    roots = [{"path": path, "device": 1, "inode": i+1} for i, path in enumerate(value["roots"])]
    reservation.update(status="not_entered", record=None, resource_lease=None, cleanup_error=None,
        schema="daemon-resource-reservations-v1", roots=roots, storage_limit_bytes=native_disk.MAX_STORAGE_BYTES)
    terminal.update(completed=False, owner_open_returned=False, child_identity=None, events={},
        error={"error_type": "DaemonResourceError", "error": "storage inventory entry bound exceeded"})
    _write_json(Path(caller["expected_resource_ledger"]), {"schema": "daemon-resource-reservations-v1",
        "reservations": {}, "roots": roots, "limit_bytes": native_disk.MAX_STORAGE_BYTES})
    policy = {"proof_safety_enabled": True, "authored_policy_only": True}
    value["expected_scheduler_policy_sha256"] = existing.policy_sha256(policy)
    raw = json.dumps(value).encode(); caller["expected_request_sha256"] = hashlib.sha256(raw).hexdigest()
    terminal["request_sha256"] = caller["expected_request_sha256"]
    terminal["scheduler"]["policy_sha256"] = value["expected_scheduler_policy_sha256"]
    _write_json(Path(value["scheduler_state_path"]), {"config": policy,
        "schema_version": native.RESOURCE_SCHEDULER_SCHEMA_VERSION, "next_sequence": 1,
        "leases": {}, "waiters": {}, "metrics": {}})
    caller["returncode"] = 1
    return module, terminal, raw, caller


@pytest.mark.parametrize("version", [1, 2])
def test_trainer_preentry_inventory_refusal_closes_source_without_grant_retry_or_storage_permission(tmp_path, version):
    module, terminal, raw, caller = _trainer_preentry_inventory_refusal_case(tmp_path)
    if version == 2:
        value = json.loads(raw); value["schema"] = "owned-f18-conditions-training-request/v2"
        raw = json.dumps(value).encode(); caller["expected_request_sha256"] = hashlib.sha256(raw).hexdigest()
        terminal["request_sha256"] = caller["expected_request_sha256"]
    ledger = Path(caller["expected_resource_ledger"])
    scheduler = Path(json.loads(raw)["scheduler_state_path"])
    before = (ledger.read_bytes(), scheduler.read_bytes(), deepcopy(terminal))
    assert module.classify_owned_trainer_source_custody(terminal, raw, **caller) == {
        "verdict": "proven_original_trainer_preentry_inventory_refusal_source_closed",
        "source_custody_closed": True, "storage_release_authorized": False}
    assert before == (ledger.read_bytes(), scheduler.read_bytes(), terminal)


@pytest.mark.parametrize("damage", ["opened_boolean", "opened_true", "record", "native_lease", "status",
    "cleanup", "unrecognized_error", "error_type", "child", "launch_event", "live_group", "rss_boolean",
    "exit_incomplete", "source_guard", "completed", "returncode", "reservation_id", "request_id",
    "wrong_purpose", "wrong_ledger", "wrong_scheduler", "durable_record", "durable_native_request",
    "durable_schema", "durable_roots", "durable_limit", "changed_backend_pin"])
def test_trainer_preentry_inventory_refusal_rejects_partial_or_conflicting_evidence(tmp_path, damage):
    module, t, raw, caller = _trainer_preentry_inventory_refusal_case(tmp_path)
    r = t["reservation"]
    ledger = Path(caller["expected_resource_ledger"])
    scheduler = Path(json.loads(raw)["scheduler_state_path"])
    if damage == "opened_boolean": t["owner_open_returned"] = 0
    elif damage == "opened_true": t["owner_open_returned"] = True
    elif damage == "record": r["record"] = {"reservation_id": r["reservation_id"]}
    elif damage == "native_lease": r["resource_lease"] = {"released": False}
    elif damage == "status": r["status"] = "retained"
    elif damage == "cleanup": r["cleanup_error"] = "unknown"
    elif damage == "unrecognized_error": t["error"]["error"] = "later native acquisition failure"
    elif damage == "error_type": t["error"]["error_type"] = "ValueError"
    elif damage == "child": t["child_identity"] = {"pid": 123, "birth": "456"}
    elif damage == "launch_event": t["events"]["child_launch_attempted"] = True
    elif damage == "live_group": t["group_observation"]["live_processes"] = 1
    elif damage == "rss_boolean": t["group_observation"]["rss_bytes"] = False
    elif damage == "exit_incomplete": t["owner_exit_handling_completed"] = False
    elif damage == "source_guard": t["source_guards"]["sources_unchanged"] = False
    elif damage == "completed": t["completed"] = True
    elif damage == "returncode": caller["returncode"] = 0
    elif damage == "reservation_id": r["reservation_id"] = "Z" * 32
    elif damage == "request_id": t["resource_request_id"] = "daemon:" + "3" * 32
    elif damage == "wrong_purpose": r["workload"] = "canonical_validation"
    elif damage == "wrong_ledger": r["ledger_path"] = str(tmp_path / "foreign-ledger")
    elif damage == "wrong_scheduler": t["scheduler"]["lane"] = "validation"
    elif damage == "durable_record":
        body = _json(ledger); body["reservations"][r["reservation_id"]] = {}; _write_json(ledger, body)
    elif damage == "durable_native_request": _write_json(scheduler, {"request": "daemon:" + r["reservation_id"]})
    elif damage == "durable_schema":
        body = _json(ledger); body["schema"] = "unrecognized"; _write_json(ledger, body)
    elif damage == "durable_roots":
        body = _json(ledger); body["roots"][0]["inode"] += 1; _write_json(ledger, body)
    elif damage == "durable_limit":
        body = _json(ledger); body["limit_bytes"] += 1; _write_json(ledger, body)
    else:
        value = json.loads(raw)
        directory = module.ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer"
        value["source_sha256"][str(directory / "autoencoder_daemon_resources.py")] = "f" * 64
        raw = json.dumps(value).encode(); caller["expected_request_sha256"] = hashlib.sha256(raw).hexdigest()
        t["request_sha256"] = caller["expected_request_sha256"]
    assert module.classify_owned_trainer_source_custody(t, raw, **caller) == {
        "verdict": "requires_original_trainer_cleanup", "source_custody_closed": False,
        "storage_release_authorized": False}



@pytest.mark.parametrize("damage", ["empty_state", "wrong_schema", "boolean_sequence", "missing_waiters",
    "invalid_lease", "wrong_policy", "proof_disabled", "escaped_value_id", "escaped_key_id"])
def test_trainer_preentry_recovery_uses_original_typed_reader_and_decoded_native_id_refusal(tmp_path, monkeypatch, damage):
    module, t, raw, caller = _trainer_preentry_inventory_refusal_case(tmp_path)
    path = Path(json.loads(raw)["scheduler_state_path"])
    state = _json(path)
    rid = t["reservation"]["reservation_id"]
    if damage == "empty_state": state = {}
    elif damage == "wrong_schema": state["schema_version"] = "unrecognized"
    elif damage == "boolean_sequence": state["next_sequence"] = True
    elif damage == "missing_waiters": state.pop("waiters")
    elif damage == "invalid_lease": state["leases"]["authored-lease"] = {}
    elif damage == "wrong_policy": state["config"]["authored_policy_only"] = False
    elif damage == "proof_disabled":
        state["config"]["proof_safety_enabled"] = False
        value = json.loads(raw); value["expected_scheduler_policy_sha256"] = existing.policy_sha256(state["config"])
        raw = json.dumps(value).encode(); caller["expected_request_sha256"] = hashlib.sha256(raw).hexdigest()
        t["request_sha256"] = caller["expected_request_sha256"]
        t["scheduler"]["policy_sha256"] = value["expected_scheduler_policy_sha256"]
    elif damage == "escaped_value_id": state["metrics"]["request"] = "daemon:" + rid
    else: state["metrics"]["daemon:" + rid] = "observed"
    encoded = json.dumps(state)
    if damage.startswith("escaped_"):
        encoded = encoded.replace(rid, "\\u0031" * 32)
        assert rid not in encoded and rid in json.dumps(json.loads(encoded))
    path.write_text(encoded)
    monkeypatch.setattr(existing, "open_existing_scheduler", lambda *a, **k: pytest.fail("opened scheduler facade"))
    monkeypatch.setattr(native, "GlobalResourceScheduler", lambda *a, **k: pytest.fail("constructed scheduler"))
    before = path.read_bytes()
    assert module.classify_owned_trainer_source_custody(t, raw, **caller) == {
        "verdict": "requires_original_trainer_cleanup", "source_custody_closed": False,
        "storage_release_authorized": False}
    assert path.read_bytes() == before


@pytest.mark.parametrize("damage", ["missing_cleanup", "ledger_extra", "wrong_record_key", "embedded_identity",
    "invalid_status", "boolean_storage", "boolean_owner", "invalid_charges"])
def test_trainer_preentry_recovery_refuses_incomplete_or_conflicting_original_ledger(tmp_path, damage):
    module, t, raw, caller = _trainer_preentry_inventory_refusal_case(tmp_path)
    path = Path(caller["expected_resource_ledger"])
    ledger = _json(path)
    rid = t["reservation"]["reservation_id"]
    key = "4" * 32
    record = {"reservation_id": key, "status": "released", "storage_bytes": 1, "owner_pid": 123}
    if damage == "missing_cleanup": t["reservation"].pop("cleanup_error")
    elif damage == "ledger_extra": ledger["unrecognized"] = True
    else:
        if damage == "wrong_record_key": record["reservation_id"] = rid
        elif damage == "embedded_identity": record["observed_identity"] = "daemon:" + rid
        elif damage == "invalid_status": record["status"] = "not_entered"
        elif damage == "boolean_storage": record["storage_bytes"] = True
        elif damage == "boolean_owner": record["owner_pid"] = True
        else: record["external_charges"] = {"authored": True}
        ledger["reservations"][key] = record
    _write_json(path, ledger)
    assert module.classify_owned_trainer_source_custody(t, raw, **caller) == {
        "verdict": "requires_original_trainer_cleanup", "source_custody_closed": False,
        "storage_release_authorized": False}


# Pure lexical/fake-dispatch controls; actual numerical execution is separate.
def _numerical_probe_controller_case(tmp_path):
    module, path, value = _v2_trainer_controller_case(tmp_path)
    value["mode"] = "numerical_probe"
    value["compute"] = {name: {"path": str(tmp_path / (name + ".json")), "bytes": 17, "sha256": "b" * 64}
        for name in ("runtime_contract", "synthetic_fixture")}
    _write_json(path, value)
    return module, path, value


def test_numerical_probe_parser_is_detached_and_opens_no_input(tmp_path, monkeypatch):
    module, path, value = _numerical_probe_controller_case(tmp_path)
    attempted = _trainer_forbid_reference_bodies(monkeypatch, value)
    parsed, raw = module.trainer_request(path, _sha(path))
    module._trainer_source_guard(parsed)
    assert parsed == value and parsed is not value and raw == path.read_bytes()
    parsed["compute"]["synthetic_fixture"]["bytes"] = 123
    assert value["compute"]["synthetic_fixture"]["bytes"] == 17
    assert attempted == [] and tuple(Path(value["attempt_directory"]).iterdir()) == ()


@pytest.mark.parametrize("damage", ["v1", "null", "extra_rate", "retained_inputs", "missing_runtime",
    "missing_fixture", "boolean_bytes", "empty_bytes", "runtime_over_bound", "fixture_over_bound",
    "bad_digest", "relative_path", "alias_refs", "input_in_attempt", "source_pin_alias", "extra_ref_field"])
def test_numerical_probe_refuses_scope_expansion_before_access(tmp_path, monkeypatch, damage):
    module, _, value = _numerical_probe_controller_case(tmp_path)
    attempted = _trainer_forbid_reference_bodies(monkeypatch, value)
    compute = value["compute"]
    if damage == "v1": value["schema"] = "owned-f18-conditions-training-request/v1"
    elif damage == "null": value["compute"] = None
    elif damage == "extra_rate": compute["learning_rate"] = 0.004
    elif damage == "retained_inputs": compute["input_descriptors"] = compute["synthetic_fixture"].copy()
    elif damage == "missing_runtime": compute.pop("runtime_contract")
    elif damage == "missing_fixture": compute.pop("synthetic_fixture")
    elif damage == "boolean_bytes": compute["synthetic_fixture"]["bytes"] = True
    elif damage == "empty_bytes": compute["synthetic_fixture"]["bytes"] = 0
    elif damage == "runtime_over_bound": compute["runtime_contract"]["bytes"] = 131073
    elif damage == "fixture_over_bound": compute["synthetic_fixture"]["bytes"] = 2097153
    elif damage == "bad_digest": compute["synthetic_fixture"]["sha256"] = "g" * 64
    elif damage == "relative_path": compute["synthetic_fixture"]["path"] = "relative.json"
    elif damage == "alias_refs": compute["synthetic_fixture"]["path"] = compute["runtime_contract"]["path"]
    elif damage == "input_in_attempt": compute["synthetic_fixture"]["path"] = str(Path(value["outputs"]["exports"]) / "input.json")
    elif damage == "source_pin_alias": value["source_sha256"][compute["synthetic_fixture"]["path"]] = "b" * 64
    else: compute["synthetic_fixture"]["gold"] = True
    with pytest.raises(ValueError): module._validate_trainer_request(value)
    assert attempted == [] and tuple(Path(value["attempt_directory"]).iterdir()) == ()


@pytest.mark.parametrize("missing", ["legal_span_conditions_fullspan_training_v2.py",
    "legal_span_conditions_fullspan_optimizer_recipe_v1.py"])
def test_numerical_probe_requires_explicit_v2_source_pins(tmp_path, missing):
    module, _, value = _numerical_probe_controller_case(tmp_path)
    directory = module.ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer"
    value["source_sha256"].pop(str(directory / missing))
    with pytest.raises(ValueError, match="explicit v2 numerical and recipe"): module._trainer_source_guard(value)


def _numerical_probe_child_case(tmp_path, monkeypatch, stop):
    module, path, value, events, before = _trainer_child_fake_bootstrap_case(tmp_path, monkeypatch, stop_at_RUN=stop)
    value["schema"] = "owned-f18-conditions-training-request/v2"
    value["mode"] = "numerical_probe"
    value["compute"] = {name: {"path": str(tmp_path / (name + ".json")), "bytes": 17, "sha256": "b" * 64}
        for name in ("runtime_contract", "synthetic_fixture")}
    directory = module.ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer"
    for name in ("legal_span_conditions_fullspan_training_v2.py", "legal_span_conditions_fullspan_optimizer_recipe_v1.py"):
        value["source_sha256"][str(directory / name)] = _sha(directory / name)
    _write_json(path, value)
    return module, path, value, events, before


def test_numerical_probe_preserves_RUN_barrier_before_dependencies_or_inputs(tmp_path, monkeypatch):
    module, path, value, events, BeforeRUN = _numerical_probe_child_case(tmp_path, monkeypatch, True)
    attempted = _trainer_forbid_reference_bodies(monkeypatch, value)
    with pytest.raises(BeforeRUN):
        module._trainer_child_main(path, _sha(path), ready_fd=7001, release_fd=7002, owner_pid=os.getppid())
    assert events == ["network", "ready", "close_READY", "wait_RUN"] and attempted == []
    assert tuple(Path(value["outputs"]["exports"]).iterdir()) == ()


@pytest.mark.parametrize("outcome", ["complete", "incomplete", "authority"])
def test_numerical_probe_after_RUN_dispatch_and_terminal_guards(tmp_path, monkeypatch, outcome):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_invocation_worker as worker
    module, path, value, events, _ = _numerical_probe_child_case(tmp_path, monkeypatch, False)
    module._trainer_bootstrap(value)._configure_dependency_paths = lambda: events.append("dependencies")
    def dispatch(offered, *, output_directory):
        assert events[-3:] == ["wait_RUN", "watch", "dependencies"]
        assert offered == value and output_directory == Path(value["outputs"]["exports"])
        events.append("numerical_dispatch")
        return {"completed": outcome != "incomplete", "admitted": outcome == "authority", "formalized": False, "promoted": False}
    monkeypatch.setattr(worker, "run_f18_numerical_probe", dispatch)
    if outcome == "authority":
        with pytest.raises(ValueError, match="result/authority"):
            module._trainer_child_main(path, _sha(path), ready_fd=7001, release_fd=7002, owner_pid=os.getppid())
        assert not (Path(value["outputs"]["exports"]) / "trainer-result.json").exists()
    else:
        rc = module._trainer_child_main(path, _sha(path), ready_fd=7001, release_fd=7002, owner_pid=os.getppid())
        assert rc == (0 if outcome == "complete" else 4)
        assert _json(Path(value["outputs"]["exports"]) / "trainer-result.json")["completed"] is (outcome == "complete")
    assert events == ["network", "ready", "close_READY", "wait_RUN", "watch", "dependencies", "numerical_dispatch"]


def test_numerical_probe_refuses_reference_to_its_request_before_bootstrap(tmp_path):
    module, path, value = _numerical_probe_controller_case(tmp_path)
    value["compute"]["synthetic_fixture"]["path"] = str(path)
    _write_json(path, value)
    with pytest.raises(ValueError, match="separate from the trainer request"):
        module.trainer_request(path, _sha(path))
    assert tuple(Path(value["attempt_directory"]).iterdir()) == ()


def _physical_core_entry(kind="symlink", path="alias", target="original.bin", target_kind="file"):
    return {"path": path, "kind": kind,
            "target": None if kind == "fifo" else target,
            "target_kind": None if kind == "fifo" else target_kind}


def _physical_core_prepare(control, *, mutate=None, entries=None):
    # This real private child explicitly consumes the frozen transport tokens.
    # Production launcher/pytest sources are never replaced or bypassed.
    marker = "mode, attempt_text, request_digest, checks_json = sys.argv[1:]"
    replacement = (
        "physical_args = sys.argv[1:]\n"
        "assert physical_args[-3:] == ['--owned-physical-fixtures', '-p', "
        "'ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_pytest']\n"
        "mode, attempt_text, request_digest, checks_json = physical_args[:-3]")
    assert CHILD_SOURCE.count(marker) == 1
    control["source"].write_text(CHILD_SOURCE.replace(marker, replacement))
    def physical(request):
        request["schema"] = "owned-validation-request/v2"
        request["argv"].extend(["--owned-physical-fixtures", "-p",
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_pytest"])
        request["physical_fixture_profile"] = {
            "schema": "owned-validation-physical-fixtures/v1",
            "root": str(Path(request["attempt_directory"]) / "tmp" / "physical-fixtures"),
            "cases": [{"nodeid": request["selected_checks"][0],
                       "entries": deepcopy(entries if entries is not None else [
                           _physical_core_entry(), _physical_core_entry("fifo", path="pipe")])}],
        }
        if mutate is not None:
            mutate(request)
    return control["prepare"](mutate=physical)


def _physical_core_case(request):
    profile = request["physical_fixture_profile"]
    return Path(profile["root"]) / hashlib.sha256(
        profile["cases"][0]["nodeid"].encode("utf-8")).hexdigest()


def _physical_core_remove_leaf(path, identity, kind):
    """Remove only this test's exact authored alias/FIFO, never its target."""
    current = path.lstat()
    expected_type = stat.S_IFLNK if kind == "symlink" else stat.S_IFIFO
    assert (current.st_dev, current.st_ino, stat.S_IFMT(current.st_mode)) == (
        identity.st_dev, identity.st_ino, expected_type)
    path.unlink()


@pytest.mark.parametrize("fault", [
    "wrong_request_schema", "missing_profile", "extra_profile_field", "wrong_profile_schema",
    "wrong_root", "empty_cases", "duplicate_case", "unselected_case", "extra_case_field",
    "empty_entries", "five_entries", "extra_entry_field", "absolute_path", "parent_path",
    "dot_path", "backslash_path", "nine_path_parts", "long_path", "duplicate_entry",
    "unknown_kind", "fifo_target", "fifo_target_kind", "missing_symlink_target",
    "missing_target_kind", "self_target", "absolute_target", "parent_target", "33_cases",
    "missing_transport_flag", "duplicate_transport_flag", "missing_plugin_pair", "wrong_plugin_pair",
])
def test_physical_fixture_profile_closed_shape_refuses_before_admission(private_control, fault):
    c = private_control
    def mutate(request):
        profile = request["physical_fixture_profile"]
        row, entry = profile["cases"][0], profile["cases"][0]["entries"][0]
        if fault == "wrong_request_schema": request["schema"] = "owned-validation-request/v1"
        elif fault == "missing_profile": del request["physical_fixture_profile"]
        elif fault == "extra_profile_field": profile["allow_anything"] = True
        elif fault == "wrong_profile_schema": profile["schema"] = "owned-validation-physical-fixtures/v2"
        elif fault == "wrong_root": profile["root"] = str(Path(request["attempt_directory"]) / "pytest")
        elif fault == "empty_cases": profile["cases"] = []
        elif fault == "duplicate_case": profile["cases"].append(deepcopy(row))
        elif fault == "unselected_case": row["nodeid"] = "a different check"
        elif fault == "extra_case_field": row["unbounded"] = True
        elif fault == "empty_entries": row["entries"] = []
        elif fault == "five_entries":
            row["entries"] = [_physical_core_entry("fifo", path="pipe-" + str(i)) for i in range(5)]
        elif fault == "extra_entry_field": entry["may_follow"] = True
        elif fault == "absolute_path": entry["path"] = "/alias"
        elif fault == "parent_path": entry["path"] = "nested/../alias"
        elif fault == "dot_path": entry["path"] = "nested/./alias"
        elif fault == "backslash_path": entry["path"] = "nested\\alias"
        elif fault == "nine_path_parts": entry["path"] = "/".join(["a"] * 9)
        elif fault == "long_path": entry["path"] = "a" * 257
        elif fault == "duplicate_entry": row["entries"].append(deepcopy(entry))
        elif fault == "unknown_kind": entry["kind"] = "socket"
        elif fault == "fifo_target":
            row["entries"][1]["target"] = "original.bin"
        elif fault == "fifo_target_kind": row["entries"][1]["target_kind"] = "file"
        elif fault == "missing_symlink_target": entry["target"] = None
        elif fault == "missing_target_kind": entry["target_kind"] = None
        elif fault == "self_target": entry["target"] = entry["path"]
        elif fault == "absolute_target": entry["target"] = "/original.bin"
        elif fault == "parent_target": entry["target"] = "../original.bin"
        elif fault == "33_cases":
            request["selected_checks"] = ["check-" + str(i) for i in range(33)]
            profile["cases"] = [{"nodeid": node, "entries": [_physical_core_entry("fifo", path="pipe")]}
                                for node in request["selected_checks"]]
        elif fault == "missing_transport_flag": request["argv"].remove("--owned-physical-fixtures")
        elif fault == "duplicate_transport_flag": request["argv"].append("--owned-physical-fixtures")
        elif fault == "missing_plugin_pair": del request["argv"][-2:]
        elif fault == "wrong_plugin_pair": request["argv"][-1] = "a.different.plugin"
        else: raise AssertionError(fault)
    attempt, _, _, kwargs = _physical_core_prepare(c, mutate=mutate)
    before = c["ledger"].read_bytes()
    with pytest.raises((validation.ValidationResourceError, native_disk.DaemonResourceError)):
        _owner(c, kwargs)
    assert c["ledger"].read_bytes() == before
    assert not tuple(attempt.iterdir())
    assert not _json(c["scheduler"].state_path)["leases"]


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_legacy_validation_profile_still_refuses_real_special_leaves(private_control, kind):
    c = private_control
    attempt, _, _, kwargs = c["prepare"]()
    with _owner(c, kwargs) as owned:
        target = attempt / "tmp" / "original.bin"
        target.write_bytes(b"original regular target retained")
        leaf = attempt / "tmp" / ("alias" if kind == "symlink" else "pipe")
        if kind == "symlink": leaf.symlink_to(target)
        else: os.mkfifo(leaf)
        identity = leaf.lstat()
        try:
            with pytest.raises((validation.ValidationResourceError, native_disk.DaemonResourceError)):
                owned.check_limits()
        finally:
            _physical_core_remove_leaf(leaf, identity, kind)
        assert target.read_bytes() == b"original regular target retained"


def test_physical_fixture_profile_precreates_exact_private_case_directories(private_control):
    c = private_control
    attempt, _, request, kwargs = _physical_core_prepare(c)
    assert not tuple(attempt.iterdir())
    with _owner(c, kwargs) as owned:
        root, case = Path(request["physical_fixture_profile"]["root"]), _physical_core_case(request)
        assert case.parent == root and case.is_dir()
        assert stat.S_IMODE(root.lstat().st_mode) == stat.S_IMODE(case.lstat().st_mode) == 0o700
        assert root.lstat().st_uid == case.lstat().st_uid == os.geteuid()
        assert list(root.iterdir()) == [case] and list(case.iterdir()) == []
        report = owned.check_limits()
        assert report["inventory"]["symlink_count"] == report["inventory"]["special_file_count"] == 0
        assert _json(c["scheduler"].state_path)["metrics"]["acquisitions_total"] == 1


def test_physical_fixture_profile_accepts_declared_upper_case_entry_and_path_bounds(private_control):
    c = private_control
    longest = "a" * 242 + "/b/c/d/e/f/g/h"
    assert len(longest) == 256 and len(longest.split("/")) == 8
    def mutate(request):
        request["selected_checks"] = ["check-" + str(i) for i in range(32)]
        request["physical_fixture_profile"]["cases"] = [
            {"nodeid": node, "entries": [
                _physical_core_entry("fifo", path=longest),
                *[_physical_core_entry("fifo", path="pipe-" + str(i)) for i in range(3)]]}
            for node in request["selected_checks"]]
    _, _, request, kwargs = _physical_core_prepare(c, mutate=mutate)
    with _owner(c, kwargs) as owned:
        root = Path(request["physical_fixture_profile"]["root"])
        assert len(list(root.iterdir())) == 32
        assert all(path.is_dir() and stat.S_IMODE(path.lstat().st_mode) == 0o700
                   for path in root.iterdir())
        assert owned.check_limits()["inventory"]["special_file_count"] == 0


def test_physical_fixture_profile_real_leaves_are_counted_without_opening_bodies(private_control, monkeypatch):
    c = private_control
    _, manifest, request, kwargs = _physical_core_prepare(c)
    with _owner(c, kwargs) as owned:
        case = _physical_core_case(request)
        target, alias, pipe = case / "original.bin", case / "alias", case / "pipe"
        target.write_bytes(b"unchanged target counted once")
        before = owned.check_limits()["inventory"]
        alias.symlink_to(target)  # Exact absolute spelling used by the unchanged public tests.
        os.mkfifo(pipe)
        alias_info, pipe_info = alias.lstat(), pipe.lstat()
        keeper = os.open(pipe, os.O_RDWR | os.O_NONBLOCK)
        original_open = os.open
        def no_body_open(path, flags, *args, **kwargs):
            if os.fspath(path) in {"alias", "pipe", str(alias), str(pipe)}:
                assert flags & os.O_PATH, "observer attempted a body-capable special-leaf open"
            return original_open(path, flags, *args, **kwargs)
        try:
            with monkeypatch.context() as patch:
                patch.setattr(os, "open", no_body_open)
                inventory = owned.check_limits()["inventory"]
            assert inventory["apparent_bytes"] - before["apparent_bytes"] == alias_info.st_size + pipe_info.st_size
            assert inventory["entry_count"] == before["entry_count"] + 2
            assert inventory["symlink_count"] == before["symlink_count"] + 1
            assert inventory["special_file_count"] == before["special_file_count"] + 1
        finally:
            os.close(keeper)
            _physical_core_remove_leaf(alias, alias_info, "symlink")
            _physical_core_remove_leaf(pipe, pipe_info, "fifo")
        assert target.read_bytes() == b"unchanged target counted once"
        result = _complete(owned, request, manifest)
        owned.seal_results(result)
        row = owned.finalize(artifacts_durable=True)
        assert row["status"] == "released"
    assert _json(c["scheduler"].state_path)["leases"] == {}


def test_physical_fixture_profile_counts_directory_alias_without_traversal(private_control):
    c = private_control
    _, _, request, kwargs = _physical_core_prepare(c, entries=[
        _physical_core_entry(path="alias", target="real", target_kind="directory")])
    with _owner(c, kwargs) as owned:
        case = _physical_core_case(request)
        real, alias = case / "real", case / "alias"
        real.mkdir()
        (real / "retained.bin").write_bytes(b"one copy")
        before = owned.check_limits()["inventory"]
        alias.symlink_to(real, target_is_directory=True)
        identity = alias.lstat()
        try:
            after = owned.check_limits()["inventory"]
            assert after["apparent_bytes"] == before["apparent_bytes"] + identity.st_size
            assert after["entry_count"] == before["entry_count"] + 1
            assert after["symlink_count"] == before["symlink_count"] + 1
        finally:
            _physical_core_remove_leaf(alias, identity, "symlink")
        assert (real / "retained.bin").read_bytes() == b"one copy"


def test_actual_cli_samples_declared_live_physical_fixtures_then_seals_regular_evidence(private_control):
    c = private_control
    attempt, manifest, request, kwargs = _physical_core_prepare(c)
    package_root = Path(validation.__file__).resolve().parents[3]
    launcher = package_root / "scripts" / "ops" / "legal_ir" / "run_owned_validation.py"
    check_source = c["source"].with_name("actual_physical_fixture_check.py")
    check_source.write_text(
        "import hashlib, json, os, stat, sys, time\n"
        "from pathlib import Path\n"
        "assert sys.argv[1:] == ['--owned-physical-fixtures', '-p', "
        "'ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_pytest']\n"
        "request_path = Path(os.environ['IPFS_DATASETS_OWNED_VALIDATION_REQUEST'])\n"
        "raw = request_path.read_bytes()\n"
        "assert hashlib.sha256(raw).hexdigest() == os.environ['IPFS_DATASETS_OWNED_VALIDATION_REQUEST_SHA256']\n"
        "request = json.loads(raw)\n"
        "assert 6 * 7 == 42\n"
        "observed_umask = os.umask(0o077)\n"
        "os.umask(observed_umask)\n"
        "assert observed_umask == 0o077\n"
        "case = Path(request['physical_fixture_profile']['root']) / hashlib.sha256(request['selected_checks'][0].encode('utf-8')).hexdigest()\n"
        "private = case/'default-private-descendant'\n"
        "private.mkdir()\n"
        "ordinary = private/'default-private-output.bin'\n"
        "ordinary.write_bytes(b'default modes observed in productive child')\n"
        "directory_mode = stat.S_IMODE(private.stat().st_mode)\n"
        "file_mode = stat.S_IMODE(ordinary.stat().st_mode)\n"
        "assert directory_mode == 0o700 and file_mode == 0o600\n"
        "target, alias, fifo = case/'original.bin', case/'alias', case/'pipe'\n"
        "target.write_bytes(b'original retained target')\n"
        "alias.symlink_to(target)\n"
        "os.mkfifo(fifo)\n"
        "identities = [(alias, alias.lstat(), stat.S_IFLNK), (fifo, fifo.lstat(), stat.S_IFIFO)]\n"
        "peer = os.open(fifo, os.O_RDWR|os.O_NONBLOCK)\n"
        "try:\n"
        "    print('actual alias and FIFO remain live for local sampling', flush=True)\n"
        "    time.sleep(0.35)\n"
        "finally:\n"
        "    os.close(peer)\n"
        "    for path, expected, kind in identities:\n"
        "        actual = path.lstat()\n"
        "        assert (actual.st_dev, actual.st_ino, stat.S_IFMT(actual.st_mode)) == (expected.st_dev, expected.st_ino, kind)\n"
        "        path.unlink()\n"
        "assert target.read_bytes() == b'original retained target'\n"
        "(case/'regular-evidence.json').write_text(json.dumps({'answer': 42, 'fixture_cleanup': True, 'observed_umask': observed_umask, 'directory_mode': directory_mode, 'file_mode': file_mode}))\n")
    request["argv"] = [sys.executable, "-B", str(check_source), "--owned-physical-fixtures", "-p",
                       "ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_pytest"]
    pinned = [launcher, check_source, Path(validation.__file__), Path(native_disk.__file__),
              Path(native.__file__), Path(existing.__file__),
              Path(native.__file__).with_name("proof_resource_safety.py"),
              Path(validation.__file__).with_name("validation_pytest.py")]
    request["source_sha256"] = {str(path.resolve()): _sha(path) for path in pinned}
    _write_json(manifest, request)
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
        IPFS_DATASETS_PY_MINIMAL_IMPORTS="1", IPFS_DATASETS_AUTO_INSTALL="0", IPFS_AUTO_INSTALL="false",
        OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    process = subprocess.run([sys.executable, "-B", str(launcher), "--request", str(manifest),
        "--expected-request-sha256", _sha(manifest), "--resource-ledger", str(c["ledger"])],
        cwd=package_root, env=environment, text=True, capture_output=True, timeout=35, umask=0o002)
    assert process.returncode == 0, process.stdout + process.stderr
    rows = [row for key, row in _json(c["ledger"])["reservations"].items() if key != "foreign-retained"]
    assert len(rows) == 1 and rows[0]["status"] == "released"
    assert rows[0]["storage_bytes"] == kwargs["storage_bytes"]
    state = _json(c["scheduler"].state_path)
    assert state["leases"] == {} and state["metrics"]["acquisitions_total"] == 1
    assert "actual alias and FIFO remain live" in (attempt / "logs" / "stdout.log").read_text()
    case = _physical_core_case(request)
    evidence = _json(case / "regular-evidence.json")
    assert evidence == {"answer": 42, "fixture_cleanup": True, "observed_umask": 0o077,
                        "directory_mode": 0o700, "file_mode": 0o600}
    private = case / "default-private-descendant"
    assert stat.S_IMODE(private.stat().st_mode) == 0o700
    assert stat.S_IMODE((private / "default-private-output.bin").stat().st_mode) == 0o600
    assert stat.S_IMODE((case / "regular-evidence.json").stat().st_mode) == 0o600
    assert not (case / "alias").exists() and not (case / "pipe").exists()
    sealed = _json(attempt / "logs" / "validation-durability.json")
    assert all(not row["path"].endswith(("/alias", "/pipe")) for row in sealed["files"])


@pytest.mark.parametrize("location", ["undeclared", "outside_root"])
def test_physical_fixture_profile_refuses_unlisted_or_out_of_scope_real_leaf(private_control, location):
    c = private_control
    attempt, _, request, kwargs = _physical_core_prepare(c)
    with _owner(c, kwargs) as owned:
        leaf = (_physical_core_case(request) / "undeclared" if location == "undeclared"
                else attempt / "exports" / "outside")
        os.mkfifo(leaf)
        identity = leaf.lstat()
        try:
            with pytest.raises((validation.ValidationResourceError, native_disk.DaemonResourceError)):
                owned.check_limits()
        finally:
            _physical_core_remove_leaf(leaf, identity, "fifo")


@pytest.mark.parametrize("actual_kind", ["fifo", "symlink"])
def test_physical_fixture_profile_real_leaf_must_match_its_declared_type(private_control, actual_kind):
    c = private_control
    _, _, request, kwargs = _physical_core_prepare(c)
    with _owner(c, kwargs) as owned:
        case = _physical_core_case(request)
        (case / "original.bin").write_bytes(b"retained original")
        leaf = case / ("alias" if actual_kind == "fifo" else "pipe")
        if actual_kind == "fifo": os.mkfifo(leaf)
        else: leaf.symlink_to(case / "original.bin")
        identity = leaf.lstat()
        try:
            with pytest.raises((validation.ValidationResourceError, native_disk.DaemonResourceError)):
                owned.check_limits()
        finally:
            _physical_core_remove_leaf(leaf, identity, actual_kind)


def test_physical_fixture_profile_does_not_substitute_a_different_symlink_target(private_control):
    c = private_control
    _, _, request, kwargs = _physical_core_prepare(c)
    with _owner(c, kwargs) as owned:
        case = _physical_core_case(request)
        (case / "original.bin").write_bytes(b"declared target")
        (case / "modified.bin").write_bytes(b"different target")
        assert len(str(case / "modified.bin")) == len(str(case / "original.bin"))
        leaf = case / "alias"
        leaf.symlink_to(case / "modified.bin")
        identity = leaf.lstat()
        try:
            with pytest.raises((validation.ValidationResourceError, native_disk.DaemonResourceError)):
                owned.check_limits()
        finally:
            _physical_core_remove_leaf(leaf, identity, "symlink")
        assert (case / "original.bin").read_bytes() == b"declared target"
        assert (case / "modified.bin").read_bytes() == b"different target"


def test_physical_fixture_profile_charges_observed_leaf_after_real_cleanup_disappearance(private_control, monkeypatch):
    c = private_control
    _, _, request, kwargs = _physical_core_prepare(c)
    with _owner(c, kwargs) as owned:
        case = _physical_core_case(request)
        target, alias = case / "original.bin", case / "alias"
        target.write_bytes(b"original target remains")
        before = owned.check_limits()["inventory"]
        alias.symlink_to(target)
        identity = alias.lstat()
        case_info = case.lstat()
        original_readlink = os.readlink
        removed = []
        def disappear_at_readlink(path, *args, **options):
            result = original_readlink(path, *args, **options)
            descriptor = options.get("dir_fd")
            if path == "alias" and descriptor is not None and not removed:
                opened = os.fstat(descriptor)
                assert (opened.st_dev, opened.st_ino) == (case_info.st_dev, case_info.st_ino)
                _physical_core_remove_leaf(alias, identity, "symlink")
                removed.append(True)
            return result
        try:
            with monkeypatch.context() as patch:
                patch.setattr(os, "readlink", disappear_at_readlink)
                sampled = owned.check_limits()["inventory"]
            assert removed == [True]
            assert sampled["apparent_bytes"] == before["apparent_bytes"] + identity.st_size
            assert sampled["entry_count"] == before["entry_count"] + 1
            assert sampled["symlink_count"] == before["symlink_count"] + 1
            assert owned.check_limits()["inventory"]["symlink_count"] == before["symlink_count"]
        finally:
            if not removed:
                _physical_core_remove_leaf(alias, identity, "symlink")
        assert target.read_bytes() == b"original target remains"


@pytest.mark.parametrize("race", ["same_target_substitution", "unbound_reappearance"])
def test_physical_fixture_profile_refuses_real_leaf_substitution_during_sample(private_control, monkeypatch, race):
    c = private_control
    _, _, request, kwargs = _physical_core_prepare(c)
    with _owner(c, kwargs) as owned:
        case = _physical_core_case(request)
        target, alias = case / "original.bin", case / "alias"
        target.write_bytes(b"retained target")
        alias.symlink_to(target)
        first = alias.lstat()
        # Keep the original inode alive while its pathname is replaced.
        held = os.open(alias, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC)
        original_readlink, original_stat = os.readlink, os.stat
        replaced, absent = [], []
        def substitute_at_readlink(path, *args, **options):
            value = original_readlink(path, *args, **options)
            if path == "alias" and options.get("dir_fd") is not None and not replaced:
                _physical_core_remove_leaf(alias, first, "symlink")
                alias.symlink_to(target)
                replaced.append(alias.lstat())
                assert (replaced[0].st_dev, replaced[0].st_ino) != (first.st_dev, first.st_ino)
            return value
        def disappear_then_reappear(path, *args, **options):
            if path == "alias" and options.get("dir_fd") is not None:
                if not absent:
                    _physical_core_remove_leaf(alias, first, "symlink")
                    absent.append(True)
                    raise FileNotFoundError("authored declared-leaf cleanup boundary")
                if not replaced:
                    alias.symlink_to(target)
                    replaced.append(alias.lstat())
            return original_stat(path, *args, **options)
        try:
            with monkeypatch.context() as patch:
                if race == "same_target_substitution":
                    patch.setattr(os, "readlink", substitute_at_readlink)
                else:
                    patch.setattr(os, "stat", disappear_then_reappear)
                with pytest.raises(validation.ValidationResourceError, match="changed|reappeared|substitut"):
                    owned.check_limits()
            assert len(replaced) == 1
        finally:
            os.close(held)
            if replaced:
                _physical_core_remove_leaf(alias, replaced[0], "symlink")
            elif not absent:
                _physical_core_remove_leaf(alias, first, "symlink")
        assert target.read_bytes() == b"retained target"


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_physical_fixture_profile_cannot_seal_live_special_leaves(private_control, kind):
    c = private_control
    _, manifest, request, kwargs = _physical_core_prepare(c)
    with _owner(c, kwargs) as owned:
        result = _complete(owned, request, manifest)
        case = _physical_core_case(request)
        (case / "original.bin").write_bytes(b"original")
        leaf = case / ("alias" if kind == "symlink" else "pipe")
        if kind == "symlink": leaf.symlink_to(case / "original.bin")
        else: os.mkfifo(leaf)
        identity = leaf.lstat()
        reservation = owned.reservation_id
        try:
            owned.check_limits()  # Live observation is allowed, unlike final durable evidence.
            with pytest.raises((validation.ValidationResourceError, native_disk.DaemonResourceError)):
                owned.seal_results(result)
            assert not (Path(request["attempt_directory"]) / "logs" / "validation-durability.json").exists()
        finally:
            _physical_core_remove_leaf(leaf, identity, kind)
    row = _json(c["ledger"])["reservations"][reservation]
    assert row["status"] == "retained" and row["storage_bytes"] == kwargs["storage_bytes"]
    assert row.get("artifacts_durable_asserted") is not True


@pytest.mark.parametrize("which", ["root", "case"])
def test_physical_fixture_profile_refuses_replaced_pinned_directories(private_control, which):
    c = private_control
    _, _, request, kwargs = _physical_core_prepare(c)
    with _owner(c, kwargs) as owned:
        path = Path(request["physical_fixture_profile"]["root"]) if which == "root" else _physical_core_case(request)
        saved = path.with_name(path.name + "-retained-original")
        path.rename(saved)
        path.mkdir(mode=0o700)
        try:
            with pytest.raises((validation.ValidationResourceError, native_disk.DaemonResourceError)):
                owned.check_limits()
        finally:
            path.rmdir()
            saved.rename(path)


def test_physical_fixture_profile_cannot_hide_regular_bytes_behind_allowance(private_control):
    c = private_control
    _, _, request, kwargs = _physical_core_prepare(c)
    with _owner(c, kwargs) as owned:
        retained = _physical_core_case(request) / "large.bin"
        retained.write_bytes(b"x" * (kwargs["storage_bytes"] + 1))
        with pytest.raises((validation.ValidationResourceError, native_disk.DaemonResourceError), match="storage|byte|allowance"):
            owned.check_limits()
        assert retained.stat().st_size == kwargs["storage_bytes"] + 1



# Explicit physical tmp_path routing; no special filesystem entries are created
# by these plugin checks. The unchanged six public tests supply that coverage.
def _physical_pytest_plugin():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import validation_pytest
    return validation_pytest


def _physical_pytest_request(tmp_path, selected=None):
    attempt = tmp_path / "physical-owner-attempt"
    root = attempt / "tmp" / "physical-fixtures"
    root.mkdir(parents=True, mode=0o700)
    test_file = tmp_path / "test_actual_physical_mapping.py"
    selected = selected or [str(test_file) + "::test_mapped_directory"]
    entries = [{"path": "leaf.bin", "kind": "symlink", "target": "original.bin", "target_kind": "file"}]
    for node in selected:
        (root / hashlib.sha256(node.encode("utf-8")).hexdigest()).mkdir(mode=0o700)
    value = dict(schema="owned-validation-request/v2", argv=[sys.executable, "-B", "-m", "pytest",
        "-p", "ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_pytest",
        "--owned-physical-fixtures", *selected], cwd=str(tmp_path), selected_checks=list(selected),
        source_sha256={}, timeout_seconds=30, storage_bytes=4*1024*1024, memory_mb=128,
        cpu_slots=1, child_process_slots=1, attempt_directory=str(attempt),
        outputs={name:str(attempt/name) for name in ("pytest", "tmp", "cache", "db", "exports", "logs")},
        declared_external_writable_paths=[], process_scope=validation.GROUP_SCOPE,
        scheduler_state_path=str(tmp_path/"not-opened-native-state.json"),
        expected_scheduler_policy_sha256="0"*64, roots=[str(tmp_path)],
        physical_fixture_profile=dict(schema="owned-validation-physical-fixtures/v1",root=str(root),
            cases=[dict(nodeid=node,entries=deepcopy(entries)) for node in selected]))
    path=tmp_path/"physical-request.json"
    _write_json(path,value)
    return path,value,root,test_file


def _load_physical_pytest_profile(monkeypatch, path, *, enabled=True):
    from types import SimpleNamespace
    monkeypatch.setenv("IPFS_DATASETS_OWNED_VALIDATION_REQUEST",str(path))
    monkeypatch.setenv("IPFS_DATASETS_OWNED_VALIDATION_REQUEST_SHA256",_sha(path))
    return _physical_pytest_plugin()._load_profile(SimpleNamespace(getoption=lambda _:enabled))


def test_physical_pytest_profile_default_has_no_request_transport(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.delenv("IPFS_DATASETS_OWNED_VALIDATION_REQUEST",raising=False)
    monkeypatch.delenv("IPFS_DATASETS_OWNED_VALIDATION_REQUEST_SHA256",raising=False)
    assert _physical_pytest_plugin()._load_profile(SimpleNamespace(getoption=lambda _:False)) is None


@pytest.mark.parametrize("flag,path_env,sha_env", [
    (True,False,False),(True,True,False),(True,False,True),
    (False,True,False),(False,False,True),(False,True,True),
])
def test_physical_pytest_profile_refuses_partial_or_one_sided_transport(
        tmp_path,monkeypatch,flag,path_env,sha_env):
    from types import SimpleNamespace
    path,_,_,_=_physical_pytest_request(tmp_path)
    for key in ("IPFS_DATASETS_OWNED_VALIDATION_REQUEST","IPFS_DATASETS_OWNED_VALIDATION_REQUEST_SHA256"):
        monkeypatch.delenv(key,raising=False)
    if path_env:monkeypatch.setenv("IPFS_DATASETS_OWNED_VALIDATION_REQUEST",str(path))
    if sha_env:monkeypatch.setenv("IPFS_DATASETS_OWNED_VALIDATION_REQUEST_SHA256",_sha(path))
    with pytest.raises(pytest.UsageError):
        _physical_pytest_plugin()._load_profile(SimpleNamespace(getoption=lambda _:flag))


@pytest.mark.parametrize("damage", ["schema","extra-request","extra-profile","extra-case","extra-entry",
    "outside-root","missing-case","duplicate-case","duplicate-entry","traversal","backslash",
    "empty-component","absolute-target","fifo-target","wrong-target-kind","bool-storage","wrong-hash",
    "relative-node","ancestor-special","target-special","target-under-special"])
def test_physical_pytest_profile_refuses_nonclosed_or_unbound_mapping(tmp_path,monkeypatch,damage):
    path,value,_,_=_physical_pytest_request(tmp_path)
    profile=value["physical_fixture_profile"];case=profile["cases"][0];entry=case["entries"][0]
    if damage=="schema":value["schema"]="owned-validation-request/v1"
    elif damage=="extra-request":value["extra"]=True
    elif damage=="extra-profile":profile["extra"]=True
    elif damage=="extra-case":case["extra"]=True
    elif damage=="extra-entry":entry["extra"]=True
    elif damage=="outside-root":profile["root"]=str(tmp_path)
    elif damage=="missing-case":case["nodeid"]+="-not-selected"
    elif damage=="duplicate-case":profile["cases"].append(deepcopy(case))
    elif damage=="duplicate-entry":case["entries"].append(deepcopy(entry))
    elif damage=="traversal":entry["path"]="../leaf.bin"
    elif damage=="backslash":entry["path"]="nested\\leaf.bin"
    elif damage=="empty-component":entry["path"]="nested//leaf.bin"
    elif damage=="absolute-target":entry["target"]="/outside.bin"
    elif damage=="fifo-target":entry["kind"]="fifo"
    elif damage=="wrong-target-kind":entry["target_kind"]="fifo"
    elif damage=="bool-storage":value["storage_bytes"]=True
    elif damage=="relative-node":
        value["selected_checks"]=["test_relative.py::test_mapped_directory"]
        case["nodeid"]=value["selected_checks"][0]
    elif damage=="ancestor-special":
        case["entries"].append(dict(path="leaf.bin/child",kind="fifo",target=None,target_kind=None))
    elif damage in {"target-special","target-under-special"}:
        case["entries"].append(dict(path="other",kind="fifo",target=None,target_kind=None))
        entry["target"]="other" if damage=="target-special" else "other/child"
    _write_json(path,value)
    if damage=="wrong-hash":
        monkeypatch.setenv("IPFS_DATASETS_OWNED_VALIDATION_REQUEST",str(path))
        monkeypatch.setenv("IPFS_DATASETS_OWNED_VALIDATION_REQUEST_SHA256","0"*64)
        from types import SimpleNamespace
        with pytest.raises(pytest.UsageError):
            _physical_pytest_plugin()._load_profile(SimpleNamespace(getoption=lambda _:True))
    else:
        with pytest.raises(pytest.UsageError):_load_physical_pytest_profile(monkeypatch,path)


def test_physical_pytest_profile_rejects_duplicate_JSON_before_mapping(tmp_path,monkeypatch):
    path,_,_,_=_physical_pytest_request(tmp_path)
    original=path.read_text()
    path.write_text(original[:-2]+',"schema":"owned-validation-request/v2"}\n')
    with pytest.raises(pytest.UsageError):_load_physical_pytest_profile(monkeypatch,path)


def test_physical_pytest_profile_binds_exact_case_inode_and_retains_replaced_evidence(tmp_path,monkeypatch):
    path,value,root,_=_physical_pytest_request(tmp_path)
    plugin=_physical_pytest_plugin();profile=_load_physical_pytest_profile(monkeypatch,path)
    node=value["selected_checks"][0];case=root/hashlib.sha256(node.encode()).hexdigest()
    assert plugin._guard_profile(profile,node)==case
    old=case.with_name(case.name+"-original")
    case.rename(old);case.mkdir(mode=0o700)
    with pytest.raises(pytest.UsageError,match="identity changed"):plugin._guard_profile(profile,node)
    assert old.is_dir() and case.is_dir()


@pytest.mark.parametrize("failure",["bytes","depth","entries"])
def test_physical_pytest_finalizer_bounds_real_ordinary_inventory(tmp_path,monkeypatch,failure):
    plugin=_physical_pytest_plugin();case=tmp_path/"strict-final-case";case.mkdir(mode=0o700)
    if failure=="bytes":(case/"retained.bin").write_bytes(b"1234")
    elif failure=="depth":
        (case/"one").mkdir();(case/"one"/"two").mkdir();monkeypatch.setattr(plugin,"_MAX_PHYSICAL_DEPTH",1)
    else:
        (case/"one.bin").write_bytes(b"1");(case/"two.bin").write_bytes(b"2")
        monkeypatch.setattr(plugin,"_MAX_PHYSICAL_INVENTORY_ENTRIES",1)
    descriptor=os.open(case,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        with pytest.raises(pytest.UsageError):plugin._strict_final_tree(descriptor,3 if failure=="bytes" else 1024)
    finally:os.close(descriptor)
    assert case.is_dir() and list(case.iterdir())


def test_physical_pytest_finalizer_retains_ordinary_target_and_checks_complete_collection(tmp_path,monkeypatch):
    from types import SimpleNamespace
    path,value,root,_=_physical_pytest_request(tmp_path)
    plugin=_physical_pytest_plugin();profile=_load_physical_pytest_profile(monkeypatch,path)
    node=value["selected_checks"][0];case=root/hashlib.sha256(node.encode()).hexdigest()
    (case/"original.bin").write_bytes(b"ordinary retained target")
    descriptor=os.open(case,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:plugin._strict_final_tree(descriptor,value["storage_bytes"])
    finally:os.close(descriptor)
    config=SimpleNamespace(_owned_physical_fixture_profile=profile)
    item=SimpleNamespace(nodeid="test_actual_physical_mapping.py::test_mapped_directory",path=Path(node.partition("::")[0]))
    plugin.pytest_collection_modifyitems(None,config,[item])
    with pytest.raises(pytest.UsageError):plugin.pytest_collection_modifyitems(None,config,[])
    session=SimpleNamespace(config=config,exitstatus=0)
    plugin.pytest_sessionfinish(session,0)
    assert session.exitstatus==pytest.ExitCode.TESTS_FAILED
    assert (case/"original.bin").read_bytes()==b"ordinary retained target"


def test_physical_pytest_actual_fixture_routes_exact_frozen_case_and_retains_targets(tmp_path):
    path,value,root,test_file=_physical_pytest_request(tmp_path)
    case=root/hashlib.sha256(value["selected_checks"][0].encode()).hexdigest()
    test_file.write_text("from pathlib import Path\n"
        "def test_mapped_directory(tmp_path):\n"
        +"    assert tmp_path == Path("+repr(str(case))+")\n"
        +"    assert tmp_path.stat().st_mode & 0o777 == 0o700\n"
        +"    (tmp_path/'original.bin').write_bytes(b'retained ordinary target')\n")
    base=tmp_path/"must-not-recreate-physical-root"
    package_root=Path(validation.__file__).resolve().parents[3]
    environment=dict(os.environ,PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",PYTHONDONTWRITEBYTECODE="1",
        IPFS_DATASETS_PY_MINIMAL_IMPORTS="1",IPFS_DATASETS_AUTO_INSTALL="0",IPFS_AUTO_INSTALL="false",
        PYTHONPATH=os.pathsep.join([str(package_root),os.environ.get("PYTHONPATH","")]),
        IPFS_DATASETS_OWNED_VALIDATION_REQUEST=str(path),
        IPFS_DATASETS_OWNED_VALIDATION_REQUEST_SHA256=_sha(path))
    result=subprocess.run([sys.executable,"-B","-m","pytest","-q","-c","/dev/null","--noconftest",
        "--rootdir",str(tmp_path),"-p","ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_pytest",
        "-p","no:cacheprovider","--owned-physical-fixtures","--basetemp",str(base),str(test_file)],
        cwd=tmp_path,env=environment,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    assert "1 passed" in result.stdout and not base.exists()
    assert (case/"original.bin").read_bytes()==b"retained ordinary target"
    assert sorted(root.iterdir())==[case]



# Actual denied native admission for the explicit v2 filesystem profile. The
# existing CLI helper still starts the real pinned launcher/private scheduler;
# only its private request-preparation fixture gains the v2 fields.
def _actual_physical_no_child_cli(control, monkeypatch):
    original_prepare = _prepare_no_child_lifecycle
    def prepare_physical(c):
        module,launcher,attempt,manifest,request,kwargs=original_prepare(c)
        request["schema"]="owned-validation-request/v2"
        request["argv"].extend(["--owned-physical-fixtures","-p",
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_pytest"])
        request["physical_fixture_profile"]={
            "schema":"owned-validation-physical-fixtures/v1",
            "root":str(attempt/"tmp"/"physical-fixtures"),
            "cases":[{"nodeid":request["selected_checks"][0],"entries":[
                {"path":"pipe","kind":"fifo","target":None,"target_kind":None}]}]}
        plugin=Path(validation.__file__).with_name("validation_pytest.py")
        request["source_sha256"][str(plugin.resolve())]=_sha(plugin)
        _write_json(manifest,request)
        kwargs["frozen_validation_manifest_sha256"]=_sha(manifest)
        return module,launcher,attempt,manifest,request,kwargs
    with monkeypatch.context() as patch:
        patch.setitem(globals(),"_prepare_no_child_lifecycle",prepare_physical)
        return _actual_no_child_cli(control)


def test_actual_v2_cli_native_timeout_closes_only_original_no_child_source_custody(
        private_control,monkeypatch):
    module,terminal,raw,caller,attempt=_actual_physical_no_child_cli(private_control,monkeypatch)
    expected={"verdict":"proven_original_no_child_no_native_grant",
              "source_custody_closed":True,"storage_release_authorized":False}
    assert module.classify_owned_validation_source_custody(terminal,raw,**caller)==expected
    request=json.loads(raw);reservation=terminal["reservation"]
    assert request["schema"]=="owned-validation-request/v2"
    assert reservation["resource_lease"] is None and reservation["process_observation"] is None
    assert reservation["record"]["child"] is None and reservation["record"]["prior_children"]==[]
    assert reservation["status"]==reservation["record"]["status"]=="retained"
    assert reservation["record"]["retention_reason"]=="scheduler_admission_failed"
    assert reservation["record"]["artifacts_durable_asserted"] is False
    assert reservation["physical_fixture_profile"]=={
        "schema":"owned-validation-physical-fixtures/v1","request_sha256":caller["expected_request_sha256"],
        "root":str(attempt/"tmp"/"physical-fixtures"),"case_count":1,"entry_count":1,
        "live_special_file_window":False}
    assert not tuple(attempt.iterdir())
    witness=terminal["source_custody_lifecycle"]
    assert witness["events"]==dict(owner_open_attempted=True,owner_open_returned=False,
        child_launch_attempted=False,child_created=False,barrier_release_attempted=False,
        barrier_released=False,owner_exit_handling_completed=True)
    assert witness["native_grant"]["exact_native_timeout"] is True
    assert witness["native_grant"]["timeout_decision"]["request_id"]=="validation:"+reservation["reservation_id"]
    # Authored changes below are rejection controls, not additional real native
    # failures. They cannot grant storage release or qualify physical fixtures.
    unknown={"verdict":"requires_original_native_cleanup","source_custody_closed":False,
             "storage_release_authorized":False}
    for fault in ("missing_observation","live_window","live_window_integer","observation_schema","observation_pin",
                  "observation_root","observation_case_bool","observation_entry_bool","extra_observation",
                  "open_returned","child_created","native_acquired","storage_release"):
        changed=deepcopy(terminal);observation=changed["reservation"]["physical_fixture_profile"]
        if fault=="missing_observation":changed["reservation"].pop("physical_fixture_profile")
        elif fault=="live_window":observation["live_special_file_window"]=True
        elif fault=="live_window_integer":observation["live_special_file_window"]=0
        elif fault=="observation_schema":observation["schema"]="owned-validation-physical-fixtures/v2"
        elif fault=="observation_pin":observation["request_sha256"]="0"*64
        elif fault=="observation_root":observation["root"]+="-different"
        elif fault=="observation_case_bool":observation["case_count"]=True
        elif fault=="observation_entry_bool":observation["entry_count"]=True
        elif fault=="extra_observation":observation["extra"]=True
        elif fault=="open_returned":changed["source_custody_lifecycle"]["events"]["owner_open_returned"]=True
        elif fault=="child_created":changed["source_custody_lifecycle"]["events"]["child_created"]=True
        elif fault=="native_acquired":changed["source_custody_lifecycle"]["native_grant"]["status"]="acquired"
        else:changed["source_custody_lifecycle"]["storage"]["release_authorized"]=True
        assert module.classify_owned_validation_source_custody(changed,raw,**caller)==unknown,fault
    for fault in ("missing_profile","extra_profile","wrong_root","unknown_kind","self_target",
                  "duplicate_entry","overlapping_entry","target_under_special","wrong_schema"):
        value=deepcopy(request);profile=value["physical_fixture_profile"]
        entry=profile["cases"][0]["entries"][0]
        if fault=="missing_profile":value.pop("physical_fixture_profile")
        elif fault=="extra_profile":profile["extra"]=True
        elif fault=="wrong_root":profile["root"]+="-outside"
        elif fault=="unknown_kind":entry["kind"]="socket"
        elif fault=="self_target":entry.update(kind="symlink",target="pipe",target_kind="file")
        elif fault=="duplicate_entry":profile["cases"][0]["entries"].append(deepcopy(entry))
        elif fault=="overlapping_entry":profile["cases"][0]["entries"].append(
            dict(path="pipe/child",kind="fifo",target=None,target_kind=None))
        elif fault=="target_under_special":profile["cases"][0]["entries"].append(
            dict(path="alias",kind="symlink",target="pipe/child",target_kind="file"))
        else:value["schema"]="owned-validation-request/v3"
        altered_raw=json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
        altered_pin=hashlib.sha256(altered_raw).hexdigest();changed=deepcopy(terminal)
        changed["request_sha256"]=changed["failure"]["request_sha256"]=changed["source_custody_lifecycle"]["request_sha256"]=altered_pin
        changed["reservation"]["physical_fixture_profile"]["request_sha256"]=altered_pin
        if fault=="wrong_root":changed["reservation"]["physical_fixture_profile"]["root"]=profile["root"]
        if fault in {"duplicate_entry","overlapping_entry","target_under_special"}:
            changed["reservation"]["physical_fixture_profile"]["entry_count"]=2
        assert module.classify_owned_validation_source_custody(changed,altered_raw,
            **{**caller,"expected_request_sha256":altered_pin})==unknown,fault
    assert module.classify_owned_validation_source_custody(terminal,raw,**caller)==expected


# Constructor refusals precede owner.open and retain no reservation or child.
# These ordinary-file tests start the actual pinned CLI against the existing
# private scheduler/ledger fixture; no shared host state or model is used.
def _actual_pre_owner_refusal_cli(control, schema='owned-validation-request/v1'):
    module, launcher, attempt, manifest, request, _ = _prepare_no_child_lifecycle(control)
    request['selected_checks'] = ['authored invalid selected check\x00']
    if schema == 'owned-validation-request/v2':
        request['schema'] = schema
        request['argv'].extend(['--owned-physical-fixtures', '-p',
            'ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_pytest'])
        request['physical_fixture_profile'] = {
            'schema': 'owned-validation-physical-fixtures/v1',
            'root': str(attempt/'tmp'/'physical-fixtures'),
            'cases': [{'nodeid': request['selected_checks'][0], 'entries': [
                {'path': 'unused.pipe', 'kind': 'fifo', 'target': None, 'target_kind': None}]}]}
        plugin = Path(validation.__file__).with_name('validation_pytest.py')
        request['source_sha256'][str(plugin.resolve())] = _sha(plugin)
    _write_json(manifest, request)
    ledger_before = control['ledger'].read_bytes()
    scheduler_before = control['scheduler'].state_path.read_bytes()
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
        IPFS_DATASETS_PY_MINIMAL_IMPORTS='1', IPFS_DATASETS_AUTO_INSTALL='0',
        IPFS_AUTO_INSTALL='false', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    cli = None
    try:
        cli = subprocess.Popen([sys.executable, '-B', str(launcher), '--request', str(manifest),
            '--expected-request-sha256', _sha(manifest), '--resource-ledger', str(control['ledger'])],
            cwd=launcher.parents[3], env=environment, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        identity = native_disk._process(cli.pid)
        assert identity is not None
        stdout, stderr = cli.communicate(timeout=30)
        assert cli.returncode != 0, (stdout, stderr)
        terminal = json.loads(stdout)
        assert terminal['failure']['error_type'] == 'ValidationResourceError', (stdout, stderr)
        assert control['ledger'].read_bytes() == ledger_before
        assert control['scheduler'].state_path.read_bytes() == scheduler_before
        assert not tuple(attempt.iterdir())
        return module, terminal, manifest.read_bytes(), dict(
            expected_request_sha256=_sha(manifest), owner_pid=cli.pid,
            owner_birth=identity['birth'], returncode=cli.returncode,
            expected_resource_ledger=str(control['ledger'])), manifest, attempt
    finally:
        if cli is not None:
            if cli.poll() is None:
                cli.terminate()
                cli.wait(timeout=10)
            _stop_group(cli)


@pytest.mark.parametrize('schema', ['owned-validation-request/v1', 'owned-validation-request/v2'],
    ids=['v1-invalid-selected-check', 'v2-invalid-selected-check'])
def test_pre_owner_actual_cli_constructor_refusal_closes_source_without_resources(private_control, schema):
    module, terminal, raw, caller, _, _ = _actual_pre_owner_refusal_cli(private_control, schema)
    assert '\x00' in json.loads(raw)['selected_checks'][0]
    assert terminal['reservation'] == {}
    witness = terminal['source_custody_lifecycle']
    assert witness['schema'] == module.PRE_OWNER_REFUSAL_SCHEMA
    assert witness['stage'] == 'owner_construction_refused'
    assert witness['events'] == {key: key == 'owner_construction_attempted'
                                 for key in module._PRE_OWNER_EVENTS}
    assert witness['native_grant'] == {'status': 'not_requested'}
    assert witness['storage'] == {'status': 'not_requested', 'release_authorized': False}
    assert witness['source_guards'] == {'request_unchanged': True, 'source_pins_unchanged': True,
        'owner_identity_unchanged': True, 'errors': []}
    assert module.classify_owned_validation_source_custody(terminal, raw, **caller) == {
        'verdict': 'proven_original_no_child_no_native_grant',
        'source_custody_closed': True, 'storage_release_authorized': False}
    assert all(terminal[key] is False for key in ('completed', 'admitted', 'Lean_admitted'))


def test_pre_owner_classifier_refuses_spoofed_missing_or_opened_certificates(private_control):
    module, terminal, raw, caller, _, _ = _actual_pre_owner_refusal_cli(private_control)
    unknown = {'verdict': 'requires_original_native_cleanup', 'source_custody_closed': False,
               'storage_release_authorized': False}
    for fault in ('missing', 'schema', 'request', 'producer', 'pid', 'birth', 'ledger', 'stage',
            'reservation', 'construct_returned', 'construct_not_attempted', 'open', 'child', 'exit',
            'event_integer', 'native', 'storage', 'storage_integer', 'source_guard', 'guard_integer',
            'failure_authority', 'failure_checks', 'failure_returncode', 'failure_extra'):
        changed = deepcopy(terminal)
        witness = changed['source_custody_lifecycle']
        if fault == 'missing': changed.pop('source_custody_lifecycle')
        elif fault == 'schema': witness['schema'] += '-different'
        elif fault == 'request': witness['request_sha256'] = '0'*64
        elif fault == 'producer': witness['producer']['sha256'] = '0'*64
        elif fault == 'pid': witness['owner']['pid'] += 1
        elif fault == 'birth': witness['owner']['birth'] += '1'
        elif fault == 'ledger': witness['ledger_path'] += '.foreign'
        elif fault == 'stage': witness['stage'] = 'owner_open_refused'
        elif fault == 'reservation': changed['reservation'] = {'record': {}}
        elif fault == 'construct_returned': witness['events']['owner_construction_returned'] = True
        elif fault == 'construct_not_attempted': witness['events']['owner_construction_attempted'] = False
        elif fault == 'open': witness['events']['owner_open_attempted'] = True
        elif fault == 'child': witness['events']['child_launch_attempted'] = True
        elif fault == 'exit': witness['events']['owner_exit_handling_completed'] = True
        elif fault == 'event_integer': witness['events']['owner_open_attempted'] = 0
        elif fault == 'native': witness['native_grant']['status'] = 'acquired'
        elif fault == 'storage': witness['storage']['release_authorized'] = True
        elif fault == 'storage_integer': witness['storage']['release_authorized'] = 0
        elif fault == 'source_guard': witness['source_guards']['source_pins_unchanged'] = False
        elif fault == 'guard_integer': witness['source_guards']['source_pins_unchanged'] = 1
        elif fault == 'failure_authority': changed['failure']['admitted'] = True
        elif fault == 'failure_checks': changed['failure']['executed_checks'] = ['not a constructor refusal']
        elif fault == 'failure_returncode': changed['failure']['returncode'] = 0
        else: changed['failure']['extra'] = True
        assert module.classify_owned_validation_source_custody(changed, raw, **caller) == unknown, fault
    for key, value in (('owner_pid', True), ('owner_birth', 'unknown'), ('returncode', 0),
            ('returncode', False), ('expected_request_sha256', '0'*64),
            ('expected_resource_ledger', str(private_control['ledger'])+'.foreign')):
        assert module.classify_owned_validation_source_custody(terminal, raw,
            **{**caller, key: value}) == unknown, key


def test_pre_owner_classifier_rechecks_original_request_and_source_pins(private_control):
    module, terminal, raw, caller, _, _ = _actual_pre_owner_refusal_cli(private_control)
    expected = {'verdict': 'proven_original_no_child_no_native_grant', 'source_custody_closed': True,
                'storage_release_authorized': False}
    for name in module._LIFECYCLE_OWNER_NAMES:
        value = json.loads(raw)
        value['source_sha256'].pop(str(module.ROOT/'ipfs_datasets_py/optimizers/logic_theorem_optimizer'/name))
        altered = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
        pin = hashlib.sha256(altered).hexdigest()
        changed = deepcopy(terminal)
        changed['request_sha256'] = changed['source_custody_lifecycle']['request_sha256'] = pin
        assert module.classify_owned_validation_source_custody(changed, altered,
            **{**caller, 'expected_request_sha256': pin})['source_custody_closed'] is False, name
    source = private_control['source']
    before = source.read_bytes()
    try:
        source.write_bytes(before+b'\n# authored endpoint drift\n')
        assert module.classify_owned_validation_source_custody(terminal, raw,
            **caller)['source_custody_closed'] is False
    finally:
        source.write_bytes(before)
    assert module.classify_owned_validation_source_custody(terminal, raw, **caller) == expected


def _prepare_pregrant_capacity(control, *, process_scope=validation.TRACKED_SCOPE):
    module, launcher, attempt, manifest, request, kwargs = _prepare_no_child_lifecycle(control)
    request['process_scope'] = process_scope
    _write_json(manifest, request)
    kwargs['frozen_validation_manifest_sha256'] = _sha(manifest)
    # Only this private ledger's already-retained foreign promise grows. The
    # real original cap, scheduler policy and host ledger are never modified.
    ledger = _json(control['ledger'])
    control['foreign']['storage_bytes'] = native_disk.MAX_STORAGE_BYTES
    ledger['reservations']['foreign-retained'] = deepcopy(control['foreign'])
    _write_json(control['ledger'], ledger)
    return module, launcher, attempt, manifest, request, kwargs


def _actual_pregrant_capacity_cli(control, *, process_scope=validation.TRACKED_SCOPE):
    module, launcher, attempt, manifest, request, _ = _prepare_pregrant_capacity(
        control, process_scope=process_scope)
    ledger_before = control['ledger'].read_bytes()
    scheduler_before = control['scheduler'].state_path.read_bytes()
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
        IPFS_DATASETS_PY_MINIMAL_IMPORTS='1', IPFS_DATASETS_AUTO_INSTALL='0',
        IPFS_AUTO_INSTALL='false', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    stdout_path, stderr_path = manifest.with_suffix('.owner.stdout'), manifest.with_suffix('.owner.stderr')
    cli = None
    try:
        with stdout_path.open('xb') as out, stderr_path.open('xb') as err:
            cli = subprocess.Popen([sys.executable, '-B', str(launcher), '--request', str(manifest),
                '--expected-request-sha256', _sha(manifest), '--resource-ledger', str(control['ledger'])],
                cwd=launcher.parents[3], env=environment, stdout=out, stderr=err, start_new_session=True)
            identity = native_disk._process(cli.pid)
            assert identity is not None
            cli.wait(timeout=30)
            out.flush(); os.fsync(out.fileno())
            err.flush(); os.fsync(err.fileno())
        assert cli.returncode != 0
        terminal = _json(stdout_path)
        assert terminal['failure']['error_type'] == 'DaemonResourceError'
        assert terminal['failure']['error'] == 'storage reservation capacity exceeded'
        assert control['ledger'].read_bytes() == ledger_before
        assert control['scheduler'].state_path.read_bytes() == scheduler_before
        assert not tuple(attempt.iterdir())
        caller = dict(expected_request_sha256=_sha(manifest), owner_pid=cli.pid,
            owner_birth=identity['birth'], returncode=cli.returncode,
            expected_resource_ledger=str(control['ledger']))
        return module, terminal, manifest.read_bytes(), caller, manifest, attempt
    finally:
        if cli is not None:
            if cli.poll() is None:
                cli.terminate()
                cli.wait(timeout=10)
            _stop_group(cli)


@pytest.mark.parametrize('process_scope', ['isolated_process_group', validation.TRACKED_SCOPE],
    ids=['legacy-no-grant', 'tracked-no-grant'])
def test_actual_cli_pregrant_capacity_refusal_closes_only_source_custody(private_control, process_scope):
    module, terminal, raw, caller, _, _ = _actual_pregrant_capacity_cli(
        private_control, process_scope=process_scope)
    witness, reservation = terminal['source_custody_lifecycle'], terminal['reservation']
    assert witness['schema'] == module.PRE_GRANT_CAPACITY_REFUSAL_SCHEMA
    assert witness['stage'] == 'owner_open_capacity_refused_before_record'
    assert witness['events'] == {key: key == 'owner_open_attempted' for key in module._PRE_GRANT_EVENTS}
    assert witness['native_grant'] == {'status': 'not_requested_capacity_refusal'}
    assert reservation['status'] == 'not_entered'
    assert reservation['record'] is reservation['resource_lease'] is None
    assert witness['capacity_observation']['storage_capacity_exceeded'] is True
    assert terminal['failure']['executed_checks'] == [] and terminal['failure']['returncode'] is None
    assert all(terminal[key] is False for key in ('completed', 'admitted', 'Lean_admitted'))
    assert module.classify_owned_validation_source_custody(terminal, raw, **caller) == {
        'verdict': 'proven_original_no_child_no_native_grant',
        'source_custody_closed': True, 'storage_release_authorized': False}


def test_pregrant_capacity_classifier_keeps_ambiguous_or_forged_terminals_unknown(private_control):
    module, terminal, raw, caller, _, _ = _actual_pregrant_capacity_cli(private_control)
    unknown = {'verdict': 'requires_original_native_cleanup', 'source_custody_closed': False,
        'storage_release_authorized': False}
    for fault in ('missing', 'schema', 'request', 'producer', 'pid', 'birth', 'ledger', 'stage',
            'record', 'record_missing', 'lease', 'lease_missing', 'cleanup', 'cleanup_missing',
            'process_observation', 'open_returned', 'child', 'barrier',
            'event_integer', 'entered', 'native', 'storage_release', 'source_guard', 'guard_integer',
            'capacity_missing', 'capacity_additional', 'capacity_sum', 'capacity_deficit',
            'capacity_bool_integer', 'capacity_no_refusal', 'failure_checks', 'failure_returncode',
            'failure_authority', 'failure_signals'):
        changed = deepcopy(terminal)
        witness = changed['source_custody_lifecycle']
        capacity = witness['capacity_observation']
        if fault == 'missing': changed.pop('source_custody_lifecycle')
        elif fault == 'schema': witness['schema'] += '-foreign'
        elif fault == 'request': witness['request_sha256'] = '0'*64
        elif fault == 'producer': witness['producer']['sha256'] = '0'*64
        elif fault == 'pid': witness['owner']['pid'] += 1
        elif fault == 'birth': witness['owner']['birth'] += '1'
        elif fault == 'ledger': witness['ledger_path'] += '.foreign'
        elif fault == 'stage': witness['stage'] = 'unknown_open_failure'
        elif fault == 'record': changed['reservation']['record'] = {'status': 'retained'}
        elif fault == 'record_missing': changed['reservation'].pop('record')
        elif fault == 'lease': changed['reservation']['resource_lease'] = {'released': True}
        elif fault == 'lease_missing': changed['reservation'].pop('resource_lease')
        elif fault == 'cleanup': changed['reservation']['cleanup_error'] = 'unknown'
        elif fault == 'cleanup_missing': changed['reservation'].pop('cleanup_error')
        elif fault == 'process_observation': changed['reservation']['process_observation'] = {'live_processes': 0}
        elif fault == 'open_returned': witness['events']['owner_open_returned'] = True
        elif fault == 'child': witness['events']['child_launch_attempted'] = True
        elif fault == 'barrier': witness['events']['barrier_released'] = True
        elif fault == 'event_integer': witness['events']['owner_open_attempted'] = 1
        elif fault == 'entered': witness['owner_state']['entered'] = True
        elif fault == 'native': witness['native_grant']['status'] = 'acquired'
        elif fault == 'storage_release': witness['storage']['release_authorized'] = True
        elif fault == 'source_guard': witness['source_guards']['source_pins_unchanged'] = False
        elif fault == 'guard_integer': witness['source_guards']['owner_identity_unchanged'] = 1
        elif fault == 'capacity_missing': witness.pop('capacity_observation')
        elif fault == 'capacity_additional': capacity['additional_requested_bytes'] += 1
        elif fault == 'capacity_sum': capacity['charged_bytes'] += 1
        elif fault == 'capacity_deficit': capacity['storage_capacity_deficit_bytes'] += 1
        elif fault == 'capacity_bool_integer': capacity['storage_capacity_exceeded'] = 1
        elif fault == 'capacity_no_refusal': capacity['storage_capacity_exceeded'] = capacity['filesystem_free_insufficient'] = False
        elif fault == 'failure_checks': changed['failure']['executed_checks'] = ['not a refused check']
        elif fault == 'failure_returncode': changed['failure']['returncode'] = 0
        elif fault == 'failure_authority': changed['failure']['authority_granted'] = True
        else: changed['failure']['received_signals'] = [signal.SIGTERM]
        assert module.classify_owned_validation_source_custody(changed, raw, **caller) == unknown, fault
    assert module.classify_owned_validation_source_custody(None, raw, **caller) == unknown
    assert module.classify_owned_validation_source_custody({}, raw, **caller) == unknown


def test_pregrant_capacity_classifier_rechecks_source_request_and_owner_bindings(private_control):
    module, terminal, raw, caller, _, _ = _actual_pregrant_capacity_cli(private_control)
    for key, value in (('owner_pid', True), ('owner_birth', 'unknown'), ('returncode', 0),
            ('expected_request_sha256', '0'*64),
            ('expected_resource_ledger', str(private_control['ledger'])+'.foreign')):
        assert module.classify_owned_validation_source_custody(terminal, raw,
            **{**caller, key: value})['source_custody_closed'] is False
    for name in module._LIFECYCLE_OWNER_NAMES:
        value = json.loads(raw)
        value['source_sha256'].pop(str(module.ROOT/'ipfs_datasets_py/optimizers/logic_theorem_optimizer'/name))
        altered = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
        pin = hashlib.sha256(altered).hexdigest()
        changed = deepcopy(terminal)
        changed['request_sha256'] = changed['source_custody_lifecycle']['request_sha256'] = pin
        changed['failure']['request_sha256'] = pin
        assert module.classify_owned_validation_source_custody(changed, altered,
            **{**caller, 'expected_request_sha256': pin})['source_custody_closed'] is False
    source = private_control['source']
    before = source.read_bytes()
    try:
        source.write_bytes(before+b'\n# source drift after refused original owner\n')
        assert module.classify_owned_validation_source_custody(terminal, raw, **caller)['source_custody_closed'] is False
    finally:
        source.write_bytes(before)
    assert module.classify_owned_validation_source_custody(terminal, raw, **caller)['source_custody_closed'] is True


def test_pregrant_capacity_builder_requires_real_original_open_and_account_frames(private_control):
    module, _, _, manifest, request, kwargs = _prepare_pregrant_capacity(private_control)
    owner = _owner(private_control, kwargs)
    events = {key: key == 'owner_open_attempted' for key in module._PRE_GRANT_EVENTS}
    with pytest.raises(native_disk.DaemonResourceError) as caught:
        owner.open()
    original = caught.value
    copied = native_disk.DaemonResourceError(str(original))
    copied._capacity_observation = original.capacity_observation
    class SubclassCapacityError(native_disk.DaemonResourceError):
        pass
    subclass = SubclassCapacityError(str(original))
    subclass._capacity_observation = original.capacity_observation
    outcome = dict(schema='owned-validation-result/v1', request_sha256=_sha(manifest),
        completed=False, executed_checks=[], returncode=None, admitted=False, Lean_admitted=False,
        authority_granted=False, model_weights_downloaded=False, error_type='DaemonResourceError',
        error=str(original), watchdog_errors=[], received_signals=[])
    for error in (RuntimeError(str(original)), copied, subclass):
        assert module._pre_grant_capacity_refusal_terminal(owner, request, manifest.read_bytes(),
            manifest, _sha(manifest), private_control['ledger'], events, error, outcome) is None
    assert _json(private_control['ledger'])['reservations'] == {'foreign-retained': private_control['foreign']}


def test_pregrant_capacity_builder_cannot_reclassify_an_actual_postgrant_failure(private_control):
    module, _, _, manifest, request, kwargs = _prepare_no_child_lifecycle(private_control)
    owner = _owner(private_control, kwargs)
    try:
        owner.open()
        assert owner._lease is not None and owner._record is not None
        ledger = _json(private_control['ledger'])
        private_control['foreign']['storage_bytes'] = native_disk.MAX_STORAGE_BYTES
        ledger['reservations']['foreign-retained'] = deepcopy(private_control['foreign'])
        _write_json(private_control['ledger'], ledger)
        with pytest.raises(native_disk.DaemonResourceError) as caught:
            owner.check_limits(full=True)
        events = {key: key == 'owner_open_attempted' for key in module._PRE_GRANT_EVENTS}
        assert module._pre_grant_capacity_refusal_terminal(owner, request, manifest.read_bytes(),
            manifest, _sha(manifest), private_control['ledger'], events, caught.value, {}) is None
    finally:
        owner.__exit__(RuntimeError, RuntimeError('post-grant capacity remains original retained custody'), None)
    assert _json(private_control['ledger'])['reservations'][owner.reservation_id]['status'] == 'retained'


# These tests exercise only the candidate's read-only sampler over real owned
# files and held directory descriptors. They do not construct/open a candidate
# resource owner, create a native scheduler, or grant candidate custody. The
# original outer owned-validation process retains all actual admission authority.
_ORDINARY_SAMPLER_NODE = "read-only ordinary sampler fixture"


def _ordinary_sampler_view(tmp_path):
    from types import SimpleNamespace
    directory = tmp_path / "ordinary-sampler"
    directory.mkdir(mode=0o700)
    outputs = {name: directory / name for name in validation.OUTPUT_NAMES}
    for path in outputs.values():
        path.mkdir(mode=0o700)
    root = outputs["tmp"] / "physical-fixtures"
    root.mkdir(mode=0o700)
    case = root / hashlib.sha256(_ORDINARY_SAMPLER_NODE.encode()).hexdigest()
    case.mkdir(mode=0o700)
    identity = lambda path: (path.lstat().st_dev, path.lstat().st_ino,
                             path.lstat().st_uid, path.lstat().st_mode)
    view = SimpleNamespace(directory=directory, output_layout=outputs,
        _physical_active=True,
        _physical_profile={"schema": validation.PHYSICAL_FIXTURE_SCHEMA,
                           "root": str(root), "cases": [{"nodeid": _ORDINARY_SAMPLER_NODE,
                           "entries": [_physical_core_entry()]}]},
        _physical_cases={_ORDINARY_SAMPLER_NODE: case},
        _physical_identities={root: identity(root), case: identity(case)},
        _physical_entries={str((case / "alias").relative_to(directory)):
                           dict(_physical_core_entry(), case_path=case)})
    scratch = case / "scratch"
    scratch.mkdir(mode=0o700)
    return view, case, scratch


def _sample_ordinary_view(view):
    return validation.ValidationResourceReservation._physical_inventory(view)


def _same_parent_descriptor(descriptor, path):
    if descriptor is None:
        return False
    opened, expected = os.fstat(descriptor), path.lstat()
    return (opened.st_dev, opened.st_ino) == (expected.st_dev, expected.st_ino)


def _on_ordinary_stat(monkeypatch, victim, boundary, action):
    """Act at an exact real anchored lstat boundary; never fake disappearance."""
    original = os.stat
    parent_info = victim.parent.lstat()
    calls = []
    def wrapped(path, *args, **options):
        descriptor = options.get("dir_fd")
        if path == victim.name and descriptor is not None:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) == (parent_info.st_dev, parent_info.st_ino):
                turn = len(calls); calls.append(turn)
                if turn == boundary:
                    action()
        return original(path, *args, **options)
    monkeypatch.setattr(os, "stat", wrapped)
    return calls


def _after_ordinary_first_lstat(monkeypatch, victim, action):
    original = os.stat
    parent_info = victim.parent.lstat()
    seen = []
    def wrapped(path, *args, **options):
        result = original(path, *args, **options)
        descriptor = options.get("dir_fd")
        if path == victim.name and descriptor is not None and not seen:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) == (parent_info.st_dev, parent_info.st_ino):
                seen.append(result)
                action()
        return result
    monkeypatch.setattr(os, "stat", wrapped)
    return seen


def test_ordinary_file_disappearance_keeps_last_observed_bytes(tmp_path, monkeypatch):
    view, _, scratch = _ordinary_sampler_view(tmp_path)
    before = _sample_ordinary_view(view)
    victim = scratch / "index.lock"
    payload = b"real private Git lock payload\n"
    victim.write_bytes(payload)
    seen = _after_ordinary_first_lstat(monkeypatch, victim, victim.unlink)
    sampled = _sample_ordinary_view(view)
    assert len(seen) == 1 and not victim.exists()
    assert sampled["apparent_bytes"] == before["apparent_bytes"] + len(payload)
    assert sampled["entry_count"] == before["entry_count"] + 1


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_ordinary_entry_disappearing_after_readdir_is_bounded(tmp_path, monkeypatch, kind):
    from contextlib import contextmanager
    view, _, scratch = _ordinary_sampler_view(tmp_path)
    before = _sample_ordinary_view(view)
    victim = scratch / "ephemeral"
    victim.write_bytes(b"gone before first lstat") if kind == "file" else victim.mkdir(mode=0o700)
    original = os.scandir
    removed = []
    @contextmanager
    def scan(descriptor):
        with original(descriptor) as entries:
            def values():
                for entry in entries:
                    if entry.name == victim.name and _same_parent_descriptor(descriptor, scratch) and not removed:
                        victim.unlink() if kind == "file" else victim.rmdir()
                        removed.append(True)
                    yield entry
            yield values()
    monkeypatch.setattr(os, "scandir", scan)
    sampled = _sample_ordinary_view(view)
    assert removed == [True] and not victim.exists()
    # No metadata size was observed before disappearance; none is invented.
    assert sampled["apparent_bytes"] == before["apparent_bytes"]
    assert sampled["entry_count"] == before["entry_count"] + 1


@pytest.mark.parametrize("boundary", ["before_open", "after_open", "after_walk"])
def test_ordinary_directory_cleanup_preserves_observed_charge(tmp_path, monkeypatch, boundary):
    view, _, scratch = _ordinary_sampler_view(tmp_path)
    before = _sample_ordinary_view(view)
    victim = scratch / "removed-directory"
    victim.mkdir(mode=0o700)
    payload = b"observed before the directory was removed\n"
    leaf = victim / "payload.bin"
    if boundary == "after_walk":
        leaf.write_bytes(payload)
        def remove():
            leaf.unlink(); victim.rmdir()
        seen = _on_ordinary_stat(monkeypatch, victim, 2, remove)
    else:
        original = os.open
        parent_info = scratch.lstat()
        seen = []
        def opened(path, flags, *args, **options):
            descriptor = options.get("dir_fd")
            match = (path == victim.name and descriptor is not None
                and (os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino) ==
                    (parent_info.st_dev, parent_info.st_ino) and not seen)
            if match and boundary == "before_open":
                victim.rmdir(); seen.append(True)
            result = original(path, flags, *args, **options)
            if match and boundary == "after_open":
                victim.rmdir(); seen.append(True)
            return result
        monkeypatch.setattr(os, "open", opened)
    sampled = _sample_ordinary_view(view)
    assert seen and not victim.exists()
    assert sampled["apparent_bytes"] == before["apparent_bytes"] + (len(payload) if boundary == "after_walk" else 0)
    assert sampled["entry_count"] == before["entry_count"] + (2 if boundary == "after_walk" else 1)


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_ordinary_reappearance_after_real_unlink_is_refused(tmp_path, monkeypatch, kind):
    view, _, scratch = _ordinary_sampler_view(tmp_path)
    victim = scratch / "reappeared"
    victim.write_bytes(b"original") if kind == "file" else victim.mkdir(mode=0o700)
    def disappear():
        victim.unlink() if kind == "file" else victim.rmdir()
    _after_ordinary_first_lstat(monkeypatch, victim, disappear)
    # A different wrapper creates the actual replacement on the missing check.
    original = os.stat
    created = []
    def reappear(path, *args, **options):
        try:
            return original(path, *args, **options)
        except FileNotFoundError:
            if path == victim.name and options.get("dir_fd") is not None and not created:
                victim.write_bytes(b"replacement") if kind == "file" else victim.mkdir(mode=0o700)
                created.append(True)
            raise
    monkeypatch.setattr(os, "stat", reappear)
    with pytest.raises(validation.ValidationResourceError, match="reappeared|identity|binding"):
        _sample_ordinary_view(view)
    assert created == [True] and victim.exists()


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_ordinary_real_inode_replacement_is_refused(tmp_path, monkeypatch, kind):
    view, _, scratch = _ordinary_sampler_view(tmp_path)
    victim = scratch / "substituted"
    saved = scratch / "retained-original"
    victim.write_bytes(b"same") if kind == "file" else victim.mkdir(mode=0o700)
    first = victim.lstat()
    def replace():
        victim.rename(saved)
        victim.write_bytes(b"same") if kind == "file" else victim.mkdir(mode=0o700)
        assert victim.lstat().st_ino != first.st_ino
    seen = _after_ordinary_first_lstat(monkeypatch, victim, replace)
    with pytest.raises(validation.ValidationResourceError, match="identity|binding"):
        _sample_ordinary_view(view)
    assert len(seen) == 1 and saved.exists()


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_ordinary_actual_symlink_is_never_followed(tmp_path, monkeypatch, kind):
    view, _, scratch = _ordinary_sampler_view(tmp_path)
    victim, target = scratch / "aliased", scratch / "real-target"
    target.write_bytes(b"untouched target") if kind == "file" else target.mkdir(mode=0o700)
    victim.symlink_to(target)
    created = victim.lstat()
    original_open = os.open
    followed = []
    def no_follow(path, flags, *args, **options):
        if path == victim.name and options.get("dir_fd") is not None:
            followed.append(True)
            raise AssertionError("ordinary symlink must be refused before opening")
        return original_open(path, flags, *args, **options)
    monkeypatch.setattr(os, "open", no_follow)
    try:
        with pytest.raises(validation.ValidationResourceError, match="regular"):
            _sample_ordinary_view(view)
        assert victim.is_symlink() and followed == []
    finally:
        if victim.is_symlink():
            current = victim.lstat()
            assert (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino)
            assert os.readlink(victim) == str(target)
            victim.unlink()
    assert target.read_bytes() == b"untouched target" if kind == "file" else target.is_dir()


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_ordinary_kind_substitution_is_refused(tmp_path, monkeypatch, kind):
    view, _, scratch = _ordinary_sampler_view(tmp_path)
    victim, saved = scratch / "changed-kind", scratch / "retained-original"
    victim.write_bytes(b"regular") if kind == "file" else victim.mkdir(mode=0o700)
    def replace():
        victim.rename(saved)
        victim.mkdir(mode=0o700) if kind == "file" else victim.write_bytes(b"regular")
    _after_ordinary_first_lstat(monkeypatch, victim, replace)
    with pytest.raises((validation.ValidationResourceError, OSError)):
        _sample_ordinary_view(view)
    assert saved.exists()


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_ordinary_foreign_uid_observation_is_refused(tmp_path, monkeypatch, kind):
    """Fault-inject a UID observation; no claim of privileged real chown."""
    view, _, scratch = _ordinary_sampler_view(tmp_path)
    victim = scratch / "foreign-uid"
    victim.write_bytes(b"owned") if kind == "file" else victim.mkdir(mode=0o700)
    original = os.stat
    observed = []
    def foreign_uid(path, *args, **options):
        result = original(path, *args, **options)
        if path == victim.name and options.get("dir_fd") is not None:
            values = list(result); values[4] = os.geteuid() + 1
            observed.append(True)
            return os.stat_result(values)
        return result
    monkeypatch.setattr(os, "stat", foreign_uid)
    with pytest.raises(validation.ValidationResourceError, match="owned|identity"):
        _sample_ordinary_view(view)
    assert observed and victim.lstat().st_uid == os.geteuid()


@pytest.mark.parametrize("kind,start,end", [
    ("file", 0o400, 0o600), ("file", 0o600, 0o400),
    ("directory", 0o500, 0o700), ("directory", 0o700, 0o500),
], ids=["file-readonly-to-owner-write", "file-owner-write-to-readonly",
        "directory-sealed-to-owner-cleanup", "directory-owner-cleanup-to-sealed"])
def test_ordinary_real_owner_cleanup_permission_transition(tmp_path, monkeypatch, kind, start, end):
    view, _, scratch = _ordinary_sampler_view(tmp_path)
    victim = scratch / "owner-mode"
    victim.write_bytes(b"unchanged body") if kind == "file" else victim.mkdir(mode=0o700)
    victim.chmod(start)
    first = victim.lstat()
    seen = _after_ordinary_first_lstat(monkeypatch, victim, lambda: victim.chmod(end))
    sampled = _sample_ordinary_view(view)
    after = victim.lstat()
    assert len(seen) == 1 and (first.st_dev, first.st_ino, first.st_uid) == (after.st_dev, after.st_ino, after.st_uid)
    assert stat.S_IMODE(after.st_mode) == end and sampled["apparent_bytes"] == (len(b"unchanged body") if kind == "file" else 0)
    victim.chmod(0o700 if kind == "directory" else 0o600)


@pytest.mark.parametrize("kind,added", [("file", 0o040), ("file", 0o020), ("file", 0o004),
                                        ("directory", 0o040), ("directory", 0o020), ("directory", 0o002)],
                         ids=["file-group-read", "file-group-write", "file-other-read",
                              "directory-group-read", "directory-group-write", "directory-other-write"])
def test_ordinary_nonowner_permission_transition_is_refused(tmp_path, monkeypatch, kind, added):
    view, _, scratch = _ordinary_sampler_view(tmp_path)
    victim = scratch / "nonowner-mode"
    victim.write_bytes(b"owned") if kind == "file" else victim.mkdir(mode=0o700)
    victim.chmod(0o600 if kind == "file" else 0o700)
    _after_ordinary_first_lstat(monkeypatch, victim, lambda: victim.chmod((0o600 if kind == "file" else 0o700) | added))
    try:
        with pytest.raises(validation.ValidationResourceError, match="nonowner|owned|nonwritable"):
            _sample_ordinary_view(view)
    finally:
        victim.chmod(0o600 if kind == "file" else 0o700)


@pytest.mark.parametrize("which", ["physical-root", "case", "output"])
def test_ordinary_cleanup_does_not_relax_protected_directory_mode(tmp_path, monkeypatch, which):
    view, case, _ = _ordinary_sampler_view(tmp_path)
    victim = Path(view._physical_profile["root"]) if which == "physical-root" else case if which == "case" else view.output_layout["exports"]
    _after_ordinary_first_lstat(monkeypatch, victim, lambda: victim.chmod(0o500))
    try:
        with pytest.raises(validation.ValidationResourceError, match="identity|binding"):
            _sample_ordinary_view(view)
    finally:
        victim.chmod(0o700)


@pytest.mark.parametrize("which", ["physical-root", "case", "output"])
def test_ordinary_cleanup_does_not_relax_protected_directory_inode(tmp_path, monkeypatch, which):
    view, case, _ = _ordinary_sampler_view(tmp_path)
    victim = Path(view._physical_profile["root"]) if which == "physical-root" else case if which == "case" else view.output_layout["exports"]
    saved = victim.with_name(victim.name + "-retained")
    def replace():
        victim.rename(saved); victim.mkdir(mode=0o700)
    _after_ordinary_first_lstat(monkeypatch, victim, replace)
    try:
        with pytest.raises(validation.ValidationResourceError, match="identity|binding"):
            _sample_ordinary_view(view)
    finally:
        if saved.exists():
            victim.rmdir(); saved.rename(victim)


# Explicit session factory adapter; existing tmp_path and physical-v2 assertions
# above remain unchanged. These tests retain only ordinary files/directories.
def _ordinary_session_test_factory(base):
    base.mkdir(mode=0o700)
    return pytest.TempPathFactory(given_basetemp=None, retention_count=3,
        retention_policy="all", trace=lambda *args: None, basetemp=base, _ispytest=True)


def test_ordinary_session_factory_retains_unique_private_directories(tmp_path):
    plugin = _physical_pytest_plugin()
    base = tmp_path / "ordinary-factory"
    original = _ordinary_session_test_factory(base)
    factory = plugin._OrdinaryTempPathFactory(original, base)
    assert factory.getbasetemp() is original.getbasetemp()
    paths = [factory.mktemp("typed-source-response-inputs") for _ in range(3)]
    for index, path in enumerate(paths):
        (path / "retained.json").write_text(json.dumps({"index": index}))
    assert len(set(paths)) == 3
    assert set(base.iterdir()) == set(paths)
    for index, path in enumerate(paths):
        assert path.parent == base and path.is_dir() and not path.is_symlink()
        assert stat.S_IMODE(path.lstat().st_mode) == 0o700
        assert json.loads((path / "retained.json").read_bytes()) == {"index": index}
    assert all(not path.is_symlink() for path in base.rglob("*"))


@pytest.mark.parametrize("basename", ["../escape", "..", ".", "", "nested/escape", "/escape"])
def test_ordinary_session_factory_refuses_original_basename_escapes_before_allocation(tmp_path, basename):
    plugin = _physical_pytest_plugin()
    base = tmp_path / "ordinary-factory"
    original = _ordinary_session_test_factory(base)
    factory = plugin._OrdinaryTempPathFactory(original, base)
    with pytest.raises(ValueError, match="normalized and relative path"):
        factory.mktemp(basename)
    assert list(base.iterdir()) == []


def test_ordinary_session_factory_preserves_original_basename_normalization(tmp_path):
    plugin = _physical_pytest_plugin()
    base = tmp_path / "ordinary-factory"
    original = _ordinary_session_test_factory(base)
    factory = plugin._OrdinaryTempPathFactory(original, base)
    path = factory.mktemp("unused/../retained")
    assert path.parent == base and path.name.startswith("retained-")
    assert sorted(base.iterdir()) == [path]
    assert not (base / "unused").exists()


def test_ordinary_session_factory_unnumbered_retains_original_path_and_duplicate_refusal(tmp_path):
    plugin = _physical_pytest_plugin()
    base = tmp_path / "ordinary-factory"
    original = _ordinary_session_test_factory(base)
    factory = plugin._OrdinaryTempPathFactory(original, base)
    path = factory.mktemp("unnumbered", numbered=False)
    assert path == base / "unnumbered"
    (path / "evidence.bin").write_bytes(b"unchanged original unnumbered directory")
    with pytest.raises(FileExistsError):
        factory.mktemp("unnumbered", numbered=False)
    assert sorted(base.iterdir()) == [path]
    assert (path / "evidence.bin").read_bytes() == b"unchanged original unnumbered directory"


def test_ordinary_session_factory_delegates_getbasetemp_and_unnumbered_exactly(tmp_path):
    from types import SimpleNamespace

    plugin = _physical_pytest_plugin()
    calls, base_result, path_result = [], object(), object()
    def original_getbasetemp():
        calls.append(("getbasetemp",))
        return base_result
    def original_mktemp(basename, numbered=True):
        calls.append(("mktemp", basename, numbered))
        return path_result
    original = SimpleNamespace(getbasetemp=original_getbasetemp, mktemp=original_mktemp)
    factory = plugin._OrdinaryTempPathFactory(original, tmp_path)
    assert calls == []
    assert factory.getbasetemp() is base_result
    assert factory.mktemp("original-basename", numbered=False) is path_result
    assert calls == [("getbasetemp",), ("mktemp", "original-basename", False)]


@pytest.mark.parametrize("configured", [None, "relative", "relative/../base", "/absolute/../base"])
def test_ordinary_session_factory_refuses_unowned_base_before_touching_original(configured):
    from types import SimpleNamespace

    plugin = _physical_pytest_plugin()
    def untouched():
        pytest.fail("invalid profile must not initialize or clear pytest's basetemp")
    original = SimpleNamespace(getbasetemp=untouched)
    with pytest.raises(pytest.UsageError, match="explicit absolute --basetemp"):
        plugin._OrdinaryTempPathFactory(original, configured)


@pytest.mark.parametrize("damage", ["different-base", "shared-base-mode"])
def test_ordinary_session_factory_refuses_changed_base_without_repair_or_allocation(tmp_path, damage):
    plugin = _physical_pytest_plugin()
    base = tmp_path / "ordinary-factory"
    original = _ordinary_session_test_factory(base)
    retained = base / "retained.bin"
    retained.write_bytes(b"preserved original fixture evidence")
    configured = tmp_path / "different-base" if damage == "different-base" else base
    if damage == "shared-base-mode":
        base.chmod(0o755)
    factory = plugin._OrdinaryTempPathFactory(original, configured)
    with pytest.raises(pytest.UsageError, match="exact absolute basetemp|private owned basetemp"):
        factory.mktemp("must-not-allocate")
    assert sorted(base.iterdir()) == [retained]
    assert retained.read_bytes() == b"preserved original fixture evidence"
    assert stat.S_IMODE(base.lstat().st_mode) == (0o755 if damage == "shared-base-mode" else 0o700)


@pytest.mark.parametrize("enabled", [False, True])
def test_ordinary_session_factory_actual_cold_pytest_preserves_default_and_tmp_path(tmp_path, enabled):
    plugin_name = "ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_pytest"
    package_root = Path(validation.__file__).resolve().parents[3]
    plugin_source = Path(validation.__file__).resolve().with_name("validation_pytest.py")
    base = tmp_path / "cold-ordinary-factory"
    inner_test = tmp_path / "test_actual_session_factory.py"
    inner_test.write_text(
        "from pathlib import Path\n"
        "import json, stat\n"
        "import pytest\n"
        + "ENABLED = " + repr(enabled) + "\n"
        + "BASE = Path(" + repr(str(base)) + ")\n"
        "@pytest.fixture(scope='session')\n"
        "def retained_inputs(tmp_path_factory):\n"
        "    assert tmp_path_factory.getbasetemp() == BASE\n"
        "    paths = ([tmp_path_factory.mktemp('typed-source-response-inputs') for _ in range(3)]\n"
        "             if ENABLED else [tmp_path_factory.mktemp('ordinary-default', numbered=False)])\n"
        "    assert len(set(paths)) == len(paths)\n"
        "    for index, path in enumerate(paths):\n"
        "        assert path.parent == BASE and not path.is_symlink()\n"
        "        assert stat.S_IMODE(path.lstat().st_mode) == 0o700\n"
        "        (path / 'retained.json').write_text(json.dumps({'index': index}))\n"
        "    return paths\n"
        "def test_session_factory(request, tmp_path_factory, tmp_path, retained_inputs):\n"
        + "    plugin = request.config.pluginmanager.getplugin(" + repr(plugin_name) + ")\n"
        + "    assert Path(plugin.__file__).resolve() == Path(" + repr(str(plugin_source)) + ")\n"
        "    assert (tmp_path_factory is request.config._tmp_path_factory) is (not ENABLED)\n"
        "    assert tmp_path.parent == BASE and not tmp_path.is_symlink()\n"
        "    assert stat.S_IMODE(tmp_path.lstat().st_mode) == 0o700\n"
        "    for index, path in enumerate(retained_inputs):\n"
        "        assert json.loads((path / 'retained.json').read_bytes()) == {'index': index}\n"
        "    assert all(not path.is_symlink() for path in BASE.rglob('*'))\n")
    environment = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1",
        IPFS_DATASETS_PY_MINIMAL_IMPORTS="1", IPFS_DATASETS_AUTO_INSTALL="0", IPFS_AUTO_INSTALL="false",
        PYTHONPATH=os.pathsep.join([str(package_root), os.environ.get("PYTHONPATH", "")]))
    environment.pop("IPFS_DATASETS_OWNED_VALIDATION_REQUEST", None)
    environment.pop("IPFS_DATASETS_OWNED_VALIDATION_REQUEST_SHA256", None)
    argv = [sys.executable, "-B", "-m", "pytest", "-q", "-c", "/dev/null", "--noconftest",
        "-p", plugin_name, "-p", "no:cacheprovider", "--basetemp", str(base)]
    if enabled:
        argv.append("--owned-ordinary-temp-factory")
    result = subprocess.run([*argv, str(inner_test)], cwd=tmp_path, env=environment,
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
    assert all(not path.is_symlink() for path in base.rglob("*"))
    assert len(list(base.glob("*/retained.json"))) == (3 if enabled else 1)


# Versioned live-census owner regressions. All native state is the existing
# private_control fixture; these checks create no child process or host grant.
def _live_census_prepare(control, **kwargs):
    def enable(value):
        value["schema"] = validation.LIVE_REQUEST_SCHEMA
        value["live_inventory_profile"] = {
            "schema": validation.LIVE_INVENTORY_SCHEMA, "max_complete_resamples": 1}
    return control["prepare"](mutate=enable, **kwargs)


def _live_census_publication(monkeypatch, owned, boundary, **kwargs):
    from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_daemon_resources import _atomic_census_publication
    return _atomic_census_publication(monkeypatch, native_disk,
                                     owned.output_layout["tmp"], boundary, **kwargs)


def _observe_live_census_calls(monkeypatch, owned, *, after_completed=None):
    actual = native_disk._inventory
    calls, partials = [], []
    def inventory(roots, **kwargs):
        selected = list(roots) == [owned.directory]
        if selected:
            calls.append(dict(kwargs))
        try:
            value = actual(roots, **kwargs)
        except native_disk.OwnedInventoryDisappearance as event:
            if selected:
                partials.append(event.partial_inventory)
            raise
        if selected and after_completed is not None:
            after_completed(len(calls))
        return value
    monkeypatch.setattr(native_disk, "_inventory", inventory)
    return calls, partials


@pytest.mark.parametrize("boundary", ["pending", "scandir"])
def test_live_census_v4_restarts_one_complete_strict_scan(private_control, monkeypatch, boundary):
    c = private_control
    attempt, _, _, kwargs = _live_census_prepare(c)
    with _owner(c, kwargs) as owned:
        state = _live_census_publication(monkeypatch, owned, boundary)
        calls, partials = _observe_live_census_calls(monkeypatch, owned)
        observed = owned._usage_inventory(attempt)
        assert calls == [{"strict": True, "report_owned_disappearance": True}] * 2
        assert len(partials) == 1 and state["publications"] == 1
        assert observed["apparent_bytes"] == state["payload_bytes"]
        assert observed["entry_count"] >= partials[0]["entry_count"]
        assert observed["symlink_count"] == observed["special_file_count"] == 0
        assert (state["current"] / "nested/payload.txt").read_bytes() == b"formal source payload\n" * 5
    row = _json(c["ledger"])["reservations"][owned.reservation_id]
    assert row["status"] == "retained" and row["storage_bytes"] == kwargs["storage_bytes"]


def test_live_census_v4_preserves_larger_partial_byte_highwater(private_control, monkeypatch):
    c = private_control
    attempt, _, _, kwargs = _live_census_prepare(c, storage_bytes=10_000)
    with _owner(c, kwargs) as owned:
        temporary = owned.output_layout["tmp"] / "observed-before-publication"
        temporary.write_bytes(b"x" * 8000)
        state = _live_census_publication(monkeypatch, owned, "pending", before_publish=temporary.unlink)
        calls, partials = _observe_live_census_calls(monkeypatch, owned)
        observed = owned._usage_inventory(attempt)
        assert len(calls) == 2 and len(partials) == 1
        assert partials[0]["apparent_bytes"] == 8000
        assert observed["apparent_bytes"] == 8000 > state["payload_bytes"]
        assert native_disk._inventory([attempt], strict=True)["apparent_bytes"] == state["payload_bytes"]


def test_live_census_v4_repeated_publication_exhausts_one_resample(private_control, monkeypatch):
    c = private_control
    attempt, _, _, kwargs = _live_census_prepare(c)
    with _owner(c, kwargs) as owned:
        state = _live_census_publication(monkeypatch, owned, "pending", publications=2)
        calls, partials = _observe_live_census_calls(monkeypatch, owned)
        with pytest.raises(validation.ValidationResourceError, match="resample exhausted"):
            owned._usage_inventory(attempt)
        assert len(calls) == len(partials) == state["publications"] == 2
        assert (state["current"] / "nested/payload.txt").is_file()
    assert _json(c["ledger"])["reservations"][owned.reservation_id]["status"] == "retained"


def test_live_census_v4_oversized_partial_fails_before_any_resample(private_control, monkeypatch):
    c = private_control
    attempt, _, _, kwargs = _live_census_prepare(c, storage_bytes=1024)
    with _owner(c, kwargs) as owned:
        temporary = owned.output_layout["tmp"] / "oversized-before-publication"
        temporary.write_bytes(b"x" * 2048)
        _live_census_publication(monkeypatch, owned, "pending", before_publish=temporary.unlink)
        calls, partials = _observe_live_census_calls(monkeypatch, owned)
        with pytest.raises(validation.ValidationResourceError, match="aggregate storage"):
            owned._usage_inventory(attempt)
        assert len(calls) == len(partials) == 1
        assert partials[0]["apparent_bytes"] == 2048
    row = _json(c["ledger"])["reservations"][owned.reservation_id]
    assert row["status"] == "retained" and row["storage_bytes"] == 1024


@pytest.mark.parametrize("boundary", ["before", "after-partial", "after-complete"])
def test_live_census_v4_deadline_guards_each_traversal(private_control, monkeypatch, boundary):
    c = private_control
    attempt, _, _, kwargs = _live_census_prepare(c)
    with _owner(c, kwargs) as owned:
        def expire():
            owned._started -= owned.validation_timeout_seconds + 1
        state = _live_census_publication(monkeypatch, owned, "pending",
            before_publish=expire if boundary == "after-partial" else None)
        calls, partials = _observe_live_census_calls(monkeypatch, owned,
            after_completed=(lambda count: expire()) if boundary == "after-complete" else None)
        if boundary == "before":
            expire()
        with pytest.raises(validation.ValidationResourceError, match="deadline"):
            owned._usage_inventory(attempt)
        assert len(calls) == {"before": 0, "after-partial": 1, "after-complete": 2}[boundary]
        assert state["publications"] == (0 if boundary == "before" else 1)


@pytest.mark.parametrize("fault", ["unversioned", "missing", "false", "bool-limit", "two-resamples"])
def test_live_census_profile_requires_exact_versioned_optin_before_admission(private_control, fault):
    c = private_control
    def mutate(value):
        value["schema"] = validation.LIVE_REQUEST_SCHEMA
        value["live_inventory_profile"] = {
            "schema": validation.LIVE_INVENTORY_SCHEMA, "max_complete_resamples": 1}
        if fault == "unversioned":
            value["schema"] = "owned-validation-request/v1"
        elif fault == "missing":
            del value["live_inventory_profile"]
        elif fault == "false":
            value["live_inventory_profile"] = False
        elif fault == "bool-limit":
            value["live_inventory_profile"]["max_complete_resamples"] = True
        else:
            value["live_inventory_profile"]["max_complete_resamples"] = 2
    _, _, _, kwargs = c["prepare"](mutate=mutate)
    ledger_before = c["ledger"].read_bytes()
    state_before = c["scheduler"].state_path.read_bytes()
    with pytest.raises(validation.ValidationResourceError, match="schema|profile"):
        _owner(c, kwargs)
    assert c["ledger"].read_bytes() == ledger_before
    assert c["scheduler"].state_path.read_bytes() == state_before


@pytest.mark.parametrize("schema", ["owned-validation-request/v1", "owned-validation-request/v2", "owned-validation-request/v4"], ids=["v1", "v2", "v4"])
def test_live_census_launcher_reads_frozen_supported_request_bytes(tmp_path, schema):
    module, launcher = _lifecycle_launcher_module()
    root = Path(__file__).resolve().parents[4]
    assert launcher == root / "scripts/ops/legal_ir/run_owned_validation.py"
    assert module.ROOT == root
    path = tmp_path / "frozen-request.json"
    raw = (json.dumps({"schema": schema, "selected_checks": ["private protocol fixture"]}) + "\n").encode()
    path.write_bytes(raw)
    parsed, observed = module.request(path, hashlib.sha256(raw).hexdigest())
    assert observed == raw and parsed == json.loads(raw)


@pytest.mark.parametrize("fault", ["external-v3", "unknown-version", "wrong-hash"])
def test_live_census_launcher_refuses_unrecognized_or_changed_request(tmp_path, fault):
    module, _ = _lifecycle_launcher_module()
    path = tmp_path / "request.json"
    raw = json.dumps({"schema": {"external-v3": "owned-validation-request/v3", "unknown-version": "owned-validation-request/v9"}.get(fault, validation.LIVE_REQUEST_SCHEMA)}).encode()
    path.write_bytes(raw)
    digest = "0" * 64 if fault == "wrong-hash" else hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="unsupported|hash differs"):
        module.request(path, digest)


def test_live_census_v4_does_not_extend_no_child_custody_classifier(tmp_path, monkeypatch):
    module, _ = _lifecycle_launcher_module()
    raw = json.dumps({"schema": validation.LIVE_REQUEST_SCHEMA}).encode()
    path_calls = []
    actual_path = module.Path
    def recorded_path(value):
        path_calls.append(value)
        return actual_path(value)
    monkeypatch.setattr(module, "Path", recorded_path)
    verdict = module.classify_owned_validation_source_custody({}, raw,
        expected_request_sha256=hashlib.sha256(raw).hexdigest(), owner_pid=os.getpid(),
        owner_birth="1", returncode=1, expected_resource_ledger=str(tmp_path / "unopened-ledger.json"))
    assert verdict == {"verdict": "requires_original_native_cleanup", "source_custody_closed": False,
                       "storage_release_authorized": False}
    assert path_calls == []



@pytest.mark.parametrize("kind", ["symlink-file", "symlink-directory", "fifo"])
def test_live_census_v4_rejects_declared_unsafe_leaf_without_resample(private_control, monkeypatch, kind):
    c = private_control
    attempt, _, _, kwargs = _live_census_prepare(c)
    assert attempt == c["root"] / "attempt-0"
    payload = b"retained ordinary payload\n"
    with _owner(c, kwargs) as owned:
        directory = owned.output_layout["tmp"]
        leaf = directory / "unsafe-leaf"
        if kind == "symlink-directory":
            target = directory / "retained-target-directory"
            target.mkdir(mode=0o700)
            retained = target / "payload.txt"
        else:
            target = directory / ("retained-target-file" if kind == "symlink-file" else "retained-payload.txt")
            retained = target
        retained.write_bytes(payload)
        assert not os.path.lexists(leaf)
        calls, partials = _observe_live_census_calls(monkeypatch, owned)
        original_resamples = owned._live_inventory_resamples
        try:
            if kind == "fifo":
                os.mkfifo(leaf, 0o600)
            else:
                leaf.symlink_to(target.absolute(), target_is_directory=kind == "symlink-directory")
            with pytest.raises(native_disk.DaemonResourceError, match="symlink|nonregular") as caught:
                owned._usage_inventory(attempt)
            assert not isinstance(caught.value, native_disk.OwnedInventoryDisappearance)
            # Exactly the explicit sample is observed; no strict retry follows
            # an alias or special entry. Native fixture exit is a separate step.
            assert calls == [{"strict": True, "report_owned_disappearance": True}]
            assert partials == [] and owned._live_inventory_resamples == original_resamples
            assert retained.read_bytes() == payload
        finally:
            leaf.unlink(missing_ok=True)
        assert not os.path.lexists(leaf) and retained.read_bytes() == payload
    row = _json(c["ledger"])["reservations"][owned.reservation_id]
    assert row["status"] == "retained" and row["storage_bytes"] == kwargs["storage_bytes"]
    assert retained.read_bytes() == payload


# Revised V4 live window controls. The original39 history is not reclassified.
def test_live_census_v4_first_stat_unknown_leaf_failure_never_resamples(private_control, monkeypatch):
    from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_daemon_resources import _owned_live_unobserved_leaf_disappearance
    c = private_control
    attempt, _, _, kwargs = _live_census_prepare(c)
    with _owner(c, kwargs) as owned:
        target, removed = _owned_live_unobserved_leaf_disappearance(monkeypatch, native_disk, owned.output_layout["tmp"])
        calls, partials = _observe_live_census_calls(monkeypatch, owned)
        with pytest.raises(FileNotFoundError) as caught:
            owned._usage_inventory(attempt)
        assert not isinstance(caught.value, native_disk.OwnedInventoryDisappearance)
        assert calls == [{"strict": True, "report_owned_disappearance": True}] and partials == []
        assert removed == [True] and not target.exists()
        assert owned._live_inventory_resamples == 0 and owned._live_inventory_in_progress is False


@pytest.mark.parametrize("boundary", ["after-partial", "after-complete"])
def test_live_census_v4_formal_stop_closes_inflight_window_and_sealing_never_resamples(private_control, monkeypatch, boundary):
    c = private_control
    attempt, manifest, request, kwargs = _live_census_prepare(c)
    with _owner(c, kwargs) as owned:
        result = _complete(owned, request, manifest)
        def close_window():
            stopped = owned._require_processes_stopped()
            assert stopped["live_processes"] == 0
        state = _live_census_publication(monkeypatch, owned, "pending",
            before_publish=close_window if boundary == "after-partial" else None)
        calls, partials = _observe_live_census_calls(monkeypatch, owned,
            after_completed=(lambda count: close_window()) if boundary == "after-complete" else None)
        with pytest.raises(validation.ValidationResourceError, match="window is closed"):
            owned._usage_inventory(attempt)
        assert owned._live_inventory_active is False and owned._live_inventory_in_progress is False
        assert len(calls) == {"after-partial": 1, "after-complete": 2}[boundary]
        assert len(partials) == state["publications"] == 1
        cumulative = owned._live_inventory_resamples
        assert cumulative == {"after-partial": 0, "after-complete": 1}[boundary]
        # A typed event supplied at the later STRICT sealing scan must escape;
        # it cannot reacquire live retry authority or reset observations.
        actual_inventory = native_disk._inventory
        sealing_calls = []
        def typed_at_seal(roots, **options):
            if list(roots) == [attempt]:
                sealing_calls.append(dict(options))
                raise native_disk.OwnedInventoryDisappearance(frozen_root=owned.identity,
                    vanished_path=owned.output_layout["tmp"] / "previously-queued",
                    partial_inventory={"apparent_bytes": 0, "entry_count": 0,
                        "symlink_count": 0, "special_file_count": 0})
            return actual_inventory(roots, **options)
        monkeypatch.setattr(native_disk, "_inventory", typed_at_seal)
        with pytest.raises(native_disk.OwnedInventoryDisappearance):
            owned.seal_results(result)
        assert sealing_calls == [{"strict": True}]
        assert owned._sealed is None and owned._live_inventory_resamples == cumulative
        assert owned._live_inventory_active is False
        monkeypatch.setattr(native_disk, "_inventory", actual_inventory)
        # The permanent closed state also preserves real default strict queue
        # failure. This explicit failed-seal control performs no auto retry.
        direct = owned.output_layout["tmp"] / "strict-seal"
        direct.mkdir()
        from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_daemon_resources import _atomic_census_publication
        _atomic_census_publication(monkeypatch, native_disk, direct, "pending")
        with pytest.raises((FileNotFoundError, native_disk.DaemonResourceError)) as caught:
            owned.seal_results(result)
        assert not isinstance(caught.value, native_disk.OwnedInventoryDisappearance)
        assert owned._sealed is None and owned._live_inventory_resamples == cumulative
        assert owned.to_dict()["live_inventory_profile"]["live_exception_active"] is False


def test_live_census_v4_per_logical_census_limit_rejects_reentry_and_preserves_cumulative_budgets(private_control, monkeypatch):
    from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_daemon_resources import _atomic_census_publication
    c = private_control
    attempt, _, _, kwargs = _live_census_prepare(c)
    with _owner(c, kwargs) as owned:
        started, timeout = owned._started, owned.validation_timeout_seconds
        original_request, rid = owned.request_sha256, owned.reservation_id
        lease_id = owned.to_dict()["resource_lease"]["lease_id"]
        calls, partials = _observe_live_census_calls(monkeypatch, owned)
        nested_refusals, states = [], []
        def refuse_nested():
            assert owned._live_inventory_in_progress is True
            with pytest.raises(validation.ValidationResourceError, match="reentrant"):
                owned._usage_inventory(attempt)
            assert owned._live_inventory_in_progress is True
            nested_refusals.append(True)
        for turn in range(2):
            directory = owned.output_layout["tmp"] / ("logical-sample-" + str(turn))
            directory.mkdir()
            states.append(_atomic_census_publication(monkeypatch, native_disk, directory,
                "pending", before_publish=refuse_nested))
            observed = owned._usage_inventory(attempt)
            assert observed["apparent_bytes"] >= states[-1]["payload_bytes"]
            assert owned._live_inventory_resamples == turn + 1
            assert owned._live_inventory_in_progress is False
        assert len(calls) == 4 and len(partials) == 2 and nested_refusals == [True, True]
        assert calls == [{"strict": True, "report_owned_disappearance": True}] * 4
        assert owned._started == started and owned.validation_timeout_seconds == timeout
        assert owned.request_sha256 == original_request and owned.reservation_id == rid
        assert owned.to_dict()["resource_lease"]["lease_id"] == lease_id
        profile = owned.to_dict()["live_inventory_profile"]
        assert profile["resample_limit_scope"] == "per_logical_live_census"
        assert profile["complete_resamples_observed"] == 2 and profile["live_exception_active"] is True
        assert owned.storage_bytes == kwargs["storage_bytes"]
    row = _json(c["ledger"])["reservations"][rid]
    assert row["status"] == "retained" and row["storage_bytes"] == kwargs["storage_bytes"]
    assert owned.to_dict()["live_inventory_profile"]["live_exception_active"] is False


# Genuine lock/thread controls use only this owner's original private scheduler,
# clock budget and regular fixture. They grant no productive concurrency credit.
class _ObservedLiveCensusLock:
    def __init__(self, actual, before_acquire):
        self.actual, self.before_acquire = actual, before_acquire
    def acquire(self, *, timeout):
        self.before_acquire(timeout)
        return self.actual.acquire(timeout=timeout)
    def release(self):
        self.actual.release()


def _live_census_thread_worker(owned, attempt, label, outcomes, done):
    try:
        outcomes[label] = ("ok", owned._usage_inventory(attempt))
    except BaseException as error:
        outcomes[label] = ("error", error)
    finally:
        done.set()


def _join_live_census_test_workers(threads, release):
    release.set()
    for worker in threads:
        if worker.ident is not None:
            worker.join(timeout=3)
    assert all(not worker.is_alive() for worker in threads), "live census worker cleanup is unresolved"


def test_live_census_v4_actual_threads_serialize_both_complete_samples(private_control, monkeypatch):
    import threading
    c = private_control
    attempt, _, _, kwargs = _live_census_prepare(c)
    with _owner(c, kwargs) as owned:
        entered, release, waiting = threading.Event(), threading.Event(), threading.Event()
        first_done, second_done = threading.Event(), threading.Event()
        outcomes, samples, occupancy = {}, [], {"active": 0, "maximum": 0}
        sample_lock = threading.Lock()
        actual_inventory = native_disk._inventory
        def inventory(roots, **options):
            if list(roots) != [attempt]:
                return actual_inventory(roots, **options)
            label = threading.current_thread().name
            with sample_lock:
                occupancy["active"] += 1
                occupancy["maximum"] = max(occupancy["maximum"], occupancy["active"])
                samples.append((label, dict(options)))
            try:
                if label == "live-first":
                    entered.set()
                    assert release.wait(timeout=2), "first sampler was never released"
                return actual_inventory(roots, **options)
            finally:
                with sample_lock:
                    occupancy["active"] -= 1
        actual_lock = owned._live_inventory_lock
        def acquiring(timeout):
            assert 0 < timeout <= owned.validation_timeout_seconds
            if threading.current_thread().name == "live-second":
                waiting.set()
        monkeypatch.setattr(owned, "_live_inventory_lock", _ObservedLiveCensusLock(actual_lock, acquiring))
        monkeypatch.setattr(native_disk, "_inventory", inventory)
        threads = [threading.Thread(name="live-first", daemon=True, target=_live_census_thread_worker,
                args=(owned, attempt, "first", outcomes, first_done)),
            threading.Thread(name="live-second", daemon=True, target=_live_census_thread_worker,
                args=(owned, attempt, "second", outcomes, second_done))]
        started, timeout = owned._started, owned.validation_timeout_seconds
        try:
            threads[0].start()
            assert entered.wait(timeout=2), "first actual scan did not enter"
            threads[1].start()
            assert waiting.wait(timeout=2), "second sampler did not attempt the real lock"
            assert not second_done.is_set(), "overlapping sampler bypassed serialization"
        finally:
            _join_live_census_test_workers(threads, release)
        assert first_done.is_set() and second_done.is_set() and set(outcomes) == {"first", "second"}
        assert all(outcomes[label][0] == "ok" for label in outcomes), repr(outcomes)
        assert outcomes["first"][1] == outcomes["second"][1]
        assert occupancy == {"active": 0, "maximum": 1}
        assert [label for label, _ in samples] == ["live-first", "live-second"]
        assert all(options == {"strict": True, "report_owned_disappearance": True} for _, options in samples)
        assert owned._started == started and owned.validation_timeout_seconds == timeout
        assert owned._live_inventory_thread is None and owned._live_inventory_in_progress is False
        assert owned._live_inventory_resamples == 0


def test_live_census_v4_lock_wait_uses_original_deadline_without_changing_global_clock(private_control, monkeypatch):
    import threading
    c = private_control
    attempt, _, _, kwargs = _live_census_prepare(c)
    with _owner(c, kwargs) as owned:
        actual_time, started, timeout = validation.time, owned._started, owned.validation_timeout_seconds
        global_monotonic = time.monotonic
        clock_started = actual_time.monotonic()
        class OwnerClock:
            def monotonic(self):
                return started + timeout - 0.2 + (actual_time.monotonic() - clock_started)
            def __getattr__(self, name):
                return getattr(actual_time, name)
        actual_lock = owned._live_inventory_lock
        attempted, done, release = threading.Event(), threading.Event(), threading.Event()
        outcomes, scan_attempts = {}, []
        actual_inventory = native_disk._inventory
        def inventory(roots, **options):
            if list(roots) == [attempt]:
                scan_attempts.append(dict(options))
            return actual_inventory(roots, **options)
        def acquiring(remaining):
            assert 0 < remaining <= 0.100001
            attempted.set()
        worker = threading.Thread(name="live-deadline-waiter", daemon=True, target=_live_census_thread_worker,
            args=(owned, attempt, "waiter", outcomes, done))
        actual_lock.acquire()
        try:
            with monkeypatch.context() as local:
                local.setattr(validation, "time", OwnerClock())
                local.setattr(owned, "_live_inventory_lock", _ObservedLiveCensusLock(actual_lock, acquiring))
                local.setattr(native_disk, "_inventory", inventory)
                try:
                    worker.start()
                    assert attempted.wait(timeout=2), "deadline waiter never attempted the real lock"
                    worker.join(timeout=2)
                    assert not worker.is_alive(), "waiter exceeded its original remaining budget"
                    assert done.is_set() and set(outcomes) == {"waiter"}
                    assert outcomes["waiter"][0] == "error"
                    assert isinstance(outcomes["waiter"][1], validation.ValidationResourceError)
                    assert "deadline" in str(outcomes["waiter"][1])
                    assert scan_attempts == []
                finally:
                    actual_lock.release()
                    _join_live_census_test_workers([worker], release)
                assert time.monotonic is global_monotonic
        finally:
            # The normal path released inside the local scope; no foreign lock
            # owner or grant is changed by this test's cleanup.
            assert not worker.is_alive()
        assert validation.time is actual_time and time.monotonic is global_monotonic
        assert owned._started == started and owned.validation_timeout_seconds == timeout
        assert owned._live_inventory_resamples == 0 and owned._live_inventory_in_progress is False
        assert owned._live_inventory_thread is None


def test_live_census_v4_formal_stop_during_wait_never_reopens_live_retry(private_control, monkeypatch):
    import threading
    c = private_control
    attempt, _, _, kwargs = _live_census_prepare(c)
    with _owner(c, kwargs) as owned:
        entered, release, waiting = threading.Event(), threading.Event(), threading.Event()
        first_done, second_done = threading.Event(), threading.Event()
        outcomes, samples = {}, []
        actual_inventory, actual_lock = native_disk._inventory, owned._live_inventory_lock
        def inventory(roots, **options):
            if list(roots) != [attempt]:
                return actual_inventory(roots, **options)
            label = threading.current_thread().name
            samples.append((label, dict(options)))
            if label == "live-stop-first":
                entered.set()
                assert release.wait(timeout=2), "in-progress sampler was never released"
            return actual_inventory(roots, **options)
        def acquiring(remaining):
            if threading.current_thread().name == "live-stop-second":
                waiting.set()
        monkeypatch.setattr(native_disk, "_inventory", inventory)
        monkeypatch.setattr(owned, "_live_inventory_lock", _ObservedLiveCensusLock(actual_lock, acquiring))
        threads = [threading.Thread(name="live-stop-first", daemon=True, target=_live_census_thread_worker,
                args=(owned, attempt, "first", outcomes, first_done)),
            threading.Thread(name="live-stop-second", daemon=True, target=_live_census_thread_worker,
                args=(owned, attempt, "second", outcomes, second_done))]
        try:
            threads[0].start()
            assert entered.wait(timeout=2)
            threads[1].start()
            assert waiting.wait(timeout=2) and not second_done.is_set()
            assert owned._require_processes_stopped()["live_processes"] == 0
            assert owned._live_inventory_active is False
        finally:
            _join_live_census_test_workers(threads, release)
        assert first_done.is_set() and second_done.is_set() and set(outcomes) == {"first", "second"}
        assert outcomes["first"][0] == "error"
        assert isinstance(outcomes["first"][1], validation.ValidationResourceError)
        assert "window is closed" in str(outcomes["first"][1])
        assert outcomes["second"][0] == "ok", repr(outcomes)
        assert samples == [("live-stop-first", {"strict": True, "report_owned_disappearance": True}),
            ("live-stop-second", {"strict": True})]
        assert owned._live_inventory_active is False and owned._live_inventory_resamples == 0
        assert owned._live_inventory_thread is None and owned._live_inventory_in_progress is False


def test_live_census_v4_constructor_and_native_no_grant_remain_inactive(private_control):
    c = private_control
    _, _, _, kwargs = _live_census_prepare(c, memory_mb=4096)
    owned = _owner(c, kwargs)
    assert owned._live_inventory_active is False and owned._live_inventory_resamples == 0
    assert owned._started is None and owned._opened is False
    blocker = c["scheduler"].acquire(native.ResourceLane.VALIDATION,
        cpu_slots=1, memory_mb=1, child_process_slots=0, timeout=0,
        request_id="private-live-census-no-grant-blocker")
    try:
        with pytest.raises(native.LeaseTimeoutError):
            owned.open()
        profile = owned.to_dict()["live_inventory_profile"]
        assert profile["live_exception_active"] is False and profile["complete_resamples_observed"] == 0
        assert owned._started is None and owned._opened is False and owned._lease is None
        assert owned._live_inventory_thread is None and owned._live_inventory_in_progress is False
        row = _json(c["ledger"])["reservations"][owned.reservation_id]
        assert row["status"] == "retained" and row["retention_reason"] == "scheduler_admission_failed"
        assert row["storage_bytes"] == kwargs["storage_bytes"] and row["child"] is None
    finally:
        blocker.release()


def test_live_census_v4_failed_first_postgrant_check_closes_window(private_control, monkeypatch):
    c = private_control
    _, _, _, kwargs = _live_census_prepare(c)
    owned, reached = _owner(c, kwargs), []
    def refuse_first_check(*, full=False):
        assert owned._opened is True and owned._started is not None and owned._lease is not None
        assert owned._live_inventory_active is True
        reached.append(True)
        raise validation.ValidationResourceError("fixture first post-grant check refusal")
    monkeypatch.setattr(owned, "check_limits", refuse_first_check)
    with pytest.raises(validation.ValidationResourceError, match="first post-grant"):
        owned.open()
    assert reached == [True] and owned._opened is False
    assert owned._live_inventory_active is False and owned._live_inventory_resamples == 0
    assert owned._live_inventory_thread is None and owned._live_inventory_in_progress is False
    row = _json(c["ledger"])["reservations"][owned.reservation_id]
    assert row["status"] == "retained" and row["retention_reason"] == "context_failed"
    assert row["storage_bytes"] == kwargs["storage_bytes"]


def test_live_census_v4_ordinary_environment_strips_ambient_physical_pair_for_unchanged_c19(private_control, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import validation_pytest as fixture_plugin
    c = private_control
    _, _, _, kwargs = _live_census_prepare(c)
    assert _sha(fixture_plugin.__file__) == "c19ab1470d0a1638635dc796e7ed60cc515181c79bc75f8ca89ad74af59a51e1"
    original_environment = dict(os.environ)
    with _owner(c, kwargs) as owned:
        ambient = dict(original_environment)
        ambient[validation.PHYSICAL_REQUEST_ENV] = "/unselected/ambient-physical-request.json"
        ambient[validation.PHYSICAL_REQUEST_SHA_ENV] = "f" * 64
        produced = owned.environment(ambient)
        assert validation.PHYSICAL_REQUEST_ENV not in produced
        assert validation.PHYSICAL_REQUEST_SHA_ENV not in produced
        assert owned._physical_profile is None
        actual_os, asked = fixture_plugin.os, []
        class PluginOS:
            environ = produced
            def __getattr__(self, name):
                return getattr(actual_os, name)
        class Config:
            def getoption(self, name):
                asked.append(name)
                assert name == "owned_physical_fixtures"
                return False
        with monkeypatch.context() as local:
            # Only the plugin's module-local environment view is replaced.
            # The process-global environment and all fixture assertions stay intact.
            local.setattr(fixture_plugin, "os", PluginOS())
            assert fixture_plugin._load_profile(Config()) is None
        assert asked == ["owned_physical_fixtures"] and fixture_plugin.os is actual_os
        assert dict(os.environ) == original_environment


# Additional return/wait cancellation fences use actual private native lease
# revocation. No grant/renewal or shared native policy is changed.
@pytest.mark.parametrize("invalidation", ["deadline", "cancellation"])
def test_live_census_v4_closed_strict_postscan_invalidation_never_returns_success(private_control, monkeypatch, invalidation):
    c = private_control
    attempt, _, _, kwargs = _live_census_prepare(c)
    with _owner(c, kwargs) as owned:
        assert owned._require_processes_stopped()["live_processes"] == 0
        assert owned._live_inventory_active is False
        actual_time, expired = validation.time, []
        started, timeout, global_clock = owned._started, owned.validation_timeout_seconds, time.monotonic
        class OwnerClock:
            def monotonic(self):
                return started + timeout + 1 if expired else actual_time.monotonic()
            def __getattr__(self, name):
                return getattr(actual_time, name)
        actual_inventory, calls = native_disk._inventory, []
        def inventory(roots, **options):
            observed = actual_inventory(roots, **options)
            if list(roots) == [attempt]:
                calls.append(dict(options))
                if invalidation == "deadline":
                    expired.append(True)
                else:
                    assert owned._lease.cancel() is True
            return observed
        with monkeypatch.context() as local:
            local.setattr(validation, "time", OwnerClock())
            local.setattr(native_disk, "_inventory", inventory)
            with pytest.raises(validation.ValidationResourceError, match="deadline|custody"):
                owned._usage_inventory(attempt)
        assert calls == [{"strict": True}]
        assert validation.time is actual_time and time.monotonic is global_clock
        assert owned._started == started and owned.validation_timeout_seconds == timeout
        assert owned._live_inventory_active is False and owned._live_inventory_resamples == 0
        assert owned._live_inventory_thread is None and owned._live_inventory_in_progress is False
        assert owned._live_inventory_lock.acquire(timeout=0) is True
        owned._live_inventory_lock.release()


def test_live_census_v4_private_revocation_during_wait_aborts_before_scan(private_control, monkeypatch):
    import threading
    c = private_control
    attempt, _, _, kwargs = _live_census_prepare(c)
    with _owner(c, kwargs) as owned:
        attempted, done, release = threading.Event(), threading.Event(), threading.Event()
        outcomes, slices, scans = {}, [], []
        actual_inventory, actual_lock = native_disk._inventory, owned._live_inventory_lock
        started, timeout = owned._started, owned.validation_timeout_seconds
        def acquiring(duration):
            assert 0 < duration <= 0.100001
            slices.append(duration)
            attempted.set()
        def inventory(roots, **options):
            if list(roots) == [attempt]:
                scans.append(dict(options))
            return actual_inventory(roots, **options)
        worker = threading.Thread(name="live-cancel-waiter", daemon=True, target=_live_census_thread_worker,
            args=(owned, attempt, "waiter", outcomes, done))
        actual_lock.acquire()
        try:
            with monkeypatch.context() as local:
                local.setattr(owned, "_live_inventory_lock", _ObservedLiveCensusLock(actual_lock, acquiring))
                local.setattr(native_disk, "_inventory", inventory)
                try:
                    worker.start()
                    assert attempted.wait(timeout=2), "waiter never attempted its real lock"
                    assert owned._lease.cancel() is True
                    worker.join(timeout=2)
                    assert not worker.is_alive(), "revoked waiter ignored bounded cancellation slices"
                    assert done.is_set() and set(outcomes) == {"waiter"}
                    assert outcomes["waiter"][0] == "error"
                    assert isinstance(outcomes["waiter"][1], validation.ValidationResourceError)
                    assert "custody" in str(outcomes["waiter"][1])
                    assert slices and scans == []
                finally:
                    actual_lock.release()
                    _join_live_census_test_workers([worker], release)
        finally:
            assert not worker.is_alive()
        assert owned._started == started and owned.validation_timeout_seconds == timeout
        assert owned._live_inventory_resamples == 0 and owned._live_inventory_thread is None
        assert owned._live_inventory_in_progress is False


def test_live_census_v4_private_revocation_after_partial_never_grants_resample(private_control, monkeypatch):
    c = private_control
    attempt, _, _, kwargs = _live_census_prepare(c)
    with _owner(c, kwargs) as owned:
        revoked = []
        def revoke():
            assert owned._lease.cancel() is True
            revoked.append(True)
        state = _live_census_publication(monkeypatch, owned, "pending", before_publish=revoke)
        calls, partials = _observe_live_census_calls(monkeypatch, owned)
        with pytest.raises(validation.ValidationResourceError, match="custody"):
            owned._usage_inventory(attempt)
        assert revoked == [True] and state["publications"] == 1
        assert calls == [{"strict": True, "report_owned_disappearance": True}] and len(partials) == 1
        assert owned._live_inventory_resamples == 0 and owned._live_inventory_in_progress is False
        assert owned._live_inventory_thread is None


# Explicit V4 native-timeout binding: the real private scheduler refuses its
# native grant and the actual pinned CLI exits. These controls grant no storage
# release, child execution, physical profile, or productive-V4 authority.
def _actual_live_no_child_cli(control, monkeypatch):
    original_prepare = _prepare_no_child_lifecycle
    def prepare_live(c):
        module, launcher, attempt, manifest, request, kwargs = original_prepare(c)
        request['schema'] = validation.LIVE_REQUEST_SCHEMA
        request['live_inventory_profile'] = {
            'schema': validation.LIVE_INVENTORY_SCHEMA, 'max_complete_resamples': 1}
        _write_json(manifest, request)
        kwargs['frozen_validation_manifest_sha256'] = _sha(manifest)
        return module, launcher, attempt, manifest, request, kwargs
    with monkeypatch.context() as patch:
        patch.setitem(globals(), '_prepare_no_child_lifecycle', prepare_live)
        return _actual_no_child_cli(control)


def _live_no_child_unknown():
    return {'verdict': 'requires_original_native_cleanup',
            'source_custody_closed': False, 'storage_release_authorized': False}


def _live_no_child_pure_request(module):
    attempt = '/fictional-no-IO/outputs/attempt-0'
    pins = {module.__file__: 'a' * 64}
    pins.update({str(module.ROOT) + '/ipfs_datasets_py/optimizers/logic_theorem_optimizer/' + name: 'a' * 64
                 for name in module._LIFECYCLE_OWNER_NAMES})
    pins['/fictional-no-IO/source.py'] = 'a' * 64
    return dict(schema='owned-validation-request/v4', argv=['python', '-B', 'check.py'],
        cwd=attempt, selected_checks=['actual arithmetic check'],
        source_sha256=pins, timeout_seconds=20,
        storage_bytes=1000000, memory_mb=4096, cpu_slots=1, child_process_slots=3,
        attempt_directory=attempt,
        outputs={name: attempt + '/' + name for name in ('pytest', 'tmp', 'cache', 'db', 'exports', 'logs')},
        declared_external_writable_paths=[], process_scope='sampled_birth_bound_descendants',
        scheduler_state_path='/fictional-no-IO/native-state.json',
        expected_scheduler_policy_sha256='b' * 64, roots=['/fictional-no-IO/outputs'],
        live_inventory_profile={'schema': 'owned-validation-live-census/v1', 'max_complete_resamples': 1})


@pytest.mark.parametrize('fault', [
    'missing-profile', 'extra-field', 'profile-null', 'extra-profile', 'profile-schema',
    'limit-bool', 'limit-float', 'limit-two', 'empty-argv', 'nul-argv', 'duplicate-checks',
    'relative-cwd', 'dot-attempt', 'wrong-output', 'external-write', 'group-scope',
    'duplicate-root', 'overlap-root', 'outside-attempt', 'bool-storage', 'over-cap-storage',
    'zero-memory', 'zero-cpu', 'float-child-slots', 'bool-timeout', 'infinite-timeout',
    'wrong-policy', 'empty-sources', 'relative-source', 'bad-source-pin', 'duplicate-json',
    'preowner-header', 'pregrant-header',
])
def test_live_v4_no_child_binding_refuses_malformed_shape_before_path_or_import(tmp_path, monkeypatch, fault):
    module, _ = _lifecycle_launcher_module()
    request = _live_no_child_pure_request(module)
    initial_raw = json.dumps(request, sort_keys=True).encode()
    assert module._live_no_child_request_shape(request, initial_raw) is True
    witness = {'schema': module.LIFECYCLE_SCHEMA}
    if fault == 'missing-profile': request.pop('live_inventory_profile')
    elif fault == 'extra-field': request['extra'] = True
    elif fault == 'profile-null': request['live_inventory_profile'] = None
    elif fault == 'extra-profile': request['live_inventory_profile']['extra'] = True
    elif fault == 'profile-schema': request['live_inventory_profile']['schema'] = 'owned-validation-live-census/v2'
    elif fault == 'limit-bool': request['live_inventory_profile']['max_complete_resamples'] = True
    elif fault == 'limit-float': request['live_inventory_profile']['max_complete_resamples'] = 1.0
    elif fault == 'limit-two': request['live_inventory_profile']['max_complete_resamples'] = 2
    elif fault == 'empty-argv': request['argv'] = []
    elif fault == 'nul-argv': request['argv'][0] = 'python\x00'
    elif fault == 'duplicate-checks': request['selected_checks'] *= 2
    elif fault == 'relative-cwd': request['cwd'] = 'relative'
    elif fault == 'dot-attempt': request['attempt_directory'] = '/fictional-no-IO/outputs/../attempt-0'
    elif fault == 'wrong-output': request['outputs']['tmp'] += '-different'
    elif fault == 'external-write': request['declared_external_writable_paths'] = ['/foreign']
    elif fault == 'group-scope': request['process_scope'] = 'isolated_process_group'
    elif fault == 'duplicate-root': request['roots'] *= 2
    elif fault == 'overlap-root': request['roots'].append('/fictional-no-IO/outputs/nested')
    elif fault == 'outside-attempt': request['roots'] = ['/elsewhere']
    elif fault == 'bool-storage': request['storage_bytes'] = True
    elif fault == 'over-cap-storage': request['storage_bytes'] = 220_000_000_001
    elif fault == 'zero-memory': request['memory_mb'] = 0
    elif fault == 'zero-cpu': request['cpu_slots'] = 0
    elif fault == 'float-child-slots': request['child_process_slots'] = 3.0
    elif fault == 'bool-timeout': request['timeout_seconds'] = True
    elif fault == 'infinite-timeout': request['timeout_seconds'] = float('inf')
    elif fault == 'wrong-policy': request['expected_scheduler_policy_sha256'] = 'not-a-sha'
    elif fault == 'empty-sources': request['source_sha256'] = {}
    elif fault == 'relative-source': request['source_sha256'] = {'relative.py': 'a' * 64}
    elif fault == 'bad-source-pin': request['source_sha256']['/fictional-no-IO/source.py'] = 'A' * 64
    elif fault == 'preowner-header': witness['schema'] = module.PRE_OWNER_REFUSAL_SCHEMA
    elif fault == 'pregrant-header': witness['schema'] = module.PRE_GRANT_CAPACITY_REFUSAL_SCHEMA
    raw = json.dumps(request, sort_keys=True).encode()
    if fault == 'duplicate-json': raw = raw[:-1] + b',"schema":"owned-validation-request/v4"}'
    path_calls, import_calls = [], []
    actual_path = module.Path
    import builtins
    actual_import = builtins.__import__
    def recorded_path(value):
        path_calls.append(value)
        return actual_path(value)
    def recorded_import(*args, **kwargs):
        import_calls.append(args[0])
        return actual_import(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(module, 'Path', recorded_path)
        patch.setattr(builtins, '__import__', recorded_import)
        verdict = module.classify_owned_validation_source_custody(
            {'source_custody_lifecycle': witness}, raw,
            expected_request_sha256=hashlib.sha256(raw).hexdigest(), owner_pid=os.getpid(),
            owner_birth='1', returncode=1, expected_resource_ledger='/unopened/no-IO-ledger.json')
    assert verdict == _live_no_child_unknown()
    assert path_calls == [] and import_calls == []


def test_actual_v4_cli_native_timeout_closes_only_original_no_child_source_custody(private_control, monkeypatch):
    module, terminal, raw, caller, attempt = _actual_live_no_child_cli(private_control, monkeypatch)
    verdict = module.classify_owned_validation_source_custody(terminal, raw, **caller)
    assert verdict == {'verdict': 'proven_original_no_child_no_native_grant',
        'source_custody_closed': True, 'storage_release_authorized': False}
    request, reservation = json.loads(raw), terminal['reservation']
    assert len(request) == 18 and request['schema'] == validation.LIVE_REQUEST_SCHEMA
    assert caller['returncode'] == 1 and reservation['resource_lease'] is None
    assert reservation['process_observation'] is None
    assert reservation['record']['child'] is None and reservation['record']['prior_children'] == []
    assert reservation['status'] == reservation['record']['status'] == 'retained'
    assert reservation['record']['retention_reason'] == 'scheduler_admission_failed'
    assert reservation['record']['artifacts_durable_asserted'] is False
    assert reservation['live_inventory_profile'] == {
        'schema': 'owned-validation-live-census/v1', 'max_complete_resamples': 1,
        'request_sha256': caller['expected_request_sha256'], 'complete_resamples_observed': 0,
        'live_exception_active': False, 'resample_limit_scope': 'per_logical_live_census'}
    assert type(reservation['live_inventory_profile']['complete_resamples_observed']) is int
    assert reservation['live_inventory_profile']['live_exception_active'] is False
    witness = terminal['source_custody_lifecycle']
    assert witness['events'] == dict(owner_open_attempted=True, owner_open_returned=False,
        child_launch_attempted=False, child_created=False, barrier_release_attempted=False,
        barrier_released=False, owner_exit_handling_completed=True)
    assert witness['native_grant']['exact_native_timeout'] is True
    assert witness['native_grant']['timeout_decision']['request_id'] == 'validation:' + reservation['reservation_id']
    assert witness['storage']['release_authorized'] is False and not tuple(attempt.iterdir())


def test_actual_v4_no_child_binding_rejects_changed_observation_and_original_custody(private_control, monkeypatch):
    module, terminal, raw, caller, _ = _actual_live_no_child_cli(private_control, monkeypatch)
    assert module.classify_owned_validation_source_custody(terminal, raw, **caller)['source_custody_closed'] is True
    for fault in ('missing-profile', 'extra-observation', 'observation-schema', 'observation-request',
                  'observation-max-bool', 'observation-max-two', 'counter-one', 'counter-bool',
                  'active-true', 'active-zero', 'wrong-scope', 'producer-pin', 'producer-path',
                  'owner-pid', 'owner-birth', 'ledger', 'cpu-budget', 'open-returned',
                  'child-created', 'child-attached', 'exit-incomplete', 'native-acquired',
                  'wrong-timeout-request', 'not-terminal-timeout', 'lease-present',
                  'record-child', 'source-guard-false', 'source-guard-errors', 'storage-release',
                  'watchdog-error', 'received-signal', 'wrong-retention', 'cleanup-error',
                  'zero-exit', 'other-exit', 'signal-exit'):
        changed, changed_caller = deepcopy(terminal), dict(caller)
        observation = changed['reservation']['live_inventory_profile']
        witness = changed['source_custody_lifecycle']
        if fault == 'missing-profile': changed['reservation'].pop('live_inventory_profile')
        elif fault == 'extra-observation': observation['extra'] = True
        elif fault == 'observation-schema': observation['schema'] = 'owned-validation-live-census/v2'
        elif fault == 'observation-request': observation['request_sha256'] = '0' * 64
        elif fault == 'observation-max-bool': observation['max_complete_resamples'] = True
        elif fault == 'observation-max-two': observation['max_complete_resamples'] = 2
        elif fault == 'counter-one': observation['complete_resamples_observed'] = 1
        elif fault == 'counter-bool': observation['complete_resamples_observed'] = False
        elif fault == 'active-true': observation['live_exception_active'] = True
        elif fault == 'active-zero': observation['live_exception_active'] = 0
        elif fault == 'wrong-scope': observation['resample_limit_scope'] = 'per_campaign'
        elif fault == 'producer-pin': witness['producer']['sha256'] = '0' * 64
        elif fault == 'producer-path': witness['producer']['path'] += '-different'
        elif fault == 'owner-pid': witness['owner']['pid'] += 1
        elif fault == 'owner-birth': witness['owner']['birth'] = '0'
        elif fault == 'ledger': witness['ledger_path'] += '-different'
        elif fault == 'cpu-budget': witness['budgets']['cpu_slots'] += 1
        elif fault == 'open-returned': witness['events']['owner_open_returned'] = True
        elif fault == 'child-created': witness['events']['child_created'] = True
        elif fault == 'child-attached': witness['owner_child_attached'] = True
        elif fault == 'exit-incomplete': witness['events']['owner_exit_handling_completed'] = False
        elif fault == 'native-acquired': witness['native_grant']['status'] = 'acquired'
        elif fault == 'wrong-timeout-request': witness['native_grant']['timeout_decision']['request_id'] += '-different'
        elif fault == 'not-terminal-timeout': witness['native_grant']['timeout_decision']['decision_scope'] = 'synthetic'
        elif fault == 'lease-present': changed['reservation']['resource_lease'] = {'lease_id': 'unproven'}
        elif fault == 'record-child': changed['reservation']['record']['child'] = {'pid': os.getpid()}
        elif fault == 'source-guard-false': witness['source_guards']['source_pins_unchanged'] = False
        elif fault == 'source-guard-errors': witness['source_guards']['errors'] = ['unproven source']
        elif fault == 'storage-release': witness['storage']['release_authorized'] = True
        elif fault == 'watchdog-error': changed['failure']['watchdog_errors'] = ['unproven watchdog']
        elif fault == 'received-signal': changed['failure']['received_signals'] = [15]
        elif fault == 'wrong-retention': changed['reservation']['record']['retention_reason'] = 'other_failure'
        elif fault == 'cleanup-error': changed['reservation']['cleanup_error'] = 'unproven cleanup'
        elif fault == 'zero-exit': changed_caller['returncode'] = 0
        elif fault == 'other-exit': changed_caller['returncode'] = 2
        elif fault == 'signal-exit': changed_caller['returncode'] = -9
        assert module.classify_owned_validation_source_custody(changed, raw, **changed_caller) == _live_no_child_unknown(), fault


def test_actual_v4_no_child_binding_replays_current_source_and_sdk_parser_identity(private_control, monkeypatch):
    module, terminal, raw, caller, _ = _actual_live_no_child_cli(private_control, monkeypatch)
    assert module.classify_owned_validation_source_custody(terminal, raw, **caller)['source_custody_closed'] is True
    sdk_path = str(Path(validation.__file__))
    actual_snapshot = module.snapshot
    def changed_snapshot(path, *args, **kwargs):
        actual = actual_snapshot(path, *args, **kwargs)
        return actual + b'\n# authored current-source drift\n' if str(path) == sdk_path else actual
    with monkeypatch.context() as patch:
        patch.setattr(module, 'snapshot', changed_snapshot)
        assert module.classify_owned_validation_source_custody(terminal, raw, **caller) == _live_no_child_unknown()
    def replaced_decoder(value):
        return json.loads(value)
    with monkeypatch.context() as patch:
        patch.setattr(validation, '_decode', replaced_decoder)
        assert module.classify_owned_validation_source_custody(terminal, raw, **caller) == _live_no_child_unknown()
    def replaced_validator(self):
        return None
    with monkeypatch.context() as patch:
        patch.setattr(validation.ValidationResourceReservation, '_validate_request', replaced_validator)
        assert module.classify_owned_validation_source_custody(terminal, raw, **caller) == _live_no_child_unknown()
    assert module.classify_owned_validation_source_custody(terminal, raw, **caller)['source_custody_closed'] is True


@pytest.mark.parametrize("route, arguments", [
    ("validation", ("--request", "/not-opened/validation.json")),
    ("trainer", ("--trainer-request", "/not-opened/trainer.json")),
    ("trainer", ("--trainer-request=/not-opened/trainer.json",)),
    ("validation", ("--request=/not-opened/--trainer-request",)),
], ids=["validation", "trainer-separated", "trainer-equals", "embedded-trainer-text"])
def test_owned_cli_dispatch_keeps_validation_and_trainer_routes_distinct(monkeypatch, route, arguments):
    """Observe routing only; neither recording callable starts a workload."""
    module, _ = _lifecycle_launcher_module()
    seen = []
    def validation_route(argv):
        seen.append(("validation", list(argv)))
        return 217
    def trainer_route(argv):
        seen.append(("trainer", list(argv)))
        return 319
    monkeypatch.setattr(module, "main", validation_route)
    monkeypatch.setattr(module, "trainer_main", trainer_route)
    argv = list(arguments)
    result = module.entrypoint(argv)
    assert result == {"validation": 217, "trainer": 319}[route]
    assert seen == [(route, list(arguments))]
    assert argv == list(arguments)


def test_validation_v4_and_trainer_guards_share_frozen_source_hash_checks(tmp_path):
    """Exercise real source hashes and parser separation without launching work."""
    module, _, trainer = _trainer_controller_request_case(tmp_path)
    shared_pins = dict(trainer["source_sha256"])
    sdk_path = Path(validation.__file__).resolve()
    shared_pins[str(sdk_path)] = _sha(sdk_path)
    marker = tmp_path / "coexisting_owned_source_marker.py"
    marker.write_text("value = 1\n")
    shared_pins[str(marker)] = _sha(marker)
    trainer["source_sha256"] = shared_pins
    ordinary = _live_no_child_pure_request(module)
    ordinary["source_sha256"] = shared_pins
    path = tmp_path / "coexisting-validation-v4.json"
    _write_json(path, ordinary)
    parsed, raw = module.request(path, _sha(path))
    assert parsed == ordinary and module._live_no_child_request_shape(parsed, raw) is True
    assert len(parsed) == 18 and parsed["schema"] == validation.LIVE_REQUEST_SCHEMA
    assert parsed["process_scope"] == validation.TRACKED_SCOPE
    assert type(parsed["live_inventory_profile"]["max_complete_resamples"]) is int
    assert parsed["live_inventory_profile"]["max_complete_resamples"] == 1
    assert trainer["schema"] == module.TRAINER_REQUEST_SCHEMA
    assert trainer["process_scope"] == "isolated_process_group"
    module.source_guard(parsed)
    module._trainer_source_guard(trainer)
    with pytest.raises(ValueError, match="closed F18 training request"):
        module._validate_trainer_request(parsed)
    marker.write_text("value = 2\n")
    for check, value in ((module.source_guard, parsed), (module._trainer_source_guard, trainer)):
        with pytest.raises(ValueError, match="source changed"):
            check(value)


# V4 pre-grant capacity is an original no-record/no-native refusal. It shares
# the existing owning fixtures and genuine CLI wait; it never gains productive
# child, cleanup, storage-release, qualification or model authority.
def _actual_live_pregrant_capacity_cli(control, monkeypatch):
    original_prepare = _prepare_pregrant_capacity
    def prepare_live(c, *, process_scope=validation.TRACKED_SCOPE):
        module, launcher, attempt, manifest, request, kwargs = original_prepare(
            c, process_scope=process_scope)
        request['schema'] = validation.LIVE_REQUEST_SCHEMA
        request['live_inventory_profile'] = {
            'schema': validation.LIVE_INVENTORY_SCHEMA, 'max_complete_resamples': 1}
        _write_json(manifest, request)
        kwargs['frozen_validation_manifest_sha256'] = _sha(manifest)
        return module, launcher, attempt, manifest, request, kwargs
    with monkeypatch.context() as patch:
        patch.setitem(globals(), '_prepare_pregrant_capacity', prepare_live)
        return _actual_pregrant_capacity_cli(control)


def test_actual_v4_cli_pregrant_capacity_refusal_closes_only_source_custody(private_control, monkeypatch):
    module, terminal, raw, caller, _, attempt = _actual_live_pregrant_capacity_cli(
        private_control, monkeypatch)
    request = json.loads(raw)
    witness, reservation = terminal['source_custody_lifecycle'], terminal['reservation']
    assert request['schema'] == validation.LIVE_REQUEST_SCHEMA
    assert witness['schema'] == module.PRE_GRANT_CAPACITY_REFUSAL_SCHEMA
    assert witness['events'] == {key: key == 'owner_open_attempted' for key in module._PRE_GRANT_EVENTS}
    assert witness['native_grant'] == {'status': 'not_requested_capacity_refusal'}
    assert witness['storage'] == {'status': 'not_entered', 'release_authorized': False}
    assert reservation['status'] == 'not_entered'
    assert reservation['record'] is reservation['resource_lease'] is reservation['process_observation'] is None
    assert reservation['live_inventory_profile']['live_exception_active'] is False
    assert reservation['live_inventory_profile']['complete_resamples_observed'] == 0
    assert terminal['failure']['executed_checks'] == []
    assert terminal['failure']['returncode'] is None and caller['returncode'] == 1
    assert all(terminal[key] is False for key in ('completed', 'admitted', 'Lean_admitted'))
    assert not tuple(attempt.iterdir())
    assert module.classify_owned_validation_source_custody(terminal, raw, **caller) == {
        'verdict': 'proven_original_no_child_no_native_grant',
        'source_custody_closed': True, 'storage_release_authorized': False}


def test_actual_v4_pregrant_capacity_classifier_refuses_forged_or_started_evidence(private_control, monkeypatch):
    module, terminal, raw, caller, _, _ = _actual_live_pregrant_capacity_cli(
        private_control, monkeypatch)
    unknown = _live_no_child_unknown()
    faults = ('missing', 'unknown_schema', 'pre_owner_schema', 'timeout_schema',
        'request', 'producer', 'pid', 'birth', 'ledger', 'stage',
        'record', 'record_missing', 'lease', 'lease_missing', 'cleanup', 'cleanup_missing',
        'process_observation', 'open_returned', 'child', 'barrier', 'event_integer',
        'entered', 'native', 'storage_release', 'source_guard', 'guard_integer',
        'capacity_missing', 'capacity_additional', 'capacity_sum', 'capacity_deficit',
        'capacity_bool_integer', 'capacity_no_refusal', 'failure_checks', 'failure_returncode',
        'failure_authority', 'failure_signals')
    for fault in faults:
        changed = deepcopy(terminal)
        witness = changed['source_custody_lifecycle']
        capacity = witness['capacity_observation']
        if fault == 'missing': changed.pop('source_custody_lifecycle')
        elif fault == 'unknown_schema': witness['schema'] += '-foreign'
        elif fault == 'pre_owner_schema': witness['schema'] = module.PRE_OWNER_REFUSAL_SCHEMA
        elif fault == 'timeout_schema': witness['schema'] = module.LIFECYCLE_SCHEMA
        elif fault == 'request': witness['request_sha256'] = '0' * 64
        elif fault == 'producer': witness['producer']['sha256'] = '0' * 64
        elif fault == 'pid': witness['owner']['pid'] += 1
        elif fault == 'birth': witness['owner']['birth'] += '1'
        elif fault == 'ledger': witness['ledger_path'] += '.foreign'
        elif fault == 'stage': witness['stage'] = 'unknown_open_failure'
        elif fault == 'record': changed['reservation']['record'] = {'status': 'retained'}
        elif fault == 'record_missing': changed['reservation'].pop('record')
        elif fault == 'lease': changed['reservation']['resource_lease'] = {'released': True}
        elif fault == 'lease_missing': changed['reservation'].pop('resource_lease')
        elif fault == 'cleanup': changed['reservation']['cleanup_error'] = 'unknown'
        elif fault == 'cleanup_missing': changed['reservation'].pop('cleanup_error')
        elif fault == 'process_observation': changed['reservation']['process_observation'] = {'live_processes': 0}
        elif fault == 'open_returned': witness['events']['owner_open_returned'] = True
        elif fault == 'child': witness['events']['child_launch_attempted'] = True
        elif fault == 'barrier': witness['events']['barrier_released'] = True
        elif fault == 'event_integer': witness['events']['owner_open_attempted'] = 1
        elif fault == 'entered': witness['owner_state']['entered'] = True
        elif fault == 'native': witness['native_grant']['status'] = 'acquired'
        elif fault == 'storage_release': witness['storage']['release_authorized'] = True
        elif fault == 'source_guard': witness['source_guards']['source_pins_unchanged'] = False
        elif fault == 'guard_integer': witness['source_guards']['owner_identity_unchanged'] = 1
        elif fault == 'capacity_missing': witness.pop('capacity_observation')
        elif fault == 'capacity_additional': capacity['additional_requested_bytes'] += 1
        elif fault == 'capacity_sum': capacity['charged_bytes'] += 1
        elif fault == 'capacity_deficit': capacity['storage_capacity_deficit_bytes'] += 1
        elif fault == 'capacity_bool_integer': capacity['storage_capacity_exceeded'] = 1
        elif fault == 'capacity_no_refusal': capacity['storage_capacity_exceeded'] = capacity['filesystem_free_insufficient'] = False
        elif fault == 'failure_checks': changed['failure']['executed_checks'] = ['not a refused check']
        elif fault == 'failure_returncode': changed['failure']['returncode'] = 0
        elif fault == 'failure_authority': changed['failure']['authority_granted'] = True
        else: changed['failure']['received_signals'] = [signal.SIGTERM]
        assert module.classify_owned_validation_source_custody(changed, raw, **caller) == unknown, fault
    for key, value in (('owner_pid', True), ('owner_birth', 'unknown'), ('returncode', 0),
            ('returncode', False), ('expected_request_sha256', '0' * 64),
            ('expected_resource_ledger', str(private_control['ledger']) + '.foreign')):
        assert module.classify_owned_validation_source_custody(terminal, raw,
            **{**caller, key: value}) == unknown, key


def test_actual_v4_pregrant_capacity_classifier_rechecks_request_and_original_sources(private_control, monkeypatch):
    module, terminal, raw, caller, _, _ = _actual_live_pregrant_capacity_cli(
        private_control, monkeypatch)
    unknown = _live_no_child_unknown()
    for fault in ('missing_live_profile', 'unknown_live_profile', 'boolean_resample',
            'extra_live_field', 'missing_lifecycle_pin'):
        request = json.loads(raw)
        if fault == 'missing_live_profile': request.pop('live_inventory_profile')
        elif fault == 'unknown_live_profile': request['live_inventory_profile']['schema'] += '-foreign'
        elif fault == 'boolean_resample': request['live_inventory_profile']['max_complete_resamples'] = True
        elif fault == 'extra_live_field': request['live_inventory_profile']['extra'] = False
        else:
            request['source_sha256'].pop(str(module.ROOT /
                'ipfs_datasets_py/optimizers/logic_theorem_optimizer' / module._LIFECYCLE_OWNER_NAMES[0]))
        changed_raw = json.dumps(request, sort_keys=True, separators=(',', ':')).encode()
        pin = hashlib.sha256(changed_raw).hexdigest()
        changed = deepcopy(terminal)
        changed['request_sha256'] = changed['source_custody_lifecycle']['request_sha256'] = pin
        changed['failure']['request_sha256'] = pin
        assert module.classify_owned_validation_source_custody(changed, changed_raw,
            **{**caller, 'expected_request_sha256': pin}) == unknown, fault
    source = private_control['source']
    before = source.read_bytes()
    try:
        source.write_bytes(before + b'\n# actual owning-source drift after refused V4 open\n')
        assert module.classify_owned_validation_source_custody(terminal, raw, **caller) == unknown
    finally:
        source.write_bytes(before)
    assert module.classify_owned_validation_source_custody(terminal, raw, **caller) == {
        'verdict': 'proven_original_no_child_no_native_grant',
        'source_custody_closed': True, 'storage_release_authorized': False}



class _ValidationAdmissionClock:
    def __init__(self, actual, now=100.0):
        self.actual = actual
        self.now = now
    def monotonic(self):
        return self.now
    def __getattr__(self, name):
        return getattr(self.actual, name)


def _validation_admission_clock(monkeypatch):
    clock = _ValidationAdmissionClock(validation.time)
    # Bind module references only; leave process-wide time.monotonic untouched.
    monkeypatch.setattr(validation, "time", clock)
    monkeypatch.setattr(native_disk, "time", clock)
    monkeypatch.setattr(native, "time", clock)
    return clock


@pytest.mark.parametrize("parent_work", [None, 110.0, 130.0])
def test_ordinary_admission_scope_clips_work_and_preserves_parent_cleanup(private_control, monkeypatch, parent_work):
    from contextlib import nullcontext
    control = private_control
    attempt, request_path, request, kwargs = control["prepare"](timeout_seconds=20)
    owner = _owner(control, kwargs)
    clock = _validation_admission_clock(monkeypatch)
    owner._admission_started = 100.0
    outer = native.resource_admission_deadline(
        work_deadline_monotonic=parent_work, native_deadline_monotonic=150.0) if parent_work is not None else nullcontext()
    with outer:
        previous = native.resource_operation_deadline()
        with owner._admission_scope():
            operation = native.resource_operation_deadline()
            assert operation.work_deadline_monotonic == (120.0 if parent_work is None else min(120.0, parent_work))
            assert operation.native_deadline_monotonic == (120.0 if parent_work is None else 150.0)
            assert not operation.cleanup_only
        assert native.resource_operation_deadline() is previous
    assert native.resource_operation_deadline() is None
    assert owner._record is None and owner._lease is None


def test_ordinary_admission_cannot_be_started_from_cleanup_only_scope(private_control, monkeypatch):
    control = private_control
    attempt, request_path, request, kwargs = control["prepare"](timeout_seconds=20)
    owner = _owner(control, kwargs)
    _validation_admission_clock(monkeypatch)
    owner._admission_started = 100.0
    with native.resource_cleanup_deadline(native_deadline_monotonic=150.0):
        previous = native.resource_operation_deadline()
        with pytest.raises(native.ResourceConfigurationError):
            with owner._admission_scope():
                pytest.fail("cleanup scope must not authorize admission")
        assert native.resource_operation_deadline() is previous
    assert owner._record is None and owner._lease is None


def test_ordinary_admission_guard_time_and_failed_open_do_not_renew_budget(private_control, monkeypatch):
    control = private_control
    attempt, request_path, request, kwargs = control["prepare"](timeout_seconds=20)
    owner = _owner(control, kwargs)
    before_ledger = control["ledger"].read_bytes()
    before_native = control["scheduler"].state_path.read_bytes()
    clock = _validation_admission_clock(monkeypatch)
    original_guard = owner._guard_inputs
    guard_calls = []
    def guard_inputs():
        original_guard()
        guard_calls.append(clock.now)
        clock.now = 125.0
    monkeypatch.setattr(owner, "_guard_inputs", guard_inputs)
    for now in (100.0, 126.0):
        clock.now = now
        with pytest.raises(native.ResourceAdmissionDeadlineError):
            owner.open()
        assert owner._admission_started == 100.0
        assert owner._started is None and not owner._opened
        assert owner._record is None and owner._lease is None
        assert native.resource_operation_deadline() is None
    assert len(guard_calls) == 2
    assert control["ledger"].read_bytes() == before_ledger
    assert control["scheduler"].state_path.read_bytes() == before_native
    assert not any(attempt.iterdir())


def test_ordinary_admission_census_expiry_precedes_ledger_and_native_grant(private_control, monkeypatch):
    control = private_control
    attempt, request_path, request, kwargs = control["prepare"](timeout_seconds=20)
    owner = _owner(control, kwargs)
    before_ledger = control["ledger"].read_bytes()
    before_native = control["scheduler"].state_path.read_bytes()
    clock = _validation_admission_clock(monkeypatch)
    original_inventory = native_disk._inventory
    calls = []
    def inventory(*args, **options):
        operation = native.resource_operation_deadline()
        assert operation is not None and operation.work_deadline_monotonic == 120.0
        result = original_inventory(*args, **options)
        calls.append(result)
        clock.now = 121.0
        return result
    monkeypatch.setattr(native_disk, "_inventory", inventory)
    with pytest.raises(native.ResourceAdmissionDeadlineError):
        owner.open()
    assert len(calls) == 1
    assert owner._admission_started == 100.0 and owner._started is None
    assert owner._lease is None and owner._record is None and not owner._opened
    assert native.resource_operation_deadline() is None
    assert control["ledger"].read_bytes() == before_ledger
    assert control["scheduler"].state_path.read_bytes() == before_native
    assert not any(attempt.iterdir())


def test_ordinary_successful_admission_preserves_separate_productive_epoch(private_control, monkeypatch):
    control = private_control
    attempt, request_path, request, kwargs = control["prepare"](timeout_seconds=20)
    owner = _owner(control, kwargs)
    clock = _validation_admission_clock(monkeypatch)
    original_inventory = native_disk._inventory
    calls = []
    def inventory(*args, **options):
        result = original_inventory(*args, **options)
        calls.append(native.resource_operation_deadline())
        if len(calls) == 1:
            clock.now = 105.0
        return result
    monkeypatch.setattr(native_disk, "_inventory", inventory)
    try:
        assert owner.open() is owner
        assert owner._admission_started == 100.0
        assert owner._started == 105.0
        assert clock.now == 105.0
        assert calls[0].work_deadline_monotonic == 120.0
        assert control["scheduler"].snapshot()["allocated"]["cpu_slots"] == 1
        assert native.resource_operation_deadline() is None
        # Admission consumed five seconds, but the original productive budget
        # still starts only after successful open. Neither epoch is renewed.
        clock.now = 121.0
        assert owner.guard() is True
        assert owner._admission_started == 100.0 and owner._started == 105.0
        clock.now = 126.0
        with pytest.raises(validation.ValidationResourceError, match="deadline"):
            owner.guard()
    finally:
        if owner._opened:
            owner.__exit__(None, None, None)
    assert control["scheduler"].snapshot()["allocated"]["cpu_slots"] == 0




# Additive existing-owner preentry controls, UNRUN. Exactly one genuine CLI
# lock-timeout case exercises the existing60-second lock cap under120seconds;
# direct-owner constructor controls use an explicit shorter lock timeout within
# the unchanged20-second admission budget. No fresh trainer/Lean qualification.
def _actual_opening_ledger_lock_cli(control, schema='owned-validation-request/v4'):
    module, launcher, attempt, manifest, request, _ = _prepare_no_child_lifecycle(control)
    request['timeout_seconds'] = 120
    request['schema'] = schema
    if schema == 'owned-validation-request/v4':
        request['live_inventory_profile'] = {'schema':'owned-validation-live-census/v1','max_complete_resamples':1}
    _write_json(manifest,request)
    lock_path = control['ledger'].with_name(control['ledger'].name+'.lock')
    descriptor = os.open(lock_path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
    ledger_before = control['ledger'].read_bytes()
    state_before = control['scheduler'].state_path.read_bytes()
    environment = dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',
        IPFS_DATASETS_PY_MINIMAL_IMPORTS='1',IPFS_DATASETS_AUTO_INSTALL='0',IPFS_AUTO_INSTALL='false',
        OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
    cli = None
    try:
        cli = subprocess.Popen([sys.executable,'-B',str(launcher),'--request',str(manifest),
            '--expected-request-sha256',_sha(manifest),'--resource-ledger',str(control['ledger'])],
            cwd=launcher.parents[3],env=environment,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            start_new_session=True)
        identity = native_disk._process(cli.pid)
        assert identity is not None
        stdout,stderr = cli.communicate(timeout=90)
        assert cli.returncode == 1,(stdout,stderr)
        terminal = json.loads(stdout)
        assert terminal['failure']['error_type'] == 'DaemonResourceError'
        assert terminal['failure']['error'] == 'disk ledger lock unavailable'
        assert control['ledger'].read_bytes() == ledger_before
        assert control['scheduler'].state_path.read_bytes() == state_before
        assert tuple(attempt.iterdir()) == ()
        return module,terminal,manifest.read_bytes(),dict(expected_request_sha256=_sha(manifest),
            owner_pid=cli.pid,owner_birth=identity['birth'],returncode=cli.returncode,
            expected_resource_ledger=str(control['ledger'])),manifest,attempt
    finally:
        if cli is not None:
            if cli.poll() is None:
                cli.terminate();cli.wait(timeout=10)
            _stop_group(cli)
        os.close(descriptor)


def test_actual_opening_ledger_lock_refusal_closes_only_source_and_rejects_mutations(private_control):
    module,terminal,raw,caller,_,_ = _actual_opening_ledger_lock_cli(private_control)
    assert module.classify_owned_validation_source_custody(terminal,raw,**caller) == {
        'verdict':'proven_original_no_child_no_native_grant','source_custody_closed':True,
        'storage_release_authorized':False}
    witness = terminal['source_custody_lifecycle']
    observation = witness['lock_observation']
    assert witness['schema'] == module.PRE_GRANT_LOCK_REFUSAL_SCHEMA
    assert observation['lock_acquired'] is False and observation['holder_identity_established'] is False
    assert observation['opened_lock_identity']['st_ino'] > 0
    assert observation['deadline_monotonic'] <= observation['started_monotonic']+observation['configured_lock_timeout_seconds']
    assert terminal['reservation']['record'] is None and terminal['reservation']['resource_lease'] is None
    assert witness['native_grant'] == {'status':'not_requested_lock_timeout'}
    assert witness['storage'] == {'status':'not_entered','release_authorized':False}

    unknown = {'verdict':'requires_original_native_cleanup','source_custody_closed':False,'storage_release_authorized':False}
    for fault in ('lock-acquired','holder-claimed','wider-deadline','deadline-before-start','wrong-lock',
                  'bad-inode','observation-extra','event-entered','record-present','lease-present',
                  'source-false','owner-birth','storage-release','error-type','wrong-request'):
        changed = deepcopy(terminal);witness = changed['source_custody_lifecycle'];obs = witness['lock_observation']
        if fault == 'lock-acquired':obs['lock_acquired'] = True
        elif fault == 'holder-claimed':obs['holder_identity_established'] = True
        elif fault == 'wider-deadline':
            obs['deadline_monotonic'] = obs['started_monotonic']+obs['configured_lock_timeout_seconds']+1
            obs['observed_monotonic'] = obs['deadline_monotonic']+1
        elif fault == 'deadline-before-start':obs['deadline_monotonic'] = obs['started_monotonic']-1
        elif fault == 'wrong-lock':obs['lock_path'] += '-other'
        elif fault == 'bad-inode':obs['opened_lock_identity']['st_ino'] = 0
        elif fault == 'observation-extra':obs['extra'] = True
        elif fault == 'event-entered':witness['events']['owner_open_returned'] = True
        elif fault == 'record-present':changed['reservation']['record'] = {'status':'reserved'}
        elif fault == 'lease-present':changed['reservation']['resource_lease'] = {'lease_id':'not-no-grant'}
        elif fault == 'source-false':witness['source_guards']['source_pins_unchanged'] = False
        elif fault == 'owner-birth':witness['owner']['birth'] += '0'
        elif fault == 'storage-release':witness['storage']['release_authorized'] = True
        elif fault == 'error-type':changed['failure']['error_type'] = 'ResourceAdmissionDeadlineError'
        else:changed['request_sha256'] = '0'*64
        assert module.classify_owned_validation_source_custody(changed,raw,**caller) == unknown,fault


@pytest.mark.parametrize('schema',['owned-validation-request/v1','owned-validation-request/v4'],ids=['legacy','strict-v4'])
def test_opening_ledger_lock_builder_binds_original_self_error_and_unentered_state(private_control,schema):
    c = private_control
    module,_,_,manifest,request,kwargs = _prepare_no_child_lifecycle(c)
    kwargs['ledger_lock_timeout_seconds'] = 0.01
    request['schema'] = schema
    if schema == 'owned-validation-request/v4':
        request['live_inventory_profile'] = {'schema':'owned-validation-live-census/v1','max_complete_resamples':1}
    _write_json(manifest,request)
    kwargs['frozen_validation_manifest_sha256'] = _sha(manifest)
    owner = _owner(c,kwargs)
    path = c['ledger'].with_name(c['ledger'].name+'.lock')
    descriptor = os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
    caught = None
    try:
        try:owner.open()
        except native_disk.DaemonResourceError as error:caught = error
    finally:os.close(descriptor)
    assert caught is not None and caught.lock_observation is not None
    detached = caught.lock_observation
    detached['lock_acquired'] = True
    assert caught.lock_observation['lock_acquired'] is False
    events = {key:key=='owner_open_attempted' for key in module._PRE_GRANT_EVENTS}
    outcome = dict(schema='owned-validation-result/v1',request_sha256=_sha(manifest),executed_checks=[],
        returncode=None,completed=False,admitted=False,Lean_admitted=False,authority_granted=False,
        model_weights_downloaded=False,error_type='DaemonResourceError',error='disk ledger lock unavailable',
        watchdog_errors=[],received_signals=[])
    def build(who,error):
        return module._pre_grant_lock_refusal_terminal(who,request,manifest.read_bytes(),manifest,
            _sha(manifest),c['ledger'],events,error,outcome)
    assert build(owner,caught) is not None
    copy_error = native_disk.DaemonResourceError(str(caught))
    copy_error._lock_observation = caught.lock_observation
    copy_error.__traceback__ = caught.__traceback__
    assert build(owner,copy_error) is None
    other = _owner(c,kwargs)
    assert build(other,caught) is None
    for field,value in (('_entered',True),('_opened',True),('_record',{}),('_lease',object()),('_child',object()),('_entered',0)):
        original = getattr(owner,field);setattr(owner,field,value)
        try:assert build(owner,caught) is None,field
        finally:setattr(owner,field,original)
    original = caught._lock_observation
    caught._lock_observation = dict(original,lock_acquired=True)
    try:assert build(owner,caught) is None
    finally:caught._lock_observation = original


def test_strict_v4_pregrant_capacity_rechecks_inactive_receipt_and_original_sdk(private_control,monkeypatch):
    # Reuse the peer's newly canonical genuine V4 capacity fixture and positives.
    module,terminal,raw,caller,_,_ = _actual_live_pregrant_capacity_cli(private_control,monkeypatch)
    unknown=_live_no_child_unknown()
    for fault in ('active','counter-one','counter-bool','max-bool','max-float','max-two','receipt-pin','receipt-extra'):
        changed=deepcopy(terminal);receipt=changed['reservation']['live_inventory_profile']
        if fault=='active':receipt['live_exception_active']=True
        elif fault=='counter-one':receipt['complete_resamples_observed']=1
        elif fault=='counter-bool':receipt['complete_resamples_observed']=False
        elif fault=='max-bool':receipt['max_complete_resamples']=True
        elif fault=='max-float':receipt['max_complete_resamples']=1.0
        elif fault=='max-two':receipt['max_complete_resamples']=2
        elif fault=='receipt-pin':receipt['request_sha256']='0'*64
        else:receipt['extra']=True
        assert module.classify_owned_validation_source_custody(changed,raw,**caller)==unknown,fault
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import validation_run_resources as sdk
    for field in ('_decode','validator'):
        with monkeypatch.context() as patch:
            if field=='_decode':patch.setattr(sdk,'_decode',lambda raw:json.loads(raw))
            else:patch.setattr(sdk.ValidationResourceReservation,'_validate_request',lambda self,raw:None)
            assert module.classify_owned_validation_source_custody(terminal,raw,**caller)==unknown
    assert module.classify_owned_validation_source_custody(terminal,raw,**caller)=={
        'verdict':'proven_original_no_child_no_native_grant','source_custody_closed':True,'storage_release_authorized':False}


@pytest.mark.parametrize('kind',['capacity','lock'])
def test_v4_pregrant_header_only_stays_unknown_before_path_or_import(tmp_path,monkeypatch,kind):
    module,_ = _lifecycle_launcher_module()
    value=_live_no_child_pure_request(module);raw=json.dumps(value,sort_keys=True).encode()
    header=module.PRE_GRANT_CAPACITY_REFUSAL_SCHEMA if kind=='capacity' else module.PRE_GRANT_LOCK_REFUSAL_SCHEMA
    import builtins
    path_calls,import_calls=[],[]
    actual_path,actual_import=module.Path,builtins.__import__
    def path(item):path_calls.append(item);return actual_path(item)
    def importer(*args,**kwargs):import_calls.append(args[0]);return actual_import(*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(module,'Path',path);patch.setattr(builtins,'__import__',importer)
        verdict=module.classify_owned_validation_source_custody({'source_custody_lifecycle':{'schema':header}},raw,
            expected_request_sha256=hashlib.sha256(raw).hexdigest(),owner_pid=os.getpid(),owner_birth='1',
            returncode=1,expected_resource_ledger='/unopened/no-IO-ledger.json')
    assert verdict=={'verdict':'requires_original_native_cleanup','source_custody_closed':False,'storage_release_authorized':False}
    assert path_calls==[] and import_calls==[]


@pytest.mark.parametrize('stage', [None, 'post_owner_open'], ids=['default-owner-open', 'post-owner-open'])
def test_capacity_refusal_reporter_preserves_default_and_post_open_aggregate(stage, capsys):
    # Fictional aggregate unit data only: no reservation/native/proof authority.
    module, _ = _lifecycle_launcher_module()
    observation = dict(schema='daemon-resource-capacity-observation/v1',
        scope='named_roots_only_apparent_bytes', observed_apparent_bytes=90,
        outstanding_full_reservations_bytes=20, additional_requested_bytes=5,
        charged_bytes=115, limit_bytes=100, minimum_filesystem_free_bytes=1000,
        storage_capacity_deficit_bytes=15, filesystem_free_deficit_bytes=0,
        storage_capacity_exceeded=True, filesystem_free_insufficient=False)
    error = native_disk.DaemonResourceError('storage reservation capacity exceeded')
    error._capacity_observation = deepcopy(observation)
    assert module.report_capacity_refusal(error, **({} if stage is None else {'stage': stage})) is True
    output = capsys.readouterr()
    assert output.out == ''
    record = json.loads(output.err)
    assert record == dict(schema='owned-validation-capacity-refusal/v1',
        stage='owner.open' if stage is None else stage,
        error_type='DaemonResourceError', error='storage reservation capacity exceeded',
        observation=observation)
    assert error.capacity_observation == observation


@pytest.mark.parametrize('stage', [None, True, 'owner.attach_child', 'post_owner_open ', ''])
def test_capacity_refusal_reporter_rejects_unrecognized_stage_before_snapshot(stage, capsys):
    module, _ = _lifecycle_launcher_module()
    accesses = []
    def observation(_):
        accesses.append(True)
        raise AssertionError('invalid stage cannot inspect the snapshot')
    error_type = type('DaemonResourceError', (RuntimeError,), {'capacity_observation': property(observation)})
    error = error_type('storage reservation capacity exceeded')
    assert module.report_capacity_refusal(error, stage=stage) is False
    assert accesses == []
    output = capsys.readouterr()
    assert output.out == output.err == ''


@pytest.mark.parametrize('opened,report_raises', [(False, False), (True, False), (True, True)])
def test_post_open_failure_handler_reports_once_and_preserves_original_exception(opened, report_raises):
    # Execute only the exact existing outer except body; no CLI/owner/native job.
    import ast
    module, launcher = _lifecycle_launcher_module()
    tree = ast.parse(launcher.read_bytes())
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    handler = next(handler for node in main.body if isinstance(node, ast.Try)
        for handler in node.handlers if any(isinstance(item, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == 'failure' for target in item.targets)
            for item in handler.body))
    isolated = ast.parse('def exercise(error_to_raise,lifecycle_events,outcome,started,errors,interrupted):\n    try:\n        raise error_to_raise\n    except BaseException:\n        pass\n')
    isolated.body[0].body[0].handlers = [deepcopy(handler)]
    calls = []
    def report(error, *, stage):
        calls.append((error, stage))
        if report_raises:
            raise RuntimeError('fictional diagnostic sink failed')
        return False
    namespace = {'report_capacity_refusal': report, 'time': time}
    exec(compile(ast.fix_missing_locations(isolated), '<existing-outer-except-unit-control>', 'exec'), namespace)
    error = RuntimeError('original post-owner failure')
    outcome = {}
    with pytest.raises(RuntimeError) as raised:
        namespace['exercise'](error, {'owner_open_returned': opened}, outcome, time.monotonic(), [], [])
    assert raised.value is error
    assert calls == ([(error, 'post_owner_open')] if opened else [])
    assert outcome['completed'] is False and outcome['error'] == str(error)


# Fictional original-producer bytes exercise the strict historical-input trust
# boundary. These fixtures do not invent a Popen receipt or claim execution.
def _closed_pre_child_fixture(control):
    module, _, attempt, manifest, request, _ = _prepare_no_child_lifecycle(control)
    request['timeout_seconds'] = 20
    _write_json(manifest, request)
    pin, owner, birth, rid, lid = _sha(manifest), 1_000_000_000, '123456', 'a'*32, 'b'*32
    usage = dict(scope='named_roots_only_apparent_bytes', additional_requested_bytes=request['storage_bytes'],
        observed_apparent_bytes=0, outstanding_full_reservations_bytes=1234,
        charged_bytes=1234+request['storage_bytes'], limit_bytes=native_disk.MAX_STORAGE_BYTES,
        minimum_filesystem_free_bytes=10**12,
        inventory=dict(apparent_bytes=0, entry_count=1, special_file_count=0, symlink_count=0))
    row = dict(reservation_id=rid, status='retained', owner_pid=owner,
        storage_bytes=request['storage_bytes'], memory_mb=request['memory_mb'], cpu_slots=request['cpu_slots'],
        child_process_slots=request['child_process_slots'], external_charges={}, created_at=100.0,
        prior_children=[], child=None, artifacts_durable_asserted=False, scheduler_lane='validation',
        workload='canonical_validation', attempt_directory=native_disk._root_identity(attempt),
        last_usage=usage, retention_reason='scheduler_admission_failed')
    ledger = _json(control['ledger'])
    ledger['reservations'][rid] = deepcopy(row)
    _write_json(control['ledger'], ledger)
    lease = dict(lease_id=lid, lane='validation', owner_pid=owner, parent_lease_id=None,
        cpu_slots=request['cpu_slots'], memory_mb=request['memory_mb'],
        child_process_slots=request['child_process_slots'], gpu_memory_mb=0, unified_memory_mb=0,
        requires_gpu=False, acquired_at=100.1, wait_seconds=.001, released=True, cancelled=True)
    reservation = dict(schema=native_disk.SCHEMA, ledger_path=str(control['ledger']), reservation_id=rid,
        status='retained', record=row, resource_lease=lease, process_observation=None, cleanup_error=None,
        roots=deepcopy(ledger['roots']), scheduler_lane='validation', workload='canonical_validation',
        storage_limit_bytes=native_disk.MAX_STORAGE_BYTES,
        enforcement='cooperative_admission_and_polled_usage_not_kernel_quota')
    witness = dict(schema=module.LIFECYCLE_SCHEMA, request_sha256=pin,
        producer=dict(path=str(Path(module.__file__).resolve()), sha256=_sha(module.__file__)),
        owner=dict(pid=owner, birth=birth), reservation_id=rid, resource_request_id='validation:'+rid,
        ledger_path=str(control['ledger']), scheduler=dict(state_path=request['scheduler_state_path'],
            policy_sha256=request['expected_scheduler_policy_sha256'], lane='validation', workload='canonical_validation'),
        attempt_directory=str(attempt), outputs=deepcopy(request['outputs']),
        budgets={key: request[key] for key in ('cpu_slots', 'memory_mb', 'child_process_slots', 'storage_bytes')},
        process_scope=request['process_scope'],
        events={key: key in ('owner_open_attempted', 'owner_exit_handling_completed') for key in module._LIFECYCLE_EVENTS},
        owner_child_attached=False,
        native_grant=dict(status='acquired', exact_native_timeout=False, timeout_decision=None),
        source_guards=dict(request_unchanged=True, source_pins_unchanged=True, owner_identity_unchanged=True, errors=[]),
        storage=dict(status='retained', cleanup_error=None, release_authorized=False))
    failure = dict(schema='owned-validation-result/v1', request_sha256=pin, executed_checks=[], returncode=None,
        completed=False, admitted=False, Lean_admitted=False,
        resource_scope='cooperative_sampled_birth_bound_descendants_and_owned_attempt',
        model_weights_downloaded=False, authority_granted=False, error_type='ResourceAdmissionDeadlineError',
        error='original absolute resource operation deadline expired', elapsed_seconds=21.0,
        watchdog_errors=[], received_signals=[], process_observation=None, process_cleanup_error=None)
    terminal = dict(schema='owned-validation-failure-terminal/v1', request_sha256=pin,
        completed=False, admitted=False, Lean_admitted=False, failure=failure,
        reservation=reservation, source_custody_lifecycle=witness, process_cleanup_error=None, owner_exit_error=None)
    caller = dict(expected_request_sha256=pin, owner_pid=owner, owner_birth=birth, returncode=1,
        expected_resource_ledger=str(control['ledger']))
    return module, terminal, manifest.read_bytes(), caller, attempt


def _assert_closed_pre_child_unknown(module, terminal, raw, caller):
    assert module.inspect_owned_validation_no_child_native_closed_v1(terminal, raw, **caller) == {
        'verdict': 'requires_original_native_cleanup', 'source_custody_closed': False,
        'storage_release_authorized': False}


def test_pre_child_closed_native_inspection_is_distinct_read_only_and_retains_storage(private_control, monkeypatch):
    module, terminal, raw, caller, attempt = _closed_pre_child_fixture(private_control)
    ledger, scheduler = private_control['ledger'], private_control['scheduler'].state_path
    before = ledger.read_bytes(), scheduler.read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('read-only source closure must not allocate or persist')
    monkeypatch.setattr(native.GlobalResourceScheduler, 'acquire', forbidden)
    monkeypatch.setattr(existing._PinnedGlobalResourceScheduler, '_persist_locked_state', forbidden)
    assert module.classify_owned_validation_source_custody(terminal, raw, **caller) == {
        'verdict': 'requires_original_native_cleanup', 'source_custody_closed': False,
        'storage_release_authorized': False}
    assert module.inspect_owned_validation_no_child_native_closed_v1(terminal, raw, **caller) == {
        'verdict': 'proven_original_no_child_native_closed', 'source_custody_closed': True,
        'storage_release_authorized': False}
    assert (ledger.read_bytes(), scheduler.read_bytes()) == before
    assert not tuple(attempt.iterdir())


@pytest.mark.parametrize('path,replacement', [
    ('schema', 'foreign'), ('completed', 0), ('admitted', True), ('process_cleanup_error', 'error'),
    ('owner_exit_error', 'error'), ('request_sha256', '0'*64),
    ('failure.error_type', 'LeaseTimeoutError'), ('failure.error', 'copied error'),
    ('failure.executed_checks', ['unproven']), ('failure.returncode', 0),
    ('failure.watchdog_errors', ['uncertain']), ('failure.received_signals', [15]),
    ('failure.process_observation', {}), ('failure.elapsed_seconds', 0),
    ('source_custody_lifecycle.producer.sha256', '0'*64),
    ('source_custody_lifecycle.owner.pid', True), ('source_custody_lifecycle.owner.birth', 'different'),
    ('source_custody_lifecycle.events.owner_open_attempted', False),
    ('source_custody_lifecycle.events.owner_open_returned', True),
    ('source_custody_lifecycle.events.child_launch_attempted', True),
    ('source_custody_lifecycle.events.child_created', True),
    ('source_custody_lifecycle.events.barrier_release_attempted', True),
    ('source_custody_lifecycle.events.barrier_released', True),
    ('source_custody_lifecycle.events.owner_exit_handling_completed', False),
    ('source_custody_lifecycle.events.child_created', 0),
    ('source_custody_lifecycle.owner_child_attached', True),
    ('source_custody_lifecycle.native_grant.status', 'not_acquired_terminal_timeout'),
    ('source_custody_lifecycle.native_grant.exact_native_timeout', 0),
    ('source_custody_lifecycle.source_guards.request_unchanged', False),
    ('source_custody_lifecycle.source_guards.source_pins_unchanged', 1),
    ('source_custody_lifecycle.storage.release_authorized', 0),
    ('source_custody_lifecycle.resource_request_id', 'foreign'),
    ('source_custody_lifecycle.outputs', {}), ('source_custody_lifecycle.scheduler.policy_sha256', '0'*64),
    ('reservation.resource_lease.released', False), ('reservation.resource_lease.released', 1),
    ('reservation.resource_lease.cancelled', False), ('reservation.resource_lease.parent_lease_id', 'c'*32),
    ('reservation.resource_lease.cpu_slots', True), ('reservation.resource_lease.owner_pid', 100),
    ('reservation.resource_lease.gpu_memory_mb', False), ('reservation.resource_lease.lane', 'proof'),
    ('reservation.record.child', {}), ('reservation.record.prior_children', [{}]),
    ('reservation.record.artifacts_durable_asserted', 0), ('reservation.record.external_charges', {'unknown': 1}),
    ('reservation.record.retention_reason', 'context_failed'), ('reservation.record.status', 'released'),
    ('reservation.record.cpu_slots', True), ('reservation.record.attempt_directory.inode', True),
    ('reservation.record.last_usage.charged_bytes', 0), ('reservation.roots', []),
])
def test_pre_child_closed_native_inspection_rejects_unbound_history(private_control, path, replacement):
    module, terminal, raw, caller, _ = _closed_pre_child_fixture(private_control)
    before = private_control['ledger'].read_bytes(), private_control['scheduler'].state_path.read_bytes()
    fields = path.split('.')
    target = terminal
    for key in fields[:-1]:
        target = target[key]
    target[fields[-1]] = replacement
    _assert_closed_pre_child_unknown(module, terminal, raw, caller)
    assert (private_control['ledger'].read_bytes(), private_control['scheduler'].state_path.read_bytes()) == before


@pytest.mark.parametrize('fault', ['source_drift', 'missing_pin', 'unsupported_schema', 'row_drift',
    'row_boolean_alias', 'nonempty_attempt', 'directory_identity', 'owner_present',
    'native_root', 'native_orphan_descendant', 'native_waiter', 'late_owner', 'late_waiter', 'expired_deadline'])
def test_pre_child_closed_native_inspection_rechecks_current_custody(private_control, monkeypatch, fault):
    module, terminal, raw, caller, attempt = _closed_pre_child_fixture(private_control)
    original_open = existing.open_existing_scheduler
    if fault == 'source_drift':
        private_control['source'].write_text('changed pinned source')
    elif fault in ('missing_pin', 'unsupported_schema'):
        request = json.loads(raw)
        if fault == 'missing_pin':
            request['source_sha256'].pop(str(module.ROOT/'ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py'))
        else:
            request['schema'] = 'owned-validation-request/v2'
        raw = json.dumps(request, sort_keys=True).encode()
        caller['expected_request_sha256'] = hashlib.sha256(raw).hexdigest()
        terminal['request_sha256'] = terminal['failure']['request_sha256'] = terminal['source_custody_lifecycle']['request_sha256'] = caller['expected_request_sha256']
    elif fault in ('row_drift', 'row_boolean_alias'):
        state = _json(private_control['ledger'])
        row = state['reservations'][terminal['reservation']['reservation_id']]
        if fault == 'row_drift': row['retention_reason'] = 'changed'
        else: row['cpu_slots'] = True
        _write_json(private_control['ledger'], state)
    elif fault == 'nonempty_attempt':
        (attempt/'unexpected.txt').write_text('retained')
    elif fault == 'directory_identity':
        monkeypatch.setattr(native_disk, '_root_identity', lambda path: dict(path=str(path), device=1, inode=1))
    elif fault == 'owner_present':
        monkeypatch.setattr(native_disk, '_process', lambda pid: {'pid': pid, 'birth': 'reused'})
    elif fault in ('native_root', 'native_orphan_descendant', 'native_waiter'):
        state = _json(private_control['scheduler'].state_path)
        lid = terminal['reservation']['resource_lease']['lease_id']
        if fault == 'native_root': state['leases'][lid] = {'lease_id': lid, 'request_id': 'validation:'+terminal['reservation']['reservation_id']}
        elif fault == 'native_orphan_descendant': state['leases']['c'*32] = {'parent_lease_id': lid}
        else: state['waiters']['c'*32] = {'request_id': 'validation:'+terminal['reservation']['reservation_id']}
        _write_json(private_control['scheduler'].state_path, state)
    elif fault in ('late_owner', 'late_waiter'):
        def opened(*args, **kwargs):
            facade = original_open(*args, **kwargs)
            inspect = facade.inspect_lease
            def after_inspection(*a, **kw):
                observed = inspect(*a, **kw)
                if fault == 'late_owner':
                    monkeypatch.setattr(native_disk, '_process', lambda pid: {'pid': pid, 'birth': 'reused'})
                else:
                    state = _json(private_control['scheduler'].state_path)
                    state['waiters']['c'*32] = {'request_id': 'validation:'+terminal['reservation']['reservation_id']}
                    _write_json(private_control['scheduler'].state_path, state)
                return observed
            monkeypatch.setattr(facade, 'inspect_lease', after_inspection)
            return facade
        monkeypatch.setattr(existing, 'open_existing_scheduler', opened)
    before = private_control['ledger'].read_bytes(), private_control['scheduler'].state_path.read_bytes()
    if fault == 'expired_deadline':
        # The outer original cleanup deadline cannot be reset by this observer.
        with native.resource_cleanup_deadline(native_deadline_monotonic=time.monotonic()+.05):
            monkeypatch.setattr(module.time, 'monotonic', lambda: float('inf'))
            _assert_closed_pre_child_unknown(module, terminal, raw, caller)
    else:
        _assert_closed_pre_child_unknown(module, terminal, raw, caller)
    assert private_control['ledger'].read_bytes() == before[0]
    if fault != 'late_waiter':
        assert private_control['scheduler'].state_path.read_bytes() == before[1]
    # Adversarial rows were fixture setup; restore before the fixture's ordinary
    # no-native-allocation teardown. The inspected API itself writes no state.
    if fault in ('native_root', 'native_orphan_descendant', 'native_waiter', 'late_waiter'):
        state = _json(private_control['scheduler'].state_path)
        state['leases'].clear()
        state['waiters'].clear()
        _write_json(private_control['scheduler'].state_path, state)


def test_actual_cli_acquired_native_admission_deadline_closes_source_without_child(private_control):
    """Real file-lock gates force the original active-update deadline branch.

    No producer, clock, lease, process or classifier is mocked. The pytest
    process and its genuine CLI are the only two processes this case needs.
    """
    control = private_control
    module, launcher, attempt, manifest, request, _ = _prepare_no_child_lifecycle(control)
    timeout = 2
    request['timeout_seconds'] = timeout
    request['child_process_slots'] = 1
    _write_json(manifest, request)
    request_raw = manifest.read_bytes()
    request_pin = _sha(manifest)
    evidence = attempt.parent.parent
    facts = dict(schema='private-real-lock-pre-child-deadline-observation/v1',
        request_sha256=request_pin, request_timeout_seconds=timeout, stages=[],
        original_cli_genuine_wait_completed=False, unexpected_cleanup_signal=False)
    cli = None
    original_identity = None
    ledger_fd = scheduler_fd = None
    stdout = stderr = None

    def stage(name, **values):
        facts['stages'].append(dict(stage=name, monotonic=time.monotonic(), **values))

    def unlock(which):
        nonlocal ledger_fd, scheduler_fd
        descriptor = ledger_fd if which == 'ledger' else scheduler_fd
        if descriptor is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
            if which == 'ledger': ledger_fd = None
            else: scheduler_fd = None

    def alive():
        current = native_disk._process(cli.pid)
        assert current is not None and original_identity is not None
        assert (current['pid'], current['birth']) == (cli.pid, original_identity['birth'])
        assert cli.poll() is None, facts

    def until(predicate, label, end):
        while True:
            alive()
            value = predicate()
            if value:
                return value
            remaining = end - time.monotonic()
            assert remaining > 0, (label, facts)
            time.sleep(min(.005, remaining))

    def take(path, label, end):
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return descriptor
                except BlockingIOError:
                    if cli is not None:
                        alive()
                    remaining = end - time.monotonic()
                    assert remaining > 0, (label, facts)
                    time.sleep(min(.005, remaining))
        except BaseException:
            os.close(descriptor)
            raise

    try:
        # Holding scheduler first would block its eager facade constructor,
        # before a reserved disk row could exist. Gate the initial ledger wait
        # first; its real descriptor proves both constructors have completed.
        ledger_path = control['ledger'].with_name(control['ledger'].name + '.lock')
        ledger_fd = take(ledger_path, 'initial ledger lock', time.monotonic()+1)
        lock_info = os.fstat(ledger_fd)
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
            IPFS_DATASETS_PY_MINIMAL_IMPORTS='1', IPFS_DATASETS_AUTO_INSTALL='0',
            IPFS_AUTO_INSTALL='false', TRANSFORMERS_OFFLINE='1', HF_HUB_OFFLINE='1',
            OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
        started = time.monotonic()
        cli = subprocess.Popen([sys.executable, '-B', str(launcher), '--request', str(manifest),
            '--expected-request-sha256', request_pin, '--resource-ledger', str(control['ledger'])],
            cwd=launcher.parents[3], env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, close_fds=True)
        original_identity = native_disk._process(cli.pid)
        assert original_identity is not None
        facts.update(owner_pid=cli.pid, owner_birth=original_identity['birth'], started_monotonic=started)
        stage('original_cli_created')

        def waiting_on_initial_ledger():
            with os.scandir(Path('/proc')/str(cli.pid)/'fd') as entries:
                for ordinal, entry in enumerate(entries):
                    assert ordinal < 128, 'bounded original CLI descriptor inventory required'
                    try:
                        observed = entry.stat(follow_symlinks=True)
                    except FileNotFoundError:
                        continue
                    if (observed.st_dev, observed.st_ino) == (lock_info.st_dev, lock_info.st_ino):
                        return entry.name
            return None

        descriptor = until(waiting_on_initial_ledger, 'initial ledger wait', started+timeout)
        stage('original_cli_reached_initial_ledger', descriptor=descriptor,
            lock_device=lock_info.st_dev, lock_inode=lock_info.st_ino)
        scheduler_fd = take(control['scheduler'].lock_path, 'scheduler gate', started+timeout)
        stage('scheduler_gate_held')
        unlock('ledger')

        def reserved_row():
            rows = [row for row in _json(control['ledger'])['reservations'].values()
                    if row.get('owner_pid') == cli.pid]
            assert len(rows) <= 1, facts
            if rows:
                assert rows[0]['status'] == 'reserved' and rows[0]['child'] is None, facts
                return rows[0]
            return None

        row = until(reserved_row, 'reserved original row', started+timeout)
        reserved_seen = time.monotonic()
        rid = row['reservation_id']
        stage('reserved_original_row_observed', reservation_id=rid)
        ledger_fd = take(ledger_path, 'active-update ledger gate', started+timeout)
        stage('active_update_ledger_gate_held')
        unlock('scheduler')

        def exact_grant():
            matches = [item for item in _json(control['scheduler'].state_path)['leases'].values()
                if item.get('request_id') == 'validation:'+rid]
            assert len(matches) <= 1, facts
            if not matches:
                return None
            item = matches[0]
            assert item['owner_pid'] == cli.pid and item['owner_birth_marker'] == original_identity['birth']
            assert item['parent_lease_id'] is None and item['lane'] == 'validation'
            return item

        granted = until(exact_grant, 'original real native grant', started+timeout)
        grant_seen = time.monotonic()
        # The admission epoch starts after Popen. Observing the grant before
        # this earlier bound proves it preceded the original admission end.
        assert grant_seen < started+timeout, facts
        stage('original_native_grant_observed_before_deadline', lease_id=granted['lease_id'],
            owner_birth_marker=granted['owner_birth_marker'])
        # The reserved row was observed after the admission epoch began, so
        # this later bound is strictly past its original two-second deadline.
        release_after = reserved_seen+timeout+.15
        assert release_after < started+2*timeout+.15, facts
        while time.monotonic() < release_after:
            alive()
            time.sleep(min(.01, max(0, release_after-time.monotonic())))
        stage('original_admission_deadline_passed_with_ledger_gate_held')
        unlock('ledger')
        stdout, stderr = cli.communicate(timeout=8)
        facts['original_cli_genuine_wait_completed'] = True
        facts['returncode'] = cli.returncode
        stage('original_cli_genuinely_waited')
        assert cli.returncode == 1, (stdout, stderr, facts)
        terminal = json.loads(stdout)
        facts['actual_terminal'] = terminal
        assert terminal['failure']['error_type'] == 'ResourceAdmissionDeadlineError', (stdout, stderr, facts)
        assert terminal['failure']['error'] == 'original absolute resource operation deadline expired'
        assert terminal['failure']['executed_checks'] == [] and terminal['failure']['returncode'] is None
        witness, reservation = terminal['source_custody_lifecycle'], terminal['reservation']
        assert witness['native_grant'] == {'status': 'acquired', 'exact_native_timeout': False, 'timeout_decision': None}
        assert witness['events'] == {key: key in ('owner_open_attempted', 'owner_exit_handling_completed')
            for key in module._LIFECYCLE_EVENTS}
        assert witness['owner_child_attached'] is False
        assert reservation['resource_lease']['lease_id'] == granted['lease_id']
        assert reservation['resource_lease']['released'] is True
        assert reservation['resource_lease']['cancelled'] is True
        actual_row = _json(control['ledger'])['reservations'][rid]
        assert len(actual_row) == 17 and actual_row == reservation['record']
        assert actual_row['status'] == 'retained' and actual_row['retention_reason'] == 'scheduler_admission_failed'
        assert actual_row['child'] is None and actual_row['prior_children'] == []
        with os.scandir(attempt) as entries:
            assert next(entries, None) is None
        native_after = _json(control['scheduler'].state_path)
        assert native_after['leases'] == {} and native_after['waiters'] == {}
        assert native_disk._process(cli.pid) is None
        caller = dict(expected_request_sha256=request_pin, owner_pid=cli.pid,
            owner_birth=original_identity['birth'], returncode=cli.returncode,
            expected_resource_ledger=str(control['ledger']))
        before = control['ledger'].read_bytes(), control['scheduler'].state_path.read_bytes()
        assert module.classify_owned_validation_source_custody(terminal, request_raw, **caller) == {
            'verdict': 'requires_original_native_cleanup', 'source_custody_closed': False,
            'storage_release_authorized': False}
        assert module.inspect_owned_validation_no_child_native_closed_v1(terminal, request_raw, **caller) == {
            'verdict': 'proven_original_no_child_native_closed', 'source_custody_closed': True,
            'storage_release_authorized': False}
        assert (control['ledger'].read_bytes(), control['scheduler'].state_path.read_bytes()) == before
        assert _json(control['ledger'])['reservations']['foreign-retained'] == control['foreign']
        facts['actual_readonly_verdict_proved_without_storage_release'] = True
    finally:
        # Release only this test's two real locks before observing/cleaning its
        # genuine CLI. Preserve unexpected output and state rather than retry.
        unlock('scheduler')
        unlock('ledger')
        try:
            if cli is not None and stdout is None:
                try:
                    stdout, stderr = cli.communicate(timeout=8)
                    facts['original_cli_genuine_wait_completed'] = True
                except subprocess.TimeoutExpired:
                    current = native_disk._process(cli.pid)
                    if current is not None:
                        assert original_identity is not None
                        assert (current['pid'], current['birth']) == (cli.pid, original_identity['birth'])
                        facts['unexpected_cleanup_signal'] = True
                        _stop_group(cli)
                    stdout, stderr = cli.communicate(timeout=2)
                facts['returncode'] = cli.returncode
        finally:
            (evidence/'actual-pre-child-deadline-owner.stdout').write_bytes(stdout or b'')
            (evidence/'actual-pre-child-deadline-owner.stderr').write_bytes(stderr or b'')
            facts['final_private_ledger'] = _json(control['ledger'])
            facts['final_private_native_state'] = _json(control['scheduler'].state_path)
            _write_json(evidence/'actual-pre-child-deadline-observation.json', facts)


# Existing-owner admission/production epoch regression controls, UNRUN.
# Module-local deterministic clocks; all schedulers/ledgers remain the original
# private_control fixture. No host workload, policy change or timer extension.
@pytest.mark.parametrize("live", [False, True], ids=["legacy-v1", "live-v4"])
def test_productive_epoch_begins_after_all_open_limits_checks(private_control, monkeypatch, live):
    control = private_control
    prepare = _live_census_prepare if live else lambda c, **kw: c["prepare"](**kw)
    _, _, _, kwargs = prepare(control, timeout_seconds=20)
    owner = _owner(control, kwargs)
    clock = _validation_admission_clock(monkeypatch)
    actual = owner.check_limits
    phases = []
    def delayed_first_limits(*, full=False):
        operation = native.resource_operation_deadline()
        opening_state = (getattr(owner, "_opening", False), owner._started, owner._admission_started,
                         operation.work_deadline_monotonic if operation else None,
                         operation.native_deadline_monotonic if operation else None)
        clock.now = 105.0
        value = actual(full=full)
        phases.append(opening_state)
        return value
    monkeypatch.setattr(owner, "check_limits", delayed_first_limits)
    try:
        assert owner.open() is owner
        assert owner._started == 105.0
        assert phases == [(True, None, 100.0, 120.0, 120.0)]
        assert not owner._opening
        assert owner._admission_started == 100.0
        assert native.resource_operation_deadline() is None
        clock.now = 121.0
        assert owner.guard()
        assert owner.heartbeat()
        assert owner._started == 105.0 and owner._admission_started == 100.0
        with pytest.raises(validation.ValidationResourceError, match="already open"):
            owner.open()
        assert owner._started == 105.0 and owner._admission_started == 100.0
        clock.now = 126.0
        with pytest.raises(validation.ValidationResourceError, match="run deadline"):
            owner.guard()
    finally:
        if owner._opened:
            owner.__exit__(None, None, None)
    assert control["scheduler"].snapshot()["allocated"]["cpu_slots"] == 0


@pytest.mark.parametrize("live", [False, True], ids=["legacy-v1", "live-v4"])
def test_post_native_open_check_expiry_never_starts_productive_epoch(private_control, monkeypatch, live):
    control = private_control
    prepare = _live_census_prepare if live else lambda c, **kw: c["prepare"](**kw)
    _, _, _, kwargs = prepare(control, timeout_seconds=20)
    owner = _owner(control, kwargs)
    clock = _validation_admission_clock(monkeypatch)
    actual = owner.check_limits
    def expire_open_check(*, full=False):
        actual(full=full)
        clock.now = 121.0
    monkeypatch.setattr(owner, "check_limits", expire_open_check)
    with pytest.raises(native.ResourceAdmissionDeadlineError):
        owner.open()
    assert owner._admission_started == 100.0 and owner._started is None
    assert not owner._opened and not owner._opening
    assert native.resource_operation_deadline() is None
    assert control["scheduler"].snapshot()["allocated"]["cpu_slots"] == 0
    row = _json(control["ledger"])["reservations"][owner.reservation_id]
    assert row["status"] == "retained" and row["retention_reason"] == "context_failed"
    assert row["storage_bytes"] == kwargs["storage_bytes"]
    with pytest.raises(native.ResourceAdmissionDeadlineError):
        owner.open()
    assert owner._admission_started == 100.0 and owner._started is None


def test_post_native_open_setup_preserves_original_parent_clock_clipping(private_control, monkeypatch):
    control = private_control
    _, _, _, kwargs = _live_census_prepare(control, timeout_seconds=20)
    owner = _owner(control, kwargs)
    clock = _validation_admission_clock(monkeypatch)
    actual = owner.check_limits
    phases = []
    def clipped_limits(*, full=False):
        operation = native.resource_operation_deadline()
        phases.append((operation.work_deadline_monotonic if operation else None,
                       operation.native_deadline_monotonic if operation else None))
        clock.now = 109.0
        return actual(full=full)
    monkeypatch.setattr(owner, "check_limits", clipped_limits)
    try:
        with native.resource_admission_deadline(work_deadline_monotonic=110.0,
                                                native_deadline_monotonic=150.0):
            previous = native.resource_operation_deadline()
            assert owner.open() is owner
            assert native.resource_operation_deadline() is previous
            assert owner._started == 109.0 and owner._admission_started == 100.0
            assert phases == [(110.0, 150.0)]
        assert native.resource_operation_deadline() is None
        assert not owner._opening
    finally:
        if owner._opened:
            owner.__exit__(None, None, None)
    assert control["scheduler"].snapshot()["allocated"]["cpu_slots"] == 0


@pytest.mark.parametrize("live", [False, True], ids=["legacy-v1", "live-v4"])
def test_base_postgrant_failure_keeps_original_cleanup_outside_admission_scope(private_control, monkeypatch, live):
    control = private_control
    prepare = _live_census_prepare if live else lambda c, **kw: c["prepare"](**kw)
    _, _, _, kwargs = prepare(control, timeout_seconds=20)
    owner = _owner(control, kwargs)
    clock = _validation_admission_clock(monkeypatch)
    actual_update, actual_retain = owner._update, owner._retain
    sentinel = native.ResourceAdmissionDeadlineError("authored post-grant original admission expiry")
    cleanup = []
    def retain(reason):
        cleanup.append(("retain", reason, native.resource_operation_deadline()))
        return actual_retain(reason)
    def postgrant_update(**fields):
        value = actual_update(**fields)
        if fields.get("status") == "active":
            assert owner._lease is not None and owner._record["status"] == "active"
            actual_release = owner._lease.release
            def release():
                cleanup.append(("native_release", native.resource_operation_deadline()))
                return actual_release()
            monkeypatch.setattr(owner._lease, "release", release)
            clock.now = 121.0
            raise sentinel
        return value
    monkeypatch.setattr(owner, "_retain", retain)
    monkeypatch.setattr(owner, "_update", postgrant_update)
    with pytest.raises(native.ResourceAdmissionDeadlineError) as caught:
        owner.open()
    assert caught.value is sentinel
    assert cleanup == [("retain", "scheduler_admission_failed", None), ("native_release", None)]
    assert owner._admission_started == 100.0 and owner._started is None
    assert not owner._opened and not owner._opening
    assert native.resource_operation_deadline() is None
    row = _json(control["ledger"])["reservations"][owner.reservation_id]
    assert row["status"] == "retained" and row["retention_reason"] == "scheduler_admission_failed"
    assert row["storage_bytes"] == kwargs["storage_bytes"]
    assert owner.to_dict()["cleanup_error"] is None
    assert control["scheduler"].snapshot()["allocated"]["cpu_slots"] == 0


@pytest.mark.parametrize("native_expired", [False, True], ids=["original-native-cleanup", "expired-native-retained"])
def test_post_setup_failure_uses_only_original_parent_cleanup_end_and_keeps_primary(
        private_control, monkeypatch, native_expired):
    control = private_control
    _, _, _, kwargs = _live_census_prepare(control, timeout_seconds=20)
    owner = _owner(control, kwargs)
    clock = _validation_admission_clock(monkeypatch)
    actual_limits, actual_retain = owner.check_limits, owner._retain
    sentinel = validation.ValidationResourceError("authored post-native setup failure")
    cleanup = []
    def phase():
        operation = native.resource_operation_deadline()
        return (operation.cleanup_only, operation.work_deadline_monotonic,
                operation.native_deadline_monotonic) if operation else None
    def retain(reason):
        cleanup.append(("retain", reason, phase()))
        return actual_retain(reason)
    def fail_after_actual_limits(*, full=False):
        actual_limits(full=full)
        actual_release = owner._lease.release
        def release():
            cleanup.append(("native_release", phase()))
            return actual_release()
        monkeypatch.setattr(owner._lease, "release", release)
        clock.now = 151.0 if native_expired else 111.0
        raise sentinel
    monkeypatch.setattr(owner, "_retain", retain)
    monkeypatch.setattr(owner, "check_limits", fail_after_actual_limits)
    try:
        with native.resource_admission_deadline(work_deadline_monotonic=110.0,
                                                native_deadline_monotonic=150.0):
            original = native.resource_operation_deadline()
            with pytest.raises(validation.ValidationResourceError) as caught:
                owner.open()
            assert caught.value is sentinel
            assert native.resource_operation_deadline() is original
            assert owner._admission_started == 100.0 and owner._started is None
            assert not owner._opening
            if native_expired:
                assert cleanup == [] and owner._opened
                assert owner._cleanup_error == "ResourceAdmissionDeadlineError"
                row = _json(control["ledger"])["reservations"][owner.reservation_id]
                assert row["status"] == "active" and row["storage_bytes"] == kwargs["storage_bytes"]
            else:
                assert cleanup == [("retain", "context_failed", (True, 150.0, 150.0)),
                                   ("native_release", (True, 150.0, 150.0))]
                assert not owner._opened and owner._cleanup_error is None
                row = _json(control["ledger"])["reservations"][owner.reservation_id]
                assert row["status"] == "retained" and row["retention_reason"] == "context_failed"
        assert native.resource_operation_deadline() is None
        assert control["scheduler"].snapshot()["allocated"]["cpu_slots"] == (1 if native_expired else 0)
    finally:
        # The failed expired-native observation remains unknown. This is the
        # test's genuine original private owner, explicitly closed only AFTER
        # leaving the authored parent context, to avoid leaking a fixture grant.
        if owner._opened:
            owner.__exit__(RuntimeError, RuntimeError("explicit private fixture cleanup"), None)
    assert control["scheduler"].snapshot()["allocated"]["cpu_slots"] == 0


# V5 explicitly allows sampled unknown scratch absence; it never proves that an
# unseen leaf was regular/owned and grants no special-leaf or final-seal allowance.
def _ordinary_scratch_prepare(control, **kwargs):
    def enable(value):
        value['schema'] = 'owned-validation-request/v5'
        value['ordinary_scratch_profile'] = {'schema': 'owned-validation-ordinary-scratch-live/v1'}
    return control['prepare'](mutate=enable, **kwargs)


def _ordinary_scratch_stat_hook(monkeypatch, owned, target, *, observed=False, reappear=None):
    actual = os.stat
    parent = target.parent.stat()
    state = dict(calls=0, successful_leaf_stats=0, removed=False)
    def sampling_stat(path, *args, **options):
        descriptor = options.get('dir_fd')
        selected = (descriptor is not None and path == target.name
            and options.get('follow_symlinks') is False)
        if selected:
            opened = os.fstat(descriptor)
            selected = (opened.st_dev, opened.st_ino) == (parent.st_dev, parent.st_ino)
        if selected:
            state['calls'] += 1
            remove_at = 2 if observed else 1
            if state['calls'] == remove_at:
                target.unlink();state['removed'] = True
            if reappear is not None and state['calls'] == remove_at + 2:
                target.write_bytes(b'reappeared ordinary backing leaf')
        result = actual(path, *args, **options)
        if selected:
            state['successful_leaf_stats'] += 1
            if reappear in ('symlink', 'fifo') and state['calls'] == remove_at + 2:
                values = list(result)
                values[0] = (stat.S_IFLNK if reappear == 'symlink' else stat.S_IFIFO) | 0o600
                result = os.stat_result(values)
                state['injected_kind'] = reappear
        return result
    monkeypatch.setattr(os, 'stat', sampling_stat)
    return state


@pytest.mark.parametrize('name', ['.scheduler.json.PID.UUID.tmp', '.daemon-reservation-actual'])
def test_ordinary_scratch_v5_samples_first_stat_absence_without_claiming_leaf_ownership(private_control, monkeypatch, name):
    c = private_control
    attempt, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        target = owned.output_layout['tmp'] / name
        target.write_bytes(b'unobserved temporary payload')
        with monkeypatch.context() as patch:
            state = _ordinary_scratch_stat_hook(patch, owned, target)
            sampled = owned._usage_inventory(attempt)
        assert state == dict(calls=3, successful_leaf_stats=0, removed=True)
        assert sampled['apparent_bytes'] == 0
        assert sampled['symlink_count'] == sampled['special_file_count'] == 0
        profile = owned.to_dict()['ordinary_scratch_profile']
        assert profile['ordinary_absences_observed'] == 1
        assert profile['unseen_leaf_ownership_attested'] is False
        assert profile['whole_census_resampling'] is False
        assert profile['live_exception_active'] is True
        assert owned._live_inventory_resamples == 0 and not target.exists()
        assert owned._physical_profile is None and owned._physical_entries == {}


def test_ordinary_scratch_v5_charges_previously_observed_regular_bytes_after_loss(private_control, monkeypatch):
    c = private_control
    attempt, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        target = owned.output_layout['tmp'] / 'observed.bin';payload = b'charged bytes' * 31
        target.write_bytes(payload)
        with monkeypatch.context() as patch:
            state = _ordinary_scratch_stat_hook(patch, owned, target, observed=True)
            sampled = owned._usage_inventory(attempt)
        assert state == dict(calls=4, successful_leaf_stats=1, removed=True)
        assert sampled['apparent_bytes'] == len(payload)
        assert owned.to_dict()['ordinary_scratch_profile']['ordinary_absences_observed'] == 1


@pytest.mark.parametrize('kind', ['regular', 'symlink', 'fifo'])
def test_ordinary_scratch_v5_refuses_reappearance_with_injected_special_metadata(private_control, monkeypatch, kind):
    c = private_control
    attempt, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        target = owned.output_layout['tmp'] / 'reappearing';target.write_bytes(b'gone')
        try:
            with monkeypatch.context() as patch:
                state = _ordinary_scratch_stat_hook(patch, owned, target, reappear=kind)
                with pytest.raises(validation.ValidationResourceError, match='reappeared'):
                    owned._usage_inventory(attempt)
            assert state.get('injected_kind') == (None if kind == 'regular' else kind)
            assert owned.to_dict()['ordinary_scratch_profile']['ordinary_absences_observed'] == 0
        finally:
            target.unlink(missing_ok=True)


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'fifo'])
def test_ordinary_scratch_v5_refuses_injected_unsafe_leaf_metadata(private_control, monkeypatch, kind):
    """Real ordinary leaves remain safe for the outer census; metadata is injected."""
    c = private_control
    attempt, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        target = owned.output_layout['tmp'] / 'unsafe-metadata';target.write_bytes(b'ordinary backing')
        actual, injected = os.stat, []
        def unsafe_stat(path, *args, **options):
            result = actual(path, *args, **options)
            if options.get('dir_fd') is not None and path == target.name:
                values = list(result)
                if kind == 'hardlink': values[3] = 2
                else: values[0] = (stat.S_IFLNK if kind == 'symlink' else stat.S_IFIFO) | 0o600
                injected.append(kind)
                return os.stat_result(values)
            return result
        try:
            with monkeypatch.context() as patch:
                patch.setattr(os, 'stat', unsafe_stat)
                with pytest.raises(validation.ValidationResourceError): owned._usage_inventory(attempt)
            assert injected == [kind]
        finally:
            target.unlink()


@pytest.mark.parametrize('which', ['attempt', 'output'])
def test_ordinary_scratch_v5_rejects_replaced_bound_directory(private_control, which):
    c = private_control
    attempt, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        target = attempt if which == 'attempt' else owned.output_layout['tmp']
        old = target.with_name(target.name + '-preserved')
        target.rename(old);target.mkdir(mode=0o700)
        try:
            with pytest.raises((validation.ValidationResourceError, native_disk.DaemonResourceError)):
                owned._usage_inventory(attempt)
        finally:
            target.rmdir();old.rename(target)


@pytest.mark.parametrize('boundary', ['deadline', 'formal_stop'])
def test_ordinary_scratch_v5_rechecks_same_clock_and_stop_inside_walk(private_control, monkeypatch, boundary):
    from types import SimpleNamespace
    c = private_control
    attempt, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        target = owned.output_layout['tmp'] / 'fence';target.write_bytes(b'fence')
        actual_stat, actual_time, started = os.stat, validation.time, owned._started
        reached = []
        def clock():
            return actual_time.monotonic() + (kwargs['timeout_seconds'] + 1 if reached else 0)
        def change_inside(path, *args, **options):
            result = actual_stat(path, *args, **options)
            if options.get('dir_fd') is not None and path == target.name and not reached:
                reached.append(True)
                if boundary == 'formal_stop': owned._require_processes_stopped()
            return result
        with monkeypatch.context() as patch:
            patch.setattr(os, 'stat', change_inside)
            if boundary == 'deadline': patch.setattr(validation, 'time', SimpleNamespace(monotonic=clock))
            with pytest.raises(validation.ValidationResourceError): owned._usage_inventory(attempt)
        assert reached == [True] and owned._started == started
        assert owned._live_inventory_in_progress is False and owned._live_inventory_thread is None


def test_ordinary_scratch_v5_stopped_sample_reverts_to_strict_inventory(private_control, monkeypatch):
    from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_daemon_resources import _owned_live_unobserved_leaf_disappearance
    c = private_control
    attempt, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        owned._require_processes_stopped()
        assert owned.to_dict()['ordinary_scratch_profile']['live_exception_active'] is False
        with monkeypatch.context() as patch:
            target, removed = _owned_live_unobserved_leaf_disappearance(patch, native_disk, owned.output_layout['tmp'])
            with pytest.raises(FileNotFoundError): owned._usage_inventory(attempt)
        assert removed == [True] and not target.exists()
        assert owned._live_inventory_active is False


@pytest.mark.parametrize('malformed', [{}, {'schema':'owned-validation-ordinary-scratch-live/v1','extra':1}, {'schema':'owned-validation-live-census/v1'}])
def test_ordinary_scratch_v5_profile_is_closed_before_admission(private_control, malformed):
    c = private_control
    def enable(value):
        value['schema'] = 'owned-validation-request/v5';value['ordinary_scratch_profile'] = malformed
    _, _, _, kwargs = c['prepare'](mutate=enable)
    original = c['ledger'].read_bytes()
    with pytest.raises(validation.ValidationResourceError): _owner(c, kwargs)
    assert c['ledger'].read_bytes() == original


@pytest.mark.parametrize('version, omit_pin, error, message', [
    ('v1', True, RuntimeError, 'run owned validation in a fresh process'),
    ('v2', True, RuntimeError, 'run owned validation in a fresh process'),
    ('v4', True, RuntimeError, 'run owned validation in a fresh process'),
    ('v5', True, ValueError, 'explicit original lifecycle owner source pins required'),
    ('v5', False, RuntimeError, 'run owned validation in a fresh process'),
])
def test_cli_requires_complete_lifecycle_pins_before_v5_native_entry(
        private_control, version, omit_pin, error, message):
    control = private_control
    module, _, attempt, manifest, request, _ = _prepare_no_child_lifecycle(control)
    request['schema'] = 'owned-validation-request/' + version
    if version == 'v5':
        request['ordinary_scratch_profile'] = {'schema': 'owned-validation-ordinary-scratch-live/v1'}
    if omit_pin:
        source = Path(native.__file__).with_name('proof_resource_safety.py').resolve()
        assert source.is_file()
        request['source_sha256'].pop(str(source))
    _write_json(manifest, request)
    ledger_before = control['ledger'].read_bytes()
    scheduler_before = control['scheduler'].state_path.read_bytes()
    # The CLI's existing fresh-process guard is the boundary sentinel here.
    with pytest.raises(error, match=message):
        module.main(['--request', str(manifest), '--expected-request-sha256', _sha(manifest),
                     '--resource-ledger', str(control['ledger'])])
    assert control['ledger'].read_bytes() == ledger_before
    assert control['scheduler'].state_path.read_bytes() == scheduler_before
    assert not tuple(attempt.iterdir())


def _actual_ordinary_scratch_no_child_cli(control, monkeypatch):
    original_prepare = _prepare_no_child_lifecycle
    def prepare_scratch(c):
        module, launcher, attempt, manifest, request, kwargs = original_prepare(c)
        request['schema'] = 'owned-validation-request/v5'
        request['ordinary_scratch_profile'] = {'schema':'owned-validation-ordinary-scratch-live/v1'}
        _write_json(manifest, request);kwargs['frozen_validation_manifest_sha256'] = _sha(manifest)
        return module, launcher, attempt, manifest, request, kwargs
    with monkeypatch.context() as patch:
        patch.setitem(globals(), '_prepare_no_child_lifecycle', prepare_scratch)
        return _actual_no_child_cli(control)


def test_actual_v5_cli_native_timeout_proves_only_exact_no_child_no_grant_custody(private_control, monkeypatch):
    module, terminal, raw, caller, attempt = _actual_ordinary_scratch_no_child_cli(private_control, monkeypatch)
    assert module.classify_owned_validation_source_custody(terminal, raw, **caller) == {
        'verdict':'proven_original_no_child_no_native_grant','source_custody_closed':True,'storage_release_authorized':False}
    reservation = terminal['reservation']
    assert reservation['ordinary_scratch_profile'] == {
        'schema':'owned-validation-ordinary-scratch-live/v1','request_sha256':caller['expected_request_sha256'],
        'ordinary_absences_observed':0,'live_exception_active':False,
        'unseen_leaf_ownership_attested':False,'whole_census_resampling':False}
    assert reservation['resource_lease'] is None and reservation['process_observation'] is None
    assert reservation['record']['status'] == 'retained' and not tuple(attempt.iterdir())
    changed = deepcopy(terminal);changed['reservation']['ordinary_scratch_profile']['unseen_leaf_ownership_attested'] = True
    assert module.classify_owned_validation_source_custody(changed, raw, **caller) == _live_no_child_unknown()
    assert module.inspect_owned_validation_no_child_native_closed_v1(terminal, raw, **caller) == _live_no_child_unknown()


@pytest.mark.parametrize('overflow', [False, True])
def test_ordinary_scratch_v5_enforces_inclusive_entry_limit_with_actual_scandir(private_control, monkeypatch, overflow):
    c = private_control
    attempt, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        assert validation.MAX_DURABILITY_ENTRIES == 20_000
        (owned.output_layout['tmp'] / 'at-edge').write_bytes(b'edge')
        if overflow: (owned.output_layout['tmp'] / 'over-edge').write_bytes(b'overflow')
        # Lower only this unit fixture's limit: six output directories + one leaf.
        with monkeypatch.context() as patch:
            patch.setattr(validation, 'MAX_DURABILITY_ENTRIES', 7)
            if overflow:
                with pytest.raises(validation.ValidationResourceError, match='entry bound'):
                    owned._usage_inventory(attempt)
            else:
                assert owned._usage_inventory(attempt)['entry_count'] == 7


@pytest.mark.parametrize('overflow', [False, True])
def test_ordinary_scratch_v5_enforces_real_depth32_boundary(private_control, overflow):
    c = private_control
    attempt, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        current = owned.output_layout['tmp']
        for index in range(30 + int(overflow)):
            current /= 'd' + str(index);current.mkdir(mode=0o700)
        (current / 'leaf').write_bytes(b'bounded-depth')
        if overflow:
            with pytest.raises(validation.ValidationResourceError, match='depth bound'):
                owned._usage_inventory(attempt)
        else:
            assert owned._usage_inventory(attempt)['apparent_bytes'] == len(b'bounded-depth')


def test_ordinary_scratch_v5_rejects_observed_byte_overrun_before_return(private_control):
    c = private_control
    attempt, _, _, kwargs = _ordinary_scratch_prepare(c, storage_bytes=1000)
    with _owner(c, kwargs) as owned:
        target = owned.output_layout['tmp'] / 'large';target.write_bytes(b'x' * 1001)
        try:
            with pytest.raises(validation.ValidationResourceError, match='storage limit'):
                owned._usage_inventory(attempt)
        finally: target.unlink()


def test_ordinary_scratch_v5_real_threads_serialize_the_same_descriptor_walker(private_control, monkeypatch):
    import threading
    c = private_control
    attempt, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        entered, release, waiting = threading.Event(), threading.Event(), threading.Event()
        first_done, second_done = threading.Event(), threading.Event()
        outcomes, samples, occupancy = {}, [], {'active':0,'maximum':0}
        sample_lock, actual_walk = threading.Lock(), owned._physical_inventory
        def walk(**options):
            label = threading.current_thread().name
            with sample_lock:
                occupancy['active'] += 1;occupancy['maximum'] = max(occupancy['maximum'], occupancy['active'])
                samples.append((label, options))
            try:
                if label == 'scratch-first':
                    entered.set();assert release.wait(timeout=2)
                return actual_walk(**options)
            finally:
                with sample_lock: occupancy['active'] -= 1
        actual_lock = owned._live_inventory_lock
        def acquiring(duration):
            assert 0 < duration <= 0.100001
            if threading.current_thread().name == 'scratch-second': waiting.set()
        with monkeypatch.context() as patch:
            patch.setattr(owned, '_physical_inventory', walk)
            patch.setattr(owned, '_live_inventory_lock', _ObservedLiveCensusLock(actual_lock, acquiring))
            workers = [threading.Thread(name='scratch-first', daemon=True, target=_live_census_thread_worker,
                    args=(owned, attempt, 'first', outcomes, first_done)),
                threading.Thread(name='scratch-second', daemon=True, target=_live_census_thread_worker,
                    args=(owned, attempt, 'second', outcomes, second_done))]
            started = owned._started
            try:
                workers[0].start();assert entered.wait(timeout=2)
                workers[1].start();assert waiting.wait(timeout=2)
                assert not second_done.is_set()
            finally: _join_live_census_test_workers(workers, release)
        assert all(outcomes[key][0] == 'ok' for key in ('first','second')), repr(outcomes)
        assert outcomes['first'][1] == outcomes['second'][1]
        assert samples == [('scratch-first', {'ordinary_scratch':True}), ('scratch-second', {'ordinary_scratch':True})]
        assert occupancy == {'active':0,'maximum':1} and owned._started == started
        assert owned._live_inventory_thread is None and owned._live_inventory_in_progress is False


@pytest.mark.parametrize('fence', ['deadline', 'cancellation', 'formal_stop'])
def test_ordinary_scratch_v5_waiter_keeps_original_clock_and_refuses_closed_custody(private_control, monkeypatch, fence):
    import threading
    c = private_control
    attempt, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        actual_time, started, timeout = validation.time, owned._started, owned.validation_timeout_seconds
        clock_started = actual_time.monotonic()
        class OwnerClock:
            def monotonic(self): return started + timeout - 0.2 + (actual_time.monotonic() - clock_started)
            def __getattr__(self, name): return getattr(actual_time, name)
        actual_lock = owned._live_inventory_lock
        attempted, done, release = threading.Event(), threading.Event(), threading.Event()
        outcomes, scans = {}, []
        def acquiring(duration):
            assert 0 < duration <= 0.100001;attempted.set()
        def forbidden_walk(**options):
            scans.append(options);raise AssertionError('closed waiter entered a live walk')
        worker = threading.Thread(name='scratch-fenced-waiter', daemon=True, target=_live_census_thread_worker,
            args=(owned, attempt, 'waiter', outcomes, done))
        actual_lock.acquire()
        try:
            with monkeypatch.context() as patch:
                patch.setattr(owned, '_live_inventory_lock', _ObservedLiveCensusLock(actual_lock, acquiring))
                patch.setattr(owned, '_physical_inventory', forbidden_walk)
                if fence == 'deadline': patch.setattr(validation, 'time', OwnerClock())
                try:
                    worker.start();assert attempted.wait(timeout=2)
                    if fence == 'cancellation': assert owned._lease.cancel() is True
                    elif fence == 'formal_stop': owned._require_processes_stopped()
                    worker.join(timeout=2)
                    assert not worker.is_alive() and done.is_set()
                    assert outcomes['waiter'][0] == 'error'
                    assert isinstance(outcomes['waiter'][1], validation.ValidationResourceError)
                    assert scans == []
                finally:
                    actual_lock.release();_join_live_census_test_workers([worker], release)
        finally: assert not worker.is_alive()
        assert validation.time is actual_time and owned._started == started
        assert owned._live_inventory_thread is None and owned._live_inventory_in_progress is False


def test_ordinary_scratch_v5_strips_ambient_physical_transport_without_special_slots(private_control):
    c = private_control
    _, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        environment = owned.environment({validation.PHYSICAL_REQUEST_ENV:'/fictional/request',
            validation.PHYSICAL_REQUEST_SHA_ENV:'a'*64,'KEEP':'value'})
        assert validation.PHYSICAL_REQUEST_ENV not in environment
        assert validation.PHYSICAL_REQUEST_SHA_ENV not in environment
        assert environment['KEEP'] == 'value'
        assert owned._physical_profile is None and owned._physical_cases == {} and owned._physical_entries == {}


@pytest.mark.parametrize('extra', ['physical_fixture_profile','live_inventory_profile','unknown'])
def test_ordinary_scratch_v5_never_combines_another_profile(private_control, extra):
    c = private_control
    def enable(value):
        value['schema'] = 'owned-validation-request/v5'
        value['ordinary_scratch_profile'] = {'schema':'owned-validation-ordinary-scratch-live/v1'}
        value[extra] = {}
    _, _, _, kwargs = c['prepare'](mutate=enable)
    original = c['ledger'].read_bytes()
    with pytest.raises(validation.ValidationResourceError): _owner(c, kwargs)
    assert c['ledger'].read_bytes() == original


def test_ordinary_scratch_v5_preserves_peer_admission_and_productive_epochs(private_control, monkeypatch):
    """Replay the existing peer phase-clock control through real V5 admission."""
    original_prepare = private_control['prepare']
    def prepare_scratch(**kwargs):
        def enable(value):
            value['schema'] = 'owned-validation-request/v5'
            value['ordinary_scratch_profile'] = {'schema':'owned-validation-ordinary-scratch-live/v1'}
        return original_prepare(mutate=enable, **kwargs)
    with monkeypatch.context() as patch:
        patch.setitem(private_control, 'prepare', prepare_scratch)
        test_productive_epoch_begins_after_all_open_limits_checks(private_control, patch, False)


# New productive-native-closed tests: the synthetic fixture below is only a
# binding/adversarial control. It has no genuine Popen/historical grant proof.
# The separate actual-CLI test exercises genuine admission, child, held lock,
# failed retention and native cleanup without clearing its ACTIVE storage row.
def _productive_failed_retention_binding_fixture(control):
    module, launcher, attempt, manifest, request, _ = _prepare_no_child_lifecycle(control)
    request['schema'] = 'owned-validation-request/v5'
    request['ordinary_scratch_profile'] = {'schema':'owned-validation-ordinary-scratch-live/v1'}
    package_root = Path(validation.__file__).resolve().parents[3]
    recovery = Path(native_disk.__file__).with_name('autoencoder_resource_recovery.py')
    process_owner = package_root/'ipfs_datasets_py/logic/backends/process.py'
    request['source_sha256'].update({str(path.resolve()):_sha(path) for path in (recovery,process_owner)})
    _write_json(manifest,request)
    raw,pin = manifest.read_bytes(),_sha(manifest)
    owner,birth,child,child_birth,rid,lid = 1_000_000_000,'123456',1_000_000_001,123457,'a'*32,'b'*32
    row = dict(reservation_id=rid,status='active',owner_pid=owner,owner_birth=birth,
        storage_bytes=request['storage_bytes'],memory_mb=request['memory_mb'],cpu_slots=request['cpu_slots'],
        child_process_slots=request['child_process_slots'],external_charges={},created_at=100.0,
        prior_children=[],child=dict(pid=child,birth=str(child_birth)),artifacts_durable_asserted=False,
        scheduler_lane='validation',workload='canonical_validation',attempt_directory=native_disk._root_identity(attempt),
        last_usage={},native_lease_id=lid,outputs=deepcopy(request['outputs']),process_scope=request['process_scope'],
        scheduler_state_path=request['scheduler_state_path'],scheduler_policy_sha256=request['expected_scheduler_policy_sha256'],
        validation_request_sha256=pin)
    ledger = _json(control['ledger']);ledger['reservations'][rid] = deepcopy(row);_write_json(control['ledger'],ledger)
    lease = dict(lease_id=lid,lane='validation',owner_pid=owner,parent_lease_id=None,
        cpu_slots=request['cpu_slots'],memory_mb=request['memory_mb'],child_process_slots=request['child_process_slots'],
        gpu_memory_mb=0,unified_memory_mb=0,requires_gpu=False,acquired_at=100.1,wait_seconds=.001,
        released=True,cancelled=True)
    observation = dict(scope='sampled_birth_bound_descendants',group_rss=dict(available=True,live_processes=0,rss_bytes=0),
        live_processes=0,rss_bytes=0,observed_identities=[dict(pid=child,birth_ticks=child_birth,parent_pid=owner,
            process_group_id=child,session_id=child)],out_of_group_live_identities=[],tracking_error='')
    diagnostic = dict(schema='owned-resource-cleanup-failure/v1',stage='failure_retention',error_kind='daemon_resource_error',
        reason_code='unclassified',lock_observation_status='absent',lock_observation=None)
    reservation = dict(schema=native_disk.SCHEMA,ledger_path=str(control['ledger']),reservation_id=rid,status='active',
        record=row,resource_lease=lease,process_observation=observation,cleanup_error='DaemonResourceError',
        roots=deepcopy(ledger['roots']),scheduler_lane='validation',workload='canonical_validation',
        storage_limit_bytes=native_disk.MAX_STORAGE_BYTES,enforcement='cooperative_admission_and_polled_usage_not_kernel_quota',
        cleanup_failure_observations=[diagnostic],cleanup_failure_observation_overflow=False,
        ordinary_scratch_profile=dict(schema='owned-validation-ordinary-scratch-live/v1',request_sha256=pin,
            ordinary_absences_observed=0,live_exception_active=False,unseen_leaf_ownership_attested=False,whole_census_resampling=False))
    witness = dict(schema=module.LIFECYCLE_SCHEMA,request_sha256=pin,
        producer=dict(path=str(launcher),sha256=_sha(launcher)),owner=dict(pid=owner,birth=birth),
        reservation_id=rid,resource_request_id='validation:'+rid,ledger_path=str(control['ledger']),
        scheduler=dict(state_path=request['scheduler_state_path'],policy_sha256=request['expected_scheduler_policy_sha256'],
            lane='validation',workload='canonical_validation'),attempt_directory=str(attempt),outputs=deepcopy(request['outputs']),
        budgets={key:request[key] for key in ('cpu_slots','memory_mb','child_process_slots','storage_bytes')},
        process_scope=request['process_scope'],events={key:True for key in module._LIFECYCLE_EVENTS},owner_child_attached=True,
        native_grant=dict(status='acquired',exact_native_timeout=False,timeout_decision=None),
        source_guards=dict(request_unchanged=True,source_pins_unchanged=True,owner_identity_unchanged=True,errors=[]),
        storage=dict(status='active',cleanup_error='DaemonResourceError',release_authorized=False,
            cleanup_failure_observations=deepcopy(reservation['cleanup_failure_observations']),cleanup_failure_observation_overflow=False))
    failure = dict(schema='owned-validation-result/v1',request_sha256=pin,executed_checks=deepcopy(request['selected_checks']),
        returncode=7,completed=False,admitted=False,Lean_admitted=False,
        resource_scope='cooperative_sampled_birth_bound_descendants_and_owned_attempt',model_weights_downloaded=False,
        authority_granted=False,error_type='RuntimeError',error='validation command failed with returncode 7',elapsed_seconds=1.0,
        watchdog_errors=[],received_signals=[],process_observation=deepcopy(observation),process_cleanup_error=None)
    terminal = dict(schema='owned-validation-failure-terminal/v1',request_sha256=pin,completed=False,admitted=False,
        Lean_admitted=False,failure=failure,reservation=reservation,source_custody_lifecycle=witness,
        process_cleanup_error=None,owner_exit_error=None)
    caller = dict(expected_request_sha256=pin,owner_pid=owner,owner_birth=birth,returncode=1,
        expected_resource_ledger=str(control['ledger']))
    return module,terminal,raw,caller,attempt


def test_productive_failed_retention_binding_and_read_only_native_absence(private_control):
    module,terminal,raw,caller,_ = _productive_failed_retention_binding_fixture(private_control)
    before = private_control['ledger'].read_bytes(),private_control['scheduler'].state_path.read_bytes()
    value,witness,reservation,row,lease = module._productive_native_closed_profile_v1(terminal,raw,**caller)
    assert row['status'] == reservation['status'] == 'active'
    assert row['storage_bytes'] == value['storage_bytes'] and lease['released'] is True
    assert module.inspect_owned_validation_productive_native_closed_v1(terminal,raw,**caller,
        original_wait_deadline_monotonic=time.monotonic()+3) == {
            'verdict':'proven_original_productive_native_closed_storage_separate',
            'source_custody_closed':True,'storage_release_authorized':False}
    assert before == (private_control['ledger'].read_bytes(),private_control['scheduler'].state_path.read_bytes())
    assert _json(private_control['ledger'])['reservations'][row['reservation_id']] == row


@pytest.mark.parametrize('fault', ['completed','owner_exit_error','process_cleanup_error','producer',
    'owner_birth','event','no_child','diagnostic_missing','diagnostic_stage','diagnostic_overflow',
    'lease_unreleased','lease_wrong_id','budget_boolean','row_birth','child_birth','identity_missing',
    'identity_cycle','identity_duplicate','tracking_error','live_group','scratch_active','witness_storage'])
def test_productive_closed_binding_rejects_unproven_terminal_fields(private_control,fault):
    module,terminal,raw,caller,_ = _productive_failed_retention_binding_fixture(private_control)
    r,w = terminal['reservation'],terminal['source_custody_lifecycle']
    if fault == 'completed': terminal['completed'] = True
    elif fault == 'owner_exit_error': terminal['owner_exit_error'] = 'failed'
    elif fault == 'process_cleanup_error': terminal['process_cleanup_error'] = 'unknown'
    elif fault == 'producer': w['producer']['sha256'] = 'c'*64
    elif fault == 'owner_birth': w['owner']['birth'] = '999'
    elif fault == 'event': w['events']['barrier_released'] = False
    elif fault == 'no_child': w['owner_child_attached'] = False
    elif fault == 'diagnostic_missing': r.pop('cleanup_failure_observations')
    elif fault == 'diagnostic_stage': r['cleanup_failure_observations'][0]['stage'] = 'native_release'
    elif fault == 'diagnostic_overflow': r['cleanup_failure_observation_overflow'] = True
    elif fault == 'lease_unreleased': r['resource_lease']['released'] = False
    elif fault == 'lease_wrong_id': r['resource_lease']['lease_id'] = 'c'*32
    elif fault == 'budget_boolean': r['record']['cpu_slots'] = True
    elif fault == 'row_birth': r['record']['owner_birth'] = '999'
    elif fault == 'child_birth': r['record']['child']['birth'] = '999'
    elif fault == 'identity_missing': r['process_observation']['observed_identities'] = []
    elif fault == 'identity_cycle': r['process_observation']['observed_identities'][0]['parent_pid'] = r['record']['child']['pid']
    elif fault == 'identity_duplicate': r['process_observation']['observed_identities'] *= 2
    elif fault == 'tracking_error': r['process_observation']['tracking_error'] = 'unknown'
    elif fault == 'live_group': r['process_observation']['group_rss']['live_processes'] = 1
    elif fault == 'scratch_active': r['ordinary_scratch_profile']['live_exception_active'] = True
    else: w['storage']['release_authorized'] = True
    before = private_control['ledger'].read_bytes(),private_control['scheduler'].state_path.read_bytes()
    with pytest.raises((ValueError,KeyError)):
        module._productive_native_closed_profile_v1(terminal,raw,**caller)
    assert before == (private_control['ledger'].read_bytes(),private_control['scheduler'].state_path.read_bytes())


@pytest.mark.parametrize('fault', ['expired','owner_function_changed','child_function_changed','group_function_changed','source_drift',
    'own_row_drift','native_root','native_waiter','native_orphan_descendant','opener_function_changed','opener_function_changed_waiter'])
def test_productive_closed_inspection_unknown_keeps_full_claim(private_control,monkeypatch,fault):
    module,terminal,raw,caller,_ = _productive_failed_retention_binding_fixture(private_control)
    r = terminal['reservation'];lid = r['record']['native_lease_id'];rid = r['reservation_id']
    original_open = existing.open_existing_scheduler
    if fault in ('owner_function_changed','child_function_changed'):
        selected = caller['owner_pid'] if fault == 'owner_function_changed' else r['record']['child']['pid']
        actual = native_disk._process
        monkeypatch.setattr(native_disk,'_process',lambda pid: {'pid':pid,'birth':'reused'} if pid == selected else actual(pid))
    elif fault == 'group_function_changed': monkeypatch.setattr(native_disk,'_group_usage',lambda child:dict(available=True,live_processes=1,rss_bytes=1))
    elif fault == 'source_drift': private_control['source'].write_text('changed pinned source')
    elif fault == 'own_row_drift':
        state = _json(private_control['ledger']);state['reservations'][rid]['storage_bytes'] += 1;_write_json(private_control['ledger'],state)
    elif fault in ('native_root','native_waiter','native_orphan_descendant'):
        state = _json(private_control['scheduler'].state_path)
        if fault == 'native_root': state['leases'][lid] = {'lease_id':lid,'request_id':'validation:'+rid}
        elif fault == 'native_waiter': state['waiters']['c'*32] = {'request_id':'validation:'+rid}
        else: state['leases']['c'*32] = {'parent_lease_id':lid}
        _write_json(private_control['scheduler'].state_path,state)
    elif fault in ('opener_function_changed','opener_function_changed_waiter'):
        def opened(*args,**kwargs):
            facade = original_open(*args,**kwargs);original_inspect = facade.inspect_lease
            def inspect(*a,**kw):
                observed = original_inspect(*a,**kw)
                if fault == 'opener_function_changed': monkeypatch.setattr(native_disk,'_process',lambda pid:dict(pid=pid,birth='reused'))
                else:
                    state = _json(private_control['scheduler'].state_path)
                    state['waiters']['c'*32] = {'request_id':'validation:'+rid};_write_json(private_control['scheduler'].state_path,state)
                return observed
            monkeypatch.setattr(facade,'inspect_lease',inspect);return facade
        monkeypatch.setattr(existing,'open_existing_scheduler',opened)
    before = private_control['ledger'].read_bytes()
    try:
        result = module.inspect_owned_validation_productive_native_closed_v1(terminal,raw,**caller,
            original_wait_deadline_monotonic=time.monotonic()+(-1 if fault == 'expired' else 3))
        assert result == {'verdict':'requires_original_native_cleanup','source_custody_closed':False,
            'storage_release_authorized':False}
        assert private_control['ledger'].read_bytes() == before
        current = _json(private_control['ledger'])['reservations'][rid]
        assert current['status'] == 'active' and current['artifacts_durable_asserted'] is False
    finally:
        if fault in ('native_root','native_waiter','native_orphan_descendant','opener_function_changed_waiter'):
            state = _json(private_control['scheduler'].state_path);state['leases'].clear();state['waiters'].clear()
            _write_json(private_control['scheduler'].state_path,state)


@pytest.mark.parametrize('fault',['accepted_none','accepted_extra','accepted_foreign_path','kind_mismatch',
    'rejected_payload','absent_reason'])
def test_productive_closed_binding_refuses_incoherent_cleanup_diagnostic(private_control,fault):
    module,terminal,raw,caller,_ = _productive_failed_retention_binding_fixture(private_control)
    diagnostic = terminal['reservation']['cleanup_failure_observations'][0]
    if fault in ('accepted_none','accepted_extra','accepted_foreign_path'):
        diagnostic.update(reason_code='ledger_lock_unavailable',lock_observation_status='accepted')
        if fault != 'accepted_none':
            diagnostic['lock_observation'] = dict(schema='daemon-resource-ledger-lock-timeout/v1',
                stage='exclusive_acquire_before_yield',lock_path='/foreign/disk.json.lock')
            if fault == 'accepted_extra': diagnostic['lock_observation']['extra'] = 1
    elif fault == 'kind_mismatch': diagnostic['error_kind'] = 'os_error'
    elif fault == 'rejected_payload': diagnostic.update(lock_observation_status='rejected',lock_observation={})
    else: diagnostic['reason_code'] = 'ledger_lock_unavailable'
    terminal['source_custody_lifecycle']['storage']['cleanup_failure_observations'] = deepcopy([diagnostic])
    with pytest.raises(ValueError): module._productive_native_closed_profile_v1(terminal,raw,**caller)


def test_productive_closed_inspection_refuses_real_current_owner_pid(private_control):
    module,terminal,raw,caller,_ = _productive_failed_retention_binding_fixture(private_control)
    actual = native_disk._process(os.getpid());assert actual is not None
    old = caller['owner_pid'];caller['owner_pid'] = os.getpid();caller['owner_birth'] = actual['birth']
    row = terminal['reservation']['record'];row.update(owner_pid=os.getpid(),owner_birth=actual['birth'])
    terminal['reservation']['resource_lease']['owner_pid'] = os.getpid()
    terminal['source_custody_lifecycle']['owner'] = dict(pid=os.getpid(),birth=actual['birth'])
    row_observation = terminal['reservation']['process_observation']['observed_identities'][0]
    assert row_observation['parent_pid'] == old;row_observation['parent_pid'] = os.getpid()
    terminal['failure']['process_observation'] = deepcopy(terminal['reservation']['process_observation'])
    state = _json(private_control['ledger']);state['reservations'][row['reservation_id']] = deepcopy(row)
    _write_json(private_control['ledger'],state)
    before = private_control['ledger'].read_bytes()
    # Pure bindings succeed; the real current process observation must refuse.
    module._productive_native_closed_profile_v1(terminal,raw,**caller)
    assert module.inspect_owned_validation_productive_native_closed_v1(terminal,raw,**caller,
        original_wait_deadline_monotonic=time.monotonic()+3)['source_custody_closed'] is False
    assert private_control['ledger'].read_bytes() == before


def test_productive_closed_inspection_refuses_real_native_lease(private_control):
    module,terminal,raw,caller,_ = _productive_failed_retention_binding_fixture(private_control)
    # Real admission under a current test-owned birth deliberately conflicts
    # with the claimed original absence; the observer may neither release it
    # nor infer historical absence from the terminal's released=True flag.
    lease = private_control['scheduler'].acquire(native.ResourceLane.VALIDATION,
        cpu_slots=1,memory_mb=128,child_process_slots=1,timeout=0,
        request_id='validation:'+terminal['reservation']['reservation_id'])
    try:
        before = private_control['ledger'].read_bytes()
        assert module.inspect_owned_validation_productive_native_closed_v1(terminal,raw,**caller,
            original_wait_deadline_monotonic=time.monotonic()+3)['source_custody_closed'] is False
        assert private_control['ledger'].read_bytes() == before
        assert lease.lease_id in _json(private_control['scheduler'].state_path)['leases']
    finally: lease.release()


def test_actual_productive_cli_failed_retention_keeps_claim_but_closes_native(private_control):
    # Genuine original CLI/Popen, one real child/native grant and real disk-lock
    # timeout. No forced API flag, fake Popen, synthetic native absence, cap
    # change, storage release or retry. The existing SDK default60 is unchanged.
    c = private_control
    module,launcher = _lifecycle_launcher_module()
    attempt,manifest,request,_ = c['prepare'](timeout_seconds=120,memory_mb=128,child_process_slots=2,
        mutate=lambda value:value.update(schema='owned-validation-request/v5',
            process_scope=validation.TRACKED_SCOPE,
            ordinary_scratch_profile={'schema':'owned-validation-ordinary-scratch-live/v1'}))
    source = c['source']
    source.write_text("import sys,time\nfrom pathlib import Path\n"
        "attempt=Path(sys.argv[1])\n(attempt/'logs'/'ready').write_text('ready')\n"
        "until=time.monotonic()+20\n"
        "while not (attempt/'exports'/'exit').exists():\n"
        " if time.monotonic()>=until: raise SystemExit(9)\n time.sleep(.01)\n"
        "raise SystemExit(7)\n")
    request['argv'] = [sys.executable,'-B',str(source),str(attempt)]
    request['selected_checks'] = ['actual failed check with real held retention lock']
    package_root = Path(validation.__file__).resolve().parents[3]
    paths = [launcher,source,Path(validation.__file__),Path(native_disk.__file__),Path(native.__file__),
        Path(existing.__file__),Path(native.__file__).with_name('proof_resource_safety.py'),
        Path(native_disk.__file__).with_name('autoencoder_resource_recovery.py'),
        package_root/'ipfs_datasets_py/logic/backends/process.py']
    request['source_sha256'] = {str(path.resolve()):_sha(path) for path in paths};_write_json(manifest,request)
    pin = _sha(manifest);raw = manifest.read_bytes()
    out_path = source.with_name('productive-owner.stdout');err_path = source.with_name('productive-owner.stderr')
    environment = dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',
        IPFS_DATASETS_PY_MINIMAL_IMPORTS='1',IPFS_DATASETS_AUTO_INSTALL='0',IPFS_AUTO_INSTALL='false',
        OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
    process = None;descriptor = None;began = time.monotonic();original_cutoff = began+150
    with out_path.open('xb') as out,err_path.open('xb') as err:
        try:
            process = subprocess.Popen([sys.executable,'-B',str(launcher),'--request',str(manifest),
                '--expected-request-sha256',pin,'--resource-ledger',str(c['ledger'])],
                cwd=package_root,env=environment,stdout=out,stderr=err,start_new_session=True)
            identity = _wait_for(lambda:native_disk._process(process.pid),'real CLI birth missing')
            _wait_for(lambda:(attempt/'logs/ready').is_file(),'real productive child did not start',timeout=20)
            descriptor = os.open(c['ledger'].with_name(c['ledger'].name+'.lock'),os.O_RDWR|os.O_NOFOLLOW)
            fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
            (attempt/'exports/exit').write_text('exit7')
            assert process.wait(timeout=max(0,original_cutoff-time.monotonic())) == 1
        finally:
            if descriptor is not None: os.close(descriptor)
            if process is not None and process.poll() is None: _stop_group(process)
    terminal = json.loads(out_path.read_bytes())
    reservation = terminal['reservation'];row = reservation['record']
    assert terminal['failure']['returncode'] == 7
    assert reservation['status'] == row['status'] == 'active'
    assert row['storage_bytes'] == request['storage_bytes'] and row['artifacts_durable_asserted'] is False
    diagnostic, = reservation['cleanup_failure_observations']
    assert diagnostic['stage'] == 'failure_retention' and diagnostic['reason_code'] == 'ledger_lock_unavailable'
    assert diagnostic['lock_observation_status'] == 'accepted'
    assert diagnostic['lock_observation']['configured_lock_timeout_seconds'] == 60
    assert reservation['resource_lease']['released'] is True
    before = c['ledger'].read_bytes(),c['scheduler'].state_path.read_bytes()
    assert module.inspect_owned_validation_productive_native_closed_v1(terminal,raw,
        expected_request_sha256=pin,owner_pid=process.pid,owner_birth=identity['birth'],returncode=process.returncode,
        expected_resource_ledger=str(c['ledger']),original_wait_deadline_monotonic=original_cutoff) == {
            'verdict':'proven_original_productive_native_closed_storage_separate',
            'source_custody_closed':True,'storage_release_authorized':False}
    assert before == (c['ledger'].read_bytes(),c['scheduler'].state_path.read_bytes())
    assert _json(c['ledger'])['reservations'][row['reservation_id']] == row
    assert _json(c['scheduler'].state_path)['leases'] == {}
    assert _json(c['scheduler'].state_path)['metrics']['acquisitions_total'] == 1


# Lower-primitive controls preserve every inspected owner/helper function.
# Synthetic historical bindings stay explicitly distinct from real Popen proof.
def _productive_inspected_functions(module):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_resource_recovery as recovery
    return (module.inspect_owned_validation_productive_native_closed_v1,
        module._productive_native_closed_profile_v1,native_disk._process,native_disk._group_usage,
        recovery._sampled_open_scheduler,recovery._sampled_stopped,
        recovery._sampled_processes_stopped,recovery._sampled_scheduler_absence,
        recovery._sampled_scheduler_observation,existing.open_existing_scheduler,
        existing._PinnedGlobalResourceScheduler._locked_state,native.GlobalResourceScheduler.inspect_lease)


def _assert_productive_unknown_without_claim_write(module,terminal,raw,caller,control,cutoff):
    before = control['ledger'].read_bytes(),control['scheduler'].state_path.read_bytes()
    functions = _productive_inspected_functions(module)
    result = module.inspect_owned_validation_productive_native_closed_v1(terminal,raw,**caller,
        original_wait_deadline_monotonic=cutoff)
    assert result == {'verdict':'requires_original_native_cleanup','source_custody_closed':False,
        'storage_release_authorized':False}
    assert all(left is right for left,right in zip(functions,_productive_inspected_functions(module)))
    assert before == (control['ledger'].read_bytes(),control['scheduler'].state_path.read_bytes())
    row = _json(control['ledger'])['reservations'][terminal['reservation']['reservation_id']]
    assert row['status'] == 'active' and row['artifacts_durable_asserted'] is False
    assert type(row['storage_bytes']) is int and row['storage_bytes'] == json.loads(raw)['storage_bytes']


@pytest.mark.parametrize('subject', ['owner','child'])
@pytest.mark.parametrize('fault_errno', [13,5],ids=['PermissionError','EIO'])
def test_productive_inspection_refuses_bound_process_stat_IO_fault(private_control,monkeypatch,subject,fault_errno):
    import errno
    module,terminal,raw,caller,_ = _productive_failed_retention_binding_fixture(private_control)
    pid = caller['owner_pid'] if subject == 'owner' else terminal['reservation']['record']['child']['pid']
    target = Path('/proc')/str(pid)/'stat';actual_read = Path.read_text;reached = []
    def denied(path,*args,**kwargs):
        if path == target:
            reached.append(str(path))
            if fault_errno == errno.EACCES: raise PermissionError(fault_errno,'bounded fixture denial')
            raise OSError(fault_errno,'bounded fixture IO error')
        return actual_read(path,*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path,'read_text',denied)
        _assert_productive_unknown_without_claim_write(module,terminal,raw,caller,private_control,time.monotonic()+3)
    assert reached == [str(target)]


def test_productive_inspection_refuses_unavailable_real_proc_accounting(private_control,monkeypatch):
    module,terminal,raw,caller,_ = _productive_failed_retention_binding_fixture(private_control)
    actual_is_file = Path.is_file;reached = []
    def unavailable(path,*args,**kwargs):
        if path == Path('/proc/self/stat'):
            reached.append(str(path));return False
        return actual_is_file(path,*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path,'is_file',unavailable)
        _assert_productive_unknown_without_claim_write(module,terminal,raw,caller,private_control,time.monotonic()+3)
    assert reached == ['/proc/self/stat']


@pytest.mark.parametrize('fault_errno', [13,5],ids=['PermissionError','EIO'])
def test_productive_inspection_refuses_real_proc_inventory_IO_fault(private_control,monkeypatch,fault_errno):
    module,terminal,raw,caller,_ = _productive_failed_retention_binding_fixture(private_control)
    actual_iterdir = Path.iterdir;reached = []
    def denied(path,*args,**kwargs):
        if path == Path('/proc'):
            reached.append(str(path));raise OSError(fault_errno,'bounded proc inventory denial')
        return actual_iterdir(path,*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path,'iterdir',denied)
        _assert_productive_unknown_without_claim_write(module,terminal,raw,caller,private_control,time.monotonic()+3)
    assert reached == ['/proc']


@pytest.mark.parametrize('subject', ['ledger','native_state'])
@pytest.mark.parametrize('fault_errno', [13,5],ids=['PermissionError','EIO'])
def test_productive_inspection_refuses_exact_control_file_open_fault(private_control,monkeypatch,subject,fault_errno):
    module,terminal,raw,caller,_ = _productive_failed_retention_binding_fixture(private_control)
    target = private_control['ledger'] if subject == 'ledger' else private_control['scheduler'].state_path
    actual_open = os.open;reached = []
    def denied(path,flags,*args,**kwargs):
        if os.fspath(path) == str(target):
            reached.append(str(path));assert flags & os.O_ACCMODE == os.O_RDONLY
            raise OSError(fault_errno,'bounded private control read denial')
        return actual_open(path,flags,*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(os,'open',denied)
        _assert_productive_unknown_without_claim_write(module,terminal,raw,caller,private_control,time.monotonic()+3)
    assert reached == [str(target)]


@pytest.mark.parametrize('subject', ['ledger','native_state'])
def test_productive_inspection_refuses_duplicate_private_control_JSON(private_control,monkeypatch,subject):
    module,terminal,raw,caller,_ = _productive_failed_retention_binding_fixture(private_control)
    target = private_control['ledger'] if subject == 'ledger' else private_control['scheduler'].state_path
    original = target.read_bytes();decoded = json.loads(original)
    key = 'schema' if subject == 'ledger' else 'schema_version'
    duplicate = (b'{'+json.dumps(key).encode()+b':'+json.dumps(decoded[key]).encode()+b','+original.lstrip()[1:])
    # Both copies have the SAME value: last-value normalization is not allowed.
    assert json.loads(duplicate) == decoded
    functions = _productive_inspected_functions(module)
    try:
        target.write_bytes(duplicate)
        actual_open = os.open;reached = []
        def observed_open(path,flags,*args,**kwargs):
            if os.fspath(path) == str(target):
                reached.append(str(path));assert flags & os.O_ACCMODE == os.O_RDONLY
                assert not flags & os.O_CREAT
            return actual_open(path,flags,*args,**kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(os,'open',observed_open)
            _assert_productive_unknown_without_claim_write(module,terminal,raw,caller,private_control,time.monotonic()+3)
        assert reached == [str(target)]
        assert target.read_bytes() == duplicate
        assert all(left is right for left,right in zip(functions,_productive_inspected_functions(module)))
    finally:
        target.write_bytes(original)


def test_productive_inspection_does_not_recreate_missing_existing_native_lock(private_control,monkeypatch):
    module,terminal,raw,caller,_ = _productive_failed_retention_binding_fixture(private_control)
    state_path = private_control['scheduler'].state_path
    lock = state_path.with_name(state_path.name+'.lock');backup = lock.with_name(lock.name+'.test-preserved')
    parked_directory = lock.with_name(lock.name+'.test-unexpected-directory')
    before = lock.lstat();assert not backup.exists() and not os.path.lexists(parked_directory)
    actual_open,actual_lstat = os.open,Path.lstat;reached = []
    def observed_open(path,flags,*args,**kwargs):
        if os.fspath(path) == str(lock):
            reached.append('open');assert flags & os.O_ACCMODE == os.O_RDONLY
            assert not flags & os.O_CREAT
        return actual_open(path,flags,*args,**kwargs)
    def observed_lstat(path,*args,**kwargs):
        if path == lock: reached.append('lstat')
        return actual_lstat(path,*args,**kwargs)
    lock.rename(backup)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(os,'open',observed_open);patch.setattr(Path,'lstat',observed_lstat)
            _assert_productive_unknown_without_claim_write(module,terminal,raw,caller,private_control,time.monotonic()+3)
        assert reached
        assert not os.path.lexists(lock)
        assert backup.lstat().st_ino == before.st_ino
    finally:
        try:
            # Preserve the regression assertion, but it cannot prevent restoring
            # the original private fixture lock in the nested finally below.
            assert not os.path.lexists(lock)
        finally:
            try:
                if os.path.lexists(lock):
                    # This path was absent before the sole inspected API call.
                    # Remove only its fixture-owned unexpected leaf; preserve
                    # an unexpected directory by renaming, never recursively
                    # deleting contents or touching an unrelated namespace.
                    if stat.S_ISDIR(lock.lstat().st_mode): lock.rename(parked_directory)
                    else: lock.unlink()
            finally:
                backup.rename(lock)
    assert (lock.lstat().st_dev,lock.lstat().st_ino) == (before.st_dev,before.st_ino)


@pytest.mark.parametrize('boundary', ['ledger_read','native_lease_inspection'])
def test_productive_inspection_expiry_inside_original_cutoff_keeps_claim(private_control,monkeypatch,boundary):
    module,terminal,raw,caller,_ = _productive_failed_retention_binding_fixture(private_control)
    state_path = private_control['scheduler'].state_path
    target = private_control['ledger'] if boundary == 'ledger_read' else state_path.with_name(state_path.name+'.lock')
    actual_open,actual_clock = os.open,time.monotonic
    cutoff = actual_clock()+3;opens = [];expired = []
    def observe_open(path,flags,*args,**kwargs):
        descriptor = actual_open(path,flags,*args,**kwargs)
        if os.fspath(path) == str(target):
            opens.append(str(path))
            # Native constructor uses the first read-only existing lock. The
            # second belongs to the actual inspect_lease call, with original
            # bound method/code unchanged. Never give any operation a new end.
            if boundary == 'ledger_read' or len(opens) == 2:
                expired.append(True)
        return descriptor
    with monkeypatch.context() as patch:
        patch.setattr(os,'open',observe_open)
        patch.setattr(time,'monotonic',lambda:cutoff+1 if expired else actual_clock())
        _assert_productive_unknown_without_claim_write(module,terminal,raw,caller,private_control,cutoff)
    assert expired == [True]
    assert len(opens) == (1 if boundary == 'ledger_read' else 2)


def test_productive_inspection_refuses_real_live_bound_child_without_signalling(private_control,monkeypatch):
    module,terminal,raw,caller,_ = _productive_failed_retention_binding_fixture(private_control)
    process = subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(20)'],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    try:
        actual = _wait_for(lambda:native_disk._process(process.pid),'actual test child identity missing')
        row = terminal['reservation']['record'];row['child'] = dict(pid=process.pid,birth=actual['birth'])
        identity = terminal['reservation']['process_observation']['observed_identities'][0]
        # Historical parent relationship remains synthetic binding-fixture DATA.
        # Current child PID/birth/group/session are the real retained Popen's.
        identity.update(pid=process.pid,birth_ticks=int(actual['birth']),
            process_group_id=actual['group_pid'],session_id=process.pid)
        terminal['failure']['process_observation'] = deepcopy(terminal['reservation']['process_observation'])
        state = _json(private_control['ledger']);state['reservations'][row['reservation_id']] = deepcopy(row)
        _write_json(private_control['ledger'],state)
        module._productive_native_closed_profile_v1(terminal,raw,**caller)
        target = Path('/proc')/str(process.pid)/'stat';actual_read = Path.read_text;reached = []
        def observed(path,*args,**kwargs):
            if path == target: reached.append(str(path))
            return actual_read(path,*args,**kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(Path,'read_text',observed)
            _assert_productive_unknown_without_claim_write(module,terminal,raw,caller,private_control,time.monotonic()+3)
        assert reached == [str(target)]
        assert process.poll() is None
        assert native_disk._process(process.pid)['birth'] == actual['birth']
    finally:
        _stop_group(process)


_closed_pre_child_deadline_fixture = _closed_pre_child_fixture

# Fictional original producer/lease records isolate the strict post-grant
# ledger-lock profile. They confer no Popen, native or storage authority.
def _closed_pre_child_postgrant_lock_fixture(control):
    module, terminal, raw, caller, attempt = _closed_pre_child_deadline_fixture(control)
    failure, reservation = terminal['failure'], terminal['reservation']
    failure.update(error_type='DaemonResourceError', error='disk ledger lock unavailable', elapsed_seconds=1.0)
    observation = dict(scope='sampled_birth_bound_descendants',
        group_rss=dict(available=True, live_processes=0, rss_bytes=0),
        live_processes=0, rss_bytes=0, observed_identities=[],
        out_of_group_live_identities=[], tracking_error='')
    failure['process_observation'] = deepcopy(observation)
    reservation['process_observation'] = deepcopy(observation)
    reservation['record']['retention_reason'] = 'context_failed'
    state = _json(control['ledger'])
    state['reservations'][reservation['reservation_id']] = deepcopy(reservation['record'])
    _write_json(control['ledger'], state)
    return module, terminal, raw, caller, attempt


def test_pre_child_postgrant_lock_profile_binds_complete_original_shape(private_control):
    module, terminal, raw, caller, _ = _closed_pre_child_postgrant_lock_fixture(private_control)
    before = private_control['ledger'].read_bytes(), private_control['scheduler'].state_path.read_bytes()
    value, witness, reservation, row, lease = module._no_child_native_closed_profile_v1(terminal, raw, **caller)
    assert value['timeout_seconds'] == 20
    assert witness == terminal['source_custody_lifecycle']
    assert reservation == terminal['reservation'] and row == reservation['record']
    assert len(row) == 17 and row['retention_reason'] == 'context_failed' and row['child'] is None
    assert lease['released'] is True and lease['cancelled'] is True
    assert (private_control['ledger'].read_bytes(), private_control['scheduler'].state_path.read_bytes()) == before


def test_pre_child_postgrant_lock_inspector_is_read_only_and_storage_separate(private_control, monkeypatch):
    module, terminal, raw, caller, attempt = _closed_pre_child_postgrant_lock_fixture(private_control)
    before = private_control['ledger'].read_bytes(), private_control['scheduler'].state_path.read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('inspection cannot allocate, persist or inventory')
    monkeypatch.setattr(native.GlobalResourceScheduler, 'acquire', forbidden)
    monkeypatch.setattr(existing._PinnedGlobalResourceScheduler, '_persist_locked_state', forbidden)
    monkeypatch.setattr(native_disk.DaemonResourceReservation, '_write', forbidden)
    monkeypatch.setattr(native_disk.DaemonResourceReservation, '_account', forbidden)
    assert module.classify_owned_validation_source_custody(terminal, raw, **caller) == dict(
        verdict='requires_original_native_cleanup', source_custody_closed=False, storage_release_authorized=False)
    assert module.inspect_owned_validation_no_child_native_closed_v1(terminal, raw, **caller) == dict(
        verdict='proven_original_no_child_native_closed', source_custody_closed=True, storage_release_authorized=False)
    assert (private_control['ledger'].read_bytes(), private_control['scheduler'].state_path.read_bytes()) == before
    assert next(attempt.iterdir(), None) is None


@pytest.mark.parametrize('elapsed', [0, -1, 20, 21, True, float('nan'), float('inf'), -float('inf')],
    ids=['zero', 'negative', 'equal-timeout', 'over-timeout', 'bool', 'nan', 'inf', 'negative-inf'])
def test_pre_child_postgrant_lock_profile_rejects_elapsed_boundaries(private_control, elapsed):
    module, terminal, raw, caller, _ = _closed_pre_child_postgrant_lock_fixture(private_control)
    terminal['failure']['elapsed_seconds'] = elapsed
    with pytest.raises(ValueError):
        module._no_child_native_closed_profile_v1(terminal, raw, **caller)


@pytest.mark.parametrize('side', ['failure', 'reservation'])
@pytest.mark.parametrize('fault', ['none', 'top_live_bool', 'top_rss_float', 'group_available_int',
    'group_live_bool', 'group_rss_float', 'observed_tuple', 'observed_nonempty',
    'out_of_group_nonempty', 'tracking_none', 'scope_wrong', 'extra_field', 'group_extra'])
def test_pre_child_postgrant_lock_profile_rejects_nonexact_zero_process_frames(private_control, side, fault):
    module, terminal, raw, caller, _ = _closed_pre_child_postgrant_lock_fixture(private_control)
    observed = terminal[side]['process_observation']
    if fault == 'none': terminal[side]['process_observation'] = None
    elif fault == 'top_live_bool': observed['live_processes'] = False
    elif fault == 'top_rss_float': observed['rss_bytes'] = 0.0
    elif fault == 'group_available_int': observed['group_rss']['available'] = 1
    elif fault == 'group_live_bool': observed['group_rss']['live_processes'] = False
    elif fault == 'group_rss_float': observed['group_rss']['rss_bytes'] = 0.0
    elif fault == 'observed_tuple': observed['observed_identities'] = ()
    elif fault == 'observed_nonempty': observed['observed_identities'] = [{'pid': 1, 'birth': '1'}]
    elif fault == 'out_of_group_nonempty': observed['out_of_group_live_identities'] = [{'pid': 1, 'birth': '1'}]
    elif fault == 'tracking_none': observed['tracking_error'] = None
    elif fault == 'scope_wrong': observed['scope'] = 'isolated_process_group_only'
    elif fault == 'extra_field': observed['extra'] = 0
    else: observed['group_rss']['extra'] = 0
    with pytest.raises(ValueError):
        module._no_child_native_closed_profile_v1(terminal, raw, **caller)


@pytest.mark.parametrize('path,replacement', [
    ('failure.error_type', 'ResourceAdmissionDeadlineError'),
    ('failure.error', 'original absolute resource operation deadline expired'),
    ('reservation.record.retention_reason', 'scheduler_admission_failed'),
    ('reservation.resource_lease.released', False), ('reservation.resource_lease.cancelled', False),
    ('reservation.resource_lease.owner_pid', 100), ('reservation.resource_lease.cpu_slots', True),
    ('reservation.record.storage_bytes', 1), ('reservation.record.child', {}),
    ('reservation.record.prior_children', [{}]), ('reservation.record.artifacts_durable_asserted', True),
    ('source_custody_lifecycle.events.child_created', True),
    ('source_custody_lifecycle.events.owner_open_returned', True),
    ('source_custody_lifecycle.source_guards.source_pins_unchanged', False),
    ('source_custody_lifecycle.producer.sha256', '0'*64),
    ('source_custody_lifecycle.owner.birth', '654321'),
    ('source_custody_lifecycle.native_grant.exact_native_timeout', True),
    ('failure.process_cleanup_error', 'uncertain'), ('reservation.cleanup_error', 'uncertain'),
])
def test_pre_child_postgrant_lock_profile_rejects_crossed_or_incomplete_bindings(private_control, path, replacement):
    module, terminal, raw, caller, _ = _closed_pre_child_postgrant_lock_fixture(private_control)
    target = terminal
    fields = path.split('.')
    for field in fields[:-1]: target = target[field]
    target[fields[-1]] = replacement
    if path == 'source_custody_lifecycle.producer.sha256':
        _assert_closed_pre_child_unknown(module, terminal, raw, caller)
    else:
        with pytest.raises(ValueError):
            module._no_child_native_closed_profile_v1(terminal, raw, **caller)


@pytest.mark.parametrize('fault', ['source_drift', 'row_drift', 'owner_present', 'native_root',
    'native_orphan_descendant', 'native_waiter', 'late_owner', 'late_waiter', 'expired_deadline'])
def test_pre_child_postgrant_lock_inspector_rechecks_current_and_late_custody(private_control, monkeypatch, fault):
    # Reuse the owning inspector's existing adversarial controls unchanged,
    # substituting only the new complete historical profile fixture.
    with monkeypatch.context() as patch:
        patch.setitem(globals(), '_closed_pre_child_fixture', _closed_pre_child_postgrant_lock_fixture)
        test_pre_child_closed_native_inspection_rechecks_current_custody(private_control, patch, fault)


# Prospective direct-helper integration only. This appended case is not a
# sealed-release validate/factory test and grants no runtime enrollment.
def test_actual_canonical_A_helper360_failed_retention_keeps_storage(private_control):
    """Original A helper/CLI/native waits; one private benign retention lock.

    The same-process thread owns only its private flock and marker. Every
    Popen, timeout, stop/reap and Source/native proof remains in the original
    A engine and R CLI. No process owner, signal or cleanup substitute is added.
    """
    import threading
    from ipfs_accelerate_py.agent_supervisor.rescue import repair_candidate_owners as owners
    from ipfs_accelerate_py.agent_supervisor.todo_daemon import engine

    c = private_control
    datasets_root = Path('/home/barberb/lift_coding/external/ipfs_datasets')
    candidate_root = Path('/home/barberb/lift_coding/external/ipfs_accelerate')
    owner_path = candidate_root / 'ipfs_accelerate_py/agent_supervisor/rescue/repair_candidate_owners.py'
    engine_path = candidate_root / 'ipfs_accelerate_py/agent_supervisor/todo_daemon/engine.py'
    cli_path = datasets_root / 'scripts/ops/legal_ir/run_owned_validation.py'
    directory = datasets_root / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer'
    expected = {
        owner_path: 'cde69e28388ab2f7e353b84dd832b002eab35c0ccfd0bd3d2aac123de1a13b6c',
        engine_path: 'e6e3e5fc0906cd312e305f46d5c7b12f48c726855561f28991de62ebee759b30',
        cli_path: '9abef02b27b5ea591cab23bdd6798fd0eb066533af8a2356eb5db92b2139c6f7',
        directory / 'validation_run_resources.py': '11e5110aa8dcf39c5b11c0bd06a6d02933052e917fa46bf6d53a5467107d6def',
        directory / 'autoencoder_daemon_resources.py': 'ff56d3c02148fbcd2aeffcd603232edde831be12218fa1e2765694aa71d03b1f',
        directory / 'autoencoder_source_lease.py': '42e9f07d0d458177079269d9f495f0b70512180c1adc2f7fe0bfdb05518a12f9',
    }
    # Normal imports must already have the selected genuine origins. This test
    # adds no sys.path mutation, aliases, loader or fabricated co_filename.
    assert Path(owners.__file__) == owner_path and owners.__spec__.origin == str(owner_path)
    assert Path(engine.__file__) == engine_path and engine.__spec__.origin == str(engine_path)
    assert owners.original_runner_wait.__code__.co_filename == str(owner_path)
    assert engine.run_command.__code__.co_filename == str(engine_path)
    assert Path(validation.__file__) == directory / 'validation_run_resources.py'
    assert Path(native_disk.__file__) == directory / 'autoencoder_daemon_resources.py'
    for path, sha in expected.items():
        assert _sha(path) == sha

    attempt, unused_request_path, request, _ = c['prepare'](
        storage_bytes=16777216, timeout_seconds=300, memory_mb=1536,
        cpu_slots=1, child_process_slots=4,
        mutate=lambda value: value.update(schema='owned-validation-request/v5',
            process_scope=validation.TRACKED_SCOPE,
            ordinary_scratch_profile={'schema': 'owned-validation-ordinary-scratch-live/v1'}))
    source = c['source']
    # Same approved cooperative child7/ready/exit semantics. There are no
    # descendants, namespace changes, startup signals or escape scenarios.
    source.write_text('import sys,time\nfrom pathlib import Path\n'
        'attempt=Path(sys.argv[1])\n(attempt/"logs"/"ready").write_text("ready")\n'
        'until=time.monotonic()+90\n'
        'while not (attempt/"exports"/"exit").exists():\n'
        ' if time.monotonic()>=until: raise SystemExit(9)\n time.sleep(.01)\n'
        'raise SystemExit(7)\n')
    invocation = source.with_name('canonical-A-helper360-invocation')
    invocation.mkdir(mode=0o700)
    check = 'direct canonical A helper360 benign child7 private-retention observation'
    request.update(argv=[sys.executable, '-B', str(source), str(attempt)],
        cwd=str(candidate_root), selected_checks=[check])

    # A is an existing genuine Git checkout, used READ-only. Source42 itself
    # resolves and acquires its actual canonical root; no .git is fabricated.
    # This is an honest read-only finite source freeze, with zero changed
    # candidate paths. It is deliberately NOT a factory-generated repair freeze.
    frozen = {
        'schema': 'canonical-A-helper360-read-only-source-context/v1',
        'candidate_root': str(candidate_root), 'changed_paths': [],
        'manifest': {str(path.relative_to(candidate_root)): owners.descriptor(path)
            for path in (owner_path, engine_path)},
        'validation_passed': False, 'runtime_adopted': False,
        'factory_generated_candidate': False,
    }
    frozen_pin = owners.new_json(invocation / 'helper-read-only-source-context.json', frozen)
    plan = {
        'schema': 'canonical-A-helper360-direct-integration-plan/v1',
        'candidate_root': str(candidate_root), 'attempt_directory': str(attempt),
        'selected_checks': [check], 'frozen_source_context': frozen_pin,
        'factory_generated_plan': False, 'semantic_test_acceptance': False,
    }
    plan_pin = owners.new_json(invocation / 'helper-plan.json', plan)
    core_paths = [owner_path, engine_path, cli_path, source, Path(__file__),
        Path(validation.__file__), Path(native_disk.__file__), Path(native.__file__),
        Path(existing.__file__), directory / 'proof_resource_safety.py',
        directory / 'autoencoder_resource_recovery.py', directory / 'runtime_telemetry.py',
        directory / 'autoencoder_source_lease.py',
        datasets_root / 'ipfs_datasets_py/logic/backends/process.py']
    source_descriptors = [owners.descriptor(path) for path in core_paths]
    request['source_sha256'] = {pin['path']: pin['sha256']
        for pin in [*source_descriptors, frozen_pin, plan_pin]}
    assert len(request['source_sha256']) <= 256
    request_pin = owners.new_json(invocation / 'execution-request.json', request)
    validation_policy = {key: request[key] for key in (
        'ordinary_scratch_profile', 'cpu_slots', 'memory_mb', 'storage_bytes',
        'timeout_seconds', 'child_process_slots', 'scheduler_state_path',
        'expected_scheduler_policy_sha256', 'roots')}
    validation_policy['resource_ledger'] = str(c['ledger'])
    policy = {'datasets_root': str(datasets_root), 'python': sys.executable,
        'source_descriptors': source_descriptors, 'validation': validation_policy}
    owners.new_json(invocation / 'direct-helper-policy.json', policy)
    context = {'plan': plan, 'request_pin': request_pin,
        'invocation': invocation, 'frozen': frozen}
    argv = [sys.executable, '-I', '-B', str(cli_path), '--request', request_pin['path'],
        '--expected-request-sha256', request_pin['sha256'], '--resource-ledger', str(c['ledger'])]

    finished = threading.Event()
    coordination = {'errors': [], 'lock_acquired': False, 'lock_closed': False,
        'exit7_requested_after_lock': False, 'main_returned': False,
        'native_Source_storage_or_completion_authority': False}
    # Conservative fixture-only cutoff starts BEFORE the original API. It
    # cannot extend its later D/W/C. The owner reports those actual clocks.
    fixture_started = time.monotonic()
    coordination_deadline = fixture_started + 270
    coordination['deadline_monotonic'] = coordination_deadline

    def coordinate_private_lock():
        descriptor = None
        try:
            ready = attempt / 'logs/ready'
            while True:
                try:
                    with ready.open('rb') as marker_file:
                        marker = marker_file.read(6)
                except FileNotFoundError:
                    marker = b''
                # Creation can precede the child's write. Only known prefixes
                # of the pinned literal are in-progress, under the same cutoff.
                assert b'ready'.startswith(marker), 'unexpected benign readiness marker'
                if marker == b'ready':
                    break
                assert not finished.is_set(), 'original owner returned before benign child readiness'
                left = coordination_deadline - time.monotonic()
                assert left > 0, 'private coordination deadline expired before readiness'
                finished.wait(min(.01, left))
            rows = _json(c['ledger'])['reservations']
            ours = [row for key, row in rows.items() if key != 'foreign-retained']
            assert len(ours) == 1
            row = ours[0]
            assert row['status'] == 'active' and row['validation_request_sha256'] == request_pin['sha256']
            assert row['storage_bytes'] == 16777216 and row['child'] is not None
            child = native_disk._process(row['child']['pid'])
            assert child is not None and child['birth'] == row['child']['birth']
            coordination['row_before'] = deepcopy(row)
            lock_path = c['ledger'].with_name(c['ledger'].name + '.lock')
            # Open ONLY the existing private SDK lock. Never create, replace,
            # delete, force-unlock or operate on the shared host ledger lock.
            descriptor = os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
            info = os.fstat(descriptor)
            assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.geteuid()
            assert (lock_path.lstat().st_dev, lock_path.lstat().st_ino) == (info.st_dev, info.st_ino)
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    left = coordination_deadline - time.monotonic()
                    assert left > 0 and not finished.is_set(), 'private lock was unavailable'
                    finished.wait(min(.01, left))
            coordination['lock_acquired'] = True
            coordination['lock_identity'] = {'device': info.st_dev, 'inode': info.st_ino}
            (attempt / 'exports/exit').write_text('exit7')
            coordination['exit7_requested_after_lock'] = True
            while not finished.is_set():
                left = coordination_deadline - time.monotonic()
                assert left > 0, 'private fixture cutoff reached; no extension or successful closeout inferred'
                finished.wait(min(.02, left))
        except BaseException as error:
            coordination['errors'].append({'type': type(error).__name__, 'message': str(error)[:1000]})
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                    coordination['lock_closed'] = True
                except BaseException as error:
                    coordination['errors'].append({'type': type(error).__name__, 'stage': 'own_private_lock_close'})
            # This records only this thread's own resource, never native/Source
            # closure. On original UNKNOWN custody, the original owner holds.
            owners.new_json(invocation / 'private-coordination.json', coordination)

    controller = threading.Thread(name='canonical360-private-lock-coordination',
        target=coordinate_private_lock, daemon=False)
    controller.start()
    try:
        completed, witness = owners.original_runner_wait(policy, argv, candidate_root, 360,
            validation_context=context)
        coordination['main_returned'] = True
        api_returned_at = time.monotonic()
    finally:
        finished.set()
        # Owned thread only: no Popen poll, process signal or recovery callback.
        controller.join(timeout=1)
        assert not controller.is_alive(), 'private coordination did not close; qualification refused'

    # A thread journal error must fail this case, not become only a warning.
    assert _json(invocation / 'private-coordination.json') == coordination
    assert coordination['errors'] == []
    assert coordination['lock_acquired'] and coordination['lock_closed']
    assert coordination['exit7_requested_after_lock'] and coordination['main_returned']
    assert completed.returncode == 1 and witness['actual_process_returncode'] == 1
    assert witness['actual_Popen_returned'] is True and witness['actual_process_waited'] is True
    parent = witness['parent_source_custody']
    assert parent['schema'] == 'agent-supervisor/v5-validation-parent-source-custody@2'
    assert parent['closure_kind'] == 'productive_native_closed_storage_separate'
    assert parent['source_closed'] is True and parent['native_closed'] is True
    assert parent['storage_status'] == 'active'
    assert parent['storage_release_authorized'] is False and parent['retry_authorized'] is False
    D = parent['authority_deadline_monotonic']
    assert fixture_started <= D - 360 <= api_returned_at < D
    assert parent['work_deadline_monotonic'] == D - 30
    assert parent['cleanup_deadline_monotonic'] == D - 20
    assert coordination_deadline <= D - 90
    assert parent['source_exit_finished_at_monotonic'] < D
    assert [r['canonical_root'] for r in parent['source_receipts']] == [str(datasets_root), str(candidate_root)]
    assert [r['mode'] for r in parent['source_receipts']] == ['read', 'read']
    execution = _json(invocation / 'runner-execution-observation.json')
    observation = execution['execution_observation']
    assert execution['exact_command_result'] is True and execution['exact_execution_observation'] is True
    assert observation['completion_kind'] == 'completed' and observation['output_capture'] == 'complete'
    assert observation['process_returncode'] == execution['public_returncode'] == 1
    assert observation['leader_waited'] is True and execution['process_count'] == 1
    assert execution['authority_deadline_monotonic'] == D
    assert execution['work_deadline_monotonic'] == observation['work_deadline_monotonic'] == D - 30
    assert execution['cleanup_deadline_monotonic'] == observation['cleanup_deadline_monotonic'] == D - 20
    terminal = json.loads(completed.stdout)
    reservation = terminal['reservation']; row = reservation['record']
    assert terminal['failure']['returncode'] == 7 and terminal['failure']['completed'] is False
    assert reservation['status'] == row['status'] == 'active'
    assert row['storage_bytes'] == 16777216 and row['artifacts_durable_asserted'] is False
    diagnostic, = reservation['cleanup_failure_observations']
    assert diagnostic['stage'] == 'failure_retention' and diagnostic['reason_code'] == 'ledger_lock_unavailable'
    assert diagnostic['lock_observation']['configured_lock_timeout_seconds'] == 60
    assert reservation['resource_lease']['released'] is True
    assert row['owner_pid'] == witness['runner_identity']['pid']
    assert row['owner_birth'] == witness['runner_identity']['birth']
    assert _json(c['ledger'])['reservations'][row['reservation_id']] == row
    assert _json(c['ledger'])['reservations']['foreign-retained'] == c['foreign']
    assert _json(c['scheduler'].state_path)['leases'] == {}
    assert _json(c['scheduler'].state_path)['metrics']['acquisitions_total'] == 1
    closeout = _json(invocation / 'parent-source-closeout.json')
    assert closeout['schema'] == 'agent-supervisor/v5-validation-parent-source-closeout@2'
    assert closeout['producer'] == owners.descriptor(owner_path)
    assert closeout['request'] == request_pin and closeout['parent_source_custody'] == parent
    assert not (invocation / 'source-custody-unknown.json').exists()
    # Failure path only: no passed receipt, release/reconciliation, retry or
    # direct adoption. Existing private_control teardown owns its native check.
    assert not (invocation / 'receipt.json').exists()


def _prepare_pregrant_ledger_bound(control, version='v5'):
    module, launcher, attempt, manifest, request, kwargs = _prepare_no_child_lifecycle(control)
    if version == 'v4':
        request['schema'] = validation.LIVE_REQUEST_SCHEMA
        request['live_inventory_profile'] = {
            'schema': validation.LIVE_INVENTORY_SCHEMA, 'max_complete_resamples': 1}
    elif version == 'v5':
        request['schema'] = 'owned-validation-request/v5'
        request['ordinary_scratch_profile'] = {'schema': 'owned-validation-ordinary-scratch-live/v1'}
    _write_json(manifest, request)
    kwargs['frozen_validation_manifest_sha256'] = _sha(manifest)
    ledger = _json(control['ledger'])
    padding = dict(deepcopy(control['foreign']), reservation_id='released-padding',
                   status='released', storage_bytes=1, ledger_padding='')
    ledger['reservations']['released-padding'] = padding
    raw = (json.dumps(ledger, sort_keys=True, separators=(',', ':')) + '\n').encode()
    padding['ledger_padding'] = (
        'x' * (native_disk.MAX_LEDGER_BYTES - len(raw) - 1))
    _write_json(control['ledger'], ledger)
    assert control['ledger'].stat().st_size == native_disk.MAX_LEDGER_BYTES - 1
    return module, launcher, attempt, manifest, request, kwargs


def _actual_pregrant_ledger_bound_cli(control, version='v5'):
    module, launcher, attempt, manifest, request, _ = _prepare_pregrant_ledger_bound(control, version)
    before = control['ledger'].read_bytes(), control['scheduler'].state_path.read_bytes()
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
        IPFS_DATASETS_PY_MINIMAL_IMPORTS='1', IPFS_DATASETS_AUTO_INSTALL='0',
        IPFS_AUTO_INSTALL='false', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    child = None
    try:
        child = subprocess.Popen([sys.executable, '-B', str(launcher), '--request', str(manifest),
            '--expected-request-sha256', _sha(manifest), '--resource-ledger', str(control['ledger'])],
            cwd=launcher.parents[3], env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True)
        identity = native_disk._process(child.pid)
        assert identity is not None
        stdout, stderr = child.communicate(timeout=30)
        for suffix, body in (('.ledger-bound-owner.stdout', stdout), ('.ledger-bound-owner.stderr', stderr)):
            with manifest.with_suffix(suffix).open('xb') as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
        assert child.returncode != 0, (stdout, stderr)
        terminal = json.loads(stdout)
        assert terminal['failure']['error'] == 'disk ledger byte bound exceeded'
        assert before == (control['ledger'].read_bytes(), control['scheduler'].state_path.read_bytes())
        assert not tuple(attempt.iterdir())
        caller = dict(expected_request_sha256=_sha(manifest), owner_pid=child.pid,
            owner_birth=identity['birth'], returncode=child.returncode,
            expected_resource_ledger=str(control['ledger']))
        return module, terminal, manifest.read_bytes(), caller
    finally:
        if child is not None:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
            _stop_group(child)


@pytest.mark.parametrize('version', ['v1', 'v4', 'v5'])
def test_actual_cli_pregrant_ledger_bound_refusal_closes_source_custody(private_control, version):
    module, terminal, raw, caller = _actual_pregrant_ledger_bound_cli(private_control, version)
    witness = terminal['source_custody_lifecycle']
    assert witness['schema'] == module.PRE_GRANT_LEDGER_BOUND_REFUSAL_SCHEMA
    observation = witness['ledger_write_bound_observation']
    assert observation['maximum_bytes'] == native_disk.MAX_LEDGER_BYTES
    assert observation['serialized_bytes'] > native_disk.MAX_LEDGER_BYTES
    assert observation['write_started'] is False
    assert terminal['reservation']['record'] is terminal['reservation']['resource_lease'] is None
    assert terminal['failure']['executed_checks'] == []
    assert module.classify_owned_validation_source_custody(terminal, raw, **caller) == {
        'verdict': 'proven_original_no_child_no_native_grant', 'source_custody_closed': True,
        'storage_release_authorized': False}


def test_pregrant_ledger_bound_classifier_refuses_ambiguous_or_changed_evidence(private_control):
    module, terminal, raw, caller = _actual_pregrant_ledger_bound_cli(private_control)
    for fault in ('schema', 'request', 'producer', 'owner', 'stage', 'record', 'lease', 'entered',
            'child', 'native', 'write_started', 'integer_bool', 'size', 'maximum', 'excess',
            'source', 'release', 'checks', 'returncode'):
        altered = deepcopy(terminal)
        witness = altered['source_custody_lifecycle']
        observation = witness['ledger_write_bound_observation']
        if fault == 'schema':
            witness['schema'] += '-foreign'
        elif fault == 'request':
            witness['request_sha256'] = '0' * 64
        elif fault == 'producer':
            witness['producer']['sha256'] = '0' * 64
        elif fault == 'owner':
            witness['owner']['birth'] += '1'
        elif fault == 'stage':
            witness['stage'] += '-postwrite'
        elif fault == 'record':
            altered['reservation']['record'] = {'status': 'reserved'}
        elif fault == 'lease':
            altered['reservation']['resource_lease'] = {'released': True}
        elif fault == 'entered':
            witness['owner_state']['entered'] = True
        elif fault == 'child':
            witness['events']['child_created'] = True
        elif fault == 'native':
            witness['native_grant']['status'] = 'acquired'
        elif fault == 'write_started':
            observation['write_started'] = True
        elif fault == 'integer_bool':
            observation['excess_bytes'] = True
        elif fault == 'size':
            observation['serialized_bytes'] = observation['maximum_bytes']
        elif fault == 'maximum':
            observation['maximum_bytes'] += 1
        elif fault == 'excess':
            observation['excess_bytes'] += 1
        elif fault == 'source':
            witness['source_guards']['request_unchanged'] = False
        elif fault == 'release':
            witness['storage']['release_authorized'] = True
        elif fault == 'checks':
            altered['failure']['executed_checks'] = ['unexecuted']
        else:
            altered['failure']['returncode'] = 0
        assert module.classify_owned_validation_source_custody(altered, raw,
            **caller)['source_custody_closed'] is False, fault


def test_pregrant_ledger_bound_builder_requires_original_error_and_first_write(private_control):
    module, _, _, manifest, request, kwargs = _prepare_pregrant_ledger_bound(private_control, 'v1')
    owner = _owner(private_control, kwargs)
    before = private_control['ledger'].read_bytes(), private_control['scheduler'].state_path.read_bytes()
    events = {key: key == 'owner_open_attempted' for key in module._PRE_GRANT_EVENTS}
    with pytest.raises(native_disk.DaemonResourceError) as caught:
        owner.open()
    original = caught.value
    observation = original.ledger_write_bound_observation
    detached = original.ledger_write_bound_observation
    detached['write_started'] = True
    assert original.ledger_write_bound_observation == observation
    outcome = dict(schema='owned-validation-result/v1', request_sha256=_sha(manifest),
        completed=False, executed_checks=[], returncode=None, admitted=False, Lean_admitted=False,
        authority_granted=False, model_weights_downloaded=False, error_type='DaemonResourceError',
        error=str(original), watchdog_errors=[], received_signals=[])
    assert module._pre_grant_ledger_bound_refusal_terminal(owner, request, manifest.read_bytes(),
        manifest, _sha(manifest), private_control['ledger'], events, original, outcome) is not None
    copied = native_disk.DaemonResourceError(str(original))
    copied._ledger_write_bound_observation = observation
    for error in (copied, RuntimeError(str(original))):
        assert module._pre_grant_ledger_bound_refusal_terminal(owner, request, manifest.read_bytes(),
            manifest, _sha(manifest), private_control['ledger'], events, error, outcome) is None
    assert before == (private_control['ledger'].read_bytes(), private_control['scheduler'].state_path.read_bytes())


def test_pregrant_ledger_bound_builder_preserves_postgrant_cleanup(private_control):
    module, _, _, manifest, request, kwargs = _prepare_no_child_lifecycle(private_control)
    owner = _owner(private_control, kwargs)
    try:
        owner.open()
        before = private_control['ledger'].read_bytes()
        with owner._locked():
            ledger = owner._read()
            ledger['reservations']['foreign-retained']['ledger_padding'] = 'x' * native_disk.MAX_LEDGER_BYTES
            with pytest.raises(native_disk.DaemonResourceError) as caught:
                owner._write(ledger)
        assert private_control['ledger'].read_bytes() == before
        events = {key: key == 'owner_open_attempted' for key in module._PRE_GRANT_EVENTS}
        assert module._pre_grant_ledger_bound_refusal_terminal(owner, request, manifest.read_bytes(),
            manifest, _sha(manifest), private_control['ledger'], events, caught.value, {}) is None
    finally:
        owner.__exit__(RuntimeError, RuntimeError('postgrant byte-bound failure'), None)
    assert _json(private_control['ledger'])['reservations'][owner.reservation_id]['status'] == 'retained'



# Cooperative local observation cancellation is distinct from validation
# success, global Source custody, durable sealing and resource release. Every
# scheduler, ledger, thread and child below belongs to the existing private
# fixture and is exercised only when the original test owner selects the case.
def _local_observation_thread_worker(owned, token, outcomes, done):
    try:
        outcomes['sample'] = ('ok', owned.check_limits(_observer_stop=token))
    except BaseException as error:
        outcomes['sample'] = ('error', error)
    finally:
        done.set()


def test_local_observation_stop_running_sample_preserves_local_only_contract(private_control):
    import threading
    c = private_control
    _, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        finished = threading.Event()
        token = owned._new_local_observation_stop(finished)
        before, started = c['ledger'].read_bytes(), owned._started
        result = owned.check_limits(_observer_stop=token)
        assert result['full_ledger_check'] is False
        assert result['attempt_bytes'] == result['inventory']['apparent_bytes']
        assert not finished.is_set() and owned._live_inventory_active is True
        assert owned._started == started and c['ledger'].read_bytes() == before
        assert owned._sealed is None


@pytest.mark.parametrize('kind', ['none', 'dictionary', 'integer', 'lookalike'])
def test_local_observation_stop_rejects_unowned_event_objects(private_control, kind):
    from types import SimpleNamespace
    c = private_control
    _, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        offered = {'none': None, 'dictionary': {}, 'integer': 1,
            'lookalike': SimpleNamespace(is_set=lambda: True, set=lambda: None)}[kind]
        before = c['ledger'].read_bytes()
        with pytest.raises(validation.ValidationResourceError):
            owned._new_local_observation_stop(offered)
        assert c['ledger'].read_bytes() == before and owned._live_inventory_active is True


def test_local_observation_stop_finished_event_requires_original_zero_process_proof(private_control):
    import threading
    c = private_control
    _, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        finished = threading.Event()
        token = owned._new_local_observation_stop(finished)
        finished.set()
        with pytest.raises(validation.ValidationResourceError, match='zero.process') as caught:
            owned.check_limits(_observer_stop=token)
        assert type(caught.value) is not validation.LocalValidationObservationStopped
        assert owned._live_inventory_active is True and owned._sealed is None


def test_local_observation_stop_uses_actual_zero_barrier_without_releasing_claim(private_control):
    import threading
    c = private_control
    _, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        finished = threading.Event()
        token = owned._new_local_observation_stop(finished)
        before, started = c['ledger'].read_bytes(), owned._started
        assert not finished.is_set()
        observation = owned._stop_local_observation(token)
        assert finished.is_set()
        assert observation['live_processes'] == 0
        with pytest.raises(validation.LocalValidationObservationStopped) as caught:
            owned.check_limits(_observer_stop=token)
        assert type(caught.value) is validation.LocalValidationObservationStopped
        assert caught.value._observer_stop is token
        assert owned._accept_local_observation_stop(caught.value, token) is True
        assert owned._live_inventory_active is False and owned._sealed is None
        assert owned._started == started and c['ledger'].read_bytes() == before
        row = _json(c['ledger'])['reservations'][owned.reservation_id]
        assert row['status'] == 'active' and row['storage_bytes'] == kwargs['storage_bytes']
        assert row['artifacts_durable_asserted'] is False


def test_local_observation_stop_rejects_other_owner_and_second_token(private_control):
    import threading
    c = private_control
    _, _, _, first_kwargs = _ordinary_scratch_prepare(c, memory_mb=512, child_process_slots=1)
    _, _, _, second_kwargs = _ordinary_scratch_prepare(c, memory_mb=512, child_process_slots=1)
    with _owner(c, first_kwargs) as first, _owner(c, second_kwargs) as second:
        token = first._new_local_observation_stop(threading.Event())
        with pytest.raises(validation.ValidationResourceError):
            first._new_local_observation_stop(threading.Event())
        with pytest.raises(validation.ValidationResourceError):
            second.check_limits(_observer_stop=token)
        with pytest.raises(validation.ValidationResourceError):
            second._stop_local_observation(token)
        assert first._live_inventory_active is second._live_inventory_active is True


def test_local_observation_stop_cannot_enter_full_census_path(private_control):
    import threading
    c = private_control
    _, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        token = owned._new_local_observation_stop(threading.Event())
        with pytest.raises(validation.ValidationResourceError):
            owned.check_limits(full=True, _observer_stop=token)
        assert owned.check_limits(full=True)['full_ledger_check'] is True
        assert owned._live_inventory_active is True


def test_local_observation_stop_interrupts_actual_descriptor_walker_after_owned_zero(private_control, monkeypatch):
    import threading
    c = private_control
    _, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        finished, entered, release, done = (threading.Event() for _ in range(4))
        token = owned._new_local_observation_stop(finished)
        target = owned.output_layout['tmp'] / 'observer-fence'; target.write_bytes(b'ordinary fixed payload')
        actual_stat, parent = os.stat, target.parent.stat()
        hits, outcomes, started = [], {}, owned._started
        def gated_stat(path, *args, **options):
            result = actual_stat(path, *args, **options)
            fd = options.get('dir_fd')
            if fd is not None and path == target.name and options.get('follow_symlinks') is False:
                info = os.fstat(fd)
                if (info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino) and not hits:
                    hits.append(True); entered.set(); assert release.wait(timeout=2)
            return result
        worker = threading.Thread(name='actual-stoppable-observer-walker', daemon=True,
            target=_local_observation_thread_worker, args=(owned, token, outcomes, done))
        with monkeypatch.context() as patch:
            patch.setattr(os, 'stat', gated_stat)
            try:
                worker.start(); assert entered.wait(timeout=2)
                assert not finished.is_set()
                assert owned._stop_local_observation(token)['live_processes'] == 0
                assert finished.is_set()
            finally:
                _join_live_census_test_workers([worker], release)
        assert done.is_set() and hits == [True]
        assert outcomes['sample'][0] == 'error'
        assert type(outcomes['sample'][1]) is validation.LocalValidationObservationStopped
        assert outcomes['sample'][1]._observer_stop is token
        assert owned._accept_local_observation_stop(outcomes['sample'][1], token) is True
        assert owned._live_inventory_thread is None and owned._live_inventory_in_progress is False
        assert owned._live_inventory_active is False and owned._started == started
        assert target.read_bytes() == b'ordinary fixed payload' and owned._sealed is None


def test_local_observation_stop_interrupts_serialized_waiter_without_entering_walker(private_control, monkeypatch):
    import threading
    c = private_control
    _, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        finished, attempted, done, release = (threading.Event() for _ in range(4))
        token = owned._new_local_observation_stop(finished)
        actual_lock, scans, outcomes, started = owned._live_inventory_lock, [], {}, owned._started
        def acquiring(duration):
            assert 0 < duration <= 0.100001; attempted.set()
        def forbidden_walk(**options):
            scans.append(options); raise AssertionError('stopped serialized observer entered a descriptor walk')
        worker = threading.Thread(name='actual-stoppable-observer-waiter', daemon=True,
            target=_local_observation_thread_worker, args=(owned, token, outcomes, done))
        actual_lock.acquire()
        try:
            with monkeypatch.context() as patch:
                patch.setattr(owned, '_live_inventory_lock', _ObservedLiveCensusLock(actual_lock, acquiring))
                patch.setattr(owned, '_physical_inventory', forbidden_walk)
                try:
                    worker.start(); assert attempted.wait(timeout=2)
                    assert not finished.is_set()
                    assert owned._stop_local_observation(token)['live_processes'] == 0
                    assert finished.is_set()
                    worker.join(timeout=2)
                    assert not worker.is_alive() and done.is_set()
                finally:
                    actual_lock.release(); _join_live_census_test_workers([worker], release)
        finally:
            assert not worker.is_alive()
        assert outcomes['sample'][0] == 'error'
        assert type(outcomes['sample'][1]) is validation.LocalValidationObservationStopped
        assert outcomes['sample'][1]._observer_stop is token and scans == []
        assert owned._accept_local_observation_stop(outcomes['sample'][1], token) is True
        assert owned._live_inventory_thread is None and owned._live_inventory_in_progress is False
        assert owned._started == started and owned._sealed is None


def test_local_observation_stop_does_not_reclassify_default_formal_stop(private_control, monkeypatch):
    c = private_control
    attempt, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        target = owned.output_layout['tmp'] / 'default-formal-fence'; target.write_bytes(b'fixed')
        actual_stat, reached = os.stat, []
        def stop_at_leaf(path, *args, **options):
            result = actual_stat(path, *args, **options)
            if options.get('dir_fd') is not None and path == target.name and not reached:
                reached.append(True); owned._require_processes_stopped()
            return result
        with monkeypatch.context() as patch:
            patch.setattr(os, 'stat', stop_at_leaf)
            with pytest.raises(validation.ValidationResourceError) as caught:
                owned._usage_inventory(attempt)
        assert type(caught.value) is not validation.LocalValidationObservationStopped
        assert reached == [True] and owned._live_inventory_active is False
        assert owned._live_inventory_thread is None and owned._live_inventory_in_progress is False


@pytest.mark.parametrize('fault', ['source', 'deadline', 'native_cancellation'])
def test_local_observation_stop_keeps_original_guard_failures_primary(private_control, monkeypatch, fault):
    from types import SimpleNamespace
    import threading
    c = private_control
    _, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        finished = threading.Event(); token = owned._new_local_observation_stop(finished)
        assert not finished.is_set()
        assert owned._stop_local_observation(token)['live_processes'] == 0
        assert finished.is_set()
        original_source, actual_time = c['source'].read_bytes(), validation.time
        try:
            with monkeypatch.context() as patch:
                if fault == 'source': c['source'].write_bytes(original_source + b'\n# changed current private source\n')
                elif fault == 'deadline':
                    patch.setattr(validation, 'time', SimpleNamespace(monotonic=lambda: owned._started + owned.validation_timeout_seconds + 1))
                else: assert owned._lease.cancel() is True
                with pytest.raises((validation.ValidationResourceError, native_disk.DaemonResourceError)) as caught:
                    owned.check_limits(_observer_stop=token)
                assert type(caught.value) is not validation.LocalValidationObservationStopped
        finally:
            if c['source'].read_bytes() != original_source: c['source'].write_bytes(original_source)
        assert owned._sealed is None


def test_local_observation_stop_keeps_already_observed_storage_overrun_primary(private_control, monkeypatch):
    import threading
    c = private_control
    _, _, _, kwargs = _ordinary_scratch_prepare(c, storage_bytes=1000)
    with _owner(c, kwargs) as owned:
        finished, entered, release, done = (threading.Event() for _ in range(4))
        token = owned._new_local_observation_stop(finished)
        target = owned.output_layout['tmp'] / 'overrun'; target.write_bytes(b'x' * 1001)
        actual_stat, hit, outcomes = os.stat, [], {}
        def stop_after_stat(path, *args, **options):
            result = actual_stat(path, *args, **options)
            if options.get('dir_fd') is not None and path == target.name and not hit:
                hit.append(True); entered.set(); assert release.wait(timeout=2)
            return result
        worker = threading.Thread(name='observer-overrun-priority', daemon=True,
            target=_local_observation_thread_worker, args=(owned, token, outcomes, done))
        try:
            with monkeypatch.context() as patch:
                patch.setattr(os, 'stat', stop_after_stat)
                try:
                    worker.start(); assert entered.wait(timeout=2)
                    assert not finished.is_set()
                    assert owned._stop_local_observation(token)['live_processes'] == 0
                    assert finished.is_set()
                finally:
                    _join_live_census_test_workers([worker], release)
            assert done.is_set() and hit == [True] and outcomes['sample'][0] == 'error'
            assert type(outcomes['sample'][1]) is not validation.LocalValidationObservationStopped
            assert isinstance(outcomes['sample'][1], validation.ValidationResourceError)
            assert 'storage limit' in str(outcomes['sample'][1])
        finally:
            target.unlink()


def test_local_observation_stop_refuses_a_genuine_live_owned_child(private_control):
    import threading
    c = private_control
    _, manifest, request, kwargs = _ordinary_scratch_prepare(c, mode='waiting')
    with _owner(c, kwargs) as owned:
        finished = threading.Event(); token = owned._new_local_observation_stop(finished)
        process = _start_attached(owned, request, manifest)
        try:
            assert process.poll() is None
            assert not finished.is_set()
            with pytest.raises(validation.ValidationResourceError) as caught:
                owned._stop_local_observation(token)
            assert type(caught.value) is not validation.LocalValidationObservationStopped
            assert process.poll() is None and owned._live_inventory_active is True
            assert not finished.is_set()
            assert owned._sealed is None
        finally:
            _stop_group(process)


@pytest.mark.parametrize('kind', ['symlink', 'fifo'])
def test_local_observation_stop_never_relaxes_final_strict_sealing(private_control, kind):
    import threading
    c = private_control
    _, manifest, request, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        finished = threading.Event(); token = owned._new_local_observation_stop(finished)
        result = _complete(owned, request, manifest)
        assert not finished.is_set()
        assert owned._stop_local_observation(token)['live_processes'] == 0
        assert finished.is_set()
        target = owned.output_layout['tmp'] / 'retained-ordinary'; target.write_bytes(b'fixed retained body')
        unsafe = owned.output_layout['tmp'] / 'strict-leaf'
        if kind == 'symlink': unsafe.symlink_to(target)
        else: os.mkfifo(unsafe)
        try:
            with pytest.raises((validation.ValidationResourceError, native_disk.DaemonResourceError)) as caught:
                owned.seal_results(result)
            assert type(caught.value) is not validation.LocalValidationObservationStopped
            assert owned._sealed is None
            assert not (owned.output_layout['logs'] / 'validation-durability.json').exists()
        finally:
            unsafe.unlink()
        assert target.read_bytes() == b'fixed retained body' and owned._live_inventory_active is False



@pytest.mark.parametrize('kind', ['wrong_exception', 'subclass', 'foreign_binding', 'unissued_token', 'unarmed'])
def test_local_observation_stop_accepts_only_exact_scoped_verified_signal(private_control, kind):
    import threading
    c = private_control
    _, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        finished = threading.Event(); token = owned._new_local_observation_stop(finished)
        if kind != 'unarmed':
            assert owned._stop_local_observation(token)['live_processes'] == 0
        class ForeignStop(validation.LocalValidationObservationStopped):
            pass
        error = (RuntimeError('real unrelated failure') if kind == 'wrong_exception' else
            ForeignStop(token) if kind == 'subclass' else
            validation.LocalValidationObservationStopped(object() if kind == 'foreign_binding' else token))
        offered_token = object() if kind == 'unissued_token' else token
        with pytest.raises(validation.ValidationResourceError):
            owned._accept_local_observation_stop(error, offered_token)
        assert owned._sealed is None


@pytest.mark.parametrize('boundary', ['observe', 'arm'])
def test_local_observation_stop_preserves_original_observer_and_creator_threads(private_control, boundary):
    import threading
    c = private_control
    _, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        finished, done = threading.Event(), threading.Event()
        token = owned._new_local_observation_stop(finished)
        if boundary == 'observe': assert owned.check_limits(_observer_stop=token)['full_ledger_check'] is False
        outcome = []
        def foreign_thread():
            try:
                if boundary == 'observe': owned.check_limits(_observer_stop=token)
                else: owned._stop_local_observation(token)
                outcome.append(('unexpected_success', None))
            except BaseException as error: outcome.append(('error', error))
            finally: done.set()
        worker = threading.Thread(name='foreign-local-observation-thread', daemon=True, target=foreign_thread)
        worker.start(); worker.join(timeout=3)
        assert not worker.is_alive() and done.is_set()
        assert len(outcome) == 1 and outcome[0][0] == 'error'
        assert type(outcome[0][1]) is validation.ValidationResourceError
        assert not finished.is_set() and owned._live_inventory_active is True and owned._sealed is None



def test_local_observation_stop_diagnostic_bounds_actual_thread_stack_without_locals():
    import threading
    module, _ = _lifecycle_launcher_module()
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    outcomes = []
    canary = 'private-test-local-value-must-never-be-exported-8d41a9'
    def gated_thread(depth):
        private_local_canary = canary
        if depth:
            return gated_thread(depth - 1)
        entered.set()
        assert release.wait(timeout=3)
        assert private_local_canary == canary
        outcomes.append('returned')
    monitor = threading.Thread(name='diagnostic-only-owned-thread', daemon=True, target=gated_thread, args=(24,))
    try:
        monitor.start(); assert entered.wait(timeout=2)
        observation = module._validation_watchdog_shutdown_observation(
            monitor, finished, {}, request_sha256='a' * 64, phase='unit_actual_gated_thread')
        assert observation['schema'] == 'owned-validation-watchdog-shutdown-observation/v1'
        assert observation['scope'] == 'local_watcher_observation_only'
        assert observation['authority_granted'] is False and observation['join_timeout_seconds'] == 5
        assert observation['request_sha256'] == 'a' * 64
        assert observation['monitor_alive'] is True and observation['finished_event_set'] is False
        assert observation['monitor_ident'] == monitor.ident and observation['monitor_native_id'] == monitor.native_id
        assert observation['stage'] == 'unknown' and observation['stage_elapsed_seconds'] >= 0
        assert len(observation['stack']) == 16 and observation['stack_truncated'] is True
        for row in observation['stack']:
            assert set(row) == {'file', 'function', 'line'}
            assert type(row['file']) is str and len(row['file']) <= 512 and '\x00' not in row['file']
            assert type(row['function']) is str and len(row['function']) <= 128 and '\x00' not in row['function']
            assert type(row['line']) is int and row['line'] > 0
        assert any(row['function'].endswith('gated_thread') for row in observation['stack'])
        assert canary not in json.dumps(observation) and 'sdk_observation' not in observation
        assert not any(key in observation for key in ('locals', 'source_closed', 'native_closed', 'storage_released', 'admitted'))
        assert not finished.is_set() and monitor.is_alive()
    finally:
        release.set()
        if monitor.ident is not None: monitor.join(timeout=3)
    assert not monitor.is_alive() and outcomes == ['returned']
    finished.set()
    closed_thread = module._validation_watchdog_shutdown_observation(
        monitor, finished, {}, request_sha256='a' * 64, phase='unit_thread_returned')
    assert closed_thread['monitor_alive'] is False and closed_thread['finished_event_set'] is True
    assert closed_thread['scope'] == 'local_watcher_observation_only' and closed_thread['authority_granted'] is False
    assert closed_thread['stack'] == [] and closed_thread['stack_truncated'] is False



def test_local_observation_stop_keeps_observed_unsafe_directory_primary(private_control, monkeypatch):
    import threading
    c = private_control
    _, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        finished, entered, release, done = (threading.Event() for _ in range(4))
        token = owned._new_local_observation_stop(finished)
        target = owned.output_layout['tmp'] / 'known-unsafe-directory'
        target.mkdir(mode=0o700); target.chmod(0o777)
        parent, actual_stat = target.parent.stat(), os.stat
        hits, outcomes = [], {}
        def gate_bad_directory(path, *args, **options):
            result = actual_stat(path, *args, **options)
            fd = options.get('dir_fd')
            if fd is not None and path == target.name and options.get('follow_symlinks') is False:
                info = os.fstat(fd)
                if (info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino) and not hits:
                    assert stat.S_ISDIR(result.st_mode) and stat.S_IMODE(result.st_mode) == 0o777
                    hits.append(True); entered.set(); assert release.wait(timeout=2)
            return result
        worker = threading.Thread(name='observer-known-unsafe-directory', daemon=True,
            target=_local_observation_thread_worker, args=(owned, token, outcomes, done))
        try:
            with monkeypatch.context() as patch:
                patch.setattr(os, 'stat', gate_bad_directory)
                try:
                    worker.start(); assert entered.wait(timeout=2)
                    assert not finished.is_set()
                    assert owned._stop_local_observation(token)['live_processes'] == 0
                    assert finished.is_set()
                finally:
                    _join_live_census_test_workers([worker], release)
            assert done.is_set() and hits == [True] and outcomes['sample'][0] == 'error'
            assert type(outcomes['sample'][1]) is validation.ValidationResourceError
            assert 'directory must be owned and nonwritable' in str(outcomes['sample'][1])
            assert owned._live_inventory_thread is None and owned._live_inventory_in_progress is False
            assert owned._sealed is None
        finally:
            target.chmod(0o700); target.rmdir()


@pytest.mark.parametrize('action', ['cached_arm', 'accept'])
def test_local_observation_stop_simulated_foreign_pid_refuses_cached_paths(private_control, monkeypatch, action):
    """Model only getpid mismatch; no fork, process, Source or new authority."""
    import threading
    c = private_control
    _, _, _, kwargs = _ordinary_scratch_prepare(c)
    with _owner(c, kwargs) as owned:
        finished = threading.Event(); token = owned._new_local_observation_stop(finished)
        assert owned._stop_local_observation(token)['live_processes'] == 0 and finished.is_set()
        actual_os, scope = validation.os, owned._local_observation_scope()
        class SimulatedForeignPID:
            def getpid(self): return actual_os.getpid() + 1
            def __getattr__(self, name): return getattr(actual_os, name)
        original_error = validation.LocalValidationObservationStopped(token)
        before = c['ledger'].read_bytes()
        with monkeypatch.context() as patch:
            patch.setattr(validation, 'os', SimulatedForeignPID())
            assert owned._local_observation_scope() == scope
            with pytest.raises(validation.ValidationResourceError,
                    match='^local observation stop belongs to the actual original owner process$'):
                if action == 'cached_arm': owned._stop_local_observation(token)
                else: owned._accept_local_observation_stop(original_error, token)
        assert validation.os is actual_os and owned._local_observation_scope() == scope
        assert c['ledger'].read_bytes() == before and owned._sealed is None


@pytest.mark.parametrize('boundary', [
    'token_creation_owner_exit',
    'attach_process_cleanup_owner_exit',
    'attach_observer_stop_owner_exit',
    'attach_join_owner_exit',
    'legacy_attach_owner_exit',
])
def test_cli_shutdown_control_preserves_original_v5_failure_before_and_after_token(
        private_control, monkeypatch, boundary):
    """Execute real CLI control flow against explicit modeled boundaries.

    No modeled owner/process/thread can witness Native, process, Source or
    storage closure. Genuine private-owner stop coverage remains in the other
    local_observation_stop cases. This case tests exception identity/order.
    """
    import threading
    from types import SimpleNamespace
    c = private_control
    module, _, attempt, manifest, value, _ = _prepare_no_child_lifecycle(c)
    legacy = boundary == 'legacy_attach_owner_exit'
    if not legacy:
        value['schema'] = 'owned-validation-request/v5'
        value['ordinary_scratch_profile'] = {'schema': 'owned-validation-ordinary-scratch-live/v1'}
    _write_json(manifest, value)
    logs = attempt / 'modeled-unit-logs'; logs.mkdir(mode=0o700)
    before = c['ledger'].read_bytes(), c['scheduler'].state_path.read_bytes()
    primary = RuntimeError('modeled original token or attachment failure')
    exit_failure = OSError('modeled secondary owner-exit failure')
    cleanup_failure = OSError('modeled secondary process-cleanup failure')
    stop_failure = OSError('modeled secondary observer-stop failure')
    join_failure = OSError('modeled secondary observer-join failure')
    token, events, original_handlers = object(), [], {}
    observed_signals = []
    finished_events = []

    class ModeledOwner:
        _entered = False
        tracks_descendants = False
        cancelled = False
        output_layout = {'logs': logs}
        def open(self):
            events.append('open'); self._entered = True
        def _new_local_observation_stop(self, finished):
            events.append('token'); finished_events.append(finished)
            if boundary == 'token_creation_owner_exit': raise primary
            return token
        def heartbeat(self): return True
        def environment(self, environment): return dict(environment)
        def attach_child(self, pid):
            assert pid == 2000000000
            events.append('attach'); raise primary
        def _stop_local_observation(self, offered):
            assert offered is token
            events.append('observer_stop')
            if boundary == 'attach_observer_stop_owner_exit': raise stop_failure
            return {'live_processes': 0}
        def to_dict(self): return {'status': 'retained'}
        def __exit__(self, typ, error, traceback):
            events.append('owner_exit')
            assert isinstance(error, BaseException)
            raise exit_failure

    class ModeledMonitor:
        ident = native_id = None
        def __init__(self, *, target, name, daemon):
            assert callable(target) and name == 'owned-validation-local-watchdog' and daemon is True
            events.append('monitor_constructed')
        def start(self): events.append('monitor_started')
        def join(self, *, timeout):
            assert timeout == 5
            events.append('join')
            if boundary == 'attach_join_owner_exit': raise join_failure
        def is_alive(self): return False

    def event():
        result = threading.Event()
        # The CLI creates cancellation then finished events; preserve actual
        # Event behavior while avoiding an executed watchdog callback.
        observed_signals.append(result)
        return result
    def signal_handler(number, handler):
        assert number in (signal.SIGTERM, signal.SIGINT)
        if number not in original_handlers:
            original_handlers[number] = object()
            events.append(('signal_install', number))
            return original_handlers[number]
        assert handler is original_handlers[number]
        events.append(('signal_restore', number))
        return None
    child = SimpleNamespace(pid=2000000000)
    def launch(*args, **kwargs):
        events.append('spawn')
        assert kwargs['start_new_session'] is True
        return child
    def stop(process, birth, owner):
        assert process is child and birth == 'modeled-birth' and owner is offered_owner
        events.append('process_cleanup')
        if boundary == 'attach_process_cleanup_owner_exit': raise cleanup_failure
    offered_owner = ModeledOwner()
    def construct(*args, **kwargs):
        events.append('construct'); return offered_owner
    reports = []
    # Override only this script's freshness view, not process sys.modules, and
    # keep the exact prevalidated request/source bytes. These substitutes are
    # explicitly inert and must never be used as parent/custody evidence.
    with monkeypatch.context() as patch:
        patch.setattr(module, 'sys', SimpleNamespace(modules={}, path=list(sys.path), executable=sys.executable))
        patch.setattr(module, 'signal', SimpleNamespace(SIGTERM=signal.SIGTERM,
            SIGINT=signal.SIGINT, signal=signal_handler))
        patch.setattr(module, 'threading', SimpleNamespace(Event=event, Thread=ModeledMonitor))
        patch.setattr(module, 'subprocess', SimpleNamespace(Popen=launch, PIPE=subprocess.PIPE))
        patch.setattr(module, 'stop_and_reap', stop)
        patch.setattr(module, '_report_validation_watchdog_shutdown',
            lambda *args, **kwargs: reports.append(kwargs['phase']))
        patch.setattr(validation, 'ValidationResourceReservation', construct)
        patch.setattr(native_disk, '_process', lambda pid: {'birth': 'modeled-birth'} if pid == child.pid else None)
        expected = exit_failure if legacy else primary
        with pytest.raises(type(expected)) as caught:
            module.main(['--request', str(manifest), '--expected-request-sha256', _sha(manifest),
                '--resource-ledger', str(c['ledger'])])
        assert caught.value is expected
    assert before == (c['ledger'].read_bytes(), c['scheduler'].state_path.read_bytes())
    assert len(observed_signals) == 2 and observed_signals[1].is_set()
    assert events.count('owner_exit') == 1
    assert [event for event in events if isinstance(event, tuple) and event[0] == 'signal_restore'] == [
        ('signal_restore', signal.SIGTERM), ('signal_restore', signal.SIGINT)]
    if boundary == 'token_creation_owner_exit':
        assert finished_events == [observed_signals[1]]
        assert 'spawn' not in events and 'monitor_constructed' not in events
        assert 'observer_stop' not in events and 'join' not in events and reports == []
    else:
        assert events.index('spawn') < events.index('attach') < events.index('process_cleanup')
        assert events.count('join') == 1
        if not legacy:
            assert events.index('process_cleanup') < events.index('join') < events.index('owner_exit')
            assert events.count('observer_stop') == (0 if boundary == 'attach_process_cleanup_owner_exit' else 1)
    if not legacy:
        notes = getattr(primary, '__notes__', [])
        assert any('Original validation owner exit also failed: OSError: modeled secondary owner-exit failure' == note for note in notes)
        if boundary == 'attach_process_cleanup_owner_exit':
            assert any('Original process cleanup also failed: OSError: modeled secondary process-cleanup failure' == note for note in notes)
        if boundary == 'attach_observer_stop_owner_exit':
            assert any('Local watcher shutdown remained unverified: OSError: modeled secondary observer-stop failure' == note for note in notes)
        if boundary == 'attach_join_owner_exit':
            assert any(note == 'Local watcher join failed: OSError' for note in notes)
    failure = _json(logs / 'failure.json')
    assert failure['completed'] is False and failure['error'] == str(primary)
    assert failure['executed_checks'] == [] and failure['returncode'] is None
    assert all(failure[field] is False for field in ('admitted', 'Lean_admitted', 'authority_granted'))


# Fictional original-producer DATA only. These fixtures test exact V5 binding
# and current private state; they do not create a genuine Popen/wait receipt or
# qualify the historical B3 owner whose parent is no longer available.
def _closed_pre_child_v5_deadline_fixture(control):
    module, terminal, raw, caller, attempt = _closed_pre_child_postgrant_lock_fixture(control)
    request = json.loads(raw)
    request['schema'] = 'owned-validation-request/v5'
    request['ordinary_scratch_profile'] = {'schema': 'owned-validation-ordinary-scratch-live/v1'}
    raw = json.dumps(request, sort_keys=True, allow_nan=False).encode()
    pin = hashlib.sha256(raw).hexdigest()
    caller['expected_request_sha256'] = pin
    for record in (terminal, terminal['failure'], terminal['source_custody_lifecycle']):
        record['request_sha256'] = pin
    terminal['failure'].update(error_type='ResourceAdmissionDeadlineError',
        error='original absolute resource operation deadline expired',
        elapsed_seconds=request['timeout_seconds'] + 1.0)
    terminal['reservation']['ordinary_scratch_profile'] = dict(
        schema='owned-validation-ordinary-scratch-live/v1', request_sha256=pin,
        ordinary_absences_observed=0, live_exception_active=False,
        unseen_leaf_ownership_attested=False, whole_census_resampling=False)
    return module, terminal, raw, caller, attempt


def _assert_closed_pre_child_v5_unknown(module, terminal, raw, caller):
    assert module.inspect_owned_validation_no_child_native_closed_v5(terminal, raw, **caller) == {
        'verdict': 'requires_original_native_cleanup', 'source_custody_closed': False,
        'storage_release_authorized': False}


def test_pre_child_v5_postgrant_deadline_binds_original_bytes_and_keeps_v1_unknown(private_control):
    module, terminal, raw, caller, _ = _closed_pre_child_v5_deadline_fixture(private_control)
    original = raw, deepcopy(terminal)
    value, witness, reservation, row, lease = module._no_child_native_closed_profile_v5(
        terminal, raw, **caller)
    assert value['schema'] == 'owned-validation-request/v5'
    assert witness == terminal['source_custody_lifecycle'] and row == reservation['record']
    assert lease['released'] is True and lease['cancelled'] is True
    assert row['retention_reason'] == 'context_failed' and row['status'] == 'retained'
    assert module.classify_owned_validation_source_custody(terminal, raw, **caller) == dict(
        verdict='requires_original_native_cleanup', source_custody_closed=False,
        storage_release_authorized=False)
    _assert_closed_pre_child_unknown(module, terminal, raw, caller)
    assert (raw, terminal) == original


def test_pre_child_v5_postgrant_deadline_current_inspection_is_read_only(private_control, monkeypatch):
    module, terminal, raw, caller, attempt = _closed_pre_child_v5_deadline_fixture(private_control)
    before = private_control['ledger'].read_bytes(), private_control['scheduler'].state_path.read_bytes()
    original = raw, deepcopy(terminal)
    def forbidden(*args, **kwargs):
        raise AssertionError('inspection cannot acquire, write, inventory or release a claim')
    monkeypatch.setattr(native.GlobalResourceScheduler, 'acquire', forbidden)
    monkeypatch.setattr(existing._PinnedGlobalResourceScheduler, '_persist_locked_state', forbidden)
    monkeypatch.setattr(native_disk.DaemonResourceReservation, '_write', forbidden)
    monkeypatch.setattr(native_disk.DaemonResourceReservation, '_account', forbidden)
    assert module.inspect_owned_validation_no_child_native_closed_v5(terminal, raw, **caller) == dict(
        verdict='proven_original_no_child_native_closed', source_custody_closed=True,
        storage_release_authorized=False)
    assert (private_control['ledger'].read_bytes(), private_control['scheduler'].state_path.read_bytes()) == before
    assert (raw, terminal) == original and next(attempt.iterdir(), None) is None
    assert _json(private_control['ledger'])['reservations'][terminal['reservation']['reservation_id']]['status'] == 'retained'


@pytest.mark.parametrize('elapsed', [0, -1, 19, True, float('nan'), float('inf'), -float('inf'), 2**63])
def test_pre_child_v5_postgrant_deadline_rejects_wrong_elapsed(private_control, elapsed):
    module, terminal, raw, caller, _ = _closed_pre_child_v5_deadline_fixture(private_control)
    terminal['failure']['elapsed_seconds'] = elapsed
    _assert_closed_pre_child_v5_unknown(module, terminal, raw, caller)


@pytest.mark.parametrize('path,replacement', [
    ('failure.error_type', 'DaemonResourceError'), ('failure.error', 'disk ledger lock unavailable'),
    ('failure.process_observation', None), ('reservation.process_observation', None),
    ('reservation.record.retention_reason', 'scheduler_admission_failed'),
    ('reservation.record.status', 'released'), ('reservation.record.child', {}),
    ('reservation.record.prior_children', [{}]), ('reservation.record.artifacts_durable_asserted', True),
    ('reservation.resource_lease.released', False), ('reservation.resource_lease.cancelled', False),
    ('reservation.resource_lease.parent_lease_id', 'c'*32),
    ('source_custody_lifecycle.events.owner_open_returned', True),
    ('source_custody_lifecycle.events.child_launch_attempted', True),
    ('source_custody_lifecycle.events.child_created', True),
    ('source_custody_lifecycle.events.barrier_release_attempted', True),
    ('source_custody_lifecycle.events.owner_exit_handling_completed', False),
    ('source_custody_lifecycle.owner_child_attached', True),
    ('source_custody_lifecycle.native_grant.status', 'unknown'),
    ('source_custody_lifecycle.source_guards.source_pins_unchanged', False),
    ('source_custody_lifecycle.producer.sha256', '0'*64),
    ('source_custody_lifecycle.owner.birth', '654321'),
    ('reservation.ordinary_scratch_profile.request_sha256', '0'*64),
    ('reservation.ordinary_scratch_profile.ordinary_absences_observed', False),
    ('reservation.ordinary_scratch_profile.ordinary_absences_observed', 1),
    ('reservation.ordinary_scratch_profile.live_exception_active', True),
    ('reservation.ordinary_scratch_profile.unseen_leaf_ownership_attested', True),
    ('reservation.ordinary_scratch_profile.whole_census_resampling', True),
    ('reservation.cleanup_error', 'ResourceAdmissionDeadlineError'),
    ('process_cleanup_error', 'uncertain'), ('owner_exit_error', 'uncertain'),
])
def test_pre_child_v5_postgrant_deadline_rejects_incomplete_or_crossed_evidence(private_control, path, replacement):
    module, terminal, raw, caller, _ = _closed_pre_child_v5_deadline_fixture(private_control)
    target = terminal
    fields = path.split('.')
    for key in fields[:-1]: target = target[key]
    target[fields[-1]] = replacement
    _assert_closed_pre_child_v5_unknown(module, terminal, raw, caller)


@pytest.mark.parametrize('side', ['failure', 'reservation'])
@pytest.mark.parametrize('fault', ['top_live_bool', 'top_rss_float', 'group_available_int',
    'group_live_bool', 'group_rss_float', 'observed_tuple', 'observed_nonempty',
    'out_of_group_nonempty', 'tracking_none', 'scope_wrong', 'extra_field', 'group_extra'])
def test_pre_child_v5_postgrant_deadline_rejects_nonexact_zero_samples(private_control, side, fault):
    module, terminal, raw, caller, _ = _closed_pre_child_v5_deadline_fixture(private_control)
    observed = terminal[side]['process_observation']
    if fault == 'top_live_bool': observed['live_processes'] = False
    elif fault == 'top_rss_float': observed['rss_bytes'] = 0.0
    elif fault == 'group_available_int': observed['group_rss']['available'] = 1
    elif fault == 'group_live_bool': observed['group_rss']['live_processes'] = False
    elif fault == 'group_rss_float': observed['group_rss']['rss_bytes'] = 0.0
    elif fault == 'observed_tuple': observed['observed_identities'] = ()
    elif fault == 'observed_nonempty': observed['observed_identities'] = [{'pid': 1, 'birth': '1'}]
    elif fault == 'out_of_group_nonempty': observed['out_of_group_live_identities'] = [{'pid': 1, 'birth': '1'}]
    elif fault == 'tracking_none': observed['tracking_error'] = None
    elif fault == 'scope_wrong': observed['scope'] = 'isolated_process_group_only'
    elif fault == 'extra_field': observed['extra'] = 0
    else: observed['group_rss']['extra'] = 0
    _assert_closed_pre_child_v5_unknown(module, terminal, raw, caller)


@pytest.mark.parametrize('fault', ['source_drift', 'missing_pin', 'unsupported_schema', 'row_drift',
    'row_boolean_alias', 'nonempty_attempt', 'directory_identity', 'owner_present',
    'native_root', 'native_orphan_descendant', 'native_waiter', 'late_owner', 'late_waiter', 'expired_deadline'])
def test_pre_child_v5_postgrant_deadline_rechecks_current_and_late_custody(private_control, monkeypatch, fault):
    with monkeypatch.context() as patch:
        patch.setitem(globals(), '_closed_pre_child_fixture', _closed_pre_child_v5_deadline_fixture)
        patch.setitem(globals(), '_assert_closed_pre_child_unknown', _assert_closed_pre_child_v5_unknown)
        test_pre_child_closed_native_inspection_rechecks_current_custody(private_control, patch, fault)


def _bind_fictional_v5_fixture_to_test_wait_process(control, process):
    # This changes fictional binding DATA only, never represents original CLI
    # producer evidence or Native closure. The caller tests return UNKNOWN.
    identity = _wait_for(lambda: native_disk._process(process.pid), 'test wait process birth missing')
    module, terminal, raw, caller, attempt = _closed_pre_child_v5_deadline_fixture(control)
    caller['owner_pid'], caller['owner_birth'] = process.pid, identity['birth']
    terminal['source_custody_lifecycle']['owner'] = {'pid': process.pid, 'birth': identity['birth']}
    reservation = terminal['reservation']
    reservation['record']['owner_pid'] = reservation['resource_lease']['owner_pid'] = process.pid
    ledger = _json(control['ledger'])
    ledger['reservations'][reservation['reservation_id']] = deepcopy(reservation['record'])
    _write_json(control['ledger'], ledger)
    return module, terminal, raw, caller, attempt


def test_pre_child_v5_caller_genuinely_waits_and_clamps_original_cutoff(private_control, monkeypatch):
    process = subprocess.Popen([sys.executable, '-B', '-c', 'import time;time.sleep(.05);raise SystemExit(1)'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        module, terminal, raw, caller, _ = _bind_fictional_v5_fixture_to_test_wait_process(private_control, process)
        observations = []
        unknown = dict(verdict='requires_original_native_cleanup', source_custody_closed=False,
            storage_release_authorized=False)
        cutoff = time.monotonic() + 2
        def inspect(*args, **kwargs):
            # UNKNOWN sentinel exercises only wait/clock integration; it does
            # not authenticate this fictional original lifecycle fixture.
            observations.append((process.returncode, kwargs['owner_pid'],
                kwargs['cleanup_timeout_seconds'], native.resource_operation_deadline()))
            return unknown
        monkeypatch.setattr(module, 'inspect_owned_validation_no_child_native_closed_v5', inspect)
        assert module.wait_and_inspect_owned_validation_no_child_native_closed_v5(process, terminal, raw,
            expected_request_sha256=caller['expected_request_sha256'], owner_birth=caller['owner_birth'],
            expected_resource_ledger=caller['expected_resource_ledger'],
            original_wait_deadline_monotonic=cutoff) == unknown
        assert process.returncode == 1 and len(observations) == 1
        code, pid, timeout, deadline = observations[0]
        assert code == 1 and pid == process.pid and 0 < timeout < 2
        assert deadline.cleanup_only is True and deadline.native_deadline_monotonic == cutoff
        assert native.resource_operation_deadline() is None
    finally:
        process.wait(timeout=5)


@pytest.mark.parametrize('cutoff', [True, float('nan'), float('inf'), -1])
def test_pre_child_v5_caller_refuses_invalid_or_exhausted_original_cutoff_before_wait(private_control, monkeypatch, cutoff):
    process = subprocess.Popen([sys.executable, '-B', '-c', 'raise SystemExit(1)'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        module, _ = _lifecycle_launcher_module()
        calls = []
        def forbidden(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError('an invalid/exhausted original cutoff cannot wait or inspect')
        monkeypatch.setattr(process, 'wait', forbidden)
        monkeypatch.setattr(module, 'inspect_owned_validation_no_child_native_closed_v5', forbidden)
        assert module.wait_and_inspect_owned_validation_no_child_native_closed_v5(process, {}, b'',
            expected_request_sha256='0'*64, owner_birth='1', expected_resource_ledger='/not-opened',
            original_wait_deadline_monotonic=cutoff) == dict(
                verdict='requires_original_native_cleanup', source_custody_closed=False,
                storage_release_authorized=False)
        # The helper catches BaseException; assert call absence outside it.
        assert calls == []
    finally:
        subprocess.Popen.wait(process, timeout=5)


def test_pre_child_v5_caller_refuses_fabricated_process_without_inspection(monkeypatch):
    module, _ = _lifecycle_launcher_module()
    calls = []
    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError('external process assertions cannot authorize inspection')
    monkeypatch.setattr(module, 'inspect_owned_validation_no_child_native_closed_v5', forbidden)
    assert module.wait_and_inspect_owned_validation_no_child_native_closed_v5(
        {'pid': 1, 'returncode': 1, 'genuine_wait_completed': True}, {}, b'',
        expected_request_sha256='0'*64, owner_birth='1', expected_resource_ledger='/not-opened',
        original_wait_deadline_monotonic=time.monotonic()+1) == dict(
            verdict='requires_original_native_cleanup', source_custody_closed=False,
            storage_release_authorized=False)
    assert calls == []


@pytest.mark.parametrize('cleanup_only', [False, True])
def test_pre_child_v5_caller_wait_itself_honors_earlier_parent_native_end(private_control, monkeypatch, cleanup_only):
    # An actual tiny Popen exercises only wait/clock ordering. UNKNOWN remains
    # the inspector sentinel: this is never original CLI custody evidence.
    process = subprocess.Popen([sys.executable, '-B', '-c', 'import time;time.sleep(.05);raise SystemExit(1)'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        module, terminal, raw, caller, _ = _bind_fictional_v5_fixture_to_test_wait_process(private_control, process)
        calls = []
        real_wait = process.wait
        def wait(*args, **kwargs):
            calls.append(('wait', kwargs['timeout']))
            return real_wait(*args, **kwargs)
        unknown = dict(verdict='requires_original_native_cleanup', source_custody_closed=False,
            storage_release_authorized=False)
        def inspect(*args, **kwargs):
            calls.append(('inspect', kwargs['cleanup_timeout_seconds'], native.resource_operation_deadline()))
            return unknown
        monkeypatch.setattr(process, 'wait', wait)
        monkeypatch.setattr(module, 'inspect_owned_validation_no_child_native_closed_v5', inspect)
        before = time.monotonic()
        parent_end = before + 1
        original_cutoff = before + 2
        context = (native.resource_cleanup_deadline(native_deadline_monotonic=parent_end)
                   if cleanup_only else native.resource_admission_deadline(
                       work_deadline_monotonic=parent_end, native_deadline_monotonic=parent_end))
        with context:
            assert module.wait_and_inspect_owned_validation_no_child_native_closed_v5(process, terminal, raw,
                expected_request_sha256=caller['expected_request_sha256'], owner_birth=caller['owner_birth'],
                expected_resource_ledger=caller['expected_resource_ledger'],
                original_wait_deadline_monotonic=original_cutoff) == unknown
        assert [row[0] for row in calls] == ['wait', 'inspect']
        assert 0 < calls[0][1] <= 1  # The original two-second window cannot win.
        assert 0 < calls[1][1] <= 1
        assert calls[1][2].cleanup_only is True
        assert calls[1][2].native_deadline_monotonic == parent_end
        assert original_cutoff == before + 2
        assert native.resource_operation_deadline() is None
    finally:
        subprocess.Popen.wait(process, timeout=5)


def test_pre_child_v5_caller_exhausted_parent_refuses_before_wait_or_inspection(private_control, monkeypatch):
    process = subprocess.Popen([sys.executable, '-B', '-c', 'raise SystemExit(1)'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        module, _ = _lifecycle_launcher_module()
        calls = []
        def forbidden(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError('expired parent lifetime cannot wait or inspect')
        monkeypatch.setattr(process, 'wait', forbidden)
        monkeypatch.setattr(module, 'inspect_owned_validation_no_child_native_closed_v5', forbidden)
        parent_end = time.monotonic() + 1
        class ExpiredCallerClock:
            @staticmethod
            def monotonic():
                return parent_end + .01
        # Real original deadline metadata, with an explicit caller-clock DATA
        # observation just after expiry. No global clock or host state changes.
        with native.resource_cleanup_deadline(native_deadline_monotonic=parent_end):
            monkeypatch.setattr(module, 'time', ExpiredCallerClock)
            assert module.wait_and_inspect_owned_validation_no_child_native_closed_v5(process, {}, b'',
                expected_request_sha256='0'*64, owner_birth='1', expected_resource_ledger='/not-opened',
                original_wait_deadline_monotonic=parent_end+1) == dict(
                    verdict='requires_original_native_cleanup', source_custody_closed=False,
                    storage_release_authorized=False)
        assert calls == []  # Outside the helper's BaseException handler.
        assert native.resource_operation_deadline() is None
    finally:
        subprocess.Popen.wait(process, timeout=5)


def test_pre_child_v5_caller_does_not_promote_late_positive_observation(private_control, monkeypatch):
    process = subprocess.Popen([sys.executable, '-B', '-c', 'import time;time.sleep(.05);raise SystemExit(1)'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        module, terminal, raw, caller, _ = _bind_fictional_v5_fixture_to_test_wait_process(private_control, process)
        cutoff = time.monotonic() + 2
        class CallerClock:
            now = time.monotonic()
            @staticmethod
            def monotonic():
                return CallerClock.now
        calls = []
        def late_observation(*args, **kwargs):
            calls.append((process.returncode, native.resource_operation_deadline()))
            CallerClock.now = cutoff + .01
            # This synthetic return is a clock-boundary challenge, never an
            # authenticated original lifecycle or current Native observation.
            return dict(verdict='proven_original_no_child_native_closed', source_custody_closed=True,
                storage_release_authorized=False)
        monkeypatch.setattr(module, 'time', CallerClock)
        monkeypatch.setattr(module, 'inspect_owned_validation_no_child_native_closed_v5', late_observation)
        assert module.wait_and_inspect_owned_validation_no_child_native_closed_v5(process, terminal, raw,
            expected_request_sha256=caller['expected_request_sha256'], owner_birth=caller['owner_birth'],
            expected_resource_ledger=caller['expected_resource_ledger'],
            original_wait_deadline_monotonic=cutoff) == dict(
                verdict='requires_original_native_cleanup', source_custody_closed=False,
                storage_release_authorized=False)
        assert len(calls) == 1 and calls[0][0] == 1
        assert calls[0][1].cleanup_only is True
        assert calls[0][1].native_deadline_monotonic == cutoff
        assert native.resource_operation_deadline() is None
    finally:
        subprocess.Popen.wait(process, timeout=5)


# Real PRIVATE/LOCAL smoke source only. These cases use actual Git-backed
# Source leases, original CLI Popen/waits, a real file-backed LOCAL scheduler
# and LOCAL retained/released rows. They never touch the host scheduler/ledger,
# canonical Source locks, paid assets or old B3 history. The enclosing standard
# qualification owner remains responsible for its own separate host custody.
from contextlib import ExitStack as _V5RealExitStack
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_source_lease as _v5_real_source_owner

_V5_REAL_LOCAL_UNRESOLVED_SOURCE_CONTEXTS = []


def _v5_real_local_Source_pair(control, facts):
    # Reuse the original Source owner's actual Git namespace contract. These
    # two fresh repositories contain only private test input/control DATA.
    first = control['source'].parent
    second = first / 'second-local-source-repository'
    second.mkdir(mode=0o700)
    environment = dict(os.environ)
    for key in ('GIT_DIR','GIT_WORK_TREE','GIT_COMMON_DIR','GIT_INDEX_FILE'):
        environment.pop(key,None)
    for root in (first,second):
        result = subprocess.run(['git','-C',str(root),'init','-q'],env=environment,
            stdin=subprocess.DEVNULL,capture_output=True,timeout=5,check=False)
        assert result.returncode==0,(result.stdout,result.stderr)
    stack=_V5RealExitStack();receipts=[]
    try:
        for root in (first,second):
            receipts.append(stack.enter_context(_v5_real_source_owner.source_lease(
                root,mode='read',timeout_seconds=2)).to_dict())
    except BaseException:
        stack.close();raise
    assert all(row['mode']=='read' for row in receipts)
    facts['real_local_Source_READ_receipts']=receipts
    facts['real_local_Source_READs_closed']=False
    facts['canonical_D_A_Source_locks_owned_by_this_smoke']=False
    return stack


def _v5_real_smoke_pin_inputs(module,launcher,source,manifest,request):
    paths=[launcher,source,Path(validation.__file__),Path(native_disk.__file__),
        Path(native.__file__),Path(existing.__file__),Path(native.__file__).with_name('proof_resource_safety.py'),
        Path(_v5_real_source_owner.__file__)]
    request['source_sha256']={str(path.resolve()):_sha(path) for path in paths}
    request['schema']='owned-validation-request/v5'
    request['ordinary_scratch_profile']={'schema':'owned-validation-ordinary-scratch-live/v1'}
    request['process_scope']='sampled_birth_bound_descendants'
    _write_json(manifest,request)
    return manifest.read_bytes(),_sha(manifest)


def _v5_real_smoke_guard(request,raw,manifest):
    assert manifest.read_bytes()==raw
    assert all(_sha(Path(path))==pin for path,pin in request['source_sha256'].items())


def _v5_real_smoke_original_end(original_cutoff):
    previous=native.resource_operation_deadline()
    end=min(original_cutoff,previous.native_deadline_monotonic) if previous else original_cutoff
    assert end>time.monotonic(),'original smoke cleanup cutoff exhausted'
    return end


def _v5_real_smoke_native_absent(control,terminal,identity,original_cutoff):
    end=_v5_real_smoke_original_end(original_cutoff)
    with native.resource_cleanup_deadline(native_deadline_monotonic=end):
        reservation=terminal['reservation'];lease=reservation['resource_lease']
        observation=control['scheduler'].inspect_lease(lease['lease_id'],
            expected_request_id='validation:'+reservation['reservation_id'],expected_lane='validation',
            expected_owner_pid=identity['pid'],expected_owner_birth_marker=identity['birth'],
            bounded_lock_timeout=min(1,end-time.monotonic()))
        assert observation['status']=='absent' and observation['descendant_count']==0
        state=_json(control['scheduler'].state_path)
        assert state['leases']=={} and state['waiters']=={}
        assert native_disk._process(identity['pid']) is None
        assert time.monotonic()<end
    return observation


def _v5_real_smoke_verify_durability(attempt,terminal,pin,original_cutoff):
    end=_v5_real_smoke_original_end(original_cutoff)
    receipt_path=attempt/'logs/validation-durability.json'
    receipt=_json(receipt_path)
    assert receipt['schema']=='owned-validation-durability/v1'
    assert receipt['request_sha256']==pin
    assert receipt['reservation_id']==terminal['reservation']['reservation_id']
    assert receipt['result_path']=='logs/result.json'
    assert receipt['result_sha256']==_sha(attempt/receipt['result_path'])
    assert receipt['scope']=='owned_files_fsynced_after_recorded_group_observed_stopped'
    assert receipt['admitted'] is receipt['arbitrary_descendant_containment'] is False
    offered=receipt['files'];actual=[]
    assert 0<len(offered)<128
    for path in attempt.rglob('*'):
        assert time.monotonic()<end
        info=path.lstat()
        if stat.S_ISDIR(info.st_mode):continue
        assert stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==os.geteuid()
        if path==receipt_path:continue
        actual.append(dict(path=str(path.relative_to(attempt)),bytes=info.st_size,
            sha256=_sha(path),device=info.st_dev,inode=info.st_ino))
    assert sorted(actual,key=lambda row:row['path'])==sorted(offered,key=lambda row:row['path'])
    assert time.monotonic()<end
    return receipt


def test_real_local_v5_postgrant_SDK_deadline_wait_and_inspect_precedes_productive_gate(private_control):
    """Real two-lock handoff reaches _opened SDK cleanup, not base rollback.

    The current native-absence API and wait helper are genuine. The paired
    Source READs are actual leases over local Git input namespaces, not host
    canonical D/A Source locks or a reconstructed old-parent receipt.
    """
    control=private_control
    module,launcher,attempt,manifest,request,_=_prepare_no_child_lifecycle(control)
    request['timeout_seconds']=2
    request['child_process_slots']=1
    raw,pin=_v5_real_smoke_pin_inputs(module,launcher,control['source'],manifest,request)
    evidence=control['source'].parent
    facts=dict(schema='real-private-local-V5-SDK-postgrant-deadline-smoke/v1',
        request_sha256=pin,request_timeout_seconds=request['timeout_seconds'],stages=[],
        original_cli_genuine_wait_completed=False,unexpected_cleanup_signal=False,
        host_global_Native_or_storage_mutated=False,original_B3_qualification=False)
    stack=_v5_real_local_Source_pair(control,facts)
    cli=identity=None;ledger_fd=scheduler_fd=None;stdout=stderr=None
    source_proven=False;closed=False
    ledger_path=control['ledger'].with_name(control['ledger'].name+'.lock')
    original_cutoff=None
    def stage(name,**fields):facts['stages'].append(dict(stage=name,monotonic=time.monotonic(),**fields))
    def unlock(which):
        nonlocal ledger_fd,scheduler_fd
        fd=ledger_fd if which=='ledger' else scheduler_fd
        if fd is not None:
            fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
            if which=='ledger':ledger_fd=None
            else:scheduler_fd=None
    def alive():
        current=native_disk._process(cli.pid)
        assert current is not None and identity is not None
        assert (current['pid'],current['birth'])==(cli.pid,identity['birth'])
        assert cli.poll() is None,facts
    def until(predicate,label,end):
        while True:
            alive();found=predicate()
            if found:return found
            remaining=end-time.monotonic();assert remaining>0,(label,facts)
            time.sleep(min(.005,remaining))
    def take(path,label,end):
        fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            while True:
                try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);return fd
                except BlockingIOError:
                    if cli is not None:alive()
                    remaining=end-time.monotonic();assert remaining>0,(label,facts)
                    time.sleep(min(.005,remaining))
        except BaseException:os.close(fd);raise
    try:
        ledger_fd=take(ledger_path,'initial ledger gate',time.monotonic()+1)
        lock_info=os.fstat(ledger_fd)
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',
            IPFS_DATASETS_PY_MINIMAL_IMPORTS='1',IPFS_DATASETS_AUTO_INSTALL='0',IPFS_AUTO_INSTALL='false',
            HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
        started=time.monotonic();original_cutoff=started+20
        cli=subprocess.Popen([sys.executable,'-B',str(launcher),'--request',str(manifest),
            '--expected-request-sha256',pin,'--resource-ledger',str(control['ledger'])],
            cwd=launcher.parents[3],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,start_new_session=True,close_fds=True)
        identity=native_disk._process(cli.pid);assert identity is not None
        facts.update(owner_pid=cli.pid,owner_birth=identity['birth'],original_wait_cutoff=original_cutoff)
        def initial_ledger_wait():
            with os.scandir(Path('/proc')/str(cli.pid)/'fd') as entries:
                for index,entry in enumerate(entries):
                    assert index<128
                    try:info=entry.stat(follow_symlinks=True)
                    except FileNotFoundError:continue
                    if (info.st_dev,info.st_ino)==(lock_info.st_dev,lock_info.st_ino):return entry.name
            return None
        until(initial_ledger_wait,'original initial ledger wait',started+2)
        scheduler_fd=take(control['scheduler'].lock_path,'initial scheduler gate',started+2)
        unlock('ledger')
        def reserved():
            rows=[row for row in _json(control['ledger'])['reservations'].values() if row.get('owner_pid')==cli.pid]
            assert len(rows)<=1
            return rows[0] if rows and rows[0]['status']=='reserved' else None
        row=until(reserved,'reserved original local row',started+2);rid=row['reservation_id']
        ledger_fd=take(ledger_path,'base active-update gate',started+2)
        unlock('scheduler')
        def granted():
            rows=[item for item in _json(control['scheduler'].state_path)['leases'].values()
                  if item.get('request_id')=='validation:'+rid]
            assert len(rows)<=1
            if rows:
                assert rows[0]['owner_pid']==cli.pid and rows[0]['owner_birth_marker']==identity['birth']
                return rows[0]
            return None
        grant=until(granted,'genuine original private Native grant',started+2)
        stage('genuine_native_grant_before_original_deadline',lease_id=grant['lease_id'])
        # The base is stopped on our ledger fd. Take the original scheduler
        # lock again before allowing base activation; SDK.to_dict then blocks
        # on its real cancellation read only AFTER _opened becomes true.
        scheduler_fd=take(control['scheduler'].lock_path,'SDK lease-status gate',started+2)
        unlock('ledger')
        def active_without_SDK_bindings():
            observed=_json(control['ledger'])['reservations'].get(rid)
            if observed and observed['status']=='active':
                assert observed['child'] is None and observed['prior_children']==[]
                assert 'native_lease_id' not in observed
                return observed
            return None
        active=until(active_without_SDK_bindings,'base active before SDK metadata binding',started+2)
        active_seen=time.monotonic();stage('base_active_SDK_bindings_not_written',reservation_id=rid)
        release_after=active_seen+request['timeout_seconds']+.15
        assert release_after<original_cutoff
        while time.monotonic()<release_after:
            alive();time.sleep(min(.01,max(0,release_after-time.monotonic())))
        stage('original_admission_deadline_passed_with_real_SDK_gate')
        unlock('scheduler')
        stdout,stderr=cli.communicate(timeout=max(.01,original_cutoff-time.monotonic()))
        facts['original_cli_genuine_wait_completed']=True
        assert cli.returncode==1,(stdout,stderr,facts)
        terminal=json.loads(stdout);facts['original_terminal']=terminal
        failure,reservation,witness=(terminal[key] for key in ('failure','reservation','source_custody_lifecycle'))
        assert failure['error_type']=='ResourceAdmissionDeadlineError'
        assert failure['error']=='original absolute resource operation deadline expired'
        assert failure['elapsed_seconds']>=request['timeout_seconds']
        assert failure['executed_checks']==[] and failure['returncode'] is None
        assert witness['events']=={key:key in ('owner_open_attempted','owner_exit_handling_completed') for key in module._LIFECYCLE_EVENTS}
        assert witness['owner_child_attached'] is False and witness['native_grant']['status']=='acquired'
        assert reservation['record']['retention_reason']=='context_failed'
        assert reservation['record']['child'] is None and reservation['record']['prior_children']==[]
        assert reservation['record']['status']=='retained' and reservation['record']['artifacts_durable_asserted'] is False
        assert reservation['record']['storage_bytes']==request['storage_bytes']
        for observed in (failure['process_observation'],reservation['process_observation']):
            assert observed['observed_identities']==[] and observed['live_processes']==0 and observed['rss_bytes']==0
        assert reservation['ordinary_scratch_profile']==dict(schema='owned-validation-ordinary-scratch-live/v1',
            request_sha256=pin,ordinary_absences_observed=0,live_exception_active=False,
            unseen_leaf_ownership_attested=False,whole_census_resampling=False)
        assert not tuple(attempt.iterdir())
        before=control['ledger'].read_bytes(),control['scheduler'].state_path.read_bytes()
        unknown=dict(verdict='requires_original_native_cleanup',source_custody_closed=False,storage_release_authorized=False)
        caller=dict(expected_request_sha256=pin,owner_pid=cli.pid,owner_birth=identity['birth'],
            returncode=cli.returncode,expected_resource_ledger=str(control['ledger']))
        assert module.classify_owned_validation_source_custody(terminal,raw,**caller)==unknown
        assert module.inspect_owned_validation_no_child_native_closed_v1(terminal,raw,**caller)==unknown
        # Same actual original Popen, actual wait and original cutoff. This is
        # intentionally before any productive >=1-observed-identity route.
        verdict=module.wait_and_inspect_owned_validation_no_child_native_closed_v5(cli,terminal,raw,
            expected_request_sha256=pin,owner_birth=identity['birth'],
            expected_resource_ledger=str(control['ledger']),original_wait_deadline_monotonic=original_cutoff)
        assert verdict==dict(verdict='proven_original_no_child_native_closed',source_custody_closed=True,storage_release_authorized=False)
        assert (control['ledger'].read_bytes(),control['scheduler'].state_path.read_bytes())==before
        assert _json(control['ledger'])['reservations'][rid]==reservation['record']
        facts['current_original_native_absence']=_v5_real_smoke_native_absent(control,terminal,identity,original_cutoff)
        end=_v5_real_smoke_original_end(original_cutoff)
        with native.resource_cleanup_deadline(native_deadline_monotonic=end):
            _v5_real_smoke_guard(request,raw,manifest)
            facts['typed_permission_to_close_local_Source']=verdict
            assert time.monotonic()<end
            source_proven=True
            stack.close();closed=True
            assert time.monotonic()<end
            facts['real_local_Source_READs_closed']=True
        assert _json(control['ledger'])['reservations']['foreign-retained']==control['foreign']
        facts['retained_local_storage_is_separate']=True
    finally:
        unlock('ledger');unlock('scheduler')
        try:
            if cli is not None and stdout is None:
                try:
                    stdout,stderr=cli.communicate(timeout=max(.01,(original_cutoff or time.monotonic())-time.monotonic()))
                    facts['original_cli_genuine_wait_completed']=True
                except subprocess.TimeoutExpired:
                    facts['unexpected_cleanup_signal']=True;_stop_group(cli)
                    stdout,stderr=cli.communicate(timeout=2)
        finally:
            if not closed:
                # Retain only LOCAL test contexts on an unexpected proof gap.
                # No Source-success receipt is fabricated; no daemon is added.
                _V5_REAL_LOCAL_UNRESOLVED_SOURCE_CONTEXTS.append((stack,facts))
            facts['source_proven_before_close']=source_proven
            (evidence/'real-local-v5-SDK-deadline.stdout').write_bytes(stdout or b'')
            (evidence/'real-local-v5-SDK-deadline.stderr').write_bytes(stderr or b'')
            facts['final_private_ledger']=_json(control['ledger'])
            facts['final_private_native_state']=_json(control['scheduler'].state_path)
            _write_json(evidence/'real-local-v5-SDK-deadline-observation.json',facts)


def test_real_local_ordinary_v5_newCLI_positive_smoke_closes_actual_Source_after_durable_result(private_control):
    """A genuine arithmetic child succeeds through the new CLI in local owners."""
    control=private_control
    attempt,manifest,request,_=control['prepare'](timeout_seconds=20)
    module,launcher=_lifecycle_launcher_module()
    source=control['source'].with_name('real_local_v5_success.py')
    source.write_text("import json,os\nfrom pathlib import Path\nassert 6*7==42\n"
        "p=Path(os.environ['TMPDIR'])/'actual-v5-answer.json'\n"
        "p.write_text(json.dumps({'answer':42,'pid':os.getpid()}))\nprint('real-local-v5-answer=42',flush=True)\n")
    request['argv']=[sys.executable,'-B',str(source)]
    request['selected_checks']=['actual ordinary V5 arithmetic and owned output']
    raw,pin=_v5_real_smoke_pin_inputs(module,launcher,source,manifest,request)
    facts=dict(schema='real-private-local-V5-positive-CLI-smoke/v1',request_sha256=pin,
        original_cli_genuine_wait_completed=False,host_global_Native_or_storage_mutated=False,
        original_B3_qualification=False)
    stack=_v5_real_local_Source_pair(control,facts)
    cli=identity=None;stdout=stderr=None;closed=False;source_proven=False
    cutoff=time.monotonic()+35
    try:
        environment=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',
            IPFS_DATASETS_PY_MINIMAL_IMPORTS='1',IPFS_DATASETS_AUTO_INSTALL='0',IPFS_AUTO_INSTALL='false',
            HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
        cli=subprocess.Popen([sys.executable,'-B',str(launcher),'--request',str(manifest),
            '--expected-request-sha256',pin,'--resource-ledger',str(control['ledger'])],
            cwd=launcher.parents[3],env=environment,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,start_new_session=True,close_fds=True)
        identity=native_disk._process(cli.pid);assert identity is not None
        facts.update(owner_pid=cli.pid,owner_birth=identity['birth'],original_wait_cutoff=cutoff)
        stdout,stderr=cli.communicate(timeout=max(.01,cutoff-time.monotonic()))
        facts['original_cli_genuine_wait_completed']=True
        assert cli.returncode==0,(stdout,stderr)
        terminal=json.loads(stdout);facts['original_terminal']=terminal
        reservation=terminal['reservation'];row=reservation['record']
        assert reservation['status']==row['status']=='released' and row['artifacts_durable_asserted'] is True
        assert row['validation_request_sha256']==pin and row['owner_pid']==cli.pid
        assert row['process_scope']=='sampled_birth_bound_descendants'
        assert _json(control['ledger'])['reservations'][row['reservation_id']]==row
        result=_json(attempt/'logs/result.json');execution=_json(attempt/'logs/execution.json')
        assert result['completed'] is True and result['returncode']==0 and result['request_sha256']==pin
        assert result['executed_checks']==request['selected_checks']
        assert execution['completed'] is True and execution['returncode']==0
        facts['independently_readback_durability']=_v5_real_smoke_verify_durability(attempt,terminal,pin,cutoff)
        assert reservation['ordinary_scratch_profile']['request_sha256']==pin
        assert reservation['ordinary_scratch_profile']['live_exception_active'] is False
        observation=reservation['process_observation']
        assert observation['live_processes']==0 and observation['out_of_group_live_identities']==[]
        assert observation['tracking_error']==''
        assert any(item['pid']==row['child']['pid'] and str(item['birth_ticks'])==row['child']['birth']
                   for item in observation['observed_identities'])
        assert native_disk._process(row['child']['pid']) is None
        proof=_json(attempt/'tmp/actual-v5-answer.json')
        assert proof['answer']==42 and proof['pid']==row['child']['pid']
        facts['current_original_native_absence']=_v5_real_smoke_native_absent(control,terminal,identity,cutoff)
        end=_v5_real_smoke_original_end(cutoff)
        with native.resource_cleanup_deadline(native_deadline_monotonic=end):
            _v5_real_smoke_guard(request,raw,manifest)
            assert time.monotonic()<end
            source_proven=True
            stack.close();closed=True
            assert time.monotonic()<end
            facts['real_local_Source_READs_closed']=True
        assert _json(control['ledger'])['reservations']['foreign-retained']==control['foreign']
        facts['actual_local_result_execution_and_durability_verified']=True
    finally:
        try:
            if cli is not None and stdout is None:
                try:
                    stdout,stderr=cli.communicate(timeout=max(.01,cutoff-time.monotonic()))
                    facts['original_cli_genuine_wait_completed']=True
                except subprocess.TimeoutExpired:
                    facts['unexpected_cleanup_signal']=True;_stop_group(cli)
                    stdout,stderr=cli.communicate(timeout=2)
        finally:
            if not closed:_V5_REAL_LOCAL_UNRESOLVED_SOURCE_CONTEXTS.append((stack,facts))
            facts['source_proven_before_close']=source_proven
            evidence=control['source'].parent
            (evidence/'real-local-v5-positive.stdout').write_bytes(stdout or b'')
            (evidence/'real-local-v5-positive.stderr').write_bytes(stderr or b'')
            facts['final_private_ledger']=_json(control['ledger'])
            facts['final_private_native_state']=_json(control['scheduler'].state_path)
            _write_json(evidence/'real-local-v5-positive-observation.json',facts)


# Explicit V6 startup-clock controls. These are private staged owning tests,
# not an executed qualification or a permission to replay an exhausted run.
def _startup_clock_v6_prepare(control, *, damage=None, **kwargs):
    def enable(value):
        value['schema'] = 'owned-validation-request/v6'
        value['process_scope'] = 'sampled_birth_bound_descendants'
        value['live_inventory_profile'] = {
            'schema': 'owned-validation-live-census/v1', 'max_complete_resamples': 1}
        value['startup_clock_profile'] = {
            'schema': 'owned-validation-startup-clock/v1',
            'admission_seconds': 180, 'productive_seconds': 180, 'total_seconds': 420}
        if damage is not None:
            damage(value)
    return control['prepare'](timeout_seconds=180, mutate=enable, **kwargs)


def _startup_clock_v6_pending_child(owned, request):
    # Reuse CHILD_SOURCE's existing stdin barrier. No work is offered here.
    return subprocess.Popen(request['argv'], cwd=request['cwd'],
        env=owned.environment(os.environ), stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True)


@pytest.mark.parametrize('fault', (
    'schema-v4', 'schema-v5', 'missing-profile', 'extra-profile-field',
    'admission-float', 'productive-bool', 'total-zero', 'wrong-profile-tag',
    'timeout-float', 'untracked-scope', 'resample-two'))
def test_startup_clock_v6_closed_original_request_refuses_before_admission(private_control, fault):
    control = private_control
    def damage(value):
        if fault == 'schema-v4': value['schema'] = 'owned-validation-request/v4'
        elif fault == 'schema-v5': value['schema'] = 'owned-validation-request/v5'
        elif fault == 'missing-profile': del value['startup_clock_profile']
        elif fault == 'extra-profile-field': value['startup_clock_profile']['renew'] = False
        elif fault == 'admission-float': value['startup_clock_profile']['admission_seconds'] = 180.0
        elif fault == 'productive-bool': value['startup_clock_profile']['productive_seconds'] = True
        elif fault == 'total-zero': value['startup_clock_profile']['total_seconds'] = 0
        elif fault == 'wrong-profile-tag': value['startup_clock_profile']['schema'] += '-other'
        elif fault == 'timeout-float': value['timeout_seconds'] = 180.0
        elif fault == 'untracked-scope': value['process_scope'] = 'isolated_process_group'
        else: value['live_inventory_profile']['max_complete_resamples'] = 2
    attempt, manifest, request, kwargs = _startup_clock_v6_prepare(control, damage=damage)
    ledger_before = control['ledger'].read_bytes()
    native_before = control['scheduler'].state_path.read_bytes()
    with pytest.raises(validation.ValidationResourceError):
        _owner(control, kwargs)
    assert control['ledger'].read_bytes() == ledger_before
    assert control['scheduler'].state_path.read_bytes() == native_before
    assert not any(attempt.iterdir())


def test_startup_clock_v6_real_attachment_accounting_precedes_one_work_publication(private_control, monkeypatch):
    control = private_control
    attempt, manifest, request, kwargs = _startup_clock_v6_prepare(control)
    clock = _validation_admission_clock(monkeypatch)
    with _owner(control, kwargs) as owned:
        assert owned._admission_started == 100.0 and owned._started is None
        pending = owned.startup_clock_observation()
        assert pending['schema'] == 'owned-validation-startup-clock-observation/v1'
        assert pending['admission_deadline_monotonic'] == 280.0
        assert pending['productive_started_monotonic'] is None
        assert pending['productive_deadline_monotonic'] is None
        assert pending['total_deadline_monotonic'] == 520.0
        assert pending['source_or_storage_release_authorized'] is False
        with pytest.raises(validation.ValidationResourceError, match='not started'):
            owned.require_productive_work()
        process = _startup_clock_v6_pending_child(owned, request)
        original_account = native_disk.DaemonResourceReservation._account
        accounts = []
        def account(instance, ledger, *args, **options):
            result = original_account(instance, ledger, *args, **options)
            if instance is owned:
                operation = native.resource_operation_deadline()
                assert operation.work_deadline_monotonic == 280.0
                assert operation.native_deadline_monotonic == 520.0
                assert process.poll() is None and not (attempt/'exports'/'checked.json').exists()
                accounts.append(deepcopy(result))
                clock.now = 279.9
            return result
        try:
            with monkeypatch.context() as attachment:
                attachment.setattr(native_disk.DaemonResourceReservation, '_account', account)
                owned.attach_child(process.pid)
            assert len(accounts) == 1 and accounts[0]['inventory']['entry_count'] >= 6
            assert owned._started is None and process.poll() is None
            with pytest.raises(validation.ValidationResourceError, match='one-shot'):
                owned.attach_child(process.pid)
            assert owned._started is None and owned._startup_attachment_ready is True
            assert not (attempt/'exports'/'checked.json').exists()
            identity = native_disk._process(process.pid)
            observation = owned.start_productive_work(process.pid, identity['birth'])
            assert owned.require_productive_work() is True
            assert observation['admission_started_monotonic'] == 100.0
            assert observation['productive_started_monotonic'] == 279.9
            assert observation['productive_deadline_monotonic'] == 459.9
            assert observation['total_deadline_monotonic'] == 520.0
            assert observation['attachment_attempted'] is observation['attachment_verified'] is True
            assert observation['attached_child'] == {'pid': process.pid, 'birth': identity['birth']}
            assert observation['original_native_lease_id'] == owned.to_dict()['resource_lease']['lease_id']
            assert owned.to_dict()['startup_clock_profile'] == observation
            assert observation['source_or_storage_release_authorized'] is False
            first_started = owned._started
            clock.now = 280.1
            with pytest.raises(validation.ValidationResourceError, match='one-shot'):
                owned.start_productive_work(process.pid, identity['birth'])
            assert owned._started == first_started and owned._admission_started == 100.0
            process.stdin.write('attached\n' + _sha(manifest) + '\n'); process.stdin.flush()
            process.wait(timeout=5)
            assert process.returncode == 0, process.stderr.read()
        finally:
            _stop_group(process)
        assert _json(attempt/'exports'/'checked.json')['sum'] == 6
        result = attempt/'logs'/'result.json'
        owned.seal_results(result)
        released = owned.finalize(artifacts_durable=True)
        assert released['status'] == 'released' and released['resource_lease']['released'] is True
        assert released['record']['storage_bytes'] == kwargs['storage_bytes']


def test_startup_clock_v6_open_reopen_and_early_publication_do_not_rearm(private_control, monkeypatch):
    control = private_control
    _, _, _, kwargs = _startup_clock_v6_prepare(control)
    clock = _validation_admission_clock(monkeypatch)
    with _owner(control, kwargs) as owned:
        with pytest.raises(validation.ValidationResourceError, match='attachment'):
            owned.start_productive_work(os.getpid(), native_disk._process(os.getpid())['birth'])
        with pytest.raises(validation.ValidationResourceError, match='one-shot'):
            owned.open()
        assert owned._started is None and owned._admission_started == 100.0
        clock.now = 279.0
        assert owned.guard() is True
        clock.now = 280.01
        with pytest.raises((validation.ValidationResourceError, native.ResourceAdmissionDeadlineError), match='deadline'):
            owned.guard()
        assert owned._started is None and owned._admission_started == 100.0


@pytest.mark.parametrize('fault', (
    'wrong-pid', 'wrong-birth', 'pid-reused', 'foreign-parent',
    'wrong-group', 'missing-tracker', 'native-released', 'source-drift'))
def test_startup_clock_v6_first_work_publication_requires_original_live_fences(private_control, monkeypatch, fault):
    control = private_control
    attempt, manifest, request, kwargs = _startup_clock_v6_prepare(control)
    clock = _validation_admission_clock(monkeypatch)
    with _owner(control, kwargs) as owned:
        process = _startup_clock_v6_pending_child(owned, request)
        source_before = control['source'].read_bytes()
        try:
            owned.attach_child(process.pid)
            identity = native_disk._process(process.pid)
            pid, birth = process.pid, identity['birth']
            with monkeypatch.context() as fence:
                if fault == 'wrong-pid': pid = os.getpid()
                elif fault == 'wrong-birth': birth = str(int(birth) + 1)
                elif fault in ('pid-reused', 'foreign-parent', 'wrong-group'):
                    original_process = native_disk._process
                    def observed(target):
                        value = original_process(target)
                        if target == process.pid and value is not None:
                            value = dict(value)
                            field = {'pid-reused':'birth', 'foreign-parent':'parent_pid', 'wrong-group':'group_pid'}[fault]
                            value[field] = str(int(value[field]) + 1) if field == 'birth' else value[field] + 1
                        return value
                    fence.setattr(native_disk, '_process', observed)
                elif fault == 'missing-tracker': fence.setattr(owned, '_descendants', None)
                elif fault == 'native-released': owned._lease.release()
                else: control['source'].write_bytes(source_before + b'\n# private deliberate source fence\n')
                with pytest.raises(validation.ValidationResourceError):
                    owned.start_productive_work(pid, birth)
                assert owned._started is None and owned._admission_started == 100.0
                assert process.poll() is None and not (attempt/'exports'/'checked.json').exists()
        finally:
            if control['source'].read_bytes() != source_before:
                control['source'].write_bytes(source_before)
            _stop_group(process)
    assert _json(control['ledger'])['reservations'][owned.reservation_id]['status'] == 'retained'


def test_startup_clock_v6_expired_attachment_keeps_real_child_not_no_child_data(private_control, monkeypatch):
    control = private_control
    attempt, manifest, request, kwargs = _startup_clock_v6_prepare(control)
    clock = _validation_admission_clock(monkeypatch)
    owned = _owner(control, kwargs).open()
    process = _startup_clock_v6_pending_child(owned, request)
    original_account = native_disk.DaemonResourceReservation._account
    accounts = []
    def account(instance, ledger, *args, **options):
        value = original_account(instance, ledger, *args, **options)
        if instance is owned:
            accounts.append(deepcopy(value))
            clock.now = 280.01
        return value
    try:
        with monkeypatch.context() as attachment:
            attachment.setattr(native_disk.DaemonResourceReservation, '_account', account)
            with pytest.raises((validation.ValidationResourceError, native.ResourceAdmissionDeadlineError), match='deadline'):
                owned.attach_child(process.pid)
        assert len(accounts) == 1 and owned._started is None
        assert owned._admission_started == 100.0 and owned._startup_attachment_attempted is True
        assert owned._startup_attachment_ready is False
        identity = native_disk._process(process.pid)
        assert owned._child == {'pid': process.pid, 'birth': identity['birth']}
        phase = owned.startup_clock_observation()
        assert phase['attached_child'] == owned._child
        assert phase['productive_started_monotonic'] is None
        assert phase['attachment_verified'] is False
        assert phase['source_or_storage_release_authorized'] is False
        assert not (attempt/'exports'/'checked.json').exists()
        assert process.poll() is None
    finally:
        _stop_group(process)
        owned.__exit__(None, None, None)
    row = _json(control['ledger'])['reservations'][owned.reservation_id]
    assert row['status'] == 'retained' and row['child']['pid'] == process.pid
    assert row['storage_bytes'] == kwargs['storage_bytes']
    assert _json(control['scheduler'].state_path)['leases'] == {}


def test_startup_clock_v6_failed_open_keeps_original_admission_and_no_work_epoch(private_control, monkeypatch):
    control = private_control
    attempt, manifest, request, kwargs = _startup_clock_v6_prepare(control)
    owned = _owner(control, kwargs)
    ledger_before = control['ledger'].read_bytes()
    native_before = control['scheduler'].state_path.read_bytes()
    clock = _validation_admission_clock(monkeypatch)
    guard = owned._guard_inputs
    def expired_guard():
        guard()
        clock.now = 280.01
    monkeypatch.setattr(owned, '_guard_inputs', expired_guard)
    clock.now = 100.0
    with pytest.raises(native.ResourceAdmissionDeadlineError):
        owned.open()
    assert owned._admission_started == 100.0 and owned._started is None
    assert owned._lease is None and owned._record is None and not owned._opened
    clock.now = 281.0
    with pytest.raises(validation.ValidationResourceError, match='one-shot'):
        owned.open()
    assert owned._admission_started == 100.0 and owned._started is None
    assert owned._lease is None and owned._record is None and not owned._opened
    assert control['ledger'].read_bytes() == ledger_before
    assert control['scheduler'].state_path.read_bytes() == native_before
    assert not any(attempt.iterdir())


def test_startup_clock_v6_late_opt_in_cannot_change_a_legacy_productive_epoch(private_control, monkeypatch):
    control = private_control
    _, manifest, request, kwargs = _live_census_prepare(control, timeout_seconds=180)
    clock = _validation_admission_clock(monkeypatch)
    with _owner(control, kwargs) as owned:
        legacy_started = owned._started
        assert legacy_started == 100.0 and owned._startup_clock_profile is None
        with pytest.raises(validation.ValidationResourceError, match='late opt-in'):
            owned.start_productive_work(os.getpid(), native_disk._process(os.getpid())['birth'])
        with monkeypatch.context() as late:
            late.setattr(owned, '_startup_clock_profile', {
                'schema':'owned-validation-startup-clock/v1',
                'admission_seconds':180, 'productive_seconds':180, 'total_seconds':420})
            with pytest.raises(validation.ValidationResourceError):
                owned.guard()
        assert owned._started == legacy_started and owned._admission_started == 100.0
        assert _json(manifest)['schema'] == 'owned-validation-request/v4'
        assert 'startup_clock_profile' not in _json(manifest)



def test_startup_clock_v6_productive_expiry_uses_first_work_publication(private_control, monkeypatch):
    control = private_control
    attempt, manifest, request, kwargs = _startup_clock_v6_prepare(control)
    clock = _validation_admission_clock(monkeypatch)
    with _owner(control, kwargs) as owned:
        process = _startup_clock_v6_pending_child(owned, request)
        try:
            owned.attach_child(process.pid)
            identity = native_disk._process(process.pid)
            observation = owned.start_productive_work(process.pid, identity['birth'])
            assert observation['productive_started_monotonic'] == 100.0
            assert observation['productive_deadline_monotonic'] == 280.0
            clock.now = 279.9
            assert owned.require_productive_work() is True
            clock.now = 280.01
            with pytest.raises(validation.ValidationResourceError, match='deadline'):
                owned.guard()
            with pytest.raises(validation.ValidationResourceError, match='deadline|one-shot'):
                owned.start_productive_work(process.pid, identity['birth'])
            assert owned._admission_started == owned._started == 100.0
            assert not (attempt/'exports'/'checked.json').exists()
        finally:
            _stop_group(process)


@pytest.mark.parametrize('mutation', (
    'cached-admission-float', 'cached-productive-float', 'cached-total-float',
    'request-admission-float', 'request-productive-float', 'request-total-float',
    'request-timeout-float'))
def test_startup_clock_v6_typed_frozen_profile_refuses_numeric_aliases(private_control, monkeypatch, mutation):
    control = private_control
    _, manifest, request, kwargs = _startup_clock_v6_prepare(control)
    _validation_admission_clock(monkeypatch)
    owned = _owner(control, kwargs).open()
    original_request = deepcopy(owned.request)
    original_profile = deepcopy(owned._startup_clock_profile)
    try:
        if mutation.startswith('cached-'):
            key = mutation[len('cached-'):-len('-float')] + '_seconds'
            owned._startup_clock_profile[key] = float(owned._startup_clock_profile[key])
        elif mutation == 'request-timeout-float':
            owned.request['timeout_seconds'] = 180.0
        else:
            key = mutation[len('request-'):-len('-float')] + '_seconds'
            owned.request['startup_clock_profile'][key] = float(owned.request['startup_clock_profile'][key])
        with pytest.raises(validation.ValidationResourceError, match='startup-clock|in-memory'):
            owned.guard()
        assert owned._started is None and owned._admission_started == 100.0
        assert _json(manifest) == original_request
        assert owned._startup_original_profile == ('owned-validation-request/v6', 180, 180, 420)
    finally:
        owned.request = original_request
        owned._startup_clock_profile = original_profile
        owned.__exit__(None, None, None)


@pytest.mark.parametrize('corruption', ('request-only', 'request-and-cache'))
@pytest.mark.parametrize('parent_native_end', (None, 450.0))
def test_startup_clock_v6_original_cleanup_bound_survives_mutable_opt_out(
        private_control, monkeypatch, corruption, parent_native_end):
    from contextlib import nullcontext
    control = private_control
    _, _, _, kwargs = _startup_clock_v6_prepare(control)
    _validation_admission_clock(monkeypatch)
    owned = _owner(control, kwargs).open()
    original_exit = owned._exit_observed_resources
    seen = []
    def observed_exit(exc_type, exc, traceback):
        operation = native.resource_operation_deadline()
        assert operation is not None and operation.cleanup_only
        assert operation.native_deadline_monotonic == (
            520.0 if parent_native_end is None else parent_native_end)
        seen.append(operation)
        return original_exit(exc_type, exc, traceback)
    monkeypatch.setattr(owned, '_exit_observed_resources', observed_exit)
    owned.request['schema'] = 'owned-validation-request/v4'
    del owned.request['startup_clock_profile']
    if corruption == 'request-and-cache':
        owned._startup_clock_profile = None
    assert owned._startup_original_profile == ('owned-validation-request/v6', 180, 180, 420)
    scope = (native.resource_admission_deadline(work_deadline_monotonic=400.0,
        native_deadline_monotonic=parent_native_end) if parent_native_end is not None else nullcontext())
    with scope:
        previous = native.resource_operation_deadline()
        owned.__exit__(None, None, None)
        assert native.resource_operation_deadline() is previous
    assert len(seen) == 1 and owned._started is None and owned._admission_started == 100.0
    assert _json(control['scheduler'].state_path)['leases'] == {}
    row = _json(control['ledger'])['reservations'][owned.reservation_id]
    assert row['status'] == 'retained' and row['storage_bytes'] == kwargs['storage_bytes']


def test_startup_clock_v6_forged_legacy_cleanup_cannot_select_new_profile(private_control, monkeypatch):
    control = private_control
    _, _, _, kwargs = _live_census_prepare(control, timeout_seconds=180)
    _validation_admission_clock(monkeypatch)
    owned = _owner(control, kwargs).open()
    assert owned._startup_original_profile is None and owned._started == 100.0
    original_exit = owned._exit_observed_resources
    seen = []
    def observed_exit(exc_type, exc, traceback):
        seen.append(native.resource_operation_deadline())
        return original_exit(exc_type, exc, traceback)
    monkeypatch.setattr(owned, '_exit_observed_resources', observed_exit)
    owned.request['schema'] = 'owned-validation-request/v6'
    owned.request['startup_clock_profile'] = {
        'schema':'owned-validation-startup-clock/v1',
        'admission_seconds':180, 'productive_seconds':180, 'total_seconds':420}
    owned._startup_clock_profile = deepcopy(owned.request['startup_clock_profile'])
    owned.__exit__(None, None, None)
    assert seen == [None]
    assert owned._startup_original_profile is None and owned._started == 100.0
    assert _json(control['scheduler'].state_path)['leases'] == {}


# V6 CLI controls below are software tests, not historical caller/Native proof.
@pytest.mark.parametrize('damage', (None, 'admission', 'productive', 'total', 'extra', 'timeout-float', 'resamples'))
def test_startup_clock_v6_cli_parser_preserves_closed_profile_before_owner(private_control, damage):
    module, _, _, manifest, value, _ = _prepare_no_child_lifecycle(private_control)
    value.update(schema='owned-validation-request/v6', timeout_seconds=180,
        live_inventory_profile={'schema':'owned-validation-live-census/v1','max_complete_resamples':1},
        startup_clock_profile={'schema':'owned-validation-startup-clock/v1',
            'admission_seconds':180,'productive_seconds':180,'total_seconds':420})
    if damage in ('admission','productive','total'):
        value['startup_clock_profile'][damage + '_seconds'] += 1
    elif damage == 'extra': value['startup_clock_profile']['renew'] = False
    elif damage == 'timeout-float': value['timeout_seconds'] = 180.0
    elif damage == 'resamples': value['live_inventory_profile']['max_complete_resamples'] = 2
    _write_json(manifest, value)
    ledger, native_state = private_control['ledger'].read_bytes(), private_control['scheduler'].state_path.read_bytes()
    if damage is None:
        parsed, raw = module.request(manifest, _sha(manifest))
        assert parsed == value and raw == manifest.read_bytes()
        assert module._startup_clock_no_child_request_shape(parsed, raw) is True
    else:
        with pytest.raises(ValueError, match='closed startup-clock'):
            module.request(manifest, _sha(manifest))
    assert private_control['ledger'].read_bytes() == ledger
    assert private_control['scheduler'].state_path.read_bytes() == native_state


@pytest.mark.parametrize('boundary', ('published-before-barrier', 'expired-attachment', 'publication-refused'))
def test_startup_clock_v6_cli_orders_first_publication_before_barrier_only(private_control, monkeypatch, boundary):
    """Execute CLI wiring against explicitly modeled owner/child/clock objects.

    Nothing here witnesses a real grant, process, Source closure or elapsed
    time. The separate SDK controls use actual private owners and inert PIDs.
    """
    import threading
    from types import SimpleNamespace
    c = private_control
    module, _, attempt, manifest, value, _ = _prepare_no_child_lifecycle(c)
    value.update(schema='owned-validation-request/v6', timeout_seconds=180,
        live_inventory_profile={'schema':'owned-validation-live-census/v1','max_complete_resamples':1},
        startup_clock_profile={'schema':'owned-validation-startup-clock/v1',
            'admission_seconds':180,'productive_seconds':180,'total_seconds':420})
    _write_json(manifest, value)
    logs = attempt/'logs'; logs.mkdir(mode=0o700)
    before = c['ledger'].read_bytes(), c['scheduler'].state_path.read_bytes()
    state = {'now':100.0, 'productive':None, 'barrier':False, 'attached':False}
    events, previous_signals = [], {}
    sentinel = RuntimeError('modeled stop after barrier; no test payload executed')
    refusal = RuntimeError('modeled publication refusal')
    class ModeledOwner:
        _entered = False
        tracks_descendants = False
        cancelled = False
        output_layout = {'logs':logs}
        def open(self): self._entered = True; events.append('open')
        def startup_clock_observation(self):
            return {'admission_deadline_monotonic':280.0,
                'productive_started_monotonic':state['productive'],
                'productive_deadline_monotonic':None if state['productive'] is None else state['productive'] + 180,
                'total_deadline_monotonic':520.0}
        def guard(self):
            deadline = 280.0 if state['productive'] is None else state['productive'] + 180
            assert state['now'] < deadline
            return True
        def heartbeat(self): return True
        def environment(self, base): return dict(base)
        def attach_child(self, pid):
            assert pid == 2_000_000_000
            state['attached'] = True; state['now'] = 280.1 if boundary == 'expired-attachment' else 279.9
            events.append('attach')
        def start_productive_work(self, pid, birth):
            assert state['attached'] and not state['barrier'] and state['productive'] is None
            assert pid == 2_000_000_000 and birth == '123456'
            events.append('publish')
            if boundary == 'publication-refused': raise refusal
            assert state['now'] < 280.0
            state['productive'] = state['now']
            return self.startup_clock_observation()
        def require_productive_work(self):
            assert state['productive'] == 279.9
            events.append('work_guard'); return True
        def to_dict(self): return {'status':'retained'}
        def __exit__(self, *args): self._entered = False; events.append('exit'); return False
    class ModeledMonitor:
        def __init__(self, **kwargs): pass
        def start(self): pass
        def join(self, **kwargs): pass
        def is_alive(self): return False
    class ModeledPipe:
        def write(self, value):
            assert value == b'1' and state['productive'] == 279.9
            state['barrier'] = True; events.append('barrier')
        def flush(self): pass
        def close(self): pass
    child = SimpleNamespace(pid=2_000_000_000, stdin=ModeledPipe())
    def poll(): raise sentinel
    child.poll = poll
    def launch(*args, **kwargs): events.append('spawn'); return child
    def cleanup(process, birth, owner):
        assert process is child and birth == '123456' and owner is offered
        events.append('cleanup')
    def signal_handler(number, handler):
        if number not in previous_signals:
            previous_signals[number] = object(); return previous_signals[number]
        assert handler is previous_signals[number]
    offered = ModeledOwner()
    with monkeypatch.context() as patch:
        patch.setattr(module, 'sys', SimpleNamespace(modules={}, path=list(sys.path), executable=sys.executable))
        patch.setattr(module, 'time', SimpleNamespace(monotonic=lambda:state['now'], sleep=lambda _:None))
        patch.setattr(module, 'signal', SimpleNamespace(SIGTERM=signal.SIGTERM, SIGINT=signal.SIGINT, signal=signal_handler))
        patch.setattr(module, 'threading', SimpleNamespace(Event=threading.Event, Thread=ModeledMonitor))
        patch.setattr(module, 'subprocess', SimpleNamespace(Popen=launch, PIPE=subprocess.PIPE))
        patch.setattr(module, 'stop_and_reap', cleanup)
        patch.setattr(module, '_source_custody_witness', lambda *args, **kwargs:{'modeled_only':True,'source_custody_closed':False})
        patch.setattr(validation, 'ValidationResourceReservation', lambda *args, **kwargs:offered)
        patch.setattr(native_disk, '_process', lambda pid:{'birth':'123456'} if pid == child.pid else None)
        expected = TimeoutError if boundary == 'expired-attachment' else RuntimeError
        with pytest.raises(expected) as caught:
            module.main(['--request',str(manifest),'--expected-request-sha256',_sha(manifest),
                '--resource-ledger',str(c['ledger'])])
        if boundary == 'published-before-barrier': assert caught.value is sentinel
        elif boundary == 'publication-refused': assert caught.value is refusal
        else: assert str(caught.value) == 'validation startup admission deadline exceeded'
    assert events.index('spawn') < events.index('attach') < events.index('cleanup')
    assert events.count('exit') == 1
    if boundary == 'published-before-barrier':
        assert events.index('attach') < events.index('publish') < events.index('work_guard') < events.index('barrier')
        assert state['productive'] == 279.9 and state['barrier'] is True
    else:
        assert state['productive'] is None and state['barrier'] is False and 'barrier' not in events
        assert events.count('publish') == (1 if boundary == 'publication-refused' else 0)
    assert before == (c['ledger'].read_bytes(), c['scheduler'].state_path.read_bytes())


def test_startup_clock_v6_actual_no_grant_cli_closes_only_matching_phase_owner(private_control, monkeypatch):
    """Reuse the existing real private pre-grant refusal; no new grant is made."""
    original_prepare = _prepare_pregrant_capacity
    def prepare_v6(control, *, process_scope=validation.TRACKED_SCOPE):
        module, launcher, attempt, manifest, value, kwargs = original_prepare(control, process_scope=process_scope)
        value.update(schema='owned-validation-request/v6', timeout_seconds=180,
            live_inventory_profile={'schema':'owned-validation-live-census/v1','max_complete_resamples':1},
            startup_clock_profile={'schema':'owned-validation-startup-clock/v1',
                'admission_seconds':180,'productive_seconds':180,'total_seconds':420})
        _write_json(manifest, value); kwargs['timeout_seconds'] = 180
        kwargs['frozen_validation_manifest_sha256'] = _sha(manifest)
        return module, launcher, attempt, manifest, value, kwargs
    with monkeypatch.context() as patch:
        patch.setitem(globals(), '_prepare_pregrant_capacity', prepare_v6)
        module, terminal, raw, caller, _, attempt = _actual_pregrant_capacity_cli(private_control)
    proved = {'verdict':'proven_original_no_child_no_native_grant','source_custody_closed':True,
        'storage_release_authorized':False}
    assert module.classify_owned_validation_source_custody(terminal, raw, **caller) == proved
    assert module.classify_owned_validation_startup_clock_source_custody_v1(terminal, raw, **caller) == proved
    assert terminal['reservation']['record'] is terminal['reservation']['resource_lease'] is None
    assert terminal['reservation']['startup_clock_profile']['productive_started_monotonic'] is None
    assert not tuple(attempt.iterdir())
    unknown = {'verdict':'requires_original_native_cleanup','source_custody_closed':False,
        'storage_release_authorized':False}
    for key in ('pid','birth'):
        changed = deepcopy(terminal)
        owner = changed['reservation']['startup_clock_profile']['original_owner']
        owner[key] = owner[key] + 1 if key == 'pid' else str(int(owner[key]) + 1)
        assert module.classify_owned_validation_source_custody(changed, raw, **caller) == unknown
        assert module.classify_owned_validation_startup_clock_source_custody_v1(changed, raw, **caller) == unknown
    for key in ('admission_seconds','productive_seconds','total_seconds'):
        changed = deepcopy(terminal)
        phase = changed['reservation']['startup_clock_profile']['profile']
        phase[key] = float(phase[key])
        assert module.classify_owned_validation_source_custody(changed, raw, **caller) == unknown
        assert module.classify_owned_validation_startup_clock_source_custody_v1(changed, raw, **caller) == unknown
    changed = deepcopy(terminal)
    changed['source_custody_lifecycle']['events']['child_created'] = True
    assert module.classify_owned_validation_source_custody(changed, raw, **caller) == unknown
    assert module.classify_owned_validation_startup_clock_source_custody_v1(changed, raw, **caller) == unknown


def _startup_clock_v6_fictional_wait_control(control, process):
    """Fresh v6 DATA plus an inert wait PID; never historical CLI evidence."""
    module, launcher = _lifecycle_launcher_module()
    attempt, manifest, value, _ = _startup_clock_v6_prepare(control)
    paths = [launcher, control['source'], Path(validation.__file__), Path(native_disk.__file__),
        Path(native.__file__), Path(existing.__file__), Path(native.__file__).with_name('proof_resource_safety.py')]
    value['source_sha256'] = {str(path.resolve()):_sha(path) for path in paths}
    _write_json(manifest, value)
    identity = _wait_for(lambda:native_disk._process(process.pid), 'inert v6 wait PID birth missing')
    caller = dict(expected_request_sha256=_sha(manifest), owner_birth=identity['birth'],
        expected_resource_ledger=str(control['ledger']))
    terminal = {'fictional_v6_wait_control_only':True, 'source_custody_closed':False}
    return module, terminal, manifest.read_bytes(), value, caller


@pytest.mark.parametrize('parent_kind', ('none', 'admission', 'cleanup'))
def test_startup_clock_v6_waiter_uses_original_cutoff_and_earlier_parent_only(private_control, monkeypatch, parent_kind):
    from contextlib import nullcontext
    process = subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(.05);raise SystemExit(1)'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        module, terminal, raw, value, caller = _startup_clock_v6_fictional_wait_control(private_control, process)
        calls = []; real_wait = process.wait
        unknown = dict(verdict='requires_original_native_cleanup',source_custody_closed=False,storage_release_authorized=False)
        def wait(*args, **kwargs):
            calls.append(('wait',kwargs['timeout'])); return real_wait(*args, **kwargs)
        def fictional_profile(offered, offered_raw, **kwargs):
            assert offered is terminal and offered_raw == raw and json.loads(raw)['schema'] == 'owned-validation-request/v6'
            assert process.returncode == 1 and kwargs['owner_pid'] == process.pid
            calls.append(('v6-profile',None)); return value,None,None,None,None
        def inspect(*args, **kwargs):
            # An UNKNOWN sentinel exercises dispatch/waiting only; it cannot
            # authenticate this explicitly fictional original-parent DATA.
            calls.append(('inspect',kwargs['cleanup_timeout_seconds'],native.resource_operation_deadline()))
            return unknown
        monkeypatch.setattr(process,'wait',wait)
        monkeypatch.setattr(module,'_no_child_native_closed_profile_v6',fictional_profile)
        monkeypatch.setattr(module,'inspect_owned_validation_no_child_native_closed_v6',inspect)
        before = time.monotonic(); cutoff = before+2; bound = cutoff if parent_kind == 'none' else before+1
        scope = (nullcontext() if parent_kind == 'none' else
            native.resource_admission_deadline(work_deadline_monotonic=bound,native_deadline_monotonic=bound)
            if parent_kind == 'admission' else native.resource_cleanup_deadline(native_deadline_monotonic=bound))
        with scope:
            previous = native.resource_operation_deadline()
            assert module.wait_and_inspect_owned_validation_no_child_native_closed_v6(process, terminal, raw,
                **caller, original_wait_deadline_monotonic=cutoff) == unknown
            assert native.resource_operation_deadline() is previous
        assert [row[0] for row in calls] == ['wait','v6-profile','inspect']
        assert process.returncode == 1 and 0 < calls[0][1] <= (2 if parent_kind == 'none' else 1)
        assert 0 < calls[2][1] <= (2 if parent_kind == 'none' else 1)
        assert calls[2][2].cleanup_only and calls[2][2].native_deadline_monotonic == bound
        assert cutoff == before+2 and native.resource_operation_deadline() is None
    finally:
        subprocess.Popen.wait(process,timeout=5)


@pytest.mark.parametrize('boundary', ('bool', 'nan', 'infinite', 'expired', 'over420', 'expired-parent'))
def test_startup_clock_v6_waiter_refuses_invalid_cutoff_without_wait_or_inspection(private_control, monkeypatch, boundary):
    from contextlib import nullcontext
    process = subprocess.Popen([sys.executable,'-B','-c','raise SystemExit(1)'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        module, _ = _lifecycle_launcher_module(); calls = []
        def forbidden(*args, **kwargs):
            calls.append(True); raise AssertionError('invalid original cutoff cannot wait or inspect')
        monkeypatch.setattr(process,'wait',forbidden)
        monkeypatch.setattr(module,'_no_child_native_closed_profile_v6',forbidden)
        monkeypatch.setattr(module,'inspect_owned_validation_no_child_native_closed_v6',forbidden)
        now = time.monotonic(); parent_end = now+1
        cutoff = {'bool':True,'nan':float('nan'),'infinite':float('inf'),'expired':now-1,
            'over420':now+421,'expired-parent':parent_end+1}[boundary]
        scope = native.resource_cleanup_deadline(native_deadline_monotonic=parent_end) if boundary == 'expired-parent' else nullcontext()
        if boundary == 'expired-parent':
            class ExpiredClock:
                @staticmethod
                def monotonic():return parent_end+.01
            monkeypatch.setattr(module,'time',ExpiredClock)
        elif boundary == 'over420':
            class FrozenCallerClock:
                @staticmethod
                def monotonic():return now
            monkeypatch.setattr(module,'time',FrozenCallerClock)
        with scope:
            assert module.wait_and_inspect_owned_validation_no_child_native_closed_v6(process,{},b'',
                expected_request_sha256='0'*64,owner_birth='1',expected_resource_ledger='/not-opened',
                original_wait_deadline_monotonic=cutoff) == dict(verdict='requires_original_native_cleanup',
                    source_custody_closed=False,storage_release_authorized=False)
        assert calls == [] and native.resource_operation_deadline() is None
    finally:
        subprocess.Popen.wait(process,timeout=5)


def test_startup_clock_v6_waiter_refuses_fabricated_process_before_inspection(monkeypatch):
    module, _ = _lifecycle_launcher_module(); calls = []
    def forbidden(*args, **kwargs):
        calls.append(True); raise AssertionError('fabricated waiter cannot inspect')
    monkeypatch.setattr(module,'_no_child_native_closed_profile_v6',forbidden)
    monkeypatch.setattr(module,'inspect_owned_validation_no_child_native_closed_v6',forbidden)
    assert module.wait_and_inspect_owned_validation_no_child_native_closed_v6(
        {'pid':1,'returncode':1,'genuine_wait_completed':True},{},b'',expected_request_sha256='0'*64,
        owner_birth='1',expected_resource_ledger='/not-opened',original_wait_deadline_monotonic=time.monotonic()+1
    ) == dict(verdict='requires_original_native_cleanup',source_custody_closed=False,storage_release_authorized=False)
    assert calls == []


def test_startup_clock_v6_waiter_does_not_promote_late_positive_sentinel(private_control, monkeypatch):
    process = subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(.05);raise SystemExit(1)'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        module, terminal, raw, value, caller = _startup_clock_v6_fictional_wait_control(private_control, process)
        cutoff = time.monotonic()+2; calls = []
        class CallerClock:
            now = time.monotonic()
            @staticmethod
            def monotonic():return CallerClock.now
        def profile(*args, **kwargs):
            assert args == (terminal,raw) and process.returncode == 1
            return value,None,None,None,None
        def late(*args, **kwargs):
            calls.append(native.resource_operation_deadline()); CallerClock.now = cutoff+.01
            # Synthetic positive is a boundary challenge, never evidence.
            return dict(verdict='proven_original_no_child_native_closed',source_custody_closed=True,
                storage_release_authorized=False)
        monkeypatch.setattr(module,'time',CallerClock)
        monkeypatch.setattr(module,'_no_child_native_closed_profile_v6',profile)
        monkeypatch.setattr(module,'inspect_owned_validation_no_child_native_closed_v6',late)
        assert module.wait_and_inspect_owned_validation_no_child_native_closed_v6(process,terminal,raw,
            **caller,original_wait_deadline_monotonic=cutoff) == dict(verdict='requires_original_native_cleanup',
                source_custody_closed=False,storage_release_authorized=False)
        assert len(calls) == 1 and calls[0].cleanup_only and calls[0].native_deadline_monotonic == cutoff
        assert native.resource_operation_deadline() is None
    finally:
        subprocess.Popen.wait(process,timeout=5)



def test_startup_clock_v6_shared_acquired_phase_rejects_typed_owner_aliases(private_control, monkeypatch):
    """Validate phase DATA from a real private grant, without asserting closure."""
    control = private_control
    _, _, value, kwargs = _startup_clock_v6_prepare(control)
    _validation_admission_clock(monkeypatch)
    module, _ = _lifecycle_launcher_module()
    with _owner(control, kwargs) as owned:
        reservation = owned.to_dict()
        assert reservation['resource_lease'] is not None and reservation['record']['child'] is None
        assert reservation['startup_clock_profile']['productive_started_monotonic'] is None
        def require(condition):
            if not condition:raise ValueError('typed acquired phase DATA differs')
        def forbidden(*args, **kwargs):
            pytest.fail('phase DATA validation cannot inspect or authorize Native/Source closure')
        with monkeypatch.context() as phase:
            phase.setattr(module,'_inspect_owned_validation_no_child_native_closed',forbidden)
            phase.setattr(existing,'open_existing_scheduler',forbidden)
            observed = module._startup_clock_no_child_observation(value, reservation, owned.request_sha256, require)
            assert observed['original_owner']['pid'] == os.getpid()
            assert observed['source_or_storage_release_authorized'] is False
            for fault in ('pid-float','pid-bool','birth-int'):
                changed = deepcopy(reservation)
                identity = changed['startup_clock_profile']['original_owner']
                if fault == 'pid-float':identity['pid'] = float(identity['pid'])
                elif fault == 'pid-bool':identity['pid'] = True
                else:identity['birth'] = int(identity['birth'])
                with pytest.raises(ValueError, match='typed acquired phase'):
                    module._startup_clock_no_child_observation(value, changed, owned.request_sha256, require)
        assert owned._started is None and owned._admission_started == 100.0


# Separate private zombie-liveness regression; staged only, no qualification yet.
def test_startup_clock_v6_unreaped_attached_zombie_cannot_publish_work(private_control, monkeypatch):
    control = private_control
    attempt, manifest, request, kwargs = _startup_clock_v6_prepare(control)
    _validation_admission_clock(monkeypatch)
    owned = _owner(control, kwargs).open()
    process = None
    identity = None
    attached = None
    try:
        process = _startup_clock_v6_pending_child(owned, request)
        identity = native_disk._process(process.pid)
        assert identity is not None and identity['state'] != 'Z'
        assert identity['parent_pid'] == os.getpid() and identity['group_pid'] == process.pid
        owned.attach_child(process.pid)
        attached = {'pid': process.pid, 'birth': identity['birth']}
        assert owned._child == owned._record['child'] == attached
        assert owned._startup_attachment_ready is True and owned._started is None
        assert process.returncode is None and not (attempt/'exports'/'checked.json').exists()
        # This is the actual test-owned direct child. Keep it unreaped so its
        # original PID/birth/parent/group still exist, but it cannot do work.
        os.kill(process.pid, signal.SIGTERM)
        def unreaped_zombie():
            current = native_disk._process(process.pid)
            return current if current is not None and current['state'] == 'Z' else None
        zombie = _wait_for(unreaped_zombie, 'owned barrier child did not become an unreaped zombie')
        assert zombie['birth'] == identity['birth']
        assert zombie['parent_pid'] == os.getpid() and zombie['group_pid'] == process.pid
        assert process.returncode is None  # Attribute only: no poll/wait/reap.
        with pytest.raises(validation.ValidationResourceError, match='original child identity or tracker differs'):
            owned.start_productive_work(process.pid, identity['birth'])
        assert owned._started is None and owned._admission_started == 100.0
        assert owned._child == owned._record['child'] == attached
        phase = owned.startup_clock_observation()
        assert phase['attached_child'] == attached and phase['productive_started_monotonic'] is None
        assert phase['source_or_storage_release_authorized'] is False
        assert not (attempt/'exports'/'checked.json').exists() and not (attempt/'logs'/'result.json').exists()
    finally:
        try:
            if process is not None:
                try:
                    current = native_disk._process(process.pid)
                    if current is not None and current['state'] != 'Z':
                        assert identity is None or current['birth'] == identity['birth']
                        os.kill(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)  # Reap only this actual owned child.
                finally:
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if stream is not None:
                            stream.close()
        finally:
            owned.__exit__(None, None, None)
    row = _json(control['ledger'])['reservations'][owned.reservation_id]
    assert row['status'] == 'retained' and row['child'] == attached
    assert row['storage_bytes'] == kwargs['storage_bytes']
    assert _json(control['scheduler'].state_path)['leases'] == {}



# Cancelled RETAINED cleanup is a separate closed profile. The fixture below is
# authored binding DATA, not a genuine original process, grant or Source proof.
# These controls inspect real private files/current process and scheduler state;
# they never turn missing worker output into a claim that no calls started.
def _cancelled_retained_binding_fixture(control):
    module, terminal, raw, caller, attempt = _productive_failed_retention_binding_fixture(control)
    request = json.loads(raw)
    request.update(cpu_slots=1, memory_mb=1536, child_process_slots=4,
        storage_bytes=16777216, timeout_seconds=300)
    manifest = control['root'].parent / (attempt.name + '-request.json')
    assert manifest.read_bytes() == raw
    _write_json(manifest, request)
    raw, request_sha = manifest.read_bytes(), _sha(manifest)
    reservation, failure, witness = (terminal[name] for name in
        ('reservation', 'failure', 'source_custody_lifecycle'))
    row, lease = reservation['record'], reservation['resource_lease']
    row.update(status='retained', retention_reason='context_failed',
        validation_request_sha256=request_sha)
    for key in ('cpu_slots', 'memory_mb', 'child_process_slots', 'storage_bytes'):
        row[key] = request[key]
        witness['budgets'][key] = request[key]
        if key != 'storage_bytes': lease[key] = request[key]
    reservation.update(status='retained', cleanup_error=None)
    reservation.pop('cleanup_failure_observations')
    reservation.pop('cleanup_failure_observation_overflow')
    reservation['ordinary_scratch_profile']['request_sha256'] = request_sha
    failure.update(request_sha256=request_sha, executed_checks=[], returncode=None,
        error_type='RuntimeError', error='validation cancelled: []', received_signals=[15])
    witness.update(request_sha256=request_sha,
        storage=dict(status='retained', cleanup_error=None, release_authorized=False))
    terminal['request_sha256'] = request_sha
    caller['expected_request_sha256'] = request_sha
    ledger = _json(control['ledger'])
    ledger['reservations'][row['reservation_id']] = deepcopy(row)
    _write_json(control['ledger'], ledger)
    return module, terminal, raw, caller, attempt


def _assert_cancelled_retained_unknown_without_write(module, terminal, raw, caller, control, cutoff,
        *, cleanup_profile='cancelled_retained_v5'):
    before = control['ledger'].read_bytes(), control['scheduler'].state_path.read_bytes()
    functions = _productive_inspected_functions(module) + (
        module._attached_native_closed_profile_v1,
        module._cancelled_retained_native_closed_profile_v5)
    actual = module.inspect_owned_validation_productive_native_closed_v1(terminal, raw, **caller,
        original_wait_deadline_monotonic=cutoff, cleanup_profile=cleanup_profile)
    assert actual == dict(verdict='requires_original_native_cleanup',
        source_custody_closed=False, storage_release_authorized=False)
    assert before == (control['ledger'].read_bytes(), control['scheduler'].state_path.read_bytes())
    assert functions == _productive_inspected_functions(module) + (
        module._attached_native_closed_profile_v1,
        module._cancelled_retained_native_closed_profile_v5)
    return actual


@pytest.mark.parametrize('worker_output', ['absent', 'partial-unsealed', 'unaccepted-sealed'])
def test_cancelled_retained_v5_cleanup_reads_current_state_without_worker_authority(
        private_control, worker_output):
    module, terminal, raw, caller, attempt = _cancelled_retained_binding_fixture(private_control)
    report = attempt / 'exports/trusted-validation.json'
    if worker_output != 'absent':
        report.parent.mkdir(parents=True)
        report.write_bytes(b'{partial' if worker_output == 'partial-unsealed' else b'{"passed":true}\n')
        report.chmod(0o600 if worker_output == 'partial-unsealed' else 0o400)
    old_report = report.read_bytes() if report.exists() else None
    frames = deepcopy(terminal), bytes(raw), dict(caller)
    before = private_control['ledger'].read_bytes(), private_control['scheduler'].state_path.read_bytes()
    value, witness, reservation, row, lease = module._cancelled_retained_native_closed_profile_v5(
        terminal, raw, **caller)
    assert row is terminal['reservation']['record'] and row['status'] == 'retained'
    assert row['retention_reason'] == 'context_failed' and row['artifacts_durable_asserted'] is False
    assert value['timeout_seconds'] == 300 and lease['released'] is True
    cutoff = time.monotonic() + 3
    assert module.inspect_owned_validation_productive_native_closed_v1(terminal, raw, **caller,
        original_wait_deadline_monotonic=cutoff, cleanup_profile='cancelled_retained_v5') == dict(
            verdict='proven_original_cancelled_retained_native_closed',
            source_custody_closed=True, storage_release_authorized=False)
    assert (terminal, raw, caller) == frames
    assert before == (private_control['ledger'].read_bytes(), private_control['scheduler'].state_path.read_bytes())
    assert (report.read_bytes() if report.exists() else None) == old_report
    assert not (attempt / 'logs/validation-durability.json').exists()
    # This is a cleanup verdict only, not source-only receipt/test acceptance.
    assert terminal['failure']['executed_checks'] == [] and terminal['completed'] is False


def test_cancelled_retained_v5_profile_does_not_replace_the_default_active_contract(private_control):
    module, terminal, raw, caller, _ = _cancelled_retained_binding_fixture(private_control)
    with pytest.raises((ValueError, KeyError)):
        module._productive_native_closed_profile_v1(terminal, raw, **caller)
    _assert_cancelled_retained_unknown_without_write(module, terminal, raw, caller,
        private_control, time.monotonic() + 3, cleanup_profile=None)
    active = _productive_failed_retention_binding_fixture(private_control)
    module, terminal, raw, caller, _ = active
    assert module.inspect_owned_validation_productive_native_closed_v1(terminal, raw, **caller,
        original_wait_deadline_monotonic=time.monotonic() + 3, cleanup_profile=None) == dict(
            verdict='proven_original_productive_native_closed_storage_separate',
            source_custody_closed=True, storage_release_authorized=False)
    _assert_cancelled_retained_unknown_without_write(module, terminal, raw, caller,
        private_control, time.monotonic() + 3)


@pytest.mark.parametrize('fault', ['reported-checks', 'child-returncode', 'signal-absent', 'signal-other',
    'signal-float', 'error-text', 'error-type', 'completed', 'model-download', 'nonfinite-elapsed',
    'boolean-elapsed', 'active-row', 'retention-reason', 'durability', 'cleanup-error', 'cleanup-diagnostics',
    'external-charge', 'storage-authority', 'wrong-lease', 'lease-not-cancelled', 'lease-not-released',
    'owner-birth', 'child-birth', 'identity-cycle', 'boolean-live-count', 'boolean-event', 'wrong-producer'])
def test_cancelled_retained_v5_binding_refuses_incomplete_or_foreign_terminal(private_control, fault):
    module, terminal, raw, caller, _ = _cancelled_retained_binding_fixture(private_control)
    reservation, failure, witness = (terminal[name] for name in
        ('reservation', 'failure', 'source_custody_lifecycle'))
    row = reservation['record']
    if fault == 'reported-checks': failure['executed_checks'] = ['unproved completion']
    elif fault == 'child-returncode': failure['returncode'] = 1
    elif fault == 'signal-absent': failure['received_signals'] = []
    elif fault == 'signal-other': failure['received_signals'] = [2]
    elif fault == 'signal-float': failure['received_signals'] = [15.0]
    elif fault == 'error-text': failure['error'] = 'another cancellation'
    elif fault == 'error-type': failure['error_type'] = 'TimeoutError'
    elif fault == 'completed': terminal['completed'] = True
    elif fault == 'model-download': failure['model_weights_downloaded'] = True
    elif fault == 'nonfinite-elapsed': failure['elapsed_seconds'] = float('nan')
    elif fault == 'boolean-elapsed': failure['elapsed_seconds'] = False
    elif fault == 'active-row': row['status'] = reservation['status'] = 'active'
    elif fault == 'retention-reason': row['retention_reason'] = 'different claim'
    elif fault == 'durability': row['artifacts_durable_asserted'] = True
    elif fault == 'cleanup-error': reservation['cleanup_error'] = 'unknown'
    elif fault == 'cleanup-diagnostics': reservation['cleanup_failure_observations'] = []
    elif fault == 'external-charge': row['external_charges'] = {'foreign': 1}
    elif fault == 'storage-authority': witness['storage']['release_authorized'] = True
    elif fault == 'wrong-lease': reservation['resource_lease']['lease_id'] = 'c' * 32
    elif fault == 'lease-not-cancelled': reservation['resource_lease']['cancelled'] = False
    elif fault == 'lease-not-released': reservation['resource_lease']['released'] = False
    elif fault == 'owner-birth': witness['owner']['birth'] = 'other'
    elif fault == 'child-birth': row['child']['birth'] = 'other'
    elif fault == 'identity-cycle': reservation['process_observation']['observed_identities'][0]['parent_pid'] = row['child']['pid']
    elif fault == 'boolean-live-count': reservation['process_observation']['live_processes'] = False
    elif fault == 'boolean-event': witness['events']['barrier_released'] = 1
    else: witness['producer']['sha256'] = 'c' * 64
    before = private_control['ledger'].read_bytes(), private_control['scheduler'].state_path.read_bytes()
    with pytest.raises((ValueError, KeyError)):
        module._cancelled_retained_native_closed_profile_v5(terminal, raw, **caller)
    assert before == (private_control['ledger'].read_bytes(), private_control['scheduler'].state_path.read_bytes())


@pytest.mark.parametrize('field,bad', [('cpu_slots', True), ('memory_mb', 2048),
    ('child_process_slots', 3), ('storage_bytes', 32 * 1024**2), ('timeout_seconds', 301)])
def test_cancelled_retained_v5_request_budget_cannot_borrow_another_profile(private_control, field, bad):
    module, terminal, raw, caller, _ = _cancelled_retained_binding_fixture(private_control)
    request = json.loads(raw); request[field] = bad
    changed = (json.dumps(request, sort_keys=True, separators=(',', ':')) + '\n').encode()
    caller['expected_request_sha256'] = hashlib.sha256(changed).hexdigest()
    with pytest.raises((ValueError, KeyError)):
        module._cancelled_retained_native_closed_profile_v5(terminal, changed, **caller)


@pytest.mark.parametrize('profile', [True, False, 0, '', 'cancelled_retained_v4', []])
def test_cancelled_retained_v5_profile_is_an_explicit_closed_keyword(private_control, profile):
    module, terminal, raw, caller, _ = _cancelled_retained_binding_fixture(private_control)
    _assert_cancelled_retained_unknown_without_write(module, terminal, raw, caller,
        private_control, time.monotonic() + 3, cleanup_profile=profile)


@pytest.mark.parametrize('fault', ['source-drift', 'own-row-drift', 'native-root', 'native-waiter',
    'native-descendant', 'attempt-inode', 'current-policy'])
def test_cancelled_retained_v5_current_absence_and_exact_row_are_not_terminal_flags(private_control, fault):
    module, terminal, raw, caller, attempt = _cancelled_retained_binding_fixture(private_control)
    row = terminal['reservation']['record']; rid, lid = row['reservation_id'], row['native_lease_id']
    state_path = private_control['scheduler'].state_path
    original_private_state = state_path.read_bytes()
    if fault == 'source-drift': private_control['source'].write_text('changed pinned source')
    elif fault == 'own-row-drift':
        state = _json(private_control['ledger']); state['reservations'][rid]['storage_bytes'] += 1
        _write_json(private_control['ledger'], state)
    elif fault in ('native-root', 'native-waiter', 'native-descendant'):
        state = _json(state_path)
        if fault == 'native-root': state['leases'][lid] = {'lease_id': lid, 'request_id': 'validation:' + rid}
        elif fault == 'native-waiter': state['waiters']['c' * 32] = {'request_id': 'validation:' + rid}
        else: state['leases']['c' * 32] = {'parent_lease_id': lid}
        _write_json(state_path, state)
    elif fault == 'attempt-inode':
        attempt.rename(attempt.with_name(attempt.name + '-retained-original'))
        attempt.mkdir(mode=0o700)
    else:
        state = _json(state_path); state['config']['total_cpu_slots'] += 1
        _write_json(state_path, state)
    try:
        _assert_cancelled_retained_unknown_without_write(module, terminal, raw, caller,
            private_control, time.monotonic() + 3)
    finally:
        if fault in ('native-root', 'native-waiter', 'native-descendant'):
            state = _json(state_path); state['leases'].clear(); state['waiters'].clear()
            _write_json(state_path, state)
        elif fault == 'current-policy':
            state_path.write_bytes(original_private_state)


@pytest.mark.parametrize('boundary', ['ledger-read', 'native-lease-inspection'])
def test_cancelled_retained_v5_checks_expiry_inside_same_original_cutoff(private_control, monkeypatch, boundary):
    module, terminal, raw, caller, _ = _cancelled_retained_binding_fixture(private_control)
    state_path = private_control['scheduler'].state_path
    target = private_control['ledger'] if boundary == 'ledger-read' else state_path.with_name(state_path.name + '.lock')
    actual_open, actual_clock = os.open, time.monotonic
    cutoff = actual_clock() + 3; reached, expired = [], []
    def observed_open(path, flags, *args, **kwargs):
        descriptor = actual_open(path, flags, *args, **kwargs)
        if os.fspath(path) == str(target):
            reached.append(str(path))
            if boundary == 'ledger-read' or len(reached) == 2: expired.append(True)
        return descriptor
    with monkeypatch.context() as patch:
        patch.setattr(os, 'open', observed_open)
        patch.setattr(time, 'monotonic', lambda: cutoff + 1 if expired else actual_clock())
        _assert_cancelled_retained_unknown_without_write(module, terminal, raw, caller, private_control, cutoff)
    assert expired == [True]
    assert len(reached) == (1 if boundary == 'ledger-read' else 2)


@pytest.mark.parametrize('remaining', [-1, 361, float('inf')])
def test_cancelled_retained_v5_never_renews_an_invalid_original_deadline(private_control, remaining):
    module, terminal, raw, caller, _ = _cancelled_retained_binding_fixture(private_control)
    _assert_cancelled_retained_unknown_without_write(module, terminal, raw, caller,
        private_control, time.monotonic() + remaining)


# Completed command failures are distinct authored RETAINED fixture DATA. No
# historical terminal is rewritten and no worker-report/test credit is inferred.
def _failed_retained_binding_fixture(control, worker_returncode=7):
    module, terminal, raw, caller, attempt = _cancelled_retained_binding_fixture(control)
    terminal['failure'].update(executed_checks=deepcopy(json.loads(raw)['selected_checks']),
        returncode=worker_returncode, error_type='RuntimeError',
        error='validation command failed with returncode '+str(worker_returncode), received_signals=[])
    return module, terminal, raw, caller, attempt


def _assert_failed_retained_unknown_without_write(module, terminal, raw, caller, control, cutoff):
    helper = module._failed_retained_native_closed_profile_v5
    _assert_cancelled_retained_unknown_without_write(module, terminal, raw, caller, control, cutoff,
        cleanup_profile='failed_retained_v5')
    assert module._failed_retained_native_closed_profile_v5 is helper


@pytest.mark.parametrize('worker_output', ['absent', 'partial-unsealed', 'unaccepted-sealed'])
@pytest.mark.parametrize('worker_returncode', [1, 7, -9])
def test_failed_retained_v5_current_closure_is_not_worker_qualification(private_control, worker_output, worker_returncode):
    module, terminal, raw, caller, attempt = _failed_retained_binding_fixture(private_control, worker_returncode)
    report = attempt / 'exports/trusted-validation.json'
    if worker_output != 'absent':
        report.parent.mkdir(parents=True)
        report.write_bytes(b'{partial' if worker_output == 'partial-unsealed' else b'{"passed":true}\n')
        report.chmod(0o600 if worker_output == 'partial-unsealed' else 0o400)
    saved_report = report.read_bytes() if report.exists() else None
    frames = deepcopy(terminal), bytes(raw), dict(caller)
    before = private_control['ledger'].read_bytes(), private_control['scheduler'].state_path.read_bytes()
    _, _, reservation, row, lease = module._failed_retained_native_closed_profile_v5(terminal, raw, **caller)
    assert row is terminal['reservation']['record'] and reservation['status'] == row['status'] == 'retained'
    assert row['retention_reason'] == 'context_failed' and row['artifacts_durable_asserted'] is False
    assert lease['released'] is True and lease['cancelled'] is True
    assert module.inspect_owned_validation_productive_native_closed_v1(terminal, raw, **caller,
        original_wait_deadline_monotonic=time.monotonic()+3, cleanup_profile='failed_retained_v5') == dict(
            verdict='proven_original_failed_retained_native_closed', source_custody_closed=True,
            storage_release_authorized=False)
    assert (terminal, raw, caller) == frames
    assert before == (private_control['ledger'].read_bytes(), private_control['scheduler'].state_path.read_bytes())
    assert (report.read_bytes() if report.exists() else None) == saved_report
    assert not (attempt / 'logs/validation-durability.json').exists()
    assert terminal['failure']['executed_checks'] == json.loads(raw)['selected_checks']
    # Reported command selectors establish no actual collected/executed case count.


def test_failed_retained_v5_does_not_project_to_cancelled_or_ACTIVE(private_control):
    module, terminal, raw, caller, _ = _failed_retained_binding_fixture(private_control)
    for helper in (module._productive_native_closed_profile_v1, module._cancelled_retained_native_closed_profile_v5):
        with pytest.raises((ValueError, KeyError)):
            helper(terminal, raw, **caller)
    for profile in (None, 'cancelled_retained_v5'):
        _assert_cancelled_retained_unknown_without_write(module, terminal, raw, caller, private_control,
            time.monotonic()+3, cleanup_profile=profile)
    module, terminal, raw, caller, _ = _cancelled_retained_binding_fixture(private_control)
    _assert_failed_retained_unknown_without_write(module, terminal, raw, caller, private_control, time.monotonic()+3)
    module, terminal, raw, caller, _ = _productive_failed_retention_binding_fixture(private_control)
    _assert_failed_retained_unknown_without_write(module, terminal, raw, caller, private_control, time.monotonic()+3)


@pytest.mark.parametrize('fault', ['reported-empty', 'reported-foreign', 'worker-zero', 'worker-none',
    'worker-bool', 'worker-float', 'error-text', 'error-type', 'signals', 'completed', 'durability',
    'retention-reason', 'cleanup-error', 'cleanup-diagnostics', 'lease-unreleased', 'lease-not-cancelled',
    'lease-wrong-id', 'owner-birth', 'child-birth', 'identity-cycle', 'event-boolean', 'native-live-count',
    'authority', 'elapsed-bool', 'elapsed-nonfinite'])
def test_failed_retained_v5_binding_refuses_incomplete_or_foreign_failure(private_control, fault):
    module, terminal, raw, caller, _ = _failed_retained_binding_fixture(private_control)
    r, f, w = (terminal[key] for key in ('reservation', 'failure', 'source_custody_lifecycle'))
    if fault == 'reported-empty': f['executed_checks'] = []
    elif fault == 'reported-foreign': f['executed_checks'] = ['foreign selector']
    elif fault == 'worker-zero': f['returncode'] = 0
    elif fault == 'worker-none': f['returncode'] = None
    elif fault == 'worker-bool': f['returncode'] = True
    elif fault == 'worker-float': f['returncode'] = 7.0
    elif fault == 'error-text': f['error'] = 'another failure'
    elif fault == 'error-type': f['error_type'] = 'TimeoutError'
    elif fault == 'signals': f['received_signals'] = [15]
    elif fault == 'completed': terminal['completed'] = True
    elif fault == 'durability': r['record']['artifacts_durable_asserted'] = True
    elif fault == 'retention-reason': r['record']['retention_reason'] = 'another claim'
    elif fault == 'cleanup-error': r['cleanup_error'] = 'unknown'
    elif fault == 'cleanup-diagnostics': r['cleanup_failure_observations'] = []
    elif fault == 'lease-unreleased': r['resource_lease']['released'] = False
    elif fault == 'lease-not-cancelled': r['resource_lease']['cancelled'] = False
    elif fault == 'lease-wrong-id': r['resource_lease']['lease_id'] = 'c'*32
    elif fault == 'owner-birth': w['owner']['birth'] = 'other'
    elif fault == 'child-birth': r['record']['child']['birth'] = 'other'
    elif fault == 'identity-cycle': r['process_observation']['observed_identities'][0]['parent_pid'] = r['record']['child']['pid']
    elif fault == 'event-boolean': w['events']['barrier_released'] = 1
    elif fault == 'native-live-count': r['process_observation']['live_processes'] = False
    elif fault == 'authority': f['authority_granted'] = True
    elif fault == 'elapsed-bool': f['elapsed_seconds'] = False
    else: f['elapsed_seconds'] = float('inf')
    with pytest.raises((ValueError, KeyError)):
        module._failed_retained_native_closed_profile_v5(terminal, raw, **caller)


@pytest.mark.parametrize('field,bad', [('cpu_slots', True), ('memory_mb', 2048),
    ('child_process_slots', 3), ('storage_bytes', 33554432), ('timeout_seconds', 301)])
def test_failed_retained_v5_cannot_borrow_different_resource_profile(private_control, field, bad):
    module, terminal, raw, caller, _ = _failed_retained_binding_fixture(private_control)
    request = json.loads(raw); request[field] = bad
    changed = (json.dumps(request, sort_keys=True, separators=(',', ':'))+'\n').encode()
    caller['expected_request_sha256'] = hashlib.sha256(changed).hexdigest()
    with pytest.raises((ValueError, KeyError)):
        module._failed_retained_native_closed_profile_v5(terminal, changed, **caller)


@pytest.mark.parametrize('fault', ['source-drift', 'own-row-drift', 'native-root', 'native-waiter',
    'native-descendant', 'attempt-inode', 'current-policy'])
def test_failed_retained_v5_rechecks_current_closure_instead_of_terminal_flags(private_control, fault):
    module, terminal, raw, caller, attempt = _failed_retained_binding_fixture(private_control)
    row = terminal['reservation']['record']; rid, lid = row['reservation_id'], row['native_lease_id']
    path = private_control['scheduler'].state_path
    original_native_bytes = path.read_bytes()
    if fault == 'source-drift': private_control['source'].write_text('changed pinned source')
    elif fault == 'own-row-drift':
        state = _json(private_control['ledger']); state['reservations'][rid]['storage_bytes'] += 1
        _write_json(private_control['ledger'], state)
    elif fault in ('native-root', 'native-waiter', 'native-descendant'):
        state = _json(path)
        if fault == 'native-root': state['leases'][lid] = {'lease_id': lid, 'request_id': 'validation:'+rid}
        elif fault == 'native-waiter': state['waiters']['c'*32] = {'request_id': 'validation:'+rid}
        else: state['leases']['c'*32] = {'parent_lease_id': lid}
        _write_json(path, state)
    elif fault == 'attempt-inode':
        attempt.rename(attempt.with_name(attempt.name+'-retained-original')); attempt.mkdir(mode=0o700)
    else:
        state = _json(path); state['config']['total_cpu_slots'] += 1; _write_json(path, state)
    try:
        _assert_failed_retained_unknown_without_write(module, terminal, raw, caller, private_control, time.monotonic()+3)
    finally:
        if fault in ('native-root', 'native-waiter', 'native-descendant', 'current-policy'):
            path.write_bytes(original_native_bytes)


@pytest.mark.parametrize('boundary', ['ledger-read', 'native-lease-inspection'])
def test_failed_retained_v5_expires_inside_the_original_absolute_cutoff(private_control, monkeypatch, boundary):
    module, terminal, raw, caller, _ = _failed_retained_binding_fixture(private_control)
    state_path = private_control['scheduler'].state_path
    target = private_control['ledger'] if boundary == 'ledger-read' else state_path.with_name(state_path.name+'.lock')
    actual_open, actual_clock = os.open, time.monotonic
    cutoff = actual_clock()+3; reached, expired = [], []
    def observed_open(path, flags, *args, **kwargs):
        descriptor = actual_open(path, flags, *args, **kwargs)
        if os.fspath(path) == str(target):
            reached.append(str(path))
            if boundary == 'ledger-read' or len(reached) == 2: expired.append(True)
        return descriptor
    with monkeypatch.context() as patch:
        patch.setattr(os, 'open', observed_open)
        patch.setattr(time, 'monotonic', lambda: cutoff+1 if expired else actual_clock())
        _assert_failed_retained_unknown_without_write(module, terminal, raw, caller, private_control, cutoff)
    assert expired == [True] and len(reached) == (1 if boundary == 'ledger-read' else 2)


@pytest.mark.parametrize('remaining', [-1, 361, float('inf')])
def test_failed_retained_v5_never_renews_or_borrows_a_deadline(private_control, remaining):
    module, terminal, raw, caller, _ = _failed_retained_binding_fixture(private_control)
    _assert_failed_retained_unknown_without_write(module, terminal, raw, caller, private_control,
        time.monotonic()+remaining)


# Fictional SDK-open producer DATA only. The actual failed v5 job and its
# abnormal keeper closeout remain historical UNKNOWN, with storage retained.
# These controls create no genuine Popen/Source/Native or cleanup authority.
def _closed_pre_child_v5_postgrant_ledger_lock_fixture(control):
    module, terminal, raw, caller, attempt = _closed_pre_child_v5_deadline_fixture(control)
    # Establish that the inherited original v5 deadline fixture is valid
    # BEFORE changing the exact failure pair to the unimplemented lock profile.
    module._no_child_native_closed_profile_v5(terminal, raw, **caller)
    assert module.inspect_owned_validation_no_child_native_closed_v5(terminal, raw, **caller) == dict(
        verdict='proven_original_no_child_native_closed', source_custody_closed=True,
        storage_release_authorized=False)
    terminal['failure'].update(error_type='DaemonResourceError',
        error='disk ledger lock unavailable', elapsed_seconds=1.0)
    return module, terminal, raw, caller, attempt


def test_pre_child_v5_postgrant_ledger_lock_current_inspection_is_read_only(private_control, monkeypatch):
    module, terminal, raw, caller, attempt = _closed_pre_child_v5_postgrant_ledger_lock_fixture(private_control)
    request = json.loads(raw)
    assert request['schema'] == 'owned-validation-request/v5'
    assert hashlib.sha256(raw).hexdigest() == caller['expected_request_sha256']
    assert all(record['request_sha256'] == caller['expected_request_sha256'] for record in (
        terminal, terminal['failure'], terminal['source_custody_lifecycle'],
        terminal['reservation']['ordinary_scratch_profile']))
    row = terminal['reservation']['record']
    assert len(row) == 17 and 'owner_birth' not in row and 'validation_request_sha256' not in row
    assert row['status'] == 'retained' and row['retention_reason'] == 'context_failed'
    assert row['child'] is None and row['prior_children'] == [] and row['artifacts_durable_asserted'] is False
    assert _json(private_control['ledger'])['reservations'][row['reservation_id']] == row
    assert 0 < terminal['failure']['elapsed_seconds'] < request['timeout_seconds']
    assert terminal['failure']['process_observation'] == terminal['reservation']['process_observation']
    assert terminal['failure']['process_observation']['observed_identities'] == []
    assert not any(terminal['source_custody_lifecycle']['events'][key] for key in (
        'owner_open_returned', 'child_launch_attempted', 'child_created',
        'barrier_release_attempted', 'barrier_released'))
    assert next(attempt.iterdir(), None) is None
    before = private_control['ledger'].read_bytes(), private_control['scheduler'].state_path.read_bytes()
    original = raw, deepcopy(terminal)
    def forbidden(*args, **kwargs):
        raise AssertionError('inspection cannot acquire, persist, inventory or release storage')
    monkeypatch.setattr(native.GlobalResourceScheduler, 'acquire', forbidden)
    monkeypatch.setattr(existing._PinnedGlobalResourceScheduler, '_persist_locked_state', forbidden)
    monkeypatch.setattr(native_disk.DaemonResourceReservation, '_write', forbidden)
    monkeypatch.setattr(native_disk.DaemonResourceReservation, '_account', forbidden)
    # Neither the general no-grant gate nor a v1 inspector can accept v5 DATA.
    assert module.classify_owned_validation_source_custody(terminal, raw, **caller) == _live_no_child_unknown()
    _assert_closed_pre_child_unknown(module, terminal, raw, caller)
    # Expected current RED: this existing v5 API returns UNKNOWN because the
    # acquired/no-child ledger-lock error pair is not an admitted v5 profile.
    assert module.inspect_owned_validation_no_child_native_closed_v5(terminal, raw, **caller) == dict(
        verdict='proven_original_no_child_native_closed', source_custody_closed=True,
        storage_release_authorized=False)
    assert (private_control['ledger'].read_bytes(), private_control['scheduler'].state_path.read_bytes()) == before
    assert (raw, terminal) == original and next(attempt.iterdir(), None) is None
    assert _json(private_control['ledger'])['reservations'][row['reservation_id']]['status'] == 'retained'


@pytest.mark.parametrize('boundary', ['zero', 'negative', 'equal-timeout', 'over-timeout', 'bool', 'nan', 'inf'])
def test_pre_child_v5_postgrant_ledger_lock_rejects_elapsed_boundaries(private_control, boundary):
    module, terminal, raw, caller, _ = _closed_pre_child_v5_postgrant_ledger_lock_fixture(private_control)
    timeout = json.loads(raw)['timeout_seconds']
    terminal['failure']['elapsed_seconds'] = {'zero': 0, 'negative': -1,
        'equal-timeout': timeout, 'over-timeout': timeout + 1, 'bool': True,
        'nan': float('nan'), 'inf': float('inf')}[boundary]
    _assert_closed_pre_child_v5_unknown(module, terminal, raw, caller)


@pytest.mark.parametrize('fault', ['wrong-error-type', 'wrong-error-text', 'scratch-request',
    'child-created', 'owner-open-returned', 'native-unreleased', 'native-uncancelled', 'producer-pin'])
def test_pre_child_v5_postgrant_ledger_lock_rejects_crossed_bindings(private_control, fault):
    module, terminal, raw, caller, _ = _closed_pre_child_v5_postgrant_ledger_lock_fixture(private_control)
    path, replacement = {
        'wrong-error-type': ('failure.error_type', 'ResourceAdmissionDeadlineError'),
        'wrong-error-text': ('failure.error', 'original absolute resource operation deadline expired'),
        'scratch-request': ('reservation.ordinary_scratch_profile.request_sha256', '0' * 64),
        'child-created': ('source_custody_lifecycle.events.child_created', True),
        'owner-open-returned': ('source_custody_lifecycle.events.owner_open_returned', True),
        'native-unreleased': ('reservation.resource_lease.released', False),
        'native-uncancelled': ('reservation.resource_lease.cancelled', False),
        'producer-pin': ('source_custody_lifecycle.producer.sha256', '0' * 64)}[fault]
    target = terminal
    fields = path.split('.')
    for key in fields[:-1]: target = target[key]
    target[fields[-1]] = replacement
    _assert_closed_pre_child_v5_unknown(module, terminal, raw, caller)


@pytest.mark.parametrize('fault', ['source_drift', 'row_drift', 'owner_present',
    'native_root', 'native_waiter', 'expired_deadline'])
def test_pre_child_v5_postgrant_ledger_lock_rechecks_current_custody(private_control, monkeypatch, fault):
    # Reuse the existing v1/v5 adversarial inspector harness. The inherited
    # original deadline-fixture alias prevents a recursive fixture substitution.
    with monkeypatch.context() as patch:
        patch.setitem(globals(), '_closed_pre_child_fixture', _closed_pre_child_v5_postgrant_ledger_lock_fixture)
        patch.setitem(globals(), '_assert_closed_pre_child_unknown', _assert_closed_pre_child_v5_unknown)
        test_pre_child_closed_native_inspection_rechecks_current_custody(private_control, patch, fault)

# Initial-entry refusal controls use the existing canonical CLI loader and the
# real public validation/host modules above. The constructor, locks/scheduler,
# source-pin marker and request-shape boundary are explicit unit fixtures;
# open/__enter__/_read/to_dict and the CLI producer/classifier remain real.
import ast as _pre_entry_ast
import contextlib as _pre_entry_contextlib
import types as _pre_entry_types
import unittest as _pre_entry_unittest

_pre_entry_fixture_meter = {'fixture_read_bytes': 0}


class _PreResourceEntryPublicFixture:
    def __init__(self, tmp_path, monkeypatch):
        self.root = tmp_path
        self.request_path = tmp_path / 'entry-request.json'
        self.ledger_path = tmp_path / 'entry-ledger.json'
        self.cli, self.cli_path = _lifecycle_launcher_module()
        self.cli_source = self.cli_path.read_bytes()
        self.project = self.cli.ROOT
        self.host, self.sdk = native_disk, validation
        self.guard_changed = False
        self.writes = self.native = 0
        self.mode = 'read_refusal'
        self.fixture_ledger = {'schema': native_disk.SCHEMA, 'roots': [],
            'limit_bytes': 280000000000, 'reservations': {}}
        _write_json(self.ledger_path, self.fixture_ledger)
        self.value = {'schema': 'owned-validation-request/v5',
            'source_sha256': {str(self.cli_path): hashlib.sha256(self.cli_source).hexdigest()},
            'ordinary_scratch_profile': {'schema': 'owned-validation-ordinary-scratch-live/v1'},
            'storage_bytes': 16777216, 'attempt_directory': str(tmp_path/'attempt'),
            'outputs': {}, 'cpu_slots': 1, 'memory_mb': 1536,
            'child_process_slots': 4, 'expected_scheduler_policy_sha256': 'f'*64,
            'process_scope': 'sampled_birth_bound_descendants'}
        self.raw = json.dumps(self.value, sort_keys=True).encode()
        self.pin = hashlib.sha256(self.raw).hexdigest()
        self.request_path.write_bytes(self.raw)
        self.modules = {'candidate': self.cli}
        self.events = {key: key == 'owner_open_attempted' for key in self.cli._PRE_GRANT_EVENTS}
        self.outcome = dict(schema='owned-validation-result/v1', request_sha256=self.pin,
            executed_checks=[], returncode=None, completed=False, admitted=False,
            Lean_admitted=False, authority_granted=False, model_weights_downloaded=False,
            watchdog_errors=[], received_signals=[])
        self._install_declared_boundaries(monkeypatch)

    def _install_declared_boundaries(self, monkeypatch):
        fx = self
        cls = validation.ValidationResourceReservation

        def fixture_constructor(owner):
            owner.ledger_path = fx.ledger_path
            owner.root_identities = []
            owner.storage_limit_bytes = 250000000000
            owner.storage_bytes = 16777216
            owner.memory_mb, owner.cpu_slots, owner.child_process_slots = 1536, 1, 4
            owner.reservation_id = 'fictional-initial-entry-owner'
            owner._owner_pid = os.getpid()
            owner._owner_identity = native_disk._process(os.getpid())
            owner._lease = owner._record = owner._child = owner._cleanup_error = None
            owner._entered = owner._opened = owner._opening = False
            owner._started = owner._admission_started = None
            owner._startup_original_profile = None
            owner._startup_open_attempted = False
            owner._scheduler_state_path = owner._attempt = None
            owner._last_process_observation = owner._physical_profile = None
            owner._live_inventory_profile = None
            owner._require_existing_ledger = True
            owner._ordinary_scratch_profile = {'schema': 'owned-validation-ordinary-scratch-live/v1'}
            owner._ordinary_scratch_absences = 0
            owner._live_inventory_active = False
            owner.request_sha256 = fx.pin
            owner._cleanup_failure_observations = []
            owner._cleanup_failure_observation_overflow = False

        @_pre_entry_contextlib.contextmanager
        def fixture_empty_scope(owner):
            yield

        def fixture_write(owner, ledger):
            fx.writes += 1
            if fx.mode == 'read_during_write':
                _write_json(fx.ledger_path, dict(ledger, limit_bytes=280000000000))
                owner._read()
            raise native_disk.DaemonResourceError('disk ledger storage scope differs')

        def fixture_acquire(owner, *args):
            fx.native += 1
            raise native_disk.DaemonResourceError('disk ledger storage scope differs')

        def fixture_source_guard(value):
            if fx.guard_changed or value['source_sha256'] != fx.value['source_sha256']:
                raise RuntimeError('fixture Source pin changed')

        monkeypatch.setattr(cls, '__init__', fixture_constructor)
        for name in ('_admission_scope', '_admission_cleanup_scope', '_locked'):
            monkeypatch.setattr(cls, name, fixture_empty_scope)
        monkeypatch.setattr(cls, '_guard_inputs', lambda owner: None)
        monkeypatch.setattr(cls, 'tracks_descendants', property(lambda owner: True))
        monkeypatch.setattr(cls, '_scheduler_identity', lambda owner: (
            _pre_entry_types.SimpleNamespace(value='validation'), 'canonical_validation'))
        monkeypatch.setattr(cls, '_validate_new_reservation', lambda owner, ledger: None)
        monkeypatch.setattr(cls, '_account', lambda owner, *args, **kwargs: {})
        monkeypatch.setattr(cls, '_retain', lambda owner, *args, **kwargs: None)
        monkeypatch.setattr(cls, '_write', fixture_write)
        monkeypatch.setattr(cls, '_acquire_native_lease', fixture_acquire)
        monkeypatch.setattr(native_disk.native_deadlines, '_check_resource_operation_deadline', lambda: None)
        monkeypatch.setattr(self.cli, '_lifecycle_source_guard', fixture_source_guard)
        monkeypatch.setattr(self.cli, '_ordinary_scratch_no_child_request_shape',
            lambda value, raw: json.loads(raw) == value and value['schema'] == 'owned-validation-request/v5')
        # No project package/module replacement or AST extraction is performed.
        # The canonical snapshot implementation reads the actual CLI/request.

    def close(self):
        pass  # tmp_path and monkeypatch retain their original pytest ownership.

    def fail_open(self):
        owner = self.sdk.ValidationResourceReservation()
        owner.request_sha256 = self.pin
        try:
            owner.open()
        except self.host.DaemonResourceError as error:
            return owner, error, dict(self.outcome, error_type=type(error).__name__, error=str(error))
        raise AssertionError('fixture must refuse')

    def produce(self, label=None, owner=None, error=None, outcome=None, events=None):
        function = getattr(self.cli, '_pre_resource_entry_refusal_terminal', None)
        if function is None:
            return None
        if owner is None:
            owner, error, outcome = self.fail_open()
        try:
            return function(owner, self.value, self.raw, self.request_path, self.pin,
                self.ledger_path, events or self.events, error, outcome)
        except BaseException:
            return None  # Same original main-finally primary-failure boundary.

    def reference(self):
        terminal = self.produce('candidate')
        assert type(terminal) is dict, 'candidate reference producer failed'
        return terminal

    def classify(self, terminal, **changes):
        arguments = dict(expected_request_sha256=self.pin, owner_pid=os.getpid(),
            owner_birth=native_disk._process(os.getpid())['birth'], returncode=1,
            expected_resource_ledger=str(self.ledger_path))
        arguments.update(changes)
        return self.cli.classify_owned_validation_source_custody(terminal, self.raw, **arguments)


@pytest.fixture
def _pre_resource_entry_public_case(request, tmp_path, monkeypatch):
    case = _PreResourceEntryPublicFixture(tmp_path, monkeypatch)
    request.instance._pre_resource_entry_fixture = case
    yield


@pytest.mark.usefixtures('_pre_resource_entry_public_case')
class TestCLIInitialReadRefusalControls(_pre_entry_unittest.TestCase):
    def setUp(self):self.fx=self._pre_resource_entry_fixture
    def tearDown(self):self.fx.close()
    def unknown(self,t,**kw):
        self.assertEqual(self.fx.classify(t,**kw),{'verdict':'requires_original_native_cleanup','source_custody_closed':False,'storage_release_authorized':False})
    def test_actual_scope_refusal_reports_constructed_owner(self):
        t=self.fx.produce();self.assertIsInstance(t,dict);self.assertIs(t['source_custody_lifecycle']['owner_state']['constructed'],True)
    def test_scope_mismatch_remains_refused_without_write_or_native(self):
        t=self.fx.produce();self.assertIsInstance(t,dict);self.assertEqual(self.fx.writes,0);self.assertEqual(self.fx.native,0)
        raw=self.fx.ledger_path.read_bytes();_pre_entry_fixture_meter['fixture_read_bytes']+=len(raw);self.assertEqual(json.loads(raw)['limit_bytes'],280000000000)
    def test_copied_message_without_live_frames_is_unknown(self):
        o=self.fx.sdk.ValidationResourceReservation();e=self.fx.host.DaemonResourceError('disk ledger storage scope differs')
        self.assertIsNone(self.fx.produce(owner=o,error=e,outcome=self.fx.outcome))
    def mutate_owner(self,key,value):
        o,e,out=self.fx.fail_open();setattr(o,key,value);self.assertIsNone(self.fx.produce(owner=o,error=e,outcome=out))
    def test_entered_owner_is_unknown(self):self.mutate_owner('_entered',True)
    def test_opened_owner_is_unknown(self):self.mutate_owner('_opened',True)
    def test_record_created_is_unknown(self):self.mutate_owner('_record',{})
    def test_native_lease_is_unknown(self):self.mutate_owner('_lease',object())
    def test_child_attached_is_unknown(self):self.mutate_owner('_child',{})
    def test_open_returned_event_is_unknown(self):
        o,e,out=self.fx.fail_open();events=dict(self.fx.events,owner_open_returned=True);self.assertIsNone(self.fx.produce(owner=o,error=e,outcome=out,events=events))
    def test_child_attempt_event_is_unknown(self):
        o,e,out=self.fx.fail_open();events=dict(self.fx.events,child_launch_attempted=True);self.assertIsNone(self.fx.produce(owner=o,error=e,outcome=out,events=events))
    def test_uncertain_write_is_unknown(self):
        good=dict(self.fx.fixture_ledger,limit_bytes=250000000000);self.fx.ledger_path.write_text(json.dumps(good));self.fx.mode='write_failure'
        o,e,out=self.fx.fail_open();self.assertGreater(self.fx.writes,0);self.assertIsNone(self.fx.produce(owner=o,error=e,outcome=out))
    def test_read_during_uncertain_write_cannot_reuse_initial_read(self):
        good=dict(self.fx.fixture_ledger,limit_bytes=250000000000);self.fx.ledger_path.write_text(json.dumps(good));self.fx.mode='read_during_write'
        o,e,out=self.fx.fail_open();self.assertGreater(self.fx.writes,0);self.assertIsNone(self.fx.produce(owner=o,error=e,outcome=out))
    def test_post_native_state_is_unknown(self):
        o,e,out=self.fx.fail_open();o._entered=True;o._lease=object();self.assertIsNone(self.fx.produce(owner=o,error=e,outcome=out))
    def test_changed_actual_owner_identity_is_unknown(self):
        o,e,out=self.fx.fail_open();o._owner_identity=dict(o._owner_identity,birth='0');self.assertIsNone(self.fx.produce(owner=o,error=e,outcome=out))
    def test_changed_Source_guard_is_unknown(self):
        o,e,out=self.fx.fail_open();self.fx.guard_changed=True;self.assertIsNone(self.fx.produce(owner=o,error=e,outcome=out))
    def test_consumer_recognizes_exact_live_V5_refusal(self):
        t=self.fx.reference();self.assertEqual(self.fx.classify(t),{'verdict':'proven_original_no_child_no_native_grant','source_custody_closed':True,'storage_release_authorized':False})
    def test_consumer_rejects_wrong_owner(self):
        self.unknown(self.fx.reference(),owner_pid=os.getpid()+1)
    def test_consumer_rejects_constructor_false_fiction(self):
        t=self.fx.reference();t['source_custody_lifecycle']['owner_state']['constructed']=False;self.unknown(t)
    def test_consumer_rejects_unverified_trace(self):
        t=self.fx.reference();t['source_custody_lifecycle']['entry_refusal_observation']['live_trace_verified']=False;self.unknown(t)
    def test_consumer_rejects_record(self):
        t=self.fx.reference();t['reservation']['record']={};self.unknown(t)
    def test_consumer_rejects_native_grant(self):
        t=self.fx.reference();t['reservation']['resource_lease']={};self.unknown(t)
    def test_consumer_rejects_child_attempt(self):
        t=self.fx.reference();t['source_custody_lifecycle']['events']['child_launch_attempted']=True;self.unknown(t)
    def test_consumer_rejects_storage_release(self):
        t=self.fx.reference();t['source_custody_lifecycle']['storage']['release_authorized']=True;self.unknown(t)
    def test_consumer_rejects_missing_Source_guard(self):
        t=self.fx.reference();t['source_custody_lifecycle']['source_guards']['source_pins_unchanged']=False;self.unknown(t)
    def test_consumer_rejects_wrong_producer_pin(self):
        t=self.fx.reference();t['source_custody_lifecycle']['producer']['sha256']='0'*64;self.unknown(t)
    def test_consumer_rejects_unexpected_signal_returncode(self):
        self.unknown(self.fx.reference(),returncode=-2)
    def test_main_calls_new_producer_after_existing_refusals(self):
        tree=_pre_entry_ast.parse(self.fx.cli_source)
        main=next(n for n in tree.body if isinstance(n,_pre_entry_ast.FunctionDef) and n.name=='main')
        calls=[n.func.id for n in _pre_entry_ast.walk(main) if isinstance(n,_pre_entry_ast.Call) and isinstance(n.func,_pre_entry_ast.Name)]
        self.assertIn('_pre_resource_entry_refusal_terminal',calls)


# V1 shares the real initial-read trace observer, without borrowing a V5
# ordinary-scratch profile.  The resource constructor/lock boundaries are the
# existing explicit unit fixture above; its open/read/trace functions stay real.
class _V1PreResourceEntryPublicFixture(_PreResourceEntryPublicFixture):
    def __init__(self, tmp_path, monkeypatch):
        original_input_guard = validation.ValidationResourceReservation._guard_inputs
        super().__init__(tmp_path, monkeypatch)
        self.attempt = tmp_path / 'attempt'
        self.attempt.mkdir(mode=0o700)
        self.source_marker = tmp_path / 'pinned-source.py'
        self.source_marker.write_bytes(b'# fictional input, never executed\n')
        self.value.pop('ordinary_scratch_profile')
        self.value.update(schema='owned-validation-request/v1',
            argv=[sys.executable, '-B', str(self.source_marker)],
            cwd=str(tmp_path), selected_checks=['fictional-initial-read-only'],
            timeout_seconds=300, roots=[], declared_external_writable_paths=[],
            scheduler_state_path=str(tmp_path/'not-opened-scheduler.json'),
            outputs={name: str(self.attempt/name) for name in validation.OUTPUT_NAMES})
        self.value['source_sha256'][str(self.source_marker)] = hashlib.sha256(
            self.source_marker.read_bytes()).hexdigest()
        self.raw = json.dumps(self.value, sort_keys=True).encode()
        self.pin = hashlib.sha256(self.raw).hexdigest()
        self.request_path.write_bytes(self.raw)
        self.outcome['request_sha256'] = self.pin
        fixture_constructor = validation.ValidationResourceReservation.__init__
        fx = self

        def original_guard_constructor(owner):
            fixture_constructor(owner)
            owner.request = deepcopy(fx.value)
            owner.request_sha256 = fx.pin
            owner.request_path = fx.request_path
            owner._request_identity = validation._regular_bytes(
                fx.request_path, validation.MAX_REQUEST_BYTES)[2]
            owner.directory = fx.attempt
            owner.identity = native_disk._root_identity(fx.attempt)
            owner.output_layout = {name: fx.attempt/name for name in validation.OUTPUT_NAMES}
            owner._cwd_identity = native_disk._root_identity(fx.root)
            owner._source_identities = {path: validation._regular_bytes(
                path, validation.MAX_SOURCE_BYTES)[2] for path in owner.request['source_sha256']}
            owner._output_identities = {}
            owner._physical_identities = {}
            owner._startup_clock_profile = None
            owner._ordinary_scratch_profile = None

        monkeypatch.setattr(validation.ValidationResourceReservation, '__init__',
            original_guard_constructor)
        monkeypatch.setattr(validation.ValidationResourceReservation, '_guard_inputs',
            original_input_guard)


@pytest.fixture
def _v1_pre_resource_entry_public_case(request, tmp_path, monkeypatch):
    request.instance._pre_resource_entry_fixture = _V1PreResourceEntryPublicFixture(
        tmp_path, monkeypatch)
    yield


@pytest.mark.usefixtures('_v1_pre_resource_entry_public_case')
class TestCLIV1InitialReadRefusalControls(_pre_entry_unittest.TestCase):
    def setUp(self):
        self.fx = self._pre_resource_entry_fixture

    def tearDown(self):
        self.fx.close()

    def assert_unknown(self, terminal, **changes):
        self.assertEqual(self.fx.classify(terminal, **changes), {
            'verdict': 'requires_original_native_cleanup',
            'source_custody_closed': False, 'storage_release_authorized': False})

    def assert_owner_change_refused(self, key, value):
        owner, error, outcome = self.fx.fail_open()
        setattr(owner, key, value)
        self.assertIsNone(self.fx.produce(owner=owner, error=error, outcome=outcome))

    def test_actual_v1_initial_scope_refusal_emits_no_grant_terminal(self):
        before = self.fx.ledger_path.read_bytes()
        terminal = self.fx.produce()
        self.assertIsInstance(terminal, dict)
        self.assertEqual(self.fx.value['schema'], 'owned-validation-request/v1')
        self.assertNotIn('ordinary_scratch_profile', self.fx.value)
        self.assertEqual(terminal['source_custody_lifecycle']['native_grant'], {
            'status': 'not_requested_before_resource_entry'})
        self.assertEqual(terminal['failure']['error'], 'disk ledger storage scope differs')
        self.assertEqual(self.fx.ledger_path.read_bytes(), before)
        self.assertEqual((self.fx.writes, self.fx.native), (0, 0))

    def test_actual_v1_terminal_closes_only_matching_original_source_custody(self):
        self.assertEqual(self.fx.classify(self.fx.reference()), {
            'verdict': 'proven_original_no_child_no_native_grant',
            'source_custody_closed': True, 'storage_release_authorized': False})

    def test_v1_copied_error_without_live_trace_remains_unknown(self):
        owner = self.fx.sdk.ValidationResourceReservation()
        error = self.fx.host.DaemonResourceError('disk ledger storage scope differs')
        self.assertIsNone(self.fx.produce(owner=owner, error=error, outcome=self.fx.outcome))

    def test_v1_uncertain_write_cannot_reuse_initial_read_boundary(self):
        self.fx.ledger_path.write_text(json.dumps(dict(self.fx.fixture_ledger,
            limit_bytes=250000000000)))
        self.fx.mode = 'write_failure'
        owner, error, outcome = self.fx.fail_open()
        self.assertGreater(self.fx.writes, 0)
        self.assertIsNone(self.fx.produce(owner=owner, error=error, outcome=outcome))

    def test_v1_later_read_during_write_cannot_reuse_initial_trace(self):
        self.fx.ledger_path.write_text(json.dumps(dict(self.fx.fixture_ledger,
            limit_bytes=250000000000)))
        self.fx.mode = 'read_during_write'
        owner, error, outcome = self.fx.fail_open()
        self.assertGreater(self.fx.writes, 0)
        self.assertIsNone(self.fx.produce(owner=owner, error=error, outcome=outcome))

    def test_v1_acquired_lease_stays_unknown(self):
        self.assert_owner_change_refused('_lease', object())

    def test_v1_created_record_stays_unknown(self):
        self.assert_owner_change_refused('_record', {})

    def test_v1_entered_owner_stays_unknown(self):
        self.assert_owner_change_refused('_entered', True)

    def test_v1_attached_child_stays_unknown(self):
        self.assert_owner_change_refused('_child', {})

    def test_v1_mismatched_owner_request_hash_stays_unknown(self):
        self.assert_owner_change_refused('request_sha256', '0'*64)

    def test_v1_mismatched_owner_request_path_stays_unknown(self):
        self.assert_owner_change_refused('request_path', self.fx.root/'other-request.json')

    def test_v1_mismatched_owner_request_value_stays_unknown(self):
        self.assert_owner_change_refused('request', dict(self.fx.value, memory_mb=1))

    def test_v1_mismatched_owner_ledger_path_stays_unknown(self):
        self.assert_owner_change_refused('ledger_path', self.fx.root/'other-ledger.json')

    def test_v1_original_owner_birth_must_still_match(self):
        owner, error, outcome = self.fx.fail_open()
        owner._owner_identity = dict(owner._owner_identity, birth='0')
        self.assertIsNone(self.fx.produce(owner=owner, error=error, outcome=outcome))

    def test_v1_changed_actual_pinned_source_is_refused_before_emission(self):
        owner, error, outcome = self.fx.fail_open()
        self.fx.source_marker.write_bytes(b'# changed fictional source\n')
        self.assertIsNone(self.fx.produce(owner=owner, error=error, outcome=outcome))

    def test_v1_changed_original_request_is_refused_before_emission(self):
        owner, error, outcome = self.fx.fail_open()
        self.fx.request_path.write_bytes(self.fx.raw + b'\n')
        self.assertIsNone(self.fx.produce(owner=owner, error=error, outcome=outcome))

    def test_v1_replaced_attempt_is_refused_by_original_input_guard(self):
        owner, error, outcome = self.fx.fail_open()
        self.fx.attempt.rename(self.fx.root/'original-attempt')
        self.fx.attempt.mkdir(mode=0o700)
        self.assertIsNone(self.fx.produce(owner=owner, error=error, outcome=outcome))

    def test_v1_child_launch_event_stays_unknown(self):
        owner, error, outcome = self.fx.fail_open()
        self.assertIsNone(self.fx.produce(owner=owner, error=error, outcome=outcome,
            events=dict(self.fx.events, child_launch_attempted=True)))

    def test_v1_consumer_rejects_mismatched_request_hash(self):
        self.assert_unknown(self.fx.reference(), expected_request_sha256='0'*64)

    def test_v1_consumer_rejects_mismatched_owner_pid(self):
        self.assert_unknown(self.fx.reference(), owner_pid=os.getpid()+1)

    def test_v1_consumer_rejects_mismatched_owner_birth(self):
        self.assert_unknown(self.fx.reference(), owner_birth='0')

    def test_v1_consumer_rejects_mismatched_resource_ledger(self):
        self.assert_unknown(self.fx.reference(), expected_resource_ledger=str(
            self.fx.root/'not-the-ledger.json'))

    def test_v1_consumer_rejects_mismatched_producer_pin(self):
        terminal = self.fx.reference()
        terminal['source_custody_lifecycle']['producer']['sha256'] = '0'*64
        self.assert_unknown(terminal)

    def test_v1_consumer_rejects_unverified_trace(self):
        terminal = self.fx.reference()
        terminal['source_custody_lifecycle']['entry_refusal_observation']['live_trace_verified'] = False
        self.assert_unknown(terminal)

    def test_v1_consumer_rejects_started_native_or_child_evidence(self):
        terminal = self.fx.reference()
        terminal['source_custody_lifecycle']['events']['child_created'] = True
        self.assert_unknown(terminal)

    def test_v1_consumer_never_authorizes_storage_release(self):
        terminal = self.fx.reference()
        terminal['source_custody_lifecycle']['storage']['release_authorized'] = True
        self.assert_unknown(terminal)

    def test_v1_consumer_requires_actual_failure_exit(self):
        self.assert_unknown(self.fx.reference(), returncode=0)
