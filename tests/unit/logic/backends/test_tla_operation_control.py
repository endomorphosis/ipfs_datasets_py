"""Whole TLA operations share setup, execution, and publication controls.

Native executors are synthetic. Admission tests use their own on-disk scheduler;
no host tools or shared pool are consulted.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields, replace
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process, resource_admission
from ipfs_datasets_py.logic.backends.installers import state_model
from ipfs_datasets_py.logic.backends.smt import operation_budget as budget
from ipfs_datasets_py.logic.backends.tla import execution_v2 as v2, runners
from ipfs_datasets_py.logic.backends.tla.compiler import GeneratedTLAArtifacts, TLACompileBounds, TLASourceMapEntry
from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest, ExecutionBounds, QueryKind
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources

MIB = 1024**2
SUCCESS = "Model checking completed. No error has been found.\nChecker reports no error\n"
TRACE = ("Error: Invariant Safety is violated.\nThe following behavior constitutes a counter-example:\n"
         "State 1: <Initial predicate>\n/\\ n = 0\nState 2: <Next>\n/\\ n = 4\n")
HELP = "TLC - provides model checking and simulation of TLA+ specifications - Version 2026.07.31\nSYNOPSIS\nDESCRIPTION\n"


def artifacts():
    return GeneratedTLAArtifacts(module_name="OperationCounter",
        model_text="---- MODULE OperationCounter ----\nEXTENDS Integers\nVARIABLE n\nInit == n = 0\nNext == n < 4 /\\ n' = n + 1\nSpec == Init /\\ [][Next]_n\nSafety == n \\in 0..3\n====\n",
        tlc_config_text="SPECIFICATION Spec\nINVARIANT Safety\nCHECK_DEADLOCK FALSE\n",
        apalache_config_text="INIT Init\nNEXT Next\nINVARIANT Safety\n",
        source_map=(TLASourceMapEntry("state:n", "state_variable", "n", "variable"),),
        losses=(), bounds=TLACompileBounds(max_steps=4), source_document_id="test:operation-counter",
        source_kind="state_transition", safety_properties=("Safety",), liveness_properties=(),
        fairness_limitations=("Only the declared finite bounds were explored.",))


def bounds(timeout_ms=1000):
    return ExecutionBounds(timeout_ms=timeout_ms, max_memory_bytes=128*MIB, max_steps=4, max_output_bytes=65536)


def request(timeout_ms=1000, **payload):
    return BackendRequest(request_id="request:tla:operation", claim_id="claim:counter",
        declaration_id="declaration:counter", claim_digest="1"*64, obligation_id="obligation:counter",
        obligation_digest="2"*64, assumption_ids=("assumption:finite-counter",),
        logic_family="state_transition", query_kind=QueryKind.SATISFIABILITY,
        bounds=bounds(timeout_ms), payload=payload)


def state_request(timeout_ms=1000, provider="tlc", **kwargs):
    options = {"artifacts": artifacts(), **kwargs}
    return v2.StateExecutionRequestV2(request_id="request:state:operation", provider=provider,
                                    bounds=bounds(timeout_ms), **options)


@pytest.fixture(autouse=True)
def no_host_work(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("operation-control fixtures must not start host tools or consult the shared pool")
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(process.SubprocessExecutor, "execute", denied)
    monkeypatch.setattr(resource_admission, "get_global_resource_scheduler", denied)


@pytest.fixture
def clock(monkeypatch):
    value = [100.0]
    fake = SimpleNamespace(monotonic=lambda: value[0])
    for module in (budget, runners, state_model, resource_admission):
        monkeypatch.setattr(module, "time", fake)
    return value


class FixtureCompiler:
    bounds = TLACompileBounds(max_steps=4)
    def __init__(self, action=None):
        self.calls = []
        self.action = action

    def compile(self, document, *, module_name="StateModel"):
        self.calls.append((document, module_name))
        if self.action:
            self.action()
        return artifacts()


@pytest.fixture
def backend_factory(tmp_path):
    workspaces, all_calls = [], []
    def make(kind=runners.TLCBackend, *, verdict="pass", action=None, compiler=None, backend_type=None,
             version_banner=None):
        calls = []
        def execute(invocation, cancellation):
            phase = "version" if invocation.argv[-1] in ("-help", "version") else "model"
            calls.append((phase, invocation, cancellation))
            all_calls.append((kind, phase))
            workspaces.append(invocation.cwd)
            assert invocation.cwd.is_dir()
            if action:
                action(phase, invocation, cancellation)
            if phase == "version":
                return process.RawProcessResult(returncode=1 if kind is runners.TLCBackend else 0,
                    stdout=version_banner if version_banner is not None else
                        HELP if kind is runners.TLCBackend else "0.58.3\n")
            return process.RawProcessResult(returncode=12 if verdict == "counterexample" else 0,
                stdout=TRACE if verdict == "counterexample" else SUCCESS)
        runner = process.BoundedToolRunner(executor=execute, workspace_root=tmp_path)
        backend = (backend_type or kind)(runner=runner, executable=sys.executable,
            jvm_probe=lambda: True, lazy_install=False, compiler=compiler)
        return backend, calls
    make.all_calls = all_calls
    yield make
    assert all(not path.exists() for path in workspaces)


def engine_from(factory, **kwargs):
    tlc, tlc_calls = factory()
    apalache, apalache_calls = factory(runners.ApalacheBackend)
    return v2.StateExecutionEngineV2(tlc=tlc, apalache=apalache, **kwargs), tlc_calls, apalache_calls


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "10", 2**31, float("nan")])
@pytest.mark.parametrize("route", ["constructor", "execute", "split", "helper", "compile", "run"])
def test_invalid_operation_controls_fail_before_callbacks(backend_factory, bad, route):
    compiler = FixtureCompiler(lambda: pytest.fail("invalid control compiled"))
    backend, calls = backend_factory(compiler=compiler)
    engine = v2.StateExecutionEngineV2(tlc=backend, apalache=backend_factory(runners.ApalacheBackend)[0])
    with pytest.raises(ValueError, match="operation_timeout_ms"):
        if route == "constructor":
            v2.StateExecutionEngineV2(operation_timeout_ms=bad)
        elif route == "execute":
            engine.execute(state_request(), operation_timeout_ms=bad)
        elif route == "split":
            engine.execute_split_providers(artifacts=artifacts(), operation_timeout_ms=bad)
        elif route == "helper":
            v2.execute_tlc(artifacts=artifacts(), engine=engine, operation_timeout_ms=bad)
        elif route == "compile":
            backend.compile_and_check(object(), operation_timeout_ms=bad)
        else:
            backend.run(request(document={}), operation_timeout_ms=bad)
    assert calls == compiler.calls == []


def test_v2_constructor_is_pure_but_rejects_wrong_injected_backend_immediately(monkeypatch):
    monkeypatch.setattr(state_model, "probe_java_runtime", lambda **k: pytest.fail("constructor probed Java"))
    engine = v2.StateExecutionEngineV2()
    assert engine is not None
    for field in ("tlc", "apalache"):
        with pytest.raises(v2.StateExecutionError, match=field):
            v2.StateExecutionEngineV2(**{field: object()})


@pytest.mark.parametrize("route", ["compile", "run", "execute", "helper", "split"])
def test_precancel_prevents_compilation_setup_and_execution(backend_factory, route):
    token = threading.Event()
    token.set()
    compiler = FixtureCompiler(lambda: pytest.fail("pre-cancelled compile"))
    backend, calls = backend_factory(compiler=compiler)
    engine = v2.StateExecutionEngineV2(tlc=backend, apalache=backend_factory(runners.ApalacheBackend)[0], compiler=compiler)
    with pytest.raises(budget.ProofOperationCancelled):
        if route == "compile":
            backend.compile_and_check(object(), cancellation=token)
        elif route == "run":
            backend.run(request(document={}), cancellation=token)
        elif route == "execute":
            engine.execute(state_request(artifacts=None, document={}), cancellation=token)
        elif route == "helper":
            v2.execute_tlc(document={}, engine=engine, cancellation=token)
        else:
            engine.execute_split_providers(document={}, cancellation=token)
    assert calls == compiler.calls == []


@pytest.mark.parametrize("route", ["compile", "run", "execute", "helper"])
@pytest.mark.parametrize("stop", ["deadline", "cancel"])
def test_compiler_time_is_inside_default_operation_budget(backend_factory, clock, route, stop):
    token = threading.Event()
    def interrupt():
        if stop == "cancel":
            token.set()
        else:
            clock[0] += 1.1
    compiler = FixtureCompiler(interrupt)
    backend, calls = backend_factory(compiler=compiler)
    engine = v2.StateExecutionEngineV2(tlc=backend, apalache=backend_factory(runners.ApalacheBackend)[0], compiler=compiler)
    expected = budget.ProofOperationCancelled if stop == "cancel" else budget.ProofOperationTimeout
    with pytest.raises(expected):
        if route == "compile":
            backend.compile_and_check(object(), request=request(), cancellation=token)
        elif route == "run":
            backend.run(request(document={}), cancellation=token)
        elif route == "execute":
            engine.execute(state_request(artifacts=None, document={}), cancellation=token)
        else:
            v2.execute_tlc(document={}, bounds=bounds(), engine=engine, cancellation=token)
    assert len(compiler.calls) == 1
    assert calls == []


@pytest.mark.parametrize("route", ["compile", "run", "execute"])
def test_compile_cost_shrinks_native_phase_deadlines_but_preserves_declared_bounds(backend_factory, clock, route):
    compiler = FixtureCompiler(lambda: clock.__setitem__(0, clock[0] + .25))
    def spend(phase, invocation, cancellation):
        assert cancellation is not None
        clock[0] += .25 if phase == "model" else .05
    backend, calls = backend_factory(compiler=compiler, action=spend)
    req = request(document={})
    if route == "compile":
        result = backend.compile_and_check({}, request=req)
    elif route == "run":
        result = backend.run(req)
    else:
        engine = v2.StateExecutionEngineV2(tlc=backend, apalache=backend_factory(runners.ApalacheBackend)[0], compiler=compiler)
        result = engine.execute(state_request(artifacts=None, document={}))
    assert [row[0] for row in calls] == ["model", "version"]
    assert 0 < calls[0][1].limits.timeout_seconds <= .750001
    assert 0 < calls[1][1].limits.timeout_seconds <= .500001
    assert req.bounds.timeout_ms == 1000
    if route == "execute":
        assert result.evidence.bounds.timeout_ms == 1000
        assert result.evidence.model_check_established
    else:
        assert result.receipt.timeout_seconds == 1.0
        assert result.receipt.status is runners.ModelCheckOutcomeStatus.PASSED


@pytest.mark.parametrize("verdict", ["pass", "counterexample"])
@pytest.mark.parametrize("phase", ["model", "version"])
def test_ambient_deadline_blocks_late_model_or_version_conclusion(backend_factory, clock, verdict, phase):
    def late(actual, *_):
        if actual == phase:
            clock[0] += 1.0
    backend, calls = backend_factory(verdict=verdict, action=late)
    with pytest.raises(budget.ProofOperationTimeout):
        with budget.proof_operation_scope(timeout_ms=500):
            backend.check(artifacts(), request=request(5000))
    assert [row[0] for row in calls] == (["model"] if phase == "model" else ["model", "version"])


def test_ambient_observed_cancellation_stays_latched_after_event_clear(backend_factory):
    token = threading.Event()
    def cancel_once(phase, invocation, signal):
        assert phase == "model"
        token.set()
        assert signal.is_set()
        token.clear()
    backend, calls = backend_factory(action=cancel_once)
    with pytest.raises(budget.ProofOperationCancelled):
        with budget.proof_operation_scope(timeout_ms=1000, cancellation=token):
            backend.check(artifacts(), request=request())
    assert not token.is_set()
    assert [row[0] for row in calls] == ["model"]


@pytest.mark.parametrize("route", ["execute", "helper", "split"])
def test_nested_larger_override_cannot_extend_parent_budget(backend_factory, clock, route):
    def late(*_):
        clock[0] += .25
    backend, calls = backend_factory(action=late)
    engine = v2.StateExecutionEngineV2(tlc=backend, apalache=backend_factory(runners.ApalacheBackend)[0], operation_timeout_ms=5000)
    with pytest.raises(budget.ProofOperationTimeout):
        with budget.proof_operation_scope(timeout_ms=100):
            if route == "execute":
                engine.execute(state_request(5000), operation_timeout_ms=9000)
            elif route == "helper":
                v2.execute_tlc(artifacts=artifacts(), engine=engine, bounds=bounds(5000), operation_timeout_ms=9000)
            else:
                engine.execute_split_providers(artifacts=artifacts(), bounds=bounds(5000), operation_timeout_ms=9000)
    assert len(calls) == 1
    assert calls[0][1].limits.timeout_seconds <= .100001


def test_child_expiry_revokes_parent_even_if_inner_error_is_caught(backend_factory, clock):
    backend, _ = backend_factory(action=lambda *_: clock.__setitem__(0, clock[0] + .2))
    engine = v2.StateExecutionEngineV2(tlc=backend, apalache=backend_factory(runners.ApalacheBackend)[0])
    with pytest.raises(budget.ProofOperationTimeout):
        with budget.proof_operation_scope(timeout_ms=5000):
            with pytest.raises(budget.ProofOperationTimeout):
                engine.execute(state_request(), operation_timeout_ms=100)


@pytest.mark.parametrize("phase", ["capability", "compile", "binding", "result"])
@pytest.mark.parametrize("verdict", ["pass", "counterexample"])
@pytest.mark.parametrize("stop", ["deadline", "cancel"])
def test_v2_outer_gate_withholds_late_bindings_and_results(backend_factory, clock, monkeypatch, phase, verdict, stop):
    token = threading.Event()
    backend, calls = backend_factory(verdict=verdict)
    compiler = FixtureCompiler()
    engine = v2.StateExecutionEngineV2(tlc=backend, apalache=backend_factory(runners.ApalacheBackend)[0], compiler=compiler)
    def trip():
        if stop == "cancel":
            token.set()
        else:
            clock[0] += 2.0
    if phase == "capability":
        original = engine.capability_receipt
        def delayed(*args, **kwargs):
            value = original(*args, **kwargs)
            trip()
            return value
        monkeypatch.setattr(engine, "capability_receipt", delayed)
    elif phase == "compile":
        compiler.action = trip
    elif phase == "binding":
        original = v2.StateCounterexampleBindingV2.from_trace.__func__
        def delayed(cls, *args, **kwargs):
            value = original(cls, *args, **kwargs)
            trip()
            return value
        monkeypatch.setattr(v2.StateCounterexampleBindingV2, "from_trace", classmethod(delayed))
    else:
        original = v2.StateExecutionResultV2.__post_init__
        def delayed(self):
            original(self)
            trip()
        monkeypatch.setattr(v2.StateExecutionResultV2, "__post_init__", delayed)
    expected = budget.ProofOperationCancelled if stop == "cancel" else budget.ProofOperationTimeout
    with pytest.raises(expected):
        engine.execute(state_request(artifacts=None, document={}), cancellation=token)
    assert len(calls) == (0 if phase in {"capability", "compile"} else 2)


@pytest.mark.parametrize("stop", ["deadline", "cancel"])
def test_split_never_starts_second_provider_after_first_whole_result_stops(backend_factory, clock, monkeypatch, stop):
    token = threading.Event()
    engine, tlc_calls, apalache_calls = engine_from(backend_factory)
    original = engine._from_outcome
    def stop_after_result(*args, **kwargs):
        result = original(*args, **kwargs)
        if stop == "cancel":
            token.set()
        else:
            clock[0] += 1.1
        return result
    monkeypatch.setattr(engine, "_from_outcome", stop_after_result)
    expected = budget.ProofOperationCancelled if stop == "cancel" else budget.ProofOperationTimeout
    with pytest.raises(expected):
        engine.execute_split_providers(artifacts=artifacts(), bounds=bounds(), cancellation=token)
    assert len(tlc_calls) == 2 and apalache_calls == []


def test_per_call_override_replaces_constructor_timeout_and_combines_signals(backend_factory, clock):
    configured, supplied = threading.Event(), threading.Event()
    backend, calls = backend_factory(action=lambda *_: clock.__setitem__(0, clock[0] + .1))
    engine = v2.StateExecutionEngineV2(tlc=backend, apalache=backend_factory(runners.ApalacheBackend)[0],
                                     operation_timeout_ms=50, cancellation=configured)
    assert engine.execute(state_request(), operation_timeout_ms=500).evidence.model_check_established
    assert len(calls) == 2
    for token in (configured, supplied):
        token.set()
        with pytest.raises(budget.ProofOperationCancelled):
            engine.execute(state_request(), operation_timeout_ms=500, cancellation=supplied)
        token.clear()
    assert len(calls) == 2


def test_engine_reuse_does_not_keep_previous_stop_state(backend_factory):
    engine, calls, _ = engine_from(backend_factory)
    token = threading.Event()
    token.set()
    with pytest.raises(budget.ProofOperationCancelled):
        engine.execute(state_request(), cancellation=token)
    token.clear()
    assert engine.execute(state_request(), cancellation=token).evidence.model_check_established
    assert len(calls) == 2


def test_shared_engine_threads_have_independent_operation_signals(backend_factory):
    rendezvous = threading.Barrier(2)
    local = threading.local()
    def meet(phase, invocation, signal):
        if phase == "model":
            rendezvous.wait(timeout=3)
            if local.should_stop:
                local.token.set()
                assert signal.is_set()
                local.token.clear()
    backend, calls = backend_factory(action=meet)
    engine = v2.StateExecutionEngineV2(tlc=backend, apalache=backend_factory(runners.ApalacheBackend)[0])
    def execute(stop):
        local.should_stop, local.token = stop, threading.Event()
        try:
            return engine.execute(state_request(5000), cancellation=local.token).evidence.model_check_established
        except budget.ProofOperationCancelled:
            return "cancelled"
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(execute, stop) for stop in (True, False)]
        assert [future.result(timeout=5) for future in futures] == ["cancelled", True]
    assert [phase for phase, *_ in calls].count("model") == 2
    assert [phase for phase, *_ in calls].count("version") == 1


@pytest.mark.parametrize("error_type", [TypeError, RuntimeError])
def test_legacy_execute_override_is_called_once_without_new_keywords(backend_factory, error_type):
    calls = []
    failure = error_type("opaque execution callback failed")
    class Legacy(v2.StateExecutionEngineV2):
        def execute(self, request):
            calls.append(request)
            raise failure
    engine = Legacy(tlc=backend_factory()[0], apalache=backend_factory(runners.ApalacheBackend)[0])
    with pytest.raises(error_type) as caught:
        v2.execute_tlc(artifacts=artifacts(), engine=engine, operation_timeout_ms=1000)
    assert caught.value is failure
    assert len(calls) == 1


def test_legacy_check_override_keeps_identity_and_late_result_is_refused(backend_factory, clock):
    calls = []
    class Legacy(runners.TLCBackend):
        def check(self, artifacts, *, request=None):
            calls.append(request)
            value = super().check(artifacts, request=request)
            clock[0] += 2.0
            return value
    backend, native = backend_factory(backend_type=Legacy)
    engine = v2.StateExecutionEngineV2(tlc=backend, apalache=backend_factory(runners.ApalacheBackend)[0])
    assert engine.backend("tlc") is backend
    with pytest.raises(budget.ProofOperationTimeout):
        engine.execute(state_request())
    assert len(calls) == 1 and len(native) == 2


def test_version_callback_cannot_swallow_latched_ambient_interruption(backend_factory):
    token = threading.Event()
    def fail(phase, invocation, signal):
        if phase == "version":
            token.set()
            assert signal.is_set()
            token.clear()
            raise OSError("version callback failed after stop")
    backend, calls = backend_factory(action=fail)
    with pytest.raises(budget.ProofOperationCancelled):
        with budget.proof_operation_scope(timeout_ms=1000, cancellation=token):
            backend.check(artifacts(), request=request())
    assert len(calls) == 2


def test_controls_do_not_enter_wire_schema_or_request_digest(backend_factory, clock):
    engine, _, _ = engine_from(backend_factory)
    req = state_request()
    before = req.to_dict()
    plain = engine.execute(req).to_dict()
    controlled = engine.execute(req, operation_timeout_ms=2000, cancellation=threading.Event()).to_dict()
    assert req.to_dict() == before
    assert plain == controlled
    assert {"operation_timeout_ms", "cancellation"}.isdisjoint({field.name for field in fields(v2.StateExecutionRequestV2)})
    assert "operation_timeout_ms" not in json.dumps(controlled)
    assert "cancellation" not in json.dumps(controlled)


@pytest.mark.parametrize("route", ["execute-mapping", "helper"])
@pytest.mark.parametrize("stop", ["deadline", "cancel"])
def test_request_normalization_is_inside_budget_before_any_capability(backend_factory, clock, monkeypatch, route, stop):
    token = threading.Event()
    engine, calls, other = engine_from(backend_factory)
    payload = {"request_id": "request:normalization", "provider": "tlc", "artifacts": artifacts(), "bounds": bounds()}
    original = v2.StateExecutionRequestV2.__post_init__
    def delayed(self):
        original(self)
        if stop == "cancel":
            token.set()
        else:
            clock[0] += 1.1
    monkeypatch.setattr(v2.StateExecutionRequestV2, "__post_init__", delayed)
    monkeypatch.setattr(engine, "capability_receipt", lambda *a, **k: pytest.fail("late normalization probed provider"))
    expected = budget.ProofOperationCancelled if stop == "cancel" else budget.ProofOperationTimeout
    with pytest.raises(expected):
        if route == "execute-mapping":
            engine.execute(payload, cancellation=token)
        else:
            v2.execute_tlc(artifacts=artifacts(), engine=engine, bounds=bounds(), cancellation=token)
    assert calls == other == []


@pytest.mark.parametrize("stop", ["deadline", "cancel"])
def test_opaque_install_callback_is_guarded_and_late_tool_never_runs(backend_factory, clock, monkeypatch, stop):
    from ipfs_datasets_py.logic.external_provers import lazy_installer
    token, installs = threading.Event(), []
    backend, native = backend_factory()
    backend._executable = None
    backend._which = lambda _: None
    backend._lazy_install = True
    def install(*args, **kwargs):
        installs.append((args, kwargs))
        if stop == "cancel":
            token.set()
        else:
            clock[0] += 1.1
        return sys.executable
    monkeypatch.setattr(lazy_installer, "ensure_prover_executable", install)
    expected = budget.ProofOperationCancelled if stop == "cancel" else budget.ProofOperationTimeout
    with pytest.raises(expected):
        backend.run(request(artifacts=artifacts().to_dict()), cancellation=token)
    assert len(installs) == 1
    assert native == []


def test_helper_outer_gate_rejects_legacy_callback_late_clean_result(backend_factory, clock):
    callbacks = []
    class Legacy(v2.StateExecutionEngineV2):
        def execute(self, request):
            callbacks.append(request)
            result = super().execute(request)
            clock[0] += 2.0
            return result
    engine = Legacy(tlc=backend_factory()[0], apalache=backend_factory(runners.ApalacheBackend)[0])
    with pytest.raises(budget.ProofOperationTimeout):
        v2.execute_tlc(artifacts=artifacts(), bounds=bounds(), engine=engine)
    assert len(callbacks) == 1


def test_capability_probe_swallowing_callback_error_still_propagates_latched_stop(backend_factory):
    token = threading.Event()
    backend, native = backend_factory()
    count = []
    def jvm():
        count.append(1)
        if len(count) == 2:
            token.set()
            assert budget.current_proof_operation().is_set()
            token.clear()
            raise RuntimeError("opaque capability callback failed after interruption")
        return True
    backend._jvm_probe = jvm
    engine = v2.StateExecutionEngineV2(tlc=backend, apalache=backend_factory(runners.ApalacheBackend)[0])
    with pytest.raises(budget.ProofOperationCancelled):
        engine.execute(state_request(), cancellation=token)
    assert len(count) == 2
    assert native == []


def test_split_second_provider_gets_only_aggregate_remaining_time(backend_factory, clock):
    first, first_calls = backend_factory(action=lambda *_: clock.__setitem__(0, clock[0] + .3))
    second, second_calls = backend_factory(runners.ApalacheBackend,
        action=lambda *_: clock.__setitem__(0, clock[0] + .5))
    engine = v2.StateExecutionEngineV2(tlc=first, apalache=second)
    with pytest.raises(budget.ProofOperationTimeout):
        engine.execute_split_providers(artifacts=artifacts(), bounds=bounds())
    assert [row[0] for row in first_calls] == ["model", "version"]
    assert [row[0] for row in second_calls] == ["model"]
    assert 0 < second_calls[0][1].limits.timeout_seconds <= .400001


@pytest.mark.parametrize("mode", [v2.StateExecutionMode.CAPABILITY_PROBE,
    v2.StateExecutionMode.MOCK, v2.StateExecutionMode.FALLBACK, v2.StateExecutionMode.HERMETIC_FIXTURE])
def test_all_v2_modes_refuse_precancel_without_entering_capability(backend_factory, monkeypatch, mode):
    engine, calls, other = engine_from(backend_factory)
    monkeypatch.setattr(engine, "capability_receipt", lambda *a, **k: pytest.fail("pre-cancel reached capability"))
    token = threading.Event()
    token.set()
    with pytest.raises(budget.ProofOperationCancelled):
        engine.execute(state_request(mode=mode), cancellation=token)
    assert calls == other == []


def test_hermetic_factory_forwards_configured_operation_controls():
    token = threading.Event()
    engine = v2.hermetic_engine(operation_timeout_ms=1000, cancellation=token)
    token.set()
    with pytest.raises(budget.ProofOperationCancelled):
        engine.execute(state_request())
    token.clear()
    assert engine.execute(state_request()).evidence.model_check_established


@pytest.fixture
def admitted_default(tmp_path, monkeypatch):
    host = ProofHostResources(8, 8192, 8192, pid_task_limit=8192, available_pid_tasks=8192)
    current_host = [host]
    def sample():
        if isinstance(current_host[0], Exception):
            raise current_host[0]
        return current_host[0]
    scheduler = resource_scheduler.GlobalResourceScheduler(resource_scheduler.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path/"private-pool.json", proof_resource_sampler=sample,
        total_cpu_slots=2, total_memory_mb=2048, total_child_process_slots=2,
        proof_memory_headroom_mb=64, lane_reservations={}, auto_renew_leases=False,
        poll_interval_seconds=.002))
    monkeypatch.setattr(resource_admission, "get_global_resource_scheduler", lambda: scheduler)
    monkeypatch.setattr(state_model, "resolve_java_executable", lambda *args, **kwargs: (sys.executable, "fixture"))
    calls, workspaces = [], []
    action = [None]
    def execute(executor, invocation, signal):
        phase = "java" if invocation.argv[-1] == "-version" else "version" if invocation.argv[-1] == "-help" else "model"
        leases = scheduler.active_leases()
        assert len(leases) == 1
        assert leases[0]["cpu_slots"] == leases[0]["child_process_slots"] == 1
        assert leases[0]["memory_mb"] == (256 if phase == "java" else 128)
        calls.append((phase, invocation, signal))
        workspaces.append(invocation.cwd)
        if action[0]:
            action[0](phase, invocation, signal)
        return process.RawProcessResult(returncode=1 if phase == "version" else 0,
            stderr='openjdk version "21.0.1"\n' if phase == "java" else "",
            stdout=HELP if phase == "version" else SUCCESS if phase == "model" else "")
    monkeypatch.setattr(process.SubprocessExecutor, "execute", execute)
    yield SimpleNamespace(scheduler=scheduler, calls=calls, action=action, healthy=host, current_host=current_host,
                          engine=lambda **kwargs: v2.StateExecutionEngineV2(which=lambda _: sys.executable,
                                                                          lazy_install=False, **kwargs))
    snapshot = scheduler.snapshot()
    assert snapshot["active_lease_count"] == snapshot["waiting_request_count"] == 0
    assert all(not path.exists() for path in workspaces)


def test_selected_default_java_setup_model_and_version_share_budget_and_admission(admitted_default, clock):
    fixture = admitted_default
    def spend(phase, invocation, signal):
        clock[0] += .2
    fixture.action[0] = spend
    engine = fixture.engine()
    assert fixture.calls == []
    result = engine.execute(state_request())
    assert result.evidence.model_check_established
    assert [phase for phase, *_ in fixture.calls] == ["java", "model", "version"]
    for (_, invocation, _), upper in zip(fixture.calls, (1.0, .8, .6)):
        assert 0 < invocation.limits.timeout_seconds <= upper + .00001
    assert result.evidence.bounds.timeout_ms == 1000


@pytest.mark.parametrize("stop", ["deadline", "cancel"])
def test_interrupted_default_java_setup_never_starts_model_or_unused_provider(admitted_default, clock, stop):
    token = threading.Event()
    def interrupt(phase, invocation, signal):
        assert phase == "java"
        if stop == "cancel":
            token.set()
            assert signal.is_set()
            token.clear()
        else:
            clock[0] += 1.1
    admitted_default.action[0] = interrupt
    expected = budget.ProofOperationCancelled if stop == "cancel" else budget.ProofOperationTimeout
    with pytest.raises(expected):
        admitted_default.engine().execute(state_request(), cancellation=token)
    assert [phase for phase, *_ in admitted_default.calls] == ["java"]


def test_default_backend_context_is_fresh_per_execution_and_injected_ownership_is_unchanged(admitted_default, clock):
    engine = admitted_default.engine()
    assert engine.execute(state_request()).evidence.model_check_established
    assert engine.execute(state_request()).evidence.model_check_established
    assert [phase for phase, *_ in admitted_default.calls] == ["java", "model", "version"]*2


@pytest.mark.parametrize("changes,reason", [
    ({"available_memory_mb": 32}, "proof_memory_headroom"),
    ({"cpu_stall_percent": 90}, "proof_cpu_stall"),
    ({"available_pid_tasks": 0}, "proof_pid_headroom"),
    (None, "proof_resource_telemetry_unknown"),
])
def test_default_setup_pressure_queue_uses_operation_cancellation_and_drains(admitted_default, changes, reason):
    fixture = admitted_default
    fixture.current_host[0] = replace(fixture.healthy, **changes) if changes else OSError("fixture telemetry unavailable")
    token, observed = threading.Event(), []
    engine = fixture.engine()
    def run():
        try:
            engine.execute(state_request(3000), cancellation=token)
        except BaseException as error:
            observed.append(error)
    worker = threading.Thread(target=run)
    worker.start()
    try:
        until = time.monotonic() + 2
        while time.monotonic() < until:
            if fixture.scheduler.snapshot()["proof_backoff"].get("reason") == reason:
                break
            time.sleep(.005)
        else:
            pytest.fail("private pool never observed fixture pressure")
        assert fixture.calls == []
        token.set()
        worker.join(3)
        assert not worker.is_alive()
        assert len(observed) == 1 and isinstance(observed[0], budget.ProofOperationCancelled)
    finally:
        token.set()
        worker.join(3)
    assert fixture.calls == []


def test_default_setup_queue_wait_cannot_reset_operation_deadline(admitted_default):
    fixture = admitted_default
    fixture.current_host[0] = replace(fixture.healthy, available_memory_mb=32)
    with pytest.raises(budget.ProofOperationTimeout):
        fixture.engine().execute(state_request(), operation_timeout_ms=30)
    assert fixture.calls == []


# Exact first 1,024 characters of native-selected/lifecycle-audit.json row 5.
# Its original 11,742-character TLC help response is retained with source and
# prefix hashes in tlc-help-regression-origin.json. Tests need no qualification
# directory at runtime and do not start Java.
RECORDED_TLC_HELP_PREFIX = '\n\x1b[1mNAME\x1b[0m\n\n\tTLC - provides model checking and simulation of TLA+ specifications - Version 2026.07.31.184830\n\n\n\x1b[1mSYNOPSIS\x1b[0m\n\n\t\x1b[1mTLC\x1b[0m [\x1b[1m-h\x1b[0m] [\x1b[1m-cleanup\x1b[0m] [\x1b[1m-continue\x1b[0m] [\x1b[1m-deadlock\x1b[0m] [\x1b[1m-debug\x1b[0m] [\x1b[1m-difftrace\x1b[0m] [\x1b[1m-gzip\x1b[0m] [\x1b[1m-noGenerateSpecTE\x1b[0m] [\x1b[1m-nowarning\x1b[0m] [\x1b[1m-terse\x1b[0m] [\x1b[1m-tool\x1b[0m] [\x1b[1m-view\x1b[0m] [\x1b[1m-checkpoint\x1b[0m \x1b[3mminutes\x1b[0m] [\x1b[1m-config\x1b[0m \x1b[3mfile\x1b[0m] [\x1b[1m-coverage\x1b[0m \x1b[3mminutes\x1b[0m] [\x1b[1m-dfid\x1b[0m \x1b[3mnum\x1b[0m] [\x1b[1m-dump\x1b[0m \x1b[3mformat file\x1b[0m] [\x1b[1m-dumpTrace\x1b[0m \x1b[3mformat file\x1b[0m] [\x1b[1m-fp\x1b[0m \x1b[3mN\x1b[0m] [\x1b[1m-fpbits\x1b[0m \x1b[3mnum\x1b[0m] [\x1b[1m-fpmem\x1b[0m \x1b[3mnum\x1b[0m] [\x1b[1m-inv\x1b[0m \x1b[3mexpr\x1b[0m] [\x1b[1m-invlevel\x1b[0m \x1b[3mn\x1b[0m] [\x1b[1m-loadTrace\x1b[0m \x1b[3mformat file\x1b[0m] [\x1b[1m-maxSetSize\x1b[0m \x1b[3mnum\x1b[0m] [\x1b[1m-messagesAsErrors\x1b[0m \x1b[3mcodes\x1b[0m] [\x1b[1m-metadir\x1b[0m \x1b[3mpath\x1b[0m] [\x1b[1m-postCondition\x1b[0m \x1b[3mmod!oper\x1b[0m] [\x1b[1m-recover\x1b[0m \x1b[3mid\x1b[0m] [\x1b[1m-suppressMessages\x1b[0m \x1b[3mcodes\x1b[0m] [\x1b[1m-teSpecOutDir\x1b[0m \x1b[3msome-dir-name\x1b'


@pytest.mark.parametrize("verdict", ["pass", "counterexample"])
def test_native_tlc_help_prefix_is_bounded_without_changing_raw_receipt(backend_factory, verdict):
    backend, calls = backend_factory(verdict=verdict, version_banner=RECORDED_TLC_HELP_PREFIX)
    engine = v2.StateExecutionEngineV2(tlc=backend, apalache=backend_factory(runners.ApalacheBackend)[0])
    result = engine.execute(state_request())
    expected = "TLC - provides model checking and simulation of TLA+ specifications - Version 2026.07.31.184830"
    assert result.evidence.capability.tool_version == expected
    assert result.evidence.receipt["tool_version"] == RECORDED_TLC_HELP_PREFIX.strip()[:512]
    assert len(result.evidence.receipt["tool_version"]) == 512
    assert [phase for phase, *_ in calls] == ["model", "version"]
    assert result.evidence.model_check_established
    assert result.disposition is (v2.StateDisposition.SATISFIED if verdict == "pass" else v2.StateDisposition.COUNTEREXAMPLE)
    assert result.evidence.receipt["returncode"] == (0 if verdict == "pass" else 12)


@pytest.mark.parametrize("banner,expected", [
    pytest.param("fixture/1", "fixture/1", id="short-existing"),
    pytest.param("q"*256, "q"*256, id="exact-field-bound"),
    pytest.param("q"*257, "unknown", id="unrecognized-oversized"),
    pytest.param("TLC2 Version 2.20\n"+"x"*600, "TLC2 Version 2.20", id="complete-numeric-line"),
    pytest.param("\x1b[1mTLC2 Version 2.20\x1b[0m\n"+"x"*600,
                 "TLC2 Version 2.20", id="display-escapes"),
    pytest.param("TLC2 Version 2.20"+"x"*600, "unknown", id="truncated-no-complete-line"),
    pytest.param("Apalache Version 0.58.3\n"+"x"*600, "unknown", id="wrong-provider"),
    pytest.param("Unrelated Version 2.20\n"+"x"*600, "unknown", id="unrelated-banner"),
    pytest.param("TLC2 Version unknown\n"+"x"*600, "unknown", id="no-numeric-version"),
    pytest.param("TLC2 Version 2.20 "+"x"*300+"\n"+"x"*300, "unknown", id="whole-line-over-field-bound"),
])
def test_v2_version_summary_preserves_short_values_and_requires_complete_selected_banner(backend_factory, banner, expected):
    backend, calls = backend_factory(version_banner=banner)
    engine = v2.StateExecutionEngineV2(tlc=backend, apalache=backend_factory(runners.ApalacheBackend)[0])
    result = engine.execute(state_request())
    assert result.evidence.capability.tool_version == expected
    assert result.evidence.receipt["tool_version"] == banner.strip()[:512]
    assert result.evidence.model_check_established
    assert len(calls) == 2


def test_v2_version_wire_schema_still_rejects_oversized_external_metadata():
    with pytest.raises(ValueError, match="tool_version"):
        v2.StateCapabilityReceiptV2(provider=v2.StateProviderKind.TLC,
            available=True, supported_document=True,
            capability=v2.capability_for("tlc").to_dict(), tool_version="x"*257)
