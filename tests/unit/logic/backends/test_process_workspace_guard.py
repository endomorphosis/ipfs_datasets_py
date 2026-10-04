"""Sampled workspace limits, with bounded Python helpers and private admission.

This does not qualify a filesystem quota, writes outside the workspace, open
unlinked files, or protection against every change between sampling intervals.
"""
from dataclasses import replace
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process as module, resource_admission as admission
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


MIB = 1024**2
pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux directory-fd workspace guard')


def limits(**changes):
    return module.ToolRunLimits(**{'timeout_seconds': 4, 'termination_grace_seconds': .08,
        'cpu_seconds': 2, 'memory_bytes': 256*MIB, 'resident_memory_bytes': 128*MIB,
        'max_input_bytes': 1, 'max_output_bytes': 2048, 'max_workspace_bytes': 4096,
        'max_workspace_entries': 32, 'max_workspace_depth': 8, **changes})


def denied(*args, **kwargs):
    pytest.fail('workspace fixture reached a shared scheduler or an unapproved executable')


@pytest.fixture(autouse=True)
def no_shared_owner_and_only_explicit_python_launches(monkeypatch):
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', denied)
    original = subprocess.Popen
    def python_only(argv, *args, **kwargs):
        command = list(argv)
        if '--' in command:
            separator = command.index('--')
            assert Path(command[0]).name == 'prlimit'
            command = command[separator+1:]
        assert Path(command[0]).resolve() == Path(sys.executable).resolve(), command
        assert command[1] == '-c', command
        assert kwargs.get('shell') is False
        return original(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', denied)
    monkeypatch.setitem(module.SubprocessExecutor.__init__.__kwdefaults__, 'popen', python_only)


@pytest.fixture
def private_owner(tmp_path, monkeypatch):
    healthy = ProofHostResources(8, 8192, 8192, pid_task_limit=8192, available_pid_tasks=8192)
    owner = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path/'private-workspace-pool.json', proof_resource_sampler=lambda: healthy,
        total_cpu_slots=4, total_memory_mb=1024, total_child_process_slots=8,
        proof_memory_headroom_mb=64, lane_reservations={}, auto_renew_leases=False,
        poll_interval_seconds=.002, proof_backoff_seconds=.01))
    workspaces, leases = [], []
    original_write = module.BoundedToolRunner._write_inputs
    def write(workspace, request):
        workspaces.append(workspace)
        return original_write(workspace, request)
    monkeypatch.setattr(module.BoundedToolRunner, '_write_inputs', staticmethod(write))
    acquire = owner.acquire
    def record(*args, **kwargs):
        lease = acquire(*args, **kwargs)
        leases.append(lease)
        return lease
    monkeypatch.setattr(owner, 'acquire', record)
    yield SimpleNamespace(owner=owner, workspaces=workspaces, leases=leases, root=tmp_path/'runs')
    assert owner.snapshot()['active_lease_count'] == owner.snapshot()['waiting_request_count'] == 0
    assert all(lease.released for lease in leases)
    assert all(not path.exists() for path in workspaces)


@pytest.mark.parametrize('field', ['max_workspace_entries', 'max_workspace_depth'])
@pytest.mark.parametrize('value', [True, False, 0, -1, 1.5, '64', None])
def test_workspace_scan_limits_require_positive_exact_integers(field, value):
    with pytest.raises(module.ToolProcessError, match=field):
        module.ToolRunLimits(**{field: value})


@pytest.mark.parametrize('field,maximum', [('max_workspace_entries', 1_000_000),
                                          ('max_workspace_depth', 256)])
def test_workspace_scan_work_has_a_finite_configuration_ceiling(field, maximum):
    assert getattr(module.ToolRunLimits(**{field: maximum}), field) == maximum
    with pytest.raises(module.ToolProcessError, match=field):
        module.ToolRunLimits(**{field: maximum+1})


def test_workspace_scan_is_enabled_by_default():
    value = module.ToolRunLimits()
    assert value.max_workspace_entries == 16384 and value.max_workspace_depth == 64


def test_exact_byte_and_entry_bounds_are_accepted_then_one_byte_refuses(tmp_path):
    (tmp_path/'a').write_bytes(b'a'*2048)
    (tmp_path/'b').write_bytes(b'b'*2048)
    bound = limits(max_workspace_entries=2)
    exact = module._inspect_workspace(tmp_path, bound)
    assert exact.bytes_used == 4096 and exact.entries == 2
    assert not exact.limit_exceeded and not exact.error and not exact.interrupted
    with (tmp_path/'b').open('ab') as stream:
        stream.write(b'x')
    exceeded = module._inspect_workspace(tmp_path, bound)
    assert exceeded.limit_exceeded and exceeded.bytes_used > 4096


def test_many_empty_files_are_bounded_independently_of_byte_usage(tmp_path):
    for name in ('a', 'b', 'c'):
        (tmp_path/name).touch()
    result = module._inspect_workspace(tmp_path, limits(max_workspace_entries=2))
    assert result.limit_exceeded and result.entries == 3 and result.bytes_used == 0


def test_exact_directory_depth_then_one_more_level(tmp_path):
    (tmp_path/'a'/'b').mkdir(parents=True)
    exact = module._inspect_workspace(tmp_path, limits(max_workspace_depth=2))
    assert not exact.limit_exceeded and not exact.error
    (tmp_path/'a'/'b'/'c').mkdir()
    assert module._inspect_workspace(tmp_path, limits(max_workspace_depth=2)).limit_exceeded


def test_symlinks_fifo_and_empty_directories_count_without_following_or_opening_bodies(tmp_path):
    root = tmp_path/'workspace'; root.mkdir()
    outside = tmp_path/'outside'; outside.mkdir()
    (outside/'large').write_bytes(b'x'*8192)
    (root/'outside').symlink_to(outside, target_is_directory=True)
    (root/'loop').symlink_to(root, target_is_directory=True)
    os.mkfifo(root/'pipe')
    (root/'empty').mkdir()
    result = module._inspect_workspace(root, limits(max_workspace_entries=4))
    assert result.bytes_used == 0 and result.entries == 4
    assert not result.limit_exceeded and not result.error
    assert (outside/'large').stat().st_size == 8192
    (root/'fifth').touch()
    assert module._inspect_workspace(root, limits(max_workspace_entries=4)).limit_exceeded


@pytest.mark.parametrize('kind', ['missing', 'file', 'symlink'])
def test_unusable_workspace_root_is_not_treated_as_empty(tmp_path, kind):
    root = tmp_path/'workspace'
    if kind == 'file':
        root.write_text('not a directory')
    elif kind == 'symlink':
        root.symlink_to(tmp_path, target_is_directory=True)
    result = module._inspect_workspace(root, limits())
    assert result.error and not result.interrupted


def test_scan_permission_error_is_reported_and_directory_descriptors_close(tmp_path, monkeypatch):
    before = {item.name for item in Path('/proc/self/fd').iterdir()}
    def fail(*args, **kwargs):
        raise PermissionError('synthetic directory access denied')
    monkeypatch.setattr(module.os, 'scandir', fail)
    result = module._inspect_workspace(tmp_path, limits())
    assert result.error and not result.interrupted
    # scandir is patched on the shared os module, so inspect descriptor names
    # using listdir, which exercises a separate OS boundary.
    assert set(os.listdir('/proc/self/fd')) == before


def test_child_disappearing_between_enumeration_and_stat_is_a_normal_race(tmp_path, monkeypatch):
    target = tmp_path/'removed'; target.write_text('removed before stat')
    actual = module.os.scandir
    class RemovingIterator:
        def __init__(self, *args, **kwargs):
            self.entries = actual(*args, **kwargs)
        def __next__(self):
            entry = next(self.entries)
            if entry.name == 'removed':
                target.unlink()
            return entry
        def close(self):
            self.entries.close()
    monkeypatch.setattr(module.os, 'scandir', RemovingIterator)
    result = module._inspect_workspace(tmp_path, limits())
    assert result.entries == 1 and result.bytes_used == 0
    assert not result.limit_exceeded and not result.error and not result.interrupted


def test_directory_replaced_by_symlink_during_open_is_not_followed(tmp_path, monkeypatch):
    root = tmp_path/'workspace'; root.mkdir(); (root/'child').mkdir()
    outside = tmp_path/'outside'; outside.mkdir(); (outside/'large').write_bytes(b'x'*8192)
    actual = module.os.open
    swapped = []
    def open_directory(path, flags, *args, **kwargs):
        if path == 'child' and kwargs.get('dir_fd') is not None:
            (root/'child').rmdir(); (root/'child').symlink_to(outside, target_is_directory=True)
            swapped.append(True)
        return actual(path, flags, *args, **kwargs)
    monkeypatch.setattr(module.os, 'open', open_directory)
    result = module._inspect_workspace(root, limits())
    assert swapped == [True] and result.error and result.bytes_used == 0
    assert (outside/'large').stat().st_size == 8192


def test_scan_stop_is_observed_before_opening_root(tmp_path, monkeypatch):
    monkeypatch.setattr(module.os, 'open', denied)
    result = module._inspect_workspace(tmp_path/'missing', limits(), stop_requested=lambda: True)
    assert result.interrupted and not result.error and not result.limit_exceeded


def test_scan_can_stop_between_entries_and_closes_descriptors(tmp_path):
    for index in range(100):
        (tmp_path/str(index)).touch()
    polls = []
    def stopped():
        polls.append(True)
        return len(polls) >= 4
    before = set(os.listdir('/proc/self/fd'))
    result = module._inspect_workspace(tmp_path, limits(max_workspace_entries=128), stop_requested=stopped)
    assert result.interrupted and not result.limit_exceeded
    assert result.entries < 100 and len(polls) >= 4
    assert set(os.listdir('/proc/self/fd')) == before


def test_raising_scan_callback_preserves_exception_and_closes_descriptors(tmp_path):
    (tmp_path/'a').mkdir(); (tmp_path/'a'/'b').touch()
    polls = []
    def stopped():
        polls.append(True)
        if len(polls) == 4:
            raise KeyboardInterrupt('synthetic scan interrupt')
        return False
    before = set(os.listdir('/proc/self/fd'))
    with pytest.raises(KeyboardInterrupt, match='synthetic scan interrupt'):
        module._inspect_workspace(tmp_path, limits(), stop_requested=stopped)
    assert set(os.listdir('/proc/self/fd')) == before


def test_child_iterator_cleanup_error_does_not_leak_ancestor_descriptors(tmp_path, monkeypatch):
    (tmp_path/'a'/'b').mkdir(parents=True)
    actual = module.os.scandir
    opened, closed = [], []
    class CloseFailure:
        def __init__(self, *args, **kwargs):
            self.entries = actual(*args, **kwargs)
            self.index = len(opened); opened.append(self.index)
        def __next__(self):
            return next(self.entries)
        def close(self):
            self.entries.close(); closed.append(self.index)
            if self.index == 1:
                raise OSError('synthetic child iterator close failure')
    monkeypatch.setattr(module.os, 'scandir', CloseFailure)
    before = set(os.listdir('/proc/self/fd'))
    result = module._inspect_workspace(tmp_path, limits(max_workspace_entries=1))
    assert result.limit_exceeded and result.error
    assert opened == [0, 1] and closed == [1, 0]
    assert set(os.listdir('/proc/self/fd')) == before


@pytest.mark.parametrize('shape', ['entries', 'depth'])
def test_materialized_input_tree_over_limit_refuses_before_native_start(private_owner, shape):
    files = {'a': '', 'b': ''} if shape == 'entries' else {'a/b/c': ''}
    runner = admission.ResourceAdmittedToolRunner(scheduler=private_owner.owner,
        executor=module.SubprocessExecutor(popen=denied), workspace_root=private_owner.root)
    result = runner.run(module.ToolRunRequest(argv=(sys.executable, '-c', "print('unreachable')"),
        limits=limits(max_workspace_entries=1 if shape == 'entries' else 32, max_workspace_depth=1),
        input_files=files))
    assert result.pid is None and result.returncode is None
    assert result.workspace_limit_exceeded and result.resource_exhausted and not result.ok
    assert result.workspace_cleaned and private_owner.leases[0].released


@pytest.mark.parametrize('phase', ['inspection-return', 'argument-preparation'])
@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
def test_stop_after_preflight_work_is_checked_again_immediately_before_popen(tmp_path, monkeypatch, phase, stop):
    now = [100.0]
    cancelled = threading.Event()
    def interrupt():
        if stop == 'cancel':
            cancelled.set()
        else:
            now[0] += 5
    if phase == 'inspection-return':
        inspect = module._inspect_workspace
        def delayed(*args, **kwargs):
            result = inspect(*args, **kwargs)
            interrupt()
            return result
        monkeypatch.setattr(module, '_inspect_workspace', delayed)
    else:
        prepare = module._linux_resource_argv
        def delayed(*args, **kwargs):
            result = prepare(*args, **kwargs)
            interrupt()
            return result
        monkeypatch.setattr(module, '_linux_resource_argv', delayed)
    invocation = module.ProcessInvocation(argv=(sys.executable, '-c', "print('unreachable')"),
        runtime=module.ToolRuntime.NATIVE, cwd=tmp_path, environment={}, stdin=None, limits=limits())
    result = module.SubprocessExecutor(popen=denied, clock=lambda: now[0]).execute(invocation, cancelled)
    assert result.pid is None and result.returncode is None
    assert result.cancelled if stop == 'cancel' else result.timed_out
    assert not result.workspace_limit_exceeded and not result.resource_exhausted


@pytest.mark.parametrize('failure', ['bytes', 'entries', 'depth', 'inspection-error'])
def test_final_scan_covers_injected_executor_and_releases_only_after_cleanup(private_owner, monkeypatch, failure):
    actual = module._inspect_workspace
    def execute(invocation, cancellation):
        assert private_owner.owner.snapshot()['active_lease_count'] == 1
        if failure == 'bytes':
            (invocation.cwd/'oversized').write_bytes(b'x'*4097)
        elif failure == 'entries':
            for i in range(4):
                (invocation.cwd/str(i)).touch()
        elif failure == 'depth':
            (invocation.cwd/'a'/'b'/'c').mkdir(parents=True)
        return module.RawProcessResult(returncode=0, stdout='verified\n')
    if failure == 'inspection-error':
        def inspect(root, bounds, **kwargs):
            return replace(actual(root, bounds, **kwargs), error='synthetic final inspection failure')
        monkeypatch.setattr(module, '_inspect_workspace', inspect)
    runner = admission.ResourceAdmittedToolRunner(scheduler=private_owner.owner, executor=execute,
        workspace_root=private_owner.root)
    result = runner.run(module.ToolRunRequest(argv=('synthetic-checker',),
        limits=limits(max_workspace_entries=3, max_workspace_depth=2)))
    assert result.returncode == 0 and result.stdout == 'verified\n'
    assert not result.ok and result.resource_exhausted
    assert result.workspace_cleaned and result.termination_reason == 'resource_limit'
    if failure != 'inspection-error':
        assert result.workspace_limit_exceeded
    else:
        assert result.error
    assert private_owner.leases[0].released and not private_owner.workspaces[0].exists()


def test_observed_live_workspace_limit_is_sticky_when_files_are_already_removed(private_owner):
    def execute(invocation, cancellation):
        path = invocation.cwd/'temporary'; path.write_bytes(b'x'*4097); path.unlink()
        return module.RawProcessResult(returncode=0, stdout='verified\n',
            workspace_limit_exceeded=True, process_tree_terminated=True)
    runner = admission.ResourceAdmittedToolRunner(scheduler=private_owner.owner, executor=execute,
        workspace_root=private_owner.root)
    result = runner.run(module.ToolRunRequest(argv=('synthetic-checker',), limits=limits()))
    assert result.workspace_limit_exceeded and result.resource_exhausted and not result.ok
    assert result.process_tree_terminated and result.workspace_cleaned
    assert result.to_dict()['workspace_limit_exceeded'] is True


@pytest.mark.parametrize('stop', ['cancelled', 'timed_out'])
def test_workspace_failure_does_not_clear_an_existing_operational_stop(tmp_path, stop):
    runner = module.BoundedToolRunner(executor=lambda invocation, cancellation:
        module.RawProcessResult(returncode=-9, workspace_limit_exceeded=True, **{stop: True}),
        workspace_root=tmp_path/'runs')
    result = runner.run(module.ToolRunRequest(argv=('synthetic-checker',), limits=limits()))
    assert getattr(result, stop) and result.workspace_limit_exceeded and result.resource_exhausted
    assert result.termination_reason == ('cancelled' if stop == 'cancelled' else 'timeout')
    assert not result.ok and result.workspace_cleaned


@pytest.mark.parametrize('phase', ['during-scan', 'after-scan'])
@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
def test_final_scan_observes_stop_and_withholds_clean_result(tmp_path, monkeypatch, phase, stop):
    now = [100.0]; cancelled = threading.Event(); scans = []
    monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    def interrupt():
        if stop == 'cancel':
            cancelled.set()
        else:
            now[0] += 5
    actual = module._inspect_workspace
    def inspect(root, bounds, *, stop_requested=None):
        assert stop_requested is not None
        polls = []
        def checked_stop():
            polls.append(True)
            if phase == 'during-scan' and len(polls) == 3:
                interrupt()
            return stop_requested()
        result = actual(root, bounds, stop_requested=checked_stop)
        scans.append(result)
        if phase == 'after-scan':
            interrupt()
        return result
    monkeypatch.setattr(module, '_inspect_workspace', inspect)
    def execute(invocation, cancellation):
        for i in range(8):
            (invocation.cwd/str(i)).touch()
        return module.RawProcessResult(returncode=0, stdout='verified\n')
    runner = module.BoundedToolRunner(executor=execute, workspace_root=tmp_path/'runs')
    result = runner.run(module.ToolRunRequest(argv=('synthetic-checker',), limits=limits()),
                        cancellation=cancelled)
    assert result.cancelled if stop == 'cancel' else result.timed_out
    assert result.returncode == 0 and result.stdout == 'verified\n' and not result.ok
    assert not result.workspace_limit_exceeded and not result.resource_exhausted
    assert result.workspace_cleaned and len(scans) == 1
    assert scans[0].interrupted is (phase == 'during-scan')


def test_plain_injected_healthy_executor_and_scanner_leave_no_failure_flags(tmp_path):
    def execute(invocation, cancellation):
        (invocation.cwd/'answer').write_bytes(b'a'*4096)
        return module.RawProcessResult(returncode=0, stdout='healthy\n')
    result = module.BoundedToolRunner(executor=execute, workspace_root=tmp_path/'runs').run(
        module.ToolRunRequest(argv=('synthetic-checker',), limits=limits()))
    assert result.ok and result.workspace_cleaned
    assert not result.workspace_limit_exceeded and not result.resource_exhausted and not result.error


def test_shared_runner_keeps_concurrent_workspace_failures_and_foreign_lease_separate(private_owner):
    foreign = private_owner.owner.acquire('validation', cpu_slots=1, memory_mb=64,
        child_process_slots=1, timeout=1)
    barrier = threading.Barrier(2)
    outcomes, errors = {}, []
    def execute(invocation, cancellation):
        barrier.wait(timeout=2)
        assert private_owner.owner.snapshot()['active_lease_count'] == 3
        barrier.wait(timeout=2)
        (invocation.cwd/'data').write_bytes(b'x'*(4097 if invocation.argv[-1] == 'large' else 32))
        return module.RawProcessResult(returncode=0)
    runner = admission.ResourceAdmittedToolRunner(scheduler=private_owner.owner, executor=execute,
        workspace_root=private_owner.root)
    def run(name):
        try:
            outcomes[name] = runner.run(module.ToolRunRequest(argv=('synthetic-checker', name), limits=limits()))
        except BaseException as error:
            errors.append(error)
    workers = [threading.Thread(target=run, args=(name,)) for name in ('large', 'small')]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)
        assert not any(worker.is_alive() for worker in workers) and not errors
        assert outcomes['large'].workspace_limit_exceeded and not outcomes['large'].ok
        assert outcomes['small'].ok and not outcomes['small'].workspace_limit_exceeded
        assert not foreign.released and private_owner.owner.snapshot()['active_lease_count'] == 1
    finally:
        foreign.release()


def python_run(private_owner, source, *, cancellation=None, **changes):
    runner = admission.ResourceAdmittedToolRunner(scheduler=private_owner.owner,
        child_process_slots=2, workspace_root=private_owner.root)
    result = runner.run(module.ToolRunRequest(argv=(sys.executable, '-c', source),
        limits=limits(**changes)), cancellation=cancellation)
    assert result.pid is not None and result.workspace_cleaned
    assert private_owner.owner.snapshot()['active_lease_count'] == 0
    assert private_owner.leases[-1].released and not private_owner.workspaces[-1].exists()
    return result


@pytest.mark.parametrize('shape', ['single-file-no-rlimit', 'aggregate-small-files'])
def test_live_python_writer_stops_before_its_sleep_finishes(private_owner, shape):
    writes = ("pathlib.Path('large').write_bytes(b'x'*8192)" if shape == 'single-file-no-rlimit'
              else "pathlib.Path('a').write_bytes(b'x'*3072); pathlib.Path('b').write_bytes(b'x'*3072)")
    source = "import pathlib,time; print('verified',flush=True); " + writes + '; time.sleep(2)'
    result = python_run(private_owner, source, enforce_file_size_limit=shape != 'single-file-no-rlimit')
    assert result.workspace_limit_exceeded and result.resource_exhausted
    assert result.process_tree_terminated and not result.ok
    assert not result.timed_out and not result.cancelled
    assert 'verified' in result.stdout and result.returncode != 0


def test_native_exact_workspace_limit_is_healthy(private_owner):
    result = python_run(private_owner,
        "import pathlib,time; pathlib.Path('exact').write_bytes(b'x'*4096); time.sleep(.15); print('healthy')")
    assert result.ok and result.returncode == 0 and result.stdout == 'healthy\n'
    assert not result.workspace_limit_exceeded and not result.resource_exhausted


@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
def test_native_stop_without_workspace_overrun_keeps_original_reason(private_owner, stop):
    class ReadySignal:
        def is_set(self):
            return stop == 'cancel' and any((p/'ready').exists() for p in private_owner.workspaces)
    source = "import pathlib,time; pathlib.Path('ready').write_text('ready'); time.sleep(2)"
    result = python_run(private_owner, source, cancellation=ReadySignal(),
                        timeout_seconds=.3 if stop == 'timeout' else 4)
    assert result.cancelled if stop == 'cancel' else result.timed_out
    assert not result.workspace_limit_exceeded and not result.resource_exhausted
    assert result.process_tree_terminated and not result.ok


def identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return int(fields[19]), fields[0]
    except (FileNotFoundError, ProcessLookupError):
        return None


def test_live_child_writer_is_drained_before_workspace_and_lease_cleanup(private_owner, tmp_path):
    record_path = tmp_path/'child.json'
    child = ("import pathlib,os,json,signal,time; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        "fields=pathlib.Path('/proc/self/stat').read_text().rsplit(')',1)[1].split(); "
        f"pathlib.Path({str(record_path)!r}).write_text(json.dumps({{'pid':os.getpid(),'birth':int(fields[19])}})); "
        "time.sleep(.2); pathlib.Path('large').write_bytes(b'x'*8192); time.sleep(2)")
    source = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(3)"
    try:
        result = python_run(private_owner, source, enforce_file_size_limit=False)
        assert result.workspace_limit_exceeded and result.resource_exhausted and result.process_tree_terminated
        assert not result.timed_out and not result.ok and record_path.is_file()
        record = json.loads(record_path.read_text())
        found = identity(record['pid'])
        assert found is None or found[0] != record['birth'] or found[1] == 'Z'
    finally:
        # This can only target the fixture's recorded birth identity, never a
        # process selected by name or a PID reused by unrelated host work.
        if record_path.exists():
            record = json.loads(record_path.read_text())
            found = identity(record['pid'])
            if found is not None and found[0] == record['birth'] and found[1] != 'Z':
                try:
                    os.kill(record['pid'], signal.SIGKILL)
                except ProcessLookupError:
                    pass
