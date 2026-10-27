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
