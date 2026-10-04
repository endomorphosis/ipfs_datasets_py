"""Request-local Hyper fallback without weakening availability vetoes.

Missing native tools may opt into real bounded self-composition. Discovery stays
false, native admission stays mandatory when a tool is present, and the generic
result never acquires theorem or satisfiability authority from fallback.
"""
from dataclasses import replace
import json
import os
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process, registry as reg, resource_admission
from ipfs_datasets_py.logic.backends.hyperproperties import adapters as hyper
from ipfs_datasets_py.logic.backends.smt import operation_budget as budget
from ipfs_datasets_py.logic.ir_core.protocols import QueryKind
from ipfs_datasets_py.logic.software_verification import hyperproperties as core
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler
from tests.unit.logic.backends.test_hyper_fallback_validation import (
    PRIVATE_LEFT, PRIVATE_RIGHT, document, pair, trace_mapping,
)
from tests.unit.logic.backends.test_hyper_resource_admission import (
    BACKENDS, SUCCESS, request as base_request, host as private_native,
)

from tests.unit.logic.backends._python_admission_fixtures import python_pool

pytestmark = pytest.mark.usefixtures("python_pool")

FAMILY = 'hyperltl_autohyper_mchyper'
PROVIDERS = (FAMILY, *BACKENDS)
MISSING = object()


def forbidden(*args, **kwargs):
    pytest.fail('registry fallback fixture reached native execution or shared scheduler')


@pytest.fixture(autouse=True)
def no_host_work(monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(os, 'system', forbidden)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', forbidden)
    monkeypatch.setattr(resource_admission, 'get_global_resource_scheduler', forbidden)
    monkeypatch.setattr(resource_scheduler, 'get_global_resource_scheduler', forbidden)
    monkeypatch.setitem(hyper.HyperpropertyBackend.__init__.__kwdefaults__, 'which', lambda name: None)


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    for module in (budget, reg, resource_admission):
        monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    return now


@pytest.fixture
def fallback_calls(monkeypatch):
    calls = []
    original = hyper.HyperpropertyBackend._fallback_outcome
    def observed(backend, *args, **kwargs):
        calls.append((backend.engine.value, budget.current_proof_operation()))
        return original(backend, *args, **kwargs)
    monkeypatch.setattr(hyper.HyperpropertyBackend, '_fallback_outcome', observed)
    return calls


def request(provider='hyperltl', *, allow=True, traces=MISSING, violated=True,
            kind=QueryKind.SATISFIABILITY, timeout_ms=2000):
    engine = 'hyperltl' if provider == FAMILY else provider
    req = base_request(engine, timeout_ms=timeout_ms, output=65536)
    payload = {**req.payload.to_dict(), 'document': document().to_dict()}
    if allow is not MISSING:
        payload['allow_fallback'] = allow
    if traces is MISSING:
        traces = [trace_mapping(item) for item in pair(violated=violated)]
    if traces is not None:
        payload['traces'] = traces
    return replace(req, requested_backend_id=provider, query_kind=kind, payload=payload)


def entry(provider='hyperltl'):
    return next(value for value in reg.EXECUTABLE_PROVIDER_MATRIX if value.provider_id == provider)


def lane(delegate=None, *, provider='hyperltl', factory=None, availability_probe=None, selected_entry=None):
    if factory is None:
        factory = lambda: delegate
    wrapper = reg.LazyMatrixProofBackend(selected_entry or entry(provider), factory=factory,
        availability_probe=availability_probe)
    return wrapper, reg.ProofBackendRegistry((wrapper,))


def unavailable(outcome, req):
    attempt, value = outcome
    assert attempt.status.value == 'unavailable'
    assert value.status.value == 'unknown' and 'result' not in value.payload
    assert attempt.request_digest == value.request_digest == req.digest
    assert value.bounds == attempt.bounds == req.bounds
    assert not value.is_theorem_proof


def bounded(outcome, req, *, provider, violated):
    attempt, value = outcome
    assert attempt.status.value == 'succeeded' and value.status.value == 'unknown'
    assert attempt.backend_id == value.backend_id == provider
    assert attempt.request_digest == value.request_digest == req.digest
    assert value.attempt_digest == attempt.digest
    assert value.bounds == attempt.bounds == req.bounds
    assert value.assumption_ids == req.assumption_ids and not value.is_theorem_proof
    typed = value.payload['result']
    assert typed['backend_id'] == ('hyperltl' if provider == FAMILY else provider)
    assert typed['status'] == ('violated' if violated else 'unknown')
    assert typed['metadata']['evidence_path'] == 'bounded_self_composition'
    assert typed['metadata']['external_tool_proof'] is False
    assert 'process' not in typed['metadata']
    assert typed['witness']['authorizes_universal_proof'] is False
    if violated:
        assert typed['witness']['counterexample']['replayed'] is True
        assert typed['witness']['counterexample']['raw'] == ''
    encoded = json.dumps(value.to_dict(), sort_keys=True)
    assert PRIVATE_LEFT not in encoded and PRIVATE_RIGHT not in encoded
    assert '"private_inputs":' not in encoded


@pytest.mark.parametrize('provider', PROVIDERS)
@pytest.mark.parametrize('kind', [QueryKind.SATISFIABILITY, QueryKind.THEOREM_PROOF])
@pytest.mark.parametrize('violated', [False, True])
def test_explicit_missing_canonical_engine_fallback_is_bound_and_nonconclusive(fallback_calls, provider, kind, violated):
    req = request(provider, kind=kind, violated=violated); original = req.to_dict()
    owner = reg.default_backend_registry()
    bounded(owner.run(req), req, provider=provider, violated=violated)
    assert req.to_dict() == original
    assert len(fallback_calls) == 1
    assert fallback_calls[0][0] == ('hyperltl' if provider == FAMILY else provider)
    assert fallback_calls[0][1] is not None
    assert owner.is_available(provider) is False
    assert budget.current_proof_operation() is None


@pytest.mark.parametrize('flag', [MISSING, False, None, 0, 1, 'true'])
def test_permission_requires_exact_true_and_is_never_inferred_from_traces(fallback_calls, flag):
    req = request(allow=flag)
    unavailable(reg.default_backend_registry().run(req), req)
    assert not fallback_calls


@pytest.mark.parametrize('traces', [None, (), [], {}, 'trace:fake'])
def test_absent_empty_or_wrong_trace_container_does_not_create_missing_tool_exemption(fallback_calls, traces):
    req = request(traces=traces)
    unavailable(reg.default_backend_registry().run(req), req)
    assert not fallback_calls


@pytest.mark.parametrize('value', [False, None, 0, 'available', 'raises'])
def test_explicit_caller_availability_probe_retains_veto_without_constructing(value, fallback_calls):
    calls = []
    def probe():
        calls.append('probe')
        if value == 'raises':
            raise OSError('controlled probe refusal')
        return value
    wrapper, owner = lane(factory=lambda: pytest.fail('vetoed factory was called'), availability_probe=probe)
    req = request()
    unavailable(owner.run(req), req)
    assert calls == ['probe'] and not fallback_calls and not wrapper._delegate_loaded


@pytest.mark.parametrize('scope', ['instance', 'class'])
def test_custom_wrapper_availability_false_is_an_explicit_veto(monkeypatch, fallback_calls, scope):
    wrapper, owner = lane(factory=lambda: pytest.fail('vetoed wrapper constructed a delegate'))
    visits = []
    def refuse(*args):
        visits.append(True)
        return False
    if scope == 'instance':
        monkeypatch.setattr(wrapper, 'is_available', refuse)
    else:
        monkeypatch.setattr(reg.LazyMatrixProofBackend, 'is_available', refuse)
    req = request()
    unavailable(owner.run(req), req)
    assert visits == [True] and not fallback_calls


@pytest.mark.parametrize('method', ['is_available', 'probe'])
@pytest.mark.parametrize('scope', ['instance', 'class'])
def test_custom_delegate_availability_or_probe_never_enables_exception(monkeypatch, fallback_calls, method, scope):
    delegate = hyper.HyperLTLBackend()
    visits = []
    def refuse(*args):
        visits.append(True)
        return False
    monkeypatch.setattr(delegate if scope == 'instance' else hyper.HyperpropertyBackend, method, refuse)
    _, owner = lane(delegate)
    req = request()
    unavailable(owner.run(req), req)
    assert not fallback_calls
    if method == 'is_available':
        assert visits == [True]


@pytest.mark.parametrize('kind', ['opaque', 'subclass', 'wrong-engine', 'wrong-capability', 'no-fallback'])
def test_only_exact_matching_canonical_delegate_can_gain_missing_tool_permission(fallback_calls, kind):
    if kind == 'opaque':
        delegate = SimpleNamespace(is_available=lambda: False, probe=lambda: False, run=forbidden)
    elif kind == 'subclass':
        class Custom(hyper.HyperLTLBackend):
            pass
        delegate = Custom()
    else:
        delegate = hyper.HyperLTLBackend()
        if kind == 'wrong-engine':
            delegate.engine = hyper.HyperEngine.AUTOHYPER
        elif kind == 'wrong-capability':
            delegate.capability = hyper.AutoHyperBackend.capability
        else:
            delegate.capability = replace(delegate.capability, supports_self_composition_fallback=False)
    _, owner = lane(delegate); req = request()
    unavailable(owner.run(req), req)
    assert not fallback_calls


@pytest.mark.parametrize('kind', ['none', 'raise'])
def test_absent_or_failed_factory_remains_unavailable_and_keeps_existing_cache(fallback_calls, kind):
    visits = []
    def factory():
        visits.append(True)
        if kind == 'raise':
            raise ImportError('controlled factory failure')
        return None
    _, owner = lane(factory=factory); req = request()
    unavailable(owner.run(req), req); unavailable(owner.run(req), req)
    assert visits == [True] and not fallback_calls


def test_canonical_discovery_exception_is_not_treated_as_missing_tool_and_can_recover(fallback_calls):
    visits = []
    failing = [True]
    def which(name):
        visits.append(name)
        if failing[0]:
            raise OSError('controlled discovery failure')
        return None
    delegate = hyper.HyperLTLBackend(which=which)
    _, owner = lane(delegate); req = request()
    unavailable(owner.run(req), req)
    assert len(visits) == 1 and not fallback_calls
    failing[0] = False
    bounded(owner.run(req), req, provider='hyperltl', violated=True)
    assert len(fallback_calls) == 1


@pytest.mark.parametrize('changed', ['entry-family', 'factory-key', 'provider-id'])
def test_noncanonical_matrix_entries_do_not_gain_the_hyper_exemption(fallback_calls, changed):
    declaration = entry()
    if changed == 'entry-family':
        declaration = replace(declaration, family=reg.PROVIDER_MATRIX_FAMILY_STATE_MODEL)
    elif changed == 'factory-key':
        declaration = replace(declaration, factory_key='custom-hyper')
    else:
        declaration = replace(declaration, provider_id='custom-hyper')
    _, owner = lane(hyper.HyperLTLBackend(), selected_entry=declaration)
    req = replace(request(), requested_backend_id=declaration.provider_id)
    unavailable(owner.run(req), req)
    assert not fallback_calls


@pytest.mark.parametrize('changed', ['logic-family', 'query-kind', 'requested-id'])
def test_unsupported_requests_are_rejected_before_factory_or_availability(changed, fallback_calls):
    selected, owner = lane(factory=lambda: pytest.fail('unsupported request loaded a delegate'))
    req = request()
    if changed == 'logic-family':
        req = replace(req, logic_family='linear_temporal_logic')
    elif changed == 'query-kind':
        req = replace(req, query_kind=QueryKind.RUNTIME_MONITOR)
    else:
        req = replace(req, requested_backend_id='autohyper')
        with pytest.raises(reg.BackendRegistryError, match='conflicts'):
            owner.run(req, backend_id='hyperltl')
        assert not fallback_calls and not selected._delegate_loaded
        return
    attempt, value = selected.run(req)
    assert attempt.status.value == 'failed' and value.status.value == 'error'
    assert 'result' not in value.payload and not fallback_calls


@pytest.mark.parametrize('kind', ['missing-id', 'malformed-field', 'record-cap'])
def test_selected_delegate_rejects_malformed_or_excessive_traces_without_native_work(monkeypatch, kind):
    if kind == 'missing-id':
        rows = [{'public_inputs': {}}]
    elif kind == 'malformed-field':
        rows = [{'trace_id': 'trace:bad', 'private_inputs': [PRIVATE_LEFT]}]
    else:
        rows = [trace_mapping(value) for value in pair()]
    req = request(traces=rows)
    if kind == 'record-cap':
        monkeypatch.setattr(core, 'MAX_EVALUATION_INPUT_TRACES', 1)
    attempt, value = reg.default_backend_registry().run(req)
    assert attempt.status.value == 'failed' and value.status.value == 'error'
    assert 'result' not in value.payload
    assert PRIVATE_LEFT not in json.dumps(value.to_dict(), sort_keys=True)


def test_discovery_remains_false_and_cataloging_never_constructs_fallback(monkeypatch):
    visits = []
    original = hyper.HyperpropertyBackend.__init__
    def construct(*args, **kwargs):
        visits.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(hyper.HyperpropertyBackend, '__init__', construct)
    owner = reg.default_backend_registry()
    catalog = reg.declared_backend_catalog(owner)
    assert not visits
    assert next(v for v in catalog if v['provider_id'] == 'hyperltl')['availability'] == 'declared'
    assert owner.is_available('hyperltl') is False and visits == [True]
    assert owner.is_available('hyperltl') is False and visits == [True]


def test_canonical_availability_runs_once_then_actual_probe_runs_inside_adapter(fallback_calls):
    req = request(); counts = {'availability': 0, 'probe': 0}
    codes = {hyper.HyperpropertyBackend.is_available.__code__: 'availability',
             hyper.HyperpropertyBackend.probe.__code__: 'probe'}
    def observe(frame, event, value):
        if event == 'call' and frame.f_code in codes:
            counts[codes[frame.f_code]] += 1
    assert sys.getprofile() is None
    sys.setprofile(observe)
    try:
        bounded(reg.default_backend_registry().run(req), req, provider='hyperltl', violated=True)
    finally:
        sys.setprofile(None)
    assert counts == {'availability': 1, 'probe': 1}
    assert len(fallback_calls) == 1


def test_fallback_permission_is_request_local_on_a_reused_delegate(fallback_calls):
    owner = reg.default_backend_registry(); permitted = request()
    denied = request(allow=False)
    bounded(owner.run(permitted), permitted, provider='hyperltl', violated=True)
    unavailable(owner.run(denied), denied)
    unavailable(owner.run(request(traces=[])), request(traces=[]))
    bounded(owner.run(permitted), permitted, provider='hyperltl', violated=True)
    assert len(fallback_calls) == 2


@pytest.mark.parametrize('phase', ['factory', 'discovery', 'evaluation'])
@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
def test_shared_operation_stops_setup_and_fallback_without_late_result(monkeypatch, clock, phase, stop):
    signal = threading.Event(); touched = []
    def trigger():
        touched.append(phase)
        if stop == 'cancel':
            signal.set()
        else:
            clock[0] += 2
    def which(name):
        if phase == 'discovery':
            trigger()
        return None
    delegate = hyper.HyperLTLBackend(which=which)
    def factory():
        if phase == 'factory':
            trigger()
        return delegate
    if phase == 'evaluation':
        original = core._projection
        def projection(*args):
            trigger()
            return original(*args)
        monkeypatch.setattr(core, '_projection', projection)
    _, owner = lane(factory=factory); req = request(timeout_ms=1000)
    attempt, value = owner.run(req, cancellation=signal)
    assert touched and attempt.status.value == ('cancelled' if stop == 'cancel' else 'timed_out')
    assert value.status.value == 'unknown' and 'result' not in value.payload
    assert attempt.request_digest == value.request_digest == req.digest
    assert budget.current_proof_operation() is None


def test_precancelled_registry_does_not_construct_or_probe():
    signal = threading.Event(); signal.set()
    _, owner = lane(factory=lambda: pytest.fail('pre-cancelled factory ran'))
    req = request(); attempt, value = owner.run(req, cancellation=signal)
    assert attempt.status.value == 'cancelled' and value.status.value == 'unknown'
    assert budget.current_proof_operation() is None


def test_interrupted_factory_is_retried_for_a_fresh_request(clock, fallback_calls):
    visits = []
    delegate = hyper.HyperLTLBackend()
    def factory():
        visits.append(True)
        if len(visits) == 1:
            clock[0] += 2
        return delegate
    _, owner = lane(factory=factory); req = request(timeout_ms=1000)
    attempt, _ = owner.run(req)
    assert attempt.status.value == 'timed_out' and not fallback_calls
    bounded(owner.run(req), req, provider='hyperltl', violated=True)
    assert visits == [True, True] and len(fallback_calls) == 1


def test_concurrent_permission_does_not_leak_from_fallback_into_refused_request(monkeypatch, fallback_calls):
    owner = reg.default_backend_registry()
    permitted, refused = request(timeout_ms=5000), request(allow=False, timeout_ms=5000)
    entered, release = threading.Event(), threading.Event()
    outcome = {}; errors = []
    original = core._projection
    def wait_for_peer(*args):
        entered.set()
        if not release.wait(timeout=2):
            raise AssertionError('bounded fixture synchronization timed out')
        return original(*args)
    monkeypatch.setattr(core, '_projection', wait_for_peer)
    def worker():
        try:
            outcome['pair'] = owner.run(permitted)
        except BaseException as error:
            errors.append(error)
    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert entered.wait(timeout=2)
        unavailable(owner.run(refused), refused)
    finally:
        release.set()
        thread.join(timeout=2)
    assert not thread.is_alive() and not errors
    bounded(outcome['pair'], permitted, provider='hyperltl', violated=True)
    assert len(fallback_calls) == 1 and budget.current_proof_operation() is None


@pytest.mark.parametrize('provider', BACKENDS)
def test_available_native_engine_keeps_default_admission_instead_of_fallback(private_native, fallback_calls, provider):
    private_native.action[0] = lambda invocation, signal: process.RawProcessResult(
        returncode=0, stdout=SUCCESS[provider])
    req = request(provider)
    attempt, value = reg.default_backend_registry().run(req)
    assert attempt.status.value == 'succeeded' and value.status.value == 'unknown'
    assert value.payload['result']['status'] == 'satisfied'
    assert value.payload['result']['metadata']['evidence_path'] == 'engine'
    assert value.payload['result']['metadata']['process']['workspace_cleaned']
    assert not fallback_calls
    assert len(private_native.calls) == len(private_native.prepared) == len(private_native.acquired) == 1
    assert private_native.acquired[0].released


def test_tool_appearing_after_missing_guard_still_requires_native_admission(private_native, fallback_calls):
    lookups = []
    missing_candidates = len(hyper.HyperLTLBackend.capability.executable_candidates)
    def which(name):
        lookups.append(name)
        return None if len(lookups) <= missing_candidates else sys.executable
    delegate = hyper.HyperLTLBackend(which=which)
    _, owner = lane(delegate)
    req = request()
    attempt, value = owner.run(req)
    assert lookups[:missing_candidates] == list(delegate.capability.executable_candidates)
    assert len(lookups) > missing_candidates
    assert attempt.status.value == 'succeeded' and value.status.value == 'unknown'
    assert value.payload['result']['status'] == 'satisfied'
    assert value.payload['result']['metadata']['evidence_path'] == 'engine'
    assert value.payload['result']['metadata']['process']['workspace_cleaned']
    assert not fallback_calls
    assert len(private_native.calls) == len(private_native.prepared) == len(private_native.acquired) == 1
    assert private_native.acquired[0].released
