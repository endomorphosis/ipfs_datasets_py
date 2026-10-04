"""ProVerif admission and lifecycle integrity without native execution.

The RESULT lines deliberately match existing synthetic query fixtures. These
tests do not qualify upstream query-polarity translation or semantic attack
replay. Pressure samples and scheduler state are private to each test.
"""
from dataclasses import replace
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process, registry, resource_admission as admission
from ipfs_datasets_py.logic.backends.protocol import proverif as pv, execution_v2 as v2
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.backends.smt import operation_budget as budget
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest, ExecutionBounds, QueryKind
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


MIB = 1024**2
SOURCE = '(* claim:secrecy *)\nquery not attacker(secret).\nprocess 0.\n'
SECURE = 'RESULT not attacker(secret) is true.\n'
ATTACK = 'RESULT not attacker(secret) is false.\n-> event Accept(secret)\n-> out(c, secret)\n'
VERDICTS = [(SECURE, ResultStatus.SECURE), (ATTACK, ResultStatus.ATTACK_FOUND)]


def request(*, timeout_ms=2000, memory=64*MIB):
    return BackendRequest(request_id='request:proverif:admission', claim_id='claim:secrecy',
        declaration_id='declaration:protocol', claim_digest='1'*64,
        obligation_id='obligation:protocol', obligation_digest='2'*64,
        assumption_ids=('assumption:symbolic',), logic_family='cryptographic_protocol',
        query_kind=QueryKind.THEOREM_PROOF, requested_backend_id='proverif',
        bounds=ExecutionBounds(timeout_ms=timeout_ms, max_memory_bytes=memory,
                               max_output_bytes=8192, max_steps=100),
        payload={'encoding': 'pv', 'source': SOURCE})


def typed_request():
    return v2.ProtocolExecutionRequestV2(request_id='request:proverif:v2:admission',
        provider='proverif', source=SOURCE, source_format='pv', bounds=request().bounds)


def forbidden(*args, **kwargs):
    pytest.fail('ProVerif fixture reached forbidden execution or semantic parsing')


@pytest.fixture(autouse=True)
def no_host_process_or_shared_pool(monkeypatch):
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
        state_path=tmp_path/'private-proverif-pool.json', proof_resource_sampler=sample,
        total_cpu_slots=3, total_memory_mb=512, total_child_process_slots=3,
        proof_memory_headroom_mb=64, lane_reservations={}, auto_renew_leases=False,
        proof_backoff_seconds=.01, poll_interval_seconds=.002))
    calls, prepared, acquisitions, resolutions = [], [], [], []
    def resolve():
        resolutions.append(True)
        return owner
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', resolve)
    monkeypatch.setattr(process.shutil, 'which', lambda *a, **k: sys.executable)
    original_acquire = owner.acquire
    def acquire(*args, **kwargs):
        lease = original_acquire(*args, **kwargs)
        acquisitions.append(lease)
        return lease
    monkeypatch.setattr(owner, 'acquire', acquire)
    original_write = process.BoundedToolRunner._write_inputs
    def write(workspace, tool_request):
        prepared.append(workspace)
        return original_write(workspace, tool_request)
    monkeypatch.setattr(process.BoundedToolRunner, '_write_inputs', staticmethod(write))
    action = [lambda invocation, signal: process.RawProcessResult(returncode=0, stdout=SECURE)]
    def execute(self, invocation, cancellation=None):
        snapshot = owner.snapshot()
        assert snapshot['active_lease_count'] >= 1
        assert cancellation is not None and not cancellation.is_set()
        assert (invocation.cwd/'protocol.pv').read_text() == SOURCE
        assert len(invocation.argv) == 2
        calls.append((invocation, cancellation, snapshot, budget.current_proof_operation()))
        return action[0](invocation, cancellation)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', execute)
    yield SimpleNamespace(owner=owner, healthy=healthy, current=current, calls=calls,
        prepared=prepared, acquisitions=acquisitions, resolutions=resolutions, action=action, tmp=tmp_path)
    snapshot = owner.snapshot()
    assert snapshot['active_lease_count'] == snapshot['waiting_request_count'] == 0
    assert all(not workspace.exists() for workspace in prepared)


def assert_bound_protocol(outcome, req, status):
    assert outcome.result.status is status and outcome.result.authority is ResultAuthority.PROTOCOL
    assert outcome.result.translation_ceiling is EvidenceAuthority.BOUNDED
    assert outcome.receipt.accepted is (status is ResultStatus.SECURE)
    assert outcome.receipt.request_digest == outcome.source_binding.request_digest == req.digest
    assert outcome.result.bounds == req.bounds
    assert outcome.source_binding.source_digest == pv.content_digest(SOURCE)
    assert outcome.receipt.compile_digest == outcome.compile_result.source_digest
    assert [item.claim_id for item in outcome.receipt.claim_outcomes] == ['secrecy']
    assert outcome.result.metadata['process']['workspace_cleaned']


@pytest.mark.parametrize('stdout,status', VERDICTS)
@pytest.mark.parametrize('route', ['direct', 'registry', 'v2', 'helper'])
def test_default_execution_routes_use_one_admitted_native_lifecycle(host, stdout, status, route):
    host.action[0] = lambda invocation, signal: process.RawProcessResult(returncode=0, stdout=stdout)
    req = request()
    before = req.to_dict()
    if route == 'direct':
        assert_bound_protocol(pv.ProVerifBackend().run(req), req, status)
    elif route == 'registry':
        attempt, result = registry.default_backend_registry().run(req, backend_id='proverif')
        assert attempt.status.value == 'succeeded' and result.status.value == 'unknown'
        assert result.payload['result_status'] == status.value
        assert result.payload['result_authority'] == 'protocol' and not result.is_theorem_proof
        assert result.payload['result']['metadata']['process']['returncode'] == 0
        assert result.request_digest == attempt.request_digest == req.digest
        assert result.attempt_digest == attempt.digest and result.bounds == req.bounds
    else:
        result = (v2.ProtocolExecutionEngineV2().execute(typed_request()) if route == 'v2' else
                  v2.execute_proverif(source=SOURCE, bounds=req.bounds))
        assert result.evidence.result_status is status
        assert result.evidence.protocol_established and not result.evidence.is_theorem_authority
        assert result.evidence.translation_ceiling is EvidenceAuthority.BOUNDED
        assert result.backend_outcome['result']['metadata']['process']['returncode'] == 0
        assert result.evidence.assumptions.provider is v2.ProtocolProviderKind.PROVERIF
    assert req.to_dict() == before
    assert len(host.calls) == len(host.prepared) == len(host.acquisitions) == len(host.resolutions) == 1
    state = host.calls[0][2]
    assert state['active_lease_count'] == state['active_root_lease_count'] == 1
    assert state['allocated'] == {'cpu_slots': 1, 'memory_mb': 64}
    assert state['allocated_child_process_slots'] == 1 and host.acquisitions[0].released


def test_constructor_discovery_and_default_toolchain_metadata_do_not_acquire(host):
    selected = pv.ProVerifBackend()
    assert type(selected._runner) is admission.ResourceAdmittedToolRunner
    assert selected.supports('protocol', QueryKind.THEOREM_PROOF) and selected.is_available()
    assert selected.probe_toolchain().tool_version == 'proverif'
    assert selected.probe_toolchain().dependencies[0].version == 'unspecified'
    engine = v2.ProtocolExecutionEngineV2()
    assert type(engine.backend('proverif')._runner) is admission.ResourceAdmittedToolRunner
    assert type(engine.backend('tamarin')._runner) is admission.ResourceAdmittedToolRunner
    assert registry.default_backend_registry()['proverif']._delegate is None
    assert host.calls == host.prepared == host.acquisitions == host.resolutions == []


@pytest.mark.parametrize('memory', [64*MIB, 65*MIB+1])
def test_request_profile_and_compiled_source_are_preserved(host, memory):
    req = request(memory=memory)
    outcome = pv.ProVerifBackend().run(req)
    assert_bound_protocol(outcome, req, ResultStatus.SECURE)
    invocation, _, snapshot, operation = host.calls[0]
    assert operation is None
    assert 0 < invocation.limits.timeout_seconds <= 2 and invocation.limits.cpu_seconds == 2
    assert invocation.limits.memory_bytes == memory and invocation.limits.resident_memory_bytes is None
    assert invocation.limits.max_output_bytes == invocation.limits.max_input_bytes == 8192
    assert invocation.limits.max_workspace_bytes == 16384
    assert snapshot['allocated']['memory_mb'] == (memory+MIB-1)//MIB
    assert invocation.argv[1] == str(invocation.cwd/'protocol.pv')
    assert invocation.environment['HOME'] == invocation.environment['TMPDIR'] == str(invocation.cwd)
    metadata = outcome.result.metadata['process'].to_dict()
    assert metadata == {
        'cancelled': False, 'command': ['proverif', '{workspace}/protocol.pv'], 'error': '',
        'output_truncated': False, 'returncode': 0, 'resource_exhausted': False,
        'stdout_digest': pv.content_digest(SECURE), 'stderr_digest': pv.content_digest(''),
        'timed_out': False, 'unavailable': False, 'workspace_cleaned': True,
        'workspace_limit_exceeded': False, 'process_tree_terminated': False, 'termination_reason': 'completed',
    }


@pytest.mark.parametrize('falsey,route', [(False, 'direct'), (True, 'v2')])
def test_explicit_plain_runner_retains_ownership_and_signal(host, monkeypatch, falsey, route):
    calls = []; token = threading.Event()
    def execute(invocation, signal):
        assert host.owner.snapshot()['active_lease_count'] == 0
        calls.append((invocation, signal, budget.current_proof_operation()))
        return process.RawProcessResult(returncode=0, stdout=SECURE)
    class SuppliedRunner(process.BoundedToolRunner):
        def __bool__(self):
            return not falsey
    supplied = SuppliedRunner(executor=execute, workspace_root=host.tmp/'plain')
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', forbidden)
    selected = pv.ProVerifBackend(runner=supplied, available_probe=lambda: True)
    assert selected._runner is supplied
    if route == 'direct':
        assert_bound_protocol(selected.run(request(), cancellation=token), request(), ResultStatus.SECURE)
        assert calls[0][1] is token
    else:
        result = v2.ProtocolExecutionEngineV2(proverif=selected).execute(typed_request())
        assert result.evidence.protocol_established and calls[0][1] is not None
        assert calls[0][1] is calls[0][2]
        assert budget.current_proof_operation() is None
    assert len(calls) == 1 and calls[0][0].limits.timeout_seconds == 2
    assert host.calls == host.acquisitions == host.resolutions == []


@pytest.mark.parametrize('early', ['unsupported', 'unavailable'])
def test_early_nonexecution_keeps_receipt_shape_without_process_metadata(host, early):
    class UnsupportedCompiler(pv.ProVerifCompiler):
        def compile_source(self, source, **kwargs):
            return replace(super().compile_source(source, **kwargs), unsupported_claims=('unsupported:fixture',))
    selected = (pv.ProVerifBackend(compiler=UnsupportedCompiler()) if early == 'unsupported' else
                pv.ProVerifBackend(available_probe=lambda: False))
    outcome = selected.run(request())
    assert outcome.result.status is (ResultStatus.UNSUPPORTED if early == 'unsupported' else ResultStatus.UNAVAILABLE)
    assert not outcome.receipt.accepted and not outcome.receipt.claim_outcomes
    assert 'process' not in outcome.result.metadata
    assert host.calls == host.prepared == host.acquisitions == host.resolutions == []


def test_precancelled_direct_native_run_does_not_resolve_scheduler(host):
    token = threading.Event(); token.set()
    outcome = pv.ProVerifBackend().run(request(), cancellation=token)
    assert outcome.result.status is ResultStatus.ERROR and not outcome.receipt.accepted
    assert not outcome.receipt.claim_outcomes and outcome.result.metadata['process']['cancelled']
    assert host.calls == host.prepared == host.acquisitions == host.resolutions == []


@pytest.mark.parametrize('stdout,status,stop', [(SECURE, ResultStatus.SECURE, 'timeout'),
                                               (ATTACK, ResultStatus.ATTACK_FOUND, 'cancel')])
def test_registry_ambient_stop_withholds_late_secure_or_attack_output(host, clock, stdout, status, stop):
    token = threading.Event()
    def late(invocation, signal):
        assert invocation.limits.timeout_seconds == pytest.approx(.5)
        assert invocation.limits.cpu_seconds == pytest.approx(.5)
        if stop == 'timeout':
            clock[0] += .6
        else:
            token.set()
        assert signal.is_set()
        return process.RawProcessResult(returncode=0, stdout=stdout)
    host.action[0] = late
    req = request()
    attempt, result = registry.default_backend_registry().run(req, backend_id='proverif',
        operation_timeout_ms=500, cancellation=token)
    assert attempt.status.value == ('timed_out' if stop == 'timeout' else 'cancelled')
    assert result.status.value == 'unknown' and not result.is_theorem_proof
    assert result.request_digest == req.digest and result.attempt_digest == attempt.digest
    assert result.bounds == req.bounds and len(host.calls) == 1
    assert host.acquisitions[0].released and budget.current_proof_operation() is None


def test_native_budget_consumes_compile_and_explicit_toolchain_callback_time(host, clock):
    class SlowCompiler(pv.ProVerifCompiler):
        def compile_source(self, *args, **kwargs):
            value = super().compile_source(*args, **kwargs)
            clock[0] += .2
            return value
    def version():
        clock[0] += .3
        return 'fixture-version'
    with budget.proof_operation_scope(timeout_ms=1000):
        outcome = pv.ProVerifBackend(compiler=SlowCompiler(), version_probe=version).run(request())
    assert outcome.result.status is ResultStatus.SECURE
    limits = host.calls[0][0].limits
    assert limits.timeout_seconds == pytest.approx(.5) and limits.cpu_seconds == pytest.approx(.5)
    assert outcome.result.bounds.timeout_ms == 2000


def until(predicate):
    deadline = time.monotonic()+2
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail('bounded ProVerif fixture wait expired')
        time.sleep(.003)


PRESSURE = [({'cpu_stall_percent': 90}, 'proof_cpu_stall'),
    ({'available_memory_mb': 32}, 'proof_memory_headroom'),
    ({'available_pid_tasks': 0}, 'proof_pid_headroom'),
    (None, 'proof_resource_telemetry_unknown')]


@pytest.mark.parametrize('changes,reason', PRESSURE)
def test_pressure_prevents_workspace_and_executor_then_resumes_same_request(host, changes, reason):
    host.current[0] = replace(host.healthy, **changes) if changes is not None else OSError('no sample')
    token = threading.Event(); observed = {}; req = request(timeout_ms=5000)
    def work():
        try:
            observed['outcome'] = pv.ProVerifBackend().run(req, cancellation=token)
        except BaseException as error:
            observed['error'] = error
    worker = threading.Thread(target=work); worker.start()
    try:
        until(lambda: host.owner.snapshot()['proof_backoff'].get('reason') == reason)
        assert host.prepared == host.calls == host.acquisitions == []
        host.current[0] = host.healthy
        worker.join(timeout=3)
        assert not worker.is_alive() and 'error' not in observed
        assert_bound_protocol(observed['outcome'], req, ResultStatus.SECURE)
        assert len(host.calls) == len(host.acquisitions) == 1
    finally:
        token.set(); host.current[0] = host.healthy; worker.join(timeout=3)


@pytest.mark.parametrize('stop', ['timeout', 'cancel'])
def test_registry_stop_drains_pressure_queue_and_preserves_foreign_owner(host, clock, stop):
    foreign = host.owner.acquire('validation', cpu_slots=1, memory_mb=32, child_process_slots=1, timeout=0)
    host.current[0] = replace(host.healthy, available_pid_tasks=0)
    token = threading.Event(); observed = {}
    def work():
        try:
            observed['pair'] = registry.default_backend_registry().run(request(), backend_id='proverif',
                operation_timeout_ms=500, cancellation=token)
        except BaseException as error:
            observed['error'] = error
    worker = threading.Thread(target=work); worker.start()
    try:
        until(lambda: host.owner.snapshot()['proof_backoff'].get('reason') == 'proof_pid_headroom')
        assert host.prepared == host.calls == []
        if stop == 'timeout':
            clock[0] += .6
        else:
            token.set()
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
        token.set(); host.current[0] = host.healthy; worker.join(timeout=3); foreign.release()


def test_supplied_admitted_child_does_not_double_charge_or_release_parent(host):
    with host.owner.acquire('orchestration', cpu_slots=2, memory_mb=256, child_process_slots=2, timeout=0) as parent:
        with host.owner.acquire('validation', cpu_slots=1, memory_mb=32, child_process_slots=1, timeout=0) as foreign:
            allocated = host.owner.snapshot()['allocated']
            runner = admission.ResourceAdmittedToolRunner(parent_lease=parent)
            assert_bound_protocol(pv.ProVerifBackend(runner=runner).run(request()), request(), ResultStatus.SECURE)
            snapshot = host.calls[0][2]
            assert snapshot['active_lease_count'] == 3 and snapshot['active_root_lease_count'] == 2
            assert snapshot['allocated'] == allocated and host.resolutions == []
            assert not parent.released and not parent.cancelled
            assert not foreign.released and not foreign.cancelled
            assert host.owner.snapshot()['active_lease_count'] == 2


def test_oversize_memory_request_is_refused_before_workspace_without_resizing(host):
    req = request(memory=513*MIB)
    outcome = pv.ProVerifBackend().run(req)
    assert outcome.result.status is ResultStatus.ERROR and not outcome.receipt.claim_outcomes
    assert outcome.result.bounds == req.bounds and not outcome.receipt.accepted
    assert outcome.result.metadata['process']['resource_exhausted']
    assert host.prepared == host.calls == host.acquisitions == []


def test_executor_exception_cleans_workspace_and_releases_reservation(host):
    def fail(invocation, signal):
        raise OSError('synthetic native failure')
    host.action[0] = fail
    outcome = pv.ProVerifBackend().run(request())
    assert outcome.result.status is ResultStatus.ERROR and not outcome.receipt.claim_outcomes
    assert outcome.result.metadata['process']['workspace_cleaned']
    assert 'synthetic native failure' in outcome.result.reason
    assert len(host.calls) == 1 and host.acquisitions[0].released


class FixedRunner(process.BoundedToolRunner):
    def __init__(self, result):
        super().__init__(executor=forbidden)
        self.result = result
        self.requests = []

    def run(self, tool_request, *, cancellation=None):
        self.requests.append(tool_request)
        return self.result


def lifecycle(stdout=SECURE, **changes):
    return process.ToolRunResult(**{
        'interface_version': process.BOUNDED_TOOL_RUNNER_VERSION, 'runtime': process.ToolRuntime.NATIVE,
        'command': ('proverif', 'protocol.pv'), 'returncode': 0, 'stdout': stdout, 'stderr': '',
        'elapsed_seconds': .01, 'output_files': {}, 'termination_reason': 'completed', **changes})


def deny_parsers(monkeypatch):
    for name in ('parse_proverif_claim_outcomes', 'classify_claim_outcomes', 'parse_attack_trace'):
        monkeypatch.setattr(pv, name, forbidden)
    monkeypatch.setattr(pv.NormalizedAttackTrace, 'replay', forbidden)


UNSAFE = [({'unavailable': True}, ResultStatus.UNAVAILABLE),
    ({'timed_out': True}, ResultStatus.TIMEOUT), ({'cancelled': True}, ResultStatus.ERROR),
    ({'resource_exhausted': True}, ResultStatus.ERROR), ({'output_truncated': True}, ResultStatus.ERROR),
    ({'workspace_limit_exceeded': True}, ResultStatus.ERROR), ({'error': 'fixture cleanup failed'}, ResultStatus.ERROR),
    ({'workspace_cleaned': False}, ResultStatus.ERROR), ({'process_tree_terminated': True}, ResultStatus.ERROR)]


@pytest.mark.parametrize('stdout,healthy_status', VERDICTS)
@pytest.mark.parametrize('changes,status', UNSAFE)
def test_unsafe_lifecycle_blocks_claim_classification_attack_parsing_and_replay(
        monkeypatch, stdout, healthy_status, changes, status):
    deny_parsers(monkeypatch)
    raw = lifecycle(stdout, **changes)
    runner = FixedRunner(raw)
    outcome = pv.ProVerifBackend(runner=runner, available_probe=lambda: True).run(request())
    assert outcome.result.status is status and not outcome.receipt.accepted
    assert outcome.receipt.claim_outcomes == ()
    assert outcome.result.translation_ceiling is EvidenceAuthority.NONE
    assert 'attack_traces' not in outcome.result.witness
    metadata = outcome.result.metadata['process']
    for name, value in changes.items():
        assert metadata[name] == value
    assert metadata['stdout_digest'] == pv.content_digest(stdout)
    assert metadata['returncode'] == 0 and metadata['termination_reason'] == 'completed'
    assert len(runner.requests) == 1


@pytest.mark.parametrize('stdout,code', [(SECURE, 1), (ATTACK, 1), (ATTACK, 2),
    (SECURE, -9), (SECURE, None), (ATTACK, None), (SECURE, False), (ATTACK, 0.0)])
def test_missing_nonzero_or_noninteger_exit_refuses_both_secure_and_attack_before_parsing(
        monkeypatch, stdout, code):
    deny_parsers(monkeypatch)
    runner = FixedRunner(lifecycle(stdout, returncode=code))
    outcome = pv.ProVerifBackend(runner=runner, available_probe=lambda: True).run(request())
    assert outcome.result.status is ResultStatus.ERROR and not outcome.receipt.accepted
    assert not outcome.receipt.claim_outcomes
    assert outcome.result.metadata['process']['returncode'] == code
    assert outcome.result.reason


@pytest.mark.parametrize('overflow', [False, True])
def test_combined_utf8_boundary_is_checked_before_claim_parser(monkeypatch, overflow):
    stdout = SECURE+'é'*1800
    remaining = 8192-len(stdout.encode())
    stderr = 'é'*(remaining//2)+' '*(remaining%2)+('é' if overflow else '')
    assert len(stdout.encode()) < 8192 and len(stderr.encode()) < 8192
    assert len(stdout)+len(stderr) < 8192
    if overflow:
        deny_parsers(monkeypatch)
    runner = FixedRunner(lifecycle(stdout, stderr=stderr))
    outcome = pv.ProVerifBackend(runner=runner, available_probe=lambda: True).run(request())
    assert outcome.result.status is (ResultStatus.ERROR if overflow else ResultStatus.SECURE)
    assert outcome.receipt.accepted is (not overflow)
    assert bool(outcome.receipt.claim_outcomes) is (not overflow)
    assert outcome.result.usage.output_bytes == 8192+(2 if overflow else 0)


@pytest.mark.parametrize('stdout,healthy_status', VERDICTS)
def test_v2_cannot_publish_protocol_or_attack_from_failed_lifecycle(monkeypatch, stdout, healthy_status):
    deny_parsers(monkeypatch)
    selected = pv.ProVerifBackend(runner=FixedRunner(lifecycle(stdout, workspace_cleaned=False)),
                                 available_probe=lambda: True)
    result = v2.ProtocolExecutionEngineV2(proverif=selected).execute(typed_request())
    assert result.evidence.result_status is ResultStatus.ERROR
    assert result.disposition is v2.ProtocolDisposition.ERROR
    assert not result.evidence.protocol_established and not result.is_theorem_authority
    assert not result.evidence.attack.attack_traces and not result.evidence.attack.replayed
    assert result.backend_outcome['result']['metadata']['process']['workspace_cleaned'] is False


def test_rejected_nul_output_keeps_digest_without_invoking_parser(monkeypatch):
    deny_parsers(monkeypatch)
    stdout = ATTACK+'\x00malformed native bytes'
    raw = lifecycle(stdout, error='synthetic transport error')
    outcome = pv.ProVerifBackend(runner=FixedRunner(raw), available_probe=lambda: True).run(request())
    assert outcome.result.status is ResultStatus.ERROR and not outcome.receipt.accepted
    assert not outcome.receipt.claim_outcomes
    assert outcome.result.metadata['process']['stdout_digest'] == pv.stable_digest({'content': stdout})
    assert outcome.result.metadata['process']['error'] == 'synthetic transport error'
