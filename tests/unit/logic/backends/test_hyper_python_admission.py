"""Actual private admission for bounded Python fallback, without native tools."""
from contextvars import copy_context
from dataclasses import replace
import json
import os
import subprocess
import threading
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process, python_admission as admission
from ipfs_datasets_py.logic.backends import registry
from ipfs_datasets_py.logic.backends.hyperproperties import adapters as hyper, execution_v2 as v2
from ipfs_datasets_py.logic.backends.smt import operation_budget as budget
from ipfs_datasets_py.logic.software_verification import hyperproperties as core
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from tests.unit.logic.backends._python_admission_fixtures import python_pool
from tests.unit.logic.backends.test_hyper_fallback_validation import (
    document, pair, trace_mapping, PRIVATE_LEFT, PRIVATE_RIGHT,
)
from tests.unit.logic.backends.test_hyper_resource_admission import BACKENDS, AIGER, request as generic_request

MIB = 1024**2


def forbidden(*args, **kwargs):
    pytest.fail('Python fallback reached native execution or shared scheduler')


@pytest.fixture(autouse=True)
def guarded(monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(os, 'system', forbidden)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', forbidden)
    monkeypatch.setattr(process.BoundedToolRunner, '_write_inputs', staticmethod(forbidden))
    monkeypatch.setattr(schedulers, 'get_global_resource_scheduler', forbidden)
    monkeypatch.setitem(hyper.HyperpropertyBackend.__init__.__kwdefaults__, 'which', lambda name: None)


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    for module in (admission, budget, registry):
        monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    return now


def admitted(memory=128*MIB):
    return admission.admitted_python_work(memory_bytes=memory)


def execute(provider='hyperltl', route='direct', violated=True):
    doc, traces = document(), pair(violated=violated)
    req = generic_request(provider, timeout_ms=3000, memory=128*MIB, output=65536)
    if route == 'direct':
        return BACKENDS[provider]().check(doc, bounds=req.bounds, traces=traces,
            allow_fallback=True, system_model=AIGER if provider == 'mchyper' else None)
    if route == 'registry':
        req = replace(req, payload={**req.payload.to_dict(), 'document': doc.to_dict(),
            'allow_fallback': True, 'traces': [trace_mapping(value) for value in traces]})
        return registry.default_backend_registry().run(req)
    req = v2.HyperExecutionRequestV2(request_id='request:python-admission', provider=provider,
        document=doc, traces=traces, allow_fallback=True, bounds=req.bounds,
        system_model=AIGER if provider == 'mchyper' else None)
    return v2.HyperExecutionEngineV2().execute(req)


@pytest.mark.parametrize('provider', BACKENDS)
@pytest.mark.parametrize('route', ['direct', 'registry', 'v2'])
@pytest.mark.parametrize('violated', [False, True])
def test_actual_fallback_routes_and_private_revalidation_hold_finite_reservations(
        monkeypatch, python_pool, provider, route, violated):
    observed = []
    original = core._projection
    def projection(*args):
        snapshot = python_pool.owner.snapshot()
        assert snapshot['active_lease_count'] == 1
        assert python_pool.acquired[-1].cpu_slots == 1
        assert python_pool.acquired[-1].memory_mb == 128
        assert python_pool.acquired[-1].child_process_slots == 0
        observed.append(python_pool.acquired[-1].lease_id)
        return original(*args)
    monkeypatch.setattr(core, '_projection', projection)
    result = execute(provider, route, violated)
    assert observed
    if route == 'registry':
        attempt, value = result
        assert attempt.status.value == 'succeeded' and value.status.value == 'unknown'
        assert value.payload['result']['status'] == ('violated' if violated else 'unknown')
        wire = value.to_dict()
    elif route == 'v2':
        assert result.disposition.value == ('violated' if violated else 'unknown')
        assert not result.hyperproperty_established and not result.is_proved
        assert len(set(observed)) >= 2  # Execution and retained-trace applicability are both admitted.
        wire = result.to_dict()
    else:
        assert result.result.status.value == ('violated' if violated else 'unknown')
        assert not result.receipt.authorizes_universal_proof and not result.receipt.external_tool_proof
        wire = result.to_dict()
    encoded = json.dumps(wire, sort_keys=True)
    assert PRIVATE_LEFT not in encoded and PRIVATE_RIGHT not in encoded
    assert '"private_inputs":' not in encoded
    assert python_pool.owner.snapshot()['active_lease_count'] == 0


def test_discovery_and_configuration_are_inert_but_default_work_resolves_pool(monkeypatch, python_pool):
    calls = []
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', lambda: calls.append(True) or python_pool.owner)
    with admission.python_admission_context():
        backend = hyper.HyperLTLBackend()
        assert backend.is_available() is False and not calls
        with budget.proof_operation_scope(timeout_ms=1000), admitted(MIB+1):
            assert calls == [True] and python_pool.acquired[-1].memory_mb == 2
    assert python_pool.acquired[-1].released


@pytest.mark.parametrize('route', ['direct', 'standalone-reconstruction'])
def test_publication_and_standalone_reconstruction_remain_inside_reservation(monkeypatch, python_pool, route):
    if route == 'direct':
        original = hyper.HyperpropertyBackend._result_from_receipt
        def pack(*args, **kwargs):
            assert python_pool.owner.snapshot()['active_lease_count'] == 1
            return original(*args, **kwargs)
        monkeypatch.setattr(hyper.HyperpropertyBackend, '_result_from_receipt', pack)
        execute()
    else:
        result = execute(route='v2')
        before = len(python_pool.acquired)
        assert budget.current_proof_operation() is None
        rebuilt = replace(result)
        assert rebuilt.to_dict() == result.to_dict()
        assert len(python_pool.acquired) == before+1


@pytest.mark.parametrize('pressure', ['cpu', 'memory', 'io', 'pid', 'unknown'])
def test_external_pressure_blocks_work_then_recovers(monkeypatch, python_pool, pressure):
    fields = {'cpu': {'cpu_stall_percent': 100}, 'memory': {'available_memory_mb': 0},
              'io': {'io_stall_percent': 100}, 'pid': {'available_pid_tasks': 0}}
    python_pool.current[0] = OSError('unavailable telemetry') if pressure == 'unknown' else replace(
        python_pool.healthy, **fields[pressure])
    python_pool.sampled.clear()
    entered = threading.Event(); errors = []
    def worker():
        try:
            with budget.proof_operation_scope(timeout_ms=2000), admitted():
                entered.set()
        except BaseException as error:
            errors.append(error)
    thread = threading.Thread(target=worker); thread.start()
    try:
        assert python_pool.sampled.wait(1) and not entered.is_set()
        assert not python_pool.acquired
        python_pool.current[0] = python_pool.healthy
    finally:
        python_pool.current[0] = python_pool.healthy
        thread.join(2)
    assert not thread.is_alive() and not errors and entered.is_set()


@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
def test_queued_stop_removes_waiter_without_entering_work(python_pool, stop):
    python_pool.current[0] = replace(python_pool.healthy, available_memory_mb=0)
    python_pool.sampled.clear(); signal = threading.Event(); errors = []; entered = []
    def worker():
        try:
            with budget.proof_operation_scope(timeout_ms=100 if stop=='timeout' else 2000,
                                              cancellation=signal), admitted():
                entered.append(True)
        except BaseException as error:
            errors.append(error)
    thread = threading.Thread(target=worker); thread.start()
    try:
        assert python_pool.sampled.wait(1)
        if stop == 'cancel':
            signal.set()
        thread.join(2)
    finally:
        signal.set(); thread.join(2)
    assert not thread.is_alive() and not entered and len(errors) == 1
    assert isinstance(errors[0], budget.ProofOperationCancelled if stop=='cancel' else budget.ProofOperationTimeout)
    assert not python_pool.acquired and python_pool.owner.snapshot()['waiting_request_count'] == 0


def test_precancel_does_not_resolve_scheduler(monkeypatch):
    signal = threading.Event(); signal.set()
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', forbidden)
    with pytest.raises(budget.ProofOperationCancelled):
        with budget.proof_operation_scope(timeout_ms=1000, cancellation=signal), admitted():
            pytest.fail('pre-cancelled body entered')


@pytest.mark.parametrize('stop', ['cancel', 'timeout', 'lease'])
def test_runtime_stop_is_sticky_and_releases_before_refusing_result(python_pool, clock, stop):
    signal = threading.Event()
    expected = budget.ProofOperationTimeout if stop=='timeout' else budget.ProofOperationCancelled
    with pytest.raises(expected):
        with budget.proof_operation_scope(timeout_ms=1000, cancellation=signal), admitted() as checkpoint:
            if stop=='cancel':
                signal.set()
            elif stop=='timeout':
                clock[0] += 2
            else:
                python_pool.acquired[-1].cancel(); clock[0] += .1
            with pytest.raises(expected):
                checkpoint('actual evaluation checkpoint')
            signal.clear()
    assert python_pool.acquired[-1].released and budget.current_proof_operation() is None


def test_same_thread_nesting_reuses_envelope_and_rejects_larger_demand(python_pool):
    with budget.proof_operation_scope(timeout_ms=1000), admitted(128*MIB):
        with admitted(64*MIB):
            assert len(python_pool.acquired) == 1
        with pytest.raises(schedulers.ResourceUnavailableError):
            with admitted(129*MIB):
                pytest.fail('oversized nested body entered')
        assert not python_pool.acquired[0].released
    assert python_pool.acquired[0].released


def test_copied_context_on_other_thread_gets_separate_cpu_reservation(python_pool):
    errors = []; entered = []
    with budget.proof_operation_scope(timeout_ms=2000), admitted():
        context = copy_context()
        def child():
            try:
                with admitted():
                    entered.append(python_pool.owner.snapshot()['active_lease_count'])
            except BaseException as error:
                errors.append(error)
        thread = threading.Thread(target=lambda: context.run(child)); thread.start(); thread.join(1)
        assert not thread.is_alive() and not errors and entered == [2]
        assert len(python_pool.acquired) == 2 and python_pool.acquired[-1].released
        assert not python_pool.acquired[0].released


def test_explicit_parent_child_is_not_double_charged_or_released(python_pool):
    with python_pool.owner.acquire('validation', cpu_slots=2, memory_mb=256, child_process_slots=0) as parent:
        with admission.python_admission_context(parent_lease=parent):
            with budget.proof_operation_scope(timeout_ms=1000), admitted():
                child = python_pool.acquired[-1]
                assert child.parent_lease_id == parent.lease_id and child.child_process_slots == 0
                snapshot = python_pool.owner.snapshot()
                assert snapshot['active_lease_count'] == 2
                assert snapshot['allocated'] == {'cpu_slots': 2, 'memory_mb': 256}
            assert child.released and not parent.released and not parent.cancelled


@pytest.mark.parametrize('kind', ['foreign', 'released', 'cancelled', 'too-small'])
def test_invalid_parent_never_enters_work(python_pool, kind):
    parent = python_pool.owner.acquire('validation', cpu_slots=1, memory_mb=64 if kind=='too-small' else 256,
                                      child_process_slots=0)
    original_pid = parent.owner_pid
    try:
        if kind=='foreign': parent.owner_pid += 1_000_000
        if kind=='released': parent.release()
        if kind=='cancelled': parent.cancel()
        expected = (schedulers.ResourceConfigurationError if kind=='foreign' else
                    schedulers.ResourceUnavailableError if kind=='too-small' else budget.ProofOperationCancelled)
        with pytest.raises(expected):
            with admission.python_admission_context(parent_lease=parent), budget.proof_operation_scope(timeout_ms=1000), admitted():
                pytest.fail('invalid parent admitted work')
    finally:
        parent.owner_pid = original_pid
        parent.release()


@pytest.mark.parametrize('kind', ['body', 'release', 'late-release'])
def test_exceptions_and_late_release_do_not_publish_success(monkeypatch, python_pool, clock, kind):
    original = schedulers.ResourceLease.release
    def release(lease):
        answer = original(lease)
        if kind=='release':
            raise schedulers.ResourceSchedulerError('controlled release failure')
        if kind=='late-release': clock[0] += 2
        return answer
    if kind!='body': monkeypatch.setattr(schedulers.ResourceLease, 'release', release)
    expected = ValueError if kind=='body' else budget.ProofOperationTimeout if kind=='late-release' else schedulers.ResourceSchedulerError
    with pytest.raises(expected):
        with budget.proof_operation_scope(timeout_ms=1000), admitted():
            if kind=='body': raise ValueError('controlled body failure')
    assert python_pool.acquired[-1].released


@pytest.mark.parametrize('memory', [None, False, 0, -1, 1.5, '128'])
def test_invalid_memory_does_not_resolve_scheduler(monkeypatch, memory):
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', forbidden)
    with budget.proof_operation_scope(timeout_ms=1000), pytest.raises(schedulers.ResourceConfigurationError):
        with admitted(memory): pass


def test_capacity_refusal_is_not_silently_reduced(python_pool):
    with budget.proof_operation_scope(timeout_ms=1000), pytest.raises(schedulers.ResourceUnavailableError):
        with admitted(4097*MIB):
            pytest.fail('oversized root admitted')
    assert not python_pool.acquired


def test_plain_native_runner_does_not_bypass_independent_python_admission(python_pool):
    runner = process.BoundedToolRunner(executor=forbidden)
    backend = hyper.HyperLTLBackend(runner=runner, which=lambda name: None)
    result = backend.check(document(), traces=pair(), allow_fallback=True)
    assert backend._runner is runner and result.result.status.value == 'violated'
    assert len(python_pool.acquired) == 1 and python_pool.acquired[0].released


def test_reused_context_does_not_make_released_lease_a_cancellation(python_pool):
    for _ in range(2):
        with budget.proof_operation_scope(timeout_ms=1000), admitted() as checkpoint:
            assert checkpoint('healthy work') > 0
    assert len(python_pool.acquired) == 2 and budget.current_proof_operation() is None


@pytest.mark.parametrize('kind', ['scheduler', 'parent', 'both'])
def test_configuration_rejects_invalid_ownership_without_resolving(kind, monkeypatch, python_pool):
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', forbidden)
    options = ({'scheduler': object()} if kind=='scheduler' else
               {'parent_lease': object()} if kind=='parent' else
               {'scheduler': python_pool.owner, 'parent_lease': object()})
    with pytest.raises(schedulers.ResourceConfigurationError if kind=='both' else TypeError):
        with admission.python_admission_context(**options):
            pytest.fail('invalid context entered')
    assert not python_pool.acquired


@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
def test_scheduler_resolution_cannot_spend_budget_then_admit(monkeypatch, python_pool, clock, stop):
    signal = threading.Event()
    def resolve():
        if stop=='cancel': signal.set()
        else: clock[0] += 2
        return python_pool.owner
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', resolve)
    expected = budget.ProofOperationCancelled if stop=='cancel' else budget.ProofOperationTimeout
    with pytest.raises(expected):
        with admission.python_admission_context(), budget.proof_operation_scope(
                timeout_ms=1000, cancellation=signal), admitted():
            pytest.fail('late scheduler resolution admitted work')
    assert not python_pool.acquired


def test_missing_operation_is_not_an_unbounded_execution(monkeypatch):
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', forbidden)
    with pytest.raises(schedulers.ResourceConfigurationError, match='operation scope'):
        with admitted(): pass


@pytest.mark.parametrize('error_type', [KeyboardInterrupt, SystemExit])
def test_special_base_exception_survives_a_simultaneous_signal_after_release(python_pool, error_type):
    signal = threading.Event()
    failure = error_type('controlled interruption')
    with pytest.raises(error_type) as captured:
        with budget.proof_operation_scope(timeout_ms=1000, cancellation=signal), admitted():
            signal.set()
            raise failure
    assert captured.value is failure and python_pool.acquired[-1].released
