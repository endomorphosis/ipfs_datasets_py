"""Whole Hyper operations with synthetic time and no native execution.

Opaque Python callbacks remain cooperative. These tests require stopping at
boundaries and withholding late evidence, rather than claiming preemption.
"""
from dataclasses import replace
import subprocess
import threading
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process, resource_admission as admission
from ipfs_datasets_py.logic.backends.hyperproperties import adapters as hyper, execution_v2 as v2
from ipfs_datasets_py.logic.backends.results import ResultStatus
from ipfs_datasets_py.logic.backends.smt import operation_budget as budget
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from tests.unit.logic.backends.test_hyper_resource_admission import (
    AIGER, BACKENDS, SUCCESS, TRACE, VIOLATION, document,
    host as private_admission, until,
)


MIB = 1024**2
ENGINES = tuple(BACKENDS)


def forbidden(*args, **kwargs):
    pytest.fail('Hyper operation fixture reached native execution or the shared pool')


@pytest.fixture(autouse=True)
def no_native_or_shared_pool(monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', forbidden)
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', forbidden)


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    fake = SimpleNamespace(monotonic=lambda: now[0])
    monkeypatch.setattr(budget, 'time', fake)
    monkeypatch.setattr(admission, 'time', fake)
    return now


def bounds(timeout_ms=1000):
    return ExecutionBounds(timeout_ms=timeout_ms, max_memory_bytes=128*MIB,
                           max_output_bytes=16384, max_steps=100)


def request(engine='hyperltl', *, timeout_ms=1000, **kwargs):
    return v2.HyperExecutionRequestV2(request_id='request:hyper:operation', provider=engine,
        document=document(), system_model=AIGER if engine == 'mchyper' else None,
        bounds=bounds(timeout_ms), **kwargs)


@pytest.fixture
def fixture_engine():
    def build(*, action=None, violated=False, **controls):
        visits, native, invocations, workspaces = [], [], [], []
        def visit(provider, phase):
            visits.append((provider, phase))
            if action is not None:
                action(provider, phase)
        def backend(provider):
            base = BACKENDS[provider]
            class Observed(base):
                def is_available(self):
                    visit(provider, 'available')
                    return True
                def supports_prefix(self, doc):
                    value = super().supports_prefix(doc)
                    visit(provider, 'support')
                    return value
                def translate(self, doc):
                    value = super().translate(doc)
                    visit(provider, 'translate')
                    return value
                def probe(self):
                    value = super().probe()
                    visit(provider, 'probe')
                    return value
                def _classify(self, *args, **kwargs):
                    value = super()._classify(*args, **kwargs)
                    visit(provider, 'classify')
                    return value
            def execute(invocation, signal):
                phase = 'version' if '--version' in invocation.argv else 'native'
                record = (provider, invocation, signal, budget.current_proof_operation())
                invocations.append(record)
                workspaces.append(invocation.cwd)
                if phase == 'native':
                    native.append(record)
                visit(provider, phase)
                output = ('fixture-engine 1.0\n' if phase == 'version' else
                          VIOLATION[provider]+TRACE if violated else SUCCESS[provider])
                return process.RawProcessResult(returncode=0, stdout=output, elapsed_seconds=0)
            return Observed(executable='fixture-'+provider, runner=process.BoundedToolRunner(executor=execute))
        backends = {name: backend(name) for name in ENGINES}
        engine = v2.HyperExecutionEngineV2(**backends, **controls)
        return SimpleNamespace(engine=engine, backends=backends, visits=visits, native=native,
            invocations=invocations, workspaces=workspaces)
    return build


@pytest.mark.parametrize('value', [True, 0, -1, 1.5, '100', budget.MAX_OPERATION_TIMEOUT_MS+1])
@pytest.mark.parametrize('route', ['constructor', 'execute', 'split', 'helper'])
def test_invalid_controls_fail_before_callbacks(fixture_engine, value, route):
    fixture = fixture_engine()
    with pytest.raises(ValueError):
        if route == 'constructor':
            v2.HyperExecutionEngineV2(**fixture.backends, operation_timeout_ms=value)
        elif route == 'execute':
            fixture.engine.execute(request(), operation_timeout_ms=value)
        elif route == 'split':
            fixture.engine.execute_split_capabilities({}, operation_timeout_ms=value)
        else:
            v2.execute_hyperltl({}, request_id='invalid-control', engine=fixture.engine, operation_timeout_ms=value)
    assert not fixture.visits and not fixture.native


def test_constructor_is_inert_and_preserves_falsey_injected_backend():
    engine = v2.HyperExecutionEngineV2()
    for name in ENGINES:
        assert type(engine.backend(name)._runner) is admission.ResourceAdmittedToolRunner
    class Falsey(hyper.HyperLTLBackend):
        def __bool__(self):
            return False
    owned = Falsey(runner=process.BoundedToolRunner(executor=forbidden), which=forbidden)
    assert v2.HyperExecutionEngineV2(hyperltl=owned).backend('hyperltl') is owned


@pytest.mark.parametrize('route', ['execute', 'mapping', 'split', *ENGINES])
def test_precancel_stops_before_document_normalization_or_provider_lookup(fixture_engine, monkeypatch, route):
    fixture = fixture_engine(); req = request(); event = threading.Event(); event.set()
    monkeypatch.setattr(v2, '_document_from_value', forbidden)
    with pytest.raises(budget.ProofOperationCancelled):
        if route == 'execute':
            fixture.engine.execute(req, cancellation=event)
        elif route == 'mapping':
            fixture.engine.execute({'request_id': 'cancelled', 'provider': 'hyperltl', 'document': {}}, cancellation=event)
        elif route == 'split':
            fixture.engine.execute_split_capabilities({}, cancellation=event)
        else:
            getattr(v2, 'execute_'+route)({}, request_id='cancelled', engine=fixture.engine, cancellation=event)
    assert not fixture.visits and not fixture.native and budget.current_proof_operation() is None


@pytest.mark.parametrize('phase', ['available', 'support', 'translate', 'probe', 'native', 'classify', 'version'])
def test_default_request_budget_stops_after_callback_before_later_phases(fixture_engine, clock, phase):
    def delay(provider, observed):
        if observed == phase:
            clock[0] += 1.1
    fixture = fixture_engine(action=delay)
    with pytest.raises(budget.ProofOperationTimeout):
        fixture.engine.execute(request())
    assert len(fixture.native) == (1 if phase in {'native', 'classify', 'version'} else 0)
    assert fixture.visits[-1] == ('hyperltl', phase)
    assert all(not path.exists() for path in fixture.workspaces)


@pytest.mark.parametrize('route', ['mapping', 'helper', 'split'])
def test_document_normalization_consumes_same_budget_before_capability(fixture_engine, clock, monkeypatch, route):
    fixture = fixture_engine(); wire = document().to_dict(); original = v2._document_from_value
    def delayed(value):
        parsed = original(value)
        clock[0] += 1.1
        return parsed
    monkeypatch.setattr(v2, '_document_from_value', delayed)
    with pytest.raises(budget.ProofOperationTimeout):
        if route == 'mapping':
            fixture.engine.execute({'request_id': 'normalization', 'provider': 'hyperltl',
                'document': wire, 'bounds': bounds()})
        elif route == 'helper':
            v2.execute_hyperltl(wire, request_id='normalization', engine=fixture.engine, bounds=bounds())
        else:
            fixture.engine.execute_split_capabilities(wire, bounds=bounds())
    assert not fixture.visits and not fixture.native


def test_request_digest_work_cannot_reset_operation_before_capability(fixture_engine, clock, monkeypatch):
    fixture = fixture_engine(); req = request(); original = v2._digest_of
    def delayed(value):
        digest = original(value)
        clock[0] += 1.1
        return digest
    monkeypatch.setattr(v2, '_digest_of', delayed)
    with pytest.raises(budget.ProofOperationTimeout):
        fixture.engine.execute(req)
    assert not fixture.visits and not fixture.native


@pytest.mark.parametrize('phase', ['capability', 'witness', 'evidence', 'result'])
@pytest.mark.parametrize('violated', [False, True])
@pytest.mark.parametrize('stop', ['timeout', 'cancel'])
def test_late_binding_or_publication_withholds_holds_and_violation(fixture_engine, clock, monkeypatch, phase, violated, stop):
    fixture = fixture_engine(violated=violated); event = threading.Event()
    def trip():
        if stop == 'cancel':
            event.set()
        else:
            clock[0] += 1.1
    if phase == 'capability':
        original = fixture.engine.capability_receipt
        def delayed(*args, **kwargs):
            result = original(*args, **kwargs); trip(); return result
        monkeypatch.setattr(fixture.engine, 'capability_receipt', delayed)
    elif phase == 'witness':
        original = v2.HyperWitnessBindingV2.from_outcome.__func__
        def delayed(cls, *args, **kwargs):
            result = original(cls, *args, **kwargs); trip(); return result
        monkeypatch.setattr(v2.HyperWitnessBindingV2, 'from_outcome', classmethod(delayed))
    else:
        selected = v2.HyperProviderEvidenceV2 if phase == 'evidence' else v2.HyperExecutionResultV2
        original = selected.__post_init__
        def delayed(self):
            original(self); trip()
        monkeypatch.setattr(selected, '__post_init__', delayed)
    expected = budget.ProofOperationCancelled if stop == 'cancel' else budget.ProofOperationTimeout
    with pytest.raises(expected):
        fixture.engine.execute(request(), cancellation=event)
    assert len(fixture.native) == (0 if phase == 'capability' else 1)
    assert all(not path.exists() for path in fixture.workspaces)


@pytest.mark.parametrize('phase', ['parse_hyper_counterexample', 'replay_hyper_counterexample'])
def test_adapter_counterexample_callback_cannot_publish_after_observed_then_cleared_cancel(
        fixture_engine, monkeypatch, phase):
    fixture = fixture_engine(violated=True); event = threading.Event(); original = getattr(hyper, phase)
    def cancelled(*args, **kwargs):
        value = original(*args, **kwargs)
        event.set(); assert budget.current_proof_operation().is_set(); event.clear()
        return value
    monkeypatch.setattr(hyper, phase, cancelled)
    if phase == 'parse_hyper_counterexample':
        monkeypatch.setattr(hyper, 'replay_hyper_counterexample', forbidden)
    with pytest.raises(budget.ProofOperationCancelled):
        fixture.engine.execute(request(), cancellation=event)
    assert len(fixture.native) == 1 and not event.is_set()
    assert all(not path.exists() for path in fixture.workspaces)


@pytest.mark.parametrize('provider', ENGINES)
def test_canonical_plain_runner_receives_current_latched_operation_signal(fixture_engine, provider):
    event = threading.Event(); seen = []
    def cancel(selected, phase):
        if phase == 'native':
            operation = budget.current_proof_operation()
            event.set(); assert operation.is_set(); event.clear(); seen.append(operation)
    fixture = fixture_engine(action=cancel)
    with pytest.raises(budget.ProofOperationCancelled):
        fixture.engine.execute(request(provider), cancellation=event)
    assert len(fixture.native) == 1 and fixture.native[0][2] is seen[0]
    assert fixture.native[0][3] is seen[0] and not event.is_set()
    assert budget.current_proof_operation() is None


def test_native_and_injected_version_share_one_deadline_without_changing_plain_profile(fixture_engine, clock):
    def consume(provider, phase):
        if phase == 'native':
            clock[0] += .3
    fixture = fixture_engine(action=consume)
    result = fixture.engine.execute(request())
    assert result.hyperproperty_established and len(fixture.invocations) == 2
    model, version = [row[1] for row in fixture.invocations]
    assert model.limits.timeout_seconds == pytest.approx(1.)
    assert version.limits.timeout_seconds == pytest.approx(.7)
    assert model.limits.memory_bytes is model.limits.resident_memory_bytes is model.limits.cpu_seconds is None
    assert version.limits.memory_bytes is version.limits.resident_memory_bytes is version.limits.cpu_seconds is None
    assert result.request.bounds.timeout_ms == result.backend_result.bounds.timeout_ms == 1000


def test_version_exception_after_latched_stop_cannot_be_swallowed(fixture_engine):
    event = threading.Event()
    def stop(provider, phase):
        if phase == 'version':
            event.set(); assert budget.current_proof_operation().is_set(); event.clear()
            raise OSError('version callback failed after observing cancellation')
    fixture = fixture_engine(action=stop)
    with pytest.raises(budget.ProofOperationCancelled):
        fixture.engine.execute(request(), cancellation=event)
    assert len(fixture.native) == 1 and len(fixture.invocations) == 2
    assert all(not path.exists() for path in fixture.workspaces)


def test_late_version_override_is_checked_before_counterexample_callbacks(fixture_engine, clock, monkeypatch):
    fixture = fixture_engine(violated=True)
    def late(*args, **kwargs):
        clock[0] += 1.1
        return 'late metadata'
    monkeypatch.setattr(fixture.backends['hyperltl'], '_tool_version', late)
    monkeypatch.setattr(hyper, 'parse_hyper_counterexample', forbidden)
    monkeypatch.setattr(hyper, 'replay_hyper_counterexample', forbidden)
    with pytest.raises(budget.ProofOperationTimeout):
        fixture.engine.execute(request())
    assert len(fixture.native) == len(fixture.invocations) == 1
    assert all(not path.exists() for path in fixture.workspaces)


def test_nested_timeout_remains_latched_in_parent_after_inner_exception(fixture_engine, clock):
    fixture = fixture_engine(action=lambda _, phase:
        clock.__setitem__(0, clock[0]+.11) if phase == 'native' else None)
    with pytest.raises(budget.ProofOperationTimeout):
        with budget.proof_operation_scope(timeout_ms=100) as parent:
            with pytest.raises(budget.ProofOperationTimeout):
                fixture.engine.execute(request(timeout_ms=2000), operation_timeout_ms=5000)
            assert parent.is_set()
    assert len(fixture.native) == 1 and budget.current_proof_operation() is None


@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
def test_split_never_returns_partial_result_or_starts_next_peer_after_stop(fixture_engine, clock, monkeypatch, stop):
    fixture = fixture_engine(); event = threading.Event(); original = fixture.engine._from_outcome
    def late(*args, **kwargs):
        result = original(*args, **kwargs)
        if stop == 'cancel':
            event.set()
        else:
            clock[0] += 1.1
        return result
    monkeypatch.setattr(fixture.engine, '_from_outcome', late)
    expected = budget.ProofOperationCancelled if stop == 'cancel' else budget.ProofOperationTimeout
    with pytest.raises(expected):
        fixture.engine.execute_split_capabilities(document(), system_models={'mchyper': AIGER},
            bounds=bounds(), cancellation=event)
    assert [row[0] for row in fixture.native] == ['hyperltl']
    assert all(provider == 'hyperltl' for provider, _ in fixture.visits)


def test_split_shares_remaining_budget_across_three_model_and_version_pairs(fixture_engine, clock):
    remaining = []
    def consume(provider, phase):
        if phase == 'native':
            remaining.append(budget.current_proof_operation().deadline-clock[0]); clock[0] += .2
    fixture = fixture_engine(action=consume); limits = bounds()
    result = fixture.engine.execute_split_capabilities(document(), system_models={'mchyper': AIGER}, bounds=limits)
    assert list(result) == list(v2.HyperProviderKind)
    assert remaining == pytest.approx([1., .8, .6])
    assert [row[1].limits.timeout_seconds for row in fixture.invocations] == pytest.approx([1., .8, .8, .6, .6, .4])
    assert all(value.request.bounds is limits and value.backend_result.bounds == limits for value in result.values())


def test_constructor_call_and_request_caps_tighten_without_mutating_request(fixture_engine, clock):
    observed = []
    fixture = fixture_engine(operation_timeout_ms=100, action=lambda _, phase:
        observed.append(budget.current_proof_operation().deadline-clock[0]) if phase == 'native' else None)
    req = request(timeout_ms=500); before = req.to_dict()
    fixture.engine.execute(req)
    fixture.engine.execute(req, operation_timeout_ms=400)
    fixture.engine.execute(req, operation_timeout_ms=900)
    v2.execute_hyperltl(document(), request_id=req.request_id, bounds=req.bounds,
        engine=fixture.engine, operation_timeout_ms=900)
    assert observed == pytest.approx([.1, .4, .5, .5])
    assert req.to_dict() == before and 'operation_timeout_ms' not in before and 'cancellation' not in before


def test_default_one_second_and_huge_request_cap_preserve_declared_bounds(fixture_engine, clock, monkeypatch):
    fixture = fixture_engine(); observed = []
    def available():
        observed.append(budget.current_proof_operation().deadline-clock[0]); return False
    selected = fixture.backends['hyperltl']
    monkeypatch.setattr(selected, 'is_available', available)
    monkeypatch.setattr(selected, 'probe', lambda: process.ToolProbe(runtime=process.ToolRuntime.NATIVE,
        requested_executable='fixture', available=False, executable_path='', reason='missing fixture'))
    default = v2.HyperExecutionRequestV2(request_id='default', provider='hyperltl', document=document())
    huge = replace(default, bounds=bounds(budget.MAX_OPERATION_TIMEOUT_MS+12345))
    fixture.engine.execute(default); fixture.engine.execute(huge)
    assert observed == pytest.approx([1., budget.MAX_OPERATION_TIMEOUT_MS/1000])
    assert huge.bounds.timeout_ms == budget.MAX_OPERATION_TIMEOUT_MS+12345 and not fixture.native


@pytest.mark.parametrize('mode', ['mock', 'fallback', 'capability_probe'])
def test_nonexecuting_modes_still_obey_final_gate(fixture_engine, clock, monkeypatch, mode):
    fixture = fixture_engine(); req = request(mode=mode)
    selected = '_capability_only' if mode == 'capability_probe' else '_rejected'
    original = getattr(fixture.engine, selected)
    def late(*args, **kwargs):
        result = original(*args, **kwargs); clock[0] += 1.1; return result
    monkeypatch.setattr(fixture.engine, selected, late)
    with pytest.raises(budget.ProofOperationTimeout):
        fixture.engine.execute(req)
    assert not fixture.native


@pytest.mark.parametrize('failure', [TypeError, RuntimeError, KeyboardInterrupt])
def test_legacy_check_callback_keeps_old_keywords_and_is_never_retried(failure):
    seen = []
    class Legacy(hyper.HyperLTLBackend):
        def check(self, doc, *, bounds, traces, system_model, allow_fallback):
            seen.append((doc, bounds, budget.current_proof_operation()))
            raise failure('legacy callback failure')
    owned = Legacy(executable='fixture', runner=process.BoundedToolRunner(executor=forbidden))
    engine = v2.HyperExecutionEngineV2(hyperltl=owned); req = request()
    if failure is TypeError:
        result = engine.execute(req)
        assert result.evidence.result_status is ResultStatus.ERROR and not result.hyperproperty_established
    else:
        with pytest.raises(failure, match='legacy callback failure'):
            engine.execute(req)
    assert len(seen) == 1 and seen[0][1] is req.bounds and seen[0][2] is not None
    assert engine.backend('hyperltl') is owned and budget.current_proof_operation() is None


def test_legacy_check_exception_cannot_hide_cancellation_even_after_event_clear():
    event = threading.Event(); calls = []
    class Legacy(hyper.HyperLTLBackend):
        def check(self, doc, *, bounds, traces, system_model, allow_fallback):
            calls.append(True); event.set(); assert budget.current_proof_operation().is_set(); event.clear()
            raise TypeError('failure after observed stop')
    engine = v2.HyperExecutionEngineV2(hyperltl=Legacy(executable='fixture',
        runner=process.BoundedToolRunner(executor=forbidden)))
    with pytest.raises(budget.ProofOperationCancelled):
        engine.execute(request(), cancellation=event)
    assert calls == [True] and not event.is_set()


@pytest.mark.parametrize('route', ['helper', 'split'])
def test_legacy_execute_override_is_called_once_and_late_result_not_published(fixture_engine, clock, route):
    fixture = fixture_engine(); baseline = fixture.engine.execute(request()); calls = []
    class Legacy(v2.HyperExecutionEngineV2):
        def execute(self, req):
            calls.append((req, budget.current_proof_operation()))
            clock[0] += 1.1
            return baseline
    selected = Legacy(**fixture.backends)
    with pytest.raises(budget.ProofOperationTimeout):
        if route == 'helper':
            v2.execute_hyperltl(document(), request_id='legacy', engine=selected, bounds=bounds())
        else:
            selected.execute_split_capabilities(document(), bounds=bounds())
    assert len(calls) == 1 and calls[0][1] is not None


def test_falsey_opaque_helper_engine_receives_old_signature_once():
    calls = []
    class Owned:
        def __bool__(self):
            return False
        def execute(self, req):
            calls.append((self, req, budget.current_proof_operation()))
            raise TypeError('opaque callback error')
    selected = Owned()
    with pytest.raises(TypeError, match='opaque callback error'):
        v2.execute_hyperltl(document(), request_id='opaque', engine=selected, cancellation=threading.Event())
    assert len(calls) == 1 and calls[0][0] is selected and calls[0][2] is not None


def test_constructor_call_signals_combine_and_shared_engine_recovers(fixture_engine):
    constructor, call = threading.Event(), threading.Event()
    fixture = fixture_engine(cancellation=constructor)
    for signal in (constructor, call):
        signal.set()
        with pytest.raises(budget.ProofOperationCancelled):
            fixture.engine.execute(request(), cancellation=call)
        signal.clear()
    assert fixture.engine.execute(request(), cancellation=call).hyperproperty_established
    assert len(fixture.native) == 1


def test_shared_engine_contexts_do_not_mix_concurrent_signals(fixture_engine):
    barrier = threading.Barrier(2); stop = threading.Event(); contexts = {}; outcomes = {}
    def synchronize(provider, phase):
        if phase == 'native':
            name = threading.current_thread().name
            contexts[name] = budget.current_proof_operation(); barrier.wait(3)
            if name == 'cancelled-call':
                stop.set(); assert contexts[name].is_set()
    fixture = fixture_engine(action=synchronize)
    def execute(name):
        try:
            outcomes[name] = fixture.engine.execute(request(timeout_ms=5000),
                cancellation=stop if name == 'cancelled-call' else None)
        except BaseException as error:
            outcomes[name] = error
    workers = [threading.Thread(target=execute, args=(name,), name=name) for name in ('cancelled-call', 'healthy-call')]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(4)
    assert all(not worker.is_alive() for worker in workers)
    assert isinstance(outcomes['cancelled-call'], budget.ProofOperationCancelled)
    assert outcomes['healthy-call'].hyperproperty_established
    assert contexts['cancelled-call'] is not contexts['healthy-call'] and budget.current_proof_operation() is None


@pytest.mark.parametrize('provider', ENGINES)
@pytest.mark.parametrize('violated', [False, True])
def test_healthy_controls_preserve_request_bindings_and_authority(fixture_engine, provider, violated):
    fixture = fixture_engine(violated=violated); req = request(provider); before = req.to_dict()
    baseline = fixture.engine.execute(req)
    controlled = fixture.engine.execute(req, operation_timeout_ms=500, cancellation=threading.Event())
    assert controlled.to_dict() == baseline.to_dict()
    assert req.to_dict() == before and controlled.request is req
    assert controlled.backend_result.bounds == baseline.backend_result.bounds == req.bounds
    assert controlled.evidence.request_digest == baseline.evidence.request_digest
    assert controlled.evidence.formula.to_dict() == baseline.evidence.formula.to_dict()
    assert controlled.evidence.system.to_dict() == baseline.evidence.system.to_dict()
    assert controlled.evidence.bounds.to_dict() == baseline.evidence.bounds.to_dict()
    assert controlled.evidence.witness.to_dict() == baseline.evidence.witness.to_dict()
    assert controlled.evidence.result_status is (ResultStatus.VIOLATED if violated else ResultStatus.SATISFIED)
    assert controlled.hyperproperty_established and not controlled.is_theorem_authority


def test_mapping_bounds_stay_rejected_instead_of_coercing_request_schema(fixture_engine):
    fixture = fixture_engine()
    with pytest.raises(v2.HyperExecutionError):
        fixture.engine.execute({'request_id': 'bad-bounds', 'provider': 'hyperltl',
            'document': document().to_dict(), 'bounds': bounds().to_dict()})
    assert not fixture.visits


def test_raw_adapter_without_ambient_scope_keeps_legacy_plain_limits_and_signal(fixture_engine):
    fixture = fixture_engine(); token = threading.Event()
    result = fixture.backends['hyperltl'].check(document(), bounds=bounds(), cancellation=token)
    assert result.result.status is ResultStatus.SATISFIED
    assert [row[1].limits.timeout_seconds for row in fixture.invocations] == [1., 3.]
    assert all(row[2] is token and row[3] is None for row in fixture.invocations)


def test_default_admitted_transport_gets_remaining_deadline_after_translation(private_admission, clock, monkeypatch):
    engine = v2.HyperExecutionEngineV2(); backend = engine.backend('hyperltl'); original = backend.translate
    def delayed(doc):
        result = original(doc); clock[0] += .25; return result
    monkeypatch.setattr(backend, 'translate', delayed)
    req = request(); before = req.to_dict()
    result = engine.execute(req)
    invocation, signal, snapshot, operation = private_admission.calls[0]
    assert 0 < invocation.limits.timeout_seconds <= .75
    assert invocation.limits.cpu_seconds == pytest.approx(.75)
    assert invocation.limits.resident_memory_bytes == req.bounds.max_memory_bytes
    assert snapshot['allocated'] == {'cpu_slots': 2, 'memory_mb': 128}
    assert signal is not None and operation is not None
    assert result.hyperproperty_established and result.backend_result.bounds == req.bounds
    assert req.to_dict() == before and len(private_admission.calls) == 1


@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
def test_external_pressure_queue_stops_preserves_foreign_lease_and_allows_reuse(private_admission, clock, stop):
    owner = private_admission.owner
    foreign = owner.acquire('validation', cpu_slots=1, memory_mb=32, child_process_slots=1, timeout=0)
    private_admission.current[0] = replace(private_admission.healthy, available_memory_mb=32)
    engine = v2.HyperExecutionEngineV2(); event = threading.Event(); observed = []
    def execute():
        try:
            observed.append(engine.execute(request(), operation_timeout_ms=500, cancellation=event))
        except BaseException as error:
            observed.append(error)
    worker = threading.Thread(target=execute); worker.start()
    try:
        until(lambda: owner.snapshot()['proof_backoff'].get('reason') == 'proof_memory_headroom')
        assert private_admission.calls == private_admission.prepared == []
        if stop == 'cancel':
            event.set()
        else:
            clock[0] += .6
        worker.join(3)
        expected = budget.ProofOperationCancelled if stop == 'cancel' else budget.ProofOperationTimeout
        assert not worker.is_alive() and len(observed) == 1 and isinstance(observed[0], expected)
        assert owner.snapshot()['active_lease_count'] == 1 and owner.snapshot()['waiting_request_count'] == 0
        assert not foreign.released and not foreign.cancelled
    finally:
        event.set(); private_admission.current[0] = private_admission.healthy; worker.join(3); foreign.release()
    assert engine.execute(request()).hyperproperty_established
    assert len(private_admission.calls) == 1
