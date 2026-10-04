"""V2 operation controls preserve receipts while refusing interrupted results."""
from dataclasses import replace
import hashlib
import json
import threading
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process
from ipfs_datasets_py.logic.backends.smt import execution_v2 as v2
from ipfs_datasets_py.logic.backends.smt import operation_budget as budget
from ipfs_datasets_py.logic.backends.smt.compiler import SoftwareVerificationSMTCompiler
from ipfs_datasets_py.logic.backends.smt.differential import SmtRawSolverOutput
from ipfs_datasets_py.logic.backends.z3.compiler import Z3SoftwareVerificationBackend as LegacyZ3
from ipfs_datasets_py.logic.backends.cvc5.compiler import CVC5SoftwareVerificationBackend as LegacyCVC5
from tests.integration.logic_providers.test_smt_execution_v2 import (
    _arith_vc_obligation, _sat_bool_obligation,
)
from tests.unit.logic.backends.test_smt_consumer_admission import admitted_host, bounds, obligation, phase


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(budget, "time", SimpleNamespace(monotonic=lambda: now[0]))
    return now


def request(provider="differential", mode="pinned_solver", timeout_ms=10):
    return v2.SmtExecutionRequestV2(request_id="req:v2:operation-control",
        obligation=_arith_vc_obligation(), provider=provider, mode=mode,
        bounds=bounds(timeout_ms=timeout_ms))


def engine(action=None, **controls):
    calls = []
    def runner(name):
        def execute(source, limits):
            calls.append((name, source, limits))
            if action is not None:
                action(name, len(calls))
            return SmtRawSolverOutput(stdout="unsat\n(assume_ge_one)\n",
                solver_version=name + "-trusted-fixture", elapsed_ms=0)
        return execute
    left = LegacyZ3(runner=runner("z3"), availability_probe=lambda: True)
    right = LegacyCVC5(runner=runner("cvc5"), availability_probe=lambda: True)
    return calls, v2.SmtExecutionEngineV2(z3=left, cvc5=right, **controls)


@pytest.mark.parametrize("provider", ["z3", "cvc5", "differential"])
@pytest.mark.parametrize("mode", ["pinned_solver", "hermetic_fixture"])
def test_default_budget_covers_peers_and_automatic_replay(clock, provider, mode):
    def consume(name, count):
        clock[0] += .006 if provider == "differential" or mode == "hermetic_fixture" else .011
    calls, selected = engine(consume)
    with pytest.raises(budget.ProofOperationTimeout):
        selected.execute(request(provider, mode))
    assert len(calls) == (2 if provider == "differential" or mode == "hermetic_fixture" else 1)
    assert budget.current_proof_operation() is None


@pytest.mark.parametrize("provider", ["z3", "cvc5", "differential"])
def test_explicit_budget_override_keeps_original_peer_bounds(clock, provider):
    def consume(name, count):
        clock[0] += .006
    calls, selected = engine(consume, operation_timeout_ms=5)
    req = request(provider, "hermetic_fixture")
    result = selected.execute(req, operation_timeout_ms=30)
    assert result.is_proved and result.request is req
    assert result.evidence.replay.matched
    assert [row[2] for row in calls] == [req.bounds] * (3 if provider == "differential" else 2)
    assert result.backend_result.bounds == req.bounds


@pytest.mark.parametrize("stop_after", [1, 2, 3])
def test_cancel_differential_peer_or_automatic_replay_never_returns_evidence(stop_after):
    event = threading.Event()
    def cancel(name, count):
        if count == stop_after:
            event.set()
    calls, selected = engine(cancel)
    with pytest.raises(budget.ProofOperationCancelled):
        selected.execute(request(mode="hermetic_fixture", timeout_ms=1000), cancellation=event)
    assert [row[0] for row in calls] == ["z3", "cvc5", "z3"][:stop_after]


@pytest.mark.parametrize("route", ["execute", "helper", "replay"])
def test_precancelled_calls_skip_compiler_and_backends(route):
    calls, selected = engine()
    original = selected.execute(request(timeout_ms=1000)) if route == "replay" else None
    calls.clear()
    class ForbiddenCompiler(SoftwareVerificationSMTCompiler):
        def compile(self, *args, **kwargs):
            pytest.fail("pre-cancelled V2 operation compiled an obligation")
    selected._compiler = ForbiddenCompiler()
    event = threading.Event()
    event.set()
    with pytest.raises(budget.ProofOperationCancelled):
        if route == "execute":
            selected.execute(request(timeout_ms=1000), cancellation=event)
        elif route == "helper":
            v2.execute_smt(_arith_vc_obligation(), engine=selected, cancellation=event)
        else:
            selected.replay(original, cancellation=event)
    assert not calls


def test_compiler_exception_handler_cannot_swallow_latched_deadline(clock):
    class SlowCompiler(SoftwareVerificationSMTCompiler):
        def compile(self, *args, **kwargs):
            result = super().compile(*args, **kwargs)
            clock[0] += .011
            return result
    calls, selected = engine(compiler=SlowCompiler())
    with pytest.raises(budget.ProofOperationTimeout):
        selected.execute(request())
    assert not calls and budget.current_proof_operation() is None


@pytest.mark.parametrize("route", ["mapping", "helper"])
def test_request_normalization_consumes_operation_budget(clock, monkeypatch, route):
    original = v2.SmtExecutionRequestV2.__post_init__
    def slow(self):
        original(self)
        clock[0] += .011
    calls, selected = engine()
    payload = request().to_dict()
    monkeypatch.setattr(v2.SmtExecutionRequestV2, "__post_init__", slow)
    with pytest.raises(budget.ProofOperationTimeout):
        if route == "mapping":
            selected.execute(payload)
        else:
            v2.execute_smt(_arith_vc_obligation(), engine=selected, bounds=bounds(timeout_ms=10))
    assert not calls


@pytest.mark.parametrize("stop", ["cancel", "timeout"])
def test_final_result_construction_withholds_conclusive_result(clock, monkeypatch, stop):
    original = v2.SmtExecutionResultV2.__post_init__
    event = threading.Event()
    built = []
    def late(self):
        original(self)
        built.append(self)
        if stop == "cancel":
            event.set()
        else:
            clock[0] += .011
    monkeypatch.setattr(v2.SmtExecutionResultV2, "__post_init__", late)
    calls, selected = engine()
    with pytest.raises(budget.ProofOperationCancelled if stop == "cancel" else budget.ProofOperationTimeout):
        selected.execute(request(), cancellation=event)
    assert len(calls) == 2 and built[0].is_proved


@pytest.mark.parametrize("mode", ["pinned_solver", "hermetic_fixture"])
def test_public_replay_has_one_budget_including_nested_execution(clock, mode):
    calls, selected = engine()
    result = selected.execute(request(mode=mode))
    calls.clear()
    original = selected.z3._runner
    def consume(source, limits):
        value = original(source, limits)
        clock[0] += .006
        return value
    selected.z3._runner = consume
    original_right = selected.cvc5._runner
    def consume_right(source, limits):
        value = original_right(source, limits)
        clock[0] += .006
        return value
    selected.cvc5._runner = consume_right
    with pytest.raises(budget.ProofOperationTimeout):
        selected.replay(result)
    assert [row[0] for row in calls] == ["z3", "cvc5"]


@pytest.mark.parametrize("stop", ["cancel", "timeout"])
def test_public_replay_final_matched_receipt_cannot_escape(clock, monkeypatch, stop):
    calls, selected = engine()
    result = selected.execute(request())
    event = threading.Event()
    original = v2.SmtReplayReceiptV2.__post_init__
    built = []
    def late(self):
        original(self)
        built.append(self)
        if stop == "cancel":
            event.set()
        else:
            clock[0] += .011
    monkeypatch.setattr(v2.SmtReplayReceiptV2, "__post_init__", late)
    with pytest.raises(budget.ProofOperationCancelled if stop == "cancel" else budget.ProofOperationTimeout):
        selected.replay(result, cancellation=event)
    assert built and built[-1].matched and built[-1].replay_claimed


def test_nested_operation_cannot_extend_parent(clock):
    def consume(name, count):
        clock[0] += .006
    calls, selected = engine(consume)
    with pytest.raises(budget.ProofOperationTimeout):
        with budget.proof_operation_scope(timeout_ms=10):
            selected.execute(request(timeout_ms=1000), operation_timeout_ms=1000)
    assert len(calls) == 2


@pytest.mark.parametrize("cancel_at_constructor", [False, True])
def test_constructor_and_call_signals_combine_and_instance_can_be_reused(cancel_at_constructor):
    constructor, call = threading.Event(), threading.Event()
    token = constructor if cancel_at_constructor else call
    calls, selected = engine(cancellation=constructor)
    token.set()
    with pytest.raises(budget.ProofOperationCancelled):
        selected.execute(request(timeout_ms=1000), cancellation=call)
    assert not calls
    token.clear()
    assert selected.execute(request(timeout_ms=1000), cancellation=call).is_proved
    assert len(calls) == 2


def test_shared_engine_calls_keep_independent_operation_contexts_and_owned_objects():
    barrier = threading.Barrier(2)
    cancelled = threading.Event()
    observed = {}
    def observe(name, count):
        thread = threading.current_thread().name
        observed.setdefault(thread, []).append(budget.current_proof_operation())
        if name == "z3":
            barrier.wait(timeout=3)
            if thread == "cancelled-v2":
                cancelled.set()
    calls, selected = engine(observe)
    identities = (selected._compiler, selected.z3, selected.cvc5)
    outcomes = {}
    def run(name):
        try:
            outcomes[name] = selected.execute(request(timeout_ms=3000),
                cancellation=cancelled if name == "cancelled-v2" else None)
        except BaseException as error:
            outcomes[name] = error
    threads = [threading.Thread(target=run, args=(name,), name=name) for name in ("cancelled-v2", "clean-v2")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert not any(thread.is_alive() for thread in threads)
    assert isinstance(outcomes["cancelled-v2"], budget.ProofOperationCancelled)
    assert outcomes["clean-v2"].is_proved
    assert observed["cancelled-v2"][0] is not observed["clean-v2"][0]
    assert observed["clean-v2"][0] is observed["clean-v2"][1]
    assert all(left is right for left, right in zip(identities, (selected._compiler, selected.z3, selected.cvc5)))
    assert budget.current_proof_operation() is None


@pytest.mark.parametrize("value", [False, 0, -1, 1.5, "10", float("inf"), 2**31])
def test_invalid_controls_refused_before_execution(value):
    calls, selected = engine()
    with pytest.raises(ValueError):
        selected.execute(request(), operation_timeout_ms=value)
    assert not calls


@pytest.mark.parametrize("provider", ["z3", "cvc5", "differential"])
def test_native_phases_and_automatic_replay_share_remaining_budget(admitted_host, monkeypatch, provider):
    _, _, _, calls, _ = admitted_host
    original = process.SubprocessExecutor.execute
    def consume(executor, invocation, cancellation=None):
        value = original(executor, invocation, cancellation=cancellation)
        time.sleep(.003)
        return value
    monkeypatch.setattr(process.SubprocessExecutor, "execute", consume)
    req = v2.SmtExecutionRequestV2(request_id="req:v2:admission", obligation=obligation(),
        provider=provider, mode="hermetic_fixture", bounds=bounds())
    result = v2.SmtExecutionEngineV2().execute(req, operation_timeout_ms=500)
    assert result.is_proved and result.evidence.replay.matched and result.request is req
    observed = [row["invocation"].limits.timeout_seconds for row in calls]
    assert len(observed) == (9 if provider == "differential" else 6)
    assert .5 >= observed[0] > observed[-1] > 0
    assert all(left > right for left, right in zip(observed, observed[1:]))
    assert result.backend_result.bounds == req.bounds


def test_transient_native_cancellation_is_latched_before_event_clears(admitted_host, monkeypatch):
    _, _, _, calls, _ = admitted_host
    event = threading.Event()
    original = process.SubprocessExecutor.execute
    def cancel(executor, invocation, cancellation=None):
        value = original(executor, invocation, cancellation=cancellation)
        event.set()
        assert cancellation.is_set()
        event.clear()
        return value
    monkeypatch.setattr(process.SubprocessExecutor, "execute", cancel)
    with pytest.raises(budget.ProofOperationCancelled):
        v2.SmtExecutionEngineV2().execute(v2.SmtExecutionRequestV2(request_id="req:v2:transient",
            obligation=obligation(), bounds=bounds()), cancellation=event)
    assert not event.is_set() and len(calls) == 1


@pytest.mark.parametrize("cancel", [False, True])
def test_private_pressure_queue_stops_without_launch_and_drains(admitted_host, cancel):
    owner, samples, healthy, calls, _ = admitted_host
    samples[0] = replace(healthy, available_memory_mb=32)
    event = threading.Event()
    errors = []
    def run():
        try:
            v2.SmtExecutionEngineV2().execute(v2.SmtExecutionRequestV2(request_id="req:v2:pressure",
                obligation=obligation(), bounds=bounds()), operation_timeout_ms=1000 if cancel else 50,
                cancellation=event)
        except BaseException as error:
            errors.append(error)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        until = time.monotonic() + 2
        while owner.snapshot()["proof_backoff"].get("reason") != "proof_memory_headroom":
            assert time.monotonic() < until
            time.sleep(.003)
        if cancel:
            event.set()
        thread.join(3)
        assert not thread.is_alive() and len(errors) == 1
        assert isinstance(errors[0], budget.ProofOperationCancelled if cancel else budget.ProofOperationTimeout)
        assert not calls
        state = owner.snapshot()
        assert state["active_lease_count"] == state["waiting_request_count"] == 0
    finally:
        event.set()
        thread.join(3)


def test_helper_preserves_legacy_overridden_execute_signature_and_late_gate(clock):
    calls, base = engine()
    class LegacyOverride(v2.SmtExecutionEngineV2):
        def execute(self, req):
            value = base.execute(req)
            clock[0] += .011
            return value
    selected = LegacyOverride()
    with pytest.raises(budget.ProofOperationTimeout):
        v2.execute_smt(_arith_vc_obligation(), engine=selected, bounds=bounds(timeout_ms=10))
    assert len(calls) == 3  # Default helper mode includes the primary replay.


def test_opaque_engine_typeerror_is_not_retried_and_owned_identity_is_preserved():
    seen = []
    class OpaqueEngine:
        def execute(self, req):
            seen.append((self, req, budget.current_proof_operation()))
            raise TypeError("deliberate callback failure")
    selected = OpaqueEngine()
    with pytest.raises(TypeError, match="deliberate callback failure"):
        v2.execute_smt(_arith_vc_obligation(), engine=selected, operation_timeout_ms=1000)
    assert len(seen) == 1 and seen[0][0] is selected and seen[0][2] is not None
    assert budget.current_proof_operation() is None


@pytest.mark.parametrize("provider", ["z3", "cvc5"])
@pytest.mark.parametrize("mode", ["pinned_solver", "hermetic_fixture"])
def test_single_and_immediate_replay_keep_duck_backend_contract(provider, mode):
    _, original = engine()
    underlying = getattr(original, provider)
    seen = []
    class DuckBackend:
        def run_compilation(self, compilation, *, bounds):
            seen.append((compilation, bounds, budget.current_proof_operation()))
            return underlying.run_compilation(compilation, bounds=bounds)
    supplied = DuckBackend()
    selected = v2.SmtExecutionEngineV2(**{provider: supplied})
    req = request(provider, mode, timeout_ms=1000)
    assert selected.execute(req).is_proved
    assert getattr(selected, provider) is supplied
    assert len(seen) == (2 if mode == "hermetic_fixture" else 1)
    assert all(row[1] is req.bounds and row[2] is seen[0][2] for row in seen)


@pytest.mark.parametrize("route", ["helper", "replay"])
def test_larger_call_override_survives_stock_nested_execute(clock, route):
    calls, selected = engine(operation_timeout_ms=5)
    original = selected.execute(request(), operation_timeout_ms=100) if route == "replay" else None
    calls.clear()
    for backend in (selected.z3, selected.cvc5):
        delegate = backend._runner
        def consume(source, limits, delegate=delegate):
            value = delegate(source, limits)
            clock[0] += .006
            return value
        backend._runner = consume
    if route == "helper":
        result = v2.execute_smt(_arith_vc_obligation(), engine=selected,
            bounds=bounds(timeout_ms=10), operation_timeout_ms=30)
        assert result.is_proved and result.evidence.replay.matched
        assert len(calls) == 3
    else:
        assert selected.replay(original, operation_timeout_ms=30).matched
        assert len(calls) == 2


@pytest.mark.parametrize("helper", [v2.execute_z3, v2.execute_cvc5, v2.execute_differential])
def test_alias_helpers_forward_cancellation_without_serializing_it(helper):
    calls, selected = engine()
    event = threading.Event()
    event.set()
    with pytest.raises(budget.ProofOperationCancelled):
        helper(_arith_vc_obligation(), engine=selected, operation_timeout_ms=1000, cancellation=event)
    assert not calls


def test_parent_owned_v2_replay_uses_children_without_double_root_charge(admitted_host, monkeypatch):
    from ipfs_datasets_py.logic.backends.z3 import Z3SoftwareVerificationBackend
    from ipfs_datasets_py.logic.backends.cvc5 import CVC5SoftwareVerificationBackend
    owner, _, _, _, _ = admitted_host
    observed = []
    with owner.acquire("validation", cpu_slots=1, memory_mb=128, child_process_slots=1, timeout=1) as parent:
        def execute(executor, invocation, cancellation=None):
            leases = owner.active_leases()
            roots = [row for row in leases if not row.get("parent_lease_id")]
            children = [row for row in leases if row.get("parent_lease_id")]
            assert len(roots) == len(children) == 1
            assert roots[0]["lease_id"] == parent.lease_id
            assert children[0]["parent_lease_id"] == parent.lease_id
            assert roots[0]["cpu_slots"] == 1 and roots[0]["memory_mb"] == 128
            observed.append(children[0]["lease_id"])
            stdout = "fixture-version\n" if phase(invocation) == "version" else (
                "unsat\n()\n" if phase(invocation) == "core" else "unsat\n")
            return process.RawProcessResult(returncode=0, stdout=stdout)
        monkeypatch.setattr(process.SubprocessExecutor, "execute", execute)
        selected = v2.SmtExecutionEngineV2(z3=Z3SoftwareVerificationBackend(parent_lease=parent),
            cvc5=CVC5SoftwareVerificationBackend(parent_lease=parent))
        result = selected.execute(v2.SmtExecutionRequestV2(request_id="req:v2:parent-owned",
            obligation=obligation(), bounds=bounds()), operation_timeout_ms=1000)
        assert result.is_proved and result.evidence.replay.matched
        assert len(observed) == len(set(observed)) == 9
        assert [row["lease_id"] for row in owner.active_leases()] == [parent.lease_id]


def test_hermetic_factory_accepts_runtime_controls_without_polluting_requests():
    token = threading.Event()
    token.set()
    selected = v2.hermetic_engine(operation_timeout_ms=1000, cancellation=token)
    with pytest.raises(budget.ProofOperationCancelled):
        selected.execute(request())


def _wire_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# Populated from the retained pre-edit process; execution_v2.py SHA256 08062974...
WIRE_BASELINES = {'proved:cvc5:hermetic_fixture': {'replay': '12fdad6aa59e7cd154635e07c3982c64ebeee484a26486c26c25fc2d91c0ae5b',
                                  'request': 'd012165579928323ee3dcf5bde70d04ced23ffa866f127d7551b7a7909400849',
                                  'result': '54ebffe755fa8348c3eea01edf1341dce0922a0c6837672a54ff6fa41d4aa0fb'},
 'proved:cvc5:pinned_solver': {'replay': '4abd26b27c61163154cdc7858c7f6ce121443c42373f1589a7f85a8db451adc3',
                               'request': '7073ee750a2535d7c817b9034bf5553827c8929c2d7f19e7e90ec61c8edeaf8b',
                               'result': '83811fa953e8733b29233c37cd455758f426c4e65adc4d05fecf5ac84a4ac7e9'},
 'proved:differential:hermetic_fixture': {'replay': '25ace0add89479d8a1e9da2803e22e45920abe41ac5952241a9088cb4c3d5960',
                                          'request': '6324539781f9ab5a1194939452036e759040d084574bdb853a1215f2e50fe6b4',
                                          'result': 'b888d47d482a695be22d87dc2278990406a391a5fbb9a0b8617ad6af24d21196'},
 'proved:differential:pinned_solver': {'replay': 'd06e96354971671185d2b217f51b0d2e4d363c55d0589a9f6ed99e80fcfb52ee',
                                       'request': '34dd78c7eb1f6dbef66afe71b49d689a0a2fbb6d686b2e8518038e81eaaac5d6',
                                       'result': '0d31b5754b910a6a7fc93b7f1736a950001626438a206a1a93c011290f6a8d35'},
 'proved:z3:hermetic_fixture': {'replay': '034e48ca0a34ed1876bd01e372ec24ad7a7cac98e96e3148aa2a9e5e6e728fd3',
                                'request': '39f5b5d32f8e916426f81d757e77b31d1bba78c836e13977cb4e1585cd57c3ba',
                                'result': 'f7d7051471bcf9ff5ffeeaa392e8e6d063375bb554da1fab5d5b4a2965c012d2'},
 'proved:z3:pinned_solver': {'replay': '049b626fac1c8194f52c445de313d10f65fc0eb82fbaee913095845eea13e001',
                             'request': '3a32d61da32da47668cd04636c8352933d87d0dfdd096d776199dc224362b950',
                             'result': '558aa909d0de1c42b034455df63d741ea9e5952051c21cf67febd722f8bfa067'},
 'satisfiable:cvc5:hermetic_fixture': {'replay': '182010d49fdfccb127d353b0e5877031a99c42b9fae3caabc3b9a2c5b607bd05',
                                       'request': '73f154eeaa3c772916aad22d1e213213b175ad3eac75ec8e20e56adc494026f8',
                                       'result': '33292e5cf37ade533d6501c869715aecdb666679cc349f97c7b9f9f8b8fa56dc'},
 'satisfiable:cvc5:pinned_solver': {'replay': '05a029b2b48f7be3c4f72c4d62b3300ae6c0040fb4ae0622d4f49d55ae87feee',
                                    'request': '6f3af1da58647f5f32695cfe6fa998aada595c4092ed9372778a3a88a5bdf2f3',
                                    'result': 'afb59803fbabfab3a3733cef432a9403da61c8c089feab1cdb1458a9be3e3911'},
 'satisfiable:differential:hermetic_fixture': {'replay': 'efeba85cb4ec66cedacf3fc93c8b7963feb72ecb933c4fd26c58f45f6cf3d8bf',
                                               'request': '1de7d8e755176b867738fd73f788ecdc14399740e6ad8a88da9f42c9cf83630a',
                                               'result': 'c778b3387d1cd837b4fa3ee5a0d36d124422ba39be87e317d3c493c3662a5c4e'},
 'satisfiable:differential:pinned_solver': {'replay': '766d7e9d7f68a0716382dc8124123339e4ad5cf52d576ece7ed0c6192a68f4ca',
                                            'request': '2c8041b455366867b270d480ad2575c7863a5ad2bf61ca2fc803da667f427076',
                                            'result': '202e483727ed55d19e62d67c81fd6e02d1f13f79f23a008a7de09920da0f495c'},
 'satisfiable:z3:hermetic_fixture': {'replay': 'c6ebf22e8fede62cda362cb91c3dc48b515b28d2c269655cdab76955d415a6ca',
                                     'request': '579691616677a1d3e2a7cbad41c97cf154c863eff5e33ba7bae4db6a3ad515b5',
                                     'result': '62a2e35472137be8747ed391085eb141c354433c2edd6dfccd265c76f918e018'},
 'satisfiable:z3:pinned_solver': {'replay': '09d231de8ad531bdb076d416aabd8f83011d1f990c1e43e7e8b375a566b987f1',
                                  'request': 'a7d054d08da8129e29b67881bf5ac02f1fd503d9eb2a6cdb022b6d80c766e9e3',
                                  'result': 'a1584532717314295747a7c14563f42caec369c785b4e23ff8619acd864af912'}}


@pytest.mark.parametrize("key", sorted(WIRE_BASELINES))
def test_successful_v2_wire_digests_match_pre_control_runtime(key):
    label, provider, mode = key.split(":")
    make = _arith_vc_obligation if label == "proved" else _sat_bool_obligation
    stdout = "unsat\n(assume_ge_one)\n" if label == "proved" else "sat\n(model (define-fun p () Bool true))\n"
    selected = v2.hermetic_engine(z3_stdout=stdout, cvc5_stdout=stdout,
        z3_kwargs={"solver_version": "z3-fixture-v1", "elapsed_ms": 0},
        cvc5_kwargs={"solver_version": "cvc5-fixture-v1", "elapsed_ms": 0}, operation_timeout_ms=1000)
    req = v2.SmtExecutionRequestV2(request_id="req:baseline:" + key, obligation=make(),
        provider=provider, mode=mode, source_ref_ids=("source:baseline",))
    result = selected.execute(req, operation_timeout_ms=2000)
    replay = selected.replay(result, operation_timeout_ms=2000)
    actual = {"request": req.to_dict(), "result": result.to_dict(), "replay": replay.to_dict()}
    assert {name: _wire_sha(value) for name, value in actual.items()} == WIRE_BASELINES[key]
    assert result.request is req
    assert "operation_timeout_ms" not in req.to_dict() and "cancellation" not in req.to_dict()
