"""Hyper engine admission and lifecycle integrity with private fake execution.

These cases qualify dispatch and resource accounting, not native engine syntax,
semantic counterexample replay, scaling, or hard aggregate containment.
"""
from dataclasses import replace
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process, registry, resource_admission as admission
from ipfs_datasets_py.logic.backends.hyperproperties import adapters as hyper, execution_v2 as v2
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.backends.smt import operation_budget as budget
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import stable_digest
from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest, ExecutionBounds, QueryKind
from ipfs_datasets_py.logic.software_verification.hyperproperties import (
    HyperpropertyIR, InformationFlowPolicy, ObservationKind, ObservationSpec,
    SecurityLabel, SecurityLevel, SelfCompositionBound,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


MIB = 1024**2
BACKENDS = {'hyperltl': hyper.HyperLTLBackend, 'autohyper': hyper.AutoHyperBackend,
            'mchyper': hyper.MCHyperBackend}
SUCCESS = {'hyperltl': 'sat\n', 'autohyper': 'SAT\n',
           'mchyper': 'Property proved. Time = 0.01 sec\n'}
VIOLATION = {'hyperltl': 'unsat\n', 'autohyper': 'UNSAT\n',
             'mchyper': 'Counterexample found. Safety violation.\n'}
AIGER = 'aag 1 1 0 1 0\n2\n2\ni0 user_id\no0 status\nc\nfixture\n'
TRACE = ('TRACE pi1:\n  public.user_id = alice\n  obs.status = ok\n'
         'TRACE pi2:\n  public.user_id = alice\n  obs.status = leak\n'
         'DIFF field=status left=ok right=leak\n')


def document():
    policy = InformationFlowPolicy(policy_id='policy:hyper:admission',
        low_input_fields=('user_id',), high_input_fields=('secret',),
        observation_fields=('status',),
        labels=(SecurityLabel('label:user', 'user_id', SecurityLevel.LOW, ObservationKind.INPUT),
                SecurityLabel('label:secret', 'secret', SecurityLevel.HIGH, ObservationKind.INPUT),
                SecurityLabel('label:status', 'status', SecurityLevel.LOW, ObservationKind.OUTPUT)),
        observations=(ObservationSpec('obs:status', 'status', ObservationKind.OUTPUT, SecurityLevel.LOW),))
    return HyperpropertyIR.noninterference_document(policy=policy,
        bound=SelfCompositionBound('bound:hyper:admission', max_traces=4, max_pairs=6, max_steps=16))


def request(engine='hyperltl', *, timeout_ms=2000, memory=128*MIB, output=8192):
    payload = {'document': document().to_dict()}
    if engine == 'mchyper':
        payload['system_model'] = AIGER
    return BackendRequest(request_id='request:hyper:admission', claim_id='claim:hyper:admission',
        declaration_id='declaration:hyper', claim_digest='1'*64,
        obligation_id='obligation:hyper', obligation_digest='2'*64,
        assumption_ids=('assumption:bounded',), logic_family='hyperproperty',
        query_kind=QueryKind.SATISFIABILITY, requested_backend_id=engine,
        bounds=ExecutionBounds(timeout_ms=timeout_ms, max_memory_bytes=memory,
                               max_output_bytes=output, max_steps=100), payload=payload)


def typed_request(engine, **bounds):
    return v2.HyperExecutionRequestV2(request_id='request:hyper:v2:admission',
        provider=engine, document=document(), bounds=request(engine, **bounds).bounds,
        system_model=AIGER if engine == 'mchyper' else None)


def forbidden(*args, **kwargs):
    pytest.fail('Hyper fixture reached host execution, shared pool, or forbidden verdict parsing')


@pytest.fixture(autouse=True)
def no_native_or_shared_pool(monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', forbidden)
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', forbidden)


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    fake = SimpleNamespace(monotonic=lambda: now[0])
    for module in (admission, registry, budget):
        monkeypatch.setattr(module, 'time', fake)
    return now


@pytest.fixture
def host(tmp_path, monkeypatch):
    healthy = ProofHostResources(8, 8192, 8192, pid_task_limit=8192, available_pid_tasks=8192)
    current = [healthy]
    def sample():
        if isinstance(current[0], Exception):
            raise current[0]
        return current[0]
    owner = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path/'private-hyper-pool.json', proof_resource_sampler=sample,
        total_cpu_slots=4, total_memory_mb=1024, total_child_process_slots=8,
        proof_memory_headroom_mb=64, lane_reservations={}, auto_renew_leases=False,
        proof_backoff_seconds=.01, poll_interval_seconds=.002))
    calls, prepared, acquired, resolutions = [], [], [], []
    def resolve():
        resolutions.append(True)
        return owner
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', resolve)
    monkeypatch.setattr(process.shutil, 'which', lambda *args, **kwargs: sys.executable)
    # The adapter captures shutil.which in a keyword default at import time.
    # Replace only that lookup seam; keep default runner construction intact.
    monkeypatch.setitem(hyper.HyperpropertyBackend.__init__.__kwdefaults__, 'which',
                        lambda name: sys.executable)
    original_acquire = owner.acquire
    def acquire(*args, **kwargs):
        lease = original_acquire(*args, **kwargs)
        acquired.append(lease)
        return lease
    monkeypatch.setattr(owner, 'acquire', acquire)
    original_write = process.BoundedToolRunner._write_inputs
    def write(workspace, tool_request):
        prepared.append(workspace)
        return original_write(workspace, tool_request)
    monkeypatch.setattr(process.BoundedToolRunner, '_write_inputs', staticmethod(write))
    action = [lambda invocation, signal: process.RawProcessResult(returncode=0, stdout=SUCCESS['hyperltl'])]
    def execute(self, invocation, cancellation=None):
        snapshot = owner.snapshot()
        assert snapshot['active_lease_count'] >= 1
        assert cancellation is not None and not cancellation.is_set()
        assert '--version' not in invocation.argv
        assert any((invocation.cwd/name).is_file() for name in ('property.hltl', 'system.aag'))
        calls.append((invocation, cancellation, snapshot, budget.current_proof_operation()))
        return action[0](invocation, cancellation)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', execute)
    yield SimpleNamespace(owner=owner, healthy=healthy, current=current, calls=calls,
        prepared=prepared, acquired=acquired, resolutions=resolutions, action=action, tmp=tmp_path)
    snapshot = owner.snapshot()
    assert snapshot['active_lease_count'] == snapshot['waiting_request_count'] == 0
    assert all(not path.exists() for path in prepared)


@pytest.mark.parametrize('engine', BACKENDS)
@pytest.mark.parametrize('route', ['direct', 'v2'])
@pytest.mark.parametrize('violated', [False, True])
def test_default_routes_reserve_requested_bounds_once_and_preserve_authority(host, engine, route, violated):
    stdout = (VIOLATION[engine]+TRACE) if violated else SUCCESS[engine]
    host.action[0] = lambda invocation, signal: process.RawProcessResult(returncode=0, stdout=stdout)
    req = request(engine, memory=129*MIB+1); before = req.to_dict()
    status = ResultStatus.VIOLATED if violated else ResultStatus.SATISFIED
    if route == 'direct':
        outcome = BACKENDS[engine]().run(req)
        result = outcome.result
        assert outcome.request_digest == req.digest and outcome.receipt.external_tool_proof
        assert outcome.receipt.tool_version == '' and not outcome.receipt.authorizes_universal_proof
        assert outcome.translation.document_digest == outcome.receipt.document_digest
        assert outcome.translation.translation_digest == outcome.receipt.translation_digest
        assert (outcome.receipt.counterexample is not None) is violated
    else:
        encoded = typed_request(engine, memory=129*MIB+1)
        wire = encoded.to_dict()
        outcome = v2.HyperExecutionEngineV2().execute(encoded)
        result = outcome.backend_result
        assert outcome.evidence.hyperproperty_established and not outcome.evidence.authorizes_universal_proof
        assert outcome.evidence.engine.value == engine
        assert encoded.to_dict() == wire
    assert result.status is status and result.authority is ResultAuthority.HYPERPROPERTY
    assert result.translation_ceiling is EvidenceAuthority.BOUNDED and result.bounds == req.bounds
    assert result.metadata['process']['workspace_cleaned']
    assert req.to_dict() == before
    assert len(host.calls) == len(host.prepared) == len(host.acquired) == len(host.resolutions) == 1
    invocation, _, snapshot, _ = host.calls[0]
    assert snapshot['active_lease_count'] == snapshot['active_root_lease_count'] == 1
    assert snapshot['allocated'] == {'cpu_slots': 2, 'memory_mb': 130}
    assert snapshot['allocated_child_process_slots'] == 4 and host.acquired[0].released
    assert invocation.limits.resident_memory_bytes == req.bounds.max_memory_bytes
    assert invocation.limits.memory_bytes == (4096 if engine == 'autohyper' else 2048)*MIB
    assert 0 < invocation.limits.timeout_seconds <= 2
    if route == 'v2':
        assert 0 < invocation.limits.cpu_seconds <= 2
        assert host.calls[0][3] is not None
    else:
        assert invocation.limits.cpu_seconds == 2
    assert invocation.limits.max_output_bytes == 8192
    assert invocation.limits.enforce_file_size_limit is (engine != 'autohyper')


def test_registry_default_hyperltl_route_preserves_typed_payload_without_authority_upgrade(host):
    req = replace(request(), requested_backend_id='hyperltl_autohyper_mchyper')
    attempt, result = registry.default_backend_registry().run(req, backend_id='hyperltl_autohyper_mchyper')
    assert attempt.status.value == 'succeeded' and result.status.value == 'unknown'
    assert result.payload['result_status'] == 'satisfied'
    assert result.payload['result_authority'] == 'hyperproperty' and not result.is_theorem_proof
    assert result.payload['result']['metadata']['process']['returncode'] == 0
    assert result.request_digest == attempt.request_digest == req.digest
    assert result.attempt_digest == attempt.digest and result.bounds == req.bounds
    assert len(host.calls) == len(host.acquired) == 1


def test_default_discovery_and_v2_construction_are_admission_free(host):
    for backend_type in BACKENDS.values():
        selected = backend_type()
        assert type(selected._runner) is admission.ResourceAdmittedToolRunner
        assert (selected._runner.cpu_slots, selected._runner.child_process_slots) == (2, 4)
        assert selected.is_available() and selected.probe().available
    engine = v2.HyperExecutionEngineV2()
    for name in BACKENDS:
        assert type(engine.backend(name)._runner) is admission.ResourceAdmittedToolRunner
        assert engine.capability_receipt(name).available
    assert host.resolutions == host.calls == host.prepared == []


@pytest.mark.parametrize('engine', BACKENDS)
def test_large_requested_rss_drives_virtual_ceiling_without_inflating_reservation(host, engine):
    host.action[0] = lambda invocation, signal: process.RawProcessResult(returncode=0, stdout=SUCCESS[engine])
    req = request(engine, memory=600*MIB)
    result = BACKENDS[engine]().run(req)
    invocation, _, snapshot, _ = host.calls[0]
    assert result.result.bounds == req.bounds
    assert invocation.limits.resident_memory_bytes == 600*MIB
    assert invocation.limits.memory_bytes == max((4096 if engine == 'autohyper' else 2048)*MIB, 4*600*MIB)
    assert snapshot['allocated']['memory_mb'] == 600 and len(host.calls) == 1


def test_owned_autohyper_environment_cannot_override_reviewed_dotnet_profile(host, monkeypatch):
    poison = {'DOTNET_ROOT': '/reviewed/dotnet', 'PATH': '/reviewed/tools', 'GHCRTS': '-N999',
        'DOTNET_PROCESSOR_COUNT': '999', 'DOTNET_gcServer': '1', 'DOTNET_GCHeapHardLimit': 'FFFFFFFF',
        'DOTNET_GCHeapHardLimitPercent': '99', 'COMPlus_GCHeapHardLimitSOH': 'FFFFFFFF',
        'DOTNET_gcConcurrent': '1', 'COMPlus_gcServer': '1'}
    original = dict(poison)
    monkeypatch.setenv('GHCRTS', '-N888')
    monkeypatch.setenv('COMPlus_GCHeapHardLimit', 'FFFFFFFF')
    host.action[0] = lambda invocation, signal: process.RawProcessResult(returncode=0, stdout=SUCCESS['autohyper'])
    backend = hyper.AutoHyperBackend(runtime_environment=poison)
    result = backend.run(request('autohyper', memory=129*MIB+1))
    environment = host.calls[0][0].environment
    assert result.result.status is ResultStatus.SATISFIED
    assert environment['DOTNET_PROCESSOR_COUNT'] == '1' and environment['DOTNET_gcServer'] == '0'
    assert environment['DOTNET_GCHeapHardLimit'] == format((129*MIB+1)//2, 'x')
    assert {name for name in environment if name.startswith(('DOTNET_GC', 'COMPlus_GC', 'DOTNET_gc', 'COMPlus_gc'))} == {
        'DOTNET_gcServer', 'DOTNET_GCHeapHardLimit'}
    assert environment['DOTNET_ROOT'] == '/reviewed/dotnet' and environment['PATH'] == '/reviewed/tools'
    assert 'GHCRTS' not in environment
    assert poison == original and backend._runtime_environment == original
    assert not host.calls[0][0].limits.enforce_file_size_limit


@pytest.mark.parametrize('engine', ['hyperltl', 'mchyper'])
def test_owned_non_dotnet_engines_remove_unreviewed_haskell_runtime_controls(host, engine):
    host.action[0] = lambda invocation, signal: process.RawProcessResult(returncode=0, stdout=SUCCESS[engine])
    outcome = BACKENDS[engine](runtime_environment={'GHCRTS': '-N999'}).run(request(engine))
    assert outcome.result.status is ResultStatus.SATISFIED
    assert 'GHCRTS' not in host.calls[0][0].environment


@pytest.mark.parametrize('engine', BACKENDS)
@pytest.mark.parametrize('falsey', [False, True])
def test_injected_plain_runner_retains_limits_signal_and_successful_version_probe(host, engine, falsey):
    seen = []; token = threading.Event()
    class Owned(process.BoundedToolRunner):
        def __bool__(self):
            return not falsey
    def execute(invocation, signal):
        assert host.owner.snapshot()['active_lease_count'] == 0
        seen.append((invocation, signal))
        return process.RawProcessResult(returncode=0,
            stdout='owned-engine 1.2\n' if '--version' in invocation.argv else SUCCESS[engine])
    owned = Owned(executor=execute)
    environment = {'GHCRTS': '-N7', 'DOTNET_PROCESSOR_COUNT': '7', 'DOTNET_gcServer': '1'}
    backend = BACKENDS[engine](runner=owned, executable='owned-engine', runtime_environment=environment)
    outcome = backend.run(request(engine), cancellation=token)
    assert backend._runner is owned and outcome.result.status is ResultStatus.SATISFIED
    assert outcome.receipt.tool_version == 'owned-engine 1.2' and len(seen) == 2
    invocation, signal = seen[0]
    assert signal is token and invocation.limits.timeout_seconds == 2
    assert invocation.limits.cpu_seconds is invocation.limits.memory_bytes is None
    assert invocation.limits.resident_memory_bytes is None
    assert invocation.limits.enforce_file_size_limit is (engine != 'autohyper')
    assert all(invocation.environment[name] == value for name, value in environment.items())
    assert seen[1][0].argv[-1] == '--version'
    assert host.calls == host.acquired == host.resolutions == []


@pytest.mark.parametrize('falsey', [False, True])
def test_explicit_admitted_runner_retains_ownership_and_refuses_legacy_missing_caps(host, falsey):
    class Owned(admission.ResourceAdmittedToolRunner):
        def __bool__(self):
            return not falsey
    owned = Owned(scheduler=host.owner)
    backend = hyper.HyperLTLBackend(runner=owned, executable='fixture-hyper')
    outcome = backend.run(request())
    assert backend._runner is owned and outcome.result.status is ResultStatus.ERROR
    assert outcome.result.metadata['process']['resource_exhausted']
    assert not outcome.receipt.external_tool_proof
    assert host.calls == host.prepared == host.acquired == host.resolutions == []


def test_caller_profile_can_delegate_parent_budget_without_double_charging(host):
    snapshots = []
    def execute(invocation, signal):
        snapshots.append(host.owner.snapshot())
        assert invocation.limits.memory_bytes == 128*MIB
        assert invocation.limits.resident_memory_bytes is None
        return process.RawProcessResult(returncode=0,
            stdout='caller-version\n' if '--version' in invocation.argv else SUCCESS['hyperltl'])
    class CallerProfile(admission.ResourceAdmittedToolRunner):
        def run(self, tool_request, *, cancellation=None):
            # Explicit caller ownership supplies the finite legacy profile.
            assert tool_request.limits.memory_bytes is None
            return super().run(replace(tool_request,
                limits=replace(tool_request.limits, memory_bytes=128*MIB)), cancellation=cancellation)
    with host.owner.acquire('orchestration', cpu_slots=2, memory_mb=256, child_process_slots=4, timeout=0) as parent:
        with host.owner.acquire('validation', cpu_slots=1, memory_mb=32, child_process_slots=1, timeout=0) as foreign:
            allocated = host.owner.snapshot()['allocated']
            runner = CallerProfile(parent_lease=parent, executor=execute)
            outcome = hyper.HyperLTLBackend(runner=runner, executable='fixture-hyper').run(request())
            assert outcome.result.status is ResultStatus.SATISFIED and outcome.receipt.tool_version == 'caller-version'
            assert len(snapshots) == 2
            for snapshot in snapshots:
                assert snapshot['active_lease_count'] == 3 and snapshot['active_root_lease_count'] == 2
                assert snapshot['allocated'] == allocated and snapshot['allocated_child_process_slots'] == 5
            assert host.owner.snapshot()['active_lease_count'] == 2
            assert not parent.released and not parent.cancelled and not foreign.released
    assert host.resolutions == host.calls == []


@pytest.mark.parametrize('early', ['unavailable', 'missing_model', 'fallback'])
def test_early_paths_never_reserve_or_invent_process_metadata(host, early):
    if early == 'missing_model':
        outcome = hyper.MCHyperBackend(executable='owned-engine').check(document())
        assert outcome.result.status is ResultStatus.UNSUPPORTED
    else:
        outcome = hyper.HyperLTLBackend(which=lambda name: None).check(document(),
            allow_fallback=early == 'fallback')
        assert not outcome.receipt.external_tool_proof
    assert 'process' not in outcome.result.metadata
    assert host.calls == host.prepared == host.acquired == host.resolutions == []


def test_check_bounds_match_request_or_fail_before_execution(host):
    selected = hyper.HyperLTLBackend(); req = request()
    with pytest.raises(hyper.HyperpropertyAdapterError):
        selected.check(document(), request=req, bounds=replace(req.bounds, timeout_ms=1000))
    assert host.calls == host.resolutions == []
    outcome = selected.check(document(), request=req, bounds=req.bounds)
    assert outcome.request_digest == req.digest and outcome.result.bounds == req.bounds
    assert len(host.calls) == 1


@pytest.mark.parametrize('bounds', [{}, False, 1000])
def test_check_rejects_untyped_bounds_before_probe_or_admission(host, bounds):
    with pytest.raises(hyper.HyperpropertyAdapterError):
        hyper.HyperLTLBackend(which=forbidden).check(document(), bounds=bounds)
    assert host.calls == host.prepared == host.resolutions == []


def test_precancelled_default_run_never_resolves_pool_or_launches_version(host):
    token = threading.Event(); token.set()
    outcome = hyper.HyperLTLBackend().run(request(), cancellation=token)
    assert outcome.result.status is ResultStatus.ERROR and not outcome.receipt.external_tool_proof
    assert outcome.receipt.counterexample is None and outcome.result.metadata['process']['cancelled']
    assert host.calls == host.prepared == host.acquired == host.resolutions == []


def until(predicate):
    deadline = time.monotonic()+2
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail('private Hyper fixture wait expired')
        time.sleep(.003)


@pytest.mark.parametrize('changes,reason', [({'cpu_stall_percent': 90}, 'proof_cpu_stall'),
    ({'available_memory_mb': 32}, 'proof_memory_headroom'),
    ({'available_pid_tasks': 0}, 'proof_pid_headroom'),
    (None, 'proof_resource_telemetry_unknown')])
def test_external_pressure_prevents_workspace_then_recovers_same_request(host, changes, reason):
    host.current[0] = replace(host.healthy, **changes) if changes is not None else OSError('missing telemetry')
    req = request(timeout_ms=5000); token = threading.Event(); observed = {}
    def run():
        try:
            observed['result'] = hyper.HyperLTLBackend().run(req, cancellation=token)
        except BaseException as error:
            observed['error'] = error
    thread = threading.Thread(target=run); thread.start()
    try:
        until(lambda: host.owner.snapshot()['proof_backoff'].get('reason') == reason)
        assert host.calls == host.prepared == host.acquired == []
        host.current[0] = host.healthy
        thread.join(3)
        assert not thread.is_alive() and 'error' not in observed
        assert observed['result'].result.status is ResultStatus.SATISFIED
        assert observed['result'].result.bounds == req.bounds and len(host.calls) == 1
    finally:
        token.set(); host.current[0] = host.healthy; thread.join(3)


@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
def test_registry_stop_drains_pressure_queue_without_touching_foreign_owner(host, clock, stop):
    foreign = host.owner.acquire('validation', cpu_slots=1, memory_mb=32, child_process_slots=1, timeout=0)
    host.current[0] = replace(host.healthy, available_pid_tasks=0)
    token = threading.Event(); observed = {}
    def run():
        try:
            req = replace(request(), requested_backend_id='hyperltl_autohyper_mchyper')
            observed['pair'] = registry.default_backend_registry().run(req, backend_id='hyperltl_autohyper_mchyper',
                operation_timeout_ms=500, cancellation=token)
        except BaseException as error:
            observed['error'] = error
    thread = threading.Thread(target=run); thread.start()
    try:
        until(lambda: host.owner.snapshot()['proof_backoff'].get('reason') == 'proof_pid_headroom')
        assert host.calls == host.prepared == []
        if stop == 'timeout':
            clock[0] += .6
        else:
            token.set()
        thread.join(3)
        assert not thread.is_alive() and 'error' not in observed
        attempt, result = observed['pair']
        assert attempt.status.value == ('timed_out' if stop == 'timeout' else 'cancelled')
        assert result.status.value == 'unknown'
        assert host.owner.snapshot()['waiting_request_count'] == 0
        assert host.owner.snapshot()['active_lease_count'] == 1
        assert not foreign.cancelled and not foreign.released
    finally:
        token.set(); host.current[0] = host.healthy; thread.join(3); foreign.release()


def test_oversized_memory_is_refused_without_lowering_requested_rss(host):
    req = request(memory=1025*MIB)
    outcome = hyper.HyperLTLBackend().run(req)
    assert outcome.result.status is ResultStatus.ERROR and not outcome.receipt.external_tool_proof
    assert outcome.result.bounds == req.bounds and outcome.result.metadata['process']['resource_exhausted']
    assert host.calls == host.prepared == host.acquired == []


def test_executor_failure_cleans_workspace_before_releasing_lease(host, monkeypatch):
    released = []; original_release = schedulers.ResourceLease.release
    def release(lease):
        assert len(host.prepared) == 1 and not host.prepared[0].exists()
        released.append(lease)
        return original_release(lease)
    monkeypatch.setattr(schedulers.ResourceLease, 'release', release)
    def fail(invocation, signal):
        raise OSError('synthetic Hyper executor failure')
    host.action[0] = fail
    outcome = hyper.HyperLTLBackend().run(request())
    assert outcome.result.status is ResultStatus.ERROR and not outcome.receipt.external_tool_proof
    assert outcome.result.metadata['process']['workspace_cleaned']
    assert len(host.calls) == 1 and released == host.acquired and host.acquired[0].released


@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
def test_ambient_budget_inherits_remaining_cpu_and_withholds_late_output(host, clock, stop):
    token = threading.Event()
    def late(invocation, signal):
        assert invocation.limits.timeout_seconds == pytest.approx(.5)
        assert invocation.limits.cpu_seconds == pytest.approx(.5)
        if stop == 'timeout':
            clock[0] += .6
        else:
            token.set()
        assert signal.is_set()
        return process.RawProcessResult(returncode=0, stdout=VIOLATION['hyperltl']+TRACE)
    host.action[0] = late
    req = replace(request(), requested_backend_id='hyperltl_autohyper_mchyper')
    attempt, result = registry.default_backend_registry().run(req, backend_id='hyperltl_autohyper_mchyper',
        operation_timeout_ms=500, cancellation=token)
    assert attempt.status.value == ('timed_out' if stop == 'timeout' else 'cancelled')
    assert result.status.value == 'unknown' and not result.is_theorem_proof
    assert len(host.calls) == 1 and host.acquired[0].released
    assert budget.current_proof_operation() is None


class FixedRunner(process.BoundedToolRunner):
    def __init__(self, result):
        super().__init__(executor=forbidden)
        self.result = result
        self.requests = []

    def run(self, tool_request, *, cancellation=None):
        self.requests.append(tool_request)
        return self.result


def lifecycle(stdout='sat\n', **changes):
    return process.ToolRunResult(**{'interface_version': process.BOUNDED_TOOL_RUNNER_VERSION,
        'runtime': process.ToolRuntime.NATIVE, 'command': ('fixture-hyper', '-f', 'property.hltl'),
        'returncode': 0, 'stdout': stdout, 'stderr': '', 'elapsed_seconds': .01,
        'output_files': {}, 'termination_reason': 'completed', **changes})


def deny_witness(monkeypatch):
    monkeypatch.setattr(hyper, 'parse_hyper_counterexample', forbidden)
    monkeypatch.setattr(hyper, 'replay_hyper_counterexample', forbidden)


UNSAFE = [({'unavailable': True}, ResultStatus.UNAVAILABLE),
    ({'cancelled': True}, ResultStatus.ERROR), ({'timed_out': True}, ResultStatus.TIMEOUT),
    ({'resource_exhausted': True}, ResultStatus.ERROR), ({'output_truncated': True}, ResultStatus.UNKNOWN),
    ({'workspace_limit_exceeded': True}, ResultStatus.ERROR), ({'error': 'fixture cleanup failed'}, ResultStatus.ERROR),
    ({'workspace_cleaned': False}, ResultStatus.ERROR), ({'process_tree_terminated': True}, ResultStatus.ERROR)]


@pytest.mark.parametrize('changes,status', UNSAFE)
@pytest.mark.parametrize('violated', [False, True])
def test_unsafe_lifecycle_precedes_verdict_and_witness_and_suppresses_version(monkeypatch, changes, status, violated):
    deny_witness(monkeypatch)
    stdout = VIOLATION['hyperltl']+TRACE if violated else SUCCESS['hyperltl']
    raw = lifecycle(stdout, **changes); runner = FixedRunner(raw)
    outcome = hyper.HyperLTLBackend(runner=runner, executable='fixture-hyper').run(request())
    assert outcome.result.status is status and not outcome.receipt.external_tool_proof
    assert outcome.receipt.counterexample is None and 'witness_bundle' not in outcome.result.witness
    assert len(runner.requests) == 1
    metadata = outcome.result.metadata['process']
    assert set(metadata) == {'cancelled', 'command', 'error', 'output_truncated', 'process_tree_terminated',
        'returncode', 'resource_exhausted', 'stderr_digest', 'stdout_digest', 'timed_out',
        'termination_reason', 'unavailable', 'workspace_cleaned', 'workspace_limit_exceeded'}
    for name, value in changes.items():
        assert metadata[name] == value
    assert metadata['stdout_digest'] == stable_digest({'content': stdout})
    assert metadata['returncode'] == 0 and metadata['termination_reason'] == 'completed'
    assert list(metadata['command']) == list(raw.command)


@pytest.mark.parametrize('engine,code', [('hyperltl', False), ('autohyper', 0.0),
    ('mchyper', 1), ('hyperltl', -9), ('autohyper', None)])
def test_invalid_or_nonzero_exit_never_establishes_verdict_or_witness(monkeypatch, engine, code):
    deny_witness(monkeypatch)
    runner = FixedRunner(lifecycle(VIOLATION[engine]+TRACE, returncode=code))
    outcome = BACKENDS[engine](runner=runner, executable='fixture-hyper').run(request(engine))
    assert outcome.result.status is ResultStatus.ERROR and not outcome.receipt.external_tool_proof
    assert outcome.receipt.counterexample is None and len(runner.requests) == 1
    assert outcome.result.metadata['process']['returncode'] == code


@pytest.mark.parametrize('overflow', [False, True])
def test_combined_utf8_output_bound_is_checked_before_witness(monkeypatch, overflow):
    stdout = SUCCESS['hyperltl']+'é'*1800
    remaining = 8192-len(stdout.encode())
    stderr = 'é'*(remaining//2)+' '*(remaining%2)+('é' if overflow else '')
    assert len(stdout.encode()) < 8192 and len(stderr.encode()) < 8192
    assert len(stdout)+len(stderr) < 8192
    deny_witness(monkeypatch)
    runner = FixedRunner(lifecycle(stdout, stderr=stderr))
    outcome = hyper.HyperLTLBackend(runner=runner, executable='fixture-hyper').run(request())
    assert outcome.result.status is (ResultStatus.UNKNOWN if overflow else ResultStatus.SATISFIED)
    assert outcome.receipt.external_tool_proof is (not overflow)
    assert len(runner.requests) == (1 if overflow else 2)
    assert outcome.result.usage.output_bytes == 8192+(2 if overflow else 0)


@pytest.mark.parametrize('reason', ['', 'completed', 'nonzero_exit'])
def test_clean_nonzero_unsupported_marker_retains_nonconclusive_compatibility(monkeypatch, reason):
    deny_witness(monkeypatch)
    runner = FixedRunner(lifecycle('unsupported quantifier alternation\n', returncode=2,
                                   termination_reason=reason))
    outcome = hyper.HyperLTLBackend(runner=runner, executable='fixture-hyper').run(request())
    assert outcome.result.status is ResultStatus.UNSUPPORTED and not outcome.receipt.external_tool_proof
    assert outcome.receipt.counterexample is None


def test_nonzero_exit_reason_with_zero_code_refuses_conclusive_output(monkeypatch):
    deny_witness(monkeypatch)
    runner = FixedRunner(lifecycle(VIOLATION['hyperltl']+TRACE, returncode=0,
                                   termination_reason='nonzero_exit'))
    outcome = hyper.HyperLTLBackend(runner=runner, executable='fixture-hyper').run(request())
    assert outcome.result.status is ResultStatus.ERROR and not outcome.receipt.external_tool_proof
    assert outcome.receipt.counterexample is None and len(runner.requests) == 1
    assert outcome.result.metadata['process']['returncode'] == 0
    assert outcome.result.metadata['process']['termination_reason'] == 'nonzero_exit'


def test_nul_output_is_nonconclusive_with_sanitized_receipt_and_raw_process_digest(monkeypatch):
    deny_witness(monkeypatch)
    stdout = VIOLATION['hyperltl']+'\x00'+TRACE
    runner = FixedRunner(lifecycle(stdout))
    outcome = hyper.HyperLTLBackend(runner=runner, executable='fixture-hyper').run(request())
    assert outcome.result.status is ResultStatus.ERROR and not outcome.receipt.external_tool_proof
    assert outcome.receipt.counterexample is None
    assert outcome.receipt.stdout == stdout.replace('\x00', '\ufffd')
    assert outcome.result.metadata['process']['stdout_digest'] == stable_digest({'content': stdout})
    assert len(runner.requests) == 1


@pytest.mark.parametrize('engine', BACKENDS)
def test_v2_never_promotes_failed_cleanup_into_engine_or_witness_authority(monkeypatch, engine):
    deny_witness(monkeypatch)
    runner = FixedRunner(lifecycle(VIOLATION[engine]+TRACE, workspace_cleaned=False))
    backend = BACKENDS[engine](runner=runner, executable='fixture-hyper')
    encoded = typed_request(engine)
    result = v2.HyperExecutionEngineV2(**{engine: backend}).execute(encoded)
    assert result.evidence.result_status is ResultStatus.ERROR
    assert not result.evidence.hyperproperty_established and not result.evidence.external_tool_proof
    assert not result.evidence.authorizes_universal_proof
    assert result.backend_result.metadata['process']['workspace_cleaned'] is False
    assert len(runner.requests) == 1
