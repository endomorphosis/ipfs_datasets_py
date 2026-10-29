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
        "limit_bytes": 220_000_000_000,
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
    assert _json(ledger)["limit_bytes"] == 220_000_000_000
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
    _write_json(path, original)
    assert module.request(path, _sha(path))[0] == original
    _write_json(path, {**original, "schema": "owned-validation-request/v2"})
    with pytest.raises(ValueError, match="unsupported validation request"):
        module.request(path, _sha(path))
    _write_json(path, trainer)
    with pytest.raises(ValueError, match="unsupported validation request"):
        module.request(path, _sha(path))
    with pytest.raises(ValueError):
        module._validate_trainer_request({"schema": "owned-validation-request/v1"})


def test_trainer_source_guard_requires_public_owner_and_rechecks_owned_source(tmp_path):
    module, _, value = _trainer_controller_request_case(tmp_path)
    module._trainer_source_guard(value)
    owner_source = str(module.ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py")
    assert value["source_sha256"][owner_source] == "da6c3596a413ba5c8dab14f9e06a6fc288d7eb9166d261a96abfdf96dd60130b"
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
            assert options["start_new_session"] is True and argv[1:3] == ["-I", "-S"]
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
    monkeypatch.setattr(module,"sys",SimpleNamespace(flags=SimpleNamespace(isolated=True,no_site=True),modules={}))
    monkeypatch.setattr(module,"threading",SimpleNamespace(Thread=lambda **kwargs:SimpleNamespace(start=lambda:events.append("watch"))))
    genuine_close=os.close
    monkeypatch.setattr(os,"close",lambda fd:events.append("close_READY") if fd == 7001 else genuine_close(fd))
    monkeypatch.chdir(module.ROOT)
    return module,path,value,events,BeforeRUN


def test_trainer_child_waits_for_original_RUN_before_reference_access_or_dispatch(tmp_path,monkeypatch):
    module,path,value,events,BeforeRUN=_trainer_child_fake_bootstrap_case(tmp_path,monkeypatch,stop_at_RUN=True)
    attempted=_trainer_forbid_reference_bodies(monkeypatch,value)
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
