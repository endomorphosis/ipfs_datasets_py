"""Synthetic process/pipe contracts; no subprocess or native model is executed."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_process as module


GUARD = {"mechanism": "linux_seccomp", "denied_syscalls": [
    "socket", "connect", "sendto", "sendmsg", "sendmmsg"], "socket_denial_verified": True}


class SyntheticSpec:
    schema_version = module.CAMPAIGN_SCHEMA_VERSION

    def __init__(self, payload):
        self.payload = payload
        self.run_id = payload["run_id"]
        self.output_directory = payload["output_directory"]
        self.training_config = SimpleNamespace(legal_ir_parallel_workers=3)
        self.canonical_sha256 = hashlib.sha256(module.canonical(payload)).hexdigest()

    @classmethod
    def from_dict(cls, payload):
        return cls(payload)


class SyntheticReservation:
    def __init__(self, events):
        self.events = events

    def check_usage(self, attempt, child_pid=None):
        self.events.append(("usage", child_pid))

    def release(self, **_kwargs):
        raise AssertionError("process helper must never release resource claims")


class SyntheticProcess:
    def __init__(self, pid, argv, options):
        self.pid, self.argv, self.options = pid, argv, options
        self.returncode = None
        self.live = True
        self.release_reader = os.dup(int(argv[9]))
        os.set_blocking(self.release_reader, False)

    def poll(self):
        return self.returncode

    def wait(self, timeout):
        assert timeout > 0
        assert self.returncode is not None
        return self.returncode


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    events, processes = [], []
    clock = [100.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(module, "TrainingJobSpec", SyntheticSpec)
    monkeypatch.setattr(module, "DaemonResourceReservation", SyntheticReservation)

    def observed(pid):
        process = next((p for p in processes if p.pid == pid), None)
        if process is None or not process.live:
            return None
        return {"pid": pid, "group_pid": pid, "birth": str(pid + 100), "parent_pid": os.getpid()}

    ready_change = [None]

    def popen(argv, **kwargs):
        events.append(("spawn",))
        process = SyntheticProcess(20000 + len(processes), argv, kwargs)
        processes.append(process)
        payload = {"schema": module.READY_SCHEMA,
            "identity": {key: observed(process.pid)[key] for key in ("pid", "group_pid", "birth")},
            "owner_pid": os.getpid(), "job_sha256": argv[5],
            "canonical_root": str(module.WORKER_SCRIPT.resolve().parents[3]), "network_guard": GUARD}
        if ready_change[0] is not None:
            payload = ready_change[0](payload)
        raw = payload if isinstance(payload, bytes) else module.canonical(payload) + b"\n"
        os.write(int(argv[8]), raw)
        return process

    def terminate(process, identity):
        assert identity["pid"] == identity["group_pid"] == process.pid
        assert identity["birth"] == str(process.pid + 100)
        events.append(("stop", process.pid))
        process.live = False
        process.returncode = -15

    monkeypatch.setattr(module.subprocess, "Popen", popen)
    monkeypatch.setattr(module, "_process", observed)
    monkeypatch.setattr(module, "_group_usage", lambda identity: {"live_processes": sum(
        p.live for p in processes if identity and p.pid == identity["pid"])})
    monkeypatch.setattr(module, "_terminate", terminate)

    def make_job(index=0):
        root = tmp_path / str(index)
        root.mkdir()
        spec = SyntheticSpec({"run_id": f"synthetic-{index}", "output_directory": str(root / "output")})
        job = root / "job.json"
        job.write_bytes(module.canonical(spec.payload))
        attempt = root / "control"
        attempt.mkdir()
        return spec, module.describe(job), attempt

    def record_start(spec, lease, artifact):
        events.append(("intent", spec.run_id))
        assert lease["run_id"] == spec.run_id and artifact["sha256"] == spec.canonical_sha256

    def record_child(spec, lease, artifact, identity):
        events.append(("observed", spec.run_id))
        process = next(p for p in processes if p.pid == identity["pid"])
        with pytest.raises(BlockingIOError):
            os.read(process.release_reader, 4)
        assert identity["bootstrap"]["network_guard"] == GUARD
        assert artifact["sha256"] == spec.canonical_sha256 and lease["run_id"] == spec.run_id

    executor = module._CampaignProcessExecutor(record_start=record_start, record_child=record_child,
        timeout_seconds=30, max_workers=2, defer_target_hydration_gc=True, reduce_native_targets=True)
    result = SimpleNamespace(events=events, processes=processes, executor=executor,
                             make_job=make_job, ready_change=ready_change, clock=clock)
    yield result
    # Never start or signal a real process, even if the assertion under test fails.
    for item in executor._jobs.values():
        module._CampaignProcessExecutor._finish_handles(item)
    for process in processes:
        os.close(process.release_reader)


def _submit(fixture, index=0, **kwargs):
    spec, artifact, attempt = fixture.make_job(index)
    fixture.executor.register(spec, reservation=SyntheticReservation(fixture.events),
        attempt_directory=attempt, job_artifact=artifact, **kwargs)
    future = fixture.executor.submit(spec, lease={"run_id": spec.run_id, "fence": 1}, job_artifact=artifact)
    return spec, artifact, future


def test_observed_identity_is_durable_before_release_and_original_receipt_is_returned(synthetic):
    owner_checks = []
    spec, _, future = _submit(synthetic, usage_check=lambda: owner_checks.append(True))
    process = synthetic.processes[0]
    assert process.argv[1:3] == ["-I", "-S"]
    assert process.argv[-2:] == ["1", "1"]
    assert process.options["env"]["IPFS_DATASETS_LEGAL_IR_PARALLEL_WORKERS"] == "3"
    assert process.options["start_new_session"] is True
    assert synthetic.events.index(("intent", spec.run_id)) < synthetic.events.index(("spawn",))
    assert not future.done() and future.cancel() is False
    synthetic.executor.poll()
    assert os.read(process.release_reader, 4) == b"RUN\n"
    assert ("observed", spec.run_id) in synthetic.events
    output = Path(spec.output_directory)
    output.mkdir()
    receipt = {"fixture_only": True, "execution_mode": "injected_test"}
    (output / "receipt.json").write_bytes(module.canonical(receipt))
    process.returncode, process.live = 0, False
    synthetic.executor.poll()
    assert future.result() == receipt
    assert owner_checks
    synthetic.executor.close()


@pytest.mark.parametrize("change", [
    lambda p: {**p, "schema": "wrong"},
    lambda p: {**p, "job_sha256": "0" * 64},
    lambda p: {**p, "identity": {**p["identity"], "birth": "reused"}},
    lambda p: {**p, "owner_pid": 1},
    lambda p: {**p, "canonical_root": "/different-tree"},
    lambda p: {**p, "network_guard": {}},
    lambda p: {**p, "unexpected": True},
    lambda p: b"{}\n{}\n",
    lambda p: b"",
])
def test_bad_ready_never_releases_compute(synthetic, change):
    synthetic.ready_change[0] = change
    spec, _, future = _submit(synthetic)
    synthetic.executor.poll()
    with pytest.raises(Exception):
        future.result()
    assert not any(row[0] == "observed" for row in synthetic.events)
    assert ("stop", synthetic.processes[0].pid) in synthetic.events
    assert synthetic.executor._jobs[spec.run_id]["released"] is False


def test_callback_failure_after_start_cannot_implicitly_retry(synthetic):
    def fail(*_args):
        raise RuntimeError("journal unavailable")
    synthetic.executor._record_start = fail
    spec, artifact, attempt = synthetic.make_job()
    synthetic.executor.register(spec, reservation=SyntheticReservation(synthetic.events),
        attempt_directory=attempt, job_artifact=artifact)
    with pytest.raises(RuntimeError, match="journal unavailable"):
        synthetic.executor.submit(spec, lease={"run_id": spec.run_id}, job_artifact=artifact)
    assert not synthetic.processes
    synthetic.executor.stop(spec)
    with pytest.raises(module.CampaignProcessError, match="cannot be retried"):
        synthetic.executor.submit(spec, lease={"run_id": spec.run_id}, job_artifact=artifact)


@pytest.mark.parametrize("boundary", ["journal_failure", "job_mutation", "source_mutation"])
def test_observed_callback_failure_or_drift_never_releases(synthetic, monkeypatch, boundary):
    spec, artifact, future = _submit(synthetic)

    def callback(*_args):
        if boundary == "journal_failure":
            raise RuntimeError("cannot persist identity")
        if boundary == "job_mutation":
            Path(artifact["path"]).write_bytes(b"{}")
        else:
            monkeypatch.setattr(synthetic.executor, "_sources_current", lambda: (_ for _ in ()).throw(RuntimeError("drift")))
    synthetic.executor._record_child = callback
    synthetic.executor.poll()
    assert future.done() and future.exception() is not None
    assert synthetic.executor._jobs[spec.run_id]["released"] is False


def test_stopping_one_job_preserves_other_worker_and_makes_future_terminal(synthetic):
    first, _, first_future = _submit(synthetic, 0)
    second, _, second_future = _submit(synthetic, 1)
    synthetic.executor.poll()
    synthetic.executor.stop(first)
    assert first_future.done() and first_future.exception() is not None
    assert not second_future.done() and synthetic.processes[1].live
    synthetic.executor.stop(first)
    synthetic.executor.stop(second)


def test_whole_execution_timeout_includes_ready_wait_and_close_reaps(synthetic):
    _, _, future = _submit(synthetic)
    synthetic.executor._deadline = 0
    with pytest.raises(module.CampaignProcessError, match="wall deadline"):
        synthetic.executor.poll()
    synthetic.executor.close()
    assert future.done() and not synthetic.processes[0].live


def test_unconfirmed_cleanup_stays_nonterminal_and_never_releases(synthetic, monkeypatch):
    spec, _, future = _submit(synthetic)
    def fail(*_args):
        raise RuntimeError("PID was reused or group death unconfirmed")
    monkeypatch.setattr(module, "_terminate", fail)
    with pytest.raises(RuntimeError, match="unconfirmed"):
        synthetic.executor.stop(spec)
    assert not future.done()
    with pytest.raises(module.CampaignProcessError, match="explicit recovery"):
        synthetic.executor.close()
    assert synthetic.processes[0].live


def test_success_exit_with_live_descendant_is_stopped_not_accepted(synthetic):
    _, _, future = _submit(synthetic)
    synthetic.executor.poll()
    synthetic.processes[0].returncode = 0
    synthetic.executor.poll()
    assert future.done() and "descendants" in str(future.exception())
    assert not synthetic.processes[0].live


def test_terminal_usage_is_monitored_until_retire_without_implicit_restart(synthetic):
    checks = []
    spec, artifact, _ = _submit(synthetic, usage_check=lambda: checks.append(True))
    with pytest.raises(module.CampaignProcessError, match="confirmed-dead"):
        synthetic.executor.retire(spec)
    synthetic.executor.stop(spec)
    before = len(checks)
    synthetic.clock[0] += module.USAGE_CHECK_INTERVAL_SECONDS
    synthetic.executor.poll()
    assert len(checks) > before
    synthetic.executor.retire(spec)
    synthetic.executor.retire(spec)
    synthetic.executor.stop(spec)
    before = len(checks)
    synthetic.executor.poll()
    assert len(checks) == before
    with pytest.raises(module.CampaignProcessError, match="already registered"):
        synthetic.executor.register(spec, reservation=SyntheticReservation(synthetic.events),
            attempt_directory=Path(artifact["path"]).parent / "control", job_artifact=artifact)


def test_terminal_replay_usage_failure_propagates_without_successful_release(synthetic):
    spec, _, future = _submit(synthetic)
    synthetic.executor.stop(spec)
    def exceeded():
        raise RuntimeError("completion usage exceeded")
    synthetic.executor._jobs[spec.run_id]["usage_check"] = exceeded
    synthetic.clock[0] += module.USAGE_CHECK_INTERVAL_SECONDS
    with pytest.raises(RuntimeError, match="completion usage"):
        synthetic.executor.poll()
    assert future.exception() is not None


def test_usage_census_is_throttled_but_execution_boundaries_force_checks(synthetic):
    checks = []
    spec, artifact, attempt = synthetic.make_job()
    synthetic.executor.register(spec, reservation=SyntheticReservation(synthetic.events),
        attempt_directory=attempt, job_artifact=artifact, usage_check=lambda: checks.append(True))
    assert len(checks) == 1
    future = synthetic.executor.submit(spec, lease={"run_id": spec.run_id}, job_artifact=artifact)
    assert len(checks) == 3  # start plus child registration, despite no elapsed time
    synthetic.executor.poll()
    assert len(checks) == 4  # ready boundary
    for delta in (0.0, 0.25, 4.99):
        synthetic.clock[0] = 100.0 + delta
        synthetic.executor.poll()
        assert len(checks) == 4
    synthetic.clock[0] = 105.0
    synthetic.executor.poll()
    assert len(checks) == 5
    output = Path(spec.output_directory)
    output.mkdir()
    (output / "receipt.json").write_bytes(module.canonical({"fixture_only": True}))
    process = synthetic.processes[0]
    process.returncode, process.live = 0, False
    synthetic.executor.poll()
    assert future.done() and len(checks) == 6  # terminal, same clock
    synthetic.executor.retire(spec)
    assert len(checks) == 7  # owner completion boundary, same clock


def _bootstrap():
    spec = importlib.util.spec_from_file_location("synthetic_campaign_bootstrap", module.WORKER_SCRIPT)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.mark.parametrize("token", [b"", b"BAD\n", b"RU"])
def test_waiting_bootstrap_exits_on_pipe_loss_or_bad_token(monkeypatch, token):
    child = _bootstrap()
    reader, writer = os.pipe()
    try:
        os.write(writer, token)
        os.close(writer)
        writer = None
        with pytest.raises(RuntimeError):
            child._await_release(reader, timeout_seconds=1, owner_pid=os.getppid())
    finally:
        os.close(reader)
        if writer is not None:
            os.close(writer)


def test_waiting_bootstrap_checks_parent_before_reading(monkeypatch):
    child = _bootstrap()
    with pytest.raises(RuntimeError, match="owner disappeared"):
        child._await_release(-1, timeout_seconds=1, owner_pid=os.getppid() + 1)


def test_waiting_bootstrap_deadline_expires_without_compute(monkeypatch):
    child = _bootstrap()
    ticks = iter([0.0, 2.0])
    monkeypatch.setattr(child.time, "monotonic", lambda: next(ticks))
    with pytest.raises(RuntimeError, match="deadline expired"):
        child._await_release(-1, timeout_seconds=1, owner_pid=os.getppid())


def test_source_pin_failure_stops_before_original_worker(monkeypatch):
    from ipfs_datasets_py.logic.autoformal import tree_pin

    child = _bootstrap()
    events = []
    monkeypatch.setattr(child, "sys", SimpleNamespace(path=[str(child.ROOT)]))
    monkeypatch.setattr(child, "_configure_dependency_paths", lambda: events.append("dependencies"))
    def reject():
        events.append("pin")
        raise RuntimeError("drifted parser")
    monkeypatch.setattr(tree_pin, "require_workspace_logic_tree", reject)
    with pytest.raises(RuntimeError, match="drifted parser"):
        child._run_original("/unused", "0" * 64, 3, "0" * 64, defer_gc=False, reduce_targets=False)
    assert events == ["dependencies", "pin"]
    assert child.sys.path[0] == str(child.ROOT)


def test_dependency_directories_do_not_execute_startup_hooks(tmp_path, monkeypatch):
    import site
    child = _bootstrap()
    user, system = tmp_path / "user", tmp_path / "system"
    user.mkdir()
    system.mkdir()
    (user / "unsafe.pth").write_text("import unexpected_editable_tree\n")
    monkeypatch.setattr(site, "getusersitepackages", lambda: str(user))
    monkeypatch.setattr(site, "getsitepackages", lambda: [str(system), str(tmp_path / "missing")])
    monkeypatch.setattr(site, "main", lambda: pytest.fail("site startup must remain disabled"))
    monkeypatch.setattr(site, "addsitedir", lambda *_: pytest.fail("pth execution must remain disabled"))
    monkeypatch.setattr(child, "sys", SimpleNamespace(path=["/stdlib", str(system), str(child.ROOT)]))
    assert child._configure_dependency_paths() == (str(user), str(system))
    assert child.sys.path == [str(child.ROOT), "/stdlib", str(user), str(system)]


@pytest.mark.parametrize("kind", ["symlink", "regular_file"])
def test_dependency_directories_reject_nonordinary_components(tmp_path, monkeypatch, kind):
    import site
    child = _bootstrap()
    path = tmp_path / "dependency"
    if kind == "symlink":
        import stat
        path.symlink_to(tmp_path, target_is_directory=True)
        owned = path.lstat()
        assert stat.S_ISLNK(owned.st_mode) and owned.st_nlink == 1
        identity = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        try:
            monkeypatch.setattr(site, "getusersitepackages", lambda: str(path / "nested"))
            monkeypatch.setattr(site, "getsitepackages", lambda: [])
            with pytest.raises(RuntimeError, match="unsafe component"):
                child._configure_dependency_paths()
        finally:
            # Remove only the exact symlink created by THIS test invocation.
            # A replaced or changed entry remains evidence and fails the test.
            current = path.lstat()
            assert stat.S_ISLNK(current.st_mode) and identity(current) == identity(owned)
            assert os.readlink(path) == str(tmp_path)
            path.unlink()
        return
    path.write_text("not a directory")
    monkeypatch.setattr(site, "getusersitepackages", lambda: str(path / "nested"))
    monkeypatch.setattr(site, "getsitepackages", lambda: [])
    with pytest.raises(RuntimeError, match="unsafe component"):
        child._configure_dependency_paths()


@pytest.mark.parametrize("isolated,modules", [(False, {}), (True, {"ipfs_datasets_py": object()})])
def test_bootstrap_rejects_unsafe_startup_before_network_or_job_import(monkeypatch, isolated, modules):
    child = _bootstrap()
    monkeypatch.setattr(child, "sys", SimpleNamespace(modules=modules, path=[], stderr=io.StringIO(),
        flags=SimpleNamespace(isolated=isolated, no_site=True)))
    monkeypatch.setattr(child, "_network_denial", lambda *_: pytest.fail("unsafe bootstrap must stop"))
    assert child.main(["/unused", "0" * 64, "3", "0" * 64, "8", "9", str(os.getppid()),
                       "1", "0" * 64, "0", "0"]) == 1


def test_release_watchdog_signals_only_its_own_isolated_group(monkeypatch):
    child = _bootstrap()
    events = []
    class ExitObserved(BaseException):
        pass
    monkeypatch.setattr(child.select, "select", lambda *_args: ([9], [], []))
    monkeypatch.setattr(child.os, "getpid", lambda: 123)
    monkeypatch.setattr(child.os, "getpgrp", lambda: 123)
    monkeypatch.setattr(child.os, "killpg", lambda *args: events.append(args))
    monkeypatch.setattr(child.os, "_exit", lambda code: (_ for _ in ()).throw(ExitObserved(code)))
    with pytest.raises(ExitObserved):
        child._watch_owner(9, owner_pid=os.getppid(), group_pid=123)
    assert events == [(123, child.signal.SIGKILL)]
    events.clear()
    with pytest.raises(ExitObserved):
        child._watch_owner(9, owner_pid=os.getppid(), group_pid=456)
    assert events == []


def test_bootstrap_order_is_offline_then_handshake_then_original_worker(monkeypatch):
    child = _bootstrap()
    events = []
    monkeypatch.setattr(child, "sys", SimpleNamespace(modules={}, path=[], stderr=io.StringIO(),
                                                     flags=SimpleNamespace(isolated=True, no_site=True)))
    monkeypatch.setattr(child, "_network_denial", lambda _sha: events.append("network") or GUARD)
    monkeypatch.setattr(child, "_identity", lambda: {"pid": 123, "group_pid": 123, "birth": "birth"})
    monkeypatch.setattr(child, "_send_ready", lambda *_args: events.append("ready"))
    monkeypatch.setattr(child, "_await_release", lambda *_args, **_kwargs: events.append("release"))
    monkeypatch.setattr(child.os, "close", lambda _fd: None)
    monkeypatch.setattr(child.threading, "Thread", lambda **_kwargs: SimpleNamespace(start=lambda: events.append("watch")))
    monkeypatch.setattr(child, "_run_original", lambda *_args, **_kwargs: events.append("original"))
    assert child.main(["/synthetic/job", "a" * 64, "3", "b" * 64, "8", "9",
                       str(os.getppid()), "1", "c" * 64, "0", "1"]) == 0
    assert events == ["network", "ready", "release", "watch", "original"]
    assert child.sys.path[0] == str(child.ROOT)


def test_bootstrap_top_level_has_no_project_imports_and_pin_precedes_worker_call():
    tree = ast.parse(module.WORKER_SCRIPT.read_text())
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("ipfs_")
        if isinstance(node, ast.Import):
            assert not any(alias.name.startswith("ipfs_") for alias in node.names)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_run_original")
    calls = [(node.func.id, node.lineno) for node in ast.walk(function)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    assert next(line for name, line in calls if name == "require_workspace_logic_tree") < next(
        line for name, line in calls if name == "_execute_training_job")


def test_reviewed_parent_callback_source_denial_preserves_original_error_and_sends_no_ack(monkeypatch):
    """Synthetic guard/FD ordering only; no grant or genuine process is claimed."""
    import socket
    parent_identity = {"pid": os.getpid(), "birth": "11001"}
    child_identity = {"pid": 22002, "birth": "33003"}
    observed = {parent_identity["pid"]: {**parent_identity, "parent_pid": 1,
        "group_pid": parent_identity["pid"], "rss_bytes": 0},
        child_identity["pid"]: {**child_identity, "parent_pid": parent_identity["pid"],
        "group_pid": child_identity["pid"], "rss_bytes": 0}}
    monkeypatch.setattr(module, "_process", lambda pid: observed.get(pid))
    monkeypatch.setattr(module, "_group_usage", lambda identity: {
        "available": True, "rss_bytes": 0, "live_processes": 1})
    owner = object.__new__(module.DaemonResourceReservation)
    owner._owner_pid = parent_identity["pid"]
    owner._entered = True
    owner._record = {"owner_pid": parent_identity["pid"], "status": "active", "child": dict(child_identity)}
    owner._child = dict(child_identity)
    owner._lease = SimpleNamespace(cancelled=False)
    owner.reservation_id = "fixture:synthetic-original-reservation"
    owner.cpu_slots, owner.memory_mb, owner.child_process_slots = 1, 64, 2
    owner.storage_bytes = 4 * 1024**2
    lane, workload = owner._scheduler_identity()
    owner._record.update(reservation_id=owner.reservation_id, scheduler_lane=lane.value,
        workload=workload, storage_bytes=owner.storage_bytes, cpu_slots=1, memory_mb=64, child_process_slots=2)
    owner._lease = SimpleNamespace(cancelled=False, lease_id="b" * 32, lane=lane.value,
        owner_pid=parent_identity["pid"], parent_lease_id=None, requires_gpu=False,
        _released=False, cpu_slots=1, memory_mb=64, child_process_slots=2)
    owner._verify_owner_roots = lambda: None
    owner.heartbeat = lambda: True
    owner.release = lambda **kwargs: pytest.fail("callback channel released storage/native custody")
    class OriginalSourceDenied(RuntimeError):
        pass
    denied = OriginalSourceDenied("original parent source guard denied")
    def source_guard():
        raise denied
    parent, peer = socket.socketpair()
    descriptor = parent.detach()
    server = None
    try:
        server = module._ReviewedParentCallbackServer(descriptor, owner=owner,
            child_identity=child_identity, owner_identity=parent_identity,
            request_sha256="a" * 64, deadline=module.time.monotonic() + 5,
            source_guard=source_guard,
            asset_policy_guard=lambda policy: pytest.fail("source denial reached asset policy"),
            current_admission_provider=lambda: pytest.fail("source denial reached current admission"))
        frame = {"schema": "reviewed-parent-callback-request/v1", "request_sha256": "a" * 64,
            "sequence": 1, "operation": "GUARD", "owner_identity": parent_identity,
            "child_identity": child_identity, "payload": None}
        os.write(peer.fileno(), module.canonical(frame) + b"\n")
        with pytest.raises(OriginalSourceDenied) as captured:
            server.poll()
        assert captured.value is denied
        observation = server.observation()
        assert observation["acknowledged_requests"] == 0
        assert observation["last_error"]["type"] == "OriginalSourceDenied"
        assert observation["closed"] is True
        os.set_blocking(peer.fileno(), False)
        assert os.read(peer.fileno(), 1024) == b""
    finally:
        if server is not None:
            server.close()
        else:
            os.close(descriptor)
        peer.close()


@pytest.fixture
def reviewed_callback_channel(monkeypatch):
    """Synthetic live-owner observations plus real private FDs; no native grant."""
    import socket
    clock = [100.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    parent = {"pid": os.getpid(), "birth": "11001"}
    child = {"pid": 22002, "birth": "33003"}
    processes = {parent["pid"]: {**parent, "parent_pid": 1, "group_pid": parent["pid"], "rss_bytes": 0, "state": "S"},
        child["pid"]: {**child, "parent_pid": parent["pid"], "group_pid": child["pid"], "rss_bytes": 0, "state": "S"}}
    group = {"available": True, "rss_bytes": 0, "live_processes": 1}
    monkeypatch.setattr(module, "_process", lambda pid: processes.get(pid))
    monkeypatch.setattr(module, "_group_usage", lambda identity: dict(group))
    owner = object.__new__(module.DaemonResourceReservation)
    owner._owner_pid, owner._entered = parent["pid"], True
    owner._record = {"owner_pid": parent["pid"], "status": "active", "child": dict(child)}
    owner._child, owner._lease = dict(child), SimpleNamespace(cancelled=False)
    owner.reservation_id = "fixture:synthetic-original-reservation"
    owner.cpu_slots, owner.memory_mb, owner.child_process_slots = 1, 64, 2
    owner.storage_bytes = 4 * 1024**2
    lane, workload = owner._scheduler_identity()
    owner._record.update(reservation_id=owner.reservation_id, scheduler_lane=lane.value,
        workload=workload, storage_bytes=owner.storage_bytes, cpu_slots=1, memory_mb=64, child_process_slots=2)
    owner._lease = SimpleNamespace(cancelled=False, lease_id="b" * 32, lane=lane.value,
        owner_pid=parent["pid"], parent_lease_id=None, requires_gpu=False,
        _released=False, cpu_slots=1, memory_mb=64, child_process_slots=2)
    owner._verify_owner_roots = lambda: None
    events = []
    owner.heartbeat = lambda: events.append("heartbeat") or True
    owner.release = lambda **kwargs: pytest.fail("callback relay released original custody")
    source = [lambda: events.append("source")]
    asset = [lambda policy: events.append(("asset", policy))]
    admission = [{"review_bytes": b"synthetic-private-review-not-for-transport", "generation": 0}]
    left, peer = socket.socketpair()
    descriptor = left.detach()
    server = None
    try:
        server = module._ReviewedParentCallbackServer(descriptor, owner=owner,
            child_identity=child, owner_identity=parent, request_sha256="a" * 64,
            deadline=110.0, source_guard=lambda: source[0](),
            asset_policy_guard=lambda policy: asset[0](policy), current_admission_provider=lambda: admission[0])
        yield SimpleNamespace(server=server, peer=peer, owner=owner, parent=parent, child=child,
            processes=processes, group=group, source=source, asset=asset,
            admission=admission, clock=clock, events=events)
    finally:
        if server is None:
            os.close(descriptor)
        else:
            server.close()
        peer.close()


def _reviewed_callback_frame(channel, operation="GUARD", payload=None, sequence=None):
    return {"schema": "reviewed-parent-callback-request/v1", "request_sha256": "a" * 64,
        "sequence": channel.server.observation()["last_sequence"] + 1 if sequence is None else sequence,
        "operation": operation, "owner_identity": dict(channel.parent),
        "child_identity": dict(channel.child), "payload": payload}


def _reviewed_callback_roundtrip(channel, operation="GUARD", payload=None):
    os.write(channel.peer.fileno(), module.canonical(_reviewed_callback_frame(channel, operation, payload)) + b"\n")
    assert channel.server.poll() is True
    raw = os.read(channel.peer.fileno(), 1024)
    assert len(raw) <= 1024
    return json.loads(raw), raw


def test_reviewed_parent_callback_checks_all_operations_and_finish_without_releasing_owner(reviewed_callback_channel):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_consumer_binding import reviewed_admission_inputs_sha256
    channel = reviewed_callback_channel
    reply, _ = _reviewed_callback_roundtrip(channel)
    assert reply["sequence"] == 1 and reply["operation"] == "GUARD" and reply["admission_sha256"] is None
    policy = {"schema": "fixture:ordinary-policy", "training_requested": False}
    _reviewed_callback_roundtrip(channel, "ASSET", policy)
    assert ("asset", policy) in channel.events
    expected = reviewed_admission_inputs_sha256(channel.admission[0])
    reply, raw = _reviewed_callback_roundtrip(channel, "ADMISSION", {"expected_sha256": expected})
    assert reply["admission_sha256"] == expected and b"synthetic-private-review" not in raw
    reply, _ = _reviewed_callback_roundtrip(channel, "FINISH")
    assert reply["sequence"] == 4 and reply["operation"] == "FINISH"
    observation = channel.server.observation()
    assert channel.server.finished is True and observation["closed"] is observation["finished"] is True
    assert observation["acknowledged_requests"] == 4 and observation["last_error"] is None
    assert observation["operations"] == {"GUARD": 1, "ASSET": 1, "ADMISSION": 1, "FINISH": 1}
    assert observation["storage_release_authorized"] is observation["resource_authority_granted"] is False
    assert channel.owner._entered is True and channel.owner._record["status"] == "active"
    assert os.read(channel.peer.fileno(), 1024) == b""
    with pytest.raises(RuntimeError):
        channel.server.poll()
    assert channel.server.observation()["acknowledged_requests"] == 4


def test_reviewed_parent_callback_checks_cancel_every_request_while_heartbeat_is_throttled(reviewed_callback_channel):
    channel = reviewed_callback_channel
    _reviewed_callback_roundtrip(channel)
    _reviewed_callback_roundtrip(channel)
    assert channel.events.count("heartbeat") == 1
    channel.owner._lease.cancelled = True
    os.write(channel.peer.fileno(), module.canonical(_reviewed_callback_frame(channel)) + b"\n")
    with pytest.raises(RuntimeError, match="cancelled"):
        channel.server.poll()
    assert channel.server.observation()["acknowledged_requests"] == 2


def test_reviewed_parent_callback_sdk_guard_and_local_check_never_request_global_census(reviewed_callback_channel, monkeypatch):
    channel = reviewed_callback_channel
    observed = []
    channel.owner.guard = lambda: observed.append("sdk_guard")
    channel.owner.check_limits = lambda *, full: observed.append(("local", full))
    monkeypatch.setattr(module, "_group_usage", lambda identity: pytest.fail("SDK callback used legacy group observer"))
    _reviewed_callback_roundtrip(channel)
    assert "sdk_guard" in observed and ("local", False) in observed
    assert all(item != ("local", True) for item in observed)


@pytest.mark.parametrize("operation", ["ASSET", "ADMISSION"])
def test_reviewed_parent_callback_original_policy_error_never_becomes_an_ack(reviewed_callback_channel, operation):
    channel = reviewed_callback_channel
    denied = PermissionError("original trusted parent policy denied")
    def reject(*args):
        raise denied
    if operation == "ASSET":
        channel.asset[0] = reject
        payload = {"fixture": "policy"}
    else:
        channel.admission[0] = None
        channel.server._admission_provider = reject
        payload = {"expected_sha256": "b" * 64}
    os.write(channel.peer.fileno(), module.canonical(_reviewed_callback_frame(channel, operation, payload)) + b"\n")
    with pytest.raises(PermissionError) as captured:
        channel.server.poll()
    assert captured.value is denied and channel.server.observation()["acknowledged_requests"] == 0
    assert channel.server.observation()["last_error"]["type"] == "PermissionError"


@pytest.mark.parametrize("fault", ["request", "owner_birth", "child_birth", "owner_float_pid", "sequence", "sequence_bool",
    "extra", "operation", "guard_payload", "admission_payload", "admission_digest"])
def test_reviewed_parent_callback_refuses_malformed_or_foreign_requests_before_ack(reviewed_callback_channel, fault):
    channel = reviewed_callback_channel
    frame = _reviewed_callback_frame(channel)
    if fault == "request": frame["request_sha256"] = "b" * 64
    elif fault == "owner_birth": frame["owner_identity"]["birth"] = "99"
    elif fault == "child_birth": frame["child_identity"]["birth"] = "99"
    elif fault == "owner_float_pid": frame["owner_identity"]["pid"] = float(channel.parent["pid"])
    elif fault == "sequence": frame["sequence"] = 2
    elif fault == "sequence_bool": frame["sequence"] = True
    elif fault == "extra": frame["extra"] = "unbound"
    elif fault == "operation": frame["operation"] = "ALLOCATE"
    elif fault == "guard_payload": frame["payload"] = {"authority": True}
    elif fault == "admission_payload": frame.update(operation="ADMISSION", payload={"expected_sha256": "b" * 64, "review": {}})
    else: frame.update(operation="ADMISSION", payload={"expected_sha256": "B" * 64})
    os.write(channel.peer.fileno(), module.canonical(frame) + b"\n")
    with pytest.raises(RuntimeError):
        channel.server.poll()
    observation = channel.server.observation()
    assert observation["acknowledged_requests"] == 0 and observation["closed"] is True


@pytest.mark.parametrize("raw", [b'{"schema":1,"schema":2}\n', b'{}\n{}\n', b'not-json\n', b'{' + b' ' * (32 * 1024)])
def test_reviewed_parent_callback_refuses_ambiguous_or_oversize_framing(reviewed_callback_channel, raw):
    channel = reviewed_callback_channel
    os.write(channel.peer.fileno(), raw)
    with pytest.raises((RuntimeError, ValueError)):
        channel.server.poll()
    assert channel.server.observation()["closed"] is True
    assert channel.server.observation()["acknowledged_requests"] == 0


@pytest.mark.parametrize("fault", ["parent_birth", "child_birth", "child_parent", "recorded_child", "lease", "deadline", "heartbeat", "rss", "slots"])
def test_reviewed_parent_callback_requires_fresh_original_custody_for_each_ack(reviewed_callback_channel, fault):
    channel = reviewed_callback_channel
    if fault == "parent_birth": channel.processes[channel.parent["pid"]]["birth"] = "99"
    elif fault == "child_birth": channel.processes[channel.child["pid"]]["birth"] = "99"
    elif fault == "child_parent": channel.processes[channel.child["pid"]]["parent_pid"] += 1
    elif fault == "recorded_child": channel.owner._record["child"] = {**channel.child, "birth": "99"}
    elif fault == "lease": channel.owner._lease = SimpleNamespace(cancelled=False)
    elif fault == "deadline": channel.clock[0] = 111.0
    elif fault == "heartbeat": channel.owner.heartbeat = lambda: False
    elif fault == "rss": channel.group["rss_bytes"] = 65 * 1024**2
    else: channel.group["live_processes"] = 3
    os.write(channel.peer.fileno(), module.canonical(_reviewed_callback_frame(channel)) + b"\n")
    with pytest.raises(RuntimeError):
        channel.server.poll()
    assert channel.server.observation()["acknowledged_requests"] == 0


def test_reviewed_parent_callback_rechecks_child_and_admission_after_trusted_callback(reviewed_callback_channel):
    channel = reviewed_callback_channel
    def revoke(policy):
        channel.processes[channel.child["pid"]]["birth"] = "99"
    channel.asset[0] = revoke
    os.write(channel.peer.fileno(), module.canonical(_reviewed_callback_frame(channel, "ASSET", {"fixture": "policy"})) + b"\n")
    with pytest.raises(RuntimeError, match="child identity"):
        channel.server.poll()
    assert channel.server.observation()["acknowledged_requests"] == 0


def test_reviewed_parent_callback_current_admission_mismatch_sends_no_review_body(reviewed_callback_channel):
    channel = reviewed_callback_channel
    os.write(channel.peer.fileno(), module.canonical(_reviewed_callback_frame(channel, "ADMISSION", {"expected_sha256": "b" * 64})) + b"\n")
    with pytest.raises(RuntimeError, match="admission digest"):
        channel.server.poll()
    assert channel.server.observation()["acknowledged_requests"] == 0
    assert os.read(channel.peer.fileno(), 1024) == b""


def test_reviewed_parent_callback_partial_frame_is_nonblocking_and_replay_is_refused(reviewed_callback_channel):
    channel = reviewed_callback_channel
    raw = module.canonical(_reviewed_callback_frame(channel)) + b"\n"
    os.write(channel.peer.fileno(), raw[:10])
    assert channel.server.poll() is False and channel.server.observation()["acknowledged_requests"] == 0
    os.write(channel.peer.fileno(), raw[10:])
    assert channel.server.poll() is True
    assert json.loads(os.read(channel.peer.fileno(), 1024))["sequence"] == 1
    os.write(channel.peer.fileno(), raw)
    with pytest.raises(RuntimeError, match="sequence"):
        channel.server.poll()
    assert channel.server.observation()["acknowledged_requests"] == 1


@pytest.mark.parametrize("after_guard", [False, True])
def test_reviewed_parent_callback_eof_without_finish_is_failure(reviewed_callback_channel, after_guard):
    channel = reviewed_callback_channel
    if after_guard:
        _reviewed_callback_roundtrip(channel)
    channel.peer.close()
    with pytest.raises(EOFError):
        channel.server.poll()
    assert channel.server.finished is False and channel.server.observation()["closed"] is True


def test_reviewed_parent_callback_parent_guard_remains_live_after_finish_and_reap(reviewed_callback_channel):
    channel = reviewed_callback_channel
    _reviewed_callback_roundtrip(channel, "FINISH")
    del channel.processes[channel.child["pid"]]
    channel.group["live_processes"] = 0
    channel.server._guard_parent()
    channel.owner._lease.cancelled = True
    with pytest.raises(RuntimeError, match="cancelled"):
        channel.server._guard_parent()
    assert channel.server.finished is True and channel.owner._record["status"] == "active"


def test_reviewed_parent_callback_changed_rpc_descriptor_refuses_without_closing_foreign_fd(reviewed_callback_channel):
    channel = reviewed_callback_channel
    descriptor = channel.server._fd
    os.close(descriptor)
    reader, writer = os.pipe()
    try:
        assert reader == descriptor
        with pytest.raises(RuntimeError, match="descriptor changed"):
            channel.server.poll()
        assert os.fstat(reader)
        observation = channel.server.observation()
        assert observation["rpc_descriptor_identity_changed"] is True
        assert observation["acknowledged_requests"] == 0
    finally:
        os.close(reader)
        os.close(writer)


def _reviewed_callback_client_fixture(monkeypatch):
    import socket
    import time
    child = _bootstrap()
    identities = {"owner": {"pid": os.getppid(), "birth": "11001"}, "child": {"pid": os.getpid(), "birth": "22002"}}
    processes = {identities["owner"]["pid"]: {**identities["owner"], "parent_pid": 1, "group_pid": identities["owner"]["pid"]},
        identities["child"]["pid"]: {**identities["child"], "parent_pid": identities["owner"]["pid"], "group_pid": identities["child"]["pid"]}}
    monkeypatch.setattr(child, "_reviewed_callback_process", lambda pid: processes.get(pid))
    left, peer = socket.socketpair()
    descriptor = left.detach()
    client = child._ReviewedParentCallbackClient(descriptor, owner_identity=identities["owner"],
        child_identity=identities["child"], request_sha256="a" * 64, deadline=time.monotonic() + 2)
    return SimpleNamespace(child=child, client=client, peer=peer, identities=identities, processes=processes)


def _reviewed_callback_respond(fixture, operations, mutate=None):
    import select
    import threading
    import time
    errors = []
    def run():
        try:
            for operation in operations:
                raw = b""
                deadline = time.monotonic() + 2
                while b"\n" not in raw:
                    remaining = deadline - time.monotonic()
                    assert remaining > 0 and select.select([fixture.peer.fileno()], [], [], remaining)[0]
                    part = os.read(fixture.peer.fileno(), 32769 - len(raw))
                    assert part
                    raw += part
                frame = json.loads(raw)
                assert frame["operation"] == operation
                reply = {"schema": "reviewed-parent-callback-reply/v1", "request_sha256": frame["request_sha256"],
                    "sequence": frame["sequence"], "operation": operation, "owner_identity": frame["owner_identity"],
                    "child_identity": frame["child_identity"],
                    "admission_sha256": frame["payload"]["expected_sha256"] if operation == "ADMISSION" else None}
                if mutate is not None:
                    mutate(reply)
                os.write(fixture.peer.fileno(), module.canonical(reply) + b"\n")
        except BaseException as error:
            errors.append(error)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, errors


def test_reviewed_parent_callback_client_binds_each_exchange_and_finish_without_grant(monkeypatch):
    fixture = _reviewed_callback_client_fixture(monkeypatch)
    thread, errors = _reviewed_callback_respond(fixture, ["GUARD", "ASSET", "ADMISSION", "FINISH"])
    try:
        fixture.client.execution_guard()
        fixture.client.asset_policy_guard({"fixture": "ordinary policy"})
        assert fixture.client.current_admission_digest("b" * 64) == "b" * 64
        fixture.client.finish()
        observation = fixture.client.observation()
        assert observation["completed_requests"] == 4 and observation["finished"] is observation["closed"] is True
        assert observation["storage_release_authorized"] is observation["resource_authority_granted"] is False
        with pytest.raises(RuntimeError):
            fixture.client.execution_guard()
        assert fixture.client.observation()["completed_requests"] == 4
    finally:
        fixture.client.close()
        fixture.peer.close()
        thread.join(timeout=1)
    assert not thread.is_alive() and errors == []


@pytest.mark.parametrize("fault", ["sequence", "operation", "request", "owner", "float_pid", "extra", "digest"])
def test_reviewed_parent_callback_client_rejects_foreign_or_malformed_ack(monkeypatch, fault):
    fixture = _reviewed_callback_client_fixture(monkeypatch)
    def mutate(reply):
        if fault == "sequence": reply["sequence"] += 1
        elif fault == "operation": reply["operation"] = "ASSET"
        elif fault == "request": reply["request_sha256"] = "b" * 64
        elif fault == "owner": reply["owner_identity"]["birth"] = "99"
        elif fault == "float_pid": reply["owner_identity"]["pid"] = float(reply["owner_identity"]["pid"])
        elif fault == "extra": reply["review_body"] = "must not be transported"
        else: reply["admission_sha256"] = "b" * 64
    thread, errors = _reviewed_callback_respond(fixture, ["GUARD"], mutate)
    try:
        with pytest.raises(RuntimeError):
            fixture.client.execution_guard()
        assert fixture.client.observation()["closed"] is True
        assert fixture.client.observation()["completed_requests"] == 0
    finally:
        fixture.client.close()
        fixture.peer.close()
        thread.join(timeout=1)
    assert not thread.is_alive() and errors == []


def test_reviewed_parent_callback_client_rechecks_original_parent_after_ack(monkeypatch):
    fixture = _reviewed_callback_client_fixture(monkeypatch)
    def change_parent(reply):
        fixture.processes[fixture.identities["owner"]["pid"]]["birth"] = "99"
    thread, errors = _reviewed_callback_respond(fixture, ["GUARD"], change_parent)
    try:
        with pytest.raises(RuntimeError, match="binding changed"):
            fixture.client.execution_guard()
        assert fixture.client.observation()["completed_requests"] == 0
    finally:
        fixture.client.close()
        fixture.peer.close()
        thread.join(timeout=1)
    assert not thread.is_alive() and errors == []


def test_reviewed_parent_callback_client_early_eof_and_original_deadline_refuse(monkeypatch):
    fixture = _reviewed_callback_client_fixture(monkeypatch)
    fixture.peer.close()
    try:
        with pytest.raises((RuntimeError, BrokenPipeError)):
            fixture.client.execution_guard()
        assert fixture.client.observation()["completed_requests"] == 0
    finally:
        fixture.client.close()
    fixture = _reviewed_callback_client_fixture(monkeypatch)
    fixture.client._deadline = -1.0
    try:
        with pytest.raises(RuntimeError, match="deadline"):
            fixture.client.execution_guard()
        assert fixture.client.observation()["completed_requests"] == 0
    finally:
        fixture.client.close()
        fixture.peer.close()



def test_reviewed_dependency_prefix_uses_only_parent_environment_and_preserves_legacy_discovery(tmp_path, monkeypatch):
    """Pure path discovery; no site hooks, model imports or subprocesses."""
    import site
    real_getsitepackages = site.getsitepackages
    child = _bootstrap()
    prefix = tmp_path / "original-parent-venv"
    (prefix / "bin").mkdir(parents=True)
    packages = prefix / "lib" / "python3.12" / "site-packages"
    packages.mkdir(parents=True)
    user = tmp_path / "unrelated-user-site"
    user.mkdir()
    base = tmp_path / "original-base-prefix"
    system = base / "lib" / "python3.12" / "site-packages"
    system.mkdir(parents=True)
    (packages / "unexecuted.pth").write_text("import forbidden_startup_hook\n")
    monkeypatch.setattr(child, "sys", SimpleNamespace(path=["/stdlib"],
        executable=str(prefix / "bin" / "python"), base_prefix=str(base), base_exec_prefix=str(base)))
    def forbidden(*args, **kwargs):
        pytest.fail("explicit original prefix consulted user site or executed startup hooks")
    monkeypatch.setattr(site, "getusersitepackages", forbidden)
    monkeypatch.setattr(site, "main", forbidden)
    monkeypatch.setattr(site, "addsitedir", forbidden)
    calls = []
    def explicit_sites(*, prefixes):
        calls.append(prefixes)
        assert prefixes == [str(prefix)]
        return [str(packages)]
    monkeypatch.setattr(site, "getsitepackages", explicit_sites)
    assert child._configure_dependency_paths(parent_prefix=str(prefix)) == (str(packages),)
    assert calls == [[str(prefix)]]
    assert child.sys.path == [str(child.ROOT), "/stdlib", str(packages)]
    with pytest.raises(RuntimeError, match="dependency prefix"):
        child._configure_dependency_paths(parent_prefix=str(tmp_path))
    assert calls == [[str(prefix)]]  # Refusal precedes any alternate discovery.
    # Only fallback directories active in the original parent's known site
    # roots are transferred; their order follows the interpreter site first.
    monkeypatch.setattr(site, "getusersitepackages", lambda: str(user))
    def known_sites(*, prefixes):
        if prefixes == [str(prefix)]:
            return [str(packages)]
        assert prefixes == [str(base), str(base)]
        return [str(system)]
    monkeypatch.setattr(site, "getsitepackages", known_sites)
    child.sys.path[:] = [str(child.ROOT), "/stdlib", str(packages), str(user), str(system)]
    child.sys.prefix = child.sys.exec_prefix = str(base)
    original = child._reviewed_dependency_paths(str(prefix))
    assert child.sys.prefix == child.sys.exec_prefix == str(base)  # Parent capture is PURE.
    assert original == (str(packages), str(user), str(system))
    child.sys.path[:] = ["/stdlib"]
    assert child._configure_dependency_paths(parent_prefix=str(prefix), parent_paths=list(original)) == original
    assert child.sys.path == [str(child.ROOT), "/stdlib", *original]
    assert child.sys.prefix == child.sys.exec_prefix == str(prefix)  # Explicit CHILD setup restores.
    with pytest.raises(RuntimeError, match="interpreter site directories first"):
        child._configure_dependency_paths(parent_prefix=str(prefix), parent_paths=[str(user), str(packages)])
    with pytest.raises(RuntimeError, match="unknown or repeated"):
        child._configure_dependency_paths(parent_prefix=str(prefix), parent_paths=[str(packages), str(tmp_path)])
    # The original no-argument/default v8 branch still asks for user then
    # ordinary global site directories, in exactly its previous order.
    legacy = []
    child.sys.path[:] = ["/stdlib"]
    monkeypatch.setattr(site, "getusersitepackages", lambda: legacy.append("user") or str(user))
    def legacy_sites():
        legacy.append("site")
        return [str(packages)]
    monkeypatch.setattr(site, "getsitepackages", legacy_sites)
    assert child._configure_dependency_paths() == (str(user), str(packages))
    assert legacy == ["user", "site"]
    assert child.sys.path == [str(child.ROOT), "/stdlib", str(user), str(packages)]
    # Exercise the ACTUAL stdlib algorithm with detached interpreter metadata,
    # rather than a path-returning mock. This reproduces -I -S losing the venv
    # metadata on Debian while leaving the pytest interpreter itself untouched.
    import sys
    import types
    actual_prefixes = (sys.prefix, sys.exec_prefix, sys.base_prefix, sys.base_exec_prefix)
    isolated = SimpleNamespace(path=["/stdlib"], executable=str(prefix / "bin" / "python"),
        prefix=str(base), exec_prefix=str(base), base_prefix=str(base), base_exec_prefix=str(base),
        version_info=sys.version_info, platlibdir=getattr(sys, "platlibdir", "lib"))
    namespace = dict(real_getsitepackages.__globals__, sys=isolated)
    real_site_algorithm = types.FunctionType(real_getsitepackages.__code__, namespace,
        real_getsitepackages.__name__, real_getsitepackages.__defaults__, real_getsitepackages.__closure__)
    monkeypatch.setattr(child, "sys", isolated)
    monkeypatch.setattr(site, "getsitepackages", real_site_algorithm)
    monkeypatch.setattr(site, "getusersitepackages", forbidden)
    discovered = child._configure_dependency_paths(parent_prefix=str(prefix))
    assert str(packages) in discovered
    assert isolated.prefix == isolated.exec_prefix == str(prefix)
    assert isolated.base_prefix == isolated.base_exec_prefix == str(base)
    assert (sys.prefix, sys.exec_prefix, sys.base_prefix, sys.base_exec_prefix) == actual_prefixes



def test_reviewed_network_fixed_soname_skips_external_library_resolver(monkeypatch):
    """Observe the real lookup branch before any irreversible filter is loaded."""
    child = _bootstrap()
    spec = importlib.util.spec_from_file_location("_test_reviewed_fixed_network_lookup", child.NETWORK_SCRIPT)
    network = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(network)
    observed = []
    stopped = RuntimeError("observed fixed seccomp load before filter")
    def forbidden(*args, **kwargs):
        pytest.fail("reviewed network lookup used subprocess-capable resolver")
    def direct_library(name, *, use_errno):
        observed.append(name)
        assert name == "libseccomp.so.2" and use_errno is True
        raise stopped
    monkeypatch.setattr(network.ctypes.util, "find_library", forbidden)
    monkeypatch.setattr(network.ctypes, "CDLL", direct_library)
    with pytest.raises(RuntimeError) as captured:
        network._deny_network(fixed_seccomp=True)
    assert captured.value is stopped and observed == ["libseccomp.so.2"]
    # The unchanged default still uses the original resolver and refusal.
    requested = []
    monkeypatch.setattr(network.ctypes.util, "find_library", lambda name: requested.append(name))
    with pytest.raises(RuntimeError, match="requires libseccomp"):
        network._deny_network()
    assert requested == ["seccomp"] and observed == ["libseccomp.so.2"]


@pytest.fixture
def fixed_f18(synthetic, tmp_path):
    """Metadata-only fixed jobs; Popen is the existing synthetic pipe fixture.

    No physical training asset is opened and no numerical implementation is
    imported or executed. These assertions do not establish native admission.
    """
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_f18_conditions_v1 as f18

    old = synthetic.executor
    executor = module._CampaignProcessExecutor(record_start=old._record_start,
        record_child=old._record_child, timeout_seconds=30, max_workers=1)
    source_root = Path(f18.__file__).resolve().parents[3]

    def make_job(index=0):
        root = tmp_path / ("f18-" + str(index))
        root.mkdir()
        def ref(name):
            path = root / name
            path.write_bytes(b"{}")
            return module.describe(path)
        source_pins = {}
        for relative, expected in f18.REQUIRED_SOURCE_SHA256.items():
            raw = (source_root / relative).read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            assert expected is None or digest == expected
            source_pins[relative] = {"bytes": len(raw), "sha256": digest}
        payload = {"schema_version": f18.SCHEMA_VERSION, "run_id": "fixed-f18-" + str(index),
            "output_directory": str(root / "output"), "prepared_inputs": ref("prepared.json"),
            "initial_checkpoint": ref("initial.json"),
            "physical_assets": [{"role": role, **ref("asset-" + str(i) + ".json")}
                                for i, role in enumerate(f18.ASSET_ROLES)],
            "source_pins": source_pins, "margin_weight": 0.25, "max_steps": 2,
            "max_seconds": 1.0, "runtime_contract": None}
        spec = f18.F18JobSpec.from_dict(payload)
        path = root / "job.json"
        path.write_bytes(module.canonical(spec.to_dict()))
        attempt = root / "control"
        attempt.mkdir()
        return spec, module.describe(path), attempt

    value = SimpleNamespace(owner=f18, executor=executor, make_job=make_job,
                            events=synthetic.events, processes=synthetic.processes)
    try:
        yield value
    finally:
        for item in executor._jobs.values():
            module._CampaignProcessExecutor._finish_handles(item)



def _submit_f18(fixture, index=0, **kwargs):
    spec, artifact, attempt = fixture.make_job(index)
    fixture.executor.register_f18(spec, reservation=SyntheticReservation(fixture.events),
        attempt_directory=attempt, job_artifact=artifact, **kwargs)
    future = fixture.executor.submit(spec, lease={"run_id": spec.run_id, "fence": 1}, job_artifact=artifact)
    return spec, artifact, future



def test_fixed_f18_uses_original_eleven_argument_barrier_and_one_worker(fixed_f18):
    spec, _, future = _submit_f18(fixed_f18)
    process = fixed_f18.processes[0]
    assert len(process.argv[4:]) == 11
    assert process.argv[1:3] == ["-I", "-S"]
    assert process.argv[-2:] == ["0", "0"]
    assert process.options["env"]["IPFS_DATASETS_LEGAL_IR_PARALLEL_WORKERS"] == "1"
    assert process.options["env"]["IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS"] == "1"
    assert process.options["start_new_session"] is True
    assert fixed_f18.events.index(("intent", spec.run_id)) < fixed_f18.events.index(("spawn",))
    with pytest.raises(BlockingIOError):
        os.read(process.release_reader, 4)
    fixed_f18.executor.poll()
    assert os.read(process.release_reader, 4) == b"RUN\n"
    assert ("observed", spec.run_id) in fixed_f18.events
    assert not future.done()
    fixed_f18.executor.stop(spec)
    assert future.exception() is not None



@pytest.mark.parametrize("policy", ["workers", "defer_gc", "reduce_targets"])
def test_fixed_f18_rejects_v8_runtime_flags_before_spawn(fixed_f18, policy):
    spec, artifact, attempt = fixed_f18.make_job()
    if policy == "workers":
        fixed_f18.executor.max_workers = 2
    elif policy == "defer_gc":
        fixed_f18.executor.defer_target_hydration_gc = True
    else:
        fixed_f18.executor.reduce_native_targets = True
    with pytest.raises(module.CampaignProcessError):
        fixed_f18.executor.register_f18(spec, reservation=SyntheticReservation(fixed_f18.events),
            attempt_directory=attempt, job_artifact=artifact)
    assert not fixed_f18.processes and not fixed_f18.executor._jobs



def test_fixed_f18_requires_literal_reservation_and_concrete_spec(fixed_f18):
    spec, artifact, attempt = fixed_f18.make_job()
    class DerivedReservation(SyntheticReservation):
        pass
    with pytest.raises(module.CampaignProcessError, match="literal original"):
        fixed_f18.executor.register_f18(spec, reservation=DerivedReservation(fixed_f18.events),
            attempt_directory=attempt, job_artifact=artifact)
    with pytest.raises(module.CampaignProcessError, match="fixed F18 job"):
        fixed_f18.executor.register_f18(SimpleNamespace(**spec.to_dict()),
            reservation=SyntheticReservation(fixed_f18.events), attempt_directory=attempt,
            job_artifact=artifact)
    assert not fixed_f18.processes and not fixed_f18.executor._jobs



def test_fixed_f18_rejects_different_serialized_job_before_spawn(fixed_f18):
    spec, artifact, attempt = fixed_f18.make_job()
    changed = spec.to_dict()
    changed["run_id"] = "another-fixed-f18-job"
    Path(artifact["path"]).write_bytes(module.canonical(changed))
    artifact = module.describe(artifact["path"])
    with pytest.raises(module.CampaignProcessError, match="registered job bytes differ"):
        fixed_f18.executor.register_f18(spec, reservation=SyntheticReservation(fixed_f18.events),
            attempt_directory=attempt, job_artifact=artifact)
    assert not fixed_f18.processes and not fixed_f18.executor._jobs



def test_fixed_f18_rejects_source_drift_before_dispatch(fixed_f18, monkeypatch):
    spec, artifact, attempt = fixed_f18.make_job()
    fixed_f18.executor.register_f18(spec, reservation=SyntheticReservation(fixed_f18.events),
        attempt_directory=attempt, job_artifact=artifact)
    assert any(item["path"] == str(module.F18_SCRIPT.resolve()) for item in fixed_f18.executor._sources)
    ordinary = module.verify
    def changed_source(item, limit):
        if item["path"] == str(module.F18_SCRIPT.resolve()):
            raise RuntimeError("fixed F18 source changed")
        return ordinary(item, limit)
    monkeypatch.setattr(module, "verify", changed_source)
    with pytest.raises(RuntimeError, match="fixed F18 source changed"):
        fixed_f18.executor.submit(spec, lease={"run_id": spec.run_id}, job_artifact=artifact)
    assert not fixed_f18.processes



def test_fixed_f18_observed_callback_failure_never_releases_compute(fixed_f18):
    spec, _, future = _submit_f18(fixed_f18)
    def refuse(*_args):
        raise RuntimeError("F18 child identity was not durable")
    fixed_f18.executor._record_child = refuse
    fixed_f18.executor.poll()
    assert future.done() and "not durable" in str(future.exception())
    assert not fixed_f18.executor._jobs[spec.run_id]["released"]
    assert not fixed_f18.processes[0].live



def test_fixed_f18_bad_receipt_cannot_be_a_success(fixed_f18):
    spec, _, future = _submit_f18(fixed_f18)
    fixed_f18.executor.poll()
    output = Path(spec.output_directory)
    output.mkdir()
    (output / "receipt.json").write_bytes(module.canonical({"fixture_only": True}))
    process = fixed_f18.processes[0]
    process.returncode, process.live = 0, False
    fixed_f18.executor.poll()
    assert future.done() and future.exception() is not None



def test_original_v8_dispatch_does_not_import_or_require_f18_owner(synthetic, monkeypatch):
    def forbidden():
        raise AssertionError("v8 cannot depend on the optional F18 route")
    monkeypatch.setattr(module, "_f18_owner", forbidden)
    spec, _, future = _submit(synthetic)
    assert synthetic.processes[0].options["env"]["IPFS_DATASETS_LEGAL_IR_PARALLEL_WORKERS"] == "3"
    synthetic.executor.poll()
    assert os.read(synthetic.processes[0].release_reader, 4) == b"RUN\n"
    synthetic.executor.stop(spec)
    assert future.exception() is not None



def test_bootstrap_owner_release_failure_prevents_every_fixed_job_import(monkeypatch):
    child = _bootstrap()
    events = []
    monkeypatch.setattr(child, "sys", SimpleNamespace(modules={}, path=[], stderr=io.StringIO(),
                                                     flags=SimpleNamespace(isolated=True, no_site=True)))
    monkeypatch.setattr(child, "_network_denial", lambda _sha: events.append("network") or GUARD)
    monkeypatch.setattr(child, "_identity", lambda: {"pid": 123, "group_pid": 123, "birth": "birth"})
    monkeypatch.setattr(child, "_send_ready", lambda *_args: events.append("ready"))
    monkeypatch.setattr(child.os, "close", lambda _fd: None)
    def no_release(*_args, **_kwargs):
        events.append("release_refused")
        raise RuntimeError("owner did not release compute")
    monkeypatch.setattr(child, "_await_release", no_release)
    monkeypatch.setattr(child, "_run_original", lambda *_args, **_kwargs: events.append("ILLEGAL_JOB_DISPATCH"))
    assert child.main(["/synthetic/job", "a" * 64, "3", "b" * 64, "8", "9",
                       str(os.getppid()), "1", "c" * 64, "0", "0"]) == 1
    assert events == ["network", "ready", "release_refused"]



def _fixed_f18_receipt(fixture, spec, artifact, completed_steps):
    """A closed metadata receipt, not a generated checkpoint or training run."""
    owner, value = fixture.owner, spec.to_dict()
    output = Path(spec.output_directory)
    output.mkdir()
    refs = {}
    for name in ("checkpoint", "report"):
        path = output / (name + ".json")
        path.write_bytes(b"{}")
        refs[name] = module.describe(path)
    complete = completed_steps == value["max_steps"]
    return {"schema_version": owner.RECEIPT_SCHEMA, "run_id": spec.run_id,
        "job_spec_sha256": spec.canonical_sha256, "job_file_sha256": artifact["sha256"],
        "prepared_inputs_sha256": value["prepared_inputs"]["sha256"],
        "initial_checkpoint_file_sha256": value["initial_checkpoint"]["sha256"],
        "profile_source_sha256": owner.PROFILE_SHA256, "margin_weight": value["margin_weight"],
        "requested_steps": value["max_steps"], "completed_steps": completed_steps,
        "initial_progress": {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0},
        "final_progress": {"epochs_completed": completed_steps // 14,
                           "row_cursor": (completed_steps % 14) * 12, "optimizer_steps": completed_steps},
        "reason": "step_limit" if complete else "deadline_before_batch",
        "status": "completed" if complete else "partial", **refs,
        "checkpoint_sha256": "f" * 64, "elapsed_seconds": 0.001,
        "training_executed": completed_steps > 0, "all_requested_steps_completed": complete,
        "prepared_inputs_integrity_only": True, "runtime_contract_sha256": None,
        **{name: False for name in owner.FALSE_FIELDS}}



@pytest.mark.parametrize("completed_steps", [1, 2])
def test_fixed_f18_preserves_valid_partial_and_completed_slice_receipts(fixed_f18, completed_steps):
    spec, artifact, future = _submit_f18(fixed_f18)
    fixed_f18.executor.poll()
    receipt = _fixed_f18_receipt(fixed_f18, spec, artifact, completed_steps)
    (Path(spec.output_directory) / "receipt.json").write_bytes(module.canonical(receipt))
    process = fixed_f18.processes[0]
    process.returncode, process.live = 0, False
    fixed_f18.executor.poll()
    assert future.result() == receipt
    assert future.result()["status"] == ("completed" if completed_steps == 2 else "partial")
    assert future.result()["qualified"] is False
    fixed_f18.executor.retire(spec)



@pytest.mark.parametrize("forgery", ["identity", "progress", "authority", "runtime"])
def test_fixed_f18_rejects_resealed_receipt_forgeries(fixed_f18, forgery):
    spec, artifact, future = _submit_f18(fixed_f18)
    fixed_f18.executor.poll()
    receipt = _fixed_f18_receipt(fixed_f18, spec, artifact, 2)
    if forgery == "identity":
        receipt["job_spec_sha256"] = "0" * 64
    elif forgery == "progress":
        receipt["completed_steps"] = 3
    elif forgery == "authority":
        receipt["native_task_completed"] = True
    else:
        receipt["runtime_contract_sha256"] = "1" * 64
    (Path(spec.output_directory) / "receipt.json").write_bytes(module.canonical(receipt))
    process = fixed_f18.processes[0]
    process.returncode, process.live = 0, False
    fixed_f18.executor.poll()
    assert future.done() and future.exception() is not None



@pytest.mark.parametrize("legacy_flags", [(False, False), (True, False), (False, True)])
def test_post_barrier_f18_dispatch_uses_only_the_fixed_owner(fixed_f18, monkeypatch, legacy_flags):
    from ipfs_datasets_py.logic.autoformal import tree_pin
    owner = fixed_f18.owner
    spec, artifact, _ = fixed_f18.make_job()
    child = _bootstrap()
    events = []
    monkeypatch.setattr(child, "_configure_dependency_paths", lambda: events.append("dependencies"))
    monkeypatch.setattr(tree_pin, "require_workspace_logic_tree", lambda: events.append("tree"))
    def execute(received, *, job_file_sha256):
        assert type(received) is owner.F18JobSpec
        assert received.to_dict() == spec.to_dict()
        assert job_file_sha256 == artifact["sha256"]
        events.append("fixed_f18_dispatch_only_no_compute")
    # Only the new fixed adapter leaf is replaced. No numerical owner runs.
    monkeypatch.setattr(owner, "execute_job", execute)
    if any(legacy_flags):
        with pytest.raises(RuntimeError, match="unsupported fixed F18 execution policy"):
            child._run_original(artifact["path"], artifact["sha256"], artifact["bytes"],
                spec.canonical_sha256, defer_gc=legacy_flags[0], reduce_targets=legacy_flags[1])
        assert events == ["dependencies", "tree"]
    else:
        child._run_original(artifact["path"], artifact["sha256"], artifact["bytes"],
            spec.canonical_sha256, defer_gc=False, reduce_targets=False)
        assert events == ["dependencies", "tree", "fixed_f18_dispatch_only_no_compute"]
