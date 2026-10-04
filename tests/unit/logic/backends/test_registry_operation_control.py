"""Generic execution budgets include setup and refuse late result publication.

Clocks and executor observations are synthetic. No native process, installer or
resource scheduler is used; caller-owned callback signatures remain unchanged.
"""
from dataclasses import replace
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process, registry as reg, resource_admission
from ipfs_datasets_py.logic.backends.smt import admitted, operation_budget as budget
from ipfs_datasets_py.logic.ir_core import protocols as core


ROUTES = ('callable', 'lazy', 'registry')
CAPABILITIES = core.BackendCapabilities(logic_families=('first_order',),
    query_kinds=(core.QueryKind.THEOREM_PROOF,), deterministic=True)


def request(timeout_ms=1000, *, tag='one'):
    return core.BackendRequest(request_id='request:registry:' + tag, claim_id='claim:registry',
        declaration_id='declaration:registry', claim_digest='1' * 64,
        obligation_id='obligation:registry', obligation_digest='2' * 64,
        assumption_ids=('assumption:bounded',), logic_family='first_order',
        query_kind=core.QueryKind.THEOREM_PROOF,
        bounds=core.ExecutionBounds(timeout_ms=timeout_ms, max_memory_bytes=256 * 1024**2,
            max_output_bytes=65536, max_steps=100),
        payload={'smtlib': '(set-logic QF_LIA)\n(assert false)\n(check-sat)\n'})


def entry():
    return reg.ProviderMatrixEntry(provider_id='fixture', family=reg.PROVIDER_MATRIX_FAMILY_STATE_MODEL,
        logic_families=('first_order',), query_kinds=('theorem_proof',), factory_key='fixture',
        aliases=('fixture-alias',))


@pytest.fixture(autouse=True)
def no_host_work(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail('registry fixtures must not start native tools or use a resource scheduler')
    monkeypatch.setattr(subprocess, 'Popen', denied)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', denied)
    monkeypatch.setattr(resource_admission, 'get_global_resource_scheduler', denied)


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    fake = SimpleNamespace(monotonic=lambda: now[0])
    for module in (reg, budget, admitted):
        monkeypatch.setattr(module, 'time', fake)
    return now


@pytest.fixture
def lane(clock):
    def make(route, *, action=None, returned=None):
        calls, observations = [], []
        def touch(phase, req=None):
            calls.append(phase)
            operation = budget.current_proof_operation()
            observations.append((phase, operation, req))
            if action:
                action(phase, req)
        def probe():
            touch('probe')
            return True
        def compile_request(req):
            touch('compile', req)
            return reg.CompiledBackendRequest(req.digest, 'fixture', '(check-sat)\n')
        def execute(compiled, req):
            touch('run', req)
            return reg.BackendRunnerOutput(stdout='unsat\n', elapsed_ms=1)
        delegate = reg.CallableProofBackend(backend_id='fixture', backend_version='fixture/v1',
            capabilities=CAPABILITIES, compiler=compile_request, runner=execute, availability_probe=probe)
        if returned is not None:
            def foreign_run(req):
                touch('run', req)
                return returned(req) if callable(returned) else returned
            delegate = SimpleNamespace(run=foreign_run, is_available=probe)
        def factory():
            touch('factory')
            return delegate
        lazy = reg.LazyMatrixProofBackend(entry(), factory=factory)
        owner = reg.ProofBackendRegistry((lazy,))
        target = delegate if route == 'callable' else lazy if route == 'lazy' else owner
        return SimpleNamespace(target=target, lazy=lazy, owner=owner, delegate=delegate,
            calls=calls, observations=observations)
    return make


def assert_stopped(pair, req, kind):
    attempt, result = pair
    assert attempt.status is (core.AttemptStatus.CANCELLED if kind == 'cancel' else core.AttemptStatus.TIMED_OUT)
    assert result.status is core.ResultStatus.UNKNOWN and not result.is_theorem_proof
    assert attempt.request_digest == result.request_digest == req.digest
    assert result.attempt_digest == attempt.digest
    assert attempt.bounds == result.bounds == req.bounds
    assert result.claim_digest == req.claim_digest and result.obligation_digest == req.obligation_digest
    assert result.assumption_ids == req.assumption_ids
    assert attempt.usage.elapsed_ms <= req.bounds.timeout_ms
    assert attempt.diagnostics and result.diagnostics


@pytest.mark.parametrize('route', ROUTES)
def test_precancel_returns_bound_terminal_before_any_setup(lane, route):
    selected = lane(route)
    signal = threading.Event(); signal.set()
    req = request()
    assert_stopped(selected.target.run(req, cancellation=signal), req, 'cancel')
    assert selected.calls == []
    assert budget.current_proof_operation() is None


@pytest.mark.parametrize('kind', [kind for kind in core.QueryKind if kind is not core.QueryKind.THEOREM_PROOF])
def test_cancelled_registry_results_keep_each_query_kind_authority_boundary(clock, kind):
    declaration = replace(entry(), query_kinds=(kind.value,))
    selected = reg.LazyMatrixProofBackend(declaration,
        factory=lambda: pytest.fail('pre-cancelled registry constructed a provider'))
    req = replace(request(), query_kind=kind)
    signal = threading.Event(); signal.set()
    pair = reg.ProofBackendRegistry((selected,)).run(req, cancellation=signal)
    assert_stopped(pair, req, 'cancel')
    assert pair[1].authority.kind is kind.authority_kind
    assert pair[1].authority.scope_digest == req.digest
    assert pair[1].authority.evidence_digests == ()


@pytest.mark.parametrize('route', ROUTES)
@pytest.mark.parametrize('invalid', [True, False, 0, -1, 1.5, '10', 2**31, float('inf')])
def test_invalid_override_refused_before_any_callback(lane, route, invalid):
    selected = lane(route)
    with pytest.raises(ValueError):
        selected.target.run(request(), operation_timeout_ms=invalid)
    assert selected.calls == []


@pytest.mark.parametrize('route', ROUTES)
def test_wrong_request_type_preserves_existing_rejection(lane, route):
    selected = lane(route)
    with pytest.raises(TypeError, match='BackendRequest'):
        selected.target.run({'bounds': {'timeout_ms': 1}})
    assert selected.calls == []


PHASES = [(route, phase) for route in ROUTES
          for phase in (('probe', 'compile', 'run') if route == 'callable' else ('factory', 'probe', 'compile', 'run'))]


@pytest.mark.parametrize('route,phase', PHASES)
@pytest.mark.parametrize('stop', ['timeout', 'cancel'])
def test_stop_after_each_callback_prevents_later_work(lane, clock, route, phase, stop):
    signal = threading.Event()
    def action(current, req):
        if current == phase:
            if stop == 'timeout':
                clock[0] += 1.1
            else:
                signal.set()
    selected = lane(route, action=action)
    req = request()
    assert_stopped(selected.target.run(req, cancellation=signal), req, stop)
    assert selected.calls[-1] == phase
    assert all(observation[1] is not None for observation in selected.observations)


@pytest.mark.parametrize('route', ROUTES)
@pytest.mark.parametrize('override,advance,stopped', [(None, .101, True), (50, .06, True), (500, .101, True), (50, .04, False)])
def test_default_timeout_and_override_only_tighten_original_request(lane, clock, route, override, advance, stopped):
    req = request(100)
    before, digest = req.to_dict(), req.digest
    selected = lane(route, action=lambda phase, _: clock.__setitem__(0, clock[0] + advance) if phase == 'run' else None)
    pair = selected.target.run(req, operation_timeout_ms=override)
    if stopped:
        assert_stopped(pair, req, 'timeout')
    else:
        assert pair[1].status is core.ResultStatus.PROVED
    assert req.to_dict() == before and req.digest == digest
    assert all(observed is req for _, _, observed in selected.observations if observed is not None)
    assert pair[0].bounds == pair[1].bounds == req.bounds


@pytest.mark.parametrize('route', ROUTES)
def test_huge_declared_timeout_uses_supported_runtime_cap_without_wire_change(lane, clock, route):
    req = request(10**100)
    selected = lane(route)
    pair = selected.target.run(req)
    assert pair[1].status is core.ResultStatus.PROVED
    first_operation = selected.observations[0][1]
    assert first_operation.deadline == pytest.approx(100 + budget.MAX_OPERATION_TIMEOUT_MS / 1000)
    assert pair[0].bounds.timeout_ms == pair[1].bounds.timeout_ms == 10**100


@pytest.mark.parametrize('route', ROUTES)
def test_expired_ambient_scope_skips_setup_but_remains_latched(lane, clock, route):
    selected = lane(route); req = request()
    with pytest.raises(budget.ProofOperationTimeout):
        with budget.proof_operation_scope(timeout_ms=100):
            clock[0] += .101
            assert_stopped(selected.target.run(req), req, 'timeout')
            assert selected.calls == []
    assert budget.current_proof_operation() is None


@pytest.mark.parametrize('route', ROUTES)
def test_child_timeout_returns_terminal_and_revokes_parent(lane, clock, route):
    selected = lane(route, action=lambda phase, _: clock.__setitem__(0, clock[0] + .06) if phase == 'run' else None)
    req = request()
    with pytest.raises(budget.ProofOperationTimeout):
        with budget.proof_operation_scope(timeout_ms=1000) as parent:
            assert_stopped(selected.target.run(req, operation_timeout_ms=50), req, 'timeout')
            assert parent.is_set()


@pytest.mark.parametrize('route', ROUTES)
def test_observed_cancel_remains_sticky_after_callback_clears_signal(lane, route):
    signal = threading.Event()
    def action(phase, req):
        if phase == 'run':
            signal.set()
            assert budget.current_proof_operation().is_set()
            signal.clear()
    selected = lane(route, action=action); req = request()
    assert_stopped(selected.target.run(req, cancellation=signal), req, 'cancel')
    assert not signal.is_set()


@pytest.mark.parametrize('route', ROUTES)
@pytest.mark.parametrize('raise_after_stop', [False, True])
def test_ordinary_callback_handler_cannot_swallow_observed_stop(lane, route, raise_after_stop):
    signal = threading.Event()
    def action(phase, req):
        if phase == 'probe':
            signal.set()
            assert budget.current_proof_operation().is_set()
            signal.clear()
            if raise_after_stop:
                raise ValueError('ordinary probe error after observed cancellation')
    selected = lane(route, action=action); req = request()
    assert_stopped(selected.target.run(req, cancellation=signal), req, 'cancel')
    assert 'compile' not in selected.calls


@pytest.mark.parametrize('route', ['lazy', 'registry'])
@pytest.mark.parametrize('stop', ['timeout', 'cancel'])
def test_interrupted_factory_does_not_cache_failed_or_late_delegate(lane, clock, route, stop):
    signal = threading.Event(); first = [True]
    def action(phase, req):
        if phase == 'factory' and first[0]:
            first[0] = False
            if stop == 'timeout':
                clock[0] += 1.1
            else:
                signal.set()
    selected = lane(route, action=action); req = request()
    assert_stopped(selected.target.run(req, cancellation=signal), req, stop)
    assert selected.calls == ['factory']
    signal.clear()
    next_pair = selected.target.run(req)
    assert next_pair[1].status is core.ResultStatus.PROVED
    assert selected.calls.count('factory') == 2


def test_ordinary_factory_failure_keeps_existing_one_attempt_cache(lane):
    def fail(phase, req):
        if phase == 'factory':
            raise ImportError('fixture optional dependency absent')
    selected = lane('registry', action=fail)
    for _ in range(2):
        attempt, result = selected.target.run(request())
        assert attempt.status is core.AttemptStatus.UNAVAILABLE
        assert result.status is core.ResultStatus.UNKNOWN
    assert selected.calls == ['factory']


@pytest.mark.parametrize('route', ['lazy', 'registry'])
@pytest.mark.parametrize('phase', ['result', 'status', 'authority', 'serialize'])
@pytest.mark.parametrize('stop', ['timeout', 'cancel'])
def test_late_foreign_getter_or_serialization_cannot_publish(lane, clock, route, phase, stop):
    signal = threading.Event(); visited = []
    def touch(current):
        visited.append(current)
        if current == phase:
            if stop == 'timeout':
                clock[0] += 1.1
            else:
                signal.set()
    class Foreign:
        @property
        def result(self):
            touch('result'); return None
        @property
        def status(self):
            touch('status'); return 'proved'
        @property
        def authority(self):
            touch('authority'); return 'theorem'
        def to_dict(self):
            touch('serialize'); return {'claim': 'untrusted proof'}
    selected = lane(route, returned=Foreign()); req = request()
    assert_stopped(selected.target.run(req, cancellation=signal), req, stop)
    assert visited == ['result', 'status', 'authority', 'serialize'][:['result', 'status', 'authority', 'serialize'].index(phase) + 1]


@pytest.mark.parametrize('phase', ['foreign-normalization', 'pair-rebind', 'pair-validation', 'result-construction'])
def test_outer_gate_covers_final_normalization_validation_and_construction(lane, clock, monkeypatch, phase):
    selected = lane('registry', returned={'status': 'proved', 'authority': 'theorem'})
    if phase == 'foreign-normalization':
        original = selected.lazy._normalize_foreign_outcome
        def delayed(*args, **kwargs):
            value = original(*args, **kwargs); clock[0] += 1.1; return value
        monkeypatch.setattr(selected.lazy, '_normalize_foreign_outcome', delayed)
    elif phase == 'pair-rebind':
        selected = lane('registry')
        original = selected.lazy._rebind_protocol_pair
        def delayed(*args, **kwargs):
            value = original(*args, **kwargs); clock[0] += 1.1; return value
        monkeypatch.setattr(selected.lazy, '_rebind_protocol_pair', delayed)
    elif phase == 'pair-validation':
        # A result property is read by the registry after the delegate returns.
        selected = lane('registry')
        original_run = selected.lazy.run
        late = [False]
        original_digest = core.BackendAttempt.digest.fget
        def digest(attempt):
            value = original_digest(attempt)
            if late[0]:
                late[0] = False; clock[0] += 1.1
            return value
        def returned(req):
            value = original_run(req); late[0] = True; return value
        monkeypatch.setattr(selected.lazy, 'run', returned)
        monkeypatch.setattr(core.BackendAttempt, 'digest', property(digest))
    else:
        original = reg._make_outcome
        once = [True]
        def delayed(**kwargs):
            value = original(**kwargs)
            if once[0]:
                once[0] = False; clock[0] += 1.1
            return value
        monkeypatch.setattr(reg, '_make_outcome', delayed)
    req = request()
    assert_stopped(selected.target.run(req), req, 'timeout')


@pytest.mark.parametrize('route', ROUTES)
def test_success_and_runtime_controls_do_not_change_wire_or_request_identity(lane, route):
    selected = lane(route); req = request()
    first = selected.target.run(req)
    second = selected.target.run(req, operation_timeout_ms=900, cancellation=threading.Event())
    assert [x.to_dict() for x in first] == [x.to_dict() for x in second]
    assert first[1].status is core.ResultStatus.PROVED
    assert all(observed is req for _, _, observed in selected.observations if observed is not None)
    assert 'operation_timeout_ms' not in str(req.to_dict())
    assert budget.current_proof_operation() is None


def test_injected_legacy_run_signature_and_internal_typeerror_are_never_retried(lane):
    observed = []
    def legacy(req):
        observed.append(req)
        raise TypeError('internal legacy callback error')
    selected = lane('registry', returned=legacy); req = request()
    attempt, result = selected.target.run(req, operation_timeout_ms=500)
    assert observed == [req]
    assert attempt.status is core.AttemptStatus.FAILED and result.status is core.ResultStatus.ERROR


@pytest.mark.parametrize('route', ROUTES)
def test_baseexceptions_are_never_normalized(lane, route):
    def action(phase, req):
        if phase == 'run':
            raise KeyboardInterrupt('fixture process-control signal')
    selected = lane(route, action=action)
    with pytest.raises(KeyboardInterrupt):
        selected.target.run(request())
    assert budget.current_proof_operation() is None


def test_smt_query_and_version_inherit_time_spent_in_registry_setup(clock, tmp_path):
    calls, workspaces = [], []
    def execute(invocation, signal):
        phase = 'version' if '-version' in invocation.argv else 'query'
        calls.append((phase, invocation.limits, signal))
        workspaces.append(invocation.cwd)
        clock[0] += .2
        return process.RawProcessResult(returncode=0, stdout='Z3 version 4.13.0\n' if phase == 'version' else 'unsat\n')
    runner = process.BoundedToolRunner(executor=execute, workspace_root=tmp_path)
    def factory():
        clock[0] += .2
        return admitted.Z3Backend(executable=sys.executable, tool_runner=runner,
            availability_probe=lambda: True)
    selected = reg.LazyMatrixProofBackend(entry(), factory=factory)
    req = request()
    attempt, result = reg.ProofBackendRegistry((selected,)).run(req)
    assert result.status is core.ResultStatus.PROVED
    assert [row[0] for row in calls] == ['query', 'version']
    for (_, limits, signal), remaining in zip(calls, (.8, .6)):
        assert 0 < limits.timeout_seconds <= remaining + .00001
        assert limits.cpu_seconds == pytest.approx(remaining)
        assert signal is not None
    assert attempt.bounds == result.bounds == req.bounds
    assert all(not directory.exists() for directory in workspaces)


def test_late_smt_query_withholds_unsat_and_skips_version(clock, tmp_path):
    calls = []
    def execute(invocation, signal):
        calls.append(invocation.argv)
        clock[0] += 1.1
        return process.RawProcessResult(returncode=0, stdout='unsat\n')
    runner = process.BoundedToolRunner(executor=execute, workspace_root=tmp_path)
    backend = admitted.Z3Backend(executable=sys.executable, tool_runner=runner, availability_probe=lambda: True)
    selected = reg.LazyMatrixProofBackend(entry(), factory=lambda: backend)
    req = request()
    assert_stopped(reg.ProofBackendRegistry((selected,)).run(req), req, 'timeout')
    assert len(calls) == 1


def test_discovery_remains_inert_even_with_expired_ambient_scope(lane, clock):
    selected = lane('registry'); req = request()
    with pytest.raises(budget.ProofOperationTimeout):
        with budget.proof_operation_scope(timeout_ms=1):
            clock[0] += 1
            assert selected.owner.supporting(req) == ('fixture',)
            assert selected.owner.capabilities_for('fixture-alias') == selected.lazy.capabilities
            assert selected.lazy.supports(req)
            assert selected.calls == []


def test_facade_native_runtime_lane_also_withholds_late_results(clock, monkeypatch):
    declaration = next(item for item in reg.EXECUTABLE_PROVIDER_MATRIX if item.factory_key == 'runtime_mtl')
    selected = reg.LazyMatrixProofBackend(declaration,
        factory=lambda: pytest.fail('runtime lane constructed an external delegate'))
    req = replace(request(), logic_family=declaration.logic_families[0], query_kind=core.QueryKind.RUNTIME_MONITOR)
    calls = []
    def monitor(observed):
        calls.append(observed)
        result = reg._make_outcome(backend_id=selected.backend_id, backend_version=selected.backend_version,
            capabilities=selected.capabilities, request=observed,
            attempt_status=core.AttemptStatus.SUCCEEDED, result_status=core.ResultStatus.UNKNOWN,
            classification='fixture-monitor', payload={'observed': True})
        clock[0] += 1.1
        return result
    monkeypatch.setattr(selected, '_run_runtime_mtl', monitor)
    assert_stopped(reg.ProofBackendRegistry((selected,)).run(req), req, 'timeout')
    assert calls == [req]


def test_reused_backend_has_fresh_context_after_observed_cancellation(lane):
    signal = threading.Event(); first = [True]
    def action(phase, req):
        if phase == 'run' and first[0]:
            first[0] = False; signal.set()
    selected = lane('registry', action=action); req = request()
    assert_stopped(selected.target.run(req, cancellation=signal), req, 'cancel')
    signal.clear()
    assert selected.target.run(req, cancellation=signal)[1].status is core.ResultStatus.PROVED
    assert selected.calls.count('factory') == 1


def test_shared_preloaded_backend_keeps_concurrent_stop_contexts_separate(lane):
    barrier = threading.Barrier(2)
    active = [False]
    signal = threading.Event()
    seen, results, errors = {}, {}, []
    def action(phase, req):
        if phase == 'run' and active[0]:
            name = threading.current_thread().name
            seen[name] = budget.current_proof_operation()
            barrier.wait(timeout=2)
            if name == 'cancelled-registry-call':
                signal.set()
                assert seen[name].is_set()
                signal.clear()
    selected = lane('registry', action=action)
    assert selected.target.run(request())[1].status is core.ResultStatus.PROVED
    active[0] = True
    def run(name):
        try:
            req = request(tag=name)
            results[name] = (req, selected.target.run(req,
                cancellation=signal if name == 'cancelled-registry-call' else None))
            assert budget.current_proof_operation() is None
        except BaseException as error:
            errors.append(error)
    threads = [threading.Thread(name=name, target=run, args=(name,))
               for name in ('cancelled-registry-call', 'healthy-registry-call')]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)
    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert seen['cancelled-registry-call'] is not seen['healthy-registry-call']
    req, pair = results['cancelled-registry-call']; assert_stopped(pair, req, 'cancel')
    assert results['healthy-registry-call'][1][1].status is core.ResultStatus.PROVED
    assert selected.calls.count('factory') == 1


def test_waiting_cold_initializer_can_cancel_without_duplicate_factory(lane):
    entered, release, waited = threading.Event(), threading.Event(), threading.Event()
    cancelled = threading.Event()
    def action(phase, req):
        if phase == 'factory':
            entered.set()
            assert release.wait(timeout=3), 'test failed to release held factory'
    selected = lane('registry', action=action)
    underlying_lock = selected.lazy._delegate_lock
    class ObservedLock:
        def acquire(self, *args, **kwargs):
            acquired = underlying_lock.acquire(*args, **kwargs)
            if not acquired:
                waited.set()
            return acquired
        def release(self):
            return underlying_lock.release()
    selected.lazy._delegate_lock = ObservedLock()
    results, errors = {}, []
    def run(name, signal=None):
        try:
            req = request(tag=name)
            results[name] = (req, selected.target.run(req, cancellation=signal))
        except BaseException as error:
            errors.append(error)
    first = threading.Thread(target=run, args=('initializer',))
    waiter = threading.Thread(target=run, args=('waiter', cancelled))
    first.start()
    try:
        assert entered.wait(timeout=2)
        waiter.start()
        assert waited.wait(timeout=2), 'contender did not reach a failed bounded lock acquisition'
        cancelled.set()
        waiter.join(timeout=2)
        assert not waiter.is_alive(), 'initializer lock ignored waiting operation cancellation'
        assert 'waiter' in results
        req, pair = results['waiter']; assert_stopped(pair, req, 'cancel')
        assert selected.calls == ['factory']
    finally:
        release.set()
        first.join(timeout=3)
        if waiter.ident is not None:
            waiter.join(timeout=3)
    assert not first.is_alive() and not waiter.is_alive()
    assert errors == []
    assert results['initializer'][1][1].status is core.ResultStatus.PROVED
    assert selected.calls.count('factory') == 1
    assert selected.target.run(request(tag='later'))[1].status is core.ResultStatus.PROVED


def test_native_signal_observation_latches_cancel_after_signal_clears(clock, tmp_path):
    signal = threading.Event(); calls = []
    def execute(invocation, cancellation):
        calls.append(invocation.argv)
        signal.set()
        assert cancellation.is_set()
        signal.clear()
        return process.RawProcessResult(returncode=0, stdout='unsat\n')
    runner = process.BoundedToolRunner(executor=execute, workspace_root=tmp_path)
    backend = admitted.Z3Backend(executable=sys.executable, tool_runner=runner, availability_probe=lambda: True)
    selected = reg.LazyMatrixProofBackend(entry(), factory=lambda: backend)
    req = request()
    assert_stopped(reg.ProofBackendRegistry((selected,)).run(req, cancellation=signal), req, 'cancel')
    assert len(calls) == 1 and not signal.is_set()
