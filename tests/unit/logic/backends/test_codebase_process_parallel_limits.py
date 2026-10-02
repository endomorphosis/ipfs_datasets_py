"""Native Linux launches enforce limits without Python preexec in pool threads."""
from concurrent.futures import ThreadPoolExecutor
import json
import resource
import subprocess
import sys
import threading
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
