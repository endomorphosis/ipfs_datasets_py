"""Default SMT consumers cross actual private admission boundaries.

Synthetic executor observations isolate routing, accounting and authority tests;
native semantic checks are separately retained in the qualification benchmark.
"""
from dataclasses import replace
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import pytest

from ipfs_datasets_py.logic.backends import process, resource_admission
from ipfs_datasets_py.logic.backends.smt import differential as legacy_differential
from ipfs_datasets_py.logic.backends.smt.compiler import SmtFeature, SmtObligation, SmtQueryMode, term_true
from ipfs_datasets_py.logic.backends.z3.compiler import Z3SoftwareVerificationBackend as LegacyZ3
from ipfs_datasets_py.logic.backends.cvc5.compiler import CVC5SoftwareVerificationBackend as LegacyCVC5
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.logic.software_verification import pipeline as legacy_pipeline
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources

ROOT = Path(__file__).resolve().parents[4]
MIB = 1024**2
SOURCE = "def successor(x: int) -> int:\n    return x + 1\n"
SMT_SOURCE = "(set-logic QF_UF)\n(assert false)\n(check-sat)\n"
CONCLUSIVE = {"proved", "disproved", "satisfiable", "unsatisfiable"}


def bounds(**updates):
    return ExecutionBounds(**{"timeout_ms": 1500, "max_memory_bytes": 128 * MIB,
                              "max_output_bytes": 4096, **updates})


def obligation():
    return SmtObligation(obligation_id="obl:consumer-admission", goal=term_true(),
        features=(SmtFeature.EQUALITY,), query_mode=SmtQueryMode.THEOREM_BY_NEGATION,
        request_model=True, request_unsat_core=True)


def contracts():
    return [legacy_pipeline.ContractSpec(function_name="successor",
        postconditions=("result == x + 1",), contract_id="contract:successor")]


def public_smt():
    return importlib.import_module("ipfs_datasets_py.logic.backends.smt")


def public_pipeline():
    return importlib.import_module("ipfs_datasets_py.logic.software_verification")


def version(argv):
    return "-version" in argv or "--version" in argv


def source_of(invocation):
    value = invocation.stdin or ""
    return value.decode() if isinstance(value, bytes) else value


def phase(invocation):
    if version(invocation.argv):
        return "version"
    source = source_of(invocation)
    return "model" if "(get-model)" in source else "core" if "(get-unsat-core)" in source else "query"


@pytest.fixture
def admitted_host(tmp_path, monkeypatch):
    healthy = ProofHostResources(8, 8192, 8192, pid_task_limit=8192, available_pid_tasks=8192)
    sample = [healthy]
    owner = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "consumer-pool.json", proof_resource_sampler=lambda: sample[0],
        total_cpu_slots=2, total_memory_mb=512, total_child_process_slots=2,
        proof_memory_headroom_mb=64, lane_reservations={}, auto_renew_leases=False,
        proof_backoff_seconds=.025, poll_interval_seconds=.002))
    monkeypatch.setattr(resource_admission, "get_global_resource_scheduler", lambda: owner)
    monkeypatch.setattr(shutil, "which", lambda *args, **kwargs: sys.executable)
    calls = []
    response = {"verdict": "unsat", "failure": None}

    def execute(executor, invocation, cancellation=None):
        active = owner.active_leases()
        assert len(active) == 1
        lease = active[0]
        assert lease["cpu_slots"] == lease["child_process_slots"] == 1
        assert lease["memory_mb"] == 128
        assert invocation.limits.memory_bytes == invocation.limits.resident_memory_bytes == 128 * MIB
        assert 0 < invocation.limits.timeout_seconds <= 1.5
        assert not cancellation.is_set()
        calls.append({"phase": phase(invocation), "invocation": invocation,
                      "lease_id": lease["lease_id"]})
        if phase(invocation) == "version":
            stdout = "consumer-fixture/1\n"
        elif phase(invocation) == "core":
            stdout = "unsat\n()\n"
        elif phase(invocation) == "model":
            stdout = "sat\n(model)\n"
        else:
            stdout = response["verdict"] + "\n"
        result = process.RawProcessResult(returncode=0, stdout=stdout)
        return replace(result, **response["failure"]) if response["failure"] else result

    monkeypatch.setattr(process.SubprocessExecutor, "execute", execute)
    yield owner, sample, healthy, calls, response
    state = owner.snapshot()
    assert state["active_lease_count"] == state["waiting_request_count"] == 0


def run_consumer(route, *, selected_bounds=None, **injections):
    chosen = selected_bounds or bounds()
    if route == "differential":
        return public_smt().run_z3_cvc5_differential(obligation(), bounds=chosen, **injections)
    if route in {"api", "api-method"}:
        from ipfs_datasets_py.logic import verification_api
        api = verification_api if route == "api" else verification_api.LogicVerificationAPI()
        return api.run_z3_cvc5_differential(obligation(), bounds=chosen, **injections)
    if route.startswith("pipeline"):
        options = {"bounds": chosen, "include_supervisor_evidence": False, **injections}
        if route == "pipeline-helper":
            return public_pipeline().run_source_to_verification_pipeline(SOURCE, path="successor.py",
                language="python", contracts=contracts(), revision="test:consumer", **options)
        return public_pipeline().SourceToVerificationPipeline(**options).run(SOURCE, path="successor.py",
            language="python", contracts=contracts(), revision="test:consumer")
    from ipfs_datasets_py.logic.parsers.classical_adapters import ClassicalBackendAdapter
    solver = route.split("-", 1)[1]
    return ClassicalBackendAdapter(**injections).run_smt(SMT_SOURCE, route=solver, bounds=chosen)


def assert_no_conclusion(result, route):
    if route.startswith("pipeline"):
        assert not result.proved and not result.disproved
        reports = [item.differential for item in result.obligation_results]
        assert reports
    elif route.startswith("classical"):
        assert result.status.value not in CONCLUSIVE
        assert not result.receipt.proof_safe and not result.receipt.counterexample_safe
        return
    else:
        reports = [result]
    for report in reports:
        assert report.left.result.status.value not in CONCLUSIVE
        assert report.right.result.status.value not in CONCLUSIVE


@pytest.mark.parametrize("route", ["differential", "api", "api-method", "pipeline", "pipeline-helper"])
@pytest.mark.parametrize("verdict", ["sat", "unsat"])
def test_public_consumer_defaults_admit_all_query_artifact_and_version_phases(admitted_host, route, verdict):
    _, _, _, calls, response = admitted_host
    response["verdict"] = verdict
    result = run_consumer(route)
    if route.startswith("pipeline"):
        assert result.proved is (verdict == "unsat")
        assert result.disproved is (verdict == "sat")
        assert len(result.obligation_results) == 1
        report = result.obligation_results[0].differential
        assert result.bindings.source.path == "successor.py"
        assert result.bindings.source.content_sha256 == hashlib.sha256(SOURCE.encode()).hexdigest()
        assert result.bindings.source.source_revision == "test:consumer"
        assert result.bindings.translation_receipt_ids
    else:
        report = result
    expected = "agree_proved" if verdict == "unsat" else "agree_disproved"
    assert report.classification.value == expected
    assert report.left.compilation.script.digest == report.right.compilation.script.digest == report.script_digest
    assert [row["phase"] for row in calls] == ["query", "core" if verdict == "unsat" else "model", "version"] * 2
    assert len({row["lease_id"] for row in calls}) == 6


@pytest.mark.parametrize("solver", ["z3", "cvc5"])
@pytest.mark.parametrize("verdict", ["sat", "unsat"])
def test_classical_defaults_admit_without_promoting_theorem_authority(admitted_host, solver, verdict):
    _, _, _, calls, response = admitted_host
    response["verdict"] = verdict
    result = run_consumer("classical-" + solver)
    assert result.status.value == ("unsatisfiable" if verdict == "unsat" else "satisfiable")
    assert result.authority.value == "satisfiability"
    assert result.receipt.proof_safe is (verdict == "unsat")
    assert result.receipt.counterexample_safe is (verdict == "sat")
    assert result.source_binding.request_digest == result.backend_request.digest
    assert [row["phase"] for row in calls] == ["query", "version"]
    assert len({row["lease_id"] for row in calls}) == 2


@pytest.mark.parametrize("route", ["differential", "api", "pipeline", "classical-z3"])
@pytest.mark.parametrize("failure", [{"returncode": 7}, {"output_truncated": True}, {"resource_exhausted": True}])
def test_unsafe_native_unsat_never_gains_consumer_authority(admitted_host, route, failure):
    _, _, _, calls, response = admitted_host
    response["failure"] = failure
    result = run_consumer(route)
    assert_no_conclusion(result, route)
    assert [row["phase"] for row in calls] == ["query"] * (1 if route.startswith("classical") else 2)


def test_compile_only_public_pipeline_preserves_exact_legacy_result_without_admission(monkeypatch):
    monkeypatch.setattr(resource_admission, "get_global_resource_scheduler", lambda: pytest.fail("compile-only admission"))
    monkeypatch.setattr(process.SubprocessExecutor, "execute", lambda *args, **kwargs: pytest.fail("compile-only launch"))
    kwargs = {"execute_solvers": False, "bounds": bounds(), "include_supervisor_evidence": False}
    selected = public_pipeline().SourceToVerificationPipeline(**kwargs)
    legacy = legacy_pipeline.SourceToVerificationPipeline(**kwargs)
    args = {"path": "successor.py", "language": "python", "contracts": contracts(), "revision": "test:consumer"}
    actual = selected.run(SOURCE, **args)
    expected = legacy.run(SOURCE, **args)
    assert actual.to_dict() == expected.to_dict()
    assert selected.z3_backend is selected.cvc5_backend is None
    assert not actual.proved and not actual.disproved
    assert actual.obligation_results and all(item.differential is None for item in actual.obligation_results)


def legacy_pair():
    calls = []

    def raw(source, chosen):
        calls.append((source, chosen))
        return legacy_differential.SmtRawSolverOutput(stdout="unsat\n()\n", solver_version="trusted-legacy/1")

    return calls, LegacyZ3(runner=raw, availability_probe=lambda: True), LegacyCVC5(runner=raw, availability_probe=lambda: True)


@pytest.mark.parametrize("route", ["differential", "api", "pipeline", "pipeline-helper"])
def test_explicit_legacy_backends_keep_caller_ownership_and_results(monkeypatch, route):
    monkeypatch.setattr(resource_admission, "get_global_resource_scheduler", lambda: pytest.fail("injected backend double charged"))
    calls, left, right = legacy_pair()
    result = run_consumer(route, z3_backend=left, cvc5_backend=right)
    if route.startswith("pipeline"):
        assert result.proved
    else:
        assert result.classification.value == "agree_proved"
    assert len(calls) == 2
    verifier = public_smt().default_z3_cvc5_verifier(z3_backend=left, cvc5_backend=right)
    assert verifier.left is left and verifier.right is right


def test_default_factories_preserve_old_signatures_and_use_only_missing_defaults(monkeypatch):
    from ipfs_datasets_py.logic.backends.z3 import Z3SoftwareVerificationBackend
    from ipfs_datasets_py.logic.backends.cvc5 import CVC5SoftwareVerificationBackend
    monkeypatch.setattr(resource_admission, "get_global_resource_scheduler", lambda: pytest.fail("construction touched pool"))
    for name in ("default_z3_cvc5_verifier", "run_z3_cvc5_differential"):
        def callable_shape(function):
            return {p.name: (p.kind, p.default) for p in inspect.signature(function).parameters.values()}
        current = callable_shape(getattr(public_smt(), name))
        original = callable_shape(getattr(legacy_differential, name))
        assert {key: current[key] for key in original} == original
        assert {key: current[key] for key in current.keys() - original.keys()} == {
            "operation_timeout_ms": (inspect.Parameter.KEYWORD_ONLY, None),
            "cancellation": (inspect.Parameter.KEYWORD_ONLY, None),
        }
    _, left, _ = legacy_pair()
    verifier = public_smt().default_z3_cvc5_verifier(z3_backend=left)
    assert verifier.left is left and type(verifier.right) is CVC5SoftwareVerificationBackend
    selected = public_pipeline().SourceToVerificationPipeline(z3_backend=left, include_supervisor_evidence=False)
    assert selected.z3_backend is left and type(selected.cvc5_backend) is CVC5SoftwareVerificationBackend
    assert type(public_pipeline().SourceToVerificationPipeline().z3_backend) is Z3SoftwareVerificationBackend


@pytest.mark.parametrize("route", ["differential", "pipeline"])
def test_one_injected_legacy_peer_keeps_ownership_while_missing_peer_is_admitted(admitted_host, route):
    _, _, _, phases, _ = admitted_host
    raw_calls, left, _ = legacy_pair()
    result = run_consumer(route, z3_backend=left)
    assert result.proved if route == "pipeline" else result.classification.value == "agree_proved"
    assert len(raw_calls) == 1
    assert [row["phase"] for row in phases] == ["query", "core", "version"]


def test_pressure_before_default_differential_query_backs_off_and_recovers(admitted_host):
    owner, current, healthy, calls, _ = admitted_host
    current[0] = replace(healthy, available_memory_mb=32)
    results = []
    thread = threading.Thread(target=lambda: results.append(run_consumer("differential")))
    thread.start()
    try:
        deadline = time.monotonic() + 1
        while owner.snapshot()["proof_backoff"].get("reason") != "proof_memory_headroom":
            assert time.monotonic() < deadline
            time.sleep(.003)
        assert not calls
        current[0] = healthy
        thread.join(3)
        assert not thread.is_alive() and results[0].classification.value == "agree_proved"
    finally:
        current[0] = healthy
        thread.join(3)
    assert len(calls) == 6


@pytest.mark.parametrize("route", ["differential", "api", "pipeline"])
def test_injected_admitted_cancellation_stops_all_default_consumer_phases(admitted_host, route):
    from ipfs_datasets_py.logic.backends.z3 import Z3SoftwareVerificationBackend
    from ipfs_datasets_py.logic.backends.cvc5 import CVC5SoftwareVerificationBackend
    _, _, _, calls, _ = admitted_host
    cancelled = threading.Event()
    cancelled.set()
    result = run_consumer(route,
        z3_backend=Z3SoftwareVerificationBackend(cancellation=cancelled),
        cvc5_backend=CVC5SoftwareVerificationBackend(cancellation=cancelled))
    assert_no_conclusion(result, route)
    assert not calls


def test_new_public_namespaces_stay_lazy_without_mutating_legacy_modules():
    source = r'''
import importlib, json, sys
sys.path.insert(0, sys.argv[1])
def deny_launch(event, args):
    if event == "subprocess.Popen":
        raise AssertionError("cold namespace or constructor launched process")
sys.addaudithook(deny_launch)
smt = importlib.import_module("ipfs_datasets_py.logic.backends.smt")
sv = importlib.import_module("ipfs_datasets_py.logic.software_verification")
assert "ipfs_datasets_py.logic.backends.smt.admitted_differential" not in sys.modules
assert "ipfs_datasets_py.logic.software_verification.admitted_pipeline" not in sys.modules
legacy = importlib.import_module("ipfs_datasets_py.logic.software_verification.pipeline")
legacy_diff = importlib.import_module("ipfs_datasets_py.logic.backends.smt.differential")
assert "ipfs_datasets_py.logic.software_verification.admitted_pipeline" not in sys.modules
assert "ipfs_datasets_py.logic.backends.smt.admitted_differential" not in sys.modules
from ipfs_datasets_py.logic.backends import resource_admission
def forbidden():
    raise AssertionError("cold constructor touched global scheduler")
resource_admission.get_global_resource_scheduler = forbidden
verifier = smt.default_z3_cvc5_verifier()
pipeline = sv.SourceToVerificationPipeline()
assert type(verifier.left).__module__.endswith(".smt.admitted")
assert type(verifier.right).__module__.endswith(".smt.admitted")
assert isinstance(pipeline, legacy.SourceToVerificationPipeline)
assert type(pipeline) is not legacy.SourceToVerificationPipeline
assert legacy.SourceToVerificationPipeline().z3_backend is None
assert legacy.run_z3_cvc5_differential is legacy_diff.run_z3_cvc5_differential
assert type(legacy_diff.default_z3_cvc5_verifier().left).__module__.endswith(".z3.compiler")
assert sv.ContractSpec is legacy.ContractSpec
assert smt.SmtDifferentialVerifier is legacy_diff.SmtDifferentialVerifier
assert "subprocess_smt_runner" not in smt.__all__
print(json.dumps({"launches": 0, "legacy_modules_unchanged": True}))
'''
    result = subprocess.run([sys.executable, "-I", "-B", "-c", source, str(ROOT)],
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {"launches": 0, "legacy_modules_unchanged": True}
