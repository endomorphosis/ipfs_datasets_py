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
        path.symlink_to(tmp_path, target_is_directory=True)
    else:
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
