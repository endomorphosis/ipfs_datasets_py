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




# Additive physical-fixture owner controls. Append to the existing owning file;
# its private_control fixture retains the actual private scheduler/ledger owner.

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
