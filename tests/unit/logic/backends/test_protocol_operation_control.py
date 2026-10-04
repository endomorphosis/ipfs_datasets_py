"""Whole protocol operations stop before publishing late protocol evidence.

Synthetic outputs below exercise the existing parser contracts, not native
protocol semantics. Actual subprocesses and the shared scheduler are denied.
"""
from dataclasses import replace
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process, resource_admission as admission
from ipfs_datasets_py.logic.backends.protocol import execution_v2 as v2, proverif as pv, tamarin as tm
from ipfs_datasets_py.logic.backends.results import ResultStatus
from ipfs_datasets_py.logic.backends.smt import operation_budget as budget
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from tests.integration.logic_providers.test_protocol_execution_v2 import (
    _protocol, _auto_proverif_secure, _auto_tamarin_secure,
)


MIB = 1024**2
PV_SOURCE = '(* claim:secrecy *)\nquery not attacker(secret).\nprocess 0.\n'
TM_SOURCE = 'theory Control\nbegin\nlemma secrecy:\n "All x #i. Secret(x) @ i ==> not (Ex #j. K(x) @ j)"\nend\n'
SOURCES = {'proverif': PV_SOURCE, 'tamarin': TM_SOURCE}
SECURE = {'proverif': 'RESULT not attacker(secret) is true.\n',
          'tamarin': 'lemma secrecy: verified (all-traces)\n'}
ATTACK = {'proverif': 'RESULT not attacker(secret) is false.\n-> event Accept(secret)\n-> out(c, secret)\n',
          'tamarin': 'lemma secrecy: falsified - found trace\nrule Reveal(secret)\n'}


def forbidden(*args, **kwargs):
    pytest.fail('operation-control fixture reached native execution or the shared pool')


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
    return ExecutionBounds(timeout_ms=timeout_ms, max_memory_bytes=64*MIB,
                           max_output_bytes=8192, max_steps=100)


def request(provider='proverif', *, timeout_ms=1000, **kwargs):
    return v2.ProtocolExecutionRequestV2(request_id='req:protocol:operation',
        provider=provider, source=SOURCES[provider], bounds=bounds(timeout_ms), **kwargs)


@pytest.fixture
def fixture_engine():
    def build(*, action=None, attack=False, **controls):
        visits, native, workspaces = [], [], []
        def visit(provider, phase):
            visits.append((provider, phase))
            if action is not None:
                action(provider, phase)
        def compiler_type(base, provider):
            class Compiler(base):
                def compile_source(self, *args, **kwargs):
                    value = super().compile_source(*args, **kwargs)
                    visit(provider, 'compile')
                    return value
                def compile_protocol(self, *args, **kwargs):
                    value = super().compile_protocol(*args, **kwargs)
                    visit(provider, 'compile')
                    return value
            return Compiler
        def runner(provider):
            def execute(invocation, cancellation):
                operation = budget.current_proof_operation()
                native.append((provider, invocation, cancellation, operation))
                workspaces.append(invocation.cwd)
                visit(provider, 'native')
                filename = 'protocol.pv' if provider == 'proverif' else 'protocol.spthy'
                source = (invocation.cwd/filename).read_text()
                if source == SOURCES[provider]:
                    output = (ATTACK if attack else SECURE)[provider]
                else:
                    output = (_auto_proverif_secure if provider == 'proverif' else _auto_tamarin_secure)(source)
                return process.RawProcessResult(returncode=0, stdout=output, elapsed_seconds=0)
            return process.BoundedToolRunner(executor=execute)
        def probe(provider, phase, value):
            def run():
                visit(provider, phase)
                return value
            return run
        proverif = pv.ProVerifBackend(runner=runner('proverif'),
            compiler=compiler_type(pv.ProVerifCompiler, 'proverif')(),
            available_probe=probe('proverif', 'available', True),
            version_probe=probe('proverif', 'version', 'ProVerif fixture'),
            opam_probe=probe('proverif', 'dependency', 'fixture'))
        tamarin = tm.TamarinBackend(runner=runner('tamarin'),
            compiler=compiler_type(tm.TamarinCompiler, 'tamarin')(),
            available_probe=probe('tamarin', 'available', True),
            version_probe=probe('tamarin', 'version', 'Tamarin fixture'),
            maude_probe=probe('tamarin', 'dependency', 'fixture'))
        engine = v2.ProtocolExecutionEngineV2(proverif=proverif, tamarin=tamarin, **controls)
        return SimpleNamespace(engine=engine, visits=visits, native=native,
                               workspaces=workspaces, proverif=proverif, tamarin=tamarin)
    return build


@pytest.mark.parametrize('value', [True, 0, -1, 1.5, '100', budget.MAX_OPERATION_TIMEOUT_MS+1])
@pytest.mark.parametrize('route', ['constructor', 'execute', 'split', 'helper'])
def test_invalid_controls_fail_before_any_callback(fixture_engine, value, route):
    fixture = fixture_engine()
    with pytest.raises(ValueError):
        if route == 'constructor':
            v2.ProtocolExecutionEngineV2(proverif=fixture.proverif,
                tamarin=fixture.tamarin, operation_timeout_ms=value)
        elif route == 'execute':
            fixture.engine.execute(request(), operation_timeout_ms=value)
        elif route == 'split':
            fixture.engine.execute_split_providers({}, operation_timeout_ms=value)
        else:
            v2.execute_proverif(source=PV_SOURCE, engine=fixture.engine, operation_timeout_ms=value)
    assert not fixture.visits and not fixture.native


def test_constructor_remains_inert_and_preserves_falsey_injected_backends(fixture_engine):
    engine = v2.ProtocolExecutionEngineV2()
    assert type(engine.backend('proverif')._runner) is admission.ResourceAdmittedToolRunner
    assert type(engine.backend('tamarin')._runner) is admission.ResourceAdmittedToolRunner
    class FalseyProVerif(pv.ProVerifBackend):
        def __bool__(self):
            return False
    owned = FalseyProVerif(runner=process.BoundedToolRunner(executor=forbidden), available_probe=forbidden)
    assert v2.ProtocolExecutionEngineV2(proverif=owned).backend('proverif') is owned
    with pytest.raises(v2.ProtocolExecutionError):
        v2.ProtocolExecutionEngineV2(tamarin=object())


@pytest.mark.parametrize('route', ['execute', 'mapping', 'split', 'proverif_helper', 'tamarin_helper'])
def test_precancel_prevents_normalization_capability_and_backend(fixture_engine, route, monkeypatch):
    fixture = fixture_engine()
    req = request()
    event = threading.Event(); event.set()
    monkeypatch.setattr(v2, '_document_from_value', forbidden)
    with pytest.raises(budget.ProofOperationCancelled):
        if route == 'execute':
            fixture.engine.execute(req, cancellation=event)
        elif route == 'mapping':
            fixture.engine.execute({'request_id': 'x', 'provider': 'proverif', 'document': {}}, cancellation=event)
        elif route == 'split':
            fixture.engine.execute_split_providers({}, cancellation=event)
        else:
            helper = v2.execute_proverif if route == 'proverif_helper' else v2.execute_tamarin
            helper(document={}, engine=fixture.engine, cancellation=event)
    assert not fixture.visits and not fixture.native
    assert budget.current_proof_operation() is None


@pytest.mark.parametrize('provider', ['proverif', 'tamarin'])
@pytest.mark.parametrize('phase', ['available', 'compile', 'version', 'native'])
def test_default_request_budget_withholds_late_provider_result(fixture_engine, clock, provider, phase):
    def delay(selected, actual):
        if selected == provider and actual == phase:
            clock[0] += 1.1
    fixture = fixture_engine(action=delay)
    with pytest.raises(budget.ProofOperationTimeout):
        fixture.engine.execute(request(provider))
    assert len(fixture.native) == (1 if phase == 'native' else 0)
    assert not any(selected != provider for selected, _ in fixture.visits)
    assert all(not path.exists() for path in fixture.workspaces)


@pytest.mark.parametrize('route', ['mapping', 'helper', 'split'])
def test_document_normalization_consumes_budget_before_capability(fixture_engine, clock, monkeypatch, route):
    fixture = fixture_engine()
    document = _protocol().to_dict()
    original = v2._document_from_value
    def delayed(value):
        result = original(value)
        clock[0] += 1.1
        return result
    monkeypatch.setattr(v2, '_document_from_value', delayed)
    with pytest.raises(budget.ProofOperationTimeout):
        if route == 'mapping':
            fixture.engine.execute({'request_id': 'req:normalization', 'provider': 'proverif',
                'document': document, 'bounds': bounds()})
        elif route == 'helper':
            v2.execute_proverif(document, engine=fixture.engine, bounds=bounds())
        else:
            fixture.engine.execute_split_providers(document, bounds=bounds())
    assert not fixture.visits and not fixture.native


def test_request_digest_work_cannot_reset_budget_before_capability(fixture_engine, clock, monkeypatch):
    fixture = fixture_engine()
    req = request()
    original = v2._digest_of
    def delayed(value):
        digest = original(value)
        clock[0] += 1.1
        return digest
    monkeypatch.setattr(v2, '_digest_of', delayed)
    with pytest.raises(budget.ProofOperationTimeout):
        fixture.engine.execute(req)
    assert not fixture.visits and not fixture.native


@pytest.mark.parametrize('phase', ['capability', 'attack', 'document', 'evidence', 'result'])
@pytest.mark.parametrize('attack', [False, True])
@pytest.mark.parametrize('stop', ['timeout', 'cancel'])
def test_late_binding_or_publication_never_returns_conclusive_evidence(
        fixture_engine, clock, monkeypatch, phase, attack, stop):
    fixture = fixture_engine(attack=attack)
    event = threading.Event()
    def trip():
        if stop == 'cancel':
            event.set()
        else:
            clock[0] += 1.1
    if phase == 'capability':
        original = fixture.engine.capability_receipt
        def delayed(*args, **kwargs):
            result = original(*args, **kwargs)
            trip()
            return result
        monkeypatch.setattr(fixture.engine, 'capability_receipt', delayed)
    elif phase == 'attack':
        original = v2.ProtocolAttackBindingV2.from_outcomes.__func__
        def delayed(cls, *args, **kwargs):
            result = original(cls, *args, **kwargs)
            trip()
            return result
        monkeypatch.setattr(v2.ProtocolAttackBindingV2, 'from_outcomes', classmethod(delayed))
    else:
        selected = {'document': v2.ProtocolDocumentBindingV2,
                    'evidence': v2.ProtocolProviderEvidenceV2,
                    'result': v2.ProtocolExecutionResultV2}[phase]
        original = selected.__post_init__
        def delayed(self):
            original(self)
            trip()
        monkeypatch.setattr(selected, '__post_init__', delayed)
    expected = budget.ProofOperationCancelled if stop == 'cancel' else budget.ProofOperationTimeout
    with pytest.raises(expected):
        fixture.engine.execute(request(), cancellation=event)
    assert len(fixture.native) == (0 if phase == 'capability' else 1)
    assert all(not path.exists() for path in fixture.workspaces)


@pytest.mark.parametrize('provider', ['proverif', 'tamarin'])
def test_canonical_backend_receives_latched_operation_signal(fixture_engine, provider):
    event = threading.Event()
    seen = []
    def cancel(selected, phase):
        if phase == 'native':
            operation = budget.current_proof_operation()
            event.set()
            assert operation.is_set()
            event.clear()
            seen.append(operation)
    fixture = fixture_engine(action=cancel)
    with pytest.raises(budget.ProofOperationCancelled):
        fixture.engine.execute(request(provider), cancellation=event)
    assert len(fixture.native) == 1 and fixture.native[0][2] is seen[0]
    assert fixture.native[0][3] is seen[0]
    assert not event.is_set() and budget.current_proof_operation() is None


def test_nested_timeout_revokes_parent_without_resetting_deadline(fixture_engine, clock):
    fixture = fixture_engine(action=lambda _, phase: clock.__setitem__(0, clock[0]+.11) if phase == 'native' else None)
    with pytest.raises(budget.ProofOperationTimeout):
        with budget.proof_operation_scope(timeout_ms=100) as parent:
            with pytest.raises(budget.ProofOperationTimeout):
                fixture.engine.execute(request(timeout_ms=2000), operation_timeout_ms=5000)
            assert parent.is_set()
    assert len(fixture.native) == 1


@pytest.mark.parametrize('stop', ['timeout', 'cancel'])
def test_split_withholds_partial_result_and_does_not_start_second_provider(fixture_engine, clock, monkeypatch, stop):
    fixture = fixture_engine()
    event = threading.Event()
    original = fixture.engine._from_backend_outcome
    def finish(*args, **kwargs):
        value = original(*args, **kwargs)
        if stop == 'cancel':
            event.set()
        else:
            clock[0] += 1.1
        return value
    monkeypatch.setattr(fixture.engine, '_from_backend_outcome', finish)
    expected = budget.ProofOperationCancelled if stop == 'cancel' else budget.ProofOperationTimeout
    with pytest.raises(expected):
        fixture.engine.execute_split_providers(_protocol(), bounds=bounds(), cancellation=event)
    assert [row[0] for row in fixture.native] == ['proverif']
    assert all(provider == 'proverif' for provider, _ in fixture.visits)


def test_split_scope_shrinks_for_second_provider_and_preserves_original_bounds(fixture_engine, clock):
    remaining = []
    def consume(provider, phase):
        if phase == 'native':
            remaining.append(budget.current_proof_operation().deadline-clock[0])
            clock[0] += .3
    fixture = fixture_engine(action=consume)
    limits = bounds()
    result = fixture.engine.execute_split_providers(_protocol(), bounds=limits)
    assert list(result) == list(v2.ProtocolProviderKind)
    assert remaining == pytest.approx([1., .7])
    assert all(value.request.bounds is limits and value.backend_result.bounds == limits for value in result.values())


def test_constructor_call_and_request_limits_tighten_without_changing_wire(fixture_engine, clock):
    observed = []
    fixture = fixture_engine(operation_timeout_ms=100, action=lambda _, phase:
        observed.append(budget.current_proof_operation().deadline-clock[0]) if phase == 'native' else None)
    req = request(timeout_ms=500)
    before = req.to_dict()
    fixture.engine.execute(req)
    fixture.engine.execute(req, operation_timeout_ms=400)
    fixture.engine.execute(req, operation_timeout_ms=900)
    v2.execute_proverif(source=PV_SOURCE, bounds=req.bounds, engine=fixture.engine, operation_timeout_ms=900)
    assert observed == pytest.approx([.1, .4, .5, .5])
    assert req.to_dict() == before
    assert 'operation_timeout_ms' not in before and 'cancellation' not in before


def test_implicit_default_is_one_second_and_huge_request_is_safely_capped(fixture_engine, clock):
    observed = []
    fixture = fixture_engine(action=lambda _, phase:
        observed.append(budget.current_proof_operation().deadline-clock[0]) if phase == 'native' else None)
    # Unavailable avoids constructing a platform-specific enormous CPU limit.
    original = fixture.proverif._available_probe
    fixture.proverif._available_probe = lambda: (observed.append(budget.current_proof_operation().deadline-clock[0]), False)[1]
    default = v2.ProtocolExecutionRequestV2(request_id='req:default', provider='proverif', source=PV_SOURCE)
    huge = replace(default, bounds=bounds(budget.MAX_OPERATION_TIMEOUT_MS+12345))
    fixture.engine.execute(default)
    fixture.engine.execute(huge)
    assert observed[0] == pytest.approx(1.)
    assert observed[-1] == pytest.approx(budget.MAX_OPERATION_TIMEOUT_MS/1000)
    assert huge.bounds.timeout_ms == budget.MAX_OPERATION_TIMEOUT_MS+12345
    fixture.proverif._available_probe = original


@pytest.mark.parametrize('mode', ['mock', 'fallback'])
def test_nonexecuting_modes_still_obey_precancel_and_final_gate(fixture_engine, clock, monkeypatch, mode):
    fixture = fixture_engine()
    req = request(mode=mode)
    original = fixture.engine._rejected
    def delayed(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] += 1.1
        return result
    monkeypatch.setattr(fixture.engine, '_rejected', delayed)
    with pytest.raises(budget.ProofOperationTimeout):
        fixture.engine.execute(req)
    event = threading.Event(); event.set()
    visits = len(fixture.visits)
    with pytest.raises(budget.ProofOperationCancelled):
        fixture.engine.execute(req, cancellation=event)
    assert len(fixture.visits) == visits and not fixture.native


@pytest.mark.parametrize('failure', [TypeError, RuntimeError, KeyboardInterrupt])
def test_legacy_backend_override_is_called_once_without_new_keywords(fixture_engine, failure):
    fixture = fixture_engine()
    seen = []
    class Legacy(pv.ProVerifBackend):
        def run(self, req):
            seen.append((self, req, budget.current_proof_operation()))
            raise failure('owned callback failure')
    owned = Legacy(available_probe=lambda: True, runner=process.BoundedToolRunner(executor=forbidden))
    engine = v2.ProtocolExecutionEngineV2(proverif=owned, tamarin=fixture.tamarin)
    with pytest.raises(failure, match='owned callback failure'):
        engine.execute(request())
    assert len(seen) == 1 and seen[0][0] is owned and seen[0][2] is not None
    assert engine.backend('proverif') is owned and budget.current_proof_operation() is None


def test_callback_exception_cannot_hide_observed_cancellation(fixture_engine):
    event = threading.Event()
    def fail(provider, phase):
        if phase == 'version':
            event.set()
            assert budget.current_proof_operation().is_set()
            event.clear()
            raise OSError('opaque version callback failed after cancellation')
    fixture = fixture_engine(action=fail)
    with pytest.raises(budget.ProofOperationCancelled):
        fixture.engine.execute(request(), cancellation=event)
    assert not fixture.native and not event.is_set()
    assert budget.current_proof_operation() is None


@pytest.mark.parametrize('route', ['helper', 'split'])
def test_legacy_execute_override_late_result_is_not_retried_or_published(fixture_engine, clock, route):
    fixture = fixture_engine()
    calls = []
    class Legacy(v2.ProtocolExecutionEngineV2):
        def __bool__(self):
            return False
        def execute(self, req):
            calls.append((self, req))
            value = fixture.engine.execute(req)
            clock[0] += 1.1
            return value
    owned = Legacy(proverif=fixture.proverif, tamarin=fixture.tamarin)
    with pytest.raises(budget.ProofOperationTimeout):
        if route == 'helper':
            v2.execute_proverif(source=PV_SOURCE, engine=owned, bounds=bounds())
        else:
            owned.execute_split_providers(_protocol(), bounds=bounds())
    assert len(calls) == 1 and calls[0][0] is owned


def test_falsey_opaque_helper_engine_gets_exact_old_signature_once():
    calls = []
    class Owned:
        def __bool__(self):
            return False
        def execute(self, req):
            calls.append((self, req, budget.current_proof_operation()))
            raise TypeError('opaque callback error')
    selected = Owned()
    with pytest.raises(TypeError, match='opaque callback error'):
        v2.execute_proverif(source=PV_SOURCE, engine=selected, cancellation=threading.Event())
    assert len(calls) == 1 and calls[0][0] is selected and calls[0][2] is not None


def test_constructor_and_call_signals_combine_and_reuse_does_not_keep_stop(fixture_engine):
    constructor_signal, call_signal = threading.Event(), threading.Event()
    fixture = fixture_engine(cancellation=constructor_signal)
    for event in (constructor_signal, call_signal):
        event.set()
        with pytest.raises(budget.ProofOperationCancelled):
            fixture.engine.execute(request(), cancellation=call_signal)
        event.clear()
    healthy = fixture.engine.execute(request(), cancellation=call_signal)
    assert healthy.protocol_established and len(fixture.native) == 1


def test_shared_engine_threads_do_not_mix_signals_or_deadlines(fixture_engine):
    barrier = threading.Barrier(2)
    contexts, outcomes = {}, {}
    def synchronize(provider, phase):
        if phase == 'native':
            name = threading.current_thread().name
            contexts[name] = budget.current_proof_operation()
            barrier.wait(timeout=3)
            if name == 'cancelled-call':
                stop.set()
                assert contexts[name].is_set()
    fixture = fixture_engine(action=synchronize)
    stop = threading.Event()
    def execute(name):
        try:
            outcomes[name] = fixture.engine.execute(request(timeout_ms=5000), cancellation=stop if name == 'cancelled-call' else None)
        except BaseException as error:
            outcomes[name] = error
    threads = [threading.Thread(target=execute, args=(name,), name=name) for name in ('cancelled-call', 'healthy-call')]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(4)
    assert not any(thread.is_alive() for thread in threads)
    assert isinstance(outcomes['cancelled-call'], budget.ProofOperationCancelled)
    assert outcomes['healthy-call'].protocol_established
    assert contexts['cancelled-call'] is not contexts['healthy-call']
    assert budget.current_proof_operation() is None


@pytest.mark.parametrize('provider', ['proverif', 'tamarin'])
@pytest.mark.parametrize('attack', [False, True])
def test_successful_controls_preserve_complete_evidence_wire(fixture_engine, provider, attack):
    fixture = fixture_engine(attack=attack)
    req = request(provider)
    baseline = fixture.engine.execute(req).to_dict()
    controlled = fixture.engine.execute(req, operation_timeout_ms=500, cancellation=threading.Event()).to_dict()
    assert controlled == baseline
    expected = 'unknown' if provider == 'tamarin' and attack else ('attack_found' if attack else 'secure')
    assert controlled['backend_result']['status'] == expected
    if provider == 'tamarin' and attack:
        assert not controlled['evidence']['protocol_established']
        assert not controlled['evidence']['attack']['replayed']
        assert not controlled['evidence']['attack']['attack_traces']
    assert controlled['is_theorem_authority'] is False


def test_mapping_bounds_remain_rejected_instead_of_coercing_a_new_wire(fixture_engine):
    fixture = fixture_engine()
    with pytest.raises(v2.ProtocolExecutionError):
        fixture.engine.execute({'request_id': 'req:bad-bounds', 'provider': 'proverif',
            'source': PV_SOURCE, 'bounds': bounds().to_dict()})
    assert not fixture.visits


@pytest.fixture
def private_admission(tmp_path, monkeypatch):
    healthy = ProofHostResources(8, 8192, 8192, pid_task_limit=8192, available_pid_tasks=8192)
    current, actions, entered = [healthy], [None], threading.Event()
    def sample():
        entered.set()
        return current[0]
    owner = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path/'private-protocol-operation.json', proof_resource_sampler=sample,
        total_cpu_slots=2, total_memory_mb=256, total_child_process_slots=2,
        proof_memory_headroom_mb=64, lane_reservations={}, auto_renew_leases=False,
        proof_backoff_seconds=.01, poll_interval_seconds=.002))
    calls, workspaces = [], []
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', lambda: owner)
    monkeypatch.setattr(process.shutil, 'which', lambda *args, **kwargs: sys.executable)
    def execute(self, invocation, cancellation=None):
        snapshot = owner.snapshot()
        assert snapshot['active_root_lease_count'] == snapshot['active_lease_count'] == 1
        assert snapshot['allocated'] == {'cpu_slots': 1, 'memory_mb': 64}
        calls.append((invocation, cancellation, budget.current_proof_operation()))
        workspaces.append(invocation.cwd)
        if actions[0] is not None:
            actions[0](invocation, cancellation)
        return process.RawProcessResult(returncode=0, stdout=SECURE['proverif'], elapsed_seconds=0)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', execute)
    yield SimpleNamespace(owner=owner, healthy=healthy, current=current, entered=entered,
                          calls=calls, actions=actions, workspaces=workspaces)
    snapshot = owner.snapshot()
    assert snapshot['active_lease_count'] == snapshot['waiting_request_count'] == 0
    assert all(not path.exists() for path in workspaces)


def test_default_admitted_native_receives_only_remaining_wall_and_cpu(private_admission, clock):
    class SlowCompile(pv.ProVerifCompiler):
        def compile_source(self, *args, **kwargs):
            value = super().compile_source(*args, **kwargs)
            clock[0] += .25
            return value
    backend = pv.ProVerifBackend(compiler=SlowCompile(), available_probe=lambda: True,
        version_probe=lambda: (clock.__setitem__(0, clock[0]+.25), 'fixture')[1])
    req = request()
    before = req.to_dict()
    result = v2.ProtocolExecutionEngineV2(proverif=backend).execute(req)
    invocation, signal, operation = private_admission.calls[0]
    assert 0 < invocation.limits.timeout_seconds <= .5
    assert invocation.limits.cpu_seconds == pytest.approx(.5)
    assert invocation.limits.memory_bytes == req.bounds.max_memory_bytes
    assert signal is not None and operation is not None
    assert result.protocol_established and result.backend_result.bounds == req.bounds
    assert req.to_dict() == before


@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
def test_private_external_pressure_queue_stops_without_native_and_drains(private_admission, monkeypatch, stop):
    private_admission.current[0] = replace(private_admission.healthy, available_memory_mb=0)
    private_admission.entered.clear()
    monkeypatch.setattr(process.BoundedToolRunner, '_write_inputs', staticmethod(forbidden))
    event = threading.Event()
    outcome = []
    def execute():
        try:
            v2.ProtocolExecutionEngineV2().execute(request(),
                operation_timeout_ms=100 if stop == 'timeout' else 2000, cancellation=event)
        except BaseException as error:
            outcome.append(error)
    thread = threading.Thread(target=execute)
    thread.start()
    try:
        assert private_admission.entered.wait(2)
        if stop == 'cancel':
            event.set()
        thread.join(3)
        assert not thread.is_alive()
        expected = budget.ProofOperationCancelled if stop == 'cancel' else budget.ProofOperationTimeout
        assert len(outcome) == 1 and isinstance(outcome[0], expected)
        assert not private_admission.calls
    finally:
        event.set()
        thread.join(3)


def test_observed_native_cancel_survives_event_clear_and_cleanup(private_admission):
    event = threading.Event()
    def cancel(invocation, signal):
        event.set()
        assert signal.is_set()
        event.clear()
    private_admission.actions[0] = cancel
    with pytest.raises(budget.ProofOperationCancelled):
        v2.ProtocolExecutionEngineV2().execute(request(), cancellation=event)
    assert len(private_admission.calls) == 1 and not event.is_set()
    assert all(not path.exists() for path in private_admission.workspaces)
