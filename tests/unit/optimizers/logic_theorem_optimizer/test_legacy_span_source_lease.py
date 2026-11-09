"""Cooperative census source lifetime; no models, network, or native grants.

AUTOENCODER_RUNNER_TEST_SOURCE may select a review candidate script. All package
imports and the fresh-process parser guard still use this canonical checkout.
"""
from __future__ import annotations

import fcntl
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest


def _root():
    for parent in (Path.cwd(), *Path(__file__).resolve().parents, *Path.cwd().parents):
        for candidate in (parent, parent / "external/ipfs_datasets"):
            if (candidate / "ipfs_datasets_py/logic/autoformal/tree_pin.py").is_file():
                return candidate.resolve()
    raise AssertionError("canonical ipfs_datasets checkout not found")


ROOT = _root()
RUNNER_SOURCE = Path(os.environ.get("AUTOENCODER_RUNNER_TEST_SOURCE",
    ROOT / "scripts/ops/legal_ir/run_legacy_span_cuda.py")).resolve()


@pytest.fixture
def runner(monkeypatch):
    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("source_lease_census_candidate", RUNNER_SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # A candidate is a source-only test overlay, never another package tree.
    monkeypatch.setattr(module, "ROOT", ROOT)
    monkeypatch.setattr(module, "STOP", False)
    monkeypatch.setattr(module, "environment", lambda: None)
    monkeypatch.setattr(module.signal, "signal", lambda *args: None)
    return module


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    return root


def cli(runtime, *extra):
    return ["--runtime-directory", str(runtime), "--scheduler-state", str(runtime / "scheduler.json"),
            "--expected-policy-sha256", "f" * 64, "--source-lease-timeout-seconds", "0", *extra]


def writer_is_excluded(root):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_source_lease as leases
    with pytest.raises(leases.SourceLeaseTimeout):
        with leases.source_lease(root, mode="write", timeout_seconds=0):
            pytest.fail("writer entered while the native owner still had live work or cleanup")


def writer_can_enter(root):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_source_lease import source_lease
    with source_lease(root, mode="write", timeout_seconds=0):
        pass


@pytest.mark.parametrize("outcome", ["success", "startup_failure", "resource_close_failure"])
def test_owner_holds_real_read_lease_through_actual_child_and_native_cleanup(
        runner, repository, tmp_path, monkeypatch, outcome):
    """Exercise the actual owner finally; only native resource authority is fake.

    The real isolated direct child is terminated/waited before the resource
    cleanup hook, and every phase probes the actual shared kernel lock.
    """
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_campaign_resources as resources
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_engine_custody as custody
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_invocation as invocation
    from ipfs_datasets_py.logic.autoformal import span_ingest_runtime as ingest

    monkeypatch.setattr(runner, "ROOT", repository)
    monkeypatch.setattr(runner, "atomic", lambda *args: writer_is_excluded(repository))
    phases, children = [], []
    runtime = tmp_path / "runtime"
    config = SimpleNamespace(total_cpu_slots=64, total_memory_mb=1000000,
        reserved_memory_mb=0, total_child_process_slots=64, reservations=lambda: {})
    def open_scheduler(*args):
        writer_is_excluded(repository)
        phases.append("scheduler")
        return SimpleNamespace(config=config)
    monkeypatch.setattr(existing, "open_existing_scheduler", open_scheduler)

    class Resource:
        def __init__(self, *args, **kwargs):
            self._opened = False
            self.reservation = SimpleNamespace(heartbeat=lambda: True, cancelled=False,
                reservation_id="test-no-native-claim", _update=lambda **kw: writer_is_excluded(repository))
        def open(self):
            writer_is_excluded(repository)
            self._opened = True
            phases.append("resource_open")
        def prepare_engine_bytecode(self):
            return runtime
        def bind_engine_launch(self, pid, digest, *, bytecode_directory):
            writer_is_excluded(repository)
            assert children[0].pid == pid
            phases.append("child_bound")
            return {"test_only": True}
        def check_limits(self):
            writer_is_excluded(repository)
            return {}
        def close(self, *, artifacts_durable):
            assert artifacts_durable is True
            self._check_drained()
            phases.append("resource_close")
            if outcome == "resource_close_failure":
                raise RuntimeError("test resource close failed")
            self._opened = False
        def __exit__(self, *args):
            self._check_drained()
            self._opened = False
            phases.append("resource_exit")
        def _check_drained(self):
            writer_is_excluded(repository)
            if children:
                assert children[0].poll() is not None
                assert "child_drained" in phases

    monkeypatch.setattr(resources, "LegacySpanCampaignResources", Resource)
    real_popen = subprocess.Popen
    def popen(command, **kwargs):
        writer_is_excluded(repository)
        assert command[-1] == "--_engine"
        child = real_popen([sys.executable, "-c", "import sys; sys.stdin.buffer.read(); sys.exit(0)"],
            cwd=repository, env=kwargs["env"], start_new_session=True, stdin=subprocess.PIPE)
        children.append(child)
        # This remains the native owner's isolated direct child.
        assert custody.owned_child_identity(child)["pid"] == child.pid
        phases.append("child_started")
        return child
    monkeypatch.setattr(runner, "subprocess", SimpleNamespace(Popen=popen, PIPE=subprocess.PIPE))
    monkeypatch.setattr(custody, "verify_startup_deadline", lambda started: writer_is_excluded(repository))
    def feed(child, payload, verify):
        verify()
        if outcome != "startup_failure":
            child.stdin.close()
    monkeypatch.setattr(ingest, "_feed_launch", feed)
    def ready(child, launch, verify):
        verify()
        assert child.pid == children[0].pid
        if outcome == "startup_failure":
            assert child.poll() is None
            raise RuntimeError("test startup failed")
        child.wait(timeout=5)
        return {"test_ready": True}
    monkeypatch.setattr(custody, "wait_engine_ready", ready)
    def stop_child(child, identity):
        writer_is_excluded(repository)
        invocation._terminate(child, identity)
        child.wait(timeout=5)
        phases.append("child_drained")
    monkeypatch.setattr(runner, "stop_child", stop_child)

    try:
        if outcome == "success":
            assert runner.main(cli(runtime)) == 0
        else:
            with pytest.raises(RuntimeError, match="test startup failed|test resource close failed"):
                runner.main(cli(runtime))
        assert phases[0] == "scheduler"
        assert phases.index("child_started") < phases.index("child_drained")
        assert phases[-1] == ("resource_close" if outcome == "success" else "resource_exit")
        writer_can_enter(repository)
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=5)


def test_waiting_writer_does_not_deadlock_hidden_engine_dispatch(runner, repository, tmp_path, monkeypatch):
    """Reproduce the fair-turnstile state that would deadlock a nested reader."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_source_lease as leases
    monkeypatch.setattr(runner, "ROOT", repository)
    calls = []
    def execute(args, argv):
        assert args._engine is True
        calls.append(argv)
        return 7
    monkeypatch.setattr(runner, "_run", execute)
    argv = cli(tmp_path, "--_engine")
    code = """
import sys
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_source_lease import source_lease
with source_lease(sys.argv[1], mode="write", timeout_seconds=5):
    print("writer_entered", flush=True)
"""
    child = None
    try:
        with leases.source_lease(repository, mode="read", timeout_seconds=0):
            child = subprocess.Popen([sys.executable, "-B", "-c", code, str(repository)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, (str(ROOT), os.environ.get("PYTHONPATH", "")))),
                         IPFS_DATASETS_PY_MINIMAL_IMPORTS="1",
                         IPFS_DATASETS_AUTO_INSTALL="0", IPFS_KIT_AUTO_INSTALL_DEPS="0"))
            # The writer has actually taken admission and is blocked on our
            # source lock; a second read acquisition now cannot pass it.
            deadline = time.monotonic() + 5
            with (repository / leases.CONTROL_DIRECTORY / "admission.lock").open("rb") as probe:
                while True:
                    try:
                        fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
                    except BlockingIOError:
                        break
                    assert child.poll() is None, "writer exited before reaching its turnstile"
                    assert time.monotonic() < deadline, "writer did not reach its turnstile"
                    time.sleep(0.01)
            def must_not_reacquire(*args, **kwargs):
                pytest.fail("engine attempted nested source admission")
            with monkeypatch.context() as patch:
                patch.setattr(leases, "source_lease", must_not_reacquire)
                assert runner.main(argv) == 7
                assert calls == [argv]
                failure = RuntimeError("test engine failure")
                def fail(args, argv):
                    raise failure
                patch.setattr(runner, "_run", fail)
                with pytest.raises(RuntimeError) as error:
                    runner.main(argv)
                assert error.value is failure
            assert child.poll() is None
        stdout, stderr = child.communicate(timeout=5)
        assert child.returncode == 0, stderr
        assert stdout == b"writer_entered\n"
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_source_wait_times_out_before_scheduler_or_native_owner_work(runner, repository, tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_source_lease as leases
    monkeypatch.setattr(runner, "ROOT", repository)
    monkeypatch.setattr(runner, "_run", lambda *args: pytest.fail("lock wait admitted native work"))
    with leases.source_lease(repository, mode="write", timeout_seconds=0):
        with pytest.raises(leases.SourceLeaseTimeout):
            runner.main(cli(tmp_path))
    writer_can_enter(repository)


def test_cancelled_source_wait_does_not_start_native_work(runner, repository, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", repository)
    monkeypatch.setattr(runner, "STOP", True)
    monkeypatch.setattr(runner, "_run", lambda *args: pytest.fail("cancelled owner started native work"))
    with pytest.raises(ValueError, match="cancelled while waiting"):
        runner.main(cli(tmp_path))
    writer_can_enter(repository)


@pytest.mark.parametrize("value", ["-1", "nan", "inf", "-inf"])
def test_source_wait_must_be_finite_nonnegative(runner, tmp_path, value):
    with pytest.raises(SystemExit) as error:
        runner.arguments(cli(tmp_path, "--source-lease-timeout-seconds=" + value))
    assert error.value.code == 2


def test_source_wait_does_not_set_a_productive_deadline_or_change_parent_argv(runner, repository, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", repository)
    argv = cli(tmp_path, "--source-lease-timeout-seconds", "0.01")
    def execute(args, passed_argv):
        assert passed_argv is None
        assert args.max_batches == 0
        assert args.source_lease_timeout_seconds == 0.01
        time.sleep(0.03)  # Productive work can exceed source-admission waiting time.
        writer_is_excluded(repository)
        return 3
    monkeypatch.setattr(runner.sys, "argv", [str(RUNNER_SOURCE), *argv])
    monkeypatch.setattr(runner, "_run", execute)
    assert runner.main() == 3
    writer_can_enter(repository)


def test_fresh_owner_keeps_actual_canonical_parser_and_complete_source_guard(tmp_path):
    """No HACC imports, replacement package, monkeypatched guard, or CUDA."""
    code = r'''
import importlib.util, json, os, sys
from pathlib import Path
root, candidate, runtime = map(Path, sys.argv[1:])
sys.path.insert(0, str(root))
assert not any(name == "ipfs_datasets_py" or name.startswith("ipfs_datasets_py.") for name in sys.modules)
spec = importlib.util.spec_from_file_location("fresh_census_source_only", candidate)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
runner.ROOT = root  # Candidate runner only; no package module is redirected.
source_lock = root / "workspace/control-plane/source-leases/source.lock"
def own_source_flock_modes():
    info = source_lock.stat()
    identity = (os.major(info.st_dev), os.minor(info.st_dev), info.st_ino)
    modes = []
    for raw in Path("/proc/locks").read_text().splitlines():
        fields = raw.split()
        # Pending ("->") entries and locks owned by other readers do not
        # establish this process's source ownership or its eventual release.
        if len(fields) < 8 or fields[1] != "FLOCK" or fields[4] != str(os.getpid()):
            continue
        device_major, device_minor, inode = fields[5].split(":")
        observed = (int(device_major, 16), int(device_minor, 16), int(inode))
        if observed == identity:
            modes.append(fields[3])
    return sorted(modes)
def observe(args, argv):
    assert own_source_flock_modes() == ["READ"], "this fresh owner has no canonical source read lock"
    import ipfs_datasets_py
    assert Path(ipfs_datasets_py.__file__).resolve() == root / "ipfs_datasets_py/__init__.py"
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_source_lease import source_lease, SourceLeaseTimeout
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legacy_span_cuda import _source_snapshot
    paths = require_workspace_logic_tree()
    assert all(root in Path(path).parents for path in paths.values())
    before, after = _source_snapshot(), _source_snapshot()
    assert before == after and before["python_file_count"] > 0
    assert before["package_root"] == str(root / "ipfs_datasets_py")
    try:
        with source_lease(root, mode="write", timeout_seconds=0):
            raise AssertionError("canonical writer entered during canonical owner work")
    except SourceLeaseTimeout:
        pass
    print(json.dumps({"canonical_paths": paths, "source": before, "candidate": str(candidate)}), flush=True)
    return 0
runner._run = observe
assert runner.main(["--runtime-directory", str(runtime), "--scheduler-state", str(runtime / "unused.json"),
    "--expected-policy-sha256", "f" * 64, "--source-lease-timeout-seconds", "1"]) == 0
# Other legitimate owners may still read this shared tree. Prove this
# process released its own descriptor without demanding global exclusivity.
assert own_source_flock_modes() == [], "this fresh owner retained its source flock after cleanup"
'''
    environment = dict(os.environ,
        PYTHONPATH=os.pathsep.join(filter(None, (str(ROOT), os.environ.get("PYTHONPATH", "")))),
        PYTHONDONTWRITEBYTECODE="1",
        IPFS_DATASETS_PY_MINIMAL_IMPORTS="1", IPFS_DATASETS_AUTO_INSTALL="0",
        IPFS_KIT_AUTO_INSTALL_DEPS="0", IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI="0",
        TRANSFORMERS_OFFLINE="1", HF_HUB_OFFLINE="1")
    result = subprocess.run([sys.executable, "-B", "-c", code, str(ROOT), str(RUNNER_SOURCE), str(tmp_path)],
        cwd=ROOT, env=environment, text=True, capture_output=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr + result.stdout
    observations = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    observation = next(row for row in observations if "canonical_paths" in row)
    assert observation["source"]["package_root"] == str(ROOT / "ipfs_datasets_py")
    assert len(observation["canonical_paths"]) == 3
