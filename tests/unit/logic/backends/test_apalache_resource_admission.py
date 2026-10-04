"""Default Apalache execution has admitted, finite, caller-sized resources.

The executor is synthetic and the scheduler state belongs to each test. No JVM,
solver, installer, network operation, or shared pool is used.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process, resource_admission, registry
from ipfs_datasets_py.logic.backends.installers import state_model
from ipfs_datasets_py.logic.backends.smt import operation_budget as budget
from ipfs_datasets_py.logic.backends.tla import execution_v2 as v2, runners
from ipfs_datasets_py.logic.backends.tla.compiler import GeneratedTLAArtifacts, TLACompileBounds
from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest, ExecutionBounds, QueryKind
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources

MIB = 1024**2
PASS = "Checker reports no error\n"
COUNTEREXAMPLE = "Checker has found an error\nError: Invariant Safety is violated.\n"


def artifacts():
    return GeneratedTLAArtifacts(module_name="AdmissionCounter",
        model_text="---- MODULE AdmissionCounter ----\nEXTENDS Integers\nVARIABLE n\nInit == n = 0\nNext == n < 4 /\\ n' = n + 1\nSafety == n \\in 0..3\n====\n",
        tlc_config_text="INIT Init\nNEXT Next\nINVARIANT Safety\n",
        apalache_config_text="INIT Init\nNEXT Next\nINVARIANT Safety\n",
        source_map=(), losses=(), bounds=TLACompileBounds(max_steps=4),
        source_document_id="fixture:apalache-admission", source_kind="state_transition",
        safety_properties=("Safety",), liveness_properties=(), fairness_limitations=())


def request(memory=256*MIB, timeout_ms=2000):
    return BackendRequest(request_id="request:apalache:admission", claim_id="claim:counter",
        declaration_id="declaration:counter", claim_digest="1"*64, obligation_id="obligation:counter",
        obligation_digest="2"*64, assumption_ids=("assumption:bounded",),
        logic_family="state_transition", query_kind=QueryKind.SATISFIABILITY,
        bounds=ExecutionBounds(timeout_ms=timeout_ms, max_memory_bytes=memory,
                               max_steps=4, max_output_bytes=65536),
        payload={"artifacts": artifacts().to_dict()}, requested_backend_id="apalache")


def phase(invocation):
    return "java" if invocation.argv[-1] == "-version" else "version" if invocation.argv[-1] == "version" else "model"


@pytest.fixture(autouse=True)
def deny_host_processes(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("host process launched"))


@pytest.fixture
def host(tmp_path, monkeypatch):
    healthy = ProofHostResources(8, 8192, 8192, pid_task_limit=8192, available_pid_tasks=8192)
    current = [healthy]
    def sample():
        if isinstance(current[0], Exception):
            raise current[0]
        return current[0]
    owner = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path/"private-pool.json", proof_resource_sampler=sample,
        total_cpu_slots=2, total_memory_mb=2048, total_child_process_slots=6,
        proof_memory_headroom_mb=64, lane_reservations={}, auto_renew_leases=False,
        proof_backoff_seconds=.025, poll_interval_seconds=.002))
    monkeypatch.setattr(resource_admission, "get_global_resource_scheduler", lambda: owner)
    monkeypatch.setattr(state_model, "resolve_java_executable", lambda *a, **k: (sys.executable, "fixture"))
    monkeypatch.setattr(runners, "_production_executable_finder", lambda _: sys.executable)
    calls, workspaces, results = [], [], []
    def clean(invocation, signal):
        selected = phase(invocation)
        return process.RawProcessResult(returncode=0,
            stdout="0.58.3\n" if selected == "version" else PASS if selected == "model" else "",
            stderr='openjdk version "21.0.1"\n' if selected == "java" else "")
    action = [clean]
    def execute(self, invocation, cancellation=None):
        snapshot = owner.snapshot()
        assert snapshot["active_lease_count"] >= 1
        assert not cancellation.is_set()
        assert invocation.cwd.is_dir()
        calls.append((phase(invocation), invocation, cancellation, snapshot))
        workspaces.append(invocation.cwd)
        raw = action[0](invocation, cancellation)
        results.append(raw)
        return raw
    monkeypatch.setattr(process.SubprocessExecutor, "execute", execute)
    yield SimpleNamespace(owner=owner, healthy=healthy, current=current, calls=calls,
        action=action, clean=clean, results=results, workspaces=workspaces, tmp=tmp_path)
    snapshot = owner.snapshot()
    assert snapshot["active_lease_count"] == snapshot["waiting_request_count"] == 0
    assert all(not path.exists() for path in workspaces)


def backend(**kwargs):
    return runners.ApalacheBackend(executable=sys.executable, jvm_probe=lambda: True,
                                   lazy_install=False, **kwargs)


def until(predicate, seconds=2):
    deadline = time.monotonic()+seconds
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail("bounded fixture wait expired")
        time.sleep(.003)


@pytest.mark.parametrize("route", ["direct", "run", "registry", "v2", "helper"])
def test_all_default_execution_routes_reserve_actual_apalache_profile(host, route):
    req = request()
    if route == "direct":
        result = backend().check(artifacts(), request=req).result
    elif route == "run":
        result = backend().run(req).result
    elif route == "registry":
        attempt, result = registry.default_backend_registry().run(req, backend_id="apalache")
        assert attempt.status.value == "succeeded" and result.status.value == "unknown"
        assert result.payload["result_status"] == "satisfied"
        assert result.payload["result_authority"] == "model_check"
        retained = result.payload["result"].to_dict()
        assert retained["status"] == "satisfied" and retained["authority"] == "model_check"
        assert retained["bounds"] == req.bounds.to_dict()
        assert result.request_digest == attempt.request_digest == req.digest
        assert result.attempt_digest == attempt.digest and not result.is_theorem_proof
        assert any("without authority upgrade" in text for text in result.diagnostics)
    else:
        engine = v2.StateExecutionEngineV2(which=lambda _: sys.executable, lazy_install=False)
        result = (engine.execute(v2.StateExecutionRequestV2(request_id="request:v2:admitted", provider="apalache",
                    artifacts=artifacts(), bounds=req.bounds)) if route == "v2" else
                  v2.execute_apalache(artifacts=artifacts(), bounds=req.bounds, engine=engine))
        assert result.evidence.model_check_established and not result.evidence.is_theorem_authority
    if route in {"direct", "run"}:
        assert result.is_conclusive
    model = [row for row in host.calls if row[0] != "java"]
    assert [row[0] for row in model] == ["model", "version"]
    for _, invocation, _, state in model:
        assert (state["allocated"]["cpu_slots"],state["allocated"]["memory_mb"],
                state["allocated_child_process_slots"]) == (1,256,3)
        assert invocation.limits.resident_memory_bytes == 256*MIB
        assert invocation.limits.memory_bytes == 4*1024**3


@pytest.mark.parametrize("memory", [256*MIB, 512*MIB, 513*MIB+1, 1536*MIB])
def test_model_and_version_heap_scale_with_requested_rss_without_reserving_address_space(host, memory):
    result = backend().check(artifacts(), request=request(memory))
    assert result.result.is_conclusive
    for selected, invocation, _, state in host.calls:
        assert selected in {"model", "version"}
        assert state["allocated"]["memory_mb"] == math.ceil(memory/MIB)
        assert invocation.limits.resident_memory_bytes == memory
        assert invocation.limits.memory_bytes == max(4*1024**3,4*memory)
        flags = invocation.environment["JVM_ARGS"].split()
        assert f"-Xmx{memory//(2*MIB)}m" in flags
        assert "-Xms16m" in flags
        assert "-XX:ActiveProcessorCount=1" in flags
        assert invocation.environment["JVM_GC_ARGS"] == "-XX:+UseSerialGC"
        assert invocation.limits.max_file_bytes == 64*MIB
        assert invocation.limits.max_workspace_bytes == 128*MIB
        assert invocation.limits.max_output_bytes == 65536
    assert result.receipt.timeout_seconds == 2.0


def test_host_java_options_do_not_override_owned_heap_gc_or_cpu(host, monkeypatch):
    for variable in (*state_model.JAVA_OPTION_ENV_VARS, "JVM_ARGS", "JVM_GC_ARGS"):
        monkeypatch.setenv(variable, "-Xmx999g -XX:ActiveProcessorCount=99 -javaagent:fixture.jar")
    selected = runners.ApalacheBackend(executable=sys.executable, java_executable=sys.executable, lazy_install=False)
    assert selected.check(artifacts(), request=request()).result.is_conclusive
    for selected_phase, invocation, _, _ in host.calls:
        assert not any(variable in invocation.environment for variable in state_model.JAVA_OPTION_ENV_VARS)
        if selected_phase != "java":
            assert "999g" not in invocation.environment["JVM_ARGS"]
            assert "javaagent" not in invocation.environment["JVM_ARGS"]
            assert invocation.environment["PATH"].split(":")[0] == str(Path(sys.executable).resolve().parent)
            assert invocation.environment["HOME"] == str(invocation.cwd)
            assert invocation.environment["TMPDIR"] == str(invocation.cwd)


def test_plain_injected_runner_remains_caller_owned_and_byte_compatible(host, monkeypatch):
    calls = []
    token = threading.Event()
    def execute(invocation, cancellation):
        assert cancellation is token
        assert host.owner.snapshot()["active_lease_count"] == 0
        calls.append(invocation)
        return host.clean(invocation, cancellation)
    selected_runner = process.BoundedToolRunner(executor=execute, workspace_root=host.tmp/"plain")
    monkeypatch.setattr(resource_admission, "get_global_resource_scheduler", lambda: pytest.fail("caller-owned runner was double charged"))
    selected = backend(runner=selected_runner)
    result = selected.check(artifacts(), request=request(128*MIB), cancellation=token)
    assert selected._runner is selected_runner and result.result.is_conclusive
    assert calls[0].argv == (sys.executable,"check","--config=apalache.cfg","--length=4","--inv=Safety","--no-deadlock","AdmissionCounter.tla")
    assert calls[1].argv == (sys.executable,"version")
    assert all("JVM_ARGS" not in x.environment and "JVM_GC_ARGS" not in x.environment for x in calls)
    assert all(x.limits.max_workspace_bytes == 16*MIB and x.limits.max_file_bytes is None for x in calls)


def test_tlc_default_cpu_args_and_limits_remain_unchanged(host):
    def tlc_result(invocation, signal):
        return process.RawProcessResult(returncode=1 if invocation.argv[-1]=="-help" else 0,
            stdout="TLC Version 2.20\n" if invocation.argv[-1]=="-help" else "Model checking completed. No error has been found.\n")
    host.action[0] = tlc_result
    selected = runners.TLCBackend(executable=sys.executable, jvm_probe=lambda: True,lazy_install=False)
    assert selected.check(artifacts(),request=replace(request(128*MIB),requested_backend_id="tlc")).result.is_conclusive
    assert host.calls[0][1].argv[1:3] == ("-workers","1")
    for _, invocation, _, state in host.calls:
        assert state["allocated_child_process_slots"] == 1
        assert "JVM_ARGS" not in invocation.environment
        assert invocation.limits.max_workspace_bytes == 16*MIB


@pytest.mark.parametrize("slots", [1,2])
def test_underfunded_admitted_runner_rejected_before_constructor_java_probe(host,monkeypatch,slots):
    monkeypatch.setattr(state_model,"probe_java_runtime",lambda **k:pytest.fail("invalid owner reached Java setup"))
    owned = resource_admission.ResourceAdmittedToolRunner(scheduler=host.owner,child_process_slots=slots)
    with pytest.raises(ValueError,match="process"):
        runners.ApalacheBackend(runner=owned)
    assert host.calls == []


def test_explicit_admitted_cpu_reservation_controls_runtime_processors(host):
    owned=resource_admission.ResourceAdmittedToolRunner(scheduler=host.owner,cpu_slots=2,child_process_slots=3)
    assert backend(runner=owned).check(artifacts(),request=request()).result.is_conclusive
    for _, invocation, _, state in host.calls:
        assert state["allocated"]["cpu_slots"] == 2
        assert "-XX:ActiveProcessorCount=2" in invocation.environment["JVM_ARGS"]


def test_explicit_admitted_base_environment_cannot_override_owned_java_profile(host):
    supplied={name:"-Xmx999g -javaagent:fixture.jar" for name in
              (*state_model.JAVA_OPTION_ENV_VARS,"JVM_ARGS","JVM_GC_ARGS")}
    original=dict(supplied)
    owned=resource_admission.ResourceAdmittedToolRunner(scheduler=host.owner,child_process_slots=3,
                                                       base_environment=supplied)
    assert backend(runner=owned).check(artifacts(),request=request()).result.is_conclusive
    assert supplied==original and owned._base_environment==original
    for _,invocation,_,_ in host.calls:
        assert all(invocation.environment[name]=="" for name in state_model.JAVA_OPTION_ENV_VARS)
        assert "-Xmx128m" in invocation.environment["JVM_ARGS"]
        assert "javaagent" not in invocation.environment["JVM_ARGS"]
        assert invocation.environment["JVM_GC_ARGS"]=="-XX:+UseSerialGC"


@pytest.mark.parametrize("memory",[1,128*MIB,256*MIB-1])
def test_subminimum_requested_rss_refused_before_probe_without_increasing_budget(host,monkeypatch,memory):
    selected=backend()
    monkeypatch.setattr(selected,"_probe",lambda **k:pytest.fail("tiny resource profile reached setup"))
    req=request(memory)
    result=selected.check(artifacts(),request=req)
    assert result.receipt.status is runners.ModelCheckOutcomeStatus.UNKNOWN
    assert not result.result.is_conclusive
    assert selected._tool_version(sys.executable,bounds=req.bounds)=="unavailable"
    assert req.bounds.max_memory_bytes==memory
    assert host.calls==[]


def test_precancellation_takes_precedence_over_subminimum_memory_refusal(host,monkeypatch):
    selected=backend()
    monkeypatch.setattr(selected,"_probe",lambda **k:pytest.fail("pre-cancel reached setup"))
    token=threading.Event();token.set()
    result=selected.check(artifacts(),request=request(128*MIB),cancellation=token)
    assert result.receipt.status is runners.ModelCheckOutcomeStatus.ERROR
    assert "cancelled" in result.receipt.reason
    assert not result.result.is_conclusive and host.calls==[]


def test_oversized_input_cannot_expand_managed_workspace_budget(host):
    selected=backend()
    limits=selected._execution_limits(request().bounds,timeout_seconds=1,max_input_bytes=129*MIB)
    with pytest.raises(process.ToolProcessError,match="max_workspace_bytes"):
        selected._profile_limits(limits)
    assert host.calls==[]


def test_managed_config_and_output_directories_preserve_raw_violation_without_input_collision(host):
    original=artifacts()
    selected_artifacts=replace(original,module_name="violation",
        model_text=original.model_text.replace("AdmissionCounter","violation"))
    trace="State 1: <Initial predicate>\n/\\ n = 0\nState 2: <Next>\n/\\ n = 4\n"
    def execute(invocation,signal):
        if phase(invocation)=="model":
            assert "--config-file=apalache-runtime.json" in invocation.argv
            assert "--run-dir=apalache-run" in invocation.argv
            assert "--out-dir=apalache-out" in invocation.argv
            assert "--smt-solver=z3" in invocation.argv
            assert (invocation.cwd/"apalache-runtime.json").read_text()=="{}\n"
            assert (invocation.cwd/"violation.tla").read_text()==selected_artifacts.model_text
            directory=invocation.cwd/"apalache-run"
            directory.mkdir()
            (directory/"violation.tla").write_text(trace)
            return process.RawProcessResult(returncode=1,stdout=COUNTEREXAMPLE)
        assert Path(invocation.argv[0]).resolve()==Path(sys.executable).resolve()
        assert invocation.argv[1:]==("version",)
        assert not (invocation.cwd/"apalache-runtime.json").exists()
        return host.clean(invocation,signal)
    host.action[0]=execute
    result=backend().check(selected_artifacts,request=request())
    assert result.receipt.status is runners.ModelCheckOutcomeStatus.COUNTEREXAMPLE
    assert result.receipt.counterexample.raw==trace
    assert result.receipt.counterexample.source=="checker_counterexample_file"
    assert result.artifacts.model_text==selected_artifacts.model_text
    assert not result.receipt.unbounded_proof


def test_parent_child_execution_does_not_double_charge_or_release_foreign_owner(host):
    with host.owner.acquire("orchestration",cpu_slots=1,memory_mb=512,child_process_slots=3,timeout=0) as parent:
        with host.owner.acquire("validation",cpu_slots=1,memory_mb=64,child_process_slots=1,timeout=0) as foreign:
            owned=resource_admission.ResourceAdmittedToolRunner(parent_lease=parent,child_process_slots=3)
            assert backend(runner=owned).check(artifacts(),request=request()).result.is_conclusive
            for _,_,_,state in host.calls:
                assert state["allocated"]["memory_mb"] == 576
                assert state["allocated"]["cpu_slots"] == 2
                assert state["allocated_child_process_slots"] == 4
                assert state["active_lease_count"] == 3
            assert not parent.released and not foreign.released
            assert host.owner.snapshot()["active_lease_count"] == 2


def test_oversized_requested_rss_refused_without_native_launch_or_silent_reduction(host):
    result=backend().check(artifacts(),request=request(2048*MIB+1))
    assert not result.result.is_conclusive
    assert result.receipt.status is runners.ModelCheckOutcomeStatus.UNKNOWN
    assert host.calls == []


@pytest.mark.parametrize("changes,reason",[
    ({"available_memory_mb":32},"proof_memory_headroom"),
    ({"cpu_stall_percent":90},"proof_cpu_stall"),
    ({"available_pid_tasks":0},"proof_pid_headroom"),
    (None,"proof_resource_telemetry_unknown"),
])
def test_queued_external_pressure_cancellation_never_launches_or_leaks(host,changes,reason):
    host.current[0]=replace(host.healthy,**changes) if changes else OSError("fixture telemetry unavailable")
    signal=threading.Event(); outcomes=[]
    worker=threading.Thread(target=lambda:outcomes.append(backend().check(artifacts(),request=request(timeout_ms=3000),cancellation=signal)))
    worker.start()
    try:
        until(lambda:host.owner.snapshot()["proof_backoff"].get("reason")==reason)
        assert host.calls == []
        signal.set(); worker.join(3)
        assert not worker.is_alive() and len(outcomes)==1
        assert not outcomes[0].result.is_conclusive
    finally:
        signal.set(); worker.join(3)
    assert host.calls == []


def test_queued_deadline_expires_without_model_or_version(host):
    host.current[0]=replace(host.healthy,cpu_stall_percent=90)
    outcome=backend().check(artifacts(),request=request(timeout_ms=30))
    assert outcome.receipt.status is runners.ModelCheckOutcomeStatus.TIMED_OUT
    assert not outcome.result.is_conclusive and host.calls == []


def test_pressure_recovery_spends_shared_model_version_deadline(host):
    host.current[0]=replace(host.healthy,available_memory_mb=32)
    outcomes=[]
    worker=threading.Thread(target=lambda:outcomes.append(backend().check(artifacts(),request=request(timeout_ms=1000))))
    worker.start()
    try:
        until(lambda:host.owner.snapshot()["proof_backoff"].get("reason")=="proof_memory_headroom")
        time.sleep(.03)
        host.current[0]=host.healthy
        worker.join(3)
        assert not worker.is_alive() and len(outcomes)==1 and outcomes[0].result.is_conclusive
    finally:
        host.current[0]=host.healthy; worker.join(3)
    assert [row[0] for row in host.calls]==["model","version"]
    assert 0<host.calls[0][1].limits.timeout_seconds<.99
    assert 0<host.calls[1][1].limits.timeout_seconds<.99


@pytest.mark.parametrize("failed_phase",["model","version"])
@pytest.mark.parametrize("flag",["timed_out","cancelled","resource_exhausted","output_truncated","process_tree_terminated"])
def test_unsafe_native_lifecycle_cannot_publish_marker_or_run_followup(host,failed_phase,flag):
    def execute(invocation,signal):
        raw=host.clean(invocation,signal)
        if phase(invocation)==failed_phase:
            raw=replace(raw,stdout=COUNTEREXAMPLE,**{flag:True})
        return raw
    host.action[0]=execute
    result=backend().check(artifacts(),request=request())
    assert not result.result.is_conclusive
    assert result.receipt.counterexample is None
    assert "counterexample" not in result.result.witness.to_dict()
    assert [row[0] for row in host.calls]==(["model"] if failed_phase=="model" else ["model","version"])


def test_executor_exception_releases_admission_after_workspace_cleanup(host):
    def fail(invocation,signal):
        raise RuntimeError("synthetic executor failure")
    host.action[0]=fail
    result=backend().check(artifacts(),request=request())
    assert result.receipt.status is runners.ModelCheckOutcomeStatus.ERROR
    assert "synthetic executor failure" in result.receipt.reason
    assert not result.result.is_conclusive
    assert len(host.calls)==1
    assert host.owner.snapshot()["active_lease_count"]==0
    assert all(not p.exists() for p in host.workspaces)


def test_native_workspace_cleanup_precedes_each_owned_lease_release(host,monkeypatch):
    released=[]
    original=schedulers.ResourceLease.release
    def observe(lease):
        if lease.owner_pid==os.getpid():
            assert all(not p.exists() for p in host.workspaces)
            released.append(lease.lease_id)
        return original(lease)
    monkeypatch.setattr(schedulers.ResourceLease,"release",observe)
    assert backend().check(artifacts(),request=request()).result.is_conclusive
    assert len(released)==2 and len(set(released))==2


def test_private_parent_with_too_few_process_slots_refuses_without_reducing_profile(host):
    with host.owner.acquire("orchestration",cpu_slots=1,memory_mb=512,child_process_slots=2,timeout=0) as parent:
        owned=resource_admission.ResourceAdmittedToolRunner(parent_lease=parent,child_process_slots=3)
        result=backend(runner=owned).check(artifacts(),request=request())
        assert not result.result.is_conclusive and host.calls==[]
        assert not parent.released


@pytest.mark.parametrize("phase_to_stop",["model","version"])
def test_ambient_operation_cancellation_stays_latched_and_cleans_owned_work(host,phase_to_stop):
    token=threading.Event()
    def execute(invocation,signal):
        if phase(invocation)==phase_to_stop:
            token.set()
            assert signal.is_set()
            token.clear()
        return host.clean(invocation,signal)
    host.action[0]=execute
    with pytest.raises(budget.ProofOperationCancelled):
        backend().run(request(),cancellation=token)
    assert [row[0] for row in host.calls]==(["model"] if phase_to_stop=="model" else ["model","version"])


def test_default_owner_configuration_failure_never_uses_unadmitted_fallback(host,monkeypatch):
    def fail():
        raise schedulers.ResourceConfigurationError("fixture invalid pool")
    monkeypatch.setattr(resource_admission,"get_global_resource_scheduler",fail)
    result=backend().check(artifacts(),request=request())
    assert not result.result.is_conclusive and host.calls==[]


def test_two_concurrent_callers_never_exceed_actual_reservations(host):
    gate=threading.Barrier(2)
    def execute(invocation,signal):
        if phase(invocation)=="model":
            gate.wait(timeout=3)
        return host.clean(invocation,signal)
    host.action[0]=execute
    selected=backend()
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks=[pool.submit(selected.check,artifacts(),request=request(timeout_ms=3000)) for _ in range(2)]
        assert all(task.result(timeout=5).result.is_conclusive for task in tasks)
    assert len(host.calls)==4
    assert max(state["allocated"]["cpu_slots"] for *_,state in host.calls)==2
    assert max(state["allocated_child_process_slots"] for *_,state in host.calls)==6
    assert max(state["allocated"]["memory_mb"] for *_,state in host.calls)==512
