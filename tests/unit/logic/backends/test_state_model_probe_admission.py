"""State-model identity/help probes use bounded private resource admission."""
from dataclasses import replace
from pathlib import Path
import os
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process, resource_admission
from ipfs_datasets_py.logic.backends.installers import state_model as model
from ipfs_datasets_py.logic.backends.smt import operation_budget as budget
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources

MIB = 1024**2
HELP = 'TLC - provides model checking and simulation of TLA+ specifications - Version fixture\nSYNOPSIS\nDESCRIPTION'
REAL_EXECUTE = process.SubprocessExecutor.execute


@pytest.fixture
def host(tmp_path, monkeypatch):
    healthy = ProofHostResources(8, 8192, 8192, pid_task_limit=8192, available_pid_tasks=8192)
    current = [healthy]
    def sample():
        if isinstance(current[0], Exception):
            raise current[0]
        return current[0]
    owner = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / 'runtime-pool.json', proof_resource_sampler=sample,
        total_cpu_slots=2, total_memory_mb=2048, total_child_process_slots=6,
        proof_memory_headroom_mb=64, lane_reservations={}, auto_renew_leases=False,
        proof_backoff_seconds=.025, poll_interval_seconds=.002))
    monkeypatch.setattr(resource_admission, 'get_global_resource_scheduler', lambda: owner)
    monkeypatch.setattr(model, 'expand_user_local_root',
        lambda root=None: Path(root) if root is not None else tmp_path / 'managed')
    calls, workspaces = [], []
    def clean(invocation, signal):
        return process.RawProcessResult(returncode=1 if invocation.argv[-1]=='-help' else 0,
            stdout=HELP if invocation.argv[-1]=='-help' else '0.58.3')
    action = [clean]
    def execute(self, invocation, cancellation=None):
        state = owner.snapshot()
        assert state['active_lease_count'] > 0
        assert state['allocated']['memory_mb'] >= 512
        assert invocation.cwd.is_dir() and not cancellation.is_set()
        calls.append((invocation, cancellation, state)); workspaces.append(invocation.cwd)
        return action[0](invocation, cancellation)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', execute)
    opaque = tmp_path / 'opaque-launcher'
    opaque.write_text('#!/bin/sh\nexit 0\n'); opaque.chmod(0o700)
    jar = tmp_path / 'tla2tools.jar'; jar.write_bytes(b'identity-validation-is-separate')
    yield SimpleNamespace(owner=owner, healthy=healthy, current=current, calls=calls,
        action=action, clean=clean, workspaces=workspaces, opaque=opaque, jar=jar)
    state = owner.snapshot()
    assert state['active_lease_count'] == state['waiting_request_count'] == 0
    assert all(not path.exists() for path in workspaces)
    assert model._JAVA_PROBE_OPERATION.get() is None


def run(host, route='tlc', **kwargs):
    if route == 'tlc':
        return model.probe_tlc_runtime(executable=str(host.opaque), **kwargs)
    if route == 'tlc_banner':
        return model.read_tlc_version_banner(str(host.opaque), **kwargs)
    if route == 'apalache':
        return model.probe_apalache_runtime(str(host.opaque), **kwargs)
    if route == 'apalache_banner':
        return model.read_apalache_version_banner(str(host.opaque), **kwargs)
    if route == 'jar':
        return model.probe_tlc_runtime(jar_path=host.jar, java_executable=sys.executable, **kwargs)
    raise AssertionError(route)


def usable(result):
    return result.usable if isinstance(result, model.RuntimeCommandProbe) else result is not None


def until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail('bounded fixture wait expired')
        time.sleep(.003)


@pytest.mark.parametrize('route,processes', [('tlc',3), ('tlc_banner',3), ('apalache',3), ('apalache_banner',3), ('jar',1)])
def test_default_routes_admit_fixed_rss_cpu_process_and_finite_virtual_limits(host, route, processes):
    result = run(host, route)
    assert usable(result)
    invocation, signal, state = host.calls[0]
    assert state['active_root_lease_count'] == state['active_lease_count'] == 1
    assert state['allocated']['cpu_slots'] == 1 and state['allocated']['memory_mb'] == 512
    assert state['allocated_child_process_slots'] == processes
    assert invocation.limits.resident_memory_bytes == 512*MIB
    assert invocation.limits.memory_bytes == 4096*MIB
    assert 0 < invocation.limits.timeout_seconds <= 20
    assert invocation.limits.max_output_bytes == 65536
    assert signal.is_set()  # Released lease; it was live inside the executor.
    if isinstance(result, model.RuntimeCommandProbe):
        assert set(result.to_dict()) == {'command','returncode','output','usable','reason_code'}
        assert result.returncode == (0 if route=='apalache' else 1)


@pytest.mark.parametrize('route', ['tlc','tlc_banner','apalache','apalache_banner'])
def test_inherited_jvm_arguments_cannot_override_owned_resource_profile(host, monkeypatch, route):
    for name in (*model.JAVA_OPTION_ENV_VARS, 'JVM_ARGS', 'JVM_GC_ARGS'):
        monkeypatch.setenv(name, '-Xmx999g -XX:ActiveProcessorCount=99 -javaagent:fixture.jar')
    assert usable(run(host, route, java_executable=sys.executable))
    environment = host.calls[0][0].environment
    assert not any(name in environment for name in model.JAVA_OPTION_ENV_VARS)
    assert '-Xmx256m' in environment['JVM_ARGS']
    assert '-XX:ActiveProcessorCount=1' in environment['JVM_ARGS']
    assert '-javaagent' not in environment['JVM_ARGS']
    assert '999' not in environment['JVM_GC_ARGS']
    assert environment['PATH'].split(os.pathsep)[0] == str(Path(sys.executable).resolve().parent)


@pytest.mark.parametrize('route', ['tlc','tlc_banner','jar'])
@pytest.mark.parametrize('failure', [
    {'timed_out':True}, {'cancelled':True}, {'output_truncated':True},
    {'resource_exhausted':True}, {'process_tree_terminated':True}, {'error':'incomplete cleanup'},
])
def test_partial_help_from_unsafe_native_lifecycle_never_becomes_usable(host, route, failure):
    def execute(invocation,signal):
        if len(host.calls)==1:
            return process.RawProcessResult(returncode=1,stdout=HELP,**failure)
        return host.clean(invocation,signal)
    host.action[0] = execute
    controls = {'jar_path':host.jar,'java_executable':sys.executable} if route=='tlc_banner' else {}
    actual = run(host, route, **controls)
    assert not usable(actual)
    if isinstance(actual, model.RuntimeCommandProbe):
        assert actual.returncode is None and actual.output == ''
    assert len(host.calls) == 1


@pytest.mark.parametrize('field', ['workspace_cleaned','workspace_limit_exceeded','unavailable'])
def test_workspace_failure_cannot_be_reclassified_as_tlc_help(host, monkeypatch, field):
    original = resource_admission.ResourceAdmittedToolRunner.run
    def unsafe(self, *args, **kwargs):
        return replace(original(self,*args,**kwargs), **{field:field!='workspace_cleaned'})
    monkeypatch.setattr(resource_admission.ResourceAdmittedToolRunner,'run',unsafe)
    assert not run(host).usable


def test_combined_output_cap_cannot_be_evaded_by_two_pipes(host):
    host.action[0] = lambda *args: process.RawProcessResult(returncode=1, stdout=HELP+'x'*40000, stderr='y'*40000)
    actual = run(host)
    assert not actual.usable and actual.output == '' and actual.returncode is None


@pytest.mark.parametrize('output,code,reason', [
    ('0.58.3',1,'runtime_probe_nonzero_exit'), ('Apalache 0.58.3',0,'runtime_version_unreadable'),
    ('0.58.2',0,'runtime_version_mismatch'), ('',0,'runtime_probe_empty_output'),
])
def test_apalache_preserves_exact_version_and_clean_exit_requirement(host, output, code, reason):
    host.action[0] = lambda *args: process.RawProcessResult(returncode=code, stdout=output)
    result = run(host,'apalache')
    assert not result.usable and result.reason_code == reason
    assert result.returncode == code


def canonical(host, tmp_path, *, java=sys.executable):
    return model.write_launcher('tlc',host.jar, install_root=tmp_path/'canonical',
        java_jar=host.jar, java_main='tlc2.TLC', java_executable=java,
        environment={'TLA2TOOLS_JAR':str(host.jar)})


def test_canonical_launcher_is_expanded_truthfully_without_rewriting_installed_bytes(host, tmp_path):
    path = canonical(host,tmp_path)
    before = path.read_bytes()
    command = model._canonical_tlc_probe_command(str(path),java_executable=sys.executable)
    assert command is not None
    assert command[0] == str(Path(sys.executable).resolve())
    assert '-Xmx256m' in command and '-XX:ActiveProcessorCount=1' in command
    assert command[-4:] == ('-cp',str(host.jar),'tlc2.TLC','-help')
    result = model.probe_tlc_runtime(executable=str(path),java_executable=sys.executable)
    assert result.usable and result.command == command
    assert host.calls[0][2]['allocated_child_process_slots'] == 1
    assert path.read_bytes() == before
    assert model._launcher_identity(path,expected_body=before.decode())['structural_match']


@pytest.mark.parametrize('variant', ['extra_line','alternate_whitespace','oversize','symlink','java_mismatch','nonexecutable'])
def test_canonical_recognition_rejects_near_match_and_unsafe_file_shapes(host,tmp_path,variant):
    path = canonical(host,tmp_path)
    if variant=='extra_line':
        path.write_text(path.read_text()+'echo extra\n')
    elif variant=='alternate_whitespace':
        path.write_text(path.read_text().replace('set -euo pipefail','set  -euo pipefail'))
    elif variant=='oversize':
        path.write_text(path.read_text()+'#'*(model.STATE_MODEL_LAUNCHER_MAX_BYTES+1))
    elif variant=='symlink':
        alias=tmp_path/'alias';alias.symlink_to(path);path=alias
    elif variant=='nonexecutable':
        path.chmod(0o600)
    selected_java='/different/java' if variant=='java_mismatch' else sys.executable
    assert model._canonical_tlc_probe_command(str(path),java_executable=selected_java) is None
    assert not host.calls
    if variant not in {'nonexecutable','java_mismatch'}:
        result=model.probe_tlc_runtime(executable=str(path),java_executable=sys.executable)
        assert result.usable
        assert host.calls[0][2]['allocated_child_process_slots']==3
        assert '-Xmx256m' not in host.calls[0][0].argv


def test_fifo_recognition_is_nonblocking_and_does_not_read_or_launch(host,tmp_path,monkeypatch):
    fifo=tmp_path/'fifo';os.mkfifo(fifo);fifo.chmod(0o700)
    original=os.open;seen=[]
    def opened(path,flags,*args,**kwargs):
        if os.fspath(path)==str(fifo):
            seen.append(flags)
            assert flags & os.O_NONBLOCK and flags & os.O_NOFOLLOW
        return original(path,flags,*args,**kwargs)
    monkeypatch.setattr(model.os,'open',opened)
    started=time.monotonic()
    assert model._canonical_tlc_probe_command(str(fifo),java_executable=sys.executable) is None
    assert time.monotonic()-started<.5
    assert not host.calls


def test_opaque_launcher_keeps_original_argv_and_reserves_script_process_profile(host):
    result=run(host)
    assert result.command==(str(host.opaque),'-help')
    assert host.calls[0][2]['allocated_child_process_slots']==3


@pytest.fixture
def fakeclock(monkeypatch):
    now=[100.0];module=SimpleNamespace(monotonic=lambda:now[0])
    monkeypatch.setattr(model,'time',module);monkeypatch.setattr(budget,'time',module)
    monkeypatch.setattr(resource_admission,'time',module)
    return now


def test_fallback_uses_one_deadline_and_selected_java(host,fakeclock):
    def execute(invocation,signal):
        fakeclock[0]+=.4
        if len(host.calls)==1:
            return process.RawProcessResult(returncode=7,stdout='not TLC help')
        return host.clean(invocation,signal)
    host.action[0]=execute
    result=model.read_tlc_version_banner(str(host.opaque),jar_path=host.jar,
        java_executable=sys.executable,timeout=1)
    assert result==HELP and len(host.calls)==2
    assert 0<host.calls[1][0].limits.timeout_seconds<=.601
    assert host.calls[1][0].limits.cpu_seconds==pytest.approx(.6)
    assert host.calls[1][2]['allocated_child_process_slots']==1


@pytest.mark.parametrize('stop',['cancel','timeout'])
def test_stopped_first_launcher_never_falls_back_to_jar(host,fakeclock,stop):
    event=threading.Event()
    def execute(invocation,signal):
        if stop=='cancel':
            event.set();assert signal.is_set();event.clear()
        else:
            fakeclock[0]+=.101
        return process.RawProcessResult(returncode=7,stdout='not help')
    host.action[0]=execute
    result=model.read_tlc_version_banner(str(host.opaque),jar_path=host.jar,
        java_executable=sys.executable,timeout=.1,cancellation=event)
    assert result is None and len(host.calls)==1


@pytest.mark.parametrize('route',['tlc','tlc_banner','apalache','apalache_banner','jar'])
def test_precancel_skips_every_native_route(host,route):
    event=threading.Event();event.set()
    assert not usable(run(host,route,cancellation=event))
    assert not host.calls


@pytest.mark.parametrize('route',['tlc','apalache'])
def test_late_semantic_normalization_cannot_return_usable(host,fakeclock,monkeypatch,route):
    if route=='tlc':
        original=model._tlc_help_probe
        def late(value):
            result=original(value);fakeclock[0]+=.101;return result
        monkeypatch.setattr(model,'_tlc_help_probe',late)
    else:
        original=model._ANSI_ESCAPE_RE
        class LatePattern:
            def sub(self,*args):
                result=original.sub(*args);fakeclock[0]+=.101;return result
        monkeypatch.setattr(model,'_ANSI_ESCAPE_RE',LatePattern())
    assert not usable(run(host,route,timeout=.1))


@pytest.mark.parametrize('stop',['cancel','timeout'])
def test_ambient_stop_raises_only_after_native_cleanup(host,fakeclock,stop):
    event=threading.Event()
    def execute(invocation,signal):
        if stop=='cancel':
            event.set();assert signal.is_set();event.clear()
        else:
            fakeclock[0]+=.051
        return host.clean(invocation,signal)
    host.action[0]=execute
    with pytest.raises(budget.ProofOperationCancelled if stop=='cancel' else budget.ProofOperationTimeout):
        with budget.proof_operation_scope(timeout_ms=50,cancellation=event):
            run(host,timeout=2)
    assert host.owner.snapshot()['active_lease_count']==0
    assert all(not path.exists() for path in host.workspaces)
    assert host.calls[0][0].limits.timeout_seconds<=.051


@pytest.mark.parametrize('changes,reason',[
    ({'available_memory_mb':32},'proof_memory_headroom'),
    ({'cpu_stall_percent':90},'proof_cpu_stall'),
    ({'available_pid_tasks':0},'proof_pid_headroom'),
    (None,'proof_resource_telemetry_unknown'),
])
def test_pressure_queue_cancellation_prevents_launch_and_drains(host,changes,reason):
    host.current[0]=replace(host.healthy,**changes) if changes else OSError('telemetry unavailable')
    event,outcomes=threading.Event(),[]
    worker=threading.Thread(target=lambda:outcomes.append(run(host,timeout=2,cancellation=event)))
    worker.start()
    try:
        until(lambda:host.owner.snapshot()['proof_backoff'].get('reason')==reason)
        assert not host.calls
        event.set();worker.join(3)
        assert not worker.is_alive() and len(outcomes)==1 and not usable(outcomes[0])
    finally:
        event.set();worker.join(3)


def test_pressure_recovery_consumes_same_execution_budget(host):
    host.current[0]=replace(host.healthy,cpu_stall_percent=90);outcomes=[]
    worker=threading.Thread(target=lambda:outcomes.append(run(host,timeout=1)))
    worker.start()
    try:
        until(lambda:host.owner.snapshot()['waiting_request_count']==1)
        time.sleep(.04);host.current[0]=host.healthy;worker.join(2)
        assert not worker.is_alive() and usable(outcomes[0])
        assert 0<host.calls[0][0].limits.timeout_seconds<.98
    finally:
        host.current[0]=host.healthy;worker.join(3)


@pytest.mark.parametrize('route,slots',[('tlc',3),('jar',1),('apalache',3)])
def test_parent_ownership_allocates_child_without_double_charge(host,monkeypatch,route,slots):
    monkeypatch.setattr(resource_admission,'get_global_resource_scheduler',lambda:pytest.fail('nested run used global owner'))
    with host.owner.acquire('orchestration',cpu_slots=1,memory_mb=512,child_process_slots=slots,timeout=0) as parent:
        assert usable(run(host,route,parent_lease=parent))
        state=host.calls[0][2]
        assert state['active_root_lease_count']==1 and state['active_lease_count']==2
        assert state['allocated']['memory_mb']==512 and state['allocated_child_process_slots']==slots
        assert host.owner.snapshot()['active_lease_count']==1 and not parent.released


def test_underfunded_parent_cannot_silently_shrink_script_request(host):
    with host.owner.acquire('orchestration',cpu_slots=1,memory_mb=512,child_process_slots=1,timeout=0) as parent:
        assert not usable(run(host,parent_lease=parent,timeout=.05))
        assert not host.calls and not parent.released


def test_default_configuration_failure_does_not_fallback_to_unadmitted_process(host,monkeypatch):
    def fail():
        raise ValueError('incompatible configuration fixture')
    monkeypatch.setattr(resource_admission,'get_global_resource_scheduler',fail)
    assert not usable(run(host)) and not host.calls


@pytest.mark.parametrize('route',['tlc','tlc_banner','apalache','apalache_banner'])
@pytest.mark.parametrize('timeout',[0,-1,True,float('nan'),float('inf')])
def test_invalid_timeouts_never_launch(host,route,timeout):
    with pytest.raises(ValueError):
        run(host,route,timeout=timeout)
    assert not host.calls


def test_legacy_injected_transport_seam_does_not_receive_new_none_keywords(host,monkeypatch):
    seen=[]
    def old(command,*,timeout,java_executable=None):
        seen.append((command,timeout,java_executable))
        return model.RuntimeCommandProbe(tuple(command),1,HELP,False,'runtime_probe_nonzero_exit')
    monkeypatch.setattr(model,'_run_runtime_command',old)
    assert run(host).usable
    assert len(seen)==1 and not host.calls


def test_relative_jar_is_resolved_before_switch_to_private_workspace(host,tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    result=model.probe_tlc_runtime(jar_path=Path('tla2tools.jar'),java_executable=sys.executable)
    assert result.usable
    assert result.command[-3]==str(host.jar)
    assert host.calls[0][0].argv[-3]==str(host.jar)
    assert host.calls[0][0].cwd!=tmp_path


def test_canonical_launcher_recognition_preserves_spaces_and_single_quotes(host,tmp_path):
    location=tmp_path / "a path's launcher"
    host.jar=tmp_path / "a jar's path.jar"
    host.jar.write_bytes(b"fixture")
    path=canonical(host,location)
    command=model._canonical_tlc_probe_command(str(path),java_executable=sys.executable)
    assert command is not None and command[-3]==str(host.jar)
    assert model.probe_tlc_runtime(executable=str(path),java_executable=sys.executable).usable


def test_changed_launcher_during_read_cannot_be_recognized(host,tmp_path,monkeypatch):
    path=canonical(host,tmp_path)
    original=os.read
    def changed(descriptor,count):
        value=original(descriptor,count)
        path.write_text(path.read_text()+'# replaced during bounded read\n')
        return value
    monkeypatch.setattr(model.os,'read',changed)
    assert model._canonical_tlc_probe_command(str(path),java_executable=sys.executable) is None
    assert not host.calls


@pytest.mark.parametrize('failure',['timed_out','cancelled','resource_exhausted','output_truncated'])
def test_partial_apalache_version_cannot_publish_success(host,failure):
    host.action[0]=lambda *args:process.RawProcessResult(returncode=0,stdout='0.58.3',**{failure:True})
    assert not run(host,'apalache').usable
    assert model.read_apalache_version_banner(str(host.opaque)) is None


def test_readers_preserve_old_injected_probe_signature(host,monkeypatch):
    seen=[]
    def old(*,executable=None,jar_path=None,java_executable=None,timeout=15):
        seen.append(timeout)
        return model.RuntimeCommandProbe((executable,'-help'),1,HELP,True)
    monkeypatch.setattr(model,'probe_tlc_runtime',old)
    assert run(host,'tlc_banner')==HELP
    assert len(seen)==1 and not host.calls


def test_foreign_lease_is_untouched_and_cleanup_precedes_own_release(host,monkeypatch):
    original=host.owner.release
    def release(*args,**kwargs):
        assert all(not path.exists() for path in host.workspaces)
        return original(*args,**kwargs)
    with host.owner.acquire('orchestration',cpu_slots=1,memory_mb=128,child_process_slots=1,timeout=0):
        monkeypatch.setattr(host.owner,'release',release)
        assert run(host).usable
        assert host.calls[0][2]['active_root_lease_count']==2
        assert host.owner.snapshot()['active_lease_count']==1


@pytest.mark.parametrize('cancel',[False,True],ids=['help-exit-one','cancel-after-help'])
def test_real_local_support_process_cleanup_and_partial_help_withholding(host,tmp_path,monkeypatch,cancel):
    pidfile=tmp_path/'probe.pid';executable=tmp_path/'support-fixture'
    executable.write_text('#!'+sys.executable+'\nimport os,time,sys\n'
        +'open('+repr(str(pidfile))+',"w").write(str(os.getpid()))\n'
        +'print('+repr(HELP)+',flush=True)\n'+('time.sleep(10)\n' if cancel else '')+'sys.exit(1)\n')
    executable.chmod(0o700)
    observations=[]
    def execute(self,invocation,cancellation=None):
        assert host.owner.snapshot()['active_lease_count']==1
        host.workspaces.append(invocation.cwd)
        result=REAL_EXECUTE(self,invocation,cancellation);observations.append(result);return result
    monkeypatch.setattr(process.SubprocessExecutor,'execute',execute)
    event,outcomes=threading.Event(),[]
    worker=threading.Thread(target=lambda:outcomes.append(model.probe_tlc_runtime(
        executable=str(executable),timeout=3,cancellation=event)))
    worker.start()
    try:
        until(pidfile.exists)
        if cancel:event.set()
        worker.join(4)
        assert not worker.is_alive() and len(outcomes)==1 and len(observations)==1
        assert outcomes[0].usable is (not cancel)
        if cancel:
            assert outcomes[0].output=='' and outcomes[0].returncode is None
            assert observations[0].cancelled and observations[0].process_tree_terminated
        assert not Path('/proc/'+pidfile.read_text()).exists()
    finally:
        event.set();worker.join(4)


def test_incomplete_local_probe_does_not_cancel_unrelated_ambient_work(host):
    host.action[0]=lambda *args:process.RawProcessResult(returncode=1,stdout=HELP,cancelled=True)
    with budget.proof_operation_scope(timeout_ms=2000) as operation:
        assert not run(host).usable
        operation.checkpoint('larger caller operation is still live')
        host.action[0]=host.clean
        assert run(host).usable


@pytest.mark.parametrize('control',[{'scheduler':object()},{'parent_lease':object()}])
def test_invalid_owner_control_does_not_launch_or_retry(host,control):
    with pytest.raises(TypeError):
        run(host,**control)
    assert not host.calls


def test_missing_launcher_discovery_can_fall_back_to_valid_explicit_jar(host,tmp_path):
    result=model.read_tlc_version_banner(str(tmp_path/'missing-tlc'),jar_path=host.jar,
        java_executable=sys.executable,timeout=1)
    assert result==HELP
    assert len(host.calls)==1
    assert host.calls[0][0].argv[-3]==str(host.jar)
    assert host.calls[0][2]['allocated_child_process_slots']==1
