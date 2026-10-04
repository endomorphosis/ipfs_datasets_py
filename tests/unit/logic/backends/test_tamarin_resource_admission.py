"""Tamarin admission and result integrity with private synthetic execution.

The resource envelope is an admission estimate, not hard aggregate containment.
Falsified fixture output remains unvalidated and never establishes attack replay.
"""
from dataclasses import replace
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process, registry, resource_admission as admission
from ipfs_datasets_py.logic.backends.protocol import tamarin as tm, execution_v2 as v2
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.backends.smt import operation_budget as budget
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest, ExecutionBounds, QueryKind
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


MIB = 1024**2
SOURCE = 'theory Admission\nbegin\nlemma secrecy:\n "All x #i. Secret(x) @ i ==> not (Ex #j. K(x) @ j)"\nend\n'
SECURE = 'lemma secrecy: verified (all-traces)\n'
ATTACK = 'lemma secrecy: falsified - found trace\nrule Reveal(secret)\n'
VERDICTS = [(SECURE, ResultStatus.SECURE), (ATTACK, ResultStatus.ATTACK_FOUND)]
# Preserve historical parameter IDs; the falsified input now expects UNKNOWN.


def request(*, timeout_ms=2000, memory=128*MIB):
    return BackendRequest(request_id='request:tamarin:admission', claim_id='claim:secrecy',
        declaration_id='declaration:protocol', claim_digest='1'*64,
        obligation_id='obligation:protocol', obligation_digest='2'*64,
        assumption_ids=('assumption:symbolic',), logic_family='cryptographic_protocol',
        query_kind=QueryKind.THEOREM_PROOF, requested_backend_id='tamarin',
        bounds=ExecutionBounds(timeout_ms=timeout_ms, max_memory_bytes=memory,
                               max_output_bytes=8192, max_steps=100),
        payload={'encoding': 'spthy', 'source': SOURCE})


def typed_request():
    return v2.ProtocolExecutionRequestV2(request_id='request:tamarin:v2:admission',
        provider='tamarin', source=SOURCE, source_format='spthy', bounds=request().bounds)


def forbidden(*args, **kwargs):
    pytest.fail('Tamarin fixture reached host execution, shared admission or forbidden semantic parsing')


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
        state_path=tmp_path/'private-tamarin-pool.json', proof_resource_sampler=sample,
        total_cpu_slots=4, total_memory_mb=1024, total_child_process_slots=16,
        proof_memory_headroom_mb=64, lane_reservations={}, auto_renew_leases=False,
        proof_backoff_seconds=.01, poll_interval_seconds=.002))
    calls, prepared, acquired, resolutions = [], [], [], []
    def resolve():
        resolutions.append(True)
        return owner
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', resolve)
    monkeypatch.setattr(process.shutil, 'which', lambda *args, **kwargs: sys.executable)
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
    action = [lambda invocation, signal: process.RawProcessResult(returncode=0, stdout=SECURE)]
    def execute(self, invocation, cancellation=None):
        snapshot = owner.snapshot()
        assert snapshot['active_lease_count'] >= 1
        assert cancellation is not None and not cancellation.is_set()
        assert (invocation.cwd/'protocol.spthy').read_text() == SOURCE
        calls.append((invocation, cancellation, snapshot, budget.current_proof_operation()))
        return action[0](invocation, cancellation)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', execute)
    yield SimpleNamespace(owner=owner, healthy=healthy, current=current, calls=calls,
        prepared=prepared, acquired=acquired, resolutions=resolutions, action=action, tmp=tmp_path)
    snapshot = owner.snapshot()
    assert snapshot['active_lease_count'] == snapshot['waiting_request_count'] == 0
    assert all(not path.exists() for path in prepared)


def assert_bound(outcome, req, status):
    expected = ResultStatus.UNKNOWN if status is ResultStatus.ATTACK_FOUND else status
    assert outcome.result.status is expected and outcome.result.authority is ResultAuthority.PROTOCOL
    assert outcome.result.translation_ceiling is (EvidenceAuthority.BOUNDED if expected is ResultStatus.SECURE else EvidenceAuthority.NONE)
    assert outcome.receipt.accepted is (status is ResultStatus.SECURE)
    assert outcome.request_digest == outcome.source_binding.request_digest == req.digest
    assert outcome.result.bounds == req.bounds and outcome.source_binding.source_digest == tm.content_digest(SOURCE)
    assert outcome.receipt.compile_digest == outcome.compile_result.source_digest
    assert [item.claim_id for item in outcome.receipt.claim_outcomes] == ['secrecy']
    assert all(item.attack_trace is None for item in outcome.receipt.claim_outcomes)
    assert outcome.result.metadata['process']['workspace_cleaned']


@pytest.mark.parametrize('stdout,status', VERDICTS)
@pytest.mark.parametrize('route', ['direct', 'registry', 'v2', 'helper'])
def test_default_routes_reserve_one_finite_profile_and_preserve_authority(host, stdout, status, route):
    host.action[0] = lambda invocation, signal: process.RawProcessResult(returncode=0, stdout=stdout)
    req = request(); before = req.to_dict()
    expected = ResultStatus.UNKNOWN if status is ResultStatus.ATTACK_FOUND else status
    if route == 'direct':
        assert_bound(tm.TamarinBackend().run(req), req, status)
    elif route == 'registry':
        attempt, result = registry.default_backend_registry().run(req, backend_id='tamarin')
        assert attempt.status.value == 'succeeded' and result.status.value == 'unknown'
        assert result.payload['result_status'] == expected.value and not result.is_theorem_proof
        assert result.request_digest == attempt.request_digest == req.digest
        assert result.attempt_digest == attempt.digest and result.bounds == req.bounds
    else:
        result = (v2.ProtocolExecutionEngineV2().execute(typed_request()) if route == 'v2' else
                  v2.execute_tamarin(source=SOURCE, bounds=req.bounds))
        assert result.evidence.result_status is expected and result.protocol_established is (expected is ResultStatus.SECURE)
        assert not result.is_theorem_authority
        assert result.evidence.translation_ceiling is (EvidenceAuthority.BOUNDED if expected is ResultStatus.SECURE else EvidenceAuthority.NONE)
        assert not result.evidence.attack.replayed and not result.evidence.attack.attack_traces
        assert result.backend_outcome['result']['metadata']['process']['returncode'] == 0
    assert req.to_dict() == before
    assert len(host.calls) == len(host.acquired) == len(host.prepared) == len(host.resolutions) == 1
    invocation, signal, snapshot, _ = host.calls[0]
    assert snapshot['active_lease_count'] == snapshot['active_root_lease_count'] == 1
    assert snapshot['allocated'] == {'cpu_slots': 2, 'memory_mb': 128}
    assert snapshot['allocated_child_process_slots'] == 8 and host.acquired[0].released
    assert invocation.limits.resident_memory_bytes == 128*MIB
    assert invocation.limits.memory_bytes == 2*1024*MIB
    assert signal is not None


@pytest.mark.parametrize('memory', [1, 128*MIB+3, 600*MIB])
def test_managed_profile_uses_requested_rss_and_integer_heap_without_inflating_request(host, memory):
    backend = tm.TamarinBackend(maude_executable='./tools/maude-3.5.1')
    req = request(memory=memory)
    tool = backend._tool_request(SOURCE, req.bounds)
    assert tool.argv == ('tamarin-prover', '--prove', '--with-maude=./tools/maude-3.5.1',
        '{workspace}/protocol.spthy', '+RTS', '-N1', f'-M{max(1,memory//2)}', '-RTS')
    assert tool.limits.resident_memory_bytes == memory
    assert tool.limits.memory_bytes == max(2*1024*MIB, 4*memory)
    assert tool.limits.timeout_seconds == tool.limits.cpu_seconds == req.bounds.timeout_ms/1000
    assert tool.limits.max_input_bytes == tool.limits.max_output_bytes == req.bounds.max_output_bytes
    assert tool.input_files['protocol.spthy'] == SOURCE
    assert req.bounds.max_memory_bytes == memory
    assert host.resolutions == host.calls == []


def test_default_runtime_environment_drops_host_debug_and_rts_controls(host, monkeypatch):
    monkeypatch.setenv('GHCRTS', '-N999 -M999G')
    monkeypatch.setenv('DEBUG_MAUDE', '1')
    req = request(memory=128*MIB+3)
    assert_bound(tm.TamarinBackend().run(req), req, ResultStatus.SECURE)
    invocation, _, snapshot, _ = host.calls[0]
    assert 'GHCRTS' not in invocation.environment and 'DEBUG_MAUDE' not in invocation.environment
    assert snapshot['allocated']['memory_mb'] == 129
    assert invocation.limits.resident_memory_bytes == req.bounds.max_memory_bytes


def test_default_construction_discovery_and_metadata_are_admission_free(host):
    backend = tm.TamarinBackend()
    assert type(backend._runner) is admission.ResourceAdmittedToolRunner
    assert (backend._runner.cpu_slots, backend._runner.child_process_slots) == (2, 8)
    assert backend.is_available() and backend.supports('protocol', QueryKind.THEOREM_PROOF)
    assert backend.probe_toolchain().tool_version == 'tamarin-prover'
    assert backend.probe_toolchain().dependencies[0].version == 'unspecified'
    assert type(v2.ProtocolExecutionEngineV2().backend('tamarin')._runner) is admission.ResourceAdmittedToolRunner
    assert registry.default_backend_registry()['tamarin']._delegate is None
    assert host.resolutions == host.calls == host.prepared == []


@pytest.mark.parametrize('executable', ['maude', '/tmp/maude-3.5.1', './tools/maude+cpu'])
def test_safe_maude_token_is_passed_as_one_argument_without_execution(executable):
    backend = tm.TamarinBackend(maude_executable=executable)
    assert '--with-maude='+executable in backend._tool_request(SOURCE, request().bounds).argv


@pytest.mark.parametrize('executable', ['-maude', 'maude shell', '/tmp/maude;id', 'maude$(id)'])
def test_unreviewed_maude_shell_tokens_refused_before_lookup(host, executable):
    with pytest.raises(tm.TamarinBackendError):
        tm.TamarinBackend(maude_executable=executable)
    assert not host.calls and not host.resolutions
    # The old explicitly injected lifecycle retains its own command policy.
    owned = process.BoundedToolRunner(executor=forbidden)
    assert tm.TamarinBackend(maude_executable=executable, runner=owned)._runner is owned


@pytest.mark.parametrize('kind', ['plain', 'falsey_plain', 'admitted', 'falsey_admitted'])
def test_any_explicit_runner_keeps_legacy_argv_memory_and_ownership(host, kind):
    seen = []
    base = admission.ResourceAdmittedToolRunner if 'admitted' in kind else process.BoundedToolRunner
    class Owned(base):
        def __bool__(self):
            return not kind.startswith('falsey')
    def execute(invocation, cancellation):
        seen.append((invocation, cancellation))
        return process.RawProcessResult(returncode=0, stdout=SECURE)
    kwargs = {'scheduler': host.owner} if 'admitted' in kind else {}
    owned = Owned(executor=execute, **kwargs)
    backend = tm.TamarinBackend(runner=owned, available_probe=lambda: True)
    signal = threading.Event(); req = request()
    assert_bound(backend.run(req, cancellation=signal), req, ResultStatus.SECURE)
    assert backend._runner is owned and len(seen) == 1
    invocation, passed = seen[0]
    assert invocation.argv == ('tamarin-prover', '--prove', str(invocation.cwd/'protocol.spthy'))
    assert invocation.limits.memory_bytes == req.bounds.max_memory_bytes
    assert invocation.limits.resident_memory_bytes is None
    assert host.resolutions == []
    if 'admitted' in kind:
        assert len(host.acquired) == 1 and host.acquired[0].released
    else:
        assert passed is signal and host.acquired == []


@pytest.mark.parametrize('early', ['unsupported', 'unavailable'])
def test_nonexecuting_paths_never_reserve_and_do_not_invent_process_metadata(host, early):
    class Unsupported(tm.TamarinCompiler):
        def compile_source(self, *args, **kwargs):
            return replace(super().compile_source(*args, **kwargs), unsupported_claims=('unsupported:fixture',))
    backend = tm.TamarinBackend(compiler=Unsupported() if early == 'unsupported' else None,
                               available_probe=lambda: early != 'unavailable')
    outcome = backend.run(request())
    assert outcome.result.status is (ResultStatus.UNSUPPORTED if early == 'unsupported' else ResultStatus.UNAVAILABLE)
    assert not outcome.receipt.accepted and not outcome.receipt.claim_outcomes
    assert 'process' not in outcome.result.metadata
    assert host.calls == host.prepared == host.acquired == host.resolutions == []


def test_precancelled_run_never_resolves_or_reserves_default_pool(host):
    token = threading.Event(); token.set()
    outcome = tm.TamarinBackend().run(request(), cancellation=token)
    assert outcome.result.status is ResultStatus.ERROR and not outcome.receipt.claim_outcomes
    assert outcome.result.metadata['process']['cancelled']
    assert host.calls == host.prepared == host.acquired == host.resolutions == []


def until(predicate):
    deadline = time.monotonic()+2
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail('private Tamarin fixture wait expired')
        time.sleep(.003)


@pytest.mark.parametrize('changes,reason', [({'cpu_stall_percent': 90}, 'proof_cpu_stall'),
    ({'available_memory_mb': 32}, 'proof_memory_headroom'),
    ({'available_pid_tasks': 0}, 'proof_pid_headroom'),
    (None, 'proof_resource_telemetry_unknown')])
def test_external_pressure_blocks_workspace_then_recovers_same_request(host, changes, reason):
    host.current[0] = replace(host.healthy, **changes) if changes is not None else OSError('unavailable telemetry')
    req = request(timeout_ms=5000); token = threading.Event(); observed = {}
    def run():
        try:
            observed['result'] = tm.TamarinBackend().run(req, cancellation=token)
        except BaseException as error:
            observed['error'] = error
    thread = threading.Thread(target=run); thread.start()
    try:
        until(lambda: host.owner.snapshot()['proof_backoff'].get('reason') == reason)
        assert host.calls == host.prepared == host.acquired == []
        host.current[0] = host.healthy
        thread.join(3)
        assert not thread.is_alive() and 'error' not in observed
        assert_bound(observed['result'], req, ResultStatus.SECURE)
        assert len(host.calls) == len(host.acquired) == 1
    finally:
        token.set(); host.current[0] = host.healthy; thread.join(3)


@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
def test_registry_stop_drains_pressure_queue_and_preserves_foreign_reservation(host, clock, stop):
    foreign = host.owner.acquire('validation', cpu_slots=1, memory_mb=32, child_process_slots=1, timeout=0)
    host.current[0] = replace(host.healthy, available_pid_tasks=0)
    token = threading.Event(); observed = {}
    def run():
        try:
            observed['pair'] = registry.default_backend_registry().run(request(), backend_id='tamarin',
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
        snapshot = host.owner.snapshot()
        assert snapshot['active_lease_count'] == 1 and snapshot['waiting_request_count'] == 0
        assert not foreign.cancelled and not foreign.released
    finally:
        token.set(); host.current[0] = host.healthy; thread.join(3); foreign.release()


def test_injected_admitted_child_uses_legacy_profile_without_double_charge(host):
    with host.owner.acquire('orchestration', cpu_slots=2, memory_mb=256, child_process_slots=8, timeout=0) as parent:
        with host.owner.acquire('validation', cpu_slots=1, memory_mb=32, child_process_slots=1, timeout=0) as foreign:
            allocated = host.owner.snapshot()['allocated']
            runner = admission.ResourceAdmittedToolRunner(parent_lease=parent)
            assert_bound(tm.TamarinBackend(runner=runner).run(request()), request(), ResultStatus.SECURE)
            invocation, _, snapshot, _ = host.calls[0]
            assert snapshot['active_lease_count'] == 3 and snapshot['active_root_lease_count'] == 2
            assert snapshot['allocated'] == allocated and not host.resolutions
            assert invocation.limits.memory_bytes == 128*MIB and invocation.limits.resident_memory_bytes is None
            assert not parent.released and not parent.cancelled and not foreign.released
            assert host.owner.snapshot()['active_lease_count'] == 2


def test_oversize_requested_memory_refuses_before_workspace_without_resizing(host):
    req = request(memory=1025*MIB)
    outcome = tm.TamarinBackend().run(req)
    assert outcome.result.status is ResultStatus.ERROR and not outcome.receipt.claim_outcomes
    assert outcome.result.bounds == req.bounds and outcome.result.metadata['process']['resource_exhausted']
    assert host.calls == host.prepared == host.acquired == []


def test_executor_error_cleans_workspace_before_releasing_reservation(host, monkeypatch):
    released = []
    original_release = schedulers.ResourceLease.release
    def release(lease):
        assert len(host.prepared) == 1 and not host.prepared[0].exists()
        released.append(lease)
        return original_release(lease)
    monkeypatch.setattr(schedulers.ResourceLease, 'release', release)
    def fail(invocation, signal):
        raise OSError('synthetic Tamarin execution failure')
    host.action[0] = fail
    outcome = tm.TamarinBackend().run(request())
    assert outcome.result.status is ResultStatus.ERROR and not outcome.receipt.claim_outcomes
    assert outcome.result.metadata['process']['workspace_cleaned']
    assert len(host.calls) == 1 and host.acquired[0].released
    assert released == host.acquired


@pytest.mark.parametrize('route', ['registry', 'v2'])
@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
def test_ambient_operation_stop_withholds_late_native_conclusion(host, clock, route, stop):
    token = threading.Event()
    def late(invocation, signal):
        assert invocation.limits.timeout_seconds == pytest.approx(.5)
        assert invocation.limits.cpu_seconds == pytest.approx(.5)
        if stop == 'timeout':
            clock[0] += .6
        else:
            token.set()
        assert signal.is_set()
        return process.RawProcessResult(returncode=0, stdout=ATTACK if stop == 'cancel' else SECURE)
    host.action[0] = late
    if route == 'registry':
        attempt, result = registry.default_backend_registry().run(request(), backend_id='tamarin',
            operation_timeout_ms=500, cancellation=token)
        assert attempt.status.value == ('timed_out' if stop == 'timeout' else 'cancelled')
        assert result.status.value == 'unknown' and not result.is_theorem_proof
    else:
        expected = budget.ProofOperationTimeout if stop == 'timeout' else budget.ProofOperationCancelled
        with pytest.raises(expected):
            v2.ProtocolExecutionEngineV2().execute(typed_request(), operation_timeout_ms=500, cancellation=token)
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


def lifecycle(stdout=SECURE, **changes):
    return process.ToolRunResult(**{
        'interface_version': process.BOUNDED_TOOL_RUNNER_VERSION, 'runtime': process.ToolRuntime.NATIVE,
        'command': ('tamarin-prover', '--prove', 'protocol.spthy'), 'returncode': 0,
        'stdout': stdout, 'stderr': '', 'elapsed_seconds': .01, 'output_files': {},
        'termination_reason': 'completed', **changes})


def deny_parsers(monkeypatch):
    for name in ('parse_tamarin_claim_outcomes', 'classify_claim_outcomes', 'parse_attack_trace'):
        monkeypatch.setattr(tm, name, forbidden)
    monkeypatch.setattr(tm.NormalizedAttackTrace, 'replay', forbidden)


UNSAFE = [({'unavailable': True}, ResultStatus.UNAVAILABLE),
    ({'cancelled': True}, ResultStatus.ERROR), ({'timed_out': True}, ResultStatus.TIMEOUT),
    ({'resource_exhausted': True}, ResultStatus.ERROR), ({'output_truncated': True}, ResultStatus.ERROR),
    ({'workspace_limit_exceeded': True}, ResultStatus.ERROR), ({'error': 'fixture cleanup failed'}, ResultStatus.ERROR),
    ({'workspace_cleaned': False}, ResultStatus.ERROR), ({'process_tree_terminated': True}, ResultStatus.ERROR)]


@pytest.mark.parametrize('stdout,healthy_status', VERDICTS)
@pytest.mark.parametrize('changes,status', UNSAFE)
def test_unsafe_lifecycle_never_reaches_claim_or_attack_classification(monkeypatch, stdout, healthy_status, changes, status):
    deny_parsers(monkeypatch)
    raw = lifecycle(stdout, **changes)
    runner = FixedRunner(raw)
    outcome = tm.TamarinBackend(runner=runner, available_probe=lambda: True).run(request())
    assert outcome.result.status is status and not outcome.receipt.accepted
    assert not outcome.receipt.claim_outcomes and outcome.result.translation_ceiling is EvidenceAuthority.NONE
    assert 'attack_traces' not in outcome.result.witness
    metadata = outcome.result.metadata['process']
    assert set(metadata) == {'cancelled', 'command', 'error', 'output_truncated', 'process_tree_terminated',
        'returncode', 'resource_exhausted', 'stderr_digest', 'stdout_digest', 'timed_out',
        'termination_reason', 'unavailable', 'workspace_cleaned', 'workspace_limit_exceeded'}
    for name, value in changes.items():
        assert metadata[name] == value
    assert metadata['stdout_digest'] == tm.content_digest(stdout)
    assert metadata['returncode'] == 0 and metadata['termination_reason'] == 'completed'
    assert list(metadata['command']) == list(raw.command)
    assert len(runner.requests) == 1


@pytest.mark.parametrize('stdout,code', [(SECURE, 1), (ATTACK, 1), (ATTACK, -9),
                                      (SECURE, None), (ATTACK, False), (SECURE, 0.0)])
def test_nonzero_missing_or_noninteger_exit_refuses_before_parsing(monkeypatch, stdout, code):
    deny_parsers(monkeypatch)
    outcome = tm.TamarinBackend(runner=FixedRunner(lifecycle(stdout, returncode=code)),
        available_probe=lambda: True).run(request())
    assert outcome.result.status is ResultStatus.ERROR and not outcome.receipt.accepted
    assert not outcome.receipt.claim_outcomes and outcome.result.reason
    assert outcome.result.metadata['process']['returncode'] == code


@pytest.mark.parametrize('overflow', [False, True])
def test_combined_utf8_output_boundary_checked_before_parser(monkeypatch, overflow):
    stdout = SECURE+'é'*1800
    remaining = 8192-len(stdout.encode())
    stderr = 'é'*(remaining//2)+' '*(remaining%2)+('é' if overflow else '')
    assert len(stdout.encode()) < 8192 and len(stderr.encode()) < 8192
    assert len(stdout)+len(stderr) < 8192
    if overflow:
        deny_parsers(monkeypatch)
    outcome = tm.TamarinBackend(runner=FixedRunner(lifecycle(stdout, stderr=stderr)),
        available_probe=lambda: True).run(request())
    assert outcome.result.status is (ResultStatus.ERROR if overflow else ResultStatus.SECURE)
    assert outcome.receipt.accepted is (not overflow)
    assert outcome.result.usage.output_bytes == 8192+(2 if overflow else 0)


@pytest.mark.parametrize('stdout,status', VERDICTS)
def test_v2_cannot_publish_secure_or_replayed_attack_from_failed_cleanup(monkeypatch, stdout, status):
    deny_parsers(monkeypatch)
    backend = tm.TamarinBackend(runner=FixedRunner(lifecycle(stdout, workspace_cleaned=False)),
        available_probe=lambda: True)
    result = v2.ProtocolExecutionEngineV2(tamarin=backend).execute(typed_request())
    assert result.evidence.result_status is ResultStatus.ERROR
    assert not result.protocol_established and not result.is_theorem_authority
    assert not result.evidence.attack.attack_traces and not result.evidence.attack.replayed
    assert result.backend_outcome['result']['metadata']['process']['workspace_cleaned'] is False


def test_rejected_nul_output_is_hashed_without_semantic_parsing(monkeypatch):
    deny_parsers(monkeypatch)
    stdout = ATTACK+'\x00malformed native output'
    outcome = tm.TamarinBackend(runner=FixedRunner(lifecycle(stdout, error='synthetic transport failure')),
        available_probe=lambda: True).run(request())
    assert outcome.result.status is ResultStatus.ERROR and not outcome.receipt.claim_outcomes
    assert outcome.result.metadata['process']['stdout_digest'] == tm.stable_digest({'content': stdout})
