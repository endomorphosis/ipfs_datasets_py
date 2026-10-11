"""Native Linux launches enforce limits without Python preexec in pool threads."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import resource
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.backends import codebase_process as module

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux prlimit qualification")

LIMIT_SCRIPT = """import json, resource, time
print(json.dumps({name: list(resource.getrlimit(getattr(resource, 'RLIMIT_' + name)))
                  for name in ('CORE', 'FSIZE', 'CPU', 'AS')}), flush=True)
time.sleep(0.15)
"""


@pytest.mark.parametrize("file_limit", [True, False])
def test_native_limit_inheritance_and_no_python_preexec(file_limit):
    observed = []
    def popen(argv, **kwargs):
        observed.append((argv, kwargs))
        return subprocess.Popen(argv, **kwargs)
    runner = module.BoundedToolRunner(executor=module.SubprocessExecutor(popen=popen))
    limits = module.ToolRunLimits(timeout_seconds=3, cpu_seconds=1.2,
        memory_bytes=256 * 1024 * 1024, max_input_bytes=1024, max_output_bytes=4096,
        max_workspace_bytes=8192, enforce_file_size_limit=file_limit)
    result = module.run_bounded_stdin_tool([sys.executable, "-c", LIMIT_SCRIPT], "", runner=runner, limits=limits)
    assert result.returncode == 0, result
    actual = json.loads(result.stdout)
    assert actual == {"CORE": [0, 0], "FSIZE": [8192, 8192] if file_limit else list(resource.getrlimit(resource.RLIMIT_FSIZE)),
                      "CPU": [2, 2], "AS": [256 * 1024 * 1024] * 2}
    argv, kwargs = observed[0]
    assert argv[0] == module._linux_prlimit_path()
    assert argv[1] == "--core=0:0" and "--cpu=2:2" in argv
    assert ("--fsize=8192:8192" in argv) is file_limit
    assert kwargs["preexec_fn"] is None and kwargs["start_new_session"] is True
    assert kwargs["shell"] is False
    assert result.command == (sys.executable, "-c", LIMIT_SCRIPT)
    assert result.workspace_cleaned


def test_concurrent_native_children_overlap_and_all_inherit_limits():
    lock = threading.Lock()
    processes = []
    overlapping = []
    def popen(argv, **kwargs):
        assert kwargs["preexec_fn"] is None
        process = subprocess.Popen(argv, **kwargs)
        with lock:
            processes.append(process)
            overlapping.append(sum(item.poll() is None for item in processes))
        return process
    runner = module.BoundedToolRunner(executor=module.SubprocessExecutor(popen=popen))
    limits = module.ToolRunLimits(timeout_seconds=3, cpu_seconds=1, memory_bytes=256 * 1024 * 1024,
                                 max_input_bytes=1024, max_output_bytes=4096, max_workspace_bytes=8192)
    def run(_):
        return module.run_bounded_stdin_tool([sys.executable, "-c", LIMIT_SCRIPT], "", runner=runner, limits=limits)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(run, range(8)))
    assert 2 <= max(overlapping) <= 4
    assert len(processes) == 8 and all(item.poll() is not None for item in processes)
    for result in results:
        assert result.returncode == 0 and result.workspace_cleaned
        assert json.loads(result.stdout)["CPU"] == [1, 1]
        assert json.loads(result.stdout)["AS"] == [256 * 1024 * 1024] * 2


def test_missing_trusted_helper_fails_before_any_launch(monkeypatch):
    def missing():
        raise module.ToolProcessError("trusted helper missing")
    monkeypatch.setattr(module, "_linux_prlimit_path", missing)
    def forbidden(*args, **kwargs):
        pytest.fail("missing limit helper launched an unbounded child")
    runner = module.BoundedToolRunner(executor=module.SubprocessExecutor(popen=forbidden))
    result = module.run_bounded_stdin_tool([sys.executable, "-c", "print(1)"], "", runner=runner)
    assert result.returncode is None and "trusted helper missing" in result.error
    assert result.workspace_cleaned


def test_native_timeout_still_terminates_child_group():
    result = module.run_bounded_stdin_tool([sys.executable, "-c", "import time; time.sleep(30)"], "",
        limits=module.ToolRunLimits(timeout_seconds=0.1, cpu_seconds=1, memory_bytes=256 * 1024 * 1024))
    assert result.timed_out and result.process_tree_terminated and result.workspace_cleaned


@pytest.mark.parametrize("interrupt_cleanup", [False, True])
def test_outer_alarm_preserves_exception_and_drains_native_child_group(tmp_path, monkeypatch, interrupt_cleanup):
    """The supervisor's outer deadline raises outside the ordinary cancel API."""
    class RefreshExpired(BaseException):
        pass

    original = RefreshExpired("original outer refresh deadline")
    secondary = KeyboardInterrupt("secondary alarm during cleanup")
    alarms = []
    ready = tmp_path / "ready"
    identities = tmp_path / "identities.json"
    workspaces = tmp_path / "workspaces"
    leaf = (
        "import os,signal,time,pathlib,json; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        "birth=int(pathlib.Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()[19]); "
        f"pathlib.Path({str(identities)!r}).write_text(json.dumps([os.getpid(),birth])); "
        f"pathlib.Path({str(ready)!r}).write_text('ready'); time.sleep(30)"
    )
    leader = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{leaf!r}]); time.sleep(30)"
    processes, timer_errors = [], []
    timer_finished = threading.Event()

    def spawn(*args, **kwargs):
        process = subprocess.Popen(*args, **kwargs)
        processes.append(process)
        return process

    def expire_after_child_ready():
        end = time.monotonic() + 5
        while not ready.exists() and not timer_finished.is_set() and time.monotonic() < end:
            time.sleep(.005)
        if ready.exists() and not timer_finished.is_set():
            signal.setitimer(signal.ITIMER_REAL, .02)
        elif not timer_finished.is_set():
            timer_errors.append("native grandchild did not become ready")

    def expire(_signum, _frame):
        alarms.append(True)
        raise original if len(alarms) == 1 else secondary

    if interrupt_cleanup:
        def interrupted_termination(*args, **kwargs):
            signal.setitimer(signal.ITIMER_REAL, .01)
            time.sleep(1)
            pytest.fail("second alarm failed to interrupt cleanup")
        monkeypatch.setattr(module, "_terminate_process_tree", interrupted_termination)

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    assert previous_timer == (0., 0.), "qualification must not replace an active caller alarm"
    watcher = threading.Thread(target=expire_after_child_ready, daemon=True)
    runner = module.BoundedToolRunner(workspace_root=workspaces,
        executor=module.SubprocessExecutor(popen=spawn))
    try:
        signal.signal(signal.SIGALRM, expire)
        watcher.start()
        with pytest.raises(RefreshExpired) as caught:
            module.run_bounded_stdin_tool([sys.executable, "-c", leader], "", runner=runner,
                limits=module.ToolRunLimits(timeout_seconds=10, termination_grace_seconds=.08,
                    memory_bytes=256 * 1024**2))
        assert caught.value is original
        if interrupt_cleanup:
            assert len(alarms) == 2
            assert "bounded process cleanup: terminate leader: KeyboardInterrupt" in original.__notes__
        else:
            assert len(alarms) == 1
        assert not timer_errors and ready.exists()
        assert len(processes) == 1 and processes[0].poll() is not None
        assert processes[0].stdout.closed and processes[0].stderr.closed
        end = time.monotonic() + 1
        while module._living_group_descendants(processes[0].pid, processes[0].pid) and time.monotonic() < end:
            time.sleep(.005)
        assert not module._living_group_descendants(processes[0].pid, processes[0].pid)
        assert not list(workspaces.iterdir())
    finally:
        timer_finished.set()
        watcher.join(timeout=1)
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        # A failing regression must not itself leave a sleeping worker behind.
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)
        if identities.exists():
            pid, birth = json.loads(identities.read_text())
            try:
                fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
                if int(fields[19]) == birth and fields[0] != "Z":
                    os.kill(pid, signal.SIGKILL)
            except (FileNotFoundError, ProcessLookupError):
                pass
