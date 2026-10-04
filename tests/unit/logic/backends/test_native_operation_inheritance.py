"""Admitted native invocations inherit an enclosing proof operation safely.

All pressure is sampled from synthetic data into a private scheduler. Executors
are Python fixtures; no solver, native subprocess, installer, or shared pool is
used. Real workspace creation and lease cleanup remain exercised.
"""
from dataclasses import replace
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process, resource_admission as admission
from ipfs_datasets_py.logic.backends.smt import operation_budget as budget
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


MIB = 1024**2


@pytest.fixture(autouse=True)
def no_host_process_or_shared_pool(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail('native inheritance fixture reached a host process or shared scheduler')
    monkeypatch.setattr(subprocess, 'Popen', denied)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', denied)
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', denied)


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    fake = SimpleNamespace(monotonic=lambda: now[0])
    monkeypatch.setattr(admission, 'time', fake)
    monkeypatch.setattr(budget, 'time', fake)
    return now


@pytest.fixture
def pool(tmp_path):
    healthy = ProofHostResources(8, 8192, 8192, pid_task_limit=8192, available_pid_tasks=8192)
    current = [healthy]
    def sample():
        if isinstance(current[0], Exception):
            raise current[0]
        return current[0]
    config = schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / 'private-native-pool.json', proof_resource_sampler=sample,
        total_cpu_slots=3, total_memory_mb=1024, total_child_process_slots=3,
        proof_memory_headroom_mb=64, lane_reservations={}, auto_renew_leases=False,
        proof_backoff_seconds=.01, poll_interval_seconds=.002)
    owner = schedulers.GlobalResourceScheduler(config)
    yield SimpleNamespace(owner=owner, healthy=healthy, current=current)
    snapshot = owner.snapshot()
    assert snapshot['active_lease_count'] == snapshot['waiting_request_count'] == 0


def request(**limits):
    return process.ToolRunRequest(argv=('synthetic-checker',),
        limits=process.ToolRunLimits(**{'timeout_seconds': 5, 'cpu_seconds': 4,
            'memory_bytes': 4 * 1024**3, 'resident_memory_bytes': 64 * MIB,
            'max_input_bytes': 1024, 'max_output_bytes': 4096, 'max_workspace_bytes': 8192,
            'max_file_bytes': 4096, **limits}), input_files={'source.txt': 'fixture input'},
        output_paths=('answer.txt',), environment={'FIXTURE_ENV': 'reviewed'})


@pytest.fixture
def runner_factory(pool, tmp_path):
    workspaces = []
    def make(action=None, *, parent=None, default_owner=False):
        calls = []
        def execute(invocation, signal):
            calls.append((invocation, signal))
            workspaces.append(invocation.cwd)
            assert invocation.cwd.is_dir()
            (invocation.cwd / 'answer.txt').write_text('fixture output')
            if action:
                return action(invocation, signal)
            return process.RawProcessResult(returncode=0, stdout='checked\n')
        ownership = {} if default_owner else ({'parent_lease': parent} if parent is not None else {'scheduler': pool.owner})
        runner = admission.ResourceAdmittedToolRunner(executor=execute,
            workspace_root=tmp_path / 'runs', **ownership)
        return runner, calls
    yield make
    assert all(not workspace.exists() for workspace in workspaces)


def until(predicate):
    deadline = time.monotonic() + 2
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError('bounded fixture wait expired')
        time.sleep(.003)


@pytest.mark.parametrize('stop', ['timeout', 'cancel'])
@pytest.mark.parametrize('argv_form', [False, True])
def test_stopped_ambient_skips_scheduler_workspace_and_executor(runner_factory, clock, tmp_path, stop, argv_form):
    runner, calls = runner_factory(default_owner=True)
    signal = threading.Event()
    expected = budget.ProofOperationTimeout if stop == 'timeout' else budget.ProofOperationCancelled
    with pytest.raises(expected):
        with budget.proof_operation_scope(timeout_ms=1000, cancellation=signal):
            if stop == 'timeout':
                clock[0] += 1.1
            else:
                signal.set()
            original = request()
            result = runner.run(original.argv, limits=original.limits) if argv_form else runner.run(original)
            assert result.timed_out if stop == 'timeout' else result.cancelled
            assert not result.ok and result.pid is None and result.workspace_cleaned
            assert calls == [] and not (tmp_path / 'runs').exists()
    assert budget.current_proof_operation() is None


@pytest.mark.parametrize('stop', ['timeout', 'cancel'])
def test_scheduler_resolution_cannot_extend_budget_or_launch_after_stop(
        runner_factory, pool, clock, tmp_path, monkeypatch, stop):
    runner, calls = runner_factory(default_owner=True)
    signal = threading.Event(); resolutions = []
    def resolve():
        resolutions.append(True)
        if stop == 'timeout':
            clock[0] += 1.1
        else:
            signal.set()
        return pool.owner
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', resolve)
    monkeypatch.setattr(pool.owner, 'acquire', lambda *a, **k: pytest.fail('stopped resolution entered admission'))
    expected = budget.ProofOperationTimeout if stop == 'timeout' else budget.ProofOperationCancelled
    with pytest.raises(expected):
        with budget.proof_operation_scope(timeout_ms=1000, cancellation=signal):
            result = runner.run(request())
            assert result.timed_out if stop == 'timeout' else result.cancelled
            assert not result.ok and result.workspace_cleaned
            assert calls == [] and not (tmp_path / 'runs').exists()
    assert resolutions == [True]


@pytest.mark.parametrize('local,ambient,cpu,expected', [
    (5, 1000, 4, 1), (1, 5000, 4, 1), (5, 1000, .2, .2), (5, 1000, None, None),
])
def test_effective_wall_and_cpu_tighten_without_mutating_other_caps(
        runner_factory, pool, clock, monkeypatch, local, ambient, cpu, expected):
    runner, calls = runner_factory()
    original = request(timeout_seconds=local, cpu_seconds=cpu)
    unchanged = replace(original)
    acquired = []
    acquire = pool.owner.acquire
    def observed_acquire(*args, **kwargs):
        acquired.append(kwargs.copy())
        return acquire(*args, **kwargs)
    monkeypatch.setattr(pool.owner, 'acquire', observed_acquire)
    with budget.proof_operation_scope(timeout_ms=ambient):
        result = runner.run(original)
        assert result.ok
    assert original == unchanged and original.limits is unchanged.limits
    assert acquired[0]['timeout'] == pytest.approx(min(local, ambient / 1000))
    assert acquired[0]['memory_mb'] == 64
    actual = calls[0][0].limits
    assert 0 < actual.timeout_seconds <= min(local, ambient / 1000)
    assert actual.cpu_seconds == expected
    for name in process.ToolRunLimits.__dataclass_fields__:
        if name not in {'timeout_seconds', 'cpu_seconds'}:
            assert getattr(actual, name) == getattr(original.limits, name)
    assert calls[0][0].environment['FIXTURE_ENV'] == 'reviewed'
    assert result.output_files['answer.txt'] == b'fixture output'


def test_admission_and_workspace_cost_share_remaining_ambient_budget(runner_factory, pool, clock, monkeypatch):
    runner, calls = runner_factory()
    acquire, write = pool.owner.acquire, runner._write_inputs
    def slow_acquire(*args, **kwargs):
        lease = acquire(*args, **kwargs); clock[0] += .2; return lease
    def slow_write(*args, **kwargs):
        write(*args, **kwargs); clock[0] += .3
    monkeypatch.setattr(pool.owner, 'acquire', slow_acquire)
    monkeypatch.setattr(runner, '_write_inputs', slow_write)
    with budget.proof_operation_scope(timeout_ms=1000):
        result = runner.run(request())
        assert result.ok
    assert calls[0][0].limits.timeout_seconds == pytest.approx(.5)
    assert calls[0][0].limits.cpu_seconds == pytest.approx(.5)
    assert result.elapsed_seconds >= .5


@pytest.mark.parametrize('phase', ['acquire', 'write'])
@pytest.mark.parametrize('stop', ['timeout', 'cancel'])
def test_stop_during_preparation_refuses_executor_and_releases_lease(
        runner_factory, pool, clock, monkeypatch, phase, stop):
    runner, calls = runner_factory(); signal = threading.Event()
    original = pool.owner.acquire if phase == 'acquire' else runner._write_inputs
    def delayed(*args, **kwargs):
        value = original(*args, **kwargs)
        if stop == 'timeout':
            clock[0] += 1.1
        else:
            signal.set()
        return value
    monkeypatch.setattr(pool.owner if phase == 'acquire' else runner,
                        'acquire' if phase == 'acquire' else '_write_inputs', delayed)
    expected = budget.ProofOperationTimeout if stop == 'timeout' else budget.ProofOperationCancelled
    with pytest.raises(expected):
        with budget.proof_operation_scope(timeout_ms=1000, cancellation=signal):
            result = runner.run(request())
            assert result.timed_out if stop == 'timeout' else result.cancelled
            assert not result.ok and result.workspace_cleaned
            assert calls == []
            assert pool.owner.snapshot()['active_lease_count'] == 0


@pytest.mark.parametrize('stop', ['timeout', 'cancel'])
def test_late_clean_executor_cannot_hide_ambient_stop(runner_factory, clock, stop):
    event = threading.Event()
    def late(invocation, signal):
        if stop == 'timeout':
            clock[0] += 1.1
        else:
            event.set()
        return process.RawProcessResult(returncode=0, stdout='proof accepted\n', pid=1234)
    runner, calls = runner_factory(late)
    expected = budget.ProofOperationTimeout if stop == 'timeout' else budget.ProofOperationCancelled
    with pytest.raises(expected):
        with budget.proof_operation_scope(timeout_ms=1000, cancellation=event):
            result = runner.run(request())
            assert result.timed_out if stop == 'timeout' else result.cancelled
            assert not result.ok and result.returncode == 0 and result.pid == 1234
            assert result.stdout == 'proof accepted\n' and result.workspace_cleaned
    assert len(calls) == 1


@pytest.mark.parametrize('ambient_signal', [False, True])
def test_observed_cancellation_is_sticky_even_when_original_event_clears(runner_factory, clock, ambient_signal):
    event = threading.Event()
    def execute(invocation, signal):
        event.set(); assert signal.is_set(); event.clear()
        assert signal.is_set()
        return process.RawProcessResult(returncode=0)
    runner, _ = runner_factory(execute)
    if ambient_signal:
        with pytest.raises(budget.ProofOperationCancelled):
            with budget.proof_operation_scope(timeout_ms=1000, cancellation=event):
                result = runner.run(request())
                assert result.cancelled and not result.ok
    else:
        with budget.proof_operation_scope(timeout_ms=1000) as outer:
            result = runner.run(request(), cancellation=event)
            assert result.cancelled and not result.ok
            assert not outer.is_set()
    assert not event.is_set()


@pytest.mark.parametrize('phase', ['output-read', 'workspace-cleanup', 'lease-release'])
@pytest.mark.parametrize('stop', ['timeout', 'cancel'])
def test_final_cleanup_and_release_stops_are_observed_without_leaking(
        runner_factory, pool, clock, monkeypatch, phase, stop):
    runner, calls = runner_factory(); event = threading.Event()
    def stop_now():
        if stop == 'timeout':
            clock[0] += 1.1
        else:
            event.set()
    if phase == 'output-read':
        original = runner._read_outputs
        def delayed(*args, **kwargs):
            value = original(*args, **kwargs); stop_now(); return value
        monkeypatch.setattr(runner, '_read_outputs', delayed)
    elif phase == 'workspace-cleanup':
        original = process.tempfile.TemporaryDirectory.cleanup
        def delayed(temporary):
            value = original(temporary); stop_now(); return value
        monkeypatch.setattr(process.tempfile.TemporaryDirectory, 'cleanup', delayed)
    else:
        original = pool.owner.release
        def delayed(*args, **kwargs):
            assert calls and not calls[0][0].cwd.exists()
            value = original(*args, **kwargs); stop_now(); return value
        monkeypatch.setattr(pool.owner, 'release', delayed)
    expected = budget.ProofOperationTimeout if stop == 'timeout' else budget.ProofOperationCancelled
    with pytest.raises(expected):
        with budget.proof_operation_scope(timeout_ms=1000, cancellation=event):
            result = runner.run(request())
            assert result.timed_out if stop == 'timeout' else result.cancelled
            assert not result.ok and result.workspace_cleaned
            assert result.output_files['answer.txt'] == b'fixture output'
            assert pool.owner.snapshot()['active_lease_count'] == 0


@pytest.mark.parametrize('flag', ['cancelled', 'timed_out', 'resource_exhausted', 'output_truncated', 'process_tree_terminated'])
def test_ambient_timeout_retains_all_lower_lifecycle_flags_and_diagnostics(runner_factory, clock, flag):
    def execute(invocation, signal):
        clock[0] += 1.1
        return process.RawProcessResult(returncode=-9, stderr='native stop marker', pid=1234,
            error='original native failure', **{flag: True})
    runner, _ = runner_factory(execute)
    with pytest.raises(budget.ProofOperationTimeout):
        with budget.proof_operation_scope(timeout_ms=1000):
            result = runner.run(request())
            assert result.timed_out and getattr(result, flag) and not result.ok
            assert result.returncode == -9 and result.pid == 1234
            assert result.stderr == 'native stop marker' and 'original native failure' in result.error


def test_cleanup_exception_propagates_after_lease_release(runner_factory, pool, clock, monkeypatch):
    runner, _ = runner_factory()
    original = process.tempfile.TemporaryDirectory.cleanup
    def fail_after_cleanup(temporary):
        original(temporary)
        raise PermissionError('fixture cleanup failure')
    monkeypatch.setattr(process.tempfile.TemporaryDirectory, 'cleanup', fail_after_cleanup)
    with budget.proof_operation_scope(timeout_ms=1000) as outer:
        with pytest.raises(PermissionError, match='fixture cleanup failure'):
            runner.run(request())
        assert not outer.is_set()
        assert pool.owner.snapshot()['active_lease_count'] == 0


def test_scheduler_error_during_release_propagates_after_real_cleanup(runner_factory, pool, clock, monkeypatch):
    runner, calls = runner_factory()
    original = pool.owner.release
    def fail_after_release(*args, **kwargs):
        assert calls and not calls[0][0].cwd.exists()
        original(*args, **kwargs)
        raise schedulers.ResourceSchedulerError('fixture lease-release failure')
    monkeypatch.setattr(pool.owner, 'release', fail_after_release)
    with budget.proof_operation_scope(timeout_ms=1000) as outer:
        with pytest.raises(schedulers.ResourceSchedulerError, match='fixture lease-release failure'):
            runner.run(request())
        assert not outer.is_set()
        assert pool.owner.snapshot()['active_lease_count'] == 0


def test_baseexception_propagates_after_workspace_and_lease_cleanup(runner_factory, pool, clock):
    def interrupt(invocation, signal):
        raise KeyboardInterrupt('fixture interruption')
    runner, calls = runner_factory(interrupt)
    with pytest.raises(KeyboardInterrupt):
        with budget.proof_operation_scope(timeout_ms=1000):
            runner.run(request())
    assert calls and not calls[0][0].cwd.exists()
    assert pool.owner.snapshot()['active_lease_count'] == 0
    assert budget.current_proof_operation() is None


def test_late_stop_preserves_redaction_and_never_reintroduces_secret_output(runner_factory, clock):
    secret = 'fixture-only-secret-native-token'
    def execute(invocation, signal):
        clock[0] += 1.1
        return process.RawProcessResult(returncode=0, stdout=secret, stderr=secret, error=secret)
    runner, _ = runner_factory(execute)
    selected = replace(request(), argv=('synthetic-checker', '--token', secret), secrets=(secret,))
    with pytest.raises(budget.ProofOperationTimeout):
        with budget.proof_operation_scope(timeout_ms=1000):
            result = runner.run(selected)
            assert result.timed_out and not result.ok
            assert secret not in str(result.to_dict())


def test_lease_only_revocation_does_not_cancel_unrelated_ambient_operation(runner_factory, pool, clock):
    with pool.owner.acquire('orchestration', cpu_slots=1, memory_mb=128,
            child_process_slots=1, timeout=0) as parent:
        def execute(invocation, signal):
            parent.cancel()
            assert signal.is_set()
            return process.RawProcessResult(returncode=0)
        runner, _ = runner_factory(execute, parent=parent)
        with budget.proof_operation_scope(timeout_ms=1000) as outer:
            result = runner.run(request())
            assert result.cancelled and not result.ok
            assert not outer.is_set()
        assert not parent.released


@pytest.mark.parametrize('kind', ['healthy', 'local-timeout', 'local-cancel'])
def test_no_ambient_preserves_standalone_cpu_and_stop_contract(runner_factory, clock, kind):
    event = threading.Event()
    def execute(invocation, signal):
        if kind == 'local-timeout':
            clock[0] += 6
        elif kind == 'local-cancel':
            event.set()
        return process.RawProcessResult(returncode=0)
    runner, calls = runner_factory(execute)
    result = runner.run(request(cpu_seconds=10), cancellation=event)
    assert calls[0][0].limits.cpu_seconds == 10
    assert result.ok is (kind == 'healthy')
    assert result.timed_out is (kind == 'local-timeout')
    assert result.cancelled is (kind == 'local-cancel')
    assert budget.current_proof_operation() is None


def test_shorter_local_deadline_does_not_poison_live_parent(runner_factory, clock):
    def execute(invocation, signal):
        clock[0] += .2
        return process.RawProcessResult(returncode=0)
    runner, _ = runner_factory(execute)
    with budget.proof_operation_scope(timeout_ms=1000) as outer:
        result = runner.run(request(timeout_seconds=.1))
        assert result.timed_out and not result.ok
        assert not outer.is_set()


@pytest.mark.parametrize('changes,reason', [
    ({'cpu_stall_percent': 90}, 'proof_cpu_stall'),
    ({'available_memory_mb': 32}, 'proof_memory_headroom'),
    ({'available_pid_tasks': 0}, 'proof_pid_headroom'),
    (None, 'proof_resource_telemetry_unknown'),
])
@pytest.mark.parametrize('child', [False, True])
@pytest.mark.parametrize('stop', ['timeout', 'cancel'])
def test_ambient_stop_drains_actual_pressure_queue_without_launch(
        runner_factory, pool, clock, changes, reason, child, stop):
    parent = pool.owner.acquire('orchestration', cpu_slots=2, memory_mb=256,
        child_process_slots=2, timeout=0) if child else None
    foreign = pool.owner.acquire('validation', cpu_slots=1, memory_mb=32, child_process_slots=1, timeout=0)
    runner, calls = runner_factory(parent=parent)
    pool.current[0] = replace(pool.healthy, **changes) if changes is not None else OSError('fixture unknown telemetry')
    event = threading.Event(); observed = {}
    def work():
        try:
            with budget.proof_operation_scope(timeout_ms=1000, cancellation=event):
                observed['result'] = runner.run(request())
        except BaseException as error:
            observed['error'] = error
    worker = threading.Thread(target=work)
    worker.start()
    try:
        until(lambda: pool.owner.snapshot()['proof_backoff'].get('reason') == reason)
        assert calls == [] and not runner._workspace_root.exists()
        if stop == 'timeout':
            clock[0] += 1.1
        else:
            event.set()
        worker.join(timeout=2)
        assert not worker.is_alive()
        result = observed['result']
        assert result.timed_out if stop == 'timeout' else result.cancelled
        assert isinstance(observed['error'], budget.ProofOperationTimeout if stop == 'timeout' else budget.ProofOperationCancelled)
        snapshot = pool.owner.snapshot()
        assert snapshot['waiting_request_count'] == 0
        assert snapshot['active_lease_count'] == 1 + int(child)
        assert not foreign.released and not foreign.cancelled
        if parent:
            assert not parent.released and not parent.cancelled
        assert calls == []
    finally:
        event.set(); pool.current[0] = pool.healthy
        worker.join(timeout=3)
        foreign.release()
        if parent:
            parent.release()


def test_child_inherits_budget_without_double_charging_or_releasing_other_owners(runner_factory, pool, clock):
    with pool.owner.acquire('orchestration', cpu_slots=2, memory_mb=256, child_process_slots=2, timeout=0) as parent:
        with pool.owner.acquire('validation', cpu_slots=1, memory_mb=32, child_process_slots=1, timeout=0) as foreign:
            expected = pool.owner.snapshot()['allocated']
            def execute(invocation, signal):
                snapshot = pool.owner.snapshot()
                assert snapshot['active_lease_count'] == 3
                assert snapshot['active_root_lease_count'] == 2
                assert snapshot['allocated'] == expected
                clock[0] += .6
                return process.RawProcessResult(returncode=0)
            runner, _ = runner_factory(execute, parent=parent)
            with pytest.raises(budget.ProofOperationTimeout):
                with budget.proof_operation_scope(timeout_ms=500):
                    result = runner.run(request())
                    assert result.timed_out
            assert not parent.cancelled and not parent.released
            assert not foreign.cancelled and not foreign.released
            assert pool.owner.snapshot()['active_lease_count'] == 2


def test_explicit_plain_runner_keeps_caller_owned_lifecycle(clock, tmp_path):
    calls = []
    def execute(invocation, signal):
        calls.append(invocation)
        clock[0] += 1.1
        return process.RawProcessResult(returncode=0)
    plain = process.BoundedToolRunner(executor=execute, workspace_root=tmp_path)
    with pytest.raises(budget.ProofOperationTimeout):
        with budget.proof_operation_scope(timeout_ms=1000):
            result = plain.run(request())
            assert result.ok  # The surrounding operation, not this explicit bypass, rejects it.
    assert calls[0].limits.timeout_seconds == 5 and calls[0].limits.cpu_seconds == 4


def test_shared_runner_keeps_thread_ambient_scopes_isolated_and_can_be_reused(runner_factory, clock):
    barrier = threading.Barrier(2); event = threading.Event(); active = [True]
    observations, results, errors = {}, {}, {}
    def execute(invocation, signal):
        if active[0]:
            name = threading.current_thread().name
            observations[name] = (budget.current_proof_operation(), signal)
            barrier.wait(timeout=2)
            if name == 'cancelled-native':
                event.set(); assert signal.is_set(); event.clear()
        return process.RawProcessResult(returncode=0)
    runner, _ = runner_factory(execute)
    def work(name):
        try:
            with budget.proof_operation_scope(timeout_ms=1000,
                    cancellation=event if name == 'cancelled-native' else None):
                results[name] = runner.run(request())
        except BaseException as error:
            errors[name] = error
    workers = [threading.Thread(name=name, target=work, args=(name,))
               for name in ('cancelled-native', 'healthy-native')]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=3)
    assert all(not worker.is_alive() for worker in workers)
    assert results['cancelled-native'].cancelled
    assert isinstance(errors['cancelled-native'], budget.ProofOperationCancelled)
    assert results['healthy-native'].ok and 'healthy-native' not in errors
    assert observations['cancelled-native'][0] is not observations['healthy-native'][0]
    active[0] = False
    with budget.proof_operation_scope(timeout_ms=1000):
        assert runner.run(request()).ok
    assert budget.current_proof_operation() is None
