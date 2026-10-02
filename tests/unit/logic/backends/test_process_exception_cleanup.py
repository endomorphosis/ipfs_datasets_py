"""Exceptions keep ownership of real separate-session native descendants."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest

from ipfs_datasets_py.logic.backends import process as module

pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux birth identities and sessions')


def identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return int(fields[19]), fields[0]
    except (FileNotFoundError, ProcessLookupError):
        return None


def write_identity():
    return ("fields=pathlib.Path('/proc/self/stat').read_text().rsplit(')',1)[1].split(); "
            "pathlib.Path(sys.argv[1]).write_text(json.dumps({'pid':os.getpid(),'birth':int(fields[19]),'group':os.getpgrp()})); ")


@pytest.fixture
def native_tree(tmp_path):
    prefix = 'import os,sys,time,pathlib,json,signal,subprocess; '
    leaf = prefix + write_identity() + 'signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)'
    middle = (prefix + write_identity() + 'signal.signal(signal.SIGTERM,signal.SIG_IGN); '
              f'subprocess.Popen([sys.executable,"-c",{leaf!r},{str(tmp_path / "leaf.json")!r}],start_new_session=True); time.sleep(60)')
    leader = (prefix + write_identity()
              + f'subprocess.Popen([sys.executable,"-c",{middle!r},{str(tmp_path / "middle.json")!r}],start_new_session=True); '
              + f'leaf=pathlib.Path({str(tmp_path / "leaf.json")!r})\n'
                'while not leaf.exists(): time.sleep(.005)\n'
              + f'pathlib.Path({str(tmp_path / "ready")!r}).write_text("ready"); time.sleep(60)')
    yield tmp_path, leader
    # Failed regressions must not leave work behind or signal a reused PID.
    for name in ('leader', 'middle', 'leaf'):
        path = tmp_path / (name + '.json')
        if path.exists():
            record = json.loads(path.read_text())
            current = identity(record['pid'])
            if current is not None and current[0] == record['birth'] and current[1] != 'Z':
                try:
                    os.kill(record['pid'], signal.SIGKILL)
                except ProcessLookupError:
                    pass


def wait_ready(root):
    deadline = time.monotonic() + 5
    while not (root / 'ready').exists():
        if time.monotonic() >= deadline:
            pytest.fail('native descendants did not become ready')
        time.sleep(.005)


def run_tree(native_tree, *, cancellation=None, executor=None, memory=False):
    root, source = native_tree
    return module.BoundedToolRunner(workspace_root=root / 'workspaces', executor=executor).run(
        module.ToolRunRequest(argv=(sys.executable, '-c', source, str(root / 'leader.json')),
            limits=module.ToolRunLimits(timeout_seconds=10, termination_grace_seconds=.08,
                resident_memory_bytes=1024**3 if memory else None)), cancellation=cancellation)


def assert_drained(root):
    assert (root / 'ready').exists()
    groups = set()
    for name in ('leader', 'middle', 'leaf'):
        record = json.loads((root / (name + '.json')).read_text())
        groups.add(record['group'])
        current = identity(record['pid'])
        assert current is None or current[0] != record['birth'] or current[1] == 'Z', record
    assert len(groups) == 3
    assert not list((root / 'workspaces').iterdir())


@pytest.mark.parametrize('exception_type', [KeyboardInterrupt, SystemExit, RuntimeError, OSError])
def test_raising_cancellation_callback_drains_sessions_and_preserves_exception(native_tree, exception_type):
    root, _ = native_tree
    original = exception_type('original interruption')
    processes, raised = [], []
    before_fds = {path.name for path in Path('/proc/self/fd').iterdir()}

    def spawn(*args, **kwargs):
        process = subprocess.Popen(*args, **kwargs)
        processes.append(process)
        return process

    class Signal:
        def is_set(self):
            if (root / 'ready').exists():
                raise original
            return False

    class ObservedExecutor(module.SubprocessExecutor):
        def execute(self, *args, **kwargs):
            try:
                return super().execute(*args, **kwargs)
            except BaseException as error:
                raised.append(error)
                raise

    executor = ObservedExecutor(popen=spawn)
    if issubclass(exception_type, Exception):
        result = run_tree(native_tree, cancellation=Signal(), executor=executor)
        assert not result.ok and 'original interruption' in result.error
    else:
        with pytest.raises(exception_type) as caught:
            run_tree(native_tree, cancellation=Signal(), executor=executor)
        assert caught.value is original
    assert raised == [original]
    assert len(processes) == 1 and processes[0].poll() is not None
    assert processes[0].stdout.closed and processes[0].stderr.closed
    assert_drained(root)
    assert {path.name for path in Path('/proc/self/fd').iterdir()} == before_fds


def test_raising_rss_sampler_drains_sessions(native_tree, monkeypatch):
    root, _ = native_tree
    original = module._LinuxDescendantTracker.resident_bytes

    def sample(tracker):
        if (root / 'ready').exists():
            raise RuntimeError('sampler failed')
        return original(tracker)

    monkeypatch.setattr(module._LinuxDescendantTracker, 'resident_bytes', sample)
    result = run_tree(native_tree, memory=True)
    assert not result.ok and 'sampler failed' in result.error
    assert_drained(root)


@pytest.mark.parametrize('failed_start', [1, 2])
def test_reader_start_failure_cleans_partially_initialized_workers(native_tree, monkeypatch, failed_start):
    root, _ = native_tree
    actual = threading.Thread
    workers = []

    class FailingStart(actual):
        def start(self):
            workers.append(self)
            if len(workers) == failed_start:
                wait_ready(root)
                raise RuntimeError('reader start failed')
            return super().start()

    monkeypatch.setattr(module.threading, 'Thread', FailingStart)
    result = run_tree(native_tree)
    assert not result.ok and 'reader start failed' in result.error
    assert all(not worker.is_alive() for worker in workers)
    assert_drained(root)


def test_tracker_initialization_failure_retries_discovery_before_parent_signal(native_tree, monkeypatch):
    root, _ = native_tree
    actual = module._LinuxDescendantTracker
    attempts = []

    def initialize(pid):
        attempts.append(pid)
        if len(attempts) == 1:
            wait_ready(root)
            raise RuntimeError('tracker initialization failed')
        return actual(pid)

    monkeypatch.setattr(module, '_LinuxDescendantTracker', initialize)
    result = run_tree(native_tree)
    assert not result.ok and 'tracker initialization failed' in result.error
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    assert_drained(root)


def test_cleanup_failure_notes_survive_ordinary_executor_error(native_tree, monkeypatch):
    root, _ = native_tree

    class Signal:
        def is_set(self):
            if (root / 'ready').exists():
                raise RuntimeError('primary callback failure')
            return False

    def failed_drain(*args):
        raise OSError('synthetic drain failure')

    monkeypatch.setattr(module._LinuxDescendantTracker, 'drain', failed_drain)
    result = run_tree(native_tree, cancellation=Signal())
    assert not result.ok and 'primary callback failure' in result.error
    assert 'bounded process cleanup: drain descendants: OSError' in result.error
    assert_drained(root)
