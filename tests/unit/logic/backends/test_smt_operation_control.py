"""Aggregate SMT cancellation/deadlines with no late conclusive publication."""
from dataclasses import replace
import importlib
import json
import pickle
import subprocess
import sys
import textwrap
import threading
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process
from ipfs_datasets_py.logic.backends.smt import differential as legacy
from ipfs_datasets_py.logic.backends.smt.compiler import SoftwareVerificationSMTCompiler
from ipfs_datasets_py.logic.backends.z3.compiler import Z3SoftwareVerificationBackend as LegacyZ3
from ipfs_datasets_py.logic.backends.cvc5.compiler import CVC5SoftwareVerificationBackend as LegacyCVC5
from ipfs_datasets_py.logic.software_verification import pipeline as legacy_pipeline
from tests.unit.logic.backends.test_smt_consumer_admission import (
    SOURCE, admitted_host, bounds, contracts, obligation, public_pipeline, public_smt,
)


@pytest.fixture
def budget():
    return importlib.import_module("ipfs_datasets_py.logic.backends.smt.operation_budget")


@pytest.fixture
def clock(budget, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(budget, "time", SimpleNamespace(monotonic=lambda: now[0]))
    return now


def peers(action=None, verdict="unsat"):
    calls = []

    def runner(name):
        def execute(source, limits):
            calls.append((name, source, limits))
            if action is not None:
                action(name, source, limits)
            return legacy.SmtRawSolverOutput(stdout=verdict + "\n" + ("()\n" if verdict == "unsat" else "(model)\n"),
                solver_version=name + "-trusted-fixture", elapsed_ms=0)
        return execute

    return calls, LegacyZ3(runner=runner("z3"), availability_probe=lambda: True), LegacyCVC5(
        runner=runner("cvc5"), availability_probe=lambda: True)


def differential(left, right, *, timeout_ms=10, **controls):
    return public_smt().run_z3_cvc5_differential(obligation(), bounds=bounds(timeout_ms=timeout_ms),
        z3_backend=left, cvc5_backend=right, **controls)


def pipeline(left, right, *, timeout_ms=10, **controls):
    return public_pipeline().SourceToVerificationPipeline(bounds=bounds(timeout_ms=timeout_ms),
        z3_backend=left, cvc5_backend=right, include_supervisor_evidence=False, **controls)


def run_source(selected, **controls):
    return selected.run(SOURCE, path="successor.py", language="python", contracts=contracts(), **controls)


@pytest.mark.parametrize("route", ["helper", "factory", "pipeline"])
def test_default_aggregate_budget_is_shared_across_both_peers(budget, clock, route):
    def advance(*args):
        clock[0] += .006
    calls, left, right = peers(advance)
    with pytest.raises(budget.ProofOperationTimeout):
        if route == "helper":
            differential(left, right)
        elif route == "factory":
            public_smt().default_z3_cvc5_verifier(z3_backend=left, cvc5_backend=right).verify(
                obligation(), bounds=bounds(timeout_ms=10))
        else:
            run_source(pipeline(left, right))
    assert [row[0] for row in calls] == ["z3", "cvc5"]
    assert budget.current_proof_operation() is None


@pytest.mark.parametrize("route", ["helper", "pipeline"])
def test_explicit_larger_aggregate_budget_preserves_declared_peer_bounds(budget, clock, route):
    def advance(*args):
        clock[0] += .006
    calls, left, right = peers(advance)
    result = (differential(left, right, operation_timeout_ms=30) if route == "helper"
              else run_source(pipeline(left, right, operation_timeout_ms=30)))
    assert result.classification.value == "agree_proved" if route == "helper" else result.proved
    assert [row[2].timeout_ms for row in calls] == [10, 10]


def test_late_first_peer_cannot_launch_second_peer(budget, clock):
    def advance(*args):
        clock[0] += .011
    calls, left, right = peers(advance)
    with pytest.raises(budget.ProofOperationTimeout):
        differential(left, right)
    assert [row[0] for row in calls] == ["z3"]


@pytest.mark.parametrize("route", ["helper", "pipeline"])
def test_precancellation_skips_compilation_and_all_backends(budget, route):
    event = threading.Event()
    event.set()
    class ForbiddenCompiler(SoftwareVerificationSMTCompiler):
        def compile(self, *args, **kwargs):
            pytest.fail("pre-cancelled operation compiled an obligation")
    calls, left, right = peers()
    with pytest.raises(budget.ProofOperationCancelled):
        if route == "helper":
            differential(left, right, compiler=ForbiddenCompiler(), cancellation=event)
        else:
            run_source(pipeline(left, right, compiler=ForbiddenCompiler(), cancellation=event))
    assert not calls


@pytest.mark.parametrize("route", ["helper", "pipeline"])
def test_slow_compilation_consumes_aggregate_budget_before_any_native_work(budget, clock, route):
    class SlowCompiler(SoftwareVerificationSMTCompiler):
        def compile(self, *args, **kwargs):
            result = super().compile(*args, **kwargs)
            clock[0] += .011
            return result
    calls, left, right = peers()
    with pytest.raises(budget.ProofOperationTimeout):
        if route == "helper":
            differential(left, right, compiler=SlowCompiler())
        else:
            run_source(pipeline(left, right, compiler=SlowCompiler()))
    assert not calls


def test_compile_only_pipeline_preserves_falsey_caller_compiler_identity_and_output():
    class FalseyCompiler(SoftwareVerificationSMTCompiler):
        def __init__(self):
            self.calls = 0

        def __bool__(self):
            return False

        def compile(self, *args, **kwargs):
            self.calls += 1
            return super().compile(*args, **kwargs)

    compiler = FalseyCompiler()
    selected = public_pipeline().SourceToVerificationPipeline(compiler=compiler,
        bounds=bounds(), execute_solvers=False, include_supervisor_evidence=False)
    assert selected.compiler is compiler
    actual = run_source(selected)
    assert compiler.calls == 1 and selected.compiler is compiler
    expected = run_source(legacy_pipeline.SourceToVerificationPipeline(compiler=compiler,
        bounds=bounds(), execute_solvers=False, include_supervisor_evidence=False))
    assert compiler.calls == 2
    assert actual.to_dict() == expected.to_dict()


def test_differential_retains_legacy_falsey_compiler_default_coalescing():
    class FalseyCompiler(SoftwareVerificationSMTCompiler):
        def __bool__(self):
            return False

        def compile(self, *args, **kwargs):
            pytest.fail("legacy differential semantics replace a falsey compiler")

    calls, left, right = peers()
    result = differential(left, right, timeout_ms=1000, compiler=FalseyCompiler())
    assert result.classification.value == "agree_proved"
    assert [row[0] for row in calls] == ["z3", "cvc5"]


@pytest.mark.parametrize("last_peer", ["z3", "cvc5"])
def test_observed_cancellation_after_peer_withholds_entire_report(budget, last_peer):
    event = threading.Event()
    def cancel(name, *args):
        if name == last_peer:
            event.set()
    calls, left, right = peers(cancel)
    with pytest.raises(budget.ProofOperationCancelled):
        differential(left, right, timeout_ms=1000, cancellation=event)
    assert [row[0] for row in calls] == (["z3"] if last_peer == "z3" else ["z3", "cvc5"])


def test_final_report_construction_deadline_is_checked_after_both_successful_peers(budget, clock, monkeypatch):
    report = legacy.SmtDifferentialVerifier._report
    constructed = []
    def late(self, *args, **kwargs):
        result = report(self, *args, **kwargs)
        constructed.append(result)
        clock[0] += .011
        return result
    monkeypatch.setattr(legacy.SmtDifferentialVerifier, "_report", late)
    calls, left, right = peers()
    with pytest.raises(budget.ProofOperationTimeout):
        differential(left, right)
    assert len(calls) == 2 and constructed[0].classification.value == "agree_proved"


@pytest.mark.parametrize("verdict", ["sat", "unsat"])
def test_pipeline_final_gate_withholds_late_disproved_and_proved_results(budget, clock, monkeypatch, verdict):
    original = legacy_pipeline.SourceToVerificationPipeline._bindings
    def late(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        clock[0] += .011
        return result
    monkeypatch.setattr(legacy_pipeline.SourceToVerificationPipeline, "_bindings", late)
    calls, left, right = peers(verdict=verdict)
    with pytest.raises(budget.ProofOperationTimeout):
        run_source(pipeline(left, right))
    assert [row[0] for row in calls] == ["z3", "cvc5"]


def test_pipeline_cannot_swallow_interruption_as_an_ordinary_error_value(budget, clock, monkeypatch):
    original = legacy_pipeline.SourceToVerificationPipeline.run
    returned = []
    def observe(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        returned.append(result)
        return result
    monkeypatch.setattr(legacy_pipeline.SourceToVerificationPipeline, "run", observe)
    def stop(*args):
        clock[0] += .011
    calls, left, right = peers(stop)
    with pytest.raises(budget.ProofOperationTimeout):
        run_source(pipeline(left, right))
    assert len(calls) == 1
    assert returned and returned[0].status.value == "error"
    assert budget.current_proof_operation() is None


@pytest.mark.parametrize("first_verdict", ["sat", "unsat"])
def test_multiple_pipeline_obligations_share_one_deadline_without_partial_conclusion(budget, clock, first_verdict):
    source = SOURCE + "\ndef successor_again(x: int) -> int:\n    return x + 1\n"
    selected_contracts = contracts() + [legacy_pipeline.ContractSpec(function_name="successor_again",
        postconditions=("result == x + 1",), contract_id="contract:again")]
    def advance(*args):
        clock[0] += .003
    calls, left, right = peers(advance, verdict=first_verdict)
    with pytest.raises(budget.ProofOperationTimeout):
        pipeline(left, right, timeout_ms=8).run(source, path="two.py", language="python", contracts=selected_contracts)
    assert [row[0] for row in calls] == ["z3", "cvc5", "z3"]


def test_nested_public_calls_cannot_extend_parent_deadline(budget, clock):
    def advance(*args):
        clock[0] += .006
    calls, left, right = peers(advance)
    with pytest.raises(budget.ProofOperationTimeout):
        with budget.proof_operation_scope(timeout_ms=10):
            differential(left, right, operation_timeout_ms=1000)
    assert len(calls) == 2
    assert budget.current_proof_operation() is None


def test_caught_nested_stop_remains_latched_in_parent_scope(budget, clock):
    def advance(*args):
        clock[0] += .011
    calls, left, right = peers(advance)
    with pytest.raises(budget.ProofOperationTimeout):
        with budget.proof_operation_scope(timeout_ms=1000):
            with pytest.raises(budget.ProofOperationTimeout):
                differential(left, right, operation_timeout_ms=10)
    assert len(calls) == 1


def test_transient_event_cleared_after_native_observation_stays_cancelled(budget, admitted_host, monkeypatch):
    _, _, _, calls, _ = admitted_host
    event = threading.Event()
    original = process.SubprocessExecutor.execute
    def observe(executor, invocation, cancellation=None):
        result = original(executor, invocation, cancellation=cancellation)
        event.set()
        assert cancellation.is_set()
        event.clear()
        return result
    monkeypatch.setattr(process.SubprocessExecutor, "execute", observe)
    with pytest.raises(budget.ProofOperationCancelled):
        public_smt().run_z3_cvc5_differential(obligation(), bounds=bounds(), cancellation=event)
    assert not event.is_set() and len(calls) == 1


def test_native_phase_deadlines_decrease_across_peer_boundary_without_rewriting_bounds(admitted_host, monkeypatch):
    _, _, _, calls, _ = admitted_host
    original = process.SubprocessExecutor.execute
    def consume(executor, invocation, cancellation=None):
        result = original(executor, invocation, cancellation=cancellation)
        time.sleep(.004)
        return result
    monkeypatch.setattr(process.SubprocessExecutor, "execute", consume)
    requested = bounds()
    report = public_smt().run_z3_cvc5_differential(obligation(), bounds=requested, operation_timeout_ms=500)
    assert report.classification.value == "agree_proved"
    observed = [row["invocation"].limits.timeout_seconds for row in calls]
    assert len(observed) == 6 and .5 >= observed[0] > observed[-1] > 0
    assert all(left > right for left, right in zip(observed, observed[1:]))
    assert report.left.result.bounds == report.right.result.bounds == requested


@pytest.mark.parametrize("cancel", [False, True])
def test_queued_pressure_consumes_aggregate_budget_and_cancellation_drains_waiter(budget, admitted_host, cancel):
    owner, current, healthy, calls, _ = admitted_host
    current[0] = replace(healthy, available_memory_mb=32)
    event = threading.Event()
    failures = []
    def run():
        try:
            public_smt().run_z3_cvc5_differential(obligation(), bounds=bounds(),
                operation_timeout_ms=1000 if cancel else 50, cancellation=event)
        except BaseException as error:
            failures.append(error)
    worker = threading.Thread(target=run)
    worker.start()
    try:
        deadline = time.monotonic() + 2
        while owner.snapshot()["proof_backoff"].get("reason") != "proof_memory_headroom":
            assert time.monotonic() < deadline
            time.sleep(.003)
        if cancel:
            event.set()
        worker.join(3)
        assert not worker.is_alive() and len(failures) == 1
        assert isinstance(failures[0], budget.ProofOperationCancelled if cancel else budget.ProofOperationTimeout)
        assert not calls
        state = owner.snapshot()
        assert state["active_lease_count"] == state["waiting_request_count"] == 0
    finally:
        event.set()
        current[0] = healthy
        worker.join(3)


def test_uncooperative_injected_callback_is_not_claimed_to_be_preempted(budget):
    completed = []
    def slow(*args):
        time.sleep(.040)
        completed.append(True)
    calls, left, right = peers(slow)
    started = time.monotonic()
    with pytest.raises(budget.ProofOperationTimeout):
        differential(left, right, timeout_ms=20)
    assert completed == [True] and len(calls) == 1
    assert time.monotonic() - started >= .040


@pytest.mark.parametrize("route", ["factory", "pipeline"])
def test_reused_instance_cancellation_does_not_poison_later_operation(budget, route):
    event = threading.Event()
    calls, left, right = peers()
    selected = (public_smt().default_z3_cvc5_verifier(z3_backend=left, cvc5_backend=right, cancellation=event)
                if route == "factory" else pipeline(left, right, timeout_ms=1000, cancellation=event))
    def invoke():
        return selected.verify(obligation(), bounds=bounds()) if route == "factory" else run_source(selected)
    event.set()
    with pytest.raises(budget.ProofOperationCancelled):
        invoke()
    assert not calls
    event.clear()
    result = invoke()
    assert result.classification.value == "agree_proved" if route == "factory" else result.proved
    assert len(calls) == 2


@pytest.mark.parametrize("route", ["factory", "pipeline"])
@pytest.mark.parametrize("cancel_constructor", [False, True])
def test_constructor_and_call_cancellation_signals_are_combined(budget, route, cancel_constructor):
    initial, per_call = threading.Event(), threading.Event()
    (initial if cancel_constructor else per_call).set()
    calls, left, right = peers()
    selected = (public_smt().default_z3_cvc5_verifier(z3_backend=left, cvc5_backend=right, cancellation=initial)
                if route == "factory" else pipeline(left, right, timeout_ms=1000, cancellation=initial))
    with pytest.raises(budget.ProofOperationCancelled):
        if route == "factory":
            selected.verify(obligation(), bounds=bounds(), cancellation=per_call)
        else:
            run_source(selected, cancellation=per_call)
    assert not calls


@pytest.mark.parametrize("route", ["factory", "pipeline"])
def test_call_timeout_override_replaces_constructor_default(budget, clock, route):
    def advance(*args):
        clock[0] += .006
    calls, left, right = peers(advance)
    selected = (public_smt().default_z3_cvc5_verifier(z3_backend=left, cvc5_backend=right, operation_timeout_ms=5)
                if route == "factory" else pipeline(left, right, operation_timeout_ms=5))
    result = (selected.verify(obligation(), bounds=bounds(timeout_ms=10), operation_timeout_ms=30)
              if route == "factory" else run_source(selected, operation_timeout_ms=30))
    assert result.classification.value == "agree_proved" if route == "factory" else result.proved
    assert len(calls) == 2


@pytest.mark.parametrize("route", ["factory", "pipeline"])
def test_shared_instance_concurrent_calls_have_separate_scopes_and_signals(budget, route):
    barrier = threading.Barrier(2)
    event = threading.Event()
    seen = {}
    outcomes = {}
    def observe(name, *args):
        thread = threading.current_thread().name
        seen.setdefault(thread, []).append(budget.current_proof_operation())
        if name == "z3":
            barrier.wait(timeout=3)
            if thread == "cancelled-call":
                event.set()
    _, left, right = peers(observe)
    selected = (public_smt().default_z3_cvc5_verifier(z3_backend=left, cvc5_backend=right)
                if route == "factory" else pipeline(left, right, timeout_ms=5000))
    def run(name):
        try:
            token = event if name == "cancelled-call" else threading.Event()
            outcomes[name] = (selected.verify(obligation(), bounds=bounds(timeout_ms=5000), cancellation=token)
                              if route == "factory" else run_source(selected, cancellation=token))
        except BaseException as error:
            outcomes[name] = error
    threads = [threading.Thread(name=name, target=run, args=(name,)) for name in ("cancelled-call", "clean-call")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert not any(thread.is_alive() for thread in threads)
    assert isinstance(outcomes["cancelled-call"], budget.ProofOperationCancelled)
    clean = outcomes["clean-call"]
    assert clean.classification.value == "agree_proved" if route == "factory" else clean.proved
    assert seen["cancelled-call"][0] is not seen["clean-call"][0]
    assert seen["clean-call"][0] is seen["clean-call"][1]
    assert budget.current_proof_operation() is None


@pytest.mark.parametrize("value", [False, 0, -1, 1.5, "10", float("inf"), float("nan")])
def test_invalid_aggregate_budget_is_rejected_before_work(budget, value):
    calls, left, right = peers()
    with pytest.raises((TypeError, ValueError)):
        differential(left, right, operation_timeout_ms=value)
    assert not calls


@pytest.mark.parametrize("value", [2**31, 2**4096], ids=["above-public-bound", "float-overflow-size"])
def test_oversized_integer_budget_fails_validation_without_float_overflow(budget, value):
    calls, left, right = peers()
    with pytest.raises(ValueError, match="operation_timeout_ms"):
        differential(left, right, operation_timeout_ms=value)
    assert not calls and budget.current_proof_operation() is None


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_nonfinite_monotonic_clock_cannot_create_an_unbounded_scope(budget, clock, value):
    clock[0] = value
    calls, left, right = peers()
    with pytest.raises(ValueError, match="finite monotonic deadline"):
        differential(left, right)
    assert not calls and budget.current_proof_operation() is None


def test_public_facades_export_the_same_typed_interruption_classes(budget):
    for package in (public_smt(), public_pipeline()):
        for name in ("ProofOperationInterrupted", "ProofOperationTimeout", "ProofOperationCancelled"):
            assert name in package.__all__ and name in dir(package)
            assert getattr(package, name) is getattr(budget, name)


@pytest.mark.parametrize("cancel", [False, True])
def test_verification_api_checks_final_receipt_inside_operation_scope(budget, clock, monkeypatch, cancel):
    from ipfs_datasets_py.logic import verification_api
    original = verification_api._check_compositional_result
    event = threading.Event()
    def late(operation, result):
        checked = original(operation, result)
        assert checked.classification.value == "agree_proved"
        if cancel:
            event.set()
        else:
            clock[0] += .011
        return checked
    monkeypatch.setattr(verification_api, "_check_compositional_result", late)
    calls, left, right = peers()
    with pytest.raises(budget.ProofOperationCancelled if cancel else budget.ProofOperationTimeout):
        verification_api.run_z3_cvc5_differential(obligation(), bounds=bounds(timeout_ms=10),
            z3_backend=left, cvc5_backend=right, cancellation=event)
    assert len(calls) == 2


@pytest.mark.parametrize("cancel", [False, True])
def test_interruption_metadata_is_typed_and_context_is_restored(budget, clock, cancel):
    event = threading.Event()
    def stop(*args):
        if cancel:
            event.set()
        else:
            clock[0] += .011
    calls, left, right = peers(stop)
    with pytest.raises(budget.ProofOperationInterrupted) as caught:
        differential(left, right, cancellation=event)
    details = caught.value.to_dict()
    assert details["kind"] == ("cancelled" if cancel else "timeout")
    assert isinstance(details["phase"], str) and details["phase"]
    assert details["timeout_ms"] == 10
    assert details["elapsed_ms"] >= 0
    assert len(calls) == 1 and budget.current_proof_operation() is None


@pytest.mark.parametrize("name,kind", [
    ("ProofOperationInterrupted", "timeout"),
    ("ProofOperationTimeout", "timeout"),
    ("ProofOperationCancelled", "cancelled"),
])
def test_typed_interruption_pickle_preserves_class_metadata_and_message(budget, name, kind):
    original = getattr(budget, name)(kind=kind, phase="after peer", elapsed_ms=17, timeout_ms=10)
    restored = pickle.loads(pickle.dumps(original))
    assert type(restored) is type(original)
    assert restored.to_dict() == original.to_dict()
    assert restored.args == original.args and str(restored) == str(original)


def test_process_pool_delivers_typed_interruption_and_remains_usable(tmp_path):
    script = tmp_path / "operation_exception_worker.py"
    script.write_text(textwrap.dedent('''
        import json
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        from ipfs_datasets_py.logic.backends.smt.operation_budget import ProofOperationCancelled

        def stopped():
            raise ProofOperationCancelled(kind="cancelled", phase="worker callback",
                                          elapsed_ms=7, timeout_ms=50)

        if __name__ == "__main__":
            with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn")) as pool:
                try:
                    pool.submit(stopped).result(timeout=5)
                except ProofOperationCancelled as error:
                    assert type(error) is ProofOperationCancelled
                    details = error.to_dict()
                else:
                    raise AssertionError("worker cancellation was lost")
                assert pool.submit(abs, -7).result(timeout=5) == 7
            print(json.dumps(details))
    '''))
    completed = subprocess.run([sys.executable, str(script)], text=True, capture_output=True,
                               timeout=15, check=True)
    assert json.loads(completed.stdout.strip().splitlines()[-1]) == {
        "kind": "cancelled", "phase": "worker callback", "elapsed_ms": 7, "timeout_ms": 50}
