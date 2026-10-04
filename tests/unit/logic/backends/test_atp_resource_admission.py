"""Default ATP admission with private pools and synthetic native executors.

No executable is started or installed. Real workspace and scheduler lifecycles
are retained, including pressure queues and delegated ownership.
"""
from dataclasses import replace
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process, registry, resource_admission as admission
from ipfs_datasets_py.logic.backends.atp import adapters, execution_v2 as v2
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.backends.smt import operation_budget as budget
from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest, ExecutionBounds, QueryKind
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


MIB = 1024**2
PROVIDERS = ('vampire', 'e')
SOURCE = 'fof(ax1, axiom, p).\nfof(goal, conjecture, p).'
PROOF = ('% SZS status Theorem\n% SZS output start CNFRefutation\n'
         "cnf(c_0, plain, p(a), file('problem.p', ax1)).\n"
         'cnf(c_1, plain, ~p(a), inference(assume, [], [])).\n'
         'cnf(c_2, plain, $false, inference(resolution, [], [c_0, c_1])).\n'
         '% SZS output end CNFRefutation\n')


def request(provider='vampire', *, timeout_ms=2000, memory=64*MIB):
    return BackendRequest(request_id='request:atp:admission', claim_id='claim:atp',
        declaration_id='declaration:atp', claim_digest='1'*64, obligation_id='obligation:atp',
        obligation_digest='2'*64, assumption_ids=('assumption:fixture',), logic_family='fol',
        query_kind=QueryKind.THEOREM_PROOF,
        requested_backend_id='eprover' if provider == 'e' else provider,
        bounds=ExecutionBounds(timeout_ms=timeout_ms, max_memory_bytes=memory,
                               max_steps=100, max_output_bytes=8192),
        payload={'encoding': 'tptp', 'source': SOURCE})


def backend(provider, **kwargs):
    return (adapters.VampireBackend if provider == 'vampire' else adapters.EProverBackend)(**kwargs)


def typed_request(provider, *, mode='pinned_solver'):
    return v2.AtpExecutionRequestV2(request_id='request:atp:v2:admission', source=SOURCE,
        provider='vampire' if provider == 'vampire' else 'eprover', mode=mode,
        bounds=request(provider).bounds, source_ref_ids=('source:fixture:admission',))


def assert_candidate(outcome, req):
    assert outcome.result.status is ResultStatus.CANDIDATE
    assert outcome.result.authority is ResultAuthority.CANDIDATE
    assert outcome.proof_object is not None and not outcome.proof_object.verified
    assert outcome.proof_object.content == PROOF
    assert outcome.request_digest == outcome.source_binding.request_digest == req.digest
    assert outcome.result.bounds == req.bounds
    assert outcome.result.metadata['process']['workspace_cleaned']


@pytest.fixture(autouse=True)
def no_host_execution(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail('ATP fixture reached a host process or shared resource pool')
    monkeypatch.setattr(subprocess, 'Popen', denied)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', denied)
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', denied)


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    fake = SimpleNamespace(monotonic=lambda: now[0])
    for module in (admission, budget, registry):
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
        state_path=tmp_path/'private-atp-pool.json', proof_resource_sampler=sample,
        total_cpu_slots=3, total_memory_mb=512, total_child_process_slots=3,
        proof_memory_headroom_mb=64, lane_reservations={}, auto_renew_leases=False,
        proof_backoff_seconds=.01, poll_interval_seconds=.002))
    calls, prepared, acquired, resolutions = [], [], [], []
    def resolve():
        resolutions.append(True)
        return owner
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', resolve)
    # Availability is an explicit fixture; never inspect a host solver installation.
    monkeypatch.setattr(process.shutil, 'which', lambda *a, **k: sys.executable)
    original_acquire = owner.acquire
    def acquire(*args, **kwargs):
        lease = original_acquire(*args, **kwargs)
        acquired.append((lease, kwargs.copy()))
        return lease
    monkeypatch.setattr(owner, 'acquire', acquire)
    original_write = process.BoundedToolRunner._write_inputs
    def write(workspace, tool_request):
        prepared.append(workspace)
        return original_write(workspace, tool_request)
    monkeypatch.setattr(process.BoundedToolRunner, '_write_inputs', staticmethod(write))
    action = [lambda invocation, signal: process.RawProcessResult(returncode=0, stdout=PROOF)]
    def execute(self, invocation, cancellation=None):
        snapshot = owner.snapshot()
        assert snapshot['active_lease_count'] >= 1
        assert cancellation is not None and not cancellation.is_set()
        assert (invocation.cwd/'problem.p').read_text() == SOURCE
        calls.append((invocation, cancellation, snapshot, budget.current_proof_operation()))
        return action[0](invocation, cancellation)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', execute)
    yield SimpleNamespace(owner=owner, healthy=healthy, current=current, calls=calls,
        prepared=prepared, acquired=acquired, resolutions=resolutions, action=action, tmp=tmp_path)
    snapshot = owner.snapshot()
    assert snapshot['active_lease_count'] == snapshot['waiting_request_count'] == 0
    assert all(not workspace.exists() for workspace in prepared)


def until(predicate):
    deadline = time.monotonic()+2
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail('bounded ATP fixture wait expired')
        time.sleep(.003)


def test_construction_discovery_and_capability_queries_are_inert(host):
    for provider in PROVIDERS:
        selected = backend(provider)
        assert type(selected._runner) is admission.ResourceAdmittedToolRunner
        assert selected.supports('fol', QueryKind.THEOREM_PROOF)
        assert selected.is_available()
    v2.AtpExecutionEngineV2()
    catalog = registry.default_backend_registry()
    assert catalog.get('vampire')._delegate is None
    assert catalog.get('e')._delegate is None
    assert host.resolutions == host.acquired == host.prepared == host.calls == []


@pytest.mark.parametrize('provider', PROVIDERS)
@pytest.mark.parametrize('memory', [64*MIB, 65*MIB+1])
def test_default_adapter_owns_one_finite_lease_without_changing_source_or_caps(host, provider, memory):
    req = request(provider, memory=memory)
    wire, digest = req.to_dict(), req.digest
    outcome = backend(provider).run(req)
    assert_candidate(outcome, req)
    assert req.to_dict() == wire and req.digest == digest
    assert len(host.calls) == len(host.prepared) == len(host.acquired) == len(host.resolutions) == 1
    invocation, signal, snapshot, ambient = host.calls[0]
    assert ambient is None
    assert snapshot['active_lease_count'] == snapshot['active_root_lease_count'] == 1
    assert snapshot['allocated'] == {'cpu_slots': 1, 'memory_mb': (memory+MIB-1)//MIB}
    assert snapshot['allocated_child_process_slots'] == 1
    assert host.acquired[0][0].released
    assert 0 < invocation.limits.timeout_seconds <= 2
    assert invocation.limits.cpu_seconds == 2
    assert invocation.limits.memory_bytes == memory and invocation.limits.resident_memory_bytes is None
    assert invocation.limits.max_output_bytes == invocation.limits.max_input_bytes == 8192
    assert invocation.limits.max_workspace_bytes == 16384
    assert invocation.environment['HOME'] == str(invocation.cwd)
    assert invocation.environment['TMPDIR'] == str(invocation.cwd)
    if provider == 'vampire':
        assert invocation.argv[2:] == ('--time_limit', '2', '--output_mode', 'szs', '--proof', 'tptp')
    else:
        assert invocation.argv[1:3] == ('--cpu-limit=2', '--proof-object')


@pytest.mark.parametrize('provider', PROVIDERS)
def test_pinned_v2_default_route_is_admitted_and_preserves_candidate_authority(host, provider):
    req = typed_request(provider)
    before = req.to_dict()
    result = v2.AtpExecutionEngineV2().execute(req)
    evidence = result.evidence
    assert evidence.disposition is v2.AtpDisposition.REPLAY_MATCHED
    assert evidence.candidate_established and not evidence.theorem_established
    assert not evidence.proof_established and not evidence.reconstruction_established
    assert evidence.result_authority is ResultAuthority.CANDIDATE
    assert evidence.proof.present and not evidence.proof.verified
    assert evidence.profile.source_digest == req.source_digest
    assert evidence.replay is not None and evidence.replay.matched
    assert req.to_dict() == before
    assert len(host.calls) == len(host.acquired) == len(host.resolutions) == 1
    assert host.calls[0][2]['allocated']['memory_mb'] == 64


@pytest.mark.parametrize('provider', PROVIDERS)
def test_default_registry_reaches_admission_and_keeps_foreign_candidate_descriptive(host, provider):
    req = request(provider)
    attempt, result = registry.default_backend_registry().run(req, backend_id=provider)
    assert attempt.status.value == 'succeeded' and result.status.value == 'unknown'
    assert result.payload['result_status'] == result.payload['result_authority'] == 'candidate'
    assert not result.is_theorem_proof
    assert result.request_digest == attempt.request_digest == req.digest
    assert result.attempt_digest == attempt.digest
    assert result.bounds == attempt.bounds == req.bounds
    assert len(host.calls) == len(host.acquired) == 1
    assert host.calls[0][3] is not None


@pytest.mark.parametrize('provider', PROVIDERS)
def test_hermetic_v2_missing_runner_never_acquires_or_falls_back_to_native(host, provider):
    result = v2.AtpExecutionEngineV2().execute(typed_request(provider, mode='hermetic_fixture'))
    assert result.evidence.disposition is v2.AtpDisposition.UNAVAILABLE
    assert not result.evidence.candidate_established
    assert host.resolutions == host.acquired == host.prepared == host.calls == []


@pytest.mark.parametrize('provider', PROVIDERS)
@pytest.mark.parametrize('route', ['direct', 'v2'])
def test_plain_injected_runner_is_caller_owned_even_when_falsey(host, provider, route, monkeypatch):
    calls = []
    event = threading.Event()
    def execute(invocation, signal):
        assert host.owner.snapshot()['active_lease_count'] == 0
        calls.append((invocation, signal))
        return process.RawProcessResult(returncode=0, stdout=PROOF)
    class FalseyRunner(process.BoundedToolRunner):
        def __bool__(self):
            return False
    runner = FalseyRunner(executor=execute, workspace_root=host.tmp/'plain')
    monkeypatch.setattr(admission, 'get_global_resource_scheduler',
                        lambda: pytest.fail('plain injected runner was reserved again'))
    if route == 'direct':
        selected = backend(provider, runner=runner)
        assert selected._runner is runner
        assert_candidate(selected.run(request(provider), cancellation=event), request(provider))
        assert calls[0][1] is event
    else:
        engine = v2.AtpExecutionEngineV2(**{('vampire_runner' if provider == 'vampire' else 'eprover_runner'): runner})
        assert engine.execute(typed_request(provider)).evidence.candidate_established
        assert calls[0][1] is None
    assert len(calls) == 1 and calls[0][0].limits.timeout_seconds == 2
    assert host.acquired == host.calls == []


@pytest.mark.parametrize('provider', PROVIDERS)
@pytest.mark.parametrize('flag,status', [('timed_out', ResultStatus.TIMEOUT),
    ('cancelled', ResultStatus.ERROR), ('resource_exhausted', ResultStatus.ERROR),
    ('output_truncated', ResultStatus.ERROR)])
def test_native_failure_flags_with_proof_text_never_become_candidates(host, provider, flag, status):
    host.action[0] = lambda invocation, signal: process.RawProcessResult(
        returncode=0, stdout=PROOF, **{flag: True})
    outcome = backend(provider).run(request(provider))
    assert outcome.result.status is status and outcome.proof_object is None
    assert outcome.result.metadata['process'][flag]
    assert outcome.result.metadata['process']['workspace_cleaned']
    assert len(host.calls) == 1 and host.acquired[0][0].released


@pytest.mark.parametrize('provider', PROVIDERS)
def test_direct_precancel_refuses_before_scheduler_or_workspace(host, provider):
    event = threading.Event(); event.set()
    outcome = backend(provider).run(request(provider), cancellation=event)
    assert outcome.result.status is ResultStatus.ERROR and outcome.proof_object is None
    assert outcome.result.metadata['process']['cancelled']
    assert host.resolutions == host.acquired == host.prepared == host.calls == []


@pytest.mark.parametrize('provider', PROVIDERS)
@pytest.mark.parametrize('stop', ['timeout', 'cancel'])
def test_registry_scope_shrinks_native_budget_and_withholds_late_proof(host, clock, provider, stop):
    event = threading.Event()
    def late(invocation, signal):
        assert invocation.limits.timeout_seconds == pytest.approx(.5)
        assert invocation.limits.cpu_seconds == pytest.approx(.5)
        if stop == 'timeout':
            clock[0] += .6
        else:
            event.set()
        assert signal.is_set()
        return process.RawProcessResult(returncode=0, stdout=PROOF)
    host.action[0] = late
    req = request(provider)
    attempt, result = registry.default_backend_registry().run(req, backend_id=provider,
        operation_timeout_ms=500, cancellation=event)
    assert attempt.status.value == ('timed_out' if stop == 'timeout' else 'cancelled')
    assert result.status.value == 'unknown' and not result.is_theorem_proof
    assert result.bounds == attempt.bounds == req.bounds
    assert result.request_digest == req.digest and result.attempt_digest == attempt.digest
    assert len(host.calls) == 1 and host.acquired[0][0].released
    assert budget.current_proof_operation() is None


PRESSURE = [({'cpu_stall_percent': 90}, 'proof_cpu_stall'),
    ({'available_memory_mb': 32}, 'proof_memory_headroom'),
    ({'available_pid_tasks': 0}, 'proof_pid_headroom'),
    (None, 'proof_resource_telemetry_unknown')]


@pytest.mark.parametrize('changes,reason', PRESSURE)
def test_external_pressure_prevents_workspace_then_recovers_without_new_request(host, changes, reason):
    host.current[0] = replace(host.healthy, **changes) if changes is not None else OSError('unavailable sample')
    event = threading.Event(); observed = {}
    def work():
        try:
            observed['outcome'] = backend('vampire').run(request(timeout_ms=5000), cancellation=event)
        except BaseException as error:
            observed['error'] = error
    worker = threading.Thread(target=work); worker.start()
    try:
        until(lambda: host.owner.snapshot()['proof_backoff'].get('reason') == reason)
        assert host.acquired == host.prepared == host.calls == []
        host.current[0] = host.healthy
        worker.join(timeout=3)
        assert not worker.is_alive() and 'error' not in observed
        assert_candidate(observed['outcome'], request(timeout_ms=5000))
        assert len(host.calls) == len(host.acquired) == 1
    finally:
        event.set(); host.current[0] = host.healthy; worker.join(timeout=3)


@pytest.mark.parametrize('stop', ['timeout', 'cancel'])
def test_registry_stop_drains_pressure_queue_without_releasing_foreign_lease(host, clock, stop):
    foreign = host.owner.acquire('validation', cpu_slots=1, memory_mb=32, child_process_slots=1, timeout=0)
    host.current[0] = replace(host.healthy, available_pid_tasks=0)
    event = threading.Event(); observed = {}
    def work():
        try:
            observed['pair'] = registry.default_backend_registry().run(request('e'), backend_id='e',
                operation_timeout_ms=500, cancellation=event)
        except BaseException as error:
            observed['error'] = error
    worker = threading.Thread(target=work); worker.start()
    try:
        until(lambda: host.owner.snapshot()['proof_backoff'].get('reason') == 'proof_pid_headroom')
        assert host.prepared == host.calls == []
        if stop == 'timeout':
            clock[0] += .6
        else:
            event.set()
        worker.join(timeout=3)
        assert not worker.is_alive() and 'error' not in observed
        attempt, result = observed['pair']
        assert attempt.status.value == ('timed_out' if stop == 'timeout' else 'cancelled')
        assert result.status.value == 'unknown'
        snapshot = host.owner.snapshot()
        assert snapshot['waiting_request_count'] == 0 and snapshot['active_lease_count'] == 1
        assert not foreign.released and not foreign.cancelled
        assert host.prepared == host.calls == []
    finally:
        event.set(); host.current[0] = host.healthy; worker.join(timeout=3); foreign.release()


def test_explicit_parent_owner_uses_child_without_double_charging_or_releasing_parent(host):
    with host.owner.acquire('orchestration', cpu_slots=2, memory_mb=256, child_process_slots=2, timeout=0) as parent:
        with host.owner.acquire('validation', cpu_slots=1, memory_mb=32, child_process_slots=1, timeout=0) as foreign:
            allocated = host.owner.snapshot()['allocated']
            runner = admission.ResourceAdmittedToolRunner(parent_lease=parent)
            outcome = backend('e', runner=runner).run(request('e'))
            assert_candidate(outcome, request('e'))
            state = host.calls[0][2]
            assert state['active_lease_count'] == 3 and state['active_root_lease_count'] == 2
            assert state['allocated'] == allocated
            assert host.resolutions == []
            assert not parent.released and not parent.cancelled
            assert not foreign.released and not foreign.cancelled
            assert host.owner.snapshot()['active_lease_count'] == 2


def test_oversize_memory_request_is_refused_without_silently_reducing_it(host):
    req = request(memory=513*MIB)
    outcome = backend('vampire').run(req)
    assert outcome.result.status is ResultStatus.ERROR and outcome.proof_object is None
    assert outcome.result.metadata['process']['resource_exhausted']
    assert outcome.result.bounds.max_memory_bytes == 513*MIB
    assert host.acquired == host.prepared == host.calls == []


def test_executor_exception_releases_lease_and_cleans_workspace(host):
    def failure(invocation, signal):
        raise OSError('synthetic executor failure')
    host.action[0] = failure
    outcome = backend('vampire').run(request())
    assert outcome.result.status is ResultStatus.ERROR and outcome.proof_object is None
    assert outcome.result.metadata['process']['workspace_cleaned']
    assert 'synthetic executor failure' in outcome.result.reason
    assert len(host.calls) == 1 and host.acquired[0][0].released


class ReturnedLifecycleRunner(process.BoundedToolRunner):
    """Trusted injection seam for independent post-cleanup failure evidence."""
    def __init__(self, result):
        super().__init__(executor=lambda *args: pytest.fail('unexpected executor'))
        self.result = result
        self.requests = []

    def run(self, tool_request, *, cancellation=None):
        self.requests.append(tool_request)
        return self.result


def lifecycle_result(**changes):
    return process.ToolRunResult(**{
        'interface_version': process.BOUNDED_TOOL_RUNNER_VERSION,
        'runtime': process.ToolRuntime.NATIVE, 'command': ('fixture-atp',),
        'returncode': 0, 'stdout': PROOF, 'stderr': '', 'elapsed_seconds': .01,
        'output_files': {}, 'termination_reason': 'completed', **changes})


UNSAFE_LIFECYCLES = [
    {'workspace_limit_exceeded': True},
    {'error': 'fixture descendant cleanup failed'},
    {'workspace_cleaned': False},
    {'process_tree_terminated': True},
    {'returncode': 1},
    {'stdout': PROOF+'é'*2000, 'stderr': 'é'*2500},
]


@pytest.mark.parametrize('provider', PROVIDERS)
@pytest.mark.parametrize('changes', UNSAFE_LIFECYCLES)
def test_unclean_lifecycle_blocks_verdict_parsing_reconstruction_and_countermodel(
        monkeypatch, provider, changes):
    def forbidden(*args, **kwargs):
        pytest.fail('unclean native output reached semantic interpretation')
    # E exit 1 needs bounded status parsing to distinguish its model result
    # convention. This fixture reports Theorem and must still fail closed.
    if not (provider == 'e' and changes.get('returncode') == 1):
        monkeypatch.setattr(adapters, 'parse_szs_status', forbidden)
    runner = ReturnedLifecycleRunner(lifecycle_result(**changes))
    req = request(provider)
    outcome = backend(provider, runner=runner, proof_reconstructor=forbidden,
                      countermodel_parser=forbidden).run(req)
    assert outcome.result.status is ResultStatus.ERROR
    assert outcome.proof_object is outcome.countermodel is None
    assert outcome.result.reason
    if 'returncode' not in changes:
        assert outcome.result.reason != 'completed'
    assert outcome.result.bounds == req.bounds and outcome.request_digest == req.digest
    metadata = outcome.result.metadata['process']
    for name in ('workspace_cleaned', 'workspace_limit_exceeded', 'process_tree_terminated',
                 'error', 'returncode', 'termination_reason'):
        assert metadata[name] == getattr(runner.result, name)
    assert len(runner.requests) == 1
    if 'stderr' in changes:
        # Neither stream is individually over the byte limit; code-point counts
        # alone would also fit. Their combined UTF-8 bytes must be rejected.
        assert len(runner.result.stdout.encode()) < req.bounds.max_output_bytes
        assert len(runner.result.stderr.encode()) < req.bounds.max_output_bytes
        assert len(runner.result.stdout)+len(runner.result.stderr) < req.bounds.max_output_bytes
        assert outcome.result.usage.output_bytes > req.bounds.max_output_bytes


@pytest.mark.parametrize('provider', PROVIDERS)
def test_v2_rejects_unclean_proof_without_claiming_candidate_or_replay(provider):
    runner = ReturnedLifecycleRunner(lifecycle_result(workspace_cleaned=False))
    engine = v2.AtpExecutionEngineV2(**{
        ('vampire_runner' if provider == 'vampire' else 'eprover_runner'): runner})
    result = engine.execute(typed_request(provider))
    assert result.evidence.disposition is v2.AtpDisposition.ERROR
    assert not result.evidence.candidate_established
    assert not result.evidence.theorem_established and not result.evidence.proof_established
    assert not result.evidence.proof.present
    assert len(runner.requests) == 1


def test_combined_byte_limit_allows_exact_boundary_without_authority_upgrade():
    stderr = 'é'*((8192-len(PROOF.encode()))//2)
    stderr += ' '*(8192-len(PROOF.encode())-len(stderr.encode()))
    runner = ReturnedLifecycleRunner(lifecycle_result(stderr=stderr))
    outcome = backend('vampire', runner=runner).run(request())
    assert outcome.result.usage.output_bytes == 8192
    assert outcome.result.status is ResultStatus.CANDIDATE
    assert outcome.result.authority is ResultAuthority.CANDIDATE
    assert outcome.proof_object is not None and not outcome.proof_object.verified
