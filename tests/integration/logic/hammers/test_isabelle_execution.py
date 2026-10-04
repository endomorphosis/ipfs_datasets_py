"""Resource-owner contracts using controlled executables, not Isabelle proofs."""
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import sys
import threading
import time

import pytest

from ipfs_datasets_py.logic.backends import process
from ipfs_datasets_py.logic.backends.installers import isabelle_execution as execution
from ipfs_datasets_py.logic.backends.installers import isabelle_installation as installation
from ipfs_datasets_py.logic.backends.installers import isabelle_profile as profile
from ipfs_datasets_py.logic.backends.installers import isabelle as legacy
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import GlobalResourceScheduler, ResourceSchedulerConfig

SOURCE = 'theory ExactInput\nimports Main\nbegin\nlemma intended: "True" by simp\nend\n'


@pytest.fixture
def owner(tmp_path):
    healthy = ProofHostResources(16, 16384, 16384)
    samples = [healthy]
    scheduler = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "resources.json", proof_resource_sampler=lambda: samples[0],
        total_cpu_slots=6, total_memory_mb=8192, total_child_process_slots=16,
        proof_memory_headroom_mb=512, proof_backoff_seconds=.02, poll_interval_seconds=.01,
        lane_reservations={}, auto_renew_leases=False))
    yield scheduler, samples, healthy
    assert scheduler.active_leases() == []
    assert scheduler.snapshot()["waiting_request_count"] == 0


def make_runtime(outer):
    root = outer / legacy.ISABELLE_VERSION
    for directory in (root / 'bin', root / 'etc', root / 'lib/scripts'):
        directory.mkdir(parents=True, exist_ok=True)
    (root / 'etc/ISABELLE_IDENTIFIER').write_text(legacy.ISABELLE_VERSION)
    for name in ('etc/settings', 'etc/components', 'lib/scripts/getsettings'):
        (root / name).write_text('# controlled test fixture\n')
    launcher = root / 'bin/isabelle'
    launcher.write_text(f'''#!{Path(sys.executable).resolve()}
import sys,os,time,hashlib
from pathlib import Path
root=Path(__file__).parent.parent
behavior=(root/'behavior').read_text() if (root/'behavior').exists() else 'normal'
args=sys.argv[1:]
if args==['version']:
 print({legacy.ISABELLE_VERSION!r})
elif args==['process_theories','-?']:
 print('Usage: isabelle process_theories [OPTIONS] [THEORIES...]'); sys.exit(1)
elif args and args[0]=='build':
 assert '-n' in args
 sys.exit(1 if behavior=='missing_hol' else 0)
else:
 assert args[0]=='process_theories' and args[1:3]==['-D',str(Path.cwd())]
 assert os.environ['HOME']==os.environ['TMPDIR']==str(Path.cwd())
 assert Path('.isabelle/{legacy.ISABELLE_VERSION}/etc/settings').exists()
 content=Path(args[-1]+'.thy').read_bytes()
 if behavior=='slow':
  (root/'started').write_text('ready'); time.sleep(30)
 if behavior=='truncated': print('x'*(2*1024**2))
 print(hashlib.sha256(content).hexdigest())
 sys.exit(1 if behavior=='exit_one' else 0)
''')
    launcher.chmod(0o700)
    return outer, root, launcher


@pytest.fixture
def runtime(tmp_path):
    return make_runtime(tmp_path / 'installed')


def run(owner, runtime, **kwargs):
    return execution.run_isabelle_operation(install_root=runtime[0], scheduler=owner[0], **kwargs)


@pytest.mark.parametrize('mode', ['command', 'capture', 'check'])
def test_default_owner_exact_source_private_profile_and_fresh_child_phases(owner, runtime, monkeypatch, mode):
    monkeypatch.setattr(execution, 'get_global_resource_scheduler', lambda: owner[0])
    invocations, roots, child_ids = [], [], []
    original = process.SubprocessExecutor.execute
    def observed(self, invocation, cancellation=None):
        rows = owner[0].active_leases()
        roots.append([row for row in rows if not row.get('parent_lease_id')])
        child_ids.append(max(rows, key=lambda row: row['sequence'])['lease_id'])
        assert len(roots[-1]) == 1 and roots[-1][0]['memory_mb'] == 2304
        invocations.append(invocation)
        return original(self, invocation, cancellation)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', observed)
    result = execution.run_isabelle_operation(mode=mode, install_root=runtime[0],
        source=None if mode=='command' else SOURCE)
    assert result.completed, result.to_dict()
    assert len(invocations) == (2 if mode=='command' else 4)
    assert len(set(child_ids)) == len(child_ids)
    assert len({rows[0]['lease_id'] for rows in roots}) == 1
    assert result.native_runtime['executable'] == str(runtime[2])
    assert result.runtime_unchanged
    if mode!='command':
        assert result.observation.stdout.strip() == hashlib.sha256(SOURCE.encode()).hexdigest() == result.source_sha256
        assert result.theory_name == 'ExactInput'
        assert result.observation.command[2:4] == ('-D', '{workspace}')
        assert ('quick_and_dirty=true' if mode=='capture' else 'quick_and_dirty=false') in result.observation.command
    report = result.to_dict()
    assert report['grants_proof_authority'] is report['grants_repository_authority'] is False
    assert report['ownership']['operation_release_requested'] is True
    for invocation in invocations:
        assert invocation.limits.resident_memory_bytes == 2048*1024**2
        assert invocation.limits.memory_bytes == 32*1024**3
        assert 0 < invocation.limits.cpu_seconds <= 30
        assert not invocation.cwd.exists()


def test_existing_parent_is_shared_and_remains_live(owner, runtime):
    with owner[0].acquire('orchestration', cpu_slots=3, memory_mb=2304, child_process_slots=12, timeout=0) as parent:
        result = execution.run_isabelle_operation(mode='check', source=SOURCE,
            install_root=runtime[0], parent_lease=parent)
        assert result.completed, result.to_dict()
        assert result.parent_lease_id == parent.lease_id
        assert not parent.released and not parent.cancelled
        assert [row['lease_id'] for row in owner[0].active_leases()] == [parent.lease_id]


@pytest.mark.parametrize('kwargs', [
    {'timeout_seconds':0}, {'timeout_seconds':True}, {'timeout_seconds':float('nan')},
    {'timeout_seconds':3601}, {'cpu_seconds':False}, {'cpu_seconds':float('inf')},
    {'memory_mb':512}, {'memory_mb':2048.0}, {'auto_install':1},
    {'mode':'unknown'}, {'mode':'command','auto_install':True}, {'mode':'command','source':SOURCE},
    {'mode':'check','source':None}, {'mode':'check','source':'plain text'},
    {'mode':'check','source':'x'*(execution.MAX_SOURCE_BYTES+1)},
    {'parent_lease':object()}, {'scheduler':object()}, {'cancellation':object()},
])
def test_invalid_inputs_rejected_before_admission_or_native_work(monkeypatch, kwargs):
    monkeypatch.setattr(execution, 'get_global_resource_scheduler', lambda: pytest.fail('invalid input admitted'))
    with pytest.raises((ValueError, TypeError)):
        execution.run_isabelle_operation(**kwargs)


@pytest.mark.parametrize('source', [None, b'theory T', 7, [], '', '\0', '\ud800'])
def test_source_validator_rejects_invalid_text_before_parsing_or_admission(monkeypatch, source):
    monkeypatch.setattr(execution, 'theory_name', lambda *_: pytest.fail('invalid source parsed'))
    monkeypatch.setattr(execution, 'get_global_resource_scheduler', lambda: pytest.fail('invalid source admitted'))
    with pytest.raises(ValueError):
        execution.validate_isabelle_source(source)
    with pytest.raises(ValueError):
        execution.run_isabelle_operation(mode='check', source=source)


def test_source_validator_rejects_str_subclasses_without_custom_scans_or_encoding():
    class UntrustedText(str):
        def __len__(self):
            pytest.fail('str subclass length consulted')

        def __contains__(self, _):
            pytest.fail('str subclass scanned')

        def encode(self, *args, **kwargs):
            pytest.fail('str subclass encoded')

    with pytest.raises(ValueError, match='exact text'):
        execution.validate_isabelle_source(UntrustedText(SOURCE))


@pytest.mark.parametrize('text', ['a', '\U0001f600'])
def test_source_validator_exact_utf8_byte_boundary_and_overflow_before_parsing(monkeypatch, text):
    width = len(text.encode('utf-8'))
    source = text * (execution.MAX_SOURCE_BYTES // width)
    data = execution.validate_isabelle_source(source)
    assert len(data) == execution.MAX_SOURCE_BYTES and data.decode('utf-8') == source
    monkeypatch.setattr(execution, 'theory_name', lambda *_: pytest.fail('oversized source parsed'))
    monkeypatch.setattr(execution, 'get_global_resource_scheduler', lambda: pytest.fail('oversized source admitted'))
    with pytest.raises(ValueError, match='UTF-8 bytes'):
        execution.validate_isabelle_source(source + 'a')
    with pytest.raises(ValueError, match='UTF-8 bytes'):
        execution.run_isabelle_operation(mode='check', source=source + 'a')


def test_ambiguous_scheduler_and_parent_rejected(owner, runtime):
    with owner[0].acquire('validation', cpu_slots=3, memory_mb=2304, child_process_slots=12, timeout=0) as parent:
        with pytest.raises(ValueError, match='only parent_lease or scheduler'):
            execution.run_isabelle_operation(parent_lease=parent, scheduler=owner[0])


def test_underfunded_parent_refuses_before_runtime_probe(owner, runtime, monkeypatch):
    monkeypatch.setattr(profile, 'resolve_runtime', lambda **kw: pytest.fail('underfunded runtime probe'))
    with owner[0].acquire('validation', cpu_slots=1, memory_mb=512, child_process_slots=1, timeout=0) as parent:
        result = execution.run_isabelle_operation(parent_lease=parent)
        assert result.status == 'admission_denied' and result.reason_code == 'underfunded_parent_lease'
        assert not parent.released


@pytest.mark.parametrize('release_pressure', [False, True])
def test_external_pressure_blocks_native_work_and_can_recover(owner, runtime, monkeypatch, release_pressure):
    owner[1][0] = replace(owner[2], available_memory_mb=64)
    calls = []
    original = process.SubprocessExecutor.execute
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', lambda self, invocation, cancellation=None:
        calls.append(time.monotonic()) or original(self, invocation, cancellation))
    timer = threading.Timer(.05, lambda: owner[1].__setitem__(0, owner[2])) if release_pressure else None
    if timer: timer.start()
    try:
        result = run(owner, runtime, timeout_seconds=1 if release_pressure else .08)
    finally:
        if timer: timer.join()
    if release_pressure:
        assert result.completed and calls, result.to_dict()
    else:
        assert result.status == 'timed_out' and not calls and result.observation is None


def test_cancellation_while_waiting_does_not_start_a_native_probe(owner, runtime, monkeypatch):
    owner[1][0] = replace(owner[2], available_memory_mb=64)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', lambda *a, **kw: pytest.fail('cancelled admission launched'))
    signal = threading.Event()
    timer = threading.Timer(.05, signal.set)
    timer.start()
    try:
        result = run(owner, runtime, timeout_seconds=1, cancellation=signal)
    finally:
        timer.join()
    assert result.status == 'cancelled' and result.observation is None and result.elapsed_seconds < .5


def test_fresh_child_admission_rechecks_pressure_after_preparation(owner, runtime, monkeypatch):
    original = execution.prepare_isabelle_runtime
    def prepared(**kwargs):
        result = original(**kwargs)
        assert result.usable
        owner[1][0] = replace(owner[2], available_memory_mb=64)
        return result
    monkeypatch.setattr(execution, 'prepare_isabelle_runtime', prepared)
    result = run(owner, runtime, mode='check', source=SOURCE, timeout_seconds=.5)
    assert result.status == 'timed_out' and result.preparation.usable and result.observation is None


@pytest.mark.parametrize('failure', ['cancel','late','runtime_drift','command','truncated','resource','malformed_flag'])
def test_late_or_misbound_native_success_cannot_complete(owner, runtime, monkeypatch, failure):
    clock = [0.0]
    signal = threading.Event()
    if failure=='late':
        from types import SimpleNamespace
        monkeypatch.setattr(execution, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    original = process.BoundedToolRunner.run
    def observed(self, request, **kwargs):
        result = original(self, request, **kwargs)
        if 'ExactInput.thy' in request.input_files:
            assert result.returncode == 0
            if failure=='cancel': signal.set()
            elif failure=='late': clock[0]=31
            elif failure=='runtime_drift': (runtime[1]/'etc/settings').write_text('changed')
            elif failure=='command': result=replace(result, command=(*result.command,'wrong'))
            elif failure=='truncated': result=replace(result, output_truncated=True)
            elif failure=='resource': result=replace(result, resource_exhausted=True)
            elif failure=='malformed_flag': result=replace(result, workspace_cleaned=1)
        return result
    monkeypatch.setattr(process.BoundedToolRunner, 'run', observed)
    result = run(owner, runtime, mode='check', source=SOURCE, cancellation=signal)
    assert not result.completed and result.observation is not None
    assert result.observation.returncode == 0
    assert result.to_dict()['grants_proof_authority'] is False


def test_nonzero_theory_exit_remains_operational_evidence_without_proof_authority(owner, runtime):
    (runtime[1]/'behavior').write_text('exit_one')
    result = run(owner, runtime, mode='check', source=SOURCE)
    assert result.completed and result.observation.returncode == 1
    assert result.to_dict()['grants_proof_authority'] is False


def test_cpu_budget_caps_whole_operation_and_native_cpu(owner, runtime, monkeypatch):
    seen = []
    original = process.SubprocessExecutor.execute
    def observed(self, invocation, cancellation=None):
        seen.append(invocation.limits)
        return original(self, invocation, cancellation)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', observed)
    result = run(owner, runtime, mode='check', source=SOURCE, timeout_seconds=30, cpu_seconds=2)
    assert result.completed, result.to_dict()
    assert result.limits['effective_wall_timeout_seconds'] == 2
    assert all(0 < limits.cpu_seconds <= 2 and limits.timeout_seconds <= 2 for limits in seen)


@pytest.mark.parametrize('missing', ['distribution','selected_file','explicit_executable','pressure'])
def test_installation_opt_in_only_applies_to_missing_distribution(owner, runtime, monkeypatch, tmp_path, missing):
    target = tmp_path/'first-use'
    calls = []
    def install(**kwargs):
        calls.append(kwargs)
        assert kwargs['parent_lease'].memory_mb == 2304
        assert not kwargs['parent_lease'].released and 0 < kwargs['timeout_seconds'] <= 2
        make_runtime(target)
        return installation.IsabelleInstallationReceipt(status='installed', installed=True, preparation={'usable':True})
    monkeypatch.setattr(installation, 'ensure_isabelle_installation', install)
    kwargs = {'install_root': target}
    if missing=='selected_file':
        kwargs = {'install_root': runtime[0]}
        (runtime[1]/'etc/settings').unlink()
    elif missing=='explicit_executable':
        kwargs = {'executable':target/'bin/isabelle'}
    elif missing=='pressure':
        owner[1][0] = replace(owner[2], available_memory_mb=64)
    result = execution.run_isabelle_operation(mode='check', source=SOURCE, scheduler=owner[0],
        auto_install=True, timeout_seconds=.08 if missing=='pressure' else 2, **kwargs)
    assert len(calls) == (1 if missing=='distribution' else 0)
    assert result.completed is (missing=='distribution'), result.to_dict()


def test_unready_hol_is_not_downgraded_into_installation(owner, runtime, monkeypatch):
    (runtime[1]/'behavior').write_text('missing_hol')
    monkeypatch.setattr(installation, 'ensure_isabelle_installation', lambda **kw: pytest.fail('unready HOL auto-installed'))
    result = run(owner, runtime, mode='check', source=SOURCE, auto_install=True)
    assert result.status == 'unavailable' and result.reason_code == 'hol_heap_build_required'


def test_late_admission_releases_envelope_without_starting_a_probe(owner, runtime, monkeypatch):
    from types import SimpleNamespace
    clock = [0.0]
    monkeypatch.setattr(execution, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    original = owner[0].acquire
    def late(*args, **kwargs):
        lease = original(*args, **kwargs)
        clock[0] = 31
        return lease
    monkeypatch.setattr(owner[0], 'acquire', late)
    monkeypatch.setattr(profile, 'resolve_runtime', lambda **kw: pytest.fail('late admission probed runtime'))
    result = run(owner, runtime)
    assert result.status == 'timed_out' and result.resource_lease_id
    assert result.observation is result.preparation is None
    assert result.ownership['operation_release_requested'] is True


def test_live_theory_cancellation_reaps_worker_before_releasing_operation(owner, runtime):
    (runtime[1]/'behavior').write_text('slow')
    cancel, stop = threading.Event(), threading.Event()
    def interrupt():
        deadline = time.monotonic()+3
        while not stop.is_set() and time.monotonic()<deadline:
            if (runtime[1]/'started').exists():
                cancel.set()
                return
            stop.wait(.005)
        cancel.set()
    thread = threading.Thread(target=interrupt)
    thread.start()
    try:
        result = run(owner, runtime, mode='check', source=SOURCE, timeout_seconds=5, cancellation=cancel)
    finally:
        stop.set()
        thread.join(2)
    assert not thread.is_alive() and (runtime[1]/'started').exists()
    assert result.status == 'cancelled' and result.observation is not None
    assert result.observation.cancelled and result.observation.process_tree_terminated
    assert result.observation.workspace_cleaned
    assert result.ownership['operation_release_requested'] is True
